"""LLM Service — FastAPI application entry point.

Stateless microservice that consumes ``llm-prompts`` from Kafka,
calls the configured LLM provider (default: Gemini), and posts the
enriched prediction results to the api-gateway ``/results`` endpoint.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import LLMServiceConsumer
from app.services.llm_client import create_llm_client, BaseLLMClient
from app.services.result_poster import ResultPoster
from shared.config import get_settings
from shared.logging import get_logger, setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("llm-service")
logger = get_logger("main")

# Module-level references for health checks
_consumer: LLMServiceConsumer | None = None
_consumer_task: asyncio.Task | None = None
_llm_client: BaseLLMClient | None = None


def get_consumer() -> LLMServiceConsumer | None:
    """Get the active consumer instance."""
    return _consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop LLM client and Kafka consumer."""
    global _consumer, _consumer_task, _llm_client

    settings = get_settings()

    # --- Startup ---

    # 1. Create LLM client
    try:
        _llm_client = create_llm_client(
            provider=settings.llm.provider,
            api_key=settings.llm.api_key,
            model=settings.llm.model,
            max_retries=settings.llm.max_retries,
            retry_base_delay=settings.llm.retry_base_delay,
        )
        logger.info(
            "LLM client created",
            provider=settings.llm.provider,
            model=settings.llm.model,
        )
    except Exception as e:
        logger.error("Failed to create LLM client", error=str(e))
        _llm_client = None

    # 2. Create result poster
    result_poster = ResultPoster(
        api_gateway_url=settings.llm.api_gateway_results_url,
    )

    # 3. Kafka consumer
    _consumer = LLMServiceConsumer(
        kafka_settings=settings.kafka,
        llm_client=_llm_client,
        result_poster=result_poster,
    )
    try:
        await _consumer.start()
        _consumer_task = asyncio.create_task(_consumer.run())
        logger.info("LLM service consumer started")
    except Exception as e:
        logger.error("Failed to start consumer", error=str(e))

    service_info.info({
        "service": "llm-service",
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

    logger.info("LLM service stopped")


app = FastAPI(
    title="TraceRat LLM Service",
    description=(
        "Consumes LLM prompts from Kafka, calls the configured LLM "
        "provider, and posts enriched prediction results to the api-gateway."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# --- Metrics ---
setup_metrics(app, "llm-service")


# --- Health Endpoints ---


@app.get("/health", tags=["health"])
async def health():
    """Liveness probe. Returns 200 if the service is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    """Readiness probe. Checks Kafka consumer connectivity."""
    consumer = get_consumer()

    checks = {
        "consumer": (
            consumer is not None and consumer._running
            if consumer
            else False
        ),
        "llm_client": _llm_client is not None,
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
        "service": "tracerat-llm-service",
        "version": "0.1.0",
        "docs": "/docs",
    }
