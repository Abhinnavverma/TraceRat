"""Health and readiness check endpoints."""

from fastapi import APIRouter, status

from app.dependencies import get_kafka_producer
from shared.logging import get_logger

logger = get_logger("health")

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def health():
    """Basic liveness check. Returns 200 if the service is running."""
    return {"status": "ok"}


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
)
async def ready():
    """Readiness check. Verifies Kafka producer connectivity."""
    producer = get_kafka_producer()

    checks = {
        "kafka": producer.is_connected,
    }

    all_ready = all(checks.values())

    if not all_ready:
        logger.warning("Readiness check failed", checks=checks)
        return {
            "status": "not_ready",
            "checks": checks,
        }

    return {
        "status": "ready",
        "checks": checks,
    }
