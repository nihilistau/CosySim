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

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Observability hardening: bounded (LRU) flood_guard so
                            a flood of unique fingerprints can't grow memory
                            without bound; error-callback exceptions now logged
                            at DEBUG with a trace instead of silent pass;
                            default high-visibility error-rate alert hook wired
                            into the aggregator; ensure_initialized() now runs a
                            post-install self-check (handlers_installed()) that
                            confirms the structured-logging + Oracle handlers
                            actually attached, warning loudly if not. All caps
                            configurable via get_config() with safe defaults.
    v1.57.0 [2026-03-26] — File Search + Context Cache metrics in diagnose() output (GEMINI SERVICES section)
    v1.56.0 [2026-03-26] — Nexus KB metrics + LMStudio model health in diagnose() output
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
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Module state ───────────────────────────────────────────────────────────

_initialized = False
_init_lock = threading.Lock()
_error_callbacks: List[Callable[[Dict[str, Any]], None]] = []

# v1.60.0 [2026-06-13] — Records the result of the post-init self-check so
# tests / diagnose() / scripts can confirm handlers actually attached.
_self_check: Dict[str, Any] = {}


def _cfg(path: str, default: Any) -> Any:
    """Read a config value, tolerating a missing/unloadable config layer.

    Args:
        path: Dot-notation config path.
        default: Fallback when config is unavailable or the key is unset.

    Returns:
        The configured value or ``default``.
    """
    try:
        from engine.config import get_config

        val = get_config().get(path, default)
        return default if val is None else val
    except Exception:
        return default


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

        structured_ok = False
        cosy_ok = False
        oracle_ok = False

        # 1. Structured logger → SQLite + JSONL
        try:
            from engine.observability.structured_logger import install_root_handler
            install_root_handler()
            structured_ok = True
        except Exception as exc:
            # v1.60.0 — Surface (don't silently suppress) init failures: stderr
            # for visibility AND the logging pipeline for capture/aggregation.
            logger.warning(
                "[Oracle] StructuredLogger init failed (operation=init_structured): %s", exc
            )
            print(f"[Oracle] WARNING: StructuredLogger init failed: {exc}", file=sys.stderr)

        # 2. CosyLogger ring buffer → Phone panel
        try:
            from engine.logging.cosy_logger import install_logger
            install_logger()
            cosy_ok = True
        except Exception as exc:
            logger.warning(
                "[Oracle] CosyLogger init failed (operation=init_cosy): %s", exc
            )
            print(f"[Oracle] WARNING: CosyLogger init failed: {exc}", file=sys.stderr)

        # 3. Oracle error handler → ErrorAggregator + callbacks
        try:
            root = logging.getLogger()
            root.addHandler(_OracleHandler())
            oracle_ok = True
        except Exception as exc:
            logger.error(
                "[Oracle] OracleHandler install failed (operation=init_oracle): %s", exc
            )
            print(f"[Oracle] WARNING: OracleHandler init failed: {exc}", file=sys.stderr)

        # 4. v1.60.0 — Wire the default high-visibility error-rate alert hook so
        #    a sustained error storm gets ONE loud line, not silence.
        try:
            from engine.observability.error_aggregator import get_error_aggregator
            get_error_aggregator().register_alert_hook(_default_rate_alert_hook)
        except Exception as exc:
            logger.warning(
                "[Oracle] Rate-alert hook wiring failed (operation=init_alert): %s", exc
            )

        _initialized = True

    # 5. v1.60.0 — Post-install self-check (outside the init lock): confirm the
    #    handlers we believe we installed are actually attached to the root
    #    logger. A silent no-op install is exactly the failure mode the audit
    #    flagged — so we verify and warn loudly if reality disagrees.
    check = _run_self_check(structured_ok=structured_ok, cosy_ok=cosy_ok, oracle_ok=oracle_ok)
    if not check.get("ok"):
        logger.warning(
            "[Oracle] Self-check FAILED (operation=self_check): %s",
            check.get("problems"),
        )
        print(
            f"[Oracle] WARNING: handler self-check failed: {check.get('problems')}",
            file=sys.stderr,
        )


# ──── Self-check ─────────────────────────────────────────────────────────────
# CONNECTS: root logger handlers, structured_logger._root_handler_installed
# CALLED BY: ensure_initialized(), handlers_installed(), diagnose(), tests
# EMITS: dict describing which handlers attached + any problems

def _run_self_check(
    structured_ok: bool = True,
    cosy_ok: bool = True,
    oracle_ok: bool = True,
) -> Dict[str, Any]:
    """Verify that the structured-logging + Oracle handlers actually installed.

    Inspects the root logger for an attached ``_OracleHandler`` and consults the
    structured logger's install flag, rather than trusting that the install
    calls had any effect. The result is cached in module state.

    Args:
        structured_ok: Whether the structured-logger install call succeeded.
        cosy_ok: Whether the CosyLogger install call succeeded.
        oracle_ok: Whether the OracleHandler install call succeeded.

    Returns:
        Dict with ``ok`` (bool), per-handler booleans, and a ``problems`` list.
    """
    problems: List[str] = []

    root = logging.getLogger()
    oracle_attached = any(isinstance(h, _OracleHandler) for h in root.handlers)
    if not oracle_attached:
        problems.append("OracleHandler not attached to root logger")

    structured_attached = False
    try:
        from engine.observability import structured_logger as _sl

        structured_attached = bool(getattr(_sl, "_root_handler_installed", False))
    except Exception as exc:  # pragma: no cover - import guard
        problems.append(f"structured_logger introspection failed: {exc}")
    if structured_ok and not structured_attached:
        problems.append("StructuredLogger root handler flag not set")

    result: Dict[str, Any] = {
        "ok": not problems,
        "oracle_handler_attached": oracle_attached,
        "structured_handler_installed": structured_attached,
        "structured_install_ok": structured_ok,
        "cosy_install_ok": cosy_ok,
        "oracle_install_ok": oracle_ok,
        "problems": problems,
        "checked_at": time.time(),
    }
    _self_check.clear()
    _self_check.update(result)
    return result


def handlers_installed() -> Dict[str, Any]:
    """Return the latest Oracle self-check result (running one if needed).

    Confirms the structured-logging and Oracle ERROR handlers are actually
    attached. Useful from ``diagnose()``, health endpoints, and tests.

    Returns:
        The self-check dict (see :func:`_run_self_check`).
    """
    if not _self_check:
        return _run_self_check()
    return dict(_self_check)


# ──── Default rate-alert hook ────────────────────────────────────────────────
# CONNECTS: ErrorAggregator.register_alert_hook, _error_callbacks
# CALLED BY: ErrorAggregator._dispatch_alert (throttled)
# EMITS: one CRITICAL log line + a synthetic 'rate_alert' callback event

def _default_rate_alert_hook(payload: Dict[str, Any]) -> None:
    """High-visibility handler for a tripped error-rate threshold.

    Logs a single CRITICAL line (already throttled by the aggregator) and fans
    the alert out to registered error callbacks as a ``rate_alert`` event so the
    Oracle dashboard can surface it. Never raises.

    Args:
        payload: Alert payload from the aggregator.
    """
    try:
        rate = payload.get("rate")
        window = payload.get("window_seconds")
        threshold = payload.get("threshold")
        uniq = payload.get("unique_fingerprints")
        logger.critical(
            "[Oracle] ERROR-RATE ALERT (operation=rate_alert): %s errors in %ss "
            "exceeds threshold %s across %s fingerprints",
            rate, window, threshold, uniq,
        )
        event = {
            "type": "rate_alert",
            "level": "CRITICAL",
            "module": "engine.observability.oracle",
            "scene": "",
            "message": (
                f"Error-rate alert: {rate} errors in {window}s "
                f"(threshold {threshold})"
            ),
            "rate_alert": payload,
            "timestamp": payload.get("timestamp", time.time()),
        }
        for cb in list(_error_callbacks):
            try:
                cb(event)
            except Exception as exc:
                logger.debug(
                    "[Oracle] rate_alert callback raised (operation=rate_alert_cb): %s", exc
                )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[Oracle] rate-alert hook failed (operation=rate_alert): %s", exc)


# ──── Oracle Error Handler ───────────────────────────────────────────────────

class _OracleHandler(logging.Handler):
    """Custom handler that fires on ERROR+ to aggregate and surface errors.

    Zero overhead on DEBUG/INFO/WARNING — only activates for ERROR and CRITICAL.
    Cost per ERROR: ~0.2ms (fingerprint hash + dict lookup + callback dispatch).

    CONNECTS: ErrorAggregator, _error_callbacks, Oracle dashboard SocketIO
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        # v1.60.0 — Bounded LRU flood_guard (audit fix: unbounded growth under
        # many unique fingerprints). OrderedDict + move_to_end gives O(1) LRU;
        # the oldest entry is evicted once the cap is hit, so memory is capped
        # regardless of fingerprint cardinality.
        self._flood_guard: "OrderedDict[str, float]" = OrderedDict()  # fp → last-emitted ts
        self._FLOOD_COOLDOWN: float = float(
            _cfg("observability.oracle.flood_cooldown_sec", 5.0)
        )  # Don't fire callback for same fingerprint within this window.
        self._FLOOD_MAX_KEYS: int = int(
            _cfg("observability.oracle.flood_guard_max_keys", 1000)
        )  # Hard cap on retained fingerprints in the flood guard.
        self._lock = threading.Lock()  # Guards _flood_guard mutation.

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
            # Flood guard: don't fire for same fingerprint within cooldown.
            now = time.time()
            should_fire = False
            with self._lock:
                last = self._flood_guard.get(fp)
                if last is None or (now - last) > self._FLOOD_COOLDOWN:
                    should_fire = True
                    self._flood_guard[fp] = now
                    # v1.60.0 — LRU touch so the hottest fingerprints survive eviction.
                    self._flood_guard.move_to_end(fp, last=True)

                    # v1.60.0 — Time-based prune (stale beyond 5 min) AND hard
                    # size cap via LRU eviction. Either alone is insufficient: a
                    # burst of >cap distinct fingerprints inside the window would
                    # still blow memory without the size cap.
                    if len(self._flood_guard) > self._FLOOD_MAX_KEYS:
                        cutoff = now - 300
                        self._flood_guard = OrderedDict(
                            (k, v) for k, v in self._flood_guard.items() if v > cutoff
                        )
                        while len(self._flood_guard) > self._FLOOD_MAX_KEYS:
                            self._flood_guard.popitem(last=False)  # drop least-recent

            if should_fire:
                event = {
                    "fingerprint": fp,
                    "level": record.levelname,
                    "module": module,
                    "scene": scene,
                    "message": message[:500],
                    "error_type": error_type,
                    "timestamp": now,
                }
                for cb in list(_error_callbacks):
                    try:
                        cb(event)
                    except Exception as exc:
                        # v1.60.0 — Audit fix: log (don't silently pass) a raising
                        # callback. DEBUG keeps it non-spammy while preserving a
                        # trace; the handler still never crashes.
                        logger.debug(
                            "[Oracle] error callback raised (operation=error_cb): %s",
                            exc,
                            exc_info=True,
                        )
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


# ──── Nexus & LMStudio Metrics Helpers ───────────────────────────────────────

# v1.56.0 [2026-03-26] — Nexus knowledge base metrics for Oracle dashboard
# CONNECTS: NexusClient, engine.nexus.client
# CALLED BY: diagnose()
# EMITS: dict with availability, entry/qa/session counts
def _nexus_metrics() -> Dict[str, Any]:
    """Fetch Nexus metrics for Oracle dashboard.

    Returns:
        Dict with ``available`` flag and entry/qa/session counts,
        or just ``available: False`` if unreachable.
    """
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if client.is_available(timeout=3):
            stats = client.stats()
            return {
                "available": True,
                "entries": stats.get("total_entries", 0),
                "qa_pairs": stats.get("total_qa", 0),
                "sessions": stats.get("total_sessions", 0),
                "rules": stats.get("total_rules", 0),
                "prompts": stats.get("total_prompts", 0),
            }
    except Exception:
        pass
    return {"available": False}


# v1.56.0 [2026-03-26] — LMStudio per-model health for Oracle dashboard
# CONNECTS: ServerController.get_model_health()
# CALLED BY: diagnose()
# EMITS: dict with model list, VRAM totals, reachability
def _lmstudio_model_health() -> Dict[str, Any]:
    """Fetch LMStudio model health for Oracle dashboard.

    Returns:
        Dict from ServerController.get_model_health(), or fallback dict.
    """
    try:
        from engine.lmstudio.server_controller import get_server_controller
        ctrl = get_server_controller()
        return ctrl.get_model_health()
    except Exception:
        pass
    return {"server_reachable": False, "models": []}


# ──── Gemini Service Metrics ──────────────────────────────────────────────────

# v1.57.0 [2026-03-26] — File Search store stats for Oracle dashboard
# CONNECTS: FileSearchClient (engine.integrations.file_search_client)
# CALLED BY: diagnose()
# EMITS: dict with availability, store count, store names
def _file_search_metrics() -> Dict[str, Any]:
    """Fetch Google File Search store stats.

    Returns:
        Dict with ``available`` flag, store count, and store display names,
        or just ``available: False`` if unreachable.
    """
    try:
        from engine.integrations.file_search_client import get_file_search_client
        client = get_file_search_client()
        stores = client.list_stores()
        return {
            "available": True,
            "stores": len(stores),
            "store_names": [s.get("display_name", "") for s in stores],
        }
    except Exception:
        return {"available": False}


# v1.57.0 [2026-03-26] — Context cache status for Oracle dashboard
# CONNECTS: ContextCacheClient (engine.integrations.context_cache_client)
# CALLED BY: diagnose()
# EMITS: dict with cached flag, cache name, TTL remaining
def _context_cache_metrics() -> Dict[str, Any]:
    """Fetch Gemini context cache status.

    Returns:
        Dict from ContextCacheClient.status(), or fallback dict.
    """
    try:
        from engine.integrations.context_cache_client import get_context_cache
        cache = get_context_cache()
        return cache.status()
    except Exception:
        return {"cached": False}


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

    # v1.60.0 — Surface the handler self-check so a broken observability
    # pipeline is visible in the very report meant to diagnose the system.
    try:
        result["self_check"] = handlers_installed()
    except Exception as exc:  # pragma: no cover - defensive
        result["self_check"] = {"ok": False, "problems": [str(exc)]}

    print("")
    print("=" * 60)
    print("  ORACLE DIAGNOSTIC REPORT")
    print("  " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # ── Self-check ────────────────────────────────────────────
    # v1.60.0 — Confirm the observability handlers actually attached.
    sc = result.get("self_check", {})
    if sc:
        if sc.get("ok"):
            print("")
            print("-- OBSERVABILITY SELF-CHECK --")
            print("  [OK] Structured + Oracle handlers installed")
        else:
            print("")
            print("-- OBSERVABILITY SELF-CHECK --")
            print("  [!!] Handler self-check FAILED:")
            for prob in sc.get("problems", []):
                print(f"       - {prob}")

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

    # ── Nexus Knowledge Base ─────────────────────────────────
    # v1.56.0 [2026-03-26] — Nexus KB metrics in Oracle diagnostic
    print("")
    print("-- NEXUS KNOWLEDGE BASE --")
    try:
        nexus = _nexus_metrics()
        result["nexus"] = nexus
        if nexus.get("available"):
            print(f"  [OK] Nexus KMS           UP")
            print(f"  Entries: {nexus.get('entries', 0)}  |  "
                  f"Q&A: {nexus.get('qa_pairs', 0)}  |  "
                  f"Sessions: {nexus.get('sessions', 0)}")
            if verbose:
                print(f"  Rules: {nexus.get('rules', 0)}  |  "
                      f"Prompts: {nexus.get('prompts', 0)}")
        else:
            print("  [!!] Nexus KMS           DOWN")
    except Exception as exc:
        print(f"  [!] Nexus metrics unavailable: {exc}")

    # ── LMStudio Model Health ────────────────────────────────
    # v1.56.0 [2026-03-26] — Per-model VRAM/health in Oracle diagnostic
    print("")
    print("-- LMSTUDIO MODELS --")
    try:
        model_health = _lmstudio_model_health()
        result["lmstudio_models"] = model_health
        if model_health.get("server_reachable"):
            count = model_health.get("model_count", 0)
            vram = model_health.get("total_vram_mb", 0)
            print(f"  Models loaded: {count}  |  Est. VRAM: {vram:.0f}MB")
            for m in model_health.get("models", []):
                req_count = m.get("request_count", 0)
                idle = m.get("idle_seconds", 0)
                print(f"    {m['id'][:40]:40s}  "
                      f"ctx={m.get('context_length', 0)}  "
                      f"vram={m.get('vram_mb', 0):.0f}MB  "
                      f"reqs={req_count}  "
                      f"idle={idle:.0f}s")
        else:
            print("  [!!] LMStudio server not reachable")
            err = model_health.get("error", "")
            if err:
                print(f"       {err[:80]}")
    except Exception as exc:
        print(f"  [!] LMStudio model health unavailable: {exc}")

    # ── Gemini Services ──────────────────────────────────────
    # v1.57.0 [2026-03-26] — File Search + Context Cache in Oracle diagnostic
    print("")
    print("-- GEMINI SERVICES --")
    try:
        fs_metrics = _file_search_metrics()
        result["file_search"] = fs_metrics
        if fs_metrics.get("available"):
            store_count = fs_metrics.get("stores", 0)
            names = ", ".join(fs_metrics.get("store_names", [])[:5]) or "(none)"
            print(f"  [OK] File Search         UP  ({store_count} store(s))")
            if verbose:
                print(f"       Stores: {names}")
        else:
            print("  [--] File Search         UNAVAILABLE")
    except Exception as exc:
        print(f"  [!] File Search metrics unavailable: {exc}")

    try:
        cc_metrics = _context_cache_metrics()
        result["context_cache"] = cc_metrics
        if cc_metrics.get("cached"):
            cache_name = cc_metrics.get("cache_name", "unknown")
            ttl_remaining = cc_metrics.get("ttl_remaining_seconds", 0)
            print(f"  [OK] Context Cache       ACTIVE  (TTL {ttl_remaining}s remaining)")
            if verbose:
                print(f"       Cache: {cache_name}")
        else:
            print("  [--] Context Cache       INACTIVE")
    except Exception as exc:
        print(f"  [!] Context Cache metrics unavailable: {exc}")

    print("")
    print("=" * 60)
    print("  End of Oracle diagnostic report")
    print("=" * 60)
    print("")

    return result
