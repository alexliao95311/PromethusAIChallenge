"""Unit tests for Lesson Mode data models: validation and serialization.

Covers the "Automated" test plan from Increment 0:
- valid instances of every model
- rejection of missing required fields
- serialization into Firestore-safe dictionaries
- round-tripping through a mocked Firestore repository
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.lesson_models import (
    BillSection,
    Lesson,
    Flashcard,
    LeitnerBox,
    UserCardProgress,
    QuizAnswer,
    QuizAttempt,
    PersonaProfile,
    LessonProgress,
)
from services.lesson_repository import LessonRepository
from tests.fake_firestore import FakeFirestoreClient


# ---------------------------------------------------------------------------
# Valid instantiation
# ---------------------------------------------------------------------------

def test_bill_section_valid_instance():
    section = BillSection(
        section_id="hr1-sec-1",
        bill_id="hr1",
        heading="Short Title",
        text="This Act may be cited as the Example Act.",
        order=0,
    )
    assert section.section_id == "hr1-sec-1"
    assert section.embedding is None


def test_lesson_valid_instance():
    lesson = Lesson(
        lesson_id="hr1-lesson",
        bill_id="hr1",
        summary="A bill about examples.",
        stakeholders=["Students", "Teachers"],
        pro_arguments=["Improves access"],
        con_arguments=["Costly to implement"],
    )
    assert lesson.bill_id == "hr1"
    assert isinstance(lesson.created_at, datetime)


def test_flashcard_valid_instance():
    card = Flashcard(
        card_id="card-1",
        lesson_id="hr1-lesson",
        term="Quorum",
        definition="The minimum number of members required to conduct business.",
        section_id="hr1-sec-1",
    )
    assert card.term == "Quorum"


def test_user_card_progress_defaults():
    progress = UserCardProgress(user_id="u1", card_id="card-1")
    assert progress.leitner_box == 1
    assert progress.correct_count == 0
    assert progress.last_reviewed is None
    assert progress.next_review_session == 1


def test_quiz_attempt_valid_instance():
    attempt = QuizAttempt(
        attempt_id="attempt-1",
        user_id="u1",
        lesson_id="hr1-lesson",
        score=87.5,
        answers=[QuizAnswer(question_id="q1", response="A", is_correct=True)],
        feedback="Good grasp of the vocabulary.",
    )
    assert attempt.score == 87.5
    assert attempt.answers[0].is_correct is True


def test_persona_profile_all_fields_optional_except_user_id():
    profile = PersonaProfile(user_id="u1")
    assert profile.occupation is None
    assert profile.state is None


def test_lesson_progress_valid_instance():
    progress = LessonProgress(
        user_id="u1",
        lesson_id="hr1-lesson",
        vocab_mastered=3,
        vocab_total=10,
        quiz_attempts=1,
        best_quiz_score=75.0,
    )
    assert progress.completed is False


# ---------------------------------------------------------------------------
# Rejection of missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model_cls, kwargs",
    [
        (BillSection, {"bill_id": "hr1", "heading": "x", "text": "y", "order": 0}),  # missing section_id
        (Lesson, {"bill_id": "hr1", "summary": "s"}),  # missing lesson_id
        (Flashcard, {"lesson_id": "l1", "term": "t", "definition": "d"}),  # missing card_id/section_id
        (UserCardProgress, {"card_id": "c1"}),  # missing user_id
        (QuizAttempt, {"user_id": "u1", "lesson_id": "l1", "score": 50}),  # missing attempt_id
        (PersonaProfile, {}),  # missing user_id
        (LessonProgress, {"lesson_id": "l1"}),  # missing user_id
    ],
)
def test_missing_required_fields_rejected(model_cls, kwargs):
    with pytest.raises(ValidationError):
        model_cls(**kwargs)


def test_bill_section_rejects_empty_text():
    with pytest.raises(ValidationError):
        BillSection(section_id="s1", bill_id="b1", heading="h", text="", order=0)


def test_user_card_progress_rejects_out_of_range_leitner_box():
    with pytest.raises(ValidationError):
        UserCardProgress(user_id="u1", card_id="c1", leitner_box=6)


def test_quiz_attempt_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        QuizAttempt(attempt_id="a1", user_id="u1", lesson_id="l1", score=150)


def test_leitner_box_enum_values():
    assert list(LeitnerBox) == [
        LeitnerBox.BOX_1,
        LeitnerBox.BOX_2,
        LeitnerBox.BOX_3,
        LeitnerBox.BOX_4,
        LeitnerBox.BOX_5,
    ]


# ---------------------------------------------------------------------------
# Firestore-safe serialization
# ---------------------------------------------------------------------------

def test_lesson_serializes_datetime_to_iso_string():
    lesson = Lesson(
        lesson_id="l1",
        bill_id="b1",
        summary="s",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
    )
    data = lesson.to_firestore_dict()
    assert isinstance(data["created_at"], str)
    assert data["created_at"].startswith("2026-07-20")


def test_bill_section_round_trips_through_firestore_dict():
    section = BillSection(
        section_id="s1",
        bill_id="b1",
        heading="h",
        text="t",
        order=2,
        embedding=[0.1, 0.2, 0.3],
    )
    data = section.to_firestore_dict()
    assert data == {
        "section_id": "s1",
        "bill_id": "b1",
        "heading": "h",
        "text": "t",
        "order": 2,
        "embedding": [0.1, 0.2, 0.3],
    }
    restored = BillSection.from_firestore_dict(data)
    assert restored == section


# ---------------------------------------------------------------------------
# Mocked Firestore repository: create + retrieve
# ---------------------------------------------------------------------------

@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


def test_repository_create_and_get_bill_section(repo):
    section = BillSection(section_id="s1", bill_id="b1", heading="h", text="t", order=0)
    repo.create_bill_section(section)
    fetched = repo.get_bill_section("s1")
    assert fetched == section


def test_repository_get_bill_section_missing_returns_none(repo):
    assert repo.get_bill_section("does-not-exist") is None


def test_repository_create_and_get_lesson(repo):
    lesson = Lesson(lesson_id="l1", bill_id="b1", summary="s")
    repo.create_lesson(lesson)
    fetched = repo.get_lesson("l1")
    assert fetched.lesson_id == "l1"
    assert fetched.summary == "s"


def test_repository_create_and_get_flashcard(repo):
    card = Flashcard(card_id="c1", lesson_id="l1", term="t", definition="d", section_id="s1")
    repo.create_flashcard(card)
    assert repo.get_flashcard("c1") == card


def test_repository_upsert_and_get_user_card_progress(repo):
    progress = UserCardProgress(user_id="u1", card_id="c1", leitner_box=2, correct_count=3)
    repo.upsert_user_card_progress(progress)
    fetched = repo.get_user_card_progress("u1", "c1")
    assert fetched.leitner_box == 2
    assert fetched.correct_count == 3


def test_repository_create_and_get_quiz_attempt(repo):
    attempt = QuizAttempt(attempt_id="a1", user_id="u1", lesson_id="l1", score=90)
    repo.create_quiz_attempt(attempt)
    fetched = repo.get_quiz_attempt("a1")
    assert fetched.score == 90


def test_repository_upsert_and_get_persona_profile(repo):
    profile = PersonaProfile(user_id="u1", occupation="Teacher", state="CA")
    repo.upsert_persona_profile(profile)
    fetched = repo.get_persona_profile("u1")
    assert fetched.occupation == "Teacher"
    assert fetched.state == "CA"


def test_repository_upsert_and_get_lesson_progress(repo):
    progress = LessonProgress(user_id="u1", lesson_id="l1", vocab_mastered=5, vocab_total=10)
    repo.upsert_lesson_progress(progress)
    fetched = repo.get_lesson_progress("u1", "l1")
    assert fetched.vocab_mastered == 5
    assert fetched.vocab_total == 10


def test_repository_get_lesson_progress_missing_returns_none(repo):
    assert repo.get_lesson_progress("u1", "no-such-lesson") is None
