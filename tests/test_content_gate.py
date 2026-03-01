"""
Tests for engine/content/content_gate.py
==========================================

Covers ContentProfile, ContentGate, ContentIntensityInterceptor, and the
get_content_gate() singleton.  Nexus is always mocked so no live server
is required.
"""
from __future__ import annotations

import json
import threading
from dataclasses import fields
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, call

import pytest

from engine.content.content_gate import (
    ContentGate,
    ContentProfile,
    ContentIntensityInterceptor,
    get_content_gate,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_nexus(search_returns: List[Dict] = None) -> MagicMock:
    """Return a MagicMock Nexus client.

    Args:
        search_returns: Value to return from ``client.search()``.

    Returns:
        Pre-configured MagicMock.
    """
    mock = MagicMock()
    mock.search.return_value = search_returns or []
    mock.add_entry.return_value = "entry-001"
    mock.update_entry.return_value = True
    return mock


# ══════════════════════════════════════════════════════════════════════════════
#  ContentProfile — Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestContentProfile:
    """Tests for ContentProfile dataclass and helpers."""

    def test_default_profile_is_explicit(self):
        """Default ContentProfile matches the explicit() preset."""
        profile = ContentProfile()
        assert profile.sexual == 2
        assert profile.violence == 2
        assert profile.horror == 2
        assert profile.gambling == 2
        assert profile.language == 3

    def test_explicit_factory_matches_default(self):
        """ContentProfile.explicit() matches the hard-coded defaults."""
        explicit = ContentProfile.explicit()
        default = ContentProfile()
        assert explicit.to_dict() == default.to_dict()

    def test_factory_all_off(self):
        """all_off() sets every field to 0."""
        p = ContentProfile.all_off()
        for f in fields(ContentProfile):
            assert getattr(p, f.name) == 0, f"{f.name} should be 0"

    def test_factory_mild(self):
        """mild() sets every field to 1."""
        p = ContentProfile.mild()
        for f in fields(ContentProfile):
            assert getattr(p, f.name) == 1, f"{f.name} should be 1"

    def test_factory_extreme(self):
        """extreme() sets every field to 3."""
        p = ContentProfile.extreme()
        for f in fields(ContentProfile):
            assert getattr(p, f.name) == 3, f"{f.name} should be 3"

    def test_to_instruction_includes_all_categories(self):
        """to_instruction() mentions all five category names."""
        instruction = ContentProfile.explicit().to_instruction()
        for category in ("Sexual", "Violence", "Horror", "Gambling", "Language"):
            assert category in instruction, f"{category} missing from instruction"

    def test_to_instruction_includes_level_numbers(self):
        """to_instruction() embeds the numeric level for each category."""
        p = ContentProfile(sexual=1, violence=0, horror=3, gambling=2, language=1)
        instruction = p.to_instruction()
        assert "level 1" in instruction   # sexual / language
        assert "level 0" in instruction   # violence
        assert "level 3" in instruction   # horror
        assert "level 2" in instruction   # gambling

    def test_to_instruction_ends_with_no_self_censor(self):
        """to_instruction() always ends with the do-not-self-censor reminder."""
        instruction = ContentProfile.explicit().to_instruction()
        assert "Do not self-censor" in instruction
        assert "adult-only environment" in instruction

    def test_to_instruction_starts_with_content_profile(self):
        """to_instruction() starts with the 'CONTENT PROFILE:' header."""
        instruction = ContentProfile.explicit().to_instruction()
        assert instruction.startswith("CONTENT PROFILE:")

    def test_profile_serialization_round_trip(self):
        """to_dict() and from_dict() produce an identical profile."""
        original = ContentProfile(sexual=1, violence=3, horror=0, gambling=2, language=1)
        restored = ContentProfile.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict() silently drops keys not in ContentProfile."""
        data = {"sexual": 1, "violence": 1, "horror": 1, "gambling": 1,
                "language": 1, "nonexistent_key": 99}
        profile = ContentProfile.from_dict(data)
        assert not hasattr(profile, "nonexistent_key")

    def test_from_dict_uses_defaults_for_missing_keys(self):
        """from_dict() uses dataclass defaults when keys are absent."""
        profile = ContentProfile.from_dict({})
        assert profile == ContentProfile()


# ══════════════════════════════════════════════════════════════════════════════
#  ContentGate — Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestContentGate:
    """Tests for ContentGate profile management and content filtering."""

    def _make_gate(self, search_returns=None) -> ContentGate:
        return ContentGate(nexus_client=_make_mock_nexus(search_returns))

    # ── Profile get / set ───────────────────────────────────────────────────

    def test_get_profile_returns_default_when_nexus_empty(self):
        """get_profile() falls back to explicit() when Nexus has no entry."""
        gate = self._make_gate(search_returns=[])
        profile = gate.get_profile("player")
        assert profile == ContentProfile.explicit()

    def test_set_and_get_profile(self):
        """set_profile() stores the profile; get_profile() returns it."""
        gate = self._make_gate()
        custom = ContentProfile(sexual=1, violence=0, horror=1, gambling=0, language=2)
        gate.set_profile(custom, "alice")
        assert gate.get_profile("alice") == custom

    def test_set_profile_persists_to_nexus(self):
        """set_profile() calls Nexus add_entry or update_entry."""
        mock_nexus = _make_mock_nexus()
        gate = ContentGate(nexus_client=mock_nexus)
        gate.set_profile(ContentProfile.extreme(), "bob")
        assert mock_nexus.add_entry.called or mock_nexus.update_entry.called

    def test_get_profile_loads_from_nexus(self):
        """get_profile() deserialises a stored entry returned by Nexus search."""
        stored_profile = ContentProfile(sexual=0, violence=1, horror=0, gambling=0, language=1)
        nexus_entry = {
            "title": "profile:player",
            "category": "content_gate",
            "content": json.dumps(stored_profile.to_dict()),
            "id": "entry-abc",
        }
        gate = self._make_gate(search_returns=[nexus_entry])
        profile = gate.get_profile("player")
        assert profile == stored_profile

    def test_get_profile_cached_after_first_load(self):
        """Subsequent get_profile() calls do not re-query Nexus."""
        mock_nexus = _make_mock_nexus()
        gate = ContentGate(nexus_client=mock_nexus)
        gate.get_profile("player")
        gate.get_profile("player")
        # Nexus should have been searched only once (first load)
        assert mock_nexus.search.call_count == 1

    # ── update_category ─────────────────────────────────────────────────────

    def test_update_single_category(self):
        """update_category() changes exactly the targeted field."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.explicit(), "player")
        gate.update_category("sexual", 0, "player")
        profile = gate.get_profile("player")
        assert profile.sexual == 0
        # Other fields unchanged
        assert profile.violence == 2
        assert profile.language == 3

    def test_update_category_invalid_name_raises(self):
        """update_category() raises ValueError for unknown category names."""
        gate = self._make_gate()
        with pytest.raises(ValueError, match="Unknown content category"):
            gate.update_category("nudity", 2)

    def test_update_category_invalid_level_raises(self):
        """update_category() raises ValueError for out-of-range levels."""
        gate = self._make_gate()
        with pytest.raises(ValueError, match="Intensity level must be"):
            gate.update_category("sexual", 4)

    # ── can_show ────────────────────────────────────────────────────────────

    def test_can_show_sexual_content_at_level_2(self):
        """can_show() returns True when profile level meets required intensity."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.explicit(), "player")  # sexual=2
        assert gate.can_show(["adult:sexual", "intensity:2"]) is True

    def test_cannot_show_content_above_profile_level(self):
        """can_show() returns False when required intensity exceeds profile level."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.mild(), "player")  # sexual=1
        assert gate.can_show(["adult:sexual", "intensity:2"]) is False

    def test_can_show_returns_true_with_no_adult_tags(self):
        """can_show() allows items with no adult/intensity tags."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.all_off(), "player")
        assert gate.can_show(["genre:adventure", "tone:dark"]) is True

    def test_can_show_at_exact_boundary(self):
        """can_show() returns True when profile level == required intensity."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile(violence=3), "player")
        assert gate.can_show(["adult:violence", "intensity:3"]) is True

    def test_can_show_extreme_allowed_by_extreme_profile(self):
        """can_show() allows intensity:3 when profile is extreme()."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.extreme(), "player")
        assert gate.can_show(["adult:horror", "intensity:3"]) is True

    # ── filter_content ───────────────────────────────────────────────────────

    def test_filter_content_list(self):
        """filter_content() returns only items permitted by the profile."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.mild(), "player")  # sexual=1, violence=1

        items = [
            {"name": "safe_item",    "content_tags": []},
            {"name": "mild_sex",     "content_tags": ["adult:sexual",   "intensity:1"]},
            {"name": "explicit_sex", "content_tags": ["adult:sexual",   "intensity:2"]},
            {"name": "mild_violence","content_tags": ["adult:violence",  "intensity:1"]},
            {"name": "gore",         "content_tags": ["adult:violence",  "intensity:3"]},
        ]
        allowed = gate.filter_content(items, "player")
        names = [i["name"] for i in allowed]
        assert "safe_item"     in names
        assert "mild_sex"      in names
        assert "mild_violence" in names
        assert "explicit_sex"  not in names
        assert "gore"          not in names

    def test_filter_content_empty_list(self):
        """filter_content() handles an empty input list."""
        gate = self._make_gate()
        assert gate.filter_content([]) == []

    def test_filter_content_object_with_attribute(self):
        """filter_content() supports objects with a content_tags attribute."""
        gate = self._make_gate()
        gate.set_profile(ContentProfile.mild(), "player")

        class Item:
            def __init__(self, name: str, tags: List[str]) -> None:
                self.name = name
                self.content_tags = tags

        items = [
            Item("allowed", ["adult:sexual", "intensity:1"]),
            Item("blocked",  ["adult:sexual", "intensity:2"]),
        ]
        allowed = gate.filter_content(items, "player")
        assert len(allowed) == 1
        assert allowed[0].name == "allowed"


# ══════════════════════════════════════════════════════════════════════════════
#  ContentIntensityInterceptor — Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestContentIntensityInterceptor:
    """Tests for ContentIntensityInterceptor injection behaviour."""

    def _make_interceptor(
        self, profile: ContentProfile = None
    ) -> ContentIntensityInterceptor:
        gate = ContentGate(nexus_client=_make_mock_nexus())
        if profile is not None:
            gate.set_profile(profile, "player")
        return ContentIntensityInterceptor(gate=gate)

    def _make_ctx(self, system_prompt: str = "") -> Dict[str, Any]:
        from engine.mcp.comms_framework import ResponseContext
        ctx = ResponseContext()
        ctx["system_prompt"] = system_prompt
        return ctx

    def test_interceptor_injects_instruction_into_system_prompt(self):
        """pre_call() prepends [CONTENT GATE] block to system_prompt."""
        interceptor = self._make_interceptor(ContentProfile.explicit())
        ctx = self._make_ctx("Original system prompt.")
        interceptor.pre_call(ctx)
        assert ctx["system_prompt"].startswith("[CONTENT GATE]")
        assert "Original system prompt." in ctx["system_prompt"]

    def test_interceptor_instruction_contains_profile_data(self):
        """Injected block includes all five category descriptions."""
        interceptor = self._make_interceptor(
            ContentProfile(sexual=0, violence=1, horror=2, gambling=3, language=0)
        )
        ctx = self._make_ctx()
        interceptor.pre_call(ctx)
        prompt = ctx["system_prompt"]
        assert "Sexual content level 0" in prompt
        assert "Violence level 1" in prompt
        assert "Horror level 2" in prompt
        assert "Gambling level 3" in prompt
        assert "Language level 0" in prompt

    def test_interceptor_disables_kill_switch_at_extreme_level(self):
        """pre_call() sets kill_switch_disabled=True when any category is 3."""
        interceptor = self._make_interceptor(ContentProfile.extreme())
        ctx = self._make_ctx()
        interceptor.pre_call(ctx)
        assert ctx.get("kill_switch_disabled") is True

    def test_interceptor_does_not_disable_kill_switch_below_extreme(self):
        """pre_call() does NOT set kill_switch_disabled for levels < 3."""
        interceptor = self._make_interceptor(ContentProfile.mild())  # all 1s
        ctx = self._make_ctx()
        interceptor.pre_call(ctx)
        assert not ctx.get("kill_switch_disabled")

    def test_interceptor_kill_switch_triggered_by_single_extreme_category(self):
        """kill_switch_disabled triggers if even one category reaches 3."""
        p = ContentProfile(sexual=2, violence=2, horror=2, gambling=2, language=3)
        interceptor = self._make_interceptor(p)
        ctx = self._make_ctx()
        interceptor.pre_call(ctx)
        assert ctx.get("kill_switch_disabled") is True

    def test_interceptor_post_call_is_passthrough(self):
        """post_call() does not modify the context."""
        interceptor = self._make_interceptor()
        ctx = self._make_ctx()
        ctx["reply"] = "Hello world"
        interceptor.post_call(ctx)
        assert ctx["reply"] == "Hello world"

    def test_interceptor_priority_is_1(self):
        """ContentIntensityInterceptor.priority == 1 (runs before everything)."""
        assert ContentIntensityInterceptor.priority == 1

    def test_interceptor_wraps_in_content_gate_tags(self):
        """Injected block uses [CONTENT GATE] / [/CONTENT GATE] delimiters."""
        interceptor = self._make_interceptor()
        ctx = self._make_ctx()
        interceptor.pre_call(ctx)
        prompt = ctx["system_prompt"]
        assert "[CONTENT GATE]" in prompt
        assert "[/CONTENT GATE]" in prompt

    def test_interceptor_respects_player_id_from_context(self):
        """pre_call() uses ctx['player_id'] when present."""
        gate = ContentGate(nexus_client=_make_mock_nexus())
        alice_profile = ContentProfile.all_off()
        gate.set_profile(alice_profile, "alice")
        gate.set_profile(ContentProfile.extreme(), "player")

        interceptor = ContentIntensityInterceptor(gate=gate)
        ctx = self._make_ctx()
        ctx["player_id"] = "alice"
        interceptor.pre_call(ctx)

        # Alice has all_off, so no extreme categories → kill_switch NOT disabled
        assert not ctx.get("kill_switch_disabled")
        # Instruction should reflect level 0 for sexual
        assert "level 0" in ctx["system_prompt"]


# ══════════════════════════════════════════════════════════════════════════════
#  Singleton — Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleton:
    """Tests for get_content_gate() singleton behaviour."""

    def test_singleton_returns_same_instance(self):
        """get_content_gate() returns the same object on repeated calls."""
        import engine.content.content_gate as mod

        # Reset the singleton so we can test fresh creation.
        original = mod._gate_instance
        mod._gate_instance = None

        with patch.object(mod, "get_nexus_client", return_value=_make_mock_nexus()):
            try:
                gate_a = mod.get_content_gate()
                gate_b = mod.get_content_gate()
                assert gate_a is gate_b
            finally:
                mod._gate_instance = original

    def test_singleton_thread_safety(self):
        """Concurrent get_content_gate() calls all receive the same object."""
        import engine.content.content_gate as mod

        original = mod._gate_instance
        mod._gate_instance = None

        with patch.object(mod, "get_nexus_client", return_value=_make_mock_nexus()):
            instances: List[Any] = []
            lock = threading.Lock()

            def worker():
                inst = mod.get_content_gate()
                with lock:
                    instances.append(inst)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            mod._gate_instance = original

        assert len(instances) == 10
        first = instances[0]
        assert all(i is first for i in instances)
