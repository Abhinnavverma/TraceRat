"""Tests for the vectorization Kafka consumer."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.consumer import VectorizationConsumer

from shared.config import KafkaSettings
from tests.conftest import SAMPLE_DIFF_CONTENT


class TestVectorizationConsumer:
    """Tests for the diff-content consumer pipeline."""

    def _make_consumer(
        self,
        mock_embedder,
        mock_vector_store,
        mock_producer,
    ) -> VectorizationConsumer:
        """Create a consumer with injected mocks."""
        settings = KafkaSettings(
            bootstrap_servers="localhost:9092",
            diff_content_topic="diff-content",
            pr_context_topic="pr-context",
        )
        consumer = VectorizationConsumer(
            kafka_settings=settings,
            embedder=mock_embedder,
            vector_store=mock_vector_store,
            producer=mock_producer,
        )
        return consumer

    @pytest.mark.asyncio
    async def test_processes_diff_content_end_to_end(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """Full pipeline: embed → store → search → publish context."""
        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_CONTENT,
        )

        # Embedding was generated
        mock_embedder.embed.assert_awaited_once()

        # Stored in Qdrant
        mock_vector_store.upsert.assert_awaited_once()
        upsert_kwargs = mock_vector_store.upsert.call_args.kwargs
        assert upsert_kwargs["point_id"] == "octocat/hello-world#42"

        # Similarity search was performed
        mock_vector_store.search.assert_awaited_once()

        # Published pr-context
        mock_producer.send.assert_awaited_once()
        send_kwargs = mock_producer.send.call_args.kwargs
        assert send_kwargs["topic"] == "pr-context"
        assert send_kwargs["key"] == "octocat/hello-world#42"

        context = send_kwargs["value"]
        assert context["event_id"] == "evt-001"
        assert context["embedding_stored"] is True
        assert len(context["similar_prs"]) == 3

    @pytest.mark.asyncio
    async def test_publishes_degraded_context_on_error(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """Should publish context with embedding_stored=False on failure."""
        mock_embedder.embed.side_effect = Exception("Model error")

        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_CONTENT,
        )

        # Still publishes context
        mock_producer.send.assert_awaited_once()
        context = mock_producer.send.call_args.kwargs["value"]
        assert context["embedding_stored"] is False
        assert context["similar_prs"] == []

    @pytest.mark.asyncio
    async def test_empty_diff_skips_embedding(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """Should skip embedding for empty diffs and publish context."""
        empty_content = {**SAMPLE_DIFF_CONTENT, "files": []}

        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=empty_content,
        )

        # Embedding not called
        mock_embedder.embed.assert_not_awaited()

        # Context still published
        mock_producer.send.assert_awaited_once()
        context = mock_producer.send.call_args.kwargs["value"]
        assert context["embedding_stored"] is False

    @pytest.mark.asyncio
    async def test_max_similarity_score_populated(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """max_similarity_score should be the highest from search results."""
        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_CONTENT,
        )

        context = mock_producer.send.call_args.kwargs["value"]
        assert context["max_similarity_score"] == 0.92

    @pytest.mark.asyncio
    async def test_historical_incident_rate_computed(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """historical_incident_rate should be fraction of incident PRs."""
        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_CONTENT,
        )

        context = mock_producer.send.call_args.kwargs["value"]
        # 1 incident out of 3 results
        assert abs(context["historical_incident_rate"] - 1 / 3) < 0.01

    @pytest.mark.asyncio
    async def test_message_key_format(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """Message key should be 'repo#pr_number'."""
        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_CONTENT,
        )

        send_kwargs = mock_producer.send.call_args.kwargs
        assert send_kwargs["key"] == "octocat/hello-world#42"

    @pytest.mark.asyncio
    async def test_search_excludes_self(
        self, mock_embedder, mock_vector_store, mock_producer
    ):
        """search() should pass exclude_point_id to avoid self-match."""
        consumer = self._make_consumer(
            mock_embedder, mock_vector_store, mock_producer
        )

        await consumer.handle_message(
            topic="diff-content",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_CONTENT,
        )

        search_kwargs = mock_vector_store.search.call_args.kwargs
        assert search_kwargs["exclude_point_id"] == "octocat/hello-world#42"
        assert search_kwargs["repo_filter"] == "octocat/hello-world"
