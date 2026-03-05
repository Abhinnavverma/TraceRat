"""Tests for health and root endpoints."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


class TestHealthEndpoints:
    """Tests for health and root endpoints."""

    def test_health_returns_ok(self):
        """GET /health should return 200 with status ok."""
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root_returns_service_info(self):
        """GET / should return service name and version."""
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "tracerat-dependency-graph-service"
        assert data["version"] == "0.1.0"
        assert data["docs"] == "/docs"
