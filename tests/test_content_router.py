"""Tests for engine/agents/content_router.py — Robust JSON extraction and content classification."""
import pytest

from engine.agents.content_router import (
    extract_json,
    ContentRouter,
    ClassifiedContent,
)


# ── extract_json ──────────────────────────────────────────────────────────

class TestExtractJson:
    """Robust JSON extraction from various LLM output formats."""

    def test_bare_json(self):
        assert extract_json('{"action": "speak"}') == {"action": "speak"}

    def test_json_with_text_before(self):
        text = 'Here is my decision: {"action": "move", "target": "bed"}'
        result = extract_json(text)
        assert result == {"action": "move", "target": "bed"}

    def test_json_with_text_after(self):
        text = '{"action": "speak"} That\'s what I chose.'
        result = extract_json(text)
        assert result == {"action": "speak"}

    def test_json_with_text_both_sides(self):
        text = 'My decision: {"action": "flirt", "message": "hey"} Hope that works!'
        result = extract_json(text)
        assert result["action"] == "flirt"

    def test_markdown_fenced(self):
        text = 'Here:\n```json\n{"action": "idle"}\n```\nDone.'
        result = extract_json(text)
        assert result == {"action": "idle"}

    def test_nested_objects(self):
        text = '{"action": "speak", "meta": {"mood": "happy", "tags": ["a","b"]}}'
        result = extract_json(text)
        assert result["meta"]["mood"] == "happy"
        assert result["meta"]["tags"] == ["a", "b"]

    def test_nested_with_wrapper_text(self):
        text = 'I think: {"outer": {"inner": {"deep": 1}}, "val": 2}'
        result = extract_json(text)
        assert result["outer"]["inner"]["deep"] == 1

    def test_trailing_comma(self):
        text = '{"action": "speak", "message": "hi",}'
        result = extract_json(text)
        assert result["action"] == "speak"

    def test_empty_string(self):
        assert extract_json("") is None

    def test_no_json(self):
        assert extract_json("Just plain text with no JSON at all.") is None

    def test_token_artifacts_stripped(self):
        text = '<|begin_of_text|>{"action": "idle"}<|end_of_text|>'
        result = extract_json(text)
        assert result == {"action": "idle"}

    def test_returns_none_for_list(self):
        # extract_json only returns dicts, not lists
        assert extract_json("[1, 2, 3]") is None

    def test_string_with_braces(self):
        text = '{"message": "I said {hello} to them"}'
        result = extract_json(text)
        assert result["message"] == "I said {hello} to them"

    def test_escaped_quotes_in_value(self):
        text = '{"message": "She said \\"hello\\" back"}'
        result = extract_json(text)
        assert "hello" in result["message"]


# ── ContentRouter.classify ────────────────────────────────────────────────

class TestClassify:
    """Content classification into json / tagged_text / plain_text."""

    def test_plain_text(self):
        result = ContentRouter.classify("Hello there!")
        assert result.content_type == "plain_text"
        assert result.clean_text == "Hello there!"
        assert not result.has_json
        assert not result.has_tags

    def test_json_content(self):
        result = ContentRouter.classify('{"action": "speak", "message": "hi"}')
        assert result.content_type == "json"
        assert result.json_data["action"] == "speak"

    def test_tagged_text(self):
        result = ContentRouter.classify("[MOOD:happy] I feel great! [ACTION:smile]")
        assert result.content_type == "tagged_text"
        assert result.tags["MOOD"] == ["happy"]
        assert result.tags["ACTION"] == ["smile"]
        assert "MOOD" not in result.clean_text
        assert "I feel great!" in result.clean_text

    def test_json_with_tags(self):
        # JSON takes priority over tags
        text = '{"action": "speak"} [MOOD:happy]'
        result = ContentRouter.classify(text)
        assert result.content_type == "json"
        assert result.tags["MOOD"] == ["happy"]

    def test_multiple_same_tags(self):
        text = "[MOOD:happy] and [MOOD:excited]"
        result = ContentRouter.classify(text)
        assert result.tags["MOOD"] == ["happy", "excited"]


# ── ContentRouter.parse_decision ──────────────────────────────────────────

class TestParseDecision:
    """Agent decision parsing with validation."""

    def test_valid_decision(self):
        text = '{"action": "speak", "target": "Luna", "message": "Hello!"}'
        result = ContentRouter.parse_decision(text)
        assert result["action"] == "speak"
        assert result["target"] == "Luna"
        assert result["message"] == "Hello!"

    def test_invalid_action_falls_back(self):
        text = '{"action": "dance", "message": "woo"}'
        result = ContentRouter.parse_decision(text)
        assert result["action"] == "idle"

    def test_custom_valid_actions(self):
        text = '{"action": "dance"}'
        result = ContentRouter.parse_decision(text, valid_actions={"dance", "sing"})
        assert result["action"] == "dance"

    def test_no_json_returns_default(self):
        result = ContentRouter.parse_decision("I don't know what to do")
        assert result["action"] == "idle"
        assert result["target"] == ""

    def test_custom_default_action(self):
        result = ContentRouter.parse_decision("nonsense", default_action="speak")
        assert result["action"] == "speak"

    def test_wrapped_decision(self):
        text = "Here is what I'll do:\n```json\n{\"action\": \"flirt\", \"message\": \"hey\"}\n```"
        result = ContentRouter.parse_decision(text)
        assert result["action"] == "flirt"

    def test_missing_optional_fields(self):
        text = '{"action": "idle"}'
        result = ContentRouter.parse_decision(text)
        assert result["target"] == ""
        assert result["message"] == ""


# ── ContentRouter.extract_tags / strip_tags ───────────────────────────────

class TestTagHelpers:
    def test_extract_tags(self):
        tags = ContentRouter.extract_tags("[MOOD:happy] Hello [IMAGE:sunset]")
        assert tags["MOOD"] == ["happy"]
        assert tags["IMAGE"] == ["sunset"]

    def test_strip_tags(self):
        text = ContentRouter.strip_tags("[MOOD:happy] Hello [IMAGE:sunset]")
        assert text == "Hello"

    def test_no_tags(self):
        tags = ContentRouter.extract_tags("Just plain text")
        assert tags == {}
