"""MCP tool domain: event_chain.

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

# ──── EVENT_CHAIN TOOLS ──────────────────────────────────────────────────


@mcp_tool
def get_chain_events(chain_id: str, limit: int = 20) -> str:
    """
    Get events from an EventChain by chain_id.
    Returns a list of events with type, actor, timestamp, and summary.
    Use this to inspect what happened in an interaction chain.
    """
    db = _get_db()
    try:
        events = db.get_chain_events(chain_id, limit=limit)
        if not events:
            return f"No events found for chain {chain_id}."
        lines = []
        for ev in events:
            ev_dict = dict(ev) if not isinstance(ev, dict) else ev
            lines.append(
                f"[{ev_dict.get('event_type', '?')}] "
                f"{ev_dict.get('actor', '?')} — "
                f"{ev_dict.get('summary', '')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get chain events: {e}"


@mcp_tool
def log_event(
    chain_id: str,
    event_type: str,
    actor: str,
    summary: str,
    payload: Optional[str] = None,
    character_id: Optional[str] = None,
) -> str:
    """
    Log a new event into an EventChain.
    Use this to record actions, observations, or state changes.
    Payload should be a JSON string if provided.
    """
    db = _get_db()
    try:
        payload_dict = json.loads(payload) if payload else {}
        db.log_event(
            event_type=event_type,
            actor=actor,
            payload=payload_dict,
            summary=summary,
            chain_id=chain_id,
            character_id=character_id,
        )
        return f"Event logged: [{event_type}] {summary}"
    except Exception as e:
        return f"Failed to log event: {e}"
