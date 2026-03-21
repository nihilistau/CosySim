"""
Core MCP tool registrations — memory, character, comms, games, penthouse & phone.

Extracted from cosysim_server.py for cleaner separation of concerns.
"""
from typing import Any, Dict, List, Optional


def register_core_tools(mcp) -> None:
    """Register core MCP tools, comms framework tools, and penthouse/phone scene tools."""

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

    # NOTE: get_scene_rules() defined in SCENE RULES ENGINE TOOLS section
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
