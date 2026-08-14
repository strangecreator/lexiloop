from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet
from django.utils import timezone

from learning.models import CardSchedule, Flashcard, ReviewLog, UserProfile
from learning.services.scheduler import priority

# Relearning first, then learning, then reviews. New cards are placed by
# ``new_card_pacing`` rather than by this rank.
NON_NEW_RANK = {
    CardSchedule.State.RELEARNING: 3,
    CardSchedule.State.LEARNING: 2,
    CardSchedule.State.REVIEW: 1,
}


_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15
_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_TWO_POW_53 = float(1 << 53)


def _fnv1a64(text: str) -> int:
    value = _FNV_OFFSET
    for byte in text.encode('utf-8'):
        value = ((value ^ byte) * _FNV_PRIME) & _MASK64
    return value


def day_seed(username: str, day) -> int:
    """A seed that is stable for one learner for one day, and portable.

    The Android offline scheduler derives the same seed from the same inputs, so
    both sides place new cards identically without exchanging any state.
    """
    return (_fnv1a64(username) ^ ((day.toordinal() * _GOLDEN) & _MASK64)) & _MASK64


def _u01(seed: int, index: int) -> float:
    """splitmix64, used as a hash rather than a stream.

    Deliberately not random.Random: this exact arithmetic is reproducible in
    Kotlin, which a Mersenne Twister stream is not.
    """
    value = (seed + _GOLDEN * (index + 1)) & _MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
    value ^= value >> 31
    return (value >> 11) / _TWO_POW_53


def new_card_offsets(count: int, *, pacing: float, seed: int) -> list[float]:
    """Where each of the day's new cards sits, as a fraction of the session.

    ``pacing`` is the single knob: it is the *mean earliness* of a new card, so
    the average new card lands at ``1 - pacing`` through the day.

    Positions are drawn from the power-function family (a Beta with one unit
    shape), which is the simplest distribution that spans exactly what is
    wanted and stays closed-form — no incomplete-beta inverse to keep in step
    across two languages:

    * ``0.0`` — every new card at 1.0, i.e. strictly after the reviews.
    * ``0.25`` — density rising towards the end; new cards cluster late but can
      appear at any point.
    * ``0.5`` — uniform. New cards are scattered evenly across the session.
    * ``0.75`` — the mirror image: clustered early, still scattered.
    * ``1.0`` — every new card at 0.0, i.e. strictly before the reviews.

    The draw is a hash of (learner, day, index), so it is random-looking but
    reproduces exactly on every recomputation — the queue is rebuilt on every
    request and must not reshuffle underneath the learner.
    """
    if count <= 0:
        return []
    pacing = min(1.0, max(0.0, float(pacing)))
    # The extremes are promises the UI makes, so they are exact, not merely very
    # concentrated distributions.
    if pacing <= 0.005:
        return [1.0] * count
    if pacing >= 0.995:
        return [0.0] * count
    if pacing <= 0.5:
        exponent = pacing / (1.0 - pacing)
        values = [_u01(seed, index) ** exponent for index in range(count)]
    else:
        exponent = (1.0 - pacing) / pacing
        values = [1.0 - (1.0 - _u01(seed, index)) ** exponent for index in range(count)]
    values.sort()
    return values


@dataclass(frozen=True)
class DueBreakdown:
    non_new: int
    new: int
    remaining_new_slots: int

    @property
    def available(self) -> int:
        return self.non_new + min(self.new, self.remaining_new_slots)


def introduced_new_today(*, user, day=None) -> int:
    """How many new cards were introduced today. A card counts as introduced
    only when a review log records that its previous state was NEW."""
    day = day or timezone.localdate()
    return ReviewLog.objects.filter(
        user=user,
        created_at__date=day,
        previous_state=CardSchedule.State.NEW,
    ).count()


def reviews_today(*, user, day=None) -> int:
    """Every card shown today, including repeats of the same card."""
    day = day or timezone.localdate()
    return ReviewLog.objects.filter(user=user, created_at__date=day).count()


def remaining_new_slots(*, user, profile: UserProfile, day=None) -> int:
    """Return how many new cards may still be introduced today.

    The scheduler's new-card limit is global per user.
    """
    return max(0, int(profile.daily_new_limit) - introduced_new_today(user=user, day=day))


def due_breakdown(cards: QuerySet[Flashcard], *, user, profile: UserProfile, now=None) -> DueBreakdown:
    now = now or timezone.now()
    due = cards.filter(suspended=False, schedule__due_at__lte=now)
    non_new = due.exclude(schedule__state=CardSchedule.State.NEW).count()
    new = due.filter(schedule__state=CardSchedule.State.NEW).count()
    return DueBreakdown(
        non_new=non_new,
        new=new,
        remaining_new_slots=remaining_new_slots(user=user, profile=profile),
    )


def serve_new_next(*, new_done: int, cards_done: int, new_left: int, review_left: int, offsets: list[float]) -> bool:
    """Should the next card of the session be a new one?

    Each of the day's new cards owns a position in ``offsets`` — a fraction of
    the day's workload, ascending. The next new card is served once the session
    has reached its position. Nothing is remembered between requests: the same
    counts always produce the same answer, so the decision survives a reload, a
    second device, and the queue being rebuilt on every request.

    Because the counts are re-read every time, a growing relearning pile
    stretches the day rather than postponing every new card behind it.
    """
    if new_left <= 0 or not offsets:
        return False
    if review_left <= 0:
        return True
    review_done = max(0, cards_done - new_done)
    total = new_done + new_left + review_done + review_left
    if total <= 0:
        return False
    # Where the card about to be served sits in the day, in [0, 1].
    progress = (new_done + review_done + 1) / total
    return progress >= offsets[min(new_done, len(offsets) - 1)]


def _ordered_non_new(cards: list[Flashcard], now) -> list[Flashcard]:
    return sorted(
        cards,
        key=lambda card: (NON_NEW_RANK.get(card.schedule.state, 0), priority(card.schedule, now)),
        reverse=True,
    )


def study_queue(
    cards: QuerySet[Flashcard],
    *,
    user,
    profile: UserProfile,
    now=None,
    progress: tuple[int, int] | None = None,
) -> list[Flashcard]:
    """The exact ordered queue Study serves for the selected scope.

    ``progress`` is an optional ``(new_done, cards_done)`` pair for today; it is
    read from the review log when omitted.
    """
    now = now or timezone.now()
    due = cards.filter(suspended=False, schedule__due_at__lte=now).select_related('pool', 'schedule')
    scheduled = _ordered_non_new(list(due.exclude(schedule__state=CardSchedule.State.NEW)), now)
    new_limit = remaining_new_slots(user=user, profile=profile)
    new_cards = list(
        due.filter(schedule__state=CardSchedule.State.NEW)
        .order_by('schedule__due_at', 'created_at', 'id')[:new_limit]
    ) if new_limit else []

    if not new_cards or not scheduled:
        return scheduled + new_cards
    if progress is None:
        progress = (introduced_new_today(user=user), reviews_today(user=user))
    offsets = new_card_offsets(
        progress[0] + len(new_cards),
        pacing=profile.new_card_pacing,
        seed=day_seed(user.username, timezone.localdate()),
    )
    return _mix(scheduled, new_cards, progress=progress, offsets=offsets)


def _mix(
    scheduled: list[Flashcard],
    new_cards: list[Flashcard],
    *,
    progress: tuple[int, int],
    offsets: list[float],
) -> list[Flashcard]:
    """Interleave the two lists so new cards stay evenly spread.

    Only the head of the returned queue is served before the counts are read
    again, but the whole list is materialized so the Study page can show an
    honest queue size and prefetch the images that really do come next.
    """
    new_done, cards_done = progress
    queue: list[Flashcard] = []
    scheduled_index = new_index = 0
    while scheduled_index < len(scheduled) or new_index < len(new_cards):
        take_new = serve_new_next(
            new_done=new_done + new_index,
            cards_done=cards_done + len(queue),
            new_left=len(new_cards) - new_index,
            review_left=len(scheduled) - scheduled_index,
            offsets=offsets,
        )
        if take_new:
            queue.append(new_cards[new_index])
            new_index += 1
        else:
            queue.append(scheduled[scheduled_index])
            scheduled_index += 1
    return queue


def due_cards(cards: QuerySet[Flashcard], *, user, profile: UserProfile, now=None) -> list[Flashcard]:
    """Backwards-compatible alias for the ordered study queue."""
    return study_queue(cards, user=user, profile=profile, now=now)
