"""Injects player relationship context into agent requests."""
from __future__ import annotations

import logging

from engine.characters.player_profile import get_player_profile
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)


class RelationshipContextInterceptor(InterceptorBase):
    """Pre-call: append player-NPC relationship context to the system prompt.

    Reads the character_id from the ResponseContext (``agent_id`` key) and
    looks up the current relationship score/sentiment in PlayerProfile.  If a
    relationship entry exists the context line is appended to the system prompt
    so the NPC is aware of how the player feels about them.

    All exceptions are caught silently — this interceptor must never break a
    conversation turn.
    """

    name = "relationship_context"
    priority = 46  # runs just after DialogueGateInterceptor (45)

    def pre_call(self, ctx: ResponseContext) -> None:
        """Append relationship context when character has an existing relationship."""
        try:
            character_id: str = ctx.get("agent_id", "") or ctx.get("character_id", "")
            if not character_id:
                return
            profile = get_player_profile()
            rel = profile.relationships.get(character_id)
            if rel is None:
                return
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                f"\n[Player relationship: {rel.sentiment} (score: {rel.score:+.1f})]"
            )
            logger.debug(
                "RelationshipContextInterceptor: injected %s relationship for %s",
                rel.sentiment,
                character_id,
            )
        except Exception:
            logger.debug(
                "RelationshipContextInterceptor.pre_call suppressed exception",
                exc_info=True,
            )

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Passthrough — no post-call processing required."""
