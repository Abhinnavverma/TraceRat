"""Result poster — sends prediction results to the api-gateway.

On LLM success: posts the enriched result with the LLM-generated
explanation.  On LLM failure: falls back to the deterministic
prediction from ``metadata.original_prediction``.
"""

from __future__ import annotations

import httpx

from app.models import LLMResponse
from shared.logging import get_logger

logger = get_logger("result_poster")


class ResultPoster:
    """Posts prediction results to the api-gateway ``/results`` endpoint.

    Parameters
    ----------
    api_gateway_url:
        Full URL of the api-gateway ``/results`` endpoint.
    """

    def __init__(self, api_gateway_url: str) -> None:
        self._api_url = api_gateway_url

    def _build_payload(
        self,
        prompt_payload: dict,
        llm_response: LLMResponse | None,
    ) -> dict:
        """Build the ``PredictionResult`` dict for the api-gateway.

        Uses ``metadata.original_prediction`` for structured fields and
        overwrites ``explanation`` with the LLM text when available.
        """
        original = prompt_payload.get("metadata", {}).get(
            "original_prediction", {}
        )

        explanation: str
        if llm_response is not None:
            explanation = llm_response.content
        else:
            explanation = original.get(
                "explanation",
                "LLM analysis unavailable — showing deterministic score only.",
            )

        # Extract affected_components in api-gateway format
        raw_components = original.get("affected_components", [])
        components = [
            {
                "name": c.get("name", "unknown"),
                "impact_score": c.get("impact_score", 0.0),
                "traffic_volume": c.get("traffic_volume"),
                "relationship": c.get("relationship", "transitive"),
            }
            for c in raw_components
        ]

        return {
            "repo_full_name": prompt_payload.get(
                "repo_full_name", original.get("repo_full_name", "unknown")
            ),
            "pr_number": prompt_payload.get(
                "pr_number", original.get("pr_number", 0)
            ),
            "installation_id": prompt_payload.get(
                "installation_id", original.get("installation_id", 0)
            ),
            "risk_score": prompt_payload.get(
                "risk_score", original.get("risk_score", 0.0)
            ),
            "risk_level": prompt_payload.get(
                "risk_level", original.get("risk_level", "UNKNOWN")
            ),
            "explanation": explanation,
            "affected_components": components,
            "traffic_impact": original.get("traffic_impact"),
            "similar_prs": original.get("similar_prs", []),
            "recommendations": original.get("recommendations", []),
            "timestamp": original.get(
                "timestamp", prompt_payload.get("timestamp", "")
            ),
        }

    async def post(
        self,
        prompt_payload: dict,
        llm_response: LLMResponse | None,
    ) -> bool:
        """POST the result to the api-gateway.

        Parameters
        ----------
        prompt_payload:
            The full ``LLMPromptPayload`` dict consumed from Kafka.
        llm_response:
            The LLM response, or ``None`` if the LLM call failed.

        Returns
        -------
        bool
            ``True`` if the POST succeeded, ``False`` otherwise.
        """
        event_id = prompt_payload.get("event_id", "unknown")
        payload = self._build_payload(prompt_payload, llm_response)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._api_url, json=payload)
                resp.raise_for_status()

            logger.info(
                "Result posted to api-gateway",
                event_id=event_id,
                llm_enriched=llm_response is not None,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to POST result to api-gateway",
                event_id=event_id,
                url=self._api_url,
            )
            return False
