"""API Gateway — FastAPI application entry point.

The API Gateway is the entry point for the TraceRat blast radius
prediction system. It receives GitHub webhooks, publishes PR events
to Kafka, and posts prediction results back to GitHub PRs.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path so shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.dependencies import get_kafka_producer
from app.routes import health, results, webhook
from shared.logging import setup_logging
from shared.metrics import service_info, setup_metrics

setup_logging("api-gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Starts Kafka producer on startup and stops it on shutdown.
    """
    # Startup
    producer = get_kafka_producer()
    try:
        await producer.start()
    except Exception as e:
        import structlog
        logger = structlog.get_logger()
        logger.error("Failed to connect to Kafka on startup", error=str(e))
        # Don't crash — allow health checks to report not ready

    service_info.info({
        "service": "api-gateway",
        "version": "0.1.0",
    })

    yield

    # Shutdown
    await producer.stop()


app = FastAPI(
    title="TraceRat API Gateway",
    description="Entry point for the blast radius prediction system. "
    "Receives GitHub webhooks and posts prediction results.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Metrics ---
setup_metrics(app, "api-gateway")

# --- Routes ---
app.include_router(webhook.router)
app.include_router(health.router)
app.include_router(results.router)


@app.get("/", tags=["root"])
async def root():
    """Root endpoint — basic service info."""
    return {
        "service": "tracerat-api-gateway",
        "version": "0.1.0",
        "docs": "/docs",
    }
