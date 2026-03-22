"""Workspace skills — MCP skill pack for Google Workspace pipeline operations.

Exposes cross-service Workspace Gemini operations to CosySim agents:
Docs, Sheets, Drive, NotebookLM, and the unified pipeline orchestrator.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import SkillCategory, skill

logger = logging.getLogger(__name__)


# ──── Lazy Accessors ──────────────────────────────────────────────────────────


def _pipeline():
    from engine.nexus.workspace_pipeline import get_workspace_pipeline
    return get_workspace_pipeline()


def _sheets():
    from engine.integrations.gsheets_client import get_sheets_client
    return get_sheets_client()


def _docs():
    from engine.integrations.google_docs_client import get_docs_client
    return get_docs_client()


def _drive():
    from engine.integrations.google_drive_client import get_drive_client
    return get_drive_client()


def _ws_gemini():
    from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
    return get_workspace_gemini_client()


# ──── Search & Discovery ──────────────────────────────────────────────────────


@skill(
    pack="workspace",
    description="Semantic search across Google Drive using AI Overviews",
    tags=["workspace", "drive", "search", "gemini"],
    category=SkillCategory.SYSTEM,
)
def workspace_search(query: str, page_size: int = 20) -> str:
    """Search Drive files with AI-powered semantic matching.

    Goes beyond keyword matching to find files by intent and meaning.
    """
    client = _drive()
    if client is None:
        return json.dumps({"error": "No Drive account available"})

    try:
        results = client.ai_overview_search(query=query, page_size=page_size)
        return json.dumps(results, default=str)
    except Exception as exc:
        logger.error("workspace_search failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Ask Gemini a question about Google Drive files",
    tags=["workspace", "drive", "gemini", "synthesis"],
    category=SkillCategory.SYSTEM,
)
def workspace_ask(
    question: str,
    file_ids: Optional[str] = None,
    max_files: int = 10,
) -> str:
    """Ask Gemini to synthesise an answer from Drive files.

    If file_ids is provided (comma-separated), uses those specific files.
    Otherwise searches Drive for relevant files automatically.
    """
    client = _drive()
    if client is None:
        return json.dumps({"error": "No Drive account available"})

    parsed_ids = file_ids.split(",") if file_ids else None

    try:
        result = client.ask_gemini(
            question=question,
            file_ids=parsed_ids,
            max_context_files=max_files,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_ask failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Document Operations ─────────────────────────────────────────────────────


@skill(
    pack="workspace",
    description="Create a Google Doc with optional Gemini-generated content",
    tags=["workspace", "docs", "create", "gemini"],
    category=SkillCategory.SYSTEM,
)
def workspace_create_doc(
    title: str,
    prompt: str = "",
    content: str = "",
    folder_id: str = "",
) -> str:
    """Create a new Google Doc.

    If prompt is given, uses Gemini to generate the content.
    If content is given, writes it directly.
    If neither, creates an empty document.
    """
    client = _docs()
    if client is None:
        return json.dumps({"error": "No Docs account available"})

    try:
        if prompt:
            result = client.create_with_gemini(
                title=title,
                prompt=prompt,
                folder_id=folder_id or None,
            )
        else:
            result = client.create_doc(title=title, folder_id=folder_id or None)
            if content and result and result.get("documentId"):
                client.append_to_doc(result["documentId"], content)

        doc_id = (result or {}).get("documentId", "")
        return json.dumps({
            "doc_id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        })
    except Exception as exc:
        logger.error("workspace_create_doc failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Spreadsheet Operations ─────────────────────────────────────────────────


@skill(
    pack="workspace",
    description="Build an entire Google Sheet from a natural language prompt",
    tags=["workspace", "sheets", "create", "gemini"],
    category=SkillCategory.SYSTEM,
)
def workspace_create_sheet(title: str, prompt: str) -> str:
    """Create a complete spreadsheet from a natural language description.

    Gemini generates the headers, formulas, data structure, and initial
    data based on the prompt.
    """
    client = _sheets()
    if client is None:
        return json.dumps({"error": "No Sheets account available"})

    try:
        result = client.build_with_gemini(prompt=prompt, title=title)
        sheet_id = (result or {}).get("spreadsheetId", "")
        return json.dumps({
            "sheet_id": sheet_id,
            "title": title,
            "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        })
    except Exception as exc:
        logger.error("workspace_create_sheet failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Fill a Google Sheet range with Gemini-enriched data",
    tags=["workspace", "sheets", "fill", "gemini", "enrichment"],
    category=SkillCategory.SYSTEM,
)
def workspace_fill_sheet(
    sheet_id: str,
    cell_range: str,
    prompt: str,
) -> str:
    """Fill cells in a spreadsheet using Gemini data enrichment.

    Gemini generates or enriches data for the specified range based on
    the prompt and existing cell context.
    """
    client = _sheets()
    if client is None:
        return json.dumps({"error": "No Sheets account available"})

    try:
        result = client.fill_with_gemini(
            spreadsheet_id=sheet_id,
            cell_range=cell_range,
            prompt=prompt,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_fill_sheet failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run AI column transformations via Columnsmith",
    tags=["workspace", "sheets", "columnsmith", "transform"],
    category=SkillCategory.SYSTEM,
)
def workspace_columnsmith(
    sheet_id: str,
    column: str,
    formula: str,
    source_columns: str = "",
) -> str:
    """Apply Gemini-powered transformations to a column.

    Each row is processed independently.  Use the formula to describe
    the transformation in natural language.
    """
    client = _sheets()
    if client is None:
        return json.dumps({"error": "No Sheets account available"})

    try:
        result = client.execute_columnsmith(
            spreadsheet_id=sheet_id,
            column=column,
            formula=formula,
            source_columns=source_columns or None,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_columnsmith failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Workspace Gemini Direct ─────────────────────────────────────────────────


@skill(
    pack="workspace",
    description="Generate text using the Workspace Gemini backend",
    tags=["workspace", "gemini", "generate"],
    category=SkillCategory.SYSTEM,
)
def workspace_generate(
    prompt: str,
    context: str = "",
    document_type: str = "docs",
) -> str:
    """Send a prompt to the Workspace Gemini (appsgenaiserver-pa) backend.

    This is the raw generation endpoint shared across Sheets, Docs, and
    Slides.  For most tasks, prefer the higher-level pipeline skills.
    """
    client = _ws_gemini()
    if client is None:
        return json.dumps({"error": "No Workspace Gemini account available"})

    try:
        result = client.stream_generate(
            prompt=prompt,
            context=context or None,
            document_type=document_type,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_generate failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Get Workspace Gemini quota and usage summary",
    tags=["workspace", "gemini", "quota"],
    category=SkillCategory.SYSTEM,
)
def workspace_quota() -> str:
    """Check current Workspace Gemini API quota and usage."""
    client = _ws_gemini()
    if client is None:
        return json.dumps({"error": "No Workspace Gemini account available"})

    try:
        result = client.quota_summary()
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_quota failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Pipeline Operations ─────────────────────────────────────────────────────


@skill(
    pack="workspace",
    description="Run a full Workspace research pipeline that distils to Nexus",
    tags=["workspace", "pipeline", "research", "nexus"],
    category=SkillCategory.SYSTEM,
    nexus_first=True,
)
def workspace_research(topic: str, questions: str = "") -> str:
    """Research a topic using the full NLM→Sheets→Drive→Nexus pipeline.

    Creates a NotebookLM notebook, researches the topic, structures
    findings in a sheet, uploads to Drive, and stores in Nexus.
    """
    pipeline = _pipeline()
    parsed_questions = [q.strip() for q in questions.split("|") if q.strip()] if questions else None

    try:
        run = pipeline.research_and_distill(
            topic=topic,
            questions=parsed_questions,
        )
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_research failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run a named Workspace pipeline template",
    tags=["workspace", "pipeline", "orchestration"],
    category=SkillCategory.SYSTEM,
)
def workspace_pipeline(template: str, topic: str = "", **kwargs) -> str:
    """Execute a named pipeline template.

    Available templates: research_and_distill, create_knowledge_doc,
    data_enrichment, cross_source_synthesis, news_pipeline,
    doc_to_notebook, sheet_to_knowledge.
    """
    pipeline = _pipeline()

    try:
        run = pipeline.run(template, topic=topic, **kwargs)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_pipeline '%s' failed: %s", template, exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="List available Workspace pipeline templates",
    tags=["workspace", "pipeline", "discovery"],
    category=SkillCategory.SYSTEM,
)
def workspace_list_pipelines() -> str:
    """List all registered pipeline templates and their stage sequences."""
    pipeline = _pipeline()
    templates = pipeline.list_templates()
    return json.dumps(templates)


@skill(
    pack="workspace",
    description="Get status of a running or completed pipeline",
    tags=["workspace", "pipeline", "status"],
    category=SkillCategory.SYSTEM,
)
def workspace_pipeline_status(run_id: str) -> str:
    """Check the status and results of a pipeline run by its ID."""
    pipeline = _pipeline()
    run = pipeline.get_run(run_id)
    if run is None:
        return json.dumps({"error": f"No pipeline run found with id: {run_id}"})
    return json.dumps(run.to_dict(), default=str)


@skill(
    pack="workspace",
    description="Create a knowledge document via the full research pipeline",
    tags=["workspace", "pipeline", "docs", "knowledge"],
    category=SkillCategory.SYSTEM,
)
def workspace_knowledge_doc(topic: str, title: str = "") -> str:
    """Research a topic and create a comprehensive Google Doc.

    Runs the create_knowledge_doc pipeline: NLM research → Google Docs
    draft → Nexus knowledge entry.
    """
    pipeline = _pipeline()

    try:
        run = pipeline.create_knowledge_doc(topic=topic, title=title or None)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_knowledge_doc failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run a cross-source synthesis across Drive files",
    tags=["workspace", "pipeline", "synthesis", "drive"],
    category=SkillCategory.SYSTEM,
)
def workspace_synthesize(topic: str) -> str:
    """Search Drive for relevant files and synthesise an answer.

    Runs the cross_source_synthesis pipeline: Drive search → Gemini
    synthesis → Nexus knowledge entry.
    """
    pipeline = _pipeline()

    try:
        run = pipeline.cross_source_synthesis(topic=topic)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_synthesize failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run the news digest pipeline for a topic",
    tags=["workspace", "pipeline", "news", "digest"],
    category=SkillCategory.SYSTEM,
)
def workspace_news(topic: str, sources: str = "") -> str:
    """Generate a curated news digest for a topic.

    Runs the news_pipeline: NLM research → Sheets digest → Nexus entries.
    Provide source URLs as pipe-separated values.
    """
    pipeline = _pipeline()
    parsed_sources = [s.strip() for s in sources.split("|") if s.strip()] if sources else None

    try:
        run = pipeline.news_digest(topic=topic, sources=parsed_sources)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_news failed: %s", exc)
        return json.dumps({"error": str(exc)})


# v1.49.5 [2026-03-22] — Renamed from workspace_generate to avoid duplicate registration
@skill(
    pack="workspace",
    description="Generate text content using Workspace Gemini and store in Nexus",
    tags=["workspace", "gemini", "generate", "text", "store"],
    category=SkillCategory.SYSTEM,
)
def workspace_generate_and_store(prompt: str, context: str = "sheets", store: bool = True) -> str:
    """Generate content via Workspace Gemini and optionally store in Nexus.

    Uses the workspace_generate pipeline stage. Context can be 'sheets' or 'docs'.
    If store=True, runs generate_and_store template (generates then stores in Nexus).
    If store=False, runs only the generation stage.
    """
    pipeline = _pipeline()
    try:
        if store:
            run = pipeline.run("generate_and_store", topic=prompt, context=context)
        else:
            run = pipeline.run_stages(
                [{"name": "workspace_generate"}],
                topic=prompt,
                prompt=prompt,
                context=context,
            )
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_generate failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Fetch latest news articles via RSS and optionally store in Nexus",
    tags=["workspace", "news", "rss", "fetch"],
    category=SkillCategory.SYSTEM,
)
def workspace_fetch_news(
    categories: str = "ai_research",
    max_articles: int = 20,
    store: bool = True,
) -> str:
    """Fetch news articles from curated RSS sources.

    Categories: ai_research, tech, world, science (pipe-separated for multiple).
    Articles are deduplicated and optionally stored in Nexus.
    """
    pipeline = _pipeline()
    cat_list = [c.strip() for c in categories.split("|") if c.strip()]

    try:
        run = pipeline.run_stages(
            [{"name": "fetch_news"}],
            topic=f"News fetch: {', '.join(cat_list)}",
            categories=cat_list,
            max_articles=max_articles,
            store_articles=store,
        )
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_fetch_news failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run full cross-service pipeline: Drive→NLM→Gemini→Sheets→Docs→Nexus",
    tags=["workspace", "cross-service", "pipeline", "full"],
    category=SkillCategory.SYSTEM,
)
def workspace_full_cross_service(topic: str) -> str:
    """Execute the full cross-service rotation pipeline.

    Searches Drive, researches with NLM, enriches with Gemini, creates
    both a Sheet and a Doc, uploads to Drive, and stores in Nexus.
    This is the most comprehensive pipeline template available.
    """
    pipeline = _pipeline()
    try:
        run = pipeline.full_cross_service(topic=topic)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_full_cross_service failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Distill a topic through Docs→NLM→Nexus knowledge pipeline",
    tags=["workspace", "docs", "nlm", "distill", "knowledge"],
    category=SkillCategory.SYSTEM,
)
def workspace_distill(topic: str, title: str = "") -> str:
    """Create a doc, export to NLM, research, and store distilled knowledge.

    Uses the docs_nlm_distill template to create comprehensive knowledge
    entries from a topic by passing content through Docs and NLM.
    """
    pipeline = _pipeline()
    try:
        run = pipeline.docs_nlm_distill(topic=topic, title=title or None)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_distill failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run full news cycle: fetch→enrich→NLM→Sheet+Doc→Drive→Nexus",
    tags=["workspace", "news", "full-cycle", "analysis"],
    category=SkillCategory.SYSTEM,
)
def workspace_news_full_cycle(category: str = "ai_research") -> str:
    """Execute the complete news analysis cycle.

    Fetches news, enriches with Gemini analysis, researches via NLM,
    creates both a data Sheet and analysis Doc, uploads to Drive,
    and stores everything in Nexus.
    """
    pipeline = _pipeline()
    try:
        run = pipeline.news_full_cycle(category=category)
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_news_full_cycle failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Enrich content using Workspace Gemini transformation",
    tags=["workspace", "gemini", "enrich", "transform"],
    category=SkillCategory.SYSTEM,
)
def workspace_enrich(text: str, prompt: str = "Summarise into key takeaways") -> str:
    """Transform or enrich text content using Workspace Gemini.

    Runs the gemini_enrich stage to transform, summarise, expand, or
    restructure content.  Useful as a standalone enrichment step.
    """
    pipeline = _pipeline()
    try:
        run = pipeline.run(
            "gemini_enrich_only",
            stages=[
                {"stage": "gemini_enrich", "params": {"prompt": prompt}},
                {"stage": "nexus_store", "params": {"category": "enriched", "content_type": "note"}},
            ],
            text=text,
            prompt=prompt,
        )
        return json.dumps(run.to_dict(), default=str)
    except Exception as exc:
        logger.error("workspace_enrich failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── v1.19b Drive v2internal & Sheets Extended Skills ────────────────────────


@skill(
    pack="workspace",
    description="Copy a Google Drive file using v2internal API",
    tags=["workspace", "drive", "copy", "v2internal"],
    category=SkillCategory.SYSTEM,
)
def workspace_copy_file(file_id: str, title: str = "", parent_id: str = "") -> str:
    """Copy a Google Drive file.

    Creates a duplicate of the given file with optional title and
    destination folder overrides.  Uses the Drive v2internal copy
    endpoint which supports team drives and all file types.

    Args:
        file_id: Source file ID to copy.
        title: Title for the copy (defaults to "Copy of ...").
        parent_id: Destination folder ID (optional).

    Returns:
        JSON with the new file ``id``, ``title``, and ``alternateLink``.
    """
    from engine.integrations.google_drive_client import get_drive_client

    try:
        client = get_drive_client()
        result = client.v2_copy_file(
            file_id=file_id,
            title=title or None,
            parent_id=parent_id or None,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_copy_file failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Export a Google Workspace file to text, PDF, CSV, etc.",
    tags=["workspace", "drive", "export", "v2internal"],
    category=SkillCategory.SYSTEM,
)
def workspace_export_file(file_id: str, fmt: str = "text") -> str:
    """Export a Google Workspace file to a different format.

    Supports: ``text``, ``html``, ``pdf``, ``csv``, ``docx``, ``xlsx``.
    Text-based formats return decoded content; binary formats return
    base64-encoded data.

    Args:
        file_id: File ID to export.
        fmt: Target format shortcut or full MIME type.

    Returns:
        JSON with ``content``, ``size``, ``mime_type``, and ``is_text``.
    """
    import base64

    from engine.integrations.google_drive_client import get_drive_client

    try:
        client = get_drive_client()
        content = client.v2_export_file(file_id, fmt)
        is_text = fmt in ("text", "html", "csv", "text/plain", "text/html", "text/csv")
        payload = {
            "file_id": file_id,
            "mime_type": fmt,
            "size": len(content),
            "is_text": is_text,
            "content": content.decode("utf-8", errors="replace") if is_text else base64.b64encode(content).decode(),
        }
        return json.dumps(payload, default=str)
    except Exception as exc:
        logger.error("workspace_export_file failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Set or list permissions on a Google Drive file",
    tags=["workspace", "drive", "permissions", "v2internal"],
    category=SkillCategory.SYSTEM,
)
def workspace_set_permissions(
    file_id: str,
    role: str = "reader",
    perm_type: str = "anyone",
    email: str = "",
) -> str:
    """Set sharing permissions on a Google Drive file.

    Creates a new permission entry.  Use ``perm_type='anyone'`` for link
    sharing or ``perm_type='user'``/``'group'`` with an email address.

    Args:
        file_id: Target file ID.
        role: Permission role — ``reader``, ``writer``, ``commenter``, ``owner``.
        perm_type: Permission type — ``anyone``, ``user``, ``group``, ``domain``.
        email: Email address (required for user/group types).

    Returns:
        JSON with the created permission object.
    """
    from engine.integrations.google_drive_client import get_drive_client

    try:
        client = get_drive_client()
        result = client.v2_insert_permission(
            file_id=file_id,
            role=role,
            perm_type=perm_type,
            email=email or None,
            with_link=True,
            send_notification=False,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_set_permissions failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Get revision history of a Google Sheets spreadsheet",
    tags=["workspace", "sheets", "revisions", "history"],
    category=SkillCategory.SYSTEM,
)
def workspace_sheet_revisions(spreadsheet_id: str, max_results: int = 50) -> str:
    """Retrieve the revision history of a Google Sheets spreadsheet.

    Returns revision metadata including editors, timestamps, and change
    summaries.  Useful for auditing changes and tracking data lineage.

    Args:
        spreadsheet_id: Target spreadsheet ID.
        max_results: Maximum number of revisions to return (default 50).

    Returns:
        JSON with ``revisions`` list and ``count``.
    """
    from engine.integrations.gsheets_client import get_sheets_client

    try:
        client = get_sheets_client()
        revisions = client.get_revision_history(spreadsheet_id, max_results=max_results)
        return json.dumps({"revisions": revisions, "count": len(revisions)}, default=str)
    except Exception as exc:
        logger.error("workspace_sheet_revisions failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Colab Pipeline Skills (v1.19c) ─────────────────────────────────────────


@skill(
    pack="workspace",
    description="Execute Python code in a Colab GPU runtime via the workspace pipeline",
    category="SYSTEM",
    cooldown=5.0,
    cost=3.0,
    tags=["colab", "gpu", "compute", "python"],
)
def workspace_colab_execute(code: str, timeout: int = 120) -> str:
    """Execute Python code in a Google Colab GPU runtime.

    The code runs in a real Colab kernel with GPU access.  Use this for
    computationally expensive tasks, ML inference, data processing, or
    anything requiring GPU acceleration.

    Args:
        code: Python source code to execute.
        timeout: Execution timeout in seconds (default 120).

    Returns:
        JSON with ``output``, ``success``, and ``runtime_id`` keys.
    """
    from engine.integrations.colab_client import get_colab_client

    try:
        client = get_colab_client()
        result = client.run_python(code, timeout=timeout)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_colab_execute failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Ask the Colab Gemini agent a question with optional code context",
    category="SYSTEM",
    cooldown=3.0,
    cost=2.0,
    tags=["colab", "gemini", "ai", "question"],
)
def workspace_colab_ask(prompt: str, context: str = "", timeout: int = 120) -> str:
    """Ask the Colab Gemini agent a question.

    Uses the full AI agent create → update → poll cycle for grounded
    answers.  Provide code or notebook context for more precise responses.

    Args:
        prompt: The question or instruction to send to Gemini.
        context: Optional code/notebook context for grounded answers.
        timeout: Response timeout in seconds (default 120).

    Returns:
        JSON with ``answer`` and ``prompt`` keys.
    """
    from engine.integrations.colab_client import get_colab_client

    try:
        client = get_colab_client()
        answer = client.ask(prompt, context=context, timeout=timeout)
        return json.dumps({"answer": answer, "prompt": prompt})
    except Exception as exc:
        logger.error("workspace_colab_ask failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Build a complete Colab notebook from a task description",
    category="SYSTEM",
    cooldown=10.0,
    cost=5.0,
    tags=["colab", "notebook", "generate", "ai"],
)
def workspace_colab_build(task_description: str, timeout: int = 180) -> str:
    """Build a Colab notebook from a task description.

    Uses the Colab AI agent workflow to generate a complete notebook with
    code cells, markdown, and outputs for the given task.

    Args:
        task_description: What the notebook should accomplish.
        timeout: Max seconds to wait for completion (default 180).

    Returns:
        JSON with ``task_id``, ``status``, and ``notebook_content`` keys.
    """
    from engine.integrations.colab_client import get_colab_client
    import time as _time

    try:
        client = get_colab_client()
        task_id = client.create_task()
        client.update_task(task_id, task_description)

        deadline = _time.time() + timeout
        notebook_content = None
        while _time.time() < deadline:
            result = client.query_task(task_id)
            if result is not None:
                notebook_content = result
                break
            _time.sleep(3)

        if notebook_content is None:
            return json.dumps({"task_id": task_id, "status": "timeout", "notebook_content": ""})
        return json.dumps({"task_id": task_id, "status": "complete", "notebook_content": notebook_content})
    except Exception as exc:
        logger.error("workspace_colab_build failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run a Colab-oriented workspace pipeline template",
    category="SYSTEM",
    cooldown=5.0,
    cost=4.0,
    tags=["colab", "pipeline", "workflow", "orchestration"],
)
def workspace_colab_pipeline(template: str, params: str = "{}") -> str:
    """Run a Colab-oriented workspace pipeline template.

    Available templates: research_and_compute, data_analysis,
    nlm_colab_loop, colab_build_and_store.

    Args:
        template: Pipeline template name.
        params: JSON string of parameters for the pipeline stages.

    Returns:
        JSON with ``results``, ``stage_count``, and ``errors`` keys.
    """
    from engine.nexus.workspace_pipeline import get_workspace_pipeline

    colab_templates = {"research_and_compute", "data_analysis", "nlm_colab_loop", "colab_build_and_store"}
    if template not in colab_templates:
        return json.dumps({"error": f"Unknown template. Choose from: {sorted(colab_templates)}"})

    try:
        parsed_params = json.loads(params) if isinstance(params, str) else params
        pipeline = get_workspace_pipeline()
        results = pipeline.run(template, parsed_params)
        errors = [r for r in results if "error" in r]
        return json.dumps({"results": results, "stage_count": len(results), "errors": errors}, default=str)
    except Exception as exc:
        logger.error("workspace_colab_pipeline failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── AI Studio Skills (v1.21b) ────


@skill(
    pack="workspace",
    description="Generate content using a Google AI Studio model",
    category="SYSTEM",
    cooldown=3.0,
    cost=2.0,
    tags=["aistudio", "generate", "gemini", "ai"],
)
def workspace_aistudio_generate(
    prompt: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    system_instruction: Optional[str] = None,
) -> str:
    """Generate content with a Google AI Studio model.

    Args:
        prompt: The user prompt to send.
        model: Model name override (uses default if omitted).
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Maximum output tokens.
        system_instruction: Optional system instruction prepended to the request.

    Returns:
        JSON string with generated content and metadata.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.generate_content(
            prompt,
            model_name=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_instruction=system_instruction,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_generate failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="List available models in Google AI Studio",
    category="SYSTEM",
    cooldown=5.0,
    cost=1.0,
    tags=["aistudio", "models", "list"],
)
def workspace_aistudio_list_models() -> str:
    """List available models in Google AI Studio.

    Returns:
        JSON string with an array of model metadata objects.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.list_models()
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_list_models failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Embed content into a vector representation via AI Studio",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.0,
    tags=["aistudio", "embed", "embedding", "vector"],
)
def workspace_aistudio_embed(
    model: str,
    content: str,
    task_type: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Embed content into a vector representation via AI Studio.

    Args:
        model: Embedding model name (e.g. ``text-embedding-004``).
        content: Text to embed.
        task_type: Optional task type hint (e.g. ``RETRIEVAL_DOCUMENT``).
        title: Optional title for the content being embedded.

    Returns:
        JSON string with the embedding vector and metadata.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.embed_content(model, content, task_type=task_type, title=title)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_embed failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Count tokens for content using an AI Studio model",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.5,
    tags=["aistudio", "tokens", "count"],
)
def workspace_aistudio_count_tokens(model: str, contents: str) -> str:
    """Count the number of tokens for the given content.

    Args:
        model: Model name used for tokenisation.
        contents: Content to tokenise (JSON string or plain text).

    Returns:
        JSON string with the token count.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        parsed_contents = json.loads(contents) if isinstance(contents, str) else contents
    except (json.JSONDecodeError, TypeError):
        parsed_contents = contents

    try:
        client = get_aistudio_client()
        result = client.count_tokens(model, parsed_contents)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_count_tokens failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Enhance or improve a prompt using AI Studio",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.5,
    tags=["aistudio", "prompt", "enhance"],
)
def workspace_aistudio_enhance_prompt(
    prompt: str,
    model: Optional[str] = None,
) -> str:
    """Enhance or improve a prompt using AI Studio.

    Args:
        prompt: The original prompt to enhance.
        model: Model name override for the enhancement request.

    Returns:
        JSON string with the enhanced prompt and suggestions.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.enhance_prompt(prompt, model=model)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_enhance_prompt failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Generate images using an AI Studio model",
    category="MEDIA",
    cooldown=10.0,
    cost=5.0,
    tags=["aistudio", "image", "generate", "multimodal"],
)
def workspace_aistudio_generate_image(
    prompt: str,
    model: Optional[str] = None,
    n: int = 1,
    size: Optional[str] = None,
) -> str:
    """Generate images from a text prompt via AI Studio.

    Args:
        prompt: Text description of the desired image.
        model: Model name override for image generation.
        n: Number of images to generate (default 1).
        size: Output image size (e.g. ``1024x1024``).

    Returns:
        JSON string with generated image data or URLs.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.generate_image(prompt, model=model, n=n, size=size)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_generate_image failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Generate a video from a text prompt via AI Studio",
    category="MEDIA",
    cooldown=15.0,
    cost=8.0,
    tags=["aistudio", "video", "generate", "multimodal"],
)
def workspace_aistudio_generate_video(
    prompt: str,
    model: Optional[str] = None,
    duration: Optional[int] = None,
    aspect_ratio: Optional[str] = None,
) -> str:
    """Generate a video from a text prompt via AI Studio.

    Args:
        prompt: Text description of the desired video.
        model: Model name override for video generation.
        duration: Desired video duration in seconds.
        aspect_ratio: Output aspect ratio (e.g. ``16:9``).

    Returns:
        JSON string with video generation results.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.generate_video(prompt, model=model, duration=duration, aspect_ratio=aspect_ratio)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_generate_video failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Convert text to speech using AI Studio",
    category="MEDIA",
    cooldown=5.0,
    cost=3.0,
    tags=["aistudio", "tts", "speech", "audio"],
)
def workspace_aistudio_tts(
    text: str,
    voice: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Convert text to speech using AI Studio.

    Args:
        text: The text to synthesise into speech.
        voice: Voice preset name.
        model: Model name override for TTS.

    Returns:
        JSON string with audio data or a reference URL.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    try:
        client = get_aistudio_client()
        result = client.text_to_speech(text, voice=voice, model=model)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_tts failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Create, list, get, update, or delete AI Studio prompts",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["aistudio", "prompt", "manage"],
)
def workspace_aistudio_manage_prompt(
    action: str,
    display_name: Optional[str] = None,
    prompt_data: Optional[str] = None,
    prompt_name: Optional[str] = None,
) -> str:
    """Manage AI Studio saved prompts.

    Args:
        action: One of ``list``, ``create``, ``get``, ``update``, ``delete``.
        display_name: Human-readable prompt name (create/update).
        prompt_data: JSON string with prompt content (create/update).
        prompt_name: Resource name of the prompt (get/update/delete).

    Returns:
        JSON string with the operation result.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    valid_actions = {"list", "create", "get", "update", "delete"}
    if action not in valid_actions:
        return json.dumps({"error": f"Unknown action. Choose from: {sorted(valid_actions)}"})

    try:
        client = get_aistudio_client()
        parsed_data = None
        if prompt_data is not None:
            try:
                parsed_data = json.loads(prompt_data) if isinstance(prompt_data, str) else prompt_data
            except (json.JSONDecodeError, TypeError):
                parsed_data = prompt_data

        if action == "list":
            result = client.list_prompts()
        elif action == "create":
            result = client.create_prompt(display_name=display_name, prompt_data=parsed_data)
        elif action == "get":
            result = client.get_prompt(prompt_name=prompt_name)
        elif action == "update":
            result = client.update_prompt(prompt_name=prompt_name, display_name=display_name, prompt_data=parsed_data)
        elif action == "delete":
            result = client.delete_prompt(prompt_name=prompt_name)

        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_manage_prompt failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Create, list, deploy, undeploy, get, or delete AI Studio applets",
    category="SYSTEM",
    cooldown=5.0,
    cost=3.0,
    tags=["aistudio", "applet", "manage", "deploy"],
)
def workspace_aistudio_manage_applet(
    action: str,
    display_name: Optional[str] = None,
    code: Optional[str] = None,
    applet_name: Optional[str] = None,
    model: Optional[str] = None,
    system_instruction: Optional[str] = None,
) -> str:
    """Manage AI Studio applets (Gems).

    Args:
        action: One of ``list``, ``create``, ``deploy``, ``undeploy``, ``delete``, ``get``.
        display_name: Human-readable applet name (create).
        code: Applet source code (create).
        applet_name: Resource name of the applet (deploy/undeploy/delete/get).
        model: Model name for the applet (create).
        system_instruction: System prompt for the applet (create).

    Returns:
        JSON string with the operation result.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    valid_actions = {"list", "create", "deploy", "undeploy", "delete", "get"}
    if action not in valid_actions:
        return json.dumps({"error": f"Unknown action. Choose from: {sorted(valid_actions)}"})

    try:
        client = get_aistudio_client()

        if action == "list":
            result = client.list_applets()
        elif action == "create":
            result = client.create_applet(
                display_name=display_name,
                code=code,
                model=model,
                system_instruction=system_instruction,
            )
        elif action == "deploy":
            result = client.deploy_applet(applet_name=applet_name)
        elif action == "undeploy":
            result = client.undeploy_applet(applet_name=applet_name)
        elif action == "delete":
            result = client.delete_applet(applet_name=applet_name)
        elif action == "get":
            result = client.get_applet(applet_name=applet_name)

        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_manage_applet failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Create, list, get, or delete AI Studio files",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["aistudio", "file", "manage"],
)
def workspace_aistudio_manage_file(
    action: str,
    display_name: Optional[str] = None,
    file_data: Optional[str] = None,
    mime_type: Optional[str] = None,
    file_name: Optional[str] = None,
) -> str:
    """Manage AI Studio uploaded files.

    Args:
        action: One of ``list``, ``create``, ``get``, ``delete``.
        display_name: Human-readable file name (create).
        file_data: Base64-encoded file data or file path (create).
        mime_type: MIME type of the file (create).
        file_name: Resource name of the file (get/delete).

    Returns:
        JSON string with the operation result.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    valid_actions = {"list", "create", "get", "delete"}
    if action not in valid_actions:
        return json.dumps({"error": f"Unknown action. Choose from: {sorted(valid_actions)}"})

    try:
        client = get_aistudio_client()

        if action == "list":
            result = client.list_files()
        elif action == "create":
            result = client.create_file(display_name=display_name, file_data=file_data, mime_type=mime_type)
        elif action == "get":
            result = client.get_file(file_name=file_name)
        elif action == "delete":
            result = client.delete_file(file_name=file_name)

        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_manage_file failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Check content safety via AI Studio moderation",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.5,
    tags=["aistudio", "safety", "check"],
)
def workspace_aistudio_check_safety(
    content: str,
    safety_settings: Optional[str] = None,
) -> str:
    """Check content against AI Studio safety filters.

    Args:
        content: Text content to evaluate.
        safety_settings: Optional JSON string with custom safety thresholds.

    Returns:
        JSON string with safety ratings per category.
    """
    from engine.integrations.aistudio_client import get_aistudio_client

    parsed_settings = None
    if safety_settings is not None:
        try:
            parsed_settings = json.loads(safety_settings) if isinstance(safety_settings, str) else safety_settings
        except (json.JSONDecodeError, TypeError):
            parsed_settings = safety_settings

    try:
        client = get_aistudio_client()
        result = client.check_safety(content, safety_settings=parsed_settings)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_check_safety failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run an AI Studio-oriented workspace pipeline template",
    category="SYSTEM",
    cooldown=5.0,
    cost=4.0,
    tags=["aistudio", "pipeline", "workflow"],
)
def workspace_aistudio_pipeline(template: str, params: str = "{}") -> str:
    """Run an AI Studio-oriented workspace pipeline template.

    Available templates: aistudio_content_pipeline, aistudio_embed_and_store,
    aistudio_applet_deploy, aistudio_image_pipeline.

    Args:
        template: Pipeline template name.
        params: JSON string of parameters for the pipeline stages.

    Returns:
        JSON with ``results``, ``stage_count``, and ``errors`` keys.
    """
    from engine.nexus.workspace_pipeline import get_workspace_pipeline

    aistudio_templates = {
        "aistudio_content_pipeline",
        "aistudio_embed_and_store",
        "aistudio_applet_deploy",
        "aistudio_image_pipeline",
    }
    if template not in aistudio_templates:
        return json.dumps({"error": f"Unknown template. Choose from: {sorted(aistudio_templates)}"})

    try:
        parsed_params = json.loads(params) if isinstance(params, str) else params
        pipeline = get_workspace_pipeline()
        results = pipeline.run(template, parsed_params)
        errors = [r for r in results if "error" in r]
        return json.dumps({"results": results, "stage_count": len(results), "errors": errors}, default=str)
    except Exception as exc:
        logger.error("workspace_aistudio_pipeline failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ──── Apps Script Skills (v1.21b) ────


@skill(
    pack="workspace",
    description="List recent executions for a Google Apps Script project",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["appscript", "executions", "list"],
)
def workspace_appscript_list_executions(project_id: str, max_results: int = 50) -> str:
    """List recent executions for an Apps Script project.

    Args:
        project_id: The Apps Script project ID.
        max_results: Maximum number of executions to return (default 50).

    Returns:
        JSON string with an array of execution records.
    """
    from engine.integrations.appscript_client import get_appscript_client

    try:
        client = get_appscript_client()
        result = client.list_executions(project_id, max_results=max_results)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_list_executions failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run a function in a Google Apps Script project",
    category="SYSTEM",
    cooldown=5.0,
    cost=3.0,
    tags=["appscript", "run", "execute", "function"],
)
def workspace_appscript_run_function(
    project_id: str,
    function_name: str,
    parameters: Optional[str] = None,
) -> str:
    """Run a function in a Google Apps Script project.

    Args:
        project_id: The Apps Script project ID.
        function_name: Name of the function to execute.
        parameters: Optional JSON string with function arguments.

    Returns:
        JSON string with the function return value and execution metadata.
    """
    from engine.integrations.appscript_client import get_appscript_client

    parsed_params = None
    if parameters is not None:
        try:
            parsed_params = json.loads(parameters) if isinstance(parameters, str) else parameters
        except (json.JSONDecodeError, TypeError):
            parsed_params = parameters

    try:
        client = get_appscript_client()
        result = client.run_function(project_id, function_name, parameters=parsed_params)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_run_function failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Get info and source files for a Google Apps Script project",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["appscript", "project", "info", "files"],
)
def workspace_appscript_get_project(project_id: str, include_files: bool = True) -> str:
    """Get project metadata and optionally its source files.

    Args:
        project_id: The Apps Script project ID.
        include_files: Whether to include source files (default True).

    Returns:
        JSON string with project info and optional file list.
    """
    from engine.integrations.appscript_client import get_appscript_client

    try:
        client = get_appscript_client()
        project_info = client.get_project(project_id)
        if include_files:
            files = client.get_project_files(project_id)
            project_info["files"] = files
        return json.dumps(project_info, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_get_project failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Save code to a file in a Google Apps Script project",
    category="SYSTEM",
    cooldown=3.0,
    cost=2.0,
    tags=["appscript", "save", "code", "edit"],
)
def workspace_appscript_save_code(project_id: str, file_id: str, code: str) -> str:
    """Save code to an Apps Script project file.

    Args:
        project_id: The Apps Script project ID.
        file_id: The file ID within the project.
        code: Source code to save.

    Returns:
        JSON string confirming the save operation.
    """
    from engine.integrations.appscript_client import get_appscript_client

    try:
        client = get_appscript_client()
        result = client.save_code(project_id, file_id, code)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_save_code failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="List triggers for a Google Apps Script project",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["appscript", "triggers", "list"],
)
def workspace_appscript_list_triggers(project_id: str) -> str:
    """List triggers configured for an Apps Script project.

    Args:
        project_id: The Apps Script project ID.

    Returns:
        JSON string with an array of trigger definitions.
    """
    from engine.integrations.appscript_client import get_appscript_client

    try:
        client = get_appscript_client()
        result = client.list_triggers(project_id)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_list_triggers failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="List versions of a Google Apps Script project",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["appscript", "versions", "list"],
)
def workspace_appscript_list_versions(project_id: str, max_results: int = 50) -> str:
    """List published versions of an Apps Script project.

    Args:
        project_id: The Apps Script project ID.
        max_results: Maximum number of versions to return (default 50).

    Returns:
        JSON string with an array of version records.
    """
    from engine.integrations.appscript_client import get_appscript_client

    try:
        client = get_appscript_client()
        result = client.list_versions(project_id, max_results=max_results)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_list_versions failed: %s", exc)
        return json.dumps({"error": str(exc)})


@skill(
    pack="workspace",
    description="Run an Apps Script-oriented workspace pipeline template",
    category="SYSTEM",
    cooldown=5.0,
    cost=4.0,
    tags=["appscript", "pipeline", "workflow"],
)
def workspace_appscript_pipeline(template: str, params: str = "{}") -> str:
    """Run an Apps Script-oriented workspace pipeline template.

    Available templates: appscript_automation, appscript_deploy_and_test.

    Args:
        template: Pipeline template name.
        params: JSON string of parameters for the pipeline stages.

    Returns:
        JSON with ``results``, ``stage_count``, and ``errors`` keys.
    """
    from engine.nexus.workspace_pipeline import get_workspace_pipeline

    appscript_templates = {"appscript_automation", "appscript_deploy_and_test"}
    if template not in appscript_templates:
        return json.dumps({"error": f"Unknown template. Choose from: {sorted(appscript_templates)}"})

    try:
        parsed_params = json.loads(params) if isinstance(params, str) else params
        pipeline = get_workspace_pipeline()
        results = pipeline.run(template, parsed_params)
        errors = [r for r in results if "error" in r]
        return json.dumps({"results": results, "stage_count": len(results), "errors": errors}, default=str)
    except Exception as exc:
        logger.error("workspace_appscript_pipeline failed: %s", exc)
        return json.dumps({"error": str(exc)})
