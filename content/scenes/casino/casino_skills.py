"""
Casino Skills — CLUB NOIR v0.68 Dark Renaissance.

Five MCP skill functions for the underground blackjack/poker den.
Callable by LMS agents via tool-use.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_casino_scene():
    """Look up the running CasinoScene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("casino")


# ── Skills ─────────────────────────────────────────────────────────────

@skill(
    pack="casino",
    description="Get current casino state and available tables",
    category=SkillCategory.GAME,
    tags=["casino", "game", "state"],
)
def casino_state() -> str:
    """Return the current CLUB NOIR state: balance, active game, tables."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    bal = scene._economy_balance()
    bj  = scene._bj_state
    lines = [
        f"CLUB NOIR | Balance: ${bal}",
        f"Active game: {bj['game'] if bj['active'] else 'none'} | "
        f"Phase: {bj['phase']}",
        f"Tables: Blackjack (min $50), Poker (min $100)",
    ]
    if bj["active"]:
        pval = scene._bj_hand_value(bj["player_hand"]) if bj["player_hand"] else 0
        lines.append(
            f"Your hand: {' '.join(bj['player_hand']) or '—'} (value {pval}) | "
            f"Bet: ${bj['bet']}"
        )
    return "\n".join(lines)


@skill(
    pack="casino",
    description="Join a gambling table with a buy-in amount",
    category=SkillCategory.GAME,
    tags=["casino", "game", "join"],
    cooldown=5,
)
def join_table(game: str = "blackjack", buy_in: int = 100) -> str:
    """Sit down at a game table with the specified buy-in."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    bj = scene._bj_state
    if bj["active"]:
        return f"Already at the {bj['game']} table. Finish or cash out first."
    ok = scene._economy_spend(buy_in, reason=f"casino_buy_in:{game}")
    if not ok:
        return f"Insufficient credits for ${buy_in} buy-in."
    bj.update({
        "active": True, "game": game, "buy_in": buy_in,
        "phase": "betting", "player_hand": [], "dealer_hand": [],
        "bet": 0, "result": None, "winnings": 0,
    })
    return (
        f"Joined {game} table with ${buy_in}. "
        f"Place a bet to start. Balance: ${scene._economy_balance()}"
    )


@skill(
    pack="casino",
    description="Place a bet on the current game",
    category=SkillCategory.GAME,
    tags=["casino", "game", "bet"],
    cooldown=3,
)
def place_bet(amount: int, target: str = "player_win") -> str:
    """Wager chips on the current hand."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    bj = scene._bj_state
    if not bj["active"]:
        return "Join a table first."
    if bj["phase"] != "betting":
        return f"Cannot bet in phase '{bj['phase']}'."
    if amount <= 0 or amount > bj["buy_in"]:
        return f"Bet must be $1–${bj['buy_in']}."
    bj["bet"] = amount
    bj["target"] = target
    return f"Bet ${amount} on {target}. Say 'deal' to receive cards."


@skill(
    pack="casino",
    description="Make a game decision: hit, stand, double, or fold",
    category=SkillCategory.GAME,
    tags=["casino", "game", "action"],
    cooldown=2,
)
def make_decision(action: str) -> str:
    """Execute a blackjack decision: hit | stand | double | fold."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    bj = scene._bj_state
    if not bj["active"] or bj["phase"] != "playing":
        return "No active hand. Deal cards first."
    action = action.lower().strip()
    if action not in ("hit", "stand", "double", "fold"):
        return "Valid actions: hit, stand, double, fold."

    from content.scenes.casino.casino_mcp import deal_hand

    if action == "hit":
        bj["player_hand"].extend(deal_hand(1))
        pval = scene._bj_hand_value(bj["player_hand"])
        if pval > 21:
            bj.update({"phase": "result", "result": "bust", "winnings": -bj["bet"], "active": False})
            scene._reputation_update("loss", bj["bet"])
            if bj["bet"] >= 100:
                scene._schedule_mira_call(bj["bet"])
            return f"Hit — bust at {pval}. Lost ${bj['bet']}."
        return f"Hit — now {pval}: {' '.join(bj['player_hand'])}."

    elif action == "stand":
        while scene._bj_hand_value(bj["dealer_hand"]) < 17:
            bj["dealer_hand"].extend(deal_hand(1))
        pval = scene._bj_hand_value(bj["player_hand"])
        dval = scene._bj_hand_value(bj["dealer_hand"])
        bj["phase"] = "result"
        if dval > 21 or pval > dval:
            bj.update({"result": "win", "winnings": bj["bet"], "active": False})
            scene._economy_credit(bj["buy_in"] + bj["winnings"], reason="casino_win")
            scene._reputation_update("win", bj["winnings"])
            if bj["winnings"] >= 200:
                scene._publish_major_win(bj["winnings"])
            return f"Stand — WIN! {pval} beats {dval}. +${bj['winnings']}."
        elif pval == dval:
            bj.update({"result": "push", "winnings": 0, "active": False})
            scene._economy_credit(bj["buy_in"], reason="casino_push")
            return f"Stand — push. {pval} = {dval}. Buy-in returned."
        else:
            bj.update({"result": "loss", "winnings": -bj["bet"], "active": False})
            scene._reputation_update("loss", bj["bet"])
            if bj["bet"] >= 100:
                scene._schedule_mira_call(bj["bet"])
            return f"Stand — LOSS. {dval} beats {pval}. -${bj['bet']}."

    elif action == "double":
        extra = min(bj["bet"], scene._economy_balance())
        if not scene._economy_spend(extra, reason="casino_double"):
            return "Can't afford to double down."
        bj["bet"] += extra
        bj["player_hand"].extend(deal_hand(1))
        pval = scene._bj_hand_value(bj["player_hand"])
        if pval > 21:
            bj.update({"phase": "result", "result": "bust", "winnings": -bj["bet"], "active": False})
            scene._reputation_update("loss", bj["bet"])
            if bj["bet"] >= 100:
                scene._schedule_mira_call(bj["bet"])
            return f"Double down — bust at {pval}. Lost ${bj['bet']}."
        while scene._bj_hand_value(bj["dealer_hand"]) < 17:
            bj["dealer_hand"].extend(deal_hand(1))
        dval = scene._bj_hand_value(bj["dealer_hand"])
        bj["phase"] = "result"
        bj["active"] = False
        if dval > 21 or pval > dval:
            bj["result"] = "win"
            bj["winnings"] = bj["bet"]
            scene._economy_credit(bj["buy_in"] + bj["winnings"], reason="casino_double_win")
            scene._reputation_update("win", bj["winnings"])
            if bj["winnings"] >= 200:
                scene._publish_major_win(bj["winnings"])
            return f"Double win! {pval} vs {dval}. +${bj['winnings']}."
        elif pval == dval:
            bj["result"] = "push"
            bj["winnings"] = 0
            scene._economy_credit(bj["buy_in"], reason="casino_push")
            return f"Double — push at {pval}."
        else:
            bj["result"] = "loss"
            bj["winnings"] = -bj["bet"]
            scene._reputation_update("loss", bj["bet"])
            if bj["bet"] >= 100:
                scene._schedule_mira_call(bj["bet"])
            return f"Double loss. {dval} beats {pval}. -${bj['bet']}."

    else:  # fold / surrender
        refund = bj["bet"] // 2
        scene._economy_credit(bj["buy_in"] - bj["bet"] + refund, reason="casino_surrender")
        bj.update({
            "result": "surrender",
            "winnings": -(bj["bet"] - refund),
            "phase": "result",
            "active": False,
        })
        return f"Surrender. Half bet (${refund}) returned. Balance: ${scene._economy_balance()}."


@skill(
    pack="casino",
    description="Cash out and return chips to credits",
    category=SkillCategory.GAME,
    tags=["casino", "game", "cashout"],
)
def cash_out() -> str:
    """End the session and convert any remaining chips to credits."""
    scene = _get_casino_scene()
    if not scene:
        return "Casino not active."
    bj = scene._bj_state
    if bj["active"]:
        return "Finish your current hand before cashing out."
    balance = scene._economy_balance()
    return f"Cashed out. Balance: ${balance}. The house thanks you."


# ── End of CLUB NOIR Casino Skills ─────────────────────────────────────
