"""Onboarding skill pack for CosySim v0.97 "THE LIVING CITY".

Provides LLM-agent-callable skills for the onboarding quest system:
checking tutorial status, advancing objectives, getting hints, and
managing the new-player experience.

All skills are registered under pack="onboarding".
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _mgr():
    from engine.world.onboarding import get_onboarding_manager
    return get_onboarding_manager()


# ── Query Skills ──────────────────────────────────────────────────────────

@skill(
    pack="onboarding",
    description="Check the player's onboarding tutorial status — current phase, quest progress, and objectives.",
    category="NARRATIVE",
)
def onboarding_status() -> str:
    """Return the current onboarding status.

    Returns:
        JSON string with phase, progress, and current quest info.
    """
    status = _mgr().get_status()
    return json.dumps(status, indent=2)


@skill(
    pack="onboarding",
    description="Get the current active onboarding quest with its objectives and progress.",
    category="NARRATIVE",
)
def onboarding_current_quest() -> str:
    """Return the current onboarding quest.

    Returns:
        JSON string with quest details, or message if complete.
    """
    quest = _mgr().get_current_quest()
    if quest:
        return json.dumps(quest, indent=2)
    if _mgr().is_completed:
        return "Onboarding complete — no active tutorial quests."
    return "Onboarding not started yet."


@skill(
    pack="onboarding",
    description="Get all onboarding quests and their completion status.",
    category="NARRATIVE",
)
def onboarding_all_quests() -> str:
    """Return all onboarding quests.

    Returns:
        JSON string with all quest data.
    """
    quests = _mgr().get_all_quests()
    return json.dumps(quests, indent=2)


@skill(
    pack="onboarding",
    description="Get the next hint for the player's current onboarding objective.",
    category="NARRATIVE",
)
def onboarding_hint() -> str:
    """Return the next hint.

    Returns:
        Hint string for the current objective.
    """
    hint = _mgr().get_next_hint()
    return hint or "No hints available — you're on your own, runner."


@skill(
    pack="onboarding",
    description="Get all phone messages sent during onboarding (encrypted messages from Ghost, intros from NPCs).",
    category="NARRATIVE",
)
def onboarding_messages() -> str:
    """Return all onboarding messages.

    Returns:
        JSON string with message list.
    """
    messages = _mgr().get_pending_messages()
    return json.dumps(messages, indent=2)


# ── Action Skills ─────────────────────────────────────────────────────────

@skill(
    pack="onboarding",
    description="Start the onboarding tutorial for a new player. Sends the first encrypted phone message.",
    category="NARRATIVE",
)
def onboarding_start() -> str:
    """Begin the onboarding experience.

    Returns:
        JSON string with start status and first quest.
    """
    result = _mgr().start_onboarding()
    return json.dumps(result, indent=2)


@skill(
    pack="onboarding",
    description="Advance an onboarding objective by marking it complete. Pass the objective ID.",
    category="NARRATIVE",
)
def onboarding_advance(objective_id: str) -> str:
    """Mark an onboarding objective as completed.

    Args:
        objective_id: The objective to complete (e.g., 'visit_grid', 'talk_to_viktor').

    Returns:
        JSON string with result and any rewards granted.
    """
    result = _mgr().advance(objective_id)
    return json.dumps(result, indent=2)


@skill(
    pack="onboarding",
    description="Record that the player visited a scene. Auto-advances any matching onboarding objectives.",
    category="NARRATIVE",
)
def onboarding_visit_scene(scene_name: str) -> str:
    """Record a scene visit.

    Args:
        scene_name: Scene identifier (e.g., 'grid', 'penthouse', 'tavern').

    Returns:
        JSON string with any objectives completed.
    """
    result = _mgr().record_scene_visit(scene_name)
    if result:
        return json.dumps(result, indent=2)
    return f"Scene '{scene_name}' visit recorded."


@skill(
    pack="onboarding",
    description="Record that the player met an NPC. Auto-advances any matching onboarding objectives.",
    category="NARRATIVE",
)
def onboarding_meet_npc(npc_name: str) -> str:
    """Record meeting an NPC.

    Args:
        npc_name: NPC identifier (e.g., 'viktor', 'lola', 'frankie').

    Returns:
        JSON string with any objectives completed.
    """
    result = _mgr().record_npc_met(npc_name)
    if result:
        return json.dumps(result, indent=2)
    return f"NPC '{npc_name}' meeting recorded."


@skill(
    pack="onboarding",
    description="Record that the player completed a mission. Auto-advances mission-related onboarding objectives.",
    category="NARRATIVE",
)
def onboarding_mission_done() -> str:
    """Record a mission completion for onboarding tracking.

    Returns:
        JSON string with any objectives completed.
    """
    result = _mgr().record_mission_completed()
    if result:
        return json.dumps(result, indent=2)
    return "Mission completion recorded."


@skill(
    pack="onboarding",
    description="Check if any reputation/credit/faction thresholds have been crossed for onboarding objectives.",
    category="NARRATIVE",
)
def onboarding_check_progress() -> str:
    """Check reputation-based onboarding objectives.

    Returns:
        JSON string with any newly completed objectives.
    """
    result = _mgr().check_reputation_objectives()
    if result:
        return json.dumps(result, indent=2)
    return "No new thresholds crossed."


@skill(
    pack="onboarding",
    description="Skip the entire onboarding tutorial. For returning players or developers.",
    category="SYSTEM",
)
def onboarding_skip() -> str:
    """Skip the tutorial entirely.

    Returns:
        JSON string with skip confirmation.
    """
    result = _mgr().skip()
    return json.dumps(result, indent=2)
