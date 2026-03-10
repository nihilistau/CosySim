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
    from engine.mcp.tools.memory import search_memory
    return search_memory(query, character_id, top_k)


@mcp.tool()
def store_memory(text: str, character_id: str, metadata: Optional[str] = None) -> str:
    """
    Store a new memory for a character in the RAG system.
    Use this to save important facts, conversation summaries, or observations.
    """
    from engine.mcp.tools.memory import store_memory
    return store_memory(text, character_id, metadata)


@mcp.tool()
def get_character_state(character_id: str) -> str:
    """
    Get the current state of a character including mood, energy, and relationships.
    Returns JSON with all character state fields.
    """
    from engine.mcp.tools.character import get_character_state
    return get_character_state(character_id)


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
    from engine.mcp.tools.character import adjust_relationship
    return adjust_relationship(character_a, character_b, field, delta)


@mcp.tool()
def get_chain_events(chain_id: str, limit: int = 20) -> str:
    """
    Get events from an EventChain by chain_id.
    Returns a list of events with type, actor, timestamp, and summary.
    Use this to inspect what happened in an interaction chain.
    """
    from engine.mcp.tools.event_chain import get_chain_events
    return get_chain_events(chain_id, limit)



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
    from engine.mcp.tools.event_chain import log_event
    return log_event(chain_id, event_type, actor, summary, payload, character_id)



@mcp.tool()
def list_characters() -> str:
    """
    List all characters in the database with their names and IDs.
    """
    from engine.mcp.tools.character import list_characters
    return list_characters()


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
    from engine.mcp.tools.media import generate_image_request
    return generate_image_request(prompt, width, height, character_id)


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
    from engine.mcp.tools.agent import get_my_skills
    return get_my_skills(scene)



# ── Randomness & game mechanics ────────────────────────────────────────

@mcp.tool()
def roll_dice(sides: int = 6, count: int = 1) -> str:
    """
    Roll one or more dice and return the results.
    Useful for game mechanics, random outcomes, or adding unpredictability.
    Example: roll_dice(100) gives a d100 result for truth-or-dare.
    Odd results = Truth, Even results = Dare (for truth-or-dare game).
    """
    from engine.mcp.tools.game import roll_dice
    return roll_dice(sides, count)


@mcp.tool()
def get_random_topic(category: str = "general") -> str:
    """
    Get a randomly selected topic or prompt for conversation or games.
    Categories: 'truth_questions', 'dare_ideas', 'mystery_clues',
    'conversation_starters', 'relationship_questions', 'general'.
    Use this to get fresh ideas for games, topics, or challenges.
    """
    from engine.mcp.tools.game import get_random_topic
    return get_random_topic(category)


# ── Game state ─────────────────────────────────────────────────────────

@mcp.tool()
def get_game_state(game_id: str, key: Optional[str] = None) -> str:
    """
    Read the current state of a game by its ID.
    If key is provided, returns only that value.
    If key is None, returns the entire game state dict.
    Common game IDs: 'truth_or_dare', 'mystery'.
    """
    from engine.mcp.tools.game import get_game_state
    return get_game_state(game_id, key)


@mcp.tool()
def set_game_state(game_id: str, key: str, value: str) -> str:
    """
    Write a value to the game state.
    Use this to record scores, round counts, discovered clues, game outcomes, etc.
    Value is stored as a string — use JSON encoding for complex types.
    Example: set_game_state('truth_or_dare', 'round', '3')
    """
    from engine.mcp.tools.game import set_game_state
    return set_game_state(game_id, key, value)


@mcp.tool()
def start_game(game_id: str, scene: str = "phone", config_json: Optional[str] = None) -> str:
    """
    Start a new game session.
    game_id options: 'truth_or_dare', 'mystery'
    This resets existing game state and marks the game as active.
    The game rules will automatically be injected into your system context.
    """
    from engine.mcp.tools.game import start_game
    return start_game(game_id, scene, config_json)


@mcp.tool()
def end_game(game_id: str) -> str:
    """
    End a game and record the final result.
    Returns a summary of the final game state including score.
    """
    from engine.mcp.tools.game import end_game
    return end_game(game_id)


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
    from engine.mcp.tools.game import launch_game
    return launch_game(character_id, game_type, case_index)


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
    from engine.mcp.tools.game import get_active_game
    return get_active_game(character_id)


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
    from engine.mcp.tools.game import game_action
    return game_action(character_id, action, data_json)


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
    from engine.mcp.tools.game import game_history
    return game_history(character_id, limit)


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
    from engine.mcp.tools.character import update_mood
    return update_mood(character_id, mood, reason, intensity)



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
    from engine.mcp.tools.character import apply_effect
    return apply_effect(character_id, effect_name, value)


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
    from engine.mcp.tools.agent import send_to_agent
    return send_to_agent(recipient_id, message, sender_id)



@mcp.tool()
def get_scene_context(scene: str = "phone") -> str:
    """
    Get context about what is currently happening in a scene:
    active characters, current game (if any), service health.
    Use this to understand the state of the world before acting.
    """
    from engine.mcp.tools.agent import get_scene_context
    return get_scene_context(scene)


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
    from engine.mcp.tools.agent import intercept_and_enhance
    return intercept_and_enhance(original_message, instruction)



# ── System stats ───────────────────────────────────────────────────────

@mcp.tool()
def get_system_stats() -> str:
    """
    Get current system resource usage: CPU, RAM, GPU VRAM, GPU temp,
    loaded LMStudio model, and activity bus status.
    Use this to check if the system is under load or what model is active.
    """
    from engine.mcp.tools.system import get_system_stats
    return get_system_stats()


@mcp.tool()
def check_relationship(character_a: str, character_b: str) -> str:
    """
    Get a concise relationship summary between two characters.
    Returns trust, attraction, relationship level and a natural-language
    summary. Use this before making decisions that depend on relationship state.
    """
    from engine.mcp.tools.character import check_relationship
    return check_relationship(character_a, character_b)



@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web for information and return a summary of results.
    Use this when you need current information, facts, or knowledge
    that might not be in your training data.
    Returns a list of titles, snippets, and URLs.
    """
    from engine.mcp.tools.system import search_web
    return search_web(query, max_results)


# ══════════════════════════════════════════════════════════════════════
# ██████████████████████████████████████████████████████████████████████
#  penthouse & PHONE  — Scene State, Wardrobe, Interactions, Narrative
# ██████████████████████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════

def _ssm():
    from engine.mcp.scene_state import get_scene_state_manager
    return get_scene_state_manager()

def _coord():
    from engine.mcp.state_coordinator import get_coordinator
    return get_coordinator()

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
    from engine.mcp.tools.wardrobe import wardrobe_get
    return wardrobe_get(character_id)


@mcp.tool()
def wardrobe_init(character_id: str, style: str = "casual") -> str:
    """
    Give a character a full starter wardrobe.  Call this when a character first
    enters a scene so they have a clothing inventory.

    style: 'casual' | 'lingerie' | 'party' | 'nightwear' | 'swimwear'
    """
    from engine.mcp.tools.wardrobe import wardrobe_init
    return wardrobe_init(character_id, style)


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
    from engine.mcp.tools.wardrobe import wardrobe_remove_item
    return wardrobe_remove_item(character_id, item_id, removed_by)


@mcp.tool()
def wardrobe_remove_outermost(character_id: str, removed_by: str = "") -> str:
    """
    Strip the outermost clothing layer from a character — perfect for a
    striptease or when the Director wants the next item to come off without
    specifying which one.

    Returns what was removed and what's left.  Call repeatedly to fully
    undress.
    """
    from engine.mcp.tools.wardrobe import wardrobe_remove_outermost
    return wardrobe_remove_outermost(character_id, removed_by)


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
    from engine.mcp.tools.wardrobe import wardrobe_add_item
    return wardrobe_add_item(character_id, item_id, name, category, color, style)


@mcp.tool()
def wardrobe_redress(character_id: str) -> str:
    """
    Put all previously removed clothing back on a character.
    Use at scene reset or morning-after scenarios.
    """
    from engine.mcp.tools.wardrobe import wardrobe_redress
    return wardrobe_redress(character_id)


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
    from engine.mcp.tools.character import get_character_scene_stats
    return get_character_scene_stats(character_id)


@mcp.tool()
def update_character_scene_stats(character_id: str, stat_changes: str) -> str:
    """
    Adjust a character's scene stats by delta values.  Pass a JSON string like:
    '{"arousal": 15, "happiness": -10, "openness": 5}'

    Stats clamp at 0-100.  Use positive values to increase, negative to decrease.
    Call this after interactions, events, emotional moments.
    """
    from engine.mcp.tools.character import update_character_scene_stats
    return update_character_scene_stats(character_id, stat_changes)



@mcp.tool()
def set_character_scene_stat(character_id: str, stat: str, value: float) -> str:
    """
    Set a specific stat to an exact value (0-100).  Use when you need precision
    rather than a delta — e.g. resetting a stat at scene start.

    stat: arousal | horniness | pleasure | happiness | anger | fear |
          drunkenness | tiredness | explicitness | openness | affection | dominance
    """
    from engine.mcp.tools.character import set_character_scene_stat
    return set_character_scene_stat(character_id, stat, value)


@mcp.tool()
def reset_character_scene_stats(character_id: str) -> str:
    """Reset all scene stats for a character back to defaults (scene reset / new character)."""
    from engine.mcp.tools.character import reset_character_scene_stats
    return reset_character_scene_stats(character_id)


# ── INTERACTIONS ──────────────────────────────────────────────────────

@mcp.tool()
def perform_interaction(
    interaction_type: str,
    initiator_id: str,
    target_id: str,
    scene_id: str = "penthouse",
    subtype: str = "",
    intensity: int = 0,
) -> str:
    """
    Perform one of the 6 core interaction types between two characters.

    penthouse interaction_types:
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
    from engine.mcp.tools.interaction import perform_interaction
    return perform_interaction(interaction_type, initiator_id, target_id, scene_id, subtype, intensity)


@mcp.tool()
def list_available_interactions(character_id: str, scene_id: str = "penthouse") -> str:
    """
    List all interaction types and their accessible subtypes for a character
    based on their current stats.  Use this before calling perform_interaction
    to know what's available without guessing.

    Returns a filtered list — only shows subtypes whose stat requirements are met.
    """
    from engine.mcp.tools.interaction import list_available_interactions
    return list_available_interactions(character_id, scene_id)


@mcp.tool()
def get_interaction_details(
    interaction_type: str,
    subtype: str = "",
    scene_id: str = "penthouse",
) -> str:
    """
    Get detailed information about a specific interaction type/subtype —
    description, phases, sample narrative fragments, stat effects, requirements.

    Call this to understand what an interaction involves before using it,
    or to pick the right fragments for your narration.
    """
    from engine.mcp.tools.interaction import get_interaction_details
    return get_interaction_details(interaction_type, subtype, scene_id)


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
    from engine.mcp.tools.interaction import start_timed_action
    return start_timed_action(character_id, action_type, duration_secs, description, phases)


@mcp.tool()
def poll_timed_action(token: str) -> str:
    """
    Check the progress of a running timed action.
    Returns phase name, progress (0.0-1.0), elapsed time, and completion status.

    Check this periodically to narrate an unfolding scene.  When complete=true
    the action has finished — emit the afterglow narrative.
    """
    from engine.mcp.tools.interaction import poll_timed_action
    return poll_timed_action(token)


@mcp.tool()
def abort_timed_action(token: str) -> str:
    """Stop a timed action early (e.g. interrupted by Director or refused by character)."""
    from engine.mcp.tools.interaction import abort_timed_action
    return abort_timed_action(token)


@mcp.tool()
def list_active_timed_actions(character_id: str = "") -> str:
    """
    List all currently running timed actions.
    Pass character_id to filter to a specific character, or leave blank for all.
    """
    from engine.mcp.tools.interaction import list_active_timed_actions
    return list_active_timed_actions(character_id)


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
    from engine.mcp.tools.scene import add_scene_narrative
    return add_scene_narrative(scene_id, event, character_id, entry_type)


@mcp.tool()
def get_scene_narrative(scene_id: str, limit: int = 20) -> str:
    """
    Read the last N entries from the scene's narrative log.
    Use this to maintain continuity — know what has already happened.

    Returns a text summary and a structured list of entries.
    Always call this at scene start and after resuming a paused session.
    """
    from engine.mcp.tools.scene import get_scene_narrative
    return get_scene_narrative(scene_id, limit)


@mcp.tool()
def get_full_scene_snapshot(scene_id: str, character_ids: str = "") -> str:
    """
    Get a complete snapshot of the scene state — all characters' stats, wardrobes,
    emotional states, current timed actions, atmosphere, and recent narrative.

    character_ids: comma-separated list, or blank to include all known characters.

    Use this at scene start, after a skip, or to ground your response in the
    current reality of the room.  This is your oracle.
    """
    from engine.mcp.tools.scene import get_full_scene_snapshot
    return get_full_scene_snapshot(scene_id, character_ids)


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
    from engine.mcp.tools.scene import set_scene_atmosphere
    return set_scene_atmosphere(scene_id, lighting, mood, music, temperature, props_present, note)


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
    from engine.mcp.tools.character import check_character_consent
    return check_character_consent(character_id, action_type)


@mcp.tool()
def get_character_agency_summary(character_id: str) -> str:
    """
    Get a full picture of a character's current agency — who they are RIGHT NOW.
    Includes emotional state, compliance level, what they most want, what they'd
    resist, and what they might spontaneously initiate.

    Use this to write authentic agent responses that feel real rather than always-compliant.
    """
    from engine.mcp.tools.character import get_character_agency_summary
    return get_character_agency_summary(character_id)


# NOTE: get_scene_rules() defined below in SCENE RULES ENGINE TOOLS section
# (delegates to SceneRulesEngine for dynamic per-scene rules)


@mcp.tool()
def get_all_tools_for_scene(scene_id: str = "penthouse") -> str:
    """
    Get a complete reference of all MCP tools available in a scene.
    Call this at the start of a session so you know every tool at your disposal.
    Agents should internalise this list and joke/reference their abilities naturally.
    """
    from engine.mcp.tools.agent import get_all_tools_for_scene
    return get_all_tools_for_scene(scene_id)


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
    from engine.mcp.tools.agent import director_action
    return director_action(scene_id, action, target_character_ids, stat_impact)


@mcp.tool()
def resolve_random_scene_event(scene_id: str = "penthouse") -> str:
    """
    Generate a random scene event to keep things fresh and unpredictable.
    Call this when the scene feels stale or to inject spontaneity.

    Returns an event description and any stat effects — ready to use.
    """
    from engine.mcp.tools.agent import resolve_random_scene_event
    return resolve_random_scene_event(scene_id)


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
        scene_roles_json: JSON dict of scene → role  e.g. '{"penthouse": "lover"}'
    """
    from engine.mcp.tools.character import character_register
    return character_register(character_id, name, age, appearance_json, personality_json, backstory, voice_style, pronouns, scene_roles_json)


@mcp.tool()
def character_query(character_id: str, attribute: str) -> str:
    """
    Retrieve any attribute from a character's profile, state, or appearance.

    Args:
        character_id: e.g. "aria"
        attribute:    Any key: "name", "age", "mood", "arousal", "voice_style",
                      "hair", "eye_colour", "restrictions", "flags", etc.
    """
    from engine.mcp.tools.character import character_query
    return character_query(character_id, attribute)


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
    from engine.mcp.tools.character import character_set_attribute
    return character_set_attribute(character_id, attribute, value)


@mcp.tool()
def character_get_summary(character_id: str) -> str:
    """
    Return a compact summary of a character's current identity, mood,
    personality, skills, and restrictions — ready for prompt injection.

    Args:
        character_id: e.g. "aria"
    """
    from engine.mcp.tools.character import character_get_summary
    return character_get_summary(character_id)


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
    from engine.mcp.tools.character import character_assign_skill
    return character_assign_skill(character_id, skill_id, skill_type, label, params_json, trigger, priority)


@mcp.tool()
def character_revoke_skill(character_id: str, skill_id: str) -> str:
    """
    Remove a skill from a character.

    Args:
        character_id: e.g. "aria"
        skill_id:     Skill to remove
    """
    from engine.mcp.tools.character import character_revoke_skill
    return character_revoke_skill(character_id, skill_id)


@mcp.tool()
def character_get_skills(character_id: str, trigger: str = "") -> str:
    """
    List all skills assigned to a character, optionally filtered by trigger type.

    Args:
        character_id: e.g. "aria"
        trigger:      Optional filter: "auto" | "optional" | "required" | "" (all)
    """
    from engine.mcp.tools.character import character_get_skills
    return character_get_skills(character_id, trigger)


@mcp.tool()
def character_add_restriction(character_id: str, restriction: str) -> str:
    """
    Add a named restriction to a character.  Restrictions are checked by the
    rules engine and character_registry interceptor before actions are allowed.

    Args:
        character_id: e.g. "aria"
        restriction:  Named restriction e.g. "no_nudity", "safe_mode"
    """
    from engine.mcp.tools.character import character_add_restriction
    return character_add_restriction(character_id, restriction)


@mcp.tool()
def character_remove_restriction(character_id: str, restriction: str) -> str:
    """
    Remove a named restriction from a character.

    Args:
        character_id: e.g. "aria"
        restriction:  Name of the restriction to remove
    """
    from engine.mcp.tools.character import character_remove_restriction
    return character_remove_restriction(character_id, restriction)


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
        scene_id:          e.g. "penthouse" or "phone"
        context_tags_json: JSON list of current context tags e.g. '["intimate", "cuddle"]'
        stats_json:        JSON dict of current stats e.g. '{"arousal": 55, "openness": 40}'
        max_options:       Maximum number of options to return
    """
    from engine.mcp.tools.dialog import get_dialog_options
    return get_dialog_options(character_id, scene_id, context_tags_json, stats_json, max_options)


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
    from engine.mcp.tools.dialog import speech_enhance
    return speech_enhance(character_id, text, style, scene_id)


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
    from engine.mcp.tools.dialog import set_response_directive
    return set_response_directive(character_id, scene_id, directive_type, value, turns, issued_by)


@mcp.tool()
def get_active_directive(character_id: str, scene_id: str) -> str:
    """
    Return the currently active response directive for a character in a scene,
    or null if none is set.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "penthouse"
    """
    from engine.mcp.tools.dialog import get_active_directive
    return get_active_directive(character_id, scene_id)


@mcp.tool()
def clear_directive(character_id: str, scene_id: str) -> str:
    """
    Clear any active response directive for a character.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "penthouse"
    """
    from engine.mcp.tools.dialog import clear_directive
    return clear_directive(character_id, scene_id)


@mcp.tool()
def get_conversation_heat(character_id: str, scene_id: str) -> str:
    """
    Return the current conversation heat (0-100) for a character in a scene.
    Higher heat = more intense/intimate exchange.  Affects dialog option availability.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "phone"
    """
    from engine.mcp.tools.dialog import get_conversation_heat
    return get_conversation_heat(character_id, scene_id)


# NOTE: bump_conversation_heat() defined below in CONVERSATION MANAGEMENT section
# (delegates to ConversationHeat from scene_rules_engine)


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
        scene_id: e.g. "penthouse" or "phone"
    """
    from engine.mcp.tools.scene import get_scene_rules
    return get_scene_rules(scene_id)


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
        scene_id:         e.g. "penthouse"
        character_id:     e.g. "aria"
        stats_json:       JSON dict of current stats
        scene_state_json: JSON dict of scene state flags
    """
    from engine.mcp.tools.scene import get_scene_available_actions
    return get_scene_available_actions(scene_id, character_id, stats_json, scene_state_json)


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

    Examples: "penthouse_lights_off", "penthouse_mood_lift", "phone_escalate"

    Args:
        scene_id:        Scene the rule belongs to
        rule_id:         Rule identifier
        target_ids_json: JSON list of target character IDs
        issuer:          Who triggered this (for audit)
    """
    from engine.mcp.tools.scene import apply_scene_rule
    return apply_scene_rule(scene_id, rule_id, target_ids_json, issuer)


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
    from engine.mcp.tools.memory import memory_recall
    return memory_recall(character_id, query, context_limit, scene_id)



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
    from engine.mcp.tools.narrative import speak_as
    return speak_as(character_id, text, style, scene_id)


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
    from engine.mcp.tools.narrative import enforce_behavior
    return enforce_behavior(character_id, behavior_type, value, reason, scene_id, turns)


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
    from engine.mcp.tools.narrative import scene_broadcast
    return scene_broadcast(scene_id, event_type, payload_json, target_characters_json)


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
        scene_id:     e.g. "penthouse" or "phone"
        character_id: The character you're working with
    """
    from engine.mcp.tools.scene import get_scene_rules_summary
    return get_scene_rules_summary(scene_id, character_id)


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
    from engine.mcp.tools.dialog import start_timer
    return start_timer(timer_name, duration_secs, on_complete_note)


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
    from engine.mcp.tools.dialog import check_timer
    return check_timer(timer_name)


@mcp.tool()
def cancel_timer(timer_name: str) -> str:
    """
    **TIMER SKILL** — Cancel a running timer before it completes.

    Args:
        timer_name: The timer to cancel
    """
    from engine.mcp.tools.dialog import cancel_timer
    return cancel_timer(timer_name)


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
    from engine.mcp.tools.game import random_pick
    return random_pick(n, options_json, weights_json, seed)


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
    in the penthouse, texts while in different locations, notifications that cross
    scene boundaries.

    The message lands in the target character's inbox and is injected into their
    next turn via the ``RouterMessageInjector``.  Their scene is also notified.

    Message types:
      text              — standard text message
      call_notification — "incoming call" notification
      event             — system-level event crossing scenes
      system            — director/framework event

    Example: Aria in the penthouse texts the user in the phone scene:
      cross_scene_message("aria", "penthouse", "user", "phone",
                          "Thinking about last night... 🔥", "text")

    Args:
        from_char:    Sending character ID
        from_scene:   Sending character's current scene
        to_char:      Receiving character ID
        to_scene:     Receiving character's current scene
        message:      The message content
        message_type: text | call_notification | event | system
    """
    from engine.mcp.tools.conversation import cross_scene_message
    return cross_scene_message(from_char, from_scene, to_char, to_scene, message, message_type)


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
    from engine.mcp.tools.conversation import get_cross_scene_inbox
    return get_cross_scene_inbox(character_id)


@mcp.tool()
def get_framework_status() -> str:
    """
    Return a full MCPFramework status snapshot: active scenes, characters,
    timers, and pending consequence chains.  Use as a Director overview.
    """
    from engine.mcp.tools.scene import get_framework_status
    return get_framework_status()


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
    from engine.mcp.tools.scene import mood_contagion
    return mood_contagion(scene_id, initiator_id, emotion, intensity, target_ids_json, affinity_factor)



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
    from engine.mcp.tools.consequence import schedule_consequence
    return schedule_consequence(scene_id, character_id, consequence_type, params_json, trigger_after_turns, description, created_by)



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
    from engine.mcp.tools.consequence import get_pending_consequences
    return get_pending_consequences(scene_id, character_id)



@mcp.tool()
def cancel_consequence(consequence_id: str) -> str:
    """
    **CONSEQUENCE CHAINS** — Cancel a scheduled consequence before it fires.

    Args:
        consequence_id: The ID returned by schedule_consequence
    """
    from engine.mcp.tools.consequence import cancel_consequence
    return cancel_consequence(consequence_id)



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
    from engine.mcp.tools.narrative import dream_whisper
    return dream_whisper(from_character_id, to_character_id, whisper_content, duration_turns, scene_id)



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
    from engine.mcp.tools.narrative import mirror_soul
    return mirror_soul(character_id, target_id, duration_turns, scene_id)



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
    from engine.mcp.tools.narrative import time_echo
    return time_echo(character_id, echo_query, emotional_tone, scene_id)




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
    from engine.mcp.tools.lounge import serve_lounge_drink
    return serve_lounge_drink(drink_id, bartender_id, scene_id)



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
    from engine.mcp.tools.lounge import start_lounge_performance
    return start_lounge_performance(song_id, lola_mood, scene_id)



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
    from engine.mcp.tools.lounge import get_lounge_menu
    return get_lounge_menu(trust_level, scene_id)



@mcp.tool()
def get_lounge_state(scene_id: str = "lounge") -> str:
    """
    Return the full Velvet Lounge MCP state as JSON.

    Includes: trust, heat, active song, atmosphere, active rules,
    narrative entries, character moods, and pending consequences.

    Returns: JSON state snapshot.
    """
    from engine.mcp.tools.lounge import get_lounge_state
    return get_lounge_state(scene_id)



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
    from engine.mcp.tools.lounge import reveal_lounge_secret
    return reveal_lounge_secret(character_id, secret_id, trust_level, scene_id)



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
    from engine.mcp.tools.lounge import trigger_lounge_event
    return trigger_lounge_event(event_id, scene_id)



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
    from engine.mcp.tools.lounge import lounge_heat_tick
    return lounge_heat_tick(delta, scene_id)



# ══════════════════════════════════════════════════════════════════════
#  MCP RESOURCES
# ══════════════════════════════════════════════════════════════════════

def resource_config() -> str:
    """Current CosySim configuration snapshot."""
    from engine.mcp.tools.utility_tools import resource_config_logic as _impl
    return _impl(_get_config)


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
    from engine.mcp.tools.media import send_selfie
    return send_selfie(prompt, character_id, width, height)


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
    from engine.mcp.tools.media import send_voice_message
    return send_voice_message(text, character_id, emotion)


@mcp.tool()
def query_stateless(prompt: str, system: str = "") -> str:
    """
    Make a disposable one-off LLM query (store=false).
    Use this for quick decisions, classifications, or utility tasks
    that shouldn't affect the conversation state.
    Returns the raw response text.
    """
    from engine.mcp.tools.conversation import query_stateless
    return query_stateless(prompt, system)



@mcp.tool()
def get_conversation_info(conversation_id: str) -> str:
    """
    Get information about a conversation including response history
    and available branch points.
    Returns JSON with conversation state and forkable response IDs.
    """
    from engine.mcp.tools.conversation import get_conversation_info
    return get_conversation_info(conversation_id)



@mcp.tool()
def fork_conversation(conversation_id: str, turn: int = -1) -> str:
    """
    Create a conversation branch from a specific turn.
    Use this to try alternative approaches or undo to a previous point.
    Turn -1 means branch from the latest point.
    Returns the new forked conversation ID.
    """
    from engine.mcp.tools.conversation import fork_conversation
    return fork_conversation(conversation_id, turn)



@mcp.tool()
def get_conversation_heat_level(conversation_id: str) -> str:
    """
    Get the current heat level (0-100) for a conversation.
    Heat increases with flirty/intimate content and decays over time.
    Returns JSON with the heat level and current directive.
    """
    from engine.mcp.tools.dialog import get_conversation_heat_level
    return get_conversation_heat_level(conversation_id)



@mcp.tool()
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
    from engine.mcp.tools.conversation import bump_conversation_heat
    return bump_conversation_heat(conversation_id, amount, reason)



@mcp.tool()
def check_conversation_history(
    conversation_id: str,
    last_n: int = 5,
) -> str:
    """
    Review recent conversation messages for a thread.
    Useful for the agent to check context before responding.
    Returns the last N messages with metadata.
    """
    from engine.mcp.tools.conversation import check_conversation_history
    return check_conversation_history(conversation_id, last_n)



@mcp.tool()
def suggest_activity(scene_id: str = "phone") -> str:
    """
    Suggest a scene-appropriate activity based on current context.
    Returns a list of suggested activities with descriptions.
    """
    from engine.mcp.tools.agent import suggest_activity
    return suggest_activity(scene_id)


@mcp.resource("benchmark://summary")
def resource_benchmarks() -> str:
    """Performance benchmark summary with timing KPIs."""
    from engine.mcp.tools.system import resource_benchmarks
    return resource_benchmarks()



@mcp.resource("character://{character_id}")
def resource_character(character_id: str) -> str:
    """Full character profile including personality, state, and relationships."""
    from engine.mcp.tools.system import resource_character
    return resource_character(character_id)



@mcp.resource("chain://{chain_id}")
def resource_chain(chain_id: str) -> str:
    """Full EventChain tree for a specific chain."""
    from engine.mcp.tools.system import resource_chain
    return resource_chain(chain_id)



@mcp.resource("scene://{scene_name}/status")
def resource_scene_status(scene_name: str) -> str:
    """Scene health status and connection info."""
    from engine.mcp.tools.system import resource_scene_status
    return resource_scene_status(scene_name)




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