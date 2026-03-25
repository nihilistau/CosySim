"""
Heat Awareness Interceptor — Inject wanted/heat level into agent prompts
========================================================================

Pre-call interceptor (priority 75) that reads the player's heat level
from PlayerState and injects context so NPCs react to the player's
notoriety. Guards become suspicious, fixers charge more, allies warn.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial implementation

CONNECTS: PlayerState, AgentGovernor
CALLED BY: InterceptorPipeline (pre_call, priority 75)
EMITS: Nothing (prompt injection only)
"""
from __future__ import annotations

import logging

from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ──── Heat Level Thresholds ──────────────────────────────────────────────

# Heat ranges (0-100) and their effects
_HEAT_LEVELS = [
    (80, "CRITICAL", (
        "The player is EXTREMELY WANTED. Law enforcement and corporate security are "
        "actively hunting them. If you are a guard, security, or authority figure: be "
        "aggressive, demand identification, threaten arrest. If you are a friend or ally: "
        "express genuine concern, warn them to lay low, maybe refuse to be seen with them "
        "in public. If you are a merchant: charge premium prices (double), or refuse service "
        "entirely — you don't want the heat."
    )),
    (60, "HIGH", (
        "The player has high heat — they're known to authorities and corps. Guards give "
        "them hard looks. Merchants nervously adjust prices upward. Friends suggest they "
        "'cool off for a while.' Reference their reputation in conversation naturally — "
        "'You've been making waves' or 'People are talking about what you did.'"
    )),
    (40, "MODERATE", (
        "The player has moderate heat — some attention from authorities. Guards are watchful "
        "but not hostile. Fixers might mention 'keeping a low profile.' Merchants don't "
        "refuse service but might be slightly wary. A subtle background tension."
    )),
    (20, "LOW", (
        "The player has some heat but nothing serious. Most NPCs don't notice or care. "
        "A perceptive character might mention 'heard you had some trouble' in passing. "
        "No behavioral changes needed."
    )),
    (0, "CLEAN", None),  # No injection needed
]

# Character archetypes that react strongly to heat
_AUTHORITY_TYPES = {"guard", "security", "officer", "detective", "corporate", "exec", "police"}
_CRIMINAL_TYPES = {"fixer", "dealer", "smuggler", "thief", "hacker", "crime", "boss", "syndicate"}
_MERCHANT_TYPES = {"merchant", "vendor", "shopkeeper", "bartender", "trader"}


def _get_character_type(agent_id: str) -> str:
    """Infer character archetype from agent_id for heat response tuning."""
    agent_lower = agent_id.lower()
    for word in _AUTHORITY_TYPES:
        if word in agent_lower:
            return "authority"
    for word in _CRIMINAL_TYPES:
        if word in agent_lower:
            return "criminal"
    for word in _MERCHANT_TYPES:
        if word in agent_lower:
            return "merchant"
    return "civilian"


# ──── Interceptor ────────────────────────────────────────────────────────

class HeatAwarenessInterceptor(InterceptorBase):
    """Inject heat/wanted level context into agent system prompts.

    At priority 75 (after memory enhancer, before response shaper),
    this interceptor reads the player's heat level and injects guidance
    so NPCs naturally react to notoriety.
    """

    name = "heat_awareness"
    priority = 75

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject heat awareness before LLM call."""
        try:
            from engine.world.player_state import get_player_state

            player = get_player_state()
            heat = getattr(player, "heat", 0)

            if heat < 20:
                return  # Clean — no injection needed

            # Find the matching heat level
            heat_label = "CLEAN"
            heat_guidance = None
            for threshold, label, guidance in _HEAT_LEVELS:
                if heat >= threshold:
                    heat_label = label
                    heat_guidance = guidance
                    break

            if not heat_guidance:
                return

            # Build context block
            agent_id = ctx.get("agent_id", "")
            char_type = _get_character_type(agent_id)

            lines = [f"[HEAT LEVEL: {heat_label} ({heat}/100)]"]
            lines.append(heat_guidance)

            # Type-specific additions
            if char_type == "authority" and heat >= 60:
                lines.append(
                    "As an authority figure, you take heat VERY seriously. "
                    "Consider confronting the player directly about their activities."
                )
            elif char_type == "criminal" and heat >= 40:
                lines.append(
                    "As someone in the underground, high heat is bad for business. "
                    "The player's heat could draw attention to YOUR operations. "
                    "You might demand they take care of it before you'll work with them."
                )
            elif char_type == "merchant" and heat >= 60:
                lines.append(
                    "You're a business owner. A wanted criminal in your shop is bad for you. "
                    "Increase prices, rush the transaction, or suggest they come back 'when things cool down.'"
                )

            heat_block = "\n".join(lines)
            system = ctx.get("system_prompt", "")
            ctx["system_prompt"] = system + "\n\n" + heat_block

        except Exception as exc:
            logger.debug("[HeatAwareness] Injection failed (non-fatal): %s", exc)
