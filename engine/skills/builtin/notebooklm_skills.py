"""
notebooklm_skills.py — Google NotebookLM integration via CosySim NLM Live Proxy
and Node MCP bridge (hybrid router).

Low-latency source ops route through the batchexecute proxy (:8800).
Chat/Q&A, audio, video, and data extraction route through the Node MCP bridge
(Patchright browser automation) which is always reliable.

Governance gates:
  read  — any agent (sub-1B: allowed)
  write — 1B+ models and copilot
  admin — copilot only (setup_auth)
"""
from __future__ import annotations

from engine.nexus.governance_rules import governed
from engine.skills.skill import skill


def _proxy_url() -> str:
    """Return the NLM Live Proxy base URL."""
    from engine.config import get_config
    return get_config().get("notebooklm.proxy_url", "http://localhost:8800")


def _post(endpoint: str, payload: dict) -> str:
    """POST JSON to the proxy and return the response body as a string."""
    import json
    import urllib.request

    url  = f"{_proxy_url()}{endpoint}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def _get(endpoint: str) -> str:
    """GET from the proxy and return the response body as a string."""
    import urllib.request

    url = f"{_proxy_url()}{endpoint}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


@skill(
    pack="notebooklm",
    description=(
        "Ask a question against a Google NotebookLM notebook and receive an "
        "answer with citations.  Returns JSON with answer, citations, and "
        "notebook_id."
    ),
    tags=["notebooklm", "research", "qa"],
)
@governed(operation="read")
def notebooklm_ask(question: str, notebook_id: str = "") -> str:
    """Send a question to a NotebookLM notebook and return the answer.

    Requires the NLM Live Proxy to be running at :8800.

    Args:
        question:    Natural-language question to ask.
        notebook_id: Target notebook ID (empty = use default notebook).

    Returns:
        JSON string with ``answer``, ``citations``, and ``notebook_id``.
    """
    try:
        import json
        payload: dict = {"question": question}
        if notebook_id:
            payload["notebook_id"] = notebook_id
        body = _post("/ask", payload)
        # Ensure the response is valid JSON before returning
        json.loads(body)
        return body
    except Exception as exc:
        import json
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Add a source (URL, text, PDF, or YouTube link) to a NotebookLM "
        "notebook.  Returns JSON with status and source_id."
    ),
    tags=["notebooklm", "sources", "ingest"],
)
@governed(operation="write")
def notebooklm_add_source(
    notebook_id: str,
    source_type: str = "url",
    source_value: str = "",
) -> str:
    """Add a source to a NotebookLM notebook.

    Requires the NLM Live Proxy to be running at :8800.

    Args:
        notebook_id:  Target notebook ID.
        source_type:  One of ``url``, ``text``, ``pdf``, ``youtube``.
        source_value: The URL, raw text, file path, or YouTube link to add.

    Returns:
        JSON string with ``status`` and ``source_id``.
    """
    try:
        import json
        body = _post("/sources", {
            "notebook_id": notebook_id,
            "source_type": source_type,
            "source_value": source_value,
        })
        json.loads(body)
        return body
    except Exception as exc:
        import json
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Generate an audio overview (podcast-style) of a NotebookLM notebook. "
        "This is an async operation; returns JSON with status and job_id."
    ),
    tags=["notebooklm", "audio", "podcast"],
)
@governed(operation="write")
def notebooklm_generate_audio(
    notebook_id: str,
    customization: str = "",
) -> str:
    """Request an audio overview for a notebook.

    Requires the NLM Live Proxy to be running at :8800.
    The operation is asynchronous — poll the returned ``job_id`` for progress.

    Args:
        notebook_id:   Target notebook ID.
        customization: Optional prompt to customize the audio style or focus.

    Returns:
        JSON string with ``status`` and ``job_id``.
    """
    try:
        import json
        payload: dict = {"notebook_id": notebook_id}
        if customization:
            payload["customization"] = customization
        body = _post("/audio", payload)
        json.loads(body)
        return body
    except Exception as exc:
        import json
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "List all available NotebookLM notebooks.  Returns a JSON array of "
        "objects with id, title, and source_count."
    ),
    tags=["notebooklm", "list", "notebooks"],
)
@governed(operation="read")
def notebooklm_list_notebooks() -> str:
    """List every notebook visible to the authenticated user.

    Requires the NLM Live Proxy to be running at :8800.

    Returns:
        JSON array of ``{id, title, source_count}`` objects.
    """
    try:
        import json
        body = _get("/notebooks")
        json.loads(body)
        return body
    except Exception as exc:
        import json
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Search across all NotebookLM notebooks by keyword.  Returns a JSON "
        "array of matching results."
    ),
    tags=["notebooklm", "search", "research"],
)
@governed(operation="read")
def notebooklm_search(query: str) -> str:
    """Search across notebooks for content matching a keyword query.

    Requires the NLM Live Proxy to be running at :8800.

    Args:
        query: Search terms / keywords.

    Returns:
        JSON array of matching results with notebook and source metadata.
    """
    try:
        import json
        import urllib.parse
        encoded = urllib.parse.quote(query, safe="")
        body = _get(f"/search?q={encoded}")
        json.loads(body)
        return body
    except Exception as exc:
        import json
        return json.dumps({"error": str(exc)})


# ──── Node MCP Bridge Skills (browser-based, auth-stable) ─────────────────────

def _hybrid():
    """Lazy-load the NLM hybrid router singleton."""
    from engine.mcp.nlm_hybrid import get_nlm_hybrid
    return get_nlm_hybrid()


@skill(
    pack="notebooklm",
    description=(
        "Ask a question against a NotebookLM notebook using the Node MCP bridge "
        "(browser-based). More reliable than the proxy — handles auth automatically. "
        "Returns JSON with answer, sources, and session_id. Pass session_id from a "
        "prior response to continue a multi-turn conversation."
    ),
    tags=["notebooklm", "research", "qa", "node-bridge"],
)
@governed(operation="read")
def notebooklm_ask_node(
    notebook_id: str,
    question: str,
    session_id: str = "",
    reset_history: bool = False,
) -> str:
    """Ask a question via the Node MCP bridge (Patchright browser automation).

    This is the preferred method for Q&A — the batchexecute RPC is unreliable
    but the Node bridge types into the real NotebookLM UI and always works.

    Args:
        notebook_id:   NLM notebook UUID.
        question:      Question to ask.
        session_id:    Optional prior session ID for conversation continuity.
        reset_history: If True, start a fresh session ignoring session_id.

    Returns:
        JSON string with ``answer``, ``sources``, ``session_id``.
    """
    import json
    try:
        result = _hybrid().ask(
            notebook_id, question,
            session_id=session_id or None,
            reset_history=reset_history,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Ask multiple questions against a NotebookLM notebook in one batch. "
        "Uses session continuity so later questions benefit from earlier answers. "
        "Returns JSON array of {answer, sources, session_id} objects."
    ),
    tags=["notebooklm", "research", "batch", "node-bridge"],
    cooldown=5.0,
)
@governed(operation="read")
def notebooklm_batch_ask(notebook_id: str, questions: str) -> str:
    """Batch ask multiple questions via Node bridge with session continuity.

    Args:
        notebook_id: NLM notebook UUID.
        questions:   JSON array of question strings, e.g. '["Q1?", "Q2?"]'.

    Returns:
        JSON array of result dicts, one per question.
    """
    import json
    try:
        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})
        results = _hybrid().ask_batch(notebook_id, q_list)
        return json.dumps(results)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Generate an audio overview (podcast-style) of a NotebookLM notebook "
        "via the Node MCP bridge. Returns JSON with status and generation progress."
    ),
    tags=["notebooklm", "audio", "podcast", "node-bridge"],
    cooldown=10.0,
)
@governed(operation="write")
def notebooklm_generate_audio_node(notebook_id: str, style: str = "standard") -> str:
    """Trigger audio overview generation via Node bridge.

    Args:
        notebook_id: NLM notebook UUID or library ID.
        style:       Audio style (standard, deep_dive). NLM controls the actual style.

    Returns:
        JSON string with ``status``, ``progress``.
    """
    import json
    try:
        result = _hybrid().generate_audio(notebook_id, style)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Generate a video overview of a NotebookLM notebook. "
        "Supports 10 visual styles: cinematic, documentary, minimalist, etc. "
        "Returns JSON with video_id and status."
    ),
    tags=["notebooklm", "video", "overview", "node-bridge"],
    cooldown=10.0,
)
@governed(operation="write")
def notebooklm_generate_video(notebook_id: str, style: str = "cinematic") -> str:
    """Trigger video overview generation via Node bridge.

    Args:
        notebook_id: NLM notebook UUID or library ID.
        style:       Video style ("cinematic", "documentary", "minimalist",
                     "energetic", "calm", "data_viz", etc.).

    Returns:
        JSON string with ``video_id``, ``status``, ``style``.
    """
    import json
    try:
        result = _hybrid().generate_video(notebook_id, style)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Extract structured data tables from a NotebookLM notebook's sources. "
        "Returns JSON with a tables array, each table having headers and rows."
    ),
    tags=["notebooklm", "data", "tables", "extraction", "node-bridge"],
)
@governed(operation="read")
def notebooklm_extract_tables(notebook_id: str, query: str = "") -> str:
    """Extract data tables from notebook sources via Node bridge.

    Args:
        notebook_id: NLM notebook UUID or library ID.
        query:       Optional filter to focus on specific data topics.

    Returns:
        JSON string with ``tables`` list.
    """
    import json
    try:
        result = _hybrid().extract_tables(notebook_id, query)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Get combined health status of both NLM backends: "
        "Node MCP bridge (Patchright) and batchexecute proxy. "
        "Returns JSON with auth state, available tools, and proxy reachability."
    ),
    tags=["notebooklm", "health", "status", "node-bridge"],
)
@governed(operation="read")
def notebooklm_hybrid_health() -> str:
    """Return combined health status of Node bridge + batchexecute proxy.

    Returns:
        JSON string with ``node_bridge``, ``batchexecute_proxy``,
        ``chrome_profile_exists``, ``node_tools_available``.
    """
    import json
    try:
        result = _hybrid().health()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="notebooklm",
    description=(
        "Run first-time Google auth setup for the Node MCP bridge. "
        "Opens Chrome visibly — user must log in to Google once. "
        "After login, all subsequent calls work in headless mode automatically."
    ),
    tags=["notebooklm", "auth", "setup", "node-bridge"],
)
@governed(operation="admin")
def notebooklm_setup_auth() -> str:
    """Open Chrome for interactive Google login (first-time auth setup).

    Run this once after initial installation. The Chrome profile is saved
    permanently so you never need to do this again.

    Returns:
        JSON string with ``status`` and auth result.
    """
    import json
    try:
        result = _hybrid().setup_auth()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
