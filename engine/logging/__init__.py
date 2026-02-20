"""
engine.logging — Centralised logging, benchmarking, and system monitoring.

Public API::

    from engine.logging import install_logger, get_logs, clear_logs
    from engine.logging import timed, get_benchmarks, reset_benchmarks
    from engine.logging import record_llm_kpi, get_llm_kpis, get_kpi_timeseries
    from engine.logging import get_system_monitor
"""
from engine.logging.cosy_logger import (
    install_logger,
    get_logs,
    clear_logs,
    get_handler,
)
from engine.logging.benchmark import (
    timed,
    get_benchmarks,
    reset_benchmarks,
    record_llm_kpi,
    get_llm_kpis,
    get_kpi_timeseries,
    get_operation_timings,
    get_all_operations,
)
from engine.logging.monitor import get_system_monitor

__all__ = [
    "install_logger", "get_logs", "clear_logs", "get_handler",
    "timed", "get_benchmarks", "reset_benchmarks",
    "record_llm_kpi", "get_llm_kpis", "get_kpi_timeseries",
    "get_operation_timings", "get_all_operations",
    "get_system_monitor",
]
