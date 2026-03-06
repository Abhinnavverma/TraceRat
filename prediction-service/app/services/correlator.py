"""Signal correlator for joining delta-graph and pr-context messages.

Holds partial data in an in-memory buffer keyed by ``event_id``.
When both signals arrive the complete :class:`SignalBundle` is returned
immediately.  A periodic sweep expels entries older than the configured
TTL as *degraded* bundles so predictions are never silently lost.
"""

import time
from typing import Literal

from app.models import SignalBundle
from shared.logging import get_logger

logger = get_logger("correlator")

SignalType = Literal["delta-graph", "pr-context"]


class SignalCorrelator:
    """In-memory two-stream join buffer.

    Parameters
    ----------
    ttl_seconds:
        Maximum seconds to hold a partial bundle before expiring it
        as a degraded prediction.
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._ttl = ttl_seconds
        self._buffer: dict[str, SignalBundle] = {}

    @property
    def buffer_size(self) -> int:
        """Number of pending (incomplete) bundles."""
        return len(self._buffer)

    def ingest(
        self, signal_type: SignalType, event_id: str, payload: dict
    ) -> SignalBundle | None:
        """Ingest a signal and return a complete bundle when both signals are present.

        Parameters
        ----------
        signal_type:
            ``"delta-graph"`` or ``"pr-context"``.
        event_id:
            Unique event identifier shared by both upstream messages.
        payload:
            Full deserialized Kafka message value.

        Returns
        -------
        SignalBundle or None:
            The completed bundle if *both* signals have now arrived,
            otherwise ``None`` (first signal stored, waiting for second).
        """
        existing = self._buffer.get(event_id)

        if existing is None:
            # First signal — create a new partial bundle
            bundle = SignalBundle(event_id=event_id)
            if signal_type == "delta-graph":
                bundle.delta_graph = payload
            else:
                bundle.pr_context = payload

            self._buffer[event_id] = bundle
            logger.info(
                "First signal ingested — waiting for pair",
                event_id=event_id,
                signal=signal_type,
            )
            return None

        # Second signal — complete the bundle
        if signal_type == "delta-graph":
            if existing.delta_graph is not None:
                logger.warning(
                    "Duplicate delta-graph signal — ignoring",
                    event_id=event_id,
                )
                return None
            existing.delta_graph = payload
        else:
            if existing.pr_context is not None:
                logger.warning(
                    "Duplicate pr-context signal — ignoring",
                    event_id=event_id,
                )
                return None
            existing.pr_context = payload

        # Both present — remove from buffer and return
        del self._buffer[event_id]
        logger.info(
            "Both signals received — bundle complete",
            event_id=event_id,
        )
        return existing

    def sweep_expired(self) -> list[SignalBundle]:
        """Remove and return all entries older than the TTL.

        Expired bundles are marked ``degraded=True`` with the missing
        signal source listed in ``missing_signals``.

        Returns
        -------
        list[SignalBundle]:
            Degraded bundles that exceeded the TTL.
        """
        now = time.time()
        expired: list[SignalBundle] = []
        expired_ids: list[str] = []

        for event_id, bundle in self._buffer.items():
            age = now - bundle.created_at
            if age >= self._ttl:
                bundle.degraded = True
                missing: list[str] = []
                if bundle.delta_graph is None:
                    missing.append("delta-graph")
                if bundle.pr_context is None:
                    missing.append("pr-context")
                bundle.missing_signals = missing
                expired.append(bundle)
                expired_ids.append(event_id)

        for event_id in expired_ids:
            del self._buffer[event_id]

        if expired:
            logger.warning(
                "Expired partial bundles swept",
                count=len(expired),
                event_ids=expired_ids,
            )

        return expired
