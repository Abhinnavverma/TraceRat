"""Qdrant vector store client for storing and searching PR embeddings.

Wraps the qdrant-client async API to provide:
- Collection lifecycle management
- Embedding upsert with PR metadata payloads
- Cosine similarity search with optional repo filtering
- Health checking
"""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

logger = logging.getLogger(__name__)


class VectorStore:
    """Async Qdrant client wrapper for PR embedding storage and search."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "pr-embeddings",
    ):
        self._host = host
        self._port = port
        self._collection_name = collection_name
        self._client: AsyncQdrantClient | None = None

    async def connect(self) -> None:
        """Initialize the Qdrant async client."""
        self._client = AsyncQdrantClient(
            host=self._host,
            port=self._port,
        )
        logger.info(
            "Connected to Qdrant at %s:%d", self._host, self._port
        )

    async def close(self) -> None:
        """Close the Qdrant client connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Qdrant client closed")

    async def health_check(self) -> bool:
        """Check if Qdrant is reachable."""
        if not self._client:
            return False
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False

    async def ensure_collection(self, dimension: int) -> None:
        """Create the collection if it does not exist.

        Uses cosine distance for similarity matching.

        Args:
            dimension: Dimensionality of the embedding vectors.
        """
        if not self._client:
            raise RuntimeError("VectorStore not connected")

        try:
            await self._client.get_collection(self._collection_name)
            logger.info(
                "Collection '%s' already exists", self._collection_name
            )
        except (UnexpectedResponse, Exception):
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(
                "Created collection '%s' (dim=%d, cosine)",
                self._collection_name,
                dimension,
            )

    async def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Store or update an embedding with metadata.

        Args:
            point_id: Unique identifier (e.g., "owner/repo#42").
            vector: The embedding vector.
            payload: PR metadata to store alongside the vector.
        """
        if not self._client:
            raise RuntimeError("VectorStore not connected")

        await self._client.upsert(
            collection_name=self._collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                ),
            ],
        )
        logger.debug("Upserted point %s", point_id)

    async def search(
        self,
        vector: list[float],
        limit: int = 5,
        repo_filter: str | None = None,
        exclude_point_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for the most similar embeddings.

        Args:
            vector: Query embedding vector.
            limit: Maximum number of results to return.
            repo_filter: If set, restrict results to this repository.
            exclude_point_id: Point ID to exclude (avoid self-match).

        Returns:
            List of dicts with 'id', 'score', and 'payload' keys.
        """
        if not self._client:
            raise RuntimeError("VectorStore not connected")

        # Build optional filter conditions
        filter_conditions = []
        if repo_filter:
            filter_conditions.append(
                models.FieldCondition(
                    key="repo_full_name",
                    match=models.MatchValue(value=repo_filter),
                )
            )

        query_filter = None
        if filter_conditions:
            query_filter = models.Filter(must=filter_conditions)

        results = await self._client.search(
            collection_name=self._collection_name,
            query_vector=vector,
            limit=limit + (1 if exclude_point_id else 0),
            query_filter=query_filter,
        )

        search_results = []
        for point in results:
            point_id = str(point.id)
            if exclude_point_id and point_id == exclude_point_id:
                continue
            search_results.append({
                "id": point_id,
                "score": point.score,
                "payload": point.payload or {},
            })

        return search_results[:limit]

    async def delete(self, point_ids: list[str]) -> None:
        """Delete points by their IDs.

        Args:
            point_ids: List of point IDs to remove.
        """
        if not self._client:
            raise RuntimeError("VectorStore not connected")

        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.PointIdsList(
                points=point_ids,
            ),
        )
        logger.debug("Deleted %d points", len(point_ids))
