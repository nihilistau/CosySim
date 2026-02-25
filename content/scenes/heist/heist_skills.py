"""
Heist MCP skills — registered with the skills server for LLM tool calling.

These skills let the LLM (as crew members) interact with the heist state:
take actions, check obstacles, gather intel, coordinate with other crew.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _get_heist():
    """Get the active HeistScene instance."""
    from engine.scenes.base_scene import BaseScene
    scene = BaseScene.get_active_scene("heist")
    if scene and hasattr(scene, "game"):
        return scene.game
    return None


@skill(
    name="heist_status",
    description="Get the current heist situation: phase, suspicion, crew status, obstacles, loot.",
    pack="heist",
    cooldown=2,
)
def heist_status() -> str:
    """Returns a text summary of the current heist state."""
    game = _get_heist()
    if not game:
        return "No active heist."
    return game.situation_summary()


@skill(
    name="heist_action",
    description=(
        "Perform a heist action. Actions: disable_alarm, crack_safe, hack_door, "
        "breach_door, fight, persuade, distract, bribe, intimidate, drive, scout, "
        "carry_loot, loop_cameras, jam_comms, improvise, getaway. "
        "Each action has a success chance based on the crew member's specialty."
    ),
    pack="heist",
    cooldown=3,
)
def heist_action(character_id: str, action: str) -> str:
    """Perform an action during the heist."""
    game = _get_heist()
    if not game:
        return json.dumps({"error": "No active heist"})
    result = game.perform_action(character_id, action)
    return json.dumps(result)


@skill(
    name="heist_advance_phase",
    description="Advance the heist to the next phase. Phases: planning → approach → execution → escape → complete.",
    pack="heist",
    cooldown=5,
)
def heist_advance_phase() -> str:
    """Move to the next heist phase."""
    game = _get_heist()
    if not game:
        return "No active heist."
    new_phase = game.advance_phase()
    return f"Phase advanced to: {new_phase.value}"


@skill(
    name="heist_collect_loot",
    description="Collect loot from the current location. Amount in dollars.",
    pack="heist",
    cooldown=3,
)
def heist_collect_loot(amount: int = 50000) -> str:
    """Grab some loot."""
    game = _get_heist()
    if not game:
        return "No active heist."
    total = game.collect_loot(amount)
    return f"Collected ${amount:,}. Total haul: ${total:,} / ${game.loot_target:,}"


@skill(
    name="heist_crew_check",
    description="Check the status and skills of a specific crew member.",
    pack="heist",
    cooldown=1,
)
def heist_crew_check(character_id: str) -> str:
    """Get detailed crew member info."""
    game = _get_heist()
    if not game:
        return "No active heist."
    member = game.crew.get(character_id)
    if not member:
        return f"No crew member with id '{character_id}'."
    from content.scenes.heist.heist_game import SKILL_TABLE
    skills = SKILL_TABLE.get(member.specialty, {})
    top_skills = sorted(skills.items(), key=lambda x: -x[1])[:5]
    skill_text = ", ".join(f"{s[0]}({int(s[1]*100)}%)" for s in top_skills)
    return (
        f"{member.name} ({member.specialty.value})\n"
        f"  Health: {member.health} | Morale: {member.morale}\n"
        f"  Status: {'arrested' if member.arrested else ('injured' if member.injured else 'ok')}\n"
        f"  Top skills: {skill_text}"
    )


@skill(
    name="heist_obstacles",
    description="List remaining obstacles that need to be cleared to complete the heist.",
    pack="heist",
    cooldown=2,
)
def heist_obstacles() -> str:
    """What stands between you and the loot."""
    game = _get_heist()
    if not game:
        return "No active heist."
    if not game.obstacles_remaining:
        return "All obstacles cleared! Time to grab the loot and escape."
    return "Remaining obstacles: " + ", ".join(game.obstacles_remaining)
