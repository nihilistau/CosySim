"""Tests for engine.world.territory module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.world.territory import (
    CONTROL_SHIFT_RANGE,
    DEFAULT_CONTROL,
    DISTRICT_NAMES,
    DISTRICT_SCENES,
    DISTRICT_SPECIALIZATIONS,
    FACTION_NAMES,
    FACTION_TRAITS,
    HQ_ROOM_TYPES,
    WAR_THRESHOLD,
    CrewHQ,
    HQRoom,
    TerritoryEvent,
    TerritoryManager,
)


# ──── Fixtures ────

@pytest.fixture
def manager(tmp_path):
    """Create an isolated TerritoryManager with temp persistence."""
    with patch("engine.world.territory._SAVE_DIR", tmp_path):
        mgr = TerritoryManager()
        yield mgr


# ──── HQRoom Tests ────

class TestHQRoom:

    def test_initial_level(self):
        """Room starts at level 1."""
        room = HQRoom(room_type="barracks")
        assert room.level == 1

    def test_bonus_scales_with_level(self):
        """Bonus values scale with level."""
        room = HQRoom(room_type="barracks", level=2)
        bonus = room.get_bonus()
        assert bonus.get("crew_capacity", 0) == 4

    def test_upgrade_cost(self):
        """Upgrade cost increases with level."""
        room = HQRoom(room_type="armory", level=1)
        cost = room.upgrade_cost()
        assert cost is not None
        assert cost > 0

    def test_upgrade_cost_at_max_is_none(self):
        """Max level room returns None upgrade cost."""
        room = HQRoom(room_type="armory", level=3)
        assert room.upgrade_cost() is None

    def test_serialization_roundtrip(self):
        """Room survives to_dict/from_dict."""
        room = HQRoom(room_type="lab", level=2)
        data = room.to_dict()
        restored = HQRoom.from_dict(data)
        assert restored.room_type == "lab"
        assert restored.level == 2


# ──── CrewHQ Tests ────

class TestCrewHQ:

    def test_add_room(self):
        """Adding a valid room type succeeds."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        assert hq.add_room("barracks")
        assert "barracks" in hq.rooms

    def test_add_duplicate_room_fails(self):
        """Cannot add the same room twice."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        hq.add_room("barracks")
        assert not hq.add_room("barracks")

    def test_add_invalid_room_type(self):
        """Invalid room type is rejected."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        assert not hq.add_room("swimming_pool")

    def test_upgrade_room(self):
        """Upgrading an existing room increments level."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        hq.add_room("armory")
        assert hq.upgrade_room("armory")
        assert hq.rooms["armory"].level == 2

    def test_upgrade_max_level_fails(self):
        """Cannot upgrade past max level."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        hq.add_room("armory")
        hq.rooms["armory"].level = 3
        assert not hq.upgrade_room("armory")

    def test_upgrade_nonexistent_room_fails(self):
        """Cannot upgrade a room that doesn't exist."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        assert not hq.upgrade_room("vault")

    def test_get_all_bonuses(self):
        """Aggregate bonuses across all rooms."""
        hq = CrewHQ(crew_id="alpha", district="DOWNTOWN")
        hq.add_room("barracks")
        hq.add_room("vault")
        bonuses = hq.get_all_bonuses()
        assert "crew_capacity" in bonuses
        assert "passive_credits" in bonuses

    def test_serialization_roundtrip(self):
        """HQ survives to_dict/from_dict."""
        hq = CrewHQ(crew_id="alpha", district="TECH_DISTRICT")
        hq.add_room("lab")
        hq.add_room("comms")
        data = hq.to_dict()
        restored = CrewHQ.from_dict(data)
        assert restored.crew_id == "alpha"
        assert restored.district == "TECH_DISTRICT"
        assert "lab" in restored.rooms
        assert "comms" in restored.rooms


# ──── TerritoryEvent Tests ────

class TestTerritoryEvent:

    def test_serialization(self):
        """TerritoryEvent serializes correctly."""
        event = TerritoryEvent(
            district="DOWNTOWN",
            faction="OmniCorp",
            delta=5.5,
            reason="mission_complete",
            triggered_war=False,
        )
        data = event.to_dict()
        assert data["district"] == "DOWNTOWN"
        assert data["faction"] == "OmniCorp"
        assert data["delta"] == 5.5
        assert not data["triggered_war"]


# ──── TerritoryManager Tests ────

class TestTerritoryManager:

    def test_defaults_initialized(self, manager):
        """All districts have control data on init."""
        for district in DISTRICT_NAMES:
            ctrl = manager.get_district_control(district)
            assert len(ctrl) > 0

    def test_control_sums_to_100(self, manager):
        """Each district's faction control should sum to ~100%."""
        for district in DISTRICT_NAMES:
            ctrl = manager.get_district_control(district)
            total = sum(ctrl.values())
            assert abs(total - 100.0) < 0.5, (
                f"{district} control sums to {total}, expected ~100"
            )

    def test_get_dominant_faction(self, manager):
        """get_dominant_faction returns the highest-control faction."""
        dominant, pct = manager.get_dominant_faction("HIGHRISE")
        assert dominant in FACTION_NAMES
        assert pct > 0

    def test_shift_control_basic(self, manager):
        """Basic control shift changes faction percentage."""
        ctrl_before = manager.get_district_control("DOWNTOWN")
        omni_before = ctrl_before.get("OmniCorp", 0)

        event = manager.shift_control("DOWNTOWN", "OmniCorp", 5.0, reason="test")
        assert event.delta > 0

        ctrl_after = manager.get_district_control("DOWNTOWN")
        assert ctrl_after["OmniCorp"] > omni_before

    def test_shift_control_redistributes(self, manager):
        """Control gained by one faction is lost by others."""
        ctrl_before = manager.get_district_control("COMBAT_ZONE")
        total_before = sum(ctrl_before.values())

        manager.shift_control("COMBAT_ZONE", "BlackMarket", 5.0)
        ctrl_after = manager.get_district_control("COMBAT_ZONE")
        total_after = sum(ctrl_after.values())

        assert abs(total_after - 100.0) < 0.5

    def test_shift_control_source_faction(self, manager):
        """Control can be taken specifically from a source faction."""
        manager.shift_control(
            "TECH_DISTRICT", "Ghost_Net", 5.0,
            source_faction="NeoTech",
        )
        ctrl = manager.get_district_control("TECH_DISTRICT")
        assert abs(sum(ctrl.values()) - 100.0) < 0.5

    def test_shift_control_war_trigger(self, manager):
        """Shifting more than WAR_THRESHOLD triggers war."""
        event = manager.shift_control(
            "DOWNTOWN", "DeepState", WAR_THRESHOLD + 1.0,
            reason="massive_attack",
        )
        assert event.triggered_war

    def test_shift_control_below_war_threshold(self, manager):
        """Shifting below threshold does not trigger war."""
        event = manager.shift_control(
            "DOWNTOWN", "DeepState", WAR_THRESHOLD - 5.0,
            reason="small_skirmish",
        )
        assert not event.triggered_war

    def test_control_cannot_go_below_zero(self, manager):
        """Faction control cannot go negative."""
        for _ in range(20):
            manager.shift_control("OUTSKIRTS", "OmniCorp", -5.0)
        ctrl = manager.get_district_control("OUTSKIRTS")
        for faction, pct in ctrl.items():
            assert pct >= 0.0, f"{faction} in OUTSKIRTS has negative control: {pct}"

    def test_establish_hq(self, manager):
        """Establishing HQ creates a CrewHQ."""
        hq = manager.establish_hq("DOWNTOWN", "alpha_squad")
        assert hq.district == "DOWNTOWN"
        assert hq.crew_id == "alpha_squad"

    def test_establish_hq_returns_existing(self, manager):
        """Establishing HQ twice returns the same HQ."""
        hq1 = manager.establish_hq("DOWNTOWN", "alpha_squad")
        hq2 = manager.establish_hq("HIGHRISE", "alpha_squad")
        assert hq1 is hq2
        assert hq2.district == "DOWNTOWN"

    def test_get_hq(self, manager):
        """get_hq retrieves existing HQ."""
        manager.establish_hq("TECH_DISTRICT", "beta_squad")
        hq = manager.get_hq("beta_squad")
        assert hq is not None
        assert hq.district == "TECH_DISTRICT"

    def test_get_hq_missing(self, manager):
        """get_hq returns None for unknown crew."""
        assert manager.get_hq("nonexistent") is None

    def test_build_room(self, manager):
        """Building a room in HQ works."""
        manager.establish_hq("DOWNTOWN", "alpha_squad")
        assert manager.build_room("alpha_squad", "barracks")
        hq = manager.get_hq("alpha_squad")
        assert "barracks" in hq.rooms

    def test_upgrade_room(self, manager):
        """Upgrading a room in HQ works."""
        manager.establish_hq("DOWNTOWN", "alpha_squad")
        manager.build_room("alpha_squad", "armory")
        assert manager.upgrade_room("alpha_squad", "armory")
        hq = manager.get_hq("alpha_squad")
        assert hq.rooms["armory"].level == 2

    def test_relocate_hq(self, manager):
        """Relocating HQ clears rooms and moves to new district."""
        manager.establish_hq("DOWNTOWN", "alpha_squad")
        manager.build_room("alpha_squad", "barracks")
        assert manager.relocate_hq("alpha_squad", "TECH_DISTRICT")
        hq = manager.get_hq("alpha_squad")
        assert hq.district == "TECH_DISTRICT"
        assert len(hq.rooms) == 0

    def test_relocate_hq_invalid_district(self, manager):
        """Cannot relocate to invalid district."""
        manager.establish_hq("DOWNTOWN", "alpha_squad")
        assert not manager.relocate_hq("alpha_squad", "ATLANTIS")

    def test_simulate_faction_tick(self, manager):
        """Faction tick produces events (non-deterministic)."""
        events = manager.simulate_faction_tick()
        assert isinstance(events, list)

    def test_faction_ranking(self, manager):
        """Faction ranking returns all factions sorted."""
        rankings = manager.get_faction_ranking()
        assert len(rankings) == len(FACTION_NAMES)
        totals = [total for _, total in rankings]
        assert totals == sorted(totals, reverse=True)

    def test_get_faction_total_control(self, manager):
        """Total control sums across all districts."""
        total = manager.get_faction_total_control("OmniCorp")
        assert total > 0

    def test_get_district_specialization(self, manager):
        """Specialization data returned for valid district."""
        spec = manager.get_district_specialization("TECH_DISTRICT")
        assert spec["type"] == "technology"
        assert spec["bonus_skill"] == "hacking"

    def test_territory_summary(self, manager):
        """Territory summary is a formatted string."""
        summary = manager.get_territory_summary()
        assert "TERRITORY CONTROL" in summary
        assert "DOWNTOWN" in summary

    def test_event_history(self, manager):
        """Events are recorded in history."""
        manager.shift_control("DOWNTOWN", "OmniCorp", 3.0, reason="test")
        history = manager.get_event_history()
        assert len(history) > 0

    def test_persistence_roundtrip(self, tmp_path):
        """State persists and reloads across manager instances."""
        with patch("engine.world.territory._SAVE_DIR", tmp_path):
            mgr1 = TerritoryManager()
            mgr1.shift_control("DOWNTOWN", "Ghost_Net", 5.0, reason="test")
            ghost_before = mgr1.get_district_control("DOWNTOWN")["Ghost_Net"]

            mgr2 = TerritoryManager()
            ghost_after = mgr2.get_district_control("DOWNTOWN")["Ghost_Net"]
            assert abs(ghost_after - ghost_before) < 0.5


# ──── Constants Validation ────

class TestConstants:

    def test_all_districts_have_default_control(self):
        """Every district has default faction control defined."""
        for district in DISTRICT_NAMES:
            assert district in DEFAULT_CONTROL
            ctrl = DEFAULT_CONTROL[district]
            total = sum(ctrl.values())
            assert abs(total - 100.0) < 0.5

    def test_all_districts_have_scenes(self):
        """Every district maps to at least one scene."""
        for district in DISTRICT_NAMES:
            assert district in DISTRICT_SCENES
            assert len(DISTRICT_SCENES[district]) >= 1

    def test_all_districts_have_specializations(self):
        """Every district has economic specialization data."""
        for district in DISTRICT_NAMES:
            assert district in DISTRICT_SPECIALIZATIONS
            spec = DISTRICT_SPECIALIZATIONS[district]
            assert "type" in spec
            assert "bonus_skill" in spec

    def test_all_factions_have_traits(self):
        """Every faction has personality traits."""
        for faction in FACTION_NAMES:
            assert faction in FACTION_TRAITS
            traits = FACTION_TRAITS[faction]
            assert "aggression" in traits
            assert "expansion_rate" in traits
            assert "preferred_districts" in traits

    def test_all_room_types_have_data(self):
        """Every HQ room type has cost and bonus data."""
        for room, data in HQ_ROOM_TYPES.items():
            assert "cost" in data
            assert "bonus" in data
            assert "max_level" in data
            assert data["max_level"] >= 1
