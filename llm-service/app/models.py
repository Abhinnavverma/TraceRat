"""Pydantic models for the LLM Service.

Defines schemas for:
- LLM API responses
"""

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Response from an LLM provider API call."""

    content: str = Field(description="Raw text content from the LLM")
    model: str = Field(description="Model identifier used for generation")
    provider: str = Field(description="Provider name (gemini, openai, etc.)")
    usage: dict = Field(
        default_factory=dict,
        description="Token usage statistics (prompt_tokens, completion_tokens, etc.)",
    )
    latency_ms: float = Field(
        ge=0.0, description="Round-trip latency in milliseconds"
    )
