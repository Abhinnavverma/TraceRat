"""Prediction Service — FastAPI application entry point.

Stateless microservice that consumes ``delta-graph`` and ``pr-context``
Kafka topics, correlates them by ``event_id``, computes a weighted
risk score, and publishes results to both a Kafka topic and the
api-gateway HTTP endpoint.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import PredictionConsumer
from app.services.correlator import SignalCorrelator
from app.services.result_publisher import ResultPublisher
from app.services.scorer import RiskScorer
from shared.config import get_settings
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger, setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("prediction-service")
logger = get_logger("main")

# Module-level references for health checks
_consumer: PredictionConsumer | None = None
_consumer_task: asyncio.Task | None = None
_producer: KafkaProducerClient | None = None
_sweep_task: asyncio.Task | None = None


def get_consumer() -> PredictionConsumer | None:
    """Get the active consumer instance."""
    return _consumer


def get_producer() -> KafkaProducerClient | None:
    """Get the active producer instance."""
    return _producer


async def _run_sweep_loop(
    correlator: SignalCorrelator,
    scorer: RiskScorer,
    publisher: ResultPublisher,
    interval: int,
) -> None:
    """Periodically sweep expired partial bundles and publish degraded predictions."""
    while True:
        try:
            await asyncio.sleep(interval)
            expired = correlator.sweep_expired()
            for bundle in expired:
                try:
                    output = scorer.score(bundle)
                    await publisher.publish(output)
                    logger.info(
                        "Degraded prediction published for expired bundle",
                        event_id=bundle.event_id,
                        missing=bundle.missing_signals,
                    )
                except Exception:
                    logger.exception(
                        "Failed to publish degraded prediction",
                        event_id=bundle.event_id,
                    )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Sweep loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop Kafka producer, consumer, sweep task."""
    global _consumer, _consumer_task, _producer, _sweep_task

    settings = get_settings()
    pred_settings = settings.prediction

    # --- Startup ---

    # 1. Signal correlator (in-memory buffer)
    correlator = SignalCorrelator(ttl_seconds=pred_settings.buffer_ttl_seconds)

    # 2. Risk scorer with configurable weights
    scorer = RiskScorer(
        change_size_weight=pred_settings.change_size_weight,
        depth_weight=pred_settings.depth_weight,
        traffic_weight=pred_settings.traffic_weight,
        history_weight=pred_settings.history_weight,
    )

    # 3. Kafka producer
    _producer = KafkaProducerClient(settings.kafka)
    try:
        await _producer.start()
        logger.info("Kafka producer started")
    except Exception as e:
        logger.error("Failed to start Kafka producer", error=str(e))

    # 4. Result publisher (dual-path: Kafka + HTTP)
    publisher = ResultPublisher(
        producer=_producer,
        prediction_topic=settings.kafka.prediction_results_topic,
        api_gateway_url=pred_settings.api_gateway_results_url,
    )

    # 5. Kafka consumer
    _consumer = PredictionConsumer(
        kafka_settings=settings.kafka,
        correlator=correlator,
        scorer=scorer,
        publisher=publisher,
    )
    try:
        await _consumer.start()
        _consumer_task = asyncio.create_task(_consumer.run())
        logger.info("Prediction consumer started")
    except Exception as e:
        logger.error("Failed to start consumer", error=str(e))

    # 6. Sweep task for expired bundles
    _sweep_task = asyncio.create_task(
        _run_sweep_loop(
            correlator=correlator,
            scorer=scorer,
            publisher=publisher,
            interval=pred_settings.sweep_interval_seconds,
        )
    )

    service_info.info({
        "service": "prediction-service",
        "version": "0.1.0",
    })

    yield

    # --- Shutdown ---

    if _sweep_task and not _sweep_task.done():
        _sweep_task.cancel()
        try:
            await _sweep_task
        except asyncio.CancelledError:
            pass

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

    logger.info("Prediction service stopped")


app = FastAPI(
    title="TraceRat Prediction Service",
    description=(
        "Stateless blast-radius scoring service. "
        "Correlates delta-graph and pr-context signals, computes a "
        "weighted risk score, and publishes predictions to Kafka "
        "and the api-gateway."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# --- Metrics ---
setup_metrics(app, "prediction-service")


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
        "service": "tracerat-prediction-service",
        "version": "0.1.0",
        "docs": "/docs",
    }
