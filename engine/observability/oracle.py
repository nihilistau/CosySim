"""
Oracle — CosySim Unified Observability Facade
===============================================

The Oracle is the single entry point for all CosySim observability. One import,
one call, and the entire monitoring infrastructure activates:

    from engine.observability.oracle import get_logger, diagnose

    logger = get_logger(__name__)    # Auto-initializes everything on first use
    logger.info("Something happened")
    logger.error("Something broke")  # Auto-aggregated + surfaced in Oracle dashboard

    diagnose()  # Print health + top errors + performance to console

The Oracle wires together 10+ dormant subsystems that were never activated:
  - StructuredLogger root handler → SQLite + JSONL (was never installed)
  - CosyLogger ring buffer → Phone panel feed
  - ErrorAggregator → fingerprint, group, count errors
  - Error callbacks → Oracle dashboard SocketIO feed

Version: v1.49.4 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.54.0 [2026-03-26] — Upgrade silent except-pass in OracleHandler.emit to traceback.print_exc
    v1.49.4 [2026-03-22] — Initial Oracle observability system — the All-Seeing Eye

CONNECTS: StructuredLogger, CosyLogger, ErrorAggregator, ActivityBus, Oracle scene
CALLED BY: FlaskScene.start(), launcher.py, any module via get_logger()
EMITS: structured logs, error callbacks, diagnostics
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

# ──── Module state ───────────────────────────────────────────────────────────

_initialized = False
_init_lock = threading.Lock()
_error_callbacks: List[Callable[[Dict[str, Any]], None]] = []


# ──── Initialization ─────────────────────────────────────────────────────────

def ensure_initialized() -> None:
    """Initialize the full Oracle observability stack (idempotent).

    Installs:
      1. StructuredLogger root handler → SQLite + JSONL capture
      2. CosyLogger ring buffer → Phone panel live feed
      3. OracleHandler → ERROR+ fires ErrorAggregator + callbacks

    Safe to call multiple times — only runs once.
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return

        # 1. Structured logger → SQLite + JSONL
        try:
            from engine.observability.structured_logger import install_root_handler
            install_root_handler()
        except Exception as exc:
            print(f"[Oracle] WARNING: StructuredLogger init failed: {exc}", file=sys.stderr)

        # 2. CosyLogger ring buffer → Phone panel
        try:
            from engine.logging.cosy_logger import install_logger
            install_logger()
        except Exception as exc:
            print(f"[Oracle] WARNING: CosyLogger init failed: {exc}", file=sys.stderr)

        # 3. Oracle error handler → ErrorAggregator + callbacks
        root = logging.getLogger()
        root.addHandler(_OracleHandler())

        _initialized = True


# ──── Oracle Error Handler ───────────────────────────────────────────────────

class _OracleHandler(logging.Handler):
    """Custom handler that fires on ERROR+ to aggregate and surface errors.

    Zero overhead on DEBUG/INFO/WARNING — only activates for ERROR and CRITICAL.
    Cost per ERROR: ~0.2ms (fingerprint hash + dict lookup + callback dispatch).

    CONNECTS: ErrorAggregator, _error_callbacks, Oracle dashboard SocketIO
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._flood_guard: Dict[str, float] = {}  # fingerprint → last emitted ts
        self._FLOOD_COOLDOWN = 5.0  # Don't fire callback for same fingerprint within 5s

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from engine.observability.error_aggregator import get_error_aggregator

            message = record.getMessage()
            module = record.name
            # Extract scene from the [SCENE_ID] prefix if present
            scene = ""
            if message.startswith("[") and "]" in message[:30]:
                scene = message[1:message.index("]")]

            error_type = ""
            if record.exc_info and record.exc_info[1]:
                error_type = type(record.exc_info[1]).__name__

            trace_id = getattr(record, "trace_id", "")

            fp = get_error_aggregator().ingest(
                message=message,
                module=module,
                scene=scene,
                error_type=error_type,
                trace_id=trace_id,
            )

            # Fire callbacks (Oracle dashboard SocketIO, etc.)
            # Flood guard: don't fire for same fingerprint within cooldown
            now = time.time()
            if fp not in self._flood_guard or (now - self._flood_guard[fp]) > self._FLOOD_COOLDOWN:
                self._flood_guard[fp] = now
                event = {
                    "fingerprint": fp,
                    "level": record.levelname,
                    "module": module,
                    "scene": scene,
                    "message": message[:500],
                    "error_type": error_type,
                    "timestamp": now,
                }
                for cb in _error_callbacks:
                    try:
                        cb(event)
                    except Exception:
                        pass  # Never crash the log handler

                # Clean flood guard (keep only last 5 minutes)
                if len(self._flood_guard) > 200:
                    cutoff = now - 300
                    self._flood_guard = {
                        k: v for k, v in self._flood_guard.items() if v > cutoff
                    }
        except Exception:
            # v1.54.0 [2026-03-26] — Log handler errors instead of swallowing
            import traceback
            traceback.print_exc()  # Safe fallback since logger may be broken


# ──── Public API ─────────────────────────────────────────────────────────────

def get_logger(name: str) -> "BoundLogger":
    """Get a structured logger with auto-initialization.

    Drop-in replacement for ``logging.getLogger(__name__)``.
    Returns a BoundLogger with trace support and structured context.
    Auto-initializes the full Oracle stack on first call.

    Args:
        name: Logger name (typically ``__name__``).

    Returns:
        BoundLogger instance with .info(), .error(), .warning(), .debug(),
        .begin_trace(), .query() support.
    """
    ensure_initialized()
    from engine.observability.structured_logger import get_logger as _get_sl
    return _get_sl(name)


def register_error_callback(fn: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callback fired on every ERROR+ log event.

    The callback receives a dict with: fingerprint, level, module, scene,
    message, error_type, timestamp.

    Used by the Oracle dashboard to emit real-time SocketIO events.

    Args:
        fn: Callback function.
    """
    if fn not in _error_callbacks:
        _error_callbacks.append(fn)


def unregister_error_callback(fn: Callable) -> None:
    """Remove a previously registered error callback."""
    if fn in _error_callbacks:
        _error_callbacks.remove(fn)


# ──── Diagnostic API ─────────────────────────────────────────────────────────
# Callable from Python REPL, tests, or scripts/oracle.py

def diagnose(verbose: bool = False) -> Dict[str, Any]:
    """Run a full system diagnostic and print results.

    Checks health, aggregates errors, shows performance metrics.
    Output is ASCII-safe (no Unicode) for Windows cp1252 compatibility.

    Args:
        verbose: If True, show full error details and trace IDs.

    Returns:
        Dict with health, errors, performance data.
    """
    ensure_initialized()
    result: Dict[str, Any] = {}

    print("")
    print("=" * 60)
    print("  ORACLE DIAGNOSTIC REPORT")
    print("  " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # ── Health ────────────────────────────────────────────────
    print("")
    print("-- HEALTH --")
    try:
        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()
        snapshot = mon.snapshot()
        result["system"] = snapshot
        cpu = snapshot.get("cpu_percent", 0)
        ram = snapshot.get("ram_percent", 0)
        gpu_vram = snapshot.get("gpu_vram_used_mb", 0)
        print(f"  CPU: {cpu:.0f}%  |  RAM: {ram:.0f}%  |  GPU VRAM: {gpu_vram:.0f}MB")
    except Exception as exc:
        print(f"  [!] System monitor unavailable: {exc}")

    try:
        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()
        services = mon.check_services()
        result["services"] = services
        for name, info in services.items():
            if isinstance(info, dict):
                status = "UP" if info.get("up") else "DOWN"
                latency = info.get("latency_ms", 0) or 0
                icon = "[OK]" if info.get("up") else "[!!]"
                print(f"  {icon} {name:20s} {status:4s}  ({latency:.0f}ms)")
            else:
                print(f"  [??] {name:20s} {info}")
    except Exception as exc:
        print(f"  [!] Service health unavailable: {exc}")

    # ── Errors ────────────────────────────────────────────────
    print("")
    print("-- ERRORS (last 5 min) --")
    try:
        from engine.observability.error_aggregator import get_error_aggregator
        agg = get_error_aggregator()
        snap = agg.snapshot()
        result["errors"] = snap
        rate = snap["error_rate"]
        print(f"  Total unique: {snap['total_unique']}  |  Rate: {rate['rate_per_min']}/min  |  New (1h): {snap['new_in_last_hour']}")
        print("")
        if snap["top_errors"]:
            print(f"  {'Count':>6}  {'Module':30s}  {'Message'}")
            print(f"  {'-----':>6}  {'------':30s}  {'-------'}")
            for err in snap["top_errors"][:10]:
                mod = err["module"][-30:] if len(err["module"]) > 30 else err["module"]
                msg = err["sample_message"][:60]
                scenes = ", ".join(err["affected_scenes"][:3])
                print(f"  {err['count']:6d}  {mod:30s}  {msg}")
                if verbose and scenes:
                    print(f"         scenes: {scenes}")
                if verbose and err["trace_ids"]:
                    print(f"         trace: {err['trace_ids'][0]}")
        else:
            print("  No errors recorded. System healthy.")
    except Exception as exc:
        print(f"  [!] Error aggregator unavailable: {exc}")

    # ── Performance ───────────────────────────────────────────
    print("")
    print("-- PERFORMANCE --")
    try:
        from engine.logging.benchmark import get_benchmarks, get_llm_kpis
        benchmarks = get_benchmarks()
        result["benchmarks"] = benchmarks
        if benchmarks:
            for op, stats in list(benchmarks.items())[:5]:
                if isinstance(stats, dict):
                    print(f"  {op:30s}  avg={stats.get('avg_ms',0):.0f}ms  p95={stats.get('p95_ms',0):.0f}ms  n={stats.get('count',0)}")
        else:
            print("  No benchmark data yet.")

        kpis = get_llm_kpis()
        if kpis:
            for op, stats in list(kpis.items())[:3]:
                if isinstance(stats, dict):
                    print(f"  LLM {op:25s}  avg={stats.get('avg_latency_ms',0):.0f}ms  tok/s={stats.get('tokens_per_sec',0):.1f}")
    except Exception as exc:
        print(f"  [!] Benchmarks unavailable: {exc}")

    print("")
    print("=" * 60)
    print("  End of Oracle diagnostic report")
    print("=" * 60)
    print("")

    return result
