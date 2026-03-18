"""
Rate Limiter for CosySim.

Provides per-service token bucket rate limiting with:
- Thread-safe token buckets (threading.Lock + background refill thread)
- Blocking and non-blocking acquire modes
- SQLite-backed config persistence and rolling 24-h event log
- Backpressure detection for producers
- @rate_limited decorator for skill functions
"""

import collections
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RateLimitConfig:
    """Configuration for a single service's token bucket.

    Attributes:
        service_name: Unique service identifier.
        capacity: Maximum tokens in the bucket (sustained capacity).
        refill_rate: Tokens added per second.
        burst_multiplier: Effective capacity = capacity × burst_multiplier.
        backpressure_threshold: Fraction of *capacity* below which
            backpressure is considered active (0.0–1.0).
        max_queue_depth: Maximum number of queued waiting requests.
    """

    service_name: str
    capacity: float
    refill_rate: float
    burst_multiplier: float = 1.0
    backpressure_threshold: float = 0.2
    max_queue_depth: int = 50

    @property
    def effective_capacity(self) -> float:
        """Capacity factoring in the burst multiplier."""
        return self.capacity * self.burst_multiplier


@dataclass
class RateLimitResult:
    """Result of a single rate-limit check.

    Attributes:
        allowed: True when the request was granted tokens.
        tokens_remaining: Token count after this operation.
        wait_seconds: Estimated seconds until *tokens* would be available.
        queued: True when the request was granted after queuing.
    """

    allowed: bool
    tokens_remaining: float
    wait_seconds: float = 0.0
    queued: bool = False


class RateLimitExceeded(Exception):
    """Raised when the waiting queue for a service is full."""


# ---------------------------------------------------------------------------
# Internal queue entry
# ---------------------------------------------------------------------------


@dataclass
class _WaitEntry:
    """A single blocked acquire request waiting in the queue."""

    tokens: float
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[RateLimitResult] = None


# ---------------------------------------------------------------------------
# Token Bucket
# ---------------------------------------------------------------------------


class TokenBucket:
    """Classic token bucket with background refill and blocking acquire.

    Args:
        config: Rate-limit configuration for this bucket.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._tokens: float = config.effective_capacity
        self._last_refill: float = time.monotonic()
        self._queue: Deque[_WaitEntry] = collections.deque()
        self._running: bool = True
        self._refill_thread = threading.Thread(
            target=self._refill_loop, daemon=True, name=f"rate-{config.service_name}"
        )
        self._refill_thread.start()

    # ------------------------------------------------------------------
    # Background refill loop
    # ------------------------------------------------------------------

    def _refill_loop(self) -> None:
        """Background daemon thread: refill tokens and drain the queue."""
        while self._running:
            time.sleep(0.05)  # 50 ms tick
            self._do_refill()
            self._drain_queue()

    def _do_refill(self) -> None:
        """Add tokens according to elapsed time and refill rate."""
        now = time.monotonic()
        with self._lock:
            elapsed = now - self._last_refill
            self._last_refill = now
            added = elapsed * self.config.refill_rate
            self._tokens = min(self.config.effective_capacity, self._tokens + added)

    def _drain_queue(self) -> None:
        """Signal waiting requests from the front of the queue when tokens allow."""
        with self._lock:
            while self._queue:
                entry = self._queue[0]
                if self._tokens >= entry.tokens:
                    self._tokens -= entry.tokens
                    self._queue.popleft()
                    entry.result = RateLimitResult(
                        allowed=True,
                        tokens_remaining=self._tokens,
                        queued=True,
                    )
                    entry.event.set()
                else:
                    break  # FIFO — cannot serve head, stop here

    # ------------------------------------------------------------------
    # Public acquire interface
    # ------------------------------------------------------------------

    def try_acquire(self, tokens: float = 1.0) -> RateLimitResult:
        """Non-blocking attempt to consume *tokens*.

        Args:
            tokens: Number of tokens to consume.

        Returns:
            RateLimitResult with ``allowed=True`` on success.
        """
        with self._lock:
            if self._tokens >= tokens:
                self._tokens -= tokens
                return RateLimitResult(allowed=True, tokens_remaining=self._tokens)
            wait = (tokens - self._tokens) / max(self.config.refill_rate, 1e-9)
            return RateLimitResult(allowed=False, tokens_remaining=self._tokens, wait_seconds=wait)

    def acquire(self, tokens: float = 1.0, timeout: float = 30.0) -> RateLimitResult:
        """Blocking acquire: wait up to *timeout* seconds for *tokens*.

        Args:
            tokens: Number of tokens to consume.
            timeout: Maximum seconds to wait.

        Returns:
            RateLimitResult with ``allowed=True`` when tokens were granted
            before the timeout.

        Raises:
            RateLimitExceeded: When the wait queue is already at max depth.
        """
        # Fast path — tokens available right now
        with self._lock:
            if self._tokens >= tokens:
                self._tokens -= tokens
                return RateLimitResult(allowed=True, tokens_remaining=self._tokens)

            if len(self._queue) >= self.config.max_queue_depth:
                raise RateLimitExceeded(
                    f"Rate limit queue full for '{self.config.service_name}' "
                    f"(max_queue_depth={self.config.max_queue_depth})"
                )

            entry = _WaitEntry(tokens=tokens)
            self._queue.append(entry)

        # Wait outside the lock
        granted = entry.event.wait(timeout=timeout)

        if not granted:
            # Timeout — remove from queue if not yet drained
            with self._lock:
                try:
                    self._queue.remove(entry)
                except ValueError:
                    pass  # Already drained — result may have been set
            return RateLimitResult(
                allowed=False,
                tokens_remaining=self._tokens,
                wait_seconds=timeout,
            )

        return entry.result or RateLimitResult(
            allowed=True, tokens_remaining=self._tokens, queued=True
        )

    def release_all(self) -> None:
        """Reset the bucket to its full effective capacity."""
        with self._lock:
            self._tokens = self.config.effective_capacity
        logger.info("Token bucket reset for '%s'", self.config.service_name)

    @property
    def tokens(self) -> float:
        """Current token count (thread-safe snapshot)."""
        with self._lock:
            return self._tokens

    @property
    def queue_depth(self) -> int:
        """Number of requests currently waiting in the queue."""
        return len(self._queue)

    def backpressure_active(self) -> bool:
        """Return True when tokens are below the backpressure threshold."""
        threshold = self.config.capacity * self.config.backpressure_threshold
        return self.tokens < threshold

    def stop(self) -> None:
        """Stop the background refill thread."""
        self._running = False


# ---------------------------------------------------------------------------
# Default service configurations
# ---------------------------------------------------------------------------

DEFAULT_CONFIGS: Dict[str, RateLimitConfig] = {
    "lmstudio": RateLimitConfig("lmstudio", capacity=10, refill_rate=2.0, burst_multiplier=1.5),
    "nlm": RateLimitConfig("nlm", capacity=50, refill_rate=5.0, burst_multiplier=2.0),
    "aistudio": RateLimitConfig("aistudio", capacity=60, refill_rate=10.0),
    "gemini": RateLimitConfig("gemini", capacity=60, refill_rate=10.0),
    "comfyui": RateLimitConfig("comfyui", capacity=5, refill_rate=0.5),
    "tts": RateLimitConfig("tts", capacity=20, refill_rate=3.0),
    "scheduler": RateLimitConfig("scheduler", capacity=100, refill_rate=20.0),
    "nexus": RateLimitConfig("nexus", capacity=200, refill_rate=50.0),
}


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Service-level rate limiter backed by token buckets and SQLite.

    Manages a pool of named TokenBucket instances, one per service.
    Configurations persist across restarts in ``data/rate_limiter.db``.
    A rolling 24-h event log powers the metrics API.

    Args:
        db_path: Path to the SQLite database.  Defaults to
            ``data/rate_limiter.db``.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()

        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        self._db_path = db_path or str(data_dir / "rate_limiter.db")

        self._buckets: Dict[str, TokenBucket] = {}
        self._metrics: Dict[str, Dict[str, Any]] = {}

        self._init_db()
        self._init_defaults()
        self._load_persisted_configs()

    # ------------------------------------------------------------------
    # Database initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create SQLite tables if they do not already exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rate_configs (
                    service_name          TEXT PRIMARY KEY,
                    capacity              REAL NOT NULL,
                    refill_rate           REAL NOT NULL,
                    burst_multiplier      REAL NOT NULL DEFAULT 1.0,
                    backpressure_threshold REAL NOT NULL DEFAULT 0.2,
                    max_queue_depth       INTEGER NOT NULL DEFAULT 50
                );
                CREATE TABLE IF NOT EXISTS rate_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT    NOT NULL,
                    service_name TEXT    NOT NULL,
                    event_type   TEXT    NOT NULL,
                    tokens       REAL    NOT NULL DEFAULT 1.0,
                    wait_ms      REAL    NOT NULL DEFAULT 0.0
                );
                CREATE INDEX IF NOT EXISTS idx_rate_events_ts
                    ON rate_events (timestamp, service_name);
                """
            )

    def _init_defaults(self) -> None:
        """Seed buckets from DEFAULT_CONFIGS (overridden by persisted configs)."""
        for service, config in DEFAULT_CONFIGS.items():
            self._ensure_bucket(service, config)

    def _load_persisted_configs(self) -> None:
        """Load user-configured overrides from the database."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT service_name, capacity, refill_rate, "
                "burst_multiplier, backpressure_threshold, max_queue_depth "
                "FROM rate_configs"
            ).fetchall()

        for row in rows:
            svc, cap, rate, burst, bp, maxq = row
            config = RateLimitConfig(
                service_name=svc,
                capacity=cap,
                refill_rate=rate,
                burst_multiplier=burst,
                backpressure_threshold=bp,
                max_queue_depth=int(maxq),
            )
            self._ensure_bucket(svc, config, replace=True)

    # ------------------------------------------------------------------
    # Bucket management
    # ------------------------------------------------------------------

    def _ensure_bucket(
        self,
        service: str,
        config: RateLimitConfig,
        replace: bool = False,
    ) -> TokenBucket:
        """Return (or create) the TokenBucket for *service*.

        Args:
            service: Service name.
            config: Configuration to use if creating a new bucket.
            replace: When True, stop any existing bucket and replace it.

        Returns:
            The active TokenBucket for *service*.
        """
        with self._lock:
            if service not in self._buckets or replace:
                if service in self._buckets:
                    self._buckets[service].stop()
                self._buckets[service] = TokenBucket(config)
                self._metrics.setdefault(
                    service, {"calls": 0, "rejections": 0, "total_wait_ms": 0.0}
                )
            return self._buckets[service]

    def _persist_config(self, config: RateLimitConfig) -> None:
        """Save a RateLimitConfig to the database.

        Args:
            config: Configuration to persist.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rate_configs
                    (service_name, capacity, refill_rate, burst_multiplier,
                     backpressure_threshold, max_queue_depth)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    config.service_name,
                    config.capacity,
                    config.refill_rate,
                    config.burst_multiplier,
                    config.backpressure_threshold,
                    config.max_queue_depth,
                ),
            )

    def _record_event(
        self, service: str, event_type: str, tokens: float, wait_ms: float
    ) -> None:
        """Append an event row and prune records older than 24 h.

        Args:
            service: Service name.
            event_type: ``"allowed"`` or ``"rejected"``.
            tokens: Token count for this request.
            wait_ms: Actual wait time in milliseconds.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO rate_events "
                    "(timestamp, service_name, event_type, tokens, wait_ms) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        service,
                        event_type,
                        tokens,
                        wait_ms,
                    ),
                )
                conn.execute(
                    "DELETE FROM rate_events "
                    "WHERE timestamp < datetime('now', '-1 day')"
                )
        except Exception as exc:
            logger.debug("rate_events DB write failed (non-critical): %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(
        self,
        service: str,
        tokens: float = 1.0,
        wait: bool = True,
        timeout: float = 30.0,
    ) -> RateLimitResult:
        """Consume tokens from *service*, optionally blocking.

        An unknown service is auto-created with moderate defaults.

        Args:
            service: Service identifier.
            tokens: Number of tokens to consume.
            wait: When True, block until tokens are available or *timeout*
                elapses.
            timeout: Maximum seconds to wait (only used when wait=True).

        Returns:
            RateLimitResult describing the outcome.

        Raises:
            RateLimitExceeded: When wait=True and the queue is full.
        """
        bucket = self._buckets.get(service)
        if bucket is None:
            self.configure_service(
                RateLimitConfig(service, capacity=50, refill_rate=10.0)
            )
            bucket = self._buckets[service]

        start = time.monotonic()
        if wait:
            result = bucket.acquire(tokens=tokens, timeout=timeout)
        else:
            result = bucket.try_acquire(tokens=tokens)

        elapsed_ms = (time.monotonic() - start) * 1000.0

        with self._lock:
            metrics = self._metrics.setdefault(
                service, {"calls": 0, "rejections": 0, "total_wait_ms": 0.0}
            )
            metrics["calls"] += 1
            if not result.allowed:
                metrics["rejections"] += 1
            metrics["total_wait_ms"] += elapsed_ms

        event_type = "allowed" if result.allowed else "rejected"
        self._record_event(service, event_type, tokens, elapsed_ms)
        return result

    def try_acquire(self, service: str, tokens: float = 1.0) -> RateLimitResult:
        """Non-blocking acquire for *service*.

        Args:
            service: Service identifier.
            tokens: Number of tokens to consume.

        Returns:
            RateLimitResult with ``allowed=True`` on success.
        """
        return self.acquire(service, tokens=tokens, wait=False)

    def release_all(self, service: str) -> None:
        """Reset *service* bucket to full effective capacity.

        Args:
            service: Service identifier.
        """
        bucket = self._buckets.get(service)
        if bucket:
            bucket.release_all()
            logger.info("Rate limit reset for service: %s", service)

    def get_status(self, service: str) -> Dict[str, Any]:
        """Current status snapshot for a single service.

        Args:
            service: Service identifier.

        Returns:
            Dict with token counts, queue depth, backpressure flag, and
            aggregate call/rejection stats.
        """
        bucket = self._buckets.get(service)
        if bucket is None:
            return {"service": service, "error": "not configured"}

        with self._lock:
            metrics = self._metrics.get(
                service, {"calls": 0, "rejections": 0, "total_wait_ms": 0.0}
            )
            calls = metrics["calls"]
            rejections = metrics["rejections"]

        rejection_rate = rejections / calls if calls > 0 else 0.0
        return {
            "service": service,
            "tokens": round(bucket.tokens, 2),
            "capacity": bucket.config.capacity,
            "refill_rate": bucket.config.refill_rate,
            "burst_multiplier": bucket.config.burst_multiplier,
            "effective_capacity": round(bucket.config.effective_capacity, 2),
            "queue_depth": bucket.queue_depth,
            "backpressure_active": bucket.backpressure_active(),
            "calls_total": calls,
            "rejections_total": rejections,
            "rejection_rate": round(rejection_rate, 4),
        }

    def configure_service(self, config: RateLimitConfig) -> None:
        """Add or update the rate-limit configuration for a service.

        Changes are persisted to SQLite and take effect immediately.

        Args:
            config: New configuration to apply.
        """
        self._ensure_bucket(config.service_name, config, replace=True)
        self._persist_config(config)
        logger.info(
            "Rate limit configured for '%s': capacity=%s, refill=%s/s",
            config.service_name,
            config.capacity,
            config.refill_rate,
        )

    def get_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Return a status snapshot for every configured service.

        Returns:
            Mapping of service name → status dict (including avg_wait_ms).
        """
        result: Dict[str, Dict[str, Any]] = {}
        for service in list(self._buckets.keys()):
            status = self.get_status(service)
            with self._lock:
                metrics = self._metrics.get(
                    service, {"calls": 0, "rejections": 0, "total_wait_ms": 0.0}
                )
                calls = metrics["calls"]
                avg_wait = metrics["total_wait_ms"] / calls if calls > 0 else 0.0
            status["avg_wait_ms"] = round(avg_wait, 2)
            result[service] = status
        return result

    def backpressure_active(self, service: str) -> bool:
        """Return True when *service* tokens are below the backpressure threshold.

        Args:
            service: Service identifier.

        Returns:
            True when backpressure is active for this service.
        """
        bucket = self._buckets.get(service)
        if bucket is None:
            return False
        return bucket.backpressure_active()

    def rate_limited(self, service: str, tokens: float = 1.0) -> Callable:
        """Decorator: raise RateLimitExceeded if tokens are unavailable.

        Args:
            service: Service to check before calling the decorated function.
            tokens: Tokens to consume per call.

        Returns:
            Decorator that wraps the target function.

        Example:
            >>> @get_rate_limiter().rate_limited("lmstudio", tokens=1)
            ... def call_lmstudio(prompt: str) -> str:
            ...     ...
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                result = self.try_acquire(service, tokens=tokens)
                if not result.allowed:
                    raise RateLimitExceeded(
                        f"Rate limit exceeded for '{service}'. "
                        f"Wait {result.wait_seconds:.1f}s"
                    )
                return func(*args, **kwargs)

            return wrapper

        return decorator


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_limiter_instance: Optional[RateLimiter] = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """Return the global RateLimiter singleton.

    Returns:
        The module-level RateLimiter instance (created on first call).
    """
    global _limiter_instance
    if _limiter_instance is None:
        with _limiter_lock:
            if _limiter_instance is None:
                _limiter_instance = RateLimiter()
    return _limiter_instance
