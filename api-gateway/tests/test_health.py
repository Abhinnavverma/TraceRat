"""Tests for health and readiness endpoints."""


class TestHealthEndpoint:
    """Test liveness probe."""

    def test_health_returns_200(self, client):
        """Health endpoint should always return 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestReadinessEndpoint:
    """Test readiness probe."""

    def test_ready_when_kafka_connected(self, client):
        """Readiness should return 200 when Kafka is connected."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["checks"]["kafka"] is True

    def test_not_ready_when_kafka_disconnected(self, client, mock_kafka_producer):
        """Readiness should report not_ready when Kafka is disconnected."""
        mock_kafka_producer.is_connected = False
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["checks"]["kafka"] is False


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root_returns_service_info(self, client):
        """Root should return service name and version."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "tracerat-api-gateway"
        assert "version" in data
