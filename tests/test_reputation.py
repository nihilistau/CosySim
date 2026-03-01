"""Tests for engine.characters.reputation — F5 Reputation System."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import engine.characters.reputation as rep_module
from engine.characters.reputation import (
    FactionId,
    ReputationEntry,
    ReputationInterceptor,
    ReputationManager,
    get_reputation_manager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    original = rep_module._manager_instance
    rep_module._manager_instance = None
    yield
    rep_module._manager_instance = original


@pytest.fixture()
def mock_nexus():
    """Patch get_nexus_client used inside reputation.py."""
    with patch("engine.characters.reputation.get_nexus_client") as mock_factory:
        client = MagicMock()
        client.search.return_value = []
        client.add_entry.return_value = "nexus-id-abc"
        client.update_entry.return_value = True
        client.delete_entry.return_value = True
        mock_factory.return_value = client
        yield client


@pytest.fixture()
def mock_event_bus():
    """Patch EventBus so no real publish calls happen."""
    with patch("engine.characters.reputation._get_event_bus") as mock_eb:
        bus = MagicMock()
        mock_eb.return_value = bus
        yield bus


@pytest.fixture()
def manager(mock_nexus):
    """Return a fresh ReputationManager backed by a mock Nexus."""
    return ReputationManager(nexus_client=mock_nexus)


# ---------------------------------------------------------------------------
# ReputationEntry.label_for
# ---------------------------------------------------------------------------


class TestLabelFor:
    def test_revered(self):
        assert ReputationEntry.label_for(100) == "Revered"
        assert ReputationEntry.label_for(81) == "Revered"

    def test_trusted(self):
        assert ReputationEntry.label_for(80) == "Trusted"
        assert ReputationEntry.label_for(61) == "Trusted"

    def test_friendly(self):
        assert ReputationEntry.label_for(60) == "Friendly"
        assert ReputationEntry.label_for(41) == "Friendly"

    def test_neutral(self):
        assert ReputationEntry.label_for(40) == "Neutral"
        assert ReputationEntry.label_for(21) == "Neutral"

    def test_indifferent(self):
        assert ReputationEntry.label_for(20) == "Indifferent"
        assert ReputationEntry.label_for(0) == "Indifferent"
        assert ReputationEntry.label_for(-20) == "Indifferent"

    def test_cold(self):
        assert ReputationEntry.label_for(-21) == "Cold"
        assert ReputationEntry.label_for(-40) == "Cold"

    def test_hostile(self):
        assert ReputationEntry.label_for(-41) == "Hostile"
        assert ReputationEntry.label_for(-60) == "Hostile"

    def test_enemy(self):
        assert ReputationEntry.label_for(-61) == "Enemy"
        assert ReputationEntry.label_for(-80) == "Enemy"

    def test_nemesis(self):
        assert ReputationEntry.label_for(-81) == "Nemesis"
        assert ReputationEntry.label_for(-100) == "Nemesis"


# ---------------------------------------------------------------------------
# test_standing_labels — required by spec
# ---------------------------------------------------------------------------


def test_standing_labels():
    """Spot-check all nine label tiers via label_for."""
    labels = {
        100: "Revered",
        70: "Trusted",
        50: "Friendly",
        30: "Neutral",
        0: "Indifferent",
        -30: "Cold",
        -50: "Hostile",
        -70: "Enemy",
        -90: "Nemesis",
    }
    for standing, expected in labels.items():
        assert ReputationEntry.label_for(standing) == expected, (
            f"standing={standing} expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# ReputationManager — basic standing
# ---------------------------------------------------------------------------


def test_default_standing_zero(manager):
    """A freshly queried entity with no Nexus record has standing 0."""
    assert manager.get_standing("unknown_npc") == 0


def test_adjust_positive(manager):
    """Adjusting standing by a positive delta increases it correctly."""
    entry = manager.adjust("luna", delta=20, reason="helped with quest")
    assert entry.standing == 20
    # standing=20 sits in the Indifferent band (-20..20)
    assert entry.label == "Indifferent"


def test_adjust_clamps_at_100(manager):
    """Standing cannot exceed +100."""
    manager.adjust("luna", delta=90, reason="first boost")
    entry = manager.adjust("luna", delta=90, reason="second boost")
    assert entry.standing == 100
    assert entry.label == "Revered"


def test_adjust_clamps_at_minus_100(manager):
    """Standing cannot fall below -100."""
    manager.adjust("thug", delta=-90, reason="first drop")
    entry = manager.adjust("thug", delta=-90, reason="second drop")
    assert entry.standing == -100
    assert entry.label == "Nemesis"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_history_appended(manager):
    """Each adjust call adds a note to history."""
    manager.adjust("mira", delta=10, reason="first event")
    entry = manager.adjust("mira", delta=5, reason="second event")
    assert len(entry.history) == 2
    assert "first event" in entry.history[0]
    assert "second event" in entry.history[1]


def test_history_max_10(manager):
    """History is capped at 10 entries."""
    for i in range(15):
        manager.adjust("mira", delta=1, reason=f"event_{i}", player_id="player")
    entry = manager.get_entry("mira")
    assert len(entry.history) <= 10


# ---------------------------------------------------------------------------
# Cross-scene ripple
# ---------------------------------------------------------------------------


def test_cross_scene_ripple_casino_debt(manager, mock_event_bus):
    """Casino debt_created ripples to SYNDICATE and mira."""
    with patch("engine.characters.reputation._HAS_EVENT_BUS", True):
        summaries = manager.apply_cross_scene_ripple("casino", "debt_created", -1)
    assert len(summaries) == 2
    targets = " ".join(summaries)
    assert FactionId.SYNDICATE.value in targets
    assert "mira" in targets
    assert manager.get_standing(FactionId.SYNDICATE.value) == -10
    assert manager.get_standing("mira") == -5


def test_cross_scene_ripple_heist_complete(manager):
    """Heist job_complete boosts UNDERGROUND."""
    summaries = manager.apply_cross_scene_ripple("heist", "job_complete", 1)
    assert len(summaries) == 1
    assert FactionId.UNDERGROUND.value in summaries[0]
    assert manager.get_standing(FactionId.UNDERGROUND.value) == 15


def test_cross_scene_ripple_unknown_event(manager):
    """Unknown ripple combinations return an empty list."""
    summaries = manager.apply_cross_scene_ripple("unknown_scene", "unknown_event", 0)
    assert summaries == []


def test_cross_scene_ripple_cheat_detected(manager):
    """Casino cheat_detected hits both CORPORATE and SYNDICATE."""
    summaries = manager.apply_cross_scene_ripple("casino", "cheat_detected", -1)
    assert len(summaries) == 2
    assert manager.get_standing(FactionId.CORPORATE.value) == -30
    assert manager.get_standing(FactionId.SYNDICATE.value) == -20


# ---------------------------------------------------------------------------
# Faction standings
# ---------------------------------------------------------------------------


def test_faction_standings(manager):
    """get_faction_standings returns an entry for every FactionId."""
    standings = manager.get_faction_standings()
    for fid in FactionId:
        assert fid.value in standings
        entry = standings[fid.value]
        assert isinstance(entry, ReputationEntry)
        assert entry.entity_type == "faction"


# ---------------------------------------------------------------------------
# Prompt context
# ---------------------------------------------------------------------------


def test_prompt_context_hostile(manager):
    """Hostile standing produces an uppercase 'HOSTILE' in the context."""
    manager.set_standing("thug", -55, reason="betrayal")
    ctx = manager.get_prompt_context("thug")
    assert "HOSTILE" in ctx
    assert "-55" in ctx


def test_prompt_context_friendly(manager):
    """Friendly standing produces a warm context string."""
    manager.set_standing("luna", 50, reason="quest complete")
    ctx = manager.get_prompt_context("luna")
    assert "FRIENDLY" in ctx
    assert "50" in ctx


def test_prompt_context_default_indifferent(manager):
    """Unrecorded entity defaults to INDIFFERENT with standing 0."""
    ctx = manager.get_prompt_context("stranger")
    assert "INDIFFERENT" in ctx
    assert "0" in ctx


# ---------------------------------------------------------------------------
# Interceptor
# ---------------------------------------------------------------------------


def test_interceptor_injects_context(manager, mock_nexus):
    """ReputationInterceptor prepends [REPUTATION] block to system_prompt."""
    with patch("engine.characters.reputation.get_reputation_manager", return_value=manager):
        interceptor = ReputationInterceptor()
        ctx = {"agent_id": "luna", "system_prompt": "You are Luna."}
        interceptor.pre_call(ctx)
        assert "[REPUTATION]" in ctx["system_prompt"]
        assert "[/REPUTATION]" in ctx["system_prompt"]
        assert "You are Luna." in ctx["system_prompt"]


def test_interceptor_skips_when_no_agent_id(manager):
    """Interceptor does nothing if agent_id is absent from context."""
    with patch("engine.characters.reputation.get_reputation_manager", return_value=manager):
        interceptor = ReputationInterceptor()
        ctx = {"system_prompt": "You are someone."}
        interceptor.pre_call(ctx)
        # system_prompt should be unchanged
        assert ctx["system_prompt"] == "You are someone."


def test_interceptor_post_call_passthrough(manager):
    """post_call does not mutate the context."""
    with patch("engine.characters.reputation.get_reputation_manager", return_value=manager):
        interceptor = ReputationInterceptor()
        ctx = {"reply": "Hello!", "agent_id": "mira"}
        interceptor.post_call(ctx)
        assert ctx["reply"] == "Hello!"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton(mock_nexus):
    """get_reputation_manager always returns the same instance."""
    with patch("engine.characters.reputation.get_nexus_client", return_value=mock_nexus):
        m1 = get_reputation_manager()
        m2 = get_reputation_manager()
        assert m1 is m2


# ---------------------------------------------------------------------------
# Nexus persistence
# ---------------------------------------------------------------------------


def test_nexus_add_called_on_new_entity(manager, mock_nexus):
    """add_entry is called when a new entity's standing is adjusted."""
    manager.adjust("new_npc", delta=10, reason="test")
    mock_nexus.add_entry.assert_called_once()
    call_kwargs = mock_nexus.add_entry.call_args
    assert "reputation" in str(call_kwargs)


def test_nexus_update_called_on_existing_entity(manager, mock_nexus):
    """update_entry is called when Nexus already has an entry for the entity."""
    import json
    existing_data = {
        "entity_id": "mira",
        "entity_type": "character",
        "player_id": "player",
        "standing": 0,
        "label": "Indifferent",
        "history": [],
        "last_updated": "2024-01-01T00:00:00+00:00",
    }
    mock_nexus.search.return_value = [
        {"id": "existing-id", "title": "rep:mira:player", "content": json.dumps(existing_data)}
    ]
    manager.adjust("mira", delta=5, reason="update test")
    mock_nexus.update_entry.assert_called()


# ---------------------------------------------------------------------------
# set_standing
# ---------------------------------------------------------------------------


def test_set_standing_absolute(manager):
    """set_standing sets an absolute value regardless of prior standing."""
    manager.adjust("kira", delta=50, reason="big boost")
    entry = manager.set_standing("kira", 10, reason="reset to neutral")
    assert entry.standing == 10


def test_set_standing_clamps(manager):
    """set_standing clamps values outside [-100, 100]."""
    entry = manager.set_standing("kira", 999, reason="overflow")
    assert entry.standing == 100
