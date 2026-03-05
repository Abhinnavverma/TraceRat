"""Tests for Neo4j client service."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import EdgeWeight, NodeWeight
from app.services.neo4j_client import Neo4jClient


def _make_mock_driver(mock_session):
    """Create a mock neo4j AsyncDriver whose session() returns an async CM.

    neo4j's driver.session() is a *regular* method returning an
    AsyncSession (async context manager), NOT a coroutine.  AsyncMock
    would incorrectly make session() awaitable, so we use MagicMock.
    """
    mock_driver = AsyncMock()  # verify_connectivity, close are async

    @asynccontextmanager
    async def _session_cm(**kwargs):
        yield mock_session

    mock_driver.session = MagicMock(side_effect=lambda **kw: _session_cm(**kw))
    return mock_driver


class TestNeo4jClientLifecycle:
    """Tests for connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_creates_driver(self):
        """connect() should create an async driver and verify connectivity."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_driver = AsyncMock()
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            mock_gdb.driver.assert_called_once()
            mock_driver.verify_connectivity.assert_awaited_once()
            assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_close_cleans_up_driver(self):
        """close() should close the driver and reset state."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_driver = AsyncMock()
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()
            await client.close()

            mock_driver.close.assert_awaited_once()
            assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_false_when_not_started(self):
        """is_connected should return False before connect()."""
        client = Neo4jClient()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_connected(self):
        """health_check() should return True when driver is connected."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_driver = AsyncMock()
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            result = await client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_connected(self):
        """health_check() should return False when driver is None."""
        client = Neo4jClient()
        result = await client.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_error(self):
        """health_check() should return False when connectivity check fails."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_driver = AsyncMock()
            mock_driver.verify_connectivity = AsyncMock(
                side_effect=[None, Exception("Connection lost")]
            )
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            result = await client.health_check()
            assert result is False


class TestNeo4jClientNodeOperations:
    """Tests for node query and upsert operations."""

    @pytest.mark.asyncio
    async def test_get_node_returns_properties(self):
        """get_node() should return node properties dict."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_session = AsyncMock()
            mock_record = MagicMock()
            mock_record.__getitem__ = MagicMock(
                return_value={"name": "auth-service", "type": "service"}
            )
            mock_result = AsyncMock()
            mock_result.single = AsyncMock(return_value=mock_record)
            mock_session.run = AsyncMock(return_value=mock_result)

            mock_driver = _make_mock_driver(mock_session)
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()
            node = await client.get_node("auth-service")

            assert node is not None
            assert node["name"] == "auth-service"
            assert node["type"] == "service"

    @pytest.mark.asyncio
    async def test_get_node_returns_none_when_not_found(self):
        """get_node() should return None for non-existent nodes."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single = AsyncMock(return_value=None)
            mock_session.run = AsyncMock(return_value=mock_result)

            mock_driver = _make_mock_driver(mock_session)
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()
            node = await client.get_node("nonexistent")

            assert node is None

    @pytest.mark.asyncio
    async def test_get_node_raises_when_not_connected(self):
        """get_node() should raise RuntimeError if not connected."""
        client = Neo4jClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_node("test")

    @pytest.mark.asyncio
    async def test_upsert_node_weight_calls_session_run(self):
        """upsert_node_weight() should execute a MERGE query."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_session = AsyncMock()
            mock_session.run = AsyncMock()

            mock_driver = _make_mock_driver(mock_session)
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            weight = NodeWeight(
                request_volume=0.8,
                error_rate=0.02,
                latency_sensitivity=0.5,
                production_criticality=0.7,
            )
            await client.upsert_node_weight("auth-service", "service", weight)

            mock_session.run.assert_awaited_once()
            call_kwargs = mock_session.run.call_args
            assert call_kwargs.kwargs["name"] == "auth-service"
            assert call_kwargs.kwargs["type"] == "service"
            assert call_kwargs.kwargs["request_volume"] == 0.8


class TestNeo4jClientEdgeOperations:
    """Tests for edge query and upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_edge_weight_calls_session_run(self):
        """upsert_edge_weight() should execute a MERGE query for edge."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_session = AsyncMock()
            mock_session.run = AsyncMock()

            mock_driver = _make_mock_driver(mock_session)
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            weight = EdgeWeight(
                call_frequency=0.9,
                traffic_volume=0.85,
                failure_propagation_rate=0.3,
            )
            await client.upsert_edge_weight("auth-service", "session-manager", weight)

            mock_session.run.assert_awaited_once()
            call_kwargs = mock_session.run.call_args
            assert call_kwargs.kwargs["source"] == "auth-service"
            assert call_kwargs.kwargs["target"] == "session-manager"
            assert call_kwargs.kwargs["call_frequency"] == 0.9

    @pytest.mark.asyncio
    async def test_find_nodes_by_filenames(self):
        """find_nodes_by_filenames() should match files and parent directories."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.data = AsyncMock(
                return_value=[{"node": {"name": "src/auth", "type": "module"}}]
            )
            mock_session.run = AsyncMock(return_value=mock_result)

            mock_driver = _make_mock_driver(mock_session)
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            nodes = await client.find_nodes_by_filenames(["src/auth/handler.py"])

            assert len(nodes) == 1
            assert nodes[0]["name"] == "src/auth"

            # Verify candidates include parent directories
            call_kwargs = mock_session.run.call_args
            candidates = call_kwargs.kwargs["candidates"]
            assert "src/auth/handler.py" in candidates
            assert "src/auth" in candidates
            assert "src" in candidates

    @pytest.mark.asyncio
    async def test_get_downstream_neighbors(self):
        """get_downstream_neighbors() should return neighbor data."""
        with patch("app.services.neo4j_client.AsyncGraphDatabase") as mock_gdb:
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.data = AsyncMock(
                return_value=[
                    {
                        "source": "auth-service",
                        "target": "session-manager",
                        "depth": 1,
                        "edge_call_frequency": 0.8,
                        "edge_traffic_volume": 0.7,
                        "edge_failure_propagation_rate": 0.3,
                        "target_type": "service",
                    }
                ]
            )
            mock_session.run = AsyncMock(return_value=mock_result)

            mock_driver = _make_mock_driver(mock_session)
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jClient()
            await client.connect()

            neighbors = await client.get_downstream_neighbors("auth-service", max_depth=2)

            assert len(neighbors) == 1
            assert neighbors[0]["target"] == "session-manager"
