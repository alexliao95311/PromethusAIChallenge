"""Typed data models for Lesson Mode (bill-based lessons, RAG sections,
flashcards, quizzes, and persona-based personalization).

These are foundation models only. Nothing in this module is wired into API
routes or the frontend yet -- see docs/LESSON_MODE_ARCHITECTURE.md for the
rollout plan and where each model will eventually be used.
"""

from datetime import datetime, timezone
from enum import IntEnum
from typing import List, Literal, Optional

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


class GroundedClaim(FirestoreModel):
    """A single factual claim tied to the bill section(s) that support it."""

    claim: str = Field(min_length=1)
    section_ids: List[str] = Field(min_length=1)


class Lesson(FirestoreModel):
    """A generated, grounded lesson for a bill (Increment 2).

    Every factual item (provision, stakeholder impact, pro/con argument) is
    a `GroundedClaim` citing the bill section_id(s) it's derived from, so a
    lesson can always be traced back to source text.
    """

    lesson_id: str
    bill_id: str
    prompt_version: str
    bill_text_hash: str

    lesson_title: str = Field(min_length=1)
    plain_language_summary: str = Field(min_length=1)
    learning_objectives: List[str] = Field(default_factory=list)
    major_provisions: List[GroundedClaim] = Field(default_factory=list)
    stakeholders: List[GroundedClaim] = Field(default_factory=list)
    pro_arguments: List[GroundedClaim] = Field(default_factory=list)
    con_arguments: List[GroundedClaim] = Field(default_factory=list)
    source_sections: List[str] = Field(default_factory=list)
    vocabulary_card_ids: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Flashcards / Leitner spaced-repetition system
# ---------------------------------------------------------------------------

class Flashcard(FirestoreModel):
    """A bill-specific vocabulary card grounded in a single bill section
    (Increment 3). `difficulty` reflects how conceptually hard the term is
    for a high-school student, not its Leitner review state (see
    `UserCardProgress`)."""

    card_id: str
    lesson_id: str
    term: str = Field(min_length=1, max_length=60)
    simple_definition: str = Field(min_length=1)
    bill_context: str = Field(min_length=1)
    example: str = Field(min_length=1)
    section_id: str
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"


class LeitnerBox(IntEnum):
    """The three Leitner boxes (Increment 4). Box 1 is due every session,
    Box 2 every third session, Box 3 every seventh session -- see
    `services/flashcard_review.py` for the due-date math."""

    BOX_1 = 1
    BOX_2 = 2
    BOX_3 = 3


class UserCardProgress(FirestoreModel):
    """A single user's Leitner-system progress on a single flashcard.

    Session numbers (not wall-clock time) drive scheduling: `last_reviewed_session`
    and `next_due_session` refer to a lesson's review-session counter (see
    `LessonProgress.current_session`), not calendar days.
    """

    user_id: str
    card_id: str
    leitner_box: int = Field(default=1, ge=1, le=3)
    correct_count: int = Field(default=0, ge=0)
    incorrect_count: int = Field(default=0, ge=0)
    last_reviewed_session: Optional[int] = Field(default=None, ge=1)
    next_due_session: int = Field(default=1, ge=1)


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
    """A user's overall progress through a single lesson (vocab + quizzes).

    `current_session` is the Leitner review-session counter for this user +
    lesson (Increment 4): 0 means the user has never started a review
    session yet; each explicit "start a new session" action increments it.
    """

    user_id: str
    lesson_id: str
    vocab_mastered: int = Field(default=0, ge=0)
    vocab_total: int = Field(default=0, ge=0)
    quiz_attempts: int = Field(default=0, ge=0)
    best_quiz_score: Optional[float] = Field(default=None, ge=0, le=100)
    completed: bool = False
    current_session: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=_utcnow)
