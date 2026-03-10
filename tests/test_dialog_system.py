"""
Tests for the Dialog System — speech enhancement, dialog trees,
conversation state, response directives, and conversation heat.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────

def _fresh_dialog_system():
    """Create a fresh DialogSystem (bypass singleton for test isolation)."""
    from engine.mcp.dialog_system import DialogSystem
    return DialogSystem()


def _mock_character_registry():
    """Return a mock registry that provides a basic character profile."""
    reg = MagicMock()
    profile = MagicMock()
    profile.voice_style = "playful, teasing"
    profile.name = "Aria"
    reg.get_profile.return_value = profile
    return reg


# ══════════════════════════════════════════════════════════════════════
#  DialogOption / DialogNode unit tests
# ══════════════════════════════════════════════════════════════════════

class TestDialogOption:
    def test_to_dict(self):
        from engine.mcp.dialog_system import DialogOption
        opt = DialogOption(label="Say hello", text="Hello there!", tag="accept", weight=1.5)
        d = opt.to_dict()
        assert d["label"] == "Say hello"
        assert d["text"] == "Hello there!"
        assert d["tag"] == "accept"

    def test_default_values(self):
        from engine.mcp.dialog_system import DialogOption
        opt = DialogOption(label="L", text="T")
        assert opt.tag == "neutral"
        assert opt.weight == 1.0
        assert opt.requires == {}


class TestDialogNode:
    def test_matches_with_overlapping_tags(self):
        from engine.mcp.dialog_system import DialogNode
        node = DialogNode(node_id="n1", scene="penthouse", situation="test",
                          tags=["cuddle", "close"])
        assert node.matches(["cuddle", "kiss"]) is True

    def test_matches_with_no_overlap(self):
        from engine.mcp.dialog_system import DialogNode
        node = DialogNode(node_id="n1", scene="penthouse", situation="test",
                          tags=["cuddle", "close"])
        assert node.matches(["fight", "run"]) is False

    def test_matches_empty_context_returns_true(self):
        from engine.mcp.dialog_system import DialogNode
        node = DialogNode(node_id="n1", scene="penthouse", situation="test",
                          tags=["cuddle"])
        assert node.matches([]) is True

    def test_filter_options_no_stats(self):
        from engine.mcp.dialog_system import DialogNode, DialogOption
        opts = [DialogOption("A", "a", requires={"arousal": 50}),
                DialogOption("B", "b")]
        node = DialogNode(node_id="n1", scene="s", situation="t", options=opts)
        filtered = node.filter_options()
        assert len(filtered) == 2

    def test_filter_options_with_stats(self):
        from engine.mcp.dialog_system import DialogNode, DialogOption
        opts = [DialogOption("A", "a", requires={"arousal": 50}),
                DialogOption("B", "b")]
        node = DialogNode(node_id="n1", scene="s", situation="t", options=opts)
        filtered = node.filter_options(stats={"arousal": 30})
        assert len(filtered) == 1
        assert filtered[0].label == "B"


# ══════════════════════════════════════════════════════════════════════
#  DialogTree tests
# ══════════════════════════════════════════════════════════════════════

class TestDialogTree:
    def test_get_options_returns_options(self):
        from engine.mcp.dialog_system import DialogTree, DialogNode, DialogOption
        tree = DialogTree("test_scene")
        tree.add_node(DialogNode(
            node_id="n1", scene="test_scene", situation="test",
            tags=["greet"],
            options=[DialogOption("Hi", "Hello"), DialogOption("Wave", "Waves hand")],
        ))
        opts = tree.get_options(["greet"])
        assert len(opts) >= 1

    def test_get_options_empty_tree(self):
        from engine.mcp.dialog_system import DialogTree
        tree = DialogTree("empty")
        opts = tree.get_options(["anything"])
        assert opts == []

    def test_get_options_fallback_when_no_match(self):
        from engine.mcp.dialog_system import DialogTree, DialogNode, DialogOption
        tree = DialogTree("s")
        tree.add_node(DialogNode(
            node_id="n1", scene="s", situation="t",
            tags=["alpha"],
            options=[DialogOption("X", "x")],
        ))
        # No matching tags but expand_if_empty=True (default)
        opts = tree.get_options(["beta"])
        assert len(opts) >= 1

    def test_get_options_no_fallback(self):
        from engine.mcp.dialog_system import DialogTree, DialogNode, DialogOption
        tree = DialogTree("s")
        tree.add_node(DialogNode(
            node_id="n1", scene="s", situation="t",
            tags=["alpha"],
            options=[DialogOption("X", "x")],
        ))
        opts = tree.get_options(["beta"], expand_if_empty=False)
        assert opts == []

    def test_max_options_limit(self):
        from engine.mcp.dialog_system import DialogTree, DialogNode, DialogOption
        tree = DialogTree("s")
        many_opts = [DialogOption(f"O{i}", f"text{i}") for i in range(10)]
        tree.add_node(DialogNode(
            node_id="n1", scene="s", situation="t", options=many_opts,
        ))
        opts = tree.get_options([], max_options=3)
        assert len(opts) <= 3


# ══════════════════════════════════════════════════════════════════════
#  ConversationState tests
# ══════════════════════════════════════════════════════════════════════

class TestConversationState:
    def _make(self):
        from engine.mcp.dialog_system import ConversationState
        return ConversationState()

    def test_bump_heat_increases(self):
        cs = self._make()
        cs.bump_heat(25)
        assert cs.heat == 25.0

    def test_bump_heat_clamps_at_100(self):
        cs = self._make()
        cs.bump_heat(150)
        assert cs.heat == 100.0

    def test_bump_heat_clamps_at_0(self):
        cs = self._make()
        cs.bump_heat(-50)
        assert cs.heat == 0.0

    def test_add_and_get_topics(self):
        cs = self._make()
        cs.add_topics(["cuddle", "kiss"])
        cs.add_topics(["talk"])
        tags = cs.get_recent_tags(depth=2)
        assert "cuddle" in tags
        assert "talk" in tags

    def test_tick_increments_turn(self):
        cs = self._make()
        assert cs.turn == 0
        cs.tick()
        assert cs.turn == 1

    def test_set_and_consume_directive(self):
        from engine.mcp.dialog_system import ResponseDirective
        cs = self._make()
        d = ResponseDirective(directive_type="force_response", value="Hello!", turns=2)
        cs.set_directive(d)
        consumed = cs.consume_directive()
        assert consumed is not None
        assert consumed.value == "Hello!"
        assert consumed.turns == 1  # decremented
        # Still active (1 turn remaining)
        consumed2 = cs.consume_directive()
        assert consumed2 is not None
        # Now exhausted
        assert cs.directive is None

    def test_consume_directive_returns_none_when_empty(self):
        cs = self._make()
        assert cs.consume_directive() is None

    def test_style_lock(self):
        cs = self._make()
        cs.set_style_lock("dominant", turns=2)
        assert cs.consume_style_lock() == "dominant"
        assert cs.consume_style_lock() == "dominant"
        # Exhausted
        assert cs.consume_style_lock() is None

    def test_record_response(self):
        cs = self._make()
        cs.record_response("resp-001", "happy")
        assert cs.last_response_id == "resp-001"
        assert cs.recent_mood == "happy"

    def test_branch_point(self):
        cs = self._make()
        cs.record_response("r0")
        cs.record_response("r1")
        cs.record_response("r2")
        assert cs.branch_point(-1) == "r2"
        assert cs.branch_point(0) == "r0"


# ══════════════════════════════════════════════════════════════════════
#  ResponseDirective tests
# ══════════════════════════════════════════════════════════════════════

class TestResponseDirective:
    def test_to_dict(self):
        from engine.mcp.dialog_system import ResponseDirective
        d = ResponseDirective(directive_type="must_include", value="blush",
                              turns=3, issued_by="scene")
        out = d.to_dict()
        assert out["directive_type"] == "must_include"
        assert out["value"] == "blush"
        assert out["turns"] == 3
        assert out["issued_by"] == "scene"


# ══════════════════════════════════════════════════════════════════════
#  SpeechEnhancer tests
# ══════════════════════════════════════════════════════════════════════

class TestSpeechEnhancer:
    def _make(self):
        from engine.mcp.dialog_system import SpeechEnhancer
        return SpeechEnhancer()

    def test_build_rewrite_prompt_contains_text(self):
        enh = self._make()
        prompt = enh.build_rewrite_prompt("I guess so.", "teasing",
                                          character_name="Aria")
        assert "I guess so." in prompt
        assert "Aria" in prompt

    def test_quick_enhance_dominant_strips_hedges(self):
        from engine.mcp.dialog_system import SpeechStyle
        enh = self._make()
        result = enh.quick_enhance("I think maybe we should go.", SpeechStyle.DOMINANT)
        assert "maybe" not in result.lower()
        assert "i think" not in result.lower()

    def test_quick_enhance_whisper_adds_ellipsis(self):
        from engine.mcp.dialog_system import SpeechStyle
        enh = self._make()
        result = enh.quick_enhance("Come here.", SpeechStyle.WHISPER)
        assert result.endswith("…")

    def test_quick_enhance_natural_passthrough(self):
        from engine.mcp.dialog_system import SpeechStyle
        enh = self._make()
        result = enh.quick_enhance("Hello there.", SpeechStyle.NATURAL)
        assert result == "Hello there."

    def test_get_style_instruction(self):
        from engine.mcp.dialog_system import SpeechStyle
        enh = self._make()
        instr = enh.get_style_instruction(SpeechStyle.WARM)
        assert "warm" in instr.lower()

    def test_get_style_instruction_unknown_falls_back(self):
        enh = self._make()
        instr = enh.get_style_instruction("nonexistent_style")
        assert len(instr) > 0  # falls back to NATURAL


# ══════════════════════════════════════════════════════════════════════
#  DialogSystem integration tests
# ══════════════════════════════════════════════════════════════════════

class TestDialogSystem:
    def test_init_bootstraps_trees(self):
        ds = _fresh_dialog_system()
        bedroom_tree = ds.get_tree("penthouse")
        assert bedroom_tree is not None
        assert len(bedroom_tree._nodes) > 0

    def test_get_tree_creates_new_for_unknown_scene(self):
        ds = _fresh_dialog_system()
        tree = ds.get_tree("nonexistent_scene")
        assert tree is not None
        assert tree.scene == "nonexistent_scene"

    def test_get_options_returns_dicts(self):
        ds = _fresh_dialog_system()
        opts = ds.get_options("aria", "penthouse", context_tags=["cuddle"])
        assert isinstance(opts, list)
        if opts:
            assert "label" in opts[0]
            assert "text" in opts[0]
            assert "tag" in opts[0]

    def test_get_options_empty_scene(self):
        ds = _fresh_dialog_system()
        opts = ds.get_options("aria", "totally_empty_scene", context_tags=["x"])
        assert opts == []

    def test_get_options_phone_scene(self):
        ds = _fresh_dialog_system()
        opts = ds.get_options("aria", "phone", context_tags=["flirt"])
        assert isinstance(opts, list)
        assert len(opts) >= 1

    def test_enhance_speech_returns_expected_keys(self):
        ds = _fresh_dialog_system()
        with patch("engine.mcp.character_registry.get_character_registry",
                   return_value=_mock_character_registry()):
            result = ds.enhance_speech("aria", "Okay, sure.")
        assert "original_text" in result
        assert "quick_version" in result
        assert "rewrite_prompt" in result
        assert "style" in result
        assert result["original_text"] == "Okay, sure."

    def test_enhance_speech_with_explicit_style(self):
        ds = _fresh_dialog_system()
        with patch("engine.mcp.character_registry.get_character_registry",
                   return_value=_mock_character_registry()):
            result = ds.enhance_speech("aria", "Whatever.", style="dominant")
        assert result["style"] == "dominant"

    def test_set_and_get_directive(self):
        ds = _fresh_dialog_system()
        ds.set_directive("aria", "penthouse", "force_response",
                         "She leans in.", turns=2)
        d = ds.get_active_directive("aria", "penthouse")
        assert d is not None
        assert d.directive_type == "force_response"
        assert d.value == "She leans in."
        assert d.turns == 2

    def test_consume_directive_decrements_turns(self):
        ds = _fresh_dialog_system()
        ds.set_directive("aria", "penthouse", "must_include",
                         "blushes", turns=1)
        consumed = ds.consume_directive("aria", "penthouse")
        assert consumed is not None
        assert consumed.value == "blushes"
        # After consumption, directive is cleared
        assert ds.get_active_directive("aria", "penthouse") is None

    def test_clear_directive(self):
        ds = _fresh_dialog_system()
        ds.set_directive("aria", "penthouse", "topic_steer", "stars")
        ds.clear_directive("aria", "penthouse")
        assert ds.get_active_directive("aria", "penthouse") is None

    def test_directive_lifecycle_set_get_clear(self):
        ds = _fresh_dialog_system()
        # Initially no directive
        assert ds.get_active_directive("aria", "phone") is None
        # Set
        ds.set_directive("aria", "phone", "mood_set", "excited", turns=3)
        d = ds.get_active_directive("aria", "phone")
        assert d.directive_type == "mood_set"
        # Clear
        ds.clear_directive("aria", "phone")
        assert ds.get_active_directive("aria", "phone") is None

    def test_conversation_heat(self):
        ds = _fresh_dialog_system()
        assert ds.get_conversation_heat("aria", "penthouse") == 0.0
        new_heat = ds.bump_heat("aria", "penthouse", 30)
        assert new_heat == 30.0
        assert ds.get_conversation_heat("aria", "penthouse") == 30.0

    def test_heat_clamped(self):
        ds = _fresh_dialog_system()
        ds.bump_heat("aria", "penthouse", 200)
        assert ds.get_conversation_heat("aria", "penthouse") == 100.0

    def test_record_and_get_topics(self):
        ds = _fresh_dialog_system()
        ds.record_topics("aria", "penthouse", ["cuddle", "kiss"])
        ds.record_topics("aria", "penthouse", ["talk"])
        tags = ds.get_recent_topics("aria", "penthouse")
        assert "cuddle" in tags
        assert "talk" in tags

    def test_tick_and_get_turn(self):
        ds = _fresh_dialog_system()
        assert ds.get_turn("aria", "penthouse") == 0
        ds.tick("aria", "penthouse")
        ds.tick("aria", "penthouse")
        assert ds.get_turn("aria", "penthouse") == 2

    def test_build_memory_hook_empty(self):
        ds = _fresh_dialog_system()
        assert ds.build_memory_hook([]) == ""

    def test_build_memory_hook_with_memories(self):
        ds = _fresh_dialog_system()
        hook = ds.build_memory_hook(["talked about stars", "laughed together"],
                                    character_name="Aria")
        assert "Aria" in hook
        assert "stars" in hook

    def test_add_node(self):
        from engine.mcp.dialog_system import DialogNode, DialogOption
        ds = _fresh_dialog_system()
        ds.add_node("custom_scene", DialogNode(
            node_id="custom1", scene="custom_scene", situation="test",
            tags=["hello"],
            options=[DialogOption("Greet", "Hi there")],
        ))
        opts = ds.get_options("aria", "custom_scene", context_tags=["hello"])
        assert len(opts) == 1
        assert opts[0]["label"] == "Greet"

    def test_separate_convo_per_character_scene(self):
        ds = _fresh_dialog_system()
        ds.bump_heat("aria", "penthouse", 50)
        ds.bump_heat("luna", "penthouse", 10)
        assert ds.get_conversation_heat("aria", "penthouse") == 50.0
        assert ds.get_conversation_heat("luna", "penthouse") == 10.0

    def test_style_lock_via_set_directive(self):
        ds = _fresh_dialog_system()
        ds.set_directive("aria", "penthouse", "style_lock", "charged", turns=2)
        d = ds.get_active_directive("aria", "penthouse")
        assert d.directive_type == "style_lock"
        assert d.value == "charged"

    def test_record_response_and_branch(self):
        ds = _fresh_dialog_system()
        ds.record_response("aria", "penthouse", "resp-001", "happy")
        ds.record_response("aria", "penthouse", "resp-002", "excited")
        branch = ds.get_branch_point("aria", "penthouse", 0)
        assert branch == "resp-001"


# ══════════════════════════════════════════════════════════════════════
#  ConversationHeat (scene_rules_engine) tests
# ══════════════════════════════════════════════════════════════════════

class TestConversationHeat:
    def _make(self):
        from engine.mcp.scene_rules_engine import ConversationHeat
        return ConversationHeat()

    def test_initial_heat_is_zero(self):
        heat = self._make()
        assert heat.get("thread1") == 0.0

    def test_bump_increases_heat(self):
        heat = self._make()
        new_val = heat.bump("thread1", 25, "flirt")
        assert new_val == 25.0
        assert heat.get("thread1") == pytest.approx(25.0, abs=1.0)

    def test_bump_clamps_at_max(self):
        heat = self._make()
        heat.bump("t", 200)
        assert heat.get("t") == pytest.approx(100.0, abs=1.0)

    def test_cool_decreases_heat(self):
        heat = self._make()
        heat.bump("t", 50)
        new_val = heat.cool("t", 20)
        assert new_val == pytest.approx(30.0, abs=1.0)

    def test_cool_clamps_at_min(self):
        heat = self._make()
        heat.bump("t", 10)
        new_val = heat.cool("t", 100)
        assert new_val == 0.0

    def test_get_directive_cold(self):
        heat = self._make()
        # Heat 0 → no directive
        assert heat.get_directive("t") == ""

    def test_get_directive_warm(self):
        heat = self._make()
        heat.bump("t", 35)
        d = heat.get_directive("t")
        assert "WARM" in d

    def test_get_directive_hot(self):
        heat = self._make()
        heat.bump("t", 65)
        d = heat.get_directive("t")
        assert "HOT" in d

    def test_get_directive_intense(self):
        heat = self._make()
        heat.bump("t", 85)
        d = heat.get_directive("t")
        assert "INTENSE" in d

    def test_analyze_message_with_keywords(self):
        heat = self._make()
        new_val = heat.analyze_message("t", "I want to kiss you")
        assert new_val > 0

    def test_analyze_message_no_keywords(self):
        heat = self._make()
        new_val = heat.analyze_message("t", "The weather is nice")
        assert new_val == 0.0

    def test_to_dict(self):
        heat = self._make()
        heat.bump("a", 10)
        heat.bump("b", 20)
        snapshot = heat.to_dict()
        assert "a" in snapshot
        assert "b" in snapshot
