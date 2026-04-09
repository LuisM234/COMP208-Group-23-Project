from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from tortoise.contrib.test import tortoise_test_context

from deps.database import (
    Card,
    DailyActivity,
    Deck,
    ReviewEvent,
    User,
)
from deps.leitner import review_card_leitner
from routes.analytics import _compute_streak, DailyActivityOut, TotalStatsOut


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with tortoise_test_context(
        ["deps.database"],
        db_url="sqlite://:memory:",
        app_label="models",
    ):
        yield


def _utc(year=2025, month=6, day=15, hour=12):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


async def _create_user(username="testuser") -> User:
    return await User.create(
        username=username,
        email=f"{username}@test.com",
        password_hash="hashed",
    )


async def _create_deck(user: User, title="Test Deck") -> Deck:
    return await Deck.create(user=user, title=title)


async def _create_card(deck: Deck, question="Q?", answer="A.") -> Card:
    return await Card.create(deck=deck, question=question, answer=answer)


async def _add_daily_activity(
    user: User, activity_date: date, reviewed: int, correct: int
) -> DailyActivity:
    return await DailyActivity.create(
        user=user,
        date=activity_date,
        cards_reviewed=reviewed,
        cards_correct=correct,
    )


# ---------------------------------------------------------------------------
# Streak computation
# ---------------------------------------------------------------------------


class TestComputeStreak:
    @pytest.mark.asyncio
    async def test_no_activity_returns_zero(self):
        user = await _create_user()
        streak = await _compute_streak(user.id)
        assert streak == 0

    @pytest.mark.asyncio
    async def test_studied_today_only(self):
        user = await _create_user()
        today = date.today()
        await _add_daily_activity(user, today, reviewed=5, correct=3)

        streak = await _compute_streak(user.id)
        assert streak == 1

    @pytest.mark.asyncio
    async def test_consecutive_days(self):
        user = await _create_user()
        today = date.today()
        for i in range(5):
            await _add_daily_activity(
                user, today - timedelta(days=i), reviewed=3, correct=2
            )

        streak = await _compute_streak(user.id)
        assert streak == 5

    @pytest.mark.asyncio
    async def test_gap_breaks_streak(self):
        user = await _create_user()
        today = date.today()
        # studied today and yesterday, but NOT 2 days ago, then 3 days ago
        await _add_daily_activity(user, today, reviewed=1, correct=1)
        await _add_daily_activity(user, today - timedelta(days=1), reviewed=1, correct=1)
        await _add_daily_activity(user, today - timedelta(days=3), reviewed=1, correct=1)

        streak = await _compute_streak(user.id)
        assert streak == 2

    @pytest.mark.asyncio
    async def test_streak_alive_from_yesterday(self):
        # if user hasn't studied today but studied yesterday, streak still counts
        user = await _create_user()
        today = date.today()
        for i in range(1, 4):  # yesterday, day before, day before that
            await _add_daily_activity(
                user, today - timedelta(days=i), reviewed=2, correct=1
            )

        streak = await _compute_streak(user.id)
        assert streak == 3

    @pytest.mark.asyncio
    async def test_no_recent_activity_returns_zero(self):
        # activity only from a week ago should give streak = 0
        user = await _create_user()
        today = date.today()
        await _add_daily_activity(
            user, today - timedelta(days=7), reviewed=5, correct=5
        )

        streak = await _compute_streak(user.id)
        assert streak == 0

    @pytest.mark.asyncio
    async def test_zero_reviewed_rows_ignored(self):
        # rows with cards_reviewed=0 should not count as active days
        user = await _create_user()
        today = date.today()
        await _add_daily_activity(user, today, reviewed=0, correct=0)

        streak = await _compute_streak(user.id)
        assert streak == 0


# ---------------------------------------------------------------------------
# Daily analytics (integration via leitner review flow)
# ---------------------------------------------------------------------------


class TestDailyAnalyticsData:
    @pytest.mark.asyncio
    async def test_review_creates_daily_activity(self):
        # verify that review_card_leitner populates DailyActivity correctly
        user = await _create_user()
        deck = await _create_deck(user)
        card1 = await _create_card(deck, question="Q1")
        card2 = await _create_card(deck, question="Q2")
        now = _utc()

        await review_card_leitner(user.id, card1.id, correct=True, as_of=now)
        await review_card_leitner(user.id, card2.id, correct=False, as_of=now)

        activity = await DailyActivity.filter(
            user_id=user.id, date=now.date()
        ).first()
        assert activity is not None
        assert activity.cards_reviewed == 2
        assert activity.cards_correct == 1

    @pytest.mark.asyncio
    async def test_multi_day_activity(self):
        # activity across multiple days produces separate rows
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)

        day1 = _utc(2025, 6, 10)
        day2 = _utc(2025, 6, 11)

        await review_card_leitner(user.id, card.id, correct=True, as_of=day1)
        await review_card_leitner(user.id, card.id, correct=False, as_of=day2)

        rows = await DailyActivity.filter(user_id=user.id).order_by("date").all()
        assert len(rows) == 2
        assert rows[0].date == day1.date()
        assert rows[1].date == day2.date()


# ---------------------------------------------------------------------------
# Total stats computation
# ---------------------------------------------------------------------------


class TestTotalStats:
    @pytest.mark.asyncio
    async def test_total_from_review_events(self):
        user = await _create_user()
        deck = await _create_deck(user)
        cards = [await _create_card(deck, question=f"Q{i}") for i in range(4)]
        now = _utc()

        await review_card_leitner(user.id, cards[0].id, correct=True, as_of=now)
        await review_card_leitner(user.id, cards[1].id, correct=True, as_of=now)
        await review_card_leitner(user.id, cards[2].id, correct=False, as_of=now)
        await review_card_leitner(user.id, cards[3].id, correct=True, as_of=now)

        events = await ReviewEvent.filter(user_id=user.id).all()
        total = len(events)
        correct = sum(1 for e in events if e.correct)

        assert total == 4
        assert correct == 3

    @pytest.mark.asyncio
    async def test_accuracy_with_no_reviews(self):
        user = await _create_user()
        events = await ReviewEvent.filter(user_id=user.id).all()
        total = len(events)
        assert total == 0
        # accuracy should be 0.0 when no reviews exist
        accuracy = 0.0 if total == 0 else (sum(1 for e in events if e.correct) / total) * 100
        assert accuracy == 0.0


# ---------------------------------------------------------------------------
# Response schema validation
# ---------------------------------------------------------------------------


class TestResponseSchemas:
    def test_daily_activity_out(self):
        obj = DailyActivityOut(
            date=date(2025, 6, 15),
            cards_reviewed=10,
            cards_correct=8,
        )
        assert obj.date == date(2025, 6, 15)
        assert obj.cards_reviewed == 10
        assert obj.cards_correct == 8

    def test_total_stats_out(self):
        obj = TotalStatsOut(
            total_cards_reviewed=100,
            overall_accuracy_pct=87.5,
            current_streak_days=3,
        )
        assert obj.total_cards_reviewed == 100
        assert obj.overall_accuracy_pct == 87.5
        assert obj.current_streak_days == 3
