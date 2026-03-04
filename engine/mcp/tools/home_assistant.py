"""MCP tool domain: home_assistant.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── HOME_ASSISTANT TOOLS ───────────────────────────────────────────────


@mcp_tool
def ha_connect() -> str:
    """Connect to Home Assistant and discover entities."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().connect(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_list_entities(domain: str = "", search: str = "") -> str:
    """List Home Assistant entities filtered by domain or search term."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        entities = get_ha_client().list_entities(
            domain=domain or None, search=search or None,
        )
        return json.dumps({"count": len(entities), "entities": entities[:100]})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_get_state(entity_id: str) -> str:
    """Get current state of a Home Assistant entity."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        state = get_ha_client().get_state(entity_id)
        return json.dumps(state or {"error": "not found"}, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_toggle(entity_id: str) -> str:
    """Toggle a Home Assistant device on/off."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().toggle(entity_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_turn_on(entity_id: str) -> str:
    """Turn on a Home Assistant device."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().turn_on(entity_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_turn_off(entity_id: str) -> str:
    """Turn off a Home Assistant device."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().turn_off(entity_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_call_service(domain: str, service: str, entity_id: str = "", data_json: str = "{}") -> str:
    """Call any Home Assistant service with custom parameters."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        extra = json.loads(data_json) if data_json.strip() != "{}" else None
        return json.dumps(get_ha_client().call_service(
            domain, service, entity_id=entity_id or None, data=extra,
        ), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_send_notification(message: str, title: str = "") -> str:
    """Send a push notification to the user's phone via Home Assistant."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().send_notification(
            message, title=title or None,
        ), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_phone_sensors() -> str:
    """Read all phone sensors exposed via HA Companion (battery, wifi, GPS, etc.)."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        sensors = get_ha_client().get_phone_sensors()
        return json.dumps({"count": len(sensors), "sensors": sensors}, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_push_metrics() -> str:
    """Push CosySim system metrics to Home Assistant as sensor entities."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        from engine.nexus.meta_metrics import get_meta_metrics
        mm = get_meta_metrics()
        collected = mm.collect_system_metrics()
        metrics = {}
        for name in collected:
            trend = mm.trend(name, days=1)
            if trend.get("count", 0) > 0:
                metrics[name] = trend.get("last", 0.0)
        return json.dumps(get_ha_client().push_system_metrics(metrics), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def ha_status() -> str:
    """Get Home Assistant client connection status and statistics."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().status(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
