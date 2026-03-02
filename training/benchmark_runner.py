"""Benchmark Runner — auto-benchmarks fine-tuned micro-models on held-out test sets.

Runs each model against its test split, computes accuracy/F1/exact-match,
stores results in ModelRegistry and Nexus, and auto-promotes if score improves.

Usage::
    from training.benchmark_runner import get_benchmark_runner
    runner = get_benchmark_runner()
    result = runner.run("qa_evaluator")
    runner.run_all()
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_BENCHMARKS_PATH = Path("training/benchmarks.jsonl")
_DATASETS_DIR = Path("training/datasets")


# ──── Result Models ───────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Result of a single model benchmark run."""
    model_id: str
    model_type: str
    accuracy: float
    f1: float
    exact_match: float
    total_examples: int
    correct: int
    latency_ms_avg: float
    aggregate_score: float
    breakdown: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    promoted: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        return (
            f"{self.model_type}/{self.model_id}: "
            f"acc={self.accuracy:.3f} f1={self.f1:.3f} "
            f"exact={self.exact_match:.3f} score={self.aggregate_score:.3f} "
            f"latency={self.latency_ms_avg:.0f}ms"
        )


class BenchmarkRunner:
    """Runs held-out test benchmarks against fine-tuned micro-models."""

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        model_type: str,
        auto_promote: bool = True,
        use_lmstudio: bool = True,
    ) -> BenchmarkResult:
        """Benchmark the currently active model for a type.

        Args:
            model_type: Micro-model type to benchmark.
            auto_promote: Auto-promote if score improves over current active.
            use_lmstudio: Use LMStudio inference (falls back to local logic).

        Returns:
            BenchmarkResult with scores.
        """
        from training.model_registry import get_model_registry
        registry = get_model_registry()
        model = registry.get_active(model_type)

        if model is None:
            # Try to find any registered model
            all_models = registry.list_models(model_type=model_type)
            if not all_models:
                return BenchmarkResult(
                    model_id="none",
                    model_type=model_type,
                    accuracy=0.0, f1=0.0, exact_match=0.0,
                    total_examples=0, correct=0, latency_ms_avg=0.0,
                    aggregate_score=0.0,
                    error="No registered model found",
                )
            # Use the latest
            model_dict = all_models[0]
            model_id = model_dict["model_id"]
        else:
            model_id = model.model_id

        test_path = _DATASETS_DIR / f"{model_type}_test.jsonl"
        if not test_path.exists():
            return BenchmarkResult(
                model_id=model_id,
                model_type=model_type,
                accuracy=0.0, f1=0.0, exact_match=0.0,
                total_examples=0, correct=0, latency_ms_avg=0.0,
                aggregate_score=0.0,
                error=f"Test dataset not found: {test_path}",
            )

        examples = self._load_test_set(test_path)
        if not examples:
            return BenchmarkResult(
                model_id=model_id,
                model_type=model_type,
                accuracy=0.0, f1=0.0, exact_match=0.0,
                total_examples=0, correct=0, latency_ms_avg=0.0,
                aggregate_score=0.0,
                error="Test set is empty",
            )

        logger.info("Benchmarking %s/%s on %d examples...", model_type, model_id, len(examples))
        result = self._run_benchmark(model_id, model_type, examples, use_lmstudio)

        # Update registry
        registry.update_benchmark(model_id, result.aggregate_score, result.breakdown)

        # Auto-promote
        if auto_promote:
            promoted_model = registry.auto_promote(model_type)
            if promoted_model and promoted_model.model_id == model_id:
                result.promoted = True

        # Persist
        self._persist(result)
        self._store_in_nexus(result)
        logger.info(result.summary())
        return result

    def run_all(self, auto_promote: bool = True) -> List[BenchmarkResult]:
        """Run benchmarks for all micro-model types.

        Args:
            auto_promote: Auto-promote best models after benchmarking.

        Returns:
            List of BenchmarkResult.
        """
        from training.micro_datasets import MODELS
        results = []
        for model_type in MODELS:
            try:
                result = self.run(model_type, auto_promote=auto_promote)
                results.append(result)
            except Exception as exc:
                logger.error("Benchmark failed for %s: %s", model_type, exc)
        return results

    def get_history(
        self, model_type: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Return benchmark history from disk.

        Args:
            model_type: Filter by type.
            limit: Max results.

        Returns:
            List of benchmark result dicts.
        """
        if not _BENCHMARKS_PATH.exists():
            return []
        entries = []
        for line in _BENCHMARKS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if model_type is None or d.get("model_type") == model_type:
                    entries.append(d)
            except json.JSONDecodeError:
                pass
        return sorted(entries, key=lambda e: e.get("timestamp", ""), reverse=True)[:limit]

    def get_leaderboard(self) -> Dict[str, Any]:
        """Return best score per model type."""
        from training.micro_datasets import MODELS
        board: Dict[str, Any] = {}
        for model_type in MODELS:
            history = self.get_history(model_type=model_type, limit=100)
            if history:
                best = max(history, key=lambda e: e.get("aggregate_score", 0.0))
                board[model_type] = {
                    "best_score": best.get("aggregate_score"),
                    "model_id": best.get("model_id"),
                    "timestamp": best.get("timestamp"),
                }
            else:
                board[model_type] = {"best_score": None, "model_id": None, "timestamp": None}
        return board

    # ── Private ───────────────────────────────────────────────────────────────

    def _load_test_set(self, path: Path) -> List[Dict[str, Any]]:
        examples = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return examples

    def _run_benchmark(
        self,
        model_id: str,
        model_type: str,
        examples: List[Dict[str, Any]],
        use_lmstudio: bool,
    ) -> BenchmarkResult:
        """Run inference on test examples and compute metrics."""
        correct = 0
        exact_matches = 0
        latencies: List[float] = []
        f1_scores: List[float] = []

        predictor = self._get_predictor(model_type, model_id, use_lmstudio)

        for ex in examples:
            inp = ex.get("input", "")
            expected = ex.get("output", "").strip().lower()

            t0 = time.time()
            try:
                predicted = predictor(inp).strip().lower()
            except Exception as exc:
                logger.debug("Inference error on example: %s", exc)
                predicted = ""
            latency_ms = (time.time() - t0) * 1000
            latencies.append(latency_ms)

            # Exact match
            if predicted == expected:
                exact_matches += 1
                correct += 1

            # F1 score (token overlap)
            f1 = self._token_f1(predicted, expected)
            f1_scores.append(f1)

        n = len(examples)
        accuracy = correct / n if n > 0 else 0.0
        exact_match = exact_matches / n if n > 0 else 0.0
        avg_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        # Aggregate: weighted combo
        aggregate = 0.4 * accuracy + 0.4 * avg_f1 + 0.2 * exact_match

        return BenchmarkResult(
            model_id=model_id,
            model_type=model_type,
            accuracy=round(accuracy, 4),
            f1=round(avg_f1, 4),
            exact_match=round(exact_match, 4),
            total_examples=n,
            correct=correct,
            latency_ms_avg=round(avg_latency, 1),
            aggregate_score=round(aggregate, 4),
            breakdown={
                "f1_scores_sample": f1_scores[:10],
                "latency_p95": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            },
        )

    def _get_predictor(
        self, model_type: str, model_id: str, use_lmstudio: bool
    ):
        """Return a callable that takes input text and returns predicted output."""
        if use_lmstudio:
            try:
                return self._lmstudio_predictor(model_type, model_id)
            except Exception:
                pass

        # Rule-based baseline predictors for evaluation
        return self._rule_predictor(model_type)

    def _lmstudio_predictor(self, model_type: str, model_id: str):
        """Use LMStudio or finetuned router for inference."""
        from engine.lmstudio.client import get_lms_client
        client = get_lms_client()
        instructions: Dict[str, str] = {
            "qa_evaluator": "Classify as ESSENTIAL, USEFUL, or SKIP:",
            "router_v2": "Route this request to the correct handler (one word):",
            "router_v3": "Classify this request into exactly one category. Respond with one word only:",
            "syntax_fixer": "Fix the syntax error. Return only the corrected code:",
            "conversation_analyzer": "Extract user facts as JSON:",
            "knowledge_synthesizer": "Synthesize a concise answer from the context:",
        }
        instr = instructions.get(model_type, "Complete:")

        def predict(inp: str) -> str:
            prompt = f"{instr}\n{inp}"
            result = client.complete(prompt, max_tokens=50, temperature=0.0)
            return result.get("text", "") if isinstance(result, dict) else str(result)
        return predict

    def _rule_predictor(self, model_type: str):
        """Simple rule-based predictor as a baseline."""
        def predict_qa(inp: str) -> str:
            generic_words = {"help", "something", "anything", "what", "how are you"}
            words = set(inp.lower().split())
            if len(words & generic_words) > 2 or len(inp) < 20:
                return "SKIP"
            tech_words = {"scene", "skill", "nexus", "config", "port", "api", "model", "pipeline"}
            if words & tech_words:
                return "ESSENTIAL"
            return "USEFUL"

        def predict_router(inp: str) -> str:
            inp_lower = inp.lower()
            if any(w in inp_lower for w in ["search", "find", "look"]):
                return "nexus_search"
            if any(w in inp_lower for w in ["start", "launch", "scene"]):
                return "scene_control"
            if any(w in inp_lower for w in ["speak", "voice", "tts"]):
                return "tts_request"
            if any(w in inp_lower for w in ["backup", "save"]):
                return "backup_request"
            return "nexus_ask"

        def predict_syntax(inp: str) -> str:
            fixed = inp
            # Add missing colon
            fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
            # Close braces
            opens = fixed.count("{") - fixed.count("}")
            if opens > 0:
                fixed += "}" * opens
            return fixed

        def predict_router_v3(inp: str) -> str:
            inp_lower = inp.lower()
            if any(w in inp_lower for w in ["hi", "hello", "hey", "chat", "talk"]):
                return "small_talk"
            if any(w in inp_lower for w in ["attack", "move", "fight", "shoot", "dodge", "defend", "craft", "build"]):
                return "game_action"
            if any(w in inp_lower for w in ["story", "scene", "narrative", "describe", "tell", "wrote", "happened"]):
                return "story_narrative"
            if any(w in inp_lower for w in ["feel", "emotion", "mood", "happy", "sad", "angry", "scared", "love"]):
                return "character_emotion"
            if any(w in inp_lower for w in ["world", "lore", "faction", "history", "who rules", "government"]):
                return "world_query"
            if any(w in inp_lower for w in ["use skill", "activate", "cast", "execute", "run skill"]):
                return "skill_call"
            if any(w in inp_lower for w in ["remember", "recall", "last time", "before", "previous"]):
                return "memory_recall"
            if any(w in inp_lower for w in ["go to", "travel", "move to", "enter", "leave", "exit", "next scene"]):
                return "scene_transition"
            if any(w in inp_lower for w in ["save", "load", "backup", "config", "setting", "system", "admin"]):
                return "system_command"
            if any(w in inp_lower for w in ["write", "create", "generate", "compose", "design", "invent"]):
                return "creative_generation"
            if any(w in inp_lower for w in ["what is", "how do", "explain", "define", "look up", "search"]):
                return "information_lookup"
            if any(w in inp_lower for w in ["help me", "feeling down", "support", "advice", "comfort"]):
                return "emotional_support"
            if any(w in inp_lower for w in ["sex", "explicit", "nude", "mature", "xxx", "adult"]):
                return "adult_content"
            if any(w in inp_lower for w in ["battle", "war", "fight report", "combat", "troops"]):
                return "combat_narrative"
            if any(w in inp_lower for w in ["buy", "sell", "trade", "market", "price", "pay", "coins", "credits"]):
                return "economic_action"
            if any(w in inp_lower for w in ["investigate", "clue", "evidence", "mystery", "suspect", "case"]):
                return "investigation"
            return "information_lookup"

        def predict_generic(inp: str) -> str:
            return inp

        predictors = {
            "qa_evaluator": predict_qa,
            "router_v2": predict_router,
            "router_v3": predict_router_v3,
            "syntax_fixer": predict_syntax,
        }
        return predictors.get(model_type, predict_generic)

    def _token_f1(self, predicted: str, expected: str) -> float:
        """Compute token-level F1 score."""
        pred_tokens = set(predicted.split())
        exp_tokens = set(expected.split())
        if not pred_tokens and not exp_tokens:
            return 1.0
        if not pred_tokens or not exp_tokens:
            return 0.0
        common = pred_tokens & exp_tokens
        precision = len(common) / len(pred_tokens)
        recall = len(common) / len(exp_tokens)
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    def _persist(self, result: BenchmarkResult) -> None:
        """Append benchmark result to disk log."""
        try:
            _BENCHMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_BENCHMARKS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except Exception as exc:
            logger.debug("Benchmark persist error: %s", exc)

    def _store_in_nexus(self, result: BenchmarkResult) -> None:
        """Store benchmark result in Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"Benchmark: {result.model_type}/{result.model_id}",
                content=json.dumps(result.to_dict()),
                content_type="history",
                category="training",
            )
        except Exception as exc:
            logger.debug("Nexus store skipped: %s", exc)


# ──── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[BenchmarkRunner] = None


def get_benchmark_runner() -> BenchmarkRunner:
    """Return the shared BenchmarkRunner singleton."""
    global _instance
    if _instance is None:
        _instance = BenchmarkRunner()
    return _instance
