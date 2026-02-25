"""
Warzone Skills — MCP skill functions for the Strategic Warzone scene.

Exposes tactical actions, resource management, and battlefield intelligence
as @skill-decorated functions callable by LMS agents via tool use.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_warzone_scene():
    """Look up the running Warzone scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("warzone")


# ── Battlefield Intelligence ───────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "strategy"],
    category=SkillCategory.GAME,
    description="Get the current battlefield status.",
)
def warzone_status() -> str:
    """Return turn, weather, resources, and unit positions."""
    scene = _get_warzone_scene()
    if not scene:
        return "Warzone not active."
    games = getattr(scene, "_games", {})
    if not games:
        return "No active games."
    # Return first game's status
    gid, game = next(iter(games.items()))
    d = game.to_dict()
    lines = [
        f"Turn: {d['turn']} | Weather: {d['weather']}",
        f"Player: credits={d['player']['credits']}, power={d['player']['power']}, intel={d['player']['intel']}",
        f"AI: credits={d['ai']['credits']}, power={d['ai']['power']}",
    ]
    if d.get("events"):
        lines.append(f"Recent event: {d['events'][-1]}")
    return "\n".join(lines)


@skill(
    pack="warzone",
    tags=["game", "warzone", "strategy"],
    category=SkillCategory.GAME,
    description="Deploy units or defenses.",
    cooldown=5,
)
def warzone_deploy(unit_type: str = "infantry") -> str:
    """Deploy a unit type: infantry, armor, artillery, air_support."""
    valid = ["infantry", "armor", "artillery", "air_support"]
    if unit_type not in valid:
        return f"Unknown unit type. Available: {', '.join(valid)}"
    return f"Deploying {unit_type}. Awaiting battlefield resolution."


@skill(
    pack="warzone",
    tags=["game", "warzone", "strategy"],
    category=SkillCategory.GAME,
    description="Launch an attack against the enemy position.",
    cooldown=10,
)
def warzone_attack(target: str = "base") -> str:
    """Attack the enemy. Target: base, flanks, supply_line."""
    return f"Attack launched against {target}. Resolving..."


@skill(
    pack="warzone",
    tags=["game", "warzone", "strategy"],
    category=SkillCategory.GAME,
    description="Gather intelligence on the enemy.",
    cooldown=15,
)
def warzone_recon() -> str:
    """Spend intel to reveal enemy positions and resources."""
    scene = _get_warzone_scene()
    if not scene:
        return "Warzone not active."
    return "Recon mission deployed. Intelligence gathering in progress."


@skill(
    pack="warzone",
    tags=["game", "warzone", "strategy"],
    category=SkillCategory.GAME,
    description="Execute a special operation using intel resources.",
    cooldown=30,
)
def warzone_special_op() -> str:
    """Execute a special operation: sabotage, airstrike, or counter-intel."""
    import random
    ops = ["sabotage", "airstrike", "counter_intelligence"]
    op = random.choice(ops)
    return f"Special operation '{op}' executing. High risk, high reward."
