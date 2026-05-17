from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from deps.database import (
    Card,
    DailyActivity,
    DeckDailyActivity,
    ReviewEvent,
    StudyProgress,
)

# ---------------------------------------------------------------------------
# Leitner box intervals
# ---------------------------------------------------------------------------
# The box number is the card's current level, and the value is how many days
# to wait before showing that card again.

BOX_INTERVALS: dict[int, timedelta] = {
    1: timedelta(minutes=1),
    2: timedelta(minutes=6),
    3: timedelta(minutes=10),
    4: timedelta(days=4),
}
MIN_BOX = 1
MAX_BOX = 4

# Wrong answers are scheduled for a short retry first instead of waiting a
# full day. This keeps misses in short-term memory and improves relearning.
WRONG_RELEARNING_DELAY_MINUTES = 1

# ---------------------------------------------------------------------------
# Session size bounds
# ---------------------------------------------------------------------------
# The study session size is user-controlled, but the backend still enforces
# sensible bounds.

MIN_SESSION_SIZE = 10
MAX_SESSION_SIZE = 150
DEFAULT_SESSION_SIZE = 20
DEFAULT_NEW_CARDS_PER_SESSION = 5


# ---------------------------------------------------------------------------
# Session summary dataclass
# ---------------------------------------------------------------------------


@dataclass
class SessionSummary:
    """Returned after a bulk review so the frontend can show end-of-session
    stats without extra API calls."""

    cards_reviewed: int = 0
    cards_correct: int = 0
    cards_wrong: int = 0
    total_response_time_ms: int = 0
    longest_streak: int = 0
    progress_entries: list[StudyProgress] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """Accuracy as a float between 0.0 and 1.0."""
        if self.cards_reviewed == 0:
            return 0.0
        return self.cards_correct / self.cards_reviewed

    @property
    def average_response_time_ms(self) -> float | None:
        """Average response time, or None if no times were recorded."""
        if self.cards_reviewed == 0:
            return None
        if self.total_response_time_ms == 0:
            return None
        return self.total_response_time_ms / self.cards_reviewed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Every scheduling comparison uses UTC so 'due now' means the same thing
    everywhere in the app."""
    return datetime.now(timezone.utc)


def validate_session_size(session_size: int) -> int:
    """Reject invalid session sizes before any database query runs."""
    if not MIN_SESSION_SIZE <= session_size <= MAX_SESSION_SIZE:
        raise ValueError(
            f"session_size must be between {MIN_SESSION_SIZE} and {MAX_SESSION_SIZE}"
        )
    return session_size


def _clamp_box(box: int) -> int:
    """Keep box within valid range in case of stale or migrated data."""
    if box < MIN_BOX:
        return MIN_BOX
    if box > MAX_BOX:
        return MAX_BOX
    return box


def _next_box(current_box: int, correct: bool) -> int:
    """Calculate the next Leitner box after a review.

    - correct answer -> move forward one box (capped at MAX_BOX)
    - wrong answer   -> reset to box 1
    """
    current = _clamp_box(current_box)
    if not correct:
        return MIN_BOX
    return min(current + 1, MAX_BOX)


# ---------------------------------------------------------------------------
# Progress initialisation
# ---------------------------------------------------------------------------


async def initialise_progress_for_card(
    user_id: int,
    card_id: int,
    as_of: datetime | None = None,
) -> StudyProgress:
    """Create a StudyProgress row for a new card so it appears in the study
    queue immediately. Silently returns the existing row if one already exists."""
    now = as_of or utc_now()
    try:
        progress = StudyProgress(
            user_id=user_id,
            card_id=card_id,
            box=MIN_BOX,
            next_review=now,
            last_result="new",
        )
        await progress.save()
        return progress
    except IntegrityError:
        return await StudyProgress.filter(
            user_id=user_id, card_id=card_id
        ).get()


async def initialise_progress_for_deck(
    user_id: int,
    deck_id: int,
    as_of: datetime | None = None,
) -> list[StudyProgress]:
    """Create StudyProgress rows for every card in a deck that doesn't already
    have one. Call this when a user first opens a deck or when new cards are
    added via AI generation."""
    now = as_of or utc_now()

    # Find cards in this deck that the user has no progress row for yet.
    existing_card_ids = set(
        await StudyProgress.filter(user_id=user_id, card__deck_id=deck_id)
        .values_list("card_id", flat=True)
    )
    all_card_ids = set(
        await Card.filter(deck_id=deck_id).values_list("id", flat=True)
    )
    missing_card_ids = all_card_ids - existing_card_ids

    if not missing_card_ids:
        return []

    new_rows = [
        StudyProgress(
            user_id=user_id,
            card_id=cid,
            box=MIN_BOX,
            next_review=now,
            last_result="new",
        )
        for cid in missing_card_ids
    ]
    await StudyProgress.bulk_create(new_rows, ignore_conflicts=True)

    return await StudyProgress.filter(
        user_id=user_id, card_id__in=missing_card_ids
    ).all()


# ---------------------------------------------------------------------------
# Due-card query
# ---------------------------------------------------------------------------


async def get_due_study_progress(
    user_id: int,
    deck_id: int | None = None,
    session_size: int = DEFAULT_SESSION_SIZE,
    new_cards_per_session: int = DEFAULT_NEW_CARDS_PER_SESSION,
    as_of: datetime | None = None,
) -> list[StudyProgress]:
    """Return cards due for review, oldest first.

    Mixes review cards (cards already seen) with a limited number of new cards
    so the user isn't overwhelmed when they have a large unseen backlog.

    Prefetches the related Card and Deck so callers don't trigger N+1 queries.
    """
    size = validate_session_size(session_size)
    cutoff = as_of or utc_now()

    # -- Review cards: already seen, due now --
    review_filter = {
        "user_id": user_id,
        "next_review__lte": cutoff,
        "last_result__not": "new",
    }
    if deck_id is not None:
        review_filter["card__deck_id"] = deck_id

    review_cards = await (
        StudyProgress.filter(**review_filter)
        .select_related("card", "card__deck")
        .order_by("next_review")
        .limit(size)
    )

    # -- New cards: never reviewed, capped per session --
    remaining = size - len(review_cards)
    new_limit = min(new_cards_per_session, remaining) if remaining > 0 else 0

    new_cards: list[StudyProgress] = []
    if new_limit > 0:
        new_filter = {
            "user_id": user_id,
            "last_result": "new",
            "next_review__lte": cutoff,
        }
        if deck_id is not None:
            new_filter["card__deck_id"] = deck_id

        new_cards = await (
            StudyProgress.filter(**new_filter)
            .select_related("card", "card__deck")
            .order_by("next_review")
            .limit(new_limit)
        )

    return review_cards + new_cards


# ---------------------------------------------------------------------------
# Daily activity upserts (internal helpers)
# ---------------------------------------------------------------------------


async def _upsert_daily_activity_with_db(
    db: BaseDBAsyncClient,
    user_id: int,
    cards_reviewed_increment: int = 0,
    cards_correct_increment: int = 0,
    activity_date: date_type | None = None,
) -> DailyActivity:
    """Create or update the per-user daily summary row inside an existing
    transaction."""
    target_date = activity_date or utc_now().date()

    activity = (
        await DailyActivity.filter(user_id=user_id, date=target_date)
        .using_db(db)
        .select_for_update()
        .first()
    )

    if activity is None:
        try:
            activity = DailyActivity(
                user_id=user_id,
                date=target_date,
                cards_reviewed=0,
                cards_correct=0,
            )
            await activity.save(using_db=db)
        except IntegrityError:
            # Two reviews hit the same date row at nearly the same time.
            activity = (
                await DailyActivity.filter(user_id=user_id, date=target_date)
                .using_db(db)
                .select_for_update()
                .get()
            )

    activity.cards_reviewed += cards_reviewed_increment
    activity.cards_correct += cards_correct_increment
    await activity.save(using_db=db, update_fields=["cards_reviewed", "cards_correct"])
    return activity


async def _upsert_deck_daily_activity_with_db(
    db: BaseDBAsyncClient,
    user_id: int,
    deck_id: int,
    cards_reviewed_increment: int = 0,
    cards_correct_increment: int = 0,
    activity_date: date_type | None = None,
) -> DeckDailyActivity:
    """Create or update the per-deck daily summary row inside an existing
    transaction."""
    target_date = activity_date or utc_now().date()

    activity = (
        await DeckDailyActivity.filter(
            user_id=user_id,
            deck_id=deck_id,
            date=target_date,
        )
        .using_db(db)
        .select_for_update()
        .first()
    )

    if activity is None:
        try:
            activity = DeckDailyActivity(
                user_id=user_id,
                deck_id=deck_id,
                date=target_date,
                cards_reviewed=0,
                cards_correct=0,
            )
            await activity.save(using_db=db)
        except IntegrityError:
            activity = (
                await DeckDailyActivity.filter(
                    user_id=user_id,
                    deck_id=deck_id,
                    date=target_date,
                )
                .using_db(db)
                .select_for_update()
                .get()
            )

    activity.cards_reviewed += cards_reviewed_increment
    activity.cards_correct += cards_correct_increment
    await activity.save(using_db=db, update_fields=["cards_reviewed", "cards_correct"])
    return activity


# ---------------------------------------------------------------------------
# Public daily-activity wrapper
# ---------------------------------------------------------------------------


async def upsert_daily_activity(
    user_id: int,
    cards_reviewed_increment: int = 0,
    cards_correct_increment: int = 0,
    activity_date: date_type | None = None,
) -> DailyActivity:
    """Convenience wrapper that opens its own transaction for callers outside
    the main review flow."""
    async with in_transaction() as db:
        return await _upsert_daily_activity_with_db(
            db=db,
            user_id=user_id,
            cards_reviewed_increment=cards_reviewed_increment,
            cards_correct_increment=cards_correct_increment,
            activity_date=activity_date,
        )


# ---------------------------------------------------------------------------
# Single-card review
# ---------------------------------------------------------------------------


async def review_card_leitner(
    user_id: int,
    card_id: int,
    correct: bool,
    as_of: datetime | None = None,
    response_time_ms: int | None = None,
    next_review_delay_seconds: int | None = None,
) -> StudyProgress:
    """Record one review and advance the Leitner schedule.

    The whole update runs in one transaction so the progress row, daily
    aggregates, and raw review event all stay in sync.
    """
    now = as_of or utc_now()
    if response_time_ms is not None and response_time_ms < 0:
        raise ValueError("response_time_ms cannot be negative")
    custom_delay = None
    if next_review_delay_seconds is not None:
        if not 1 <= next_review_delay_seconds <= 60 * 60 * 24 * 365:
            raise ValueError("next_review_delay_seconds must be between 1 second and 365 days")
        custom_delay = timedelta(seconds=next_review_delay_seconds)

    async with in_transaction() as db:
        # Load the card and verify it belongs to a deck owned by this user.
        card = (
            await Card.filter(id=card_id)
            .using_db(db)
            .select_related("deck")
            .only("id", "deck_id", "deck__id", "deck__user_id")
            .first()
        )
        if card is None:
            raise ValueError(f"Card with id {card_id} does not exist")
        if card.deck.user_id != user_id:
            raise PermissionError(
                f"Card {card_id} does not belong to user {user_id}"
            )
        deck_id = card.deck_id

        # Lock the progress row for this user/card pair.
        progress = (
            await StudyProgress.filter(user_id=user_id, card_id=card_id)
            .using_db(db)
            .select_for_update()
            .first()
        )

        if progress is None:
            try:
                progress = StudyProgress(
                    user_id=user_id,
                    card_id=card_id,
                    box=MIN_BOX,
                    next_review=now,
                )
                await progress.save(using_db=db)
            except IntegrityError:
                # Race: two concurrent reviews for the same user+card.
                progress = (
                    await StudyProgress.filter(user_id=user_id, card_id=card_id)
                    .using_db(db)
                    .select_for_update()
                    .get()
                )

        old_box = _clamp_box(progress.box)
        progress.box = _next_box(progress.box, correct)
        progress.last_reviewed = now

        if correct:
            progress.next_review = now + (custom_delay or BOX_INTERVALS[progress.box])
            progress.streak += 1
            progress.last_result = "correct"
        else:
            progress.next_review = now + (
                custom_delay or timedelta(minutes=WRONG_RELEARNING_DELAY_MINUTES)
            )
            progress.lapse_count += 1
            progress.streak = 0
            progress.last_result = "wrong"

        await progress.save(
            using_db=db,
            update_fields=[
                "box",
                "last_reviewed",
                "next_review",
                "streak",
                "lapse_count",
                "last_result",
            ],
        )

        # Update daily totals.
        await _upsert_daily_activity_with_db(
            db=db,
            user_id=user_id,
            cards_reviewed_increment=1,
            cards_correct_increment=1 if correct else 0,
            activity_date=now.date(),
        )

        await _upsert_deck_daily_activity_with_db(
            db=db,
            user_id=user_id,
            deck_id=deck_id,
            cards_reviewed_increment=1,
            cards_correct_increment=1 if correct else 0,
            activity_date=now.date(),
        )

        # Raw event log for debugging and richer analytics later.
        event = ReviewEvent(
            user_id=user_id,
            deck_id=deck_id,
            card_id=card_id,
            reviewed_at=now,
            correct=correct,
            old_box=old_box,
            new_box=progress.box,
            response_time_ms=response_time_ms,
        )
        await event.save(using_db=db)

        return progress


# ---------------------------------------------------------------------------
# Bulk review (batch submission)
# ---------------------------------------------------------------------------


@dataclass
class ReviewInput:
    """One review in a batch submission."""

    card_id: int
    correct: bool
    response_time_ms: int | None = None


async def review_cards_bulk(
    user_id: int,
    reviews: list[ReviewInput],
    as_of: datetime | None = None,
) -> SessionSummary:
    """Process a batch of reviews in a single transaction and return a
    session summary. Preferred over calling review_card_leitner in a loop
    because it avoids N separate transactions."""
    now = as_of or utc_now()
    summary = SessionSummary()
    current_streak = 0

    for r in reviews:
        if r.response_time_ms is not None and r.response_time_ms < 0:
            raise ValueError(
                f"response_time_ms cannot be negative for card {r.card_id}"
            )

    async with in_transaction() as db:
        for r in reviews:
            card = (
                await Card.filter(id=r.card_id)
                .using_db(db)
                .select_related("deck")
                .only("id", "deck_id", "deck__id", "deck__user_id")
                .first()
            )
            if card is None:
                raise ValueError(f"Card with id {r.card_id} does not exist")
            if card.deck.user_id != user_id:
                raise PermissionError(
                    f"Card {r.card_id} does not belong to user {user_id}"
                )
            deck_id = card.deck_id

            progress = (
                await StudyProgress.filter(user_id=user_id, card_id=r.card_id)
                .using_db(db)
                .select_for_update()
                .first()
            )

            if progress is None:
                try:
                    progress = StudyProgress(
                        user_id=user_id,
                        card_id=r.card_id,
                        box=MIN_BOX,
                        next_review=now,
                    )
                    await progress.save(using_db=db)
                except IntegrityError:
                    progress = (
                        await StudyProgress.filter(
                            user_id=user_id, card_id=r.card_id
                        )
                        .using_db(db)
                        .select_for_update()
                        .get()
                    )

            old_box = _clamp_box(progress.box)
            progress.box = _next_box(progress.box, r.correct)
            progress.last_reviewed = now

            if r.correct:
                progress.next_review = now + BOX_INTERVALS[progress.box]
                progress.streak += 1
                progress.last_result = "correct"
                current_streak += 1
            else:
                progress.next_review = now + timedelta(
                    minutes=WRONG_RELEARNING_DELAY_MINUTES
                )
                progress.lapse_count += 1
                progress.streak = 0
                progress.last_result = "wrong"
                current_streak = 0

            summary.longest_streak = max(summary.longest_streak, current_streak)

            await progress.save(
                using_db=db,
                update_fields=[
                    "box",
                    "last_reviewed",
                    "next_review",
                    "streak",
                    "lapse_count",
                    "last_result",
                ],
            )

            event = ReviewEvent(
                user_id=user_id,
                deck_id=deck_id,
                card_id=r.card_id,
                reviewed_at=now,
                correct=r.correct,
                old_box=old_box,
                new_box=progress.box,
                response_time_ms=r.response_time_ms,
            )
            await event.save(using_db=db)

            # Accumulate summary stats.
            summary.cards_reviewed += 1
            if r.correct:
                summary.cards_correct += 1
            else:
                summary.cards_wrong += 1
            if r.response_time_ms is not None:
                summary.total_response_time_ms += r.response_time_ms
            summary.progress_entries.append(progress)

        # Batch-update daily aggregates once instead of per-card.
        # Group increments by deck so each deck row is touched only once.
        await _upsert_daily_activity_with_db(
            db=db,
            user_id=user_id,
            cards_reviewed_increment=summary.cards_reviewed,
            cards_correct_increment=summary.cards_correct,
            activity_date=now.date(),
        )

        deck_totals: dict[int, tuple[int, int]] = {}
        for r, prog in zip(reviews, summary.progress_entries):
            did = prog.card_id  # we need deck_id, re-derive from card
            # Re-fetch deck_id from the card we already validated
            c = await Card.filter(id=r.card_id).using_db(db).only("deck_id").first()
            did = c.deck_id  # type: ignore[union-attr]
            reviewed, correct_count = deck_totals.get(did, (0, 0))
            deck_totals[did] = (
                reviewed + 1,
                correct_count + (1 if r.correct else 0),
            )

        for did, (reviewed, correct_count) in deck_totals.items():
            await _upsert_deck_daily_activity_with_db(
                db=db,
                user_id=user_id,
                deck_id=did,
                cards_reviewed_increment=reviewed,
                cards_correct_increment=correct_count,
                activity_date=now.date(),
            )

    return summary


# ---------------------------------------------------------------------------
# Progress reset
# ---------------------------------------------------------------------------


async def reset_card_progress(
    user_id: int,
    card_id: int,
    as_of: datetime | None = None,
) -> StudyProgress | None:
    """Reset a single card back to box 1. Returns None if no progress row
    exists (card was never studied)."""
    now = as_of or utc_now()
    progress = await StudyProgress.filter(
        user_id=user_id, card_id=card_id
    ).first()
    if progress is None:
        return None

    progress.box = MIN_BOX
    progress.next_review = now
    progress.streak = 0
    progress.last_result = "new"
    await progress.save(
        update_fields=["box", "next_review", "streak", "last_result"]
    )
    return progress


async def reset_deck_progress(
    user_id: int,
    deck_id: int,
    as_of: datetime | None = None,
) -> int:
    """Reset all progress for a deck back to box 1. Returns the number of
    cards reset."""
    now = as_of or utc_now()

    # Two-step query: fetch IDs first, then update by primary key.
    # A single .filter(card__deck_id=...).update() generates an UPDATE JOIN
    # which SQLite cannot handle.
    progress_ids = await StudyProgress.filter(
        user_id=user_id, card__deck_id=deck_id
    ).values_list("id", flat=True)

    if not progress_ids:
        return 0

    return await StudyProgress.filter(id__in=progress_ids).update(
        box=MIN_BOX,
        next_review=now,
        streak=0,
        last_result="new",
    )
