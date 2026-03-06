"""Tests for the ResultPoster."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import LLMResponse
from app.services.result_poster import ResultPoster
from tests.conftest import SAMPLE_PROMPT_PAYLOAD


def _llm_response(content: str = "## Analysis\nHigh risk.") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="gemini-2.0-flash",
        provider="gemini",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        latency_ms=300.0,
    )


class TestBuildPayload:
    """Tests for ResultPoster._build_payload."""

    def _poster(self) -> ResultPoster:
        return ResultPoster(api_gateway_url="http://localhost:8000/results")

    def test_enriched_payload_uses_llm_content(self):
        payload = self._poster()._build_payload(
            SAMPLE_PROMPT_PAYLOAD, _llm_response("LLM explanation")
        )
        assert payload["explanation"] == "LLM explanation"
        assert payload["repo_full_name"] == "acme/web-app"
        assert payload["pr_number"] == 42
        assert payload["risk_score"] == 0.72

    def test_fallback_payload_uses_original_explanation(self):
        payload = self._poster()._build_payload(SAMPLE_PROMPT_PAYLOAD, None)
        assert (
            payload["explanation"]
            == "Large change set touching critical auth components."
        )

    def test_fallback_missing_explanation_uses_default(self):
        modified = {
            **SAMPLE_PROMPT_PAYLOAD,
            "metadata": {
                "original_prediction": {
                    "risk_score": 0.5,
                    "risk_level": "MEDIUM",
                    "affected_components": [],
                },
            },
        }
        payload = self._poster()._build_payload(modified, None)
        assert "unavailable" in payload["explanation"].lower()

    def test_affected_components_mapped_correctly(self):
        payload = self._poster()._build_payload(
            SAMPLE_PROMPT_PAYLOAD, _llm_response()
        )
        assert len(payload["affected_components"]) == 2
        first = payload["affected_components"][0]
        assert first["name"] == "auth-service"
        assert first["impact_score"] == 0.85

    def test_similar_prs_carried_through(self):
        payload = self._poster()._build_payload(
            SAMPLE_PROMPT_PAYLOAD, _llm_response()
        )
        assert len(payload["similar_prs"]) == 1
        assert payload["similar_prs"][0]["pr_number"] == 10


class TestPost:
    """Tests for ResultPoster.post HTTP call."""

    async def test_successful_post_returns_true(self):
        poster = ResultPoster(api_gateway_url="http://localhost:8000/results")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.result_poster.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await poster.post(SAMPLE_PROMPT_PAYLOAD, _llm_response())
            assert result is True
            mock_client.post.assert_awaited_once()

    async def test_failed_post_returns_false(self):
        poster = ResultPoster(api_gateway_url="http://localhost:8000/results")

        with patch("app.services.result_poster.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await poster.post(SAMPLE_PROMPT_PAYLOAD, _llm_response())
            assert result is False

    async def test_fallback_post_sends_without_llm_content(self):
        poster = ResultPoster(api_gateway_url="http://localhost:8000/results")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.result_poster.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await poster.post(SAMPLE_PROMPT_PAYLOAD, None)
            assert result is True

            posted_json = mock_client.post.call_args.kwargs["json"]
            assert (
                posted_json["explanation"]
                == "Large change set touching critical auth components."
            )
