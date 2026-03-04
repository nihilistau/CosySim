"""MCP tool domain: lounge.

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

# ──── LOUNGE TOOLS ───────────────────────────────────────────────────────


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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
                logger.debug("Suppressed exception", exc_info=True)
        elif new_heat >= 65:
            try:
                eng.apply_rule(scene_id, "heat_warning_rule", target_ids=[VIKTOR_ID], issuer="heat_tick")
                fired.append("heat_warning_rule")
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

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
        return json.dumps(result, default=str)

    except Exception as exc:
        return f"lounge_heat_tick failed: {exc}"
