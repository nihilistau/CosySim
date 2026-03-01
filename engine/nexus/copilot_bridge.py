"""Copilot Bridge — Makes Copilot CLI self-improving via NLM + Nexus.

Provides functions that the Copilot CLI hooks can call to:
- Pre-plan tasks using NLM (batch-ask before coding)
- Analyze source files before editing
- Get implementation guides from NLM
- Post-session distillation of learnings
- Track compute savings

Usage in hooks:
    from engine.nexus.copilot_bridge import get_copilot_bridge
    bridge = get_copilot_bridge()
    guide = bridge.pre_plan("Add caching to the API")
    bridge.post_session("Implemented caching layer in 3 modules")
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class SessionMetrics:
    """Tracks a single Copilot session's NLM/Nexus usage."""

    session_start: float = field(default_factory=time.monotonic)
    nexus_searches: int = 0
    nexus_cache_hits: int = 0
    nlm_asks: int = 0
    llm_calls: int = 0
    tools_used: List[str] = field(default_factory=list)
    files_edited: List[str] = field(default_factory=list)
    decisions_stored: int = 0
    qa_pairs_generated: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session metrics."""
        elapsed = time.monotonic() - self.session_start
        total_queries = self.nexus_cache_hits + self.nlm_asks + self.llm_calls
        saved = (self.nexus_cache_hits + self.nlm_asks) if total_queries > 0 else 0
        pct = (saved / total_queries * 100) if total_queries > 0 else 0
        return {
            "duration_seconds": round(elapsed, 1),
            "nexus_searches": self.nexus_searches,
            "nexus_cache_hits": self.nexus_cache_hits,
            "nlm_asks": self.nlm_asks,
            "llm_calls": self.llm_calls,
            "total_queries": total_queries,
            "compute_saved_pct": round(pct, 1),
            "tools_used": len(self.tools_used),
            "files_edited": len(self.files_edited),
            "decisions_stored": self.decisions_stored,
            "qa_pairs_generated": self.qa_pairs_generated,
        }


class CopilotBridge:
    """Bridge between Copilot CLI and the NLM + Nexus intelligence layer.

    Designed to be called from Copilot CLI hooks at session boundaries
    and during tool use. Automates the Nexus-first workflow.
    """

    def __init__(self) -> None:
        self._metrics = SessionMetrics()
        self._nexus = None
        self._router = None
        self._forge = None

    def _get_nexus(self) -> Any:
        """Lazy-load NexusClient."""
        if self._nexus is None:
            try:
                from engine.nexus.client import get_nexus_client
                self._nexus = get_nexus_client()
            except Exception as e:
                logger.warning("NexusClient unavailable: %s", e)
        return self._nexus

    def _get_router(self) -> Any:
        """Lazy-load NLMRouter."""
        if self._router is None:
            try:
                from engine.nexus.nlm_router import get_nlm_router
                self._router = get_nlm_router()
            except Exception as e:
                logger.warning("NLMRouter unavailable: %s", e)
        return self._router

    def _get_forge(self) -> Any:
        """Lazy-load KnowledgeForge."""
        if self._forge is None:
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                self._forge = get_knowledge_forge()
            except Exception as e:
                logger.warning("KnowledgeForge unavailable: %s", e)
        return self._forge

    # ──── Session Lifecycle ────

    def session_start(self, task_description: str = "") -> Dict[str, Any]:
        """Called at session start — searches Nexus for task-relevant knowledge.

        Args:
            task_description: Description of the task from user's first message.

        Returns:
            Dict with relevant knowledge, rules, and context.
        """
        self._metrics = SessionMetrics()
        context: Dict[str, Any] = {"task": task_description, "knowledge": []}

        nexus = self._get_nexus()
        if not nexus or not task_description:
            return context

        # Search for relevant knowledge
        try:
            results = nexus.search(task_description, limit=5)
            self._metrics.nexus_searches += 1
            if results:
                context["knowledge"] = [
                    {"title": r.get("title", ""), "content": r.get("content", "")[:300]}
                    for r in results[:5]
                ]
        except Exception as e:
            logger.debug("Session start search failed: %s", e)

        # Check for relevant Q&A
        try:
            qa = nexus.find_qa(task_description)
            if qa and qa.get("answer"):
                context["cached_answer"] = qa["answer"][:500]
                self._metrics.nexus_cache_hits += 1
        except Exception as e:
            logger.debug("Session start Q&A lookup failed: %s", e)

        # Load relevant rules
        try:
            rules = nexus.get_rules(scope="coding")
            if rules:
                context["rules"] = rules[:5]
        except Exception as e:
            logger.debug("Rules lookup failed: %s", e)

        logger.info(
            "Session started: %d knowledge entries, %s cached Q&A",
            len(context.get("knowledge", [])),
            "yes" if "cached_answer" in context else "no",
        )
        return context

    def session_end(self, summary: str = "") -> Dict[str, Any]:
        """Called at session end — distills learnings and stores metrics.

        Args:
            summary: Summary of what was accomplished.

        Returns:
            Dict with session metrics and storage results.
        """
        result: Dict[str, Any] = {"metrics": self._metrics.to_dict()}

        nexus = self._get_nexus()
        if not nexus:
            return result

        # Log the session
        try:
            nexus.log_session(
                project="CosySim",
                summary=summary or "Copilot CLI session",
            )
        except Exception as e:
            logger.debug("Session log failed: %s", e)

        # Store metrics summary
        try:
            metrics = self._metrics.to_dict()
            nexus.add_entry(
                title=f"Session: {summary[:60]}" if summary else "Copilot Session",
                content=json.dumps(metrics, indent=2),
                content_type="history",
                category="sessions",
                tags=["copilot", "session", "metrics"],
            )
        except Exception as e:
            logger.debug("Metrics storage failed: %s", e)

        return result

    # ──── Pre-Coding Operations ────

    def pre_plan(
        self,
        task: str,
        context_files: Optional[List[str]] = None,
        question_count: int = 10,
    ) -> Dict[str, Any]:
        """Pre-plan a task using NLM before writing code.

        Generates relevant questions about the task, batch-asks NLM,
        and returns a knowledge brief. All answers stored in Nexus.

        Args:
            task: Description of the task.
            context_files: Optional source files for context.
            question_count: Number of questions to generate.

        Returns:
            Dict with guide questions, answers, and recommendations.
        """
        from engine.nexus.knowledge_forge import generate_questions

        guide: Dict[str, Any] = {"task": task, "qa_pairs": [], "recommendations": []}

        # Generate relevant questions
        questions = generate_questions(task, category="plan", count=question_count, subject=task[:50])

        # Route through NLM-first pipeline
        router = self._get_router()
        if not router:
            guide["error"] = "NLM router unavailable"
            return guide

        for q in questions:
            result = router.route(q)
            if result.answer:
                guide["qa_pairs"].append({
                    "question": q,
                    "answer": result.answer[:500],
                    "source": result.source_tier,
                })
                if result.source_tier in ("cache", "fts"):
                    self._metrics.nexus_cache_hits += 1
                elif result.source_tier == "nlm":
                    self._metrics.nlm_asks += 1
                else:
                    self._metrics.llm_calls += 1

        self._metrics.qa_pairs_generated += len(guide["qa_pairs"])
        return guide

    def analyze_files(
        self,
        file_paths: List[str],
        questions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Analyze source files using NLM before editing them.

        Args:
            file_paths: Files about to be edited.
            questions: Specific questions about the files.

        Returns:
            Dict with insights about each file.
        """
        forge = self._get_forge()
        if not forge:
            return {"error": "KnowledgeForge unavailable"}

        result = forge.analyze(file_paths, questions=questions)
        return {
            "notebook_id": result.notebook_id,
            "insights": [p.to_dict() for p in result.qa_pairs],
            "errors": result.errors,
        }

    def get_guide(
        self,
        plan: str,
        files: Optional[List[str]] = None,
        notebook_id: str = "",
    ) -> Dict[str, Any]:
        """Get a step-by-step implementation guide from NLM.

        Args:
            plan: The implementation plan.
            files: Source files for context.
            notebook_id: Existing notebook with context.

        Returns:
            Dict with implementation steps.
        """
        forge = self._get_forge()
        if not forge:
            return {"error": "KnowledgeForge unavailable"}

        # Create notebook from files if needed
        if files and not notebook_id:
            from engine.nexus.nlm_engine import get_nlm_engine
            engine = get_nlm_engine()
            nb_result = engine.create_from_files(files, f"Guide: {plan[:40]}")
            notebook_id = nb_result.get("notebook_id", "")

        result = forge.decompose(plan, notebook_id=notebook_id)
        return {
            "steps": result.steps,
            "step_count": len(result.steps),
            "errors": result.errors,
        }

    # ──── During-Coding Operations ────

    def track_tool_use(self, tool_name: str, params: Dict[str, Any] = None) -> None:
        """Track a tool being used in the session.

        Args:
            tool_name: Name of the tool called.
            params: Tool parameters (for analysis).
        """
        self._metrics.tools_used.append(tool_name)

        # Track file edits
        if tool_name in ("edit", "create") and params:
            path = params.get("path", "")
            if path and path not in self._metrics.files_edited:
                self._metrics.files_edited.append(path)

    def track_error(self, tool_name: str, error_msg: str) -> None:
        """Track an error occurrence for pattern analysis.

        Args:
            tool_name: Name of the tool that errored.
            error_msg: Error message text.
        """
        self._metrics.tools_used.append(f"ERROR:{tool_name}")
        try:
            nexus = self._get_nexus()
            if nexus:
                nexus.add_entry(
                    f"Error in {tool_name}",
                    f"Tool: {tool_name}\nError: {error_msg}",
                    content_type="memory",
                    category="debugging",
                    tags=["error", "copilot", tool_name],
                )
        except Exception:
            logger.debug("Could not store error tracking in Nexus")

    def store_decision(self, title: str, content: str, category: str = "architecture") -> Optional[str]:
        """Store a design decision in Nexus.

        Args:
            title: Decision title.
            content: Full decision description.
            category: Decision category.

        Returns:
            Nexus entry ID or None.
        """
        nexus = self._get_nexus()
        if not nexus:
            return None

        try:
            entry_id = nexus.add_entry(
                title=f"Decision: {title}",
                content=content,
                content_type="note",
                category=category,
                tags=["decision", "copilot"],
            )
            self._metrics.decisions_stored += 1
            return entry_id
        except Exception as e:
            logger.debug("Decision storage failed: %s", e)
            return None

    # ──── Post-Session Operations ────

    def post_session(
        self,
        summary: str,
        decisions: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Post-session distillation — store learnings and metrics.

        Args:
            summary: What was accomplished.
            decisions: List of decisions made during the session.

        Returns:
            Dict with storage results and metrics.
        """
        result: Dict[str, Any] = {"stored": []}

        nexus = self._get_nexus()
        if not nexus:
            return {"error": "Nexus unavailable", "metrics": self._metrics.to_dict()}

        # Store each decision
        if decisions:
            for d in decisions:
                entry_id = self.store_decision(
                    d.get("title", "Untitled Decision"),
                    d.get("content", ""),
                    d.get("category", "architecture"),
                )
                if entry_id:
                    result["stored"].append(entry_id)

        # End the session
        end_result = self.session_end(summary)
        result["metrics"] = end_result.get("metrics", {})
        return result

    def generate_questions(
        self,
        topic: str,
        count: int = 15,
        category: str = "topic",
    ) -> List[str]:
        """Generate questions for batch asking.

        Args:
            topic: Topic to generate questions about.
            count: Number of questions.
            category: Question category — "code", "topic", "plan".

        Returns:
            List of generated questions.
        """
        from engine.nexus.knowledge_forge import generate_questions
        return generate_questions(topic, category=category, count=count, subject=topic[:50])

    # ──── Governance & Memory ────

    def consensus_gate(
        self,
        operation: str,
        description: str,
        allow_categories: Optional[List[str]] = None,
    ) -> bool:
        """Check governance rules before a high-impact operation.

        Queries Nexus governance rules and prior decisions to determine
        if the proposed operation is permitted and consistent with
        established patterns.

        Args:
            operation: Operation type — e.g. "arch-change", "rule-change",
                "major-refactor", "new-dependency", "config-change".
            description: What is being changed and why.
            allow_categories: Rule categories to check. Defaults to all.

        Returns:
            True if permitted. Logs the gate check regardless.
        """
        nexus = self._get_nexus()
        if not nexus:
            logger.debug("consensus_gate: Nexus unavailable — allowing by default")
            return True

        # Check governance rules
        blocked_by: Optional[str] = None
        try:
            scope = f"operation:{operation}"
            rules = nexus.get_rules(scope=scope)
            for rule in (rules or []):
                rule_str = json.dumps(rule) if isinstance(rule, dict) else str(rule)
                if "block" in rule_str.lower() or "deny" in rule_str.lower():
                    blocked_by = rule.get("title") if isinstance(rule, dict) else rule_str[:80]
                    break
        except Exception as exc:
            logger.debug("Gate rule check failed: %s", exc)

        # Check decision history for conflicting prior decisions
        conflicts = []
        try:
            prior = self.get_decision_history(operation, n=3)
            for d in prior:
                content = d.get("content", "") + d.get("answer", "")
                if "must not" in content.lower() or "do not" in content.lower():
                    conflicts.append(d.get("title", d.get("question", "unknown"))[:60])
        except Exception as exc:
            logger.debug("Gate history check failed: %s", exc)

        permitted = blocked_by is None

        logger.info(
            "consensus_gate: op=%s permitted=%s blocked_by=%s conflicts=%d",
            operation, permitted, blocked_by, len(conflicts),
        )

        # Store gate check as a micro-version event
        try:
            nexus.add_entry(
                title=f"Gate: {operation}",
                content=(
                    f"Operation: {operation}\n"
                    f"Description: {description}\n"
                    f"Permitted: {permitted}\n"
                    f"Blocked by: {blocked_by or 'none'}\n"
                    f"Conflicts: {conflicts}"
                ),
                content_type="note",
                category="copilot-decisions",
                tags=["copilot", "governance", "gate", operation],
            )
        except Exception:
            pass

        return permitted

    def get_onboarding_context(self) -> Dict[str, Any]:
        """Load full onboarding context for a new Copilot CLI session.

        Pulls together:
          - Copilot-specific governance rules
          - Recent architectural decisions (last 10)
          - System architecture overview
          - Active todos or pending tasks

        Returns:
            Dict with rules, decisions, architecture, and quick-start guidance.
        """
        context: Dict[str, Any] = {
            "rules": [],
            "recent_decisions": [],
            "architecture_overview": "",
            "active_todos": [],
        }

        nexus = self._get_nexus()
        if not nexus:
            context["error"] = "Nexus unavailable"
            return context

        # Load coding/project rules
        for scope in ("coding", "global", "copilot"):
            try:
                rules = nexus.get_rules(scope=scope)
                if rules:
                    context["rules"].extend(rules[:5])
            except Exception:
                pass

        # Load recent architectural decisions
        try:
            decisions = self.get_decision_history("architecture", n=10)
            context["recent_decisions"] = decisions
        except Exception as exc:
            logger.debug("Decision history failed: %s", exc)

        # Load architecture overview from Nexus
        try:
            results = nexus.search("CosySim architecture overview", limit=1)
            if results:
                context["architecture_overview"] = results[0].get("content", "")[:1000]
        except Exception:
            pass

        # Load active todos from session DB (best-effort)
        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()
            pending = scheduler.get_pending_tasks(limit=5)
            context["active_todos"] = [
                {"title": t.get("title", ""), "priority": t.get("priority", 0)}
                for t in (pending or [])
            ]
        except Exception:
            pass

        logger.info(
            "Onboarding context: %d rules, %d decisions",
            len(context["rules"]), len(context["recent_decisions"]),
        )
        return context

    def get_decision_history(
        self,
        topic: str,
        n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieve past architectural/design decisions from Nexus.

        Searches both knowledge entries (category=copilot-decisions) and
        Q&A pairs that match the given topic.

        Args:
            topic: Topic to search for (e.g. "caching", "testing", "NLM routing").
            n: Maximum number of decisions to return.

        Returns:
            List of decision dicts with title, content/answer, and created_at.
        """
        nexus = self._get_nexus()
        if not nexus:
            return []

        decisions: List[Dict[str, Any]] = []

        # Search knowledge entries in copilot-decisions category
        try:
            results = nexus.search(
                f"decision {topic}",
                limit=n,
            )
            for r in results or []:
                category = r.get("category", "")
                if "decision" in category or "architecture" in category or "copilot" in category:
                    decisions.append({
                        "title": r.get("title", ""),
                        "content": r.get("content", "")[:400],
                        "created_at": r.get("created_at", ""),
                        "source": "knowledge",
                    })
        except Exception as exc:
            logger.debug("Decision search failed: %s", exc)

        # Also check Q&A cache
        try:
            qa_result = nexus.find_qa(f"decision {topic}")
            if qa_result and qa_result.get("answer"):
                decisions.append({
                    "title": f"Q&A: {topic}",
                    "answer": qa_result["answer"][:400],
                    "question": qa_result.get("question", ""),
                    "source": "qa_cache",
                })
        except Exception:
            pass

        self._metrics.nexus_searches += 1
        return decisions[:n]

    # ──── Metrics ────

    def get_savings_report(self) -> Dict[str, Any]:
        """Get compute savings report for the current session.

        Returns:
            Dict with savings metrics.
        """
        metrics = self._metrics.to_dict()

        # Add router stats if available
        router = self._get_router()
        if router:
            metrics["router_savings"] = router.savings_report()

        return metrics

    @property
    def metrics(self) -> SessionMetrics:
        """Current session metrics."""
        return self._metrics


# ──── Singleton ────

_bridge: Optional[CopilotBridge] = None


def get_copilot_bridge() -> CopilotBridge:
    """Return the global CopilotBridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = CopilotBridge()
    return _bridge
