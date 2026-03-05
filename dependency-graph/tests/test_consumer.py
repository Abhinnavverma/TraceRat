"""Tests for the dependency graph Kafka consumer.

Tests end-to-end message processing: diff-metadata in → delta-graph out.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.consumer import DependencyGraphConsumer
from app.models import AffectedComponent, NodeType

from shared.config import KafkaSettings
from tests.conftest import SAMPLE_DIFF_METADATA


class TestDependencyGraphConsumer:
    """Tests for the diff-metadata consumer."""

    def _make_consumer(
        self, mock_neo4j, mock_producer, mock_delta_calculator=None
    ):
        """Create a consumer with injected dependencies."""
        settings = KafkaSettings(
            bootstrap_servers="localhost:9092",
            diff_metadata_topic="diff-metadata",
            delta_graph_topic="delta-graph",
        )
        consumer = DependencyGraphConsumer(
            kafka_settings=settings,
            neo4j_client=mock_neo4j,
            delta_calculator=mock_delta_calculator,
            producer=mock_producer,
        )
        return consumer

    @pytest.mark.asyncio
    async def test_processes_diff_metadata_and_publishes_delta(
        self, mock_neo4j_client, mock_producer
    ):
        """Should compute delta graph and publish to delta-graph topic."""
        affected = [
            AffectedComponent(
                node_id="session-manager",
                node_type=NodeType.SERVICE,
                name="session-manager",
                risk_score=0.65,
                dependency_depth=1,
                traffic_weight=0.65,
                path_from_change=["auth-service", "session-manager"],
            )
        ]
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(return_value=affected)

        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_METADATA,
        )

        # Verify producer was called
        mock_producer.send.assert_awaited_once()
        call_kwargs = mock_producer.send.call_args.kwargs
        assert call_kwargs["topic"] == "delta-graph"
        assert call_kwargs["key"] == "octocat/hello-world#42"

        # Verify the published value
        published = call_kwargs["value"]
        assert published["event_id"] == "evt-001"
        assert published["repo_full_name"] == "octocat/hello-world"
        assert published["pr_number"] == 42
        assert published["total_affected_count"] == 1
        assert published["aggregate_risk_score"] == 0.65
        assert published["graph_available"] is True

    @pytest.mark.asyncio
    async def test_publishes_empty_result_on_calculator_error(
        self, mock_neo4j_client, mock_producer
    ):
        """Should publish empty result when delta computation fails."""
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(
            side_effect=Exception("Neo4j connection lost")
        )

        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_METADATA,
        )

        # Should still publish, but with empty affected components
        mock_producer.send.assert_awaited_once()
        published = mock_producer.send.call_args.kwargs["value"]
        assert published["affected_components"] == []
        assert published["graph_available"] is False
        assert published["aggregate_risk_score"] == 0.0

    @pytest.mark.asyncio
    async def test_changed_nodes_from_modules(
        self, mock_neo4j_client, mock_producer
    ):
        """Should populate changed_nodes from affected_modules."""
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(return_value=[])

        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_METADATA,
        )

        published = mock_producer.send.call_args.kwargs["value"]
        assert "auth-service" in published["changed_nodes"]

    @pytest.mark.asyncio
    async def test_changed_nodes_fallback_to_filenames(
        self, mock_neo4j_client, mock_producer
    ):
        """Should use filenames when no affected_modules provided."""
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(return_value=[])

        event = {**SAMPLE_DIFF_METADATA, "affected_modules": []}
        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="octocat/hello-world#42",
            value=event,
        )

        published = mock_producer.send.call_args.kwargs["value"]
        assert "src/auth/handler.py" in published["changed_nodes"]

    @pytest.mark.asyncio
    async def test_aggregate_risk_is_max_of_components(
        self, mock_neo4j_client, mock_producer
    ):
        """aggregate_risk_score should be the max of all component scores."""
        affected = [
            AffectedComponent(
                node_id="a", node_type=NodeType.SERVICE, name="a",
                risk_score=0.3, dependency_depth=1, traffic_weight=0.3,
            ),
            AffectedComponent(
                node_id="b", node_type=NodeType.SERVICE, name="b",
                risk_score=0.8, dependency_depth=1, traffic_weight=0.8,
            ),
            AffectedComponent(
                node_id="c", node_type=NodeType.SERVICE, name="c",
                risk_score=0.5, dependency_depth=2, traffic_weight=0.5,
            ),
        ]
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(return_value=affected)

        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="test/repo#1",
            value=SAMPLE_DIFF_METADATA,
        )

        published = mock_producer.send.call_args.kwargs["value"]
        assert published["aggregate_risk_score"] == 0.8
        assert published["total_affected_count"] == 3

    @pytest.mark.asyncio
    async def test_max_depth_reached(
        self, mock_neo4j_client, mock_producer
    ):
        """max_depth_reached should reflect the deepest affected component."""
        affected = [
            AffectedComponent(
                node_id="a", node_type=NodeType.SERVICE, name="a",
                risk_score=0.5, dependency_depth=1, traffic_weight=0.5,
            ),
            AffectedComponent(
                node_id="b", node_type=NodeType.MODULE, name="b",
                risk_score=0.3, dependency_depth=3, traffic_weight=0.3,
            ),
        ]
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(return_value=affected)

        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="test/repo#1",
            value=SAMPLE_DIFF_METADATA,
        )

        published = mock_producer.send.call_args.kwargs["value"]
        assert published["max_depth_reached"] == 3

    @pytest.mark.asyncio
    async def test_message_key_format(
        self, mock_neo4j_client, mock_producer
    ):
        """Published message key should be 'repo_full_name#pr_number'."""
        mock_calculator = AsyncMock()
        mock_calculator.compute_delta = AsyncMock(return_value=[])

        consumer = self._make_consumer(
            mock_neo4j_client, mock_producer, mock_calculator
        )

        await consumer.handle_message(
            topic="diff-metadata",
            key="octocat/hello-world#42",
            value=SAMPLE_DIFF_METADATA,
        )

        call_kwargs = mock_producer.send.call_args.kwargs
        assert call_kwargs["key"] == "octocat/hello-world#42"
