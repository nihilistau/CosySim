"""
TagRegistry — Extensible inline tag system for CosySim.

Central registry for all ``[TAG:value]`` patterns used in LLM output.
Instead of hardcoding tag patterns in StreamProcessor, StreamWatcher, and
TokenRouter, all three consume this single registry.

Built-in tags (always registered)::

    [MOOD:happy]             → mood sync, TTS emotion
    [IMAGE:prompt]           → image generation pre-warm
    [SELFIE:prompt]          → alias for IMAGE
    [PHOTO:prompt]           → alias for IMAGE
    [ACTION:sit down]        → scene animation / state change
    [STAT:arousal+10]        → character stat delta
    [VOICE:whisper]          → TTS style override

Routing tags (new in v4.1)::

    [SEND:character_name]    → route message to another agent
    [EVENT:event_name]       → fire event on ActivityBus
    [MEMORY:important fact]  → store in long-term memory
    [THINK:internal reason]  → hidden reasoning (stripped, never shown)

Scenes can register custom tags at startup::

    from engine.mcp.tag_registry import TagRegistry

    registry = TagRegistry.get()
    registry.register(TagDef(
        name="plan",
        pattern=r"\\[PLAN:([^\\]]+)\\]",
        handler=my_plan_handler,
        pre_warm_intent="planning",
    ))
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Tag definition ──────────────────────────────────────────────────────

@dataclass
class TagDef:
    """Definition of a single inline tag type."""

    # Unique tag name (lowercase), e.g. "mood", "image", "send"
    name: str

    # Regex with one capture group for the value.
    # Example: r"\[MOOD:([^\]]+)\]"
    pattern: str

    # Optional handler called when tag is detected.
    # Signature: handler(tag_name: str, value: str, context: dict) -> Any
    handler: Optional[Callable[..., Any]] = None

    # Whether to strip this tag from user-visible output
    strip_from_output: bool = True

    # If set, the TokenAheadRouter will pre-warm this intent when the tag
    # is detected during streaming (e.g. "image_generation").
    pre_warm_intent: str = ""

    # Compiled regex (set by registry on register)
    _compiled: Optional[re.Pattern] = field(default=None, repr=False)

    # Tag aliases grouped under this name (e.g. IMAGE covers SELFIE, PHOTO).
    # The pattern should already use alternation; this is for documentation.
    aliases: List[str] = field(default_factory=list)


@dataclass
class TagMatch:
    """A single tag match found in text."""
    tag_name: str
    value: str
    start: int
    end: int


# ── TagRegistry singleton ──────────────────────────────────────────────

class TagRegistry:
    """
    Central registry for all inline tags.

    Singleton — access via ``TagRegistry.get()``.
    Thread-safe for registration and detection.
    """

    _instance: Optional[TagRegistry] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> TagRegistry:
        """Get or create the global TagRegistry instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def __init__(self) -> None:
        self._tags: Dict[str, TagDef] = {}
        self._strip_pattern: Optional[re.Pattern] = None
        self._strip_dirty = True
        self._rw_lock = threading.Lock()

        # Register built-in tags
        self._register_builtins()

    # ── Registration ────────────────────────────────────────────────

    def register(self, tag_def: TagDef) -> None:
        """
        Register a tag definition.

        If a tag with the same name already exists, it is replaced.
        """
        with self._rw_lock:
            tag_def._compiled = re.compile(tag_def.pattern, re.IGNORECASE)
            self._tags[tag_def.name] = tag_def
            self._strip_dirty = True
            logger.debug("Tag registered: %s", tag_def.name)

    def unregister(self, name: str) -> None:
        """Remove a tag definition."""
        with self._rw_lock:
            self._tags.pop(name, None)
            self._strip_dirty = True

    def get_tag(self, name: str) -> Optional[TagDef]:
        """Get a tag definition by name."""
        return self._tags.get(name)

    @property
    def tag_names(self) -> List[str]:
        """All registered tag names."""
        return list(self._tags.keys())

    @property
    def tag_count(self) -> int:
        return len(self._tags)

    # ── Detection ───────────────────────────────────────────────────

    def detect_all(self, text: str) -> Dict[str, List[TagMatch]]:
        """
        Detect all registered tags in text.

        Returns dict of tag_name → list of TagMatch.
        """
        results: Dict[str, List[TagMatch]] = {}
        with self._rw_lock:
            tags = dict(self._tags)

        for name, tdef in tags.items():
            compiled = tdef._compiled
            if not compiled:
                continue
            for m in compiled.finditer(text):
                match = TagMatch(
                    tag_name=name,
                    value=m.group(1).strip() if m.lastindex and m.lastindex >= 1 else m.group(0),
                    start=m.start(),
                    end=m.end(),
                )
                results.setdefault(name, []).append(match)
        return results

    def detect_tag(self, name: str, text: str) -> List[TagMatch]:
        """Detect a single tag type in text."""
        tdef = self._tags.get(name)
        if not tdef or not tdef._compiled:
            return []
        matches = []
        for m in tdef._compiled.finditer(text):
            matches.append(TagMatch(
                tag_name=name,
                value=m.group(1).strip() if m.lastindex and m.lastindex >= 1 else m.group(0),
                start=m.start(),
                end=m.end(),
            ))
        return matches

    # ── Stripping ───────────────────────────────────────────────────

    def get_strip_pattern(self) -> re.Pattern:
        """
        Get a compiled regex that matches ALL strippable tags.

        Cached and rebuilt when tags change.
        """
        if not self._strip_dirty and self._strip_pattern is not None:
            return self._strip_pattern

        with self._rw_lock:
            strippable = [
                tdef.pattern for tdef in self._tags.values()
                if tdef.strip_from_output
            ]
            if strippable:
                combined = "|".join(f"(?:{p})" for p in strippable)
                # Add trailing whitespace consumption
                self._strip_pattern = re.compile(
                    f"(?:{combined})\\s*", re.IGNORECASE
                )
            else:
                self._strip_pattern = re.compile(r"(?!)")  # never matches
            self._strip_dirty = False

        return self._strip_pattern

    def strip_tags(self, text: str) -> str:
        """Remove all strippable tags from text."""
        return self.get_strip_pattern().sub("", text).strip()

    # ── Handler dispatch ────────────────────────────────────────────

    def dispatch(
        self,
        tag_name: str,
        value: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Call the handler for a detected tag.

        Returns handler result, or None if no handler registered.
        """
        tdef = self._tags.get(tag_name)
        if not tdef or not tdef.handler:
            return None
        try:
            return tdef.handler(tag_name, value, context or {})
        except Exception as exc:
            logger.warning("Tag handler error [%s]: %s", tag_name, exc)
            return None

    def dispatch_all(
        self,
        matches: Dict[str, List[TagMatch]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[Any]]:
        """
        Dispatch handlers for all detected tags.

        Returns dict of tag_name → list of handler results.
        """
        results: Dict[str, List[Any]] = {}
        for tag_name, tag_matches in matches.items():
            for tm in tag_matches:
                result = self.dispatch(tag_name, tm.value, context)
                if result is not None:
                    results.setdefault(tag_name, []).append(result)
        return results

    # ── Pre-warm intent lookup ──────────────────────────────────────

    def get_pre_warm_intent(self, tag_name: str) -> str:
        """Get the pre-warm intent for a tag type (for TokenAheadRouter)."""
        tdef = self._tags.get(tag_name)
        return tdef.pre_warm_intent if tdef else ""

    def get_intent_map(self) -> Dict[str, str]:
        """Get tag_name → pre_warm_intent for all tags with intents."""
        return {
            name: tdef.pre_warm_intent
            for name, tdef in self._tags.items()
            if tdef.pre_warm_intent
        }

    # ── Built-in tags ───────────────────────────────────────────────

    def _register_builtins(self) -> None:
        """Register the core CosySim tags."""
        builtins = [
            TagDef(
                name="mood",
                pattern=r"\[MOOD:([^\]]+)\]",
                pre_warm_intent="mood_update",
            ),
            TagDef(
                name="image",
                pattern=r"\[(?:IMAGE|SELFIE|PHOTO):([^\]]+)\]",
                aliases=["selfie", "photo"],
                pre_warm_intent="image_generation",
            ),
            TagDef(
                name="action",
                pattern=r"\[ACTION:([^\]]+)\]",
                pre_warm_intent="action_execution",
            ),
            TagDef(
                name="stat",
                pattern=r"\[STAT:(\w+[+-]\d+)\]",
                pre_warm_intent="stat_update",
            ),
            TagDef(
                name="voice",
                pattern=r"\[VOICE:([^\]]+)\]",
                pre_warm_intent="voice_style",
            ),
            # ── Routing tags (v4.1) ────────────────────────────────
            TagDef(
                name="send",
                pattern=r"\[SEND:([^\]]+)\]",
                pre_warm_intent="send_message",
            ),
            TagDef(
                name="event",
                pattern=r"\[EVENT:([^\]]+)\]",
                pre_warm_intent="fire_event",
            ),
            TagDef(
                name="memory",
                pattern=r"\[MEMORY:([^\]]+)\]",
                pre_warm_intent="memory_store",
            ),
            TagDef(
                name="think",
                pattern=r"\[THINK:([^\]]+)\]",
                strip_from_output=True,
                # No pre-warm — think tags are internal reasoning only
            ),
        ]
        for tdef in builtins:
            self.register(tdef)

    # ── Utilities ───────────────────────────────────────────────────

    def describe(self) -> str:
        """Human-readable description of all registered tags (for prompts)."""
        lines = []
        for name, tdef in sorted(self._tags.items()):
            aliases = f" (aliases: {', '.join(tdef.aliases)})" if tdef.aliases else ""
            intent = f" → {tdef.pre_warm_intent}" if tdef.pre_warm_intent else ""
            strip = " [stripped]" if tdef.strip_from_output else ""
            lines.append(f"  [{name.upper()}:value]{aliases}{intent}{strip}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"TagRegistry(tags={list(self._tags.keys())})"
