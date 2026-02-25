"""
Casino Skills — MCP skill functions for The Midnight Casino.

Exposes poker actions, drink ordering, bluff reading, and game state
as @skill-decorated functions callable by LMS agents via tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_casino_scene():
    """Look up the running Casino scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("casino")


# ── Game State ─────────────────────────────────────────────────

@skill(
    pack="casino",
    tags=["game", "casino", "poker"],
    category=SkillCategory.GAME,
    description="Get the current state of the poker table.",
)
def casino_table_status() -> str:
    """Return game phase, pot, player chips, and round number."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    gs = getattr(scene, "game_state", {})
    lines = [
        f"Round: {gs.get('round', 0)} | Phase: {gs.get('phase', 'idle')}",
        f"Pot: ${gs.get('pot', 0)} | Your chips: ${gs.get('player_chips', 0)}",
    ]
    if gs.get("community_cards"):
        lines.append(f"Community: {' '.join(gs['community_cards'])}")
    if gs.get("player_hand"):
        lines.append(f"Your hand: {' '.join(gs['player_hand'])}")
    return "\n".join(lines)


@skill(
    pack="casino",
    tags=["game", "casino", "poker"],
    category=SkillCategory.GAME,
    description="Place a bet at the poker table.",
    cooldown=5,
)
def casino_bet(amount: int = 10) -> str:
    """Place a bet. Amount is in chips."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    gs = getattr(scene, "game_state", {})
    chips = gs.get("player_chips", 0)
    if amount > chips:
        return f"Not enough chips! You have ${chips}."
    if amount <= 0:
        return "Bet must be positive."
    gs["pot"] = gs.get("pot", 0) + amount
    gs["player_chips"] = chips - amount
    return f"Bet ${amount}. Pot is now ${gs['pot']}. You have ${gs['player_chips']} chips."


@skill(
    pack="casino",
    tags=["game", "casino", "poker"],
    category=SkillCategory.GAME,
    description="Fold your current hand.",
)
def casino_fold() -> str:
    """Fold the current hand and forfeit the pot."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    gs = getattr(scene, "game_state", {})
    lost = gs.get("pot", 0)
    gs["phase"] = "idle"
    gs["pot"] = 0
    return f"You fold. Lost pot of ${lost}."


@skill(
    pack="casino",
    tags=["game", "casino", "social"],
    category=SkillCategory.SOCIAL,
    description="Order a cocktail from the casino bar.",
)
def casino_order_drink(drink_name: str = "whiskey") -> str:
    """Order a drink. Drinks can affect your stats."""
    from content.scenes.casino.casino_mcp import COCKTAILS
    drink = COCKTAILS.get(drink_name.lower())
    if not drink:
        available = ", ".join(COCKTAILS.keys())
        return f"Unknown drink. Available: {available}"
    effects = drink.get("effects", {})
    effect_str = ", ".join(f"{k}: {v:+d}" for k, v in effects.items()) if effects else "none"
    return f"Ordered {drink['name']}. Effects: {effect_str}. {drink.get('flavor', '')}"


@skill(
    pack="casino",
    tags=["game", "casino", "social"],
    category=SkillCategory.SOCIAL,
    description="Try to read an opponent's bluff tells.",
    cooldown=15,
)
def casino_read_opponent(target: str = "dealer_jack") -> str:
    """Attempt to read a character's poker tells."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    from content.scenes.casino.casino_mcp import BLUFF_TELLS
    import random
    tell = random.choice(BLUFF_TELLS) if BLUFF_TELLS else "No tells detected."
    return f"Reading {target}... {tell}"


@skill(
    pack="casino",
    tags=["game", "casino"],
    category=SkillCategory.GAME,
    description="Go all-in with all remaining chips.",
    cooldown=30,
)
def casino_all_in() -> str:
    """Push all chips into the pot."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    gs = getattr(scene, "game_state", {})
    chips = gs.get("player_chips", 0)
    if chips <= 0:
        return "You're broke! No chips to go all-in with."
    gs["pot"] = gs.get("pot", 0) + chips
    gs["player_chips"] = 0
    return f"ALL IN! ${chips} pushed into the pot. Pot is now ${gs['pot']}."
