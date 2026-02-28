"""
NLM Live Proxy — Direct batchexecute API bridge for NotebookLM.

Architecture
~~~~~~~~~~~~
Rather than trying to automate a browser (which fails due to WebAuthn/passkeys
and Chrome's DPAPI cookie encryption), this proxy works by:

1. Extracting Google auth cookies from a user-captured HAR file
2. Using those cookies to make direct batchexecute HTTP calls to NotebookLM
3. Exposing a REST API at :8800 for CosySim skills to consume

This approach works because the HAR was captured from an already-authenticated
browser session. The session cookies remain valid until they expire (typically
1–24 hours for Google sessions).

Workflow:
    1. User visits notebooklm.google.com in Chrome, does some interactions
    2. User saves HAR: DevTools → Network → right-click → "Save all as HAR"
    3. User uploads HAR to Nexus Panel (or calls POST /cookies/import)
    4. This proxy extracts cookies and starts serving live NLM requests
    5. When cookies expire, user captures a new HAR

Limitations:
    - READ only — batchexecute RPCs are read operations
    - Cannot ask new questions (write operations need a different API)
    - Cookies expire; requires periodic HAR re-capture

Usage::

    from engine.mcp.nlm_live_proxy import create_nlm_proxy_app, get_nlm_proxy_app
    app = create_nlm_proxy_app()
    app.run(port=8800)

    # Standalone:
    python -m engine.mcp.nlm_live_proxy
"""
from __future__ import annotations

import base64
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
_NLM_HOST = "notebooklm.google.com"
_BATCH_URL = f"https://{_NLM_HOST}/_/LabsTailwindUi/data/batchexecute"
_REQUEST_TIMEOUT = 30
_COOKIES_LOCK = threading.Lock()

# RPC IDs we expose via HTTP API
_RPC_IDS = {
    "notebooks":     "ub2Bae",   # list all notebooks (account-wide)
    "sources":       "wXbhsf",   # source listing for a notebook
    "content":       "e3bVqc",   # full source text content
    "notes":         "gArtLc",   # notes/blueprints
    "summary":       "VfAZjd",   # AI summary/guide
    "conversations": "cFji9",    # Q&A chat history
    "thread":        "khqZz",    # full conversation thread
    "config":        "rLM1Ne",   # notebook configuration
}


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


def extract_cookies_from_har(har_path: str) -> Dict[str, str]:
    """Extract Google auth cookies from a HAR file.

    Looks for requests to notebooklm.google.com and extracts the cookies
    sent with those requests.

    Args:
        har_path: Path to the .har file.

    Returns:
        Dict of cookie_name → cookie_value for NLM-scoped cookies.
    """
    try:
        with open(har_path, "r", encoding="utf-8", errors="replace") as fh:
            har = json.load(fh)
    except Exception as exc:
        logger.error("Could not read HAR file %s: %s", har_path, exc)
        return {}

    cookies: Dict[str, str] = {}
    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        if _NLM_HOST not in url:
            continue
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

    # Keep only the auth-relevant cookies (Google session cookies)
    _AUTH_PREFIXES = ("SID", "SSID", "APISID", "SAPISID", "HSID", "OSID",
                      "__Secure-", "NID", "1P_JAR", "AEC", "SOCS",
                      "CONSENT", "SEARCH_SAMESITE")
    filtered = {k: v for k, v in cookies.items()
                if any(k.startswith(p) for p in _AUTH_PREFIXES)}
    logger.info("Extracted %d auth cookies from HAR (kept %d after filter)",
                len(cookies), len(filtered))
    return filtered


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

def _batchexecute(
    rpc_id: str,
    args_json: str,
    cookies: Dict[str, str],
    notebook_id: str = "",
) -> Tuple[Optional[str], Any]:
    """Make a single batchexecute RPC call to NotebookLM.

    Args:
        rpc_id:      The RPC function ID (e.g. "VfAZjd").
        args_json:   JSON-stringified argument array (e.g. '["nb-id",[2]]').
        cookies:     Google auth cookies dict.
        notebook_id: Optional notebook ID for the source-path URL param.

    Returns:
        Tuple of (rpc_id_returned, parsed_inner_data) or (None, None).
    """
    params: Dict[str, str] = {
        "rpcids": rpc_id,
        "source-path": f"/notebook/{notebook_id}" if notebook_id else "/",
        "bl": "boq_labs-tailwind-frontend_20250101.00_p0",
        "f.sid": "-1",
        "hl": "en",
        "_reqid": "1",
        "rt": "c",
    }
    url = f"{_BATCH_URL}?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode({
        "f.req": json.dumps([[
            [rpc_id, args_json, None, "generic"]
        ]])
    }).encode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36"),
        "Referer": f"https://{_NLM_HOST}/",
        "Origin": f"https://{_NLM_HOST}",
        "X-Same-Domain": "1",
        "Cookie": _cookies_header(cookies),
    }
    sapisid_hash = _sapisid_hash(cookies)
    if sapisid_hash:
        headers["Authorization"] = sapisid_hash

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace") if exc.fp else ""
        logger.error("batchexecute HTTP %s for %s: %s", exc.code, rpc_id, body_text[:200])
        return None, {"error": f"HTTP {exc.code}", "detail": body_text[:500]}
    except (urllib.error.URLError, OSError) as exc:
        logger.error("batchexecute connection error for %s: %s", rpc_id, exc)
        return None, {"error": "connection_error", "detail": str(exc)}

    return _parse_batchexecute(raw)


def _parse_batchexecute(raw: str) -> Tuple[Optional[str], Any]:
    """Decode the full batchexecute response pipeline (5 layers)."""
    body = raw.lstrip(")]}'").lstrip("\n")
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith('[["wrb.fr"'):
            try:
                outer = json.loads(line)
                rpc_id = outer[0][1]
                inner_raw = outer[0][2]
                inner = json.loads(inner_raw) if isinstance(inner_raw, str) else inner_raw
                return rpc_id, inner
            except (json.JSONDecodeError, IndexError, TypeError):
                continue
    return None, None


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
        return jsonify({
            "status": "ok" if cookies else "no_cookies",
            "has_cookies": bool(cookies),
            "cookie_count": len(cookies),
            "cookie_file": str(_COOKIES_FILE),
            "service": "nlm-live-proxy",
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

        new_cookies = extract_cookies_from_har(har_path)
        if not new_cookies:
            return jsonify({"error": "no_nlm_cookies_found",
                            "detail": "No Google auth cookies for notebooklm.google.com found in HAR"}), 422

        # Merge with existing cookies
        existing = _load_cookies()
        merged = {**existing, **new_cookies}
        _save_cookies(merged)
        return jsonify({
            "imported": len(new_cookies),
            "total": len(merged),
            "status": "ok",
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
