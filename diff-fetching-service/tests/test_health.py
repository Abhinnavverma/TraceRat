"""Tests for the health and root endpoints."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Patch the consumer before importing the app to prevent real Kafka connections
with patch("app.main.DiffConsumer") as MockConsumer:
    mock_consumer = MagicMock()
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()
    mock_consumer.run = AsyncMock()
    mock_consumer._running = True
    mock_consumer.producer = MagicMock()
    mock_consumer.producer.is_connected = True
    MockConsumer.return_value = mock_consumer

    from app.main import app

    client = TestClient(app)


class TestHealthEndpoints:
    """Test liveness and readiness probes."""

    def test_health_returns_200(self):
        """Health endpoint should always return 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root_returns_service_info(self):
        """Root endpoint returns service identification."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "tracerat-diff-fetching-service"
        assert "version" in data
