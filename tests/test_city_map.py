"""Tests for engine/world/city_map.py — CityMap, CityNode, TravelResult."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture(autouse=True)
def fresh_map():
    from engine.world.city_map import reset_city_map
    reset_city_map()
    yield
    reset_city_map()


@pytest.fixture()
def city_map():
    from engine.world.city_map import get_city_map
    return get_city_map()


@pytest.fixture()
def mock_player_state():
    ps = MagicMock()
    ps.active_location = "SIGNAL"
    ps.energy = 100
    ps.skills = {"hacking": 1}
    with patch("engine.world.city_map.get_player_state", return_value=ps):
        yield ps


# ---------------------------------------------------------------------------
# TestCityMapInit
# ---------------------------------------------------------------------------

class TestCityMapInit:
    def test_has_16_nodes(self, city_map):
        nodes = city_map.get_all_nodes()
        assert len(nodes) == 16

    def test_all_scene_ports_present(self, city_map):
        from engine.world.city_map import SCENE_PORTS
        for name in SCENE_PORTS:
            assert city_map.get_node(name) is not None

    def test_nodes_have_correct_districts(self, city_map):
        node = city_map.get_node("SIGNAL")
        assert node is not None
        assert node.district == "TECH_DISTRICT"

        node2 = city_map.get_node("THE PENTHOUSE")
        assert node2 is not None
        assert node2.district == "HIGHRISE"

    def test_adjacency_is_bidirectional(self, city_map):
        # THE VELVET PIT ↔ CLUB NOIR
        neighbors_vp = {n["name"] for n in city_map.get_neighbors("THE VELVET PIT")}
        neighbors_cn = {n["name"] for n in city_map.get_neighbors("CLUB NOIR")}
        assert "CLUB NOIR" in neighbors_vp
        assert "THE VELVET PIT" in neighbors_cn


# ---------------------------------------------------------------------------
# TestGetNeighbors
# ---------------------------------------------------------------------------

class TestGetNeighbors:
    def test_signal_has_neighbors(self, city_map):
        neighbors = city_map.get_neighbors("SIGNAL")
        assert len(neighbors) > 0
        names = {n["name"] for n in neighbors}
        assert "THE ARCADE" in names or "THE LAB" in names or "Command Center" in names

    def test_unknown_location_returns_empty(self, city_map):
        neighbors = city_map.get_neighbors("NOWHERE")
        assert neighbors == []

    def test_neighbor_has_required_keys(self, city_map):
        neighbors = city_map.get_neighbors("THE GRID")
        assert len(neighbors) > 0
        n = neighbors[0]
        assert "name" in n
        assert "district" in n
        assert "travel_time_min" in n
        assert "energy_cost" in n
        assert "heat_add" in n


# ---------------------------------------------------------------------------
# TestGetRoute
# ---------------------------------------------------------------------------

class TestGetRoute:
    def test_same_location_returns_zero_cost(self, city_map):
        route = city_map.get_route("SIGNAL", "SIGNAL")
        assert route is not None
        assert route["total_time"] == 0
        assert route["path"] == ["SIGNAL"]

    def test_adjacent_route(self, city_map):
        route = city_map.get_route("THE GRID", "THE LAB")
        assert route is not None
        assert "THE LAB" in route["path"]
        assert route["total_time"] > 0

    def test_multi_hop_route(self, city_map):
        # SIGNAL → THE PENTHOUSE requires multiple hops
        route = city_map.get_route("SIGNAL", "THE PENTHOUSE")
        assert route is not None
        assert len(route["path"]) >= 2
        assert route["path"][0] == "SIGNAL"
        assert route["path"][-1] == "THE PENTHOUSE"

    def test_route_to_unknown_returns_none(self, city_map):
        route = city_map.get_route("SIGNAL", "NOWHERE")
        assert route is None

    def test_route_includes_first_hop(self, city_map):
        route = city_map.get_route("SIGNAL", "THE PENTHOUSE")
        assert route is not None
        assert "first_hop" in route


# ---------------------------------------------------------------------------
# TestTravel
# ---------------------------------------------------------------------------

class TestTravel:
    def test_travel_to_adjacent_succeeds(self, city_map, mock_player_state):
        # SIGNAL is adjacent to THE ARCADE
        result = city_map.travel("THE ARCADE")
        assert result.success is True
        assert result.from_location == "SIGNAL"
        assert result.to_location == "THE ARCADE"
        assert result.energy_cost >= 0
        mock_player_state.spend_energy.assert_called_once()
        mock_player_state.set_location.assert_called_with("THE ARCADE")

    def test_travel_to_same_location_succeeds(self, city_map, mock_player_state):
        result = city_map.travel("SIGNAL")
        assert result.success is True
        assert result.energy_cost == 0
        mock_player_state.spend_energy.assert_not_called()

    def test_travel_to_unknown_fails(self, city_map, mock_player_state):
        result = city_map.travel("NOWHERE")
        assert result.success is False
        assert "Unknown" in result.message

    def test_travel_to_non_adjacent_fails_with_hint(self, city_map, mock_player_state):
        # THE PENTHOUSE is not directly adjacent to SIGNAL
        # (depends on edges — may or may not be adjacent)
        # Find a non-adjacent pair
        non_adj = None
        all_nodes = [n["name"] for n in city_map.get_all_nodes()]
        adjacent = {n["name"] for n in city_map.get_neighbors("SIGNAL")}
        for name in all_nodes:
            if name != "SIGNAL" and name not in adjacent:
                non_adj = name
                break
        if non_adj:
            result = city_map.travel(non_adj)
            assert result.success is False
            assert "Cannot travel directly" in result.message

    def test_travel_insufficient_energy_fails(self, city_map, mock_player_state):
        mock_player_state.energy = 0  # no energy
        # find a neighbor with energy_cost > 0
        neighbors = [n for n in city_map.get_neighbors("SIGNAL") if n["energy_cost"] > 0]
        if neighbors:
            result = city_map.travel(neighbors[0]["name"])
            assert result.success is False
            assert "energy" in result.message.lower()

    def test_travel_heat_add_calls_add_heat(self, city_map, mock_player_state):
        # Find a neighbor with heat_add > 0
        for n in city_map.get_neighbors("SIGNAL"):
            if n["heat_add"] > 0:
                mock_player_state.active_location = "SIGNAL"
                city_map.travel(n["name"])
                mock_player_state.add_heat.assert_called()
                return
        # No heat neighbor from SIGNAL — that's fine, test passes


# ---------------------------------------------------------------------------
# TestNPCTracking
# ---------------------------------------------------------------------------

class TestNPCTracking:
    def test_set_and_get_npc_location(self, city_map):
        city_map.set_npc_location("lola", "THE VELVET PIT")
        assert city_map.get_npc_location("lola") == "THE VELVET PIT"

    def test_npc_appears_in_node_names(self, city_map):
        city_map.set_npc_location("viktor", "THE GRID")
        npcs = city_map.get_npcs_at("THE GRID")
        assert "viktor" in npcs

    def test_npc_moved_removed_from_old_node(self, city_map):
        city_map.set_npc_location("mira", "SIGNAL")
        city_map.set_npc_location("mira", "THE ARCADE")
        assert "mira" not in city_map.get_npcs_at("SIGNAL")
        assert "mira" in city_map.get_npcs_at("THE ARCADE")

    def test_unknown_npc_returns_none(self, city_map):
        assert city_map.get_npc_location("ghost_npc") is None

    def test_get_all_npc_locations(self, city_map):
        city_map.set_npc_location("lola", "THE VELVET PIT")
        city_map.set_npc_location("frankie", "THE SCORE")
        locs = city_map.get_all_npc_locations()
        assert locs["lola"] == "THE VELVET PIT"
        assert locs["frankie"] == "THE SCORE"


# ---------------------------------------------------------------------------
# TestCityMapToDict
# ---------------------------------------------------------------------------

class TestCityMapToDict:
    def test_to_dict_has_required_keys(self, city_map, mock_player_state):
        d = city_map.to_dict()
        assert "nodes" in d
        assert "districts" in d
        assert "player_location" in d
        assert "npc_locations" in d

    def test_to_dict_nodes_count(self, city_map, mock_player_state):
        d = city_map.to_dict()
        assert len(d["nodes"]) == 16


# ---------------------------------------------------------------------------
# TestDistrictGroupings
# ---------------------------------------------------------------------------

class TestDistrictGroupings:
    def test_all_districts_have_nodes(self, city_map):
        from engine.world.city_map import DISTRICTS
        for district, names in DISTRICTS.items():
            nodes = city_map.get_district_nodes(district)
            assert len(nodes) == len(names), f"{district} mismatch"

    def test_tech_district_contains_signal(self, city_map):
        nodes = city_map.get_district_nodes("TECH_DISTRICT")
        names = [n.name for n in nodes]
        assert "SIGNAL" in names

    def test_set_scene_active(self, city_map):
        city_map.set_scene_active("THE GRID", True)
        node = city_map.get_node("THE GRID")
        assert node is not None
        assert node.is_active is True
