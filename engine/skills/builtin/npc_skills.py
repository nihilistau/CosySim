"""NPC skills — runtime state management and activity overrides for NPCs.

Skill pack: ``npc``

Provides LLM-callable skills for querying and manually setting NPC world
state (location, activity, mood).  All state changes flow through
:class:`~engine.world.npc_state.NPCStateRegistry` so they are reflected
immediately in the MCPFramework tree and emitted as socket events.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


@skill(
    pack="npc",
    description="Get an NPC's current runtime state: location, activity, and mood.",
    category=SkillCategory.SYSTEM,
    tags=["npc", "state", "world"],
)
def get_npc_state(character_id: str) -> str:
    """Return the current state of an NPC as a formatted string.

    Args:
        character_id: The NPC's unique identifier.

    Returns:
        A human-readable summary of the NPC's state, or a 'not found' message.
    """
    from engine.world.npc_state import get_npc_state_registry
    registry = get_npc_state_registry()
    state = registry.get(character_id)
    if state is None:
        return f"NPC '{character_id}' has no recorded state yet."
    return (
        f"NPC: {state.character_id}\n"
        f"  Location : {state.location}\n"
        f"  Activity : {state.activity}\n"
        f"  Mood     : {state.mood}\n"
        f"  Busy     : {'yes' if state.is_busy else 'no'}\n"
        f"  Last action: {state.last_action or '—'}"
    )


@skill(
    pack="npc",
    description="List all NPCs that are currently active (non-idle).",
    category=SkillCategory.SYSTEM,
    tags=["npc", "world", "list"],
)
def list_active_npcs() -> str:
    """Return a formatted list of NPCs currently marked as busy/active.

    Returns:
        Newline-separated summary lines, or a message when none are active.
    """
    from engine.world.npc_state import get_npc_state_registry
    registry = get_npc_state_registry()
    busy = registry.list_busy()
    if not busy:
        return "No NPCs are currently active."
    lines = ["Active NPCs:"]
    for state in busy:
        lines.append(
            f"  • {state.character_id} @ {state.location} — {state.activity} [{state.mood}]"
        )
    return "\n".join(lines)


@skill(
    pack="npc",
    description="Manually set an NPC's current activity and location, overriding the scheduler.",
    category=SkillCategory.SYSTEM,
    tags=["npc", "state", "override"],
)
def set_npc_activity(character_id: str, activity: str, location: str = "") -> str:
    """Override an NPC's activity and optional location.

    Args:
        character_id: The NPC to update.
        activity: The new activity description.
        location: Optional new location; if empty, the existing location is kept.

    Returns:
        Confirmation message with the updated state.
    """
    from engine.world.npc_state import get_npc_state_registry
    registry = get_npc_state_registry()
    kwargs = {"activity": activity, "is_busy": True}
    if location:
        kwargs["location"] = location
    state = registry.update(character_id, **kwargs)
    loc_str = state.location
    return (
        f"✓ Updated {character_id}: activity='{activity}'"
        + (f", location='{loc_str}'" if location else "")
    )
