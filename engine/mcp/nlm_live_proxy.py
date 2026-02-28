"""
NLM Live Proxy — Full batchexecute API bridge for NotebookLM.

Architecture
~~~~~~~~~~~~
This proxy provides complete read AND write access to NotebookLM's private
batchexecute API, reverse-engineered from multi-session HAR analysis (11 HARs
across 5 NLM sessions). It exposes a REST API at :8800 for CosySim agents.

Auth is handled via Google session cookies extracted from either:
  1. A manually captured HAR file (DevTools → Save all as HAR)
  2. Automatically via Chrome DevTools Protocol (CDP) — preferred

Complete Reverse-Engineered RPC Catalogue
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
RPC IDs are **STABLE within a build label** but MAY change when Google
deploys a new frontend (BL changes approx. weekly). The BL is tracked in
data/nlm_meta.json and auto-extracted from imported HARs.

Read RPCs (stable across all observed builds):
| RPC ID  | Function                   | Payload signature                             |
|---------|----------------------------|-----------------------------------------------|
| ZwVcOc  | Session init               | [null,[1,...,[1]]]                            |
| wXbhsf  | List sources (full)        | [null,1,null,[2]]                             |
| ub2Bae  | List notebooks             | [[2]]                                         |
| sqTeoe  | List all notebooks         | [[2,...],null,1]                              |
| rLM1Ne  | Load notebook by ID        | [nb_id,null,[2],null,0]                       |
| e3bVqc  | Notebook extended info     | [null,null,nb_id]                             |
| hPTbtc  | List sources (paginated)   | [[],null,nb_id,page_size]                     |
| khqZz   | Sources for sub-notebook   | [[],null,null,nb_id,page_size]                |
| JFMDGd  | Sources list (condensed)   | [nb_id,[2]]                                   |
| VfAZjd  | AI overview/summary        | [nb_id,[2]]                                   |
| gArtLc  | List notes/artifacts       | [[2,...],nb_id,"NOT...SUGGESTED"]             |
| cFji9   | Conversation history       | [nb_id,null,cursor_ts,[2]]                    |
| ozz5Z   | User quota / account info  | [[[[null,"1",count],...,1]]]                  |
| tr032e  | Read source content        | [[[[source_id]]]]                             |

Write RPCs:
| RPC ID  | Function                   | Notes                                         |
|---------|----------------------------|-----------------------------------------------|
| s0tc2d  | Chat message (CURRENT)     | [nb_id,[[null*7,[[2,"question"],[resp_len]]]]]|
| CYK0Xb  | Annotate text w/ citations | [nb_id,"context_text"] → [[id, cited_text]]   |
| ciyUvf  | Generate deep-research doc | [WRITE_CONFIG,nb_id,[[src_id],...]]           |
| R7cb6c  | Save note/brief            | [WRITE_CONFIG,nb_id,[null,null,type,srcs]]    |

RPC Change History:
  - CYK0Xb was the ORIGINAL chat-ask RPC (still valid for citation annotation)
  - s0tc2d is the CURRENT chat-ask RPC as of build 20260226.08_p0+
  - Both can be used; s0tc2d supports response length + configure-chat

Document/Note Types for R7cb6c and save_note:
  2 = Standard research brief
  9 = Notes (free-form)
  (Other types: study guide, FAQ, timeline — test with /rpc/R7cb6c)

Configure Chat (s0tc2d position 0):
  The inner message array null[0] is the "configure chat" goal/role string.
  Injecting a role here affects how NLM responds to all messages in the session.
  Example: "Act as a PhD researcher. Provide thorough analysis with citations."

Response Length for s0tc2d (position [resp_len]):
  4 = Default length (confirmed from HAR)
  1 = Longer (hypothesis — test required)
  2 = Shorter (hypothesis — test required)

Multi-question batching:
  Up to 5 CYK0Xb or s0tc2d calls can be packed into a single batchexecute
  f.req array, reducing total API round-trips by 5×.

Usage::

    from engine.mcp.nlm_live_proxy import create_nlm_proxy_app, get_nlm_proxy_app
    app = create_nlm_proxy_app()
    app.run(port=8800)

    # Standalone:
    python -m engine.mcp.nlm_live_proxy
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

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_COOKIES_FILE = _PROJECT_ROOT / "data" / "nlm_cookies.json"
_META_FILE = _PROJECT_ROOT / "data" / "nlm_meta.json"
_NLM_HOST = "notebooklm.google.com"
_BATCH_URL = f"https://{_NLM_HOST}/_/LabsTailwindUi/data/batchexecute"
_REQUEST_TIMEOUT = 60
_COOKIES_LOCK = threading.Lock()

# Known-good build label — updated automatically on HAR import
# Format: boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
# Changes roughly weekly when Google deploys a new frontend build.
_DEFAULT_BL = "boq_labs-tailwind-frontend_20260226.08_p0"
_DEFAULT_BL_DATE = "2026-02-26"  # for staleness calculation

# ── RPC ID Registry ──────────────────────────────────────────────────────
# Stable within a build, may change across builds. Monitor /meta for age.
RPC_SESSION_INIT = "ZwVcOc"
RPC_LIST_SOURCES = "wXbhsf"
RPC_LIST_NOTEBOOKS = "ub2Bae"
RPC_LIST_NOTEBOOKS_ALL = "sqTeoe"
RPC_LOAD_NOTEBOOK = "rLM1Ne"
RPC_NOTEBOOK_INFO = "e3bVqc"
RPC_LIST_SOURCES_PAGED = "hPTbtc"
RPC_LIST_SOURCES_SUB = "khqZz"
RPC_SOURCES_CONDENSED = "JFMDGd"
RPC_AI_SUMMARY = "VfAZjd"
RPC_LIST_ARTIFACTS = "gArtLc"
RPC_CONVERSATION_HISTORY = "cFji9"
RPC_USER_QUOTA = "ozz5Z"
RPC_READ_SOURCE = "tr032e"       # Read full source text content
RPC_CHAT_MESSAGE = "s0tc2d"      # Current chat/ask RPC (replaces CYK0Xb)
RPC_ANNOTATE_TEXT = "CYK0Xb"    # Annotate text with notebook citations
RPC_GENERATE_DOC = "ciyUvf"     # Generate deep-research document
RPC_SAVE_NOTE = "R7cb6c"        # Save note/brief to notebook

# ── Response Length Constants ────────────────────────────────────────────
# Used as the second element in s0tc2d message array [[2,"question"],[RESP_LEN]]
RESP_LEN_DEFAULT = 4   # Confirmed from HAR analysis
RESP_LEN_LONGER  = 1   # Hypothesis — test via /rpc/s0tc2d
RESP_LEN_SHORTER = 2   # Hypothesis — test via /rpc/s0tc2d

# ── Document/Note Types ──────────────────────────────────────────────────
# Used in R7cb6c save_note calls
DOC_TYPE_BRIEF   = 2   # Research brief (confirmed)
DOC_TYPE_NOTE    = 9   # Notes (confirmed)
# Study guide, FAQ, timeline may be 3-8 — use /rpc/R7cb6c to test

# Document/note config object used for write RPCs (from HAR analysis)
_WRITE_CONFIG = [2, None, None,
                 [1, None, None, None, None, None, None, None, None, None, [1]],
                 [[2, 1]]]


# ── Meta (bl, f.sid) management ─────────────────────────────────────────

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


# ── Cookie management ────────────────────────────────────────────────────

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
        Tuple of (cookies_dict, meta_dict) where meta has keys 'bl', 'f_sid'.
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
    """Compute the SAPISIDHASH for the Authorization header."""
    import hashlib
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID", "")
    if not sapisid:
        return ""
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} https://{_NLM_HOST}"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


# ── batchexecute caller ──────────────────────────────────────────────────

def _build_headers(cookies: Dict[str, str]) -> Dict[str, str]:
    """Build the HTTP headers required for NLM batchexecute requests."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/145.0.0.0 Safari/537.36"),
        "Referer": f"https://{_NLM_HOST}/",
        "Origin": f"https://{_NLM_HOST}",
        "X-Same-Domain": "1",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    if cookies:
        headers["Cookie"] = _cookies_header(cookies)
        sapisid_hash = _sapisid_hash(cookies)
        if sapisid_hash:
            headers["Authorization"] = sapisid_hash
    return headers


def _batchexecute(
    rpc_id: str,
    args_json: str,
    cookies: Dict[str, str],
    notebook_id: str = "",
) -> Tuple[Optional[str], Any]:
    """Make a single batchexecute RPC call to NotebookLM.

    Args:
        rpc_id:      The RPC function ID (e.g. "VfAZjd", "CYK0Xb").
        args_json:   JSON-stringified argument array.
        cookies:     Google auth cookies dict.
        notebook_id: Optional notebook ID for the source-path URL param.

    Returns:
        Tuple of (rpc_id_returned, parsed_inner_data) or (None, None).
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
) -> List[Tuple[Optional[str], Any]]:
    """Make multiple batchexecute RPC calls in a single HTTP request.

    This is the core of multi-question batching — up to 5 questions
    can be sent simultaneously by packing multiple CYK0Xb calls.

    Args:
        calls:       List of (rpc_id, args_json) tuples.
        cookies:     Google auth cookies dict.
        notebook_id: Optional notebook context.

    Returns:
        List of (rpc_id_returned, parsed_inner_data) tuples, one per call.
    """
    if not calls:
        return []

    bl = _get_bl()
    fsid = _get_fsid()
    req_id = str(int(time.time()) % 100000 * 100)

    # Build rpcids param — semicolon-separated when batching
    rpc_ids_param = ";".join(rpc_id for rpc_id, _ in calls)

    params: Dict[str, str] = {
        "rpcids": rpc_ids_param,
        "source-path": f"/notebook/{notebook_id}" if notebook_id else "/",
        "bl": bl,
        "f.sid": fsid,
        "hl": "en",
        "_reqid": req_id,
        "rt": "c",
    }
    url = f"{_BATCH_URL}?" + urllib.parse.urlencode(params)

    # Pack all calls into a single f.req array
    f_req_inner = [[rpc_id, args_json, None, "generic"] for rpc_id, args_json in calls]
    body = urllib.parse.urlencode({
        "f.req": json.dumps(f_req_inner)
    }).encode()

    headers = _build_headers(cookies)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
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

    return _parse_batchexecute_multi(raw)


def _parse_batchexecute_multi(raw: str) -> List[Tuple[Optional[str], Any]]:
    """Decode ALL batchexecute wrb.fr blocks from a multi-RPC response.

    A batched response contains multiple ``wrb.fr`` blocks, one per call.

    Returns:
        List of (rpc_id, parsed_data) tuples in response order.
    """
    results: List[Tuple[Optional[str], Any]] = []
    body = raw.lstrip(")]}'").lstrip("\n")
    for line in body.split("\n"):
        line = line.strip()
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


# ── Content extraction helpers ───────────────────────────────────────────

def _extract_strings(obj: Any, min_len: int = 80) -> List[str]:
    """Recursively extract all meaningful text strings from nested data."""
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
    seen: set = set()
    return [t for t in texts if t[:key_len] not in seen and not seen.add(t[:key_len])]  # type: ignore[func-returns-value]


def _extract_sources(data: Any) -> Tuple[str, List[Dict]]:
    """Parse wXbhsf response → (notebook_name, sources_list)."""
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


# ── Write operation helpers ───────────────────────────────────────────────

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
    _, data = _batchexecute(RPC_ANNOTATE_TEXT, args, cookies, notebook_id)
    return _parse_ask_response(data)


def chat_message(
    notebook_id: str,
    question: str,
    cookies: Dict[str, str],
    role: str = "",
    response_length: int = RESP_LEN_DEFAULT,
) -> Dict[str, Any]:
    """Send a chat message using s0tc2d (current NLM chat RPC).

    This is the proper chat interface. Unlike CYK0Xb (which annotates text),
    s0tc2d triggers NLM's conversational Gemini model to generate an answer.

    Configure Chat support: pass a ``role`` string to set the chat persona,
    e.g. "Act as a PhD researcher providing citations" or
    "You are a patient teacher explaining concepts step by step."
    The role is injected at position 0 of the message structure.

    Response length: use RESP_LEN_DEFAULT (4), RESP_LEN_LONGER (1, hypothesis),
    or RESP_LEN_SHORTER (2, hypothesis).

    Args:
        notebook_id:     UUID of the target notebook.
        question:        The question to ask.
        cookies:         Google auth cookies.
        role:            Optional configure-chat role/goal string.
        response_length: Response length hint (default 4).

    Returns:
        Dict with keys: answer_id, answer, sources, notebook_name, raw.
    """
    # Build message structure: [[role_or_null, null*6, [[2,question],[resp_len]]]]
    inner_msg = [[2, question], [response_length]]
    chat_config = [role if role else None,
                   None, None, None, None, None, None,
                   inner_msg]
    args = json.dumps([notebook_id, [chat_config]])
    _, data = _batchexecute(RPC_CHAT_MESSAGE, args, cookies, notebook_id)
    return _parse_chat_response(data, question)


def chat_messages_batch(
    notebook_id: str,
    questions: List[str],
    cookies: Dict[str, str],
    role: str = "",
    response_length: int = RESP_LEN_DEFAULT,
    max_batch: int = 5,
) -> List[Dict[str, Any]]:
    """Send multiple chat messages in parallel batches using s0tc2d.

    Args:
        notebook_id:     UUID of the target notebook.
        questions:       List of question strings.
        cookies:         Google auth cookies.
        role:            Optional configure-chat role/goal for all messages.
        response_length: Response length hint (default 4).
        max_batch:       Max questions per HTTP request (default 5).

    Returns:
        List of chat response dicts in question order.
    """
    results: List[Dict[str, Any]] = []
    for i in range(0, len(questions), max_batch):
        batch = questions[i:i + max_batch]
        calls = []
        for q in batch:
            inner_msg = [[2, q], [response_length]]
            chat_config = [role if role else None,
                           None, None, None, None, None, None,
                           inner_msg]
            calls.append((RPC_CHAT_MESSAGE, json.dumps([notebook_id, [chat_config]])))
        raw_results = _batchexecute_multi(calls, cookies, notebook_id)
        for j, (_, data) in enumerate(raw_results):
            results.append(_parse_chat_response(data, batch[j] if j < len(batch) else ""))
    return results


def _parse_chat_response(data: Any, question: str = "") -> Dict[str, Any]:
    """Parse an s0tc2d response.

    s0tc2d returns: [notebook_title, null, notebook_id, emoji, null,
                     [status_flags...], null, [[2,"question"],[resp_len]]]

    The response echoes the question metadata but does NOT contain the answer
    inline — the answer is generated asynchronously. For synchronous answers,
    use CYK0Xb (ask_question) or poll the conversation history (cFji9).

    Args:
        data: Parsed inner data from batchexecute response.
        question: Original question for context.

    Returns:
        Dict with: notebook_title, notebook_id, question, status, queued.
    """
    if data is None:
        return {"queued": False, "question": question, "error": "no_data",
                "answer": "", "answer_id": None, "sources": []}
    if isinstance(data, dict) and "error" in data:
        return {"queued": False, "question": question, "answer": "",
                "answer_id": None, "sources": [], **data}
    try:
        if isinstance(data, list) and len(data) >= 3:
            notebook_title = data[0] if isinstance(data[0], str) else ""
            notebook_id = data[2] if isinstance(data[2], str) else ""
            return {
                "queued": True,
                "notebook_title": notebook_title,
                "notebook_id": notebook_id,
                "question": question,
                "answer": "",        # Answer arrives asynchronously
                "answer_id": None,
                "sources": [],
                "note": "s0tc2d queues the response. Poll /conversations for answer.",
            }
    except (IndexError, TypeError) as exc:
        logger.warning("parse chat response: %s | data=%s", exc, str(data)[:200])
    return {"queued": False, "question": question, "answer": "",
            "answer_id": None, "sources": [], "raw": str(data)[:500]}


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
            (RPC_ANNOTATE_TEXT, json.dumps([notebook_id, q]))
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
    """Parse a tr032e response → source content."""
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
    _, data = _batchexecute("ciyUvf", args, cookies, notebook_id)
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


def save_note(
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
    _, data = _batchexecute("R7cb6c", args, cookies, notebook_id)
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


# ── Flask app ────────────────────────────────────────────────────────────

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

    # ── Health ──────────────────────────────────────────────────────────

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
            "rpc_catalog_version": "v2.1",
            "known_rpcs": 18,
        }), 200 if cookies else 503

    # ── Cookie management ───────────────────────────────────────────────

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

        # Update meta (bl, f.sid) if found
        existing_meta = _load_meta()
        if new_meta.get("bl"):
            existing_meta["bl"] = new_meta["bl"]
        if new_meta.get("f_sid"):
            existing_meta["f_sid"] = new_meta["f_sid"]
        _save_meta(existing_meta)

        return jsonify({
            "imported_cookies": len(new_cookies),
            "total_cookies": len(merged),
            "bl": existing_meta.get("bl", _DEFAULT_BL),
            "f_sid": existing_meta.get("f_sid", "-1"),
            "status": "ok",
            "note": "No cookies found in HAR (Chrome may have redacted them). "
                    "Use POST /cookies/capture for automatic Chrome CDP extraction."
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

    # ── Notebook list ───────────────────────────────────────────────────

    @app.route("/notebooks", methods=["GET"])
    def list_notebooks():
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        _, data = _batchexecute("ub2Bae", "[[2]]", cookies)
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

    # ── Notebook data ───────────────────────────────────────────────────

    @app.route("/notebooks/<notebook_id>/sources", methods=["GET"])
    def get_sources(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([None, 1, None, [2]])
        _, data = _batchexecute("wXbhsf", args, cookies, notebook_id)
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
        _, data = _batchexecute("VfAZjd", args, cookies, notebook_id)
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
        _, data = _batchexecute("gArtLc", args, cookies, notebook_id)
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
        _, data = _batchexecute("cFji9", args, cookies, notebook_id)
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
        _, data = _batchexecute("e3bVqc", args, cookies, notebook_id)
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
        _, data = _batchexecute("VfAZjd", json.dumps([notebook_id, [2]]),
                                cookies, notebook_id)
        result["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

        # Sources
        _, data = _batchexecute("wXbhsf", json.dumps([None, 1, None, [2]]),
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
        _, data = _batchexecute("cFji9", json.dumps([notebook_id, None, None, [2]]),
                                cookies, notebook_id)
        convos = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["conversations"] = [c for c in convos if len(c) > 100]

        result["stats"] = {
            "sources": len(result["sources"]),
            "notes":   len(result["notes"]),
            "conversations": len(result["conversations"]),
        }
        return jsonify(result)

    # ── Write operations ────────────────────────────────────────────────

    @app.route("/notebooks/<notebook_id>/ask", methods=["POST"])
    def ask_single(notebook_id: str):
        """Ask a single question to a NotebookLM notebook.

        Two modes via ``mode`` parameter:
        - "annotate" (default): CYK0Xb — synchronous, returns cited answer
        - "chat": s0tc2d — asynchronous, queues response, supports role config

        Body (JSON):
          {
            "question": "What is the main argument?",
            "mode": "annotate",
            "role": "",
            "response_length": 4
          }
        Returns: {answer_id, answer, sources} or {queued, notebook_title}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "missing question"}), 400
        mode = body.get("mode", "annotate")
        if mode == "chat":
            role = body.get("role", "")
            resp_len = body.get("response_length", RESP_LEN_DEFAULT)
            result = chat_message(notebook_id, question, cookies, role, resp_len)
        else:
            result = ask_question(notebook_id, question, cookies)
        if result.get("error") and not result.get("queued"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/ask_batch", methods=["POST"])
    def ask_batch(notebook_id: str):
        """Ask multiple questions in parallel (up to max_batch at once).

        Two modes: "annotate" (CYK0Xb, default) or "chat" (s0tc2d).

        Body (JSON):
          {
            "questions": ["Q1?", "Q2?", "Q3?"],
            "mode": "annotate",
            "role": "",
            "response_length": 4,
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
        mode = body.get("mode", "annotate")
        if mode == "chat":
            role = body.get("role", "")
            resp_len = body.get("response_length", RESP_LEN_DEFAULT)
            results = chat_messages_batch(notebook_id, questions, cookies,
                                          role, resp_len, max_batch)
        else:
            results = ask_questions_batch(notebook_id, questions, cookies, max_batch)
        return jsonify({
            "answers": results,
            "count": len(results),
            "questions": questions,
            "mode": mode,
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
    def save_note_route(notebook_id: str):
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
        result = save_note(notebook_id, source_ids, cookies, note_type)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/chat", methods=["POST"])
    def chat_single(notebook_id: str):
        """Send a chat message using the current s0tc2d RPC.

        Supports configure-chat role injection and response length control.
        Note: s0tc2d queues the response asynchronously. The answer arrives
        via the conversation history — poll GET /conversations after calling.

        Body (JSON):
          {
            "question": "What is the main argument?",
            "role": "Act as a PhD researcher providing thorough analysis",
            "response_length": 4
          }
        Returns: {queued, notebook_title, notebook_id, question}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "missing question"}), 400
        role = body.get("role", "")
        resp_len = body.get("response_length", RESP_LEN_DEFAULT)
        result = chat_message(notebook_id, question, cookies, role, resp_len)
        if result.get("error") and not result.get("queued"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/chat_batch", methods=["POST"])
    def chat_batch(notebook_id: str):
        """Send multiple chat messages using s0tc2d in parallel batches.

        Body (JSON):
          {
            "questions": ["Q1?", "Q2?", ...],
            "role": "Act as a researcher",
            "response_length": 4,
            "max_batch": 5
          }
        Returns: {queued_count, questions}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        questions = body.get("questions", [])
        if not questions:
            return jsonify({"error": "missing questions array"}), 400
        role = body.get("role", "")
        resp_len = body.get("response_length", RESP_LEN_DEFAULT)
        max_batch = body.get("max_batch", 5)
        results = chat_messages_batch(notebook_id, questions, cookies,
                                      role, resp_len, max_batch)
        return jsonify({
            "results": results,
            "queued_count": sum(1 for r in results if r.get("queued")),
            "count": len(results),
            "questions": questions,
        })

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

    # ── CDP Cookie Capture ──────────────────────────────────────────────

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

    return app


# ── Singleton ────────────────────────────────────────────────────────────

_proxy_app: Optional[Flask] = None


def get_nlm_proxy_app() -> Flask:
    """Return the shared NLM proxy Flask application."""
    global _proxy_app
    if _proxy_app is None:
        _proxy_app = create_nlm_proxy_app()
    return _proxy_app


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
