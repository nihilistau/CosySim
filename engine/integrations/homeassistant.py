"""
Home Assistant Integration — REST API client for CosySim.

Provides bidirectional communication with Home Assistant:
- Read sensor states (temperature, humidity, phone battery, etc.)
- Control devices (lights, switches, media players)
- Call services (automations, scripts, notifications)
- Send mobile notifications via HA Companion
- Expose CosySim system metrics as HA sensors

Configuration (config/default.yaml):
    homeassistant:
      url: "http://homeassistant.local:8123"
      token: ""                         # Long-lived access token
      auto_discover: true               # Auto-discover entities on connect
      notification_service: "notify.mobile_app_sm_s908b"
      poll_interval_seconds: 30         # State polling interval

Thread-safe singleton — call ``get_ha_client()``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from engine.config import get_config

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

_DEFAULT_URL = "http://homeassistant.local:8123"
_TIMEOUT = 10  # seconds


# ── Data Helpers ────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Home Assistant Client ───────────────────────────────────────────────


class HomeAssistantClient:
    """REST API client for Home Assistant.

    Provides entity state reading, service calling, automation triggering,
    and mobile notifications.  Uses only stdlib (urllib) — no requests dep.

    Args:
        url: Base URL for the HA instance.
        token: Long-lived access token for authentication.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        cfg = get_config()
        self._url = (url or cfg.get("homeassistant.url", _DEFAULT_URL)).rstrip("/")
        self._token = token or cfg.get("homeassistant.token", "")
        self._notify_service = cfg.get(
            "homeassistant.notification_service",
            "notify.mobile_app_sm_s908b",
        )
        self._poll_interval = cfg.get("homeassistant.poll_interval_seconds", 30)
        self._auto_discover = cfg.get("homeassistant.auto_discover", True)

        self._entities: Dict[str, Dict[str, Any]] = {}
        self._entity_lock = threading.Lock()
        self._connected = False
        self._last_poll: float = 0.0
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []

        # Stats
        self._stats = {
            "requests": 0,
            "errors": 0,
            "notifications_sent": 0,
            "services_called": 0,
            "last_connected": None,
        }

    # ── HTTP Layer ──────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = _TIMEOUT,
    ) -> Any:
        """Make an authenticated HTTP request to the HA REST API."""
        url = f"{self._url}{path}"
        headers = {
            "Content-Type": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, headers=headers, method=method)

        self._stats["requests"] += 1
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as exc:
            self._stats["errors"] += 1
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8")[:200]
            except Exception:
                pass
            logger.warning("HA API %s %s → %d: %s", method, path, exc.code, error_body)
            raise
        except URLError as exc:
            self._stats["errors"] += 1
            logger.warning("HA API connection failed: %s", exc.reason)
            raise
        except Exception as exc:
            self._stats["errors"] += 1
            logger.warning("HA API error: %s", exc)
            raise

    def _get(self, path: str) -> Any:
        return self._request("GET", path)

    def _post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, data)

    # ── Connection & Discovery ──────────────────────────────────────

    def connect(self) -> Dict[str, Any]:
        """Test connection and optionally auto-discover entities.

        Returns:
            Connection status dict with HA version and entity count.
        """
        try:
            config = self._get("/api/config")
            self._connected = True
            self._stats["last_connected"] = _ts()
            result = {
                "connected": True,
                "location_name": config.get("location_name", ""),
                "version": config.get("version", ""),
                "url": self._url,
            }

            if self._auto_discover:
                self.refresh_entities()
                result["entities_discovered"] = len(self._entities)

            logger.info(
                "Connected to Home Assistant %s (%d entities)",
                config.get("version", "?"),
                len(self._entities),
            )
            return result

        except Exception as exc:
            self._connected = False
            return {"connected": False, "error": str(exc), "url": self._url}

    def is_connected(self) -> bool:
        """Check if the client has successfully connected."""
        return self._connected

    def refresh_entities(self) -> int:
        """Refresh the local entity cache from HA.

        Returns:
            Number of entities discovered.
        """
        try:
            states = self._get("/api/states")
            with self._entity_lock:
                self._entities = {}
                for entity in states:
                    eid = entity.get("entity_id", "")
                    self._entities[eid] = {
                        "entity_id": eid,
                        "state": entity.get("state", "unknown"),
                        "attributes": entity.get("attributes", {}),
                        "last_changed": entity.get("last_changed", ""),
                        "last_updated": entity.get("last_updated", ""),
                    }
            self._last_poll = time.time()
            return len(self._entities)
        except Exception as exc:
            logger.warning("Failed to refresh entities: %s", exc)
            return 0

    # ── Entity State ────────────────────────────────────────────────

    def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get the current state of a specific entity.

        Args:
            entity_id: The HA entity ID (e.g., "sensor.temperature").

        Returns:
            Entity state dict or None if not found.
        """
        try:
            result = self._get(f"/api/states/{entity_id}")
            state = {
                "entity_id": entity_id,
                "state": result.get("state", "unknown"),
                "attributes": result.get("attributes", {}),
                "last_changed": result.get("last_changed", ""),
                "last_updated": result.get("last_updated", ""),
                "friendly_name": result.get("attributes", {}).get(
                    "friendly_name", entity_id
                ),
            }
            # Update cache
            with self._entity_lock:
                self._entities[entity_id] = state
            return state
        except Exception as exc:
            logger.debug("get_state(%s) failed: %s", entity_id, exc)
            return None

    def get_states(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all entity states, optionally filtered by domain.

        Args:
            domain: Filter by domain (e.g., "sensor", "light", "switch").

        Returns:
            List of entity state dicts.
        """
        if time.time() - self._last_poll > self._poll_interval:
            self.refresh_entities()

        with self._entity_lock:
            entities = list(self._entities.values())

        if domain:
            entities = [
                e for e in entities
                if e["entity_id"].startswith(f"{domain}.")
            ]
        return entities

    def list_entities(
        self,
        domain: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """List entities with their current state — lightweight summary.

        Args:
            domain: Filter by domain (e.g., "sensor", "light").
            search: Filter by substring in entity_id or friendly_name.

        Returns:
            List of {entity_id, state, friendly_name, domain} dicts.
        """
        states = self.get_states(domain)
        result = []
        for s in states:
            eid = s["entity_id"]
            friendly = s.get("friendly_name", eid)
            if search and search.lower() not in eid.lower() and search.lower() not in friendly.lower():
                continue
            result.append({
                "entity_id": eid,
                "state": s["state"],
                "friendly_name": friendly,
                "domain": eid.split(".")[0] if "." in eid else "",
            })
        return result

    # ── Services ────────────────────────────────────────────────────

    def call_service(
        self,
        domain: str,
        service: str,
        entity_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a Home Assistant service.

        Args:
            domain: Service domain (e.g., "light", "switch", "automation").
            service: Service name (e.g., "turn_on", "toggle", "trigger").
            entity_id: Target entity ID.
            data: Additional service data.

        Returns:
            Result dict with success status.
        """
        payload: Dict[str, Any] = {}
        if entity_id:
            payload["entity_id"] = entity_id
        if data:
            payload.update(data)

        try:
            result = self._post(f"/api/services/{domain}/{service}", payload)
            self._stats["services_called"] += 1
            logger.info("HA service %s.%s called on %s", domain, service, entity_id or "all")
            return {
                "success": True,
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "result": result,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "domain": domain,
                "service": service,
            }

    def toggle(self, entity_id: str) -> Dict[str, Any]:
        """Toggle an entity (light, switch, etc.)."""
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        return self.call_service(domain, "toggle", entity_id=entity_id)

    def turn_on(self, entity_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Turn on an entity."""
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        return self.call_service(domain, "turn_on", entity_id=entity_id, data=kwargs or None)

    def turn_off(self, entity_id: str) -> Dict[str, Any]:
        """Turn off an entity."""
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        return self.call_service(domain, "turn_off", entity_id=entity_id)

    # ── Automations ─────────────────────────────────────────────────

    def trigger_automation(self, entity_id: str) -> Dict[str, Any]:
        """Trigger an automation by entity ID."""
        return self.call_service("automation", "trigger", entity_id=entity_id)

    def list_automations(self) -> List[Dict[str, str]]:
        """List all automations with their state."""
        return self.list_entities(domain="automation")

    # ── Notifications ───────────────────────────────────────────────

    def send_notification(
        self,
        message: str,
        title: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        service: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a notification to the mobile device via HA Companion.

        Args:
            message: Notification body text.
            title: Notification title.
            data: Extra notification data (actions, image, channel, etc.).
            service: Override notification service (default from config).

        Returns:
            Result dict with success status.
        """
        svc = service or self._notify_service
        # Parse "notify.mobile_app_xxx" into domain + service
        parts = svc.split(".", 1)
        domain = parts[0] if len(parts) > 1 else "notify"
        svc_name = parts[1] if len(parts) > 1 else svc

        payload: Dict[str, Any] = {"message": message}
        if title:
            payload["title"] = title
        if data:
            payload["data"] = data

        result = self.call_service(domain, svc_name, data=payload)
        if result.get("success"):
            self._stats["notifications_sent"] += 1
        return result

    def send_news_alert(
        self,
        title: str,
        summary: str,
        url: Optional[str] = None,
        relevance: float = 0.0,
    ) -> Dict[str, Any]:
        """Send a high-relevance news article as a mobile notification.

        Args:
            title: Article title.
            summary: Brief summary.
            url: Article URL (opens in browser on tap).
            relevance: Relevance score for priority.
        """
        data: Dict[str, Any] = {
            "channel": "news_feed",
            "importance": "high" if relevance > 0.7 else "default",
            "tag": "cosysim_news",
        }
        if url:
            data["url"] = url
            data["clickAction"] = url

        return self.send_notification(
            message=summary[:200],
            title=f"📰 {title[:80]}",
            data=data,
        )

    # ── Phone Sensors ───────────────────────────────────────────────

    def get_phone_sensors(self) -> Dict[str, Any]:
        """Get all phone sensors exposed via HA Companion.

        Returns dict of sensor readings: battery, wifi, location, etc.
        """
        phone_domains = ["sensor", "device_tracker", "binary_sensor"]
        phone_keywords = [
            "phone", "sm_s908", "mobile", "battery", "charger",
            "wifi", "bluetooth", "gps", "geocoded", "activity",
            "light_sensor", "pressure", "proximity", "steps",
        ]
        result: Dict[str, Any] = {}
        for domain in phone_domains:
            for entity in self.get_states(domain):
                eid = entity["entity_id"].lower()
                fname = entity.get("friendly_name", "").lower()
                if any(kw in eid or kw in fname for kw in phone_keywords):
                    result[entity["entity_id"]] = {
                        "state": entity["state"],
                        "friendly_name": entity.get("friendly_name", ""),
                        "attributes": entity.get("attributes", {}),
                    }
        return result

    # ── System Metrics as HA Sensors ────────────────────────────────

    def push_system_metrics(self, metrics: Dict[str, Any]) -> Dict[str, int]:
        """Push CosySim system metrics to HA as sensor states.

        Uses the HA REST API to set sensor states for dashboard display.

        Args:
            metrics: Dict of metric_name → value pairs.

        Returns:
            Count of successfully pushed metrics.
        """
        pushed = 0
        errors = 0
        for name, value in metrics.items():
            entity_id = f"sensor.cosysim_{name.replace('.', '_').replace('-', '_')}"
            try:
                self._post(f"/api/states/{entity_id}", {
                    "state": str(value),
                    "attributes": {
                        "friendly_name": f"CosySim {name.replace('_', ' ').title()}",
                        "source": "cosysim",
                        "updated_at": _ts(),
                    },
                })
                pushed += 1
            except Exception:
                errors += 1
        return {"pushed": pushed, "errors": errors}

    # ── Event Listening ─────────────────────────────────────────────

    def add_state_listener(
        self, callback: Callable[[str, Dict[str, Any]], None]
    ) -> None:
        """Register a callback for entity state changes.

        Args:
            callback: Called with (entity_id, new_state) on state change.
        """
        self._listeners.append(callback)

    def poll_changes(self) -> List[Dict[str, Any]]:
        """Poll for entity state changes since last poll.

        Returns:
            List of changed entities with old and new states.
        """
        old_states = dict(self._entities)
        self.refresh_entities()
        changes = []

        with self._entity_lock:
            for eid, new in self._entities.items():
                old = old_states.get(eid)
                if old and old["state"] != new["state"]:
                    change = {
                        "entity_id": eid,
                        "old_state": old["state"],
                        "new_state": new["state"],
                        "changed_at": _ts(),
                    }
                    changes.append(change)
                    for listener in self._listeners:
                        try:
                            listener(eid, new)
                        except Exception as exc:
                            logger.debug("Listener error: %s", exc)

        return changes

    # ── Status ──────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return client status and stats."""
        return {
            "connected": self._connected,
            "url": self._url,
            "entities_cached": len(self._entities),
            "last_poll": self._last_poll,
            "notification_service": self._notify_service,
            **self._stats,
        }

    def domains(self) -> List[str]:
        """List all unique entity domains."""
        with self._entity_lock:
            return sorted({
                eid.split(".")[0]
                for eid in self._entities
                if "." in eid
            })


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[HomeAssistantClient] = None
_lock = threading.Lock()


def get_ha_client() -> HomeAssistantClient:
    """Get or create the singleton HomeAssistantClient."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = HomeAssistantClient()
    return _instance
