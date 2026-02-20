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
        from engine.lmstudio import get_lmstudio_client
        client = get_lmstudio_client()
        msgs = [
            {"role": "system", "content":
             "You are a message editor. Reshape the given message according to "
             "the instruction. Return ONLY the rewritten message, nothing else."},
            {"role": "user", "content":
             f"Original:\n{original_message}\n\nInstruction:\n{instruction}"},
        ]
        resp = client.chat(msgs, max_tokens=300, temperature=0.7)
        return resp.content.strip()
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
