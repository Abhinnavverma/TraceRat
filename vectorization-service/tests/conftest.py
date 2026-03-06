"""Shared fixtures for vectorization-service tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --- Sample Data ---

SAMPLE_DIFF_CONTENT = {
    "event_id": "evt-001",
    "repo_full_name": "octocat/hello-world",
    "pr_number": 42,
    "head_sha": "abc123def456",
    "installation_id": 99999,
    "files": [
        {
            "filename": "src/auth/handler.py",
            "status": "modified",
            "additions": 30,
            "deletions": 5,
            "changes": 35,
            "patch": (
                "@@ -10,6 +10,8 @@\n"
                " class AuthHandler:\n"
                "     def validate_token(self, token):\n"
                "-        return self._check(token)\n"
                "+        result = self._check(token)\n"
                "+        self._audit_log(token, result)\n"
                "+        return result\n"
            ),
            "previous_filename": None,
            "sha": "aaa111",
            "contents_url": "https://api.github.com/repos/octocat/hello-world/contents/src/auth/handler.py",
        },
        {
            "filename": "src/auth/utils.py",
            "status": "added",
            "additions": 50,
            "deletions": 0,
            "changes": 50,
            "patch": (
                "@@ -0,0 +1,50 @@\n"
                "+def audit_log(token, result):\n"
                "+    '''Log authentication attempts.'''\n"
                "+    pass\n"
            ),
            "previous_filename": None,
            "sha": "bbb222",
            "contents_url": "https://api.github.com/repos/octocat/hello-world/contents/src/auth/utils.py",
        },
        {
            "filename": "docs/README.md",
            "status": "modified",
            "additions": 2,
            "deletions": 1,
            "changes": 3,
            "patch": None,
            "previous_filename": None,
            "sha": "ccc333",
            "contents_url": "https://api.github.com/repos/octocat/hello-world/contents/docs/README.md",
        },
    ],
    "timestamp": "2026-01-01T00:00:00",
}

SAMPLE_SEARCH_RESULTS = [
    {
        "id": "octocat/hello-world#10",
        "score": 0.92,
        "payload": {
            "repo_full_name": "octocat/hello-world",
            "pr_number": 10,
            "head_sha": "old111",
            "title": "Add auth logging",
            "files_changed": [
                "src/auth/handler.py",
                "src/auth/logger.py",
            ],
            "modules_affected": ["auth-service"],
            "total_additions": 45,
            "total_deletions": 3,
            "outcome": "merged",
            "timestamp": "2025-06-15T10:00:00",
        },
    },
    {
        "id": "octocat/hello-world#25",
        "score": 0.78,
        "payload": {
            "repo_full_name": "octocat/hello-world",
            "pr_number": 25,
            "head_sha": "old222",
            "title": "Fix auth token validation",
            "files_changed": [
                "src/auth/handler.py",
                "src/auth/validator.py",
            ],
            "modules_affected": ["auth-service"],
            "total_additions": 20,
            "total_deletions": 10,
            "outcome": "incident",
            "timestamp": "2025-09-20T14:30:00",
        },
    },
    {
        "id": "octocat/hello-world#30",
        "score": 0.65,
        "payload": {
            "repo_full_name": "octocat/hello-world",
            "pr_number": 30,
            "head_sha": "old333",
            "title": "Update session handling",
            "files_changed": [
                "src/session/manager.py",
            ],
            "modules_affected": ["session-service"],
            "total_additions": 15,
            "total_deletions": 5,
            "outcome": "merged",
            "timestamp": "2025-11-01T09:00:00",
        },
    },
]


# --- Fixtures ---


@pytest.fixture
def mock_embedder():
    """Mock embedding backend that returns deterministic vectors."""
    embedder = AsyncMock()
    embedder.embed.return_value = [0.1] * 384
    embedder.embed_batch.return_value = [[0.1] * 384]
    embedder.dimension.return_value = 384
    return embedder


@pytest.fixture
def mock_vector_store():
    """Mock Qdrant vector store."""
    store = AsyncMock()
    store.health_check.return_value = True
    store.upsert.return_value = None
    store.search.return_value = SAMPLE_SEARCH_RESULTS
    store.ensure_collection.return_value = None
    store.connect.return_value = None
    store.close.return_value = None
    return store


@pytest.fixture
def mock_producer():
    """Mock Kafka producer."""
    producer = AsyncMock()
    producer.is_connected = True
    producer.start.return_value = None
    producer.stop.return_value = None
    producer.send.return_value = None
    return producer
