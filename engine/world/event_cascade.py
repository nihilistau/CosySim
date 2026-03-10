"""World Event Cascade — broadcast WorldSim events to relevant scenes via Socket.IO.

Subscribes to the WorldSim event stream and fans out events to all running
scenes that declare interest.  Each scene registers which WorldEventType values
it cares about; the cascade layer filters and delivers them.

Usage (in a scene's start() method):
    from engine.world.event_cascade import get_event_cascade
    cascade = get_event_cascade()
    cascade.subscribe("penthouse", [WorldEventType.ECONOMY, WorldEventType.MOOD])

The cascade emits 'world_event' Socket.IO events to each subscribed scene's
socket namespace (or broadcasts via the cross-scene relay if available).

Architecture:
    WorldSim → EventCascade → (filter by scene subscriptions) → Socket.IO rooms
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Lazy imports — resolved at call time but exposed at module level for patching
try:
    from engine.events.event_bus import get_event_bus
except ImportError:
    get_event_bus = None  # type: ignore[assignment]

try:
    from engine.mcp import get_framework
except ImportError:
    get_framework = None  # type: ignore[assignment]

# ──── Event Types ─────────────────────────────────────────────────────────────


class WorldEventType:
    """String constants for world event categories."""

    ECONOMY = "economy"       # Price changes, market shifts
    FACTION = "faction"       # Faction standing changes
    NPC = "npc"               # NPC state transitions
    CRIME = "crime"           # Crime/security events
    WEATHER = "weather"       # Atmospheric events
    POLITICAL = "political"   # Political developments
    SOCIAL = "social"         # Social dynamics
    DISASTER = "disaster"     # Major disruptive events
    RUMOUR = "rumour"         # Information spreading
    COMBAT = "combat"         # Arena / conflict events

    ALL: Set[str] = {
        ECONOMY, FACTION, NPC, CRIME, WEATHER,
        POLITICAL, SOCIAL, DISASTER, RUMOUR, COMBAT,
    }


# ──── Default scene subscriptions ────────────────────────────────────────────
# Scenes that care about world events by default (can be overridden at runtime)

DEFAULT_SCENE_SUBSCRIPTIONS: Dict[str, List[str]] = {
    "penthouse":  [WorldEventType.SOCIAL, WorldEventType.RUMOUR, WorldEventType.NPC],
    "phone":    [WorldEventType.SOCIAL, WorldEventType.POLITICAL, WorldEventType.CRIME],
    "lounge":   [WorldEventType.SOCIAL, WorldEventType.ECONOMY, WorldEventType.RUMOUR],
    "tavern":   [WorldEventType.SOCIAL, WorldEventType.CRIME, WorldEventType.RUMOUR, WorldEventType.NPC],
    "casino":   [WorldEventType.ECONOMY, WorldEventType.CRIME, WorldEventType.FACTION],
    "gallery":  [WorldEventType.SOCIAL, WorldEventType.POLITICAL],
    "arena":    [WorldEventType.COMBAT, WorldEventType.FACTION, WorldEventType.SOCIAL],
    "realm":    [WorldEventType.FACTION, WorldEventType.POLITICAL, WorldEventType.DISASTER],
    "neoncity": [WorldEventType.CRIME, WorldEventType.FACTION, WorldEventType.ECONOMY, WorldEventType.WEATHER],
    "heist":    [WorldEventType.CRIME, WorldEventType.ECONOMY, WorldEventType.FACTION],
    "intel_hub": list(WorldEventType.ALL),  # Intel Hub sees everything
}


# ──── Singleton ───────────────────────────────────────────────────────────────

_cascade_instance: Optional["EventCascade"] = None
_cascade_lock = threading.Lock()


def get_event_cascade() -> "EventCascade":
    """Return the global EventCascade singleton."""
    global _cascade_instance
    if _cascade_instance is None:
        with _cascade_lock:
            if _cascade_instance is None:
                _cascade_instance = EventCascade()
    return _cascade_instance


# ──── Core class ──────────────────────────────────────────────────────────────


@dataclass
class CascadeEvent:
    """A world event ready to be delivered to a scene."""

    scene: str
    event_type: str
    payload: Dict[str, Any]
    source: str = "world_sim"


class EventCascade:
    """Subscribes to WorldSim and fans events out to interested scenes.

    Thread-safe.  Uses the cross-scene relay (EventBus) when available,
    with a Socket.IO direct emit fallback.
    """

    def __init__(self) -> None:
        self._subscriptions: Dict[str, Set[str]] = {}
        self._lock = threading.Lock()
        self._delivered: int = 0
        self._filtered: int = 0
        self._started = False

        # Pre-load default subscriptions
        for scene, event_types in DEFAULT_SCENE_SUBSCRIPTIONS.items():
            self._subscriptions[scene] = set(event_types)

    # ── Subscription management ───────────────────────────────────────────

    def subscribe(self, scene: str, event_types: List[str]) -> None:
        """Register a scene's interest in specific event types.

        Args:
            scene: Scene name (e.g. 'penthouse', 'casino').
            event_types: List of WorldEventType constants.
        """
        with self._lock:
            if scene not in self._subscriptions:
                self._subscriptions[scene] = set()
            self._subscriptions[scene].update(event_types)
        logger.debug("EventCascade: %s subscribed to %s", scene, event_types)

    def unsubscribe(self, scene: str, event_types: Optional[List[str]] = None) -> None:
        """Remove a scene's subscriptions.

        Args:
            scene: Scene name.
            event_types: Specific types to remove, or None to remove all.
        """
        with self._lock:
            if event_types is None:
                self._subscriptions.pop(scene, None)
            elif scene in self._subscriptions:
                for et in event_types:
                    self._subscriptions[scene].discard(et)

    def get_subscriptions(self, scene: str) -> Set[str]:
        """Return the set of event types the scene is subscribed to."""
        with self._lock:
            return set(self._subscriptions.get(scene, set()))

    # ── Event delivery ────────────────────────────────────────────────────

    def dispatch(self, event_type: str, payload: Dict[str, Any], source: str = "world_sim") -> int:
        """Fan out an event to all scenes subscribed to its type.

        Args:
            event_type: WorldEventType constant.
            payload: Event data dict.
            source: Origin identifier.

        Returns:
            Number of scenes the event was delivered to.
        """
        with self._lock:
            targets = [
                scene for scene, types in self._subscriptions.items()
                if event_type in types
            ]

        delivered = 0
        for scene in targets:
            evt = CascadeEvent(scene=scene, event_type=event_type, payload=payload, source=source)
            if self._deliver(evt):
                delivered += 1

        self._delivered += delivered
        self._filtered += max(0, len(self._subscriptions) - delivered)

        if delivered:
            logger.debug(
                "EventCascade: dispatched %s to %d/%d scenes",
                event_type, delivered, len(self._subscriptions),
            )
        return delivered

    def _deliver(self, evt: CascadeEvent) -> bool:
        """Deliver a single CascadeEvent to its target scene.

        Tries (in order):
        1. Cross-scene EventBus relay
        2. Direct Socket.IO emit via MCPFramework

        Returns:
            True if delivered successfully.
        """
        payload = {
            "event_type": evt.event_type,
            "scene": evt.scene,
            "source": evt.source,
            "data": evt.payload,
        }

        # Attempt 1: EventBus relay (cross-scene broadcast)
        try:
            bus = get_event_bus()
            bus.publish(
                f"world_event.{evt.event_type}",
                payload,
                target_scene=evt.scene,
            )
            return True
        except Exception as exc:
            logger.debug("EventCascade attempt 1 (EventBus) failed for %s→%s: %s",
                         evt.event_type, evt.scene, exc)

        # Attempt 2: MCPFramework Socket.IO emit
        try:
            fw = get_framework()
            if fw and hasattr(fw, "socketio") and fw.socketio:
                fw.socketio.emit(
                    "world_event",
                    payload,
                    room=f"scene_{evt.scene}",
                )
                return True
        except Exception as exc:
            logger.debug("EventCascade attempt 2 (Socket.IO) failed for %s→%s: %s",
                         evt.event_type, evt.scene, exc)

        # Attempt 3: Store in MCPFramework for scene to poll
        try:
            fw = get_framework()
            node = fw.get_node(f"scenes.{evt.scene}")
            if node:
                pending = node.get("pending_world_events", [])
                pending.append(payload)
                # Keep only last 20 events
                node.set("pending_world_events", pending[-20:])
                return True
        except Exception as exc:
            logger.debug("EventCascade attempt 3 (MCP poll store) failed for %s→%s: %s",
                         evt.event_type, evt.scene, exc)

        return False

    # ── WorldSim bridge ───────────────────────────────────────────────────

    def start(self) -> None:
        """Begin listening to WorldSim events.

        Hooks into WorldSim's event callbacks if available.
        Safe to call multiple times (idempotent).
        """
        if self._started:
            return
        self._started = True

        try:
            from engine.world.world_sim import get_world_sim
            sim = get_world_sim()
            if hasattr(sim, "on_event"):
                sim.on_event(self._on_world_sim_event)
                logger.info("EventCascade: connected to WorldSim event stream")
        except Exception as exc:
            logger.debug("EventCascade: could not connect to WorldSim: %s", exc)

    def _on_world_sim_event(self, event: Any) -> None:
        """Callback invoked by WorldSim when a new event fires.

        Args:
            event: WorldSim event object (dict or dataclass with type + data attrs).
        """
        try:
            if isinstance(event, dict):
                event_type = event.get("type", WorldEventType.SOCIAL)
                payload = event
            else:
                event_type = getattr(event, "type", WorldEventType.SOCIAL)
                payload = asdict(event) if hasattr(event, "__dataclass_fields__") else vars(event)
            self.dispatch(event_type, payload, source="world_sim")
        except Exception as exc:
            logger.debug("EventCascade: error handling WorldSim event: %s", exc)

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return cascade statistics for the metrics endpoint.

        Returns:
            Dict with delivered, filtered, subscribed_scenes counts.
        """
        with self._lock:
            subscriptions_snapshot = {
                scene: list(types) for scene, types in self._subscriptions.items()
            }
        return {
            "delivered": self._delivered,
            "filtered": self._filtered,
            "subscribed_scenes": len(self._subscriptions),
            "subscriptions": subscriptions_snapshot,
        }

    def reset_stats(self) -> None:
        """Reset delivery counters (for testing)."""
        self._delivered = 0
        self._filtered = 0
