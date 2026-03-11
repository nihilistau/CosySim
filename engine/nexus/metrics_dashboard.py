"""Metrics dashboard Flask blueprint for CosySim system monitoring.

Provides API endpoints for system health, test results, task queue,
Nexus knowledge stats, and LMStudio model performance.  Serves a
single-page dashboard at ``/dashboard``.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_METRICS_DB = _DATA_DIR / "metrics.db"
_TEST_REPORTS_DIR = _DATA_DIR / "test_reports"
_TEST_TIMING_FILE = _DATA_DIR / "test_timing.json"
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


# ── Helpers ───────────────────────────────────────────────────────────

def _query_metrics_db(
    query: str,
    params: tuple = (),
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Execute a read-only query against metrics.db.

    Args:
        query: SQL SELECT statement.
        params: Bind parameters.
        limit: Max rows (appended if not already present).

    Returns:
        List of row dicts, or empty list on error.
    """
    if not _METRICS_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(_METRICS_DB), timeout=3)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchmany(limit)]
        conn.close()
        return rows
    except Exception as exc:
        logger.warning("metrics.db query failed: %s", exc)
        return []


def _load_json_file(path: Path) -> Optional[Any]:
    """Load and parse a JSON file, returning *None* on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _check_http(
    url: str,
    timeout: float = 2.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Probe an HTTP endpoint and return status info.

    Args:
        url: Full URL to GET.
        timeout: Request timeout in seconds.
        headers: Optional request headers (e.g. Bearer auth).

    Returns:
        Dict with ``ok``, ``latency_ms``, and optional ``data`` keys.
    """
    try:
        import requests as _req
        t0 = time.time()
        resp = _req.get(url, timeout=timeout, headers=headers or {})
        latency = round((time.time() - t0) * 1000, 1)
        return {
            "ok": resp.status_code < 400,
            "status_code": resp.status_code,
            "latency_ms": latency,
            "data": resp.json() if resp.headers.get(
                "content-type", ""
            ).startswith("application/json") else None,
        }
    except Exception as exc:
        return {"ok": False, "latency_ms": -1, "error": str(exc)}


def _get_lmstudio_headers() -> Dict[str, str]:
    """Build LMStudio request headers with Bearer auth from config."""
    headers: Dict[str, str] = {}
    try:
        from engine.config import get_config
        token = get_config().get("lmstudio.api_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass
    return headers


# ── Metric Collectors ─────────────────────────────────────────────────

def _collect_system_metrics() -> Dict[str, Any]:
    """Collect current system health data.

    Returns:
        Dict with service statuses, latest DB metrics, and disk info.
    """
    try:
        from engine.port_registry import get_port, SERVICE_GROUPS
    except ImportError:
        get_port = None  # type: ignore[assignment]
        SERVICE_GROUPS = {}

    # -- Service health probes ------------------------------------------------
    services: Dict[str, Dict[str, Any]] = {}
    service_checks = {
        "lmstudio": ("lmstudio", "/api/v1/models"),
        "nexus": ("nexus", "/api/health"),
        "hub": ("hub", "/api/health"),
    }

    lms_headers = _get_lmstudio_headers()

    for name, (svc, path) in service_checks.items():
        port = get_port(svc) if get_port else {"lmstudio": 1234, "nexus": 8700, "hub": 8500}.get(svc, 0)
        url = f"http://localhost:{port}{path}"
        hdrs = lms_headers if name == "lmstudio" else {}
        services[name] = _check_http(url, headers=hdrs)

    # -- Scene health probes --------------------------------------------------
    scene_ports: Dict[str, int] = {}
    if get_port:
        for svc in SERVICE_GROUPS.get("scenes", []):
            try:
                scene_ports[svc] = get_port(svc)
            except Exception:
                pass

    scenes_online = 0
    scenes_total = len(scene_ports)
    for svc, port in scene_ports.items():
        probe = _check_http(f"http://localhost:{port}/api/health", timeout=1.0)
        services[svc] = probe
        if probe.get("ok"):
            scenes_online += 1

    # -- Latest system_metrics row --------------------------------------------
    latest_hw = _query_metrics_db(
        "SELECT * FROM system_metrics ORDER BY ts DESC LIMIT 1",
    )
    hw = latest_hw[0] if latest_hw else {}

    # -- Disk usage -----------------------------------------------------------
    disk: Dict[str, Any] = {}
    try:
        import shutil
        usage = shutil.disk_usage(str(_PROJECT_ROOT))
        disk = {
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "used_gb": round(usage.used / (1024 ** 3), 1),
            "free_gb": round(usage.free / (1024 ** 3), 1),
            "percent": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        pass

    return {
        "timestamp": time.time(),
        "services": services,
        "scenes_online": scenes_online,
        "scenes_total": scenes_total,
        "hardware": hw,
        "disk": disk,
    }


def _collect_test_metrics() -> Dict[str, Any]:
    """Collect test report data.

    Returns:
        Dict with latest report, pass-rate history, and slowest tests.
    """
    reports: List[Dict[str, Any]] = []
    if _TEST_REPORTS_DIR.exists():
        for fp in sorted(_TEST_REPORTS_DIR.glob("*.json"), reverse=True):
            data = _load_json_file(fp)
            if data:
                reports.append(data)

    latest = reports[0] if reports else {}

    # Pass-rate history (last 10 reports)
    history = []
    for r in reports[:10]:
        total = r.get("total", 0)
        passed = r.get("passed", 0)
        rate = round(passed / total * 100, 1) if total else 0.0
        history.append({
            "timestamp": r.get("timestamp", ""),
            "tier": r.get("tier", ""),
            "total": total,
            "passed": passed,
            "failed": r.get("failed", 0),
            "rate": rate,
            "duration": r.get("duration_seconds", 0),
        })

    # Timing data
    timing: Dict[str, float] = {}
    if _TEST_TIMING_FILE.exists():
        timing = _load_json_file(_TEST_TIMING_FILE) or {}

    slowest = sorted(timing.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "latest": latest,
        "history": history,
        "slowest_by_file": [{"file": f, "duration": d} for f, d in slowest],
        "report_count": len(reports),
    }


def _collect_task_metrics() -> Dict[str, Any]:
    """Collect task queue statistics.

    Returns:
        Dict with pending/completed/failed counts and recent tasks.
    """
    try:
        from engine.nexus.task_scheduler import TaskScheduler
        scheduler = TaskScheduler()
        tasks = scheduler.list_tasks()
    except Exception:
        tasks = []

    counts: Dict[str, int] = {
        "pending": 0,
        "claimed": 0,
        "in_progress": 0,
        "completed": 0,
        "failed": 0,
        "blocked": 0,
        "cancelled": 0,
    }
    latencies: List[float] = []
    recent: List[Dict[str, Any]] = []

    for t in tasks:
        status = getattr(t, "status", "pending") if not isinstance(t, dict) else t.get("status", "pending")
        counts[status] = counts.get(status, 0) + 1

        # Collect latency for completed tasks
        if status == "completed":
            claimed = getattr(t, "claimed_at", None) if not isinstance(t, dict) else t.get("claimed_at")
            completed = getattr(t, "completed_at", None) if not isinstance(t, dict) else t.get("completed_at")
            if claimed and completed:
                try:
                    from datetime import datetime
                    if isinstance(claimed, str):
                        c = datetime.fromisoformat(claimed)
                        d = datetime.fromisoformat(completed)
                        latencies.append((d - c).total_seconds())
                except Exception:
                    pass

        # Recent tasks (last 10)
        title = getattr(t, "title", "") if not isinstance(t, dict) else t.get("title", "")
        created = getattr(t, "created_at", "") if not isinstance(t, dict) else t.get("created_at", "")
        recent.append({"title": title, "status": status, "created_at": str(created)})

    recent = recent[:10]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

    return {
        "counts": counts,
        "total": len(tasks),
        "avg_latency_s": avg_latency,
        "recent": recent,
    }


def _collect_nexus_metrics() -> Dict[str, Any]:
    """Collect Nexus knowledge base statistics.

    Returns:
        Dict with entry counts, categories, freshness, and cache stats.
    """
    result: Dict[str, Any] = {
        "total_entries": 0,
        "categories": {},
        "content_types": {},
        "freshness_hours": None,
        "qa_cache_size": 0,
    }
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        # Total entries by searching broadly
        all_entries = client.search("*", limit=1000)
        entries = all_entries if all_entries else []
        result["total_entries"] = len(entries)

        # Category breakdown
        cats: Dict[str, int] = {}
        types: Dict[str, int] = {}
        newest_ts = 0.0
        for e in entries:
            cat = e.get("category", "uncategorized") if isinstance(e, dict) else "uncategorized"
            cats[cat] = cats.get(cat, 0) + 1
            ct = e.get("content_type", "unknown") if isinstance(e, dict) else "unknown"
            types[ct] = types.get(ct, 0) + 1
            created = e.get("created_at", "") if isinstance(e, dict) else ""
            if created:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(str(created))
                    newest_ts = max(newest_ts, dt.timestamp())
                except Exception:
                    pass

        result["categories"] = cats
        result["content_types"] = types
        if newest_ts > 0:
            result["freshness_hours"] = round(
                (time.time() - newest_ts) / 3600, 1,
            )
    except Exception as exc:
        logger.debug("Nexus metrics collection failed: %s", exc)

    # Q&A cache stats via router if available
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        stats = router.stats()
        result["qa_cache_size"] = stats.get("cache_size", 0)
        result["router_stats"] = stats
    except Exception:
        pass

    return result


def _collect_model_metrics() -> Dict[str, Any]:
    """Collect LMStudio model performance data.

    Returns:
        Dict with loaded models, avg latency/TPS from pipeline_metrics.
    """
    # Loaded models from LMStudio API
    models: List[Dict[str, Any]] = []
    lms_headers = _get_lmstudio_headers()
    probe = _check_http(
        "http://localhost:1234/api/v1/models",
        headers=lms_headers,
    )
    if probe.get("ok") and probe.get("data"):
        raw = probe["data"]
        model_list = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(model_list, list):
            for m in model_list:
                models.append({
                    "id": m.get("id", "unknown"),
                    "type": m.get("type", ""),
                    "owned_by": m.get("owned_by", ""),
                })

    # Pipeline metrics: avg latency and TPS per model (last 100 rows)
    perf_rows = _query_metrics_db(
        "SELECT model, "
        "  AVG(latency_ms) as avg_latency, "
        "  AVG(tps) as avg_tps, "
        "  COUNT(*) as call_count, "
        "  AVG(tokens_in) as avg_tokens_in, "
        "  AVG(tokens_out) as avg_tokens_out "
        "FROM pipeline_metrics "
        "GROUP BY model "
        "ORDER BY call_count DESC",
    )

    return {
        "loaded_models": models,
        "model_count": len(models),
        "performance": perf_rows,
        "lmstudio_online": probe.get("ok", False),
    }


# ── Blueprint Factory ─────────────────────────────────────────────────

def create_dashboard_blueprint() -> Any:
    """Create and return the metrics dashboard Flask blueprint.

    Returns:
        Flask Blueprint with metrics API endpoints and dashboard page,
        or ``None`` if Flask is unavailable.
    """
    try:
        from flask import Blueprint, jsonify, render_template, request
    except ImportError:
        logger.warning("Flask not installed — metrics dashboard unavailable")
        return None

    bp = Blueprint(
        "metrics_dashboard",
        __name__,
        template_folder=str(_TEMPLATE_DIR),
    )

    # ── API endpoints ─────────────────────────────────────────────────

    @bp.route("/api/metrics/system")
    def system_metrics() -> Any:
        """Current system health: LMStudio, Nexus, GPU, disk, services."""
        try:
            return jsonify(_collect_system_metrics())
        except Exception as exc:
            logger.error("system_metrics error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/metrics/tests")
    def test_metrics() -> Any:
        """Test results: latest report, pass rate history, slowest tests."""
        try:
            return jsonify(_collect_test_metrics())
        except Exception as exc:
            logger.error("test_metrics error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/metrics/tasks")
    def task_metrics() -> Any:
        """Task queue: pending, completed, failed, avg latency."""
        try:
            return jsonify(_collect_task_metrics())
        except Exception as exc:
            logger.error("task_metrics error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/metrics/nexus")
    def nexus_metrics() -> Any:
        """Nexus knowledge: entry count, categories, freshness, cache."""
        try:
            return jsonify(_collect_nexus_metrics())
        except Exception as exc:
            logger.error("nexus_metrics error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/metrics/models")
    def model_metrics() -> Any:
        """LMStudio models: loaded, latency, TPS, usage counts."""
        try:
            return jsonify(_collect_model_metrics())
        except Exception as exc:
            logger.error("model_metrics error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/metrics/overview")
    def overview() -> Any:
        """Combined overview of all metrics for the dashboard."""
        result: Dict[str, Any] = {}
        for key, collector in (
            ("system", _collect_system_metrics),
            ("tests", _collect_test_metrics),
            ("tasks", _collect_task_metrics),
            ("nexus", _collect_nexus_metrics),
            ("models", _collect_model_metrics),
        ):
            try:
                result[key] = collector()
            except Exception as exc:
                logger.error("overview/%s error: %s", key, exc)
                result[key] = {"error": str(exc)}
        return jsonify(result)

    # ── Dashboard page ────────────────────────────────────────────────

    @bp.route("/dashboard")
    def dashboard_page() -> Any:
        """Render the metrics dashboard HTML page."""
        try:
            return render_template("dashboard.html")
        except Exception as exc:
            logger.error("dashboard render error: %s", exc)
            return f"<h1>Dashboard Error</h1><pre>{exc}</pre>", 500

    return bp
