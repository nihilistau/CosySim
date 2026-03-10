"""tests/test_art_skills.py — Unit tests for art_skills and PortraitCache.

All ComfyUI / SceneArtManager calls are mocked — no real HTTP requests.
"""
from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers — lightweight ArtResult stub
# ──────────────────────────────────────────────────────────────────────────────


def _make_art_result(url: str = "/view?filename=test.png", cached: bool = False,
                     generation_ms: int = 800) -> MagicMock:
    """Return a MagicMock that looks like ArtResult."""
    r = MagicMock()
    r.url = url
    r.cached = cached
    r.generation_ms = generation_ms
    return r


def _mock_art_manager(
    portrait_url: str = "/view?filename=portrait.png",
    bg_url: str = "/view?filename=bg.png",
    card_url: str = "/view?filename=card.png",
    cached: bool = False,
) -> MagicMock:
    mgr = MagicMock()
    mgr.get_character_portrait.return_value = _make_art_result(portrait_url, cached)
    mgr.get_scene_bg.return_value = _make_art_result(bg_url, cached)
    mgr.get_action_card.return_value = _make_art_result(card_url, cached, generation_ms=500)
    return mgr


# ──────────────────────────────────────────────────────────────────────────────
#  PortraitCache tests
# ──────────────────────────────────────────────────────────────────────────────


class TestPortraitCache:

    def _fresh_cache(self):
        """Return a fresh PortraitCache instance."""
        from engine.art.portrait_cache import PortraitCache
        return PortraitCache()

    def test_set_and_get_url(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "happy", "/view?filename=aria_happy.png")
        assert cache.get_url("aria", "happy") == "/view?filename=aria_happy.png"

    def test_case_insensitive_keys(self):
        cache = self._fresh_cache()
        cache.set_url("ARIA", "HAPPY", "/view?filename=aria.png")
        assert cache.get_url("aria", "happy") == "/view?filename=aria.png"

    def test_fallback_to_neutral(self):
        cache = self._fresh_cache()
        cache.set_url("lola", "neutral", "/view?filename=lola.png")
        # Ask for "angry" which is not cached — should fall back to neutral
        assert cache.get_url("lola", "angry") == "/view?filename=lola.png"

    def test_returns_none_when_empty(self):
        cache = self._fresh_cache()
        assert cache.get_url("unknown_char", "neutral") is None

    def test_ignores_placeholder(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "neutral", "/static/img/placeholder.png")
        assert cache.get_url("aria", "neutral") is None  # placeholder is discarded

    def test_ignores_empty_url(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "neutral", "")
        assert cache.get_url("aria", "neutral") is None

    def test_overwrite_url(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "neutral", "/old.png")
        cache.set_url("aria", "neutral", "/new.png")
        assert cache.get_url("aria", "neutral") == "/new.png"

    def test_get_all_returns_dict(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "happy", "/a.png")
        cache.set_url("lola", "sad", "/b.png")
        all_entries = cache.get_all()
        assert "aria:happy" in all_entries
        assert "lola:sad" in all_entries

    def test_clear(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "neutral", "/x.png")
        cache.clear()
        assert len(cache) == 0

    def test_len(self):
        cache = self._fresh_cache()
        cache.set_url("aria", "neutral", "/a.png")
        cache.set_url("lola", "happy", "/b.png")
        assert len(cache) == 2

    def test_singleton_is_same_object(self):
        from engine.art.portrait_cache import get_portrait_cache
        c1 = get_portrait_cache()
        c2 = get_portrait_cache()
        assert c1 is c2


# ──────────────────────────────────────────────────────────────────────────────
#  Art skills tests
# ──────────────────────────────────────────────────────────────────────────────


class TestGeneratePortraitSkill:

    def test_returns_url_on_success(self):
        mgr = _mock_art_manager("/view?filename=aria.png")
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_portrait
            result = generate_portrait("aria", mood="happy", scene="penthouse")
        assert "/view?filename=aria.png" in result
        mgr.get_character_portrait.assert_called_once_with("aria", mood="happy", scene="penthouse")

    def test_stores_url_in_portrait_cache(self):
        from engine.art.portrait_cache import PortraitCache
        fresh_cache = PortraitCache()
        mgr = _mock_art_manager("/view?filename=aria_happy.png")
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr), \
             patch("engine.art.portrait_cache.get_portrait_cache", return_value=fresh_cache):
            from engine.skills.builtin.art_skills import generate_portrait
            generate_portrait("aria", mood="happy")
        assert fresh_cache.get_url("aria", "happy") == "/view?filename=aria_happy.png"

    def test_cached_label(self):
        mgr = _mock_art_manager("/view?filename=aria.png", cached=True)
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_portrait
            result = generate_portrait("aria")
        assert "(cached)" in result

    def test_generation_ms_shown_when_not_cached(self):
        mgr = _mock_art_manager("/view?filename=aria.png", cached=False)
        mgr.get_character_portrait.return_value.generation_ms = 1234
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_portrait
            result = generate_portrait("aria")
        assert "1234ms" in result

    def test_returns_error_message_on_exception(self):
        mgr = MagicMock()
        mgr.get_character_portrait.side_effect = RuntimeError("ComfyUI offline")
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_portrait
            result = generate_portrait("aria")
        assert "failed" in result.lower() or "ComfyUI offline" in result


class TestGetPortraitUrlSkill:

    def test_returns_cached_url(self):
        from engine.art.portrait_cache import PortraitCache
        fresh_cache = PortraitCache()
        fresh_cache.set_url("aria", "neutral", "/view?filename=aria.png")
        with patch("engine.art.portrait_cache.get_portrait_cache", return_value=fresh_cache):
            from engine.skills.builtin.art_skills import get_portrait_url
            result = get_portrait_url("aria", "neutral")
        assert result == "/view?filename=aria.png"

    def test_returns_empty_string_when_not_cached(self):
        from engine.art.portrait_cache import PortraitCache
        fresh_cache = PortraitCache()
        with patch("engine.art.portrait_cache.get_portrait_cache", return_value=fresh_cache):
            from engine.skills.builtin.art_skills import get_portrait_url
            result = get_portrait_url("unknown", "neutral")
        assert result == ""


class TestGenerateSceneBackgroundSkill:

    def test_returns_url(self):
        mgr = _mock_art_manager(bg_url="/view?filename=bg.png")
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_scene_background
            result = generate_scene_background("casino", time_of_day="night", mood="tense")
        assert "/view?filename=bg.png" in result
        mgr.get_scene_bg.assert_called_once_with("casino", time_of_day="night", mood="tense")

    def test_error_returns_message(self):
        mgr = MagicMock()
        mgr.get_scene_bg.side_effect = Exception("ComfyUI timeout")
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_scene_background
            result = generate_scene_background("casino")
        assert "failed" in result.lower() or "timeout" in result.lower()


class TestGenerateActionCardSkill:

    def test_returns_url(self):
        mgr = _mock_art_manager(card_url="/view?filename=card.png")
        with patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr):
            from engine.skills.builtin.art_skills import generate_action_card
            result = generate_action_card("A dramatic kiss in the moonlight", scene="penthouse", intensity=1)
        assert "/view?filename=card.png" in result
        mgr.get_action_card.assert_called_once()


class TestBatchGeneratePortraitsSkill:

    def test_generates_per_character(self):
        # Mock character registry
        mock_char = MagicMock()
        mock_char.char_id = "aria"
        mock_char.id = "aria"
        mock_char.scene = "penthouse"

        mock_registry = MagicMock()
        mock_registry.get_all_characters.return_value = [mock_char]

        mgr = _mock_art_manager("/view?filename=aria.png")

        from engine.art.portrait_cache import PortraitCache
        fresh_cache = PortraitCache()

        with patch("engine.mcp.get_character_registry", return_value=mock_registry), \
             patch("engine.art.scene_art.get_scene_art_manager", return_value=mgr), \
             patch("engine.art.portrait_cache.get_portrait_cache", return_value=fresh_cache):
            from engine.skills.builtin.art_skills import batch_generate_portraits
            result = batch_generate_portraits("penthouse", mood="neutral")

        assert "aria" in result
        assert fresh_cache.get_url("aria", "neutral") == "/view?filename=aria.png"

    def test_returns_no_characters_message_when_empty(self):
        mock_registry = MagicMock()
        mock_registry.get_all_characters.return_value = []
        with patch("engine.mcp.get_character_registry", return_value=mock_registry):
            from engine.skills.builtin.art_skills import batch_generate_portraits
            result = batch_generate_portraits("empty_scene")
        assert "No characters" in result


# ──────────────────────────────────────────────────────────────────────────────
#  Art skills registered in skill registry
# ──────────────────────────────────────────────────────────────────────────────


class TestArtSkillsRegistered:

    def test_art_pack_has_skills(self):
        from engine.skills.registry import SKILL_REGISTRY
        tools = SKILL_REGISTRY.get_pack_tools("art")
        names = [t.__name__ if callable(t) else str(t) for t in tools]
        assert len(tools) >= 4

    def test_generate_portrait_is_skill(self):
        from engine.skills.skill import SkillMeta
        from engine.skills.registry import SKILL_REGISTRY
        skill_obj = SKILL_REGISTRY.get_skill("generate_portrait")
        assert skill_obj is not None

    def test_get_portrait_url_is_skill(self):
        from engine.skills.registry import SKILL_REGISTRY
        skill_obj = SKILL_REGISTRY.get_skill("get_portrait_url")
        assert skill_obj is not None

    def test_generate_scene_background_is_skill(self):
        from engine.skills.registry import SKILL_REGISTRY
        skill_obj = SKILL_REGISTRY.get_skill("generate_scene_background")
        assert skill_obj is not None

    def test_generate_action_card_is_skill(self):
        from engine.skills.registry import SKILL_REGISTRY
        skill_obj = SKILL_REGISTRY.get_skill("generate_action_card")
        assert skill_obj is not None
