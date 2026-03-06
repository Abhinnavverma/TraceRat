"""Shared fixtures and sample data for prediction-service tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure shared and app modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ------------------------------------------------------------------ #
# Sample delta-graph payload (mirrors DeltaGraphResult.model_dump())
# ------------------------------------------------------------------ #

SAMPLE_DELTA_GRAPH: dict = {
    "event_id": "evt-001",
    "repo_full_name": "acme/web-app",
    "pr_number": 42,
    "head_sha": "abc123",
    "installation_id": 99,
    "changed_nodes": ["src/auth/handler.py", "src/auth/utils.py", "src/config.py"],
    "affected_components": [
        {
            "node_id": "auth-service",
            "node_type": "service",
            "name": "auth-service",
            "risk_score": 0.85,
            "dependency_depth": 1,
            "traffic_weight": 0.9,
            "path_from_change": ["src/auth/handler.py", "auth-service"],
        },
        {
            "node_id": "login-gateway",
            "node_type": "module",
            "name": "login-gateway",
            "risk_score": 0.65,
            "dependency_depth": 2,
            "traffic_weight": 0.6,
            "path_from_change": [
                "src/auth/handler.py",
                "auth-service",
                "login-gateway",
            ],
        },
        {
            "node_id": "session-manager",
            "node_type": "module",
            "name": "session-manager",
            "risk_score": 0.40,
            "dependency_depth": 3,
            "traffic_weight": 0.3,
            "path_from_change": [
                "src/auth/handler.py",
                "auth-service",
                "login-gateway",
                "session-manager",
            ],
        },
    ],
    "max_depth_reached": 3,
    "total_affected_count": 3,
    "aggregate_risk_score": 0.85,
    "graph_available": True,
    "timestamp": "2026-03-06T12:00:00",
}


# ------------------------------------------------------------------ #
# Sample pr-context payload (mirrors PRContext output)
# ------------------------------------------------------------------ #

SAMPLE_PR_CONTEXT: dict = {
    "event_id": "evt-001",
    "repo_full_name": "acme/web-app",
    "pr_number": 42,
    "head_sha": "abc123",
    "similar_prs": [
        {
            "repo_full_name": "acme/web-app",
            "pr_number": 10,
            "similarity_score": 0.92,
            "title": "Refactor auth token validation",
            "outcome": "merged",
            "overlapping_files": ["src/auth/handler.py"],
            "blast_radius_score": 0.7,
            "timestamp": "2025-11-01T10:00:00",
        },
        {
            "repo_full_name": "acme/web-app",
            "pr_number": 25,
            "similarity_score": 0.78,
            "title": "Fix login session bug",
            "outcome": "incident",
            "overlapping_files": ["src/auth/handler.py", "src/config.py"],
            "blast_radius_score": 0.9,
            "timestamp": "2025-12-15T08:00:00",
        },
    ],
    "max_similarity_score": 0.92,
    "historical_incident_rate": 0.5,
    "embedding_stored": True,
    "timestamp": "2026-03-06T12:00:01",
}


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_producer():
    """Mock Kafka producer."""
    producer = AsyncMock()
    producer.is_connected = True
    producer.send = AsyncMock()
    return producer


@pytest.fixture
def mock_scorer():
    """Mock RiskScorer that returns a deterministic PredictionOutput."""
    from app.models import PredictionOutput, RiskLevel

    scorer = MagicMock()
    scorer.score.return_value = PredictionOutput(
        event_id="evt-001",
        repo_full_name="acme/web-app",
        pr_number=42,
        installation_id=99,
        head_sha="abc123",
        risk_score=0.72,
        risk_level=RiskLevel.HIGH,
        explanation="Test explanation.",
        degraded=False,
    )
    return scorer


@pytest.fixture
def mock_publisher():
    """Mock ResultPublisher."""
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    return publisher
