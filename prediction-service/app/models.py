"""Pydantic models for the Prediction Service.

Defines schemas for:
- Risk classification levels
- Signal correlation bundles (joined delta-graph + pr-context)
- Prediction output published to Kafka and sent to api-gateway
"""

import time
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    """Risk classification levels for blast radius predictions."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalBundle(BaseModel):
    """Correlated payload joining delta-graph and pr-context signals.

    The correlator holds partial data in memory until both signals
    arrive (matched by ``event_id``).  If the TTL expires before both
    signals arrive, the bundle is emitted in *degraded* mode with
    ``degraded=True`` and the missing source listed in ``missing_signals``.
    """

    event_id: str = Field(description="Original PR event ID from api-gateway")
    delta_graph: dict | None = Field(
        default=None,
        description="Full DeltaGraphResult payload (None when missing)",
    )
    pr_context: dict | None = Field(
        default=None,
        description="Full PRContext payload (None when missing)",
    )
    degraded: bool = Field(
        default=False,
        description="True when emitted before both signals arrived",
    )
    missing_signals: list[str] = Field(
        default_factory=list,
        description="Names of signal sources that did not arrive before TTL",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix epoch when the first signal was ingested",
    )


class AffectedComponentOutput(BaseModel):
    """A component affected by the blast radius, mapped for the api-gateway."""

    name: str = Field(description="Component / module name")
    impact_score: float = Field(
        ge=0.0, le=1.0, description="Propagated risk score (0-1)"
    )
    traffic_volume: str | None = Field(
        default=None, description="Human-readable traffic descriptor"
    )
    relationship: str = Field(
        default="transitive",
        description="Relationship type (direct, transitive, runtime)",
    )


class PredictionOutput(BaseModel):
    """Internal prediction result before mapping to external formats.

    Published to the ``prediction-results`` Kafka topic and POST-ed
    to the api-gateway ``/results`` endpoint.
    """

    event_id: str = Field(description="Original PR event ID")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    installation_id: int = Field(default=0, description="GitHub App installation ID")
    head_sha: str = Field(default="", description="Head commit SHA")

    risk_score: float = Field(ge=0.0, le=1.0, description="Overall risk score (0-1)")
    risk_level: RiskLevel = Field(description="Classified risk level")
    explanation: str = Field(default="", description="Human-readable risk explanation")

    affected_components: list[AffectedComponentOutput] = Field(
        default_factory=list,
        description="Components impacted by the change",
    )
    traffic_impact: str | None = Field(
        default=None, description="Overall traffic impact summary"
    )
    similar_prs: list[str] = Field(
        default_factory=list,
        description="URLs of historically similar PRs",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Mitigation recommendations",
    )

    degraded: bool = Field(
        default=False,
        description="True when prediction was computed with partial signals",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Prediction timestamp (ISO 8601)",
    )
