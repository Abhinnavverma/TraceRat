"""LLM client abstraction with pluggable provider backends.

Provides a ``BaseLLMClient`` ABC and a concrete ``GeminiClient``
implementation using the ``google-genai`` SDK.  Includes retry
with exponential backoff.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod

from app.models import LLMResponse
from shared.logging import get_logger

logger = get_logger("llm_client")


class BaseLLMClient(ABC):
    """Abstract base class for LLM provider clients."""

    @abstractmethod
    async def call(self, messages: list[dict]) -> LLMResponse:
        """Send messages to the LLM and return the response.

        Parameters
        ----------
        messages:
            List of ``{"role": "system"|"user", "content": "..."}`` dicts.

        Returns
        -------
        LLMResponse
            Parsed response from the LLM provider.
        """


class GeminiClient(BaseLLMClient):
    """Google Gemini LLM client using the ``google-genai`` SDK.

    Parameters
    ----------
    api_key:
        Gemini API key.
    model:
        Model identifier (e.g. ``gemini-2.0-flash``).
    max_retries:
        Maximum number of retry attempts on failure.
    retry_base_delay:
        Base delay in seconds for exponential backoff.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._client = None

    def _ensure_client(self):
        """Lazy-initialise the Gemini client."""
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)

    def _build_contents(self, messages: list[dict]) -> str:
        """Convert system + user message pairs to a single prompt string.

        The Gemini ``generate_content`` API accepts a flat content string
        or a list of content parts. We join the messages into a single
        string with role labels so the model understands the division.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"[System Instruction]\n{content}")
            else:
                parts.append(f"[User]\n{content}")
        return "\n\n".join(parts)

    async def call(self, messages: list[dict]) -> LLMResponse:
        """Call Gemini with retry + exponential backoff.

        Returns
        -------
        LLMResponse
            Parsed response.

        Raises
        ------
        Exception
            If all retry attempts are exhausted.
        """
        self._ensure_client()
        contents = self._build_contents(messages)
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                start = time.perf_counter()
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000

                text = response.text or ""
                usage: dict = {}
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    um = response.usage_metadata
                    usage = {
                        "prompt_tokens": getattr(um, "prompt_token_count", 0),
                        "completion_tokens": getattr(
                            um, "candidates_token_count", 0
                        ),
                        "total_tokens": getattr(um, "total_token_count", 0),
                    }

                logger.info(
                    "Gemini call succeeded",
                    model=self._model,
                    attempt=attempt + 1,
                    latency_ms=round(elapsed_ms, 1),
                )

                return LLMResponse(
                    content=text,
                    model=self._model,
                    provider="gemini",
                    usage=usage,
                    latency_ms=elapsed_ms,
                )

            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = self._retry_base_delay * (2**attempt)
                    logger.warning(
                        "Gemini call failed, retrying",
                        attempt=attempt + 1,
                        max_retries=self._max_retries,
                        delay_s=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Gemini call failed — retries exhausted",
                        attempts=self._max_retries + 1,
                        error=str(exc),
                    )

        raise last_error  # type: ignore[misc]


def create_llm_client(
    provider: str,
    api_key: str,
    model: str,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
) -> BaseLLMClient:
    """Factory function to create the appropriate LLM client.

    Parameters
    ----------
    provider:
        LLM provider name (``gemini``).
    api_key:
        Provider API key.
    model:
        Model identifier.
    max_retries:
        Maximum retry attempts.
    retry_base_delay:
        Base delay for exponential backoff.

    Raises
    ------
    ValueError
        If the provider is not supported.
    """
    if provider == "gemini":
        return GeminiClient(
            api_key=api_key,
            model=model,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )
    raise ValueError(
        f"Unsupported LLM provider: {provider!r}. Supported: gemini"
    )
