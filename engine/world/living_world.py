"""Central Living World orchestrator for CosySim v1.0 "NeonCity 2".

The :class:`LivingWorld` daemon ties together all dynamic world systems —
market, NPC routines, faction AI, weather, and event generation — into a
single coordinated tick that fires every game hour (60 real seconds).

Each tick:

1. **Advance game clock** — read time from WorldState.
2. **Move NPCs** — RoutineManager transitions NPCs to scheduled locations.
3. **Faction AI** — each faction makes one strategic decision.
4. **Market tick** — supply/demand drift, territory-based price adjustments.
5. **Weather cycle** — probabilistic weather transitions.
6. **Event generation** — stochastic world events based on current state.
7. **Consequence propagation** — events ripple to market, factions, NPCs.

The daemon integrates with existing systems without replacing them:

* :mod:`engine.world.world_state` — game clock and weather
* :mod:`engine.world.world_sim` — event templates and broadcasting
* :mod:`engine.world.market` — supply/demand economy
* :mod:`engine.world.npc_routines` — NPC location schedules
* :mod:`engine.world.faction_ai` — autonomous faction decisions
* :mod:`engine.world.territory` — district control data
* :mod:`engine.events.event_bus` — pub/sub event distribution
* :mod:`engine.world.event_cascade` — scene-level event filtering

Usage::

    from engine.world.living_world import get_living_world

    lw = get_living_world()
    lw.start()                    # begin daemon ticking
    status = lw.get_status()      # snapshot of all subsystems
    lw.stop()                     # graceful shutdown
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Lazy imports ────

def _get_world_state():
    from engine.world.world_state import get_world_state
    return get_world_state()


def _get_market():
    from engine.world.market import get_market
    return get_market()


def _get_routine_manager():
    from engine.world.npc_routines import get_routine_manager
    return get_routine_manager()


def _get_faction_ai():
    from engine.world.faction_ai import get_faction_ai
    return get_faction_ai()


def _get_territory():
    try:
        from engine.world.territory import get_territory_manager
        return get_territory_manager()
    except Exception as e:
        logger.debug("[LivingWorld] Territory manager unavailable (operation=lazy_load): %s", e)
        return None


def _get_event_bus():
    try:
        from engine.events.event_bus import get_event_bus
        return get_event_bus()
    except Exception as e:
        logger.debug("[LivingWorld] EventBus unavailable (operation=lazy_load): %s", e)
        return None


# ──── Constants ────

WEATHER_TRANSITIONS = {
    "CLEAR": {"CLEAR": 0.6, "OVERCAST": 0.25, "FOG": 0.1, "NEON_RAIN": 0.05},
    "OVERCAST": {"OVERCAST": 0.4, "CLEAR": 0.2, "NEON_RAIN": 0.25, "FOG": 0.1, "STORM": 0.05},
    "NEON_RAIN": {"NEON_RAIN": 0.4, "HEAVY_RAIN": 0.2, "OVERCAST": 0.25, "STORM": 0.1, "CLEAR": 0.05},
    "HEAVY_RAIN": {"HEAVY_RAIN": 0.3, "NEON_RAIN": 0.3, "STORM": 0.2, "OVERCAST": 0.15, "BLACKOUT": 0.05},
    "FOG": {"FOG": 0.4, "CLEAR": 0.3, "OVERCAST": 0.2, "NEON_RAIN": 0.1},
    "STORM": {"STORM": 0.3, "HEAVY_RAIN": 0.3, "NEON_RAIN": 0.2, "BLACKOUT": 0.1, "OVERCAST": 0.1},
    "BLACKOUT": {"BLACKOUT": 0.2, "STORM": 0.3, "HEAVY_RAIN": 0.3, "OVERCAST": 0.2},
}

# Random event templates with consequences
WORLD_EVENT_TEMPLATES = [
    {
        "name": "Corp Security Sweep",
        "type": "crackdown",
        "districts": ["DOWNTOWN", "HIGHRISE"],
        "market_effect": "crackdown",
        "narrative": "OmniCorp security forces are conducting sweeps through {district}. Contraband prices spike.",
        "npc_interrupts": ["fixer", "crime_boss"],
    },
    {
        "name": "Underground Fight Night",
        "type": "festival",
        "districts": ["COMBAT_ZONE"],
        "market_effect": "festival",
        "narrative": "An unsanctioned fight tournament draws crowds to {district}. The economy booms.",
        "npc_interrupts": ["fighter"],
    },
    {
        "name": "Data Breach",
        "type": "hack",
        "districts": ["TECH_DISTRICT"],
        "market_effect": "hack",
        "narrative": "A massive data breach rocks {district}. Tech demand surges as everyone scrambles for patches.",
        "npc_interrupts": ["hacker"],
    },
    {
        "name": "Supply Convoy Hijacked",
        "type": "shortage",
        "districts": ["OUTSKIRTS", "COMBAT_ZONE"],
        "market_effect": "shortage",
        "narrative": "A supply convoy was hijacked en route to {district}. Consumable prices are climbing.",
        "npc_interrupts": [],
    },
    {
        "name": "Neon Festival",
        "type": "festival",
        "districts": ["DOWNTOWN"],
        "market_effect": "festival",
        "narrative": "The annual Neon Festival fills {district} with lights, music, and spending.",
        "npc_interrupts": ["socialite", "merchant"],
    },
    {
        "name": "Gang Turf War",
        "type": "war",
        "districts": ["UNDERWORLD", "COMBAT_ZONE"],
        "market_effect": "war",
        "narrative": "Rival gangs clash in {district}. Weapons and stims are in high demand.",
        "npc_interrupts": ["guard", "crime_boss", "fixer"],
    },
    {
        "name": "Market Crash",
        "type": "crash",
        "districts": ["DOWNTOWN", "HIGHRISE"],
        "market_effect": "crash",
        "narrative": "A sudden market downturn hits {district}. Prices plummet across the board.",
        "npc_interrupts": ["merchant"],
    },
    {
        "name": "Black ICE Outbreak",
        "type": "hack",
        "districts": ["TECH_DISTRICT", "HIGHRISE"],
        "market_effect": "hack",
        "narrative": "Rogue Black ICE programs are propagating through {district}'s networks.",
        "npc_interrupts": ["hacker"],
    },
    {
        "name": "Surplus Shipment",
        "type": "surplus",
        "districts": ["OUTSKIRTS", "DOWNTOWN"],
        "market_effect": "surplus",
        "narrative": "An unexpectedly large shipment arrived at {district}. Prices drop temporarily.",
        "npc_interrupts": [],
    },
    {
        "name": "Power Grid Failure",
        "type": "disaster",
        "districts": ["TECH_DISTRICT", "DOWNTOWN", "OUTSKIRTS"],
        "market_effect": "shortage",
        "narrative": "The power grid failed in {district}. Darkness and chaos reign until repairs are complete.",
        "npc_interrupts": ["guard", "hacker"],
    },
]


# ──── Data classes ────


@dataclass
class WorldTickResult:
    """Result of one living-world tick cycle.

    Attributes:
        tick_number: Sequential tick counter.
        game_time: Current game time display string.
        time_of_day: Current period (dawn/morning/afternoon/etc).
        npc_transitions: How many NPCs moved this tick.
        faction_decisions: Number of faction decisions made.
        market_changes: Number of price changes.
        weather_changed: Whether weather transitioned.
        events_generated: List of world events that fired.
        wars_active: Number of active faction wars.
    """
    tick_number: int = 0
    game_time: str = ""
    time_of_day: str = ""
    npc_transitions: int = 0
    faction_decisions: int = 0
    market_changes: int = 0
    weather_changed: bool = False
    events_generated: List[Dict[str, Any]] = field(default_factory=list)
    wars_active: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──── LivingWorld Engine ────


class LivingWorld:
    """Central orchestrator for all living-world systems.

    Runs as a daemon thread, ticking every game hour (60 real seconds
    by default).  Each tick coordinates the market, NPC routines, faction
    AI, weather, and stochastic event generation.
    """

    def __init__(self, tick_interval: float = 60.0) -> None:
        self._lock = threading.RLock()
        self._tick_interval = tick_interval
        self._tick_count = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_time_slot = ""
        self._event_log: List[Dict[str, Any]] = []
        self._last_weather = "CLEAR"
        self._initialized = False
        logger.info("LivingWorld created (interval=%.1fs)", tick_interval)

    # ──── Lifecycle ────

    def start(self) -> None:
        """Start the living-world daemon thread."""
        if self._running:
            return
        self._running = True
        self._init_subsystems()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="LivingWorld"
        )
        self._thread.start()
        logger.info("LivingWorld daemon started")

    def stop(self) -> None:
        """Stop the daemon thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("LivingWorld daemon stopped")

    def _init_subsystems(self) -> None:
        """Initialize subsystems on first start."""
        if self._initialized:
            return

        try:
            rm = _get_routine_manager()
            count = rm.register_defaults()
            logger.info("LivingWorld: registered %d default NPC routines", count)
        except Exception as exc:
            logger.warning("LivingWorld: routine init failed: %s", exc)

        try:
            ai = _get_faction_ai()
            tm = _get_territory()
            if tm:
                control = {}
                from engine.world.territory import DISTRICT_NAMES, DEFAULT_CONTROL
                for d in DISTRICT_NAMES:
                    control[d] = dict(DEFAULT_CONTROL.get(d, {}))
                ai.set_control(control)
                logger.info("LivingWorld: faction AI initialized with territory data")
        except Exception as exc:
            logger.warning("LivingWorld: faction AI init failed: %s", exc)

        self._initialized = True

    def _run_loop(self) -> None:
        """Main daemon loop — ticks every interval."""
        while self._running:
            try:
                self.tick()
            except Exception as exc:
                logger.error("LivingWorld tick error: %s", exc)
            time.sleep(self._tick_interval)

    # ──── Core Tick ────

    def tick(self) -> WorldTickResult:
        """Execute one full world tick cycle.

        Coordinates all subsystems in order:
        1. Game clock → time_of_day
        2. NPC routines → transitions
        3. Faction AI → decisions
        4. Market → price drift
        5. Weather → probabilistic transition
        6. Events → stochastic generation + consequences

        Returns:
            Summary of everything that happened this tick.
        """
        with self._lock:
            self._tick_count += 1
            result = WorldTickResult(tick_number=self._tick_count)

        # 1. Game clock
        try:
            ws = _get_world_state()
            wt = ws.get_time()
            result.game_time = wt.to_display()
            result.time_of_day = wt.time_of_day
        except Exception as exc:
            logger.debug("LivingWorld: clock read failed: %s", exc)
            result.time_of_day = "afternoon"

        # 2. NPC routines
        try:
            rm = _get_routine_manager()
            rt_result = rm.tick(result.time_of_day)
            result.npc_transitions = rt_result.get("transitions", 0)
        except Exception as exc:
            logger.debug("LivingWorld: routine tick failed: %s", exc)

        # 3. Faction AI (every 5th tick to avoid churn)
        if self._tick_count % 5 == 0:
            try:
                ai = _get_faction_ai()
                ai_result = ai.tick()
                result.faction_decisions = len(ai_result.get("decisions", []))
                result.wars_active = len(ai.get_active_wars())

                # Feed territory changes to market
                if ai_result.get("control_changes"):
                    try:
                        mkt = _get_market()
                        ctrl = {}
                        for d_name in ["DOWNTOWN", "COMBAT_ZONE", "HIGHRISE",
                                       "UNDERWORLD", "TECH_DISTRICT", "OUTSKIRTS"]:
                            ai_ctrl = ai._control.get(d_name, {})
                            if ai_ctrl:
                                ctrl[d_name] = ai_ctrl
                        if ctrl:
                            mkt.update_territory_multipliers(ctrl)
                    except Exception as e:
                        logger.debug("[LivingWorld] Territory multiplier update failed (operation=faction_tick): %s", e)
            except Exception as exc:
                logger.debug("LivingWorld: faction tick failed: %s", exc)

        # 4. Market tick
        try:
            mkt = _get_market()
            mkt_result = mkt.tick()
            result.market_changes = mkt_result.get("price_changes", 0)
        except Exception as exc:
            logger.debug("LivingWorld: market tick failed: %s", exc)

        # 5. Weather cycle (15% chance per tick)
        if random.random() < 0.15:
            try:
                new_weather = self._cycle_weather()
                if new_weather != self._last_weather:
                    result.weather_changed = True
                    self._last_weather = new_weather
                    ws = _get_world_state()
                    from engine.world.world_state import Weather
                    weather_enum = getattr(Weather, new_weather, None)
                    if weather_enum:
                        ws.set_weather("global", weather_enum)
            except Exception as exc:
                logger.debug("LivingWorld: weather cycle failed: %s", exc)

        # 6. Stochastic events (20% chance per tick)
        if random.random() < 0.20:
            try:
                event = self._generate_event()
                if event:
                    result.events_generated.append(event)
                    self._apply_event_consequences(event)
                    with self._lock:
                        self._event_log.append(event)
                        if len(self._event_log) > 200:
                            self._event_log = self._event_log[-200:]
            except Exception as exc:
                logger.debug("LivingWorld: event generation failed: %s", exc)

        # Emit tick summary
        bus = _get_event_bus()
        if bus:
            try:
                bus.publish("living_world_tick", result.to_dict())
            except Exception as e:
                logger.debug("[LivingWorld] EventBus publish failed (operation=tick_summary): %s", e)

        logger.debug(
            "LivingWorld tick #%d: %s — %d NPC moves, %d faction decisions, "
            "%d market changes, weather_changed=%s, events=%d",
            result.tick_number, result.game_time, result.npc_transitions,
            result.faction_decisions, result.market_changes,
            result.weather_changed, len(result.events_generated),
        )

        return result

    # ──── Weather ────

    def _cycle_weather(self) -> str:
        """Compute next weather based on Markov transition probabilities."""
        current = self._last_weather
        transitions = WEATHER_TRANSITIONS.get(current, WEATHER_TRANSITIONS["CLEAR"])

        states = list(transitions.keys())
        weights = [transitions[s] for s in states]
        chosen = random.choices(states, weights=weights, k=1)[0]
        return chosen

    # ──── Event Generation ────

    def _generate_event(self) -> Optional[Dict[str, Any]]:
        """Generate a random world event from templates."""
        template = random.choice(WORLD_EVENT_TEMPLATES)
        district = random.choice(template["districts"])

        return {
            "name": template["name"],
            "type": template["type"],
            "district": district,
            "market_effect": template["market_effect"],
            "narrative": template["narrative"].format(district=district),
            "npc_interrupts": template["npc_interrupts"],
            "tick": self._tick_count,
        }

    def _apply_event_consequences(self, event: Dict[str, Any]) -> None:
        """Apply an event's effects to market and NPCs."""
        # Market effect
        market_effect = event.get("market_effect")
        if market_effect:
            try:
                mkt = _get_market()
                mkt.apply_event(market_effect)
            except Exception as e:
                logger.debug("[LivingWorld] Market event apply failed (operation=apply_event_effects): %s", e)

        # NPC interruptions
        interrupts = event.get("npc_interrupts", [])
        if interrupts:
            try:
                rm = _get_routine_manager()
                for npc_id in rm.list_npcs():
                    routine = rm.get_routine(npc_id)
                    if routine and routine.get("archetype") in interrupts:
                        rm.interrupt_npc(
                            npc_id,
                            reason=event.get("narrative", event["name"]),
                            location=event.get("district", ""),
                        )
            except Exception as e:
                logger.debug("[LivingWorld] NPC interrupt failed (operation=apply_event_effects): %s", e)

        # Broadcast event
        bus = _get_event_bus()
        if bus:
            try:
                bus.publish("world_event", event)
            except Exception as e:
                logger.debug("[LivingWorld] EventBus world_event publish failed (operation=apply_event_effects): %s", e)

    # ──── Status / Queries ────

    def get_status(self) -> Dict[str, Any]:
        """Return a comprehensive snapshot of the living world state.

        Returns:
            Dict with subsystem summaries: market, NPCs, factions, weather, events.
        """
        status: Dict[str, Any] = {
            "running": self._running,
            "tick_count": self._tick_count,
        }

        try:
            ws = _get_world_state()
            wt = ws.get_time()
            status["game_time"] = wt.to_display()
            status["time_of_day"] = wt.time_of_day
        except Exception as e:
            logger.debug("[LivingWorld] Game time unavailable (operation=get_status): %s", e)
            status["game_time"] = "unknown"

        try:
            mkt = _get_market()
            status["market"] = mkt.get_stats()
        except Exception as e:
            logger.debug("[LivingWorld] Market stats unavailable (operation=get_status): %s", e)
            status["market"] = {}

        try:
            rm = _get_routine_manager()
            status["npc_routines"] = rm.get_stats()
        except Exception as e:
            logger.debug("[LivingWorld] NPC routine stats unavailable (operation=get_status): %s", e)
            status["npc_routines"] = {}

        try:
            ai = _get_faction_ai()
            status["faction_ai"] = ai.get_stats()
        except Exception as e:
            logger.debug("[LivingWorld] Faction AI stats unavailable (operation=get_status): %s", e)
            status["faction_ai"] = {}

        status["weather"] = self._last_weather

        with self._lock:
            status["recent_events"] = self._event_log[-5:]

        return status

    def get_event_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent world events.

        Args:
            limit: Maximum events.

        Returns:
            List of event dicts (newest first).
        """
        with self._lock:
            return self._event_log[-limit:][::-1]

    def get_stats(self) -> Dict[str, Any]:
        """Return living world statistics."""
        with self._lock:
            event_types: Dict[str, int] = {}
            for e in self._event_log:
                t = e.get("type", "unknown")
                event_types[t] = event_types.get(t, 0) + 1

            return {
                "tick_count": self._tick_count,
                "running": self._running,
                "total_events": len(self._event_log),
                "event_type_distribution": event_types,
                "current_weather": self._last_weather,
            }

    def reset(self) -> None:
        """Reset living world state (stops daemon if running)."""
        self.stop()
        with self._lock:
            self._tick_count = 0
            self._event_log.clear()
            self._last_weather = "CLEAR"
            self._last_time_slot = ""
            self._initialized = False

        try:
            _get_market().reset()
        except Exception as e:
            logger.debug("[LivingWorld] Market reset failed (operation=reset): %s", e)
        try:
            _get_routine_manager().reset()
        except Exception as e:
            logger.debug("[LivingWorld] Routine manager reset failed (operation=reset): %s", e)
        try:
            _get_faction_ai().reset()
        except Exception as e:
            logger.debug("[LivingWorld] Faction AI reset failed (operation=reset): %s", e)


# ──── Singleton ────

_instance: Optional[LivingWorld] = None
_instance_lock = threading.Lock()


def get_living_world(tick_interval: float = 60.0) -> LivingWorld:
    """Return the singleton LivingWorld instance.

    Args:
        tick_interval: Seconds between ticks (default 60).

    Returns:
        The LivingWorld instance.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LivingWorld(tick_interval=tick_interval)
    return _instance


def reset_living_world() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    if _instance is not None:
        _instance.stop()
    _instance = None
