"""MCP tool domain: narrative.

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

# ──── NARRATIVE TOOLS ────────────────────────────────────────────────────


@mcp_tool
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
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.character_registry import get_character_registry
        from engine.mcp.tools.dialog_tools import speak_as as _impl
        return _impl(get_dialog_system(), get_character_registry(),
                     character_id, text, style=style, scene_id=scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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
        from engine.mcp.tools.dialog_tools import enforce_behavior as _impl
        return _impl(get_dialog_system(), character_id, behavior_type, value,
                     reason=reason, scene_id=scene_id, turns=turns, ssm=_ssm())
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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
        from engine.mcp.tools.scene_tools import scene_broadcast as _impl
        return _impl(scene_id, event_type, payload_json=payload_json,
                     target_characters_json=target_characters_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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
            logger.debug("Suppressed exception", exc_info=True)

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
