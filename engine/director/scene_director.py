"""CosySim AI Scene Director.

Periodically analyses scene state, selects a narrative beat type, resolves
an instruction from Nexus (or a built-in template), publishes the beat on
the EventBus, and persists beat history.

Typical use::

    director = get_scene_director()
    beat = director.tick("penthouse", scene_state)
    if beat:
        inject_into_prompt(beat.instruction)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — kept at call-site to avoid circular deps at module load time
# ---------------------------------------------------------------------------

def _nexus():
    from engine.nexus.client import get_nexus_client  # noqa: PLC0415
    return get_nexus_client()


def _bus():
    from engine.events.event_bus import get_event_bus  # noqa: PLC0415
    return get_event_bus()


def _event_types():
    from engine.events.event_bus import EventTypes  # noqa: PLC0415
    return EventTypes


# ---------------------------------------------------------------------------
# BeatType
# ---------------------------------------------------------------------------

class BeatType(str, Enum):
    """Narrative beat categories recognised by the Scene Director.

    Attributes:
        STORY_BEAT: Advances the main narrative thread.
        COMPLICATION: Throws a wrench into the current scene flow.
        REWARD: Positive event — pleasure, credits, unlocked content.
        REVELATION: Exposes hidden lore, character backstory, or a secret.
        ESCALATION: Adult/intensity escalation cue for the active scene.
        COOL_DOWN: De-escalation signal after an intense moment.
        CHARACTER_ACTION: NPC performs an unprompted action.
        WORLD_EVENT: City- or scene-wide event fires independently.
    """

    STORY_BEAT = "story_beat"
    COMPLICATION = "complication"
    REWARD = "reward"
    REVELATION = "revelation"
    ESCALATION = "escalation"
    COOL_DOWN = "cool_down"
    CHARACTER_ACTION = "character_action"
    WORLD_EVENT = "world_event"


# ---------------------------------------------------------------------------
# Beat instruction templates (fallback when Nexus has no matching content)
# ---------------------------------------------------------------------------

BEAT_TEMPLATES: Dict[BeatType, str] = {
    BeatType.STORY_BEAT: (
        "The scene in {scene} calls for a natural story progression. "
        "Introduce a new narrative thread or advance an existing subplot."
    ),
    BeatType.COMPLICATION: (
        "Introduce a complication in {scene}: an unexpected interruption, "
        "a rival's interference, or a sudden revelation that complicates things."
    ),
    BeatType.REWARD: (
        "A reward opportunity opens in {scene}. "
        "The player may earn credits, unlock content, or receive a pleasurable surprise."
    ),
    BeatType.REVELATION: (
        "It is time for a revelation in {scene}. "
        "Unveil hidden lore, a character's backstory, or a secret that reframes recent events."
    ),
    BeatType.ESCALATION: (
        "The tension in {scene} is rising. "
        "The character should escalate the intimacy or emotional intensity of the moment."
    ),
    BeatType.COOL_DOWN: (
        "After the intensity of the last beat in {scene}, "
        "guide the scene toward a natural pause — tender, quiet, or reflective."
    ),
    BeatType.CHARACTER_ACTION: (
        "An NPC in {scene} takes an unprompted action that shifts the dynamic. "
        "Make it feel organic and character-driven."
    ),
    BeatType.WORLD_EVENT: (
        "A city- or scene-wide event erupts in {scene}. "
        "The outside world intrudes — news, chaos, weather, or faction activity."
    ),
}

# Map nudge direction strings → BeatType
_NUDGE_MAP: Dict[str, BeatType] = {
    "escalate": BeatType.ESCALATION,
    "cool_down": BeatType.COOL_DOWN,
    "complicate": BeatType.COMPLICATION,
    "reward": BeatType.REWARD,
    "reveal": BeatType.REVELATION,
    "story": BeatType.STORY_BEAT,
    "character": BeatType.CHARACTER_ACTION,
    "world": BeatType.WORLD_EVENT,
}

# Minimum seconds between auto-fired beats for a given scene
_BEAT_COOLDOWN_SECONDS: float = 60.0

# Turn counts that trigger REVELATION beats
_MILESTONE_TURNS = {10, 25, 50, 100, 200}

# ---------------------------------------------------------------------------
# Per-scene beat configuration
# ---------------------------------------------------------------------------

#: Per-scene overrides for beat selection.  Each entry may contain:
#:   ``preferred_beats``      – ordered list of :class:`BeatType` biases
#:   ``avoid_beats``          – beat types that should never be auto-selected
#:   ``escalation_threshold`` – arousal level at which ESCALATION fires (default 80)
SCENE_BEAT_CONFIGS: Dict[str, Dict] = {
    "penthouse": {
        "preferred_beats": [BeatType.ESCALATION, BeatType.COOL_DOWN, BeatType.REWARD],
        "avoid_beats": [BeatType.WORLD_EVENT],
        "escalation_threshold": 70,
    },
    "arena": {
        "preferred_beats": [BeatType.WORLD_EVENT, BeatType.CHARACTER_ACTION, BeatType.ESCALATION],
        "avoid_beats": [],
        "escalation_threshold": 85,
    },
    "casino": {
        "preferred_beats": [BeatType.REWARD, BeatType.COMPLICATION, BeatType.CHARACTER_ACTION],
        "avoid_beats": [],
        "escalation_threshold": 90,
    },
    "lounge": {
        "preferred_beats": [BeatType.STORY_BEAT, BeatType.REVELATION, BeatType.CHARACTER_ACTION],
        "avoid_beats": [],
        "escalation_threshold": 90,
    },
    "neoncity": {
        "preferred_beats": [BeatType.WORLD_EVENT, BeatType.COMPLICATION, BeatType.STORY_BEAT],
        "avoid_beats": [],
        "escalation_threshold": 90,
    },
    "heist": {
        "preferred_beats": [BeatType.COMPLICATION, BeatType.CHARACTER_ACTION, BeatType.ESCALATION],
        "avoid_beats": [],
        "escalation_threshold": 80,
    },
    "tavern": {
        "preferred_beats": [BeatType.STORY_BEAT, BeatType.CHARACTER_ACTION, BeatType.REVELATION],
        "avoid_beats": [],
        "escalation_threshold": 85,
    },
}


# ---------------------------------------------------------------------------
# DirectorBeat
# ---------------------------------------------------------------------------

@dataclass
class DirectorBeat:
    """A single narrative directive produced by the Scene Director.

    Attributes:
        id: Unique identifier (UUID4 string).
        scene: Name of the scene this beat targets.
        beat_type: Category of the beat (see :class:`BeatType`).
        instruction: Human-readable directive injected into the agent prompt
            or delivered via Socket.IO notification.
        urgency: 0.0–1.0. Values ≥ 1.0 should be fired immediately.
        content_intensity: 0–3 content-rating level of this beat.
        context: Arbitrary extra payload (emotion levels, economy snapshot, …).
        timestamp: Unix epoch float at beat creation time.
        fired: Whether this beat has been consumed by the pipeline.
    """

    id: str
    scene: str
    beat_type: BeatType
    instruction: str
    urgency: float
    content_intensity: int
    context: Dict
    timestamp: float
    fired: bool = False

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict:
        """Return a JSON-serialisable representation of this beat.

        Returns:
            Dict with all fields; ``beat_type`` is the string value of the
            enum so the result is immediately JSON-serialisable.
        """
        raw = asdict(self)
        raw["beat_type"] = self.beat_type.value  # enum → str
        return raw


# ---------------------------------------------------------------------------
# SceneDirector
# ---------------------------------------------------------------------------

class SceneDirector:
    """AI-driven narrative director for CosySim scenes.

    The director is called periodically (every scene tick or on demand) and
    decides whether to fire a :class:`DirectorBeat`.  Beats are dispatched on
    the :class:`~engine.events.event_bus.EventBus` and optionally persisted to
    Nexus for lore continuity.

    Args:
        nexus_client: Optional pre-built Nexus client.  If ``None`` the
            module-level :func:`_nexus` factory is used on demand.
    """

    def __init__(self, nexus_client=None) -> None:
        self._nexus_client = nexus_client

        # scene_name → unix timestamp of the last beat fired
        self._last_beat_time: Dict[str, float] = {}

        # scene_name → list of DirectorBeat (all, including fired)
        self._beat_history: Dict[str, List[DirectorBeat]] = {}

        # beat_id → DirectorBeat (fast lookup)
        self._beats_by_id: Dict[str, DirectorBeat] = {}

        logger.info("SceneDirector initialised.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _nexus(self):
        """Lazy accessor for the Nexus client."""
        if self._nexus_client is not None:
            return self._nexus_client
        try:
            return _nexus()
        except Exception:
            return None

    def _publish(self, beat: DirectorBeat) -> None:
        """Fire the beat on the EventBus.

        Args:
            beat: The beat to publish.
        """
        try:
            bus = _bus()
            et = _event_types()
            bus.publish(
                event_type=et.DIRECTOR_BEAT_FIRED,
                payload=beat.to_dict(),
                scene=beat.scene,
            )
            logger.debug(
                "Director fired beat %s (%s) for scene %r.",
                beat.id,
                beat.beat_type.value,
                beat.scene,
            )
        except Exception:
            logger.exception("Failed to publish director beat %s.", beat.id)

    def _log_to_nexus(self, beat: DirectorBeat) -> None:
        """Persist the beat to Nexus as history.

        Args:
            beat: The beat to log.
        """
        nexus = self._nexus
        if nexus is None:
            return
        try:
            nexus.add_entry(
                title=f"beat:{beat.scene}:{beat.id}",
                content=(
                    f"type={beat.beat_type.value} urgency={beat.urgency:.2f} "
                    f"intensity={beat.content_intensity}\n{beat.instruction}"
                ),
                content_type="history",
                category="director",
                tags=["director", beat.scene, beat.beat_type.value],
            )
        except Exception:
            logger.exception("Nexus logging failed for beat %s.", beat.id)

    def _register_beat(self, beat: DirectorBeat) -> None:
        """Store beat in internal state dictionaries.

        Args:
            beat: Newly created beat to register.
        """
        self._beat_history.setdefault(beat.scene, []).append(beat)
        self._beats_by_id[beat.id] = beat

    # ------------------------------------------------------------------
    # Beat instruction resolution
    # ------------------------------------------------------------------

    def _get_instruction(
        self,
        scene: str,
        beat_type: BeatType,
        scene_state: dict,
    ) -> str:
        """Resolve a beat instruction string.

        Tries Nexus first; falls back to :data:`BEAT_TEMPLATES`.

        Args:
            scene: Scene name.
            beat_type: The type of beat being constructed.
            scene_state: Current scene state snapshot (for context).

        Returns:
            Instruction string ready for agent injection.
        """
        nexus = self._nexus
        if nexus is not None:
            try:
                query = f"{scene} {beat_type.value} director beat"
                results = nexus.search(query, limit=3)
                if results:
                    content = results[0].get("content", "")
                    if content and len(content) > 20:
                        logger.debug(
                            "Nexus resolved instruction for %s/%s.",
                            scene,
                            beat_type.value,
                        )
                        return content
            except Exception:
                logger.debug(
                    "Nexus search failed for %s/%s; using template.",
                    scene,
                    beat_type.value,
                )

        template = BEAT_TEMPLATES.get(
            beat_type,
            "The scene calls for a narrative shift. Respond naturally.",
        )
        return template.format(scene=scene)

    # ------------------------------------------------------------------
    # Beat type selection
    # ------------------------------------------------------------------

    def _select_beat_type(self, scene: str, scene_state: dict) -> Optional[BeatType]:
        """Analyse scene state and choose an appropriate beat type.

        Decision priority (first match wins):

        1. ``turn_count`` is a milestone → :attr:`BeatType.REVELATION`
        2. ``arousal`` > 80 → :attr:`BeatType.ESCALATION`
        3. ``arousal`` < 20 **and** last beat was escalation → :attr:`BeatType.COOL_DOWN`
        4. ``credits`` < 100 → :attr:`BeatType.REWARD`
        5. ``idle_seconds`` > 120 → :attr:`BeatType.STORY_BEAT` or :attr:`BeatType.COMPLICATION`
        6. No trigger condition met → ``None`` (no beat this tick)

        Args:
            scene: Scene name (used for logging).
            scene_state: State snapshot with optional keys:
                ``turn_count``, ``emotion_levels``, ``idle_seconds``,
                ``economy_balance``, ``reputation``, ``last_beat_type``.

        Returns:
            The selected :class:`BeatType`, or ``None`` if no beat should fire.
        """
        turn_count: int = scene_state.get("turn_count", 0)
        emotion_levels: dict = scene_state.get("emotion_levels", {})
        idle_seconds: float = scene_state.get("idle_seconds", 0.0)
        credits: float = scene_state.get("economy_balance", scene_state.get("credits", 999.0))
        last_beat_type_raw: Optional[str] = scene_state.get("last_beat_type")
        arousal: float = emotion_levels.get("arousal", 0.0)

        # Per-scene config (avoid_beats, escalation_threshold)
        scene_cfg = SCENE_BEAT_CONFIGS.get(scene, {})
        avoid_beats = set(scene_cfg.get("avoid_beats", []))
        escalation_threshold: float = scene_cfg.get("escalation_threshold", 80.0)

        # 1. Milestone revelation
        if turn_count in _MILESTONE_TURNS:
            logger.debug("Scene %r hit milestone turn %d → REVELATION.", scene, turn_count)
            return BeatType.REVELATION

        # 2. High arousal → escalation (per-scene threshold)
        if arousal > escalation_threshold and BeatType.ESCALATION not in avoid_beats:
            logger.debug("Scene %r arousal=%.1f → ESCALATION.", scene, arousal)
            return BeatType.ESCALATION

        # 3. Cool-down after escalation
        if arousal < 20 and last_beat_type_raw == BeatType.ESCALATION.value:
            logger.debug("Scene %r arousal low after escalation → COOL_DOWN.", scene)
            return BeatType.COOL_DOWN

        # 4. Economy opportunity
        if credits < 100 and BeatType.REWARD not in avoid_beats:
            logger.debug("Scene %r credits=%.1f → REWARD.", scene, credits)
            return BeatType.REWARD

        # 5. Idle too long
        if idle_seconds > 120:
            # Alternate between story beat and complication based on history
            history = self._beat_history.get(scene, [])
            last_auto = next(
                (
                    b.beat_type
                    for b in reversed(history)
                    if b.beat_type in (BeatType.STORY_BEAT, BeatType.COMPLICATION)
                ),
                None,
            )
            chosen = (
                BeatType.COMPLICATION
                if last_auto == BeatType.STORY_BEAT
                else BeatType.STORY_BEAT
            )
            if chosen in avoid_beats:
                chosen = BeatType.WORLD_EVENT if BeatType.WORLD_EVENT not in avoid_beats else None
            if chosen is not None:
                logger.debug(
                    "Scene %r idle %.1fs → %s.", scene, idle_seconds, chosen.value
                )
            return chosen

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self, scene: str, scene_state: dict) -> Optional[DirectorBeat]:
        """Main director tick — analyse state and optionally fire a beat.

        Should be called periodically (e.g. every 30 s by the scene loop or
        on each user turn).

        Args:
            scene: Identifier of the active scene (e.g. ``"penthouse"``).
            scene_state: Current state snapshot.  Recognised keys:

                - ``turn_count`` (int)
                - ``emotion_levels`` (dict) — must contain ``"arousal"`` float
                - ``idle_seconds`` (float)
                - ``economy_balance`` or ``credits`` (float)
                - ``last_beat_type`` (str)

        Returns:
            A :class:`DirectorBeat` if one was fired, or ``None`` if the
            cooldown is still active or no trigger condition matched.
        """
        now = time.time()

        # Cooldown guard
        last = self._last_beat_time.get(scene, 0.0)
        if now - last < _BEAT_COOLDOWN_SECONDS:
            remaining = _BEAT_COOLDOWN_SECONDS - (now - last)
            logger.debug(
                "Director cooldown for scene %r: %.1fs remaining.", scene, remaining
            )
            return None

        beat_type = self._select_beat_type(scene, scene_state)
        if beat_type is None:
            logger.debug("No beat triggered for scene %r this tick.", scene)
            return None

        instruction = self._get_instruction(scene, beat_type, scene_state)

        # Compute urgency and content intensity from state
        arousal: float = scene_state.get("emotion_levels", {}).get("arousal", 0.0)
        idle_seconds: float = scene_state.get("idle_seconds", 0.0)
        urgency = min(1.0, max(0.1, idle_seconds / 300.0 + arousal / 200.0))
        content_intensity = min(3, int(arousal // 30))

        beat = DirectorBeat(
            id=str(uuid.uuid4()),
            scene=scene,
            beat_type=beat_type,
            instruction=instruction,
            urgency=round(urgency, 3),
            content_intensity=content_intensity,
            context=dict(scene_state),
            timestamp=now,
            fired=False,
        )

        self._register_beat(beat)
        self._last_beat_time[scene] = now
        self._log_to_nexus(beat)
        self._publish(beat)

        logger.info(
            "Director beat fired: scene=%r type=%s urgency=%.2f id=%s",
            scene,
            beat_type.value,
            urgency,
            beat.id,
        )
        return beat

    def nudge(
        self,
        scene: str,
        direction: str,
        intensity: int = 2,
    ) -> DirectorBeat:
        """Create an on-demand beat in the requested direction.

        Bypasses the cooldown guard — intended for explicit MCP ``director_nudge``
        skill invocations.

        Args:
            scene: Target scene identifier.
            direction: One of ``"escalate"``, ``"cool_down"``, ``"complicate"``,
                ``"reward"``, ``"reveal"``, ``"story"``, ``"character"``,
                ``"world"``.
            intensity: Content intensity level 0–3 (default 2).

        Returns:
            The created and published :class:`DirectorBeat`.

        Raises:
            ValueError: If ``direction`` is not a recognised nudge key.
        """
        beat_type = _NUDGE_MAP.get(direction.lower())
        if beat_type is None:
            valid = ", ".join(sorted(_NUDGE_MAP))
            raise ValueError(
                f"Unknown nudge direction {direction!r}. Valid: {valid}"
            )

        instruction = self._get_instruction(scene, beat_type, {})

        beat = DirectorBeat(
            id=str(uuid.uuid4()),
            scene=scene,
            beat_type=beat_type,
            instruction=instruction,
            urgency=min(1.0, 0.4 + intensity * 0.2),
            content_intensity=min(3, max(0, intensity)),
            context={"nudge_direction": direction, "nudge_intensity": intensity},
            timestamp=time.time(),
            fired=False,
        )

        self._register_beat(beat)
        self._last_beat_time[scene] = beat.timestamp
        self._log_to_nexus(beat)
        self._publish(beat)

        logger.info(
            "Director nudge: scene=%r direction=%r beat_id=%s",
            scene,
            direction,
            beat.id,
        )
        return beat

    def get_pending_beats(self, scene: str) -> List[DirectorBeat]:
        """Return all unfired beats for a scene.

        Args:
            scene: Scene identifier.

        Returns:
            List of :class:`DirectorBeat` instances with ``fired=False``,
            in creation order.
        """
        return [b for b in self._beat_history.get(scene, []) if not b.fired]

    def mark_fired(self, beat_id: str) -> None:
        """Mark a beat as consumed by the pipeline.

        Args:
            beat_id: UUID string of the beat to mark.
        """
        beat = self._beats_by_id.get(beat_id)
        if beat is None:
            logger.warning("mark_fired: unknown beat_id %r.", beat_id)
            return
        beat.fired = True
        logger.debug("Beat %s marked as fired.", beat_id)

    def get_history(self, scene: str, limit: int = 20) -> List[DirectorBeat]:
        """Return the most recent beats for a scene.

        Args:
            scene: Scene identifier.
            limit: Maximum number of beats to return (most recent first).

        Returns:
            List of :class:`DirectorBeat` instances, newest first.
        """
        history = self._beat_history.get(scene, [])
        return list(reversed(history[-limit:])) if history else []

    def reset_scene(self, scene: str) -> None:
        """Clear all director state for a scene, restarting its arc.

        Args:
            scene: Scene identifier to reset.
        """
        removed = len(self._beat_history.pop(scene, []))
        self._last_beat_time.pop(scene, None)
        # Clean up beats_by_id for this scene
        stale = [bid for bid, b in self._beats_by_id.items() if b.scene == scene]
        for bid in stale:
            del self._beats_by_id[bid]
        logger.info(
            "Director state reset for scene %r (%d beats removed).", scene, removed
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_director_instance: Optional[SceneDirector] = None
_director_lock = __import__("threading").Lock()


def get_scene_director() -> SceneDirector:
    """Return the process-wide :class:`SceneDirector` singleton.

    Returns:
        The shared :class:`SceneDirector` instance, creating it on first call.
    """
    global _director_instance
    if _director_instance is None:
        with _director_lock:
            if _director_instance is None:
                _director_instance = SceneDirector()
    return _director_instance
