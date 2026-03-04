"""Mission skill pack for CosySim v0.82 "THE OPEN WORLD".

Provides LLM-agent-callable skills for the mission system:
browsing the board, accepting/abandoning missions, tracking objectives,
completing missions, assigning crew, and creating custom jobs.

All skills are registered under pack="mission".
"""
from __future__ import annotations

import logging
from typing import List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _mgr():
    from engine.world.mission import get_mission_manager
    return get_mission_manager()


# ---------------------------------------------------------------------------
# Query Skills
# ---------------------------------------------------------------------------

@skill(
    pack="mission",
    description="List missions available on the board, optionally filtered by location, type, or max difficulty.",
    category="NARRATIVE",
)
def mission_list(
    location: Optional[str] = None,
    mission_type: Optional[str] = None,
    max_difficulty: Optional[int] = None,
) -> str:
    """Return available missions.

    Args:
        location: Filter by scene name (e.g. 'THE GRID').
        mission_type: Filter by type: recon/heist/deal/extraction/hit.
        max_difficulty: Only show missions at or below this difficulty (1–5).

    Returns:
        JSON list of mission dicts.
    """
    import json
    missions = _mgr().list_available(location=location, mission_type=mission_type, max_difficulty=max_difficulty)
    if not missions:
        return json.dumps({"count": 0, "missions": [], "message": "No missions match the filters."})
    return json.dumps({"count": len(missions), "missions": missions})


@skill(
    pack="mission",
    description="Get the status of a specific mission by ID, including objectives and progress.",
    category="NARRATIVE",
)
def mission_status(mission_id: str) -> str:
    """Return full status of a mission.

    Args:
        mission_id: Mission identifier.

    Returns:
        JSON mission dict, or error if not found.
    """
    import json
    result = _mgr().get_status(mission_id)
    if not result:
        return json.dumps({"error": f"Mission {mission_id} not found."})
    return json.dumps(result, default=str)


@skill(
    pack="mission",
    description="List all currently active (accepted) missions.",
    category="NARRATIVE",
)
def mission_list_active() -> str:
    """Return all active missions.

    Returns:
        JSON list of active mission dicts.
    """
    import json
    missions = _mgr().list_active()
    return json.dumps({"count": len(missions), "missions": missions})


# ---------------------------------------------------------------------------
# Lifecycle Skills
# ---------------------------------------------------------------------------

@skill(
    pack="mission",
    description="Accept a mission from the board and make it active.",
    category="NARRATIVE",
    cooldown=1.0,
)
def mission_accept(mission_id: str) -> str:
    """Accept an available mission.

    Args:
        mission_id: Mission to accept.

    Returns:
        JSON with success flag and mission details.
    """
    import json
    return json.dumps(_mgr().accept(mission_id))


@skill(
    pack="mission",
    description="Abandon an active mission (minor reputation penalty).",
    category="NARRATIVE",
    cooldown=2.0,
)
def mission_abandon(mission_id: str) -> str:
    """Abandon an active mission.

    Args:
        mission_id: Mission to abandon.

    Returns:
        JSON with success flag and message.
    """
    import json
    return json.dumps(_mgr().abandon(mission_id))


@skill(
    pack="mission",
    description="Mark a mission objective as completed.",
    category="NARRATIVE",
)
def mission_complete_objective(mission_id: str, objective_id: str) -> str:
    """Mark a single objective as done.

    Args:
        mission_id: Parent mission ID.
        objective_id: Objective ID to mark complete.

    Returns:
        JSON with success flag and updated progress.
    """
    import json
    return json.dumps(_mgr().complete_objective(mission_id, objective_id))


@skill(
    pack="mission",
    description="Complete a mission and collect all rewards (credits, XP, items, faction rep). All required objectives must be done first.",
    category="NARRATIVE",
    cooldown=1.0,
)
def mission_complete(mission_id: str, notes: str = "") -> str:
    """Complete a mission and apply rewards.

    Args:
        mission_id: Mission to complete.
        notes: Optional completion notes or outcome description.

    Returns:
        JSON with success, rewards granted, and full mission dict.
    """
    import json
    return json.dumps(_mgr().complete(mission_id, notes=notes))


# ---------------------------------------------------------------------------
# Crew & Creation Skills
# ---------------------------------------------------------------------------

@skill(
    pack="mission",
    description="Assign crew members to an active mission to support or execute it.",
    category="NARRATIVE",
)
def mission_assign_crew(mission_id: str, crew_ids: str) -> str:
    """Assign crew to a mission.

    Args:
        mission_id: Active mission to assign crew to.
        crew_ids: Comma-separated crew member IDs.

    Returns:
        JSON with success and updated assigned_crew list.
    """
    import json
    ids = [c.strip() for c in crew_ids.split(",") if c.strip()]
    return json.dumps(_mgr().assign_crew(mission_id, ids))


@skill(
    pack="mission",
    description="Create a new custom mission and add it to the board.",
    category="NARRATIVE",
    cooldown=2.0,
)
def mission_create(
    title: str,
    description: str,
    mission_type: str,
    giver_npc: str,
    location: str,
    difficulty: int = 2,
    reward_credits: int = 1000,
    reward_xp: int = 50,
    objectives: Optional[str] = None,
) -> str:
    """Create a custom mission.

    Args:
        title: Mission name.
        description: Full mission brief.
        mission_type: One of recon/heist/deal/extraction/hit.
        giver_npc: NPC offering the mission.
        location: Primary scene location.
        difficulty: 1–5.
        reward_credits: Credits on completion.
        reward_xp: XP on completion.
        objectives: Semicolon-separated objective descriptions.

    Returns:
        JSON with new mission ID and dict.
    """
    import json
    obj_list: Optional[List[str]] = None
    if objectives:
        obj_list = [o.strip() for o in objectives.split(";") if o.strip()]
    return json.dumps(_mgr().create(
        title=title,
        description=description,
        mission_type=mission_type,
        giver_npc=giver_npc,
        location=location,
        difficulty=difficulty,
        reward_credits=reward_credits,
        reward_xp=reward_xp,
        objectives=obj_list,
    ))


@skill(
    pack="mission",
    description="Get the full mission board snapshot: available, active, and completed missions.",
    category="NARRATIVE",
)
def mission_board() -> str:
    """Return the full mission board state.

    Returns:
        JSON with available, active, and completed mission lists.
    """
    import json
    return json.dumps(_mgr().to_dict())
