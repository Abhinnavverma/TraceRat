"""Structured JSON logging configuration."""

import logging
import sys

import structlog


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Configure structured logging for a service.

    Uses structlog for structured JSON output in production
    and colored console output in development.

    Args:
        service_name: Name of the service for log context.
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.getLevelName(level.upper()),
    )

    # Bind service name to all loggers
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a structlog logger.

    Args:
        name: Optional logger name for context.

    Returns:
        Bound structlog logger instance.
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(component=name)
    return logger
