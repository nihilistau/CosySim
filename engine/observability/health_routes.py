"""Health Flask Routes — mountable Blueprint for health and service-discovery endpoints.

Mount on any Flask scene::

    from engine.observability.health_routes import health_bp
    app.register_blueprint(health_bp)

Endpoints
---------
GET  /api/health                — full system health report (cached 10 s)
GET  /api/health/<service>      — single service health probe
GET  /api/services              — all registered services
POST /api/services/discover     — filter services by type/tags/capabilities
GET  /metrics                   — Prometheus text-format metrics
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)

# Simple in-process cache for /api/health
_health_cache: dict = {"report": None, "expires_at": 0.0}


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


@health_bp.route("/api/health", methods=["GET"])
def get_health() -> Any:
    """Return the full system health report.

    The response is cached for 10 seconds to avoid hammering probes.

    Returns:
        JSON with overall status, per-service details, score, and alerts.
        HTTP 200 (healthy), 207 (degraded), or 503 (unhealthy).
    """
    try:
        now = time.monotonic()
        if _health_cache["report"] is not None and now < _health_cache["expires_at"]:
            return jsonify(_health_cache["report"])

        from engine.observability.health_checker import HealthStatus, get_health_checker

        checker = get_health_checker()
        report = checker.check_all()

        data = {
            "timestamp": report.timestamp.isoformat(),
            "overall": report.overall.value,
            "score": round(report.score, 4),
            "alerts": report.alerts,
            "services": {
                name: {
                    "status": h.status.value,
                    "latency_ms": round(h.latency_ms, 2),
                    "message": h.message,
                    "checked_at": h.checked_at.isoformat(),
                    "details": h.details,
                }
                for name, h in report.services.items()
            },
        }

        _health_cache["report"] = data
        _health_cache["expires_at"] = now + 10.0

        if report.overall == HealthStatus.HEALTHY:
            status_code = 200
        elif report.overall == HealthStatus.DEGRADED:
            status_code = 207
        else:
            status_code = 503

        return jsonify(data), status_code

    except Exception as exc:
        logger.error("Health endpoint error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /api/health/<service>
# ---------------------------------------------------------------------------


@health_bp.route("/api/health/<service_name>", methods=["GET"])
def get_service_health(service_name: str) -> Any:
    """Probe and return health for a single named service.

    Args:
        service_name: Name of the service to probe (path parameter).

    Returns:
        JSON with service_name, status, latency_ms, message, checked_at,
        and details.  HTTP 404 if the service is unknown.
    """
    try:
        from engine.observability.health_checker import get_health_checker

        checker = get_health_checker()
        health = checker.check_service(service_name)
        return jsonify(
            {
                "service_name": health.service_name,
                "status": health.status.value,
                "latency_ms": round(health.latency_ms, 2),
                "message": health.message,
                "checked_at": health.checked_at.isoformat(),
                "details": health.details,
            }
        )
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logger.error("Service health endpoint error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /api/services
# ---------------------------------------------------------------------------


@health_bp.route("/api/services", methods=["GET"])
def list_services() -> Any:
    """Return all services registered in the service registry.

    Returns:
        JSON object with ``services`` list and ``total`` count.
    """
    try:
        from engine.observability.service_registry import get_service_registry

        registry = get_service_registry()
        services = registry.list_all()
        return jsonify(
            {
                "services": [
                    {
                        "service_id": s.service_id,
                        "name": s.name,
                        "service_type": s.service_type.value,
                        "host": s.host,
                        "port": s.port,
                        "health_url": s.health_url,
                        "status": s.status,
                        "tags": s.tags,
                        "capabilities": s.capabilities,
                        "metadata": s.metadata,
                        "registered_at": s.registered_at.isoformat(),
                        "last_seen": s.last_seen.isoformat(),
                    }
                    for s in services
                ],
                "total": len(services),
            }
        )
    except Exception as exc:
        logger.error("List services endpoint error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /api/services/discover  (POST)
# ---------------------------------------------------------------------------


@health_bp.route("/api/services/discover", methods=["POST"])
def discover_services() -> Any:
    """Discover services by type, tags, or capabilities.

    Expects JSON body::

        {
            "type":         "llm",          // optional
            "tags":         ["inference"],  // optional
            "capabilities": ["vision"],     // optional
            "status":       "active"        // optional
        }

    Returns:
        JSON object with ``services``, ``total``, and ``filtered_by``.
        HTTP 400 if *type* is not a valid ServiceType.
    """
    try:
        from engine.observability.service_registry import ServiceType, get_service_registry

        data = request.get_json(silent=True) or {}

        service_type = None
        if data.get("type"):
            try:
                service_type = ServiceType(data["type"].lower())
            except ValueError:
                valid = [t.value for t in ServiceType]
                return jsonify({"error": f"Unknown service type: {data['type']!r}. Valid: {valid}"}), 400

        registry = get_service_registry()
        result = registry.discover(
            service_type=service_type,
            tags=data.get("tags"),
            capabilities=data.get("capabilities"),
            status=data.get("status"),
        )

        return jsonify(
            {
                "services": [
                    {
                        "service_id": s.service_id,
                        "name": s.name,
                        "service_type": s.service_type.value,
                        "host": s.host,
                        "port": s.port,
                        "status": s.status,
                        "tags": s.tags,
                        "capabilities": s.capabilities,
                        "metadata": s.metadata,
                    }
                    for s in result.services
                ],
                "total": result.total,
                "filtered_by": result.filtered_by,
            }
        )
    except Exception as exc:
        logger.error("Discover services endpoint error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# /metrics  (Prometheus)
# ---------------------------------------------------------------------------


@health_bp.route("/metrics", methods=["GET"])
def prometheus_metrics() -> Any:
    """Return health metrics in Prometheus text format.

    Returns:
        Prometheus-format plain-text response.
    """
    try:
        from engine.observability.health_checker import get_health_checker

        checker = get_health_checker()
        if checker.get_last_report() is None:
            checker.check_all()
        text = checker.export_prometheus()
        return Response(text, mimetype="text/plain; version=0.0.4; charset=utf-8")
    except Exception as exc:
        logger.error("Prometheus metrics endpoint error: %s", exc, exc_info=True)
        return Response(f"# Error: {exc}\n", mimetype="text/plain"), 500
