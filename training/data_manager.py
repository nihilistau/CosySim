"""
Training Data Manager — End-to-end pipeline for collecting, curating, and
preparing router agent training data.

Provides a unified API for users and dashboard to:
  1. Collect live data from the running pipeline (TrainingCapture)
  2. Generate synthetic seed data (generate_datasets)
  3. Import/augment from Nexus and NLM (prepare_training)
  4. Review, filter, score, and curate candidates
  5. Export prepared datasets for fine-tuning
  6. Trigger the training process itself

Usage::

    from training.data_manager import get_data_manager
    mgr = get_data_manager()
    mgr.get_pipeline_status()
    mgr.seed_datasets()
    mgr.prepare_for_training()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent
DATASETS_DIR = TRAINING_DIR / "datasets"

ROUTER_DATASETS = [
    "tag_extraction",
    "tool_routing",
    "priority_classify",
    "decision_classify",
    "response_validate",
]

_manager_instance: Optional[TrainingDataManager] = None


# ── Data Structures ────────────────────────────────────────────────

@dataclass
class PipelineStatus:
    """Current state of the training data pipeline."""
    capture_enabled: bool = False
    capture_count: int = 0
    candidates_by_dataset: Dict[str, int] = field(default_factory=dict)
    candidates_pending: int = 0
    candidates_exported: int = 0
    synthetic_counts: Dict[str, int] = field(default_factory=dict)
    live_counts: Dict[str, int] = field(default_factory=dict)
    combined_counts: Dict[str, int] = field(default_factory=dict)
    total_training_examples: int = 0
    ready_for_training: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capture_enabled": self.capture_enabled,
            "capture_count": self.capture_count,
            "candidates_by_dataset": self.candidates_by_dataset,
            "candidates_pending": self.candidates_pending,
            "candidates_exported": self.candidates_exported,
            "synthetic_counts": self.synthetic_counts,
            "live_counts": self.live_counts,
            "combined_counts": self.combined_counts,
            "total_training_examples": self.total_training_examples,
            "ready_for_training": self.ready_for_training,
        }


@dataclass
class CurationResult:
    """Result of a curation operation."""
    action: str = ""
    affected: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


# ── Main Manager ───────────────────────────────────────────────────

class TrainingDataManager:
    """Orchestrates the full training data pipeline.

    Ties together:
      - TrainingCapture (live pipeline data)
      - generate_datasets (synthetic data seeding)
      - prepare_from_live (export candidates to JSONL)
      - prepare_training (validate, combine, augment)
      - finetune_local (trigger training)
    """

    def __init__(self) -> None:
        self._metrics_db = None
        self._capture = None

    def _get_db(self):
        """Lazy-load MetricsDB."""
        if self._metrics_db is None:
            try:
                from engine.observability.metrics_db import get_metrics_db
                self._metrics_db = get_metrics_db()
            except Exception as exc:
                logger.debug("MetricsDB unavailable: %s", exc)
        return self._metrics_db

    def _get_capture(self):
        """Get the TrainingCapture instance from MetricsCollector."""
        if self._capture is None:
            try:
                from engine.observability.metrics_collector import get_metrics_collector
                collector = get_metrics_collector()
                self._capture = collector.training_capture
            except Exception:
                pass
        return self._capture

    # ── Status & Inspection ────────────────────────────────────────

    def get_pipeline_status(self) -> PipelineStatus:
        """Get complete pipeline status — candidates, datasets, readiness."""
        status = PipelineStatus()

        # Capture state
        capture = self._get_capture()
        if capture:
            status.capture_enabled = capture.enabled
            status.capture_count = capture.capture_count

        # DB candidates
        db = self._get_db()
        if db:
            try:
                stats = db.get_training_stats()
                for ds_name, ds_stats in stats.items():
                    status.candidates_by_dataset[ds_name] = ds_stats.get("total", 0)
                    status.candidates_pending += ds_stats.get("pending", 0)
                    status.candidates_exported += ds_stats.get("total", 0) - ds_stats.get("pending", 0)
            except Exception:
                pass

        # File-based datasets
        for ds in ROUTER_DATASETS:
            for suffix, target in [("train", "synthetic"), ("live", "live"), ("combined", "combined")]:
                path = DATASETS_DIR / f"{ds}_{suffix}.jsonl"
                if path.exists():
                    count = sum(1 for line in open(path, encoding="utf-8") if line.strip())
                    if target == "synthetic":
                        status.synthetic_counts[ds] = count
                    elif target == "live":
                        status.live_counts[ds] = count
                    elif target == "combined":
                        status.combined_counts[ds] = count

        # Total
        status.total_training_examples = sum(status.synthetic_counts.values()) + sum(status.live_counts.values())

        # Ready check
        min_per_dataset = 50
        status.ready_for_training = all(
            status.synthetic_counts.get(ds, 0) + status.live_counts.get(ds, 0) >= min_per_dataset
            for ds in ROUTER_DATASETS
        )

        return status

    def get_candidates(
        self,
        dataset: Optional[str] = None,
        min_quality: float = 0.0,
        exported: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get training candidates for review/curation."""
        db = self._get_db()
        if not db:
            return []
        try:
            candidates = db.get_training_candidates(
                dataset=dataset,
                min_quality=min_quality,
                exported=exported,
                limit=limit,
            )
            return candidates[offset:] if offset else candidates
        except Exception as exc:
            logger.warning("Failed to get candidates: %s", exc)
            return []

    def get_candidate_stats(self) -> Dict[str, Any]:
        """Aggregate stats about training candidates."""
        db = self._get_db()
        if not db:
            return {}
        try:
            return db.get_training_stats()
        except Exception:
            return {}

    # ── Collection Control ─────────────────────────────────────────

    def set_capture_enabled(self, enabled: bool) -> bool:
        """Enable or disable live training data capture."""
        capture = self._get_capture()
        if capture:
            capture.enabled = enabled
            logger.info("Training capture %s", "enabled" if enabled else "disabled")
            return True
        return False

    def get_capture_enabled(self) -> bool:
        """Check if live capture is currently active."""
        capture = self._get_capture()
        return capture.enabled if capture else False

    # ── Data Seeding ───────────────────────────────────────────────

    def seed_datasets(
        self,
        datasets: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, int]:
        """Generate synthetic training data for specified datasets.

        Skips datasets that already have data unless force=True.

        Returns:
            Dict mapping dataset names to example counts generated.
        """
        from training.generate_datasets import (
            gen_tag_extraction,
            gen_tool_routing,
            gen_priority,
            gen_decision,
            gen_response_validate,
        )

        generators = {
            "tag_extraction": gen_tag_extraction,
            "tool_routing": gen_tool_routing,
            "priority_classify": gen_priority,
            "decision_classify": gen_decision,
            "response_validate": gen_response_validate,
        }

        targets = datasets or ROUTER_DATASETS
        results: Dict[str, int] = {}
        DATASETS_DIR.mkdir(parents=True, exist_ok=True)

        for ds in targets:
            if ds not in generators:
                logger.warning("Unknown dataset: %s", ds)
                continue

            train_path = DATASETS_DIR / f"{ds}_train.jsonl"
            if train_path.exists() and not force:
                count = sum(1 for line in open(train_path, encoding="utf-8") if line.strip())
                results[ds] = count
                logger.info("Skipping %s (already has %d examples)", ds, count)
                continue

            try:
                count = generators[ds](str(DATASETS_DIR))
                results[ds] = count
                logger.info("Generated %d examples for %s", count, ds)
            except Exception as exc:
                logger.warning("Failed to generate %s: %s", ds, exc)
                results[ds] = 0

        return results

    # ── Curation ───────────────────────────────────────────────────

    def update_candidate_quality(
        self,
        candidate_id: int,
        quality_score: float,
        notes: str = "",
    ) -> CurationResult:
        """Update quality score for a specific candidate (user review)."""
        db = self._get_db()
        if not db:
            return CurationResult(action="update_quality", affected=0)
        try:
            db.update_quality(candidate_id, quality_score, notes)
            return CurationResult(
                action="update_quality",
                affected=1,
                details={"id": candidate_id, "new_score": quality_score},
            )
        except Exception as exc:
            return CurationResult(action="update_quality", affected=0,
                                  details={"error": str(exc)})

    def bulk_update_quality(
        self,
        candidate_ids: List[int],
        quality_score: float,
        notes: str = "",
    ) -> CurationResult:
        """Bulk update quality scores (approve/reject batch)."""
        db = self._get_db()
        if not db:
            return CurationResult(action="bulk_update", affected=0)
        count = 0
        for cid in candidate_ids:
            try:
                db.update_quality(cid, quality_score, notes)
                count += 1
            except Exception:
                pass
        return CurationResult(
            action="bulk_update",
            affected=count,
            details={"total": len(candidate_ids), "score": quality_score},
        )

    def delete_candidate(self, candidate_id: int) -> CurationResult:
        """Delete a specific candidate (bad data removal)."""
        db = self._get_db()
        if not db:
            return CurationResult(action="delete", affected=0)
        try:
            with db._cursor() as cur:
                cur.execute(
                    "DELETE FROM training_candidates WHERE id = ?",
                    (candidate_id,),
                )
                return CurationResult(action="delete", affected=cur.rowcount)
        except Exception as exc:
            return CurationResult(action="delete", affected=0,
                                  details={"error": str(exc)})

    def add_manual_example(
        self,
        dataset: str,
        input_text: str,
        output_text: str,
        quality_score: float = 1.0,
        notes: str = "manual",
    ) -> CurationResult:
        """Manually add a training example (user-created gold data)."""
        db = self._get_db()
        if not db:
            return CurationResult(action="add_manual", affected=0)
        try:
            row_id = db.store_training_candidate(
                source="manual",
                dataset=dataset,
                input_text=input_text,
                output_text=output_text,
                quality_score=quality_score,
                notes=notes,
            )
            return CurationResult(
                action="add_manual",
                affected=1,
                details={"id": row_id, "dataset": dataset},
            )
        except Exception as exc:
            return CurationResult(action="add_manual", affected=0,
                                  details={"error": str(exc)})

    # ── Export & Preparation ───────────────────────────────────────

    def export_live_candidates(
        self,
        dataset: Optional[str] = None,
        min_quality: float = 0.7,
        limit: Optional[int] = None,
    ) -> Dict[str, int]:
        """Export pending candidates from DB to _live.jsonl files."""
        from training.prepare_from_live import prepare_dataset
        try:
            total = prepare_dataset(
                dataset_name=dataset,
                min_quality=min_quality,
                limit=limit,
            )
            return {"exported": total}
        except Exception as exc:
            return {"error": str(exc)}

    def merge_datasets(self, dataset: Optional[str] = None) -> Dict[str, int]:
        """Merge synthetic + live data into combined files."""
        from training.prepare_from_live import merge_datasets
        targets = [dataset] if dataset else ROUTER_DATASETS
        results = {}
        for ds in targets:
            try:
                count = merge_datasets(ds)
                results[ds] = count
            except Exception as exc:
                results[ds] = 0
                logger.warning("Merge failed for %s: %s", ds, exc)
        return results

    def augment_from_nexus(self) -> Dict[str, Any]:
        """Pull Q&A and knowledge from Nexus as training data."""
        from training.prepare_training import augment_from_nexus
        try:
            return augment_from_nexus()
        except Exception as exc:
            return {"error": str(exc)}

    def augment_from_nlm(
        self,
        notebook_id: str = "",
        topics: Optional[List[str]] = None,
        count: int = 50,
    ) -> Dict[str, Any]:
        """Distill Q&A from NotebookLM as training data."""
        from training.prepare_training import augment_from_nlm
        try:
            return augment_from_nlm(
                notebook_id=notebook_id,
                topics=topics,
                count=count,
            )
        except Exception as exc:
            return {"error": str(exc)}

    def validate_datasets(self) -> Dict[str, Any]:
        """Validate all datasets for quality/completeness."""
        from training.prepare_training import validate_all
        try:
            report = validate_all(DATASETS_DIR)
            return {
                "ready": report.ready_for_training,
                "total_examples": report.total_examples,
                "datasets": [
                    {
                        "name": ds.name,
                        "train_count": ds.train_count,
                        "val_count": ds.val_count,
                        "valid": ds.is_valid,
                        "issues": ds.issues,
                        "warnings": ds.warnings,
                    }
                    for ds in report.datasets
                ],
            }
        except Exception as exc:
            return {"error": str(exc)}

    def create_combined_dataset(self, shuffle: bool = True) -> Dict[str, int]:
        """Create the final combined multi-task training set."""
        from training.prepare_training import create_combined_dataset
        try:
            return create_combined_dataset(DATASETS_DIR, shuffle=shuffle)
        except Exception as exc:
            return {"error": str(exc)}

    def get_training_config(self, **overrides) -> Dict[str, Any]:
        """Build training configuration for the Colab notebook."""
        from training.prepare_training import build_training_config
        return build_training_config(**overrides)

    # ── Full Pipeline ──────────────────────────────────────────────

    def prepare_for_training(
        self,
        min_quality: float = 0.7,
        augment_nexus: bool = False,
        augment_nlm: bool = False,
        nlm_notebook_id: str = "",
    ) -> Dict[str, Any]:
        """Run the full preparation pipeline end-to-end.

        Steps:
          1. Export live candidates from DB to JSONL
          2. Optionally augment from Nexus
          3. Optionally augment from NLM
          4. Merge synthetic + live datasets
          5. Create combined multi-task dataset
          6. Validate everything

        Returns:
            Summary of all steps.
        """
        results: Dict[str, Any] = {"steps": [], "success": True}
        t0 = time.time()

        # Step 1: Export live
        step1 = self.export_live_candidates(min_quality=min_quality)
        results["steps"].append({"name": "export_live", "result": step1})

        # Step 2: Nexus augment
        if augment_nexus:
            step2 = self.augment_from_nexus()
            results["steps"].append({"name": "augment_nexus", "result": step2})

        # Step 3: NLM augment
        if augment_nlm and nlm_notebook_id:
            step3 = self.augment_from_nlm(notebook_id=nlm_notebook_id)
            results["steps"].append({"name": "augment_nlm", "result": step3})

        # Step 4: Merge
        step4 = self.merge_datasets()
        results["steps"].append({"name": "merge", "result": step4})

        # Step 5: Combine
        step5 = self.create_combined_dataset()
        results["steps"].append({"name": "combine", "result": step5})

        # Step 6: Validate
        step6 = self.validate_datasets()
        results["steps"].append({"name": "validate", "result": step6})
        if isinstance(step6, dict):
            results["ready_for_training"] = step6.get("ready", False)
            results["total_examples"] = step6.get("total_examples", 0)

        results["duration_seconds"] = round(time.time() - t0, 2)
        return results

    def get_dataset_files(self) -> List[Dict[str, Any]]:
        """List all dataset files with sizes and line counts."""
        files = []
        if not DATASETS_DIR.exists():
            return files
        for path in sorted(DATASETS_DIR.glob("*.jsonl")):
            count = sum(1 for line in open(path, encoding="utf-8") if line.strip())
            files.append({
                "name": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "examples": count,
                "dataset": path.stem.rsplit("_", 1)[0] if "_" in path.stem else path.stem,
                "split": path.stem.rsplit("_", 1)[-1] if "_" in path.stem else "unknown",
            })
        return files

    def download_dataset(self, filename: str) -> Optional[Path]:
        """Get path to a dataset file for download."""
        path = DATASETS_DIR / filename
        if path.exists() and path.suffix == ".jsonl":
            return path
        return None


# ── Singleton ──────────────────────────────────────────────────────

def get_data_manager() -> TrainingDataManager:
    """Get or create the singleton TrainingDataManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = TrainingDataManager()
    return _manager_instance


# ── CLI ────────────────────────────────────────────────────────────

def main() -> None:
    """CLI for training data management."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description="Training Data Manager — collect, curate, prepare, train",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m training.data_manager status          # Pipeline overview
  python -m training.data_manager candidates      # Review live candidates
  python -m training.data_manager seed            # Generate synthetic data
  python -m training.data_manager export          # Export candidates to JSONL
  python -m training.data_manager merge           # Merge synthetic + live
  python -m training.data_manager prepare         # Full pipeline run
  python -m training.data_manager validate        # Pre-training validation
  python -m training.data_manager files           # List dataset files
  python -m training.data_manager add --dataset tool_routing \\
      --input "scene=bedroom" --output '{"name":"search"}'
""",
    )
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show training pipeline status")

    # candidates
    p_cand = sub.add_parser("candidates", help="List training candidates")
    p_cand.add_argument("--dataset", help="Filter by dataset name")
    p_cand.add_argument("--min-quality", type=float, default=0.0)
    p_cand.add_argument("--limit", type=int, default=20)
    p_cand.add_argument("--pending", action="store_true",
                        help="Show only unexported candidates")

    # seed
    p_seed = sub.add_parser("seed", help="Generate synthetic training data")
    p_seed.add_argument("--datasets", nargs="*", help="Specific datasets")
    p_seed.add_argument("--force", action="store_true",
                        help="Regenerate even if data exists")

    # export
    p_export = sub.add_parser("export", help="Export candidates to JSONL")
    p_export.add_argument("--dataset", help="Specific dataset")
    p_export.add_argument("--min-quality", type=float, default=0.7)

    # merge
    p_merge = sub.add_parser("merge", help="Merge synthetic + live datasets")
    p_merge.add_argument("--dataset", help="Specific dataset")

    # prepare
    p_prep = sub.add_parser("prepare", help="Full preparation pipeline")
    p_prep.add_argument("--min-quality", type=float, default=0.7)
    p_prep.add_argument("--augment-nexus", action="store_true")
    p_prep.add_argument("--augment-nlm", action="store_true")
    p_prep.add_argument("--nlm-notebook", default="")

    # validate
    sub.add_parser("validate", help="Validate datasets for training")

    # files
    sub.add_parser("files", help="List dataset files")

    # add
    p_add = sub.add_parser("add", help="Add a manual training example")
    p_add.add_argument("--dataset", required=True)
    p_add.add_argument("--input", required=True, dest="input_text")
    p_add.add_argument("--output", required=True, dest="output_text")
    p_add.add_argument("--quality", type=float, default=1.0)
    p_add.add_argument("--notes", default="manual_cli")

    # capture
    p_cap = sub.add_parser("capture", help="Toggle live capture")
    p_cap.add_argument("action", choices=["on", "off", "status"])

    args = parser.parse_args()
    mgr = get_data_manager()

    if args.command == "status":
        status = mgr.get_pipeline_status()
        d = status.to_dict()
        print("\n📊 Training Data Pipeline Status")
        print("=" * 50)
        print(f"  Capture enabled:  {d['capture_enabled']}")
        print(f"  Capture count:    {d['capture_count']}")
        print(f"  Pending export:   {d['candidates_pending']}")
        print(f"  Already exported: {d['candidates_exported']}")
        print(f"  Total examples:   {d['total_training_examples']}")
        print(f"  Ready to train:   {'✅' if d['ready_for_training'] else '❌'}")
        if d["candidates_by_dataset"]:
            print("\n  Candidates by dataset:")
            for ds, count in d["candidates_by_dataset"].items():
                print(f"    {ds}: {count}")
        if d["synthetic_counts"]:
            print("\n  Synthetic data:")
            for ds, count in d["synthetic_counts"].items():
                print(f"    {ds}: {count}")
        if d["live_counts"]:
            print("\n  Live data:")
            for ds, count in d["live_counts"].items():
                print(f"    {ds}: {count}")

    elif args.command == "candidates":
        exp_flag = False if args.pending else None
        candidates = mgr.get_candidates(
            dataset=args.dataset,
            min_quality=args.min_quality,
            exported=exp_flag,
            limit=args.limit,
        )
        print(f"\n📋 Training Candidates ({len(candidates)} shown)")
        for c in candidates:
            q = c.get("quality_score", 0)
            ds = c.get("dataset", "?")
            src = c.get("source", "?")
            inp = (c.get("input_text", ""))[:60]
            cid = c.get("id", "?")
            print(f"  [{cid}] {ds} (q={q:.1f}, src={src}): {inp}...")

    elif args.command == "seed":
        print("\n🌱 Generating synthetic training data...")
        results = mgr.seed_datasets(
            datasets=args.datasets, force=args.force,
        )
        for ds, count in results.items():
            print(f"  {ds}: {count} examples")

    elif args.command == "export":
        print("\n📤 Exporting candidates to JSONL...")
        results = mgr.export_live_candidates(
            dataset=args.dataset, min_quality=args.min_quality,
        )
        for k, v in results.items():
            print(f"  {k}: {v}")

    elif args.command == "merge":
        print("\n🔀 Merging datasets...")
        results = mgr.merge_datasets(dataset=args.dataset)
        for ds, count in results.items():
            print(f"  {ds}: {count}")

    elif args.command == "prepare":
        print("\n🚀 Running full preparation pipeline...")
        results = mgr.prepare_for_training(
            min_quality=args.min_quality,
            augment_nexus=args.augment_nexus,
            augment_nlm=args.augment_nlm,
            nlm_notebook_id=args.nlm_notebook,
        )
        for step in results.get("steps", []):
            print(f"  ✓ {step['name']}: {step['result']}")
        print(f"\n  Duration: {results.get('duration_seconds', 0)}s")
        print(f"  Ready: {'✅' if results.get('ready_for_training') else '❌'}")
        print(f"  Total: {results.get('total_examples', 0)} examples")

    elif args.command == "validate":
        print("\n🔍 Validating datasets...")
        results = mgr.validate_datasets()
        if "datasets" in results:
            for ds in results["datasets"]:
                icon = "✅" if ds.get("valid") else "❌"
                print(f"  {icon} {ds['name']}: "
                      f"{ds['train_count']} train, {ds['val_count']} val")
                for issue in ds.get("issues", []):
                    print(f"      ⚠️  {issue}")
        print(f"\n  Ready: {'✅' if results.get('ready') else '❌'}")

    elif args.command == "files":
        files = mgr.get_dataset_files()
        print(f"\n📁 Dataset Files ({len(files)})")
        total_size = 0
        total_examples = 0
        for f in files:
            size_kb = f["size_bytes"] / 1024
            total_size += f["size_bytes"]
            total_examples += f["examples"]
            print(f"  {f['name']:40s} {f['examples']:>6d} examples  {size_kb:>8.1f} KB")
        print(f"\n  Total: {total_examples} examples, {total_size / 1024:.1f} KB")

    elif args.command == "add":
        result = mgr.add_manual_example(
            dataset=args.dataset,
            input_text=args.input_text,
            output_text=args.output_text,
            quality_score=args.quality,
            notes=args.notes,
        )
        if result.affected:
            print(f"✅ Added example to {args.dataset} (id={result.details.get('id')})")
        else:
            print(f"❌ Failed: {result.details}")

    elif args.command == "capture":
        if args.action == "status":
            print(f"Capture enabled: {mgr.get_capture_enabled()}")
        elif args.action == "on":
            mgr.set_capture_enabled(True)
            print("✅ Live capture enabled")
        elif args.action == "off":
            mgr.set_capture_enabled(False)
            print("⏸️ Live capture disabled")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
