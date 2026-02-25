from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone

from tortoise import Model, fields
from tortoise.fields import ForeignKeyRelation, OneToOneRelation, ReverseRelation

# Central schema file for the backend.
# Keep every table here so migrations are generated from one module.
# All timestamps are stored in UTC.


def utc_now() -> datetime:
    # Consistent UTC timestamp default for datetime fields.
    return datetime.now(timezone.utc)


def utc_today() -> date_type:
    # UTC date default for daily aggregate rows.
    return utc_now().date()


class User(Model):
    # Login identity. A user owns decks, settings, study progress, and analytics rows.
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=50, unique=True, index=True)
    email = fields.CharField(max_length=255, unique=True, index=True)
    password_hash = fields.CharField(max_length=255)
    created_at = fields.DatetimeField(default=utc_now)

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
    # Named collection of cards owned by one user.
    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=255)
    description = fields.TextField(null=True)
    created_at = fields.DatetimeField(default=utc_now)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="decks",
        on_delete=fields.CASCADE,
    )

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
    # One flashcard (question/answer) inside a deck.
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
    # Set only when card was created by the AI generation flow.
    generation_run: ForeignKeyRelation["AIGenerationRun"] = fields.ForeignKeyField(
        "models.AIGenerationRun",
        related_name="generated_cards",
        on_delete=fields.SET_NULL,
        null=True,
    )

    study_progress_entries: ReverseRelation["StudyProgress"]
    review_events: ReverseRelation["ReviewEvent"]

    class Meta:
        table = "cards"

    def __str__(self) -> str:
        return f"Card(id={self.id}, question={self.question[:40]!r})"


class StudyProgress(Model):
    # Leitner state for one user + one card.
    # This drives due-card queries and review scheduling.
    id = fields.IntField(pk=True)
    box = fields.IntField(default=1)
    next_review = fields.DatetimeField(index=True)
    last_reviewed = fields.DatetimeField(null=True)
    lapse_count = fields.IntField(default=0)
    streak = fields.IntField(default=0)
    # Last outcome stored as text for quick UI/analytics reads.
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
    )

    class Meta:
        table = "study_progress"
        unique_together = (("user", "card"),)
        indexes = (("user", "next_review"),)

    def __str__(self) -> str:
        return f"StudyProgress(id={self.id}, user_id={self.user_id}, card_id={self.card_id})"


class MCQQuestion(Model):
    # One generated MCQ row tied to a deck.
    # Options are stored as four fixed columns for simpler reads.
    id = fields.IntField(pk=True)
    question = fields.TextField()
    option_a = fields.TextField()
    option_b = fields.TextField()
    option_c = fields.TextField()
    option_d = fields.TextField()
    correct_answer = fields.CharField(max_length=1)
    explanation = fields.TextField(null=True)
    # Difficulty is optional and comes from the generation request.
    difficulty = fields.CharField(max_length=16, null=True)
    created_at = fields.DatetimeField(default=utc_now)
    deck: ForeignKeyRelation[Deck] = fields.ForeignKeyField(
        "models.Deck",
        related_name="mcq_questions",
        on_delete=fields.CASCADE,
    )
    # Set only when this MCQ came from an AI generation run.
    generation_run: ForeignKeyRelation["AIGenerationRun"] = fields.ForeignKeyField(
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


class DailyActivity(Model):
    # Per-user daily totals across all decks.
    # Used for week/month line charts.
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
        unique_together = (("user", "date"),)
        indexes = (("user", "date"),)

    def __str__(self) -> str:
        return f"DailyActivity(id={self.id}, date={self.date.isoformat()})"


class DeckDailyActivity(Model):
    # Same daily totals as DailyActivity, split by deck.
    # Used for "deck breakdown" below analytics charts.
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
        unique_together = (("user", "deck", "date"),)
        indexes = (
            ("user", "date"),
            ("user", "deck", "date"),
        )

    def __str__(self) -> str:
        return (
            f"DeckDailyActivity(id={self.id}, user_id={self.user_id}, "
            f"deck_id={self.deck_id}, date={self.date.isoformat()})"
        )


class ReviewEvent(Model):
    # Immutable log of every review action.
    # This is the source-of-truth table for detailed analytics.
    id = fields.IntField(pk=True)
    reviewed_at = fields.DatetimeField(default=utc_now, index=True)
    correct = fields.BooleanField()
    old_box = fields.IntField()
    new_box = fields.IntField()
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
            f"ReviewEvent(id={self.id}, user_id={self.user_id}, card_id={self.card_id}, "
            f"correct={self.correct})"
        )


class UserSettings(Model):
    # Per-user preferences for study flow and analytics display.
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
    week_start_day = fields.CharField(max_length=3, default="MON")

    class Meta:
        table = "user_settings"

    def __str__(self) -> str:
        return (
            f"UserSettings(id={self.id}, user_id={self.user_id}, "
            f"review_batch_size={self.review_batch_size})"
        )


class AIGenerationRun(Model):
    # One Gemini request record.
    # Stores status, errors, and counts so failures are traceable.
    id = fields.IntField(pk=True)
    # Expected values: flashcards | mcq
    kind = fields.CharField(max_length=24)
    # Expected values: notes | deck
    input_type = fields.CharField(max_length=16)
    requested_count = fields.IntField()
    created_count = fields.IntField(default=0)
    difficulty = fields.CharField(max_length=16, null=True)
    model_name = fields.CharField(max_length=64, default="gemini")
    # Typical values: pending | success | failed | rate_limited | invalid_json
    status = fields.CharField(max_length=24, default="pending")
    error_code = fields.CharField(max_length=64, null=True)
    error_message = fields.TextField(null=True)
    raw_response = fields.TextField(null=True)
    created_at = fields.DatetimeField(default=utc_now)
    updated_at = fields.DatetimeField(auto_now=True)
    user: ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User",
        related_name="generation_runs",
        on_delete=fields.CASCADE,
    )
    deck: ForeignKeyRelation[Deck] = fields.ForeignKeyField(
        "models.Deck",
        related_name="generation_runs",
        on_delete=fields.CASCADE,
        null=True,
    )

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
            f"AIGenerationRun(id={self.id}, user_id={self.user_id}, kind={self.kind!r}, "
            f"status={self.status!r})"
        )
