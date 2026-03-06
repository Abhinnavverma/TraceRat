"""Tests for the RiskScorer — weighted linear risk scoring engine."""

import math

import pytest
from app.models import PredictionOutput, RiskLevel, SignalBundle
from app.services.scorer import RiskScorer

from tests.conftest import SAMPLE_DELTA_GRAPH, SAMPLE_PR_CONTEXT


class TestScoreComputation:
    """Tests for RiskScorer.score() risk score computation."""

    def test_full_bundle_produces_score(self):
        """A complete bundle should produce a valid risk score 0-1."""
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert 0.0 <= output.risk_score <= 1.0
        assert isinstance(output, PredictionOutput)
        assert output.event_id == "evt-1"
        assert output.degraded is False

    def test_score_components_contribute(self):
        """All four factors should contribute to the final score."""
        scorer = RiskScorer(
            change_size_weight=0.25,
            depth_weight=0.25,
            traffic_weight=0.25,
            history_weight=0.25,
        )
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)

        # With non-zero values for all factors and equal weights, score > 0
        assert output.risk_score > 0.0

    def test_zero_change_size_does_not_collapse(self):
        """A PR with zero changed nodes should still produce a score from other factors."""
        scorer = RiskScorer()
        dg = {**SAMPLE_DELTA_GRAPH, "changed_nodes": []}
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=dg,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        # depth, traffic, and history still contribute
        assert output.risk_score > 0.0

    def test_all_max_values_produce_high_score(self):
        """Maximum values for all factors should produce a score near 1.0."""
        scorer = RiskScorer()
        dg = {
            **SAMPLE_DELTA_GRAPH,
            "changed_nodes": [f"file{i}.py" for i in range(50)],
            "max_depth_reached": 10,
            "aggregate_risk_score": 1.0,
        }
        ctx = {
            **SAMPLE_PR_CONTEXT,
            "historical_incident_rate": 1.0,
        }
        bundle = SignalBundle(event_id="evt-1", delta_graph=dg, pr_context=ctx)
        output = scorer.score(bundle)
        assert output.risk_score >= 0.85
        assert output.risk_level == RiskLevel.CRITICAL

    def test_all_zero_values_produce_low_score(self):
        """Zero values for every factor should produce score 0."""
        scorer = RiskScorer()
        dg = {
            **SAMPLE_DELTA_GRAPH,
            "changed_nodes": [],
            "max_depth_reached": 0,
            "aggregate_risk_score": 0.0,
        }
        ctx = {**SAMPLE_PR_CONTEXT, "historical_incident_rate": 0.0}
        bundle = SignalBundle(event_id="evt-1", delta_graph=dg, pr_context=ctx)
        output = scorer.score(bundle)
        assert output.risk_score == 0.0
        assert output.risk_level == RiskLevel.LOW


class TestDegradedPrediction:
    """Tests for degraded mode (missing one source)."""

    def test_missing_pr_context(self):
        """Missing pr-context should produce degraded output, history factor = 0."""
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=None,
            degraded=True,
            missing_signals=["pr-context"],
        )
        output = scorer.score(bundle)
        assert output.degraded is True
        assert output.risk_score > 0.0  # change/depth/traffic still contribute
        assert output.similar_prs == []

    def test_missing_delta_graph(self):
        """Missing delta-graph should produce degraded output, only history contributes."""
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=None,
            pr_context=SAMPLE_PR_CONTEXT,
            degraded=True,
            missing_signals=["delta-graph"],
        )
        output = scorer.score(bundle)
        assert output.degraded is True
        # Only history_factor contributes, weight redistributed to 1.0
        assert output.risk_score > 0.0
        assert output.affected_components == []

    def test_missing_both_produces_zero(self):
        """If somehow both are missing, score should be 0."""
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=None,
            pr_context=None,
            degraded=True,
            missing_signals=["delta-graph", "pr-context"],
        )
        output = scorer.score(bundle)
        assert output.risk_score == 0.0


class TestClassification:
    """Tests for RiskScorer.classify() thresholds."""

    @pytest.mark.parametrize(
        "score, expected",
        [
            (0.0, RiskLevel.LOW),
            (0.15, RiskLevel.LOW),
            (0.29, RiskLevel.LOW),
            (0.30, RiskLevel.MEDIUM),
            (0.45, RiskLevel.MEDIUM),
            (0.59, RiskLevel.MEDIUM),
            (0.60, RiskLevel.HIGH),
            (0.75, RiskLevel.HIGH),
            (0.84, RiskLevel.HIGH),
            (0.85, RiskLevel.CRITICAL),
            (0.95, RiskLevel.CRITICAL),
            (1.0, RiskLevel.CRITICAL),
        ],
    )
    def test_classification_thresholds(self, score, expected):
        assert RiskScorer.classify(score) == expected


class TestFactors:
    """Tests for individual factor extraction methods."""

    def test_change_size_factor_log_scale(self):
        """3 changed nodes: log2(4)/5 = 0.4."""
        factor = RiskScorer._change_size_factor(SAMPLE_DELTA_GRAPH)
        expected = min(1.0, math.log2(4) / 5.0)
        assert abs(factor - expected) < 1e-9

    def test_change_size_factor_none(self):
        assert RiskScorer._change_size_factor(None) == 0.0

    def test_depth_factor_normalized(self):
        """max_depth_reached=3 → 3/5 = 0.6."""
        factor = RiskScorer._depth_factor(SAMPLE_DELTA_GRAPH)
        assert abs(factor - 0.6) < 1e-9

    def test_depth_factor_none(self):
        assert RiskScorer._depth_factor(None) == 0.0

    def test_traffic_factor_uses_aggregate(self):
        """Should return aggregate_risk_score directly."""
        factor = RiskScorer._traffic_factor(SAMPLE_DELTA_GRAPH)
        assert factor == 0.85

    def test_traffic_factor_none(self):
        assert RiskScorer._traffic_factor(None) == 0.0

    def test_history_factor_uses_incident_rate(self):
        """Should return historical_incident_rate directly."""
        factor = RiskScorer._history_factor(SAMPLE_PR_CONTEXT)
        assert factor == 0.5

    def test_history_factor_none(self):
        assert RiskScorer._history_factor(None) == 0.0


class TestExplanationAndRecommendations:
    """Tests for explanation and recommendation generation."""

    def test_explanation_contains_risk_level(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert output.risk_level.value in output.explanation

    def test_explanation_mentions_degraded(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=None,
            degraded=True,
            missing_signals=["pr-context"],
        )
        output = scorer.score(bundle)
        assert "Degraded" in output.explanation

    def test_recommendations_not_empty(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert len(output.recommendations) > 0


class TestMetadataExtraction:
    """Tests for repo/PR metadata and similar PR URL extraction."""

    def test_extracts_repo_from_delta_graph(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert output.repo_full_name == "acme/web-app"
        assert output.pr_number == 42
        assert output.installation_id == 99

    def test_extracts_repo_from_context_when_no_delta(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=None,
            pr_context=SAMPLE_PR_CONTEXT,
            degraded=True,
            missing_signals=["delta-graph"],
        )
        output = scorer.score(bundle)
        assert output.repo_full_name == "acme/web-app"
        assert output.pr_number == 42

    def test_similar_pr_urls_generated(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert "https://github.com/acme/web-app/pull/10" in output.similar_prs
        assert "https://github.com/acme/web-app/pull/25" in output.similar_prs

    def test_traffic_impact_summary(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert output.traffic_impact is not None
        assert "3 component(s)" in output.traffic_impact

    def test_affected_components_mapped(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        assert len(output.affected_components) == 3
        names = [c.name for c in output.affected_components]
        assert "auth-service" in names
        assert "login-gateway" in names

    def test_direct_vs_transitive_relationship(self):
        scorer = RiskScorer()
        bundle = SignalBundle(
            event_id="evt-1",
            delta_graph=SAMPLE_DELTA_GRAPH,
            pr_context=SAMPLE_PR_CONTEXT,
        )
        output = scorer.score(bundle)
        comp_map = {c.name: c for c in output.affected_components}
        assert comp_map["auth-service"].relationship == "direct"
        assert comp_map["login-gateway"].relationship == "transitive"
