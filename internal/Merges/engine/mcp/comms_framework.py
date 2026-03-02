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

from engine.agents.protocols import AgentCapability, IAgent
from engine.agents.content_router import ContentRouter
from engine.services.activity_bus import get_activity_bus
from engine.paths import CONFIG_DIR
from engine.agents.interceptors import (
    NaturalMoodDriftInterceptor,
    ConversationRecapInterceptor,
    CharacterRegistryInterceptor,
    RouterMessageInjector,
    DialogDirectiveInterceptor,
    BedroomSceneInterceptor,
    PhoneSceneInterceptor,
    LoungeSceneInterceptor,
    GallerySceneInterceptor,
    UniversalSceneInterceptor,
    AmbientEventInterceptor,
    AutoResultInjector,
    SkillAwarenessInterceptor,
    GameSessionInterceptor,
    GameRulesInterceptor,
    PersonalityGuardInterceptor,
    ConversationVarietyInterceptor,
    PolicyEnforcerInterceptor,
    MemoryEnhancerInterceptor,
    ResponseShaperInterceptor,
    TTSStyleInterceptor,
    ActivityLoggerInterceptor,
    MoodSyncInterceptor,
    RelationshipEventInterceptor,
)
from engine.agents.dialogue_gate import DialogueGateInterceptor

from engine.mcp.comms_types import (
    SkillEntry,
    SceneManifest,
    SkillManifest,
    InteractionPolicy,
    ResponseContext,
    InterceptorBase,
    InterceptorPipeline,
    TRIGGER_AUTO,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
    GameState,
    AgentRouter,
)

logger = logging.getLogger(__name__)

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
        scene: str = "phone",
        pipeline: Optional[InterceptorPipeline] = None,
        policy: Optional[InteractionPolicy] = None,
    ) -> None:
        self.agent = agent
        self.scene = scene
        self.pipeline = pipeline or _build_default_pipeline()
        self.policy = policy or InteractionPolicy()
        self._manifest = get_skill_manifest()
        self._bus = None  # lazy

    def reply(
        self,
        user_message: str,
        *,
        chain_id: Optional[str] = None,
        history: Optional[List] = None,
        skip_gov: bool = False,
        **_kwargs,  # absorb extra kwargs (e.g. use_tools=False)
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
        agent_id = getattr(getattr(self.agent, "character", None), "id", "unknown")

        ctx = ResponseContext(
            scene=self.scene,
            agent_id=agent_id,
            agent_name=agent_name,
            user_message=user_message,
            system_prompt="",
            messages=[],
            reply="",
            skill_manifest=manifest,
            policy=self.policy,
            game_state={},
            auto_results={},
            abort=False,
            skip_llm=False,
            history=history or [],
            chain_id=chain_id,
        )

        # ── 2. Execute AUTO skills ───────────────────────────────────
        for skill_entry in manifest.auto_skills():
            try:
                result = _invoke_mcp_tool(
                    skill_entry.name, skill_entry.args_template, ctx
                )
                ctx["auto_results"][skill_entry.name] = result
                logger.debug("Auto skill %s: %s", skill_entry.name, str(result)[:80])
            except Exception as exc:
                logger.debug("Auto skill %s failed: %s", skill_entry.name, exc)

        # ── 3. Pre-call pipeline ─────────────────────────────────────
        bus = self._get_bus()
        with bus.activity(
            "thinking",
            f"{agent_name} is thinking…",
            agent_id=agent_id,
            scene=self.scene,
        ):
            self.pipeline.run_pre(ctx)

            if ctx.get("skip_llm"):
                return ctx.get("reply", "")

        # ── 4. LLM call ──────────────────────────────────────────────
        with bus.activity(
            "llm_call",
            f"{agent_name}: generating reply",
            agent_id=agent_id,
            scene=self.scene,
        ):
            try:
                # Pass interceptor-built context to the agent
                gov_ctx = ctx.get("system_prompt", "").strip() or None
                reply = self.agent.reply(
                    user_message,
                    chain_id=ctx.get("chain_id"),
                    history=ctx.get("history"),
                    governance_context=gov_ctx,
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
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)
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
            except Exception as exc:
                logger.error("AgentGovernor LLM call failed: %s", exc)
                ctx["reply"] = ""

        # ── 5. Parse response (single pass — v3.1) ─────────────────────
        reply = ctx.get("reply", "")
        if reply:
            ctx["parsed"] = ContentRouter.parse_full(reply)

        # ── 6. Post-call pipeline ────────────────────────────────────
        self.pipeline.run_post(ctx)

        return ctx.get("reply", "")

    def _get_bus(self):
        if self._bus is None:
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
        manifest = self._manifest.get(self.scene)
        agent_name = (
            getattr(self.character, "name", "Agent") if self.character else "Agent"
        )
        agent_id = (
            getattr(self.character, "id", "unknown") if self.character else "unknown"
        )
        ctx = ResponseContext(
            scene=self.scene,
            agent_id=agent_id,
            agent_name=agent_name,
            user_message=user_message,
            system_prompt="",
            messages=[],
            reply="<<DRY RUN — LLM NOT CALLED>>",
            skill_manifest=manifest,
            policy=self.policy,
            game_state={},
            auto_results={},
            abort=False,
            skip_llm=True,
            history=[],
            chain_id=None,
        )
        self.pipeline.run_pre(ctx)
        return dict(ctx)


def _invoke_mcp_tool(tool_name: str, args: Dict, ctx: ResponseContext) -> Any:
    """Call a tool function by name via the MCP registry."""
    import engine.mcp.cosysim_server as srv

    fn = getattr(srv, tool_name, None)
    if fn is None:
        # Try the comms tools module
        try:
            import engine.mcp.comms_tools as ct

            fn = getattr(ct, tool_name, None)
        except ImportError:
            logger.debug("Suppressed exception", exc_info=True)
    if fn is None:
        raise ValueError(f"Tool {tool_name!r} not found in MCP server or comms_tools")
    return fn(**args)


def _build_default_pipeline() -> InterceptorPipeline:
    """Build the default interceptor pipeline for new governors."""
    pipeline = InterceptorPipeline()
    from engine.agents.interceptors import InterceptorRegistry

    for interceptor in InterceptorRegistry.discover_and_instantiate():
        pipeline.add(interceptor)
    return pipeline


# ══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETONS
# ══════════════════════════════════════════════════════════════════════

_manifest: Optional[SkillManifest] = None
_game_state: Optional[GameState] = None
_router: Optional[AgentRouter] = None
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
