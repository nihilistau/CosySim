"""
CosySim MCP Framework
======================

The Framework is the root of the entire MCP system.  Every other subsystem —
character registry, dialog engine, rules engine, scene state — registers with
this framework and communicates through it.

Architecture
------------

``MCPFramework``  (global singleton — the root)
│
├─── ``MCPSceneNode``  (one per active scene: "bedroom", "phone", …)
│     ├── local rules (from SceneRulesEngine)
│     ├── present characters  (MCPCharacterNode refs)
│     ├── event subscriptions
│     └── cross-scene bridge slots
│
└─── ``MCPCharacterNode``  (one per character — exists independently of scene)
      ├── profile + state  (from CharacterRegistry)
      ├── skill list        (auto / optional / required)
      ├── RAG memory knob
      ├── current_scene ref
      └── message inbox

Cross-scene communication
-------------------------
Characters in *different* scenes can communicate through a shared
``CrossSceneBridge`` managed by MCPFramework.  Example use-cases:

* Phone call between "phone" scene (user) and "bedroom" scene (Aria)
* Message notification arriving while the agent is in the bedroom
* Director-issued event that spans multiple scenes simultaneously

Consequence chains
------------------
``MCPFramework.schedule_consequence()`` queues a future effect that fires
after N conversation turns.  The ``DialogDirectiveInterceptor`` tick calls
``MCPFramework.tick_consequences()`` each turn, draining the queue.

MCPSceneMixin
-------------
A lightweight mixin that makes any ``BaseScene`` subclass aware of the
MCP framework automatically::

    class BedroomScene(BaseScene, MCPSceneMixin, scene_id="bedroom"):
        ...

The mixin calls ``MCPFramework.get().register_scene(self)`` in ``__init_subclass__``
so no extra wiring is needed in the concrete scene.

Standalone use::

    from engine.mcp.framework import get_framework, MCPCharacterNode

    fw = get_framework()

    # Register a scene node  
    bedroom = fw.get_scene("bedroom")   # auto-created if not exists

    # Register a character and put them in the bedroom
    aria = fw.get_character("aria")
    aria.enter_scene("bedroom")

    # Send a cross-scene message (bedroom → phone)
    fw.cross_scene_send(
        from_char="user", from_scene="phone",
        to_char="aria",   to_scene="bedroom",
        message="Hey, thinking about you.",
        message_type="text",
    )

    # Schedule a consequence
    fw.schedule_consequence(
        scene_id="bedroom", character_id="aria",
        consequence_type="stat_adjust",
        params={"stat": "arousal", "delta": 15},
        trigger_after_turns=2,
        description="Tension builds after the touch.",
    )
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  TIMER  ─ lightweight in-process countdown timer
# ══════════════════════════════════════════════════════════════════════

@dataclass
class MCPTimer:
    """
    A named countdown timer managed by MCPFramework.

    The timer is intentionally *passive* — it does not fire a Python thread
    callback.  Instead, any agent can ``check_timer(name)`` and act on it.
    This keeps timers conversation-turn driven, which is correct for an LLM
    system.

    Fields
    ------
    name            — unique identifier
    duration_secs   — total duration
    started_at      — unix timestamp when started
    on_complete_note — human-readable note returned when timer fires
    metadata        — arbitrary extra data
    """
    name:             str
    duration_secs:    float
    started_at:       float    = field(default_factory=time.time)
    on_complete_note: str      = ""
    metadata:         Dict     = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    @property
    def remaining(self) -> float:
        return max(0.0, self.duration_secs - self.elapsed)

    @property
    def completed(self) -> bool:
        return self.elapsed >= self.duration_secs

    @property
    def progress(self) -> float:
        """0.0 → 1.0"""
        return min(1.0, self.elapsed / self.duration_secs) if self.duration_secs > 0 else 1.0

    def to_dict(self) -> Dict:
        return {
            "name":             self.name,
            "duration_secs":    self.duration_secs,
            "elapsed":          round(self.elapsed, 1),
            "remaining":        round(self.remaining, 1),
            "progress_pct":     round(self.progress * 100, 1),
            "completed":        self.completed,
            "on_complete_note": self.on_complete_note,
        }


# ══════════════════════════════════════════════════════════════════════
#  CONSEQUENCE CHAIN  ─ deferred effects
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ScheduledConsequence:
    """
    A deferred effect that fires after ``turn_delay`` conversation turns.

    Consequence types mirror RuleEffect types:
      stat_adjust, state_set, add_restriction, remove_restriction,
      add_narrative, set_directive, scene_event, custom_callback
    """
    consequence_id:   str
    scene_id:         str
    character_id:     str
    consequence_type: str
    params:           Dict
    description:      str       = ""
    created_at_turn:  int       = 0
    turn_delay:       int       = 1
    fired:            bool      = False
    created_by:       str       = "director"

    @property
    def fire_at_turn(self) -> int:
        return self.created_at_turn + self.turn_delay

    def is_ready(self, current_turn: int) -> bool:
        return not self.fired and current_turn >= self.fire_at_turn

    def to_dict(self) -> Dict:
        return {
            "consequence_id":   self.consequence_id,
            "scene_id":         self.scene_id,
            "character_id":     self.character_id,
            "type":             self.consequence_type,
            "description":      self.description,
            "fires_at_turn":    self.fire_at_turn,
            "fired":            self.fired,
        }


# ══════════════════════════════════════════════════════════════════════
#  CROSS-SCENE MESSAGE
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CrossSceneMessage:
    """
    A message sent between characters residing in different scenes.

    Delivered into the target character's inbox and surfaces via
    ``RouterMessageInjector`` on their next turn.
    """
    message_id:   str
    from_char:    str
    from_scene:   str
    to_char:      str
    to_scene:     str
    message:      str
    message_type: str   = "text"      # text | call_notification | event | system
    sent_at:      float = field(default_factory=time.time)
    read:         bool  = False

    def to_dict(self) -> Dict:
        return {
            "from":         self.from_char,
            "from_scene":   self.from_scene,
            "to":           self.to_char,
            "message":      self.message,
            "type":         self.message_type,
            "sent_at":      self.sent_at,
            "read":         self.read,
        }


# ══════════════════════════════════════════════════════════════════════
#  MCPCharacterNode  ─ per-character subsystem
# ══════════════════════════════════════════════════════════════════════

class MCPCharacterNode:
    """
    The MCP view of one character.  Sits between the raw CharacterRegistry
    and the scene, and provides:

    * Scene membership tracking (which scene the character is currently "in")
    * Message inbox for cross-scene messages
    * Convenience accessors into CharacterRegistry and DialogSystem
    * Unified ``brief()`` for quick agent injection

    Characters are created automatically by ``MCPFramework.get_character()``.
    You do not create them directly.
    """

    def __init__(self, character_id: str, framework: "MCPFramework") -> None:
        self.character_id  = character_id
        self._fw           = framework
        self.current_scene: Optional[str] = None
        self._inbox:        List[CrossSceneMessage] = []
        self._inbox_lock    = threading.Lock()

    # ── Scene membership ─────────────────────────────────────────────

    def enter_scene(self, scene_id: str) -> None:
        """Move this character into a scene, firing the scene's on_character_enter hook."""
        if self.current_scene and self.current_scene != scene_id:
            self._fw.get_scene(self.current_scene).on_character_leave(self.character_id)
        previous = self.current_scene
        self.current_scene = scene_id
        scene_node = self._fw.get_scene(scene_id)
        scene_node.on_character_enter(self.character_id)
        # Update CharacterRegistry state.current_role if scene has a role defined
        try:
            from engine.mcp.character_registry import get_character_registry
            reg = get_character_registry()
            rec = reg.get_record(self.character_id)
            if rec:
                role = rec.profile.scene_roles.get(scene_id, "")
                if role:
                    reg.set_state(self.character_id, current_role=role)
        except Exception:
            pass
        logger.debug("MCPCharacterNode: %s entered scene %s (was: %s)", self.character_id, scene_id, previous)

    def leave_scene(self) -> None:
        """Leave the current scene."""
        if self.current_scene:
            self._fw.get_scene(self.current_scene).on_character_leave(self.character_id)
            self.current_scene = None

    # ── Inbox ────────────────────────────────────────────────────────

    def receive_message(self, msg: CrossSceneMessage) -> None:
        with self._inbox_lock:
            self._inbox.append(msg)
        logger.debug("MCPCharacterNode: %s received cross-scene message from %s@%s",
                     self.character_id, msg.from_char, msg.from_scene)

    def get_unread_messages(self, mark_read: bool = True) -> List[CrossSceneMessage]:
        with self._inbox_lock:
            unread = [m for m in self._inbox if not m.read]
            if mark_read:
                for m in unread:
                    m.read = True
        return unread

    def get_all_messages(self, limit: int = 10) -> List[CrossSceneMessage]:
        with self._inbox_lock:
            return list(self._inbox[-limit:])

    def clear_inbox(self) -> None:
        with self._inbox_lock:
            self._inbox.clear()

    # ── Quick accessors ──────────────────────────────────────────────

    def get_summary(self) -> Dict:
        """Return character summary from registry (or minimal stub)."""
        try:
            from engine.mcp.character_registry import get_character_registry
            return get_character_registry().get_character_summary(self.character_id) or {}
        except Exception:
            return {"character_id": self.character_id}

    def get_state(self) -> Dict:
        """Return mutable state dict."""
        try:
            from engine.mcp.character_registry import get_character_registry
            state = get_character_registry().get_state(self.character_id)
            return state.__dict__ if state else {}
        except Exception:
            return {}

    def has_skill(self, skill_id: str) -> bool:
        try:
            from engine.mcp.character_registry import get_character_registry
            return get_character_registry().has_skill(self.character_id, skill_id)
        except Exception:
            return False

    def brief(self) -> str:
        """One-line status summary for logging/debug."""
        s = self.get_state()
        mood = s.get("mood", "?")
        scene = self.current_scene or "no scene"
        unread = len([m for m in self._inbox if not m.read])
        return f"{self.character_id}@{scene} mood={mood} inbox={unread}"

    def __repr__(self) -> str:
        return f"MCPCharacterNode({self.brief()})"


# ══════════════════════════════════════════════════════════════════════
#  MCPSceneNode  ─ per-scene subsystem
# ══════════════════════════════════════════════════════════════════════

class MCPSceneNode:
    """
    The MCP view of one scene.  Manages the set of characters present,
    fires lifecycle hooks, and bridges to the SceneRulesEngine for this
    scene's rules.

    Scene nodes are created automatically by ``MCPFramework.get_scene()``.
    Concrete scenes can subclass this (via MCPSceneMixin) to override hooks.

    Standard hooks
    --------------
    ``on_character_enter(character_id)``
        Called when a character enters the scene.  Default: pulls their
        character summary and injects scene rules into the dialog system.

    ``on_character_leave(character_id)``
        Called when a character leaves.

    ``on_cross_scene_message(msg)``
        Called when a cross-scene message arrives in this scene.
    """

    def __init__(self, scene_id: str, framework: "MCPFramework") -> None:
        self.scene_id    = scene_id
        self._fw         = framework
        self._present:   Set[str] = set()          # character IDs currently in scene
        self._event_log: List[Dict] = []
        self._lock       = threading.Lock()
        self._subscribers: List[Callable[[str, Dict], None]] = []

    # ── Lifecycle hooks ───────────────────────────────────────────────

    def on_character_enter(self, character_id: str) -> None:
        """
        Default enter hook:
        1. Registers character in present set
        2. Ensures registry + default skills
        3. Injects scene rules into dialog system as a ``topic_steer`` pre-note
        """
        with self._lock:
            self._present.add(character_id)
        self._log_event("character_enter", {"character_id": character_id})

        try:
            from engine.mcp.character_registry import get_character_registry, apply_default_skills
            reg = get_character_registry()
            reg.ensure(character_id)
            if not reg.get_skills(character_id, enabled_only=False):
                apply_default_skills(character_id)
        except Exception as exc:
            logger.debug("MCPSceneNode.on_character_enter registry error: %s", exc)

        # Tell the scene narrative a character has entered
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            get_scene_state_manager().add_narrative(
                self.scene_id,
                f"{character_id} is present in the scene.",
                entry_type="system", character_id=character_id,
            )
        except Exception:
            pass

        logger.debug("MCPSceneNode[%s]: %s entered", self.scene_id, character_id)

    def on_character_leave(self, character_id: str) -> None:
        with self._lock:
            self._present.discard(character_id)
        self._log_event("character_leave", {"character_id": character_id})
        logger.debug("MCPSceneNode[%s]: %s left", self.scene_id, character_id)

    def on_cross_scene_message(self, msg: CrossSceneMessage) -> None:
        """
        A cross-scene message has arrived.  Default: log to narrative.
        """
        self._log_event("cross_scene_message", msg.to_dict())
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            get_scene_state_manager().add_narrative(
                self.scene_id,
                f"[Cross-scene from {msg.from_char}@{msg.from_scene}]: {msg.message[:100]}",
                entry_type="message", character_id=msg.to_char,
            )
        except Exception:
            pass

    # ── Rules accessor ────────────────────────────────────────────────

    def get_rules_text(self) -> str:
        try:
            from engine.mcp.scene_rules_engine import get_rules_engine
            return get_rules_engine().get_rules_text(self.scene_id)
        except Exception as exc:
            return f"[rules unavailable: {exc}]"

    def get_available_actions(self, character_id: str, stats: Optional[Dict] = None) -> List[Dict]:
        try:
            from engine.mcp.scene_rules_engine import get_rules_engine
            return get_rules_engine().get_available_actions(self.scene_id, character_id, stats=stats)
        except Exception:
            return []

    # ── Present characters ────────────────────────────────────────────

    def get_present(self) -> List[str]:
        with self._lock:
            return list(self._present)

    def is_present(self, character_id: str) -> bool:
        with self._lock:
            return character_id in self._present

    # ── Event subscription ────────────────────────────────────────────

    def subscribe(self, callback: Callable[[str, Dict], None]) -> None:
        """Subscribe to scene events.  Callback: (event_type, payload)."""
        self._subscribers.append(callback)

    def emit(self, event_type: str, payload: Optional[Dict] = None) -> None:
        """Emit a scene event to all subscribers."""
        data = payload or {}
        self._log_event(event_type, data)
        for cb in list(self._subscribers):
            try:
                cb(event_type, data)
            except Exception as exc:
                logger.debug("MCPSceneNode subscriber error: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────

    def _log_event(self, event_type: str, payload: Dict) -> None:
        self._event_log.append({
            "event_type": event_type, "payload": payload, "ts": time.time()
        })
        # Keep log bounded
        if len(self._event_log) > 500:
            self._event_log = self._event_log[-300:]

    def get_event_log(self, limit: int = 20) -> List[Dict]:
        return list(self._event_log[-limit:])

    def brief(self) -> str:
        return f"{self.scene_id}[{', '.join(self.get_present())}]"

    def __repr__(self) -> str:
        return f"MCPSceneNode({self.brief()})"


# ══════════════════════════════════════════════════════════════════════
#  MCPSceneMixin  ─ plug into any BaseScene subclass
# ══════════════════════════════════════════════════════════════════════

class MCPSceneMixin:
    """
    Mixin that wires a concrete BaseScene subclass into the MCP Framework.

    Usage::

        class BedroomScene(BaseScene, MCPSceneMixin, mcp_scene_id="bedroom"):
            def __init__(self, ...):
                super().__init__(scene_name="bedroom", ...)
                self._mcp_init()   # call after super().__init__

    The mixin automatically:
    * Gets/creates the MCPSceneNode for this scene from the framework
    * Patches ``load_character`` to call ``character.enter_scene()``
    * Patches ``unload_character`` to call ``character.leave_scene()``

    Subclasses can override ``mcp_on_enter`` and ``mcp_on_leave`` to add
    custom logic when characters arrive/depart.
    """

    _mcp_scene_id: str = ""

    def __init_subclass__(cls, mcp_scene_id: str = "", **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if mcp_scene_id:
            cls._mcp_scene_id = mcp_scene_id

    def _mcp_init(self) -> None:
        """Call this at the end of __init__ to wire up the mixin."""
        scene_id = self._mcp_scene_id or getattr(self, "scene_name", "unknown")
        self._mcp_scene_node: MCPSceneNode = get_framework().get_scene(scene_id)
        logger.debug("MCPSceneMixin: %s wired to framework", scene_id)

    @property
    def mcp(self) -> MCPSceneNode:
        """Access the MCPSceneNode for this scene."""
        if not hasattr(self, "_mcp_scene_node"):
            self._mcp_init()
        return self._mcp_scene_node

    def mcp_on_enter(self, character_id: str) -> None:
        """Override to add custom logic when a character enters."""

    def mcp_on_leave(self, character_id: str) -> None:
        """Override to add custom logic when a character leaves."""


# ══════════════════════════════════════════════════════════════════════
#  MCPFramework  ─ global root singleton
# ══════════════════════════════════════════════════════════════════════

class MCPFramework:
    """
    Root of the CosySim MCP system.

    Owns
    ----
    * ``_scenes``       — Dict[scene_id, MCPSceneNode]
    * ``_characters``   — Dict[character_id, MCPCharacterNode]
    * ``_timers``       — Dict[timer_name, MCPTimer]
    * ``_consequences`` — List[ScheduledConsequence]
    * ``_turn``         — global turn counter (incremented by tick())

    All access is thread-safe.

    Primary operations
    ------------------
    ``get_scene(scene_id)``        — get or auto-create a scene node
    ``get_character(char_id)``     — get or auto-create a character node
    ``cross_scene_send(...)``      — route a message between scenes
    ``schedule_consequence(...)``  — queue a future effect
    ``tick(scene_id)``             — advance turn counter + fire due consequences
    ``start_timer(...)``           — create a timer
    ``check_timer(name)``          — query a timer's state
    ``random_pick(n, ...)``        — weighted / seeded random choice
    """

    def __init__(self) -> None:
        self._lock           = threading.RLock()
        self._scenes:        Dict[str, MCPSceneNode]      = {}
        self._characters:    Dict[str, MCPCharacterNode]  = {}
        self._timers:        Dict[str, MCPTimer]           = {}
        self._consequences:  List[ScheduledConsequence]    = []
        self._turn:          int                           = 0
        self._consequence_counter = 0

    # ── Scene registry ────────────────────────────────────────────────

    def get_scene(self, scene_id: str) -> MCPSceneNode:
        """Get or auto-create the MCPSceneNode for ``scene_id``."""
        with self._lock:
            if scene_id not in self._scenes:
                self._scenes[scene_id] = MCPSceneNode(scene_id, self)
                logger.debug("MCPFramework: auto-created scene node '%s'", scene_id)
        return self._scenes[scene_id]

    def register_scene(self, scene_id: str, node: Optional[MCPSceneNode] = None) -> MCPSceneNode:
        """Register a custom MCPSceneNode (or auto-create one)."""
        node = node or MCPSceneNode(scene_id, self)
        with self._lock:
            self._scenes[scene_id] = node
        return node

    def list_scenes(self) -> List[str]:
        with self._lock:
            return list(self._scenes.keys())

    # ── Character registry ────────────────────────────────────────────

    def get_character(self, character_id: str) -> MCPCharacterNode:
        """Get or auto-create the MCPCharacterNode for ``character_id``."""
        with self._lock:
            if character_id not in self._characters:
                self._characters[character_id] = MCPCharacterNode(character_id, self)
                logger.debug("MCPFramework: auto-created character node '%s'", character_id)
        return self._characters[character_id]

    def list_characters(self) -> List[str]:
        with self._lock:
            return list(self._characters.keys())

    def get_characters_in_scene(self, scene_id: str) -> List[str]:
        """Return all character IDs currently in a scene."""
        with self._lock:
            return [cid for cid, node in self._characters.items()
                    if node.current_scene == scene_id]

    # ── Cross-scene communication ─────────────────────────────────────

    def cross_scene_send(
        self,
        from_char:    str,
        from_scene:   str,
        to_char:      str,
        to_scene:     str,
        message:      str,
        message_type: str = "text",
    ) -> CrossSceneMessage:
        """
        Send a message from a character in one scene to a character in another.

        The message lands in the target character's inbox and is picked up by
        ``RouterMessageInjector`` on their next turn (via ``get_cross_scene_inbox``).
        Both scene nodes are notified.
        """
        import uuid
        msg = CrossSceneMessage(
            message_id   = str(uuid.uuid4())[:8],
            from_char    = from_char,
            from_scene   = from_scene,
            to_char      = to_char,
            to_scene     = to_scene,
            message      = message,
            message_type = message_type,
        )
        # Deliver to target character
        target_char = self.get_character(to_char)
        target_char.receive_message(msg)
        # Notify target scene
        target_scene = self.get_scene(to_scene)
        target_scene.on_cross_scene_message(msg)
        # Log on source side
        source_scene = self.get_scene(from_scene)
        source_scene._log_event("cross_scene_sent", {
            "from": from_char, "to": to_char, "to_scene": to_scene,
            "preview": message[:60],
        })
        logger.debug("MCPFramework: cross-scene %s@%s → %s@%s: %s",
                     from_char, from_scene, to_char, to_scene, message[:40])
        return msg

    def get_cross_scene_inbox(self, character_id: str) -> List[Dict]:
        """Return (and mark as read) all unread cross-scene messages for a character."""
        node = self.get_character(character_id)
        return [m.to_dict() for m in node.get_unread_messages(mark_read=True)]

    # ── Timer system ─────────────────────────────────────────────────

    def start_timer(
        self,
        name:             str,
        duration_secs:    float,
        on_complete_note: str = "",
        metadata:         Optional[Dict] = None,
    ) -> MCPTimer:
        """Create or reset a named timer."""
        timer = MCPTimer(
            name             = name,
            duration_secs    = duration_secs,
            on_complete_note = on_complete_note,
            metadata         = metadata or {},
        )
        with self._lock:
            self._timers[name] = timer
        return timer

    def check_timer(self, name: str) -> Optional[MCPTimer]:
        with self._lock:
            return self._timers.get(name)

    def cancel_timer(self, name: str) -> bool:
        with self._lock:
            return bool(self._timers.pop(name, None))

    def list_timers(self) -> List[Dict]:
        with self._lock:
            return [t.to_dict() for t in self._timers.values()]

    # ── Random-pick skill ─────────────────────────────────────────────

    def random_pick(
        self,
        n:        int,
        seed:     Optional[int] = None,
        weights:  Optional[List[float]] = None,
        options:  Optional[List[Any]] = None,
    ) -> Dict:
        """
        Return a random choice from 1..n (or from an options list).

        ``weights`` can bias the distribution (same length as options / n items).
        ``seed`` makes results reproducible.

        Returns a dict with: value, pick, index, roll, interpretation.
        """
        rng = random.Random(seed)

        if options:
            effective_weights = weights if weights and len(weights) == len(options) else None
            if effective_weights:
                pick = rng.choices(options, weights=effective_weights, k=1)[0]
            else:
                pick = rng.choice(options)
            idx  = options.index(pick)
            roll = idx + 1
        else:
            candidates = list(range(1, n + 1))
            if weights and len(weights) == n:
                roll = rng.choices(candidates, weights=weights, k=1)[0]
            else:
                roll = rng.randint(1, n)
            pick = roll
            idx  = roll - 1

        # Interpretation buckets
        if n > 0:
            pct = roll / n
            if pct >= 0.9:
                interp = "exceptional — best possible outcome"
            elif pct >= 0.7:
                interp = "strong — favourable"
            elif pct >= 0.4:
                interp = "moderate — mixed result"
            elif pct >= 0.2:
                interp = "weak — unfavourable"
            else:
                interp = "poor — worst outcome"
        else:
            interp = "invalid"

        return {
            "roll":           roll,
            "value":          pick,
            "index":          idx,
            "out_of":         n,
            "percentile":     round((roll / n) * 100 if n else 0, 1),
            "interpretation": interp,
            "seed":           seed,
        }

    # ── Consequence chains ────────────────────────────────────────────

    def schedule_consequence(
        self,
        scene_id:         str,
        character_id:     str,
        consequence_type: str,
        params:           Dict,
        trigger_after_turns: int = 1,
        description:      str   = "",
        created_by:       str   = "director",
    ) -> ScheduledConsequence:
        """
        Queue a future effect that fires after N conversation turns.

        ``tick(scene_id)`` must be called each turn (the DialogDirectiveInterceptor
        does this automatically).

        Returns the ScheduledConsequence so the caller can inspect or cancel it.
        """
        with self._lock:
            self._consequence_counter += 1
            cseq = ScheduledConsequence(
                consequence_id   = f"cseq_{self._consequence_counter}",
                scene_id         = scene_id,
                character_id     = character_id,
                consequence_type = consequence_type,
                params           = params,
                description      = description,
                created_at_turn  = self._turn,
                turn_delay       = trigger_after_turns,
                created_by       = created_by,
            )
            self._consequences.append(cseq)
        logger.debug("MCPFramework: consequence '%s' scheduled in %d turns",
                     cseq.consequence_id, trigger_after_turns)
        return cseq

    def tick(self, scene_id: str = "") -> List[Dict]:
        """
        Advance the global turn counter and fire all due consequences.
        Called by DialogDirectiveInterceptor after each agent response.

        Returns a list of what fired.
        """
        with self._lock:
            self._turn += 1
            current_turn = self._turn
            due = [c for c in self._consequences
                   if c.is_ready(current_turn) and (not scene_id or c.scene_id == scene_id)]

        fired_reports = []
        for cseq in due:
            report = self._fire_consequence(cseq)
            cseq.fired = True
            fired_reports.append(report)

        return fired_reports

    def get_pending_consequences(self, scene_id: str = "", character_id: str = "") -> List[Dict]:
        """Return unfired consequences, optionally filtered."""
        with self._lock:
            results = [c for c in self._consequences if not c.fired]
        if scene_id:
            results = [c for c in results if c.scene_id == scene_id]
        if character_id:
            results = [c for c in results if c.character_id == character_id]
        return [c.to_dict() for c in results]

    def cancel_consequence(self, consequence_id: str) -> bool:
        """Cancel a pending consequence by ID."""
        with self._lock:
            for c in self._consequences:
                if c.consequence_id == consequence_id and not c.fired:
                    c.fired = True  # Mark as fired to skip
                    return True
        return False

    def _fire_consequence(self, cseq: ScheduledConsequence) -> Dict:
        """Execute a consequence's effect.  Returns a report dict."""
        try:
            from engine.mcp.scene_rules_engine import RuleEffect, get_rules_engine  # noqa
            effect = RuleEffect(effect_type=cseq.consequence_type, params=cseq.params)
            eng = get_rules_engine()
            result = eng._execute_effect(effect, cseq.scene_id, cseq.character_id)
            # Also log narrative
            if cseq.description:
                try:
                    from engine.mcp.scene_state import get_scene_state_manager
                    get_scene_state_manager().add_narrative(
                        cseq.scene_id, cseq.description,
                        entry_type="consequence", character_id=cseq.character_id,
                    )
                except Exception:
                    pass
            return {
                "consequence_id": cseq.consequence_id,
                "type":           cseq.consequence_type,
                "character_id":   cseq.character_id,
                "result":         result,
                "description":    cseq.description,
                "fired_at_turn":  self._turn,
            }
        except Exception as exc:
            return {"consequence_id": cseq.consequence_id, "error": str(exc)}

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Return a full framework status snapshot."""
        with self._lock:
            return {
                "turn":            self._turn,
                "scenes":          list(self._scenes.keys()),
                "characters":      {cid: n.brief() for cid, n in self._characters.items()},
                "active_timers":   len(self._timers),
                "pending_consequences": len([c for c in self._consequences if not c.fired]),
            }

    def __repr__(self) -> str:
        s = self.get_status()
        return (f"MCPFramework(turn={s['turn']}, scenes={s['scenes']}, "
                f"chars={list(s['characters'].keys())}, timers={s['active_timers']})")


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ══════════════════════════════════════════════════════════════════════

_FW_INSTANCE: Optional[MCPFramework] = None
_FW_LOCK = threading.Lock()


def get_framework() -> MCPFramework:
    """
    Return the global MCPFramework singleton.
    Thread-safe, safe to call from any context.
    """
    global _FW_INSTANCE
    if _FW_INSTANCE is None:
        with _FW_LOCK:
            if _FW_INSTANCE is None:
                _FW_INSTANCE = MCPFramework()
                logger.info("MCPFramework: singleton initialised")
    return _FW_INSTANCE
