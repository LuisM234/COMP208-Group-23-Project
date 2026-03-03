from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from tortoise.contrib.test import tortoise_test_context
from tortoise.exceptions import IntegrityError

from deps.database import (
    VALID_CORRECT_ANSWERS,
    VALID_GENERATION_KINDS,
    VALID_GENERATION_STATUSES,
    VALID_INPUT_TYPES,
    VALID_LAST_RESULTS,
    VALID_WEEK_DAYS,
    AIGenerationRun,
    Card,
    DailyActivity,
    Deck,
    DeckDailyActivity,
    MCQQuestion,
    ReviewEvent,
    StudyProgress,
    User,
    UserSettings,
    utc_now,
    utc_today,
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


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtcHelpers:
    def test_utc_now_has_timezone(self):
        now = utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc

    def test_utc_today_returns_date(self):
        today = utc_today()
        assert today == utc_now().date()


# ---------------------------------------------------------------------------
# Validation sets
# ---------------------------------------------------------------------------


class TestValidationSets:
    def test_last_results(self):
        assert VALID_LAST_RESULTS == {"new", "correct", "wrong"}

    def test_correct_answers(self):
        assert VALID_CORRECT_ANSWERS == {"A", "B", "C", "D"}

    def test_week_days(self):
        assert len(VALID_WEEK_DAYS) == 7
        assert "MON" in VALID_WEEK_DAYS
        assert "SUN" in VALID_WEEK_DAYS

    def test_generation_kinds(self):
        assert VALID_GENERATION_KINDS == {"flashcards", "mcq"}

    def test_input_types(self):
        assert VALID_INPUT_TYPES == {"notes", "deck"}

    def test_generation_statuses(self):
        assert "pending" in VALID_GENERATION_STATUSES
        assert "success" in VALID_GENERATION_STATUSES
        assert "failed" in VALID_GENERATION_STATUSES


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


class TestUserModel:
    @pytest.mark.asyncio
    async def test_create_user(self):
        user = await User.create(
            username="alice",
            email="alice@test.com",
            password_hash="hashed123",
        )
        assert user.id is not None
        assert user.username == "alice"
        assert user.email == "alice@test.com"
        assert user.created_at is not None

    @pytest.mark.asyncio
    async def test_username_unique(self):
        await User.create(username="bob", email="bob@test.com", password_hash="h")
        with pytest.raises(IntegrityError):
            await User.create(username="bob", email="bob2@test.com", password_hash="h")

    @pytest.mark.asyncio
    async def test_email_unique(self):
        await User.create(username="carol", email="carol@test.com", password_hash="h")
        with pytest.raises(IntegrityError):
            await User.create(username="carol2", email="carol@test.com", password_hash="h")

    @pytest.mark.asyncio
    async def test_str_representation(self):
        user = await User.create(
            username="dave", email="dave@test.com", password_hash="h"
        )
        result = str(user)
        assert "dave" in result
        assert str(user.id) in result


# ---------------------------------------------------------------------------
# Deck model
# ---------------------------------------------------------------------------


class TestDeckModel:
    @pytest.mark.asyncio
    async def test_create_deck(self):
        user = await User.create(username="u1", email="u1@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Physics")

        assert deck.id is not None
        assert deck.title == "Physics"
        assert deck.description == ""
        assert deck.created_at is not None

    @pytest.mark.asyncio
    async def test_description_defaults_to_empty_string(self):
        user = await User.create(username="u2", email="u2@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Maths")
        assert deck.description == ""
        assert deck.description is not None

    @pytest.mark.asyncio
    async def test_cascade_delete_with_user(self):
        user = await User.create(username="u3", email="u3@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Bio")
        deck_id = deck.id

        await user.delete()
        assert await Deck.filter(id=deck_id).first() is None

    @pytest.mark.asyncio
    async def test_str_representation(self):
        user = await User.create(username="u4", email="u4@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Chemistry")
        result = str(deck)
        assert "Chemistry" in result


# ---------------------------------------------------------------------------
# Card model
# ---------------------------------------------------------------------------


class TestCardModel:
    @pytest.mark.asyncio
    async def test_create_card(self):
        user = await User.create(username="u5", email="u5@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Vocab")
        card = await Card.create(deck=deck, question="What is H2O?", answer="Water")

        assert card.id is not None
        assert card.question == "What is H2O?"
        assert card.answer == "Water"
        assert card.is_ai_generated is False
        assert card.created_at is not None

    @pytest.mark.asyncio
    async def test_ai_generated_flag(self):
        user = await User.create(username="u6", email="u6@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="AI Deck")
        card = await Card.create(
            deck=deck, question="Q", answer="A", is_ai_generated=True
        )
        assert card.is_ai_generated is True

    @pytest.mark.asyncio
    async def test_cascade_delete_with_deck(self):
        user = await User.create(username="u7", email="u7@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        card_id = card.id

        await deck.delete()
        assert await Card.filter(id=card_id).first() is None

    @pytest.mark.asyncio
    async def test_str_representation(self):
        user = await User.create(username="u8", email="u8@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Long question here", answer="A")
        result = str(card)
        assert "Long question" in result


# ---------------------------------------------------------------------------
# StudyProgress model
# ---------------------------------------------------------------------------


class TestStudyProgressModel:
    @pytest.mark.asyncio
    async def test_create_progress(self):
        user = await User.create(username="u9", email="u9@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        now = _utc()

        progress = await StudyProgress.create(
            user=user, card=card, next_review=now
        )
        assert progress.box == 1
        assert progress.last_result == "new"
        assert progress.streak == 0
        assert progress.lapse_count == 0

    @pytest.mark.asyncio
    async def test_unique_together_user_card(self):
        user = await User.create(username="u10", email="u10@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        now = _utc()

        await StudyProgress.create(user=user, card=card, next_review=now)
        with pytest.raises(IntegrityError):
            await StudyProgress.create(user=user, card=card, next_review=now)

    @pytest.mark.asyncio
    async def test_different_users_same_card(self):
        user_a = await User.create(username="u11", email="u11@t.com", password_hash="h")
        user_b = await User.create(username="u12", email="u12@t.com", password_hash="h")
        deck = await Deck.create(user=user_a, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        now = _utc()

        p1 = await StudyProgress.create(user=user_a, card=card, next_review=now)
        p2 = await StudyProgress.create(user=user_b, card=card, next_review=now)
        assert p1.id != p2.id

    @pytest.mark.asyncio
    async def test_cascade_delete_with_card(self):
        user = await User.create(username="u13", email="u13@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        progress = await StudyProgress.create(
            user=user, card=card, next_review=_utc()
        )
        progress_id = progress.id

        await card.delete()
        assert await StudyProgress.filter(id=progress_id).first() is None


# ---------------------------------------------------------------------------
# MCQQuestion model
# ---------------------------------------------------------------------------


class TestMCQQuestionModel:
    @pytest.mark.asyncio
    async def test_create_mcq(self):
        user = await User.create(username="u14", email="u14@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Quiz")
        mcq = await MCQQuestion.create(
            deck=deck,
            question="Capital of France?",
            option_a="London",
            option_b="Paris",
            option_c="Berlin",
            option_d="Madrid",
            correct_answer="B",
        )
        assert mcq.id is not None
        assert mcq.correct_answer == "B"
        assert mcq.explanation is None
        assert mcq.difficulty is None

    @pytest.mark.asyncio
    async def test_cascade_delete_with_deck(self):
        user = await User.create(username="u15", email="u15@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="Quiz")
        mcq = await MCQQuestion.create(
            deck=deck,
            question="Q",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_answer="A",
        )
        mcq_id = mcq.id

        await deck.delete()
        assert await MCQQuestion.filter(id=mcq_id).first() is None


# ---------------------------------------------------------------------------
# DailyActivity model
# ---------------------------------------------------------------------------


class TestDailyActivityModel:
    @pytest.mark.asyncio
    async def test_create_activity(self):
        user = await User.create(username="u16", email="u16@t.com", password_hash="h")
        activity = await DailyActivity.create(
            user=user, cards_reviewed=5, cards_correct=3
        )
        assert activity.id is not None
        assert activity.cards_reviewed == 5
        assert activity.cards_correct == 3
        assert activity.date is not None

    @pytest.mark.asyncio
    async def test_unique_together_user_date(self):
        user = await User.create(username="u17", email="u17@t.com", password_hash="h")
        await DailyActivity.create(user=user)
        with pytest.raises(IntegrityError):
            await DailyActivity.create(user=user)

    @pytest.mark.asyncio
    async def test_defaults(self):
        user = await User.create(username="u18", email="u18@t.com", password_hash="h")
        activity = await DailyActivity.create(user=user)
        assert activity.cards_reviewed == 0
        assert activity.cards_correct == 0


# ---------------------------------------------------------------------------
# DeckDailyActivity model
# ---------------------------------------------------------------------------


class TestDeckDailyActivityModel:
    @pytest.mark.asyncio
    async def test_create_deck_activity(self):
        user = await User.create(username="u19", email="u19@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        activity = await DeckDailyActivity.create(
            user=user, deck=deck, cards_reviewed=2, cards_correct=1
        )
        assert activity.id is not None

    @pytest.mark.asyncio
    async def test_unique_together_user_deck_date(self):
        user = await User.create(username="u20", email="u20@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        await DeckDailyActivity.create(user=user, deck=deck)
        with pytest.raises(IntegrityError):
            await DeckDailyActivity.create(user=user, deck=deck)


# ---------------------------------------------------------------------------
# ReviewEvent model
# ---------------------------------------------------------------------------


class TestReviewEventModel:
    @pytest.mark.asyncio
    async def test_create_event(self):
        user = await User.create(username="u21", email="u21@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")

        event = await ReviewEvent.create(
            user=user,
            deck=deck,
            card=card,
            correct=True,
            old_box=1,
            new_box=2,
            response_time_ms=1200,
        )
        assert event.id is not None
        assert event.correct is True
        assert event.response_time_ms == 1200
        assert event.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_null_response_time(self):
        user = await User.create(username="u22", email="u22@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")

        event = await ReviewEvent.create(
            user=user, deck=deck, card=card,
            correct=False, old_box=2, new_box=1,
        )
        assert event.response_time_ms is None

    @pytest.mark.asyncio
    async def test_cascade_delete_with_user(self):
        user = await User.create(username="u23", email="u23@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        event = await ReviewEvent.create(
            user=user, deck=deck, card=card,
            correct=True, old_box=1, new_box=2,
        )
        event_id = event.id

        await user.delete()
        assert await ReviewEvent.filter(id=event_id).first() is None


# ---------------------------------------------------------------------------
# UserSettings model
# ---------------------------------------------------------------------------


class TestUserSettingsModel:
    @pytest.mark.asyncio
    async def test_create_settings(self):
        user = await User.create(username="u24", email="u24@t.com", password_hash="h")
        settings = await UserSettings.create(user=user)

        assert settings.timezone == "UTC"
        assert settings.review_batch_size == 20
        assert settings.new_cards_per_session == 5
        assert settings.daily_goal == 20
        assert settings.week_start_day == "MON"

    @pytest.mark.asyncio
    async def test_custom_settings(self):
        user = await User.create(username="u25", email="u25@t.com", password_hash="h")
        settings = await UserSettings.create(
            user=user,
            timezone="Europe/London",
            review_batch_size=30,
            new_cards_per_session=10,
            daily_goal=50,
            week_start_day="SUN",
        )
        assert settings.timezone == "Europe/London"
        assert settings.review_batch_size == 30
        assert settings.week_start_day == "SUN"

    @pytest.mark.asyncio
    async def test_one_to_one_with_user(self):
        user = await User.create(username="u26", email="u26@t.com", password_hash="h")
        await UserSettings.create(user=user)
        with pytest.raises(IntegrityError):
            await UserSettings.create(user=user)

    @pytest.mark.asyncio
    async def test_cascade_delete_with_user(self):
        user = await User.create(username="u27", email="u27@t.com", password_hash="h")
        settings = await UserSettings.create(user=user)
        settings_id = settings.id

        await user.delete()
        assert await UserSettings.filter(id=settings_id).first() is None


# ---------------------------------------------------------------------------
# AIGenerationRun model
# ---------------------------------------------------------------------------


class TestAIGenerationRunModel:
    @pytest.mark.asyncio
    async def test_create_run(self):
        user = await User.create(username="u28", email="u28@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="AI Deck")

        run = await AIGenerationRun.create(
            user=user,
            deck=deck,
            kind="flashcards",
            input_type="notes",
            requested_count=10,
        )
        assert run.id is not None
        assert run.status == "pending"
        assert run.created_count == 0
        assert run.model_name == "gemini"
        assert run.created_at is not None
        assert run.updated_at is not None

    @pytest.mark.asyncio
    async def test_link_generated_cards(self):
        user = await User.create(username="u29", email="u29@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        run = await AIGenerationRun.create(
            user=user, deck=deck, kind="flashcards",
            input_type="notes", requested_count=2,
        )

        await Card.create(
            deck=deck, question="Q1", answer="A1",
            is_ai_generated=True, generation_run=run,
        )
        await Card.create(
            deck=deck, question="Q2", answer="A2",
            is_ai_generated=True, generation_run=run,
        )

        generated = await Card.filter(generation_run=run).all()
        assert len(generated) == 2

    @pytest.mark.asyncio
    async def test_link_generated_mcqs(self):
        user = await User.create(username="u30", email="u30@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        run = await AIGenerationRun.create(
            user=user, deck=deck, kind="mcq",
            input_type="deck", requested_count=1,
        )

        await MCQQuestion.create(
            deck=deck, question="Q", option_a="A", option_b="B",
            option_c="C", option_d="D", correct_answer="A",
            generation_run=run,
        )

        generated = await MCQQuestion.filter(generation_run=run).all()
        assert len(generated) == 1

    @pytest.mark.asyncio
    async def test_set_null_on_run_delete(self):
        user = await User.create(username="u31", email="u31@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        run = await AIGenerationRun.create(
            user=user, deck=deck, kind="flashcards",
            input_type="notes", requested_count=1,
        )
        card = await Card.create(
            deck=deck, question="Q", answer="A",
            is_ai_generated=True, generation_run=run,
        )

        await run.delete()

        card = await Card.filter(id=card.id).first()
        assert card is not None
        assert card.generation_run_id is None

    @pytest.mark.asyncio
    async def test_cascade_delete_with_user(self):
        user = await User.create(username="u32", email="u32@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        run = await AIGenerationRun.create(
            user=user, deck=deck, kind="flashcards",
            input_type="notes", requested_count=1,
        )
        run_id = run.id

        await user.delete()
        assert await AIGenerationRun.filter(id=run_id).first() is None


# ---------------------------------------------------------------------------
# Cross-model relationship queries
# ---------------------------------------------------------------------------


class TestRelationshipQueries:
    @pytest.mark.asyncio
    async def test_user_has_many_decks(self):
        user = await User.create(username="u33", email="u33@t.com", password_hash="h")
        await Deck.create(user=user, title="Deck 1")
        await Deck.create(user=user, title="Deck 2")

        decks = await Deck.filter(user=user).all()
        assert len(decks) == 2

    @pytest.mark.asyncio
    async def test_deck_has_many_cards(self):
        user = await User.create(username="u34", email="u34@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        await Card.create(deck=deck, question="Q1", answer="A1")
        await Card.create(deck=deck, question="Q2", answer="A2")
        await Card.create(deck=deck, question="Q3", answer="A3")

        cards = await Card.filter(deck=deck).all()
        assert len(cards) == 3

    @pytest.mark.asyncio
    async def test_full_cascade_user_to_events(self):
        user = await User.create(username="u35", email="u35@t.com", password_hash="h")
        deck = await Deck.create(user=user, title="D")
        card = await Card.create(deck=deck, question="Q", answer="A")
        await StudyProgress.create(user=user, card=card, next_review=_utc())
        await ReviewEvent.create(
            user=user, deck=deck, card=card,
            correct=True, old_box=1, new_box=2,
        )
        await DailyActivity.create(user=user, cards_reviewed=1)
        await DeckDailyActivity.create(user=user, deck=deck, cards_reviewed=1)
        await UserSettings.create(user=user)

        await user.delete()

        assert await Deck.all().count() == 0
        assert await Card.all().count() == 0
        assert await StudyProgress.all().count() == 0
        assert await ReviewEvent.all().count() == 0
        assert await DailyActivity.all().count() == 0
        assert await DeckDailyActivity.all().count() == 0
        assert await UserSettings.all().count() == 0
