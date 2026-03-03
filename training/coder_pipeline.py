"""CosySim Coder Model Pipeline — end-to-end lifecycle: dataset → train → eval → promote → deploy."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CODER_DATASET_PATH = Path("training/datasets/coder_train.jsonl")
_CODER_MODEL_TYPE = "coder"
_COLLECTED_DIR = Path("training/datasets/collected")


@dataclass
class CoderStatus:
    """Full status snapshot of the coder model pipeline."""

    dataset_size: int
    last_dataset_refresh: Optional[str]
    active_job_id: Optional[str]
    active_job_status: Optional[str]
    active_model_id: Optional[str]
    best_score: float
    train_threshold: int
    ready_to_train: bool
    lmstudio_loaded: bool


class CoderPipeline:
    """Manages the full lifecycle of the CosySim coder model."""

    def build_dataset(self, force: bool = False) -> int:
        """Run all generate_coder strategies, flush data_collector, return total examples.

        Args:
            force: Rebuild even if dataset already exists.

        Returns:
            Total number of examples in the dataset.
        """
        if not force and _CODER_DATASET_PATH.exists():
            # Still merge collected data even if not rebuilding from scratch
            self._merge_collected()
            return self._count_examples(_CODER_DATASET_PATH)

        # 1. Run generate_coder strategies
        try:
            from training.datasets.generate_coder import main as gen_main
            gen_main()
        except Exception as e:
            logger.warning(f"generate_coder.main() failed: {e}")

        # 2. Merge collected data
        self._merge_collected()

        return self._count_examples(_CODER_DATASET_PATH)

    def _merge_collected(self) -> int:
        """Merge collected live data into coder_train.jsonl.

        Returns:
            Number of new records merged.
        """
        merged = 0
        collected_types = [_CODER_MODEL_TYPE, "coding_sessions", "nexus_code_qa"]

        existing: set = set()
        if _CODER_DATASET_PATH.exists():
            try:
                with _CODER_DATASET_PATH.open(encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                            key = rec.get("instruction", "")[:50] + rec.get("input", "")[:100]
                            existing.add(key)
                        except Exception:
                            pass
            except Exception:
                pass

        new_records: list = []
        for ct in collected_types:
            live_path = _COLLECTED_DIR / f"{ct}_live.jsonl"
            if not live_path.exists():
                continue
            try:
                with live_path.open(encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                            instruction = rec.get("instruction", _CODER_MODEL_TYPE)
                            inp = rec.get("input", rec.get("input_text", ""))
                            out = rec.get("output", rec.get("output_text", ""))
                            if not inp or not out:
                                continue
                            key = instruction[:50] + inp[:100]
                            if key not in existing:
                                existing.add(key)
                                new_records.append({
                                    "instruction": instruction,
                                    "input": inp,
                                    "output": out,
                                    "model_type": "coder",
                                    "strategy": "collected",
                                    "source_file": "",
                                    "convention_type": None,
                                })
                                merged += 1
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Could not read {live_path}: {e}")

        if new_records:
            _CODER_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _CODER_DATASET_PATH.open("a", encoding="utf-8") as f:
                for rec in new_records:
                    f.write(json.dumps(rec) + "\n")
            logger.info(f"Merged {merged} collected examples into coder dataset")

        return merged

    def _count_examples(self, path: Path) -> int:
        """Count lines in a JSONL file.

        Args:
            path: Path to the JSONL file.

        Returns:
            Number of non-empty lines.
        """
        if not path.exists():
            return 0
        try:
            with path.open(encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def check_and_train(self, force: bool = False) -> Optional[str]:
        """Check if threshold met, submit finetune job.

        Args:
            force: Submit even if below threshold.

        Returns:
            job_id if submitted, None otherwise.
        """
        from training.model_zoo import get_spec
        spec = get_spec(_CODER_MODEL_TYPE)
        count = self._count_examples(_CODER_DATASET_PATH)

        if not force and count < spec.train_threshold:
            logger.info(
                f"Coder dataset has {count} examples, threshold is {spec.train_threshold} — not training yet"
            )
            return None

        try:
            from training.finetune_orchestrator import get_finetune_orchestrator
            orch = get_finetune_orchestrator()
            job = orch.submit(
                _CODER_MODEL_TYPE,
                lora_overrides=spec.lora_overrides,
            )
            job_id = job.job_id
            logger.info(f"Submitted coder finetune job: {job_id}")

            # Store in Nexus
            try:
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                client.add_entry(
                    title=f"Coder Training Job: {job_id}",
                    content=f"Submitted coder finetune job with {count} examples.",
                    content_type="history",
                    category="training",
                )
            except Exception:
                pass

            return job_id
        except Exception as e:
            logger.error(f"Failed to submit coder finetune job: {e}")
            return None

    def run_next_job(self) -> Optional[Dict[str, Any]]:
        """Run the next pending coder job if any.

        Returns:
            Job result dict or None.
        """
        try:
            from training.finetune_orchestrator import get_finetune_orchestrator
            orch = get_finetune_orchestrator()
            jobs = orch.list_jobs(model_type=_CODER_MODEL_TYPE, status="pending")
            if not jobs:
                return None
            result = orch.run_next()
            return result
        except Exception as e:
            logger.error(f"run_next_job failed: {e}")
            return None

    def evaluate(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Run BenchmarkRunner on a completed coder job.

        Args:
            job_id: Optional specific job to evaluate. Uses latest completed if None.

        Returns:
            Dict with score, accuracy, samples.
        """
        try:
            from training.benchmark_runner import get_benchmark_runner
            runner = get_benchmark_runner()
            result = runner.run(_CODER_MODEL_TYPE, auto_promote=False)
            return {
                "score": result.aggregate_score,
                "accuracy": result.accuracy,
                "samples": result.total_examples,
                "model_id": result.model_id,
                "job_id": job_id,
            }
        except Exception as e:
            logger.error(f"evaluate failed: {e}")
            return {"score": 0.0, "accuracy": 0.0, "samples": 0, "error": str(e)}

    def promote(self, job_id: str, force: bool = False) -> bool:
        """Promote model if benchmark score improved.

        Args:
            job_id: The finetune job ID to evaluate and promote.
            force: Promote even if score didn't improve.

        Returns:
            True if promoted.
        """
        try:
            from training.benchmark_runner import get_benchmark_runner
            runner = get_benchmark_runner()
            result = runner.run(_CODER_MODEL_TYPE, auto_promote=True)
            promoted = result.promoted or force
            if promoted:
                logger.info(f"Coder model promoted: job={job_id} score={result.aggregate_score:.3f}")
            return promoted
        except Exception as e:
            logger.error(f"promote failed: {e}")
            return False

    def full_cycle(self) -> Dict[str, Any]:
        """Build dataset → train → evaluate → promote in one call.

        Returns:
            Dict with cycle results.
        """
        result: Dict[str, Any] = {}

        # 1. Build dataset
        count = self.build_dataset()
        result["dataset_size"] = count

        # 2. Train if ready
        job_id = self.check_and_train()
        result["job_id"] = job_id

        if job_id:
            # 3. Run job
            self.run_next_job()

            # 4. Evaluate
            eval_result = self.evaluate(job_id)
            result["eval"] = eval_result

            # 5. Promote if improved
            promoted = self.promote(job_id)
            result["promoted"] = promoted

        return result

    def deploy_to_lmstudio(self, model_id: str) -> bool:
        """Load promoted model in LMStudio for inference.

        Args:
            model_id: The model identifier to load.

        Returns:
            True if loaded successfully.
        """
        try:
            import lmstudio
            client = lmstudio.Client()
            client.llm.load(model_id)
            logger.info(f"Loaded coder model in LMStudio: {model_id}")
            return True
        except Exception as e:
            logger.warning(f"Could not load model in LMStudio: {e}")
            return False

    def status(self) -> CoderStatus:
        """Get full coder pipeline status.

        Returns:
            CoderStatus dataclass.
        """
        from training.model_zoo import get_spec
        spec = get_spec(_CODER_MODEL_TYPE)
        count = self._count_examples(_CODER_DATASET_PATH)

        # Get last refresh time from file mtime
        last_refresh = None
        if _CODER_DATASET_PATH.exists():
            mtime = _CODER_DATASET_PATH.stat().st_mtime
            last_refresh = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        # Get active job info
        active_job_id = None
        active_job_status = None
        try:
            from training.finetune_orchestrator import get_finetune_orchestrator
            orch = get_finetune_orchestrator()
            running = orch.list_jobs(model_type=_CODER_MODEL_TYPE, status="running")
            if running:
                active_job_id = running[0].job_id
                active_job_status = running[0].status
            else:
                pending = orch.list_jobs(model_type=_CODER_MODEL_TYPE, status="pending")
                if pending:
                    active_job_id = pending[0].job_id
                    active_job_status = pending[0].status
        except Exception:
            pass

        # Get best score from registry
        best_score = 0.0
        active_model_id = None
        try:
            from training.model_registry import get_model_registry
            registry = get_model_registry()
            active = registry.get_active(_CODER_MODEL_TYPE)
            if active:
                active_model_id = active.get("model_id")
                best_score = active.get("score", 0.0)
        except Exception:
            pass

        # Check if loaded in LMStudio
        lmstudio_loaded = False
        try:
            from engine.lmstudio.client import get_lmstudio_client
            client = get_lmstudio_client()
            models = client.list_models()
            lmstudio_loaded = any("coder" in str(m).lower() for m in models)
        except Exception:
            pass

        return CoderStatus(
            dataset_size=count,
            last_dataset_refresh=last_refresh,
            active_job_id=active_job_id,
            active_job_status=active_job_status,
            active_model_id=active_model_id,
            best_score=best_score,
            train_threshold=spec.train_threshold,
            ready_to_train=count >= spec.train_threshold,
            lmstudio_loaded=lmstudio_loaded,
        )

    def refresh_dataset(self) -> int:
        """Force rebuild dataset from scratch.

        Returns:
            Total examples after rebuild.
        """
        return self.build_dataset(force=True)


# ──── Singleton ────

_pipeline: Optional[CoderPipeline] = None
_pipeline_lock = threading.Lock()


def get_coder_pipeline() -> CoderPipeline:
    """Get or create the singleton CoderPipeline.

    Returns:
        The singleton CoderPipeline instance.
    """
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = CoderPipeline()
    return _pipeline
