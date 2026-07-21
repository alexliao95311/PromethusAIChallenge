"""Bill-section RAG pipeline: splitting, embedding, caching, and retrieval.

See docs/LESSON_MODE_ARCHITECTURE.md (Increment 1) for the design.
"""

from services.rag.retrieval_service import BillRagService, RetrievedSection

__all__ = ["BillRagService", "RetrievedSection"]
