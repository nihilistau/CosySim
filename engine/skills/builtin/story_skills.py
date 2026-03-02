"""Story arc skills — LLM-callable tools for narrative arc management."""
from __future__ import annotations

import logging

from engine.skills.skill import skill
from engine.story.story_arc import ArcStatus, get_story_arc_engine

logger = logging.getLogger(__name__)


@skill(
    pack="story",
    description="Get story arc progress for the current scene",
    category="NARRATIVE",
)
def get_scene_story_state(scene: str) -> str:
    """Return a formatted summary of all arc states for a scene.

    Args:
        scene: The scene name to query.

    Returns:
        Human-readable arc progress summary.
    """
    engine = get_story_arc_engine()
    state = engine.get_scene_state(scene)
    arcs = state["arcs"]
    if not arcs:
        return f"No active story arcs for {scene}."
    lines = [f"Scene: {scene} | Progress: {state['overall_progress']:.0%}"]
    for a in arcs:
        lines.append(f"  [{a['status'].upper()}] {a['name']} — {a['progress']:.0%}")
    return "\n".join(lines)


@skill(
    pack="story",
    description="Advance a story arc step",
    category="NARRATIVE",
)
def advance_story_step(arc_id: str, step_id: str, success: bool = True) -> str:
    """Mark a step in a story arc as complete or failed.

    Args:
        arc_id: The arc to advance.
        step_id: The step within the arc.
        success: True to complete the step, False to fail it.

    Returns:
        Status string describing the arc state after advancement.
    """
    engine = get_story_arc_engine()
    arc = engine.advance_arc(arc_id, step_id, success)
    if not arc:
        return f"Arc '{arc_id}' not found."
    status_emoji = {
        "completed": "🏆",
        "failed": "💀",
        "active": "⚡",
        "inactive": "💤",
    }.get(arc.status, "")
    outcome = "succeeded" if success else "failed"
    return (
        f"{status_emoji} Arc '{arc.name}': step '{step_id}' {outcome}. "
        f"Progress: {arc.progress:.0%} [{arc.status}]"
    )


@skill(
    pack="story",
    description="Check if player won or lost a story arc",
    category="NARRATIVE",
)
def check_arc_outcome(arc_id: str) -> str:
    """Return the win/lose/progress outcome for an arc.

    Args:
        arc_id: The arc to check.

    Returns:
        Outcome description string.
    """
    engine = get_story_arc_engine()
    arc = engine.get_arc(arc_id)
    if not arc:
        return f"Arc '{arc_id}' not found."
    if arc.outcome == "win":
        return f"🏆 Victory! Arc '{arc.name}' completed successfully."
    if arc.outcome == "lose":
        return f"💀 Defeat. Arc '{arc.name}' failed."
    return f"Arc '{arc.name}' is {arc.status} ({arc.progress:.0%} complete)."


@skill(
    pack="story",
    description="List all story arcs for a scene",
    category="NARRATIVE",
)
def list_scene_arcs(scene: str) -> str:
    """Return a formatted list of all arcs registered for a scene.

    Args:
        scene: The scene name to query.

    Returns:
        Newline-separated arc list.
    """
    engine = get_story_arc_engine()
    arcs = engine.get_scene_arcs(scene)
    if not arcs:
        return f"No arcs registered for scene '{scene}'."
    return "\n".join(f"  {a.id}: {a.name} [{a.status}]" for a in arcs)
