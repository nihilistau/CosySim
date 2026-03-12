"""Workspace Pipeline — cross-service orchestrator for Google Workspace + Nexus.

Coordinates workflows across Google Docs, Sheets, Drive, NotebookLM, and Nexus
to execute multi-stage knowledge pipelines.  Each pipeline is a named sequence
of stages that move data between services, with Drive as the intermediate
storage / movement layer and Nexus as the final knowledge destination.

Pipelines:
    research_and_distill  — NLM research → Sheets data → Nexus knowledge
    create_knowledge_doc  — NLM sources → Docs draft → Nexus document
    data_enrichment       — Sheets Fill-with-Gemini → Nexus structured data
    cross_source_synthesis — Drive search → NLM → Nexus synthesis
    news_pipeline         — Fetch → NLM notebook → distill → Sheets → Nexus
    doc_to_notebook       — Docs → Drive → NLM notebook source → distill
    sheet_to_knowledge    — Sheets export → NLM research → Nexus entries
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
        {"stage": "nlm_research", "params": {}},
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
