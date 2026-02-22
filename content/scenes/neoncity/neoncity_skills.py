"""
NeonCity Skills — MCP skill functions for the Cyberpunk Strategy Board Game.

Exposes movement, combat, hacking, storm status, and event triggers as
@skill-decorated functions callable by LMS agents via tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_neoncity_scene():
    """Look up the running NeonCity scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("neoncity")


# ── Game State ────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "strategy"],
    category=SkillCategory.GAME,
    description="Get the current NeonCity game state: round, storm radius, alive players.",
)
def neoncity_status() -> str:
    """Return a summary of the NeonCity board state."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    st = scene.state
    alive = [p for p in st.players if p.alive]
    return (
        f"Round: {st.turn_number} | Storm radius: {st.storm_radius}\n"
        f"Players alive: {len(alive)}/{len(st.players)}\n"
        f"Firewall: {st.target_firewall} layers remaining\n"
        f"Target: ({st.target_x}, {st.target_y})"
    )


@skill(
    pack="neoncity",
    tags=["game", "strategy"],
    category=SkillCategory.GAME,
    description="Get a specific player's stats (HP, position, weapons, implants).",
)
def neoncity_player_info(player_id: str = "player") -> str:
    """Return detailed info about a player."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    p = scene.state.get_player(player_id)
    if not p:
        return f"Player '{player_id}' not found."
    weapons = ", ".join(w["name"] for w in p.weapons) if p.weapons else "None"
    implants = ", ".join(i["name"] for i in p.implants) if p.implants else "None"
    return (
        f"{p.name} | HP: {p.hp}/{p.max_hp} | Pos: ({p.x}, {p.y})\n"
        f"Move: {p.movement_points}/{p.max_movement} | Hack: {p.hacking} | Defense: {p.defense}\n"
        f"Weapons: {weapons}\n"
        f"Implants: {implants}\n"
        f"Alive: {p.alive} | Credits: {p.credits}"
    )


# ── Movement ──────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "strategy", "movement"],
    category=SkillCategory.GAME,
    description="Move the human player to a new position on the NeonCity grid.",
)
def neoncity_move(x: int, y: int) -> str:
    """Move the player to (x, y). Returns result including any loot found."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    result = scene.state.move_player("player", x, y)
    if "error" in result:
        return f"Move failed: {result['error']}"
    msg = f"Moved to ({result.get('x', x)}, {result.get('y', y)}). Moves remaining: {result.get('moves_left', '?')}"
    if result.get("loot"):
        msg += f"\nLooted: {json.dumps(result['loot'])}"
    return msg


# ── Combat ────────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "strategy", "combat"],
    category=SkillCategory.GAME,
    description="Attack another player in NeonCity with an equipped weapon.",
)
def neoncity_attack(target_id: str, weapon_idx: int = 0) -> str:
    """Attack a target player. Returns hit/miss, damage dealt."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    result = scene.state.attack_player("player", target_id, weapon_idx)
    if "error" in result:
        return f"Attack failed: {result['error']}"
    if result.get("hit"):
        msg = f"HIT! Dealt {result['damage']} damage to {target_id}."
        if result.get("killed"):
            msg += " TARGET ELIMINATED! 💀"
        return msg
    return f"MISS! Attack on {target_id} failed."


# ── Hacking ───────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "strategy", "hacking"],
    category=SkillCategory.GAME,
    description="Attempt to hack the AI target's firewall (must be at target location).",
)
def neoncity_hack() -> str:
    """Hack attempt at the AI target. Must be standing on the target cell."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    result = scene.state.hack_target("player")
    if "error" in result:
        return f"Hack failed: {result['error']}"
    if result.get("breached"):
        return "🔓 FIREWALL BREACHED! You've captured the AI program. VICTORY!"
    outcome = "Layer cracked! ✅" if result.get("success") else "Blocked! ❌"
    return f"Hack: {outcome} Firewalls remaining: {result.get('firewall_remaining', '?')}"


# ── Events & Storm ────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "strategy", "environment"],
    category=SkillCategory.ENVIRONMENT,
    description="Get the current Glitch Storm status (radius, cells affected).",
)
def neoncity_storm_status() -> str:
    """Return storm boundary and danger zone info."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    st = scene.state
    in_storm = []
    for p in st.players:
        if p.alive and st.is_in_storm(p.x, p.y):
            in_storm.append(p.name)
    msg = f"Storm radius: {st.storm_radius} (shrinks each round)\n"
    msg += f"Safe zone: ({st.storm_radius}, {st.storm_radius}) to ({12 - st.storm_radius - 1}, {12 - st.storm_radius - 1})\n"
    if in_storm:
        msg += f"⚠️ Players in storm: {', '.join(in_storm)}"
    else:
        msg += "All players are in the safe zone."
    return msg


@skill(
    pack="neoncity",
    tags=["game", "strategy"],
    category=SkillCategory.GAME,
    description="Trigger a random NeonCity event (blackout, drone strike, etc).",
)
def neoncity_trigger_event() -> str:
    """Trigger a random global event. Returns the event description and effects."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    result = scene.state.trigger_event()
    if not result:
        return "No event triggered."
    ev = result.get("event", {})
    return f"⚡ EVENT: {ev.get('label', '?')} — {ev.get('description', '')}"


@skill(
    pack="neoncity",
    tags=["game", "strategy"],
    category=SkillCategory.GAME,
    description="End the current player's turn and process AI turns.",
)
def neoncity_end_turn() -> str:
    """End turn, process AI moves, advance storm."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    advance = scene.state.advance_turn()
    ai_actions = []
    while True:
        cp = scene.state.get_current_player()
        if not cp or not cp.is_ai:
            break
        actions = scene.state.ai_turn(cp.id)
        ai_actions.append(f"{cp.name}: {', '.join(str(a) for a in actions)}")
        if scene.state.ended:
            break
        scene.state.advance_turn()
    msg = f"Turn ended. Round {scene.state.turn_number}.\n"
    if ai_actions:
        msg += "AI actions:\n  " + "\n  ".join(ai_actions)
    return msg
