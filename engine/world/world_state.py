"""World state manager for CosySim v0.68 "Dark Renaissance".

Provides the game clock, NPC scheduling, per-scene weather, and live world
events — the "living world" backbone that keeps ticking even when no single
scene is actively in focus.

Game-time scaling:
    1 real minute == 1 game hour
    24 real minutes == 1 in-game day

Nexus storage:
    content_type="memory", category="world_state", title="world:state"

Usage::

    from engine.world.world_state import get_world_state, Weather

    ws = get_world_state()
    print(ws.get_time().to_display())          # "Monday, 14:00 (Afternoon)"
    ws.set_weather("neon_district", Weather.NEON_RAIN)
    summary = ws.tick()
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from engine.nexus.client import get_nexus_client
from engine.events.event_bus import get_event_bus, EventTypes
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Real seconds that elapse per in-game hour (1 real minute = 1 game hour).
_SECONDS_PER_GAME_HOUR: float = 60.0

_DAY_NAMES: List[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

#: Default NPC schedule when no custom schedule has been set.
_DEFAULT_NPC_AVAILABLE_TIMES: List[str] = [
    "afternoon",
    "evening",
    "night",
    "late_night",
]


# ---------------------------------------------------------------------------
# WorldTime
# ---------------------------------------------------------------------------


@dataclass
class WorldTime:
    """A snapshot of the current game time.

    Attributes:
        game_hour: Hour of the day (0–23).
        game_day: Days elapsed since world start (0+).
        game_day_name: Human-readable day name, cycling Monday–Sunday.
        time_of_day: Descriptive period label.
            One of: ``dawn``, ``morning``, ``afternoon``, ``evening``,
            ``night``, ``late_night``.
    """

    game_hour: int
    game_day: int
    game_day_name: str
    time_of_day: str

    def to_display(self) -> str:
        """Return a human-readable time string.

        Returns:
            Formatted string, e.g. ``"Monday, 09:00 (Morning)"``.
        """
        label = self.time_of_day.replace("_", " ").title()
        return f"{self.game_day_name}, {self.game_hour:02d}:00 ({label})"


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


class Weather(str, Enum):
    """Weather conditions available in CosySim scenes.

    Each member value doubles as a particle/visual preset identifier key that
    is resolved by the renderer (see :attr:`particle_preset`).
    """

    CLEAR = "clear"
    OVERCAST = "overcast"
    NEON_RAIN = "neon_rain"
    HEAVY_RAIN = "heavy_rain"
    FOG = "fog"
    STORM = "storm"
    BLACKOUT = "blackout"

    @property
    def particle_preset(self) -> str:
        """Return the visual renderer particle-system preset name.

        Returns:
            Preset identifier string passed to the particle system.
        """
        _presets: Dict[str, str] = {
            "clear": "none",
            "overcast": "overcast_light",
            "neon_rain": "neon_rain",
            "heavy_rain": "heavy_rain",
            "fog": "smoke",
            "storm": "storm_heavy",
            "blackout": "darkness",
        }
        return _presets.get(self.value, "none")


# ---------------------------------------------------------------------------
# WorldEvent
# ---------------------------------------------------------------------------


@dataclass
class WorldEvent:
    """A time-limited event that affects one or more scenes.

    Attributes:
        id: Unique event identifier.
        name: Short display name.
        description: LLM-facing narrative description.
        scene: Scene this event affects, or ``"global"`` for world-wide.
        event_type: Semantic category.
            Known types: ``gang_war``, ``corp_raid``, ``fight_night``,
            ``festival``, ``blackout``, ``underground_auction``,
            ``hacker_event``.
        started_at: Real epoch timestamp when the event was created.
        expires_at: Real epoch timestamp after which the event is inactive.
            Use ``0`` for never-expiring events.
        active: Whether the event is currently live.
        payload: Arbitrary extra context dictionary for the director.
    """

    id: str
    name: str
    description: str
    scene: str
    event_type: str
    started_at: float
    expires_at: float
    active: bool = True
    payload: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_time_of_day(hour: int) -> str:
    """Map a 0–23 game hour to a descriptive time-of-day label.

    Ranges:
        dawn 5–7 | morning 8–11 | afternoon 12–17 | evening 18–21
        night 22–23 and 0–1 | late_night 2–4

    Args:
        hour: Game hour in the range 0–23.

    Returns:
        One of ``dawn``, ``morning``, ``afternoon``, ``evening``,
        ``night``, or ``late_night``.
    """
    if 5 <= hour <= 7:
        return "dawn"
    if 8 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 17:
        return "afternoon"
    if 18 <= hour <= 21:
        return "evening"
    if hour >= 22 or hour <= 1:
        return "night"
    # 2–4
    return "late_night"


# ---------------------------------------------------------------------------
# WorldState
# ---------------------------------------------------------------------------


class WorldState:
    """Living-world state manager — clock, weather, events, NPC schedules.

    The game clock scales real wall-clock seconds so that one real minute
    equals one in-game hour (24 real minutes == one in-game day).  All
    mutable world state is persisted to and loaded from Nexus so that it
    survives CosySim restarts.

    This class is not intended to be instantiated directly — use
    :func:`get_world_state` to obtain the process-wide singleton.

    Args:
        nexus_client: Optional :class:`~engine.nexus.client.NexusClient`
            override.  When ``None`` the default client is fetched from
            :func:`~engine.nexus.client.get_nexus_client`.  Pass a mock in
            tests to avoid real HTTP calls.
    """

    def __init__(self, nexus_client=None) -> None:
        self._lock = threading.Lock()
        self._nexus = nexus_client if nexus_client is not None else _safe_get_nexus()

        # Real epoch when this world "started" — persisted so restarts
        # continue from the same in-game timeline.
        self._start_time: float = time.time()

        # scene_id → Weather (always contains at least "global").
        self._weather: Dict[str, Weather] = {"global": Weather.CLEAR}

        # All world events, including expired ones (filtered on read).
        self._events: List[WorldEvent] = []

        # character_id → list of available time-of-day labels.
        self._npc_schedules: Dict[str, List[str]] = {}

        self._load_state()

    # ------------------------------------------------------------------
    # Game clock
    # ------------------------------------------------------------------

    def get_time(self) -> WorldTime:
        """Calculate and return the current game time.

        The calculation is purely derived from wall-clock elapsed time, so
        no mutation or locking is required.

        Returns:
            A :class:`WorldTime` snapshot.
        """
        elapsed: float = time.time() - self._start_time
        total_game_hours: int = int(elapsed / _SECONDS_PER_GAME_HOUR)
        game_hour: int = total_game_hours % 24
        game_day: int = total_game_hours // 24
        day_name: str = _DAY_NAMES[game_day % 7]
        tod: str = _classify_time_of_day(game_hour)
        return WorldTime(
            game_hour=game_hour,
            game_day=game_day,
            game_day_name=day_name,
            time_of_day=tod,
        )

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------

    def get_weather(self, scene: str = "global") -> Weather:
        """Return the current weather for a scene.

        Falls back to the global weather if no per-scene override exists.

        Args:
            scene: Scene identifier or ``"global"``.

        Returns:
            The active :class:`Weather` for that scene.
        """
        return self._weather.get(scene, self._weather.get("global", Weather.CLEAR))

    def set_weather(self, scene: str, weather: Weather) -> None:
        """Set weather for a scene and persist the change to Nexus.

        Args:
            scene: Scene identifier or ``"global"``.
            weather: New :class:`Weather` value.
        """
        with self._lock:
            self._weather[scene] = weather
        self._persist_state()
        logger.info("Weather for '%s' set to %s", scene, weather.value)

    # ------------------------------------------------------------------
    # World events
    # ------------------------------------------------------------------

    def get_active_events(self, scene: str = "") -> List[WorldEvent]:
        """Return active world events, optionally filtered by scene.

        Expired events are silently deactivated on read — no separate
        housekeeping loop is required.

        Args:
            scene: When non-empty, only return events whose ``scene``
                attribute matches this value or ``"global"``.

        Returns:
            List of currently active :class:`WorldEvent` objects.
        """
        now: float = time.time()
        with self._lock:
            for ev in self._events:
                if ev.active and ev.expires_at > 0 and now >= ev.expires_at:
                    ev.active = False
            if scene:
                return [
                    ev
                    for ev in self._events
                    if ev.active and (ev.scene == scene or ev.scene == "global")
                ]
            return [ev for ev in self._events if ev.active]

    def add_event(self, event: WorldEvent) -> None:
        """Register a world event and persist to Nexus.

        Args:
            event: :class:`WorldEvent` to add.
        """
        with self._lock:
            self._events.append(event)
        self._persist_state()
        logger.info("World event added: %s (%s)", event.name, event.event_type)

    def expire_event(self, event_id: str) -> None:
        """Immediately expire a world event by ID.

        Sets ``active=False`` and ``expires_at`` to the current real time.
        Safe to call for unknown IDs (no-op).

        Args:
            event_id: Unique identifier of the event to expire.
        """
        with self._lock:
            for ev in self._events:
                if ev.id == event_id:
                    ev.active = False
                    ev.expires_at = time.time()
                    logger.info("World event expired: %s", event_id)
                    break
        self._persist_state()

    # ------------------------------------------------------------------
    # NPC schedules
    # ------------------------------------------------------------------

    def get_npc_availability(self, character_id: str) -> bool:
        """Check whether an NPC is available at the current game time.

        Uses the schedule stored via :meth:`set_npc_schedule`.  Falls back
        to :data:`_DEFAULT_NPC_AVAILABLE_TIMES` (afternoon/evening/night/
        late_night) when no custom schedule exists.

        Args:
            character_id: Character identifier to query.

        Returns:
            ``True`` if the NPC is available right now, ``False`` otherwise.
        """
        schedule: List[str] = self._npc_schedules.get(
            character_id, _DEFAULT_NPC_AVAILABLE_TIMES
        )
        current_tod: str = self.get_time().time_of_day
        return current_tod in schedule

    def set_npc_schedule(
        self, character_id: str, available_times: List[str]
    ) -> None:
        """Set the availability schedule for a character and persist to Nexus.

        Args:
            character_id: Character identifier.
            available_times: Ordered list of time-of-day labels when the
                NPC should be considered available.
        """
        with self._lock:
            self._npc_schedules[character_id] = list(available_times)
        self._persist_state()
        logger.info(
            "NPC schedule updated for '%s': %s", character_id, available_times
        )

    # ------------------------------------------------------------------
    # Tick and summary
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        """Advance the living world one tick.

        Prunes expired events, builds a world summary, and fires
        :attr:`~engine.events.event_bus.EventTypes.WORLD_TICK` on the
        :class:`~engine.events.event_bus.EventBus`.

        Returns:
            World summary dictionary — same shape as
            :meth:`get_world_summary`.
        """
        # Prune any events that have expired since the last tick.
        now: float = time.time()
        with self._lock:
            for ev in self._events:
                if ev.active and ev.expires_at > 0 and now >= ev.expires_at:
                    ev.active = False

        summary: dict = self.get_world_summary()

        # Fire EventBus notification — lazy import guards against circular
        # import chains at startup.
        try:
            bus = get_event_bus()
            bus.publish(EventTypes.WORLD_TICK, summary)
        except Exception as exc:  # pragma: no cover
            logger.warning("EventBus publish failed during world tick: %s", exc)

        return summary

    def get_world_summary(self) -> dict:
        """Return the full current world state as a plain dictionary.

        Returns:
            Dictionary with the following keys:

            * ``time`` — nested dict with ``game_hour``, ``game_day``,
              ``game_day_name``, ``time_of_day``, ``display``.
            * ``weather`` — mapping of scene → weather value string.
            * ``active_events`` — list of slim event dicts.
            * ``npcs_available`` — list of character IDs that are
              currently available.
        """
        wt: WorldTime = self.get_time()
        active_events: List[WorldEvent] = self.get_active_events()

        weather_summary: Dict[str, str] = {
            scene: w.value for scene, w in self._weather.items()
        }

        npcs_available: List[str] = [
            npc_id
            for npc_id in self._npc_schedules
            if self.get_npc_availability(npc_id)
        ]

        return {
            "time": {
                "game_hour": wt.game_hour,
                "game_day": wt.game_day,
                "game_day_name": wt.game_day_name,
                "time_of_day": wt.time_of_day,
                "display": wt.to_display(),
            },
            "weather": weather_summary,
            "active_events": [
                {
                    "id": ev.id,
                    "name": ev.name,
                    "scene": ev.scene,
                    "event_type": ev.event_type,
                    "description": ev.description,
                }
                for ev in active_events
            ],
            "npcs_available": npcs_available,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        """Serialise and save the current world state to Nexus.

        Searches for an existing ``"world:state"`` entry and updates it;
        creates a new one when none is found.  All errors are caught and
        logged so that a Nexus outage does not crash the world simulation.
        """
        if self._nexus is None:
            return
        try:
            state: dict = {
                "start_time": self._start_time,
                "weather": {k: v.value for k, v in self._weather.items()},
                "events": [asdict(ev) for ev in self._events],
                "npc_schedules": self._npc_schedules,
            }
            content: str = json.dumps(state)

            # Check for an existing entry to update rather than accumulate.
            results: List[Dict] = self._nexus.search("world:state")
            existing_id: Optional[str] = None
            for r in results:
                if r.get("title") == "world:state":
                    existing_id = r.get("id")
                    break

            if existing_id:
                self._nexus.update_entry(existing_id, content=content)
            else:
                self._nexus.add_entry(
                    title="world:state",
                    content=content,
                    content_type="memory",
                    category="world_state",
                )
        except Exception as exc:
            logger.warning("Failed to persist world state to Nexus: %s", exc)

    def _load_state(self) -> None:
        """Restore world state from Nexus on initialisation.

        Silently skips loading if Nexus is unavailable or the entry does
        not yet exist (first-run case).
        """
        if self._nexus is None:
            return
        try:
            results: List[Dict] = self._nexus.search("world:state")
            for r in results:
                if r.get("title") != "world:state":
                    continue

                raw: str = r.get("content", "{}")
                state: dict = json.loads(raw)

                self._start_time = float(
                    state.get("start_time", self._start_time)
                )

                # Restore per-scene weather.
                for scene, wval in state.get("weather", {}).items():
                    try:
                        self._weather[scene] = Weather(wval)
                    except ValueError:
                        logger.warning(
                            "Unknown weather value '%s' for scene '%s' — skipped.",
                            wval,
                            scene,
                        )

                # Restore world events.
                self._events = []
                for ev_dict in state.get("events", []):
                    try:
                        self._events.append(WorldEvent(**ev_dict))
                    except (TypeError, KeyError) as exc:
                        logger.warning(
                            "Could not deserialise world event: %s", exc
                        )

                # Restore NPC schedules.
                self._npc_schedules = dict(state.get("npc_schedules", {}))

                logger.info(
                    "World state loaded from Nexus (%d event(s), %d NPC schedule(s)).",
                    len(self._events),
                    len(self._npc_schedules),
                )
                return  # Only process the first matching entry.

        except Exception as exc:
            logger.warning("Failed to load world state from Nexus: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_get_nexus():
    """Return a Nexus client or ``None`` if the client is unavailable.

    Returns:
        A :class:`~engine.nexus.client.NexusClient` instance, or ``None``
        when the Nexus service cannot be reached.
    """
    try:
        return get_nexus_client()
    except Exception as exc:
        logger.debug("Nexus client unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# WorldStateInterceptor
# ---------------------------------------------------------------------------


class WorldStateInterceptor(InterceptorBase):
    """Pre-call interceptor that injects current world state into the system prompt.

    Prepends a ``[WORLD STATE]`` block containing the current game time,
    active weather, and any live world events so characters respond with
    awareness of the living world.

    Priority 15 places this after memory (7) and before reputation (22).
    """

    name: str = "world_state"
    priority: int = 15

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject world context into the system prompt before LLM call.

        Args:
            ctx: Mutable interaction context bag.
        """
        try:
            ws = get_world_state()
            time_str = ws.get_time().to_display()
            scene = ctx.get("scene", "")
            weather = ws.get_weather(scene) if scene else None
            events = ws.get_active_events()

            lines = [f"Current time: {time_str}"]
            if weather:
                lines.append(f"Weather: {weather.value}")
            if events:
                event_summaries = [e.description for e in events[:3]]
                lines.append("Active events: " + "; ".join(event_summaries))

            block = "[WORLD STATE]\n" + "\n".join(lines) + "\n[/WORLD STATE]"
            existing = ctx.get("system_prompt", "") or ""
            ctx["system_prompt"] = f"{block}\n{existing}"
        except Exception as exc:
            logger.debug("WorldStateInterceptor.pre_call skipped — %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Pass-through; no post-LLM mutation needed.

        Args:
            ctx: Mutable interaction context bag.
        """


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_WORLD_STATE: Optional[WorldState] = None
_WORLD_LOCK: threading.Lock = threading.Lock()


def get_world_state() -> WorldState:
    """Return the process-wide :class:`WorldState` singleton.

    Thread-safe double-checked locking ensures the instance is created
    at most once even under concurrent calls.

    Returns:
        The singleton :class:`WorldState` instance.
    """
    global _WORLD_STATE
    if _WORLD_STATE is None:
        with _WORLD_LOCK:
            if _WORLD_STATE is None:
                _WORLD_STATE = WorldState()
    return _WORLD_STATE
