"""
Advanced MCP tool registrations — character registry, dialog, rules, framework,
cross-scene, mood contagion, consequences, special skills, lounge, and streaming.

Extracted from cosysim_server.py for cleaner separation of concerns.
"""
from typing import Any, Dict, List, Optional


def register_advanced_tools(mcp) -> None:
    """Register advanced MCP tools and resources."""

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

    from engine.mcp._lazy import _get_config  # noqa: F811

    @mcp.resource("config://cosysim")
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
        from engine.mcp.tools.utility_tools import resource_benchmarks_logic
        return resource_benchmarks_logic()

    @mcp.resource("character://{character_id}")
    def resource_character(character_id: str) -> str:
        """Full character profile including personality, state, and relationships."""
        from engine.mcp.tools.utility_tools import resource_character_logic
        from engine.mcp._lazy import _get_db
        return resource_character_logic(character_id, _get_db())

    @mcp.resource("chain://{chain_id}")
    def resource_chain(chain_id: str) -> str:
        """Full EventChain tree for a specific chain."""
        from engine.mcp.tools.utility_tools import resource_chain_logic
        from engine.mcp._lazy import _get_db
        return resource_chain_logic(chain_id, _get_db())

    @mcp.resource("scene://{scene_name}/status")
    def resource_scene_status(scene_name: str) -> str:
        """Scene health status and connection info."""
        from engine.mcp.tools.scene_tools import resource_scene_status as _impl
        return _impl(scene_name)
