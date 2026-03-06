"""Map internal PredictionOutput to external payload formats.

Two targets:
- **api-gateway** ``POST /results`` — matches the ``PredictionResult``
  schema defined in ``api-gateway/app/models.py``.
- **Kafka ``prediction-results`` topic** — full output including the
  ``degraded`` flag consumed by prompt-generation-service.
"""

from app.models import PredictionOutput


class ResultMapper:
    """Stateless mapper between internal and external schemas."""

    @staticmethod
    def to_api_gateway_payload(output: PredictionOutput) -> dict:
        """Map a :class:`PredictionOutput` to the api-gateway ``PredictionResult`` schema.

        The api-gateway expects:
        ``repo_full_name``, ``pr_number``, ``installation_id``,
        ``risk_score``, ``risk_level``, ``explanation``,
        ``affected_components`` (list of {name, impact_score,
        traffic_volume, relationship}), ``traffic_impact``,
        ``similar_prs`` (list of URL strings),
        ``recommendations``, ``timestamp``.
        """
        return {
            "repo_full_name": output.repo_full_name,
            "pr_number": output.pr_number,
            "installation_id": output.installation_id,
            "risk_score": output.risk_score,
            "risk_level": output.risk_level.value,
            "explanation": output.explanation,
            "affected_components": [
                {
                    "name": c.name,
                    "impact_score": c.impact_score,
                    "traffic_volume": c.traffic_volume,
                    "relationship": c.relationship,
                }
                for c in output.affected_components
            ],
            "traffic_impact": output.traffic_impact,
            "similar_prs": output.similar_prs,
            "recommendations": output.recommendations,
            "timestamp": output.timestamp,
        }

    @staticmethod
    def to_kafka_payload(output: PredictionOutput) -> dict:
        """Serialize the full output for the ``prediction-results`` topic.

        Includes the ``degraded`` flag so the prompt-generation-service
        knows whether it can construct a complete prompt.
        """
        return output.model_dump(mode="json")
