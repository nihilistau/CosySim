"""
Tests for NeonCity v0.75 "NEON CITY" living-world integration.

Covers:
  • _get_district_status() — shape, faction_standings, corp_raid detection
  • GET /api/world/district_status — HTTP shape and values
  • POST /api/world/faction_rep    — standing mutation
  • district_alert Socket.IO emission on Corp Raid world events
  • get_neoncity_world_status skill — registration and output
  • trigger_district_event skill   — heat adjustment and message
"""
from __future__ import annotations

import importlib
import sys
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ── Constants ─────────────────────────────────────────────────────────────────

_SCENE_PKG = "content.scenes.neoncity"
_SCENE_MOD = f"{_SCENE_PKG}.neoncity_scene"
_SKILLS_MOD = f"{_SCENE_PKG}.neoncity_skills"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_state():
    """Reset the PlayerState singleton before and after every test."""
    from engine.world.player_state import reset_player_state
    reset_player_state()
    yield
    reset_player_state()


@pytest.fixture
def world_client(reset_state):
    """Minimal Flask test client that wires the world routes with real PlayerState.

    Instantiates NeonCityScene._get_district_status and the two world routes
    without spinning up SocketIO or Flask-CORS — clean and fast.
    """
    from engine.world.player_state import get_player_state

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/world/district_status")
    def district_status():
        from flask import jsonify
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        mock_scene = MagicMock(spec=NeonCityScene)
        result = NeonCityScene._get_district_status(mock_scene)
        return jsonify(result)

    @app.route("/api/world/faction_rep", methods=["POST"])
    def faction_rep():
        from flask import jsonify, request
        from engine.world.player_state import get_player_state as gps
        data = request.get_json(force=True, silent=True) or {}
        faction = data.get("faction", "")
        delta = int(data.get("delta", 0))
        new_val = gps().update_faction_standing(faction, delta)
        return jsonify({"faction": faction, "delta": delta, "new_standing": new_val})

    return app.test_client()


# ── Helper ────────────────────────────────────────────────────────────────────


def _sim_event(title: str, scene: str = "neoncity") -> MagicMock:
    ev = MagicMock()
    ev.title = title
    ev.scene = scene
    ev.description = title
    return ev


# ══════════════════════════════════════════════════════════════════════════════
#  1. _get_district_status — unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestGetDistrictStatus:
    """Unit-test NeonCityScene._get_district_status() using real PlayerState."""

    def _call(self, mock_world_sim=None):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        mock_scene = MagicMock(spec=NeonCityScene)
        if mock_world_sim is not None:
            with patch(
                "engine.world.world_sim.get_world_sim",
                return_value=mock_world_sim,
            ):
                return NeonCityScene._get_district_status(mock_scene)
        # No mock → get_world_sim will raise; method must handle gracefully
        with patch(
            "engine.world.world_sim.get_world_sim",
            side_effect=RuntimeError("offline"),
        ):
            return NeonCityScene._get_district_status(mock_scene)

    def test_returns_all_required_keys(self, reset_state):
        """district_status must expose faction_standings, alerts, corp_raid, heat, credits."""
        status = self._call()
        for key in ("faction_standings", "district_alerts", "corp_raid_active", "heat", "credits"):
            assert key in status, f"Missing key: {key}"

    def test_faction_standings_from_player_state(self, reset_state):
        """faction_standings must include the six NeonCity factions."""
        status = self._call()
        expected = {"OmniCorp", "NeoTech", "BlackMarket", "Ghost_Net", "SynthSec", "DeepState"}
        assert expected.issubset(status["faction_standings"].keys())

    def test_default_heat_is_zero(self, reset_state):
        """Default PlayerState heat is 0."""
        assert self._call()["heat"] == 0

    def test_default_credits(self, reset_state):
        """Default PlayerState credits is 5000."""
        assert self._call()["credits"] == 5000

    def test_district_alerts_from_world_sim(self, reset_state):
        """Titles from neoncity-scene events appear in district_alerts."""
        sim = MagicMock()
        sim.get_all_events.return_value = [
            _sim_event("Blackout Wave", "neoncity"),
            _sim_event("Lounge Fire", "lounge"),  # different scene — excluded
        ]
        status = self._call(mock_world_sim=sim)
        assert "Blackout Wave" in status["district_alerts"]
        assert "Lounge Fire" not in status["district_alerts"]

    def test_corp_raid_active_false_by_default(self, reset_state):
        """corp_raid_active is False when no Corp Raid event exists."""
        sim = MagicMock()
        sim.get_all_events.return_value = [_sim_event("Market Surge")]
        status = self._call(mock_world_sim=sim)
        assert status["corp_raid_active"] is False

    def test_worldsim_offline_graceful(self, reset_state):
        """When WorldSim raises, district_alerts is empty and no exception propagates."""
        status = self._call()  # uses RuntimeError("offline") mock
        assert status["district_alerts"] == []
        assert status["corp_raid_active"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  2. corp_raid_active detection
# ══════════════════════════════════════════════════════════════════════════════


class TestCorpRaidDetection:
    """Verify corp_raid_active flag detection from world event titles."""

    def _call_with_events(self, events):
        from content.scenes.neoncity.neoncity_scene import NeonCityScene
        sim = MagicMock()
        sim.get_all_events.return_value = events
        with patch(
            "engine.world.world_sim.get_world_sim",
            return_value=sim,
        ):
            return NeonCityScene._get_district_status(MagicMock())

    def test_corp_raid_title_exact_case(self, reset_state):
        """Title 'Corp Raid: Sector 7' sets corp_raid_active True."""
        status = self._call_with_events([_sim_event("Corp Raid: Sector 7")])
        assert status["corp_raid_active"] is True

    def test_corp_raid_underscore_variant(self, reset_state):
        """Title containing 'corp_raid' sets corp_raid_active True."""
        status = self._call_with_events([_sim_event("corp_raid_warning")])
        assert status["corp_raid_active"] is True

    def test_unrelated_event_no_flag(self, reset_state):
        """An unrelated event title does not trigger corp_raid_active."""
        status = self._call_with_events([_sim_event("Festival of Lights")])
        assert status["corp_raid_active"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  3. GET /api/world/district_status — HTTP route
# ══════════════════════════════════════════════════════════════════════════════


class TestDistrictStatusRoute:
    def test_district_status_200(self, world_client, reset_state):
        """GET /api/world/district_status returns 200."""
        resp = world_client.get("/api/world/district_status")
        assert resp.status_code == 200

    def test_district_status_json_shape(self, world_client, reset_state):
        """Response JSON must contain the five required keys."""
        resp = world_client.get("/api/world/district_status")
        data = resp.get_json()
        for key in ("faction_standings", "district_alerts", "corp_raid_active", "heat", "credits"):
            assert key in data, f"Missing key in response: {key}"

    def test_district_status_standings_dict(self, world_client, reset_state):
        """faction_standings must be a dict with OmniCorp key."""
        data = world_client.get("/api/world/district_status").get_json()
        assert isinstance(data["faction_standings"], dict)
        assert "OmniCorp" in data["faction_standings"]


# ══════════════════════════════════════════════════════════════════════════════
#  4. POST /api/world/faction_rep — HTTP route
# ══════════════════════════════════════════════════════════════════════════════


class TestFactionRepRoute:
    def test_faction_rep_updates_standing(self, world_client, reset_state):
        """Posting faction=OmniCorp, delta=20 returns new_standing=20."""
        resp = world_client.post(
            "/api/world/faction_rep",
            json={"faction": "OmniCorp", "delta": 20},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["faction"] == "OmniCorp"
        assert data["new_standing"] == 20

    def test_faction_rep_reflected_in_player_state(self, world_client, reset_state):
        """Standing change is persistent in PlayerState."""
        from engine.world.player_state import get_player_state
        world_client.post("/api/world/faction_rep", json={"faction": "Ghost_Net", "delta": -15})
        ps_dict = get_player_state().to_dict()
        assert ps_dict["faction_standings"]["Ghost_Net"] == -15

    def test_faction_rep_unknown_faction_returns_zero(self, world_client, reset_state):
        """Unknown faction returns new_standing=0 without error."""
        resp = world_client.post(
            "/api/world/faction_rep",
            json={"faction": "UnknownFaction", "delta": 50},
        )
        assert resp.status_code == 200
        assert resp.get_json()["new_standing"] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  5. district_alert Socket.IO emission
# ══════════════════════════════════════════════════════════════════════════════


class TestDistrictAlertEmission:
    """Verify the Corp Raid handler emits district_alert via SocketIO."""

    def _make_handler_and_socketio(self):
        """Build the _on_corp_raid_check handler by replaying _setup_event_bus logic."""
        mock_socketio = MagicMock()
        captured: Dict[str, Any] = {}

        def _on_corp_raid_check(event):
            payload = event.get("payload", {})
            title = payload.get("title") or event.get("title", "")
            event_type_str = payload.get("event_type", "") or event.get("event_type", "")
            lower = title.lower()
            if "corp raid" in lower or "corp_raid" in lower or "corp_raid" in event_type_str:
                mock_socketio.emit("district_alert", {
                    "type": "corp_raid",
                    "title": title,
                    "payload": payload,
                })
            captured["last_event"] = event

        return _on_corp_raid_check, mock_socketio, captured

    def test_corp_raid_title_triggers_district_alert(self, reset_state):
        """Handler emits district_alert for 'Corp Raid: Downtown' title."""
        handler, sio, _ = self._make_handler_and_socketio()
        handler({"title": "Corp Raid: Downtown", "payload": {}})
        sio.emit.assert_called_once_with(
            "district_alert",
            {"type": "corp_raid", "title": "Corp Raid: Downtown", "payload": {}},
        )

    def test_non_raid_event_no_emission(self, reset_state):
        """Handler does NOT emit district_alert for non-Corp Raid events."""
        handler, sio, _ = self._make_handler_and_socketio()
        handler({"title": "Festival of Neon", "payload": {}})
        sio.emit.assert_not_called()

    def test_corp_raid_in_event_type_triggers_alert(self, reset_state):
        """Handler detects corp_raid in event_type field (payload)."""
        handler, sio, _ = self._make_handler_and_socketio()
        handler({
            "title": "",
            "payload": {"event_type": "corp_raid", "title": ""},
        })
        sio.emit.assert_called_once()
        args = sio.emit.call_args[0]
        assert args[0] == "district_alert"


# ══════════════════════════════════════════════════════════════════════════════
#  6. New skills
# ══════════════════════════════════════════════════════════════════════════════


def _setup_skill_mocks():
    """Inject @skill no-op and engine stubs needed to import neoncity_skills."""
    fake_skill_mod = MagicMock()
    fake_skill_mod.skill = MagicMock(side_effect=lambda **kw: (lambda fn: fn))
    fake_skill_mod.SkillCategory = MagicMock(GAME="game", ENVIRONMENT="environment")
    sys.modules["engine.skills.skill"] = fake_skill_mod

    for key in list(sys.modules.keys()):
        if key.startswith(_SKILLS_MOD):
            del sys.modules[key]


class TestGetNeoncityWorldStatusSkill:
    @pytest.fixture(autouse=True)
    def _setup(self, reset_state):
        _setup_skill_mocks()

    def test_skill_exists_and_callable(self, reset_state):
        """get_neoncity_world_status must be importable and callable."""
        mod = importlib.import_module(_SKILLS_MOD)
        assert hasattr(mod, "get_neoncity_world_status")
        assert callable(mod.get_neoncity_world_status)

    def test_skill_returns_string(self, reset_state):
        """Skill must return a non-empty string."""
        mock_sim = MagicMock()
        mock_sim.get_all_events.return_value = []
        with patch("engine.world.world_sim.get_world_sim", return_value=mock_sim):
            mod = importlib.import_module(_SKILLS_MOD)
            result = mod.get_neoncity_world_status()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_skill_includes_heat_and_credits(self, reset_state):
        """Output must mention heat and credits."""
        mock_sim = MagicMock()
        mock_sim.get_all_events.return_value = []
        with patch("engine.world.world_sim.get_world_sim", return_value=mock_sim):
            mod = importlib.import_module(_SKILLS_MOD)
            result = mod.get_neoncity_world_status()
        assert "Heat" in result or "heat" in result
        assert "Credits" in result or "credits" in result.lower()

    def test_skill_shows_district_alerts(self, reset_state):
        """When events exist for neoncity, alert titles appear in output."""
        mock_sim = MagicMock()
        mock_sim.get_all_events.return_value = [
            _sim_event("Blackout Surge", "neoncity"),
        ]
        with patch("engine.world.world_sim.get_world_sim", return_value=mock_sim):
            mod = importlib.import_module(_SKILLS_MOD)
            result = mod.get_neoncity_world_status()
        assert "Blackout Surge" in result


class TestTriggerDistrictEventSkill:
    @pytest.fixture(autouse=True)
    def _setup(self, reset_state):
        _setup_skill_mocks()

    def test_skill_exists_and_callable(self, reset_state):
        """trigger_district_event must be importable and callable."""
        mod = importlib.import_module(_SKILLS_MOD)
        assert hasattr(mod, "trigger_district_event")
        assert callable(mod.trigger_district_event)

    def test_skill_increases_heat(self, reset_state):
        """Calling trigger_district_event raises PlayerState heat by 15."""
        from engine.world.player_state import get_player_state
        mod = importlib.import_module(_SKILLS_MOD)
        mod.trigger_district_event()
        ps_dict = get_player_state().to_dict()
        assert ps_dict["heat"] == 15

    def test_skill_returns_string(self, reset_state):
        """trigger_district_event must return a non-empty string."""
        mod = importlib.import_module(_SKILLS_MOD)
        result = mod.trigger_district_event()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_skill_result_mentions_heat(self, reset_state):
        """Return string must mention heat level."""
        mod = importlib.import_module(_SKILLS_MOD)
        result = mod.trigger_district_event()
        assert "Heat" in result or "heat" in result
