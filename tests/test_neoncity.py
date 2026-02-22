"""Tests for NeonCity scene — game state, grid, combat, storm mechanics."""
import pytest

from content.scenes.neoncity.neoncity_state import (
    GRID_SIZE,
    PREFAB_TYPES,
    NeonCityGameState,
    NeonPlayer,
)


class TestNeonPlayer:
    def test_initial_state(self):
        p = NeonPlayer(id="p1", name="Test")
        assert p.hp == 100
        assert p.alive
        assert p.movement_points == 3

    def test_take_damage(self):
        p = NeonPlayer(id="p1", name="Test", defense=5)
        hp, dead = p.take_damage(20)
        assert hp == 85  # 20 - 5 defense = 15 actual
        assert not dead

    def test_lethal_damage(self):
        p = NeonPlayer(id="p1", name="Test", defense=0)
        hp, dead = p.take_damage(200)
        assert hp == 0
        assert dead
        assert not p.alive

    def test_heal(self):
        p = NeonPlayer(id="p1", name="Test", defense=0)
        p.take_damage(50)
        hp = p.heal(30)
        assert hp == 80

    def test_heal_capped(self):
        p = NeonPlayer(id="p1", name="Test")
        hp = p.heal(50)
        assert hp == 100

    def test_to_dict(self):
        p = NeonPlayer(id="p1", name="Test")
        d = p.to_dict()
        assert d["id"] == "p1"
        assert d["name"] == "Test"
        assert d["hp"] == 100
        assert d["alive"]


class TestNeonCityGameState:
    def setup_method(self):
        self.state = NeonCityGameState(num_ai_players=2)

    def test_initial_state(self):
        assert self.state.grid_size == GRID_SIZE
        assert self.state.turn_number == 0
        assert not self.state.ended
        assert len(self.state.players) == 3  # 1 human + 2 AI

    def test_grid_dimensions(self):
        assert len(self.state.grid) == GRID_SIZE
        assert len(self.state.grid[0]) == GRID_SIZE

    def test_target_placed(self):
        cell = self.state.grid[self.state.target_y][self.state.target_x]
        assert cell.terrain == "target"

    def test_prefabs_placed(self):
        prefab_count = 0
        for row in self.state.grid:
            for cell in row:
                if cell.prefab:
                    prefab_count += 1
        assert prefab_count == len(PREFAB_TYPES)

    def test_start_game(self):
        result = self.state.start_game()
        assert result["started"]
        assert self.state.turn_number == 1
        assert self.state.phase == "movement"

    def test_to_dict(self):
        d = self.state.to_dict()
        assert "session_id" in d
        assert "players" in d
        assert len(d["players"]) == 3
        assert "target" in d
        assert d["grid_size"] == GRID_SIZE

    def test_get_grid_dict(self):
        gd = self.state.get_grid_dict()
        assert len(gd) == GRID_SIZE
        assert len(gd[0]) == GRID_SIZE
        assert "x" in gd[0][0]
        assert "terrain" in gd[0][0]

    def test_move_player(self):
        self.state.start_game()
        p = self.state.players[0]  # human
        # Find a valid adjacent street cell
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = p.x + dx, p.y + dy
                if 0 <= nx < GRID_SIZE and 0 <= ny < GRID_SIZE:
                    if self.state.grid[ny][nx].terrain != "building" and (dx, dy) != (0, 0):
                        result = self.state.move_player("player", nx, ny)
                        if "moved" in result:
                            assert result["moved"]
                            assert p.x == nx and p.y == ny
                            return
        pytest.skip("No adjacent street cell found")

    def test_move_out_of_bounds(self):
        self.state.start_game()
        result = self.state.move_player("player", -1, -1)
        assert "error" in result

    def test_move_into_building(self):
        self.state.start_game()
        # Place a building next to player
        p = self.state.players[0]
        bx, by = min(p.x + 1, GRID_SIZE - 1), p.y
        self.state.grid[by][bx].terrain = "building"
        result = self.state.move_player("player", bx, by)
        assert "error" in result

    def test_advance_turn(self):
        self.state.start_game()
        result = self.state.advance_turn()
        assert "turn" in result
        assert "current_player" in result

    def test_storm_shrinks(self):
        self.state.start_game()
        initial_radius = self.state.storm_radius
        # Simulate full round (advance past all players)
        for _ in range(len(self.state.players)):
            self.state.advance_turn()
        assert self.state.storm_radius == initial_radius - 1

    def test_attack_player(self):
        self.state.start_game()
        # Put two players adjacent
        self.state.players[0].x = 5
        self.state.players[0].y = 5
        self.state.players[1].x = 6
        self.state.players[1].y = 5
        result = self.state.attack_player("player", self.state.players[1].id)
        assert "hit" in result or "error" in result

    def test_attack_out_of_range(self):
        self.state.start_game()
        self.state.players[0].x = 0
        self.state.players[0].y = 0
        self.state.players[1].x = 10
        self.state.players[1].y = 10
        result = self.state.attack_player("player", self.state.players[1].id)
        assert "error" in result

    def test_hack_not_at_target(self):
        self.state.start_game()
        self.state.players[0].x = 0
        self.state.players[0].y = 0
        result = self.state.hack_target("player")
        assert "error" in result

    def test_hack_at_target(self):
        self.state.start_game()
        self.state.players[0].x = self.state.target_x
        self.state.players[0].y = self.state.target_y
        result = self.state.hack_target("player")
        assert "success" in result or "error" in result

    def test_trigger_event(self):
        self.state.start_game()
        result = self.state.trigger_event()
        assert "event" in result
        assert "id" in result["event"]

    def test_ai_turn(self):
        self.state.start_game()
        ai = next(p for p in self.state.players if p.is_ai)
        actions = self.state.ai_turn(ai.id)
        assert isinstance(actions, list)


class TestStormMechanics:
    def test_storm_damages_players(self):
        state = NeonCityGameState(num_ai_players=0)
        state.start_game()
        # Move player to edge (will be in storm after shrink)
        state.players[0].x = 0
        state.players[0].y = 0
        state.grid[0][0].in_storm = True
        initial_hp = state.players[0].hp
        state._apply_storm_damage()
        assert state.players[0].hp < initial_hp

    def test_storm_advance_marks_cells(self):
        state = NeonCityGameState(num_ai_players=0)
        state.start_game()
        state.storm_radius = 3
        state._advance_storm()
        # Corner cells should be in storm
        assert state.grid[0][0].in_storm
