"""Lesson Mode API routes.

Increment 1 added bill-section retrieval; Increment 2 added grounded lesson
generation; Increment 3 adds optional vocabulary generation on top of it --
see docs/LESSON_MODE_ARCHITECTURE.md.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.lesson_models import Flashcard, Lesson
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
    except (LessonGenerationError, VocabularyGenerationError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in /lesson/generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating lesson")

    return GenerateLessonResponse(**lesson.model_dump(), vocabulary=vocabulary)
