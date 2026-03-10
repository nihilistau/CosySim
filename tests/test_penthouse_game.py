"""Tests for Bedroom scene game logic — BedGameState, AgentStats, actions, escalation."""

import pytest
from dataclasses import asdict
from content.scenes.penthouse.penthouse_scene import (
    BedGameState, AgentStats, BED_GAME_ACTIONS, ESCALATION_THRESHOLDS,
)


# ══════════════════════════════════════════════════════════════════════
#  BedGameState — initialisation
# ══════════════════════════════════════════════════════════════════════

class TestBedGameStateInit:
    def test_default_state(self):
        g = BedGameState()
        assert g.active is False
        assert g.players == []
        assert g.turn_index == 0
        assert g.round_number == 1
        assert g.max_rounds == 0
        assert g.escalation_level == 1

    def test_current_player_empty(self):
        g = BedGameState()
        assert g.current_player_id == ""

    def test_current_player_with_players(self):
        g = BedGameState(players=["a", "b"], player_names={"a": "Alice", "b": "Bob"})
        assert g.current_player_id == "a"
        assert g.current_player_name == "Alice"

    def test_to_dict_keys(self):
        g = BedGameState(players=["a"], player_names={"a": "A"}, active=True)
        d = g.to_dict()
        expected_keys = {
            "active", "players", "player_names", "current_player",
            "current_name", "turn_index", "round", "max_rounds",
            "history", "available_actions", "escalation",
        }
        assert expected_keys == set(d.keys())


# ══════════════════════════════════════════════════════════════════════
#  Turn management
# ══════════════════════════════════════════════════════════════════════

class TestTurnManagement:
    def test_advance_two_players(self):
        g = BedGameState(players=["a", "b"])
        assert g.current_player_id == "a"
        nxt = g.advance_turn()
        assert nxt == "b"
        assert g.round_number == 1  # still round 1

    def test_round_increments_after_full_rotation(self):
        g = BedGameState(players=["a", "b"])
        g.advance_turn()  # -> b, round 1
        g.advance_turn()  # -> a, round 2
        assert g.round_number == 2
        assert g.current_player_id == "a"

    def test_three_player_rotation(self):
        g = BedGameState(players=["a", "b", "c"])
        ids = [g.current_player_id]
        for _ in range(6):
            ids.append(g.advance_turn())
        # Two full rotations: a b c a b c a
        assert ids == ["a", "b", "c", "a", "b", "c", "a"]
        assert g.round_number == 3  # started at 1, +1 after each full rotation

    def test_current_player_name_fallback(self):
        g = BedGameState(players=["x"], player_names={})
        assert g.current_player_name == "x"  # falls back to id


# ══════════════════════════════════════════════════════════════════════
#  Available actions
# ══════════════════════════════════════════════════════════════════════

class TestAvailableActions:
    def test_two_player_actions(self):
        g = BedGameState(players=["a", "b"])
        actions = g.available_actions()
        assert len(actions) > 0
        for a in actions:
            assert a["min_players"] <= 2

    def test_three_player_unlocks_more(self):
        g2 = BedGameState(players=["a", "b"])
        g3 = BedGameState(players=["a", "b", "c"])
        assert len(g3.available_actions()) > len(g2.available_actions())

    def test_threesome_actions_require_three(self):
        g = BedGameState(players=["a", "b"])
        action_ids = {a["id"] for a in g.available_actions()}
        assert "threesome — spit roast" not in action_ids

        g3 = BedGameState(players=["a", "b", "c"])
        action_ids3 = {a["id"] for a in g3.available_actions()}
        assert "threesome — spit roast" in action_ids3

    def test_all_actions_have_required_keys(self):
        for aid, data in BED_GAME_ACTIONS.items():
            assert "stat_effects" in data, f"{aid} missing stat_effects"
            assert "min_players" in data, f"{aid} missing min_players"
            assert "explicit_level" in data, f"{aid} missing explicit_level"
            assert "description" in data, f"{aid} missing description"


# ══════════════════════════════════════════════════════════════════════
#  Action stat effects
# ══════════════════════════════════════════════════════════════════════

class TestActionStatEffects:
    def test_kiss_deeply_effects(self):
        fx = BED_GAME_ACTIONS["kiss deeply"]["stat_effects"]
        assert fx["arousal"] == 8
        assert fx["pleasure"] == 6
        assert fx["horniness"] == 5

    def test_orgasm_together_reduces_arousal(self):
        fx = BED_GAME_ACTIONS["orgasm together"]["stat_effects"]
        assert fx["arousal"] < 0
        assert fx["horniness"] < 0
        assert fx["pleasure"] > 0
        assert fx["happiness"] > 0

    def test_aftercare_calms_down(self):
        fx = BED_GAME_ACTIONS["aftercare"]["stat_effects"]
        assert fx["arousal"] < 0
        assert fx["happiness"] > 0
        assert fx["affection"] > 0


# ══════════════════════════════════════════════════════════════════════
#  Escalation system
# ══════════════════════════════════════════════════════════════════════

class TestEscalation:
    def test_record_escalation_updates_peak(self):
        g = BedGameState(players=["a", "b"], player_scores={"a": 0, "b": 0})
        g.record_escalation("a", 3)
        assert g.peak_explicit == 3

    def test_record_escalation_higher_replaces(self):
        g = BedGameState(players=["a", "b"], player_scores={"a": 0, "b": 0})
        g.record_escalation("a", 3)
        g.record_escalation("a", 5)
        assert g.peak_explicit == 5

    def test_streak_increments_on_high_explicit(self):
        g = BedGameState(players=["a"], player_scores={"a": 0})
        g.record_escalation("a", 4)
        assert g.streak == 1
        g.record_escalation("a", 5)
        assert g.streak == 2

    def test_streak_decrements_on_low_explicit(self):
        g = BedGameState(players=["a"], player_scores={"a": 0}, streak=3)
        g.record_escalation("a", 2)
        assert g.streak == 2  # max(0, 3-1)

    def test_player_scores_accumulate(self):
        g = BedGameState(players=["a", "b"], player_scores={})
        g.record_escalation("a", 3)
        g.record_escalation("b", 5)
        assert g.player_scores["a"] > 0
        assert g.player_scores["b"] > g.player_scores["a"]

    def test_escalation_info_structure(self):
        g = BedGameState(players=["a"], player_scores={"a": 10})
        info = g.escalation_info
        assert "level" in info
        assert "label" in info
        assert "bonus" in info
        assert "prompt_hint" in info
        assert "streak" in info
        assert "leader" in info
        assert "scores" in info

    def test_escalation_level_updates_from_history(self):
        g = BedGameState(players=["a"], player_scores={"a": 0})
        # Simulate a history of high-explicit actions
        for _ in range(6):
            g.history.append({"explicit_level": 5})
        g.record_escalation("a", 5)
        assert g.escalation_level == 5

    def test_escalation_thresholds_cover_all_levels(self):
        for lvl in range(1, 6):
            assert lvl in ESCALATION_THRESHOLDS
            t = ESCALATION_THRESHOLDS[lvl]
            assert "label" in t
            assert "bonus" in t
            assert "prompt_hint" in t


# ══════════════════════════════════════════════════════════════════════
#  AgentStats
# ══════════════════════════════════════════════════════════════════════

class TestAgentStats:
    def test_defaults(self):
        s = AgentStats()
        assert s.arousal == 20.0
        assert s.happiness == 60.0
        assert s.pleasure == 10.0

    def test_adjust_adds(self):
        s = AgentStats()
        s.adjust(arousal=30)
        assert s.arousal == 50.0

    def test_adjust_clamps_high(self):
        s = AgentStats(arousal=90)
        s.adjust(arousal=50)
        assert s.arousal == 100.0

    def test_adjust_clamps_low(self):
        s = AgentStats(arousal=10)
        s.adjust(arousal=-50)
        assert s.arousal == 0.0

    def test_adjust_ignores_unknown_keys(self):
        s = AgentStats()
        s.adjust(nonexistent=99)
        # Should not crash; no new attribute created
        assert not hasattr(s, "nonexistent") or s.nonexistent is None

    def test_clamp_all_fields(self):
        s = AgentStats(arousal=150, happiness=-20)
        s.clamp()
        assert s.arousal == 100.0
        assert s.happiness == 0.0

    def test_compliance_score_range(self):
        s = AgentStats()
        score = s.compliance_score()
        assert 0 <= score <= 100

    def test_compliance_increases_with_drunkenness(self):
        sober = AgentStats(drunkenness=0)
        drunk = AgentStats(drunkenness=80)
        assert drunk.compliance_score() > sober.compliance_score()

    def test_compliance_decreases_with_anger(self):
        calm = AgentStats(anger=0)
        angry = AgentStats(anger=80)
        assert angry.compliance_score() < calm.compliance_score()

    def test_describe_neutral(self):
        s = AgentStats(arousal=0, horniness=0, drunkenness=0, tiredness=0,
                       happiness=50, anger=0, fear=0, pleasure=0)
        assert s.describe() == "neutral"

    def test_describe_aroused(self):
        s = AgentStats(arousal=80)
        desc = s.describe()
        assert "aroused" in desc

    def test_to_dict_all_keys(self):
        s = AgentStats()
        d = s.to_dict()
        expected = {"arousal", "horniness", "drunkenness", "tiredness",
                    "happiness", "anger", "fear", "pleasure",
                    "explicitness", "openness"}
        assert set(d.keys()) == expected

    def test_apply_action_stat_effects(self):
        """Applying an action's stat_effects through AgentStats.adjust."""
        s = AgentStats()
        fx = BED_GAME_ACTIONS["kiss deeply"]["stat_effects"]
        s.adjust(**fx)
        assert s.arousal == 20.0 + 8
        assert s.pleasure == 10.0 + 6
        assert s.horniness == 15.0 + 5


# ══════════════════════════════════════════════════════════════════════
#  Edge cases
# ══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_game_with_single_player(self):
        g = BedGameState(players=["solo"])
        assert g.current_player_id == "solo"
        g.advance_turn()
        assert g.current_player_id == "solo"
        assert g.round_number == 2

    def test_max_rounds_not_enforced_by_state(self):
        """max_rounds is advisory; BedGameState does not stop the game."""
        g = BedGameState(players=["a", "b"], max_rounds=2)
        for _ in range(10):
            g.advance_turn()
        # Game keeps going even past max_rounds
        assert g.round_number > 2

    def test_history_trimmed_in_to_dict(self):
        g = BedGameState(players=["a"])
        g.history = [{"action": f"a{i}"} for i in range(20)]
        d = g.to_dict()
        assert len(d["history"]) == 10  # last 10 only

    def test_escalation_info_no_scores(self):
        g = BedGameState(players=["a"], player_scores={})
        info = g.escalation_info
        assert info["leader"] is None
