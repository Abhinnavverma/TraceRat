"""Shared fixtures and sample data for prompt-generation-service tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Ensure shared and app modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ------------------------------------------------------------------ #
# Sample prediction-results payload (mirrors PredictionOutput)
# ------------------------------------------------------------------ #

SAMPLE_PREDICTION: dict = {
    "event_id": "evt-001",
    "repo_full_name": "acme/web-app",
    "pr_number": 42,
    "installation_id": 99,
    "head_sha": "abc123",
    "risk_score": 0.72,
    "risk_level": "HIGH",
    "explanation": "Large change set touching critical auth components.",
    "affected_components": [
        {
            "name": "auth-service",
            "impact_score": 0.85,
            "traffic_volume": "high",
            "relationship": "direct",
        },
        {
            "name": "login-gateway",
            "impact_score": 0.65,
            "traffic_volume": "medium",
            "relationship": "transitive",
        },
        {
            "name": "session-manager",
            "impact_score": 0.40,
            "traffic_volume": None,
            "relationship": "transitive",
        },
    ],
    "traffic_impact": "High — auth traffic path affected",
    "similar_prs": [
        {
            "repo_full_name": "acme/web-app",
            "pr_number": 10,
            "similarity_score": 0.92,
            "title": "Refactor auth token validation",
            "outcome": "merged",
        },
        {
            "repo_full_name": "acme/web-app",
            "pr_number": 25,
            "similarity_score": 0.78,
            "title": "Fix login session bug",
            "outcome": "incident",
        },
    ],
    "recommendations": [
        "Add integration tests for auth token flow",
        "Review session timeout handling",
    ],
    "degraded": False,
    "timestamp": "2026-03-06T12:00:00",
}

SAMPLE_DEGRADED_PREDICTION: dict = {
    "event_id": "evt-002",
    "repo_full_name": "acme/web-app",
    "pr_number": 43,
    "installation_id": 99,
    "head_sha": "def456",
    "risk_score": 0.35,
    "risk_level": "MEDIUM",
    "explanation": "",
    "affected_components": [],
    "traffic_impact": None,
    "similar_prs": [],
    "recommendations": [],
    "degraded": True,
    "missing_signals": ["pr-context"],
    "timestamp": "2026-03-06T12:00:05",
}

SAMPLE_MINIMAL_PREDICTION: dict = {
    "event_id": "evt-003",
    "repo_full_name": "acme/api",
    "pr_number": 7,
    "risk_score": 0.10,
    "risk_level": "LOW",
    "degraded": False,
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
