"""NLM gRPC Skills — MCP skills for heap-discovered NotebookLM gRPC methods.

Wraps the 24 heap-discovered gRPC service methods exposed by NLMDirectClient
into LLM-callable skills.  These complement the batchexecute-based nlm_forge
skills with lower-level notebook management: artifacts, source lifecycle,
chat sessions, notes, account info, and prompt/report suggestions.

Usage by agents:
    nlm_create_artifact(notebook_id="nb-123", title="My Note", content="...")
    nlm_check_freshness(notebook_id="nb-123")
    nlm_account_info()
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _get_client():
    """Lazy-load NLMDirectClient."""
    from engine.integrations.nlm_direct_client import get_nlm_direct_client
    return get_nlm_direct_client()


def _truncated_json(obj: object, limit: int = 2000) -> str:
    """Serialise *obj* to indented JSON, truncated to *limit* characters."""
    raw = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    if len(raw) > limit:
        return raw[:limit] + "\n... (truncated)"
    return raw


# ──── Artifact Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "Create an artifact (note, code, document) inside a NotebookLM notebook. "
        "Returns the created artifact metadata."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "artifact", "create"],
)
def nlm_create_artifact(
    notebook_id: str,
    title: str = "",
    content: str = "",
    artifact_type: str = "note",
) -> str:
    """Create a new artifact in a NotebookLM notebook.

    Args:
        notebook_id: Target notebook UUID.
        title: Artifact title.
        content: Artifact body text.
        artifact_type: Type of artifact — note, code, document.

    Returns:
        JSON with created artifact metadata or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.create_artifact(
            notebook_id,
            artifact_type=artifact_type,
            title=title,
            content=content,
        )
        if result is None:
            return json.dumps({"error": "create_artifact returned None — method may not be live"})
        return f"Artifact created: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_create_artifact failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Generate an artifact from a natural-language prompt using NotebookLM. "
        "The service creates content based on notebook context and the prompt."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "artifact", "generate"],
)
def nlm_generate_artifact(
    notebook_id: str,
    prompt: str,
    artifact_type: str = "note",
) -> str:
    """Generate an artifact from a prompt via NotebookLM gRPC.

    Args:
        notebook_id: Notebook to generate within.
        prompt: Natural-language generation prompt.
        artifact_type: Type of artifact — note, code, document.

    Returns:
        JSON with generated artifact content or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.generate_artifact(
            notebook_id,
            prompt=prompt,
            artifact_type=artifact_type,
        )
        if result is None:
            return json.dumps({"error": "generate_artifact returned None — method may not be live"})
        return f"Artifact generated: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_generate_artifact failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Source Management Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "Check whether sources in a notebook are stale and need refreshing. "
        "Optionally pass specific source IDs; otherwise checks all sources."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "source", "freshness"],
)
def nlm_check_freshness(
    notebook_id: str,
    source_ids: str = "",
) -> str:
    """Check source freshness in a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        source_ids: Optional JSON array of source IDs to check.  Empty means all.

    Returns:
        JSON with freshness status per source or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        ids: Optional[List[str]] = json.loads(source_ids) if source_ids else None
        result = client.check_source_freshness(notebook_id, source_ids=ids)
        if result is None:
            return json.dumps({"error": "check_source_freshness returned None"})
        return f"Freshness check: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_check_freshness failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Refresh a single source in a notebook to re-fetch its content from "
        "the original URL or service."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "source", "refresh"],
)
def nlm_refresh_source(
    notebook_id: str,
    source_id: str,
) -> str:
    """Refresh a source in a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        source_id: Source to refresh.

    Returns:
        JSON with refresh result or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.refresh_source(notebook_id, source_id)
        if result is None:
            return json.dumps({"error": "refresh_source returned None"})
        return f"Source refreshed: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_refresh_source failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Discover new sources relevant to a query. Searches the web or linked "
        "services for content that could be added to the notebook."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "source", "discover"],
)
def nlm_discover_sources(
    notebook_id: str,
    query: str,
    max_results: int = 10,
) -> str:
    """Discover new sources for a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        query: Search query for source discovery.
        max_results: Maximum number of results to return.

    Returns:
        JSON with discovered source candidates or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.discover_sources_async(
            notebook_id,
            query=query,
            max_results=max_results,
        )
        if result is None:
            return json.dumps({"error": "discover_sources_async returned None"})
        return f"Discovered sources: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_discover_sources failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Update source metadata (e.g. title) for a source in a notebook."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "source", "mutate"],
)
def nlm_mutate_source(
    notebook_id: str,
    source_id: str,
    title: str = "",
) -> str:
    """Update metadata for a source in a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        source_id: Source to update.
        title: New title for the source.  Empty string leaves unchanged.

    Returns:
        JSON with mutation result or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        mutations = {}
        if title:
            mutations["title"] = title
        if not mutations:
            return json.dumps({"error": "No mutations specified — provide at least a title"})
        result = client.mutate_source(notebook_id, source_id, mutations)
        if result is None:
            return json.dumps({"error": "mutate_source returned None"})
        return f"Source updated: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_mutate_source failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Bulk-delete sources from a NotebookLM notebook. Accepts a JSON array "
        "of source IDs to remove."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "source", "delete"],
)
def nlm_delete_sources(
    notebook_id: str,
    source_ids: str,
) -> str:
    """Bulk-delete sources from a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        source_ids: JSON array of source IDs to delete.

    Returns:
        JSON with deletion result or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        ids: List[str] = json.loads(source_ids) if isinstance(source_ids, str) else source_ids
        if not ids:
            return json.dumps({"error": "source_ids array is empty"})
        result = client.delete_sources_bulk(notebook_id, ids)
        if result is None:
            return json.dumps({"error": "delete_sources_bulk returned None"})
        return f"Sources deleted: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_delete_sources failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Project Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "Update notebook/project metadata such as title."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "project", "mutate"],
)
def nlm_mutate_project(
    notebook_id: str,
    title: str = "",
) -> str:
    """Update metadata for a NotebookLM notebook/project.

    Args:
        notebook_id: Notebook UUID.
        title: New title for the notebook.

    Returns:
        JSON with mutation result or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        mutations = {}
        if title:
            mutations["title"] = title
        if not mutations:
            return json.dumps({"error": "No mutations specified — provide at least a title"})
        result = client.mutate_project(notebook_id, mutations)
        if result is None:
            return json.dumps({"error": "mutate_project returned None"})
        return f"Project updated: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_mutate_project failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Chat Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "List all chat sessions inside a NotebookLM notebook. Returns session "
        "IDs, timestamps, and turn counts."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "chat", "list"],
)
def nlm_list_chat_sessions(
    notebook_id: str,
) -> str:
    """List chat sessions in a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.

    Returns:
        JSON array of chat session metadata or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.list_chat_sessions(notebook_id)
        if result is None:
            return json.dumps({"error": "list_chat_sessions returned None"})
        return f"Chat sessions: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_list_chat_sessions failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Delete specific chat turns from a NotebookLM notebook. Accepts a "
        "JSON array of turn IDs to remove."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "chat", "delete"],
)
def nlm_delete_chat_turns(
    notebook_id: str,
    turn_ids: str,
) -> str:
    """Delete chat turns from a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        turn_ids: JSON array of turn IDs to delete.

    Returns:
        JSON with deletion result or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        ids: List[str] = json.loads(turn_ids) if isinstance(turn_ids, str) else turn_ids
        if not ids:
            return json.dumps({"error": "turn_ids array is empty"})
        result = client.delete_chat_turns(notebook_id, ids)
        if result is None:
            return json.dumps({"error": "delete_chat_turns returned None"})
        return f"Turns deleted: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_delete_chat_turns failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Notes Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "Update the content of a note inside a NotebookLM notebook."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "note", "mutate"],
)
def nlm_mutate_note(
    notebook_id: str,
    note_id: str,
    content: str = "",
) -> str:
    """Update a note in a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        note_id: Note to update.
        content: New content for the note.  Empty string leaves unchanged.

    Returns:
        JSON with mutation result or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        mutations = {}
        if content:
            mutations["content"] = content
        if not mutations:
            return json.dumps({"error": "No mutations specified — provide content"})
        result = client.mutate_note(notebook_id, note_id, mutations)
        if result is None:
            return json.dumps({"error": "mutate_note returned None"})
        return f"Note updated: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_mutate_note failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Account Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "Get or create the NotebookLM account record. Returns account tier, "
        "quotas, preferences, and metadata."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "account", "info"],
)
def nlm_account_info() -> str:
    """Get or create the NLM account record.

    Returns:
        JSON with account metadata (tier, quotas, preferences) or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.get_or_create_account()
        if result is None:
            return json.dumps({"error": "get_or_create_account returned None"})
        return f"Account info: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_account_info failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Suggestion Skills ────


@skill(
    pack="nlm_grpc",
    description=(
        "Generate prompt suggestions for a notebook. Returns a list of "
        "suggested follow-up questions or prompts based on notebook content."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "prompt", "suggestions"],
)
def nlm_prompt_suggestions(
    notebook_id: str,
    context: str = "",
    count: int = 5,
) -> str:
    """Generate prompt suggestions for a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        context: Optional context string to guide suggestion generation.
        count: Number of suggestions to generate.

    Returns:
        JSON array of suggested prompts or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.generate_prompt_suggestions(
            notebook_id,
            context=context,
            count=count,
        )
        if result is None:
            return json.dumps({"error": "generate_prompt_suggestions returned None"})
        return f"Prompt suggestions: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_prompt_suggestions failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_grpc",
    description=(
        "Generate report suggestions for a notebook. Returns suggested report "
        "topics or structures (summary, comparison, analysis, etc.)."
    ),
    category="SYSTEM",
    tags=["nlm", "grpc", "report", "suggestions"],
)
def nlm_report_suggestions(
    notebook_id: str,
    report_type: str = "summary",
    context: str = "",
) -> str:
    """Generate report suggestions for a NotebookLM notebook.

    Args:
        notebook_id: Notebook UUID.
        report_type: Type of report — summary, comparison, analysis.
        context: Optional context string to guide suggestion generation.

    Returns:
        JSON array of suggested report topics or error.
    """
    client = _get_client()
    if not client:
        return json.dumps({"error": "NLM client unavailable"})
    try:
        result = client.generate_report_suggestions(
            notebook_id,
            report_type=report_type,
            context=context,
        )
        if result is None:
            return json.dumps({"error": "generate_report_suggestions returned None"})
        return f"Report suggestions: {_truncated_json(result)}"
    except Exception as exc:
        logger.error("nlm_report_suggestions failed: %s", exc)
        return json.dumps({"error": str(exc)})
