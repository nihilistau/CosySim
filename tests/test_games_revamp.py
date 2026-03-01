"""
Tests for THE ARCADE — v0.68 Dark Renaissance Games Scene revamp.

Covers: scene metadata, skills registration, skill logic, file existence.
All tests run without a live Flask/Socket.IO server.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _mock_games_scene() -> MagicMock:
    """Return a minimal GamesScene mock for skills that call _get_games_scene()."""
    scene = MagicMock()
    scene._active_game = {}
    scene._scene_node = MagicMock()
    scene._scene_node.get_state.return_value = {
        "scores": {},
        "leaderboard": [
            {"player": "alice", "points": 50, "games": 5},
            {"player": "bob",   "points": 30, "games": 3},
        ],
        "games_played": 8,
        "active_game": None,
    }
    scene._get_leaderboard.return_value = [
        {"player": "alice", "points": 50, "games": 5},
        {"player": "bob",   "points": 30, "games": 3},
    ]
    return scene


# ══════════════════════════════════════════════════════════════════════
#  1. Scene metadata
# ══════════════════════════════════════════════════════════════════════

class TestGamesSceneMetadata:
    def test_scene_metadata_keys(self):
        from content.scenes.games.games_scene import GamesScene
        meta = GamesScene.SCENE_METADATA
        assert meta["name"]         == "games"
        assert meta["display_name"] == "THE ARCADE"
        assert meta["port"]         == 5567
        assert meta["type"]         == "games"
        assert meta["accent_color"] == "#8b5cf6"
        assert meta["accent_rgb"]   == "139 92 246"
        assert "description" in meta

    def test_scene_metadata_description_flavour(self):
        from content.scenes.games.games_scene import GamesScene
        desc = GamesScene.SCENE_METADATA["description"]
        assert "coin" in desc.lower() or "arcade" in desc.lower() or "score" in desc.lower()

    def test_games_port_constant(self):
        from content.scenes.games.games_scene import DEFAULT_PORT
        assert DEFAULT_PORT == 5567

    def test_arcade_games_list(self):
        from content.scenes.games.games_scene import ARCADE_GAMES
        assert "mystery"      in ARCADE_GAMES
        assert "truth_or_dare" in ARCADE_GAMES
        assert "dice_challenge" in ARCADE_GAMES

    def test_get_plugin_info_v068(self):
        """get_plugin_info must return v0.68 metadata without instantiating Flask."""
        from content.scenes.games import games_scene as gs_mod
        scene = MagicMock(spec=gs_mod.GamesScene)
        scene.port = 5567
        # Restore real class attribute so the method can read it
        scene.SCENE_METADATA = gs_mod.GamesScene.SCENE_METADATA
        result = gs_mod.GamesScene.get_plugin_info(scene)
        assert result["display_name"] == "THE ARCADE"
        assert result["version"]      == "0.68"
        assert result["port"]         == 5567
        assert result.get("accent_color") == "#8b5cf6"
        assert "games" in result.get("tags", [])


# ══════════════════════════════════════════════════════════════════════
#  2. Skills registered in SKILL_REGISTRY
# ══════════════════════════════════════════════════════════════════════

class TestGamesSkillsRegistered:
    def test_all_v068_skills_registered(self):
        """Import games_skills forces @skill registration."""
        import content.scenes.games.games_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        tools = SKILL_REGISTRY.get_pack_tools("games")
        registered = {fn.__name__ for fn in tools}
        expected = {"arcade_state", "start_game", "get_leaderboard"}
        missing  = expected - registered
        assert not missing, f"Skills not registered: {missing}"

    def test_legacy_skills_still_registered(self):
        """Legacy skills (games_status, games_mystery_start, etc.) remain."""
        import content.scenes.games.games_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        tools = SKILL_REGISTRY.get_pack_tools("games")
        registered = {fn.__name__ for fn in tools}
        legacy = {"games_status", "games_mystery_start", "games_mystery_clue",
                  "games_mystery_accuse", "games_tod_start", "games_tod_roll",
                  "games_tod_answer"}
        missing = legacy - registered
        assert not missing, f"Legacy skills missing: {missing}"

    def test_skill_pack_is_games(self):
        import content.scenes.games.games_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        for name in ("arcade_state", "start_game", "get_leaderboard"):
            meta = SKILL_REGISTRY.get_skill(name)
            assert meta is not None, f"Skill not found: {name}"
            assert meta.pack == "games", f"{name}.pack = {meta.pack!r}"

    def test_skills_have_descriptions(self):
        import content.scenes.games.games_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        for name in ("arcade_state", "start_game", "get_leaderboard"):
            meta = SKILL_REGISTRY.get_skill(name)
            assert meta is not None
            assert meta.description, f"{name} has no description"


# ══════════════════════════════════════════════════════════════════════
#  3. arcade_state skill
# ══════════════════════════════════════════════════════════════════════

class TestArcadeStateSkill:
    def test_returns_the_arcade_header(self):
        from content.scenes.games.games_skills import arcade_state
        with patch("content.scenes.games.games_skills._get_games_scene", return_value=None):
            result = arcade_state()
        assert "THE ARCADE" in result

    def test_lists_available_games(self):
        from content.scenes.games.games_skills import arcade_state
        with patch("content.scenes.games.games_skills._get_games_scene", return_value=None):
            result = arcade_state()
        assert "Mystery" in result or "mystery" in result.lower()
        assert "Dice" in result or "dice" in result.lower()

    def test_active_game_shown_when_scene_present(self):
        from content.scenes.games.games_skills import arcade_state
        mock = _mock_games_scene()
        mock._active_game = {"player": "mystery"}
        with patch("content.scenes.games.games_skills._get_games_scene", return_value=mock):
            result = arcade_state(player="player")
        assert "mystery" in result.lower()

    def test_no_scene_still_returns_string(self):
        from content.scenes.games.games_skills import arcade_state
        with patch("content.scenes.games.games_skills._get_games_scene", return_value=None):
            result = arcade_state()
        assert isinstance(result, str) and len(result) > 10


# ══════════════════════════════════════════════════════════════════════
#  4. HTML file exists
# ══════════════════════════════════════════════════════════════════════

class TestGamesHtmlExists:
    def _html(self) -> Path:
        return ROOT / "content" / "scenes" / "games" / "templates" / "games.html"

    def test_html_file_exists(self):
        assert self._html().exists(), f"Template not found: {self._html()}"

    def test_html_contains_the_arcade(self):
        content = self._html().read_text(encoding="utf-8")
        assert "THE ARCADE" in content

    def test_html_has_data_scene_games(self):
        content = self._html().read_text(encoding="utf-8")
        assert 'data-scene="games"' in content

    def test_html_has_game_selector(self):
        content = self._html().read_text(encoding="utf-8")
        assert "game-selector" in content
        assert "mystery" in content.lower()
        assert "dice" in content.lower()
        assert "truth" in content.lower()

    def test_html_has_investigation_board(self):
        content = self._html().read_text(encoding="utf-8")
        assert "investigation-board" in content

    def test_html_has_dice_3d(self):
        content = self._html().read_text(encoding="utf-8")
        assert "dice-3d" in content

    def test_html_has_leaderboard(self):
        content = self._html().read_text(encoding="utf-8")
        assert "leaderboard" in content

    def test_html_has_sparks_canvas(self):
        content = self._html().read_text(encoding="utf-8")
        assert "sparks-canvas" in content

    def test_html_has_socket_io(self):
        content = self._html().read_text(encoding="utf-8")
        assert "socket.io" in content.lower()

    def test_html_has_bench_hud(self):
        content = self._html().read_text(encoding="utf-8")
        assert "bench-hud" in content

    def test_html_includes_navbar(self):
        content = self._html().read_text(encoding="utf-8")
        assert "navbar" in content.lower()


# ══════════════════════════════════════════════════════════════════════
#  5. CSS file exists
# ══════════════════════════════════════════════════════════════════════

class TestGamesCssExists:
    def _css(self) -> Path:
        return ROOT / "content" / "scenes" / "games" / "static" / "css" / "games.css"

    def test_css_file_exists(self):
        assert self._css().exists(), f"CSS not found: {self._css()}"

    def test_css_has_violet_accent(self):
        content = self._css().read_text(encoding="utf-8")
        assert "#8b5cf6" in content

    def test_css_has_game_selector(self):
        content = self._css().read_text(encoding="utf-8")
        assert ".game-selector" in content

    def test_css_has_game_card(self):
        content = self._css().read_text(encoding="utf-8")
        assert ".game-card" in content

    def test_css_has_investigation_board(self):
        content = self._css().read_text(encoding="utf-8")
        assert ".investigation-board" in content

    def test_css_has_dice_3d(self):
        content = self._css().read_text(encoding="utf-8")
        assert ".dice-3d" in content

    def test_css_has_leaderboard(self):
        content = self._css().read_text(encoding="utf-8")
        assert ".leaderboard" in content

    def test_css_has_neon_flicker_animation(self):
        content = self._css().read_text(encoding="utf-8")
        assert "neon-flicker" in content

    def test_css_has_result_classes(self):
        content = self._css().read_text(encoding="utf-8")
        assert ".result-win" in content
        assert ".result-loss" in content


# ══════════════════════════════════════════════════════════════════════
#  6. JS file exists
# ══════════════════════════════════════════════════════════════════════

class TestGamesJsExists:
    def _js(self) -> Path:
        return ROOT / "content" / "scenes" / "games" / "static" / "js" / "games.js"

    def test_js_file_exists(self):
        assert self._js().exists(), f"JS not found: {self._js()}"

    def test_js_has_arcade_scene_class(self):
        content = self._js().read_text(encoding="utf-8")
        assert "TheArcadeScene" in content

    def test_js_has_required_methods(self):
        content = self._js().read_text(encoding="utf-8")
        for method in ("init", "_setupSocket", "loadState", "startGame",
                       "submitAnswer", "rollDice", "_renderGameArea",
                       "sendMessage"):
            assert method in content, f"Missing method: {method}"

    def test_js_has_sparks_particle_effect(self):
        content = self._js().read_text(encoding="utf-8")
        assert "_launchSparks" in content
        assert "requestAnimationFrame" in content

    def test_js_bootstrap_sets_window_arcade(self):
        content = self._js().read_text(encoding="utf-8")
        assert "window._arcade" in content

    def test_js_has_leaderboard_renderer(self):
        content = self._js().read_text(encoding="utf-8")
        assert "_renderLeaderboard" in content

    def test_js_has_investigation_board_pin(self):
        content = self._js().read_text(encoding="utf-8")
        assert "_addCluePinToBoard" in content or "clue-pin" in content

    def test_js_has_dice_roll_animation(self):
        content = self._js().read_text(encoding="utf-8")
        assert "rolling" in content
        assert "dice-3d" in content or "dice_3d" in content.replace("-", "_")
