"""Typed data models for Lesson Mode (bill-based lessons, RAG sections,
flashcards, quizzes, and persona-based personalization).

These are foundation models only. Nothing in this module is wired into API
routes or the frontend yet -- see docs/LESSON_MODE_ARCHITECTURE.md for the
rollout plan and where each model will eventually be used.
"""

from datetime import datetime, timezone
from enum import IntEnum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
    quiz_question_ids: List[str] = Field(default_factory=list)
    open_response_question_id: Optional[str] = None

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

class QuizQuestion(FirestoreModel):
    """A single grounded multiple-choice question generated for a lesson
    (Increment 5). `answer_choices` always has exactly one correct entry,
    at `correct_answer_index` -- the correct answer's own position is
    randomized per question at generation time, not fixed to index 0."""

    question_id: str
    lesson_id: str
    question: str = Field(min_length=1)
    answer_choices: List[str] = Field(min_length=2)
    correct_answer_index: int = Field(ge=0)
    explanation: str = Field(min_length=1)
    section_ids: List[str] = Field(min_length=1)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    question_type: Literal["vocabulary", "stakeholder_impact", "provision", "implementation"]


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
# Open-response question and grading (Increment 6)
# ---------------------------------------------------------------------------

class OpenResponseQuestion(FirestoreModel):
    """The single open-ended question generated for a lesson.

    `expected_points` and `context_excerpt` are grading inputs, not shown to
    the student before they answer -- see routes/lesson_routes.py's public
    response shape, which omits both.
    """

    question_id: str
    lesson_id: str
    question: str = Field(min_length=1)
    question_type: Literal[
        "stakeholder_perspective", "tradeoff", "pro_con_comparison",
        "implementation_challenge", "impact_prediction",
    ]
    expected_points: List[str] = Field(min_length=1)
    section_ids: List[str] = Field(min_length=1)
    context_excerpt: str = Field(min_length=1)


class OpenResponseAttempt(FirestoreModel):
    """A user's graded attempt at a lesson's open-response question."""

    attempt_id: str
    user_id: str
    lesson_id: str
    question_id: str
    student_answer: str
    score: int = Field(ge=0, le=3)
    feedback: str = Field(min_length=1)
    missed_points: List[str] = Field(default_factory=list)
    accurate_points: List[str] = Field(default_factory=list)
    section_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Personalization
# ---------------------------------------------------------------------------

# US states + DC, keyed by the two-letter USPS code we store. State is the
# only geographic field we collect -- never a city, address, or ZIP.
US_STATES: dict = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Broad ranges only -- deliberately never an exact age.
AGE_RANGES: List[str] = [
    "Under 18", "18-24", "25-34", "35-44", "45-54", "55-64", "65+",
]

# Broad household-income brackets only -- deliberately never an exact figure.
INCOME_BRACKETS: List[str] = [
    "Under $25,000",
    "$25,000-$49,999",
    "$50,000-$99,999",
    "$100,000-$199,999",
    "$200,000 or more",
]

# Broad occupation categories the UI offers as chips. Occupation is the one
# field that also accepts free text (a student may type a specific role or an
# intended future occupation), so this list is a suggestion set, not a
# closed enum -- see `PersonaProfile.occupation`.
OCCUPATION_CATEGORIES: List[str] = [
    "Student",
    "Educator",
    "Healthcare",
    "Service industry",
    "Skilled trades",
    "Technology",
    "Business or finance",
    "Government or public sector",
    "Arts or media",
    "Retired",
    "Not currently working",
    "Other",
]

OCCUPATION_MAX_LENGTH = 80


class PersonaProfile(FirestoreModel):
    """A lightweight, optional persona a student builds for personalized
    lessons (Increment 7).

    Every field except ``user_id`` is optional -- a student may fill in one
    field, all of them, or none, and the persona may be entirely fictional.
    By design this model collects only *broad* attributes and deliberately
    has no field for exact age, exact income, home address, employer name,
    race, religion, health information, or political affiliation.

    ``state`` is stored as a two-letter USPS code; ``age_range`` and
    ``income_bracket`` must be one of the broad predefined choices
    (``AGE_RANGES`` / ``INCOME_BRACKETS``). ``occupation`` accepts either a
    broad category from ``OCCUPATION_CATEGORIES`` or free text (e.g. an
    intended future role), capped at ``OCCUPATION_MAX_LENGTH`` characters.
    """

    user_id: str
    occupation: Optional[str] = None
    state: Optional[str] = None
    age_range: Optional[str] = None
    income_bracket: Optional[str] = None

    @field_validator("occupation", mode="before")
    @classmethod
    def _normalize_occupation(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if len(value) > OCCUPATION_MAX_LENGTH:
            raise ValueError(
                f"occupation must be at most {OCCUPATION_MAX_LENGTH} characters"
            )
        return value

    @field_validator("state", mode="before")
    @classmethod
    def _normalize_state(cls, value):
        if value is None:
            return None
        value = str(value).strip().upper()
        if not value:
            return None
        if value not in US_STATES:
            raise ValueError(f"state must be a two-letter US state code, got {value!r}")
        return value

    @field_validator("age_range", mode="before")
    @classmethod
    def _validate_age_range(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if value not in AGE_RANGES:
            raise ValueError(f"age_range must be one of {AGE_RANGES}, got {value!r}")
        return value

    @field_validator("income_bracket", mode="before")
    @classmethod
    def _validate_income_bracket(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if value not in INCOME_BRACKETS:
            raise ValueError(
                f"income_bracket must be one of {INCOME_BRACKETS}, got {value!r}"
            )
        return value

    def is_empty(self) -> bool:
        """True when the student saved a persona with no attributes at all."""
        return not any(
            (self.occupation, self.state, self.age_range, self.income_bracket)
        )

    def to_impact_representation(self) -> dict:
        """A stable, self-describing representation for the (future)
        personal-impact generator (Increment 8).

        Returns the structured attributes that are set, a plain-language
        descriptor the generator can drop into a prompt, and an explicit
        ``is_fictional`` flag so downstream code never treats the persona as
        verified personal data. Never raises; unset fields are simply omitted.
        """
        attributes: dict = {}
        if self.occupation:
            attributes["occupation"] = self.occupation
        if self.state:
            attributes["state"] = self.state
            attributes["state_name"] = US_STATES[self.state]
        if self.age_range:
            attributes["age_range"] = self.age_range
        if self.income_bracket:
            attributes["income_bracket"] = self.income_bracket

        parts: List[str] = []
        if self.occupation:
            parts.append(f"works or intends to work in {self.occupation.lower()}")
        if self.state:
            parts.append(f"lives in {US_STATES[self.state]}")
        if self.age_range:
            parts.append(f"is in the {self.age_range} age range")
        if self.income_bracket:
            parts.append(f"has a household income of {self.income_bracket}")

        if parts:
            descriptor = "A person who " + ", ".join(parts) + "."
        else:
            descriptor = ""

        return {
            "has_persona": bool(attributes),
            "attributes": attributes,
            "descriptor": descriptor,
            # Personas are explicitly allowed to be fictional; the generator
            # must not present impacts as factual claims about a real person.
            "is_fictional": True,
        }

    @staticmethod
    def field_options() -> dict:
        """The choice sets and privacy disclaimer the persona builder UI needs.

        Kept next to the model so the frontend's dropdowns and the backend's
        validation can never drift apart.
        """
        return {
            "occupation_suggestions": list(OCCUPATION_CATEGORIES),
            "occupation_allows_custom": True,
            "occupation_max_length": OCCUPATION_MAX_LENGTH,
            "states": [{"code": c, "name": n} for c, n in US_STATES.items()],
            "age_ranges": list(AGE_RANGES),
            "income_brackets": list(INCOME_BRACKETS),
            "all_fields_optional": True,
            "persona_may_be_fictional": True,
            "not_collected": [
                "exact age",
                "exact income",
                "home address",
                "employer name",
                "race",
                "religion",
                "health information",
                "political affiliation",
            ],
        }


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
