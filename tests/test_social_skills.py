"""Tests for social_skills.py — social, environment, and narrative MCP skills."""
import pytest
from unittest.mock import MagicMock, patch, call


# ── Patch paths (source modules — skills use local imports) ──────────
_FW = "engine.mcp.framework.get_framework"
_SSM = "engine.mcp.scene_state.get_scene_state_manager"
_REG = "engine.mcp.character_registry.get_character_registry"
_ROUTER = "engine.mcp.comms_framework.get_router"
_DIALOG = "engine.mcp.dialog_system.get_dialog_system"


# ── Helper factories ────────────────────────────────────────────────
def _mock_char(current_scene="living_room"):
    """Create a mock character node with a current_scene attribute."""
    char = MagicMock()
    char.current_scene = current_scene
    return char


def _mock_scene(present=None, events=None):
    """Create a mock scene with get_present() and get_event_log(limit)."""
    scene = MagicMock()
    scene.get_present.return_value = present or []
    scene.get_event_log.return_value = events or []
    return scene


def _mock_record(relationships=None):
    """Create a mock character record with state.relationships."""
    rec = MagicMock()
    rec.state = MagicMock()
    rec.state.relationships = relationships if relationships is not None else {}
    return rec


# ════════════════════════════════════════════════════════════════════
#  MOOD CONTAGION
# ════════════════════════════════════════════════════════════════════

class TestMoodContagion:
    """Tests for the mood_contagion skill."""

    @patch(_SSM)
    @patch(_FW)
    def test_spreads_mood_to_multiple_characters(self, mock_fw_fn, mock_ssm_fn):
        """Mood propagates to all other characters in the scene."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_character.return_value = _mock_char("penthouse")
        fw.get_characters_in_scene.return_value = ["alice", "bob", "carol"]

        from engine.skills.builtin.social_skills import mood_contagion
        result = mood_contagion("alice", "happy", intensity=0.5, scene_id="penthouse")

        assert "bob" in result
        assert "carol" in result
        assert "happy" in result
        assert ssm.update_stats.call_count == 2
        ssm.update_stats.assert_any_call("bob", happy=10)
        ssm.update_stats.assert_any_call("carol", happy=10)

    @patch(_SSM)
    @patch(_FW)
    def test_intensity_scales_delta(self, mock_fw_fn, mock_ssm_fn):
        """Higher intensity produces a larger stat delta (int(intensity * 20))."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_character.return_value = _mock_char("room")
        fw.get_characters_in_scene.return_value = ["src", "target"]

        from engine.skills.builtin.social_skills import mood_contagion
        mood_contagion("src", "sad", intensity=1.0, scene_id="room")

        ssm.update_stats.assert_called_once_with("target", sad=20)

    @patch(_SSM)
    @patch(_FW)
    def test_no_other_characters_in_scene(self, mock_fw_fn, mock_ssm_fn):
        """When only the source character is in the scene, nothing spreads."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_character.return_value = _mock_char("lonely_room")
        fw.get_characters_in_scene.return_value = ["solo"]

        from engine.skills.builtin.social_skills import mood_contagion
        result = mood_contagion("solo", "bored", scene_id="lonely_room")

        assert "No other characters" in result
        ssm.update_stats.assert_not_called()

    @patch(_SSM)
    @patch(_FW)
    def test_no_scene_returns_not_in_scene(self, mock_fw_fn, mock_ssm_fn):
        """Character without a scene gets a clear error message."""
        fw = mock_fw_fn.return_value
        fw.get_character.return_value = _mock_char(current_scene="")

        from engine.skills.builtin.social_skills import mood_contagion
        result = mood_contagion("ghost", "fear", scene_id="")

        assert "not in a scene" in result

    @patch(_SSM)
    @patch(_FW)
    def test_uses_char_current_scene_when_scene_id_omitted(self, mock_fw_fn, mock_ssm_fn):
        """When scene_id is empty, fall back to the character's current_scene."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_character.return_value = _mock_char("fallback_scene")
        fw.get_characters_in_scene.return_value = ["src", "other"]

        from engine.skills.builtin.social_skills import mood_contagion
        mood_contagion("src", "calm")

        fw.get_characters_in_scene.assert_called_once_with("fallback_scene")

    @patch(_SSM)
    @patch(_FW)
    def test_emits_mood_contagion_event(self, mock_fw_fn, mock_ssm_fn):
        """An event is always emitted, even if no characters are affected."""
        fw = mock_fw_fn.return_value
        fw.get_character.return_value = _mock_char("room")
        fw.get_characters_in_scene.return_value = ["a", "b"]

        from engine.skills.builtin.social_skills import mood_contagion
        mood_contagion("a", "joy", intensity=0.3, scene_id="room")

        fw.emit_event.assert_called_once()
        event_data = fw.emit_event.call_args[0][1]
        assert event_data["source"] == "a"
        assert event_data["mood"] == "joy"
        assert event_data["affected"] == ["b"]

    @patch(_SSM)
    @patch(_FW)
    def test_exception_returns_failure_message(self, mock_fw_fn, mock_ssm_fn):
        """Exceptions are caught and returned as a failure string."""
        mock_fw_fn.side_effect = RuntimeError("framework down")

        from engine.skills.builtin.social_skills import mood_contagion
        result = mood_contagion("x", "panic")

        assert "Mood contagion failed" in result
        assert "framework down" in result

    @patch(_SSM)
    @patch(_FW)
    def test_default_intensity_is_half(self, mock_fw_fn, mock_ssm_fn):
        """Default intensity=0.5 yields delta of 10."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_character.return_value = _mock_char("s")
        fw.get_characters_in_scene.return_value = ["src", "tgt"]

        from engine.skills.builtin.social_skills import mood_contagion
        mood_contagion("src", "relaxed", scene_id="s")

        ssm.update_stats.assert_called_once_with("tgt", relaxed=10)


# ════════════════════════════════════════════════════════════════════
#  RELATIONSHIP ADJUST
# ════════════════════════════════════════════════════════════════════

class TestRelationshipAdjust:
    """Tests for the relationship_adjust skill."""

    @patch(_FW)
    @patch(_REG)
    def test_success_default_trust(self, mock_reg_fn, mock_fw_fn):
        """Default dimension is 'trust', default delta is +5.0."""
        reg = mock_reg_fn.return_value
        rec_a = _mock_record()
        rec_b = _mock_record()
        reg.get_record.side_effect = lambda cid: {"alice": rec_a, "bob": rec_b}[cid]

        from engine.skills.builtin.social_skills import relationship_adjust
        result = relationship_adjust("alice", "bob")

        assert "trust" in result
        assert "alice" in result
        assert "bob" in result
        assert "+5.0" in result

    @patch(_FW)
    @patch(_REG)
    def test_custom_dimension(self, mock_reg_fn, mock_fw_fn):
        """Non-default dimensions like 'affection' are respected."""
        reg = mock_reg_fn.return_value
        rec = _mock_record()
        reg.get_record.return_value = rec

        from engine.skills.builtin.social_skills import relationship_adjust
        result = relationship_adjust("a", "b", dimension="affection", delta=10.0)

        assert "affection" in result
        assert "+10.0" in result

    @patch(_FW)
    @patch(_REG)
    def test_negative_delta(self, mock_reg_fn, mock_fw_fn):
        """Negative delta weakens the relationship."""
        reg = mock_reg_fn.return_value
        rec = _mock_record()
        reg.get_record.return_value = rec

        from engine.skills.builtin.social_skills import relationship_adjust
        result = relationship_adjust("a", "b", dimension="trust", delta=-15.0)

        assert "-15.0" in result

    @patch(_FW)
    @patch(_REG)
    def test_updates_both_directions(self, mock_reg_fn, mock_fw_fn):
        """Both (a→b) and (b→a) records are updated."""
        reg = mock_reg_fn.return_value
        rec_a = _mock_record()
        rec_b = _mock_record()
        reg.get_record.side_effect = lambda cid: {"x": rec_a, "y": rec_b}[cid]

        from engine.skills.builtin.social_skills import relationship_adjust
        relationship_adjust("x", "y", dimension="tension", delta=3.0)

        # get_record called for a→b and b→a
        assert reg.get_record.call_count == 2

    @patch(_FW)
    @patch(_REG)
    def test_emits_relationship_adjusted_event(self, mock_reg_fn, mock_fw_fn):
        """An event is emitted with dimension and delta."""
        fw = mock_fw_fn.return_value
        reg = mock_reg_fn.return_value
        reg.get_record.return_value = _mock_record()

        from engine.skills.builtin.social_skills import relationship_adjust
        relationship_adjust("a", "b", dimension="rivalry", delta=8.0)

        fw.emit_event.assert_called_once()
        data = fw.emit_event.call_args[0][1]
        assert data["dimension"] == "rivalry"
        assert data["delta"] == 8.0

    @patch(_FW)
    @patch(_REG)
    def test_clamps_to_0_100(self, mock_reg_fn, mock_fw_fn):
        """Values are clamped to [0, 100] range."""
        reg = mock_reg_fn.return_value
        rec = _mock_record(relationships={"b": {"trust": 95.0}})
        reg.get_record.return_value = rec

        from engine.skills.builtin.social_skills import relationship_adjust
        relationship_adjust("a", "b", dimension="trust", delta=20.0)

        # After clamping: min(100, 95+20) = 100
        assert rec.state.relationships["b"]["trust"] == 100

    @patch(_FW)
    @patch(_REG)
    def test_clamps_to_zero_floor(self, mock_reg_fn, mock_fw_fn):
        """Negative delta cannot push below 0."""
        reg = mock_reg_fn.return_value
        rec = _mock_record(relationships={"b": {"trust": 5.0}})
        reg.get_record.return_value = rec

        from engine.skills.builtin.social_skills import relationship_adjust
        relationship_adjust("a", "b", dimension="trust", delta=-20.0)

        assert rec.state.relationships["b"]["trust"] == 0

    @patch(_FW)
    @patch(_REG)
    def test_exception_returns_failure(self, mock_reg_fn, mock_fw_fn):
        """Exceptions are caught and reported."""
        mock_reg_fn.side_effect = RuntimeError("registry offline")

        from engine.skills.builtin.social_skills import relationship_adjust
        result = relationship_adjust("a", "b")

        assert "Relationship adjust failed" in result
        assert "registry offline" in result

    @patch(_FW)
    @patch(_REG)
    def test_record_without_state_is_skipped(self, mock_reg_fn, mock_fw_fn):
        """If rec has no state, the record is skipped gracefully."""
        reg = mock_reg_fn.return_value
        rec = MagicMock()
        rec.state = None
        reg.get_record.return_value = rec

        from engine.skills.builtin.social_skills import relationship_adjust
        result = relationship_adjust("a", "b")

        # Should still complete — no crash
        assert "trust" in result


# ════════════════════════════════════════════════════════════════════
#  SCENE BROADCAST
# ════════════════════════════════════════════════════════════════════

class TestSceneBroadcast:
    """Tests for the scene_broadcast skill."""

    @patch(_ROUTER)
    @patch(_SSM)
    @patch(_FW)
    def test_broadcasts_to_all_present(self, mock_fw_fn, mock_ssm_fn, mock_router_fn):
        """Message is routed to every character in the scene."""
        fw = mock_fw_fn.return_value
        router = mock_router_fn.return_value
        fw.get_scene.return_value = _mock_scene(present=["a", "b", "c"])

        from engine.skills.builtin.social_skills import scene_broadcast
        result = scene_broadcast("room1", "Lights flicker.")

        assert "3 characters" in result
        assert router.send.call_count == 3

    @patch(_ROUTER)
    @patch(_SSM)
    @patch(_FW)
    def test_adds_narrative_entry(self, mock_fw_fn, mock_ssm_fn, mock_router_fn):
        """Message is recorded in scene narrative."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value
        fw.get_scene.return_value = _mock_scene(present=["x"])

        from engine.skills.builtin.social_skills import scene_broadcast
        scene_broadcast("room", "Thunder rolls.", sender="system", message_type="atmosphere")

        ssm.add_narrative.assert_called_once_with(
            "room", "Thunder rolls.",
            entry_type="atmosphere", character_id="system",
        )

    @patch(_ROUTER)
    @patch(_SSM)
    @patch(_FW)
    def test_default_sender_is_narrator(self, mock_fw_fn, mock_ssm_fn, mock_router_fn):
        """If no sender is specified, defaults to 'narrator'."""
        fw = mock_fw_fn.return_value
        fw.get_scene.return_value = _mock_scene(present=["z"])
        router = mock_router_fn.return_value

        from engine.skills.builtin.social_skills import scene_broadcast
        scene_broadcast("s1", "Hello")

        sent_msg = router.send.call_args[0][1]
        assert "[narrator]" in sent_msg

    @patch(_ROUTER)
    @patch(_SSM)
    @patch(_FW)
    def test_emits_scene_broadcast_event(self, mock_fw_fn, mock_ssm_fn, mock_router_fn):
        """An event with truncated message is emitted."""
        fw = mock_fw_fn.return_value
        fw.get_scene.return_value = _mock_scene(present=["a"])

        from engine.skills.builtin.social_skills import scene_broadcast
        scene_broadcast("s", "A long narration.")

        fw.emit_event.assert_called_once()
        data = fw.emit_event.call_args[0][1]
        assert data["scene_id"] == "s"
        assert data["recipients"] == ["a"]

    @patch(_ROUTER)
    @patch(_SSM)
    @patch(_FW)
    def test_exception_returns_failure(self, mock_fw_fn, mock_ssm_fn, mock_router_fn):
        """Exceptions produce a clear failure message."""
        mock_fw_fn.side_effect = RuntimeError("boom")

        from engine.skills.builtin.social_skills import scene_broadcast
        result = scene_broadcast("s", "msg")

        assert "Broadcast failed" in result
        assert "boom" in result


# ════════════════════════════════════════════════════════════════════
#  ENVIRONMENT CHANGE
# ════════════════════════════════════════════════════════════════════

class TestEnvironmentChange:
    """Tests for the environment_change skill."""

    @patch(_SSM)
    @patch(_FW)
    def test_success_with_default_description(self, mock_fw_fn, mock_ssm_fn):
        """Auto-generated description uses change_type and value."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        from engine.skills.builtin.social_skills import environment_change
        result = environment_change("cafe", "lighting", "dim candles")

        assert "cafe" in result
        assert "lighting" in result
        assert "dim candles" in result
        ssm.add_narrative.assert_called_once()
        narrative_text = ssm.add_narrative.call_args[0][1]
        assert "lighting" in narrative_text
        assert "dim candles" in narrative_text

    @patch(_SSM)
    @patch(_FW)
    def test_custom_description_overrides_default(self, mock_fw_fn, mock_ssm_fn):
        """Explicit description replaces the auto-generated one."""
        ssm = mock_ssm_fn.return_value

        from engine.skills.builtin.social_skills import environment_change
        environment_change("room", "music", "jazz", description="Smooth jazz fills the air")

        narrative_text = ssm.add_narrative.call_args[0][1]
        assert narrative_text == "Smooth jazz fills the air"

    @patch(_SSM)
    @patch(_FW)
    def test_emits_environment_change_event(self, mock_fw_fn, mock_ssm_fn):
        """Event payload includes change_type, value, and description."""
        fw = mock_fw_fn.return_value

        from engine.skills.builtin.social_skills import environment_change
        environment_change("s", "temperature", "warm")

        fw.emit_event.assert_called_once()
        data = fw.emit_event.call_args[0][1]
        assert data["change_type"] == "temperature"
        assert data["value"] == "warm"
        assert data["scene_id"] == "s"

    @patch(_SSM)
    @patch(_FW)
    def test_narrative_entry_type_is_environment(self, mock_fw_fn, mock_ssm_fn):
        """Narrative entry is tagged with entry_type='environment'."""
        ssm = mock_ssm_fn.return_value

        from engine.skills.builtin.social_skills import environment_change
        environment_change("s", "prop_add", "candelabra")

        ssm.add_narrative.assert_called_once()
        assert ssm.add_narrative.call_args[1]["entry_type"] == "environment"

    @patch(_SSM)
    @patch(_FW)
    def test_exception_returns_failure(self, mock_fw_fn, mock_ssm_fn):
        """Exceptions are caught and reported."""
        mock_fw_fn.side_effect = ValueError("bad scene")

        from engine.skills.builtin.social_skills import environment_change
        result = environment_change("x", "lighting", "off")

        assert "Environment change failed" in result
        assert "bad scene" in result


# ════════════════════════════════════════════════════════════════════
#  GET SCENE SNAPSHOT
# ════════════════════════════════════════════════════════════════════

class TestGetSceneSnapshot:
    """Tests for the get_scene_snapshot skill."""

    @patch(_SSM)
    @patch(_FW)
    def test_snapshot_with_characters_and_narrative(self, mock_fw_fn, mock_ssm_fn):
        """Snapshot includes scene name, present characters, and narrative."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_scene.return_value = _mock_scene(
            present=["alice", "bob"],
            events=[{"type": "enter"}],
        )
        ssm.get_narrative.return_value = [
            {"text": "Alice sits down."},
            "Bob waves hello.",
        ]

        from engine.skills.builtin.social_skills import get_scene_snapshot
        result = get_scene_snapshot("living_room")

        assert "living_room" in result
        assert "alice" in result
        assert "bob" in result
        assert "Alice sits down." in result
        assert "Bob waves hello." in result
        assert "Recent narrative:" in result

    @patch(_SSM)
    @patch(_FW)
    def test_empty_scene(self, mock_fw_fn, mock_ssm_fn):
        """Empty scene shows 'empty' for present characters."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_scene.return_value = _mock_scene(present=[], events=[])
        ssm.get_narrative.return_value = []

        from engine.skills.builtin.social_skills import get_scene_snapshot
        result = get_scene_snapshot("void")

        assert "void" in result
        assert "empty" in result
        assert "Recent narrative:" not in result

    @patch(_SSM)
    @patch(_FW)
    def test_narrative_entries_are_string_or_dict(self, mock_fw_fn, mock_ssm_fn):
        """Both plain strings and dicts with 'text' key are rendered."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        fw.get_scene.return_value = _mock_scene(present=["a"])
        ssm.get_narrative.return_value = [
            "Plain string entry",
            {"text": "Dict-based entry"},
        ]

        from engine.skills.builtin.social_skills import get_scene_snapshot
        result = get_scene_snapshot("test_scene")

        assert "Plain string entry" in result
        assert "Dict-based entry" in result

    @patch(_SSM)
    @patch(_FW)
    def test_narrative_limit_is_five(self, mock_fw_fn, mock_ssm_fn):
        """get_narrative is called with limit=5."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value
        fw.get_scene.return_value = _mock_scene(present=[])
        ssm.get_narrative.return_value = []

        from engine.skills.builtin.social_skills import get_scene_snapshot
        get_scene_snapshot("s")

        ssm.get_narrative.assert_called_once_with("s", limit=5)

    @patch(_SSM)
    @patch(_FW)
    def test_long_narrative_is_truncated_to_80_chars(self, mock_fw_fn, mock_ssm_fn):
        """Each narrative line is truncated to 80 characters."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value
        fw.get_scene.return_value = _mock_scene(present=[])
        long_text = "X" * 120
        ssm.get_narrative.return_value = [long_text]

        from engine.skills.builtin.social_skills import get_scene_snapshot
        result = get_scene_snapshot("s")

        # The bullet line should contain only 80 chars of the text
        for line in result.splitlines():
            if "•" in line:
                # Strip the bullet prefix "  • " then check length
                content = line.split("• ", 1)[1]
                assert len(content) == 80

    @patch(_SSM)
    @patch(_FW)
    def test_exception_returns_failure(self, mock_fw_fn, mock_ssm_fn):
        """Exceptions produce a clear failure message."""
        mock_fw_fn.side_effect = KeyError("scene not found")

        from engine.skills.builtin.social_skills import get_scene_snapshot
        result = get_scene_snapshot("missing")

        assert "Scene snapshot failed" in result


# ════════════════════════════════════════════════════════════════════
#  INJECT STORY BEAT
# ════════════════════════════════════════════════════════════════════

class TestInjectStoryBeat:
    """Tests for the inject_story_beat skill."""

    @patch(_SSM)
    @patch(_FW)
    def test_success_default_urgency(self, mock_fw_fn, mock_ssm_fn):
        """Story beat is injected with default urgency='normal'."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        from engine.skills.builtin.social_skills import inject_story_beat
        result = inject_story_beat("garden", "A stranger arrives at the gate.")

        assert "garden" in result
        assert "urgency=normal" in result
        assert "A stranger arrives" in result

        ssm.add_narrative.assert_called_once_with(
            "garden", "A stranger arrives at the gate.",
            entry_type="story_beat", character_id="",
        )

    @patch(_SSM)
    @patch(_FW)
    def test_with_character_and_urgency(self, mock_fw_fn, mock_ssm_fn):
        """Character and urgency are forwarded correctly."""
        fw = mock_fw_fn.return_value
        ssm = mock_ssm_fn.return_value

        from engine.skills.builtin.social_skills import inject_story_beat
        result = inject_story_beat(
            "throne_room", "The king collapses!",
            character_id="king", urgency="critical",
        )

        assert "urgency=critical" in result
        ssm.add_narrative.assert_called_once_with(
            "throne_room", "The king collapses!",
            entry_type="story_beat", character_id="king",
        )

    @patch(_SSM)
    @patch(_FW)
    def test_emits_story_beat_event(self, mock_fw_fn, mock_ssm_fn):
        """Event includes scene_id, beat, character_id, and urgency."""
        fw = mock_fw_fn.return_value

        from engine.skills.builtin.social_skills import inject_story_beat
        inject_story_beat("s", "tension rises", character_id="villain", urgency="high")

        fw.emit_event.assert_called_once()
        data = fw.emit_event.call_args[0][1]
        assert data["scene_id"] == "s"
        assert data["beat"] == "tension rises"
        assert data["character_id"] == "villain"
        assert data["urgency"] == "high"

    @patch(_SSM)
    @patch(_FW)
    def test_event_source_is_scene_id(self, mock_fw_fn, mock_ssm_fn):
        """Event is emitted with source=scene_id."""
        fw = mock_fw_fn.return_value

        from engine.skills.builtin.social_skills import inject_story_beat
        inject_story_beat("my_scene", "plot twist")

        _, kwargs = fw.emit_event.call_args
        assert kwargs["source"] == "my_scene"

    @patch(_SSM)
    @patch(_FW)
    def test_long_beat_is_truncated_in_result(self, mock_fw_fn, mock_ssm_fn):
        """Return string truncates beat to 80 chars."""
        from engine.skills.builtin.social_skills import inject_story_beat
        long_beat = "A" * 200
        result = inject_story_beat("s", long_beat)

        # The result should not contain the full 200-char beat
        assert "A" * 80 in result
        assert "A" * 81 not in result

    @patch(_SSM)
    @patch(_FW)
    def test_exception_returns_failure(self, mock_fw_fn, mock_ssm_fn):
        """Exceptions are caught and reported."""
        mock_fw_fn.side_effect = ConnectionError("no MCP")

        from engine.skills.builtin.social_skills import inject_story_beat
        result = inject_story_beat("s", "beat")

        assert "Story beat injection failed" in result
        assert "no MCP" in result


# ════════════════════════════════════════════════════════════════════
#  GET DIALOG OPTIONS
# ════════════════════════════════════════════════════════════════════

class TestGetDialogOptions:
    """Tests for the get_dialog_options skill."""

    @patch(_DIALOG)
    def test_options_returned(self, mock_dialog_fn):
        """Available options are formatted as a bulleted list."""
        ds = mock_dialog_fn.return_value
        ds.get_options.return_value = [
            {"label": "Greet", "text": "Hello there, friend!"},
            {"label": "Ask", "text": "What brings you here?"},
        ]

        from engine.skills.builtin.social_skills import get_dialog_options
        result = get_dialog_options("alice", "tavern")

        assert "Available dialog options:" in result
        assert "[Greet]" in result
        assert "Hello there, friend!" in result
        assert "[Ask]" in result
        assert "What brings you here?" in result

    @patch(_DIALOG)
    def test_no_options_available(self, mock_dialog_fn):
        """Empty options list returns a 'speak freely' message."""
        ds = mock_dialog_fn.return_value
        ds.get_options.return_value = []

        from engine.skills.builtin.social_skills import get_dialog_options
        result = get_dialog_options("bob", "market")

        assert "speak freely" in result

    @patch(_DIALOG)
    def test_with_context_tags(self, mock_dialog_fn):
        """Comma-separated tags are parsed and forwarded."""
        ds = mock_dialog_fn.return_value
        ds.get_options.return_value = [{"label": "X", "text": "y"}]

        from engine.skills.builtin.social_skills import get_dialog_options
        get_dialog_options("c", "s", context_tags="romance, flirt, evening")

        called_tags = ds.get_options.call_args[1]["context_tags"]
        assert called_tags == ["romance", "flirt", "evening"]

    @patch(_DIALOG)
    def test_empty_tags_passes_empty_list(self, mock_dialog_fn):
        """Empty context_tags string results in an empty tag list."""
        ds = mock_dialog_fn.return_value
        ds.get_options.return_value = []

        from engine.skills.builtin.social_skills import get_dialog_options
        get_dialog_options("c", "s", context_tags="")

        called_tags = ds.get_options.call_args[1]["context_tags"]
        assert called_tags == []

    @patch(_DIALOG)
    def test_tags_strips_whitespace(self, mock_dialog_fn):
        """Tags with extra whitespace are stripped."""
        ds = mock_dialog_fn.return_value
        ds.get_options.return_value = []

        from engine.skills.builtin.social_skills import get_dialog_options
        get_dialog_options("c", "s", context_tags="  tag1 ,  tag2  , ")

        called_tags = ds.get_options.call_args[1]["context_tags"]
        assert called_tags == ["tag1", "tag2"]

    @patch(_DIALOG)
    def test_exception_returns_failure(self, mock_dialog_fn):
        """Exceptions are caught and reported."""
        mock_dialog_fn.side_effect = ImportError("dialog system unavailable")

        from engine.skills.builtin.social_skills import get_dialog_options
        result = get_dialog_options("c", "s")

        assert "Dialog options failed" in result
        assert "dialog system unavailable" in result

    @patch(_DIALOG)
    def test_long_text_truncated_to_60_chars(self, mock_dialog_fn):
        """Option text longer than 60 chars is truncated in the output."""
        ds = mock_dialog_fn.return_value
        long_text = "W" * 100
        ds.get_options.return_value = [{"label": "Verbose", "text": long_text}]

        from engine.skills.builtin.social_skills import get_dialog_options
        result = get_dialog_options("c", "s")

        assert "[Verbose]" in result
        # Should contain exactly 60 chars of the text
        assert "W" * 60 in result
        assert "W" * 61 not in result

    @patch(_DIALOG)
    def test_returns_none_option_values_gracefully(self, mock_dialog_fn):
        """Options missing label or text keys don't crash."""
        ds = mock_dialog_fn.return_value
        ds.get_options.return_value = [{"label": "", "text": ""}]

        from engine.skills.builtin.social_skills import get_dialog_options
        result = get_dialog_options("c", "s")

        assert "Available dialog options:" in result
        assert "[]" in result
