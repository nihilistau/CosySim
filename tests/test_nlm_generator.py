"""Tests for engine.content.nlm_generator — NLMContentGenerator.

All external services (Nexus client, ContentEngine, BeatType) are mocked so
no real network calls are made.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_nexus(answer: str = "") -> MagicMock:
    """Return a MagicMock Nexus client that returns *answer* for ask()."""
    nexus = MagicMock()
    nexus.ask.return_value = {"answer": answer}
    nexus.add_entry.return_value = "fake-entry-id"
    return nexus


def _make_fresh_generator(nexus_mock: MagicMock) -> Any:
    """Import a *fresh* NLMContentGenerator instance with a pre-set nexus."""
    from engine.content.nlm_generator import NLMContentGenerator
    gen = NLMContentGenerator()
    gen._nexus = nexus_mock
    return gen


# ---------------------------------------------------------------------------
# _parse_json_array
# ---------------------------------------------------------------------------

class TestParseJsonArray:
    def test_valid_array_extracted(self):
        from engine.content.nlm_generator import NLMContentGenerator
        gen = NLMContentGenerator()
        raw = 'Some text ["alpha", "beta", "gamma"] trailing'
        result = gen._parse_json_array(raw)
        assert result == ["alpha", "beta", "gamma"]

    def test_empty_string_returns_empty(self):
        from engine.content.nlm_generator import NLMContentGenerator
        gen = NLMContentGenerator()
        assert gen._parse_json_array("") == []

    def test_no_array_returns_empty(self):
        from engine.content.nlm_generator import NLMContentGenerator
        gen = NLMContentGenerator()
        assert gen._parse_json_array("no brackets here") == []

    def test_malformed_json_returns_empty(self):
        from engine.content.nlm_generator import NLMContentGenerator
        gen = NLMContentGenerator()
        assert gen._parse_json_array("[broken json") == []

    def test_nested_non_string_items_cast(self):
        from engine.content.nlm_generator import NLMContentGenerator
        gen = NLMContentGenerator()
        result = gen._parse_json_array("[1, 2, 3]")
        assert result == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# _ask_nlm
# ---------------------------------------------------------------------------

class TestAskNlm:
    def test_returns_answer_string(self):
        nexus = _make_mock_nexus(answer="test answer")
        gen = _make_fresh_generator(nexus)
        result = gen._ask_nlm("question?")
        assert result == "test answer"
        nexus.ask.assert_called_once_with("question?", depth="auto")

    def test_dict_with_no_answer_key_returns_empty(self):
        nexus = MagicMock()
        nexus.ask.return_value = {}
        gen = _make_fresh_generator(nexus)
        result = gen._ask_nlm("q")
        assert result == ""

    def test_exception_returns_empty(self):
        nexus = MagicMock()
        nexus.ask.side_effect = RuntimeError("network fail")
        gen = _make_fresh_generator(nexus)
        result = gen._ask_nlm("q")
        assert result == ""


# ---------------------------------------------------------------------------
# generate_beat_instructions
# ---------------------------------------------------------------------------

class TestGenerateBeatInstructions:
    def test_stores_one_instruction_per_item(self):
        instructions = ["Do X.", "Do Y.", "Do Z."]
        nexus = _make_mock_nexus(answer=json.dumps(instructions))
        gen = _make_fresh_generator(nexus)
        stored = gen.generate_beat_instructions("tavern", "escalation", count=3)
        assert stored == 3
        assert nexus.add_entry.call_count == 3

    def test_stores_with_correct_tags(self):
        nexus = _make_mock_nexus(answer='["Do X."]')
        gen = _make_fresh_generator(nexus)
        gen.generate_beat_instructions("casino", "tension_build", count=1)
        _, kwargs = nexus.add_entry.call_args
        assert "scene:casino" in kwargs["tags"]
        assert "beat_type:tension_build" in kwargs["tags"]
        assert "director_beat" in kwargs["tags"]

    def test_empty_nlm_response_returns_zero(self):
        nexus = _make_mock_nexus(answer="")
        gen = _make_fresh_generator(nexus)
        stored = gen.generate_beat_instructions("lounge", "climax", count=5)
        assert stored == 0
        nexus.add_entry.assert_not_called()

    def test_title_matches_director_search_pattern(self):
        """Title must match SceneDirector._get_instruction search: '{scene} {beat_type} director beat'."""
        nexus = _make_mock_nexus(answer='["Instruct something."]')
        gen = _make_fresh_generator(nexus)
        gen.generate_beat_instructions("arena", "resolution", count=1)
        _, kwargs = nexus.add_entry.call_args
        assert kwargs["title"] == "arena resolution director beat"


# ---------------------------------------------------------------------------
# generate_dialogue_pool
# ---------------------------------------------------------------------------

class TestGenerateDialoguePool:
    def test_adds_items_to_content_engine(self):
        lines = ["Hello.", "What do you want?", "Get out."]
        nexus = _make_mock_nexus(answer=json.dumps(lines))
        gen = _make_fresh_generator(nexus)

        mock_engine = MagicMock()
        mock_engine.add_to_pool.return_value = None

        with patch("engine.content.content_engine.get_content_engine", return_value=mock_engine):
            added = gen.generate_dialogue_pool("lounge", count=3, intensity=2)

        assert added == 3
        assert mock_engine.add_to_pool.call_count == 3

    def test_correct_pool_name_used(self):
        nexus = _make_mock_nexus(answer='["Line one."]')
        gen = _make_fresh_generator(nexus)
        mock_engine = MagicMock()
        with patch("engine.content.content_engine.get_content_engine", return_value=mock_engine):
            gen.generate_dialogue_pool("bedroom", count=1, intensity=3)
        call_kwargs = mock_engine.add_to_pool.call_args[1]
        assert call_kwargs["pool"] == "dialogue"
        assert call_kwargs["scene"] == "bedroom"
        assert call_kwargs["intensity"] == 3

    def test_empty_nlm_returns_zero(self):
        nexus = _make_mock_nexus(answer="")
        gen = _make_fresh_generator(nexus)
        with patch("engine.content.content_engine.get_content_engine"):
            added = gen.generate_dialogue_pool("tavern", count=5)
        assert added == 0

    def test_content_engine_exception_returns_zero(self):
        nexus = _make_mock_nexus(answer='["Line."]')
        gen = _make_fresh_generator(nexus)
        with patch("engine.content.content_engine.get_content_engine", side_effect=RuntimeError("no engine")):
            added = gen.generate_dialogue_pool("arena", count=1)
        assert added == 0


# ---------------------------------------------------------------------------
# seed_director_beats
# ---------------------------------------------------------------------------

class TestSeedDirectorBeats:
    def test_iterates_all_beat_types(self):
        from engine.director.scene_director import BeatType
        nexus = _make_mock_nexus(answer='["Beat instruction."]')
        gen = _make_fresh_generator(nexus)
        total = gen.seed_director_beats("realm", beat_count=1)
        # Should have called generate_beat_instructions once per BeatType
        expected_calls = len(list(BeatType))
        assert total == expected_calls  # 1 stored per beat type

    def test_exceptions_do_not_propagate(self):
        nexus = MagicMock()
        nexus.ask.side_effect = RuntimeError("oops")
        nexus.add_entry.return_value = "id"
        gen = _make_fresh_generator(nexus)
        # Should return 0 but not raise
        total = gen.seed_director_beats("casino", beat_count=2)
        assert total == 0


# ---------------------------------------------------------------------------
# seed_scene
# ---------------------------------------------------------------------------

class TestSeedScene:
    def test_returns_beats_and_content_keys(self):
        from engine.director.scene_director import BeatType
        nexus = _make_mock_nexus(answer='["item one.", "item two.", "item three."]')
        gen = _make_fresh_generator(nexus)
        mock_engine = MagicMock()
        mock_engine.refill_pool.return_value = 3
        with patch("engine.content.content_engine.get_content_engine", return_value=mock_engine):
            result = gen.seed_scene("tavern", intensity=2, beat_count=3, content_count=3)
        assert "beats" in result
        assert "content" in result
        assert result["beats"] >= 0
        assert result["content"] >= 0


# ---------------------------------------------------------------------------
# seed_all_scenes
# ---------------------------------------------------------------------------

class TestSeedAllScenes:
    def test_seeds_each_configured_scene(self):
        from engine.content.nlm_generator import GENERATOR_SCENES
        nexus = _make_mock_nexus(answer='["x.", "y.", "z."]')
        gen = _make_fresh_generator(nexus)
        mock_engine = MagicMock()
        mock_engine.refill_pool.return_value = 1
        with patch("engine.content.content_engine.get_content_engine", return_value=mock_engine):
            results = gen.seed_all_scenes(beat_count=1, content_count=1)
        for scene in GENERATOR_SCENES:
            assert scene in results

    def test_totals_key_present(self):
        nexus = _make_mock_nexus(answer="[]")
        gen = _make_fresh_generator(nexus)
        mock_engine = MagicMock()
        mock_engine.refill_pool.return_value = 0
        with patch("engine.content.content_engine.get_content_engine", return_value=mock_engine):
            results = gen.seed_all_scenes()
        assert "_totals" in results
        assert "beats" in results["_totals"]
        assert "content" in results["_totals"]


# ---------------------------------------------------------------------------
# generate_scene_lore
# ---------------------------------------------------------------------------

class TestGenerateSceneLore:
    def test_stores_lore_entries(self):
        lore_items = ["Faction A rules the docks.", "The old mine is haunted.", "Silver coins are counterfeit here."]
        nexus = _make_mock_nexus(answer=json.dumps(lore_items))
        gen = _make_fresh_generator(nexus)
        stored = gen.generate_scene_lore("tavern", count=3)
        assert stored == 3
        assert nexus.add_entry.call_count == 3

    def test_stores_with_correct_tags(self):
        nexus = _make_mock_nexus(answer='["The city never sleeps."]')
        gen = _make_fresh_generator(nexus)
        gen.generate_scene_lore("neoncity", count=1)
        _, kwargs = nexus.add_entry.call_args
        assert "scene:neoncity" in kwargs["tags"]
        assert "type:lore" in kwargs["tags"]
        assert "world_lore" in kwargs["tags"]

    def test_empty_response_returns_zero(self):
        nexus = _make_mock_nexus(answer="")
        gen = _make_fresh_generator(nexus)
        stored = gen.generate_scene_lore("arena", count=5)
        assert stored == 0
        nexus.add_entry.assert_not_called()


# ---------------------------------------------------------------------------
# generate_npc_backstory
# ---------------------------------------------------------------------------

class TestGenerateNpcBackstory:
    def test_stores_backstory_with_character_tag(self):
        backstory = "Viktor grew up in the slums and became a fixer for the syndicate."
        nexus = _make_mock_nexus(answer=backstory)
        gen = _make_fresh_generator(nexus)
        result = gen.generate_npc_backstory("casino", "Viktor")
        assert result == backstory
        _, kwargs = nexus.add_entry.call_args
        assert "character:Viktor" in kwargs["tags"]
        assert "backstory" in kwargs["tags"]
        assert "npc_lore" in kwargs["tags"]
        assert "scene:casino" in kwargs["tags"]

    def test_empty_response_returns_none(self):
        nexus = _make_mock_nexus(answer="")
        gen = _make_fresh_generator(nexus)
        result = gen.generate_npc_backstory("lounge", "Lola")
        assert result is None
        nexus.add_entry.assert_not_called()


# ---------------------------------------------------------------------------
# seed_lore_all_scenes
# ---------------------------------------------------------------------------

class TestSeedLoreAllScenes:
    def test_returns_per_scene_counts(self):
        from engine.content.nlm_generator import GENERATOR_SCENES
        lore = ["Lore entry one.", "Lore entry two."]
        nexus = _make_mock_nexus(answer=json.dumps(lore))
        gen = _make_fresh_generator(nexus)
        results = gen.seed_lore_all_scenes(lore_count=2)
        for scene in GENERATOR_SCENES:
            assert scene in results
            assert results[scene] == 2

    def test_exception_per_scene_returns_zero(self):
        nexus = MagicMock()
        nexus.ask.side_effect = RuntimeError("nlm down")
        gen = _make_fresh_generator(nexus)
        results = gen.seed_lore_all_scenes(lore_count=5)
        for v in results.values():
            assert v == 0


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

class TestGetNlmGenerator:
    def test_returns_same_instance(self):
        from engine.content.nlm_generator import get_nlm_generator
        a = get_nlm_generator()
        b = get_nlm_generator()
        assert a is b

    def test_returns_nlm_content_generator_instance(self):
        from engine.content.nlm_generator import NLMContentGenerator, get_nlm_generator
        gen = get_nlm_generator()
        assert isinstance(gen, NLMContentGenerator)
