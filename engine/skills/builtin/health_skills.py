"""Health Skills — MCP skill pack for health monitoring and service discovery.

Pack: ``health``
Category: SYSTEM

Skills
------
1.  get_system_health           — full health report with composite score
2.  check_service_health        — single service probe
3.  get_health_history          — historical health data from SQLite
4.  get_health_alerts           — recent UNHEALTHY/DEGRADED events
5.  register_service            — register in the service discovery registry
6.  discover_services           — find services by type / capability
7.  deregister_service          — remove from registry
8.  heartbeat_service           — keep-alive ping
9.  export_prometheus_metrics   — Prometheus text-format metrics
10. get_service_capabilities    — list what a service can do
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import SkillCategory, skill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. get_system_health
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description="Get the full system health report including per-service status and a composite score (0-1).",
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=1.0,
    tags=["health", "monitoring", "system"],
)
def get_system_health() -> str:
    """Return full health report with composite score.

    Returns:
        Formatted string with overall status, per-service breakdown, and alerts.
    """
    from engine.observability.health_checker import get_health_checker

    checker = get_health_checker()
    report = checker.check_all()
    _STATUS_ICONS = {
        "healthy": "✅",
        "degraded": "⚠️",
        "unhealthy": "❌",
        "unknown": "❓",
    }
    parts = [
        f"🏥 System Health: {report.overall.value.upper()} (score: {report.score:.2f})",
        f"📊 Checked at: {report.timestamp.strftime('%H:%M:%S')}",
    ]
    for name, health in sorted(report.services.items()):
        icon = _STATUS_ICONS.get(health.status.value, "❓")
        parts.append(
            f"  {icon} {name}: {health.message} ({health.latency_ms:.0f} ms)"
        )
    if report.alerts:
        parts.append("\n⚠️ Alerts:")
        for alert in report.alerts:
            parts.append(f"  • {alert}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 2. check_service_health
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description=(
        "Check the health of a specific service by name "
        "(e.g. lmstudio, nexus, pm2, disk_space)."
    ),
    category=SkillCategory.SYSTEM,
    cooldown=2.0,
    cost=0.5,
    tags=["health", "monitoring", "service"],
)
def check_service_health(service_name: str) -> str:
    """Probe a single service and return its health status.

    Args:
        service_name: Name of the service to probe.

    Returns:
        Formatted status string with latency and details.
    """
    from engine.observability.health_checker import get_health_checker

    checker = get_health_checker()
    try:
        health = checker.check_service(service_name)
    except KeyError as exc:
        return f"❌ Unknown service: {service_name}. {exc}"

    icon = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "❌", "unknown": "❓"}.get(
        health.status.value, "❓"
    )
    lines = [
        f"{icon} {service_name}: {health.status.value.upper()}",
        f"  Message : {health.message}",
        f"  Latency : {health.latency_ms:.0f} ms",
        f"  Checked : {health.checked_at.strftime('%H:%M:%S')}",
    ]
    if health.details:
        lines.append(f"  Details : {json.dumps(health.details, default=str)[:300]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. get_health_history
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description="Get historical health data for the past N hours (default 24).",
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=1.0,
    tags=["health", "history", "monitoring"],
)
def get_health_history(hours: int = 24) -> str:
    """Return health history from SQLite for the past N hours.

    Args:
        hours: Number of hours to look back (default 24).

    Returns:
        Summary of up to 10 most recent records.
    """
    from engine.observability.health_checker import get_health_checker

    checker = get_health_checker()
    history = checker.get_history(hours=hours)
    if not history:
        return f"No health history found for the past {hours} hour(s)."

    lines = [f"📈 Health History — last {hours}h ({len(history)} records):"]
    for entry in history[:10]:
        bar_len = int(entry["score"] * 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        lines.append(
            f"  {entry['timestamp'][:19]} | {entry['overall_status']:10s} | [{bar}] {entry['score']:.2f}"
        )
    if len(history) > 10:
        lines.append(f"  … and {len(history) - 10} more records")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. get_health_alerts
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description=(
        "Get recent health alerts — services that went UNHEALTHY or DEGRADED "
        "in the past N hours (default 1)."
    ),
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=0.5,
    tags=["health", "alerts", "monitoring"],
)
def get_health_alerts(hours: int = 1) -> str:
    """Return list of recent unhealthy/degraded events from health history.

    Args:
        hours: How many hours back to scan (default 1).

    Returns:
        Formatted alert summary or confirmation that no alerts exist.
    """
    from engine.observability.health_checker import get_health_checker

    checker = get_health_checker()
    alerts = checker.get_alerts(hours=hours)
    if not alerts:
        return f"✅ No health alerts in the past {hours} hour(s)."

    lines = [f"⚠️ Health Alerts — last {hours}h ({len(alerts)} event(s)):"]
    for event in alerts:
        lines.append(f"\n  🕐 {event['timestamp'][:19]} (status: {event['overall_status']})")
        for alert in event["alerts"]:
            lines.append(f"    • {alert}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. register_service
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description=(
        "Register a service in the discovery registry. "
        "service_type must be one of: scene, agent, llm, skill_pack, tool, external. "
        "capabilities_json is a JSON array string, e.g. '[\"inference\",\"vision\"]'."
    ),
    category=SkillCategory.SYSTEM,
    cooldown=1.0,
    cost=0.5,
    tags=["discovery", "registry", "service"],
)
def register_service(
    name: str,
    service_type: str,
    host: str,
    port: int,
    capabilities_json: str = "[]",
) -> str:
    """Register a service in the service discovery registry.

    Args:
        name: Human-readable service name.
        service_type: ServiceType value string.
        host: Hostname or IP.
        port: TCP port (0 if not applicable).
        capabilities_json: JSON array of capability strings.

    Returns:
        Confirmation with assigned service_id, or an error message.
    """
    from datetime import datetime

    from engine.observability.service_registry import (
        ServiceRecord,
        ServiceType,
        get_service_registry,
    )

    try:
        stype = ServiceType(service_type.lower())
    except ValueError:
        valid = [t.value for t in ServiceType]
        return f"❌ Invalid service_type {service_type!r}. Valid: {valid}"

    try:
        capabilities = json.loads(capabilities_json)
    except json.JSONDecodeError as exc:
        return f"❌ Invalid capabilities_json: {exc}"

    registry = get_service_registry()
    import uuid

    service_id = f"user-{name}-{uuid.uuid4().hex[:8]}"
    now = datetime.now()
    record = ServiceRecord(
        service_id=service_id,
        name=name,
        service_type=stype,
        host=host,
        port=port,
        health_url=f"http://{host}:{port}/health" if port else "",
        metadata={"registered_by": "health_skill"},
        registered_at=now,
        last_seen=now,
        status="active",
        tags=[service_type.lower()],
        capabilities=capabilities,
    )
    registry.register(record)
    return f"✅ Registered service '{name}' as {service_type} (id: {service_id})"


# ---------------------------------------------------------------------------
# 6. discover_services
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description=(
        "Discover services in the registry. "
        "Optionally filter by service_type (scene/agent/llm/skill_pack/tool/external) "
        "and/or capability string."
    ),
    category=SkillCategory.SYSTEM,
    cooldown=1.0,
    cost=0.5,
    tags=["discovery", "registry", "service"],
)
def discover_services(service_type: str = "", capability: str = "") -> str:
    """Find services in the registry matching type and/or capability.

    Args:
        service_type: Optional ServiceType filter string.
        capability: Optional capability string filter.

    Returns:
        Formatted list of matching services.
    """
    from engine.observability.service_registry import ServiceType, get_service_registry

    registry = get_service_registry()
    stype = None
    if service_type:
        try:
            stype = ServiceType(service_type.lower())
        except ValueError:
            valid = [t.value for t in ServiceType]
            return f"❌ Invalid service_type {service_type!r}. Valid: {valid}"

    caps = [capability] if capability else None
    result = registry.discover(service_type=stype, capabilities=caps)

    if not result.services:
        return f"No services found matching filters: {result.filtered_by or '(none)'}"

    lines = [f"🔍 Discovered {result.total} service(s):"]
    for svc in result.services:
        caps_str = ", ".join(svc.capabilities) if svc.capabilities else "none"
        lines.append(
            f"  • {svc.name} ({svc.service_type.value}) @ {svc.host}:{svc.port} "
            f"[{svc.status}] caps: {caps_str}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. deregister_service
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description="Deregister a service from the discovery registry by service_id.",
    category=SkillCategory.SYSTEM,
    cooldown=1.0,
    cost=0.5,
    tags=["discovery", "registry", "service"],
)
def deregister_service(service_id: str) -> str:
    """Remove a service from the registry.

    Args:
        service_id: ID of the service to remove.

    Returns:
        Confirmation or error message.
    """
    from engine.observability.service_registry import get_service_registry

    registry = get_service_registry()
    removed = registry.deregister(service_id)
    if removed:
        return f"✅ Deregistered service: {service_id}"
    return f"❌ Service not found: {service_id}"


# ---------------------------------------------------------------------------
# 8. heartbeat_service
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description="Send a keep-alive heartbeat for a registered service by service_id.",
    category=SkillCategory.SYSTEM,
    cooldown=0.5,
    cost=0.1,
    tags=["discovery", "registry", "heartbeat"],
)
def heartbeat_service(service_id: str) -> str:
    """Update last_seen for a registered service (keep-alive ping).

    Args:
        service_id: ID of the service to heartbeat.

    Returns:
        Confirmation or error message.
    """
    from engine.observability.service_registry import get_service_registry

    registry = get_service_registry()
    ok = registry.heartbeat(service_id)
    if ok:
        return f"💓 Heartbeat recorded for service: {service_id}"
    return f"❌ Service not found: {service_id}"


# ---------------------------------------------------------------------------
# 9. export_prometheus_metrics
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description="Export current system health metrics in Prometheus text format.",
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=0.5,
    tags=["health", "prometheus", "metrics"],
)
def export_prometheus_metrics() -> str:
    """Return Prometheus-formatted health metrics.

    Triggers check_all() if no report has been generated yet.

    Returns:
        Prometheus text-format metrics string.
    """
    from engine.observability.health_checker import get_health_checker

    checker = get_health_checker()
    if checker.get_last_report() is None:
        checker.check_all()
    return checker.export_prometheus()


# ---------------------------------------------------------------------------
# 10. get_service_capabilities
# ---------------------------------------------------------------------------


@skill(
    pack="health",
    description="List the capabilities and metadata for a registered service by service_id.",
    category=SkillCategory.SYSTEM,
    cooldown=1.0,
    cost=0.2,
    tags=["discovery", "registry", "capabilities"],
)
def get_service_capabilities(service_id: str) -> str:
    """Show the capabilities registered for a given service.

    Args:
        service_id: ID of the service to inspect.

    Returns:
        Formatted capability list, or an error message if not found.
    """
    from engine.observability.service_registry import get_service_registry

    registry = get_service_registry()
    record = registry.get(service_id)
    if record is None:
        return f"❌ Service not found: {service_id}"

    caps = record.capabilities
    tags = record.tags
    lines = [
        f"🛠 Service: {record.name} ({record.service_type.value})",
        f"   ID          : {record.service_id}",
        f"   Status      : {record.status}",
        f"   Capabilities: {', '.join(caps) if caps else 'none'}",
        f"   Tags        : {', '.join(tags) if tags else 'none'}",
        f"   Host        : {record.host}:{record.port}",
        f"   Last seen   : {record.last_seen.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines)
