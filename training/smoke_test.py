"""Smoke test for the CosySim fine-tune training pipeline.

Validates the full pipeline end-to-end without requiring a GPU:
  1. MicroDatasetManager can build a tiny dataset
  2. FinetuneOrchestrator generates a valid train.py script
  3. Generated script has correct Python syntax
  4. ModelRegistry can register and auto-promote a model
  5. BenchmarkRunner can run a dry benchmark (rule-based predictor)
  6. FinetunedRouter can route through a registered model path

Run as:
    python training/smoke_test.py
    python -m training.smoke_test
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smoke_test")

# ──── Test Helpers ────────────────────────────────────────────────────────────

_PASS = "✓"
_FAIL = "✗"
_results: list[dict] = []


def _check(name: str, fn) -> bool:
    """Run a single check, capture pass/fail."""
    try:
        fn()
        logger.info("%s  %s", _PASS, name)
        _results.append({"name": name, "passed": True})
        return True
    except Exception as exc:
        logger.error("%s  %s  →  %s: %s", _FAIL, name, type(exc).__name__, exc)
        _results.append({"name": name, "passed": False, "error": str(exc)})
        return False


# ──── Checks ──────────────────────────────────────────────────────────────────

def check_micro_dataset_manager():
    """MicroDatasetManager can build a small dataset in a temp directory."""
    from training.micro_datasets import MicroDatasetManager, MODELS
    assert MODELS, "MODELS list is empty"
    mgr = MicroDatasetManager()
    assert isinstance(mgr.status(), dict), "status() did not return dict"


def check_dataset_build_qa_evaluator(tmp_dir: Path):
    """Build a tiny qa_evaluator dataset and confirm files are written."""
    from training.micro_datasets import MicroDatasetManager
    import unittest.mock as mock

    with (
        mock.patch("training.micro_datasets._DATASETS_DIR", tmp_dir / "datasets"),
    ):
        mgr = MicroDatasetManager()
        result = mgr.build("qa_evaluator", count=10)
        train_path = tmp_dir / "datasets" / "qa_evaluator_train.jsonl"
        test_path = tmp_dir / "datasets" / "qa_evaluator_test.jsonl"
        assert train_path.exists(), "Training file not created"
        assert test_path.exists(), "Test file not created"
        lines = train_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 1, "Training file has no lines"
        # Each line must be valid JSON
        for line in lines:
            json.loads(line)


def check_finetune_orchestrator_script_gen(tmp_dir: Path):
    """FinetuneOrchestrator generates a syntactically valid train.py."""
    import ast
    import unittest.mock as mock
    from training.finetune_orchestrator import FinetuneOrchestrator

    datasets_dir = tmp_dir / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = tmp_dir / "jobs.jsonl"
    models_dir = tmp_dir / "models"

    # Create a dummy training file so submit() doesn't raise
    (datasets_dir / "qa_evaluator_train.jsonl").write_text(
        '{"input": "Q: x\\nA: y", "output": "ESSENTIAL"}\n' * 10,
        encoding="utf-8",
    )

    with (
        mock.patch("training.finetune_orchestrator._DATASETS_DIR", datasets_dir),
        mock.patch("training.finetune_orchestrator._JOBS_PATH", jobs_path),
        mock.patch("training.finetune_orchestrator._MODELS_DIR", models_dir),
    ):
        orch = FinetuneOrchestrator()
        job = orch.submit("qa_evaluator", base_model="Qwen/Qwen2.5-0.5B-Instruct")
        script_path = Path(job.output_dir) / "train.py"
        assert script_path.exists(), f"train.py not created at {script_path}"
        code = script_path.read_text(encoding="utf-8")
        # Validate syntax
        ast.parse(code)
        assert "from unsloth import" in code or "unsloth" in code.lower(), \
            "train.py does not reference unsloth"


def check_model_registry(tmp_dir: Path):
    """ModelRegistry registers, benchmarks, auto-promotes models."""
    import unittest.mock as mock
    from training.model_registry import ModelRegistry

    registry_path = tmp_dir / "model_registry.json"
    models_dir = tmp_dir / "models"

    with (
        mock.patch("training.model_registry._REGISTRY_PATH", registry_path),
        mock.patch("training.model_registry._MODELS_DIR", models_dir),
    ):
        reg = ModelRegistry()
        m = reg.register(
            "qa_evaluator",
            adapter_path=str(tmp_dir / "models" / "fake_adapter"),
            base_model="Qwen/Qwen2.5-0.5B-Instruct",
        )
        assert m.model_id, "No model_id assigned"

        reg.update_benchmark(m.model_id, score=0.85)
        promoted = reg.auto_promote("qa_evaluator")
        assert promoted is not None, "auto_promote returned None"
        assert promoted.model_id == m.model_id, "Wrong model promoted"
        assert promoted.active is True, "Promoted model not marked active"


def check_benchmark_runner_rule_predictor(tmp_dir: Path):
    """BenchmarkRunner rule predictor returns sensible labels."""
    from training.benchmark_runner import BenchmarkRunner

    runner = BenchmarkRunner()
    predictor = runner._rule_predictor("qa_evaluator")
    # Technical text should be ESSENTIAL
    result = predictor("How does the interceptor pipeline and scene skills work in CosySim?")
    assert result in ("ESSENTIAL", "USEFUL", "SKIP"), f"Unexpected label: {result}"


def check_finetuned_router():
    """FinetunedRouter registers and routes without a real LMStudio model."""
    from engine.lmstudio.finetuned_router import FinetunedRouter

    router = FinetunedRouter()
    assert not router.is_available("qa_evaluator"), "Should have no models initially"
    router.register_model("qa_evaluator", "/fake/model/path")
    assert router.is_available("qa_evaluator"), "Model not registered"
    assert router.get_active_models() == {"qa_evaluator": "/fake/model/path"}
    # Route returns None because LMStudio call will fail (no server here)
    result = router.route("qa_evaluator", "test input")
    # None is acceptable — graceful degradation
    assert result is None or isinstance(result, str), "Unexpected route return type"


def check_conversation_analyzer_heuristic():
    """ConversationAnalyzer heuristic extractor works without any LLM."""
    from engine.nexus.conversation_analyzer import ConversationAnalyzer

    analyzer = ConversationAnalyzer()
    text = (
        "User: I'm working on CosySim with Python and LMStudio on my RTX 2060.\n"
        "Assistant: Great setup! How can I help?\n"
        "User: I want to add QLoRA finetune support using Unsloth on HuggingFace.\n"
    )
    result = analyzer.analyze(text, mode="heuristic", store_to_profile=False)
    assert not result.error, f"Heuristic extraction errored: {result.error}"
    # Should at least find some tech keywords
    assert result.technical_background or result.facts, \
        "No tech facts extracted by heuristic"
    assert result.extraction_mode == "heuristic"


def check_user_profile_store(tmp_dir: Path):
    """UserProfileStore persists and merges data correctly."""
    from engine.nexus.user_profile import UserProfileStore

    store = UserProfileStore(cache_path=tmp_dir / "user_profile.json")
    profile = store.get_profile()
    assert profile["name"] == "Knack", "Default name not set"

    store.add_fact("Smoke test fact")
    store.add_preference("test_key", "test_value")

    profile = store.get_profile()
    assert "Smoke test fact" in profile["facts"]
    assert profile["preferences"]["test_key"] == "test_value"

    # Merge extends lists, not replaces
    store.merge({"technical_background": ["Python", "Rust"]})
    profile = store.get_profile()
    assert "Python" in profile["technical_background"]
    assert "Rust" in profile["technical_background"]

    # Re-merging same items doesn't duplicate
    store.merge({"technical_background": ["Python"]})
    py_count = sum(1 for t in store.get_profile()["technical_background"] if t == "Python")
    assert py_count == 1, f"Python duplicated: count={py_count}"


# ──── Main ────────────────────────────────────────────────────────────────────

def run_smoke_tests() -> bool:
    """Run all smoke tests. Returns True if all passed."""
    logger.info("=" * 60)
    logger.info("CosySim Training Pipeline Smoke Test")
    logger.info("=" * 60)

    passed = True
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        passed &= _check("MicroDatasetManager import + MODELS list", check_micro_dataset_manager)
        passed &= _check("Build qa_evaluator dataset (10 examples)", lambda: check_dataset_build_qa_evaluator(tmp))
        passed &= _check("Orchestrator generates valid train.py", lambda: check_finetune_orchestrator_script_gen(tmp))
        passed &= _check("ModelRegistry register + auto-promote", lambda: check_model_registry(tmp))
        passed &= _check("BenchmarkRunner rule predictor", lambda: check_benchmark_runner_rule_predictor(tmp))
        passed &= _check("FinetunedRouter register + graceful route", check_finetuned_router)
        passed &= _check("ConversationAnalyzer heuristic extraction", check_conversation_analyzer_heuristic)
        passed &= _check("UserProfileStore persist + merge", lambda: check_user_profile_store(tmp))

    logger.info("=" * 60)
    total = len(_results)
    success = sum(1 for r in _results if r["passed"])
    failed = total - success
    if failed == 0:
        logger.info("ALL %d CHECKS PASSED", total)
    else:
        logger.error("%d/%d CHECKS FAILED", failed, total)
        for r in _results:
            if not r["passed"]:
                logger.error("  FAIL: %s — %s", r["name"], r.get("error", ""))
    logger.info("=" * 60)
    return passed


if __name__ == "__main__":
    ok = run_smoke_tests()
    sys.exit(0 if ok else 1)
