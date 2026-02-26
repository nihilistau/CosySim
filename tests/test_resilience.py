"""Tests for engine.services.resilience — CircuitBreaker, retry, ServiceStatus."""

import pytest
from unittest.mock import patch, MagicMock

from engine.services.resilience import CircuitBreaker, retry, ServiceStatus


# ═══════════════════════════════════════════════════════════════════════════
#  ServiceStatus
# ═══════════════════════════════════════════════════════════════════════════
class TestServiceStatus:
    """Tests for ServiceStatus enum."""

    def test_enum_values(self):
        """All three status variants exist with expected string values."""
        assert ServiceStatus.UP.value == "up"
        assert ServiceStatus.DOWN.value == "down"
        assert ServiceStatus.DEGRADED.value == "degraded"

    def test_enum_members_count(self):
        """Exactly three members in ServiceStatus."""
        assert len(ServiceStatus) == 3


# ═══════════════════════════════════════════════════════════════════════════
#  CircuitBreaker
# ═══════════════════════════════════════════════════════════════════════════
class TestCircuitBreakerInitialState:
    """Tests for CircuitBreaker construction and defaults."""

    def test_initial_state_is_closed(self):
        """New circuit breaker starts in closed state."""
        cb = CircuitBreaker("test-svc")
        assert cb.state == "closed"

    def test_initial_status_is_up(self):
        """Closed state maps to ServiceStatus.UP."""
        cb = CircuitBreaker("test-svc")
        assert cb.status == ServiceStatus.UP

    def test_default_parameters(self):
        """Defaults: threshold=5, recovery_timeout=60."""
        cb = CircuitBreaker()
        assert cb.name == "service"
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0

    def test_custom_parameters(self):
        """Custom values are stored correctly."""
        cb = CircuitBreaker("comfyui", failure_threshold=3, recovery_timeout=30)
        assert cb.name == "comfyui"
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30.0


class TestCircuitBreakerClosed:
    """Tests for behaviour in the CLOSED state."""

    def test_allow_request_when_closed(self):
        """Closed circuit allows requests."""
        cb = CircuitBreaker("svc", failure_threshold=5)
        assert cb.allow_request() is True

    def test_failures_below_threshold_stay_closed(self):
        """Fewer failures than threshold keeps circuit closed."""
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_record_success_resets_failure_count(self):
        """Success after some failures resets count, stays closed."""
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(3):
            cb.record_failure()
        cb.record_success()
        # Should be able to tolerate another 4 failures without opening
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"


class TestCircuitBreakerOpenTransition:
    """Tests for CLOSED → OPEN transition."""

    def test_threshold_failures_opens_circuit(self):
        """Exactly threshold failures transitions to open."""
        cb = CircuitBreaker("svc", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"

    def test_more_than_threshold_stays_open(self):
        """Extra failures beyond threshold keep circuit open."""
        cb = CircuitBreaker("svc", failure_threshold=3)
        for _ in range(6):
            cb.record_failure()
        assert cb.state == "open"

    def test_open_blocks_requests(self):
        """Open circuit blocks allow_request."""
        cb = CircuitBreaker("svc", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is False

    def test_open_status_is_down(self):
        """Open state maps to ServiceStatus.DOWN."""
        cb = CircuitBreaker("svc", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.status == ServiceStatus.DOWN


class TestCircuitBreakerHalfOpen:
    """Tests for OPEN → HALF_OPEN transition via recovery timeout."""

    @patch("engine.services.resilience.time")
    def test_recovery_timeout_transitions_to_half_open(self, mock_time):
        """After recovery_timeout elapses, state becomes half_open."""
        # time.time() used during record_failure
        mock_time.time.return_value = 1000.0
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30)
        cb.record_failure()
        cb.record_failure()
        assert cb._state == "open"

        # Advance time past recovery window
        mock_time.time.return_value = 1031.0
        assert cb.state == "half_open"

    @patch("engine.services.resilience.time")
    def test_half_open_allows_request(self, mock_time):
        """Half-open circuit allows a probe request."""
        mock_time.time.return_value = 1000.0
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()

        mock_time.time.return_value = 1011.0
        assert cb.allow_request() is True

    @patch("engine.services.resilience.time")
    def test_half_open_status_is_degraded(self, mock_time):
        """Half-open state maps to ServiceStatus.DEGRADED."""
        mock_time.time.return_value = 1000.0
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()

        mock_time.time.return_value = 1011.0
        assert cb.status == ServiceStatus.DEGRADED

    @patch("engine.services.resilience.time")
    def test_success_in_half_open_closes_circuit(self, mock_time):
        """A successful request in half-open transitions back to closed."""
        mock_time.time.return_value = 1000.0
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()

        # Move to half-open
        mock_time.time.return_value = 1011.0
        assert cb.state == "half_open"

        # Record success — should close
        cb.record_success()
        assert cb.state == "closed"
        assert cb.status == ServiceStatus.UP

    @patch("engine.services.resilience.time")
    def test_before_timeout_stays_open(self, mock_time):
        """Circuit stays open if recovery_timeout has not elapsed."""
        mock_time.time.return_value = 1000.0
        cb = CircuitBreaker("svc", failure_threshold=2, recovery_timeout=30)
        cb.record_failure()
        cb.record_failure()

        # Just before timeout
        mock_time.time.return_value = 1029.0
        assert cb.state == "open"
        assert cb.allow_request() is False


class TestCircuitBreakerReset:
    """Tests for manual reset."""

    def test_reset_from_open(self):
        """Reset from open returns to closed, allows requests."""
        cb = CircuitBreaker("svc", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        cb.reset()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_reset_clears_failure_count(self):
        """After reset, failure count is back to zero."""
        cb = CircuitBreaker("svc", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.reset()

        # Two more failures shouldn't open (total of 2, below threshold 3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"

    def test_reset_idempotent_on_closed(self):
        """Reset on an already-closed breaker is a no-op."""
        cb = CircuitBreaker("svc")
        cb.reset()
        assert cb.state == "closed"
        assert cb.allow_request() is True


# ═══════════════════════════════════════════════════════════════════════════
#  retry decorator
# ═══════════════════════════════════════════════════════════════════════════
class TestRetryDecorator:
    """Tests for the @retry decorator."""

    @patch("engine.services.resilience.time.sleep")
    def test_success_on_first_try(self, mock_sleep):
        """No retries needed when function succeeds immediately."""
        @retry(max_attempts=3, delay=1.0)
        def succeed():
            return "ok"

        assert succeed() == "ok"
        mock_sleep.assert_not_called()

    @patch("engine.services.resilience.time.sleep")
    def test_success_after_retries(self, mock_sleep):
        """Function succeeds on the second attempt after one failure."""
        call_count = {"n": 0}

        @retry(max_attempts=3, delay=0.1)
        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise ConnectionError("fail")
            return "recovered"

        assert flaky() == "recovered"
        assert call_count["n"] == 2
        assert mock_sleep.call_count == 1

    @patch("engine.services.resilience.time.sleep")
    def test_exhausts_all_retries(self, mock_sleep):
        """After max_attempts failures, the last exception is raised."""
        @retry(max_attempts=3, delay=0.1)
        def always_fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            always_fail()

        # 2 sleeps: after attempt 1 and attempt 2 (not after final attempt)
        assert mock_sleep.call_count == 2

    @patch("engine.services.resilience.time.sleep")
    def test_preserves_return_value(self, mock_sleep):
        """Decorated function returns original value on success."""
        @retry(max_attempts=2)
        def get_dict():
            return {"key": "value", "count": 42}

        result = get_dict()
        assert result == {"key": "value", "count": 42}

    @patch("engine.services.resilience.time.sleep")
    def test_respects_exception_filter(self, mock_sleep):
        """Only specified exceptions trigger retries; others propagate."""
        @retry(max_attempts=3, delay=0.1, exceptions=(ConnectionError,))
        def raise_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            raise_type_error()

        # Should NOT have retried — TypeError not in exceptions tuple
        mock_sleep.assert_not_called()

    @patch("engine.services.resilience.time.sleep")
    def test_backoff_multiplier(self, mock_sleep):
        """Delay doubles (by default backoff=2.0) between retries."""
        call_count = {"n": 0}

        @retry(max_attempts=4, delay=1.0, backoff=2.0)
        def fail_thrice():
            call_count["n"] += 1
            if call_count["n"] < 4:
                raise RuntimeError("not yet")
            return "done"

        assert fail_thrice() == "done"
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @patch("engine.services.resilience.time.sleep")
    def test_wraps_preserves_function_name(self, mock_sleep):
        """@retry uses functools.wraps, so __name__ is preserved."""
        @retry(max_attempts=2)
        def my_special_function():
            return True

        assert my_special_function.__name__ == "my_special_function"

    @patch("engine.services.resilience.time.sleep")
    def test_passes_args_and_kwargs(self, mock_sleep):
        """Positional and keyword arguments are forwarded correctly."""
        @retry(max_attempts=2)
        def add(a, b, offset=0):
            return a + b + offset

        assert add(2, 3, offset=10) == 15

    @patch("engine.services.resilience.time.sleep")
    def test_single_attempt_no_retry(self, mock_sleep):
        """With max_attempts=1, failure raises immediately with no sleep."""
        @retry(max_attempts=1, delay=1.0)
        def instant_fail():
            raise RuntimeError("one-shot")

        with pytest.raises(RuntimeError, match="one-shot"):
            instant_fail()

        mock_sleep.assert_not_called()
