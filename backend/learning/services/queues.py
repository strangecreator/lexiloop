from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet
from django.utils import timezone

from learning.models import CardSchedule, Flashcard, ReviewLog, UserProfile


@dataclass(frozen=True)
class DueBreakdown:
    non_new: int
    new: int
    remaining_new_slots: int

    @property
    def available(self) -> int:
        return self.non_new + min(self.new, self.remaining_new_slots)


def remaining_new_slots(*, user, profile: UserProfile, day=None) -> int:
    """Return how many new cards may still be introduced today.

    The scheduler's new-card limit is global per user. A card counts as introduced
    only when a review log records that its previous state was NEW.
    """
    day = day or timezone.localdate()
    introduced = ReviewLog.objects.filter(
        user=user,
        created_at__date=day,
        previous_state=CardSchedule.State.NEW,
    ).count()
    return max(0, int(profile.daily_new_limit) - introduced)


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


def due_cards(cards: QuerySet[Flashcard], *, user, profile: UserProfile, now=None) -> list[Flashcard]:
    """Materialize the exact queue exposed by Study for the selected scope."""
    now = now or timezone.now()
    due = cards.filter(suspended=False, schedule__due_at__lte=now).select_related('pool', 'schedule')
    scheduled = list(due.exclude(schedule__state=CardSchedule.State.NEW))
    new_limit = remaining_new_slots(user=user, profile=profile)
    if new_limit:
        new_cards = list(
            due.filter(schedule__state=CardSchedule.State.NEW)
            .order_by('schedule__due_at', 'created_at', 'id')[:new_limit]
        )
    else:
        new_cards = []
    return scheduled + new_cards
