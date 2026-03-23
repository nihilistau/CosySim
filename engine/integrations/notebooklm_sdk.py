"""
NotebookLM SDK
==============

Complete Python SDK for Google NotebookLM — wraps all reverse-engineered
batchexecute RPCs and gRPC-web streaming methods into a clean, documented,
self-healing interface.

**Designed for agents and developers.** Every method has docstrings, type hints,
usage examples, gotchas, and notes. RPC IDs resolve dynamically from the YAML
registry so when Google rotates them, update the registry and everything works.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial SDK: 37 rpcids, 24 gRPC methods, full docs

Architecture:
    NotebookLMSDK (this file)
        ├── NLMRpcRegistry (config/nlm_rpcids.yaml) — dynamic rpcid resolution
        ├── nlm_rpc_constants.py — hardcoded fallbacks if registry unavailable
        ├── nlm_operations.py — payload construction + response parsing
        ├── nlm_archive.py — composite operations (export, download)
        ├── nlm_transport.py — batchexecute HTTP layer
        ├── nlm_auth.py — cookie/session management
        └── nlm_hybrid.py — dual-backend router (batchexecute + Node bridge)

Usage:
    from engine.integrations.notebooklm_sdk import NotebookLMSDK

    sdk = NotebookLMSDK()  # Auto-loads cookies + session tokens

    # List notebooks
    notebooks = sdk.list_notebooks()

    # Ask a question (grounded in sources)
    answer = sdk.ask("notebook-uuid", "What are the key findings?")

    # Add a source
    sdk.add_source_url("notebook-uuid", "https://example.com/paper.pdf")

    # Generate study guide
    guide = sdk.generate_guide("notebook-uuid", style="study_guide")
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import IntEnum, Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# ──── Constants & Enums ───────────────────────────────────────────────


class DocType(IntEnum):
    """Document generation types.

    Used by generate_document() and save_note_report().

    Example:
        sdk.generate_document("nb-id", source_ids, doc_type=DocType.BRIEF)
    """

    BRIEF = 2        # Standard brief (~1 page)
    DEEP_RESEARCH = 9  # Long-form deep research note


class AudioStyle(IntEnum):
    """Audio overview generation styles.

    Each style produces a different podcast format from notebook sources.

    Example:
        sdk.generate_audio("nb-id", style=AudioStyle.DEBATE)
    """

    DEEP_DIVE = 1   # ~30 min, two hosts, thorough exploration
    BRIEF = 2       # ~5 min, quick summary
    CRITIQUE = 3    # Critical analysis of the material
    DEBATE = 4      # Two hosts with opposing viewpoints


class GuideType(str, Enum):
    """Study guide generation types.

    Example:
        sdk.generate_guide("nb-id", style=GuideType.FAQ)
    """

    STUDY_GUIDE = "study_guide"
    FAQ = "faq"
    BRIEFING = "briefing_doc"
    TABLE_OF_CONTENTS = "toc"
    TIMELINE = "timeline"


class SourceType(IntEnum):
    """Source format types returned in source metadata.

    These are READ-ONLY identifiers — you don't pass them when adding sources.
    The SDK auto-detects source type from the URL/content.
    """

    URL = 1
    PDF = 2
    TEXT = 3
    YOUTUBE = 7


class ResponseLength(IntEnum):
    """Response verbosity control.

    GOTCHA: Not all RPCs respect this. Currently only used by AI summary
    and document generation.
    """

    SHORTER = 2    # Condensed response
    DEFAULT = 4    # Standard verbosity (most RPCs)
    LONGER = 1     # More detailed response


# ──── Payload Templates ──────────────────────────────────────────────
# These are the "magic arrays" that Google's batchexecute expects.
# Discovered via HAR capture (2026-02-26 through 2026-03-01).
# Do NOT modify without a fresh HAR confirming the new format.


WRITE_CONFIG = [
    2,       # [0] Document type (overridden per-call)
    None,    # [1] Reserved
    None,    # [2] Reserved
    [1, None, None, None, None, None, None, None, None, None, [1]],
    #  [3] Source config envelope — [3][0]=create flag, [3][10]=feature flags
    [[2, 1]],
    #  [4] Model quality marker — [2, 1] = standard quality
]
"""Write config template for document generation and note saving.

Position [0] is overridden with DocType value per call.
Position [4] controls model quality: [[2, 1]] = standard, [[3, 1]] = high.

GOTCHA: This array must match EXACTLY what the browser sends.
Changing any None position to a value may cause silent failures.
"""

SOURCE_CONFIG = [1, None, None, None, None, None, None, None, None, None, [1]]
"""Source config template for add_source operations.

Position [0] = 1 means "create new source".
Position [10] = [1] is the feature flags marker.

Used by: add_source_url, add_text_source, register_file_sources.
"""

# ──── Source Object Templates ────────────────────────────────────────
# CRITICAL GOTCHA: URL position differs by source type!
#   Regular URL  → position [2] (string)
#   YouTube URL  → position [7] (list containing string)
#   Text content → position [1] ([title, content]), position [3] = 3

_SOURCE_TEMPLATE = [None, None, None, None, None, None, None, None, None, None, 1]
"""Base source object (11 elements). Position [10] is always 1 (flags).

To create a source object:
    Regular URL:  template[2] = "https://example.com"
    YouTube:      template[7] = ["https://youtube.com/watch?v=xyz"]
    Text:         template[1] = ["Title", "Content..."], template[3] = 3
"""


# ──── Tier Markers ───────────────────────────────────────────────────

TIER_FREE = [1]
TIER_PRO = [2]     # Default — used in most payloads
TIER_ULTRA = [3]
"""Tier markers passed in payloads. Controls quota accounting on Google's side.

GOTCHA: These are client-side hints. Google accepts whatever you send.
Using TIER_PRO on a free account doesn't upgrade you — it just tells the
server to use the pro model tier for processing.
"""


# ──── Chat Response Config ───────────────────────────────────────────

CHAT_RESPONSE_CONFIG = [2, None, [1], [1]]
"""Response config for GenerateFreeFormStreamed (gRPC chat).

Position [0] = 2 (response mode)
Position [2] = [1] (include source citations)
Position [3] = [1] (include thinking/reasoning)

Passed at position [3] of the 9-element chat payload.
"""


# ──── Rate Limits & Timeouts ─────────────────────────────────────────

DEFAULT_RATE_LIMIT_SECONDS = 1.5
"""Minimum gap between batchexecute calls. Google throttles (429) or
silently drops responses if you go faster.

Batch calls (10 RPCs in one HTTP request) count as ONE request.
"""

MAX_BATCH_SIZE = 10
"""Maximum RPCs per batchexecute HTTP request. Google silently drops extras."""

MAX_QUESTIONS_PER_BATCH = 5
"""Default max questions per ask_batch call."""

TIMEOUT_BATCHEXECUTE = 60
"""HTTP timeout for batchexecute calls (seconds)."""

TIMEOUT_GRPC_CHAT = 120
"""HTTP timeout for GenerateFreeFormStreamed (seconds). Longer because
complex queries trigger Gemini thinking which takes time."""

TIMEOUT_FILE_UPLOAD = 300
"""HTTP timeout for file uploads (seconds)."""

TIMEOUT_SOURCE_POLL = 120
"""Default timeout for wait_for_sources (seconds)."""

SOURCE_POLL_INTERVAL = 3.0
"""Seconds between source indexing status polls."""

BUILD_LABEL_MAX_AGE_DAYS = 8
"""Build label staleness threshold. After this many days, batchexecute
silently returns null for ALL calls (no error, just empty).

When this happens: import a fresh HAR or run CDP auth recovery.
"""


# ──── RPC ID Map ─────────────────────────────────────────────────────
# Format: operation_name → (primary_rpcid, description)
# These are FALLBACK values. The SDK resolves from the YAML registry first.
# When Google rotates rpcids, update config/nlm_rpcids.yaml — NOT this dict.

_RPCID_FALLBACKS: Dict[str, Tuple[str, str]] = {
    # ── Notebook Management ──────────────────────────────────────
    "session_init":         ("ZwVcOc", "Initialize NLM session / get user plan"),
    "list_notebooks":       ("ub2Bae", "List all notebooks for current user"),
    "list_sources":         ("wXbhsf", "List sources in a notebook"),
    "load_notebook":        ("rLM1Ne", "Load notebook with source processing status"),
    "notebook_info":        ("e3bVqc", "Get raw notebook content/document data"),
    "notebook_metadata":    ("mFtdI",  "Fetch metadata for single notebook"),
    "create_notebook":      ("CCqFvf", "Create new empty notebook"),
    "rename_notebook":      ("s0tc2d", "Rename a notebook"),
    "delete_notebook":      ("WWINqb", "Delete a notebook by UUID"),
    "share_notebook":       ("dI5Y8",  "Get or create shareable link"),
    "get_shared_notebook":  ("jzEKsc", "Access notebook shared by another user"),

    # ── Source Management ────────────────────────────────────────
    "add_source":           ("izAoDd", "Add URL/YouTube/text source to notebook"),
    "delete_source":        ("tGMBJ",  "Delete a source from notebook"),
    "read_source":          ("tr032e", "Read full text content of a source"),
    "source_detail":        ("hizoJc", "Get detailed metadata for single source"),
    "source_metadata":      ("K4YCPe", "Fetch metadata for specific source"),
    "sources_advanced":     ("jtGGne", "List sources with rich metadata"),
    "register_files":       ("o4cbdc", "Register file uploads (step 1 of upload)"),
    "process_source":       ("bfEAsb", "Trigger reprocessing of failed/stale source"),

    # ── Q&A & Chat ───────────────────────────────────────────────
    "create_note":          ("CYK0Xb", "Citation-annotated Q&A (NOT real chat)"),
    "streaming_chat":       ("tJHFsf", "Multi-turn streaming chat (via gRPC)"),

    # ── Notes & Artifacts ────────────────────────────────────────
    "save_note":            ("cYAfTb", "Live auto-save note content"),
    "save_report":          ("R7cb6c", "Save a note/report artifact"),
    "list_artifacts":       ("gArtLc", "List notes and saved artifacts"),

    # ── Document Generation ──────────────────────────────────────
    "generate_doc":         ("ciyUvf", "Generate document from selected sources"),
    "generate_guide":       ("xqEXEf", "Generate study guide/FAQ/briefing/timeline"),
    "generate_mind_map":    ("yyryJe", "Generate D3-format mind map from sources"),

    # ── Audio ────────────────────────────────────────────────────
    "list_audio_types":     ("sqTeoe", "List available audio overview styles"),

    # ── Research ─────────────────────────────────────────────────
    "fast_research":        ("Ljjv0c", "Start fast research session"),
    "deep_research":        ("QA9ei",  "Start async deep research session"),
    "add_research_source":  ("LBwxtb", "Add AI-generated research doc as source"),

    # ── User & Account ───────────────────────────────────────────
    "user_profile":         ("JFMDGd", "Get user email, name, queries remaining"),
    "ai_summary":           ("VfAZjd", "Fetch AI summary of notebook"),
    "feature_flags":        ("ozz5Z",  "Get account state / feature flags / quota"),
    "get_locale":           ("DYBcR",  "Return user locale/language preferences"),

    # ── Threads & History ────────────────────────────────────────
    "get_thread_ids":       ("hPTbtc", "Get conversation thread IDs"),
    "read_thread":          ("khqZz",  "Read all messages in a thread"),
    "get_chat_history":     ("GzgSEd", "Get full chat history for notebook"),
    "delete_chat_history":  ("GfmCOc", "Delete entire chat history"),

    # ── Sync & Export ────────────────────────────────────────────
    "sync_notes":           ("cFji9",  "Delta poll for note changes"),
    "export_to_sheets":     ("Krh3pd", "Export artifact/table to Google Sheets"),
}

# ──── gRPC Methods (Heap-Discovered) ─────────────────────────────────
# These use the LabsTailwindOrchestrationService endpoint directly,
# NOT batchexecute. Payload formats are partially known from traffic capture.

_GRPC_METHODS: Dict[str, str] = {
    # ── Implemented ──────────────────────────────────────────────
    "GenerateFreeFormStreamed": "Real conversational chat (streaming response)",

    # ── Artifact Operations (discovered, not yet implemented) ────
    "CreateArtifact":              "Create a new artifact (note, guide, etc.)",
    "DeriveArtifact":              "Create artifact derived from existing one",
    "GenerateArtifact":            "AI-generate an artifact from sources",
    "GetArtifactUserState":        "Get user's state for an artifact",
    "UpsertArtifactUserState":     "Update user's artifact state",

    # ── Source Discovery (discovered, not yet implemented) ───────
    "CheckSourceFreshness":        "Check if a source needs refreshing",
    "DiscoverSourcesAsync":        "Auto-discover relevant sources (async job)",
    "DiscoverSourcesManifold":     "Multi-signal source discovery",
    "CancelDiscoverSourcesJob":    "Cancel running source discovery",
    "FinishDiscoverSourcesRun":    "Complete a source discovery run",
    "MutateSource":                "Modify an existing source",
    "RefreshSource":               "Force-refresh a source's content",
    "DeleteSources":               "Bulk delete sources",

    # ── Project/Notebook (discovered, not yet implemented) ───────
    "MutateProject":               "Modify notebook properties",
    "DeleteProjects":              "Bulk delete notebooks",
    "ListFeaturedProjects":        "List featured/public notebooks",
    "UpdateFeaturedNotebookStatus": "Toggle featured status",

    # ── Chat & Notes (discovered, not yet implemented) ───────────
    "DeleteChatTurns":             "Delete specific chat messages",
    "ListChatSessions":            "List all chat sessions",
    "MutateNote":                  "Modify an existing note",

    # ── Account (discovered, not yet implemented) ────────────────
    "GetOrCreateAccount":          "Initialize user account",
    "ReportContent":               "Report inappropriate content",

    # ── AI Suggestions (discovered, not yet implemented) ─────────
    "GeneratePromptSuggestions":   "Get suggested prompts for notebook",
    "GenerateReportSuggestions":   "Get suggested reports to generate",
}


# ──── Endpoints ──────────────────────────────────────────────────────

NLM_BASE = "https://notebooklm.google.com"
NLM_BATCHEXECUTE = f"{NLM_BASE}/_/LabsTailwindUi/data/batchexecute"
NLM_GRPC_SERVICE = (
    f"{NLM_BASE}/_/LabsTailwindUi/data/"
    "google.internal.labs.tailwind.orchestration.v1."
    "LabsTailwindOrchestrationService"
)
NLM_CHAT_ENDPOINT = f"{NLM_GRPC_SERVICE}/GenerateFreeFormStreamed"


# ──── Auth Constants ─────────────────────────────────────────────────

REQUIRED_COOKIES = [
    "SID", "SSID", "APISID", "SAPISID", "HSID",
    "__Secure-3PSID", "__Secure-3PAPISID",
]
"""Minimum cookies required for batchexecute auth.

GOTCHA: Do NOT add Authorization: SAPISIDHASH to batchexecute requests.
NLM batchexecute auth is ONLY via Cookie + 'at' CSRF token in POST body.
Adding SAPISIDHASH causes HTTP 400 error code 3.

Other Google services (Colab, Sheets, Drive) DO need SAPISIDHASH.
"""

WIZ_GLOBAL_DATA_KEYS = {
    "build_label": ["cfb2h", "QrtxK"],      # bl parameter
    "session_id":  ["FdrFJe", "IxjpMA"],     # f.sid parameter
    "csrf_token":  ["SNlM0e"],               # at parameter
}
"""Keys in window.WIZ_global_data that contain session parameters.

Google obfuscates these per-build — multiple keys are checked as fallbacks.
The build label can also be extracted via regex: boq_labs-tailwind-frontend_*
"""

BUILD_LABEL_PATTERN = re.compile(
    r"boq_labs-tailwind-frontend_\d{8}\.\d{2}_p\d"
)
"""Regex pattern for valid build labels.

Format: boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
Example: boq_labs-tailwind-frontend_20260319.10_p0

Changes approximately weekly when Google deploys new frontend builds.
"""


# ──── Data Classes ───────────────────────────────────────────────────


@dataclass
class NLMNotebook:
    """A NotebookLM notebook."""

    id: str
    name: str
    emoji: str = ""
    source_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_shared: bool = False
    raw: Optional[Dict[str, Any]] = None


@dataclass
class NLMSource:
    """A source within a notebook."""

    id: str
    title: str
    source_type: SourceType = SourceType.URL
    word_count: int = 0
    url: Optional[str] = None
    status: str = "ready"  # ready, processing, failed
    raw: Optional[Dict[str, Any]] = None


@dataclass
class NLMAnswer:
    """An answer from Q&A or chat."""

    answer: str
    answer_id: Optional[str] = None
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    question: str = ""
    raw: Optional[Dict[str, Any]] = None


@dataclass
class NLMNote:
    """A note/artifact in a notebook."""

    id: str
    title: str
    content: str = ""
    note_type: int = 2
    raw: Optional[Dict[str, Any]] = None


@dataclass
class NLMSession:
    """Session parameters for batchexecute calls."""

    build_label: str = ""
    session_id: str = ""
    csrf_token: str = ""
    cookies: Dict[str, str] = field(default_factory=dict)
    loaded_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        """Check if session has minimum required parameters."""
        return bool(self.build_label and self.cookies)

    @property
    def bl_age_days(self) -> float:
        """Days since build label was captured."""
        if not self.loaded_at:
            return 999.0
        return (time.time() - self.loaded_at) / 86400

    @property
    def is_stale(self) -> bool:
        """True if build label is older than BUILD_LABEL_MAX_AGE_DAYS."""
        return self.bl_age_days > BUILD_LABEL_MAX_AGE_DAYS


@dataclass
class SDKStats:
    """Usage statistics for the SDK instance."""

    asks: int = 0
    batch_asks: int = 0
    chat_messages: int = 0
    sources_added: int = 0
    sources_deleted: int = 0
    notebooks_created: int = 0
    docs_generated: int = 0
    errors: int = 0
    rpc_calls: int = 0
    grpc_calls: int = 0
    cache_hits: int = 0
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.__dict__,
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }


# ──── SDK Class ──────────────────────────────────────────────────────


class NotebookLMSDK:
    """Complete SDK for Google NotebookLM.

    Wraps all reverse-engineered batchexecute RPCs and gRPC-web streaming
    methods into a clean, documented, self-healing interface.

    RPC IDs are resolved dynamically:
        1. YAML registry (config/nlm_rpcids.yaml) — freshest, auto-updated by ARGUS
        2. Hardcoded fallbacks (_RPCID_FALLBACKS) — last resort

    When Google rotates rpcids (approximately weekly):
        - Update config/nlm_rpcids.yaml
        - Or run ARGUS: python scripts/argus/orchestrator.py --target notebooklm
        - The SDK automatically picks up the new IDs

    Session parameters (build_label, session_id, csrf_token) are auto-loaded
    from disk (data/nlm_meta.json) and refreshed via CDP when stale.

    Example:
        sdk = NotebookLMSDK()

        # Check health
        print(sdk.health())

        # List notebooks
        for nb in sdk.list_notebooks():
            print(f"{nb.name} ({nb.source_count} sources)")

        # Ask a question
        answer = sdk.ask("notebook-uuid", "Summarize the key findings")
        print(answer.answer)
        print(f"Citations: {answer.citations}")

        # Add sources
        sdk.add_source_url("nb-uuid", "https://arxiv.org/abs/2401.12345")
        sdk.add_source_text("nb-uuid", "My Notes", "Content here...")
        sdk.wait_for_sources("nb-uuid")

        # Generate study guide
        guide = sdk.generate_guide("nb-uuid", style=GuideType.FAQ)

    GOTCHAS:
        - Do NOT add SAPISIDHASH header to batchexecute (causes 400)
        - Build labels expire silently (~weekly) — returns null, no error
        - YouTube URLs go at position [7] as a list, not position [2]
        - Real chat uses gRPC streaming, not batchexecute
        - Source IDs are session-scoped after Gemini v2 migration
        - Rate limit: 1.5s minimum between calls (configurable)
    """

    def __init__(
        self,
        cookies: Optional[Dict[str, str]] = None,
        auto_load: bool = True,
    ) -> None:
        """Initialize the SDK.

        Args:
            cookies: Google session cookies. If None, auto-loads from disk.
            auto_load: If True, load cookies and session from disk on init.
        """
        self._session = NLMSession()
        self._stats = SDKStats()
        self._registry = None
        self._last_call_time = 0.0
        self._rate_limit = DEFAULT_RATE_LIMIT_SECONDS

        if cookies:
            self._session.cookies = cookies
        elif auto_load:
            self._load_session()

        # Try to load the YAML registry for dynamic rpcid resolution
        try:
            from engine.integrations.nlm_rpc_registry import get_rpc_registry
            self._registry = get_rpc_registry()
        except Exception:
            logger.debug("[NotebookLMSDK] YAML registry unavailable, using fallbacks")

    # ──── RPC Resolution ─────────────────────────────────────────

    def rpcid(self, operation: str) -> str:
        """Resolve an operation name to its current rpcid.

        Resolution order:
            1. YAML registry (config/nlm_rpcids.yaml)
            2. Hardcoded fallbacks (_RPCID_FALLBACKS)

        When Google rotates rpcids, update the YAML registry.
        The SDK will automatically use the new IDs.

        Args:
            operation: Operation name (e.g., "list_notebooks", "add_source")

        Returns:
            The rpcid string (e.g., "ub2Bae")

        Raises:
            KeyError: If operation is unknown

        Example:
            sdk.rpcid("list_notebooks")  # "ub2Bae"
            sdk.rpcid("add_source")      # "izAoDd"
        """
        # Try YAML registry first
        if self._registry:
            try:
                rid = self._registry.get_rpcid(operation)
                if rid:
                    return rid
            except Exception:
                pass

        # Fall back to hardcoded
        if operation in _RPCID_FALLBACKS:
            return _RPCID_FALLBACKS[operation][0]

        raise KeyError(f"Unknown operation: {operation}")

    def list_operations(self) -> Dict[str, str]:
        """List all known operations with their current rpcids.

        Returns:
            Dict of operation_name → rpcid

        Example:
            for op, rid in sdk.list_operations().items():
                print(f"{op:25s} → {rid}")
        """
        result = {}
        for op, (rid, _) in _RPCID_FALLBACKS.items():
            try:
                result[op] = self.rpcid(op)
            except KeyError:
                result[op] = rid
        return result

    def list_grpc_methods(self) -> Dict[str, str]:
        """List all known gRPC methods with descriptions.

        These methods use the LabsTailwindOrchestrationService endpoint
        directly (not batchexecute). Some are implemented, most are
        discovered via ARGUS heap analysis and await implementation.

        Returns:
            Dict of method_name → description
        """
        return dict(_GRPC_METHODS)

    # ──── Session Management ─────────────────────────────────────

    def _load_session(self) -> None:
        """Load cookies and session tokens from disk.

        Reads from:
            - data/nlm_cookies.json (cookies)
            - data/nlm_meta.json (build_label, session_id, csrf_token)
        """
        try:
            from engine.mcp.nlm_auth import _load_cookies, _load_meta
            self._session.cookies = _load_cookies()
            meta = _load_meta()
            self._session.build_label = meta.get("bl", "")
            self._session.session_id = str(meta.get("f_sid", ""))
            self._session.csrf_token = meta.get("at", "")
            self._session.loaded_at = time.time()
            logger.debug(
                "[NotebookLMSDK] Session loaded (bl=%s, cookies=%d)",
                self._session.build_label[:30],
                len(self._session.cookies),
            )
        except Exception as e:
            logger.debug("[NotebookLMSDK] Session load failed (operation=init): %s", e)

    def refresh_session(self) -> bool:
        """Refresh session tokens via CDP (Chrome DevTools Protocol).

        Connects to Chrome on port 9223, extracts fresh build_label,
        session_id, and csrf_token from the running NLM tab.

        Returns:
            True if refresh succeeded

        GOTCHA: Requires Chrome running with --remote-debugging-port=9223
        and a NotebookLM tab open.
        """
        try:
            from engine.nexus.cdp_auth_recovery import run_recovery
            status = run_recovery()
            if status.healthy:
                self._load_session()
                return True
            return False
        except Exception as e:
            logger.debug("[NotebookLMSDK] CDP refresh failed (operation=refresh): %s", e)
            return False

    @property
    def session(self) -> NLMSession:
        """Current session state (read-only)."""
        return self._session

    @property
    def stats(self) -> SDKStats:
        """Usage statistics for this SDK instance."""
        return self._stats

    def health(self) -> Dict[str, Any]:
        """Full health check.

        Returns:
            Dict with: has_cookies, cookie_count, build_label, bl_age_days,
            bl_stale, has_csrf, has_session_id, registry_available, stats
        """
        return {
            "has_cookies": bool(self._session.cookies),
            "cookie_count": len(self._session.cookies),
            "build_label": self._session.build_label[:40] if self._session.build_label else None,
            "bl_age_days": round(self._session.bl_age_days, 1),
            "bl_stale": self._session.is_stale,
            "has_csrf": bool(self._session.csrf_token),
            "has_session_id": bool(self._session.session_id),
            "registry_available": self._registry is not None,
            "rate_limit_seconds": self._rate_limit,
            "stats": self._stats.to_dict(),
        }

    # ──── Rate Limiter ───────────────────────────────────────────

    def _rate_wait(self) -> None:
        """Enforce minimum gap between calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_call_time = time.time()

    # ──── Transport ──────────────────────────────────────────────

    def _call_rpc(
        self,
        operation: str,
        args: Any,
        notebook_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Any]:
        """Execute a batchexecute RPC call.

        Handles: rate limiting, rpcid resolution, payload encoding,
        response parsing, and auto-retry on stale build label.

        Args:
            operation: Operation name (e.g., "list_notebooks")
            args: Payload array (will be JSON-encoded)
            notebook_id: If set, included in source-path URL param

        Returns:
            (rpcid, parsed_data) tuple. data is None on failure.

        GOTCHA: If ALL results are None, build label is probably stale.
        The transport layer auto-retries once after refreshing tokens.
        """
        self._rate_wait()
        self._stats.rpc_calls += 1

        rid = self.rpcid(operation)

        try:
            from engine.mcp.nlm_transport import _batchexecute
            rpc_result, data = _batchexecute(
                rid,
                json.dumps(args),
                self._session.cookies,
                notebook_id=notebook_id,
            )
            return rpc_result, data
        except Exception as e:
            self._stats.errors += 1
            logger.debug(
                "[NotebookLMSDK] RPC failed (operation=%s, rpcid=%s): %s",
                operation, rid, e,
            )
            return rid, {"error": str(e)}

    def _call_grpc(
        self,
        method: str,
        payload: Any,
        timeout: int = TIMEOUT_GRPC_CHAT,
    ) -> Dict[str, Any]:
        """Execute a gRPC-web call to LabsTailwindOrchestrationService.

        Args:
            method: gRPC method name (e.g., "GenerateFreeFormStreamed")
            payload: Request payload (will be JSON-encoded)
            timeout: HTTP timeout in seconds

        Returns:
            Parsed response dict. Contains "error" key on failure.

        GOTCHA: Response is streaming — each chunk contains the FULL
        answer text (not deltas). Use the last chunk's text.
        """
        self._rate_wait()
        self._stats.grpc_calls += 1

        endpoint = f"{NLM_GRPC_SERVICE}/{method}"

        try:
            import urllib.request
            import urllib.parse

            bl = self._session.build_label
            outer = json.dumps([None, json.dumps(payload)])
            body = f"f.req={urllib.parse.quote(outer)}"
            if self._session.csrf_token:
                body += f"&at={urllib.parse.quote(self._session.csrf_token)}"

            url = f"{endpoint}?bl={bl}&rt=c"
            cookie_str = "; ".join(
                f"{k}={v}" for k, v in self._session.cookies.items()
            )

            req = urllib.request.Request(
                url,
                data=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Cookie": cookie_str,
                    "X-Same-Domain": "1",
                    "Origin": NLM_BASE,
                    "Referer": f"{NLM_BASE}/",
                },
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            return {"raw": raw, "status": "ok"}

        except Exception as e:
            self._stats.errors += 1
            logger.debug(
                "[NotebookLMSDK] gRPC failed (operation=%s): %s", method, e,
            )
            return {"error": str(e)}

    # ──── Notebook Operations ────────────────────────────────────

    def list_notebooks(self) -> List[NLMNotebook]:
        """List all notebooks for the current user.

        Returns:
            List of NLMNotebook objects

        Example:
            for nb in sdk.list_notebooks():
                print(f"{nb.name} ({nb.id})")
        """
        try:
            from engine.mcp.nlm_operations import ask_question  # noqa: F401
            from engine.mcp.nlm_transport import _batchexecute, _extract_sources

            self._rate_wait()
            self._stats.rpc_calls += 1
            rid = self.rpcid("list_sources")
            _, data = _batchexecute(
                rid,
                json.dumps([None, 1, None, TIER_PRO]),
                self._session.cookies,
            )

            if data is None:
                return []

            notebooks = []
            nb_uuids = re.findall(
                r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                json.dumps(data) if not isinstance(data, str) else data,
            )

            # Extract notebook names and source counts from response
            try:
                from engine.mcp.nlm_transport import _extract_sources
                name, sources = _extract_sources(data)
                if name:
                    notebooks.append(NLMNotebook(
                        id=nb_uuids[0] if nb_uuids else "",
                        name=name,
                        source_count=len(sources),
                        raw=data,
                    ))
            except Exception:
                pass

            return notebooks

        except Exception as e:
            self._stats.errors += 1
            logger.debug("[NotebookLMSDK] list_notebooks failed (operation=list): %s", e)
            return []

    def create_notebook(self, name: str = "Untitled") -> Dict[str, Any]:
        """Create a new empty notebook.

        Args:
            name: Notebook title

        Returns:
            Dict with notebook_id and metadata

        Example:
            result = sdk.create_notebook("My Research")
        """
        self._stats.notebooks_created += 1
        _, data = self._call_rpc("create_notebook", [])
        return {"data": data}

    def rename_notebook(self, notebook_id: str, new_name: str) -> Dict[str, Any]:
        """Rename an existing notebook.

        Args:
            notebook_id: Notebook UUID
            new_name: New name string

        Returns:
            Dict with renamed status, notebook_id, name

        GOTCHA: This was WRONGLY mapped as "chat" in SDK v2.x.
        Corrected in v3.1 (2026-02-28).

        Example:
            sdk.rename_notebook("uuid", "Better Name")
        """
        try:
            from engine.mcp.nlm_operations import rename_notebook
            return rename_notebook(notebook_id, new_name, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def delete_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Delete a notebook by UUID.

        Args:
            notebook_id: Notebook UUID to delete

        Returns:
            Dict with deletion status
        """
        _, data = self._call_rpc("delete_notebook", [notebook_id])
        return {"deleted": data is not None, "notebook_id": notebook_id}

    # ──── Source Operations ──────────────────────────────────────

    def add_source_url(self, notebook_id: str, url: str) -> Dict[str, Any]:
        """Add a URL source to a notebook.

        Auto-detects YouTube URLs and uses the correct payload position.

        Args:
            notebook_id: Target notebook UUID
            url: Source URL (web page, PDF, or YouTube)

        Returns:
            Dict with source_id, url, status

        GOTCHA: YouTube URLs go at position [7] as a LIST, not position [2].
        This SDK handles it automatically.

        Example:
            sdk.add_source_url("nb-id", "https://arxiv.org/abs/2401.12345")
            sdk.add_source_url("nb-id", "https://youtube.com/watch?v=xyz")
        """
        self._stats.sources_added += 1
        try:
            from engine.mcp.nlm_operations import add_source_url
            return add_source_url(notebook_id, url, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def add_source_text(
        self,
        notebook_id: str,
        title: str,
        content: str,
    ) -> Dict[str, Any]:
        """Add inline text/markdown as a source.

        Args:
            notebook_id: Target notebook UUID
            title: Source title
            content: Text or markdown content

        Returns:
            Dict with source_id, title, status

        Example:
            sdk.add_source_text("nb-id", "My Notes", "# Key Findings\\n...")
        """
        self._stats.sources_added += 1
        try:
            from engine.mcp.nlm_operations import add_text_source
            return add_text_source(notebook_id, title, content, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def delete_source(self, source_id: str) -> Dict[str, Any]:
        """Delete a source from a notebook.

        Args:
            source_id: Source UUID to delete

        Returns:
            Dict with deleted status

        Example:
            sdk.delete_source("source-uuid")
        """
        self._stats.sources_deleted += 1
        try:
            from engine.mcp.nlm_operations import delete_source
            return delete_source(source_id, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def list_sources(self, notebook_id: str) -> List[NLMSource]:
        """List all sources in a notebook.

        Args:
            notebook_id: Notebook UUID

        Returns:
            List of NLMSource objects

        Example:
            for src in sdk.list_sources("nb-id"):
                print(f"{src.title} ({src.word_count} words)")
        """
        _, data = self._call_rpc(
            "list_sources",
            [None, 1, None, TIER_PRO],
            notebook_id=notebook_id,
        )

        if data is None:
            return []

        sources = []
        try:
            from engine.mcp.nlm_transport import _extract_sources
            _, raw_sources = _extract_sources(data)
            for s in raw_sources:
                sources.append(NLMSource(
                    id=s.get("id", ""),
                    title=s.get("title", ""),
                    word_count=s.get("word_count", 0),
                    url=s.get("url", ""),
                    raw=s,
                ))
        except Exception:
            pass

        return sources

    def read_source(self, source_id: str) -> Dict[str, Any]:
        """Read the full text content of a source.

        Args:
            source_id: Source UUID

        Returns:
            Dict with source_id, content (markdown), word_count

        GOTCHA: Source UUID is QUADRUPLE-NESTED in the payload:
            [[[[source_id]]]]

        Example:
            result = sdk.read_source("source-uuid")
            print(result["content"])
        """
        try:
            from engine.mcp.nlm_operations import read_source
            return read_source(source_id, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def wait_for_sources(
        self,
        notebook_id: str,
        timeout: int = TIMEOUT_SOURCE_POLL,
        poll_interval: float = SOURCE_POLL_INTERVAL,
    ) -> bool:
        """Block until all sources are indexed or timeout.

        Args:
            notebook_id: Notebook UUID
            timeout: Max wait time in seconds (default 120)
            poll_interval: Seconds between polls (default 3.0)

        Returns:
            True if all sources are ready, False on timeout

        Example:
            sdk.add_source_url("nb-id", "https://example.com")
            ready = sdk.wait_for_sources("nb-id", timeout=60)
        """
        try:
            from engine.mcp.nlm_operations import wait_for_sources
            return wait_for_sources(
                notebook_id, self._session.cookies,
                timeout=timeout, poll_interval=poll_interval,
            )
        except Exception as e:
            self._stats.errors += 1
            return False

    def upload_file(
        self,
        notebook_id: str,
        file_path: str,
    ) -> Dict[str, Any]:
        """Upload a file as a source (2-step: register + upload).

        Supported formats: PDF, TXT, MD, HTML, images, audio, video.

        Args:
            notebook_id: Target notebook UUID
            file_path: Local file path

        Returns:
            Dict with source_id, filename, status

        Example:
            sdk.upload_file("nb-id", "/path/to/paper.pdf")
        """
        self._stats.sources_added += 1
        try:
            from engine.mcp.nlm_operations import register_file_sources, upload_file_to_nlm
            path = Path(file_path)

            # Step 1: Register
            registered = register_file_sources(
                notebook_id, [path.name], self._session.cookies,
            )
            if not registered:
                return {"error": "registration_failed"}

            # Step 2: Upload
            content = path.read_bytes()
            suffix = path.suffix.lower()
            mime_types = {
                ".pdf": "application/pdf", ".txt": "text/plain",
                ".md": "text/plain", ".html": "text/html",
                ".jpg": "image/jpeg", ".png": "image/png",
                ".mp3": "audio/mpeg", ".mp4": "video/mp4",
            }
            mime = mime_types.get(suffix, "application/octet-stream")

            result = upload_file_to_nlm(
                path.name, content, self._session.cookies, mime_type=mime,
            )
            return result

        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    # ──── Q&A Operations ─────────────────────────────────────────

    def ask(
        self,
        notebook_id: str,
        question: str,
    ) -> NLMAnswer:
        """Ask a question grounded in notebook sources (citation mode).

        Uses CYK0Xb (CREATE_NOTE) RPC which returns markdown with
        [source_uuid] citation markers.

        Args:
            notebook_id: Notebook UUID
            question: Question text

        Returns:
            NLMAnswer with answer text, citations, and source references

        NOTE: This is citation-annotated Q&A, NOT real conversational chat.
        For multi-turn conversation, use chat() instead.

        Example:
            answer = sdk.ask("nb-id", "What are the key findings?")
            print(answer.answer)
            print(f"Cited {len(answer.citations)} sources")
        """
        self._stats.asks += 1
        try:
            from engine.mcp.nlm_operations import ask_question
            result = ask_question(notebook_id, question, self._session.cookies)

            if "error" in result:
                self._stats.errors += 1
                return NLMAnswer(answer="", question=question, raw=result)

            citations = re.findall(
                r"\[([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\]",
                result.get("answer", ""),
            )

            return NLMAnswer(
                answer=result.get("answer", ""),
                answer_id=result.get("answer_id"),
                citations=citations,
                question=question,
                raw=result,
            )
        except Exception as e:
            self._stats.errors += 1
            return NLMAnswer(answer="", question=question, raw={"error": str(e)})

    def ask_batch(
        self,
        notebook_id: str,
        questions: List[str],
        max_batch: int = MAX_QUESTIONS_PER_BATCH,
    ) -> List[NLMAnswer]:
        """Ask multiple questions in batch (citation mode).

        Questions are sent in groups of max_batch (default 5) per HTTP request.
        Each batch is rate-limited.

        Args:
            notebook_id: Notebook UUID
            questions: List of question strings
            max_batch: Max questions per HTTP request (default 5)

        Returns:
            List of NLMAnswer objects in same order as questions

        Example:
            answers = sdk.ask_batch("nb-id", [
                "What is the methodology?",
                "What are the results?",
                "What are the limitations?",
            ])
        """
        self._stats.batch_asks += 1
        try:
            from engine.mcp.nlm_operations import ask_questions_batch
            results = ask_questions_batch(
                notebook_id, questions, self._session.cookies,
                max_batch=max_batch,
            )
            return [
                NLMAnswer(
                    answer=r.get("answer", ""),
                    answer_id=r.get("answer_id"),
                    question=q,
                    raw=r,
                )
                for r, q in zip(results, questions)
            ]
        except Exception as e:
            self._stats.errors += 1
            return [NLMAnswer(answer="", question=q, raw={"error": str(e)}) for q in questions]

    def chat(
        self,
        notebook_id: str,
        message: str,
        source_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> NLMAnswer:
        """Real conversational chat via GenerateFreeFormStreamed (gRPC).

        Uses the gRPC streaming endpoint — the only way to have true
        multi-turn conversation with NotebookLM.

        Args:
            notebook_id: Notebook UUID
            message: User message text
            source_ids: Source UUIDs to ground the response in.
                        If None, uses all sources in the notebook.
            thread_id: Thread UUID for conversation continuity.
                       Pass the thread_id from a previous response
                       to continue the conversation.

        Returns:
            NLMAnswer with answer, thread_id (for continuation), message_id

        GOTCHA: Each response chunk contains the FULL answer text (not deltas).
        The SDK extracts the final chunk automatically.

        GOTCHA: Source IDs are session-scoped after Gemini v2 migration.
        IDs from one session may not work in another.

        Example:
            # First message
            r1 = sdk.chat("nb-id", "Explain the methodology")

            # Follow-up (same thread)
            r2 = sdk.chat("nb-id", "How does that compare to X?",
                          thread_id=r1.thread_id)
        """
        self._stats.chat_messages += 1

        # Auto-fetch source IDs if not provided
        if source_ids is None:
            sources = self.list_sources(notebook_id)
            source_ids = [s.id for s in sources]

        try:
            from engine.mcp.nlm_operations import _grpc_ask
            result = _grpc_ask(
                notebook_id, message, source_ids,
                self._session.cookies, thread_id=thread_id,
            )

            if "error" in result:
                self._stats.errors += 1

            return NLMAnswer(
                answer=result.get("answer", ""),
                thread_id=result.get("thread_id"),
                message_id=result.get("message_id"),
                sources=source_ids,
                question=message,
                raw=result,
            )
        except Exception as e:
            self._stats.errors += 1
            return NLMAnswer(answer="", question=message, raw={"error": str(e)})

    # ──── Note & Artifact Operations ─────────────────────────────

    def create_note(
        self,
        notebook_id: str,
        title: str,
        content_html: str = "",
    ) -> Dict[str, Any]:
        """Create a note in a notebook.

        Args:
            notebook_id: Notebook UUID
            title: Note title
            content_html: Note content (HTML or plain text)

        Returns:
            Dict with note_id, title, status

        Example:
            sdk.create_note("nb-id", "My Analysis", "<h1>Key Points</h1>...")
        """
        try:
            from engine.mcp.nlm_operations import create_note
            return create_note(notebook_id, title, content_html, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def save_note(
        self,
        notebook_id: str,
        note_id: str,
        title: str,
        content_html: str,
    ) -> Dict[str, Any]:
        """Save/update an existing note (auto-save style).

        Args:
            notebook_id: Notebook UUID
            note_id: Note UUID to update
            title: Updated title
            content_html: Updated content

        Returns:
            Dict with note_id, title, status

        Example:
            sdk.save_note("nb-id", "note-id", "Updated Title", "<p>New content</p>")
        """
        try:
            from engine.mcp.nlm_operations import save_note
            return save_note(notebook_id, note_id, title, content_html, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def list_artifacts(
        self,
        notebook_id: str,
        filter_str: str = 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"',
    ) -> Dict[str, Any]:
        """List notes and saved artifacts in a notebook.

        Args:
            notebook_id: Notebook UUID
            filter_str: SQL-like filter (default excludes suggested artifacts)

        Returns:
            Dict with artifacts data

        NOTE: Supports SQL-like filter syntax for querying artifacts.

        Example:
            artifacts = sdk.list_artifacts("nb-id")
        """
        _, data = self._call_rpc(
            "list_artifacts",
            [TIER_PRO, notebook_id, filter_str],
            notebook_id=notebook_id,
        )
        return {"data": data}

    # ──── Document Generation ────────────────────────────────────

    def generate_document(
        self,
        notebook_id: str,
        source_ids: Optional[List[str]] = None,
        doc_type: DocType = DocType.BRIEF,
    ) -> Dict[str, Any]:
        """Generate a document from notebook sources.

        Args:
            notebook_id: Notebook UUID
            source_ids: Source UUIDs to include. If None, uses all sources.
            doc_type: Document type (BRIEF or DEEP_RESEARCH)

        Returns:
            Dict with title, description, source_ids

        Example:
            doc = sdk.generate_document("nb-id", doc_type=DocType.DEEP_RESEARCH)
        """
        self._stats.docs_generated += 1

        if source_ids is None:
            sources = self.list_sources(notebook_id)
            source_ids = [s.id for s in sources]

        try:
            from engine.mcp.nlm_archive import generate_document
            return generate_document(
                notebook_id, source_ids, self._session.cookies,
                doc_type=int(doc_type),
            )
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def generate_guide(
        self,
        notebook_id: str,
        style: GuideType = GuideType.STUDY_GUIDE,
    ) -> Dict[str, Any]:
        """Generate a study guide, FAQ, briefing, or timeline.

        Args:
            notebook_id: Notebook UUID
            style: Guide type (study_guide, faq, briefing_doc, toc, timeline)

        Returns:
            Dict with generated guide content

        Example:
            faq = sdk.generate_guide("nb-id", style=GuideType.FAQ)
        """
        self._stats.docs_generated += 1
        _, data = self._call_rpc(
            "generate_guide",
            [notebook_id, TIER_PRO],
            notebook_id=notebook_id,
        )
        return {"data": data, "style": style.value}

    def generate_mind_map(self, notebook_id: str) -> Dict[str, Any]:
        """Generate a D3-format mind map from notebook sources.

        Args:
            notebook_id: Notebook UUID

        Returns:
            Dict with D3-compatible JSON mind map data

        Example:
            mindmap = sdk.generate_mind_map("nb-id")
        """
        _, data = self._call_rpc(
            "sync_notes",
            [notebook_id, None, None, TIER_PRO],
            notebook_id=notebook_id,
        )
        return {"data": data}

    # ──── Research Operations ────────────────────────────────────

    def start_deep_research(
        self,
        notebook_id: str,
        topic: str,
    ) -> Dict[str, Any]:
        """Start an async deep research session.

        Args:
            notebook_id: Notebook UUID
            topic: Research topic/question

        Returns:
            Dict with session_id for tracking

        Example:
            result = sdk.start_deep_research("nb-id", "Impact of AI on healthcare")
            session_id = result["session_id"]
        """
        try:
            from engine.mcp.nlm_operations import start_deep_research
            return start_deep_research(notebook_id, topic, self._session.cookies)
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    def add_research_source(
        self,
        notebook_id: str,
        session_id: str,
        title: str,
        content: str,
    ) -> Dict[str, Any]:
        """Add an AI-generated research document as a source.

        Args:
            notebook_id: Notebook UUID
            session_id: Research session UUID (from start_deep_research)
            title: Document title
            content: Document content

        Returns:
            Dict with source_id

        Example:
            sdk.add_research_source("nb-id", session_id, "Analysis", "...")
        """
        self._stats.sources_added += 1
        try:
            from engine.mcp.nlm_operations import add_research_source
            return add_research_source(
                notebook_id, session_id, title, content, self._session.cookies,
            )
        except Exception as e:
            self._stats.errors += 1
            return {"error": str(e)}

    # ──── Audio Operations ───────────────────────────────────────

    def get_audio_options(self, notebook_id: str) -> Dict[str, Any]:
        """List available audio overview styles.

        Args:
            notebook_id: Notebook UUID

        Returns:
            Dict with options list: [{id, label, description}, ...]

        Example:
            options = sdk.get_audio_options("nb-id")
            # Returns: Deep Dive, Brief, Critique, Debate
        """
        try:
            from engine.mcp.nlm_operations import get_audio_options
            return get_audio_options(notebook_id, self._session.cookies)
        except Exception as e:
            return {"error": str(e)}

    # ──── User & Account ─────────────────────────────────────────

    def get_user_profile(self, notebook_id: str = "") -> Dict[str, Any]:
        """Get user profile: email, name, queries remaining.

        Args:
            notebook_id: Optional notebook context

        Returns:
            Dict with user profile data
        """
        _, data = self._call_rpc("user_profile", [notebook_id, TIER_PRO])
        return {"data": data}

    def get_user_quota(self) -> Dict[str, Any]:
        """Get account storage quota and plan info.

        Returns:
            Dict with quota data
        """
        try:
            from engine.mcp.nlm_archive import get_user_quota
            return get_user_quota(self._session.cookies)
        except Exception as e:
            return {"error": str(e)}

    def get_user_plan(self) -> Dict[str, Any]:
        """Get plan tier, daily query limit, and queries remaining.

        Returns:
            Dict with plan_name, daily_limit, queries_remaining
        """
        try:
            from engine.mcp.nlm_archive import get_user_plan
            return get_user_plan(self._session.cookies)
        except Exception as e:
            return {"error": str(e)}

    # ──── Export & Archive ────────────────────────────────────────

    def export_notebook(
        self,
        notebook_id: str,
        include_source_content: bool = True,
        include_threads: bool = True,
    ) -> Dict[str, Any]:
        """Export a complete notebook snapshot.

        Includes: summary, sources, source content, notes, threads, mind map.
        Makes 7+ RPC calls (rate-limited).

        Args:
            notebook_id: Notebook UUID
            include_source_content: Download full text of all sources
            include_threads: Include conversation threads

        Returns:
            Dict with complete notebook archive

        Example:
            archive = sdk.export_notebook("nb-id")
            print(f"Sources: {len(archive['sources'])}")
        """
        try:
            from engine.mcp.nlm_archive import export_notebook
            return export_notebook(
                notebook_id, self._session.cookies,
                include_source_content=include_source_content,
                include_threads=include_threads,
            )
        except Exception as e:
            return {"error": str(e)}

    def download_all_sources(
        self,
        notebook_id: str,
    ) -> List[Dict[str, Any]]:
        """Download full text content of all sources.

        Rate-limited (1.5s per source).

        Args:
            notebook_id: Notebook UUID

        Returns:
            List of dicts with source_id, title, content, word_count

        Example:
            sources = sdk.download_all_sources("nb-id")
            total_words = sum(s["word_count"] for s in sources)
        """
        try:
            from engine.mcp.nlm_archive import download_all_sources
            return download_all_sources(notebook_id, self._session.cookies)
        except Exception as e:
            return [{"error": str(e)}]

    # ──── Sync Operations ────────────────────────────────────────

    def sync_notes(
        self,
        notebook_id: str,
        prev_timestamp: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Delta poll for note changes since a timestamp.

        Args:
            notebook_id: Notebook UUID
            prev_timestamp: [seconds, nanoseconds] from previous sync.
                           None for first sync (returns all notes).

        Returns:
            Dict with notes list and next_timestamp for subsequent calls

        Example:
            # First sync
            r1 = sdk.sync_notes("nb-id")
            # Subsequent syncs (only changes)
            r2 = sdk.sync_notes("nb-id", prev_timestamp=r1["next_timestamp"])
        """
        try:
            from engine.mcp.nlm_operations import sync_notes
            return sync_notes(
                notebook_id, self._session.cookies,
                prev_timestamp=prev_timestamp,
            )
        except Exception as e:
            return {"error": str(e)}

    # ──── Thread & History Operations ────────────────────────────

    def get_chat_history(self, notebook_id: str) -> Dict[str, Any]:
        """Get full chat history for a notebook.

        Args:
            notebook_id: Notebook UUID

        Returns:
            Dict with conversation history
        """
        _, data = self._call_rpc(
            "get_chat_history",
            [[], None, notebook_id, 50],
            notebook_id=notebook_id,
        )
        return {"data": data}

    def delete_chat_history(self, notebook_id: str) -> Dict[str, Any]:
        """Delete entire chat history for a notebook.

        Args:
            notebook_id: Notebook UUID

        Returns:
            Dict with deletion status

        WARNING: This is irreversible.
        """
        _, data = self._call_rpc(
            "delete_chat_history",
            [notebook_id],
            notebook_id=notebook_id,
        )
        return {"deleted": data is not None}


# ──── Module-Level Convenience ───────────────────────────────────────

_sdk_instance: Optional[NotebookLMSDK] = None


def get_notebooklm_sdk(
    cookies: Optional[Dict[str, str]] = None,
) -> NotebookLMSDK:
    """Get or create the singleton NotebookLMSDK instance.

    Args:
        cookies: Optional cookies override. If None, auto-loads from disk.

    Returns:
        NotebookLMSDK singleton instance

    Example:
        from engine.integrations.notebooklm_sdk import get_notebooklm_sdk
        sdk = get_notebooklm_sdk()
        answer = sdk.ask("nb-id", "What is this about?")
    """
    global _sdk_instance
    if _sdk_instance is None:
        _sdk_instance = NotebookLMSDK(cookies=cookies)
    return _sdk_instance


def reset_sdk() -> None:
    """Reset the singleton SDK instance (for testing)."""
    global _sdk_instance
    _sdk_instance = None
