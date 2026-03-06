"""Tests for the ResultPublisher — Kafka-only publishing."""

from unittest.mock import AsyncMock

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
        )
        output = _make_output()

        await publisher.publish(output)

        producer.send.assert_awaited_once()
        call_kwargs = producer.send.call_args.kwargs
        assert call_kwargs["topic"] == "prediction-results"
        assert call_kwargs["key"] == "acme/web-app#42"

    @pytest.mark.asyncio
    async def test_message_key_format(self):
        """Kafka message key should be 'repo#pr_number'."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
        )
        output = _make_output(repo_full_name="org/repo", pr_number=99)

        await publisher.publish(output)

        key = producer.send.call_args.kwargs["key"]
        assert key == "org/repo#99"

    @pytest.mark.asyncio
    async def test_kafka_failure_logged_not_raised(self):
        """If Kafka fails, the error should be logged but not raised."""
        producer = AsyncMock()
        producer.send = AsyncMock(side_effect=Exception("broker unavailable"))
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
        )
        output = _make_output()

        # Should not raise
        await publisher.publish(output)

        producer.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_payload_includes_degraded_flag(self):
        """The Kafka payload should include the degraded flag."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
        )
        output = _make_output(degraded=True)

        await publisher.publish(output)

        payload = producer.send.call_args.kwargs["value"]
        assert payload["degraded"] is True

    @pytest.mark.asyncio
    async def test_payload_contains_event_id(self):
        """The Kafka payload should contain the event_id."""
        producer = AsyncMock()
        publisher = ResultPublisher(
            producer=producer,
            prediction_topic="prediction-results",
        )
        output = _make_output(event_id="evt-abc")

        await publisher.publish(output)

        payload = producer.send.call_args.kwargs["value"]
        assert payload["event_id"] == "evt-abc"
