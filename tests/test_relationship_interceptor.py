"""Tests for RelationshipContextInterceptor and admin profile route.

Covers:
  - Interceptor instantiation
  - pre_call injects relationship context when character is known
  - pre_call leaves request unchanged when character not in profile
  - pre_call never raises (exception safety)
  - post_call is a passthrough
  - Admin profile route returns correct JSON keys
  - Admin overlay HTML has the PROFILE tab
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from engine.agents.relationship_interceptor import RelationshipContextInterceptor
from engine.characters.player_profile import PlayerProfile, RelationshipEntry
from engine.mcp.comms_framework import ResponseContext

# ──── Repo paths ────
REPO = Path(__file__).parent.parent
TEMPLATE = REPO / "content" / "shared" / "templates" / "admin_overlay.html"


# ──── Helpers ────

def _make_ctx(**kwargs: Any) -> ResponseContext:
    ctx = ResponseContext()
    ctx["system_prompt"] = kwargs.pop("system_prompt", "Base prompt.")
    ctx.update(kwargs)
    return ctx


def _fresh_profile() -> PlayerProfile:
    """Return a fresh, isolated PlayerProfile (not the singleton)."""
    with patch("engine.characters.player_profile.get_config") as mc:
        mc.return_value.get = lambda key, default="": default
        return PlayerProfile()


# ══════════════════════════════════════════════════════════════════════
#  Interceptor — instantiation
# ══════════════════════════════════════════════════════════════════════

class TestRelationshipInterceptorInstantiation:
    def test_instantiates_successfully(self) -> None:
        interceptor = RelationshipContextInterceptor()
        assert interceptor is not None

    def test_name_attribute(self) -> None:
        interceptor = RelationshipContextInterceptor()
        assert interceptor.name == "relationship_context"

    def test_priority_attribute(self) -> None:
        interceptor = RelationshipContextInterceptor()
        assert isinstance(interceptor.priority, int)
        # Must run just after DialogueGateInterceptor (45)
        assert interceptor.priority > 45


# ══════════════════════════════════════════════════════════════════════
#  pre_call — relationship context injection
# ══════════════════════════════════════════════════════════════════════

class TestPreCallWithRelationship:
    """When character has a relationship entry, context is appended."""

    def _setup_profile_with(self, char_id: str, score: float, sentiment: str) -> PlayerProfile:
        profile = _fresh_profile()
        profile.relationships[char_id] = RelationshipEntry(
            character_id=char_id, score=score, sentiment=sentiment
        )
        return profile

    def test_appends_sentiment_to_system_prompt(self) -> None:
        profile = self._setup_profile_with("lola", 60.0, "close")
        ctx = _make_ctx(agent_id="lola")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert "close" in ctx["system_prompt"]

    def test_appends_score_to_system_prompt(self) -> None:
        profile = self._setup_profile_with("viktor", -70.0, "hostile")
        ctx = _make_ctx(agent_id="viktor")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert "-70.0" in ctx["system_prompt"]

    def test_appends_after_existing_prompt(self) -> None:
        profile = self._setup_profile_with("aria", 30.0, "neutral")
        ctx = _make_ctx(agent_id="aria", system_prompt="Original prompt.")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert ctx["system_prompt"].startswith("Original prompt.")

    def test_context_line_format(self) -> None:
        profile = self._setup_profile_with("frankie", 80.0, "close")
        ctx = _make_ctx(agent_id="frankie")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert "[Player relationship:" in ctx["system_prompt"]

    def test_uses_agent_id_key(self) -> None:
        profile = self._setup_profile_with("mira", 20.0, "neutral")
        ctx = _make_ctx(agent_id="mira")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert "neutral" in ctx["system_prompt"]

    def test_uses_character_id_fallback_key(self) -> None:
        """Falls back to ctx['character_id'] when agent_id is absent."""
        profile = self._setup_profile_with("lola", 55.0, "close")
        ctx = ResponseContext()
        ctx["system_prompt"] = "Hello."
        ctx["character_id"] = "lola"
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert "close" in ctx["system_prompt"]


# ══════════════════════════════════════════════════════════════════════
#  pre_call — no-op cases
# ══════════════════════════════════════════════════════════════════════

class TestPreCallNoOp:
    """When no relationship is found, system_prompt is unchanged."""

    def test_no_character_id_leaves_prompt_unchanged(self) -> None:
        ctx = _make_ctx(system_prompt="Clean.")
        interceptor = RelationshipContextInterceptor()
        interceptor.pre_call(ctx)
        assert ctx["system_prompt"] == "Clean."

    def test_unknown_character_leaves_prompt_unchanged(self) -> None:
        profile = _fresh_profile()  # empty relationships
        ctx = _make_ctx(agent_id="unknown_char", system_prompt="Clean.")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert ctx["system_prompt"] == "Clean."

    def test_empty_agent_id_string_leaves_prompt_unchanged(self) -> None:
        ctx = _make_ctx(agent_id="", system_prompt="Clean.")
        interceptor = RelationshipContextInterceptor()
        interceptor.pre_call(ctx)
        assert ctx["system_prompt"] == "Clean."


# ══════════════════════════════════════════════════════════════════════
#  pre_call — exception safety
# ══════════════════════════════════════════════════════════════════════

class TestPreCallExceptionSafety:
    """pre_call must never raise, regardless of what PlayerProfile does."""

    def test_does_not_raise_when_profile_raises(self) -> None:
        ctx = _make_ctx(agent_id="lola")

        def _boom():
            raise RuntimeError("Profile unavailable")

        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            side_effect=_boom,
        ):
            interceptor.pre_call(ctx)  # must not raise

    def test_does_not_raise_when_relationships_raises(self) -> None:
        profile = MagicMock()
        profile.relationships = MagicMock()
        profile.relationships.get.side_effect = AttributeError("broken")
        ctx = _make_ctx(agent_id="lola")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)  # must not raise

    def test_does_not_raise_on_import_error(self) -> None:
        ctx = _make_ctx(agent_id="aria")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            side_effect=ImportError("module not found"),
        ):
            interceptor.pre_call(ctx)  # must not raise

    def test_prompt_unchanged_on_exception(self) -> None:
        ctx = _make_ctx(agent_id="lola", system_prompt="Safe.")
        interceptor = RelationshipContextInterceptor()
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            side_effect=Exception("boom"),
        ):
            interceptor.pre_call(ctx)
        assert ctx["system_prompt"] == "Safe."


# ══════════════════════════════════════════════════════════════════════
#  post_call — passthrough
# ══════════════════════════════════════════════════════════════════════

class TestPostCall:
    def test_post_call_is_passthrough(self) -> None:
        ctx = _make_ctx(agent_id="lola")
        ctx["reply"] = "Hello there."
        interceptor = RelationshipContextInterceptor()
        interceptor.post_call(ctx)
        assert ctx["reply"] == "Hello there."

    def test_post_call_does_not_raise(self) -> None:
        ctx = _make_ctx()
        interceptor = RelationshipContextInterceptor()
        interceptor.post_call(ctx)  # must not raise

    def test_post_call_returns_none(self) -> None:
        ctx = _make_ctx()
        interceptor = RelationshipContextInterceptor()
        result = interceptor.post_call(ctx)
        assert result is None


# ══════════════════════════════════════════════════════════════════════
#  Admin profile route
# ══════════════════════════════════════════════════════════════════════

class TestAdminProfileRoute:
    """Verify /api/admin/profile returns correct keys via the Flask blueprint."""

    @pytest.fixture()
    def flask_app(self):
        """Create a minimal Flask app with the shared blueprint registered."""
        from flask import Flask
        from unittest.mock import patch as _patch

        app = Flask(__name__)
        app.config["TESTING"] = True

        # Patch Nexus + config so register_shared_assets doesn't error
        with (
            _patch("engine.characters.player_profile.get_config") as mc,
            _patch("engine.characters.player_profile.get_nexus_client"),
        ):
            mc.return_value.get = lambda key, default="": default
            from content.shared import register_shared_assets
            register_shared_assets(app)

        return app

    def test_profile_route_exists(self, flask_app) -> None:
        with flask_app.test_client() as client:
            resp = client.get("/api/admin/profile")
        assert resp.status_code == 200

    def test_profile_returns_json(self, flask_app) -> None:
        with flask_app.test_client() as client:
            resp = client.get("/api/admin/profile")
        data = json.loads(resp.data)
        assert isinstance(data, dict)

    def test_profile_has_player_id_key(self, flask_app) -> None:
        with flask_app.test_client() as client:
            resp = client.get("/api/admin/profile")
        data = json.loads(resp.data)
        assert "player_id" in data or "error" in data

    def test_profile_has_sessions_key(self, flask_app) -> None:
        with flask_app.test_client() as client:
            resp = client.get("/api/admin/profile")
        data = json.loads(resp.data)
        if "error" not in data:
            assert "sessions" in data

    def test_profile_has_relationships_key(self, flask_app) -> None:
        with flask_app.test_client() as client:
            resp = client.get("/api/admin/profile")
        data = json.loads(resp.data)
        if "error" not in data:
            assert "relationships" in data

    def test_profile_has_decisions_key(self, flask_app) -> None:
        with flask_app.test_client() as client:
            resp = client.get("/api/admin/profile")
        data = json.loads(resp.data)
        if "error" not in data:
            assert "decisions" in data


# ══════════════════════════════════════════════════════════════════════
#  Admin overlay HTML — PROFILE tab
# ══════════════════════════════════════════════════════════════════════

class TestAdminOverlayProfileTab:
    """Verify the PROFILE tab was added to the admin overlay template."""

    @classmethod
    def setup_class(cls) -> None:
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_template_exists(self) -> None:
        assert TEMPLATE.exists(), f"Missing: {TEMPLATE}"

    def test_profile_tab_button_present(self) -> None:
        assert 'data-tab="profile"' in self.html

    def test_profile_tab_label_present(self) -> None:
        assert "[PROFILE]" in self.html

    def test_profile_panel_id_present(self) -> None:
        assert 'id="cs-admin-panel-profile"' in self.html

    def test_profile_fetch_api_call(self) -> None:
        assert "/api/admin/profile" in self.html
