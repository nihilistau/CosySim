"""
test_lmlink_robustness
=======================

Hermetic tests for the v1.60.0 "Living Systems" federation-robustness upgrade.

Covers:
    * ``BackoffPolicy`` — exponential growth, capping, jitter bounds, config build.
    * ``LMLinkManager.check_peer_health`` — retries transient failures with
      backoff before marking a peer unhealthy; recovers on a later attempt;
      respects ``retry=False``; surfaces non-200 as transient.
    * ``LMSClient.close`` / ``__del__`` — silent + best-effort during
      interpreter finalization (no "sys.meta_path is None" noise).

All HTTP is mocked at the boundary (``httpx.get`` for lmlink,
``_probe_peer_once`` for retry-loop logic, ``httpx.Client`` for lms_client).
No global ``data/*.json`` state is touched; every manager is constructed
fresh from a local mock config so parallel agents cannot interfere.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial robustness suite.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ── Local hermetic mock config ─────────────────────────────────────────

class _MockConfig:
    """Minimal dot-path config backed by a dict (no global state)."""

    def __init__(self, overrides: Dict[str, Any] | None = None) -> None:
        self._d: Dict[str, Any] = {
            "lmlink.enabled": True,
            "lmlink.local.name": "workstation",
            "lmlink.local.host": "localhost",
            "lmlink.local.port": 1234,
            "lmlink.local.capabilities": ["inference"],
            "lmlink.peers": [
                {
                    "name": "nuc",
                    "host": "100.64.0.5",
                    "port": 1234,
                    "capabilities": ["inference"],
                },
            ],
            "lmlink.routing.strategy": "capability_first",
            "lmlink.routing.affinity": [],
            "lmlink.routing.failover.enabled": True,
            "lmlink.routing.failover.max_retries": 2,
            "lmlink.routing.failover.retry_delay_ms": 1,
            "lmlink.routing.failover.fallback_to_local": True,
            "lmlink.health.check_interval_seconds": 60,
            "lmlink.health.timeout_ms": 5000,
            "lmlink.health.auto_reconnect": True,
            "lmlink.health.max_reconnect_attempts": 3,
            # Backoff knobs — tiny + no jitter so tests are fast/deterministic.
            "lmlink.health.backoff.base_seconds": 0.0,
            "lmlink.health.backoff.max_seconds": 0.0,
            "lmlink.health.backoff.factor": 2.0,
            "lmlink.health.backoff.max_attempts": 3,
            "lmlink.health.backoff.jitter_ratio": 0.0,
        }
        if overrides:
            self._d.update(overrides)

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)


def _make_mgr(overrides: Dict[str, Any] | None = None):
    """Construct a fresh LMLinkManager with the singleton reset."""
    import engine.lmstudio.lmlink_manager as mod

    mod._instance = None
    return mod.LMLinkManager(config=_MockConfig(overrides))


# ── BackoffPolicy ──────────────────────────────────────────────────────

class TestBackoffPolicy:
    def test_exponential_growth_no_jitter(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        p = BackoffPolicy(base_seconds=1.0, max_seconds=100.0,
                          factor=2.0, jitter_ratio=0.0)
        assert p.delay_for(0) == 1.0
        assert p.delay_for(1) == 2.0
        assert p.delay_for(2) == 4.0
        assert p.delay_for(3) == 8.0

    def test_capped_at_max(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        p = BackoffPolicy(base_seconds=1.0, max_seconds=5.0,
                          factor=10.0, jitter_ratio=0.0)
        # 1, 10→cap 5, 100→cap 5
        assert p.delay_for(0) == 1.0
        assert p.delay_for(1) == 5.0
        assert p.delay_for(2) == 5.0

    def test_negative_attempt_clamped(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        p = BackoffPolicy(base_seconds=2.0, jitter_ratio=0.0)
        assert p.delay_for(-5) == p.delay_for(0) == 2.0

    def test_jitter_within_bounds(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        p = BackoffPolicy(base_seconds=10.0, max_seconds=100.0,
                          factor=2.0, jitter_ratio=0.5)
        # Equal-jitter: fixed half + random half → delay in [5, 10].
        for attempt in range(5):
            for _ in range(50):
                d = p.delay_for(0)
                assert 5.0 <= d <= 10.0

    def test_full_jitter_bounds(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        p = BackoffPolicy(base_seconds=8.0, jitter_ratio=1.0)
        for _ in range(100):
            d = p.delay_for(0)
            assert 0.0 <= d <= 8.0

    def test_from_config(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        cfg = _MockConfig({
            "lmlink.health.backoff.base_seconds": 0.25,
            "lmlink.health.backoff.max_seconds": 12.0,
            "lmlink.health.backoff.factor": 3.0,
            "lmlink.health.backoff.max_attempts": 5,
            "lmlink.health.backoff.jitter_ratio": 0.3,
        })
        p = BackoffPolicy.from_config(cfg)
        assert p.base_seconds == 0.25
        assert p.max_seconds == 12.0
        assert p.factor == 3.0
        assert p.max_attempts == 5
        assert p.jitter_ratio == 0.3

    def test_from_config_defaults_on_missing(self):
        from engine.lmstudio.lmlink_manager import BackoffPolicy

        class _Empty:
            def get(self, key, default=None):
                return default

        p = BackoffPolicy.from_config(_Empty())
        assert p.base_seconds == 0.5
        assert p.max_attempts == 3


# ── check_peer_health retry behaviour ──────────────────────────────────

class TestHealthRetry:
    def test_manager_builds_backoff_from_config(self):
        mgr = _make_mgr({
            "lmlink.health.backoff.max_attempts": 4,
            "lmlink.health.backoff.base_seconds": 0.0,
        })
        assert mgr._backoff.max_attempts == 4

    def test_success_first_try(self):
        mgr = _make_mgr()
        peer = mgr.get_peer("nuc")
        with patch.object(mgr, "_probe_peer_once", return_value=True) as probe:
            assert mgr.check_peer_health(peer) is True
        assert probe.call_count == 1
        assert peer.reachable is True
        assert peer.consecutive_failures == 0

    def test_transient_then_recover(self):
        """First probe fails, retry succeeds → peer stays healthy, 1 fail not recorded."""
        mgr = _make_mgr()
        peer = mgr.get_peer("nuc")
        peer.consecutive_failures = 0

        seq = [ConnectionError("boom"), True]

        def _fake_probe(_peer):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        with patch.object(mgr, "_probe_peer_once", side_effect=_fake_probe):
            ok = mgr.check_peer_health(peer)

        assert ok is True
        assert peer.reachable is True
        # Recovered before exhausting attempts → no failure recorded.
        assert peer.consecutive_failures == 0

    def test_all_attempts_fail_records_single_failure(self):
        """Exhausting retries marks unhealthy ONCE (not once per attempt)."""
        mgr = _make_mgr({"lmlink.health.backoff.max_attempts": 3})
        peer = mgr.get_peer("nuc")
        peer.consecutive_failures = 0

        with patch.object(
            mgr, "_probe_peer_once",
            side_effect=ConnectionError("down"),
        ) as probe:
            ok = mgr.check_peer_health(peer)

        assert ok is False
        assert peer.reachable is False
        # 1 initial + 3 retries = 4 probes.
        assert probe.call_count == 4
        # Despite 4 failed probes, consecutive_failures increments by exactly 1.
        assert peer.consecutive_failures == 1

    def test_retry_false_single_probe(self):
        mgr = _make_mgr({"lmlink.health.backoff.max_attempts": 5})
        peer = mgr.get_peer("nuc")
        with patch.object(
            mgr, "_probe_peer_once",
            side_effect=ConnectionError("down"),
        ) as probe:
            ok = mgr.check_peer_health(peer, retry=False)
        assert ok is False
        assert probe.call_count == 1
        assert peer.consecutive_failures == 1

    def test_non_200_is_transient(self):
        """A non-200 (e.g. 503 during model load) is retried, not raised."""
        mgr = _make_mgr({"lmlink.health.backoff.max_attempts": 2})
        peer = mgr.get_peer("nuc")
        # Returns False (non-200) every time → retried then unhealthy.
        with patch.object(mgr, "_probe_peer_once", return_value=False) as probe:
            ok = mgr.check_peer_health(peer)
        assert ok is False
        assert probe.call_count == 3  # 1 + 2 retries
        assert peer.consecutive_failures == 1

    def test_backoff_sleeps_between_attempts(self):
        """Delays come from BackoffPolicy and are waited on the stop-event."""
        mgr = _make_mgr({
            "lmlink.health.backoff.max_attempts": 2,
            "lmlink.health.backoff.base_seconds": 0.0,
        })
        peer = mgr.get_peer("nuc")
        waits: List[float] = []
        orig_wait = mgr._health_stop.wait

        def _spy_wait(timeout=None):
            waits.append(timeout)
            return False  # never "stopped"

        with patch.object(mgr, "_probe_peer_once",
                          side_effect=ConnectionError("down")), \
             patch.object(mgr._health_stop, "wait", side_effect=_spy_wait):
            mgr.check_peer_health(peer)

        # 2 retries → 2 backoff waits between the 3 probes.
        assert len(waits) == 2

    def test_probe_once_mocks_httpx_boundary(self):
        """_probe_peer_once hits httpx.get and maps 200 → True."""
        mgr = _make_mgr()
        peer = mgr.get_peer("nuc")
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        with patch("httpx.get", return_value=fake_resp) as hg:
            assert mgr._probe_peer_once(peer) is True
        hg.assert_called_once()

    def test_probe_once_non_200_false(self):
        mgr = _make_mgr()
        peer = mgr.get_peer("nuc")
        fake_resp = MagicMock()
        fake_resp.status_code = 503
        with patch("httpx.get", return_value=fake_resp):
            assert mgr._probe_peer_once(peer) is False

    def test_status_exposes_backoff(self):
        mgr = _make_mgr({"lmlink.health.backoff.max_attempts": 7})
        status = mgr.get_status()
        assert "health_backoff" in status
        assert status["health_backoff"]["max_attempts"] == 7


# ── LMSClient shutdown-noise guard ─────────────────────────────────────

def _make_lms_client():
    from engine.lmstudio.inference_config import InferenceConfig
    from engine.lmstudio.lms_client import LMSClient

    cfg = _MockConfig()
    with patch(
        "engine.lmstudio.lms_client.InferenceConfig.from_yaml",
        return_value=InferenceConfig(),
    ):
        return LMSClient(base_url="http://127.0.0.1:1234", config=cfg)


class TestLmsShutdownGuard:
    def test_close_normal_path(self):
        client = _make_lms_client()
        client._client = MagicMock()
        client.close()
        client._client.close.assert_called_once()

    def test_close_silent_when_finalizing(self):
        """During finalization, close errors are swallowed with NO logging."""
        client = _make_lms_client()
        client._client = MagicMock()
        client._client.close.side_effect = RuntimeError("teardown")

        with patch.object(type(client), "_is_finalizing", return_value=True), \
             patch("engine.lmstudio.lms_client.logger") as mock_logger:
            client.close()  # must not raise

        mock_logger.debug.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()

    def test_close_logs_when_not_finalizing(self):
        client = _make_lms_client()
        client._client = MagicMock()
        client._client.close.side_effect = RuntimeError("oops")

        with patch.object(type(client), "_is_finalizing", return_value=False), \
             patch("engine.lmstudio.lms_client.logger") as mock_logger:
            client.close()

        assert mock_logger.debug.called

    def test_del_silent_when_finalizing(self):
        client = _make_lms_client()
        client._client = MagicMock()
        client._client.close.side_effect = RuntimeError("teardown")

        with patch.object(type(client), "_is_finalizing", return_value=True), \
             patch("engine.lmstudio.lms_client.logger") as mock_logger:
            client.__del__()  # must not raise

        mock_logger.debug.assert_not_called()

    def test_del_handles_missing_client_attr(self):
        """__del__ must not blow up if _client was never set (partial init)."""
        client = _make_lms_client()
        # Simulate a half-constructed object.
        del client._client
        with patch.object(type(client), "_is_finalizing", return_value=True):
            client.__del__()  # no AttributeError

    def test_is_finalizing_reflects_sys(self):
        from engine.lmstudio.lms_client import LMSClient

        # Normal runtime → not finalizing.
        assert LMSClient._is_finalizing() in (True, False)
        with patch.object(sys, "is_finalizing", return_value=True):
            assert LMSClient._is_finalizing() is True
        with patch.object(sys, "is_finalizing", return_value=False):
            assert LMSClient._is_finalizing() is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
