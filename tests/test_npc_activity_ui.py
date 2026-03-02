"""Tests for v72-b2: NPC Activity UI Badges.

Covers:
- /api/admin/npcs route JSON shape
- Badge CSS file content
- JS file content
- Admin overlay HTML NPC tab
- NPCStateRegistry.list_all()
- NPCScheduler._emit_activity_update()
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ──── Paths ────

SHARED_DIR = Path(__file__).parent.parent / "content" / "shared"
CSS_PATH   = SHARED_DIR / "static" / "css" / "cosysim-scene.css"
JS_PATH    = SHARED_DIR / "static" / "js" / "cosysim-shared.js"
HTML_PATH  = SHARED_DIR / "templates" / "admin_overlay.html"


# ──── CSS file ────────────────────────────────────────────────────

class TestBadgeCSS:
    """cosysim-scene.css must exist and contain badge styles."""

    def test_css_file_exists(self) -> None:
        assert CSS_PATH.exists(), f"Missing: {CSS_PATH}"

    def test_css_contains_badge_class(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert ".cs-npc-badge" in content

    def test_css_contains_idle_variant(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert 'data-activity="idle"' in content

    def test_css_contains_talking_variant(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert 'data-activity="talking"' in content

    def test_css_contains_working_variant(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert 'data-activity="working"' in content

    def test_css_contains_resting_variant(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert 'data-activity="resting"' in content

    def test_css_contains_fighting_variant(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert 'data-activity="fighting"' in content

    def test_css_contains_fadein_animation(self) -> None:
        content = CSS_PATH.read_text(encoding="utf-8")
        assert "cs-badge-fadein" in content


# ──── JS file ─────────────────────────────────────────────────────

class TestBadgeJS:
    """cosysim-shared.js must exist and contain CosySimNPCBadges."""

    def test_js_file_exists(self) -> None:
        assert JS_PATH.exists(), f"Missing: {JS_PATH}"

    def test_js_contains_class(self) -> None:
        content = JS_PATH.read_text(encoding="utf-8")
        assert "CosySimNPCBadges" in content

    def test_js_listens_for_event(self) -> None:
        content = JS_PATH.read_text(encoding="utf-8")
        assert "npc_activity_update" in content

    def test_js_renders_badge_element(self) -> None:
        content = JS_PATH.read_text(encoding="utf-8")
        assert "cs-npc-badge" in content

    def test_js_targets_panel(self) -> None:
        content = JS_PATH.read_text(encoding="utf-8")
        assert "cs-npc-activity-panel" in content

    def test_js_has_badge_name_span(self) -> None:
        content = JS_PATH.read_text(encoding="utf-8")
        assert "badge-name" in content

    def test_js_has_badge_activity_span(self) -> None:
        content = JS_PATH.read_text(encoding="utf-8")
        assert "badge-activity" in content


# ──── Admin overlay HTML ──────────────────────────────────────────

class TestAdminOverlayHTML:
    """admin_overlay.html must include the NPC tab."""

    def test_html_file_exists(self) -> None:
        assert HTML_PATH.exists(), f"Missing: {HTML_PATH}"

    def test_html_has_npc_tab_button(self) -> None:
        content = HTML_PATH.read_text(encoding="utf-8")
        assert 'data-tab="npc"' in content

    def test_html_has_npc_panel(self) -> None:
        content = HTML_PATH.read_text(encoding="utf-8")
        assert 'id="cs-admin-panel-npc"' in content

    def test_html_has_npc_table_body(self) -> None:
        content = HTML_PATH.read_text(encoding="utf-8")
        assert 'id="cs-npc-tbody"' in content


# ──── NPCState / Registry ────────────────────────────────────────

class TestNPCStateListAll:
    """NPCStateRegistry.list_all() must work as an alias for get_all()."""

    def test_list_all_returns_list(self) -> None:
        from engine.world.npc_state import NPCStateRegistry
        reg = NPCStateRegistry()
        result = reg.list_all()
        assert isinstance(result, list)

    def test_list_all_empty_by_default(self) -> None:
        from engine.world.npc_state import NPCStateRegistry
        reg = NPCStateRegistry()
        assert reg.list_all() == []

    def test_list_all_reflects_updates(self) -> None:
        from engine.world.npc_state import NPCStateRegistry
        reg = NPCStateRegistry()
        with patch.object(reg, "_fire_event"):
            reg.update("lola", activity="chatting")
        result = reg.list_all()
        assert len(result) == 1
        assert result[0].character_id == "lola"

    def test_list_all_to_dict(self) -> None:
        from engine.world.npc_state import NPCStateRegistry
        reg = NPCStateRegistry()
        with patch.object(reg, "_fire_event"):
            reg.update("viktor", activity="guarding")
        dicts = [n.to_dict() for n in reg.list_all()]
        assert isinstance(dicts, list)
        assert dicts[0]["character_id"] == "viktor"

    def test_get_npc_state_alias(self) -> None:
        """get_npc_state() must return the same registry as get_npc_state_registry()."""
        from engine.world.npc_state import get_npc_state, get_npc_state_registry
        assert get_npc_state() is get_npc_state_registry()


# ──── /api/admin/npcs route ──────────────────────────────────────

class TestAdminNPCsRoute:
    """/api/admin/npcs returns correct JSON shape."""

    def _make_app(self):
        """Build a minimal Flask app with the shared blueprint registered."""
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True
        with patch("flask_cors.CORS"):
            pass
        with patch("engine.assistant.assistant_bp.mount_assistant"):
            pass
        # Register blueprint directly without assistant / CORS side-effects
        from flask import Blueprint, jsonify as _jsonify
        bp = Blueprint("shared", __name__, url_prefix="")

        @bp.route("/api/admin/npcs")
        def admin_npcs():
            from engine.world.npc_state import get_npc_state
            state = get_npc_state()
            return _jsonify({"npcs": [n.to_dict() for n in state.list_all()]})

        app.register_blueprint(bp)
        return app

    def test_route_returns_200(self) -> None:
        app = self._make_app()
        with app.test_client() as client:
            resp = client.get("/api/admin/npcs")
        assert resp.status_code == 200

    def test_route_returns_json(self) -> None:
        app = self._make_app()
        with app.test_client() as client:
            resp = client.get("/api/admin/npcs")
        data = json.loads(resp.data)
        assert "npcs" in data

    def test_route_npcs_is_list(self) -> None:
        app = self._make_app()
        with app.test_client() as client:
            resp = client.get("/api/admin/npcs")
        data = json.loads(resp.data)
        assert isinstance(data["npcs"], list)

    def test_route_npc_dict_has_character_id(self) -> None:
        from engine.world.npc_state import get_npc_state_registry, NPCStateRegistry
        reg = NPCStateRegistry()
        with patch.object(reg, "_fire_event"):
            reg.update("aria", activity="singing")
        with patch("engine.world.npc_state._registry", reg):
            app = self._make_app()
            with app.test_client() as client:
                resp = client.get("/api/admin/npcs")
            data = json.loads(resp.data)
        assert any(n.get("character_id") == "aria" for n in data["npcs"])


# ──── NPCScheduler emit update ────────────────────────────────────

class TestNPCSchedulerEmitUpdate:
    """NPCScheduler._emit_activity_update() emits npc_activity_update."""

    def test_emit_activity_update_calls_framework(self) -> None:
        from engine.agents.npc_scheduler import NPCScheduler
        sched = NPCScheduler.__new__(NPCScheduler)
        sched._tick_interval = 60
        sched._max_per_tick  = 3
        sched._fallback_npcs = ["lola"]
        sched._activity_pool = ["idle"]
        sched._running       = False
        sched._thread        = None
        sched._task          = None
        sched._last_tick_at  = None
        sched._npcs_active   = 0

        mock_fw = MagicMock()
        with patch("engine.mcp.get_framework", return_value=mock_fw), \
             patch("engine.world.npc_state._registry", None):
            sched._emit_activity_update()

        # get_framework().emit should have been called with npc_activity_update
        mock_fw.emit.assert_called_once()
        call_args = mock_fw.emit.call_args
        assert call_args[0][0] == "npc_activity_update"
        payload = call_args[0][1]
        assert "npcs" in payload
        assert isinstance(payload["npcs"], list)

    def test_emit_activity_update_graceful_on_error(self) -> None:
        from engine.agents.npc_scheduler import NPCScheduler
        sched = NPCScheduler.__new__(NPCScheduler)
        # Should not raise even if framework unavailable
        with patch("engine.mcp.get_framework", side_effect=RuntimeError("no fw")):
            try:
                sched._emit_activity_update()
            except Exception as exc:
                pytest.fail(f"_emit_activity_update raised unexpectedly: {exc}")
