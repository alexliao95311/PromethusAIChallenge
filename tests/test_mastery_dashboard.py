"""Tests for the Increment 11 mastery dashboard aggregation service."""

import uuid

import pytest

from models.lesson_models import (
    DebateReflection,
    Flashcard,
    Lesson,
    OpenResponseAttempt,
    QuizAttempt,
    ReflectionFeedbackItem,
    UserCardProgress,
)
from services.flashcard_review import FlashcardReviewService
from services.lesson_repository import LessonRepository
from services.mastery_dashboard import QUIZ_RETAKE_THRESHOLD, MasteryDashboardService
from tests.fake_firestore import FakeFirestoreClient

USER_ID = "u1"


@pytest.fixture
def repo():
    return LessonRepository(db=FakeFirestoreClient())


@pytest.fixture
def service(repo):
    return MasteryDashboardService(repository=repo)


def _lesson(lesson_id, title="Test Lesson", card_ids=None, quiz_ids=None, or_id=None):
    return Lesson(
        lesson_id=lesson_id,
        bill_id="hr1-119",
        prompt_version="v1",
        bill_text_hash="abc123",
        lesson_title=title,
        plain_language_summary="s",
        vocabulary_card_ids=card_ids or [],
        quiz_question_ids=quiz_ids or [],
        open_response_question_id=or_id,
    )


def _flashcard(card_id, lesson_id):
    return Flashcard(
        card_id=card_id, lesson_id=lesson_id, term="term", simple_definition="def",
        bill_context="ctx", example="ex", section_id="section-1",
    )


def _reflection_item(text="feedback"):
    return ReflectionFeedbackItem(feedback=text)


def _reflection(lesson_id, user_id=USER_ID, skill="Address counterarguments"):
    return DebateReflection(
        reflection_id=str(uuid.uuid4()),
        lesson_id=lesson_id,
        user_id=user_id,
        view_changed="somewhat",
        strongest_student_argument=_reflection_item(),
        weakest_reasoning_step=_reflection_item(),
        evidence_use_feedback=_reflection_item(),
        missed_opponent_point=_reflection_item(),
        perspective_understanding=_reflection_item(),
        recommended_skill=skill,
        recommended_next_activity="Debate again",
    )


def test_empty_dashboard_for_new_user_has_no_activity(service):
    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.has_activity is False
    assert dashboard.total_lessons_started == 0
    assert dashboard.completed_lesson_count == 0
    assert dashboard.overall_vocabulary_mastery_percent == 0.0
    assert dashboard.lessons == []
    assert dashboard.recommended_activity.activity_type == "generate_lesson"


def test_no_division_by_zero_when_lesson_has_no_cards(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"]))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=80.0))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.lessons[0].vocabulary.total_cards == 0
    assert dashboard.lessons[0].vocabulary.mastery_percent == 0.0
    assert dashboard.overall_vocabulary_mastery_percent == 0.0


def test_vocabulary_mastery_reflects_leitner_box_distribution(repo, service):
    card_ids = ["c1", "c2", "c3", "c4"]
    repo.create_lesson(_lesson("lesson-1", card_ids=card_ids))
    for cid in card_ids:
        repo.create_flashcard(_flashcard(cid, "lesson-1"))

    review = FlashcardReviewService(repository=repo)
    # c1: answer correctly 3x -> box 3 (mastered). c2: answer once correctly -> box 2.
    # c3: never touched -> box 1 (learning, the default for an untouched card).
    # c4: left alone too.
    for _ in range(3):
        review.submit_answer(USER_ID, "lesson-1", "c1", correct=True)
    review.submit_answer(USER_ID, "lesson-1", "c2", correct=True)

    dashboard = service.get_dashboard(USER_ID)
    vocab = dashboard.lessons[0].vocabulary
    assert vocab.total_cards == 4
    assert vocab.box_distribution == {"1": 2, "2": 1, "3": 1}
    assert vocab.mastery_percent == 25.0  # 1 of 4 mastered


def test_missing_a_card_resets_its_box_and_lowers_mastery(repo, service):
    card_ids = ["c1", "c2"]
    repo.create_lesson(_lesson("lesson-1", card_ids=card_ids))
    for cid in card_ids:
        repo.create_flashcard(_flashcard(cid, "lesson-1"))

    review = FlashcardReviewService(repository=repo)
    review.submit_answer(USER_ID, "lesson-1", "c1", correct=True)
    review.submit_answer(USER_ID, "lesson-1", "c1", correct=True)  # c1 -> box 3
    review.submit_answer(USER_ID, "lesson-1", "c2", correct=True)
    review.submit_answer(USER_ID, "lesson-1", "c2", correct=True)  # c2 -> box 3

    before = service.get_dashboard(USER_ID).lessons[0].vocabulary
    assert before.mastery_percent == 100.0

    review.submit_answer(USER_ID, "lesson-1", "c2", correct=False)  # miss it -> back to box 1

    after = service.get_dashboard(USER_ID).lessons[0].vocabulary
    assert after.mastery_percent == 50.0
    assert after.box_distribution["1"] == 1


def test_quiz_and_open_response_scores_tracked_per_lesson(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"], or_id="or1"))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=60.0))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a2", user_id=USER_ID, lesson_id="lesson-1", score=90.0))
    repo.create_open_response_attempt(OpenResponseAttempt(
        attempt_id="or-a1", user_id=USER_ID, lesson_id="lesson-1", question_id="or1",
        student_answer="answer", score=2, feedback="feedback",
    ))

    dashboard = service.get_dashboard(USER_ID)
    lesson_summary = dashboard.lessons[0]
    assert lesson_summary.quiz_attempts == 2
    assert lesson_summary.best_quiz_score == 90.0
    assert lesson_summary.latest_quiz_score == 90.0  # most recently created
    assert lesson_summary.open_response_attempts == 1
    assert lesson_summary.latest_open_response_score == 2
    assert len(dashboard.recent_quiz_scores) == 2
    assert len(dashboard.recent_open_response_scores) == 1


def test_lesson_marked_completed_only_when_all_its_graded_activities_are_attempted(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"], or_id="or1"))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=80.0))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.lessons[0].completed is False  # open-response not attempted yet
    assert dashboard.completed_lesson_count == 0

    repo.create_open_response_attempt(OpenResponseAttempt(
        attempt_id="or-a1", user_id=USER_ID, lesson_id="lesson-1", question_id="or1",
        student_answer="answer", score=3, feedback="feedback",
    ))

    dashboard2 = service.get_dashboard(USER_ID)
    assert dashboard2.lessons[0].completed is True
    assert dashboard2.completed_lesson_count == 1


def test_debate_skill_summary_is_a_profile_not_a_single_score(repo, service):
    repo.create_debate_reflection(_reflection("lesson-1", skill="Skill A"))
    repo.create_debate_reflection(_reflection("lesson-1", skill="Skill B"))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.debate_skill is not None
    assert dashboard.debate_skill.reflections_count == 2
    assert dashboard.debate_skill.is_estimate is True
    assert len(dashboard.debate_skill.recent_recommended_skills) == 2
    # No overall "intelligence"/combined numeric score field exists anywhere
    # on the dashboard model tying debate feedback to quiz/vocab data.
    assert not hasattr(dashboard, "overall_score")
    assert not hasattr(dashboard, "intelligence_score")


def test_recommendation_prioritizes_due_flashcards_over_everything_else(repo, service):
    repo.create_lesson(_lesson("lesson-1", card_ids=["c1"], quiz_ids=["q1"]))
    repo.create_flashcard(_flashcard("c1", "lesson-1"))
    # A card with no progress record is always due.
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=50.0))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.recommended_activity.activity_type == "review_flashcards"
    assert dashboard.recommended_activity.lesson_id == "lesson-1"


def test_recommendation_suggests_taking_an_unattempted_quiz(repo, service):
    repo.create_lesson(_lesson("lesson-1", card_ids=["c1"], quiz_ids=["q1"]))
    repo.create_flashcard(_flashcard("c1", "lesson-1"))
    review = FlashcardReviewService(repository=repo)
    # Master the only card (box 3, not due) so the due-flashcards rule
    # doesn't fire first -- isolates the "unattempted quiz" rule.
    review.submit_answer(USER_ID, "lesson-1", "c1", correct=True)
    review.submit_answer(USER_ID, "lesson-1", "c1", correct=True)

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.recommended_activity.activity_type == "take_quiz"
    assert dashboard.recommended_activity.lesson_id == "lesson-1"


def test_recommendation_suggests_retaking_a_low_scoring_quiz(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"], or_id="or1"))
    repo.create_quiz_attempt(QuizAttempt(
        attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=QUIZ_RETAKE_THRESHOLD - 10
    ))
    repo.create_open_response_attempt(OpenResponseAttempt(
        attempt_id="or-a1", user_id=USER_ID, lesson_id="lesson-1", question_id="or1",
        student_answer="answer", score=2, feedback="feedback",
    ))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.recommended_activity.activity_type == "retake_quiz"
    assert dashboard.recommended_activity.lesson_id == "lesson-1"


def test_recommendation_suggests_debate_and_reflect_when_lesson_fully_completed(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"], or_id="or1"))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=95.0))
    repo.create_open_response_attempt(OpenResponseAttempt(
        attempt_id="or-a1", user_id=USER_ID, lesson_id="lesson-1", question_id="or1",
        student_answer="answer", score=3, feedback="feedback",
    ))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.recommended_activity.activity_type == "debate_and_reflect"


def test_recommendation_falls_back_to_explore_new_bill_when_fully_caught_up(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"], or_id="or1"))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id=USER_ID, lesson_id="lesson-1", score=95.0))
    repo.create_open_response_attempt(OpenResponseAttempt(
        attempt_id="or-a1", user_id=USER_ID, lesson_id="lesson-1", question_id="or1",
        student_answer="answer", score=3, feedback="feedback",
    ))
    repo.create_debate_reflection(_reflection("lesson-1"))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.recommended_activity.activity_type == "explore_new_bill"


def test_dashboard_scoped_to_authenticated_user_only(repo, service):
    repo.create_lesson(_lesson("lesson-1", quiz_ids=["q1"]))
    repo.create_quiz_attempt(QuizAttempt(attempt_id="a1", user_id="other-user", lesson_id="lesson-1", score=80.0))

    dashboard = service.get_dashboard(USER_ID)
    assert dashboard.has_activity is False
