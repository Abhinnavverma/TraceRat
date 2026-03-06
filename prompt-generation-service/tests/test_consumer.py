"""Tests for the PromptGenerationConsumer."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.consumer import PromptGenerationConsumer
from app.services.prompt_builder import PromptBuilder
from app.services.skip_filter import SkipFilter
from tests.conftest import SAMPLE_DEGRADED_PREDICTION, SAMPLE_PREDICTION


def _make_consumer(mock_producer: AsyncMock) -> PromptGenerationConsumer:
    """Build a consumer with mocked Kafka dependencies."""
    from shared.config import KafkaSettings

    settings = KafkaSettings()
    consumer = PromptGenerationConsumer(
        kafka_settings=settings,
        prompt_builder=PromptBuilder(),
        skip_filter=SkipFilter(),
        producer=mock_producer,
        llm_prompts_topic="llm-prompts",
    )
    return consumer


class TestPromptGenerationConsumer:
    """Tests for handle_message in PromptGenerationConsumer."""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_producer):
        self.mock_producer = mock_producer
        self.consumer = _make_consumer(mock_producer)

    async def test_publishes_prompt_for_normal_prediction(self):
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-001",
            value=SAMPLE_PREDICTION,
        )
        self.mock_producer.send.assert_awaited_once()
        call_kwargs = self.mock_producer.send.call_args
        assert call_kwargs.kwargs["topic"] == "llm-prompts"
        assert call_kwargs.kwargs["key"] == "evt-001"
        payload = call_kwargs.kwargs["value"]
        assert payload["event_id"] == "evt-001"
        assert len(payload["messages"]) == 2

    async def test_skips_degraded_prediction(self):
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-002",
            value=SAMPLE_DEGRADED_PREDICTION,
        )
        self.mock_producer.send.assert_not_awaited()

    async def test_handles_build_error_gracefully(self):
        # Inject a builder that raises
        self.consumer._prompt_builder = type(
            "BadBuilder", (), {"build": lambda self, p: (_ for _ in ()).throw(ValueError("boom"))}
        )()
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-001",
            value=SAMPLE_PREDICTION,
        )
        self.mock_producer.send.assert_not_awaited()

    async def test_handles_publish_error_gracefully(self):
        self.mock_producer.send.side_effect = RuntimeError("kafka down")
        # Should not raise
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-001",
            value=SAMPLE_PREDICTION,
        )
        self.mock_producer.send.assert_awaited_once()

    async def test_logs_warning_when_no_producer(self):
        self.consumer._producer = None
        # Should not raise
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-001",
            value=SAMPLE_PREDICTION,
        )

    async def test_payload_contains_correct_metadata(self):
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-001",
            value=SAMPLE_PREDICTION,
        )
        payload = self.mock_producer.send.call_args.kwargs["value"]
        assert payload["metadata"]["source_topic"] == "prediction-results"
        assert payload["metadata"]["affected_component_count"] == 3
        assert payload["metadata"]["similar_pr_count"] == 2

    async def test_payload_messages_have_roles(self):
        await self.consumer.handle_message(
            topic="prediction-results",
            key="evt-001",
            value=SAMPLE_PREDICTION,
        )
        payload = self.mock_producer.send.call_args.kwargs["value"]
        roles = [m["role"] for m in payload["messages"]]
        assert roles == ["system", "user"]
