"""MCP tool domain: consequence.

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

# ──── CONSEQUENCE TOOLS ──────────────────────────────────────────────────


@mcp_tool
def schedule_consequence(
    scene_id:            str,
    character_id:        str,
    consequence_type:    str,
    params_json:         str,
    trigger_after_turns: int  = 1,
    description:         str  = "",
    created_by:          str  = "director",
) -> str:
    """
    **CONSEQUENCE CHAINS** — Schedule a future effect that fires automatically
    after N conversation turns.

    This is how actions echo into the future.  A touch now leads to arousal
    in two turns.  An emotional admission reverberates into affection
    three turns later.  A timer expires and a consequence fires.

    Consequences fire silently (injecting into narrative + stats) and are
    reported back in post-call context.  Agents can then reference them naturally.

    Consequence types mirror RuleEffect types:
      stat_adjust     — {"stat": "arousal", "delta": 20}
      state_set       — {"field": "mood", "value": "tender"}
      add_restriction — {"restriction": "no_touch"}
      add_narrative   — {"event": "The room feels different now."}
      set_directive   — {"directive_type": "style_lock", "value": "warm", "turns": 1}
      scene_event     — {"event": "tension_release"}

    Examples:
      schedule_consequence("penthouse", "aria", "stat_adjust",
                          '{"stat": "arousal", "delta": 25}', 2,
                          "The kiss lingers — arousal builds.")

      schedule_consequence("penthouse", "aria", "state_set",
                          '{"field": "mood", "value": "vulnerable"}', 3,
                          "The confession settles in. She feels exposed.")

    Args:
        scene_id:            Scene where the consequence fires
        character_id:        The affected character
        consequence_type:    Effect type (see above)
        params_json:         JSON dict of parameters for the effect
        trigger_after_turns: How many turns until it fires (1 = next turn)
        description:         Narrative text logged when it fires
        created_by:          Who scheduled this (for audit)
    """
    try:
        import json as _json
        from engine.mcp.framework import get_framework
        params = _json.loads(params_json) if params_json else {}
        cseq   = get_framework().schedule_consequence(
            scene_id             = scene_id,
            character_id         = character_id,
            consequence_type     = consequence_type,
            params               = params,
            trigger_after_turns  = trigger_after_turns,
            description          = description,
            created_by           = created_by,
        )
        return json.dumps({
            "ok":             True,
            "consequence_id": cseq.consequence_id,
            "fires_at_turn":  cseq.fire_at_turn,
            "type":           consequence_type,
            "character_id":   character_id,
            "description":    description,
            "note":           f"Will fire in {trigger_after_turns} turn(s) automatically.",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp_tool
def get_pending_consequences(scene_id: str = "", character_id: str = "") -> str:
    """
    **CONSEQUENCE CHAINS** — List all scheduled consequences that haven't fired yet.

    Use this to see what's coming and plan your response.
    A thoughtful agent references pending consequences in their narration.

    Args:
        scene_id:     Filter by scene (optional)
        character_id: Filter by character (optional)
    """
    try:
        from engine.mcp.framework import get_framework
        pending = get_framework().get_pending_consequences(scene_id=scene_id, character_id=character_id)
        return json.dumps({"pending": pending, "count": len(pending)}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
def cancel_consequence(consequence_id: str) -> str:
    """
    **CONSEQUENCE CHAINS** — Cancel a scheduled consequence before it fires.

    Args:
        consequence_id: The ID returned by schedule_consequence
    """
    try:
        from engine.mcp.framework import get_framework
        ok = get_framework().cancel_consequence(consequence_id)
        return json.dumps({"ok": ok, "consequence_id": consequence_id})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
