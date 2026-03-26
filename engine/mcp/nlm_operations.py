"""NLM RPC operations — all batchexecute and gRPC-Web operation functions.

Version: v1.57.2 [2026-03-26]

Change Log:
    v1.57.2 [2026-03-26] — Convert all RPC_* import-time constants to
                            get_rpcid() call-time lookups for live rotation
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine.config import get_config

# ── Path constants ────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"

logger = logging.getLogger(__name__)

# ── Sibling imports ───────────────────────────────────────────────────────
# v1.57.2 [2026-03-26] — Switched from import-time RPC_* constants to
# call-time get_rpcid() lookups.  This means rpcid rotations picked up by
# RpcidUpdater take effect immediately without process restart.
#
# OLD imports (kept as comments for reference / backward compat):
#   RPC_CREATE_NOTE, RPC_RENAME_NOTEBOOK, RPC_ADD_SOURCE,
#   RPC_SOURCE_STATUS, RPC_REGISTER_FILES, RPC_SAVE_NOTE,
#   RPC_GET_SOURCE_SUMMARY, RPC_GET_AUDIO_OPTIONS, RPC_SYNC_NOTES,
#   RPC_DELETE_SOURCE, RPC_START_DEEP_RESEARCH, RPC_ADD_RESEARCH_SOURCE,
#   RPC_READ_SOURCE,
from engine.mcp.nlm_rpc_constants import (
    _rate_limiter, _get_rate_limit,
    _DEFAULT_BL, _GRPC_CHAT_URL, _SOURCE_CONFIG,
    get_rpcid,
)
from engine.mcp.nlm_auth import (
    _cookies_header, _load_meta, _NLM_HOST,
)
from engine.mcp.nlm_transport import (
    _batchexecute, _batchexecute_multi, _extract_strings,
)


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
    _, data = _batchexecute(get_rpcid("create_note"), args, cookies, notebook_id)
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
    _, data = _batchexecute(get_rpcid("rename_notebook"), args, cookies, notebook_id)
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
    _, data = _batchexecute(get_rpcid("add_source"), args, cookies, notebook_id)
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

    _rpc_id, data = _batchexecute(get_rpcid("add_source"), args, cookies, notebook_id)
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
    _rpc_id, data = _batchexecute(get_rpcid("source_status"), args, cookies, notebook_id)
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

    _rpc_id, data = _batchexecute(get_rpcid("register_files"), args, cookies, notebook_id)
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
    _rpc_id, data = _batchexecute(get_rpcid("create_note"), args, cookies, notebook_id)
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
    _rpc_id, data = _batchexecute(get_rpcid("save_note"), args, cookies, notebook_id)
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
    _rpc_id, data = _batchexecute(get_rpcid("get_source_summary"), args, cookies)
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
        [[2, None, None, [1, None, None, None, None, None, None, None, None, None, [1]], [[2, 1, 3]]], None, 1],
        separators=(",", ":"),
    )
    _rpc_id, data = _batchexecute(get_rpcid("get_audio_options"), args, cookies, notebook_id)
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
    _rpc_id, data = _batchexecute(get_rpcid("sync_notes"), args, cookies, notebook_id)
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
            (get_rpcid("create_note"), json.dumps([notebook_id, q]))
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
    _, data = _batchexecute(get_rpcid("delete_source"), args, cookies)
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
    _, data = _batchexecute(get_rpcid("start_deep_research"), args, cookies, notebook_id)
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
    _, data = _batchexecute(get_rpcid("add_research_source"), args, cookies, notebook_id)
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
    _, data = _batchexecute(get_rpcid("read_source"), args, cookies)
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
