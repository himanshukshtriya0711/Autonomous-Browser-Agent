"""
backend/utils/logger.py
========================
Logger factory — call get_logger(__name__) in every module.
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for the given module."""
    return logging.getLogger(name)
