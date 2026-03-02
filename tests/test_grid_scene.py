"""Tests for THE GRID scene — CosySim v0.75.

Covers: scene metadata, routes, market logic, faction pledging,
broker intel, skills, and Socket.IO event handling.
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def grid_state():
    """Return a fresh _GridState instance."""
    # Reset the singleton before each test
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    return gs_mod._get_grid_state()


@pytest.fixture()
def flask_client(tmp_path):
    """Return a Flask test client for GridScene."""
    import content.scenes.grid.grid_scene as gs_mod

    # Reset grid state singleton
    gs_mod._grid_state_instance = None

    scene = type("FakeScene", (), {
        "SCENE_METADATA": gs_mod.GridScene.SCENE_METADATA,
        "scene_name": "grid",
    })()

    app = MagicMock()
    routes: dict = {}

    def fake_route(path, **kwargs):
        def decorator(fn):
            routes[path] = fn
            return fn
        return decorator

    from flask import Flask
    real_app = Flask(__name__)
    gs_mod._grid_state_instance = None

    # Build a minimal real app via _register_routes
    grid_scene = object.__new__(gs_mod.GridScene)
    grid_scene.scene_name = "grid"
    grid_scene._state = gs_mod._get_grid_state()
    grid_scene.socketio = None

    from flask import Flask
    from flask_socketio import SocketIO
    real_app = Flask(__name__, template_folder=str(tmp_path))
    real_app.config["TESTING"] = True
    real_app.config["SECRET_KEY"] = "test"

    # Stub SocketIO
    grid_scene.socketio = MagicMock()
    grid_scene.app = real_app
    grid_scene._register_routes()

    return real_app.test_client()


# ──────────────────────────────────────────────────────────────────────────────
# Scene metadata
# ──────────────────────────────────────────────────────────────────────────────

def test_grid_scene_metadata():
    from content.scenes.grid.grid_scene import GridScene
    m = GridScene.SCENE_METADATA
    assert m["port"] == 5569
    assert m["accent_color"] == "#00ff88"
    assert m["name"] == "grid"
    assert "mira" in m["characters"]


def test_grid_get_plugin_info():
    from content.scenes.grid.grid_scene import GridScene
    scene = object.__new__(GridScene)
    scene.scene_name = "grid"
    scene.SCENE_METADATA = GridScene.SCENE_METADATA
    info = scene.get_plugin_info()
    assert info["port"] == 5569
    assert info["scene_key"] == "grid"
    assert info["accent_color"] == "#00ff88"


# ──────────────────────────────────────────────────────────────────────────────
# _GridState: market logic
# ──────────────────────────────────────────────────────────────────────────────

def test_get_market_items_returns_all(grid_state):
    items = grid_state.get_market_items()
    assert len(items) == 17  # MARKET_CATALOGUE count
    for item in items:
        assert "price" in item
        assert "stock" in item
        assert "trend" in item


def test_buy_item_success(grid_state):
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        ps = MagicMock()
        ps.credits = 10000
        mock_ps.return_value = ps
        result = grid_state.buy_item("stim_v1", 1)
    assert result["success"] is True
    assert result["item"] == "Stim-Pack v1"
    assert result["paid"] == 120
    assert grid_state._stock["stim_v1"] == 9


def test_buy_item_insufficient_stock(grid_state):
    grid_state._stock["stim_v1"] = 0
    result = grid_state.buy_item("stim_v1", 1)
    assert result["success"] is False
    assert "stock" in result["error"].lower()


def test_buy_item_insufficient_credits(grid_state):
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        ps = MagicMock()
        ps.credits = 1
        mock_ps.return_value = ps
        result = grid_state.buy_item("stim_v1", 1)
    assert result["success"] is False
    assert "credits" in result["error"].lower()


def test_buy_item_unknown(grid_state):
    result = grid_state.buy_item("no_such_item")
    assert result["success"] is False


def test_sell_item_success(grid_state):
    # First add to inventory manually
    grid_state._player_inventory.append({"item_id": "rush_dose", "name": "Rush Dose", "qty": 2, "paid": 160})
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        mock_ps.return_value = MagicMock()
        result = grid_state.sell_item("rush_dose", 1)
    assert result["success"] is True
    assert result["earned"] == int(80 * 0.65)


def test_sell_item_not_owned(grid_state):
    result = grid_state.sell_item("rush_dose", 1)
    assert result["success"] is False


def test_economy_shock_raises_prices(grid_state):
    changed = grid_state.economy_shock("corp_raid", 100)
    rising = [c for c in changed if c["trend"] == "rising"]
    assert len(rising) > 0


def test_economy_shock_drops_prices(grid_state):
    changed = grid_state.economy_shock("market_crash", -200)
    falling = [c for c in changed if c["trend"] == "falling"]
    assert len(falling) > 0


# ──────────────────────────────────────────────────────────────────────────────
# _GridState: faction logic
# ──────────────────────────────────────────────────────────────────────────────

def test_pledge_allegiance_success(grid_state):
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        ps = MagicMock()
        mock_ps.return_value = ps
        result = grid_state.pledge_allegiance("Ghost_Net")
    assert result["success"] is True
    assert result["rep_gained"] == 15
    assert "Ghost_Net" in result["faction"]


def test_pledge_allegiance_unknown(grid_state):
    result = grid_state.pledge_allegiance("NonExistent")
    assert result["success"] is False


def test_accept_quest_success(grid_state):
    result = grid_state.accept_quest("OmniCorp")
    assert result["success"] is True
    assert result["quest"]["faction"] == "OmniCorp"


def test_accept_quest_already_complete(grid_state):
    grid_state._quest_complete["OmniCorp"] = True
    result = grid_state.accept_quest("OmniCorp")
    assert result["success"] is False


def test_complete_quest_success(grid_state):
    grid_state.accept_quest("OmniCorp")
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        mock_ps.return_value = MagicMock()
        result = grid_state.complete_quest("OmniCorp")
    assert result["success"] is True
    assert result["rewards_applied"] is True
    assert grid_state._quest_complete.get("OmniCorp") is True


def test_complete_quest_wrong_faction(grid_state):
    grid_state.accept_quest("OmniCorp")
    result = grid_state.complete_quest("NeoTech")
    assert result["success"] is False


# ──────────────────────────────────────────────────────────────────────────────
# _GridState: intel / broker
# ──────────────────────────────────────────────────────────────────────────────

def test_add_intel_and_get_feed(grid_state):
    entry = {"id": "x1", "title": "Test Intel", "desc": "test", "type": "tip", "timestamp": 0, "source": "test"}
    grid_state.add_intel(entry)
    feed = grid_state.get_intel_feed()
    assert feed[0]["id"] == "x1"


def test_intel_feed_max_30(grid_state):
    for i in range(35):
        grid_state.add_intel({"id": str(i), "title": f"Entry {i}", "desc": "", "type": "tip", "timestamp": i, "source": "test"})
    assert len(grid_state.get_intel_feed(50)) <= 30


def test_get_player_inventory_empty(grid_state):
    assert grid_state.get_player_inventory() == []


# ──────────────────────────────────────────────────────────────────────────────
# API routes (via flask_client)
# ──────────────────────────────────────────────────────────────────────────────

def test_api_market_items_200(flask_client):
    res = flask_client.get("/api/market/items")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "items" in data
    assert len(data["items"]) == 17


def test_api_market_buy_missing_item(flask_client):
    res = flask_client.post(
        "/api/market/buy",
        data=json.dumps({"item_id": "no_such", "quantity": 1}),
        content_type="application/json",
    )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is False


def test_api_faction_standings_200(flask_client):
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        ps = MagicMock()
        ps.faction_standings = {}
        mock_ps.return_value = ps
        with patch("engine.world.world_state.get_world_state") as mock_ws:
            mock_ws.return_value.get_world_summary.return_value = {}
            res = flask_client.get("/api/faction/standings")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "factions" in data
    assert len(data["factions"]) == 6


def test_api_broker_intel_200(flask_client):
    with patch("engine.world.world_state.get_world_state") as mock_ws:
        mock_ws.return_value.get_active_events.return_value = []
        res = flask_client.get("/api/broker/intel")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "intel" in data


# ──────────────────────────────────────────────────────────────────────────────
# Skills
# ──────────────────────────────────────────────────────────────────────────────

def test_grid_buy_item_skill_success():
    import content.scenes.grid.grid_skills as skills_mod
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    state = gs_mod._get_grid_state()
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        ps = MagicMock()
        ps.credits = 9999
        mock_ps.return_value = ps
        result = skills_mod.grid_buy_item("stim_v1", 1)
    assert "Bought" in result
    assert "₵120" in result


def test_grid_buy_item_skill_fail():
    import content.scenes.grid.grid_skills as skills_mod
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    gs_mod._get_grid_state()._stock["stim_v1"] = 0
    result = skills_mod.grid_buy_item("stim_v1", 1)
    assert "failed" in result.lower()


def test_grid_get_market_prices_skill():
    import content.scenes.grid.grid_skills as skills_mod
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    result = skills_mod.grid_get_market_prices()
    assert "₵" in result
    assert "Stim-Pack" in result


def test_grid_faction_pledge_skill():
    import content.scenes.grid.grid_skills as skills_mod
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    with patch("engine.world.player_state.get_player_state") as mock_ps:
        mock_ps.return_value = MagicMock()
        result = skills_mod.grid_faction_pledge("Ghost_Net")
    assert "Ghost_Net" in result or "Allegiance" in result


def test_grid_accept_quest_skill():
    import content.scenes.grid.grid_skills as skills_mod
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    result = skills_mod.grid_accept_quest("OmniCorp")
    assert "OmniCorp" in result or "Quest accepted" in result


def test_grid_broker_intel_skill_empty():
    import content.scenes.grid.grid_skills as skills_mod
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    result = skills_mod.grid_broker_intel()
    assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# city map nodes
# ──────────────────────────────────────────────────────────────────────────────

def test_city_map_nodes_count():
    from content.scenes.grid.grid_scene import CITY_MAP_NODES
    assert len(CITY_MAP_NODES) == 15


def test_city_map_nodes_have_grid():
    from content.scenes.grid.grid_scene import CITY_MAP_NODES
    grid_node = next((n for n in CITY_MAP_NODES if n["key"] == "grid"), None)
    assert grid_node is not None
    assert grid_node.get("is_current") is True


def test_city_map_nodes_unique_ports():
    from content.scenes.grid.grid_scene import CITY_MAP_NODES
    ports = [n["port"] for n in CITY_MAP_NODES]
    assert len(ports) == len(set(ports)), "Duplicate ports in CITY_MAP_NODES"
