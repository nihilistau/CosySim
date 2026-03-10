"""Tests for THE RUSTY ANCHOR — tavern v0.68 'Dark Renaissance' revamp.

Covers: SCENE_METADATA, skill registration, skill behaviour, static asset
existence, and Socket.IO event handler presence.
"""
from __future__ import annotations

import importlib
import re
import os
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

TAVERN_DIR = os.path.join(os.path.dirname(__file__), "..", "content", "scenes", "tavern")
STATIC_DIR = os.path.join(TAVERN_DIR, "static")
TEMPLATE_DIR = os.path.join(TAVERN_DIR, "templates")

NEON_BASE = os.path.join(os.path.dirname(__file__), "..", "content", "shared", "templates", "neon_base.html")


def _effective_content(raw: str) -> str:
    """If template extends neon_base.html, include base content for assertion checks."""
    if "extends 'neon_base.html'" in raw or 'extends "neon_base.html"' in raw:
        base = open(NEON_BASE, encoding="utf-8").read() if os.path.isfile(NEON_BASE) else ""
        combined = raw + "\n" + base
        m = re.search(r"{%\s*set\s+scene_key\s*=\s*['\"](\w+)['\"]", raw)
        if m:
            combined = combined.replace("{{ scene_key }}", m.group(1))
        return combined
    return raw


# ---------------------------------------------------------------------------
#  1. SCENE_METADATA
# ---------------------------------------------------------------------------

class TestTavernSceneMetadata:
    """SCENE_METADATA has the correct v0.68 values."""

    def _meta(self):
        import content.scenes.tavern as pkg
        return pkg.SCENE_METADATA

    def test_tavern_scene_metadata_display_name(self):
        meta = self._meta()
        assert meta["display_name"] == "THE RUSTY ANCHOR", (
            "display_name must be 'THE RUSTY ANCHOR'"
        )

    def test_tavern_scene_metadata_port(self):
        meta = self._meta()
        assert meta["port"] == 5558

    def test_tavern_scene_metadata_accent_color(self):
        meta = self._meta()
        assert meta["accent_color"] == "#92400e"

    def test_tavern_scene_metadata_accent_rgb(self):
        meta = self._meta()
        assert meta["accent_rgb"] == "146 64 14"

    def test_tavern_scene_metadata_type(self):
        meta = self._meta()
        assert meta["type"] == "adventure"

    def test_tavern_scene_metadata_description(self):
        meta = self._meta()
        assert "quests" in meta["description"].lower() or "ale" in meta["description"].lower(), (
            "description should mention quests or ale"
        )

    def test_tavern_scene_class_metadata_matches(self):
        """TavernScene.SCENE_METADATA agrees with package-level metadata."""
        from content.scenes.tavern.tavern_scene import TavernScene
        import content.scenes.tavern as pkg
        assert TavernScene.SCENE_METADATA["port"] == pkg.SCENE_METADATA["port"]
        assert TavernScene.SCENE_METADATA["accent_color"] == pkg.SCENE_METADATA["accent_color"]

    def test_tavern_plugin_info_version(self):
        """get_plugin_info() reports v0.68."""
        from content.scenes.tavern.tavern_scene import TavernScene
        # Create without starting Flask
        with mock.patch.object(TavernScene, "__init__", lambda self, **kw: None):
            scene = TavernScene.__new__(TavernScene)
            scene.port = 5558
        info = TavernScene.get_plugin_info(scene)
        assert info["version"] == "0.68"
        assert info["display_name"] == "THE RUSTY ANCHOR"


# ---------------------------------------------------------------------------
#  2. Skills registered
# ---------------------------------------------------------------------------

class TestTavernSkillsRegistered:
    """All v0.68 skills are importable and decorated."""

    def _skills_module(self):
        return importlib.import_module("content.scenes.tavern.tavern_skills")

    def test_tavern_skills_registered_atmosphere(self):
        mod = self._skills_module()
        assert hasattr(mod, "tavern_atmosphere"), "tavern_atmosphere skill missing"
        assert callable(mod.tavern_atmosphere)

    def test_tavern_skills_registered_get_quest_board(self):
        mod = self._skills_module()
        assert hasattr(mod, "get_quest_board"), "get_quest_board skill missing"
        assert callable(mod.get_quest_board)

    def test_tavern_skills_registered_accept_quest(self):
        mod = self._skills_module()
        assert hasattr(mod, "accept_quest"), "accept_quest skill missing"
        assert callable(mod.accept_quest)

    def test_tavern_skills_registered_roll_dice(self):
        mod = self._skills_module()
        assert hasattr(mod, "roll_dice"), "roll_dice skill missing"
        assert callable(mod.roll_dice)

    def test_tavern_skills_registered_buy_drink_and_rumor(self):
        mod = self._skills_module()
        assert hasattr(mod, "buy_drink_and_rumor"), "buy_drink_and_rumor skill missing"
        assert callable(mod.buy_drink_and_rumor)


# ---------------------------------------------------------------------------
#  3. Skill behaviour (no live scene needed)
# ---------------------------------------------------------------------------

class TestTavernAtmosphereSkill:
    """tavern_atmosphere() returns a usable string."""

    def test_tavern_atmosphere_skill_no_scene(self):
        """With no active scene, returns a closed message."""
        from content.scenes.tavern.tavern_skills import tavern_atmosphere
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            result = tavern_atmosphere()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tavern_atmosphere_skill_with_state(self):
        """With an active state snapshot, returns branding and heat."""
        from content.scenes.tavern.tavern_skills import tavern_atmosphere
        from content.scenes.tavern.tavern_state import TavernState

        state = TavernState()
        state.heat = 55
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=state):
            result = tavern_atmosphere()
        assert "RUSTY ANCHOR" in result
        assert "55" in result

    def test_tavern_atmosphere_skill_heat_description(self):
        """Heat descriptions change with value."""
        from content.scenes.tavern.tavern_skills import tavern_atmosphere
        from content.scenes.tavern.tavern_state import TavernState

        state = TavernState()
        state.heat = 85
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=state):
            result = tavern_atmosphere()
        # High heat → rowdy/brawl description
        assert any(word in result.lower() for word in ["brawl", "snap", "grip", "bottles"])


class TestGetQuestBoardSkill:
    """get_quest_board() returns quest board content."""

    def test_get_quest_board_skill_no_scene(self):
        """Returns a string even with no active scene and no ContentEngine."""
        from content.scenes.tavern.tavern_skills import get_quest_board
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            with mock.patch.dict("sys.modules", {"engine.content.content_engine": None}):
                result = get_quest_board()
        assert isinstance(result, str)

    def test_get_quest_board_skill_with_state(self):
        """With state, returns available quests."""
        from content.scenes.tavern.tavern_skills import get_quest_board
        from content.scenes.tavern.tavern_state import TavernState

        state = TavernState()
        # Mock ContentEngine to raise so we fall back to state quests
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=state):
            with mock.patch(
                "engine.content.content_engine.get_content_engine",
                side_effect=Exception("no engine"),
            ):
                result = get_quest_board()
        assert isinstance(result, str)
        assert "QUEST BOARD" in result

    def test_get_quest_board_skill_uses_content_engine(self):
        """When ContentEngine is available, its items appear in result."""
        from content.scenes.tavern.tavern_skills import get_quest_board
        from content.scenes.tavern.tavern_state import TavernState

        state = TavernState()

        fake_item = mock.MagicMock()
        fake_item.id = "q_cursed_cargo"
        fake_item.title = "The Cursed Cargo"
        fake_item.tags = ["adventure", "dockside"]

        fake_ce = mock.MagicMock()
        fake_ce.get_by_scene.return_value = [fake_item]

        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=state):
            with mock.patch(
                "engine.content.content_engine.get_content_engine",
                return_value=fake_ce,
            ):
                result = get_quest_board()
        assert "Cursed Cargo" in result


class TestRollDiceSkill:
    """roll_dice() produces correct output."""

    def test_roll_dice_skill_default(self):
        """Default d20 roll returns a result string."""
        from content.scenes.tavern.tavern_skills import roll_dice
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            result = roll_dice()
        assert isinstance(result, str)
        assert "d20" in result
        assert "Total:" in result

    def test_roll_dice_skill_sides(self):
        """Custom sides appear in output."""
        from content.scenes.tavern.tavern_skills import roll_dice
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            result = roll_dice(sides=6, reason="lock pick")
        assert "d6" in result
        assert "lock pick" in result

    def test_roll_dice_skill_critical(self):
        """When all dice max out, CRITICAL appears."""
        import random
        from content.scenes.tavern.tavern_skills import roll_dice
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            with mock.patch.object(random, "randint", return_value=20):
                result = roll_dice(sides=20)
        assert "CRITICAL" in result

    def test_roll_dice_skill_fumble(self):
        """When all dice roll 1, FUMBLE appears."""
        import random
        from content.scenes.tavern.tavern_skills import roll_dice
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            with mock.patch.object(random, "randint", return_value=1):
                result = roll_dice(sides=20)
        assert "FUMBLE" in result

    def test_roll_dice_skill_sides_clamped(self):
        """Sides are clamped to sane range (2–100)."""
        from content.scenes.tavern.tavern_skills import roll_dice
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            result_low  = roll_dice(sides=0)
            result_high = roll_dice(sides=9999)
        assert "d2"   in result_low
        assert "d100" in result_high


# ---------------------------------------------------------------------------
#  4. Accept quest skill
# ---------------------------------------------------------------------------

class TestAcceptQuestSkill:
    """accept_quest() calls state.accept_quest and emits events."""

    def test_accept_quest_skill_no_id(self):
        from content.scenes.tavern.tavern_skills import accept_quest
        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=None):
            result = accept_quest("")
        assert isinstance(result, str)

    def test_accept_quest_skill_success(self):
        from content.scenes.tavern.tavern_skills import accept_quest
        from content.scenes.tavern.tavern_state import TavernState

        state = TavernState()
        quest_id = list(state.quests.keys())[0] if state.quests else None
        if not quest_id:
            pytest.skip("No quests in default state")

        with mock.patch("content.scenes.tavern.tavern_skills._get_state", return_value=state):
            with mock.patch(
                "engine.events.event_bus.get_event_bus",
                side_effect=Exception("no bus"),
            ):
                result = accept_quest(quest_id)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
#  5. Static assets exist
# ---------------------------------------------------------------------------

class TestTavernStaticAssets:
    """Required static files are present on disk."""

    def test_tavern_html_exists(self):
        path = os.path.join(TEMPLATE_DIR, "tavern.html")
        assert os.path.isfile(path), f"tavern.html not found at {path}"

    def test_tavern_css_exists(self):
        path = os.path.join(STATIC_DIR, "tavern.css")
        assert os.path.isfile(path), f"tavern.css not found at {path}"

    def test_tavern_js_exists(self):
        path = os.path.join(STATIC_DIR, "tavern.js")
        assert os.path.isfile(path), f"tavern.js not found at {path}"

    def test_tavern_html_contains_scene_attr(self):
        """HTML body has data-scene='tavern'."""
        path = os.path.join(TEMPLATE_DIR, "tavern.html")
        content = _effective_content(open(path, encoding="utf-8").read())
        assert 'data-scene="tavern"' in content

    def test_tavern_html_contains_rusty_anchor(self):
        """HTML references THE RUSTY ANCHOR branding."""
        path = os.path.join(TEMPLATE_DIR, "tavern.html")
        content = _effective_content(open(path, encoding="utf-8").read())
        assert "RUSTY ANCHOR" in content

    def test_tavern_css_contains_accent_color(self):
        """CSS defines the dark amber accent colour."""
        path = os.path.join(STATIC_DIR, "tavern.css")
        content = open(path, encoding="utf-8").read()
        assert "#92400e" in content

    def test_tavern_css_contains_quest_board(self):
        path = os.path.join(STATIC_DIR, "tavern.css")
        content = open(path, encoding="utf-8").read()
        assert ".quest-board" in content

    def test_tavern_css_contains_dice_area(self):
        path = os.path.join(STATIC_DIR, "tavern.css")
        content = open(path, encoding="utf-8").read()
        assert ".dice-area" in content

    def test_tavern_css_contains_rumor_card(self):
        path = os.path.join(STATIC_DIR, "tavern.css")
        content = open(path, encoding="utf-8").read()
        assert ".rumor-card" in content

    def test_tavern_css_contains_time_badge(self):
        path = os.path.join(STATIC_DIR, "tavern.css")
        content = open(path, encoding="utf-8").read()
        assert ".time-badge" in content

    def test_tavern_js_contains_rusty_anchor_class(self):
        path = os.path.join(STATIC_DIR, "tavern.js")
        content = open(path, encoding="utf-8").read()
        assert "class RustyAnchorScene" in content

    def test_tavern_js_contains_embers(self):
        path = os.path.join(STATIC_DIR, "tavern.js")
        content = open(path, encoding="utf-8").read()
        assert "embers" in content or "Ember" in content

    def test_tavern_js_contains_animate_dice(self):
        path = os.path.join(STATIC_DIR, "tavern.js")
        content = open(path, encoding="utf-8").read()
        assert "_animateDiceRoll" in content


# ---------------------------------------------------------------------------
#  6. Socket handler registration
# ---------------------------------------------------------------------------

class TestTavernSocketHandlers:
    """Socket.IO handlers are registered for all required events."""

    def _scene_source(self):
        path = os.path.join(TAVERN_DIR, "tavern_scene.py")
        return open(path, encoding="utf-8").read()

    def test_get_tavern_state_handler(self):
        src = self._scene_source()
        assert '"get_tavern_state"' in src or "'get_tavern_state'" in src

    def test_get_quest_board_handler(self):
        src = self._scene_source()
        assert '"get_quest_board"' in src or "'get_quest_board'" in src

    def test_accept_quest_handler(self):
        src = self._scene_source()
        assert '"accept_quest"' in src or "'accept_quest'" in src

    def test_roll_dice_handler(self):
        src = self._scene_source()
        assert '"roll_dice"' in src or "'roll_dice'" in src

    def test_order_drink_handler(self):
        src = self._scene_source()
        assert '"order_drink"' in src or "'order_drink'" in src

    def test_investigate_rumor_handler(self):
        src = self._scene_source()
        assert '"investigate_rumor"' in src or "'investigate_rumor'" in src


# ── World State wiring ─────────────────────────────────────────────────────

class TestWorldStateWiring:
    """TavernScene wires world_state and EventBus."""

    def test_world_state_wired(self):
        """TavernScene has _on_world_tick and _on_time_change methods."""
        from content.scenes.tavern.tavern_scene import TavernScene
        assert hasattr(TavernScene, "_on_world_tick")
        assert hasattr(TavernScene, "_on_time_change")

    def _scene_source(self) -> str:
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "content", "scenes", "tavern", "tavern_scene.py")
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def test_tavern_quest_refresh_on_dawn(self):
        """_on_time_change emits quest_refresh at hour 6 (dawn)."""
        src = self._scene_source()
        assert "quest_refresh" in src
        assert "hour == 6" in src
