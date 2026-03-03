"""Injects player relationship context into agent requests."""
from __future__ import annotations

import logging
from typing import Optional

from engine.characters.player_profile import get_player_profile
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ──── Tier labels ────────────────────────────────────────────────────────────

def _relationship_tier(score: float) -> str:
    """Convert a relationship score (−100 to +100) to a tier label."""
    if score >= 80:
        return "INTIMATE"
    if score >= 60:
        return "CLOSE"
    if score >= 40:
        return "FRIEND"
    if score >= 20:
        return "ACQUAINTANCE"
    return "STRANGER"


class RelationshipContextInterceptor(InterceptorBase):
    """Pre-call: inject relationship tier, score, and memory snippets into system prompt.

    Reads the character_id from the ResponseContext (``agent_id`` key) and
    looks up the current relationship data in PlayerProfile.  Injects:
    - Relationship tier (STRANGER → INTIMATE)
    - Current score
    - Up to 3 recent memory notes
    - Number of past interactions

    All exceptions are caught silently — this interceptor must never break a
    conversation turn.
    """

    name = "relationship_context"
    priority = 46  # runs just after DialogueGateInterceptor (45)

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject relationship tier and memory snippets into system prompt."""
        try:
            character_id: str = ctx.get("agent_id", "") or ctx.get("character_id", "")
            if not character_id:
                return
            profile = get_player_profile()
            rel = profile.relationships.get(character_id)
            if rel is None:
                return

            tier = _relationship_tier(rel.score)
            memory_block = self._build_memory_block(character_id, rel, tier)
            ctx["system_prompt"] = ctx.get("system_prompt", "") + memory_block
            logger.debug(
                "RelationshipContextInterceptor: injected %s tier for %s (score %.1f, %d notes)",
                tier, character_id, rel.score, len(rel.notes),
            )
        except Exception:
            logger.debug(
                "RelationshipContextInterceptor.pre_call suppressed exception",
                exc_info=True,
            )

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Passthrough — no post-call processing required."""

    @staticmethod
    def _build_memory_block(character_id: str, rel: object, tier: str) -> str:
        """Build the system prompt suffix with relationship context.

        Args:
            character_id: The NPC's ID.
            rel: RelationshipEntry with score, interaction_count, notes, rel_type.
            tier: The computed tier label.

        Returns:
            Multi-line context block to append to the system prompt.
        """
        rel_type = getattr(rel, "rel_type", "stranger")
        lines = [
            f"\n[RELATIONSHIP CONTEXT — {character_id.upper()}]",
            f"Tier: {tier} | Type: {rel_type.upper()} | Score: {rel.score:+.1f} | Interactions: {rel.interaction_count}",
        ]
        # Include up to 3 most recent memory notes
        notes = getattr(rel, "notes", [])
        if notes:
            recent = notes[-3:]
            lines.append("Memory:")
            for note in recent:
                lines.append(f"  • {note}")
        lines.append("[END RELATIONSHIP CONTEXT]")
        return "\n".join(lines)
