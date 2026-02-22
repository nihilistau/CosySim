"""Tests for StreamProcessor — real-time SSE stream processing."""

import pytest
from dataclasses import dataclass, field
from typing import Dict, Optional
from engine.agents.stream_processor import (
    StreamProcessor,
    ProcessedResponse,
    ToolCallRecord,
    StatDelta,
    _RE_MOOD,
    _RE_IMAGE,
    _RE_ACTION,
    _RE_STAT,
    _RE_ALL_TAGS,
)


# ── Fake LMSStreamEvent ────────────────────────────────────────────────

@dataclass
class FakeEvent:
    event_type: str = ""
    content: str = ""
    progress: float = 0.0
    model_instance_id: str = ""
    load_time_seconds: float = 0.0
    tool_name: str = ""
    tool_arguments: Optional[Dict] = None
    tool_output: str = ""
    tool_provider: Optional[Dict] = None
    error: Optional[Dict] = None
    stats: Optional[Dict] = None
    result: Optional[Dict] = None
    response_id: str = ""
    is_done: bool = False


# ── Tag regex tests ─────────────────────────────────────────────────────

class TestTagRegex:
    def test_mood_single(self):
        m = _RE_MOOD.search("Hello [MOOD:happy] world")
        assert m and m.group(1) == "happy"

    def test_mood_multi(self):
        m = _RE_MOOD.search("[MOOD:nervous,excited]")
        assert m and m.group(1) == "nervous,excited"

    def test_mood_case_insensitive(self):
        m = _RE_MOOD.search("[mood:Sad]")
        assert m and m.group(1) == "Sad"

    def test_image_tag(self):
        m = _RE_IMAGE.search("[IMAGE:a cute selfie in bedroom]")
        assert m and m.group(1) == "a cute selfie in bedroom"

    def test_selfie_tag(self):
        m = _RE_IMAGE.search("[SELFIE:posing on bed]")
        assert m and m.group(1) == "posing on bed"

    def test_photo_tag(self):
        m = _RE_IMAGE.search("[PHOTO:sunset view]")
        assert m and m.group(1) == "sunset view"

    def test_action_tag(self):
        m = _RE_ACTION.search("[ACTION:sit down on bed]")
        assert m and m.group(1) == "sit down on bed"

    def test_stat_positive(self):
        m = _RE_STAT.search("[STAT:arousal+10]")
        assert m and m.group(1) == "arousal" and m.group(2) == "+10"

    def test_stat_negative(self):
        m = _RE_STAT.search("[STAT:energy-5]")
        assert m and m.group(1) == "energy" and m.group(2) == "-5"

    def test_strip_all_tags(self):
        text = "Hello [MOOD:happy] world [IMAGE:test] bye [ACTION:wave] end"
        clean = _RE_ALL_TAGS.sub("", text).strip()
        assert clean == "Hello world bye end"


# ── StreamProcessor basic tests ─────────────────────────────────────────

class TestStreamProcessorBasic:
    def test_empty_stream(self):
        proc = StreamProcessor()
        result = proc.result()
        assert result.raw_text == ""
        assert result.clean_text == ""
        assert result.mood_tags == []
        assert result.tool_calls == []

    def test_content_accumulation(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="chat.start", model_instance_id="test-model"))
        proc.on_event(FakeEvent(event_type="message.delta", content="Hello "))
        proc.on_event(FakeEvent(event_type="message.delta", content="world!"))
        proc.on_event(FakeEvent(event_type="chat.end", response_id="resp_123", stats={}))
        result = proc.result()
        assert result.raw_text == "Hello world!"
        assert result.clean_text == "Hello world!"
        assert result.response_id == "resp_123"
        assert result.model == "test-model"

    def test_reasoning_accumulation(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="reasoning.delta", content="thinking step 1, "))
        proc.on_event(FakeEvent(event_type="reasoning.delta", content="step 2"))
        result = proc.result()
        assert result.reasoning_content == "thinking step 1, step 2"

    def test_model_load_time(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="model_load.end", load_time_seconds=2.5))
        result = proc.result()
        assert result.model_load_time_s == 2.5


# ── Tag extraction tests ───────────────────────────────────────────────

class TestStreamProcessorTags:
    def test_mood_extraction(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="I'm feeling [MOOD:happy] today"))
        result = proc.result()
        assert result.mood_tags == ["happy"]
        assert "[MOOD:" not in result.clean_text
        assert "today" in result.clean_text

    def test_multi_mood(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="[MOOD:nervous,excited] Oh wow"))
        result = proc.result()
        assert "nervous" in result.mood_tags
        assert "excited" in result.mood_tags

    def test_image_request(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="Here's a selfie [IMAGE:cute pose on bed]"))
        result = proc.result()
        assert result.image_requests == ["cute pose on bed"]
        assert result.has_images

    def test_action_tag(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="[ACTION:pick up phone] Let me check"))
        result = proc.result()
        assert result.action_tags == ["pick up phone"]

    def test_stat_delta(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="Hmm [STAT:arousal+10] interesting"))
        result = proc.result()
        assert len(result.stat_deltas) == 1
        assert result.stat_deltas[0].stat == "arousal"
        assert result.stat_deltas[0].delta == 10

    def test_voice_style(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="[VOICE:whisper] come closer"))
        result = proc.result()
        assert result.voice_style == "whisper"

    def test_multiple_tags_mixed(self):
        proc = StreamProcessor()
        text = "[MOOD:playful] Hey! [IMAGE:winking selfie] [ACTION:wink] Catch this [STAT:trust+5]"
        proc.on_event(FakeEvent(event_type="message.delta", content=text))
        result = proc.result()
        assert result.mood_tags == ["playful"]
        assert result.image_requests == ["winking selfie"]
        assert result.action_tags == ["wink"]
        assert result.stat_deltas[0].stat == "trust"
        assert "Hey!" in result.clean_text
        assert "Catch this" in result.clean_text


# ── Tool call tests ─────────────────────────────────────────────────────

class TestStreamProcessorToolCalls:
    def test_successful_tool_call(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="generate_image_request"))
        proc.on_event(FakeEvent(
            event_type="tool_call.arguments",
            tool_arguments={"prompt": "selfie", "width": 512},
        ))
        proc.on_event(FakeEvent(event_type="tool_call.success", tool_output="path/to/image.png"))
        result = proc.result()
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.name == "generate_image_request"
        assert tc.arguments == {"prompt": "selfie", "width": 512}
        assert tc.output == "path/to/image.png"
        assert tc.success is True
        assert result.has_tool_calls

    def test_failed_tool_call(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="search_memory"))
        proc.on_event(FakeEvent(event_type="tool_call.failure", tool_output="RAG unavailable"))
        result = proc.result()
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].success is False
        assert result.tool_calls[0].output == "RAG unavailable"

    def test_multiple_tool_calls(self):
        proc = StreamProcessor()
        # First tool
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="search_memory"))
        proc.on_event(FakeEvent(event_type="tool_call.success", tool_output="found memory"))
        # Second tool
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="generate_image_request"))
        proc.on_event(FakeEvent(event_type="tool_call.success", tool_output="image.png"))
        result = proc.result()
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "search_memory"
        assert result.tool_calls[1].name == "generate_image_request"


# ── Callbacks tests ─────────────────────────────────────────────────────

class TestStreamProcessorCallbacks:
    def test_on_delta_callback(self):
        chunks = []
        proc = StreamProcessor(on_delta=lambda t: chunks.append(t))
        proc.on_event(FakeEvent(event_type="message.delta", content="Hello "))
        proc.on_event(FakeEvent(event_type="message.delta", content="world"))
        assert chunks == ["Hello ", "world"]

    def test_on_mood_callback(self):
        moods = []
        proc = StreamProcessor(on_mood=lambda m: moods.append(m))
        proc.on_event(FakeEvent(event_type="message.delta", content="[MOOD:happy] hey"))
        assert moods == ["happy"]

    def test_on_image_request_callback(self):
        images = []
        proc = StreamProcessor(on_image_request=lambda p: images.append(p))
        proc.on_event(FakeEvent(event_type="message.delta", content="[IMAGE:bedroom selfie]"))
        assert images == ["bedroom selfie"]

    def test_on_tool_call_callback(self):
        calls = []
        proc = StreamProcessor(on_tool_call=lambda tc: calls.append(tc))
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="test"))
        proc.on_event(FakeEvent(event_type="tool_call.success", tool_output="done"))
        assert len(calls) == 1
        assert calls[0].name == "test"

    def test_on_action_callback(self):
        actions = []
        proc = StreamProcessor(on_action=lambda a: actions.append(a))
        proc.on_event(FakeEvent(event_type="message.delta", content="[ACTION:sit down]"))
        assert actions == ["sit down"]

    def test_on_stat_delta_callback(self):
        deltas = []
        proc = StreamProcessor(on_stat_delta=lambda d: deltas.append(d))
        proc.on_event(FakeEvent(event_type="message.delta", content="[STAT:trust+5]"))
        assert len(deltas) == 1
        assert deltas[0].stat == "trust"
        assert deltas[0].delta == 5


# ── Stats extraction tests ──────────────────────────────────────────────

class TestStreamProcessorStats:
    def test_stats_from_chat_end(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="chat.start"))
        proc.on_event(FakeEvent(event_type="message.delta", content="Hi"))
        proc.on_event(FakeEvent(
            event_type="chat.end",
            response_id="resp_abc123",
            stats={
                "tokens_per_second": 42.5,
                "time_to_first_token_seconds": 0.15,
                "input_tokens": 100,
                "output_tokens": 50,
                "reasoning_tokens": 20,
            },
        ))
        result = proc.result()
        assert result.response_id == "resp_abc123"
        assert result.server_tps == 42.5
        assert result.time_to_first_token_s == 0.15
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.reasoning_tokens == 20
        assert result.is_stateful

    def test_event_count(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="chat.start"))
        proc.on_event(FakeEvent(event_type="message.delta", content="Hi"))
        proc.on_event(FakeEvent(event_type="chat.end"))
        result = proc.result()
        assert result.event_count == 3

    def test_latency_calculated(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="chat.start"))
        proc.on_event(FakeEvent(event_type="message.delta", content="Hi"))
        proc.on_event(FakeEvent(event_type="chat.end"))
        result = proc.result()
        assert result.latency_ms > 0


# ── ProcessedResponse properties ────────────────────────────────────────

class TestProcessedResponse:
    def test_is_stateful_true(self):
        r = ProcessedResponse(response_id="resp_123")
        assert r.is_stateful is True

    def test_is_stateful_false(self):
        r = ProcessedResponse(response_id="other_123")
        assert r.is_stateful is False

    def test_is_stateful_empty(self):
        r = ProcessedResponse()
        assert r.is_stateful is False

    def test_primary_mood(self):
        r = ProcessedResponse(mood_tags=["nervous", "excited"])
        assert r.primary_mood == "nervous"

    def test_primary_mood_empty(self):
        r = ProcessedResponse()
        assert r.primary_mood == ""

    def test_has_images(self):
        r = ProcessedResponse(image_requests=["test"])
        assert r.has_images is True

    def test_has_no_images(self):
        r = ProcessedResponse()
        assert r.has_images is False


# ── Reset test ──────────────────────────────────────────────────────────

class TestStreamProcessorReset:
    def test_reset_clears_state(self):
        proc = StreamProcessor()
        proc.on_event(FakeEvent(event_type="message.delta", content="Hello [MOOD:happy]"))
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="test"))
        proc.on_event(FakeEvent(event_type="tool_call.success", tool_output="done"))
        proc.on_event(FakeEvent(event_type="chat.end", response_id="resp_1"))

        result1 = proc.result()
        assert result1.raw_text == "Hello [MOOD:happy]"
        assert len(result1.tool_calls) == 1

        proc.reset()
        result2 = proc.result()
        assert result2.raw_text == ""
        assert result2.tool_calls == []
        assert result2.response_id == ""


# ── Full stream simulation ──────────────────────────────────────────────

class TestFullStreamSimulation:
    def test_realistic_chat_stream(self):
        """Simulate a realistic chat stream with reasoning, tool call, and content."""
        proc = StreamProcessor()

        # Chat starts
        proc.on_event(FakeEvent(event_type="chat.start", model_instance_id="qwen3-4b"))

        # Model thinks
        proc.on_event(FakeEvent(event_type="reasoning.start"))
        proc.on_event(FakeEvent(event_type="reasoning.delta", content="User wants a selfie. "))
        proc.on_event(FakeEvent(event_type="reasoning.delta", content="I should use generate_image."))
        proc.on_event(FakeEvent(event_type="reasoning.end"))

        # Tool call
        proc.on_event(FakeEvent(event_type="tool_call.start", tool_name="generate_image_request"))
        proc.on_event(FakeEvent(
            event_type="tool_call.arguments",
            tool_arguments={"prompt": "selfie in bedroom, cute pose", "width": 512, "height": 768},
        ))
        proc.on_event(FakeEvent(
            event_type="tool_call.success",
            tool_output="Image generated: content/simulation/media/images/selfie_001.png",
        ))

        # Content with inline tags
        proc.on_event(FakeEvent(event_type="message.start"))
        proc.on_event(FakeEvent(event_type="message.delta", content="[MOOD:playful] "))
        proc.on_event(FakeEvent(event_type="message.delta", content="Here's that selfie you wanted! "))
        proc.on_event(FakeEvent(event_type="message.delta", content="[ACTION:pose for camera] "))
        proc.on_event(FakeEvent(event_type="message.delta", content="Do you like it? 😘"))
        proc.on_event(FakeEvent(event_type="message.end"))

        # Chat ends
        proc.on_event(FakeEvent(
            event_type="chat.end",
            response_id="resp_selfie_001",
            stats={
                "tokens_per_second": 38.2,
                "time_to_first_token_seconds": 0.23,
                "input_tokens": 450,
                "output_tokens": 85,
                "reasoning_tokens": 30,
            },
        ))

        result = proc.result()

        # Content
        assert "Here's that selfie you wanted!" in result.clean_text
        assert "Do you like it?" in result.clean_text
        assert "[MOOD:" not in result.clean_text
        assert "[ACTION:" not in result.clean_text

        # Tags
        assert result.mood_tags == ["playful"]
        assert result.action_tags == ["pose for camera"]

        # Reasoning
        assert "User wants a selfie" in result.reasoning_content

        # Tool call
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "generate_image_request"
        assert "selfie_001.png" in result.tool_calls[0].output

        # Stats
        assert result.response_id == "resp_selfie_001"
        assert result.model == "qwen3-4b"
        assert result.server_tps == 38.2
        assert result.is_stateful
        assert result.event_count == 15
