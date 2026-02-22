"""
CosySim Agent Interceptors
===========================

Concrete interceptors for the ``InterceptorPipeline``.  Each one focuses on
a single concern and composes cleanly with the others.

Execution order (by priority):
   8  CharacterRegistryInterceptor — inject character identity/mood; handle force_response
  10  RouterMessageInjector        — inject inbox messages from other agents
  12  DialogDirectiveInterceptor   — inject must_include/style_lock; post-call verification
  15  BedroomSceneInterceptor      — inject wardrobe/stats/narrative for bedroom scene
  15  PhoneSceneInterceptor        — inject conversation heat/stats for phone scene
  20  AutoResultInjector           — inject auto-skill results into system prompt
  30  SkillAwarenessInterceptor    — build the "available skills" list for the LLM
  35  GameSessionInterceptor       — inject MCPGameSession history + actions when a game is active
  40  GameRulesInterceptor         — inject game-specific rules and required tools
  50  PersonalityGuardInterceptor  — add in-character reminders and tone guidance
  60  PolicyEnforcerInterceptor    — enforce reply length, forbidden topics
  70  MemoryEnhancerInterceptor    — augment context with extra RAG results
  80  ResponseShaperInterceptor    — post-call: trim/reshape reply to match policy
  90  ActivityLoggerInterceptor    — post-call: log final reply to EventChain

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
import time
import threading
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  Interceptor TTL cache (v3.1)
# ══════════════════════════════════════════════════════════════════════

class _InterceptorCache:
    """Thread-safe TTL cache for interceptor pre-computed outputs.

    Keyed by ``(agent_id, interceptor_name)``.  Interceptors that produce
    the same output across multiple calls (e.g. character identity, skill
    list, personality reminders) can cache here to avoid re-computation.
    """

    def __init__(self, default_ttl: float = 60.0) -> None:
        self._lock = threading.Lock()
        self._store: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._default_ttl = default_ttl

    def get(self, agent_id: str, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get((agent_id, key))
            if entry is None:
                return None
            expiry, value = entry
            if time.time() > expiry:
                del self._store[(agent_id, key)]
                return None
            return value

    def set(self, agent_id: str, key: str, value: str, ttl: Optional[float] = None) -> None:
        with self._lock:
            self._store[(agent_id, key)] = (
                time.time() + (ttl or self._default_ttl),
                value,
            )

    def invalidate(self, agent_id: str, key: Optional[str] = None) -> None:
        """Invalidate cache for an agent. If key is None, invalidate all."""
        with self._lock:
            if key:
                self._store.pop((agent_id, key), None)
            else:
                self._store = {
                    k: v for k, v in self._store.items() if k[0] != agent_id
                }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


INTERCEPTOR_CACHE = _InterceptorCache(default_ttl=60.0)


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

        # Cross-scene messages via MCPFramework
        try:
            from engine.mcp.framework import get_framework
            cross = get_framework().get_cross_scene_inbox(agent_id)
            if cross:
                for cm in cross:
                    pending.append({
                        "sender":  f"{cm['from']}@{cm['from_scene']}",
                        "message": f"[{cm['type'].upper()}] {cm['message']}",
                    })
        except Exception as exc:
            logger.debug("RouterMessageInjector: cross-scene inbox error: %s", exc)

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
#  GameSessionInterceptor  (priority 35)
# ══════════════════════════════════════════════════════════════════════

class GameInterceptor(InterceptorBase):
    """
    Unified game interceptor (v3.1 — merges GameSessionInterceptor + GameRulesInterceptor).

    Priority 35.

    Pre-call
    --------
    1. Checks for active ``MCPGameSession`` → injects session state + history
    2. Checks for active game rules → injects rules + current state

    Post-call
    ---------
    Reads ``ctx["parsed"].game_events`` to detect events and fire
    MCPGameSession log entries.
    """
    name     = "game"
    priority = 35

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
        # Part 1: MCP game session context
        try:
            from engine.mcp.game_mcp import GameSessionInterceptor as _GSI
            _GSI().pre_call(ctx)
        except Exception as exc:
            logger.debug("GameInterceptor session pre_call: %s", exc)

        # Part 2: Game rules injection
        try:
            from engine.mcp.comms_framework import get_game_state
            gs = get_game_state()
            scene = ctx.get("scene", "")

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
        except Exception as exc:
            logger.debug("GameInterceptor rules pre_call: %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:
        try:
            from engine.mcp.game_mcp import GameSessionInterceptor as _GSI
            _GSI().post_call(ctx)
        except Exception as exc:
            logger.debug("GameInterceptor post_call: %s", exc)


# Keep old names as aliases for backward compatibility
GameSessionInterceptor = GameInterceptor
GameRulesInterceptor = GameInterceptor


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
#  ConversationVarietyInterceptor  (priority 55)
# ══════════════════════════════════════════════════════════════════════

class ConversationVarietyInterceptor(InterceptorBase):
    """
    Pre-call: prevents conversation loops by tracking recent responses
    per character and injecting anti-repetition guidance.

    Also injects expressiveness instructions (emoji, adult content,
    conversation continuation) based on scene context.
    """
    name     = "conversation_variety"
    priority = 55

    # Per-agent recent response tracking (class-level shared cache)
    _recent_responses: Dict[str, List[str]] = {}  # agent_id → last N summaries
    _MAX_TRACKED = 5

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        variety_lines: List[str] = []

        # Check recent responses for repetition
        recent = self._recent_responses.get(agent_id, [])
        if len(recent) >= 2:
            topics = ", ".join(f'"{r[:50]}"' for r in recent[-3:])
            variety_lines.append(
                f"IMPORTANT: Your recent messages covered these topics: {topics}. "
                "Do NOT repeat these ideas. Bring up something completely new, "
                "ask a question, share a personal story, or react emotionally to "
                "what the other person said."
            )

        # Expressiveness guidance
        scene = ctx.get("scene", "")
        variety_lines.append(
            "Express yourself naturally with emojis 😏💕🔥, "
            "slang, and casual texting style. "
            "Be vivid and emotionally expressive. "
            "Always advance the conversation — never just agree or repeat. "
            "Reference earlier parts of the conversation to show you remember."
        )

        if scene in ("bedroom", "phone"):
            variety_lines.append(
                "You may be flirty, seductive, suggestive, or vulgar "
                "when the conversation naturally leads there. "
                "Don't hold back on sexual or adult topics if appropriate."
            )

        # Conversation heat directive
        try:
            from engine.mcp.scene_rules_engine import get_conversation_heat
            heat = get_conversation_heat()
            conv_key = ctx.get("conversation_id") or f"{scene}_{agent_id}"
            directive = heat.get_directive(conv_key)
            if directive:
                variety_lines.append(directive)
        except Exception as exc:
            logger.debug("ConversationVarietyInterceptor: heat directive failed: %s", exc)

        if variety_lines:
            block = "\n".join(variety_lines)
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                f"\n\n[CONVERSATION VARIETY]\n{block}\n[/CONVERSATION VARIETY]"
            )

    def post_call(self, ctx: ResponseContext) -> None:
        """Track the response for future variety checking and heat analysis."""
        agent_id = ctx.get("agent_id", "")
        reply = ctx.get("reply", "")
        if agent_id and reply:
            if agent_id not in self._recent_responses:
                self._recent_responses[agent_id] = []
            self._recent_responses[agent_id].append(reply[:80])
            # Keep only last N
            if len(self._recent_responses[agent_id]) > self._MAX_TRACKED:
                self._recent_responses[agent_id] = self._recent_responses[agent_id][-self._MAX_TRACKED:]

            # Update conversation heat based on response content
            try:
                from engine.mcp.scene_rules_engine import get_conversation_heat
                heat = get_conversation_heat()
                scene = ctx.get("scene", "")
                conv_key = ctx.get("conversation_id") or f"{scene}_{agent_id}"
                heat.analyze_message(conv_key, reply)
            except Exception as exc:
                logger.debug("ConversationVarietyInterceptor: heat analysis failed: %s", exc)


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
    Post-call: trim excessively long replies, strip leaked system
    instructions and LLM token artifacts.
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

        # Strip LLM special token artifacts
        from engine.agents.content_router import _RE_TOKEN_ARTIFACTS
        reply = _RE_TOKEN_ARTIFACTS.sub("", reply)

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


# ══════════════════════════════════════════════════════════════════════
#  BedroomSceneInterceptor  (priority 15)
# ══════════════════════════════════════════════════════════════════════

class BedroomSceneInterceptor(InterceptorBase):
    """
    Pre-call: loads full bedroom scene snapshot and injects wardrobe state,
    emotional/physical stats, and recent narrative into the system prompt.

    Runs at priority 15 (after RouterMessageInjector, before AutoResultInjector)
    so that downstream interceptors can see the snapshot.

    Snapshot is stored in ctx["extra"]["scene_snapshot"] for other interceptors.
    """
    name     = "bedroom_scene"
    priority = 15
    applicable_scenes = {"bedroom"}

    # ------------------------------------------------------------------ pre
    def pre_call(self, ctx: ResponseContext) -> None:  # noqa: D401

        agent_id  = ctx.get("agent_id", "")
        scene_id  = ctx.get("scene_id") or ctx.get("room_id") or "bedroom"
        char_ids: List[str] = ctx.get("character_ids") or ([agent_id] if agent_id else [])

        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()

            # ── wardrobe summary ────────────────────────────────────────────
            wardrobe_lines: list[str] = []
            for cid in char_ids:
                wd = ssm.get_wardrobe(cid)
                coverage = wd.coverage_description() if wd else "unknown"
                worn = [i.name for i in wd.worn_items()] if wd else []
                label = cid if cid != agent_id else "YOU"
                wardrobe_lines.append(
                    f"  {label}: {coverage} | wearing: {', '.join(worn) or 'nothing'}"
                )

            # ── stats summary ────────────────────────────────────────────────
            stats_lines: list[str] = []
            for cid in char_ids:
                snap = ssm.get_stats(cid)
                if snap:
                    label = cid if cid != agent_id else "YOU"
                    stats_lines.append(
                        f"  {label}: {snap.emotional_state_text()} "
                        f"(arousal={snap.arousal:.0f}, mood={snap.happiness:.0f}, "
                        f"openness={snap.openness:.0f})"
                    )

            # ── recent narrative ─────────────────────────────────────────────
            narrative_entries = ssm.get_narrative_entries(scene_id, limit=8)
            narrative = [e["event"] for e in narrative_entries]
            narrative_block = "\n".join(f"  • {e}" for e in narrative) if narrative else "  (scene just started)"

            # ── atmosphere ───────────────────────────────────────────────────
            atm = ssm.get_atmosphere(scene_id)
            atm_text = ""
            if atm:
                parts = []
                if atm.get("lighting"):  parts.append(f"lighting={atm['lighting']}")
                if atm.get("mood"):      parts.append(f"mood={atm['mood']}")
                if atm.get("music"):     parts.append(f"music={atm['music']}")
                atm_text = f"\nAtmosphere: {', '.join(parts)}" if parts else ""

            # ── inject into system prompt ────────────────────────────────────
            injection = (
                "\n\n--- BEDROOM SCENE STATE ---"
                f"{atm_text}"
                "\nClothing:"
                + ("\n" + "\n".join(wardrobe_lines) if wardrobe_lines else " (no data)")
                + "\nEmotional state:"
                + ("\n" + "\n".join(stats_lines) if stats_lines else " (no data)")
                + "\nRecent events:"
                + "\n" + narrative_block
                + "\n--- END SCENE STATE ---"
            )
            ctx["system_prompt"] = ctx.get("system_prompt", "") + injection

            # ── MCP rules engine: available actions ─────────────────────────
            mcp_actions_block = ""
            try:
                from engine.mcp.scene_rules_engine import get_rules_engine
                eng = get_rules_engine()
                for cid in char_ids:
                    snap = ssm.get_stats(cid)
                    stats_dict = snap.__dict__ if snap else {}
                    available = eng.get_available_actions(BEDROOM_SCENE_ID, stats_dict)
                    if available:
                        acts = ", ".join(
                            f"{a['id']} ({a.get('label', '')})" for a in available[:8]
                        )
                        mcp_actions_block += f"\nMCP-available actions for {cid}: {acts}"
                    # Live rules summary
                    rules_summary = eng.get_rules_summary(BEDROOM_SCENE_ID)
                    if rules_summary:
                        mcp_actions_block += f"\nScene rules: {rules_summary[:300]}"
                        break  # Same for all chars
            except Exception as exc:
                logger.debug("BedroomSceneInterceptor: MCP governance failed: %s", exc)

            if mcp_actions_block:
                ctx["system_prompt"] = ctx.get("system_prompt", "") + "\nMCP Governance:" + mcp_actions_block

            # ── store for downstream ─────────────────────────────────────────
            extra = ctx.setdefault("extra", {})
            extra["scene_snapshot"] = {
                "scene_id"         : scene_id,
                "character_ids"    : char_ids,
                "wardrobe_lines"   : wardrobe_lines,
                "stats_lines"      : stats_lines,
                "recent_narrative" : narrative,
                "atmosphere"       : atm or {},
            }

        except Exception as exc:
            logger.debug("BedroomSceneInterceptor pre_call failed: %s", exc)


BEDROOM_SCENE_ID = "bedroom"


# ══════════════════════════════════════════════════════════════════════
#  PhoneSceneInterceptor  (priority 15)
# ══════════════════════════════════════════════════════════════════════

class PhoneSceneInterceptor(InterceptorBase):
    """
    Pre-call: injects conversation heat (arousal, mood) and stat-driven
    behavioural cues into the phone-scene system prompt so agent texting
    feels authentic and evolves with the conversation.

    Also injects a one-line "current vibe" hint if stats are elevated.
    """
    name     = "phone_scene"
    priority = 15
    applicable_scenes = {"phone"}

    # Vibe hints keyed by (arousal_bucket, openness_bucket)
    _VIBE_HINTS: Dict[tuple, str] = {
        ("high", "high")  : "You are intensely engaged — flirty, forward, a little breathless.",
        ("high", "mid")   : "You feel the heat rising but still hold a hint of playful restraint.",
        ("high", "low")   : "You're aroused but guarded — mixed feelings, simmering tension.",
        ("mid",  "high")  : "You're comfortable and warm, happy to lean into wherever this goes.",
        ("mid",  "mid")   : "You're your usual self — curious, a little flirty, easy.",
        ("mid",  "low")   : "You're present but not open to anything too intense right now.",
        ("low",  "high")  : "You're relaxed, maybe a bit bored, easily amused.",
        ("low",  "mid")   : "You're calm and composed, replying at your own pace.",
        ("low",  "low")   : "You feel a bit flat today — short replies, guarded.",
    }

    @staticmethod
    def _bucket(val: float) -> str:
        if val >= 65:
            return "high"
        if val >= 35:
            return "mid"
        return "low"

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        scene_id = ctx.get("scene_id") or ctx.get("room_id") or "phone"

        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()

            snap = ssm.get_stats(agent_id) if agent_id else None
            narrative_entries = ssm.get_narrative_entries(scene_id, limit=6)
            narrative = [e["event"] for e in narrative_entries]

            lines: List[str] = []

            if snap:
                a_bucket = self._bucket(snap.arousal)
                o_bucket = self._bucket(snap.openness)
                vibe = self._VIBE_HINTS.get((a_bucket, o_bucket), "")
                if vibe:
                    lines.append(f"Current vibe: {vibe}")
                lines.append(
                    f"Your stats: arousal={snap.arousal:.0f}, happiness={snap.happiness:.0f}, "
                    f"openness={snap.openness:.0f}, affection={snap.affection:.0f}"
                )

            if narrative:
                narr_block = " | ".join(narrative[-4:])
                lines.append(f"Recent conversation context: {narr_block}")

            # ── MCP available actions ─────────────────────────────────────
            try:
                from engine.mcp.scene_rules_engine import get_rules_engine
                eng = get_rules_engine()
                if agent_id:
                    snap_for_rules = ssm.get_stats(agent_id) if agent_id else None
                    stats_dict = snap_for_rules.__dict__ if snap_for_rules else {}
                    available = eng.get_available_actions("phone", stats_dict)
                    if available:
                        acts = ", ".join(a["id"] for a in available[:6])
                        lines.append(f"MCP-available actions: {acts}")
            except Exception as exc:
                logger.debug("PhoneSceneInterceptor: MCP actions failed: %s", exc)

            if lines:
                injection = "\n\n[PHONE SCENE CONTEXT]\n" + "\n".join(lines) + "\n[/PHONE SCENE CONTEXT]"
                ctx["system_prompt"] = ctx.get("system_prompt", "") + injection

            # store for downstream
            extra = ctx.setdefault("extra", {})
            extra["scene_snapshot"] = {
                "scene_id"         : scene_id,
                "stats"            : snap.__dict__ if snap else {},
                "recent_narrative" : narrative,
            }

        except Exception as exc:
            logger.debug("PhoneSceneInterceptor pre_call failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  LoungeSceneInterceptor  (priority 15)
#  Injects: trust, heat, current song/atmosphere, available cocktails,
#  back-room status, active MCP rules, and Lola↔Viktor cross-agent note.
# ══════════════════════════════════════════════════════════════════════

class LoungeSceneInterceptor(InterceptorBase):
    """
    Pre-call: enriches Lola's and Viktor's system prompt with the live
    Velvet Lounge MCP state — heat, trust, stage performance, cocktail
    menu, back-room access, and the full set of available MCP actions so
    the LLM knows exactly what is allowed and what is restricted.
    """
    name     = "lounge_scene"
    priority = 15
    applicable_scenes = {"lounge"}

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")

        try:
            from engine.mcp.scene_state   import get_scene_state_manager
            from engine.mcp.scene_rules_engine import get_rules_engine
            from engine.mcp.character_registry import get_character_registry
            from engine.mcp.dialog_system  import get_dialog_system
            from content.scenes.lounge.lounge_mcp import (
                get_all_cocktails, SCENE_ID, LOLA_ID, VIKTOR_ID,
            )

            ssm = get_scene_state_manager()
            eng = get_rules_engine()
            reg = get_character_registry()
            ds  = get_dialog_system()

            # ── Character state ───────────────────────────────────────
            lola_state   = reg.get_state(LOLA_ID)   or {}
            viktor_state = reg.get_state(VIKTOR_ID) or {}
            guest_stats  = ssm.get_stats("guest") if hasattr(ssm, "get_stats") else None
            trust  = int((guest_stats.trust  if guest_stats else 0) or
                         lola_state.get("guest_trust", 10))
            heat   = int(lola_state.get("heat_level", 0))

            # ── Atmosphere ────────────────────────────────────────────
            atm = ssm.get_atmosphere(SCENE_ID) or {}
            atm_line = " · ".join(str(v) for v in atm.values() if v)

            # ── Narrative ─────────────────────────────────────────────
            narrative_entries = ssm.get_narrative_entries(SCENE_ID, limit=5)
            narrative = [e["event"] for e in narrative_entries]

            # ── Active directive ──────────────────────────────────────
            directive = None
            try:
                directive = ds.get_active_directive(agent_id, SCENE_ID)
            except Exception as exc:
                logger.debug("LoungeSceneInterceptor: directive lookup failed: %s", exc)

            # ── Available cocktails this trust level ──────────────────
            cocktails_avail = get_all_cocktails(trust)
            avail_names = ", ".join(
                c["name"] for c in cocktails_avail if not c.get("locked")
            )

            # ── MCP available actions ─────────────────────────────────
            available_actions: List[str] = []
            try:
                stats_dict = guest_stats.__dict__ if guest_stats else {}
                stats_dict["trust"]      = trust
                stats_dict["heat_level"] = heat
                actions = eng.get_available_actions(SCENE_ID, stats_dict)
                available_actions = [a["id"] for a in actions[:8]]
            except Exception as exc:
                logger.debug("LoungeSceneInterceptor: available actions failed: %s", exc)

            # ── Rules summary ─────────────────────────────────────────
            rules_summary = ""
            try:
                rules_summary = eng.get_rules_summary(SCENE_ID)
            except Exception as exc:
                logger.debug("LoungeSceneInterceptor: rules summary failed: %s", exc)

            # ── Cross-agent inbox ─────────────────────────────────────
            cross_note = ""
            try:
                from engine.mcp.framework import get_framework
                fw    = get_framework()
                inbox = fw.get_cross_scene_inbox(agent_id)
                if inbox:
                    msgs = [m.get("message", "") for m in inbox[:2] if m.get("message")]
                    if msgs:
                        cross_note = "Internal message: " + " / ".join(msgs)
            except Exception as exc:
                logger.debug("LoungeSceneInterceptor: cross-scene inbox failed: %s", exc)

            # ── Build injection block ─────────────────────────────────
            lines: List[str] = [
                "Scene: The Velvet Lounge, 1920s underground speakeasy.",
                f"Guest trust level: {trust}/100  |  Heat level: {heat}/100",
            ]

            if atm_line:
                lines.append(f"Atmosphere: {atm_line}")

            if avail_names:
                lines.append(f"Cocktails available at this trust: {avail_names}")

            if available_actions:
                lines.append(f"MCP-available actions: {', '.join(available_actions)}")

            if rules_summary:
                lines.append(f"Active rules: {rules_summary}")

            if directive:
                d_type = getattr(directive, "directive_type", "")
                d_val  = getattr(directive, "value", "")
                if d_type and d_val:
                    lines.append(f"Your current directive [{d_type}]: {d_val}")

            if narrative:
                lines.append("Recent lounge events: " + " | ".join(narrative[-3:]))

            if cross_note:
                lines.append(cross_note)

            if heat >= 65:
                lines.append(
                    "WARNING: heat level is dangerously high. "
                    "Keep things low-key. Do not attract attention."
                )
            elif heat >= 40:
                lines.append("Heat is elevated. Stay measured.")

            injection = "\n\n[LOUNGE MCP CONTEXT]\n" + "\n".join(lines) + "\n[/LOUNGE MCP CONTEXT]"
            ctx["system_prompt"] = ctx.get("system_prompt", "") + injection

            # Stash for downstream interceptors
            extra = ctx.setdefault("extra", {})
            extra["lounge_snapshot"] = {
                "trust": trust, "heat": heat,
                "atmosphere": atm,
                "available_actions": available_actions,
                "directive": {"type": d_type, "value": d_val} if directive else None,
            }

        except Exception as exc:
            logger.debug("LoungeSceneInterceptor pre_call failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  CharacterRegistryInterceptor  (priority 8)
# ══════════════════════════════════════════════════════════════════════

class CharacterRegistryInterceptor(InterceptorBase):
    """
    Runs BEFORE all scene interceptors (priority 8).

    pre_call
    --------
    1. Ensures the active character has a registry entry (auto-creates a stub
       if not found).
    2. Injects a compact character-summary block into the system prompt so the
       LLM always knows its own name, mood, personality, and active skills.
    3. Loads the full personality profile from the simulation DB for rich
       backstory, speech patterns, and behavioral traits.
    4. Checks the DialogSystem for a ``force_response`` directive — if one is
       active it short-circuits the LLM call by writing the forced reply
       directly into ctx["reply"] and setting ctx["skip_llm"] = True.

    This makes the registry the authoritative first step for every agent turn.
    """
    name     = "character_registry"
    priority = 8

    @staticmethod
    def _load_personality_profile(agent_id: str) -> str:
        """Load full personality profile from simulation DB."""
        try:
            from content.simulation.database.db import Database
            db = Database()
            # Try to find character in DB
            char = db.get_character(agent_id)
            if not char:
                return ""

            parts = []
            personality_id = char.get("personality_id") or char.get("personality")
            if personality_id:
                profile = db.get_personality(personality_id)
                if profile:
                    if profile.get("backstory"):
                        parts.append(f"Backstory: {profile['backstory'][:300]}")
                    if profile.get("speech_patterns"):
                        parts.append(f"Speech style: {profile['speech_patterns']}")
                    if profile.get("traits"):
                        traits = profile["traits"] if isinstance(profile["traits"], str) else ", ".join(profile["traits"])
                        parts.append(f"Core traits: {traits}")
                    if profile.get("quirks"):
                        parts.append(f"Quirks: {profile['quirks']}")
                    if profile.get("interests"):
                        parts.append(f"Interests: {profile['interests']}")

            # Character-level overrides
            if char.get("backstory") and not any("Backstory" in p for p in parts):
                parts.append(f"Backstory: {char['backstory'][:300]}")
            if char.get("description"):
                parts.append(f"Description: {char['description'][:200]}")

            if parts:
                return "--- Personality Profile ---\n" + "\n".join(parts)
        except Exception as exc:
            logger.debug("_load_personality_profile failed for %s: %s", agent_id, exc)
        return ""

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        try:
            from engine.mcp.character_registry import get_character_registry, apply_default_skills
            reg = get_character_registry()
            reg.ensure(agent_id)

            # One-time: apply default skills if the character has none yet
            existing = reg.get_skills(agent_id, enabled_only=False)
            if not existing:
                apply_default_skills(agent_id)

            summary = reg.get_character_summary(agent_id)
            if summary:
                mood       = summary.get("mood", "neutral")
                intensity  = float(summary.get("mood_intensity", 0.5))
                lines = [
                    "[CHARACTER IDENTITY]",
                    f"Name: {summary.get('name', agent_id)}",
                ]
                if mood:
                    lines.append(f"Current mood: {mood} (intensity {intensity:.0%})")
                if summary.get("top_traits"):
                    lines.append(f"Personality: {summary['top_traits']}")
                voice = summary.get("voice_style")
                if voice:
                    lines.append(f"Voice style: {voice}")
                if summary.get("restrictions"):
                    lines.append(f"Current restrictions: {', '.join(summary['restrictions'])}")
                auto_skills = summary.get("active_skills", [])
                if auto_skills:
                    lines.append(f"Active skills: {', '.join(auto_skills)}")

                # Load full personality profile from simulation DB (cached)
                cached_profile = INTERCEPTOR_CACHE.get(agent_id, "personality_profile")
                if cached_profile is None:
                    cached_profile = self._load_personality_profile(agent_id)
                    if cached_profile:
                        INTERCEPTOR_CACHE.set(agent_id, "personality_profile", cached_profile, ttl=300.0)
                if cached_profile:
                    lines.append(cached_profile)

                lines.append("[/CHARACTER IDENTITY]")
                block = "\n".join(lines)
                ctx["system_prompt"] = block + "\n\n" + ctx.get("system_prompt", "")

        except Exception as exc:
            logger.debug("CharacterRegistryInterceptor pre_call failed: %s", exc)
            return

        # ── Register character with MCPFramework + scene tracking ────
        try:
            scene = ctx.get("scene", "")
            from engine.mcp.framework import get_framework
            fw   = get_framework()
            char_node = fw.get_character(agent_id)
            if scene and char_node.current_scene != scene:
                char_node.enter_scene(scene)
        except Exception as exc:
            logger.debug("CharacterRegistryInterceptor framework enter_scene failed: %s", exc)

        # ── Check for force_response directive ──────────────────────
        try:
            scene = ctx.get("scene", "")
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            directive = ds.get_active_directive(agent_id, scene)
            if directive and directive.get("directive_type") == "force_response":
                forced = directive.get("value", "")
                if forced:
                    ctx["reply"]     = forced
                    ctx["skip_llm"]  = True
                    ds.consume_directive(agent_id, scene)
                    logger.debug("CharacterRegistryInterceptor: force_response applied for %s", agent_id)
        except Exception as exc:
            logger.debug("CharacterRegistryInterceptor directive check failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  DialogDirectiveInterceptor  (priority 12)
# ══════════════════════════════════════════════════════════════════════

class DialogDirectiveInterceptor(InterceptorBase):
    """
    Runs between CharacterRegistryInterceptor and scene interceptors (priority 12).

    pre_call
    --------
    - Injects ``must_include`` fragments and ``style_lock`` style instructions
      into the system prompt so the model naturally incorporates them.
    - Records any active style_lock in ctx so ResponseShaperInterceptor can
      reference it.

    post_call
    ---------
    - Checks if a ``must_include`` directive is active; if the fragment is
      missing from the final reply it is appended gracefully.
    - Ticks the DialogSystem conversation state (increments turn counter,
      decrements directive turns).
    """
    name     = "dialog_directive"
    priority = 12

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        scene    = ctx.get("scene", "")
        if not agent_id:
            return

        try:
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            directive = ds.get_active_directive(agent_id, scene)
            if not directive:
                return

            dtype = directive.get("directive_type", "")
            value = directive.get("value", "")

            if dtype == "must_include" and value:
                ctx.setdefault("dialog_must_include", []).append(value)
                ctx["system_prompt"] = (
                    ctx.get("system_prompt", "") +
                    f"\n\n[DIRECTIVE] Your response MUST naturally include or reference: \"{value}\". "
                    f"Work it in organically — do not quote it verbatim."
                )

            elif dtype == "style_lock" and value:
                from engine.mcp.dialog_system import SpeechStyle, _STYLE_INSTRUCTIONS
                instr = _STYLE_INSTRUCTIONS.get(value, "")
                if instr:
                    ctx["system_prompt"] = (
                        ctx.get("system_prompt", "") +
                        f"\n\n[STYLE LOCK] Respond in this style for this turn: {value.upper()} — {instr}"
                    )
                ctx["active_style_lock"] = value

            elif dtype == "topic_steer" and value:
                ctx["system_prompt"] = (
                    ctx.get("system_prompt", "") +
                    f"\n\n[DIRECTIVE] Steer the conversation toward this topic: {value}"
                )

            elif dtype == "mood_set" and value:
                ctx["system_prompt"] = (
                    ctx.get("system_prompt", "") +
                    f"\n\n[DIRECTIVE] Your mood and tone for this turn: {value}"
                )

        except Exception as exc:
            logger.debug("DialogDirectiveInterceptor pre_call failed: %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        scene    = ctx.get("scene", "")
        if not agent_id:
            return

        # ── Enforce must_include fragments ───────────────────────────
        must_list = ctx.get("dialog_must_include", [])
        reply     = ctx.get("reply", "")
        if must_list and reply:
            for fragment in must_list:
                if fragment.lower() not in reply.lower():
                    # Append gracefully
                    ctx["reply"] = reply.rstrip() + f"  ({fragment})"
                    reply = ctx["reply"]

        # ── Tick conversation state + framework consequence chains ────────
        try:
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            ds.tick(agent_id, scene)
        except Exception as exc:
            logger.debug("DialogDirectiveInterceptor post_call tick failed: %s", exc)

        try:
            from engine.mcp.framework import get_framework
            fired = get_framework().tick(scene)
            if fired:
                for item in fired:
                    logger.debug(
                        "DialogDirectiveInterceptor: consequence fired: %s",
                        item.get("consequence_id")
                    )
                ctx.setdefault("fired_consequences", []).extend(fired)
        except Exception as exc:
            logger.debug("DialogDirectiveInterceptor framework tick failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  TTSStyleInterceptor  (priority 85)
#  Post-call: annotate the reply with a TTS emotion hint and voice style
#  tags so CosyVoice / Qwen3-TTS picks up the right prosody.
# ══════════════════════════════════════════════════════════════════════

class TTSStyleInterceptor(InterceptorBase):
    """
    Post-call: attach TTS rendering metadata to ``ctx["tts_meta"]``.

    The metadata is a dict with keys:
    * ``emotion``    — primary emotion label for CosyVoice instruction mode
    * ``speed``      — float multiplier (1.0 = normal)
    * ``style_lock`` — style tag from ``DialogDirectiveInterceptor`` (if any)
    * ``voice_id``   — character voice id from CharacterRegistry (if configured)

    Scene UIs can read ``ctx["tts_meta"]`` after the governor call to drive
    voice synthesis.  Does NOT modify the reply text.
    """
    name     = "tts_style"
    priority = 85

    # Maps mood keyword → CosyVoice-compatible emotion label
    _MOOD_EMOTION: Dict[str, str] = {
        "happy":    "happy",
        "excited":  "happy",
        "sad":      "sad",
        "angry":    "angry",
        "fearful":  "fearful",
        "surprised":"surprised",
        "disgust":  "disgusted",
        "tender":   "tender",
        "romantic": "tender",
        "flirty":   "happy",
        "mischievous": "happy",
        "tired":    "sad",
        "calm":     "neutral",
        "neutral":  "neutral",
    }

    def post_call(self, ctx: ResponseContext) -> None:
        reply     = ctx.get("reply", "")
        agent_id  = ctx.get("agent_id", "")
        scene     = ctx.get("scene", "")
        if not reply:
            return

        # ── Determine emotion from character registry mood ────────────
        emotion = "neutral"
        speed   = 1.0
        voice_id = ""
        try:
            from engine.mcp.character_registry import get_character_registry
            reg     = get_character_registry()
            summary = reg.get_character_summary(agent_id)
            if summary:
                mood      = str(summary.get("mood") or "neutral").lower()
                emotion   = self._MOOD_EMOTION.get(mood, "neutral")
                intensity = float(summary.get("mood_intensity", 0.5))
                # Higher intensity → slightly faster delivery
                speed    = 1.0 + (intensity - 0.5) * 0.2
                voice_id = summary.get("voice_id", "") or ""

            # Fallback: if registry has no voice_id, try voices.yaml by agent_id
            if not voice_id and agent_id:
                try:
                    from engine.config import get_config
                    voices_cfg = get_config().get("voices", {})
                    if isinstance(voices_cfg, dict) and agent_id in voices_cfg:
                        voice_id = agent_id
                except Exception as exc:
                    logger.debug("TTSStyleInterceptor: voice config lookup failed: %s", exc)
        except Exception as exc:
            logger.debug("TTSStyleInterceptor: registry lookup failed: %s", exc)

        # ── Inherit style_lock from DialogDirectiveInterceptor ────────
        style_lock = ctx.get("active_style_lock", "")

        # ── Heuristic: scan reply text for emotion cues ───────────────
        reply_lower = reply.lower()
        for keyword, emo in self._MOOD_EMOTION.items():
            if keyword in reply_lower:
                emotion = emo
                break

        ctx["tts_meta"] = {
            "emotion":    emotion,
            "speed":      round(speed, 2),
            "style_lock": style_lock,
            "voice_id":   voice_id,
            "scene":      scene,
        }


# ══════════════════════════════════════════════════════════════════════
#  MoodSyncInterceptor  (priority 92)
#  Post-call: detect mood shifts in the LLM reply and sync them back to
#  CharacterRegistry so future turns see an updated mood.
# ══════════════════════════════════════════════════════════════════════

class MoodSyncInterceptor(InterceptorBase):
    """
    Post-call: read mood data from ``ctx["parsed"]`` (a ``ParsedResponse``)
    and push back to the CharacterRegistry.

    If ``ctx["parsed"]`` is not populated (legacy path), falls back to
    ``ContentRouter.parse_full()`` on the raw reply.

    The mood tag is already stripped from ``parsed.content``.
    """
    name     = "mood_sync"
    priority = 92

    def post_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        reply    = ctx.get("reply", "")
        if not reply or not agent_id:
            return

        # Use pre-parsed data if available, otherwise parse now
        parsed = ctx.get("parsed")
        if parsed is None:
            from engine.agents.content_router import ContentRouter
            parsed = ContentRouter.parse_full(reply)
            ctx["parsed"] = parsed

        if not parsed.mood:
            return

        # Update reply with clean text (tags already stripped)
        ctx["reply"] = parsed.content

        intensity = parsed.mood_intensity if parsed.mood_intensity is not None else 0.6

        try:
            from engine.mcp.character_registry import get_character_registry
            get_character_registry().set_state(
                agent_id,
                mood           = parsed.mood,
                mood_intensity = intensity,
            )
            logger.debug(
                "MoodSyncInterceptor: %s → mood=%s (%.0f%%)",
                agent_id, parsed.mood, intensity * 100,
            )
        except Exception as exc:
            logger.debug("MoodSyncInterceptor: registry update failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
#  Module exports
# ══════════════════════════════════════════════════════════════════════

__all__ = [
    # Priority order
    "CharacterRegistryInterceptor",    #  8
    "RouterMessageInjector",           # 10
    "DialogDirectiveInterceptor",      # 12
    "BedroomSceneInterceptor",         # 15
    "PhoneSceneInterceptor",           # 15
    "LoungeSceneInterceptor",          # 15
    "AutoResultInjector",              # 20
    "SkillAwarenessInterceptor",       # 30
    "GameInterceptor",                 # 35 (merged session + rules)
    "GameSessionInterceptor",          # alias → GameInterceptor
    "GameRulesInterceptor",            # alias → GameInterceptor
    "PersonalityGuardInterceptor",     # 50
    "PolicyEnforcerInterceptor",       # 60
    "MemoryEnhancerInterceptor",       # 70
    "ResponseShaperInterceptor",       # 80
    "TTSStyleInterceptor",             # 85
    "ActivityLoggerInterceptor",       # 90
    "MoodSyncInterceptor",             # 92
    # v3.1 utilities
    "INTERCEPTOR_CACHE",
    # Constant for scene ID
    "BEDROOM_SCENE_ID",
]
