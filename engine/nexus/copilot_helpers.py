"""
Copilot Helper Tools — Utilities for the Copilot CLI agent to interact
with CosySim and Nexus more efficiently.

Provides reusable helpers for:
- Storing snippets and discoveries in Nexus
- Generating context primers for new sessions
- Tracking work progress in Nexus
- Common patterns for PowerShell/Python operations

These are wired as MCP tools and also usable from Python directly.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_client():
    """Get a NexusClient instance."""
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


# ── Snippet Storage ─────────────────────────────────────────────────────

def store_snippet(
    title: str,
    code: str,
    language: str = "python",
    tags: Optional[List[str]] = None,
    description: str = "",
) -> Dict[str, Any]:
    """Store a reusable code snippet in Nexus.

    Args:
        title: Snippet title.
        code: The code content.
        language: Programming language.
        tags: Optional tags for categorisation.
        description: Optional description.

    Returns:
        Dict with status and entry_id.
    """
    client = _get_client()
    content = f"```{language}\n{code}\n```"
    if description:
        content = f"{description}\n\n{content}"

    try:
        entry_id = client.add_entry(
            title=f"Snippet: {title}",
            content=content,
            content_type="code",
            category="snippets",
            tags=(tags or []) + [language, "snippet"],
            created_by="copilot",
        )
        return {"status": "ok", "entry_id": entry_id}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── Discovery Storage ───────────────────────────────────────────────────

def store_discovery(
    title: str,
    finding: str,
    category: str = "debugging",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store a discovery or workaround in Nexus for future reference.

    Use this when you discover a workaround, gotcha, or important behaviour
    that future sessions should know about.

    Args:
        title: Brief title (e.g. "PowerShell triple-escape in heredocs").
        finding: Detailed description of the discovery.
        category: Category (debugging, performance, api, etc).
        tags: Optional tags.

    Returns:
        Dict with status.
    """
    client = _get_client()
    try:
        entry_id = client.add_entry(
            title=f"Discovery: {title}",
            content=finding,
            content_type="note",
            category=category,
            tags=(tags or []) + ["discovery", "copilot"],
            created_by="copilot",
        )
        return {"status": "ok", "entry_id": entry_id}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── Work Progress Tracking ──────────────────────────────────────────────

def log_work_progress(
    task: str,
    status: str = "completed",
    details: str = "",
    files_changed: Optional[List[str]] = None,
    tests_passed: int = 0,
    commit_sha: str = "",
) -> Dict[str, Any]:
    """Log a work progress entry in Nexus.

    Args:
        task: What was worked on.
        status: completed, in_progress, blocked.
        details: Additional details.
        files_changed: List of changed files.
        tests_passed: Number of passing tests.
        commit_sha: Git commit SHA if committed.

    Returns:
        Dict with status.
    """
    client = _get_client()
    content_parts = [
        f"Task: {task}",
        f"Status: {status}",
    ]
    if details:
        content_parts.append(f"Details: {details}")
    if files_changed:
        content_parts.append(f"Files: {', '.join(files_changed)}")
    if tests_passed:
        content_parts.append(f"Tests: {tests_passed} passed")
    if commit_sha:
        content_parts.append(f"Commit: {commit_sha}")

    content = "\n".join(content_parts)

    try:
        entry_id = client.add_entry(
            title=f"Progress: {task}",
            content=content,
            content_type="history",
            category="progress",
            tags=["progress", "copilot", status],
            created_by="copilot",
        )
        return {"status": "ok", "entry_id": entry_id}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── Context Primer Generation ───────────────────────────────────────────

def generate_context_primer(project: str = "CosySim") -> str:
    """Generate a compact context primer from Nexus knowledge.

    Builds a summary of recent decisions, active work, and key patterns
    that can be injected into new session contexts to reduce token usage.

    Args:
        project: Project name to scope the primer.

    Returns:
        Formatted context primer string.
    """
    client = _get_client()
    sections = []

    # Recent decisions
    try:
        decisions = client.search("Decision:", limit=5)
        if decisions:
            lines = []
            for d in decisions:
                title = d.get("title", "").replace("Decision: ", "")
                lines.append(f"- {title}")
            sections.append("## Recent Decisions\n" + "\n".join(lines))
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Recent progress
    try:
        progress = client.search("Progress:", limit=5)
        if progress:
            lines = []
            for p in progress:
                title = p.get("title", "").replace("Progress: ", "")
                lines.append(f"- {title}")
            sections.append("## Recent Work\n" + "\n".join(lines))
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Active discoveries
    try:
        discoveries = client.search("Discovery:", limit=5)
        if discoveries:
            lines = []
            for d in discoveries:
                title = d.get("title", "").replace("Discovery: ", "")
                content = d.get("content", "")[:100]
                lines.append(f"- **{title}**: {content}")
            sections.append("## Known Gotchas\n" + "\n".join(lines))
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Key snippets
    try:
        snippets = client.search("Snippet:", limit=3)
        if snippets:
            lines = []
            for s in snippets:
                title = s.get("title", "").replace("Snippet: ", "")
                lines.append(f"- {title}")
            sections.append("## Available Snippets\n" + "\n".join(lines))
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    if not sections:
        return f"# {project} Context Primer\n\nNo knowledge available yet."

    header = f"# {project} Context Primer\n_Generated {time.strftime('%Y-%m-%d %H:%M')}_\n"
    return header + "\n\n".join(sections)


# ── Local Model Guidance ────────────────────────────────────────────────

def generate_local_model_guidance(task_type: str = "general") -> str:
    """Generate guidance text for local LMStudio models working with Nexus.

    Provides structured instructions and guardrails for smaller models
    to safely interact with the Nexus knowledge base.

    Args:
        task_type: Type of task (general, code_review, knowledge_extraction,
                   qa_generation, maintenance).

    Returns:
        Guidance text string.
    """
    guides = {
        "general": (
            "You are a local AI assistant working with the CosySim project.\n"
            "Rules:\n"
            "1. Never delete knowledge entries — only add or update\n"
            "2. Always tag entries with the source (scene name, module, etc)\n"
            "3. Use category='architecture' for design decisions\n"
            "4. Use category='debugging' for bug fixes and workarounds\n"
            "5. Keep entries concise — under 500 words\n"
            "6. If unsure, store as content_type='note' with category='uncategorized'\n"
        ),
        "code_review": (
            "Review the following code and identify:\n"
            "1. Bugs or logic errors\n"
            "2. Missing error handling\n"
            "3. Naming convention violations\n"
            "4. Missing type hints\n"
            "5. Security concerns\n"
            "Output as a JSON array of {file, line, severity, message} objects.\n"
            "Severity: critical, warning, info\n"
            "Only report genuine issues — no style nitpicks.\n"
        ),
        "knowledge_extraction": (
            "Extract structured knowledge from the following text.\n"
            "For each knowledge item, output:\n"
            "1. title: Brief descriptive title\n"
            "2. content: The knowledge content (1-3 sentences)\n"
            "3. content_type: note|code|document|memory\n"
            "4. category: architecture|api|debugging|testing|performance\n"
            "5. tags: [relevant, tags]\n"
            "Output as a JSON array.\n"
        ),
        "qa_generation": (
            "Generate Q&A pairs from the following content.\n"
            "Each pair should be:\n"
            "1. question: A clear, specific question\n"
            "2. answer: A concise, accurate answer (1-3 sentences)\n"
            "3. category: The topic category\n"
            "Focus on practical 'how-to' questions.\n"
            "Output as a JSON array of {question, answer, category} objects.\n"
        ),
        "maintenance": (
            "You are running Nexus maintenance. Your tasks:\n"
            "1. Identify entries that can be merged (similar titles/content)\n"
            "2. Flag entries with missing tags or categories\n"
            "3. Suggest category corrections\n"
            "4. Identify outdated information\n"
            "NEVER delete entries — only suggest changes.\n"
            "Output as a JSON array of {entry_id, action, reason} objects.\n"
            "Actions: merge, retag, recategorize, flag_outdated\n"
        ),
    }

    return guides.get(task_type, guides["general"])
