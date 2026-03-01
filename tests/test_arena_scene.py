"""Tests for THE COLOSSEUM — Arena Scene (v0.68 'Dark Renaissance').

Covers:
    - SCENE_METADATA contract
    - Skill registration and callability
    - Skill logic with mocked ArenaEngine
    - Static asset existence (HTML, CSS, JS)
    - Port in config/default.yaml
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── Project root ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARENA_DIR = PROJECT_ROOT / "content" / "scenes" / "arena"


# ══════════════════════════════════════════════════════════════════════
#  METADATA
# ══════════════════════════════════════════════════════════════════════


class TestArenaSceneMetadata:
    """Validate the SCENE_METADATA class attribute."""

    def test_arena_scene_metadata_exists(self):
        """ArenaScene must expose a SCENE_METADATA dict."""
        from content.scenes.arena import ArenaScene
        assert hasattr(ArenaScene, "SCENE_METADATA")
        assert isinstance(ArenaScene.SCENE_METADATA, dict)

    def test_arena_scene_metadata_name(self):
        """SCENE_METADATA.name == 'arena'."""
        from content.scenes.arena import ArenaScene
        assert ArenaScene.SCENE_METADATA.get("name") == "arena"

    def test_arena_scene_metadata_port(self):
        """SCENE_METADATA.port == 5561."""
        from content.scenes.arena import ArenaScene
        assert ArenaScene.SCENE_METADATA.get("port") == 5561

    def test_arena_scene_metadata_accent(self):
        """SCENE_METADATA.accent_color == '#dc2626'."""
        from content.scenes.arena import ArenaScene
        assert ArenaScene.SCENE_METADATA.get("accent_color") == "#dc2626"

    def test_arena_scene_metadata_display_name(self):
        """SCENE_METADATA.display_name == 'THE COLOSSEUM'."""
        from content.scenes.arena import ArenaScene
        assert ArenaScene.SCENE_METADATA.get("display_name") == "THE COLOSSEUM"

    def test_arena_scene_metadata_type(self):
        """SCENE_METADATA.type == 'game'."""
        from content.scenes.arena import ArenaScene
        assert ArenaScene.SCENE_METADATA.get("type") == "game"


# ══════════════════════════════════════════════════════════════════════
#  SKILLS REGISTRATION
# ══════════════════════════════════════════════════════════════════════


class TestArenaSkillsRegistered:
    """Verify skill functions are importable and callable."""

    def test_arena_skills_module_importable(self):
        """arena_skills module must import without errors."""
        from content.scenes.arena import arena_skills
        assert arena_skills is not None

    def test_create_arena_match_callable(self):
        """create_arena_match must be a callable."""
        from content.scenes.arena.arena_skills import create_arena_match
        assert callable(create_arena_match)

    def test_play_arena_round_callable(self):
        """play_arena_round must be a callable."""
        from content.scenes.arena.arena_skills import play_arena_round
        assert callable(play_arena_round)

    def test_place_arena_bet_callable(self):
        """place_arena_bet must be a callable."""
        from content.scenes.arena.arena_skills import place_arena_bet
        assert callable(place_arena_bet)

    def test_get_arena_leaderboard_callable(self):
        """get_arena_leaderboard must be a callable."""
        from content.scenes.arena.arena_skills import get_arena_leaderboard
        assert callable(get_arena_leaderboard)

    def test_list_arena_fighters_callable(self):
        """list_arena_fighters must be a callable."""
        from content.scenes.arena.arena_skills import list_arena_fighters
        assert callable(list_arena_fighters)


# ══════════════════════════════════════════════════════════════════════
#  SKILL LOGIC (mocked scene)
# ══════════════════════════════════════════════════════════════════════


def _make_mock_match():
    """Build a lightweight mock ArenaMatch object."""
    from types import SimpleNamespace
    card_a = SimpleNamespace(
        name="Iron Fist", card_type=SimpleNamespace(value="ATTACK"),
        power=4, flavor_text="A strike.",
    )
    card_b = SimpleNamespace(
        name="Iron Shield", card_type=SimpleNamespace(value="DEFENSE"),
        power=5, flavor_text="A shield.",
    )
    outcome = SimpleNamespace(
        round_num=1,
        fighter_a_card=card_a,
        fighter_b_card=card_b,
        fighter_a_reasoning="Attack now",
        fighter_b_reasoning="Block incoming",
        winner="fighter_a",
        damage_a=0,
        damage_b=4,
        commentary="Fighter A lands a solid blow!",
        special_triggered="",
    )
    bet = SimpleNamespace(
        id="bet-001",
        bet_type="match_winner",
        target="fighter_a",
        amount=100,
        to_dict=lambda: {
            "id": "bet-001",
            "bet_type": "match_winner",
            "target": "fighter_a",
            "amount": 100,
        },
    )
    fighter_a = SimpleNamespace(
        id="shadow", name="Shadow", hp=92, max_hp=100,
        persona="Stealthy assassin", model_id="qwen3-4b",
        wins=2, losses=1, draws=0,
        deck=[], hand=[], stats={"last_response_ms": 450},
        to_dict=lambda: {"id": "shadow", "name": "Shadow", "hp": 92, "max_hp": 100},
    )
    fighter_b = SimpleNamespace(
        id="blaze", name="Blaze", hp=96, max_hp=100,
        persona="Fire warrior", model_id="qwen3-4b",
        wins=1, losses=2, draws=0,
        deck=[], hand=[], stats={"last_response_ms": 380},
        to_dict=lambda: {"id": "blaze", "name": "Blaze", "hp": 96, "max_hp": 100},
    )
    from engine.arena.arena_engine import MatchStatus
    match = SimpleNamespace(
        id="match-001",
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        status=MatchStatus.IN_PROGRESS,
        rounds=[],
        bets=[],
        max_rounds=7,
        winner=None,
        to_dict=lambda: {
            "id": "match-001",
            "fighter_a": fighter_a.to_dict(),
            "fighter_b": fighter_b.to_dict(),
            "status": "IN_PROGRESS",
            "rounds": [],
            "bets": [],
            "max_rounds": 7,
            "winner": None,
        },
    )
    return match, outcome, bet, fighter_a, fighter_b


class TestCreateArenaMatchSkill:
    """Tests for the create_arena_match skill function."""

    def test_create_arena_match_no_scene(self):
        """Should return a friendly string when arena is not active."""
        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=None,
        ):
            from content.scenes.arena.arena_skills import create_arena_match
            result = create_arena_match("shadow", "blaze")
        assert "not active" in result.lower()

    def test_create_arena_match_success(self):
        """Should return match ID and fighter names on success."""
        match, *_ = _make_mock_match()
        mock_engine = MagicMock()
        mock_engine.create_match.return_value = match

        mock_scene = MagicMock()
        type(mock_scene)._engine = PropertyMock(return_value=mock_engine)

        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=mock_scene,
        ):
            from content.scenes.arena.arena_skills import create_arena_match
            result = create_arena_match("shadow", "blaze")

        assert "match-001" in result
        mock_engine.create_match.assert_called_once_with("shadow", "blaze")


class TestPlayArenaRoundSkill:
    """Tests for the play_arena_round skill function."""

    def test_play_arena_round_no_scene(self):
        """Should return a friendly string when arena is not active."""
        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=None,
        ):
            from content.scenes.arena.arena_skills import play_arena_round
            result = play_arena_round("match-001")
        assert "not active" in result.lower()

    def test_play_arena_round_success(self):
        """Should return round summary with cards and commentary."""
        match, outcome, *_ = _make_mock_match()
        mock_engine = MagicMock()
        mock_engine.play_round.return_value = outcome
        mock_engine._matches = {"match-001": match}

        mock_scene = MagicMock()
        type(mock_scene)._engine = PropertyMock(return_value=mock_engine)

        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=mock_scene,
        ):
            from content.scenes.arena.arena_skills import play_arena_round
            result = play_arena_round("match-001")

        assert "Round 1" in result
        assert "Iron Fist" in result
        assert "Iron Shield" in result
        assert "commentary" in result.lower() or "Fighter A" in result


class TestPlaceArenaBetSkill:
    """Tests for the place_arena_bet skill function."""

    def test_place_arena_bet_no_scene(self):
        """Should return a friendly string when arena is not active."""
        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=None,
        ):
            from content.scenes.arena.arena_skills import place_arena_bet
            result = place_arena_bet("match-001", "fighter_a", 100)
        assert "not active" in result.lower()

    def test_place_arena_bet_zero_amount(self):
        """Should reject non-positive amounts."""
        mock_scene = MagicMock()
        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=mock_scene,
        ):
            from content.scenes.arena.arena_skills import place_arena_bet
            result = place_arena_bet("match-001", "fighter_a", 0)
        assert "positive" in result.lower() or "invalid" in result.lower() or "amount" in result.lower()

    def test_place_arena_bet_success(self):
        """Should confirm the bet was placed with its ID."""
        match, _, bet, *_ = _make_mock_match()
        mock_engine = MagicMock()
        mock_engine.place_bet.return_value = bet

        mock_scene = MagicMock()
        type(mock_scene)._engine = PropertyMock(return_value=mock_engine)

        with patch(
            "content.scenes.arena.arena_skills._get_arena_scene",
            return_value=mock_scene,
        ):
            from content.scenes.arena.arena_skills import place_arena_bet
            result = place_arena_bet("match-001", "fighter_a", 100, "match_winner")

        assert "bet-001" in result or "Bet placed" in result


# ══════════════════════════════════════════════════════════════════════
#  STATIC ASSETS
# ══════════════════════════════════════════════════════════════════════


class TestArenaStaticAssets:
    """Confirm required static files exist on disk."""

    def test_arena_html_exists(self):
        """templates/arena.html must exist."""
        html = ARENA_DIR / "templates" / "arena.html"
        assert html.exists(), f"Missing: {html}"

    def test_arena_css_exists(self):
        """static/arena.css must exist."""
        css = ARENA_DIR / "static" / "arena.css"
        assert css.exists(), f"Missing: {css}"

    def test_arena_js_exists(self):
        """static/arena.js must exist."""
        js = ARENA_DIR / "static" / "arena.js"
        assert js.exists(), f"Missing: {js}"

    def test_arena_html_has_fighter_panels(self):
        """arena.html must contain both fighter panel elements."""
        html = (ARENA_DIR / "templates" / "arena.html").read_text(encoding="utf-8")
        assert "fighter-a" in html
        assert "fighter-b" in html

    def test_arena_html_has_commentary_feed(self):
        """arena.html must contain the commentary feed element."""
        html = (ARENA_DIR / "templates" / "arena.html").read_text(encoding="utf-8")
        assert "commentary-feed" in html

    def test_arena_html_has_bet_panel(self):
        """arena.html must contain the betting panel."""
        html = (ARENA_DIR / "templates" / "arena.html").read_text(encoding="utf-8")
        assert "arena-bet-panel" in html

    def test_arena_js_has_arena_scene_class(self):
        """arena.js must define the ArenaScene class."""
        js = (ARENA_DIR / "static" / "arena.js").read_text(encoding="utf-8")
        assert "class ArenaScene" in js

    def test_arena_css_has_arena_floor(self):
        """arena.css must define .arena-floor styles."""
        css = (ARENA_DIR / "static" / "arena.css").read_text(encoding="utf-8")
        assert ".arena-floor" in css


# ══════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════


class TestArenaConfig:
    """Verify port 5561 is declared in config/default.yaml."""

    def test_arena_port_in_config(self):
        """config/default.yaml must declare arena port 5561."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        cfg_path = PROJECT_ROOT / "config" / "default.yaml"
        if not cfg_path.exists():
            pytest.skip("config/default.yaml not found")

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        arena_cfg = cfg.get("scenes", {}).get("arena", {})
        assert arena_cfg.get("port") == 5561, (
            f"Expected port 5561 for arena, got {arena_cfg.get('port')}"
        )
