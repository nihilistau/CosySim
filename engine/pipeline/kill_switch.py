"""
KillSwitch — Quality gate that cancels LLM generation mid-stream.

Evaluates StreamWatcher analysis and decides whether to kill the current
generation.  If killed, provides retry strategies:

1. Lower temperature (more constrained output)
2. Add explicit constraints to system prompt
3. Increase watcher sensitivity on retry

Cancel mechanism:
- SDK path: ``PredictionStream.cancel()``
- REST path: close the httpx stream connection
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.pipeline.pipeline_result import (
    PipelineConfig,
    WatcherAnalysis,
    WatcherSignal,
)

logger = logging.getLogger(__name__)


# ── Kill reasons ────────────────────────────────────────────────────────

@dataclass
class KillDecision:
    """The kill switch's decision for a generation."""
    should_kill: bool = False
    reason: str = ""
    retry_allowed: bool = True
    confidence: float = 0.0          # 0-1 how confident we are in the kill


# ── KillSwitch ──────────────────────────────────────────────────────────

class KillSwitch:
    """
    Quality gate that evaluates StreamWatcher analysis and kills bad generations.

    Kill conditions (any one triggers):
    1. Watcher acceptability below threshold
    2. Kill signal from watcher (explicit KILL)
    3. Generation exceeds retry limit (accept best attempt)

    Retry strategy:
    - Temperature decays by config.retry_temperature_decay per retry
    - Explicit constraint added to system prompt
    - Max retries configurable (default 2)
    """

    def __init__(self, config: PipelineConfig = PipelineConfig()):
        self._config = config
        self._retry_count = 0
        self._killed_contents: List[str] = []
        self._best_content: str = ""
        self._best_acceptability: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._config.kill_switch_enabled

    @property
    def retry_count(self) -> int:
        return self._retry_count

    @property
    def max_retries(self) -> int:
        return self._config.max_retries

    @property
    def can_retry(self) -> bool:
        return self._retry_count < self._config.max_retries

    @property
    def killed_contents(self) -> List[str]:
        return list(self._killed_contents)

    def reset(self) -> None:
        """Reset for a new generation cycle."""
        self._retry_count = 0
        self._killed_contents = []
        self._best_content = ""
        self._best_acceptability = 0.0

    def evaluate(
        self,
        analysis: WatcherAnalysis,
        accumulated_content: str = "",
        token_count: int = 0,
    ) -> KillDecision:
        """
        Evaluate whether to kill the current generation.

        Returns a KillDecision with should_kill, reason, and retry info.
        """
        if not self.enabled:
            return KillDecision(should_kill=False)

        # Track best attempt so far
        if analysis.acceptability > self._best_acceptability:
            self._best_acceptability = analysis.acceptability
            self._best_content = accumulated_content

        # Check 1: Explicit KILL signal from watcher
        if WatcherSignal.KILL in analysis.signals:
            reason = analysis.kill_reason or "Watcher issued KILL signal"
            return KillDecision(
                should_kill=True,
                reason=reason,
                retry_allowed=self.can_retry,
                confidence=1.0 - analysis.acceptability,
            )

        # Check 2: Acceptability below threshold
        if analysis.acceptability < self._config.kill_threshold:
            return KillDecision(
                should_kill=True,
                reason=f"Acceptability {analysis.acceptability:.2f} < threshold {self._config.kill_threshold}",
                retry_allowed=self.can_retry,
                confidence=1.0 - analysis.acceptability,
            )

        return KillDecision(should_kill=False)

    def on_kill(self, content: str) -> None:
        """Record that a generation was killed."""
        self._killed_contents.append(content)
        self._retry_count += 1
        logger.info(
            "Kill switch fired (retry %d/%d): %s",
            self._retry_count,
            self._config.max_retries,
            content[:80] + "..." if len(content) > 80 else content,
        )

    def modify_for_retry(
        self,
        messages: List[Dict[str, str]],
        original_temperature: Optional[float] = None,
        kill_reason: str = "",
    ) -> Dict[str, Any]:
        """
        Modify request parameters for retry after kill.

        Returns dict with:
        - messages: adjusted messages (constraint appended to system prompt)
        - temperature: reduced temperature
        """
        messages = copy.deepcopy(messages)
        temp = original_temperature or 0.7

        # Reduce temperature per retry
        new_temp = max(0.1, temp - (self._config.retry_temperature_decay * self._retry_count))

        # Add constraint to system prompt
        constraint = self._build_retry_constraint(kill_reason)
        if constraint and messages:
            if messages[0].get("role") == "system":
                messages[0]["content"] += f"\n\n{constraint}"
            else:
                messages.insert(0, {"role": "system", "content": constraint})

        return {
            "messages": messages,
            "temperature": new_temp,
        }

    def get_best_content(self) -> str:
        """Get the best content from all attempts (including killed ones)."""
        return self._best_content

    def _build_retry_constraint(self, kill_reason: str) -> str:
        """Build a constraint message for retrying after kill."""
        parts = ["IMPORTANT: Your previous response was rejected."]
        if kill_reason:
            parts.append(f"Reason: {kill_reason}")
        parts.append("Please stay focused and follow the expected format closely.")

        if self._retry_count >= 2:
            parts.append("Keep your response SHORT and direct.")

        return " ".join(parts)
