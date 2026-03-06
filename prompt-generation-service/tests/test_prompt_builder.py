"""Tests for the PromptBuilder service."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import LLMPromptPayload, PromptMessage
from app.services.prompt_builder import (
    SYSTEM_PROMPT,
    PromptBuilder,
    _build_user_prompt,
    _format_affected_components,
    _format_similar_prs,
)
from tests.conftest import (
    SAMPLE_DEGRADED_PREDICTION,
    SAMPLE_MINIMAL_PREDICTION,
    SAMPLE_PREDICTION,
)


class TestFormatAffectedComponents:
    """Tests for _format_affected_components helper."""

    def test_formats_components_as_table(self):
        components = SAMPLE_PREDICTION["affected_components"]
        result = _format_affected_components(components)

        assert "| Component | Impact Score | Relationship | Traffic |" in result
        assert "auth-service" in result
        assert "0.85" in result
        assert "direct" in result
        assert "high" in result

    def test_handles_empty_list(self):
        result = _format_affected_components([])
        assert result == "No affected components identified."

    def test_handles_none_traffic(self):
        components = [
            {"name": "svc", "impact_score": 0.5, "traffic_volume": None, "relationship": "direct"}
        ]
        result = _format_affected_components(components)
        assert "N/A" in result

    def test_handles_missing_fields(self):
        components = [{}]
        result = _format_affected_components(components)
        assert "unknown" in result
        assert "0.00" in result


class TestFormatSimilarPRs:
    """Tests for _format_similar_prs helper."""

    def test_formats_dict_entries(self):
        similar = SAMPLE_PREDICTION["similar_prs"]
        result = _format_similar_prs(similar)

        assert "acme/web-app#10" in result
        assert "Refactor auth token validation" in result
        assert "merged" in result
        assert "0.92" in result

    def test_formats_string_entries(self):
        similar = ["https://github.com/acme/web-app/pull/10"]
        result = _format_similar_prs(similar)
        assert "https://github.com/acme/web-app/pull/10" in result

    def test_handles_empty_list(self):
        result = _format_similar_prs([])
        assert result == "No historically similar PRs found."


class TestBuildUserPrompt:
    """Tests for _build_user_prompt helper."""

    def test_includes_pr_header(self):
        result = _build_user_prompt(SAMPLE_PREDICTION)
        assert "acme/web-app#42" in result
        assert "evt-001" in result

    def test_includes_risk_info(self):
        result = _build_user_prompt(SAMPLE_PREDICTION)
        assert "0.72" in result
        assert "HIGH" in result

    def test_includes_explanation(self):
        result = _build_user_prompt(SAMPLE_PREDICTION)
        assert "Large change set touching critical auth components." in result

    def test_includes_recommendations(self):
        result = _build_user_prompt(SAMPLE_PREDICTION)
        assert "Add integration tests for auth token flow" in result
        assert "Review session timeout handling" in result

    def test_omits_explanation_when_empty(self):
        result = _build_user_prompt(SAMPLE_DEGRADED_PREDICTION)
        assert "### Explanation" not in result

    def test_omits_recommendations_when_empty(self):
        result = _build_user_prompt(SAMPLE_DEGRADED_PREDICTION)
        assert "### Existing Recommendations" not in result

    def test_includes_report_instruction(self):
        result = _build_user_prompt(SAMPLE_PREDICTION)
        assert "blast-radius report" in result


class TestPromptBuilder:
    """Tests for the PromptBuilder class."""

    def setup_method(self):
        self.builder = PromptBuilder()

    def test_build_returns_llm_prompt_payload(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert isinstance(result, LLMPromptPayload)

    def test_build_contains_two_messages(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert len(result.messages) == 2

    def test_first_message_is_system(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert result.messages[0].role == "system"
        assert result.messages[0].content == SYSTEM_PROMPT

    def test_second_message_is_user(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert result.messages[1].role == "user"
        assert "acme/web-app#42" in result.messages[1].content

    def test_build_copies_event_metadata(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert result.event_id == "evt-001"
        assert result.repo_full_name == "acme/web-app"
        assert result.pr_number == 42
        assert result.installation_id == 99
        assert result.head_sha == "abc123"
        assert result.risk_score == 0.72
        assert result.risk_level == "HIGH"

    def test_build_sets_metadata(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert result.metadata["source_topic"] == "prediction-results"
        assert result.metadata["affected_component_count"] == 3
        assert result.metadata["similar_pr_count"] == 2
        assert result.metadata["degraded"] is False
        assert result.metadata["original_prediction"] == SAMPLE_PREDICTION

    def test_build_minimal_prediction(self):
        result = self.builder.build(SAMPLE_MINIMAL_PREDICTION)
        assert result.event_id == "evt-003"
        assert result.risk_score == 0.10
        assert result.risk_level == "LOW"
        assert len(result.messages) == 2
        assert result.metadata["affected_component_count"] == 0
        assert result.metadata["similar_pr_count"] == 0

    def test_build_has_timestamp(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        assert result.timestamp  # Non-empty ISO timestamp

    def test_messages_are_prompt_message_instances(self):
        result = self.builder.build(SAMPLE_PREDICTION)
        for msg in result.messages:
            assert isinstance(msg, PromptMessage)
