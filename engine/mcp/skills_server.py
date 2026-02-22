"""
skills_server.py — Lightweight MCP-compatible skills server (v3.1).

Wraps ``SKILL_REGISTRY`` as an MCP tool endpoint that LMStudio can call
via ephemeral integration.  Uses Flask blueprint at ``/mcp/skills``.

LMStudio sends tool calls during inference; this server executes the
matching skill and returns the result.

The server also provides:
- ``GET /mcp/skills/tools`` — list all available tools (JSON schema)
- ``POST /mcp/skills/call`` — execute a tool by name
- ``GET /mcp/skills/health`` — health check

Integration with VirtualAgentManager:
    ``MCPIntegration.ephemeral("http://localhost:<port>/mcp/skills")``
    is attached to InferenceConfig.integrations when skills are enabled.
"""

from __future__ import annotations

import inspect
import json
import logging
import traceback
from typing import Any, Callable, Dict, List, Optional, get_type_hints

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ── Blueprint ───────────────────────────────────────────────────────────

skills_bp = Blueprint("mcp_skills", __name__, url_prefix="/mcp/skills")


def _python_type_to_json_schema(t: type) -> Dict[str, str]:
    """Convert a Python type hint to a JSON Schema type."""
    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }
    # Handle Optional[X] → X with nullable
    origin = getattr(t, "__origin__", None)
    if origin is type(None):
        return {"type": "null"}
    return type_map.get(t, {"type": "string"})


def _skill_to_json_schema(meta: Any) -> Dict[str, Any]:
    """Convert a SkillMeta to MCP-compatible tool definition."""
    func = meta.func
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        prop = _python_type_to_json_schema(hints.get(param_name, str))
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)
        # Use param name as description fallback
        properties[param_name] = prop

    return {
        "name": meta.name,
        "description": meta.description or func.__doc__ or f"Skill: {meta.name}",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ── Routes ──────────────────────────────────────────────────────────────

@skills_bp.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({"status": "ok", "server": "cosysim-mcp-skills"})


@skills_bp.route("/tools", methods=["GET"])
def list_tools():
    """List all available tools as MCP-compatible JSON schemas."""
    from engine.skills.registry import SKILL_REGISTRY

    pack_filter = request.args.get("pack")
    category_filter = request.args.get("category")

    if pack_filter:
        metas = SKILL_REGISTRY.get_pack_metas(pack_filter)
    elif category_filter:
        metas = SKILL_REGISTRY.get_by_category(category_filter)
    else:
        metas = []
        for pack in SKILL_REGISTRY.all_packs():
            metas.extend(SKILL_REGISTRY.get_pack_metas(pack))

    tools = [_skill_to_json_schema(m) for m in metas]
    return jsonify({"tools": tools})


@skills_bp.route("/call", methods=["POST"])
def call_tool():
    """Execute a tool by name with given arguments.

    Request body::

        {
            "name": "generate_image",
            "arguments": {"prompt": "sunset", "width": 512}
        }

    Response::

        {
            "content": [{"type": "text", "text": "...result..."}],
            "isError": false
        }
    """
    from engine.skills.registry import SKILL_REGISTRY
    from engine.skills.skill import COOLDOWN_TRACKER

    data = request.get_json(silent=True) or {}
    tool_name = data.get("name", "")
    arguments = data.get("arguments", {})

    if not tool_name:
        return jsonify({
            "content": [{"type": "text", "text": "Missing 'name' in request"}],
            "isError": True,
        }), 400

    meta = SKILL_REGISTRY.get_skill(tool_name)
    if meta is None:
        return jsonify({
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True,
        }), 404

    # Cooldown check
    if not COOLDOWN_TRACKER.can_use(meta.name, meta.cooldown_secs):
        remaining = COOLDOWN_TRACKER.get_remaining(meta.name, meta.cooldown_secs)
        return jsonify({
            "content": [{"type": "text", "text": f"Tool on cooldown ({remaining:.1f}s remaining)"}],
            "isError": True,
        }), 429

    # Execute
    try:
        result = meta.func(**arguments)
        COOLDOWN_TRACKER.mark_used(meta.name)
        logger.debug("MCP skill executed: %s → %s", tool_name, str(result)[:100])

        # Normalize result to string
        if isinstance(result, dict):
            result_text = json.dumps(result)
        elif result is None:
            result_text = "OK"
        else:
            result_text = str(result)

        return jsonify({
            "content": [{"type": "text", "text": result_text}],
            "isError": False,
        })

    except Exception as exc:
        logger.error("MCP skill %s failed: %s", tool_name, exc)
        return jsonify({
            "content": [{"type": "text", "text": f"Error: {exc}"}],
            "isError": True,
        }), 500


@skills_bp.route("/packs", methods=["GET"])
def list_packs():
    """List all registered skill packs."""
    from engine.skills.registry import SKILL_REGISTRY
    return jsonify({"packs": SKILL_REGISTRY.all_packs()})


@skills_bp.route("/manifest", methods=["GET"])
def manifest():
    """Full skill manifest for admin/diagnostic display."""
    from engine.skills.registry import SKILL_REGISTRY
    return jsonify({"skills": SKILL_REGISTRY.mcp_manifest()})


@skills_bp.route("/pipeline/stats", methods=["GET"])
def pipeline_stats():
    """Return VirtualAgentManager pipeline statistics.

    Includes: total requests, tokens, latency, stateful/stateless split,
    repair rates, quality gate usage.
    """
    try:
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        mgr = get_virtual_agent_manager()
        return jsonify(mgr.get_stats())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Helper: get the integration URL ────────────────────────────────────

_skills_server_port: Optional[int] = None


def set_skills_server_port(port: int) -> None:
    """Set the port where the skills server is running."""
    global _skills_server_port
    _skills_server_port = port


def get_skills_integration() -> Optional[Dict[str, str]]:
    """Return an MCP integration dict for attaching to inference requests.

    Returns None if the skills server port hasn't been configured.
    """
    if _skills_server_port is None:
        return None
    return {
        "type": "ephemeral_mcp",
        "server_url": f"http://localhost:{_skills_server_port}/mcp/skills",
    }
