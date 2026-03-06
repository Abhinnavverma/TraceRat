"""Pydantic models for the Prompt Generation Service.

Defines schemas for:
- LLM prompt messages (system + user pairs)
- LLM prompt payloads published to the ``llm-prompts`` Kafka topic
"""

from datetime import datetime

from pydantic import BaseModel, Field


class PromptMessage(BaseModel):
    """A single message in a system/user prompt pair."""

    role: str = Field(description="Message role: 'system' or 'user'")
    content: str = Field(description="Message content text")


class LLMPromptPayload(BaseModel):
    """Payload published to the ``llm-prompts`` Kafka topic.

    Contains the structured prompt ready for an LLM provider,
    plus metadata needed to route the response back to the PR.
    """

    event_id: str = Field(description="Original PR event ID")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    installation_id: int = Field(default=0, description="GitHub App installation ID")
    head_sha: str = Field(default="", description="Head commit SHA")

    risk_score: float = Field(
        ge=0.0, le=1.0, description="Risk score from prediction service"
    )
    risk_level: str = Field(description="Classified risk level (LOW/MEDIUM/HIGH/CRITICAL)")

    messages: list[PromptMessage] = Field(
        description="Ordered list of prompt messages (system + user)"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional metadata for the LLM service",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Prompt generation timestamp (ISO 8601)",
    )
