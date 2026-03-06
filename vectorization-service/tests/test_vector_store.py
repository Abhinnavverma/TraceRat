"""Tests for the Qdrant vector store client."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vector_store import VectorStore


class TestVectorStoreLifecycle:
    """Tests for connection lifecycle management."""

    @pytest.mark.asyncio
    async def test_connect_creates_client(self):
        """connect() should initialize the Qdrant client."""
        with patch("app.services.vector_store.AsyncQdrantClient") as mock_cls:
            store = VectorStore(host="localhost", port=6333)
            await store.connect()
            mock_cls.assert_called_once_with(host="localhost", port=6333)
            assert store._client is not None

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        """close() should close the client and set to None."""
        store = VectorStore()
        store._client = AsyncMock()
        await store.close()
        store._client is None

    @pytest.mark.asyncio
    async def test_health_check_true_when_connected(self):
        """health_check() should return True when Qdrant is reachable."""
        store = VectorStore()
        store._client = AsyncMock()
        store._client.get_collections.return_value = []
        assert await store.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false_when_not_connected(self):
        """health_check() should return False when client is None."""
        store = VectorStore()
        assert await store.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_false_on_error(self):
        """health_check() should return False when Qdrant errors."""
        store = VectorStore()
        store._client = AsyncMock()
        store._client.get_collections.side_effect = Exception("connection refused")
        assert await store.health_check() is False


class TestVectorStoreCollection:
    """Tests for collection management."""

    @pytest.mark.asyncio
    async def test_ensure_collection_creates_when_missing(self):
        """Should create collection if it doesn't exist."""
        store = VectorStore(collection_name="test-collection")
        store._client = AsyncMock()
        store._client.get_collection.side_effect = Exception("not found")

        await store.ensure_collection(dimension=384)

        store._client.create_collection.assert_awaited_once()
        call_kwargs = store._client.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == "test-collection"

    @pytest.mark.asyncio
    async def test_ensure_collection_skips_when_exists(self):
        """Should not create collection if it already exists."""
        store = VectorStore(collection_name="test-collection")
        store._client = AsyncMock()
        store._client.get_collection.return_value = MagicMock()

        await store.ensure_collection(dimension=384)

        store._client.create_collection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ensure_collection_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        store = VectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await store.ensure_collection(dimension=384)


class TestVectorStoreOperations:
    """Tests for upsert, search, and delete operations."""

    @pytest.mark.asyncio
    async def test_upsert_stores_point(self):
        """upsert() should call client.upsert with correct params."""
        store = VectorStore(collection_name="test-col")
        store._client = AsyncMock()

        await store.upsert(
            point_id="repo/name#42",
            vector=[0.1, 0.2, 0.3],
            payload={"pr_number": 42},
        )

        store._client.upsert.assert_awaited_once()
        call_kwargs = store._client.upsert.call_args.kwargs
        assert call_kwargs["collection_name"] == "test-col"
        points = call_kwargs["points"]
        assert len(points) == 1
        assert points[0].id == "repo/name#42"
        assert points[0].vector == [0.1, 0.2, 0.3]
        assert points[0].payload == {"pr_number": 42}

    @pytest.mark.asyncio
    async def test_upsert_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        store = VectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await store.upsert("id", [0.1], {})

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """search() should return formatted search results."""
        store = VectorStore(collection_name="test-col")
        store._client = AsyncMock()

        mock_point = MagicMock()
        mock_point.id = "repo/name#10"
        mock_point.score = 0.92
        mock_point.payload = {"pr_number": 10}

        store._client.search.return_value = [mock_point]

        results = await store.search(vector=[0.1, 0.2], limit=5)

        assert len(results) == 1
        assert results[0]["id"] == "repo/name#10"
        assert results[0]["score"] == 0.92
        assert results[0]["payload"] == {"pr_number": 10}

    @pytest.mark.asyncio
    async def test_search_excludes_self(self):
        """search() should exclude the current PR from results."""
        store = VectorStore(collection_name="test-col")
        store._client = AsyncMock()

        point1 = MagicMock()
        point1.id = "repo/name#42"
        point1.score = 1.0
        point1.payload = {}

        point2 = MagicMock()
        point2.id = "repo/name#10"
        point2.score = 0.85
        point2.payload = {}

        store._client.search.return_value = [point1, point2]

        results = await store.search(
            vector=[0.1],
            limit=5,
            exclude_point_id="repo/name#42",
        )

        assert len(results) == 1
        assert results[0]["id"] == "repo/name#10"

    @pytest.mark.asyncio
    async def test_search_with_repo_filter(self):
        """search() with repo_filter should pass filter to client."""
        store = VectorStore(collection_name="test-col")
        store._client = AsyncMock()
        store._client.search.return_value = []

        await store.search(
            vector=[0.1],
            limit=5,
            repo_filter="octocat/hello-world",
        )

        call_kwargs = store._client.search.call_args.kwargs
        assert call_kwargs["query_filter"] is not None

    @pytest.mark.asyncio
    async def test_search_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        store = VectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await store.search([0.1])

    @pytest.mark.asyncio
    async def test_delete_removes_points(self):
        """delete() should call client.delete with point IDs."""
        store = VectorStore(collection_name="test-col")
        store._client = AsyncMock()

        await store.delete(["repo/name#1", "repo/name#2"])

        store._client.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        store = VectorStore()
        with pytest.raises(RuntimeError, match="not connected"):
            await store.delete(["id1"])
