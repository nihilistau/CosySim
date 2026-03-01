"""
Tests for NeonCity v0.68 "Dark Renaissance" revamp.

Covers scene metadata, skill registration, skill logic, and static asset
presence.  All engine subsystems are mocked so no running server is required.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCENE_PKG = "content.scenes.neoncity"
_SKILLS_MOD = f"{_SCENE_PKG}.neoncity_skills"
_SCENE_MOD = f"{_SCENE_PKG}.neoncity_scene"

#: Directory of the neoncity scene
_NEONCITY_DIR = Path(__file__).parent.parent / "content" / "scenes" / "neoncity"


def _mock_engine_modules() -> None:
    """Inject lightweight mocks for engine subsystems that are not under test.

    Base-scene classes are constructed as real ``type`` objects so that Python's
    metaclass machinery does not raise a conflict when ``NeonCityScene`` inherits
    from them.
    """
    # Real type objects — avoids MagicMock metaclass conflicts in class bodies
    _FakeBase = type("BaseScene", (), {
        "__init__": lambda self, *a, **kw: None,
        "get_health": lambda self: {},
    })
    _FakeMCP = type("MCPSceneMixin", (), {
        "__init_subclass__": classmethod(lambda cls, mcp_scene_id=None, **kw: None),
        "_mcp_init": lambda self: None,
        "_mcp_deregister_scene": lambda self: None,
        "mount_overlay": lambda self, *a, **kw: None,
        "mount_skills_server": lambda self, *a, **kw: None,
        "mcp": MagicMock(),
    })
    _FakeNexus = type("NexusSceneMixin", (), {
        "nexus_init": lambda self, *a: None,
        "nexus_flush": lambda self: None,
    })

    stubs: Dict[str, Any] = {
        "engine.scenes.base_scene":               MagicMock(BaseScene=_FakeBase, get_active_scene=MagicMock(return_value=None)),
        "engine.scenes.nexus_mixin":              MagicMock(NexusSceneMixin=_FakeNexus),
        "engine.mcp.framework":                   MagicMock(MCPSceneMixin=_FakeMCP, get_framework=MagicMock()),
        "engine.mcp.scene_state":                 MagicMock(),
        "engine.mcp.tag_registry":                MagicMock(),
        "engine.events.event_bus":                MagicMock(),
        "engine.economy.economy":                 MagicMock(),
        "engine.characters.reputation":           MagicMock(),
        "engine.mechanics.consequences":          MagicMock(),
        "engine.world.world_state":               MagicMock(),
        "engine.world.world_sim":                 MagicMock(),
        "engine.content.content_engine":          MagicMock(),
        "engine.director.scene_director":         MagicMock(),
        "content.shared":                         MagicMock(),
        "content.scenes.neoncity.neoncity_rules": MagicMock(),
        "content.scenes.neoncity.neoncity_state": MagicMock(
            NeonCityGameState=MagicMock,
            EVENT_POOL=[],
            PREFAB_TYPES={},
        ),
        "flask":         MagicMock(),
        "flask_cors":    MagicMock(),
        "flask_socketio":MagicMock(),
    }
    for name, mock in stubs.items():
        sys.modules.setdefault(name, mock)


# ── Test 1: Scene metadata ────────────────────────────────────────────────────

class TestNeonCitySceneMetadata:
    """Validate SCENE_METADATA fields on the module and class."""

    def test_neoncity_scene_metadata(self) -> None:
        """SCENE_METADATA should expose required v0.68 world-hub fields."""
        _mock_engine_modules()
        # Import fresh to pick up mocks
        mod_name = _SCENE_MOD
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        mod = importlib.import_module(mod_name)
        meta: dict = mod.SCENE_METADATA

        assert meta["name"] == "neoncity"
        assert meta["display_name"] == "NEON CITY"
        assert meta["port"] == 5563
        assert meta["type"] == "world_hub"
        assert meta["accent_color"] == "#06b6d4"
        assert meta["accent_rgb"] == "6 182 212"
        assert "description" in meta
        assert "faction" in meta["description"].lower() or "city" in meta["description"].lower()

    def test_neoncity_scene_metadata_on_class(self) -> None:
        """NeonCityScene.SCENE_METADATA should reference the same module-level dict."""
        _mock_engine_modules()
        mod_name = _SCENE_MOD
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        mod = importlib.import_module(mod_name)
        # Verify the class exposes SCENE_METADATA
        assert hasattr(mod, "SCENE_METADATA")
        assert mod.SCENE_METADATA["port"] == 5563


# ── Test 2: Skills registered ─────────────────────────────────────────────────

class TestNeonCitySkillsRegistered:
    """Verify the five required skill functions exist in neoncity_skills."""

    @pytest.fixture(autouse=True)
    def _patch_skill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace @skill decorator with a transparent pass-through."""
        _mock_engine_modules()
        dummy_skill = MagicMock(side_effect=lambda **kw: (lambda fn: fn))
        dummy_cat = MagicMock()
        dummy_cat.GAME = "game"

        fake_skill_mod = MagicMock()
        fake_skill_mod.skill = dummy_skill
        fake_skill_mod.SkillCategory = dummy_cat
        sys.modules["engine.skills.skill"] = fake_skill_mod

        # Force reimport
        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]

    def test_neoncity_skills_registered(self) -> None:
        """All five v0.68 skill functions must be importable."""
        mod = importlib.import_module(_SKILLS_MOD)
        expected = [
            "get_faction_status",
            "buy_city_intel",
            "city_news_feed",
            "credit_exchange",
            "check_reputation",
        ]
        for name in expected:
            assert hasattr(mod, name), f"Missing skill: {name}"
            assert callable(getattr(mod, name)), f"Not callable: {name}"


# ── Test 3: get_faction_status skill ─────────────────────────────────────────

class TestGetFactionStatusSkill:
    """Unit-test the get_faction_status skill function."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_engine_modules()
        # Patch @skill to no-op
        fake_skill_mod = MagicMock()
        fake_skill_mod.skill = MagicMock(side_effect=lambda **kw: (lambda fn: fn))
        fake_skill_mod.SkillCategory = MagicMock(GAME="game")
        sys.modules["engine.skills.skill"] = fake_skill_mod

        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]

    def test_get_faction_status_skill(self) -> None:
        """get_faction_status should return a string mentioning all factions."""
        # Mock reputation manager to return empty standings
        mock_rep = MagicMock()
        mock_rep.get_faction_standings.return_value = {}
        mock_rep_mod = MagicMock()
        mock_rep_mod.get_reputation_manager.return_value = mock_rep
        sys.modules["engine.characters.reputation"] = mock_rep_mod

        mod = importlib.import_module(_SKILLS_MOD)
        result: str = mod.get_faction_status()

        assert isinstance(result, str)
        assert len(result) > 0
        # All six factions must appear in the output
        for faction in ["OmniCorp", "NeoTech", "BlackMarket", "Ghost_Net", "SynthSec", "DeepState"]:
            assert faction in result, f"Faction missing from output: {faction}"

    def test_get_faction_status_bar_format(self) -> None:
        """Faction power bars should use block characters and pad to 10."""
        mock_rep = MagicMock()
        mock_rep.get_faction_standings.return_value = {}
        sys.modules["engine.characters.reputation"] = MagicMock(
            get_reputation_manager=MagicMock(return_value=mock_rep)
        )

        # Re-import after mock is in place
        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]
        mod = importlib.import_module(_SKILLS_MOD)
        result = mod.get_faction_status()

        # Should contain block chars
        assert "█" in result
        assert "░" in result


# ── Test 4: city_news_feed skill ──────────────────────────────────────────────

class TestCityNewsFeedSkill:
    """Unit-test the city_news_feed skill function."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        _mock_engine_modules()
        fake_skill_mod = MagicMock()
        fake_skill_mod.skill = MagicMock(side_effect=lambda **kw: (lambda fn: fn))
        fake_skill_mod.SkillCategory = MagicMock(GAME="game")
        sys.modules["engine.skills.skill"] = fake_skill_mod

        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]

    def test_city_news_feed_skill(self) -> None:
        """city_news_feed should return a non-empty string with the news header."""
        # WorldSim returns empty events
        mock_sim = MagicMock()
        mock_sim.get_all_events.return_value = []
        sys.modules["engine.world.world_sim"] = MagicMock(
            get_world_sim=MagicMock(return_value=mock_sim)
        )

        # WorldState returns a mock time
        mock_wt = MagicMock(game_day_name="Monday", game_hour=22, time_of_day="night")
        mock_ws = MagicMock()
        mock_ws.get_time.return_value = mock_wt
        mock_ws.get_active_events.return_value = []
        sys.modules["engine.world.world_state"] = MagicMock(
            get_world_state=MagicMock(return_value=mock_ws)
        )

        mod = importlib.import_module(_SKILLS_MOD)
        result: str = mod.city_news_feed()

        assert isinstance(result, str)
        assert "NEON CITY NEWS FEED" in result

    def test_city_news_feed_quiet_message(self) -> None:
        """With no events, feed should include 'ALL QUIET' message."""
        mock_sim = MagicMock()
        mock_sim.get_all_events.return_value = []
        sys.modules["engine.world.world_sim"] = MagicMock(
            get_world_sim=MagicMock(return_value=mock_sim)
        )
        mock_ws = MagicMock()
        mock_ws.get_time.side_effect = Exception("offline")
        mock_ws.get_active_events.return_value = []
        sys.modules["engine.world.world_state"] = MagicMock(
            get_world_state=MagicMock(return_value=mock_ws)
        )

        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]
        mod = importlib.import_module(_SKILLS_MOD)
        result: str = mod.city_news_feed()

        assert "ALL QUIET" in result


# ── Test 5: credit_exchange skill ─────────────────────────────────────────────

class TestCreditExchangeSkill:
    """Unit-test the credit_exchange skill function."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        _mock_engine_modules()
        fake_skill_mod = MagicMock()
        fake_skill_mod.skill = MagicMock(side_effect=lambda **kw: (lambda fn: fn))
        fake_skill_mod.SkillCategory = MagicMock(GAME="game")
        sys.modules["engine.skills.skill"] = fake_skill_mod
        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]

    def test_credit_exchange_invalid_direction(self) -> None:
        """Invalid direction should return an error string."""
        mod = importlib.import_module(_SKILLS_MOD)
        result = mod.credit_exchange(100, direction="sideways")
        assert "Invalid direction" in result

    def test_credit_exchange_deposit(self) -> None:
        """Deposit should call transact and return success message."""
        mock_economy = MagicMock()
        mock_economy.get_balance.return_value = 500
        mock_economy.transact.return_value = MagicMock()
        sys.modules["engine.economy.economy"] = MagicMock(
            get_economy_manager=MagicMock(return_value=mock_economy),
            TransactionType=MagicMock(EARN="EARN", SPEND="SPEND"),
        )
        for key in list(sys.modules.keys()):
            if key.startswith(_SKILLS_MOD):
                del sys.modules[key]
        mod = importlib.import_module(_SKILLS_MOD)
        result = mod.credit_exchange(200, direction="in")
        assert "Deposited" in result or "✅" in result


# ── Test 6: HTML template exists ──────────────────────────────────────────────

class TestNeonCityHTMLExists:
    def test_neoncity_html_exists(self) -> None:
        """neoncity.html must exist in the templates directory."""
        template = _NEONCITY_DIR / "templates" / "neoncity.html"
        assert template.exists(), f"Template not found: {template}"

    def test_neoncity_html_has_data_scene(self) -> None:
        """Template must include data-scene='neoncity' attribute."""
        template = _NEONCITY_DIR / "templates" / "neoncity.html"
        content = template.read_text(encoding="utf-8")
        assert 'data-scene="neoncity"' in content

    def test_neoncity_html_has_district_cards(self) -> None:
        """Template must include all 5 district card elements."""
        template = _NEONCITY_DIR / "templates" / "neoncity.html"
        content = template.read_text(encoding="utf-8")
        districts = [
            "black_market", "corporate_tower", "underground_club",
            "hacker_den", "street_level",
        ]
        for d in districts:
            assert d in content, f"District missing from template: {d}"

    def test_neoncity_html_has_faction_bars(self) -> None:
        """Template must include faction bar elements for all 6 factions."""
        template = _NEONCITY_DIR / "templates" / "neoncity.html"
        content = template.read_text(encoding="utf-8")
        for faction in ["OmniCorp", "NeoTech", "BlackMarket", "Ghost_Net", "SynthSec", "DeepState"]:
            assert faction in content, f"Faction missing from template: {faction}"

    def test_neoncity_html_has_socket_io(self) -> None:
        """Template must include Socket.IO script tag."""
        template = _NEONCITY_DIR / "templates" / "neoncity.html"
        content = template.read_text(encoding="utf-8")
        assert "socket.io" in content.lower()


# ── Test 7: CSS file exists ───────────────────────────────────────────────────

class TestNeonCityCSSExists:
    def test_neoncity_css_exists(self) -> None:
        """neoncity.css must exist in the static directory."""
        css = _NEONCITY_DIR / "static" / "neoncity.css"
        assert css.exists(), f"CSS not found: {css}"

    def test_neoncity_css_has_accent_color(self) -> None:
        """CSS must define the cyan accent color #06b6d4."""
        css = _NEONCITY_DIR / "static" / "neoncity.css"
        content = css.read_text(encoding="utf-8")
        assert "#06b6d4" in content

    def test_neoncity_css_has_district_card_class(self) -> None:
        """CSS must define .district-card style."""
        css = _NEONCITY_DIR / "static" / "neoncity.css"
        content = css.read_text(encoding="utf-8")
        assert ".district-card" in content

    def test_neoncity_css_has_faction_bars_class(self) -> None:
        """CSS must define .faction-bars style."""
        css = _NEONCITY_DIR / "static" / "neoncity.css"
        content = css.read_text(encoding="utf-8")
        assert ".faction-bars" in content


# ── Test 8: JS file exists ────────────────────────────────────────────────────

class TestNeonCityJSExists:
    def test_neoncity_js_exists(self) -> None:
        """neoncity.js must exist in the static directory."""
        js = _NEONCITY_DIR / "static" / "neoncity.js"
        assert js.exists(), f"JS not found: {js}"

    def test_neoncity_js_has_scene_class(self) -> None:
        """JS must define the NeonCityScene class."""
        js = _NEONCITY_DIR / "static" / "neoncity.js"
        content = js.read_text(encoding="utf-8")
        assert "class NeonCityScene" in content

    def test_neoncity_js_has_required_methods(self) -> None:
        """NeonCityScene must define all required methods."""
        js = _NEONCITY_DIR / "static" / "neoncity.js"
        content = js.read_text(encoding="utf-8")
        required = [
            "init()", "_setupSocket()", "loadCityState()",
            "visitDistrict(", "_renderDistricts(", "_renderFactionBars(",
            "_updateTicker(", "sendMessage()", "buyIntel()",
        ]
        for method in required:
            assert method in content, f"Method missing from JS: {method}"

    def test_neoncity_js_has_neon_city_app(self) -> None:
        """JS must expose NeonCityApp global singleton."""
        js = _NEONCITY_DIR / "static" / "neoncity.js"
        content = js.read_text(encoding="utf-8")
        assert "NeonCityApp" in content


# ── Test 9: Scene __init__ exports ───────────────────────────────────────────

class TestNeonCityPackageInit:
    def test_neoncity_init_exports(self) -> None:
        """__init__.py must export NeonCityScene and SCENE_METADATA."""
        init_file = _NEONCITY_DIR / "__init__.py"
        content = init_file.read_text(encoding="utf-8")
        assert "NeonCityScene" in content
        assert "SCENE_METADATA" in content


# ── Test 10: Scene plugin info ────────────────────────────────────────────────

class TestNeonCityPluginInfo:
    """Verify get_plugin_info returns required v0.68 fields."""

    def test_get_plugin_info_version(self) -> None:
        """get_plugin_info must report version 0.68 and type world_hub."""
        _mock_engine_modules()
        if _SCENE_MOD in sys.modules:
            del sys.modules[_SCENE_MOD]
        mod = importlib.import_module(_SCENE_MOD)

        # Instantiate scene with mocked super().__init__
        with patch.object(mod.NeonCityScene, "__init__", return_value=None):
            scene = mod.NeonCityScene.__new__(mod.NeonCityScene)
            scene.port = 5563
            info = scene.get_plugin_info()

        assert info["version"] == "0.68"
        assert info["type"] == "world_hub"
        assert info["accent_color"] == "#06b6d4"
        assert len(info["factions"]) == 6
        assert len(info["districts"]) == 5

    def test_get_plugin_info_skill_packs(self) -> None:
        """get_plugin_info must include neoncity skill pack."""
        _mock_engine_modules()
        if _SCENE_MOD in sys.modules:
            del sys.modules[_SCENE_MOD]
        mod = importlib.import_module(_SCENE_MOD)

        with patch.object(mod.NeonCityScene, "__init__", return_value=None):
            scene = mod.NeonCityScene.__new__(mod.NeonCityScene)
            scene.port = 5563
            info = scene.get_plugin_info()

        assert "neoncity" in info["skill_packs"]
