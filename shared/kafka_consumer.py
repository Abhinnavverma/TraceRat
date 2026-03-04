"""Async Kafka consumer base class using aiokafka."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from aiokafka import AIOKafkaConsumer

from shared.config import KafkaSettings

logger = logging.getLogger(__name__)


class KafkaConsumerBase(ABC):
    """Base class for Kafka consumers.

    Subclass and implement `handle_message` to process incoming messages.
    """

    def __init__(
        self,
        topics: list[str],
        settings: KafkaSettings | None = None,
        group_id: str | None = None,
    ):
        self._settings = settings or KafkaSettings()
        self._topics = topics
        self._group_id = group_id or self._settings.consumer_group
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        """Start the Kafka consumer."""
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._settings.bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Kafka consumer started",
            extra={"topics": self._topics, "group_id": self._group_id},
        )

    async def stop(self) -> None:
        """Stop the Kafka consumer."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")

    async def run(self) -> None:
        """Main consume loop. Call after start()."""
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")

        try:
            async for message in self._consumer:
                if not self._running:
                    break
                try:
                    await self.handle_message(
                        topic=message.topic,
                        key=message.key.decode("utf-8") if message.key else None,
                        value=message.value,
                    )
                except Exception:
                    logger.exception(
                        "Error processing message",
                        extra={"topic": message.topic, "offset": message.offset},
                    )
        finally:
            await self.stop()

    @abstractmethod
    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single message.

        Args:
            topic: Source topic name.
            key: Message key (may be None).
            value: Deserialized message payload.
        """
        ...
