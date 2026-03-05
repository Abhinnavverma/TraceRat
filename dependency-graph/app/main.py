"""Dependency Graph Service — FastAPI application entry point.

Hybrid service: Two Kafka consumers (diff-metadata + telemetry) running
as background tasks, plus lightweight HTTP endpoints for health,
readiness, and metrics.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import DependencyGraphConsumer
from app.services.neo4j_client import Neo4jClient
from app.services.telemetry_consumer import TelemetryConsumer
from shared.logging import get_logger, setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("dependency-graph-service")
logger = get_logger("main")

# Module-level references for health checks
_neo4j_client: Neo4jClient | None = None
_graph_consumer: DependencyGraphConsumer | None = None
_telemetry_consumer: TelemetryConsumer | None = None
_graph_consumer_task: asyncio.Task | None = None
_telemetry_consumer_task: asyncio.Task | None = None


def get_neo4j_client() -> Neo4jClient | None:
    """Get the active Neo4j client instance."""
    return _neo4j_client


def get_graph_consumer() -> DependencyGraphConsumer | None:
    """Get the active graph consumer instance."""
    return _graph_consumer


def get_telemetry_consumer() -> TelemetryConsumer | None:
    """Get the active telemetry consumer instance."""
    return _telemetry_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop Neo4j, Kafka consumers."""
    global _neo4j_client, _graph_consumer, _telemetry_consumer
    global _graph_consumer_task, _telemetry_consumer_task

    # --- Startup ---

    # 1. Connect to Neo4j
    _neo4j_client = Neo4jClient()
    try:
        await _neo4j_client.connect()
        logger.info("Neo4j connected")
    except Exception as e:
        logger.error("Failed to connect to Neo4j", error=str(e))
        # Continue without Neo4j — service degrades gracefully

    # 2. Start the diff-metadata consumer (delta graph computation)
    _graph_consumer = DependencyGraphConsumer(neo4j_client=_neo4j_client)
    try:
        await _graph_consumer.start()
        _graph_consumer_task = asyncio.create_task(_graph_consumer.run())
        logger.info("Dependency graph consumer started")
    except Exception as e:
        logger.error("Failed to start graph consumer", error=str(e))

    # 3. Start the telemetry consumer (runtime weight enrichment)
    _telemetry_consumer = TelemetryConsumer(neo4j_client=_neo4j_client)
    try:
        await _telemetry_consumer.start()
        _telemetry_consumer_task = asyncio.create_task(_telemetry_consumer.run())
        logger.info("Telemetry consumer started")
    except Exception as e:
        logger.error("Failed to start telemetry consumer", error=str(e))

    service_info.info({
        "service": "dependency-graph-service",
        "version": "0.1.0",
    })

    yield

    # --- Shutdown ---

    # Flush remaining telemetry batch
    if _telemetry_consumer:
        await _telemetry_consumer.flush_remaining()

    # Stop consumers
    if _graph_consumer:
        await _graph_consumer.stop()
    if _telemetry_consumer:
        await _telemetry_consumer.stop()

    # Cancel background tasks
    for task in [_graph_consumer_task, _telemetry_consumer_task]:
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Close Neo4j connection
    if _neo4j_client:
        await _neo4j_client.close()

    logger.info("Dependency graph service stopped")


app = FastAPI(
    title="TraceRat Dependency Graph Service",
    description="Consumes diff-metadata events, queries the weighted dependency "
    "graph in Neo4j, computes delta graphs, and publishes affected "
    "components to the delta-graph topic. Also ingests runtime "
    "telemetry to enrich graph weights.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Metrics ---
setup_metrics(app, "dependency-graph-service")


# --- Health Endpoints ---


@app.get("/health", tags=["health"])
async def health():
    """Liveness probe. Returns 200 if the service is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    """Readiness probe. Checks Neo4j and Kafka connectivity."""
    neo4j = get_neo4j_client()
    graph_consumer = get_graph_consumer()
    telemetry_consumer = get_telemetry_consumer()

    neo4j_healthy = await neo4j.health_check() if neo4j else False

    checks = {
        "neo4j": neo4j_healthy,
        "graph_consumer": (
            graph_consumer is not None and graph_consumer._running
            if graph_consumer
            else False
        ),
        "graph_producer": (
            graph_consumer.producer.is_connected if graph_consumer else False
        ),
        "telemetry_consumer": (
            telemetry_consumer is not None and telemetry_consumer._running
            if telemetry_consumer
            else False
        ),
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
        "service": "tracerat-dependency-graph-service",
        "version": "0.1.0",
        "docs": "/docs",
    }
