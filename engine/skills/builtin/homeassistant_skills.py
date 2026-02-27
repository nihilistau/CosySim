"""
Home Assistant Skills — @skill-decorated functions for agent HA interaction.

Agents can read sensors, control devices, send notifications, query state,
and trigger automations in Home Assistant via these skills.

All skills use the singleton HomeAssistantClient from
``engine.integrations.homeassistant``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _ha() -> Any:
    """Lazy import to avoid circular dependencies."""
    from engine.integrations.homeassistant import get_ha_client
    return get_ha_client()


# ── Connection & Discovery ──────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Connect to Home Assistant and discover entities",
    category="system",
    tags=["homeassistant", "connect", "discover"],
)
def ha_connect() -> str:
    """Connect to the Home Assistant instance and discover all entities."""
    result = _ha().connect()
    return json.dumps(result)


@skill(
    pack="homeassistant",
    description="List Home Assistant entities, optionally filtered by domain or search term",
    category="system",
    tags=["homeassistant", "entities", "list"],
)
def ha_list_entities(domain: str = "", search: str = "") -> str:
    """List HA entities with current state. Filter by domain (sensor, light, switch) or search term."""
    entities = _ha().list_entities(
        domain=domain or None,
        search=search or None,
    )
    return json.dumps({"count": len(entities), "entities": entities[:50]})


@skill(
    pack="homeassistant",
    description="Get the current state of a specific Home Assistant entity",
    category="system",
    tags=["homeassistant", "state", "sensor"],
)
def ha_get_state(entity_id: str) -> str:
    """Get the current state and attributes of a Home Assistant entity."""
    state = _ha().get_state(entity_id)
    if state:
        return json.dumps(state)
    return json.dumps({"error": f"Entity {entity_id} not found"})


# ── Device Control ──────────────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Toggle a Home Assistant device (light, switch, etc.)",
    category="system",
    tags=["homeassistant", "toggle", "control"],
)
def ha_toggle(entity_id: str) -> str:
    """Toggle a device on/off."""
    result = _ha().toggle(entity_id)
    return json.dumps(result)


@skill(
    pack="homeassistant",
    description="Turn on a Home Assistant device",
    category="system",
    tags=["homeassistant", "turn_on", "control"],
)
def ha_turn_on(entity_id: str) -> str:
    """Turn on a device (light, switch, media player, etc.)."""
    result = _ha().turn_on(entity_id)
    return json.dumps(result)


@skill(
    pack="homeassistant",
    description="Turn off a Home Assistant device",
    category="system",
    tags=["homeassistant", "turn_off", "control"],
)
def ha_turn_off(entity_id: str) -> str:
    """Turn off a device."""
    result = _ha().turn_off(entity_id)
    return json.dumps(result)


@skill(
    pack="homeassistant",
    description="Call any Home Assistant service with custom data",
    category="system",
    tags=["homeassistant", "service", "call"],
)
def ha_call_service(
    domain: str,
    service: str,
    entity_id: str = "",
    data_json: str = "{}",
) -> str:
    """Call a HA service. domain=light, service=turn_on, entity_id=light.living_room.
    data_json is optional extra parameters as JSON string."""
    try:
        extra = json.loads(data_json)
    except json.JSONDecodeError:
        extra = None
    result = _ha().call_service(
        domain, service,
        entity_id=entity_id or None,
        data=extra if extra else None,
    )
    return json.dumps(result)


# ── Automations ─────────────────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Trigger a Home Assistant automation",
    category="system",
    tags=["homeassistant", "automation", "trigger"],
)
def ha_trigger_automation(entity_id: str) -> str:
    """Trigger a specific automation by entity ID."""
    result = _ha().trigger_automation(entity_id)
    return json.dumps(result)


@skill(
    pack="homeassistant",
    description="List all Home Assistant automations",
    category="system",
    tags=["homeassistant", "automation", "list"],
)
def ha_list_automations() -> str:
    """List all automations with their current state."""
    automations = _ha().list_automations()
    return json.dumps({"count": len(automations), "automations": automations})


# ── Notifications ───────────────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Send a notification to the user's phone via Home Assistant",
    category="communication",
    tags=["homeassistant", "notification", "phone", "alert"],
)
def ha_send_notification(message: str, title: str = "") -> str:
    """Send a push notification to the user's mobile device."""
    result = _ha().send_notification(message, title=title or None)
    return json.dumps(result)


@skill(
    pack="homeassistant",
    description="Send a news alert notification to the user's phone",
    category="communication",
    tags=["homeassistant", "news", "alert", "notification"],
)
def ha_send_news_alert(
    title: str,
    summary: str,
    url: str = "",
    relevance: float = 0.5,
) -> str:
    """Send a high-relevance news article as a mobile push notification."""
    result = _ha().send_news_alert(title, summary, url=url or None, relevance=relevance)
    return json.dumps(result)


# ── Phone Sensors ───────────────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Read all phone sensors from Home Assistant (battery, wifi, GPS, etc.)",
    category="system",
    tags=["homeassistant", "phone", "sensors", "battery"],
)
def ha_phone_sensors() -> str:
    """Get all phone sensor readings exposed via the HA Companion app."""
    sensors = _ha().get_phone_sensors()
    return json.dumps({"count": len(sensors), "sensors": sensors})


# ── System Metrics Push ─────────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Push CosySim system metrics to Home Assistant as sensor entities",
    category="system",
    tags=["homeassistant", "metrics", "push", "dashboard"],
)
def ha_push_metrics() -> str:
    """Collect CosySim system metrics and push them to HA for dashboard display."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        mm = get_meta_metrics()
        collected = mm.collect_system_metrics()
        metrics_dict = {m: 0.0 for m in collected}
        # Get latest values
        for name in collected:
            trend = mm.trend(name, days=1)
            if trend.get("count", 0) > 0:
                metrics_dict[name] = trend.get("last", 0.0)
        result = _ha().push_system_metrics(metrics_dict)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Status ──────────────────────────────────────────────────────────────


@skill(
    pack="homeassistant",
    description="Get Home Assistant connection status and statistics",
    category="system",
    tags=["homeassistant", "status"],
)
def ha_status() -> str:
    """Get HA client connection status, entity count, and request stats."""
    return json.dumps(_ha().status())


@skill(
    pack="homeassistant",
    description="List all entity domains available in Home Assistant",
    category="system",
    tags=["homeassistant", "domains"],
)
def ha_domains() -> str:
    """List all entity domains (sensor, light, switch, automation, etc.)."""
    domains = _ha().domains()
    return json.dumps({"count": len(domains), "domains": domains})
