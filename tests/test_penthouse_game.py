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
                    "explicitness", "openness", "dominance", "affection"}
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


# ══════════════════════════════════════════════════════════════════════
#  Explicit-pose eligibility — consent_given gate (v1.62.0)
# ══════════════════════════════════════════════════════════════════════

class TestBedgamePoseConsentGate:
    """_bedgame_pose_eligible must honour the consent_given flag for explicit poses."""

    def _make_scene(self, openness_by_id):
        """Build a minimal object exposing the mixin method + profiles."""
        from content.scenes.penthouse.penthouse_combat_mixin import PenthouseCombatMixin
        from content.scenes.penthouse.penthouse_scene import CharacterProfile, AgentStats

        class _Scene(PenthouseCombatMixin):
            pass

        scene = _Scene()
        scene.profiles = {}
        for cid, openness in openness_by_id.items():
            scene.profiles[cid] = CharacterProfile(stats=AgentStats(openness=openness))
        return scene

    def _set_consent(self, cid, value):
        from engine.mcp.character_registry import get_character_registry
        get_character_registry().set_state(cid, consent_given=value)

    def test_explicit_pose_blocked_when_consent_withdrawn(self):
        # High openness but consent_given=False → explicit pose NOT eligible.
        scene = self._make_scene({"alice": 90})
        self._set_consent("alice", False)
        assert scene._bedgame_pose_eligible(["alice"], explicit_level=5) is False

    def test_explicit_pose_allowed_with_consent_and_openness(self):
        # consent_given=True + openness >= min → explicit pose eligible.
        scene = self._make_scene({"alice": 90})
        self._set_consent("alice", True)
        assert scene._bedgame_pose_eligible(["alice"], explicit_level=5) is True

    def test_explicit_pose_blocked_when_openness_low(self):
        # Openness below the bar still blocks, even with consent given.
        scene = self._make_scene({"alice": 10})
        self._set_consent("alice", True)
        assert scene._bedgame_pose_eligible(["alice"], explicit_level=5) is False

    def test_low_explicit_level_bypasses_consent_gate(self):
        # Below the explicit gate level, poses always play (no consent needed).
        scene = self._make_scene({"alice": 0})
        self._set_consent("alice", False)
        assert scene._bedgame_pose_eligible(["alice"], explicit_level=1) is True

    def test_one_participant_without_consent_blocks_all(self):
        # If any involved character withdrew consent, the explicit pose is gated.
        scene = self._make_scene({"alice": 90, "bob": 90})
        self._set_consent("alice", True)
        self._set_consent("bob", False)
        assert scene._bedgame_pose_eligible(["alice", "bob"], explicit_level=5) is False

    def test_director_treated_as_consenting(self):
        # Director has no profile/flags and is always treated as consenting.
        scene = self._make_scene({"alice": 90})
        self._set_consent("alice", True)
        assert scene._bedgame_pose_eligible(["director", "alice"], explicit_level=5) is True

    def test_skill_path_fail_closed_without_gate_method(self):
        # v1.62.0 — regression: the skill path defaults pose_eligible=False so a
        # scene lacking _bedgame_pose_eligible can never let an EXPLICIT pose
        # through un-gated. We feed an explicit action into the skill via a fake
        # scene with NO gate method and assert the emitted payload is gated.
        from content.scenes.penthouse import penthouse_skills
        from content.scenes.penthouse.penthouse_scene import BedGameState

        emitted = {}

        class _FakeSceneNoGate:
            # Deliberately NO _bedgame_pose_eligible method.
            def __init__(self):
                self.bed_game = BedGameState(
                    active=True,
                    players=["alice", "bob"],
                    player_names={"alice": "Alice", "bob": "Bob"},
                )

                class _SIO:
                    def emit(_self, event, payload, *a, **k):
                        emitted[event] = payload

                self.socketio = _SIO()

            def _broadcast_state(self):
                pass

        fake = _FakeSceneNoGate()
        penthouse_skills._get_penthouse_scene = lambda: fake
        try:
            # "ride" is an explicit_level=5 action (>= the gate level of 3).
            penthouse_skills.penthouse_game_action(action="ride")
        finally:
            # Restore the original lookup so other tests are unaffected.
            import importlib
            importlib.reload(penthouse_skills)

        assert "bedgame_action" in emitted
        # Sanity: confirm this really exercised the explicit branch.
        assert emitted["bedgame_action"]["explicit_level"] >= 3
        # Explicit action with no gate method present must be suppressed.
        assert emitted["bedgame_action"]["pose_eligible"] is False


# ══════════════════════════════════════════════════════════════════════
#  v1.62.0 — Multi-agent registration: every present character gets an agent
# ══════════════════════════════════════════════════════════════════════

class TestMultiAgentRegistration:
    """Every present non-player character must register its own agent.

    Regression for v1.62.0: the load path capped characters at a hardcoded
    2 (contradicting SCENE_METADATA['max_characters'] = 3), so a 3rd
    character could never enter the scene and therefore never receive a
    CharacterAgent. These tests pin the cap to the metadata value and pin
    the AgentLoop invariant: N registered characters → N agents.
    """

    def test_character_cap_uses_scene_metadata_not_hardcoded_two(self):
        # The load-path capacity check must reference the configured maximum,
        # not a literal `>= 2`. SCENE_METADATA declares max_characters = 3.
        from pathlib import Path
        from content.scenes.penthouse.penthouse_scene import PenthouseScene

        cap = PenthouseScene.SCENE_METADATA.get("max_characters")
        assert cap == 3, "SCENE_METADATA max_characters should be 3"

        src = (
            Path(__file__).parent.parent
            / "content" / "scenes" / "penthouse" / "penthouse_social_mixin.py"
        ).read_text(encoding="utf-8")
        # The old hardcoded gate must be gone; capacity is derived from config.
        assert ">= 2 and" not in src, (
            "penthouse_social_mixin must not hardcode a 2-character cap; "
            "derive it from SCENE_METADATA['max_characters']"
        )

    def test_agent_loop_registers_one_agent_per_character(self):
        # Pin the core invariant: registering N characters with non-None
        # agents yields N entries in agent_loop._agents.
        from engine.agents.agent_loop import AgentLoop

        class _Char:
            def __init__(self, cid):
                self.id = cid
                self.name = cid.title()

        class _Map:
            def remove_character(self, *_a, **_k):
                pass

        loop = AgentLoop(scene_map=_Map(), db=None, socketio=None, scene_id="penthouse")
        cids = ["mira", "lola", "aria"]
        for cid in cids:
            loop.register_character(_Char(cid), agent=object())

        assert len(loop._agents) == len(cids)
        assert set(loop._agents.keys()) == set(cids)
        # And the present-character / agent counts must match (the runtime assertion).
        assert len(loop._agents) == len(loop._characters)


class TestNexusStoreEventGuard:
    """nexus_store_event must not raise when the Nexus layer is uninitialised.

    Regression for v1.62.0: _on_agent_action calls nexus_store_event for
    every agent action. When _connect_nexus() has not run (any tick path
    that doesn't go through the full server run(), e.g. manual tick or
    tests), `self._nexus_scene_id` is unset and the method raised
    AttributeError — which AgentLoop.tick() caught and turned into a
    duplicate idle/error action per character, corrupting agent turns.
    """

    def test_store_event_no_attribute_error_when_uninitialised(self):
        from engine.scenes.nexus_mixin import NexusSceneMixin

        class _Scene(NexusSceneMixin):
            pass

        scene = _Scene()
        # Deliberately do NOT call _connect_nexus(): _nexus_scene_id is unset.
        # This must be a no-op, not an AttributeError.
        scene.nexus_store_event("agent_speak", "Mira: hello", tags=["mira", "speak"])
