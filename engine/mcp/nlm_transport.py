"""NLM batchexecute transport layer — headers, HTTP calls, and response parsing.

Version: v1.57.2 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-26] — Auto-recovery on rpcid rotation via fallback registry
    v1.53.0 [2026-03-21] — Baseline transport layer
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.nlm_rpc_constants import _rate_limiter, _get_rate_limit
from engine.mcp.nlm_auth import (
    _cookies_header, _get_bl, _get_fsid, _load_meta, refresh_session_tokens,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-26] — Track rpcids known to be stale after rotation
_STALE_RPCIDS: set = set()

_NLM_HOST = "notebooklm.google.com"
_BATCH_URL = f"https://{_NLM_HOST}/_/LabsTailwindUi/data/batchexecute"
_REQUEST_TIMEOUT = 60


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

# ── Rotation Recovery Helper ──────────────────────────────────────────────

# v1.57.2 [2026-03-26] — Rotation detection with fallback rpcid lookup
# CONNECTS: NLMRpcRegistry (config/nlm_rpcids.yaml)
# CALLED BY: _batchexecute_multi response parsing
def _get_fallback_rpcid(rpc_id: str) -> Optional[str]:
    """Get a fallback rpcid for a stale one via the registry.

    Performs a reverse lookup from rpcid to operation name, then retrieves
    the fallback rpcid for that operation. This enables auto-recovery when
    Google rotates rpcids during frontend deployments.

    Args:
        rpc_id: The rpcid that returned null/error (potentially stale).

    Returns:
        Fallback rpcid string, or None if no fallback exists.
    """
    try:
        from engine.integrations.nlm_rpc_registry import get_rpc_registry
        reg = get_rpc_registry()
        # Reverse lookup: rpcid → operation name
        op = reg.find_operation_by_rpcid(rpc_id)
        if op:
            return reg.get_fallback_rpcid(op)
    except Exception:
        pass
    return None


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

    # ── Rotation detection with fallback ─────────────────────────────────
    # v1.57.2 [2026-03-26] — Per-rpcid rotation recovery
    # If a SPECIFIC rpcid returns null (but not all of them), it may be a
    # rotated rpcid rather than a stale session. Try the fallback rpcid
    # from the registry. Only attempt once per call (_refreshed flag reused
    # to prevent infinite recursion).
    if not _refreshed:
        recovered_results = list(results)
        any_recovered = False
        for idx, ((orig_rpcid, orig_args), (ret_rpcid, ret_data)) in enumerate(
            zip(calls, results)
        ):
            if ret_data is not None:
                continue  # This call succeeded — skip
            # null result for a non-session rpcid → possible rotation
            fallback = _get_fallback_rpcid(orig_rpcid)
            if fallback and fallback != orig_rpcid:
                logger.info(
                    "[NLMTransport] Trying fallback rpcid %s → %s "
                    "(operation=rotation_recovery)",
                    orig_rpcid, fallback,
                )
                fallback_results = _batchexecute_multi(
                    [(fallback, orig_args)], cookies, notebook_id,
                    _refreshed=True,
                )
                if fallback_results and fallback_results[0][1] is not None:
                    recovered_results[idx] = fallback_results[0]
                    any_recovered = True
                    # Mark the original rpcid as stale for diagnostics
                    _STALE_RPCIDS.add(orig_rpcid)
                    logger.info(
                        "[NLMTransport] Rotation recovery succeeded: "
                        "%s → %s (operation=rotation_recovery)",
                        orig_rpcid, fallback,
                    )
                else:
                    logger.warning(
                        "[NLMTransport] Fallback rpcid %s also returned null "
                        "(operation=rotation_recovery)",
                        fallback,
                    )
        if any_recovered:
            return recovered_results

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
