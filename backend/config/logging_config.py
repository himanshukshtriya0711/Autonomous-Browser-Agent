"""
backend/config/logging_config.py
=================================
Structured logging configuration for the entire application.
Uses rotating file handler + console handler with standard formatter.
"""

import logging
import logging.config
import logging.handlers
from pathlib import Path

from backend.config.settings import get_settings


def setup_logging() -> None:
    """Configure structured logging with file and console handlers."""
    settings = get_settings()

    # Ensure log directory exists
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.app_log_level.upper(), logging.INFO)

    LOGGING_CONFIG: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": logging.DEBUG,
                "formatter": "standard",
                "filename": str(log_dir / "agent.log"),
                "maxBytes": 10 * 1024 * 1024,  # 10 MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file"],
        },
        "loggers": {
            "uvicorn":          {"level": "INFO",    "propagate": True},
            "uvicorn.access":   {"level": "WARNING", "propagate": True},
            "playwright":       {"level": "WARNING", "propagate": True},
            "chromadb":         {"level": "WARNING", "propagate": True},
            "httpx":            {"level": "WARNING", "propagate": True},
            "httpcore":         {"level": "WARNING", "propagate": True},
        },
    }

    logging.config.dictConfig(LOGGING_CONFIG)
