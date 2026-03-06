"""Tests for the LLM client abstraction layer."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import LLMResponse
from app.services.llm_client import (
    BaseLLMClient,
    GeminiClient,
    create_llm_client,
)


# ------------------------------------------------------------------ #
# GeminiClient._build_contents
# ------------------------------------------------------------------ #


class TestBuildContents:
    """Tests for GeminiClient._build_contents."""

    def _client(self) -> GeminiClient:
        return GeminiClient(api_key="test-key", model="gemini-2.0-flash")

    def test_system_and_user_messages(self):
        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        result = self._client()._build_contents(messages)
        assert "[System Instruction]" in result
        assert "Be helpful." in result
        assert "[User]" in result
        assert "Hello!" in result

    def test_user_only_messages(self):
        messages = [{"role": "user", "content": "What is 2+2?"}]
        result = self._client()._build_contents(messages)
        assert "[User]" in result
        assert "[System Instruction]" not in result

    def test_empty_messages_returns_empty_string(self):
        result = self._client()._build_contents([])
        assert result == ""


# ------------------------------------------------------------------ #
# GeminiClient.call — mocked SDK
# ------------------------------------------------------------------ #


def _mock_genai_response(text: str = "LLM output") -> MagicMock:
    """Create a mock Gemini GenerateContentResponse."""
    usage = MagicMock()
    usage.prompt_token_count = 100
    usage.candidates_token_count = 50
    usage.total_token_count = 150

    resp = MagicMock()
    resp.text = text
    resp.usage_metadata = usage
    return resp


class TestGeminiClientCall:
    """Tests for GeminiClient.call with a mocked google-genai SDK."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = GeminiClient(
            api_key="test-key",
            model="gemini-2.0-flash",
            max_retries=2,
            retry_base_delay=0.01,  # fast for tests
        )

    async def test_successful_call_returns_llm_response(self):
        mock_resp = _mock_genai_response("Generated text")

        mock_genai_client = MagicMock()
        mock_genai_client.aio.models.generate_content = AsyncMock(
            return_value=mock_resp
        )
        self.client._client = mock_genai_client

        messages = [{"role": "user", "content": "Hello"}]
        result = await self.client.call(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "Generated text"
        assert result.provider == "gemini"
        assert result.model == "gemini-2.0-flash"
        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 50
        assert result.latency_ms >= 0

    async def test_retries_on_failure_then_succeeds(self):
        mock_resp = _mock_genai_response("OK after retry")

        mock_genai_client = MagicMock()
        mock_genai_client.aio.models.generate_content = AsyncMock(
            side_effect=[RuntimeError("transient"), mock_resp]
        )
        self.client._client = mock_genai_client

        result = await self.client.call([{"role": "user", "content": "Hi"}])
        assert result.content == "OK after retry"
        assert mock_genai_client.aio.models.generate_content.call_count == 2

    async def test_raises_after_retries_exhausted(self):
        mock_genai_client = MagicMock()
        mock_genai_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("always fails")
        )
        self.client._client = mock_genai_client

        with pytest.raises(RuntimeError, match="always fails"):
            await self.client.call([{"role": "user", "content": "Hi"}])

        # 1 initial + 2 retries = 3 calls
        assert mock_genai_client.aio.models.generate_content.call_count == 3

    async def test_no_usage_metadata_returns_empty_usage(self):
        resp = MagicMock()
        resp.text = "No usage"
        resp.usage_metadata = None

        mock_genai_client = MagicMock()
        mock_genai_client.aio.models.generate_content = AsyncMock(
            return_value=resp
        )
        self.client._client = mock_genai_client

        result = await self.client.call([{"role": "user", "content": "Hi"}])
        assert result.usage == {}

    async def test_none_text_becomes_empty_string(self):
        resp = MagicMock()
        resp.text = None
        resp.usage_metadata = None

        mock_genai_client = MagicMock()
        mock_genai_client.aio.models.generate_content = AsyncMock(
            return_value=resp
        )
        self.client._client = mock_genai_client

        result = await self.client.call([{"role": "user", "content": "Hi"}])
        assert result.content == ""


# ------------------------------------------------------------------ #
# create_llm_client factory
# ------------------------------------------------------------------ #


class TestCreateLLMClient:
    """Tests for the create_llm_client factory function."""

    def test_creates_gemini_client(self):
        client = create_llm_client(
            provider="gemini", api_key="key", model="gemini-2.0-flash"
        )
        assert isinstance(client, GeminiClient)

    def test_raises_for_unsupported_provider(self):
        with pytest.raises(ValueError, match="Unsupported"):
            create_llm_client(provider="foo", api_key="key", model="m")

    def test_respects_retry_params(self):
        client = create_llm_client(
            provider="gemini",
            api_key="key",
            model="m",
            max_retries=5,
            retry_base_delay=2.0,
        )
        assert client._max_retries == 5
        assert client._retry_base_delay == 2.0
