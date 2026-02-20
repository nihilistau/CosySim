"""
CosySim Communications & Governance Framework
==============================================

This module is the **central nervous system** of CosySim.  Every agent
interaction flows through it — before the LLM is called, during tool-calling,
and after a response is generated.

Architecture
------------

``SkillManifest``
    Maps *scene names* → lists of skills with trigger types:

    * ``auto``     — executed before the LLM call, result injected into context
    * ``optional`` — offered to the LLM as an available tool (model decides)
    * ``required`` — LLM MUST call this before replying (enforced by prompt)

``InteractionPolicy``
    Per-character/scene rules: max reply length, forbidden topics, required
    personality tone, response format constraints.

``ResponseContext``
    Carries all information about a single LLM call — mutable dict that each
    interceptor reads and writes.  Think of it as the request/response object
    for one interaction.

``InterceptorBase``
    Abstract hook.  Subclass and override ``pre_call(ctx)`` or ``post_call(ctx)``.

``InterceptorPipeline``
    Ordered list of interceptors.  ``run_pre(ctx)`` and ``run_post(ctx)`` call
    each one in sequence.  Any interceptor can abort the pipeline by setting
    ``ctx["abort"] = True``.

``AgentGovernor``
    Wraps ``CharacterAgent``.  On each ``reply()`` call it:
    1. Loads the scene's ``SkillManifest``
    2. Runs pre-call interceptors (injects skills, rules, context)
    3. Calls the agent
    4. Runs post-call interceptors (shape response, log, enforce rules)

``GameState``
    Thread-safe key-value store for game variables.  Shared across all
    governors so agents can read/write cross-scene game state.

``AgentRouter``
    Routes messages between named agents.  Agent A can ``send(agent_id, msg)``
    and Agent B's next tick will receive it.

Usage::

    from engine.mcp.comms_framework import get_governor, get_game_state

    # Wrap an agent with the governance layer
    gov = get_governor(character_agent, scene="phone")
    reply = gov.reply("Hey there!")

    # Read/write game state from anywhere
    gs = get_game_state()
    gs.set("tod_game", "dare_count", 3)
    print(gs.get("tod_game", "dare_count"))

    # Route a message to another agent
    from engine.mcp.comms_framework import get_router
    router = get_router()
    router.send("char-aria", "Your friend just called.")
"""
from __future__ import annotations

import abc
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

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
        yaml_path = Path(__file__).parent.parent.parent / "config" / "skill_manifests.yaml"
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
    """
    name: str = "base"
    priority: int = 50  # lower runs first

    def pre_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Run before the LLM call.  Modify ctx['system_prompt'] or ctx['messages']."""

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Run after the LLM call.  Read/modify ctx['reply']."""


class InterceptorPipeline:
    """
    Ordered chain of interceptors.

    Interceptors added via ``add()`` are sorted by ``priority`` (ascending).
    Any interceptor can set ``ctx['abort'] = True`` to stop the chain.
    """

    def __init__(self) -> None:
        self._interceptors: List[InterceptorBase] = []

    def add(self, interceptor: InterceptorBase) -> "InterceptorPipeline":
        self._interceptors.append(interceptor)
        self._interceptors.sort(key=lambda x: x.priority)
        return self

    def remove(self, name: str) -> None:
        self._interceptors = [i for i in self._interceptors if i.name != name]

    def run_pre(self, ctx: ResponseContext) -> None:
        for interceptor in self._interceptors:
            if ctx.get("abort"):
                break
            try:
                interceptor.pre_call(ctx)
            except Exception as exc:
                logger.warning("Interceptor %s.pre_call failed: %s", interceptor.name, exc)

    def run_post(self, ctx: ResponseContext) -> None:
        for interceptor in self._interceptors:
            if ctx.get("abort"):
                break
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
    Thread-safe, multi-game key-value store.

    Each game has its own namespace:  ``get_game_state().get("tod", "round")``
    """

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}

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
        return new_val

    def get_all(self, game_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._store.get(game_id, {}))

    def reset(self, game_id: str) -> None:
        with self._lock:
            self._store.pop(game_id, None)
        logger.info("GameState reset for game %r", game_id)

    def all_games(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    # Observers — lightweight pub/sub for game events
    def _notify(self, game_id: str, key: str, value: Any) -> None:
        pass  # hook for future observer pattern


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
#  AGENT GOVERNOR
# ══════════════════════════════════════════════════════════════════════

class AgentGovernor:
    """
    Wraps a ``CharacterAgent`` with the full governance pipeline.

    On each ``reply()`` call:
    1. Load scene ``SkillManifest``
    2. Build a ``ResponseContext``
    3. Execute auto-triggered skills (results added to context)
    4. Run pre-call interceptors (modify system prompt, inject rules)
    5. Call the underlying ``CharacterAgent.reply()``
    6. Run post-call interceptors (shape/validate response)
    7. Post activity to ``ActivityBus``
    8. Return final reply

    Parameters
    ----------
    agent : CharacterAgent
        The agent to wrap.
    scene : str
        Scene name used to look up the ``SkillManifest``.
    pipeline : InterceptorPipeline, optional
        Override the default pipeline.
    policy : InteractionPolicy, optional
        Override the default policy.
    """

    def __init__(
        self,
        agent,
        *,
        scene:    str                       = "phone",
        pipeline: Optional[InterceptorPipeline] = None,
        policy:   Optional[InteractionPolicy]   = None,
    ) -> None:
        self.agent    = agent
        self.scene    = scene
        self.pipeline = pipeline or _build_default_pipeline()
        self.policy   = policy   or InteractionPolicy()
        self._manifest = get_skill_manifest()
        self._bus      = None  # lazy

    def reply(
        self,
        user_message: str,
        *,
        chain_id:   Optional[str]  = None,
        history:    Optional[List] = None,
        skip_gov:   bool           = False,
        **_kwargs,                            # absorb extra kwargs (e.g. use_tools=False)
    ) -> str:
        """
        Governed reply — runs through the full pipeline.
        Pass ``skip_gov=True`` to bypass and call the agent directly.
        """
        if skip_gov:
            return self.agent.reply(user_message, chain_id=chain_id, history=history)

        # ── 1. Build context ─────────────────────────────────────────
        manifest = self._manifest.get(self.scene)
        agent_name = getattr(self.agent, "character", None)
        agent_name = getattr(agent_name, "name", "Agent") if agent_name else "Agent"
        agent_id   = getattr(getattr(self.agent, "character", None), "id", "unknown")

        ctx = ResponseContext(
            scene         = self.scene,
            agent_id      = agent_id,
            agent_name    = agent_name,
            user_message  = user_message,
            system_prompt = "",
            messages      = [],
            reply         = "",
            skill_manifest= manifest,
            policy        = self.policy,
            game_state    = {},
            auto_results  = {},
            abort         = False,
            skip_llm      = False,
            history       = history or [],
            chain_id      = chain_id,
        )

        # ── 2. Execute AUTO skills ───────────────────────────────────
        for skill_entry in manifest.auto_skills():
            try:
                result = _invoke_mcp_tool(skill_entry.name, skill_entry.args_template, ctx)
                ctx["auto_results"][skill_entry.name] = result
                logger.debug("Auto skill %s: %s", skill_entry.name, str(result)[:80])
            except Exception as exc:
                logger.debug("Auto skill %s failed: %s", skill_entry.name, exc)

        # ── 3. Pre-call pipeline ─────────────────────────────────────
        bus = self._get_bus()
        with bus.activity("thinking", f"{agent_name} is thinking…", agent_id=agent_id, scene=self.scene):
            self.pipeline.run_pre(ctx)

            if ctx.get("skip_llm"):
                return ctx.get("reply", "")

        # ── 4. LLM call ──────────────────────────────────────────────
        with bus.activity("llm_call", f"{agent_name}: generating reply", agent_id=agent_id, scene=self.scene):
            try:
                reply = self.agent.reply(
                    user_message,
                    chain_id = ctx.get("chain_id"),
                    history  = ctx.get("history"),
                )
                ctx["reply"] = reply
            except Exception as exc:
                logger.error("AgentGovernor LLM call failed: %s", exc)
                ctx["reply"] = ""

        # ── 5. Post-call pipeline ────────────────────────────────────
        self.pipeline.run_post(ctx)

        return ctx.get("reply", "")

    def _get_bus(self):
        if self._bus is None:
            from engine.services.activity_bus import get_activity_bus
            self._bus = get_activity_bus()
        return self._bus


def _invoke_mcp_tool(tool_name: str, args: Dict, ctx: ResponseContext) -> Any:
    """Call a tool function by name via the MCP registry."""
    from engine.mcp import cosysim_server as srv
    fn = getattr(srv, tool_name, None)
    if fn is None:
        # Try the comms tools module
        try:
            import engine.mcp.comms_tools as ct
            fn = getattr(ct, tool_name, None)
        except ImportError:
            pass
    if fn is None:
        raise ValueError(f"Tool {tool_name!r} not found in MCP server or comms_tools")
    return fn(**args)


def _build_default_pipeline() -> InterceptorPipeline:
    """Build the default interceptor pipeline for new governors."""
    from engine.agents.interceptors import (
        CharacterRegistryInterceptor,
        RouterMessageInjector,
        DialogDirectiveInterceptor,
        BedroomSceneInterceptor,
        PhoneSceneInterceptor,
        LoungeSceneInterceptor,
        AutoResultInjector,
        SkillAwarenessInterceptor,
        GameSessionInterceptor,
        GameRulesInterceptor,
        PersonalityGuardInterceptor,
        PolicyEnforcerInterceptor,
        MemoryEnhancerInterceptor,
        ResponseShaperInterceptor,
        ActivityLoggerInterceptor,
    )
    pipeline = InterceptorPipeline()
    pipeline.add(CharacterRegistryInterceptor()) #  8
    pipeline.add(RouterMessageInjector())        # 10
    pipeline.add(DialogDirectiveInterceptor())   # 12
    pipeline.add(BedroomSceneInterceptor())      # 15
    pipeline.add(PhoneSceneInterceptor())        # 15
    pipeline.add(LoungeSceneInterceptor())       # 15
    pipeline.add(AutoResultInjector())           # 20
    pipeline.add(SkillAwarenessInterceptor())    # 30
    pipeline.add(GameSessionInterceptor())       # 35  ← MCP game history + actions
    pipeline.add(GameRulesInterceptor())         # 40
    pipeline.add(PersonalityGuardInterceptor())  # 50
    pipeline.add(PolicyEnforcerInterceptor())    # 60
    pipeline.add(MemoryEnhancerInterceptor())    # 70
    pipeline.add(ResponseShaperInterceptor())    # 80
    pipeline.add(ActivityLoggerInterceptor())    # 90
    return pipeline


# ══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETONS
# ══════════════════════════════════════════════════════════════════════

_manifest:     Optional[SkillManifest] = None
_game_state:   Optional[GameState]     = None
_router:       Optional[AgentRouter]   = None
_singletons_lock = threading.Lock()


def get_skill_manifest() -> SkillManifest:
    global _manifest
    if _manifest is None:
        with _singletons_lock:
            if _manifest is None:
                _manifest = SkillManifest()
    return _manifest


def get_game_state() -> GameState:
    global _game_state
    if _game_state is None:
        with _singletons_lock:
            if _game_state is None:
                _game_state = GameState()
    return _game_state


def get_router() -> AgentRouter:
    global _router
    if _router is None:
        with _singletons_lock:
            if _router is None:
                _router = AgentRouter()
    return _router


def get_governor(agent, *, scene: str = "phone", **kwargs) -> AgentGovernor:
    """Convenience factory: wrap an agent in a governor for a given scene."""
    return AgentGovernor(agent, scene=scene, **kwargs)
