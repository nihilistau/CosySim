"""Tests for router_v3 benchmark support in BenchmarkRunner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from training.benchmark_runner import BenchmarkRunner, get_benchmark_runner
from training.micro_datasets import MODELS

_TEST_DATASET = Path("training/datasets/router_v3_test.jsonl")
_VALID_CLASSES = {
    "small_talk", "game_action", "story_narrative", "character_emotion",
    "world_query", "skill_call", "memory_recall", "scene_transition",
    "system_command", "creative_generation", "information_lookup",
    "emotional_support", "adult_content", "combat_narrative",
    "economic_action", "investigation",
}


# ──── Test dataset ────────────────────────────────────────────────────────────

class TestRouterV3TestDataset:
    def test_file_exists(self) -> None:
        assert _TEST_DATASET.exists(), f"Missing: {_TEST_DATASET}"

    def test_minimum_50_examples(self) -> None:
        with open(_TEST_DATASET, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) >= 50, f"Only {len(lines)} examples (need >= 50)"

    def test_alpaca_format(self) -> None:
        with open(_TEST_DATASET, encoding="utf-8") as f:
            first = json.loads(f.readline())
        assert "instruction" in first
        assert "input" in first
        assert "output" in first

    def test_outputs_are_valid_classes(self) -> None:
        with open(_TEST_DATASET, encoding="utf-8") as f:
            examples = [json.loads(l) for l in f if l.strip()]
        invalid = [e["output"] for e in examples if e["output"] not in _VALID_CLASSES]
        assert not invalid, f"Invalid class labels found: {set(invalid)}"


# ──── Model type registration ─────────────────────────────────────────────────

class TestRouterV3InModelsList:
    def test_router_v3_in_models(self) -> None:
        assert "router_v3" in MODELS, f"router_v3 missing from MODELS: {MODELS}"


# ──── Rule predictor ──────────────────────────────────────────────────────────

@pytest.fixture()
def runner() -> BenchmarkRunner:
    return BenchmarkRunner()


class TestRouterV3RulePredictor:
    def _predict(self, runner: BenchmarkRunner, text: str) -> str:
        predictor = runner._rule_predictor("router_v3")
        return predictor(text)

    def test_returns_valid_class(self, runner: BenchmarkRunner) -> None:
        result = self._predict(runner, "What is the capital city?")
        assert result in _VALID_CLASSES

    def test_small_talk(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "hey, how are you?") == "small_talk"

    def test_game_action(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "attack the dragon") == "game_action"

    def test_story_narrative(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "tell me what happened in the last scene") == "story_narrative"

    def test_character_emotion(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "she feels sad and scared today") == "character_emotion"

    def test_world_query(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "who rules the northern faction?") == "world_query"

    def test_memory_recall(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "recall what we discussed before") == "memory_recall"

    def test_scene_transition(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "go to the tavern") == "scene_transition"

    def test_system_command(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "save my progress") == "system_command"

    def test_creative_generation(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "generate a poem about the war") == "creative_generation"

    def test_information_lookup(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "what is the loot drop rate?") == "information_lookup"

    def test_economic_action(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "buy 10 credits at the market") == "economic_action"

    def test_investigation(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "investigate the clue near the door") == "investigation"

    def test_adult_content(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "show me explicit content") == "adult_content"

    def test_combat_narrative(self, runner: BenchmarkRunner) -> None:
        assert self._predict(runner, "report the war combat involving troops") == "combat_narrative"

    def test_default_fallback(self, runner: BenchmarkRunner) -> None:
        result = self._predict(runner, "random unclassifiable gibberish zzz")
        assert result == "information_lookup"


# ──── BenchmarkRunner integration ────────────────────────────────────────────

class TestBenchmarkRunnerRouterV3:
    def test_run_returns_result_with_test_data(self, tmp_path: Path) -> None:
        """BenchmarkRunner.run() works for router_v3 with a mock registry."""
        mock_model = MagicMock()
        mock_model.model_id = "router_v3_test_model"

        mock_registry = MagicMock()
        mock_registry.get_active.return_value = mock_model
        mock_registry.list_models.return_value = [{"model_id": "router_v3_test_model"}]
        mock_registry.auto_promote.return_value = None

        with patch("training.benchmark_runner._DATASETS_DIR", Path("training/datasets")):
            with patch("training.model_registry.get_model_registry", return_value=mock_registry):
                with patch("training.benchmark_runner.BenchmarkRunner._store_in_nexus"):
                    with patch("training.benchmark_runner._BENCHMARKS_PATH", tmp_path / "bench.jsonl"):
                        br = BenchmarkRunner()
                        result = br.run("router_v3", auto_promote=False, use_lmstudio=False)

        assert result.model_type == "router_v3"
        assert result.total_examples >= 50
        assert result.error is None
        assert 0.0 <= result.accuracy <= 1.0
