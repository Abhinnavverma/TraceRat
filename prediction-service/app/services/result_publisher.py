"""Kafka-only result publisher.

Publishes every prediction to the **Kafka ``prediction-results`` topic**,
which is consumed downstream by the prompt-generation-service.

The HTTP POST path to the api-gateway has been removed — the LLM
service is now the sole publisher to the api-gateway ``/results``
endpoint.
"""

from app.models import PredictionOutput
from app.services.result_mapper import ResultMapper
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger
from shared.metrics import kafka_messages_produced

logger = get_logger("result_publisher")


class ResultPublisher:
    """Publish prediction results to the Kafka prediction-results topic.

    Parameters
    ----------
    producer:
        Shared Kafka producer instance.
    prediction_topic:
        Kafka topic name for prediction results.
    """

    def __init__(
        self,
        producer: KafkaProducerClient,
        prediction_topic: str,
    ) -> None:
        self._producer = producer
        self._topic = prediction_topic
        self._mapper = ResultMapper()

    async def publish(self, output: PredictionOutput) -> None:
        """Publish a prediction to the Kafka prediction-results topic."""
        message_key = f"{output.repo_full_name}#{output.pr_number}"

        try:
            payload = self._mapper.to_kafka_payload(output)
            await self._producer.send(
                topic=self._topic,
                value=payload,
                key=message_key,
            )
            kafka_messages_produced.labels(topic=self._topic).inc()
            logger.info(
                "Prediction published to Kafka",
                event_id=output.event_id,
                topic=self._topic,
                degraded=output.degraded,
            )
        except Exception:
            logger.exception(
                "Failed to publish prediction to Kafka",
                event_id=output.event_id,
            )
