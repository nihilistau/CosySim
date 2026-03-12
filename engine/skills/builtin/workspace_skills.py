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


@skill(
    pack="workspace",
    description="Generate text content using Workspace Gemini (Sheets/Docs context)",
    tags=["workspace", "gemini", "generate", "text"],
    category=SkillCategory.SYSTEM,
)
def workspace_generate(prompt: str, context: str = "sheets", store: bool = True) -> str:
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
