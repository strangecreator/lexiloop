from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet
from django.utils import timezone

from learning.models import CardSchedule, Flashcard, ReviewLog, UserProfile
from learning.services.scheduler import priority

# Relearning first, then learning, then reviews. New cards are placed by
# ``new_card_order`` rather than by this rank.
NON_NEW_RANK = {
    CardSchedule.State.RELEARNING: 3,
    CardSchedule.State.LEARNING: 2,
    CardSchedule.State.REVIEW: 1,
}


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


def serve_new_next(*, new_done: int, cards_done: int, new_left: int, review_left: int) -> bool:
    """Should the next card of a mixed session be a new one?

    The day's whole workload is ``new_total`` new cards among ``total`` cards, so
    an evenly mixed session has shown ``round(position * new_total / total)`` new
    cards by the time it reaches ``position``. Serving a new card exactly when
    the session has fallen behind that line spreads new cards evenly without
    keeping any per-session state on the server: the same counts always produce
    the same answer, so the decision survives reloads, a second device, and the
    queue being recomputed on every request.

    Because the counts are re-read every time, a growing relearning pile lowers
    the new-card share smoothly instead of postponing every new card behind it.
    """
    if new_left <= 0:
        return False
    if review_left <= 0:
        return True
    review_done = max(0, cards_done - new_done)
    new_total = new_done + new_left
    total = new_total + review_done + review_left
    if total <= 0:
        return False
    target = round((new_done + review_done + 1) * new_total / total)
    return new_done < target


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
    read from the review log when omitted. Only the mixed order needs it.
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
    order = profile.new_card_order
    if order == UserProfile.NewCardOrder.BEFORE_REVIEWS:
        return new_cards + scheduled
    if order == UserProfile.NewCardOrder.AFTER_REVIEWS:
        return scheduled + new_cards
    if progress is None:
        progress = (introduced_new_today(user=user), reviews_today(user=user))
    return _mix(scheduled, new_cards, progress=progress)


def _mix(scheduled: list[Flashcard], new_cards: list[Flashcard], *, progress: tuple[int, int]) -> list[Flashcard]:
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
