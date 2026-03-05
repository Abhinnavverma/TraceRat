"""Pydantic models for the Dependency Graph Service.

Defines schemas for:
- Telemetry ingestion events
- Node and edge weights in the weighted dependency graph
- Delta graph computation output (affected components)
- Kafka message output to the delta-graph topic
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# --- Telemetry Ingestion ---


class TelemetryEvent(BaseModel):
    """Incoming runtime telemetry event from the telemetry-events topic.

    Provides call-level metrics used to enrich edge and node weights
    in the dependency graph stored in Neo4j.
    """

    source_service: str = Field(description="Caller service/module name")
    target_service: str = Field(description="Callee service/module name")
    call_frequency: float = Field(
        default=0.0, description="Calls per second between source and target"
    )
    error_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Fraction of errored calls (0-1)"
    )
    latency_p99: float = Field(
        default=0.0, ge=0.0, description="99th percentile latency in ms"
    )
    traffic_volume: float = Field(
        default=0.0, ge=0.0, description="Requests per hour between source and target"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Telemetry measurement timestamp (ISO 8601)",
    )


# --- Graph Weight Models ---


class NodeWeight(BaseModel):
    """Weight properties stored on a dependency graph node in Neo4j.

    Composite score is calculated as a weighted combination of individual factors.
    All factors are normalized to 0-1 before combining.
    """

    request_volume: float = Field(
        default=0.0, ge=0.0, description="Normalized request volume (0-1)"
    )
    error_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Error rate fraction (0-1)"
    )
    latency_sensitivity: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Normalized latency sensitivity (0-1)"
    )
    production_criticality: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Production criticality score (0-1)"
    )

    @property
    def composite_score(self) -> float:
        """Weighted combination of all factors.

        Higher score = more critical node.
        Weights: volume=0.3, error=0.25, latency=0.2, criticality=0.25
        """
        return (
            0.30 * self.request_volume
            + 0.25 * self.error_rate
            + 0.20 * self.latency_sensitivity
            + 0.25 * self.production_criticality
        )


class EdgeWeight(BaseModel):
    """Weight properties stored on a dependency graph edge in Neo4j.

    Composite score reflects the runtime interaction strength between two nodes.
    """

    call_frequency: float = Field(
        default=0.0, ge=0.0, description="Normalized call frequency (0-1)"
    )
    traffic_volume: float = Field(
        default=0.0, ge=0.0, description="Normalized traffic volume (0-1)"
    )
    failure_propagation_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Rate at which failures in source propagate to target (0-1)",
    )

    @property
    def composite_score(self) -> float:
        """Weighted combination of all factors.

        Higher score = stronger runtime coupling.
        Weights: frequency=0.4, traffic=0.35, failure_prop=0.25
        """
        return (
            0.40 * self.call_frequency
            + 0.35 * self.traffic_volume
            + 0.25 * self.failure_propagation_rate
        )


# --- Node Type Classification ---


class NodeType(StrEnum):
    """Type of node in the dependency graph."""

    SERVICE = "service"
    MODULE = "module"
    PACKAGE = "package"
    FILE = "file"


# --- Delta Graph Output Models ---


class AffectedComponent(BaseModel):
    """A single component affected by a PR change.

    Contains the propagated risk score computed via BFS/DFS
    with edge-weight multiplication through the dependency graph.
    """

    node_id: str = Field(description="Unique node identifier in Neo4j")
    node_type: NodeType = Field(description="Type of graph node")
    name: str = Field(description="Human-readable component name")
    risk_score: float = Field(
        ge=0.0, le=1.0, description="Propagated risk score (0-1)"
    )
    dependency_depth: int = Field(
        ge=0, description="Number of hops from the changed node"
    )
    traffic_weight: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Edge weight (traffic coupling) from the path leading here",
    )
    path_from_change: list[str] = Field(
        default_factory=list,
        description="Ordered list of node names from the changed node to this node",
    )


class DeltaGraphResult(BaseModel):
    """Output message published to the delta-graph topic.

    Consumed by the prediction-service to aggregate risk signals
    and compute the final blast radius score.
    """

    event_id: str = Field(description="Original PR event ID from api-gateway")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    head_sha: str = Field(description="Head commit SHA")
    installation_id: int = Field(description="GitHub App installation ID")

    # Change context
    changed_nodes: list[str] = Field(
        default_factory=list,
        description="Names of directly changed files/modules",
    )

    # Delta computation results
    affected_components: list[AffectedComponent] = Field(
        default_factory=list,
        description="Downstream components affected by the change, sorted by risk_score desc",
    )
    max_depth_reached: int = Field(
        default=0, description="Maximum BFS depth reached during propagation"
    )
    total_affected_count: int = Field(
        default=0, description="Total number of affected components"
    )
    aggregate_risk_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Overall risk score for the PR (max of component scores)",
    )

    # Metadata
    graph_available: bool = Field(
        default=True,
        description="Whether a dependency graph existed for this repo in Neo4j",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Analysis timestamp (ISO 8601)",
    )
