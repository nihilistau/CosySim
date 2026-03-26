"""NLM Forge Skills — MCP skills for NLM-powered knowledge operations.

Provides agent-callable skills that wrap the KnowledgeForge and NLMEngine
for Q&A distillation, plan decomposition, code analysis, dialog polish,
training export, and the NLM-first router.

Version: v1.55.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.55.0 [2026-03-26] — Added nlm_decompose_task skill for plan decomposition
    v1.50.0 [2026-03-20] — Initial NLM forge skills (ask, batch, distill, decompose, etc.)

Usage by agents:
    nlm_ask("How does the interceptor pipeline work?")
    nlm_batch_ask(questions=["Q1?", "Q2?"], notebook_id="nb-123")
    nlm_distill(notebook_id="nb-123", topic="MCP state")
"""
from __future__ import annotations

import json

from engine.skills.skill import skill


def _get_engine():
    """Lazy-load NLMEngine."""
    from engine.nexus.nlm_engine import get_nlm_engine
    return get_nlm_engine()


def _get_forge():
    """Lazy-load KnowledgeForge."""
    from engine.nexus.knowledge_forge import get_knowledge_forge
    return get_knowledge_forge()


def _get_router():
    """Lazy-load NLMRouter."""
    from engine.nexus.nlm_router import get_nlm_router
    return get_nlm_router()


@skill(
    pack="nlm_forge",
    description=(
        "Ask a question using the NLM-first router. Checks Nexus cache, "
        "then FTS search, then NotebookLM (free Gemini), then LLM as last "
        "resort. Answer auto-stored in Nexus for compound reuse."
    ),
    category="SYSTEM",
    tags=["nlm", "qa", "router", "nexus"],
)
def nlm_ask(question: str, notebook_id: str = "") -> str:
    """Route a question through the 4-tier NLM-first pipeline.

    Args:
        question: The question to answer.
        notebook_id: Optional NLM notebook for context.

    Returns:
        JSON with answer, source_tier, confidence, and savings info.
    """
    try:
        router = _get_router()
        result = router.route(question, notebook_id=notebook_id)
        return json.dumps(result.to_dict(), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Ask multiple questions in batch via NLM-first router. Each question "
        "is routed through cache → FTS → NLM → LLM. All answers stored in "
        "Nexus automatically. Returns array of results."
    ),
    category="SYSTEM",
    tags=["nlm", "batch", "qa", "router"],
)
def nlm_batch_ask(questions: str, notebook_id: str = "") -> str:
    """Batch-ask multiple questions through the NLM-first router.

    Args:
        questions: JSON array of question strings.
        notebook_id: Optional NLM notebook for context.

    Returns:
        JSON array of route results.
    """
    try:
        qs = json.loads(questions) if isinstance(questions, str) else questions
        router = _get_router()
        results = []
        for q in qs:
            result = router.route(q, notebook_id=notebook_id)
            results.append(result.to_dict())
        return json.dumps(results, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Create a new NotebookLM notebook optionally with sources. "
        "Returns notebook_id for use with other NLM skills."
    ),
    category="SYSTEM",
    tags=["nlm", "notebook", "create"],
)
def nlm_create_notebook(name: str, sources: str = "", category: str = "general") -> str:
    """Create a NotebookLM notebook via the centralised factory.

    Args:
        name: Notebook name.
        sources: Optional JSON array of source URLs.
        category: Notebook category (news, bootstrap, training, research, etc.).

    Returns:
        JSON with notebook_id and metadata.
    """
    try:
        from engine.nexus.nlm_notebook_factory import get_notebook_factory

        factory = get_notebook_factory()
        notebook_id = factory.get_or_create(name, category=category or "general")
        if not notebook_id:
            return json.dumps({"error": "Factory failed to create notebook"})
        return json.dumps({
            "notebook_id": notebook_id,
            "name": name,
            "category": category,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Add source code files to an NLM notebook for code analysis. "
        "Each file becomes a text source in the notebook."
    ),
    category="SYSTEM",
    tags=["nlm", "codebase", "sources"],
)
def nlm_add_codebase(notebook_id: str, paths: str) -> str:
    """Add source files to an existing notebook.

    Args:
        notebook_id: Target notebook UUID.
        paths: JSON array of file paths to add.

    Returns:
        JSON with notebook_id and source add results.
    """
    try:
        engine = _get_engine()
        file_paths = json.loads(paths) if isinstance(paths, str) else paths
        result = engine.create_from_files(file_paths, f"Codebase: {notebook_id[:8]}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Generate a structured document from a notebook using NotebookLM. "
        "Types: study_guide, faq, briefing, deep_dive, timeline."
    ),
    category="SYSTEM",
    tags=["nlm", "document", "generate"],
)
def nlm_generate_doc(notebook_id: str, doc_type: str = "study_guide", instructions: str = "") -> str:
    """Generate a document from notebook content.

    Args:
        notebook_id: Source notebook UUID.
        doc_type: Document type — study_guide, faq, briefing, deep_dive.
        instructions: Custom instructions to guide generation.

    Returns:
        JSON with generated content and metadata.
    """
    try:
        forge = _get_forge()
        result = forge.generate_doc(notebook_id, doc_type, instructions)
        return json.dumps({
            "success": result.success,
            "documents": result.documents,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Distill Q&A pairs from a notebook via batch asking. Generates "
        "relevant questions about the topic and batch-asks NLM. All answers "
        "stored in Nexus Q&A cache for compound reuse."
    ),
    category="SYSTEM",
    tags=["nlm", "distill", "qa", "training"],
)
def nlm_distill(notebook_id: str, topic: str = "", count: int = 20) -> str:
    """Distill Q&A pairs from a notebook.

    Args:
        notebook_id: Source notebook UUID.
        topic: Topic to generate questions about.
        count: Number of Q&A pairs to generate.

    Returns:
        JSON with Q&A pairs, nexus_ids, and metadata.
    """
    try:
        forge = _get_forge()
        topics = [topic] if topic else None
        result = forge.distill(notebook_id, topics=topics, count=count)
        return json.dumps({
            "success": result.success,
            "qa_count": len(result.qa_pairs),
            "qa_pairs": [p.to_dict() for p in result.qa_pairs],
            "nexus_ids": result.nexus_ids,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Decompose a complex plan into specific steps executable by a small "
        "language model. Each step includes file, changes, imports needed."
    ),
    category="SYSTEM",
    tags=["nlm", "plan", "decompose"],
)
def nlm_decompose(plan: str, notebook_id: str = "", model_size: str = "9b") -> str:
    """Decompose a plan into small-model executable steps.

    Args:
        plan: The high-level plan text to decompose.
        notebook_id: Notebook with codebase context.
        model_size: Target model size (affects granularity).

    Returns:
        JSON with numbered steps and metadata.
    """
    try:
        forge = _get_forge()
        result = forge.decompose(plan, notebook_id=notebook_id, model_size=model_size)
        return json.dumps({
            "success": result.success,
            "steps": result.steps,
            "step_count": len(result.steps),
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Analyze source code by creating an NLM notebook with the files and "
        "asking targeted questions. Returns insights about design patterns, "
        "dependencies, error handling, and more."
    ),
    category="SYSTEM",
    tags=["nlm", "analyze", "code"],
)
def nlm_analyze(files: str, questions: str = "") -> str:
    """Analyze source files using NLM.

    Args:
        files: JSON array of file paths to analyze.
        questions: Optional JSON array of specific questions.

    Returns:
        JSON with Q&A insights about the code.
    """
    try:
        forge = _get_forge()
        file_paths = json.loads(files) if isinstance(files, str) else files
        q_list = json.loads(questions) if questions else None
        result = forge.analyze(file_paths, questions=q_list)
        return json.dumps({
            "success": result.success,
            "notebook_id": result.notebook_id,
            "insights": [p.to_dict() for p in result.qa_pairs],
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Solve a problem using NLM with optional code context. Creates a "
        "notebook from context files if needed, asks the question, stores "
        "the solution in Nexus."
    ),
    category="SYSTEM",
    tags=["nlm", "solve", "problem"],
)
def nlm_solve(question: str, context: str = "", notebook_id: str = "") -> str:
    """Solve a problem via NLM with optional code context.

    Args:
        question: The problem or question to solve.
        context: Optional JSON array of context file paths.
        notebook_id: Existing notebook with context.

    Returns:
        JSON with the solution Q&A pair and metadata.
    """
    try:
        forge = _get_forge()
        ctx_files = json.loads(context) if context else None
        result = forge.solve(question, context_files=ctx_files, notebook_id=notebook_id)
        return json.dumps({
            "success": result.success,
            "solution": result.qa_pairs[0].to_dict() if result.qa_pairs else None,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Build a complete topic knowledge base: create notebook, add sources, "
        "generate questions, batch-ask NLM, store all Q&A in Nexus. "
        "End-to-end knowledge building pipeline."
    ),
    category="SYSTEM",
    tags=["nlm", "topic", "knowledge", "pipeline"],
)
def nlm_build_topic(topic: str, sources: str = "", question_count: int = 30) -> str:
    """Build a complete knowledge base for a topic.

    Args:
        topic: Topic name.
        sources: Optional JSON array of source URLs or file paths.
        question_count: Number of Q&A pairs to generate.

    Returns:
        JSON with notebook_id, Q&A pairs, and metadata.
    """
    try:
        forge = _get_forge()
        source_list = json.loads(sources) if sources else None
        result = forge.build_topic(topic, sources=source_list, question_count=question_count)
        return json.dumps({
            "success": result.success,
            "notebook_id": result.notebook_id,
            "qa_count": len(result.qa_pairs),
            "nexus_ids": result.nexus_ids,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _get_hybrid():
    """Lazy-load NLMHybrid router."""
    from engine.mcp.nlm_hybrid import get_nlm_hybrid
    return get_nlm_hybrid()


@skill(
    pack="nlm_forge",
    description=(
        "Generate a NotebookLM audio overview for a notebook. "
        "Returns a link or status of the generated audio (style: standard or deep_dive)."
    ),
    category="SYSTEM",
    tags=["nlm", "audio", "overview", "generate"],
)
def nlm_audio(notebook_id: str, style: str = "standard") -> str:
    """Generate an audio overview for a notebook via the NLM hybrid router.

    Args:
        notebook_id: NLM notebook ID.
        style: Audio style — "standard" or "deep_dive".

    Returns:
        JSON with audio_url or status.
    """
    try:
        result = _get_hybrid().generate_audio(notebook_id, style=style)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Generate a NotebookLM video overview for a notebook. "
        "Styles: cinematic, educational, documentary, tutorial, short_reel, interview, "
        "news_report, product_demo, animated_explainer, corporate."
    ),
    category="SYSTEM",
    tags=["nlm", "video", "overview", "generate"],
)
def nlm_video(notebook_id: str, style: str = "cinematic") -> str:
    """Generate a video overview for a notebook via the NLM hybrid router.

    Args:
        notebook_id: NLM notebook ID.
        style: Video generation style.

    Returns:
        JSON with video_url or status.
    """
    try:
        result = _get_hybrid().generate_video(notebook_id, style=style)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Extract structured data tables from a notebook. "
        "Useful for getting structured facts, comparisons, or metrics stored in sources."
    ),
    category="SYSTEM",
    tags=["nlm", "data", "tables", "extract"],
)
def nlm_data_tables(notebook_id: str, query: str = "") -> str:
    """Extract data tables from notebook sources via the NLM hybrid router.

    Args:
        notebook_id: NLM notebook ID.
        query: Optional filtering query for specific table topics.

    Returns:
        JSON array of extracted tables.
    """
    try:
        result = _get_hybrid().extract_tables(notebook_id, query=query)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="nlm_forge",
    description=(
        "Retrieve the full chat history for a notebook. "
        "Returns all previous questions and answers for review or re-distillation."
    ),
    category="SYSTEM",
    tags=["nlm", "chat", "history", "retrieve"],
)
def nlm_chat_history(notebook_id: str) -> str:
    """Get the chat history for a NLM notebook.

    Args:
        notebook_id: NLM notebook ID.

    Returns:
        JSON array of {question, answer} entries.
    """
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        result = get_nlm_node_bridge().get_chat_history(notebook_id)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Plan Decomposition ────────────────────────────────────────────────

# v1.55.0 [2026-03-26] — Plan decomposition skill for agent task planning
@skill(
    pack="nlm_forge",
    description="Break a complex task into numbered steps a local agent can follow",
    category="SYSTEM",
    cooldown=10.0,
    cost=2.0,
    tags=["planning", "decomposition", "nlm"],
)
def nlm_decompose_task(task_description: str, model_size: str = "small") -> str:
    """Decompose a complex task into simple executable steps via NLM.

    Tries KnowledgeForge.decompose() first for structured output, then
    falls back to a simple numbered-list prompt via NLM ask.

    Args:
        task_description: The complex task to break down into steps.
        model_size: Target model size hint — "small" (sub-3B), "medium" (3-9B),
            or "large" (10B+). Smaller targets get more granular steps.

    Returns:
        JSON with numbered steps, step_count, and source method.

    CONNECTS: KnowledgeForge, NLMRouter, NexusClient
    CALLED BY: Agent planning pipeline, auto-skill system
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    # ── Attempt 1: KnowledgeForge.decompose() ──
    try:
        forge = _get_forge()
        result = forge.decompose(
            task_description, notebook_id="", model_size=model_size,
        )
        if result.success and result.steps:
            _logger.info(
                "[nlm_decompose_task] Forge decomposition succeeded (operation=decompose, steps=%d)",
                len(result.steps),
            )
            return json.dumps({
                "steps": result.steps,
                "step_count": len(result.steps),
                "source": "knowledge_forge",
                "model_size": model_size,
                "duration_seconds": result.duration_seconds,
            }, ensure_ascii=False)
    except Exception as exc:
        _logger.debug(
            "[nlm_decompose_task] Forge decompose unavailable (operation=decompose): %s", exc,
        )

    # ── Attempt 2: NLM ask with a decomposition prompt ──
    try:
        # Build granularity guidance based on model_size
        granularity = {
            "small": "very granular (one simple action per step, no multi-step logic)",
            "medium": "moderately detailed (2-3 actions per step acceptable)",
            "large": "high-level (each step can involve multiple sub-actions)",
        }.get(model_size, "moderately detailed")

        prompt = (
            f"Break the following task into numbered steps that a {model_size} "
            f"language model can follow. Steps should be {granularity}. "
            f"Return ONLY a numbered list, no preamble.\n\n"
            f"Task: {task_description}"
        )

        router = _get_router()
        result = router.route(prompt)
        answer = result.answer if hasattr(result, "answer") else str(result)

        # Parse numbered steps from the answer
        import re
        steps = []
        for line in answer.strip().splitlines():
            line = line.strip()
            # Match lines starting with a number followed by . or )
            match = re.match(r"^\d+[.)]\s*(.+)", line)
            if match:
                steps.append(match.group(1).strip())

        if not steps:
            # Fallback: treat each non-empty line as a step
            steps = [l.strip() for l in answer.strip().splitlines() if l.strip()]

        _logger.info(
            "[nlm_decompose_task] NLM decomposition succeeded (operation=decompose, steps=%d)",
            len(steps),
        )
        return json.dumps({
            "steps": steps,
            "step_count": len(steps),
            "source": "nlm_router",
            "model_size": model_size,
            "raw_answer": answer,
        }, ensure_ascii=False)

    except Exception as exc:
        _logger.warning(
            "[nlm_decompose_task] All decomposition methods failed (operation=decompose): %s", exc,
        )
        return json.dumps({"error": str(exc), "steps": [], "step_count": 0})
