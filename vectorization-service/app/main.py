"""Vectorization Service — FastAPI application entry point.

Hybrid service: Kafka consumer for diff-content processing running
as a background task, plus HTTP endpoints for health, readiness,
metrics, and historical PR backfill.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import VectorizationConsumer
from app.routes.backfill import router as backfill_router
from app.routes.backfill import set_dependencies
from app.services.embedder import create_embedder
from app.services.vector_store import VectorStore
from shared.config import get_settings
from shared.logging import get_logger, setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("vectorization-service")
logger = get_logger("main")

# Module-level references for health checks
_vector_store: VectorStore | None = None
_consumer: VectorizationConsumer | None = None
_consumer_task: asyncio.Task | None = None


def get_vector_store() -> VectorStore | None:
    """Get the active VectorStore instance."""
    return _vector_store


def get_consumer() -> VectorizationConsumer | None:
    """Get the active consumer instance."""
    return _consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop VectorStore, embedder, Kafka consumer."""
    global _vector_store, _consumer, _consumer_task

    settings = get_settings()

    # --- Startup ---

    # 1. Create embedding backend
    embedder = create_embedder(
        backend_type=settings.embedding.backend,
        model_name=settings.embedding.model_name,
        openai_api_key=settings.embedding.openai_api_key,
    )
    logger.info(
        "Embedding backend configured",
        backend=settings.embedding.backend,
        model=settings.embedding.model_name,
    )

    # 2. Connect to Qdrant
    _vector_store = VectorStore(
        host=settings.qdrant.host,
        port=settings.qdrant.port,
        collection_name=settings.qdrant.collection_name,
    )
    try:
        await _vector_store.connect()
        await _vector_store.ensure_collection(embedder.dimension())
        logger.info("Qdrant connected and collection ensured")
    except Exception as e:
        logger.error("Failed to connect to Qdrant", error=str(e))

    # 3. Inject dependencies into backfill router
    set_dependencies(
        embedder=embedder,
        vector_store=_vector_store,
    )

    # 4. Start the Kafka consumer
    _consumer = VectorizationConsumer(
        kafka_settings=settings.kafka,
        embedder=embedder,
        vector_store=_vector_store,
    )
    try:
        await _consumer.start()
        _consumer_task = asyncio.create_task(_consumer.run())
        logger.info("Vectorization consumer started")
    except Exception as e:
        logger.error("Failed to start consumer", error=str(e))

    service_info.info({
        "service": "vectorization-service",
        "version": "0.1.0",
    })

    yield

    # --- Shutdown ---

    if _consumer:
        await _consumer.stop()

    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    if _vector_store:
        await _vector_store.close()

    logger.info("Vectorization service stopped")


app = FastAPI(
    title="TraceRat Vectorization Service",
    description=(
        "Embeds PR diffs into vector representations, stores them in "
        "Qdrant, and performs similarity search against historical PRs. "
        "Publishes enriched pr-context messages for the prediction service."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# --- Metrics ---
setup_metrics(app, "vectorization-service")

# --- Backfill Router ---
app.include_router(backfill_router)


# --- Health Endpoints ---


@app.get("/health", tags=["health"])
async def health():
    """Liveness probe. Returns 200 if the service is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    """Readiness probe. Checks Qdrant and Kafka connectivity."""
    store = get_vector_store()
    consumer = get_consumer()

    qdrant_healthy = await store.health_check() if store else False

    checks = {
        "qdrant": qdrant_healthy,
        "consumer": (
            consumer is not None and consumer._running
            if consumer
            else False
        ),
        "producer": (
            consumer.producer.is_connected if consumer else False
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
        "service": "tracerat-vectorization-service",
        "version": "0.1.0",
        "docs": "/docs",
    }
