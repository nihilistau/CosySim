"""
TokenAheadRouter — Pre-warms MCP tools during LLM generation.

When the StreamWatcher detects an intent (e.g., "the LLM is about to request
an image"), the router starts the MCP tool call immediately — while tokens are
still generating.  By the time the tag actually appears, the result is ready.

Timeline::

    Token  Primary LLM Output        Watcher         MCP Tool
    T1     "She"                      analyzing...    idle
    T3     "her phone"                ACTION →        pre-warm: get_phone
    T5     "a selfie"                 IMAGE →         start: generate_image
    T6     "[IMAGE:cute selfie]"      confirmed       result READY ✓
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from engine.pipeline.pipeline_result import PreWarmResult

logger = logging.getLogger(__name__)


# ── Intent → tool mapping ───────────────────────────────────────────────

# Default mapping of detected intents to tool pre-warming actions.
# Scenes can extend this with scene-specific mappings.
_DEFAULT_INTENT_MAP: Dict[str, str] = {
    "image_generation": "generate_image_request",
    "selfie": "generate_image_request",
    "memory_lookup": "search_memory",
    "memory_store": "store_memory",
    "character_state": "get_character_state",
    "mood_update": "update_mood",
    "relationship": "adjust_relationship",
    "dice_roll": "roll_dice",
    "voice_message": "send_voice_message",
    # v4.1 routing intents
    "send_message": "send_agent_message",
    "fire_event": "fire_scene_event",
}


def _get_tag_intent_map() -> Dict[str, str]:
    """Get tag→intent mapping from TagRegistry when available."""
    try:
        from engine.mcp.tag_registry import TagRegistry
        return TagRegistry.get().get_intent_map()
    except Exception:
        # Fallback to hardcoded map
        return {
            "image": "image_generation",
            "mood": "mood_update",
            "action": "action_execution",
            "stat": "stat_update",
            "voice": "voice_style",
        }


# ── TokenAheadRouter ────────────────────────────────────────────────────

class TokenAheadRouter:
    """
    Pre-warms MCP tools when the StreamWatcher detects intent.

    Usage::

        router = TokenAheadRouter(tool_executor=my_executor)

        # When watcher detects intent:
        router.on_intent_detected("image_generation", {"prompt": "selfie"})

        # When tag is confirmed in stream:
        router.on_tag_detected("image", "a selfie in the penthouse")

        # At end of generation:
        results = router.collect_results(timeout=5.0)
    """

    def __init__(
        self,
        tool_executor: Optional[Callable] = None,
        intent_map: Optional[Dict[str, str]] = None,
        max_workers: int = 3,
        timeout: float = 5.0,
    ):
        self._executor_fn = tool_executor
        self._intent_map = dict(_DEFAULT_INTENT_MAP)
        if intent_map:
            self._intent_map.update(intent_map)
        self._timeout = timeout
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pre-warm")
        self._futures: Dict[str, Tuple[Future, float, str, Dict]] = {}  # key → (future, start_time, tool, args)
        self._results: List[PreWarmResult] = []

    def on_intent_detected(
        self,
        intent: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Watcher detected an intent — pre-warm the matching tool.

        Returns the tool name if pre-warming started, else None.
        """
        tool_name = self._intent_map.get(intent)
        if not tool_name or not self._executor_fn:
            return None

        # Don't re-start if already warming this tool
        if tool_name in self._futures:
            return tool_name

        context = context or {}
        t0 = time.perf_counter()
        try:
            future = self._pool.submit(self._executor_fn, tool_name, context)
            self._futures[tool_name] = (future, t0, tool_name, context)
            logger.info("Pre-warming tool: %s (intent: %s)", tool_name, intent)
            return tool_name
        except Exception as exc:
            logger.debug("Failed to start pre-warm for %s: %s", tool_name, exc)
            return None

    def on_tag_detected(
        self,
        tag_type: str,
        tag_value: str,
    ) -> Optional[str]:
        """
        StreamProcessor confirmed a tag — start tool if not already warming.

        Returns tool name if started or already running, else None.
        """
        # Get intent from TagRegistry (dynamic) or fallback map
        intent_map = _get_tag_intent_map()
        intent = intent_map.get(tag_type)
        if not intent:
            return None
        return self.on_intent_detected(intent, {"value": tag_value})

    def collect_results(self, timeout: Optional[float] = None) -> List[PreWarmResult]:
        """
        Collect all pre-warmed tool results.

        Blocks until all futures complete or timeout.
        """
        timeout = timeout or self._timeout
        results: List[PreWarmResult] = []

        for tool_name, (future, t0, name, args) in self._futures.items():
            pw = PreWarmResult(tool_name=name, arguments=args)
            try:
                remaining = max(0.1, timeout - (time.perf_counter() - t0))
                pw.result = future.result(timeout=remaining)
                pw.success = True
                pw.latency_ms = (time.perf_counter() - t0) * 1000
            except FuturesTimeout:
                pw.success = False
                pw.latency_ms = timeout * 1000
                logger.warning("Pre-warm timeout for %s", name)
            except Exception as exc:
                pw.success = False
                pw.latency_ms = (time.perf_counter() - t0) * 1000
                logger.warning("Pre-warm failed for %s: %s", name, exc)
            results.append(pw)

        self._results = results
        return results

    def mark_used(self, tool_name: str) -> None:
        """Mark a pre-warmed result as actually used (tag appeared in final output)."""
        for r in self._results:
            if r.tool_name == tool_name:
                r.was_used = True

    def reset(self) -> None:
        """Reset for a new generation cycle."""
        # Cancel any pending futures
        for _, (future, _, _, _) in self._futures.items():
            future.cancel()
        self._futures.clear()
        self._results.clear()

    @property
    def active_count(self) -> int:
        """Number of currently active pre-warm tasks."""
        return sum(1 for _, (f, _, _, _) in self._futures.items() if not f.done())

    @property
    def completed_count(self) -> int:
        return sum(1 for _, (f, _, _, _) in self._futures.items() if f.done())

    def shutdown(self) -> None:
        """Shutdown the thread pool."""
        self._pool.shutdown(wait=False)
