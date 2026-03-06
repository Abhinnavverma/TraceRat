"""Pluggable embedding backend for generating vector representations.

Supports two backends:
- SentenceTransformerBackend: Local model (all-MiniLM-L6-v2, 384 dimensions).
  Free, no API key required. Default for development.
- OpenAIBackend: OpenAI text-embedding-3-small (1536 dimensions).
  Higher quality, requires OPENAI_API_KEY.

Use create_embedder() factory to instantiate the configured backend.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmbeddingBackend(ABC):
    """Abstract base class for embedding backends."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single text string into a vector."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings into vectors."""

    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""


class SentenceTransformerBackend(EmbeddingBackend):
    """Local embedding backend using sentence-transformers.

    Lazy-loads the model on first embed() call to avoid slow startup
    when the service might not need it immediately.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dimension: int | None = None

    def _load_model(self):
        """Lazy-load the SentenceTransformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                "Loaded SentenceTransformer model %s (dim=%d)",
                self._model_name,
                self._dimension,
            )

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings."""
        self._load_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]

    def dimension(self) -> int:
        """Return the embedding dimension (loads model if needed)."""
        self._load_model()
        return self._dimension


class OpenAIBackend(EmbeddingBackend):
    """OpenAI embedding backend using text-embedding-3-small.

    Requires OPENAI_API_KEY to be set. Uses async client for
    non-blocking embedding within the event loop.
    """

    DEFAULT_MODEL = "text-embedding-3-small"
    DEFAULT_DIMENSION = 1536

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
    ):
        self._model = model
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        """Lazy-initialize the OpenAI async client."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key)
            logger.info("Initialized OpenAI embedding client (model=%s)", self._model)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string via OpenAI API."""
        client = self._get_client()
        response = await client.embeddings.create(
            input=[text],
            model=self._model,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings via OpenAI API."""
        client = self._get_client()
        response = await client.embeddings.create(
            input=texts,
            model=self._model,
        )
        return [item.embedding for item in response.data]

    def dimension(self) -> int:
        """Return the embedding dimension for text-embedding-3-small."""
        return self.DEFAULT_DIMENSION


def create_embedder(
    backend_type: str = "sentence-transformer",
    model_name: str = "all-MiniLM-L6-v2",
    openai_api_key: str = "",
) -> EmbeddingBackend:
    """Factory function to create the configured embedding backend.

    Args:
        backend_type: 'sentence-transformer' or 'openai'.
        model_name: Model name for sentence-transformers backend.
        openai_api_key: API key for OpenAI backend.

    Returns:
        An EmbeddingBackend instance.

    Raises:
        ValueError: If backend_type is not recognized.
    """
    if backend_type == "sentence-transformer":
        return SentenceTransformerBackend(model_name=model_name)
    elif backend_type == "openai":
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI backend")
        return OpenAIBackend(api_key=openai_api_key, model=model_name)
    else:
        raise ValueError(
            f"Unknown embedding backend: {backend_type}. "
            "Use 'sentence-transformer' or 'openai'."
        )
