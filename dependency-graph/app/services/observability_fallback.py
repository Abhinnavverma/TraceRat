"""Observability API fallback for runtime graph weights.

When telemetry data from the Kafka topic is stale or unavailable,
this service pulls metrics directly from an observability backend
(e.g., Prometheus, Jaeger) to enrich graph weights.

This module defines the interface and a Prometheus stub implementation.
Concrete implementations can be swapped via configuration.
"""

from abc import ABC, abstractmethod

from app.models import EdgeWeight, NodeWeight
from shared.logging import get_logger

logger = get_logger("observability_fallback")


class ObservabilityBackend(ABC):
    """Abstract interface for observability data sources.

    Implementations pull runtime metrics from external systems
    to provide weight data when Kafka telemetry is unavailable.
    """

    @abstractmethod
    async def fetch_node_weight(self, node_name: str) -> NodeWeight | None:
        """Fetch weight data for a single node.

        Args:
            node_name: Name of the service/module to look up.

        Returns:
            NodeWeight with metrics, or None if unavailable.
        """
        ...

    @abstractmethod
    async def fetch_edge_weight(
        self, source: str, target: str
    ) -> EdgeWeight | None:
        """Fetch weight data for an edge between two nodes.

        Args:
            source: Source service/module name.
            target: Target service/module name.

        Returns:
            EdgeWeight with metrics, or None if unavailable.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check connectivity to the observability backend."""
        ...


class PrometheusBackend(ObservabilityBackend):
    """Prometheus-based observability backend (stub implementation).

    Queries Prometheus for service-level metrics like request rate,
    error rate, and latency. Actual PromQL queries would be customized
    per deployment.

    TODO: Implement actual Prometheus API calls when deployed.
    """

    def __init__(self, prometheus_url: str = "http://localhost:9090"):
        self._url = prometheus_url

    async def fetch_node_weight(self, node_name: str) -> NodeWeight | None:
        """Fetch node weight from Prometheus metrics.

        Stub: returns None. In production, would execute PromQL queries like:
        - rate(http_requests_total{service="<node_name>"}[5m])
        - rate(http_errors_total{service="<node_name>"}[5m])
        - histogram_quantile(0.99, http_request_duration_seconds{...})
        """
        logger.debug(
            "Prometheus node weight fetch (stub)",
            node=node_name,
            url=self._url,
        )
        return None

    async def fetch_edge_weight(
        self, source: str, target: str
    ) -> EdgeWeight | None:
        """Fetch edge weight from Prometheus metrics.

        Stub: returns None. In production, would query inter-service
        call metrics from distributed tracing or service mesh telemetry.
        """
        logger.debug(
            "Prometheus edge weight fetch (stub)",
            source=source,
            target=target,
            url=self._url,
        )
        return None

    async def health_check(self) -> bool:
        """Check Prometheus connectivity.

        Stub: always returns True. In production, would GET /-/ready.
        """
        return True


class ObservabilityFallback:
    """Orchestrates fallback weight lookups from observability backends.

    Used by the delta calculator when telemetry data is stale
    or when graph nodes lack weight annotations.
    """

    def __init__(self, backend: ObservabilityBackend | None = None):
        self._backend = backend or PrometheusBackend()

    async def fetch_weights_for_nodes(
        self, node_names: list[str]
    ) -> dict[str, NodeWeight]:
        """Fetch weights for multiple nodes.

        Args:
            node_names: List of service/module names.

        Returns:
            Dict mapping node name to NodeWeight (only includes
            nodes where data was available).
        """
        results: dict[str, NodeWeight] = {}
        for name in node_names:
            try:
                weight = await self._backend.fetch_node_weight(name)
                if weight is not None:
                    results[name] = weight
            except Exception:
                logger.exception("Failed to fetch node weight", node=name)
        return results

    async def fetch_edge_weight(
        self, source: str, target: str
    ) -> EdgeWeight | None:
        """Fetch a single edge weight from the observability backend."""
        try:
            return await self._backend.fetch_edge_weight(source, target)
        except Exception:
            logger.exception(
                "Failed to fetch edge weight", source=source, target=target
            )
            return None

    async def health_check(self) -> bool:
        """Check backend connectivity."""
        return await self._backend.health_check()
