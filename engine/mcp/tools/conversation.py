"""MCP tool domain: conversation.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── CONVERSATION TOOLS ─────────────────────────────────────────────────


@mcp_tool
def cross_scene_message(
    from_char:    str,
    from_scene:   str,
    to_char:      str,
    to_scene:     str,
    message:      str,
    message_type: str = "text",
) -> str:
    """
    **CROSS-SCENE BRIDGE** — Send a message from a character in one scene to a
    character in a *different* scene.

    This is how two agents in separate scenes communicate — phone calls while
    in the bedroom, texts while in different locations, notifications that cross
    scene boundaries.

    The message lands in the target character's inbox and is injected into their
    next turn via the ``RouterMessageInjector``.  Their scene is also notified.

    Message types:
      text              — standard text message
      call_notification — "incoming call" notification
      event             — system-level event crossing scenes
      system            — director/framework event

    Example: Aria in the bedroom texts the user in the phone scene:
      cross_scene_message("aria", "bedroom", "user", "phone",
                          "Thinking about last night... 🔥", "text")

    Args:
        from_char:    Sending character ID
        from_scene:   Sending character's current scene
        to_char:      Receiving character ID
        to_scene:     Receiving character's current scene
        message:      The message content
        message_type: text | call_notification | event | system
    """
    try:
        from engine.mcp.tools.utility_tools import cross_scene_message_logic as _impl
        return _impl(from_char, from_scene, to_char, to_scene, message,
                     message_type=message_type)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_cross_scene_inbox(character_id: str) -> str:
    """
    **CROSS-SCENE BRIDGE** — Check for unread cross-scene messages for a character.
    Messages are marked as read once retrieved.

    Call this at the start of a character's turn if they might have received
    cross-scene messages (phone calls, texts from other scenes, etc.)

    Args:
        character_id: The character whose inbox to check
    """
    try:
        from engine.mcp.tools.utility_tools import get_cross_scene_inbox_logic as _impl
        return _impl(character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def query_stateless(prompt: str, system: str = "") -> str:
    """
    Make a disposable one-off LLM query (store=false).
    Use this for quick decisions, classifications, or utility tasks
    that shouldn't affect the conversation state.
    Returns the raw response text.
    """
    try:
        from engine.agents.scene_agent import get_scene_agent
        agent = get_scene_agent()
        if system:
            agent.system_prompt = system
        return agent.run(prompt, max_tokens=500, store=False)
    except Exception as e:
        return f"Stateless query failed: {e}"


@mcp_tool
def get_conversation_info(conversation_id: str) -> str:
    """
    Get information about a conversation including response history
    and available branch points.
    Returns JSON with conversation state and forkable response IDs.
    """
    try:
        from engine.lmstudio.conversation import get_conversation_manager
        cm = get_conversation_manager()
        conv = cm.get(conversation_id)
        if not conv:
            return json.dumps({"error": f"No conversation '{conversation_id}'"})
        history = getattr(conv, "_response_id_history", [])
        return json.dumps({
            "conversation_id": conversation_id,
            "model": conv.model or "default",
            "is_synced": conv.is_synced,
            "response_id": conv.response_id or "",
            "message_count": len(conv.messages),
            "response_history": history,
            "can_branch": len(history) > 0,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def fork_conversation(conversation_id: str, turn: int = -1) -> str:
    """
    Create a conversation branch from a specific turn.
    Use this to try alternative approaches or undo to a previous point.
    Turn -1 means branch from the latest point.
    Returns the new forked conversation ID.
    """
    try:
        from engine.lmstudio.conversation import get_conversation_manager
        cm = get_conversation_manager()
        conv = cm.get(conversation_id)
        if not conv:
            return json.dumps({"error": f"No conversation '{conversation_id}'"})

        if turn >= 0 and hasattr(conv, "branch_at"):
            forked = conv.branch_at(turn)
        elif hasattr(conv, "fork"):
            forked = conv.fork()
        else:
            return json.dumps({"error": "Conversation does not support branching"})

        new_id = f"{conversation_id}_fork_{turn}"
        cm._conversations[new_id] = forked
        return json.dumps({
            "success": True,
            "original_id": conversation_id,
            "forked_id": new_id,
            "branch_turn": turn,
            "message_count": len(forked.messages),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def bump_conversation_heat(
    conversation_id: str,
    amount: float = 10,
    reason: str = "",
) -> str:
    """
    Manually increase conversation heat level.
    Use during flirty, intimate, or emotionally charged exchanges.
    Returns the new heat level.
    """
    try:
        from engine.mcp.scene_rules_engine import get_conversation_heat
        heat = get_conversation_heat()
        new_level = heat.bump(conversation_id, amount, reason)
        return json.dumps({
            "conversation_id": conversation_id,
            "heat": round(new_level, 1),
            "bumped_by": amount,
            "reason": reason,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def check_conversation_history(
    conversation_id: str,
    last_n: int = 5,
) -> str:
    """
    Review recent conversation messages for a thread.
    Useful for the agent to check context before responding.
    Returns the last N messages with metadata.
    """
    try:
        from engine.lmstudio.conversation import get_conversation_manager
        cm = get_conversation_manager()
        conv = cm.get(conversation_id)
        if not conv:
            return json.dumps({"error": f"No conversation '{conversation_id}'"})
        messages = conv.messages[-last_n:] if conv.messages else []
        return json.dumps({
            "conversation_id": conversation_id,
            "total_messages": len(conv.messages),
            "recent": [
                {"role": m.get("role", "?"), "content": m.get("content", "")[:200]}
                for m in messages
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
