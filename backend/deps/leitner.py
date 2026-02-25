from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from deps.database import Card, DailyActivity, DeckDailyActivity, ReviewEvent, StudyProgress

# Days to wait before the next review for each Leitner box.
BOX_INTERVAL_DAYS: dict[int, int] = {
    1: 1,
    2: 2,
    3: 4,
    4: 7,
    5: 15,
}
MIN_BOX = min(BOX_INTERVAL_DAYS)
MAX_BOX = max(BOX_INTERVAL_DAYS)

MIN_SESSION_SIZE = 10
MAX_SESSION_SIZE = 150
DEFAULT_SESSION_SIZE = 20


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_session_size(session_size: int) -> int:
    if not MIN_SESSION_SIZE <= session_size <= MAX_SESSION_SIZE:
        raise ValueError(
            f"session_size must be between {MIN_SESSION_SIZE} and {MAX_SESSION_SIZE}"
        )
    return session_size


def _clamp_box(box: int) -> int:
    if box < MIN_BOX:
        return MIN_BOX
    if box > MAX_BOX:
        return MAX_BOX
    return box


def _next_box(current_box: int, correct: bool) -> int:
    current = _clamp_box(current_box)
    if not correct:
        return MIN_BOX
    return min(current + 1, MAX_BOX)


async def get_due_study_progress(
    user_id: int,
    session_size: int = DEFAULT_SESSION_SIZE,
    as_of: datetime | None = None,
) -> list[StudyProgress]:
    size = validate_session_size(session_size)
    cutoff = as_of or utc_now()
    return await (
        StudyProgress.filter(user_id=user_id, next_review__lte=cutoff)
        .order_by("next_review")
        .limit(size)
    )


async def _upsert_daily_activity_with_db(
    db: BaseDBAsyncClient,
    user_id: int,
    cards_reviewed_increment: int = 0,
    cards_correct_increment: int = 0,
    activity_date: date_type | None = None,
) -> DailyActivity:
    target_date = activity_date or utc_now().date()

    # Keep one row per user/day and update counters in-place.
    activity = (
        await DailyActivity.filter(user_id=user_id, date=target_date)
        .using_db(db)
        .select_for_update()
        .first()
    )

    if activity is None:
        try:
            activity = await DailyActivity.create(
                user_id=user_id,
                date=target_date,
                cards_reviewed=0,
                cards_correct=0,
                using_db=db,
            )
        except IntegrityError:
            # Another request may have created today's row first.
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
    target_date = activity_date or utc_now().date()

    # Same as DailyActivity, but split by deck for analytics drill-down.
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
            activity = await DeckDailyActivity.create(
                user_id=user_id,
                deck_id=deck_id,
                date=target_date,
                cards_reviewed=0,
                cards_correct=0,
                using_db=db,
            )
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


async def upsert_daily_activity(
    user_id: int,
    cards_reviewed_increment: int = 0,
    cards_correct_increment: int = 0,
    activity_date: date_type | None = None,
) -> DailyActivity:
    async with in_transaction() as db:
        return await _upsert_daily_activity_with_db(
            db=db,
            user_id=user_id,
            cards_reviewed_increment=cards_reviewed_increment,
            cards_correct_increment=cards_correct_increment,
            activity_date=activity_date,
        )


async def review_card_leitner(
    user_id: int,
    card_id: int,
    correct: bool,
    as_of: datetime | None = None,
    response_time_ms: int | None = None,
) -> StudyProgress:
    now = as_of or utc_now()
    if response_time_ms is not None and response_time_ms < 0:
        raise ValueError("response_time_ms cannot be negative")

    async with in_transaction() as db:
        # We store deck-level analytics, so we need the card's deck id.
        deck_id = (
            await Card.filter(id=card_id)
            .using_db(db)
            .values_list("deck_id", flat=True)
            .first()
        )
        if deck_id is None:
            raise ValueError(f"Card with id {card_id} does not exist")

        progress = (
            await StudyProgress.filter(user_id=user_id, card_id=card_id)
            .using_db(db)
            .select_for_update()
            .first()
        )

        if progress is None:
            progress = await StudyProgress.create(
                user_id=user_id,
                card_id=card_id,
                box=MIN_BOX,
                next_review=now,
                using_db=db,
            )

        old_box = _clamp_box(progress.box)
        progress.box = _next_box(progress.box, correct)
        progress.last_reviewed = now
        progress.next_review = now + timedelta(days=BOX_INTERVAL_DAYS[progress.box])
        if correct:
            progress.streak += 1
            progress.last_result = "correct"
        else:
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

        await ReviewEvent.create(
            user_id=user_id,
            deck_id=deck_id,
            card_id=card_id,
            reviewed_at=now,
            correct=correct,
            old_box=old_box,
            new_box=progress.box,
            response_time_ms=response_time_ms,
            using_db=db,
        )

        return progress
