"""
Tests for CLUB NOIR Casino Revamp — v0.68 Dark Renaissance.

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


def _mock_scene(balance: int = 500, bj_state: dict | None = None) -> MagicMock:
    """Return a minimal CasinoScene mock for skills that call _get_casino_scene()."""
    scene = MagicMock()
    scene._economy_balance.return_value = balance
    scene._bj_state = bj_state or {
        "active": False,
        "game": "blackjack",
        "buy_in": 0,
        "bet": 0,
        "target": "player_win",
        "player_hand": [],
        "dealer_hand": [],
        "phase": "idle",
        "result": None,
        "winnings": 0,
    }
    scene._economy_spend.return_value = True
    scene._economy_credit.return_value = None
    scene._reputation_update.return_value = None
    scene._schedule_mira_call.return_value = None
    scene._publish_major_win.return_value = None

    # _bj_hand_value delegate
    def _bj_hand_value(hand):
        total = 0
        for card in hand:
            rank = card[:-1]
            if rank in ("J", "Q", "K"):
                total += 10
            elif rank == "A":
                total += 11
            else:
                try:
                    total += int(rank)
                except ValueError:
                    pass
        return total

    scene._bj_hand_value.side_effect = _bj_hand_value
    return scene


# ══════════════════════════════════════════════════════════════════════
#  1. Scene metadata
# ══════════════════════════════════════════════════════════════════════

class TestCasinoSceneMetadata:
    def test_scene_metadata_keys(self):
        from content.scenes.casino.casino_scene import CasinoScene
        meta = CasinoScene.SCENE_METADATA
        assert meta["name"]         == "casino"
        assert meta["display_name"] == "CLUB NOIR"
        assert meta["port"]         == 5559
        assert meta["type"]         == "gambling"
        assert meta["accent_color"] == "#f97316"
        assert meta["accent_rgb"]   == "249 115 22"
        assert "description" in meta

    def test_scene_metadata_description_flavour(self):
        from content.scenes.casino.casino_scene import CasinoScene
        desc = CasinoScene.SCENE_METADATA["description"]
        assert len(desc) > 10

    def test_casino_port_constant(self):
        from content.scenes.casino.casino_scene import CASINO_PORT
        assert CASINO_PORT == 5559

    def test_get_plugin_info_v068(self):
        """get_plugin_info must not instantiate Flask — patch __init__."""
        from content.scenes.casino import casino_scene as cs_mod
        scene = MagicMock(spec=cs_mod.CasinoScene)
        scene.port = 5559
        # Call the real method on the mock instance
        result = cs_mod.CasinoScene.get_plugin_info(scene)
        assert result["display_name"] == "CLUB NOIR"
        assert result["version"]      == "0.68"
        assert result["port"]         == 5559
        assert "casino" in result.get("tags", [])
        assert "#f97316" == result.get("accent_color")


# ══════════════════════════════════════════════════════════════════════
#  2. Skills registered in SKILL_REGISTRY
# ══════════════════════════════════════════════════════════════════════

class TestCasinoSkillsRegistered:
    def test_all_five_skills_registered(self):
        """Import casino_skills forces @skill registration."""
        import content.scenes.casino.casino_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        tools = SKILL_REGISTRY.get_pack_tools("casino")
        registered = {fn.__name__ for fn in tools}
        expected = {"casino_state", "join_table", "place_bet", "make_decision", "cash_out"}
        missing  = expected - registered
        assert not missing, f"Skills not registered: {missing}"

    def test_skill_pack_is_casino(self):
        import content.scenes.casino.casino_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        for name in ("casino_state", "join_table", "place_bet", "make_decision", "cash_out"):
            meta = SKILL_REGISTRY.get_skill(name)
            assert meta is not None, f"Skill not found: {name}"
            assert meta.pack == "casino", f"{name}.pack = {meta.pack!r}"

    def test_skills_have_descriptions(self):
        import content.scenes.casino.casino_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY

        for name in ("casino_state", "join_table", "place_bet", "make_decision", "cash_out"):
            meta = SKILL_REGISTRY.get_skill(name)
            assert meta is not None
            assert meta.description, f"{name} has no description"


# ══════════════════════════════════════════════════════════════════════
#  3. casino_state skill
# ══════════════════════════════════════════════════════════════════════

class TestCasinoStateSkill:
    def test_returns_club_noir_header(self):
        from content.scenes.casino.casino_skills import casino_state
        mock = _mock_scene(balance=750)
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = casino_state()
        assert "CLUB NOIR" in result
        assert "750" in result

    def test_returns_no_table_when_inactive(self):
        from content.scenes.casino.casino_skills import casino_state
        mock = _mock_scene()
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = casino_state()
        assert "none" in result.lower() or "idle" in result.lower()

    def test_no_scene_returns_not_active(self):
        from content.scenes.casino.casino_skills import casino_state
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=None):
            result = casino_state()
        assert "not active" in result.lower()


# ══════════════════════════════════════════════════════════════════════
#  4. join_table skill
# ══════════════════════════════════════════════════════════════════════

class TestJoinTableSkill:
    def test_join_deducts_buy_in(self):
        from content.scenes.casino.casino_skills import join_table
        mock = _mock_scene()
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = join_table(game="blackjack", buy_in=200)
        mock._economy_spend.assert_called_once_with(200, reason="casino_buy_in:blackjack")
        assert "joined" in result.lower() or "blackjack" in result.lower()

    def test_join_fails_when_insufficient_credits(self):
        from content.scenes.casino.casino_skills import join_table
        mock = _mock_scene()
        mock._economy_spend.return_value = False
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = join_table(game="blackjack", buy_in=500)
        assert "insufficient" in result.lower()

    def test_join_fails_when_already_active(self):
        from content.scenes.casino.casino_skills import join_table
        mock = _mock_scene(bj_state={
            "active": True, "game": "blackjack", "buy_in": 100,
            "phase": "playing", "player_hand": [], "dealer_hand": [],
            "bet": 50, "result": None, "winnings": 0,
        })
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = join_table()
        assert "already" in result.lower()

    def test_join_activates_bj_state(self):
        from content.scenes.casino.casino_skills import join_table
        mock = _mock_scene()
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            join_table(game="blackjack", buy_in=150)
        assert mock._bj_state["active"] is True
        assert mock._bj_state["buy_in"] == 150


# ══════════════════════════════════════════════════════════════════════
#  5. place_bet skill
# ══════════════════════════════════════════════════════════════════════

class TestPlaceBetSkill:
    def test_place_bet_sets_bet(self):
        from content.scenes.casino.casino_skills import place_bet
        mock = _mock_scene(bj_state={
            "active": True, "game": "blackjack", "buy_in": 200,
            "phase": "betting", "player_hand": [], "dealer_hand": [],
            "bet": 0, "result": None, "winnings": 0,
        })
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = place_bet(amount=75)
        assert mock._bj_state["bet"] == 75
        assert "75" in result

    def test_place_bet_fails_when_inactive(self):
        from content.scenes.casino.casino_skills import place_bet
        mock = _mock_scene()
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = place_bet(amount=50)
        assert "join" in result.lower()

    def test_place_bet_rejects_over_buy_in(self):
        from content.scenes.casino.casino_skills import place_bet
        mock = _mock_scene(bj_state={
            "active": True, "game": "blackjack", "buy_in": 100,
            "phase": "betting", "player_hand": [], "dealer_hand": [],
            "bet": 0, "result": None, "winnings": 0,
        })
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            result = place_bet(amount=999)
        assert "1–" in result or "invalid" in result.lower() or "must be" in result.lower()

    def test_place_bet_sets_target(self):
        from content.scenes.casino.casino_skills import place_bet
        mock = _mock_scene(bj_state={
            "active": True, "game": "blackjack", "buy_in": 200,
            "phase": "betting", "player_hand": [], "dealer_hand": [],
            "bet": 0, "result": None, "winnings": 0,
        })
        with patch("content.scenes.casino.casino_skills._get_casino_scene", return_value=mock):
            place_bet(amount=50, target="blackjack")
        assert mock._bj_state["target"] == "blackjack"


# ══════════════════════════════════════════════════════════════════════
#  6. HTML file exists
# ══════════════════════════════════════════════════════════════════════

class TestCasinoHtmlExists:
    def test_html_file_exists(self):
        p = ROOT / "content" / "scenes" / "casino" / "templates" / "casino.html"
        assert p.exists(), f"Template not found: {p}"

    def test_html_contains_club_noir(self):
        p = ROOT / "content" / "scenes" / "casino" / "templates" / "casino.html"
        content = p.read_text(encoding="utf-8")
        assert "CLUB NOIR" in content

    def test_html_has_data_scene_casino(self):
        p = ROOT / "content" / "scenes" / "casino" / "templates" / "casino.html"
        content = p.read_text(encoding="utf-8")
        assert 'data-scene="casino"' in content

    def test_html_has_action_buttons(self):
        p = ROOT / "content" / "scenes" / "casino" / "templates" / "casino.html"
        content = p.read_text(encoding="utf-8")
        for action in ("HIT", "STAND", "DOUBLE", "FOLD"):
            assert action in content, f"Missing action button: {action}"

    def test_html_has_socket_io(self):
        p = ROOT / "content" / "scenes" / "casino" / "templates" / "casino.html"
        content = p.read_text(encoding="utf-8")
        assert "socket.io" in content.lower()

    def test_html_has_sparks_canvas(self):
        p = ROOT / "content" / "scenes" / "casino" / "templates" / "casino.html"
        content = p.read_text(encoding="utf-8")
        assert "sparks-canvas" in content


# ══════════════════════════════════════════════════════════════════════
#  7. CSS file exists
# ══════════════════════════════════════════════════════════════════════

class TestCasinoCssExists:
    def test_css_file_exists(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        assert p.exists(), f"CSS not found: {p}"

    def test_css_has_orange_accent(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        content = p.read_text(encoding="utf-8")
        assert "#f97316" in content

    def test_css_has_casino_table(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        content = p.read_text(encoding="utf-8")
        assert ".cn-table" in content

    def test_css_has_card_styles(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        content = p.read_text(encoding="utf-8")
        assert ".card" in content
        assert ".face-down" in content
        assert ".card-flip" in content

    def test_css_has_win_loss_flash(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        content = p.read_text(encoding="utf-8")
        assert "cn-flash--win" in content
        assert "cn-flash--loss" in content

    def test_css_has_consequence_badge(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        content = p.read_text(encoding="utf-8")
        assert "consequence-badge" in content

    def test_css_has_action_bar(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "css" / "casino.css"
        content = p.read_text(encoding="utf-8")
        assert "cn-action-bar" in content or "action-bar" in content


# ══════════════════════════════════════════════════════════════════════
#  8. JS file exists
# ══════════════════════════════════════════════════════════════════════

class TestCasinoJsExists:
    def test_js_file_exists(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "js" / "casino.js"
        assert p.exists(), f"JS not found: {p}"

    def test_js_has_club_noir_class(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "js" / "casino.js"
        content = p.read_text(encoding="utf-8")
        assert "ClubNoirScene" in content

    def test_js_has_required_methods(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "js" / "casino.js"
        content = p.read_text(encoding="utf-8")
        for method in ("init", "_setupSocket", "loadState", "joinTable", "placeBet",
                       "dealCards", "makeDecision", "cashOut", "_renderCards",
                       "_updateBalance", "_triggerWinEffect", "_triggerLossEffect",
                       "sendMessage"):
            assert method in content, f"Missing method: {method}"

    def test_js_has_sparks_particle_effect(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "js" / "casino.js"
        content = p.read_text(encoding="utf-8")
        assert "_launchSparks" in content
        assert "requestAnimationFrame" in content

    def test_js_bootstrap_sets_window_casino(self):
        p = ROOT / "content" / "scenes" / "casino" / "static" / "js" / "casino.js"
        content = p.read_text(encoding="utf-8")
        assert "window._casino" in content
