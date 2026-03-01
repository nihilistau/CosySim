"""Micro-model Dataset Generators — NLM-powered dataset creation for 5 fine-tune targets.

Each generator produces (input, expected_output) pairs at scale using the
TeacherPipeline (Gemini 3.0 via NLM), with augmentation and dedup post-processing.

Usage::
    from training.micro_datasets import MicroDatasetManager
    mgr = MicroDatasetManager()
    result = mgr.build("qa_evaluator", count=1000)
    mgr.build_all(count_per_model=500)
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MODELS = ["qa_evaluator", "conversation_analyzer", "syntax_fixer", "router_v2", "knowledge_synthesizer"]
_DATASET_DIR = Path("training/datasets")
_DATASET_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class DatasetStats:
    """Statistics for a built dataset."""
    model_type: str
    total: int
    train: int
    val: int
    test: int
    duplicates_removed: int
    augmented: int
    path_train: str
    path_val: str
    path_test: str
    duration_s: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        return (
            f"{self.model_type}: {self.total} examples "
            f"(train={self.train}, val={self.val}, test={self.test}) "
            f"| deduped={self.duplicates_removed} aug={self.augmented} "
            f"| {self.duration_s:.1f}s"
        )


class MicroDatasetManager:
    """Manages NLM-powered dataset generation for all micro-model fine-tunes."""

    def __init__(self) -> None:
        _DATASET_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        model_type: str,
        count: int = 500,
        augment: bool = True,
        split: Tuple[float, float, float] = (0.8, 0.1, 0.1),
    ) -> DatasetStats:
        """Build complete dataset for one micro-model.

        Args:
            model_type: Target model type.
            count: Target number of training examples.
            augment: Apply augmentation to increase diversity.
            split: Train/val/test fractions.

        Returns:
            DatasetStats with paths and counts.
        """
        start = time.time()
        examples: List[Dict[str, Any]] = []

        # 1. Load existing saved examples
        existing = self._load_existing(model_type)
        examples.extend(existing)
        logger.info("%s: loaded %d existing examples", model_type, len(existing))

        # 2. Generate more via teacher pipeline if needed
        need = max(0, count - len(existing))
        if need > 0:
            logger.info("%s: generating %d new examples via NLM teacher", model_type, need)
            new_examples = self._generate_via_teacher(model_type, need)
            examples.extend(new_examples)

        # 3. Augment
        aug_count = 0
        if augment and examples:
            augmented = self._augment(model_type, examples, target=count)
            aug_count = len(augmented) - len(examples)
            examples = augmented

        # 4. Deduplicate
        before_dedup = len(examples)
        examples = self._deduplicate(examples)
        dupes = before_dedup - len(examples)

        # 5. Shuffle + split
        random.shuffle(examples)
        n = len(examples)
        train_end = int(n * split[0])
        val_end = train_end + int(n * split[1])
        train_set = examples[:train_end]
        val_set = examples[train_end:val_end]
        test_set = examples[val_end:]

        # 6. Convert to Alpaca format and save
        path_train = self._save_split(model_type, "train", self._to_format(model_type, train_set))
        path_val = self._save_split(model_type, "val", self._to_format(model_type, val_set))
        path_test = self._save_split(model_type, "test", self._to_format(model_type, test_set))

        duration = time.time() - start
        stats = DatasetStats(
            model_type=model_type,
            total=len(examples),
            train=len(train_set),
            val=len(val_set),
            test=len(test_set),
            duplicates_removed=dupes,
            augmented=aug_count,
            path_train=path_train,
            path_val=path_val,
            path_test=path_test,
            duration_s=round(duration, 2),
        )
        logger.info(stats.summary())
        self._store_stats(stats)
        return stats

    def build_all(
        self, count_per_model: int = 500, augment: bool = True
    ) -> List[DatasetStats]:
        """Build datasets for all micro-model types.

        Args:
            count_per_model: Target examples per model.
            augment: Apply augmentation.

        Returns:
            List of DatasetStats.
        """
        results = []
        for model_type in MODELS:
            try:
                stats = self.build(model_type, count=count_per_model, augment=augment)
                results.append(stats)
            except Exception as exc:
                logger.error("Failed to build dataset for %s: %s", model_type, exc)
        return results

    def status(self) -> Dict[str, Any]:
        """Return status of all datasets."""
        result: Dict[str, Any] = {}
        for model_type in MODELS:
            train_path = _DATASET_DIR / f"{model_type}_train.jsonl"
            val_path = _DATASET_DIR / f"{model_type}_val.jsonl"
            test_path = _DATASET_DIR / f"{model_type}_test.jsonl"
            result[model_type] = {
                "train": self._count_lines(train_path),
                "val": self._count_lines(val_path),
                "test": self._count_lines(test_path),
                "ready": train_path.exists(),
            }
        return result

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _load_existing(self, model_type: str) -> List[Dict[str, Any]]:
        """Load previously generated raw examples."""
        # Load from teacher pipeline raw output
        raw_path = _DATASET_DIR / f"{model_type}_train.jsonl"
        examples: List[Dict[str, Any]] = []
        if raw_path.exists():
            for line in raw_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        examples.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return examples

    def _generate_via_teacher(self, model_type: str, count: int) -> List[Dict[str, Any]]:
        """Use TeacherPipeline to generate new examples."""
        try:
            from engine.nexus.teacher_pipeline import get_teacher_pipeline
            pipeline = get_teacher_pipeline()
            result = pipeline.generate_dataset(model_type, count=count, store_in_nexus=True)
            return pipeline.load_dataset(model_type)
        except Exception as exc:
            logger.warning("Teacher pipeline unavailable, using synthetic: %s", exc)
            return self._generate_synthetic(model_type, count)

    def _generate_synthetic(self, model_type: str, count: int) -> List[Dict[str, Any]]:
        """Generate basic synthetic examples as a fallback."""
        examples = []
        templates: Dict[str, List[Dict[str, Any]]] = {
            "qa_evaluator": [
                {"input": "How do I start the bedroom scene?", "output": "ESSENTIAL"},
                {"input": "What is the weather today?", "output": "SKIP"},
                {"input": "What port does Nexus run on?", "output": "ESSENTIAL"},
                {"input": "How does the interceptor pipeline work?", "output": "ESSENTIAL"},
                {"input": "Can you help me with something?", "output": "SKIP"},
                {"input": "What skills are available in the bedroom scene?", "output": "USEFUL"},
                {"input": "How do I register a new @skill?", "output": "ESSENTIAL"},
            ],
            "router_v2": [
                {"input": "search nexus for interceptor docs", "output": "nexus_search"},
                {"input": "what port is lmstudio on", "output": "nexus_ask"},
                {"input": "start bedroom scene", "output": "scene_control"},
                {"input": "speak this text out loud", "output": "tts_request"},
                {"input": "run backup now", "output": "backup_request"},
                {"input": "transcribe this audio", "output": "stt_request"},
                {"input": "research NLM best practices", "output": "nlm_research"},
                {"input": "update the model config", "output": "config_update"},
            ],
            "syntax_fixer": [
                {"input": "def foo()\n    return 1", "output": "def foo():\n    return 1"},
                {"input": '{"key": "val"', "output": '{"key": "val"}'},
                {"input": "x = {'a: 1}", "output": "x = {'a': 1}"},
            ],
            "conversation_analyzer": [
                {"input": "I'm John, a Python developer", "output": '{"name":"John","tech_level":"expert"}'},
                {"input": "I love working with AI systems", "output": '{"preferences":{"domain":"AI systems"}}'},
            ],
            "knowledge_synthesizer": [
                {"input": "How does state sync work? [Context: MCPFramework tree syncs to SQLite]",
                 "output": "State sync works through the MCPFramework tree, which persists to SQLite automatically."},
            ],
        }
        base = templates.get(model_type, [{"input": "query", "output": "result"}])
        for i in range(count):
            ex = base[i % len(base)].copy()
            ex["source"] = "synthetic"
            ex["model_type"] = model_type
            examples.append(ex)
        return examples

    def _augment(
        self, model_type: str, examples: List[Dict[str, Any]], target: int
    ) -> List[Dict[str, Any]]:
        """Augment examples to reach target count."""
        if len(examples) >= target:
            return examples

        augmented = list(examples)
        need = target - len(examples)
        base_pool = [e for e in examples if e.get("source") != "synthetic"]
        if not base_pool:
            base_pool = examples

        augmenters = {
            "qa_evaluator": self._augment_qa_evaluator,
            "router_v2": self._augment_router,
            "syntax_fixer": self._augment_syntax,
            "conversation_analyzer": self._augment_conversation,
            "knowledge_synthesizer": self._augment_synthesizer,
        }
        fn = augmenters.get(model_type, self._augment_generic)

        for i in range(need):
            base = base_pool[i % len(base_pool)]
            aug = fn(base)
            if aug:
                augmented.append(aug)

        return augmented

    def _augment_qa_evaluator(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment by rephrasing the question."""
        rephrase_patterns = [
            (r"^How do I (.+)\?$", "What is the procedure for {}?"),
            (r"^What is (.+)\?$", "Can you explain {}?"),
            (r"^Where (.+)\?$", "What location does {}?"),
        ]
        q = ex.get("input", "")
        for pat, template in rephrase_patterns:
            m = re.match(pat, q, re.IGNORECASE)
            if m:
                new_q = template.format(m.group(1))
                return {**ex, "input": new_q, "source": "augmented"}
        # Generic: add context prefix
        prefixes = ["In CosySim, ", "For the agent, ", "When using Nexus, "]
        prefix = random.choice(prefixes)
        if not q.startswith(prefix):
            return {**ex, "input": prefix + q[0].lower() + q[1:], "source": "augmented"}
        return None

    def _augment_router(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment router examples with synonym phrases."""
        synonyms: Dict[str, List[str]] = {
            "search": ["find", "look up", "query", "locate"],
            "start": ["launch", "begin", "run", "open", "activate"],
            "update": ["change", "modify", "set", "configure"],
            "backup": ["save", "archive", "snapshot"],
        }
        q = ex.get("input", "")
        words = q.split()
        for i, w in enumerate(words):
            if w.lower() in synonyms:
                replacement = random.choice(synonyms[w.lower()])
                new_words = words[:i] + [replacement] + words[i+1:]
                return {**ex, "input": " ".join(new_words), "source": "augmented"}
        return None

    def _augment_syntax(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment syntax_fixer by introducing small variations."""
        inp = ex.get("input", "")
        out = ex.get("output", "")
        # Add a comment to the output
        if inp and "\n" in out:
            lines = out.splitlines()
            if len(lines) > 1:
                commented = f"# fixed\n{out}"
                return {**ex, "output": commented, "source": "augmented"}
        return None

    def _augment_conversation(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment by adding filler words to conversation."""
        inp = ex.get("input", "")
        if inp:
            fillers = ["Actually, ", "By the way, ", "I should mention that "]
            filler = random.choice(fillers)
            return {**ex, "input": filler + inp, "source": "augmented"}
        return None

    def _augment_synthesizer(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment by adding slight answer rewording."""
        out = ex.get("output", "")
        if out and not out.startswith("Based on"):
            return {**ex, "output": f"Based on the available context: {out}", "source": "augmented"}
        return None

    def _augment_generic(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return {**ex, "source": "augmented"}

    def _deduplicate(self, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate examples based on input text."""
        seen: set[str] = set()
        unique: List[Dict[str, Any]] = []
        for ex in examples:
            key = ex.get("input", "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(ex)
        return unique

    def _to_format(
        self, model_type: str, examples: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert examples to Alpaca instruction format."""
        formatted = []
        instructions: Dict[str, str] = {
            "qa_evaluator": "Classify this Q&A pair as ESSENTIAL, USEFUL, or SKIP for the knowledge cache.",
            "conversation_analyzer": "Extract structured user facts from this conversation snippet.",
            "syntax_fixer": "Fix the syntax errors in this code or text. Return only the corrected version.",
            "router_v2": "Classify this request to the most appropriate CosySim subsystem handler.",
            "knowledge_synthesizer": "Synthesize a concise answer from the provided context fragments.",
        }
        instruction = instructions.get(model_type, "Complete the task.")
        for ex in examples:
            formatted.append({
                "instruction": instruction,
                "input": ex.get("input", ""),
                "output": ex.get("output", ""),
                "model_type": model_type,
            })
        return formatted

    def _save_split(
        self, model_type: str, split: str, examples: List[Dict[str, Any]]
    ) -> str:
        """Save a dataset split as JSONL and return path."""
        path = _DATASET_DIR / f"{model_type}_{split}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex) + "\n")
        return str(path)

    def _count_lines(self, path: Path) -> int:
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def _store_stats(self, stats: DatasetStats) -> None:
        """Save dataset stats to Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"Dataset Build: {stats.model_type}",
                content=json.dumps(stats.to_dict()),
                content_type="history",
                category="training",
            )
        except Exception as exc:
            logger.debug("Nexus store skipped: %s", exc)
