"""Tests for Casino scene game logic — cards, hands, betting, drinks, events."""

import pytest
import random
from unittest.mock import MagicMock, patch
from content.scenes.casino.casino_mcp import (
    deal_hand, evaluate_hand_simple, pick_random_event,
    HAND_RANKS, SUITS, VALUES, CASINO_DRINKS, RANDOM_EVENTS, TELL_DESCRIPTIONS,
)


# ══════════════════════════════════════════════════════════════════════
#  Card dealing
# ══════════════════════════════════════════════════════════════════════

class TestDealHand:
    def test_deal_default_two_cards(self):
        hand = deal_hand()
        assert len(hand) == 2

    def test_deal_n_cards(self):
        for n in (1, 3, 5, 7):
            hand = deal_hand(n)
            assert len(hand) == n

    def test_deal_no_duplicates(self):
        hand = deal_hand(10)
        assert len(hand) == len(set(hand))

    def test_deal_cap_at_deck_size(self):
        deck_size = len(VALUES) * len(SUITS)  # 52
        hand = deal_hand(100)
        assert len(hand) == deck_size

    def test_card_format(self):
        hand = deal_hand(5)
        for card in hand:
            # Card should be value + suit, e.g. "10♠" or "A♥"
            assert card[-1] in "♠♥♦♣"
            value_part = card[:-1]
            assert value_part in VALUES


# ══════════════════════════════════════════════════════════════════════
#  Hand evaluation
# ══════════════════════════════════════════════════════════════════════

class TestEvaluateHand:
    def test_high_card(self):
        result = evaluate_hand_simple(["2♠", "5♥", "9♦", "J♣", "K♠"])
        assert result["rank"] == "high_card"
        assert result["score"] == 0

    def test_pair(self):
        result = evaluate_hand_simple(["A♠", "A♥", "3♦", "7♣", "9♠"])
        assert result["rank"] == "pair"
        assert result["score"] == 1

    def test_two_pair(self):
        result = evaluate_hand_simple(["A♠", "A♥", "K♦", "K♣", "9♠"])
        assert result["rank"] == "two_pair"
        assert result["score"] == 2

    def test_three_of_a_kind(self):
        result = evaluate_hand_simple(["A♠", "A♥", "A♦", "7♣", "9♠"])
        assert result["rank"] == "three_of_a_kind"
        assert result["score"] == 3

    def test_full_house(self):
        result = evaluate_hand_simple(["A♠", "A♥", "A♦", "K♣", "K♠"])
        assert result["rank"] == "full_house"
        assert result["score"] == 6

    def test_four_of_a_kind(self):
        result = evaluate_hand_simple(["A♠", "A♥", "A♦", "A♣", "9♠"])
        assert result["rank"] == "four_of_a_kind"
        assert result["score"] == 7

    def test_score_ordering(self):
        """Higher-ranked hands should have higher scores."""
        high_card = evaluate_hand_simple(["2♠", "5♥", "9♦", "J♣", "K♠"])
        pair = evaluate_hand_simple(["A♠", "A♥", "3♦", "7♣", "9♠"])
        three = evaluate_hand_simple(["A♠", "A♥", "A♦", "7♣", "9♠"])
        full = evaluate_hand_simple(["A♠", "A♥", "A♦", "K♣", "K♠"])
        four = evaluate_hand_simple(["A♠", "A♥", "A♦", "A♣", "9♠"])
        assert high_card["score"] < pair["score"] < three["score"] < full["score"] < four["score"]

    def test_empty_hand(self):
        result = evaluate_hand_simple([])
        assert result["rank"] == "high_card"
        assert result["score"] == 0

    def test_single_card(self):
        result = evaluate_hand_simple(["A♠"])
        assert result["rank"] == "high_card"


# ══════════════════════════════════════════════════════════════════════
#  Casino game state logic (isolated from Flask)
# ══════════════════════════════════════════════════════════════════════

class TestCasinoGameState:
    """Test the pure game-state logic from CasinoScene without Flask deps."""

    def _make_state(self):
        """Return a minimal game-state dict mirroring CasinoScene attributes."""
        return {
            "player_chips": 500,
            "mira_chips": 500,
            "pot": 0,
            "round_number": 0,
            "game_active": False,
            "current_phase": "lobby",
            "player_stats": {
                "confidence": 50.0, "focus": 50.0, "luck": 50.0,
                "charm": 50.0, "recklessness": 20.0,
            },
            "hand_history": [],
        }

    def test_ante_deduction(self):
        s = self._make_state()
        ante = 10
        s["player_chips"] -= ante
        s["mira_chips"] -= ante
        s["pot"] = ante * 2
        assert s["player_chips"] == 490
        assert s["mira_chips"] == 490
        assert s["pot"] == 20

    def test_bet_placement(self):
        s = self._make_state()
        bet = 50
        s["player_chips"] -= bet
        s["pot"] += bet
        assert s["player_chips"] == 450
        assert s["pot"] == 50

    def test_bet_capped_at_available_chips(self):
        s = self._make_state()
        s["player_chips"] = 30
        amount = min(50, s["player_chips"])
        assert amount == 30

    def test_invalid_bet_zero(self):
        s = self._make_state()
        amount = min(0, s["player_chips"])
        assert amount <= 0  # would be rejected

    def test_mira_call(self):
        s = self._make_state()
        bet = 40
        mira_bet = min(bet, s["mira_chips"])
        s["mira_chips"] -= mira_bet
        s["pot"] += mira_bet
        assert s["mira_chips"] == 460
        assert s["pot"] == 40

    def test_mira_raise(self):
        s = self._make_state()
        bet = 30
        mira_bet = min(bet * 2, s["mira_chips"])
        s["mira_chips"] -= mira_bet
        s["pot"] += mira_bet
        assert mira_bet == 60
        assert s["mira_chips"] == 440

    def test_showdown_player_wins(self):
        s = self._make_state()
        s["pot"] = 100
        player_eval = {"rank": "pair", "score": 1}
        mira_eval = {"rank": "high_card", "score": 0}
        if player_eval["score"] >= mira_eval["score"]:
            winner = "player"
            s["player_chips"] += s["pot"]
        else:
            winner = "mira"
            s["mira_chips"] += s["pot"]
        s["pot"] = 0
        assert winner == "player"
        assert s["player_chips"] == 600

    def test_showdown_mira_wins(self):
        s = self._make_state()
        s["pot"] = 80
        player_eval = {"rank": "high_card", "score": 0}
        mira_eval = {"rank": "three_of_a_kind", "score": 3}
        if player_eval["score"] >= mira_eval["score"]:
            winner = "player"
            s["player_chips"] += s["pot"]
        else:
            winner = "mira"
            s["mira_chips"] += s["pot"]
        s["pot"] = 0
        assert winner == "mira"
        assert s["mira_chips"] == 580

    def test_luck_modifier(self):
        s = self._make_state()
        s["player_stats"]["luck"] = 75
        luck_bonus = int((s["player_stats"]["luck"] - 50) / 25)
        assert luck_bonus == 1

    def test_luck_modifier_negative(self):
        s = self._make_state()
        s["player_stats"]["luck"] = 25
        luck_bonus = int((s["player_stats"]["luck"] - 50) / 25)
        assert luck_bonus == -1

    def test_phase_transitions(self):
        s = self._make_state()
        assert s["current_phase"] == "lobby"
        s["current_phase"] = "deal"
        s["current_phase"] = "bet"
        s["current_phase"] = "showdown"
        s["current_phase"] = "result"
        assert s["current_phase"] == "result"

    def test_recklessness_increases_with_bets(self):
        s = self._make_state()
        initial = s["player_stats"]["recklessness"]
        amount = 100
        s["player_stats"]["recklessness"] = min(
            100, s["player_stats"]["recklessness"] + amount / 50
        )
        assert s["player_stats"]["recklessness"] > initial

    def test_confidence_boost_on_win(self):
        s = self._make_state()
        s["player_stats"]["confidence"] = min(100, s["player_stats"]["confidence"] + 15)
        assert s["player_stats"]["confidence"] == 65.0

    def test_confidence_drop_on_loss(self):
        s = self._make_state()
        s["player_stats"]["confidence"] = max(0, s["player_stats"]["confidence"] - 10)
        assert s["player_stats"]["confidence"] == 40.0


# ══════════════════════════════════════════════════════════════════════
#  Bluff power calculation
# ══════════════════════════════════════════════════════════════════════

class TestBluffLogic:
    def test_bluff_power_formula(self):
        stats = {"charm": 70, "confidence": 80, "focus": 60, "recklessness": 30}
        power = (
            stats["charm"] * 0.3
            + stats["confidence"] * 0.3
            + stats["focus"] * 0.2
            - stats["recklessness"] * 0.2
        )
        assert power == pytest.approx(51.0)

    def test_high_recklessness_hurts_bluff(self):
        base = {"charm": 50, "confidence": 50, "focus": 50, "recklessness": 0}
        reckless = {"charm": 50, "confidence": 50, "focus": 50, "recklessness": 80}
        p_base = base["charm"]*0.3 + base["confidence"]*0.3 + base["focus"]*0.2 - base["recklessness"]*0.2
        p_reck = reckless["charm"]*0.3 + reckless["confidence"]*0.3 + reckless["focus"]*0.2 - reckless["recklessness"]*0.2
        assert p_reck < p_base


# ══════════════════════════════════════════════════════════════════════
#  Drinks
# ══════════════════════════════════════════════════════════════════════

class TestDrinks:
    def test_all_drinks_have_required_fields(self):
        for did, d in CASINO_DRINKS.items():
            assert "name" in d
            assert "cost" in d
            assert "stat_effects" in d
            assert isinstance(d["cost"], int)
            assert d["cost"] > 0

    def test_drink_stat_application(self):
        stats = {"confidence": 50.0, "focus": 50.0, "luck": 50.0,
                 "charm": 50.0, "recklessness": 20.0}
        drink = CASINO_DRINKS["whiskey_neat"]
        for k, v in drink["stat_effects"].items():
            stats[k] = stats.get(k, 0) + v
        assert stats["confidence"] == 60.0
        assert stats["focus"] == 45.0

    def test_drink_cost_deduction(self):
        chips = 500
        drink = CASINO_DRINKS["champagne_tower"]
        chips -= drink["cost"]
        assert chips == 475

    def test_cannot_afford_drink(self):
        chips = 1
        drink = CASINO_DRINKS["champagne_tower"]
        assert chips < drink["cost"]


# ══════════════════════════════════════════════════════════════════════
#  Random events and tells
# ══════════════════════════════════════════════════════════════════════

class TestRandomEvents:
    def test_pick_random_event_returns_dict(self):
        evt = pick_random_event()
        assert isinstance(evt, dict)
        assert "id" in evt
        assert "text" in evt
        assert "stat_effect" in evt

    def test_all_events_have_stat_effects(self):
        for e in RANDOM_EVENTS:
            assert isinstance(e["stat_effect"], dict)

    def test_tell_descriptions_non_empty(self):
        assert len(TELL_DESCRIPTIONS) > 0
        for t in TELL_DESCRIPTIONS:
            assert isinstance(t, str)
            assert len(t) > 0


# ══════════════════════════════════════════════════════════════════════
#  Hand history recording
# ══════════════════════════════════════════════════════════════════════

class TestHandHistory:
    def test_record_hand(self):
        history = []
        record = {
            "round": 1, "winner": "player",
            "player_hand": ["A♠", "K♠"], "player_eval": "pair",
            "mira_hand": ["2♥", "3♦"], "mira_eval": "high_card",
            "community": ["5♠", "A♥", "9♦"],
        }
        history.append(record)
        assert len(history) == 1
        assert history[0]["winner"] == "player"

    def test_history_last_five(self):
        history = [{"round": i} for i in range(10)]
        assert len(history[-5:]) == 5
        assert history[-5:][0]["round"] == 5


# ══════════════════════════════════════════════════════════════════════
#  Data integrity
# ══════════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    def test_hand_ranks_ordering(self):
        assert HAND_RANKS[0] == "high_card"
        assert HAND_RANKS[-1] == "royal_flush"
        assert len(HAND_RANKS) == 10

    def test_deck_size(self):
        assert len(VALUES) == 13
        assert len(SUITS) == 4

    def test_full_deck_52(self):
        deck = [f"{v}{s}" for v in VALUES for s in SUITS]
        assert len(deck) == 52
        assert len(set(deck)) == 52
