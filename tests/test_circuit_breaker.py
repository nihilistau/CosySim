"""Tests for engine.resilience.circuit_breaker module.

Covers: CircuitState, CircuitConfig, CircuitBreaker, ExponentialBackoff,
RetryPolicy, retry_with_backoff, circuit_protected, CircuitOpenError,
CircuitBreakerRegistry, StateTransition, and Nexus/metrics logging.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitConfig,
    CircuitOpenError,
    CircuitState,
    ExponentialBackoff,
    RetryPolicy,
    StateTransition,
    _log_transition_to_metrics,
    _log_transition_to_nexus,
    circuit_protected,
    get_breaker_registry,
    retry_with_backoff,
)


# ──── Helpers ──────────────────────────────────────────────────────────────


class _Excluded(Exception):
    """Exception type used for excluded_exceptions tests."""


class _Retryable(Exception):
    """Exception type used for retryable tests."""


class _NonRetryable(Exception):
    """Exception type that should NOT trigger retries."""


def _make_breaker(
    name: str = "test",
    failure_threshold: int = 3,
    recovery_timeout: float = 10.0,
    success_threshold: int = 2,
    half_open_max_calls: int = 3,
    excluded_exceptions: tuple = (),
    window_size: int = 60,
) -> CircuitBreaker:
    """Shortcut to build a CircuitBreaker with sensible test defaults."""
    cfg = CircuitConfig(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        success_threshold=success_threshold,
        half_open_max_calls=half_open_max_calls,
        excluded_exceptions=excluded_exceptions,
        window_size=window_size,
    )
    return CircuitBreaker(cfg)


# ──── TestCircuitState ─────────────────────────────────────────────────────


class TestCircuitState:
    def test_enum_values_exist(self):
        assert hasattr(CircuitState, "CLOSED")
        assert hasattr(CircuitState, "OPEN")
        assert hasattr(CircuitState, "HALF_OPEN")

    def test_string_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_all_members(self):
        assert len(CircuitState) == 3


# ──── TestCircuitConfig ────────────────────────────────────────────────────


class TestCircuitConfig:
    def test_default_values(self):
        cfg = CircuitConfig()
        assert cfg.failure_threshold == 5
        assert cfg.recovery_timeout == 60.0
        assert cfg.half_open_max_calls == 3
        assert cfg.success_threshold == 2
        assert cfg.excluded_exceptions == ()
        assert cfg.window_size == 60
        assert cfg.name == ""

    def test_custom_values(self):
        cfg = CircuitConfig(
            failure_threshold=10,
            recovery_timeout=30.0,
            half_open_max_calls=5,
            success_threshold=3,
            excluded_exceptions=(ValueError,),
            window_size=120,
            name="custom",
        )
        assert cfg.failure_threshold == 10
        assert cfg.recovery_timeout == 30.0
        assert cfg.half_open_max_calls == 5
        assert cfg.success_threshold == 3
        assert cfg.excluded_exceptions == (ValueError,)
        assert cfg.window_size == 120
        assert cfg.name == "custom"

    def test_excluded_exceptions_tuple(self):
        cfg = CircuitConfig(excluded_exceptions=(ValueError, TypeError))
        assert ValueError in cfg.excluded_exceptions
        assert TypeError in cfg.excluded_exceptions


# ──── TestCircuitBreaker ───────────────────────────────────────────────────


@patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
@patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
class TestCircuitBreaker:
    def test_initial_state_is_closed(self, _m, _n):
        cb = _make_breaker()
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self, _m, _n):
        cb = _make_breaker()
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_closed_to_open_after_failure_threshold(self, _m, _n):
        cb = _make_breaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure(RuntimeError("boom"))
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_requests(self, _m, _n):
        cb = _make_breaker(failure_threshold=2)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    @patch("engine.resilience.circuit_breaker.time")
    def test_open_to_half_open_after_recovery_timeout(self, mock_time, _m, _n):
        mock_time.monotonic = MagicMock()
        t = 1000.0
        mock_time.monotonic.return_value = t

        cb = _make_breaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())
        assert cb.state == CircuitState.OPEN

        # Advance past recovery_timeout
        mock_time.monotonic.return_value = t + 11.0
        assert cb.state == CircuitState.HALF_OPEN

    @patch("engine.resilience.circuit_breaker.time")
    def test_half_open_to_closed_after_success_threshold(self, mock_time, _m, _n):
        mock_time.monotonic = MagicMock()
        t = 1000.0
        mock_time.monotonic.return_value = t

        cb = _make_breaker(failure_threshold=2, recovery_timeout=5.0, success_threshold=2)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())

        mock_time.monotonic.return_value = t + 6.0
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    @patch("engine.resilience.circuit_breaker.time")
    def test_half_open_to_open_on_failure(self, mock_time, _m, _n):
        mock_time.monotonic = MagicMock()
        t = 1000.0
        mock_time.monotonic.return_value = t

        cb = _make_breaker(failure_threshold=2, recovery_timeout=5.0)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())

        mock_time.monotonic.return_value = t + 6.0
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure(RuntimeError())
        assert cb.state == CircuitState.OPEN

    def test_excluded_exceptions_not_counted(self, _m, _n):
        cb = _make_breaker(failure_threshold=2, excluded_exceptions=(_Excluded,))
        cb.record_failure(_Excluded("ignored"))
        cb.record_failure(_Excluded("ignored"))
        cb.record_failure(_Excluded("ignored"))
        assert cb.state == CircuitState.CLOSED

    def test_non_excluded_exceptions_still_counted(self, _m, _n):
        cb = _make_breaker(failure_threshold=2, excluded_exceptions=(_Excluded,))
        cb.record_failure(RuntimeError("counted"))
        cb.record_failure(RuntimeError("counted"))
        assert cb.state == CircuitState.OPEN

    def test_reset_forces_closed(self, _m, _n):
        cb = _make_breaker(failure_threshold=2)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_counters(self, _m, _n):
        cb = _make_breaker(failure_threshold=2)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())
        cb.reset()
        stats = cb.get_stats()
        assert stats["failure_count"] == 0
        assert stats["half_open_calls"] == 0
        assert stats["half_open_successes"] == 0

    def test_get_stats_returns_correct_values(self, _m, _n):
        cb = _make_breaker(name="stats_test", failure_threshold=5)
        cb.record_success()
        cb.record_failure(RuntimeError())
        stats = cb.get_stats()
        assert stats["name"] == "stats_test"
        assert stats["state"] == "closed"
        assert stats["total_requests"] == 2
        assert stats["total_successes"] == 1
        assert stats["total_failures"] == 1

    @patch("engine.resilience.circuit_breaker.time")
    def test_rolling_window_old_failures_expire(self, mock_time, _m, _n):
        mock_time.monotonic = MagicMock()
        t = 1000.0
        mock_time.monotonic.return_value = t

        cb = _make_breaker(failure_threshold=5, window_size=30)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())

        # Advance past window_size so old failures are pruned
        mock_time.monotonic.return_value = t + 31.0
        rate = cb.get_failure_rate()
        assert rate == 0.0

    def test_success_resets_consecutive_failure_count(self, _m, _n):
        cb = _make_breaker(failure_threshold=3)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())
        cb.record_success()
        # One more failure should NOT open (counter was reset)
        cb.record_failure(RuntimeError())
        assert cb.state == CircuitState.CLOSED

    @patch("engine.resilience.circuit_breaker.time")
    def test_allow_request_half_open_limited(self, mock_time, _m, _n):
        mock_time.monotonic = MagicMock()
        t = 1000.0
        mock_time.monotonic.return_value = t

        cb = _make_breaker(failure_threshold=2, recovery_timeout=5.0, half_open_max_calls=2)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())

        mock_time.monotonic.return_value = t + 6.0
        assert cb.allow_request() is True
        assert cb.allow_request() is True
        assert cb.allow_request() is False  # exceeds half_open_max_calls

    def test_allow_request_closed_always_true(self, _m, _n):
        cb = _make_breaker()
        assert cb.allow_request() is True
        assert cb.allow_request() is True

    def test_allow_request_open_always_false(self, _m, _n):
        cb = _make_breaker(failure_threshold=1)
        cb.record_failure(RuntimeError())
        assert cb.allow_request() is False

    def test_thread_safety_concurrent_failures(self, _m, _n):
        cb = _make_breaker(failure_threshold=100)
        errors = []

        def record_many():
            try:
                for _ in range(50):
                    cb.record_failure(RuntimeError())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        stats = cb.get_stats()
        assert stats["total_failures"] == 200

    def test_record_failure_none_error(self, _m, _n):
        cb = _make_breaker(failure_threshold=3)
        cb.record_failure(None)
        assert cb.get_stats()["total_failures"] == 1

    def test_name_property(self, _m, _n):
        cb = _make_breaker(name="mybreaker")
        assert cb.name == "mybreaker"

    def test_repr(self, _m, _n):
        cb = _make_breaker(name="repr_test")
        r = repr(cb)
        assert "repr_test" in r
        assert "closed" in r


# ──── TestExponentialBackoff ───────────────────────────────────────────────


class TestExponentialBackoff:
    def test_first_attempt_delay_equals_base(self):
        bo = ExponentialBackoff(base_delay=2.0, jitter=False)
        assert bo.next_delay(0) == 2.0

    def test_delays_increase_exponentially(self):
        bo = ExponentialBackoff(base_delay=1.0, multiplier=2.0, jitter=False, max_delay=1000.0)
        assert bo.next_delay(0) == 1.0
        assert bo.next_delay(1) == 2.0
        assert bo.next_delay(2) == 4.0
        assert bo.next_delay(3) == 8.0

    def test_max_delay_is_capped(self):
        bo = ExponentialBackoff(base_delay=1.0, max_delay=5.0, jitter=False)
        assert bo.next_delay(10) == 5.0

    def test_jitter_adds_randomness(self):
        bo = ExponentialBackoff(base_delay=1.0, jitter=True, max_delay=100.0)
        delays = {bo.next_delay(2) for _ in range(20)}
        # With jitter, we expect variation
        assert len(delays) > 1

    def test_reset_clears_attempt_counter(self):
        bo = ExponentialBackoff()
        bo._attempt = 5
        bo.reset()
        assert bo._attempt == 0

    def test_zero_base_delay(self):
        bo = ExponentialBackoff(base_delay=0.0, jitter=False)
        assert bo.next_delay(0) == 0.0
        assert bo.next_delay(5) == 0.0


# ──── TestRetryPolicy ──────────────────────────────────────────────────────


class TestRetryPolicy:
    def test_default_values(self):
        rp = RetryPolicy()
        assert rp.max_attempts == 3
        assert isinstance(rp.backoff, ExponentialBackoff)
        assert rp.retryable_exceptions == (Exception,)
        assert rp.on_retry is None

    def test_custom_backoff(self):
        bo = ExponentialBackoff(base_delay=5.0)
        rp = RetryPolicy(backoff=bo)
        assert rp.backoff.base_delay == 5.0

    def test_custom_retryable_exceptions(self):
        rp = RetryPolicy(retryable_exceptions=(_Retryable, ValueError))
        assert _Retryable in rp.retryable_exceptions
        assert ValueError in rp.retryable_exceptions

    def test_on_retry_callback(self):
        cb = MagicMock()
        rp = RetryPolicy(on_retry=cb)
        assert rp.on_retry is cb


# ──── TestRetryWithBackoff ─────────────────────────────────────────────────


class TestRetryWithBackoff:
    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_succeeds_on_first_try(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()

        @retry_with_backoff(RetryPolicy(max_attempts=3))
        def ok():
            return "success"

        assert ok() == "success"
        mock_time.sleep.assert_not_called()

    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_succeeds_after_retries(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()
        call_count = 0

        @retry_with_backoff(RetryPolicy(max_attempts=4))
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("not yet")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 3
        assert mock_time.sleep.call_count == 2

    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_raises_after_max_attempts_exhausted(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()

        @retry_with_backoff(RetryPolicy(max_attempts=3))
        def always_fail():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            always_fail()

    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_only_retries_retryable_exceptions(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()

        policy = RetryPolicy(
            max_attempts=5,
            retryable_exceptions=(_Retryable,),
        )

        @retry_with_backoff(policy)
        def wrong_error():
            raise _NonRetryable("nope")

        with pytest.raises(_NonRetryable):
            wrong_error()
        mock_time.sleep.assert_not_called()

    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_on_retry_callback_is_called(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()
        callback = MagicMock()
        call_count = 0

        policy = RetryPolicy(max_attempts=3, on_retry=callback)

        @retry_with_backoff(policy)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("retry me")
            return "done"

        fail_twice()
        assert callback.call_count == 2
        # First retry: attempt=1
        assert callback.call_args_list[0][0][0] == 1

    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_backoff_delays_are_used(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()

        bo = ExponentialBackoff(base_delay=1.0, multiplier=2.0, jitter=False, max_delay=100.0)
        policy = RetryPolicy(max_attempts=4, backoff=bo)

        call_count = 0

        @retry_with_backoff(policy)
        def fail_thrice():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise RuntimeError("fail")
            return "ok"

        fail_thrice()
        delays = [c[0][0] for c in mock_time.sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @patch("engine.resilience.circuit_breaker.time")
    @patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
    @patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
    def test_default_policy_when_none(self, _m, _n, mock_time):
        mock_time.monotonic = MagicMock(return_value=1000.0)
        mock_time.sleep = MagicMock()

        @retry_with_backoff()
        def succeed():
            return 42

        assert succeed() == 42


# ──── TestCircuitProtected ─────────────────────────────────────────────────


@patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
@patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
class TestCircuitProtected:
    def test_normal_call_passes_through(self, _m, _n):
        cb = _make_breaker()

        @circuit_protected(cb)
        def greet(name):
            return f"hello {name}"

        assert greet("world") == "hello world"

    def test_raises_circuit_open_error_no_fallback(self, _m, _n):
        cb = _make_breaker(failure_threshold=1)
        cb.record_failure(RuntimeError())

        @circuit_protected(cb)
        def blocked():
            return "never"

        with pytest.raises(CircuitOpenError):
            blocked()

    def test_calls_fallback_when_open(self, _m, _n):
        cb = _make_breaker(failure_threshold=1)
        cb.record_failure(RuntimeError())

        @circuit_protected(cb, fallback=lambda: "fallback_result")
        def blocked():
            return "never"

        assert blocked() == "fallback_result"

    def test_records_success_on_normal_call(self, _m, _n):
        cb = _make_breaker()

        @circuit_protected(cb)
        def ok():
            return "good"

        ok()
        stats = cb.get_stats()
        assert stats["total_successes"] == 1

    def test_records_failure_and_reraises(self, _m, _n):
        cb = _make_breaker()

        @circuit_protected(cb)
        def fail():
            raise ValueError("bad")

        with pytest.raises(ValueError, match="bad"):
            fail()

        stats = cb.get_stats()
        assert stats["total_failures"] == 1

    def test_fallback_receives_args(self, _m, _n):
        cb = _make_breaker(failure_threshold=1)
        cb.record_failure(RuntimeError())

        def fb(x, y):
            return x + y

        @circuit_protected(cb, fallback=fb)
        def add(x, y):
            return x * y

        assert add(3, 4) == 7  # fallback adds instead of multiplies


# ──── TestCircuitOpenError ─────────────────────────────────────────────────


class TestCircuitOpenError:
    def test_message_formatting(self):
        err = CircuitOpenError("test_svc", time.monotonic(), 30.0)
        assert "test_svc" in str(err)
        assert "OPEN" in str(err)

    def test_attributes_accessible(self):
        now = time.monotonic()
        err = CircuitOpenError("svc", now, 60.0)
        assert err.breaker_name == "svc"
        assert err.open_since == now
        assert err.recovery_timeout == 60.0


# ──── TestCircuitBreakerRegistry ───────────────────────────────────────────


@patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
@patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
class TestCircuitBreakerRegistry:
    def _fresh_registry(self):
        return CircuitBreakerRegistry()

    def test_register_and_get(self, _m, _n):
        reg = self._fresh_registry()
        cb = _make_breaker(name="a")
        reg.register("a", cb)
        assert reg.get("a") is cb

    def test_get_returns_none_for_missing(self, _m, _n):
        reg = self._fresh_registry()
        assert reg.get("nonexistent") is None

    def test_register_duplicate_raises(self, _m, _n):
        reg = self._fresh_registry()
        cb = _make_breaker(name="dup")
        reg.register("dup", cb)
        with pytest.raises(ValueError, match="already registered"):
            reg.register("dup", cb)

    def test_get_or_create_creates_new(self, _m, _n):
        reg = self._fresh_registry()
        cb = reg.get_or_create("new_one")
        assert cb is not None
        assert cb.name == "new_one"

    def test_get_or_create_returns_existing(self, _m, _n):
        reg = self._fresh_registry()
        first = reg.get_or_create("existing")
        second = reg.get_or_create("existing", CircuitConfig(failure_threshold=99))
        assert first is second

    def test_all_status(self, _m, _n):
        reg = self._fresh_registry()
        reg.get_or_create("s1")
        reg.get_or_create("s2")
        status = reg.all_status()
        assert "s1" in status
        assert "s2" in status
        assert status["s1"]["state"] == "closed"

    def test_reset_all(self, _m, _n):
        reg = self._fresh_registry()
        cb = reg.get_or_create("r", CircuitConfig(name="r", failure_threshold=1))
        cb.record_failure(RuntimeError())
        assert cb.state == CircuitState.OPEN
        reg.reset_all()
        assert cb.state == CircuitState.CLOSED

    def test_get_open_circuits(self, _m, _n):
        reg = self._fresh_registry()
        cb1 = reg.get_or_create("open1", CircuitConfig(name="open1", failure_threshold=1))
        reg.get_or_create("closed1")
        cb1.record_failure(RuntimeError())
        opens = reg.get_open_circuits()
        assert "open1" in opens
        assert "closed1" not in opens

    def test_get_health_summary(self, _m, _n):
        reg = self._fresh_registry()
        reg.get_or_create("h1")
        cb2 = reg.get_or_create("h2", CircuitConfig(name="h2", failure_threshold=1))
        cb2.record_failure(RuntimeError())
        summary = reg.get_health_summary()
        assert summary["total"] == 2
        assert summary["closed"] == 1
        assert summary["open"] == 1
        assert summary["half_open"] == 0
        assert len(summary["breakers"]) == 2

    def test_len_and_contains(self, _m, _n):
        reg = self._fresh_registry()
        reg.get_or_create("x")
        assert len(reg) == 1
        assert "x" in reg
        assert "y" not in reg

    def test_unregister(self, _m, _n):
        reg = self._fresh_registry()
        cb = reg.get_or_create("removeme")
        removed = reg.unregister("removeme")
        assert removed is cb
        assert reg.get("removeme") is None

    def test_singleton_via_get_breaker_registry(self, _m, _n):
        r1 = get_breaker_registry()
        r2 = get_breaker_registry()
        assert r1 is r2


# ──── TestStateTransition ──────────────────────────────────────────────────


@patch("engine.resilience.circuit_breaker._log_transition_to_nexus")
@patch("engine.resilience.circuit_breaker._log_transition_to_metrics")
class TestStateTransition:
    def test_transitions_are_recorded(self, _m, _n):
        cb = _make_breaker(failure_threshold=2)
        cb.record_failure(RuntimeError())
        cb.record_failure(RuntimeError())
        transitions = cb.transitions
        assert len(transitions) >= 1
        assert transitions[-1].to_state == CircuitState.OPEN

    def test_transition_fields_correct(self, _m, _n):
        cb = _make_breaker(name="field_test", failure_threshold=1)
        cb.record_failure(RuntimeError())
        t = cb.transitions[-1]
        assert t.breaker_name == "field_test"
        assert t.from_state == CircuitState.CLOSED
        assert t.to_state == CircuitState.OPEN
        assert t.reason == "failure_threshold"
        assert isinstance(t.timestamp, float)

    def test_max_transitions_bounded(self, _m, _n):
        cb = _make_breaker(failure_threshold=1, recovery_timeout=0.0)
        # Each failure→open, then reset→closed produces 2 transitions
        for _ in range(60):
            cb.record_failure(RuntimeError())
            cb.reset()
        assert len(cb.transitions) <= 100

    def test_reset_transition_recorded(self, _m, _n):
        cb = _make_breaker(failure_threshold=1)
        cb.record_failure(RuntimeError())
        cb.reset()
        t = cb.transitions[-1]
        assert t.to_state == CircuitState.CLOSED
        assert t.reason == "manual_reset"


# ──── TestNexusLogging ─────────────────────────────────────────────────────


class TestNexusLogging:
    def test_nexus_logging_attempted_on_transition(self):
        transition = StateTransition(
            breaker_name="nexus_test",
            from_state=CircuitState.CLOSED,
            to_state=CircuitState.OPEN,
            timestamp=1000.0,
            reason="failure_threshold",
            failure_count=5,
        )
        mock_client = MagicMock()
        with patch(
            "engine.resilience.circuit_breaker.get_nexus_client",
            return_value=mock_client,
            create=True,
        ):
            with patch.dict("sys.modules", {"engine.nexus.client": MagicMock(get_nexus_client=lambda: mock_client)}):
                _log_transition_to_nexus(transition)
                mock_client.add_entry.assert_called_once()
                call_kwargs = mock_client.add_entry.call_args
                assert "nexus_test" in call_kwargs.kwargs.get("title", "") or "nexus_test" in str(call_kwargs)

    def test_nexus_failure_silently_caught(self):
        transition = StateTransition(
            breaker_name="fail_nexus",
            from_state=CircuitState.CLOSED,
            to_state=CircuitState.OPEN,
            timestamp=1000.0,
            reason="test",
            failure_count=1,
        )
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=ImportError("no nexus"),
            create=True,
        ):
            # Should not raise
            _log_transition_to_nexus(transition)

    def test_metrics_logging_attempted(self):
        transition = StateTransition(
            breaker_name="metrics_test",
            from_state=CircuitState.CLOSED,
            to_state=CircuitState.OPEN,
            timestamp=1000.0,
            reason="failure_threshold",
            failure_count=5,
        )
        mock_db = MagicMock()
        with patch.dict("sys.modules", {"engine.observability.metrics_db": MagicMock(get_metrics_db=lambda: mock_db)}):
            _log_transition_to_metrics(transition, CircuitState.OPEN)
            mock_db.record_alert.assert_called_once()
            call_kwargs = mock_db.record_alert.call_args
            assert "red" in str(call_kwargs)
