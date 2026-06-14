"""
Spectator Broadcast Interceptor — broadcasts agent replies as danmaku
=====================================================================

Post-call interceptor (priority 92) that fires after mood_sync has
parsed the reply.  Extracts the reply text (first 100 chars), mood,
scene, and agent name, then broadcasts a SpectatorMessage via the
SpectatorBus for the danmaku overlay.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial implementation: post_call extraction,
                            mood-based color mapping, SpectatorBus broadcast

CONNECTS: SpectatorBus, MoodSyncInterceptor (runs after mood_sync)
CALLED BY: Interceptor pipeline (post_call phase, priority 92)
EMITS:     SpectatorBus.broadcast() → danmaku_msg SocketIO events
"""
from __future__ import annotations

import logging

from engine.mcp.comms_framework import InterceptorBase, ResponseContext
from engine.services.spectator_bus import (
    DEFAULT_COLOR,
    MOOD_COLORS,
    SpectatorMessage,
    get_spectator_bus,
)

logger = logging.getLogger(__name__)

# Maximum characters of reply text to include in a danmaku message
_MAX_TEXT_LEN = 100


class SpectatorBroadcastInterceptor(InterceptorBase):
    """Broadcast agent replies as danmaku spectator messages.

    Runs at priority 92 (post-call, alongside mood_sync) so that the
    parsed mood data is available for color selection.

    CONNECTS: SpectatorBus, ParsedResponse (ctx["parsed"])
    CALLED BY: InterceptorPipeline post_call phase
    EMITS:     SpectatorBus.broadcast(SpectatorMessage)
    """
    name = "spectator_broadcast"
    priority = 92

    # v1.51.0 [2026-03-25] — Post-call: extract reply + mood, broadcast as danmaku
    def post_call(self, ctx: ResponseContext) -> None:
        """Extract reply metadata and broadcast as a SpectatorMessage.

        Args:
            ctx: The mutable ResponseContext with reply, agent_id, scene, parsed data.
        """
        reply = ctx.get("reply", "")
        agent_id = ctx.get("agent_id", "")
        if not reply:
            return

        # Truncate reply text for overlay readability
        text = reply[:_MAX_TEXT_LEN]
        if len(reply) > _MAX_TEXT_LEN:
            text += "..."

        # Determine display name — prefer agent_name, fall back to agent_id
        agent_name = ctx.get("agent_name", "") or agent_id
        if agent_name:
            text = f"{agent_name}: {text}"

        # Pick color from mood (via pre-parsed data from MoodSyncInterceptor)
        color = DEFAULT_COLOR
        parsed = ctx.get("parsed")
        mood = ""
        if parsed is not None:
            mood = getattr(parsed, "mood", "") or ""
        if mood:
            color = MOOD_COLORS.get(mood.lower(), DEFAULT_COLOR)

        scene = ctx.get("scene", "")

        # Determine message kind based on available metadata
        kind = "chat"
        if parsed is not None:
            actions = getattr(parsed, "actions", None)
            if actions:
                kind = "action"

        msg = SpectatorMessage(
            kind=kind,
            text=text,
            agent_id=agent_id,
            scene=scene,
            color=color,
        )

        try:
            get_spectator_bus().broadcast(msg)
        except Exception as exc:
            logger.debug(
                "[SpectatorBroadcast] Broadcast failed (operation=broadcast, agent=%s): %s",
                agent_id, exc,
            )
