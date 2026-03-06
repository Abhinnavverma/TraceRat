"""Skip filter for degraded predictions.

Decides whether a prediction result should be skipped (no prompt
generated) based on its attributes.  Currently only checks for the
``degraded`` flag — degraded predictions are logged and dropped.
"""

from __future__ import annotations

from shared.logging import get_logger

logger = get_logger("skip_filter")


class SkipFilter:
    """Determines whether a prediction should be skipped.

    Stateless — safe to share across concurrent calls.
    """

    def should_skip(self, prediction: dict) -> bool:
        """Return ``True`` if prompts should NOT be generated for this prediction.

        Parameters
        ----------
        prediction:
            Deserialized prediction payload from the ``prediction-results`` topic.
        """
        degraded = prediction.get("degraded", False)

        if degraded:
            event_id = prediction.get("event_id", "unknown")
            missing = prediction.get("missing_signals", [])
            logger.info(
                "Skipping degraded prediction — no LLM prompt will be generated",
                event_id=event_id,
                missing_signals=missing,
            )
            return True

        return False
