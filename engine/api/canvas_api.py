"""Canvas API — FastAPI service at port 5595.

Provides all Python-side endpoints for the Nexus Canvas control plane:
  - HAR file management and account pool
  - Training data capture and stats
  - Nexus knowledge (search / ask / add / rules / QA)
  - NotebookLM notebook management
  - Compute (Colab JIT sessions, tunnels)
  - GitHub Copilot API proxy
  - General RPC proxy

The TypeScript Express server (port 5590) proxies these routes here instead
of spawning Python subprocesses via callPython(), giving proper long-lived
import caching and ~10× lower latency.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ──── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CosySim Canvas API",
    version="1.0.0",
    description="Python backend for the Nexus Canvas control plane",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──── Health ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "canvas-api", "port": 5595}


# ──── Accounts / HAR pool ─────────────────────────────────────────────────────

@app.get("/api/accounts")
def list_accounts() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import list_accounts_from_dirs
    return list_accounts_from_dirs()


@app.get("/api/accounts/list")
def list_accounts_with_tiers() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import list_accounts_with_tiers
    return list_accounts_with_tiers()


class ImportHarBody(BaseModel):
    filepath: str = ""
    account_name: str = ""
    services: List[str] = []


@app.post("/api/accounts/import-har")
def import_har(body: ImportHarBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import import_har_to_pool
    return import_har_to_pool(
        filepath=body.filepath,
        account_name=body.account_name,
        services=body.services,
    )


class ImportDirBody(BaseModel):
    directory: str = ""
    account_name: str = ""
    services: List[str] = []


@app.post("/api/accounts/import-directory")
def import_directory(body: ImportDirBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import import_har_to_pool
    directory = Path(body.directory)
    if not directory.exists():
        raise HTTPException(status_code=400, detail=f"Directory not found: {directory}")
    har_files = list(directory.glob("*.har"))
    results = []
    for har_path in har_files:
        try:
            r = import_har_to_pool(
                filepath=str(har_path),
                account_name=body.account_name or directory.name,
                services=body.services,
            )
            results.append({"file": har_path.name, **r})
        except Exception as exc:
            results.append({"file": har_path.name, "error": str(exc)})
    return {"imported": len(results), "results": results}


class ConfigureAccountBody(BaseModel):
    account_name: str = ""
    tier: str = "free"
    limits: Dict[str, Any] = {}


@app.post("/api/accounts/configure")
def configure_account(body: ConfigureAccountBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import configure_account as _configure
    return _configure(
        account_name=body.account_name,
        tier=body.tier,
        limits=body.limits,
    )


@app.delete("/api/accounts/{name}")
def delete_account(name: str) -> Dict[str, Any]:
    try:
        pool = __import__("engine.integrations.google_account_pool", fromlist=["get_account_pool"]).get_account_pool()
        if hasattr(pool, "remove_account"):
            pool.remove_account(name)
            return {"ok": True, "deleted": name}
        return {"ok": False, "error": "remove_account not supported"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ──── HAR files ───────────────────────────────────────────────────────────────

@app.get("/api/har/list")
def har_list() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import list_har_files_dict
    return list_har_files_dict()


class ParseHarBody(BaseModel):
    filepath: str = ""
    filename: str = ""


@app.post("/api/har/parse")
def har_parse(body: ParseHarBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import parse_har_file
    return parse_har_file(filepath=body.filepath or body.filename)


class ImportAccountBody(BaseModel):
    path: str = ""
    filepath: str = ""
    account_name: str = ""
    services: List[str] = []


@app.post("/api/har/import")
@app.post("/api/har/import-account")
def har_import_account(body: ImportAccountBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import import_har_to_pool
    fp = body.path or body.filepath
    return import_har_to_pool(
        filepath=fp,
        account_name=body.account_name,
        services=body.services,
    )


@app.get("/api/har/{filename}/entries")
def har_entries(
    filename: str,
    url_search: str = Query(default=""),
    method: str = Query(default=""),
    limit: int = Query(default=100),
    offset: int = Query(default=0),
) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import get_entries_dict
    return get_entries_dict(
        filename=filename,
        url_search=url_search,
        method_filter=method,
        limit=limit,
        offset=offset,
    )


@app.get("/api/har/{filename}/entry/{idx}")
def har_entry(filename: str, idx: int) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import get_entry_dict
    return get_entry_dict(filename=filename, idx=idx)


@app.get("/api/har/{filename}/analyze")
def har_analyze(filename: str) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import analyze_har_dict
    return analyze_har_dict(filename=filename)


# ──── Training data ───────────────────────────────────────────────────────────

@app.get("/api/training/stats")
def training_stats() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import get_training_stats
    return get_training_stats()


class CaptureBody(BaseModel):
    instruction: str = ""
    input: str = ""
    output: str = ""
    source: str = "canvas"


@app.post("/api/training/capture")
def training_capture(body: CaptureBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import capture_training_example
    return capture_training_example(
        instruction=body.instruction,
        input=body.input,
        output=body.output,
        source=body.source,
    )


# ──── Nexus knowledge ─────────────────────────────────────────────────────────

NEXUS_KMS = "http://localhost:8700"


async def _nexus_proxy(path: str, method: str = "GET", body: Any = None) -> Any:
    """Try Nexus KMS first; fall through on error."""
    import httpx
    async with httpx.AsyncClient(timeout=5.0) as client:
        if method == "GET":
            r = await client.get(f"{NEXUS_KMS}/api{path}")
        else:
            r = await client.post(f"{NEXUS_KMS}/api{path}", json=body)
        r.raise_for_status()
        return r.json()


@app.post("/api/nexus/search")
@app.get("/api/nexus/search")
async def nexus_search(
    q: str = Query(default=""),
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    query = q or (body or {}).get("q") or (body or {}).get("query") or ""
    try:
        return await _nexus_proxy(f"/search?q={query}")
    except Exception:
        from engine.integrations.rpc_proxy import nexus_search_python
        return nexus_search_python(query=query)


@app.post("/api/nexus/ask")
@app.get("/api/nexus/ask")
async def nexus_ask(
    q: str = Query(default=""),
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    question = q or (body or {}).get("question") or ""
    try:
        return await _nexus_proxy(f"/ask?q={question}")
    except Exception:
        from engine.integrations.rpc_proxy import nexus_ask_direct
        return nexus_ask_direct(question=question)


class NexusAddBody(BaseModel):
    title: str = ""
    content: str = ""
    content_type: str = "note"
    category: str = "general"


@app.post("/api/nexus/add")
async def nexus_add(body: NexusAddBody) -> Dict[str, Any]:
    try:
        return await _nexus_proxy("/add", "POST", body.model_dump())
    except Exception:
        from engine.integrations.rpc_proxy import nexus_add_python
        return nexus_add_python(**body.model_dump())


@app.get("/api/nexus/rules")
async def nexus_rules(scope: str = Query(default="global")) -> Dict[str, Any]:
    try:
        return await _nexus_proxy(f"/rules?scope={scope}")
    except Exception:
        return {"rules": []}


class NexusQABody(BaseModel):
    question: str = ""
    answer: str = ""
    category: str = "general"


@app.post("/api/nexus/qa")
async def nexus_qa(body: NexusQABody) -> Dict[str, Any]:
    try:
        return await _nexus_proxy("/qa", "POST", body.model_dump())
    except Exception:
        from engine.integrations.rpc_proxy import nexus_add_python
        content = f"Q: {body.question}\nA: {body.answer}"
        return nexus_add_python(title=body.question, content=content, content_type="qa", category=body.category)


# ──── NotebookLM ──────────────────────────────────────────────────────────────

@app.get("/api/nlm/notebooks")
async def nlm_notebooks() -> Dict[str, Any]:
    try:
        return await _nexus_proxy("/nlm/notebooks")
    except Exception:
        from engine.integrations.rpc_proxy import list_nlm_notebooks
        return list_nlm_notebooks()


class NLMAskBody(BaseModel):
    question: str = ""
    notebook_id: str = ""


@app.post("/api/nlm/ask")
async def nlm_ask(body: NLMAskBody) -> Dict[str, Any]:
    try:
        return await _nexus_proxy("/nlm/ask", "POST", body.model_dump())
    except Exception:
        from engine.integrations.rpc_proxy import nlm_ask_python
        return nlm_ask_python(question=body.question, notebook_id=body.notebook_id)


# ──── Compute (Colab JIT) ─────────────────────────────────────────────────────

@app.get("/api/compute/status")
def compute_status() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import get_status_dict
    return get_status_dict()


class InferBody(BaseModel):
    prompt: str = ""
    model: str = ""
    session_id: str = ""
    max_tokens: int = 512
    temperature: float = 0.7


@app.post("/api/compute/infer")
def compute_infer(body: InferBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import jit_infer_dict
    return jit_infer_dict(**body.model_dump())


class TunnelDeployBody(BaseModel):
    account_name: str = ""
    notebook_url: str = ""
    tier: str = "free"
    limits: Dict[str, Any] = {}


@app.post("/api/compute/tunnel/deploy")
def tunnel_deploy(body: TunnelDeployBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import deploy_tunnel_dict
    return deploy_tunnel_dict(**body.model_dump())


@app.get("/api/compute/tunnel/list")
def tunnel_list() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import list_sessions_dict
    return list_sessions_dict()


@app.delete("/api/compute/tunnel/{session_id}")
def tunnel_delete(session_id: str) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import teardown_by_id
    return teardown_by_id(session_id=session_id)


@app.get("/api/compute/models")
def compute_models() -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import get_all_models
    return get_all_models()


# ──── GitHub Copilot ──────────────────────────────────────────────────────────

@app.get("/api/copilot/models")
def copilot_models(account_name: str = Query(default="nihilistcod")) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import list_models_dict
    return list_models_dict(account_name=account_name)


class CopilotAskBody(BaseModel):
    prompt: str = ""
    model: str = "claude-sonnet-4.6"
    account_name: str = "nihilistcod"


@app.post("/api/copilot/ask")
def copilot_ask(body: CopilotAskBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import ask_dict
    return ask_dict(
        prompt=body.prompt,
        model=body.model,
        account_name=body.account_name,
    )


class ThreadCreateBody(BaseModel):
    account_name: str = "nihilistcod"


@app.post("/api/copilot/thread/create")
def copilot_thread_create(body: ThreadCreateBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import create_thread_dict
    return create_thread_dict(account_name=body.account_name)


class ThreadMessageBody(BaseModel):
    content: str = ""
    model: str = "claude-sonnet-4.6"
    parent_message_id: str = "root"
    account_name: str = "nihilistcod"


@app.post("/api/copilot/thread/{thread_id}/message")
def copilot_thread_message(thread_id: str, body: ThreadMessageBody) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import send_message_dict
    return send_message_dict(
        thread_id=thread_id,
        content=body.content,
        model=body.model,
        parent_message_id=body.parent_message_id,
        account_name=body.account_name,
    )


# ──── General RPC proxy ───────────────────────────────────────────────────────

@app.post("/api/rpc/proxy")
def rpc_proxy(body: Dict[str, Any]) -> Dict[str, Any]:
    from engine.integrations.rpc_proxy import proxy_request
    return proxy_request(**body)


# ──── Sidecar compatibility shim ──────────────────────────────────────────────

@app.get("/api/sidecar/health")
def sidecar_health() -> Dict[str, Any]:
    return {"status": "ok", "service": "canvas-api", "mode": "fastapi", "sidecar": False}


# ──── Entry point ─────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Return the FastAPI app instance (for use as a factory in launcher)."""
    return app


def run(host: str = "0.0.0.0", port: int = 5595, reload: bool = False) -> None:
    """Start the Canvas API server."""
    uvicorn.run(
        "engine.api.canvas_api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    run()
