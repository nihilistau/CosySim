"""
Coders Room Skills — MCP skill functions for the AI Agent Idle Simulation.

Exposes feature management, pipeline control, agent status, and sandboxed
code execution as @skill-decorated functions callable by LMS agents via
tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_coders_scene():
    """Look up the running Coders Room scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("coders")


# ── Simulation Control ────────────────────────────────────────

@skill(
    pack="coders",
    tags=["game", "coding", "simulation"],
    category=SkillCategory.SYSTEM,
    description="Get the current Coders Room simulation status.",
)
def coders_status() -> str:
    """Return simulation state: agents, features, pipeline progress."""
    scene = _get_coders_scene()
    if not scene or not scene.state:
        return "Coders Room not active."
    st = scene.state
    busy = [a for a in st.agents if a.status != "idle"]
    feature = st.get_current_feature()
    lines = [
        f"Simulation: {'RUNNING' if st.active else 'STOPPED'} | Tick: {st.tick_count}",
        f"Features: {len(st.features)} queued, {len(st.completed_features)} completed",
        f"Total lines: {st.total_lines} | Total tests: {st.total_tests}",
    ]
    if feature:
        lines.append(f"Current feature: '{feature.title}' — phase: {feature.phase.value}")
    if busy:
        lines.append(f"Busy agents: {', '.join(f'{a.name} ({a.status})' for a in busy)}")
    else:
        lines.append("All agents idle.")
    return "\n".join(lines)


@skill(
    pack="coders",
    tags=["game", "coding"],
    category=SkillCategory.SYSTEM,
    description="Get detailed info about a specific coding agent.",
)
def coders_agent_info(agent_id: str) -> str:
    """Return stats for a specific agent (lines written, reviews, tests)."""
    scene = _get_coders_scene()
    if not scene or not scene.state:
        return "Coders Room not active."
    agent = scene.state.get_agent(agent_id)
    if not agent:
        names = ", ".join(f"{a.id} ({a.name})" for a in scene.state.agents)
        return f"Agent '{agent_id}' not found. Available: {names}"
    return (
        f"{agent.name} ({agent.role.value}) | Desk #{agent.desk_slot}\n"
        f"Status: {agent.status} | Mood: {agent.mood}\n"
        f"Lines written: {agent.lines_written} | Reviews: {agent.reviews_done} | Tests: {agent.tests_run}\n"
        f"Current task: {agent.current_task or 'None'}"
    )


# ── Feature Management ────────────────────────────────────────

@skill(
    pack="coders",
    tags=["game", "coding", "features"],
    category=SkillCategory.GAME,
    description="Add a new feature request to the Coders Room pipeline.",
)
def coders_add_feature(title: str = "", description: str = "") -> str:
    """Queue a feature for the agents to implement. Random if no title given."""
    scene = _get_coders_scene()
    if not scene or not scene.state:
        return "Coders Room not active."
    feature = scene.state.add_feature(title or None, description or None)
    return f"Feature queued: '{feature.title}' (ID: {feature.id}, phase: {feature.phase.value})"


@skill(
    pack="coders",
    tags=["game", "coding", "features"],
    category=SkillCategory.GAME,
    description="List all features in the pipeline with their current phase.",
)
def coders_feature_list() -> str:
    """Return all queued and completed features."""
    scene = _get_coders_scene()
    if not scene or not scene.state:
        return "Coders Room not active."
    st = scene.state
    lines = []
    if st.features:
        lines.append(f"📋 Pipeline ({len(st.features)}):")
        for f in st.features:
            lines.append(f"  [{f.phase.value}] {f.title}")
    if st.completed_features:
        lines.append(f"\n✅ Completed ({len(st.completed_features)}):")
        for f in st.completed_features:
            lines.append(f"  {f.title}")
    if not lines:
        lines.append("No features in pipeline.")
    return "\n".join(lines)


# ── Code Execution ────────────────────────────────────────────

@skill(
    pack="coders",
    tags=["coding", "sandbox"],
    category=SkillCategory.SYSTEM,
    description="Execute Python code in the Coders Room sandbox (10s timeout).",
    cooldown=5.0,
)
def coders_run_code(code: str, tests: str = "") -> str:
    """Execute Python code in a sandboxed subprocess. Optional test code appended."""
    scene = _get_coders_scene()
    if not scene or not scene.state:
        return "Coders Room not active."
    result = scene.state.execute_code(code, tests)
    status = "✅ SUCCESS" if result["success"] else "❌ FAILED"
    parts = [f"Execution: {status} (exit code: {result['returncode']})"]
    if result.get("stdout"):
        parts.append(f"stdout:\n{result['stdout'][:500]}")
    if result.get("stderr"):
        parts.append(f"stderr:\n{result['stderr'][:500]}")
    return "\n".join(parts)


@skill(
    pack="coders",
    tags=["coding", "simulation"],
    category=SkillCategory.SYSTEM,
    description="Manually trigger one pipeline tick in the Coders Room.",
)
def coders_tick() -> str:
    """Advance the simulation by one tick, processing the next pipeline phase."""
    scene = _get_coders_scene()
    if not scene or not scene.state:
        return "Coders Room not active."
    scene._tick()
    feature = scene.state.get_current_feature()
    if feature:
        return f"Tick {scene.state.tick_count}: Feature '{feature.title}' at phase '{feature.phase.value}'"
    return f"Tick {scene.state.tick_count}: No active feature (new one will be auto-queued)."
