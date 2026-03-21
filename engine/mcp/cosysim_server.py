"""
CosySim MCP Server — Expose framework tools & resources to LMStudio

This FastMCP server makes CosySim's capabilities available as MCP tools
(actions the LLM can execute) and resources (data the LLM can read).

**Tools** (actions):
    - search_memory       — RAG vector search
    - store_memory        — persist text to ChromaDB
    - get_character_state — mood, arousal, relationships
    - adjust_relationship — modify trust/attraction/arousal
    - generate_image      — proxy to ComfyUI
    - get_chain_events    — browse EventChain
    - log_event           — inject event into chain

**Resources** (readable data):
    - config://cosysim        — current YAML config snapshot
    - benchmark://summary     — timing KPIs
    - character://{id}        — full character profile + state
    - chain://{chain_id}      — EventChain tree as JSON
    - scene://{name}/status   — scene health

Run standalone::

    python -m engine.mcp.cosysim_server          # stdio mode (for mcp.json)
    python -m engine.mcp.cosysim_server --http    # HTTP mode (for web bridge)

Or mount onto a FastAPI app::

    from engine.mcp.cosysim_server import mcp
    app.mount("/mcp", mcp.http_app(path="/mcp"))
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is importable
from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ── Server instance ────────────────────────────────────────────────────

mcp = FastMCP(
    "CosySim",
    instructions=(
        "CosySim is an AI agent simulation framework. "
        "Use these tools to interact with characters, memories, media, "
        "and the event chain system. Use resources to read config, "
        "benchmarks, and character profiles."
    ),
)

# ── Lazy service getters (shared via engine.mcp._lazy) ──────────────────
from engine.mcp._lazy import _get_db, _get_rag, _get_config  # noqa: F401

# ── Register all MCP tools from extracted modules ──────────────────────
from engine.mcp.mcp_tools import register_core_tools
from engine.mcp.advanced_tools import register_advanced_tools

register_core_tools(mcp)
register_advanced_tools(mcp)

# ── Re-export tool functions for backward compatibility ───────────────
# Tests and other modules access tools as ``cosysim_server.search_memory`` etc.
# Pull the underlying functions from the mcp tool registry.
import types as _types
for _tool in mcp._tool_manager._tools.values():
    _fn = getattr(_tool, "fn", None)
    if _fn and hasattr(_fn, "__name__"):
        globals()[_fn.__name__] = _fn

# Also re-export resource functions (resources + templates)
_rm = getattr(mcp, "_resource_manager", None)
if _rm is not None:
    for _res in list(_rm._resources.values()) + list(_rm._templates.values()):
        _fn = getattr(_res, "fn", None)
        if _fn and hasattr(_fn, "__name__"):
            globals()[_fn.__name__] = _fn


# ── Entry point ────────────────────────────────────────────────────────
# NOTE: Nexus, Copilot, System, and Agent tools have been extracted to
# engine/mcp/devtools_server.py for cleaner separation of concerns.


# ── Entry point ────────────────────────────────────────────────────────

def run_server(mode: str = "stdio"):
    """Start the MCP server."""
    if mode == "http":
        logger.info("Starting CosySim MCP server in HTTP mode...")
        mcp.run(transport="sse")
    else:
        logger.info("Starting CosySim MCP server in stdio mode...")
        mcp.run()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CosySim MCP Server")
    parser.add_argument("--http", action="store_true", help="Run in HTTP/SSE mode")
    args = parser.parse_args()
    run_server("http" if args.http else "stdio")
