"""Direct NotebookLM HTTP client — reverse-engineered from HAR/CDP analysis.

Runs direct private-RPC HTTP calls after browser-attached auth/session capture
has established fresh NotebookLM cookies and session metadata. Three endpoint
families:

1. GenerateFreeFormStreamed — multi-turn notebook chat (ask / ask_streaming)
2. batchexecute — all studio operations: create_note, generate_audio,
   add_source, generate_flashcards, generate_mind_map, export_to_sheets, etc.
3. gRPC-web — heap-discovered operations via the LabsTailwindOrchestrationService
   path: artifact CRUD, source mutations, prompt suggestions, chat sessions, etc.

Gemini 3.0 is fully multimodal. Every source can be: text, URL, YouTube link,
image (jpg/png/webp/gif), audio (mp3/wav/ogg/m4a), video (mp4/mov/webm), or PDF.
Feed ComfyUI output, NLM-generated audio, screenshots, charts — anything — back
as sources for the next call. Recursive self-improvement is the architecture.

Endpoints confirmed from notebooklm.google.com-complete-new.har (2026-06).
rpcid registry: config/nlm_rpcids.yaml v5.0 (302 operations)
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import mimetypes
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Generator, Iterator, List, Optional, Tuple

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool
from engine.integrations.nlm_rpc_registry import get_rpc_registry

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_NLM_BASE = "https://notebooklm.google.com"

# Chat endpoint — GenerateFreeFormStreamed (multi-turn Q&A against sources)
_NLM_CHAT_ENDPOINT = (
    f"{_NLM_BASE}/_/LabsTailwindUi/data/"
    "google.internal.labs.tailwind.orchestration.v1."
    "LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
)

# Studio endpoint — batchexecute (all rpcid operations: generate, create, export…)
_NLM_RPC_ENDPOINT = f"{_NLM_BASE}/_/LabsTailwindUi/data/batchexecute"

# Legacy alias kept for any code that referenced the old constant name
_NLM_ENDPOINT = _NLM_CHAT_ENDPOINT

# gRPC-web service path for heap-discovered operations (24 methods)
_GRPC_SERVICE_PATH = (
    "google.internal.labs.tailwind.orchestration.v1."
    "LabsTailwindOrchestrationService"
)
_NLM_GRPC_ENDPOINT = f"{_NLM_BASE}/_/LabsTailwindUi/data/{_GRPC_SERVICE_PATH}"

_NLM_ORIGIN = "https://notebooklm.google.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
_NLM_ARTIFACTS_PATH = Path(__file__).resolve().parents[2] / "data" / "nlm_artifacts.json"
_NLM_META_PATH = Path(__file__).resolve().parents[2] / "data" / "nlm_meta.json"
_NLM_BUILD_LABEL_PREFIX = "boq_labs-tailwind-frontend_"

# Chrome DevTools Protocol — used for live token refresh from running NLM tabs
_CDP_PORT = 9222
_CDP_TABS_URL = f"http://localhost:{_CDP_PORT}/json"

# Audio type constants (from sqTeoe GET_AUDIO_OPTIONS)
AUDIO_DEEP_DIVE = 1   # ~30 minutes, two-host conversation
AUDIO_BRIEF = 2       # ~5 minutes, concise overview
AUDIO_CRITIQUE = 3    # critical analysis of sources
AUDIO_DEBATE = 4      # two-host debate on the topic

# Guide type constants (from xqEXEf)
GUIDE_STUDY = 1       # Study guide with key concepts and explanations
GUIDE_FAQ = 2         # FAQ format — questions and answers
GUIDE_BRIEFING = 3    # Executive briefing / summary
GUIDE_TOC = 4         # Table of contents / outline
GUIDE_TIMELINE = 5    # Chronological timeline

# MIME types accepted by NLM for file upload (Gemini 3.0 multimodal)
_MIME_MAP: Dict[str, str] = {
    # Images
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    # Audio — feed generated NLM podcasts back as sources
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    # Video — feed ComfyUI output, screen recordings back as sources
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    # Documents
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".html": "text/html",
}


# ──── Client ─────────────────────────────────────────────────────────────────

class NLMDirectClient:
    """Direct NotebookLM query client using browser session cookies.

    Args:
        account: Authenticated GoogleAccount from the pool.
    """

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._bl: Optional[str] = None
        self._f_sid: Optional[str] = None
        raw_at_token = getattr(account, "at_token", None)
        self._at_token: Optional[str] = raw_at_token if isinstance(raw_at_token, str) and raw_at_token else None
        self._session_params_loaded = False
        self._reqid = 1000000
        try:
            self._registry = get_rpc_registry()
        except Exception:
            self._registry = None
        self._prime_saved_session_params()

    # ──── Registry helpers ────────────────────────────────────────────────────

    def _rpcid(self, operation: str, tier: str = "primary") -> Optional[str]:
        """Look up an rpcid from the registry, returning None if unavailable."""
        if not self._registry:
            return None
        try:
            return self._registry.get_rpcid(operation, tier)
        except (KeyError, ValueError):
            logger.debug("rpcid lookup failed for %s/%s", operation, tier)
            return None

    def _rpcid_pair(self, operation: str) -> tuple:
        """Return (primary_rpcid, fallback_rpcid) from registry, with None for missing."""
        primary = self._rpcid(operation, "primary")
        fallback = self._rpcid(operation, "fallback")
        return primary, fallback

    # ──── Page params ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_valid_nlm_build_label(build_label: Optional[str]) -> bool:
        """Return True when a build label matches NotebookLM's frontend naming."""
        return bool(build_label and build_label.startswith(_NLM_BUILD_LABEL_PREFIX))

    def _load_saved_session_params(self) -> Dict[str, str]:
        """Load any persisted NotebookLM session data from the account and disk."""
        session: Dict[str, str] = {}

        account_service_sessions = getattr(self._account, "service_sessions", None)
        if isinstance(account_service_sessions, dict):
            notebooklm_session = account_service_sessions.get("notebooklm")
            if isinstance(notebooklm_session, dict):
                for key in ("bl", "f_sid", "at", "source_path", "notebook_id"):
                    value = notebooklm_session.get(key)
                    if isinstance(value, str) and value:
                        session[key] = value

        account_session = getattr(self._account, "nlm_session", None)
        if isinstance(account_session, dict):
            for key in ("bl", "f_sid", "at", "source_path", "notebook_id"):
                value = account_session.get(key)
                if isinstance(value, str) and value and key not in session:
                    session[key] = value

        if _NLM_META_PATH.exists():
            try:
                meta = json.loads(_NLM_META_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.debug("Could not read NotebookLM metadata from %s", _NLM_META_PATH, exc_info=True)
            else:
                for key in ("bl", "f_sid", "at"):
                    value = meta.get(key)
                    if isinstance(value, str) and value and key not in session:
                        session[key] = value

        if "bl" in session and not self._is_valid_nlm_build_label(session["bl"]):
            session.pop("bl", None)

        return session

    def _persist_session_params(
        self,
        bl: Optional[str],
        f_sid: Optional[str],
        at_token: Optional[str],
    ) -> None:
        """Persist NotebookLM session params back to the account and metadata file."""
        current_session = getattr(self._account, "nlm_session", None)
        account_session = dict(current_session) if isinstance(current_session, dict) else {}

        if bl and self._is_valid_nlm_build_label(bl):
            account_session["bl"] = bl
        if f_sid:
            account_session["f_sid"] = f_sid
        if at_token:
            account_session["at"] = at_token

        if account_session:
            try:
                setattr(self._account, "nlm_session", account_session)
            except AttributeError:
                logger.debug("Could not persist NotebookLM session to account object", exc_info=True)

        current_service_sessions = getattr(self._account, "service_sessions", None)
        service_sessions = dict(current_service_sessions) if isinstance(current_service_sessions, dict) else {}
        notebooklm_session = dict(service_sessions.get("notebooklm", {}))
        notebooklm_session.update(account_session)
        if notebooklm_session:
            service_sessions["notebooklm"] = notebooklm_session
            try:
                setattr(self._account, "service_sessions", service_sessions)
            except AttributeError:
                logger.debug("Could not persist NotebookLM service session to account object", exc_info=True)

        existing_meta: Dict[str, Any] = {}
        if _NLM_META_PATH.exists():
            try:
                existing_meta = json.loads(_NLM_META_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.debug("Could not read existing NotebookLM metadata", exc_info=True)

        updated_meta = dict(existing_meta)
        if bl and self._is_valid_nlm_build_label(bl):
            updated_meta["bl"] = bl
            updated_meta["bl_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if f_sid:
            updated_meta["f_sid"] = f_sid
        if at_token:
            updated_meta["at"] = at_token

        if updated_meta:
            _NLM_META_PATH.parent.mkdir(parents=True, exist_ok=True)
            _NLM_META_PATH.write_text(json.dumps(updated_meta, indent=2), encoding="utf-8")

    def _prime_saved_session_params(self) -> None:
        """Seed the client with any persisted NotebookLM session state."""
        saved = self._load_saved_session_params()
        if saved.get("bl") and saved.get("f_sid"):
            self._set_session_params(
                saved.get("bl"),
                saved.get("f_sid"),
                saved.get("at"),
                persist=False,
            )
            return
        if saved.get("at") and not self._at_token:
            self._at_token = saved["at"]

    def _get_offline_build_label(self) -> Optional[str]:
        """Return the latest ARGUS-mined NLM build label if available."""
        try:
            data = json.loads(_NLM_ARTIFACTS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            logger.debug("Offline build label unavailable: %s", exc)
            return None

        build_label = data.get("build_info", {}).get("build_label")
        if isinstance(build_label, str) and self._is_valid_nlm_build_label(build_label):
            return build_label
        return None

    def _extract_page_params(self, html: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract build label, f.sid, and at token from the live NLM page."""
        bl: Optional[str] = None
        f_sid: Optional[str] = None
        at_token: Optional[str] = None
        wiz_data: Dict[str, Any] = {}

        wiz_match = re.search(r"WIZ_global_data\s*=\s*({.*?});", html, re.DOTALL)
        if wiz_match:
            try:
                wiz_data = json.loads(wiz_match.group(1))
            except json.JSONDecodeError:
                logger.debug("Could not parse WIZ_global_data from NLM homepage")

        for key in ("IxjpMA", "FdrFJe"):
            value = wiz_data.get(key)
            if value not in (None, ""):
                f_sid = str(value)
                break

        if not f_sid:
            for pattern in (
                r'"IxjpMA"\s*:\s*"([^"]+)"',
                r'"FdrFJe"\s*:\s*"([^"]+)"',
                r"f\.sid=([^&\"']+)",
            ):
                match = re.search(pattern, html)
                if match:
                    f_sid = urllib.parse.unquote(match.group(1))
                    break

        wiz_at_token = wiz_data.get("SNlM0e")
        if isinstance(wiz_at_token, str) and wiz_at_token:
            at_token = wiz_at_token
        else:
            at_match = re.search(r'"SNlM0e"\s*:\s*"([^"]+)"', html)
            if at_match:
                at_token = at_match.group(1)

        for key in ("QrtxK", "cfb2h", "bl"):
            value = wiz_data.get(key)
            if isinstance(value, str) and self._is_valid_nlm_build_label(value):
                bl = value
                break

        if not bl:
            for pattern in (
                r'"bl"\s*:\s*"([^"]+)"',
                r'cfb_data["\s:]+\{["\s]*bl["\s:]+(["\'])([^"\']+)\1',
                r"(boq_[A-Za-z0-9._-]+)",
            ):
                match = re.search(pattern, html)
                if not match:
                    continue
                candidate = match.group(2) if match.lastindex and match.lastindex > 1 else match.group(1)
                if self._is_valid_nlm_build_label(candidate):
                    bl = candidate
                    break

        return bl, f_sid, at_token

    def _set_session_params(
        self,
        bl: Optional[str],
        f_sid: Optional[str],
        at_token: Optional[str],
        persist: bool = True,
    ) -> None:
        """Cache the current NLM session parameters."""
        resolved_bl = bl or self._bl
        resolved_f_sid = f_sid or self._f_sid
        resolved_at_token = at_token or self._at_token

        self._bl = resolved_bl
        self._f_sid = resolved_f_sid
        self._at_token = resolved_at_token
        if resolved_at_token and getattr(self._account, "at_token", None) != resolved_at_token:
            setattr(self._account, "at_token", resolved_at_token)
        self._session_params_loaded = bool(self._bl and self._f_sid)
        if persist:
            self._persist_session_params(self._bl, self._f_sid, self._at_token)

    def _clear_session_params(self) -> None:
        """Clear cached AND persisted NLM session parameters to force a live refresh."""
        self._bl = None
        self._f_sid = None
        self._at_token = None
        self._session_params_loaded = False
        # Wipe persisted params from the account object
        for attr in ("nlm_session", ):
            obj = getattr(self._account, attr, None)
            if isinstance(obj, dict):
                for key in ("bl", "f_sid", "at"):
                    obj.pop(key, None)
        svc = getattr(self._account, "service_sessions", None)
        if isinstance(svc, dict) and isinstance(svc.get("notebooklm"), dict):
            for key in ("bl", "f_sid", "at"):
                svc["notebooklm"].pop(key, None)
        # Wipe persisted params from the meta file
        if _NLM_META_PATH.exists():
            try:
                meta = json.loads(_NLM_META_PATH.read_text(encoding="utf-8"))
                for key in ("bl", "f_sid", "at"):
                    meta.pop(key, None)
                _NLM_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass

    # ──── CDP-based live token refresh ────────────────────────────────────────

    def _refresh_from_cdp(self) -> bool:
        """Extract fresh session tokens from a live NotebookLM Chrome tab via CDP.

        Chrome must be running with ``--remote-debugging-port=9222``. The
        ``websockets`` library connects to the tab's DevTools WebSocket and
        evaluates JavaScript to read ``WIZ_global_data`` directly from the
        authenticated page — bypassing the HTTP-fetch token path that goes
        stale when the page's session fingerprint drifts.

        Also refreshes cookies from the live browser session into the account
        pool so that subsequent HTTP calls carry fresh auth.

        Returns:
            True if fresh tokens were successfully extracted and set.
        """
        try:
            import websockets  # noqa: F811
        except ImportError:
            logger.debug("websockets not installed — CDP refresh unavailable")
            return False

        try:
            tabs_resp = requests.get(_CDP_TABS_URL, timeout=3)
            tabs = tabs_resp.json()
        except Exception:
            logger.debug("Chrome CDP not reachable at port %d", _CDP_PORT)
            return False

        nlm_tabs = [
            t for t in tabs
            if "notebooklm" in t.get("url", "").lower()
            and t.get("webSocketDebuggerUrl")
            and t.get("type") == "page"
        ]
        if not nlm_tabs:
            logger.debug("No NotebookLM tabs found in Chrome CDP")
            return False

        async def _extract() -> Optional[Dict[str, str]]:
            ws_url = nlm_tabs[0]["webSocketDebuggerUrl"]
            async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                msg_id = 0

                # 1. Extract WIZ_global_data tokens
                msg_id += 1
                expr = (
                    "JSON.stringify({"
                    "  bl: (() => {"
                    "    const wiz = window.WIZ_global_data || {};"
                    "    for (const v of Object.values(wiz)) {"
                    "      if (typeof v === 'string' && v.startsWith('boq_labs-tailwind-frontend_')) return v;"
                    "    }"
                    "    return '';"
                    "  })(),"
                    "  f_sid: (window.WIZ_global_data && (window.WIZ_global_data.IxjpMA || window.WIZ_global_data.FdrFJe)) || '',"
                    "  at: (window.WIZ_global_data && window.WIZ_global_data.SNlM0e) || ''"
                    "})"
                )
                await ws.send(json.dumps({
                    "id": msg_id,
                    "method": "Runtime.evaluate",
                    "params": {"expression": expr, "returnByValue": True},
                }))
                tokens: Dict[str, str] = {}
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("id") == msg_id:
                        val = (
                            msg.get("result", {})
                            .get("result", {})
                            .get("value", "")
                        )
                        if val:
                            tokens = json.loads(val)
                        break

                if not tokens.get("bl") or not tokens.get("f_sid"):
                    return None

                # 2. Extract fresh cookies from the browser
                msg_id += 1
                await ws.send(json.dumps({
                    "id": msg_id,
                    "method": "Network.getCookies",
                    "params": {"urls": [
                        "https://notebooklm.google.com",
                        "https://google.com",
                        "https://accounts.google.com",
                    ]},
                }))
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("id") == msg_id:
                        browser_cookies = {
                            c["name"]: c["value"]
                            for c in msg.get("result", {}).get("cookies", [])
                            if c.get("name") and c.get("value")
                        }
                        tokens["_cookies"] = browser_cookies
                        break

            return tokens

        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_extract())
            loop.close()
        except Exception as exc:
            logger.warning("CDP token extraction failed: %s", exc)
            return False

        if not result or not result.get("bl") or not result.get("f_sid"):
            return False

        # Apply the fresh tokens
        self._set_session_params(
            result["bl"], result["f_sid"], result.get("at"), persist=True
        )

        # Apply fresh cookies to the account pool
        browser_cookies = result.get("_cookies", {})
        if browser_cookies:
            pool = get_account_pool()
            existing = getattr(self._account, "cookies", {}) or {}
            existing.update(browser_cookies)
            self._account.cookies = existing
            pool.save()
            logger.info(
                "CDP refresh: applied %d cookies + fresh tokens (bl=%s… f_sid=%s)",
                len(browser_cookies),
                result["bl"][:40],
                result["f_sid"],
            )

        return True

    def _get_page_params(self) -> Tuple[str, str]:
        """Fetch build label (bl) and session fingerprint (f.sid) from NLM homepage.

        Returns:
            Tuple of (bl, f_sid) strings.

        Raises:
            ValueError: If parameters cannot be extracted.
        """
        if self._bl and self._f_sid:
            return self._bl, self._f_sid

        saved_session = self._load_saved_session_params()
        saved_bl = saved_session.get("bl")
        saved_f_sid = saved_session.get("f_sid")
        saved_at_token = saved_session.get("at")
        if saved_at_token and not self._at_token:
            self._at_token = saved_at_token
        if saved_bl and saved_f_sid:
            self._set_session_params(saved_bl, saved_f_sid, saved_at_token, persist=False)
            return self._bl or saved_bl, self._f_sid or saved_f_sid

        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": cookie_header,
            "User-Agent": _USER_AGENT,
        }

        resp = self._session.get(_NLM_BASE, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

        bl, f_sid, at_token = self._extract_page_params(html)

        if not bl:
            bl = saved_bl
        if not bl:
            bl = self._get_offline_build_label()
            if bl:
                logger.warning("Could not extract bl from NLM page, using ARGUS build label: %s", bl)

        if not f_sid:
            f_sid = saved_f_sid

        if not f_sid or not bl:
            # HTTP page fetch failed to get valid tokens — try CDP as live fallback
            if self._refresh_from_cdp():
                if self._bl and self._f_sid:
                    return self._bl, self._f_sid

        if not f_sid:
            raise ValueError("Could not extract f.sid from NLM page")

        if not bl:
            raise ValueError("Could not determine NotebookLM build label")

        self._set_session_params(bl, f_sid, at_token or saved_at_token)
        logger.debug(
            "NLM page params: bl=%s f.sid=%s at_present=%s",
            bl,
            f_sid,
            bool(self._at_token),
        )
        return bl, f_sid

    # ──── Auth headers ────────────────────────────────────────────────────────

    def _get_headers(self, source_path: str = "/") -> Dict[str, str]:
        """Build NLM request headers.

        Returns:
            Headers dict including Cookie, Origin, and x-same-domain.
        """
        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        referer = f"{_NLM_BASE}{source_path}" if source_path != "/" else f"{_NLM_BASE}/"
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Cookie": cookie_header,
            "Origin": _NLM_ORIGIN,
            "Referer": referer,
            "User-Agent": _USER_AGENT,
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

    # ──── Request building ────────────────────────────────────────────────────

    def _build_request_body(
        self,
        notebook_id: str,
        source_ids: List[str],
        question: str,
        conversation_history: Optional[List[Any]] = None,
        previous_answer: Optional[str] = None,
    ) -> str:
        """Build the URL-encoded f.req body for GenerateFreeFormStreamed.

        The inner JSON structure confirmed from HAR:
        [
            [[[source_id_1]], [[source_id_2]], ...],   # sources
            previous_answer_or_null,
            question_text,
            notebook_id,
            null,
            conversation_history_or_null,
            null,
            null,
            null
        ]
        Wrapped as: [null, json_string_of_inner]

        Args:
            notebook_id: NLM notebook UUID.
            source_ids: List of source UUIDs to query against.
            question: Question text.
            conversation_history: Optional prior conversation turns.
            previous_answer: Optional previous response text.

        Returns:
            URL-encoded form body string.
        """
        source_list = [[[sid]] for sid in source_ids]
        inner = [
            source_list,
            previous_answer,
            question,
            notebook_id,
            None,
            conversation_history,
            None,
            None,
            None,
        ]
        inner_json = json.dumps(inner, ensure_ascii=False, separators=(",", ":"))
        outer = [None, inner_json]
        outer_json = json.dumps(outer, ensure_ascii=False, separators=(",", ":"))
        return "f.req=" + urllib.parse.quote(outer_json)

    # ──── Response parsing ────────────────────────────────────────────────────

    def _parse_response(self, raw: str) -> str:
        """Extract the final answer text from the chunked NLM response.

        Response format: alternating lines of ``{size}\\n{json}\\n``
        where the first JSON chunk starts with the ``)]}'`` XSSI prefix.
        Each JSON chunk is: ``[["wrb.fr", null, "inner_json_string"]]``

        The inner JSON is a list where [0][0] is the response text.

        Args:
            raw: Raw response body string.

        Returns:
            Extracted text from the last completed wrb.fr chunk,
            or the raw content if parsing fails.
        """
        # Strip XSSI prefix from first chunk
        stripped = raw.replace(")]}'", "")

        # Split into chunks — each chunk is a JSON array line
        # Chunks are separated by decimal size prefixes
        # Split on lines and process each JSON-looking line
        chunks: List[str] = []
        lines = stripped.splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Skip lines that are purely numeric (chunk size markers)
            if line.isdigit():
                continue
            if line.startswith("["):
                chunks.append(line)

        # Collect all wrb.fr text payloads; return the last complete one
        last_text: Optional[str] = None

        for chunk in chunks:
            try:
                parsed = json.loads(chunk)
                for item in parsed:
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                        inner_str = item[2]
                        if not inner_str:
                            continue
                        inner = json.loads(inner_str)
                        # inner[0][0] is the response text
                        if inner and inner[0] and isinstance(inner[0][0], str):
                            last_text = inner[0][0]
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        if last_text is not None:
            return last_text

        # Fallback: return cleaned raw
        logger.warning("Could not parse NLM response structure, returning raw")
        return stripped[:5000]

    # ──── Public API ──────────────────────────────────────────────────────────

    def ask(
        self,
        notebook_id: str,
        source_ids: List[str],
        question: str,
        conversation_history: Optional[List[Any]] = None,
    ) -> str:
        """Ask a question against a NotebookLM notebook.

        Args:
            notebook_id: NLM notebook UUID.
            source_ids: List of source UUIDs in the notebook.
            question: The question to ask.
            conversation_history: Optional prior conversation for multi-turn.

        Returns:
            Answer text from NotebookLM.
        """
        bl, f_sid = self._get_page_params()
        self._reqid += 100000
        reqid = self._reqid

        url = (
            f"{_NLM_ENDPOINT}"
            f"?bl={urllib.parse.quote(bl)}&f.sid={f_sid}"
            f"&hl=en-US&_reqid={reqid}&rt=c"
        )

        body = self._build_request_body(
            notebook_id=notebook_id,
            source_ids=source_ids,
            question=question,
            conversation_history=conversation_history,
        )

        headers = self._get_headers(source_path=f"/notebook/{notebook_id}")
        resp = self._session.post(url, headers=headers, data=body, timeout=120)
        resp.raise_for_status()

        return self._parse_response(resp.text)

    def ask_streaming(
        self,
        notebook_id: str,
        source_ids: List[str],
        question: str,
    ) -> Generator[str, None, None]:
        """Ask a question and yield text as it streams in.

        Args:
            notebook_id: NLM notebook UUID.
            source_ids: List of source UUIDs.
            question: The question to ask.

        Yields:
            Incremental text chunks as they arrive.
        """
        bl, f_sid = self._get_page_params()
        self._reqid += 100000

        url = (
            f"{_NLM_ENDPOINT}"
            f"?bl={urllib.parse.quote(bl)}&f.sid={f_sid}"
            f"&hl=en-US&_reqid={self._reqid}&rt=c"
        )

        body = self._build_request_body(
            notebook_id=notebook_id,
            source_ids=source_ids,
            question=question,
        )

        headers = self._get_headers(source_path=f"/notebook/{notebook_id}")
        with self._session.post(
            url, headers=headers, data=body, stream=True, timeout=120
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                buffer += chunk
                # Try to extract complete wrb.fr items from buffer
                for text in self._extract_streaming_texts(buffer):
                    yield text

    def _extract_streaming_texts(self, buffer: str) -> List[str]:
        """Extract any complete wrb.fr text items from a streaming buffer."""
        texts = []
        clean = buffer.replace(")]}'", "")
        for line in clean.splitlines():
            line = line.strip()
            if not line or line.isdigit():
                continue
            if not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
                for item in parsed:
                    if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                        inner_str = item[2]
                        if inner_str:
                            inner = json.loads(inner_str)
                            if inner and inner[0] and isinstance(inner[0][0], str):
                                texts.append(inner[0][0])
            except (json.JSONDecodeError, IndexError, TypeError):
                pass
        return texts

    # ──── Generic batchexecute RPC caller ─────────────────────────────────────

    def _rpc_call(
        self,
        rpc_id: str,
        payload: Any,
        timeout: int = 120,
        source_path: str = "/",
        _retried: bool = False,
    ) -> Any:
        """Call any NLM studio operation via the batchexecute endpoint.

        This is the backbone for all non-chat operations: create_note,
        generate_audio, add_source, export_to_sheets, etc.

        Args:
            rpc_id: NLM rpcid string (e.g. ``'CYK0Xb'``, ``'QA9ei'``).
            payload: Python object — will be JSON-serialised as the inner payload.
            timeout: HTTP request timeout in seconds.
            source_path: URL source-path parameter (default ``'/'``; use
                ``'/notebook/{id}'`` for notebook-scoped calls).

        Returns:
            Parsed inner response data (list/dict), or ``None`` if unparseable.
        """
        bl, f_sid = self._get_page_params()
        self._reqid += 100000

        url = (
            f"{_NLM_RPC_ENDPOINT}"
            f"?rpcids={rpc_id}"
            f"&source-path={urllib.parse.quote(source_path)}"
            f"&f.sid={urllib.parse.quote(str(f_sid))}"
            f"&bl={urllib.parse.quote(bl)}"
            f"&hl=en-US"
            f"&_reqid={self._reqid}"
            f"&rt=c"
        )

        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        f_req_calls = [[[rpc_id, payload_json, None, "generic"]]]
        body_dict: Dict[str, str] = {
            "f.req": json.dumps(f_req_calls, ensure_ascii=False, separators=(",", ":"))
        }
        if self._at_token:
            body_dict["at"] = self._at_token
        body = urllib.parse.urlencode(body_dict)

        headers = self._get_headers(source_path=source_path)
        resp = self._session.post(url, headers=headers, data=body, timeout=timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            if not _retried and resp.status_code in (400, 401, 403):
                logger.warning(
                    "NLM batchexecute %s returned HTTP %s; attempting CDP token refresh",
                    rpc_id,
                    resp.status_code,
                )
                self._clear_session_params()
                if not self._refresh_from_cdp():
                    logger.warning("CDP refresh unavailable — falling back to HTTP page params")
                return self._rpc_call(
                    rpc_id,
                    payload,
                    timeout=timeout,
                    source_path=source_path,
                    _retried=True,
                )
            raise

        result = self._parse_rpc_response(resp.text, rpc_id)
        if result is None and not _retried:
            logger.warning("NLM batchexecute %s returned null; attempting CDP token refresh", rpc_id)
            self._clear_session_params()
            self._refresh_from_cdp()
            return self._rpc_call(
                rpc_id,
                payload,
                timeout=timeout,
                source_path=source_path,
                _retried=True,
            )
        return result

    def _parse_rpc_response(self, raw: str, rpc_id: str) -> Any:
        """Extract the inner payload from a batchexecute response.

        Response format mirrors GenerateFreeFormStreamed: chunked wrb.fr JSON.
        We match on the rpcid to find the right item when multiple are present.

        Args:
            raw: Raw response body string.
            rpc_id: rpcid we sent, used to match the right response item.

        Returns:
            Parsed inner response (list/dict/str), or ``None``.
        """
        stripped = raw.replace(")]}'", "")
        for line in stripped.splitlines():
            line = line.strip()
            if not line or line.isdigit() or not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
                for item in parsed:
                    if (
                        isinstance(item, list)
                        and len(item) >= 3
                        and item[0] == "wrb.fr"
                    ):
                        # item[1] is the rpcid, item[2] is the inner JSON string
                        if item[1] == rpc_id and item[2]:
                            return json.loads(item[2])
            except (json.JSONDecodeError, IndexError, TypeError):
                continue
        logger.debug("Could not parse rpc response for %s, raw length=%d", rpc_id, len(raw))
        return None

    # ──── Generic gRPC-web caller (heap-discovered methods) ───────────────────

    def _grpc_call(
        self,
        method_name: str,
        payload: Any,
        notebook_id: Optional[str] = None,
        timeout: int = 60,
        _retried: bool = False,
    ) -> Any:
        """Call a heap-discovered NLM operation via the gRPC-web endpoint.

        Uses the same auth (cookies + at token), session params (bl, f.sid),
        and ``f.req`` body format as batchexecute, but the URL encodes the
        full gRPC service path + method name instead of an rpcid.

        These methods were discovered via Chrome DevTools heap snapshots and
        have NOT been confirmed in HAR traffic.  Expect graceful failures
        (404, 400, 500) — all are logged and return ``None``.

        Args:
            method_name: gRPC method name (e.g. ``'CreateArtifact'``).
            payload: Python object — will be JSON-serialised as the inner payload.
            notebook_id: Optional notebook UUID for scoped operations.
            timeout: HTTP request timeout in seconds.

        Returns:
            Parsed response data (list/dict/str), or ``None`` on any failure.
        """
        bl, f_sid = self._get_page_params()
        self._reqid += 100000

        url = (
            f"{_NLM_GRPC_ENDPOINT}/{method_name}"
            f"?bl={urllib.parse.quote(bl)}"
            f"&f.sid={urllib.parse.quote(str(f_sid))}"
            f"&hl=en-US"
            f"&_reqid={self._reqid}"
            f"&rt=c"
        )
        if notebook_id:
            url += f"&source-path={urllib.parse.quote(f'/notebook/{notebook_id}')}"

        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        outer = [None, payload_json]
        outer_json = json.dumps(outer, ensure_ascii=False, separators=(",", ":"))

        body_dict: Dict[str, str] = {"f.req": outer_json}
        if self._at_token:
            body_dict["at"] = self._at_token
        body = urllib.parse.urlencode(body_dict)

        source_path = f"/notebook/{notebook_id}" if notebook_id else "/"
        headers = self._get_headers(source_path=source_path)

        try:
            resp = self._session.post(url, headers=headers, data=body, timeout=timeout)
        except requests.RequestException as exc:
            logger.warning("gRPC-web %s network error: %s", method_name, exc)
            return None

        if resp.status_code in (404, 501):
            logger.info(
                "gRPC-web %s returned %d — method may not be live yet",
                method_name,
                resp.status_code,
            )
            return None

        if resp.status_code in (400, 401, 403) and not _retried:
            logger.warning(
                "gRPC-web %s returned HTTP %d; attempting CDP token refresh",
                method_name,
                resp.status_code,
            )
            self._clear_session_params()
            if not self._refresh_from_cdp():
                logger.warning("CDP refresh unavailable for gRPC retry")
            return self._grpc_call(
                method_name,
                payload,
                notebook_id=notebook_id,
                timeout=timeout,
                _retried=True,
            )

        if resp.status_code >= 400:
            logger.warning(
                "gRPC-web %s returned HTTP %d (body=%s)",
                method_name,
                resp.status_code,
                resp.text[:500],
            )
            return None

        return self._parse_grpc_response(resp.text, method_name)

    def _parse_grpc_response(self, raw: str, method_name: str) -> Any:
        """Parse a gRPC-web response using multiple strategies.

        Strategy order:
        1. wrb.fr format (same as batchexecute) — NLM may wrap gRPC in this
        2. Raw JSON array/object — direct gRPC-JSON transcoding
        3. Raw text — if nothing else works, return trimmed text

        Args:
            raw: Raw response body string.
            method_name: Method name for logging context.

        Returns:
            Parsed response data, or ``None`` if empty/unparseable.
        """
        if not raw or not raw.strip():
            logger.debug("gRPC-web %s returned empty response", method_name)
            return None

        stripped = raw.replace(")]}'", "").strip()

        # Strategy 1: wrb.fr chunked format (most likely)
        for line in stripped.splitlines():
            line = line.strip()
            if not line or line.isdigit() or not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
                for item in parsed:
                    if (
                        isinstance(item, list)
                        and len(item) >= 3
                        and item[0] == "wrb.fr"
                        and item[2]
                    ):
                        inner = json.loads(item[2])
                        logger.debug(
                            "gRPC-web %s parsed via wrb.fr (inner type=%s)",
                            method_name,
                            type(inner).__name__,
                        )
                        return inner
            except (json.JSONDecodeError, IndexError, TypeError):
                continue

        # Strategy 2: direct JSON (gRPC-JSON transcoding)
        try:
            result = json.loads(stripped)
            logger.debug(
                "gRPC-web %s parsed as direct JSON (type=%s)",
                method_name,
                type(result).__name__,
            )
            return result
        except json.JSONDecodeError:
            pass

        # Strategy 3: return raw text if non-empty
        if len(stripped) > 0:
            logger.debug(
                "gRPC-web %s returned unparseable text (len=%d), returning raw",
                method_name,
                len(stripped),
            )
            return stripped[:10000]

        return None

    # ──── Source management ────────────────────────────────────────────────────

    def add_source_url(self, notebook_id: str, url: str) -> str:
        """Add any URL as a notebook source — web page, YouTube video, image, Sheet.

        Gemini 3.0 handles YouTube natively (no Whisper needed).
        Pass a Google Sheets URL to let Gemini read live spreadsheet data.
        Pass a direct image/video URL for multimodal ingestion.

        Args:
            notebook_id: NLM notebook UUID.
            url: URL to add. YouTube, web page, Google Sheets, image, etc.

        Returns:
            Source ID string.
        """
        payload = [notebook_id, None, [url]]
        rpcid = self._rpcid("add_source") or "izAoDd"
        result = self._rpc_call(rpcid, payload)
        if result and isinstance(result, list) and result[0]:
            return result[0] if isinstance(result[0], str) else str(result[0][0])
        raise RuntimeError(f"add_source_url failed for {url}: {result}")

    def add_source_text(self, notebook_id: str, title: str, content: str) -> str:
        """Paste text content directly as a notebook source.

        Use this to feed: transcripts, code files, JSON data, markdown docs,
        Colab execution results, Nexus entries — anything text-based.

        Args:
            notebook_id: NLM notebook UUID.
            title: Display name for the source.
            content: Full text content to add.

        Returns:
            Source ID string.
        """
        payload = [[title, content], None, None, 3]
        rpcid = self._rpcid("add_source") or "izAoDd"
        result = self._rpc_call(rpcid, payload)
        if result and isinstance(result, list) and result[0]:
            return result[0] if isinstance(result[0], str) else str(result[0][0])
        raise RuntimeError(f"add_source_text failed for '{title}': {result}")

    def add_source_file(
        self,
        notebook_id: str,
        file_path: str,
        mime_type: Optional[str] = None,
    ) -> str:
        """Upload a local file as a notebook source (multimodal).

        Gemini 3.0 natively understands:
        - Images: jpg, png, gif, webp — screenshots, ComfyUI output, charts
        - Audio: mp3, wav, ogg, m4a — feed NLM-generated podcasts back as sources
        - Video: mp4, mov, webm — ComfyUI video, screen recordings, demos
        - PDF, TXT, MD, HTML

        The self-referential audio loop:
            QA9ei → generate 30-min podcast → download mp3
            add_source_file(mp3) → Gemini listens to its own podcast
            QA9ei again → generates a FOLLOW-UP podcast building on the first
            → recursive knowledge amplification

        Args:
            notebook_id: NLM notebook UUID.
            file_path: Absolute path to the local file.
            mime_type: MIME type override. Auto-detected from extension if omitted.

        Returns:
            Source ID string.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not mime_type:
            mime_type = _MIME_MAP.get(path.suffix.lower())
            if not mime_type:
                # Fall back to mimetypes stdlib
                mime_type, _ = mimetypes.guess_type(str(path))
            if not mime_type:
                mime_type = "application/octet-stream"
                logger.warning("Unknown MIME type for %s, using octet-stream", path.name)

        logger.debug("Uploading %s (%s) to notebook %s", path.name, mime_type, notebook_id)

        # Step 1: Register the upload — o4cbdc returns upload URL + source ID
        rpcid = self._rpcid("upload_file") or "o4cbdc"
        payload = [[[path.name]], notebook_id, [2], [1, None, None, [1]]]
        result = self._rpc_call(rpcid, payload, timeout=30)
        if not result or not result[0]:
            raise RuntimeError(f"File upload registration failed for {path.name}: {result}")

        # result shape: [[[source_id], filename, [upload_url, ...]]]
        source_id: str = result[0][0][0]
        upload_url: str = result[0][2][0]

        # Step 2: PUT the file to the signed upload URL
        file_data = path.read_bytes()
        upload_resp = self._session.put(
            upload_url,
            data=file_data,
            headers={
                "Content-Type": mime_type,
                "Content-Length": str(len(file_data)),
            },
            timeout=300,
        )
        upload_resp.raise_for_status()
        logger.debug("Uploaded %s (%d bytes) → source %s", path.name, len(file_data), source_id)

        # Step 3: Poll until NLM has finished processing the file
        self._poll_source_ready(notebook_id, source_id)
        return source_id

    def delete_source(self, notebook_id: str, source_id: str) -> None:
        """Remove a source from a notebook.

        Use this to clean up temporary sources added for one-shot analysis
        (e.g. cross-notebook cross-reference pass).

        Args:
            notebook_id: NLM notebook UUID.
            source_id: Source ID to delete.
        """
        payload = [[[source_id]], [1]]
        rpcid = self._rpcid("delete_source") or "LBwxtb"
        self._rpc_call(rpcid, payload)
        logger.debug("Deleted source %s from notebook %s", source_id, notebook_id)

    def get_sources(self, notebook_id: str) -> List[str]:
        """Return all source IDs for a notebook.

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of source ID strings.
        """
        payload = [[], None, notebook_id, 20]
        rpcid = self._rpcid("list_sources") or "hPTbtc"
        result = self._rpc_call(rpcid, payload)
        source_ids: List[str] = []
        if result:
            for item in result:
                if isinstance(item, list):
                    for inner in item:
                        if isinstance(inner, list) and inner:
                            source_ids.append(str(inner[0]))
        return source_ids

    def _poll_source_ready(
        self,
        notebook_id: str,
        source_id: str,
        max_wait: int = 120,
        poll_interval: int = 3,
    ) -> None:
        """Poll rLM1Ne until a source finishes processing.

        Args:
            notebook_id: NLM notebook UUID.
            source_id: Source ID to wait for.
            max_wait: Maximum seconds to wait.
            poll_interval: Seconds between polls.

        Raises:
            TimeoutError: If source is not ready within max_wait seconds.
        """
        deadline = time.time() + max_wait
        while time.time() < deadline:
            payload = [notebook_id, None, 0]
            rpcid = self._rpcid("poll_source") or "rLM1Ne"
            result = self._rpc_call(rpcid, payload, timeout=30)
            # result=None means all sources are ready (no pending)
            if result is None:
                return
            # Check if our specific source_id is still pending
            pending_ids: List[str] = []
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, list) and item:
                        pending_ids.append(str(item[0]))
            if source_id not in pending_ids:
                return
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Source {source_id} not ready after {max_wait}s in notebook {notebook_id}"
        )

    # ──── Studio generation ────────────────────────────────────────────────────

    def create_note(self, notebook_id: str, prompt: str) -> Dict[str, Any]:
        """Generate a custom report/document via Gemini (CYK0Xb).

        The prompt is your creative brief — up to ~10,000 words.
        Gemini reads the ENTIRE prompt plus every source in the notebook.

        Args:
            notebook_id: NLM notebook UUID.
            prompt: Full prompt / creative brief (up to ~10k words).

        Returns:
            Dict with ``id``, ``title``, ``content`` (markdown).
        """
        rpcid = self._rpcid("create_note") or "CYK0Xb"
        payload = [notebook_id, prompt]
        result = self._rpc_call(rpcid, payload, timeout=180)
        if not result:
            raise RuntimeError(f"create_note returned empty response for notebook {notebook_id}")
        # result shape: [artifact_id, title, markdown_content]
        return {
            "id": result[0] if len(result) > 0 else None,
            "title": result[1] if len(result) > 1 else "Untitled",
            "content": result[2] if len(result) > 2 else "",
        }

    def generate_audio(
        self,
        notebook_id: str,
        focus_text: str,
        audio_type: int = AUDIO_DEEP_DIVE,
    ) -> Tuple[str, str]:
        """Generate a custom audio overview — 30-minute Gemini podcast (QA9ei).

        The focus_text is your producer's brief — up to ~10,000 words.
        Direct every segment, name the hosts' argumentative roles, specify
        which sources to emphasise, request specific examples, control tone.

        The generated audio is ~30 minutes of dense expert conversation.
        Transcribed with Whisper → 12,000–15,000 words per run.

        Self-referential loop (most powerful use):
            1. generate_audio(nb, "explain architecture deeply") → mp3
            2. add_source_file(mp3) → Gemini now listens to its own explanation
            3. generate_audio(nb, "now cover all the gotchas the first podcast missed") → mp3
            Each pass adds depth the previous pass lacked.

        Args:
            notebook_id: NLM notebook UUID.
            focus_text: Producer brief directing the full podcast content.
            audio_type: AUDIO_DEEP_DIVE (1), AUDIO_BRIEF (2),
                        AUDIO_CRITIQUE (3), AUDIO_DEBATE (4).

        Returns:
            Tuple of ``(job_id, artifact_id)``. Poll artifact_id with
            ``poll_artifact()`` until status is COMPLETE, then ``download_audio()``.
        """
        payload = [None, [audio_type], [focus_text, 1], 5, notebook_id]
        rpcid = self._rpcid("generate_audio") or "QA9ei"
        result = self._rpc_call(rpcid, payload, timeout=60)
        if not result or len(result) < 2:
            raise RuntimeError(f"generate_audio returned unexpected result: {result}")
        logger.info(
            "Audio generation started: job_id=%s artifact_id=%s", result[0], result[1]
        )
        return str(result[0]), str(result[1])

    def poll_artifact(
        self,
        notebook_id: str,
        artifact_id: str,
        max_wait: int = 600,
        poll_interval: int = 10,
    ) -> Dict[str, Any]:
        """Poll gArtLc until an artifact (audio, video) is complete.

        Args:
            notebook_id: NLM notebook UUID.
            artifact_id: Artifact ID from generate_audio() or similar.
            max_wait: Maximum seconds to wait (audio takes 3–8 minutes).
            poll_interval: Seconds between polls.

        Returns:
            Completed artifact dict (contains download URL).

        Raises:
            RuntimeError: If artifact generation failed.
            TimeoutError: If not complete within max_wait seconds.
        """
        filter_str = 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'
        deadline = time.time() + max_wait
        while time.time() < deadline:
            payload = [None, notebook_id, filter_str]
            rpcid = self._rpcid("list_artifacts") or "gArtLc"
            result = self._rpc_call(rpcid, payload, timeout=30)
            if isinstance(result, list):
                for artifact in result:
                    if not isinstance(artifact, dict):
                        continue
                    if artifact.get("id") != artifact_id:
                        continue
                    status = artifact.get("status", "")
                    logger.debug("Artifact %s status: %s", artifact_id, status)
                    if "COMPLETE" in status or "READY" in status:
                        return artifact
                    if "FAILED" in status or "ERROR" in status:
                        raise RuntimeError(
                            f"Artifact {artifact_id} generation failed: {status}"
                        )
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Artifact {artifact_id} not complete after {max_wait}s"
        )

    def download_audio(self, artifact: Dict[str, Any], output_path: str) -> str:
        """Download a completed audio artifact to a local file.

        Args:
            artifact: Completed artifact dict from ``poll_artifact()``.
            output_path: Local file path to write the MP3 to.

        Returns:
            Absolute path to the written file.
        """
        audio_url = (
            artifact.get("audio_url")
            or artifact.get("url")
            or artifact.get("download_url")
        )
        if not audio_url:
            raise ValueError(
                f"No download URL found in artifact. Keys: {list(artifact.keys())}"
            )

        headers = self._get_headers()
        resp = self._session.get(audio_url, headers=headers, stream=True, timeout=300)
        resp.raise_for_status()

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)

        size_mb = out.stat().st_size / (1024 * 1024)
        logger.info("Downloaded audio: %s (%.1f MB)", output_path, size_mb)
        return str(out.resolve())

    def generate_flashcards(
        self,
        notebook_id: str,
        source_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Generate flashcard Q&A pairs from notebook sources (ciyUvf).

        Flashcards are instant, free Q&A. Every flashcard goes directly into
        the Nexus Q&A cache. No prompt engineering needed — Gemini extracts
        the natural question-answer pairs from the source material.

        Args:
            notebook_id: NLM notebook UUID.
            source_ids: Specific source IDs to use, or None for all.

        Returns:
            List of ``{"question": str, "answer": str}`` dicts.
        """
        src_list = [[sid] for sid in (source_ids or [])]
        payload = [None, notebook_id, src_list]
        rpcid = self._rpcid("generate_flashcards") or "ciyUvf"
        result = self._rpc_call(rpcid, payload, timeout=120)
        cards: List[Dict[str, str]] = []
        if isinstance(result, list):
            for card in result:
                if isinstance(card, (list, tuple)) and len(card) >= 2:
                    cards.append({"question": str(card[0]), "answer": str(card[1])})
                elif isinstance(card, dict):
                    cards.append({
                        "question": card.get("title", card.get("question", "")),
                        "answer": card.get("summary", card.get("answer", "")),
                    })
        logger.info("Generated %d flashcards from notebook %s", len(cards), notebook_id)
        return cards

    def generate_quiz(
        self,
        notebook_id: str,
        source_ids: Optional[List[str]] = None,
        quiz_type: int = 1,
    ) -> List[Dict[str, Any]]:
        """Generate a quiz from notebook sources (R7cb6c).

        Args:
            notebook_id: NLM notebook UUID.
            source_ids: Specific source IDs, or None for all.
            quiz_type: Quiz format (1=multiple choice, 2=true/false).

        Returns:
            List of question dicts with options and source references.
        """
        src_list = [[sid] for sid in (source_ids or [])]
        payload = [None, notebook_id, [None, None, quiz_type, src_list]]
        rpcid = self._rpcid("generate_quiz") or "R7cb6c"
        result = self._rpc_call(rpcid, payload, timeout=120)
        return result if isinstance(result, list) else []

    def generate_mind_map(self, source_ids: List[str]) -> Dict[str, Any]:
        """Generate a concept mind map from source IDs (yyryJe).

        Returns a JSON concept tree: ``{name, children: [{name, children: [...]}]}``.
        Traverse the tree to extract Q&A pairs for Nexus, or visualise
        in a D3.js panel.

        Args:
            source_ids: List of source UUIDs to map.

        Returns:
            Nested dict representing the concept tree.
        """
        src_list = [[sid] for sid in source_ids]
        payload = [src_list]
        rpcid = self._rpcid("generate_mind_map") or "yyryJe"
        result = self._rpc_call(rpcid, payload, timeout=120)
        return result if isinstance(result, dict) else {}

    def generate_blog_post(
        self,
        notebook_id: str,
        artifact_id: str,
        prompt: str,
    ) -> str:
        """Generate long-form narrative content from an artifact (LBwxtb).

        Args:
            notebook_id: NLM notebook UUID.
            artifact_id: Source artifact ID.
            prompt: Narrative direction / creative brief.

        Returns:
            Generated long-form content string.
        """
        payload = [None, [1], artifact_id, notebook_id, [[None, [prompt]]]]
        rpcid = self._rpcid("generate_blog_post") or "LBwxtb"
        result = self._rpc_call(rpcid, payload, timeout=180)
        if isinstance(result, list) and result:
            return str(result[0])
        return str(result) if result else ""

    def get_source_summary(self, source_id: str) -> str:
        """Get Gemini's AI-generated summary of a single source (tr032e).

        Args:
            source_id: Source UUID.

        Returns:
            Markdown summary string.
        """
        payload = [[[[source_id]]]]
        rpcid = self._rpcid("get_source_summary") or "tr032e"
        result = self._rpc_call(rpcid, payload, timeout=60)
        if isinstance(result, list) and result:
            return str(result[0])
        return str(result) if result else ""

    def export_to_sheets(self, artifact_id: str, title: str) -> str:
        """Export any artifact to Google Sheets (Krh3pd).

        The returned URL is a live Google Sheet. Add it back as an NLM source
        via add_source_url() to let Gemini read the spreadsheet data in the
        next call — creating a read-write data loop.

        Args:
            artifact_id: ID of the artifact to export.
            title: Title for the Google Sheet.

        Returns:
            Google Sheets URL string.
        """
        payload = [None, artifact_id, None, title, 2]
        rpcid = self._rpcid("export_to_sheets") or "Krh3pd"
        result = self._rpc_call(rpcid, payload, timeout=60)
        if isinstance(result, list) and result:
            return str(result[0])
        raise RuntimeError(f"export_to_sheets returned no URL: {result}")

    # ──── Notebook management ──────────────────────────────────────────────────

    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all notebooks in this account.

        Rpcids and payloads are resolved from the YAML registry when available,
        with hardcoded fallbacks for robustness.

        Returns:
            List of notebook dicts/lists with id, name, and metadata.
        """
        import base64

        primary, fallback = self._rpcid_pair("list_notebooks")
        candidates = [
            (primary or "wXbhsf", [None, 1, None, [2]]),
            (fallback or "ub2Bae", [[2]]),
        ]

        for rpcid, payload in candidates:
            try:
                result = self._rpc_call(rpcid, payload, timeout=30)
                if not isinstance(result, list):
                    continue

                # Pro-tier rpcid returns [[nb1, nb2, ...], ...] — unwrap the outer layer
                items = result
                if (
                    rpcid != (fallback or "ub2Bae")
                    and len(result) >= 1
                    and isinstance(result[0], list)
                    and result[0]
                    and isinstance(result[0][0], list)
                ):
                    items = result[0]

                notebooks: List[Dict[str, Any]] = []
                for item in items:
                    try:
                        if isinstance(item, str):
                            decoded = base64.b64decode(item).decode("utf-8")
                            notebooks.append(json.loads(decoded))
                        elif isinstance(item, (list, dict)):
                            notebooks.append(item)  # type: ignore[arg-type]
                    except Exception:
                        notebooks.append({"raw": item})
                if notebooks:
                    return notebooks
            except Exception:
                if rpcid == candidates[0][0]:
                    logger.debug("%s failed, trying fallback %s", rpcid, candidates[1][0])
                    continue
                raise
        return []

    def get_artifacts(self, notebook_id: str) -> List[Dict[str, Any]]:
        """List all artifacts in a notebook.

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of artifact dicts with id, status, type, download_url.
        """
        rpcid = self._rpcid("list_artifacts") or "gArtLc"
        filter_str = 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'
        payload = [None, notebook_id, filter_str]
        result = self._rpc_call(rpcid, payload, timeout=30)
        return result if isinstance(result, list) else []

    def update_notebook_title(self, notebook_id: str, new_title: str) -> None:
        """Rename a notebook.

        Args:
            notebook_id: NLM notebook UUID.
            new_title: New display name.
        """
        rpcid = self._rpcid("update_notebook") or "s0tc2d"
        payload = [notebook_id, [[None, None, None, [None, new_title]]]]
        self._rpc_call(rpcid, payload, timeout=30)
        logger.debug("Renamed notebook %s → '%s'", notebook_id, new_title)

    def create_notebook(self, title: str) -> str:
        """Create a new empty NotebookLM notebook.

        Rpcids resolved from YAML registry with hardcoded fallbacks.

        Args:
            title: Display name for the new notebook.

        Returns:
            New notebook ID string.
        """
        primary, fallback = self._rpcid_pair("create_notebook")
        rpcid_pro = primary or "CCqFvf"
        rpcid_legacy = fallback or "VqhFhd"

        payload = [title, None, None, [2], [1, None, None, None, None, None, None, None, None, None, [1]]]
        result = self._rpc_call(rpcid_pro, payload, timeout=30)
        if result and isinstance(result, list):
            nb_id = result[2] if len(result) > 2 and result[2] else None
            if nb_id:
                return str(nb_id)
            if result[0] and len(str(result[0])) > 10:
                return str(result[0])
        # Fallback: try the legacy rpcid
        try:
            payload_legacy = [title, None, None]
            result = self._rpc_call(rpcid_legacy, payload_legacy, timeout=30)
            if result and isinstance(result, list) and result[0]:
                return str(result[0])
        except Exception:
            pass
        raise RuntimeError(f"create_notebook failed for title='{title}': {result}")

    def delete_notebook(self, notebook_id: str) -> None:
        """Permanently delete a notebook and all its sources.

        Uses Pro-tier rpcid with legacy fallback, both from registry.

        Args:
            notebook_id: NLM notebook UUID to delete.
        """
        primary, fallback = self._rpcid_pair("delete_notebook")
        rpcid_pro = primary or "WWINqb"
        rpcid_legacy = fallback or "kVoZqc"

        payload = [[notebook_id], [2]]
        try:
            self._rpc_call(rpcid_pro, payload, timeout=30)
        except Exception:
            logger.debug("%s failed, falling back to %s", rpcid_pro, rpcid_legacy)
            self._rpc_call(rpcid_legacy, [[notebook_id]], timeout=30)
        logger.info("Deleted notebook %s", notebook_id)

    def get_chat_history(self, notebook_id: str) -> List[Dict[str, Any]]:
        """Retrieve the conversation history for a notebook (GzgSEd).

        Each turn is a dict with ``role`` (user/model) and ``text``.

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of conversation turn dicts.
        """
        payload = [notebook_id]
        rpcid = self._rpcid("get_chat_history") or "GzgSEd"
        result = self._rpc_call(rpcid, payload, timeout=30)
        turns: List[Dict[str, Any]] = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, list) and len(item) >= 2:
                    turns.append({"role": str(item[0]), "text": str(item[1])})
                elif isinstance(item, dict):
                    turns.append(item)
        return turns

    def delete_chat_history(self, notebook_id: str) -> None:
        """Delete all chat history for a notebook (GfmCOc).

        Args:
            notebook_id: NLM notebook UUID.
        """
        payload = [notebook_id]
        rpcid = self._rpcid("delete_chat_history") or "GfmCOc"
        self._rpc_call(rpcid, payload, timeout=30)
        logger.debug("Deleted chat history for notebook %s", notebook_id)

    def generate_guide(
        self,
        notebook_id: str,
        guide_type: int = GUIDE_STUDY,
        source_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a structured guide from notebook sources (xqEXEf).

        Guide types:
            GUIDE_STUDY (1)    — Study guide with concepts, definitions, examples
            GUIDE_FAQ (2)      — FAQ format: natural questions with detailed answers
            GUIDE_BRIEFING (3) — Executive briefing: key findings, implications
            GUIDE_TOC (4)      — Table of contents / document outline
            GUIDE_TIMELINE (5) — Chronological timeline of events/topics

        Args:
            notebook_id: NLM notebook UUID.
            guide_type: Type of guide to generate (use GUIDE_* constants).
            source_ids: Specific source IDs, or None for all sources.

        Returns:
            Dict with ``id``, ``title``, ``content`` (markdown).
        """
        src_list = [[sid] for sid in (source_ids or [])]
        payload = [None, notebook_id, guide_type, src_list]
        rpcid = self._rpcid("generate_guide") or "xqEXEf"
        result = self._rpc_call(rpcid, payload, timeout=180)
        if not result:
            raise RuntimeError(f"generate_guide returned empty for notebook {notebook_id}")
        return {
            "id": result[0] if len(result) > 0 else None,
            "title": result[1] if len(result) > 1 else f"Guide (type {guide_type})",
            "content": result[2] if len(result) > 2 else "",
        }

    def share_notebook(self, notebook_id: str, share_level: int = 1) -> str:
        """Get or create a shareable link for a notebook (dI5Y8).

        Args:
            notebook_id: NLM notebook UUID.
            share_level: 1=anyone_with_link (default), 0=private.

        Returns:
            Shareable URL string.
        """
        payload = [notebook_id, share_level]
        rpcid = self._rpcid("share_notebook") or "dI5Y8"
        result = self._rpc_call(rpcid, payload, timeout=30)
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str):
            return result
        raise RuntimeError(f"share_notebook returned no URL for {notebook_id}: {result}")

    def wait_for_source(
        self,
        notebook_id: str,
        source_id: str,
        max_wait: int = 120,
        poll_interval: int = 3,
    ) -> None:
        """Public alias for _poll_source_ready — wait until a source finishes processing.

        Args:
            notebook_id: NLM notebook UUID.
            source_id: Source ID to wait for.
            max_wait: Maximum seconds to wait.
            poll_interval: Seconds between polls.

        Raises:
            TimeoutError: If source is not ready within max_wait seconds.
        """
        self._poll_source_ready(notebook_id, source_id, max_wait=max_wait, poll_interval=poll_interval)

    def generate_data_table(self, notebook_id: str) -> Dict[str, Any]:
        """Generate a structured data table from notebook sources (CCqFvf).

        Extracts tabular data from sources and returns it as a structured
        table with headers and rows.

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            Dict with ``id``, ``title``, ``content`` (table as text/markdown).
        """
        payload = [notebook_id, None, None, [2], [1, None, None, None, None, None, None, None, None, None, [1]]]
        rpcid = self._rpcid("generate_data_table") or "CCqFvf"
        result = self._rpc_call(rpcid, payload, timeout=180)
        if not result:
            return {"id": None, "title": "Data Table", "content": ""}
        return {
            "id": result[0] if len(result) > 0 else None,
            "title": result[1] if len(result) > 1 else "Data Table",
            "content": result[2] if len(result) > 2 else str(result),
        }

    # ──── SDK gap methods (ARGUS audit) ───────────────────────────────────────

    def get_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Fetch metadata for a single notebook (mFtdI).

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            Notebook metadata dict (id, title, created_at, source_count, etc.).
        """
        payload = [notebook_id]
        rpcid = self._rpcid("get_notebook_metadata") or "mFtdI"
        result = self._rpc_call(rpcid, payload, timeout=30)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return {"id": notebook_id, "raw": result}
        return {"id": notebook_id}

    def get_source(self, notebook_id: str, source_id: str) -> Dict[str, Any]:
        """Fetch metadata for a single source (K4YCPe).

        Args:
            notebook_id: NLM notebook UUID.
            source_id: Source UUID.

        Returns:
            Source metadata dict (id, title, type, status, url, etc.).
        """
        payload = [notebook_id, source_id]
        rpcid = self._rpcid("get_source_metadata") or "K4YCPe"
        result = self._rpc_call(rpcid, payload, timeout=30)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return {"id": source_id, "notebook_id": notebook_id, "raw": result}
        return {"id": source_id, "notebook_id": notebook_id}

    def list_sources(self, notebook_id: str) -> List[Dict[str, Any]]:
        """List all sources for a notebook via jtGGne rpcid.

        This is the metadata-rich sources listing (different from ``get_sources``
        which uses the hPTbtc rpcid for the source-content endpoint).

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of source metadata dicts.
        """
        payload = [notebook_id]
        rpcid = self._rpcid("list_sources_metadata") or "jtGGne"
        result = self._rpc_call(rpcid, payload, timeout=30)
        if isinstance(result, list):
            return [
                item if isinstance(item, dict) else {"raw": item}
                for item in result
            ]
        return []

    def process_source(self, notebook_id: str, source_id: str) -> None:
        """Trigger reprocessing of a source (bfEAsb).

        Use after uploading a file or when a source has a failed status.

        Args:
            notebook_id: NLM notebook UUID.
            source_id: Source UUID to reprocess.
        """
        payload = [notebook_id, source_id]
        rpcid = self._rpcid("process_source") or "bfEAsb"
        self._rpc_call(rpcid, payload, timeout=60)
        logger.debug("Triggered reprocessing of source %s in notebook %s", source_id, notebook_id)

    def add_source(
        self,
        notebook_id: str,
        source_type: str,
        content: str,
        title: Optional[str] = None,
    ) -> str:
        """Generic add-source wrapper dispatching by type (PoHVkb).

        For convenience when you don't want to call the type-specific methods.

        Args:
            notebook_id: NLM notebook UUID.
            source_type: One of ``"url"``, ``"text"``, ``"file"``.
            content: URL, raw text body, or local file path.
            title: Optional display title.

        Returns:
            New source ID string.
        """
        source_type = source_type.lower()
        if source_type == "url":
            return self.add_source_url(notebook_id, content, title=title)
        elif source_type == "text":
            return self.add_source_text(notebook_id, content, title=title or "Text Source")
        elif source_type in ("file", "path"):
            return self.add_source_file(notebook_id, content)
        else:
            raise ValueError(f"Unknown source_type '{source_type}'. Use 'url', 'text', or 'file'.")

    def send_chat_message(
        self,
        notebook_id: str,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Send a structured chat message to a notebook (tJHFsf).

        This is the batchexecute variant of the chat endpoint (distinct from
        ``ask()`` which uses the GenerateFreeFormStreamed streaming endpoint).
        Use for fire-and-forget messages when streaming is not needed.

        Args:
            notebook_id: NLM notebook UUID.
            message: User message text.
            conversation_id: Optional existing conversation ID to continue.

        Returns:
            Response text string.
        """
        payload = [notebook_id, message, conversation_id]
        rpcid = self._rpcid("send_chat_message") or "tJHFsf"
        result = self._rpc_call(rpcid, payload, timeout=120)
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str):
            return result
        return str(result) if result else ""

    def get_shared_notebook(self, share_token: str) -> Dict[str, Any]:
        """Access a notebook shared by another user (jzEKsc).

        Args:
            share_token: The share token or share ID from a shared notebook URL.

        Returns:
            Shared notebook metadata dict.
        """
        payload = [share_token]
        rpcid = self._rpcid("get_shared_notebook") or "jzEKsc"
        result = self._rpc_call(rpcid, payload, timeout=30)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return {"share_token": share_token, "raw": result}
        return {"share_token": share_token}

    def get_notebook_analysis(
        self,
        notebook_id: str,
        analysis_depth: int = 2,
    ) -> Dict[str, Any]:
        """Get Gemini's structural analysis of a notebook (VfAZjd).

        Returns conceptual clusters, key themes, source quality signals,
        and readiness scores for guide/audio generation.

        Args:
            notebook_id: NLM notebook UUID.
            analysis_depth: Analysis verbosity (1=summary, 2=detailed).

        Returns:
            Dict with themes, clusters, coverage_score, ready_for_audio, etc.
        """
        payload = [notebook_id, [analysis_depth]]
        rpcid = self._rpcid("get_notebook_analysis") or "VfAZjd"
        result = self._rpc_call(rpcid, payload, timeout=60)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return {"notebook_id": notebook_id, "analysis": result}
        return {"notebook_id": notebook_id}

    def get_audio_overview_options(self, notebook_id: str) -> List[Dict[str, Any]]:
        """Get available audio overview types for a notebook (sqTeoe).

        Returns the list of audio formats available (Deep Dive, Briefing, etc.)
        along with their estimated generation time and readiness.

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of option dicts with type_id, label, estimated_minutes, available.
        """
        payload = [
            [
                2, None, None,
                [1, None, None, None, None, None, None, None, None, None, [1]],
                [[2, 1]],
            ],
            None,
            1,
        ]
        rpcid = self._rpcid("get_audio_options") or "sqTeoe"
        result = self._rpc_call(rpcid, payload, source_path=f"/notebook/{notebook_id}", timeout=30)
        if isinstance(result, list):
            options = []
            for item in result:
                if isinstance(item, (list, dict)):
                    options.append(item if isinstance(item, dict) else {"raw": item})
            return options
        return []

    def get_ice_config(self, notebook_id: str) -> Dict[str, Any]:
        """Fetch WebRTC ICE configuration for live audio (Of0kDd).

        Returns STUN/TURN server configuration needed for WebRTC peer
        connections (live audio overview streaming).

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            ICE config dict with ice_servers, username, credential.
        """
        payload = [notebook_id]
        rpcid = self._rpcid("get_ice_config") or "Of0kDd"
        result = self._rpc_call(rpcid, payload, timeout=15)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return {"notebook_id": notebook_id, "raw": result}
        return {"notebook_id": notebook_id}

    def send_sdp_offer(
        self,
        notebook_id: str,
        sdp_offer: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a WebRTC SDP offer for live audio streaming (eyWvXc).

        Used for initiating live two-way audio conversations with a notebook.
        Requires a prior ``get_ice_config()`` call to obtain STUN/TURN servers.

        Args:
            notebook_id: NLM notebook UUID.
            sdp_offer: WebRTC SDP offer string (from RTCPeerConnection.createOffer).
            session_id: Optional session ID from a prior WebRTC negotiation.

        Returns:
            Dict with sdp_answer, session_id for the WebRTC connection.
        """
        payload = [notebook_id, sdp_offer, session_id]
        rpcid = self._rpcid("send_sdp_offer") or "eyWvXc"
        result = self._rpc_call(rpcid, payload, timeout=30)
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and len(result) >= 2:
            return {"sdp_answer": str(result[0]), "session_id": str(result[1])}
        return {"notebook_id": notebook_id, "raw": result}

    def update_notebook(self, notebook_id: str, new_title: str) -> None:
        """Rename a notebook — alias for ``update_notebook_title`` (sM6gLf/s0tc2d).

        The auditor expects this name. Delegates to ``update_notebook_title``.

        Args:
            notebook_id: NLM notebook UUID.
            new_title: New display title.
        """
        self.update_notebook_title(notebook_id, new_title)

    # ──── Compound helpers ─────────────────────────────────────────────────────

    def run_knowledge_flywheel(
        self,
        notebook_id: str,
        analysis_prompt: str,
        source_ids: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
        """Run the 2-call knowledge flywheel: report → Q&A JSON.

        Call 1 (CYK0Xb): Gemini generates a comprehensive analysis document
        from the ~10k word analysis_prompt against all notebook sources.

        Call 2 (GenerateFreeFormStreamed): Extract 60 Q&A pairs from the
        analysis document as a JSON array.

        Args:
            notebook_id: NLM notebook UUID.
            analysis_prompt: Full creative brief (~10k words).
            source_ids: Source IDs to use. Fetched automatically if omitted.

        Returns:
            Tuple of (report_artifact, qa_pairs_list).
        """
        if source_ids is None:
            source_ids = self.get_sources(notebook_id)

        # Call 1: generate the analysis report
        logger.info("Flywheel call 1/2: generating analysis report...")
        report = self.create_note(notebook_id, analysis_prompt)
        logger.info("Report generated: '%s' (%d chars)", report["title"], len(report["content"]))

        # Call 2: extract Q&A pairs from the report
        qa_prompt = (
            "Based on the analysis document you just created, extract exactly 60 "
            "question-answer pairs that cover the most important concepts, decisions, "
            "and implementation details. Format as a JSON array:\n"
            '[{"q": "...", "a": "..."}, ...]\n'
            "Return ONLY the JSON array. No markdown fences. No explanation."
        )
        logger.info("Flywheel call 2/2: extracting Q&A pairs...")
        qa_response = self.ask(
            notebook_id=notebook_id,
            source_ids=source_ids,
            question=qa_prompt,
            conversation_history=[[report["content"], None]],
        )

        # Parse Q&A JSON
        qa_pairs: List[Dict[str, str]] = []
        try:
            # Strip markdown fences if present
            clean = re.sub(r"```(?:json)?|```", "", qa_response).strip()
            raw_pairs = json.loads(clean)
            for pair in raw_pairs:
                if isinstance(pair, dict):
                    q = pair.get("q") or pair.get("question") or ""
                    a = pair.get("a") or pair.get("answer") or ""
                    if q and a:
                        qa_pairs.append({"question": str(q), "answer": str(a)})
        except json.JSONDecodeError:
            logger.warning("Q&A JSON parse failed, raw response length=%d", len(qa_response))

        logger.info("Flywheel complete: %d Q&A pairs extracted", len(qa_pairs))
        return report, qa_pairs

    def run_audio_flywheel(
        self,
        notebook_id: str,
        focus_text: str,
        output_dir: str = "data/nlm_audio",
        audio_type: int = AUDIO_DEEP_DIVE,
    ) -> Tuple[str, str]:
        """Generate audio → add transcript back as source.

        This is the self-referential loop:
            1. QA9ei with your focus_text → 30-min Gemini podcast (MP3)
            2. Polls until complete
            3. Downloads MP3 to output_dir
            4. Adds MP3 back as a file source → Gemini can now LISTEN to its own podcast

        The returned transcript_source_id can be used in the next
        run_knowledge_flywheel() or run_audio_flywheel() call.
        Repeat and each generation builds on all previous ones.

        Note: Requires ``openai-whisper`` installed for transcription.
        Falls back to returning the raw audio path if Whisper is not available.

        Args:
            notebook_id: NLM notebook UUID.
            focus_text: Producer brief directing the podcast content (~10k words).
            output_dir: Directory for downloaded MP3 files.
            audio_type: AUDIO_DEEP_DIVE (1), AUDIO_BRIEF (2), etc.

        Returns:
            Tuple of ``(audio_path, transcript_source_id)``.
            transcript_source_id is the NLM source ID of the added transcript/audio.
        """
        import hashlib
        ts = int(time.time())
        audio_filename = f"nlm_audio_{ts}.mp3"
        audio_path = str(Path(output_dir) / audio_filename)

        # Step 1: Generate audio
        logger.info("Audio flywheel: generating audio (type=%d)...", audio_type)
        job_id, artifact_id = self.generate_audio(notebook_id, focus_text, audio_type)

        # Step 2: Poll until ready (audio takes 3–8 minutes)
        logger.info("Polling artifact %s (may take several minutes)...", artifact_id)
        artifact = self.poll_artifact(notebook_id, artifact_id, max_wait=600)

        # Step 3: Download MP3
        audio_path = self.download_audio(artifact, audio_path)
        logger.info("Audio downloaded: %s", audio_path)

        # Step 4: Transcribe with Whisper if available
        transcript_text: Optional[str] = None
        try:
            import whisper  # type: ignore[import]
            logger.info("Transcribing with Whisper large...")
            model = whisper.load_model("large")
            result = model.transcribe(audio_path)
            transcript_text = result["text"]
            logger.info("Transcribed: %d words", len(transcript_text.split()))
        except ImportError:
            logger.info("Whisper not available — feeding raw audio as source")

        # Step 5: Add back as source (transcript text or raw audio file)
        title = f"Audio Transcript {ts}" if transcript_text else f"Audio File {ts}"
        if transcript_text:
            source_id = self.add_source_text(notebook_id, title, transcript_text)
        else:
            source_id = self.add_source_file(notebook_id, audio_path, "audio/mpeg")

        logger.info(
            "Audio flywheel complete: audio=%s source_id=%s", audio_path, source_id
        )
        return audio_path, source_id

    # ──── Account / feature flags ──────────────────────────────────────────────

    def get_feature_flags(self, flag_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """Probe NotebookLM feature flag values (GetFeatureFlags / ozz5Z).

        Args:
            flag_ids: List of integer flag IDs to probe. Defaults to a broad range.

        Returns:
            Dict mapping flag_id → value.
        """
        if flag_ids is None:
            flag_ids = list(range(300, 400))
        payload = [[[fid, None, None] for fid in flag_ids]]
        rpcid = self._rpcid("get_feature_flags") or "ozz5Z"
        result = self._rpc_call(rpcid, payload, timeout=30)
        flags: Dict[str, Any] = {}
        if isinstance(result, list):
            for item in result:
                try:
                    if isinstance(item, list) and len(item) >= 2:
                        flags[str(item[0])] = item[1]
                except Exception:
                    pass
        return flags

    def get_locale_preferences(self) -> Dict[str, str]:
        """Return user locale and regional preferences (GetLocalePreferences / DYBcR).

        Returns:
            Dict with locale, language, region strings.
        """
        rpcid = self._rpcid("get_locale_preferences") or "DYBcR"
        result = self._rpc_call(rpcid, [None], timeout=15)
        if isinstance(result, list) and result:
            raw = result[0] if isinstance(result[0], list) else result
            try:
                return {
                    "locale": str(raw[0]) if len(raw) > 0 else "en",
                    "language": str(raw[1]) if len(raw) > 1 else "en",
                    "region": str(raw[2]) if len(raw) > 2 else "",
                }
            except Exception:
                logger.debug("Locale preference parsing partial failure for raw=%s", raw)
                return {"locale": str(raw[0]) if raw else "en"}
        return {"locale": "en"}

    # ──── gRPC-web heap-discovered methods — Artifacts ─────────────────────────

    def create_artifact(
        self,
        notebook_id: str,
        artifact_type: str = "note",
        title: str = "",
        content: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Create a new artifact in a notebook (heap-discovered: CreateArtifact).

        Args:
            notebook_id: Notebook UUID.
            artifact_type: Artifact type string (e.g. ``'note'``, ``'summary'``).
            title: Display title for the artifact.
            content: Initial content body.

        Returns:
            Parsed response with artifact metadata, or ``None``.
        """
        payload = [notebook_id, artifact_type, title, content]
        return self._grpc_call("CreateArtifact", payload, notebook_id=notebook_id)

    def derive_artifact(
        self,
        notebook_id: str,
        source_artifact_id: str,
        derivation_type: str = "summary",
    ) -> Optional[Dict[str, Any]]:
        """Derive a new artifact from an existing one (heap-discovered: DeriveArtifact).

        Args:
            notebook_id: Notebook UUID.
            source_artifact_id: ID of the artifact to derive from.
            derivation_type: Type of derivation (e.g. ``'summary'``, ``'expansion'``).

        Returns:
            Parsed response with derived artifact metadata, or ``None``.
        """
        payload = [notebook_id, source_artifact_id, derivation_type]
        return self._grpc_call("DeriveArtifact", payload, notebook_id=notebook_id)

    def generate_artifact(
        self,
        notebook_id: str,
        prompt: str,
        artifact_type: str = "note",
    ) -> Optional[Dict[str, Any]]:
        """Generate an artifact from a prompt (heap-discovered: GenerateArtifact).

        Args:
            notebook_id: Notebook UUID.
            prompt: Generation prompt / instructions.
            artifact_type: Desired artifact type.

        Returns:
            Parsed response with generated artifact, or ``None``.
        """
        payload = [notebook_id, prompt, artifact_type]
        return self._grpc_call("GenerateArtifact", payload, notebook_id=notebook_id)

    def get_artifact_user_state(
        self,
        notebook_id: str,
        artifact_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get user-specific state for an artifact (heap-discovered: GetArtifactUserState).

        Args:
            notebook_id: Notebook UUID.
            artifact_id: Artifact ID.

        Returns:
            User state data (read status, bookmarks, etc.), or ``None``.
        """
        payload = [notebook_id, artifact_id]
        return self._grpc_call("GetArtifactUserState", payload, notebook_id=notebook_id)

    def upsert_artifact_user_state(
        self,
        notebook_id: str,
        artifact_id: str,
        state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update user-specific state for an artifact (heap-discovered: UpsertArtifactUserState).

        Args:
            notebook_id: Notebook UUID.
            artifact_id: Artifact ID.
            state: State dict to upsert (e.g. ``{"read": true, "pinned": true}``).

        Returns:
            Updated state confirmation, or ``None``.
        """
        payload = [notebook_id, artifact_id, state]
        return self._grpc_call("UpsertArtifactUserState", payload, notebook_id=notebook_id)

    # ──── gRPC-web heap-discovered methods — Sources ──────────────────────────

    def check_source_freshness(
        self,
        notebook_id: str,
        source_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Check if sources are stale (heap-discovered: CheckSourceFreshness).

        Args:
            notebook_id: Notebook UUID.
            source_ids: Optional list of specific source IDs. If ``None``,
                checks all sources in the notebook.

        Returns:
            Freshness status for each source, or ``None``.
        """
        payload = [notebook_id, source_ids or []]
        return self._grpc_call("CheckSourceFreshness", payload, notebook_id=notebook_id)

    def discover_sources_async(
        self,
        notebook_id: str,
        query: str,
        max_results: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """Start async source discovery (heap-discovered: DiscoverSourcesAsync).

        Searches the web or linked services for relevant sources to add.

        Args:
            notebook_id: Notebook UUID.
            query: Search query for source discovery.
            max_results: Maximum number of sources to discover.

        Returns:
            Job ID and initial status, or ``None``.
        """
        payload = [notebook_id, query, max_results]
        return self._grpc_call("DiscoverSourcesAsync", payload, notebook_id=notebook_id)

    def discover_sources_manifold(
        self,
        notebook_id: str,
        query: str,
        sources: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Discover sources via manifold search (heap-discovered: DiscoverSourcesManifold).

        Args:
            notebook_id: Notebook UUID.
            query: Discovery query string.
            sources: Optional list of source types/channels to search.

        Returns:
            Discovered source candidates, or ``None``.
        """
        payload = [notebook_id, query, sources or []]
        return self._grpc_call("DiscoverSourcesManifold", payload, notebook_id=notebook_id)

    def cancel_discover_sources_job(
        self,
        notebook_id: str,
        job_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Cancel a running source discovery job (heap-discovered: CancelDiscoverSourcesJob).

        Args:
            notebook_id: Notebook UUID.
            job_id: Discovery job ID from ``discover_sources_async()``.

        Returns:
            Cancellation confirmation, or ``None``.
        """
        payload = [notebook_id, job_id]
        return self._grpc_call("CancelDiscoverSourcesJob", payload, notebook_id=notebook_id)

    def finish_discover_sources_run(
        self,
        notebook_id: str,
        job_id: str,
        accept_source_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Finish a source discovery run, optionally accepting sources (heap-discovered: FinishDiscoverSourcesRun).

        Args:
            notebook_id: Notebook UUID.
            job_id: Discovery job ID.
            accept_source_ids: IDs of discovered sources to accept/add.

        Returns:
            Finalization result, or ``None``.
        """
        payload = [notebook_id, job_id, accept_source_ids or []]
        return self._grpc_call("FinishDiscoverSourcesRun", payload, notebook_id=notebook_id)

    def mutate_source(
        self,
        notebook_id: str,
        source_id: str,
        mutations: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Apply mutations to a source (heap-discovered: MutateSource).

        Args:
            notebook_id: Notebook UUID.
            source_id: Source ID to mutate.
            mutations: Mutation dict (e.g. ``{"title": "New Title"}``).

        Returns:
            Updated source metadata, or ``None``.
        """
        payload = [notebook_id, source_id, mutations]
        return self._grpc_call("MutateSource", payload, notebook_id=notebook_id)

    def refresh_source(
        self,
        notebook_id: str,
        source_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Refresh a source to re-fetch content (heap-discovered: RefreshSource).

        Args:
            notebook_id: Notebook UUID.
            source_id: Source ID to refresh.

        Returns:
            Refresh status, or ``None``.
        """
        payload = [notebook_id, source_id]
        return self._grpc_call("RefreshSource", payload, notebook_id=notebook_id)

    def delete_sources_bulk(
        self,
        notebook_id: str,
        source_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Bulk-delete sources from a notebook (heap-discovered: DeleteSources).

        Args:
            notebook_id: Notebook UUID.
            source_ids: List of source IDs to delete.

        Returns:
            Deletion confirmation, or ``None``.
        """
        payload = [notebook_id, source_ids]
        return self._grpc_call("DeleteSources", payload, notebook_id=notebook_id)

    # ──── gRPC-web heap-discovered methods — Projects ─────────────────────────

    def mutate_project(
        self,
        notebook_id: str,
        mutations: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Apply mutations to a project/notebook (heap-discovered: MutateProject).

        Args:
            notebook_id: Notebook UUID.
            mutations: Mutation dict (e.g. ``{"title": "New Name"}``).

        Returns:
            Updated project metadata, or ``None``.
        """
        payload = [notebook_id, mutations]
        return self._grpc_call("MutateProject", payload, notebook_id=notebook_id)

    def delete_projects(
        self,
        project_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Bulk-delete projects/notebooks (heap-discovered: DeleteProjects).

        Args:
            project_ids: List of notebook UUIDs to delete.

        Returns:
            Deletion confirmation, or ``None``.
        """
        payload = [project_ids]
        return self._grpc_call("DeleteProjects", payload)

    def list_featured_projects(self) -> Optional[List[Any]]:
        """List featured/template projects (heap-discovered: ListFeaturedProjects).

        Returns:
            List of featured project metadata, or ``None``.
        """
        payload = []
        return self._grpc_call("ListFeaturedProjects", payload)

    def update_featured_notebook_status(
        self,
        notebook_id: str,
        status: str = "featured",
    ) -> Optional[Dict[str, Any]]:
        """Update the featured status of a notebook (heap-discovered: UpdateFeaturedNotebookStatus).

        Args:
            notebook_id: Notebook UUID.
            status: New status string (e.g. ``'featured'``, ``'unfeatured'``).

        Returns:
            Status update confirmation, or ``None``.
        """
        payload = [notebook_id, status]
        return self._grpc_call("UpdateFeaturedNotebookStatus", payload, notebook_id=notebook_id)

    # ──── gRPC-web heap-discovered methods — Chat ─────────────────────────────

    def delete_chat_turns(
        self,
        notebook_id: str,
        turn_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Delete specific chat turns from a notebook (heap-discovered: DeleteChatTurns).

        Args:
            notebook_id: Notebook UUID.
            turn_ids: List of turn IDs to delete.

        Returns:
            Deletion confirmation, or ``None``.
        """
        payload = [notebook_id, turn_ids]
        return self._grpc_call("DeleteChatTurns", payload, notebook_id=notebook_id)

    def list_chat_sessions(
        self,
        notebook_id: str,
    ) -> Optional[List[Any]]:
        """List chat sessions in a notebook (heap-discovered: ListChatSessions).

        Args:
            notebook_id: Notebook UUID.

        Returns:
            List of chat session metadata, or ``None``.
        """
        payload = [notebook_id]
        return self._grpc_call("ListChatSessions", payload, notebook_id=notebook_id)

    # ──── gRPC-web heap-discovered methods — Notes ────────────────────────────

    def mutate_note(
        self,
        notebook_id: str,
        note_id: str,
        mutations: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Apply mutations to a notebook note (heap-discovered: MutateNote).

        Args:
            notebook_id: Notebook UUID.
            note_id: Note ID to mutate.
            mutations: Mutation dict (e.g. ``{"content": "Updated text"}``).

        Returns:
            Updated note metadata, or ``None``.
        """
        payload = [notebook_id, note_id, mutations]
        return self._grpc_call("MutateNote", payload, notebook_id=notebook_id)

    # ──── gRPC-web heap-discovered methods — Account ──────────────────────────

    def get_or_create_account(self) -> Optional[Dict[str, Any]]:
        """Get or create the NLM account record (heap-discovered: GetOrCreateAccount).

        Returns:
            Account metadata including tier, quotas, preferences, or ``None``.
        """
        payload = []
        return self._grpc_call("GetOrCreateAccount", payload)

    # ──── gRPC-web heap-discovered methods — Moderation ───────────────────────

    def report_content(
        self,
        notebook_id: str,
        content_id: str,
        reason: str = "inappropriate",
        details: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Report content for moderation (heap-discovered: ReportContent).

        Args:
            notebook_id: Notebook UUID.
            content_id: ID of the content to report.
            reason: Report reason category.
            details: Optional additional details.

        Returns:
            Report confirmation, or ``None``.
        """
        payload = [notebook_id, content_id, reason, details]
        return self._grpc_call("ReportContent", payload, notebook_id=notebook_id)

    # ──── gRPC-web heap-discovered methods — Suggestions ──────────────────────

    def generate_prompt_suggestions(
        self,
        notebook_id: str,
        context: str = "",
        count: int = 5,
    ) -> Optional[List[str]]:
        """Generate prompt suggestions for a notebook (heap-discovered: GeneratePromptSuggestions).

        Args:
            notebook_id: Notebook UUID.
            context: Optional context to guide suggestion generation.
            count: Number of suggestions to generate.

        Returns:
            List of suggested prompts, or ``None``.
        """
        payload = [notebook_id, context, count]
        return self._grpc_call("GeneratePromptSuggestions", payload, notebook_id=notebook_id)

    def generate_report_suggestions(
        self,
        notebook_id: str,
        report_type: str = "summary",
        context: str = "",
    ) -> Optional[List[str]]:
        """Generate report suggestions for a notebook (heap-discovered: GenerateReportSuggestions).

        Args:
            notebook_id: Notebook UUID.
            report_type: Type of report to suggest (e.g. ``'summary'``, ``'analysis'``).
            context: Optional context to guide suggestions.

        Returns:
            List of suggested report topics/structures, or ``None``.
        """
        payload = [notebook_id, report_type, context]
        return self._grpc_call("GenerateReportSuggestions", payload, notebook_id=notebook_id)


# ──── Factory ─────────────────────────────────────────────────────────────────

def get_nlm_direct_client(
    account_name: Optional[str] = None,
) -> Optional[NLMDirectClient]:
    """Get an NLMDirectClient for the named account or next available one.

    Args:
        account_name: Specific account name, or None for round-robin.

    Returns:
        NLMDirectClient, or None if no account is available.
    """
    pool = get_account_pool()

    if account_name:
        account = pool.get_by_name(account_name)
    else:
        account = pool.get_account("notebooklm")

    if account is None:
        logger.warning(
            "No NotebookLM account available (requested: %s). "
            "Import an account with: pool.import_from_har(har_path, name, ['notebooklm'])",
            account_name,
        )
        return None

    return NLMDirectClient(account)
