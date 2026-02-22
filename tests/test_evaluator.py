"""Tests for engine/agents/evaluator.py — Text and image quality scoring."""
import pytest
from engine.agents.evaluator import (
    TextEvaluator,
    ResponseScore,
    ImageScore,
    get_text_evaluator,
)


# ── TextEvaluator heuristic scoring ──────────────────────────────────────

class TestResponseScore:
    def test_total_is_weighted_average(self):
        s = ResponseScore(
            length_score=1.0, variety_score=1.0, engagement_score=1.0,
            personality_score=1.0, expressiveness=1.0,
        )
        assert s.total == pytest.approx(1.0)

    def test_empty_score_is_zero(self):
        s = ResponseScore()
        assert s.total == 0.0

    def test_is_acceptable_above_threshold(self):
        s = ResponseScore(
            length_score=0.6, variety_score=0.6, engagement_score=0.6,
            personality_score=0.6, expressiveness=0.6,
        )
        assert s.is_acceptable

    def test_garbage_not_acceptable(self):
        s = ResponseScore(
            length_score=1.0, variety_score=1.0, engagement_score=1.0,
            personality_score=1.0, expressiveness=1.0,
            problems=["garbage"],
        )
        assert not s.is_acceptable


class TestTextEvaluator:
    def setup_method(self):
        self.eval = TextEvaluator()

    def test_empty_text(self):
        score = self.eval.score_heuristic("")
        assert "empty" in score.problems
        assert score.total == 0.0

    def test_good_response(self):
        text = "Hey there! How are you doing tonight? 😊 [ACTION:waves]"
        score = self.eval.score_heuristic(text)
        assert score.total > 0.4
        assert score.engagement_score > 0.5  # has question

    def test_short_response(self):
        score = self.eval.score_heuristic("ok")
        assert "too_short" in score.problems

    def test_repetitive_detection(self):
        recent = ["Hello there!", "Hello there!", "Hello there!"]
        score = self.eval.score_heuristic("Hello there!", recent_messages=recent)
        assert "repetitive" in score.problems

    def test_variety_with_different_messages(self):
        recent = ["How was your day?", "I love pizza", "The weather is nice"]
        score = self.eval.score_heuristic(
            "Want to play a game? It could be fun! 🎮",
            recent_messages=recent,
        )
        assert score.variety_score > 0.5

    def test_personality_keywords(self):
        eval_with_kw = TextEvaluator(personality_keywords={"rebel", "bold", "daring"})
        score = eval_with_kw.score_heuristic(
            "I'm feeling bold and daring tonight! Let's do something rebel-like!"
        )
        assert score.personality_score > 0.5

    def test_token_artifacts_detected(self):
        text = "<|begin_of_text|>Hello there!<|end_of_text|>"
        score = self.eval.score_heuristic(text)
        assert "token_artifacts" in score.problems

    def test_garbage_detection(self):
        assert self.eval.is_garbage("")
        assert self.eval.is_garbage("  ")
        assert self.eval.is_garbage("ab")
        assert self.eval.is_garbage("...")
        assert not self.eval.is_garbage("Hello!")

    def test_detect_problems_shortcut(self):
        problems = self.eval.detect_problems("")
        assert "empty" in problems

    def test_engagement_with_question(self):
        score = self.eval.score_heuristic("What do you think about that?")
        assert score.engagement_score > 0.5

    def test_engagement_without_question(self):
        score = self.eval.score_heuristic("I think that is fine.")
        assert score.engagement_score <= 0.5

    def test_expressiveness_with_emoji(self):
        score = self.eval.score_heuristic("Let's go! 🎉🔥")
        assert score.expressiveness > 0.5


class TestImageScore:
    def test_total_weighted(self):
        s = ImageScore(quality=1.0, relevance=1.0)
        assert s.total == pytest.approx(1.0)

    def test_is_acceptable(self):
        s = ImageScore(quality=0.7, relevance=0.7)
        assert s.is_acceptable

    def test_low_score_not_acceptable(self):
        s = ImageScore(quality=0.1, relevance=0.1)
        assert not s.is_acceptable


class TestSingleton:
    def test_get_text_evaluator_returns_same_instance(self):
        a = get_text_evaluator()
        b = get_text_evaluator()
        assert a is b
