"""HAR file parser with streaming support for large files.

Provides efficient parsing, filtering, and analysis of HAR files.
Large files (>50 MB) are parsed with ijson streaming to avoid OOM.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

HAR_BASE_DIRS: List[str] = [
    r"C:\Files\Models\HAR_Files",
    r"C:\Files\Models\CosySim\data\har_files",
]

LARGE_FILE_THRESHOLD_MB = 50
BODY_TRUNCATE = 8000  # chars — enough to see JSON payloads

# ── Path helpers ──────────────────────────────────────────────────────────────


def get_har_dirs() -> List[str]:
    """Return all directories that contain HAR files."""
    return [d for d in HAR_BASE_DIRS if os.path.exists(d)]


def list_har_files() -> List[Dict[str, Any]]:
    """Return all HAR files across all HAR directories.

    Returns:
        List of dicts with keys: name, path, size_mb, account.
    """
    results: List[Dict[str, Any]] = []
    seen: set = set()

    def _walk(directory: str) -> None:
        if not os.path.exists(directory):
            return
        for root, dirs, files in os.walk(directory):
            dirs.sort()
            for fname in sorted(files):
                if not fname.endswith(".har"):
                    continue
                full = os.path.join(root, fname)
                if full in seen:
                    continue
                seen.add(full)
                size_mb = round(os.path.getsize(full) / (1024 * 1024), 1)
                rel = os.path.relpath(full, directory)
                account = rel.split(os.sep)[0] if os.sep in rel else "default"
                results.append({
                    "name": fname,
                    "path": full,
                    "size_mb": size_mb,
                    "account": account,
                })

    for d in get_har_dirs():
        _walk(d)

    return results


def find_har_file(filename: str) -> Optional[str]:
    """Find a HAR file by name (recursive search across all base dirs).

    Args:
        filename: The HAR filename (e.g. 'github.com-Extra-long-nihilistcod.har').

    Returns:
        Full path or None.
    """
    for base in get_har_dirs():
        for root, _, files in os.walk(base):
            if filename in files:
                return os.path.join(root, filename)
    return None


# ── Entry normalization ───────────────────────────────────────────────────────


def _headers_dict(headers_list: List[Dict]) -> Dict[str, str]:
    """Convert HAR headers array to dict, last value wins."""
    out: Dict[str, str] = {}
    for h in headers_list or []:
        out[h.get("name", "")] = h.get("value", "")
    return out


def _cookies_list(cookies: List[Dict]) -> List[Dict[str, str]]:
    return [{"name": c.get("name", ""), "value": c.get("value", "")} for c in (cookies or [])]


def _extract_body(content: Dict) -> str:
    """Extract response body from HAR content object."""
    text = content.get("text", "") or ""
    if len(text) > BODY_TRUNCATE:
        text = text[:BODY_TRUNCATE] + f"\n…[truncated {len(text) - BODY_TRUNCATE} chars]"
    return text


def _extract_request_body(postdata: Optional[Dict]) -> str:
    if not postdata:
        return ""
    text = postdata.get("text", "") or ""
    if len(text) > BODY_TRUNCATE:
        text = text[:BODY_TRUNCATE] + f"\n…[truncated {len(text) - BODY_TRUNCATE} chars]"
    return text


def normalize_entry(e: Dict) -> Dict[str, Any]:
    """Normalize a raw HAR entry into HAREntry-compatible dict."""
    req = e.get("request", {})
    resp = e.get("response", {})
    timings = e.get("timings", {})

    return {
        "url": req.get("url", ""),
        "method": req.get("method", "GET"),
        "status": resp.get("status", 0),
        "mime_type": resp.get("content", {}).get("mimeType", ""),
        "size": resp.get("content", {}).get("size", 0),
        "time_ms": round(e.get("time", 0), 1),
        "send_time_ms": round(timings.get("send", 0), 1),
        "wait_time_ms": round(timings.get("wait", 0), 1),
        "request_headers": _headers_dict(req.get("headers", [])),
        "response_headers": _headers_dict(resp.get("headers", [])),
        "request_cookies": _cookies_list(req.get("cookies", [])),
        "response_cookies": _cookies_list(resp.get("cookies", [])),
        "request_body": _extract_request_body(req.get("postData")),
        "response_body": _extract_body(resp.get("content", {})),
    }


# ── File loading ──────────────────────────────────────────────────────────────


def _load_har_json(har_path: str) -> Dict:
    """Load HAR JSON. Uses ijson streaming for large files if available."""
    size_mb = os.path.getsize(har_path) / (1024 * 1024)
    if size_mb > LARGE_FILE_THRESHOLD_MB:
        try:
            return _load_har_streaming(har_path)
        except ImportError:
            logger.warning("ijson not installed, falling back to full load for %s (%.1f MB)", har_path, size_mb)

    with open(har_path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _load_har_streaming(har_path: str) -> Dict:
    """Stream-parse a large HAR file using ijson to build entries list.

    Returns a minimal structure: {'log': {'entries': [...]}}
    """
    import ijson  # type: ignore

    entries: List[Dict] = []
    t0 = time.time()
    logger.info("Streaming large HAR: %s", har_path)

    with open(har_path, "rb") as f:
        for entry in ijson.items(f, "log.entries.item"):
            entries.append(entry)

    logger.info("Streamed %d entries in %.1fs", len(entries), time.time() - t0)
    return {"log": {"entries": entries}}


# ── Public API ────────────────────────────────────────────────────────────────


def get_entries(
    har_path: str,
    url_search: str = "",
    method_filter: str = "",
    offset: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    """Get paginated, filtered entries from a HAR file.

    Args:
        har_path: Absolute path to HAR file.
        url_search: Substring to match in URL.
        method_filter: HTTP method filter (GET, POST, etc.).
        offset: Pagination offset.
        limit: Page size (max 200).

    Returns:
        Dict with keys: total, entries (list of HAREntry dicts).
    """
    limit = min(limit, 200)
    raw = _load_har_json(har_path)
    all_entries: List[Dict] = raw.get("log", {}).get("entries", [])

    # Filter
    if url_search:
        search_lower = url_search.lower()
        all_entries = [
            e for e in all_entries
            if search_lower in e.get("request", {}).get("url", "").lower()
        ]
    if method_filter:
        method_upper = method_filter.upper()
        all_entries = [
            e for e in all_entries
            if e.get("request", {}).get("method", "").upper() == method_upper
        ]

    total = len(all_entries)
    page = all_entries[offset: offset + limit]
    normalized = [normalize_entry(e) for e in page]

    return {"total": total, "entries": normalized}


def get_entry(har_path: str, idx: int) -> Optional[Dict[str, Any]]:
    """Get a single entry by index.

    Args:
        har_path: Absolute path to HAR file.
        idx: Zero-based entry index.

    Returns:
        HAREntry dict or None.
    """
    raw = _load_har_json(har_path)
    entries: List[Dict] = raw.get("log", {}).get("entries", [])
    if idx < 0 or idx >= len(entries):
        return None
    return normalize_entry(entries[idx])


def extract_cookies(har_path: str, domain: Optional[str] = None) -> Dict[str, str]:
    """Extract all cookies from a HAR file.

    Args:
        har_path: Absolute path to HAR file.
        domain: Optional domain substring filter.

    Returns:
        Dict of cookie_name → cookie_value (last value wins).
    """
    raw = _load_har_json(har_path)
    cookies: Dict[str, str] = {}

    for entry in raw.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        url = req.get("url", "")
        if domain and domain not in url:
            continue
        for cookie in req.get("cookies", []):
            cookies[cookie.get("name", "")] = cookie.get("value", "")
        # Parse Cookie header for values not in cookies array
        for h in req.get("headers", []):
            if h.get("name", "").lower() == "cookie":
                for part in h.get("value", "").split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookies[k.strip()] = v.strip()

    return cookies


def find_api_endpoints(har_path: str, pattern: Optional[str] = None) -> List[Dict[str, Any]]:
    """Find interesting API endpoints in a HAR file.

    Filters for XHR/API calls (excludes static assets), optionally matching a pattern.

    Args:
        har_path: Absolute path to HAR file.
        pattern: Optional regex pattern to match in URL.

    Returns:
        List of simplified entry dicts: url, method, status, mime_type.
    """
    raw = _load_har_json(har_path)
    results: List[Dict[str, Any]] = []
    skip_exts = {".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                 ".woff", ".woff2", ".ttf", ".ico", ".map", ".webp"}
    re_pattern = re.compile(pattern, re.IGNORECASE) if pattern else None

    for entry in raw.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        url = req.get("url", "")
        method = req.get("method", "GET")

        # Skip static assets
        path = url.split("?")[0].split("/")[-1]
        ext = os.path.splitext(path)[1].lower()
        if ext in skip_exts:
            continue

        if re_pattern and not re_pattern.search(url):
            continue

        results.append({
            "url": url,
            "method": method,
            "status": entry.get("response", {}).get("status", 0),
            "mime_type": entry.get("response", {}).get("content", {}).get("mimeType", ""),
            "time_ms": round(entry.get("time", 0), 1),
        })

    return results


def analyze_har(har_path: str) -> Dict[str, Any]:
    """Produce a quick analysis/summary of a HAR file.

    Returns:
        Dict with: total_entries, unique_domains, methods, status_distribution,
                   has_google_auth, has_github_auth, api_endpoints, cookies_found.
    """
    raw = _load_har_json(har_path)
    entries = raw.get("log", {}).get("entries", [])

    from collections import Counter, defaultdict
    domains: set = set()
    methods: Counter = Counter()
    statuses: Counter = Counter()
    cookies_found: set = set()
    has_google_auth = False
    has_github_auth = False
    sapisid_found = False
    gh_bearer_found = False

    for entry in entries:
        req = entry.get("request", {})
        url = req.get("url", "")
        method = req.get("method", "GET")
        status = entry.get("response", {}).get("status", 0)

        # Domain
        m = re.match(r"https?://([^/]+)", url)
        if m:
            domains.add(m.group(1))

        methods[method] += 1
        statuses[status] += 1

        # Auth detection
        for h in req.get("headers", []):
            hn, hv = h.get("name", "").lower(), h.get("value", "")
            if hn == "authorization":
                if "github-bearer" in hv.lower() or "bearer" in hv.lower():
                    has_github_auth = True
                    gh_bearer_found = True
            if hn == "cookie":
                if "SAPISID" in hv:
                    has_google_auth = True
                    sapisid_found = True
                if "user_session" in hv:
                    has_github_auth = True

        # Also check the cookies array (some HAR files put cookies here)
        for c in req.get("cookies", []):
            cname = c.get("name", "")
            if cname == "SAPISID":
                has_google_auth = True
                sapisid_found = True
            if cname == "user_session":
                has_github_auth = True
            cookies_found.add(cname)

    return {
        "total_entries": len(entries),
        "unique_domains": sorted(domains),
        "methods": dict(methods.most_common()),
        "status_distribution": dict(statuses.most_common()),
        "has_google_auth": has_google_auth,
        "has_github_auth": has_github_auth,
        "sapisid_found": sapisid_found,
        "gh_bearer_found": gh_bearer_found,
        "cookies_found": sorted(cookies_found),
        "interesting_domains": [
            d for d in sorted(domains)
            if any(x in d for x in [
                "colab", "notebooklm", "copilot", "github", "gemini",
                "aistudio", "google", "openai", "anthropic", "rpc",
                "clients6", "googleapis",
            ])
        ],
    }


# ── Dict-serializable wrappers for rpc_proxy ─────────────────────────────────


def list_har_files_dict() -> Dict[str, Any]:
    """Wrapper for rpc_proxy call."""
    files = list_har_files()
    return {"files": files, "count": len(files)}


def get_entries_dict(
    filename: str,
    url_search: str = "",
    method_filter: str = "",
    offset: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    """Wrapper for rpc_proxy call."""
    har_path = find_har_file(filename)
    if not har_path:
        return {"error": f"HAR file not found: {filename}", "total": 0, "entries": []}
    return get_entries(har_path, url_search=url_search, method_filter=method_filter,
                       offset=offset, limit=limit)


def get_entry_dict(filename: str, idx: int) -> Dict[str, Any]:
    """Wrapper for rpc_proxy call."""
    har_path = find_har_file(filename)
    if not har_path:
        return {"error": f"HAR file not found: {filename}"}
    entry = get_entry(har_path, idx)
    if not entry:
        return {"error": f"Entry {idx} not found"}
    return entry


def analyze_har_dict(filename: str) -> Dict[str, Any]:
    """Wrapper for rpc_proxy call."""
    har_path = find_har_file(filename)
    if not har_path:
        return {"error": f"HAR file not found: {filename}"}
    return analyze_har(har_path)


def import_har_to_pool(
    filepath: str,
    account_name: str,
    services: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Extract cookies from a HAR and import into the Google account pool.

    Args:
        filepath: Path to HAR file (or just filename to auto-locate).
        account_name: Account name in the pool.
        services: List of service names (e.g. ['colab', 'notebooklm']).

    Returns:
        Dict with ok, cookies_imported, message.
    """
    # Resolve path
    if not os.path.isabs(filepath):
        found = find_har_file(filepath)
        if not found:
            return {"ok": False, "error": f"Cannot find HAR: {filepath}"}
        filepath = found

    if not os.path.exists(filepath):
        return {"ok": False, "error": f"File not found: {filepath}"}

    try:
        from engine.integrations.google_account_pool import get_account_pool

        pool = get_account_pool()
        cookies = extract_cookies(filepath)

        if not cookies:
            return {"ok": False, "error": "No cookies found in HAR"}

        svc = services or ["notebooklm"]
        entry = pool.get_account(account_name)
        if not entry:
            pool.add_account(account_name, cookies, svc)
        else:
            # Merge cookies and services
            existing = {c["name"]: c["value"] for c in entry.get("cookies", [])}
            existing.update(cookies)
            entry["cookies"] = [{"name": k, "value": v} for k, v in existing.items()]
            for s in svc:
                if s not in entry.get("services", []):
                    entry.setdefault("services", []).append(s)
            pool.save()

        return {
            "ok": True,
            "cookies_imported": len(cookies),
            "services": svc,
            "account_name": account_name,
            "message": f"Imported {len(cookies)} cookies for {account_name}",
        }

    except Exception as e:
        logger.exception("Failed to import HAR to pool")
        return {"ok": False, "error": str(e)}
