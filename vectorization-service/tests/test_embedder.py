"""Tests for the pluggable embedding backend."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.embedder import (
    OpenAIBackend,
    SentenceTransformerBackend,
    create_embedder,
)


class TestSentenceTransformerBackend:
    """Tests for the local sentence-transformers backend."""

    @pytest.mark.asyncio
    async def test_embed_returns_list_of_floats(self):
        """embed() should return a list of floats."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
        mock_model.get_sentence_embedding_dimension.return_value = 3

        backend = SentenceTransformerBackend(model_name="test-model")
        backend._model = mock_model
        backend._dimension = 3

        result = await backend.embed("test text")
        assert isinstance(result, list)
        assert len(result) == 3
        mock_model.encode.assert_called_once_with(
            "test text", normalize_embeddings=True
        )

    @pytest.mark.asyncio
    async def test_embed_batch_returns_list_of_lists(self):
        """embed_batch() should return a list of embedding lists."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ])
        mock_model.get_sentence_embedding_dimension.return_value = 3

        backend = SentenceTransformerBackend(model_name="test-model")
        backend._model = mock_model
        backend._dimension = 3

        result = await backend.embed_batch(["text1", "text2"])
        assert len(result) == 2
        assert len(result[0]) == 3

    def test_dimension_returns_correct_value(self):
        """dimension() should return the model's embedding size."""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        backend = SentenceTransformerBackend()
        backend._model = mock_model
        backend._dimension = 384

        assert backend.dimension() == 384

    def test_lazy_loads_model(self):
        """Model should be loaded lazily on first dimension() call."""
        import types

        # Create a fake sentence_transformers module
        fake_module = types.ModuleType("sentence_transformers")
        mock_st_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_sentence_embedding_dimension.return_value = 384
        mock_st_class.return_value = mock_instance
        fake_module.SentenceTransformer = mock_st_class

        backend = SentenceTransformerBackend(model_name="all-MiniLM-L6-v2")
        assert backend._model is None

        with patch.dict("sys.modules", {"sentence_transformers": fake_module}):
            # Re-import is not needed; _load_model does a lazy import
            dim = backend.dimension()

        assert dim == 384
        mock_st_class.assert_called_once_with("all-MiniLM-L6-v2")


class TestOpenAIBackend:
    """Tests for the OpenAI embedding backend."""

    @pytest.mark.asyncio
    async def test_embed_calls_openai_api(self):
        """embed() should call the OpenAI embeddings API."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_data_item = MagicMock()
        mock_data_item.embedding = [0.1, 0.2, 0.3]
        mock_response.data = [mock_data_item]
        mock_client.embeddings.create.return_value = mock_response

        backend = OpenAIBackend(api_key="test-key")
        backend._client = mock_client

        result = await backend.embed("test text")
        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_awaited_once_with(
            input=["test text"],
            model="text-embedding-3-small",
        )

    @pytest.mark.asyncio
    async def test_embed_batch_returns_all_embeddings(self):
        """embed_batch() should return embeddings for all inputs."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        item1 = MagicMock()
        item1.embedding = [0.1, 0.2]
        item2 = MagicMock()
        item2.embedding = [0.3, 0.4]
        mock_response.data = [item1, item2]
        mock_client.embeddings.create.return_value = mock_response

        backend = OpenAIBackend(api_key="test-key")
        backend._client = mock_client

        result = await backend.embed_batch(["text1", "text2"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    def test_dimension_returns_1536(self):
        """OpenAI text-embedding-3-small has 1536 dimensions."""
        backend = OpenAIBackend(api_key="test-key")
        assert backend.dimension() == 1536


class TestCreateEmbedder:
    """Tests for the factory function."""

    def test_creates_sentence_transformer_backend(self):
        """Should create SentenceTransformerBackend by default."""
        embedder = create_embedder(backend_type="sentence-transformer")
        assert isinstance(embedder, SentenceTransformerBackend)

    def test_creates_openai_backend(self):
        """Should create OpenAIBackend when specified."""
        embedder = create_embedder(
            backend_type="openai",
            openai_api_key="test-key",
        )
        assert isinstance(embedder, OpenAIBackend)

    def test_openai_requires_api_key(self):
        """Should raise ValueError when OpenAI backend has no key."""
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            create_embedder(backend_type="openai", openai_api_key="")

    def test_unknown_backend_raises_error(self):
        """Should raise ValueError for unknown backend types."""
        with pytest.raises(ValueError, match="Unknown embedding backend"):
            create_embedder(backend_type="invalid")
