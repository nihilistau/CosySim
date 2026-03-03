"""RPC proxy — makes Google API requests using account pool cookies.

Provides standalone callable functions designed for invocation via the
callPython bridge in the TypeScript Express server.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from engine.integrations.google_account_pool import get_account_pool

logger = logging.getLogger(__name__)


# ──── Auth helpers ────────────────────────────────────────────────────────────

def _sapisidhash(sapisid: str, origin: str) -> str:
    ts = str(int(time.time()))
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


# ──── Core proxy ──────────────────────────────────────────────────────────────

def proxy_request(
    url: str,
    method: str = "POST",
    account_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[str] = None,
    content_type: str = "application/json+protobuf",
) -> Dict[str, Any]:
    """Make a server-side HTTP request using account pool cookies.

    Args:
        url: Target URL.
        method: HTTP method.
        account_name: Specific account to use; picks best available if omitted.
        headers: Extra request headers to merge.
        body: Raw request body string.
        content_type: Content-Type header value.

    Returns:
        Dict with ``status``, ``body``, ``headers``, and ``latency_ms``.
    """
    pool = get_account_pool()

    if account_name:
        account = pool.get_account_by_name(account_name)
    else:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        if "colab" in domain:
            service = "colab"
        elif "notebooklm" in domain:
            service = "notebooklm"
        else:
            service = "general"
        account = pool.get_account(service)

    if not account:
        return {"status": 401, "body": "No account available", "headers": {}, "latency_ms": 0}

    origin = (
        "https://colab.research.google.com"
        if "colab" in url
        else "https://notebooklm.google.com"
    )
    cookie_str = "; ".join(f"{k}={v}" for k, v in account.cookies.items())
    sapisid = account.cookies.get("SAPISID", "")

    req_headers: Dict[str, str] = {
        "Cookie": cookie_str,
        "Content-Type": content_type,
        "Origin": origin,
        "x-goog-authuser": str(account.authuser),
    }
    if sapisid:
        req_headers["Authorization"] = _sapisidhash(sapisid, origin)
    if headers:
        req_headers.update(headers)

    start = time.time()
    try:
        resp = requests.request(
            method=method.upper(),
            url=url,
            headers=req_headers,
            data=body.encode() if body else None,
            timeout=60,
        )
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": resp.status_code,
            "body": resp.text,
            "headers": dict(resp.headers),
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {"status": 0, "body": str(exc), "headers": {}, "latency_ms": 0}


# ──── HAR / account pool helpers ──────────────────────────────────────────────

def import_har_to_pool(filepath: str, account_name: str, services: List[str]) -> Dict[str, Any]:
    """Import HAR cookies into the account pool.

    Args:
        filepath: Path to the HAR file.
        account_name: Name to assign the imported account.
        services: List of service keys (e.g. ["colab", "notebooklm"]).

    Returns:
        Dict with ``name``, ``services``, and ``cookie_count``.
    """
    pool = get_account_pool()
    account = pool.import_from_har(filepath, account_name, services)
    pool.save()
    return {
        "name": account.name,
        "services": account.services,
        "cookie_count": len(account.cookies),
    }


def list_accounts_with_tiers(dummy: str = "") -> List[Dict[str, Any]]:
    """List all accounts in the pool.

    Returns:
        List of account dicts from the pool.
    """
    pool = get_account_pool()
    return pool.list_accounts()


def configure_account(
    account_name: str,
    feature: str = "",
    service: str = "",
    value: str = "",
) -> Dict[str, Any]:
    """Configure per-account limits or feature flags.

    Args:
        account_name: Account to configure.
        feature: Feature flag name to toggle.
        service: Service key for limit configuration.
        value: New value (``"true"``/``"unlimited"`` to enable; numeric to set limit).

    Returns:
        ``{"ok": True}`` on success.
    """
    from engine.integrations.compute_router import get_compute_router

    router = get_compute_router()
    if feature:
        enabled = value.lower() in ("true", "1", "yes", "unlimited")
        router.set_feature_config(account_name, [feature] if enabled else [])
    if service:
        limit_val = float("inf") if value == "unlimited" else float(value)
        router.configure_limits(account_name, service, limit_val)
    return {"ok": True}


# ──── Compute helpers ─────────────────────────────────────────────────────────

def get_status_dict(dummy: str = "") -> Dict[str, Any]:
    """Get compute router status summary.

    Returns:
        Status dict from the compute router.
    """
    from engine.integrations.compute_router import get_compute_router

    return get_compute_router().get_status()


def jit_infer_dict(
    prompt: str,
    model: str = "auto",
    tier: str = "free",
) -> Dict[str, Any]:
    """JIT inference via the compute router.

    Args:
        prompt: Text prompt.
        model: Model identifier or ``"auto"``.
        tier: Minimum account tier (``"free"`` or ``"pro"``).

    Returns:
        Inference result dict.
    """
    from engine.integrations.compute_router import get_compute_router

    return get_compute_router().jit_infer(prompt=prompt, model=model, require_tier=tier)


def get_all_models(dummy: str = "") -> Dict[str, List[str]]:
    """Return all available models grouped by tier.

    Returns:
        Dict with ``free`` and ``pro`` model lists.
    """
    from engine.integrations.compute_router import MODELS_FREE, MODELS_PRO

    return {"free": MODELS_FREE, "pro": MODELS_PRO}


# ──── GitHub Copilot helpers ──────────────────────────────────────────────────


def list_models_dict(account_name: str = "nihilistcod") -> List[Dict[str, Any]]:
    """List all available GitHub Copilot models.

    Args:
        account_name: Account identifier for cookie lookup.

    Returns:
        List of model dicts from the Copilot API.
    """
    from engine.integrations.github_copilot_client import get_copilot_client

    try:
        client = get_copilot_client(account_name)
        return client.list_models()
    except Exception as exc:
        logger.error("list_models_dict failed: %s", exc)
        return []


def ask_dict(
    prompt: str,
    model: str = "claude-sonnet-4.6",
    account_name: str = "nihilistcod",
) -> Dict[str, Any]:
    """Ask GitHub Copilot a question and return a response dict.

    Args:
        prompt: Question or instruction.
        model: Copilot model ID.
        account_name: Account identifier for cookie lookup.

    Returns:
        Dict with ``response`` text and ``model``, or ``error`` on failure.
    """
    from engine.integrations.github_copilot_client import get_copilot_client

    try:
        client = get_copilot_client(account_name)
        response = client.ask(prompt, model=model)
        return {"response": response, "model": model, "account": account_name}
    except Exception as exc:
        logger.error("ask_dict failed: %s", exc)
        return {"error": str(exc), "response": ""}


def create_thread_dict(account_name: str = "nihilistcod") -> Dict[str, Any]:
    """Create a new Copilot chat thread.

    Args:
        account_name: Account identifier for cookie lookup.

    Returns:
        Dict with ``thread_id``, or ``error`` on failure.
    """
    from engine.integrations.github_copilot_client import get_copilot_client

    try:
        client = get_copilot_client(account_name)
        thread_id = client.create_thread()
        return {"thread_id": thread_id, "account": account_name}
    except Exception as exc:
        logger.error("create_thread_dict failed: %s", exc)
        return {"error": str(exc), "thread_id": ""}


def send_message_dict(
    thread_id: str,
    content: str,
    model: str = "claude-sonnet-4.6",
    parent_message_id: str = "root",
    account_name: str = "nihilistcod",
) -> Dict[str, Any]:
    """Send a message to a Copilot thread and return the response.

    Args:
        thread_id: Thread to post to.
        content: User message text.
        model: Copilot model ID.
        parent_message_id: Parent message ID for threading.
        account_name: Account identifier for cookie lookup.

    Returns:
        Dict with ``response``, ``message_id``, and ``model``.
    """
    from engine.integrations.github_copilot_client import get_copilot_client

    try:
        client = get_copilot_client(account_name)
        text, message_id = client.send_message(
            thread_id, content, model=model, parent_message_id=parent_message_id
        )
        return {
            "response": text,
            "message_id": message_id,
            "model": model,
            "account": account_name,
        }
    except Exception as exc:
        logger.error("send_message_dict failed: %s", exc)
        return {"error": str(exc), "response": "", "message_id": ""}


# ──── Tunnel helpers ──────────────────────────────────────────────────────────

def deploy_tunnel_dict(
    account_name: str = "",
    tunnel_type: str = "cloudflare",
) -> Dict[str, Any]:
    """Deploy a Colab tunnel server.

    Args:
        account_name: Account to use; picks best available if empty.
        tunnel_type: Tunnel type (``"cloudflare"`` or ``"ngrok"``).

    Returns:
        Dict with ``tunnel_url``, ``hardware``, ``kernel_id``, ``started_at``,
        or ``{"error": ...}`` on failure.
    """
    from engine.integrations.colab_tunnel_server import get_tunnel_server

    server = get_tunnel_server()
    try:
        session = server.deploy(account_name or None)
        return {
            "tunnel_url": session.tunnel_url,
            "hardware": session.hardware,
            "kernel_id": session.kernel_id,
            "session_id": session.session_id,
            "started_at": session.started_at,
        }
    except Exception as exc:
        return {"error": str(exc)}


def list_sessions_dict(dummy: str = "") -> List[Dict[str, Any]]:
    """List all active tunnel sessions.

    Returns:
        List of session dicts with ``tunnel_url``, ``hardware``, ``healthy``,
        ``started_at``, and ``kernel_id``.
    """
    from engine.integrations.colab_tunnel_server import get_tunnel_server

    server = get_tunnel_server()
    return [
        {
            "tunnel_url": s.tunnel_url,
            "hardware": s.hardware,
            "healthy": s.healthy,
            "started_at": s.started_at,
            "kernel_id": s.kernel_id,
            "session_id": s.session_id,
        }
        for s in server.get_active_sessions()
    ]


def teardown_by_id(session_id: str) -> Dict[str, Any]:
    """Tear down a tunnel session by its session_id.

    Args:
        session_id: Jupyter session UUID of the session to tear down.

    Returns:
        ``{"ok": True, "session_id": ...}`` or ``{"error": ...}`` if not found.
    """
    from engine.integrations.colab_tunnel_server import get_tunnel_server

    server = get_tunnel_server()
    # pylint: disable=protected-access
    session = server._sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}
    server.teardown(session)
    return {"ok": True, "session_id": session_id}


# ──── HAR parser bridge ───────────────────────────────────────────────────────

def list_har_files_dict(**_: Any) -> Dict[str, Any]:
    """List all HAR files across configured HAR directories."""
    from engine.integrations.har_parser import list_har_files_dict as _fn
    return _fn()


def get_entries_dict(
    filename: str,
    url_search: str = "",
    method_filter: str = "",
    offset: int = 0,
    limit: int = 100,
    **_: Any,
) -> Dict[str, Any]:
    """Get paginated, filtered entries from a HAR file.

    Args:
        filename: HAR file name (auto-located across base dirs).
        url_search: URL substring filter.
        method_filter: HTTP method filter.
        offset: Pagination offset.
        limit: Page size (max 200).

    Returns:
        Dict with ``total``, ``entries`` (list of HAREntry dicts).
    """
    from engine.integrations.har_parser import get_entries_dict as _fn
    return _fn(
        filename=filename,
        url_search=url_search,
        method_filter=method_filter,
        offset=int(offset),
        limit=int(limit),
    )


def get_entry_dict(filename: str, idx: int, **_: Any) -> Dict[str, Any]:
    """Get a single HAR entry by filename and index."""
    from engine.integrations.har_parser import get_entry_dict as _fn
    return _fn(filename=filename, idx=int(idx))


def analyze_har_dict(filename: str, **_: Any) -> Dict[str, Any]:
    """Analyze a HAR file and return a summary."""
    from engine.integrations.har_parser import analyze_har_dict as _fn
    return _fn(filename=filename)


def import_har_to_pool(
    filepath: str = "",
    account_name: str = "",
    services: Optional[List[str]] = None,
    **_: Any,
) -> Dict[str, Any]:
    """Import cookies from a HAR file into the account pool."""
    from engine.integrations.har_parser import import_har_to_pool as _fn
    return _fn(filepath=filepath, account_name=account_name, services=services)
