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
from typing import Optional

# Ensure project root is importable
_root = Path(__file__).parent.parent.parent
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

# ── Lazy service getters (avoid import-time side effects) ──────────────

def _get_db():
    from content.simulation.database.db import Database
    return Database()

def _get_rag():
    try:
        from content.simulation.database.rag import RAGManager
        return RAGManager()
    except Exception:
        return None

def _get_config():
    from engine.config import get_config
    return get_config()


# ═══════════════════════════════════════════════════════════════════════
#  MCP TOOLS  (actions the LLM can execute)
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_memory(query: str, character_id: Optional[str] = None, top_k: int = 5) -> str:
    """
    Search character memories using RAG vector search.
    Returns the most relevant stored memories for the given query.
    Use this to recall past conversations, facts, or context.
    """
    rag = _get_rag()
    if rag is None:
        return "RAG system unavailable."
    try:
        results = rag.search(query, character_id=character_id, top_k=top_k)
        if not results:
            return "No relevant memories found."
        entries = []
        for i, r in enumerate(results, 1):
            text = r.get("text", r.get("document", str(r)))
            score = r.get("score", r.get("distance", "?"))
            entries.append(f"{i}. [score={score}] {text}")
        return "\n".join(entries)
    except Exception as e:
        return f"Memory search failed: {e}"


@mcp.tool()
def store_memory(text: str, character_id: str, metadata: Optional[str] = None) -> str:
    """
    Store a new memory for a character in the RAG system.
    Use this to save important facts, conversation summaries, or observations.
    """
    rag = _get_rag()
    if rag is None:
        return "RAG system unavailable."
    try:
        meta = json.loads(metadata) if metadata else {}
        rag.add(text, character_id=character_id, metadata=meta)
        return f"Memory stored for character {character_id}."
    except Exception as e:
        return f"Failed to store memory: {e}"


@mcp.tool()
def get_character_state(character_id: str) -> str:
    """
    Get the current state of a character including mood, energy, and relationships.
    Returns JSON with all character state fields.
    """
    db = _get_db()
    try:
        state = db.get_character_state(character_id)
        if state is None:
            return f"No state found for character {character_id}."
        # Also get relationships
        rels = db.list_relationships(character_id)
        return json.dumps({
            "state": dict(state) if state else {},
            "relationships": [dict(r) for r in rels] if rels else [],
        }, indent=2, default=str)
    except Exception as e:
        return f"Failed to get character state: {e}"


@mcp.tool()
def adjust_relationship(
    character_a: str,
    character_b: str,
    field: str,
    delta: float,
) -> str:
    """
    Adjust a relationship value between two characters.
    Fields: relationship_level, trust, attraction, arousal_a, arousal_b.
    Delta is added to current value (can be negative). Values clamped 0-1.
    """
    valid_fields = {"relationship_level", "trust", "attraction", "arousal_a", "arousal_b"}
    if field not in valid_fields:
        return f"Invalid field '{field}'. Must be one of: {', '.join(sorted(valid_fields))}"

    db = _get_db()
    try:
        rel = db.get_or_create_relationship(character_a, character_b)
        current = rel.get(field, 0.0) if rel else 0.0
        new_val = max(0.0, min(1.0, current + delta))
        db.update_relationship(character_a, character_b, {field: new_val})
        return f"Updated {field}: {current:.2f} → {new_val:.2f}"
    except Exception as e:
        return f"Failed to adjust relationship: {e}"


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def list_characters() -> str:
    """
    List all characters in the database with their names and IDs.
    """
    db = _get_db()
    try:
        chars = db.get_all_characters()
        if not chars:
            return "No characters found."
        lines = []
        for c in chars:
            c_dict = dict(c) if not isinstance(c, dict) else c
            lines.append(f"- {c_dict.get('name', '?')} (id: {c_dict.get('id', '?')})")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list characters: {e}"


@mcp.tool()
def get_benchmark_stats() -> str:
    """
    Get performance benchmark statistics.
    Returns timing KPIs (min/max/avg/p95) for all tracked operations.
    """
    try:
        from engine.logging import get_benchmarks
        stats = get_benchmarks()
        if not stats:
            return "No benchmark data available."
        lines = []
        for op, s in stats.items():
            lines.append(
                f"{op}: count={s['count']}, avg={s['avg_ms']:.1f}ms, "
                f"p95={s['p95_ms']:.1f}ms, max={s['max_ms']:.1f}ms"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get benchmarks: {e}"


@mcp.tool()
def generate_image_request(
    prompt: str,
    width: int = 512,
    height: int = 768,
    character_id: Optional[str] = None,
) -> str:
    """
    Request image generation via ComfyUI.
    Provide a detailed prompt describing the desired image.
    Returns the file path of the generated image.
    """
    try:
        from content.simulation.services.comfyui_client import ComfyUIClient
        from engine.config import get_config
        config = get_config()
        url = config.get("comfyui.base_url", "http://127.0.0.1:8188")
        client = ComfyUIClient(base_url=url)
        result = client.generate_image(prompt=prompt, width=width, height=height)
        return f"Image generated: {result}" if result else "Image generation failed."
    except Exception as e:
        return f"Image generation failed: {e}"


# ═══════════════════════════════════════════════════════════════════════
#  MCP RESOURCES  (data the LLM can read)
# ═══════════════════════════════════════════════════════════════════════

@mcp.resource("config://cosysim")
def resource_config() -> str:
    """Current CosySim configuration snapshot."""
    try:
        config = _get_config()
        return json.dumps(dict(config._config), indent=2, default=str)
    except Exception as e:
        return f"Config unavailable: {e}"


@mcp.resource("benchmark://summary")
def resource_benchmarks() -> str:
    """Performance benchmark summary with timing KPIs."""
    try:
        from engine.logging import get_benchmarks
        return json.dumps(get_benchmarks(), indent=2, default=str)
    except Exception as e:
        return f"Benchmarks unavailable: {e}"


@mcp.resource("character://{character_id}")
def resource_character(character_id: str) -> str:
    """Full character profile including personality, state, and relationships."""
    db = _get_db()
    try:
        char = db.get_character(character_id)
        state = db.get_character_state(character_id)
        rels = db.list_relationships(character_id)
        personality = db.get_personality(character_id)
        return json.dumps({
            "character": dict(char) if char else None,
            "personality": dict(personality) if personality else None,
            "state": dict(state) if state else None,
            "relationships": [dict(r) for r in rels] if rels else [],
        }, indent=2, default=str)
    except Exception as e:
        return f"Character data unavailable: {e}"


@mcp.resource("chain://{chain_id}")
def resource_chain(chain_id: str) -> str:
    """Full EventChain tree for a specific chain."""
    db = _get_db()
    try:
        events = db.get_chain_events(chain_id, limit=100)
        return json.dumps(
            [dict(e) if not isinstance(e, dict) else e for e in events],
            indent=2, default=str,
        )
    except Exception as e:
        return f"Chain unavailable: {e}"


@mcp.resource("scene://{scene_name}/status")
def resource_scene_status(scene_name: str) -> str:
    """Scene health status and connection info."""
    import socket
    from engine.config import get_config
    config = get_config()
    port = int(config.get(f"scenes.{scene_name}.port", 0))
    if not port:
        # Fallback to known ports
        known = {"phone": 5555, "bedroom": 5556, "hub": 8500, "admin": 8502}
        port = known.get(scene_name, 0)
    if not port:
        return json.dumps({"scene": scene_name, "status": "unknown", "error": "No port configured"})

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            running = True
    except OSError:
        running = False

    return json.dumps({
        "scene": scene_name,
        "port": port,
        "status": "running" if running else "stopped",
        "url": f"http://localhost:{port}",
    }, indent=2)


# ── Entry point ────────────────────────────────────────────────────────

def run_server(mode: str = "stdio"):
    """Start the MCP server."""
    if mode == "http":
        print("Starting CosySim MCP server in HTTP mode...")
        mcp.run(transport="sse")
    else:
        print("Starting CosySim MCP server in stdio mode...")
        mcp.run()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CosySim MCP Server")
    parser.add_argument("--http", action="store_true", help="Run in HTTP/SSE mode")
    args = parser.parse_args()
    run_server("http" if args.http else "stdio")
