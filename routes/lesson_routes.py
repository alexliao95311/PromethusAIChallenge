"""Lesson Mode API routes.

Increment 1: bill-section retrieval only. Lesson generation is out of scope
here -- see docs/LESSON_MODE_ARCHITECTURE.md for the rollout plan.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.rag.retrieval_service import BillNotCachedError, BillRagService, RetrievedSection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lesson", tags=["lesson"])

# Shared service instance so the in-memory embedding cache persists across
# requests within a running process.
_rag_service = BillRagService()


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
