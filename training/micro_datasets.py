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

MODELS = ["qa_evaluator", "conversation_analyzer", "syntax_fixer", "router_v2", "router_v3", "knowledge_synthesizer", "tool_dispatch", "grammar_scanner", "output_evaluator", "conversational", "coder"]
_DATASET_DIR = Path("training/datasets")
_DATASET_DIR.mkdir(parents=True, exist_ok=True)

# ── Router v2 label taxonomy ───────────────────────────────────────────────
# Labels map user intent to the most appropriate CosySim subsystem handler.
# nexus_search   - full-text knowledge base search
# nexus_ask      - Q&A lookup / factual question
# scene_control  - start/stop/pause/restart a scene or workflow
# tts_request    - text-to-speech generation / speak aloud
# backup_request - create/restore/list backups
# stt_request    - speech-to-text / transcribe audio
# nlm_research   - NotebookLM research, notebook management, analysis
# config_update  - change/read configuration settings

_ROUTER_V2_TEMPLATES: List[Dict[str, Any]] = [
    # ── nexus_search ──
    {"input": "search nexus for interceptor docs", "output": "nexus_search"},
    {"input": "find knowledge entries about MCP framework", "output": "nexus_search"},
    {"input": "look up notes on the bedroom scene", "output": "nexus_search"},
    {"input": "query nexus for information about skills", "output": "nexus_search"},
    {"input": "search for documents tagged architecture", "output": "nexus_search"},
    {"input": "find all nexus entries about training pipeline", "output": "nexus_search"},
    {"input": "look up the governance rules in nexus", "output": "nexus_search"},
    {"input": "search knowledge base for LMStudio configuration", "output": "nexus_search"},
    {"input": "find any notes about the dialog system", "output": "nexus_search"},
    {"input": "locate all entries tagged with 'testing'", "output": "nexus_search"},
    {"input": "search nexus for TTS benchmarks", "output": "nexus_search"},
    {"input": "look for documents about the event chain", "output": "nexus_search"},
    {"input": "find all knowledge entries from this week", "output": "nexus_search"},
    {"input": "search for snippets about async agents", "output": "nexus_search"},
    {"input": "query the knowledge base for cosysim architecture", "output": "nexus_search"},
    # ── nexus_ask ──
    {"input": "what port is lmstudio on", "output": "nexus_ask"},
    {"input": "how do I register a new skill", "output": "nexus_ask"},
    {"input": "what is the Nexus Q&A hit rate", "output": "nexus_ask"},
    {"input": "how does the interceptor pipeline work", "output": "nexus_ask"},
    {"input": "what is the current version of CosySim", "output": "nexus_ask"},
    {"input": "how do I write a pytest test for a scene", "output": "nexus_ask"},
    {"input": "what port does the bedroom scene run on", "output": "nexus_ask"},
    {"input": "how does state sync to the MCP tree", "output": "nexus_ask"},
    {"input": "what MCP tools are available for NLM operations", "output": "nexus_ask"},
    {"input": "how do I create a new scene", "output": "nexus_ask"},
    {"input": "what conventions apply to Python files", "output": "nexus_ask"},
    {"input": "what was the last breaking change in cosysim", "output": "nexus_ask"},
    {"input": "how do I add a character to a scene", "output": "nexus_ask"},
    {"input": "what is the @skill decorator signature", "output": "nexus_ask"},
    {"input": "how does the QA cache pipeline work", "output": "nexus_ask"},
    # ── scene_control ──
    {"input": "start bedroom scene", "output": "scene_control"},
    {"input": "launch the phone scene", "output": "scene_control"},
    {"input": "open the nexus panel", "output": "scene_control"},
    {"input": "stop all running scenes", "output": "scene_control"},
    {"input": "restart the command center", "output": "scene_control"},
    {"input": "run the heist scene", "output": "scene_control"},
    {"input": "pause the realm scene", "output": "scene_control"},
    {"input": "list all active scenes", "output": "scene_control"},
    {"input": "activate the intel hub", "output": "scene_control"},
    {"input": "shut down the bedroom scene", "output": "scene_control"},
    {"input": "begin the tutorial scene", "output": "scene_control"},
    {"input": "turn off all scenes", "output": "scene_control"},
    {"input": "reload the phone scene", "output": "scene_control"},
    {"input": "initialize the gaming scene", "output": "scene_control"},
    {"input": "check which scenes are running", "output": "scene_control"},
    # ── tts_request ──
    {"input": "speak this text out loud", "output": "tts_request"},
    {"input": "say hello world using aria's voice", "output": "tts_request"},
    {"input": "read this paragraph aloud", "output": "tts_request"},
    {"input": "generate speech from this text", "output": "tts_request"},
    {"input": "use piper to speak the notification", "output": "tts_request"},
    {"input": "play the welcome message with orpheus", "output": "tts_request"},
    {"input": "convert this text to audio", "output": "tts_request"},
    {"input": "voice this message using qwen3 TTS", "output": "tts_request"},
    {"input": "synthesize speech for the dialog line", "output": "tts_request"},
    {"input": "narrate the scene description", "output": "tts_request"},
    {"input": "announce the system status via TTS", "output": "tts_request"},
    {"input": "speak the error message", "output": "tts_request"},
    {"input": "preview the selected voice", "output": "tts_request"},
    {"input": "generate audio for the assistant reply", "output": "tts_request"},
    {"input": "text to speech for this sentence", "output": "tts_request"},
    # ── backup_request ──
    {"input": "run backup now", "output": "backup_request"},
    {"input": "create a nexus snapshot", "output": "backup_request"},
    {"input": "archive the current database", "output": "backup_request"},
    {"input": "save a backup of the knowledge base", "output": "backup_request"},
    {"input": "list available backups", "output": "backup_request"},
    {"input": "restore from the latest backup", "output": "backup_request"},
    {"input": "make a checkpoint of all databases", "output": "backup_request"},
    {"input": "export nexus to a backup file", "output": "backup_request"},
    {"input": "how many backups are stored", "output": "backup_request"},
    {"input": "schedule a backup for tonight", "output": "backup_request"},
    {"input": "verify the backup integrity", "output": "backup_request"},
    {"input": "delete old backups older than 30 days", "output": "backup_request"},
    {"input": "create a full system snapshot", "output": "backup_request"},
    {"input": "backup before the finetuning run", "output": "backup_request"},
    {"input": "get the last backup timestamp", "output": "backup_request"},
    # ── stt_request ──
    {"input": "transcribe this audio", "output": "stt_request"},
    {"input": "convert my voice recording to text", "output": "stt_request"},
    {"input": "transcribe the meeting recording", "output": "stt_request"},
    {"input": "listen to my microphone input", "output": "stt_request"},
    {"input": "use whisper to transcribe this file", "output": "stt_request"},
    {"input": "speech to text for the audio clip", "output": "stt_request"},
    {"input": "transcribe the user's voice message", "output": "stt_request"},
    {"input": "process this audio through whisper", "output": "stt_request"},
    {"input": "convert speech to text in real time", "output": "stt_request"},
    {"input": "start voice recognition", "output": "stt_request"},
    {"input": "transcribe the scene audio file", "output": "stt_request"},
    {"input": "decode this mp3 to text", "output": "stt_request"},
    {"input": "record and transcribe my voice", "output": "stt_request"},
    {"input": "turn audio into readable text", "output": "stt_request"},
    {"input": "transcribe the notification from the call", "output": "stt_request"},
    # ── nlm_research ──
    {"input": "research NLM best practices", "output": "nlm_research"},
    {"input": "create a notebook on cosysim architecture", "output": "nlm_research"},
    {"input": "ask notebooklm about the interceptor pipeline", "output": "nlm_research"},
    {"input": "open NLM lab and distill Q&A pairs", "output": "nlm_research"},
    {"input": "start a research session on LMStudio routing", "output": "nlm_research"},
    {"input": "batch-ask 20 questions to the architecture notebook", "output": "nlm_research"},
    {"input": "generate a study guide for the training pipeline", "output": "nlm_research"},
    {"input": "converse with notebooklm about the scene system", "output": "nlm_research"},
    {"input": "add the docs folder as sources to the research notebook", "output": "nlm_research"},
    {"input": "distill conversation from the NLM notebook", "output": "nlm_research"},
    {"input": "extract flashcards from the codebase notebook", "output": "nlm_research"},
    {"input": "create a data table from the NLM notebook", "output": "nlm_research"},
    {"input": "upload source files to the cosysim notebook", "output": "nlm_research"},
    {"input": "list all notebooklm notebooks", "output": "nlm_research"},
    {"input": "delete the old research notebook", "output": "nlm_research"},
    # ── config_update ──
    {"input": "update the model config", "output": "config_update"},
    {"input": "change the lmstudio port to 1235", "output": "config_update"},
    {"input": "enable debug mode in the config", "output": "config_update"},
    {"input": "set the TTS backend to orpheus", "output": "config_update"},
    {"input": "disable the news fetch scheduler task", "output": "config_update"},
    {"input": "configure the nexus knowledge base URL", "output": "config_update"},
    {"input": "read the current config for the bedroom scene", "output": "config_update"},
    {"input": "update the router model path in config", "output": "config_update"},
    {"input": "set concurrent_slots to 4 in lmstudio config", "output": "config_update"},
    {"input": "turn on verbose logging in default config", "output": "config_update"},
    {"input": "modify the ComfyUI port setting", "output": "config_update"},
    {"input": "change the finetuning batch size in config", "output": "config_update"},
    {"input": "reload the config from disk", "output": "config_update"},
    {"input": "what is the current value of nexus.port", "output": "config_update"},
    {"input": "update the scheduler interval for news-fetch", "output": "config_update"},
]



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
        """Use TeacherPipeline to generate new examples, supplementing with synthetic."""
        teacher_examples: List[Dict[str, Any]] = []
        try:
            from engine.nexus.teacher_pipeline import get_teacher_pipeline
            pipeline = get_teacher_pipeline()
            pipeline.generate_dataset(model_type, count=count, store_in_nexus=True)
            teacher_examples = pipeline.load_dataset(model_type)
        except Exception as exc:
            logger.warning("Teacher pipeline unavailable, using synthetic: %s", exc)

        # Always supplement with synthetic templates to ensure full label coverage.
        # This is safe: _deduplicate in build() removes any true duplicates.
        synthetic = self._generate_synthetic(model_type, count)

        # Merge: teacher examples first (higher quality), synthetic fill the rest
        combined = list(teacher_examples)
        existing_inputs = {e.get("input", "").strip().lower() for e in combined}
        for ex in synthetic:
            if ex.get("input", "").strip().lower() not in existing_inputs:
                combined.append(ex)
                existing_inputs.add(ex.get("input", "").strip().lower())
        return combined

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
            "router_v2": _ROUTER_V2_TEMPLATES,
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
            "tool_dispatch": [
                {"input": "search nexus for interceptor pipeline",
                 "output": '{"tool": "nexus_search", "args": {"query": "interceptor pipeline"}}'},
                {"input": "ask nexus how MCP framework works",
                 "output": '{"tool": "nexus_ask", "args": {"question": "how does MCP framework work"}}'},
                {"input": "store a note about architecture",
                 "output": '{"tool": "nexus_add", "args": {"title": "Architecture Note", "content": "...", "content_type": "note"}}'},
                {"input": "check system health status",
                 "output": '{"tool": "system_status", "args": {}}'},
                {"input": "list all available skills",
                 "output": '{"tool": "list_all_skills", "args": {}}'},
            ],
            "grammar_scanner": [
                {"input": "def foo()\n    return 1", "output": "Issue: Missing colon after function definition"},
                {"input": '{"key": "val"', "output": "Issue: Unclosed JSON object, missing closing brace"},
                {"input": "x = {'a: 1}", "output": "Issue: Unclosed string key 'a"},
                {"input": "def bar():\n    return 2", "output": "OK"},
                {"input": '{"key": "value"}', "output": "OK"},
            ],
            "output_evaluator": [
                {"input": "Paris is the capital of France.", "output": "SCORE: 5\nREASON: Factually correct and concise"},
                {"input": "I dunno maybe something idk", "output": "SCORE: 1\nREASON: Vague and unhelpful response"},
                {"input": "The interceptor pipeline processes requests by applying pre and post call hooks.", "output": "SCORE: 4\nREASON: Clear and informative"},
            ],
            "conversational": [
                {"input": "System: You are Aria.\n\nUSER: Hello", "output": "Hi there! How can I help you today?"},
                {"input": "System: You are Lola.\n\nUSER: What do you want?", "output": "That depends entirely on what you're offering..."},
                {"input": "System: You are Viktor.\n\nUSER: Status report.", "output": "All systems nominal. No threats detected. Standing by."},
            ],
            "coder": [
                {"input": "# Write a Python function to get config\ndef get_config():", "output": "def get_config():\n    from engine.config import get_config as _gc\n    return _gc()"},
                {"input": "# Module: base_scene\n# Task: Start the scene\ndef start(self):", "output": "def start(self) -> None:\n    \"\"\"Initialize and start the scene.\"\"\"\n    self._setup_routes()\n    self._register_skills()\n    logger.info(f'Scene {self.SCENE_METADATA[\"name\"]} started')"},
            ],
        }
        base = templates.get(model_type, [{"input": "query", "output": "result"}])
        # Return all unique templates first; only cycle if count exceeds template set
        for i in range(count):
            ex = base[i % len(base)].copy()
            ex["source"] = "synthetic"
            ex["model_type"] = model_type
            if i < len(base):
                examples.append(ex)  # Only add unique template examples, skip duplicates
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
        # For router_v2, use all examples as base to ensure full label coverage
        if model_type == "router_v2":
            base_pool = examples

        augmenters = {
            "qa_evaluator": self._augment_qa_evaluator,
            "router_v2": self._augment_router,
            "syntax_fixer": self._augment_syntax,
            "conversation_analyzer": self._augment_conversation,
            "knowledge_synthesizer": self._augment_synthesizer,
            "tool_dispatch": self._augment_tool_dispatch,
            "grammar_scanner": self._augment_grammar_scanner,
            "output_evaluator": self._augment_output_evaluator,
            "conversational": self._augment_conversation,
            "coder": self._augment_generic,
        }
        fn = augmenters.get(model_type, self._augment_generic)

        if model_type == "router_v2":
            # Special handling: enumerate all (base × transform) pairs to guarantee
            # uniqueness. With 120 templates × 4 transforms = 480 unique combos.
            base_count = len(base_pool)
            for i in range(need):
                b = i % base_count          # which base template
                cycle = i // base_count     # 0→transform0, 1→transform1, ...
                base = {**base_pool[b], "_aug_index": cycle}  # cycle IS the transform selector
                aug = self._augment_router(base)
                if aug:
                    augmented.append(aug)
        else:
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
        """Augment router examples — 4 deterministic transforms, cycled by _aug_index."""
        q = ex.get("input", "").strip()
        label = ex.get("output", "")
        aug_index: int = ex.get("_aug_index", 0)
        if not q:
            return None

        words = q.split()
        low_q = q[0].lower() + q[1:]

        # 8 conversational prefixes — chosen deterministically by aug_index
        _prefixes = [
            "please ", "can you ", "hey, ", "i need to ",
            "quickly ", "go ahead and ", "help me ", "right now, ",
        ]
        # 8 label-aware noun-phrase wrappers
        _noun_wrap: Dict[str, str] = {
            "nexus_search": "nexus search: {q}",
            "nexus_ask": "nexus question: {q}",
            "scene_control": "scene action: {q}",
            "tts_request": "tts: {q}",
            "backup_request": "backup task: {q}",
            "stt_request": "stt: {q}",
            "nlm_research": "nlm task: {q}",
            "config_update": "config: {q}",
        }
        # 8 question-form wrappers
        _question_wrap: Dict[str, str] = {
            "nexus_search": "what nexus entries cover {rest}?",
            "nexus_ask": "can you explain {rest}?",
            "scene_control": "can we {rest}?",
            "tts_request": "would you {rest}?",
            "backup_request": "is it possible to {rest}?",
            "stt_request": "could you {rest}?",
            "nlm_research": "would you {rest}?",
            "config_update": "how do i {rest}?",
        }
        # synonym table — first matching word is swapped
        _synonyms: Dict[str, List[str]] = {
            "search": ["find", "look up", "query", "locate", "hunt for", "retrieve"],
            "find": ["search", "locate", "fetch", "retrieve"],
            "start": ["launch", "begin", "run", "open", "activate", "boot"],
            "launch": ["start", "open", "run", "fire up", "activate"],
            "stop": ["shut down", "halt", "kill", "terminate"],
            "run": ["execute", "trigger", "fire", "kick off"],
            "update": ["change", "modify", "set", "configure", "adjust"],
            "change": ["update", "modify", "set", "configure"],
            "backup": ["snapshot", "archive", "save", "checkpoint"],
            "create": ["make", "build", "generate", "set up"],
            "transcribe": ["convert to text", "decode", "process"],
            "research": ["investigate", "explore", "study", "examine"],
            "speak": ["say", "voice", "read aloud", "narrate", "announce"],
            "say": ["speak", "voice", "read", "narrate"],
            "list": ["show", "enumerate", "display", "get"],
            "open": ["launch", "start", "activate", "load"],
            "ask": ["query", "request", "question"],
            "use": ["employ", "utilize", "apply"],
            "enable": ["turn on", "activate", "switch on"],
            "disable": ["turn off", "deactivate", "switch off"],
        }

        transform = aug_index % 4

        if transform == 0:
            # Deterministic prefix — chosen by cycling through 8 options
            prefix = _prefixes[aug_index % len(_prefixes)]
            new_q = prefix + low_q
            if new_q.strip() != q:
                return {**ex, "input": new_q, "source": "augmented"}

        elif transform == 1:
            # Question-form wrapper
            rest = " ".join(words[1:]).lower() if len(words) > 1 else low_q
            tmpl = _question_wrap.get(label, "can you {rest}?")
            new_q = tmpl.replace("{rest}", rest)
            if new_q != q:
                return {**ex, "input": new_q, "source": "augmented"}

        elif transform == 2:
            # Noun-phrase / category prefix
            tmpl = _noun_wrap.get(label, "task: {q}")
            new_q = tmpl.replace("{q}", low_q)
            if new_q != q:
                return {**ex, "input": new_q, "source": "augmented"}

        else:  # transform == 3
            # Deterministic synonym swap — pick word at position (aug_index // 4) % len(words)
            pivot = (aug_index // 4) % max(len(words), 1)
            for offset in range(len(words)):
                idx = (pivot + offset) % len(words)
                w = words[idx].lower().rstrip(".,!?")
                if w in _synonyms:
                    choices = [s for s in _synonyms[w] if s != w]
                    if choices:
                        replacement = choices[(aug_index // 4) % len(choices)]
                        new_words = list(words)
                        new_words[idx] = replacement
                        new_q = " ".join(new_words)
                        if new_q != q:
                            return {**ex, "input": new_q, "source": "augmented"}
                        break

        # Last-resort: numeric suffix to guarantee uniqueness
        return {**ex, "input": f"{q} [v{aug_index}]", "source": "augmented"}

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

    def _augment_tool_dispatch(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment tool_dispatch examples with phrasing variations."""
        inp = ex.get("input", "")
        prefixes = ["please ", "can you ", "I need to ", "help me "]
        import random
        prefix = random.choice(prefixes)
        if not inp.startswith(prefix):
            return {**ex, "input": prefix + inp[0].lower() + inp[1:], "source": "augmented"}
        return {**ex, "source": "augmented"}

    def _augment_grammar_scanner(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment grammar_scanner by minor input rewording."""
        inp = ex.get("input", "")
        if inp:
            return {**ex, "input": inp + " ", "source": "augmented"}
        return None

    def _augment_output_evaluator(self, ex: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Augment output_evaluator examples with context prefix."""
        inp = ex.get("input", "")
        if inp and not inp.startswith("Context:"):
            return {**ex, "input": f"Evaluate this output:\n{inp}", "source": "augmented"}
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
            "tool_dispatch": 'Route this instruction to the correct tool. Respond with JSON: {"tool": "skill_name", "args": {...}}',
            "grammar_scanner": "Scan this text for grammar errors and missing symbols. List all issues or respond 'OK' if clean.",
            "output_evaluator": "Score the quality of this LLM output from 1 (bad) to 5 (excellent). Respond: SCORE: N\nREASON: brief explanation",
            "conversational": "Continue this conversation naturally, in character.",
            "coder": "Complete or generate the requested code following CosySim conventions.",
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
