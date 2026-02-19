"""
engine.logging — Centralised logging, benchmarking, and system monitoring.

Public API::

    from engine.logging import install_logger, get_logs, clear_logs
    from engine.logging import timed, get_benchmarks, reset_benchmarks
    from engine.logging import get_system_monitor
"""
from engine.logging.cosy_logger import (
    install_logger,
    get_logs,
    clear_logs,
    get_handler,
)
from engine.logging.benchmark import timed, get_benchmarks, reset_benchmarks
from engine.logging.monitor import get_system_monitor

__all__ = [
    "install_logger", "get_logs", "clear_logs", "get_handler",
    "timed", "get_benchmarks", "reset_benchmarks",
    "get_system_monitor",
]
