"""Tests for engine.world.inventory and engine.world.crew."""
from __future__ import annotations

import json
import pytest
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch


# ──── InventoryManager tests ──────────────────────────────────────────────────

class TestInventoryManager:
    """Tests for InventoryManager functionality."""

    @pytest.fixture(autouse=True)
    def fresh_manager(self, tmp_path):
        """Create a fresh InventoryManager with temp save path for each test."""
        from engine.world import inventory as inv_module
        save_path = tmp_path / "inventory.json"
        inv_module.InventoryManager._SAVE_PATH = save_path
        inv_module.InventoryManager._instance = None
        yield
        inv_module.InventoryManager._instance = None

    def _get(self):
        from engine.world.inventory import get_inventory
        return get_inventory()

    def test_singleton(self):
        inv1 = self._get()
        inv2 = self._get()
        assert inv1 is inv2

    def test_add_item_known(self):
        inv = self._get()
        item = inv.add_item("stim_pack", quantity=2)
        assert item is not None
        assert item.item_id == "stim_pack"
        assert item.quantity == 2

    def test_add_item_stackable_increments(self):
        inv = self._get()
        inv.add_item("stim_pack", quantity=1)
        inv.add_item("stim_pack", quantity=3)
        assert inv.get_item("stim_pack").quantity == 4

    def test_add_item_returns_none_when_full(self):
        inv = self._get()
        inv._max_slots = 2
        inv.add_item("neural_jack")
        inv.add_item("reflex_booster")
        result = inv.add_item("optic_implant")
        assert result is None

    def test_has_item_true(self):
        inv = self._get()
        inv.add_item("health_booster", quantity=3)
        assert inv.has_item("health_booster", quantity=3) is True
        assert inv.has_item("health_booster", quantity=4) is False

    def test_has_item_false_for_missing(self):
        inv = self._get()
        assert inv.has_item("nonexistent") is False

    def test_remove_item_success(self):
        inv = self._get()
        inv.add_item("stim_pack", quantity=3)
        ok = inv.remove_item("stim_pack", quantity=2)
        assert ok is True
        assert inv.get_item("stim_pack").quantity == 1

    def test_remove_item_full_removes_entry(self):
        inv = self._get()
        inv.add_item("stim_pack", quantity=1)
        inv.remove_item("stim_pack", quantity=1)
        assert inv.get_item("stim_pack") is None

    def test_remove_item_insufficient_quantity(self):
        inv = self._get()
        inv.add_item("stim_pack", quantity=1)
        ok = inv.remove_item("stim_pack", quantity=5)
        assert ok is False

    def test_remove_item_not_found(self):
        inv = self._get()
        ok = inv.remove_item("nonexistent")
        assert ok is False

    def test_equip_item(self):
        inv = self._get()
        inv.add_item("neural_jack")
        ok = inv.equip("neural_jack", "cyberware_1")
        assert ok is True
        assert inv.get_item("neural_jack").equipped is True
        assert inv.get_item("neural_jack").equipped_slot == "cyberware_1"
        assert inv.get_equipped()["cyberware_1"] == "neural_jack"

    def test_equip_replaces_existing(self):
        inv = self._get()
        inv.add_item("neural_jack")
        inv.add_item("subdermal_armor")
        inv.equip("neural_jack", "cyberware_1")
        inv.equip("subdermal_armor", "cyberware_1")
        # Old item should be unequipped
        assert inv.get_item("neural_jack").equipped is False
        assert inv.get_equipped()["cyberware_1"] == "subdermal_armor"

    def test_equip_invalid_slot(self):
        inv = self._get()
        inv.add_item("neural_jack")
        ok = inv.equip("neural_jack", "invalid_slot")
        assert ok is False

    def test_equip_item_not_in_inventory(self):
        inv = self._get()
        ok = inv.equip("neural_jack", "cyberware_1")
        assert ok is False

    def test_unequip(self):
        inv = self._get()
        inv.add_item("neural_jack")
        inv.equip("neural_jack", "cyberware_1")
        ok = inv.unequip("neural_jack")
        assert ok is True
        assert inv.get_item("neural_jack").equipped is False
        assert inv.get_equipped()["cyberware_1"] is None

    def test_get_items_by_category(self):
        inv = self._get()
        inv.add_item("neural_jack")
        inv.add_item("stim_pack")
        inv.add_item("optic_implant")
        cyberware = inv.get_items_by_category("cyberware")
        ids = {item.item_id for item in cyberware}
        assert "neural_jack" in ids
        assert "optic_implant" in ids
        assert "stim_pack" not in ids

    def test_to_hud_dict_max_12(self):
        inv = self._get()
        # Add 15 unique items (using drugs/food which are stackable but unique item_ids)
        for i, item_id in enumerate([
            "stim_pack", "health_booster", "focus_chip", "synth_ramen",
            "protein_bar", "corp_ration", "encrypted_file", "corp_keycard",
            "ghost_net_token", "ice_breaker_v1", "shadow_protocol",
            "data_mine", "tracer_kill", "black_lotus", "monofilament",
        ]):
            inv.add_item(item_id)
        hud = inv.to_hud_dict()
        assert len(hud) <= 12

    def test_to_dict_shape(self):
        inv = self._get()
        inv.add_item("stim_pack")
        d = inv.to_dict()
        assert "items" in d
        assert "equipment" in d
        assert "item_count" in d
        assert "max_slots" in d

    def test_persistence(self, tmp_path):
        from engine.world import inventory as inv_module
        save_path = tmp_path / "inv_persist.json"
        inv_module.InventoryManager._SAVE_PATH = save_path
        inv_module.InventoryManager._instance = None

        inv = inv_module.get_inventory()
        inv.add_item("stim_pack", quantity=5)
        inv.equip("neural_jack", "cyberware_1") if inv.add_item("neural_jack") else None

        # Reset singleton and reload
        inv_module.InventoryManager._instance = None
        inv2 = inv_module.get_inventory()
        assert inv2.has_item("stim_pack", quantity=5)

    def test_thread_safety(self):
        inv = self._get()
        errors = []

        def add_items():
            try:
                for _ in range(20):
                    inv.add_item("stim_pack", quantity=1)
                    inv.remove_item("stim_pack", quantity=1)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=add_items) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ──── CrewManager tests ───────────────────────────────────────────────────────

class TestCrewManager:
    """Tests for CrewManager functionality."""

    @pytest.fixture(autouse=True)
    def fresh_manager(self, tmp_path):
        """Create a fresh CrewManager with temp save path for each test."""
        from engine.world import crew as crew_module
        save_path = tmp_path / "crew.json"
        crew_module.CrewManager._SAVE_PATH = save_path
        crew_module.CrewManager._instance = None
        yield
        crew_module.CrewManager._instance = None

    def _get(self):
        from engine.world.crew import get_crew_manager
        return get_crew_manager()

    def _mock_relationship(self, score: float = 80.0):
        """Patch get_player_profile in crew module so relationship checks return *score*."""
        mock_rel = MagicMock()
        mock_rel.score = score
        mock_profile = MagicMock()
        mock_profile.relationships = {"lola": mock_rel, "viktor": mock_rel, "aria": mock_rel}
        mock_profile.add_crew_member = MagicMock()
        mock_profile.set_relationship_type = MagicMock()
        return patch(
            "engine.world.crew.get_player_profile",
            return_value=mock_profile,
        )

    def test_singleton(self):
        cm1 = self._get()
        cm2 = self._get()
        assert cm1 is cm2

    def test_recruit_success(self):
        cm = self._get()
        with self._mock_relationship(score=80):
            ok, msg = cm.recruit("lola", role="fixer", notes="Joined after casino job")
        assert ok is True
        assert "lola" in msg.lower() or "fixer" in msg.lower()
        assert cm.get_member("lola") is not None

    def test_recruit_insufficient_relationship(self):
        cm = self._get()
        with self._mock_relationship(score=20):
            ok, msg = cm.recruit("lola", role="fixer")
        assert ok is False
        assert "trust" in msg.lower() or "relationship" in msg.lower() or "score" in msg.lower()

    def test_recruit_skip_check(self):
        cm = self._get()
        ok, msg = cm.recruit("aria", role="tech", skip_check=True)
        assert ok is True
        assert cm.get_member("aria") is not None

    def test_recruit_duplicate(self):
        cm = self._get()
        cm.recruit("aria", role="tech", skip_check=True)
        ok, msg = cm.recruit("aria", role="fixer", skip_check=True)
        assert ok is False
        assert "already" in msg.lower()

    def test_recruit_max_size(self):
        from engine.world.crew import _MAX_CREW_SIZE
        cm = self._get()
        for i in range(_MAX_CREW_SIZE):
            cm.recruit(f"npc_{i}", skip_check=True)
        ok, msg = cm.recruit("overflow_npc", skip_check=True)
        assert ok is False
        assert "full" in msg.lower()

    def test_dismiss(self):
        cm = self._get()
        cm.recruit("aria", skip_check=True)
        ok = cm.dismiss("aria", reason="mission complete")
        assert ok is True
        assert cm.get_member("aria") is None

    def test_dismiss_not_in_crew(self):
        cm = self._get()
        ok = cm.dismiss("nobody")
        assert ok is False

    def test_adjust_loyalty_positive(self):
        cm = self._get()
        cm.recruit("aria", skip_check=True)
        val = cm.adjust_loyalty("aria", delta=20.0, reason="saved the crew")
        assert val == pytest.approx(70.0)

    def test_adjust_loyalty_clamped(self):
        cm = self._get()
        cm.recruit("aria", skip_check=True)
        val = cm.adjust_loyalty("aria", delta=200.0)
        assert val == pytest.approx(100.0)

    def test_adjust_loyalty_not_in_crew(self):
        cm = self._get()
        val = cm.adjust_loyalty("nobody", delta=10.0)
        assert val is None

    def test_start_operation_success(self):
        cm = self._get()
        cm.recruit("aria", role="hacker", skip_check=True)
        ok, msg = cm.start_operation(
            op_type="hack",
            assigned_crew=["aria"],
            label="Corp server breach",
            duration_secs=10,
            reward_credits=500,
        )
        assert ok is True
        assert cm.get_member("aria").available is False

    def test_start_operation_insufficient_crew(self):
        cm = self._get()
        ok, msg = cm.start_operation(op_type="heist", assigned_crew=["lone_wolf"])
        assert ok is False
        assert "require" in msg.lower() or "minimum" in msg.lower() or "at least" in msg.lower()

    def test_start_operation_unavailable_crew(self):
        cm = self._get()
        cm.recruit("aria", role="hacker", skip_check=True)
        cm.start_operation(op_type="hack", assigned_crew=["aria"], duration_secs=3600)
        ok, msg = cm.start_operation(op_type="hack", assigned_crew=["aria"], duration_secs=3600)
        assert ok is False
        assert "not available" in msg.lower() or "unavailable" in msg.lower()

    def test_check_operations_completes_immediately(self):
        # v1.60.0: operations now resolve via a graded skill-check (success/
        # partial/failure) instead of always paying full reward. Assert the
        # durable contract — a 0-duration op is picked up and resolved, the
        # member is freed, and the reward matches the rolled outcome tier.
        cm = self._get()
        cm.recruit("aria", role="hacker", skip_check=True)
        m = cm.get_member("aria")
        m.level = 5
        m.loyalty = 100  # maximise odds for a stable (usually-success) roll
        cm.start_operation(
            op_type="hack",
            assigned_crew=["aria"],
            duration_secs=0,
            reward_credits=100,
            reward_xp=25,
        )
        import time
        time.sleep(0.01)
        results = cm.check_operations()
        assert len(results) == 1
        r = results[0]
        assert r["outcome"] in ("success", "partial", "failure")
        # member is always freed when an operation resolves
        assert cm.get_member("aria").available is True
        # full reward only on a clean success; never negative
        assert r["credits_earned"] >= 0
        if r["outcome"] == "success":
            assert r["credits_earned"] == 100

    def test_crew_member_xp_and_level_up(self):
        from engine.world.crew import CrewMember
        m = CrewMember(character_id="aria")
        levelled = m.add_xp(100)
        assert levelled is True
        assert m.level == 2
        assert m.xp == 0

    def test_crew_member_no_level_up(self):
        from engine.world.crew import CrewMember
        m = CrewMember(character_id="aria")
        levelled = m.add_xp(50)
        assert levelled is False
        assert m.level == 1
        assert m.xp == 50

    def test_set_crew_name(self):
        cm = self._get()
        cm.set_crew_name("The Ghost Circuit")
        assert cm._crew_name == "The Ghost Circuit"

    def test_to_dict_shape(self):
        cm = self._get()
        cm.recruit("aria", skip_check=True)
        d = cm.to_dict()
        assert "crew_name" in d
        assert "members" in d
        assert "member_count" in d
        assert len(d["members"]) == 1

    def test_to_hud_dict(self):
        cm = self._get()
        cm.recruit("aria", role="tech", skip_check=True)
        hud = cm.to_hud_dict()
        assert len(hud) == 1
        assert hud[0]["id"] == "aria"
        assert hud[0]["role"] == "tech"
        assert "loyalty" in hud[0]

    def test_persistence(self, tmp_path):
        from engine.world import crew as crew_module
        save_path = tmp_path / "crew_persist.json"
        crew_module.CrewManager._SAVE_PATH = save_path
        crew_module.CrewManager._instance = None

        cm = crew_module.get_crew_manager()
        cm.recruit("aria", role="hacker", skip_check=True)
        cm.set_crew_name("Test Crew")

        crew_module.CrewManager._instance = None
        cm2 = crew_module.get_crew_manager()
        assert cm2.get_member("aria") is not None
        assert cm2._crew_name == "Test Crew"


# ──── Skill function tests ────────────────────────────────────────────────────

class TestInventorySkills:
    """Smoke tests for inventory skill functions."""

    @pytest.fixture(autouse=True)
    def fresh_inventory(self, tmp_path):
        from engine.world import inventory as inv_module
        inv_module.InventoryManager._SAVE_PATH = tmp_path / "inv.json"
        inv_module.InventoryManager._instance = None
        yield
        inv_module.InventoryManager._instance = None

    def test_inventory_list_empty(self):
        from engine.skills.builtin.inventory_skills import inventory_list
        result = inventory_list()
        assert "empty" in result.lower()

    def test_inventory_add_and_list(self):
        from engine.skills.builtin.inventory_skills import inventory_add, inventory_list
        inventory_add("stim_pack", quantity=2)
        result = inventory_list()
        assert "stim" in result.lower() or "Stim" in result

    def test_inventory_has(self):
        from engine.skills.builtin.inventory_skills import inventory_add, inventory_has
        inventory_add("health_booster", quantity=3)
        assert "Yes" in inventory_has("health_booster", quantity=3)
        assert "No" in inventory_has("health_booster", quantity=10)

    def test_inventory_catalog_all(self):
        from engine.skills.builtin.inventory_skills import inventory_catalog
        result = inventory_catalog()
        assert "catalog" in result.lower()
        assert "stim" in result.lower() or "neural" in result.lower()

    def test_inventory_catalog_filtered(self):
        from engine.skills.builtin.inventory_skills import inventory_catalog
        result = inventory_catalog(category="drug")
        assert "stim" in result.lower() or "chem" in result.lower()


class TestCrewSkills:
    """Smoke tests for crew skill functions."""

    @pytest.fixture(autouse=True)
    def fresh_crew(self, tmp_path):
        from engine.world import crew as crew_module
        crew_module.CrewManager._SAVE_PATH = tmp_path / "crew.json"
        crew_module.CrewManager._instance = None
        yield
        crew_module.CrewManager._instance = None

    def test_crew_status_empty(self):
        from engine.skills.builtin.crew_skills import crew_status
        result = crew_status()
        assert "no crew" in result.lower()

    def test_crew_recruit_and_status(self):
        from engine.skills.builtin.crew_skills import crew_recruit, crew_status
        mock_rel = MagicMock()
        mock_rel.score = 80.0
        mock_profile = MagicMock()
        mock_profile.relationships = {"lola": mock_rel}
        mock_profile.add_crew_member = MagicMock()
        mock_profile.set_relationship_type = MagicMock()
        with patch("engine.world.crew.get_player_profile", return_value=mock_profile):
            result = crew_recruit("lola", role="fixer", notes="test")
        assert "lola" in result.lower() or "fixer" in result.lower()
        status = crew_status()
        assert "lola" in status.upper() or "LOLA" in status

    def test_crew_can_recruit(self):
        from engine.skills.builtin.crew_skills import crew_can_recruit
        mock_rel = MagicMock()
        mock_rel.score = 80.0
        mock_profile = MagicMock()
        mock_profile.relationships = {"aria": mock_rel}
        mock_profile.add_crew_member = MagicMock()
        with patch("engine.world.crew.get_player_profile", return_value=mock_profile):
            result = crew_can_recruit("aria")
        assert "CAN" in result or "can" in result

    def test_crew_set_name(self):
        from engine.skills.builtin.crew_skills import crew_set_name
        result = crew_set_name("The Ghost Circuit")
        assert "Ghost Circuit" in result
