"""Kafka consumer for runtime telemetry ingestion.

Consumes telemetry events from the telemetry-events topic and enriches
the dependency graph in Neo4j with runtime edge and node weights.
Supports batched updates for efficiency.
"""

import time
from typing import Any

from app.models import EdgeWeight, NodeWeight, TelemetryEvent
from app.services.neo4j_client import Neo4jClient
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed

logger = get_logger("telemetry_consumer")

# --- Normalization Constants ---
# These define the scale for normalizing raw telemetry values to 0-1.
# Adjust based on production traffic patterns.
MAX_CALL_FREQUENCY = 10_000.0  # calls/sec
MAX_TRAFFIC_VOLUME = 1_000_000.0  # requests/hour
MAX_LATENCY_P99 = 5_000.0  # ms


def _normalize(value: float, max_val: float) -> float:
    """Clamp and normalize a value to [0, 1]."""
    if max_val <= 0:
        return 0.0
    return min(max(value / max_val, 0.0), 1.0)


class TelemetryConsumer(KafkaConsumerBase):
    """Consumes telemetry events and updates Neo4j graph weights.

    For each telemetry event:
    1. Parses the event into a TelemetryEvent model
    2. Normalizes raw metrics to 0-1 scale
    3. Upserts edge weight between source and target services
    4. Upserts node weight for the target service (callees get updated
       most frequently since they're the dependency being measured)
    """

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        neo4j_client: Neo4jClient | None = None,
    ):
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.telemetry_events_topic],
            settings=settings,
            group_id="dependency-graph-telemetry",
        )
        self._neo4j = neo4j_client or Neo4jClient()
        self._kafka_settings = settings
        self._batch: list[TelemetryEvent] = []
        self._batch_size = 50
        self._last_flush = time.monotonic()
        self._flush_interval = 5.0  # seconds

    @property
    def neo4j_client(self) -> Neo4jClient:
        """Expose Neo4j client for lifespan management."""
        return self._neo4j

    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single telemetry event.

        Validates the event and adds to batch. Flushes batch when
        size or time threshold is reached.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="dependency-graph-telemetry"
        ).inc()

        try:
            event = TelemetryEvent(**value)
        except Exception:
            logger.exception("Invalid telemetry event", raw=value)
            return

        self._batch.append(event)

        # Flush if batch is full or enough time has elapsed
        elapsed = time.monotonic() - self._last_flush
        if len(self._batch) >= self._batch_size or elapsed >= self._flush_interval:
            await self._flush_batch()

    async def _flush_batch(self) -> None:
        """Write accumulated telemetry events to Neo4j."""
        if not self._batch:
            return

        batch = self._batch
        self._batch = []
        self._last_flush = time.monotonic()

        logger.info("Flushing telemetry batch", batch_size=len(batch))

        for event in batch:
            try:
                await self._process_event(event)
            except Exception:
                logger.exception(
                    "Failed to process telemetry event",
                    source=event.source_service,
                    target=event.target_service,
                )

    async def _process_event(self, event: TelemetryEvent) -> None:
        """Normalize and upsert a single telemetry event into Neo4j."""
        # Normalize raw values to 0-1
        norm_frequency = _normalize(event.call_frequency, MAX_CALL_FREQUENCY)
        norm_traffic = _normalize(event.traffic_volume, MAX_TRAFFIC_VOLUME)
        norm_latency = _normalize(event.latency_p99, MAX_LATENCY_P99)

        # Upsert edge weight
        edge_weight = EdgeWeight(
            call_frequency=norm_frequency,
            traffic_volume=norm_traffic,
            failure_propagation_rate=event.error_rate,
        )
        await self._neo4j.upsert_edge_weight(
            source=event.source_service,
            target=event.target_service,
            weight=edge_weight,
        )

        # Upsert target node weight (the dependency being called)
        node_weight = NodeWeight(
            request_volume=norm_traffic,
            error_rate=event.error_rate,
            latency_sensitivity=norm_latency,
            production_criticality=0.0,  # Set by separate criticality scoring job
        )
        await self._neo4j.upsert_node_weight(
            node_name=event.target_service,
            node_type="service",
            weight=node_weight,
        )

    async def flush_remaining(self) -> None:
        """Flush any remaining events on shutdown."""
        await self._flush_batch()
