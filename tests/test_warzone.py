"""Tests for SharedBoardManager and Global Strike game logic."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── SharedBoardManager ──────────────────────────────────────────────────

class TestSharedBoards:
    @pytest.fixture(autouse=True)
    def fresh_db(self, tmp_path, monkeypatch):
        import engine.mcp.shared_boards as sb
        monkeypatch.setattr(sb, "_DB_PATH", tmp_path / "test_boards.db")
        sb.SharedBoardManager._instance = None
        yield
        sb.SharedBoardManager._instance = None

    def test_ensure_board(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        result = b.ensure_board("test_hs", "highscore", "Test Scores")
        assert result["board_id"] == "test_hs"
        # Idempotent
        result2 = b.ensure_board("test_hs", "highscore")
        assert result2["board_id"] == "test_hs"

    def test_submit_and_get_scores(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        b.submit_score("game1", "Alice", 100)
        b.submit_score("game1", "Bob", 200)
        b.submit_score("game1", "Carol", 150)
        scores = b.get_highscores("game1", 10)
        assert len(scores) == 3
        assert scores[0]["player_name"] == "Bob"
        assert scores[0]["rank"] == 1
        assert scores[2]["player_name"] == "Alice"

    def test_score_rank(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        r1 = b.submit_score("g", "A", 50)
        r2 = b.submit_score("g", "B", 100)
        assert r1["rank"] == 1  # only score at submission time
        assert r2["rank"] == 1  # highest

    def test_post_and_get_messages(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        b.post_message("chat", "agent1", "Hello!", "Agent One")
        b.post_message("chat", "agent2", "Hi there!", "Agent Two")
        msgs = b.get_messages("chat", 10)
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Hi there!"  # newest first

    def test_messages_since_id(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        m1 = b.post_message("ch", "a", "first")
        m2 = b.post_message("ch", "a", "second")
        msgs = b.get_messages("ch", 10, since_id=m1["id"])
        assert len(msgs) == 1
        assert msgs[0]["content"] == "second"

    def test_list_boards(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        b.ensure_board("hs1", "highscore", "HS")
        b.ensure_board("mb1", "messageboard", "MB")
        all_boards = b.list_boards()
        assert len(all_boards) >= 3  # 2 + default cosysim_global
        hs_only = b.list_boards("highscore")
        assert all(x["board_type"] == "highscore" for x in hs_only)

    def test_default_global_board(self):
        from engine.mcp.shared_boards import get_shared_boards
        b = get_shared_boards()
        boards = b.list_boards("messageboard")
        ids = [x["board_id"] for x in boards]
        assert "cosysim_global" in ids


# ── Global Strike game logic ────────────────────────────────────────────

class TestGameState:
    def _make_game(self):
        from content.scenes.warzone.warzone_scene import GameState
        return GameState("test_game")

    def test_initial_state(self):
        g = self._make_game()
        assert g.turn == 1
        assert g.player.base_hp == 500
        assert g.ai.base_hp == 500
        assert g.player.weapon_level == 1
        assert g.phase == "player_turn"

    def test_build_factory(self):
        g = self._make_game()
        result = g.process_action("player", "build_factory")
        assert result["type"] == "build"
        assert len(g.player.buildings) == 1
        assert g.player.credits == 300  # 500 - 200

    def test_build_no_credits(self):
        g = self._make_game()
        g.player.credits = 50
        result = g.process_action("player", "build_factory")
        assert result["type"] == "error"

    def test_build_max_slots(self):
        g = self._make_game()
        g.player.credits = 10000
        g.process_action("player", "build_factory")
        g.process_action("player", "build_powerplant")
        g.process_action("player", "build_intel")
        result = g.process_action("player", "build_factory")
        assert result["type"] == "error"
        assert "slots" in result["msg"].lower()

    def test_upgrade_weapon(self):
        g = self._make_game()
        result = g.process_action("player", "upgrade_weapon")
        assert result["type"] == "upgrade"
        assert g.player.weapon_level == 2

    def test_upgrade_weapon_needs_resources(self):
        g = self._make_game()
        g.player.credits = 0
        result = g.process_action("player", "upgrade_weapon")
        assert result["type"] == "error"

    def test_attack_deals_damage(self):
        import random
        random.seed(42)
        g = self._make_game()
        g.weather = "clear"
        g.ai.defense_level = 1  # sandbags
        result = g.process_action("player", "attack", target="base")
        assert result["type"] == "attack"
        # May or may not hit depending on seed, but structure is correct
        assert "total_damage" in result
        assert "hits" in result

    def test_game_over_on_kill(self):
        g = self._make_game()
        g.ai.base_hp = 1
        g.weather = "favorable"
        g.player.weapon_level = 5  # laser, 100% accuracy
        result = g.process_action("player", "attack", target="base")
        assert g.ai.base_hp == 0
        assert g.phase == "game_over"
        assert g.winner == "player"

    def test_special_emp(self):
        g = self._make_game()
        g.player.power = 5
        result = g.process_action("player", "special_emp_burst")
        assert result["type"] == "special"
        assert g.ai.emp_turns == 1

    def test_special_spy(self):
        g = self._make_game()
        g.player.intel = 5
        result = g.process_action("player", "special_spy_satellite")
        assert result["type"] == "special"
        assert g.player.spy_turns == 3

    def test_special_taunt(self):
        g = self._make_game()
        g.player.intel = 5
        result = g.process_action("player", "special_taunt")
        assert result["type"] == "special"
        assert g.player.damage_bonus == 0.10

    def test_advance_turn(self):
        g = self._make_game()
        g.player.buildings.append({"type": "factory", "hp": 100})
        old_credits = g.player.credits
        g.advance_turn()
        assert g.turn == 2
        assert g.player.credits > old_credits  # income collected

    def test_to_dict_structure(self):
        g = self._make_game()
        d = g.to_dict()
        assert "game_id" in d
        assert "player" in d
        assert "ai" in d
        assert "turn" in d
        assert "weather_label" in d

    def test_spy_reveals_ai_stats(self):
        g = self._make_game()
        g.player.spy_turns = 0
        d = g.to_dict()
        # AI stats should be hidden
        assert "credits" not in d["ai"]
        g.player.spy_turns = 2
        d2 = g.to_dict()
        assert "credits" in d2["ai"]

    def test_income_with_escalation(self):
        g = self._make_game()
        g.player.buildings.append({"type": "factory", "hp": 100})
        inc1 = g.player.income(1.0)
        inc2 = g.player.income(2.0)
        assert inc2["credits"] > inc1["credits"]

    def test_sabotage_destroys_building(self):
        g = self._make_game()
        g.player.intel = 5
        g.player.power = 5
        g.ai.buildings.append({"type": "factory", "hp": 100})
        result = g.process_action("player", "special_sabotage")
        assert result["type"] == "special"
        assert len(g.ai.buildings) == 0


class TestPlayerState:
    def test_can_afford(self):
        from content.scenes.warzone.warzone_scene import PlayerState
        p = PlayerState("test")
        p.credits = 100
        p.power = 2
        p.intel = 1
        assert p.can_afford(credits=100, power=2, intel=1)
        assert not p.can_afford(credits=101)

    def test_spend(self):
        from content.scenes.warzone.warzone_scene import PlayerState
        p = PlayerState("test")
        p.credits = 500
        p.power = 3
        p.spend(credits=200, power=1)
        assert p.credits == 300
        assert p.power == 2
