"""Tests for the telemetry consumer."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.telemetry_consumer import (
    MAX_CALL_FREQUENCY,
    MAX_TRAFFIC_VOLUME,
    TelemetryConsumer,
    _normalize,
)

from shared.config import KafkaSettings
from tests.conftest import SAMPLE_TELEMETRY_EVENT


class TestNormalization:
    """Tests for the _normalize helper."""

    def test_normalize_mid_range(self):
        assert _normalize(500.0, 1000.0) == 0.5

    def test_normalize_at_max(self):
        assert _normalize(1000.0, 1000.0) == 1.0

    def test_normalize_exceeds_max_clamped(self):
        assert _normalize(1500.0, 1000.0) == 1.0

    def test_normalize_zero(self):
        assert _normalize(0.0, 1000.0) == 0.0

    def test_normalize_negative_clamped(self):
        assert _normalize(-10.0, 1000.0) == 0.0

    def test_normalize_zero_max(self):
        assert _normalize(100.0, 0.0) == 0.0


class TestTelemetryConsumer:
    """Tests for telemetry event processing."""

    def _make_consumer(self, mock_neo4j):
        """Create a telemetry consumer with mocked dependencies."""
        settings = KafkaSettings(
            bootstrap_servers="localhost:9092",
            telemetry_events_topic="telemetry-events",
        )
        consumer = TelemetryConsumer(
            kafka_settings=settings,
            neo4j_client=mock_neo4j,
        )
        # Set small batch size for testing
        consumer._batch_size = 1
        return consumer

    @pytest.mark.asyncio
    async def test_processes_valid_telemetry_event(self, mock_neo4j_client):
        """Should parse and upsert telemetry event weights to Neo4j."""
        consumer = self._make_consumer(mock_neo4j_client)

        await consumer.handle_message(
            topic="telemetry-events",
            key=None,
            value=SAMPLE_TELEMETRY_EVENT,
        )

        # With batch_size=1, it should flush immediately
        mock_neo4j_client.upsert_edge_weight.assert_awaited_once()
        mock_neo4j_client.upsert_node_weight.assert_awaited_once()

        # Verify edge weight call
        edge_call = mock_neo4j_client.upsert_edge_weight.call_args
        assert edge_call.kwargs["source"] == "api-gateway"
        assert edge_call.kwargs["target"] == "auth-service"

        # Verify node weight call
        node_call = mock_neo4j_client.upsert_node_weight.call_args
        assert node_call.kwargs["node_name"] == "auth-service"
        assert node_call.kwargs["node_type"] == "service"

    @pytest.mark.asyncio
    async def test_normalizes_values_correctly(self, mock_neo4j_client):
        """Should normalize raw telemetry to 0-1 scale."""
        consumer = self._make_consumer(mock_neo4j_client)

        await consumer.handle_message(
            topic="telemetry-events",
            key=None,
            value=SAMPLE_TELEMETRY_EVENT,
        )

        # Check edge weight normalization
        edge_call = mock_neo4j_client.upsert_edge_weight.call_args
        edge_weight = edge_call.kwargs["weight"]
        expected_freq = 5000.0 / MAX_CALL_FREQUENCY
        expected_traffic = 500000.0 / MAX_TRAFFIC_VOLUME
        assert abs(edge_weight.call_frequency - expected_freq) < 0.001
        assert abs(edge_weight.traffic_volume - expected_traffic) < 0.001
        assert edge_weight.failure_propagation_rate == 0.02

    @pytest.mark.asyncio
    async def test_invalid_event_does_not_crash(self, mock_neo4j_client):
        """Should log error and skip invalid events."""
        consumer = self._make_consumer(mock_neo4j_client)

        # Missing required fields
        await consumer.handle_message(
            topic="telemetry-events",
            key=None,
            value={"invalid": "data"},
        )

        # Should not have called Neo4j
        mock_neo4j_client.upsert_edge_weight.assert_not_awaited()
        mock_neo4j_client.upsert_node_weight.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batching_accumulates(self, mock_neo4j_client):
        """Should accumulate events until batch is full."""
        consumer = self._make_consumer(mock_neo4j_client)
        consumer._batch_size = 3  # Need 3 events to trigger flush

        # Send 2 events — should not flush yet
        await consumer.handle_message(
            topic="telemetry-events", key=None, value=SAMPLE_TELEMETRY_EVENT
        )
        await consumer.handle_message(
            topic="telemetry-events", key=None, value=SAMPLE_TELEMETRY_EVENT
        )

        mock_neo4j_client.upsert_edge_weight.assert_not_awaited()
        assert len(consumer._batch) == 2

        # Third event triggers flush
        await consumer.handle_message(
            topic="telemetry-events", key=None, value=SAMPLE_TELEMETRY_EVENT
        )

        assert mock_neo4j_client.upsert_edge_weight.await_count == 3
        assert len(consumer._batch) == 0

    @pytest.mark.asyncio
    async def test_flush_remaining_on_shutdown(self, mock_neo4j_client):
        """flush_remaining() should process any pending events."""
        consumer = self._make_consumer(mock_neo4j_client)
        consumer._batch_size = 100  # Won't auto-flush

        await consumer.handle_message(
            topic="telemetry-events", key=None, value=SAMPLE_TELEMETRY_EVENT
        )
        assert len(consumer._batch) == 1

        await consumer.flush_remaining()

        mock_neo4j_client.upsert_edge_weight.assert_awaited_once()
        assert len(consumer._batch) == 0

    @pytest.mark.asyncio
    async def test_neo4j_error_does_not_crash_batch(self, mock_neo4j_client):
        """Should continue processing batch even if one event fails."""
        mock_neo4j_client.upsert_edge_weight = AsyncMock(
            side_effect=[Exception("Neo4j error"), None]
        )
        mock_neo4j_client.upsert_node_weight = AsyncMock(
            side_effect=[None, None]
        )

        consumer = self._make_consumer(mock_neo4j_client)
        consumer._batch_size = 2

        await consumer.handle_message(
            topic="telemetry-events", key=None, value=SAMPLE_TELEMETRY_EVENT
        )
        await consumer.handle_message(
            topic="telemetry-events", key=None, value=SAMPLE_TELEMETRY_EVENT
        )

        # Both events should be attempted despite first failing
        assert mock_neo4j_client.upsert_edge_weight.await_count == 2
