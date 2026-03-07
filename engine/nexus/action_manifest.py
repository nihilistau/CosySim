"""Action Manifest helpers for structured pre-plan artifacts.

These helpers translate pre-plan Q&A into a small, dependency-aware manifest
that downstream agents can consume without reloading the entire task context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_FILE_PATTERN = re.compile(
    r"([A-Za-z0-9_./\\-]+\.(?:py|md|yaml|yml|json|html|js|css|ps1|txt))"
)


@dataclass
class ManifestStep:
    """Atomic action in an Action Manifest."""

    step_id: str
    action_type: str
    title: str
    target_file: str = ""
    dependencies: List[str] = field(default_factory=list)
    code_logic_summary: str = ""
    validation: List[str] = field(default_factory=list)
    source: str = ""
    source_question: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the step to a JSON-safe dictionary."""
        return {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "title": self.title,
            "target_file": self.target_file,
            "dependencies": list(self.dependencies),
            "code_logic_summary": self.code_logic_summary,
            "validation": list(self.validation),
            "source": self.source,
            "source_question": self.source_question,
        }


@dataclass
class ManifestMilestone:
    """Logical group of manifest steps."""

    milestone_id: str
    title: str
    goal: str
    step_ids: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the milestone to a JSON-safe dictionary."""
        return {
            "milestone_id": self.milestone_id,
            "title": self.title,
            "goal": self.goal,
            "step_ids": list(self.step_ids),
            "dependencies": list(self.dependencies),
        }


@dataclass
class ActionManifest:
    """Structured artifact generated from pre-plan Q&A."""

    manifest_id: str
    task: str
    summary: str
    context_files: List[str] = field(default_factory=list)
    steps: List[ManifestStep] = field(default_factory=list)
    milestones: List[ManifestMilestone] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the manifest to a JSON-safe dictionary."""
        return {
            "manifest_id": self.manifest_id,
            "task": self.task,
            "summary": self.summary,
            "context_files": list(self.context_files),
            "steps": [step.to_dict() for step in self.steps],
            "milestones": [milestone.to_dict() for milestone in self.milestones],
            "next_actions": list(self.next_actions),
        }


def build_preplan_manifest(
    task: str,
    qa_pairs: List[Dict[str, Any]],
    context_files: Optional[List[str]] = None,
) -> ActionManifest:
    """Build an Action Manifest from pre-plan Q&A pairs."""
    normalized_context = _normalize_context_files(context_files)
    manifest_id = f"preplan-{_slugify(task) or 'task'}"
    steps: List[ManifestStep] = []
    group_order: List[str] = []
    grouped_steps: Dict[str, List[ManifestStep]] = {}
    previous_step_id = ""

    for index, qa_pair in enumerate(qa_pairs, start=1):
        question = str(qa_pair.get("question", "")).strip()
        answer = str(qa_pair.get("answer", "")).strip()
        source = str(qa_pair.get("source", "")).strip()
        if not answer:
            continue

        action_type = _classify_action(question, answer)
        group = _milestone_group(action_type)
        if group not in group_order:
            group_order.append(group)
        grouped_steps.setdefault(group, [])

        step_id = f"step-{index:02d}"
        target_file = _extract_target_file(question, answer, normalized_context)
        step = ManifestStep(
            step_id=step_id,
            action_type=action_type,
            title=_build_step_title(question, action_type),
            target_file=target_file,
            dependencies=[previous_step_id] if previous_step_id else [],
            code_logic_summary=_truncate(_single_line(answer), limit=220),
            validation=_default_validation(action_type, target_file),
            source=source,
            source_question=question,
        )
        steps.append(step)
        grouped_steps[group].append(step)
        previous_step_id = step_id

    milestones = _build_milestones(group_order, grouped_steps)
    summary = _build_manifest_summary(task, steps)
    next_actions = [f"{step.step_id}: {step.title}" for step in steps[:3]]

    return ActionManifest(
        manifest_id=manifest_id,
        task=task,
        summary=summary,
        context_files=normalized_context,
        steps=steps,
        milestones=milestones,
        next_actions=next_actions,
    )


def _build_milestones(
    group_order: List[str],
    grouped_steps: Dict[str, List[ManifestStep]],
) -> List[ManifestMilestone]:
    """Build milestone groups from ordered step buckets."""
    labels = {
        "research": (
            "Capture grounded context",
            "Lock in the most relevant grounded context before code changes begin.",
        ),
        "implement": (
            "Execute code or runtime changes",
            "Apply the concrete edits and runtime actions implied by the pre-plan answers.",
        ),
        "validate": (
            "Validate the outcome",
            "Run the required tests and checks before handing work to a downstream agent.",
        ),
    }
    milestones: List[ManifestMilestone] = []
    previous_milestone_id = ""

    for index, group in enumerate(group_order, start=1):
        title, goal = labels.get(
            group,
            ("Advance the task", "Complete the planned work for this stage."),
        )
        milestone_id = f"milestone-{index:02d}"
        milestones.append(
            ManifestMilestone(
                milestone_id=milestone_id,
                title=title,
                goal=goal,
                step_ids=[step.step_id for step in grouped_steps.get(group, [])],
                dependencies=[previous_milestone_id] if previous_milestone_id else [],
            )
        )
        previous_milestone_id = milestone_id

    return milestones


def _normalize_context_files(context_files: Optional[List[str]]) -> List[str]:
    """Return a unique, order-preserving context file list."""
    ordered: List[str] = []
    for path in context_files or []:
        if isinstance(path, str) and path and path not in ordered:
            ordered.append(path)
    return ordered


def _slugify(value: str) -> str:
    """Normalize text into a filesystem and ID friendly slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def _single_line(value: str) -> str:
    """Collapse repeated whitespace into a single line."""
    return " ".join(value.split())


def _truncate(value: str, *, limit: int) -> str:
    """Truncate a string without splitting mid-word when possible."""
    if len(value) <= limit:
        return value
    shortened = value[: limit - 3].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return f"{shortened}..."


def _build_step_title(question: str, action_type: str) -> str:
    """Turn a question into a compact step title."""
    cleaned = question.rstrip(" ?")
    if cleaned:
        return _truncate(cleaned, limit=80)
    return f"{action_type.title()} follow-up"


def _extract_target_file(
    question: str,
    answer: str,
    context_files: List[str],
) -> str:
    """Choose the most relevant target file for a manifest step."""
    combined = f"{question}\n{answer}"
    match = _FILE_PATTERN.search(combined)
    if match:
        return match.group(1)

    lowered = combined.lower()
    for path in context_files:
        filename = path.split("\\")[-1].split("/")[-1].lower()
        if filename and filename in lowered:
            return path

    if len(context_files) == 1:
        return context_files[0]
    return ""


def _classify_action(question: str, answer: str) -> str:
    """Infer the best-fit action type for a pre-plan answer."""
    lowered = f"{question} {answer}".lower()
    if any(token in lowered for token in ("test", "validate", "verify", "health check", "regression")):
        return "TEST"
    if any(token in lowered for token in ("run ", "command", "shell", "benchmark", "launch", "restart")):
        return "SHELL"
    if any(
        token in lowered
        for token in (
            "edit",
            "update",
            "patch",
            "change",
            "implement",
            "wire",
            "route",
            "module",
            "scene",
            "skill",
            "file",
            "class",
            "function",
        )
    ):
        return "EDIT"
    return "RESEARCH"


def _milestone_group(action_type: str) -> str:
    """Map step action types onto coarse milestones."""
    if action_type == "RESEARCH":
        return "research"
    if action_type == "TEST":
        return "validate"
    return "implement"


def _default_validation(action_type: str, target_file: str) -> List[str]:
    """Create default validation guidance for a step."""
    if action_type == "TEST":
        return ["The targeted tests or health checks must pass before the next step begins."]
    if action_type == "SHELL":
        return ["Capture command output and confirm the expected runtime state transition."]
    if action_type == "EDIT":
        if target_file:
            return [f"Run focused regression coverage for {target_file} after the edit lands."]
        return ["Run focused regression coverage for the edited surface after the change lands."]
    return ["Confirm the grounded guidance is stored in Nexus and reusable by downstream agents."]


def _build_manifest_summary(task: str, steps: List[ManifestStep]) -> str:
    """Create a compact manifest summary."""
    if not steps:
        return f"Action manifest scaffold for {task} with no executable steps yet."
    action_counts: Dict[str, int] = {}
    for step in steps:
        action_counts[step.action_type] = action_counts.get(step.action_type, 0) + 1
    counts = ", ".join(
        f"{count} {action_type.lower()}"
        for action_type, count in sorted(action_counts.items())
    )
    return f"{task}: {len(steps)} planned step(s) across {counts}."
