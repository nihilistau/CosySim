"""Tests for The Dragon's Flagon tavern scene.

Covers: TavernState, tavern_rules, tavern_skills, and scene instantiation.
"""

from __future__ import annotations

import pytest

from content.scenes.tavern.tavern_state import (
    Atmosphere,
    DrinkItem,
    NPC_PROFILES,
    Quest,
    QuestStatus,
    RumorEntry,
    TavernState,
    TimeOfDay,
    DRINKS_MENU,
    QUEST_TEMPLATES,
    RUMOR_POOL,
)
from content.scenes.tavern.tavern_rules import (
    ATMOSPHERE_DIRECTIVES,
    REPUTATION_GATES,
    TIME_DIRECTIVES,
    build_scene_directive,
    can_approach_stranger,
    can_haggle,
    can_start_brawl,
    get_reputation_directive,
    get_unlocked_features,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def state():
    """Fresh TavernState."""
    return TavernState()


# ── TavernState — Gold ──────────────────────────────────────────────

class TestGold:
    def test_initial_gold(self, state):
        assert state.gold == 50

    def test_spend_gold_success(self, state):
        assert state.spend_gold(20) is True
        assert state.gold == 30

    def test_spend_gold_insufficient(self, state):
        assert state.spend_gold(100) is False
        assert state.gold == 50

    def test_earn_gold(self, state):
        state.earn_gold(25)
        assert state.gold == 75


# ── TavernState — Stats ────────────────────────────────────────────

class TestStats:
    def test_initial_stats(self, state):
        assert state.stats["warmth"] == 50
        assert state.stats["courage"] == 50
        assert state.stats["clarity"] == 80

    def test_adjust_stats_positive(self, state):
        changes = state.adjust_stats(warmth=20)
        assert changes == {"warmth": 20}
        assert state.stats["warmth"] == 70

    def test_adjust_stats_negative(self, state):
        changes = state.adjust_stats(courage=-30)
        assert changes == {"courage": -30}
        assert state.stats["courage"] == 20

    def test_stat_clamped_at_zero(self, state):
        state.adjust_stats(courage=-100)
        assert state.stats["courage"] == 0

    def test_stat_clamped_at_100(self, state):
        state.adjust_stats(warmth=100)
        assert state.stats["warmth"] == 100

    def test_adjust_unknown_stat_ignored(self, state):
        changes = state.adjust_stats(nonexistent=10)
        assert changes == {}


# ── TavernState — Reputation ────────────────────────────────────────

class TestReputation:
    def test_initial_reputation(self, state):
        for npc_id in NPC_PROFILES:
            assert state.reputation[npc_id] == 50

    def test_adjust_reputation(self, state):
        delta = state.adjust_reputation("greta", 20)
        assert delta == 20
        assert state.reputation["greta"] == 70

    def test_reputation_clamped(self, state):
        state.adjust_reputation("greta", 100)
        assert state.reputation["greta"] == 100
        state.adjust_reputation("greta", -200)
        assert state.reputation["greta"] == 0

    def test_unknown_npc_reputation(self, state):
        delta = state.adjust_reputation("nobody", 10)
        assert delta == 0

    @pytest.mark.parametrize("rep,expected", [
        (0, "hostile"), (15, "hostile"), (20, "wary"), (39, "wary"),
        (40, "neutral"), (59, "neutral"), (60, "friendly"), (79, "friendly"),
        (80, "trusted"), (100, "trusted"),
    ])
    def test_reputation_tiers(self, state, rep, expected):
        state.reputation["greta"] = rep
        assert state.get_reputation_tier("greta") == expected


# ── TavernState — Atmosphere ────────────────────────────────────────

class TestAtmosphere:
    def test_initial_atmosphere(self, state):
        assert state.atmosphere == Atmosphere.QUIET

    def test_heat_changes_atmosphere(self, state):
        state.heat = 30
        state.update_atmosphere()
        assert state.atmosphere == Atmosphere.LIVELY

    def test_rowdy_threshold(self, state):
        state.heat = 60
        state.update_atmosphere()
        assert state.atmosphere == Atmosphere.ROWDY

    def test_brawl_threshold(self, state):
        state.heat = 85
        state.update_atmosphere()
        assert state.atmosphere == Atmosphere.BRAWL

    def test_adjust_heat_clamped(self, state):
        state.adjust_heat(200)
        assert state.heat == 100
        state.adjust_heat(-200)
        assert state.heat == 0


# ── TavernState — Quests ────────────────────────────────────────────

class TestQuests:
    def test_quests_seeded(self, state):
        assert len(state.quests) == len(QUEST_TEMPLATES)

    def test_all_quests_available(self, state):
        avail = state.get_available_quests()
        assert len(avail) == len(QUEST_TEMPLATES)

    def test_accept_quest(self, state):
        q = state.accept_quest("lost_heirloom")
        assert q is not None
        assert q.status == QuestStatus.ACTIVE

    def test_accept_nonexistent_quest(self, state):
        q = state.accept_quest("nonexistent")
        assert q is None

    def test_cannot_accept_active_quest(self, state):
        state.accept_quest("lost_heirloom")
        q = state.accept_quest("lost_heirloom")
        assert q is None

    def test_advance_quest(self, state):
        state.accept_quest("lost_heirloom")
        q = state.advance_quest("lost_heirloom")
        assert q.status == QuestStatus.COMPLETED

    def test_quest_rewards(self, state):
        initial_gold = state.gold
        state.accept_quest("lost_heirloom")
        state.advance_quest("lost_heirloom")
        assert state.gold > initial_gold

    def test_multi_progress_quest(self, state):
        state.accept_quest("bards_rival")
        q = state.advance_quest("bards_rival")
        assert q.status == QuestStatus.ACTIVE
        assert q.progress == 1
        state.advance_quest("bards_rival")
        assert q.progress == 2
        state.advance_quest("bards_rival")
        assert q.status == QuestStatus.COMPLETED

    def test_advance_unavailable_quest(self, state):
        q = state.advance_quest("lost_heirloom")
        assert q is None

    def test_active_quests_list(self, state):
        state.accept_quest("lost_heirloom")
        active = state.get_active_quests()
        assert len(active) == 1
        assert active[0].id == "lost_heirloom"


# ── TavernState — Rumors ────────────────────────────────────────────

class TestRumors:
    def test_rumors_seeded(self, state):
        assert len(state.rumors) == len(RUMOR_POOL)

    def test_hear_rumor(self, state):
        rumor = state.hear_rumor()
        assert rumor is not None
        assert rumor.heard is True

    def test_all_rumors_eventually_heard(self, state):
        heard = set()
        for _ in range(len(RUMOR_POOL) + 5):
            r = state.hear_rumor()
            if r:
                heard.add(r.id)
        assert len(heard) == len(RUMOR_POOL)

    def test_no_more_rumors(self, state):
        for _ in range(len(RUMOR_POOL)):
            state.hear_rumor()
        assert state.hear_rumor() is None


# ── TavernState — Dice Game ─────────────────────────────────────────

class TestDiceGame:
    def test_start_dice_game(self, state):
        assert state.start_dice_game(10) is True
        assert state.dice_game_active is True
        assert state.gold == 40

    def test_start_insufficient_gold(self, state):
        assert state.start_dice_game(100) is False
        assert state.dice_game_active is False

    def test_roll_dice(self, state):
        state.start_dice_game(10)
        result = state.roll_dice()
        assert "die1" in result
        assert "die2" in result
        assert 2 <= result["total"] <= 12

    def test_roll_without_game(self, state):
        result = state.roll_dice()
        assert "error" in result

    def test_hold_dice(self, state):
        state.start_dice_game(10)
        state.dice_score = 15  # Set manually for deterministic test
        result = state.hold_dice()
        assert "player" in result
        assert "house" in result
        assert state.dice_game_active is False

    def test_hold_without_game(self, state):
        result = state.hold_dice()
        assert "error" in result


# ── TavernState — Stranger ──────────────────────────────────────────

class TestStranger:
    def test_stranger_not_initially_present(self, state):
        assert "stranger" not in state.npcs_present

    def test_stranger_appears_at_night(self, state):
        state.time_of_day = TimeOfDay.MIDNIGHT
        state.turn = 10  # Guarantee appearance
        appeared = state.maybe_stranger_appears()
        assert appeared is True
        assert "stranger" in state.npcs_present

    def test_stranger_appears_only_once(self, state):
        state.time_of_day = TimeOfDay.MIDNIGHT
        state.turn = 10
        state.maybe_stranger_appears()
        assert state.maybe_stranger_appears() is False

    def test_stranger_wont_appear_in_morning(self, state):
        state.time_of_day = TimeOfDay.MORNING
        state.turn = 100
        appeared = state.maybe_stranger_appears()
        assert appeared is False


# ── TavernState — Narrative ─────────────────────────────────────────

class TestNarrative:
    def test_log_event(self, state):
        state.log_event("Test event", "test")
        assert len(state.narrative) == 1
        assert state.narrative[0]["text"] == "Test event"

    def test_narrative_capped_at_50(self, state):
        for i in range(60):
            state.log_event(f"Event {i}")
        assert len(state.narrative) == 50

    def test_snapshot_includes_narrative_count(self, state):
        state.log_event("test")
        snap = state.to_snapshot()
        assert snap["narrative_count"] == 1


# ── TavernState — Snapshot ──────────────────────────────────────────

class TestSnapshot:
    def test_snapshot_keys(self, state):
        snap = state.to_snapshot()
        expected = {
            "gold", "atmosphere", "time_of_day", "turn", "heat",
            "reputation", "stats", "inventory", "npcs_present",
            "quests", "rumors_heard", "rumors_total",
            "dice_game_active", "narrative_count",
        }
        assert set(snap.keys()) == expected

    def test_snapshot_serialisable(self, state):
        import json
        snap = state.to_snapshot()
        s = json.dumps(snap)
        assert isinstance(s, str)


# ── Rules ───────────────────────────────────────────────────────────

class TestRules:
    def test_atmosphere_directives_complete(self):
        for atm in Atmosphere:
            assert atm in ATMOSPHERE_DIRECTIVES

    def test_time_directives_complete(self):
        for tod in TimeOfDay:
            assert tod in TIME_DIRECTIVES

    def test_reputation_gates_exist(self):
        for npc_id in NPC_PROFILES:
            assert npc_id in REPUTATION_GATES

    def test_get_unlocked_features_none(self, state):
        assert get_unlocked_features(state) == []

    def test_get_unlocked_features_high_rep(self, state):
        state.reputation["greta"] = 85
        feats = get_unlocked_features(state)
        assert "cellar_access" in feats
        assert "secret_menu" in feats

    def test_get_reputation_directive(self, state):
        result = get_reputation_directive(state, "greta")
        assert "neutral" in result

    def test_can_haggle_true(self, state):
        assert can_haggle(state) is True  # clarity=80, charm=50

    def test_can_haggle_false(self, state):
        state.stats["clarity"] = 20
        assert can_haggle(state) is False

    def test_can_start_brawl_false(self, state):
        assert can_start_brawl(state) is False

    def test_can_start_brawl_true(self, state):
        state.atmosphere = Atmosphere.ROWDY
        state.stats["courage"] = 70
        assert can_start_brawl(state) is True

    def test_can_approach_stranger_false(self, state):
        assert can_approach_stranger(state) is False

    def test_can_approach_stranger_true(self, state):
        state.npcs_present.append("stranger")
        state.stats["courage"] = 50
        assert can_approach_stranger(state) is True

    def test_build_scene_directive(self, state):
        directive = build_scene_directive(state, npc_id="greta")
        assert "Dragon's Flagon" in directive
        assert "Greta Ironhearth" in directive

    def test_build_scene_directive_no_npc(self, state):
        directive = build_scene_directive(state)
        assert "Dragon's Flagon" in directive


# ── Constants ───────────────────────────────────────────────────────

class TestConstants:
    def test_drinks_menu(self):
        assert len(DRINKS_MENU) >= 5
        for d in DRINKS_MENU:
            assert isinstance(d, DrinkItem)
            assert d.price > 0

    def test_quest_templates(self):
        assert len(QUEST_TEMPLATES) >= 5
        ids = {q["id"] for q in QUEST_TEMPLATES}
        assert len(ids) == len(QUEST_TEMPLATES)

    def test_rumor_pool(self):
        assert len(RUMOR_POOL) >= 5

    def test_npc_profiles(self):
        assert len(NPC_PROFILES) >= 4
        for npc_id, prof in NPC_PROFILES.items():
            assert "name" in prof
            assert "role" in prof
            assert "personality" in prof
            assert "speech_style" in prof
