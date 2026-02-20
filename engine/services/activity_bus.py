"""
ActivityBus — Global real-time activity tracker for CosySim

Provides a thread-safe, singleton registry of what is happening across ALL
agents and scenes RIGHT NOW.  Anything that wants to report status (thinking,
calling a tool, generating TTS, etc.) posts to the bus; the stats overlay
polls it to show the user what the AI is doing.

Usage::

    from engine.services.activity_bus import get_activity_bus, Activity

    bus = get_activity_bus()

    # Signal that an agent is thinking
    token = bus.push(Activity(
        kind="thinking",
        label="Aria is thinking…",
        agent_id="char-aria",
        scene="phone",
    ))

    # ...LLM call happens...

    bus.pop(token)           # remove when done

    # Or use the context manager:
    with bus.activity(kind="tool_call", label="Calling search_web", agent_id="char-aria"):
        results = search_web(query)
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

_HISTORY_MAX = 50


@dataclass
class Activity:
    """A single in-flight activity."""
    kind:      str               # "thinking" | "tool_call" | "tts" | "image_gen" | "memory" | ...
    label:     str               # human-readable description
    agent_id:  str  = ""         # character / agent id
    scene:     str  = ""         # which scene this is happening in
    model:     str  = ""         # model being used (if relevant)
    started_at: float = field(default_factory=time.time)
    token:      str  = field(default_factory=lambda: str(uuid.uuid4())[:8])
    extra:      Dict[str, Any] = field(default_factory=dict)

    def elapsed_ms(self) -> float:
        return (time.time() - self.started_at) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind":       self.kind,
            "label":      self.label,
            "agent_id":   self.agent_id,
            "scene":      self.scene,
            "model":      self.model,
            "elapsed_ms": round(self.elapsed_ms(), 0),
            "token":      self.token,
        }


@dataclass
class HistoryEntry:
    """A completed activity (for recent-history display)."""
    kind:       str
    label:      str
    agent_id:   str
    duration_ms: float
    timestamp:  float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind":        self.kind,
            "label":       self.label,
            "agent_id":    self.agent_id,
            "duration_ms": round(self.duration_ms, 0),
            "timestamp":   round(self.timestamp, 2),
        }


class ActivityBus:
    """
    Central, thread-safe registry of in-flight activities.

    At any moment ``current_activities`` holds everything happening right now.
    Historical completed entries are kept in a fixed-size ring buffer
    (last 50) so the overlay can show a brief recent log.
    """

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._active:  Dict[str, Activity]     = {}  # token → Activity
        self._history: List[HistoryEntry]       = []

    # ── Write API ──────────────────────────────────────────────────────

    def push(self, activity: Activity) -> str:
        """Register a new in-flight activity.  Returns its token."""
        with self._lock:
            self._active[activity.token] = activity
        return activity.token

    def pop(self, token: str) -> Optional[Activity]:
        """Mark an activity as complete by its token.  Adds to history."""
        with self._lock:
            act = self._active.pop(token, None)
            if act:
                entry = HistoryEntry(
                    kind=act.kind,
                    label=act.label,
                    agent_id=act.agent_id,
                    duration_ms=act.elapsed_ms(),
                )
                self._history.append(entry)
                if len(self._history) > _HISTORY_MAX:
                    self._history = self._history[-(_HISTORY_MAX // 2):]
        return act

    @contextmanager
    def activity(
        self,
        kind: str,
        label: str,
        *,
        agent_id: str = "",
        scene:    str = "",
        model:    str = "",
        extra:    Optional[Dict] = None,
    ) -> Iterator[Activity]:
        """Context manager: push on enter, pop on exit (even on exception)."""
        act = Activity(
            kind=kind, label=label, agent_id=agent_id,
            scene=scene, model=model, extra=extra or {},
        )
        token = self.push(act)
        try:
            yield act
        finally:
            self.pop(token)

    # ── Read API ───────────────────────────────────────────────────────

    @property
    def current_activities(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in self._active.values()]

    @property
    def recent_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [h.to_dict() for h in self._history[-20:]]

    @property
    def is_idle(self) -> bool:
        with self._lock:
            return len(self._active) == 0

    def snapshot(self) -> Dict[str, Any]:
        """Full state snapshot for the stats API."""
        with self._lock:
            active = [a.to_dict() for a in self._active.values()]
            history = [h.to_dict() for h in self._history[-10:]]
        return {
            "active":  active,
            "history": history,
            "count":   len(active),
            "idle":    len(active) == 0,
        }

    def clear(self) -> None:
        """Emergency clear (e.g. on server restart)."""
        with self._lock:
            self._active.clear()


# ── Module-level singleton ─────────────────────────────────────────────

_bus: Optional[ActivityBus] = None
_bus_lock = threading.Lock()


def get_activity_bus() -> ActivityBus:
    """Return the global ActivityBus singleton."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = ActivityBus()
    return _bus
