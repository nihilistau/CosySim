"""Local Agent Bridge — connects LMStudio local models to the CosySim task system.

Version: v1.50.2 [2026-03-24]

Change Log:
    v1.50.2 [2026-03-24] — Add build_agent_registry(), agent feedback on task completion

Provides a clean interface for local LMStudio agents to:
- Discover and claim tasks appropriate for their model size
- Retrieve full task context (instructions, examples, relevant Nexus knowledge)
- Execute tasks with Nexus consultation at each step
- Report results and store artifacts back in Nexus

Model size routing:
    - router  (270M)  → classify, triage, route
    - mini    (0.6–1B) → simple edits, data extraction, formatting
    - worker  (3–9B)  → implementation, testing, analysis
    - expert  (14B+)  → architecture, complex reasoning, review

Usage::

    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    bridge = get_local_agent_bridge()

    # Agent discovers what it can work on
    tasks = bridge.get_ready_tasks(model_size="worker", limit=5)

    # Claim a task
    task = bridge.claim_task(task_id="abc1234", agent_id="worker-qwen-7b")

    # Load everything needed to execute
    ctx = bridge.get_task_context(task_id="abc1234")

    # Mark complete
    bridge.complete_task(task_id="abc1234", result="Implemented 3 skills. Tests pass.")
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_bridge_instance: Optional["LocalAgentBridge"] = None
_bridge_lock = threading.Lock()

# ── Model size → task complexity mapping ─────────────────────────────────

_MODEL_COMPLEXITY_MAP: Dict[str, List[str]] = {
    "router": ["low"],
    "mini": ["low"],
    "worker": ["low", "medium"],
    "expert": ["low", "medium", "high"],
}

# Max tasks per model claim in one session
_MAX_CLAIM_BATCH = 3

# v1.50.2 [2026-03-24] — Model size parsing patterns
import re
_SIZE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[bB]", re.IGNORECASE)


def _parse_model_size(model: Any) -> float:
    """Extract model size in billions from model metadata or ID string.

    Tries: model.params, model.id, str(model) for patterns like '7B', '0.5b', '14B'.
    Returns 0.0 if size cannot be determined.
    """
    # Try numeric attribute first
    for attr in ("params", "parameters", "size"):
        val = getattr(model, attr, None)
        if isinstance(val, (int, float)) and val > 0:
            return float(val) if val < 1000 else val / 1e9

    # Try string parsing from id or str representation
    for source in (getattr(model, "id", ""), str(model)):
        match = _SIZE_PATTERN.search(source)
        if match:
            return float(match.group(1))

    return 0.0

# Nexus context chunks to include per task
_NEXUS_CONTEXT_LIMIT = 5


class LocalAgentBridge:
    """Bridge for local LMStudio agents to consume and act on CosySim tasks."""

    def __init__(self) -> None:
        self._scheduler: Optional[Any] = None
        self._nexus: Optional[Any] = None

    # ── Internal helpers ─────────────────────────────────────────────────

    def _get_scheduler(self) -> Any:
        if self._scheduler is None:
            from engine.nexus.task_scheduler import TaskScheduler
            self._scheduler = TaskScheduler()
        return self._scheduler

    def _get_nexus(self) -> Any:
        if self._nexus is None:
            from engine.nexus.client import get_nexus_client
            self._nexus = get_nexus_client()
        return self._nexus

    # ── Public API ───────────────────────────────────────────────────────

    def get_ready_tasks(
        self,
        model_size: str = "worker",
        limit: int = 10,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return pending tasks appropriate for this model size.

        Args:
            model_size: One of 'router', 'mini', 'worker', 'expert'.
            limit: Max tasks to return.
            tags: Optional tag filter (any match).

        Returns:
            List of task dicts with id, title, description, complexity, priority.
        """
        allowed_complexity = _MODEL_COMPLEXITY_MAP.get(model_size, ["low", "medium"])
        scheduler = self._get_scheduler()
        all_tasks = scheduler.get_pending_tasks()

        filtered: List[Dict[str, Any]] = []
        for task in all_tasks:
            task_dict = task.to_dict() if hasattr(task, "to_dict") else task
            complexity = task_dict.get("complexity", "medium")
            if complexity not in allowed_complexity:
                continue
            if tags:
                task_tags = task_dict.get("tags", [])
                if not any(t in task_tags for t in tags):
                    continue
            filtered.append(task_dict)

        # Sort by priority (lower int = higher priority)
        filtered.sort(key=lambda t: (t.get("priority", 2), t.get("created_at", 0)))
        return filtered[:limit]

    def claim_task(self, task_id: str, agent_id: str) -> Dict[str, Any]:
        """Claim a task for this agent.

        Args:
            task_id: ID of the task to claim.
            agent_id: Unique identifier for this agent instance.

        Returns:
            Task dict with status='claimed', or error dict.
        """
        try:
            scheduler = self._get_scheduler()
            task = scheduler.claim_task_by_id(task_id, agent_id)
            if task is None:
                return {"error": f"Task {task_id} not found or already claimed."}
            task_dict = task.to_dict() if hasattr(task, "to_dict") else task
            logger.info("Agent %s claimed task %s: %s", agent_id, task_id,
                        task_dict.get("title", ""))
            return task_dict
        except Exception as exc:
            logger.warning("claim_task failed: %s", exc)
            return {"error": str(exc)}

    def get_task_context(self, task_id: str) -> Dict[str, Any]:
        """Load full execution context for a task.

        Includes:
        - Task metadata (title, description, target_files, allowed_ops)
        - Relevant Nexus knowledge entries (searched by task title + tags)
        - Governance rules (coding standards, safety)
        - Step-by-step execution template

        Args:
            task_id: ID of the task.

        Returns:
            Context dict ready to be included in an LLM system prompt.
        """
        try:
            scheduler = self._get_scheduler()
            task = scheduler.get_task(task_id)
            if task is None:
                return {"error": f"Task {task_id} not found."}

            task_dict = task.to_dict() if hasattr(task, "to_dict") else task
            title = task_dict.get("title", "")
            tags = task_dict.get("tags", [])
            target_files = task_dict.get("target_files", [])

            # Gather Nexus knowledge relevant to this task
            nexus = self._get_nexus()
            search_terms = [title] + tags + [f.split("/")[-1] for f in target_files]
            nexus_knowledge: List[Dict[str, Any]] = []
            seen_titles: set = set()
            for term in search_terms[:4]:
                if not term:
                    continue
                results = nexus.search(term, limit=3)
                for r in results:
                    t = r.get("title", "")
                    if t not in seen_titles:
                        seen_titles.add(t)
                        nexus_knowledge.append({
                            "title": t,
                            "content": r.get("content", "")[:500],
                            "source": r.get("content_type", ""),
                        })
                    if len(nexus_knowledge) >= _NEXUS_CONTEXT_LIMIT:
                        break
                if len(nexus_knowledge) >= _NEXUS_CONTEXT_LIMIT:
                    break

            # Load governance rules
            coding_rules: str = ""
            try:
                rules_result = nexus.get_rules("coding")
                if isinstance(rules_result, list):
                    coding_rules = "\n".join(r.get("rule_text", "") for r in rules_result[:5])
                elif isinstance(rules_result, str):
                    coding_rules = rules_result[:800]
            except Exception:
                pass

            # Execution template
            execution_steps = _build_execution_steps(task_dict)

            return {
                "task": task_dict,
                "nexus_knowledge": nexus_knowledge,
                "coding_rules": coding_rules,
                "execution_steps": execution_steps,
                "context_summary": _build_context_summary(task_dict, nexus_knowledge),
            }
        except Exception as exc:
            logger.warning("get_task_context failed: %s", exc)
            return {"error": str(exc)}

    def complete_task(
        self,
        task_id: str,
        result: str,
        files_changed: Optional[List[str]] = None,
        store_to_nexus: bool = True,
    ) -> Dict[str, Any]:
        """Mark a task as completed and store result artifacts.

        Args:
            task_id: ID of the completed task.
            result: Human-readable summary of what was done.
            files_changed: List of file paths modified.
            store_to_nexus: Whether to store the completion as a Nexus entry.

        Returns:
            Dict with 'status': 'completed' and 'nexus_id' if stored.
        """
        try:
            scheduler = self._get_scheduler()
            ok = scheduler.complete_task(task_id, result, files_changed=files_changed)
            if not ok:
                return {"error": f"Task {task_id} not found."}

            task = scheduler.get_task(task_id)
            title = task.title if task else task_id

            nexus_id: Optional[str] = None
            if store_to_nexus:
                nexus = self._get_nexus()
                content = (
                    f"Task: {title}\n"
                    f"Result: {result}\n"
                    f"Files changed: {', '.join(files_changed or []) or 'none'}\n"
                    f"Completed at: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}"
                )
                try:
                    stored = nexus.add_entry(
                        title=f"Task Complete: {title}",
                        content=content,
                        content_type="history",
                        category="agent-tasks",
                    )
                    nexus_id = stored.get("id") if isinstance(stored, dict) else None
                except Exception as exc:
                    logger.debug("Could not store task result in Nexus: %s", exc)

            # v1.50.2 [2026-03-24] — Store structured feedback for distiller loop
            # CONNECTS: NexusDistiller — agent feedback entries are picked up
            # by the distiller for pattern extraction and task generation
            try:
                nexus = self._get_nexus()
                agent_id = task.assigned_agent if task else "unknown"
                feedback_content = json.dumps({
                    "task_id": task_id,
                    "task_title": title,
                    "agent_id": agent_id,
                    "result_summary": result[:500],
                    "files_changed": files_changed or [],
                    "completed_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                })
                nexus.add_entry(
                    title=f"Agent Feedback: {title[:80]}",
                    content=feedback_content,
                    content_type="note",
                    category="agent-feedback",
                    tags=["agent-feedback", "auto-generated", "distiller-input"],
                )
            except Exception as exc:
                logger.debug("Could not store agent feedback: %s", exc)

            logger.info("Task %s completed: %s", task_id, result[:80])
            return {"status": "completed", "task_id": task_id, "nexus_id": nexus_id}
        except Exception as exc:
            logger.warning("complete_task failed: %s", exc)
            return {"error": str(exc)}

    def fail_task(
        self,
        task_id: str,
        reason: str,
        retry: bool = False,
    ) -> Dict[str, Any]:
        """Mark a task as failed.

        Args:
            task_id: ID of the failed task.
            reason: Why the task failed.
            retry: If True, reset to 'pending' for another agent to pick up.

        Returns:
            Dict with 'status': 'failed' or 'pending' (if retry=True).
        """
        try:
            scheduler = self._get_scheduler()
            new_status = "pending" if retry else "failed"
            task = scheduler.fail_task(task_id, reason, retry=retry)
            if task is None:
                return {"error": f"Task {task_id} not found."}

            logger.info("Task %s failed: %s (retry=%s)", task_id, reason, retry)
            return {"status": new_status, "task_id": task_id, "reason": reason}
        except Exception as exc:
            logger.warning("fail_task failed: %s", exc)
            return {"error": str(exc)}

    # v1.50.2 [2026-03-24] — Agent registry for auto_assign: discovers loaded models
    # CONNECTS: LMSClient.get_models(), TaskScheduler.auto_assign()
    # CALLED BY: _auto_assign_callback in scheduler_daemon.py
    def build_agent_registry(self) -> List[Dict[str, Any]]:
        """Discover loaded LMStudio models and build agent capability dicts.

        Returns:
            List of agent capability dicts suitable for TaskScheduler.auto_assign().
            Empty list if LMStudio is offline or no models loaded.
        """
        try:
            from engine.lmstudio import get_lms_client
            client = get_lms_client()
            if not client.is_available():
                logger.debug("[AgentBridge] LMStudio offline (operation=build_registry)")
                return []

            models = client.get_models(loaded_only=True)
            if not models:
                return []

            agents: List[Dict[str, Any]] = []
            for model in models:
                # Parse model size from identifier or metadata
                size_b = _parse_model_size(model)
                if size_b <= 0:
                    continue

                agents.append({
                    "id": getattr(model, "id", str(model)),
                    "model_size_b": size_b,
                    "can_edit": size_b >= 3.0,
                    "can_test": size_b >= 3.0,
                    "can_review": size_b >= 14.0,
                    "tags": [
                        getattr(model, "architecture", ""),
                        getattr(model, "type", ""),
                    ],
                })

            logger.info(
                "[AgentBridge] Built registry with %d agent(s) (operation=build_registry)",
                len(agents),
            )
            return agents
        except Exception as exc:
            logger.debug("[AgentBridge] Registry build failed (operation=build_registry): %s", exc)
            return []

    def get_agent_manifest(self, model_size: str = "worker") -> str:
        """Return a formatted system prompt fragment for an agent of this size.

        Includes: role description, available task complexity levels, Nexus
        instructions, and step-by-step execution guide.

        Args:
            model_size: Agent tier — 'router', 'mini', 'worker', 'expert'.

        Returns:
            Multi-line string suitable for inclusion in a system prompt.
        """
        allowed = _MODEL_COMPLEXITY_MAP.get(model_size, ["medium"])
        nexus_url = get_config().get("nexus.base_url", "http://localhost:8700")
        lines = [
            f"# CosySim Agent Manifest — {model_size.upper()} tier",
            "",
            "## Your Role",
            f"You are a {model_size}-tier local agent in the CosySim autonomous system.",
            f"You can handle tasks with complexity: {', '.join(allowed)}.",
            "",
            "## Workflow",
            "1. Call `get_ready_tasks` to see available work.",
            "2. Pick a task matching your capability and call `claim_task`.",
            "3. Call `get_task_context` to load full instructions + relevant Nexus knowledge.",
            "4. Execute the task, following coding standards and testing instructions.",
            "5. Call `complete_task` with a clear summary of what you did.",
            "6. If you fail, call `fail_task` — be honest about why.",
            "",
            "## Nexus Usage (MANDATORY)",
            f"- Nexus API: {nexus_url}",
            "- Search before every step: what do I know about this?",
            "- Store every decision, finding, and result in Nexus.",
            "- Cache every Q&A pair you generate.",
            "",
            "## Code Standards",
            "- Absolute imports only (from engine.x import y)",
            "- Type hints on all functions",
            "- logger = logging.getLogger(__name__) — no print()",
            "- Run tests after every code change",
            "- Never create stubs — complete the full implementation",
        ]
        return "\n".join(lines)


# ── Context builders ──────────────────────────────────────────────────────

def _build_execution_steps(task_dict: Dict[str, Any]) -> List[str]:
    """Build step-by-step execution instructions from task metadata."""
    title = task_dict.get("title", "")
    ops = task_dict.get("allowed_operations", ["read", "edit", "test"])
    files = task_dict.get("target_files", [])
    desc = task_dict.get("description", "")

    steps = ["0. Search Nexus for existing knowledge about this task."]
    if "read" in ops:
        steps.append("1. Read the relevant source files to understand the current state.")
    if files:
        steps.append(f"2. Focus on: {', '.join(files)}")
    if "edit" in ops or "create" in ops:
        steps.append("3. Implement the changes. Complete the full feature — no stubs.")
    if "test" in ops:
        steps.append("4. Run tests: python -m pytest tests/ -q --tb=short")
    steps.append("5. Store results and decisions in Nexus.")
    steps.append("6. Call complete_task with a clear 1-sentence summary.")
    return steps


def _build_context_summary(
    task_dict: Dict[str, Any],
    nexus_knowledge: List[Dict[str, Any]],
) -> str:
    """Build a short context paragraph for LLM system prompt injection."""
    title = task_dict.get("title", "")
    desc = task_dict.get("description", "")
    knowledge_titles = [k["title"] for k in nexus_knowledge[:3]]
    parts = [
        f"Task: {title}",
        f"Description: {desc[:300]}" if desc else "",
        f"Relevant knowledge: {', '.join(knowledge_titles)}" if knowledge_titles else "",
    ]
    return "\n".join(p for p in parts if p)


# ── Singleton ─────────────────────────────────────────────────────────────

def get_local_agent_bridge() -> LocalAgentBridge:
    """Get the singleton LocalAgentBridge."""
    global _bridge_instance
    if _bridge_instance is None:
        with _bridge_lock:
            if _bridge_instance is None:
                _bridge_instance = LocalAgentBridge()
    return _bridge_instance
