"""Direct NotebookLM HTTP client — reverse-engineered from HAR analysis.

Bypasses browser automation entirely. Two endpoint families:

1. GenerateFreeFormStreamed — multi-turn notebook chat (ask / ask_streaming)
2. batchexecute — all studio operations: create_note, generate_audio,
   add_source, generate_flashcards, generate_mind_map, export_to_sheets, etc.

Gemini 3.0 is fully multimodal. Every source can be: text, URL, YouTube link,
image (jpg/png/webp/gif), audio (mp3/wav/ogg/m4a), video (mp4/mov/webm), or PDF.
Feed ComfyUI output, NLM-generated audio, screenshots, charts — anything — back
as sources for the next call. Recursive self-improvement is the architecture.

Endpoints confirmed from notebooklm.google.com-complete-new.har (2026-06).
rpcid registry: data/nlm_rpc_registry.json v4.0
"""
from __future__ import annotations

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

_NLM_ORIGIN = "https://notebooklm.google.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

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

    # ──── Generic batchexecute RPC caller ─────────────────────────────────────

    def _rpc_call(
        self,
        rpc_id: str,
        payload: Any,
        timeout: int = 120,
    ) -> Any:
        """Call any NLM studio operation via the batchexecute endpoint.

        This is the backbone for all non-chat operations: create_note,
        generate_audio, add_source, export_to_sheets, etc.

        Args:
            rpc_id: NLM rpcid string (e.g. ``'CYK0Xb'``, ``'QA9ei'``).
            payload: Python object — will be JSON-serialised as the inner payload.
            timeout: HTTP request timeout in seconds.

        Returns:
            Parsed inner response data (list/dict), or ``None`` if unparseable.
        """
        bl, f_sid = self._get_page_params()
        self._reqid += 100000

        url = (
            f"{_NLM_RPC_ENDPOINT}"
            f"?rpcids={rpc_id}"
            f"&source-path=/"
            f"&f.sid={urllib.parse.quote(str(f_sid))}"
            f"&bl={urllib.parse.quote(bl)}"
            f"&hl=en-US"
            f"&_reqid={self._reqid}"
            f"&rt=c"
        )

        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        f_req_inner = json.dumps([[rpc_id, payload_json, "generic"]])
        body = "f.req=" + urllib.parse.quote(f_req_inner)

        headers = self._get_headers()
        resp = self._session.post(url, headers=headers, data=body, timeout=timeout)
        resp.raise_for_status()

        return self._parse_rpc_response(resp.text, rpc_id)

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
        # HAR-confirmed payload for URL source: [nb_id, null, [url]]
        payload = [notebook_id, None, [url]]
        result = self._rpc_call("izAoDd", payload)
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
        # HAR-confirmed payload: [[title, content], null, null, 3]
        payload = [[title, content], None, None, 3]
        result = self._rpc_call("izAoDd", payload)
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
        payload = [[[path.name]], notebook_id, [2], [1, None, None, [1]]]
        result = self._rpc_call("o4cbdc", payload, timeout=30)
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
        self._rpc_call("LBwxtb", payload)
        logger.debug("Deleted source %s from notebook %s", source_id, notebook_id)

    def get_sources(self, notebook_id: str) -> List[str]:
        """Return all source IDs for a notebook.

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of source ID strings.
        """
        payload = [[], None, notebook_id, 20]
        result = self._rpc_call("hPTbtc", payload)
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
            result = self._rpc_call("rLM1Ne", payload, timeout=30)
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
        """Generate a custom report/document via Gemini 3.0 (CYK0Xb).

        The prompt is your creative brief — up to ~10,000 words.
        Gemini reads the ENTIRE prompt plus every source in the notebook.
        Use this for: analysis reports, code generation, data extraction,
        Q&A JSON generation, documentation, any structured output.

        Args:
            notebook_id: NLM notebook UUID.
            prompt: Full prompt / creative brief (up to ~10k words).

        Returns:
            Dict with ``id``, ``title``, ``content`` (markdown).
        """
        payload = [notebook_id, prompt]
        result = self._rpc_call("CYK0Xb", payload, timeout=180)
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
        result = self._rpc_call("QA9ei", payload, timeout=60)
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
            result = self._rpc_call("gArtLc", payload, timeout=30)
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
        result = self._rpc_call("ciyUvf", payload, timeout=120)
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
        result = self._rpc_call("R7cb6c", payload, timeout=120)
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
        result = self._rpc_call("yyryJe", payload, timeout=120)
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
        result = self._rpc_call("LBwxtb", payload, timeout=180)
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
        result = self._rpc_call("tr032e", payload, timeout=60)
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
        result = self._rpc_call("Krh3pd", payload, timeout=60)
        if isinstance(result, list) and result:
            return str(result[0])
        raise RuntimeError(f"export_to_sheets returned no URL: {result}")

    # ──── Notebook management ──────────────────────────────────────────────────

    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all notebooks in this account (ub2Bae).

        Returns:
            List of notebook dicts with id, name, and metadata.
        """
        import base64
        payload = [[2]]
        result = self._rpc_call("ub2Bae", payload, timeout=30)
        notebooks: List[Dict[str, Any]] = []
        if not isinstance(result, list):
            return notebooks
        for item in result:
            try:
                if isinstance(item, str):
                    decoded = base64.b64decode(item).decode("utf-8")
                    notebooks.append(json.loads(decoded))
                elif isinstance(item, (list, dict)):
                    notebooks.append(item)  # type: ignore[arg-type]
            except Exception:
                notebooks.append({"raw": item})
        return notebooks

    def get_artifacts(self, notebook_id: str) -> List[Dict[str, Any]]:
        """List all artifacts in a notebook (gArtLc).

        Args:
            notebook_id: NLM notebook UUID.

        Returns:
            List of artifact dicts with id, status, type, download_url.
        """
        filter_str = 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'
        payload = [None, notebook_id, filter_str]
        result = self._rpc_call("gArtLc", payload, timeout=30)
        return result if isinstance(result, list) else []

    def update_notebook_title(self, notebook_id: str, new_title: str) -> None:
        """Rename a notebook (s0tc2d).

        Args:
            notebook_id: NLM notebook UUID.
            new_title: New display name.
        """
        payload = [notebook_id, [[None, None, None, [None, new_title]]]]
        self._rpc_call("s0tc2d", payload, timeout=30)
        logger.debug("Renamed notebook %s → '%s'", notebook_id, new_title)

    def create_notebook(self, title: str) -> str:
        """Create a new empty NotebookLM notebook (VqhFhd).

        Args:
            title: Display name for the new notebook.

        Returns:
            New notebook ID string.
        """
        payload = [title, None, None]
        result = self._rpc_call("VqhFhd", payload, timeout=30)
        if result and isinstance(result, list) and result[0]:
            return str(result[0])
        raise RuntimeError(f"create_notebook failed for title='{title}': {result}")

    def delete_notebook(self, notebook_id: str) -> None:
        """Permanently delete a notebook and all its sources (kVoZqc).

        Args:
            notebook_id: NLM notebook UUID to delete.
        """
        payload = [[notebook_id]]
        self._rpc_call("kVoZqc", payload, timeout=30)
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
        result = self._rpc_call("GzgSEd", payload, timeout=30)
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
        self._rpc_call("GfmCOc", payload, timeout=30)
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
        result = self._rpc_call("xqEXEf", payload, timeout=180)
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
        result = self._rpc_call("dI5Y8", payload, timeout=30)
        if isinstance(result, list) and result:
            return str(result[0])
        if isinstance(result, str):
            return result
        raise RuntimeError(f"share_notebook returned no URL for {notebook_id}: {result}")

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
