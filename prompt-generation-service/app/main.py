"""Prompt Generation Service — FastAPI application entry point.

Stateless microservice that consumes ``prediction-results`` from Kafka,
builds structured LLM prompts, and publishes them to the ``llm-prompts``
topic for downstream LLM processing.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import PromptGenerationConsumer
from app.services.prompt_builder import PromptBuilder
from app.services.skip_filter import SkipFilter
from shared.config import get_settings
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger, setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("prompt-generation-service")
logger = get_logger("main")

# Module-level references for health checks
_consumer: PromptGenerationConsumer | None = None
_consumer_task: asyncio.Task | None = None
_producer: KafkaProducerClient | None = None


def get_consumer() -> PromptGenerationConsumer | None:
    """Get the active consumer instance."""
    return _consumer


def get_producer() -> KafkaProducerClient | None:
    """Get the active producer instance."""
    return _producer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop Kafka producer and consumer."""
    global _consumer, _consumer_task, _producer

    settings = get_settings()

    # --- Startup ---

    # 1. Prompt builder (stateless)
    prompt_builder = PromptBuilder()

    # 2. Skip filter (stateless)
    skip_filter = SkipFilter()

    # 3. Kafka producer
    _producer = KafkaProducerClient(settings.kafka)
    try:
        await _producer.start()
        logger.info("Kafka producer started")
    except Exception as e:
        logger.error("Failed to start Kafka producer", error=str(e))

    # 4. Kafka consumer
    _consumer = PromptGenerationConsumer(
        kafka_settings=settings.kafka,
        prompt_builder=prompt_builder,
        skip_filter=skip_filter,
        producer=_producer,
        llm_prompts_topic=settings.kafka.llm_prompts_topic,
    )
    try:
        await _consumer.start()
        _consumer_task = asyncio.create_task(_consumer.run())
        logger.info("Prompt generation consumer started")
    except Exception as e:
        logger.error("Failed to start consumer", error=str(e))

    service_info.info({
        "service": "prompt-generation-service",
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

    if _producer:
        await _producer.stop()

    logger.info("Prompt generation service stopped")


app = FastAPI(
    title="TraceRat Prompt Generation Service",
    description=(
        "Consumes prediction results from Kafka, builds structured "
        "LLM prompts, and publishes them to the llm-prompts topic."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# --- Metrics ---
setup_metrics(app, "prompt-generation-service")


# --- Health Endpoints ---


@app.get("/health", tags=["health"])
async def health():
    """Liveness probe. Returns 200 if the service is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    """Readiness probe. Checks Kafka consumer and producer connectivity."""
    consumer = get_consumer()
    producer = get_producer()

    checks = {
        "consumer": (
            consumer is not None and consumer._running
            if consumer
            else False
        ),
        "producer": producer.is_connected if producer else False,
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
        "service": "tracerat-prompt-generation-service",
        "version": "0.1.0",
        "docs": "/docs",
    }
