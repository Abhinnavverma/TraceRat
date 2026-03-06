"""Tests for health and root endpoints."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import health, root  # noqa: E402


def _test_app() -> FastAPI:
    """Build a lightweight app duplicating health/root handlers."""

    @asynccontextmanager
    async def noop_lifespan(a):
        yield

    ta = FastAPI(lifespan=noop_lifespan)
    ta.get("/health")(health)
    ta.get("/")(root)
    return ta


class TestHealthEndpoints:
    """Tests for /health and / endpoints."""

    def test_health_returns_ok(self):
        client = TestClient(_test_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_root_returns_service_info(self):
        client = TestClient(_test_app())
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "tracerat-llm-service"
        assert data["version"] == "0.1.0"
