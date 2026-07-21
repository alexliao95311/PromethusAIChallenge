"""Bill-section retrieval: the reusable RAG service for Lesson Mode.

Flow: bill text -> section_splitter -> embeddings -> cached section
embeddings -> cosine similarity search -> top relevant sections.

`BillRagService.retrieve_relevant_sections` is the single entry point other
increments (lesson generation, flashcards, quizzes) should call instead of
sending an entire bill to the model.
"""

import logging
import time
from typing import List, Optional

from pydantic import BaseModel

from models.lesson_models import BillSection
from services.rag.cache import (
    CachedBillEmbeddings,
    EmbeddingCache,
    InMemoryEmbeddingCache,
    compute_text_hash,
)
from services.rag.embeddings import EmbeddingProvider, get_embedding_provider
from services.rag.section_splitter import split_bill_into_sections

logger = logging.getLogger(__name__)


class RetrievedSection(BaseModel):
    section_id: str
    heading: str
    text: str
    order: int
    similarity_score: float


class BillNotCachedError(Exception):
    """Raised when a bill has no cached sections and no bill_text was supplied."""


def _cosine_similarity(query_vec: List[float], section_vecs: List[List[float]]) -> List[float]:
    import numpy as np

    query = np.array(query_vec, dtype=float)
    matrix = np.array(section_vecs, dtype=float)

    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return [0.0] * len(section_vecs)

    matrix_norms = np.linalg.norm(matrix, axis=1)
    scores = np.zeros(len(section_vecs))
    nonzero = matrix_norms != 0
    scores[nonzero] = (matrix[nonzero] @ query) / (matrix_norms[nonzero] * query_norm)
    return scores.tolist()


class BillRagService:
    """Reusable bill-section RAG service: split, embed, cache, retrieve."""

    def __init__(
        self,
        cache: Optional[EmbeddingCache] = None,
        embedding_provider_factory=None,
    ):
        self._cache = cache or InMemoryEmbeddingCache()
        self._embedding_provider_factory = embedding_provider_factory or get_embedding_provider

    def _build_and_cache(self, bill_id: str, bill_text: str, text_hash: str) -> CachedBillEmbeddings:
        sections = split_bill_into_sections(bill_text, bill_id)
        provider: EmbeddingProvider = self._embedding_provider_factory()

        if sections:
            texts = [s.text for s in sections]
            provider.fit(texts)
            embeddings = provider.embed_batch(texts)
            for section, embedding in zip(sections, embeddings):
                section.embedding = embedding

        entry = CachedBillEmbeddings(
            bill_id=bill_id, text_hash=text_hash, sections=sections, provider=provider
        )
        self._cache.set(entry)
        return entry

    def _get_or_build_sections(self, bill_id: str, bill_text: Optional[str]) -> CachedBillEmbeddings:
        cached = self._cache.get(bill_id)

        if bill_text is None:
            if cached is None:
                raise BillNotCachedError(
                    f"No cached sections for bill_id={bill_id!r}; bill_text must be "
                    "supplied on first retrieval for this bill."
                )
            logger.info(
                "bill_rag cache_hit bill_id=%s sections=%d", bill_id, len(cached.sections)
            )
            return cached

        text_hash = compute_text_hash(bill_text)
        if cached is not None and cached.text_hash == text_hash:
            logger.info(
                "bill_rag cache_hit bill_id=%s sections=%d", bill_id, len(cached.sections)
            )
            return cached

        reason = "text_changed" if cached is not None else "not_cached"
        logger.info("bill_rag cache_miss bill_id=%s reason=%s", bill_id, reason)
        return self._build_and_cache(bill_id, bill_text, text_hash)

    def retrieve_relevant_sections(
        self,
        bill_id: str,
        query: str,
        top_k: int = 5,
        bill_text: Optional[str] = None,
    ) -> List[RetrievedSection]:
        """Return the top_k bill sections most relevant to `query`.

        If `bill_text` is given, sections are (re)built from it when the
        bill isn't cached yet or its text has changed since the last call;
        otherwise the cached sections for `bill_id` are reused unchanged. If
        `bill_text` is omitted and nothing is cached, raises
        `BillNotCachedError`.
        """
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        if not query or not query.strip():
            raise ValueError("query must not be empty")

        start = time.perf_counter()
        entry = self._get_or_build_sections(bill_id, bill_text)
        sections: List[BillSection] = entry.sections

        if not sections:
            logger.info(
                "bill_rag retrieval bill_id=%s query=%r results=0 latency_ms=%.1f",
                bill_id, query, (time.perf_counter() - start) * 1000,
            )
            return []

        query_vec = entry.provider.embed(query)
        scores = _cosine_similarity(query_vec, [s.embedding for s in sections])

        ranked = sorted(zip(sections, scores), key=lambda pair: pair[1], reverse=True)
        top = ranked[: min(top_k, len(ranked))]

        results = [
            RetrievedSection(
                section_id=section.section_id,
                heading=section.heading,
                text=section.text,
                order=section.order,
                similarity_score=round(float(score), 6),
            )
            for section, score in top
        ]

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "bill_rag retrieval bill_id=%s query=%r top_k=%d results=%d latency_ms=%.1f",
            bill_id, query, top_k, len(results), latency_ms,
        )
        return results
