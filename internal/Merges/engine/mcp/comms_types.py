from __future__ import annotations
import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from engine.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  SKILL MANIFEST
# ══════════════════════════════════════════════════════════════════════

TRIGGER_AUTO     = "auto"       # run before LLM call; inject result into context
TRIGGER_OPTIONAL = "optional"   # model may choose to call it
TRIGGER_REQUIRED = "required"   # model MUST call it (enforced via system prompt)


@dataclass
class SkillEntry:
    """One skill definition within a manifest."""
    name:           str
    trigger:        str   = TRIGGER_OPTIONAL
    description:    str   = ""
    when:           str   = "always"   # "always" | "game_active" | python expr string
    args_template:  Dict  = field(default_factory=dict)  # pre-filled arg defaults


@dataclass
class SceneManifest:
    """All skills available in a particular scene."""
    scene:   str
    skills:  List[SkillEntry] = field(default_factory=list)

    def auto_skills(self)     -> List[SkillEntry]:
        return [s for s in self.skills if s.trigger == TRIGGER_AUTO]

    def optional_skills(self) -> List[SkillEntry]:
        return [s for s in self.skills if s.trigger == TRIGGER_OPTIONAL]

    def required_skills(self) -> List[SkillEntry]:
        return [s for s in self.skills if s.trigger == TRIGGER_REQUIRED]


class SkillManifest:
    """
    Loads scene→skill mappings from ``config/skill_manifests.yaml``
    and exposes them to the governance layer.
    """

    _DEFAULTS: Dict[str, List[Dict]] = {
        "phone": [
            {"name": "search_memory",  "trigger": "auto",     "description": "Recall relevant past conversations"},
            {"name": "update_mood",    "trigger": "optional", "description": "Update character mood"},
            {"name": "roll_dice",      "trigger": "optional", "description": "Generate a random outcome (1–100)"},
            {"name": "log_event",      "trigger": "auto",     "description": "Log this interaction to the event chain"},
        ],
        "bedroom": [
            {"name": "search_memory",  "trigger": "auto",     "description": "Recall relevant past encounters"},
            {"name": "update_mood",    "trigger": "optional", "description": "Update character mood"},
            {"name": "adjust_relationship", "trigger": "optional", "description": "Adjust relationship metrics"},
        ],
        "games/truth_or_dare": [
            {"name": "roll_dice",      "trigger": "auto",     "description": "Roll to pick truth or dare"},
            {"name": "get_game_state", "trigger": "auto",     "description": "Read current game state"},
            {"name": "set_game_state", "trigger": "required", "description": "Record round result"},
            {"name": "update_mood",    "trigger": "auto",     "description": "Apply mood from dare/truth result"},
            {"name": "get_random_topic","trigger":"optional", "description": "Pick a truth question or dare idea"},
        ],
        "games/mystery": [
            {"name": "search_memory",  "trigger": "auto",     "description": "Search memories for clues"},
            {"name": "search_web",     "trigger": "optional", "description": "Look up a clue online"},
            {"name": "get_game_state", "trigger": "auto",     "description": "Read mystery state"},
            {"name": "set_game_state", "trigger": "required", "description": "Record clue discovery"},
            {"name": "get_random_topic","trigger":"optional", "description": "Generate a new clue"},
        ],
    }

    def __init__(self) -> None:
        self._scenes:   Dict[str, SceneManifest] = {}
        self._yaml_mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        """Load from YAML file; fall back to defaults."""
        yaml_path = CONFIG_DIR / "skill_manifests.yaml"
        try:
            if yaml_path.exists():
                mtime = yaml_path.stat().st_mtime
                if mtime == self._yaml_mtime:
                    return  # unchanged
                import yaml
                with yaml_path.open() as f:
                    data = yaml.safe_load(f) or {}
                scenes_data: Dict[str, Any] = data.get("scenes", {})
                self._scenes = {}
                for scene_name, skill_list in scenes_data.items():
                    entries = [SkillEntry(**s) for s in (skill_list or [])]
                    self._scenes[scene_name] = SceneManifest(scene=scene_name, skills=entries)
                self._yaml_mtime = mtime
                return
        except Exception as exc:
            logger.warning("skill_manifests.yaml load failed: %s — using defaults", exc)

        # Build from defaults
        self._scenes = {}
        for scene_name, skill_list in self._DEFAULTS.items():
            entries = [SkillEntry(**s) for s in skill_list]
            self._scenes[scene_name] = SceneManifest(scene=scene_name, skills=entries)

    def get(self, scene: str) -> SceneManifest:
        """Return manifest for a scene; reload YAML if modified."""
        self._load()
        if scene in self._scenes:
            return self._scenes[scene]
        # Return empty manifest for unknown scenes
        return SceneManifest(scene=scene, skills=[])

    def all_scenes(self) -> List[str]:
        self._load()
        return list(self._scenes.keys())


# ══════════════════════════════════════════════════════════════════════
#  INTERACTION POLICY
# ══════════════════════════════════════════════════════════════════════

@dataclass
class InteractionPolicy:
    """
    Governs how a specific character behaves in a scene.

    All fields are optional; unset fields impose no constraint.
    """
    max_reply_tokens:     int  = 500
    min_reply_tokens:     int  = 10
    enforce_in_character: bool = True     # add "stay in character" reminder
    allow_explicit:       bool = False
    required_tone:        str  = ""       # e.g. "warm", "mysterious", "playful"
    forbidden_topics:     List[str] = field(default_factory=list)
    tool_call_limit:      int  = 6        # max tool-call rounds per reply
    append_to_system:     str  = ""       # custom text appended to system prompt


# ══════════════════════════════════════════════════════════════════════
#  RESPONSE CONTEXT
# ══════════════════════════════════════════════════════════════════════

class ResponseContext(dict):
    """
    Mutable bag-of-properties for one interaction.

    Interceptors read and write standard keys:

    * ``system_prompt``   — the character's system prompt (pre: modify here)
    * ``user_message``    — what the user sent
    * ``messages``        — full messages list passed to the LLM
    * ``reply``           — the LLM's reply (post: modify here)
    * ``scene``           — current scene name
    * ``agent_id``        — character id
    * ``agent_name``      — character display name
    * ``skill_manifest``  — ``SceneManifest`` for the current scene
    * ``policy``          — ``InteractionPolicy``
    * ``game_state``      — current game state dict (if in a game)
    * ``abort``           — set True to stop the pipeline
    * ``skip_llm``        — set True to bypass the LLM (interceptor provides reply)
    * ``auto_results``    — results from auto-triggered skills
    * ``extra``           — arbitrary pass-through data

    **v2.7 keys** (set after LLM call):

    * ``response_id``     — server response_id for conversation branching
    * ``store``           — whether this call was stored (True/False/None)
    * ``is_stateful``     — whether response has a valid response_id
    * ``reasoning``       — reasoning content from thinking models
    * ``tool_calls``      — list of tool calls made during inference
    * ``mood_tags``       — extracted [MOOD:x] tags from response
    * ``image_requests``  — extracted [IMAGE:x] tags from response
    * ``action_tags``     — extracted [ACTION:x] tags from response
    * ``processed``       — full ProcessedResponse (when streaming used)
    """

    def require(self, key: str) -> Any:
        if key not in self:
            raise KeyError(f"ResponseContext missing required key: {key!r}")
        return self[key]


# ══════════════════════════════════════════════════════════════════════
#  INTERCEPTOR BASE & PIPELINE
# ══════════════════════════════════════════════════════════════════════

class InterceptorBase(abc.ABC):
    """
    Abstract interceptor hook.

    Override ``pre_call`` to modify messages/system_prompt BEFORE the LLM.
    Override ``post_call`` to modify the reply AFTER the LLM.

    Both methods receive the mutable ``ResponseContext``.

    Set ``applicable_scenes`` to a set of scene IDs to restrict this
    interceptor to specific scenes.  ``None`` means run everywhere.
    """
    name: str = "base"
    priority: int = 50  # lower runs first
    applicable_scenes: Optional[Set[str]] = None  # None = all scenes

    def pre_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Run before the LLM call.  Modify ctx['system_prompt'] or ctx['messages']."""

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Run after the LLM call.  Read/modify ctx['reply']."""


class InterceptorPipeline:
    """
    Ordered chain of interceptors.

    Interceptors added via ``add()`` are sorted by ``priority`` (ascending).
    Any interceptor can set ``ctx['abort'] = True`` to stop the chain.

    Scene-aware (v3.1): interceptors with ``applicable_scenes`` set are
    skipped when ``ctx['scene']`` doesn't match.
    """

    def __init__(self) -> None:
        self._interceptors: List[InterceptorBase] = []

    def add(self, interceptor: InterceptorBase) -> "InterceptorPipeline":
        self._interceptors.append(interceptor)
        self._interceptors.sort(key=lambda x: x.priority)
        return self

    def remove(self, name: str) -> None:
        self._interceptors = [i for i in self._interceptors if i.name != name]

    def _is_applicable(self, interceptor: InterceptorBase, ctx: ResponseContext) -> bool:
        """Check if an interceptor should run for the current scene."""
        if interceptor.applicable_scenes is None:
            return True
        scene = ctx.get("scene", "")
        return scene in interceptor.applicable_scenes

    def run_pre(self, ctx: ResponseContext) -> None:
        for interceptor in self._interceptors:
            if ctx.get("abort"):
                break
            if not self._is_applicable(interceptor, ctx):
                continue
            try:
                interceptor.pre_call(ctx)
            except Exception as exc:
                logger.warning("Interceptor %s.pre_call failed: %s", interceptor.name, exc)

    def run_post(self, ctx: ResponseContext) -> None:
        for interceptor in self._interceptors:
            if ctx.get("abort"):
                break
            if not self._is_applicable(interceptor, ctx):
                continue
            try:
                interceptor.post_call(ctx)
            except Exception as exc:
                logger.warning("Interceptor %s.post_call failed: %s", interceptor.name, exc)

    @property
    def names(self) -> List[str]:
        return [i.name for i in self._interceptors]


# ══════════════════════════════════════════════════════════════════════
#  GAME STATE
# ══════════════════════════════════════════════════════════════════════

class GameState:
    """
    Thread-safe, multi-game key-value store with reactive observers.

    Each game has its own namespace:  ``get_game_state().get("tod", "round")``

    Observer example::

        def on_change(game_id: str, key: str, value: Any) -> None:
            print(f"[{game_id}] {key} = {value}")

        gs = get_game_state()
        gs.subscribe("tod_game", on_change)
        gs.set("tod_game", "round", 3)   # triggers on_change
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._store:    Dict[str, Dict[str, Any]] = {}
        self._obs_lock  = threading.Lock()
        self._observers: Dict[str, List[Callable]] = {}   # game_id → list of callables

    # ── CRUD ─────────────────────────────────────────────────────────

    def get(self, game_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._store.get(game_id, {}).get(key, default)

    def set(self, game_id: str, key: str, value: Any) -> None:
        with self._lock:
            if game_id not in self._store:
                self._store[game_id] = {}
            self._store[game_id][key] = value
        self._notify(game_id, key, value)

    def increment(self, game_id: str, key: str, amount: int = 1) -> int:
        with self._lock:
            if game_id not in self._store:
                self._store[game_id] = {}
            new_val = self._store[game_id].get(key, 0) + amount
            self._store[game_id][key] = new_val
        self._notify(game_id, key, new_val)
        return new_val

    def get_all(self, game_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._store.get(game_id, {}))

    def reset(self, game_id: str) -> None:
        with self._lock:
            self._store.pop(game_id, None)
        self._notify(game_id, "__reset__", None)
        logger.info("GameState reset for game %r", game_id)

    def all_games(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    # ── Observers ────────────────────────────────────────────────────

    def subscribe(self, game_id: str, fn: Callable) -> None:
        """
        Register *fn* as an observer for all state changes in *game_id*.

        ``fn`` will be called as ``fn(game_id, key, value)`` synchronously
        after each ``set()`` or ``increment()`` (and with key=``"__reset__"``
        on ``reset()``).

        Multiple subscribers for the same game are supported.
        """
        with self._obs_lock:
            if game_id not in self._observers:
                self._observers[game_id] = []
            if fn not in self._observers[game_id]:
                self._observers[game_id].append(fn)

    def unsubscribe(self, game_id: str, fn: Callable) -> None:
        """Remove a previously registered observer."""
        with self._obs_lock:
            obs = self._observers.get(game_id, [])
            if fn in obs:
                obs.remove(fn)

    def subscribe_all(self, fn: Callable) -> None:
        """
        Register *fn* as a catch-all observer for ALL games.

        Useful for logging or audit trails:  ``fn(game_id, key, value)``
        """
        with self._obs_lock:
            if "__all__" not in self._observers:
                self._observers["__all__"] = []
            if fn not in self._observers["__all__"]:
                self._observers["__all__"].append(fn)

    def _notify(self, game_id: str, key: str, value: Any) -> None:
        """Internal: fire all observers for *game_id* and catch-all observers."""
        with self._obs_lock:
            targets = list(self._observers.get(game_id, []))
            targets += list(self._observers.get("__all__", []))
        for fn in targets:
            try:
                fn(game_id, key, value)
            except Exception as exc:
                logger.debug("GameState observer %r raised: %s", fn, exc)


# ══════════════════════════════════════════════════════════════════════
#  AGENT ROUTER  (agent-to-agent messaging)
# ══════════════════════════════════════════════════════════════════════

class AgentRouter:
    """
    Simple in-process message bus for agent-to-agent communication.

    An agent sends a message to another agent's inbox via ``send()``.
    On the next tick the recipient can drain its inbox via ``drain()``.
    """

    def __init__(self) -> None:
        self._lock:   threading.Lock             = threading.Lock()
        self._inboxes: Dict[str, List[Dict]]      = {}

    def send(self, recipient_id: str, message: str, *, sender_id: str = "system", meta: Optional[Dict] = None) -> None:
        """Place a message in ``recipient_id``'s inbox."""
        with self._lock:
            if recipient_id not in self._inboxes:
                self._inboxes[recipient_id] = []
            self._inboxes[recipient_id].append({
                "sender":    sender_id,
                "message":   message,
                "timestamp": time.time(),
                "meta":      meta or {},
            })
        logger.debug("AgentRouter: %s → %s: %s", sender_id, recipient_id, message[:60])

    def drain(self, agent_id: str) -> List[Dict]:
        """Return and clear all pending messages for ``agent_id``."""
        with self._lock:
            msgs = self._inboxes.pop(agent_id, [])
        return msgs

    def peek(self, agent_id: str) -> List[Dict]:
        """Return messages without clearing."""
        with self._lock:
            return list(self._inboxes.get(agent_id, []))

    def has_messages(self, agent_id: str) -> bool:
        with self._lock:
            return bool(self._inboxes.get(agent_id))


# ══════════════════════════════════════════════════════════════════════
