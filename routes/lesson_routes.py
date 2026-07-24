"""Lesson Mode API routes.

Increment 1 added bill-section retrieval; Increment 2 added grounded lesson
generation; Increment 3 added optional vocabulary generation; Increment 4
added the adaptive (Leitner-box) flashcard review endpoints; Increment 5
added grounded multiple-choice quiz generation; Increment 6 adds the
open-response question and its grading -- see
docs/LESSON_MODE_ARCHITECTURE.md.
"""

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from models.lesson_models import Flashcard, Lesson, OpenResponseAttempt, QuizAnswer, QuizAttempt
from services.auth import get_current_user_id
from services.flashcard_review import (
    CardNotInLessonError,
    FlashcardReviewService,
    LessonNotFoundError,
    ReviewState,
)
from services.lesson_generation import (
    DEFAULT_LESSON_MODEL,
    LessonGenerationError,
    LessonGenerationService,
)
from services.open_response_generation import (
    OpenResponseGenerationError,
    OpenResponseGenerationService,
)
from services.open_response_grading import OpenResponseGradingError, OpenResponseGradingService
from services.quiz_generation import QuizGenerationError, QuizGenerationService
from services.rag.retrieval_service import BillNotCachedError, BillRagService, RetrievedSection
from services.vocabulary_generation import VocabularyGenerationError, VocabularyGenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lesson", tags=["lesson"])

# Shared service instances so the in-memory RAG embedding cache persists
# across requests within a running process.
_rag_service = BillRagService()
_lesson_generation_service = LessonGenerationService(rag_service=_rag_service)
_vocabulary_generation_service = VocabularyGenerationService(rag_service=_rag_service)
_flashcard_review_service = FlashcardReviewService(repository=_lesson_generation_service.repository)
_quiz_generation_service = QuizGenerationService(repository=_lesson_generation_service.repository)
_open_response_generation_service = OpenResponseGenerationService(
    repository=_lesson_generation_service.repository
)
_open_response_grading_service = OpenResponseGradingService()


class RetrieveSectionsRequest(BaseModel):
    bill_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, gt=0, le=50)
    bill_text: Optional[str] = None


class RetrieveSectionsResponse(BaseModel):
    bill_id: str
    query: str
    sections: List[RetrievedSection]


@router.post("/retrieve-sections", response_model=RetrieveSectionsResponse)
async def retrieve_sections(request: RetrieveSectionsRequest):
    logger.info(
        "POST /lesson/retrieve-sections bill_id=%s top_k=%d has_bill_text=%s",
        request.bill_id, request.top_k, request.bill_text is not None,
    )
    try:
        sections = _rag_service.retrieve_relevant_sections(
            bill_id=request.bill_id,
            query=request.query,
            top_k=request.top_k,
            bill_text=request.bill_text,
        )
    except BillNotCachedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/retrieve-sections: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving bill sections")

    return RetrieveSectionsResponse(
        bill_id=request.bill_id, query=request.query, sections=sections
    )


class GenerateLessonRequest(BaseModel):
    bill_id: str = Field(..., min_length=1)
    bill_text: str = Field(..., min_length=1)
    model: str = DEFAULT_LESSON_MODEL
    include_vocabulary: bool = False
    include_quiz: bool = False
    include_open_response: bool = False


class QuizQuestionPublic(BaseModel):
    """A quiz question without its correct_answer_index/explanation -- the
    shape shown to a student taking the quiz, before they submit answers."""

    question_id: str
    question: str
    answer_choices: List[str]
    section_ids: List[str]
    difficulty: str
    question_type: str


class OpenResponseQuestionPublic(BaseModel):
    """An open-response question without `expected_points`/`context_excerpt`
    -- the shape shown to a student before they answer."""

    question_id: str
    question: str
    question_type: str
    section_ids: List[str]


class GenerateLessonResponse(Lesson):
    vocabulary: Optional[List[Flashcard]] = None
    quiz: Optional[List[QuizQuestionPublic]] = None
    open_response_question: Optional[OpenResponseQuestionPublic] = None


def _merge_ids(existing_ids: List[str], new_ids: List[str]) -> List[str]:
    return existing_ids + [i for i in new_ids if i not in existing_ids]


@router.post("/generate", response_model=GenerateLessonResponse)
async def generate_lesson(request: GenerateLessonRequest):
    logger.info(
        "POST /lesson/generate bill_id=%s model=%s include_vocabulary=%s include_quiz=%s include_open_response=%s",
        request.bill_id, request.model, request.include_vocabulary, request.include_quiz,
        request.include_open_response,
    )
    try:
        lesson = await _lesson_generation_service.generate_lesson(
            bill_id=request.bill_id, bill_text=request.bill_text, model=request.model
        )

        vocabulary = None
        if request.include_vocabulary:
            vocabulary = await _vocabulary_generation_service.generate_vocabulary(
                bill_id=request.bill_id,
                lesson_id=lesson.lesson_id,
                bill_text=request.bill_text,
                model=request.model,
            )
            merged_ids = _merge_ids(lesson.vocabulary_card_ids, [c.card_id for c in vocabulary])
            if merged_ids != lesson.vocabulary_card_ids:
                lesson = lesson.model_copy(update={"vocabulary_card_ids": merged_ids})
                _lesson_generation_service.repository.create_lesson(lesson)

        quiz = None
        if request.include_quiz:
            quiz_questions = await _quiz_generation_service.generate_quiz(
                lesson_id=lesson.lesson_id, model=request.model
            )
            merged_ids = _merge_ids(lesson.quiz_question_ids, [q.question_id for q in quiz_questions])
            if merged_ids != lesson.quiz_question_ids:
                lesson = lesson.model_copy(update={"quiz_question_ids": merged_ids})
                _lesson_generation_service.repository.create_lesson(lesson)
            quiz = [
                QuizQuestionPublic(**q.model_dump(exclude={"lesson_id", "correct_answer_index", "explanation"}))
                for q in quiz_questions
            ]

        open_response_question = None
        if request.include_open_response:
            or_question = await _open_response_generation_service.generate_question(
                lesson_id=lesson.lesson_id, model=request.model
            )
            if lesson.open_response_question_id != or_question.question_id:
                lesson = lesson.model_copy(update={"open_response_question_id": or_question.question_id})
                _lesson_generation_service.repository.create_lesson(lesson)
            open_response_question = OpenResponseQuestionPublic(
                **or_question.model_dump(exclude={"lesson_id", "expected_points", "context_excerpt"})
            )
    except (LessonGenerationError, VocabularyGenerationError, QuizGenerationError, OpenResponseGenerationError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating lesson")

    return GenerateLessonResponse(
        **lesson.model_dump(), vocabulary=vocabulary, quiz=quiz, open_response_question=open_response_question
    )


class StartSessionResponse(BaseModel):
    session: int


class AnswerCardRequest(BaseModel):
    card_id: str = Field(..., min_length=1)
    correct: bool


class AnswerCardResponse(BaseModel):
    card_id: str
    leitner_box: int
    correct_count: int
    incorrect_count: int
    last_reviewed_session: int
    next_due_session: int


@router.post("/{lesson_id}/review/start-session", response_model=StartSessionResponse)
async def start_review_session(lesson_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("POST /lesson/%s/review/start-session user_id=%s", lesson_id, user_id)
    session = _flashcard_review_service.start_session(user_id=user_id, lesson_id=lesson_id)
    return StartSessionResponse(session=session)


@router.get("/{lesson_id}/review/state", response_model=ReviewState)
async def get_review_state(lesson_id: str, user_id: str = Depends(get_current_user_id)):
    logger.info("GET /lesson/%s/review/state user_id=%s", lesson_id, user_id)
    try:
        return _flashcard_review_service.get_review_state(user_id=user_id, lesson_id=lesson_id)
    except LessonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/review/state: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching review state")


@router.post("/{lesson_id}/review/answer", response_model=AnswerCardResponse)
async def submit_review_answer(
    lesson_id: str, request: AnswerCardRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/review/answer user_id=%s card_id=%s correct=%s",
        lesson_id, user_id, request.card_id, request.correct,
    )
    try:
        updated = _flashcard_review_service.submit_answer(
            user_id=user_id, lesson_id=lesson_id, card_id=request.card_id, correct=request.correct
        )
    except LessonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CardNotInLessonError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/review/answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error submitting answer")

    return AnswerCardResponse(
        card_id=updated.card_id,
        leitner_box=updated.leitner_box,
        correct_count=updated.correct_count,
        incorrect_count=updated.incorrect_count,
        last_reviewed_session=updated.last_reviewed_session,
        next_due_session=updated.next_due_session,
    )


def _get_lesson_or_404(lesson_id: str) -> Lesson:
    lesson = _lesson_generation_service.repository.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail=f"No lesson found for lesson_id={lesson_id!r}")
    return lesson


@router.get("/{lesson_id}/quiz", response_model=List[QuizQuestionPublic])
async def get_quiz(lesson_id: str):
    logger.info("GET /lesson/%s/quiz", lesson_id)
    lesson = _get_lesson_or_404(lesson_id)

    questions = [
        q for q in (
            _lesson_generation_service.repository.get_quiz_question(qid)
            for qid in lesson.quiz_question_ids
        ) if q is not None
    ]
    if not questions:
        raise HTTPException(status_code=404, detail=f"No quiz generated yet for lesson_id={lesson_id!r}")

    return [
        QuizQuestionPublic(**q.model_dump(exclude={"lesson_id", "correct_answer_index", "explanation"}))
        for q in questions
    ]


class QuizAnswerSubmission(BaseModel):
    question_id: str = Field(..., min_length=1)
    selected_index: int = Field(ge=0)


class SubmitQuizRequest(BaseModel):
    answers: List[QuizAnswerSubmission] = Field(min_length=1)


class QuestionResult(BaseModel):
    question_id: str
    selected_index: int
    correct: bool
    correct_answer_index: int
    explanation: str


class SubmitQuizResponse(BaseModel):
    attempt_id: str
    score: float
    results: List[QuestionResult]


@router.post("/{lesson_id}/quiz/submit", response_model=SubmitQuizResponse)
async def submit_quiz(
    lesson_id: str, request: SubmitQuizRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/quiz/submit user_id=%s answers=%d",
        lesson_id, user_id, len(request.answers),
    )
    lesson = _get_lesson_or_404(lesson_id)

    questions_by_id = {
        qid: q for qid in lesson.quiz_question_ids
        if (q := _lesson_generation_service.repository.get_quiz_question(qid)) is not None
    }
    if not questions_by_id:
        raise HTTPException(status_code=404, detail=f"No quiz generated yet for lesson_id={lesson_id!r}")

    results: List[QuestionResult] = []
    quiz_answers: List[QuizAnswer] = []
    correct_count = 0

    for submitted in request.answers:
        question = questions_by_id.get(submitted.question_id)
        if question is None:
            raise HTTPException(
                status_code=400,
                detail=f"question_id={submitted.question_id!r} does not belong to lesson_id={lesson_id!r}",
            )

        is_correct = submitted.selected_index == question.correct_answer_index
        if is_correct:
            correct_count += 1

        results.append(
            QuestionResult(
                question_id=question.question_id,
                selected_index=submitted.selected_index,
                correct=is_correct,
                correct_answer_index=question.correct_answer_index,
                explanation=question.explanation,
            )
        )
        quiz_answers.append(
            QuizAnswer(
                question_id=question.question_id,
                response=str(submitted.selected_index),
                is_correct=is_correct,
            )
        )

    score = round(100 * correct_count / len(request.answers), 1)
    attempt = QuizAttempt(
        attempt_id=str(uuid.uuid4()),
        user_id=user_id,
        lesson_id=lesson_id,
        score=score,
        answers=quiz_answers,
    )
    _lesson_generation_service.repository.create_quiz_attempt(attempt)

    return SubmitQuizResponse(attempt_id=attempt.attempt_id, score=score, results=results)


@router.get("/{lesson_id}/open-response", response_model=OpenResponseQuestionPublic)
async def get_open_response_question(lesson_id: str):
    logger.info("GET /lesson/%s/open-response", lesson_id)
    lesson = _get_lesson_or_404(lesson_id)

    if not lesson.open_response_question_id:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )
    question = _lesson_generation_service.repository.get_open_response_question(
        lesson.open_response_question_id
    )
    if question is None:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )

    return OpenResponseQuestionPublic(
        **question.model_dump(exclude={"lesson_id", "expected_points", "context_excerpt"})
    )


class SubmitOpenResponseRequest(BaseModel):
    student_answer: str = Field(..., min_length=0)


class SubmitOpenResponseResponse(BaseModel):
    attempt_id: str
    score: int
    feedback: str
    missed_points: List[str]
    accurate_points: List[str]
    section_ids: List[str]


@router.post("/{lesson_id}/open-response/submit", response_model=SubmitOpenResponseResponse)
async def submit_open_response(
    lesson_id: str, request: SubmitOpenResponseRequest, user_id: str = Depends(get_current_user_id)
):
    logger.info(
        "POST /lesson/%s/open-response/submit user_id=%s answer_length=%d",
        lesson_id, user_id, len(request.student_answer),
    )
    lesson = _get_lesson_or_404(lesson_id)

    if not lesson.open_response_question_id:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )
    question = _lesson_generation_service.repository.get_open_response_question(
        lesson.open_response_question_id
    )
    if question is None:
        raise HTTPException(
            status_code=404, detail=f"No open-response question generated yet for lesson_id={lesson_id!r}"
        )

    try:
        grade = await _open_response_grading_service.grade_answer(question, request.student_answer)
    except OpenResponseGradingError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/{lesson_id}/open-response/submit: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error grading answer")

    attempt = OpenResponseAttempt(
        attempt_id=str(uuid.uuid4()),
        user_id=user_id,
        lesson_id=lesson_id,
        question_id=question.question_id,
        student_answer=request.student_answer,
        score=grade.score,
        feedback=grade.feedback,
        missed_points=grade.missed_points,
        accurate_points=grade.accurate_points,
        section_ids=grade.section_ids,
    )
    _lesson_generation_service.repository.create_open_response_attempt(attempt)

    return SubmitOpenResponseResponse(
        attempt_id=attempt.attempt_id,
        score=grade.score,
        feedback=grade.feedback,
        missed_points=grade.missed_points,
        accurate_points=grade.accurate_points,
        section_ids=grade.section_ids,
    )
