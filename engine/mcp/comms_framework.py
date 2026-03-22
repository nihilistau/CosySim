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

Version: v1.49.3 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.3 [2026-03-22] — Structured logging context: [CommsFramework]/[AgentGovernor]
                            prefixes, operation= and entity= context on all log calls
    v1.49.1 [2026-03-22] — Audit: upgrade error swallowing from debug→warning,
                            discriminate LLM exception types, add ctx["error"] flag,
                            structured context in all log messages
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
        "penthouse": [
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
        from engine.paths import CONFIG_DIR
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
            # v1.49.3 [2026-03-22] — Structured logging context
            logger.warning("[CommsFramework] Skill manifest load failed (operation=load_manifests): %s — using defaults", exc)

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
                logger.warning("[CommsFramework] Interceptor pre_call failed (operation=pre_call, interceptor=%s): %s", interceptor.name, exc)

    def run_post(self, ctx: ResponseContext) -> None:
        for interceptor in self._interceptors:
            if ctx.get("abort"):
                break
            if not self._is_applicable(interceptor, ctx):
                continue
            try:
                interceptor.post_call(ctx)
            except Exception as exc:
                logger.warning("[CommsFramework] Interceptor post_call failed (operation=post_call, interceptor=%s): %s", interceptor.name, exc)

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
        logger.info("[CommsFramework] GameState reset (operation=reset, game=%s)", game_id)

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
                # v1.49.1 [2026-03-22] — Upgrade to warning so observer failures are visible
                logger.warning("[CommsFramework] GameState observer raised (operation=notify, game=%s, key=%s): %s", game_id, key, exc)


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
                # v1.49.1 [2026-03-22] — Upgrade from debug to warning for visibility
                logger.warning(
                    "[AgentGovernor] Auto skill failed (operation=auto_skill, skill=%s, scene=%s, agent_id=%s): %s",
                    skill_entry.name, ctx.get("scene", "?"), ctx.get("agent_id", "?"), exc,
                )

        # ── 3. Pre-call pipeline ─────────────────────────────────────
        bus = self._get_bus()
        with bus.activity("thinking", f"{agent_name} is thinking…", agent_id=agent_id, scene=self.scene):
            self.pipeline.run_pre(ctx)

            if ctx.get("skip_llm"):
                return ctx.get("reply", "")

        # ── 4. LLM call ──────────────────────────────────────────────
        with bus.activity("llm_call", f"{agent_name}: generating reply", agent_id=agent_id, scene=self.scene):
            try:
                # Pass interceptor-built context to the agent
                gov_ctx = ctx.get("system_prompt", "").strip() or None
                reply = self.agent.reply(
                    user_message,
                    chain_id = ctx.get("chain_id"),
                    history  = ctx.get("history"),
                    governance_context = gov_ctx,
                )
                ctx["reply"] = reply
                # v2.7: populate response metadata for post-call interceptors
                agent_state = {}
                last_response = None
                try:
                    if hasattr(self.agent, "get_state"):
                        agent_state = self.agent.get_state()
                    elif hasattr(self.agent, "_virtual_agent"):
                        agent_state = self.agent._virtual_agent.get_state()
                    # Get the last InferenceResponse if available
                    va = getattr(self.agent, "_virtual_agent", None)
                    if va:
                        last_response = getattr(va, "_last_response", None)
                except Exception as exc:
                    # v1.49.1 [2026-03-22] — Surface agent state extraction failures
                    logger.warning(
                        "[AgentGovernor] Failed to extract agent state (operation=state_extract, agent_id=%s, scene=%s): %s",
                        ctx.get("agent_id", "?"), ctx.get("scene", "?"), exc,
                    )
                ctx["response_id"] = agent_state.get("last_response_id", "")
                ctx["is_stateful"] = bool(
                    ctx["response_id"] and ctx["response_id"].startswith("resp_")
                )
                # v2.7: populate extracted tags from InferenceResponse
                if last_response:
                    ctx["mood_tags"] = getattr(last_response, "mood_tags", [])
                    ctx["image_requests"] = getattr(last_response, "image_requests", [])
                    ctx["action_tags"] = getattr(last_response, "action_tags", [])
                    ctx["processed"] = getattr(last_response, "processed", None)
                    ctx["reasoning"] = getattr(last_response, "reasoning_content", "")
                    ctx["tool_calls"] = getattr(last_response, "tool_calls", [])
            except TimeoutError as exc:
                # v1.49.1 [2026-03-22] — Discriminate exception types for LLM failures
                logger.error("[AgentGovernor] LLM call timed out (operation=llm_call, agent_id=%s, scene=%s): %s",
                             ctx.get("agent_id", "?"), ctx.get("scene", "?"), exc)
                ctx["reply"] = ""
                ctx["error"] = "timeout"
            except ConnectionError as exc:
                logger.error("[AgentGovernor] LLM connection failed (operation=llm_call, agent_id=%s, scene=%s): %s",
                             ctx.get("agent_id", "?"), ctx.get("scene", "?"), exc)
                ctx["reply"] = ""
                ctx["error"] = "connection"
            except Exception as exc:
                logger.error("[AgentGovernor] LLM call failed (operation=llm_call, agent_id=%s, scene=%s): %s",
                             ctx.get("agent_id", "?"), ctx.get("scene", "?"), exc)
                ctx["reply"] = ""
                ctx["error"] = str(type(exc).__name__)

        # ── 5. Parse response (single pass — v3.1) ─────────────────────
        reply = ctx.get("reply", "")
        if reply:
            from engine.agents.content_router import ContentRouter
            ctx["parsed"] = ContentRouter.parse_full(reply)

        # ── 6. Post-call pipeline ────────────────────────────────────
        self.pipeline.run_post(ctx)

        return ctx.get("reply", "")

    def _get_bus(self):
        if self._bus is None:
            from engine.services.activity_bus import get_activity_bus
            self._bus = get_activity_bus()
        return self._bus

    # ── IAgent-compatible convenience methods ────────────────────────

    def quick_query(self, prompt: str, *, max_tokens: int = 200) -> str:
        """
        Delegate to the underlying agent's ``quick_query()`` or fall back to
        a bare ``reply()`` call with governance bypassed.

        This lets ``AgentLoop._decide()`` work whether the agent is a raw
        ``CharacterAgent`` or a governor-wrapped agent.
        """
        inner = self.agent
        if hasattr(inner, "quick_query"):
            return inner.quick_query(prompt, max_tokens=max_tokens)
        # Fallback: skip governance for fast JSON action queries
        return self.reply(prompt, skip_gov=True)

    def cancel(self) -> None:
        """Delegate cancellation to the underlying agent."""
        if hasattr(self.agent, "cancel"):
            self.agent.cancel()

    @property
    def character(self):
        """Expose the underlying agent's character for interceptors."""
        return getattr(self.agent, "character", None)

    @property
    def capabilities(self):
        """Expose the underlying agent's capability set."""
        from engine.agents.protocols import AgentCapability
        caps = set(getattr(self.agent, "capabilities", set()))
        caps.add(AgentCapability.GOVERNED)
        return caps

    def context_dump(self, user_message: str = "") -> dict:
        """
        Return a dry-run snapshot of the ``ResponseContext`` that would be built
        for *user_message* — useful for debugging interceptor state.

        Does NOT call the LLM.  Auto skills and the interceptor pre-call pipeline
        ARE executed so you can see what each interceptor injects.
        """
        manifest  = self._manifest.get(self.scene)
        agent_name = getattr(self.character, "name", "Agent") if self.character else "Agent"
        agent_id   = getattr(self.character, "id", "unknown") if self.character else "unknown"
        ctx = ResponseContext(
            scene         = self.scene,
            agent_id      = agent_id,
            agent_name    = agent_name,
            user_message  = user_message,
            system_prompt = "",
            messages      = [],
            reply         = "<<DRY RUN — LLM NOT CALLED>>",
            skill_manifest= manifest,
            policy        = self.policy,
            game_state    = {},
            auto_results  = {},
            abort         = False,
            skip_llm      = True,
            history       = [],
            chain_id      = None,
        )
        self.pipeline.run_pre(ctx)
        return dict(ctx)


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
            logger.debug("comms_tools module not available for tool lookup: %s", tool_name)
    if fn is None:
        raise ValueError(f"Tool {tool_name!r} not found in MCP server or comms_tools")
    return fn(**args)


def _build_default_pipeline() -> InterceptorPipeline:
    """Build the default interceptor pipeline for new governors."""
    from engine.agents.interceptors import (
        get_all_interceptors,
        GameInterceptor,
    )
    from engine.agents.dialogue_gate import DialogueGateInterceptor
    # v1.49.1 [2026-03-22] — Registry now has the real RelationshipContextInterceptor,
    # no need to skip/replace. DialogueGateInterceptor still added separately.
    pipeline = InterceptorPipeline()
    for cls in get_all_interceptors():
        pipeline.add(cls())
    # GameInterceptor replaces GameSessionInterceptor + GameRulesInterceptor (one instance)
    if not any(isinstance(i, GameInterceptor) for i in pipeline._interceptors):
        pipeline.add(GameInterceptor())
    pipeline.add(DialogueGateInterceptor())          # 45
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


def build_governance_context(
    agent_id: str,
    scene: str,
    user_message: str = "",
    *,
    history: Optional[List] = None,
) -> str:
    """
    Build governance context (interceptor directives) without a full governor.

    Use this in scenes that call VAM/LMS directly (streaming, special pipelines)
    but still want interceptor-generated directives appended to the system prompt.

    Returns a multi-line string of interceptor injections (mood, heat, personality,
    scene rules, etc.) that should be appended to the agent's system prompt.
    """
    pipeline = _build_default_pipeline()
    manifest = get_skill_manifest().get(scene)
    ctx = ResponseContext(
        scene=scene,
        agent_id=agent_id,
        agent_name=agent_id,
        user_message=user_message,
        system_prompt="",
        messages=[],
        reply="",
        skill_manifest=manifest,
        policy=InteractionPolicy(),
        game_state={},
        auto_results={},
        abort=False,
        skip_llm=False,
        history=history or [],
        chain_id=None,
    )
    try:
        pipeline.run_pre(ctx)
    except Exception as exc:
        logger.debug("build_governance_context pipeline error: %s", exc)
    return ctx.get("system_prompt", "").strip()
