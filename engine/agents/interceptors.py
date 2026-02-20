"""
CosySim Agent Interceptors
===========================

Concrete interceptors for the ``InterceptorPipeline``.  Each one focuses on
a single concern and composes cleanly with the others.

Execution order (by priority):
  10  RouterMessageInjector   — inject inbox messages from other agents
  20  AutoResultInjector      — inject auto-skill results into system prompt
  30  SkillAwarenessInterceptor — build the "available skills" list for the LLM
  40  GameRulesInterceptor    — inject game-specific rules and required tools
  50  PersonalityGuardInterceptor — add in-character reminders and tone guidance
  60  PolicyEnforcerInterceptor   — enforce reply length, forbidden topics
  70  MemoryEnhancerInterceptor   — augment context with extra RAG results
  80  ResponseShaperInterceptor   — post-call: trim/reshape reply to match policy
  90  ActivityLoggerInterceptor   — post-call: log final reply to EventChain

Adding your own::

    from engine.agents.interceptors import InterceptorBase
    from engine.mcp.comms_framework import get_governor

    class MyHook(InterceptorBase):
        name = "my_hook"
        priority = 45

        def pre_call(self, ctx):
            ctx["system_prompt"] += "\\nAlways end with a question."

    gov = get_governor(agent, scene="phone")
    gov.pipeline.add(MyHook())
"""
from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Optional

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  RouterMessageInjector  (priority 10)
# ══════════════════════════════════════════════════════════════════════

class RouterMessageInjector(InterceptorBase):
    """
    Pre-call: drain any pending agent-router inbox messages and
    inject them into the user message context so the character
    sees them as additional context to react to.
    """
    name     = "router_messages"
    priority = 10

    def pre_call(self, ctx: ResponseContext) -> None:
        from engine.mcp.comms_framework import get_router
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return
        router = get_router()
        pending = router.drain(agent_id)
        if not pending:
            return
        lines = [f"[incoming from {m['sender']}]: {m['message']}" for m in pending]
        extra = "\n".join(lines)
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n--- Messages received from other agents ---\n{extra}\n---"
        )
        logger.debug("RouterMessageInjector: injected %d message(s) for %s", len(pending), agent_id)


# ══════════════════════════════════════════════════════════════════════
#  AutoResultInjector  (priority 20)
# ══════════════════════════════════════════════════════════════════════

class AutoResultInjector(InterceptorBase):
    """
    Pre-call: take results from auto-triggered skills (already stored in
    ``ctx['auto_results']``) and append them as a structured context block
    in the system prompt.
    """
    name     = "auto_results"
    priority = 20

    def pre_call(self, ctx: ResponseContext) -> None:
        auto_results: Dict[str, Any] = ctx.get("auto_results", {})
        if not auto_results:
            return
        lines = []
        for skill_name, result in auto_results.items():
            snippet = str(result)[:300]
            lines.append(f"[{skill_name}] {snippet}")
        block = "\n".join(lines)
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n--- Automatic context (from skills) ---\n{block}\n---"
        )


# ══════════════════════════════════════════════════════════════════════
#  SkillAwarenessInterceptor  (priority 30)
# ══════════════════════════════════════════════════════════════════════

class SkillAwarenessInterceptor(InterceptorBase):
    """
    Pre-call: inject a "skills available to you" section into the system prompt
    so the model knows what tools it can call and why.

    Required skills get a strong instruction to call them before replying.
    Optional skills get a suggestion.
    """
    name     = "skill_awareness"
    priority = 30

    def pre_call(self, ctx: ResponseContext) -> None:
        manifest = ctx.get("skill_manifest")
        if manifest is None:
            return

        optional_skills  = manifest.optional_skills()
        required_skills  = manifest.required_skills()

        parts: List[str] = []

        if required_skills:
            names = ", ".join(f"`{s.name}`" for s in required_skills)
            descs = "\n".join(
                f"  • {s.name}: {s.description}" for s in required_skills
            )
            parts.append(
                f"REQUIRED: You MUST call the following tools before answering:\n{descs}\n"
                f"Do not reply until you have called: {names}."
            )

        if optional_skills:
            descs = "\n".join(
                f"  • {s.name}: {s.description}" for s in optional_skills
            )
            parts.append(
                f"AVAILABLE TOOLS (use when relevant):\n{descs}"
            )

        if parts:
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                "\n\n--- Skills & Tools ---\n" + "\n\n".join(parts) + "\n---"
            )


# ══════════════════════════════════════════════════════════════════════
#  GameRulesInterceptor  (priority 40)
# ══════════════════════════════════════════════════════════════════════

class GameRulesInterceptor(InterceptorBase):
    """
    Pre-call: if a game is active in the current scene, inject its rules
    and current state into the system prompt.

    Post-call: check if the reply triggers any game state transitions.
    """
    name     = "game_rules"
    priority = 40

    # Game definitions  ─────────────────────────────────────────────
    GAME_RULES: Dict[str, str] = {
        "truth_or_dare": (
            "You are playing Truth or Dare! Rules:\n"
            "1. On each turn, roll the dice (call `roll_dice`). "
            "Odd = Truth, Even = Dare.\n"
            "2. Give the user a truth question OR a dare based on your roll.\n"
            "3. If they complete it, call `set_game_state` to record the result "
            "and increment the score.\n"
            "4. Keep track of the round with `get_game_state`.\n"
            "5. After 10 rounds, tally the score and declare a winner.\n"
            "Make it playful, escalate intensity gradually."
        ),
        "mystery": (
            "You are running a mystery investigation game! Rules:\n"
            "1. The player is investigating a mystery — guide them with clues.\n"
            "2. Use `search_memory` to find relevant clues from past sessions.\n"
            "3. Use `get_random_topic` to generate new clue ideas.\n"
            "4. When the player discovers a clue, call `set_game_state` to record it.\n"
            "5. Check `get_game_state` to know what clues they've found so far.\n"
            "6. The player wins by finding all 5 clues and naming the culprit.\n"
            "Build suspense, be cryptic, reward deduction."
        ),
    }

    def pre_call(self, ctx: ResponseContext) -> None:
        from engine.mcp.comms_framework import get_game_state
        gs = get_game_state()
        scene = ctx.get("scene", "")

        # Find active game for this scene
        game_id = None
        for gid in gs.all_games():
            if gs.get(gid, "scene") == scene and gs.get(gid, "active"):
                game_id = gid
                break

        if game_id is None:
            return

        rules = self.GAME_RULES.get(game_id, "")
        state = gs.get_all(game_id)
        ctx["game_state"] = state

        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n--- GAME: {game_id.upper()} ---\n"
            f"{rules}\n"
            f"Current state: {json.dumps(state, indent=2)}\n---"
        )


# ══════════════════════════════════════════════════════════════════════
#  PersonalityGuardInterceptor  (priority 50)
# ══════════════════════════════════════════════════════════════════════

class PersonalityGuardInterceptor(InterceptorBase):
    """
    Pre-call: append in-character reminders based on the character's
    personality traits and the interaction policy's required tone.
    """
    name     = "personality_guard"
    priority = 50

    def pre_call(self, ctx: ResponseContext) -> None:
        policy: Any = ctx.get("policy")
        if policy is None:
            return

        reminders: List[str] = []

        if policy.enforce_in_character:
            reminders.append("Stay fully in-character at all times.")

        if policy.required_tone:
            reminders.append(f"Your tone should be: {policy.required_tone}.")

        if policy.forbidden_topics:
            topics = ", ".join(policy.forbidden_topics)
            reminders.append(f"Never discuss: {topics}.")

        if policy.append_to_system:
            reminders.append(policy.append_to_system)

        if reminders:
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                "\n\n" + "  ".join(reminders)
            )


# ══════════════════════════════════════════════════════════════════════
#  PolicyEnforcerInterceptor  (priority 60)
# ══════════════════════════════════════════════════════════════════════

class PolicyEnforcerInterceptor(InterceptorBase):
    """
    Pre-call: inject token-budget instruction so the model knows the expected
    reply length.
    """
    name     = "policy_enforcer"
    priority = 60

    def pre_call(self, ctx: ResponseContext) -> None:
        policy: Any = ctx.get("policy")
        if policy is None:
            return
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\nKeep your reply between {policy.min_reply_tokens} and "
            f"{policy.max_reply_tokens} tokens."
        )


# ══════════════════════════════════════════════════════════════════════
#  MemoryEnhancerInterceptor  (priority 70)
# ══════════════════════════════════════════════════════════════════════

class MemoryEnhancerInterceptor(InterceptorBase):
    """
    Pre-call: run an additional RAG search targeting the current user message
    and append any *highly relevant* extra memories (beyond what CharacterAgent
    already injects) as a supplemental context block.

    Disabled by default (add to pipeline explicitly when deep recall matters).
    """
    name     = "memory_enhancer"
    priority = 70

    def __init__(self, top_k: int = 3) -> None:
        super().__init__()
        self.top_k = top_k

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return
        user_msg = ctx.get("user_message", "")
        if not user_msg:
            return
        try:
            from content.simulation.database.rag import RAGMemory
            rag = RAGMemory()
            results = rag.search(user_msg, n_results=self.top_k, character_id=agent_id)
            if results:
                snippets = []
                for r in results:
                    text = r.get("content", str(r)) if isinstance(r, dict) else str(r)
                    snippets.append(f"• {text[:200]}")
                block = "\n".join(snippets)
                ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                    f"\n\n--- Enhanced memory context ---\n{block}\n---"
                )
        except Exception as exc:
            logger.debug("MemoryEnhancerInterceptor failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  ResponseShaperInterceptor  (priority 80)
# ══════════════════════════════════════════════════════════════════════

class ResponseShaperInterceptor(InterceptorBase):
    """
    Post-call: trim excessively long replies and strip any leaked system
    instructions that sometimes appear at the end of responses.
    """
    name     = "response_shaper"
    priority = 80

    # Markers that sometimes leak from system prompts
    _LEAK_MARKERS = [
        "--- Skills", "--- Messages received", "--- Automatic context",
        "--- GAME:", "--- Enhanced memory", "REQUIRED:", "AVAILABLE TOOLS",
        "Stay fully in-character",
    ]

    def post_call(self, ctx: ResponseContext) -> None:
        reply: str = ctx.get("reply", "")
        if not reply:
            return

        # Strip leaked system sections
        for marker in self._LEAK_MARKERS:
            if marker in reply:
                reply = reply[:reply.index(marker)].rstrip()

        ctx["reply"] = reply.strip()


# ══════════════════════════════════════════════════════════════════════
#  ActivityLoggerInterceptor  (priority 90)
# ══════════════════════════════════════════════════════════════════════

class ActivityLoggerInterceptor(InterceptorBase):
    """
    Post-call: log the completed interaction to the EventChain with
    governance metadata (which interceptors ran, skill manifest name, etc.).
    """
    name     = "activity_logger"
    priority = 90

    def post_call(self, ctx: ResponseContext) -> None:
        chain_id   = ctx.get("chain_id")
        agent_id   = ctx.get("agent_id", "")
        agent_name = ctx.get("agent_name", "?")
        reply      = ctx.get("reply", "")
        if not chain_id or not reply:
            return
        try:
            from content.simulation.database.events import get_event_chain
            ec = get_event_chain()
            if ec:
                ec.log(
                    "governed_response",
                    actor=agent_name,
                    payload={
                        "scene": ctx.get("scene"),
                        "skills_auto": list(ctx.get("auto_results", {}).keys()),
                        "game_active": bool(ctx.get("game_state")),
                    },
                    summary=reply[:120],
                    chain_id=chain_id,
                    character_id=agent_id,
                )
        except Exception as exc:
            logger.debug("ActivityLoggerInterceptor failed: %s", exc)
