"""Shared fixtures and sample data for llm-service tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Ensure shared and app modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ------------------------------------------------------------------ #
# Sample LLM-prompts payload (mirrors LLMPromptPayload)
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
    ],
    "recommendations": [
        "Add integration tests for auth token flow",
    ],
    "degraded": False,
    "timestamp": "2026-03-06T12:00:00",
}

SAMPLE_PROMPT_PAYLOAD: dict = {
    "event_id": "evt-001",
    "repo_full_name": "acme/web-app",
    "pr_number": 42,
    "installation_id": 99,
    "risk_score": 0.72,
    "risk_level": "HIGH",
    "messages": [
        {
            "role": "system",
            "content": "You are a blast-radius analyst for GitHub PRs.",
        },
        {
            "role": "user",
            "content": "Analyse PR #42 on acme/web-app with risk_score=0.72.",
        },
    ],
    "metadata": {
        "source_topic": "prediction-results",
        "affected_component_count": 2,
        "similar_pr_count": 1,
        "original_prediction": SAMPLE_PREDICTION,
    },
    "timestamp": "2026-03-06T12:00:00",
}

SAMPLE_PROMPT_PAYLOAD_NO_MESSAGES: dict = {
    "event_id": "evt-002",
    "repo_full_name": "acme/web-app",
    "pr_number": 43,
    "messages": [],
    "metadata": {
        "original_prediction": SAMPLE_PREDICTION,
    },
}


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_llm_client():
    """Mock LLM client that returns a canned LLMResponse."""
    from app.models import LLMResponse

    client = AsyncMock()
    client.call = AsyncMock(
        return_value=LLMResponse(
            content="## Blast Radius Analysis\n\nHigh risk detected.",
            model="gemini-2.0-flash",
            provider="gemini",
            usage={
                "prompt_tokens": 150,
                "completion_tokens": 80,
                "total_tokens": 230,
            },
            latency_ms=420.5,
        )
    )
    return client


@pytest.fixture
def mock_result_poster():
    """Mock ResultPoster."""
    poster = AsyncMock()
    poster.post = AsyncMock(return_value=True)
    return poster
