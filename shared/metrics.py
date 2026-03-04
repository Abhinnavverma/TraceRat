"""Prometheus metrics utilities for all services."""

from prometheus_client import Counter, Histogram, Info
from prometheus_fastapi_instrumentator import Instrumentator


def setup_metrics(app, service_name: str) -> Instrumentator:
    """Instrument a FastAPI app with Prometheus metrics.

    Args:
        app: FastAPI application instance.
        service_name: Name of the service (used in metric labels).

    Returns:
        Configured Instrumentator instance.
    """
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        inprogress_labels=True,
    )
    instrumentator.instrument(app).expose(app, endpoint="/metrics")
    return instrumentator


# --- Common metrics shared across services ---

webhook_events_total = Counter(
    "tracerat_webhook_events_total",
    "Total webhook events received",
    ["event_type", "action"],
)

kafka_messages_produced = Counter(
    "tracerat_kafka_messages_produced_total",
    "Total messages produced to Kafka",
    ["topic"],
)

kafka_messages_consumed = Counter(
    "tracerat_kafka_messages_consumed_total",
    "Total messages consumed from Kafka",
    ["topic", "consumer_group"],
)

prediction_duration = Histogram(
    "tracerat_prediction_duration_seconds",
    "Time taken to generate a prediction",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

github_api_requests = Counter(
    "tracerat_github_api_requests_total",
    "Total GitHub API requests",
    ["endpoint", "status"],
)

service_info = Info(
    "tracerat_service",
    "Service metadata",
)
