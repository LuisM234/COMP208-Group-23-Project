from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone

from tortoise import Model, fields
from tortoise.fields import ForeignKeyRelation, OneToOneRelation, ReverseRelation

# Database schema for the flashcard application.

# Tables:
#   users, user_settings          – accounts & preferences
#   decks, cards, mcq_questions   – content
#   study_progress                – Leitner scheduling state
#   daily_activity, deck_daily_activity – aggregated analytics
#   review_events                 – per-review analytics (source of truth)
#   ai_generation_runs            – AI generation audit log


def utc_now() -> datetime:
    """Return the current moment in UTC."""
    return datetime.now(timezone.utc)


def utc_today() -> date_type:
    """Return today's date in UTC."""
    return utc_now().date()


# ------------------------------------------------------------------
# Valid value sets (used for application-level validation)
# ------------------------------------------------------------------

VALID_LAST_RESULTS = {"new", "correct", "wrong"}
VALID_CORRECT_ANSWERS = {"A", "B", "C", "D"}
VALID_WEEK_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
VALID_GENERATION_KINDS = {"flashcards", "mcq"}
VALID_INPUT_TYPES = {"notes", "deck"}
VALID_GENERATION_STATUSES = {"pending", "success", "failed", "rate_limited", "invalid_json"}


# ---------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------


class User(Model):
    """User accounts."""

    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=50, unique=True, index=True)
    email = fields.CharField(max_length=255, unique=True, index=True)
    password_hash = fields.CharField(max_length=255)
    created_at = fields.DatetimeField(default=utc_now)

    # Reverse relations
    settings: OneToOneRelation["UserSettings"]
    decks: ReverseRelation["Deck"]
    daily_activities: ReverseRelation["DailyActivity"]
    deck_daily_activities: ReverseRelation["DeckDailyActivity"]
    study_progress_entries: ReverseRelation["StudyProgress"]
    review_events: ReverseRelation["ReviewEvent"]
    generation_runs: ReverseRelation["AIGenerationRun"]

    class Meta:
        table = "users"

    def __str__(self) -> str:
        return f"User(id={self.id}, username={self.username!r})"


class Deck(Model):
    """Flashcard decks owned by a user."""

    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=255)
    # Empty string instead of NULL to avoid None-vs-"" ambiguity.
    description = fields.TextField(default="")
    created_at = fields.DatetimeField(default=utc_now)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="decks",
        on_delete=fields.CASCADE,
    )

    # Reverse relations
    cards: ReverseRelation["Card"]
    mcq_questions: ReverseRelation["MCQQuestion"]
    daily_activity_entries: ReverseRelation["DeckDailyActivity"]
    review_events: ReverseRelation["ReviewEvent"]
    generation_runs: ReverseRelation["AIGenerationRun"]

    class Meta:
        table = "decks"

    def __str__(self) -> str:
        return f"Deck(id={self.id}, title={self.title!r})"


class Card(Model):
    """Individual flashcards belonging to a deck."""

    id = fields.IntField(pk=True)
    question = fields.TextField()
    answer = fields.TextField()
    is_ai_generated = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(default=utc_now)
    deck: ForeignKeyRelation[Deck] = fields.ForeignKeyField(
        "models.Deck",
        related_name="cards",
        on_delete=fields.CASCADE,
    )
    # NULL for manually-created cards (no associated AI run).
    generation_run: ForeignKeyRelation["AIGenerationRun"] | None = fields.ForeignKeyField(
        "models.AIGenerationRun",
        related_name="generated_cards",
        on_delete=fields.SET_NULL,
        null=True,
    )

    # Reverse relations
    study_progress_entries: ReverseRelation["StudyProgress"]
    review_events: ReverseRelation["ReviewEvent"]

    class Meta:
        table = "cards"

    def __str__(self) -> str:
        return f"Card(id={self.id}, question={self.question[:40]!r})"


# ---------------------------------------------------------------
# Study scheduling (Leitner system)
# ---------------------------------------------------------------


class StudyProgress(Model):
    """Leitner scheduling state for each (user, card) pair."""

    id = fields.IntField(pk=True)
    box = fields.IntField(default=1)
    next_review = fields.DatetimeField(index=True)
    last_reviewed = fields.DatetimeField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)
    lapse_count = fields.IntField(default=0)
    streak = fields.IntField(default=0)
    # Allowed values: new | correct | wrong  (validated in service layer)
    last_result = fields.CharField(max_length=16, default="new")
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="study_progress_entries",
        on_delete=fields.CASCADE,
    )
    card: ForeignKeyRelation[Card] = fields.ForeignKeyField(
        "models.Card",
        related_name="study_progress_entries",
        on_delete=fields.CASCADE,
        index=True,  # Allows efficient lookup of all progress rows for a card
    )

    class Meta:
        table = "study_progress"
        unique_together = (("user", "card"),)
        indexes = (("user", "next_review"),)

    def __str__(self) -> str:
        return f"StudyProgress(id={self.id}, user_id={self.user.id}, card_id={self.card.id})"


# --------------------------------------------------------------
# Content – MCQ questions
# --------------------------------------------------------------


class MCQQuestion(Model):
    """AI-generated multiple-choice questions linked to a deck."""

    id = fields.IntField(pk=True)
    question = fields.TextField()
    option_a = fields.TextField()
    option_b = fields.TextField()
    option_c = fields.TextField()
    option_d = fields.TextField()
    # Must be one of A, B, C, D (validated in service layer).
    correct_answer = fields.CharField(max_length=1)
    explanation = fields.TextField(null=True)
    # Optional difficulty label from the generation request.
    difficulty = fields.CharField(max_length=16, null=True)
    created_at = fields.DatetimeField(default=utc_now)
    deck: ForeignKeyRelation[Deck] = fields.ForeignKeyField(
        "models.Deck",
        related_name="mcq_questions",
        on_delete=fields.CASCADE,
    )
    # NULL when MCQs are seeded/imported outside an AI run.
    generation_run: ForeignKeyRelation["AIGenerationRun"] | None = fields.ForeignKeyField(
        "models.AIGenerationRun",
        related_name="generated_mcqs",
        on_delete=fields.SET_NULL,
        null=True,
    )

    class Meta:
        table = "mcq_questions"
        indexes = (
            ("deck", "created_at"),
            ("deck", "difficulty", "created_at"),
        )

    def __str__(self) -> str:
        return f"MCQQuestion(id={self.id}, question={self.question[:40]!r})"


# -------------------------------------------------------------------
# Analytics – daily aggregates
# -------------------------------------------------------------------


class DailyActivity(Model):
    """Per-user daily review totals across all decks."""

    id = fields.IntField(pk=True)
    date = fields.DateField(default=utc_today)
    cards_reviewed = fields.IntField(default=0)
    cards_correct = fields.IntField(default=0)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="daily_activities",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "daily_activity"
        # unique_together already creates a composite index on (user, date),
        # so no separate indexes entry is needed.
        unique_together = (("user", "date"),)

    def __str__(self) -> str:
        return f"DailyActivity(id={self.id}, date={self.date.isoformat()})"


class DeckDailyActivity(Model):
    """Per-user, per-deck daily review totals."""

    id = fields.IntField(pk=True)
    date = fields.DateField(default=utc_today)
    cards_reviewed = fields.IntField(default=0)
    cards_correct = fields.IntField(default=0)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="deck_daily_activities",
        on_delete=fields.CASCADE,
    )
    deck: ForeignKeyRelation[Deck] = fields.ForeignKeyField(
        "models.Deck",
        related_name="daily_activity_entries",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "deck_daily_activity"
        # unique_together already creates an index on (user, deck, date).
        # Only the (user, date) index is added since it's a different column set.
        unique_together = (("user", "deck", "date"),)
        indexes = (("user", "date"),)

    def __str__(self) -> str:
        return (
            f"DeckDailyActivity(id={self.id}, user_id={self.user.id}, "
            f"deck_id={self.deck.id}, date={self.date.isoformat()})"
        )


# ----------------------------------------------------------------
# Analytics – individual review events (source of truth)
# ----------------------------------------------------------------


class ReviewEvent(Model):
    """One row per review attempt – the analytics source of truth."""

    id = fields.IntField(pk=True)
    reviewed_at = fields.DatetimeField(default=utc_now, index=True)
    correct = fields.BooleanField()
    old_box = fields.IntField()
    new_box = fields.IntField()
    # Client-reported response time; NULL when not available.
    # Validate >= 0 in the service layer.
    response_time_ms = fields.IntField(null=True)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="review_events",
        on_delete=fields.CASCADE,
    )
    deck: ForeignKeyRelation[Deck] = fields.ForeignKeyField(
        "models.Deck",
        related_name="review_events",
        on_delete=fields.CASCADE,
    )
    card: ForeignKeyRelation[Card] = fields.ForeignKeyField(
        "models.Card",
        related_name="review_events",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "review_events"
        indexes = (
            ("user", "reviewed_at"),
            ("user", "deck", "reviewed_at"),
            ("deck", "reviewed_at"),
        )

    def __str__(self) -> str:
        return (
            f"ReviewEvent(id={self.id}, user_id={self.user.id}, card_id={self.card.id}, "
            f"correct={self.correct})"
        )


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------


class UserSettings(Model):
    """Per-user study and analytics preferences."""

    id = fields.IntField(pk=True)
    user: OneToOneRelation[User] = fields.OneToOneField(
        "models.User",
        related_name="settings",
        on_delete=fields.CASCADE,
    )
    timezone = fields.CharField(max_length=64, default="UTC")
    review_batch_size = fields.IntField(default=20)
    new_cards_per_session = fields.IntField(default=5)
    daily_goal = fields.IntField(default=20)
    # Must be one of MON, TUE, WED, THU, FRI, SAT, SUN (validated in service layer).
    week_start_day = fields.CharField(max_length=3, default="MON")

    class Meta:
        table = "user_settings"

    def __str__(self) -> str:
        return (
            f"UserSettings(id={self.id}, user_id={self.user.id}, "
            f"review_batch_size={self.review_batch_size})"
        )


# -------------------------------------------------------------
# AI generation audit log
# -------------------------------------------------------------


class AIGenerationRun(Model):
    """Audit record for a single AI generation request and its outcome."""

    id = fields.IntField(pk=True)
    # Allowed values: flashcards | mcq  (validated in service layer)
    kind = fields.CharField(max_length=24)
    # Allowed values: notes | deck  (validated in service layer)
    input_type = fields.CharField(max_length=16)
    requested_count = fields.IntField()
    created_count = fields.IntField(default=0)
    difficulty = fields.CharField(max_length=16, null=True)
    model_name = fields.CharField(max_length=64, default="gemini")
    # Allowed values: pending | success | failed | rate_limited | invalid_json
    status = fields.CharField(max_length=24, default="pending")
    error_code = fields.IntField(max_length=64, null=True)
    error_message = fields.TextField(null=True)
    raw_response = fields.TextField(null=True)
    created_at = fields.DatetimeField(default=utc_now)
    updated_at = fields.DatetimeField(auto_now=True)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="generation_runs",
        on_delete=fields.CASCADE,
    )
    deck: ForeignKeyRelation[Deck] | None = fields.ForeignKeyField(
        "models.Deck",
        related_name="generation_runs",
        on_delete=fields.CASCADE,
        null=True,
    )

    # Reverse relations
    generated_cards: ReverseRelation[Card]
    generated_mcqs: ReverseRelation[MCQQuestion]

    class Meta:
        table = "ai_generation_runs"
        indexes = (
            ("user", "created_at"),
            ("user", "kind", "created_at"),
            ("deck", "created_at"),
            ("status", "created_at"),
        )

    def __str__(self) -> str:
        return (
            f"AIGenerationRun(id={self.id}, user_id={self.user.id}, kind={self.kind!r}, "
            f"status={self.status!r})"
        )
