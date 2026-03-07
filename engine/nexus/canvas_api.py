"""Canvas API Sidecar — Flask bridge between Notebook-Canvas and CosySim Python services.

Runs at port 5591. Provides REST endpoints for:
- AI Studio generation (via AiStudioClient)
- Google account management (via GoogleAccountManager)
- Training data capture (via DataCollector)
- Nexus knowledge queries (via NexusClient or direct Nexus KMS REST proxy)

Started alongside the canvas Node.js server via start_servers.ps1.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, request, jsonify
from flask_cors import CORS

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ──── Lazy Service Accessors ────

_NEXUS_KMS_URL = "http://localhost:8700"
_COLLECTED_DIR = Path("training/datasets/collected")

_TYPE_MAP = {
    "conversational": "conversations",
    "tool_call": "tool_calls",
    "code": "code",
    "grammar_error": "grammar_errors",
}


def _get_aistudio() -> Optional[Any]:
    """Lazily import and return the AiStudioClient singleton."""
    try:
        from engine.nexus.aistudio_client import get_aistudio_client
        return get_aistudio_client()
    except Exception as exc:
        logger.warning("AiStudioClient unavailable: %s", exc)
        return None


def _get_account_manager() -> Optional[Any]:
    """Lazily import and return the GoogleAccountManager singleton."""
    try:
        from engine.nexus.google_account_manager import get_account_manager
        return get_account_manager()
    except Exception as exc:
        logger.warning("GoogleAccountManager unavailable: %s", exc)
        return None


def _get_nexus_client() -> Optional[Any]:
    """Lazily import and return the NexusClient singleton."""
    try:
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()
    except Exception as exc:
        logger.warning("NexusClient unavailable: %s", exc)
        return None


def _get_data_collector() -> Optional[Any]:
    """Lazily import and return the DataCollector singleton."""
    try:
        from training.data_collector import get_data_collector
        return get_data_collector()
    except Exception as exc:
        logger.warning("DataCollector unavailable: %s", exc)
        return None


# ──── AI Studio ────

@app.route("/api/generate", methods=["POST"])
def generate() -> Tuple[Any, int]:
    """Generate text via AI Studio with account rotation.

    Body JSON fields:
        prompt (str): The user prompt.
        model (str, optional): Gemini model ID.
        temperature (float, optional): Sampling temperature.
        max_tokens (int, optional): Maximum output tokens.

    Returns:
        JSON ``{text, model, tokens_used}`` on success, ``{error}`` on failure.
        Status 200 on success, 503 if no accounts available, 500 on error.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    prompt: str = body.get("prompt", "")
    model: str = body.get("model", "gemini-2.0-flash")
    temperature: float = float(body.get("temperature", 0.7))
    max_tokens: int = int(body.get("max_tokens", 2048))

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    client = _get_aistudio()
    if client is None:
        return jsonify({"error": "AI Studio client unavailable"}), 503

    try:
        text = client.generate_with_rotation(prompt, model, temperature, max_tokens)
        if text is None:
            return jsonify({"error": "No available accounts or generation failed"}), 503
        return jsonify({"text": text, "model": model, "tokens_used": None}), 200
    except Exception as exc:
        logger.error("generate() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/models", methods=["GET"])
def list_models() -> Tuple[Any, int]:
    """List available Gemini models.

    Returns:
        JSON ``{models: [{id, name, description, context_window}]}``.
    """
    client = _get_aistudio()
    if client is None:
        return jsonify({"models": []}), 200

    try:
        raw: List[Dict[str, Any]] = client.list_models()
        models = [
            {
                "id": m.get("id", ""),
                "name": m.get("name", m.get("id", "")),
                "description": m.get("description", ""),
                "context_window": m.get("context_window", 0),
            }
            for m in raw
        ]
        return jsonify({"models": models}), 200
    except Exception as exc:
        logger.error("list_models() error: %s", exc)
        return jsonify({"models": []}), 200


# ──── Google Accounts ────

@app.route("/api/accounts", methods=["GET"])
def get_accounts() -> Tuple[Any, int]:
    """Return all Google accounts with cookie counts masked.

    Returns:
        JSON ``{accounts: [...], total, available}`` where each account
        has ``cookies_count`` instead of raw cookie values.
    """
    manager = _get_account_manager()
    if manager is None:
        return jsonify({"accounts": [], "total": 0, "available": 0}), 200

    try:
        raw_accounts: List[Dict[str, Any]] = manager.get_all_accounts()
        masked: List[Dict[str, Any]] = []
        for acct in raw_accounts:
            cookies = acct.get("cookies", {})
            masked.append({
                "account_id": acct.get("account_id", ""),
                "service": acct.get("service", "google"),
                "services": acct.get("services", []),
                "detected_services": acct.get("detected_services", []),
                "cookies_count": len(cookies),
                "is_rate_limited": acct.get("is_rate_limited", False),
                "last_used": acct.get("last_used"),
                "request_count": acct.get("request_count", 0),
                "has_at_token": bool(acct.get("at_token")),
                "has_service_sessions": bool(acct.get("service_sessions")),
                "service_profiles": acct.get("service_profiles", {}),
            })
        available = sum(1 for a in masked if not a["is_rate_limited"])
        return jsonify({"accounts": masked, "total": len(masked), "available": available}), 200
    except Exception as exc:
        logger.error("get_accounts() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/accounts/import-har", methods=["POST"])
def import_har() -> Tuple[Any, int]:
    """Import Google auth cookies from a HAR file.

    Body JSON fields:
        har_path (str): Path to the .har file.
        account_id (str, optional): Account identifier.
        service (str, optional): Service label.

    Returns:
        JSON ``{success, account_id, cookies_extracted}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    har_path: str = body.get("har_path", "")
    account_id: str = body.get("account_id", Path(har_path).stem)
    service: str = body.get("service", "google")

    if not har_path:
        return jsonify({"error": "har_path is required"}), 400

    manager = _get_account_manager()
    if manager is None:
        return jsonify({"error": "Account manager unavailable"}), 503

    try:
        success: bool = manager.import_from_har(har_path, account_id, service)
        cookies_extracted = 0
        if success:
            acct_data = manager._load_account(account_id)  # noqa: SLF001
            cookies_extracted = len((acct_data or {}).get("cookies", {}))
        return jsonify({
            "success": success,
            "account_id": account_id,
            "cookies_extracted": cookies_extracted,
            "detected_services": (acct_data or {}).get("detected_services", []) if success else [],
            "services": (acct_data or {}).get("services", []) if success else [],
        }), 200
    except Exception as exc:
        logger.error("import_har() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/accounts/import-directory", methods=["POST"])
def import_directory() -> Tuple[Any, int]:
    """Import all HAR files from a directory.

    Body JSON fields:
        directory (str): Path to directory containing .har files.
        service (str, optional): Service label.

    Returns:
        JSON ``{success, accounts_imported}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    directory: str = body.get("directory", "")
    service: str = body.get("service", "google")

    if not directory:
        return jsonify({"error": "directory is required"}), 400

    manager = _get_account_manager()
    if manager is None:
        return jsonify({"error": "Account manager unavailable"}), 503

    try:
        count: int = manager.import_all_from_directory(directory, service)
        return jsonify({"success": True, "accounts_imported": count}), 200
    except Exception as exc:
        logger.error("import_directory() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ──── Training Data ────

@app.route("/api/training/capture", methods=["POST"])
def training_capture() -> Tuple[Any, int]:
    """Capture a conversation for training data.

    Body JSON fields:
        system_prompt (str): Character system prompt.
        messages (list): Conversation history turns.
        rating (float, optional): Quality rating 0.0-1.0.
        source (str, optional): Data source label.
        notebook_id (str, optional): Associated notebook ID.

    Returns:
        JSON ``{success, dataset_size}`` — always 200, non-blocking.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    system_prompt: str = body.get("system_prompt", "")
    messages: List[Dict[str, str]] = body.get("messages", [])
    rating: Optional[float] = body.get("rating")
    try:
        collector = _get_data_collector()
        if collector is None:
            return jsonify({"success": False, "dataset_size": 0}), 200

        # Extract the last assistant turn as the response; rest is history
        history = messages
        response = ""
        if messages and messages[-1].get("role") == "assistant":
            response = messages[-1].get("content", "")
            history = messages[:-1]

        collector.collect_conversation(
            system_prompt=system_prompt,
            history=history,
            response=response,
            rating=float(rating) if rating is not None else None,
        )
        stats: Dict[str, int] = collector.stats()
        dataset_size = sum(stats.values())
        return jsonify({"success": True, "dataset_size": dataset_size}), 200
    except Exception as exc:
        logger.warning("training_capture() failed (non-blocking): %s", exc)
        return jsonify({"success": False, "dataset_size": 0}), 200


@app.route("/api/training/stats", methods=["GET"])
def training_stats() -> Tuple[Any, int]:
    """Return training dataset statistics.

    Counts lines in each .jsonl file under training/datasets/collected/.

    Returns:
        JSON ``{total_examples, by_type: {conversations, tool_calls, code, grammar_errors}}``.
    """
    collected_dir = _COLLECTED_DIR
    by_type: Dict[str, int] = {
        "conversations": 0,
        "tool_calls": 0,
        "code": 0,
        "grammar_errors": 0,
    }

    try:
        collector = _get_data_collector()
        if collector is not None:
            raw_stats: Dict[str, int] = collector.stats()
            for model_type, count in raw_stats.items():
                friendly = _TYPE_MAP.get(model_type)
                if friendly and friendly in by_type:
                    by_type[friendly] += count
                elif model_type not in _TYPE_MAP:
                    # Accumulate unknown types into conversations as a catch-all
                    by_type["conversations"] += count

        # Also scan collected/ directory for flushed .jsonl files
        if collected_dir.exists():
            for jsonl_file in sorted(collected_dir.glob("*.jsonl")):
                stem = jsonl_file.stem.replace("_live", "")
                friendly = _TYPE_MAP.get(stem, "conversations")
                if friendly in by_type:
                    try:
                        with jsonl_file.open("r", encoding="utf-8") as fh:
                            line_count = sum(1 for line in fh if line.strip())
                        by_type[friendly] = max(by_type[friendly], line_count)
                    except Exception as file_exc:
                        logger.debug("Could not read %s: %s", jsonl_file, file_exc)
    except Exception as exc:
        logger.error("training_stats() error: %s", exc)

    total = sum(by_type.values())
    return jsonify({"total_examples": total, "by_type": by_type}), 200


# ──── Nexus Knowledge ────

def _nexus_search_fallback(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fallback Nexus search via Nexus KMS REST API.

    Args:
        query: Search query string.
        limit: Maximum number of results.

    Returns:
        List of result dicts from the KMS API, or empty list on failure.
    """
    url = f"{_NEXUS_KMS_URL}/api/entries?q={urllib.request.quote(query)}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else data.get("results", [])
    except Exception as exc:
        logger.warning("Nexus KMS REST fallback failed: %s", exc)
        return []


@app.route("/api/nexus/search", methods=["POST"])
def nexus_search() -> Tuple[Any, int]:
    """Search the Nexus knowledge base.

    Body JSON fields:
        query (str): Search query.
        limit (int, optional): Max results (default 10).

    Returns:
        JSON ``{results: [{id, title, content, category}]}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    query: str = body.get("query", "")
    limit: int = int(body.get("limit", 10))

    if not query:
        return jsonify({"results": []}), 200

    client = _get_nexus_client()
    if client is not None:
        try:
            raw = client.search(query)
            results = [
                {
                    "id": r.get("id", ""),
                    "title": r.get("title", ""),
                    "content": r.get("content", ""),
                    "category": r.get("category", ""),
                }
                for r in (raw or [])[:limit]
            ]
            return jsonify({"results": results}), 200
        except Exception as exc:
            logger.warning("NexusClient.search failed, trying REST fallback: %s", exc)

    # REST fallback
    results = _nexus_search_fallback(query, limit)
    return jsonify({"results": results}), 200


@app.route("/api/nexus/ask", methods=["POST"])
def nexus_ask() -> Tuple[Any, int]:
    """Ask a question against the Nexus knowledge base.

    Body JSON fields:
        question (str): The question to answer.
        depth (str, optional): Query depth — ``shallow``, ``deep``, or ``auto``.

    Returns:
        JSON ``{answer, source, confidence}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    question: str = body.get("question", "")
    depth: str = body.get("depth", "auto")

    if not question:
        return jsonify({"answer": "", "source": "none", "confidence": 0.0}), 200

    client = _get_nexus_client()
    if client is None:
        return jsonify({"error": "Nexus client unavailable"}), 503

    try:
        result = client.ask(question, depth=depth)
        if isinstance(result, dict):
            return jsonify({
                "answer": result.get("answer", ""),
                "source": result.get("source", "unknown"),
                "confidence": result.get("confidence", 0.0),
            }), 200
        return jsonify({"answer": str(result), "source": "unknown", "confidence": 0.5}), 200
    except Exception as exc:
        logger.error("nexus_ask() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/nexus/add", methods=["POST"])
def nexus_add() -> Tuple[Any, int]:
    """Add an entry to the Nexus knowledge base.

    Body JSON fields:
        title (str): Entry title.
        content (str): Entry content.
        content_type (str, optional): Content type (default ``note``).
        category (str, optional): Category label.

    Returns:
        JSON ``{success, entry_id}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    title: str = body.get("title", "")
    content: str = body.get("content", "")
    content_type: str = body.get("content_type", "note")
    category: str = body.get("category", "general")

    if not title or not content:
        return jsonify({"error": "title and content are required"}), 400

    client = _get_nexus_client()
    if client is None:
        return jsonify({"error": "Nexus client unavailable"}), 503

    try:
        result = client.add_entry(title, content, content_type=content_type, category=category)
        if isinstance(result, dict):
            return jsonify({"success": True, "entry_id": result.get("id", "")}), 200
        return jsonify({"success": bool(result), "entry_id": ""}), 200
    except Exception as exc:
        logger.error("nexus_add() error: %s", exc)
        return jsonify({"error": str(exc)}), 500




# ──── HAR File Management ────

_HAR_DIR = Path("data") / "har_files"


def _get_har_dir() -> Path:
    """Return and create the HAR storage directory."""
    _HAR_DIR.mkdir(parents=True, exist_ok=True)
    return _HAR_DIR


@app.route("/api/har/list", methods=["GET"])
def har_list() -> Tuple[Any, int]:
    """List available HAR files.

    Returns:
        JSON ``{files: [{name, size_mb, path, domain}]}``.
    """
    har_dir = _get_har_dir()
    files = []
    for p in sorted(har_dir.glob("*.har")):
        size_mb = round(p.stat().st_size / 1_048_576, 2)
        files.append({"name": p.name, "size_mb": size_mb, "path": str(p)})
    return jsonify({"files": files}), 200


@app.route("/api/har/upload", methods=["POST"])
def har_upload() -> Tuple[Any, int]:
    """Save an uploaded HAR file to data/har_files/.

    Expects multipart/form-data with a ``file`` field.

    Returns:
        JSON ``{success, name, path}``.
    """
    from flask import request as freq
    har_dir = _get_har_dir()
    if "file" not in freq.files:
        return jsonify({"error": "No file field in request"}), 400
    f = freq.files["file"]
    name: str = f.filename or "upload.har"
    if not name.endswith(".har"):
        name += ".har"
    dest = har_dir / name
    f.save(str(dest))
    return jsonify({"success": True, "name": name, "path": str(dest)}), 200


@app.route("/api/har/parse", methods=["POST"])
def har_parse() -> Tuple[Any, int]:
    """Parse a HAR file and return its entries as JSON (streaming-safe).

    Body JSON fields:
        path (str): Path to the .har file.
        limit (int, optional): Max entries to return (default 200).
        offset (int, optional): Entry offset for pagination (default 0).

    Returns:
        JSON ``{entries: [...], total, has_more}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    har_path: str = body.get("path", "")
    limit: int = int(body.get("limit", 200))
    offset: int = int(body.get("offset", 0))

    if not har_path or not Path(har_path).exists():
        return jsonify({"error": "HAR file not found"}), 404

    try:
        entries = _stream_har_entries(har_path, offset=offset, limit=limit)
        return jsonify(entries), 200
    except Exception as exc:
        logger.error("har_parse() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


def _stream_har_entries(
    har_path: str, offset: int = 0, limit: int = 200
) -> Dict[str, Any]:
    """Parse HAR entries with streaming to handle large files.

    Reads HAR entries lazily via ``ijson`` if available, falling back to
    a plain JSON load for files under 50 MB.

    Args:
        har_path: Path to .har file.
        offset: Entry offset.
        limit: Max entries.

    Returns:
        Dict ``{entries, total, has_more}``.
    """
    file_size = Path(har_path).stat().st_size

    if file_size < 50 * 1_048_576:
        # Small files — load fully
        with open(har_path, "r", encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
        raw_entries: List[Any] = data.get("log", {}).get("entries", [])
        total = len(raw_entries)
        slice_ = raw_entries[offset: offset + limit]
    else:
        # Large files — try ijson streaming, fall back to partial read
        try:
            import ijson  # type: ignore
            raw_entries = []
            count = 0
            with open(har_path, "rb") as fh:
                for entry in ijson.items(fh, "log.entries.item"):
                    count += 1
                    if count <= offset:
                        continue
                    if len(raw_entries) >= limit:
                        break
                    raw_entries.append(entry)
            total = count  # approximate
            slice_ = raw_entries
        except ImportError:
            # ijson not installed — read partial JSON safely
            with open(har_path, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
            raw_entries = data.get("log", {}).get("entries", [])
            total = len(raw_entries)
            slice_ = raw_entries[offset: offset + limit]

    def _format(e: Dict[str, Any]) -> Dict[str, Any]:
        req = e.get("request", {})
        resp = e.get("response", {})
        timings = e.get("timings", {})
        return {
            "url": req.get("url", ""),
            "method": req.get("method", ""),
            "status": resp.get("status", 0),
            "mime_type": resp.get("content", {}).get("mimeType", ""),
            "size": resp.get("bodySize", -1),
            "time_ms": round(e.get("time", 0)),
            "send_time_ms": round(timings.get("send", 0)),
            "wait_time_ms": round(timings.get("wait", 0)),
            "request_headers": {
                h["name"]: h["value"]
                for h in req.get("headers", [])
            },
            "response_headers": {
                h["name"]: h["value"]
                for h in resp.get("headers", [])
            },
            "request_cookies": req.get("cookies", []),
            "response_cookies": resp.get("cookies", []),
            "request_body": req.get("postData", {}).get("text", ""),
            "response_body": resp.get("content", {}).get("text", ""),
        }

    return {
        "entries": [_format(e) for e in slice_],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@app.route("/api/har/import-account", methods=["POST"])
def har_import_account() -> Tuple[Any, int]:
    """Extract cookies from a HAR file and add the account to the pool.

    Body JSON fields:
        path (str): Path to the .har file.
        account_name (str, optional): Account name (default: filename stem).

    Returns:
        JSON ``{success, account_name, cookies_extracted}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    har_path: str = body.get("path", "")
    account_name: str = body.get("account_name", Path(har_path).stem)

    if not har_path or not Path(har_path).exists():
        return jsonify({"error": "HAR file not found"}), 404

    try:
        from engine.integrations.har_extractor import HARExtractor
        from engine.integrations.google_account_pool import get_account_pool, GoogleAccount

        extractor = HARExtractor(har_path)
        cookies = extractor.extract_cookies()
        at_token = extractor.extract_at_token()
        pool = get_account_pool()

        account = GoogleAccount(
            name=account_name,
            cookies=cookies,
            services=["colab", "nlm", "aistudio"],
            at_token=at_token,
        )
        pool.add_account(account)
        return jsonify({
            "success": True,
            "account_name": account_name,
            "cookies_extracted": len(cookies),
        }), 200
    except Exception as exc:
        logger.error("har_import_account() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/har/<filename>/entries", methods=["GET"])
def har_entries(filename: str) -> Tuple[Any, int]:
    """Paginated entry list with optional filters.

    Query params:
        offset (int): Start offset (default 0).
        limit (int): Max results (default 100).
        method (str): Filter by HTTP method.
        url_search (str): Filter by URL substring.
        status (int): Filter by response status.

    Returns:
        JSON ``{entries, total, has_more}``.
    """
    har_dir = _get_har_dir()
    har_path = har_dir / filename
    if not har_path.exists():
        return jsonify({"error": "HAR file not found"}), 404

    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 100))
    method_filter = request.args.get("method", "").upper()
    url_search = request.args.get("url_search", "")
    status_filter = request.args.get("status", "")

    try:
        result = _stream_har_entries(str(har_path), offset=0, limit=100_000)
        entries = result["entries"]

        if method_filter:
            entries = [e for e in entries if e["method"] == method_filter]
        if url_search:
            entries = [e for e in entries if url_search.lower() in e["url"].lower()]
        if status_filter:
            try:
                sc = int(status_filter)
                entries = [e for e in entries if e["status"] == sc]
            except ValueError:
                pass

        total = len(entries)
        return jsonify({
            "entries": entries[offset: offset + limit],
            "total": total,
            "has_more": (offset + limit) < total,
        }), 200
    except Exception as exc:
        logger.error("har_entries() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/har/<filename>/entry/<int:idx>", methods=["GET"])
def har_entry_detail(filename: str, idx: int) -> Tuple[Any, int]:
    """Return full detail for a single HAR entry.

    Args:
        filename: HAR filename.
        idx: Zero-based entry index.

    Returns:
        JSON entry detail including full request/response bodies.
    """
    har_dir = _get_har_dir()
    har_path = har_dir / filename
    if not har_path.exists():
        return jsonify({"error": "HAR file not found"}), 404

    try:
        result = _stream_har_entries(str(har_path), offset=idx, limit=1)
        entries = result.get("entries", [])
        if not entries:
            return jsonify({"error": "Entry index out of range"}), 404
        return jsonify(entries[0]), 200
    except Exception as exc:
        logger.error("har_entry_detail() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ──── RPC Proxy ────


def _compute_sapisidhash(sapisid: str, origin: str) -> str:
    """Compute SAPISIDHASH Authorization header value.

    Args:
        sapisid: SAPISID cookie value.
        origin: Request origin URL.

    Returns:
        Authorization header string.
    """
    import hashlib
    ts = str(int(time.time()))
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


@app.route("/api/rpc/proxy", methods=["POST"])
def rpc_proxy() -> Tuple[Any, int]:
    """Server-side RPC proxy using stored account cookies.

    Retrieves the named account's cookies, computes SAPISIDHASH auth,
    and forwards the request — bypassing browser CORS restrictions.

    Body JSON fields:
        url (str): Full target URL (e.g. Colab RPC endpoint).
        method (str, optional): HTTP method (default ``POST``).
        account_name (str, optional): Account name from pool.
        headers (dict, optional): Extra headers to merge.
        body (str, optional): Raw request body string.
        content_type (str, optional): Content-Type header (default ``application/json+protobuf``).

    Returns:
        JSON ``{status, body, headers, latency_ms}``.
    """
    import requests as _req

    data: Dict[str, Any] = request.get_json(silent=True) or {}
    url: str = data.get("url", "")
    method: str = data.get("method", "POST").upper()
    account_name: Optional[str] = data.get("account_name")
    extra_headers: Dict[str, str] = data.get("headers", {})
    body_str: Optional[str] = data.get("body")
    content_type: str = data.get("content_type", "application/json+protobuf")

    if not url:
        return jsonify({"error": "url is required"}), 400

    headers: Dict[str, str] = {
        "Content-Type": content_type,
        "Accept": "*/*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
    }

    if account_name:
        try:
            from engine.integrations.google_account_pool import get_account_pool
            pool = get_account_pool()
            account = pool.get_by_name(account_name)
            if account is not None:
                headers["Cookie"] = pool.get_cookie_header(account)
                headers["X-Goog-Authuser"] = str(account.authuser)
                headers["X-Same-Domain"] = "1"
                from urllib.parse import urlparse
                origin = f"https://{urlparse(url).netloc}"
                sapisid = account.cookies.get("SAPISID", "")
                if sapisid:
                    headers["Authorization"] = _compute_sapisidhash(sapisid, origin)
        except Exception as exc:
            logger.warning("rpc_proxy: could not attach account cookies: %s", exc)

    headers.update(extra_headers)

    start = time.time()
    try:
        resp = _req.request(
            method=method,
            url=url,
            headers=headers,
            data=body_str.encode("utf-8") if body_str else None,
            timeout=30,
        )
        latency_ms = int((time.time() - start) * 1000)
        # Strip XSSI prefix )]}' if present
        resp_text = resp.text
        for prefix in (")]}'\n", ")]}'", ")]}"):
            if resp_text.startswith(prefix):
                resp_text = resp_text[len(prefix):]
                break
        return jsonify({
            "status": resp.status_code,
            "body": resp_text,
            "headers": dict(resp.headers),
            "latency_ms": latency_ms,
        }), 200
    except Exception as exc:
        logger.error("rpc_proxy() request error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ──── Account Management (compute-aware) ────


def _get_compute_router_safe() -> Optional[Any]:
    """Lazily import and return the ComputeRouter singleton."""
    try:
        from engine.integrations.compute_router import get_compute_router
        return get_compute_router()
    except Exception as exc:
        logger.warning("ComputeRouter unavailable: %s", exc)
        return None


@app.route("/api/accounts/list", methods=["GET"])
def accounts_list_compute() -> Tuple[Any, int]:
    """List all accounts with tier and usage info from ComputeRouter.

    Returns:
        JSON ``{accounts: [{name, tier, services, usage, limits}]}``.
    """
    try:
        from engine.integrations.google_account_pool import get_account_pool
        pool = get_account_pool()
        router = _get_compute_router_safe()

        result: List[Dict[str, Any]] = []
        for acct_info in pool.list_accounts():
            name = acct_info["name"]
            tier_info = router._tiers.get(name) if router else None
            usage = (router._usage.get(name, {}) if router else {})
            limits = tier_info.limits if tier_info else {}
            result.append({
                "name": name,
                "tier": tier_info.tier if tier_info else "unknown",
                "services": acct_info.get("services", []),
                "detected_services": acct_info.get("detected_services", []),
                "service_profiles": acct_info.get("service_profiles", {}),
                "has_service_sessions": acct_info.get("has_service_sessions", False),
                "has_nlm_session": acct_info.get("has_nlm_session", False),
                "hardware": tier_info.hardware if tier_info else [],
                "usage": usage,
                "limits": limits,
            })
        return jsonify({"accounts": result}), 200
    except Exception as exc:
        logger.error("accounts_list_compute() error: %s", exc)
        return jsonify({"accounts": [], "error": str(exc)}), 200


@app.route("/api/accounts/configure", methods=["POST"])
def accounts_configure() -> Tuple[Any, int]:
    """Configure limits or features for an account.

    Body JSON fields:
        name (str): Account name.
        service (str, optional): Service key to configure.
        limit (float, optional): New limit (use 1e18 for unlimited).
        features (list, optional): List of feature strings to unlock.

    Returns:
        JSON ``{success}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    name: str = body.get("name", "")
    if not name:
        return jsonify({"error": "name is required"}), 400

    router = _get_compute_router_safe()
    if router is None:
        return jsonify({"error": "ComputeRouter unavailable"}), 503

    if "service" in body and "limit" in body:
        router.configure_limits(name, body["service"], float(body["limit"]))
    if "features" in body:
        router.set_feature_config(name, list(body["features"]))

    return jsonify({"success": True}), 200


@app.route("/api/accounts/<name>", methods=["DELETE"])
def accounts_delete(name: str) -> Tuple[Any, int]:
    """Remove an account from the pool.

    Args:
        name: Account name.

    Returns:
        JSON ``{success}``.
    """
    try:
        from engine.integrations.google_account_pool import get_account_pool
        pool = get_account_pool()
        pool.remove_account(name)
        return jsonify({"success": True}), 200
    except Exception as exc:
        logger.error("accounts_delete() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ──── Compute (JIT) ────


@app.route("/api/compute/status", methods=["GET"])
def compute_status() -> Tuple[Any, int]:
    """Return ComputeRouter status snapshot.

    Returns:
        JSON ``{accounts, tunnels, lmstudio}``.
    """
    router = _get_compute_router_safe()
    if router is None:
        return jsonify({"error": "ComputeRouter unavailable"}), 503
    return jsonify(router.get_status()), 200


@app.route("/api/compute/infer", methods=["POST"])
def compute_infer() -> Tuple[Any, int]:
    """JIT inference via ComputeRouter.

    Body JSON fields:
        prompt (str): Text prompt.
        model (str, optional): Model ID or ``auto``.
        tier (str, optional): Minimum tier — ``free`` or ``pro``.

    Returns:
        JSON ``{response, backend, model, account, latency_ms, jit}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    prompt: str = body.get("prompt", "")
    model: str = body.get("model", "auto")
    tier: str = body.get("tier", "free")

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    router = _get_compute_router_safe()
    if router is None:
        return jsonify({"error": "ComputeRouter unavailable"}), 503

    try:
        result = router.jit_infer(prompt=prompt, model=model, require_tier=tier)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("compute_infer() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/compute/tunnel/deploy", methods=["POST"])
def compute_tunnel_deploy() -> Tuple[Any, int]:
    """Deploy a new Colab tunnel server.

    Body JSON fields:
        account_name (str): Account to use for deployment.
        tunnel_type (str, optional): ``cloudflare`` or ``ngrok`` (default ``cloudflare``).

    Returns:
        JSON ``{success, tunnel_url, hardware}`` or ``{error}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    account_name: str = body.get("account_name", "")
    tunnel_type: str = body.get("tunnel_type", "cloudflare")

    if not account_name:
        return jsonify({"error": "account_name is required"}), 400

    try:
        from engine.integrations.google_account_pool import get_account_pool
        from engine.integrations.colab_tunnel_server import get_tunnel_server
        pool = get_account_pool()
        account = pool.get_by_name(account_name)
        if account is None:
            return jsonify({"error": f"Account {account_name!r} not found"}), 404

        server = get_tunnel_server()
        session = server.deploy(account=account, tunnel_type=tunnel_type)
        return jsonify({
            "success": True,
            "tunnel_url": session.tunnel_url,
            "hardware": session.hardware,
            "account_name": session.account_name,
        }), 200
    except Exception as exc:
        logger.error("compute_tunnel_deploy() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/compute/tunnel/list", methods=["GET"])
def compute_tunnel_list() -> Tuple[Any, int]:
    """List active Colab tunnel sessions.

    Returns:
        JSON ``{sessions: [{account_name, tunnel_url, hardware, started_at, healthy}]}``.
    """
    try:
        from engine.integrations.colab_tunnel_server import get_tunnel_server
        server = get_tunnel_server()
        sessions = [
            {
                "id": k,
                "account_name": s.account_name,
                "tunnel_url": s.tunnel_url,
                "tunnel_type": s.tunnel_type,
                "hardware": s.hardware,
                "started_at": s.started_at,
                "healthy": s.healthy,
            }
            for k, s in server._sessions.items()
        ]
        return jsonify({"sessions": sessions}), 200
    except Exception as exc:
        logger.error("compute_tunnel_list() error: %s", exc)
        return jsonify({"sessions": [], "error": str(exc)}), 200


@app.route("/api/compute/tunnel/<session_id>", methods=["DELETE"])
def compute_tunnel_teardown(session_id: str) -> Tuple[Any, int]:
    """Tear down a tunnel session.

    Args:
        session_id: Session key (account_name).

    Returns:
        JSON ``{success}``.
    """
    try:
        from engine.integrations.colab_tunnel_server import get_tunnel_server
        server = get_tunnel_server()
        if session_id in server._sessions:
            del server._sessions[session_id]
            return jsonify({"success": True}), 200
        return jsonify({"error": "Session not found"}), 404
    except Exception as exc:
        logger.error("compute_tunnel_teardown() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/compute/models", methods=["GET"])
def compute_models() -> Tuple[Any, int]:
    """Return available models grouped by tier.

    Returns:
        JSON ``{free: [...], pro: [...]}``.
    """
    from engine.integrations.compute_router import MODELS_FREE, MODELS_PRO
    return jsonify({"free": MODELS_FREE, "pro": MODELS_PRO}), 200


# ──── Nexus GET pass-through ────


@app.route("/api/nexus/search", methods=["GET"])
def nexus_search_get() -> Tuple[Any, int]:
    """GET variant of Nexus search — ``?q=query`` param.

    Returns:
        JSON ``{results: [...]}``.
    """
    query: str = request.args.get("q", "")
    limit: int = int(request.args.get("limit", 10))
    if not query:
        return jsonify({"results": []}), 200
    client = _get_nexus_client()
    if client is not None:
        try:
            raw = client.search(query)
            results = [
                {"id": r.get("id", ""), "title": r.get("title", ""),
                 "content": r.get("content", ""), "category": r.get("category", "")}
                for r in (raw or [])[:limit]
            ]
            return jsonify({"results": results}), 200
        except Exception as exc:
            logger.warning("nexus_search_get fallback: %s", exc)
    results = _nexus_search_fallback(query, limit)
    return jsonify({"results": results}), 200


@app.route("/api/nexus/qa", methods=["POST"])
def nexus_qa() -> Tuple[Any, int]:
    """Store a Q&A pair in Nexus.

    Body JSON fields:
        question (str): Question.
        answer (str): Answer.
        category (str, optional): Category label.

    Returns:
        JSON ``{success, qa_id}``.
    """
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    question: str = body.get("question", "")
    answer: str = body.get("answer", "")
    category: str = body.get("category", "general")

    if not question or not answer:
        return jsonify({"error": "question and answer are required"}), 400

    client = _get_nexus_client()
    if client is None:
        return jsonify({"error": "Nexus client unavailable"}), 503

    try:
        result = client.add_qa(question, answer, category=category)
        if isinstance(result, dict):
            return jsonify({"success": True, "qa_id": result.get("id", "")}), 200
        return jsonify({"success": bool(result), "qa_id": ""}), 200
    except Exception as exc:
        logger.error("nexus_qa() error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/nexus/rules", methods=["GET"])
def nexus_rules() -> Tuple[Any, int]:
    """Get governance rules for a scope.

    Query params:
        scope (str): Rule scope (default ``global``).

    Returns:
        JSON ``{rules, scope}``.
    """
    scope: str = request.args.get("scope", "global")
    client = _get_nexus_client()
    if client is None:
        return jsonify({"rules": [], "scope": scope}), 200
    try:
        rules = client.get_rules(scope=scope)
        return jsonify({"rules": rules or [], "scope": scope}), 200
    except Exception as exc:
        logger.warning("nexus_rules() error: %s", exc)
        return jsonify({"rules": [], "scope": scope}), 200


# ──── Health ────

@app.route("/api/health", methods=["GET"])
def health() -> Tuple[Any, int]:
    """Return sidecar health and service availability.

    Returns:
        JSON ``{status, services: {aistudio, accounts, nexus, collector}}``.
    """
    aistudio_ok = _get_aistudio() is not None
    nexus_ok = _get_nexus_client() is not None
    collector_ok = _get_data_collector() is not None

    manager = _get_account_manager()
    account_count = 0
    if manager is not None:
        try:
            account_count = manager.account_count()
        except Exception:
            account_count = 0

    return jsonify({
        "status": "ok",
        "services": {
            "aistudio": aistudio_ok,
            "accounts": account_count,
            "nexus": nexus_ok,
            "collector": collector_ok,
        },
    }), 200


# ──── App Factory ────

def create_app() -> Flask:
    """Create and return the configured Flask application.

    Returns:
        Configured Flask app with all routes registered.
    """
    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Canvas API Sidecar")
    parser.add_argument("--port", type=int, default=5591)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Canvas API sidecar on %s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False)
