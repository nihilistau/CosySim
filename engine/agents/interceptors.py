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

    # ------------------------------------------------------------------ pre
    def pre_call(self, ctx: ResponseContext) -> None:  # noqa: D401
        scene = ctx.get("scene", "")
        if scene != "bedroom":
            return

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
        scene = ctx.get("scene", "")
        if scene != "phone":
            return

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
    3. Checks the DialogSystem for a ``force_response`` directive — if one is
       active it short-circuits the LLM call by writing the forced reply
       directly into ctx["reply"] and setting ctx["skip_llm"] = True.

    This makes the registry the authoritative first step for every agent turn.
    """
    name     = "character_registry"
    priority = 8

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
                lines = [
                    f"[CHARACTER IDENTITY]",
                    f"Name: {summary.get('name', agent_id)}",
                ]
                if summary.get("mood"):
                    lines.append(f"Current mood: {summary['mood']} (intensity {summary.get('mood_intensity', 0.5):.0%})")
                p = summary.get("personality", {})
                if p:
                    p_str = ", ".join(f"{k}={v:.0%}" for k, v in p.items())
                    lines.append(f"Personality: {p_str}")
                voice = summary.get("voice_style")
                if voice:
                    lines.append(f"Voice style: {voice}")
                if summary.get("restrictions"):
                    lines.append(f"Current restrictions: {', '.join(summary['restrictions'])}")
                active_skills = [s["label"] for s in summary.get("skills", []) if s.get("trigger") == "auto"]
                if active_skills:
                    lines.append(f"Auto-active skills: {', '.join(active_skills)}")
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
