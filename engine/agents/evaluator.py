"""
TextEvaluator v2.9 — Fast response quality scoring.

Two evaluation modes:
1. **Heuristic** (no LLM, instant): keyword density, length, variety, loops
2. **Model-based** (store=false, fast small model): personality alignment score

The heuristic scorer runs on every response. The model-based scorer is
optional and only used for quality gates or important conversations.

Usage::

    from engine.agents.evaluator import TextEvaluator, ResponseScore

    evaluator = TextEvaluator()

    # Fast heuristic score
    score = evaluator.score_heuristic(text, character_name="Luna")
    print(score.total)  # 0.0 - 1.0

    # Check for response problems
    problems = evaluator.detect_problems(text, recent_messages=["Hi", "Hello"])
    print(problems)  # ["repetitive", "too_short"]

    # Score with model (expensive, use sparingly)
    score = await evaluator.score_with_model(text, personality="flirty rebel")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Patterns ────────────────────────────────────────────────────────────

_RE_QUESTION = re.compile(r"\?")
_RE_EMOJI = re.compile(
    r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U0000FE0F]"
)
_RE_ACTION_TAG = re.compile(r"\[ACTION:[^\]]+\]", re.IGNORECASE)
_RE_ALL_CAPS = re.compile(r"\b[A-Z]{4,}\b")


@dataclass
class ResponseScore:
    """Quality score breakdown for an LLM response."""
    length_score: float = 0.0      # 0-1: appropriate length
    variety_score: float = 0.0     # 0-1: not repeating recent messages
    engagement_score: float = 0.0  # 0-1: questions, callbacks, emotions
    personality_score: float = 0.0 # 0-1: matches character traits
    expressiveness: float = 0.0    # 0-1: emojis, actions, varied punctuation
    problems: List[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        """Weighted average quality score (0.0 - 1.0)."""
        return (
            self.length_score * 0.15
            + self.variety_score * 0.25
            + self.engagement_score * 0.25
            + self.personality_score * 0.20
            + self.expressiveness * 0.15
        )

    @property
    def is_acceptable(self) -> bool:
        """Score above minimum threshold."""
        return self.total >= 0.35 and not any(
            p in ("garbage", "empty", "token_artifacts")
            for p in self.problems
        )


class TextEvaluator:
    """Fast response quality evaluator."""

    def __init__(
        self,
        ideal_length: tuple = (40, 400),
        personality_keywords: Optional[Set[str]] = None,
    ):
        self._ideal_min, self._ideal_max = ideal_length
        self._personality_keywords = personality_keywords or set()

    def score_heuristic(
        self,
        text: str,
        *,
        character_name: str = "",
        recent_messages: Optional[List[str]] = None,
        personality_keywords: Optional[Set[str]] = None,
    ) -> ResponseScore:
        """Instant heuristic quality score — no LLM call needed."""
        score = ResponseScore()

        if not text or not text.strip():
            score.problems.append("empty")
            return score

        text = text.strip()
        words = text.split()
        word_count = len(words)

        # Length score
        if word_count < 3:
            score.length_score = 0.1
            score.problems.append("too_short")
        elif word_count > 200:
            score.length_score = 0.4
            score.problems.append("too_long")
        elif self._ideal_min <= len(text) <= self._ideal_max:
            score.length_score = 1.0
        else:
            score.length_score = 0.6

        # Variety score (vs recent messages)
        recent = recent_messages or []
        if recent:
            text_lower = text.lower()
            overlap_count = sum(
                1 for msg in recent[-5:]
                if msg and self._similarity(text_lower, msg.lower()) > 0.6
            )
            if overlap_count >= 2:
                score.variety_score = 0.1
                score.problems.append("repetitive")
            elif overlap_count == 1:
                score.variety_score = 0.5
            else:
                score.variety_score = 1.0
        else:
            score.variety_score = 0.8

        # Engagement score
        has_question = bool(_RE_QUESTION.search(text))
        has_exclaim = "!" in text
        has_action = bool(_RE_ACTION_TAG.search(text))
        engagement = 0.3  # base
        if has_question:
            engagement += 0.3
        if has_exclaim:
            engagement += 0.1
        if has_action:
            engagement += 0.2
        if any(w in text.lower() for w in ("remember", "earlier", "before", "last time")):
            engagement += 0.1  # references earlier conversation
        score.engagement_score = min(1.0, engagement)

        # Personality score
        kw = personality_keywords or self._personality_keywords
        if kw:
            text_lower = text.lower()
            matches = sum(1 for k in kw if k.lower() in text_lower)
            score.personality_score = min(1.0, matches / max(1, len(kw) * 0.3))
        else:
            score.personality_score = 0.6  # neutral

        # Expressiveness
        has_emoji = bool(_RE_EMOJI.search(text))
        has_ellipsis = "..." in text or "…" in text
        has_caps_emphasis = bool(_RE_ALL_CAPS.search(text))
        expr = 0.3  # base
        if has_emoji:
            expr += 0.3
        if has_ellipsis:
            expr += 0.1
        if has_caps_emphasis:
            expr += 0.1
        if has_action:
            expr += 0.2
        score.expressiveness = min(1.0, expr)

        # Problem detection
        if self._has_token_artifacts(text):
            score.problems.append("token_artifacts")
        if self._is_garbage(text):
            score.problems.append("garbage")

        return score

    def detect_problems(
        self,
        text: str,
        recent_messages: Optional[List[str]] = None,
    ) -> List[str]:
        """Quick problem check — returns list of problem types."""
        score = self.score_heuristic(text, recent_messages=recent_messages)
        return score.problems

    def is_garbage(self, text: str) -> bool:
        """Check if response is garbage (empty, artifacts-only, too short)."""
        return self._is_garbage(text)

    # ── Internal ─────────────────────────────────────────────────────────

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Simple word-overlap Jaccard similarity."""
        if not a or not b:
            return 0.0
        set_a = set(a.split())
        set_b = set(b.split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _has_token_artifacts(text: str) -> bool:
        """Check for leaked special tokens."""
        artifacts = (
            "<|begin_of_text|>", "<|end_of_text|>", "<|eot_id|>",
            "<|im_start|>", "<|im_end|>", "<|endoftext|>",
        )
        return any(a in text for a in artifacts)

    @staticmethod
    def _is_garbage(text: str) -> bool:
        """Detect garbage responses."""
        if not text or not text.strip():
            return True
        stripped = text.strip()
        if len(stripped) < 3:
            return True
        # All whitespace/punctuation
        if not any(c.isalnum() for c in stripped):
            return True
        return False


# ── Image Evaluator ─────────────────────────────────────────────────────

@dataclass
class ImageScore:
    """Quality score for a generated image."""
    quality: float = 0.0       # 0-1: technical quality
    relevance: float = 0.0     # 0-1: matches the prompt
    description: str = ""      # VLM description of what it sees
    problems: List[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.quality * 0.4 + self.relevance * 0.6

    @property
    def is_acceptable(self) -> bool:
        return self.total >= 0.4


class ImageEvaluator:
    """Evaluate generated images using a Vision-Language Model.

    Uses ``LMSClient.chat_with_images()`` with store=false for cheap
    one-shot evaluation. Requires a VLM to be loaded in LMStudio.
    """

    EVAL_SYSTEM = (
        "You are an image quality evaluator. Respond ONLY with JSON:\n"
        '{"quality": 0.0-1.0, "relevance": 0.0-1.0, "description": "brief description"}\n'
        "quality: technical quality (sharpness, coherence, no artifacts)\n"
        "relevance: how well it matches the requested prompt"
    )

    def evaluate(
        self,
        image_data_url: str,
        prompt: str,
        *,
        model: Optional[str] = None,
    ) -> ImageScore:
        """Evaluate an image using VLM. Returns ImageScore.

        Args:
            image_data_url: base64 data URL (data:image/png;base64,...)
            prompt: The original generation prompt
            model: Optional VLM model override
        """
        try:
            from engine.lmstudio.lms_client import get_lms_client
            from engine.agents.content_router import extract_json

            client = get_lms_client()
            user_text = f"Evaluate this image against the prompt: \"{prompt}\""

            resp = client.chat_with_images(
                user_text,
                [image_data_url],
                system=self.EVAL_SYSTEM,
                store=False,
                max_output_tokens=200,
                temperature=0.1,
                **({"model": model} if model else {}),
            )

            data = extract_json(resp.content or "")
            if data:
                return ImageScore(
                    quality=float(data.get("quality", 0.5)),
                    relevance=float(data.get("relevance", 0.5)),
                    description=str(data.get("description", "")),
                )

            return ImageScore(quality=0.5, relevance=0.5, description="eval_parse_failed")

        except Exception as exc:
            logger.warning("Image evaluation failed: %s", exc)
            return ImageScore(quality=0.5, relevance=0.5, problems=["eval_failed"])

    def describe(
        self,
        image_data_url: str,
        *,
        model: Optional[str] = None,
    ) -> str:
        """Get a text description of an image using VLM."""
        try:
            from engine.lmstudio.lms_client import get_lms_client

            client = get_lms_client()
            resp = client.chat_with_images(
                "Describe this image in one concise sentence.",
                [image_data_url],
                store=False,
                max_output_tokens=100,
                temperature=0.3,
                **({"model": model} if model else {}),
            )
            return (resp.content or "").strip()

        except Exception as exc:
            logger.warning("Image description failed: %s", exc)
            return ""


_image_evaluator_instance: Optional[ImageEvaluator] = None


def get_image_evaluator() -> ImageEvaluator:
    """Return the global ImageEvaluator singleton."""
    global _image_evaluator_instance
    if _image_evaluator_instance is None:
        _image_evaluator_instance = ImageEvaluator()
    return _image_evaluator_instance


# ── Text Evaluator Singleton ────────────────────────────────────────────

_evaluator_instance: Optional[TextEvaluator] = None


def get_text_evaluator(**kwargs) -> TextEvaluator:
    """Return the global TextEvaluator singleton."""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = TextEvaluator(**kwargs)
    return _evaluator_instance
