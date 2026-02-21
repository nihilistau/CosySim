"""
casino_mcp.py — MCP rules, data, and helpers for The Midnight Casino
=====================================================================

All casino-specific game data, character definitions, and rule registration
live here.  The scene module imports only what it needs so the scene file
stays focused on Flask/SocketIO routing.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCENE_ID    = "casino"
DEALER_ID   = "dealer_jack"
HUSTLER_ID  = "hustler_mira"

# ══════════════════════════════════════════════════════════════════════
#  POKER HANDS (simplified Texas Hold'em ranking)
# ══════════════════════════════════════════════════════════════════════

HAND_RANKS = [
    "high_card", "pair", "two_pair", "three_of_a_kind",
    "straight", "flush", "full_house", "four_of_a_kind",
    "straight_flush", "royal_flush",
]

SUITS = ["♠", "♥", "♦", "♣"]
VALUES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

def deal_hand(n: int = 2) -> List[str]:
    """Deal n random cards."""
    deck = [f"{v}{s}" for v in VALUES for s in SUITS]
    return random.sample(deck, min(n, len(deck)))

def evaluate_hand_simple(cards: List[str]) -> Dict:
    """Simplified hand evaluation — returns rank name and score 0–9."""
    # Simple heuristic: count pairs
    vals = [c[:-1] for c in cards]
    from collections import Counter
    counts = Counter(vals)
    mc = counts.most_common()
    if len(mc) >= 1 and mc[0][1] >= 4:
        return {"rank": "four_of_a_kind", "score": 7}
    if len(mc) >= 2 and mc[0][1] >= 3 and mc[1][1] >= 2:
        return {"rank": "full_house", "score": 6}
    if len(mc) >= 1 and mc[0][1] >= 3:
        return {"rank": "three_of_a_kind", "score": 3}
    if len(mc) >= 2 and mc[0][1] >= 2 and mc[1][1] >= 2:
        return {"rank": "two_pair", "score": 2}
    if len(mc) >= 1 and mc[0][1] >= 2:
        return {"rank": "pair", "score": 1}
    return {"rank": "high_card", "score": 0}


# ══════════════════════════════════════════════════════════════════════
#  COCKTAILS & SIDE BETS
# ══════════════════════════════════════════════════════════════════════

CASINO_DRINKS = {
    "whiskey_neat": {
        "name": "Whiskey Neat",
        "emoji": "🥃",
        "cost": 5,
        "stat_effects": {"confidence": 10, "focus": -5},
        "description": "A measure of courage in a glass.",
    },
    "champagne_tower": {
        "name": "Champagne Tower",
        "emoji": "🍾",
        "cost": 25,
        "stat_effects": {"confidence": 15, "charm": 10, "focus": -10},
        "description": "You're celebrating already? Bold move.",
    },
    "black_coffee": {
        "name": "Black Coffee",
        "emoji": "☕",
        "cost": 2,
        "stat_effects": {"focus": 15, "confidence": -5},
        "description": "The sharp player's choice.",
    },
    "lucky_martini": {
        "name": "Lucky Martini",
        "emoji": "🍸",
        "cost": 10,
        "stat_effects": {"luck": 5, "charm": 5},
        "description": "Stirred, not shaken. For luck.",
    },
    "devils_old_fashioned": {
        "name": "Devil's Old Fashioned",
        "emoji": "😈",
        "cost": 15,
        "stat_effects": {"confidence": 20, "recklessness": 15, "focus": -10},
        "description": "Bourbon, bitters, and bad decisions.",
    },
}


# ══════════════════════════════════════════════════════════════════════
#  BLUFF TELLS — what the AI looks for when evaluating bluffs
# ══════════════════════════════════════════════════════════════════════

TELL_DESCRIPTIONS = [
    "adjusts their collar nervously",
    "maintains unnervingly steady eye contact",
    "taps the table rhythmically",
    "leans back with a half-smile",
    "fidgets with their chips",
    "glances at their cards one more time",
    "takes a slow sip of their drink",
    "cracks their knuckles quietly",
    "narrows their eyes almost imperceptibly",
    "drums their fingers once — then stops",
]


# ══════════════════════════════════════════════════════════════════════
#  CASINO EVENTS — random atmospheric events
# ══════════════════════════════════════════════════════════════════════

RANDOM_EVENTS = [
    {"id": "high_roller", "text": "A high roller enters the room, drawing everyone's attention.", "stat_effect": {"confidence": -5}},
    {"id": "winning_streak", "text": "Someone at the roulette table lets out a triumphant shout.", "stat_effect": {"recklessness": 5}},
    {"id": "power_outage", "text": "The lights flicker for a moment. Tension rises.", "stat_effect": {"focus": 5}},
    {"id": "singer", "text": "A lounge singer begins a smoky rendition of 'Luck Be a Lady'.", "stat_effect": {"charm": 5}},
    {"id": "security", "text": "Security escorts someone out. The room goes quiet.", "stat_effect": {"confidence": -10, "focus": 10}},
    {"id": "jackpot", "text": "Slot machines erupt — jackpot somewhere in the casino.", "stat_effect": {"recklessness": 10}},
    {"id": "whisper", "text": "Mira leans over and whispers a tip about your opponent's tell.", "stat_effect": {"focus": 10}},
    {"id": "complimentary", "text": "The house sends over complimentary drinks.", "stat_effect": {"confidence": 5, "focus": -5}},
]

def pick_random_event() -> Dict:
    return random.choice(RANDOM_EVENTS)


# ══════════════════════════════════════════════════════════════════════
#  RULE REGISTRATION
# ══════════════════════════════════════════════════════════════════════

def register_casino_rules() -> None:
    """Register casino-specific rules with the MCP framework."""
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine, RuleDefinition, ActionDefinition, RuleCondition

        eng = get_rules_engine()

        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="bet", label="Place a Bet",
            description="Wager chips on the current hand",
            intimacy_level=0,
            stat_effects={"recklessness": 3},
        ))
        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="bluff", label="Bluff",
            description="Attempt to mislead opponents about your hand",
            intimacy_level=0,
            stat_effects={"confidence": 5, "recklessness": 5},
        ))
        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="fold", label="Fold",
            description="Surrender the hand",
            intimacy_level=0,
            stat_effects={"confidence": -5},
        ))
        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="order_drink", label="Order a Drink",
            description="Order from the casino bar",
            intimacy_level=0,
            stat_effects={},
        ))
        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="read_opponent", label="Read Opponent",
            description="Study your opponent for tells",
            intimacy_level=0,
            stat_effects={"focus": 5},
        ))
        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="side_bet", label="Side Bet",
            description="Make a personal wager with another player",
            intimacy_level=1,
            stat_effects={"recklessness": 10, "charm": 5},
        ))
        eng.register_action(SCENE_ID, ActionDefinition(
            action_id="all_in", label="Go All In",
            description="Push all your chips into the pot — ultimate risk",
            intimacy_level=0,
            stat_effects={"recklessness": 20, "confidence": 15},
            conditions=RuleCondition(thresholds={"confidence": 30}),
        ))

        logger.info("Casino rules registered")
    except Exception as exc:
        logger.warning("Casino rule registration failed: %s", exc)
