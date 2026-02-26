"""
StreamWatcher — Real-time token stream analyzer for quality gating.

Runs in parallel with the primary LLM generation, analyzing tokens as they
arrive. Two speeds:

1. **Rule-based (instant)** — repetition detection, token budget, forbidden
   content.  Always runs, no model needed.
2. **Model-based (~50ms)** — intent classification, acceptability scoring.
   Uses fine-tuned Gemma 270M on CPU.  Runs when model is loaded.

Without the fine-tuned model, rule-based checks still catch the majority of
issues.  The pipeline degrades gracefully.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from engine.pipeline.pipeline_result import (
    PipelineConfig,
    WatcherAnalysis,
    WatcherSignal,
)

logger = logging.getLogger(__name__)

# ── Watch context ───────────────────────────────────────────────────────

@dataclass
class WatchContext:
    """Context provided to the watcher for each generation."""
    scene_id: str = ""
    agent_id: str = ""
    character_name: str = ""
    expected_format: str = "dialogue"      # "dialogue", "json", "tool_call"
    scene_rules: List[str] = field(default_factory=list)
    recent_history: List[str] = field(default_factory=list)  # last N responses
    max_tokens: Optional[int] = None       # expected max output length
    forbidden_patterns: List[str] = field(default_factory=list)


# ── Rule-based watcher ──────────────────────────────────────────────────

class RuleBasedWatcher:
    """
    Instant quality checks — no model call needed.

    Catches:
    - Repetition (same phrase repeated N times)
    - Token budget exceeded
    - Forbidden content patterns
    - Stale/empty generation
    """

    def __init__(self, config: PipelineConfig):
        self._config = config
        self._forbidden_re: List[re.Pattern] = []

    def check(self, accumulated: str, context: WatchContext) -> Optional[WatcherSignal]:
        """Run all rule-based checks. Returns KILL if any fail, else None."""
        reason = self._check_repetition(accumulated, context)
        if reason:
            return WatcherSignal.KILL

        reason = self._check_token_budget(accumulated, context)
        if reason:
            return WatcherSignal.KILL

        reason = self._check_forbidden(accumulated, context)
        if reason:
            return WatcherSignal.KILL

        return None

    def get_kill_reason(self) -> str:
        return self._last_reason

    def _check_repetition(self, text: str, context: WatchContext) -> Optional[str]:
        """Detect repeated phrases (3+ word n-grams appearing too often)."""
        self._last_reason = ""
        words = text.split()
        if len(words) < 10:
            return None

        # Check 3-gram repetition
        limit = self._config.repetition_limit
        trigrams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
        counts = Counter(trigrams)
        for gram, count in counts.most_common(3):
            if count >= limit:
                self._last_reason = f"Repetition: '{gram}' repeated {count} times"
                return self._last_reason

        # Check if last 2 sentences are identical
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        if len(sentences) >= 3:
            if sentences[-1] == sentences[-2] == sentences[-3]:
                self._last_reason = f"Identical sentence repeated 3 times"
                return self._last_reason

        return None

    def _check_token_budget(self, text: str, context: WatchContext) -> Optional[str]:
        """Check if generation exceeds expected length."""
        self._last_reason = ""
        if context.max_tokens:
            # Rough estimate: 1 token ≈ 4 characters
            estimated_tokens = len(text) // 4
            if estimated_tokens > context.max_tokens * 1.5:
                self._last_reason = f"Token budget exceeded: ~{estimated_tokens} > {context.max_tokens}"
                return self._last_reason
        return None

    def _check_forbidden(self, text: str, context: WatchContext) -> Optional[str]:
        """Check for forbidden content patterns."""
        self._last_reason = ""
        for pattern in context.forbidden_patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    self._last_reason = f"Forbidden pattern matched: {pattern}"
                    return self._last_reason
            except re.error:
                logger.debug("Suppressed exception", exc_info=True)
        return None

    _last_reason: str = ""


# ── Tag detector (instant) ──────────────────────────────────────────────

# Pre-compiled patterns for CosySim inline tags (fallback if TagRegistry unavailable)
_TAG_PATTERNS = {
    "mood": re.compile(r"\[MOOD:([^\]]+)\]", re.IGNORECASE),
    "image": re.compile(r"\[(?:IMAGE|SELFIE|PHOTO):([^\]]+)\]", re.IGNORECASE),
    "action": re.compile(r"\[ACTION:([^\]]+)\]", re.IGNORECASE),
    "stat": re.compile(r"\[STAT:(\w+[+-]\d+)\]", re.IGNORECASE),
    "voice": re.compile(r"\[VOICE:([^\]]+)\]", re.IGNORECASE),
}


def _get_tag_registry():
    """Lazy import to avoid circular deps."""
    try:
        from engine.mcp.tag_registry import TagRegistry
        return TagRegistry.get()
    except Exception:
        return None


def detect_tags(text: str) -> Dict[str, List[str]]:
    """Detect CosySim inline tags in text.

    Uses TagRegistry when available (covers routing tags too),
    falls back to hardcoded patterns.
    """
    registry = _get_tag_registry()
    if registry:
        results = registry.detect_all(text)
        return {name: [m.value for m in matches] for name, matches in results.items()}

    # Fallback: hardcoded patterns only
    found: Dict[str, List[str]] = {}
    for tag_type, pattern in _TAG_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            found[tag_type] = matches
    return found


# ── Model-based watcher (optional) ─────────────────────────────────────

class ModelBasedWatcher:
    """
    Uses fine-tuned Gemma 270M for intent classification and acceptability
    scoring.  Calls the model via SDK client (~50ms on CPU).

    Falls back silently if model is unavailable.
    """

    def __init__(self, model_key: str, sdk_client: Any = None):
        self._model_key = model_key
        self._sdk = sdk_client
        self._available = False
        self._check_availability()

    def _check_availability(self):
        """Check if the watcher model is loaded in LMStudio."""
        if not self._sdk or not self._model_key:
            self._available = False
            return
        try:
            models = self._sdk.list_loaded()
            self._available = any(
                self._model_key in str(m) for m in models
            )
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def classify(
        self, tokens: str, context: WatchContext
    ) -> Optional[Dict[str, Any]]:
        """
        Classify accumulated tokens using the watcher model.

        Returns dict with: intent, acceptability (0-1), action (continue/kill/pre_warm)
        Returns None if model unavailable.
        """
        if not self._available:
            return None

        prompt = self._build_prompt(tokens, context)
        try:
            t0 = time.perf_counter()
            response = self._sdk.respond(
                messages=[
                    {"role": "system", "content": self._system_prompt(context)},
                    {"role": "user", "content": prompt},
                ],
                model_key=self._model_key,
            )
            latency = (time.perf_counter() - t0) * 1000

            import json
            result = json.loads(response.content.strip())
            result["latency_ms"] = latency
            return result
        except Exception as exc:
            logger.debug("Watcher model classification failed: %s", exc)
            return None

    def _system_prompt(self, context: WatchContext) -> str:
        rules = "\n".join(f"- {r}" for r in context.scene_rules) if context.scene_rules else "None"
        return (
            "You are a stream quality analyzer. Given the first tokens of an LLM response, "
            "classify the intent and score acceptability (0.0–1.0).\n"
            f"Scene: {context.scene_id}\n"
            f"Character: {context.character_name}\n"
            f"Rules:\n{rules}\n"
            "Respond ONLY with JSON: "
            '{"intent":"...","acceptability":0.0-1.0,"action":"continue|kill|pre_warm","tools":[]}'
        )

    def _build_prompt(self, tokens: str, context: WatchContext) -> str:
        return (
            f'Tokens so far: "{tokens}"\n'
            f"Expected format: {context.expected_format}"
        )


# ── StreamWatcher (main class) ──────────────────────────────────────────

class StreamWatcher:
    """
    Composite watcher that combines rule-based and model-based analysis.

    Usage::

        watcher = StreamWatcher(config, sdk_client=sdk)
        watcher.start_session(context)

        # Feed tokens as they arrive
        for token in stream:
            signal = watcher.feed(token)
            if signal == WatcherSignal.KILL:
                cancel_generation()
                break

        analysis = watcher.get_analysis()
    """

    def __init__(
        self,
        config: PipelineConfig = PipelineConfig(),
        sdk_client: Any = None,
    ):
        self._config = config
        self._rules = RuleBasedWatcher(config)
        self._model: Optional[ModelBasedWatcher] = None
        if config.watcher_enabled and config.watcher_model_key:
            self._model = ModelBasedWatcher(config.watcher_model_key, sdk_client)

        # Session state
        self._context: Optional[WatchContext] = None
        self._accumulated: str = ""
        self._token_count: int = 0
        self._signals: List[WatcherSignal] = []
        self._intent: str = ""
        self._acceptability: float = 1.0
        self._predicted_tools: List[str] = []
        self._total_latency: float = 0.0
        self._kill_reason: str = ""
        self._tags_detected: Dict[str, List[str]] = {}
        self._classification_done: bool = False

    def start_session(self, context: WatchContext) -> None:
        """Begin a new watch session."""
        self._context = context
        self._accumulated = ""
        self._token_count = 0
        self._signals = []
        self._intent = ""
        self._acceptability = 1.0
        self._predicted_tools = []
        self._total_latency = 0.0
        self._kill_reason = ""
        self._tags_detected = {}
        self._classification_done = False

    def feed(self, token: str) -> Optional[WatcherSignal]:
        """
        Feed a token (or token batch). Returns a signal if action needed.

        Called for every token from the primary LLM stream.
        """
        if not self._context:
            return None

        self._accumulated += token
        self._token_count += 1

        # Always check for tags (instant)
        new_tags = detect_tags(token)
        if new_tags:
            for tag_type, values in new_tags.items():
                self._tags_detected.setdefault(tag_type, []).extend(values)
            signal = WatcherSignal.ROUTE
            self._signals.append(signal)
            return signal

        # Rule-based checks every batch
        if self._token_count % self._config.watcher_batch_size == 0:
            rule_signal = self._rules.check(self._accumulated, self._context)
            if rule_signal:
                self._kill_reason = self._rules.get_kill_reason()
                self._acceptability = 0.0
                self._signals.append(rule_signal)
                return rule_signal

        # Model-based classification on first trigger
        if (
            not self._classification_done
            and self._token_count >= self._config.watcher_trigger_tokens
            and self._model
            and self._model.available
        ):
            self._classification_done = True
            t0 = time.perf_counter()
            result = self._model.classify(self._accumulated, self._context)
            self._total_latency += (time.perf_counter() - t0) * 1000

            if result:
                self._intent = result.get("intent", "")
                self._acceptability = result.get("acceptability", 1.0)
                action = result.get("action", "continue")
                tools = result.get("tools", [])

                if self._acceptability < self._config.kill_threshold:
                    self._kill_reason = f"Low acceptability: {self._acceptability:.2f}"
                    signal = WatcherSignal.KILL
                    self._signals.append(signal)
                    return signal

                if action == "pre_warm" or tools:
                    self._predicted_tools = tools
                    signal = WatcherSignal.PRE_WARM
                    self._signals.append(signal)
                    return signal

        return None

    def get_analysis(self) -> WatcherAnalysis:
        """Get the final analysis after generation completes."""
        return WatcherAnalysis(
            intent=self._intent,
            acceptability=self._acceptability,
            signals=list(self._signals),
            tokens_analyzed=self._token_count,
            latency_ms=self._total_latency,
            kill_reason=self._kill_reason,
            predicted_tools=list(self._predicted_tools),
        )

    @property
    def tags_detected(self) -> Dict[str, List[str]]:
        """Tags detected during this session."""
        return dict(self._tags_detected)

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    @property
    def has_model(self) -> bool:
        """Whether the model-based watcher is available."""
        return self._model is not None and self._model.available
