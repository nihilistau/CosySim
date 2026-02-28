"""
notebooklm_skills.py — Google NotebookLM integration via CosySim NLM Live Proxy.

These skills communicate with the NLM Live Proxy (``engine/mcp/nlm_live_proxy.py``)
at ``http://localhost:8800``.  The proxy makes direct batchexecute calls to
NotebookLM using HAR-extracted Google auth cookies — no Node.js or browser
automation required.

The proxy URL defaults to ``http://localhost:8800`` and can be overridden via
the ``notebooklm.proxy_url`` configuration key.
"""
from __future__ import annotations

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
