"""Story arc skills — LLM-callable tools for narrative arc management."""
from __future__ import annotations

import logging

from engine.skills.skill import skill
from engine.story.story_arc import ArcStatus, get_story_arc_engine  # noqa: F401

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
    nexus_first=True,
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


# ──── Faction skills ──────────────────────────────────────────────────────────


@skill(
    pack="story",
    description="Get faction standings for current scene",
    category="NARRATIVE",
)
def get_faction_politics(scene: str) -> str:
    """Return a formatted summary of all faction standings in a scene.

    Args:
        scene: Scene name to query.

    Returns:
        Human-readable faction politics summary.
    """
    from engine.story.faction_politics import get_faction_manager

    politics = get_faction_manager().get_scene_politics(scene)
    factions = politics.get("factions", [])
    if not factions:
        return f"No factions registered for scene '{scene}'."
    lines = [f"Scene: {scene} — Faction Politics"]
    for f in factions:
        lines.append(
            f"  [{f['standing_label'].upper()}] {f['name']} "
            f"(standing: {f['player_standing']:+d})"
        )
    return "\n".join(lines)


@skill(
    pack="story",
    description="Modify player standing with a faction",
    category="NARRATIVE",
    cost=1.0,
)
def change_faction_standing(faction_id: str, delta: int, reason: str = "") -> str:
    """Modify the player's standing with a faction and cascade to allies/enemies.

    Args:
        faction_id: The faction whose standing to change.
        delta: Signed integer change (positive = better, negative = worse).
        reason: Optional human-readable reason for the change.

    Returns:
        Summary of all standing changes applied.
    """
    from engine.story.faction_politics import get_faction_manager

    changes = get_faction_manager().modify_standing(faction_id, delta)
    if not changes:
        return f"Faction '{faction_id}' not found."
    lines = [f"Standing changes{' (' + reason + ')' if reason else ''}:"]
    for fid, new_val in changes.items():
        lines.append(f"  {fid}: {new_val:+d}")
    return "\n".join(lines)


@skill(
    pack="story",
    description="Check player's standing with a specific faction",
    category="NARRATIVE",
)
def check_faction_standing(faction_id: str) -> str:
    """Return the player's current standing with a faction.

    Args:
        faction_id: The faction to check.

    Returns:
        Standing description string.
    """
    from engine.story.faction_politics import _standing_label, get_faction_manager

    faction = get_faction_manager().get(faction_id)
    if not faction:
        return f"Faction '{faction_id}' not found."
    label = _standing_label(faction.player_standing)
    return (
        f"{faction.name}: standing {faction.player_standing:+d} ({label})"
    )


# ──── Daily challenge skills ──────────────────────────────────────────────────


@skill(
    pack="story",
    description="Get today's challenge for a scene",
    category="NARRATIVE",
)
def get_daily_challenge(scene: str) -> str:
    """Return today's challenge for a scene.

    Args:
        scene: Scene name.

    Returns:
        Formatted challenge description.
    """
    from engine.nexus.daily_challenge import get_daily_challenge_manager

    challenge = get_daily_challenge_manager().get_challenge(scene)
    if not challenge:
        return f"No challenge available for scene '{scene}'."
    difficulty_bar = "★" * challenge.get("difficulty", 1) + "☆" * (5 - challenge.get("difficulty", 1))
    return (
        f"[Daily Challenge — {scene.title()}]\n"
        f"Title: {challenge['title']}\n"
        f"Description: {challenge['description']}\n"
        f"Win condition: {challenge['win_condition']}\n"
        f"Reward: {challenge['reward']}\n"
        f"Difficulty: {difficulty_bar}"
    )


@skill(
    pack="story",
    description="Complete today's challenge objective",
    category="NARRATIVE",
    cost=2.0,
)
def complete_daily_challenge(scene: str, outcome: str) -> str:
    """Mark today's challenge as attempted and record the outcome.

    Args:
        scene: Scene name.
        outcome: Description of how the challenge was resolved.

    Returns:
        Result string logged to Nexus.
    """
    from engine.nexus.daily_challenge import get_daily_challenge_manager

    challenge = get_daily_challenge_manager().get_challenge(scene)
    if not challenge:
        return f"No active challenge for scene '{scene}'."

    result_str = (
        f"Challenge '{challenge['title']}' in {scene} resolved: {outcome}"
    )
    logger.info(result_str)

    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            title=f"Challenge Complete: {challenge['title']}",
            content=result_str,
            content_type="history",
            category="challenges",
            tags=["challenge", "completed", scene],
        )
    except Exception as exc:
        logger.debug("Could not log challenge completion to Nexus: %s", exc)

    return result_str
