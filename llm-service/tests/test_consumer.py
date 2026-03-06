"""Tests for the LLMServiceConsumer."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.consumer import LLMServiceConsumer
from tests.conftest import SAMPLE_PROMPT_PAYLOAD, SAMPLE_PROMPT_PAYLOAD_NO_MESSAGES


def _make_consumer(
    mock_llm_client: AsyncMock,
    mock_result_poster: AsyncMock,
) -> LLMServiceConsumer:
    """Build a consumer with mocked dependencies."""
    from shared.config import KafkaSettings

    return LLMServiceConsumer(
        kafka_settings=KafkaSettings(),
        llm_client=mock_llm_client,
        result_poster=mock_result_poster,
    )


class TestLLMServiceConsumer:
    """Tests for handle_message in LLMServiceConsumer."""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_llm_client, mock_result_poster):
        self.mock_llm = mock_llm_client
        self.mock_poster = mock_result_poster
        self.consumer = _make_consumer(mock_llm_client, mock_result_poster)

    async def test_calls_llm_and_posts_result(self):
        await self.consumer.handle_message(
            topic="llm-prompts",
            key="evt-001",
            value=SAMPLE_PROMPT_PAYLOAD,
        )
        self.mock_llm.call.assert_awaited_once()
        self.mock_poster.post.assert_awaited_once()

        # Verify poster received the LLM response
        call_args = self.mock_poster.post.call_args
        assert call_args.args[0] == SAMPLE_PROMPT_PAYLOAD
        assert call_args.args[1] is not None  # LLMResponse

    async def test_posts_fallback_when_no_messages(self):
        await self.consumer.handle_message(
            topic="llm-prompts",
            key="evt-002",
            value=SAMPLE_PROMPT_PAYLOAD_NO_MESSAGES,
        )
        self.mock_llm.call.assert_not_awaited()
        self.mock_poster.post.assert_awaited_once()

        # Fallback: llm_response should be None
        call_args = self.mock_poster.post.call_args
        assert call_args.args[1] is None

    async def test_posts_fallback_on_llm_failure(self):
        self.mock_llm.call.side_effect = RuntimeError("LLM down")

        await self.consumer.handle_message(
            topic="llm-prompts",
            key="evt-001",
            value=SAMPLE_PROMPT_PAYLOAD,
        )
        self.mock_poster.post.assert_awaited_once()

        # Fallback: llm_response should be None
        call_args = self.mock_poster.post.call_args
        assert call_args.args[1] is None

    async def test_handles_no_llm_client_gracefully(self):
        self.consumer._llm_client = None

        await self.consumer.handle_message(
            topic="llm-prompts",
            key="evt-001",
            value=SAMPLE_PROMPT_PAYLOAD,
        )
        # Should still post fallback
        self.mock_poster.post.assert_awaited_once()
        call_args = self.mock_poster.post.call_args
        assert call_args.args[1] is None

    async def test_handles_no_result_poster_gracefully(self):
        self.consumer._result_poster = None

        # Should not raise
        await self.consumer.handle_message(
            topic="llm-prompts",
            key="evt-001",
            value=SAMPLE_PROMPT_PAYLOAD,
        )

    async def test_llm_receives_correct_messages(self):
        await self.consumer.handle_message(
            topic="llm-prompts",
            key="evt-001",
            value=SAMPLE_PROMPT_PAYLOAD,
        )
        call_args = self.mock_llm.call.call_args
        messages = call_args.args[0]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
