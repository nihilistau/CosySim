"""
StreamProcessor v2.7 — Real-time processing of LMStudio v1 SSE event streams.

Consumes ``LMSStreamEvent`` objects from ``LMSClient.chat_stream()`` or
``chat_stream_stateful()`` and produces a rich ``ProcessedResponse`` with:

- Accumulated content text (message deltas)
- Extracted inline tags: ``[MOOD:happy]``, ``[IMAGE:prompt]``, ``[ACTION:sit]``
- Reasoning content (thinking/chain-of-thought)
- Tool call tracking (name, args, result, success/failure)
- Stats from chat.end (TPS, TTFT, token counts)
- Streaming callbacks for real-time UI updates

Usage::

    from engine.agents.stream_processor import StreamProcessor

    proc = StreamProcessor(on_delta=lambda text: print(text, end=""))

    # Feed events from infer_stream
    for chunk in mgr.infer_stream(request, on_event=proc.on_event):
        proc.feed_content(chunk)

    result = proc.result()
    print(result.clean_text)          # text with tags stripped
    print(result.mood_tags)           # ["happy"]
    print(result.image_requests)      # ["a selfie in the penthouse"]
    print(result.tool_calls)          # [{name, args, output, success}]

Or use the shortcut::

    result = StreamProcessor.process_generator(
        mgr.infer_stream(request, on_event=proc.on_event)
    )
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

# ── Inline tag patterns ─────────────────────────────────────────────────
# These fast regexes handle the original 5 tag types directly.
# The TagRegistry is used for new routing tags and for the strip pattern.

# [MOOD:happy]  [MOOD:nervous,excited]
_RE_MOOD = re.compile(r"\[MOOD:([^\]]+)\]", re.IGNORECASE)
# [IMAGE:a selfie in the penthouse]  [SELFIE:cute pose]
_RE_IMAGE = re.compile(r"\[(?:IMAGE|SELFIE|PHOTO):([^\]]+)\]", re.IGNORECASE)
# [ACTION:sit down]  [ACTION:pick up phone]
_RE_ACTION = re.compile(r"\[ACTION:([^\]]+)\]", re.IGNORECASE)
# [STAT:arousal+10]  [STAT:energy-5]
_RE_STAT = re.compile(r"\[STAT:(\w+)([+-]\d+)\]", re.IGNORECASE)
# [VOICE:whisper]  [VOICE:playful]
_RE_VOICE = re.compile(r"\[VOICE:([^\]]+)\]", re.IGNORECASE)

# ── Tag Registry integration ────────────────────────────────────────────
# Strip pattern comes from the registry so new tags are auto-stripped.

def _get_strip_pattern() -> re.Pattern:
    """Get the tag strip pattern from TagRegistry (covers all registered tags)."""
    try:
        from engine.mcp.tag_registry import TagRegistry
        return TagRegistry.get().get_strip_pattern()
    except Exception:
        # Fallback to hardcoded pattern if registry unavailable
        return re.compile(
            r"\[(?:MOOD|IMAGE|SELFIE|PHOTO|ACTION|STAT|VOICE):[^\]]+\]\s*",
            re.IGNORECASE,
        )

# LLM special token artifacts that leak into output
_RE_TOKEN_ARTIFACTS = re.compile(
    r"<\|(?:begin_of_text|end_of_text|eot_id|start_header_id|end_header_id|"
    r"im_start|im_end|pad|unk|endoftext|system|user|assistant)\|>",
    re.IGNORECASE,
)


def strip_token_artifacts(text: str) -> str:
    """Remove LLM special token artifacts that leak into output."""
    if not text:
        return text
    return _RE_TOKEN_ARTIFACTS.sub("", text).strip()


# ── Data classes ────────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    """A tool call observed during streaming."""
    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    output: str = ""
    success: bool = True
    provider: Optional[Dict] = None


@dataclass
class StatDelta:
    """A stat adjustment parsed from [STAT:name±value]."""
    stat: str = ""
    delta: int = 0


@dataclass
class ProcessedResponse:
    """Rich result from processing a stream of LMSStreamEvents."""

    # Raw accumulated text (includes tags)
    raw_text: str = ""
    # Text with inline tags stripped
    clean_text: str = ""
    # Reasoning/thinking content
    reasoning_content: str = ""

    # Extracted inline tags
    mood_tags: List[str] = field(default_factory=list)
    image_requests: List[str] = field(default_factory=list)
    action_tags: List[str] = field(default_factory=list)
    stat_deltas: List[StatDelta] = field(default_factory=list)
    voice_style: str = ""

    # Routing tags (v4.1)
    send_targets: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    memories: List[str] = field(default_factory=list)
    think_content: List[str] = field(default_factory=list)
    # Generic: all tags detected (name → values)
    all_tags: Dict[str, List[str]] = field(default_factory=dict)

    # Tool calls (from tool_call.* events)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)

    # Stats from chat.end
    response_id: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    server_tps: float = 0.0
    time_to_first_token_s: float = 0.0
    model_load_time_s: float = 0.0
    latency_ms: float = 0.0

    # Processing metadata
    event_count: int = 0
    stream_started: float = 0.0
    stream_ended: float = 0.0

    @property
    def has_images(self) -> bool:
        return bool(self.image_requests)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def has_mood(self) -> bool:
        return bool(self.mood_tags)

    @property
    def primary_mood(self) -> str:
        return self.mood_tags[0] if self.mood_tags else ""

    @property
    def is_stateful(self) -> bool:
        return bool(self.response_id and self.response_id.startswith("resp_"))


# ── StreamProcessor ─────────────────────────────────────────────────────

class StreamProcessor:
    """
    Consumes LMSStreamEvent objects and content chunks from the v2.7
    streaming pipeline, producing a rich ProcessedResponse.

    Two input channels:
    1. ``on_event(event)`` — receives typed LMSStreamEvent (set as on_event callback)
    2. ``feed_content(chunk)`` — receives yielded content strings

    Callbacks for real-time reactions:
    - ``on_delta`` — called with each content delta (for UI streaming)
    - ``on_tool_call`` — called when a tool call completes
    - ``on_mood`` — called when a mood tag is detected
    - ``on_image_request`` — called when an image request tag is detected
    """

    def __init__(
        self,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[ToolCallRecord], None]] = None,
        on_mood: Optional[Callable[[str], None]] = None,
        on_image_request: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_stat_delta: Optional[Callable[[StatDelta], None]] = None,
        on_tag: Optional[Callable[[str, str], None]] = None,
    ):
        self._on_delta = on_delta
        self._on_tool_call = on_tool_call
        self._on_mood = on_mood
        self._on_image_request = on_image_request
        self._on_action = on_action
        self._on_stat_delta = on_stat_delta
        self._on_tag = on_tag  # Generic: (tag_name, value) for any tag

        # Accumulation buffers
        self._content_parts: List[str] = []
        self._reasoning_parts: List[str] = []
        self._tool_calls: List[ToolCallRecord] = []
        self._current_tool: Optional[ToolCallRecord] = None

        # Tag accumulation (v3.1 — single pass, no re-scan in result())
        self._mood_tags: List[str] = []
        self._image_requests: List[str] = []
        self._action_tags: List[str] = []
        self._stat_deltas: List[StatDelta] = []
        self._voice_styles: List[str] = []

        # Routing tags (v4.1)
        self._send_targets: List[str] = []
        self._events: List[str] = []
        self._memories: List[str] = []
        self._think_content: List[str] = []
        self._all_tags: Dict[str, List[str]] = {}
        self._image_requests: List[str] = []
        self._action_tags: List[str] = []
        self._stat_deltas: List[StatDelta] = []
        self._voice_styles: List[str] = []

        # Stats captured from events
        self._response_id: str = ""
        self._model: str = ""
        self._stats: Dict[str, Any] = {}
        self._model_load_time: float = 0.0
        self._event_count: int = 0
        self._t_start: float = 0.0
        self._t_first_token: float = 0.0
        self._t_end: float = 0.0
        self._done: bool = False

    # ── Event callback (set as on_event in stream calls) ────────────

    def on_event(self, event: Any) -> None:
        """
        Process a single LMSStreamEvent. Set this as the ``on_event``
        callback in ``LMSClient.chat_stream()`` or ``infer_stream()``.
        """
        self._event_count += 1
        etype = getattr(event, "event_type", "")

        if not self._t_start:
            self._t_start = time.perf_counter()

        # ── Chat lifecycle ──────────────────────────────────────────
        if etype == "chat.start":
            self._model = getattr(event, "model_instance_id", "") or self._model

        elif etype == "chat.end":
            self._t_end = time.perf_counter()
            self._done = True
            self._response_id = getattr(event, "response_id", "") or ""
            stats = getattr(event, "stats", None) or {}
            self._stats = stats

        # ── Model loading ───────────────────────────────────────────
        elif etype == "model_load.end":
            self._model_load_time = getattr(event, "load_time_seconds", 0.0)

        # ── Reasoning ───────────────────────────────────────────────
        elif etype == "reasoning.delta":
            content = getattr(event, "content", "")
            if content:
                self._reasoning_parts.append(content)

        # ── Message content ─────────────────────────────────────────
        elif etype == "message.delta":
            content = getattr(event, "content", "")
            if content:
                self._content_parts.append(content)
                self._scan_for_tags(content)
                if not self._t_first_token:
                    self._t_first_token = time.perf_counter()
                if self._on_delta:
                    self._on_delta(content)

        # ── Tool calls ──────────────────────────────────────────────
        elif etype == "tool_call.start":
            self._current_tool = ToolCallRecord(
                name=getattr(event, "tool_name", ""),
                provider=getattr(event, "tool_provider", None),
            )

        elif etype == "tool_call.arguments":
            if self._current_tool:
                args = getattr(event, "tool_arguments", None) or {}
                self._current_tool.arguments = args

        elif etype == "tool_call.success":
            if self._current_tool:
                self._current_tool.output = getattr(event, "tool_output", "")
                self._current_tool.success = True
                self._tool_calls.append(self._current_tool)
                if self._on_tool_call:
                    self._on_tool_call(self._current_tool)
                self._current_tool = None

        elif etype == "tool_call.failure":
            if self._current_tool:
                self._current_tool.output = getattr(event, "tool_output", "")
                self._current_tool.success = False
                self._tool_calls.append(self._current_tool)
                if self._on_tool_call:
                    self._on_tool_call(self._current_tool)
                self._current_tool = None

        # ── Error ───────────────────────────────────────────────────
        elif etype == "error":
            err = getattr(event, "error", None)
            logger.error("Stream error event: %s", err)

    # ── Content feed (from yielded chunks) ──────────────────────────

    def feed_content(self, chunk: str) -> None:
        """Feed a content chunk yielded by the stream generator."""
        # Content is already tracked via on_event(message.delta),
        # but if chunks come from the generator yield they may be
        # redundant. Only add if on_event isn't being used.
        pass  # on_event handles accumulation; this is a no-op hook

    # ── Tag scanning ────────────────────────────────────────────────

    def _scan_for_tags(self, text: str) -> None:
        """Scan a content delta for inline tags, accumulate and fire callbacks."""
        for match in _RE_MOOD.finditer(text):
            moods = [m.strip() for m in match.group(1).split(",")]
            for mood in moods:
                self._mood_tags.append(mood)
                if self._on_mood:
                    self._on_mood(mood)

        for match in _RE_IMAGE.finditer(text):
            prompt = match.group(1).strip()
            self._image_requests.append(prompt)
            if self._on_image_request:
                self._on_image_request(prompt)

        for match in _RE_ACTION.finditer(text):
            action = match.group(1).strip()
            self._action_tags.append(action)
            if self._on_action:
                self._on_action(action)

        for match in _RE_STAT.finditer(text):
            stat = match.group(1)
            delta = int(match.group(2))
            sd = StatDelta(stat=stat, delta=delta)
            self._stat_deltas.append(sd)
            if self._on_stat_delta:
                self._on_stat_delta(sd)

        for match in _RE_VOICE.finditer(text):
            self._voice_styles.append(match.group(1).strip())

        # ── Routing tags via TagRegistry (v4.1) ─────────────────────
        self._scan_routing_tags(text)

    # Routing tag patterns (compiled once)
    _RE_SEND = re.compile(r"\[SEND:([^\]]+)\]", re.IGNORECASE)
    _RE_EVENT = re.compile(r"\[EVENT:([^\]]+)\]", re.IGNORECASE)
    _RE_MEMORY = re.compile(r"\[MEMORY:([^\]]+)\]", re.IGNORECASE)
    _RE_THINK = re.compile(r"\[THINK:([^\]]+)\]", re.IGNORECASE)

    def _scan_routing_tags(self, text: str) -> None:
        """Scan for v4.1 routing tags."""
        for match in self._RE_SEND.finditer(text):
            val = match.group(1).strip()
            self._send_targets.append(val)
            self._all_tags.setdefault("send", []).append(val)
            if self._on_tag:
                self._on_tag("send", val)

        for match in self._RE_EVENT.finditer(text):
            val = match.group(1).strip()
            self._events.append(val)
            self._all_tags.setdefault("event", []).append(val)
            if self._on_tag:
                self._on_tag("event", val)

        for match in self._RE_MEMORY.finditer(text):
            val = match.group(1).strip()
            self._memories.append(val)
            self._all_tags.setdefault("memory", []).append(val)
            if self._on_tag:
                self._on_tag("memory", val)

        for match in self._RE_THINK.finditer(text):
            val = match.group(1).strip()
            self._think_content.append(val)
            self._all_tags.setdefault("think", []).append(val)
            # No callback for think — internal only

        # Also track original tags in all_tags
        if _RE_MOOD.search(text):
            for m in _RE_MOOD.finditer(text):
                self._all_tags.setdefault("mood", []).append(m.group(1).strip())
        if _RE_IMAGE.search(text):
            for m in _RE_IMAGE.finditer(text):
                self._all_tags.setdefault("image", []).append(m.group(1).strip())
        if _RE_ACTION.search(text):
            for m in _RE_ACTION.finditer(text):
                self._all_tags.setdefault("action", []).append(m.group(1).strip())
        if _RE_STAT.search(text):
            for m in _RE_STAT.finditer(text):
                self._all_tags.setdefault("stat", []).append(f"{m.group(1)}{m.group(2)}")
        if _RE_VOICE.search(text):
            for m in _RE_VOICE.finditer(text):
                self._all_tags.setdefault("voice", []).append(m.group(1).strip())

    # ── Result assembly ─────────────────────────────────────────────

    def result(self) -> ProcessedResponse:
        """
        Assemble the final ProcessedResponse from all accumulated data.

        v3.1: Tags are accumulated during streaming — no re-scan needed.
        Call this after the stream completes (after iterating the generator).
        """
        raw_text = "".join(self._content_parts)
        reasoning = "".join(self._reasoning_parts)

        # Use pre-accumulated tags (no re-scan)
        voice_style = self._voice_styles[-1] if self._voice_styles else ""

        # Strip tags to produce clean text (uses TagRegistry for full coverage)
        strip_re = _get_strip_pattern()
        clean_text = strip_re.sub("", raw_text).strip()
        # Strip leaked LLM token artifacts
        clean_text = strip_token_artifacts(clean_text)
        raw_text = strip_token_artifacts(raw_text)

        # Extract stats from chat.end
        stats = self._stats
        tps = stats.get("tokens_per_second", 0.0)
        ttft = stats.get("time_to_first_token_seconds", 0.0)
        input_tokens = stats.get("input_tokens", 0) or stats.get("prompt_tokens", 0)
        output_tokens = stats.get("output_tokens", 0) or stats.get("completion_tokens", 0)
        reasoning_tokens = stats.get("reasoning_tokens", 0)

        if not self._t_end:
            self._t_end = time.perf_counter()
        latency_ms = (self._t_end - self._t_start) * 1000 if self._t_start else 0.0

        return ProcessedResponse(
            raw_text=raw_text,
            clean_text=clean_text,
            reasoning_content=reasoning,
            mood_tags=list(self._mood_tags),
            image_requests=list(self._image_requests),
            action_tags=list(self._action_tags),
            stat_deltas=list(self._stat_deltas),
            voice_style=voice_style,
            send_targets=list(self._send_targets),
            events=list(self._events),
            memories=list(self._memories),
            think_content=list(self._think_content),
            all_tags=dict(self._all_tags),
            tool_calls=list(self._tool_calls),
            response_id=self._response_id,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            server_tps=tps,
            time_to_first_token_s=ttft,
            model_load_time_s=self._model_load_time,
            latency_ms=latency_ms,
            event_count=self._event_count,
            stream_started=self._t_start,
            stream_ended=self._t_end,
        )

    # ── Convenience: process a full generator ───────────────────────

    @staticmethod
    def process_generator(
        gen: Generator[str, None, Any],
        *,
        on_event: Optional[Callable] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[ToolCallRecord], None]] = None,
        on_mood: Optional[Callable[[str], None]] = None,
        on_image_request: Optional[Callable[[str], None]] = None,
    ) -> ProcessedResponse:
        """
        Process an entire stream generator and return a ProcessedResponse.

        If the generator was started with ``on_event`` pointing to the
        processor's ``on_event``, this just drains the content chunks.
        Otherwise, it creates its own processor.

        Usage::

            proc = StreamProcessor(on_delta=lambda t: print(t, end=""))
            result = StreamProcessor.process_generator(
                client.chat_stream(messages, on_event=proc.on_event),
                on_delta=lambda t: print(t, end=""),
            )
        """
        proc = StreamProcessor(
            on_delta=on_delta,
            on_tool_call=on_tool_call,
            on_mood=on_mood,
            on_image_request=on_image_request,
        )

        # If an external on_event is provided, the caller has already
        # wired events to a different handler — we just drain content.
        # Otherwise we create our own and expect the generator wasn't
        # given an on_event (the content chunks still come through).
        for chunk in gen:
            pass  # Events handled via on_event callback

        return proc.result()

    def reset(self) -> None:
        """Reset the processor for reuse with a new stream."""
        self._content_parts.clear()
        self._reasoning_parts.clear()
        self._tool_calls.clear()
        self._current_tool = None
        self._response_id = ""
        self._model = ""
        self._stats = {}
        self._model_load_time = 0.0
        self._event_count = 0
        self._t_start = 0.0
        self._t_first_token = 0.0
        self._t_end = 0.0
        self._done = False
