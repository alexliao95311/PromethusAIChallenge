"""Firestore repository for Lesson Mode data models.

Increment 0: foundation only. Nothing here is called from an API route yet
-- it exists so later increments (lesson generation, flashcards, quizzes,
personas) can be built on a tested persistence layer. See
docs/LESSON_MODE_ARCHITECTURE.md for the rollout plan.
"""

import logging
from typing import Optional

from models.lesson_models import (
    BillSection,
    Lesson,
    Flashcard,
    UserCardProgress,
    QuizQuestion,
    QuizAttempt,
    OpenResponseQuestion,
    OpenResponseAttempt,
    PersonaProfile,
    LessonProgress,
)
from services.firebase_client import get_firestore_db

logger = logging.getLogger(__name__)

COLLECTION_BILL_SECTIONS = "bill_sections"
COLLECTION_LESSONS = "lessons"
COLLECTION_FLASHCARDS = "flashcards"
COLLECTION_USER_CARD_PROGRESS = "user_card_progress"
COLLECTION_QUIZ_QUESTIONS = "quiz_questions"
COLLECTION_QUIZ_ATTEMPTS = "quiz_attempts"
COLLECTION_OPEN_RESPONSE_QUESTIONS = "open_response_questions"
COLLECTION_OPEN_RESPONSE_ATTEMPTS = "open_response_attempts"
COLLECTION_PERSONA_PROFILES = "persona_profiles"
COLLECTION_LESSON_PROGRESS = "lesson_progress"


def _user_card_progress_doc_id(user_id: str, card_id: str) -> str:
    return f"{user_id}_{card_id}"


def _lesson_progress_doc_id(user_id: str, lesson_id: str) -> str:
    return f"{user_id}_{lesson_id}"


class LessonRepository:
    """Firestore repository for lesson-mode entities.

    Accepts an injected Firestore (or Firestore-compatible fake/emulator)
    client so it can be unit tested without hitting real Firestore. Falls
    back to the shared lazily-initialized client from `firebase_client` when
    no client is injected.
    """

    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_db()
        return self._db

    # -- BillSection ---------------------------------------------------
    def create_bill_section(self, section: BillSection) -> str:
        self.db.collection(COLLECTION_BILL_SECTIONS).document(section.section_id).set(
            section.to_firestore_dict()
        )
        return section.section_id

    def get_bill_section(self, section_id: str) -> Optional[BillSection]:
        doc = self.db.collection(COLLECTION_BILL_SECTIONS).document(section_id).get()
        if not doc.exists:
            return None
        return BillSection.from_firestore_dict(doc.to_dict())

    # -- Lesson ----------------------------------------------------------
    def create_lesson(self, lesson: Lesson) -> str:
        self.db.collection(COLLECTION_LESSONS).document(lesson.lesson_id).set(
            lesson.to_firestore_dict()
        )
        return lesson.lesson_id

    def get_lesson(self, lesson_id: str) -> Optional[Lesson]:
        doc = self.db.collection(COLLECTION_LESSONS).document(lesson_id).get()
        if not doc.exists:
            return None
        return Lesson.from_firestore_dict(doc.to_dict())

    # -- Flashcard ---------------------------------------------------------
    def create_flashcard(self, card: Flashcard) -> str:
        self.db.collection(COLLECTION_FLASHCARDS).document(card.card_id).set(
            card.to_firestore_dict()
        )
        return card.card_id

    def get_flashcard(self, card_id: str) -> Optional[Flashcard]:
        doc = self.db.collection(COLLECTION_FLASHCARDS).document(card_id).get()
        if not doc.exists:
            return None
        return Flashcard.from_firestore_dict(doc.to_dict())

    # -- UserCardProgress ----------------------------------------------
    def upsert_user_card_progress(self, progress: UserCardProgress) -> str:
        doc_id = _user_card_progress_doc_id(progress.user_id, progress.card_id)
        self.db.collection(COLLECTION_USER_CARD_PROGRESS).document(doc_id).set(
            progress.to_firestore_dict()
        )
        return doc_id

    def get_user_card_progress(self, user_id: str, card_id: str) -> Optional[UserCardProgress]:
        doc_id = _user_card_progress_doc_id(user_id, card_id)
        doc = self.db.collection(COLLECTION_USER_CARD_PROGRESS).document(doc_id).get()
        if not doc.exists:
            return None
        return UserCardProgress.from_firestore_dict(doc.to_dict())

    # -- QuizQuestion --------------------------------------------------
    def create_quiz_question(self, question: QuizQuestion) -> str:
        self.db.collection(COLLECTION_QUIZ_QUESTIONS).document(question.question_id).set(
            question.to_firestore_dict()
        )
        return question.question_id

    def get_quiz_question(self, question_id: str) -> Optional[QuizQuestion]:
        doc = self.db.collection(COLLECTION_QUIZ_QUESTIONS).document(question_id).get()
        if not doc.exists:
            return None
        return QuizQuestion.from_firestore_dict(doc.to_dict())

    # -- QuizAttempt -------------------------------------------------------
    def create_quiz_attempt(self, attempt: QuizAttempt) -> str:
        self.db.collection(COLLECTION_QUIZ_ATTEMPTS).document(attempt.attempt_id).set(
            attempt.to_firestore_dict()
        )
        return attempt.attempt_id

    def get_quiz_attempt(self, attempt_id: str) -> Optional[QuizAttempt]:
        doc = self.db.collection(COLLECTION_QUIZ_ATTEMPTS).document(attempt_id).get()
        if not doc.exists:
            return None
        return QuizAttempt.from_firestore_dict(doc.to_dict())

    # -- OpenResponseQuestion --------------------------------------------
    def create_open_response_question(self, question: OpenResponseQuestion) -> str:
        self.db.collection(COLLECTION_OPEN_RESPONSE_QUESTIONS).document(question.question_id).set(
            question.to_firestore_dict()
        )
        return question.question_id

    def get_open_response_question(self, question_id: str) -> Optional[OpenResponseQuestion]:
        doc = self.db.collection(COLLECTION_OPEN_RESPONSE_QUESTIONS).document(question_id).get()
        if not doc.exists:
            return None
        return OpenResponseQuestion.from_firestore_dict(doc.to_dict())

    # -- OpenResponseAttempt ----------------------------------------------
    def create_open_response_attempt(self, attempt: OpenResponseAttempt) -> str:
        self.db.collection(COLLECTION_OPEN_RESPONSE_ATTEMPTS).document(attempt.attempt_id).set(
            attempt.to_firestore_dict()
        )
        return attempt.attempt_id

    def get_open_response_attempt(self, attempt_id: str) -> Optional[OpenResponseAttempt]:
        doc = self.db.collection(COLLECTION_OPEN_RESPONSE_ATTEMPTS).document(attempt_id).get()
        if not doc.exists:
            return None
        return OpenResponseAttempt.from_firestore_dict(doc.to_dict())

    # -- PersonaProfile ------------------------------------------------
    def upsert_persona_profile(self, profile: PersonaProfile) -> str:
        self.db.collection(COLLECTION_PERSONA_PROFILES).document(profile.user_id).set(
            profile.to_firestore_dict()
        )
        return profile.user_id

    def get_persona_profile(self, user_id: str) -> Optional[PersonaProfile]:
        doc = self.db.collection(COLLECTION_PERSONA_PROFILES).document(user_id).get()
        if not doc.exists:
            return None
        return PersonaProfile.from_firestore_dict(doc.to_dict())

    # -- LessonProgress ------------------------------------------------
    def upsert_lesson_progress(self, progress: LessonProgress) -> str:
        doc_id = _lesson_progress_doc_id(progress.user_id, progress.lesson_id)
        self.db.collection(COLLECTION_LESSON_PROGRESS).document(doc_id).set(
            progress.to_firestore_dict()
        )
        return doc_id

    def get_lesson_progress(self, user_id: str, lesson_id: str) -> Optional[LessonProgress]:
        doc_id = _lesson_progress_doc_id(user_id, lesson_id)
        doc = self.db.collection(COLLECTION_LESSON_PROGRESS).document(doc_id).get()
        if not doc.exists:
            return None
        return LessonProgress.from_firestore_dict(doc.to_dict())
