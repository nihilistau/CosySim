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

import json
import logging
import threading
import time
from pathlib import Path
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

    Thread-safe singleton. State persists to ``data/player_state.json`` across
    server restarts and is serialisable via :meth:`to_dict` for REST responses.

    Not intended for direct instantiation — use :func:`get_player_state`.
    """

    _SAVE_PATH: Path = Path("data") / "player_state.json"
    _AUTO_SAVE_DELAY: float = 5.0  # seconds debounce

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
        self._save_timer: Optional[threading.Timer] = None
        # Auto-load persisted state if it exists
        if self._SAVE_PATH.exists():
            try:
                self.load_from_file()
            except Exception as exc:
                logger.warning("PlayerState: failed to load saved state: %s", exc)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def credits(self) -> int:
        """Current credit balance."""
        with self._lock:
            return self._credits

    @property
    def reputation(self) -> int:
        """Current reputation score (0–100)."""
        with self._lock:
            return self._rep

    @property
    def heat(self) -> int:
        """Current heat level (0–100)."""
        with self._lock:
            return self._heat

    @property
    def faction_standings(self) -> Dict[str, int]:
        """Faction standings dict (copy)."""
        with self._lock:
            return dict(self._faction_standings)

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
        self._schedule_auto_save()
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
        self._schedule_auto_save()
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
        self._schedule_auto_save()
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
        self._schedule_auto_save()
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
            self._schedule_auto_save()
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
        self._schedule_auto_save()
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
        self._schedule_auto_save()

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
    # Persistence
    # ------------------------------------------------------------------

    def save_to_file(self, path: Optional[Path] = None) -> None:
        """Save player state to JSON file.

        Args:
            path: Override save path (defaults to ``data/player_state.json``).
        """
        target = path or self._SAVE_PATH
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = self.to_dict()
            data["_saved_at"] = time.time()
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.debug("PlayerState saved → %s", target)
        except Exception as exc:
            logger.warning("PlayerState.save_to_file failed: %s", exc)

    def load_from_file(self, path: Optional[Path] = None) -> bool:
        """Load player state from JSON file.

        Args:
            path: Override load path (defaults to ``data/player_state.json``).

        Returns:
            True if loaded successfully, False otherwise.
        """
        target = path or self._SAVE_PATH
        if not target.exists():
            return False
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            with self._lock:
                self._credits = int(data.get("credits", _DEFAULT_CREDITS))
                self._rep = max(0, min(100, int(data.get("reputation", _DEFAULT_REP))))
                self._heat = max(0, min(100, int(data.get("heat", _DEFAULT_HEAT))))
                stored_factions = data.get("faction_standings", {})
                for f in _FACTION_NAMES:
                    self._faction_standings[f] = int(stored_factions.get(f, 0))
                self._active_location = str(data.get("active_location", "NEON CITY"))
                self._inventory = list(data.get("inventory", []))
                self._last_updated = float(data.get("last_updated", time.time()))
            logger.info("PlayerState restored from %s (₵%d, REP %d)", target, self._credits, self._rep)
            return True
        except Exception as exc:
            logger.warning("PlayerState.load_from_file failed: %s", exc)
            return False

    def reset_to_defaults(self) -> None:
        """Reset state to defaults and delete save file."""
        with self._lock:
            self._credits = _DEFAULT_CREDITS
            self._rep = _DEFAULT_REP
            self._heat = _DEFAULT_HEAT
            self._faction_standings = {f: 0 for f in _FACTION_NAMES}
            self._active_location = "NEON CITY"
            self._inventory = []
            self._event_history = []
            self._last_updated = time.time()
        try:
            if self._SAVE_PATH.exists():
                self._SAVE_PATH.unlink()
        except Exception:
            pass
        logger.info("PlayerState reset to defaults")

    def _schedule_auto_save(self) -> None:
        """Debounced auto-save — fires 5 s after the last mutation."""
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(self._AUTO_SAVE_DELAY, self.save_to_file)
        self._save_timer.daemon = True
        self._save_timer.start()

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
        if _PLAYER_STATE is not None and _PLAYER_STATE._save_timer is not None:
            _PLAYER_STATE._save_timer.cancel()
        _PLAYER_STATE = None
