"""A dependency-free, deterministic fake `EmbeddingProvider` for tests that
need *some* consistent vector per text but not real semantic quality
(caching behavior, top_k/ordering mechanics, generation-pipeline plumbing
against a mocked LLM). Uses the classic "hashing trick" (bag-of-words
hashed into a fixed-size vector) -- no numpy, scikit-learn, or
sentence-transformers/torch required, so these tests run in a lightweight
environment.

Tests whose assertions genuinely depend on real semantic similarity (e.g.
`tests/test_bill_rag.py`'s retrieval-quality queries, or distractor/
irrelevance threshold checks calibrated against real embeddings) should NOT
use this fixture -- they should use the real `sentence-transformers`
provider, guarded with `pytest.importorskip("sentence_transformers")` so
they skip cleanly rather than error when the ML stack isn't installed.
"""

import hashlib
import re
from typing import List

from services.rag.embeddings import EmbeddingProvider

VECTOR_SIZE = 64
_WORD_RE = re.compile(r"[a-z0-9]+")


class FakeEmbeddingProvider(EmbeddingProvider):
    name = "fake-hashing-v1"

    def fit(self, texts: List[str]) -> None:
        pass  # stateless

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> List[float]:
        vector = [0.0] * VECTOR_SIZE
        for word in _WORD_RE.findall(text.lower()):
            index = int(hashlib.md5(word.encode()).hexdigest(), 16) % VECTOR_SIZE
            vector[index] += 1.0
        return vector
