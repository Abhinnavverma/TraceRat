"""Kafka consumer for processing diff-metadata messages.

Consumes from the diff-metadata topic, computes the delta dependency
graph using the weighted graph in Neo4j, and publishes results to
the delta-graph topic for the prediction-service.
"""

from typing import Any

from app.models import DeltaGraphResult
from app.services.delta_calculator import DeltaCalculator
from app.services.neo4j_client import Neo4jClient
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed, kafka_messages_produced

logger = get_logger("consumer")


class DependencyGraphConsumer(KafkaConsumerBase):
    """Consumes diff-metadata events and produces delta graph results.

    For each diff-metadata message:
    1. Extracts changed files and affected modules
    2. Queries the weighted dependency graph in Neo4j
    3. Computes delta graph via BFS with weight multiplication
    4. Publishes DeltaGraphResult to delta-graph topic
    """

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        neo4j_client: Neo4jClient | None = None,
        delta_calculator: DeltaCalculator | None = None,
        producer: KafkaProducerClient | None = None,
    ):
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.diff_metadata_topic],
            settings=settings,
            group_id="dependency-graph-service",
        )
        self._kafka_settings = settings
        self._neo4j = neo4j_client or Neo4jClient()
        self._delta_calculator = delta_calculator or DeltaCalculator(self._neo4j)
        self._producer = producer or KafkaProducerClient(settings)

    @property
    def producer(self) -> KafkaProducerClient:
        """Expose producer for lifespan management."""
        return self._producer

    @property
    def neo4j_client(self) -> Neo4jClient:
        """Expose Neo4j client for lifespan management."""
        return self._neo4j

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
        """Process a single diff-metadata message.

        Args:
            topic: Source Kafka topic.
            key: Message key (repo#pr_number).
            value: Deserialized DiffMetadata payload.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="dependency-graph-service"
        ).inc()

        event_id = value.get("event_id", "unknown")
        repo_full_name = value.get("repo_full_name", "")
        pr_number = value.get("pr_number", 0)
        head_sha = value.get("head_sha", "")
        installation_id = value.get("installation_id", 0)

        logger.info(
            "Processing diff-metadata event",
            event_id=event_id,
            repo=repo_full_name,
            pr_number=pr_number,
        )

        changed_files = value.get("changed_files", [])
        affected_modules = value.get("affected_modules", [])

        # Check if graph exists for this repo
        graph_available = True

        try:
            affected_components = await self._delta_calculator.compute_delta(
                changed_files=changed_files,
                affected_modules=affected_modules,
                repo_full_name=repo_full_name,
            )
        except Exception:
            logger.exception(
                "Delta computation failed — publishing empty result",
                event_id=event_id,
                repo=repo_full_name,
            )
            affected_components = []
            graph_available = False

        # Build changed node names for the output
        changed_nodes: list[str] = []
        for module in affected_modules:
            name = module.get("module_name", "")
            if name:
                changed_nodes.append(name)
        if not changed_nodes:
            changed_nodes = [
                f.get("filename", "") for f in changed_files if f.get("filename")
            ]

        # Compute aggregate risk score (max of component scores)
        aggregate_risk = (
            max(c.risk_score for c in affected_components)
            if affected_components
            else 0.0
        )

        # Compute max depth reached
        max_depth = (
            max(c.dependency_depth for c in affected_components)
            if affected_components
            else 0
        )

        # Build result
        result = DeltaGraphResult(
            event_id=event_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            installation_id=installation_id,
            changed_nodes=changed_nodes,
            affected_components=affected_components,
            max_depth_reached=max_depth,
            total_affected_count=len(affected_components),
            aggregate_risk_score=aggregate_risk,
            graph_available=graph_available,
        )

        # Publish to delta-graph topic
        message_key = f"{repo_full_name}#{pr_number}"
        await self._producer.send(
            topic=self._kafka_settings.delta_graph_topic,
            value=result.model_dump(),
            key=message_key,
        )
        kafka_messages_produced.labels(
            topic=self._kafka_settings.delta_graph_topic
        ).inc()

        logger.info(
            "Delta graph result published",
            event_id=event_id,
            repo=repo_full_name,
            pr_number=pr_number,
            affected_count=len(affected_components),
            aggregate_risk=aggregate_risk,
            graph_available=graph_available,
        )
