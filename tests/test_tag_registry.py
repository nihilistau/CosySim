"""Tests for TagRegistry — extensible inline tag system."""

import re
import pytest
from unittest.mock import MagicMock

from engine.mcp.tag_registry import TagRegistry, TagDef, TagMatch


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_registry():
    """Reset the TagRegistry singleton before each test."""
    TagRegistry.reset()
    yield
    TagRegistry.reset()


# ── Singleton ───────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_returns_same_instance(self):
        r1 = TagRegistry.get()
        r2 = TagRegistry.get()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        r1 = TagRegistry.get()
        TagRegistry.reset()
        r2 = TagRegistry.get()
        assert r1 is not r2


# ── Built-in tags ───────────────────────────────────────────────────────

class TestBuiltinTags:
    def test_builtins_registered(self):
        reg = TagRegistry.get()
        expected = {"mood", "image", "action", "stat", "voice",
                    "send", "event", "memory", "think"}
        assert set(reg.tag_names) == expected

    def test_tag_count(self):
        reg = TagRegistry.get()
        assert reg.tag_count == 9

    def test_get_tag(self):
        reg = TagRegistry.get()
        mood = reg.get_tag("mood")
        assert mood is not None
        assert mood.name == "mood"
        assert mood.pre_warm_intent == "mood_update"

    def test_image_aliases(self):
        reg = TagRegistry.get()
        img = reg.get_tag("image")
        assert "selfie" in img.aliases
        assert "photo" in img.aliases


# ── Detection ───────────────────────────────────────────────────────────

class TestDetection:
    def test_detect_mood(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[MOOD:happy]")
        assert "mood" in results
        assert results["mood"][0].value == "happy"

    def test_detect_image(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[IMAGE:a selfie in the bedroom]")
        assert "image" in results
        assert results["image"][0].value == "a selfie in the bedroom"

    def test_detect_selfie_alias(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[SELFIE:cute pose]")
        assert "image" in results
        assert results["image"][0].value == "cute pose"

    def test_detect_photo_alias(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[PHOTO:sunset view]")
        assert "image" in results

    def test_detect_action(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[ACTION:sit down]")
        assert "action" in results
        assert results["action"][0].value == "sit down"

    def test_detect_stat(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[STAT:arousal+10]")
        assert "stat" in results
        assert "arousal+10" in results["stat"][0].value

    def test_detect_voice(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[VOICE:whisper]")
        assert "voice" in results
        assert results["voice"][0].value == "whisper"

    def test_detect_send(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[SEND:lola]")
        assert "send" in results
        assert results["send"][0].value == "lola"

    def test_detect_event(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[EVENT:phone_ring]")
        assert "event" in results
        assert results["event"][0].value == "phone_ring"

    def test_detect_memory(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[MEMORY:user likes coffee]")
        assert "memory" in results
        assert results["memory"][0].value == "user likes coffee"

    def test_detect_think(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[THINK:I should be more flirty]")
        assert "think" in results
        assert results["think"][0].value == "I should be more flirty"

    def test_detect_multiple(self):
        text = "[MOOD:happy] She smiled [IMAGE:a selfie] and [ACTION:wave]"
        reg = TagRegistry.get()
        results = reg.detect_all(text)
        assert "mood" in results
        assert "image" in results
        assert "action" in results

    def test_detect_case_insensitive(self):
        reg = TagRegistry.get()
        results = reg.detect_all("[mood:happy] [Image:test]")
        assert "mood" in results
        assert "image" in results

    def test_detect_single_tag(self):
        reg = TagRegistry.get()
        matches = reg.detect_tag("mood", "[MOOD:happy] [IMAGE:test]")
        assert len(matches) == 1
        assert matches[0].value == "happy"

    def test_detect_no_match(self):
        reg = TagRegistry.get()
        results = reg.detect_all("Hello, how are you?")
        assert results == {}

    def test_tag_match_positions(self):
        reg = TagRegistry.get()
        results = reg.detect_all("Hello [MOOD:happy] world")
        m = results["mood"][0]
        assert m.start == 6
        assert m.end == 18


# ── Stripping ───────────────────────────────────────────────────────────

class TestStripping:
    def test_strip_mood(self):
        reg = TagRegistry.get()
        assert reg.strip_tags("[MOOD:happy] Hello") == "Hello"

    def test_strip_multiple(self):
        reg = TagRegistry.get()
        text = "[MOOD:happy] Hello [IMAGE:test] world [VOICE:whisper]"
        clean = reg.strip_tags(text)
        assert "MOOD" not in clean
        assert "IMAGE" not in clean
        assert "VOICE" not in clean
        assert "Hello" in clean
        assert "world" in clean

    def test_strip_routing_tags(self):
        reg = TagRegistry.get()
        text = "Hey [SEND:lola] [EVENT:ring] [MEMORY:note] [THINK:hmm] world"
        clean = reg.strip_tags(text)
        assert "SEND" not in clean
        assert "EVENT" not in clean
        assert "MEMORY" not in clean
        assert "THINK" not in clean
        assert "Hey" in clean
        assert "world" in clean

    def test_strip_pattern_cached(self):
        reg = TagRegistry.get()
        p1 = reg.get_strip_pattern()
        p2 = reg.get_strip_pattern()
        assert p1 is p2

    def test_strip_pattern_invalidated_on_register(self):
        reg = TagRegistry.get()
        p1 = reg.get_strip_pattern()
        reg.register(TagDef(name="custom", pattern=r"\[CUSTOM:([^\]]+)\]"))
        p2 = reg.get_strip_pattern()
        assert p1 is not p2


# ── Custom tag registration ─────────────────────────────────────────────

class TestCustomTags:
    def test_register_custom(self):
        reg = TagRegistry.get()
        reg.register(TagDef(
            name="plan",
            pattern=r"\[PLAN:([^\]]+)\]",
            pre_warm_intent="planning",
        ))
        assert "plan" in reg.tag_names
        results = reg.detect_all("[PLAN:rob the bank]")
        assert "plan" in results
        assert results["plan"][0].value == "rob the bank"

    def test_unregister(self):
        reg = TagRegistry.get()
        reg.register(TagDef(name="temp", pattern=r"\[TEMP:([^\]]+)\]"))
        assert "temp" in reg.tag_names
        reg.unregister("temp")
        assert "temp" not in reg.tag_names

    def test_custom_stripped(self):
        reg = TagRegistry.get()
        reg.register(TagDef(
            name="order",
            pattern=r"\[ORDER:([^\]]+)\]",
            strip_from_output=True,
        ))
        assert reg.strip_tags("Move [ORDER:advance] now") == "Move now"

    def test_custom_not_stripped(self):
        reg = TagRegistry.get()
        reg.register(TagDef(
            name="debug",
            pattern=r"\[DEBUG:([^\]]+)\]",
            strip_from_output=False,
        ))
        text = "Check [DEBUG:info] this"
        assert "[DEBUG:info]" in reg.strip_tags(text)


# ── Handler dispatch ────────────────────────────────────────────────────

class TestHandlerDispatch:
    def test_dispatch_with_handler(self):
        handler = MagicMock(return_value="ok")
        reg = TagRegistry.get()
        reg.register(TagDef(
            name="test_tag",
            pattern=r"\[TEST:([^\]]+)\]",
            handler=handler,
        ))
        result = reg.dispatch("test_tag", "hello", {"scene": "penthouse"})
        handler.assert_called_once_with("test_tag", "hello", {"scene": "penthouse"})
        assert result == "ok"

    def test_dispatch_no_handler(self):
        reg = TagRegistry.get()
        result = reg.dispatch("mood", "happy")
        assert result is None

    def test_dispatch_handler_error(self):
        handler = MagicMock(side_effect=ValueError("boom"))
        reg = TagRegistry.get()
        reg.register(TagDef(
            name="bad",
            pattern=r"\[BAD:([^\]]+)\]",
            handler=handler,
        ))
        result = reg.dispatch("bad", "val")
        assert result is None

    def test_dispatch_all(self):
        handler = MagicMock(return_value="done")
        reg = TagRegistry.get()
        reg.register(TagDef(
            name="cmd",
            pattern=r"\[CMD:([^\]]+)\]",
            handler=handler,
        ))
        matches = reg.detect_all("[CMD:one] [CMD:two]")
        results = reg.dispatch_all(matches)
        assert handler.call_count == 2
        assert "cmd" in results
        assert len(results["cmd"]) == 2


# ── Pre-warm intent ────────────────────────────────────────────────────

class TestPreWarmIntent:
    def test_get_intent(self):
        reg = TagRegistry.get()
        assert reg.get_pre_warm_intent("image") == "image_generation"
        assert reg.get_pre_warm_intent("mood") == "mood_update"
        assert reg.get_pre_warm_intent("send") == "send_message"
        assert reg.get_pre_warm_intent("event") == "fire_event"
        assert reg.get_pre_warm_intent("memory") == "memory_store"

    def test_think_no_intent(self):
        reg = TagRegistry.get()
        assert reg.get_pre_warm_intent("think") == ""

    def test_intent_map(self):
        reg = TagRegistry.get()
        imap = reg.get_intent_map()
        assert "image" in imap
        assert imap["image"] == "image_generation"
        assert "think" not in imap  # no intent for think

    def test_nonexistent_tag_intent(self):
        reg = TagRegistry.get()
        assert reg.get_pre_warm_intent("nonexistent") == ""


# ── Describe ────────────────────────────────────────────────────────────

class TestDescribe:
    def test_describe_contains_all_tags(self):
        reg = TagRegistry.get()
        desc = reg.describe()
        assert "[MOOD:value]" in desc
        assert "[IMAGE:value]" in desc
        assert "[SEND:value]" in desc
        assert "[THINK:value]" in desc

    def test_repr(self):
        reg = TagRegistry.get()
        r = repr(reg)
        assert "TagRegistry" in r
        assert "mood" in r


# ── Integration: StreamProcessor routing tags ───────────────────────────

class TestStreamProcessorRouting:
    """Test that StreamProcessor detects the new routing tags."""

    def test_send_tag(self):
        from engine.agents.stream_processor import StreamProcessor

        proc = StreamProcessor()
        # Simulate a message.delta event with [SEND:lola]
        class FakeEvent:
            event_type = "message.delta"
            content = "Hey [SEND:lola] tell her I said hi"
        proc.on_event(FakeEvent())

        class EndEvent:
            event_type = "chat.end"
            response_id = "test123"
            stats = {}
        proc.on_event(EndEvent())

        result = proc.result()
        assert "lola" in result.send_targets
        assert "SEND" not in result.clean_text

    def test_event_tag(self):
        from engine.agents.stream_processor import StreamProcessor
        proc = StreamProcessor()
        class FakeEvent:
            event_type = "message.delta"
            content = "[EVENT:phone_ring] The phone starts ringing"
        proc.on_event(FakeEvent())
        class EndEvent:
            event_type = "chat.end"
            response_id = ""
            stats = {}
        proc.on_event(EndEvent())
        result = proc.result()
        assert "phone_ring" in result.events

    def test_memory_tag(self):
        from engine.agents.stream_processor import StreamProcessor
        proc = StreamProcessor()
        class FakeEvent:
            event_type = "message.delta"
            content = "[MEMORY:user is allergic to cats] Got it!"
        proc.on_event(FakeEvent())
        class EndEvent:
            event_type = "chat.end"
            response_id = ""
            stats = {}
        proc.on_event(EndEvent())
        result = proc.result()
        assert "user is allergic to cats" in result.memories

    def test_think_tag_stripped(self):
        from engine.agents.stream_processor import StreamProcessor
        proc = StreamProcessor()
        class FakeEvent:
            event_type = "message.delta"
            content = "[THINK:be more playful] Sure, let's go!"
        proc.on_event(FakeEvent())
        class EndEvent:
            event_type = "chat.end"
            response_id = ""
            stats = {}
        proc.on_event(EndEvent())
        result = proc.result()
        assert "be more playful" in result.think_content
        assert "THINK" not in result.clean_text
        assert "Sure, let's go!" in result.clean_text

    def test_all_tags_dict(self):
        from engine.agents.stream_processor import StreamProcessor
        proc = StreamProcessor()
        class FakeEvent:
            event_type = "message.delta"
            content = "[MOOD:happy] [SEND:aria] [EVENT:knock] Hello"
        proc.on_event(FakeEvent())
        class EndEvent:
            event_type = "chat.end"
            response_id = ""
            stats = {}
        proc.on_event(EndEvent())
        result = proc.result()
        assert "mood" in result.all_tags
        assert "send" in result.all_tags
        assert "event" in result.all_tags

    def test_on_tag_callback(self):
        from engine.agents.stream_processor import StreamProcessor
        tags_seen = []
        proc = StreamProcessor(on_tag=lambda name, val: tags_seen.append((name, val)))
        class FakeEvent:
            event_type = "message.delta"
            content = "[SEND:lola] [EVENT:alert]"
        proc.on_event(FakeEvent())
        assert ("send", "lola") in tags_seen
        assert ("event", "alert") in tags_seen


# ── Integration: StreamWatcher with registry ────────────────────────────

class TestStreamWatcherRegistry:
    """Test that StreamWatcher detect_tags uses registry for routing tags."""

    def test_detect_routing_tags(self):
        from engine.pipeline.stream_watcher import detect_tags
        result = detect_tags("[SEND:aria] [EVENT:alarm] [MEMORY:note]")
        assert "send" in result
        assert "event" in result
        assert "memory" in result

    def test_detect_original_tags(self):
        from engine.pipeline.stream_watcher import detect_tags
        result = detect_tags("[MOOD:happy] [IMAGE:selfie]")
        assert "mood" in result
        assert "image" in result

    def test_detect_think(self):
        from engine.pipeline.stream_watcher import detect_tags
        result = detect_tags("[THINK:reasoning here]")
        assert "think" in result


# ── Integration: TokenRouter with registry ──────────────────────────────

class TestTokenRouterRegistry:
    """Test that TokenRouter reads intents from TagRegistry."""

    def test_tag_detected_routing(self):
        from engine.pipeline.token_router import TokenAheadRouter
        calls = []
        def fake_executor(tool_name, context):
            calls.append((tool_name, context))
            return "ok"

        router = TokenAheadRouter(tool_executor=fake_executor)
        # send tag should map to send_message intent → send_agent_message tool
        result = router.on_tag_detected("send", "lola")
        assert result == "send_agent_message"
        assert len(calls) == 1
        assert calls[0][0] == "send_agent_message"

    def test_tag_detected_original(self):
        from engine.pipeline.token_router import TokenAheadRouter
        calls = []
        def fake_executor(tool_name, context):
            calls.append(tool_name)
            return "ok"

        router = TokenAheadRouter(tool_executor=fake_executor)
        result = router.on_tag_detected("image", "a selfie")
        assert result == "generate_image_request"
