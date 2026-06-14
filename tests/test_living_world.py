"""Tests for Phase 5 — Living World systems.

Covers Market, NPC Routines, Faction AI, Living World orchestrator,
and Living World MCP skills.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ════════════════════════════════════════════════════════════════════════════
# Market
# ════════════════════════════════════════════════════════════════════════════

class TestGood:
    """Good dataclass and price calculation."""

    def test_current_price_balanced(self):
        from engine.world.market import Good
        g = Good(id="x", name="X", category="tech", base_price=100,
                 supply=50, demand=50)
        assert g.current_price == 100

    def test_current_price_high_demand(self):
        from engine.world.market import Good
        g = Good(id="x", name="X", category="tech", base_price=100,
                 supply=30, demand=80)
        assert g.current_price == 150

    def test_current_price_high_supply(self):
        from engine.world.market import Good
        g = Good(id="x", name="X", category="tech", base_price=100,
                 supply=90, demand=30)
        assert g.current_price == 40

    def test_current_price_floor(self):
        from engine.world.market import Good
        g = Good(id="x", name="X", category="tech", base_price=10,
                 supply=100, demand=0)
        assert g.current_price >= 1

    def test_to_dict_includes_current_price(self):
        from engine.world.market import Good
        g = Good(id="x", name="X", category="tech", base_price=100)
        d = g.to_dict()
        assert "current_price" in d
        assert d["id"] == "x"


class TestMarketCore:
    """Market engine initialization and catalog."""

    @pytest.fixture
    def market(self, tmp_path):
        from engine.world.market import Market
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            m = Market()
            yield m

    def test_seed_goods(self, market):
        goods = market.get_goods()
        assert len(goods) >= 25  # 30 goods in catalog

    def test_seed_shops(self, market):
        shops = market.get_shops()
        assert len(shops) >= 10  # 12 shops in templates

    def test_filter_by_category(self, market):
        weapons = market.get_goods("weapons")
        assert all(g["category"] == "weapons" for g in weapons)
        assert len(weapons) >= 4

    def test_get_good(self, market):
        g = market.get_good("stim_pack")
        assert g is not None
        assert g["name"] == "Stim Pack"

    def test_get_good_nonexistent(self, market):
        assert market.get_good("nonexistent") is None

    def test_get_shops_by_district(self, market):
        shops = market.get_shops("DOWNTOWN")
        assert len(shops) >= 2
        assert all(s["district"] == "DOWNTOWN" for s in shops)

    def test_get_prices(self, market):
        prices = market.get_prices("DOWNTOWN")
        assert len(prices) > 0
        for p in prices:
            assert "shop_price" in p
            assert "shop_name" in p
            assert p["district"] == "DOWNTOWN"


class TestMarketTrading:
    """Buy and sell mechanics."""

    @pytest.fixture
    def market(self, tmp_path):
        from engine.world.market import Market
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            m = Market()
            yield m

    def test_buy_success(self, market):
        result = market.buy("DOWNTOWN", "stim_pack", quantity=2)
        assert result["status"] == "ok"
        assert result["action"] == "buy"
        assert result["quantity"] == 2
        assert result["total"] > 0

    def test_buy_unknown_good(self, market):
        result = market.buy("DOWNTOWN", "nonexistent")
        assert result["status"] == "error"

    def test_buy_no_shop(self, market):
        # Contraband not sold in HIGHRISE corp store
        result = market.buy("HIGHRISE", "synth_dust")
        # Could be error or success depending on shop categories
        # Corp Store has tech + luxury, Skyline has consumables
        # synth_dust is contraband — not in either
        assert result["status"] == "error"

    def test_buy_increases_demand(self, market):
        good_before = market.get_good("stim_pack")
        demand_before = good_before["demand"]
        market.buy("DOWNTOWN", "stim_pack", quantity=5)
        good_after = market.get_good("stim_pack")
        assert good_after["demand"] > demand_before

    def test_sell_success(self, market):
        result = market.sell("DOWNTOWN", "stim_pack", quantity=1)
        assert result["status"] == "ok"
        assert result["action"] == "sell"
        assert result["total"] > 0

    def test_sell_unknown_good(self, market):
        result = market.sell("DOWNTOWN", "nonexistent")
        assert result["status"] == "error"

    def test_sell_price_lower_than_buy(self, market):
        buy = market.buy("DOWNTOWN", "stim_pack")
        sell = market.sell("DOWNTOWN", "stim_pack")
        assert sell["unit_price"] < buy["unit_price"]

    def test_trade_history(self, market):
        # v1.59.0: selling now requires possession (economy settlement), so
        # seed the medkit into inventory before selling it.
        from engine.world.inventory import get_inventory
        get_inventory().add_item("medkit", 1)
        market.buy("DOWNTOWN", "stim_pack", quantity=1)
        market.sell("DOWNTOWN", "medkit", quantity=1)
        history = market.get_history(limit=10)
        assert len(history) == 2


class TestMarketSimulation:
    """Tick, events, and territory effects."""

    @pytest.fixture
    def market(self, tmp_path):
        from engine.world.market import Market
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            m = Market()
            yield m

    def test_tick_advances(self, market):
        result = market.tick()
        assert result["tick"] == 1
        assert "price_changes" in result

    def test_multiple_ticks(self, market):
        for _ in range(10):
            market.tick()
        stats = market.get_stats()
        assert stats["tick_count"] == 10

    def test_apply_event_war(self, market):
        weapons_before = [g for g in market.get_goods("weapons")]
        market.apply_event("war")
        weapons_after = [g for g in market.get_goods("weapons")]
        # Demand should have increased
        for before, after in zip(weapons_before, weapons_after):
            assert after["demand"] >= before["demand"]

    def test_apply_event_unknown(self, market):
        # Should not raise
        market.apply_event("nonexistent_event")

    def test_territory_multipliers(self, market):
        control = {
            "DOWNTOWN": {"OmniCorp": 60, "NeoTech": 20, "BlackMarket": 20},
        }
        market.update_territory_multipliers(control)
        # OmniCorp dominates DOWNTOWN → tech/luxury cheaper
        prices = market.get_prices("DOWNTOWN", "tech")
        assert len(prices) > 0  # prices exist

    def test_persistence(self, market, tmp_path):
        from engine.world.market import Market
        market.buy("DOWNTOWN", "stim_pack", quantity=3)
        market.tick()

        # Load fresh from disk
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            m2 = Market()
            assert m2.get_stats()["tick_count"] == 1

    def test_stats(self, market):
        stats = market.get_stats()
        assert stats["total_goods"] >= 25
        assert stats["total_shops"] >= 10
        assert "categories" in stats

    def test_reset(self, market):
        market.buy("DOWNTOWN", "stim_pack")
        market.tick()
        market.reset()
        assert market.get_stats()["tick_count"] == 0
        assert len(market.get_history()) == 0


# ════════════════════════════════════════════════════════════════════════════
# NPC Routines
# ════════════════════════════════════════════════════════════════════════════

class TestNPCRoutineEntry:
    """RoutineEntry and NPCRoutine dataclasses."""

    def test_entry_to_dict(self):
        from engine.world.npc_routines import RoutineEntry
        e = RoutineEntry(time_of_day="evening", location="bar", activity="serving")
        d = e.to_dict()
        assert d["time_of_day"] == "evening"
        assert d["location"] == "bar"

    def test_routine_to_dict(self):
        from engine.world.npc_routines import NPCRoutine, RoutineEntry
        r = NPCRoutine(
            character_id="viktor",
            archetype="bartender",
            schedule=[RoutineEntry("evening", "bar", "serving")],
        )
        d = r.to_dict()
        assert d["character_id"] == "viktor"
        assert len(d["schedule"]) == 1


class TestRoutineManager:
    """RoutineManager lifecycle and NPC registration."""

    @pytest.fixture
    def manager(self):
        from engine.world.npc_routines import RoutineManager
        return RoutineManager()

    def test_register_npc(self, manager):
        routine = manager.register_npc("viktor", "bartender", "COMBAT_ZONE")
        assert routine.character_id == "viktor"
        assert routine.archetype == "bartender"
        assert len(routine.schedule) == 6  # 6 time slots

    def test_register_defaults(self, manager):
        count = manager.register_defaults()
        assert count == 5  # 5 default NPCs

    def test_list_npcs(self, manager):
        manager.register_defaults()
        npcs = manager.list_npcs()
        assert "lola" in npcs
        assert "viktor" in npcs
        assert "aria" in npcs

    def test_get_routine(self, manager):
        manager.register_npc("viktor", "bartender", "DOWNTOWN")
        routine = manager.get_routine("viktor")
        assert routine is not None
        assert routine["archetype"] == "bartender"

    def test_get_routine_nonexistent(self, manager):
        assert manager.get_routine("nobody") is None


class TestRoutineTicking:
    """NPC movement on game clock ticks."""

    @pytest.fixture
    def manager(self):
        from engine.world.npc_routines import RoutineManager
        m = RoutineManager()
        m.register_defaults()
        return m

    def test_tick_moves_npcs(self, manager):
        result = manager.tick("evening")
        assert result["transitions"] >= 0
        assert result["time_of_day"] == "evening"

    def test_tick_same_slot_no_movement(self, manager):
        manager.tick("evening")
        result = manager.tick("evening")
        assert result.get("same_slot", False) is True

    def test_tick_invalid_slot(self, manager):
        result = manager.tick("invalid_time")
        assert "error" in result

    def test_npc_location_after_tick(self, manager):
        manager.tick("evening")
        loc = manager.get_npc_location("viktor")
        assert loc is not None
        assert loc["activity"] != ""

    def test_get_npcs_at(self, manager):
        manager.tick("evening")
        # Viktor (bartender) should be at a bar
        loc = manager.get_npc_location("viktor")
        scene = loc["location"]
        npcs = manager.get_npcs_at(scene)
        assert any(n["character_id"] == "viktor" for n in npcs)


class TestRoutineInterrupts:
    """NPC routine interruption and resumption."""

    @pytest.fixture
    def manager(self):
        from engine.world.npc_routines import RoutineManager
        m = RoutineManager()
        m.register_npc("viktor", "bartender", "DOWNTOWN")
        m.tick("evening")
        return m

    def test_interrupt(self, manager):
        assert manager.interrupt_npc("viktor", "Gang war!", "COMBAT_ZONE")
        loc = manager.get_npc_location("viktor")
        assert loc["interrupted"] is True
        assert "Gang war" in loc["activity"]

    def test_interrupt_nonexistent(self, manager):
        assert manager.interrupt_npc("nobody", "reason") is False

    def test_interrupted_npc_skips_tick(self, manager):
        manager.interrupt_npc("viktor", "Emergency")
        manager.tick("night")
        loc = manager.get_npc_location("viktor")
        assert loc["interrupted"] is True

    def test_resume(self, manager):
        manager.interrupt_npc("viktor", "Emergency")
        assert manager.resume_npc("viktor") is True
        loc = manager.get_npc_location("viktor")
        assert loc["interrupted"] is False

    def test_resume_non_interrupted(self, manager):
        assert manager.resume_npc("viktor") is False

    def test_get_all_locations(self, manager):
        locs = manager.get_all_locations()
        assert "viktor" in locs


class TestRoutineStats:
    """Routine system statistics and reset."""

    def test_stats(self):
        from engine.world.npc_routines import RoutineManager
        m = RoutineManager()
        m.register_defaults()
        stats = m.get_stats()
        assert stats["total_npcs"] == 5
        assert stats["active"] == 5
        assert stats["interrupted"] == 0

    def test_reset(self):
        from engine.world.npc_routines import RoutineManager
        m = RoutineManager()
        m.register_defaults()
        m.reset()
        assert m.get_stats()["total_npcs"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Faction AI
# ════════════════════════════════════════════════════════════════════════════

class TestFactionDecision:
    """FactionDecision dataclass."""

    def test_to_dict(self):
        from engine.world.faction_ai import FactionDecision
        d = FactionDecision(
            faction="OmniCorp",
            action="expand",
            target_district="DOWNTOWN",
            control_delta=3.5,
            narrative="OmniCorp expanded in DOWNTOWN.",
        )
        out = d.to_dict()
        assert out["faction"] == "OmniCorp"
        assert out["control_delta"] == 3.5


class TestFactionAICore:
    """FactionAI decision engine."""

    @pytest.fixture
    def ai(self):
        from engine.world.faction_ai import FactionAI
        from engine.world.territory import DEFAULT_CONTROL
        ai = FactionAI()
        ai.set_control({d: dict(f) for d, f in DEFAULT_CONTROL.items()})
        return ai

    def test_tick_produces_decisions(self, ai):
        result = ai.tick()
        assert len(result["decisions"]) == 6  # 6 factions
        for d in result["decisions"]:
            assert d["faction"] in [
                "OmniCorp", "NeoTech", "BlackMarket",
                "Ghost_Net", "SynthSec", "DeepState",
            ]
            assert d["action"] != ""

    def test_multiple_ticks(self, ai):
        for _ in range(10):
            ai.tick()
        stats = ai.get_stats()
        assert stats["tick_count"] == 10
        assert stats["total_decisions"] == 60  # 6 factions × 10 ticks

    def test_history(self, ai):
        ai.tick()
        history = ai.get_history(limit=20)
        assert len(history) == 6

    def test_history_filter_faction(self, ai):
        ai.tick()
        history = ai.get_history(faction="OmniCorp")
        assert len(history) == 1
        assert history[0]["faction"] == "OmniCorp"

    def test_war_trigger(self, ai):
        # Run many ticks to eventually trigger a war
        for _ in range(50):
            result = ai.tick()
        # Wars may or may not have triggered (probabilistic)
        wars = ai.get_active_wars()
        assert isinstance(wars, dict)

    def test_end_war(self, ai):
        ai._war_active["DOWNTOWN"] = {"attacker": "OmniCorp", "defender": "BlackMarket"}
        assert ai.end_war("DOWNTOWN") is True
        assert "DOWNTOWN" not in ai.get_active_wars()

    def test_end_war_nonexistent(self, ai):
        assert ai.end_war("NONEXISTENT") is False


class TestFactionAIStats:
    """Statistics and reset."""

    def test_stats(self):
        from engine.world.faction_ai import FactionAI
        ai = FactionAI()
        stats = ai.get_stats()
        assert stats["tick_count"] == 0
        assert stats["total_decisions"] == 0

    def test_reset(self):
        from engine.world.faction_ai import FactionAI, FactionDecision
        from engine.world.territory import DEFAULT_CONTROL
        ai = FactionAI()
        ai.set_control({d: dict(f) for d, f in DEFAULT_CONTROL.items()})
        ai.tick()
        ai.reset()
        assert ai.get_stats()["tick_count"] == 0
        assert len(ai.get_history()) == 0


class TestFactionProfiles:
    """Faction profile definitions."""

    def test_all_factions_have_profiles(self):
        from engine.world.faction_ai import FACTION_PROFILES
        from engine.world.territory import FACTION_NAMES
        for name in FACTION_NAMES:
            assert name in FACTION_PROFILES

    def test_profiles_have_valid_weights(self):
        from engine.world.faction_ai import FACTION_PROFILES
        for name, profile in FACTION_PROFILES.items():
            assert 0 <= profile.aggression <= 1
            assert 0 <= profile.expansion <= 1
            assert 0 <= profile.defense <= 1
            assert 0 <= profile.subterfuge <= 1
            assert 0 <= profile.diplomacy <= 1


class TestFactionSingleton:
    """Singleton behavior."""

    def test_singleton(self):
        from engine.world.faction_ai import get_faction_ai, reset_faction_ai
        reset_faction_ai()
        a1 = get_faction_ai()
        a2 = get_faction_ai()
        assert a1 is a2
        reset_faction_ai()


# ════════════════════════════════════════════════════════════════════════════
# Living World Orchestrator
# ════════════════════════════════════════════════════════════════════════════

class TestLivingWorldCore:
    """LivingWorld orchestrator basics."""

    @pytest.fixture
    def lw(self, tmp_path):
        from engine.world.living_world import LivingWorld
        from engine.world.market import Market
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            world = LivingWorld(tick_interval=0.01)
            yield world
            world.stop()

    def test_tick(self, lw):
        lw._init_subsystems()
        result = lw.tick()
        assert result.tick_number == 1
        assert result.time_of_day != ""

    def test_multiple_ticks(self, lw):
        lw._init_subsystems()
        for _ in range(5):
            lw.tick()
        stats = lw.get_stats()
        assert stats["tick_count"] == 5

    def test_event_generation(self, lw):
        """Run enough ticks to likely generate events (20% per tick)."""
        lw._init_subsystems()
        events_seen = 0
        for _ in range(30):
            result = lw.tick()
            events_seen += len(result.events_generated)
        assert events_seen > 0  # Probabilistic — 30 ticks × 20% ≈ 6 events

    def test_weather_cycling(self, lw):
        """Weather should change at least once in many ticks."""
        lw._init_subsystems()
        weather_changes = 0
        for _ in range(50):
            result = lw.tick()
            if result.weather_changed:
                weather_changes += 1
        assert weather_changes > 0

    def test_get_status(self, lw):
        lw._init_subsystems()
        lw.tick()
        status = lw.get_status()
        assert "running" in status
        assert "market" in status
        assert "npc_routines" in status
        assert "faction_ai" in status

    def test_event_log(self, lw):
        lw._init_subsystems()
        for _ in range(30):
            lw.tick()
        log = lw.get_event_log(limit=5)
        # May or may not have events (probabilistic)
        assert isinstance(log, list)


class TestLivingWorldDaemon:
    """Start/stop daemon behavior."""

    def test_start_stop(self, tmp_path):
        from engine.world.living_world import LivingWorld
        from engine.world.market import Market
        import time as _time
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            lw = LivingWorld(tick_interval=0.05)
            lw.start()
            assert lw._running is True
            _time.sleep(0.2)
            lw.stop()
            assert lw._running is False
            assert lw._tick_count > 0

    def test_double_start(self, tmp_path):
        from engine.world.living_world import LivingWorld
        from engine.world.market import Market
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            lw = LivingWorld(tick_interval=0.05)
            lw.start()
            lw.start()  # Should not raise
            lw.stop()


class TestLivingWorldReset:
    """Reset behavior."""

    def test_reset(self, tmp_path):
        from engine.world.living_world import LivingWorld
        from engine.world.market import Market
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            lw = LivingWorld(tick_interval=0.01)
            lw._init_subsystems()
            lw.tick()
            lw.tick()
            lw.reset()
            assert lw.get_stats()["tick_count"] == 0


class TestLivingWorldWeather:
    """Weather transition system."""

    def test_cycle_weather(self):
        from engine.world.living_world import LivingWorld, WEATHER_TRANSITIONS
        lw = LivingWorld()
        lw._last_weather = "CLEAR"
        new = lw._cycle_weather()
        assert new in WEATHER_TRANSITIONS.get("CLEAR", {})

    def test_all_weather_states_have_transitions(self):
        from engine.world.living_world import WEATHER_TRANSITIONS
        for state, transitions in WEATHER_TRANSITIONS.items():
            assert sum(transitions.values()) == pytest.approx(1.0, abs=0.01)


class TestLivingWorldEvents:
    """Event generation and consequences."""

    def test_generate_event(self):
        from engine.world.living_world import LivingWorld
        lw = LivingWorld()
        event = lw._generate_event()
        assert event is not None
        assert "name" in event
        assert "district" in event
        assert "narrative" in event
        assert "market_effect" in event

    def test_event_templates_valid(self):
        from engine.world.living_world import WORLD_EVENT_TEMPLATES
        for t in WORLD_EVENT_TEMPLATES:
            assert "name" in t
            assert "type" in t
            assert "districts" in t
            assert len(t["districts"]) > 0


class TestLivingWorldSingleton:
    """Singleton access."""

    def test_singleton(self):
        from engine.world.living_world import get_living_world, reset_living_world
        reset_living_world()
        lw1 = get_living_world()
        lw2 = get_living_world()
        assert lw1 is lw2
        reset_living_world()


# ════════════════════════════════════════════════════════════════════════════
# Living World MCP Skills
# ════════════════════════════════════════════════════════════════════════════

class TestLivingWorldSkills:
    """Test living_world skill pack imports and basic invocations."""

    @pytest.fixture(autouse=True)
    def setup_market(self, tmp_path):
        from engine.world.market import Market, reset_market
        reset_market()
        with patch.object(Market, "_SAVE_PATH", tmp_path / "market.json"):
            from engine.world.market import get_market
            m = get_market()  # force init with patched path
            yield
            reset_market()

    def test_imports(self):
        from engine.skills.builtin import living_world_skills
        assert hasattr(living_world_skills, "browse_goods")
        assert hasattr(living_world_skills, "buy_item")
        assert hasattr(living_world_skills, "find_npc")
        assert hasattr(living_world_skills, "faction_decisions")
        assert hasattr(living_world_skills, "world_status")

    def test_browse_goods(self):
        from engine.skills.builtin.living_world_skills import browse_goods
        result = browse_goods()
        assert "Market Goods" in result

    def test_browse_goods_filtered(self):
        from engine.skills.builtin.living_world_skills import browse_goods
        result = browse_goods(category="weapons")
        assert "weapons" in result.lower() or "Market Goods" in result

    def test_check_prices(self):
        from engine.skills.builtin.living_world_skills import check_prices
        result = check_prices("DOWNTOWN")
        assert "DOWNTOWN" in result

    def test_buy_item(self):
        from engine.skills.builtin.living_world_skills import buy_item
        result = buy_item("stim_pack", "DOWNTOWN")
        assert "Bought" in result or "Cannot" in result

    def test_sell_item(self):
        from engine.skills.builtin.living_world_skills import sell_item
        result = sell_item("stim_pack", "DOWNTOWN")
        assert "Sold" in result or "Cannot" in result

    def test_trade_history(self):
        from engine.skills.builtin.living_world_skills import trade_history
        result = trade_history()
        assert "history" in result.lower() or "No trade" in result

    def test_market_stats(self):
        from engine.skills.builtin.living_world_skills import market_stats
        result = market_stats()
        assert "Market Stats" in result

    def test_find_npc(self):
        from engine.world.npc_routines import get_routine_manager, reset_routine_manager
        reset_routine_manager()
        rm = get_routine_manager()
        rm.register_defaults()

        from engine.skills.builtin.living_world_skills import find_npc
        result = find_npc("viktor")
        assert "viktor" in result

    def test_find_npc_unknown(self):
        from engine.skills.builtin.living_world_skills import find_npc
        result = find_npc("nonexistent_npc")
        assert "not found" in result

    def test_npc_schedule(self):
        from engine.world.npc_routines import get_routine_manager, reset_routine_manager
        reset_routine_manager()
        rm = get_routine_manager()
        rm.register_defaults()

        from engine.skills.builtin.living_world_skills import npc_schedule
        result = npc_schedule("viktor")
        assert "viktor" in result
        assert "bartender" in result

    def test_npc_routine_stats(self):
        from engine.world.npc_routines import get_routine_manager, reset_routine_manager
        reset_routine_manager()
        rm = get_routine_manager()
        rm.register_defaults()

        from engine.skills.builtin.living_world_skills import npc_routine_stats
        result = npc_routine_stats()
        assert "NPC Routines" in result

    def test_faction_decisions(self):
        from engine.skills.builtin.living_world_skills import faction_decisions
        result = faction_decisions()
        assert "decision" in result.lower() or "No faction" in result

    def test_active_wars(self):
        from engine.skills.builtin.living_world_skills import active_wars
        result = active_wars()
        assert "war" in result.lower() or "quiet" in result.lower()

    def test_world_status(self):
        from engine.skills.builtin.living_world_skills import world_status
        result = world_status()
        assert "Living World" in result

    def test_world_events(self):
        from engine.skills.builtin.living_world_skills import world_events
        result = world_events()
        assert "event" in result.lower() or "No world" in result

    def test_living_world_stats(self):
        from engine.skills.builtin.living_world_skills import living_world_stats
        result = living_world_stats()
        assert "Living World Stats" in result
