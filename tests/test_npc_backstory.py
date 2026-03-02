"""
Tests for NPC backstory skills and portrait overlay backstory panel.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.skills.builtin.npc_backstory_skills import (
    CHARACTER_BACKSTORIES,
    get_character_profile,
    get_npc_backstory,
    store_npc_backstory,
)

REPO = Path(__file__).parent.parent
TEMPLATE = REPO / "content" / "shared" / "templates" / "portrait_overlay.html"
CSS_FILE = REPO / "content" / "shared" / "static" / "css" / "portrait.css"
JS_FILE = REPO / "content" / "shared" / "static" / "js" / "portrait.js"
SHARED_INIT = REPO / "content" / "shared" / "__init__.py"


# ═══════════════════════════════════════════════════════════════════════
#  Built-in backstory data
# ═══════════════════════════════════════════════════════════════════════

class TestCharacterBackstoriesDict:
    def test_five_characters_seeded(self):
        assert len(CHARACTER_BACKSTORIES) == 5

    def test_all_seeded_characters_present(self):
        for char in ("aria", "lola", "viktor", "frankie", "mira"):
            assert char in CHARACTER_BACKSTORIES

    def test_backstories_are_non_empty_strings(self):
        for char, story in CHARACTER_BACKSTORIES.items():
            assert isinstance(story, str) and len(story) > 20, f"Backstory too short for {char}"


# ═══════════════════════════════════════════════════════════════════════
#  get_npc_backstory
# ═══════════════════════════════════════════════════════════════════════

class TestGetNpcBackstory:
    def _patch_nexus_empty(self):
        """Context manager that makes Nexus return no results."""
        mock_client = MagicMock()
        mock_client.search.return_value = []
        return patch("engine.nexus.client.get_nexus_client", return_value=mock_client)

    def test_returns_string_for_known_character(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("lola")
        assert isinstance(result, str)
        assert len(result) > 10

    def test_lola_backstory_contains_penthouse(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("lola")
        assert "PENTHOUSE" in result or "Penthouse" in result

    def test_viktor_backstory_contains_intelligence(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("viktor")
        assert "intelligence" in result.lower() or "operative" in result.lower()

    def test_aria_backstory_returned(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("aria")
        assert "aria" in result.lower() or "AI" in result or "assistant" in result.lower()

    def test_mira_backstory_returned(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("mira")
        assert len(result) > 20

    def test_frankie_backstory_returned(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("frankie")
        assert len(result) > 20

    def test_unknown_character_graceful_fallback(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("unknown_xyz")
        assert isinstance(result, str)
        assert "unknown_xyz" in result or "classified" in result or "No backstory" in result

    def test_character_id_case_insensitive(self):
        with self._patch_nexus_empty():
            result = get_npc_backstory("LOLA")
        assert len(result) > 10

    def test_nexus_result_takes_precedence(self):
        mock_client = MagicMock()
        mock_client.search.return_value = [{"content": "Custom nexus backstory for lola."}]
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = get_npc_backstory("lola")
        assert result == "Custom nexus backstory for lola."

    def test_nexus_exception_falls_back_to_builtin(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("Nexus offline")
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = get_npc_backstory("viktor")
        assert "viktor" in result.lower() or "operative" in result.lower()


# ═══════════════════════════════════════════════════════════════════════
#  get_character_profile
# ═══════════════════════════════════════════════════════════════════════

class TestGetCharacterProfile:
    def _patch_nexus_empty(self):
        mock_client = MagicMock()
        mock_client.search.return_value = []
        return patch("engine.nexus.client.get_nexus_client", return_value=mock_client)

    def test_returns_string(self):
        with self._patch_nexus_empty():
            result = get_character_profile("lola")
        assert isinstance(result, str)

    def test_includes_character_name_title_case(self):
        with self._patch_nexus_empty():
            result = get_character_profile("lola")
        assert "Lola" in result

    def test_includes_backstory_text(self):
        with self._patch_nexus_empty():
            result = get_character_profile("viktor")
        assert len(result) > 30

    def test_name_appears_before_backstory(self):
        with self._patch_nexus_empty():
            result = get_character_profile("aria")
        lines = result.strip().split("\n")
        assert "Aria" in lines[0]


# ═══════════════════════════════════════════════════════════════════════
#  store_npc_backstory
# ═══════════════════════════════════════════════════════════════════════

class TestStoreNpcBackstory:
    def test_calls_nexus_add_entry(self):
        mock_client = MagicMock()
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = store_npc_backstory("lola", "Updated backstory text.")
        mock_client.add_entry.assert_called_once()
        args, kwargs = mock_client.add_entry.call_args
        assert "lola" in args[0].lower()
        assert "Updated backstory text." in args[1]

    def test_returns_confirmation_string(self):
        mock_client = MagicMock()
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = store_npc_backstory("lola", "Some backstory.")
        assert isinstance(result, str)
        assert "lola" in result.lower()

    def test_nexus_failure_returns_error_string(self):
        mock_client = MagicMock()
        mock_client.add_entry.side_effect = RuntimeError("Connection refused")
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = store_npc_backstory("lola", "text")
        assert "Failed" in result or "failed" in result


# ═══════════════════════════════════════════════════════════════════════
#  Portrait overlay backstory panel — HTML
# ═══════════════════════════════════════════════════════════════════════

class TestPortraitOverlayBackstoryHTML:
    @classmethod
    def setup_class(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_backstory_panel_exists(self):
        assert 'id="cs-backstory-panel"' in self.html

    def test_backstory_text_element_exists(self):
        assert 'id="cs-backstory-text"' in self.html

    def test_backstory_close_button_exists(self):
        assert 'id="cs-backstory-close"' in self.html

    def test_backstory_panel_has_aria_live(self):
        assert 'aria-live="polite"' in self.html

    def test_backstory_close_has_aria_label(self):
        assert 'aria-label="Close"' in self.html


# ═══════════════════════════════════════════════════════════════════════
#  Portrait overlay backstory panel — CSS
# ═══════════════════════════════════════════════════════════════════════

class TestPortraitOverlayBackstoryCSS:
    @classmethod
    def setup_class(cls):
        cls.css = CSS_FILE.read_text(encoding="utf-8")

    def test_backstory_panel_rule_exists(self):
        assert ".cs-backstory-panel" in self.css

    def test_backstory_text_rule_exists(self):
        assert ".cs-backstory-text" in self.css

    def test_backstory_close_rule_exists(self):
        assert ".cs-backstory-close" in self.css

    def test_backstory_visible_state(self):
        assert ".cs-backstory-panel.is-visible" in self.css


# ═══════════════════════════════════════════════════════════════════════
#  Portrait overlay backstory panel — JavaScript
# ═══════════════════════════════════════════════════════════════════════

class TestPortraitOverlayBackstoryJS:
    @classmethod
    def setup_class(cls):
        cls.js = JS_FILE.read_text(encoding="utf-8")

    def test_fetch_backstory_method_exists(self):
        assert "_fetchBackstory" in self.js

    def test_backstory_api_url_pattern(self):
        assert "/api/character/backstory/" in self.js

    def test_bind_backstory_events_method(self):
        assert "_bindBackstoryEvents" in self.js

    def test_backstory_panel_reference(self):
        assert "cs-backstory-panel" in self.js

    def test_backstory_text_reference(self):
        assert "cs-backstory-text" in self.js or "_backstoryText" in self.js

    def test_backstory_close_reference(self):
        assert "cs-backstory-close" in self.js

    def test_uses_fetch_api(self):
        assert "fetch(" in self.js


# ═══════════════════════════════════════════════════════════════════════
#  Backstory API route registered in shared/__init__.py
# ═══════════════════════════════════════════════════════════════════════

class TestBackstoryApiRoute:
    @classmethod
    def setup_class(cls):
        cls.init = SHARED_INIT.read_text(encoding="utf-8")

    def test_backstory_route_registered(self):
        assert "/api/character/backstory/" in self.init

    def test_backstory_skill_imported(self):
        assert "npc_backstory_skills" in self.init or "get_npc_backstory" in self.init
