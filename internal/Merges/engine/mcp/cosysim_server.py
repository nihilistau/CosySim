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
import random
import dataclasses


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

from engine.mcp.tools.memory_tools import (
    memory_recall as memory_recall_impl,
    time_echo as time_echo_impl,
    search_memory as search_memory_impl,
    store_memory as store_memory_impl,
)
from engine.mcp.tools.character_tools import (
    get_character_scene_stats_impl,
    update_character_scene_stats_impl,
    set_character_scene_stat_impl,
    reset_character_scene_stats_impl,
    check_character_consent_impl,
    get_character_agency_summary_impl,
)
from engine.mcp.tools.character_tools import (
    get_character_state as get_character_state_impl,
    adjust_relationship as adjust_relationship_impl,
    list_characters as list_characters_impl,
    character_register as character_register_impl,
    character_query as character_query_impl,
    character_set_attribute as character_set_attribute_impl,
    character_get_summary as character_get_summary_impl,
    character_assign_skill as character_assign_skill_impl,
    character_revoke_skill as character_revoke_skill_impl,
    character_get_skills as character_get_skills_impl,
    character_add_restriction as character_add_restriction_impl,
    character_remove_restriction as character_remove_restriction_impl,
)
from engine.mcp.tools.media_tools import (
    generate_image_request_logic as generate_image_request_impl,
    search_web_logic as search_web_impl,
    send_selfie_logic as send_selfie_impl,
    send_voice_message_logic as send_voice_message_impl,
)
from engine.mcp.tools.utility_tools import (
    roll_dice_logic as roll_dice_impl,
    get_random_topic_logic as get_random_topic_impl,
    get_system_stats_logic as get_system_stats_impl,
    start_timer_logic as start_timer_impl,
    check_timer_logic as check_timer_impl,
    cancel_timer_logic as cancel_timer_impl,
    random_pick_logic as random_pick_impl,
    cross_scene_message_logic as cross_scene_message_impl,
    get_cross_scene_inbox_logic as get_cross_scene_inbox_impl,
    get_framework_status_logic as get_framework_status_impl,
    resource_config_logic as resource_config_impl,
    resource_benchmarks_logic as resource_benchmarks_impl,
    resource_character_logic as resource_character_impl,
    resource_chain_logic as resource_chain_impl,
    suggest_activity_logic as suggest_activity_impl,
)
from engine.mcp.tools.game_tools import (
    get_game_state as get_game_state_impl,
    set_game_state as set_game_state_impl,
    start_game as start_game_impl,
    end_game as end_game_impl,
    launch_game as launch_game_impl,
    get_active_game as get_active_game_impl,
    game_action as game_action_impl,
    game_history as game_history_impl,
)
from engine.mcp.tools.conversation_tools import (
    query_stateless_impl,
    get_conversation_info_impl,
    fork_conversation_impl,
    get_conversation_heat_level_impl,
    bump_conversation_heat_impl,
    check_conversation_history_impl,
)
from engine.mcp.tools.lounge_tools import (
    start_lounge_performance_impl,
    get_lounge_menu_impl,
    get_lounge_state_impl,
    reveal_lounge_secret_impl,
    trigger_lounge_event_impl,
    lounge_heat_tick_impl,
)
from engine.mcp.tools.interaction_tools import (
    perform_interaction_impl,
    list_available_interactions_impl,
    get_interaction_details_impl,
    start_timed_action_impl,
    poll_timed_action_impl,
    abort_timed_action_impl,
    list_active_timed_actions_impl,
)
from engine.mcp.tools.scene_tools import (
    get_scene_context as get_scene_context_impl,
    add_scene_narrative as add_scene_narrative_impl,
    get_scene_narrative as get_scene_narrative_impl,
    get_full_scene_snapshot as get_full_scene_snapshot_impl,
    set_scene_atmosphere as set_scene_atmosphere_impl,
    get_scene_rules as get_scene_rules_impl,
    get_scene_available_actions as get_scene_available_actions_impl,
    apply_scene_rule as apply_scene_rule_impl,
    scene_broadcast as scene_broadcast_impl,
    get_scene_rules_summary as get_scene_rules_summary_impl,
    resource_scene_status as resource_scene_status_impl,
)
from engine.mcp.tools.wardrobe_tools import (
    wardrobe_get as wardrobe_get_impl,
    wardrobe_init as wardrobe_init_impl,
    wardrobe_remove_item as wardrobe_remove_item_impl,
    wardrobe_remove_outermost as wardrobe_remove_outermost_impl,
    wardrobe_add_item as wardrobe_add_item_impl,
    wardrobe_redress as wardrobe_redress_impl,
)
from engine.mcp.tools.dialog_tools import (
    get_dialog_options as get_dialog_options_impl,
    speech_enhance as speech_enhance_impl,
    set_response_directive as set_response_directive_impl,
    get_active_directive as get_active_directive_impl,
    clear_directive as clear_directive_impl,
    get_conversation_heat as get_conversation_heat_impl,
    speak_as as speak_as_impl,
    enforce_behavior as enforce_behavior_impl,
)


from engine.mcp.scene_state import get_scene_state_manager, InteractionRecord
from engine.mcp.comms_framework import get_router, get_skill_manifest

# ── Lazy service getters (avoid import-time side effects) ──────────────


def _get_db():
    from content.simulation.database.db import Database

    return Database()


def _get_rag():
    try:
        from content.simulation.database.rag import RAGManager
        return RAGManager()
    except ImportError:
        return None
    except BaseException:
        return None


def _get_config():
    from engine.config import get_config

    return get_config()


# ═══════════════════════════════════════════════════════════════════════
#  MCP TOOLS  (actions the LLM can execute)
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def search_memory(
    query: str, character_id: Optional[str] = None, top_k: int = 5
) -> str:
    """
    Search character memories using RAG vector search.
    Returns the most relevant stored memories for the given query.
    Use this to recall past conversations, facts, or context.
    """
    return search_memory_impl(query, _get_rag(), character_id=character_id, top_k=top_k)


@mcp.tool()
def store_memory(text: str, character_id: str, metadata: Optional[str] = None) -> str:
    """
    Store a new memory for a character in the RAG system.
    Use this to save important facts, conversation summaries, or observations.
    """
    return store_memory_impl(text, character_id, _get_rag(), metadata=metadata)


@mcp.tool()
def get_character_state(character_id: str) -> str:
    """
    Get the current state of a character including mood, energy, and relationships.
    Returns JSON with all character state fields.
    """
    return get_character_state_impl(character_id, _get_db())


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
    return adjust_relationship_impl(character_a, character_b, field, delta, _get_db())


@mcp.tool()
def get_chain_events(chain_id: str, limit: int = 20) -> str:
    """
    Get events from an EventChain by chain_id.
    Returns a list of events with type, actor, timestamp, and summary.
    Use this to inspect what happened in an interaction chain.
    """
    from engine.mcp.tools.utility_tools import get_chain_events_impl
    return get_chain_events_impl(chain_id, limit=limit, db=_get_db())


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
    from engine.mcp.tools.utility_tools import log_event_impl
    return log_event_impl(
        chain_id, event_type, actor, summary, payload=payload, character_id=character_id, db=_get_db()
    )


@mcp.tool()
def list_characters() -> str:
    """
    List all characters in the database with their names and IDs.
    """
    return list_characters_impl(_get_db())


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
    return generate_image_request_impl(prompt, width=width, height=height, character_id=character_id)


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
    from engine.mcp.tools.scene_tools import get_my_skills_impl
    return get_my_skills_impl(scene, get_skill_manifest())


# ── Randomness & game mechanics ────────────────────────────────────────


@mcp.tool()
def roll_dice(sides: int = 6, count: int = 1) -> str:
    """
    Roll one or more dice and return the results.
    Useful for game mechanics, random outcomes, or adding unpredictability.
    Example: roll_dice(100) gives a d100 result for truth-or-dare.
    Odd results = Truth, Even results = Dare (for truth-or-dare game).
    """
    return roll_dice_impl(sides, count)


@mcp.tool()
def get_random_topic(category: str = "general") -> str:
    """
    Get a randomly selected topic or prompt for conversation or games.
    Categories: 'truth_questions', 'dare_ideas', 'mystery_clues',
    'conversation_starters', 'relationship_questions', 'general'.
    Use this to get fresh ideas for games, topics, or challenges.
    """
    return get_random_topic_impl(category)


# ── Game state ─────────────────────────────────────────────────────────


@mcp.tool()
def get_game_state(game_id: str, key: Optional[str] = None) -> str:
    """
    Read the current state of a game by its ID.
    If key is provided, returns only that value.
    If key is None, returns the entire game state dict.
    Common game IDs: 'truth_or_dare', 'mystery'.
    """
    return get_game_state_impl(game_id, key=key)


@mcp.tool()
def set_game_state(game_id: str, key: str, value: str) -> str:
    """
    Write a value to the game state.
    Use this to record scores, round counts, discovered clues, game outcomes, etc.
    Value is stored as a string — use JSON encoding for complex types.
    Example: set_game_state('truth_or_dare', 'round', '3')
    """
    return set_game_state_impl(game_id, key, value)


@mcp.tool()
def start_game(
    game_id: str, scene: str = "phone", config_json: Optional[str] = None
) -> str:
    """
    Start a new game session.
    game_id options: 'truth_or_dare', 'mystery'
    This resets existing game state and marks the game as active.
    The game rules will automatically be injected into your system context.
    """
    return start_game_impl(game_id, scene, config_json)


@mcp.tool()
def end_game(game_id: str) -> str:
    """
    End a game and record the final result.
    Returns a summary of the final game state including score.
    """
    return end_game_impl(game_id)


# ── MCP-tracked game tools (MCPGameSession) ───────────────────────────


@mcp.tool()
def launch_game(
    character_id: str,
    game_type: str,
    case_index: int = -1,
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
    return launch_game_impl(character_id, game_type, case_index)


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
    return get_active_game_impl(character_id)


@mcp.tool()
def game_action(
    character_id: str,
    action: str,
    data_json: str = "{}",
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
    return game_action_impl(character_id, action, data_json)


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
    return game_history_impl(character_id, limit)


# ── Character emotion & mood ───────────────────────────────────────────


@mcp.tool()
def update_mood(
    character_id: str,
    mood: str,
    reason: str = "",
    intensity: float = 0.5,
) -> str:
    """
    Update a character's current mood and optionally trigger emotional effects.
    mood options: 'happy', 'excited', 'sad', 'anxious', 'flirty', 'mysterious',
                  'playful', 'serious', 'irritated', 'loving', 'bored', 'curious'.
    intensity: float 0.0–1.0 (how strongly the mood is felt).
    reason: short string explaining what caused the mood change.
    Use this after an impactful event, a game result, or an emotional exchange.
    """
    from engine.mcp.tools.character_tools import update_mood_impl
    return update_mood_impl(character_id, mood, reason=reason, intensity=intensity, db=_get_db())


@mcp.tool()
def apply_effect(
    character_id: str,
    effect_name: str,
    value: float = 0.1,
) -> str:
    """
    Apply a status effect to a character's state.
    Effects are additive deltas on personality/relationship fields.
    effect_name options: 'trust_boost', 'attraction_boost', 'trust_drop',
    'energise', 'deflate', 'excite', 'calm', 'curiosity_spike'.
    value: magnitude of the effect (0.0–1.0).
    """
    from engine.mcp.tools.character_tools import apply_effect_impl
    return apply_effect_impl(character_id, effect_name, value=value, db=_get_db())


# ── Agent routing & communication ──────────────────────────────────────


@mcp.tool()
def send_to_agent(
    recipient_id: str,
    message: str,
    sender_id: str = "system",
) -> str:
    """
    Send a message to another agent's inbox.
    The recipient will see this message on their next reply tick.
    Use this for agent-to-agent communication, coordination, or triggering
    reactions in other characters.
    sender_id should be your character ID or 'system'.
    """
    from engine.mcp.tools.conversation_tools import send_to_agent_impl
    return send_to_agent_impl(recipient_id, message, get_router(), sender_id=sender_id).model_dump_json()


@mcp.tool()
def get_scene_context(scene: str = "phone") -> str:
    """
    Get context about what is currently happening in a scene:
    active characters, current game (if any), service health.
    Use this to understand the state of the world before acting.
    """
    return get_scene_context_impl(scene)


@mcp.tool()
def intercept_and_enhance(
    original_message: str,
    instruction: str,
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
    from engine.mcp.tools.dialog_tools import intercept_and_enhance_impl
    return intercept_and_enhance_impl(original_message, instruction, get_virtual_agent_manager()).model_dump_json(indent=2)


# ── System stats ───────────────────────────────────────────────────────


@mcp.tool()
def get_system_stats() -> str:
    """
    Get current system resource usage: CPU, RAM, GPU VRAM, GPU temp,
    loaded LMStudio model, and activity bus status.
    Use this to check if the system is under load or what model is active.
    """
    return get_system_stats_impl()


@mcp.tool()
def check_relationship(character_a: str, character_b: str) -> str:
    """
    Get a concise relationship summary between two characters.
    Returns trust, attraction, relationship level and a natural-language
    summary. Use this before making decisions that depend on relationship state.
    """
    from engine.mcp.tools.character_tools import check_relationship_impl
    return check_relationship_impl(character_a, character_b, db=_get_db())


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web for information and return a summary of results.
    Use this when you need current information, facts, or knowledge
    that might not be in your training data.
    Returns a list of titles, snippets, and URLs.
    """
    return search_web_impl(query, max_results)


# ══════════════════════════════════════════════════════════════════════
# ██████████████████████████████████████████████████████████████████████
#  BEDROOM & PHONE  — Scene State, Wardrobe, Interactions, Narrative
# ██████████████████████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════


def _ssm():

    return get_scene_state_manager()


def _coord():

    return get_coordinator()


def _itrees():

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
    return wardrobe_get_impl(_ssm(), character_id)


@mcp.tool()
def wardrobe_init(character_id: str, style: str = "casual") -> str:
    """
    Give a character a full starter wardrobe.  Call this when a character first
    enters a scene so they have a clothing inventory.

    style: 'casual' | 'lingerie' | 'party' | 'nightwear' | 'swimwear'
    """
    return wardrobe_init_impl(_ssm(), character_id, style=style)


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
    return wardrobe_remove_item_impl(_ssm(), character_id, item_id, removed_by=removed_by)


@mcp.tool()
def wardrobe_remove_outermost(character_id: str, removed_by: str = "") -> str:
    """
    Strip the outermost clothing layer from a character — perfect for a
    striptease or when the Director wants the next item to come off without
    specifying which one.

    Returns what was removed and what's left.  Call repeatedly to fully
    undress.
    """
    return wardrobe_remove_outermost_impl(_ssm(), character_id, removed_by=removed_by)


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
    return wardrobe_add_item_impl(
            _ssm(), character_id, item_id, name, category, color=color, style=style
        )


@mcp.tool()
def wardrobe_redress(character_id: str) -> str:
    """
    Put all previously removed clothing back on a character.
    Use at scene reset or morning-after scenarios.
    """
    return wardrobe_redress_impl(_ssm(), character_id)


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
    return get_character_scene_stats_impl(character_id)


@mcp.tool()
def update_character_scene_stats(character_id: str, stat_changes: str) -> str:
    """
    Adjust a character's scene stats by delta values.  Pass a JSON string like:
    '{"arousal": 15, "happiness": -10, "openness": 5}'

    Stats clamp at 0-100.  Use positive values to increase, negative to decrease.
    Call this after interactions, events, emotional moments.
    """
    return update_character_scene_stats_impl(character_id, stat_changes)


@mcp.tool()
def set_character_scene_stat(character_id: str, stat: str, value: float) -> str:
    """
    Set a specific stat to an exact value (0-100).  Use when you need precision
    rather than a delta — e.g. resetting a stat at scene start.

    stat: arousal | horniness | pleasure | happiness | anger | fear |
          drunkenness | tiredness | explicitness | openness | affection | dominance
    """
    return set_character_scene_stat_impl(character_id, stat, value)


@mcp.tool()
def reset_character_scene_stats(character_id: str) -> str:
    """Reset all scene stats for a character back to defaults (scene reset / new character)."""
    return reset_character_scene_stats_impl(character_id)


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
    return perform_interaction_impl(
        interaction_type, initiator_id, target_id, scene_id, subtype, intensity
    )


@mcp.tool()
def list_available_interactions(character_id: str, scene_id: str = "bedroom") -> str:
    """
    List all interaction types and their accessible subtypes for a character
    based on their current stats.  Use this before calling perform_interaction
    to know what's available without guessing.

    Returns a filtered list — only shows subtypes whose stat requirements are met.
    """
    return list_available_interactions_impl(character_id, scene_id)


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
    return get_interaction_details_impl(interaction_type, subtype, scene_id)


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
    return start_timed_action_impl(
        character_id, action_type, duration_secs, description, phases
    )


@mcp.tool()
def poll_timed_action(token: str) -> str:
    """
    Check the progress of a running timed action.
    Returns phase name, progress (0.0-1.0), elapsed time, and completion status.

    Check this periodically to narrate an unfolding scene.  When complete=true
    the action has finished — emit the afterglow narrative.
    """
    return poll_timed_action_impl(token)


@mcp.tool()
def abort_timed_action(token: str) -> str:
    """Stop a timed action early (e.g. interrupted by Director or refused by character)."""
    return abort_timed_action_impl(token)


@mcp.tool()
def list_active_timed_actions(character_id: str = "") -> str:
    """
    List all currently running timed actions.
    Pass character_id to filter to a specific character, or leave blank for all.
    """
    return list_active_timed_actions_impl(character_id)


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
    return add_scene_narrative_impl(scene_id, event, character_id=character_id, entry_type=entry_type)


@mcp.tool()
def get_scene_narrative(scene_id: str, limit: int = 20) -> str:
    """
    Read the last N entries from the scene's narrative log.
    Use this to maintain continuity — know what has already happened.

    Returns a text summary and a structured list of entries.
    Always call this at scene start and after resuming a paused session.
    """
    return get_scene_narrative_impl(scene_id, limit)


@mcp.tool()
def get_full_scene_snapshot(scene_id: str, character_ids: str = "") -> str:
    """
    Get a complete snapshot of the scene state — all characters' stats, wardrobes,
    emotional states, current timed actions, atmosphere, and recent narrative.

    character_ids: comma-separated list, or blank to include all known characters.

    Use this at scene start, after a skip, or to ground your response in the
    current reality of the room.  This is your oracle.
    """
    return get_full_scene_snapshot_impl(scene_id, character_ids)


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
    return set_scene_atmosphere_impl(
            scene_id,
            lighting=lighting,
            mood=mood,
            music=music,
            temperature=temperature,
            props_present=props_present,
            note=note,
        )


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
    return check_character_consent_impl(character_id, action_type)


@mcp.tool()
def get_character_agency_summary(character_id: str) -> str:
    """
    Get a full picture of a character's current agency — who they are RIGHT NOW.
    Includes emotional state, compliance level, what they most want, what they'd
    resist, and what they might spontaneously initiate.

    Use this to write authentic agent responses that feel real rather than always-compliant.
    """
    return get_character_agency_summary_impl(character_id)


# NOTE: get_scene_rules() defined below in SCENE RULES ENGINE TOOLS section
# (delegates to SceneRulesEngine for dynamic per-scene rules)


@mcp.tool()
def get_all_tools_for_scene(scene_id: str = "bedroom") -> str:
    """
    Get a complete reference of all MCP tools available in a scene.
    Call this at the start of a session so you know every tool at your disposal.
    Agents should internalise this list and joke/reference their abilities naturally.
    """
    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl
    return get_all_tools_for_scene_impl(scene_id).model_dump_json(indent=2)
    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl
    return get_all_tools_for_scene_impl(scene_id).model_dump_json(indent=2)
    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl
    return get_all_tools_for_scene_impl(scene_id).model_dump_json(indent=2)
    from engine.mcp.tools.scene_tools import get_all_tools_for_scene_impl
    return get_all_tools_for_scene_impl(scene_id).model_dump_json(indent=2)
