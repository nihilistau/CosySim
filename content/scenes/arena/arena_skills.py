"""Arena Skills — MCP skill functions for THE COLOSSEUM scene.

Exposes match management, betting, and fighter listing as
``@skill``-decorated functions callable by LMStudio agents via tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_arena_scene():
    """Look up the running ArenaScene instance.

    Returns:
        ArenaScene if active, or ``None``.
    """
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("arena")


# ── Match Management ────────────────────────────────────────────────


@skill(
    pack="arena",
    tags=["arena", "match", "game"],
    category=SkillCategory.GAME,
    description="Create a new arena match between two fighters",
)
def create_arena_match(fighter_a_id: str, fighter_b_id: str) -> str:
    """Create a new arena match and return its match ID.

    Args:
        fighter_a_id: Identifier for fighter A (e.g. ``"shadow"``).
        fighter_b_id: Identifier for fighter B (e.g. ``"blaze"``).

    Returns:
        Confirmation string with match ID or error message.
    """
    scene = _get_arena_scene()
    if not scene:
        return "Arena not active."
    try:
        match = scene._engine.create_match(fighter_a_id, fighter_b_id)
        return (
            f"Match created! ID: {match.id}\n"
            f"{match.fighter_a.name} vs {match.fighter_b.name}\n"
            f"Status: {match.status.value}"
        )
    except Exception as exc:
        logger.warning("create_arena_match skill error: %s", exc)
        return f"Error creating match: {exc}"


@skill(
    pack="arena",
    tags=["arena", "match", "game"],
    category=SkillCategory.GAME,
    description="Play the next round of an arena match",
)
def play_arena_round(match_id: str) -> str:
    """Play one round of an in-progress arena match.

    Args:
        match_id: UUID of the match to advance.

    Returns:
        Round summary with cards played, damage dealt, and reasoning.
    """
    scene = _get_arena_scene()
    if not scene:
        return "Arena not active."
    try:
        outcome = scene._engine.play_round(match_id)
        match = scene._engine._matches[match_id]
        fa_name = match.fighter_a.name
        fb_name = match.fighter_b.name
        lines = [
            f"Round {outcome.round_num} complete!",
            (
                f"  {fa_name} played: {outcome.fighter_a_card.name}"
                f" [{outcome.fighter_a_card.card_type.value}]"
                f" -- '{outcome.fighter_a_reasoning}'"
            ),
            (
                f"  {fb_name} played: {outcome.fighter_b_card.name}"
                f" [{outcome.fighter_b_card.card_type.value}]"
                f" -- '{outcome.fighter_b_reasoning}'"
            ),
            (
                f"  Winner: {outcome.winner} | "
                f"Damage A: {outcome.damage_a} | Damage B: {outcome.damage_b}"
            ),
            f"  HP -> {fa_name}: {match.fighter_a.hp} | {fb_name}: {match.fighter_b.hp}",
            f"  Commentary: {outcome.commentary}",
        ]
        if outcome.special_triggered:
            lines.append(f"  ⚡ Special: {outcome.special_triggered}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("play_arena_round skill error: %s", exc)
        return f"Error playing round: {exc}"


# ── Betting ──────────────────────────────────────────────────────────


@skill(
    pack="arena",
    tags=["arena", "bet", "economy"],
    category=SkillCategory.GAME,
    description="Place a bet on an arena match",
    cooldown=5,
)
def place_arena_bet(
    match_id: str,
    target: str,
    amount: int,
    bet_type: str = "match_winner",
) -> str:
    """Place a bet on a match or round outcome.

    Args:
        match_id: UUID of the active match.
        target: ``"fighter_a"`` or ``"fighter_b"``.
        amount: Credits to wager (must be positive).
        bet_type: ``"match_winner"`` or ``"round_winner"``.

    Returns:
        Bet confirmation or error message.
    """
    scene = _get_arena_scene()
    if not scene:
        return "Arena not active."
    if amount <= 0:
        return "Bet amount must be positive."
    try:
        bet = scene._engine.place_bet(match_id, bet_type, target, amount)
        balance_str = ""
        try:
            from engine.economy.economy import get_economy_manager
            balance = get_economy_manager().get_balance("player")
            balance_str = f" | Remaining balance: ₵{balance}"
        except Exception:
            pass
        return (
            f"Bet placed! ID: {bet.id}\n"
            f"  Type: {bet.bet_type} | Target: {bet.target} | Amount: ₵{bet.amount}"
            f"{balance_str}"
        )
    except Exception as exc:
        logger.warning("place_arena_bet skill error: %s", exc)
        return f"Error placing bet: {exc}"


# ── Leaderboard ──────────────────────────────────────────────────────


@skill(
    pack="arena",
    tags=["arena", "leaderboard", "stats"],
    category=SkillCategory.GAME,
    description="Get the current arena leaderboard",
)
def get_arena_leaderboard() -> str:
    """Return the career win/loss leaderboard for all known fighters.

    Returns:
        Formatted leaderboard string sorted by wins.
    """
    scene = _get_arena_scene()
    if not scene:
        return "Arena not active."
    try:
        profiles = list(scene._engine._fighter_profiles.values())
        if not profiles:
            return "No fighters registered yet."
        board = sorted(profiles, key=lambda f: f.wins, reverse=True)
        lines = ["=== COLOSSEUM LEADERBOARD ==="]
        for i, f in enumerate(board, 1):
            lines.append(
                f"  {i}. {f.name} — W:{f.wins} L:{f.losses} D:{f.draws}"
            )
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("get_arena_leaderboard skill error: %s", exc)
        return f"Error fetching leaderboard: {exc}"


# ── Fighter Discovery ────────────────────────────────────────────────


@skill(
    pack="arena",
    tags=["arena", "fighters", "nexus"],
    category=SkillCategory.GAME,
    description="Get available fighters from Nexus",
)
def list_arena_fighters() -> str:
    """List all fighter profiles known to the arena engine.

    Profiles are loaded from Nexus on first use and cached in-process.

    Returns:
        Formatted list of fighters with persona summaries.
    """
    scene = _get_arena_scene()
    if not scene:
        return "Arena not active."
    try:
        profiles = list(scene._engine._fighter_profiles.values())
        if not profiles:
            return "No fighters loaded yet. Create a match first to seed profiles."
        lines = ["=== AVAILABLE FIGHTERS ==="]
        for f in profiles:
            lines.append(f"  • {f.name} (id: {f.id}) — {f.persona[:80]}...")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("list_arena_fighters skill error: %s", exc)
        return f"Error listing fighters: {exc}"
