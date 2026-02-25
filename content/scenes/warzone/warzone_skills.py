"""
Warzone Skills — MCP skill functions for the Strategic Warzone scene.

Exposes tactical actions, resource management, building construction,
upgrades, special operations, and battlefield intelligence as
@skill-decorated functions callable by LMS agents via tool use.

Skills interact with the actual GameState engine — not stubs.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_warzone_scene():
    """Look up the running Warzone scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("warzone")


def _get_game() -> Optional[Any]:
    """Get the first active game from the warzone scene."""
    scene = _get_warzone_scene()
    if not scene:
        return None
    games = getattr(scene, "_games", {})
    if not games:
        return None
    return next(iter(games.values()))


# ── Battlefield Intelligence ───────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "strategy", "status"],
    category=SkillCategory.GAME,
    description="Get full battlefield status: turn, weather, resources, buildings, HP.",
)
def warzone_status() -> str:
    """Return detailed battlefield state."""
    game = _get_game()
    if not game:
        return "No active warzone game."
    d = game.to_dict()
    p = d["player"]
    a = d["ai"]
    lines = [
        f"⚔️ WARZONE — Turn {d['turn']} | Phase: {d['phase']}",
        f"Weather: {d.get('weather_label', d['weather'])}",
        f"Escalation: ×{d['escalation']:.1f}",
        "",
        f"🔵 You ({p['name']}): HP {p['base_hp']}/{p['max_hp']}",
        f"   💰 {p.get('credits', '?')} | ⚡ {p.get('power', '?')} | 🔍 {p.get('intel', '?')}",
        f"   Weapon: {p['weapon_name']} (L{p['weapon_level']})",
        f"   Defense: {p['defense_name']} (L{p['defense_level']})",
        f"   Buildings: {len(p['buildings'])}/{4 - p.get('building_slots', 0)} — " +
        (", ".join(b['name'] for b in p['buildings']) if p['buildings'] else "none"),
        "",
        f"🔴 Enemy ({a['name']}): HP {a['base_hp']}/{a['max_hp']}",
        f"   Weapon: {a['weapon_name']} | Defense: {a['defense_name']}",
        f"   Buildings: {len(a['buildings'])}",
    ]
    # Show spy intel if available
    if p.get("spy_turns", 0) > 0:
        lines.append(f"   🔍 SPY ACTIVE ({p['spy_turns']} turns): "
                     f"💰{a.get('credits', '?')} ⚡{a.get('power', '?')} 🔍{a.get('intel', '?')}")
    # Recent events
    log = d.get("log", [])
    if log:
        lines.append("")
        lines.append("Recent:")
        for entry in log[-3:]:
            lines.append(f"  {entry['msg']}")
    if d.get("winner"):
        lines.append(f"\n🏆 Winner: {d['winner']}!")
    return "\n".join(lines)


# ── Attack ─────────────────────────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "combat", "attack"],
    category=SkillCategory.GAME,
    description="Launch an attack. Target: 'base' (damage HP) or 'building' (destroy structures).",
    cooldown=5,
)
def warzone_attack(target: str = "base") -> str:
    """Attack the enemy. Resolves weapon vs defense with dice rolls."""
    game = _get_game()
    if not game:
        return "No active warzone game."
    if game.phase == "game_over":
        return f"Game over! Winner: {game.winner}"
    if target not in ("base", "building"):
        return "Target must be 'base' or 'building'."
    result = game.process_action("player", "attack", target=target)
    if result.get("type") == "error":
        return f"⚠ {result['msg']}"
    dmg = result.get("total_damage", 0)
    hits = result.get("hits", [])
    crits = sum(1 for h in hits if h.get("crit"))
    intercepted = sum(1 for h in hits if h.get("intercepted"))
    lines = [f"🎯 Attack on {target} with {result.get('weapon', '?')}!"]
    lines.append(f"   Damage dealt: {dmg}")
    if crits:
        lines.append(f"   💥 Critical hits: {crits}")
    if intercepted:
        lines.append(f"   🛡️ Intercepted: {intercepted}")
    lines.append(f"   Enemy HP: {game.ai.base_hp}/{game.ai.max_hp}")
    if game.phase == "game_over":
        lines.append(f"🏆 VICTORY! {game.winner} wins!")
    return "\n".join(lines)


# ── Build ──────────────────────────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "build", "economy"],
    category=SkillCategory.GAME,
    description="Build a structure: factory (income), power_plant (power), radar (intel), fortress (defense HP).",
    cooldown=5,
)
def warzone_build(building_type: str = "factory") -> str:
    """Construct a building. Costs credits."""
    game = _get_game()
    if not game:
        return "No active warzone game."
    result = game.process_action("player", f"build_{building_type}")
    if result.get("type") == "error":
        return f"⚠ {result['msg']}"
    return (
        f"🏗️ Built {building_type}!\n"
        f"Credits: {game.player.credits} | Buildings: {len(game.player.buildings)}/4"
    )


# ── Upgrade ────────────────────────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "upgrade"],
    category=SkillCategory.GAME,
    description="Upgrade weapon or defense. Costs credits + power/intel.",
    cooldown=8,
)
def warzone_upgrade(what: str = "weapon") -> str:
    """Upgrade 'weapon' or 'defense'. Higher tiers cost more but deal/block more."""
    game = _get_game()
    if not game:
        return "No active warzone game."
    if what not in ("weapon", "defense"):
        return "Upgrade 'weapon' or 'defense'."
    result = game.process_action("player", f"upgrade_{what}")
    if result.get("type") == "error":
        return f"⚠ {result['msg']}"
    level = result.get("level", "?")
    p = game.player
    return (
        f"⬆️ {what.title()} upgraded to level {level}!\n"
        f"Credits: {p.credits} | Power: {p.power} | Intel: {p.intel}"
    )


# ── Special Operations ────────────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "special", "tactics"],
    category=SkillCategory.GAME,
    description="Execute special op: spy_satellite (reveal enemy), emp_burst (disable defense), sabotage (destroy building), shield_overcharge (double defense), taunt (+damage).",
    cooldown=15,
)
def warzone_special_op(operation: str = "spy_satellite") -> str:
    """Execute a special operation using intel/power resources."""
    game = _get_game()
    if not game:
        return "No active warzone game."
    result = game.process_action("player", f"special_{operation}")
    if result.get("type") == "error":
        return f"⚠ {result['msg']}"
    p = game.player
    return (
        f"🔮 Special Op: {operation.replace('_', ' ').title()}\n"
        f"Resources: 💰{p.credits} ⚡{p.power} 🔍{p.intel}"
    )


# ── Recon (alias for spy satellite) ───────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "intel", "recon"],
    category=SkillCategory.GAME,
    description="Spend intel to reveal enemy resources and positions for 3 turns.",
    cooldown=15,
)
def warzone_recon() -> str:
    """Deploy recon — alias for spy_satellite special op."""
    return warzone_special_op(operation="spy_satellite")


# ── End Turn ───────────────────────────────────────────────────

@skill(
    pack="warzone",
    tags=["game", "warzone", "turn"],
    category=SkillCategory.GAME,
    description="End your turn. AI takes its turn, weather changes, income collected.",
    cooldown=3,
)
def warzone_end_turn() -> str:
    """End the player turn and let the AI act."""
    game = _get_game()
    if not game:
        return "No active warzone game."
    if game.phase == "game_over":
        return f"Game over! Winner: {game.winner}"

    # Collect income
    inc = game.player.collect_income(game.escalation)

    # AI turn
    scene = _get_warzone_scene()
    if scene and hasattr(scene, "_ai_turn"):
        scene._ai_turn(game)

    # Advance turn
    game.turn += 1
    game.roll_weather()
    game.check_events()

    # Tick status effects
    if game.player.spy_turns > 0:
        game.player.spy_turns -= 1
    if game.player.emp_turns > 0:
        game.player.emp_turns -= 1
    if game.ai.spy_turns > 0:
        game.ai.spy_turns -= 1
    if game.ai.emp_turns > 0:
        game.ai.emp_turns -= 1

    lines = [
        f"⏭️ Turn {game.turn} begins!",
        f"Income: +{inc['credits']}💰 +{inc['power']}⚡ +{inc['intel']}🔍",
        f"Weather: {game.weather}",
        f"Your HP: {game.player.base_hp} | Enemy HP: {game.ai.base_hp}",
    ]
    return "\n".join(lines)
