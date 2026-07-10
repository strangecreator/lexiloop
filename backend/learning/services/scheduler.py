from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from learning.models import CardSchedule, ReviewLog, UserProfile


def _steps(raw, fallback):
    result = []
    for value in raw if isinstance(raw, list) else []:
        try:
            value = max(1, int(value))
        except (TypeError, ValueError):
            continue
        result.append(value)
    return result or fallback


def _set_step(schedule, *, state, steps, index, now):
    schedule.state = state
    schedule.step_index = min(index, len(steps) - 1)
    schedule.due_at = now + timedelta(minutes=steps[schedule.step_index])
    schedule.interval_days = 0


def apply_rating(schedule: CardSchedule, rating: int, profile: UserProfile, now=None) -> CardSchedule:
    """An Anki/SM-2-inspired state machine. Rating: 1 Again, 2 Hard, 3 Good, 4 Easy."""
    now = now or timezone.now()
    learning = _steps(profile.learning_steps_minutes, [1, 10])
    relearning = _steps(profile.relearning_steps_minutes, [10])
    rating = max(1, min(4, int(rating)))

    if schedule.state == CardSchedule.State.NEW:
        if rating == ReviewLog.Rating.AGAIN:
            _set_step(schedule, state=CardSchedule.State.LEARNING, steps=learning, index=0, now=now)
        elif rating == ReviewLog.Rating.HARD:
            _set_step(schedule, state=CardSchedule.State.LEARNING, steps=learning, index=0, now=now)
            schedule.due_at = now + timedelta(minutes=max(1, round(learning[0] * 1.5)))
        elif rating == ReviewLog.Rating.GOOD and len(learning) > 1:
            _set_step(schedule, state=CardSchedule.State.LEARNING, steps=learning, index=1, now=now)
        else:
            schedule.state = CardSchedule.State.REVIEW
            schedule.interval_days = profile.easy_interval_days if rating == 4 else profile.graduating_interval_days
            schedule.due_at = now + timedelta(days=schedule.interval_days)
            schedule.step_index = 0

    elif schedule.state in {CardSchedule.State.LEARNING, CardSchedule.State.RELEARNING}:
        steps = relearning if schedule.state == CardSchedule.State.RELEARNING else learning
        if rating == 1:
            _set_step(schedule, state=schedule.state, steps=steps, index=0, now=now)
        elif rating == 2:
            current = steps[min(schedule.step_index, len(steps) - 1)]
            schedule.due_at = now + timedelta(minutes=max(1, round(current * 1.5)))
        elif rating == 4 or schedule.step_index + 1 >= len(steps):
            schedule.state = CardSchedule.State.REVIEW
            base = max(profile.graduating_interval_days, schedule.interval_days)
            schedule.interval_days = base * (profile.easy_bonus if rating == 4 else 1.0)
            schedule.due_at = now + timedelta(days=schedule.interval_days)
            schedule.step_index = 0
        else:
            schedule.step_index += 1
            schedule.due_at = now + timedelta(minutes=steps[schedule.step_index])

    else:  # review
        old = max(schedule.interval_days, profile.graduating_interval_days)
        if rating == 1:
            schedule.lapses += 1
            schedule.ease_factor = max(profile.minimum_ease, schedule.ease_factor - 0.2)
            schedule.interval_days = max(profile.graduating_interval_days, old * profile.lapse_multiplier)
            _set_step(schedule, state=CardSchedule.State.RELEARNING, steps=relearning, index=0, now=now)
        elif rating == 2:
            schedule.ease_factor = max(profile.minimum_ease, schedule.ease_factor - 0.15)
            schedule.interval_days = max(profile.graduating_interval_days, old * profile.hard_multiplier)
            schedule.due_at = now + timedelta(days=schedule.interval_days)
        elif rating == 3:
            schedule.interval_days = max(profile.graduating_interval_days, old * schedule.ease_factor)
            schedule.due_at = now + timedelta(days=schedule.interval_days)
        else:
            schedule.ease_factor += 0.15
            schedule.interval_days = max(profile.easy_interval_days, old * schedule.ease_factor * profile.easy_bonus)
            schedule.due_at = now + timedelta(days=schedule.interval_days)

    schedule.repetitions += 1
    schedule.last_reviewed_at = now
    schedule.save()
    return schedule


def priority(schedule: CardSchedule, now=None) -> float:
    now = now or timezone.now()
    overdue_hours = max(0.0, (now - schedule.due_at).total_seconds() / 3600)
    bonus = {
        CardSchedule.State.RELEARNING: 300,
        CardSchedule.State.LEARNING: 250,
        CardSchedule.State.REVIEW: 150,
        CardSchedule.State.NEW: 50,
    }.get(schedule.state, 0)
    return bonus + overdue_hours + 12 * schedule.lapses - 0.01 * schedule.interval_days


def automatic_rating(*, accepted: bool, response_ms: int, direction: str, judge_score: int | None = None, profile: UserProfile | None = None, hint_revealed_letters: int = 0, hint_total_letters: int = 0) -> int:
    """Choose the internal Anki-style rating from correctness and recall speed.

    The learner never selects Again/Hard/Good/Easy manually. Incorrect or
    revealed answers are always ``Again``. Correct answers are classified using
    direction-specific timing bands because writing a definition naturally takes
    longer than recalling a word. A barely accepted semantic answer is capped at
    ``Hard`` and a good-but-not-exact answer is capped at ``Good``.
    """
    if not accepted:
        return ReviewLog.Rating.AGAIN

    try:
        milliseconds = max(0, min(int(response_ms), 60 * 60 * 1000))
    except (TypeError, ValueError):
        milliseconds = 0

    # A missing timer should not be interpreted as an impossibly fast answer.
    if milliseconds <= 0:
        base = ReviewLog.Rating.GOOD
    else:
        seconds = milliseconds / 1000
        if direction == ReviewLog.Direction.DEFINITION_TO_TERM:
            easy_seconds = getattr(profile, 'definition_to_term_easy_seconds', 6)
            good_seconds = getattr(profile, 'definition_to_term_good_seconds', 18)
        else:
            easy_seconds = getattr(profile, 'term_to_definition_easy_seconds', 12)
            good_seconds = getattr(profile, 'term_to_definition_good_seconds', 35)
        easy_seconds = max(1, int(easy_seconds))
        good_seconds = max(easy_seconds + 1, int(good_seconds))
        if seconds < easy_seconds:
            base = ReviewLog.Rating.EASY
        elif seconds < good_seconds:
            base = ReviewLog.Rating.GOOD
        else:
            base = ReviewLog.Rating.HARD

    if judge_score is not None:
        try:
            score = int(judge_score)
        except (TypeError, ValueError):
            score = None
        if score is not None:
            if score <= 5:
                base = min(base, ReviewLog.Rating.HARD)
            elif score == 6:
                base = min(base, ReviewLog.Rating.GOOD)

    if direction == ReviewLog.Direction.DEFINITION_TO_TERM and hint_total_letters > 0:
        revealed = max(0, min(int(hint_revealed_letters), int(hint_total_letters)))
        ratio = revealed / max(1, int(hint_total_letters))
        if ratio > 0.40:
            base = ReviewLog.Rating.AGAIN
        elif ratio > 0.20:
            base = min(base, ReviewLog.Rating.HARD)
        elif revealed > 0:
            base = min(base, ReviewLog.Rating.GOOD)
    return int(base)
