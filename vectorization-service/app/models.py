"""Pydantic models for the Vectorization Service.

Defines the data structures for PR embeddings, similarity search
results, and the pr-context Kafka output message.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EmbeddingBackendType(StrEnum):
    """Supported embedding backend types."""

    SENTENCE_TRANSFORMER = "sentence-transformer"
    OPENAI = "openai"


class PROutcome(StrEnum):
    """Historical outcome of a pull request."""

    MERGED = "merged"
    CLOSED = "closed"
    INCIDENT = "incident"
    UNKNOWN = "unknown"


class SimilarPR(BaseModel):
    """A historically similar pull request found via vector similarity search."""

    repo_full_name: str = Field(description="Repository of the similar PR")
    pr_number: int = Field(description="PR number of the similar PR")
    similarity_score: float = Field(
        ge=0.0, le=1.0, description="Cosine similarity score (0–1)"
    )
    title: str = Field(default="", description="PR title")
    outcome: PROutcome = Field(
        default=PROutcome.UNKNOWN,
        description="Historical outcome of the PR",
    )
    overlapping_files: list[str] = Field(
        default_factory=list,
        description="Files changed in both this PR and the current PR",
    )
    blast_radius_score: float | None = Field(
        default=None,
        description="Blast radius score from the similar PR (if available)",
    )
    timestamp: str = Field(
        default="",
        description="Timestamp of the similar PR",
    )


class PRMetadata(BaseModel):
    """Metadata stored alongside the embedding vector in Qdrant.

    This payload is attached to each vector point so similarity
    search results can be enriched without additional lookups.
    """

    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    head_sha: str = Field(default="", description="Head commit SHA")
    title: str = Field(default="", description="PR title")
    files_changed: list[str] = Field(
        default_factory=list,
        description="List of filenames changed in the PR",
    )
    modules_affected: list[str] = Field(
        default_factory=list,
        description="Module/service names affected by the PR",
    )
    total_additions: int = Field(default=0, description="Total lines added")
    total_deletions: int = Field(default=0, description="Total lines deleted")
    outcome: str = Field(
        default=PROutcome.UNKNOWN,
        description="PR outcome (merged/closed/incident)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="When this PR was indexed",
    )


class PRContext(BaseModel):
    """Output message published to the pr-context Kafka topic.

    Contains the embedding result and similar historical PRs for
    consumption by the prediction-service.
    """

    event_id: str = Field(description="Original PR event ID from api-gateway")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    head_sha: str = Field(default="", description="Head commit SHA")

    similar_prs: list[SimilarPR] = Field(
        default_factory=list,
        description="Top-K similar historical PRs",
    )
    max_similarity_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Highest similarity score among results",
    )
    historical_incident_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of similar PRs with incident outcomes",
    )
    embedding_stored: bool = Field(
        default=False,
        description="Whether the embedding was successfully stored",
    )

    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Analysis timestamp (ISO 8601)",
    )


class BackfillRequest(BaseModel):
    """Request body for the historical PR backfill endpoint."""

    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    max_prs: int = Field(
        default=100, ge=1, le=500, description="Maximum PRs to backfill"
    )
    installation_id: int = Field(
        description="GitHub App installation ID for API access"
    )


class BackfillResponse(BaseModel):
    """Response from the historical PR backfill endpoint."""

    indexed: int = Field(description="Number of PRs successfully indexed")
    failed: int = Field(description="Number of PRs that failed to index")
    total: int = Field(description="Total PRs processed")
    repo_full_name: str = Field(description="Repository that was backfilled")
