"""
NLM Live Proxy — Reverse-Engineered NotebookLM batchexecute API Bridge.

Version: v3.1  |  Last Updated: 2026-02-28

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DISCOVERY METHODOLOGY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every RPC mapping in this file was discovered empirically through 10+ sessions of
manual HAR analysis.  The workflow each session:

  1. Open NotebookLM in Chrome with DevTools → Network tab open.
  2. Perform the target operation (rename notebook, add source, ask question…).
  3. In DevTools: Network tab → right-click the batchexecute POST → "Save all as
     HAR with content" (must tick "Include sensitive data" for cookies).
  4. Inspect the HAR to identify the RPC ID (the ``rpcids`` query param), the
     exact ``f.req`` POST body structure, and the wrb.fr response shape.
  5. Implement the RPC helper, add a REST endpoint, add it to the RPC table here.

Several RPCs required multiple HAR captures to confirm — particularly write RPCs
where the first attempt used a wrong payload shape that silently returned null.

CRITICAL CORRECTION (v3.1): ``s0tc2d`` was mapped as RPC_CHAT_MESSAGE in v2.x
based on a misread of early HAR captures.  A fresh HAR confirmed it is actually
RENAME_NOTEBOOK.  Real chat uses the GenerateFreeFormStreamed gRPC endpoint.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSPORT PROTOCOL: batchexecute
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NotebookLM's primary API is Google's generic ``/_/LabsTailwindUi/data/batchexecute``
endpoint (same transport used by Google Maps, Docs, etc.).

Request format:
  POST /batchexecute?rpcids=<id>&bl=<build_label>&f.sid=<session_id>&hl=en&rt=c
  Content-Type: application/x-www-form-urlencoded
  Body: f.req=[["rpc_id","args_json",null,"generic"]]&at=<anti_forgery_token>

  Multiple RPCs in one HTTP request (batching):
    f.req=[["rpc_id_1","args_1",null,"generic"],["rpc_id_2","args_2",null,"generic"]]

Response format (multi-level wrapping):
  Line 1:  )]}'                                  ← XSSI protection prefix, always strip
  Lines 2+: one JSON array per wrb.fr block:
    [["wrb.fr","rpc_id","<inner_json_string>",null,null,null,"generic"],...]
  The actual data lives inside the inner_json_string, double-JSON-encoded.

Auth headers required:
  Cookie: <all Google session cookies>
  Authorization: SAPISIDHASH <ts>_<sha1(ts + " " + SAPISID + " " + origin)>
  X-Same-Domain: 1
  Origin: https://notebooklm.google.com

Build label (bl):
  Stable per Google frontend deploy, changes ~weekly.
  Format: boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
  Stored in data/nlm_meta.json.  Warn after 8 days.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSPORT PROTOCOL: GenerateFreeFormStreamed (gRPC-Web)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Real conversational chat uses a separate proto endpoint, NOT batchexecute:

  POST https://notebooklm.google.com/_/LabsTailwindUi/data/
       google.internal.labs.tailwind.orchestration.v1
       .LabsTailwindOrchestrationService/GenerateFreeFormStreamed
  Body: f.req=<url_encoded_json>

Payload (outer): [null, json.dumps(inner)]
Payload (inner, 9 elements):
  [0] source_context  = [[[src_id_1]], [[src_id_2]], ...]
  [1] question text
  [2] null
  [3] response config = [2, null, [1], [1]]
  [4] thread_id       = UUID (existing or new, for conversation threading)
  [5] null
  [6] null
  [7] notebook_id
  [8] 1

Response is SSE-like streaming where each chunk delivers the FULL TEXT SO FAR
(not incremental deltas).  Parse via wrb.fr blocks: inner[0][0] = full text.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL OPERATIONAL NOTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BL Staleness:
  Google deploys new NLM frontends ~weekly, changing the build label (bl).
  A stale bl causes all batchexecute calls to return null data silently.
  → Run ``POST /cookies/refresh`` or ``POST /meta`` to update the bl.
  → Import a fresh HAR to get the new bl automatically.
  → After 8 days without a bl update, the proxy logs a warning.

Cookie Refresh:
  Google session cookies expire; SID tokens are typically valid 6-12 months
  but ``f.sid`` and ``at`` tokens are session-scoped and expire sooner.
  → ``POST /cookies/refresh`` auto-fetches fresh f.sid and at from the live page.
  → ``POST /cookies/capture`` uses Chrome CDP to extract fresh cookies entirely.
  → ``POST /cookies/import`` + HAR file is the manual fallback.

Auth failures:
  HTTP 401 → cookies are fully expired, must re-authenticate.
  null data with 200 OK → bl or f.sid is stale; run /cookies/refresh.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETE CONFIRMED RPC TABLE  (v3.1, 25 batchexecute RPCs + 1 proto endpoint)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RPC ID    Name                   Confirmed   Description
───────   ────────────────────   ─────────   ──────────────────────────────────────
ZwVcOc    SESSION_INIT           2026-02-20  Init session, returns account info
wXbhsf    LIST_SOURCES           2026-02-20  List all sources in a notebook
ub2Bae    LIST_NOTEBOOKS         2026-02-20  List all notebooks for account
sqTeoe    LIST_AUDIO_TYPES       2026-02-24  List available audio overview types
rLM1Ne    LOAD_NOTEBOOK          2026-02-20  Load notebook with sources + status
e3bVqc    NOTEBOOK_INFO          2026-02-20  Get raw notebook content/document data
hPTbtc    GET_THREAD_IDS         2026-02-24  List conversation thread IDs  (⚠️ v3.0 rename)
khqZz     READ_THREAD            2026-02-24  Read messages in a thread      (⚠️ v3.0 rename)
JFMDGd    USER_PROFILE           2026-02-24  Get user profile + queries remaining (⚠️ v3.0)
VfAZjd    AI_SUMMARY             2026-02-20  Generate/fetch AI notebook summary
gArtLc    LIST_ARTIFACTS         2026-02-20  List notes and artifacts
cFji9     MIND_MAP               2026-02-24  Generate/fetch D3 mind map     (⚠️ v3.0 rename)
ozz5Z     ACCOUNT_STATE          2026-02-20  Account state + storage quota
tr032e    READ_SOURCE            2026-02-22  Read full text content of a source
CCqFvf    RESUME_SESSION         2026-02-27  Load last active notebook       (v3.0 new)
s0tc2d    RENAME_NOTEBOOK        2026-02-28  ⭐ CRITICAL: was wrong in v2.x as CHAT_MESSAGE
CYK0Xb    SAVE_NOTE              2026-02-22  Citation-annotate Q&A (was "legacy chat" ⚠️)
ciyUvf    GENERATE_DOC           2026-02-22  Generate document from sources
R7cb6c    SAVE_REPORT            2026-02-22  Save note artifact to notebook
Ljjv0c    FAST_RESEARCH_START    2026-02-27  Start fast research session     (v3.0 new)
LBwxtb    ADD_RESEARCH_SOURCE    2026-02-28  Add AI-generated doc as source  (v3.1 new)
izAoDd    ADD_SOURCE             2026-02-28  Add URL or YouTube source       (v3.1 new)
QA9ei     START_DEEP_RESEARCH    2026-02-28  Start deep research → session_id (v3.1 new)
tGMBJ     DELETE_SOURCE          2026-02-28  Delete a source from notebook   (v3.1 new)
──────    ─────────────────────  ─────────   ─────────────────────────────────────────────
(proto)   GenerateFreeFormStreamed 2026-02-27  Real NLM chat via gRPC-Web     (v3.0 new)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECTION INDEX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Imports & Module-Level Globals
  2. Version History
  3. Constants & RPC Registry
  4. Rate Limiter
  5. Meta / Build Label Management
  6. Cookie Management
  7. batchexecute Transport Layer
  8. Response Parsing
  9. Content Extraction Utilities
 10. Write Operation Helpers  (rename, add source, delete source, deep research)
 11. Download & Archive Operations
 12. NLMClient Class
 13. Flask Application  (REST API at :8800)
 14. CLI Entry Point

Architecture::

    from engine.mcp.nlm_live_proxy import create_nlm_proxy_app, get_nlm_proxy_app
    app = create_nlm_proxy_app()
    app.run(port=8800)

    # Standalone:
    python -m engine.mcp.nlm_live_proxy

Auth is handled via Google session cookies extracted from either:
  1. A manually captured HAR file (DevTools → Save all as HAR with sensitive data)
  2. Automatically via Chrome DevTools Protocol (CDP) — preferred

RPC ID Management:
  RPC IDs are **STABLE within a build label** but MAY change when Google deploys
  a new frontend (BL changes approx. weekly). IDs are loaded from:
    1. data/nlm_rpc_registry.json   — updated by nlm_automation.py
    2. nlm_rpc_mapper._FALLBACK_RPC_IDS   — hardcoded confirmed IDs (fallback)
  Run ``python -m engine.nexus.nlm_automation`` to re-discover all IDs.
  Run ``python -m engine.nexus.nlm_rpc_mapper`` to check registry status.

Rate Limiting:
  All outbound NLM calls are rate-limited (default 1.5s between requests).
  Configure via ``notebooklm.rate_limit_seconds`` in config/default.yaml.
  Batch calls count as ONE request for rate-limiting purposes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request

from engine.config import get_config

try:
    from engine.integrations.nlm_rpc_registry import get_rpc_registry as _get_registry
except Exception:
    _get_registry = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_COOKIES_FILE = _PROJECT_ROOT / "data" / "nlm_cookies.json"
_META_FILE = _PROJECT_ROOT / "data" / "nlm_meta.json"
_NLM_HOST = "notebooklm.google.com"
_BATCH_URL = f"https://{_NLM_HOST}/_/LabsTailwindUi/data/batchexecute"
_REQUEST_TIMEOUT = 60
_COOKIES_LOCK = threading.Lock()

# ── Version History ───────────────────────────────────────────────────────
# v1.0  2026-02-20  Initial proxy with ~12 RPCs from first HAR capture.
#                   Covered: SESSION_INIT, LIST_SOURCES, LIST_NOTEBOOKS,
#                   LOAD_NOTEBOOK, NOTEBOOK_INFO, AI_SUMMARY, LIST_ARTIFACTS,
#                   ACCOUNT_STATE, READ_SOURCE, GENERATE_DOC, SAVE_REPORT,
#                   SAVE_NOTE (CYK0Xb, wrongly called "ask" at the time).
# v2.0  2026-02-22  Added SSE streaming for real-time answers, batch Q&A via
#                   multi-RPC batchexecute, and first write RPCs.  16 RPCs total.
# v2.1  2026-02-24  21 RPCs confirmed.  Corrected 4 ID mappings (sqTeoe was
#                   "list all notebooks" → is LIST_AUDIO_TYPES; hPTbtc was
#                   "list sources paged" → is GET_THREAD_IDS; khqZz was
#                   "sub-notebook sources" → is READ_THREAD; JFMDGd was
#                   "sources condensed" → is USER_PROFILE; cFji9 was
#                   "conversation history" → is MIND_MAP).
#                   s0tc2d still wrongly mapped as RPC_CHAT_MESSAGE.
# v3.0  2026-02-27  Chrome CDP auth capture (nlm_har_capture.py).
#                   Discovered GenerateFreeFormStreamed proto endpoint — this is
#                   the REAL chat interface, not any batchexecute RPC.
#                   Added RESUME_SESSION (CCqFvf) and FAST_RESEARCH_START (Ljjv0c).
#                   QA distiller and grpc_ask batch implemented.
# v3.1  2026-02-28  CRITICAL CORRECTIONS from fresh HAR analysis:
#                     s0tc2d = RENAME_NOTEBOOK (NOT chat — v2.x mapping was wrong)
#                     izAoDd = ADD_SOURCE (new: add URL/YouTube sources)
#                     QA9ei  = START_DEEP_RESEARCH (new: async research pipeline)
#                     tGMBJ  = DELETE_SOURCE (new: remove a source by UUID)
#                     LBwxtb = ADD_RESEARCH_SOURCE (new: add AI doc as source)
#                   Added download_all_sources(), export_notebook(),
#                   export_all_notebooks() for full-notebook archival.
#                   RPC count: 25 batchexecute RPCs + 1 proto endpoint = 26 total.
# ─────────────────────────────────────────────────────────────────────────

# Known-good build label — updated automatically on HAR import
# Format: boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
# Changes roughly weekly when Google deploys a new frontend build.
_DEFAULT_BL = "boq_labs-tailwind-frontend_20260226.08_p0"
_DEFAULT_BL_DATE = "2026-02-26"  # for staleness calculation

# ════════════════════════════════════════════════════════════════════════════
# RATE LIMITER
# Enforces a minimum time gap between all outbound NLM API calls.
# Google will 429-throttle or rate-ban clients that poll too fast.
# Default gap: 1.5 s (configurable via notebooklm.rate_limit_seconds).
# Batch calls (multiple RPCs in one HTTP request) count as ONE request.
# ════════════════════════════════════════════════════════════════════════════

class _RateLimiter:
    """Simple per-host rate limiter. Enforces a minimum gap between requests."""

    def __init__(self, min_gap_seconds: float = 1.5) -> None:
        self._last_call: float = 0.0
        self._min_gap = min_gap_seconds
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until the minimum gap has elapsed since the last call."""
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_gap:
                time.sleep(self._min_gap - elapsed)
            self._last_call = time.time()

    def set_gap(self, seconds: float) -> None:
        self._min_gap = seconds


def _get_rate_limit() -> float:
    try:
        return float(get_config().get("notebooklm.rate_limit_seconds", 1.5))
    except Exception:
        return 1.5


_rate_limiter = _RateLimiter(min_gap_seconds=1.5)

# ════════════════════════════════════════════════════════════════════════════
# CONSTANTS & RPC REGISTRY
#
# Hardcoded RPC IDs (confirmed from HAR analysis) used as readable aliases.
# At call time, _rpc(operation, fallback) consults nlm_rpc_mapper first —
# if the registry has a fresher value it overrides the constant.
#
# ⚠️  Mapping corrections between versions are documented on each constant.
# ⭐  v3.1 additions are the result of the 2026-02-28 deep HAR session.
# ════════════════════════════════════════════════════════════════════════════

try:
    from engine.nexus.nlm_rpc_mapper import get_rpc_id as _get_rpc_id
    _registry_available = True
except ImportError:
    _registry_available = False
    def _get_rpc_id(op: str) -> Optional[str]:  # type: ignore[misc]
        return None

def _rpc(operation: str, fallback: str) -> str:
    """Get RPC ID from YAML registry, then old mapper, then hardcoded fallback."""
    if _get_registry is not None:
        try:
            reg = _get_registry()
            rpcid = reg.get_rpcid(operation)
            if rpcid:
                return rpcid
        except Exception:
            pass
    if _registry_available:
        rid = _get_rpc_id(operation)
        if rid:
            return rid
    return fallback

# Readable aliases (resolved at call time via _rpc() in actual calls)
# Each constant has: confirmed date · payload signature · response shape · gotchas

RPC_SESSION_INIT = _rpc("session_init", "ZwVcOc")
# HAR-confirmed 2026-02-20.  Initialises an NLM browser session.
# Payload: [] (empty)
# Response: [session_token, account_info, ...]

RPC_LIST_SOURCES = _rpc("list_sources", "wXbhsf")
# HAR-confirmed 2026-02-20.  Lists all sources in a notebook.
# Payload: [null, 1, null, [2]]
# Response: [[[notebook_name, [source_obj, ...]]], ...]
# Source obj: [[uid], title, [meta: word_count@1, src_type@6, url_list@7], ...]

RPC_LIST_NOTEBOOKS = _rpc("list_notebooks", "ub2Bae")
# HAR-confirmed 2026-02-20.  Lists all notebooks for the authenticated account.
# Payload: [[2]]
# Response: [[[nb_obj, ...]], ...]  — nb_obj contains UUID and name strings.

RPC_LIST_AUDIO_TYPES = _rpc("list_audio_types", "sqTeoe")
# HAR-confirmed 2026-02-24.  Returns available audio overview types/voices.
# ⚠️ v3.0 correction: was wrongly mapped as "list all notebooks" in v2.x.
# Payload: [notebook_id]
# Response: list of audio type descriptors

RPC_LOAD_NOTEBOOK = _rpc("load_notebook", "rLM1Ne")
# HAR-confirmed 2026-02-20.  Loads a notebook with source processing status.
# Used by /sources/wait polling — returns word_count per source (0 = still processing).
# Payload: [notebook_id, null, [2], null, 0]
# Response: same shape as wXbhsf but richer per-source metadata.

RPC_NOTEBOOK_INFO = _rpc("notebook_info", "e3bVqc")
# HAR-confirmed 2026-02-20.  Returns raw notebook content/document data.
# Payload: [null, null, notebook_id]
# Response: nested document structure (use _extract_strings for text).

RPC_GET_THREAD_IDS = _rpc("get_thread_ids", "hPTbtc")
# HAR-confirmed 2026-02-24.  Returns conversation thread IDs for a notebook.
# ⚠️ v3.0 correction: was wrongly mapped as "list sources paged" in v2.x.
# Payload: [[], null, notebook_id, page_size]
# Response: [[thread_id_list], ...] where each item is [thread_uuid, ...]

RPC_READ_THREAD = _rpc("read_thread", "khqZz")
# HAR-confirmed 2026-02-24.  Reads all messages in a conversation thread.
# ⚠️ v3.0 correction: was wrongly mapped as "sub-notebook sources" in v2.x.
# Payload: [[], null, null, thread_id, page_size]
# Response: nested message objects (use _extract_strings for text content).

RPC_USER_PROFILE = _rpc("user_profile", "JFMDGd")
# HAR-confirmed 2026-02-24.  Returns user profile: email, name, queries remaining.
# ⚠️ v3.0 correction: was wrongly mapped as "sources condensed" in v2.x.
# Payload: [notebook_id, [2]]
# Response: [[email, name, ...], null, queries_remaining, ...]

RPC_AI_SUMMARY = _rpc("ai_summary", "VfAZjd")
# HAR-confirmed 2026-02-20.  Fetches or generates the AI summary of a notebook.
# Payload: [notebook_id, [2]]
# Response: nested text structure — join _extract_strings(data, 50).

RPC_LIST_ARTIFACTS = _rpc("list_artifacts", "gArtLc")
# HAR-confirmed 2026-02-20.  Lists notes and saved artifacts in a notebook.
# Payload: [[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""]
# Response: nested artifact objects with title/content strings.

RPC_MIND_MAP = _rpc("mind_map", "cFji9")
# HAR-confirmed 2026-02-24.  Generates/returns D3-format mind map JSON.
# ⚠️ v3.0 correction: was wrongly mapped as "conversation history" in v2.x.
# Payload: [notebook_id, null, null, [2]]
# Response: [json_string, ...] — parse inner JSON for D3 hierarchy.

RPC_ACCOUNT_STATE = _rpc("account_state", "ozz5Z")
# HAR-confirmed 2026-02-20.  Returns account state including storage quota.
# Also aliased as RPC_USER_QUOTA (same ID, different usage context).
# Payload: [[[null, "1", 627], [null,null,null,null,null,null,null,null,null,[null,null,4]], 1]]]
# Response: complex nested quota structure.

RPC_READ_SOURCE = _rpc("read_source", "tr032e")
# HAR-confirmed 2026-02-22.  Reads the full text content of a notebook source.
# Returns the complete markdown-formatted text.  Expensive for large sources.
# Payload: [[[[source_uuid]]]]
# Response: nested text chunks — join via _extract_strings(data, 10).

RPC_RESUME_SESSION = _rpc("resume_session", "CCqFvf")
# HAR-confirmed 2026-02-27.  ⭐ v3.0 new.  Loads the last active notebook.
# Payload: []
# Response: notebook_id and basic metadata.

RPC_RENAME_NOTEBOOK = _rpc("rename_notebook", "s0tc2d")
# HAR-confirmed 2026-02-28.  ⭐ CRITICAL v3.1 CORRECTION.
# This RPC was WRONGLY mapped as RPC_CHAT_MESSAGE in all v2.x code.
# A fresh HAR on 2026-02-28 definitively confirmed s0tc2d = RENAME_NOTEBOOK.
# Real chat uses GenerateFreeFormStreamed (the gRPC proto endpoint), not batchexecute.
# Payload: [notebook_id, [[null, null, null, [null, "new_name"]]]]
# Response: [new_name, null, notebook_id, emoji_char, ...]

RPC_CREATE_NOTE = _rpc("create_note", "CYK0Xb")
# HAR-confirmed 2026-02-22.  Citation-annotate Q&A (was called "legacy chat" in v2.x).
# ⚠️ v3.0 correction: this is NOT real chat — it annotates text with source citations.
# Used for Q&A distillation: returns cited answers grounded in notebook sources.
# Payload: [notebook_id, question_text]
# Response: [[answer_id, markdown_answer_with_citations], ...]
# Citations appear as [source_uuid] markers in the answer text.

RPC_GENERATE_DOC = _rpc("generate_doc", "ciyUvf")
# HAR-confirmed 2026-02-22.  Generates a document/report from selected sources.
# Payload: [_WRITE_CONFIG, notebook_id, [[src_id_1], [src_id_2], ...]]
# Response: [[title, description, null, [[src_ids]]], ...]

RPC_SAVE_REPORT = _rpc("save_report", "R7cb6c")
# HAR-confirmed 2026-02-22.  Saves a note artifact to a notebook.
# Payload: [_WRITE_CONFIG, notebook_id, [null, null, note_type, [[src_id], ...]]]
# Response: [[note_id, title, note_type_int, [[source_ids]]], ...]

RPC_FAST_RESEARCH_START = _rpc("fast_research_start", "Ljjv0c")
# HAR-confirmed 2026-02-27.  ⭐ v3.0 new.  Starts a fast research session.
# Payload: [[query, 1], null, 1, notebook_id]
# Response: [session_id, ...]

RPC_ADD_RESEARCH_SOURCE = _rpc("add_research_source", "LBwxtb")
# HAR-confirmed 2026-02-28.  ⭐ v3.1 new.
# Adds an AI-generated research document as a notebook source.
# Called AFTER start_deep_research (QA9ei) with the AI-authored content.
# Payload: [null, [1], session_id, notebook_id, [[null, [title, content]]]]
# Response: source metadata including new source UUID.

RPC_ADD_SOURCE = _rpc("add_source", "izAoDd")
# HAR-confirmed 2026-02-28.  ⭐ v3.1 new.
# Adds a URL or YouTube video as a notebook source.
# The source object shape differs by content type (see add_source_url docstring):
#   Regular URL: source_obj[2] = url
#   YouTube URL: source_obj[7] = [url]   (list, at position 7, not 2)
# Payload: [[source_obj], notebook_id, [2], _SOURCE_CONFIG]
# Response: new source metadata including UUID.  Status is "processing" initially.

RPC_START_DEEP_RESEARCH = _rpc("start_deep_research", "QA9ei")
# HAR-confirmed 2026-02-28.  ⭐ v3.1 new.
# Starts an async deep research session on a given topic.
# NLM generates a research document in the background (takes 10-60 seconds).
# Returns session_id UUID; poll via add_research_source (LBwxtb) to retrieve doc.
# Payload: [null, [1], ["topic", 1], 5, notebook_id]
# Response: [session_uuid, ...]

RPC_DELETE_SOURCE = _rpc("delete_source", "tGMBJ")
# HAR-confirmed 2026-02-28.  ⭐ v3.1 new.
# Deletes a source from a notebook by UUID.
# Payload: [[[source_uuid]], [2]]
# Response: acknowledgement (empty or minimal).

RPC_USER_QUOTA = _rpc("account_state", "ozz5Z")
# Same ID as RPC_ACCOUNT_STATE — used in get_user_quota() specifically for
# the quota/storage usage payload variant.

# ── New RPCs confirmed from HAR 2026-03-01 manual_testing.har ──────────────
RPC_USER_PLAN        = _rpc("user_plan", "ZwVcOc")   # GET_USER_PLAN — quota limits (NOT delete_notebook — has no nb_id arg)
RPC_OPEN_NOTEBOOK    = _rpc("open_notebook", "CCqFvf")   # OPEN_NOTEBOOK — called when entering a notebook, returns state
RPC_SOURCE_STATUS    = _rpc("source_status", "rLM1Ne")   # POLL_SOURCE_STATUS — poll until source indexed (arg[4]=0 first, 1=continuing)
RPC_PENDING_SOURCES  = _rpc("pending_sources", "hPTbtc")   # GET_PENDING_SOURCES — [[], null, nb_id, 20]
RPC_NOTEBOOK_DETAILS = _rpc("notebook_details", "JFMDGd")   # GET_NOTEBOOK_DETAILS — [nb_id, [2]]
RPC_NOTEBOOK_CONTENT = _rpc("notebook_content", "VfAZjd")   # GET_NOTEBOOK_CONTENT — [nb_id, [2]]
RPC_SAVE_NOTE = _rpc("save_note", "cYAfTb")  # SAVE_NOTE — live auto-save as you type [nb_id, note_id, [[["<html>","title",[],0]]], [2]]
RPC_SOURCE_DETAIL    = _rpc("source_detail", "hizoJc")   # GET_SOURCE_DETAIL — [[src_id], [2], [2]]
RPC_REGISTER_FILES   = _rpc("register_files", "o4cbdc")   # REGISTER_FILE_UPLOAD — [[[fn1],[fn2]], nb_id, [2], [1,...,[1]]]
RPC_SYNC_NOTES = _rpc("sync_notes", "cFji9")  # SYNC_NOTES — delta poll for note changes [nb_id, null, [prev_ts_sec, prev_ts_nano], [2]]. Returns [[note_objects], [current_ts]]. No prev_ts on first call.
RPC_NOTEBOOK_STATE   = _rpc("notebook_state", "e3bVqc")   # GET_NOTEBOOK_STATE — [null, null, nb_id]

# ── New RPCs confirmed from HAR 2026-03-01 addnote-saveresptonote-convsource.har ──
RPC_CREATE_NOTE      = _rpc("create_note", "CYK0Xb")   # CREATE_NOTE — [nb_id, content_html, [1], null, title, null, [2]]. Also used for "save response to note" (pass AI response as content).
RPC_LIST_NOTES       = _rpc("list_notes", "khqZz")    # LIST_NOTES — [[],null,null,notes_container_id,20]. Returns notes with full markdown content.
RPC_LIST_SOURCES     = _rpc("list_sources", "wXbhsf")   # LIST_SOURCES — [null,1,null,[2]]. Returns all sources in all notebooks (sidebar list).
RPC_GET_AUDIO_OPTIONS = _rpc("get_audio_options", "sqTeoe")  # GET_AUDIO_OPTIONS — [[2,null,null,[1,...],[[2,1]]],null,1]. Returns audio format types: Deep dive, Brief, Critique, Debate.
RPC_GET_ARTIFACTS    = _rpc("get_artifacts", "gArtLc")   # GET_ARTIFACTS — [[2,...],nb_id,filter_str]. filter_str uses SQL-like syntax e.g. 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'
RPC_GET_SOURCE_SUMMARY = _rpc("get_source_summary", "tr032e") # GET_SOURCE_SUMMARY — [[[[source_id]]]]. Returns AI-generated markdown summary of a source. NEW — never seen in prior HARs.

# ── Response Length Constants ────────────────────────────────────────────
# Passed as second element of response-config arrays in several RPCs.
# Controls how much detail NLM returns in the response payload.
RESP_LEN_DEFAULT = 4  # standard response verbosity (most RPCs)
RESP_LEN_LONGER  = 1  # request a longer/more detailed response
RESP_LEN_SHORTER = 2  # request a condensed/shorter response

# ── Document/Note Types ──────────────────────────────────────────────────
# Used in generate_document() and save_note() to control output format.
DOC_TYPE_BRIEF   = 2  # standard brief document (used in most cases)
DOC_TYPE_NOTE    = 9  # deep research / long-form note type

# Write config object shared by several write RPCs (ciyUvf, R7cb6c).
# Observed verbatim across 3 different HAR captures — do not change.
# Structure matches the "write operation metadata" envelope used by NLM.
_WRITE_CONFIG = [2, None, None,
                 [1, None, None, None, None, None, None, None, None, None, [1]],
                 [[2, 1]]]

# Source config object used by izAoDd (ADD_SOURCE RPC).
# This is the "source creation metadata" envelope — confirmed from HAR.
# Position [0] = 1 signals "create new source"; the [1] at position 10 is flags.
_SOURCE_CONFIG = [1, None, None, None, None, None, None, None, None, None, [1]]

# Override from registry if available
if _get_registry is not None:
    try:
        _reg = _get_registry()
        _wc = _reg.get_shared_config("write_config")
        if _wc:
            _WRITE_CONFIG = _wc
        _sc = _reg.get_shared_config("source_config")
        if _sc:
            _SOURCE_CONFIG = _sc
        del _reg, _wc, _sc
    except Exception:
        pass

# gRPC endpoint for real free-form chat (GenerateFreeFormStreamed)
_GRPC_CHAT_URL = (
    "https://notebooklm.google.com/_/LabsTailwindUi/data/"
    "google.internal.labs.tailwind.orchestration.v1"
    ".LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
)


def _is_valid_nlm_build_label(build_label: Optional[str]) -> bool:
    """Return True when a build label matches NotebookLM's frontend pattern."""
    return bool(build_label and build_label.startswith("boq_labs-tailwind-frontend_"))


# ════════════════════════════════════════════════════════════════════════════
# META / BUILD LABEL MANAGEMENT
#
# The batchexecute URL requires two session parameters:
#   bl      — build label; stable per Google frontend deploy, changes ~weekly.
#             Format: boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
#   f.sid   — server session ID; extracted from the NLM page's WIZ_global_data.
#   at      — anti-forgery token; also from WIZ_global_data (key "SNlM0e").
#
# When bl is stale, batchexecute silently returns null for all calls.
# Refresh via: POST /cookies/refresh  or  POST /meta  or  re-import a HAR.
# ════════════════════════════════════════════════════════════════════════════

def _load_meta() -> Dict[str, str]:
    """Load stored build label and session meta from disk."""
    try:
        if _META_FILE.exists():
            return json.loads(_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"bl": _DEFAULT_BL, "f_sid": "-1"}


def _save_meta(meta: Dict[str, str]) -> None:
    """Persist build label and session meta to disk."""
    import datetime
    # Stamp BL update time when BL changes
    existing = _load_meta()
    if meta.get("bl") and meta.get("bl") != existing.get("bl"):
        meta["bl_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _META_FILE.parent.mkdir(parents=True, exist_ok=True)
    _META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _get_bl() -> str:
    """Return the current build label, falling back to default.

    Logs a warning when the stored BL is more than 8 days old since
    Google typically deploys new frontends weekly.
    """
    meta = _load_meta()
    bl = meta.get("bl", _DEFAULT_BL)
    # Check staleness using bl_updated_at if present
    updated_at = meta.get("bl_updated_at")
    if updated_at:
        try:
            import datetime
            age_days = (datetime.datetime.now(datetime.timezone.utc) -
                        datetime.datetime.fromisoformat(updated_at)).days
            if age_days >= 8:
                logger.warning(
                    "NLM build label is %d days old (%s). "
                    "Google may have deployed a new frontend — "
                    "consider importing a fresh HAR or CDP capture.",
                    age_days, bl,
                )
        except Exception:
            pass
    return bl


def _get_fsid() -> str:
    """Return the current f.sid session ID."""
    return _load_meta().get("f_sid", "-1")


def refresh_session_tokens() -> bool:
    """Refresh f.sid and at token by loading the NLM main page with stored cookies.

    Call this when batchexecute returns null data (stale f.sid / at token).
    Extracts tokens from ``WIZ_global_data`` in the page HTML — tries multiple
    known key variants since Google obfuscates these names per build:

    - f.sid:  ``IxjpMA``, ``FdrFJe``
    - at:     ``SNlM0e``
    - bl:     ``QrtxK``, ``cfb2h`` (also detected from boq_ string in HTML)

    Persists any found values to ``data/nlm_meta.json``.

    Returns:
        True if at least one token was refreshed, False otherwise.
    """
    cookies = _load_cookies()
    if not cookies:
        logger.warning("No cookies stored — cannot refresh session tokens")
        return False
    headers = {
        "Cookie": _cookies_header(cookies),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        req = urllib.request.Request(f"https://{_NLM_HOST}/", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.error("Failed to load NLM page for token refresh: %s", exc)
        return False

    m = re.search(r"WIZ_global_data\s*=\s*({.*?});", html, re.DOTALL)
    wiz: Dict[str, Any] = {}
    if m:
        try:
            wiz = json.loads(m.group(1))
        except Exception as exc:
            logger.warning("Failed to parse WIZ_global_data: %s", exc)

    invalid_build_label: Optional[str] = None
    for key in ("QrtxK", "cfb2h"):
        val = wiz.get(key)
        if isinstance(val, str) and val.startswith("boq_") and not _is_valid_nlm_build_label(val):
            invalid_build_label = val
            break
    if not invalid_build_label:
        match = re.search(r'"(boq_[^"]+)"', html)
        if match and not _is_valid_nlm_build_label(match.group(1)):
            invalid_build_label = match.group(1)
    if invalid_build_label or "identityfrontendauthuiserver" in html.lower():
        logger.warning(
            "Token refresh landed on a non-NotebookLM page; refusing to persist session tokens (build=%s)",
            invalid_build_label or "unknown",
        )
        return False

    meta = _load_meta()
    updated = False

    # f.sid — try known key variants in order of likelihood
    for key in ("IxjpMA", "FdrFJe"):
        if wiz.get(key):
            meta["f_sid"] = str(wiz[key])
            updated = True
            logger.debug("Extracted f.sid from WIZ_global_data.%s", key)
            break

    # at anti-forgery token
    if wiz.get("SNlM0e"):
        meta["at"] = wiz["SNlM0e"]
        updated = True
        logger.debug("Extracted at from WIZ_global_data.SNlM0e")

    # bl — try WIZ_global_data keys, then fall back to boq_ string scan
    # Only accept values that look like real build labels (boq_ prefix)
    for key in ("QrtxK", "cfb2h"):
        val = wiz.get(key)
        if val and isinstance(val, str) and _is_valid_nlm_build_label(val):
            new_bl = val
            if new_bl != meta.get("bl"):
                meta["bl"] = new_bl
                updated = True
                logger.info("Updated build label from WIZ_global_data.%s: %s", key, new_bl)
            break
    else:
        bl_match = re.search(r'"(boq_labs-tailwind-frontend_[^"]+)"', html)
        if bl_match:
            new_bl = bl_match.group(1)
            if new_bl != meta.get("bl"):
                meta["bl"] = new_bl
                updated = True
                logger.info("Updated build label from HTML scan: %s", new_bl)

    if updated:
        _save_meta(meta)
        logger.info(
            "Session tokens refreshed: f.sid=%s at_present=%s bl=%s",
            meta.get("f_sid"), bool(meta.get("at")), meta.get("bl"),
        )
    else:
        logger.warning(
            "refresh_session_tokens: no tokens found in page "
            "(WIZ keys present: %s)", list(wiz.keys())[:10] if wiz else "none"
        )
    return updated


# ════════════════════════════════════════════════════════════════════════════
# COOKIE MANAGEMENT
#
# Google auth requires a set of session cookies.  The critical ones are:
#   SID, SSID, APISID, SAPISID  — core Google session tokens
#   __Secure-3PSID, __Secure-3PAPISID  — same-site secure variants
#   HSID  — security cookie preventing CSRF
#   NID   — Google preference cookie (sometimes needed for API calls)
#
# Cookies are stored in data/nlm_cookies.json (thread-safe via _COOKIES_LOCK).
# Obtain them via: HAR import, CDP capture, or DevTools manual copy.
#
# The SAPISIDHASH in the Authorization header is derived from SAPISID:
#   SHA1(unix_timestamp + " " + SAPISID + " " + "https://notebooklm.google.com")
# This is a Google-wide anti-abuse mechanism; without it, API calls return 401.
# ════════════════════════════════════════════════════════════════════════════

def _load_cookies() -> Dict[str, str]:
    """Load stored Google auth cookies from disk."""
    with _COOKIES_LOCK:
        if not _COOKIES_FILE.exists():
            return {}
        try:
            return json.loads(_COOKIES_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load NLM cookies: %s", exc)
            return {}


def _save_cookies(cookies: Dict[str, str]) -> None:
    """Persist Google auth cookies to disk."""
    _COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _COOKIES_LOCK:
        _COOKIES_FILE.write_text(
            json.dumps(cookies, indent=2), encoding="utf-8"
        )


def extract_cookies_from_har(har_path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Extract Google auth cookies AND metadata (bl, f.sid) from a HAR file.

    Looks for requests to notebooklm.google.com and extracts:
    - Auth cookies sent with requests
    - Build label (bl) from URL parameters
    - Session ID (f.sid) from URL parameters

    Args:
        har_path: Path to the .har file.

    Returns:
        Tuple of (cookies_dict, meta_dict) where meta has keys 'bl', 'f_sid', 'at'.
    """
    try:
        with open(har_path, "r", encoding="utf-8", errors="replace") as fh:
            har = json.load(fh)
    except Exception as exc:
        logger.error("Could not read HAR file %s: %s", har_path, exc)
        return {}, {}

    cookies: Dict[str, str] = {}
    meta: Dict[str, str] = {}

    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        if _NLM_HOST not in url:
            continue

        # Extract bl and f.sid from batchexecute URLs
        if "batchexecute" in url:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if "bl" in params and not meta.get("bl"):
                meta["bl"] = params["bl"][0]
                logger.info("Extracted bl from HAR: %s", meta["bl"])
            if "f.sid" in params and not meta.get("f_sid"):
                meta["f_sid"] = params["f.sid"][0]
                logger.info("Extracted f.sid from HAR: %s", meta["f_sid"])
            # Extract 'at' anti-forgery token from POST body
            if not meta.get("at"):
                post_data = entry.get("request", {}).get("postData", {})
                post_text = post_data.get("text", "")
                if post_text:
                    parsed_body = urllib.parse.parse_qs(post_text)
                    if "at" in parsed_body:
                        meta["at"] = parsed_body["at"][0]
                        logger.info("Extracted at token from HAR postData")

        # Cookies in request headers
        for header in entry.get("request", {}).get("headers", []):
            if header.get("name", "").lower() == "cookie":
                for part in header["value"].split(";"):
                    part = part.strip()
                    if "=" in part:
                        name, _, value = part.partition("=")
                        cookies[name.strip()] = value.strip()
        # Cookies as structured objects
        for c in entry.get("request", {}).get("cookies", []):
            if isinstance(c, dict) and c.get("name"):
                cookies[c["name"]] = c.get("value", "")

        # Also check response Set-Cookie headers for fresh tokens
        for header in entry.get("response", {}).get("headers", []):
            if header.get("name", "").lower() == "set-cookie":
                parts = header["value"].split(";")[0].strip()
                if "=" in parts:
                    name, _, value = parts.partition("=")
                    cookies[name.strip()] = value.strip()

    # Keep only the auth-relevant Google session cookies
    _AUTH_PREFIXES = ("SID", "SSID", "APISID", "SAPISID", "HSID", "OSID",
                      "__Secure-", "NID", "1P_JAR", "AEC", "SOCS",
                      "CONSENT", "SEARCH_SAMESITE", "LSID", "SIDCC")
    filtered = {k: v for k, v in cookies.items()
                if any(k.startswith(p) for p in _AUTH_PREFIXES)}
    logger.info("Extracted %d auth cookies from HAR (kept %d after filter)",
                len(cookies), len(filtered))
    return filtered, meta


def _cookies_header(cookies: Dict[str, str]) -> str:
    """Format cookies dict as HTTP Cookie header value."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _sapisid_hash(cookies: Dict[str, str]) -> str:
    """Compute the SAPISIDHASH Authorization header value.

    Google requires this header on all notebooklm.google.com API requests.
    Without it, batchexecute returns HTTP 401.

    Algorithm (Google-standard, same across Maps/Docs/NLM):
      1. Extract SAPISID cookie value (fallback: __Secure-3PAPISID).
      2. Build raw string: "<unix_ts> <sapisid_value> <origin>"
      3. SHA-1 hash the raw string.
      4. Return "SAPISIDHASH <unix_ts>_<hex_digest>"

    The timestamp is included in both the raw string AND the header value so
    the server can verify freshness (tokens older than ~30 minutes are rejected).

    Args:
        cookies: Google auth cookies dict (must contain SAPISID or __Secure-3PAPISID).

    Returns:
        Authorization header value string, or "" if no SAPISID found.
    """
    import hashlib
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID", "")
    if not sapisid:
        return ""
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} https://{_NLM_HOST}"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


# ════════════════════════════════════════════════════════════════════════════
# BATCHEXECUTE TRANSPORT LAYER
#
# All NLM read and most write operations go through Google's generic
# batchexecute endpoint.  This section contains the HTTP plumbing:
#
#   _build_headers()         — constructs required HTTP headers incl. SAPISIDHASH
#   _batchexecute()          — single RPC call (thin wrapper around _multi)
#   _batchexecute_multi()    — multi-RPC batched call (core transport function)
#
# Key implementation details:
#   • All calls go through the rate limiter (_rate_limiter.wait()).
#   • The f.req body is URL-encoded JSON (not raw JSON).
#   • The 'at' anti-forgery token is included in the POST body when available.
#   • If ALL results are null, an automatic single retry is made after
#     refreshing the f.sid and at tokens from the live NLM page.
#   • The source-path URL parameter sets the notebook context for NLM's
#     server-side session tracking (affects source-scoped calls).
# ════════════════════════════════════════════════════════════════════════════

def _build_headers(cookies: Dict[str, str]) -> Dict[str, str]:
    """Build the HTTP headers required for NLM batchexecute requests.

    HAR analysis (2026-03-01) confirmed the real Chrome browser does NOT send
    an Authorization: SAPISIDHASH header — NLM batchexecute authenticates via
    Cookie + 'at' CSRF token in the POST body only.  Adding SAPISIDHASH causes
    HTTP 400 (error code 3 in the er response block).

    The sec-fetch-* headers are required for CORS compliance.
    """
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/145.0.0.0 Safari/537.36"),
        "Referer": f"https://{_NLM_HOST}/",
        "Origin": f"https://{_NLM_HOST}",
        "X-Same-Domain": "1",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-browser-channel": "stable",
        "x-browser-year": "2026",
        "DNT": "1",
    }
    if cookies:
        headers["Cookie"] = _cookies_header(cookies)
        # NOTE: Do NOT add Authorization: SAPISIDHASH here.
        # NLM batchexecute authenticates via Cookie + 'at' body token only.
        # SAPISIDHASH is used by other Google APIs (Maps, Docs) but causes 400 on NLM.
    return headers


def _batchexecute(
    rpc_id: str,
    args_json: str,
    cookies: Dict[str, str],
    notebook_id: str = "",
) -> Tuple[Optional[str], Any]:
    """Make a single batchexecute RPC call to NotebookLM.

    Thin convenience wrapper around _batchexecute_multi for the common single-RPC
    case.  Prefer _batchexecute_multi directly when sending multiple RPCs to
    amortise the HTTP overhead.

    The ``notebook_id`` is passed as ``source-path=/notebook/<id>`` in the URL
    query string.  NLM uses this for server-side notebook context scoping —
    some RPCs (LIST_SOURCES, SAVE_NOTE, etc.) require the correct notebook_id
    here or they silently return null data.

    Args:
        rpc_id:      The RPC function ID (e.g. ``"VfAZjd"``, ``"CYK0Xb"``).
        args_json:   JSON-stringified argument array (e.g. ``'["nb_id", [2]]'``).
        cookies:     Google auth cookies dict (from ``_load_cookies()``).
        notebook_id: Optional notebook UUID for the ``source-path`` URL param.
                     Pass ``""`` for account-level RPCs (LIST_NOTEBOOKS, USER_QUOTA).

    Returns:
        Tuple of ``(rpc_id_returned, parsed_inner_data)``.
        Returns ``(None, None)`` on complete failure.
        Returns ``(None, {"error": ..., "detail": ...})`` on HTTP errors.
    """
    results = _batchexecute_multi(
        [(rpc_id, args_json)], cookies, notebook_id
    )
    if results:
        return results[0]
    return None, None


def _batchexecute_multi(
    calls: List[Tuple[str, str]],
    cookies: Dict[str, str],
    notebook_id: str = "",
    _refreshed: bool = False,
) -> List[Tuple[Optional[str], Any]]:
    """Make multiple batchexecute RPC calls in a single HTTP request.

    This is the core transport function.  All other batchexecute helpers
    ultimately call this.

    Batching mechanics:
      Multiple RPC calls are packed into a single POST by putting them all in
      the ``f.req`` array.  The server processes each independently and returns
      a ``wrb.fr`` block per call in the response.  Up to ~10 calls per request
      is safe; NLM seems to silently drop extras beyond that.

    The ``f.req`` body format (confirmed from HAR, SDK v3.0):
      ``[["rpc_id_1", "args_json_1", null, "generic"], ["rpc_id_2", ...], ...]``
      This is URL-encoded as: ``f.req=<url_encoded_json_array>``

    The ``at`` anti-forgery token is included in the POST body when present.
    If not present (fresh install with no page load yet), omit it entirely —
    including a blank ``at`` causes 403.

    Auto-retry on stale tokens:
      If ALL returned results are ``None``, it means the bl or f.sid is stale.
      The function calls ``refresh_session_tokens()`` once and retries the
      entire batch.  The ``_refreshed`` flag prevents infinite recursion.

    The ``source-path`` URL parameter:
      Set to ``/notebook/<notebook_id>`` when a notebook_id is provided.
      This tells NLM which notebook the call is scoped to — critical for
      source-scoped RPCs.  Set to ``/`` for account-level calls.

    Args:
        calls:       List of ``(rpc_id, args_json)`` tuples.
        cookies:     Google auth cookies dict.
        notebook_id: Optional notebook UUID for the ``source-path`` URL param.
        _refreshed:  Internal flag — do not pass; prevents refresh infinite loop.

    Returns:
        List of ``(rpc_id_returned, parsed_inner_data)`` tuples, one per call,
        in the same order as the input ``calls`` list.
        On error, returns ``[(None, {"error": ..., "detail": ...})]`` repeated.
    """
    if not calls:
        return []

    # ── Build the request URL ──────────────────────────────────────────────
    bl = _get_bl()
    fsid = _get_fsid()
    req_id = str(int(time.time()) % 100000 * 100)

    # rpcids param: semicolon-separated when batching multiple RPCs.
    # NLM uses this for routing/logging — must match the RPCs in f.req exactly.
    rpc_ids_param = ";".join(rpc_id for rpc_id, _ in calls)

    params: Dict[str, str] = {
        "rpcids": rpc_ids_param,
        # source-path scopes the call to a specific notebook on the server side.
        # Without it, source-scoped RPCs (wXbhsf, CYK0Xb, etc.) return null.
        "source-path": f"/notebook/{notebook_id}" if notebook_id else "/",
        "bl": bl,        # build label — must match current frontend deploy
        "f.sid": fsid,   # server session ID extracted from WIZ_global_data
        "hl": "en",
        "_reqid": req_id,
        "rt": "c",       # response type "c" = chunked / wrb.fr format
    }
    url = f"{_BATCH_URL}?" + urllib.parse.urlencode(params)

    # ── Pack all calls into a single f.req array ───────────────────────────
    # Format: [["rpc_id", "args_json", null, "generic"], ...]
    # The 3rd element (null) and 4th element ("generic") are required padding
    # observed in every HAR capture — their meaning is not fully understood,
    # but omitting them causes the server to reject the request.
    # HAR-confirmed format (2026-03-01): f.req must be triple-nested.
    # Correct:  [[[rpc_id, args, null, "generic"], ...]]   ← three levels
    # Wrong:    [[rpc_id, args, null, "generic"], ...]     ← two levels (causes HTTP 400)
    f_req_calls = [[[rpc_id, args_json, None, "generic"] for rpc_id, args_json in calls]]
    body_dict: Dict[str, str] = {"f.req": json.dumps(f_req_calls)}

    # Include 'at' anti-forgery token if available.
    # Do NOT send a blank at= — that causes HTTP 403.  Omit entirely if missing.
    at_token = _load_meta().get("at", "")
    if at_token:
        body_dict["at"] = at_token
    body = urllib.parse.urlencode(body_dict).encode()

    headers = _build_headers(cookies)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    # Enforce rate limit before every outbound NLM call
    _rate_limiter.set_gap(_get_rate_limit())
    _rate_limiter.wait()

    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace") if exc.fp else ""
        status = exc.code
        logger.error("batchexecute HTTP %s for %s: %s", status, rpc_ids_param, body_text[:200])
        err = {"error": f"HTTP {status}", "detail": body_text[:500]}
        if status == 401:
            err["detail"] = "Auth expired — import a new HAR or capture cookies via CDP"
        return [(None, err)] * len(calls)
    except (urllib.error.URLError, OSError) as exc:
        logger.error("batchexecute connection error for %s: %s", rpc_ids_param, exc)
        err = {"error": "connection_error", "detail": str(exc)}
        return [(None, err)] * len(calls)

    results = _parse_batchexecute_multi(raw)

    # ── Auto-retry on stale tokens ─────────────────────────────────────────
    # If every result is None (not an error dict, just None), the bl or f.sid
    # is almost certainly stale — NLM returns a valid 200 but with empty data.
    # We refresh tokens once and retry.  _refreshed=True prevents a second loop.
    if not _refreshed and all(data is None for _, data in results):
        logger.info("All batchexecute results null — refreshing session tokens and retrying")
        if refresh_session_tokens():
            return _batchexecute_multi(calls, cookies, notebook_id, _refreshed=True)

    return results



# ════════════════════════════════════════════════════════════════════════════
# RESPONSE PARSING
#
# batchexecute responses have three layers of wrapping to unwrap:
#   Layer 1: XSSI prefix  )]}'  on the first line — always strip this.
#   Layer 2: Outer JSON   [["wrb.fr", "rpc_id", "<inner_json_str>", ...], ...]
#   Layer 3: Inner JSON   the actual RPC result, double-encoded as a string.
#
# The response body may contain multiple wrb.fr blocks (one per batched call),
# each on its own line.  Non-wrb.fr lines (e.g. size hints) are ignored.
#
# Parse strategy:
#   1. Strip the )]}'  XSSI prefix and leading whitespace.
#   2. Split on newlines.
#   3. For each line that starts with [["wrb.fr": parse as JSON.
#   4. Extract outer[0][1] = rpc_id, outer[0][2] = inner_json_string.
#   5. JSON-decode the inner string to get the actual result.
# ════════════════════════════════════════════════════════════════════════════

def _parse_batchexecute_multi(raw: str) -> List[Tuple[Optional[str], Any]]:
    """Decode ALL batchexecute wrb.fr blocks from a multi-RPC response.

    Handles Google's three-layer batchexecute response format:

    Layer 1 — XSSI prefix:
      The response always starts with ``)]}'`` followed by a newline.
      This is Google's standard Cross-Site Script Inclusion (XSSI) protection.
      Strip it before any JSON parsing.

    Layer 2 — Outer envelope (one line per RPC call):
      ``[["wrb.fr", "rpc_id", "<inner_json_string>", null, null, null, "generic"], ...]``
      Each batched call produces exactly one such line.
      Lines that do NOT start with ``[["wrb.fr"`` are size hints or padding — skip.

    Layer 3 — Inner data (double-encoded JSON string):
      ``outer[0][2]`` is a JSON string that must be decoded a second time.
      After decoding, ``inner`` is the actual RPC result array.

    Args:
        raw: Raw HTTP response body string from batchexecute.

    Returns:
        List of ``(rpc_id, parsed_data)`` tuples in response order.
        Returns ``[(None, None)]`` if no wrb.fr blocks found (unexpected format).
    """
    results: List[Tuple[Optional[str], Any]] = []
    # ── Strip XSSI prefix ─────────────────────────────────────────────────
    # Google prepends )]}'  to all batchexecute responses as XSSI protection.
    # Must strip before any JSON parsing — json.loads will fail otherwise.
    body = raw.lstrip(")]}'").lstrip("\n")
    for line in body.split("\n"):
        line = line.strip()
        # Only process wrb.fr blocks — skip size hints, empty lines, padding
        if not line.startswith('[["wrb.fr"'):
            continue
        try:
            outer = json.loads(line)
            rpc_id = outer[0][1]
            inner_raw = outer[0][2]
            inner = json.loads(inner_raw) if isinstance(inner_raw, str) else inner_raw
            results.append((rpc_id, inner))
        except (json.JSONDecodeError, IndexError, TypeError):
            continue
    return results or [(None, None)]


def _parse_batchexecute(raw: str) -> Tuple[Optional[str], Any]:
    """Decode a single batchexecute response (backward compat wrapper)."""
    results = _parse_batchexecute_multi(raw)
    return results[0] if results else (None, None)


# ════════════════════════════════════════════════════════════════════════════
# CONTENT EXTRACTION UTILITIES
#
# Generic helpers for mining structured data out of deeply nested NLM responses.
# NLM responses are irregular — the same data can appear at different nesting
# depths depending on the RPC version and content type.  These helpers use
# recursive traversal to find strings and structured source objects regardless
# of exact position.
# ════════════════════════════════════════════════════════════════════════════

def _extract_strings(obj: Any, min_len: int = 80) -> List[str]:
    """Recursively extract all meaningful text strings from nested NLM response data.

    NLM response structures are irregular — useful text can appear at arbitrary
    nesting depths.  This helper does a depth-first walk and collects strings
    that pass two filters:
      1. Length >= min_len (avoids UUIDs, short labels, empty strings).
      2. Not a UUID-like hex string (avoids source IDs and session tokens).

    Args:
        obj:     Any nested Python object (list, dict, str, int, …).
        min_len: Minimum string length to keep (default 80 chars).

    Returns:
        List of matching strings in traversal order.
    """
    results: List[str] = []
    if isinstance(obj, str):
        s = obj.strip()
        if len(s) >= min_len and not re.match(r"^[a-f0-9-]{30,}$", s):
            results.append(s)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_extract_strings(item, min_len))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(_extract_strings(v, min_len))
    return results


def _dedup(texts: List[str], key_len: int = 120) -> List[str]:
    """Deduplicate a list of strings using the first ``key_len`` characters as the key.

    NLM sometimes returns the same text block at multiple nesting levels.
    This removes duplicates while preserving the first-seen order.

    Args:
        texts:   List of strings to deduplicate.
        key_len: Number of leading characters used as the uniqueness key.

    Returns:
        Deduplicated list in original order.
    """
    seen: set = set()
    return [t for t in texts if t[:key_len] not in seen and not seen.add(t[:key_len])]  # type: ignore[func-returns-value]


def _extract_sources(data: Any) -> Tuple[str, List[Dict]]:
    """Parse a wXbhsf (LIST_SOURCES) response into notebook name + sources list.

    wXbhsf response shape (confirmed from HAR, v3.1):
      data[0][0]       = nb_core
      nb_core[0]       = notebook_name (str)
      nb_core[1]       = list of source objects
      source[0][0]     = source UUID
      source[1]        = source title (str)
      source[2]        = source metadata list:
        meta[1]        = word_count (int, 0 if still processing)
        meta[6]        = source_type (int: 1=URL, 2=PDF, 3=text, 7=YouTube, …)
        meta[7]        = url_list ([url_str, ...])

    Args:
        data: Parsed inner data from a wXbhsf batchexecute response.

    Returns:
        Tuple of ``(notebook_name, sources_list)`` where each source is a dict
        with keys: id, title, url, word_count, source_type.
    """
    notebook_name = ""
    sources = []
    try:
        nb_core = data[0][0]
        notebook_name = nb_core[0] if isinstance(nb_core[0], str) else ""
        src_list = nb_core[1] if len(nb_core) > 1 and isinstance(nb_core[1], list) else []
        for src in src_list:
            if not isinstance(src, list) or len(src) < 2:
                continue
            try:
                uid   = src[0][0] if isinstance(src[0], list) and src[0] else ""
                title = src[1] if isinstance(src[1], str) else ""
                url   = ""
                word_count = 0
                src_type   = None
                if len(src) > 2 and isinstance(src[2], list):
                    meta = src[2]
                    word_count = meta[1] if len(meta) > 1 and isinstance(meta[1], int) else 0
                    src_type   = meta[6] if len(meta) > 6 else None
                    if len(meta) > 7 and isinstance(meta[7], list) and meta[7]:
                        url = meta[7][0] if isinstance(meta[7][0], str) else ""
                sources.append({
                    "id": uid, "title": title, "url": url,
                    "word_count": word_count, "source_type": src_type,
                })
            except (IndexError, TypeError):
                continue
    except (IndexError, TypeError) as exc:
        logger.warning("parse sources: %s", exc)
    return notebook_name, sources


# ════════════════════════════════════════════════════════════════════════════
# WRITE OPERATION HELPERS
#
# Module-level functions for all NLM write (and some read) operations.
# Each function maps to a specific confirmed RPC ID.
# These are called both directly and via the NLMClient class methods.
#
# Write RPCs confirmed in v3.1:
#   CYK0Xb (SAVE_NOTE)           — citation-annotate Q&A
#   s0tc2d (RENAME_NOTEBOOK)     — CRITICAL: was wrong in v2.x
#   izAoDd (ADD_SOURCE)          — add URL/YouTube source
#   tGMBJ  (DELETE_SOURCE)       — delete source by UUID
#   QA9ei  (START_DEEP_RESEARCH) — start async deep research
#   LBwxtb (ADD_RESEARCH_SOURCE) — add AI-generated doc as source
#   ciyUvf (GENERATE_DOC)        — generate document from sources
#   R7cb6c (SAVE_REPORT)         — save note artifact
#
# Read RPCs also in this section (for grouping convenience):
#   tr032e (READ_SOURCE)         — read full source text content
#   GenerateFreeFormStreamed      — real conversational chat (proto endpoint)
# ════════════════════════════════════════════════════════════════════════════

def ask_question(
    notebook_id: str,
    question: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Ask a single question using CYK0Xb (citation-annotate mode).

    CYK0Xb annotates the provided text with source citations from the notebook.
    This is best for Q&A distillation where you want cited answers.

    Args:
        notebook_id: UUID of the target notebook.
        question:    The question/context text to annotate.
        cookies:     Google auth cookies.

    Returns:
        Dict with keys: answer_id, answer (markdown with [citations]), sources.
    """
    args = json.dumps([notebook_id, question])
    _, data = _batchexecute(RPC_CREATE_NOTE, args, cookies, notebook_id)
    return _parse_ask_response(data)


def rename_notebook(
    notebook_id: str,
    new_name: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Rename a notebook using s0tc2d (RENAME_NOTEBOOK RPC).

    Confirmed v3.1 from HAR analysis: s0tc2d is the rename RPC, NOT chat.
    Payload: [notebook_id, [[null, null, null, [null, "new_name"]]]]
    Response: [new_name, null, notebook_id, emoji, ...]

    Args:
        notebook_id: UUID of the notebook to rename.
        new_name:    The new title for the notebook.
        cookies:     Google auth cookies.

    Returns:
        Dict with: renamed (bool), notebook_id, name.
    """
    args = json.dumps([notebook_id, [[None, None, None, [None, new_name]]]])
    _, data = _batchexecute(RPC_RENAME_NOTEBOOK, args, cookies, notebook_id)
    return _parse_rename_response(data, notebook_id, new_name)


def _parse_rename_response(
    data: Any,
    notebook_id: str,
    new_name: str = "",
) -> Dict[str, Any]:
    """Parse an s0tc2d (RENAME_NOTEBOOK) response.

    Response structure: [name, null, notebook_id, emoji, ...]
    """
    if data is None:
        return {"renamed": False, "notebook_id": notebook_id, "name": new_name,
                "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"renamed": False, "notebook_id": notebook_id, "name": new_name, **data}
    try:
        if isinstance(data, list) and len(data) >= 3:
            returned_name = data[0] if isinstance(data[0], str) else new_name
            returned_id = data[2] if isinstance(data[2], str) else notebook_id
            return {"renamed": True, "notebook_id": returned_id, "name": returned_name}
    except (IndexError, TypeError) as exc:
        logger.warning("parse rename response: %s | data=%s", exc, str(data)[:200])
    return {"renamed": True, "notebook_id": notebook_id, "name": new_name}


def add_source_url(
    notebook_id: str,
    url: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Add a URL or YouTube video as a source using izAoDd (ADD_SOURCE RPC).

    Confirmed v3.1 from HAR analysis:
    - Regular URL: source object with URL at position 2
    - YouTube URL: source object with [url] at position 7
    Same RPC handles both — detected automatically via URL pattern.

    Payload: [[[source_obj]], notebook_id, [2], _SOURCE_CONFIG]

    Args:
        notebook_id: UUID of the target notebook.
        url:         HTTP/HTTPS URL or YouTube URL to add as source.
        cookies:     Google auth cookies.

    Returns:
        Dict with: source_id (UUID or None), url, status ("processing").
    """
    # ── YouTube vs regular URL source object encoding ─────────────────────
    # The izAoDd source object has 11 positional slots.  The URL goes in a
    # different position depending on content type — confirmed from HAR:
    #   Regular URL → position 2  (direct string)
    #   YouTube URL → position 7  (wrapped in a list: [url])
    # Using the wrong position causes NLM to silently ignore the URL and
    # create an empty source.  The [2] in the outer payload's 3rd element
    # is the "add mode" flag (2 = add to existing notebook).
    is_youtube = bool(re.search(r"youtube\.com/watch|youtu\.be/", url))
    if is_youtube:
        source_obj = [None, None, None, None, None, None, None, [url], None, None, 1]
    else:
        source_obj = [None, None, url, None, None, None, None, None, None, None, 1]
    args = json.dumps([[source_obj], notebook_id, [2], _SOURCE_CONFIG])
    _, data = _batchexecute(RPC_ADD_SOURCE, args, cookies, notebook_id)
    return _parse_add_source_response(data, url)


def _parse_add_source_response(data: Any, url: str = "") -> Dict[str, Any]:
    """Parse an izAoDd (ADD_SOURCE) response.

    Response contains the new source UUID and processing status.
    """
    if data is None:
        return {"source_id": None, "url": url, "status": "queued", "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"source_id": None, "url": url, "status": "error", **data}
    source_id = None
    try:
        for s in _extract_strings(data, min_len=36):
            if re.match(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", s):
                source_id = s
                break
    except Exception as exc:
        logger.debug("parse add_source: %s", exc)
    return {"source_id": source_id, "url": url, "status": "processing"}


def add_text_source(
    notebook_id: str,
    title: str,
    content: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Add an inline text/markdown source to a notebook via izAoDd RPC.

    Confirmed from HAR 2026-03-01 (notebooklm_manual_testing.har).
    Text sources use position 1 = ["title", "content"] and position 3 = 3
    (format type for paste/text), unlike URL sources which use position 2.

    Args:
        notebook_id: Target notebook UUID.
        title:       Display name for the source.
        content:     Markdown or plain-text content (can be large).
        cookies:     Google auth cookies.

    Returns:
        Dict with source_id on success, or error dict on failure.
    """
    # Build the source object: pos[1]=[title,content], pos[3]=3 (text format)
    # Confirmed payload structure from HAR (notebooklm_manual_testing.har, 2026-02-28):
    # [[null, ["title", "content"], null, 3, null,null,null,null,null,null, 1]],
    #   notebook_id, [2], [1,null,null,null,null,null,null,null,null,null,[1]]]
    # Note: source_obj is wrapped in ONE list [source_obj], not [[source_obj]].
    # Double-wrapping causes INVALID_ARGUMENT ([3] in wrb.fr pos[5]).
    source_obj = [None, [title, content], None, 3, None, None, None, None, None, None, 1]
    args = json.dumps([
        [source_obj],
        notebook_id,
        [2],
        [1, None, None, None, None, None, None, None, None, None, [1]],
    ], separators=(",", ":"))

    _rpc_id, data = _batchexecute(RPC_ADD_SOURCE, args, cookies, notebook_id)
    if data is None:
        return {"error": "null_response", "detail": "No data returned from add_text_source"}
    if isinstance(data, dict) and data.get("error"):
        return data

    # Response mirrors add_source_url — extract first source_id from data[0][0][0]
    try:
        source_id = data[0][0][0]
        return {"source_id": source_id, "title": title, "status": "added"}
    except (TypeError, IndexError, KeyError):
        return {"source_id": None, "title": title, "status": "added", "raw": data}


def poll_source_status(
    notebook_id: str,
    cookies: Dict[str, str],
    first_poll: bool = True,
) -> Dict[str, Any]:
    """Poll source processing status for a notebook via rLM1Ne RPC.

    Confirmed from HAR 2026-03-01. Called repeatedly after adding sources
    until all sources are indexed. last arg 0 = first poll, 1 = continuing.

    Args:
        notebook_id: Target notebook UUID.
        cookies:     Google auth cookies.
        first_poll:  True for first call (arg[4]=0), False for subsequent (arg[4]=1).

    Returns:
        Dict with processing status info.
    """
    poll_flag = 0 if first_poll else 1
    args = json.dumps([notebook_id, None, [2], None, poll_flag], separators=(",", ":"))
    _rpc_id, data = _batchexecute(RPC_SOURCE_STATUS, args, cookies, notebook_id)
    if data is None:
        return {"error": "null_response"}
    if isinstance(data, dict) and data.get("error"):
        return data
    return {"status": "ok", "data": data}


def wait_for_sources(
    notebook_id: str,
    cookies: Dict[str, str],
    timeout: int = 120,
    poll_interval: float = 3.0,
) -> bool:
    """Poll rLM1Ne until all sources are processed or timeout reached.

    Args:
        notebook_id:   Target notebook UUID.
        cookies:       Google auth cookies.
        timeout:       Maximum seconds to wait (default 120).
        poll_interval: Seconds between polls (default 3.0).

    Returns:
        True if sources appear ready, False on timeout.
    """
    import time as _time
    deadline = _time.time() + timeout
    first = True
    while _time.time() < deadline:
        result = poll_source_status(notebook_id, cookies, first_poll=first)
        first = False
        # If data contains no pending indicators, consider it done.
        # rLM1Ne returns null data when all sources are ready.
        data = result.get("data")
        if data is None:
            return True
        # Check for any active processing indicators (non-null nested lists)
        try:
            if not any(item for item in data if item is not None):
                return True
        except TypeError:
            pass
        _time.sleep(poll_interval)
    logger.warning("wait_for_sources timed out after %ss for notebook %s", timeout, notebook_id)
    return False


def register_file_sources(
    notebook_id: str,
    filenames: List[str],
    cookies: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Register filenames for upload and get source IDs via o4cbdc RPC.

    Step 1 of 2 for file upload. After calling this, upload each file's
    bytes to POST /upload/_/?authuser=0 using the returned source_id as
    the upload identifier.

    Confirmed from HAR 2026-03-01. Payload: [[[fn1],[fn2]], nb_id, [2], [1,...,[1]]]
    Response: [[source_id], filename, [null,null,null,null,0]] per file.

    Args:
        notebook_id: Target notebook UUID.
        filenames:   List of filenames (e.g. ["ARCHITECTURE.md", "API.md"]).
        cookies:     Google auth cookies.

    Returns:
        List of dicts: [{source_id, filename}]
    """
    fn_list = [[fn] for fn in filenames]
    args = json.dumps([
        fn_list,
        notebook_id,
        [2],
        [1, None, None, None, None, None, None, None, None, None, [1]],
    ], separators=(",", ":"))

    _rpc_id, data = _batchexecute(RPC_REGISTER_FILES, args, cookies, notebook_id)
    if data is None:
        return [{"error": "null_response", "filename": fn} for fn in filenames]
    if isinstance(data, dict) and data.get("error"):
        return [{"error": data, "filename": fn} for fn in filenames]

    results = []
    try:
        # data[0] = list of [[[source_id], filename, [...]]]
        entries = data[0]
        for item in entries:
            source_id = item[0][0] if item[0] else None
            fname = item[1] if len(item) > 1 else None
            results.append({"source_id": source_id, "filename": fname})
    except (TypeError, IndexError):
        results = [{"source_id": None, "filename": fn, "raw": data} for fn in filenames]
    return results


def upload_file_to_nlm(
    filename: str,
    content_bytes: bytes,
    cookies: Dict[str, str],
    mime_type: str = "text/plain",
) -> Dict[str, Any]:
    """Upload file bytes to NotebookLM via the resumable upload endpoint.

    2-step process confirmed from HAR 2026-03-01:
      Step 1: POST /upload/_/?authuser=0  (no body or empty body) → X-GUploader header = upload_id
      Step 2: POST /upload/_/?authuser=0&upload_id=<id>  (with file bytes) → 'OK: Enqueued...'

    Args:
        filename:      Original filename (for Content-Disposition).
        content_bytes: Raw file bytes to upload.
        cookies:       Google auth cookies.
        mime_type:     MIME type (default text/plain; use text/markdown for .md files).

    Returns:
        Dict with upload_id and status.
    """
    _rate_limiter.set_gap(_get_rate_limit())
    _rate_limiter.wait()

    cookie_str = _cookies_header(cookies)
    base_url = f"https://{_NLM_HOST}/upload/_/?authuser=0"
    upload_headers = {
        "Cookie": cookie_str,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
        "Origin": f"https://{_NLM_HOST}",
        "Referer": f"https://{_NLM_HOST}/",
        "X-Same-Domain": "1",
    }

    # Step 1: register upload, get upload_id from X-GUploader response header
    try:
        req1 = urllib.request.Request(base_url, data=b"", headers=upload_headers, method="POST")
        with urllib.request.urlopen(req1, timeout=30) as resp1:
            upload_id = resp1.headers.get("X-GUploader-UploadID") or resp1.headers.get("x-guploader-uploadid", "")
            _ = resp1.read()
    except Exception as exc:
        return {"error": "upload_register_failed", "detail": str(exc)}

    if not upload_id:
        return {"error": "no_upload_id", "detail": "Step 1 did not return X-GUploader header"}

    # Step 2: upload file bytes
    upload_url = f"{base_url}&upload_id={upload_id}"
    upload_headers["Content-Type"] = mime_type
    upload_headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    upload_headers["Content-Length"] = str(len(content_bytes))

    try:
        req2 = urllib.request.Request(upload_url, data=content_bytes, headers=upload_headers, method="POST")
        with urllib.request.urlopen(req2, timeout=60) as resp2:
            body = resp2.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"error": "upload_bytes_failed", "detail": str(exc), "upload_id": upload_id}

    return {
        "upload_id": upload_id,
        "filename": filename,
        "status": "enqueued" if "Enqueued" in body else "uploaded",
        "response": body,
    }


def create_note(
    notebook_id: str,
    title: str,
    content_html: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Create a new note in a notebook via CYK0Xb RPC.

    Confirmed from HAR 2026-03-01 (addnote-saveresptonote-convsource.har).
    Also used for "save AI response to note" — pass the AI response markdown
    as content_html to save it directly as a note.

    Payload: [nb_id, content_html, [1], null, title, null, [2]]
    Response: [[note_id, content, [1, version_id, [ts_sec, ts_nano]], null, title]]

    Args:
        notebook_id:  Target notebook UUID.
        title:        Note title.
        content_html: Note body as HTML string (e.g. "<p>Hello world</p>").
                      Pass empty string "" for a blank note.
        cookies:      Google auth cookies.

    Returns:
        Dict with note_id, title, and status.
    """
    args = json.dumps(
        [notebook_id, content_html, [1], None, title, None, [2]],
        separators=(",", ":"),
    )
    _rpc_id, data = _batchexecute(RPC_CREATE_NOTE, args, cookies, notebook_id)
    if data is None:
        return {"error": "null_response", "detail": "No data from create_note"}
    if isinstance(data, dict) and data.get("error"):
        return data
    try:
        note = data[0]
        note_id = note[0]
        return {"note_id": note_id, "title": title, "status": "created"}
    except (TypeError, IndexError):
        return {"note_id": None, "title": title, "status": "created", "raw": data}


def save_note(
    notebook_id: str,
    note_id: str,
    title: str,
    content_html: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Save/update a note's content via cYAfTb RPC (live auto-save).

    Confirmed from HAR 2026-03-01. This is the same RPC NLM fires on every
    keystroke as you type. Safe to call as often as needed.

    Payload: [nb_id, note_id, [[["<html>", "title", [], 0]]], [2]]
    Response: [[note_id, content, [1, version_id, [ts_sec, ts_nano]], null, title]]

    Note: Previously this constant was incorrectly labelled GET_SOURCE_STATUS_DETAIL.
    The payload structure was misread — pos[2][0] = ["html","title",[],0], not source status.

    Args:
        notebook_id:  Target notebook UUID.
        note_id:      UUID of the note to update.
        title:        Note title (can be unchanged).
        content_html: New HTML content for the note.
        cookies:      Google auth cookies.

    Returns:
        Dict with note_id, title, and status.
    """
    args = json.dumps(
        [notebook_id, note_id, [[[content_html, title, [], 0]]], [2]],
        separators=(",", ":"),
    )
    _rpc_id, data = _batchexecute(RPC_SAVE_NOTE, args, cookies, notebook_id)
    if data is None:
        return {"error": "null_response"}
    if isinstance(data, dict) and data.get("error"):
        return data
    try:
        note = data[0]
        return {"note_id": note[0], "title": title, "status": "saved"}
    except (TypeError, IndexError):
        return {"note_id": note_id, "title": title, "status": "saved", "raw": data}


def get_source_summary(
    source_id: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Get an AI-generated markdown summary of a source via tr032e RPC.

    Confirmed from HAR 2026-03-01. NEW RPC — never seen in prior HAR captures.
    Called with just a source_id; returns a full markdown summary generated by NLM.
    Extremely useful for indexing source content without reading the raw text.

    Payload: [[[[source_id]]]]
    Response: [[[[source_id]], "### Markdown summary text..."]]

    Args:
        source_id: UUID of the source to summarize.
        cookies:   Google auth cookies.

    Returns:
        Dict with source_id, summary (markdown), and status.
    """
    args = json.dumps([[[[source_id]]]], separators=(",", ":"))
    _rpc_id, data = _batchexecute(RPC_GET_SOURCE_SUMMARY, args, cookies)
    if data is None:
        return {"error": "null_response"}
    if isinstance(data, dict) and data.get("error"):
        return data
    try:
        summary = data[0][1] if data[0] and len(data[0]) > 1 else str(data)
        return {"source_id": source_id, "summary": summary, "status": "ok"}
    except (TypeError, IndexError):
        return {"source_id": source_id, "summary": None, "status": "ok", "raw": data}


def get_audio_options(
    notebook_id: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """List available audio overview formats via sqTeoe RPC.

    Confirmed from HAR 2026-03-01. Returns the list of audio types:
    1=Deep dive, 2=Brief, 3=Critique, 4=Debate.

    Payload: [[2,null,null,[1,null,null,null,null,null,null,null,null,null,[1]],[[2,1]]],null,1]

    Args:
        notebook_id: Target notebook UUID (used in request context).
        cookies:     Google auth cookies.

    Returns:
        Dict with options list [{id, label, description}].
    """
    args = json.dumps(
        [[2, None, None, [1, None, None, None, None, None, None, None, None, None, [1]], [[2, 1]]], None, 1],
        separators=(",", ":"),
    )
    _rpc_id, data = _batchexecute(RPC_GET_AUDIO_OPTIONS, args, cookies, notebook_id)
    if data is None:
        return {"error": "null_response"}
    if isinstance(data, dict) and data.get("error"):
        return data
    try:
        raw_options = data[0][0][0]
        options = [
            {"id": opt[0], "label": opt[1], "description": opt[2]}
            for opt in raw_options
        ]
        return {"options": options, "status": "ok"}
    except (TypeError, IndexError):
        return {"options": [], "status": "ok", "raw": data}


def sync_notes(
    notebook_id: str,
    cookies: Dict[str, str],
    prev_timestamp: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Poll for note changes since a given timestamp via cFji9 RPC.

    Confirmed from HAR 2026-03-01. NLM uses this as a delta sync — on first
    call (no prev_timestamp) returns all notes. Subsequent calls return only
    notes changed since prev_timestamp. Returns a new timestamp for the next poll.

    Payload: [nb_id, null, [prev_ts_sec, prev_ts_nano], [2]]  (or [nb_id, null, null, [2]] first call)
    Response: [[[note_id, note_object], ...], [current_ts_sec, current_ts_nano]]

    Args:
        notebook_id:    Target notebook UUID.
        cookies:        Google auth cookies.
        prev_timestamp: [sec, nanosec] from last sync response. None for first call.

    Returns:
        Dict with notes list and next_timestamp for continued polling.
    """
    args = json.dumps(
        [notebook_id, None, prev_timestamp, [2]],
        separators=(",", ":"),
    )
    _rpc_id, data = _batchexecute(RPC_SYNC_NOTES, args, cookies, notebook_id)
    if data is None:
        return {"notes": [], "next_timestamp": None}
    if isinstance(data, dict) and data.get("error"):
        return data
    try:
        notes_raw = data[0] if data else []
        next_ts = data[1] if len(data) > 1 else None
        notes = []
        for entry in (notes_raw or []):
            if entry and len(entry) >= 2:
                note_obj = entry[1]
                notes.append({
                    "note_id": note_obj[0] if note_obj else entry[0],
                    "content": note_obj[1] if note_obj and len(note_obj) > 1 else None,
                    "title": note_obj[4] if note_obj and len(note_obj) > 4 else None,
                })
        return {"notes": notes, "next_timestamp": next_ts, "status": "ok"}
    except (TypeError, IndexError):
        return {"notes": [], "next_timestamp": None, "status": "ok", "raw": data}


def ask_questions_batch(
    notebook_id: str,
    questions: List[str],
    cookies: Dict[str, str],
    max_batch: int = 5,
) -> List[Dict[str, Any]]:
    """Ask multiple questions using CYK0Xb (citation-annotate) in batches.

    Packs up to max_batch CYK0Xb calls per HTTP request. This is the primary
    Q&A distillation method — answers come back with inline source citations.

    Args:
        notebook_id: UUID of the target notebook.
        questions:   List of question/context strings.
        cookies:     Google auth cookies.
        max_batch:   Max questions per HTTP request (default 5).

    Returns:
        List of answer dicts in the same order as questions.
    """
    results: List[Dict[str, Any]] = []
    for i in range(0, len(questions), max_batch):
        batch = questions[i:i + max_batch]
        calls = [
            (RPC_CREATE_NOTE, json.dumps([notebook_id, q]))
            for q in batch
        ]
        raw_results = _batchexecute_multi(calls, cookies, notebook_id)
        for _, data in raw_results:
            results.append(_parse_ask_response(data))
    return results


def _parse_ask_response(data: Any) -> Dict[str, Any]:
    """Parse a CYK0Xb response into a structured answer dict.

    Args:
        data: Parsed inner data from batchexecute response.

    Returns:
        Dict with: answer_id, answer (markdown text), sources (list).
    """
    if data is None:
        return {"answer_id": None, "answer": "", "sources": [], "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"answer_id": None, "answer": "", "sources": [], **data}
    try:
        # CYK0Xb returns [[answer_id, markdown_answer_with_citations], ...]
        answer_id = None
        answer_text = ""
        sources: List[str] = []

        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, list) and len(first) >= 2:
                answer_id = first[0] if isinstance(first[0], str) else None
                answer_text = first[1] if isinstance(first[1], str) else ""
                # Extract source IDs from citation markers in answer
                sources = re.findall(r"\[([a-f0-9-]{36})\]", answer_text)

        return {
            "answer_id": answer_id,
            "answer": answer_text,
            "sources": sources,
        }
    except (IndexError, TypeError) as exc:
        logger.warning("parse ask response: %s | data=%s", exc, str(data)[:200])
        return {"answer_id": None, "answer": "", "sources": [],
                "error": str(exc), "raw": str(data)[:500]}


def delete_source(
    source_id: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Delete a source from a notebook using tGMBJ (DELETE_SOURCE RPC).

    Confirmed v3.1 from HAR analysis.
    Payload: [[[source_id]], [2]]

    Args:
        source_id: UUID of the source to delete.
        cookies:   Google auth cookies.

    Returns:
        Dict with: deleted (bool), source_id.
    """
    args = json.dumps([[[source_id]], [2]])
    _, data = _batchexecute(RPC_DELETE_SOURCE, args, cookies)
    ok = data is not None and not (isinstance(data, dict) and "error" in data)
    return {"deleted": ok, "source_id": source_id}


def start_deep_research(
    notebook_id: str,
    topic: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Start a deep research session on a topic using QA9ei.

    Confirmed v3.1 from HAR analysis (was wrongly assumed to be Add Text Source).
    Payload: [null, [1], ["topic", 1], 5, notebook_id]
    Returns a session_id UUID. NLM then asynchronously generates a research
    document which is added as a source via add_research_source (LBwxtb).

    Args:
        notebook_id: UUID of the target notebook.
        topic:       The research topic or question.
        cookies:     Google auth cookies.

    Returns:
        Dict with: session_id (UUID), topic, notebook_id.
    """
    args = json.dumps([None, [1], [topic, 1], 5, notebook_id])
    _, data = _batchexecute(RPC_START_DEEP_RESEARCH, args, cookies, notebook_id)
    session_id = None
    if data is not None:
        try:
            for s in _extract_strings(data, min_len=36):
                if re.match(
                    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", s
                ):
                    session_id = s
                    break
        except Exception as exc:
            logger.debug("start_deep_research session_id parse: %s", exc)
    return {"session_id": session_id, "topic": topic, "notebook_id": notebook_id}


def add_research_source(
    notebook_id: str,
    session_id: str,
    title: str,
    content: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Add an AI-generated research document as a source using LBwxtb.

    Confirmed v3.1 from HAR analysis. Fires after start_deep_research (QA9ei)
    with the AI-written document as payload.
    Payload: [null, [1], session_id, notebook_id, [[null, [title, content]]]]

    Args:
        notebook_id: UUID of the target notebook.
        session_id:  Session ID returned by start_deep_research.
        title:       Title of the research document.
        content:     Full text content of the research document.
        cookies:     Google auth cookies.

    Returns:
        Dict with: source_id (UUID or None), title, session_id, notebook_id.
    """
    sources_array = [[None, [title, content]]]
    args = json.dumps([None, [1], session_id, notebook_id, sources_array])
    _, data = _batchexecute(RPC_ADD_RESEARCH_SOURCE, args, cookies, notebook_id)
    source_id = None
    if data is not None:
        try:
            for s in _extract_strings(data, min_len=36):
                if re.match(
                    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", s
                ):
                    source_id = s
                    break
        except Exception as exc:
            logger.debug("add_research_source parse: %s", exc)
    return {
        "source_id": source_id,
        "title": title,
        "session_id": session_id,
        "notebook_id": notebook_id,
    }


def _grpc_ask(
    notebook_id: str,
    question: str,
    source_ids: List[str],
    cookies: Dict[str, str],
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask a free-form question via the gRPC GenerateFreeFormStreamed endpoint.

    This is the REAL chat interface — confirmed v3.1 from HAR analysis.
    Unlike CYK0Xb (citation-annotate), this triggers NLM's conversational
    Gemini model for natural dialogue. Supports multi-turn conversation via
    thread_id.

    Endpoint: POST /GenerateFreeFormStreamed?bl=<bl>
    Inner payload (9 elements):
      [0] source_context: [[[src_id1]], [[src_id2]], ...]
      [1] question text
      [2] null
      [3] [2, null, [1], [1]]  — response config
      [4] thread UUID (existing thread or new UUID for new conversation)
      [5] null
      [6] null
      [7] notebook UUID
      [8] 1
    Outer: [null, json.dumps(inner)]
    Body: f.req=<url_encoded_outer>

    Response: SSE-like streaming. Each chunk has FULL text so far (not deltas).
    Parse pattern: outer[0] == "wrb.fr" → inner_str → inner[0][0] = full text.

    Args:
        notebook_id: UUID of the target notebook.
        question:    The question to ask.
        source_ids:  All source UUIDs for the notebook (required by NLM).
        cookies:     Google auth cookies.
        thread_id:   Existing thread UUID for multi-turn, or None for new.

    Returns:
        Dict with: answer (full text), thread_id, message_id, question, sources.
    """
    import urllib.parse as _urlparse

    if thread_id is None:
        import uuid
        thread_id = str(uuid.uuid4())

    meta = _load_meta()
    bl = meta.get("bl", _DEFAULT_BL)

    source_context = [[[sid]] for sid in source_ids]
    # ── Build the GenerateFreeFormStreamed inner payload ───────────────────
    # 9-element array confirmed from HAR — positions documented in module docstring.
    # source_context: each source is wrapped as [[[uuid]]] — triple-nested.
    # response_config [2,None,[1],[1]]: controls response length/citation style.
    # thread_id at position [4]: pass existing UUID for multi-turn continuity.
    inner = [
        source_context,  # [0] source context: [[[src_id_1]], [[src_id_2]], ...]
        question,         # [1] the user's question text
        None,             # [2] null (reserved)
        [2, None, [1], [1]],  # [3] response config (length/format flags)
        thread_id,        # [4] thread UUID for conversation continuity
        None,             # [5] null (reserved)
        None,             # [6] null (reserved)
        notebook_id,      # [7] notebook UUID
        1,                # [8] request type flag
    ]
    # The outer wrapper is [null, json.dumps(inner)] — the inner is double-encoded
    outer = json.dumps([None, json.dumps(inner)])
    params = _urlparse.urlencode({"bl": bl, "rt": "c"})
    url = _GRPC_CHAT_URL + "?" + params
    body = ("f.req=" + _urlparse.quote(outer)).encode()

    hdrs = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "Origin": "https://notebooklm.google.com",
        "Referer": f"https://notebooklm.google.com/notebook/{notebook_id}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
    }

    _rate_limiter.wait()

    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    full_text = ""
    returned_thread_id = thread_id
    returned_msg_id = None

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        # ── SSE-like streaming response parse ──────────────────────────────
        # GenerateFreeFormStreamed returns chunked SSE-like data.
        # Each chunk is delivered as two lines: a hex size hint, then a JSON line.
        # We read the full response body at once (no incremental streaming here)
        # because urllib reads it all before returning.
        #
        # IMPORTANT: NLM delivers FULL TEXT IN EACH CHUNK, not deltas.
        # Each wrb.fr block contains the complete answer text generated so far.
        # We therefore only need the LAST wrb.fr block — but iterating all of
        # them and overwriting full_text is equivalent and simpler.
        #
        # Each JSON line structure:
        #   [["wrb.fr", null, "<inner_json_str>"], ["di", ...], ...]
        #   inner_data = json.loads(inner_json_str)
        #   inner_data[0][0]    = full answer text so far (str)
        #   inner_data[0][2]    = [thread_id, message_id]  (on final chunk)
        for line in raw.splitlines():
            line = line.strip()
            # Skip empty lines, the )]}'  XSSI prefix, and hex size lines
            if not line or line == ")]}'" or re.match(r"^[0-9a-f]+$", line, re.I):
                continue
            try:
                chunk = json.loads(line)
                for item in chunk:
                    if not (isinstance(item, list) and len(item) >= 3):
                        continue
                    if item[0] != "wrb.fr" or not item[2]:
                        continue
                    inner_data = json.loads(item[2])
                    if not (isinstance(inner_data, list) and inner_data):
                        continue
                    first = inner_data[0]
                    if not isinstance(first, list):
                        continue
                    # full text so far at position 0
                    if first and isinstance(first[0], str):
                        full_text = first[0]
                    # thread/message IDs at position 2
                    if len(first) > 2 and isinstance(first[2], list):
                        ids = first[2]
                        if len(ids) >= 1 and ids[0]:
                            returned_thread_id = ids[0]
                        if len(ids) >= 2 and ids[1]:
                            returned_msg_id = ids[1]
            except (json.JSONDecodeError, IndexError, TypeError):
                pass

    except Exception as exc:
        logger.warning("_grpc_ask error: %s", exc)
        return {
            "answer": "",
            "thread_id": thread_id,
            "message_id": None,
            "question": question,
            "sources": [],
            "error": str(exc),
        }

    return {
        "answer": full_text,
        "thread_id": returned_thread_id,
        "message_id": returned_msg_id,
        "question": question,
        "sources": source_ids,
    }


def grpc_ask_batch(
    notebook_id: str,
    questions: List[str],
    source_ids: List[str],
    cookies: Dict[str, str],
    thread_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Ask multiple questions sequentially via GenerateFreeFormStreamed.

    Each question reuses the same thread_id so responses are in context.
    For independent questions use thread_id=None (each call starts fresh thread).

    Args:
        notebook_id: UUID of the target notebook.
        questions:   List of question strings.
        source_ids:  All source UUIDs for the notebook.
        cookies:     Google auth cookies.
        thread_id:   Thread UUID for linked conversation, or None for independent.

    Returns:
        List of grpc_ask response dicts in question order.
    """
    results: List[Dict[str, Any]] = []
    current_thread = thread_id
    for q in questions:
        result = _grpc_ask(notebook_id, q, source_ids, cookies, current_thread)
        results.append(result)
        # Continue thread across questions if thread_id was provided or carry forward
        if thread_id is not None:
            current_thread = result.get("thread_id", current_thread)
    return results


def read_source(
    source_id: str,
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """Read the full text content of a notebook source (tr032e RPC).

    Returns the complete markdown-formatted text of a source document.
    This is powerful for offline analysis — you can extract all content
    from NLM sources into Nexus without re-uploading.

    Args:
        source_id: UUID of the source to read.
        cookies:   Google auth cookies.

    Returns:
        Dict with: source_id, content (markdown text), word_count.
    """
    args = json.dumps([[[[source_id]]]])
    _, data = _batchexecute(RPC_READ_SOURCE, args, cookies)
    return _parse_read_source_response(data, source_id)


def _parse_read_source_response(data: Any, source_id: str) -> Dict[str, Any]:
    """Parse a tr032e (READ_SOURCE) response into source content dict.

    tr032e wraps the source text in a nested structure that varies slightly by
    source type (PDF, URL, YouTube transcript, etc.).  We use _extract_strings
    with a low min_len to catch all content fragments, then join them.

    Args:
        data:      Parsed inner data from a tr032e batchexecute response.
        source_id: UUID of the source (echoed into the return dict).

    Returns:
        Dict with: source_id, content (joined markdown text), word_count.
    """
    if data is None:
        return {"source_id": source_id, "content": "", "word_count": 0, "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"source_id": source_id, "content": "", "word_count": 0, **data}
    texts = _extract_strings(data, min_len=10)
    content = "\n\n".join(texts)
    return {
        "source_id": source_id,
        "content": content,
        "word_count": len(content.split()),
    }


# ════════════════════════════════════════════════════════════════════════════
# DOWNLOAD & ARCHIVE OPERATIONS
#
# High-level operations that combine multiple RPCs to produce complete exports.
#
#   download_all_sources()   — fetch full text of all sources (tr032e loop)
#   export_notebook()        — full notebook archive (summary + sources + notes
#                              + threads + mindmap) in a single structured dict
#   export_all_notebooks()   — export every notebook for the authenticated user
#
# These are the primary integration points for Nexus ingestion and offline
# analysis.  Source content reading is rate-limited per the global limiter.
# ════════════════════════════════════════════════════════════════════════════

def download_all_sources(
    notebook_id: str,
    cookies: Dict[str, str],
    source_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Download the full text content of all sources in a notebook (tr032e RPC).

    Workflow:
      1. If ``source_ids`` is None, fetch the source list via wXbhsf to get
         all source UUIDs and their metadata (title, url, source_type).
      2. Call ``read_source()`` (tr032e) for each source UUID individually.
         Each call respects the rate limiter (1.5s default gap).
      3. Return a combined list with both metadata and full text content.

    Use this to extract all NLM source content into Nexus or local storage
    for offline analysis, fine-tuning data collection, or archival.

    Performance note: Large notebooks with many sources will be slow due to
    the rate limiter.  A 20-source notebook takes ~30s minimum at 1.5s/call.

    Args:
        notebook_id: UUID of the target notebook.
        cookies:     Google auth cookies.
        source_ids:  Optional list of specific source UUIDs to read. If None,
                     reads ALL sources in the notebook.

    Returns:
        List of dicts: [{source_id, title, url, source_type, word_count, content, error}, ...]
        where ``content`` is the full markdown text of the source.
        ``error`` is present (and non-None) only if tr032e failed for that source.
    """
    if source_ids is None:
        args = json.dumps([None, 1, None, [2]])
        _, data = _batchexecute(RPC_LIST_SOURCES, args, cookies, notebook_id)
        _, sources = _extract_sources(data) if data and not isinstance(data, dict) else ("", [])
        source_ids = [s["id"] for s in sources if s.get("id")]
        source_meta = {s["id"]: s for s in sources if s.get("id")}
    else:
        source_meta = {}

    results = []
    for sid in source_ids:
        meta = source_meta.get(sid, {"id": sid, "title": "", "url": ""})
        content_result = read_source(sid, cookies)
        results.append({
            "source_id": sid,
            "title": meta.get("title", ""),
            "url": meta.get("url", ""),
            "source_type": meta.get("source_type"),
            "word_count": content_result.get("word_count", 0),
            "content": content_result.get("content", ""),
            "error": content_result.get("error"),
        })
    return results


def export_notebook(
    notebook_id: str,
    cookies: Dict[str, str],
    include_source_content: bool = True,
    include_threads: bool = True,
) -> Dict[str, Any]:
    """Export a complete notebook archive with all available data.

    Makes the following RPC calls in sequence (each rate-limited):
      1. VfAZjd  (AI_SUMMARY)     — notebook summary text
      2. wXbhsf  (LIST_SOURCES)   — source metadata list
      3. tr032e  (READ_SOURCE)    — full text per source (if include_source_content)
      4. gArtLc  (LIST_ARTIFACTS) — notes and saved artifacts
      5. hPTbtc  (GET_THREAD_IDS) — conversation thread UUIDs (if include_threads)
      6. khqZz   (READ_THREAD)    — messages per thread (if include_threads)
      7. cFji9   (MIND_MAP)       — D3 mind map JSON structure

    The resulting archive dict is self-contained and suitable for:
      - Storage in Nexus as a knowledge entry
      - Offline analysis without NLM access
      - Comparison between notebook versions
      - Fine-tuning dataset construction

    Performance: With include_source_content=True, this makes (2 + N + 3 + T)
    API calls where N = source count and T = thread count.  At 1.5s/call, a
    notebook with 10 sources and 5 threads takes ~30s minimum.

    Args:
        notebook_id:           UUID of the target notebook.
        cookies:               Google auth cookies.
        include_source_content: If True, read full text of each source via
                               tr032e (slow but complete). False = metadata only.
        include_threads:       If True, fetch and read all conversation threads.

    Returns:
        Dict with keys: notebook_id, notebook_name, summary, sources,
        notes, threads, mindmap, stats (counts + total_source_words), exported_at.
    """
    import datetime
    archive: Dict[str, Any] = {
        "notebook_id": notebook_id,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    # Summary
    _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]), cookies, notebook_id)
    archive["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

    # Sources with optional full content
    _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]), cookies, notebook_id)
    notebook_name, sources = _extract_sources(data) if data and not isinstance(data, dict) else ("", [])
    archive["notebook_name"] = notebook_name

    if include_source_content:
        sources_with_content = []
        for src in sources:
            if src.get("id"):
                content_result = read_source(src["id"], cookies)
                src["content"] = content_result.get("content", "")
                src["content_word_count"] = content_result.get("word_count", 0)
            sources_with_content.append(src)
        archive["sources"] = sources_with_content
    else:
        archive["sources"] = sources

    # Notes / artifacts
    _, data = _batchexecute(
        "gArtLc",
        json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""]),
        cookies, notebook_id,
    )
    notes = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
    archive["notes"] = [n for n in notes if len(n) > 50]

    # Conversation threads
    if include_threads:
        t_args = json.dumps([[], None, notebook_id, 50])
        _, t_data = _batchexecute(RPC_GET_THREAD_IDS, t_args, cookies, notebook_id)
        thread_ids: List[str] = []
        try:
            if isinstance(t_data, list) and t_data:
                for item in t_data[0]:
                    if isinstance(item, list) and item and isinstance(item[0], str):
                        thread_ids.append(item[0])
        except (IndexError, TypeError):
            pass

        threads = []
        for tid in thread_ids:
            m_args = json.dumps([[], None, None, tid, 50])
            _, m_data = _batchexecute(RPC_READ_THREAD, m_args, cookies, notebook_id)
            messages = [s for s in _extract_strings(m_data or [], min_len=10) if len(s) > 20]
            threads.append({"thread_id": tid, "messages": messages, "message_count": len(messages)})
        archive["threads"] = threads
    else:
        archive["threads"] = []

    # Mind map
    _, data = _batchexecute(RPC_MIND_MAP, json.dumps([notebook_id, None, None, [2]]), cookies, notebook_id)
    mindmap_raw = ""
    try:
        mindmap_raw = _extract_strings(data, min_len=5)[0] if data and _extract_strings(data, min_len=5) else ""
    except (IndexError, TypeError):
        pass
    try:
        archive["mindmap"] = json.loads(mindmap_raw)
    except (json.JSONDecodeError, TypeError):
        archive["mindmap"] = mindmap_raw or None

    archive["stats"] = {
        "sources": len(archive["sources"]),
        "notes": len(archive["notes"]),
        "threads": len(archive["threads"]),
        "total_source_words": sum(s.get("content_word_count", s.get("word_count", 0)) for s in archive["sources"]),
    }
    return archive


def export_all_notebooks(
    cookies: Dict[str, str],
    include_source_content: bool = False,
    include_threads: bool = True,
) -> Dict[str, Any]:
    """Export all notebooks for the authenticated user as a complete archive.

    Workflow:
      1. Call ub2Bae (LIST_NOTEBOOKS) to get all notebook UUIDs + names.
      2. Call export_notebook() for each notebook in sequence.
      3. Return a combined result dict.

    Source content is disabled by default for full-account exports because
    reading all sources across all notebooks can take many minutes.
    Set include_source_content=True only when you explicitly need all text
    (e.g., for full Nexus ingestion or training data collection).

    Error handling: Failed notebooks are included in the result with an
    "error" key instead of crashing the entire export.

    Args:
        cookies:                Google auth cookies.
        include_source_content: Read full source text per source per notebook.
                               Disabled by default for large accounts.
        include_threads:        Read conversation threads for each notebook.

    Returns:
        Dict with: count (total notebooks), notebooks (list of archives), exported_at.
        Each archive follows the export_notebook() return structure.
    """
    import datetime
    _, data = _batchexecute(RPC_LIST_NOTEBOOKS, "[[2]]", cookies)
    notebook_ids: List[Dict[str, str]] = []
    try:
        for nb in (data[0] if isinstance(data, list) and data else []):
            if isinstance(nb, list):
                nid = None
                for part in nb:
                    if isinstance(part, str) and re.match(r"[a-f0-9-]{36}", part):
                        nid = part
                        break
                texts = _extract_strings(nb, min_len=5)
                if nid:
                    notebook_ids.append({"id": nid, "name": texts[0] if texts else "Unknown"})
    except (IndexError, TypeError) as exc:
        logger.warning("export_all_notebooks: list parse error: %s", exc)

    notebooks = []
    for nb_meta in notebook_ids:
        try:
            archive = export_notebook(
                nb_meta["id"], cookies,
                include_source_content=include_source_content,
                include_threads=include_threads,
            )
            archive["notebook_name"] = archive.get("notebook_name") or nb_meta["name"]
            notebooks.append(archive)
        except Exception as exc:
            logger.error("export_all_notebooks: failed for %s: %s", nb_meta["id"], exc)
            notebooks.append({
                "notebook_id": nb_meta["id"],
                "notebook_name": nb_meta["name"],
                "error": str(exc),
            })

    return {
        "count": len(notebooks),
        "notebooks": notebooks,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def get_user_quota(cookies: Dict[str, str]) -> Dict[str, Any]:
    """Fetch user account info and storage quota (ozz5Z RPC).

    Returns quota usage, plan type, and account metadata.

    Args:
        cookies: Google auth cookies.

    Returns:
        Dict with: raw_data (nested structure), extracted_text.
    """
    args = json.dumps([[[[None, "1", 627],
                         [None, None, None, None, None, None, None,
                          None, None, [None, None, 4]],
                         1]]])
    _, data = _batchexecute(RPC_USER_QUOTA, args, cookies)
    if data is None or (isinstance(data, dict) and "error" in data):
        return data or {"error": "no_data"}
    texts = _extract_strings(data, min_len=5)
    return {"quota_data": data, "extracted": texts[:10]}


def get_user_plan(cookies: Dict[str, str]) -> Dict[str, Any]:
    """Fetch user plan/tier and quota limits (ZwVcOc RPC).

    Returns current plan name, daily query allowance, and remaining queries.

    Args:
        cookies: Google auth cookies.

    Returns:
        Dict with: plan_name, daily_limit, queries_remaining, raw_data.
    """
    args = json.dumps([None, [2]])
    _, data = _batchexecute(RPC_USER_PLAN, args, cookies)
    if data is None or (isinstance(data, dict) and "error" in data):
        return data or {"error": "no_data"}

    result: Dict[str, Any] = {"raw_data": data}
    try:
        texts = _extract_strings(data, min_len=3)
        ints = [x for x in _walk_ints(data)]

        # Heuristic: plan name is the first string of length > 3
        if texts:
            result["plan_name"] = texts[0]

        # daily_limit and queries_remaining are typically integers in the payload
        if len(ints) >= 2:
            result["daily_limit"] = ints[0]
            result["queries_remaining"] = ints[1]
        elif len(ints) == 1:
            result["queries_remaining"] = ints[0]
    except Exception:
        pass

    return result


def _walk_ints(obj: Any) -> List[int]:
    """Recursively extract all integers from a nested structure."""
    results: List[int] = []
    if isinstance(obj, int) and not isinstance(obj, bool):
        results.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_walk_ints(item))
    return results


def generate_document(
    notebook_id: str,
    source_ids: List[str],
    cookies: Dict[str, str],
    doc_type: int = 2,
) -> Dict[str, Any]:
    """Generate a document/report from selected sources (ciyUvf RPC).

    Args:
        notebook_id: UUID of the target notebook.
        source_ids:  List of source UUIDs to include in the document.
        cookies:     Google auth cookies.
        doc_type:    Document type integer (2=standard, 9=deep research).

    Returns:
        Dict with: title, description, source_ids.
    """
    source_array = [[sid] for sid in source_ids]
    args = json.dumps([_WRITE_CONFIG, notebook_id, source_array])
    _, data = _batchexecute(RPC_GENERATE_DOC, args, cookies, notebook_id)
    return _parse_generate_response(data, source_ids)


def _parse_generate_response(data: Any, source_ids: List[str]) -> Dict[str, Any]:
    """Parse a ciyUvf response."""
    if data is None:
        return {"title": "", "description": "", "source_ids": source_ids, "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"title": "", "description": "", "source_ids": source_ids, **data}
    try:
        # ciyUvf returns [[title, description, null, [[source_id], ...]], ...]
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, list):
                title = first[0] if isinstance(first[0], str) else ""
                description = first[1] if len(first) > 1 and isinstance(first[1], str) else ""
                return {"title": title, "description": description, "source_ids": source_ids}
    except (IndexError, TypeError) as exc:
        logger.warning("parse generate: %s", exc)
    return {"title": "", "description": "", "source_ids": source_ids}


def save_note_report(
    notebook_id: str,
    source_ids: List[str],
    cookies: Dict[str, str],
    note_type: int = 2,
) -> Dict[str, Any]:
    """Create/save a note artifact in a notebook (R7cb6c RPC).

    Args:
        notebook_id: UUID of the target notebook.
        source_ids:  List of source UUIDs to associate with the note.
        cookies:     Google auth cookies.
        note_type:   Note type (2=standard note, 9=deep research).

    Returns:
        Dict with: note_id, title, note_type.
    """
    # Build nested source array as observed in HAR: [[[src_id]], [[src_id]], ...]
    source_array = [[sid] for sid in source_ids]
    note_body = [None, None, note_type, source_array]
    args = json.dumps([_WRITE_CONFIG, notebook_id, note_body])
    _, data = _batchexecute(RPC_SAVE_REPORT, args, cookies, notebook_id)
    return _parse_save_note_response(data)


def _parse_save_note_response(data: Any) -> Dict[str, Any]:
    """Parse an R7cb6c response."""
    if data is None:
        return {"note_id": None, "title": "", "note_type": 2, "error": "no_data"}
    if isinstance(data, dict) and "error" in data:
        return {"note_id": None, "title": "", "note_type": 2, **data}
    try:
        # R7cb6c returns [[note_id, title, type_int, [[source_ids]]], ...]
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, list) and len(first) >= 3:
                note_id = first[0] if isinstance(first[0], str) else None
                title = first[1] if isinstance(first[1], str) else ""
                note_type = first[2] if isinstance(first[2], int) else 2
                return {"note_id": note_id, "title": title, "note_type": note_type}
    except (IndexError, TypeError) as exc:
        logger.warning("parse save_note: %s", exc)
    return {"note_id": None, "title": "", "note_type": 2}


# ════════════════════════════════════════════════════════════════════════════
# NLMClient CLASS
#
# High-level object-oriented API over all module-level batchexecute helpers.
# This is the primary interface for CosySim agents and nlm_engine.py.
#
# Auth (cookies + meta) is managed via the module-level global store
# (data/nlm_cookies.json, data/nlm_meta.json) — the client itself is stateless.
#
# Method groups:
#   Auth:        get_cookies, has_cookies, import_cookies_from_har,
#                capture_cookies_from_chrome
#   Notebooks:   list_notebooks, get_notebook, get_sources, get_chat_history,
#                get_notes
#   Ask/Chat:    ask, ask_batch, grpc_ask, grpc_ask_batch
#                chat / chat_batch (backward-compat aliases → grpc_ask*)
#   Write:       rename, add_source, delete_source, deep_research,
#                deep_research_with_source
#   Generate:    generate_document, save_note
#   Read:        read_source, get_summary, get_user_quota
#   Status:      get_status
# ════════════════════════════════════════════════════════════════════════════

class NLMClient:
    """High-level NotebookLM client wrapping all batchexecute RPCs.

    Provides a clean class-based API over the module-level helper functions.
    Used by nlm_engine.py and any caller that needs direct NLM access.
    Delegates to module-level functions and uses the global cookie/meta store.
    """

    # ── Auth ──────────────────────────────────────────────────────────────

    def get_cookies(self) -> Dict[str, Any]:
        """Load cookies from disk. Returns empty dict if none."""
        return _load_cookies()

    def has_cookies(self) -> bool:
        """Return True if auth cookies are present."""
        return bool(_load_cookies())

    def import_cookies_from_har(self, har_path: str) -> Dict[str, Any]:
        """Extract and save cookies from a HAR file.

        Args:
            har_path: Path to the .har file.

        Returns:
            Dict with imported count, total count, and meta fields.
        """
        new_cookies, new_meta = extract_cookies_from_har(har_path)
        existing = _load_cookies()
        merged = {**existing, **new_cookies}
        _save_cookies(merged)
        existing_meta = _load_meta()
        if new_meta.get("bl"):
            existing_meta["bl"] = new_meta["bl"]
        if new_meta.get("f_sid"):
            existing_meta["f_sid"] = new_meta["f_sid"]
        if new_meta.get("at"):
            existing_meta["at"] = new_meta["at"]
            logger.info("import_cookies_from_har: updated at token from HAR")
        _save_meta(existing_meta)
        return {"imported": len(new_cookies), "total": len(merged), **existing_meta}

    def capture_cookies_from_chrome(self) -> Dict[str, Any]:
        """Auto-capture cookies from Chrome via CDP.

        Returns:
            Dict with captured cookie count and meta.
        """
        from engine.nexus.nlm_har_capture import capture_nlm_cookies
        return capture_nlm_cookies()

    # ── Notebooks ─────────────────────────────────────────────────────────

    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all notebooks for the authenticated user.

        Returns:
            List of notebook dicts with id and name.
        """
        cookies = _load_cookies()
        if not cookies:
            return []
        _, data = _batchexecute(RPC_LIST_NOTEBOOKS, "[[2]]", cookies)
        if not data or isinstance(data, dict):
            return []
        notebooks = []
        try:
            for nb in (data[0] if isinstance(data, list) and data else []):
                if isinstance(nb, list):
                    texts = _extract_strings(nb, min_len=5)
                    name = texts[0] if texts else "Unknown"
                    nid = None
                    for part in nb:
                        if isinstance(part, str) and re.match(r"[a-f0-9-]{36}", part):
                            nid = part
                            break
                    if nid:
                        notebooks.append({"id": nid, "name": name})
        except (IndexError, TypeError):
            pass
        return notebooks

    def get_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Get full notebook data: summary, sources, notes, conversations.

        Args:
            notebook_id: The notebook UUID.

        Returns:
            Dict with summary, sources, notes, conversations, and stats.
        """
        cookies = _load_cookies()
        result: Dict[str, Any] = {"notebook_id": notebook_id}
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]), cookies, notebook_id)
        result["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""
        _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]), cookies, notebook_id)
        if data and not isinstance(data, dict):
            result["notebook_name"], result["sources"] = _extract_sources(data)
        else:
            result["notebook_name"] = ""
            result["sources"] = []
        _, data = _batchexecute(
            "gArtLc",
            json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""]),
            cookies, notebook_id,
        )
        notes = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["notes"] = [n for n in notes if len(n) > 100]
        _, data = _batchexecute(RPC_SYNC_NOTES, json.dumps([notebook_id, None, None, [2]]), cookies, notebook_id)
        convos = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["conversations"] = [c for c in convos if len(c) > 100]
        result["stats"] = {
            "sources": len(result["sources"]),
            "notes": len(result["notes"]),
            "conversations": len(result["conversations"]),
        }
        return result

    def get_sources(self, notebook_id: str) -> List[Dict[str, Any]]:
        """List all sources in a notebook.

        Args:
            notebook_id: The notebook UUID.

        Returns:
            List of source dicts.
        """
        cookies = _load_cookies()
        _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]), cookies, notebook_id)
        if not data or isinstance(data, dict):
            return []
        _, sources = _extract_sources(data)
        return sources

    def get_chat_history(self, notebook_id: str, page_size: int = 20) -> List[Dict[str, Any]]:
        """Get conversation/chat history for a notebook (hPTbtc RPC).

        Args:
            notebook_id: The notebook UUID.
            page_size: Number of messages per page.

        Returns:
            List of conversation message dicts.
        """
        cookies = _load_cookies()
        args = json.dumps([[], None, notebook_id, page_size])
        _, data = _batchexecute(RPC_PENDING_SOURCES, args, cookies, notebook_id)
        if not data or isinstance(data, dict):
            return []
        messages = []
        try:
            for s in _extract_strings(data, min_len=20):
                if len(s) > 50:
                    messages.append({"content": s, "type": "message"})
        except (IndexError, TypeError):
            pass
        return messages

    def get_notes(self, notebook_id: str) -> List[str]:
        """Get all notes/artifacts for a notebook.

        Args:
            notebook_id: The notebook UUID.

        Returns:
            List of note text strings.
        """
        cookies = _load_cookies()
        args = json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""])
        _, data = _batchexecute(RPC_GET_ARTIFACTS, args, cookies, notebook_id)
        if not data or isinstance(data, dict):
            return []
        notes = _dedup(_extract_strings(data, 80))
        return [n for n in notes if len(n) > 100]

    # ── Ask / Chat ────────────────────────────────────────────────────────

    def ask(self, notebook_id: str, question: str) -> Dict[str, Any]:
        """Ask a single question using CYK0Xb (citation mode, synchronous).

        Args:
            notebook_id: The notebook UUID.
            question: The question to ask.

        Returns:
            Dict with answer_id, answer, and sources.
        """
        return ask_question(notebook_id, question, _load_cookies())

    def ask_batch(
        self, notebook_id: str, questions: List[str], max_batch: int = 5
    ) -> List[Dict[str, Any]]:
        """Ask multiple questions in batches using CYK0Xb.

        Args:
            notebook_id: The notebook UUID.
            questions: List of question strings.
            max_batch: Max questions per HTTP request.

        Returns:
            List of answer dicts in question order.
        """
        return ask_questions_batch(notebook_id, questions, _load_cookies(), max_batch)

    def rename(self, notebook_id: str, new_name: str) -> Dict[str, Any]:
        """Rename a notebook using s0tc2d (RENAME_NOTEBOOK RPC).

        Args:
            notebook_id: The notebook UUID.
            new_name: The new title for the notebook.

        Returns:
            Dict with renamed (bool), notebook_id, and name.
        """
        return rename_notebook(notebook_id, new_name, _load_cookies())

    def add_source(self, notebook_id: str, url: str) -> Dict[str, Any]:
        """Add a URL or YouTube video as a notebook source (izAoDd RPC).

        Args:
            notebook_id: The notebook UUID.
            url: HTTP/HTTPS URL or YouTube URL to add.

        Returns:
            Dict with source_id, url, and status.
        """
        return add_source_url(notebook_id, url, _load_cookies())

    def delete_source(self, source_id: str) -> Dict[str, Any]:
        """Delete a notebook source (tGMBJ RPC).

        Args:
            source_id: UUID of the source to delete.

        Returns:
            Dict with deleted (bool) and source_id.
        """
        return delete_source(source_id, _load_cookies())

    def deep_research(self, notebook_id: str, topic: str) -> Dict[str, Any]:
        """Start a deep research session (QA9ei RPC).

        Args:
            notebook_id: The notebook UUID.
            topic: The research topic or question.

        Returns:
            Dict with session_id, topic, and notebook_id.
        """
        return start_deep_research(notebook_id, topic, _load_cookies())

    def deep_research_with_source(
        self, notebook_id: str, topic: str, title: str, content: str
    ) -> Dict[str, Any]:
        """Start deep research and add the generated document as a source.

        Runs QA9ei (start_deep_research) then LBwxtb (add_research_source).

        Args:
            notebook_id: The notebook UUID.
            topic: The research topic.
            title: Title for the research document.
            content: Full text content of the research document.

        Returns:
            Dict with session_id, source_id, title, and notebook_id.
        """
        cookies = _load_cookies()
        research = start_deep_research(notebook_id, topic, cookies)
        session_id = research.get("session_id") or topic[:36]
        source = add_research_source(notebook_id, session_id, title, content, cookies)
        return {**research, **source}

    def grpc_ask(
        self,
        notebook_id: str,
        question: str,
        source_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Chat via GenerateFreeFormStreamed (real NLM chat, synchronous).

        Auto-fetches source IDs if not provided. Supports multi-turn conversation
        via thread_id.

        Args:
            notebook_id: The notebook UUID.
            question: The question to ask.
            source_ids: Source UUIDs (auto-fetched if None).
            thread_id: Thread UUID for multi-turn, or None for new conversation.

        Returns:
            Dict with answer, thread_id, message_id, question, sources.
        """
        cookies = _load_cookies()
        if source_ids is None:
            _, data = _batchexecute(
                RPC_LIST_SOURCES,
                json.dumps([None, 1, None, [2]]),
                cookies,
                notebook_id,
            )
            _, srcs = _extract_sources(data) if data and not isinstance(data, dict) else (None, [])
            source_ids = [s["id"] for s in srcs if s.get("id")]
        return _grpc_ask(notebook_id, question, source_ids, cookies, thread_id)

    def grpc_ask_batch(
        self,
        notebook_id: str,
        questions: List[str],
        source_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Ask multiple questions via GenerateFreeFormStreamed.

        Args:
            notebook_id: The notebook UUID.
            questions: List of question strings.
            source_ids: Source UUIDs (auto-fetched if None).
            thread_id: Thread UUID for linked conversation (None = independent).

        Returns:
            List of grpc_ask response dicts in question order.
        """
        cookies = _load_cookies()
        if source_ids is None:
            _, data = _batchexecute(
                RPC_LIST_SOURCES,
                json.dumps([None, 1, None, [2]]),
                cookies,
                notebook_id,
            )
            _, srcs = _extract_sources(data) if data and not isinstance(data, dict) else (None, [])
            source_ids = [s["id"] for s in srcs if s.get("id")]
        return grpc_ask_batch(notebook_id, questions, source_ids, cookies, thread_id)

    # Backward-compat aliases — old "chat" and "chat_batch" now delegate to grpc_ask

    def chat(
        self,
        notebook_id: str,
        question: str,
        thread_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Alias for grpc_ask (backward compat). Uses GenerateFreeFormStreamed."""
        return self.grpc_ask(notebook_id, question, source_ids, thread_id)

    def chat_batch(
        self,
        notebook_id: str,
        questions: List[str],
        thread_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Alias for grpc_ask_batch (backward compat). Uses GenerateFreeFormStreamed."""
        return self.grpc_ask_batch(notebook_id, questions, source_ids, thread_id)

    # ── Generate ──────────────────────────────────────────────────────────

    def generate_document(
        self, notebook_id: str, source_ids: List[str], doc_type: int = 2
    ) -> Dict[str, Any]:
        """Generate a document from notebook sources (ciyUvf RPC).

        Args:
            notebook_id: The notebook UUID.
            source_ids: List of source UUIDs to include.
            doc_type: Document type integer (2=standard, 9=deep research).

        Returns:
            Dict with title, description, and source_ids.
        """
        return generate_document(notebook_id, source_ids, _load_cookies(), doc_type)

    def save_note(
        self, notebook_id: str, source_ids: List[str], note_type: int = 2
    ) -> Dict[str, Any]:
        """Save a note artifact to a notebook (R7cb6c RPC).

        Args:
            notebook_id: The notebook UUID.
            source_ids: List of source UUIDs to associate.
            note_type: Note type (2=standard, 9=deep research).

        Returns:
            Dict with note_id, title, and note_type.
        """
        return save_note_report(notebook_id, source_ids, _load_cookies(), note_type)

    def read_source(self, source_id: str) -> Dict[str, Any]:
        """Read the full text content of a source (tr032e RPC).

        Args:
            source_id: UUID of the source to read.

        Returns:
            Dict with source_id, content, and word_count.
        """
        return read_source(source_id, _load_cookies())

    def get_summary(self, notebook_id: str) -> str:
        """Get the AI-generated overview/summary of a notebook (VfAZjd RPC).

        Args:
            notebook_id: The notebook UUID.

        Returns:
            Summary text string.
        """
        cookies = _load_cookies()
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]), cookies, notebook_id)
        return "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

    def get_user_quota(self) -> Dict[str, Any]:
        """Fetch user quota and account info (ozz5Z RPC).

        Returns:
            Dict with quota_data and extracted text.
        """
        return get_user_quota(_load_cookies())

    def get_user_plan(self) -> Dict[str, Any]:
        """Fetch user plan/tier and daily query allowance (ZwVcOc RPC).

        Returns:
            Dict with plan_name, daily_limit, queries_remaining.
        """
        return get_user_plan(_load_cookies())

    # ── Status ────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current auth and meta status.

        Returns:
            Dict with has_cookies, cookie_count, bl, bl_age_days, and bl_stale.
        """
        cookies = _load_cookies()
        meta = _load_meta()
        import datetime
        bl_age: Optional[int] = None
        try:
            updated_at = meta.get("bl_updated_at")
            if updated_at:
                bl_age = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(updated_at)
                ).days
        except Exception:
            pass
        return {
            "has_cookies": bool(cookies),
            "cookie_count": len(cookies),
            "bl": meta.get("bl", _DEFAULT_BL),
            "bl_age_days": bl_age,
            "bl_stale": bl_age is not None and bl_age >= 8,
            "rpc_catalog_version": "v3.1",
            "known_rpcs": 25,
        }


# ── NLMClient singleton ───────────────────────────────────────────────────

_nlm_client: Optional["NLMClient"] = None


def get_nlm_client() -> NLMClient:
    """Return the shared NLMClient singleton.

    Returns:
        The global NLMClient instance.
    """
    global _nlm_client
    if _nlm_client is None:
        _nlm_client = NLMClient()
    return _nlm_client


# ════════════════════════════════════════════════════════════════════════════
# FLASK APPLICATION
#
# REST API server for the NLM Live Proxy, running at :8800.
# All endpoints require valid Google session cookies to be stored first.
#
# Authentication:
#   POST /cookies/import   — import from HAR file (manual)
#   POST /cookies/capture  — auto-capture via Chrome CDP (preferred)
#   POST /cookies/refresh  — refresh f.sid and at tokens from live page
#   GET  /cookies          — list stored cookie names
#   DELETE /cookies        — clear all stored cookies
#
# Read operations:
#   GET  /notebooks                         — list all notebooks
#   GET  /notebooks/<id>                    — full notebook data
#   GET  /notebooks/<id>/sources            — list sources
#   GET  /notebooks/<id>/summary            — AI summary
#   GET  /notebooks/<id>/notes              — notes/artifacts
#   GET  /notebooks/<id>/conversations      — conversation history
#   GET  /notebooks/<id>/content            — raw document content
#   GET  /notebooks/<id>/threads            — thread IDs (hPTbtc)
#   GET  /notebooks/<id>/threads/<tid>      — thread messages (khqZz)
#   GET  /notebooks/<id>/mindmap            — D3 mind map (cFji9)
#   GET  /notebooks/<id>/history            — combined thread history
#   GET  /sources/<id>/content              — full source text (tr032e)
#   GET  /user/profile                      — user profile (JFMDGd)
#   GET  /user/quota                        — storage quota (ozz5Z)
#
# Write operations:
#   POST /notebooks                              — reserve new notebook UUID
#   POST /notebooks/<id>/sources                 — add URLs (izAoDd)
#   POST /notebooks/<id>/sources/url             — add single URL (izAoDd)
#   DELETE /notebooks/<id>/sources/<src_id>      — delete source (tGMBJ)
#   POST /notebooks/<id>/rename                  — rename (s0tc2d)
#   POST /notebooks/<id>/ask                     — Q&A via CYK0Xb
#   POST /notebooks/<id>/ask_batch               — batch Q&A via CYK0Xb
#   POST /notebooks/<id>/chat                    — chat via GenerateFreeFormStreamed
#   POST /notebooks/<id>/chat_batch              — batch chat via GenerateFreeFormStreamed
#   POST /notebooks/<id>/generate                — generate document (ciyUvf)
#   POST /notebooks/<id>/save_note               — save note artifact (R7cb6c)
#   POST /notebooks/<id>/research                — fast research (Ljjv0c)
#   POST /notebooks/<id>/research/deep           — deep research (QA9ei)
#   POST /notebooks/<id>/research/source         — add research doc (LBwxtb)
#   GET  /notebooks/<id>/sources/wait            — poll until sources ready (rLM1Ne)
#
# Meta / Config:
#   GET  /health             — service health + BL staleness status
#   GET  /meta               — current bl, f.sid, at presence
#   POST /meta               — update bl / f.sid manually
#   GET  /rate_limit         — current rate limit config
#   POST /rate_limit         — override rate limit for this session
#   POST /rpc/<rpc_id>       — generic batchexecute passthrough
#   GET  /rpc_registry       — RPC registry status (from nlm_rpc_mapper)
# ════════════════════════════════════════════════════════════════════════════

def create_nlm_proxy_app() -> Flask:
    """Create and return the NLM Live Proxy Flask app."""
    app = Flask(__name__)
    app.logger.setLevel(logging.WARNING)

    def _cookies() -> Dict[str, str]:
        return _load_cookies()

    def _no_cookies():
        return jsonify({
            "error": "no_cookies",
            "detail": (
                "No auth cookies stored. Upload a NotebookLM HAR file "
                "via POST /cookies/import to enable live API access."
            ),
        }), 401

    # ── Health & Status Routes ────────────────────────────────────────────
    # GET /health  — full service health: cookies, BL age, rate limit config

    @app.route("/health")
    def health():
        cookies = _cookies()
        meta = _load_meta()
        bl = meta.get("bl", _DEFAULT_BL)

        # Calculate BL age
        bl_age_days: Optional[int] = None
        try:
            import datetime
            updated_at = meta.get("bl_updated_at")
            if updated_at:
                bl_age_days = (datetime.datetime.now(datetime.timezone.utc) -
                               datetime.datetime.fromisoformat(updated_at)).days
        except Exception:
            pass

        return jsonify({
            "status": "ok" if cookies else "no_cookies",
            "has_cookies": bool(cookies),
            "cookie_count": len(cookies),
            "cookie_file": str(_COOKIES_FILE),
            "service": "nlm-live-proxy",
            "bl": bl,
            "bl_age_days": bl_age_days,
            "bl_stale": bl_age_days is not None and bl_age_days >= 8,
            "rpc_catalog_version": "v3.1",
            "known_rpcs": 25,
            "rate_limit_seconds": _rate_limiter._min_gap,
            "registry_available": _registry_available,
        }), 200 if cookies else 503

    # ── Cookie Management Routes ──────────────────────────────────────────
    # POST /cookies/refresh  — refresh f.sid + at from live NLM page
    # POST /cookies/import   — import from HAR file
    # POST /cookies/capture  — auto-capture via Chrome CDP
    # GET  /cookies          — list stored cookie names
    # DELETE /cookies        — clear all stored cookies

    @app.route("/cookies/refresh", methods=["POST"])
    def refresh_cookies():
        """Refresh f.sid and at token by loading the NLM page with stored cookies.

        Call this when batchexecute returns null data due to stale session tokens.
        Does NOT require a new HAR — uses the existing stored cookies to fetch
        fresh tokens from the live NLM page.
        """
        if not _cookies():
            return jsonify({"error": "no_cookies", "detail": "No cookies stored. Import a HAR first."}), 422
        ok = refresh_session_tokens()
        meta = _load_meta()
        return jsonify({
            "refreshed": ok,
            "f_sid": meta.get("f_sid", "-1"),
            "at_present": bool(meta.get("at")),
            "bl": meta.get("bl", _DEFAULT_BL),
        })

    @app.route("/cookies/import", methods=["POST"])
    def import_cookies():
        """Extract and store auth cookies from an uploaded or local HAR file.

        Body (JSON): {"har_path": "/absolute/path/to/file.har"}
        or multipart: file upload with field "har_file"
        """
        har_path: Optional[str] = None

        if request.is_json:
            har_path = (request.json or {}).get("har_path")
        elif "har_file" in request.files:
            f = request.files["har_file"]
            tmp = _PROJECT_ROOT / "data" / f"_nlm_cookies_import_{int(time.time())}.har"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            f.save(str(tmp))
            har_path = str(tmp)

        if not har_path:
            return jsonify({"error": "missing har_path or har_file"}), 400
        if not Path(har_path).exists():
            return jsonify({"error": "file_not_found", "path": har_path}), 404

        new_cookies, new_meta = extract_cookies_from_har(har_path)
        if not new_cookies and not new_meta:
            return jsonify({"error": "no_nlm_cookies_found",
                            "detail": "No Google auth cookies or metadata for notebooklm.google.com found in HAR. "
                                      "Note: some HAR exports redact cookies. Try Chrome CDP capture instead."}), 422

        # Merge with existing
        existing = _load_cookies()
        merged = {**existing, **new_cookies}
        _save_cookies(merged)

        # Update meta (bl, f.sid, at) if found
        existing_meta = _load_meta()
        if new_meta.get("bl"):
            existing_meta["bl"] = new_meta["bl"]
        if new_meta.get("f_sid"):
            existing_meta["f_sid"] = new_meta["f_sid"]
        if new_meta.get("at"):
            existing_meta["at"] = new_meta["at"]
        _save_meta(existing_meta)

        return jsonify({
            "imported_cookies": len(new_cookies),
            "total_cookies": len(merged),
            "bl": existing_meta.get("bl", _DEFAULT_BL),
            "f_sid": existing_meta.get("f_sid", "-1"),
            "status": "ok",
            "note": "No cookies found in HAR (Chrome redacted them). "
                    "In Chrome DevTools: Network tab → Export HAR → tick 'Include sensitive information' checkbox. "
                    "Alternatively use POST /cookies/capture for Chrome CDP extraction."
            if not new_cookies else None,
        })

    @app.route("/cookies", methods=["GET"])
    def list_cookies():
        cookies = _cookies()
        return jsonify({
            "count": len(cookies),
            "names": list(cookies.keys()),
            "has_cookies": bool(cookies),
        })

    @app.route("/cookies", methods=["DELETE"])
    def clear_cookies():
        _save_cookies({})
        return jsonify({"cleared": True})

    # ── Notebook Read Routes ──────────────────────────────────────────────
    # GET /notebooks                  — list all notebooks (ub2Bae)
    # GET /notebooks/<id>             — full notebook dump (multiple RPCs)
    # GET /notebooks/<id>/sources     — source metadata (wXbhsf)
    # GET /notebooks/<id>/summary     — AI summary (VfAZjd)
    # GET /notebooks/<id>/notes       — notes/artifacts (gArtLc)
    # GET /notebooks/<id>/conversations — conversation text (cFji9)
    # GET /notebooks/<id>/content     — raw document content (e3bVqc)
    # GET /notebooks/<id>/history     — thread IDs + messages (hPTbtc + khqZz)

    @app.route("/notebooks", methods=["GET"])
    def list_notebooks():
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        _, data = _batchexecute(RPC_LIST_NOTEBOOKS, "[[2]]", cookies)
        if data is None:
            return jsonify({"error": "no_data", "notebooks": []}), 502
        if isinstance(data, dict) and "error" in data:
            return jsonify(data), 502
        notebooks = []
        try:
            for nb in (data[0] if isinstance(data, list) and data else []):
                if isinstance(nb, list):
                    texts = _extract_strings(nb, min_len=5)
                    name = texts[0] if texts else "Unknown"
                    nid_match = None
                    for part in nb:
                        if isinstance(part, str) and re.match(r"[a-f0-9-]{36}", part):
                            nid_match = part
                            break
                    notebooks.append({"id": nid_match, "name": name})
        except (IndexError, TypeError) as exc:
            logger.warning("parse notebooks: %s", exc)
        return jsonify({"notebooks": notebooks, "count": len(notebooks)})

    # ── Notebook Sub-Resource Read Routes ─────────────────────────────────

    @app.route("/notebooks/<notebook_id>/sources", methods=["GET"])
    def get_sources(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([None, 1, None, [2]])
        _, data = _batchexecute(RPC_LIST_SOURCES, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        name, sources = _extract_sources(data)
        return jsonify({"notebook_name": name, "sources": sources,
                        "count": len(sources)})

    @app.route("/notebooks/<notebook_id>/summary", methods=["GET"])
    def get_summary(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([notebook_id, [2]])
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        summary = "\n\n".join(_extract_strings(data, 50))
        return jsonify({"notebook_id": notebook_id, "summary": summary})

    @app.route("/notebooks/<notebook_id>/notes", methods=["GET"])
    def get_notes(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([[2], notebook_id,
                           "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""])
        _, data = _batchexecute(RPC_GET_ARTIFACTS, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        notes = _dedup(_extract_strings(data, 80))
        return jsonify({"notes": [n for n in notes if len(n) > 100],
                        "count": len(notes)})

    @app.route("/notebooks/<notebook_id>/conversations", methods=["GET"])
    def get_conversations(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([notebook_id, None, None, [2]])
        _, data = _batchexecute(RPC_SYNC_NOTES, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        convos = _dedup(_extract_strings(data, 80))
        return jsonify({"conversations": [c for c in convos if len(c) > 100],
                        "count": len(convos)})

    @app.route("/notebooks/<notebook_id>/content", methods=["GET"])
    def get_content(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([None, None, notebook_id])
        _, data = _batchexecute(RPC_NOTEBOOK_STATE, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        docs = _dedup(_extract_strings(data, 100))
        return jsonify({"documents": [d for d in docs if len(d) > 200],
                        "count": len(docs)})

    @app.route("/notebooks/<notebook_id>", methods=["GET"])
    def get_notebook_full(notebook_id: str):
        """Fetch all available data for a notebook in one call."""
        cookies = _cookies()
        if not cookies:
            return _no_cookies()

        result: Dict[str, Any] = {"notebook_id": notebook_id}

        # Summary
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]),
                                cookies, notebook_id)
        result["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

        # Sources
        _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]),
                                cookies, notebook_id)
        if data and not isinstance(data, dict):
            result["notebook_name"], result["sources"] = _extract_sources(data)
        else:
            result["notebook_name"] = ""
            result["sources"] = []

        # Notes
        _, data = _batchexecute(
            "gArtLc",
            json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""]),
            cookies, notebook_id,
        )
        notes = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["notes"] = [n for n in notes if len(n) > 100]

        # Conversations
        _, data = _batchexecute(RPC_SYNC_NOTES, json.dumps([notebook_id, None, None, [2]]),
                                cookies, notebook_id)
        convos = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["conversations"] = [c for c in convos if len(c) > 100]

        result["stats"] = {
            "sources": len(result["sources"]),
            "notes":   len(result["notes"]),
            "conversations": len(result["conversations"]),
        }
        return jsonify(result)

    # ── Write: Ask / Chat Routes ──────────────────────────────────────────
    # POST /notebooks/<id>/ask        — citation-annotate Q&A (CYK0Xb)
    # POST /notebooks/<id>/ask_batch  — batch citation Q&A (CYK0Xb multi)
    # POST /notebooks/<id>/chat       — real chat (GenerateFreeFormStreamed)
    # POST /notebooks/<id>/chat_batch — batch chat (GenerateFreeFormStreamed)

    @app.route("/notebooks/<notebook_id>/ask", methods=["POST"])
    def ask_single(notebook_id: str):
        """Ask a single question using CYK0Xb (citation-annotate, synchronous).

        For natural conversational chat, use POST /notebooks/<id>/chat instead.

        Body (JSON):
          {
            "question": "What is the main argument?",
            "mode": "annotate"
          }
        Returns: {answer_id, answer, sources}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "missing question"}), 400
        result = ask_question(notebook_id, question, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/ask_batch", methods=["POST"])
    def ask_batch_route(notebook_id: str):
        """Ask multiple questions in parallel batches using CYK0Xb.

        For natural conversational chat, use POST /notebooks/<id>/chat_batch instead.

        Body (JSON):
          {
            "questions": ["Q1?", "Q2?", "Q3?"],
            "max_batch": 5
          }
        Returns: {answers: [{answer_id, answer, sources}, ...]}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        questions = body.get("questions", [])
        if not questions or not isinstance(questions, list):
            return jsonify({"error": "missing or invalid questions array"}), 400
        max_batch = body.get("max_batch", 5)
        results = ask_questions_batch(notebook_id, questions, cookies, max_batch)
        return jsonify({
            "answers": results,
            "count": len(results),
            "questions": questions,
        })

    @app.route("/notebooks/<notebook_id>/generate", methods=["POST"])
    def generate(notebook_id: str):
        """Generate a document/report from selected notebook sources.

        Body (JSON): {"source_ids": ["uuid1", "uuid2", ...], "doc_type": 2}
        Returns: {title, description, source_ids}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        source_ids = body.get("source_ids", [])
        doc_type = body.get("doc_type", 2)
        result = generate_document(notebook_id, source_ids, cookies, doc_type)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/save_note", methods=["POST"])
    def save_note_report_route(notebook_id: str):
        """Create/save a note artifact in a notebook.

        Body (JSON): {"source_ids": ["uuid1", ...], "note_type": 2}
        Returns: {note_id, title, note_type}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        source_ids = body.get("source_ids", [])
        note_type = body.get("note_type", 2)
        result = save_note_report(notebook_id, source_ids, cookies, note_type)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/chat", methods=["POST"])
    def chat_single(notebook_id: str):
        """Send a chat message — delegates to NLM Node bridge (browser-based).

        The batchexecute GenerateFreeFormStreamed RPC returns 400 (payload
        undecoded). The Node bridge uses real browser automation — always works.

        Body (JSON):
          {
            "question": "What is the main argument?",
            "reset_history": false
          }
        Returns: {answer, thread_id, message_id, question, sources}
        """
        if not _COOKIES_FILE.exists():
            return jsonify({"error": "not authenticated — run setup_auth first"}), 401
        body = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "missing question"}), 400
        reset_history = bool(body.get("reset_history", False))
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            result = get_nlm_hybrid().ask(notebook_id, question, reset_history=reset_history)
        except Exception as exc:
            logger.error("chat_single hybrid error: %s", exc)
            result = {"error": str(exc)}
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/chat_batch", methods=["POST"])
    def chat_batch_route(notebook_id: str):
        """Send multiple chat messages — delegates to NLM Node bridge.

        Body (JSON):
          {
            "questions": ["Q1?", "Q2?", ...]
          }
        Returns: {results: [{answer, ...}], count, questions}
        """
        if not _COOKIES_FILE.exists():
            return jsonify({"error": "not authenticated — run setup_auth first"}), 401
        body = request.json or {}
        questions = body.get("questions", [])
        if not questions:
            return jsonify({"error": "missing questions array"}), 400
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            results = get_nlm_hybrid().ask_batch(notebook_id, questions)
        except Exception as exc:
            logger.error("chat_batch_route hybrid error: %s", exc)
            results = [{"error": str(exc)}] * len(questions)
        return jsonify({
            "results": results,
            "count": len(results),
            "questions": questions,
        })

    # ── Write: Source Management Routes ──────────────────────────────────
    # POST   /notebooks/<id>/sources          — add URLs (izAoDd)
    # POST   /notebooks/<id>/sources/url      — add single URL (izAoDd)
    # DELETE /notebooks/<id>/sources/<src_id> — delete source (tGMBJ)
    # POST   /notebooks/<id>/rename           — rename notebook (s0tc2d)
    # GET    /notebooks/<id>/sources/wait     — poll until sources ready (rLM1Ne)
    # POST   /notebooks/<id>/generate         — generate document (ciyUvf)
    # POST   /notebooks/<id>/save_note        — save note artifact (R7cb6c)

    # ── Write: Research Routes ────────────────────────────────────────────
    # POST /notebooks/<id>/research        — fast research session (Ljjv0c)
    # POST /notebooks/<id>/research/deep   — deep research (QA9ei)
    # POST /notebooks/<id>/research/source — add research doc as source (LBwxtb)

    # ── Read: Threads, Mindmap, User Routes ──────────────────────────────
    # GET /notebooks/<id>/threads          — thread IDs (hPTbtc)
    # GET /notebooks/<id>/threads/<tid>    — thread messages (khqZz)
    # GET /notebooks/<id>/mindmap          — D3 mind map (cFji9)
    # GET /sources/<id>/content            — full source text (tr032e)
    # GET /user/profile                    — user profile (JFMDGd)
    # GET /user/quota                      — storage quota (ozz5Z)

    @app.route("/sources/<source_id>/content", methods=["GET"])
    def read_source_content(source_id: str):
        """Read the full text content of a source document (tr032e RPC).

        Returns the complete markdown text of the source. Use this to extract
        all source content from NLM into Nexus for offline analysis.

        Returns: {source_id, content, word_count}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = read_source(source_id, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/user/quota", methods=["GET"])
    def user_quota():
        """Fetch user account info and storage quota (ozz5Z RPC).

        Returns: {quota_data, extracted}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_user_quota(cookies)
        if isinstance(result, dict) and result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    # ── CDP Cookie Capture & Meta Routes ─────────────────────────────────
    # POST /cookies/capture  — auto-capture via Chrome CDP
    # GET  /meta             — return current bl, f.sid, at-presence
    # POST /meta             — manually update bl or f.sid
    # GET  /rate_limit       — current rate limit config
    # POST /rate_limit       — override rate limit for session
    # POST /rpc/<id>         — generic batchexecute passthrough
    # GET  /rpc_registry     — RPC ID registry status

    @app.route("/cookies/capture", methods=["POST"])
    def capture_cookies():
        """Automatically capture auth cookies from Chrome via CDP.

        Requires Chrome to be running with --remote-debugging-port=9222,
        OR launches Chrome automatically using the existing user profile.

        Body (JSON): {} (no params needed)
        Returns: {imported_cookies, bl, f_sid, status}
        """
        try:
            from engine.nexus.nlm_har_capture import capture_nlm_cookies
            result = capture_nlm_cookies()
            if result.get("error"):
                return jsonify(result), 500
            # If at token wasn't captured from CDP JS, refresh it from the live page
            if not result.get("at_present"):
                logger.info("at token not in CDP capture — running refresh_session_tokens()")
                refresh_session_tokens()
                meta = _load_meta()
                result["at_present"] = bool(meta.get("at"))
            return jsonify(result)
        except ImportError:
            return jsonify({
                "error": "nlm_har_capture module not available",
                "detail": "engine/nexus/nlm_har_capture.py not found"
            }), 501

    @app.route("/meta", methods=["GET"])
    def get_meta():
        """Return current build label and session metadata."""
        return jsonify(_load_meta())

    @app.route("/meta", methods=["POST"])
    def update_meta():
        """Manually update build label and session metadata.

        Body (JSON): {"bl": "boq_labs-...", "f_sid": "12345..."}
        """
        body = request.json or {}
        meta = _load_meta()
        if "bl" in body:
            meta["bl"] = body["bl"]
        if "f_sid" in body:
            meta["f_sid"] = body["f_sid"]
        if "at" in body and body["at"]:
            meta["at"] = body["at"]
        _save_meta(meta)
        return jsonify({"updated": True, **meta})

    # ── Generic batchexecute passthrough ────────────────────────────────

    @app.route("/rpc/<rpc_id>", methods=["POST"])
    def call_rpc(rpc_id: str):
        """Call any batchexecute RPC directly.

        Body (JSON): {"args": "[\"notebook_id\",[2]]", "notebook_id": "..."}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        data = request.json or {}
        args_str = data.get("args", "[]")
        if not isinstance(args_str, str):
            args_str = json.dumps(args_str)
        nb_id = data.get("notebook_id", "")
        _, result = _batchexecute(rpc_id, args_str, cookies, nb_id)
        return jsonify({"rpc_id": rpc_id, "data": result})

    @app.route("/notebooks/<notebook_id>/history", methods=["GET"])
    def get_history(notebook_id: str):
        """Get conversation/chat history for a notebook.

        Uses hPTbtc to get thread IDs, then khqZz to read messages.
        Query params: page_size (default 20)
        Returns: {threads: [{thread_id, messages}], count, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        page_size = request.args.get("page_size", 20, type=int)
        # Step 1: get thread IDs via hPTbtc
        args = json.dumps([[], None, notebook_id, page_size])
        _, data = _batchexecute(RPC_GET_THREAD_IDS, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        thread_ids: List[str] = []
        try:
            if isinstance(data, list) and data:
                for item in data[0]:
                    if isinstance(item, list) and item and isinstance(item[0], str):
                        thread_ids.append(item[0])
        except (IndexError, TypeError):
            pass
        threads = []
        for tid in thread_ids[:10]:  # cap at 10 threads per request
            t_args = json.dumps([[], None, None, tid, page_size])
            _, t_data = _batchexecute(RPC_READ_THREAD, t_args, cookies, notebook_id)
            messages = []
            if t_data and isinstance(t_data, list):
                for s in _extract_strings(t_data, min_len=10):
                    if len(s) > 20:
                        messages.append(s)
            threads.append({"thread_id": tid, "messages": messages})
        return jsonify({"threads": threads, "count": len(threads), "notebook_id": notebook_id})

    # ── Write: create notebook ───────────────────────────────────────────

    @app.route("/notebooks", methods=["POST"])
    def create_notebook():
        """Create a new notebook (client-side UUID, backend created on first source add).

        Body (JSON): {"title": "My Notebook"}
        Returns: {notebook_id, title, message}

        NLM creates the backend record lazily when the first source is added via
        LBwxtb. We generate a UUID v4 here and return it — the caller should
        immediately add sources to materialise the notebook.
        """
        import uuid
        body = request.json or {}
        title = body.get("title", "New Notebook")
        notebook_id = str(uuid.uuid4())
        logger.info("Created client-side notebook UUID %s (title=%r)", notebook_id, title)
        return jsonify({
            "notebook_id": notebook_id,
            "title": title,
            "message": "Notebook UUID reserved. Add sources to materialise on NLM backend.",
            "warning": "Backend record is created lazily — call POST /notebooks/<id>/sources next.",
        }), 201

    # ── Write: add URL sources ───────────────────────────────────────────

    @app.route("/notebooks/<notebook_id>/sources", methods=["POST"])
    def add_sources(notebook_id: str):
        """Add one or more URL sources to a notebook via izAoDd RPC.

        Confirmed v3.1: izAoDd is the correct RPC for adding URL/YouTube sources.
        Each URL is added in a separate API call. YouTube URLs are detected
        automatically and encoded at position 7 instead of position 2.

        Body (JSON):
            {
              "urls": ["https://example.com/article", "https://youtu.be/xyz"]
            }

        Returns: {added, results: [{source_id, url, status}], notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        raw_urls = body.get("urls", [])
        if not raw_urls:
            return jsonify({"error": "urls array is required"}), 400

        results = []
        for item in raw_urls:
            url_str = item if isinstance(item, str) else item.get("url", "")
            if not url_str:
                continue
            res = add_source_url(notebook_id, url_str, cookies)
            results.append(res)

        return jsonify({
            "added": len(results),
            "results": results,
            "notebook_id": notebook_id,
        })

    @app.route("/notebooks/<notebook_id>/sources/url", methods=["POST"])
    def add_single_source(notebook_id: str):
        """Add a single URL or YouTube source to a notebook (izAoDd RPC).

        YouTube URLs (youtube.com/watch, youtu.be/) are auto-detected and
        encoded at position 7 in the source object. Regular URLs use position 2.

        Body (JSON): {"url": "https://..."}
        Returns: {source_id, url, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        url = body.get("url", "").strip()
        if not url:
            return jsonify({"error": "url is required"}), 400
        result = add_source_url(notebook_id, url, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/sources/text", methods=["POST"])
    def add_text_source_route(notebook_id: str):
        """Add an inline text/markdown source to a notebook (izAoDd RPC, text format).

        Confirmed from HAR 2026-03-01. No external URL needed — content is
        passed directly. NLM indexes it as a paste/text source.

        Body (JSON):
            {
              "title": "ARCHITECTURE.md",
              "content": "# Architecture\\n\\nCosySim is..."
            }

        Returns: {source_id, title, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        title = body.get("title", "").strip()
        content = body.get("content", "").strip()
        if not title or not content:
            return jsonify({"error": "title and content are required"}), 400
        result = add_text_source(notebook_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/sources/status", methods=["GET"])
    def source_status_route(notebook_id: str):
        """Poll source processing status via rLM1Ne RPC.

        Query params:
            first=true  (default) for first poll, first=false for continuing.

        Returns: {status, data}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        first = request.args.get("first", "true").lower() != "false"
        result = poll_source_status(notebook_id, cookies, first_poll=first)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/sources/file", methods=["POST"])
    def upload_file_source_route(notebook_id: str):
        """Upload a file as a notebook source (o4cbdc + /upload/_/ flow).

        Accepts multipart/form-data with a 'file' field, or JSON with
        {"filename": "...", "content": "...", "mime_type": "text/plain"}.

        For text/markdown files, prefer POST /sources/text (simpler, no upload step).
        Use this route for PDFs and binary files.

        Returns: {source_id, filename, upload_id, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()

        # Support both multipart and JSON
        if request.content_type and "multipart" in request.content_type:
            if "file" not in request.files:
                return jsonify({"error": "file field required"}), 400
            f = request.files["file"]
            filename = f.filename
            content_bytes = f.read()
            mime_type = f.content_type or "application/octet-stream"
        else:
            body = request.json or {}
            filename = body.get("filename", "upload.txt")
            content = body.get("content", "")
            content_bytes = content.encode("utf-8")
            mime_type = body.get("mime_type", "text/plain")

        # Step 1: register filename with NLM to get source_id
        registrations = register_file_sources(notebook_id, [filename], cookies)
        if not registrations or registrations[0].get("error"):
            return jsonify(registrations[0] if registrations else {"error": "registration_failed"}), 502
        source_id = registrations[0].get("source_id")

        # Step 2: upload bytes
        upload_result = upload_file_to_nlm(filename, content_bytes, cookies, mime_type)
        if upload_result.get("error"):
            return jsonify(upload_result), 502

        return jsonify({
            "source_id": source_id,
            "filename": filename,
            "upload_id": upload_result.get("upload_id"),
            "status": upload_result.get("status", "uploaded"),
        })

    @app.route("/notebooks/<notebook_id>/sources/<source_id>", methods=["DELETE"])
    def delete_source_route(notebook_id: str, source_id: str):
        """Delete a source from a notebook (tGMBJ RPC).

        Confirmed v3.1 from HAR analysis.
        Payload: [[[source_id]], [2]]

        Returns: {deleted, source_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = delete_source(source_id, cookies)
        if not result.get("deleted"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/rename", methods=["POST"])
    def rename_notebook_route(notebook_id: str):
        """Rename a notebook (s0tc2d RPC).

        Confirmed v3.1: s0tc2d is RENAME_NOTEBOOK, not chat.

        Body (JSON): {"name": "New Notebook Title"}
        Returns: {renamed, notebook_id, name}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        new_name = body.get("name", "").strip()
        if not new_name:
            return jsonify({"error": "name is required"}), 400
        result = rename_notebook(notebook_id, new_name, cookies)
        if not result.get("renamed"):
            return jsonify(result), 502
        return jsonify(result)

    # ── Write: poll source processing ───────────────────────────────────

    @app.route("/notebooks/<notebook_id>/sources/wait", methods=["GET"])
    def wait_for_sources(notebook_id: str):
        """Poll rLM1Ne until all sources have a non-zero word_count.

        Query params:
            timeout   — max seconds to wait (default 60, max 300)
            interval  — poll interval in seconds (default 3, min 2)

        Returns: {ready, sources, elapsed_seconds}

        Uses the rate limiter — each poll respects the configured min gap.
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        timeout = min(request.args.get("timeout", 60, type=int), 300)
        interval = max(request.args.get("interval", 3, type=int), 2)
        start = time.time()
        while True:
            args = json.dumps([notebook_id, None, [2], None, 0])
            _, data = _batchexecute(RPC_LOAD_NOTEBOOK, args, cookies, notebook_id)
            if data is None or (isinstance(data, dict) and "error" in data):
                return jsonify({"error": "poll failed", "detail": data}), 502
            # Parse sources — check if any are still processing (word_count == 0)
            _, sources = _extract_sources(data)
            pending = [s for s in sources if s.get("word_count", 0) == 0]
            elapsed = time.time() - start
            if not pending or elapsed >= timeout:
                return jsonify({
                    "ready": len(pending) == 0,
                    "sources": sources,
                    "pending_count": len(pending),
                    "elapsed_seconds": round(elapsed, 1),
                })
            time.sleep(interval)

    # ── Write: start fast research ───────────────────────────────────────

    @app.route("/notebooks/<notebook_id>/research", methods=["POST"])
    def start_research(notebook_id: str):
        """Start a fast research session for a notebook (Ljjv0c RPC).

        Body (JSON): {"query": "multi-agent frameworks"}
        Returns: {session_id, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        query = body.get("query", "")
        if not query:
            return jsonify({"error": "query is required"}), 400
        args = json.dumps([[query, 1], None, 1, notebook_id])
        _, data = _batchexecute(RPC_FAST_RESEARCH_START, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify({"error": "Ljjv0c failed", "detail": data}), 502
        try:
            session_id = data[0] if isinstance(data, list) else ""
        except (IndexError, TypeError):
            session_id = ""
        return jsonify({"session_id": session_id, "notebook_id": notebook_id, "query": query})

    @app.route("/notebooks/<notebook_id>/research/deep", methods=["POST"])
    def start_deep_research_route(notebook_id: str):
        """Start a deep research session (QA9ei RPC).

        Confirmed v3.1: QA9ei triggers NLM deep research on a topic.
        Returns session_id. NLM generates a research document async.
        Use POST /research/source to add the generated document as a source.

        Body (JSON): {"topic": "transformer attention mechanisms"}
        Returns: {session_id, topic, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        topic = body.get("topic", "").strip()
        if not topic:
            return jsonify({"error": "topic is required"}), 400
        result = start_deep_research(notebook_id, topic, cookies)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/research/source", methods=["POST"])
    def add_research_source_route(notebook_id: str):
        """Add an AI-generated research document as a notebook source (LBwxtb RPC).

        Confirmed v3.1: LBwxtb adds AI-generated content docs as sources.
        Call this after start_deep_research with the generated title and content.

        Body (JSON):
          {
            "session_id": "uuid from deep research",
            "title": "Research: Transformer Attention",
            "content": "Full text of the research document..."
          }
        Returns: {source_id, title, session_id, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        session_id = body.get("session_id", "").strip()
        title = body.get("title", "").strip()
        content = body.get("content", "").strip()
        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        if not title or not content:
            return jsonify({"error": "title and content are required"}), 400
        result = add_research_source(notebook_id, session_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    # ── Read: conversation threads ───────────────────────────────────────

    @app.route("/notebooks/<notebook_id>/threads", methods=["GET"])
    def get_threads(notebook_id: str):
        """Get conversation thread IDs for a notebook (hPTbtc RPC).

        Returns: {threads: [{thread_id}], count, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        page_size = request.args.get("page_size", 20, type=int)
        args = json.dumps([[], None, notebook_id, page_size])
        _, data = _batchexecute(RPC_GET_THREAD_IDS, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        thread_ids: List[str] = []
        try:
            if isinstance(data, list) and data:
                for item in data[0]:
                    if isinstance(item, list) and item and isinstance(item[0], str):
                        thread_ids.append(item[0])
        except (IndexError, TypeError):
            pass
        return jsonify({"threads": [{"thread_id": tid} for tid in thread_ids],
                        "count": len(thread_ids), "notebook_id": notebook_id})

    @app.route("/notebooks/<notebook_id>/threads/<thread_id>", methods=["GET"])
    def get_thread_messages(notebook_id: str, thread_id: str):
        """Read all messages in a conversation thread (khqZz RPC).

        Returns: {thread_id, messages: [str], count}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        page_size = request.args.get("page_size", 20, type=int)
        args = json.dumps([[], None, None, thread_id, page_size])
        _, data = _batchexecute(RPC_READ_THREAD, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        messages = [s for s in _extract_strings(data, min_len=10) if len(s) > 20]
        return jsonify({"thread_id": thread_id, "messages": messages, "count": len(messages)})

    # ── Read: mind map ───────────────────────────────────────────────────

    @app.route("/notebooks/<notebook_id>/mindmap", methods=["GET"])
    def get_mindmap(notebook_id: str):
        """Get or generate the mind map for a notebook (cFji9 RPC).

        Returns: {notebook_id, mindmap_json} where mindmap_json is D3 hierarchical JSON.
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([notebook_id, None, None, [2]])
        _, data = _batchexecute(RPC_MIND_MAP, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        # cFji9 returns a JSON string of the D3 hierarchy inside the response
        mindmap_str = ""
        try:
            mindmap_str = _extract_strings(data, min_len=5)[0] if _extract_strings(data, min_len=5) else ""
        except (IndexError, TypeError):
            pass
        try:
            mindmap = json.loads(mindmap_str)
        except (json.JSONDecodeError, TypeError):
            mindmap = mindmap_str
        return jsonify({"notebook_id": notebook_id, "mindmap": mindmap})

    # ── Read: user profile ───────────────────────────────────────────────

    @app.route("/user/profile", methods=["GET"])
    def get_user_profile():
        """Get user profile and queries remaining (JFMDGd RPC).

        Returns: {email, name, queries_remaining, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        notebook_id = request.args.get("notebook_id", "")
        args = json.dumps([notebook_id, [2]])
        _, data = _batchexecute(RPC_USER_PROFILE, args, cookies, notebook_id)
        if data is None or (isinstance(data, dict) and "error" in data):
            return jsonify(data or {"error": "no_data"}), 502
        profile: Dict[str, Any] = {"notebook_id": notebook_id}
        try:
            if isinstance(data, list) and data and isinstance(data[0], list):
                inner = data[0][0]
                strings = _extract_strings(inner, min_len=3)
                if strings:
                    profile["email"] = strings[0] if "@" in strings[0] else ""
                    profile["name"] = strings[1] if len(strings) > 1 else ""
            # queries_remaining is typically at data[2] as an integer
            if isinstance(data, list) and len(data) > 2 and isinstance(data[2], (int, float)):
                profile["queries_remaining"] = int(data[2])
        except (IndexError, TypeError):
            pass
        return jsonify(profile)

    @app.route("/user/plan", methods=["GET"])
    def get_user_plan_route():
        """Get user plan/tier and daily query allowance (ZwVcOc RPC).

        Returns: {plan_name, daily_limit, queries_remaining}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_user_plan(cookies)
        if isinstance(result, dict) and "error" in result:
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/user/queries", methods=["GET"])
    def get_user_queries():
        """Get remaining queries as a simple integer (fast path from JFMDGd RPC).

        Returns: {queries_remaining: int}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        notebook_id = request.args.get("notebook_id", "")
        args = json.dumps([notebook_id, [2]])
        _, data = _batchexecute(RPC_USER_PROFILE, args, cookies, notebook_id)
        remaining: Optional[int] = None
        try:
            if isinstance(data, list) and len(data) > 2 and isinstance(data[2], (int, float)):
                remaining = int(data[2])
        except (IndexError, TypeError):
            pass
        return jsonify({"queries_remaining": remaining})

    # ── Read/Write: rate limiter control ────────────────────────────────

    @app.route("/rate_limit", methods=["GET"])
    def get_rate_limit_status():
        """Return current rate limit configuration."""
        return jsonify({
            "min_gap_seconds": _rate_limiter._min_gap,
            "config_key": "notebooklm.rate_limit_seconds",
        })

    @app.route("/rate_limit", methods=["POST"])
    def set_rate_limit():
        """Override rate limit for this session.

        Body (JSON): {"seconds": 2.0}
        """
        body = request.json or {}
        seconds = float(body.get("seconds", 1.5))
        seconds = max(0.5, min(seconds, 30.0))  # clamp to sane range
        _rate_limiter.set_gap(seconds)
        logger.info("Rate limit set to %.1fs via API", seconds)
        return jsonify({"min_gap_seconds": seconds})

    # ── Read: RPC registry status ────────────────────────────────────────

    @app.route("/rpc_registry", methods=["GET"])
    def get_rpc_registry():
        """Return RPC registry status — which IDs are loaded and their source."""
        if not _registry_available:
            return jsonify({"available": False, "message": "nlm_rpc_mapper not installed"})
        try:
            from engine.nexus.nlm_rpc_mapper import NLMRPCRegistry
            reg = NLMRPCRegistry()
            return jsonify({"available": True, **reg.report()})
        except Exception as exc:
            return jsonify({"available": False, "error": str(exc)}), 200

    # ════════════════════════════════════════════════════════════════════════════
    # DOWNLOAD & ARCHIVE ROUTES
    # Bulk export of notebook content, sources, and full archives.
    # These routes use tr032e (read_source) per source, which is slow for large
    # notebooks — each source call respects the rate limiter (1.5s gap default).
    # ════════════════════════════════════════════════════════════════════════════

    @app.route("/notebooks/<notebook_id>/sources/content", methods=["GET"])
    def download_sources_content(notebook_id: str):
        """Download full text content of ALL sources in a notebook.

        Uses wXbhsf to list sources, then tr032e per source to read content.
        Slow for large notebooks — each source is a separate rate-limited call.

        Query params:
            source_ids  — comma-separated UUIDs to read (default: all sources)

        Returns: {notebook_id, sources: [{source_id, title, url, word_count, content}],
                  total_sources, total_words}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        raw_ids = request.args.get("source_ids", "")
        sid_filter = [s.strip() for s in raw_ids.split(",") if s.strip()] if raw_ids else None
        results = download_all_sources(notebook_id, cookies, sid_filter)
        total_words = sum(r.get("word_count", 0) for r in results)
        return jsonify({
            "notebook_id": notebook_id,
            "sources": results,
            "total_sources": len(results),
            "total_words": total_words,
        })

    @app.route("/sources/<source_id>/export", methods=["GET"])
    def export_source_text(source_id: str):
        """Export a single source as a plain text file download.

        Uses tr032e to read the full source content and streams it as a
        text/plain attachment. Useful for piping source content into other tools.

        Query params:
            filename  — override the download filename (default: <source_id>.txt)

        Returns: text/plain file download
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        from flask import Response
        result = read_source(source_id, cookies)
        if result.get("error") and not result.get("content"):
            return jsonify(result), 502
        filename = request.args.get("filename") or f"{source_id}.txt"
        content = result.get("content", "")
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/notebooks/<notebook_id>/archive", methods=["GET"])
    def export_notebook_archive(notebook_id: str):
        """Export a complete notebook archive — all data in one JSON response.

        Combines: summary (VfAZjd), sources + content (wXbhsf + tr032e),
        notes (gArtLc), conversation threads (hPTbtc + khqZz), mind map (cFji9).

        This is the canonical "download everything" endpoint for a single notebook.
        Source content reading is ON by default — disable with include_content=false
        for faster metadata-only export.

        Query params:
            include_content  — read full source text (default: true)
            include_threads  — read conversation threads (default: true)

        Returns: Full notebook archive JSON (notebook_id, notebook_name, summary,
                 sources, notes, threads, mindmap, stats, exported_at)
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        include_content = request.args.get("include_content", "true").lower() != "false"
        include_threads = request.args.get("include_threads", "true").lower() != "false"
        result = export_notebook(notebook_id, cookies, include_content, include_threads)
        return jsonify(result)

    @app.route("/notebooks/archive", methods=["GET"])
    def export_all_notebooks_archive():
        """Export all notebooks for the authenticated user as a single JSON archive.

        Lists all notebooks (ub2Bae) then exports each via export_notebook().
        Source content is OFF by default (metadata-only) for bulk exports since
        large accounts may have hundreds of sources.
        Enable with include_content=true but expect long response times.

        Query params:
            include_content  — read full source text per source (default: false)
            include_threads  — read conversation threads per notebook (default: true)

        Returns: {count, notebooks: [...], exported_at}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        include_content = request.args.get("include_content", "false").lower() == "true"
        include_threads = request.args.get("include_threads", "true").lower() != "false"
        result = export_all_notebooks(cookies, include_content, include_threads)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/notes", methods=["POST"])
    def create_note_route(notebook_id: str):
        """Create a new note (CYK0Xb). Also use to save AI response as a note.

        Body (JSON): {"title": "My Note", "content": "<p>html</p>"}
        Returns: {note_id, title, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        title = body.get("title", "New note")
        content = body.get("content", "")
        result = create_note(notebook_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result), 201

    @app.route("/notebooks/<notebook_id>/notes/<note_id>", methods=["PUT"])
    def save_note_route(notebook_id: str, note_id: str):
        """Save/update a note's content (cYAfTb live save).

        Body (JSON): {"title": "My Note", "content": "<p>updated html</p>"}
        Returns: {note_id, title, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        title = body.get("title", "")
        content = body.get("content", "")
        result = save_note(notebook_id, note_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/notes/sync", methods=["GET"])
    def sync_notes_route(notebook_id: str):
        """Delta-sync notes since a timestamp (cFji9).

        Query params: ts_sec=<int>&ts_nano=<int> for continuation (omit for first call).
        Returns: {notes, next_timestamp, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        ts_sec = request.args.get("ts_sec")
        ts_nano = request.args.get("ts_nano")
        prev_ts = [int(ts_sec), int(ts_nano)] if ts_sec and ts_nano else None
        result = sync_notes(notebook_id, cookies, prev_timestamp=prev_ts)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/audio-options", methods=["GET"])
    def audio_options_route(notebook_id: str):
        """List available audio overview formats (sqTeoe).

        Returns: {options: [{id, label, description}], status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_audio_options(notebook_id, cookies)
        return jsonify(result)

    @app.route("/sources/<source_id>/summary", methods=["GET"])
    def source_summary_route(source_id: str):
        """Get AI-generated markdown summary of a source (tr032e).

        Returns: {source_id, summary, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_source_summary(source_id, cookies)
        return jsonify(result)

    # ── Workspace Gemini Routes ───────────────────────────────────────────

    @app.route("/api/workspace/generate", methods=["POST"])
    def workspace_generate_route():
        """Stream-generate text via the Workspace Gemini backend.

        Body: {prompt, context?, document_type?}
        Returns: {text, model, usage, chunks}
        """
        from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
        body = request.json or {}
        prompt = body.get("prompt", "")
        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        client = get_workspace_gemini_client()
        if client is None:
            return jsonify({"error": "No Workspace Gemini account available"}), 503

        try:
            result = client.stream_generate(
                prompt=prompt,
                context=body.get("context"),
                document_type=body.get("document_type", "docs"),
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/search", methods=["POST"])
    def workspace_search_route():
        """AI Overview search across Google Drive.

        Body: {query, page_size?}
        Returns: {results, total}
        """
        from engine.integrations.google_drive_client import get_drive_client
        body = request.json or {}
        query = body.get("query", "")
        if not query:
            return jsonify({"error": "query is required"}), 400

        client = get_drive_client()
        if client is None:
            return jsonify({"error": "No Drive account available"}), 503

        try:
            result = client.ai_overview_search(
                query=query,
                page_size=body.get("page_size", 20),
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/ask", methods=["POST"])
    def workspace_ask_route():
        """Ask Gemini a question about Drive files.

        Body: {question, file_ids?, max_files?}
        Returns: {answer, sources, model, usage}
        """
        from engine.integrations.google_drive_client import get_drive_client
        body = request.json or {}
        question = body.get("question", "")
        if not question:
            return jsonify({"error": "question is required"}), 400

        client = get_drive_client()
        if client is None:
            return jsonify({"error": "No Drive account available"}), 503

        try:
            result = client.ask_gemini(
                question=question,
                file_ids=body.get("file_ids"),
                max_context_files=body.get("max_files", 10),
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/docs/create", methods=["POST"])
    def workspace_docs_create_route():
        """Create a Google Doc with optional Gemini content.

        Body: {title, prompt?, content?, folder_id?}
        Returns: {doc_id, title, url}
        """
        from engine.integrations.google_docs_client import get_docs_client
        body = request.json or {}
        title = body.get("title", "")
        if not title:
            return jsonify({"error": "title is required"}), 400

        client = get_docs_client()
        if client is None:
            return jsonify({"error": "No Docs account available"}), 503

        try:
            prompt = body.get("prompt", "")
            content = body.get("content", "")
            folder_id = body.get("folder_id")

            if prompt:
                result = client.create_with_gemini(title=title, prompt=prompt, folder_id=folder_id)
            else:
                result = client.create_doc(title=title, folder_id=folder_id)
                if content and result and result.get("documentId"):
                    client.append_to_doc(result["documentId"], content)

            doc_id = (result or {}).get("documentId", "")
            return jsonify({
                "doc_id": doc_id,
                "title": title,
                "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            }), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/sheets/create", methods=["POST"])
    def workspace_sheets_create_route():
        """Build a spreadsheet from a natural language prompt.

        Body: {title, prompt}
        Returns: {sheet_id, title, url}
        """
        from engine.integrations.gsheets_client import get_sheets_client
        body = request.json or {}
        prompt = body.get("prompt", "")
        title = body.get("title", "Untitled Sheet")
        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        client = get_sheets_client()
        if client is None:
            return jsonify({"error": "No Sheets account available"}), 503

        try:
            result = client.build_with_gemini(prompt=prompt, title=title)
            sheet_id = (result or {}).get("spreadsheetId", "")
            return jsonify({
                "sheet_id": sheet_id,
                "title": title,
                "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
            }), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/sheets/fill", methods=["POST"])
    def workspace_sheets_fill_route():
        """Fill a sheet range with Gemini-enriched data.

        Body: {sheet_id, range, prompt}
        Returns: {updated_range, values_written}
        """
        from engine.integrations.gsheets_client import get_sheets_client
        body = request.json or {}
        sheet_id = body.get("sheet_id", "")
        cell_range = body.get("range", "")
        prompt = body.get("prompt", "")

        if not all([sheet_id, cell_range, prompt]):
            return jsonify({"error": "sheet_id, range, and prompt are required"}), 400

        client = get_sheets_client()
        if client is None:
            return jsonify({"error": "No Sheets account available"}), 503

        try:
            result = client.fill_with_gemini(
                spreadsheet_id=sheet_id,
                cell_range=cell_range,
                prompt=prompt,
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/pipeline", methods=["POST"])
    def workspace_pipeline_route():
        """Run a named Workspace pipeline template.

        Body: {template, topic?, ...params}
        Returns: PipelineRun dict
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        body = request.json or {}
        template = body.get("template", "")
        if not template:
            return jsonify({"error": "template is required"}), 400

        pipeline = get_workspace_pipeline()
        params = {k: v for k, v in body.items() if k != "template"}

        try:
            run = pipeline.run(template, **params)
            return jsonify(run.to_dict())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/pipeline/status/<run_id>", methods=["GET"])
    def workspace_pipeline_status_route(run_id: str):
        """Get status of a pipeline run.

        Returns: PipelineRun dict or 404
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        pipeline = get_workspace_pipeline()
        run = pipeline.get_run(run_id)
        if run is None:
            return jsonify({"error": f"Pipeline run {run_id} not found"}), 404
        return jsonify(run.to_dict())

    @app.route("/api/workspace/pipeline/templates", methods=["GET"])
    def workspace_pipeline_templates_route():
        """List available pipeline templates.

        Returns: {templates: {name: [stages]}}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        pipeline = get_workspace_pipeline()
        return jsonify({"templates": pipeline.list_templates()})

    @app.route("/api/workspace/status", methods=["GET"])
    def workspace_status_route():
        """Get Workspace integration status — available services and quota.

        Returns: {services, quota, registry}
        """
        from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
        from engine.integrations.workspace_rpc_registry import get_workspace_registry

        registry = get_workspace_registry()
        services = {
            "workspace_gemini": get_workspace_gemini_client() is not None,
        }
        try:
            from engine.integrations.gsheets_client import get_sheets_client
            services["sheets"] = get_sheets_client() is not None
        except Exception:
            services["sheets"] = False
        try:
            from engine.integrations.google_drive_client import get_drive_client
            services["drive"] = get_drive_client() is not None
        except Exception:
            services["drive"] = False
        try:
            from engine.integrations.google_docs_client import get_docs_client
            services["docs"] = get_docs_client() is not None
        except Exception:
            services["docs"] = False

        return jsonify({
            "services": services,
            "registry": registry.summary(),
        })

    @app.route("/api/workspace/news/fetch", methods=["POST"])
    def workspace_news_fetch_route():
        """Fetch news articles via RSS and optionally store in Nexus.

        Body: {categories?: ["ai_research","tech",...], max_articles?: 20, store?: true}
        Returns: {status, articles, categories}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(silent=True) or {}
        categories = data.get("categories", ["ai_research"])
        max_articles = data.get("max_articles", 20)
        store = data.get("store", True)

        pipeline = get_workspace_pipeline()
        try:
            run = pipeline.run_stages(
                [{"name": "fetch_news"}],
                topic=f"News fetch: {', '.join(categories)}",
                categories=categories,
                max_articles=max_articles,
                store_articles=store,
            )
            return jsonify(run.to_dict())
        except Exception as exc:
            logger.error("workspace news fetch failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/news/digest", methods=["POST"])
    def workspace_news_digest_route():
        """Run the full news pipeline: fetch → research → store.

        Body: {topic: str, sources?: [url,...]}
        Returns: Pipeline run result.
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(silent=True) or {}
        topic = data.get("topic", "latest AI news")
        sources = data.get("sources")

        pipeline = get_workspace_pipeline()
        try:
            run = pipeline.news_digest(topic=topic, sources=sources)
            return jsonify(run.to_dict())
        except Exception as exc:
            logger.error("workspace news digest failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── v1.19b Drive v2internal & Sheets Extended Routes ─────────────────

    @app.route("/api/workspace/drive/copy", methods=["POST"])
    def workspace_drive_copy_route():
        """Copy a Google Drive file via v2internal.

        Body: {file_id: str, title?: str, parent_id?: str, description?: str}
        Returns: New file metadata (id, title, alternateLink).
        """
        from engine.integrations.google_drive_client import get_drive_client

        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400

        try:
            client = get_drive_client()
            result = client.v2_copy_file(
                file_id=file_id,
                title=data.get("title"),
                parent_id=data.get("parent_id"),
                description=data.get("description"),
            )
            return jsonify(result)
        except Exception as exc:
            logger.error("workspace drive copy failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/drive/export", methods=["POST"])
    def workspace_drive_export_route():
        """Export a Google Workspace file to a different format.

        Body: {file_id: str, mime_type?: str}
        Returns: {content: str, size: int, mime_type: str, is_text: bool}
        """
        import base64

        from engine.integrations.google_drive_client import get_drive_client

        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400

        mime_type = data.get("mime_type", "text")
        try:
            client = get_drive_client()
            content = client.v2_export_file(file_id, mime_type)
            is_text = mime_type in ("text", "html", "csv", "text/plain", "text/html", "text/csv")
            payload = {
                "file_id": file_id,
                "mime_type": mime_type,
                "size": len(content),
                "is_text": is_text,
                "content": content.decode("utf-8", errors="replace") if is_text else base64.b64encode(content).decode(),
            }
            return jsonify(payload)
        except Exception as exc:
            logger.error("workspace drive export failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/drive/permissions", methods=["POST"])
    def workspace_drive_permissions_route():
        """Manage Drive file permissions via v2internal.

        Body: {file_id: str, action?: "list"|"set", role?: str,
               perm_type?: str, email?: str}
        Returns: Permission list or created permission.
        """
        from engine.integrations.google_drive_client import get_drive_client

        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400

        action = data.get("action", "list")
        try:
            client = get_drive_client()
            if action == "set":
                result = client.v2_insert_permission(
                    file_id=file_id,
                    role=data.get("role", "reader"),
                    perm_type=data.get("perm_type", "anyone"),
                    email=data.get("email"),
                    with_link=data.get("with_link", True),
                    send_notification=data.get("send_notification", False),
                )
                return jsonify({"permission": result, "action": "set"})
            else:
                perms = client.v2_get_permissions(file_id)
                return jsonify({"permissions": perms, "action": "list", "count": len(perms)})
        except Exception as exc:
            logger.error("workspace drive permissions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/sheets/revisions", methods=["GET"])
    def workspace_sheets_revisions_route():
        """Get revision history of a spreadsheet.

        Query: ?spreadsheet_id=...&max_results=50
        Returns: {revisions: [...], count: int}
        """
        from engine.integrations.gsheets_client import get_sheets_client

        spreadsheet_id = request.args.get("spreadsheet_id")
        if not spreadsheet_id:
            return jsonify({"error": "spreadsheet_id required"}), 400

        max_results = int(request.args.get("max_results", "50"))
        try:
            client = get_sheets_client()
            revisions = client.get_revision_history(spreadsheet_id, max_results=max_results)
            return jsonify({"revisions": revisions, "count": len(revisions)})
        except Exception as exc:
            logger.error("workspace sheets revisions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    return app


# ── Singleton ────────────────────────────────────────────────────────────

_proxy_app: Optional[Flask] = None


def get_nlm_proxy_app() -> Flask:
    """Return the shared NLM proxy Flask application."""
    global _proxy_app
    if _proxy_app is None:
        _proxy_app = create_nlm_proxy_app()
    return _proxy_app


# ── Launcher-compatible server class ─────────────────────────────────────


class NLMProxyServer:
    """Thin wrapper so the launcher can start the proxy via `.start()`.

    Follows the same contract as Flask-based scene classes:
      NLMProxyServer().start()  — blocks serving until process dies.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8800) -> None:
        cfg = get_config()
        self.host = host
        self.port = cfg.get("notebooklm.proxy_port", port)

    def start(self) -> None:
        """Start the NLM proxy Flask server (blocking)."""
        has_cookies = bool(_load_cookies())
        if has_cookies:
            logger.info("NLM Proxy: cookies loaded — live NLM access active")
        else:
            logger.warning(
                "NLM Proxy: no auth cookies found. "
                "POST /cookies/import with a NotebookLM HAR file to enable live access. "
                "Cookie file: %s",
                _COOKIES_FILE,
            )
        app = get_nlm_proxy_app()
        logger.info("NLM Live Proxy starting on %s:%d", self.host, self.port)
        app.run(host=self.host, port=self.port, debug=False, threaded=True)


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    )
    port = int(os.environ.get("NLM_PROXY_PORT", "8800"))
    logger.info("Starting NLM Live Proxy on port %d", port)
    logger.info("Cookie file: %s", _COOKIES_FILE)
    logger.info("To import cookies: POST /cookies/import with {har_path: '...'}")
    create_nlm_proxy_app().run(
        host="0.0.0.0", port=port, debug=False, threaded=True
    )
