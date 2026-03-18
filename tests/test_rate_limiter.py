"""
Tests for engine.security.rate_limiter — 45+ tests covering:
- TokenBucket fill / drain / refill logic
- acquire() blocking and timeout
- try_acquire() non-blocking
- burst_multiplier
- backpressure_active
- queue max-depth → RateLimitExceeded
- RateLimiter with all 8 default services
- configure_service / persist / get_status
- get_metrics
- release_all
- @rate_limited decorator
- Auto-create for unknown services
"""

import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.security.rate_limiter import (
    DEFAULT_CONFIGS,
    RateLimitConfig,
    RateLimitExceeded,
    RateLimitResult,
    RateLimiter,
    TokenBucket,
    get_rate_limiter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rl(tmp_path: Path) -> RateLimiter:
    """Fresh RateLimiter with isolated temp DB."""
    return RateLimiter(db_path=str(tmp_path / "rate.db"))


def _make_bucket(capacity: float, refill_rate: float, burst: float = 1.0) -> TokenBucket:
    """Helper: create a standalone TokenBucket."""
    config = RateLimitConfig(
        service_name="test",
        capacity=capacity,
        refill_rate=refill_rate,
        burst_multiplier=burst,
    )
    return TokenBucket(config)


# ---------------------------------------------------------------------------
# RateLimitConfig
# ---------------------------------------------------------------------------


class TestRateLimitConfig:
    def test_effective_capacity_no_burst(self):
        cfg = RateLimitConfig("svc", capacity=10, refill_rate=1.0)
        assert cfg.effective_capacity == 10.0

    def test_effective_capacity_with_burst(self):
        cfg = RateLimitConfig("svc", capacity=10, refill_rate=1.0, burst_multiplier=1.5)
        assert cfg.effective_capacity == 15.0

    def test_defaults(self):
        cfg = RateLimitConfig("svc", capacity=5, refill_rate=1.0)
        assert cfg.backpressure_threshold == 0.2
        assert cfg.max_queue_depth == 50


# ---------------------------------------------------------------------------
# RateLimitResult
# ---------------------------------------------------------------------------


class TestRateLimitResult:
    def test_creation_allowed(self):
        r = RateLimitResult(allowed=True, tokens_remaining=9.0)
        assert r.allowed is True
        assert r.tokens_remaining == 9.0
        assert r.wait_seconds == 0.0
        assert r.queued is False

    def test_creation_denied(self):
        r = RateLimitResult(allowed=False, tokens_remaining=0.0, wait_seconds=2.5)
        assert r.allowed is False
        assert r.wait_seconds == 2.5


# ---------------------------------------------------------------------------
# RateLimitExceeded exception
# ---------------------------------------------------------------------------


class TestRateLimitExceeded:
    def test_is_exception(self):
        exc = RateLimitExceeded("too fast")
        assert isinstance(exc, Exception)
        assert "too fast" in str(exc)


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_initial_full(self):
        bucket = _make_bucket(10, 1.0)
        try:
            assert bucket.tokens == pytest.approx(10.0, abs=0.1)
        finally:
            bucket.stop()

    def test_try_acquire_success(self):
        bucket = _make_bucket(10, 1.0)
        try:
            result = bucket.try_acquire(tokens=3)
            assert result.allowed is True
            assert result.tokens_remaining == pytest.approx(7.0, abs=0.1)
        finally:
            bucket.stop()

    def test_try_acquire_insufficient(self):
        bucket = _make_bucket(2, 1.0)
        try:
            result = bucket.try_acquire(tokens=5)
            assert result.allowed is False
            assert result.wait_seconds > 0
        finally:
            bucket.stop()

    def test_try_acquire_depletes_tokens(self):
        bucket = _make_bucket(5, 0.1)
        try:
            bucket.try_acquire(tokens=3)
            assert bucket.tokens == pytest.approx(2.0, abs=0.2)
        finally:
            bucket.stop()

    def test_try_acquire_to_zero(self):
        bucket = _make_bucket(5, 0.1)
        try:
            result = bucket.try_acquire(tokens=5)
            assert result.allowed is True
            assert bucket.tokens == pytest.approx(0.0, abs=0.1)
        finally:
            bucket.stop()

    def test_burst_multiplier_increases_capacity(self):
        bucket = _make_bucket(10, 1.0, burst=2.0)
        try:
            assert bucket.config.effective_capacity == pytest.approx(20.0, abs=0.1)
            result = bucket.try_acquire(tokens=15)
            assert result.allowed is True
        finally:
            bucket.stop()

    def test_refill_over_time(self):
        """Tokens refill to capacity over time."""
        bucket = _make_bucket(10, 100.0)  # 100 tokens/s — fast refill
        try:
            bucket.try_acquire(tokens=10)
            assert bucket.tokens == pytest.approx(0.0, abs=0.5)
            time.sleep(0.15)  # ~15 tokens at 100/s
            assert bucket.tokens > 1.0
        finally:
            bucket.stop()

    def test_tokens_capped_at_effective_capacity(self):
        bucket = _make_bucket(10, 100.0)
        try:
            time.sleep(0.1)
            assert bucket.tokens <= bucket.config.effective_capacity + 0.5
        finally:
            bucket.stop()

    def test_backpressure_active_when_low(self):
        bucket = _make_bucket(10, 0.01)
        try:
            bucket.try_acquire(tokens=9.5)  # leaves < 20% of 10
            assert bucket.backpressure_active() is True
        finally:
            bucket.stop()

    def test_backpressure_inactive_when_full(self):
        bucket = _make_bucket(10, 1.0)
        try:
            assert bucket.backpressure_active() is False
        finally:
            bucket.stop()

    def test_release_all_refills(self):
        bucket = _make_bucket(10, 0.001)
        try:
            bucket.try_acquire(tokens=10)
            assert bucket.tokens == pytest.approx(0.0, abs=0.1)
            bucket.release_all()
            assert bucket.tokens == pytest.approx(10.0, abs=0.1)
        finally:
            bucket.stop()

    def test_queue_depth_starts_at_zero(self):
        bucket = _make_bucket(10, 1.0)
        try:
            assert bucket.queue_depth == 0
        finally:
            bucket.stop()

    def test_acquire_blocking_succeeds(self):
        """Blocking acquire returns True when tokens become available."""
        bucket = _make_bucket(5, 50.0)  # Fast refill
        try:
            bucket.try_acquire(tokens=5)  # Drain
            result = bucket.acquire(tokens=1, timeout=2.0)
            assert result.allowed is True
        finally:
            bucket.stop()

    def test_acquire_timeout_returns_not_allowed(self):
        """Blocking acquire respects timeout when tokens never arrive."""
        bucket = _make_bucket(5, 0.0001)  # Extremely slow refill
        try:
            bucket.try_acquire(tokens=5)  # Drain
            result = bucket.acquire(tokens=5, timeout=0.2)
            assert result.allowed is False
        finally:
            bucket.stop()

    def test_queue_max_depth_raises(self):
        """Enqueueing beyond max_queue_depth raises RateLimitExceeded."""
        cfg = RateLimitConfig(
            "svc", capacity=1, refill_rate=0.0001, max_queue_depth=2
        )
        bucket = TokenBucket(cfg)
        try:
            bucket.try_acquire(tokens=1)  # Drain
            # Fill up the queue
            threads = []
            results = []

            def _try(timeout=5.0):
                try:
                    r = bucket.acquire(tokens=1, timeout=timeout)
                    results.append(("ok", r))
                except RateLimitExceeded as exc:
                    results.append(("exceeded", exc))

            for _ in range(4):
                t = threading.Thread(target=_try)
                t.daemon = True
                t.start()
                threads.append(t)
                time.sleep(0.05)

            # At least some threads should have hit the limit
            time.sleep(0.3)
            exceeded = [r for r in results if r[0] == "exceeded"]
            assert len(exceeded) >= 1
        finally:
            bucket.stop()
            for t in threads:
                t.join(timeout=1.0)


# ---------------------------------------------------------------------------
# Default service configs
# ---------------------------------------------------------------------------


class TestDefaultConfigs:
    @pytest.mark.parametrize(
        "service",
        ["lmstudio", "nlm", "aistudio", "gemini", "comfyui", "tts", "scheduler", "nexus"],
    )
    def test_default_config_exists(self, service):
        assert service in DEFAULT_CONFIGS

    def test_lmstudio_config(self):
        cfg = DEFAULT_CONFIGS["lmstudio"]
        assert cfg.capacity == 10
        assert cfg.refill_rate == 2.0
        assert cfg.burst_multiplier == 1.5

    def test_nlm_config(self):
        cfg = DEFAULT_CONFIGS["nlm"]
        assert cfg.capacity == 50
        assert cfg.burst_multiplier == 2.0

    def test_comfyui_config(self):
        cfg = DEFAULT_CONFIGS["comfyui"]
        assert cfg.capacity == 5
        assert cfg.refill_rate == 0.5

    def test_nexus_config(self):
        cfg = DEFAULT_CONFIGS["nexus"]
        assert cfg.capacity == 200

    def test_all_8_services_present(self):
        assert len(DEFAULT_CONFIGS) == 8


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_default_services_registered(self, rl):
        for service in DEFAULT_CONFIGS:
            assert service in rl._buckets

    def test_acquire_allowed(self, rl):
        result = rl.acquire("nexus", tokens=1)
        assert result.allowed is True

    def test_try_acquire_success(self, rl):
        result = rl.try_acquire("nexus", tokens=1)
        assert result.allowed is True

    def test_try_acquire_fail_when_empty(self, rl):
        # Drain the comfyui bucket (only 5 tokens)
        for _ in range(5):
            rl.try_acquire("comfyui", tokens=1)
        result = rl.try_acquire("comfyui", tokens=1)
        assert result.allowed is False

    def test_release_all_refills(self, rl):
        for _ in range(5):
            rl.try_acquire("comfyui", tokens=1)
        rl.release_all("comfyui")
        result = rl.try_acquire("comfyui", tokens=1)
        assert result.allowed is True

    def test_release_all_unknown_service_noop(self, rl):
        rl.release_all("ghost_service")  # Should not raise

    def test_get_status_fields(self, rl):
        status = rl.get_status("lmstudio")
        assert "service" in status
        assert "tokens" in status
        assert "capacity" in status
        assert "refill_rate" in status
        assert "queue_depth" in status
        assert "backpressure_active" in status
        assert "calls_total" in status

    def test_get_status_unknown_service(self, rl):
        status = rl.get_status("unknown_svc")
        assert "error" in status

    def test_configure_service(self, rl):
        cfg = RateLimitConfig("custom_svc", capacity=100, refill_rate=20.0)
        rl.configure_service(cfg)
        assert "custom_svc" in rl._buckets
        status = rl.get_status("custom_svc")
        assert status["capacity"] == 100.0

    def test_configure_service_persists(self, tmp_path):
        db = str(tmp_path / "rate.db")
        rl_a = RateLimiter(db_path=db)
        cfg = RateLimitConfig("persist_svc", capacity=77, refill_rate=7.0)
        rl_a.configure_service(cfg)
        rl_b = RateLimiter(db_path=db)
        assert "persist_svc" in rl_b._buckets
        assert rl_b.get_status("persist_svc")["capacity"] == 77.0

    def test_get_metrics_all_services(self, rl):
        metrics = rl.get_metrics()
        for service in DEFAULT_CONFIGS:
            assert service in metrics

    def test_get_metrics_has_avg_wait(self, rl):
        rl.acquire("nexus", tokens=1)
        metrics = rl.get_metrics()
        assert "avg_wait_ms" in metrics["nexus"]

    def test_backpressure_active_false_when_full(self, rl):
        assert rl.backpressure_active("nexus") is False

    def test_backpressure_active_true_when_drained(self, rl):
        for _ in range(5):
            rl.try_acquire("comfyui", tokens=1)
        # 0 tokens < 20% of 5 = 1.0 → backpressure active
        assert rl.backpressure_active("comfyui") is True

    def test_backpressure_unknown_service_false(self, rl):
        assert rl.backpressure_active("ghost") is False

    def test_auto_create_unknown_service(self, rl):
        result = rl.acquire("brand_new_service", tokens=1)
        assert result.allowed is True
        assert "brand_new_service" in rl._buckets

    def test_metrics_track_calls(self, rl):
        rl.acquire("nexus", tokens=1)
        rl.acquire("nexus", tokens=1)
        metrics = rl.get_metrics()
        assert metrics["nexus"]["calls_total"] >= 2

    def test_metrics_track_rejections(self, rl):
        # Drain comfyui bucket
        for _ in range(5):
            rl.try_acquire("comfyui", tokens=1)
        # Try again — should be rejected
        rl.try_acquire("comfyui", tokens=1)
        metrics = rl.get_metrics()
        assert metrics["comfyui"]["rejections_total"] >= 1

    def test_rejection_rate_calculation(self, rl):
        # Make sure initial stats are zero
        metrics = rl.get_metrics()
        # rejection_rate is 0 when no calls made
        for service_metrics in metrics.values():
            assert 0.0 <= service_metrics["rejection_rate"] <= 1.0


# ---------------------------------------------------------------------------
# @rate_limited decorator
# ---------------------------------------------------------------------------


class TestRateLimitedDecorator:
    def test_allows_when_tokens_available(self, rl):
        @rl.rate_limited("nexus", tokens=1)
        def my_func():
            return "called"

        assert my_func() == "called"

    def test_raises_when_drained(self, rl):
        # Drain comfyui
        for _ in range(5):
            rl.try_acquire("comfyui", tokens=1)

        @rl.rate_limited("comfyui", tokens=1)
        def my_func():
            return "should_not_reach"

        with pytest.raises(RateLimitExceeded):
            my_func()

    def test_preserves_function_name(self, rl):
        @rl.rate_limited("nexus")
        def original_name():
            pass

        assert original_name.__name__ == "original_name"
