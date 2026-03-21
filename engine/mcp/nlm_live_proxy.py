"""
NLM Live Proxy — Reverse-Engineered NotebookLM batchexecute API Bridge.

Version: v3.1  |  Last Updated: 2026-02-28

This module has been refactored into sub-modules for maintainability:
    - nlm_rpc_constants.py  — RPC IDs, rate limiter, response/doc-type constants
    - nlm_auth.py           — cookies, build label, session token management
    - nlm_transport.py      — batchexecute HTTP layer, response parsing, extraction
    - nlm_operations.py     — all RPC operation functions (ask, rename, add source…)
    - nlm_archive.py        — download, export, document generation, user account
    - nlm_client.py         — NLMClient class + singleton
    - nlm_proxy_routes.py   — Flask REST API with 100+ routes

All public names are re-exported here for backward compatibility.

Architecture::

    from engine.mcp.nlm_live_proxy import create_nlm_proxy_app, get_nlm_proxy_app
    app = create_nlm_proxy_app()
    app.run(port=8800)

    # Standalone:
    python -m engine.mcp.nlm_live_proxy
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Path constants (canonical definitions) ────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_COOKIES_FILE = _PROJECT_ROOT / "data" / "nlm_cookies.json"
_META_FILE = _PROJECT_ROOT / "data" / "nlm_meta.json"
_NLM_HOST = "notebooklm.google.com"
_BATCH_URL = f"https://{_NLM_HOST}/_/LabsTailwindUi/data/batchexecute"
_REQUEST_TIMEOUT = 60
_COOKIES_LOCK = threading.Lock()

# ── Re-exports: RPC constants & rate limiter ──────────────────────────────
from engine.mcp.nlm_rpc_constants import (  # noqa: F401, E402
    _DEFAULT_BL, _DEFAULT_BL_DATE,
    _RateLimiter, _rate_limiter, _get_rate_limit,
    _rpc, _is_valid_nlm_build_label,
    # RPC ID constants
    RPC_SESSION_INIT, RPC_LIST_SOURCES, RPC_LIST_NOTEBOOKS,
    RPC_LIST_AUDIO_TYPES, RPC_LOAD_NOTEBOOK, RPC_NOTEBOOK_INFO,
    RPC_GET_THREAD_IDS, RPC_READ_THREAD, RPC_USER_PROFILE,
    RPC_AI_SUMMARY, RPC_LIST_ARTIFACTS, RPC_MIND_MAP,
    RPC_ACCOUNT_STATE, RPC_READ_SOURCE, RPC_RESUME_SESSION,
    RPC_RENAME_NOTEBOOK, RPC_SAVE_NOTE, RPC_GENERATE_DOC,
    RPC_SAVE_REPORT, RPC_FAST_RESEARCH_START, RPC_ADD_RESEARCH_SOURCE,
    RPC_ADD_SOURCE, RPC_START_DEEP_RESEARCH, RPC_DELETE_SOURCE,
    RPC_CREATE_NOTE, RPC_SOURCE_STATUS, RPC_REGISTER_FILES,
    RPC_GET_SOURCE_SUMMARY, RPC_GET_AUDIO_OPTIONS, RPC_SYNC_NOTES,
    RPC_USER_PLAN, RPC_USER_QUOTA,
    _GRPC_CHAT_URL,
    # Response length & doc type constants
    RESP_LEN_DEFAULT, RESP_LEN_SHORTER, RESP_LEN_LONGER,
    DOC_TYPE_BRIEF, DOC_TYPE_NOTE,
    # Config dicts
    _WRITE_CONFIG, _SOURCE_CONFIG,
    # Registry availability flag
    _registry_available,
    # Additional RPC constants
    RPC_NOTEBOOK_CONTENT, RPC_NOTEBOOK_DETAILS, RPC_NOTEBOOK_STATE,
    RPC_OPEN_NOTEBOOK, RPC_PENDING_SOURCES, RPC_GET_ARTIFACTS,
    RPC_SOURCE_DETAIL, RPC_LIST_NOTES,
)

# ── Re-exports: Auth ─────────────────────────────────────────────────────
from engine.mcp.nlm_auth import (  # noqa: F401, E402
    _load_meta, _save_meta, _get_bl, _get_fsid,
    refresh_session_tokens,
    _load_cookies, _save_cookies, extract_cookies_from_har,
    _cookies_header, _sapisid_hash,
)

# ── Re-exports: Transport ────────────────────────────────────────────────
from engine.mcp.nlm_transport import (  # noqa: F401, E402
    _build_headers, _batchexecute, _batchexecute_multi,
    _parse_batchexecute, _parse_batchexecute_multi,
    _extract_strings, _dedup, _extract_sources,
)

# ── Re-exports: Operations ───────────────────────────────────────────────
from engine.mcp.nlm_operations import (  # noqa: F401, E402
    ask_question, rename_notebook, _parse_rename_response,
    add_source_url, _parse_add_source_response,
    add_text_source, poll_source_status, wait_for_sources,
    register_file_sources, upload_file_to_nlm,
    create_note, save_note,
    get_source_summary, get_audio_options, sync_notes,
    ask_questions_batch, _parse_ask_response,
    delete_source, start_deep_research, add_research_source,
    _grpc_ask, grpc_ask_batch,
    read_source, _parse_read_source_response,
)

# ── Re-exports: Archive ──────────────────────────────────────────────────
from engine.mcp.nlm_archive import (  # noqa: F401, E402
    download_all_sources, export_notebook, export_all_notebooks,
    get_user_quota, get_user_plan, _walk_ints,
    generate_document, _parse_generate_response,
    save_note_report, _parse_save_note_response,
)

# ── Re-exports: Client ───────────────────────────────────────────────────
from engine.mcp.nlm_client import NLMClient, get_nlm_client  # noqa: F401, E402

# ── Re-exports: Proxy routes ─────────────────────────────────────────────
from engine.mcp.nlm_proxy_routes import (  # noqa: F401, E402
    create_nlm_proxy_app, get_nlm_proxy_app, NLMProxyServer,
)


# ── CLI Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NLM Live Proxy — NotebookLM API Bridge")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8800, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    app = create_nlm_proxy_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
