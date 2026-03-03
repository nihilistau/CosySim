"""OutputEvaluator — auto-scores every LLM response 0.0–1.0.

Low-quality responses (score < 0.4) are stored in Nexus for improvement review.
Scores also feed DataCollector for training signal.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_evaluator_instance: Optional["OutputEvaluator"] = None
_evaluator_lock = threading.Lock()

# Punctuation that marks a properly completed sentence end
_SENTENCE_ENDS = frozenset(".!?…\"')")

# Punctuation that signals truncation
_TRUNCATION_ENDS = frozenset(",;:")


class OutputEvaluator:
    """Scores LLM responses and routes low-quality output to Nexus."""

    # ── Scoring ─────────────────────────────────────────────────────

    def score(self, response: str, context: Dict[str, Any]) -> float:  # noqa: ARG002
        """Return a quality score in [0.0, 1.0] based on five heuristics.

        Args:
            response: The LLM-generated text to evaluate.
            context: Request context (not used in heuristics, reserved for future use).

        Returns:
            Float score from 0.0 to 1.0; each passing check adds 0.2.
        """
        if not response:
            return 0.0

        total = 0.0

        # 1. length_ok
        if len(response) >= 10:
            total += 0.2

        # 2. sentence_complete — last non-whitespace char is a sentence-end
        stripped = response.rstrip()
        if stripped and stripped[-1] in _SENTENCE_ENDS:
            total += 0.2

        # 3. no_truncation — does not end with truncation punctuation or mid-word
        if stripped:
            last_char = stripped[-1]
            if last_char not in _TRUNCATION_ENDS and last_char.isalnum() is False:
                # Passes if last char is not a truncation mark
                total += 0.2
            elif last_char not in _TRUNCATION_ENDS and last_char.isalpha():
                # Last char is alphabetic → mid-word cut → fail
                pass
            elif last_char not in _TRUNCATION_ENDS:
                total += 0.2

        # 4. no_repetition — no 4+ word phrase repeated 3 or more times
        if not self._has_repetition(response):
            total += 0.2

        # 5. coherent — not all caps, has spaces, > 2 unique words
        if self._is_coherent(response):
            total += 0.2

        return round(min(total, 1.0), 2)

    # ── Evaluate + store ─────────────────────────────────────────────

    def evaluate_and_store(
        self,
        response: str,
        context: Dict[str, Any],
        agent_name: str = "",
    ) -> float:
        """Score a response and persist low-quality ones to Nexus.

        Args:
            response: The LLM-generated text.
            context: Request context; ``user_message`` key used for storage.
            agent_name: Originating agent identifier for logging.

        Returns:
            The quality score (0.0–1.0).
        """
        quality = self.score(response, context)

        if quality < 0.4:
            self._store_in_nexus(response, context, agent_name, quality)

        self._collect_training_signal(context, response, quality)

        return quality

    # ── Private helpers ──────────────────────────────────────────────

    def _has_repetition(self, text: str) -> bool:
        """Return True if a 4+ word phrase is repeated 3 or more times."""
        words = text.lower().split()
        if len(words) < 12:
            return False
        for phrase_len in range(4, min(8, len(words) // 3) + 1):
            counts: Dict[str, int] = {}
            for i in range(len(words) - phrase_len + 1):
                phrase = " ".join(words[i : i + phrase_len])
                counts[phrase] = counts.get(phrase, 0) + 1
                if counts[phrase] >= 3:
                    return True
        return False

    def _is_coherent(self, text: str) -> bool:
        """Return True if text passes basic coherence checks."""
        if text == text.upper() and any(c.isalpha() for c in text):
            return False
        if " " not in text.strip():
            return False
        unique_words = {w.lower() for w in re.findall(r"[a-zA-Z]+", text)}
        if len(unique_words) <= 2:
            return False
        return True

    def _store_in_nexus(
        self,
        response: str,
        context: Dict[str, Any],
        agent_name: str,
        quality: float,
    ) -> None:
        """Persist a low-quality response to Nexus for review."""
        try:
            from engine.nexus.client import get_nexus_client

            user_msg = context.get("user_message", "")
            title = f"Low-quality response — {agent_name or 'unknown'} (score={quality:.2f})"
            content = (
                f"Agent: {agent_name or 'unknown'}\n"
                f"Score: {quality:.2f}\n"
                f"User message: {user_msg[:500]}\n\n"
                f"Response:\n{response[:2000]}"
            )
            get_nexus_client().add_entry(
                title,
                content,
                content_type="note",
                category="improvement",
            )
            logger.debug("OutputEvaluator stored low-quality response (score=%.2f)", quality)
        except Exception:
            logger.debug("OutputEvaluator: Nexus store failed", exc_info=True)

    def _collect_training_signal(
        self,
        context: Dict[str, Any],
        response: str,
        quality: float,
    ) -> None:
        """Send quality score to DataCollector for training signal."""
        try:
            from training.data_collector import get_data_collector

            user_msg = context.get("user_message", "")
            get_data_collector().collect(
                "output_quality",
                user_msg,
                response,
                quality=quality,
            )
        except Exception:
            logger.debug("OutputEvaluator: DataCollector call failed", exc_info=True)


# ── Singleton ────────────────────────────────────────────────────────


def get_output_evaluator() -> OutputEvaluator:
    """Return the global OutputEvaluator singleton."""
    global _evaluator_instance
    if _evaluator_instance is None:
        with _evaluator_lock:
            if _evaluator_instance is None:
                _evaluator_instance = OutputEvaluator()
    return _evaluator_instance
