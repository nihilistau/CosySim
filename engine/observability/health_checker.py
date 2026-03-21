"""Health Check Aggregator — unified health polling for all system services.

Provides a singleton HealthChecker that polls every registered service probe
concurrently, calculates a composite health score, persists results to SQLite,
and can emit Prometheus-format metrics.

Usage::

    from engine.observability.health_checker import get_health_checker

    checker = get_health_checker()
    report  = checker.check_all()
    print(report.score, report.overall)
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import threading
import time as _time_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/health_history.db"


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------


class HealthStatus(Enum):
    """Health status for a service or the overall system."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealth:
    """Health status snapshot for a single service.

    Attributes:
        service_name: Unique service identifier.
        status: Current HealthStatus.
        latency_ms: Probe round-trip time in milliseconds.
        message: Human-readable status summary.
        checked_at: When this probe ran.
        details: Arbitrary probe-specific metadata.
    """

    service_name: str
    status: HealthStatus
    latency_ms: float
    message: str
    checked_at: datetime
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealthReport:
    """Composite health report for all monitored services.

    Attributes:
        timestamp: When this report was generated.
        overall: Aggregate HealthStatus derived from score.
        services: Per-service health results.
        score: Float 0–1 (1 = fully healthy).
        alerts: List of human-readable alert messages.
    """

    timestamp: datetime
    overall: HealthStatus
    services: Dict[str, ServiceHealth]
    score: float
    alerts: List[str]


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------


class HealthChecker:
    """Unified health check system that polls all system services.

    Instantiate via :func:`get_health_checker` (singleton).
    """

    # Optional services don't reduce score below DEGRADED (0.5)
    _OPTIONAL_SERVICES: frozenset = frozenset({"comfyui", "tts"})

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        """Initialise the HealthChecker.

        Args:
            db_path: Path to SQLite database for health history.
        """
        self._db_path = db_path
        self._lock = threading.Lock()
        self._last_report: Optional[SystemHealthReport] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._custom_probes: Dict[str, tuple] = {}  # name -> (fn, timeout)
        self._init_db()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create SQLite table for health history if absent."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS health_reports (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp      TEXT    NOT NULL,
                    overall_status TEXT    NOT NULL,
                    score          REAL    NOT NULL,
                    services_json  TEXT    NOT NULL,
                    alerts_json    TEXT    NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_health_timestamp "
                "ON health_reports (timestamp)"
            )
            conn.commit()

    def _persist_report(self, report: SystemHealthReport) -> None:
        """Persist a SystemHealthReport to SQLite.

        Args:
            report: The report to store.
        """
        try:
            services_json = json.dumps(
                {
                    name: {
                        "status": h.status.value,
                        "latency_ms": h.latency_ms,
                        "message": h.message,
                        "checked_at": h.checked_at.isoformat(),
                        "details": h.details,
                    }
                    for name, h in report.services.items()
                }
            )
            alerts_json = json.dumps(report.alerts)
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO health_reports
                        (timestamp, overall_status, score, services_json, alerts_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        report.timestamp.isoformat(),
                        report.overall.value,
                        report.score,
                        services_json,
                        alerts_json,
                    ),
                )
                conn.execute(
                    "DELETE FROM health_reports WHERE timestamp < ?", (cutoff,)
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist health report: %s", exc)

    # ------------------------------------------------------------------
    # Score helpers
    # ------------------------------------------------------------------

    def _status_to_score(self, status: HealthStatus) -> float:
        """Map HealthStatus to a numeric score (0–1).

        Args:
            status: HealthStatus enum value.

        Returns:
            Float score.
        """
        return {
            HealthStatus.HEALTHY: 1.0,
            HealthStatus.DEGRADED: 0.5,
            HealthStatus.UNKNOWN: 0.3,
            HealthStatus.UNHEALTHY: 0.0,
        }[status]

    def score_to_status(self, score: float) -> HealthStatus:
        """Convert a numeric health score to a HealthStatus.

        Args:
            score: Float between 0.0 and 1.0.

        Returns:
            HEALTHY if score >= 0.9, DEGRADED if >= 0.6, else UNHEALTHY.
        """
        if score >= 0.9:
            return HealthStatus.HEALTHY
        if score >= 0.6:
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY

    def _calculate_score(self, services: Dict[str, ServiceHealth]) -> float:
        """Calculate composite health score.

        Optional services (comfyui, tts) are floor-clamped at 0.5 so they
        cannot reduce the overall score below DEGRADED.

        Args:
            services: Map of service name → ServiceHealth.

        Returns:
            Score between 0.0 and 1.0.
        """
        if not services:
            return 1.0
        scores = []
        for name, health in services.items():
            s = self._status_to_score(health.status)
            if name in self._OPTIONAL_SERVICES:
                s = max(s, 0.5)
            scores.append(s)
        return sum(scores) / len(scores)

    def _build_alerts(self, services: Dict[str, ServiceHealth]) -> List[str]:
        """Build alert messages for unhealthy or degraded services.

        Args:
            services: Map of service name → ServiceHealth.

        Returns:
            List of alert strings.
        """
        alerts = []
        for name, health in services.items():
            if health.status == HealthStatus.UNHEALTHY:
                alerts.append(f"UNHEALTHY: {name} — {health.message}")
            elif health.status == HealthStatus.DEGRADED:
                alerts.append(f"DEGRADED: {name} — {health.message}")
        return alerts

    # ------------------------------------------------------------------
    # Built-in service probes
    # ------------------------------------------------------------------

    def _check_lmstudio(self) -> ServiceHealth:
        """Probe LMStudio REST API.

        Returns:
            ServiceHealth for lmstudio.
        """
        start = _time_module.monotonic()
        try:
            import urllib.request

            from engine.config import get_config

            cfg = get_config()
            base = cfg.get("lmstudio.url", "http://localhost:1234")
            url = f"{base}/api/v1/models"
            token = cfg.get("lmstudio.api_token", "")
            req = urllib.request.Request(url)
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = data.get("data", [])
            latency = (_time_module.monotonic() - start) * 1000
            count = len(models)
            if count > 0:
                return ServiceHealth(
                    service_name="lmstudio",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message=f"{count} model(s) loaded",
                    checked_at=datetime.now(),
                    details={
                        "model_count": count,
                        "models": [m.get("id", "") for m in models[:3]],
                    },
                )
            return ServiceHealth(
                service_name="lmstudio",
                status=HealthStatus.DEGRADED,
                latency_ms=latency,
                message="No models loaded",
                checked_at=datetime.now(),
                details={"model_count": 0},
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="lmstudio",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_nexus(self) -> ServiceHealth:
        """Probe Nexus knowledge base with a 3-second timeout.

        Returns:
            ServiceHealth for nexus.
        """
        start = _time_module.monotonic()
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            result_holder: List[Any] = []

            def _do_search() -> None:
                result_holder.append(client.search("health"))

            t = threading.Thread(target=_do_search, daemon=True)
            t.start()
            t.join(timeout=3.0)
            latency = (_time_module.monotonic() - start) * 1000
            if t.is_alive():
                return ServiceHealth(
                    service_name="nexus",
                    status=HealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Search timed out after 3s",
                    checked_at=datetime.now(),
                )
            results = result_holder[0] if result_holder else []
            return ServiceHealth(
                service_name="nexus",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message=f"Nexus responsive, {len(results)} result(s)",
                checked_at=datetime.now(),
                details={"result_count": len(results)},
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="nexus",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_pm2(self) -> ServiceHealth:
        """Probe PM2 process manager via ``pm2 jlist``.

        Returns:
            ServiceHealth for pm2.
        """
        start = _time_module.monotonic()
        try:
            result = subprocess.run(
                ["pm2", "jlist"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            latency = (_time_module.monotonic() - start) * 1000
            if result.returncode != 0:
                return ServiceHealth(
                    service_name="pm2",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message=f"pm2 jlist failed: {result.stderr.strip()}",
                    checked_at=datetime.now(),
                )
            try:
                processes = json.loads(result.stdout)
            except json.JSONDecodeError:
                processes = []
            online = sum(
                1
                for p in processes
                if p.get("pm2_env", {}).get("status") == "online"
            )
            errored = sum(
                1
                for p in processes
                if p.get("pm2_env", {}).get("status") == "errored"
            )
            total = len(processes)
            status = HealthStatus.HEALTHY if errored == 0 else HealthStatus.DEGRADED
            return ServiceHealth(
                service_name="pm2",
                status=status,
                latency_ms=latency,
                message=f"{online}/{total} online, {errored} errored",
                checked_at=datetime.now(),
                details={"total": total, "online": online, "errored": errored},
            )
        except FileNotFoundError:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="pm2",
                status=HealthStatus.UNKNOWN,
                latency_ms=latency,
                message="pm2 not found in PATH",
                checked_at=datetime.now(),
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="pm2",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_comfyui(self) -> ServiceHealth:
        """Probe ComfyUI image service (optional — skip if unreachable).

        Returns:
            ServiceHealth for comfyui.
        """
        start = _time_module.monotonic()
        try:
            import urllib.request

            with urllib.request.urlopen(
                "http://localhost:8188/system_stats", timeout=2
            ) as resp:
                data = json.loads(resp.read())
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="comfyui",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="ComfyUI reachable",
                checked_at=datetime.now(),
                details=data,
            )
        except Exception:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="comfyui",
                status=HealthStatus.UNKNOWN,
                latency_ms=latency,
                message="ComfyUI unreachable (optional service)",
                checked_at=datetime.now(),
            )

    def _check_tts(self) -> ServiceHealth:
        """Probe TTS service (optional — skip if unreachable).

        Returns:
            ServiceHealth for tts.
        """
        start = _time_module.monotonic()
        try:
            import urllib.request

            with urllib.request.urlopen(
                "http://localhost:5050/health", timeout=2
            ) as resp:
                data = json.loads(resp.read())
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="tts",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="TTS service reachable",
                checked_at=datetime.now(),
                details=data,
            )
        except Exception:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="tts",
                status=HealthStatus.UNKNOWN,
                latency_ms=latency,
                message="TTS unreachable (optional service)",
                checked_at=datetime.now(),
            )

    def _check_secret_manager(self) -> ServiceHealth:
        """Probe SecretManager via export_safe_report().

        Returns:
            ServiceHealth for secret_manager.
        """
        start = _time_module.monotonic()
        try:
            from engine.security.secret_manager import get_secret_manager

            sm = get_secret_manager()
            report = sm.export_safe_report()
            latency = (_time_module.monotonic() - start) * 1000
            details = report if isinstance(report, dict) else {"report": str(report)}
            return ServiceHealth(
                service_name="secret_manager",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="SecretManager operational",
                checked_at=datetime.now(),
                details=details,
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="secret_manager",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_rate_limiter(self) -> ServiceHealth:
        """Probe RateLimiter via get_metrics().

        Returns:
            ServiceHealth for rate_limiter.
        """
        start = _time_module.monotonic()
        try:
            from engine.security.rate_limiter import get_rate_limiter

            rl = get_rate_limiter()
            metrics = rl.get_metrics()
            latency = (_time_module.monotonic() - start) * 1000
            details = metrics if isinstance(metrics, dict) else {"metrics": str(metrics)}
            return ServiceHealth(
                service_name="rate_limiter",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="RateLimiter operational",
                checked_at=datetime.now(),
                details=details,
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="rate_limiter",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_structured_logger(self) -> ServiceHealth:
        """Probe StructuredLogger via get_error_summary(hours=1).

        Returns:
            ServiceHealth for structured_logger.
        """
        start = _time_module.monotonic()
        try:
            from engine.observability.structured_logger import get_structured_logger

            sl = get_structured_logger()
            summary = sl.get_error_summary(hours=1)
            latency = (_time_module.monotonic() - start) * 1000
            details = summary if isinstance(summary, dict) else {"summary": str(summary)}
            return ServiceHealth(
                service_name="structured_logger",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="StructuredLogger operational",
                checked_at=datetime.now(),
                details=details,
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="structured_logger",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_integration_runner(self) -> ServiceHealth:
        """Probe IntegrationRunner via probe_service("lmstudio").

        Returns:
            ServiceHealth for integration_runner.
        """
        start = _time_module.monotonic()
        try:
            from engine.testing.integration_runner import get_integration_runner

            ir = get_integration_runner()
            available = ir.probe_service("lmstudio")
            latency = (_time_module.monotonic() - start) * 1000
            svc_status = HealthStatus.HEALTHY if available else HealthStatus.DEGRADED
            return ServiceHealth(
                service_name="integration_runner",
                status=svc_status,
                latency_ms=latency,
                message=f"IntegrationRunner operational, lmstudio={'up' if available else 'down'}",
                checked_at=datetime.now(),
                details={"lmstudio_probe": available},
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="integration_runner",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    def _check_disk_space(self) -> ServiceHealth:
        """Check available disk space for the data/ directory.

        Returns:
            ServiceHealth for disk_space; UNHEALTHY at <100 MB, DEGRADED at <1 GB.
        """
        start = _time_module.monotonic()
        try:
            data_path = Path("data")
            if not data_path.exists():
                data_path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(str(data_path))
            free_bytes = usage.free
            free_gb = free_bytes / (1024**3)
            free_mb = free_bytes / (1024**2)
            latency = (_time_module.monotonic() - start) * 1000

            if free_bytes < 100 * 1024 * 1024:
                status = HealthStatus.UNHEALTHY
                msg = f"Critical: only {free_mb:.0f} MB free"
            elif free_bytes < 1024 * 1024 * 1024:
                status = HealthStatus.DEGRADED
                msg = f"Warning: only {free_mb:.0f} MB free"
            else:
                status = HealthStatus.HEALTHY
                msg = f"{free_gb:.1f} GB free"

            return ServiceHealth(
                service_name="disk_space",
                status=status,
                latency_ms=latency,
                message=msg,
                checked_at=datetime.now(),
                details={
                    "free_bytes": free_bytes,
                    "free_gb": round(free_gb, 2),
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                },
            )
        except Exception as exc:
            latency = (_time_module.monotonic() - start) * 1000
            return ServiceHealth(
                service_name="disk_space",
                status=HealthStatus.UNKNOWN,
                latency_ms=latency,
                message=str(exc),
                checked_at=datetime.now(),
            )

    # ------------------------------------------------------------------
    # Probe registry helpers
    # ------------------------------------------------------------------

    def _all_probes(self) -> Dict[str, Callable]:
        """Return all built-in plus registered custom probes.

        Returns:
            Dict mapping service name to probe callable.
        """
        probes: Dict[str, Callable] = {
            "lmstudio": self._check_lmstudio,
            "nexus": self._check_nexus,
            "pm2": self._check_pm2,
            "comfyui": self._check_comfyui,
            "tts": self._check_tts,
            "secret_manager": self._check_secret_manager,
            "rate_limiter": self._check_rate_limiter,
            "structured_logger": self._check_structured_logger,
            "integration_runner": self._check_integration_runner,
            "disk_space": self._check_disk_space,
        }
        for name, (fn, _timeout) in self._custom_probes.items():
            probes[name] = fn
        return probes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self, parallel: bool = True) -> SystemHealthReport:
        """Run all service probes and return a composite health report.

        Args:
            parallel: If True (default), run probes concurrently via
                ThreadPoolExecutor.

        Returns:
            SystemHealthReport with all service health data and overall score.
        """
        probes = self._all_probes()
        services: Dict[str, ServiceHealth] = {}

        if parallel:
            with ThreadPoolExecutor(max_workers=min(len(probes), 10)) as executor:
                futures = {executor.submit(fn): name for name, fn in probes.items()}
                for future in as_completed(futures, timeout=30):
                    name = futures[future]
                    try:
                        services[name] = future.result(timeout=30)
                    except Exception as exc:
                        services[name] = ServiceHealth(
                            service_name=name,
                            status=HealthStatus.UNKNOWN,
                            latency_ms=0.0,
                            message=f"Probe failed: {exc}",
                            checked_at=datetime.now(),
                        )
        else:
            for name, fn in probes.items():
                try:
                    services[name] = fn()
                except Exception as exc:
                    services[name] = ServiceHealth(
                        service_name=name,
                        status=HealthStatus.UNKNOWN,
                        latency_ms=0.0,
                        message=f"Probe failed: {exc}",
                        checked_at=datetime.now(),
                    )

        score = self._calculate_score(services)
        overall = self.score_to_status(score)
        alerts = self._build_alerts(services)

        report = SystemHealthReport(
            timestamp=datetime.now(),
            overall=overall,
            services=services,
            score=score,
            alerts=alerts,
        )

        with self._lock:
            self._last_report = report

        self._persist_report(report)
        return report

    def check_service(self, name: str) -> ServiceHealth:
        """Probe a single registered service.

        Args:
            name: Service name (e.g., ``"lmstudio"``, ``"nexus"``).

        Returns:
            ServiceHealth for the named service.

        Raises:
            KeyError: If *name* is not a registered probe.
        """
        probes = self._all_probes()
        if name not in probes:
            raise KeyError(
                f"Unknown service: {name!r}. Available: {sorted(probes)}"
            )
        return probes[name]()

    def get_last_report(self) -> Optional[SystemHealthReport]:
        """Return the most recent cached health report.

        Returns:
            Last SystemHealthReport, or None if no report has been run.
        """
        with self._lock:
            return self._last_report

    def watch(
        self,
        interval_seconds: float = 60.0,
        callback: Optional[Callable[[SystemHealthReport], None]] = None,
    ) -> None:
        """Start a background thread that periodically calls :meth:`check_all`.

        Calling ``watch`` when a watcher is already running is a no-op.

        Args:
            interval_seconds: How often to run check_all (default 60 s).
            callback: Optional callable invoked with each new report.
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            logger.warning("Health watcher already running; ignoring second watch() call")
            return

        self._stop_event.clear()

        def _run() -> None:
            while not self._stop_event.is_set():
                try:
                    report = self.check_all()
                    if callback:
                        callback(report)
                except Exception as exc:
                    logger.error("Health watcher error: %s", exc, exc_info=True)
                self._stop_event.wait(timeout=interval_seconds)

        self._watcher_thread = threading.Thread(
            target=_run, daemon=True, name="health-watcher"
        )
        self._watcher_thread.start()
        logger.info("Health watcher started (interval=%ss)", interval_seconds)

    def stop_watch(self) -> None:
        """Stop the background health-check watcher thread."""
        self._stop_event.set()
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=5.0)
        logger.info("Health watcher stopped")

    def get_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Query SQLite for historical health reports.

        Args:
            hours: How many hours back to include (default 24).

        Returns:
            List of report dicts ordered by timestamp descending.
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT timestamp, overall_status, score, services_json, alerts_json
                    FROM health_reports
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                    """,
                    (cutoff,),
                ).fetchall()
            return [
                {
                    "timestamp": row["timestamp"],
                    "overall_status": row["overall_status"],
                    "score": row["score"],
                    "services": json.loads(row["services_json"]),
                    "alerts": json.loads(row["alerts_json"]),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("Failed to query health history: %s", exc)
            return []

    def get_alerts(self, hours: int = 1) -> List[Dict[str, Any]]:
        """Return report entries with active alerts from the last N hours.

        Args:
            hours: How many hours back to scan (default 1).

        Returns:
            List of dicts containing timestamp, alerts, overall_status, score.
        """
        history = self.get_history(hours=hours)
        return [
            {
                "timestamp": entry["timestamp"],
                "alerts": entry["alerts"],
                "overall_status": entry["overall_status"],
                "score": entry["score"],
            }
            for entry in history
            if entry["alerts"]
        ]

    def register_probe(
        self,
        name: str,
        fn: Callable[[], ServiceHealth],
        timeout: float = 5.0,
    ) -> None:
        """Register a custom service probe.

        Args:
            name: Unique service name for this probe.
            fn: Callable that accepts no arguments and returns a ServiceHealth.
            timeout: Advisory probe timeout in seconds (default 5).
        """
        self._custom_probes[name] = (fn, timeout)
        logger.info("Registered custom health probe: %s", name)

    def export_prometheus(self) -> str:
        """Emit current health metrics in Prometheus text format.

        Returns:
            Prometheus-formatted multi-line string.  Returns a comment line if
            no report has been generated yet.
        """
        report = self._last_report
        if report is None:
            return "# No health data available — run check_all() first\n"

        lines = [
            "# HELP cosysim_health_score Overall system health score (0-1)",
            "# TYPE cosysim_health_score gauge",
            f"cosysim_health_score {report.score:.4f}",
            "",
            "# HELP cosysim_service_healthy Per-service health (1=healthy, 0.5=degraded, 0=unhealthy)",
            "# TYPE cosysim_service_healthy gauge",
        ]
        for name, health in report.services.items():
            score = self._status_to_score(health.status)
            lines.append(f'cosysim_service_healthy{{service="{name}"}} {score:.1f}')

        lines += [
            "",
            "# HELP cosysim_service_latency_ms Probe round-trip latency in milliseconds",
            "# TYPE cosysim_service_latency_ms gauge",
        ]
        for name, health in report.services.items():
            lines.append(
                f'cosysim_service_latency_ms{{service="{name}"}} {health.latency_ms:.2f}'
            )

        lines += [
            "",
            "# HELP cosysim_alerts_total Number of active service alerts",
            "# TYPE cosysim_alerts_total gauge",
            f"cosysim_alerts_total {len(report.alerts)}",
            "",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_checker_instance: Optional[HealthChecker] = None
_checker_lock = threading.Lock()


def get_health_checker(db_path: str = _DEFAULT_DB_PATH) -> HealthChecker:
    """Return the global HealthChecker singleton.

    Args:
        db_path: SQLite file path (used only on first call).

    Returns:
        The module-level HealthChecker instance.
    """
    global _checker_instance
    if _checker_instance is None:
        with _checker_lock:
            if _checker_instance is None:
                _checker_instance = HealthChecker(db_path=db_path)
    return _checker_instance
