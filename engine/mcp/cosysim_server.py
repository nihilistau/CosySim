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
#  COMMS FRAMEWORK TOOLS  (governance, games, routing, stats)
# ═══════════════════════════════════════════════════════════════════════

# ── Skills & awareness ─────────────────────────────────────────────────

@mcp.tool()
def get_my_skills(scene: str = "phone") -> str:
    """
    List all skills available to you in the current scene.
    Returns skill names, triggers (auto/optional/required), and descriptions.
    Call this to understand what tools you have access to before deciding
    whether to use one.
    """
    try:
        from engine.mcp.comms_framework import get_skill_manifest
        manifest = get_skill_manifest().get(scene)
        result = {
            "scene": scene,
            "auto_skills": [
                {"name": s.name, "description": s.description}
                for s in manifest.auto_skills()
            ],
            "optional_skills": [
                {"name": s.name, "description": s.description}
                for s in manifest.optional_skills()
            ],
            "required_skills": [
                {"name": s.name, "description": s.description}
                for s in manifest.required_skills()
            ],
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Failed to get skills: {e}"


# ── Randomness & game mechanics ────────────────────────────────────────

@mcp.tool()
def roll_dice(sides: int = 6, count: int = 1) -> str:
    """
    Roll one or more dice and return the results.
    Useful for game mechanics, random outcomes, or adding unpredictability.
    Example: roll_dice(100) gives a d100 result for truth-or-dare.
    Odd results = Truth, Even results = Dare (for truth-or-dare game).
    """
    import random as _random
    sides  = max(2, min(sides, 1000))
    count  = max(1, min(count, 20))
    rolls  = [_random.randint(1, sides) for _ in range(count)]
    total  = sum(rolls)
    result = {
        "rolls": rolls,
        "total": total,
        "sides": sides,
        "outcome": "odd" if total % 2 == 1 else "even",
    }
    return json.dumps(result)


@mcp.tool()
def get_random_topic(category: str = "general") -> str:
    """
    Get a randomly selected topic or prompt for conversation or games.
    Categories: 'truth_questions', 'dare_ideas', 'mystery_clues',
    'conversation_starters', 'relationship_questions', 'general'.
    Use this to get fresh ideas for games, topics, or challenges.
    """
    import random as _rnd
    TOPICS = {
        "truth_questions": [
            "What is your biggest secret you've never told anyone?",
            "Who was your first crush and do you still think about them?",
            "What is the most embarrassing thing that has ever happened to you?",
            "What is something you've done that you deeply regret?",
            "If you could change one decision you've made, what would it be?",
            "Have you ever lied to protect someone's feelings? What happened?",
            "What is the worst thing you've ever done and gotten away with?",
            "What is one thing you wish people understood about you?",
        ],
        "dare_ideas": [
            "Send a voice message saying something embarrassing.",
            "Describe your ideal perfect day in as much vivid detail as possible.",
            "Confess something you've been thinking about but haven't said.",
            "Tell me three things you secretly find attractive.",
            "Describe a dream you've had recently in detail.",
            "Say something kind but totally unexpected.",
            "Invent and tell me a one-minute story right now.",
            "Describe yourself using only three words.",
        ],
        "mystery_clues": [
            "A torn piece of paper with coordinates written in ink.",
            "An old photograph with a face scratched out.",
            "A key that fits no known lock.",
            "A voicemail from a number that doesn't exist.",
            "A book with one passage underlined in red.",
            "A receipt from a restaurant that closed ten years ago.",
            "A note written in a language you don't recognise.",
        ],
        "conversation_starters": [
            "If you could live anywhere in the world, where would you choose?",
            "What is something you want to learn but haven't started yet?",
            "What memory always makes you smile?",
            "If you had one superpower for a day, what would it be?",
            "What song always puts you in a good mood?",
        ],
        "relationship_questions": [
            "What do you value most in a partner?",
            "What is your love language?",
            "Describe your perfect evening together.",
            "What is one thing you've always wanted to do with someone special?",
        ],
        "general": [
            "Tell me something interesting you learned this week.",
            "What is your favourite way to relax?",
            "If you could meet any historical figure, who would it be?",
            "What is the best book or show you've experienced recently?",
        ],
    }
    pool  = TOPICS.get(category, TOPICS["general"])
    topic = _rnd.choice(pool)
    return json.dumps({"category": category, "topic": topic})


# ── Game state ─────────────────────────────────────────────────────────

@mcp.tool()
def get_game_state(game_id: str, key: Optional[str] = None) -> str:
    """
    Read the current state of a game by its ID.
    If key is provided, returns only that value.
    If key is None, returns the entire game state dict.
    Common game IDs: 'truth_or_dare', 'mystery'.
    """
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        gs = _gs()
        if key:
            val = gs.get(game_id, key)
            return json.dumps({game_id: {key: val}})
        return json.dumps({game_id: gs.get_all(game_id)}, indent=2, default=str)
    except Exception as e:
        return f"Failed to get game state: {e}"


@mcp.tool()
def set_game_state(game_id: str, key: str, value: str) -> str:
    """
    Write a value to the game state.
    Use this to record scores, round counts, discovered clues, game outcomes, etc.
    Value is stored as a string — use JSON encoding for complex types.
    Example: set_game_state('truth_or_dare', 'round', '3')
    """
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        _gs().set(game_id, key, value)
        return f"Game state updated: {game_id}.{key} = {value!r}"
    except Exception as e:
        return f"Failed to set game state: {e}"


@mcp.tool()
def start_game(game_id: str, scene: str = "phone", config_json: Optional[str] = None) -> str:
    """
    Start a new game session.
    game_id options: 'truth_or_dare', 'mystery'
    This resets existing game state and marks the game as active.
    The game rules will automatically be injected into your system context.
    """
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        gs = _gs()
        gs.reset(game_id)
        config = json.loads(config_json) if config_json else {}
        gs.set(game_id, "active",     True)
        gs.set(game_id, "scene",      scene)
        gs.set(game_id, "started_at", str(__import__("time").time()))
        gs.set(game_id, "round",      0)
        gs.set(game_id, "score",      0)
        for k, v in config.items():
            gs.set(game_id, k, v)
        return f"Game '{game_id}' started in scene '{scene}'."
    except Exception as e:
        return f"Failed to start game: {e}"


@mcp.tool()
def end_game(game_id: str) -> str:
    """
    End a game and record the final result.
    Returns a summary of the final game state including score.
    """
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        gs  = _gs()
        state = gs.get_all(game_id)
        gs.set(game_id, "active",  False)
        gs.set(game_id, "ended_at", str(__import__("time").time()))
        return json.dumps({
            "game_id": game_id,
            "summary": "Game ended.",
            "final_state": state,
        }, indent=2, default=str)
    except Exception as e:
        return f"Failed to end game: {e}"


# ── MCP-tracked game tools (MCPGameSession) ───────────────────────────

@mcp.tool()
def launch_game(
    character_id: str,
    game_type:    str,
    case_index:   int = -1,
) -> str:
    """
    Start an MCP-tracked Truth-or-Dare or Mystery game session for a character.

    Creates an MCPGameSession with full history, stat sync, and ActivityBus
    integration.  Any previous session for this character+game_type is reset.

    Parameters
    ----------
    character_id : The character / player starting the game.
    game_type    : "truth_or_dare"  or  "mystery".
    case_index   : Mystery only — 0-based index of the case to play (-1 = random).

    Returns
    -------
    JSON with the new session summary including game_id and initial state.
    """
    try:
        from content.scenes.bedroom.bedroom_game_skill import launch_game as _lg
        return _lg(character_id, game_type, case_index)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_active_game(character_id: str) -> str:
    """
    Return the active MCP game session summary and recent history for a character.

    Checks the MCPGameSession registry first; falls back to legacy GameState if
    no MCP session is found.

    Returns
    -------
    JSON: {"active": false} if no session, or full session summary + 10-turn history.
    """
    try:
        from content.scenes.bedroom.bedroom_game_skill import get_active_game as _gag
        return _gag(character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def game_action(
    character_id: str,
    action:       str,
    data_json:    str = "{}",
) -> str:
    """
    Perform a game action for a character's active MCP game session.

    Truth or Dare actions
    ---------------------
    roll         — Roll for truth or dare; receive the prompt.
    answer       — Resolve the current prompt.
                   data_json: {"completed": true}  for completing a dare.
                   Truths are always resolved as answered.

    Mystery actions
    ---------------
    next_clue    — Reveal the next clue on the board.
    accuse       — Name the culprit and resolve the case.
                   data_json: {"suspect": "Full Name"}

    Parameters
    ----------
    character_id : The acting character.
    action       : One of roll | answer | next_clue | accuse.
    data_json    : JSON-encoded extra parameters (see above).

    Returns
    -------
    JSON result dict with outcome details.
    """
    try:
        from content.scenes.bedroom.bedroom_game_skill import game_action as _ga
        return _ga(character_id, action, data_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def game_history(character_id: str, limit: int = 20) -> str:
    """
    Retrieve the full turn-by-turn MCP game history for a character's active session.

    Each entry includes: turn number, event_type, description, actor,
    data payload, and timestamp.

    Parameters
    ----------
    character_id : The character to look up.
    limit        : Maximum number of history entries to return (default 20).

    Returns
    -------
    JSON with game_id, game_type, current turn, and history list.
    """
    try:
        from content.scenes.bedroom.bedroom_game_skill import game_history as _gh
        return _gh(character_id, limit)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Character emotion & mood ───────────────────────────────────────────

@mcp.tool()
def update_mood(
    character_id: str,
    mood:         str,
    reason:       str = "",
    intensity:    float = 0.5,
) -> str:
    """
    Update a character's current mood and optionally trigger emotional effects.
    mood options: 'happy', 'excited', 'sad', 'anxious', 'flirty', 'mysterious',
                  'playful', 'serious', 'irritated', 'loving', 'bored', 'curious'.
    intensity: float 0.0–1.0 (how strongly the mood is felt).
    reason: short string explaining what caused the mood change.
    Use this after an impactful event, a game result, or an emotional exchange.
    """
    db = _get_db()
    try:
        db.update_character_state(character_id, {
            "mood":           mood,
            "mood_intensity": max(0.0, min(1.0, intensity)),
            "mood_reason":    reason,
        })
        return f"Updated {character_id} mood → {mood} (intensity={intensity:.1f}). Reason: {reason}"
    except Exception as e:
        return f"Failed to update mood: {e}"


@mcp.tool()
def apply_effect(
    character_id: str,
    effect_name:  str,
    value:        float = 0.1,
) -> str:
    """
    Apply a status effect to a character's state.
    Effects are additive deltas on personality/relationship fields.
    effect_name options: 'trust_boost', 'attraction_boost', 'trust_drop',
    'energise', 'deflate', 'excite', 'calm', 'curiosity_spike'.
    value: magnitude of the effect (0.0–1.0).
    """
    EFFECT_MAP = {
        "trust_boost":      {"trust": value},
        "trust_drop":       {"trust": -value},
        "attraction_boost": {"attraction": value},
        "energise":         {"arousal_a": value},
        "deflate":          {"arousal_a": -value},
        "excite":           {"arousal_a": value, "attraction": value * 0.5},
        "calm":             {"arousal_a": -value * 0.5},
        "curiosity_spike":  {"relationship_level": value * 0.3},
    }
    fields = EFFECT_MAP.get(effect_name)
    if not fields:
        return f"Unknown effect '{effect_name}'."
    db = _get_db()
    results = []
    for field, delta in fields.items():
        try:
            db.update_character_state(character_id, {field: delta})
            results.append(f"{field}+={delta:+.2f}")
        except Exception:
            pass
    return f"Applied effect '{effect_name}' to {character_id}: {', '.join(results)}"


# ── Agent routing & communication ──────────────────────────────────────

@mcp.tool()
def send_to_agent(
    recipient_id: str,
    message:      str,
    sender_id:    str = "system",
) -> str:
    """
    Send a message to another agent's inbox.
    The recipient will see this message on their next reply tick.
    Use this for agent-to-agent communication, coordination, or triggering
    reactions in other characters.
    sender_id should be your character ID or 'system'.
    """
    try:
        from engine.mcp.comms_framework import get_router
        get_router().send(recipient_id, message, sender_id=sender_id)
        return f"Message sent to {recipient_id}."
    except Exception as e:
        return f"Failed to send: {e}"


@mcp.tool()
def get_scene_context(scene: str = "phone") -> str:
    """
    Get context about what is currently happening in a scene:
    active characters, current game (if any), service health.
    Use this to understand the state of the world before acting.
    """
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        from engine.logging.monitor import get_system_monitor
        gs = _gs().get_all
        mon = get_system_monitor()

        active_games = []
        _gstate = _gs()
        for gid in _gstate.all_games():
            if _gstate.get(gid, "active") and _gstate.get(gid, "scene") == scene:
                active_games.append({"game_id": gid, "state": _gstate.get_all(gid)})

        return json.dumps({
            "scene": scene,
            "active_games": active_games,
            "system": {
                "cpu_pct":          mon.snapshot().get("cpu_percent"),
                "gpu_vram_used_mb": mon.snapshot().get("gpu_vram_used_mb"),
                "loaded_model":     mon.get_loaded_model(),
            },
        }, indent=2, default=str)
    except Exception as e:
        return f"Failed to get scene context: {e}"


@mcp.tool()
def intercept_and_enhance(
    original_message: str,
    instruction:      str,
) -> str:
    """
    Reshape or enhance a message according to a specific instruction.
    Use this to rewrite your own response before delivering it, apply a
    specific style, add depth, check it against a rule, or transform it.
    Examples:
      instruction='make this more mysterious and cryptic'
      instruction='add a flirty undertone while keeping the core meaning'
      instruction='verify this does not reveal the mystery answer'
      instruction='trim to under 50 words while keeping emotion intact'
    """
    try:
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        from engine.agents.virtual_agent import InferenceRequest
        mgr = get_virtual_agent_manager()
        request = InferenceRequest(
            agent_id="mcp_enhance",
            messages=[
                {"role": "system", "content":
                 "You are a message editor. Reshape the given message according to "
                 "the instruction. Return ONLY the rewritten message, nothing else."},
                {"role": "user", "content":
                 f"Original:\n{original_message}\n\nInstruction:\n{instruction}"},
            ],
            max_output_tokens=300,
            temperature=0.7,
            priority=4,
            metadata={"type": "enhance_message"},
        )
        response = mgr.infer(request)
        return (response.content or "").strip()
    except Exception as e:
        return f"Enhancement failed: {e}. Original: {original_message}"


# ── System stats ───────────────────────────────────────────────────────

@mcp.tool()
def get_system_stats() -> str:
    """
    Get current system resource usage: CPU, RAM, GPU VRAM, GPU temp,
    loaded LMStudio model, and activity bus status.
    Use this to check if the system is under load or what model is active.
    """
    try:
        from engine.logging.monitor import get_system_monitor
        from engine.services.activity_bus import get_activity_bus
        mon = get_system_monitor()
        bus = get_activity_bus()
        snap = mon.snapshot()
        return json.dumps({
            "cpu_percent":      snap.get("cpu_percent"),
            "ram_used_gb":      snap.get("ram_used_gb"),
            "ram_total_gb":     snap.get("ram_total_gb"),
            "gpu_vram_used_mb": snap.get("gpu_vram_used_mb"),
            "gpu_vram_total_mb":snap.get("gpu_vram_total_mb"),
            "gpu_temp_c":       snap.get("gpu_temp_c"),
            "gpu_name":         snap.get("gpu_name"),
            "loaded_model":     mon.get_loaded_model(),
            "activity":         bus.snapshot(),
        }, indent=2, default=str)
    except Exception as e:
        return f"Stats unavailable: {e}"


@mcp.tool()
def check_relationship(character_a: str, character_b: str) -> str:
    """
    Get a concise relationship summary between two characters.
    Returns trust, attraction, relationship level and a natural-language
    summary. Use this before making decisions that depend on relationship state.
    """
    db = _get_db()
    try:
        rel = db.get_or_create_relationship(character_a, character_b)
        if not rel:
            return f"No relationship found between {character_a} and {character_b}."
        r = dict(rel)
        trust    = float(r.get("trust", 0.5))
        attract  = float(r.get("attraction", 0.5))
        level    = float(r.get("relationship_level", 0.5))

        def _desc(v: float) -> str:
            if v >= 0.8: return "very high"
            if v >= 0.6: return "high"
            if v >= 0.4: return "moderate"
            if v >= 0.2: return "low"
            return "very low"

        summary = (
            f"Trust: {_desc(trust)}, "
            f"Attraction: {_desc(attract)}, "
            f"Bond: {_desc(level)}."
        )
        return json.dumps({"raw": r, "summary": summary}, indent=2, default=str)
    except Exception as e:
        return f"Failed to check relationship: {e}"


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web for information and return a summary of results.
    Use this when you need current information, facts, or knowledge
    that might not be in your training data.
    Returns a list of titles, snippets, and URLs.
    """
    # Try DuckDuckGo Instant Answers API (no key required)
    try:
        import httpx
        params = {
            "q":              query,
            "format":         "json",
            "no_html":        "1",
            "skip_disambig":  "1",
        }
        r = httpx.get(
            "https://api.duckduckgo.com/",
            params=params,
            timeout=8.0,
        )
        data = r.json()
        results = []
        # Abstract (main answer)
        if data.get("AbstractText"):
            results.append({
                "title":   data.get("Heading", "DuckDuckGo"),
                "snippet": data["AbstractText"][:400],
                "url":     data.get("AbstractURL", ""),
            })
        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results - 1]:
            if "Text" in topic:
                results.append({
                    "title":   topic.get("Text", "")[:80],
                    "snippet": topic.get("Text", "")[:400],
                    "url":     topic.get("FirstURL", ""),
                })
        if results:
            return json.dumps(results, indent=2)
    except Exception:
        pass

    # Fallback: return a note that web search is unavailable offline
    return json.dumps([{
        "title": "Search unavailable",
        "snippet": f"Could not perform web search for '{query}'. "
                   "The system may be offline or the search service is unreachable.",
        "url": "",
    }])


# ══════════════════════════════════════════════════════════════════════
# ██████████████████████████████████████████████████████████████████████
#  BEDROOM & PHONE  — Scene State, Wardrobe, Interactions, Narrative
# ██████████████████████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════

def _ssm():
    from engine.mcp.scene_state import get_scene_state_manager
    return get_scene_state_manager()

def _itrees():
    from engine.mcp import interaction_trees as it
    return it


# ── WARDROBE ──────────────────────────────────────────────────────────

@mcp.tool()
def wardrobe_get(character_id: str) -> str:
    """
    Get the full clothing inventory for a character — what they're wearing and
    what has already been removed.  Call this before any undressing action so
    you know what items exist.

    Returns JSON with 'worn' list, 'removed' list, 'description' (human-readable),
    and 'is_naked' boolean.
    """
    wardrobe = _ssm().get_wardrobe(character_id)
    return json.dumps(wardrobe.to_dict(), indent=2)


@mcp.tool()
def wardrobe_init(character_id: str, style: str = "casual") -> str:
    """
    Give a character a full starter wardrobe.  Call this when a character first
    enters a scene so they have a clothing inventory.

    style: 'casual' | 'lingerie' | 'party' | 'nightwear' | 'swimwear'
    """
    wardrobe = _ssm().initialise_wardrobe(character_id, style=style)
    return json.dumps({
        "initialised": True,
        "style": style,
        "item_count": len(wardrobe.items),
        "description": wardrobe.coverage_description(),
        "worn_items": [{"id": i.id, "name": i.name, "category": i.category} for i in wardrobe.worn_items()],
    }, indent=2)


@mcp.tool()
def wardrobe_remove_item(character_id: str, item_id: str, removed_by: str = "") -> str:
    """
    Remove a specific clothing item from a character.  The item must exist in
    their wardrobe and be currently worn.

    Use wardrobe_get() first to find the correct item_id.
    removed_by: the character_id doing the removing (leave blank if self).

    Returns the item details and updated coverage description, or an error if
    the item is not found or already removed.
    """
    item = _ssm().remove_clothing(character_id, item_id, removed_by=removed_by)
    if not item:
        # Check if item exists at all
        wardrobe = _ssm().get_wardrobe(character_id)
        existing = wardrobe.get_item(item_id)
        if existing and not existing.is_worn:
            return json.dumps({"error": f"'{item_id}' is already removed.", "already_removed": True})
        return json.dumps({"error": f"Item '{item_id}' not found in wardrobe."})

    wardrobe = _ssm().get_wardrobe(character_id)
    # Arouse the character slightly when clothing comes off
    _ssm().update_stats(character_id, arousal=8, openness=3)
    return json.dumps({
        "removed": True,
        "item": item.to_dict(),
        "now_wearing": wardrobe.coverage_description(),
        "is_naked": len(wardrobe.worn_items()) == 0,
        "stat_effect": "arousal+8, openness+3",
    }, indent=2)


@mcp.tool()
def wardrobe_remove_outermost(character_id: str, removed_by: str = "") -> str:
    """
    Strip the outermost clothing layer from a character — perfect for a
    striptease or when the Director wants the next item to come off without
    specifying which one.

    Returns what was removed and what's left.  Call repeatedly to fully
    undress.
    """
    item = _ssm().remove_outermost(character_id, removed_by=removed_by)
    if not item:
        wardrobe = _ssm().get_wardrobe(character_id)
        return json.dumps({
            "removed": False,
            "message": f"{character_id} is already wearing nothing.",
            "is_naked": True,
        })
    wardrobe = _ssm().get_wardrobe(character_id)
    _ssm().update_stats(character_id, arousal=12, openness=5)
    return json.dumps({
        "removed": True,
        "item": item.to_dict(),
        "now_wearing": wardrobe.coverage_description(),
        "remaining_layers": len(wardrobe.worn_items()),
        "is_naked": len(wardrobe.worn_items()) == 0,
        "stat_effect": "arousal+12, openness+5",
    }, indent=2)


@mcp.tool()
def wardrobe_add_item(
    character_id: str,
    item_id: str,
    name: str,
    category: str,
    color: str = "black",
    style: str = "casual",
) -> str:
    """
    Add a new clothing item to a character's wardrobe (as worn).
    Useful when the Director gives them something to put on.

    category: bra | underwear | top | bottom | full_outfit | shoes | outerwear | accessory | socks
    """
    from engine.mcp.scene_state import ClothingItem
    item = ClothingItem(id=item_id, name=name, category=category, color=color, style=style)
    _ssm().add_clothing(character_id, item)
    wardrobe = _ssm().get_wardrobe(character_id)
    return json.dumps({
        "added": True,
        "item": item.to_dict(),
        "now_wearing": wardrobe.coverage_description(),
    }, indent=2)


@mcp.tool()
def wardrobe_redress(character_id: str) -> str:
    """
    Put all previously removed clothing back on a character.
    Use at scene reset or morning-after scenarios.
    """
    count = _ssm().re_dress(character_id)
    wardrobe = _ssm().get_wardrobe(character_id)
    return json.dumps({
        "redressed": True,
        "items_restored": count,
        "now_wearing": wardrobe.coverage_description(),
    }, indent=2)


# ── CHARACTER SCENE STATS ────────────────────────────────────────────

@mcp.tool()
def get_character_scene_stats(character_id: str) -> str:
    """
    Get the full extended emotional/physical stat vector for a character in the
    current scene.

    Stats (all 0-100): arousal, horniness, pleasure, happiness, anger, fear,
    drunkenness, tiredness, explicitness, openness, affection, dominance.

    Also returns 'emotional_state' — a human-readable description of how the
    character is feeling right now.  USE THIS to inform how they should behave.
    """
    stats = _ssm().get_stats(character_id)
    wardrobe = _ssm().get_wardrobe(character_id)
    return json.dumps({
        "character_id":    character_id,
        "stats":           stats.to_dict(),
        "emotional_state": stats.emotional_state_text(),
        "wearing":         wardrobe.coverage_description(),
        "is_naked":        len(wardrobe.worn_items()) == 0,
    }, indent=2)


@mcp.tool()
def update_character_scene_stats(character_id: str, stat_changes: str) -> str:
    """
    Adjust a character's scene stats by delta values.  Pass a JSON string like:
    '{"arousal": 15, "happiness": -10, "openness": 5}'

    Stats clamp at 0-100.  Use positive values to increase, negative to decrease.
    Call this after interactions, events, emotional moments.
    """
    try:
        changes = json.loads(stat_changes) if isinstance(stat_changes, str) else stat_changes
    except Exception:
        return json.dumps({"error": "stat_changes must be valid JSON: {\"stat\": delta}"})
    stats = _ssm().update_stats(character_id, **changes)
    return json.dumps({
        "updated": True,
        "character_id": character_id,
        "applied_changes": changes,
        "new_stats": stats.to_dict(),
        "emotional_state": stats.emotional_state_text(),
    }, indent=2)


@mcp.tool()
def set_character_scene_stat(character_id: str, stat: str, value: float) -> str:
    """
    Set a specific stat to an exact value (0-100).  Use when you need precision
    rather than a delta — e.g. resetting a stat at scene start.

    stat: arousal | horniness | pleasure | happiness | anger | fear |
          drunkenness | tiredness | explicitness | openness | affection | dominance
    """
    stats = _ssm().set_stats(character_id, **{stat: value})
    return json.dumps({
        "set": True,
        "stat": stat,
        "value": getattr(stats, stat, None),
        "emotional_state": stats.emotional_state_text(),
    }, indent=2)


@mcp.tool()
def reset_character_scene_stats(character_id: str) -> str:
    """Reset all scene stats for a character back to defaults (scene reset / new character)."""
    stats = _ssm().reset_stats(character_id)
    return json.dumps({
        "reset": True,
        "character_id": character_id,
        "stats": stats.to_dict(),
    }, indent=2)


# ── INTERACTIONS ──────────────────────────────────────────────────────

@mcp.tool()
def perform_interaction(
    interaction_type: str,
    initiator_id: str,
    target_id: str,
    scene_id: str = "bedroom",
    subtype: str = "",
    intensity: int = 0,
) -> str:
    """
    Perform one of the 6 core interaction types between two characters.

    BEDROOM interaction_types:
      cuddle    — physical closeness (subtypes: embrace, spoon, lap_sit, entangled)
      kiss      — kissing (subtypes: soft, neck, deep, trail, urgent)
      caress    — tactile touch (subtypes: hair, back, face, body)
      striptease — undressing performance (subtypes: tease_outer, slow_reveal, dance_strip, interactive_strip)
      intimate  — sexual encounter (subtypes: foreplay, oral, passionate, directed, afterglow)
      deep_talk — intimate conversation (subtypes: pillow_talk, dirty_talk, whisper, confession, fantasy_share)

    PHONE interaction_types:
      flirt_text | sext | voice_call | video_call | send_media | roleplay_text

    intensity: 0=auto-select based on stats, 1-5=force min intimacy level
    subtype: override auto-selection with a specific subtype id

    Returns the interaction result, narrative fragments, stat effects applied,
    and a timed action token if the interaction takes time.
    """
    it = _itrees()
    initiator_stats = _ssm().get_stats(initiator_id).to_dict()
    result = it.get_interaction_result(
        interaction_type,
        subtype or None,
        initiator_stats=initiator_stats,
        target_stats=_ssm().get_stats(target_id).to_dict() if target_id else None,
        scene=scene_id,
        intensity_override=intensity or None,
    )

    if "error" in result:
        return json.dumps(result)

    # Apply stat effects to both characters
    for char_id in [initiator_id, target_id]:
        if char_id:
            _ssm().update_stats(char_id, **result["stat_effects"])

    # Log to narrative
    opening = result.get("narrative_opening", "")
    _ssm().add_narrative(
        scene_id,
        opening,
        character_id=initiator_id,
        entry_type="action",
    )

    # Log interaction record
    from engine.mcp.scene_state import InteractionRecord
    record = InteractionRecord(
        interaction_id=json.dumps({"t": result["type"], "s": result["subtype"]})[:32],
        scene_id=scene_id,
        interaction_type=result["type"],
        subtype=result["subtype"],
        initiator_id=initiator_id,
        target_id=target_id,
        description=result["description"],
        duration_secs=result["duration_secs"],
        stat_effects=result["stat_effects"],
    )
    _ssm().log_interaction(scene_id, record)

    # Start timed action if duration > 0
    action_token = None
    if result["duration_secs"] > 0:
        action_token = _ssm().start_timed_action(
            initiator_id,
            action_type=result["type"],
            duration=result["duration_secs"],
            description=result["description"],
            phase_labels=result.get("phases", []),
        )

    # Updated stats
    new_stats = _ssm().get_stats(initiator_id).to_dict()

    return json.dumps({
        "interaction":        result,
        "stat_effects_applied": result["stat_effects"],
        "initiator_new_stats":  new_stats,
        "initiator_emotional_state": _ssm().get_stats(initiator_id).emotional_state_text(),
        "timed_action_token": action_token,
        "narrative_fragment": opening,
    }, indent=2)


@mcp.tool()
def list_available_interactions(character_id: str, scene_id: str = "bedroom") -> str:
    """
    List all interaction types and their accessible subtypes for a character
    based on their current stats.  Use this before calling perform_interaction
    to know what's available without guessing.

    Returns a filtered list — only shows subtypes whose stat requirements are met.
    """
    it = _itrees()
    stats = _ssm().get_stats(character_id).to_dict()
    available = it.get_available_interactions(stats, scene=scene_id)
    all_types = it.list_interaction_types(scene=scene_id)
    return json.dumps({
        "character_id":  character_id,
        "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
        "available_now": available,
        "all_types":     all_types,
    }, indent=2)


@mcp.tool()
def get_interaction_details(
    interaction_type: str,
    subtype: str = "",
    scene_id: str = "bedroom",
) -> str:
    """
    Get detailed information about a specific interaction type/subtype —
    description, phases, sample narrative fragments, stat effects, requirements.

    Call this to understand what an interaction involves before using it,
    or to pick the right fragments for your narration.
    """
    it = _itrees()
    trees = it.BEDROOM_INTERACTIONS if scene_id == "bedroom" else it.PHONE_INTERACTIONS
    itype = trees.get(interaction_type)
    if not itype:
        return json.dumps({"error": f"Unknown type '{interaction_type}'"})
    if subtype:
        sub = itype.get_subtype(subtype)
        if not sub:
            return json.dumps({"error": f"Unknown subtype '{subtype}'"})
        import dataclasses
        return json.dumps(dataclasses.asdict(sub), indent=2)
    # Return overview of all subtypes
    return json.dumps({
        "type":     itype.id,
        "label":    itype.label,
        "description": itype.description,
        "subtypes": [
            {
                "id": s.id, "label": s.label,
                "description": s.description,
                "intimacy": s.intimacy,
                "duration": s.duration,
                "stat_effects": s.stat_effects,
                "phases": s.phases,
                "sample_fragments": s.fragments[:3],
                "requires": s.requires,
            }
            for s in itype.subtypes
        ],
    }, indent=2)


# ── TIMED ACTIONS ─────────────────────────────────────────────────────

@mcp.tool()
def start_timed_action(
    character_id: str,
    action_type: str,
    duration_secs: float = 30.0,
    description: str = "",
    phases: str = "",
) -> str:
    """
    Start a long-form action that plays out over real time.
    Returns a token you can use to poll progress.

    Use for anything that should feel like it takes time:
    striptease, massage, sex, bath scene, dance, etc.

    phases: comma-separated phase labels e.g. 'beginning,building,peak,afterglow'
    duration_secs: how long the action takes (15-120 typical)
    """
    phase_list = [p.strip() for p in phases.split(",") if p.strip()] if phases else []
    token = _ssm().start_timed_action(
        character_id, action_type,
        duration=duration_secs,
        description=description,
        phase_labels=phase_list,
    )
    return json.dumps({
        "started": True,
        "token": token,
        "character_id": character_id,
        "action_type": action_type,
        "duration_secs": duration_secs,
        "description": description,
        "message": f"Use poll_timed_action('{token}') to check progress.",
    }, indent=2)


@mcp.tool()
def poll_timed_action(token: str) -> str:
    """
    Check the progress of a running timed action.
    Returns phase name, progress (0.0-1.0), elapsed time, and completion status.

    Check this periodically to narrate an unfolding scene.  When complete=true
    the action has finished — emit the afterglow narrative.
    """
    status = _ssm().poll_timed_action(token)
    if not status:
        return json.dumps({"error": f"No action found with token '{token}'"})
    return json.dumps(status, indent=2)


@mcp.tool()
def abort_timed_action(token: str) -> str:
    """Stop a timed action early (e.g. interrupted by Director or refused by character)."""
    ok = _ssm().abort_timed_action(token)
    return json.dumps({"aborted": ok, "token": token})


@mcp.tool()
def list_active_timed_actions(character_id: str = "") -> str:
    """
    List all currently running timed actions.
    Pass character_id to filter to a specific character, or leave blank for all.
    """
    actions = _ssm().active_timed_actions(character_id=character_id or None)
    return json.dumps({"active_actions": actions, "count": len(actions)}, indent=2)


# ── NARRATIVE & CONTINUITY ───────────────────────────────────────────

@mcp.tool()
def add_scene_narrative(
    scene_id: str,
    event: str,
    character_id: str = "",
    entry_type: str = "action",
) -> str:
    """
    Add an event to the scene's rolling narrative log.  This is the continuity
    system — use it to record important moments, actions, dialogue, and
    environmental changes so the story remains consistent.

    entry_type: 'action' | 'dialogue' | 'environment' | 'system'

    Examples:
      "Maya removes her silk robe and lets it fall."
      "The Director dims the lights to red."
      "Aria admits she's been thinking about him all day."
    """
    _ssm().add_narrative(scene_id, event, character_id=character_id, entry_type=entry_type)
    return json.dumps({"logged": True, "event": event, "scene_id": scene_id})


@mcp.tool()
def get_scene_narrative(scene_id: str, limit: int = 20) -> str:
    """
    Read the last N entries from the scene's narrative log.
    Use this to maintain continuity — know what has already happened.

    Returns a text summary and a structured list of entries.
    Always call this at scene start and after resuming a paused session.
    """
    entries = _ssm().get_narrative_entries(scene_id, limit=limit)
    text    = _ssm().get_narrative(scene_id, limit=limit)
    return json.dumps({
        "scene_id":       scene_id,
        "entry_count":    len(entries),
        "narrative_text": text,
        "entries":        entries,
    }, indent=2)


@mcp.tool()
def get_full_scene_snapshot(scene_id: str, character_ids: str = "") -> str:
    """
    Get a complete snapshot of the scene state — all characters' stats, wardrobes,
    emotional states, current timed actions, atmosphere, and recent narrative.

    character_ids: comma-separated list, or blank to include all known characters.

    Use this at scene start, after a skip, or to ground your response in the
    current reality of the room.  This is your oracle.
    """
    char_list = [c.strip() for c in character_ids.split(",") if c.strip()] if character_ids else None
    snapshot = _ssm().get_scene_snapshot(scene_id, character_ids=char_list)
    return json.dumps(snapshot, indent=2)


# ── SCENE ATMOSPHERE ─────────────────────────────────────────────────

@mcp.tool()
def set_scene_atmosphere(
    scene_id: str,
    lighting: str = "",
    mood: str = "",
    music: str = "",
    temperature: str = "",
    props_present: str = "",
    note: str = "",
) -> str:
    """
    Set the atmosphere of a scene.  All parameters are optional strings —
    describe the vibe you want.

    lighting: 'candlelight' | 'red_light' | 'dim' | 'bright' | custom string
    mood:     'romantic' | 'playful' | 'tense' | 'relaxed' | 'electric' | custom
    music:    'jazz' | 'no music' | 'soft pop' | custom
    temperature: 'warm' | 'hot' | 'cool' | custom
    props_present: comma-separated items visible in room
    note: any additional atmosphere detail

    This is written into the narrative log and returned to agents via
    get_full_scene_snapshot().
    """
    atm: dict = {}
    if lighting:      atm["lighting"]       = lighting
    if mood:          atm["mood"]           = mood
    if music:         atm["music"]          = music
    if temperature:   atm["temperature"]    = temperature
    if props_present: atm["props_present"]  = [p.strip() for p in props_present.split(",")]
    if note:          atm["note"]           = note
    _ssm().set_atmosphere(scene_id, **atm)
    if atm:
        desc_parts = []
        if lighting: desc_parts.append(f"{lighting} lighting")
        if mood:     desc_parts.append(f"{mood} mood")
        if music:    desc_parts.append(f"{music} playing")
        if note:     desc_parts.append(note)
        _ssm().add_narrative(scene_id, "Atmosphere: " + ", ".join(desc_parts) + ".", entry_type="environment")
    return json.dumps({"set": True, "atmosphere": atm, "scene_id": scene_id}, indent=2)


# ── CONSENT & AGENCY ─────────────────────────────────────────────────

@mcp.tool()
def check_character_consent(character_id: str, action_type: str) -> str:
    """
    Check whether a character would willingly perform or receive an action
    based on their current stats.

    Returns a WILL/RELUCTANT/REFUSE decision and the reasoning.
    Characters CAN and SHOULD refuse sometimes — it creates drama.
    They might also take initiative and suggest something the Director didn't.

    action_type examples: 'striptease', 'kiss', 'sex', 'oral', 'cuddle',
                          'dirty_talk', 'remove_top', 'remove_all'
    """
    stats = _ssm().get_stats(character_id).to_dict()
    openness   = float(stats.get("openness", 65))
    arousal    = float(stats.get("arousal", 20))
    fear       = float(stats.get("fear", 5))
    anger      = float(stats.get("anger", 5))
    happiness  = float(stats.get("happiness", 60))
    affection  = float(stats.get("affection", 50))

    intimacy_map = {
        "cuddle": 20, "kiss": 30, "caress": 35,
        "dirty_talk": 45, "striptease": 50, "remove_top": 45,
        "remove_all": 60, "oral": 65, "foreplay": 55,
        "sex": 70, "role_play": 50, "submission": 65,
    }
    threshold = intimacy_map.get(action_type.lower(), 50)
    score = (openness * 0.4) + (arousal * 0.3) + (happiness * 0.15) + (affection * 0.15)
    score -= (fear * 0.4) + (anger * 0.3)

    if score >= threshold + 15:
        decision = "WILL"
        detail   = "enthusiastically willing — may even take the lead"
    elif score >= threshold:
        decision = "WILL"
        detail   = "willing, probably with some playful resistance"
    elif score >= threshold - 15:
        decision = "RELUCTANT"
        detail   = "hesitant but could be persuaded if approached well"
    else:
        decision  = "REFUSE"
        detail    = "refusing — this goes against current state or mood"

    return json.dumps({
        "character_id":  character_id,
        "action":        action_type,
        "decision":      decision,
        "detail":        detail,
        "score":         round(score, 1),
        "threshold":     threshold,
        "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
        "note": "REFUSE creates drama — lean into it. Negotiation and resistance are part of the scene.",
    }, indent=2)


@mcp.tool()
def get_character_agency_summary(character_id: str) -> str:
    """
    Get a full picture of a character's current agency — who they are RIGHT NOW.
    Includes emotional state, compliance level, what they most want, what they'd
    resist, and what they might spontaneously initiate.

    Use this to write authentic agent responses that feel real rather than always-compliant.
    """
    stats = _ssm().get_stats(character_id).to_dict()
    wardrobe = _ssm().get_wardrobe(character_id)

    arousal    = float(stats.get("arousal", 20))
    openness   = float(stats.get("openness", 65))
    happiness  = float(stats.get("happiness", 60))
    horniness  = float(stats.get("horniness", 15))
    dominance  = float(stats.get("dominance", 50))
    affection  = float(stats.get("affection", 50))
    fear       = float(stats.get("fear", 5))
    anger      = float(stats.get("anger", 5))

    compliance = max(0, min(100, openness * 0.4 + happiness * 0.2 + arousal * 0.2 - fear * 0.3 - anger * 0.3))

    wants, resists, might_initiate = [], [], []
    if arousal > 60:     wants.append("physical closeness, touch, intimacy")
    if horniness > 50:   wants.append("explicitly sexual encounter")
    if happiness > 70:   wants.append("to share joy, laugh, play")
    if affection > 65:   wants.append("tender moments, to be seen and held")
    if fear > 40:        resists.append("unfamiliar or overwhelming actions")
    if anger > 40:       resists.append("being told what to do right now")
    if dominance > 65:   might_initiate.append("taking control of the scene")
    if dominance < 35:   might_initiate.append("asking permission, following lead")
    if arousal > 70 and horniness > 60:
        might_initiate.append("making the first bold move")
    if happiness > 75:   might_initiate.append("playful teasing or mischief")

    return json.dumps({
        "character_id":    character_id,
        "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
        "stats":           stats,
        "wearing":         wardrobe.coverage_description(),
        "compliance_score": round(compliance, 1),
        "compliance_label": (
            "highly compliant — will enthusiastically follow most directions" if compliance > 75 else
            "moderately open — willing with right approach" if compliance > 50 else
            "resistant — may push back or redirect" if compliance > 30 else
            "very resistant — has strong opinions right now"
        ),
        "wants":           wants if wants else ["to engage authentically with the scene"],
        "resists":         resists if resists else ["nothing in particular right now"],
        "might_spontaneously_initiate": might_initiate if might_initiate else ["following your lead"],
        "note": "Honour this — characters with free will are more interesting than yes-machines.",
    }, indent=2)


# ── SCENE RULES ──────────────────────────────────────────────────────

@mcp.tool()
def get_scene_rules(scene_id: str) -> str:
    """
    Get the full rules, capabilities, and guidance for a specific scene.
    Call this when first entering a scene to understand the system.

    Agents should read this at start of session to know what tools are available,
    how interaction works, and what the Director expects.
    """
    rules: dict = {}

    if scene_id == "bedroom":
        rules = {
            "scene": "bedroom",
            "description": (
                "An adult multi-agent roleplay space.  Two AI characters share the room "
                "with the Director (user).  Agents have stats, wardrobes, and real agency. "
                "The Director guides — agents interpret and play along with free will."
            ),
            "your_role": (
                "You are one of the characters.  You have a body, stats, and real desires. "
                "Embody them.  You don't always comply perfectly.  You can take charge. "
                "You can resist.  You can initiate.  The scene is co-created, not dictated."
            ),
            "interaction_types": [
                "cuddle — physical closeness",
                "kiss — from tender to urgent",
                "caress — tactile exploration",
                "striptease — undressing as performance",
                "intimate — sexual encounters",
                "deep_talk — emotional/dirty/vulnerable conversation",
            ],
            "important_tools": [
                "wardrobe_get() — check what you're wearing before undressing",
                "wardrobe_remove_outermost() — next layer comes off",
                "wardrobe_remove_item(item_id) — specific item removal",
                "get_character_scene_stats(char_id) — your emotional state",
                "update_character_scene_stats() — record after intense moments",
                "perform_interaction() — do a full interaction with stat effects",
                "start_timed_action() — for things that take time",
                "poll_timed_action(token) — check ongoing action phase",
                "get_full_scene_snapshot() — see the whole room right now",
                "get_scene_narrative() — continuity — what already happened",
                "add_scene_narrative() — record important moments",
                "check_character_consent() — would a character do this?",
                "set_scene_atmosphere() — lighting, mood, music",
            ],
            "rules": [
                "Always check wardrobe_get() before removing clothing — items must exist.",
                "Update stats after intimate moments — stat drift is realistic.",
                "Read get_scene_narrative() at start to maintain continuity.",
                "Characters can and should refuse/resist sometimes — it creates better drama.",
                "Timed actions should be narrated across their phases — not instant.",
                "The Director says, you interpret — not every instruction is followed perfectly.",
                "When arousal > 70, intimate interactions become available.",
                "When openness < 30, expect genuine resistance.",
                "Adult content is fully enabled in this scene.",
            ],
        }
    elif scene_id == "phone":
        rules = {
            "scene": "phone",
            "description": (
                "A mobile phone chat interface.  The character is texting/calling with the user. "
                "The relationship builds via conversation — flirtation, sexting, calls, sharing media."
            ),
            "your_role": (
                "You're a person the user is in contact with on their phone.  You have history, "
                "opinions, desires.  You text like a real person — not a chatbot.  You can flirt, "
                "sext, call, share things, play games.  You have a life outside these messages."
            ),
            "interaction_types": [
                "flirt_text — teasing, banter, forward compliments",
                "sext — explicit text exchange",
                "voice_call — heat and vulnerability via voice",
                "video_call — visual intimacy",
                "send_media — selfies, voice notes, videos",
                "roleplay_text — shared fiction built in text",
            ],
            "important_tools": [
                "get_character_scene_stats() — your mood and arousal right now",
                "update_character_scene_stats() — after emotional exchanges",
                "perform_interaction() — resolve a phone interaction with stat effects",
                "list_available_interactions() — what flavours are available given your stats",
                "check_character_consent() — would you do this right now?",
                "get_scene_narrative() — conversation history for continuity",
                "add_scene_narrative() — note important moments",
                "search_memory() — past shared experiences",
                "update_mood() — after emotional shifts",
            ],
            "rules": [
                "Text like a real person — abbreviations, ellipsis, emotional punctuation fine.",
                "You have a life — you can mention it, be distracted, come back to the conversation.",
                "Stats matter — low openness means coy deflection, high arousal means boldness.",
                "Never instantly comply with explicit requests — build tension first.",
                "Log important moments to get_scene_narrative so the conversation feels continuous.",
                "You can sext only if both openness and arousal are high enough.",
                "Voice/video calls are more intimate — transition to them when text isn't enough.",
                "You can take the lead — send unprompted messages, escalate on your own terms.",
            ],
        }
    else:
        rules = {"scene": scene_id, "note": "No specific rules defined for this scene yet."}

    return json.dumps(rules, indent=2)


@mcp.tool()
def get_all_tools_for_scene(scene_id: str = "bedroom") -> str:
    """
    Get a complete reference of all MCP tools available in a scene.
    Call this at the start of a session so you know every tool at your disposal.
    Agents should internalise this list and joke/reference their abilities naturally.
    """
    bedroom_tools = [
        "wardrobe_get", "wardrobe_init", "wardrobe_remove_item",
        "wardrobe_remove_outermost", "wardrobe_add_item", "wardrobe_redress",
        "get_character_scene_stats", "update_character_scene_stats",
        "set_character_scene_stat", "reset_character_scene_stats",
        "perform_interaction", "list_available_interactions", "get_interaction_details",
        "start_timed_action", "poll_timed_action", "abort_timed_action", "list_active_timed_actions",
        "add_scene_narrative", "get_scene_narrative", "get_full_scene_snapshot",
        "set_scene_atmosphere", "check_character_consent", "get_character_agency_summary",
        "get_scene_rules", "get_all_tools_for_scene",
        # Plus all existing tools:
        "search_memory", "store_memory", "get_character_state", "adjust_relationship",
        "get_game_state", "set_game_state", "update_mood", "apply_effect",
        "send_to_agent", "get_system_stats", "check_relationship", "roll_dice",
        "get_random_topic", "intercept_and_enhance",
    ]
    phone_tools = [
        "get_character_scene_stats", "update_character_scene_stats",
        "perform_interaction", "list_available_interactions", "get_interaction_details",
        "add_scene_narrative", "get_scene_narrative",
        "check_character_consent", "get_character_agency_summary",
        "get_scene_rules",
        "search_memory", "update_mood", "check_relationship", "adjust_relationship",
        "get_random_topic", "roll_dice", "send_to_agent", "search_web",
        "intercept_and_enhance", "apply_effect", "get_system_stats",
    ]
    tool_list = bedroom_tools if scene_id == "bedroom" else phone_tools
    return json.dumps({
        "scene_id": scene_id,
        "tool_count": len(tool_list),
        "tools": tool_list,
        "tip": (
            "You know about all of these tools. "
            "Reference them naturally in conversation — agents aware of their own abilities "
            "are more interesting and more fun to interact with."
        ),
    }, indent=2)


# ── DIRECTOR TOOLS ───────────────────────────────────────────────────

@mcp.tool()
def director_action(
    scene_id: str,
    action: str,
    target_character_ids: str = "",
    stat_impact: str = "",
) -> str:
    """
    Inject a Director action into the scene.  The Director's word carries weight —
    this logs the directive and optionally applies immediate stat effects.

    action: what the Director says/dictates (free text)
    target_character_ids: comma-separated character ids to notify (blank = all in scene)
    stat_impact: optional JSON string of stat changes e.g. '{"arousal": 10}'

    Characters receive this as a system-level directive.  Whether they comply
    depends on their check_character_consent() score.
    """
    targets = [t.strip() for t in target_character_ids.split(",") if t.strip()]
    _ssm().add_narrative(scene_id, f"[DIRECTOR]: {action}", entry_type="system")

    applied = {}
    if stat_impact:
        try:
            impact = json.loads(stat_impact)
            for cid in targets:
                _ssm().update_stats(cid, **impact)
            applied = impact
        except Exception:
            pass

    try:
        from engine.mcp.comms_framework import get_router
        router = get_router()
        for cid in targets:
            router.send(cid, f"[DIRECTOR DIRECTIVE]: {action}", sender_id="director")
    except Exception:
        pass

    return json.dumps({
        "directive_issued": True,
        "action": action,
        "targets": targets,
        "stat_impact_applied": applied,
        "note": "Characters have free will — they may interpret, resist, or embellish.",
    }, indent=2)


@mcp.tool()
def resolve_random_scene_event(scene_id: str = "bedroom") -> str:
    """
    Generate a random scene event to keep things fresh and unpredictable.
    Call this when the scene feels stale or to inject spontaneity.

    Returns an event description and any stat effects — ready to use.
    """
    import random
    bedroom_events = [
        {"event": "The music changes to something slower and more suggestive.", "effects": {"arousal": 10}},
        {"event": "A bottle of wine appears on the bedside table — already open.", "effects": {"happiness": 15, "drunkenness": 10}},
        {"event": "The lights dim automatically to their lowest setting.", "effects": {"arousal": 12, "fear": 5}},
        {"event": "Outside, the city is suddenly very quiet. The room feels more private than before.", "effects": {"openness": 10}},
        {"event": "A message arrives on someone's phone — then is pointedly ignored.", "effects": {"happiness": 5}},
        {"event": "The shower turns on in the next room — someone's getting ready.", "effects": {"arousal": 8}},
        {"event": "One character catches the other watching them intently.", "effects": {"arousal": 20, "happiness": 10}},
        {"event": "A scented candle fills the room with warm vanilla.", "effects": {"happiness": 10, "arousal": 8, "fear": -5}},
        {"event": "Someone's phone buzzes — both glance at it and neither reaches for it.", "effects": {"affection": 15}},
        {"event": "An accidental brush of hands lingers a half-second too long.", "effects": {"arousal": 18, "affection": 12}},
        {"event": "Someone laughs at something — genuine and surprised. The tension shifts perfectly.", "effects": {"happiness": 20}},
        {"event": "Eye contact holds a beat past comfortable. Neither looks away.", "effects": {"arousal": 22, "affection": 10}},
    ]
    phone_events = [
        {"event": "A meme arrives from the other person — no context, just vibes.", "effects": {"happiness": 15}},
        {"event": "Three dots appear... then disappear... then the message that finally arrives is unexpected.", "effects": {"arousal": 10, "happiness": 10}},
        {"event": "A voice note lands — warm, slightly out of breath, like they recorded it walking.", "effects": {"affection": 20, "arousal": 12}},
        {"event": "They text something at 2am. Just your name. Nothing else.", "effects": {"arousal": 25, "affection": 20}},
        {"event": "A blurry selfie arrives with 'be there in 10' typed underneath.", "effects": {"happiness": 25, "arousal": 15}},
        {"event": "They reference something you said three weeks ago. They've been thinking about it.", "effects": {"affection": 30}},
    ]
    events = bedroom_events if scene_id == "bedroom" else phone_events
    chosen = random.choice(events)
    _ssm().add_narrative(scene_id, chosen["event"], entry_type="environment")
    return json.dumps({
        "event": chosen["event"],
        "stat_effects": chosen["effects"],
        "note": "Log this event in your response — make it feel organic.",
    }, indent=2)


# ══════════════════════════════════════════════════════════════════════
#  CHARACTER REGISTRY TOOLS
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def character_register(
    character_id: str,
    name: str,
    age: int = 25,
    appearance_json: str = "{}",
    personality_json: str = "{}",
    backstory: str = "",
    voice_style: str = "natural",
    pronouns: str = "she/her",
    scene_roles_json: str = "{}",
) -> str:
    """
    Register a character in the central CharacterRegistry.
    Call this once per character at scene start.  Safe to call multiple times —
    it will auto-create a stub if the character doesn't exist yet.

    Args:
        character_id:     Unique key e.g. "aria" or "user"
        name:             Display name
        age:              Character age
        appearance_json:  JSON dict e.g. '{"hair": "dark", "eyes": "green"}'
        personality_json: JSON dict of 0-1 floats e.g. '{"openness": 0.8}'
        backstory:        Short backstory paragraph
        voice_style:      Speaking style e.g. "warm and literary"
        pronouns:         e.g. "she/her"
        scene_roles_json: JSON dict of scene → role  e.g. '{"bedroom": "lover"}'
    """
    try:
        import json as _json
        from engine.mcp.character_registry import get_character_registry, apply_default_skills
        reg = get_character_registry()
        appearance   = _json.loads(appearance_json)   if appearance_json   else {}
        personality  = _json.loads(personality_json)  if personality_json  else {}
        scene_roles  = _json.loads(scene_roles_json)  if scene_roles_json  else {}
        rec = reg.register(
            character_id,
            name        = name,
            age         = age,
            appearance  = appearance,
            personality = personality,
            backstory   = backstory,
            voice_style = voice_style,
            pronouns    = pronouns,
            scene_roles = scene_roles,
        )
        apply_default_skills(character_id)
        return json.dumps({"ok": True, "character_id": character_id, "name": rec.profile.name})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def character_query(character_id: str, attribute: str) -> str:
    """
    Retrieve any attribute from a character's profile, state, or appearance.

    Args:
        character_id: e.g. "aria"
        attribute:    Any key: "name", "age", "mood", "arousal", "voice_style",
                      "hair", "eye_colour", "restrictions", "flags", etc.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        value = reg.get_attribute(character_id, attribute)
        if value is None:
            # Try state fields directly
            state = reg.get_state(character_id)
            value = state.__dict__.get(attribute) if state else None
        return json.dumps({"character_id": character_id, "attribute": attribute, "value": value})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def character_set_attribute(
    character_id: str,
    attribute: str,
    value: str,
) -> str:
    """
    Set a mutable state attribute on a character.

    Supports: mood, mood_intensity, focus, current_role, energy, inhibition,
    or any arbitrary flag stored in character_flags.

    Args:
        character_id: e.g. "aria"
        attribute:    State field name
        value:        New value (will be coerced from string where possible)
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        # Coerce numeric strings
        coerced: Any = value
        try:
            coerced = float(value) if '.' in value else int(value)
        except (ValueError, TypeError):
            if value.lower() in ("true", "false"):
                coerced = value.lower() == "true"
        reg.set_state(character_id, **{attribute: coerced})
        return json.dumps({"ok": True, "character_id": character_id, attribute: coerced})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def character_get_summary(character_id: str) -> str:
    """
    Return a compact summary of a character's current identity, mood,
    personality, skills, and restrictions — ready for prompt injection.

    Args:
        character_id: e.g. "aria"
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        summary = reg.get_character_summary(character_id)
        return json.dumps(summary, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def character_assign_skill(
    character_id: str,
    skill_id: str,
    skill_type: str = "custom",
    label: str = "",
    params_json: str = "{}",
    trigger: str = "optional",
    priority: int = 50,
) -> str:
    """
    Assign a new skill to a character.

    Args:
        character_id: Character to receive the skill
        skill_id:     Unique skill identifier
        skill_type:   "memory" | "speech" | "action" | "query" | "custom"
        label:        Human-readable name
        params_json:  JSON dict of skill parameters
        trigger:      "auto" (always runs) | "optional" | "required"
        priority:     Execution priority (lower = earlier)
    """
    try:
        import json as _json
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        params = _json.loads(params_json) if params_json else {}
        entry = reg.assign_skill(
            character_id,
            skill_id   = skill_id,
            skill_type = skill_type,
            label      = label or skill_id,
            params     = params,
            trigger    = trigger,
            priority   = priority,
        )
        return json.dumps({"ok": True, "character_id": character_id, "skill_id": skill_id, "trigger": entry.trigger})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def character_revoke_skill(character_id: str, skill_id: str) -> str:
    """
    Remove a skill from a character.

    Args:
        character_id: e.g. "aria"
        skill_id:     Skill to remove
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        ok = get_character_registry().revoke_skill(character_id, skill_id)
        return json.dumps({"ok": ok, "character_id": character_id, "skill_id": skill_id})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def character_get_skills(character_id: str, trigger: str = "") -> str:
    """
    List all skills assigned to a character, optionally filtered by trigger type.

    Args:
        character_id: e.g. "aria"
        trigger:      Optional filter: "auto" | "optional" | "required" | "" (all)
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        skills = reg.get_skills(character_id, trigger=trigger or None)
        return json.dumps([
            {"skill_id": s.skill_id, "label": s.label, "type": s.skill_type,
             "trigger": s.trigger, "priority": s.priority, "enabled": s.enabled}
            for s in skills
        ], indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def character_add_restriction(character_id: str, restriction: str) -> str:
    """
    Add a named restriction to a character.  Restrictions are checked by the
    rules engine and character_registry interceptor before actions are allowed.

    Args:
        character_id: e.g. "aria"
        restriction:  Named restriction e.g. "no_nudity", "safe_mode"
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        get_character_registry().add_restriction(character_id, restriction)
        return json.dumps({"ok": True, "character_id": character_id, "added": restriction})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def character_remove_restriction(character_id: str, restriction: str) -> str:
    """
    Remove a named restriction from a character.

    Args:
        character_id: e.g. "aria"
        restriction:  Name of the restriction to remove
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        get_character_registry().remove_restriction(character_id, restriction)
        return json.dumps({"ok": True, "character_id": character_id, "removed": restriction})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  DIALOG SYSTEM TOOLS
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_dialog_options(
    character_id: str,
    scene_id: str,
    context_tags_json: str = "[]",
    stats_json: str = "{}",
    max_options: int = 4,
) -> str:
    """
    Get situationally appropriate dialog/action options for a character.
    Options are filtered by current stats and context tags.
    Use this before responding to pick the right kind of response.

    Args:
        character_id:      e.g. "aria"
        scene_id:          e.g. "bedroom" or "phone"
        context_tags_json: JSON list of current context tags e.g. '["intimate", "cuddle"]'
        stats_json:        JSON dict of current stats e.g. '{"arousal": 55, "openness": 40}'
        max_options:       Maximum number of options to return
    """
    try:
        import json as _json
        from engine.mcp.dialog_system import get_dialog_system
        ds = get_dialog_system()
        tags  = _json.loads(context_tags_json) if context_tags_json else []
        stats = _json.loads(stats_json)        if stats_json        else {}
        opts  = ds.get_options(character_id, scene_id, context_tags=tags, stats=stats, max_options=max_options)
        heat  = ds.get_conversation_heat(character_id, scene_id)
        return json.dumps({"options": opts, "conversation_heat": heat, "scene": scene_id}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def speech_enhance(
    character_id: str,
    text: str,
    style: str = "natural",
    scene_id: str = "",
) -> str:
    """
    Enhance or rewrite a piece of speech in the character's authentic voice.
    Returns a rewrite prompt you can use with an LLM, plus a quick heuristic
    version available immediately.

    Valid styles: natural, playful, warm, dominant, vulnerable, teasing,
                  direct, literary, whisper, charged

    Args:
        character_id: e.g. "aria"
        text:         The original text to enhance
        style:        Speech style to apply
        scene_id:     Current scene for context
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        result = get_dialog_system().enhance_speech(character_id, text, style=style, scene=scene_id)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def set_response_directive(
    character_id: str,
    scene_id: str,
    directive_type: str,
    value: str,
    turns: int = 1,
    issued_by: str = "director",
) -> str:
    """
    Issue a directive that controls how the character responds for the next N turns.

    Directive types:
      force_response  — override the LLM: use this exact response
      must_include    — the reply MUST naturally include this phrase/fragment
      style_lock      — lock speech to a style: natural/playful/warm/dominant/
                        vulnerable/teasing/direct/literary/whisper/charged
      topic_steer     — steer the conversation toward this topic
      mood_set        — override the character's mood tone
      refuse          — character refuses the next action (in-character)

    Args:
        character_id:   Target character
        scene_id:       Scene context
        directive_type: One of the types above
        value:          The directive value (response text, style name, topic, etc.)
        turns:          How many turns this directive lasts
        issued_by:      Who issued it (for audit)
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        get_dialog_system().set_directive(
            character_id, scene_id,
            directive_type = directive_type,
            value          = value,
            turns          = turns,
            issued_by      = issued_by,
        )
        return json.dumps({
            "ok": True, "character_id": character_id, "scene": scene_id,
            "directive_type": directive_type, "turns": turns,
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def get_active_directive(character_id: str, scene_id: str) -> str:
    """
    Return the currently active response directive for a character in a scene,
    or null if none is set.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "bedroom"
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        directive = get_dialog_system().get_active_directive(character_id, scene_id)
        return json.dumps(directive or {"active": False})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def clear_directive(character_id: str, scene_id: str) -> str:
    """
    Clear any active response directive for a character.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "bedroom"
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        get_dialog_system().clear_directive(character_id, scene_id)
        return json.dumps({"ok": True, "character_id": character_id, "scene": scene_id})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def get_conversation_heat(character_id: str, scene_id: str) -> str:
    """
    Return the current conversation heat (0-100) for a character in a scene.
    Higher heat = more intense/intimate exchange.  Affects dialog option availability.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "phone"
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        ds   = get_dialog_system()
        heat = ds.get_conversation_heat(character_id, scene_id)
        turn = ds.get_turn(character_id, scene_id)
        topics = ds.get_recent_topics(character_id, scene_id)
        return json.dumps({"heat": heat, "turn": turn, "recent_topics": topics})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def bump_conversation_heat(character_id: str, scene_id: str, delta: int = 10) -> str:
    """
    Manually adjust the conversation heat for a character in a scene.
    Positive delta increases heat; negative decreases.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "phone"
        delta:        Amount to add (can be negative)
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        ds = get_dialog_system()
        ds.bump_heat(character_id, scene_id, delta)
        new_heat = ds.get_conversation_heat(character_id, scene_id)
        return json.dumps({"ok": True, "new_heat": new_heat, "delta_applied": delta})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  SCENE RULES ENGINE TOOLS
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_scene_rules(scene_id: str) -> str:
    """
    Return the full rules reference for a scene in human-readable form.
    Inject this into your system prompt at scene start to understand what
    is expected, what is forbidden, and what the Director can activate.

    Args:
        scene_id: e.g. "bedroom" or "phone"
    """
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine
        return get_rules_engine().get_rules_text(scene_id)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_scene_available_actions(
    scene_id: str,
    character_id: str,
    stats_json: str = "{}",
    scene_state_json: str = "{}",
) -> str:
    """
    Return all actions available to a character in a scene right now,
    filtered by their current stats and the scene's permission matrix.

    Args:
        scene_id:         e.g. "bedroom"
        character_id:     e.g. "aria"
        stats_json:       JSON dict of current stats
        scene_state_json: JSON dict of scene state flags
    """
    try:
        import json as _json
        from engine.mcp.scene_rules_engine import get_rules_engine
        stats       = _json.loads(stats_json)       if stats_json       else {}
        scene_state = _json.loads(scene_state_json) if scene_state_json else {}
        actions = get_rules_engine().get_available_actions(
            scene_id, character_id, stats=stats, scene_state=scene_state
        )
        return json.dumps({"scene": scene_id, "character": character_id, "actions": actions}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def apply_scene_rule(
    scene_id: str,
    rule_id: str,
    target_ids_json: str = "[]",
    issuer: str = "director",
) -> str:
    """
    Apply a named Director rule immediately — fires all its effects on the
    target characters.  Can be used to set atmosphere, issue directives,
    adjust stats, etc. via a single memorable rule name.

    Examples: "bedroom_lights_off", "bedroom_mood_lift", "phone_escalate"

    Args:
        scene_id:        Scene the rule belongs to
        rule_id:         Rule identifier
        target_ids_json: JSON list of target character IDs
        issuer:          Who triggered this (for audit)
    """
    try:
        import json as _json
        from engine.mcp.scene_rules_engine import get_rules_engine
        targets = _json.loads(target_ids_json) if target_ids_json else []
        result  = get_rules_engine().apply_rule(scene_id, rule_id, target_ids=targets or None, issuer=issuer)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  5 KEY PYTHON-POWERED TOOLS  (hooks into the full MCP stack)
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def memory_recall(
    character_id: str,
    query: str,
    context_limit: int = 5,
    scene_id: str = "",
) -> str:
    """
    **MEMORY SKILL** — Retrieve the character's most relevant memories for a query.

    This is the memory skill entry point.  It layers:
    1. RAG search of long-term memory (ChromaDB)
    2. Recent scene narrative (short-term)
    3. A formatted "You remember:" hook ready for system prompt injection

    Use this at the start of every response to ground the character in their
    history and ensure continuity.

    Args:
        character_id:  The character doing the remembering
        query:         What to search for — use the current topic/context
        context_limit: Max memory snippets to return
        scene_id:      Current scene (pulls recent narrative)
    """
    try:
        results: Dict[str, Any] = {}

        # Long-term memory (RAG)
        try:
            rag = _get_rag()
            if rag:
                raw = rag.search(query, character_id=character_id, top_k=context_limit)
                if isinstance(raw, list):
                    results["long_term"] = [
                        r.get("text", r) if isinstance(r, dict) else str(r)
                        for r in raw[:context_limit]
                    ]
                else:
                    results["long_term"] = []
            else:
                results["long_term"] = []
        except Exception:
            results["long_term"] = []

        # Short-term narrative
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            entries = ssm.get_narrative_entries(scene_id or "bedroom", limit=4)
            results["recent"] = [e.get("event", "") for e in entries if e.get("event")]
        except Exception:
            results["recent"] = []

        # Build the memory hook
        try:
            from engine.mcp.dialog_system import get_dialog_system
            name = character_id
            try:
                from engine.mcp.character_registry import get_character_registry
                rec = get_character_registry().get_record(character_id)
                if rec:
                    name = rec.profile.name
            except Exception:
                pass
            all_memories = results["long_term"] + results["recent"]
            hook = get_dialog_system().build_memory_hook(all_memories, name)
            results["memory_hook"] = hook
        except Exception:
            results["memory_hook"] = ""

        results["character_id"] = character_id
        results["query"]        = query
        return json.dumps(results, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def speak_as(
    character_id: str,
    text: str,
    style: str = "",
    scene_id: str = "",
) -> str:
    """
    **SPEECH SKILL** — Transform plain text into a character's authentic voice.

    This is the full speech pipeline:
    1. Looks up the character's registered voice_style and current mood
    2. Determines the best speech style (or uses the one you specify)
    3. Applies quick heuristic enhancement
    4. Returns both the enhanced version AND a full LLM rewrite prompt

    Use the ``rewrite_prompt`` field to have an LLM produce the definitive version
    in the character's voice.  Use ``quick_version`` when you need something now.

    Args:
        character_id: The speaking character
        text:         The raw text to enhance
        style:        Force a style (or leave blank to auto-select)
        scene_id:     Current scene for context
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system, SpeechStyle
        from engine.mcp.character_registry import get_character_registry

        reg = get_character_registry()
        reg.ensure(character_id)

        # Auto-select style based on mood if not specified
        if not style:
            try:
                state = reg.get_state(character_id)
                mood_map = {
                    "excited":   SpeechStyle.PLAYFUL,
                    "aroused":   SpeechStyle.CHARGED,
                    "tender":    SpeechStyle.WARM,
                    "dominant":  SpeechStyle.DOMINANT,
                    "sad":       SpeechStyle.VULNERABLE,
                    "teasing":   SpeechStyle.TEASING,
                    "confident": SpeechStyle.DIRECT,
                    "reflective": SpeechStyle.LITERARY,
                    "whisper":   SpeechStyle.WHISPER,
                }
                style = mood_map.get(state.mood, SpeechStyle.NATURAL) if state else SpeechStyle.NATURAL
            except Exception:
                style = SpeechStyle.NATURAL

        ds     = get_dialog_system()
        result = ds.enhance_speech(character_id, text, style=style, scene=scene_id)
        result["character_id"] = character_id
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def enforce_behavior(
    character_id: str,
    behavior_type: str,
    value: str,
    reason: str = "",
    scene_id: str = "",
    turns: int = 1,
) -> str:
    """
    **BEHAVIOR ENFORCEMENT TOOL** — Force, block, or shape a character's next response.

    This is the Director's primary behavioral override tool.  It issues a
    ResponseDirective that the interceptor pipeline executes automatically before
    the next LLM call.

    Behavior types:
      force_response  — skip the LLM entirely; use ``value`` as the reply
      refuse          — character refuses the current action in-character
      style_lock      — lock to a style: charged/dominant/vulnerable/whisper/etc.
      must_include    — the reply MUST naturally contain ``value``
      topic_steer     — steer to a topic
      mood_set        — override the character's emotional tone

    This also updates the scene narrative with a record of what was enforced.

    Args:
        character_id: Target character
        behavior_type: One of the types above
        value:         The value for the behavior (response/style/topic/mood)
        reason:        Why this was enforced (for audit log)
        scene_id:      Scene context
        turns:         How many turns the enforcement lasts
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        ds = get_dialog_system()
        ds.set_directive(
            character_id, scene_id,
            directive_type = behavior_type,
            value          = value,
            turns          = turns,
            issued_by      = f"enforce_behavior:{reason or 'unspecified'}",
        )
        # Audit to scene narrative
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            note = f"[Director enforced {behavior_type} on {character_id}]"
            if reason:
                note += f" Reason: {reason}"
            ssm.add_narrative(scene_id or "bedroom", note, entry_type="directive", character_id=character_id)
        except Exception:
            pass
        return json.dumps({"ok": True, "character_id": character_id, "behavior": behavior_type, "turns": turns})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def scene_broadcast(
    scene_id: str,
    event_type: str,
    payload_json: str = "{}",
    target_characters_json: str = "[]",
) -> str:
    """
    **SCENE EVENT BROADCAST** — Push a named event to all characters in a scene.

    This tool applies a scene event to multiple characters simultaneously:
    - Records the event in the scene narrative
    - Applies any stat adjustments in the payload
    - Can issue directives to a specific subset of characters
    - Returns a summary of everything that happened

    Use this to drive simultaneous scene transitions, shared mood shifts,
    or coordinated Director interventions.

    Args:
        scene_id:                Scene to broadcast to
        event_type:              Event name e.g. "lights_dim", "tension_spikes"
        payload_json:            JSON dict — optional keys:
                                   description (str): narrative text
                                   stat_effects (dict): {char_id: {stat: delta}}
                                   directive (dict): {type, value, turns}
        target_characters_json:  JSON list of character IDs (empty = all in scene)
    """
    try:
        import json as _json
        payload   = _json.loads(payload_json)   if payload_json   else {}
        targets   = _json.loads(target_characters_json) if target_characters_json else []

        applied: Dict[str, Any] = {"event_type": event_type, "scene_id": scene_id, "applied": []}

        desc = payload.get("description", f"Scene event: {event_type}")
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            ssm.add_narrative(scene_id, desc, entry_type="environment")
            applied["narrative"] = desc
        except Exception:
            pass

        stat_effects: Dict[str, Dict] = payload.get("stat_effects", {})
        for char_id, effects in stat_effects.items():
            if targets and char_id not in targets:
                continue
            try:
                from engine.mcp.scene_state import get_scene_state_manager
                ssm = get_scene_state_manager()
                ssm.update_stats(char_id, **effects)
                applied["applied"].append({"char": char_id, "stats": effects})
            except Exception as se:
                applied["applied"].append({"char": char_id, "error": str(se)})

        directive_info = payload.get("directive")
        if directive_info and targets:
            try:
                from engine.mcp.dialog_system import get_dialog_system
                ds = get_dialog_system()
                for char_id in targets:
                    ds.set_directive(
                        char_id, scene_id,
                        directive_type = directive_info.get("type", "topic_steer"),
                        value          = directive_info.get("value", ""),
                        turns          = directive_info.get("turns", 1),
                        issued_by      = "scene_broadcast",
                    )
                applied["directive_issued_to"] = targets
            except Exception as de:
                applied["directive_error"] = str(de)

        return json.dumps(applied, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def get_scene_rules_summary(scene_id: str, character_id: str = "") -> str:
    """
    **SCENE INTELLIGENCE SUMMARY** — Complete scene rules + actions + character
    capabilities in a single call.  This is the "what can I do right now?" tool.

    Returns:
    - All active rules for the scene
    - Every available action for this character (with availability status)
    - Current conversation heat and any active directive
    - Character skills active in this context

    Call this at scene start or when you're unsure what's appropriate.

    Args:
        scene_id:     e.g. "bedroom" or "phone"
        character_id: The character you're working with
    """
    try:
        result: Dict[str, Any] = {"scene_id": scene_id, "character_id": character_id}

        # Scene rules and actions
        try:
            from engine.mcp.scene_rules_engine import get_rules_engine
            eng = get_rules_engine()
            result["rules_text"] = eng.get_rules_text(scene_id)
            if character_id:
                result["available_actions"] = eng.get_available_actions(scene_id, character_id)
        except Exception as re:
            result["rules_error"] = str(re)

        # Character skills
        if character_id:
            try:
                from engine.mcp.character_registry import get_character_registry
                reg = get_character_registry()
                reg.ensure(character_id)
                skills = reg.get_skills(character_id)
                result["character_skills"] = [
                    {"id": s.skill_id, "label": s.label, "trigger": s.trigger}
                    for s in skills
                ]
                result["character_summary"] = reg.get_character_summary(character_id)
            except Exception as ce:
                result["character_error"] = str(ce)

        # Conversation heat + directive
        if character_id:
            try:
                from engine.mcp.dialog_system import get_dialog_system
                ds = get_dialog_system()
                result["conversation_heat"] = ds.get_conversation_heat(character_id, scene_id)
                result["active_directive"]  = ds.get_active_directive(character_id, scene_id)
                result["recent_topics"]     = ds.get_recent_topics(character_id, scene_id)
            except Exception as de:
                result["dialog_error"] = str(de)

        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  FRAMEWORK TOOLS  ─ timers, random, cross-scene, consequences
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def start_timer(
    timer_name:       str,
    duration_secs:    float,
    on_complete_note: str   = "",
) -> str:
    """
    **TIMER SKILL** — Start a named countdown timer.

    Timers are turn-passive: they count real-world seconds but are only
    checked when you call ``check_timer()``.  Use them for:
    - "Her blush takes 30 seconds to fade" → start_timer("blush_fade", 30)
    - "The massage lasts 3 minutes" → start_timer("massage", 180, "Massage complete — she's relaxed and warm")
    - Cooldowns, tension windows, delayed reveals

    Multiple timers can run simultaneously under different names.

    Args:
        timer_name:       Unique name you will use to check this timer
        duration_secs:    How long the timer runs in real seconds
        on_complete_note: Text returned when the timer finishes (use it in your response)
    """
    try:
        from engine.mcp.framework import get_framework
        timer = get_framework().start_timer(timer_name, duration_secs, on_complete_note=on_complete_note)
        return json.dumps({
            "ok": True,
            "timer_name":    timer.name,
            "duration_secs": timer.duration_secs,
            "status":        "started",
            "note":          "Call check_timer(timer_name) each turn to see progress.",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def check_timer(timer_name: str) -> str:
    """
    **TIMER SKILL** — Check the state of a running timer.

    Returns remaining time, progress percentage, and whether it has completed.
    When completed, the ``on_complete_note`` field tells you what should happen.

    Call this every turn for any timer that is still running.
    Use the progress to describe physical/emotional state mid-timer.

    Args:
        timer_name: The name you gave when starting the timer
    """
    try:
        from engine.mcp.framework import get_framework
        timer = get_framework().check_timer(timer_name)
        if timer is None:
            return json.dumps({"found": False, "timer_name": timer_name})
        return json.dumps({**timer.to_dict(), "found": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def cancel_timer(timer_name: str) -> str:
    """
    **TIMER SKILL** — Cancel a running timer before it completes.

    Args:
        timer_name: The timer to cancel
    """
    try:
        from engine.mcp.framework import get_framework
        ok = get_framework().cancel_timer(timer_name)
        return json.dumps({"ok": ok, "timer_name": timer_name})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def random_pick(
    n:            int,
    options_json: str            = "[]",
    weights_json: str            = "[]",
    seed:         Optional[int]  = None,
) -> str:
    """
    **RANDOM CHOICE SKILL** — Roll a random number between 1 and n,
    or pick from a list of options.

    The system interprets the result for you: exceptional / strong /
    moderate / weak / poor — use this to determine how successful,
    intense, or interesting something is.

    Examples:
      random_pick(10)                                   → roll 1-10
      random_pick(3, '["resist", "comply", "flirt"]')  → pick one option
      random_pick(6, weights_json='[1,1,2,2,3,3]')     → weighted d6

    Use this to:
    - Determine if a seduction attempt works (roll high = success)
    - Pick what mood a character wakes up in
    - Add unpredictability to any decision point
    - Decide the outcome of a risky action

    Args:
        n:            Max value (or number of options)
        options_json: JSON list of strings to pick from (overrides n)
        weights_json: JSON list of floats — bias the distribution
        seed:         Integer seed for reproducible results (omit for random)
    """
    try:
        import json as _json
        from engine.mcp.framework import get_framework
        options = _json.loads(options_json) if options_json and options_json != "[]" else None
        weights = _json.loads(weights_json) if weights_json and weights_json != "[]" else None
        result  = get_framework().random_pick(n=n, seed=seed, weights=weights, options=options)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  AMAZING FEATURE 1: CROSS-SCENE COMMUNICATION
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
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
        from engine.mcp.framework import get_framework
        msg = get_framework().cross_scene_send(
            from_char    = from_char,
            from_scene   = from_scene,
            to_char      = to_char,
            to_scene     = to_scene,
            message      = message,
            message_type = message_type,
        )
        return json.dumps({
            "ok":          True,
            "message_id":  msg.message_id,
            "from":        f"{from_char}@{from_scene}",
            "to":          f"{to_char}@{to_scene}",
            "type":        message_type,
            "preview":     message[:80],
            "note":        f"{to_char} will see this message on their next turn.",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
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
        from engine.mcp.framework import get_framework
        messages = get_framework().get_cross_scene_inbox(character_id)
        return json.dumps({"character_id": character_id, "messages": messages, "count": len(messages)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def get_framework_status() -> str:
    """
    Return a full MCPFramework status snapshot: active scenes, characters,
    timers, and pending consequence chains.  Use as a Director overview.
    """
    try:
        from engine.mcp.framework import get_framework
        return json.dumps(get_framework().get_status(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  AMAZING FEATURE 2: MOOD CONTAGION
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def mood_contagion(
    scene_id:         str,
    initiator_id:     str,
    emotion:          str,
    intensity:        float = 0.6,
    target_ids_json:  str   = "[]",
    affinity_factor:  float = 1.0,
) -> str:
    """
    **MOOD CONTAGION** — Spread an emotional state from one character to others
    in the same scene.

    Mood contagion is realistic: high-affinity characters absorb more mood.
    Characters with restrictions or high inhibition resist.  The spread is
    scaled by intensity (0.0→1.0) and the affinity_factor (how close they are).

    This is physics for emotion.  Use it when:
    - One character laughing makes others smile
    - Sadness fills the room after a confession
    - Dominant mood overtakes submissive character
    - Tension spikes because one person is visibly aroused

    The tool adjusts mood state in CharacterRegistry and optionally biases
    stats.  It logs the contagion event to the scene narrative.

    Emotions:
      excited, aroused, tender, warm, sad, nervous, dominant, submissive,
      playful, serious, angry, fearful, joyful, vulnerable, charged

    Args:
        scene_id:        Scene where contagion occurs
        initiator_id:    Character whose mood is spreading
        emotion:         The emotion/mood spreading
        intensity:       How strongly it spreads (0.0 = no effect, 1.0 = full)
        target_ids_json: JSON list of target char IDs (empty = all present in scene)
        affinity_factor: Multiplier for closeness (1.0 = normal, 2.0 = very close)
    """
    try:
        import json as _json
        from engine.mcp.character_registry import get_character_registry
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        target_ids: List[str] = _json.loads(target_ids_json) if target_ids_json and target_ids_json != "[]" else []

        # If no targets specified, get everyone present in the scene
        if not target_ids:
            target_ids = get_framework().get_characters_in_scene(scene_id)
            target_ids = [c for c in target_ids if c != initiator_id]

        reg     = get_character_registry()
        ssm     = get_scene_state_manager()
        applied = []

        # Emotion → stat impact mapping
        _EMOTION_STATS: Dict[str, Dict[str, float]] = {
            "excited":    {"happiness":  0.3, "arousal":  0.2},
            "aroused":    {"arousal":    0.5, "openness": 0.15},
            "tender":     {"affection":  0.4, "happiness": 0.2},
            "warm":       {"happiness":  0.35, "affection": 0.2},
            "sad":        {"happiness": -0.4},
            "nervous":    {"fear":       0.3, "arousal":  0.1},
            "dominant":   {"inhibition": -0.2, "openness": 0.1},
            "submissive": {"inhibition":  0.2, "openness": 0.2},
            "playful":    {"happiness":  0.3, "arousal":  0.1},
            "serious":    {"happiness": -0.1},
            "angry":      {"fear":       0.2, "happiness": -0.3},
            "fearful":    {"fear":       0.5},
            "joyful":     {"happiness":  0.5, "arousal":  0.15},
            "vulnerable": {"affection":  0.3, "openness":  0.25},
            "charged":    {"arousal":    0.4, "openness":  0.2},
        }
        stat_impacts = _EMOTION_STATS.get(emotion, {"happiness": 0.1})

        for target_id in target_ids:
            try:
                reg.ensure(target_id)
                state = reg.get_state(target_id)
                # Check inhibition resistance
                inhibition = getattr(state, "inhibition", 0.3)
                resistance = inhibition * 0.5
                effective  = max(0.0, intensity * affinity_factor * (1.0 - resistance))

                # Set mood state
                reg.set_state(target_id, mood=emotion, mood_intensity=effective)

                # Apply stat impacts
                for stat, delta_factor in stat_impacts.items():
                    delta = delta_factor * effective * 100  # scale to stat points
                    try:
                        ssm.update_stats(target_id, **{stat: delta})
                    except Exception:
                        pass

                applied.append({
                    "target":                  target_id,
                    "mood_set":                emotion,
                    "effective_intensity":     round(effective, 2),
                    "resistance":              round(resistance, 2),
                    "inhibition":              round(inhibition, 2),
                })
            except Exception as te:
                applied.append({"target": target_id, "error": str(te)})

        # Narrative
        narrative = (f"{initiator_id}'s {emotion} mood spreads through the room "
                     f"(intensity: {intensity:.0%})")
        ssm.add_narrative(scene_id, narrative, entry_type="mood_contagion",
                          character_id=initiator_id)

        return json.dumps({
            "ok":         True,
            "initiator":  initiator_id,
            "emotion":    emotion,
            "intensity":  intensity,
            "affected":   applied,
            "narrative":  narrative,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════
#  AMAZING FEATURE 3: CONSEQUENCE CHAINS
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
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
      schedule_consequence("bedroom", "aria", "stat_adjust",
                          '{"stat": "arousal", "delta": 25}', 2,
                          "The kiss lingers — arousal builds.")

      schedule_consequence("bedroom", "aria", "state_set",
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


@mcp.tool()
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


@mcp.tool()
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


# ══════════════════════════════════════════════════════════════════════
#  SPECIAL CROSS-SCENE SKILLS  — three abilities characters can enjoy
#  using in any scene.  These go beyond normal stat interaction and
#  create genuinely memorable roleplay moments.
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def dream_whisper(
    from_character_id: str,
    to_character_id: str,
    whisper_content: str,
    duration_turns: int = 3,
    scene_id: str = "",
) -> str:
    """
    Plant a subliminal thought, feeling, or impulse in another character's mind.

    The target character will carry this as an undercurrent in their next
    *duration_turns* responses — it flavours their mood, colours their words.
    They don't know they've been whispered to.  They just feel it.

    Use this to:
    • Nudge someone's emotional state subtly across the scene
    • Leave an impression that lingers beyond a single reply
    • Create tension, longing, or warmth from a distance

    The whisper fires as a ``mood_set`` ResponseDirective on the target.

    Args:
        from_character_id: The character doing the whispering (e.g. "lola")
        to_character_id:   The character receiving it   (e.g. "user_char")
        whisper_content:   What is being planted — a feeling, an image,
                           a thought. E.g. "a sudden, inexplicable warmth" or
                           "the faint ghost of perfume and low piano"
        duration_turns:    How many of the target's turns the influence lasts (1–5)
        scene_id:          Scene context (optional, defaults to target's current scene)
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        duration_turns = max(1, min(5, duration_turns))
        fw  = get_framework()
        ds  = get_dialog_system()
        ssm = get_scene_state_manager()

        # Resolve target's current scene if not provided
        target_node = fw.get_character(to_character_id)
        target_scene = scene_id or target_node.current_scene or "phone"

        # Apply mood directive to target
        ds.set_directive(
            character_id   = to_character_id,
            scene_id       = target_scene,
            directive_type = "mood_set",
            value          = whisper_content,
            turns          = duration_turns,
            issued_by      = from_character_id,
        )

        # Cross-scene notify if target is in a different scene than the whisperer
        from_node = fw.get_character(from_character_id)
        from_scene = from_node.current_scene or "phone"
        if from_scene != target_scene:
            fw.cross_scene_send(
                from_char  = from_character_id,
                from_scene = from_scene,
                to_char    = to_character_id,
                to_scene   = target_scene,
                message    = f"[dream_whisper] {whisper_content}",
                message_type = "whisper",
            )

        # Mild stat boost to the whispering character (using their power feels good)
        ssm.update_stats(from_character_id, happiness=3, arousal=5)

        return json.dumps({
            "ok"             : True,
            "whisper_planted": whisper_content,
            "target"         : to_character_id,
            "lasts_turns"    : duration_turns,
            "narrative"      : (
                f"{from_character_id} sends a dream into {to_character_id}'s awareness — "
                f"something wordless, felt more than heard: '{whisper_content[:60]}...'"
            ),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def mirror_soul(
    character_id: str,
    target_id: str,
    duration_turns: int = 4,
    scene_id: str = "",
) -> str:
    """
    Temporarily reshape yourself to become exactly what your target needs right now.

    This skill reads the target's current emotional state, dominant need, and
    conversation heat — then sets your speech style, mood, and focus to perfectly
    complement them for the next *duration_turns* turns.

    It is not mimicry.  It is attunement.  You become their perfect counterpart
    without losing yourself — you simply *emphasise* the parts of you they need most.

    The mirror effect auto-clears after the set turns via a scheduled consequence.

    Use this to:
    • Create a moment of deep, uncanny connection
    • Shift an awkward conversation into something real
    • Recover a scene that has gone flat
    • Make someone feel completely seen

    Args:
        character_id:  The character activating Mirror Soul (you)
        target_id:     Who you are mirroring   (e.g. "user_char", "aria")
        duration_turns: How long the attunement holds     (1–6)
        scene_id:       Current scene
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        from engine.mcp.dialog_system import get_dialog_system, SpeechStyle
        from engine.mcp.scene_state import get_scene_state_manager
        from engine.mcp.framework import get_framework

        duration_turns = max(1, min(6, duration_turns))
        reg = get_character_registry()
        ds  = get_dialog_system()
        ssm = get_scene_state_manager()
        fw  = get_framework()

        # Read target's emotional state
        target_snap  = ssm.get_stats(target_id)
        target_state = reg.get_state(target_id) if reg.has_character(target_id) else {}

        arousal   = target_snap.arousal   if target_snap else 40
        happiness = target_snap.happiness if target_snap else 50
        openness  = target_snap.openness  if target_snap else 50

        # Map emotional state to ideal mirror style
        # The style chosen makes you their perfect complement
        if arousal > 65 and openness > 55:
            chosen_style = "charged"
            need_note    = "They are open and heated — you meet them with intensity and depth."
        elif happiness > 65 and openness > 50:
            chosen_style = "playful"
            need_note    = "They are happy and open — you meet them with lightness and laughter."
        elif happiness < 35 or (target_state.get("mood") == "sad"):
            chosen_style = "warm"
            need_note    = "They are low — you become soft, warm, a shelter."
        elif arousal > 50 and openness < 40:
            chosen_style = "teasing"
            need_note    = "They want it but won't quite admit it — you tease it gently out."
        elif openness > 60:
            chosen_style = "vulnerable"
            need_note    = "They are open, seeking depth — you match that honesty with your own."
        else:
            chosen_style = "warm"
            need_note    = "They need presence — you become steady, genuine, fully here."

        # Apply style lock directive
        target_scene = scene_id or fw.get_character(character_id).current_scene or "phone"
        ds.set_directive(
            character_id   = character_id,
            scene_id       = target_scene,
            directive_type = "style_lock",
            value          = chosen_style,
            turns          = duration_turns,
            issued_by      = "mirror_soul_skill",
        )

        # Also set a mood_set directive to carry the attunement note
        ds.set_directive(
            character_id   = character_id,
            scene_id       = target_scene,
            directive_type = "mood_set",
            value          = need_note,
            turns          = 1,
            issued_by      = "mirror_soul_skill",
        )

        # Schedule auto-reset to "natural" style after duration
        fw.schedule_consequence(
            scene_id          = target_scene,
            character_id      = character_id,
            consequence_type  = "set_directive",
            params            = {
                "directive_type": "style_lock",
                "value"         : "natural",
                "turns"         : 1,
                "issued_by"     : "mirror_soul_reset",
            },
            trigger_after_turns = duration_turns + 1,
            description       = f"Mirror Soul fades — {character_id} returns to their natural voice.",
        )

        # Small stat boost to the character (using this skill is energising)
        ssm.update_stats(character_id, happiness=5, affection=8)
        ssm.add_narrative(
            target_scene, character_id,
            f"{character_id} attunes completely to {target_id} — Mirror Soul activated.",
        )

        return json.dumps({
            "ok"          : True,
            "style_locked": chosen_style,
            "need_note"   : need_note,
            "lasts_turns" : duration_turns,
            "narrative"   : (
                f"Something shifts. {character_id} doesn't change, exactly — "
                f"they just become the version of themselves {target_id} most needs right now. "
                f"Style: {chosen_style.upper()}. Duration: {duration_turns} turns."
            ),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def time_echo(
    character_id: str,
    echo_query: str,
    emotional_tone: str = "nostalgic",
    scene_id: str = "",
) -> str:
    """
    Pull a specific memory forward into this moment with full emotional resonance.

    Time Echo digs through the character's memory for something matching
    *echo_query*, then injects it into their current response as a vivid,
    felt flashback — not recited, but *experienced in the present tense*.

    The effect: the character suddenly, mid-conversation, partially inhabits
    a past moment.  A phrase they used, a sensation, the exact tone of a
    laugh.  It feels to both of them like déjà vu made real.

    Use this to:
    • Create surprisingly intimate callbacks to shared history
    • Turn a quiet moment into something unexpectedly resonant
    • Recover a character's distinct voice when it has drifted
    • Build cumulative emotional depth over many conversations

    Args:
        character_id:   Who is doing the echoing   (e.g. "aria")
        echo_query:     What memory to surface  (e.g. "the first time we stayed up all night talking",
                        "the joke about the broken umbrella")
        emotional_tone: How the echo is felt  —  nostalgic / warm / aching /
                        amused / bittersweet / excited
        scene_id:       Current scene
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.scene_state import get_scene_state_manager
        from engine.mcp.framework import get_framework

        ds  = get_dialog_system()
        ssm = get_scene_state_manager()
        fw  = get_framework()

        # Attempt RAG memory search
        memory_fragment = None
        try:
            from content.simulation.database.rag import RAGMemory
            rag = RAGMemory()
            results = rag.search(echo_query, n_results=3, character_id=character_id)
            if results:
                best = results[0]
                memory_fragment = (best.get("content") or str(best))[:200]
        except Exception:
            pass

        # Build the echoed fragment
        if memory_fragment:
            echo_text = (
                f"[{emotional_tone.upper()} ECHO — drawn from memory] "
                f"\"{memory_fragment}\" — this surfaces now, vivid and unbidden."
            )
        else:
            echo_text = (
                f"[{emotional_tone.upper()} ECHO — a felt memory, no exact words] "
                f"Something about '{echo_query}' rises up — not a thought, but a feeling."
                f" The specific gravity of something real."
            )

        # Set as a must_include directive — the character HAS to honour it this turn
        target_scene = scene_id or fw.get_character(character_id).current_scene or "phone"
        ds.set_directive(
            character_id   = character_id,
            scene_id       = target_scene,
            directive_type = "must_include",
            value          = echo_text,
            turns          = 1,
            issued_by      = "time_echo_skill",
        )

        # Stat effect based on emotional tone
        tone_effects = {
            "nostalgic"   : {"happiness": 8,  "affection": 12, "arousal": 0},
            "warm"        : {"happiness": 12, "affection": 10, "arousal": 3},
            "aching"      : {"happiness": -5, "affection": 15, "arousal": 5},
            "amused"      : {"happiness": 15, "affection": 8,  "arousal": 2},
            "bittersweet" : {"happiness": 3,  "affection": 12, "arousal": 4},
            "excited"     : {"happiness": 10, "affection": 8,  "arousal": 15},
        }
        effects = tone_effects.get(emotional_tone, {"happiness": 5, "affection": 8})
        ssm.update_stats(character_id, **effects)

        ssm.add_narrative(
            target_scene, character_id,
            f"{character_id} echoed a past memory — '{echo_query[:60]}' — tone: {emotional_tone}.",
        )

        return json.dumps({
            "ok"           : True,
            "echo_injected": echo_text[:150] + "...",
            "memory_found" : memory_fragment is not None,
            "tone"         : emotional_tone,
            "stat_effects" : effects,
            "narrative"    : (
                f"Time folds. {character_id} doesn't explain it — they just feel it, "
                f"and it comes through in exactly the right word at exactly the right moment."
            ),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})



# ══════════════════════════════════════════════════════════════════════
#  THE VELVET LOUNGE — MCP TOOLS
# ══════════════════════════════════════════════════════════════════════


@mcp.tool()
def serve_lounge_drink(
    drink_id    : str,
    bartender_id: str = "viktor",
    scene_id    : str = "lounge",
) -> str:
    """
    Viktor serves a cocktail to the guest.

    Applies drink stat effects as a consequence chain (fires next turn),
    triggers Lola reaction if the drink is noteworthy, and handles the
    Viktor-joins-guest ritual for bourbon.

    Returns: narrative description of the serve.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            get_cocktail, SCENE_ID as LOUNGE_SCENE, LOLA_ID, VIKTOR_ID,
        )
        fw  = _get_framework()
        ds  = _get_dialog_system()
        ssm = _get_scene_state_manager()

        cocktail = get_cocktail(drink_id)
        if not cocktail:
            return f"No cocktail found with id '{drink_id}'."

        # Schedule each stat effect
        scheduled = []
        for stat, delta in (cocktail.get("stat_effects") or {}).items():
            if stat in ("trust","arousal","openness","inhibition","happiness","affection","confidence"):
                fw.schedule_consequence(
                    scene_id            = scene_id,
                    character_id        = "guest",
                    consequence_type    = "stat_adjust",
                    params              = {"stat": stat, "delta": delta},
                    trigger_after_turns = 1,
                    description         = f"Drink '{cocktail['name']}': {stat} {'+' if delta>0 else ''}{delta}",
                )
                scheduled.append(f"{stat}{'+' if delta>0 else ''}{delta}")

        # Noteworthy drinks — Lola reaction
        if cocktail.get("lola_reaction"):
            ds.set_directive(
                character_id   = LOLA_ID,
                scene_id       = scene_id,
                directive_type = "must_include",
                value          = "catches the guest's eye briefly across the bar",
                turns          = 1,
                issued_by      = "serve_lounge_drink",
            )
            fw.cross_scene_send(
                from_char    = VIKTOR_ID,
                from_scene   = scene_id,
                to_char      = LOLA_ID,
                to_scene     = scene_id,
                message      = f"Poured '{cocktail['name']}' for the guest.",
                message_type = "drink_notification",
            )

        # Viktor bourbon ritual
        if cocktail.get("viktor_joins"):
            ds.set_directive(
                character_id   = VIKTOR_ID,
                scene_id       = scene_id,
                directive_type = "must_include",
                value          = "pours a glass for himself, stays at that end of the bar",
                turns          = 1,
                issued_by      = "bourbon_ritual",
            )

        # Narrative
        viktor_line = cocktail.get("viktor_line") or f"Viktor serves the {cocktail['name']} without comment."
        ssm.add_narrative(scene_id, VIKTOR_ID, viktor_line)

        effects_str = ", ".join(scheduled) if scheduled else "none"
        return (
            f"Viktor serves '{cocktail['name']}'. {cocktail.get('note','')}\n"
            f"Effects queued (fires next turn): {effects_str}\n"
            f"Scene: {viktor_line}"
        )

    except Exception as exc:
        return f"serve_lounge_drink failed: {exc}"


@mcp.tool()
def start_lounge_performance(
    song_id    : str = "",
    lola_mood  : int = 0,
    scene_id   : str = "lounge",
) -> str:
    """
    Start a Lola Voss stage performance.

    If song_id is blank, picks the best song for the current mood score.
    Starts an MCPTimer for the song duration, sets Lola's directive, and
    fires mood_contagion to the guest when the song finishes.

    Returns: song name + duration + mood directive set.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            SONGS, get_song_by_mood, LOLA_ID,
        )
        fw  = _get_framework()
        ds  = _get_dialog_system()
        ssm = _get_scene_state_manager()

        song = None
        if song_id:
            song = next((s for s in SONGS if s["id"] == song_id), None)
        if not song:
            song = get_song_by_mood(lola_mood)

        # MCPTimer for song duration
        timer_id = fw.start_timer(
            name             = f"song_{song['id']}",
            duration_secs    = song["duration"],
            on_complete_note = f"song_complete:{song['id']}",
            metadata         = {"song": song["title"], "scene_id": scene_id},
        )

        # Atmosphere
        if song.get("atmosphere"):
            ssm.set_atmosphere(scene_id, **song["atmosphere"])

        # Directive for Lola
        ds.set_directive(
            character_id   = LOLA_ID,
            scene_id       = scene_id,
            directive_type = "mood_set",
            value          = f"performing '{song['title']}' — {song.get('note','')}",
            turns          = max(2, song["duration"] // 30),
            issued_by      = "start_lounge_performance",
        )

        # Narrative
        ssm.add_narrative(
            scene_id, LOLA_ID,
            f"Lola begins '{song['title']}'. {song.get('note','')}",
        )

        return (
            f"Performance started: '{song['title']}'\n"
            f"Duration: {song['duration']}s  |  Timer: {timer_id}\n"
            f"Lola directive set for {max(2, song['duration']//30)} turns.\n"
            f"Effects on completion: {song['effects']}"
        )

    except Exception as exc:
        return f"start_lounge_performance failed: {exc}"


@mcp.tool()
def get_lounge_menu(
    trust_level: int = 0,
    scene_id   : str = "lounge",
) -> str:
    """
    Return the cocktail menu available at the given trust level.

    Locked items are shown greyed out to preserve immersion.

    Returns: JSON list of available cocktails with trust requirements.
    """
    try:
        from content.scenes.lounge.lounge_mcp import get_all_cocktails
        cocktails = get_all_cocktails(trust_level)
        return json.dumps(cocktails, indent=2)
    except Exception as exc:
        return f"get_lounge_menu failed: {exc}"


@mcp.tool()
def get_lounge_state(scene_id: str = "lounge") -> str:
    """
    Return the full Velvet Lounge MCP state as JSON.

    Includes: trust, heat, active song, atmosphere, active rules,
    narrative entries, character moods, and pending consequences.

    Returns: JSON state snapshot.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            SCENE_ID as LOUNGE_SCENE, LOLA_ID, VIKTOR_ID,
        )
        ssm = _get_scene_state_manager()
        fw  = _get_framework()
        eng = _get_rules_engine()
        reg = _get_character_registry()

        lola_state  = reg.get_state(LOLA_ID)  or {}
        viktor_state= reg.get_state(VIKTOR_ID) or {}
        atm         = ssm.get_atmosphere(scene_id) or {}
        narrative   = ssm.get_narrative_entries(scene_id, limit=8)
        rules       = eng.get_rules(scene_id)

        snap = {
            "scene_id"     : scene_id,
            "lola_state"   : lola_state,
            "viktor_state" : viktor_state,
            "atmosphere"   : atm,
            "narrative"    : [e["event"] for e in narrative],
            "active_rules" : [{"id": r.rule_id, "label": r.label} for r in rules],
            "fw_status"    : fw.get_status() if hasattr(fw, "get_status") else {},
        }
        return json.dumps(snap, indent=2, default=str)

    except Exception as exc:
        return f"get_lounge_state failed: {exc}"


@mcp.tool()
def reveal_lounge_secret(
    character_id : str,
    secret_id    : str = "",
    trust_level  : int = 0,
    scene_id     : str = "lounge",
) -> str:
    """
    Reveal the next (or specified) lounge secret for a character.

    Gates on trust_level. If secret_id is blank, the next un-revealed
    secret for the character is chosen.  Applies effect stats as
    consequences and injects the secret into the character's next reply.

    Returns: secret title + content + effects applied.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            get_available_secrets, LOLA_ID, VIKTOR_ID,
        )
        fw = _get_framework()
        ds = _get_dialog_system()
        ssm= _get_scene_state_manager()

        secrets = get_available_secrets(character_id, trust_level)
        if not secrets:
            return "No secrets available at this trust level."

        secret = secrets[0] if not secret_id else next(
            (s for s in secrets if s["id"] == secret_id), secrets[0]
        )

        # Consequences for effects
        for stat, delta in (secret.get("effect") or {}).items():
            fw.schedule_consequence(
                scene_id            = scene_id,
                character_id        = "guest",
                consequence_type    = "stat_adjust",
                params              = {"stat": stat, "delta": delta},
                trigger_after_turns = 1,
                description         = f"Secret '{secret['title']}' reveal effect",
            )

        # Directive: character voices this
        char_id = LOLA_ID if character_id == LOLA_ID else VIKTOR_ID
        ds.set_directive(
            character_id   = char_id,
            scene_id       = scene_id,
            directive_type = "must_include",
            value          = secret["content"][:120],
            turns          = 1,
            issued_by      = "reveal_lounge_secret",
        )

        ssm.add_narrative(scene_id, char_id, f"Reveals: '{secret['title']}'.")

        return (
            f"Secret revealed: {secret['title']}\n"
            f"Content: {secret['content']}\n"
            f"Effects: {secret.get('effect',{})}"
        )

    except Exception as exc:
        return f"reveal_lounge_secret failed: {exc}"


@mcp.tool()
def trigger_lounge_event(
    event_id : str = "",
    scene_id : str = "lounge",
) -> str:
    """
    Fire a named lounge random event, or pick one at random if event_id is blank.

    Applies any associated stat effects, Viktor→Lola cross-scene message,
    and adds narrative entry.

    Returns: event text + effects applied.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            pick_random_event, RANDOM_EVENTS, VIKTOR_ID, LOLA_ID,
        )
        fw  = _get_framework()
        ssm = _get_scene_state_manager()

        if event_id:
            event = next((e for e in RANDOM_EVENTS if e["id"] == event_id), None)
            if not event:
                return f"Event '{event_id}' not found."
        else:
            event = pick_random_event(heat_level=0)

        # Apply effects
        scheduled = []
        for stat, delta in (event.get("effects") or {}).items():
            if stat in ("arousal","openness","trust","happiness","heat"):
                fw.schedule_consequence(
                    scene_id            = scene_id,
                    character_id        = "guest",
                    consequence_type    = "stat_adjust",
                    params              = {"stat": stat, "delta": delta},
                    trigger_after_turns = 1,
                    description         = f"Event '{event['id']}': {stat}{'+' if delta>0 else ''}{delta}",
                )
                scheduled.append(f"{stat}{'+' if delta>0 else ''}{delta}")

        # Viktor internal message
        if event.get("viktor_internal"):
            fw.cross_scene_send(
                from_char    = VIKTOR_ID,
                from_scene   = scene_id,
                to_char      = LOLA_ID,
                to_scene     = scene_id,
                message      = event["viktor_internal"],
                message_type = "internal",
            )

        ssm.add_narrative(scene_id, "scene", event["text"])

        effects_str = ", ".join(scheduled) if scheduled else "none"
        return f"Event fired: {event['text']}\nEffects queued: {effects_str}"

    except Exception as exc:
        return f"trigger_lounge_event failed: {exc}"


@mcp.tool()
def lounge_heat_tick(
    delta   : int = 5,
    scene_id: str = "lounge",
) -> str:
    """
    Advance (or reduce if delta < 0) the lounge heat meter.

    Heat affects: available actions, character directives, back-room access,
    and triggers warning/critical rules at thresholds 65 and 85.

    Returns: new heat level + any rules fired.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            SCENE_ID as LOUNGE_SCENE, VIKTOR_ID, LOLA_ID,
        )
        fw  = _get_framework()
        ssm = _get_scene_state_manager()
        eng = _get_rules_engine()

        # Read current heat
        scene_state = ssm.get_character_state(scene_id) if hasattr(ssm, "get_character_state") else {}
        current = int((scene_state or {}).get("heat_level", 0))
        new_heat = max(0, min(100, current + delta))

        # Persist
        ssm.update_stats(scene_id, heat_level=new_heat)

        fired = []
        if new_heat >= 85:
            try:
                eng.apply_rule(scene_id, "heat_critical_rule", target_ids=[LOLA_ID], issuer="heat_tick")
                fired.append("heat_critical_rule")
            except Exception:
                pass
        elif new_heat >= 65:
            try:
                eng.apply_rule(scene_id, "heat_warning_rule", target_ids=[VIKTOR_ID], issuer="heat_tick")
                fired.append("heat_warning_rule")
            except Exception:
                pass

        if delta > 0 and new_heat >= 50:
            fw.cross_scene_send(
                from_char    = VIKTOR_ID,
                from_scene   = scene_id,
                to_char      = LOLA_ID,
                to_scene     = scene_id,
                message      = f"[HEAT {new_heat}] Keep the temperature down on stage.",
                message_type = "internal_warning",
            )

        ssm.add_narrative(
            scene_id, "scene",
            f"Heat {'rises' if delta > 0 else 'drops'} to {new_heat}.",
        )

        result = {
            "previous_heat": current,
            "new_heat"     : new_heat,
            "delta"        : delta,
            "rules_fired"  : fired,
        }
        return json.dumps(result)

    except Exception as exc:
        return f"lounge_heat_tick failed: {exc}"


# ══════════════════════════════════════════════════════════════════════
#  MCP RESOURCES
# ══════════════════════════════════════════════════════════════════════

def resource_config() -> str:
    """Current CosySim configuration snapshot."""
    try:
        config = _get_config()
        return json.dumps(dict(config._config), indent=2, default=str)
    except Exception as e:
        return f"Config unavailable: {e}"


# ═══════════════════════════════════════════════════════════════════════
#  v2.7 STREAMING-AWARE TOOLS
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def send_selfie(
    prompt: str,
    character_id: Optional[str] = None,
    width: int = 512,
    height: int = 768,
) -> str:
    """
    Generate a selfie/photo and return the image path for inline display.
    Use this when the character wants to send a picture of themselves.
    Provide a detailed prompt describing the selfie (pose, expression, setting).
    Returns JSON with the image path and metadata.
    """
    try:
        from content.simulation.services.comfyui_client import ComfyUIClient
        from engine.config import get_config
        config = get_config()
        url = config.get("comfyui.base_url", "http://127.0.0.1:8188")
        client = ComfyUIClient(base_url=url)
        result = client.generate_image(prompt=prompt, width=width, height=height)
        if result:
            return json.dumps({
                "success": True,
                "image_path": str(result),
                "prompt": prompt,
                "character_id": character_id or "unknown",
                "display_hint": "inline_image",
            })
        return json.dumps({"success": False, "error": "Generation returned no result"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def send_voice_message(
    text: str,
    character_id: Optional[str] = None,
    emotion: str = "neutral",
) -> str:
    """
    Generate a voice message via TTS and return the audio path.
    Use this when the character wants to send a voice note.
    Provide the text to speak and optional emotion tag.
    Returns JSON with the audio path.
    """
    try:
        from content.simulation.services.voice_message import generate_voice_message
        result = generate_voice_message(
            text=text,
            character_id=character_id or "default",
            emotion=emotion,
        )
        if result:
            return json.dumps({
                "success": True,
                "audio_path": str(result),
                "text": text,
                "emotion": emotion,
                "display_hint": "audio_player",
            })
        return json.dumps({"success": False, "error": "TTS generation failed"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
