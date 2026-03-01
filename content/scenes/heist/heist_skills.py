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


# ══════════════════════════════════════════════════════════════════════
#  v0.68 "Dark Renaissance" — THE SCORE skills
# ══════════════════════════════════════════════════════════════════════


def _get_heist_scene():
    """Get the active HeistScene instance (not just the game state)."""
    from engine.scenes.base_scene import BaseScene
    return BaseScene.get_active_scene("heist")


@skill(
    name="get_heist_jobs",
    description="Get available heist jobs from the planning board",
    pack="heist",
    cooldown=3,
)
def get_heist_jobs() -> str:
    """Return a list of available heist jobs with payout and risk information."""
    import json
    scene = _get_heist_scene()
    jobs = []
    # Try ContentEngine first
    try:
        from engine.content.content_engine import get_content_engine
        ce = get_content_engine()
        if hasattr(ce, "get_heist_jobs"):
            jobs = ce.get_heist_jobs() or []
    except Exception:
        pass
    # Fallback to VENUES
    if not jobs:
        try:
            from content.scenes.heist.heist_game import VENUES
            jobs = [
                {
                    "id": k,
                    "name": v.get("name", k),
                    "payout": v.get("loot_value", 500_000),
                    "difficulty": v.get("difficulty", 1),
                    "guards": v.get("guards", 0),
                }
                for k, v in VENUES.items()
            ]
        except Exception:
            return "Unable to retrieve available jobs."
    return json.dumps(jobs)


@skill(
    name="select_heist",
    description="Select a heist job as the active target",
    pack="heist",
    cooldown=5,
)
def select_heist(job_id: str) -> str:
    """Set the active heist target by job ID.

    Args:
        job_id: The identifier of the heist venue/job to select.

    Returns:
        Confirmation string with job details or an error message.
    """
    if not job_id:
        return "Specify a job_id to select."
    try:
        from content.scenes.heist.heist_game import VENUES
        venue = VENUES.get(job_id)
        if not venue:
            return f"Unknown job: '{job_id}'. Available: {', '.join(VENUES.keys())}"
        scene = _get_heist_scene()
        if scene and hasattr(scene, "_active_job_id"):
            scene._active_job_id = job_id
        name = venue.get("name", job_id)
        payout = venue.get("loot_value", 0)
        diff = venue.get("difficulty", 1)
        return f"Job selected: {name} | Payout: ${payout:,} | Difficulty: {diff}/3"
    except Exception as exc:
        return f"Failed to select job: {exc}"


@skill(
    name="assign_crew_member",
    description="Assign a crew member to a role in the active heist",
    pack="heist",
    cooldown=2,
)
def assign_crew_member(crew_member: str, role: str) -> str:
    """Assign a crew member to a specific operational role.

    Args:
        crew_member: The crew member's ID (e.g. 'ghost', 'tank', 'silk', 'wheels').
        role: The operational role (e.g. 'mastermind', 'hacker', 'lookout', 'muscle', 'driver').

    Returns:
        Confirmation string or error message.
    """
    if not crew_member or not role:
        return "Specify both crew_member and role."
    game = _get_heist()
    if game and crew_member not in game.crew:
        available = ", ".join(game.crew.keys()) if game.crew else "none"
        return f"Crew member '{crew_member}' not found. Active crew: {available}"
    scene = _get_heist_scene()
    if scene and hasattr(scene, "_assigned_roles"):
        scene._assigned_roles[crew_member] = role
    return f"{crew_member.capitalize()} assigned as {role.upper()}."


@skill(
    name="execute_heist_phase",
    description="Execute the current heist phase",
    pack="heist",
    cooldown=5,
)
def execute_heist_phase(phase: str) -> str:
    """Advance the heist to execute the specified phase.

    Args:
        phase: Target phase to execute (planning/approach/execution/escape).

    Returns:
        Result string including new phase and any complications.
    """
    game = _get_heist()
    if not game:
        return "No active heist to execute."
    current = game.phase.value
    new_phase = game.advance_phase()
    comp = game.maybe_complication()
    result = f"Phase advanced: {current} → {new_phase.value}"
    if comp:
        result += f" | COMPLICATION: {comp}"
    if game.check_bust():
        result += " | ⚠ BLOWN — too much heat!"
    elif game.check_victory():
        result += " | ✓ THE SCORE — clean exit."
    return result


@skill(
    name="crew_status",
    description="Get current crew status and heist heat level",
    pack="heist",
    cooldown=2,
)
def crew_status() -> str:
    """Return a full status report: heat level, phase, and each crew member's state.

    Returns:
        Human-readable status string suitable for LLM consumption.
    """
    game = _get_heist()
    if not game:
        return "No active heist."
    lines = [
        f"Phase: {game.phase.value.upper()}",
        f"Heat: {game.suspicion}/100",
        f"Loot: ${game.loot_collected:,} / ${game.loot_target:,}",
        "",
        "CREW:",
    ]
    for cid, member in game.crew.items():
        status_str = "ARRESTED" if member.arrested else ("INJURED" if member.injured else "OK")
        lines.append(
            f"  {member.name} ({member.specialty.value}) — "
            f"HP:{member.health} MOR:{member.morale} [{status_str}]"
        )
    scene = _get_heist_scene()
    if scene and hasattr(scene, "_assigned_roles") and scene._assigned_roles:
        lines.append("")
        lines.append("ROLES:")
        for m, r in scene._assigned_roles.items():
            lines.append(f"  {m} → {r}")
    if game.obstacles_remaining:
        lines.append("")
        lines.append("REMAINING: " + ", ".join(game.obstacles_remaining))
    return "\n".join(lines)
