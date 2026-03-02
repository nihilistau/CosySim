"""
Pure business-logic functions for Velvet Lounge MCP tools.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import logging
from pydantic import BaseModel
from engine.mcp.decorators import mcp_tool, ToolExecutionError

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────


def _get_scene_state_manager():
    from engine.mcp.scene_state import get_scene_state_manager

    return get_scene_state_manager()


def _get_framework():
    from engine.mcp.comms_framework import get_framework

    return get_framework()


def _get_dialog_system():
    from engine.mcp.dialog_system import get_dialog_system

    return get_dialog_system()


def _get_rules_engine():
    from engine.mcp.scene_rules_engine import get_rules_engine

    return get_rules_engine()


def _get_character_registry():
    from engine.mcp.character_registry import get_character_registry

    return get_character_registry()


# ── Domain Models ────────────────────────────────────────────────────


class LoungeStateResponse(BaseModel):
    scene_id: str
    lola_state: Dict[str, Any]
    viktor_state: Dict[str, Any]
    atmosphere: Dict[str, Any]
    narrative: List[str]
    active_rules: List[Dict[str, Any]]
    fw_status: Dict[str, Any]


class HeatTickResponse(BaseModel):
    previous_heat: int
    new_heat: int
    delta: int
    rules_fired: List[str]


# ── Lounge Tools ─────────────────────────────────────────────────────


@mcp_tool
def start_lounge_performance_impl(
    song_id: str = "",
    lola_mood: int = 0,
    scene_id: str = "lounge",
) -> str:
    from content.scenes.lounge.lounge_mcp import SONGS, get_song_by_mood, LOLA_ID

    fw = _get_framework()
    ds = _get_dialog_system()
    ssm = _get_scene_state_manager()

    if song_id:
        song = next((s for s in SONGS if s["id"] == song_id), None)
        if not song:
            raise ToolExecutionError(f"Song '{song_id}' not found.")
    else:
        song = get_song_by_mood(lola_mood)

    # MCPTimer for song duration
    timer_id = fw.start_timer(
        name=f"song_{song['id']}",
        duration_secs=song["duration"],
        on_complete_note=f"song_complete:{song['id']}",
        metadata={"song": song["title"], "scene_id": scene_id},
    )

    # Atmosphere
    if song.get("atmosphere"):
        ssm.set_atmosphere(scene_id, **song["atmosphere"])

    # Directive for Lola
    ds.set_directive(
        character_id=LOLA_ID,
        scene_id=scene_id,
        directive_type="mood_set",
        value=f"performing '{song['title']}' — {song.get('note', '')}",
        turns=max(2, song["duration"] // 30),
        issued_by="start_lounge_performance",
    )

    # Narrative
    ssm.add_narrative(
        scene_id,
        LOLA_ID,
        f"Lola begins '{song['title']}'. {song.get('note', '')}",
    )

    return (
        f"Performance started: '{song['title']}'\n"
        f"Duration: {song['duration']}s  |  Timer: {timer_id}\n"
        f"Lola directive set for {max(2, song['duration'] // 30)} turns.\n"
        f"Effects on completion: {song['effects']}"
    )


@mcp_tool
def get_lounge_menu_impl(
    trust_level: int = 0,
    scene_id: str = "lounge",
) -> List[Dict[str, Any]]:
    from content.scenes.lounge.lounge_mcp import get_all_cocktails

    return get_all_cocktails(trust_level)


@mcp_tool
def get_lounge_state_impl(scene_id: str = "lounge") -> LoungeStateResponse:
    from content.scenes.lounge.lounge_mcp import LOLA_ID, VIKTOR_ID

    ssm = _get_scene_state_manager()
    fw = _get_framework()
    eng = _get_rules_engine()
    reg = _get_character_registry()

    lola_state = reg.get_state(LOLA_ID) or {}
    viktor_state = reg.get_state(VIKTOR_ID) or {}
    atm = ssm.get_atmosphere(scene_id) or {}
    narrative = ssm.get_narrative_entries(scene_id, limit=8)
    rules = eng.get_rules(scene_id)

    return LoungeStateResponse(
        scene_id=scene_id,
        lola_state=lola_state,
        viktor_state=viktor_state,
        atmosphere=atm,
        narrative=[e["event"] for e in narrative],
        active_rules=[{"id": r.rule_id, "label": r.label} for r in rules],
        fw_status=fw.get_status() if hasattr(fw, "get_status") else {},
    )


@mcp_tool
def reveal_lounge_secret_impl(
    character_id: str,
    secret_id: str = "",
    trust_level: int = 0,
    scene_id: str = "lounge",
) -> str:
    from content.scenes.lounge.lounge_mcp import (
        get_available_secrets,
        LOLA_ID,
        VIKTOR_ID,
    )

    fw = _get_framework()
    ds = _get_dialog_system()
    ssm = _get_scene_state_manager()

    secrets = get_available_secrets(character_id, trust_level)
    if not secrets:
        return "No secrets available at this trust level."

    secret = (
        secrets[0]
        if not secret_id
        else next((s for s in secrets if s["id"] == secret_id), secrets[0])
    )

    # Consequences for effects
    for stat, delta in (secret.get("effect") or {}).items():
        fw.schedule_consequence(
            scene_id=scene_id,
            character_id="guest",
            consequence_type="stat_adjust",
            params={"stat": stat, "delta": delta},
            trigger_after_turns=1,
            description=f"Secret '{secret['title']}' reveal effect",
        )

    # Directive: character voices this
    char_id = LOLA_ID if character_id == LOLA_ID else VIKTOR_ID
    ds.set_directive(
        character_id=char_id,
        scene_id=scene_id,
        directive_type="must_include",
        value=secret["content"][:120],
        turns=1,
        issued_by="reveal_lounge_secret",
    )

    ssm.add_narrative(scene_id, char_id, f"Reveals: '{secret['title']}'.")

    return (
        f"Secret revealed: {secret['title']}\n"
        f"Content: {secret['content']}\n"
        f"Effects: {secret.get('effect', {})}"
    )


@mcp_tool
def trigger_lounge_event_impl(
    event_id: str = "",
    scene_id: str = "lounge",
) -> str:
    from content.scenes.lounge.lounge_mcp import (
        pick_random_event,
        RANDOM_EVENTS,
        VIKTOR_ID,
        LOLA_ID,
    )

    fw = _get_framework()
    ssm = _get_scene_state_manager()

    if event_id:
        event = next((e for e in RANDOM_EVENTS if e["id"] == event_id), None)
        if not event:
            raise ToolExecutionError(f"Event '{event_id}' not found.")
    else:
        event = pick_random_event(heat_level=0)

    # Apply effects
    scheduled = []
    for stat, delta in (event.get("effects") or {}).items():
        if stat in ("arousal", "openness", "trust", "happiness", "heat"):
            fw.schedule_consequence(
                scene_id=scene_id,
                character_id="guest",
                consequence_type="stat_adjust",
                params={"stat": stat, "delta": delta},
                trigger_after_turns=1,
                description=f"Event '{event['id']}': {stat}{'+' if delta > 0 else ''}{delta}",
            )
            scheduled.append(f"{stat}{'+' if delta > 0 else ''}{delta}")

    # Viktor internal message
    if event.get("viktor_internal"):
        fw.cross_scene_send(
            from_char=VIKTOR_ID,
            from_scene=scene_id,
            to_char=LOLA_ID,
            to_scene=scene_id,
            message=event["viktor_internal"],
            message_type="internal",
        )

    ssm.add_narrative(scene_id, "scene", event["text"])

    effects_str = ", ".join(scheduled) if scheduled else "none"
    return f"Event fired: {event['text']}\nEffects queued: {effects_str}"


@mcp_tool
def lounge_heat_tick_impl(
    delta: int = 5,
    scene_id: str = "lounge",
) -> HeatTickResponse:
    from content.scenes.lounge.lounge_mcp import VIKTOR_ID, LOLA_ID

    fw = _get_framework()
    ssm = _get_scene_state_manager()
    eng = _get_rules_engine()

    # Read current heat
    scene_state = (
        ssm.get_character_state(scene_id) if hasattr(ssm, "get_character_state") else {}
    )
    current = int((scene_state or {}).get("heat_level", 0))
    new_heat = max(0, min(100, current + delta))

    # Persist
    ssm.update_stats(scene_id, heat_level=new_heat)

    fired = []
    if new_heat >= 85:
        try:
            eng.evaluate_event(scene_id, "heat_critical")
            fired.append("heat_critical")
        except Exception:
            pass
    elif new_heat >= 65:
        try:
            eng.evaluate_event(scene_id, "heat_warning")
            fired.append("heat_warning")
        except Exception:
            pass

    return HeatTickResponse(new_heat=new_heat, rules_fired=fired)


class ServeLoungeDrinkResponse(BaseModel):
    ok: bool
    drink: str
    narrative: str


@mcp_tool
def serve_lounge_drink_impl(
    drink_id: str,
    bartender_id: str,
    fw: Any,
    ssm: Any,
    ds: Any,
    scene_id: str = "lounge",
) -> ServeLoungeDrinkResponse:
    from content.scenes.lounge.lounge_mcp import get_cocktail, LOLA_ID, VIKTOR_ID

    cocktail = get_cocktail(drink_id)
    if not cocktail:
        raise Exception(f"No cocktail found with id '{drink_id}'.")

    scheduled = []
    for stat, delta in (cocktail.get("stat_effects") or {}).items():
        if stat in (
            "trust",
            "arousal",
            "openness",
            "inhibition",
            "happiness",
            "affection",
            "confidence",
        ):
            fw.schedule_consequence(
                scene_id=scene_id,
                character_id="guest",
                consequence_type="stat_adjust",
                params={"stat": stat, "delta": delta},
                trigger_after_turns=1,
                description=f"Drink '{cocktail['name']}': {stat} {'+' if delta > 0 else ''}{delta}",
            )
            scheduled.append(f"{stat}{'+' if delta > 0 else ''}{delta}")

    if cocktail.get("lola_reaction"):
        ds.set_directive(
            character_id=LOLA_ID,
            scene_id=scene_id,
            directive_type="must_include",
            value="catches the guest's eye briefly across the bar",
            turns=1,
            issued_by="serve_lounge_drink",
        )
        fw.cross_scene_send(
            from_char=VIKTOR_ID,
            from_scene=scene_id,
            to_char=LOLA_ID,
            to_scene=scene_id,
            message=f"Poured '{cocktail['name']}' for the guest.",
            message_type="drink_notification",
        )

    if cocktail.get("viktor_joins"):
        ds.set_directive(
            character_id=VIKTOR_ID,
            scene_id=scene_id,
            directive_type="must_include",
            value="pours a glass for himself, stays at that end of the bar",
            turns=1,
            issued_by="bourbon_ritual",
        )

    viktor_line = (
        cocktail.get("viktor_line")
        or f"Viktor serves the {cocktail['name']} without comment."
    )
    ssm.add_narrative(scene_id, VIKTOR_ID, viktor_line)

    effects_str = ", ".join(scheduled) if scheduled else "none"
    return ServeLoungeDrinkResponse(
        ok=True,
        drink=cocktail["name"],
        narrative=f"Viktor serves '{cocktail['name']}'. {cocktail.get('note', '')}\\nEffects queued (fires next turn): {effects_str}\\nScene: {viktor_line}",
    )
