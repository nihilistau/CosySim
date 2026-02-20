"""
CosyLogger (services shim) — redirects to engine.logging.cosy_logger.

This module is kept for backward compatibility.
All logic lives in engine/logging/cosy_logger.py.
"""
# Re-export everything from the canonical engine implementation
from engine.logging.cosy_logger import (  # noqa: F401
    install_logger,
    get_logs,
    get_handler,
    MAX_RECORDS,
    DEFAULT_FORMAT,
    LEVELS,
)
