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


# ── Tactical Intelligence (v0.50b) ────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "strategy", "recon"],
    category=SkillCategory.GAME,
    description="Scan the area around the player for cover, enemies, loot, and hazards.",
)
def neoncity_scan(radius: int = 2) -> str:
    """Scan surrounding cells for tactical intelligence."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    st = scene.state
    p = st.get_player("player")
    if not p or not p.alive:
        return "Player is not alive."

    radius = max(1, min(3, radius))
    enemies_nearby = []
    cover_cells = []
    loot_cells = []

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            cx, cy = p.x + dx, p.y + dy
            if cx < 0 or cy < 0 or cx >= st.grid_size or cy >= st.grid_size:
                continue
            cell = st.grid[cy][cx] if hasattr(st, 'grid') and cy < len(st.grid) and cx < len(st.grid[0]) else None
            if cell:
                if cell.get("type") == "building":
                    cover_cells.append(f"({cx},{cy}) building")
                elif cell.get("type") == "alley":
                    cover_cells.append(f"({cx},{cy}) alley")
                if cell.get("loot"):
                    loot_cells.append(f"({cx},{cy})")

            # Check for enemies
            for other in st.players:
                if other.id != "player" and other.alive and other.x == cx and other.y == cy:
                    dist = abs(dx) + abs(dy)
                    enemies_nearby.append(f"{other.name} at ({cx},{cy}) dist:{dist} HP:{other.hp}")

    lines = [f"🔍 SCAN — Radius {radius} from ({p.x},{p.y}):"]
    if enemies_nearby:
        lines.append(f"  ⚠️ Enemies: {', '.join(enemies_nearby)}")
    else:
        lines.append("  ✅ No enemies detected.")
    if cover_cells:
        lines.append(f"  🏗️ Cover: {', '.join(cover_cells[:5])}")
    if loot_cells:
        lines.append(f"  💎 Loot at: {', '.join(loot_cells[:5])}")

    # Storm check
    if st.is_in_storm(p.x, p.y):
        lines.append("  ⚡ WARNING: You are in the Glitch Storm!")
    return "\n".join(lines)


@skill(
    pack="neoncity",
    tags=["game", "strategy", "hacking"],
    category=SkillCategory.GAME,
    description="Check the current alarm level and security response status.",
)
def neoncity_alarm_status() -> str:
    """Show the alarm level and its consequences."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    st = scene.state

    # Track alarm as state attribute
    alarm = getattr(st, 'alarm_level', 0)
    lines = [f"🚨 ALARM LEVEL: {alarm}/5"]

    thresholds = [
        (0, "All clear — no security presence."),
        (1, "Security on standby — occasional patrols."),
        (2, "Heightened alert — security drones active."),
        (3, "Active pursuit — aggressive search patterns."),
        (4, "Lockdown — all exits monitored, reinforcements called."),
        (5, "MAXIMUM ALERT — lethal force authorized!"),
    ]
    for level, desc in thresholds:
        marker = "→" if level == alarm else " "
        lines.append(f"  {marker} [{level}] {desc}")

    # Failed hack tracking
    failed = getattr(st, 'failed_hacks', 0)
    if failed > 0:
        lines.append(f"\n  Failed hacks: {failed} (each raises alarm by 1)")

    return "\n".join(lines)


@skill(
    pack="neoncity",
    tags=["game", "strategy", "economy"],
    category=SkillCategory.GAME,
    description="Use credits to buy items: medkit (heal 30HP), EMP grenade (stun), hack_boost (+5 hacking).",
    cooldown=5,
)
def neoncity_buy(item: str = "medkit") -> str:
    """Purchase tactical equipment with credits."""
    scene = _get_neoncity_scene()
    if not scene or not scene.state:
        return "No active NeonCity game."
    p = scene.state.get_player("player")
    if not p or not p.alive:
        return "Player is not alive."

    shop = {
        "medkit": {"cost": 30, "desc": "Heal 30 HP", "effect": "heal"},
        "emp_grenade": {"cost": 50, "desc": "Stun enemies in area", "effect": "stun"},
        "hack_boost": {"cost": 40, "desc": "+5 hacking skill", "effect": "hack"},
        "armor_patch": {"cost": 35, "desc": "+3 defense", "effect": "defense"},
    }

    if item not in shop:
        items = ", ".join(f"{k} ({v['cost']}💰)" for k, v in shop.items())
        return f"Unknown item. Available: {items}"

    info = shop[item]
    if p.credits < info["cost"]:
        return f"Need {info['cost']} credits, have {p.credits}."

    p.credits -= info["cost"]
    if info["effect"] == "heal":
        p.hp = min(p.max_hp, p.hp + 30)
    elif info["effect"] == "hack":
        p.hacking += 5
    elif info["effect"] == "defense":
        p.defense += 3

    return f"🛒 Purchased {item}: {info['desc']}. Credits: {p.credits}"
