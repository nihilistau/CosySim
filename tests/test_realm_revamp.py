"""
Tests for THE SHATTERED THRONE — realm scene revamp (v0.68 Dark Renaissance).

Covers: scene metadata, skill registration, skill functions,
        template/static asset existence, Socket.IO handlers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Paths ───────────────────────────────────────────────────────────
SCENE_DIR     = Path(__file__).parents[1] / "content" / "scenes" / "realm"
TEMPLATES_DIR = SCENE_DIR / "templates"
STATIC_DIR    = SCENE_DIR / "static"

NEON_BASE = Path(__file__).parent.parent / "content" / "shared" / "templates" / "neon_base.html"


def _effective_content(raw: str) -> str:
    """If template extends neon_base.html, include base content for assertion checks."""
    if "extends 'neon_base.html'" in raw or 'extends "neon_base.html"' in raw:
        base = NEON_BASE.read_text(encoding="utf-8") if NEON_BASE.exists() else ""
        combined = raw + "\n" + base
        m = re.search(r"{%\s*set\s+scene_key\s*=\s*['\"](\w+)['\"]", raw)
        if m:
            combined = combined.replace("{{ scene_key }}", m.group(1))
        return combined
    return raw


# ═════════════════════════════════════════════════════════════════════
#  1. SCENE METADATA
# ═════════════════════════════════════════════════════════════════════

class TestRealmSceneMetadata:
    def test_realm_scene_metadata(self):
        """SCENE_METADATA must reflect THE SHATTERED THRONE v0.68 brand."""
        from content.scenes.realm import SCENE_METADATA
        assert SCENE_METADATA["name"]         == "realm"
        assert SCENE_METADATA["display_name"] == "THE SHATTERED THRONE"
        assert SCENE_METADATA["port"]         == 5562
        assert SCENE_METADATA["type"]         == "rpg"
        assert SCENE_METADATA["accent_color"] == "#059669"
        assert SCENE_METADATA["accent_rgb"]   == "5 150 105"
        assert "throne" in SCENE_METADATA["description"].lower()

    def test_realm_scene_metadata_on_class(self):
        """RealmScene.SCENE_METADATA class attribute must match package constant."""
        from content.scenes.realm.realm_scene import RealmScene
        md = RealmScene.SCENE_METADATA
        assert md["display_name"] == "THE SHATTERED THRONE"
        assert md["port"] == 5562
        assert md["accent_color"] == "#059669"

    def test_plugin_info_version(self):
        """get_plugin_info must report version 0.68."""
        scene = _make_realm_scene()
        info = scene.get_plugin_info()
        assert info["version"] == "0.68"
        assert info["name"] == "THE SHATTERED THRONE"
        assert "#059669" in json.dumps(info)


# ═════════════════════════════════════════════════════════════════════
#  2. SKILLS REGISTERED
# ═════════════════════════════════════════════════════════════════════

class TestRealmSkillsRegistered:
    def test_realm_skills_registered(self):
        """All v0.68 @skill functions must be importable and callable."""
        from content.scenes.realm import realm_skills  # noqa: F401 triggers registration
        from engine.skills.registry import SKILL_REGISTRY
        pack_skills = SKILL_REGISTRY.get_pack_tools("realm")
        assert len(pack_skills) >= 5, f"Expected ≥5 realm skills, got {len(pack_skills)}"

    def test_new_skills_present_in_registry(self):
        """Shattered Throne v0.68 skill names must exist in the registry."""
        from content.scenes.realm import realm_skills  # noqa: F401
        from engine.skills.registry import SKILL_REGISTRY
        registered_names = {t.__name__ for t in SKILL_REGISTRY.get_pack_tools("realm")}
        for expected in ("realm_state", "get_story_arcs", "start_story_arc", "make_choice", "player_stats"):
            assert expected in registered_names, f"Skill '{expected}' not registered"


# ═════════════════════════════════════════════════════════════════════
#  3. SKILL FUNCTION BEHAVIOUR
# ═════════════════════════════════════════════════════════════════════

class TestRealmStateSkill:
    def test_realm_state_skill_no_scene(self):
        """realm_state() must return a safe string when no scene is active."""
        with patch("content.scenes.realm.realm_skills._get_realm_scene", return_value=None):
            from content.scenes.realm.realm_skills import realm_state
            result = realm_state()
            assert isinstance(result, str)
            assert len(result) > 0
            assert "no active" in result.lower() or "shattered throne" in result.lower()

    def test_realm_state_skill_with_mock_scene(self):
        """realm_state() must return full state details when a mock scene is active."""
        mock_scene = _mock_realm_scene()
        with patch("content.scenes.realm.realm_skills._get_realm_scene", return_value=mock_scene):
            from content.scenes.realm.realm_skills import realm_state
            result = realm_state()
        assert "HP" in result
        assert "MP" in result
        assert "Sanity" in result or "Turn" in result
        assert "Level" in result


class TestGetStoryArcsSkill:
    def test_get_story_arcs_skill(self):
        """get_story_arcs() must return all 5 dark arc IDs."""
        from content.scenes.realm.realm_skills import get_story_arcs
        result = get_story_arcs()
        assert isinstance(result, str)
        for arc in ("corruption", "forbidden_magic", "betrayal", "lovecraftian", "political_intrigue"):
            assert arc in result, f"Arc '{arc}' missing from get_story_arcs() output"

    def test_get_story_arcs_format(self):
        """get_story_arcs() must include arc icons and titles."""
        from content.scenes.realm.realm_skills import get_story_arcs
        result = get_story_arcs()
        assert "☠" in result or "📖" in result or "🗡" in result
        assert "DARK STORY ARCS" in result.upper() or "shattered throne" in result.lower()


class TestStartStoryArcSkill:
    def test_start_story_arc_invalid(self):
        """start_story_arc with unknown arc_id returns helpful error."""
        with patch("content.scenes.realm.realm_skills._get_realm_scene", return_value=None):
            from content.scenes.realm.realm_skills import start_story_arc
            result = start_story_arc("nonexistent_arc")
            assert "no active" in result.lower() or "unknown arc" in result.lower()

    def test_start_story_arc_sets_active_arc(self):
        """start_story_arc sets active_arc on the scene state."""
        mock_scene = _mock_realm_scene()
        with patch("content.scenes.realm.realm_skills._get_realm_scene", return_value=mock_scene):
            from content.scenes.realm.realm_skills import start_story_arc
            result = start_story_arc("corruption")
        assert "corruption" in result.lower() or "activated" in result.lower()
        assert mock_scene.state.active_arc == "corruption"


class TestPlayerStatsSkill:
    def test_player_stats_no_scene(self):
        """player_stats() returns safe fallback when no game active."""
        with patch("content.scenes.realm.realm_skills._get_realm_scene", return_value=None):
            from content.scenes.realm.realm_skills import player_stats
            result = player_stats()
            assert isinstance(result, str)

    def test_player_stats_includes_sanity(self):
        """player_stats() output must include Sanity."""
        mock_scene = _mock_realm_scene()
        with patch("content.scenes.realm.realm_skills._get_realm_scene", return_value=mock_scene):
            from content.scenes.realm.realm_skills import player_stats
            result = player_stats()
        assert "Sanity" in result
        assert "HP" in result
        assert "MP" in result


# ═════════════════════════════════════════════════════════════════════
#  4. STATIC ASSET EXISTENCE
# ═════════════════════════════════════════════════════════════════════

class TestRealmAssetFiles:
    def test_realm_html_exists(self):
        """templates/realm.html must exist."""
        assert (TEMPLATES_DIR / "realm.html").is_file(), \
            "Missing templates/realm.html"

    def test_realm_css_exists(self):
        """static/realm.css must exist."""
        assert (STATIC_DIR / "realm.css").is_file(), \
            "Missing static/realm.css"

    def test_realm_js_exists(self):
        """static/realm.js must exist."""
        assert (STATIC_DIR / "realm.js").is_file(), \
            "Missing static/realm.js"

    def test_realm_html_has_data_scene(self):
        """realm.html must declare data-scene='realm' on the body."""
        html = _effective_content((TEMPLATES_DIR / "realm.html").read_text(encoding="utf-8"))
        assert 'data-scene="realm"' in html

    def test_realm_html_has_socketio(self):
        """realm.html must load Socket.IO."""
        html = _effective_content((TEMPLATES_DIR / "realm.html").read_text(encoding="utf-8"))
        assert "socket.io" in html.lower()

    def test_realm_css_has_sanity_low(self):
        """realm.css must define .sanity-low selector."""
        css = (STATIC_DIR / "realm.css").read_text(encoding="utf-8")
        assert ".sanity-low" in css

    def test_realm_css_has_stat_bars(self):
        """realm.css must define HP, MP, XP, and Sanity stat bar fills."""
        css = (STATIC_DIR / "realm.css").read_text(encoding="utf-8")
        for selector in (".stat-bar.hp", ".stat-bar.mp", ".stat-bar.xp", ".stat-bar.sanity"):
            assert selector in css, f"Missing CSS selector: {selector}"

    def test_realm_css_has_inventory_grid(self):
        """realm.css must define .inventory-grid."""
        css = (STATIC_DIR / "realm.css").read_text(encoding="utf-8")
        assert ".inventory-grid" in css

    def test_realm_css_has_spell_bar(self):
        """realm.css must define .spell-bar."""
        css = (STATIC_DIR / "realm.css").read_text(encoding="utf-8")
        assert ".spell-bar" in css

    def test_realm_js_has_shattered_throne_class(self):
        """realm.js must define the ShatteredThroneScene class."""
        js = (STATIC_DIR / "realm.js").read_text(encoding="utf-8")
        assert "class ShatteredThroneScene" in js

    def test_realm_js_has_typewriter(self):
        """realm.js must implement _typewriterReveal."""
        js = (STATIC_DIR / "realm.js").read_text(encoding="utf-8")
        assert "_typewriterReveal" in js

    def test_realm_js_has_sparks(self):
        """realm.js must implement spawnSparks for level-up particles."""
        js = (STATIC_DIR / "realm.js").read_text(encoding="utf-8")
        assert "spawnSparks" in js


# ═════════════════════════════════════════════════════════════════════
#  5. SOCKET.IO HANDLER REGISTRATION
# ═════════════════════════════════════════════════════════════════════

class TestRealmSocketIOHandlers:
    def test_socketio_handlers_registered(self):
        """All required Socket.IO events must be registered on the scene."""
        scene = _make_realm_scene()
        handler_names = {h.event for h in getattr(scene.socketio, "handlers", {}).get("/", [])}
        # Check via scene source that events are wired
        from content.scenes.realm import realm_scene as rs_module
        source = Path(rs_module.__file__).read_text(encoding="utf-8")
        required_events = [
            "get_realm_state", "get_story_arcs", "start_arc",
            "player_choice", "cast_spell", "inventory_action",
        ]
        for event in required_events:
            assert f'"{event}"' in source or f"'{event}'" in source, \
                f"Socket.IO event '{event}' not found in realm_scene.py"


# ═════════════════════════════════════════════════════════════════════
#  Helpers
# ═════════════════════════════════════════════════════════════════════

def _make_realm_scene():
    """Instantiate a RealmScene with all external dependencies mocked."""
    with (
        patch("content.scenes.realm.realm_scene.register_shared_assets"),
        patch("content.scenes.realm.realm_scene.CORS"),
        patch("content.scenes.realm.realm_scene.SocketIO", return_value=MagicMock()),
        patch("content.scenes.realm.realm_scene.MCPSceneMixin._mcp_init"),
        patch("engine.scenes.base_scene.BaseScene.mount_overlay"),
        patch("engine.scenes.base_scene.BaseScene.mount_skills_server"),
        patch("engine.scenes.base_scene.BaseScene.register_health_route"),
        patch("engine.scenes.base_scene.BaseScene.register_bench_route"),
        patch("engine.scenes.base_scene.BaseScene.register_tts_route"),
        patch("content.scenes.realm.realm_scene.get_scene_state_manager", return_value=MagicMock()),
        patch("content.scenes.realm.realm_scene.TagRegistry.get", return_value=MagicMock()),
        patch("content.scenes.realm.realm_scene.register_realm_rules"),
        patch("content.scenes.realm.realm_scene.NexusSceneMixin.nexus_init"),
    ):
        from content.scenes.realm.realm_scene import RealmScene
        return RealmScene(host="localhost", port=5562)


def _mock_realm_scene():
    """Create a mock scene with a fully-populated state object."""
    mock_state = MagicMock()
    mock_state.player_stats = {
        "hp": 85, "max_hp": 100,
        "mp": 40, "max_mp": 50,
        "xp": 250, "xp_next": 500,
        "level": 3,
        "gold": 150,
        "strength": 12, "agility": 10, "intellect": 14,
        "charisma": 8,  "luck": 11,
    }
    mock_state.director_personality = "dark"
    mock_state.director_patience    = 72.0
    mock_state.turn_number          = 7
    mock_state.current_location     = "ruined_throne_room"
    mock_state.active_quests        = [{"title": "Claim the Shard", "objective": "Find the throne fragment"}]
    mock_state.inventory            = [{"id": "void_dagger", "name": "Void Dagger", "type": "weapon"}]
    mock_state.ended                = False
    mock_state.current_choices      = [
        {"id": "a", "text": "Take the dark bargain"},
        {"id": "b", "text": "Refuse the entity"},
    ]
    mock_state.sanity = 68
    mock_state.active_arc = None

    mock_scene = MagicMock()
    mock_scene.state = mock_state
    return mock_scene
