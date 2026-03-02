"""Player state manager for CosySim v0.75 "NEON CITY".

Tracks the player's persistent state across all scenes:
- credits (₵) — in-game currency
- reputation (0–100) — social standing in Neon City
- heat (0–100) — law/corp attention level
- faction_standings — per-faction rep (–100 to +100)
- active_location — current scene display name
- inventory — list of item names

The PlayerState singleton integrates with WorldSim:
- economy_tick events adjust credits ±
- faction_shift events adjust faction standings ±
- corp_raid / crime events raise heat
- festival events adjust reputation +

Emits ``hud_update`` Socket.IO events via EventCascade whenever
state changes so the Neon HUD updates in real-time on all connected clients.

Usage::

    from engine.world.player_state import get_player_state

    ps = get_player_state()
    ps.earn_credits(500, reason="market_sale")
    ps.set_location("THE GRID")
    state = ps.to_dict()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CREDITS: int = 5000
_DEFAULT_REP: int = 50
_DEFAULT_HEAT: int = 0

_FACTION_NAMES: List[str] = [
    "OmniCorp",
    "NeoTech",
    "BlackMarket",
    "Ghost_Net",
    "SynthSec",
    "DeepState",
]

# Economy impact thresholds
_ECONOMY_CREDIT_RANGE = (30, 150)    # ± per economy_tick
_FACTION_REP_DELTA = 5               # ± per faction_shift
_HEAT_RAID_DELTA = 8                 # + per corp_raid
_HEAT_HEIST_DELTA = 5                # + per heist_gone_wrong
_HEAT_DECAY_PER_TICK = 2             # - per economy_tick (natural decay)

# Weather icon map for HUD
WEATHER_ICONS: Dict[str, str] = {
    "clear": "☀️",
    "overcast": "🌥️",
    "neon_rain": "🌧️",
    "heavy_rain": "⛈️",
    "fog": "🌫️",
    "storm": "⚡",
    "blackout": "🌑",
}


# ---------------------------------------------------------------------------
# PlayerState
# ---------------------------------------------------------------------------


class PlayerState:
    """Persistent player state across all CosySim scenes.

    Thread-safe singleton. State persists in memory for the session and is
    serialisable via :meth:`to_dict` for REST responses.

    Not intended for direct instantiation — use :func:`get_player_state`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._credits: int = _DEFAULT_CREDITS
        self._rep: int = _DEFAULT_REP
        self._heat: int = _DEFAULT_HEAT
        self._faction_standings: Dict[str, int] = {f: 0 for f in _FACTION_NAMES}
        self._active_location: str = "NEON CITY"
        self._inventory: List[str] = []
        self._event_history: List[Dict[str, Any]] = []  # last 50 HUD events
        self._last_updated: float = time.time()

    # ------------------------------------------------------------------
    # Credits
    # ------------------------------------------------------------------

    def earn_credits(self, amount: int, reason: str = "") -> int:
        """Add credits to the player's balance.

        Args:
            amount: Positive number of credits to add.
            reason: Optional context label for the HUD log.

        Returns:
            New credit balance.
        """
        with self._lock:
            self._credits = max(0, self._credits + abs(amount))
            self._last_updated = time.time()
            balance = self._credits
        self._emit_hud_update({"credits_delta": abs(amount), "reason": reason})
        logger.debug("earn_credits +%d (%s) → %d", amount, reason, balance)
        return balance

    def spend_credits(self, amount: int, reason: str = "") -> Optional[int]:
        """Deduct credits from the player's balance.

        Args:
            amount: Positive number of credits to deduct.
            reason: Optional context label.

        Returns:
            New credit balance, or ``None`` if insufficient funds.
        """
        with self._lock:
            if self._credits < amount:
                return None
            self._credits -= abs(amount)
            self._last_updated = time.time()
            balance = self._credits
        self._emit_hud_update({"credits_delta": -abs(amount), "reason": reason})
        logger.debug("spend_credits -%d (%s) → %d", amount, reason, balance)
        return balance

    # ------------------------------------------------------------------
    # Reputation
    # ------------------------------------------------------------------

    def update_reputation(self, delta: int, reason: str = "") -> int:
        """Adjust the player's reputation score.

        Args:
            delta: Amount to add (can be negative).
            reason: Optional context label.

        Returns:
            New reputation score (clamped 0–100).
        """
        with self._lock:
            self._rep = max(0, min(100, self._rep + delta))
            self._last_updated = time.time()
            rep = self._rep
        self._emit_hud_update({"rep_delta": delta, "reason": reason})
        return rep

    # ------------------------------------------------------------------
    # Heat
    # ------------------------------------------------------------------

    def set_heat(self, value: int) -> int:
        """Set the player's heat level directly.

        Args:
            value: New heat value (clamped 0–100).

        Returns:
            New heat value.
        """
        with self._lock:
            self._heat = max(0, min(100, value))
            self._last_updated = time.time()
            heat = self._heat
        self._emit_hud_update({"heat": heat})
        return heat

    def adjust_heat(self, delta: int, reason: str = "") -> int:
        """Adjust the player's heat score.

        Args:
            delta: Amount to add (can be negative for decay).
            reason: Optional context label.

        Returns:
            New heat value (clamped 0–100).
        """
        with self._lock:
            self._heat = max(0, min(100, self._heat + delta))
            self._last_updated = time.time()
            heat = self._heat
        if delta != 0:
            self._emit_hud_update({"heat_delta": delta, "reason": reason})
        return heat

    # ------------------------------------------------------------------
    # Faction standings
    # ------------------------------------------------------------------

    def update_faction_standing(self, faction: str, delta: int) -> int:
        """Adjust standing with a faction.

        Args:
            faction: Faction name (must be in FACTION_NAMES).
            delta: Amount to add (can be negative).

        Returns:
            New standing value (clamped –100 to +100).
        """
        if faction not in self._faction_standings:
            logger.debug("Unknown faction: %s", faction)
            return 0
        with self._lock:
            current = self._faction_standings.get(faction, 0)
            new_val = max(-100, min(100, current + delta))
            self._faction_standings[faction] = new_val
            self._last_updated = time.time()
        self._emit_hud_update({"faction": faction, "standing_delta": delta})
        return new_val

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def set_location(self, location: str) -> None:
        """Set the player's current scene/location.

        Args:
            location: Display name of the current location.
        """
        with self._lock:
            self._active_location = location
            self._last_updated = time.time()
        self._emit_hud_update({"location": location})

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def add_item(self, item: str) -> None:
        """Add an item to the player's inventory."""
        with self._lock:
            if item not in self._inventory:
                self._inventory.append(item)
                self._last_updated = time.time()

    def remove_item(self, item: str) -> bool:
        """Remove an item from inventory. Returns True if found."""
        with self._lock:
            if item in self._inventory:
                self._inventory.remove(item)
                self._last_updated = time.time()
                return True
        return False

    def has_item(self, item: str) -> bool:
        """Return True if item is in inventory."""
        with self._lock:
            return item in self._inventory

    # ------------------------------------------------------------------
    # World event hooks (called by WorldSim)
    # ------------------------------------------------------------------

    def on_economy_tick(self, event_type: str, payload: Dict) -> None:
        """React to an economy tick from WorldSim.

        Adjusts credits based on event type and applies heat decay.

        Args:
            event_type: e.g. ``"market_surge"``, ``"market_crash"``, ``"corp_tax"``
            payload: Event payload dict with optional ``credit_delta`` key.
        """
        import random
        base_delta = payload.get("credit_delta", random.randint(*_ECONOMY_CREDIT_RANGE))
        if event_type in ("market_crash", "corp_tax", "blackout"):
            # Negative economy events
            self.spend_credits(abs(base_delta), reason=event_type)
        else:
            self.earn_credits(abs(base_delta), reason=event_type)

        # Natural heat decay
        self.adjust_heat(-_HEAT_DECAY_PER_TICK, reason="natural_decay")

    def on_faction_shift(self, faction: str, action: str, delta: int) -> None:
        """React to a faction shift event from WorldSim.

        Args:
            faction: Faction name that shifted.
            action: What the faction did.
            delta: Faction tension delta (used to calculate player standing impact).
        """
        impact = _FACTION_REP_DELTA if delta > 0 else -_FACTION_REP_DELTA
        self.update_faction_standing(faction, impact // 2)  # partial impact on player

    def on_world_event(self, event_type: str, title: str, payload: Dict) -> None:
        """React to a major world event.

        Args:
            event_type: e.g. ``"corp_raid"``, ``"festival"``, ``"gang_war"``
            title: Display title for HUD log.
            payload: Event payload.
        """
        if event_type in ("corp_raid", "gang_war"):
            self.adjust_heat(_HEAT_RAID_DELTA, reason=event_type)
        elif event_type == "gang_war" or "heist" in event_type.lower():
            self.adjust_heat(_HEAT_HEIST_DELTA, reason="heist_wave")
        elif event_type == "festival":
            self.update_reputation(3, reason="festival")
        elif event_type == "underground_auction":
            self.earn_credits(200, reason="auction_windfall")

        # Log to HUD event history
        self._add_hud_event(title)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise player state to a JSON-safe dict for REST responses.

        Returns:
            Dict with all player state fields.
        """
        with self._lock:
            return {
                "credits": self._credits,
                "reputation": self._rep,
                "heat": self._heat,
                "faction_standings": dict(self._faction_standings),
                "active_location": self._active_location,
                "inventory": list(self._inventory),
                "event_history": list(self._event_history[-10:]),
                "last_updated": self._last_updated,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_hud_event(self, title: str) -> None:
        """Add an event title to the rolling HUD event history (max 50)."""
        entry: Dict[str, Any] = {"title": title, "ts": time.time()}
        with self._lock:
            self._event_history.append(entry)
            if len(self._event_history) > 50:
                self._event_history.pop(0)

    def _emit_hud_update(self, delta: Dict[str, Any]) -> None:
        """Emit a ``hud_update`` Socket.IO event via EventCascade.

        Best-effort — silently skips if EventCascade is not running.

        Args:
            delta: Partial update payload to include alongside the full state.
        """
        try:
            from engine.world.event_cascade import get_event_cascade
            state = self.to_dict()
            state["_delta"] = delta
            get_event_cascade().emit("hud_update", state)
        except Exception as exc:
            logger.debug("PlayerState._emit_hud_update failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_PLAYER_STATE: Optional[PlayerState] = None
_PS_LOCK = threading.Lock()


def get_player_state() -> PlayerState:
    """Return the process-wide :class:`PlayerState` singleton.

    Thread-safe double-checked locking.

    Returns:
        The singleton :class:`PlayerState` instance.
    """
    global _PLAYER_STATE
    if _PLAYER_STATE is None:
        with _PS_LOCK:
            if _PLAYER_STATE is None:
                _PLAYER_STATE = PlayerState()
    return _PLAYER_STATE


def reset_player_state() -> None:
    """Reset the singleton (test helper only)."""
    global _PLAYER_STATE
    with _PS_LOCK:
        _PLAYER_STATE = None
