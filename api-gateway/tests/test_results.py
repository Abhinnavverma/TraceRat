"""Tests for the results endpoint (PR comment posting)."""

from unittest.mock import AsyncMock, patch

from app.models import AffectedComponent, PredictionResult, RiskLevel
from app.routes.results import format_pr_comment


class TestFormatPRComment:
    """Test PR comment formatting."""

    def test_format_high_risk(self):
        """High risk result should produce a properly formatted comment."""
        result = PredictionResult(
            repo_full_name="octocat/hello-world",
            pr_number=42,
            installation_id=99999,
            risk_score=0.82,
            risk_level=RiskLevel.HIGH,
            explanation="Change affects auth token validator",
            affected_components=[
                AffectedComponent(
                    name="auth-service",
                    impact_score=0.9,
                    traffic_volume="2.3M req/hour",
                    relationship="direct",
                ),
                AffectedComponent(
                    name="login-gateway",
                    impact_score=0.7,
                    traffic_volume="1.8M req/hour",
                    relationship="transitive",
                ),
            ],
            traffic_impact="~2.3M requests/hour",
            recommendations=[
                "Add integration tests for token validation",
                "Consider staged rollout",
            ],
            similar_prs=["https://github.com/octocat/hello-world/pull/38"],
        )

        comment = format_pr_comment(result)

        assert "Blast Radius Analysis" in comment
        assert "0.82" in comment
        assert "HIGH" in comment
        assert "auth-service" in comment
        assert "login-gateway" in comment
        assert "2.3M requests/hour" in comment
        assert "Add integration tests" in comment
        assert "TraceRat" in comment

    def test_format_low_risk_minimal(self):
        """Low risk with no extras should still format correctly."""
        result = PredictionResult(
            repo_full_name="octocat/hello-world",
            pr_number=1,
            installation_id=99999,
            risk_score=0.12,
            risk_level=RiskLevel.LOW,
            explanation="Minor documentation change",
        )

        comment = format_pr_comment(result)

        assert "0.12" in comment
        assert "LOW" in comment
        assert "Minor documentation change" in comment


class TestResultsEndpoint:
    """Test the /results endpoint."""

    @patch("app.routes.results.GitHubClient")
    def test_post_results_success(self, mock_github_client, client):
        """Successful result should post a PR comment."""
        mock_instance = mock_github_client.return_value
        mock_instance.post_pr_comment = AsyncMock(
            return_value="https://github.com/octocat/hello-world/pull/42#issuecomment-1"
        )

        result_payload = {
            "repo_full_name": "octocat/hello-world",
            "pr_number": 42,
            "installation_id": 99999,
            "risk_score": 0.5,
            "risk_level": "MEDIUM",
            "explanation": "Moderate change",
        }

        response = client.post("/results", json=result_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "posted"
        assert data["risk_level"] == "MEDIUM"

    def test_post_results_invalid_repo(self, client):
        """Invalid repo_full_name should return 422."""
        result_payload = {
            "repo_full_name": "invalid-no-slash",
            "pr_number": 42,
            "installation_id": 99999,
            "risk_score": 0.5,
            "risk_level": "MEDIUM",
            "explanation": "Test",
        }

        response = client.post("/results", json=result_payload)
        assert response.status_code == 422
