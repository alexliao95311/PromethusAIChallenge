"""Embedding cache for the bill-section RAG pipeline.

Caches, per bill_id, the split+embedded sections plus the fitted embedding
provider (needed to embed queries consistently with stateful providers like
TF-IDF) keyed by a hash of the normalized bill text. A text change produces a
different hash, which naturally invalidates the cache without needing an
explicit eviction step.

`InMemoryEmbeddingCache` is the default (Increment 1 scope: "simple
in-memory implementation first"). `EmbeddingCache` is an abstract interface
so a later increment can swap in a Firestore-backed or vector-database cache
without changing `BillRagService`.
"""

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from models.lesson_models import BillSection
from services.rag.embeddings import EmbeddingProvider


def normalize_bill_text(bill_text: str) -> str:
    """Collapse whitespace so cosmetic-only diffs don't bust the cache."""
    return re.sub(r"\s+", " ", bill_text).strip()


def compute_text_hash(bill_text: str) -> str:
    normalized = normalize_bill_text(bill_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class CachedBillEmbeddings:
    bill_id: str
    text_hash: str
    sections: List[BillSection]
    provider: EmbeddingProvider


class EmbeddingCache(ABC):
    @abstractmethod
    def get(self, bill_id: str) -> Optional[CachedBillEmbeddings]:
        ...

    @abstractmethod
    def set(self, entry: CachedBillEmbeddings) -> None:
        ...


class InMemoryEmbeddingCache(EmbeddingCache):
    """Process-local cache, keyed by bill_id. Not shared across workers/restarts."""

    def __init__(self):
        self._store = {}

    def get(self, bill_id: str) -> Optional[CachedBillEmbeddings]:
        return self._store.get(bill_id)

    def set(self, entry: CachedBillEmbeddings) -> None:
        self._store[entry.bill_id] = entry
