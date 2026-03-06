"""Dual-path result publisher (Kafka + HTTP).

Publishes every prediction to:

1.  **Kafka ``prediction-results`` topic** — consumed by the
    prompt-generation-service.
2.  **HTTP ``POST`` to api-gateway ``/results``** — triggers the
    GitHub PR comment.

An HTTP failure is logged but does **not** prevent the Kafka publish
from succeeding — the two paths are independent.
"""

import httpx

from app.models import PredictionOutput
from app.services.result_mapper import ResultMapper
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger
from shared.metrics import kafka_messages_produced

logger = get_logger("result_publisher")


class ResultPublisher:
    """Publish prediction results to Kafka and the api-gateway.

    Parameters
    ----------
    producer:
        Shared Kafka producer instance.
    prediction_topic:
        Kafka topic name for prediction results.
    api_gateway_url:
        Full URL of the api-gateway ``/results`` endpoint.
    """

    def __init__(
        self,
        producer: KafkaProducerClient,
        prediction_topic: str,
        api_gateway_url: str,
    ) -> None:
        self._producer = producer
        self._topic = prediction_topic
        self._api_url = api_gateway_url
        self._mapper = ResultMapper()

    async def publish(self, output: PredictionOutput) -> None:
        """Publish a prediction to Kafka and POST to the api-gateway.

        Each path is handled independently — a failure in one does not
        block the other.
        """
        message_key = f"{output.repo_full_name}#{output.pr_number}"

        # 1. Kafka publish
        kafka_ok = await self._publish_kafka(output, message_key)

        # 2. HTTP POST to api-gateway
        http_ok = await self._post_to_gateway(output)

        logger.info(
            "Prediction published",
            event_id=output.event_id,
            kafka=kafka_ok,
            http=http_ok,
            degraded=output.degraded,
        )

    async def _publish_kafka(
        self, output: PredictionOutput, key: str
    ) -> bool:
        """Publish to the prediction-results Kafka topic."""
        try:
            payload = self._mapper.to_kafka_payload(output)
            await self._producer.send(
                topic=self._topic,
                value=payload,
                key=key,
            )
            kafka_messages_produced.labels(topic=self._topic).inc()
            return True
        except Exception:
            logger.exception(
                "Failed to publish prediction to Kafka",
                event_id=output.event_id,
            )
            return False

    async def _post_to_gateway(self, output: PredictionOutput) -> bool:
        """POST the prediction to the api-gateway /results endpoint."""
        try:
            payload = self._mapper.to_api_gateway_payload(output)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._api_url, json=payload)
                resp.raise_for_status()
            return True
        except Exception:
            logger.exception(
                "Failed to POST prediction to api-gateway",
                event_id=output.event_id,
                url=self._api_url,
            )
            return False
