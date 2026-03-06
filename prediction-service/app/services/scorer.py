"""Risk scoring engine for blast radius predictions.

Computes a weighted linear risk score from four normalized factors:
change size, dependency depth, traffic weight, and historical failure
probability.  Produces a :class:`PredictionOutput` with classification,
human-readable explanation, and mitigation recommendations.
"""

import math

from app.models import (
    AffectedComponentOutput,
    PredictionOutput,
    RiskLevel,
    SignalBundle,
)
from shared.logging import get_logger

logger = get_logger("scorer")


class RiskScorer:
    """Weighted linear risk scorer.

    Parameters
    ----------
    change_size_weight:
        Weight applied to the normalized change-size factor.
    depth_weight:
        Weight applied to the normalized dependency-depth factor.
    traffic_weight:
        Weight applied to the aggregate traffic/risk score.
    history_weight:
        Weight applied to the historical incident rate.
    """

    def __init__(
        self,
        change_size_weight: float = 0.30,
        depth_weight: float = 0.25,
        traffic_weight: float = 0.25,
        history_weight: float = 0.20,
    ) -> None:
        self._w_change = change_size_weight
        self._w_depth = depth_weight
        self._w_traffic = traffic_weight
        self._w_history = history_weight

    # ------------------------------------------------------------------ #
    # Factor extraction
    # ------------------------------------------------------------------ #

    @staticmethod
    def _change_size_factor(delta_graph: dict | None) -> float:
        """Normalize change size using log-scale of changed node count.

        ``min(1.0, log2(count + 1) / 5)`` maps ~31 changed nodes to 1.0.
        """
        if delta_graph is None:
            return 0.0
        count = len(delta_graph.get("changed_nodes", []))
        if count == 0:
            return 0.0
        return min(1.0, math.log2(count + 1) / 5.0)

    @staticmethod
    def _depth_factor(delta_graph: dict | None) -> float:
        """Normalize max BFS depth.  Depth 5+ maps to 1.0."""
        if delta_graph is None:
            return 0.0
        depth = delta_graph.get("max_depth_reached", 0)
        return min(1.0, depth / 5.0)

    @staticmethod
    def _traffic_factor(delta_graph: dict | None) -> float:
        """Use the pre-computed aggregate risk score (already 0-1)."""
        if delta_graph is None:
            return 0.0
        return float(delta_graph.get("aggregate_risk_score", 0.0))

    @staticmethod
    def _history_factor(pr_context: dict | None) -> float:
        """Use the historical incident rate (already 0-1)."""
        if pr_context is None:
            return 0.0
        return float(pr_context.get("historical_incident_rate", 0.0))

    # ------------------------------------------------------------------ #
    # Classification
    # ------------------------------------------------------------------ #

    @staticmethod
    def classify(score: float) -> RiskLevel:
        """Map a 0-1 risk score to a discrete risk level.

        Thresholds:
        - < 0.30 → LOW
        - < 0.60 → MEDIUM
        - < 0.85 → HIGH
        - ≥ 0.85 → CRITICAL
        """
        if score < 0.30:
            return RiskLevel.LOW
        if score < 0.60:
            return RiskLevel.MEDIUM
        if score < 0.85:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    # ------------------------------------------------------------------ #
    # Explanation & recommendations
    # ------------------------------------------------------------------ #

    def _generate_explanation(
        self,
        bundle: SignalBundle,
        factors: dict[str, float],
        score: float,
        level: RiskLevel,
    ) -> str:
        """Build a human-readable explanation highlighting dominant factors."""
        parts: list[str] = [f"Risk level: {level.value} (score {score:.2f})."]

        dg = bundle.delta_graph or {}
        ctx = bundle.pr_context or {}

        # Changed files
        changed = dg.get("changed_nodes", [])
        if changed:
            parts.append(f"{len(changed)} file(s) directly changed.")

        # Affected components
        affected_count = dg.get("total_affected_count", 0)
        if affected_count:
            depth = dg.get("max_depth_reached", 0)
            parts.append(
                f"{affected_count} downstream component(s) affected "
                f"up to depth {depth}."
            )

        # Traffic
        agg_risk = factors.get("traffic", 0.0)
        if agg_risk > 0.5:
            parts.append(
                "High traffic coupling detected — changes may propagate "
                "to critical production paths."
            )

        # Historical incidents
        incident_rate = factors.get("history", 0.0)
        if incident_rate > 0:
            similar_count = len(ctx.get("similar_prs", []))
            parts.append(
                f"Historical incident rate: {incident_rate:.0%} "
                f"across {similar_count} similar past PR(s)."
            )

        if bundle.degraded:
            missing = ", ".join(bundle.missing_signals)
            parts.append(f"⚠ Degraded prediction — missing signal(s): {missing}.")

        return " ".join(parts)

    @staticmethod
    def _generate_recommendations(
        bundle: SignalBundle,
        level: RiskLevel,
    ) -> list[str]:
        """Return contextual mitigation recommendations."""
        recs: list[str] = []
        dg = bundle.delta_graph or {}
        ctx = bundle.pr_context or {}

        if level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            recs.append(
                "Consider adding integration tests for the affected components."
            )

        affected = dg.get("affected_components", [])
        high_risk = [c for c in affected if c.get("risk_score", 0) > 0.7]
        if high_risk:
            names = ", ".join(c.get("name", "unknown") for c in high_risk[:5])
            recs.append(f"Review high-risk modules closely: {names}.")

        incident_rate = ctx.get("historical_incident_rate", 0.0)
        if incident_rate > 0.3:
            recs.append(
                "Similar past PRs have a significant incident rate — "
                "consider a phased rollout."
            )

        depth = dg.get("max_depth_reached", 0)
        if depth >= 3:
            recs.append(
                "Deep dependency chain detected — verify transitive "
                "impacts are covered by tests."
            )

        if level == RiskLevel.CRITICAL:
            recs.append("Strongly recommend a thorough code review before merge.")

        if not recs:
            recs.append("No specific recommendations — standard review process applies.")

        return recs

    # ------------------------------------------------------------------ #
    # Affected components mapping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _map_affected_components(
        delta_graph: dict | None,
    ) -> list[AffectedComponentOutput]:
        """Map delta-graph affected components to output format."""
        if delta_graph is None:
            return []

        components: list[AffectedComponentOutput] = []
        for comp in delta_graph.get("affected_components", []):
            depth = comp.get("dependency_depth", 1)
            relationship = "direct" if depth <= 1 else "transitive"
            traffic = comp.get("traffic_weight", 0.0)
            traffic_str = (
                f"{traffic:.0%} coupling" if traffic > 0 else None
            )
            components.append(
                AffectedComponentOutput(
                    name=comp.get("name", comp.get("node_id", "unknown")),
                    impact_score=min(1.0, max(0.0, comp.get("risk_score", 0.0))),
                    traffic_volume=traffic_str,
                    relationship=relationship,
                )
            )
        return components

    # ------------------------------------------------------------------ #
    # Core scoring
    # ------------------------------------------------------------------ #

    def score(self, bundle: SignalBundle) -> PredictionOutput:
        """Compute the blast radius prediction from a correlated signal bundle.

        When the bundle is degraded (missing one source), the weight of
        the missing factor is redistributed proportionally across the
        remaining factors.

        Returns
        -------
        PredictionOutput
            The complete prediction ready for publishing.
        """
        dg = bundle.delta_graph
        ctx = bundle.pr_context

        # Extract raw factors
        factors_raw = {
            "change_size": self._change_size_factor(dg),
            "depth": self._depth_factor(dg),
            "traffic": self._traffic_factor(dg),
            "history": self._history_factor(ctx),
        }

        weights = {
            "change_size": self._w_change,
            "depth": self._w_depth,
            "traffic": self._w_traffic,
            "history": self._w_history,
        }

        # Zero out weights for missing signals and redistribute
        if dg is None:
            for k in ("change_size", "depth", "traffic"):
                weights[k] = 0.0
        if ctx is None:
            weights["history"] = 0.0

        total_weight = sum(weights.values())
        if total_weight > 0:
            # Normalize weights so they sum to 1.0
            weights = {k: v / total_weight for k, v in weights.items()}

        # Weighted linear combination
        risk_score = sum(
            weights[k] * factors_raw[k] for k in factors_raw
        )
        risk_score = min(1.0, max(0.0, risk_score))

        level = self.classify(risk_score)

        # Build metadata from whichever signals are available
        repo = ""
        pr_number = 0
        installation_id = 0
        head_sha = ""

        if dg:
            repo = dg.get("repo_full_name", "")
            pr_number = dg.get("pr_number", 0)
            installation_id = dg.get("installation_id", 0)
            head_sha = dg.get("head_sha", "")
        elif ctx:
            repo = ctx.get("repo_full_name", "")
            pr_number = ctx.get("pr_number", 0)
            head_sha = ctx.get("head_sha", "")

        # Similar PR URLs
        similar_urls: list[str] = []
        if ctx:
            for s in ctx.get("similar_prs", []):
                s_repo = s.get("repo_full_name", repo)
                s_pr = s.get("pr_number", 0)
                if s_repo and s_pr:
                    similar_urls.append(
                        f"https://github.com/{s_repo}/pull/{s_pr}"
                    )

        # Traffic impact summary
        traffic_impact: str | None = None
        if dg:
            total_affected = dg.get("total_affected_count", 0)
            agg_risk = dg.get("aggregate_risk_score", 0.0)
            if total_affected > 0:
                traffic_impact = (
                    f"{total_affected} component(s) affected with "
                    f"aggregate risk {agg_risk:.2f}"
                )

        explanation = self._generate_explanation(bundle, factors_raw, risk_score, level)
        recommendations = self._generate_recommendations(bundle, level)
        components = self._map_affected_components(dg)

        output = PredictionOutput(
            event_id=bundle.event_id,
            repo_full_name=repo,
            pr_number=pr_number,
            installation_id=installation_id,
            head_sha=head_sha,
            risk_score=risk_score,
            risk_level=level,
            explanation=explanation,
            affected_components=components,
            traffic_impact=traffic_impact,
            similar_prs=similar_urls,
            recommendations=recommendations,
            degraded=bundle.degraded,
        )

        logger.info(
            "Prediction scored",
            event_id=bundle.event_id,
            risk_score=risk_score,
            risk_level=level.value,
            degraded=bundle.degraded,
        )
        return output
