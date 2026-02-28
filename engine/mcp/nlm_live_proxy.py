"""
NLM Live Proxy — Full batchexecute API bridge for NotebookLM.

Architecture
~~~~~~~~~~~~
This proxy provides complete read AND write access to NotebookLM's private
batchexecute API, reverse-engineered from multi-session HAR analysis (8 HARs,
21 confirmed RPCs). It exposes a REST API at :8800 for CosySim agents.

Auth is handled via Google session cookies extracted from either:
  1. A manually captured HAR file (DevTools → Save all as HAR with sensitive data)
  2. Automatically via Chrome DevTools Protocol (CDP) — preferred

RPC ID Management
~~~~~~~~~~~~~~~~~
RPC IDs are **STABLE within a build label** but MAY change when Google deploys
a new frontend (BL changes approx. weekly). IDs are loaded from:
  1. data/nlm_rpc_registry.json   — updated by nlm_automation.py
  2. nlm_rpc_mapper._FALLBACK_RPC_IDS   — hardcoded confirmed IDs (fallback)

Run ``python -m engine.nexus.nlm_automation`` to re-discover all IDs.
Run ``python -m engine.nexus.nlm_rpc_mapper`` to check registry status.

Rate Limiting
~~~~~~~~~~~~~
All outbound NLM calls are rate-limited (default 1.5s between requests).
Configure via ``notebooklm.rate_limit_seconds`` in config/default.yaml.
Batch calls count as ONE request for rate-limiting purposes.

Complete RPC Catalogue (v3.0, 21 RPCs + 1 proto endpoint):
  See docs/NOTEBOOKLM_SDK.md for full documentation.

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

# ── Rate limiter ─────────────────────────────────────────────────────────

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

# ── RPC ID Registry ──────────────────────────────────────────────────────
# Loaded from nlm_rpc_mapper at runtime; hardcoded constants kept as
# readable aliases for use in this module.

try:
    from engine.nexus.nlm_rpc_mapper import get_rpc_id as _get_rpc_id
    _registry_available = True
except ImportError:
    _registry_available = False
    def _get_rpc_id(op: str) -> Optional[str]:  # type: ignore[misc]
        return None

def _rpc(operation: str, fallback: str) -> str:
    """Get RPC ID from registry, falling back to hardcoded value."""
    if _registry_available:
        rid = _get_rpc_id(operation)
        if rid:
            return rid
    return fallback

# Readable aliases (resolved at call time via _rpc() in actual calls)
RPC_SESSION_INIT        = "ZwVcOc"
RPC_LIST_SOURCES        = "wXbhsf"
RPC_LIST_NOTEBOOKS      = "ub2Bae"
RPC_LIST_AUDIO_TYPES    = "sqTeoe"   # ⚠️ v3.0: was "list all notebooks", is audio types
RPC_LOAD_NOTEBOOK       = "rLM1Ne"
RPC_NOTEBOOK_INFO       = "e3bVqc"
RPC_GET_THREAD_IDS      = "hPTbtc"   # ⚠️ v3.0: was "list sources paged", is thread IDs
RPC_READ_THREAD         = "khqZz"    # ⚠️ v3.0: was "sub-notebook sources", is thread msgs
RPC_USER_PROFILE        = "JFMDGd"   # ⚠️ v3.0: was "sources condensed", is user profile
RPC_AI_SUMMARY          = "VfAZjd"
RPC_LIST_ARTIFACTS      = "gArtLc"
RPC_MIND_MAP            = "cFji9"    # ⚠️ v3.0: was "conversation history", is mind map
RPC_ACCOUNT_STATE       = "ozz5Z"
RPC_READ_SOURCE         = "tr032e"
RPC_RESUME_SESSION      = "CCqFvf"   # ⭐ v3.0 new: load last active notebook
RPC_CHAT_MESSAGE        = "s0tc2d"
RPC_SAVE_NOTE           = "CYK0Xb"   # ⚠️ v3.0: was "legacy chat", is save note
RPC_GENERATE_DOC        = "ciyUvf"
RPC_SAVE_REPORT         = "R7cb6c"
RPC_FAST_RESEARCH_START = "Ljjv0c"   # ⭐ v3.0 new: start fast research
RPC_ADD_URL_SOURCES     = "LBwxtb"   # ⭐ v3.0 new: add URL sources batch

# ── Response Length Constants ────────────────────────────────────────────
RESP_LEN_DEFAULT = 4
RESP_LEN_LONGER  = 1
RESP_LEN_SHORTER = 2

# ── Document/Note Types ──────────────────────────────────────────────────
DOC_TYPE_BRIEF   = 2
DOC_TYPE_NOTE    = 9

# Write config object shared by several write RPCs (from HAR analysis)
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
    for key in ("QrtxK", "cfb2h"):
        if wiz.get(key):
            new_bl = str(wiz[key])
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
    _refreshed: bool = False,
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

    # Pack all calls into a single f.req array — 2-level format per SDK v3.0:
    # [["rpc_id", "args_json", null, "generic"], ...]
    f_req_calls = [[rpc_id, args_json, None, "generic"] for rpc_id, args_json in calls]
    body_dict: Dict[str, str] = {"f.req": json.dumps(f_req_calls)}
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

    # Auto-retry once if all results are null (likely stale at/f.sid token)
    if not _refreshed and all(data is None for _, data in results):
        logger.info("All batchexecute results null — refreshing session tokens and retrying")
        if refresh_session_tokens():
            return _batchexecute_multi(calls, cookies, notebook_id, _refreshed=True)

    return results


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
    _, data = _batchexecute(RPC_SAVE_NOTE, args, cookies, notebook_id)
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
            (RPC_SAVE_NOTE, json.dumps([notebook_id, q]))
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


# ── NLMClient ────────────────────────────────────────────────────────────

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
        _, data = _batchexecute("ub2Bae", "[[2]]", cookies)
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
        _, data = _batchexecute("VfAZjd", json.dumps([notebook_id, [2]]), cookies, notebook_id)
        result["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""
        _, data = _batchexecute("wXbhsf", json.dumps([None, 1, None, [2]]), cookies, notebook_id)
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
        _, data = _batchexecute("cFji9", json.dumps([notebook_id, None, None, [2]]), cookies, notebook_id)
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
        _, data = _batchexecute("wXbhsf", json.dumps([None, 1, None, [2]]), cookies, notebook_id)
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
        _, data = _batchexecute("hPTbtc", args, cookies, notebook_id)
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
        _, data = _batchexecute("gArtLc", args, cookies, notebook_id)
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

    def chat(
        self,
        notebook_id: str,
        question: str,
        role: str = "",
        response_length: int = RESP_LEN_DEFAULT,
    ) -> Dict[str, Any]:
        """Send a chat message using s0tc2d (async, supports role config).

        Args:
            notebook_id: The notebook UUID.
            question: The question to send.
            role: Optional configure-chat role/goal string.
            response_length: Response length hint (default RESP_LEN_DEFAULT).

        Returns:
            Dict with queued status and notebook metadata.
        """
        return chat_message(notebook_id, question, _load_cookies(), role, response_length)

    def chat_batch(
        self,
        notebook_id: str,
        questions: List[str],
        role: str = "",
        response_length: int = RESP_LEN_DEFAULT,
        max_batch: int = 5,
    ) -> List[Dict[str, Any]]:
        """Send multiple chat messages in batches using s0tc2d.

        Args:
            notebook_id: The notebook UUID.
            questions: List of question strings.
            role: Optional configure-chat role/goal for all messages.
            response_length: Response length hint.
            max_batch: Max questions per HTTP request.

        Returns:
            List of chat response dicts.
        """
        return chat_messages_batch(notebook_id, questions, _load_cookies(), role, response_length, max_batch)

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
        return save_note(notebook_id, source_ids, _load_cookies(), note_type)

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
        _, data = _batchexecute("VfAZjd", json.dumps([notebook_id, [2]]), cookies, notebook_id)
        return "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

    def get_user_quota(self) -> Dict[str, Any]:
        """Fetch user quota and account info (ozz5Z RPC).

        Returns:
            Dict with quota_data and extracted text.
        """
        return get_user_quota(_load_cookies())

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
            "rpc_catalog_version": "v2.1",
            "known_rpcs": 18,
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
            "rpc_catalog_version": "v3.0",
            "known_rpcs": 21,
            "rate_limit_seconds": _rate_limiter._min_gap,
            "registry_available": _registry_available,
        }), 200 if cookies else 503

    # ── Cookie management ───────────────────────────────────────────────

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
        """Add URL sources to a notebook via LBwxtb RPC.

        Body (JSON):
            {
              "urls": [{"url": "https://...", "title": "optional title"}],
              "session_id": "optional — if omitted, a fast research session is started first"
            }

        Returns: {added, session_id, notebook_id, poll_url}

        Flow:
          1. If session_id not provided, call Ljjv0c to start a fast research session
          2. Call LBwxtb with the session ID + URL array
          3. Return poll URL (/notebooks/<id>/sources/wait) to check processing status
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        urls = body.get("urls", [])
        if not urls:
            return jsonify({"error": "urls array is required"}), 400

        session_id = body.get("session_id", "")

        # Step 1: start fast research session if no session_id provided
        if not session_id:
            query = body.get("query", "research")
            rs_args = json.dumps([[query, 1], None, 1, notebook_id])
            _, rs_data = _batchexecute(RPC_FAST_RESEARCH_START, rs_args, cookies, notebook_id)
            if rs_data is None or (isinstance(rs_data, dict) and "error" in rs_data):
                return jsonify({"error": "failed to start research session",
                                "detail": rs_data}), 502
            try:
                session_id = rs_data[0] if isinstance(rs_data, list) else ""
            except (IndexError, TypeError):
                session_id = ""
            if not session_id:
                return jsonify({"error": "no session_id returned from Ljjv0c",
                                "raw": rs_data}), 502
            logger.info("Started fast research session %s for notebook %s", session_id, notebook_id)

        # Step 2: build sources array for LBwxtb
        # Web URL format: [None, None, [url, title], None, None, None, None, None, None, None, 2]
        sources_array = []
        for item in urls:
            url_str = item.get("url", "") if isinstance(item, dict) else str(item)
            title_str = item.get("title", url_str[:80]) if isinstance(item, dict) else url_str[:80]
            sources_array.append([None, None, [url_str, title_str],
                                   None, None, None, None, None, None, None, 2])

        lbw_args = json.dumps([None, [1], session_id, notebook_id, sources_array])
        _, lbw_data = _batchexecute(RPC_ADD_URL_SOURCES, lbw_args, cookies, notebook_id)
        if isinstance(lbw_data, dict) and "error" in lbw_data:
            return jsonify({"error": "LBwxtb failed", "detail": lbw_data}), 502

        return jsonify({
            "added": len(sources_array),
            "session_id": session_id,
            "notebook_id": notebook_id,
            "poll_url": f"/notebooks/{notebook_id}/sources/wait",
            "message": f"Added {len(sources_array)} URL(s). Poll poll_url to wait for processing.",
        })

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
