"""Direct NotebookLM HTTP client — reverse-engineered from HAR analysis.

Bypasses browser automation entirely; sends queries directly to the
LabsTailwind orchestration endpoint using browser session cookies.

Endpoint confirmed from notebooklm.google.com-jackpot-nihilistcod.har.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_NLM_BASE = "https://notebooklm.google.com"
_NLM_ENDPOINT = (
    f"{_NLM_BASE}/_/LabsTailwindUi/data/"
    "google.internal.labs.tailwind.orchestration.v1."
    "LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
)
_NLM_ORIGIN = "https://notebooklm.google.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


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
        self._reqid = 1000000

    # ──── Page params ─────────────────────────────────────────────────────────

    def _get_page_params(self) -> Tuple[str, str]:
        """Fetch build label (bl) and session fingerprint (f.sid) from NLM homepage.

        Returns:
            Tuple of (bl, f_sid) strings.

        Raises:
            ValueError: If parameters cannot be extracted.
        """
        if self._bl and self._f_sid:
            return self._bl, self._f_sid

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

        # Extract bl from cfb_data or inline script
        bl: Optional[str] = None
        f_sid: Optional[str] = None

        # Pattern: "bl":"boq_labs-tailwind-frontend_20260301.03_p0"
        bl_match = re.search(r'"bl"\s*:\s*"([^"]+)"', html)
        if bl_match:
            bl = bl_match.group(1)

        # Also try alternate pattern: cfb_data":{"bl":"..."}
        if not bl:
            cfb_match = re.search(r'cfb_data["\s:]+\{["\s]*bl["\s:]+(["\'])([^"\']+)\1', html)
            if cfb_match:
                bl = cfb_match.group(2)

        # Extract f.sid from WIZ_global_data: "FdrFJe":"...", or similar
        fsid_match = re.search(r'"FdrFJe"\s*:\s*"([^"]+)"', html)
        if fsid_match:
            f_sid = fsid_match.group(1)

        # Fallback: look for SNlM0e (older pattern used as session token)
        if not f_sid:
            snl_match = re.search(r'"SNlM0e"\s*:\s*"([^"]+)"', html)
            if snl_match:
                f_sid = snl_match.group(1)

        if not bl:
            # Use a reasonable default based on observed values
            bl = "boq_labs-tailwind-frontend_20260301.03_p0"
            logger.warning("Could not extract bl from NLM page, using default: %s", bl)

        if not f_sid:
            f_sid = str(int(time.time() * 1000))
            logger.warning("Could not extract f.sid from NLM page, using timestamp: %s", f_sid)

        self._bl = bl
        self._f_sid = f_sid
        logger.debug("NLM page params: bl=%s f.sid=%s", bl, f_sid)
        return bl, f_sid

    # ──── Auth headers ────────────────────────────────────────────────────────

    def _get_headers(self) -> Dict[str, str]:
        """Build NLM request headers.

        Returns:
            Headers dict including Cookie, Origin, and x-same-domain.
        """
        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Cookie": cookie_header,
            "Origin": _NLM_ORIGIN,
            "Referer": f"{_NLM_BASE}/",
            "User-Agent": _USER_AGENT,
            "X-Same-Domain": "1",
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

        headers = self._get_headers()
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

        headers = self._get_headers()
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
