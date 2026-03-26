"""
TitanCode Technologies — Structured Logging Configuration
===========================================================
This module configures structured JSON logging for the entire application.
JSON logs are essential for production because they are:

    1. **Machine-readable** — Tools like Datadog, ELK, and CloudWatch can
       parse and index them automatically.
    2. **Searchable** — Every log line is a JSON object with consistent
       fields, so you can filter by endpoint, user_id, status_code, etc.
    3. **Consistent** — No more guessing log formats. Every line has the
       same structure regardless of which module emitted it.

Log Format Example:
    {
        "timestamp": "2026-03-26T12:00:00.000Z",
        "level": "INFO",
        "message": "POST /api/v1/auth/login 200",
        "logger": "uvicorn.access",
        "module": "auth",
        "service": "titancode-api"
    }

Usage:
    from app.core.logging_config import setup_logging
    setup_logging()  # Call once in main.py lifespan
"""

import logging
import sys
from datetime import datetime, timezone

from pythonjsonlogger.json import JsonFormatter

from app.core.config import settings


class TitanCodeJsonFormatter(JsonFormatter):
    """
    Custom JSON formatter that adds TitanCode-specific fields to every log.

    Fields added automatically:
        - timestamp: ISO 8601 UTC timestamp
        - level:     Log level (INFO, WARNING, ERROR, etc.)
        - service:   The project name from settings
        - logger:    The name of the logger that emitted the message
        - module:    The Python module name

    This ensures every log line across the entire application has the
    same consistent structure — no matter which module or library emits it.
    """

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        """
        Override to inject our custom fields into every JSON log record.

        Args:
            log_record:  The dictionary that will be serialized to JSON.
            record:      The Python LogRecord with standard metadata.
            message_dict: Any extra key-value pairs from the log call.
        """
        super().add_fields(log_record, record, message_dict)

        # Add a proper ISO 8601 timestamp (not Python's default format)
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Add log level as an uppercase string for easy filtering
        log_record["level"] = record.levelname

        # Tag every log with the service name for multi-service environments
        log_record["service"] = settings.PROJECT_NAME

        # Include the logger name and module for traceability
        log_record["logger"] = record.name
        log_record["module"] = record.module


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure structured JSON logging for the entire application.

    This function:
        1. Creates a JSON formatter with our custom fields.
        2. Replaces the root logger's handlers with a JSON-emitting handler.
        3. Configures uvicorn's access and error loggers to use JSON too.

    Args:
        log_level: The minimum log level to capture. Default: "INFO".
                   Use "DEBUG" for verbose development output.

    Call this ONCE during application startup (in the lifespan handler).
    """
    # ── Step 1: Create the JSON formatter ──────────────────────────────
    formatter = TitanCodeJsonFormatter(
        # These fields are extracted from the LogRecord and included in output
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
    )

    # ── Step 2: Create a stream handler that writes to stdout ──────────
    # Writing to stdout (not stderr) is the Docker/k8s convention —
    # container orchestrators capture stdout for log aggregation.
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    # ── Step 3: Configure the root logger ──────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Clear any existing handlers to prevent duplicate log lines
    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)

    # ── Step 4: Configure uvicorn loggers ──────────────────────────────
    # Uvicorn has its own loggers that we need to override,
    # otherwise they'll output plain text alongside our JSON.
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvi_logger = logging.getLogger(logger_name)
        uvi_logger.handlers.clear()
        uvi_logger.addHandler(stream_handler)
        uvi_logger.propagate = False  # Don't double-log through root

    # ── Step 5: Quiet down noisy libraries ─────────────────────────────
    # SQLAlchemy's engine logger is very chatty at INFO level
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # Confirmation log (this will be the first JSON log line)
    logging.getLogger(__name__).info("Structured JSON logging initialized")
