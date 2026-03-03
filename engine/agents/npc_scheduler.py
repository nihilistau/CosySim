"""NPCScheduler — async tick loop driving NPC world activity.

Every tick_interval seconds, selects idle NPCs and generates a short
autonomous activity via LMStudio (routed to 'small' model profile).
Results update NPCStateRegistry and emit socket events for scene UIs.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Fallback activity pool ────

ACTIVITY_POOL: List[str] = [
    "tending to business in the area",
    "having a quiet moment to themselves",
    "browsing nearby goods",
    "chatting with someone",
    "lost in thought",
]

# ──── NPCScheduler ────


class NPCScheduler:
    """Drives autonomous NPC activity via a periodic tick loop.

    On each :meth:`tick`, up to ``max_npcs_per_tick`` idle NPCs are selected
    from WorldSim (or from a config fallback list).  A short prompt is sent to
    LMStudio's *small* model profile; the reply updates :class:`NPCStateRegistry`
    and emits a ``npc_activity`` socket event so scene UIs stay current.

    Graceful degradation:
        - WorldSim unavailable → uses ``npc_scheduler.fallback_npcs`` config list.
        - LMStudio unavailable → picks randomly from :data:`ACTIVITY_POOL`.
        - No exception ever propagates out of :meth:`tick`.
    """

    def __init__(self, tick_interval: float = 60.0) -> None:
        """Initialise the scheduler.

        Args:
            tick_interval: Seconds between autonomous ticks.
        """
        from engine.config import get_config
        cfg = get_config()
        self._tick_interval: float = float(
            cfg.get("npc_scheduler.tick_interval", tick_interval)
        )
        self._max_per_tick: int = int(cfg.get("npc_scheduler.max_npcs_per_tick", 3))
        self._fallback_npcs: List[str] = list(
            cfg.get("npc_scheduler.fallback_npcs", ["lola", "viktor", "aria"])
        )
        self._activity_pool: List[str] = list(
            cfg.get("npc_scheduler.activity_pool", ACTIVITY_POOL)
        )
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._thread: Optional[threading.Thread] = None
        self._last_tick_at: Optional[float] = None
        self._npcs_active: int = 0

    # ──── Lifecycle ────

    def start(self) -> None:
        """Start the background tick loop in a daemon thread."""
        if self._running:
            logger.warning("NPCScheduler already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="NPCScheduler",
        )
        self._thread.start()
        logger.info("NPCScheduler started (interval=%.0fs)", self._tick_interval)

    def stop(self) -> None:
        """Stop the background tick loop."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("NPCScheduler stopped")

    def _run_loop(self) -> None:
        """Thread target: sleep then tick repeatedly."""
        while self._running:
            waited = 0.0
            while waited < self._tick_interval and self._running:
                time.sleep(min(1.0, self._tick_interval - waited))
                waited += 1.0
            if self._running:
                try:
                    self.tick()
                except Exception as exc:
                    logger.error("NPCScheduler loop error: %s", exc)

    # ──── Tick ────

    def tick(self) -> None:
        """Execute one NPC activity cycle.

        Steps:
        1. Fetch idle NPCs from WorldSim (fallback to config list).
        2. Pick up to ``max_npcs_per_tick`` candidates.
        3. For each: generate activity via LMStudio, update registry, emit socket event.

        Never raises — all errors are caught and logged.
        """
        self._last_tick_at = time.time()
        candidates = self._get_idle_npcs()
        if not candidates:
            logger.debug("NPCScheduler tick: no idle NPCs found")
            return

        active = 0
        for npc in candidates[: self._max_per_tick]:
            try:
                self._process_npc(npc)
                active += 1
            except Exception as exc:
                logger.error("NPCScheduler: error processing NPC %r: %s", npc.get("id", "?"), exc)
        self._npcs_active = active
        logger.debug("NPCScheduler tick: processed %d NPC(s)", active)
        self._emit_activity_update()

    def _get_idle_npcs(self) -> List[Dict[str, Any]]:
        """Return a list of NPC info dicts for currently idle NPCs.

        Tries WorldSim first; falls back to config list.
        Each dict must have at least ``id``, ``name``, and ``location`` keys.
        """
        try:
            from engine.world.world_sim import get_world_sim
            sim = get_world_sim()
            npcs = []
            for char_id in self._fallback_npcs:
                npcs.append({"id": char_id, "name": char_id.capitalize(), "location": "unknown"})
            # Attempt to enrich from WorldSim NPC actions
            events = sim.get_digest("", limit=20)
            seen: set = set()
            enriched: List[Dict] = []
            for evt in events:
                actor = getattr(evt, "actor", "") or evt.get("actor", "") if not hasattr(evt, "actor") else evt.actor
                scene = getattr(evt, "scene", "") or ""
                if actor and actor not in seen:
                    seen.add(actor)
                    enriched.append({"id": actor, "name": actor.replace("_", " ").capitalize(), "location": scene or "unknown"})
            if enriched:
                return enriched
            return npcs
        except Exception as exc:
            logger.debug("NPCScheduler: WorldSim unavailable (%s), using fallback list", exc)
            return [
                {"id": cid, "name": cid.capitalize(), "location": "unknown"}
                for cid in self._fallback_npcs
            ]

    def _process_npc(self, npc: Dict[str, Any]) -> None:
        """Generate activity for a single NPC and update state + socket."""
        char_id: str = npc.get("id", "unknown")
        name: str = npc.get("name", char_id.capitalize())
        location: str = npc.get("location", "unknown")

        activity = self._generate_activity(name, location)
        mood = self._infer_mood(activity)

        from engine.world.npc_state import get_npc_state_registry
        registry = get_npc_state_registry()
        registry.update(
            char_id,
            location=location,
            activity=activity,
            last_action=activity,
            last_action_time=time.time(),
            mood=mood,
            is_busy=True,
        )

        self._emit_socket_event(char_id, activity, location, mood)
        self._track_npc_in_city_map(char_id, location)

    def _track_npc_in_city_map(self, char_id: str, location: Optional[str]) -> None:
        """Update CityMap NPC location and emit npc_location socket event."""
        if not location:
            return
        try:
            from engine.world.city_map import get_city_map
            cm = get_city_map()
            old_location = cm.get_npc_location(char_id)
            cm.set_npc_location(char_id, location)
            if old_location != location:
                payload: Dict[str, str] = {
                    "character_id": char_id,
                    "location": location,
                    "previous_location": old_location or "",
                }
                try:
                    from engine.mcp import get_framework
                    fw = get_framework()
                    fw.emit("npc_location", payload)
                except Exception as exc:
                    logger.debug("NPCScheduler: could not emit npc_location: %s", exc)
        except Exception as exc:
            logger.debug("NPCScheduler: CityMap tracking failed: %s", exc)

    def _generate_activity(self, name: str, location: str) -> str:
        """Generate a one-sentence activity string via LMStudio.

        Falls back to :data:`ACTIVITY_POOL` if LMStudio is unavailable.

        Args:
            name: NPC display name.
            location: NPC's current scene/location.

        Returns:
            A short activity description sentence.
        """
        prompt = (
            f"You are {name}. You are currently in {location}. "
            "What are you doing? Reply in one sentence."
        )
        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
            messages = [{"role": "user", "content": prompt}]
            response = client.chat(messages, model_profile="small", store=False)
            text = response.content.strip()
            if text:
                # Strip leading "I am " or similar for readability
                return text
            return random.choice(self._activity_pool)
        except Exception as exc:
            logger.debug("NPCScheduler: LMStudio unavailable (%s), using fallback", exc)
            return random.choice(self._activity_pool)

    def _infer_mood(self, activity: str) -> str:
        """Derive a simple mood string from activity text.

        Args:
            activity: The activity description.

        Returns:
            One of: "neutral", "happy", "tense", "curious", "tired".
        """
        lowered = activity.lower()
        if any(w in lowered for w in ("laugh", "smile", "enjoy", "celebrat", "happy", "delight")):
            return "happy"
        if any(w in lowered for w in ("worry", "nervous", "tense", "anxious", "watch", "guard")):
            return "tense"
        if any(w in lowered for w in ("wonder", "curious", "explor", "search", "look")):
            return "curious"
        if any(w in lowered for w in ("tired", "rest", "sleep", "weary", "exhaust")):
            return "tired"
        return "neutral"

    def _emit_socket_event(self, character_id: str, activity: str, location: str, mood: str) -> None:
        """Broadcast npc_activity to connected Socket.IO clients (best-effort)."""
        payload: Dict[str, str] = {
            "character_id": character_id,
            "activity": activity,
            "location": location,
            "mood": mood,
        }
        try:
            from engine.mcp import get_framework
            fw = get_framework()
            fw.emit("npc_activity", payload)
        except Exception as exc:
            logger.debug("NPCScheduler: could not emit socket event: %s", exc)

    def _emit_activity_update(self) -> None:
        """Broadcast npc_activity_update with all NPC states (best-effort)."""
        try:
            from engine.world.npc_state import get_npc_state_registry
            registry = get_npc_state_registry()
            npcs = [
                {
                    "id": s.character_id,
                    "activity": s.activity,
                    "scene": s.location,
                }
                for s in registry.get_all()
            ]
            payload: Dict[str, Any] = {"npcs": npcs}
            try:
                from engine.mcp import get_framework
                fw = get_framework()
                fw.emit("npc_activity_update", payload)
            except Exception as exc:
                logger.debug("NPCScheduler: could not emit npc_activity_update: %s", exc)
        except Exception as exc:
            logger.debug("NPCScheduler: _emit_activity_update error: %s", exc)

    # ──── Status ────

    def get_status(self) -> Dict[str, Any]:
        """Return a status snapshot for monitoring.

        Returns:
            Dict with keys: ``running``, ``tick_interval``, ``last_tick_at``,
            ``npcs_active``.
        """
        return {
            "running": self._running,
            "tick_interval": self._tick_interval,
            "last_tick_at": self._last_tick_at,
            "npcs_active": self._npcs_active,
        }


# ──── Singleton ────

_scheduler: Optional[NPCScheduler] = None
_scheduler_lock = threading.Lock()


def get_npc_scheduler() -> NPCScheduler:
    """Return the singleton :class:`NPCScheduler`.

    Returns:
        The global scheduler instance.
    """
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = NPCScheduler()
    return _scheduler
