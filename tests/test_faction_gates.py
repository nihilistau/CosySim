"""
Tests for faction_gates + standing-aware FactionAI ("Living Systems" v1.60.0)
=============================================================================

Hermetic: every test constructs fresh state or injects explicit standings — no
dependency on global data/*.json or live PlayerState (other agents run in
parallel). The FactionAI tests use a freshly constructed instance (not the
singleton) and inject player context directly via ``set_player_context``.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial test suite covering shop access, price
        multipliers, mission filtering, NPC notes, and player-standing bias in
        FactionAI._decide().
"""
from __future__ import annotations

import random

import pytest

from engine.world import faction_gates as fg
from engine.world.faction_ai import FactionAI, FactionAction


# ──── Standing classification ────────────────────────────────────────────


def test_standing_band_classification():
    assert fg.standing_band(80) == fg.StandingBand.ALLIED
    assert fg.standing_band(50) == fg.StandingBand.ALLIED
    assert fg.standing_band(30) == fg.StandingBand.FRIENDLY
    assert fg.standing_band(0) == fg.StandingBand.NEUTRAL
    assert fg.standing_band(-30) == fg.StandingBand.UNFRIENDLY
    assert fg.standing_band(-60) == fg.StandingBand.HOSTILE


def test_is_ally_is_rival():
    assert fg.is_ally(60) and not fg.is_rival(60)
    assert fg.is_ally(25) and not fg.is_rival(25)
    assert not fg.is_ally(0) and not fg.is_rival(0)
    assert fg.is_rival(-25) and not fg.is_ally(-25)
    assert fg.is_rival(-80)


# ──── Shop access ────────────────────────────────────────────────────────


def test_shop_access_allowed_by_default():
    # Neutral player is allowed at a default shop.
    assert fg.shop_access_allowed("BlackMarket", 0) is True
    # Allied player is allowed.
    assert fg.shop_access_allowed("BlackMarket", 70) is True


def test_shop_access_denied_below_min():
    # A sworn enemy is below the default shop_min_standing (-50).
    assert fg.shop_access_allowed("OmniCorp", -80) is False


def test_shop_access_per_shop_min_standing():
    # A VIP shop requiring +60 turns away a merely-friendly player.
    assert fg.shop_access_allowed("OmniCorp", 30, min_standing=60) is False
    assert fg.shop_access_allowed("OmniCorp", 75, min_standing=60) is True


# ──── Price multipliers ──────────────────────────────────────────────────


def test_price_matching_faction_discount():
    # Friendly with your own faction → exactly -10%.
    mult = fg.price_multiplier_for("BlackMarket", 30, relation="match")
    assert mult == pytest.approx(0.90)


def test_price_rival_faction_surcharge():
    # Friendly with a RIVAL faction → +15% at the rival's shop.
    mult = fg.price_multiplier_for("OmniCorp", 30, relation="rival")
    assert mult == pytest.approx(1.15)


def test_price_ally_gets_deeper_discount_than_friendly():
    friendly = fg.price_multiplier_for("BlackMarket", 30, relation="match")
    ally = fg.price_multiplier_for("BlackMarket", 80, relation="match")
    assert ally < friendly  # full allies pay less than the merely friendly


def test_price_enemy_pays_more_at_rival_than_ally():
    # Allied with rival → highest surcharge; player who hates rival → discount.
    allied_with_rival = fg.price_multiplier_for("OmniCorp", 80, relation="rival")
    hates_rival = fg.price_multiplier_for("OmniCorp", -80, relation="rival")
    assert allied_with_rival > 1.0
    assert hates_rival < 1.0


def test_price_neutral_is_full_price():
    assert fg.price_multiplier_for("NeoTech", 0, relation="match") == pytest.approx(1.0)
    assert fg.price_multiplier_for("NeoTech", 0, relation="rival") == pytest.approx(1.0)


def test_price_multiplier_clamped():
    # Even with extreme standing the multiplier stays in [0.5, 2.0].
    for s in (-100, 100):
        for rel in ("match", "rival"):
            m = fg.price_multiplier_for("SynthSec", s, relation=rel)
            assert 0.5 <= m <= 2.0


def test_apply_price_rounds_to_credits():
    assert fg.apply_price(100, "BlackMarket", 30, relation="match") == 90
    assert fg.apply_price(100, "OmniCorp", 30, relation="rival") == 115
    # Never free.
    assert fg.apply_price(1, "BlackMarket", 100, relation="match") >= 1


# ──── Mission filtering ──────────────────────────────────────────────────


def test_mission_unlocked_no_gate():
    ok, reason = fg.mission_unlocked({"id": "m1", "title": "Open Job"}, {})
    assert ok and reason == ""


def test_mission_min_standing_gate():
    mission = {"id": "m2", "faction": "Ghost_Net", "min_standing": 50}
    ok, reason = fg.mission_unlocked(mission, {"Ghost_Net": 10})
    assert not ok and "Ghost Net" in reason
    ok2, _ = fg.mission_unlocked(mission, {"Ghost_Net": 60})
    assert ok2


def test_mission_max_standing_gate():
    # Anti-corp job only offered while NOT a corp ally.
    mission = {"id": "m3", "faction": "OmniCorp", "max_standing": 0}
    ok, reason = fg.mission_unlocked(mission, {"OmniCorp": 40})
    assert not ok and reason
    ok2, _ = fg.mission_unlocked(mission, {"OmniCorp": -10})
    assert ok2


def test_filter_missions_drops_locked():
    missions = [
        {"id": "a"},
        {"id": "b", "faction": "Ghost_Net", "min_standing": 50},
        {"id": "c", "faction": "BlackMarket", "min_standing": 0},
    ]
    standings = {"Ghost_Net": 10, "BlackMarket": 30}
    visible = fg.filter_missions_by_standing(missions, standings)
    ids = {m["id"] for m in visible}
    assert ids == {"a", "c"}  # 'b' is locked out


def test_filter_missions_include_locked_annotates():
    missions = [{"id": "b", "faction": "Ghost_Net", "min_standing": 50}]
    out = fg.filter_missions_by_standing(
        missions, {"Ghost_Net": 10}, include_locked=True
    )
    assert len(out) == 1
    assert out[0]["locked"] is True
    assert out[0]["lock_reason"]
    # original dict not mutated
    assert "locked" not in missions[0]


# ──── NPC notes ──────────────────────────────────────────────────────────


def test_npc_standing_note_reflects_band():
    # Ghost_Net has an underscore → label "Ghost Net".
    ally_note = fg.npc_standing_note("Ghost_Net", 80)
    enemy_note = fg.npc_standing_note("Ghost_Net", -80)
    assert "Ghost Net" in ally_note
    assert ally_note != enemy_note
    # Deterministic — same inputs give same output (hermetic, no global RNG).
    assert fg.npc_standing_note("Ghost_Net", 80) == ally_note


def test_npc_standing_note_all_bands_nonempty():
    for s in (90, 30, 0, -30, -90):
        note = fg.npc_standing_note("SynthSec", s)
        assert isinstance(note, str) and note


# ──── FactionAI player-standing bias ─────────────────────────────────────


def _seed_control():
    """Return a control map with the player's district included."""
    return {
        "DOWNTOWN": {"OmniCorp": 40, "BlackMarket": 30, "SynthSec": 30},
        "COMBAT_ZONE": {"SynthSec": 50, "BlackMarket": 50},
        "HIGHRISE": {"OmniCorp": 70, "NeoTech": 30},
        "UNDERWORLD": {"BlackMarket": 60, "Ghost_Net": 40},
        "TECH_DISTRICT": {"NeoTech": 60, "Ghost_Net": 40},
        "OUTSKIRTS": {"DeepState": 100},
    }


def test_ai_ally_avoids_raiding_player(monkeypatch):
    """An allied faction should raid the player far less than a rival does."""
    random.seed(1234)
    ai_ally = FactionAI()
    ai_ally.set_control(_seed_control())
    ai_ally.set_player_context({"SynthSec": 90}, district="DOWNTOWN")

    ai_rival = FactionAI()
    ai_rival.set_control(_seed_control())
    ai_rival.set_player_context({"SynthSec": -90}, district="DOWNTOWN")

    profile = __import__(
        "engine.world.faction_ai", fromlist=["FACTION_PROFILES"]
    ).FACTION_PROFILES["SynthSec"]

    ally_raids = 0
    rival_raids = 0
    for _ in range(200):
        if ai_ally._decide("SynthSec", profile).action == FactionAction.RAID.value:
            ally_raids += 1
        if ai_rival._decide("SynthSec", profile).action == FactionAction.RAID.value:
            rival_raids += 1

    assert rival_raids > ally_raids, (
        f"rival should raid more than ally (rival={rival_raids}, ally={ally_raids})"
    )


def test_ai_rival_targets_player_district():
    """A rival faction, when it raids, should aim at the player's district.

    Uses SynthSec (high aggression, low subterfuge) so RAID is its dominant
    rival action, making the targeting assertion meaningful.
    """
    random.seed(99)
    ai = FactionAI()
    ai.set_control(_seed_control())
    ai.set_player_context({"SynthSec": -90}, district="DOWNTOWN")
    profile = __import__(
        "engine.world.faction_ai", fromlist=["FACTION_PROFILES"]
    ).FACTION_PROFILES["SynthSec"]

    targeted_player_district = 0
    raids = 0
    for _ in range(200):
        d = ai._decide("SynthSec", profile)
        if d.action == FactionAction.RAID.value:
            raids += 1
            if d.target_district == "DOWNTOWN":
                targeted_player_district += 1

    assert raids > 0
    # The majority of raids should hit the player's district.
    assert targeted_player_district >= raids * 0.6


def test_ai_tick_broadcasts_faction_shift():
    """tick() should emit neoncity.faction_shift events for control changes."""
    from engine.events.event_bus import EventTypes, get_event_bus

    random.seed(7)
    bus = get_event_bus()
    captured = []
    sub = bus.subscribe(
        EventTypes.NEONCITY_FACTION_SHIFT,
        lambda ev: captured.append(ev),
        "test_faction_gates",
    )
    try:
        ai = FactionAI()
        ai.set_control(_seed_control())
        ai.set_player_context({}, district="")
        result = ai.tick()
        # If any control change happened, it must have been broadcast.
        if result["control_changes"]:
            assert captured, "control changes were not broadcast on EventBus"
            payload = captured[0]["payload"]
            assert "district" in payload and "faction" in payload
            assert "control_before" in payload and "control_after" in payload
    finally:
        bus.unsubscribe(sub)
        bus.clear_handlers()


def test_ai_no_player_context_is_neutral():
    """With no player standings, bias is a no-op and decisions still work."""
    random.seed(3)
    ai = FactionAI()
    ai.set_control(_seed_control())
    profile = __import__(
        "engine.world.faction_ai", fromlist=["FACTION_PROFILES"]
    ).FACTION_PROFILES["OmniCorp"]
    d = ai._decide("OmniCorp", profile)
    assert d.action in {a.value for a in FactionAction}
