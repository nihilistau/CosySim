"""
ContentRouter v3.1 — Unified content pipeline for all LLM response types.

Provides robust JSON extraction (brace-counting parser that handles nested
objects, markdown fences, and text wrappers), inline tag extraction, and
content classification for routing to downstream handlers.

**v3.1** adds ``ParsedResponse`` and ``ContentRouter.parse_full()`` — a single
parse pass that extracts all structured data from LLM output.  All downstream
code (interceptors, stream processor, agent loop) should read from this object
instead of running independent regex scans.

Usage::

    from engine.agents.content_router import ContentRouter, extract_json

    # Robust JSON extraction from LLM text
    obj = extract_json(llm_text)
    if obj:
        print(obj["action"])

    # Full content classification
    result = ContentRouter.classify(llm_text)
    print(result.content_type)  # "json", "tagged_text", "plain_text"
    print(result.json_data)     # parsed dict or None
    print(result.tags)          # {"MOOD": ["happy"], "IMAGE": [...]}
    print(result.clean_text)    # text with JSON/tags stripped

    # One-pass parsed response (v3.1)
    parsed = ContentRouter.parse_full(llm_text)
    print(parsed.content)         # clean dialog text
    print(parsed.mood)            # "happy" or None
    print(parsed.image_requests)  # ["sunset over ocean"]
    print(parsed.json_data)       # parsed dict or None

    # Agent decision parsing (replaces _parse_decision)
    decision = ContentRouter.parse_decision(llm_text, valid_actions)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Patterns ────────────────────────────────────────────────────────────

_RE_MARKDOWN_FENCE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL | re.IGNORECASE,
)

_RE_INLINE_TAG = re.compile(
    r"\[([A-Z_]+):([^\]]+)\]",
    re.IGNORECASE,
)

_RE_TOKEN_ARTIFACTS = re.compile(
    r"<\|(?:begin_of_text|end_of_text|eot_id|start_header_id|end_header_id|"
    r"im_start|im_end|pad|unk|endoftext|system|user|assistant)\|>",
    re.IGNORECASE,
)


# ── Robust JSON extraction ──────────────────────────────────────────────

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first valid JSON object from LLM output.

    Handles:
    - Bare JSON: ``{"action": "speak"}``
    - Markdown fenced: ``\\`\\`\\`json\\n{...}\\`\\`\\`
    - Text-wrapped: ``Here is my decision: {"action": "speak"} Let me explain...``
    - Nested objects: ``{"a": {"b": 1}, "c": [1,2]}``
    - Trailing commas (common LLM error)
    - Multiple JSON objects (returns first valid one)

    Returns None if no valid JSON object found.
    """
    if not text or not isinstance(text, str):
        return None

    text = _RE_TOKEN_ARTIFACTS.sub("", text).strip()

    # Try 1: markdown fence
    fence_match = _RE_MARKDOWN_FENCE.search(text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        result = _try_parse(candidate)
        if result is not None:
            return result

    # Try 2: brace-counting extraction
    result = _extract_by_brace_counting(text)
    if result is not None:
        return result

    # Try 3: the entire text might be JSON
    result = _try_parse(text)
    if result is not None:
        return result

    return None


def _extract_by_brace_counting(text: str) -> Optional[Dict[str, Any]]:
    """Find JSON objects using brace counting (handles nesting)."""
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            in_string = False
            escape = False
            start = i
            for j in range(i, len(text)):
                ch = text[j]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : j + 1]
                        result = _try_parse(candidate)
                        if result is not None:
                            return result
                        break
            i = start + 1
        else:
            i += 1
    return None


def _try_parse(text: str) -> Optional[Dict[str, Any]]:
    """Attempt to parse JSON with error recovery."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Try fixing trailing commas
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    return None


# ── Content classification ──────────────────────────────────────────────

@dataclass
class ClassifiedContent:
    """Result of content classification."""
    content_type: str = "plain_text"  # "json", "tagged_text", "plain_text"
    raw_text: str = ""
    clean_text: str = ""
    json_data: Optional[Dict[str, Any]] = None
    tags: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def has_json(self) -> bool:
        return self.json_data is not None

    @property
    def has_tags(self) -> bool:
        return bool(self.tags)


# ── Parsed Response (v3.1) ──────────────────────────────────────────────

@dataclass
class ParsedResponse:
    """Single-pass extraction of all structured data from LLM output.

    Produced by ``ContentRouter.parse_full()`` — every downstream consumer
    (interceptors, stream processor, agent loop) reads from this instead of
    running independent regex scans.
    """
    content: str = ""
    """Clean dialog text with all tags, JSON, and artifacts stripped."""

    mood: Optional[str] = None
    """Extracted ``[MOOD:xxx]`` value (first occurrence)."""

    mood_intensity: Optional[float] = None
    """Optional intensity from ``[MOOD:happy intensity=0.8]``."""

    actions: List[str] = field(default_factory=list)
    """All ``[ACTION:xxx]`` values."""

    image_requests: List[str] = field(default_factory=list)
    """All ``[IMAGE:prompt]`` values."""

    voice_hints: List[str] = field(default_factory=list)
    """All ``[VOICE:tone]`` values."""

    game_events: List[str] = field(default_factory=list)
    """All ``[GAME_EVENT:xxx]`` or legacy markers like ``[DARE_COMPLETE]``."""

    stat_updates: List[str] = field(default_factory=list)
    """All ``[STAT:key=value]`` values."""

    json_data: Optional[Dict[str, Any]] = None
    """First valid JSON object found in the text."""

    tags: Dict[str, List[str]] = field(default_factory=dict)
    """All ``[TAG:value]`` pairs (superset — includes mood, action, etc.)."""

    raw_text: str = ""
    """Original unmodified text."""

    @property
    def has_images(self) -> bool:
        return bool(self.image_requests)

    @property
    def has_game_events(self) -> bool:
        return bool(self.game_events)

    @property
    def has_actions(self) -> bool:
        return bool(self.actions)


# ── Legacy game-event markers ──────────────────────────────────────────

_RE_LEGACY_GAME_EVENT = re.compile(
    r"\[(DARE_COMPLETE|GAME_WIN|GAME_LOSE|TRUTH_REVEALED|ROUND_END|"
    r"MYSTERY_SOLVED|CHALLENGE_COMPLETE)\]",
    re.IGNORECASE,
)

_RE_MOOD_INTENSITY = re.compile(
    r"\[MOOD:(\w+)(?:\s+intensity=([\d.]+))?\]",
    re.IGNORECASE,
)


class ContentRouter:
    """Unified content pipeline for LLM responses."""

    @staticmethod
    def classify(text: str) -> ClassifiedContent:
        """Classify and parse LLM output into structured content."""
        if not text:
            return ClassifiedContent(raw_text="", clean_text="")

        result = ClassifiedContent(raw_text=text)
        cleaned = _RE_TOKEN_ARTIFACTS.sub("", text).strip()

        # Extract JSON
        result.json_data = extract_json(cleaned)
        if result.json_data:
            result.content_type = "json"

        # Extract inline tags
        for match in _RE_INLINE_TAG.finditer(cleaned):
            tag_name = match.group(1).upper()
            tag_value = match.group(2).strip()
            if tag_name not in result.tags:
                result.tags[tag_name] = []
            result.tags[tag_name].append(tag_value)

        if not result.json_data and result.tags:
            result.content_type = "tagged_text"

        # Build clean text (strip tags and JSON)
        clean = _RE_INLINE_TAG.sub("", cleaned)
        # Remove markdown-fenced JSON blocks
        clean = _RE_MARKDOWN_FENCE.sub("", clean)
        result.clean_text = clean.strip()

        return result

    @staticmethod
    def parse_decision(
        text: str,
        valid_actions: Optional[Set[str]] = None,
        default_action: str = "idle",
    ) -> Dict[str, Any]:
        """Parse an agent decision from LLM text.

        Returns a dict with keys: action, target, message.
        Falls back to default_action if parsing fails.
        """
        if valid_actions is None:
            valid_actions = {
                "speak", "move", "interact", "idle",
                "flirt", "touch", "kiss", "cuddle", "intimate",
            }

        data = extract_json(text)
        if data:
            action = str(data.get("action", default_action)).lower()
            if action not in valid_actions:
                action = default_action
            return {
                "action": action,
                "target": str(data.get("target", "")),
                "message": str(data.get("message", "")),
            }

        logger.debug("Failed to parse decision JSON from: %.100s", text)
        return {"action": default_action, "target": "", "message": ""}

    @staticmethod
    def extract_tags(text: str) -> Dict[str, List[str]]:
        """Extract all inline tags from text."""
        tags: Dict[str, List[str]] = {}
        for match in _RE_INLINE_TAG.finditer(text):
            tag_name = match.group(1).upper()
            tag_value = match.group(2).strip()
            if tag_name not in tags:
                tags[tag_name] = []
            tags[tag_name].append(tag_value)
        return tags

    @staticmethod
    def strip_tags(text: str) -> str:
        """Remove all inline tags from text."""
        return _RE_INLINE_TAG.sub("", text).strip()

    @staticmethod
    def parse_full(text: str) -> ParsedResponse:
        """Single-pass extraction of all structured data from LLM output.

        This is the **canonical** way to process LLM responses in v3.1+.
        All interceptors, stream processors, and agent loops should call
        this once and read the result — never re-scan with custom regex.

        Returns a ``ParsedResponse`` with clean text, mood, actions,
        image requests, voice hints, game events, JSON data, and raw tags.
        """
        if not text:
            return ParsedResponse()

        parsed = ParsedResponse(raw_text=text)
        cleaned = _RE_TOKEN_ARTIFACTS.sub("", text).strip()

        # ── JSON extraction ─────────────────────────────────────────
        parsed.json_data = extract_json(cleaned)

        # ── Tag extraction (single pass) ────────────────────────────
        for match in _RE_INLINE_TAG.finditer(cleaned):
            tag_name = match.group(1).upper()
            tag_value = match.group(2).strip()
            if tag_name not in parsed.tags:
                parsed.tags[tag_name] = []
            parsed.tags[tag_name].append(tag_value)

        # ── Semantic routing from tags ──────────────────────────────
        # Mood (with intensity support)
        mood_match = _RE_MOOD_INTENSITY.search(cleaned)
        if mood_match:
            parsed.mood = mood_match.group(1).lower()
            if mood_match.group(2):
                try:
                    parsed.mood_intensity = float(mood_match.group(2))
                except ValueError:
                    pass
        elif "MOOD" in parsed.tags:
            parsed.mood = parsed.tags["MOOD"][0].lower()

        parsed.actions = parsed.tags.get("ACTION", [])
        parsed.image_requests = parsed.tags.get("IMAGE", [])
        parsed.voice_hints = parsed.tags.get("VOICE", [])
        parsed.stat_updates = parsed.tags.get("STAT", [])
        parsed.game_events = parsed.tags.get("GAME_EVENT", [])

        # ── Legacy game markers (e.g. [DARE_COMPLETE]) ─────────────
        for legacy in _RE_LEGACY_GAME_EVENT.finditer(cleaned):
            event = legacy.group(1).upper()
            if event not in parsed.game_events:
                parsed.game_events.append(event)

        # ── Clean text (strip all tags, JSON, artifacts) ────────────
        clean = _RE_INLINE_TAG.sub("", cleaned)
        clean = _RE_LEGACY_GAME_EVENT.sub("", clean)
        clean = _RE_MARKDOWN_FENCE.sub("", clean)
        parsed.content = clean.strip()

        return parsed
