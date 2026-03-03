"""GrammarScannerInterceptor — post-call scanner that detects low-quality LLM output.

Priority 95 (runs after all other interceptors).
Observes but never blocks responses.
All detected issues are sent to DataCollector for training signal.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List

from engine.mcp.comms_framework import InterceptorBase

logger = logging.getLogger(__name__)

# ── thresholds ────────────────────────────────────────────────────────
_TRUNCATION_MIN_LEN = 50
_MISSING_END_MIN_LEN = 20
_ALL_CAPS_MIN_LEN = 30
_ALL_CAPS_THRESHOLD = 0.60
_REPEAT_PHRASE_WORDS = 5
_REPEAT_PHRASE_MIN_COUNT = 3

_SENTENCE_END_CHARS = frozenset(".!?…\"')")
_BROKEN_SYMBOL_RE = re.compile(r"[□▯]|[\x00-\x08]|\?{3,}")


def _check_truncated(text: str) -> bool:
    """True if text is long but does not end with sentence-ending punctuation."""
    return len(text) >= _TRUNCATION_MIN_LEN and text[-1] not in frozenset(".!?")


def _check_repeated_phrase(text: str) -> bool:
    """True if any 5-word phrase appears 3 or more times."""
    words = text.split()
    if len(words) < _REPEAT_PHRASE_WORDS * _REPEAT_PHRASE_MIN_COUNT:
        return False
    counts: Dict[str, int] = {}
    for i in range(len(words) - _REPEAT_PHRASE_WORDS + 1):
        phrase = " ".join(words[i : i + _REPEAT_PHRASE_WORDS]).lower()
        counts[phrase] = counts.get(phrase, 0) + 1
        if counts[phrase] >= _REPEAT_PHRASE_MIN_COUNT:
            return True
    return False


def _check_empty_response(text: str) -> bool:
    """True if stripped text is empty."""
    return len(text.strip()) == 0


def _check_broken_symbols(text: str) -> bool:
    """True if text contains replacement characters, NUL-range control chars, or ??? runs."""
    return bool(_BROKEN_SYMBOL_RE.search(text))


def _check_missing_sentence_end(text: str) -> bool:
    """True if text is long but last char is not a sentence-ending character."""
    return len(text) > _MISSING_END_MIN_LEN and text[-1] not in _SENTENCE_END_CHARS


def _check_all_caps_spam(text: str) -> bool:
    """True if more than 60 % of alpha characters are uppercase, in responses > 30 chars."""
    if len(text) <= _ALL_CAPS_MIN_LEN:
        return False
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return False
    upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
    return upper_ratio > _ALL_CAPS_THRESHOLD


# ── interceptor ───────────────────────────────────────────────────────

class GrammarScannerInterceptor(InterceptorBase):
    """Post-call interceptor that flags low-quality LLM output for training data.

    Runs at priority 95, after all transformation interceptors have finished.
    Never modifies the context — observation only.
    """

    name = "grammar_scanner"
    priority = 95

    def post_call(self, ctx: object) -> None:  # type: ignore[override]
        """Scan the response for quality issues and record them via DataCollector."""
        response: str = (
            ctx.get("response") or ctx.get("reply", "")  # type: ignore[union-attr]
        )

        issues: List[str] = []

        if _check_empty_response(response):
            issues.append("empty_response")
        else:
            if _check_truncated(response):
                issues.append("truncated")
            if _check_repeated_phrase(response):
                issues.append("repeated_phrase")
            if _check_broken_symbols(response):
                issues.append("broken_symbols")
            if _check_missing_sentence_end(response):
                issues.append("missing_sentence_end")
            if _check_all_caps_spam(response):
                issues.append("all_caps_spam")

        if not issues:
            return

        logger.debug(
            "GrammarScannerInterceptor: issues detected %s (len=%d)",
            issues,
            len(response),
        )

        try:
            from training.data_collector import get_data_collector  # lazy import

            collector = get_data_collector()
            for issue in issues:
                collector.collect_grammar_error(
                    bad_text=response,
                    fixed_text="",
                    error_type=issue,
                )
        except Exception as exc:
            logger.debug("GrammarScannerInterceptor: DataCollector unavailable: %s", exc)
