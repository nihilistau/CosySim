import json
from typing import Optional


def notebooklm_node_ask_impl(
    notebook_id: str, question: str, session_id: str = ""
) -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        result = get_nlm_hybrid().ask(
            notebook_id,
            question,
            session_id=session_id or None,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_batch_ask_impl(notebook_id: str, questions: str) -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})
        results = get_nlm_hybrid().ask_batch(notebook_id, q_list)
        return json.dumps(results)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_add_source_impl(
    notebook_id: str,
    source_type: str,
    source_value: str,
    title: str = "",
) -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        hybrid = get_nlm_hybrid()
        if source_type == "url" or source_type == "youtube":
            result = hybrid.add_url_source(notebook_id, source_value)
        else:
            result = hybrid.add_text_source(notebook_id, source_value, title=title)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_create_notebook_impl(
    name: str,
    sources: str = "[]",
    description: str = "",
    topics: str = "",
) -> str:
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge

        src_list = json.loads(sources) if isinstance(sources, str) else sources
        result = get_nlm_node_bridge().create_notebook(
            name=name,
            sources=src_list,
            description=description,
            topics=[t.strip() for t in topics.split(",") if t.strip()],
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_list_notebooks_impl() -> str:
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge

        result = get_nlm_node_bridge().list_notebooks()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_generate_audio_impl(notebook_id: str) -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        result = get_nlm_hybrid().generate_audio(notebook_id)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_generate_video_impl(
    notebook_id: str, style: str = "cinematic"
) -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        result = get_nlm_hybrid().generate_video(notebook_id, style)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_extract_tables_impl(notebook_id: str, query: str = "") -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        result = get_nlm_hybrid().extract_tables(notebook_id, query)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_chat_history_impl(notebook_id: str, limit: int = 20) -> str:
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge

        result = get_nlm_node_bridge().get_chat_history(notebook_id, limit=limit)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_health_impl() -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        result = get_nlm_hybrid().health()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_setup_auth_impl() -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid

        result = get_nlm_hybrid().setup_auth()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def notebooklm_node_sync_nexus_impl(notebook_id: str, questions: str) -> str:
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        from engine.nexus.client import get_nexus_client

        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})

        results = get_nlm_hybrid().ask_batch(notebook_id, q_list)
        client = get_nexus_client()

        stored = 0
        errors = 0
        pairs = []
        for q, r in zip(q_list, results):
            answer = r.get("answer", "") if isinstance(r, dict) else str(r)
            if answer and "error" not in r:
                try:
                    client.add_qa(q, answer, category="nlm-distilled")
                    stored += 1
                    pairs.append({"question": q, "answer": answer[:200]})
                except Exception:
                    errors += 1
            else:
                errors += 1

        return json.dumps({"stored": stored, "errors": errors, "pairs": pairs})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def master_notebook_build_impl(
    sources_only: bool = False,
    generators_only: bool = False,
    notebook_id: str = "",
    dry_run: bool = False,
) -> str:
    from engine.nexus.master_notebook_builder import MasterNotebookBuilder

    builder = MasterNotebookBuilder(dry_run=dry_run)
    result = builder.build(
        notebook_id=notebook_id or None,
        sources_only=sources_only,
        generators_only=generators_only,
    )
    return json.dumps(result, indent=2, default=str)


def master_notebook_status_impl() -> str:
    from engine.nexus.master_notebook_builder import _load_state, DISTILLATION_QUESTIONS

    state = _load_state()
    nb_id = state.get("notebook_id", "not created yet")
    sources_done = len(state.get("sources_uploaded", []))
    gens_done = state.get("generators_done", [])
    qa_done = state.get("qa_done_index", 0)
    qa_total = len(DISTILLATION_QUESTIONS)
    lines = [
        "=== Master Notebook Status ===",
        f"Notebook ID   : {nb_id}",
        f"Last build    : {state.get('last_build', 'never')}",
        f"Sources done  : {sources_done}",
        f"Generators    : {', '.join(gens_done) or 'none yet'}",
        f"Q&A distilled : {qa_done}/{qa_total}",
    ]
    return "\n".join(lines)


def master_notebook_reset_impl() -> str:
    from engine.nexus.master_notebook_builder import _STATE_FILE

    try:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
        return "Master notebook state reset. Next build will create a fresh notebook."
    except Exception as exc:
        return f"Reset failed: {exc}"


def master_notebook_list_sources_impl() -> str:
    from engine.nexus.master_notebook_builder import SDK_URLS

    lines = ["=== Master Notebook Source Manifest ===\n", "TEXT BUNDLES (code + docs):"]
    text_bundles = [
        "CosySim Hardware & System Specification",
        "Engine Framework: Config, MCP, Scenes, Agents",
        "Engine Nexus: Knowledge Management System",
        "Engine LMStudio: LLM Inference Integration",
        "Engine MCP Servers: DevTools, NLM Hybrid, Bridges",
        "Engine Skills: @skill Decorator + All Builtin Packs",
        "Engine Services: TTS, Integrations, Assistant",
        "Scene Implementations: Top 8 Scenes",
        "Config Files, Governance Rules & Copilot Instructions",
        "Documentation: Architecture, Guides, Protocols",
        "Frontend JavaScript: All Scene + Shared JS",
        "Test Suite: Patterns and Conventions",
        "Dependencies: requirements.txt, package.json, pyproject.toml",
    ]
    for i, b in enumerate(text_bundles, 1):
        lines.append(f"  {i:2}. {b}")
    lines.append(f"\nSDK / API DOCUMENTATION URLs ({len(SDK_URLS)} sources):")
    for i, sdk in enumerate(SDK_URLS, 1):
        lines.append(f"  {i:2}. {sdk['label']} → {sdk['url']}")
    lines.append(f"\nTotal sources: {len(text_bundles) + len(SDK_URLS)}")
    return "\n".join(lines)
