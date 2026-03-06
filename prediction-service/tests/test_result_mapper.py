"""Tests for the ResultMapper — schema conversion for api-gateway and Kafka."""


from app.models import AffectedComponentOutput, PredictionOutput, RiskLevel
from app.services.result_mapper import ResultMapper


def _make_output(**overrides) -> PredictionOutput:
    """Helper to build a PredictionOutput with sensible defaults."""
    defaults = {
        "event_id": "evt-1",
        "repo_full_name": "acme/web-app",
        "pr_number": 42,
        "installation_id": 99,
        "head_sha": "abc123",
        "risk_score": 0.72,
        "risk_level": RiskLevel.HIGH,
        "explanation": "Test explanation.",
        "affected_components": [
            AffectedComponentOutput(
                name="auth-service",
                impact_score=0.85,
                traffic_volume="90% coupling",
                relationship="direct",
            ),
            AffectedComponentOutput(
                name="login-gateway",
                impact_score=0.65,
                traffic_volume=None,
                relationship="transitive",
            ),
        ],
        "traffic_impact": "3 component(s) affected with aggregate risk 0.85",
        "similar_prs": [
            "https://github.com/acme/web-app/pull/10",
            "https://github.com/acme/web-app/pull/25",
        ],
        "recommendations": ["Add integration tests."],
        "degraded": False,
    }
    defaults.update(overrides)
    return PredictionOutput(**defaults)


class TestToApiGatewayPayload:
    """Tests for ResultMapper.to_api_gateway_payload()."""

    def test_maps_all_fields(self):
        output = _make_output()
        payload = ResultMapper.to_api_gateway_payload(output)

        assert payload["repo_full_name"] == "acme/web-app"
        assert payload["pr_number"] == 42
        assert payload["installation_id"] == 99
        assert payload["risk_score"] == 0.72
        assert payload["risk_level"] == "HIGH"
        assert payload["explanation"] == "Test explanation."
        assert payload["traffic_impact"] is not None
        assert len(payload["similar_prs"]) == 2
        assert len(payload["recommendations"]) == 1

    def test_maps_affected_components(self):
        output = _make_output()
        payload = ResultMapper.to_api_gateway_payload(output)

        comps = payload["affected_components"]
        assert len(comps) == 2
        assert comps[0]["name"] == "auth-service"
        assert comps[0]["impact_score"] == 0.85
        assert comps[0]["traffic_volume"] == "90% coupling"
        assert comps[0]["relationship"] == "direct"
        assert comps[1]["traffic_volume"] is None

    def test_empty_components(self):
        output = _make_output(affected_components=[])
        payload = ResultMapper.to_api_gateway_payload(output)
        assert payload["affected_components"] == []

    def test_no_degraded_field_in_gateway_payload(self):
        """The api-gateway PredictionResult schema doesn't have a degraded field."""
        output = _make_output(degraded=True)
        payload = ResultMapper.to_api_gateway_payload(output)
        assert "degraded" not in payload


class TestToKafkaPayload:
    """Tests for ResultMapper.to_kafka_payload()."""

    def test_includes_degraded_flag(self):
        output = _make_output(degraded=True)
        payload = ResultMapper.to_kafka_payload(output)
        assert payload["degraded"] is True

    def test_includes_all_fields(self):
        output = _make_output()
        payload = ResultMapper.to_kafka_payload(output)
        assert payload["event_id"] == "evt-1"
        assert payload["risk_score"] == 0.72
        assert payload["risk_level"] == "HIGH"
        assert len(payload["affected_components"]) == 2
        assert "timestamp" in payload
