"""Typed data models for Lesson Mode (bill-based lessons, RAG sections,
flashcards, quizzes, and persona-based personalization).

These are foundation models only. Nothing in this module is wired into API
routes or the frontend yet -- see docs/LESSON_MODE_ARCHITECTURE.md for the
rollout plan and where each model will eventually be used.
"""

from datetime import datetime, timezone
from enum import IntEnum
from typing import List, Optional

from pydantic import BaseModel, Field


class FirestoreModel(BaseModel):
    """Base class adding Firestore-safe (de)serialization to Pydantic models.

    Firestore documents must be plain JSON-compatible dicts, so we round-trip
    through Pydantic's "json" dump mode (datetimes -> ISO strings, enums ->
    values) rather than handing raw Python objects to the client.
    """

    def to_firestore_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_firestore_dict(cls, data: dict) -> "FirestoreModel":
        return cls.model_validate(data)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Bill content / RAG pipeline
# ---------------------------------------------------------------------------

class BillSection(FirestoreModel):
    """A single chunk of a bill's text -- the unit of retrieval for RAG."""

    section_id: str
    bill_id: str
    heading: str
    text: str = Field(min_length=1)
    order: int = Field(ge=0)
    embedding: Optional[List[float]] = None


class Lesson(FirestoreModel):
    """A generated lesson for a bill: summary, stakeholders, and arguments."""

    lesson_id: str
    bill_id: str
    summary: str
    stakeholders: List[str] = Field(default_factory=list)
    pro_arguments: List[str] = Field(default_factory=list)
    con_arguments: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Flashcards / Leitner spaced-repetition system
# ---------------------------------------------------------------------------

class Flashcard(FirestoreModel):
    """A term/definition card grounded in a specific bill section."""

    card_id: str
    lesson_id: str
    term: str
    definition: str
    section_id: str


class LeitnerBox(IntEnum):
    """The five Leitner boxes; higher box = better mastery, longer interval."""

    BOX_1 = 1
    BOX_2 = 2
    BOX_3 = 3
    BOX_4 = 4
    BOX_5 = 5


class UserCardProgress(FirestoreModel):
    """A single user's Leitner-system progress on a single flashcard."""

    user_id: str
    card_id: str
    leitner_box: int = Field(default=1, ge=1, le=5)
    correct_count: int = Field(default=0, ge=0)
    last_reviewed: Optional[datetime] = None
    next_review_session: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------

class QuizAnswer(FirestoreModel):
    """A single answer within a quiz attempt."""

    question_id: str
    response: str
    is_correct: Optional[bool] = None


class QuizAttempt(FirestoreModel):
    """A user's full attempt at a lesson's quiz, with score and feedback."""

    attempt_id: str
    user_id: str
    lesson_id: str
    score: float = Field(ge=0, le=100)
    answers: List[QuizAnswer] = Field(default_factory=list)
    feedback: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Personalization
# ---------------------------------------------------------------------------

class PersonaProfile(FirestoreModel):
    """A lightweight persona the student builds for personalized lessons."""

    user_id: str
    occupation: Optional[str] = None
    state: Optional[str] = None
    age_range: Optional[str] = None
    income_bracket: Optional[str] = None


class LessonProgress(FirestoreModel):
    """A user's overall progress through a single lesson (vocab + quizzes)."""

    user_id: str
    lesson_id: str
    vocab_mastered: int = Field(default=0, ge=0)
    vocab_total: int = Field(default=0, ge=0)
    quiz_attempts: int = Field(default=0, ge=0)
    best_quiz_score: Optional[float] = Field(default=None, ge=0, le=100)
    completed: bool = False
    updated_at: datetime = Field(default_factory=_utcnow)
