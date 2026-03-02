"""
Tests for CLUB NOIR living-world integration — CosySim v0.75 "NEON CITY".

Covers:
  • GET /api/world/status — shape, VIP logic, heat_locked logic
  • POST /api/world/earn  — credits update, validation
  • _get_world_status()   — method-level unit tests
  • get_casino_world_status skill — registration, output format
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_state():
    """Reset the PlayerState singleton before and after every test."""
    from engine.world.player_state import reset_player_state
    reset_player_state()
    yield
    reset_player_state()


@pytest.fixture
def world_client():
    """Minimal Flask test client that wires the world routes with real PlayerState.

    We deliberately do NOT instantiate CasinoScene (which would attempt Flask
    socket-io, LMStudio wiring, etc.).  Instead we create a tiny Flask app
    that exercises the same route logic so we can test it in isolation.
    """
    from engine.world.player_state import get_player_state

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/world/status")
    def world_status():
        from flask import jsonify
        from engine.world.player_state import get_player_state as gps
        from content.scenes.casino.casino_scene import CasinoScene

        # Call the real method on a lightweight stand-in (no self needed
        # because _get_world_status only uses lazy imports, not instance attrs).
        mock_scene = MagicMock(spec=CasinoScene)
        result = CasinoScene._get_world_status(mock_scene)
        return jsonify(result)

    @app.route("/api/world/earn", methods=["POST"])
    def world_earn():
        from flask import jsonify, request
        from engine.world.player_state import get_player_state as gps

        data = request.get_json(force=True, silent=True) or {}
        amount = data.get("amount")
        reason = str(data.get("reason", "earn"))
        if not isinstance(amount, int) or amount <= 0:
            return jsonify({"error": "amount must be a positive integer"}), 400
        balance = gps().earn_credits(int(amount), reason)
        return jsonify({"balance": balance, "reason": reason, "amount": amount})

    return app.test_client()


# ── Helper: scene mock ─────────────────────────────────────────────────────


def _mock_scene_for_world() -> MagicMock:
    """Return a mock CasinoScene whose _get_world_status is the real method."""
    from content.scenes.casino.casino_scene import CasinoScene
    m = MagicMock(spec=CasinoScene)
    return m


# ══════════════════════════════════════════════════════════════════════════════
#  1. _get_world_status — unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestGetWorldStatus:
    def _call(self):
        from content.scenes.casino.casino_scene import CasinoScene
        return CasinoScene._get_world_status(MagicMock())

    def test_returns_all_required_keys(self, reset_state):
        status = self._call()
        for key in ("credits", "reputation", "heat", "faction_standings",
                    "vip_access", "heat_locked", "recent_events"):
            assert key in status, f"Missing key: {key}"

    def test_recent_events_is_list(self, reset_state):
        status = self._call()
        assert isinstance(status["recent_events"], list)

    def test_default_no_vip(self, reset_state):
        """OmniCorp standing defaults to 0 → vip_access is False."""
        status = self._call()
        assert status["vip_access"] is False

    def test_default_heat_not_locked(self, reset_state):
        """Default heat is 0 → heat_locked is False."""
        status = self._call()
        assert status["heat_locked"] is False

    def test_faction_standings_present(self, reset_state):
        status = self._call()
        assert isinstance(status["faction_standings"], dict)
        assert "OmniCorp" in status["faction_standings"]


# ══════════════════════════════════════════════════════════════════════════════
#  2. VIP access logic
# ══════════════════════════════════════════════════════════════════════════════


class TestVIPLogic:
    def _call(self):
        from content.scenes.casino.casino_scene import CasinoScene
        return CasinoScene._get_world_status(MagicMock())

    def test_vip_access_at_exactly_30(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().update_faction_standing("OmniCorp", 30)
        status = self._call()
        assert status["vip_access"] is True

    def test_vip_access_above_30(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().update_faction_standing("OmniCorp", 55)
        status = self._call()
        assert status["vip_access"] is True

    def test_no_vip_below_30(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().update_faction_standing("OmniCorp", 29)
        status = self._call()
        assert status["vip_access"] is False

    def test_no_vip_negative_standing(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().update_faction_standing("OmniCorp", -10)
        status = self._call()
        assert status["vip_access"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  3. Heat-lock logic
# ══════════════════════════════════════════════════════════════════════════════


class TestHeatLock:
    def _call(self):
        from content.scenes.casino.casino_scene import CasinoScene
        return CasinoScene._get_world_status(MagicMock())

    def test_heat_locked_at_80(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().set_heat(80)
        status = self._call()
        assert status["heat_locked"] is True

    def test_heat_locked_above_80(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().set_heat(99)
        status = self._call()
        assert status["heat_locked"] is True

    def test_not_locked_at_79(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().set_heat(79)
        status = self._call()
        assert status["heat_locked"] is False

    def test_heat_value_reflected(self, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().set_heat(42)
        status = self._call()
        assert status["heat"] == 42


# ══════════════════════════════════════════════════════════════════════════════
#  4. /api/world/status route
# ══════════════════════════════════════════════════════════════════════════════


class TestWorldStatusRoute:
    def test_status_200(self, world_client, reset_state):
        rv = world_client.get("/api/world/status")
        assert rv.status_code == 200

    def test_status_shape(self, world_client, reset_state):
        rv = world_client.get("/api/world/status")
        data = rv.get_json()
        for key in ("credits", "reputation", "heat", "vip_access", "heat_locked"):
            assert key in data, f"Missing key: {key}"

    def test_status_reflects_vip(self, world_client, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().update_faction_standing("OmniCorp", 40)
        rv = world_client.get("/api/world/status")
        assert rv.get_json()["vip_access"] is True

    def test_status_reflects_heat_lock(self, world_client, reset_state):
        from engine.world.player_state import get_player_state
        get_player_state().set_heat(85)
        rv = world_client.get("/api/world/status")
        data = rv.get_json()
        assert data["heat_locked"] is True
        assert data["heat"] == 85


# ══════════════════════════════════════════════════════════════════════════════
#  5. /api/world/earn route
# ══════════════════════════════════════════════════════════════════════════════


class TestWorldEarnRoute:
    def test_earn_returns_new_balance(self, world_client, reset_state):
        from engine.world.player_state import get_player_state
        initial = get_player_state().to_dict()["credits"]
        rv = world_client.post(
            "/api/world/earn",
            data=json.dumps({"amount": 500, "reason": "test_earn"}),
            content_type="application/json",
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["balance"] == initial + 500
        assert data["amount"] == 500
        assert data["reason"] == "test_earn"

    def test_earn_credits_persisted(self, world_client, reset_state):
        from engine.world.player_state import get_player_state
        initial = get_player_state().to_dict()["credits"]
        world_client.post(
            "/api/world/earn",
            data=json.dumps({"amount": 200, "reason": "persist_test"}),
            content_type="application/json",
        )
        assert get_player_state().to_dict()["credits"] == initial + 200

    def test_earn_invalid_amount_zero(self, world_client, reset_state):
        rv = world_client.post(
            "/api/world/earn",
            data=json.dumps({"amount": 0}),
            content_type="application/json",
        )
        assert rv.status_code == 400
        assert "error" in rv.get_json()

    def test_earn_invalid_amount_negative(self, world_client, reset_state):
        rv = world_client.post(
            "/api/world/earn",
            data=json.dumps({"amount": -100}),
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_earn_missing_body(self, world_client, reset_state):
        rv = world_client.post(
            "/api/world/earn",
            data="",
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_earn_non_integer_amount(self, world_client, reset_state):
        rv = world_client.post(
            "/api/world/earn",
            data=json.dumps({"amount": "lots"}),
            content_type="application/json",
        )
        assert rv.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  6. get_casino_world_status skill
# ══════════════════════════════════════════════════════════════════════════════


class TestCasinoWorldStatusSkill:
    def test_skill_registered(self, reset_state):
        import content.scenes.casino.casino_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY
        meta = SKILL_REGISTRY.get_skill("get_casino_world_status")
        assert meta is not None, "Skill 'get_casino_world_status' not registered"

    def test_skill_pack_is_casino(self, reset_state):
        import content.scenes.casino.casino_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY
        meta = SKILL_REGISTRY.get_skill("get_casino_world_status")
        assert meta.pack == "casino"

    def test_skill_returns_not_active_when_no_scene(self, reset_state):
        from content.scenes.casino.casino_skills import get_casino_world_status
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=None):
            result = get_casino_world_status()
        assert "not active" in result.lower()

    def test_skill_returns_formatted_string(self, reset_state):
        from content.scenes.casino.casino_skills import get_casino_world_status
        from engine.world.player_state import get_player_state
        get_player_state().earn_credits(0, "init")  # ensure singleton created

        mock_scene = MagicMock()
        mock_scene._get_world_status.return_value = {
            "credits": 1234,
            "reputation": 55,
            "heat": 20,
            "faction_standings": {"OmniCorp": 10, "NeoTech": 0},
            "vip_access": False,
            "heat_locked": False,
        }
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock_scene):
            result = get_casino_world_status()

        assert "CLUB NOIR" in result
        assert "1234" in result
        assert "55" in result
        assert "20" in result

    def test_skill_shows_vip_tag(self, reset_state):
        from content.scenes.casino.casino_skills import get_casino_world_status

        mock_scene = MagicMock()
        mock_scene._get_world_status.return_value = {
            "credits": 5000,
            "reputation": 70,
            "heat": 10,
            "faction_standings": {"OmniCorp": 35},
            "vip_access": True,
            "heat_locked": False,
        }
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock_scene):
            result = get_casino_world_status()

        assert "VIP" in result

    def test_skill_shows_heat_locked_tag(self, reset_state):
        from content.scenes.casino.casino_skills import get_casino_world_status

        mock_scene = MagicMock()
        mock_scene._get_world_status.return_value = {
            "credits": 100,
            "reputation": 30,
            "heat": 95,
            "faction_standings": {"OmniCorp": 0},
            "vip_access": False,
            "heat_locked": True,
        }
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock_scene):
            result = get_casino_world_status()

        assert "HEAT" in result.upper()
        assert "LOCKED" in result.upper() or "⚠" in result
