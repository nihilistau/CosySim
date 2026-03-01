"""engine/events/cross_scene_relay.py — Cross-scene EventBus relay.

Listens for key events from one scene and publishes ripple effects
to other scenes. For example: arena match result → NeonCity faction shift.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from engine.events.event_bus import get_event_bus

logger = logging.getLogger(__name__)


class CrossSceneRelay:
    """Routes events between scenes via the EventBus."""

    def __init__(self) -> None:
        self._subscribed: bool = False
        self._sub_ids: List[str] = []

    def start(self) -> None:
        """Subscribe to cross-scene relay events."""
        if self._subscribed:
            return
        try:
            bus = get_event_bus()
            self._sub_ids = [
                bus.subscribe("arena.match_end", self._on_arena_match_end, "cross_scene_relay"),
                bus.subscribe("casino.major_win", self._on_casino_major_win, "cross_scene_relay"),
                bus.subscribe("heist.completed", self._on_heist_completed, "cross_scene_relay"),
                bus.subscribe("world.faction_shift", self._on_faction_shift, "cross_scene_relay"),
            ]
            self._subscribed = True
            logger.info("CrossSceneRelay started")
        except Exception as exc:
            logger.debug("CrossSceneRelay.start skipped: %s", exc)

    def stop(self) -> None:
        """Unsubscribe from all events."""
        try:
            bus = get_event_bus()
            for sub_id in self._sub_ids:
                bus.unsubscribe(sub_id)
            self._sub_ids = []
            self._subscribed = False
        except Exception as exc:
            logger.debug("CrossSceneRelay.stop skipped: %s", exc)

    def _on_arena_match_end(self, payload: Dict[str, Any]) -> None:
        """Arena match end → NeonCity faction shift + Lounge gossip."""
        try:
            bus = get_event_bus()
            winner = payload.get("winner", "unknown")
            faction = payload.get("faction", "")
            bus.publish("neoncity.faction_event", {
                "source": "arena",
                "faction": faction,
                "event": "champion_victory" if faction else "gladiator_victory",
                "winner": winner,
            })
            bus.publish("lounge.new_rumor", {
                "source": "arena",
                "text": f"Word is {winner} just destroyed everyone at the Colosseum.",
                "intensity": 0.7,
            })
            logger.debug("CrossSceneRelay: arena.match_end rippled to neoncity + lounge")
        except Exception as exc:
            logger.debug("arena ripple failed: %s", exc)

    def _on_casino_major_win(self, payload: Dict[str, Any]) -> None:
        """Casino big win → Lounge celebration + Intel Hub alert."""
        try:
            bus = get_event_bus()
            amount = payload.get("amount", 0)
            player = payload.get("player", "someone")
            bus.publish("lounge.new_rumor", {
                "source": "casino",
                "text": f"{player} just broke the bank at Club Noir. {amount:,} chips.",
                "intensity": 0.8,
            })
            bus.publish("intel_hub.alert", {
                "type": "financial",
                "severity": "medium",
                "headline": "Unusual activity at Club Noir — possible card counting",
                "source": "casino",
            })
            logger.debug("CrossSceneRelay: casino.major_win rippled")
        except Exception as exc:
            logger.debug("casino ripple failed: %s", exc)

    def _on_heist_completed(self, payload: Dict[str, Any]) -> None:
        """Heist success → Intel Hub alert + NeonCity faction event."""
        try:
            bus = get_event_bus()
            target = payload.get("target", "unknown location")
            crew = payload.get("crew", [])
            bus.publish("intel_hub.alert", {
                "type": "security",
                "severity": "high",
                "headline": f"Security breach at {target} — crew of {len(crew)}",
                "source": "heist",
            })
            bus.publish("neoncity.faction_event", {
                "source": "heist",
                "faction": "BlackMarket",
                "event": "successful_operation",
                "target": target,
            })
            logger.debug("CrossSceneRelay: heist.completed rippled")
        except Exception as exc:
            logger.debug("heist ripple failed: %s", exc)

    def _on_faction_shift(self, payload: Dict[str, Any]) -> None:
        """World faction shift → all interested scenes notified."""
        try:
            bus = get_event_bus()
            faction = payload.get("faction", "")
            bus.publish("tavern.new_rumor", {
                "source": "world",
                "text": f"The {faction} have been making moves. Power is shifting.",
                "intensity": 0.5,
            })
            logger.debug("CrossSceneRelay: world.faction_shift rippled to tavern")
        except Exception as exc:
            logger.debug("faction_shift ripple failed: %s", exc)


_RELAY: CrossSceneRelay | None = None


def get_cross_scene_relay() -> CrossSceneRelay:
    """Return the global CrossSceneRelay singleton."""
    global _RELAY
    if _RELAY is None:
        _RELAY = CrossSceneRelay()
    return _RELAY
