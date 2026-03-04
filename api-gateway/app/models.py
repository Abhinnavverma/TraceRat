"""Pydantic models for the API Gateway."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# --- GitHub Webhook Models ---


class PRAction(StrEnum):
    """Pull request actions we care about."""

    OPENED = "opened"
    SYNCHRONIZE = "synchronize"
    REOPENED = "reopened"
    CLOSED = "closed"


class PRUser(BaseModel):
    """GitHub user (minimal)."""

    login: str
    id: int


class PRHead(BaseModel):
    """PR head reference."""

    sha: str
    ref: str


class PRBase(BaseModel):
    """PR base reference."""

    sha: str
    ref: str


class PullRequest(BaseModel):
    """Pull request object from GitHub webhook payload."""

    number: int
    title: str
    state: str
    user: PRUser
    head: PRHead
    base: PRBase
    html_url: str
    diff_url: str
    created_at: str
    updated_at: str
    changed_files: int | None = None
    additions: int | None = None
    deletions: int | None = None


class Repository(BaseModel):
    """Repository object from GitHub webhook payload."""

    id: int
    full_name: str
    name: str
    owner: PRUser
    html_url: str
    default_branch: str = "main"


class Installation(BaseModel):
    """GitHub App installation reference."""

    id: int


class WebhookPayload(BaseModel):
    """GitHub pull_request webhook payload."""

    action: str
    number: int | None = None
    pull_request: PullRequest | None = None
    repository: Repository | None = None
    installation: Installation | None = None
    sender: PRUser | None = None


# --- Internal Kafka Event Models ---


class PREvent(BaseModel):
    """Internal representation of a PR event sent to Kafka.

    This is produced by the API gateway and consumed by downstream services.
    """

    event_id: str = Field(description="Unique event identifier (UUID)")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    repo_id: int = Field(description="GitHub repository ID")
    pr_number: int = Field(description="Pull request number")
    pr_title: str = Field(description="Pull request title")
    action: str = Field(description="PR action (opened, synchronize, reopened)")
    author: str = Field(description="PR author login")
    head_sha: str = Field(description="Head commit SHA")
    base_ref: str = Field(description="Base branch name")
    head_ref: str = Field(description="Head branch name")
    diff_url: str = Field(description="URL to fetch the diff")
    html_url: str = Field(description="Web URL of the PR")
    installation_id: int = Field(description="GitHub App installation ID")
    changed_files: int | None = Field(default=None, description="Number of changed files")
    additions: int | None = Field(default=None, description="Lines added")
    deletions: int | None = Field(default=None, description="Lines deleted")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Event timestamp (ISO 8601)",
    )


# --- Prediction Result Models ---


class AffectedComponent(BaseModel):
    """A component affected by the blast radius."""

    name: str
    impact_score: float = Field(ge=0.0, le=1.0)
    traffic_volume: str | None = None
    relationship: str = Field(
        description="Relationship type (direct, transitive, runtime)"
    )


class RiskLevel(StrEnum):
    """Risk classification levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PredictionResult(BaseModel):
    """Blast radius prediction result.

    Sent by the prediction service back to the API gateway
    for posting as a PR comment.
    """

    repo_full_name: str
    pr_number: int
    installation_id: int
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    explanation: str
    affected_components: list[AffectedComponent] = []
    traffic_impact: str | None = None
    similar_prs: list[str] = Field(
        default_factory=list,
        description="URLs of similar historical PRs",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Mitigation recommendations",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
    )
