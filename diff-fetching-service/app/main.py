"""Diff Fetching Service — FastAPI application entry point.

Hybrid service: Kafka consumer for processing PR events +
lightweight HTTP endpoints for health, readiness, and metrics.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import DiffConsumer
from shared.logging import get_logger, setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("diff-fetching-service")
logger = get_logger("main")

# Module-level reference so routes can access the consumer
_consumer: DiffConsumer | None = None
_consumer_task: asyncio.Task | None = None


def get_consumer() -> DiffConsumer | None:
    """Get the active consumer instance."""
    return _consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop the Kafka consumer."""
    global _consumer, _consumer_task

    _consumer = DiffConsumer()

    try:
        await _consumer.start()
        # Run the consumer loop as a background task
        _consumer_task = asyncio.create_task(_consumer.run())
        logger.info("Diff consumer started")
    except Exception as e:
        logger.error("Failed to start diff consumer", error=str(e))

    service_info.info({
        "service": "diff-fetching-service",
        "version": "0.1.0",
    })

    yield

    # Shutdown
    if _consumer:
        await _consumer.stop()
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    logger.info("Diff consumer stopped")


app = FastAPI(
    title="TraceRat Diff Fetching Service",
    description="Consumes PR events, fetches diffs from GitHub, "
    "maps to modules, and publishes analysis results.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Metrics ---
setup_metrics(app, "diff-fetching-service")


# --- Health Endpoints ---


@app.get("/health", tags=["health"])
async def health():
    """Liveness probe. Returns 200 if the service is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    """Readiness probe. Checks Kafka consumer and producer connectivity."""
    consumer = get_consumer()

    checks = {
        "kafka_consumer": consumer is not None and consumer._running if consumer else False,
        "kafka_producer": consumer.producer.is_connected if consumer else False,
    }

    all_ready = all(checks.values())

    if not all_ready:
        logger.warning("Readiness check failed", checks=checks)

    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
    }


@app.get("/", tags=["root"])
async def root():
    """Root endpoint — basic service info."""
    return {
        "service": "tracerat-diff-fetching-service",
        "version": "0.1.0",
        "docs": "/docs",
    }
