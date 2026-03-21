"""Source Health Monitor — tracks RSS feed health and manages source lifecycle.

Monitors all configured news sources, tracks consecutive failures,
auto-disables dead feeds, and persists health data in SQLite.

Usage::

    from engine.nexus.news.source_monitor import SourceHealthMonitor

    monitor = SourceHealthMonitor()
    report  = monitor.get_health_report()
    failing = monitor.get_failing_sources(threshold_failures=3)
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DB_PATH = Path("data/news_sources_health.db")
_HTTP_TIMEOUT = 15       # seconds per health probe
_USER_AGENT = "CosySim-HealthMonitor/1.0"
_SLOW_THRESHOLD_SECS = 8.0   # requests slower than this are "SLOW"
_AUTO_DISABLE_THRESHOLD = 5   # failures before auto-disable


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class SourceHealth:
    """Health snapshot for a single RSS source.

    Attributes:
        source_id: Source identifier from registry.
        url: RSS feed URL.
        status: "UP" | "DOWN" | "SLOW" | "FLAKY" | "DISABLED".
        last_success: Unix timestamp of last successful fetch, or None.
        consecutive_failures: How many consecutive fetches have failed.
        avg_articles_per_fetch: Rolling average of articles returned.
        last_checked: Unix timestamp of most recent check.
        response_time_ms: HTTP probe response time in milliseconds.
        error_message: Last error description, or empty string.
    """

    source_id: str
    url: str
    status: str = "UP"
    last_success: Optional[float] = None
    consecutive_failures: int = 0
    avg_articles_per_fetch: float = 0.0
    last_checked: float = 0.0
    response_time_ms: float = 0.0
    error_message: str = ""


class SourceHealthMonitor:
    """Monitors RSS feed health and manages source lifecycle.

    Persists health data in ``data/news_sources_health.db``.

    Args:
        db_path: Override for the health SQLite database path.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._lock = threading.Lock()
        self._ensure_db()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Create health database schema if absent."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS source_health (
                        source_id              TEXT PRIMARY KEY,
                        url                    TEXT NOT NULL,
                        status                 TEXT DEFAULT 'UP',
                        last_success           REAL,
                        consecutive_failures   INTEGER DEFAULT 0,
                        avg_articles_per_fetch REAL DEFAULT 0.0,
                        last_checked           REAL DEFAULT 0.0,
                        response_time_ms       REAL DEFAULT 0.0,
                        error_message          TEXT DEFAULT '',
                        disabled_reason        TEXT DEFAULT '',
                        total_checks           INTEGER DEFAULT 0,
                        total_successes        INTEGER DEFAULT 0
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sh_status ON source_health(status)"
                )
                conn.commit()
        except Exception as exc:
            logger.warning("SourceHealthMonitor DB init error: %s", exc)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _upsert_health(self, health: SourceHealth, disabled_reason: str = "") -> None:
        """Persist a SourceHealth record to the database.

        Args:
            health: SourceHealth to persist.
            disabled_reason: Optional reason for disabling the source.
        """
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO source_health
                       (source_id, url, status, last_success, consecutive_failures,
                        avg_articles_per_fetch, last_checked, response_time_ms,
                        error_message, disabled_reason, total_checks, total_successes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                       ON CONFLICT(source_id) DO UPDATE SET
                           url=excluded.url,
                           status=excluded.status,
                           last_success=COALESCE(excluded.last_success, source_health.last_success),
                           consecutive_failures=excluded.consecutive_failures,
                           avg_articles_per_fetch=excluded.avg_articles_per_fetch,
                           last_checked=excluded.last_checked,
                           response_time_ms=excluded.response_time_ms,
                           error_message=excluded.error_message,
                           disabled_reason=CASE
                               WHEN excluded.disabled_reason != '' THEN excluded.disabled_reason
                               ELSE source_health.disabled_reason
                           END,
                           total_checks=source_health.total_checks+1,
                           total_successes=source_health.total_successes + CASE
                               WHEN excluded.status='UP' THEN 1 ELSE 0 END""",
                    (
                        health.source_id,
                        health.url,
                        health.status,
                        health.last_success,
                        health.consecutive_failures,
                        health.avg_articles_per_fetch,
                        health.last_checked,
                        health.response_time_ms,
                        health.error_message,
                        disabled_reason,
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("upsert_health error: %s", exc)

    def _load_health(self, source_id: str) -> Optional[SourceHealth]:
        """Load persisted health for a source.

        Args:
            source_id: Source identifier.

        Returns:
            SourceHealth or None if not found.
        """
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT source_id, url, status, last_success,
                              consecutive_failures, avg_articles_per_fetch,
                              last_checked, response_time_ms, error_message
                       FROM source_health WHERE source_id=?""",
                    (source_id,),
                ).fetchone()
            if row:
                return SourceHealth(**{k: row[k] for k in row.keys()})
        except Exception as exc:
            logger.debug("load_health error: %s", exc)
        return None

    # ── HTTP probe ────────────────────────────────────────────────────────────

    def _probe_url(self, url: str) -> Dict:
        """Perform an HTTP HEAD (fallback: GET) probe to check feed liveness.

        Args:
            url: URL to probe.

        Returns:
            Dict with keys: success (bool), status_code (int), duration_ms (float),
            error (str).
        """
        t0 = time.time()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
            method="HEAD",
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                duration_ms = (time.time() - t0) * 1000
                return {
                    "success": True,
                    "status_code": resp.status,
                    "duration_ms": duration_ms,
                    "error": "",
                }
        except urllib.error.HTTPError as exc:
            # HEAD not allowed → try GET with minimal read
            if exc.code in (405, 501):
                req2 = urllib.request.Request(
                    url,
                    headers={"User-Agent": _USER_AGENT},
                )
                try:
                    with urllib.request.urlopen(req2, timeout=_HTTP_TIMEOUT) as resp2:
                        resp2.read(256)
                        duration_ms = (time.time() - t0) * 1000
                        return {
                            "success": True,
                            "status_code": resp2.status,
                            "duration_ms": duration_ms,
                            "error": "",
                        }
                except Exception as exc2:
                    pass
            duration_ms = (time.time() - t0) * 1000
            return {
                "success": False,
                "status_code": exc.code,
                "duration_ms": duration_ms,
                "error": f"HTTP {exc.code}: {exc.reason}",
            }
        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000
            return {
                "success": False,
                "status_code": 0,
                "duration_ms": duration_ms,
                "error": str(exc)[:200],
            }

    # ── Public API ─────────────────────────────────────────────────────────────

    def check_source(self, source_id: str) -> SourceHealth:
        """Check the health of a single news source.

        Performs an HTTP probe and updates the persistent health record.
        Auto-disables the source if consecutive_failures >= _AUTO_DISABLE_THRESHOLD.

        Args:
            source_id: Source identifier.

        Returns:
            Updated SourceHealth object.
        """
        # Load source URL from registry
        url = ""
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            source = registry.get_source(source_id)
            if source:
                url = source.url
        except Exception as exc:
            logger.debug("Registry lookup failed: %s", exc)

        if not url:
            # Fall back to stored URL
            existing = self._load_health(source_id)
            if existing:
                url = existing.url
            else:
                logger.warning("check_source: no URL found for source %s", source_id)
                return SourceHealth(source_id=source_id, url="", status="DOWN",
                                    last_checked=time.time(), error_message="Source URL unknown")

        # Load existing health state for consecutive_failures history
        existing = self._load_health(source_id)
        consecutive_failures = existing.consecutive_failures if existing else 0
        last_success = existing.last_success if existing else None
        avg_articles = existing.avg_articles_per_fetch if existing else 0.0

        # Probe
        probe = self._probe_url(url)
        now = time.time()

        if probe["success"]:
            status = "SLOW" if probe["duration_ms"] > (_SLOW_THRESHOLD_SECS * 1000) else "UP"
            consecutive_failures = 0
            last_success = now
        else:
            consecutive_failures += 1
            if consecutive_failures >= _AUTO_DISABLE_THRESHOLD:
                status = "DOWN"
            else:
                status = "FLAKY" if consecutive_failures >= 2 else "DOWN"

        health = SourceHealth(
            source_id=source_id,
            url=url,
            status=status,
            last_success=last_success,
            consecutive_failures=consecutive_failures,
            avg_articles_per_fetch=avg_articles,
            last_checked=now,
            response_time_ms=round(probe["duration_ms"], 1),
            error_message=probe["error"],
        )

        # Auto-disable if too many failures
        disabled_reason = ""
        if consecutive_failures >= _AUTO_DISABLE_THRESHOLD:
            self.disable_source(source_id, reason=f"Auto-disabled: {consecutive_failures} consecutive failures")
            disabled_reason = f"Auto-disabled after {consecutive_failures} failures"
            health.status = "DOWN"

        self._upsert_health(health, disabled_reason=disabled_reason)
        return health

    def check_all_sources(self) -> Dict[str, SourceHealth]:
        """Check health for all configured news sources.

        Returns:
            Dict mapping source_id to SourceHealth.
        """
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            sources = registry.list_sources(enabled_only=False)
        except Exception as exc:
            logger.warning("check_all_sources: registry unavailable: %s", exc)
            sources = []

        results: Dict[str, SourceHealth] = {}
        for source in sources:
            try:
                health = self.check_source(source.id)
                results[source.id] = health
            except Exception as exc:
                logger.warning("check_source failed for %s: %s", source.id, exc)
                results[source.id] = SourceHealth(
                    source_id=source.id,
                    url=source.url,
                    status="DOWN",
                    last_checked=time.time(),
                    error_message=str(exc)[:200],
                )

        logger.info(
            "check_all_sources: checked %d sources, %d UP, %d DOWN/SLOW/FLAKY",
            len(results),
            sum(1 for h in results.values() if h.status == "UP"),
            sum(1 for h in results.values() if h.status != "UP"),
        )
        return results

    def get_failing_sources(self, threshold_failures: int = 3) -> List[str]:
        """Return source IDs with at least threshold_failures consecutive failures.

        Args:
            threshold_failures: Minimum consecutive failures to include.

        Returns:
            List of source_id strings.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT source_id FROM source_health
                       WHERE consecutive_failures >= ?
                       ORDER BY consecutive_failures DESC""",
                    (threshold_failures,),
                ).fetchall()
            return [row["source_id"] for row in rows]
        except Exception as exc:
            logger.warning("get_failing_sources error: %s", exc)
            return []

    def disable_source(self, source_id: str, reason: str = "") -> None:
        """Disable a source in the registry and mark it in health DB.

        Args:
            source_id: Source to disable.
            reason: Human-readable reason for disabling.
        """
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            source = registry.get_source(source_id)
            if source:
                source.enabled = False
            logger.info("Disabled news source %s: %s", source_id, reason)
        except Exception as exc:
            logger.debug("Registry disable error: %s", exc)

        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE source_health
                       SET status='DOWN', disabled_reason=?
                       WHERE source_id=?""",
                    (reason[:500], source_id),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("DB disable error: %s", exc)

    def re_enable_source(self, source_id: str) -> None:
        """Re-enable a previously disabled source.

        Resets consecutive_failures to 0 and re-enables in registry.

        Args:
            source_id: Source to re-enable.
        """
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            source = registry.get_source(source_id)
            if source:
                source.enabled = True
            logger.info("Re-enabled news source %s", source_id)
        except Exception as exc:
            logger.debug("Registry re-enable error: %s", exc)

        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE source_health
                       SET status='UP', consecutive_failures=0, disabled_reason=''
                       WHERE source_id=?""",
                    (source_id,),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("DB re-enable error: %s", exc)

    def suggest_replacements(self, failing_source: Dict) -> List[Dict]:
        """Suggest alternative sources for a failing feed.

        Currently returns other enabled sources in the same category.

        Args:
            failing_source: Dict with 'source_id' and 'category' keys.

        Returns:
            List of alternative source dicts.
        """
        category = failing_source.get("category", "")
        source_id = failing_source.get("source_id", "")
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            all_sources = registry.list_sources(category=category or None, enabled_only=True)
            return [
                {"source_id": s.id, "name": s.name, "url": s.url, "category": s.category}
                for s in all_sources
                if s.id != source_id
            ][:5]
        except Exception as exc:
            logger.debug("suggest_replacements error: %s", exc)
            return []

    def get_health_report(self) -> Dict:
        """Return an aggregated health report for all monitored sources.

        Returns:
            Dict with keys: total, up, down, slow, flaky, disabled,
            failing_sources, avg_response_ms, last_run.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT source_id, url, status, consecutive_failures,
                              avg_articles_per_fetch, last_checked,
                              response_time_ms, error_message
                       FROM source_health
                       ORDER BY status, source_id"""
                ).fetchall()

            by_status: Dict[str, int] = {"UP": 0, "DOWN": 0, "SLOW": 0, "FLAKY": 0}
            total_response_ms = 0.0
            response_count = 0
            all_sources = []

            for row in rows:
                status = row["status"]
                by_status[status] = by_status.get(status, 0) + 1
                if row["response_time_ms"]:
                    total_response_ms += row["response_time_ms"]
                    response_count += 1
                all_sources.append({
                    "source_id": row["source_id"],
                    "status": status,
                    "consecutive_failures": row["consecutive_failures"],
                    "last_checked": row["last_checked"],
                    "response_time_ms": row["response_time_ms"],
                })

            avg_ms = round(total_response_ms / response_count, 1) if response_count else 0.0
            failing = [s for s in all_sources if s["consecutive_failures"] >= 3]

            return {
                "total": len(rows),
                "up": by_status.get("UP", 0),
                "down": by_status.get("DOWN", 0),
                "slow": by_status.get("SLOW", 0),
                "flaky": by_status.get("FLAKY", 0),
                "failing_sources": failing,
                "avg_response_ms": avg_ms,
                "last_run": time.time(),
            }
        except Exception as exc:
            logger.warning("get_health_report error: %s", exc)
            return {"error": str(exc)}

    def record_fetch_result(
        self,
        source_id: str,
        url: str,
        article_count: int,
        success: bool,
        error: str = "",
    ) -> None:
        """Record a fetch result for a source (called by the RSS fetcher).

        Updates consecutive_failures and avg_articles_per_fetch.

        Args:
            source_id: Source identifier.
            url: Source URL.
            article_count: How many articles were returned.
            success: Whether the fetch succeeded.
            error: Error message on failure.
        """
        existing = self._load_health(source_id)
        consecutive_failures = existing.consecutive_failures if existing else 0
        avg_articles = existing.avg_articles_per_fetch if existing else 0.0
        last_success = existing.last_success if existing else None
        now = time.time()

        if success:
            consecutive_failures = 0
            last_success = now
            # Exponential moving average (α=0.3)
            avg_articles = 0.7 * avg_articles + 0.3 * article_count
            status = "UP"
        else:
            consecutive_failures += 1
            status = "DOWN" if consecutive_failures >= 3 else "FLAKY"

        health = SourceHealth(
            source_id=source_id,
            url=url,
            status=status,
            last_success=last_success,
            consecutive_failures=consecutive_failures,
            avg_articles_per_fetch=round(avg_articles, 1),
            last_checked=now,
            error_message=error[:200] if error else "",
        )
        self._upsert_health(health)


# ── Module-level singleton ─────────────────────────────────────────────────

_monitor_instance: Optional[SourceHealthMonitor] = None
_monitor_lock = threading.Lock()


def get_source_health_monitor() -> SourceHealthMonitor:
    """Return the module-level SourceHealthMonitor singleton.

    Returns:
        Shared SourceHealthMonitor instance.
    """
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = SourceHealthMonitor()
    return _monitor_instance
