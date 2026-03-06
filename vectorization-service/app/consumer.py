"""Kafka consumer for processing diff-content messages.

Consumes from the diff-content topic, generates embeddings, stores
them in Qdrant, performs similarity search, and publishes enriched
pr-context messages for the prediction service.
"""

from __future__ import annotations

from typing import Any

from app.models import PRContext, PRMetadata
from app.services.diff_chunker import chunk_diff, compute_change_stats, extract_file_list
from app.services.embedder import EmbeddingBackend
from app.services.similarity_enricher import compute_incident_rate, enrich_results
from app.services.vector_store import VectorStore
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed, kafka_messages_produced

logger = get_logger("vectorization-consumer")


class VectorizationConsumer(KafkaConsumerBase):
    """Consumes diff-content events and produces pr-context results.

    For each diff-content message:
    1. Chunks the diff into embeddable text
    2. Generates an embedding via the configured backend
    3. Stores the embedding in Qdrant with PR metadata
    4. Searches for similar historical PRs
    5. Publishes a PRContext message to the pr-context topic
    """

    SIMILARITY_TOP_K = 5

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        embedder: EmbeddingBackend | None = None,
        vector_store: VectorStore | None = None,
        producer: KafkaProducerClient | None = None,
    ):
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.diff_content_topic],
            settings=settings,
            group_id="vectorization-service",
        )
        self._kafka_settings = settings
        self._embedder = embedder
        self._vector_store = vector_store
        self._producer = producer or KafkaProducerClient(settings)

    @property
    def producer(self) -> KafkaProducerClient:
        """Expose producer for lifespan health checks."""
        return self._producer

    async def start(self) -> None:
        """Start consumer and producer."""
        await self._producer.start()
        await super().start()

    async def stop(self) -> None:
        """Stop consumer and producer."""
        await super().stop()
        await self._producer.stop()

    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single diff-content message.

        Args:
            topic: Source Kafka topic.
            key: Message key (repo#pr_number).
            value: Deserialized DiffContent payload.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="vectorization-service"
        ).inc()

        event_id = value.get("event_id", "unknown")
        repo_full_name = value.get("repo_full_name", "")
        pr_number = value.get("pr_number", 0)
        head_sha = value.get("head_sha", "")

        logger.info(
            "Processing diff-content event",
            event_id=event_id,
            repo=repo_full_name,
            pr_number=pr_number,
        )

        embedding_stored = False
        similar_prs_enriched = []
        max_similarity = 0.0
        incident_rate = 0.0

        try:
            # 1. Chunk the diff into embeddable text
            diff_text = chunk_diff(value)
            if not diff_text:
                logger.warning(
                    "Empty diff text, skipping embedding",
                    event_id=event_id,
                )
                await self._publish_context(
                    event_id, repo_full_name, pr_number, head_sha,
                    [], 0.0, 0.0, False,
                )
                return

            # 2. Generate embedding
            vector = await self._embedder.embed(diff_text)

            # 3. Build metadata payload
            file_list = extract_file_list(value)
            stats = compute_change_stats(value)
            metadata = PRMetadata(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                head_sha=head_sha,
                files_changed=file_list,
                total_additions=stats["total_additions"],
                total_deletions=stats["total_deletions"],
            )

            # 4. Store in Qdrant
            point_id = f"{repo_full_name}#{pr_number}"
            await self._vector_store.upsert(
                point_id=point_id,
                vector=vector,
                payload=metadata.model_dump(),
            )
            embedding_stored = True

            # 5. Search for similar PRs
            search_results = await self._vector_store.search(
                vector=vector,
                limit=self.SIMILARITY_TOP_K,
                repo_filter=repo_full_name,
                exclude_point_id=point_id,
            )

            # 6. Enrich results
            similar_prs_enriched = enrich_results(search_results, file_list)
            max_similarity = (
                similar_prs_enriched[0].similarity_score
                if similar_prs_enriched
                else 0.0
            )
            incident_rate = compute_incident_rate(similar_prs_enriched)

        except Exception:
            logger.exception(
                "Vectorization failed — publishing degraded context",
                event_id=event_id,
                repo=repo_full_name,
            )

        # 7. Publish pr-context
        await self._publish_context(
            event_id, repo_full_name, pr_number, head_sha,
            similar_prs_enriched, max_similarity, incident_rate,
            embedding_stored,
        )

    async def _publish_context(
        self,
        event_id: str,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
        similar_prs: list,
        max_similarity: float,
        incident_rate: float,
        embedding_stored: bool,
    ) -> None:
        """Build and publish the PRContext message."""
        context = PRContext(
            event_id=event_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            similar_prs=similar_prs,
            max_similarity_score=max_similarity,
            historical_incident_rate=incident_rate,
            embedding_stored=embedding_stored,
        )

        msg_key = f"{repo_full_name}#{pr_number}"
        await self._producer.send(
            topic=self._kafka_settings.pr_context_topic,
            value=context.model_dump(),
            key=msg_key,
        )

        kafka_messages_produced.labels(
            topic=self._kafka_settings.pr_context_topic
        ).inc()

        logger.info(
            "Published pr-context",
            event_id=event_id,
            repo=repo_full_name,
            pr_number=pr_number,
            similar_count=len(similar_prs),
            embedding_stored=embedding_stored,
        )
