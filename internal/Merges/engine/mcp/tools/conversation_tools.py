"""
Pure business-logic functions for conversation-related MCP tools.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import logging
from pydantic import BaseModel
from engine.mcp.decorators import mcp_tool, ToolExecutionError

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────

def _get_scene_agent():
    from engine.mcp.comms_framework import get_scene_agent
    return get_scene_agent()

def _get_conversation_manager():
    from engine.mcp.conversation_manager import get_conversation_manager
    return get_conversation_manager()

def _get_conversation_heat():
    from engine.mcp.conversation_heat import get_conversation_heat
    return get_conversation_heat()

# ── Domain Models ────────────────────────────────────────────────────

class ConversationInfoResponse(BaseModel):
    conversation_id: str
    model: str
    is_synced: bool
    response_id: str
    message_count: int
    response_history: List[str]
    can_branch: bool

class ForkConversationResponse(BaseModel):
    success: bool
    original_id: str
    forked_id: str
    branch_turn: int
    message_count: int

class ConversationHeatResponse(BaseModel):
    conversation_id: str
    heat: float
    directive: str
    thresholds: Dict[str, int]

class BumpHeatResponse(BaseModel):
    conversation_id: str
    heat: float
    bumped_by: float
    reason: str

class ConversationHistoryResponse(BaseModel):
    conversation_id: str
    total_messages: int
    recent: List[Dict[str, str]]

# ── Conversation Tools ────────────────────────────────────────────────

@mcp_tool
def query_stateless_impl(prompt: str, system: str = "") -> str:
    agent = _get_scene_agent()
    if system:
        agent.system_prompt = system
    return agent.run(prompt, max_tokens=500, store=False)

@mcp_tool
def get_conversation_info_impl(conversation_id: str) -> ConversationInfoResponse:
    cm = _get_conversation_manager()
    conv = cm.get(conversation_id)
    if not conv:
        raise ToolExecutionError(f"No conversation '{conversation_id}'")
        
    history = getattr(conv, "_response_id_history", [])
    return ConversationInfoResponse(
        conversation_id=conversation_id,
        model=conv.model or "default",
        is_synced=conv.is_synced,
        response_id=conv.response_id or "",
        message_count=len(conv.messages),
        response_history=history,
        can_branch=len(history) > 0,
    )

@mcp_tool
def fork_conversation_impl(conversation_id: str, turn: int = -1) -> ForkConversationResponse:
    cm = _get_conversation_manager()
    conv = cm.get(conversation_id)
    if not conv:
        raise ToolExecutionError(f"No conversation '{conversation_id}'")

    if turn >= 0 and hasattr(conv, "branch_at"):
        forked = conv.branch_at(turn)
    elif hasattr(conv, "fork"):
        forked = conv.fork()
    else:
        raise ToolExecutionError("Conversation does not support branching")

    new_id = f"{conversation_id}_fork_{turn}"
    cm._conversations[new_id] = forked
    
    return ForkConversationResponse(
        success=True,
        original_id=conversation_id,
        forked_id=new_id,
        branch_turn=turn,
        message_count=len(forked.messages),
    )

@mcp_tool
def get_conversation_heat_level_impl(conversation_id: str) -> ConversationHeatResponse:
    heat = _get_conversation_heat()
    level = heat.get(conversation_id)
    directive = heat.get_directive(conversation_id)
    
    return ConversationHeatResponse(
        conversation_id=conversation_id,
        heat=round(level, 1),
        directive=directive or "normal",
        thresholds={"warm": 30, "hot": 60, "intense": 80},
    )

@mcp_tool
def bump_conversation_heat_impl(
    conversation_id: str,
    amount: float = 10,
    reason: str = "",
) -> BumpHeatResponse:
    heat = _get_conversation_heat()
    new_level = heat.bump(conversation_id, amount, reason)
    
    return BumpHeatResponse(
        conversation_id=conversation_id,
        heat=round(new_level, 1),
        bumped_by=amount,
        reason=reason,
    )

@mcp_tool
def check_conversation_history_impl(
    conversation_id: str,
    last_n: int = 5,
) -> ConversationHistoryResponse:
    cm = _get_conversation_manager()
    conv = cm.get(conversation_id)
    if not conv:
        raise ToolExecutionError(f"No conversation '{conversation_id}'")
        
    messages = conv.messages[-last_n:] if conv.messages else []
    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        total_messages=len(conv.messages),
        recent=[
            {"role": m.get("role", "?"), "content": m.get("content", "")[:200]}
            for m in messages
        ],
    )

class SendToAgentResponse(BaseModel):
    status: str
    recipient: str

@mcp_tool
def send_to_agent_impl(
    recipient_id: str,
    message: str,
    router: Any,
    sender_id: str = "system"
) -> SendToAgentResponse:
    router.send(recipient_id, message, sender_id=sender_id)
    return SendToAgentResponse(
        status="success",
        recipient=recipient_id
    )
