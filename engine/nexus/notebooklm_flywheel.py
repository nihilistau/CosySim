"""NotebookLM control flywheel for the Copilot/Nexus control plane.

This module turns the dedicated control notebook into a repeatable orchestration
surface:

1. ask grounded control-plane questions against the control notebook
2. run a second structured report prompt to emit a strict JSON artifact
3. store the artifact and context packet in Nexus
4. create actionable TaskScheduler items for downstream agents
5. feed the TrainingFlywheel with the generated Q&A and task envelopes

The browser-backed NotebookLM path remains the source of truth. Studio helpers
are used first, with the browser-chat path as an explicit fallback when needed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from engine.config import get_config
from engine.nexus.action_manifest import build_preplan_manifest
from engine.nexus.client import get_nexus_client
from engine.nexus.task_scheduler import (
    AgentTask,
    TaskComplexity,
    TaskPriority,
    get_task_scheduler,
)
from engine.nexus.training_flywheel import get_training_flywheel

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOOTSTRAP_STATE_FILE = REPO_ROOT / ".github" / "hooks" / "logs" / "notebook_bootstrap.json"
STATE_FILE = REPO_ROOT / ".github" / "hooks" / "logs" / "notebooklm_flywheel.json"

CONTROL_NOTEBOOK_NAME = "copilot-system-control"
CONTROL_NOTEBOOK_DESCRIPTION = (
    "Control-plane notebook for Copilot, Nexus, NotebookLM, hooks, scheduler, "
    "auth, and downstream local-agent orchestration."
)
DEFAULT_MULTI_ASK_QUESTIONS = [
    (
        "Summarize the current Copilot/Nexus/NotebookLM control-plane state in 6 "
        "grounded bullet points. Prefer concrete modules, files, and runtime "
        "surfaces over general advice."
    ),
    (
        "List the highest-value integration gaps or brittle control-plane surfaces "
        "that should be addressed next so the system keeps compounding instead of "
        "re-discovering context."
    ),
    (
        "List the most important auth freshness, credential keepalive, checkpoint, "
        "compaction, scheduler, or browser-session actions the system should keep "
        "checking to stay reliable."
    ),
]

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(?P<body>[\s\S]*?)```", re.IGNORECASE)


@dataclass
class FlywheelTaskSpec:
    """Structured task emitted by the control-notebook report."""

    title: str
    template: str = "feature"
    description: str = ""
    target_files: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    priority: str = "medium"
    complexity: str = "medium"
    allowed_operations: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlywheelTaskSpec":
        """Normalize a task specification from parsed JSON."""
        return cls(
            title=str(data.get("title", "")).strip(),
            template=str(data.get("template", "feature")).strip() or "feature",
            description=str(data.get("description", "")).strip(),
            target_files=_string_list(data.get("target_files", [])),
            tags=_string_list(data.get("tags", [])),
            priority=str(data.get("priority", "medium")).strip().lower() or "medium",
            complexity=str(data.get("complexity", "medium")).strip().lower() or "medium",
            allowed_operations=_string_list(data.get("allowed_operations", [])),
            depends_on=_string_list(data.get("depends_on", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the task spec for storage."""
        return {
            "title": self.title,
            "template": self.template,
            "description": self.description,
            "target_files": list(self.target_files),
            "tags": list(self.tags),
            "priority": self.priority,
            "complexity": self.complexity,
            "allowed_operations": list(self.allowed_operations),
            "depends_on": list(self.depends_on),
        }


@dataclass
class NotebookLMFlywheelArtifact:
    """Persistable control artifact emitted from the NotebookLM flywheel."""

    notebook_url: str
    notebook_ref: str
    generated_at: str
    trigger_reason: str
    qa_method: str
    report_method: str
    summary: str
    system_state: List[str] = field(default_factory=list)
    priorities: List[str] = field(default_factory=list)
    keepalive_actions: List[str] = field(default_factory=list)
    distillation_topics: List[str] = field(default_factory=list)
    context_packet: Dict[str, Any] = field(default_factory=dict)
    qa_pairs: List[Dict[str, str]] = field(default_factory=list)
    tasks: List[FlywheelTaskSpec] = field(default_factory=list)
    action_manifest: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full artifact."""
        return {
            "notebook_url": self.notebook_url,
            "notebook_ref": self.notebook_ref,
            "generated_at": self.generated_at,
            "trigger_reason": self.trigger_reason,
            "qa_method": self.qa_method,
            "report_method": self.report_method,
            "summary": self.summary,
            "system_state": list(self.system_state),
            "priorities": list(self.priorities),
            "keepalive_actions": list(self.keepalive_actions),
            "distillation_topics": list(self.distillation_topics),
            "context_packet": dict(self.context_packet),
            "qa_pairs": list(self.qa_pairs),
            "tasks": [task.to_dict() for task in self.tasks],
            "action_manifest": dict(self.action_manifest),
            "session_id": self.session_id,
        }

    def hash_payload(self) -> Dict[str, Any]:
        """Return the stable subset used for idempotence hashing."""
        return {
            "notebook_url": self.notebook_url,
            "summary": self.summary,
            "system_state": list(self.system_state),
            "priorities": list(self.priorities),
            "keepalive_actions": list(self.keepalive_actions),
            "distillation_topics": list(self.distillation_topics),
            "context_packet": dict(self.context_packet),
            "qa_pairs": list(self.qa_pairs),
            "tasks": [task.to_dict() for task in self.tasks],
            "action_manifest": dict(self.action_manifest),
        }


class NotebookLMFlywheel:
    """Orchestrate the control notebook into Nexus artifacts and agent tasks."""

    def __init__(
        self,
        config: Optional[Any] = None,
        *,
        state_path: Optional[Path] = None,
        bootstrap_state_path: Optional[Path] = None,
    ) -> None:
        self._config = config or get_config()
        self._state_path = Path(state_path or STATE_FILE)
        self._bootstrap_state_path = Path(bootstrap_state_path or BOOTSTRAP_STATE_FILE)

    def run(
        self,
        *,
        notebook_url: str = "",
        force: bool = False,
        reason: str = "manual",
    ) -> Dict[str, Any]:
        """Run the full control-notebook flywheel."""
        if not self._config.get("notebooklm.flywheel.enabled", True):
            return {"status": "skipped", "reason": "disabled"}

        state = self._load_state()
        if not force:
            interval_skip = self._should_skip_for_interval(state)
            if interval_skip:
                return interval_skip

        resolved_url = notebook_url.strip() or self._resolve_control_notebook_url()
        if not resolved_url:
            return {"status": "error", "error": "Control notebook URL is unavailable"}

        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge

        bridge = get_nlm_node_bridge()
        health = bridge.get_health()
        if health.get("error"):
            return {"status": "error", "error": f"NLM health check failed: {health['error']}"}
        if health.get("authenticated") is False:
            return {"status": "error", "error": "NotebookLM is not authenticated"}

        notebook_ref = self._ensure_notebook_reference(bridge, resolved_url)
        questions = self._multi_ask_questions()
        qa_pairs, session_id, qa_method, qa_warning = self._run_multi_ask_chain(
            bridge,
            notebook_ref=notebook_ref,
            notebook_url=resolved_url,
            questions=questions,
            prior_session_id=str(state.get("last_session_id", "")),
        )
        if not qa_pairs:
            return {
                "status": "error",
                "error": "Could not collect grounded NotebookLM answers",
                "qa_warning": qa_warning,
            }

        report_prompt = self._build_report_prompt(qa_pairs)
        report_payload, report_method, raw_report = self._run_report_chain(
            bridge,
            notebook_ref=notebook_ref,
            notebook_url=resolved_url,
            prompt=report_prompt,
        )

        artifact = self._build_artifact(
            notebook_url=resolved_url,
            notebook_ref=notebook_ref,
            qa_pairs=qa_pairs,
            qa_method=qa_method,
            report_method=report_method,
            report_payload=report_payload,
            reason=reason,
            session_id=session_id,
        )
        artifact_hash = _stable_hash(artifact.hash_payload())
        if not force and artifact_hash == str(state.get("last_artifact_hash", "")):
            return {
                "status": "skipped",
                "reason": "artifact_unchanged",
                "notebook_url": resolved_url,
                "artifact_hash": artifact_hash,
            }

        nexus = get_nexus_client()
        qa_store_count = self._store_qa_pairs(nexus, qa_pairs)
        artifact_entry_id, context_entry_id, report_entry_id = self._store_artifacts(
            nexus=nexus,
            artifact=artifact,
            raw_report=raw_report,
            artifact_hash=artifact_hash,
        )

        scheduler = get_task_scheduler()
        try:
            scheduler.load_from_nexus()
        except Exception as exc:
            logger.debug("TaskScheduler load_from_nexus failed: %s", exc)
        created_tasks, task_skips = self._create_tasks(scheduler, artifact.tasks, state=state)

        distill_result = bridge.distill_to_nexus(
            notebook_ref,
            nexus_category=self._config.get(
                "notebooklm.flywheel.distill_category",
                "notebooklm-flywheel",
            ),
            nexus_url=self._config.get("nexus.base_url", "http://localhost:8700"),
        ) or {}
        distilled_pairs = int(
            distill_result.get("nexus_count")
            or distill_result.get("total_stored")
            or distill_result.get("stored_count")
            or 0
        )

        warnings = [warning for warning in [qa_warning] if warning]
        if distill_result.get("error"):
            warnings.append(str(distill_result["error"]))

        training_stats = {"qa_examples": 0, "nlm_examples": 0, "task_examples": 0}
        try:
            training_stats = self._capture_training(qa_pairs=qa_pairs, created_tasks=created_tasks)
        except Exception as exc:
            warnings.append(f"training_capture_failed: {exc}")

        result = {
            "status": "ok",
            "notebook_url": resolved_url,
            "notebook_ref": notebook_ref,
            "artifact_hash": artifact_hash,
            "artifact_entry_id": artifact_entry_id,
            "context_entry_id": context_entry_id,
            "report_entry_id": report_entry_id,
            "qa_pairs": len(qa_pairs),
            "qa_store_count": qa_store_count,
            "qa_method": qa_method,
            "report_method": report_method,
            "tasks_created": len(created_tasks),
            "task_ids": [task.id for task in created_tasks],
            "task_skips": task_skips,
            "distilled_pairs": distilled_pairs,
            "training": training_stats,
            "warnings": warnings,
            "reason": reason,
        }
        self._update_state(
            state=state,
            result=result,
            session_id=session_id,
            artifact_hash=artifact_hash,
        )
        return result

    def _load_state(self) -> Dict[str, Any]:
        """Load flywheel state from disk."""
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("Invalid NotebookLM flywheel state file: %s", self._state_path)
        return {"task_fingerprints": {}, "runs": []}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Persist flywheel state to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _resolve_control_notebook_url(self) -> str:
        """Resolve the control notebook URL from notebook bootstrap state."""
        if not self._bootstrap_state_path.exists():
            return ""
        try:
            state = json.loads(self._bootstrap_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Invalid notebook bootstrap state file: %s", self._bootstrap_state_path)
            return ""

        detail = (
            state.get("notebooks_detail", {})
            .get(CONTROL_NOTEBOOK_NAME, {})
        )
        notebook_url = str(
            detail.get("notebook_url")
            or state.get("notebooks", {}).get(CONTROL_NOTEBOOK_NAME)
            or ""
        ).strip()
        return notebook_url

    def _should_skip_for_interval(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a skip result when the minimum run interval has not elapsed."""
        min_hours = float(self._config.get("notebooklm.flywheel.min_interval_hours", 8) or 0)
        if min_hours <= 0:
            return None

        last_run_at = _parse_iso_timestamp(str(state.get("last_run_at", "")))
        if not last_run_at:
            return None

        earliest = last_run_at + timedelta(hours=min_hours)
        now = datetime.now(timezone.utc)
        if now >= earliest:
            return None
        return {
            "status": "skipped",
            "reason": "interval_not_elapsed",
            "next_run_at": earliest.isoformat(),
        }

    def _ensure_notebook_reference(self, bridge: Any, notebook_url: str) -> str:
        """Ensure the control notebook is registered with the Node bridge."""
        result = bridge.add_notebook(
            notebook_url,
            name="Copilot System Control",
            description=CONTROL_NOTEBOOK_DESCRIPTION,
            topics=["copilot", "nexus", "notebooklm", "control-plane"],
        ) or {}
        notebook_ref = str(
            result.get("id")
            or result.get("notebook_id")
            or ""
        ).strip()
        if notebook_ref:
            return notebook_ref
        raise ValueError(
            "Control notebook could not be registered with the NotebookLM bridge: "
            f"{result.get('error', 'missing notebook id')}"
        )

    def _multi_ask_questions(self) -> List[str]:
        """Return the configured first-pass control questions."""
        configured = self._config.get("notebooklm.flywheel.multi_ask_questions", [])
        questions = _string_list(configured)
        return questions or list(DEFAULT_MULTI_ASK_QUESTIONS)

    def _build_report_prompt(self, qa_pairs: Sequence[Dict[str, str]]) -> str:
        """Build the second-pass strict JSON report prompt."""
        qa_context = json.dumps(list(qa_pairs), indent=2)
        max_tasks = int(self._config.get("notebooklm.flywheel.max_tasks", 6) or 6)
        return (
            "You are generating a control-plane action artifact for the CosySim system.\n"
            "Use the notebook sources plus the grounded first-pass Q&A below.\n\n"
            f"Grounded first-pass Q&A:\n{qa_context}\n\n"
            "Return ONLY valid JSON with this exact top-level shape:\n"
            "{\n"
            '  "summary": "short paragraph",\n'
            '  "system_state": ["bullet", "..."],\n'
            '  "priorities": ["priority", "..."],\n'
            '  "keepalive_actions": ["action", "..."],\n'
            '  "distillation_topics": ["topic", "..."],\n'
            '  "context_packet": {\n'
            '    "immediate_summary": "startup-ready summary",\n'
            '    "startup_focus": ["focus item", "..."],\n'
            '    "watch_surfaces": ["surface", "..."]\n'
            "  },\n"
            '  "tasks": [\n'
            "    {\n"
            '      "title": "concrete task title",\n'
            '      "template": "feature",\n'
            '      "description": "small executable description",\n'
            '      "target_files": ["repo/relative/path.py"],\n'
            '      "tags": ["copilot", "notebooklm"],\n'
            '      "priority": "medium",\n'
            '      "complexity": "medium",\n'
            '      "allowed_operations": ["read", "edit", "test"],\n'
            '      "depends_on": ["title of earlier task"]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Requirements:\n"
            f"- Emit 3 to {max_tasks} tasks.\n"
            "- Use only these template names: bug-fix, feature, refactor, test, "
            "doc-update, skill-add, scene-polish, knowledge-refresh.\n"
            "- Prefer control-plane, Nexus, NotebookLM, auth freshness, hooks, "
            "scheduler, and training-flywheel work.\n"
            "- Include real repo-relative file paths where possible.\n"
            "- Keep tasks dependency-aware and small enough for local agents.\n"
            "- If something is a keepalive/monitoring action rather than a code "
            "change, keep it under keepalive_actions instead of creating a vague task.\n"
            "- Do not include markdown fences, prose before JSON, or comments."
        )

    def _run_multi_ask_chain(
        self,
        bridge: Any,
        *,
        notebook_ref: str,
        notebook_url: str,
        questions: Sequence[str],
        prior_session_id: str,
    ) -> Tuple[List[Dict[str, str]], str, str, str]:
        """Run the first-pass grounded question chain."""
        result = bridge.ask_multi(
            notebook_id=notebook_ref,
            questions=list(questions),
            session_id=prior_session_id,
        ) or {}
        answers = _normalize_multi_answers(result.get("answers", []), questions)
        if answers:
            session_id = str(answers[-1].get("session_id", prior_session_id)).strip()
            return answers, session_id, "ask_multi", ""

        batch = bridge.ask_batch(notebook_url, list(questions), keep_session=True) or []
        answers = []
        batch_session_id = prior_session_id
        for question, item in zip(questions, batch):
            answer = str(item.get("answer", "")).strip() if isinstance(item, dict) else str(item).strip()
            if not answer:
                continue
            batch_session_id = str(item.get("session_id", batch_session_id)).strip()
            answers.append(
                {
                    "question": question,
                    "answer": answer,
                    "session_id": batch_session_id,
                }
            )
        warning = str(result.get("error") or "ask_multi returned no answers").strip()
        return answers, batch_session_id, "chat_batch_fallback", warning

    def _run_report_chain(
        self,
        bridge: Any,
        *,
        notebook_ref: str,
        notebook_url: str,
        prompt: str,
    ) -> Tuple[Dict[str, Any], str, str]:
        """Run the second-pass report generation step."""
        report = bridge.generate_report_with_prompt(
            notebook_id=notebook_ref,
            custom_prompt=prompt,
            content_type="report",
        ) or {}
        raw_text = _extract_text_payload(report)
        parsed = _parse_json_payload(raw_text)
        if parsed is not None:
            return parsed, "studio_report", raw_text

        fallback = bridge.ask_question(notebook_url, prompt, reset_history=True) or {}
        raw_text = _extract_text_payload(fallback)
        parsed = _parse_json_payload(raw_text)
        if parsed is not None:
            return parsed, "chat_report_fallback", raw_text

        raise ValueError("NotebookLM report prompt did not return valid JSON")

    def _build_artifact(
        self,
        *,
        notebook_url: str,
        notebook_ref: str,
        qa_pairs: Sequence[Dict[str, str]],
        qa_method: str,
        report_method: str,
        report_payload: Dict[str, Any],
        reason: str,
        session_id: str,
    ) -> NotebookLMFlywheelArtifact:
        """Normalize parsed NotebookLM output into a typed artifact."""
        raw_tasks = report_payload.get("tasks", [])
        task_specs = []
        if isinstance(raw_tasks, list):
            task_specs = [FlywheelTaskSpec.from_dict(item) for item in raw_tasks if isinstance(item, dict)]
        task_specs = [task for task in task_specs if task.title and task.description]
        if not task_specs:
            task_specs = self._task_specs_from_manifest(
                build_preplan_manifest(
                    "NotebookLM control flywheel",
                    list(qa_pairs),
                    context_files=[],
                )
            )

        context_files = []
        for task in task_specs:
            for path in task.target_files:
                if path not in context_files:
                    context_files.append(path)
        manifest = build_preplan_manifest(
            "NotebookLM control flywheel",
            list(qa_pairs),
            context_files=context_files,
        )

        return NotebookLMFlywheelArtifact(
            notebook_url=notebook_url,
            notebook_ref=notebook_ref,
            generated_at=_now_iso(),
            trigger_reason=reason,
            qa_method=qa_method,
            report_method=report_method,
            summary=str(report_payload.get("summary", "")).strip(),
            system_state=_string_list(report_payload.get("system_state", [])),
            priorities=_string_list(report_payload.get("priorities", [])),
            keepalive_actions=_string_list(report_payload.get("keepalive_actions", [])),
            distillation_topics=_string_list(report_payload.get("distillation_topics", [])),
            context_packet=_normalize_context_packet(report_payload.get("context_packet", {})),
            qa_pairs=[{"question": pair["question"], "answer": pair["answer"]} for pair in qa_pairs],
            tasks=task_specs,
            action_manifest=manifest.to_dict(),
            session_id=session_id,
        )

    def _task_specs_from_manifest(self, manifest: Any) -> List[FlywheelTaskSpec]:
        """Fallback conversion from Action Manifest steps into task specs."""
        manifest_dict = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest or {})
        specs: List[FlywheelTaskSpec] = []
        action_map = {
            "RESEARCH": "knowledge-refresh",
            "EDIT": "feature",
            "SHELL": "refactor",
            "TEST": "test",
        }
        operations_map = {
            "RESEARCH": ["read"],
            "EDIT": ["read", "edit", "test"],
            "SHELL": ["read", "edit", "test"],
            "TEST": ["read", "create", "test"],
        }
        for step in manifest_dict.get("steps", []):
            title = str(step.get("title", "")).strip()
            summary = str(step.get("code_logic_summary", "")).strip()
            if not title or not summary:
                continue
            action_type = str(step.get("action_type", "EDIT")).upper()
            specs.append(
                FlywheelTaskSpec(
                    title=title,
                    template=action_map.get(action_type, "feature"),
                    description=summary,
                    target_files=_string_list([step.get("target_file", "")]),
                    tags=["notebooklm-flywheel", action_type.lower()],
                    priority="medium",
                    complexity="medium",
                    allowed_operations=operations_map.get(action_type, ["read", "edit", "test"]),
                    depends_on=[],
                )
            )
        return specs[: int(self._config.get("notebooklm.flywheel.max_tasks", 6) or 6)]

    def _store_qa_pairs(self, nexus: Any, qa_pairs: Sequence[Dict[str, str]]) -> int:
        """Store grounded first-pass Q&A pairs in Nexus."""
        stored = 0
        for pair in qa_pairs:
            entry_id = nexus.add_qa(
                pair["question"],
                pair["answer"],
                category="notebooklm-flywheel",
                tags=["copilot", "notebooklm", "flywheel", "control"],
                quality_score=0.75,
                namespace="copilot",
            )
            if entry_id:
                stored += 1
        return stored

    def _store_artifacts(
        self,
        *,
        nexus: Any,
        artifact: NotebookLMFlywheelArtifact,
        raw_report: str,
        artifact_hash: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Persist the flywheel artifact, context packet, and raw report to Nexus."""
        artifact_entry_id = nexus.add_entry(
            title=f"NotebookLM Control Flywheel — {artifact.generated_at}",
            content=json.dumps(artifact.to_dict(), indent=2),
            content_type="plan",
            category="copilot-preplan",
            tags=["copilot", "notebooklm", "flywheel", "control", artifact_hash[:12]],
            namespace="copilot",
        )
        context_entry_id = nexus.add_entry(
            title=f"Control Flywheel Context Packet — {artifact.generated_at}",
            content=json.dumps(artifact.context_packet, indent=2),
            content_type="plan",
            category="copilot-preplan",
            tags=["copilot", "context", "startup", "notebooklm"],
            namespace="copilot",
        )
        report_entry_id = nexus.add_entry(
            title=f"NotebookLM Control Flywheel Raw Report — {artifact.generated_at}",
            content=raw_report,
            content_type="note",
            category="copilot-preplan",
            tags=["copilot", "notebooklm", "flywheel", "raw-report"],
            namespace="copilot",
        )
        if not artifact_entry_id or not context_entry_id:
            raise RuntimeError("NotebookLM flywheel artifact could not be stored in Nexus")
        return artifact_entry_id, context_entry_id, report_entry_id

    def _create_tasks(
        self,
        scheduler: Any,
        task_specs: Sequence[FlywheelTaskSpec],
        *,
        state: Dict[str, Any],
    ) -> Tuple[List[AgentTask], List[str]]:
        """Create TaskScheduler entries from the parsed task specs."""
        created: List[AgentTask] = []
        skipped: List[str] = []
        known_fingerprints = dict(state.get("task_fingerprints", {}))
        known_fingerprints.update(self._existing_task_fingerprints(scheduler))
        title_to_id = {
            task.title: task.id
            for task in getattr(scheduler, "_tasks", {}).values()
            if getattr(task, "title", "")
        }
        template_defaults = self._template_defaults()

        for spec in task_specs[: int(self._config.get("notebooklm.flywheel.max_tasks", 6) or 6)]:
            fingerprint = _task_fingerprint(spec)
            if fingerprint in known_fingerprints:
                skipped.append(spec.title)
                continue

            defaults = template_defaults.get(spec.template, {})
            description = defaults.get("description", "")
            if spec.description:
                description = f"{description}\n\n{spec.description}".strip()

            task = scheduler.create_task(
                title=spec.title,
                description=description,
                priority=_priority_from_text(spec.priority, defaults.get("priority", TaskPriority.MEDIUM)),
                complexity=_complexity_from_text(
                    spec.complexity,
                    defaults.get("complexity", TaskComplexity.MEDIUM),
                ),
                allowed_operations=spec.allowed_operations or list(defaults.get("operations", ["read", "edit", "test"])),
                target_files=spec.target_files,
                tags=_merge_tags(defaults.get("tags", []), spec.tags, ["notebooklm-flywheel", "from-template", spec.template]),
                depends_on=[title_to_id[title] for title in spec.depends_on if title in title_to_id],
            )
            known_fingerprints[fingerprint] = {
                "task_id": task.id,
                "title": task.title,
                "created_at": _now_iso(),
            }
            state.setdefault("task_fingerprints", {})[fingerprint] = known_fingerprints[fingerprint]
            title_to_id[task.title] = task.id
            created.append(task)

        return created, skipped

    def _existing_task_fingerprints(self, scheduler: Any) -> Dict[str, Dict[str, str]]:
        """Build a fingerprint map from tasks already present in the scheduler."""
        fingerprints: Dict[str, Dict[str, str]] = {}
        for task in getattr(scheduler, "_tasks", {}).values():
            target_files = list(getattr(task, "target_files", []) or [])
            spec = FlywheelTaskSpec(
                title=str(getattr(task, "title", "")).strip(),
                description=str(getattr(task, "description", "")).strip(),
                target_files=target_files,
                tags=list(getattr(task, "tags", []) or []),
            )
            if not spec.title or not spec.description:
                continue
            fingerprints[_task_fingerprint(spec)] = {
                "task_id": str(getattr(task, "id", "")),
                "title": spec.title,
                "created_at": str(getattr(task, "created_at", "")),
            }
        return fingerprints

    def _capture_training(
        self,
        *,
        qa_pairs: Sequence[Dict[str, str]],
        created_tasks: Sequence[AgentTask],
    ) -> Dict[str, int]:
        """Push NotebookLM outputs into the training flywheel."""
        training = get_training_flywheel()
        qa_count = 0
        for pair in qa_pairs:
            if training.collect_from_qa(
                pair["question"],
                pair["answer"],
                source="notebooklm-flywheel",
                confidence=0.75,
                model="notebooklm",
            ):
                qa_count += 1

        conversation: List[Dict[str, str]] = []
        for pair in qa_pairs:
            conversation.append({"role": "user", "content": pair["question"]})
            conversation.append({"role": "assistant", "content": pair["answer"]})
        nlm_ids = training.collect_from_nlm(conversation, topic="copilot-system-control") if conversation else []

        task_count = 0
        for task in created_tasks:
            result_payload = json.dumps(
                {
                    "allowed_operations": list(getattr(task, "allowed_operations", []) or []),
                    "target_files": list(getattr(task, "target_files", []) or []),
                    "depends_on": list(getattr(task, "depends_on", []) or []),
                    "tags": list(getattr(task, "tags", []) or []),
                },
                indent=2,
            )
            if training.collect_from_task(task, result_payload, model="notebooklm-flywheel"):
                task_count += 1

        return {
            "qa_examples": qa_count,
            "nlm_examples": sum(1 for item in nlm_ids if item),
            "task_examples": task_count,
        }

    def _template_defaults(self) -> Dict[str, Dict[str, Any]]:
        """Return TaskScheduler template defaults when available."""
        from engine.nexus.task_scheduler import TaskScheduler

        return TaskScheduler._get_templates()  # type: ignore[attr-defined]

    def _update_state(
        self,
        *,
        state: Dict[str, Any],
        result: Dict[str, Any],
        session_id: str,
        artifact_hash: str,
    ) -> None:
        """Persist the last successful flywheel run."""
        state["last_run_at"] = _now_iso()
        state["last_session_id"] = session_id
        state["last_artifact_hash"] = artifact_hash
        state["last_result"] = result
        history = list(state.get("runs", []))
        history.append(
            {
                "ran_at": state["last_run_at"],
                "artifact_hash": artifact_hash,
                "tasks_created": result.get("tasks_created", 0),
                "notebook_url": result.get("notebook_url", ""),
                "reason": result.get("reason", ""),
            }
        )
        state["runs"] = history[-10:]
        self._save_state(state)


def run_control_notebook_flywheel(
    *,
    notebook_url: str = "",
    force: bool = False,
    reason: str = "manual",
) -> Dict[str, Any]:
    """Convenience entry point for the control-notebook flywheel."""
    flywheel = NotebookLMFlywheel()
    return flywheel.run(notebook_url=notebook_url, force=force, reason=reason)


def _extract_notebook_id(notebook_url: str) -> str:
    """Extract the NotebookLM UUID from a notebook URL."""
    return notebook_url.rstrip("/").split("/")[-1].split("?")[0]


def _extract_text_payload(payload: Dict[str, Any]) -> str:
    """Extract the most likely text body from a NotebookLM response payload."""
    for key in ("content", "answer", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(payload, indent=2)


def _parse_json_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    """Parse the first valid JSON object from a NotebookLM text payload."""
    candidates = [raw_text.strip()]
    candidates.extend(match.group("body").strip() for match in _JSON_FENCE_PATTERN.finditer(raw_text))

    for candidate in candidates:
        parsed = _try_parse_json(candidate)
        if isinstance(parsed, dict):
            return parsed
        extracted = _extract_balanced_json(candidate)
        if extracted is None:
            continue
        parsed = _try_parse_json(extracted)
        if isinstance(parsed, dict):
            return parsed
    return None


def _try_parse_json(text: str) -> Optional[Any]:
    """Attempt to parse a JSON string."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_balanced_json(text: str) -> Optional[str]:
    """Extract the first balanced JSON object from freeform text."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _normalize_multi_answers(
    answers: Iterable[Dict[str, Any]],
    questions: Sequence[str],
) -> List[Dict[str, str]]:
    """Normalize ask_multi answers into a stable list of question/answer pairs."""
    normalized: List[Dict[str, str]] = []
    for index, item in enumerate(answers):
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer", "")).strip()
        if not answer:
            continue
        fallback_question = questions[index] if index < len(questions) else ""
        normalized.append(
            {
                "question": str(item.get("question") or fallback_question).strip(),
                "answer": answer,
                "session_id": str(item.get("session_id", "")).strip(),
            }
        )
    return normalized


def _normalize_context_packet(payload: Any) -> Dict[str, Any]:
    """Normalize the context packet section from the NotebookLM report."""
    data = payload if isinstance(payload, dict) else {}
    return {
        "immediate_summary": str(data.get("immediate_summary", "")).strip(),
        "startup_focus": _string_list(data.get("startup_focus", [])),
        "watch_surfaces": _string_list(data.get("watch_surfaces", [])),
    }


def _stable_hash(payload: Dict[str, Any]) -> str:
    """Create a stable hash for a JSON-safe payload."""
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _task_fingerprint(spec: FlywheelTaskSpec) -> str:
    """Build an idempotence fingerprint for a task spec."""
    return _stable_hash(
        {
            "title": spec.title,
            "description": spec.description,
            "target_files": sorted(spec.target_files),
        }
    )[:16]


def _priority_from_text(value: str, default: Any) -> int:
    """Map a string priority to TaskPriority."""
    mapping = {
        "critical": TaskPriority.CRITICAL,
        "high": TaskPriority.HIGH,
        "medium": TaskPriority.MEDIUM,
        "low": TaskPriority.LOW,
        "background": TaskPriority.BACKGROUND,
    }
    return int(mapping.get(value, default))


def _complexity_from_text(value: str, default: Any) -> str:
    """Map a string complexity to TaskComplexity."""
    mapping = {
        "low": TaskComplexity.LOW,
        "medium": TaskComplexity.MEDIUM,
        "high": TaskComplexity.HIGH,
    }
    return str(mapping.get(value, default))


def _merge_tags(*groups: Iterable[str]) -> List[str]:
    """Merge tag groups while preserving order."""
    merged: List[str] = []
    for group in groups:
        for tag in group:
            text = str(tag).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _string_list(raw: Any) -> List[str]:
    """Normalize an arbitrary input into a list of strings."""
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if not isinstance(raw, list):
        return []
    values: List[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            values.append(text)
    return values


def _parse_iso_timestamp(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()
