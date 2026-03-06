"""Tests for the PredictionConsumer — dual-topic Kafka consumer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.consumer import PredictionConsumer
from app.models import PredictionOutput, RiskLevel
from app.services.correlator import SignalCorrelator

from tests.conftest import SAMPLE_DELTA_GRAPH, SAMPLE_PR_CONTEXT


def _make_consumer(
    correlator=None, scorer=None, publisher=None
) -> PredictionConsumer:
    """Create a PredictionConsumer with mock/default dependencies."""
    from shared.config import KafkaSettings

    settings = KafkaSettings()
    return PredictionConsumer(
        kafka_settings=settings,
        correlator=correlator or SignalCorrelator(),
        scorer=scorer,
        publisher=publisher,
    )


class TestPredictionConsumer:
    """Tests for PredictionConsumer.handle_message()."""

    @pytest.mark.asyncio
    async def test_delta_graph_ingested(self):
        """A delta-graph message should be ingested into the correlator."""
        correlator = SignalCorrelator()
        consumer = _make_consumer(correlator=correlator)

        await consumer.handle_message(
            topic="delta-graph", key="acme/web-app#42", value=SAMPLE_DELTA_GRAPH
        )

        assert correlator.buffer_size == 1

    @pytest.mark.asyncio
    async def test_pr_context_ingested(self):
        """A pr-context message should be ingested into the correlator."""
        correlator = SignalCorrelator()
        consumer = _make_consumer(correlator=correlator)

        await consumer.handle_message(
            topic="pr-context", key="acme/web-app#42", value=SAMPLE_PR_CONTEXT
        )

        assert correlator.buffer_size == 1

    @pytest.mark.asyncio
    async def test_complete_bundle_triggers_scoring_and_publish(self):
        """When both signals arrive, scorer and publisher should be called."""
        correlator = SignalCorrelator()
        scorer = MagicMock()
        publisher = AsyncMock()

        mock_output = PredictionOutput(
            event_id="evt-001",
            repo_full_name="acme/web-app",
            pr_number=42,
            risk_score=0.7,
            risk_level=RiskLevel.HIGH,
        )
        scorer.score.return_value = mock_output

        consumer = _make_consumer(
            correlator=correlator, scorer=scorer, publisher=publisher
        )

        # First signal — no scoring
        await consumer.handle_message(
            topic="delta-graph", key="acme/web-app#42", value=SAMPLE_DELTA_GRAPH
        )
        scorer.score.assert_not_called()

        # Second signal — triggers scoring + publishing
        await consumer.handle_message(
            topic="pr-context", key="acme/web-app#42", value=SAMPLE_PR_CONTEXT
        )
        scorer.score.assert_called_once()
        publisher.publish.assert_awaited_once_with(mock_output)

    @pytest.mark.asyncio
    async def test_incomplete_bundle_does_not_trigger(self):
        """Only one signal should not trigger scoring."""
        scorer = MagicMock()
        publisher = AsyncMock()
        consumer = _make_consumer(scorer=scorer, publisher=publisher)

        await consumer.handle_message(
            topic="delta-graph", key="acme/web-app#42", value=SAMPLE_DELTA_GRAPH
        )

        scorer.score.assert_not_called()
        publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unexpected_topic_skipped(self):
        """Messages from unknown topics should be silently skipped."""
        correlator = SignalCorrelator()
        consumer = _make_consumer(correlator=correlator)

        await consumer.handle_message(
            topic="unknown-topic", key="key", value={"event_id": "evt-1"}
        )

        assert correlator.buffer_size == 0

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Errors during scoring should not crash the consumer."""
        correlator = SignalCorrelator()
        scorer = MagicMock()
        scorer.score.side_effect = Exception("scoring failed")
        publisher = AsyncMock()

        consumer = _make_consumer(
            correlator=correlator, scorer=scorer, publisher=publisher
        )

        # Ingest first signal
        await consumer.handle_message(
            topic="delta-graph", key="k", value=SAMPLE_DELTA_GRAPH
        )
        # Second signal triggers scoring which fails
        await consumer.handle_message(
            topic="pr-context", key="k", value=SAMPLE_PR_CONTEXT
        )

        # Should not raise — error is caught
        publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_publisher_logs_warning(self):
        """If publisher is None, scoring should still succeed without crash."""
        correlator = SignalCorrelator()
        scorer = MagicMock()
        scorer.score.return_value = PredictionOutput(
            event_id="evt-001",
            repo_full_name="acme/web-app",
            pr_number=42,
            risk_score=0.5,
            risk_level=RiskLevel.MEDIUM,
        )

        consumer = _make_consumer(
            correlator=correlator, scorer=scorer, publisher=None
        )

        await consumer.handle_message(
            topic="delta-graph", key="k", value=SAMPLE_DELTA_GRAPH
        )
        await consumer.handle_message(
            topic="pr-context", key="k", value=SAMPLE_PR_CONTEXT
        )

        scorer.score.assert_called_once()
