"""Tests for The Realm scene — game state, skill checks, murder mystery."""
import pytest
import time

from content.scenes.realm.realm_state import (
    DIRECTOR_PERSONALITIES,
    MURDER_NPCS,
    MURDER_ROOMS,
    MURDER_WEAPONS,
    MurderMysteryState,
    RealmGameState,
    SKILL_TREE,
)


class TestRealmGameState:
    def setup_method(self):
        self.state = RealmGameState("test_realm")

    def test_initial_state(self):
        assert self.state.session_id == "test_realm"
        assert self.state.player_stats["hp"] == 100
        assert len(self.state.inventory) == 3  # starter items
        assert self.state.director_patience == 100.0
        assert not self.state.ended

    def test_to_dict(self):
        d = self.state.to_dict()
        assert d["session_id"] == "test_realm"
        assert "player_stats" in d
        assert "inventory" in d
        assert "director_patience" in d

    def test_set_director(self):
        result = self.state.set_director("aggressive")
        assert result["personality"] == "aggressive"
        assert self.state.director_personality == "aggressive"
        assert self.state.director_patience == 100.0

    def test_set_director_invalid_falls_back(self):
        self.state.set_director("nonexistent")
        assert self.state.director_personality == "random"

    def test_decay_patience(self):
        p1 = self.state.decay_patience(10.0)
        assert p1 == 90.0
        assert self.state.director_patience == 90.0

    def test_patience_floors_at_zero(self):
        self.state.decay_patience(200.0)
        assert self.state.director_patience == 0.0

    def test_adjust_stat(self):
        val = self.state.adjust_stat("strength", 5)
        assert val == 15
        assert self.state.player_stats["strength"] == 15

    def test_stat_capped_by_max(self):
        val = self.state.adjust_stat("hp", 9999)
        assert val == self.state.player_stats["max_hp"]

    def test_stat_floors_at_zero(self):
        val = self.state.adjust_stat("hp", -9999)
        assert val == 0

    def test_take_damage(self):
        hp, dead = self.state.take_damage(30)
        assert hp == 70
        assert not dead

    def test_take_lethal_damage(self):
        hp, dead = self.state.take_damage(9999)
        assert hp == 0
        assert dead
        assert self.state.ended
        assert self.state.outcome == "death"

    def test_heal(self):
        self.state.take_damage(50)
        hp = self.state.heal(25)
        assert hp == 75

    def test_gain_xp_level_up(self):
        result = self.state.gain_xp(100)
        assert result["leveled_up"]
        assert result["level"] == 2
        assert self.state.player_stats["max_hp"] == 110  # +10 per level

    def test_skill_check_structure(self):
        result = self.state.skill_check("persuasion")
        assert "roll" in result
        assert "dc" in result
        assert "success" in result
        assert "skill" in result
        assert result["skill"] == "persuasion"

    def test_skill_check_unknown(self):
        result = self.state.skill_check("flying")
        assert not result["success"]
        assert result["reason"] == "unknown skill"

    def test_add_remove_item(self):
        self.state.add_item({"id": "magic_ring", "name": "Magic Ring", "type": "misc"})
        assert self.state.has_item("magic_ring")
        removed = self.state.remove_item("magic_ring")
        assert removed is not None
        assert not self.state.has_item("magic_ring")

    def test_remove_nonexistent_item(self):
        result = self.state.remove_item("ghost_item")
        assert result is None

    def test_assistant_steal(self):
        item = self.state.assistant_steal("Settings Button")
        assert item["type"] == "fourth_wall"
        assert "STOLEN" in item["name"]
        assert self.state.has_item(item["id"])
        assert "Settings Button" in self.state.assistant_stolen_items

    def test_desperation_dice(self):
        result = self.state.desperation_dice()
        assert result["success"]
        assert result["new_max_hp"] == 90
        assert self.state.player_stats["max_hp"] == 90

    def test_desperation_dice_too_low(self):
        self.state.player_stats["max_hp"] = 15
        result = self.state.desperation_dice()
        assert not result["success"]

    def test_advance_turn(self):
        turn = self.state.advance_turn("You enter a dark cave.", [{"id": "a", "text": "Proceed"}])
        assert turn == 1
        assert self.state.current_scene_text == "You enter a dark cave."
        assert len(self.state.story_log) == 1

    def test_end_game(self):
        result = self.state.end_game("victory")
        assert self.state.ended
        assert result["outcome"] == "victory"

    def test_mutiny(self):
        self.state.trigger_mutiny(0.5)
        assert self.state.is_mutiny_active()
        assert self.state.director_locked_out
        time.sleep(0.6)
        assert not self.state.is_mutiny_active()

    def test_end_mutiny(self):
        self.state.trigger_mutiny(60)
        self.state.end_mutiny()
        assert not self.state.is_mutiny_active()
        assert not self.state.director_locked_out

    def test_memory_echo_no_deaths(self):
        assert self.state.get_echo_hint() is None

    def test_memory_echo_with_deaths(self):
        self.state.record_death("fell into lava", 5)
        hint = self.state.get_echo_hint()
        assert hint is not None
        assert "lava" in hint


class TestMurderMystery:
    def setup_method(self):
        self.murder = MurderMysteryState()

    def test_initial_state(self):
        assert not self.murder.active
        assert self.murder.phase == "setup"
        assert len(self.murder.npcs) == 5
        assert self.murder.accusations_remaining == 3
        assert self.murder.weapon in MURDER_WEAPONS
        assert self.murder.room in MURDER_ROOMS

    def test_start_party(self):
        result = self.murder.start_party_phase()
        assert self.murder.active
        assert self.murder.phase == "party"
        assert result["time_limit"] == 300

    def test_investigation_phase(self):
        self.murder.start_party_phase()
        result = self.murder.start_investigation_phase()
        assert self.murder.phase == "investigation"
        assert result["time_limit"] == 900

    def test_add_clue(self):
        self.murder.add_clue({"type": "fingerprint", "location": "kitchen"})
        assert len(self.murder.clues_found) == 1

    def test_interrogate(self):
        self.murder.interrogate("lord_ashford", "Where were you?", "In the study.")
        assert len(self.murder.interrogations) == 1

    def test_correct_accusation(self):
        result = self.murder.accuse(self.murder.murderer_id, self.murder.weapon, self.murder.room)
        assert result["won"]
        assert result["correct_suspect"]
        assert result["correct_weapon"]
        assert result["correct_room"]
        assert self.murder.resolved
        assert self.murder.detective_won

    def test_wrong_accusation(self):
        result = self.murder.accuse("wrong_id", "wrong_weapon", "wrong_room")
        assert not result["won"]
        assert result["remaining"] == 2

    def test_three_wrong_accusations_lose(self):
        for _ in range(3):
            result = self.murder.accuse("wrong", "wrong", "wrong")
        assert self.murder.resolved
        assert not self.murder.detective_won

    def test_to_dict(self):
        self.murder.start_party_phase()
        d = self.murder.to_dict()
        assert d["active"]
        assert d["phase"] == "party"
        assert d["accusations_remaining"] == 3
        assert len(d["npcs"]) == 4  # 5 minus victim

    def test_director_brief(self):
        self.murder.start_party_phase()
        brief = self.murder.get_director_brief()
        assert "MURDER MYSTERY" in brief
        assert self.murder.weapon in brief
        assert self.murder.room in brief


class TestDirectorPersonalities:
    def test_all_personalities_valid(self):
        for key, info in DIRECTOR_PERSONALITIES.items():
            assert "label" in info
            assert "patience_decay" in info
            assert "difficulty_mod" in info
            assert "style" in info

    def test_personality_affects_skill_check(self):
        state = RealmGameState()
        state.set_director("aggressive")
        result = state.skill_check("persuasion")
        # Aggressive adds +2 to DC
        assert result["dc"] > 12  # base DC is 12, +2 from aggressive

    def test_passive_lowers_dc(self):
        state = RealmGameState()
        state.set_director("passive")
        result = state.skill_check("persuasion")
        # Passive has -1 difficulty mod
        assert result["dc"] == 11  # 12 - 1
