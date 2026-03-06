"""Kafka consumer for the prompt generation service.

Subscribes to the ``prediction-results`` topic, filters degraded
predictions, builds LLM prompts, and publishes them to the
``llm-prompts`` topic.
"""

from typing import Any

from app.services.prompt_builder import PromptBuilder
from app.services.skip_filter import SkipFilter
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed

logger = get_logger("consumer")


class PromptGenerationConsumer(KafkaConsumerBase):
    """Consumes prediction results, builds prompts, and publishes to llm-prompts.

    Parameters
    ----------
    kafka_settings:
        Kafka connection/topic configuration.
    prompt_builder:
        Prompt construction engine.
    skip_filter:
        Filter to decide which predictions to skip.
    producer:
        Kafka producer for publishing LLM prompts.
    llm_prompts_topic:
        Destination topic for the generated prompts.
    """

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        prompt_builder: PromptBuilder | None = None,
        skip_filter: SkipFilter | None = None,
        producer: KafkaProducerClient | None = None,
        llm_prompts_topic: str | None = None,
    ) -> None:
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.prediction_results_topic],
            settings=settings,
            group_id="prompt-generation-service",
        )
        self._kafka_settings = settings
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._skip_filter = skip_filter or SkipFilter()
        self._producer = producer
        self._llm_prompts_topic = llm_prompts_topic or settings.llm_prompts_topic

    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single prediction-result message.

        1. Check skip filter (degraded predictions are dropped).
        2. Build LLM prompt payload.
        3. Publish to the ``llm-prompts`` topic.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="prompt-generation-service"
        ).inc()

        event_id = value.get("event_id", "unknown")
        logger.info("Prediction result received", event_id=event_id, topic=topic)

        # Step 1: Check skip filter
        if self._skip_filter.should_skip(value):
            return

        # Step 2: Build prompt
        try:
            payload = self._prompt_builder.build(value)
        except Exception:
            logger.exception(
                "Failed to build prompt",
                event_id=event_id,
            )
            return

        # Step 3: Publish to llm-prompts
        if self._producer is None:
            logger.warning(
                "Producer not set — prompt not published",
                event_id=event_id,
            )
            return

        try:
            await self._producer.send(
                topic=self._llm_prompts_topic,
                key=event_id,
                value=payload.model_dump(),
            )
            logger.info(
                "LLM prompt published",
                event_id=event_id,
                topic=self._llm_prompts_topic,
                message_count=len(payload.messages),
            )
        except Exception:
            logger.exception(
                "Failed to publish LLM prompt",
                event_id=event_id,
            )
