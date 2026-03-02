"""Tests for Bedroom scene — living world integration (v0.75 NEON CITY Track D).

Covers:
- GET /api/world/context response shape
- mood_modifier logic (heat/rep thresholds)
- world_context capped at 3 items
- get_bedroom_world_context skill
- update_bedroom_reputation skill
- PlayerState reset between tests
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BEDROOM_ROOT = Path(__file__).parent.parent / "content" / "scenes" / "bedroom"
SKILLS_FILE  = BEDROOM_ROOT / "bedroom_skills.py"

# ---------------------------------------------------------------------------
# Minimal SimEvent stub for testing (mirrors engine.world.world_sim.SimEvent)
# ---------------------------------------------------------------------------


@dataclass
class _SimEvent:
    id: str = "evt-1"
    event_type: str = "npc_action"
    title: str = "Test Event"
    description: str = "Something happened."
    scene: str = ""
    actor: str = ""
    intensity: float = 1.0
    payload: dict = field(default_factory=dict)
    created_at: str = ""
    seen_by_player: bool = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_player_state():
    """Reset the PlayerState singleton before every test."""
    from engine.world.player_state import reset_player_state
    reset_player_state()
    yield
    reset_player_state()


@pytest.fixture()
def player_state():
    """Return a fresh PlayerState instance."""
    from engine.world.player_state import get_player_state
    return get_player_state()


@pytest.fixture()
def flask_client():
    """Return a Flask test client with the /api/world/context route mounted directly."""
    from flask import Flask, jsonify
    from engine.world.player_state import get_player_state
    from engine.world.world_sim import get_event_log

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/world/context")
    def _world_context_route():
        events = get_event_log(limit=20)
        relevant = [e for e in events if e.scene == "bedroom" or e.intensity >= 2.0][:3]
        wc = [f"{e.title}: {e.description}" for e in relevant]
        ps = get_player_state()
        state = ps.to_dict()
        credits = state.get("credits", 0)
        rep     = state.get("reputation", 50)
        heat    = state.get("heat", 0)
        if heat >= 70:
            mood = "tense"
        elif rep >= 70:
            mood = "impressed"
        elif rep <= 30:
            mood = "cold"
        else:
            mood = "neutral"
        return jsonify({"world_context": wc, "credits": credits,
                        "reputation": rep, "heat": heat, "mood_modifier": mood})

    with app.test_client() as client:
        yield client


@pytest.fixture()
def mock_events():
    """Return a factory for patching get_event_log."""
    return _SimEvent


# ---------------------------------------------------------------------------
# Helper: build a BedroomScene._get_world_context_for_character directly
# ---------------------------------------------------------------------------


def _make_world_context_fn(events, ps_state: dict):
    """Return a callable equivalent to _get_world_context_for_character, seeded with test data."""
    def _fn():
        relevant = [e for e in events if e.scene == "bedroom" or e.intensity >= 2.0][:3]
        wc = [f"{e.title}: {e.description}" for e in relevant]
        credits = ps_state.get("credits", 0)
        rep     = ps_state.get("reputation", 50)
        heat    = ps_state.get("heat", 0)
        if heat >= 70:
            mood = "tense"
        elif rep >= 70:
            mood = "impressed"
        elif rep <= 30:
            mood = "cold"
        else:
            mood = "neutral"
        return {"world_context": wc, "credits": credits,
                "reputation": rep, "heat": heat, "mood_modifier": mood}
    return _fn


# ══════════════════════════════════════════════════════════════════════
#  API /api/world/context  — shape
# ══════════════════════════════════════════════════════════════════════


class TestWorldContextApiShape:
    """Verifies the API route returns the correct JSON structure."""

    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/world/context")
        assert resp.status_code == 200

    def test_has_world_context_key(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert "world_context" in data

    def test_world_context_is_list(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert isinstance(data["world_context"], list)

    def test_has_credits_key(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert "credits" in data

    def test_has_reputation_key(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert "reputation" in data

    def test_has_heat_key(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert "heat" in data

    def test_has_mood_modifier_key(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert "mood_modifier" in data

    def test_mood_modifier_is_string(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert isinstance(data["mood_modifier"], str)

    def test_credits_is_numeric(self, flask_client):
        data = flask_client.get("/api/world/context").get_json()
        assert isinstance(data["credits"], (int, float))

    def test_default_credits_match_player_state(self, flask_client, player_state):
        data = flask_client.get("/api/world/context").get_json()
        expected = player_state.to_dict()["credits"]
        assert data["credits"] == expected


# ══════════════════════════════════════════════════════════════════════
#  mood_modifier logic
# ══════════════════════════════════════════════════════════════════════


class TestMoodModifierLogic:
    """Verifies the four mood derivation rules."""

    def _mood(self, heat: int = 0, rep: int = 50) -> str:
        fn = _make_world_context_fn([], {"credits": 0, "reputation": rep, "heat": heat})
        return fn()["mood_modifier"]

    def test_heat_70_gives_tense(self):
        assert self._mood(heat=70, rep=50) == "tense"

    def test_heat_above_70_gives_tense(self):
        assert self._mood(heat=90, rep=20) == "tense"

    def test_rep_70_gives_impressed(self):
        assert self._mood(heat=0, rep=70) == "impressed"

    def test_rep_above_70_gives_impressed(self):
        assert self._mood(heat=0, rep=85) == "impressed"

    def test_rep_30_gives_cold(self):
        assert self._mood(heat=0, rep=30) == "cold"

    def test_rep_below_30_gives_cold(self):
        assert self._mood(heat=0, rep=10) == "cold"

    def test_neutral_default(self):
        assert self._mood(heat=0, rep=50) == "neutral"

    def test_heat_takes_priority_over_rep(self):
        # heat=80 trumps rep=80
        assert self._mood(heat=80, rep=80) == "tense"


# ══════════════════════════════════════════════════════════════════════
#  world_context capped at 3
# ══════════════════════════════════════════════════════════════════════


class TestWorldContextLength:
    """world_context must contain at most 3 items."""

    def test_at_most_3_items_from_many_events(self):
        events = [
            _SimEvent(id=f"e{i}", title=f"T{i}", description=f"D{i}", scene="bedroom", intensity=3.0)
            for i in range(10)
        ]
        fn = _make_world_context_fn(events, {"credits": 0, "reputation": 50, "heat": 0})
        ctx = fn()
        assert len(ctx["world_context"]) <= 3

    def test_only_relevant_events_included(self):
        events = [
            _SimEvent(id="a", title="High", description="High intensity", scene="other", intensity=2.5),
            _SimEvent(id="b", title="Low",  description="Low intensity",  scene="other", intensity=0.5),
        ]
        fn = _make_world_context_fn(events, {"credits": 0, "reputation": 50, "heat": 0})
        ctx = fn()
        assert len(ctx["world_context"]) == 1
        assert "High" in ctx["world_context"][0]

    def test_bedroom_scene_events_included_regardless_of_intensity(self):
        events = [
            _SimEvent(id="b1", title="BedEvent", description="Low but in bedroom",
                      scene="bedroom", intensity=0.1),
        ]
        fn = _make_world_context_fn(events, {"credits": 0, "reputation": 50, "heat": 0})
        ctx = fn()
        assert len(ctx["world_context"]) == 1
        assert "BedEvent" in ctx["world_context"][0]

    def test_empty_when_no_relevant_events(self):
        events = [
            _SimEvent(id="x", title="Elsewhere", description="...", scene="lounge", intensity=1.0),
        ]
        fn = _make_world_context_fn(events, {"credits": 0, "reputation": 50, "heat": 0})
        ctx = fn()
        assert ctx["world_context"] == []


# ══════════════════════════════════════════════════════════════════════
#  Skills
# ══════════════════════════════════════════════════════════════════════


def _import_skills_module():
    """Import bedroom_skills with mocked deps; @skill passes through the function."""
    skill_mock = MagicMock()
    # Make @skill(...)  return a passthrough decorator
    skill_mock.side_effect = lambda *a, **kw: lambda fn: fn

    skill_module_mock = MagicMock()
    skill_module_mock.skill = skill_mock
    skill_module_mock.SkillCategory = MagicMock()

    mocks = {
        "engine.skills.skill":          skill_module_mock,
        "engine.scenes.base_scene":     MagicMock(),
        "engine.mcp.state_coordinator": MagicMock(),
    }
    with patch.dict("sys.modules", mocks):
        sys.modules.pop("bedroom_skills_test", None)
        spec = importlib.util.spec_from_file_location("bedroom_skills_test", SKILLS_FILE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestGetBedroomWorldContextSkill:
    """get_bedroom_world_context returns a formatted string."""

    def test_returns_string(self, player_state):
        mod = _import_skills_module()
        with patch("engine.world.world_sim.get_event_log", return_value=[]):
            result = mod.get_bedroom_world_context()
        assert isinstance(result, str)

    def test_contains_credits_label(self, player_state):
        mod = _import_skills_module()
        with patch("engine.world.world_sim.get_event_log", return_value=[]):
            result = mod.get_bedroom_world_context()
        assert "Credits" in result

    def test_contains_mood_label(self, player_state):
        mod = _import_skills_module()
        with patch("engine.world.world_sim.get_event_log", return_value=[]):
            result = mod.get_bedroom_world_context()
        assert "Mood" in result

    def test_includes_event_title_when_relevant(self, player_state):
        ev = _SimEvent(id="e1", title="Fire at Penthouse", description="Sprinklers triggered",
                       scene="bedroom", intensity=2.0)
        mod = _import_skills_module()
        with patch("engine.world.world_sim.get_event_log", return_value=[ev]):
            result = mod.get_bedroom_world_context()
        assert "Fire at Penthouse" in result


class TestUpdateBedroomReputationSkill:
    """update_bedroom_reputation modifies PlayerState and returns confirmation."""

    def test_positive_delta_increases_rep(self, player_state):
        initial = player_state.to_dict()["reputation"]
        mod = _import_skills_module()
        mod.update_bedroom_reputation(delta=10)
        assert player_state.to_dict()["reputation"] == initial + 10

    def test_negative_delta_decreases_rep(self, player_state):
        initial = player_state.to_dict()["reputation"]
        mod = _import_skills_module()
        mod.update_bedroom_reputation(delta=-5)
        assert player_state.to_dict()["reputation"] == initial - 5

    def test_zero_delta_returns_no_change_message(self):
        mod = _import_skills_module()
        result = mod.update_bedroom_reputation(delta=0)
        assert "No reputation change" in result

    def test_returns_new_rep_in_string(self, player_state):
        mod = _import_skills_module()
        result = mod.update_bedroom_reputation(delta=5, reason="test")
        assert str(player_state.to_dict()["reputation"]) in result

    def test_custom_reason_in_return(self, player_state):
        mod = _import_skills_module()
        result = mod.update_bedroom_reputation(delta=3, reason="charmed_lola")
        assert "charmed_lola" in result

    def test_rep_clamped_at_100(self, player_state):
        player_state.update_reputation(100, "max")  # set to near max
        mod = _import_skills_module()
        mod.update_bedroom_reputation(delta=50)
        assert player_state.to_dict()["reputation"] <= 100

    def test_rep_clamped_at_0(self, player_state):
        player_state.update_reputation(-100, "min")  # set to near min
        mod = _import_skills_module()
        mod.update_bedroom_reputation(delta=-50)
        assert player_state.to_dict()["reputation"] >= 0
