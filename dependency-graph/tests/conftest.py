"""Shared fixtures for dependency-graph service tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --- Sample Data ---

SAMPLE_DIFF_METADATA = {
    "event_id": "evt-001",
    "repo_full_name": "octocat/hello-world",
    "repo_id": 12345,
    "pr_number": 42,
    "pr_title": "Add auth handler",
    "action": "opened",
    "author": "octocat",
    "head_sha": "abc123def456",
    "base_ref": "main",
    "head_ref": "feat/auth",
    "html_url": "https://github.com/octocat/hello-world/pull/42",
    "installation_id": 99999,
    "changed_files": [
        {
            "filename": "src/auth/handler.py",
            "status": "modified",
            "additions": 30,
            "deletions": 5,
            "changes": 35,
            "previous_filename": None,
        },
        {
            "filename": "src/auth/utils.py",
            "status": "added",
            "additions": 50,
            "deletions": 0,
            "changes": 50,
            "previous_filename": None,
        },
    ],
    "total_files_changed": 2,
    "total_additions": 80,
    "total_deletions": 5,
    "file_types": [{"extension": ".py", "count": 2}],
    "affected_modules": [
        {
            "module_name": "auth-service",
            "matched_files": ["src/auth/handler.py", "src/auth/utils.py"],
            "confidence": 1.0,
            "matching_rule": r"services/(?P<module>[^/]+)/",
        }
    ],
    "timestamp": "2026-01-01T00:00:00",
}

SAMPLE_TELEMETRY_EVENT = {
    "source_service": "api-gateway",
    "target_service": "auth-service",
    "call_frequency": 5000.0,
    "error_rate": 0.02,
    "latency_p99": 150.0,
    "traffic_volume": 500000.0,
    "timestamp": "2026-01-01T00:00:00",
}

# --- Graph Fixture Data ---

# Simulates Neo4j downstream neighbor query results
SAMPLE_GRAPH_NEIGHBORS = [
    {
        "source": "auth-service",
        "target": "session-manager",
        "depth": 1,
        "edge_call_frequency": 0.8,
        "edge_traffic_volume": 0.7,
        "edge_failure_propagation_rate": 0.3,
        "target_type": "service",
        "target_request_volume": 0.6,
        "target_error_rate": 0.01,
        "target_latency_sensitivity": 0.5,
        "target_production_criticality": 0.7,
    },
    {
        "source": "auth-service",
        "target": "login-gateway",
        "depth": 1,
        "edge_call_frequency": 0.9,
        "edge_traffic_volume": 0.85,
        "edge_failure_propagation_rate": 0.5,
        "target_type": "service",
        "target_request_volume": 0.9,
        "target_error_rate": 0.005,
        "target_latency_sensitivity": 0.8,
        "target_production_criticality": 0.9,
    },
]

SAMPLE_SECOND_HOP_NEIGHBORS = [
    {
        "source": "session-manager",
        "target": "redis-cache",
        "depth": 1,
        "edge_call_frequency": 0.6,
        "edge_traffic_volume": 0.5,
        "edge_failure_propagation_rate": 0.1,
        "target_type": "service",
        "target_request_volume": 0.4,
        "target_error_rate": 0.001,
        "target_latency_sensitivity": 0.3,
        "target_production_criticality": 0.4,
    },
]


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client with pre-configured responses."""
    client = AsyncMock()
    client.is_connected = True
    client.health_check = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.get_node = AsyncMock(return_value={"name": "auth-service", "type": "service"})
    client.find_nodes_by_filenames = AsyncMock(
        return_value=[{"name": "auth-service", "type": "service"}]
    )
    client.get_downstream_neighbors = AsyncMock(return_value=SAMPLE_GRAPH_NEIGHBORS)
    client.upsert_node_weight = AsyncMock()
    client.upsert_edge_weight = AsyncMock()
    return client


@pytest.fixture
def mock_producer():
    """Create a mock Kafka producer."""
    producer = AsyncMock()
    producer.is_connected = True
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.send = AsyncMock()
    return producer
