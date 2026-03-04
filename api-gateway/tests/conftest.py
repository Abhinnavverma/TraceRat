"""Pytest configuration and fixtures for api-gateway tests."""

import hashlib
import hmac
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import dependencies
from app.main import app

from shared.github_auth import GitHubAppAuth
from shared.kafka_producer import KafkaProducerClient

WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture
def mock_kafka_producer():
    """Create a mock Kafka producer."""
    producer = MagicMock(spec=KafkaProducerClient)
    producer.send_pr_event = AsyncMock()
    producer.send = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.is_connected = True
    return producer


@pytest.fixture
def mock_github_auth():
    """Create a mock GitHub auth that accepts our test secret."""
    auth = MagicMock(spec=GitHubAppAuth)

    def _verify(payload: bytes, signature: str) -> bool:
        expected = hmac.new(
            key=WEBHOOK_SECRET.encode("utf-8"),
            msg=payload,
            digestmod=hashlib.sha256,
        ).hexdigest()
        received = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, received)

    auth.verify_signature = _verify
    return auth


@pytest.fixture
def client(mock_kafka_producer, mock_github_auth):
    """Create a test client with mocked dependencies."""
    dependencies.set_kafka_producer(mock_kafka_producer)
    dependencies.set_github_auth(mock_github_auth)
    return TestClient(app, raise_server_exceptions=False)


def make_signature(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Generate a valid HMAC-SHA256 signature for a payload."""
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def sample_pr_webhook_payload(
    action: str = "opened",
    pr_number: int = 42,
    repo_name: str = "octocat/hello-world",
) -> dict:
    """Generate a sample GitHub PR webhook payload."""
    owner, repo = repo_name.split("/")
    return {
        "action": action,
        "number": pr_number,
        "pull_request": {
            "number": pr_number,
            "title": "Fix authentication bug",
            "state": "open",
            "user": {"login": "octocat", "id": 1},
            "head": {"sha": "abc123def456", "ref": "fix/auth-bug"},
            "base": {"sha": "main123", "ref": "main"},
            "html_url": f"https://github.com/{repo_name}/pull/{pr_number}",
            "diff_url": f"https://github.com/{repo_name}/pull/{pr_number}.diff",
            "created_at": "2026-03-04T10:00:00Z",
            "updated_at": "2026-03-04T10:00:00Z",
            "changed_files": 3,
            "additions": 50,
            "deletions": 10,
        },
        "repository": {
            "id": 123456,
            "full_name": repo_name,
            "name": repo,
            "owner": {"login": owner, "id": 1},
            "html_url": f"https://github.com/{repo_name}",
            "default_branch": "main",
        },
        "installation": {"id": 99999},
        "sender": {"login": "octocat", "id": 1},
    }
