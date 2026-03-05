"""Google AI Mode (AIM) client — reverse-engineered from HAR + heap captures.

Google AI Mode (udm=50) is the AI-powered search interface at google.com.
It includes:
- Conversational follow-up via /async/folif (follow in flow)
- Inline image viewer via /async/imgv
- Canvas document creation/editing/export
- Thread management via AimThreadsService (12 methods)
- Side-by-side mode (aim_sxs), journey creation, share management

Architecture:
    1. Start a search: GET /search?q=...&udm=50  → initial HTML + session tokens
    2. Follow-up: GET /async/folif?q=...&stkp=...&elrc=...&mstk=...
    3. Export canvas: POST /httpservice/web/AimThreadsService/ExportThread
    4. Thread CRUD: POST /httpservice/web/AimThreadsService/{Method}
    5. Image viewer: GET /async/imgv?tbnid=...&docid=...&udm=50&aep=10

Discovered from HAR + heap analysis (2026-03-05, two heap snapshots + 3 log files):

Endpoints:
    /async/folif                          — conversation turn (follow in flow)
    /async/folwr                          — follow with rewrite (canvas edit mode)
    /async/imgv                           — inline image viewer within AI Mode
    AimThreadsService/ListThreads         — list saved threads
    AimThreadsService/ListSharedThreads   — shared threads
    AimThreadsService/SearchThreads       — search by query
    AimThreadsService/GetThreadContext    — get thread detail
    AimThreadsService/ExportThread        — export canvas as HTML (JSPB response)
    AimThreadsService/UpdateThread        — rename / update thread metadata
    AimThreadsService/DeleteThreads       — delete threads by ID list
    AimThreadsService/DeleteSharedThreads — delete shared threads
    AimThreadsService/InitiateShare       — create shareable link
    AimThreadsService/CreateJourney       — create a journey/project grouping threads
    AimThreadsService/UpdateJourneys      — update journey metadata
    AimThreadsService/DeleteJourneys      — delete journeys

Canvas DOM events (dispatched on the canvas container element):
    aimCanvasBeforeFirstContentPaint  — first pixel painted
    aimCanvasDiffsAvailable           — incremental diff patches ready
    aimCanvasPatchStart               — applying a patch to canvas HTML
    aimCanvasPatchFinished            — patch application complete
    aimCanvasRenderStarted            — canvas render beginning
    aimCanvasRenderFinished           — canvas render complete
    aimCanvasTitleAvailable           — title extracted from canvas content
    aimCanvasContainerResize          — canvas container resized

Thread lifecycle events:
    aimMstkAvailable       → handler OxNw6c  — new mstk token available (use for next turn)
    aimRenderComplete      → handler iuwyKd  — full render complete
    aimBodyComplete        → handler C6rCke  — response body complete
    aimModelResponseStarted → handler R5LEBf — model started generating
    aimOpenShareManagementView → handler dfHbI
    aimOpenStatefulJourneyCreation → handler eA5Ajf
    aimOpenStatefulJourneyHub → handler zAaRWc
    aimNavigateToZeroState → handler CFLK0e

UI interaction events:
    aimInputPlateDrag / LockInput / RequestEdit / RequestHide / RequestRestore
    aimInputPlateUnlockInput / UpdateState
    aimInterrupt              — cancel in-flight generation
    aimOpenThreadsView        — open thread list UI
    aimThreadRhsResize / Update — right-hand panel resize
    aimThreadsViewStateChange — thread list view state changed

URL params:
    udm=50      — activates AI Mode
    aep=10      — activates AI Exploration Panel (side panel)
    canvasid    — loads a specific canvas by ID in new search
    stkp        — session token (per conversation)
    elrc        — encoded context proto (conversation threading)
    mstk        — message/mstk token (from aimMstkAvailable event)
    csui=3      — context UI type (3 = AI Mode)
    csuir=1     — context UI request flag
    aim_sxs     — side-by-side mode
    aim_padt    — prompt/add-text flag
    aim_folif   — follow in flow mode
    aim_folwr   — follow with rewrite mode

Canvas controller:
    jscontroller="AwlxTd"          — canvas component controller class
    data-suuid="<uuid>||"          — canvas session UUID
    data-component-xid="Z9Ie4d"   — component identifier
    folwr-token="XSRF:timestamp"   — separate auth token for rewrite ops

JSPB format: responses start with )]}' + newline, then JSON.
ExportThread body: [null, [mstk_token], thread_ei, [1], null, 2]
ExportThread response: ["query", [[[null, "<html>"], "\\n"]]]
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ──── Constants ────────────────────────────────────────────────────────────────

BASE_URL = "https://www.google.com"
AIM_SEARCH_URL = f"{BASE_URL}/search"
FOLIF_URL = f"{BASE_URL}/async/folif"
FOLWR_URL = f"{BASE_URL}/async/folwr"
IMGV_URL = f"{BASE_URL}/async/imgv"
HTTPSERVICE_URL = f"{BASE_URL}/httpservice/web/AimThreadsService"

# udm=50 activates AI Mode; aep=10 activates AI Exploration Panel
AIM_PARAMS = {"udm": "50", "aep": "10"}

# fmt=jspb returns JSON-PB (Google's binary-compat JSON format)
# Response starts with )]}'  and then valid JSON
SERVICE_PARAMS = {"fmt": "jspb", "msc": "gwsclient", "opi": "89978449"}

# Canvas DOM event names dispatched on the canvas container
CANVAS_EVENTS = [
    "aimCanvasBeforeFirstContentPaint",
    "aimCanvasDiffsAvailable",
    "aimCanvasPatchStart",
    "aimCanvasPatchFinished",
    "aimCanvasRenderStarted",
    "aimCanvasRenderFinished",
    "aimCanvasTitleAvailable",
    "aimCanvasContainerResize",
]

# Thread lifecycle events with their obfuscated handler names (from heap jsaction)
THREAD_EVENTS = {
    "aimMstkAvailable": "OxNw6c",
    "aimRenderComplete": "iuwyKd",
    "aimBodyComplete": "C6rCke",
    "aimModelResponseStarted": "R5LEBf",
    "aimOpenShareManagementView": "dfHbI",
    "aimOpenStatefulJourneyCreation": "eA5Ajf",
    "aimOpenStatefulJourneyHub": "zAaRWc",
    "aimNavigateToZeroState": "CFLK0e",
}

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "DNT": "1",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "X-Browser-Channel": "stable",
}


def _strip_jspb(text: str) -> Any:
    """Strip the )]}' JSPB prefix and parse JSON.

    Args:
        text: Raw response body from a fmt=jspb endpoint.

    Returns:
        Parsed Python object.
    """
    text = text.strip()
    if text.startswith(")]}'"):
        text = text[4:].lstrip("\n")
    import json
    return json.loads(text)


# ──── Session state ─────────────────────────────────────────────────────────────

class AIMSession(BaseModel):
    """Holds the stateful tokens required for a multi-turn AIM conversation.

    Attributes:
        thread_ei: Conversation/thread ID extracted from folif response HTML.
        stkp: Session token from the most recent folif response.
        mstk: Another session token variant (data-mstk from HTML).
        msei: Session event ID (data-msei from HTML).
        xsrf: XSRF token from cookie.
        elrc: Encoded conversation context (base64 protobuf).
        query: Last query sent.
    """

    model_config = ConfigDict(validate_assignment=True)

    thread_ei: Optional[str] = None
    stkp: Optional[str] = None
    mstk: Optional[str] = None
    msei: Optional[str] = None
    xsrf: Optional[str] = None
    elrc: Optional[str] = None
    query: Optional[str] = None

    @classmethod
    def from_folif_html(cls, html: str, xsrf: str) -> "AIMSession":
        """Parse session tokens from a /async/folif HTML response.

        Args:
            html: Raw HTML response text from /async/folif.
            xsrf: XSRF token from cookies.

        Returns:
            Populated AIMSession.
        """
        fields: Dict[str, Optional[str]] = {"xsrf": xsrf}

        m = re.search(r'data-container-id="([^"]+)"', html)
        if m:
            fields["thread_ei"] = m.group(1)

        m = re.search(r'data-mstk="([^"]+)"', html)
        if m:
            fields["mstk"] = m.group(1)

        m = re.search(r'data-msei="([^"]+)"', html)
        if m:
            fields["msei"] = m.group(1)

        return cls(**fields)

    def is_valid(self) -> bool:
        """Check if session has minimum required tokens."""
        return bool(self.thread_ei and self.xsrf)

    def __repr__(self) -> str:
        xsrf_preview = (self.xsrf[:10] + "...") if self.xsrf else "None"
        return (
            f"AIMSession(thread_ei={self.thread_ei!r}, "
            f"xsrf={xsrf_preview!r}, valid={self.is_valid()})"
        )


# ──── Main client ───────────────────────────────────────────────────────────────

class GoogleAIMClient:
    """Client for Google AI Mode (AIM) — search, canvas, and thread management.

    Google AI Mode is the conversational AI interface embedded in Google Search
    (enabled with udm=50). It can create Canvas documents, share threads,
    and maintain multi-turn conversations.

    Usage::

        client = GoogleAIMClient(cookies={"SID": "...", "HSID": "..."})

        # Start a conversation
        session, html = client.search("Explain quantum computing")

        # Follow up (canvas mode)
        session, html = client.followup(
            session, "Create a canvas document summarizing this"
        )

        # Export the canvas
        canvas = client.export_thread(session)
        print(canvas["content"])

        # List your saved threads
        threads = client.list_threads()
    """

    def __init__(
        self,
        cookies: Optional[Dict[str, str]] = None,
        account_name: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        """Initialise the AIM client.

        Args:
            cookies: Google session cookies (SID, HSID, SSID, APISID, etc.)
            account_name: Account key in data/accounts/pool.json (alternative to cookies).
            timeout: Request timeout in seconds.
        """
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

        if cookies:
            self._session.cookies.update(cookies)
        elif account_name:
            self._load_account_cookies(account_name)

    # ──── Auth helpers ────────────────────────────────────────────────────────

    def _load_account_cookies(self, account_name: str) -> None:
        """Load cookies from the shared account pool.

        Args:
            account_name: Key in data/accounts/pool.json (e.g. 'nihilistcod').
        """
        import json
        from pathlib import Path

        pool_path = Path("data/accounts/pool.json")
        if not pool_path.exists():
            raise FileNotFoundError(f"Account pool not found: {pool_path}")

        with pool_path.open(encoding="utf-8") as fh:
            pool = json.load(fh)

        account = pool.get(account_name)
        if not account:
            raise ValueError(f"Account '{account_name}' not found in pool")

        raw_cookies = account.get("cookies", [])
        for c in raw_cookies:
            self._session.cookies.set(
                c.get("name", ""),
                c.get("value", ""),
                domain=c.get("domain", ".google.com"),
                path=c.get("path", "/"),
            )

        logger.info("Loaded %d cookies for account '%s'", len(raw_cookies), account_name)

    def _get_xsrf(self) -> str:
        """Extract XSRF token from current session cookies.

        Returns:
            XSRF token string.

        Raises:
            RuntimeError: If XSRF cookie is not available.
        """
        xsrf = self._session.cookies.get("__Secure-1PSIDTS")
        if not xsrf:
            xsrf = self._session.cookies.get("XSRF-TOKEN")
        if not xsrf:
            # Construct from SAPISID hash (fallback)
            sapisid = self._session.cookies.get("SAPISID") or self._session.cookies.get("__Secure-1PAPISID")
            if sapisid:
                ts = str(int(time.time() * 1000))
                import hashlib
                h = hashlib.sha1(f"{ts} {sapisid} {BASE_URL}".encode()).hexdigest()
                xsrf = f"SAPISIDHASH {ts}_{h}"
        if not xsrf:
            raise RuntimeError(
                "No XSRF token available. Load Google session cookies first."
            )
        return xsrf

    # ──── Search & conversation ───────────────────────────────────────────────

    def search(
        self,
        query: str,
        hl: str = "en",
    ) -> Tuple[AIMSession, str]:
        """Start a new AI Mode conversation with an initial search query.

        Hits the Google Search page in AI Mode (udm=50) and extracts the
        initial session tokens needed for follow-up turns.

        Args:
            query: The search query.
            hl: UI language code.

        Returns:
            Tuple of (AIMSession, raw_html_response).
        """
        params = {
            "q": query,
            "udm": "50",
            "aep": "10",
            "hl": hl,
        }
        resp = self._session.get(
            AIM_SEARCH_URL, params=params, timeout=self._timeout
        )
        resp.raise_for_status()
        html = resp.text

        xsrf = self._get_xsrf()
        session = AIMSession.from_folif_html(html, xsrf)
        session.query = query

        # Try to extract stkp (session token key) from the page
        m = re.search(r'"stkp":"([^"]+)"', html)
        if m:
            session.stkp = m.group(1)
        m = re.search(r'"elrc":"([^"]+)"', html)
        if m:
            session.elrc = m.group(1)

        logger.info(
            "AIM search started: %r → thread=%s", query[:60], session.thread_ei
        )
        return session, html

    def followup(
        self,
        session: AIMSession,
        query: str,
        yv: int = 3,
    ) -> Tuple[AIMSession, str]:
        """Send a follow-up question in an existing AIM conversation.

        Uses /async/folif endpoint which is the conversational AJAX endpoint
        for Google AI Mode. Supports canvas creation requests.

        Args:
            session: Current AIMSession with valid tokens.
            query: The follow-up question/instruction.
            yv: Request version number (default 3).

        Returns:
            Tuple of (updated_AIMSession, raw_html_response).
        """
        if not session.xsrf:
            session.xsrf = self._get_xsrf()

        params: Dict[str, Any] = {
            "q": query,
            "udm": "50",
            "aep": "10",
            "yv": str(yv),
            "cs": "1",
            "csuir": "0",
            "csui": "3",
            "_fmt": "adl",
        }

        if session.thread_ei:
            params["ei"] = session.thread_ei
        if session.stkp:
            params["stkp"] = session.stkp
        if session.mstk:
            params["mstk"] = session.mstk
        if session.elrc:
            params["elrc"] = session.elrc

        # Add XSRF to async params
        params["_xsrf"] = session.xsrf

        # Build the async= parameter (Google's async query format)
        async_val = f"_fmt:adl,_xsrf:{urllib.parse.quote(session.xsrf)}"
        params["async"] = async_val

        resp = self._session.get(
            FOLIF_URL, params=params, timeout=self._timeout
        )
        resp.raise_for_status()
        html = resp.text

        # Update session with new tokens from response
        new_session = AIMSession.from_folif_html(html, session.xsrf)
        new_session.stkp = session.stkp
        new_session.elrc = session.elrc
        new_session.query = query

        # Update stkp/mstk if new ones appeared
        if not new_session.thread_ei:
            new_session.thread_ei = session.thread_ei

        logger.info(
            "AIM followup: %r → thread=%s, canvas=%s",
            query[:60],
            new_session.thread_ei,
            "aim/canvas" in html,
        )
        return new_session, html

    # ──── Canvas operations ───────────────────────────────────────────────────

    def followup_rewrite(
        self,
        session: AIMSession,
        query: str,
        *,
        csui: int = 3,
    ) -> Tuple[AIMSession, str]:
        """Send a follow-up with canvas rewrite mode via /async/folwr.

        ``folwr`` (follow with rewrite) triggers a canvas edit operation —
        the model rewrites or extends the existing canvas document rather than
        appending a new turn. Use when the canvas already exists and the user
        wants in-place editing.

        The ``folwr-token`` is the rewrite-specific XSRF token embedded as a
        ``data-`` attribute on the canvas container in the prior response HTML.
        If unavailable, falls back to the standard ``xsrf`` token.

        Args:
            session: Current AIMSession with valid mstk + thread_ei.
            query: The rewrite instruction to the model.
            csui: Context UI type (default 3 = AI Mode).

        Returns:
            Tuple of (updated AIMSession, raw response HTML).
        """
        if not session.is_valid():
            raise ValueError(f"Invalid session for rewrite: {session}")

        params = {
            **AIM_PARAMS,
            "q": query,
            "stkp": session.stkp or "",
            "mstk": session.mstk or "",
            "csui": str(csui),
            "csuir": "1",
            "opi": SERVICE_PARAMS["opi"],
        }
        if session.elrc:
            params["elrc"] = session.elrc
        if session.thread_ei:
            params["ei"] = session.thread_ei

        resp = self._session.get(FOLWR_URL, params=params, timeout=self._timeout)
        resp.raise_for_status()
        html = resp.text

        new_session = AIMSession.from_folif_html(html, session.xsrf)
        new_session.stkp = session.stkp
        new_session.elrc = session.elrc
        new_session.query = query
        if not new_session.thread_ei:
            new_session.thread_ei = session.thread_ei

        logger.info(
            "AIM folwr rewrite: %r → canvas=%s",
            query[:60],
            "aim/canvas" in html,
        )
        return new_session, html

    def get_image_viewer(
        self,
        session: AIMSession,
        tbnid: str,
        docid: str,
        query: str = "",
        *,
        yv: int = 3,
    ) -> str:
        """Load the inline image viewer (/async/imgv) within an AI Mode context.

        Discovered from HAR log (2026-03-05): imgv is called when the user
        clicks an image result inside an AI Mode conversation. Returns HTML
        for the inline image detail panel.

        The ``_id`` format observed: ``imgv__1:2389:async:1:{tbnid}-{docid}-1-__h``

        Args:
            session: Current AIMSession (provides ei/vet context).
            tbnid: Thumbnail ID from the image search result.
            docid: Document ID of the image.
            query: The search query (for context).
            yv: Image viewer version (default 3).

        Returns:
            Raw HTML of the image viewer panel.
        """
        params = {
            **AIM_PARAMS,
            "tbnid": tbnid,
            "imgdii": tbnid,
            "docid": docid,
            "yv": str(yv),
            "cs": "1",
            "opi": SERVICE_PARAMS["opi"],
        }
        if query:
            params["q"] = query
        if session.thread_ei:
            params["ei"] = session.thread_ei

        resp = self._session.get(IMGV_URL, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.text

    def export_thread(
        self,
        session: AIMSession,
        export_type: int = 1,
    ) -> Dict[str, Any]:
        """Export the canvas content from an AI Mode thread.

        POST /httpservice/web/AimThreadsService/ExportThread
        Body: [null, [session_token], thread_id, [export_type], null, 2]
        Response: JSPB array with [query, [[[null, html_content], ...], ...]]

        Args:
            session: AIMSession with valid thread_ei and mstk/xsrf.
            export_type: Export format type (1 = default HTML canvas).

        Returns:
            Dict with ``thread_id``, ``query``, ``content`` (HTML), ``raw``.
        """
        if not session.is_valid():
            raise ValueError(f"Invalid session for export: {session}")

        token = session.mstk or session.stkp or ""
        body = [None, [token], session.thread_ei, [export_type], None, 2]

        import json as _json
        raw_body = _json.dumps(body, separators=(",", ":"))

        params = {
            "aep": "10",
            "udm": "50",
            "msc": "gwsclient",
            "opi": "89978449",
            "fmt": "jspb",
            "xsrf": f"{session.xsrf}",
        }

        resp = self._session.post(
            f"{HTTPSERVICE_URL}/ExportThread",
            data=raw_body,
            params=params,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        raw = _strip_jspb(resp.text)

        # Parse response: ["query", [[[null, "<html>"], "\n"], ...]]
        query = raw[0] if raw and len(raw) > 0 else ""
        content_html = ""
        if len(raw) > 1 and isinstance(raw[1], list):
            blocks = raw[1]
            for block in blocks:
                if isinstance(block, list) and len(block) > 0:
                    inner = block[0]
                    if isinstance(inner, list) and len(inner) > 1:
                        content_html += str(inner[1] or "")

        logger.info(
            "Exported thread %s: query=%r, html_len=%d",
            session.thread_ei, query[:60], len(content_html)
        )
        return {
            "thread_id": session.thread_ei,
            "query": query,
            "content": content_html,
            "content_html": content_html,
            "raw": raw,
        }

    def is_canvas_response(self, html: str) -> bool:
        """Check if a folif response contains a canvas.

        Args:
            html: Raw HTML from a /async/folif response.

        Returns:
            True if the response includes canvas content.
        """
        return "aim/canvas" in html or "Canvas is used in this thread" in html

    # ──── AimThreadsService CRUD ──────────────────────────────────────────────

    def _httpservice_post(
        self,
        method: str,
        body: Any,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Generic POST to AimThreadsService/{method}.

        Args:
            method: Service method name (e.g. 'ListThreads').
            body: Request body (will be JSON-serialised).
            extra_params: Additional query params.

        Returns:
            Parsed response (JSPB stripped).
        """
        import json as _json

        params = {**SERVICE_PARAMS, **AIM_PARAMS}
        if extra_params:
            params.update(extra_params)

        xsrf = self._get_xsrf()
        params["xsrf"] = xsrf

        raw_body = _json.dumps(body, separators=(",", ":"))
        resp = self._session.post(
            f"{HTTPSERVICE_URL}/{method}",
            data=raw_body,
            params=params,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return _strip_jspb(resp.text)

    def list_threads(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """List saved AI Mode conversation threads.

        Args:
            max_results: Maximum threads to return.

        Returns:
            List of thread dicts with id, title, timestamp, has_canvas.
        """
        body = [max_results, None, None]
        raw = self._httpservice_post("ListThreads", body)
        threads = []
        if isinstance(raw, list):
            for item in (raw[0] if raw and isinstance(raw[0], list) else raw):
                if not isinstance(item, list):
                    continue
                threads.append({
                    "id": item[0] if len(item) > 0 else None,
                    "title": item[1] if len(item) > 1 else None,
                    "timestamp": item[2] if len(item) > 2 else None,
                    "has_canvas": bool(item[3]) if len(item) > 3 else False,
                    "raw": item,
                })
        logger.info("Listed %d AIM threads", len(threads))
        return threads

    def get_thread_context(self, thread_id: str) -> Dict[str, Any]:
        """Get the full context/history of a thread.

        Args:
            thread_id: Thread EI identifier.

        Returns:
            Dict with thread context and turn history.
        """
        body = [thread_id]
        raw = self._httpservice_post("GetThreadContext", body)
        return {"thread_id": thread_id, "raw": raw}

    def update_thread(
        self,
        thread_id: str,
        title: str,
    ) -> None:
        """Rename/update a thread title.

        Args:
            thread_id: Thread EI identifier.
            title: New display title.
        """
        body = [thread_id, title]
        self._httpservice_post("UpdateThread", body)
        logger.info("Updated thread %s title to %r", thread_id, title)

    def delete_threads(self, thread_ids: List[str]) -> None:
        """Permanently delete one or more threads.

        Args:
            thread_ids: List of thread EI identifiers to delete.
        """
        body = [thread_ids]
        self._httpservice_post("DeleteThreads", body)
        logger.info("Deleted %d threads: %s", len(thread_ids), thread_ids)

    def initiate_share(
        self,
        thread_id: str,
        share_level: int = 1,
    ) -> str:
        """Create a shareable link for a thread/canvas.

        Args:
            thread_id: Thread EI identifier.
            share_level: 1 = anyone with link (default), 0 = private.

        Returns:
            Shareable URL string.
        """
        body = [thread_id, share_level]
        raw = self._httpservice_post("InitiateShare", body)
        if isinstance(raw, list) and raw:
            return str(raw[0])
        return str(raw)

    def list_shared_threads(self) -> List[Dict[str, Any]]:
        """List threads that have been shared.

        Returns:
            List of shared thread dicts.
        """
        body = [None]
        raw = self._httpservice_post("ListSharedThreads", body)
        threads = []
        if isinstance(raw, list):
            for item in (raw[0] if raw and isinstance(raw[0], list) else raw):
                if isinstance(item, list):
                    threads.append({
                        "id": item[0] if len(item) > 0 else None,
                        "share_url": item[1] if len(item) > 1 else None,
                        "raw": item,
                    })
        return threads

    def delete_shared_threads(self, thread_ids: List[str]) -> None:
        """Remove threads from the shared list.

        Args:
            thread_ids: List of thread IDs to un-share.
        """
        body = [thread_ids]
        self._httpservice_post("DeleteSharedThreads", body)

    def search_threads(self, query: str) -> List[Dict[str, Any]]:
        """Search through saved threads by keyword.

        Args:
            query: Search keyword.

        Returns:
            List of matching thread dicts.
        """
        body = [query, None]
        raw = self._httpservice_post("SearchThreads", body)
        results = []
        if isinstance(raw, list):
            for item in (raw[0] if raw and isinstance(raw[0], list) else raw):
                if isinstance(item, list):
                    results.append({
                        "id": item[0] if len(item) > 0 else None,
                        "title": item[1] if len(item) > 1 else None,
                        "raw": item,
                    })
        return results

    # ──── Journey management ─────────────────────────────────────────────────

    def create_journey(self, title: str) -> Dict[str, Any]:
        """Create a Journey (a grouped project of related threads).

        Args:
            title: Journey display name.

        Returns:
            Dict with journey_id and metadata.
        """
        body = [title, None]
        raw = self._httpservice_post("CreateJourney", body)
        if isinstance(raw, list) and raw:
            return {"journey_id": raw[0], "title": title, "raw": raw}
        return {"raw": raw}

    def update_journeys(
        self,
        journey_id: str,
        title: Optional[str] = None,
        thread_ids: Optional[List[str]] = None,
    ) -> None:
        """Update a journey title or add threads to it.

        Args:
            journey_id: Journey identifier.
            title: New title (optional).
            thread_ids: Thread IDs to add (optional).
        """
        body = [journey_id, title, thread_ids or []]
        self._httpservice_post("UpdateJourneys", body)

    def delete_journeys(self, journey_ids: List[str]) -> None:
        """Delete one or more journeys.

        Args:
            journey_ids: List of journey IDs to delete.
        """
        body = [journey_ids]
        self._httpservice_post("DeleteJourneys", body)

    # ──── Compound helpers ────────────────────────────────────────────────────

    def create_canvas(
        self,
        prompt: str,
        canvas_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One-shot canvas creation: search → canvas followup → export.

        Args:
            prompt: Initial topic or question to research.
            canvas_instruction: Instruction for canvas creation. Defaults to
                a generic "Create a detailed canvas document summarizing this."

        Returns:
            Dict with ``thread_id``, ``query``, ``content`` (HTML), and
            ``session`` (AIMSession for further turns).
        """
        if canvas_instruction is None:
            canvas_instruction = (
                "Create a detailed, well-structured canvas document that "
                "comprehensively covers this topic."
            )

        logger.info("Creating AIM canvas for: %r", prompt[:80])

        # Step 1: Initial search
        session, _ = self.search(prompt)
        logger.debug("Search session: %s", session)

        # Step 2: Request canvas creation
        session, html = self.followup(session, canvas_instruction)
        has_canvas = self.is_canvas_response(html)
        logger.info("Canvas response received: has_canvas=%s", has_canvas)

        # Step 3: Export canvas
        result = self.export_thread(session)
        result["session"] = session
        result["has_canvas"] = has_canvas
        return result

    def canvas_to_text(self, canvas_html: str) -> str:
        """Convert exported canvas HTML to clean plain text.

        Args:
            canvas_html: HTML string from export_thread['content'].

        Returns:
            Cleaned plain text.
        """
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", canvas_html)
        # Decode HTML entities
        import html as _html
        text = _html.unescape(text)
        # Collapse whitespace
        text = re.sub(r"\s{2,}", "\n", text).strip()
        return text


# ──── Singleton ────────────────────────────────────────────────────────────────

_aim_client: Optional[GoogleAIMClient] = None


def get_aim_client(
    account_name: Optional[str] = None,
    cookies: Optional[Dict[str, str]] = None,
) -> GoogleAIMClient:
    """Get or create the shared GoogleAIMClient singleton.

    Args:
        account_name: Account pool key (used on first initialisation).
        cookies: Raw cookies dict (used on first initialisation).

    Returns:
        Shared GoogleAIMClient instance.
    """
    global _aim_client
    if _aim_client is None:
        _aim_client = GoogleAIMClient(cookies=cookies, account_name=account_name)
    return _aim_client
