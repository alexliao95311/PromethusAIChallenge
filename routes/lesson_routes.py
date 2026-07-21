"""Lesson Mode API routes.

Increment 1 added bill-section retrieval; Increment 2 added grounded lesson
generation; Increment 3 added optional vocabulary generation; Increment 4
adds the adaptive (Leitner-box) flashcard review endpoints -- see
docs/LESSON_MODE_ARCHITECTURE.md.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from models.lesson_models import Flashcard, Lesson
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


class GenerateLessonResponse(Lesson):
    vocabulary: Optional[List[Flashcard]] = None


@router.post("/generate", response_model=GenerateLessonResponse)
async def generate_lesson(request: GenerateLessonRequest):
    logger.info(
        "POST /lesson/generate bill_id=%s model=%s include_vocabulary=%s",
        request.bill_id, request.model, request.include_vocabulary,
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
            new_ids = [c.card_id for c in vocabulary]
            merged_ids = lesson.vocabulary_card_ids + [
                cid for cid in new_ids if cid not in lesson.vocabulary_card_ids
            ]
            if merged_ids != lesson.vocabulary_card_ids:
                lesson = lesson.model_copy(update={"vocabulary_card_ids": merged_ids})
                _lesson_generation_service.repository.create_lesson(lesson)
    except (LessonGenerationError, VocabularyGenerationError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating lesson")

    return GenerateLessonResponse(**lesson.model_dump(), vocabulary=vocabulary)


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
