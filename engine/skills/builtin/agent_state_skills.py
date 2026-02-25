"""
Agent State Skills — MCP skills for cross-scene agent management.

Allows agents to check their persistent state, reputation, relationships,
and achievements across different scenes.
"""
from __future__ import annotations

import logging
from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


@skill(
    pack="system",
    tags=["agent", "state", "cross-scene"],
    category=SkillCategory.SYSTEM,
    description="View an agent's persistent state: reputation, mood, achievements.",
)
def agent_persistent_state(agent_id: str = "") -> str:
    """Show cross-scene persistent state for an agent."""
    from engine.scenes.agent_state import get_agent_state_manager
    asm = get_agent_state_manager()
    if not agent_id:
        states = asm.get_all_states()
        if not states:
            return "No agents have persistent state yet."
        lines = ["👤 All Agents:"]
        for aid, state in states.items():
            lines.append(f"  {aid}: mood={state.mood}, scenes={state.stats['scenes_visited']}, "
                         f"achievements={len(state.achievements)}")
        return "\n".join(lines)
    state = asm.get_state(agent_id)
    return state.summary()


@skill(
    pack="system",
    tags=["agent", "reputation", "cross-scene"],
    category=SkillCategory.SYSTEM,
    description="Adjust an agent's reputation in a specific scene.",
)
def agent_adjust_reputation(agent_id: str, scene_name: str, delta: int = 5) -> str:
    """Change an agent's reputation for a scene. Positive = better."""
    from engine.scenes.agent_state import get_agent_state_manager
    asm = get_agent_state_manager()
    state = asm.get_state(agent_id)
    new_val = state.adjust_reputation(scene_name, delta)
    direction = "+" if delta > 0 else ""
    return f"📊 {agent_id} reputation in {scene_name}: {direction}{delta} → {new_val}/100"


@skill(
    pack="system",
    tags=["agent", "achievement"],
    category=SkillCategory.SYSTEM,
    description="Grant an achievement to an agent.",
)
def agent_grant_achievement(agent_id: str, achievement: str) -> str:
    """Give an agent an achievement. Returns False if already earned."""
    from engine.scenes.agent_state import get_agent_state_manager
    asm = get_agent_state_manager()
    state = asm.get_state(agent_id)
    if state.add_achievement(achievement):
        return f"🏅 Achievement unlocked for {agent_id}: '{achievement}'! Total: {len(state.achievements)}"
    return f"{agent_id} already has '{achievement}'."
