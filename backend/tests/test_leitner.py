from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from tortoise.contrib.test import tortoise_test_context

from deps.database import (
    Card,
    DailyActivity,
    Deck,
    DeckDailyActivity,
    ReviewEvent,
    StudyProgress,
    User,
)
from deps.leitner import (
    BOX_INTERVALS,
    MAX_BOX,
    MIN_BOX,
    WRONG_RELEARNING_DELAY_MINUTES,
    ReviewInput,
    SessionSummary,
    _clamp_box,
    _next_box,
    get_due_study_progress,
    initialise_progress_for_card,
    initialise_progress_for_deck,
    reset_card_progress,
    reset_deck_progress,
    review_card_leitner,
    review_cards_bulk,
    validate_session_size,
)


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


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestClampBox:
    def test_within_range(self):
        for box in range(MIN_BOX, MAX_BOX + 1):
            assert _clamp_box(box) == box

    def test_below_min(self):
        assert _clamp_box(0) == MIN_BOX
        assert _clamp_box(-5) == MIN_BOX

    def test_above_max(self):
        assert _clamp_box(MAX_BOX + 1) == MAX_BOX
        assert _clamp_box(999) == MAX_BOX


class TestNextBox:
    def test_correct_advances(self):
        assert _next_box(1, True) == 2
        assert _next_box(2, True) == 3
        assert _next_box(4, True) == 4

    def test_correct_caps_at_max(self):
        assert _next_box(MAX_BOX, True) == MAX_BOX

    def test_wrong_resets_to_min(self):
        for box in range(MIN_BOX, MAX_BOX + 1):
            assert _next_box(box, False) == MIN_BOX


class TestValidateSessionSize:
    def test_valid(self):
        assert validate_session_size(20) == 20
        assert validate_session_size(10) == 10
        assert validate_session_size(150) == 150

    def test_too_small(self):
        with pytest.raises(ValueError):
            validate_session_size(1)

    def test_too_large(self):
        with pytest.raises(ValueError):
            validate_session_size(999)


# ---------------------------------------------------------------------------
# Progress initialisation
# ---------------------------------------------------------------------------


class TestInitialiseProgress:
    @pytest.mark.asyncio
    async def test_initialise_single_card(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        progress = await initialise_progress_for_card(user.id, card.id, as_of=now)

        assert progress.box == MIN_BOX
        assert progress.next_review == now
        assert progress.last_result == "new"

    @pytest.mark.asyncio
    async def test_initialise_duplicate_returns_existing(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        first = await initialise_progress_for_card(user.id, card.id, as_of=now)
        second = await initialise_progress_for_card(user.id, card.id, as_of=now)

        assert first.id == second.id

    @pytest.mark.asyncio
    async def test_initialise_deck(self):
        user = await _create_user()
        deck = await _create_deck(user)
        cards = [await _create_card(deck, question=f"Q{i}") for i in range(5)]
        now = _utc()

        rows = await initialise_progress_for_deck(user.id, deck.id, as_of=now)

        assert len(rows) == 5
        card_ids = {r.card_id for r in rows}
        assert card_ids == {c.id for c in cards}

    @pytest.mark.asyncio
    async def test_initialise_deck_skips_existing(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card1 = await _create_card(deck, question="Q1")
        card2 = await _create_card(deck, question="Q2")
        now = _utc()

        await initialise_progress_for_card(user.id, card1.id, as_of=now)
        rows = await initialise_progress_for_deck(user.id, deck.id, as_of=now)

        assert len(rows) == 1
        assert rows[0].card_id == card2.id

    @pytest.mark.asyncio
    async def test_initialise_empty_deck(self):
        user = await _create_user()
        deck = await _create_deck(user)

        rows = await initialise_progress_for_deck(user.id, deck.id)
        assert rows == []


# ---------------------------------------------------------------------------
# Due-card query
# ---------------------------------------------------------------------------


class TestGetDueStudyProgress:
    @pytest.mark.asyncio
    async def test_returns_due_cards(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await initialise_progress_for_card(user.id, card.id, as_of=now)
        due = await get_due_study_progress(user.id, as_of=now + timedelta(hours=1))

        assert len(due) == 1
        assert due[0].card_id == card.id

    @pytest.mark.asyncio
    async def test_excludes_not_yet_due(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await initialise_progress_for_card(user.id, card.id, as_of=now)
        await review_card_leitner(user.id, card.id, correct=True, as_of=now)

        due = await get_due_study_progress(user.id, as_of=now)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_deck_filter(self):
        user = await _create_user()
        deck_a = await _create_deck(user, title="A")
        deck_b = await _create_deck(user, title="B")
        card_a = await _create_card(deck_a)
        card_b = await _create_card(deck_b)
        now = _utc()

        await initialise_progress_for_card(user.id, card_a.id, as_of=now)
        await initialise_progress_for_card(user.id, card_b.id, as_of=now)

        due = await get_due_study_progress(user.id, deck_id=deck_a.id, as_of=now)
        assert len(due) == 1
        assert due[0].card_id == card_a.id

    @pytest.mark.asyncio
    async def test_new_cards_cap(self):
        user = await _create_user()
        deck = await _create_deck(user)
        now = _utc()

        for i in range(20):
            card = await _create_card(deck, question=f"Q{i}")
            await initialise_progress_for_card(user.id, card.id, as_of=now)

        due = await get_due_study_progress(
            user.id, new_cards_per_session=3, as_of=now
        )
        assert len(due) == 3

    @pytest.mark.asyncio
    async def test_prefetches_card_and_deck(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await initialise_progress_for_card(user.id, card.id, as_of=now)
        due = await get_due_study_progress(user.id, as_of=now)

        assert due[0].card.question == "Q?"
        assert due[0].card.deck.title == "Test Deck"


# ---------------------------------------------------------------------------
# Single-card review
# ---------------------------------------------------------------------------


class TestReviewCardLeitner:
    @pytest.mark.asyncio
    async def test_correct_advances_box(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        progress = await review_card_leitner(user.id, card.id, correct=True, as_of=now)

        assert progress.box == 2
        assert progress.streak == 1
        assert progress.last_result == "correct"
        assert progress.next_review == now + BOX_INTERVALS[2]

    @pytest.mark.asyncio
    async def test_wrong_resets_box(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await review_card_leitner(user.id, card.id, correct=True, as_of=now)
        await review_card_leitner(user.id, card.id, correct=True, as_of=now)
        progress = await review_card_leitner(user.id, card.id, correct=False, as_of=now)

        assert progress.box == MIN_BOX
        assert progress.streak == 0
        assert progress.lapse_count == 1
        assert progress.last_result == "wrong"
        assert progress.next_review == now + timedelta(minutes=WRONG_RELEARNING_DELAY_MINUTES)

    @pytest.mark.asyncio
    async def test_creates_daily_activity(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await review_card_leitner(user.id, card.id, correct=True, as_of=now)

        activity = await DailyActivity.filter(user_id=user.id, date=now.date()).first()
        assert activity is not None
        assert activity.cards_reviewed == 1
        assert activity.cards_correct == 1

    @pytest.mark.asyncio
    async def test_creates_deck_daily_activity(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await review_card_leitner(user.id, card.id, correct=False, as_of=now)

        activity = await DeckDailyActivity.filter(
            user_id=user.id, deck_id=deck.id, date=now.date()
        ).first()
        assert activity is not None
        assert activity.cards_reviewed == 1
        assert activity.cards_correct == 0

    @pytest.mark.asyncio
    async def test_creates_review_event(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await review_card_leitner(
            user.id, card.id, correct=True, as_of=now, response_time_ms=1500
        )

        event = await ReviewEvent.filter(user_id=user.id, card_id=card.id).first()
        assert event is not None
        assert event.correct is True
        assert event.old_box == 1
        assert event.new_box == 2
        assert event.response_time_ms == 1500

    @pytest.mark.asyncio
    async def test_rejects_negative_response_time(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)

        with pytest.raises(ValueError, match="negative"):
            await review_card_leitner(user.id, card.id, correct=True, response_time_ms=-1)

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_card(self):
        user = await _create_user()

        with pytest.raises(ValueError, match="does not exist"):
            await review_card_leitner(user.id, card_id=99999, correct=True)

    @pytest.mark.asyncio
    async def test_rejects_other_users_card(self):
        user_a = await _create_user("alice")
        user_b = await _create_user("bob")
        deck = await _create_deck(user_a)
        card = await _create_card(deck)

        with pytest.raises(PermissionError):
            await review_card_leitner(user_b.id, card.id, correct=True)

    @pytest.mark.asyncio
    async def test_multiple_reviews_accumulate_activity(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card1 = await _create_card(deck, question="Q1")
        card2 = await _create_card(deck, question="Q2")
        now = _utc()

        await review_card_leitner(user.id, card1.id, correct=True, as_of=now)
        await review_card_leitner(user.id, card2.id, correct=False, as_of=now)

        activity = await DailyActivity.filter(user_id=user.id, date=now.date()).first()
        assert activity.cards_reviewed == 2
        assert activity.cards_correct == 1


# ---------------------------------------------------------------------------
# Bulk review
# ---------------------------------------------------------------------------


class TestBulkReview:
    @pytest.mark.asyncio
    async def test_processes_batch(self):
        user = await _create_user()
        deck = await _create_deck(user)
        cards = [await _create_card(deck, question=f"Q{i}") for i in range(3)]
        now = _utc()

        reviews = [
            ReviewInput(card_id=cards[0].id, correct=True, response_time_ms=1000),
            ReviewInput(card_id=cards[1].id, correct=False, response_time_ms=2000),
            ReviewInput(card_id=cards[2].id, correct=True, response_time_ms=1500),
        ]
        summary = await review_cards_bulk(user.id, reviews, as_of=now)

        assert summary.cards_reviewed == 3
        assert summary.cards_correct == 2
        assert summary.cards_wrong == 1
        assert summary.total_response_time_ms == 4500
        assert summary.accuracy == pytest.approx(2 / 3)
        assert summary.average_response_time_ms == pytest.approx(1500.0)
        assert len(summary.progress_entries) == 3

    @pytest.mark.asyncio
    async def test_longest_streak(self):
        user = await _create_user()
        deck = await _create_deck(user)
        cards = [await _create_card(deck, question=f"Q{i}") for i in range(5)]
        now = _utc()

        reviews = [
            ReviewInput(card_id=cards[0].id, correct=True),
            ReviewInput(card_id=cards[1].id, correct=True),
            ReviewInput(card_id=cards[2].id, correct=True),
            ReviewInput(card_id=cards[3].id, correct=False),
            ReviewInput(card_id=cards[4].id, correct=True),
        ]
        summary = await review_cards_bulk(user.id, reviews, as_of=now)

        assert summary.longest_streak == 3

    @pytest.mark.asyncio
    async def test_daily_aggregates_written_once(self):
        user = await _create_user()
        deck = await _create_deck(user)
        cards = [await _create_card(deck, question=f"Q{i}") for i in range(3)]
        now = _utc()

        reviews = [ReviewInput(card_id=c.id, correct=True) for c in cards]
        await review_cards_bulk(user.id, reviews, as_of=now)

        activity = await DailyActivity.filter(user_id=user.id, date=now.date()).first()
        assert activity.cards_reviewed == 3
        assert activity.cards_correct == 3

        deck_activity = await DeckDailyActivity.filter(
            user_id=user.id, deck_id=deck.id, date=now.date()
        ).first()
        assert deck_activity.cards_reviewed == 3

    @pytest.mark.asyncio
    async def test_rejects_other_users_card_in_batch(self):
        user_a = await _create_user("alice")
        user_b = await _create_user("bob")
        deck = await _create_deck(user_a)
        card = await _create_card(deck)

        reviews = [ReviewInput(card_id=card.id, correct=True)]
        with pytest.raises(PermissionError):
            await review_cards_bulk(user_b.id, reviews)

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        user = await _create_user()
        summary = await review_cards_bulk(user.id, [])

        assert summary.cards_reviewed == 0
        assert summary.accuracy == 0.0
        assert summary.average_response_time_ms is None


# ---------------------------------------------------------------------------
# Progress reset
# ---------------------------------------------------------------------------


class TestProgressReset:
    @pytest.mark.asyncio
    async def test_reset_single_card(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        await review_card_leitner(user.id, card.id, correct=True, as_of=now)
        await review_card_leitner(user.id, card.id, correct=True, as_of=now)

        progress = await reset_card_progress(user.id, card.id, as_of=now)

        assert progress.box == MIN_BOX
        assert progress.streak == 0
        assert progress.last_result == "new"
        assert progress.next_review == now

    @pytest.mark.asyncio
    async def test_reset_unstudied_card_returns_none(self):
        user = await _create_user()
        result = await reset_card_progress(user.id, card_id=99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_reset_deck(self):
        user = await _create_user()
        deck = await _create_deck(user)
        cards = [await _create_card(deck, question=f"Q{i}") for i in range(3)]
        now = _utc()

        for card in cards:
            await review_card_leitner(user.id, card.id, correct=True, as_of=now)

        count = await reset_deck_progress(user.id, deck.id, as_of=now)
        assert count == 3

        for card in cards:
            p = await StudyProgress.filter(user_id=user.id, card_id=card.id).first()
            assert p.box == MIN_BOX
            assert p.last_result == "new"

    @pytest.mark.asyncio
    async def test_reset_empty_deck(self):
        user = await _create_user()
        deck = await _create_deck(user)

        count = await reset_deck_progress(user.id, deck.id)
        assert count == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_box_caps_at_max(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        for _ in range(MAX_BOX + 5):
            progress = await review_card_leitner(
                user.id, card.id, correct=True, as_of=now
            )
        assert progress.box == MAX_BOX

    @pytest.mark.asyncio
    async def test_review_creates_progress_if_missing(self):
        user = await _create_user()
        deck = await _create_deck(user)
        card = await _create_card(deck)
        now = _utc()

        progress = await review_card_leitner(user.id, card.id, correct=True, as_of=now)
        assert progress is not None
        assert progress.box == 2

    @pytest.mark.asyncio
    async def test_session_summary_properties(self):
        summary = SessionSummary()
        assert summary.accuracy == 0.0
        assert summary.average_response_time_ms is None

        summary.cards_reviewed = 4
        summary.cards_correct = 3
        summary.total_response_time_ms = 8000
        assert summary.accuracy == pytest.approx(0.75)
        assert summary.average_response_time_ms == pytest.approx(2000.0)
