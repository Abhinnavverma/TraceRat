"""LLM Service Kafka consumer.

Subscribes to the ``llm-prompts`` topic, invokes the LLM via the
pluggable client, and posts results to the api-gateway.
"""

from __future__ import annotations

from typing import Any

from app.models import LLMResponse
from app.services.llm_client import BaseLLMClient
from app.services.result_poster import ResultPoster
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed

logger = get_logger("consumer")


class LLMServiceConsumer(KafkaConsumerBase):
    """Consumes ``llm-prompts``, calls the LLM, and posts results.

    Parameters
    ----------
    kafka_settings:
        Kafka connection / topic configuration.
    llm_client:
        The pluggable LLM client implementation.
    result_poster:
        Posts enriched / fallback results to the api-gateway.
    """

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        llm_client: BaseLLMClient | None = None,
        result_poster: ResultPoster | None = None,
    ) -> None:
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.llm_prompts_topic],
            settings=settings,
            group_id="llm-service",
        )
        self._llm_client = llm_client
        self._result_poster = result_poster

    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single ``llm-prompts`` message.

        Flow
        ----
        1. Extract the message list from the payload.
        2. Call the LLM via the pluggable client.
        3. On success — post enriched result to api-gateway.
        4. On failure — post fallback (deterministic score) to api-gateway.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="llm-service"
        ).inc()

        event_id = value.get("event_id", "unknown")
        logger.info("LLM prompt received", event_id=event_id, topic=topic)

        # 1. Extract messages
        messages: list[dict] = value.get("messages", [])
        if not messages:
            logger.warning("Prompt payload has no messages", event_id=event_id)
            await self._post_fallback(value, event_id)
            return

        # 2. Call LLM
        llm_response: LLMResponse | None = None
        if self._llm_client is not None:
            try:
                llm_response = await self._llm_client.call(messages)
                logger.info(
                    "LLM call succeeded",
                    event_id=event_id,
                    model=llm_response.model,
                    latency_ms=round(llm_response.latency_ms, 1),
                )
            except Exception:
                logger.exception(
                    "LLM call failed — falling back to deterministic score",
                    event_id=event_id,
                )
        else:
            logger.warning(
                "No LLM client configured — using fallback",
                event_id=event_id,
            )

        # 3/4. Post result (enriched or fallback)
        if self._result_poster is not None:
            await self._result_poster.post(value, llm_response)
        else:
            logger.warning(
                "No result poster configured — result not sent",
                event_id=event_id,
            )

    async def _post_fallback(self, value: dict, event_id: str) -> None:
        """Post the deterministic fallback to the api-gateway."""
        if self._result_poster is not None:
            await self._result_poster.post(value, None)
        else:
            logger.warning(
                "No result poster configured — fallback not sent",
                event_id=event_id,
            )
