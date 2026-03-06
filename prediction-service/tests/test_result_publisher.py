"""Tests for the ResultPublisher — dual-path Kafka + HTTP publishing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models import PredictionOutput, RiskLevel
from app.services.result_publisher import ResultPublisher


def _make_output(**overrides) -> PredictionOutput:
    defaults = {
        "event_id": "evt-1",
        "repo_full_name": "acme/web-app",
        "pr_number": 42,
        "installation_id": 99,
        "risk_score": 0.72,
        "risk_level": RiskLevel.HIGH,
        "explanation": "Test explanation.",
        "degraded": False,
    }
    defaults.update(overrides)
    return PredictionOutput(**defaults)


class TestResultPublisher:
    """Tests for ResultPublisher.publish()."""

    @pytest.mark.asyncio
    async def test_publishes_to_kafka(self):
        """Should send the prediction to the Kafka topic."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
            api_gateway_url="http://fake:8000/results",
        )
        output = _make_output()

        with patch("app.services.result_publisher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await publisher.publish(output)

        producer.send.assert_awaited_once()
        call_kwargs = producer.send.call_args.kwargs
        assert call_kwargs["topic"] == "prediction-results"
        assert call_kwargs["key"] == "acme/web-app#42"

    @pytest.mark.asyncio
    async def test_posts_to_api_gateway(self):
        """Should POST the prediction to the api-gateway."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
            api_gateway_url="http://fake:8000/results",
        )
        output = _make_output()

        with patch("app.services.result_publisher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await publisher.publish(output)

        mock_client.post.assert_awaited_once()
        post_args = mock_client.post.call_args
        assert post_args.args[0] == "http://fake:8000/results"

    @pytest.mark.asyncio
    async def test_http_failure_does_not_block_kafka(self):
        """If the HTTP POST fails, Kafka publish should still succeed."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
            api_gateway_url="http://fake:8000/results",
        )
        output = _make_output()

        with patch("app.services.result_publisher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await publisher.publish(output)

        # Kafka should still have been called
        producer.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kafka_failure_does_not_block_http(self):
        """If Kafka fails, the HTTP POST should still proceed."""
        producer = AsyncMock()
        producer.send = AsyncMock(side_effect=Exception("broker unavailable"))
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
            api_gateway_url="http://fake:8000/results",
        )
        output = _make_output()

        with patch("app.services.result_publisher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await publisher.publish(output)

        # HTTP should still have been called
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_key_format(self):
        """Kafka message key should be 'repo#pr_number'."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
            api_gateway_url="http://fake:8000/results",
        )
        output = _make_output(repo_full_name="org/repo", pr_number=99)

        with patch("app.services.result_publisher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await publisher.publish(output)

        key = producer.send.call_args.kwargs["key"]
        assert key == "org/repo#99"
