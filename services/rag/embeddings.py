"""Embedding providers for the bill-section RAG pipeline.

The retrieval service depends only on the `EmbeddingProvider` interface, so
the concrete provider is configurable (env-driven) and swappable without
touching retrieval/caching logic. `SentenceTransformerEmbeddingProvider` is
the default: local semantic embeddings (no API key), matching on meaning
rather than exact vocabulary overlap. `TfidfEmbeddingProvider` is a
dependency-light fallback (scikit-learn only, no model download) for
environments without network access. `OpenAIEmbeddingProvider` is available
for hosted production embeddings and is only imported/instantiated if
explicitly selected.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Turns text into vectors for similarity search.

    `fit` lets stateful providers (e.g. a per-bill TF-IDF vectorizer) build
    their vocabulary from a bill's own sections before embedding; stateless
    providers (e.g. a hosted embeddings API) can no-op it.
    """

    name: str = "base"

    @abstractmethod
    def fit(self, texts: List[str]) -> None:
        ...

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        ...

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]


class TfidfEmbeddingProvider(EmbeddingProvider):
    """Default embedding provider: per-bill TF-IDF vectors + cosine similarity.

    Fitting per bill (rather than a single global vocabulary) keeps this
    accurate for small, self-contained corpora like one bill's sections,
    with no external dependency or API key required.
    """

    name = "tfidf-v1"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._fitted = False

    def fit(self, texts: List[str]) -> None:
        self._vectorizer.fit(texts)
        self._fitted = True

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not self._fitted:
            raise RuntimeError("TfidfEmbeddingProvider.fit() must be called before embedding")
        matrix = self._vectorizer.transform(texts)
        return matrix.toarray().tolist()


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local semantic embeddings via sentence-transformers (no API key).

    Preferred default over TF-IDF: it matches on meaning (e.g. "who
    qualifies" ~ "eligibility requirements") rather than exact vocabulary
    overlap, at the cost of a one-time model download/load. Stateless
    across bills -- `fit` is a no-op since the model isn't per-bill.
    """

    _model = None  # loaded lazily, shared across instances in-process

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self.name = f"sentence-transformers-{model_name}"

    def _get_model(self):
        if SentenceTransformerEmbeddingProvider._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading sentence-transformers model %s", self._model_name)
            SentenceTransformerEmbeddingProvider._model = SentenceTransformer(self._model_name)
        return SentenceTransformerEmbeddingProvider._model

    def fit(self, texts: List[str]) -> None:
        pass  # stateless: pretrained model, no per-bill vocabulary to fit

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()
        return model.encode(list(texts), convert_to_numpy=True).tolist()


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Hosted OpenAI embeddings (e.g. text-embedding-3-small). Stateless."""

    name = "openai-text-embedding-3-small"

    def __init__(self, model: str = "text-embedding-3-small"):
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required to use OpenAIEmbeddingProvider")
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self.name = f"openai-{model}"

    def fit(self, texts: List[str]) -> None:
        pass  # stateless: no vocabulary to fit

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


_PROVIDERS = {
    "sentence-transformers": SentenceTransformerEmbeddingProvider,
    "tfidf": TfidfEmbeddingProvider,
    "openai": OpenAIEmbeddingProvider,
}


def get_embedding_provider(provider_name: str = None) -> EmbeddingProvider:
    """Instantiate the configured embedding provider.

    Selected via the `provider_name` argument, falling back to the
    `LESSON_EMBEDDING_PROVIDER` env var, defaulting to `sentence-transformers`
    (local, semantic, no API key required).
    """
    provider_name = provider_name or os.getenv("LESSON_EMBEDDING_PROVIDER", "sentence-transformers")
    try:
        provider_cls = _PROVIDERS[provider_name]
    except KeyError:
        raise ValueError(
            f"Unknown embedding provider '{provider_name}'. Valid options: {sorted(_PROVIDERS)}"
        )
    return provider_cls()
