"""Background living-world simulation daemon for CosySim v0.68 "Dark Renaissance".

``WorldSim`` runs as a daemon thread.  It fires scripted events on a
game-clock schedule (1 real minute = 1 game hour) so that the world keeps
ticking even when the player is not actively in a scene.  All generated
:class:`SimEvent` objects are:

* Appended to an in-memory ring buffer (max 200 entries).
* Persisted to Nexus as ``history`` / ``world_sim`` entries.
* Broadcast on the :class:`~engine.events.event_bus.EventBus` so scenes can
  react in real time.

Game-clock rate (mirrors WorldState)::

    1 real second  ==  1 game minute
    60 real seconds == 1 game hour
    1 440 real seconds == 1 in-game day

Usage::

    from engine.world.world_sim import get_world_sim, start_world_sim

    sim = start_world_sim()          # start daemon
    digest = sim.get_digest("lounge")  # events player missed
    sim.stop()
"""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from engine.events.event_bus import EventTypes, get_event_bus
from engine.nexus.client import get_nexus_client
from engine.world.neon_city_events import (
    ECONOMY_EVENTS,
    FACTION_EVENTS_RICH,
    GHOST_MESSAGES_RICH,
    NPC_ACTIONS_RICH,
    WORLD_EVENTS_RICH,
    get_events_for_scene,
)
from engine.world.world_state import WorldEvent, WorldTime, get_world_state

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SimEventType
# ---------------------------------------------------------------------------


class SimEventType(str, Enum):
    """Semantic categories for :class:`SimEvent` objects.

    Values mirror the CosySim scene taxonomy so that consumers can filter
    events by type without string matching on titles.
    """

    NPC_ACTION = "npc_action"
    FACTION_SHIFT = "faction_shift"
    SCENE_AMBIENT = "scene_ambient"
    HACKER_MESSAGE = "hacker_message"
    ARENA_MATCH = "arena_match"
    WORLD_EVENT = "world_event"
    ECONOMY_TICK = "economy_tick"


# ---------------------------------------------------------------------------
# SimEvent
# ---------------------------------------------------------------------------


@dataclass
class SimEvent:
    """A single simulated world event.

    Attributes:
        id: UUID4 unique identifier.
        event_type: Semantic category (see :class:`SimEventType`).
        title: Short display title.
        description: LLM-facing narrative description.
        scene: Scene this event affects, or ``""`` for global.
        actor: NPC or entity that caused the event (may be empty).
        intensity: Narrative weight on a 0–3 scale.
        payload: Arbitrary extra context for downstream handlers.
        created_at: Human-readable game-time string e.g. ``"Day 3 14:30"``.
        seen_by_player: ``True`` once :meth:`WorldSim.get_digest` has
            returned this event.
    """

    id: str
    event_type: SimEventType
    title: str
    description: str
    scene: str
    actor: str = ""
    intensity: float = 1.0
    payload: dict = field(default_factory=dict)
    created_at: str = ""
    seen_by_player: bool = False


# ---------------------------------------------------------------------------
# NPC action templates
# ---------------------------------------------------------------------------

NPC_ACTIONS: List[Dict] = [
    {
        "scene": "neoncity",
        "actor": "street_vendor",
        "title": "Vendor dispute",
        "desc": "A street vendor gets into an argument with a corp drone over territory.",
    },
    {
        "scene": "lounge",
        "actor": "bouncer",
        "title": "Ejection incident",
        "desc": "The Velvet Pit bouncer throws out a rowdy patron who owed money.",
    },
    {
        "scene": "tavern",
        "actor": "bard",
        "title": "New ballad",
        "desc": "The tavern bard debuts a new song about a recent heist.",
    },
    {
        "scene": "casino",
        "actor": "dealer",
        "title": "Loaded deck caught",
        "desc": "Security catches someone using a marked deck at Club Noir.",
    },
    {
        "scene": "arena",
        "actor": "challenger",
        "title": "New challenger",
        "desc": "A mysterious fighter challenges the current champion via note.",
    },
    {
        "scene": "neoncity",
        "actor": "gang_lieutenant",
        "title": "Gang shakedown",
        "desc": "A gang lieutenant shakes down a noodle stall for protection money.",
    },
    {
        "scene": "lounge",
        "actor": "information_broker",
        "title": "Deal brokered",
        "desc": "A well-known information broker finalises a transaction in a private booth.",
    },
    {
        "scene": "heist",
        "actor": "fence",
        "title": "Hot merchandise moved",
        "desc": "A fence quietly offloads a crate of stolen corp hardware.",
    },
    {
        "scene": "phone",
        "actor": "unknown_caller",
        "title": "Anonymous tip",
        "desc": "An anonymous caller warns about an upcoming sweep of the district.",
    },
    {
        "scene": "casino",
        "actor": "high_roller",
        "title": "High stakes table",
        "desc": "A masked high-roller drops 50k credits in a single hand at the VIP table.",
    },
    {
        "scene": "arena",
        "actor": "medic",
        "title": "Fighter injured",
        "desc": "A top-ranked fighter is wheeled out of the pit on a stretcher; cause unknown.",
    },
    {
        "scene": "neoncity",
        "actor": "corpo_patrol",
        "title": "Checkpoint established",
        "desc": "OmniCorp enforcers set up an ID checkpoint on the main boulevard.",
    },
    {
        "scene": "tavern",
        "actor": "spy",
        "title": "Overheard conversation",
        "desc": "Two figures in the corner speak quietly about a missing shipment.",
    },
    {
        "scene": "lounge",
        "actor": "jazz_singer",
        "title": "Late-night set",
        "desc": "The lounge jazz singer ends her set early; rumour says she received a threat.",
    },
    {
        "scene": "heist",
        "actor": "lookout",
        "title": "Lookout spotted",
        "desc": "A nervous lookout paces the alley outside the target building.",
    },
    {
        "scene": "neoncity",
        "actor": "holo_preacher",
        "title": "Holo-sermon",
        "desc": "A holo-preacher decries the corps from a makeshift podium, drawing a crowd.",
    },
    {
        "scene": "casino",
        "actor": "pit_boss",
        "title": "Credit freeze",
        "desc": "The pit boss quietly freezes a player's account pending identity verification.",
    },
    {
        "scene": "arena",
        "actor": "promoter",
        "title": "Exhibition arranged",
        "desc": "The arena promoter posts a flyer for an unranked exhibition bout tonight.",
    },
    {
        "scene": "tavern",
        "actor": "smuggler",
        "title": "Back-room deal",
        "desc": "A smuggler slides an unmarked package under the bar to the innkeeper.",
    },
    {
        "scene": "neoncity",
        "actor": "graffiti_artist",
        "title": "Graffiti warning",
        "desc": "Fresh graffiti appears overnight: a skull with corp logos for eyes.",
    },
    {
        "scene": "lounge",
        "actor": "data_courier",
        "title": "Data drop",
        "desc": "A data courier passes a chip to a waiting contact between drinks.",
    },
]

# ---------------------------------------------------------------------------
# Faction templates
# ---------------------------------------------------------------------------

FACTION_NAMES: List[str] = [
    "OmniCorp",
    "NeoTech",
    "BlackMarket",
    "Ghost_Net",
    "SynthSec",
    "DeepState",
]

FACTION_ACTIONS: List[str] = [
    "expands territory",
    "loses ground",
    "declares conflict with",
    "forms alliance with",
    "bribes officials in",
    "goes dark in sector",
]

# ---------------------------------------------------------------------------
# 0xGH0ST message templates
# ---------------------------------------------------------------------------

GHOST_MESSAGES: List[str] = [
    "They moved the package. Check the drop point.",
    "Corp comms intercepted. Sending now.",
    "Someone's been asking about you. Be careful.",
    "Phase 2 begins. You know what to do.",
    "I found something. Meet me at the node.",
    "Encrypted burst incoming. Don't open it on a corp network.",
    "The auction has a new buyer. Things just got complicated.",
    "Your name came up in a SynthSec briefing. Lay low.",
]

# ---------------------------------------------------------------------------
# World-event templates
# ---------------------------------------------------------------------------

WORLD_EVENTS: List[Dict] = [
    {
        "title": "Corporate Blackout",
        "desc": "NeoTech cuts power to the lower districts. Lights out in three scenes.",
        "scene": "neoncity",
        "event_type": "blackout",
    },
    {
        "title": "Underground Auction",
        "desc": "A mysterious auction of stolen goods draws powerful players.",
        "scene": "lounge",
        "event_type": "underground_auction",
    },
    {
        "title": "Faction War Erupts",
        "desc": "OmniCorp and BlackMarket forces clash in the streets.",
        "scene": "neoncity",
        "event_type": "gang_war",
    },
    {
        "title": "Grand Tournament Announced",
        "desc": "The Colosseum announces a 16-fighter elimination tournament.",
        "scene": "arena",
        "event_type": "fight_night",
    },
    {
        "title": "The Ghost Goes Dark",
        "desc": "0xGH0ST's signals go silent. Something is very wrong.",
        "scene": "phone",
        "event_type": "hacker_event",
    },
    {
        "title": "Festival of Neon",
        "desc": "Street celebrations light up NeonCity. Everyone is out tonight.",
        "scene": "neoncity",
        "event_type": "festival",
    },
    {
        "title": "Corp Raid",
        "desc": "Security forces sweep through the black market district.",
        "scene": "neoncity",
        "event_type": "corp_raid",
    },
    {
        "title": "Heist Gone Wrong",
        "desc": "News of a botched heist spreads. Heat levels rise city-wide.",
        "scene": "heist",
        "event_type": "gang_war",
    },
]

# ---------------------------------------------------------------------------
# Arena fighter pool
# ---------------------------------------------------------------------------

_FIGHTERS: List[str] = [
    "Iron Vex",
    "The Revenant",
    "Neon Fist",
    "Kira Volkov",
    "Slag",
]

# ---------------------------------------------------------------------------
# Ambient mood pool
# ---------------------------------------------------------------------------

_AMBIENT_MOODS: List[str] = [
    "bustling",
    "quiet",
    "tense",
    "festive",
    "dangerous",
    "intimate",
]

# ---------------------------------------------------------------------------
# Scheduled-task configuration
# ---------------------------------------------------------------------------

#: Maps task key → real-time interval in seconds.
_TASK_INTERVALS: Dict[str, float] = {
    "npc_action": 60.0,
    "scene_ambient": 120.0,
    "faction_shift": 180.0,
    "hacker_event": 600.0,
    "arena_queue": 1200.0,
    "world_event": 2400.0,
    "economy_tick": 90.0,
}

_RING_BUFFER_MAX: int = 200


# ---------------------------------------------------------------------------
# WorldSim
# ---------------------------------------------------------------------------


def _game_time_string(world_time: WorldTime) -> str:
    """Format a :class:`WorldTime` snapshot as a compact display string.

    Args:
        world_time: Current game-time snapshot.

    Returns:
        String like ``"Day 3 14:30"``.
    """
    return f"Day {world_time.game_day} {world_time.game_hour:02d}:00"


class WorldSim:
    """Background living-world simulation daemon.

    Fires scripted events on a game-clock schedule so that the world keeps
    ticking even when the player is not actively in a scene.  All events are
    stored in a ring buffer, persisted to Nexus, and broadcast over the
    :class:`~engine.events.event_bus.EventBus`.

    Not intended for direct instantiation — use :func:`get_world_sim` (or
    :func:`start_world_sim`) to obtain the process-wide singleton.

    Args:
        nexus_client: Optional Nexus client override (useful for testing).
        world_state: Optional :class:`~engine.world.world_state.WorldState`
            override (useful for testing).
        event_bus: Optional :class:`~engine.events.event_bus.EventBus`
            override (useful for testing).
    """

    def __init__(
        self,
        nexus_client=None,
        world_state=None,
        event_bus=None,
    ) -> None:
        self._nexus = nexus_client
        self._world_state = world_state
        self._bus = event_bus

        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock: threading.Lock = threading.Lock()

        # Real-time last-run epoch per task key.
        self._last_ticks: Dict[str, float] = {k: 0.0 for k in _TASK_INTERVALS}

        # In-memory ring buffer — newest item at the end.
        self._event_log: List[SimEvent] = []

    # ------------------------------------------------------------------
    # Lazy dependency resolution
    # ------------------------------------------------------------------

    def _get_nexus(self):
        """Return the Nexus client, resolving lazily if not injected."""
        if self._nexus is None:
            try:
                self._nexus = get_nexus_client()
            except Exception as exc:
                logger.debug("Nexus client unavailable: %s", exc)
        return self._nexus

    def _get_world_state(self):
        """Return the WorldState, resolving lazily if not injected."""
        if self._world_state is None:
            self._world_state = get_world_state()
        return self._world_state

    def _get_bus(self):
        """Return the EventBus, resolving lazily if not injected."""
        if self._bus is None:
            self._bus = get_event_bus()
        return self._bus

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background simulation daemon thread.

        Safe to call multiple times; subsequent calls while running are
        no-ops.
        """
        with self._lock:
            if self._running:
                logger.debug("WorldSim already running; ignoring start().")
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name="WorldSim-daemon",
                daemon=True,
            )
            self._thread.start()
        logger.info("WorldSim daemon started.")

    def stop(self) -> None:
        """Signal the daemon to stop and wait up to 2 seconds for it.

        Safe to call if the sim has not been started or has already stopped.
        """
        with self._lock:
            self._running = False
            thread = self._thread

        if thread is not None:
            thread.join(timeout=2.0)
            logger.info("WorldSim daemon stopped.")

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main scheduling loop executed inside the daemon thread.

        Checks each task against its real-time interval every 10 seconds
        (= 10 game minutes at the 1 min/hour scale).
        """
        while self._running:
            now: float = time.time()
            for task_key, interval in _TASK_INTERVALS.items():
                if now - self._last_ticks[task_key] >= interval:
                    self._last_ticks[task_key] = now
                    try:
                        self._dispatch_task(task_key)
                    except Exception as exc:
                        logger.warning(
                            "WorldSim task '%s' raised: %s", task_key, exc
                        )
            time.sleep(10)

    def _dispatch_task(self, task_key: str) -> None:
        """Invoke the handler for *task_key*.

        Args:
            task_key: One of the keys in :data:`_TASK_INTERVALS`.
        """
        handler_map = {
            "npc_action": self._fire_npc_action,
            "scene_ambient": self._fire_scene_ambient,
            "faction_shift": self._fire_faction_shift,
            "hacker_event": self._fire_hacker_event,
            "arena_queue": self._fire_arena_queue,
            "world_event": self._fire_world_event,
            "economy_tick": self._fire_economy_tick,
        }
        handler = handler_map.get(task_key)
        if handler:
            result = handler()
            if result is not None:
                logger.debug("WorldSim fired %s: %s", task_key, result.title)

    # ------------------------------------------------------------------
    # Task handlers
    # ------------------------------------------------------------------

    def _current_game_time_str(self) -> str:
        """Return the current game time as a display string.

        Returns:
            E.g. ``"Day 3 14:00"``.
        """
        try:
            ws = self._get_world_state()
            return _game_time_string(ws.get_time())
        except Exception as e:
            logger.debug("[WorldSim] Game time unavailable (operation=current_time): %s", e)
            return "Day 0 00:00"

    def _fire_npc_action(self) -> SimEvent:
        """Pick a random NPC action template and broadcast it.

        Returns:
            The generated :class:`SimEvent`.
        """
        template = random.choice(NPC_ACTIONS_RICH)
        event = SimEvent(
            id=str(uuid.uuid4()),
            event_type=SimEventType.NPC_ACTION,
            title=template["title"],
            description=template["desc"],
            scene=template["scene"],
            actor=template.get("actor", "unknown"),
            intensity=round(template.get("intensity", random.uniform(0.5, 1.5)), 2),
            payload={
                "economy_impact": template.get("economy_impact", 0),
                "rep_impact": template.get("rep_impact", 0),
                "heat_impact": template.get("heat_impact", 0),
                "affected_scenes": template.get("affected_scenes", [template["scene"]]),
                "narrative": template.get("narrative", ""),
                "faction": template.get("faction", ""),
            },
            created_at=self._current_game_time_str(),
        )
        self._log_event(event)
        # Apply player state impacts (best-effort)
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            eco = template.get("economy_impact", 0)
            if eco > 0:
                ps.earn_credits(eco, f"npc_{template['title']}")
            elif eco < 0:
                ps.spend_credits(-eco, f"npc_{template['title']}")
            heat = template.get("heat_impact", 0)
            if heat:
                ps.adjust_heat(heat)
            rep = template.get("rep_impact", 0)
            if rep:
                ps.update_reputation(rep, f"npc_{template['title']}")
        except Exception as exc:
            logger.debug("PlayerState update skipped for npc_action: %s", exc)
        try:
            self._get_bus().publish(
                EventTypes.NEONCITY_FACTION_SHIFT
                if event.scene == "neoncity"
                else "world.npc_action",
                {
                    "actor": event.actor,
                    "title": event.title,
                    "scene": event.scene,
                    "sim_event_id": event.id,
                    "economy_impact": template.get("economy_impact", 0),
                    "heat_impact": template.get("heat_impact", 0),
                },
                scene=event.scene,
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for npc_action: %s", exc)
        return event

    def _fire_faction_shift(self) -> SimEvent:
        """Generate a random faction action and update WorldState tension.

        Returns:
            The generated :class:`SimEvent`.
        """
        faction = random.choice(FACTION_NAMES)
        action = random.choice(FACTION_ACTIONS)

        # Dyadic actions need a second faction.
        if action in ("declares conflict with", "forms alliance with"):
            others = [f for f in FACTION_NAMES if f != faction]
            target = random.choice(others)
            description = f"{faction} {action} {target}."
            title = f"{faction} {action.split()[0].capitalize()} {target}"
        else:
            description = f"{faction} {action}."
            title = f"{faction}: {action.capitalize()}"

        # Update WorldState faction tension.
        delta = random.choice([-5, 5])
        try:
            ws = self._get_world_state()
            summary = ws.get_world_summary()
            current = summary.get("faction_tension", {}).get(faction, 50)
            new_val = max(0, min(100, current + delta))
            ws.add_event(
                WorldEvent(
                    id=str(uuid.uuid4()),
                    name=title,
                    description=description,
                    scene="neoncity",
                    event_type="faction_shift",
                    started_at=time.time(),
                    expires_at=time.time() + 3600,
                    active=True,
                    payload={"faction": faction, "tension": new_val},
                )
            )
        except Exception as exc:
            logger.debug("Could not update WorldState for faction_shift: %s", exc)

        event = SimEvent(
            id=str(uuid.uuid4()),
            event_type=SimEventType.FACTION_SHIFT,
            title=title,
            description=description,
            scene="neoncity",
            actor=faction,
            intensity=round(abs(delta) / 5.0, 2),
            payload={"faction": faction, "action": action, "tension_delta": delta},
            created_at=self._current_game_time_str(),
        )
        self._log_event(event)
        try:
            self._get_bus().publish(
                EventTypes.NEONCITY_FACTION_SHIFT,
                {
                    "faction": faction,
                    "action": action,
                    "description": description,
                    "sim_event_id": event.id,
                },
                scene="neoncity",
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for faction_shift: %s", exc)
        return event

    def _fire_scene_ambient(self) -> SimEvent:
        """Shift the ambient mood of a random scene.

        Returns:
            The generated :class:`SimEvent`.
        """
        all_scenes = list({t["scene"] for t in NPC_ACTIONS_RICH})
        scene = random.choice(all_scenes)
        mood = random.choice(_AMBIENT_MOODS)

        event = SimEvent(
            id=str(uuid.uuid4()),
            event_type=SimEventType.SCENE_AMBIENT,
            title=f"{scene.capitalize()} feels {mood}",
            description=(
                f"The atmosphere in {scene} has shifted to {mood}. "
                "Patrons and locals adjust their behaviour accordingly."
            ),
            scene=scene,
            intensity=round(random.uniform(0.3, 1.0), 2),
            payload={"mood": mood},
            created_at=self._current_game_time_str(),
        )
        self._log_event(event)
        try:
            self._get_bus().publish(
                "world.scene_ambient_shift",
                {"scene": scene, "mood": mood, "sim_event_id": event.id},
                scene=scene,
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for scene_ambient: %s", exc)
        return event

    def _fire_hacker_event(self) -> Optional[SimEvent]:
        """Fire a 0xGH0ST message with 30 % probability.

        Returns:
            A :class:`SimEvent` if triggered, otherwise ``None``.
        """
        if random.random() > 0.30:
            return None

        ghost_entry = random.choice(GHOST_MESSAGES_RICH)
        message = ghost_entry["message"]
        intensity = ghost_entry.get("intensity", 2.0)
        heat_impact = ghost_entry.get("heat_impact", 0)
        timestamp = self._current_game_time_str()
        nexus_title = f"ghost_msg:{timestamp.replace(' ', '_')}"

        try:
            nexus = self._get_nexus()
            if nexus is not None:
                nexus.add_entry(
                    title=nexus_title,
                    content=message,
                    content_type="history",
                    category="phone_messages",
                    tags=["ghost", "hacker", "phone"],
                )
        except Exception as exc:
            logger.warning("Nexus store failed for hacker_event: %s", exc)

        # Apply heat impact to player state
        if heat_impact:
            try:
                from engine.world.player_state import get_player_state
                get_player_state().adjust_heat(heat_impact, reason="ghost_message")
            except Exception as e:
                logger.debug("[WorldSim] Heat adjustment failed (operation=hacker_event): %s", e)

        event = SimEvent(
            id=str(uuid.uuid4()),
            event_type=SimEventType.HACKER_MESSAGE,
            title="Message from 0xGH0ST",
            description=message,
            scene="phone",
            actor="0xGH0ST",
            intensity=intensity,
            payload={"message": message, "heat_impact": heat_impact},
            created_at=timestamp,
        )
        self._log_event(event)
        try:
            self._get_bus().publish(
                EventTypes.PHONE_HACKER_MESSAGE,
                {"message": message, "sim_event_id": event.id},
                scene="phone",
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for hacker_event: %s", exc)
        return event

    def _fire_arena_queue(self) -> SimEvent:
        """Queue a new arena fight between two randomly chosen fighters.

        Returns:
            The generated :class:`SimEvent`.
        """
        fighters = random.sample(_FIGHTERS, k=min(2, len(_FIGHTERS)))
        fighter_a, fighter_b = fighters[0], fighters[1] if len(fighters) > 1 else "Unknown"
        match_id = str(uuid.uuid4())[:8]
        title = f"{fighter_a} vs {fighter_b}"
        description = (
            f"A new arena match has been queued: {fighter_a} faces {fighter_b}. "
            "Bookmakers are already taking bets."
        )

        try:
            nexus = self._get_nexus()
            if nexus is not None:
                nexus.add_entry(
                    title=f"match:{match_id}",
                    content=description,
                    content_type="history",
                    category="arena_queue",
                    tags=["arena", "match", fighter_a, fighter_b],
                )
        except Exception as exc:
            logger.warning("Nexus store failed for arena_queue: %s", exc)

        event = SimEvent(
            id=str(uuid.uuid4()),
            event_type=SimEventType.ARENA_MATCH,
            title=title,
            description=description,
            scene="arena",
            intensity=1.5,
            payload={"match_id": match_id, "fighter_a": fighter_a, "fighter_b": fighter_b},
            created_at=self._current_game_time_str(),
        )
        self._log_event(event)
        try:
            self._get_bus().publish(
                "arena.match_queued",
                {
                    "match_id": match_id,
                    "fighter_a": fighter_a,
                    "fighter_b": fighter_b,
                    "sim_event_id": event.id,
                },
                scene="arena",
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for arena_queue: %s", exc)
        return event

    def _fire_world_event(self) -> SimEvent:
        """Fire a major world event and register it with WorldState.

        Returns:
            The generated :class:`SimEvent`.
        """
        template = random.choice(WORLD_EVENTS_RICH)
        event_id = str(uuid.uuid4())

        # Register in WorldState so scenes can query it.
        try:
            ws = self._get_world_state()
            ws.add_event(
                WorldEvent(
                    id=event_id,
                    name=template["title"],
                    description=template["desc"],
                    scene=template["scene"],
                    event_type=template["event_type"],
                    started_at=time.time(),
                    expires_at=time.time() + 7200,  # 2 real hours = ~2 in-game days
                    active=True,
                    payload={"sim_event_id": event_id},
                )
            )
        except Exception as exc:
            logger.warning("WorldState.add_event failed for world_event: %s", exc)

        event = SimEvent(
            id=event_id,
            event_type=SimEventType.WORLD_EVENT,
            title=template["title"],
            description=template["desc"],
            scene=template["scene"],
            intensity=template.get("intensity", 3.0),
            payload={
                "world_event_type": template["event_type"],
                "economy_impact": template.get("economy_impact", 0),
                "rep_impact": template.get("rep_impact", 0),
                "heat_impact": template.get("heat_impact", 0),
                "affected_scenes": template.get("affected_scenes", [template["scene"]]),
                "faction": template.get("faction", ""),
                "narrative": template.get("narrative", ""),
            },
            created_at=self._current_game_time_str(),
        )
        self._log_event(event)
        # Apply player state impacts (best-effort)
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            eco = template.get("economy_impact", 0)
            if eco > 0:
                ps.earn_credits(eco, f"world_{template['title']}")
            elif eco < 0:
                ps.spend_credits(-eco, f"world_{template['title']}")
            heat = template.get("heat_impact", 0)
            if heat:
                ps.adjust_heat(heat)
            rep = template.get("rep_impact", 0)
            if rep:
                ps.update_reputation(rep, f"world_{template['title']}")
        except Exception as exc:
            logger.debug("PlayerState update skipped for world_event: %s", exc)
        try:
            self._get_bus().publish(
                "world.major_event",
                {
                    "title": template["title"],
                    "scene": template["scene"],
                    "event_type": template["event_type"],
                    "sim_event_id": event_id,
                },
                scene=template["scene"],
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for world_event: %s", exc)
        return event

    def _fire_economy_tick(self) -> Optional[SimEvent]:
        """Apply a passive economy tick: market shifts affect player credits and heat.

        Picks a random :data:`ECONOMY_EVENTS` template, applies player state
        impacts, and publishes ``world.economy_tick`` on the event bus.

        Returns:
            A :class:`SimEvent` describing the tick, or ``None`` if skipped
            (40 % chance per tick to keep it varied).
        """
        if random.random() < 0.40:
            return None

        template = random.choice(ECONOMY_EVENTS)
        event_id = str(uuid.uuid4())
        event = SimEvent(
            id=event_id,
            event_type=SimEventType.ECONOMY_TICK,
            title=template["title"],
            description=template["desc"],
            scene=template.get("scene", "global"),
            intensity=template.get("intensity", 1.0),
            payload={
                "economy_impact": template.get("economy_impact", 0),
                "heat_impact": template.get("heat_impact", 0),
                "event_type": template.get("event_type", "economy"),
            },
            created_at=self._current_game_time_str(),
        )
        self._log_event(event)
        # Apply player state (best-effort)
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            ps.on_economy_tick(template.get("event_type", "market_shift"))
        except Exception as exc:
            logger.debug("PlayerState economy_tick skipped: %s", exc)
        # Publish on event bus so scenes can react
        try:
            self._get_bus().publish(
                "world.economy_tick",
                {
                    "title": template["title"],
                    "economy_impact": template.get("economy_impact", 0),
                    "event_type": template.get("event_type", "economy"),
                    "sim_event_id": event_id,
                },
            )
        except Exception as exc:
            logger.warning("EventBus publish failed for economy_tick: %s", exc)
        return event

    # ------------------------------------------------------------------
    # Event log management
    # ------------------------------------------------------------------

    def _log_event(self, event: SimEvent) -> None:
        """Append *event* to the ring buffer and persist to Nexus.

        Drops the oldest entry when the buffer exceeds
        :data:`_RING_BUFFER_MAX`.

        Args:
            event: :class:`SimEvent` to log.
        """
        with self._lock:
            self._event_log.append(event)
            if len(self._event_log) > _RING_BUFFER_MAX:
                self._event_log.pop(0)

        try:
            nexus = self._get_nexus()
            if nexus is not None:
                nexus.add_entry(
                    title=f"sim:{event.id}",
                    content=f"{event.title} — {event.description}",
                    content_type="history",
                    category="world_sim",
                    tags=[event.event_type.value, event.scene or "global"],
                )
        except Exception as exc:
            logger.warning("Nexus log failed for event %s: %s", event.id, exc)

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_digest(self, scene: str, since_game_time: str = "") -> List[SimEvent]:
        """Return unseen events for *scene* and mark them as seen.

        Returns all :class:`SimEvent` objects whose ``scene`` matches
        *scene* (or is ``""``) and that have not yet been seen by the
        player.  Results are ordered newest-first.  Each returned event is
        immediately marked ``seen_by_player = True``.

        Args:
            scene: Scene identifier to filter by.
            since_game_time: Reserved for future use — currently unused.

        Returns:
            List of unseen :class:`SimEvent` objects, newest first.
        """
        with self._lock:
            unseen = [
                ev
                for ev in self._event_log
                if not ev.seen_by_player and (ev.scene == scene or ev.scene == "")
            ]
            for ev in unseen:
                ev.seen_by_player = True

        return list(reversed(unseen))

    def get_all_events(self, limit: int = 50) -> List[SimEvent]:
        """Return the most recent events from the ring buffer.

        Args:
            limit: Maximum number of events to return (default 50).

        Returns:
            List of :class:`SimEvent` objects, newest first.
        """
        with self._lock:
            snapshot = list(self._event_log)
        return list(reversed(snapshot))[:limit]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_WORLD_SIM: Optional[WorldSim] = None
_SIM_LOCK: threading.Lock = threading.Lock()


def get_world_sim() -> WorldSim:
    """Return the process-wide :class:`WorldSim` singleton.

    Thread-safe double-checked locking ensures the instance is created at
    most once even under concurrent calls.

    Returns:
        The singleton :class:`WorldSim` instance.
    """
    global _WORLD_SIM
    if _WORLD_SIM is None:
        with _SIM_LOCK:
            if _WORLD_SIM is None:
                _WORLD_SIM = WorldSim()
    return _WORLD_SIM


def get_event_log(limit: int = 50) -> List[SimEvent]:
    """Return recent world events from the singleton WorldSim.

    Convenience wrapper around :meth:`WorldSim.get_all_events`.

    Args:
        limit: Maximum number of events to return (default 50).

    Returns:
        List of :class:`SimEvent` objects, newest first.
    """
    return get_world_sim().get_all_events(limit=limit)


def start_world_sim() -> WorldSim:
    """Return the singleton :class:`WorldSim` and start it if not running.

    Convenience helper for engine boot code.

    Returns:
        The started singleton :class:`WorldSim` instance.
    """
    sim = get_world_sim()
    sim.start()
    return sim
