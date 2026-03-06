"""Tests for the LLMResponse model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import LLMResponse


class TestLLMResponse:
    """Validation tests for the LLMResponse Pydantic model."""

    def test_valid_response(self):
        resp = LLMResponse(
            content="Hello world",
            model="gemini-2.0-flash",
            provider="gemini",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            latency_ms=42.5,
        )
        assert resp.content == "Hello world"
        assert resp.model == "gemini-2.0-flash"
        assert resp.provider == "gemini"
        assert resp.latency_ms == 42.5

    def test_default_usage_is_empty_dict(self):
        resp = LLMResponse(
            content="test",
            model="m",
            provider="p",
            latency_ms=0.0,
        )
        assert resp.usage == {}

    def test_rejects_negative_latency(self):
        import pytest

        with pytest.raises(Exception):
            LLMResponse(
                content="test",
                model="m",
                provider="p",
                latency_ms=-1.0,
            )
