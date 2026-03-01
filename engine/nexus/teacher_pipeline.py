"""NLM Teacher Pipeline — uses Gemini 3.0 (NotebookLM) as a teacher model to
generate gold-standard training examples for micro-model fine-tuning.

For each micro-model type, creates a dedicated NLM notebook, loads relevant
CosySim source documents, then uses generate_report_with_prompt + extract_data_tables
to bulk-generate (input, expected_output) training pairs.

Usage::
    from engine.nexus.teacher_pipeline import get_teacher_pipeline
    pipeline = get_teacher_pipeline()
    result = pipeline.generate_dataset("qa_evaluator", count=500)
"""
from __future__ import annotations

import csv
import io
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Constants ────────────────────────────────────────────────────────────────

MICRO_MODEL_TYPES = [
    "qa_evaluator",
    "conversation_analyzer",
    "syntax_fixer",
    "router_v2",
    "knowledge_synthesizer",
]

_DATASET_DIR = Path("training/datasets")


# ──── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TrainingExample:
    """A single (input, output) training pair."""
    input: str
    output: str
    model_type: str
    source: str = "nlm_teacher"
    quality: str = "gold"  # gold | silver | bronze
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_alpaca(self) -> Dict[str, Any]:
        """Convert to Alpaca instruction format for Unsloth."""
        instruction = self.metadata.get("instruction", self.input)
        return {
            "instruction": instruction,
            "input": self.metadata.get("context", ""),
            "output": self.output,
        }

    def to_sharegpt(self) -> Dict[str, Any]:
        """Convert to ShareGPT chat format."""
        return {
            "conversations": [
                {"from": "human", "value": self.input},
                {"from": "gpt", "value": self.output},
            ]
        }


@dataclass
class TeacherResult:
    """Result of a teacher pipeline generation run."""
    model_type: str
    count_requested: int
    count_generated: int
    count_accepted: int
    dataset_path: str
    notebook_id: Optional[str]
    duration_s: float
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──── Prompt Templates ─────────────────────────────────────────────────────────

_PROMPTS: Dict[str, str] = {
    "qa_evaluator": """You are generating training data for a tiny classification model.
Task: classify whether a Q&A pair should be stored in the CosySim knowledge cache.
Labels: ESSENTIAL (critical system knowledge), USEFUL (helpful context), SKIP (too vague/generic).

Generate {count} training examples as CSV with columns:
question,answer,label,reasoning

Rules:
- ESSENTIAL: startup sequences, API contracts, config keys, error fixes, architecture decisions
- USEFUL: patterns, best practices, workflow tips, component descriptions  
- SKIP: trivial, circular, extremely generic, or already obvious from code
- reasoning must be one concise sentence explaining the label
- questions should be phrased as a developer or agent would actually ask them
- answers should be factual, concise, and accurate to CosySim

Output ONLY valid CSV. No preamble. No commentary. Start with the header row.""",

    "conversation_analyzer": """You are generating training data for a conversation fact extractor.
Task: given a user message or conversation snippet, extract structured facts about the user.

Generate {count} training examples as JSON Lines (one JSON per line):
{{"input": "<conversation_text>", "output": {{"name": null, "age": null, "occupation": null, "tech_level": "beginner|intermediate|expert", "projects": [], "preferences": {{}}, "facts": []}}}}

Rules:
- input can be 1-3 message turns from a real technical conversation
- output should only include fields where evidence exists in the input (null otherwise)
- tech_level is inferred from vocabulary and topics discussed
- projects: list of project names mentioned
- preferences: dict of user preferences (e.g. {{"language": "Python", "style": "terse"}})
- facts: list of standalone factual claims about the user

Output ONLY JSON Lines. No preamble.""",

    "syntax_fixer": """You are generating training data for an instant code/text repair model.
Task: given broken code or text with syntax errors, output the fixed version.

Generate {count} training examples as JSON Lines:
{{"input": "<broken_code_or_text>", "output": "<fixed_version>", "error_type": "<type>"}}

Error types to cover: missing_colon, missing_bracket, wrong_indent, undefined_variable,
import_error, type_mismatch, missing_comma, unclosed_string, wrong_quote_style,
missing_self, incorrect_return_type, malformed_yaml, malformed_json

Rules:
- Python, YAML, and JSON errors (roughly equal split)
- input should look like real code from a CosySim-style project
- output is the minimal fix only — don't refactor or add features
- error_type is one of the types listed above

Output ONLY JSON Lines.""",

    "router_v2": """You are generating training data for a request routing classifier.
Task: given a user request, output which CosySim subsystem should handle it.

Classes: nexus_search, nexus_ask, nlm_research, lmstudio_chat, scene_control,
skill_call, tts_request, stt_request, config_update, backup_request,
scheduler_control, finetune_request, system_status, unknown

Generate {count} training examples as CSV:
request,class,confidence,reasoning

Rules:
- requests should be phrased exactly as a user or agent would send them
- confidence: high/medium/low
- reasoning: one sentence
- cover all classes roughly proportionally
- include ambiguous cases with medium/low confidence

Output ONLY valid CSV with header.""",

    "knowledge_synthesizer": """You are generating training data for a knowledge synthesis model.
Task: given a question and 2-5 Nexus knowledge fragments as context, synthesize a concise answer.

Generate {count} training examples as JSON Lines:
{{"question": "<q>", "context_fragments": ["<fragment1>", ...], "answer": "<synthesized_answer>"}}

Rules:
- questions should be real CosySim/agent/developer questions
- context_fragments are plausible knowledge base entries (1-4 sentences each)
- answer is derived ONLY from the fragments (no hallucination)
- if fragments don't fully answer, say so and give partial answer
- answer should be 1-4 sentences

Output ONLY JSON Lines.""",
}


# ──── Pipeline ─────────────────────────────────────────────────────────────────

class TeacherPipeline:
    """Uses NLM (NotebookLM) as a teacher to generate fine-tune training data."""

    def __init__(self) -> None:
        self._notebook_cache: Dict[str, str] = {}  # model_type → notebook_id
        _DATASET_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_dataset(
        self,
        model_type: str,
        count: int = 500,
        use_existing_notebook: bool = True,
        store_in_nexus: bool = True,
    ) -> TeacherResult:
        """Generate a training dataset for a micro-model via NLM.

        Args:
            model_type: One of MICRO_MODEL_TYPES.
            count: Number of examples to generate.
            use_existing_notebook: Reuse cached notebook ID if available.
            store_in_nexus: Save result metadata to Nexus.

        Returns:
            TeacherResult with dataset path and stats.
        """
        if model_type not in MICRO_MODEL_TYPES:
            raise ValueError(f"Unknown model_type '{model_type}'. Valid: {MICRO_MODEL_TYPES}")

        start = time.time()
        errors: List[str] = []
        notebook_id: Optional[str] = None
        examples: List[TrainingExample] = []

        try:
            # Get or create NLM notebook
            notebook_id = self._get_or_create_notebook(model_type, use_existing_notebook)

            # Generate via NLM report
            raw = self._generate_raw(model_type, count, notebook_id)

            # Parse into examples
            examples = self._parse_examples(model_type, raw, count)

        except Exception as exc:
            logger.error("Teacher pipeline error for %s: %s", model_type, exc)
            errors.append(str(exc))
            # Fall back to synthetic generation
            examples = self._generate_synthetic_fallback(model_type, count)

        # Save dataset
        dataset_path = self._save_dataset(model_type, examples)

        if store_in_nexus and examples:
            self._store_metadata_in_nexus(model_type, len(examples), dataset_path)

        duration = time.time() - start
        result = TeacherResult(
            model_type=model_type,
            count_requested=count,
            count_generated=len(examples),
            count_accepted=len(examples),
            dataset_path=dataset_path,
            notebook_id=notebook_id,
            duration_s=round(duration, 2),
            errors=errors,
        )
        logger.info(
            "Teacher pipeline %s: generated %d examples in %.1fs → %s",
            model_type, len(examples), duration, dataset_path,
        )
        return result

    def generate_all_datasets(self, count_per_model: int = 500) -> List[TeacherResult]:
        """Generate datasets for all micro-model types.

        Args:
            count_per_model: Examples per model type.

        Returns:
            List of TeacherResult, one per model type.
        """
        results = []
        for model_type in MICRO_MODEL_TYPES:
            logger.info("Generating dataset for %s...", model_type)
            result = self.generate_dataset(model_type, count=count_per_model)
            results.append(result)
        return results

    def get_dataset_stats(self) -> Dict[str, Any]:
        """Return stats on all saved datasets."""
        stats: Dict[str, Any] = {}
        for model_type in MICRO_MODEL_TYPES:
            path = _DATASET_DIR / f"{model_type}_train.jsonl"
            if path.exists():
                lines = path.read_text(encoding="utf-8").splitlines()
                stats[model_type] = {"examples": len(lines), "path": str(path), "exists": True}
            else:
                stats[model_type] = {"examples": 0, "path": str(path), "exists": False}
        return stats

    def load_dataset(self, model_type: str) -> List[Dict[str, Any]]:
        """Load a saved dataset as a list of dicts.

        Args:
            model_type: Model type to load.

        Returns:
            List of training example dicts.
        """
        path = _DATASET_DIR / f"{model_type}_train.jsonl"
        if not path.exists():
            return []
        examples = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return examples

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _get_or_create_notebook(self, model_type: str, use_existing: bool) -> Optional[str]:
        """Return a notebook ID for the given model type."""
        if use_existing and model_type in self._notebook_cache:
            return self._notebook_cache[model_type]

        try:
            from engine.nexus.nlm_notebook_manager import get_notebook_manager
            mgr = get_notebook_manager()

            title = f"CosySim Teacher: {model_type}"
            sources = self._get_sources_for_model(model_type)
            notebook_id = mgr.create_notebook(title=title, sources=sources)
            self._notebook_cache[model_type] = notebook_id
            logger.info("Created NLM notebook %s for %s", notebook_id, model_type)
            return notebook_id
        except Exception as exc:
            logger.warning("NLM notebook creation failed: %s", exc)
            return None

    def _get_sources_for_model(self, model_type: str) -> List[str]:
        """Return file paths to upload as NLM sources for a given model type."""
        base = Path(".")
        common = [
            "docs/ARCHITECTURE.md",
            "docs/MCP_FRAMEWORK.md",
            "README.md",
        ]
        specific: Dict[str, List[str]] = {
            "qa_evaluator": ["docs/NEXUS.md", "engine/nexus/cache_pipeline.py"],
            "conversation_analyzer": ["engine/nexus/conversation_analyzer.py", "engine/nexus/user_profile.py"],
            "syntax_fixer": ["engine/config.py", "engine/skills/skill.py"],
            "router_v2": ["engine/lmstudio/router.py", "engine/agents/agent_router.py"],
            "knowledge_synthesizer": ["engine/nexus/client.py", "docs/NEXUS.md"],
        }
        all_sources = common + specific.get(model_type, [])
        return [str(base / p) for p in all_sources if (base / p).exists()]

    def _generate_raw(self, model_type: str, count: int, notebook_id: Optional[str]) -> str:
        """Call NLM generate_report_with_prompt to get raw output."""
        if notebook_id is None:
            raise RuntimeError("No notebook available for NLM generation")

        prompt = _PROMPTS[model_type].format(count=count)
        try:
            from engine.nexus.nlm_notebook_manager import get_notebook_manager
            mgr = get_notebook_manager()
            raw = mgr.generate_report_with_prompt(notebook_id, prompt)
            return raw or ""
        except Exception as exc:
            raise RuntimeError(f"NLM generation failed: {exc}") from exc

    def _parse_examples(
        self, model_type: str, raw: str, expected: int
    ) -> List[TrainingExample]:
        """Parse NLM raw output into TrainingExample list."""
        if model_type in ("qa_evaluator", "router_v2"):
            return self._parse_csv(model_type, raw)
        else:
            return self._parse_jsonl(model_type, raw)

    def _parse_csv(self, model_type: str, raw: str) -> List[TrainingExample]:
        """Parse CSV output (qa_evaluator, router_v2)."""
        examples: List[TrainingExample] = []
        # Find CSV block
        lines = raw.strip().splitlines()
        csv_start = 0
        for i, line in enumerate(lines):
            if "," in line and not line.startswith("#"):
                csv_start = i
                break
        csv_text = "\n".join(lines[csv_start:])
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            for row in reader:
                if not row:
                    continue
                keys = list(row.keys())
                if not keys:
                    continue
                input_text = row.get(keys[0], "").strip()
                output_text = row.get(keys[1], "").strip() if len(keys) > 1 else ""
                if input_text and output_text:
                    examples.append(TrainingExample(
                        input=input_text,
                        output=output_text,
                        model_type=model_type,
                        metadata={k: v for k, v in row.items()},
                    ))
        except Exception as exc:
            logger.warning("CSV parse error for %s: %s", model_type, exc)
        return examples

    def _parse_jsonl(self, model_type: str, raw: str) -> List[TrainingExample]:
        """Parse JSON Lines output."""
        examples: List[TrainingExample] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
                inp = obj.get("input", "")
                out = obj.get("output", "")
                if isinstance(out, (dict, list)):
                    out = json.dumps(out)
                if inp and out:
                    examples.append(TrainingExample(
                        input=inp,
                        output=out,
                        model_type=model_type,
                        metadata=obj,
                    ))
            except json.JSONDecodeError:
                pass
        return examples

    def _generate_synthetic_fallback(
        self, model_type: str, count: int
    ) -> List[TrainingExample]:
        """Generate minimal synthetic examples when NLM is unavailable."""
        logger.info("Using synthetic fallback for %s (%d examples)", model_type, count)
        examples: List[TrainingExample] = []

        templates: Dict[str, List[tuple[str, str]]] = {
            "qa_evaluator": [
                ("How do I start the CosySim bedroom scene?", "ESSENTIAL"),
                ("What is the meaning of life?", "SKIP"),
                ("How does the interceptor pipeline work?", "ESSENTIAL"),
                ("What port does the Nexus KMS run on?", "ESSENTIAL"),
                ("Can you help me?", "SKIP"),
            ],
            "router_v2": [
                ("Search for interceptor docs", "nexus_search"),
                ("What port is LMStudio on?", "nexus_ask"),
                ("Start the bedroom scene", "scene_control"),
                ("Synthesize speech for Aria", "tts_request"),
                ("Run the backup now", "backup_request"),
            ],
            "syntax_fixer": [
                ("def foo()\n    return 1", "def foo():\n    return 1"),
                ('{"key": "value"', '{"key": "value"}'),
                ("import os\nos.path.exists(path)", "import os\nfound = os.path.exists(path)"),
            ],
            "conversation_analyzer": [
                ("I'm John, a Python developer working on AI agents",
                 '{"name":"John","tech_level":"expert","facts":["Python developer","works on AI agents"]}'),
                ("I've been using CosySim for 6 months",
                 '{"facts":["CosySim user, 6 months experience"]}'),
            ],
            "knowledge_synthesizer": [
                ("How does MCP state work?",
                 "MCP state is managed through the MCPFramework tree, a hierarchical key-value store synced to SQLite."),
            ],
        }

        base_examples = templates.get(model_type, [("sample input", "sample output")])
        for i in range(min(count, len(base_examples) * 10)):
            t = base_examples[i % len(base_examples)]
            examples.append(TrainingExample(
                input=t[0],
                output=t[1],
                model_type=model_type,
                source="synthetic_fallback",
                quality="bronze",
            ))
        return examples

    def _save_dataset(self, model_type: str, examples: List[TrainingExample]) -> str:
        """Save examples as JSONL and return path."""
        path = _DATASET_DIR / f"{model_type}_train.jsonl"
        _DATASET_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex.to_dict()) + "\n")
        logger.info("Saved %d examples to %s", len(examples), path)
        return str(path)

    def _store_metadata_in_nexus(
        self, model_type: str, count: int, path: str
    ) -> None:
        """Record dataset generation event in Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"Teacher Dataset: {model_type}",
                content=json.dumps({
                    "model_type": model_type,
                    "examples": count,
                    "path": path,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }),
                content_type="history",
                category="training",
            )
        except Exception as exc:
            logger.debug("Nexus store skipped: %s", exc)


# ──── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[TeacherPipeline] = None


def get_teacher_pipeline() -> TeacherPipeline:
    """Return the shared TeacherPipeline singleton."""
    global _instance
    if _instance is None:
        _instance = TeacherPipeline()
    return _instance
