"""Kafka consumer for the prediction service.

Subscribes to both ``delta-graph`` and ``pr-context`` topics, correlates
messages by ``event_id``, scores complete bundles, and publishes the
prediction via :class:`ResultPublisher`.
"""

from typing import Any

from app.services.correlator import SignalCorrelator
from app.services.result_publisher import ResultPublisher
from app.services.scorer import RiskScorer
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed

logger = get_logger("consumer")


class PredictionConsumer(KafkaConsumerBase):
    """Dual-topic consumer that correlates and scores PR signals.

    Parameters
    ----------
    kafka_settings:
        Kafka connection/topic configuration.
    correlator:
        In-memory signal correlator.
    scorer:
        Risk scoring engine.
    publisher:
        Dual-path result publisher.
    """

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        correlator: SignalCorrelator | None = None,
        scorer: RiskScorer | None = None,
        publisher: ResultPublisher | None = None,
    ) -> None:
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.delta_graph_topic, settings.pr_context_topic],
            settings=settings,
            group_id="prediction-service",
        )
        self._kafka_settings = settings
        self._correlator = correlator or SignalCorrelator()
        self._scorer = scorer or RiskScorer()
        self._publisher = publisher  # Must be set before consuming

    @property
    def correlator(self) -> SignalCorrelator:
        """Expose correlator for sweep task."""
        return self._correlator

    @property
    def scorer(self) -> RiskScorer:
        """Expose scorer for sweep task."""
        return self._scorer

    @property
    def publisher(self) -> ResultPublisher | None:
        """Expose publisher for sweep task."""
        return self._publisher

    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single delta-graph or pr-context message.

        1. Identify the signal type from the topic name.
        2. Feed it to the correlator.
        3. If the bundle is now complete, score and publish.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="prediction-service"
        ).inc()

        event_id = value.get("event_id", "unknown")

        # Determine signal type from topic
        delta_topic = self._kafka_settings.delta_graph_topic
        context_topic = self._kafka_settings.pr_context_topic

        if topic == delta_topic:
            signal_type = "delta-graph"
        elif topic == context_topic:
            signal_type = "pr-context"
        else:
            logger.warning("Unexpected topic — skipping", topic=topic)
            return

        logger.info(
            "Message received",
            topic=topic,
            signal=signal_type,
            event_id=event_id,
            key=key,
        )

        try:
            bundle = self._correlator.ingest(signal_type, event_id, value)

            if bundle is not None:
                output = self._scorer.score(bundle)
                if self._publisher:
                    await self._publisher.publish(output)
                else:
                    logger.warning(
                        "Publisher not set — prediction not published",
                        event_id=event_id,
                    )
        except Exception:
            logger.exception(
                "Failed to process message",
                event_id=event_id,
                topic=topic,
            )
