"""Tests for the delta dependency graph calculator.

Tests BFS propagation with edge-weight multiplication, depth limits,
score pruning, and graceful handling of empty graphs.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.delta_calculator import DeltaCalculator

from tests.conftest import SAMPLE_GRAPH_NEIGHBORS, SAMPLE_SECOND_HOP_NEIGHBORS


class TestDeltaCalculatorExtraction:
    """Tests for changed node extraction logic."""

    def test_extract_changed_nodes_from_modules(self):
        """Should extract module names from affected_modules."""
        calc = DeltaCalculator(neo4j_client=AsyncMock())
        nodes = calc._extract_changed_nodes(
            changed_files=[],
            affected_modules=[
                {"module_name": "auth-service", "matched_files": ["a.py"]},
                {"module_name": "user-service", "matched_files": ["b.py"]},
            ],
        )
        assert nodes == {"auth-service", "user-service"}

    def test_extract_changed_nodes_from_files_fallback(self):
        """Should fall back to filenames when no modules provided."""
        calc = DeltaCalculator(neo4j_client=AsyncMock())
        nodes = calc._extract_changed_nodes(
            changed_files=[
                {"filename": "src/auth/handler.py"},
                {"filename": "src/auth/utils.py"},
            ],
            affected_modules=[],
        )
        assert "src/auth/handler.py" in nodes
        assert "src/auth/utils.py" in nodes

    def test_extract_changed_nodes_combines_both(self):
        """Should include both module names and filenames."""
        calc = DeltaCalculator(neo4j_client=AsyncMock())
        nodes = calc._extract_changed_nodes(
            changed_files=[{"filename": "src/auth/handler.py"}],
            affected_modules=[{"module_name": "auth-service", "matched_files": []}],
        )
        assert "auth-service" in nodes
        assert "src/auth/handler.py" in nodes

    def test_extract_changed_nodes_ignores_empty_names(self):
        """Should skip entries with empty module_name or filename."""
        calc = DeltaCalculator(neo4j_client=AsyncMock())
        nodes = calc._extract_changed_nodes(
            changed_files=[{"filename": ""}, {"filename": "valid.py"}],
            affected_modules=[{"module_name": "", "matched_files": []}],
        )
        assert "" not in nodes
        assert "valid.py" in nodes


class TestDeltaCalculatorBFS:
    """Tests for BFS propagation logic."""

    @pytest.mark.asyncio
    async def test_single_hop_propagation(self):
        """BFS should propagate risk to direct downstream neighbors."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(
            return_value=[{"name": "auth-service", "type": "service"}]
        )
        # First call: neighbors of auth-service
        # Subsequent calls: no further neighbors
        mock_neo4j.get_downstream_neighbors = AsyncMock(
            side_effect=[SAMPLE_GRAPH_NEIGHBORS, [], []]
        )

        calc = DeltaCalculator(neo4j_client=mock_neo4j, max_depth=1)
        result = await calc.compute_delta(
            changed_files=[{"filename": "src/auth/handler.py"}],
            affected_modules=[{"module_name": "auth-service", "matched_files": []}],
            repo_full_name="octocat/hello-world",
        )

        assert len(result) == 2
        names = {c.name for c in result}
        assert "session-manager" in names
        assert "login-gateway" in names

        # Verify risk scores are edge composite scores (score=1.0 * edge_composite)
        for comp in result:
            assert 0.0 < comp.risk_score <= 1.0
            assert comp.dependency_depth == 1

    @pytest.mark.asyncio
    async def test_multi_hop_propagation(self):
        """BFS should propagate through multiple hops with multiplied scores."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(
            return_value=[{"name": "auth-service", "type": "service"}]
        )

        # auth-service -> session-manager, login-gateway (hop 1)
        # session-manager -> redis-cache (hop 2)
        # login-gateway -> nothing (hop 2)
        # redis-cache -> nothing (hop 3, but we won't reach it with max_depth=2)
        async def mock_neighbors(node_name, max_depth=1):
            if node_name == "auth-service":
                return SAMPLE_GRAPH_NEIGHBORS
            if node_name == "session-manager":
                return SAMPLE_SECOND_HOP_NEIGHBORS
            return []

        mock_neo4j.get_downstream_neighbors = AsyncMock(side_effect=mock_neighbors)

        calc = DeltaCalculator(neo4j_client=mock_neo4j, max_depth=2)
        result = await calc.compute_delta(
            changed_files=[],
            affected_modules=[{"module_name": "auth-service", "matched_files": []}],
            repo_full_name="octocat/hello-world",
        )

        names = {c.name for c in result}
        assert "session-manager" in names
        assert "login-gateway" in names
        assert "redis-cache" in names

        # redis-cache should have lower score (multiplied through two edges)
        redis = next(c for c in result if c.name == "redis-cache")
        session = next(c for c in result if c.name == "session-manager")
        assert redis.risk_score < session.risk_score
        assert redis.dependency_depth == 2
        assert redis.path_from_change == ["auth-service", "session-manager", "redis-cache"]

    @pytest.mark.asyncio
    async def test_depth_limit_respected(self):
        """BFS should not traverse beyond max_depth."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(
            return_value=[{"name": "auth-service", "type": "service"}]
        )

        async def mock_neighbors(node_name, max_depth=1):
            if node_name == "auth-service":
                return SAMPLE_GRAPH_NEIGHBORS
            if node_name == "session-manager":
                return SAMPLE_SECOND_HOP_NEIGHBORS
            return []

        mock_neo4j.get_downstream_neighbors = AsyncMock(side_effect=mock_neighbors)

        # With max_depth=1, we should only see direct neighbors
        calc = DeltaCalculator(neo4j_client=mock_neo4j, max_depth=1)
        result = await calc.compute_delta(
            changed_files=[],
            affected_modules=[{"module_name": "auth-service", "matched_files": []}],
            repo_full_name="octocat/hello-world",
        )

        names = {c.name for c in result}
        assert "session-manager" in names
        assert "login-gateway" in names
        assert "redis-cache" not in names

    @pytest.mark.asyncio
    async def test_score_threshold_pruning(self):
        """BFS should prune branches where propagated score drops below threshold."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(
            return_value=[{"name": "start", "type": "service"}]
        )

        # Create neighbor with very low edge weights
        low_weight_neighbors = [
            {
                "source": "start",
                "target": "weak-dep",
                "depth": 1,
                "edge_call_frequency": 0.001,
                "edge_traffic_volume": 0.001,
                "edge_failure_propagation_rate": 0.001,
                "target_type": "service",
            }
        ]
        mock_neo4j.get_downstream_neighbors = AsyncMock(
            return_value=low_weight_neighbors
        )

        calc = DeltaCalculator(
            neo4j_client=mock_neo4j, max_depth=3, min_score_threshold=0.01
        )
        result = await calc.compute_delta(
            changed_files=[],
            affected_modules=[{"module_name": "start", "matched_files": []}],
            repo_full_name="test/repo",
        )

        # Score = 1.0 * (0.4*0.001 + 0.35*0.001 + 0.25*0.001) = 0.001 < 0.01
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_no_graph_nodes_returns_empty(self):
        """Should return empty list when no graph nodes match changed files."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(return_value=[])

        calc = DeltaCalculator(neo4j_client=mock_neo4j)
        result = await calc.compute_delta(
            changed_files=[{"filename": "unknown/file.py"}],
            affected_modules=[],
            repo_full_name="test/repo",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_no_changed_nodes_returns_empty(self):
        """Should return empty list when no changed nodes can be extracted."""
        mock_neo4j = AsyncMock()

        calc = DeltaCalculator(neo4j_client=mock_neo4j)
        result = await calc.compute_delta(
            changed_files=[],
            affected_modules=[],
            repo_full_name="test/repo",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_results_sorted_by_risk_descending(self):
        """Result should be sorted by risk_score in descending order."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(
            return_value=[{"name": "auth-service", "type": "service"}]
        )
        mock_neo4j.get_downstream_neighbors = AsyncMock(
            side_effect=[SAMPLE_GRAPH_NEIGHBORS, [], []]
        )

        calc = DeltaCalculator(neo4j_client=mock_neo4j, max_depth=1)
        result = await calc.compute_delta(
            changed_files=[],
            affected_modules=[{"module_name": "auth-service", "matched_files": []}],
            repo_full_name="test/repo",
        )

        scores = [c.risk_score for c in result]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_keeps_highest_score_path(self):
        """When a node is reachable via multiple paths, keep the highest score."""
        mock_neo4j = AsyncMock()
        mock_neo4j.find_nodes_by_filenames = AsyncMock(
            return_value=[
                {"name": "service-a", "type": "service"},
                {"name": "service-b", "type": "service"},
            ]
        )

        # Both service-a and service-b connect to shared-dep
        high_weight = [
            {
                "source": "service-a",
                "target": "shared-dep",
                "depth": 1,
                "edge_call_frequency": 0.9,
                "edge_traffic_volume": 0.9,
                "edge_failure_propagation_rate": 0.5,
                "target_type": "service",
            }
        ]
        low_weight = [
            {
                "source": "service-b",
                "target": "shared-dep",
                "depth": 1,
                "edge_call_frequency": 0.1,
                "edge_traffic_volume": 0.1,
                "edge_failure_propagation_rate": 0.1,
                "target_type": "service",
            }
        ]

        call_count = 0

        async def mock_neighbors(node_name, max_depth=1):
            nonlocal call_count
            call_count += 1
            if node_name == "service-a":
                return high_weight
            if node_name == "service-b":
                return low_weight
            return []

        mock_neo4j.get_downstream_neighbors = AsyncMock(side_effect=mock_neighbors)

        calc = DeltaCalculator(neo4j_client=mock_neo4j, max_depth=1)
        result = await calc.compute_delta(
            changed_files=[],
            affected_modules=[
                {"module_name": "service-a", "matched_files": []},
                {"module_name": "service-b", "matched_files": []},
            ],
            repo_full_name="test/repo",
        )

        assert len(result) == 1
        assert result[0].name == "shared-dep"
        # Should have the higher score from the service-a path
        expected_high = 0.4 * 0.9 + 0.35 * 0.9 + 0.25 * 0.5
        assert abs(result[0].risk_score - expected_high) < 0.001
