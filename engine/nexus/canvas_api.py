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
                "cookies_count": len(cookies),
                "is_rate_limited": acct.get("is_rate_limited", False),
                "last_used": acct.get("last_used"),
                "request_count": acct.get("request_count", 0),
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
        return jsonify({"success": success, "account_id": account_id, "cookies_extracted": cookies_extracted}), 200
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
