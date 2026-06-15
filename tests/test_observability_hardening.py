"""
Observability Hardening Tests — v1.60.0 "Living Systems"
========================================================

Covers the v1.60.0 hardening of the Oracle observability subsystem:

  1. ErrorAggregator bounds its bucket store (LRU size cap) so a flood of
     unique fingerprints cannot grow memory without bound.
  2. ErrorAggregator fires a single THROTTLED alert when the error rate
     exceeds a configurable threshold, then re-arms after a cooldown.
  3. Misbehaving alert hooks are isolated — a raising hook never crashes
     ingest, and other hooks still fire.
  4. Oracle's _OracleHandler bounds its flood_guard (LRU) under many unique
     fingerprints and logs (does not silently swallow) a raising error callback.
  5. Oracle's handler self-check confirms the structured + Oracle handlers
     actually installed.

All tests are HERMETIC: they construct fresh ErrorAggregator / _OracleHandler
instances (never the module singleton) and do not touch data/*.json or the
shared root-logger pipeline destructively.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial hardening test suite.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from engine.observability.error_aggregator import ErrorAggregator
from engine.observability import oracle as oracle_mod


# ──── Helpers ────────────────────────────────────────────────────────────────

def _make_record(msg: str, name: str = "engine.test.module") -> logging.LogRecord:
    """Build a bare ERROR LogRecord for feeding _OracleHandler.emit directly."""
    return logging.LogRecord(
        name=name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


# ──── 1. Bounded bucket growth (LRU size cap) ────────────────────────────────

def test_aggregator_bounds_unique_fingerprints() -> None:
    """A flood of distinct messages must not grow buckets past max_buckets."""
    agg = ErrorAggregator(max_buckets=50, alert_threshold=0)  # alerts off
    for i in range(500):
        agg.ingest(message=f"[scene] unique failure variant {i} of kind XYZ",
                   module=f"engine.mod.{i}", level="ERROR")

    snap = agg.snapshot()
    assert snap["total_unique"] <= 50, snap["total_unique"]
    # Every ingest was counted even though buckets were evicted.
    assert snap["total_count"] == 500
    assert snap["buckets_evicted"] >= 450
    assert snap["max_buckets"] == 50


def test_aggregator_lru_keeps_hot_fingerprint() -> None:
    """The most-recently-seen fingerprint survives eviction; a cold one is dropped."""
    agg = ErrorAggregator(max_buckets=10, alert_threshold=0)
    hot_fp = agg.ingest(message="[scene] the HOT recurring error",
                        module="engine.hot", level="ERROR")

    # Flood with cold uniques, but keep touching the hot one so it stays MRU.
    for i in range(100):
        agg.ingest(message=f"[scene] cold transient {i}",
                   module=f"engine.cold.{i}", level="ERROR")
        if i % 3 == 0:
            agg.ingest(message="[scene] the HOT recurring error",
                       module="engine.hot", level="ERROR")

    top = agg.get_top_errors(50)
    fps = {b["fingerprint"] for b in top}
    assert hot_fp in fps, "Hot fingerprint was evicted despite being recently seen"


# ──── 2. Throttled rate alerting ─────────────────────────────────────────────

def test_rate_alert_fires_once_when_threshold_exceeded() -> None:
    """Exceeding the threshold inside the window fires exactly one throttled alert."""
    received: List[Dict[str, Any]] = []
    agg = ErrorAggregator(
        max_buckets=1000,
        alert_threshold=20,
        alert_window_sec=300,
        alert_cooldown_sec=300,
    )
    agg.register_alert_hook(lambda payload: received.append(payload))

    for i in range(25):
        agg.ingest(message=f"[scene] flooding error {i % 4}",
                   module="engine.flood", level="ERROR")

    assert len(received) == 1, f"expected one throttled alert, got {len(received)}"
    payload = received[0]
    assert payload["rate"] >= 20
    assert payload["threshold"] == 20
    assert payload["window_seconds"] == 300
    assert payload["top_errors"], "alert should include top_errors"

    snap = agg.snapshot()
    assert snap["alerts_fired"] == 1


def test_rate_alert_does_not_fire_below_threshold() -> None:
    """Staying under the threshold fires no alert."""
    received: List[Dict[str, Any]] = []
    agg = ErrorAggregator(alert_threshold=100, alert_window_sec=300, alert_cooldown_sec=1)
    agg.register_alert_hook(lambda payload: received.append(payload))

    for i in range(10):
        agg.ingest(message=f"[scene] mild error {i}", module="engine.mild", level="ERROR")

    assert received == []
    assert agg.snapshot()["alerts_fired"] == 0


def test_rate_alert_throttled_by_cooldown() -> None:
    """A second burst inside the cooldown must NOT produce a second alert."""
    received: List[Dict[str, Any]] = []
    agg = ErrorAggregator(alert_threshold=10, alert_window_sec=300, alert_cooldown_sec=300)
    agg.register_alert_hook(lambda payload: received.append(payload))

    for i in range(15):
        agg.ingest(message="[scene] burst one", module="engine.b1", level="ERROR")
    for i in range(15):
        agg.ingest(message="[scene] burst two", module="engine.b2", level="ERROR")

    assert len(received) == 1, "cooldown should throttle the second burst"


def test_alert_threshold_zero_disables_alerts() -> None:
    """A threshold of 0 (disabled) never fires, even under heavy load."""
    received: List[Dict[str, Any]] = []
    agg = ErrorAggregator(alert_threshold=0)
    agg.register_alert_hook(lambda payload: received.append(payload))
    for i in range(200):
        agg.ingest(message=f"[scene] err {i}", module="engine.x", level="ERROR")
    assert received == []


# ──── 3. Alert-hook isolation ────────────────────────────────────────────────

def test_raising_alert_hook_does_not_break_ingest() -> None:
    """A hook that raises must not crash ingest, and other hooks still fire."""
    good: List[Dict[str, Any]] = []

    def bad_hook(_payload: Dict[str, Any]) -> None:
        raise RuntimeError("boom")

    agg = ErrorAggregator(alert_threshold=5, alert_window_sec=300, alert_cooldown_sec=300)
    agg.register_alert_hook(bad_hook)
    agg.register_alert_hook(lambda payload: good.append(payload))

    # Should not raise despite bad_hook blowing up.
    for i in range(10):
        agg.ingest(message="[scene] trip it", module="engine.trip", level="ERROR")

    assert len(good) == 1, "good hook should still receive the alert"


# ──── 4. _OracleHandler flood-guard bound + callback isolation ────────────────

def test_oracle_handler_flood_guard_bounded() -> None:
    """flood_guard must stay capped under a flood of unique fingerprints."""
    handler = oracle_mod._OracleHandler()
    handler._FLOOD_MAX_KEYS = 50  # tighten for the test

    for i in range(1000):
        handler.emit(_make_record(f"[scene] distinct boom number {i}",
                                  name=f"engine.distinct.{i}"))

    assert len(handler._flood_guard) <= 50, len(handler._flood_guard)


def test_oracle_handler_logs_raising_callback(caplog: Any) -> None:
    """A raising error callback is logged at DEBUG, not silently swallowed."""
    def bad_cb(_event: Dict[str, Any]) -> None:
        raise ValueError("callback exploded")

    oracle_mod.register_error_callback(bad_cb)
    try:
        handler = oracle_mod._OracleHandler()
        with caplog.at_level(logging.DEBUG, logger="engine.observability.oracle"):
            handler.emit(_make_record("[scene] something failed badly"))

        assert any(
            "error callback raised" in rec.getMessage()
            for rec in caplog.records
        ), "raising callback should be logged, not swallowed"
    finally:
        oracle_mod.unregister_error_callback(bad_cb)


def test_oracle_handler_emit_never_raises() -> None:
    """emit() must be exception-safe even with a broken callback present."""
    def bad_cb(_event: Dict[str, Any]) -> None:
        raise RuntimeError("nope")

    oracle_mod.register_error_callback(bad_cb)
    try:
        handler = oracle_mod._OracleHandler()
        # Must not propagate.
        handler.emit(_make_record("[scene] boom"))
    finally:
        oracle_mod.unregister_error_callback(bad_cb)


# ──── 5. Handler self-check ──────────────────────────────────────────────────

def test_self_check_reports_after_init() -> None:
    """After ensure_initialized, the self-check confirms handlers attached."""
    oracle_mod.ensure_initialized()
    check = oracle_mod.handlers_installed()
    assert check["oracle_handler_attached"] is True
    assert check["ok"] is True, check.get("problems")


def test_self_check_detects_missing_oracle_handler() -> None:
    """If no _OracleHandler is on the root logger, the self-check flags it."""
    root = logging.getLogger()
    saved = [h for h in root.handlers if isinstance(h, oracle_mod._OracleHandler)]
    for h in saved:
        root.removeHandler(h)
    try:
        check = oracle_mod._run_self_check()
        assert check["oracle_handler_attached"] is False
        assert check["ok"] is False
        assert any("OracleHandler" in p for p in check["problems"])
    finally:
        for h in saved:
            root.addHandler(h)
