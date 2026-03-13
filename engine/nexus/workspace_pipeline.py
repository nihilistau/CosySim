"""Workspace Pipeline — cross-service orchestrator for Google Workspace + Nexus.

Coordinates workflows across Google Docs, Sheets, Drive, NotebookLM, Colab,
and Nexus to execute multi-stage knowledge pipelines.  Each pipeline is a
named sequence of stages that move data between services, with Drive as the
intermediate
storage / movement layer and Nexus as the final knowledge destination.

Stages (17):
    nlm_research       — Research a topic via NotebookLM
    create_doc         — Create a Google Doc (optionally with Gemini content)
    create_sheet       — Create or populate a Google Sheet
    fill_sheet         — Fill a sheet range using Gemini enrichment
    drive_search       — Search Drive files using AI Overview semantic search
    drive_ask          — Ask Gemini a question about Drive files
    drive_upload       — Upload content to Drive as an intermediate artifact
    nexus_store        — Store pipeline results in Nexus as knowledge entries
    columnsmith        — Run Columnsmith AI transformations on sheet columns
    export_doc         — Export a Google Doc to text for downstream processing
    nlm_add_source     — Add a source to an NLM notebook
    workspace_generate — Generate text via WorkspaceGeminiClient
    fetch_news         — Fetch news articles via the NewsPipeline
    docs_to_sheets     — Convert a doc export into a structured sheet
    sheets_to_doc      — Convert sheet data into a formatted document
    gemini_enrich      — Enrich/transform content using Workspace Gemini
    prewarm            — Pre-warm Gemini models for latency reduction

Pipelines (17):
    research_and_distill   — NLM research → Sheets data → Nexus knowledge
    create_knowledge_doc   — NLM sources → Docs draft → Nexus document
    data_enrichment        — Sheets Fill-with-Gemini → Nexus structured data
    cross_source_synthesis — Drive search → NLM → Nexus synthesis
    news_pipeline          — Fetch RSS → NLM distill → Sheets → Nexus
    doc_to_notebook        — Docs → Drive → NLM notebook source → distill
    sheet_to_knowledge     — Sheets export → NLM research → Nexus entries
    generate_and_store     — Workspace Gemini generation → Nexus
    news_to_knowledge      — Fetch → NLM research → Docs → Drive → Nexus
    docs_nlm_distill       — Docs → export → NLM source → research → Nexus
    sheets_enrichment_cycle— Sheet → fill → columnsmith → doc report → Nexus
    drive_nlm_nexus        — Drive search → ask → enrich → NLM → doc → Nexus
    full_cross_service     — Drive → NLM → Gemini → Sheets → Docs → Drive → Nexus
    knowledge_distillation — Generate → enrich → NLM source → research → Nexus
    news_full_cycle        — News → enrich → NLM → Sheet + Doc → Drive → Nexus
    doc_structure_extract  — Doc → extract structured data → Sheet → Nexus
    sheet_knowledge_report — Sheet → doc report → NLM → Drive → Nexus
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Pipeline Types ──────────────────────────────────────────────────────────


class PipelineStatus(Enum):
    """Lifecycle status of a pipeline run."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(Enum):
    """Status of an individual pipeline stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """Result from a single pipeline stage."""

    stage_name: str
    status: StageStatus = StageStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineRun:
    """Tracks state of a single pipeline execution."""

    run_id: str
    pipeline_name: str
    status: PipelineStatus = PipelineStatus.PENDING
    params: Dict[str, Any] = field(default_factory=dict)
    stages: List[StageResult] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    final_output: Any = None
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        """Total pipeline duration in milliseconds."""
        if self.completed_at:
            return (self.completed_at - self.created_at) * 1000
        return (time.time() - self.created_at) * 1000

    @property
    def current_stage(self) -> Optional[str]:
        """Name of the currently running stage."""
        for stage in self.stages:
            if stage.status == StageStatus.RUNNING:
                return stage.stage_name
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the pipeline run to a dict."""
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "status": self.status.value,
            "params": self.params,
            "current_stage": self.current_stage,
            "stages": [
                {
                    "name": s.stage_name,
                    "status": s.status.value,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                    "metadata": s.metadata,
                }
                for s in self.stages
            ],
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


# ──── Stage Executors ─────────────────────────────────────────────────────────
# Each executor is a function(params, context) → output.  Context carries
# accumulated outputs from earlier stages.


def _stage_nlm_research(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Research a topic via NotebookLM.

    Creates or reuses a notebook, adds web sources if given, then asks
    a series of questions to distil knowledge.
    """
    from engine.nexus.nlm_engine import get_nlm_engine

    engine = get_nlm_engine()
    topic = params.get("topic", context.get("topic", ""))
    questions = params.get("questions", [f"Give a comprehensive overview of: {topic}"])
    notebook_id = params.get("notebook_id") or context.get("notebook_id")
    sources = params.get("sources", [])

    if not notebook_id:
        nb = engine.create_notebook(f"Research: {topic}")
        notebook_id = nb.get("id") or nb.get("notebook_id", "")
        if sources:
            for src in sources[:10]:
                try:
                    engine.add_source(notebook_id, src)
                except Exception as exc:
                    logger.warning("Failed to add source %s: %s", src, exc)

    answers: List[Dict[str, str]] = []
    for q in questions:
        try:
            answer = engine.ask(notebook_id, q)
            answers.append({"question": q, "answer": str(answer)})
        except Exception as exc:
            logger.warning("NLM ask failed for '%s': %s", q, exc)
            answers.append({"question": q, "answer": f"[error: {exc}]"})

    return {
        "notebook_id": notebook_id,
        "topic": topic,
        "answers": answers,
        "source_count": len(sources),
    }


def _stage_create_doc(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Create a Google Doc with optional Gemini-generated content."""
    from engine.integrations.google_docs_client import get_docs_client

    client = get_docs_client()
    if client is None:
        raise RuntimeError("No Google Docs account available")

    title = params.get("title", context.get("title", "Untitled"))
    prompt = params.get("prompt", "")
    folder_id = params.get("folder_id") or context.get("folder_id")

    content = context.get("content")
    if not content and context.get("answers"):
        parts = []
        for qa in context["answers"]:
            parts.append(f"## {qa['question']}\n\n{qa['answer']}\n")
        content = "\n".join(parts)

    if prompt:
        result = client.create_with_gemini(title=title, prompt=prompt, folder_id=folder_id)
    elif content:
        result = client.create_doc(title=title, folder_id=folder_id)
        if result and result.get("documentId"):
            client.append_to_doc(result["documentId"], content)
    else:
        result = client.create_doc(title=title, folder_id=folder_id)

    return {
        "doc_id": (result or {}).get("documentId", ""),
        "title": title,
        "url": f"https://docs.google.com/document/d/{(result or {}).get('documentId', '')}/edit",
    }


def _stage_create_sheet(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Create or populate a Google Sheet."""
    from engine.integrations.gsheets_client import get_sheets_client

    client = get_sheets_client()
    if client is None:
        raise RuntimeError("No Google Sheets account available")

    title = params.get("title", context.get("title", "Untitled Sheet"))
    prompt = params.get("prompt", "")
    data = params.get("data") or context.get("data")

    if prompt:
        result = client.build_with_gemini(prompt=prompt, title=title)
    elif data:
        result = client.create_spreadsheet(title=title)
        if result:
            sheet_id = result.get("spreadsheetId", "")
            if isinstance(data, list) and data:
                client.write_range(
                    sheet_id,
                    "Sheet1!A1",
                    data,
                )
    else:
        result = client.create_spreadsheet(title=title)

    sheet_id = (result or {}).get("spreadsheetId", "")
    return {
        "sheet_id": sheet_id,
        "title": title,
        "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
    }


def _stage_fill_sheet(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Fill a sheet range using Gemini enrichment."""
    from engine.integrations.gsheets_client import get_sheets_client

    client = get_sheets_client()
    if client is None:
        raise RuntimeError("No Google Sheets account available")

    sheet_id = params.get("sheet_id") or context.get("sheet_id", "")
    cell_range = params.get("range", "A1")
    prompt = params.get("prompt", "")

    result = client.fill_with_gemini(
        spreadsheet_id=sheet_id,
        cell_range=cell_range,
        prompt=prompt,
    )
    return result


def _stage_drive_search(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Search Drive files using AI Overview semantic search."""
    from engine.integrations.google_drive_client import get_drive_client

    client = get_drive_client()
    if client is None:
        raise RuntimeError("No Google Drive account available")

    query = params.get("query") or context.get("topic", "")
    page_size = params.get("page_size", 20)

    results = client.ai_overview_search(query=query, page_size=page_size)
    return results


def _stage_drive_ask(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Ask Gemini a question about Drive files."""
    from engine.integrations.google_drive_client import get_drive_client

    client = get_drive_client()
    if client is None:
        raise RuntimeError("No Google Drive account available")

    question = params.get("question") or context.get("topic", "")
    file_ids = params.get("file_ids") or context.get("file_ids")

    result = client.ask_gemini(question=question, file_ids=file_ids)
    return result


def _stage_drive_upload(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Upload content to Drive as an intermediate artifact."""
    from engine.integrations.google_drive_client import get_drive_client

    client = get_drive_client()
    if client is None:
        raise RuntimeError("No Google Drive account available")

    name = params.get("name", f"pipeline_{context.get('run_id', 'unknown')}.txt")
    content = params.get("content", "")

    if not content:
        if context.get("answers"):
            parts = []
            for qa in context["answers"]:
                parts.append(f"Q: {qa['question']}\nA: {qa['answer']}\n")
            content = "\n\n".join(parts)
        elif context.get("text"):
            content = context["text"]
        elif context.get("answer"):
            content = context["answer"]

    subfolder = params.get("subfolder", "pipeline")
    result = client.upload_text_to_cosysim_folder(
        name=name,
        content=content,
        subfolder=subfolder,
    )
    return result


def _stage_nexus_store(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Store pipeline results in Nexus as knowledge entries."""
    from engine.nexus.client import get_nexus_client

    client = get_nexus_client()

    title = params.get("title") or context.get("title", "Pipeline Result")
    category = params.get("category", "research")
    content_type = params.get("content_type", "note")
    tags = params.get("tags", [])

    stored_ids: List[str] = []

    if context.get("answers"):
        for qa in context["answers"]:
            try:
                result = client.add_qa(
                    question=qa["question"],
                    answer=qa["answer"],
                    category=category,
                )
                if result:
                    stored_ids.append(str(result.get("id", "")))
            except Exception as exc:
                logger.warning("Failed to store Q&A: %s", exc)

    content_parts: List[str] = []
    if context.get("answer"):
        content_parts.append(context["answer"])
    if context.get("text"):
        content_parts.append(context["text"])
    if context.get("doc_id"):
        content_parts.append(f"\nGoogle Doc: https://docs.google.com/document/d/{context['doc_id']}/edit")
    if context.get("sheet_id"):
        content_parts.append(f"\nGoogle Sheet: https://docs.google.com/spreadsheets/d/{context['sheet_id']}/edit")
    if context.get("notebook_id"):
        content_parts.append(f"\nNotebookLM: notebook {context['notebook_id']}")

    full_content = "\n\n".join(content_parts) if content_parts else f"Pipeline {context.get('pipeline_name', 'unknown')} completed."

    try:
        entry = client.add_entry(
            title=title,
            content=full_content,
            content_type=content_type,
            category=category,
            tags=tags,
        )
        if entry:
            stored_ids.append(str(entry.get("id", "")))
    except Exception as exc:
        logger.warning("Failed to store knowledge entry: %s", exc)

    return {
        "stored_ids": stored_ids,
        "entry_count": len(stored_ids),
    }


def _stage_columnsmith(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Run Columnsmith AI transformations on sheet columns."""
    from engine.integrations.gsheets_client import get_sheets_client

    client = get_sheets_client()
    if client is None:
        raise RuntimeError("No Google Sheets account available")

    sheet_id = params.get("sheet_id") or context.get("sheet_id", "")
    column = params.get("column", "C")
    formula = params.get("formula", "")
    source_columns = params.get("source_columns")

    result = client.execute_columnsmith(
        spreadsheet_id=sheet_id,
        column=column,
        formula=formula,
        source_columns=source_columns,
    )
    return result


def _stage_export_doc(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Export a Google Doc to text for downstream processing."""
    from engine.integrations.google_docs_client import get_docs_client

    client = get_docs_client()
    if client is None:
        raise RuntimeError("No Google Docs account available")

    doc_id = params.get("doc_id") or context.get("doc_id", "")
    fmt = params.get("format", "text")

    content = client.export_doc(doc_id, format=fmt)
    return {"doc_id": doc_id, "text": content, "format": fmt}


def _stage_nlm_add_source(params: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Add a source to an NLM notebook (text, URL, or Drive file)."""
    from engine.nexus.nlm_engine import get_nlm_engine

    engine = get_nlm_engine()
    notebook_id = params.get("notebook_id") or context.get("notebook_id", "")
    source = params.get("source", "")
    source_type = params.get("source_type", "text")

    if not source and context.get("text"):
        source = context["text"]
        source_type = "text"

    result = engine.add_source(notebook_id, source, source_type=source_type)
    return {"notebook_id": notebook_id, "source_added": True, "result": result}


def _stage_workspace_generate(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Generate text via WorkspaceGeminiClient.stream_generate.

    Directly invokes the Workspace Gemini generation endpoint,
    independent of Docs/Sheets-specific wrappers.

    Params:
        prompt (str): Generation prompt (or falls back to ``topic`` / ``question``).
        document_type (str): ``"sheets"`` or ``"docs"`` — selects API key and
            context code.  Defaults to ``"sheets"``.
        doc_id (str): Optional document / spreadsheet ID for context.

    Returns:
        Dict with ``text``, ``model``, ``prompt_tokens``, ``completion_tokens``.
    """
    from engine.integrations.workspace_gemini_client import get_workspace_gemini_client

    prompt = (
        params.get("prompt")
        or context.get("prompt")
        or context.get("topic")
        or context.get("question", "")
    )
    doc_type = params.get("document_type", context.get("document_type", "sheets"))
    doc_id = params.get("doc_id", context.get("doc_id"))

    client = get_workspace_gemini_client(document_type=doc_type)
    result = client.stream_generate(prompt, doc_id=doc_id)

    return {
        "text": result.get("text", ""),
        "model": result.get("model", ""),
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "generated": True,
    }


def _stage_fetch_news(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Fetch news articles via the standalone NewsPipeline.

    Bridges the independent RSS/web news fetcher into the workspace pipeline,
    so ``news_pipeline`` templates can start with real article fetching
    instead of generic NLM research.

    Params:
        category (str): News category to fetch (``"ai_research"``, ``"tech"``,
            ``"world"``, ``"science"``).  If empty, fetches all categories.
        limit (int): Max articles per source (default 20).
        store (bool): Whether to store raw articles to Nexus (default True).

    Returns:
        Dict with ``articles`` list, ``total_fetched``, ``total_stored``,
        ``digest`` markdown, and ``text`` (for downstream stages).
    """
    from engine.nexus.news.news_pipeline import get_news_pipeline
    from engine.nexus.news_sources import get_questions

    category = (
        params.get("category")
        or context.get("category")
        or context.get("topic", "")
    )

    news = get_news_pipeline()

    if category and category in ("ai_research", "tech", "world", "science"):
        items = news.fetch_category(category)
    else:
        items = []
        for cat_items in (news.fetch_all() or {}).values():
            items.extend(cat_items)

    stored = 0
    if params.get("store", True) and items:
        stored = news.store_items_to_nexus(items)

    digest = news.build_digest(items, category=category or "all")

    digest_text = ""
    if digest:
        lines = [f"# News Digest — {category or 'all'}"]
        for item in (digest.items or []):
            lines.append(f"\n## {item.title}")
            lines.append(f"Source: {item.source} | {item.url}")
            lines.append(item.summary or "")
        digest_text = "\n".join(lines)

    questions = get_questions(category) if category else []

    return {
        "articles": [
            {"title": i.title, "url": i.url, "summary": i.summary, "source": i.source}
            for i in (items or [])
        ],
        "total_fetched": len(items or []),
        "total_stored": stored,
        "digest": digest_text,
        "text": digest_text,
        "distillation_questions": questions,
    }


def _stage_docs_to_sheets(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Convert a Google Doc export into a structured Google Sheet.

    Exports a doc as text, then uses Workspace Gemini to build a spreadsheet
    from the document content — enabling structured data extraction from
    unstructured documents.

    Params:
        doc_id (str): Document ID to export (or from context).
        sheet_title (str): Title for the new sheet.
        extraction_prompt (str): Optional Gemini prompt for how to structure
            the data.  Defaults to a generic "extract key data" prompt.

    Returns:
        Dict with ``doc_id``, ``sheet_id``, ``sheet_url``, ``rows_created``.
    """
    from engine.integrations.google_docs_client import get_docs_client
    from engine.integrations.gsheets_client import get_sheets_client

    doc_id = params.get("doc_id") or context.get("doc_id", "")
    sheet_title = params.get("sheet_title") or context.get("title", "Extracted Data")
    extraction_prompt = params.get("extraction_prompt", "")

    docs_client = get_docs_client()
    if docs_client is None:
        raise RuntimeError("No Google Docs account available")

    doc_text = docs_client.export_doc(doc_id, format="text")
    if not doc_text:
        raise RuntimeError(f"Failed to export doc {doc_id}")

    sheets_client = get_sheets_client()
    if sheets_client is None:
        raise RuntimeError("No Google Sheets account available")

    if extraction_prompt:
        prompt = f"{extraction_prompt}\n\nSource document content:\n{doc_text[:8000]}"
        result = sheets_client.build_with_gemini(prompt=prompt, title=sheet_title)
    else:
        result = sheets_client.create_spreadsheet(title=sheet_title)
        if result:
            lines = doc_text.strip().split("\n")
            data = [[line] for line in lines[:500]]
            if data:
                sheets_client.write_range(
                    result.get("spreadsheetId", ""),
                    "Sheet1!A1",
                    data,
                )

    sheet_id = (result or {}).get("spreadsheetId", "")
    return {
        "doc_id": doc_id,
        "sheet_id": sheet_id,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        "rows_created": len(doc_text.strip().split("\n")) if doc_text else 0,
        "text": doc_text,
    }


def _stage_sheets_to_doc(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Convert structured sheet data into a formatted Google Doc.

    Reads a sheet range and creates a document from it, optionally using
    Workspace Gemini to transform the data into prose or a report.

    Params:
        sheet_id (str): Spreadsheet ID (or from context).
        range (str): Sheet range to read (default ``"Sheet1"``).
        doc_title (str): Title for the new document.
        transform_prompt (str): Optional Gemini prompt for transforming
            the data into document format.

    Returns:
        Dict with ``sheet_id``, ``doc_id``, ``doc_url``.
    """
    from engine.integrations.google_docs_client import get_docs_client
    from engine.integrations.gsheets_client import get_sheets_client

    sheet_id = params.get("sheet_id") or context.get("sheet_id", "")
    read_range = params.get("range", "Sheet1")
    doc_title = params.get("doc_title") or context.get("title", "Sheet Report")
    transform_prompt = params.get("transform_prompt", "")

    sheets_client = get_sheets_client()
    if sheets_client is None:
        raise RuntimeError("No Google Sheets account available")

    data = sheets_client.read_range(sheet_id, read_range)
    if not data:
        raise RuntimeError(f"No data in sheet {sheet_id} range {read_range}")

    text_lines = []
    for row in data:
        text_lines.append(" | ".join(str(cell) for cell in row))
    sheet_text = "\n".join(text_lines)

    docs_client = get_docs_client()
    if docs_client is None:
        raise RuntimeError("No Google Docs account available")

    if transform_prompt:
        full_prompt = f"{transform_prompt}\n\nData:\n{sheet_text[:8000]}"
        result = docs_client.create_with_gemini(title=doc_title, prompt=full_prompt)
    else:
        result = docs_client.create_doc(title=doc_title)
        if result and result.get("documentId"):
            docs_client.append_to_doc(result["documentId"], sheet_text)

    doc_id = (result or {}).get("documentId", "")
    return {
        "sheet_id": sheet_id,
        "doc_id": doc_id,
        "doc_url": f"https://docs.google.com/document/d/{doc_id}/edit",
        "text": sheet_text,
    }


def _stage_gemini_enrich(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Enrich content using Workspace Gemini for cross-stage transformation.

    Takes text from a previous stage and runs a Gemini prompt against it
    to transform, summarise, expand, or restructure the content before
    passing it to the next stage.

    Params:
        prompt (str): Transformation prompt (e.g. "Summarise into 5 bullet
            points", "Extract action items", "Rewrite for a technical
            audience").
        text (str): Input text to transform (or from context).
        document_type (str): ``"sheets"`` or ``"docs"`` context.

    Returns:
        Dict with ``text`` (enriched output), ``original_length``,
        ``enriched_length``, ``prompt``.
    """
    from engine.integrations.workspace_gemini_client import get_workspace_gemini_client

    prompt = params.get("prompt") or context.get("prompt", "Summarise this content")
    text = params.get("text") or context.get("text", "")
    doc_type = params.get("document_type", "docs")

    if not text and context.get("answers"):
        parts = []
        for qa in context["answers"]:
            parts.append(f"Q: {qa['question']}\nA: {qa['answer']}")
        text = "\n\n".join(parts)

    if not text and context.get("digest"):
        text = context["digest"]

    full_prompt = f"{prompt}\n\nContent:\n{text[:12000]}"
    client = get_workspace_gemini_client(document_type=doc_type)
    result = client.stream_generate(full_prompt)

    enriched_text = result.get("text", "")
    return {
        "text": enriched_text,
        "original_length": len(text),
        "enriched_length": len(enriched_text),
        "prompt": prompt,
        "model": result.get("model", ""),
    }


def _stage_prewarm(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Pre-warm Workspace Gemini models to reduce first-request latency.

    Calls the espresso-pa prewarm endpoint before generation stages.
    Should be the first stage in latency-sensitive pipelines.

    Params:
        document_type (str): ``"sheets"`` or ``"docs"`` context.

    Returns:
        Dict with ``prewarmed`` status and ``duration_ms``.
    """
    import requests as req

    doc_type = params.get("document_type", context.get("document_type", "sheets"))
    ctx_code = 3 if doc_type == "sheets" else 1

    try:
        resp = req.post(
            "https://espresso-pa.clients6.google.com/v1/prewarm",
            json=[ctx_code],
            timeout=10,
        )
        return {
            "prewarmed": resp.status_code == 200,
            "status_code": resp.status_code,
            "document_type": doc_type,
        }
    except Exception as exc:
        logger.warning("Prewarm failed (non-blocking): %s", exc)
        return {"prewarmed": False, "error": str(exc)}


def _stage_drive_copy(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Copy a Drive file using the v2internal API.

    Supports template duplication with automatic title and parent override.

    Params:
        file_id (str): Source file ID to copy (or from context).
        title (str): Title for the copy.
        parent_id (str): Destination folder ID.

    Returns:
        Dict with the new file's ``id``, ``title``, and ``alternateLink``.
    """
    from engine.integrations.google_drive_client import get_drive_client

    file_id = params.get("file_id") or context.get("file_id")
    if not file_id:
        raise ValueError("drive_copy requires file_id")

    client = get_drive_client()
    result = client.v2_copy_file(
        file_id=file_id,
        title=params.get("title") or context.get("title"),
        parent_id=params.get("parent_id") or context.get("parent_id"),
        description=params.get("description"),
    )
    return result


def _stage_drive_export(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Export a Google Workspace file to a different format.

    Exports Docs/Sheets/Slides to text, HTML, PDF, CSV, DOCX, or XLSX.

    Params:
        file_id (str): File ID to export (or from context).
        mime_type (str): Target format — ``text``, ``html``, ``pdf``,
            ``csv``, ``docx``, ``xlsx``, or full MIME type.

    Returns:
        Dict with ``content`` (decoded text or base64), ``mime_type``,
        and ``size`` in bytes.
    """
    import base64

    from engine.integrations.google_drive_client import get_drive_client

    file_id = params.get("file_id") or context.get("file_id") or context.get("doc_id")
    if not file_id:
        raise ValueError("drive_export requires file_id")

    mime_type = params.get("mime_type", "text")
    client = get_drive_client()
    content = client.v2_export_file(file_id, mime_type)

    is_text = mime_type in ("text", "html", "csv", "text/plain", "text/html", "text/csv")
    return {
        "content": content.decode("utf-8", errors="replace") if is_text else base64.b64encode(content).decode(),
        "mime_type": mime_type,
        "size": len(content),
        "file_id": file_id,
        "is_text": is_text,
    }


def _stage_drive_permissions(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Manage file permissions using the v2internal API.

    When ``action`` is ``list``, returns current permissions.
    When ``action`` is ``set``, adds or updates a permission.

    Params:
        file_id (str): Target file ID (or from context).
        action (str): ``list`` or ``set``.
        role (str): Permission role (for ``set``).
        perm_type (str): Permission type (for ``set``).
        email (str): Email address (for user/group types).

    Returns:
        Dict with ``permissions`` list or created ``permission`` dict.
    """
    from engine.integrations.google_drive_client import get_drive_client

    file_id = params.get("file_id") or context.get("file_id")
    if not file_id:
        raise ValueError("drive_permissions requires file_id")

    action = params.get("action", "list")
    client = get_drive_client()

    if action == "set":
        perm = client.v2_insert_permission(
            file_id=file_id,
            role=params.get("role", "reader"),
            perm_type=params.get("perm_type", "anyone"),
            email=params.get("email"),
            with_link=params.get("with_link", True),
            send_notification=params.get("send_notification", False),
        )
        return {"permission": perm, "action": "set"}
    else:
        perms = client.v2_get_permissions(file_id)
        return {"permissions": perms, "action": "list", "count": len(perms)}


def _stage_sheet_revisions(
    params: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    """Retrieve revision history for a spreadsheet.

    Params:
        spreadsheet_id (str): Target spreadsheet (or from context).
        max_results (int): Maximum revisions to return (default 50).

    Returns:
        Dict with ``revisions`` list and ``count``.
    """
    from engine.integrations.gsheets_client import get_sheets_client

    spreadsheet_id = params.get("spreadsheet_id") or context.get("spreadsheet_id") or context.get("sheet_id")
    if not spreadsheet_id:
        raise ValueError("sheet_revisions requires spreadsheet_id")

    client = get_sheets_client()
    revisions = client.get_revision_history(
        spreadsheet_id,
        max_results=params.get("max_results", 50),
    )
    return {"revisions": revisions, "count": len(revisions), "spreadsheet_id": spreadsheet_id}


# ──── Colab Stages (v1.19c) ──────────────────────────────────────────────────


def _stage_colab_execute(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Python code in a Colab GPU runtime.

    Params:
        code: Python source code to execute.
        timeout: Execution timeout in seconds (default 120).

    Returns:
        Dict with ``output``, ``success``, and ``runtime_id`` keys.
    """
    from engine.integrations.colab_client import get_colab_client

    code = params.get("code") or context.get("code", "")
    if not code:
        return {"error": "No code provided", "success": False}

    timeout = int(params.get("timeout", context.get("timeout", 120)))
    try:
        client = get_colab_client()
        result = client.run_python(code, timeout=timeout)
        return {
            "output": result.get("output", ""),
            "success": result.get("success", False),
            "runtime_id": result.get("runtime_id", ""),
            "execution_count": result.get("execution_count", 0),
        }
    except Exception as exc:
        return {"error": str(exc), "success": False}


def _stage_colab_ask(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the Colab Gemini agent a question.

    Params:
        prompt: The question or instruction to send to Gemini.
        context_text: Optional notebook/code context for grounded answers.
        timeout: Response timeout in seconds (default 120).

    Returns:
        Dict with ``answer`` and ``prompt`` keys.
    """
    from engine.integrations.colab_client import get_colab_client

    prompt = params.get("prompt") or context.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided", "answer": ""}

    context_text = params.get("context_text") or context.get("context_text", "")
    timeout = int(params.get("timeout", context.get("timeout", 120)))
    try:
        client = get_colab_client()
        answer = client.ask(prompt, context=context_text, timeout=timeout)
        return {"answer": answer, "prompt": prompt}
    except Exception as exc:
        return {"error": str(exc), "answer": ""}


def _stage_colab_build(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Build a Colab notebook from a task description.

    Uses the full Colab AI agent workflow: create_task → update_task → query_task
    to generate a complete notebook for a given task.

    Params:
        task_description: What the notebook should do.
        timeout: Max seconds to wait for task completion (default 180).

    Returns:
        Dict with ``notebook_content``, ``task_id``, and ``status`` keys.
    """
    from engine.integrations.colab_client import get_colab_client

    description = params.get("task_description") or context.get("task_description", "")
    if not description:
        return {"error": "No task_description provided", "status": "failed"}

    timeout = int(params.get("timeout", context.get("timeout", 180)))
    try:
        client = get_colab_client()

        task_id = client.create_task()
        client.update_task(task_id, description)

        import time as _time
        deadline = _time.time() + timeout
        notebook_content = None
        while _time.time() < deadline:
            result = client.query_task(task_id)
            if result is not None:
                notebook_content = result
                break
            _time.sleep(3)

        if notebook_content is None:
            return {"task_id": task_id, "status": "timeout", "notebook_content": ""}

        return {
            "task_id": task_id,
            "status": "complete",
            "notebook_content": notebook_content,
        }
    except Exception as exc:
        return {"error": str(exc), "status": "failed"}


# ──── AI Studio Stage Functions (v1.21b) ─────────────────────────────────────


def _stage_aistudio_generate(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Generate content via AI Studio.

    Params:
        prompt: Text prompt for content generation.
        model: Model name (default from context or 'gemini-2.5-flash').
        temperature: Sampling temperature (default 0.7).
        max_tokens: Maximum output tokens (default 8192).

    Returns:
        Dict with ``content``, ``model``, and ``tokens_used`` keys.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    prompt = params.get("prompt") or context.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided", "content": ""}

    model = params.get("model") or context.get("model", "gemini-2.5-flash")
    temperature = float(params.get("temperature", context.get("temperature", 0.7)))
    max_tokens = int(params.get("max_tokens", context.get("max_tokens", 8192)))
    try:
        client = get_aistudio_client()
        result = client.generate_content(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "content": result.get("text", result.get("content", "")),
            "model": model,
            "tokens_used": result.get("usage", {}).get("total_tokens", 0),
        }
    except Exception as exc:
        return {"error": str(exc), "content": ""}


def _stage_aistudio_embed(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Embed content via AI Studio embedding API.

    Params:
        text: Text to embed. Falls back to context content/output.
        model: Embedding model name (default 'text-embedding-004').
        task_type: Embedding task type (default 'RETRIEVAL_DOCUMENT').

    Returns:
        Dict with ``embedding``, ``dimensions``, and ``model`` keys.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    text = params.get("text") or context.get("content", context.get("output", ""))
    if not text:
        return {"error": "No text provided", "embedding": []}

    model = params.get("model") or context.get("embed_model", "text-embedding-004")
    task_type = params.get("task_type") or context.get("task_type", "RETRIEVAL_DOCUMENT")
    try:
        client = get_aistudio_client()
        result = client.embed_content(text=text, model=model, task_type=task_type)
        embedding = result.get("embedding", result.get("values", []))
        return {
            "embedding": embedding,
            "dimensions": len(embedding) if isinstance(embedding, list) else 0,
            "model": model,
        }
    except Exception as exc:
        return {"error": str(exc), "embedding": []}


def _stage_aistudio_create_applet(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Create and optionally deploy an AI Studio applet.

    Params:
        name: Applet display name.
        prompt: System prompt / instructions for the applet.
        model: Model to use (default 'gemini-2.5-flash').
        deploy: Whether to deploy immediately (default False).

    Returns:
        Dict with ``applet_id``, ``name``, ``deployed``, and ``url`` keys.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    name = params.get("name") or context.get("applet_name", "")
    prompt = params.get("prompt") or context.get("prompt", "")
    if not name or not prompt:
        return {"error": "Both name and prompt are required", "applet_id": ""}

    model = params.get("model") or context.get("model", "gemini-2.5-flash")
    deploy = bool(params.get("deploy", context.get("deploy", False)))
    try:
        client = get_aistudio_client()
        applet = client.create_applet(name=name, system_instruction=prompt, model=model)
        applet_id = applet.get("id", applet.get("applet_id", ""))

        deployed = False
        url = ""
        if deploy and applet_id:
            deploy_result = client.deploy_applet(applet_id)
            deployed = deploy_result.get("success", False)
            url = deploy_result.get("url", "")

        return {
            "applet_id": applet_id,
            "name": name,
            "deployed": deployed,
            "url": url,
        }
    except Exception as exc:
        return {"error": str(exc), "applet_id": ""}


def _stage_aistudio_generate_image(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Generate images via AI Studio image generation.

    Params:
        prompt: Image generation prompt.
        count: Number of images to generate (default 1).
        aspect_ratio: Aspect ratio (default '1:1').

    Returns:
        Dict with ``images`` list, ``count``, and ``prompt`` keys.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    prompt = params.get("prompt") or context.get("image_prompt", context.get("prompt", ""))
    if not prompt:
        return {"error": "No prompt provided", "images": []}

    count = int(params.get("count", context.get("image_count", 1)))
    aspect_ratio = params.get("aspect_ratio") or context.get("aspect_ratio", "1:1")
    try:
        client = get_aistudio_client()
        result = client.generate_image(prompt=prompt, count=count, aspect_ratio=aspect_ratio)
        images = result.get("images", [result] if result else [])
        return {
            "images": images,
            "count": len(images),
            "prompt": prompt,
        }
    except Exception as exc:
        return {"error": str(exc), "images": []}


# ──── Apps Script Stage Functions (v1.21b) ────────────────────────────────────


def _stage_appscript_run(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Run a function in an Apps Script project.

    Params:
        project_id: The Apps Script project ID.
        function_name: Name of the function to execute.
        parameters: Optional list of parameters to pass.

    Returns:
        Dict with ``result``, ``function_name``, and ``project_id`` keys.
    """
    from engine.integrations.appscript_client import get_appscript_client

    project_id = params.get("project_id") or context.get("project_id", "")
    function_name = params.get("function_name") or context.get("function_name", "")
    if not project_id or not function_name:
        return {"error": "Both project_id and function_name are required", "result": None}

    parameters = params.get("parameters") or context.get("parameters", [])
    try:
        client = get_appscript_client()
        result = client.run_function(project_id, function_name, parameters=parameters)
        return {
            "result": result,
            "function_name": function_name,
            "project_id": project_id,
        }
    except Exception as exc:
        return {"error": str(exc), "result": None}


def _stage_appscript_deploy(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Deploy code to an Apps Script project.

    Params:
        project_id: The Apps Script project ID.
        files: List of file dicts with 'name', 'type', and 'source' keys.
        description: Optional version description.

    Returns:
        Dict with ``success``, ``project_id``, and ``files_saved`` keys.
    """
    from engine.integrations.appscript_client import get_appscript_client

    project_id = params.get("project_id") or context.get("project_id", "")
    files = params.get("files") or context.get("files", [])
    if not project_id or not files:
        return {"error": "Both project_id and files are required", "success": False}

    description = params.get("description") or context.get("description", "Pipeline deployment")
    try:
        client = get_appscript_client()
        result = client.save_code(project_id, files)
        return {
            "success": True,
            "project_id": project_id,
            "files_saved": len(files),
            "description": description,
        }
    except Exception as exc:
        return {"error": str(exc), "success": False}


def _stage_appscript_get_project(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Get Apps Script project information and files.

    Params:
        project_id: The Apps Script project ID.
        include_files: Whether to fetch source files (default True).

    Returns:
        Dict with ``info``, ``files``, and ``project_id`` keys.
    """
    from engine.integrations.appscript_client import get_appscript_client

    project_id = params.get("project_id") or context.get("project_id", "")
    if not project_id:
        return {"error": "project_id is required", "info": {}}

    include_files = bool(params.get("include_files", context.get("include_files", True)))
    try:
        client = get_appscript_client()
        info = client.get_project_info(project_id)
        files = []
        if include_files:
            files = client.get_project_files(project_id)
        return {
            "info": info,
            "files": files,
            "project_id": project_id,
            "file_count": len(files) if isinstance(files, list) else 0,
        }
    except Exception as exc:
        return {"error": str(exc), "info": {}}


# ──── Stage Registry ──────────────────────────────────────────────────────────

STAGE_REGISTRY: Dict[str, Callable] = {
    "nlm_research": _stage_nlm_research,
    "create_doc": _stage_create_doc,
    "create_sheet": _stage_create_sheet,
    "fill_sheet": _stage_fill_sheet,
    "drive_search": _stage_drive_search,
    "drive_ask": _stage_drive_ask,
    "drive_upload": _stage_drive_upload,
    "nexus_store": _stage_nexus_store,
    "columnsmith": _stage_columnsmith,
    "export_doc": _stage_export_doc,
    "nlm_add_source": _stage_nlm_add_source,
    "workspace_generate": _stage_workspace_generate,
    "fetch_news": _stage_fetch_news,
    "docs_to_sheets": _stage_docs_to_sheets,
    "sheets_to_doc": _stage_sheets_to_doc,
    "gemini_enrich": _stage_gemini_enrich,
    "prewarm": _stage_prewarm,
    "drive_copy": _stage_drive_copy,
    "drive_export": _stage_drive_export,
    "drive_permissions": _stage_drive_permissions,
    "sheet_revisions": _stage_sheet_revisions,
    "colab_execute": _stage_colab_execute,
    "colab_ask": _stage_colab_ask,
    "colab_build": _stage_colab_build,
    # AI Studio (v1.21b)
    "aistudio_generate": _stage_aistudio_generate,
    "aistudio_embed": _stage_aistudio_embed,
    "aistudio_create_applet": _stage_aistudio_create_applet,
    "aistudio_generate_image": _stage_aistudio_generate_image,
    # Apps Script (v1.21b)
    "appscript_run": _stage_appscript_run,
    "appscript_deploy": _stage_appscript_deploy,
    "appscript_get_project": _stage_appscript_get_project,
}


# ──── Pipeline Templates ──────────────────────────────────────────────────────

PIPELINE_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "research_and_distill": [
        {"stage": "nlm_research", "params": {}},
        {"stage": "create_sheet", "params": {"title": "Research Data"}},
        {"stage": "drive_upload", "params": {"subfolder": "research"}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "note"}},
    ],
    "create_knowledge_doc": [
        {"stage": "nlm_research", "params": {}},
        {"stage": "create_doc", "params": {}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document"}},
    ],
    "data_enrichment": [
        {"stage": "fill_sheet", "params": {}},
        {"stage": "nexus_store", "params": {"category": "data", "content_type": "note"}},
    ],
    "cross_source_synthesis": [
        {"stage": "drive_search", "params": {}},
        {"stage": "drive_ask", "params": {}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "note"}},
    ],
    "news_pipeline": [
        {"stage": "fetch_news", "params": {"store": True}},
        {"stage": "nlm_research", "params": {}, "optional": True},
        {"stage": "create_sheet", "params": {"title": "News Digest"}},
        {"stage": "nexus_store", "params": {"category": "news", "content_type": "note", "tags": ["news", "digest"]}},
    ],
    "doc_to_notebook": [
        {"stage": "export_doc", "params": {}},
        {"stage": "nlm_add_source", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "note"}},
    ],
    "sheet_to_knowledge": [
        {"stage": "drive_search", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "nexus_store", "params": {"category": "data", "content_type": "note"}},
    ],
    "generate_and_store": [
        {"stage": "workspace_generate", "params": {}},
        {"stage": "nexus_store", "params": {"category": "generated", "content_type": "note"}},
    ],
    "news_to_knowledge": [
        {"stage": "fetch_news", "params": {"store": True}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "create_doc", "params": {}},
        {"stage": "drive_upload", "params": {"subfolder": "news"}},
        {"stage": "nexus_store", "params": {"category": "news", "content_type": "document", "tags": ["news", "knowledge"]}},
    ],

    # ── Cross-Service Chain Prompt Templates ──────────────────────────────────
    # These templates implement the Docs↔Sheets↔NLM↔Drive↔Nexus rotation
    # workflows that leverage each service's built-in Gemini for its domain.

    "docs_nlm_distill": [
        {"stage": "create_doc", "params": {}},
        {"stage": "export_doc", "params": {}},
        {"stage": "nlm_add_source", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document", "tags": ["distilled", "cross-service"]}},
    ],

    "sheets_enrichment_cycle": [
        {"stage": "create_sheet", "params": {}},
        {"stage": "fill_sheet", "params": {}},
        {"stage": "columnsmith", "params": {}, "optional": True},
        {"stage": "sheets_to_doc", "params": {"transform_prompt": "Create a summary report from this data"}},
        {"stage": "nexus_store", "params": {"category": "data", "content_type": "note", "tags": ["enriched", "gemini"]}},
    ],

    "drive_nlm_nexus": [
        {"stage": "drive_search", "params": {}},
        {"stage": "drive_ask", "params": {}},
        {"stage": "gemini_enrich", "params": {"prompt": "Synthesise the key findings and insights"}},
        {"stage": "nlm_add_source", "params": {}, "optional": True},
        {"stage": "nlm_research", "params": {}, "optional": True},
        {"stage": "create_doc", "params": {}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document", "tags": ["drive-sourced", "synthesis"]}},
    ],

    "full_cross_service": [
        {"stage": "prewarm", "params": {}, "optional": True},
        {"stage": "drive_search", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "gemini_enrich", "params": {"prompt": "Extract structured data points, metrics, and key findings"}},
        {"stage": "create_sheet", "params": {"title": "Research Data"}},
        {"stage": "create_doc", "params": {}},
        {"stage": "drive_upload", "params": {"subfolder": "cross-service"}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document", "tags": ["cross-service", "full-rotation"]}},
    ],

    "knowledge_distillation": [
        {"stage": "workspace_generate", "params": {}},
        {"stage": "gemini_enrich", "params": {"prompt": "Distil into clear, concise knowledge entries with key takeaways"}},
        {"stage": "nlm_add_source", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "nexus_store", "params": {"category": "knowledge", "content_type": "note", "tags": ["distilled"]}},
    ],

    "news_full_cycle": [
        {"stage": "fetch_news", "params": {"store": True}},
        {"stage": "gemini_enrich", "params": {"prompt": "Analyse these news articles: identify key themes, trends, and implications"}},
        {"stage": "nlm_add_source", "params": {}, "optional": True},
        {"stage": "nlm_research", "params": {}, "optional": True},
        {"stage": "create_sheet", "params": {"title": "News Analysis"}},
        {"stage": "create_doc", "params": {}},
        {"stage": "drive_upload", "params": {"subfolder": "news"}},
        {"stage": "nexus_store", "params": {"category": "news", "content_type": "document", "tags": ["news", "full-cycle", "analysed"]}},
    ],

    "doc_structure_extract": [
        {"stage": "export_doc", "params": {}},
        {"stage": "gemini_enrich", "params": {"prompt": "Extract all structured data, tables, lists, and key-value pairs from this document"}},
        {"stage": "docs_to_sheets", "params": {"extraction_prompt": "Create a structured spreadsheet from this document's data"}},
        {"stage": "nexus_store", "params": {"category": "data", "content_type": "note", "tags": ["extracted", "structured"]}},
    ],

    "sheet_knowledge_report": [
        {"stage": "sheets_to_doc", "params": {"transform_prompt": "Write a comprehensive analysis report based on this data"}},
        {"stage": "nlm_add_source", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "drive_upload", "params": {"subfolder": "reports"}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document", "tags": ["report", "data-driven"]}},
    ],

    # ── v1.19b Drive v2internal & Sheets Extended Templates ───────────────────

    "drive_template_clone": [
        {"stage": "drive_copy", "params": {}},
        {"stage": "drive_permissions", "params": {"action": "set", "role": "reader", "perm_type": "anyone"}},
        {"stage": "nexus_store", "params": {"category": "drive", "content_type": "note", "tags": ["cloned", "template"]}},
    ],

    "drive_export_and_distill": [
        {"stage": "drive_export", "params": {"mime_type": "text"}},
        {"stage": "gemini_enrich", "params": {"prompt": "Distil the key information, facts, and actionable items"}},
        {"stage": "nlm_add_source", "params": {}, "optional": True},
        {"stage": "nlm_research", "params": {}, "optional": True},
        {"stage": "nexus_store", "params": {"category": "knowledge", "content_type": "document", "tags": ["exported", "distilled"]}},
    ],

    "drive_audit_permissions": [
        {"stage": "drive_permissions", "params": {"action": "list"}},
        {"stage": "nexus_store", "params": {"category": "audit", "content_type": "note", "tags": ["permissions", "audit"]}},
    ],

    "sheet_revision_audit": [
        {"stage": "sheet_revisions", "params": {"max_results": 100}},
        {"stage": "gemini_enrich", "params": {"prompt": "Analyse these spreadsheet revisions: identify major changes, editors, and patterns"}, "optional": True},
        {"stage": "nexus_store", "params": {"category": "audit", "content_type": "note", "tags": ["revisions", "audit"]}},
    ],

    # ── Colab Pipeline Templates (v1.19c) ────────────────────────────────

    "research_and_compute": [
        {"stage": "nlm_research", "params": {}},
        {"stage": "colab_ask", "params": {"prompt": "Analyse the research findings and identify key claims that can be tested computationally"}},
        {"stage": "colab_execute", "params": {}, "optional": True},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "note", "tags": ["research", "computed", "colab"]}},
    ],

    "data_analysis": [
        {"stage": "drive_search", "params": {}},
        {"stage": "colab_execute", "params": {}},
        {"stage": "create_sheet", "params": {}},
        {"stage": "nexus_store", "params": {"category": "analysis", "content_type": "document", "tags": ["data", "analysis", "colab"]}},
    ],

    "nlm_colab_loop": [
        {"stage": "nlm_research", "params": {}},
        {"stage": "colab_ask", "params": {"prompt": "Verify these research claims and identify gaps or errors"}},
        {"stage": "colab_execute", "params": {}, "optional": True},
        {"stage": "gemini_enrich", "params": {"prompt": "Synthesise the research findings with the computational verification results"}, "optional": True},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "note", "tags": ["verified", "nlm", "colab"]}},
    ],

    "colab_build_and_store": [
        {"stage": "colab_build", "params": {}},
        {"stage": "drive_upload", "params": {}, "optional": True},
        {"stage": "nexus_store", "params": {"category": "code", "content_type": "code", "tags": ["notebook", "generated", "colab"]}},
    ],

    # ── AI Studio Pipeline Templates (v1.21b) ────────────────────────────────

    "aistudio_content_pipeline": [
        {"stage": "aistudio_generate", "params": {}},
        {"stage": "aistudio_embed", "params": {}},
        {"stage": "nexus_store", "params": {"category": "generated", "content_type": "note", "tags": ["aistudio", "generated"]}},
    ],

    "aistudio_embed_and_store": [
        {"stage": "aistudio_embed", "params": {}},
        {"stage": "nexus_store", "params": {"category": "embeddings", "content_type": "note", "tags": ["aistudio", "embedding"]}},
    ],

    "aistudio_applet_deploy": [
        {"stage": "aistudio_create_applet", "params": {"deploy": True}},
        {"stage": "nexus_store", "params": {"category": "applets", "content_type": "code", "tags": ["aistudio", "applet", "deployed"]}},
    ],

    "aistudio_image_pipeline": [
        {"stage": "aistudio_generate_image", "params": {}},
        {"stage": "drive_upload", "params": {"subfolder": "generated-images"}},
        {"stage": "nexus_store", "params": {"category": "media", "content_type": "note", "tags": ["aistudio", "image", "generated"]}},
    ],

    "aistudio_research_generate": [
        {"stage": "nlm_research", "params": {}},
        {"stage": "aistudio_generate", "params": {}},
        {"stage": "aistudio_embed", "params": {}, "optional": True},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document", "tags": ["aistudio", "nlm", "research"]}},
    ],

    # ── Apps Script Pipeline Templates (v1.21b) ──────────────────────────────

    "appscript_automation": [
        {"stage": "appscript_run", "params": {}},
        {"stage": "nexus_store", "params": {"category": "automation", "content_type": "code", "tags": ["appscript", "automation"]}},
    ],

    "appscript_deploy_and_test": [
        {"stage": "appscript_deploy", "params": {}},
        {"stage": "appscript_run", "params": {}},
        {"stage": "nexus_store", "params": {"category": "automation", "content_type": "code", "tags": ["appscript", "deployed", "tested"]}},
    ],

    "appscript_inspect_and_store": [
        {"stage": "appscript_get_project", "params": {"include_files": True}},
        {"stage": "nexus_store", "params": {"category": "code", "content_type": "code", "tags": ["appscript", "inspection"]}},
    ],

    # ── Cross-Service with AI Studio/Apps Script (v1.21b) ────────────────────

    "full_cross_service_v2": [
        {"stage": "prewarm", "params": {}, "optional": True},
        {"stage": "drive_search", "params": {}},
        {"stage": "nlm_research", "params": {}},
        {"stage": "aistudio_generate", "params": {}},
        {"stage": "aistudio_embed", "params": {}, "optional": True},
        {"stage": "create_sheet", "params": {"title": "Research Data v2"}},
        {"stage": "create_doc", "params": {}},
        {"stage": "drive_upload", "params": {"subfolder": "cross-service-v2"}},
        {"stage": "nexus_store", "params": {"category": "research", "content_type": "document", "tags": ["cross-service", "v2", "aistudio"]}},
    ],

    "appscript_data_pipeline": [
        {"stage": "appscript_run", "params": {}},
        {"stage": "create_sheet", "params": {}},
        {"stage": "aistudio_generate", "params": {"prompt": "Analyse and summarise the data from the Apps Script execution"}},
        {"stage": "nexus_store", "params": {"category": "data", "content_type": "note", "tags": ["appscript", "data", "pipeline"]}},
    ],
}


# ──── Pipeline Orchestrator ───────────────────────────────────────────────────


class WorkspacePipeline:
    """Cross-service pipeline orchestrator.

    Executes named pipeline templates or custom stage sequences.
    Tracks runs with full state and stage-level results.

    Example::

        pipeline = get_workspace_pipeline()
        result = pipeline.run("research_and_distill", topic="quantum computing")
        print(result.final_output)
    """

    def __init__(self) -> None:
        self._runs: Dict[str, PipelineRun] = {}
        self._custom_stages: Dict[str, Callable] = {}

    # ──── Stage Management ────────────────────────────────────────────────

    def register_stage(self, name: str, executor: Callable) -> None:
        """Register a custom stage executor.

        Args:
            name: Stage name.
            executor: Function(params, context) → output.
        """
        self._custom_stages[name] = executor
        logger.info("Registered custom pipeline stage: %s", name)

    def _get_executor(self, stage_name: str) -> Optional[Callable]:
        """Look up executor for a stage name."""
        return self._custom_stages.get(stage_name) or STAGE_REGISTRY.get(stage_name)

    # ──── Pipeline Execution ──────────────────────────────────────────────

    def run(
        self,
        pipeline_name: str,
        stages: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> PipelineRun:
        """Execute a pipeline by template name or custom stage list.

        If ``stages`` is provided, uses those stages directly.  Otherwise
        looks up the template by ``pipeline_name``.

        All ``kwargs`` are merged into the initial context and passed
        to every stage.

        Args:
            pipeline_name: Template name or custom identifier.
            stages: Optional explicit stage list (overrides template).
            **kwargs: Pipeline parameters (topic, sheet_id, doc_id, etc.).

        Returns:
            PipelineRun with final status and all stage results.
        """
        run_id = str(uuid.uuid4())[:12]

        if stages is None:
            stages = PIPELINE_TEMPLATES.get(pipeline_name)
            if stages is None:
                run = PipelineRun(
                    run_id=run_id,
                    pipeline_name=pipeline_name,
                    status=PipelineStatus.FAILED,
                    error=f"Unknown pipeline template: {pipeline_name}",
                )
                self._runs[run_id] = run
                return run

        run = PipelineRun(
            run_id=run_id,
            pipeline_name=pipeline_name,
            params=dict(kwargs),
        )

        for stage_def in stages:
            run.stages.append(StageResult(stage_name=stage_def["stage"]))

        self._runs[run_id] = run
        run.status = PipelineStatus.RUNNING

        context: Dict[str, Any] = {
            "run_id": run_id,
            "pipeline_name": pipeline_name,
            **kwargs,
        }

        logger.info(
            "Pipeline %s started (run_id=%s, stages=%d)",
            pipeline_name,
            run_id,
            len(stages),
        )

        for idx, stage_def in enumerate(stages):
            stage_name = stage_def["stage"]
            stage_params = {**stage_def.get("params", {}), **kwargs}
            stage_result = run.stages[idx]

            executor = self._get_executor(stage_name)
            if executor is None:
                stage_result.status = StageStatus.FAILED
                stage_result.error = f"No executor for stage: {stage_name}"
                run.status = PipelineStatus.FAILED
                run.error = stage_result.error
                run.completed_at = time.time()
                logger.error("Pipeline %s failed at stage %s: no executor", pipeline_name, stage_name)
                return run

            stage_result.status = StageStatus.RUNNING
            t0 = time.time()

            try:
                output = executor(stage_params, context)
                stage_result.output = output
                stage_result.status = StageStatus.COMPLETED
                stage_result.duration_ms = (time.time() - t0) * 1000

                if isinstance(output, dict):
                    context.update(output)

                logger.info(
                    "Pipeline %s stage %d/%d '%s' completed (%.0fms)",
                    pipeline_name,
                    idx + 1,
                    len(stages),
                    stage_name,
                    stage_result.duration_ms,
                )
            except Exception as exc:
                stage_result.status = StageStatus.FAILED
                stage_result.error = str(exc)
                stage_result.duration_ms = (time.time() - t0) * 1000

                if stage_def.get("optional", False):
                    stage_result.status = StageStatus.SKIPPED
                    logger.warning(
                        "Pipeline %s optional stage '%s' failed (skipped): %s",
                        pipeline_name,
                        stage_name,
                        exc,
                    )
                    continue

                run.status = PipelineStatus.FAILED
                run.error = f"Stage '{stage_name}' failed: {exc}"
                run.completed_at = time.time()
                logger.error("Pipeline %s failed at stage '%s': %s", pipeline_name, stage_name, exc)
                return run

        run.status = PipelineStatus.COMPLETED
        run.completed_at = time.time()
        run.final_output = context

        logger.info(
            "Pipeline %s completed (run_id=%s, %.0fms, %d stages)",
            pipeline_name,
            run_id,
            run.duration_ms,
            len(stages),
        )
        return run

    # ──── Run Management ──────────────────────────────────────────────────

    def get_run(self, run_id: str) -> Optional[PipelineRun]:
        """Get a pipeline run by ID.

        Args:
            run_id: The run identifier.

        Returns:
            PipelineRun, or None if not found.
        """
        return self._runs.get(run_id)

    def list_runs(
        self,
        status: Optional[PipelineStatus] = None,
        limit: int = 50,
    ) -> List[PipelineRun]:
        """List pipeline runs, optionally filtered by status.

        Args:
            status: Filter by pipeline status.
            limit: Maximum runs to return.

        Returns:
            List of PipelineRun objects.
        """
        runs = list(self._runs.values())
        if status:
            runs = [r for r in runs if r.status == status]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def list_templates(self) -> Dict[str, List[str]]:
        """List available pipeline templates and their stages.

        Returns:
            Dict of template_name → list of stage names.
        """
        return {
            name: [s["stage"] for s in stages]
            for name, stages in PIPELINE_TEMPLATES.items()
        }

    def clear_runs(self, keep_last: int = 100) -> int:
        """Clear old pipeline runs, keeping the most recent.

        Args:
            keep_last: Number of most recent runs to keep.

        Returns:
            Number of runs removed.
        """
        runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        to_remove = runs[keep_last:]
        for r in to_remove:
            del self._runs[r.run_id]
        return len(to_remove)

    # ──── Convenience Methods ─────────────────────────────────────────────

    def research_and_distill(self, topic: str, **kwargs: Any) -> PipelineRun:
        """Run the research_and_distill pipeline.

        Args:
            topic: Research topic.
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run("research_and_distill", topic=topic, **kwargs)

    def create_knowledge_doc(self, topic: str, title: Optional[str] = None, **kwargs: Any) -> PipelineRun:
        """Run the create_knowledge_doc pipeline.

        Args:
            topic: Topic to research and document.
            title: Optional document title (defaults to topic).
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run(
            "create_knowledge_doc",
            topic=topic,
            title=title or f"Knowledge: {topic}",
            **kwargs,
        )

    def cross_source_synthesis(self, topic: str, **kwargs: Any) -> PipelineRun:
        """Run the cross_source_synthesis pipeline.

        Args:
            topic: Topic to synthesise across sources.
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run("cross_source_synthesis", topic=topic, **kwargs)

    def news_digest(self, topic: str, sources: Optional[List[str]] = None, **kwargs: Any) -> PipelineRun:
        """Run the news_pipeline for a topic.

        Args:
            topic: News topic to digest.
            sources: Optional list of source URLs.
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run("news_pipeline", topic=topic, sources=sources or [], **kwargs)

    def docs_nlm_distill(self, topic: str, title: Optional[str] = None, **kwargs: Any) -> PipelineRun:
        """Run the docs_nlm_distill pipeline.

        Creates a doc, exports it to NLM, researches, and stores in Nexus.

        Args:
            topic: Topic to document and distill.
            title: Optional document title.
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run(
            "docs_nlm_distill",
            topic=topic,
            title=title or f"Distill: {topic}",
            **kwargs,
        )

    def full_cross_service(self, topic: str, **kwargs: Any) -> PipelineRun:
        """Run the full_cross_service pipeline.

        Complete rotation: Drive → NLM → Gemini → Sheets → Docs → Drive → Nexus.

        Args:
            topic: Research topic for cross-service workflow.
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run("full_cross_service", topic=topic, **kwargs)

    def knowledge_distillation(self, topic: str, **kwargs: Any) -> PipelineRun:
        """Run the knowledge_distillation pipeline.

        Generate → enrich → NLM source → NLM research → Nexus.

        Args:
            topic: Topic to generate and distill.
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run("knowledge_distillation", topic=topic, **kwargs)

    def news_full_cycle(self, category: str = "", **kwargs: Any) -> PipelineRun:
        """Run the news_full_cycle pipeline.

        Fetch → enrich → NLM → Sheet + Doc → Drive → Nexus.

        Args:
            category: News category (ai_research, tech, world, science).
            **kwargs: Additional parameters.

        Returns:
            PipelineRun with results.
        """
        return self.run("news_full_cycle", category=category, **kwargs)


# ──── Factory ─────────────────────────────────────────────────────────────────

_pipeline_instance: Optional[WorkspacePipeline] = None


def get_workspace_pipeline() -> WorkspacePipeline:
    """Get the singleton WorkspacePipeline instance.

    Returns:
        WorkspacePipeline instance.
    """
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = WorkspacePipeline()
    return _pipeline_instance
