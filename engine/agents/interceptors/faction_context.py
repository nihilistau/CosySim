"""
Faction Context Interceptor — Inject faction standings into agent prompts
========================================================================

Pre-call interceptor (priority 40) that reads the player's faction standings
from PlayerState and injects context so NPCs naturally adjust their tone
based on whether the player is allied, neutral, or hostile with their faction.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial implementation

CONNECTS: PlayerState, AgentGovernor, CharacterRegistry
CALLED BY: InterceptorPipeline (pre_call, priority 40)
EMITS: Nothing (prompt injection only)
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ──── Constants ──────────────────────────────────────────────────────────

# Faction standing thresholds
ALLIED_THRESHOLD = 50
FRIENDLY_THRESHOLD = 20
HOSTILE_THRESHOLD = -20
ENEMY_THRESHOLD = -50

# Map standing ranges to relationship descriptors
_STANDING_LABELS = [
    (ALLIED_THRESHOLD, "allied"),
    (FRIENDLY_THRESHOLD, "friendly"),
    (-FRIENDLY_THRESHOLD, "neutral"),
    (HOSTILE_THRESHOLD, "unfriendly"),
    (float("-inf"), "hostile"),
]

# Known factions and which characters belong to them
# Characters not in this map are treated as independent
_FACTION_CHARACTERS = {
    "omnicorp": ["corporate_exec", "omnicorp_guard", "corporate_fixer"],
    "ghost_net": ["hacker", "netrunner", "ghost_agent"],
    "iron_collective": ["enforcer", "iron_boss", "mechanic"],
    "neon_syndicate": ["syndicate_dealer", "neon_boss", "courier"],
    "free_radicals": ["activist", "rebel", "street_doc"],
    "chrome_saints": ["chrome_priest", "augmented", "body_mod"],
}


def _get_standing_label(standing: int) -> str:
    """Convert numeric standing to a human-readable label."""
    for threshold, label in _STANDING_LABELS:
        if standing >= threshold:
            return label
    return "hostile"


def _get_character_faction(character_id: str) -> Optional[str]:
    """Look up which faction a character belongs to, if any."""
    char_lower = character_id.lower()
    for faction, members in _FACTION_CHARACTERS.items():
        if char_lower in members or any(m in char_lower for m in members):
            return faction
    return None


# ──── Interceptor ────────────────────────────────────────────────────────

class FactionContextInterceptor(InterceptorBase):
    """Inject faction standing context into agent system prompts.

    At priority 40 (after scene injection, before personality guards),
    this interceptor reads the player's faction standings and injects
    a context block that tells the agent how to treat the player based
    on their reputation with the agent's faction.
    """

    name = "faction_context"
    priority = 40

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject faction context before LLM call."""
        try:
            from engine.world.player_state import get_player_state

            player = get_player_state()
            standings = getattr(player, "faction_standings", {})
            if not standings:
                return

            agent_id = ctx.get("agent_id", "")
            agent_faction = _get_character_faction(agent_id)

            # Build faction context block
            lines = ["[FACTION CONTEXT]"]

            # If the agent belongs to a faction, highlight that relationship
            if agent_faction:
                faction_standing = standings.get(agent_faction, 0)
                label = _get_standing_label(faction_standing)
                lines.append(
                    f"You are a member of {agent_faction.replace('_', ' ').title()}. "
                    f"The player's standing with your faction is {label} ({faction_standing:+d})."
                )

                if faction_standing >= ALLIED_THRESHOLD:
                    lines.append(
                        "Treat them as a valued ally. Be warm, offer help, share insider knowledge. "
                        "You trust them."
                    )
                elif faction_standing >= FRIENDLY_THRESHOLD:
                    lines.append(
                        "They're on good terms with your faction. Be cordial and professional. "
                        "Give them the benefit of the doubt."
                    )
                elif faction_standing <= ENEMY_THRESHOLD:
                    lines.append(
                        "They are an ENEMY of your faction. Be cold, suspicious, or threatening. "
                        "Don't share information freely. Consider them a threat."
                    )
                elif faction_standing <= HOSTILE_THRESHOLD:
                    lines.append(
                        "They're not welcome here. Be curt and guarded. "
                        "Don't go out of your way to help them."
                    )

            # Add overall reputation summary for context
            notable = []
            for faction, standing in sorted(standings.items(), key=lambda x: abs(x[1]), reverse=True):
                if abs(standing) >= FRIENDLY_THRESHOLD:
                    label = _get_standing_label(standing)
                    notable.append(f"{faction.replace('_', ' ').title()}: {label} ({standing:+d})")

            if notable:
                lines.append("Player faction standings: " + ", ".join(notable[:4]))

            # Inject into system prompt
            faction_block = "\n".join(lines)
            system = ctx.get("system_prompt", "")
            ctx["system_prompt"] = system + "\n\n" + faction_block

        except Exception as exc:
            logger.debug("[FactionContext] Injection failed (non-fatal): %s", exc)
