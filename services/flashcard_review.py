"""Adaptive (Leitner-box) flashcard review scheduling for Lesson Mode
(Increment 4).

Scheduling is driven by a per-user, per-lesson *review-session counter*
(`LessonProgress.current_session`), not wall-clock time: "due every N
sessions" means due N sessions after the one it was last reviewed in,
inclusive of that session (see `_INTERVALS` and `compute_next_due_session`
below). A card with no progress record yet is always due -- it's new.

Ownership: every method here takes `user_id` as a plain argument, but the
only caller that matters is `routes/lesson_routes.py`, which always
supplies it from `services.auth.get_current_user_id` (a verified Firebase
ID token), never from request body/query data. That's what actually
prevents one user from touching another's progress; this module just
trusts whatever `user_id` it's given.
"""

import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from models.lesson_models import Flashcard, Lesson, LessonProgress, UserCardProgress
from services.lesson_repository import LessonRepository

logger = logging.getLogger(__name__)

MAX_BOX = 3
MIN_BOX = 1

# Box -> "review every Nth session". Due `interval - 1` sessions after the
# session it was last reviewed in (inclusive counting: reviewed on session
# s counts as that cycle's "session 1", so it's next due on session
# s + interval - 1). Box 1 (interval=1) is therefore due starting the very
# next session onward, for as long as it stays unanswered.
_INTERVALS: Dict[int, int] = {1: 1, 2: 3, 3: 7}


class LessonNotFoundError(Exception):
    pass


class CardNotInLessonError(Exception):
    pass


class ReviewCard(BaseModel):
    """A flashcard plus this user's current review state, for the frontend."""

    card_id: str
    term: str
    simple_definition: str
    bill_context: str
    example: str
    section_id: str
    difficulty: str
    leitner_box: int
    is_new: bool
    is_due: bool


class ReviewState(BaseModel):
    session: int
    due_cards: List[ReviewCard]
    total_cards: int
    due_count: int
    box_distribution: Dict[str, int]
    mastery_percent: float


def compute_next_due_session(box: int, reviewed_session: int) -> int:
    return reviewed_session + (_INTERVALS[box] - 1)


def is_card_due(progress: Optional[UserCardProgress], current_session: int) -> bool:
    """A card with no progress record is new, and new cards are always due."""
    if progress is None:
        return True
    return current_session >= progress.next_due_session


def apply_answer(progress: UserCardProgress, correct: bool, session: int) -> UserCardProgress:
    """Return a new `UserCardProgress` reflecting one answer.

    Correct: box moves up one, capped at `MAX_BOX`. Incorrect: box resets to
    `MIN_BOX`, regardless of the box it was in. Either way, the review
    interval restarts from the *new* box.
    """
    if correct:
        new_box = min(progress.leitner_box + 1, MAX_BOX)
    else:
        new_box = MIN_BOX

    return progress.model_copy(
        update={
            "leitner_box": new_box,
            "correct_count": progress.correct_count + (1 if correct else 0),
            "incorrect_count": progress.incorrect_count + (0 if correct else 1),
            "last_reviewed_session": session,
            "next_due_session": compute_next_due_session(new_box, session),
        }
    )


class FlashcardReviewService:
    """Starts review sessions, reports due cards/mastery, and applies answers."""

    def __init__(self, repository: Optional[LessonRepository] = None):
        self._repository = repository or LessonRepository()

    def _get_or_init_lesson_progress(self, user_id: str, lesson_id: str) -> LessonProgress:
        progress = self._repository.get_lesson_progress(user_id, lesson_id)
        if progress is None:
            progress = LessonProgress(user_id=user_id, lesson_id=lesson_id, current_session=1)
            self._repository.upsert_lesson_progress(progress)
            logger.info(
                "flashcard_review session_init user_id=%s lesson_id=%s session=1", user_id, lesson_id
            )
        return progress

    def start_session(self, user_id: str, lesson_id: str) -> int:
        """Advance to a new review session and return its number.

        The first-ever call for a user+lesson initializes at session 1
        (matching `_get_or_init_lesson_progress`) rather than jumping to 2.
        """
        progress = self._repository.get_lesson_progress(user_id, lesson_id)
        if progress is None:
            progress = LessonProgress(user_id=user_id, lesson_id=lesson_id, current_session=1)
        else:
            progress = progress.model_copy(update={"current_session": progress.current_session + 1})
        self._repository.upsert_lesson_progress(progress)
        logger.info(
            "flashcard_review start_session user_id=%s lesson_id=%s session=%d",
            user_id, lesson_id, progress.current_session,
        )
        return progress.current_session

    def _load_lesson_cards(self, lesson_id: str) -> List[Flashcard]:
        lesson: Optional[Lesson] = self._repository.get_lesson(lesson_id)
        if lesson is None:
            raise LessonNotFoundError(f"No lesson found for lesson_id={lesson_id!r}")

        cards = []
        for card_id in lesson.vocabulary_card_ids:
            card = self._repository.get_flashcard(card_id)
            if card is not None:
                cards.append(card)
        return cards

    def get_review_state(self, user_id: str, lesson_id: str) -> ReviewState:
        lesson_progress = self._get_or_init_lesson_progress(user_id, lesson_id)
        session = lesson_progress.current_session
        cards = self._load_lesson_cards(lesson_id)

        review_cards: List[ReviewCard] = []
        due_cards: List[ReviewCard] = []
        box_distribution = {"1": 0, "2": 0, "3": 0}
        mastered = 0

        for card in cards:
            progress = self._repository.get_user_card_progress(user_id, card.card_id)
            box = progress.leitner_box if progress else MIN_BOX
            due = is_card_due(progress, session)
            box_distribution[str(box)] += 1
            if box == MAX_BOX:
                mastered += 1

            review_card = ReviewCard(
                card_id=card.card_id,
                term=card.term,
                simple_definition=card.simple_definition,
                bill_context=card.bill_context,
                example=card.example,
                section_id=card.section_id,
                difficulty=card.difficulty,
                leitner_box=box,
                is_new=progress is None,
                is_due=due,
            )
            review_cards.append(review_card)
            if due:
                due_cards.append(review_card)

        total = len(cards)
        mastery_percent = round(100 * mastered / total, 1) if total else 0.0

        return ReviewState(
            session=session,
            due_cards=due_cards,
            total_cards=total,
            due_count=len(due_cards),
            box_distribution=box_distribution,
            mastery_percent=mastery_percent,
        )

    def submit_answer(
        self, user_id: str, lesson_id: str, card_id: str, correct: bool
    ) -> UserCardProgress:
        lesson: Optional[Lesson] = self._repository.get_lesson(lesson_id)
        if lesson is None:
            raise LessonNotFoundError(f"No lesson found for lesson_id={lesson_id!r}")
        if card_id not in lesson.vocabulary_card_ids:
            raise CardNotInLessonError(
                f"card_id={card_id!r} does not belong to lesson_id={lesson_id!r}"
            )

        lesson_progress = self._get_or_init_lesson_progress(user_id, lesson_id)
        session = lesson_progress.current_session

        existing = self._repository.get_user_card_progress(user_id, card_id)
        if existing is None:
            existing = UserCardProgress(user_id=user_id, card_id=card_id)

        updated = apply_answer(existing, correct=correct, session=session)
        self._repository.upsert_user_card_progress(updated)
        logger.info(
            "flashcard_review answer user_id=%s lesson_id=%s card_id=%s correct=%s "
            "box=%d->%d next_due_session=%d",
            user_id, lesson_id, card_id, correct,
            existing.leitner_box, updated.leitner_box, updated.next_due_session,
        )
        return updated
