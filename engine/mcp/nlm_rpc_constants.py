"""NLM RPC constants, rate limiter, and registry helpers.

Extracted from nlm_live_proxy.py for reuse across NLM integration modules.
Contains:
- Build label defaults (_DEFAULT_BL, _DEFAULT_BL_DATE)
- _RateLimiter class and singleton
- All RPC_* and GRPC_* constants (resolved via _rpc() from YAML registry)
- Response length and document type constants
- _WRITE_CONFIG / _SOURCE_CONFIG shared payloads
- _GRPC_CHAT_URL endpoint
- _is_valid_nlm_build_label() validator
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.config import get_config

try:
    from engine.integrations.nlm_rpc_registry import get_rpc_registry as _get_registry
except Exception as e:
    logging.getLogger(__name__).debug("[NLMRpcConstants] RPC registry unavailable (operation=import): %s", e)
    _get_registry = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

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
    except Exception as e:
        logger.debug("[NLMRpcConstants] Config unavailable, using default rate limit (operation=get_rate_limit): %s", e)
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
        except Exception as e:
            logger.debug("[NLMRpcConstants] YAML registry lookup failed (operation=resolve_rpc_id): %s", e)
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

# ──── gRPC-web method names (heap-discovered) ──────────────────────────────
# These use method NAMES (not rpcids) and are invoked via NLMDirectClient._grpc_call().
# Discovered via CDP heap snapshot diffing across 3 sessions (2026-03 sprint).

# Artifact operations
GRPC_CREATE_ARTIFACT           = "CreateArtifact"
GRPC_DERIVE_ARTIFACT           = "DeriveArtifact"
GRPC_GENERATE_ARTIFACT         = "GenerateArtifact"
GRPC_GET_ARTIFACT_USER_STATE   = "GetArtifactUserState"
GRPC_UPSERT_ARTIFACT_USER_STATE = "UpsertArtifactUserState"

# Source operations
GRPC_CHECK_SOURCE_FRESHNESS    = "CheckSourceFreshness"
GRPC_DISCOVER_SOURCES_ASYNC    = "DiscoverSourcesAsync"
GRPC_DISCOVER_SOURCES_MANIFOLD = "DiscoverSourcesManifold"
GRPC_CANCEL_DISCOVER_SOURCES   = "CancelDiscoverSourcesJob"
GRPC_FINISH_DISCOVER_SOURCES   = "FinishDiscoverSourcesRun"
GRPC_MUTATE_SOURCE             = "MutateSource"
GRPC_REFRESH_SOURCE            = "RefreshSource"
GRPC_DELETE_SOURCES_BULK       = "DeleteSources"

# Project operations
GRPC_MUTATE_PROJECT            = "MutateProject"
GRPC_DELETE_PROJECTS           = "DeleteProjects"
GRPC_LIST_FEATURED_PROJECTS    = "ListFeaturedProjects"
GRPC_UPDATE_FEATURED_STATUS    = "UpdateFeaturedNotebookStatus"

# Chat operations
GRPC_DELETE_CHAT_TURNS         = "DeleteChatTurns"
GRPC_LIST_CHAT_SESSIONS        = "ListChatSessions"

# Notes
GRPC_MUTATE_NOTE               = "MutateNote"

# Account
GRPC_GET_OR_CREATE_ACCOUNT     = "GetOrCreateAccount"

# Moderation
GRPC_REPORT_CONTENT            = "ReportContent"

# Suggestions
GRPC_GENERATE_PROMPT_SUGGESTIONS = "GeneratePromptSuggestions"
GRPC_GENERATE_REPORT_SUGGESTIONS = "GenerateReportSuggestions"

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
# v1.50.2 [2026-03-23] — Updated from [[2,1]] to [[2,1,3]] per Chrome MCP capture.
# The third element (3) was added in the March 2026 NLM deployment.
# Old format [[2,1]] causes HTTP 400 on ciyUvf (GenerateDoc).
_WRITE_CONFIG = [2, None, None,
                 [1, None, None, None, None, None, None, None, None, None, [1]],
                 [[2, 1, 3]]]

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
    except Exception as e:
        logger.debug("[NLMRpcConstants] Shared config load failed (operation=init): %s", e)

# gRPC endpoint for real free-form chat (GenerateFreeFormStreamed)
_GRPC_CHAT_URL = (
    "https://notebooklm.google.com/_/LabsTailwindUi/data/"
    "google.internal.labs.tailwind.orchestration.v1"
    ".LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
)


def _is_valid_nlm_build_label(build_label: Optional[str]) -> bool:
    """Return True when a build label matches NotebookLM's frontend pattern."""
    return bool(build_label and build_label.startswith("boq_labs-tailwind-frontend_"))
