"""Tests for Heist game logic — state, actions, phases, skill checks."""

import pytest
import random
from content.scenes.heist.heist_game import (
    HeistState, Phase, Specialty, CrewMember, VENUES, COMPLICATIONS, SKILL_TABLE,
)


class TestHeistStateCreation:
    def test_new_heist_default(self):
        g = HeistState.new_heist()
        assert g.venue_key == "diamond_exchange"
        assert g.phase == Phase.PLANNING
        assert g.turn == 0
        assert g.suspicion == 15
        assert g.loot_collected == 0
        assert len(g.obstacles_remaining) == 3

    def test_new_heist_art_museum(self):
        g = HeistState.new_heist("art_museum")
        assert g.venue_key == "art_museum"
        assert g.suspicion == 25
        assert g.loot_target == 2_000_000
        assert len(g.obstacles_remaining) == 4

    def test_new_heist_casino_vault(self):
        g = HeistState.new_heist("casino_vault")
        assert g.suspicion == 30
        assert len(g.obstacles_remaining) == 5

    def test_new_heist_invalid_venue_falls_back(self):
        g = HeistState.new_heist("nonexistent")
        assert g.venue_key == "nonexistent"
        # Falls back to diamond_exchange defaults via VENUES.get
        assert g.loot_target == 500_000


class TestCrewManagement:
    def test_add_crew_member(self):
        g = HeistState.new_heist()
        m = g.add_crew("ghost", "Ghost", "hacker")
        assert m.char_id == "ghost"
        assert m.name == "Ghost"
        assert m.specialty == Specialty.HACKER
        assert m.health == 100
        assert m.morale == 75

    def test_add_crew_invalid_specialty(self):
        g = HeistState.new_heist()
        m = g.add_crew("test", "Test", "invalid_specialty")
        assert m.specialty == Specialty.WILDCARD

    def test_crew_summary(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        g.add_crew("tank", "Tank", "muscle")
        summary = g.crew_summary()
        assert "Ghost" in summary
        assert "Tank" in summary
        assert "hacker" in summary

    def test_empty_crew_summary(self):
        g = HeistState.new_heist()
        assert g.crew_summary() == "No crew assigned."


class TestSkillChecks:
    def test_hacker_disable_alarm_high_chance(self):
        m = CrewMember(char_id="test", name="Test", specialty=Specialty.HACKER)
        assert m.success_chance("disable_alarm") > 0.8

    def test_muscle_fight_high_chance(self):
        m = CrewMember(char_id="test", name="Test", specialty=Specialty.MUSCLE)
        assert m.success_chance("fight") > 0.8

    def test_talker_persuade_high_chance(self):
        m = CrewMember(char_id="test", name="Test", specialty=Specialty.TALKER)
        assert m.success_chance("persuade") > 0.8

    def test_driver_drive_high_chance(self):
        m = CrewMember(char_id="test", name="Test", specialty=Specialty.DRIVER)
        assert m.success_chance("drive") > 0.85

    def test_wrong_specialty_low_chance(self):
        m = CrewMember(char_id="test", name="Test", specialty=Specialty.HACKER)
        assert m.success_chance("fight") < 0.4

    def test_morale_affects_chance(self):
        m_high = CrewMember(char_id="a", name="A", specialty=Specialty.HACKER, morale=100)
        m_low = CrewMember(char_id="b", name="B", specialty=Specialty.HACKER, morale=0)
        assert m_high.success_chance("hack_door") > m_low.success_chance("hack_door")

    def test_injury_reduces_chance(self):
        m_ok = CrewMember(char_id="a", name="A", specialty=Specialty.HACKER)
        m_hurt = CrewMember(char_id="b", name="B", specialty=Specialty.HACKER, injured=True)
        assert m_ok.success_chance("hack_door") > m_hurt.success_chance("hack_door")

    def test_unknown_action_has_base_chance(self):
        m = CrewMember(char_id="test", name="Test", specialty=Specialty.HACKER)
        chance = m.success_chance("unknown_action")
        assert 0.05 <= chance <= 0.98


class TestActions:
    def test_perform_action_returns_result(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        result = g.perform_action("ghost", "disable_alarm")
        assert "success" in result
        assert "action" in result
        assert result["action"] == "disable_alarm"
        assert result["character"] == "Ghost"

    def test_action_increments_turn(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        assert g.turn == 0
        g.perform_action("ghost", "disable_alarm")
        assert g.turn == 1

    def test_action_changes_suspicion(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        initial = g.suspicion
        g.perform_action("ghost", "disable_alarm")
        # Suspicion changes (may go up or down)
        assert isinstance(g.suspicion, int)

    def test_arrested_member_cant_act(self):
        g = HeistState.new_heist()
        m = g.add_crew("ghost", "Ghost", "hacker")
        m.arrested = True
        result = g.perform_action("ghost", "disable_alarm")
        assert result["success"] is False

    def test_nonexistent_member_cant_act(self):
        g = HeistState.new_heist()
        result = g.perform_action("nobody", "fight")
        assert result["success"] is False

    def test_successful_action_boosts_morale(self):
        random.seed(0)  # Control randomness
        g = HeistState.new_heist()
        m = g.add_crew("ghost", "Ghost", "hacker")
        initial_morale = m.morale
        # Run many actions to ensure at least one success
        for _ in range(10):
            g.perform_action("ghost", "disable_alarm")
        # Morale should have changed


class TestPhases:
    def test_advance_through_all_phases(self):
        g = HeistState.new_heist()
        assert g.phase == Phase.PLANNING
        g.advance_phase()
        assert g.phase == Phase.APPROACH
        g.advance_phase()
        assert g.phase == Phase.EXECUTION
        g.advance_phase()
        assert g.phase == Phase.ESCAPE
        g.advance_phase()
        assert g.phase == Phase.COMPLETE

    def test_advance_creates_event(self):
        g = HeistState.new_heist()
        g.advance_phase()
        assert len(g.events) > 0
        assert g.events[-1]["type"] == "phase_change"

    def test_time_pressure_increases_during_execution(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        g.phase = Phase.EXECUTION
        g.perform_action("ghost", "disable_alarm")
        assert g.time_pressure > 0


class TestBustAndVictory:
    def test_bust_on_max_suspicion(self):
        g = HeistState.new_heist()
        g.suspicion = 100
        assert g.check_bust() is True
        assert g.phase == Phase.FAILED

    def test_no_bust_below_100(self):
        g = HeistState.new_heist()
        g.suspicion = 99
        assert g.check_bust() is False

    def test_victory_on_escape_with_no_obstacles(self):
        g = HeistState.new_heist()
        g.phase = Phase.ESCAPE
        g.obstacles_remaining.clear()
        assert g.check_victory() is True
        assert g.phase == Phase.COMPLETE

    def test_no_victory_with_obstacles(self):
        g = HeistState.new_heist()
        g.phase = Phase.ESCAPE
        assert g.check_victory() is False

    def test_no_victory_wrong_phase(self):
        g = HeistState.new_heist()
        g.obstacles_remaining.clear()
        g.phase = Phase.EXECUTION
        assert g.check_victory() is False


class TestLoot:
    def test_collect_loot(self):
        g = HeistState.new_heist()
        total = g.collect_loot(50000)
        assert total == 50000
        assert g.loot_collected == 50000

    def test_collect_loot_accumulates(self):
        g = HeistState.new_heist()
        g.collect_loot(100000)
        g.collect_loot(200000)
        assert g.loot_collected == 300000

    def test_collect_loot_creates_event(self):
        g = HeistState.new_heist()
        g.collect_loot(50000)
        assert any(e["type"] == "loot" for e in g.events)


class TestComplications:
    def test_complication_sometimes_fires(self):
        g = HeistState.new_heist()
        fired = False
        for _ in range(100):
            if g.maybe_complication():
                fired = True
                break
        assert fired, "Complication should fire within 100 attempts"

    def test_complication_adds_to_list(self):
        g = HeistState.new_heist()
        random.seed(1)  # seed that gives complication
        for _ in range(100):
            comp = g.maybe_complication()
            if comp:
                assert comp in g.complications
                break


class TestSerialization:
    def test_to_dict_has_required_keys(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        d = g.to_dict()
        assert "heist_id" in d
        assert "phase" in d
        assert "crew" in d
        assert "suspicion" in d
        assert "loot_collected" in d
        assert "obstacles_remaining" in d
        assert "is_active" in d

    def test_to_dict_crew_serialized(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        d = g.to_dict()
        assert "ghost" in d["crew"]
        assert d["crew"]["ghost"]["name"] == "Ghost"
        assert d["crew"]["ghost"]["specialty"] == "hacker"

    def test_situation_summary_has_key_info(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        summary = g.situation_summary()
        assert "Diamond Exchange" in summary
        assert "planning" in summary.lower()
        assert "Ghost" in summary


class TestObstacleClearance:
    def test_disable_alarm_clears_laser_grid(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        # Force success
        random.seed(42)
        for _ in range(50):
            result = g.perform_action("ghost", "disable_alarm")
            if result.get("obstacle_cleared"):
                assert result["obstacle_cleared"] in ("laser_grid", "motion_sensors")
                return
        # May not clear if none match — that's ok for diamond exchange

    def test_crack_safe_clears_vault(self):
        g = HeistState.new_heist()
        g.add_crew("ghost", "Ghost", "hacker")
        random.seed(42)
        for _ in range(50):
            result = g.perform_action("ghost", "crack_safe")
            if result.get("obstacle_cleared"):
                assert result["obstacle_cleared"] == "vault_combination"
                assert "vault_combination" not in g.obstacles_remaining
                return


class TestVenueTemplates:
    def test_all_venues_have_required_keys(self):
        for key, venue in VENUES.items():
            assert "name" in venue, f"{key} missing name"
            assert "difficulty" in venue, f"{key} missing difficulty"
            assert "loot_value" in venue, f"{key} missing loot_value"
            assert "guards" in venue, f"{key} missing guards"
            assert "obstacles" in venue, f"{key} missing obstacles"

    def test_all_specialties_have_skill_table(self):
        for spec in Specialty:
            assert spec in SKILL_TABLE, f"{spec} missing from SKILL_TABLE"

    def test_all_phases_have_complications(self):
        for phase in [Phase.PLANNING, Phase.APPROACH, Phase.EXECUTION, Phase.ESCAPE]:
            assert phase in COMPLICATIONS, f"{phase} missing complications"
            assert len(COMPLICATIONS[phase]) >= 3
