"""Async Kafka producer wrapper using aiokafka."""

import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer

from shared.config import KafkaSettings

logger = logging.getLogger(__name__)


class KafkaProducerClient:
    """Async Kafka producer with JSON serialization."""

    def __init__(self, settings: KafkaSettings | None = None):
        self._settings = settings or KafkaSettings()
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Start the Kafka producer."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self._producer.start()
        logger.info(
            "Kafka producer started",
            extra={"bootstrap_servers": self._settings.bootstrap_servers},
        )

    async def stop(self) -> None:
        """Stop the Kafka producer."""
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def send(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        """Send a message to a Kafka topic.

        Args:
            topic: Target Kafka topic.
            value: Message payload (will be JSON-serialized).
            key: Optional message key for partitioning.
        """
        if not self._producer:
            raise RuntimeError("Kafka producer is not started. Call start() first.")

        await self._producer.send_and_wait(topic=topic, value=value, key=key)
        logger.info(
            "Message sent to Kafka",
            extra={"topic": topic, "key": key},
        )

    async def send_pr_event(self, event: dict[str, Any]) -> None:
        """Convenience method to send a PR event to the configured topic.

        Args:
            event: PR event payload.
        """
        key = f"{event.get('repo_full_name', 'unknown')}#{event.get('pr_number', 0)}"
        await self.send(
            topic=self._settings.pr_events_topic,
            value=event,
            key=key,
        )

    @property
    def is_connected(self) -> bool:
        """Check if the producer is connected."""
        return self._producer is not None
