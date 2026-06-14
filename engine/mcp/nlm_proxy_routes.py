"""NLM Flask proxy routes — REST API for all NLM, Gemini, Workspace, Colab, AI Studio, and AppScript operations."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request

from engine.mcp.nlm_rpc_constants import (
    _RateLimiter,
    DOC_TYPE_BRIEF,
    DOC_TYPE_NOTE,
    RPC_ACCOUNT_STATE,
    RPC_ADD_RESEARCH_SOURCE,
    RPC_ADD_SOURCE,
    RPC_AI_SUMMARY,
    RPC_CREATE_NOTE,
    RPC_DELETE_SOURCE,
    RPC_FAST_RESEARCH_START,
    RPC_GENERATE_DOC,
    RPC_GET_ARTIFACTS,
    RPC_GET_THREAD_IDS,
    RPC_LIST_ARTIFACTS,
    RPC_LIST_AUDIO_TYPES,
    RPC_LIST_NOTEBOOKS,
    RPC_LIST_SOURCES,
    RPC_LOAD_NOTEBOOK,
    RPC_MIND_MAP,
    RPC_NOTEBOOK_CONTENT,
    RPC_NOTEBOOK_DETAILS,
    RPC_NOTEBOOK_INFO,
    RPC_NOTEBOOK_STATE,
    RPC_OPEN_NOTEBOOK,
    RPC_PENDING_SOURCES,
    RPC_READ_SOURCE,
    RPC_READ_THREAD,
    RPC_REGISTER_FILES,
    RPC_RENAME_NOTEBOOK,
    RPC_RESUME_SESSION,
    RPC_SAVE_NOTE,
    RPC_SAVE_REPORT,
    RPC_SESSION_INIT,
    RPC_SOURCE_DETAIL,
    RPC_SOURCE_STATUS,
    RPC_START_DEEP_RESEARCH,
    RPC_SYNC_NOTES,
    RPC_USER_PLAN,
    RPC_USER_PROFILE,
    RPC_USER_QUOTA,
    _DEFAULT_BL,
    _DEFAULT_BL_DATE,
    _rate_limiter,
    _registry_available,
)
import engine.mcp.nlm_auth as _nlm_auth
from engine.mcp.nlm_auth import (
    _COOKIES_LOCK,
    _NLM_HOST,
    _get_bl,
    _get_fsid,
    _load_cookies,
    _load_meta,
    _save_cookies,
    _save_meta,
    extract_cookies_from_har,
    refresh_session_tokens,
)
from engine.mcp.nlm_transport import (
    _batchexecute,
    _batchexecute_multi,
    _build_headers,
    _dedup,
    _extract_sources,
    _extract_strings,
    _parse_batchexecute,
    _parse_batchexecute_multi,
)
from engine.mcp.nlm_operations import (
    add_research_source,
    add_source_url,
    add_text_source,
    ask_question,
    ask_questions_batch,
    create_note,
    delete_source,
    get_audio_options,
    get_source_summary,
    poll_source_status,
    read_source,
    register_file_sources,
    rename_notebook,
    save_note,
    start_deep_research,
    sync_notes,
    upload_file_to_nlm,
)
from engine.mcp.nlm_archive import (
    download_all_sources,
    export_all_notebooks,
    export_notebook,
    generate_document,
    get_user_plan,
    get_user_quota,
    save_note_report,
)
from engine.mcp.nlm_client import NLMClient, get_nlm_client

from engine.config import get_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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

    # ── Health & Status Routes ────────────────────────────────────────────
    # GET /health  — full service health: cookies, BL age, rate limit config

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
        except Exception as exc:
            logger.debug("BL age calculation failed in health check: %s", exc)

        return jsonify({
            "status": "ok" if cookies else "no_cookies",
            "has_cookies": bool(cookies),
            "cookie_count": len(cookies),
            "cookie_file": str(_nlm_auth._COOKIES_FILE),
            "service": "nlm-live-proxy",
            "bl": bl,
            "bl_age_days": bl_age_days,
            "bl_stale": bl_age_days is not None and bl_age_days >= 8,
            "rpc_catalog_version": "v3.1",
            "known_rpcs": 25,
            "rate_limit_seconds": _rate_limiter._min_gap,
            "registry_available": _registry_available,
        }), 200 if cookies else 503

    # ── Cookie Management Routes ──────────────────────────────────────────
    # POST /cookies/refresh  — refresh f.sid + at from live NLM page
    # POST /cookies/import   — import from HAR file
    # POST /cookies/capture  — auto-capture via Chrome CDP
    # GET  /cookies          — list stored cookie names
    # DELETE /cookies        — clear all stored cookies

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

    # ── Notebook Read Routes ──────────────────────────────────────────────
    # GET /notebooks                  — list all notebooks (ub2Bae)
    # GET /notebooks/<id>             — full notebook dump (multiple RPCs)
    # GET /notebooks/<id>/sources     — source metadata (wXbhsf)
    # GET /notebooks/<id>/summary     — AI summary (VfAZjd)
    # GET /notebooks/<id>/notes       — notes/artifacts (gArtLc)
    # GET /notebooks/<id>/conversations — conversation text (cFji9)
    # GET /notebooks/<id>/content     — raw document content (e3bVqc)
    # GET /notebooks/<id>/history     — thread IDs + messages (hPTbtc + khqZz)

    @app.route("/notebooks", methods=["GET"])
    def list_notebooks():
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        _, data = _batchexecute(RPC_LIST_NOTEBOOKS, "[[2]]", cookies)
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

    # ── Notebook Sub-Resource Read Routes ─────────────────────────────────

    @app.route("/notebooks/<notebook_id>/sources", methods=["GET"])
    def get_sources(notebook_id: str):
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        args = json.dumps([None, 1, None, [2]])
        _, data = _batchexecute(RPC_LIST_SOURCES, args, cookies, notebook_id)
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
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, args, cookies, notebook_id)
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
        _, data = _batchexecute(RPC_GET_ARTIFACTS, args, cookies, notebook_id)
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
        _, data = _batchexecute(RPC_SYNC_NOTES, args, cookies, notebook_id)
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
        _, data = _batchexecute(RPC_NOTEBOOK_STATE, args, cookies, notebook_id)
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
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]),
                                cookies, notebook_id)
        result["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

        # Sources
        _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]),
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
        _, data = _batchexecute(RPC_SYNC_NOTES, json.dumps([notebook_id, None, None, [2]]),
                                cookies, notebook_id)
        convos = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["conversations"] = [c for c in convos if len(c) > 100]

        result["stats"] = {
            "sources": len(result["sources"]),
            "notes":   len(result["notes"]),
            "conversations": len(result["conversations"]),
        }
        return jsonify(result)

    # ── Write: Ask / Chat Routes ──────────────────────────────────────────
    # POST /notebooks/<id>/ask        — citation-annotate Q&A (CYK0Xb)
    # POST /notebooks/<id>/ask_batch  — batch citation Q&A (CYK0Xb multi)
    # POST /notebooks/<id>/chat       — real chat (GenerateFreeFormStreamed)
    # POST /notebooks/<id>/chat_batch — batch chat (GenerateFreeFormStreamed)

    @app.route("/notebooks/<notebook_id>/ask", methods=["POST"])
    def ask_single(notebook_id: str):
        """Ask a single question using CYK0Xb (citation-annotate, synchronous).

        For natural conversational chat, use POST /notebooks/<id>/chat instead.

        Body (JSON):
          {
            "question": "What is the main argument?",
            "mode": "annotate"
          }
        Returns: {answer_id, answer, sources}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "missing question"}), 400
        result = ask_question(notebook_id, question, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/ask_batch", methods=["POST"])
    def ask_batch_route(notebook_id: str):
        """Ask multiple questions in parallel batches using CYK0Xb.

        For natural conversational chat, use POST /notebooks/<id>/chat_batch instead.

        Body (JSON):
          {
            "questions": ["Q1?", "Q2?", "Q3?"],
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
        results = ask_questions_batch(notebook_id, questions, cookies, max_batch)
        return jsonify({
            "answers": results,
            "count": len(results),
            "questions": questions,
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
    def save_note_report_route(notebook_id: str):
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
        result = save_note_report(notebook_id, source_ids, cookies, note_type)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/chat", methods=["POST"])
    def chat_single(notebook_id: str):
        """Send a chat message — delegates to NLM Node bridge (browser-based).

        The batchexecute GenerateFreeFormStreamed RPC returns 400 (payload
        undecoded). The Node bridge uses real browser automation — always works.

        Body (JSON):
          {
            "question": "What is the main argument?",
            "reset_history": false
          }
        Returns: {answer, thread_id, message_id, question, sources}
        """
        if not _nlm_auth._COOKIES_FILE.exists():
            return jsonify({"error": "not authenticated — run setup_auth first"}), 401
        body = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "missing question"}), 400
        reset_history = bool(body.get("reset_history", False))
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            result = get_nlm_hybrid().ask(notebook_id, question, reset_history=reset_history)
        except Exception as exc:
            logger.error("chat_single hybrid error: %s", exc)
            result = {"error": str(exc)}
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/chat_batch", methods=["POST"])
    def chat_batch_route(notebook_id: str):
        """Send multiple chat messages — delegates to NLM Node bridge.

        Body (JSON):
          {
            "questions": ["Q1?", "Q2?", ...]
          }
        Returns: {results: [{answer, ...}], count, questions}
        """
        if not _nlm_auth._COOKIES_FILE.exists():
            return jsonify({"error": "not authenticated — run setup_auth first"}), 401
        body = request.json or {}
        questions = body.get("questions", [])
        if not questions:
            return jsonify({"error": "missing questions array"}), 400
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            results = get_nlm_hybrid().ask_batch(notebook_id, questions)
        except Exception as exc:
            logger.error("chat_batch_route hybrid error: %s", exc)
            results = [{"error": str(exc)}] * len(questions)
        return jsonify({
            "results": results,
            "count": len(results),
            "questions": questions,
        })

    # ── Write: Source Management Routes ──────────────────────────────────
    # POST   /notebooks/<id>/sources          — add URLs (izAoDd)
    # POST   /notebooks/<id>/sources/url      — add single URL (izAoDd)
    # DELETE /notebooks/<id>/sources/<src_id> — delete source (tGMBJ)
    # POST   /notebooks/<id>/rename           — rename notebook (s0tc2d)
    # GET    /notebooks/<id>/sources/wait     — poll until sources ready (rLM1Ne)
    # POST   /notebooks/<id>/generate         — generate document (ciyUvf)
    # POST   /notebooks/<id>/save_note        — save note artifact (R7cb6c)

    # ── Write: Research Routes ────────────────────────────────────────────
    # POST /notebooks/<id>/research        — fast research session (Ljjv0c)
    # POST /notebooks/<id>/research/deep   — deep research (QA9ei)
    # POST /notebooks/<id>/research/source — add research doc as source (LBwxtb)

    # ── Read: Threads, Mindmap, User Routes ──────────────────────────────
    # GET /notebooks/<id>/threads          — thread IDs (hPTbtc)
    # GET /notebooks/<id>/threads/<tid>    — thread messages (khqZz)
    # GET /notebooks/<id>/mindmap          — D3 mind map (cFji9)
    # GET /sources/<id>/content            — full source text (tr032e)
    # GET /user/profile                    — user profile (JFMDGd)
    # GET /user/quota                      — storage quota (ozz5Z)

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

    # ── CDP Cookie Capture & Meta Routes ─────────────────────────────────
    # POST /cookies/capture  — auto-capture via Chrome CDP
    # GET  /meta             — return current bl, f.sid, at-presence
    # POST /meta             — manually update bl or f.sid
    # GET  /rate_limit       — current rate limit config
    # POST /rate_limit       — override rate limit for session
    # POST /rpc/<id>         — generic batchexecute passthrough
    # GET  /rpc_registry     — RPC ID registry status

    @app.route("/cookies/capture", methods=["POST"])
    def capture_cookies():
        """Automatically capture auth cookies from Chrome via CDP.

        Requires Chrome to be running with --remote-debugging-port=9223,
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
        if "at" in body and body["at"]:
            meta["at"] = body["at"]
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
        except (IndexError, TypeError) as exc:
            logger.warning("Failed to parse thread IDs for notebook %s: %s", notebook_id, exc)
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
        """Add one or more URL sources to a notebook via izAoDd RPC.

        Confirmed v3.1: izAoDd is the correct RPC for adding URL/YouTube sources.
        Each URL is added in a separate API call. YouTube URLs are detected
        automatically and encoded at position 7 instead of position 2.

        Body (JSON):
            {
              "urls": ["https://example.com/article", "https://youtu.be/xyz"]
            }

        Returns: {added, results: [{source_id, url, status}], notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        raw_urls = body.get("urls", [])
        if not raw_urls:
            return jsonify({"error": "urls array is required"}), 400

        results = []
        for item in raw_urls:
            url_str = item if isinstance(item, str) else item.get("url", "")
            if not url_str:
                continue
            res = add_source_url(notebook_id, url_str, cookies)
            results.append(res)

        return jsonify({
            "added": len(results),
            "results": results,
            "notebook_id": notebook_id,
        })

    @app.route("/notebooks/<notebook_id>/sources/url", methods=["POST"])
    def add_single_source(notebook_id: str):
        """Add a single URL or YouTube source to a notebook (izAoDd RPC).

        YouTube URLs (youtube.com/watch, youtu.be/) are auto-detected and
        encoded at position 7 in the source object. Regular URLs use position 2.

        Body (JSON): {"url": "https://..."}
        Returns: {source_id, url, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        url = body.get("url", "").strip()
        if not url:
            return jsonify({"error": "url is required"}), 400
        result = add_source_url(notebook_id, url, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/sources/text", methods=["POST"])
    def add_text_source_route(notebook_id: str):
        """Add an inline text/markdown source to a notebook (izAoDd RPC, text format).

        Confirmed from HAR 2026-03-01. No external URL needed — content is
        passed directly. NLM indexes it as a paste/text source.

        Body (JSON):
            {
              "title": "ARCHITECTURE.md",
              "content": "# Architecture\\n\\nCosySim is..."
            }

        Returns: {source_id, title, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        title = body.get("title", "").strip()
        content = body.get("content", "").strip()
        if not title or not content:
            return jsonify({"error": "title and content are required"}), 400
        result = add_text_source(notebook_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/sources/status", methods=["GET"])
    def source_status_route(notebook_id: str):
        """Poll source processing status via rLM1Ne RPC.

        Query params:
            first=true  (default) for first poll, first=false for continuing.

        Returns: {status, data}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        first = request.args.get("first", "true").lower() != "false"
        result = poll_source_status(notebook_id, cookies, first_poll=first)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/sources/file", methods=["POST"])
    def upload_file_source_route(notebook_id: str):
        """Upload a file as a notebook source (o4cbdc + /upload/_/ flow).

        Accepts multipart/form-data with a 'file' field, or JSON with
        {"filename": "...", "content": "...", "mime_type": "text/plain"}.

        For text/markdown files, prefer POST /sources/text (simpler, no upload step).
        Use this route for PDFs and binary files.

        Returns: {source_id, filename, upload_id, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()

        # Support both multipart and JSON
        if request.content_type and "multipart" in request.content_type:
            if "file" not in request.files:
                return jsonify({"error": "file field required"}), 400
            f = request.files["file"]
            filename = f.filename
            content_bytes = f.read()
            mime_type = f.content_type or "application/octet-stream"
        else:
            body = request.json or {}
            filename = body.get("filename", "upload.txt")
            content = body.get("content", "")
            content_bytes = content.encode("utf-8")
            mime_type = body.get("mime_type", "text/plain")

        # Step 1: register filename with NLM to get source_id
        registrations = register_file_sources(notebook_id, [filename], cookies)
        if not registrations or registrations[0].get("error"):
            return jsonify(registrations[0] if registrations else {"error": "registration_failed"}), 502
        source_id = registrations[0].get("source_id")

        # Step 2: upload bytes
        upload_result = upload_file_to_nlm(filename, content_bytes, cookies, mime_type)
        if upload_result.get("error"):
            return jsonify(upload_result), 502

        return jsonify({
            "source_id": source_id,
            "filename": filename,
            "upload_id": upload_result.get("upload_id"),
            "status": upload_result.get("status", "uploaded"),
        })

    @app.route("/notebooks/<notebook_id>/sources/<source_id>", methods=["DELETE"])
    def delete_source_route(notebook_id: str, source_id: str):
        """Delete a source from a notebook (tGMBJ RPC).

        Confirmed v3.1 from HAR analysis.
        Payload: [[[source_id]], [2]]

        Returns: {deleted, source_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = delete_source(source_id, cookies)
        if not result.get("deleted"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/rename", methods=["POST"])
    def rename_notebook_route(notebook_id: str):
        """Rename a notebook (s0tc2d RPC).

        Confirmed v3.1: s0tc2d is RENAME_NOTEBOOK, not chat.

        Body (JSON): {"name": "New Notebook Title"}
        Returns: {renamed, notebook_id, name}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        new_name = body.get("name", "").strip()
        if not new_name:
            return jsonify({"error": "name is required"}), 400
        result = rename_notebook(notebook_id, new_name, cookies)
        if not result.get("renamed"):
            return jsonify(result), 502
        return jsonify(result)

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
        except (IndexError, TypeError) as exc:
            logger.warning("Failed to extract research session_id for %s: %s", notebook_id, exc)
            session_id = ""
        return jsonify({"session_id": session_id, "notebook_id": notebook_id, "query": query})

    @app.route("/notebooks/<notebook_id>/research/deep", methods=["POST"])
    def start_deep_research_route(notebook_id: str):
        """Start a deep research session (QA9ei RPC).

        Confirmed v3.1: QA9ei triggers NLM deep research on a topic.
        Returns session_id. NLM generates a research document async.
        Use POST /research/source to add the generated document as a source.

        Body (JSON): {"topic": "transformer attention mechanisms"}
        Returns: {session_id, topic, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        topic = body.get("topic", "").strip()
        if not topic:
            return jsonify({"error": "topic is required"}), 400
        result = start_deep_research(notebook_id, topic, cookies)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/research/source", methods=["POST"])
    def add_research_source_route(notebook_id: str):
        """Add an AI-generated research document as a notebook source (LBwxtb RPC).

        Confirmed v3.1: LBwxtb adds AI-generated content docs as sources.
        Call this after start_deep_research with the generated title and content.

        Body (JSON):
          {
            "session_id": "uuid from deep research",
            "title": "Research: Transformer Attention",
            "content": "Full text of the research document..."
          }
        Returns: {source_id, title, session_id, notebook_id}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        session_id = body.get("session_id", "").strip()
        title = body.get("title", "").strip()
        content = body.get("content", "").strip()
        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        if not title or not content:
            return jsonify({"error": "title and content are required"}), 400
        result = add_research_source(notebook_id, session_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

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
        except (IndexError, TypeError) as exc:
            logger.debug("Thread ID parse error for %s: %s", notebook_id, exc)
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
        except (IndexError, TypeError) as exc:
            logger.debug("Mindmap extraction error for %s: %s", notebook_id, exc)
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
        except (IndexError, TypeError) as exc:
            logger.debug("User profile parse error: %s", exc)
        return jsonify(profile)

    @app.route("/user/plan", methods=["GET"])
    def get_user_plan_route():
        """Get user plan/tier and daily query allowance (ZwVcOc RPC).

        Returns: {plan_name, daily_limit, queries_remaining}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_user_plan(cookies)
        if isinstance(result, dict) and "error" in result:
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/user/queries", methods=["GET"])
    def get_user_queries():
        """Get remaining queries as a simple integer (fast path from JFMDGd RPC).

        Returns: {queries_remaining: int}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        notebook_id = request.args.get("notebook_id", "")
        args = json.dumps([notebook_id, [2]])
        _, data = _batchexecute(RPC_USER_PROFILE, args, cookies, notebook_id)
        remaining: Optional[int] = None
        try:
            if isinstance(data, list) and len(data) > 2 and isinstance(data[2], (int, float)):
                remaining = int(data[2])
        except (IndexError, TypeError) as exc:
            logger.debug("Quota parse error: %s", exc)
        return jsonify({"queries_remaining": remaining})

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

    # ════════════════════════════════════════════════════════════════════════════
    # DOWNLOAD & ARCHIVE ROUTES
    # Bulk export of notebook content, sources, and full archives.
    # These routes use tr032e (read_source) per source, which is slow for large
    # notebooks — each source call respects the rate limiter (1.5s gap default).
    # ════════════════════════════════════════════════════════════════════════════

    @app.route("/notebooks/<notebook_id>/sources/content", methods=["GET"])
    def download_sources_content(notebook_id: str):
        """Download full text content of ALL sources in a notebook.

        Uses wXbhsf to list sources, then tr032e per source to read content.
        Slow for large notebooks — each source is a separate rate-limited call.

        Query params:
            source_ids  — comma-separated UUIDs to read (default: all sources)

        Returns: {notebook_id, sources: [{source_id, title, url, word_count, content}],
                  total_sources, total_words}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        raw_ids = request.args.get("source_ids", "")
        sid_filter = [s.strip() for s in raw_ids.split(",") if s.strip()] if raw_ids else None
        results = download_all_sources(notebook_id, cookies, sid_filter)
        total_words = sum(r.get("word_count", 0) for r in results)
        return jsonify({
            "notebook_id": notebook_id,
            "sources": results,
            "total_sources": len(results),
            "total_words": total_words,
        })

    @app.route("/sources/<source_id>/export", methods=["GET"])
    def export_source_text(source_id: str):
        """Export a single source as a plain text file download.

        Uses tr032e to read the full source content and streams it as a
        text/plain attachment. Useful for piping source content into other tools.

        Query params:
            filename  — override the download filename (default: <source_id>.txt)

        Returns: text/plain file download
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        from flask import Response
        result = read_source(source_id, cookies)
        if result.get("error") and not result.get("content"):
            return jsonify(result), 502
        filename = request.args.get("filename") or f"{source_id}.txt"
        content = result.get("content", "")
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/notebooks/<notebook_id>/archive", methods=["GET"])
    def export_notebook_archive(notebook_id: str):
        """Export a complete notebook archive — all data in one JSON response.

        Combines: summary (VfAZjd), sources + content (wXbhsf + tr032e),
        notes (gArtLc), conversation threads (hPTbtc + khqZz), mind map (cFji9).

        This is the canonical "download everything" endpoint for a single notebook.
        Source content reading is ON by default — disable with include_content=false
        for faster metadata-only export.

        Query params:
            include_content  — read full source text (default: true)
            include_threads  — read conversation threads (default: true)

        Returns: Full notebook archive JSON (notebook_id, notebook_name, summary,
                 sources, notes, threads, mindmap, stats, exported_at)
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        include_content = request.args.get("include_content", "true").lower() != "false"
        include_threads = request.args.get("include_threads", "true").lower() != "false"
        result = export_notebook(notebook_id, cookies, include_content, include_threads)
        return jsonify(result)

    @app.route("/notebooks/archive", methods=["GET"])
    def export_all_notebooks_archive():
        """Export all notebooks for the authenticated user as a single JSON archive.

        Lists all notebooks (ub2Bae) then exports each via export_notebook().
        Source content is OFF by default (metadata-only) for bulk exports since
        large accounts may have hundreds of sources.
        Enable with include_content=true but expect long response times.

        Query params:
            include_content  — read full source text per source (default: false)
            include_threads  — read conversation threads per notebook (default: true)

        Returns: {count, notebooks: [...], exported_at}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        include_content = request.args.get("include_content", "false").lower() == "true"
        include_threads = request.args.get("include_threads", "true").lower() != "false"
        result = export_all_notebooks(cookies, include_content, include_threads)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/notes", methods=["POST"])
    def create_note_route(notebook_id: str):
        """Create a new note (CYK0Xb). Also use to save AI response as a note.

        Body (JSON): {"title": "My Note", "content": "<p>html</p>"}
        Returns: {note_id, title, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        title = body.get("title", "New note")
        content = body.get("content", "")
        result = create_note(notebook_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result), 201

    @app.route("/notebooks/<notebook_id>/notes/<note_id>", methods=["PUT"])
    def save_note_route(notebook_id: str, note_id: str):
        """Save/update a note's content (cYAfTb live save).

        Body (JSON): {"title": "My Note", "content": "<p>updated html</p>"}
        Returns: {note_id, title, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        body = request.json or {}
        title = body.get("title", "")
        content = body.get("content", "")
        result = save_note(notebook_id, note_id, title, content, cookies)
        if result.get("error"):
            return jsonify(result), 502
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/notes/sync", methods=["GET"])
    def sync_notes_route(notebook_id: str):
        """Delta-sync notes since a timestamp (cFji9).

        Query params: ts_sec=<int>&ts_nano=<int> for continuation (omit for first call).
        Returns: {notes, next_timestamp, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        ts_sec = request.args.get("ts_sec")
        ts_nano = request.args.get("ts_nano")
        prev_ts = [int(ts_sec), int(ts_nano)] if ts_sec and ts_nano else None
        result = sync_notes(notebook_id, cookies, prev_timestamp=prev_ts)
        return jsonify(result)

    @app.route("/notebooks/<notebook_id>/audio-options", methods=["GET"])
    def audio_options_route(notebook_id: str):
        """List available audio overview formats (sqTeoe).

        Returns: {options: [{id, label, description}], status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_audio_options(notebook_id, cookies)
        return jsonify(result)

    @app.route("/sources/<source_id>/summary", methods=["GET"])
    def source_summary_route(source_id: str):
        """Get AI-generated markdown summary of a source (tr032e).

        Returns: {source_id, summary, status}
        """
        cookies = _cookies()
        if not cookies:
            return _no_cookies()
        result = get_source_summary(source_id, cookies)
        return jsonify(result)

    # ── Workspace Gemini Routes ───────────────────────────────────────────

    @app.route("/api/workspace/generate", methods=["POST"])
    def workspace_generate_route():
        """Stream-generate text via the Workspace Gemini backend.

        Body: {prompt, context?, document_type?}
        Returns: {text, model, usage, chunks}
        """
        from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
        body = request.json or {}
        prompt = body.get("prompt", "")
        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        client = get_workspace_gemini_client()
        if client is None:
            return jsonify({"error": "No Workspace Gemini account available"}), 503

        try:
            result = client.stream_generate(
                prompt=prompt,
                context=body.get("context"),
                document_type=body.get("document_type", "docs"),
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/search", methods=["POST"])
    def workspace_search_route():
        """AI Overview search across Google Drive.

        Body: {query, page_size?}
        Returns: {results, total}
        """
        from engine.integrations.google_drive_client import get_drive_client
        body = request.json or {}
        query = body.get("query", "")
        if not query:
            return jsonify({"error": "query is required"}), 400

        client = get_drive_client()
        if client is None:
            return jsonify({"error": "No Drive account available"}), 503

        try:
            result = client.ai_overview_search(
                query=query,
                page_size=body.get("page_size", 20),
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/ask", methods=["POST"])
    def workspace_ask_route():
        """Ask Gemini a question about Drive files.

        Body: {question, file_ids?, max_files?}
        Returns: {answer, sources, model, usage}
        """
        from engine.integrations.google_drive_client import get_drive_client
        body = request.json or {}
        question = body.get("question", "")
        if not question:
            return jsonify({"error": "question is required"}), 400

        client = get_drive_client()
        if client is None:
            return jsonify({"error": "No Drive account available"}), 503

        try:
            result = client.ask_gemini(
                question=question,
                file_ids=body.get("file_ids"),
                max_context_files=body.get("max_files", 10),
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/docs/create", methods=["POST"])
    def workspace_docs_create_route():
        """Create a Google Doc with optional Gemini content.

        Body: {title, prompt?, content?, folder_id?}
        Returns: {doc_id, title, url}
        """
        from engine.integrations.google_docs_client import get_docs_client
        body = request.json or {}
        title = body.get("title", "")
        if not title:
            return jsonify({"error": "title is required"}), 400

        client = get_docs_client()
        if client is None:
            return jsonify({"error": "No Docs account available"}), 503

        try:
            prompt = body.get("prompt", "")
            content = body.get("content", "")
            folder_id = body.get("folder_id")

            if prompt:
                result = client.create_with_gemini(title=title, prompt=prompt, folder_id=folder_id)
            else:
                result = client.create_doc(title=title, folder_id=folder_id)
                if content and result and result.get("documentId"):
                    client.append_to_doc(result["documentId"], content)

            doc_id = (result or {}).get("documentId", "")
            return jsonify({
                "doc_id": doc_id,
                "title": title,
                "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            }), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/sheets/create", methods=["POST"])
    def workspace_sheets_create_route():
        """Build a spreadsheet from a natural language prompt.

        Body: {title, prompt}
        Returns: {sheet_id, title, url}
        """
        from engine.integrations.gsheets_client import get_sheets_client
        body = request.json or {}
        prompt = body.get("prompt", "")
        title = body.get("title", "Untitled Sheet")
        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        client = get_sheets_client()
        if client is None:
            return jsonify({"error": "No Sheets account available"}), 503

        try:
            result = client.build_with_gemini(prompt=prompt, title=title)
            sheet_id = (result or {}).get("spreadsheetId", "")
            return jsonify({
                "sheet_id": sheet_id,
                "title": title,
                "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
            }), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/sheets/fill", methods=["POST"])
    def workspace_sheets_fill_route():
        """Fill a sheet range with Gemini-enriched data.

        Body: {sheet_id, range, prompt}
        Returns: {updated_range, values_written}
        """
        from engine.integrations.gsheets_client import get_sheets_client
        body = request.json or {}
        sheet_id = body.get("sheet_id", "")
        cell_range = body.get("range", "")
        prompt = body.get("prompt", "")

        if not all([sheet_id, cell_range, prompt]):
            return jsonify({"error": "sheet_id, range, and prompt are required"}), 400

        client = get_sheets_client()
        if client is None:
            return jsonify({"error": "No Sheets account available"}), 503

        try:
            result = client.fill_with_gemini(
                spreadsheet_id=sheet_id,
                cell_range=cell_range,
                prompt=prompt,
            )
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/pipeline", methods=["POST"])
    def workspace_pipeline_route():
        """Run a named Workspace pipeline template.

        Body: {template, topic?, ...params}
        Returns: PipelineRun dict
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        body = request.json or {}
        template = body.get("template", "")
        if not template:
            return jsonify({"error": "template is required"}), 400

        pipeline = get_workspace_pipeline()
        params = {k: v for k, v in body.items() if k != "template"}

        try:
            run = pipeline.run(template, **params)
            return jsonify(run.to_dict())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/workspace/pipeline/status/<run_id>", methods=["GET"])
    def workspace_pipeline_status_route(run_id: str):
        """Get status of a pipeline run.

        Returns: PipelineRun dict or 404
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        pipeline = get_workspace_pipeline()
        run = pipeline.get_run(run_id)
        if run is None:
            return jsonify({"error": f"Pipeline run {run_id} not found"}), 404
        return jsonify(run.to_dict())

    @app.route("/api/workspace/pipeline/templates", methods=["GET"])
    def workspace_pipeline_templates_route():
        """List available pipeline templates.

        Returns: {templates: {name: [stages]}}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        pipeline = get_workspace_pipeline()
        return jsonify({"templates": pipeline.list_templates()})

    @app.route("/api/workspace/status", methods=["GET"])
    def workspace_status_route():
        """Get Workspace integration status — available services and quota.

        Returns: {services, quota, registry}
        """
        from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
        from engine.integrations.workspace_rpc_registry import get_workspace_registry

        registry = get_workspace_registry()
        services = {
            "workspace_gemini": get_workspace_gemini_client() is not None,
        }
        try:
            from engine.integrations.gsheets_client import get_sheets_client
            services["sheets"] = get_sheets_client() is not None
        except Exception:
            services["sheets"] = False
        try:
            from engine.integrations.google_drive_client import get_drive_client
            services["drive"] = get_drive_client() is not None
        except Exception:
            services["drive"] = False
        try:
            from engine.integrations.google_docs_client import get_docs_client
            services["docs"] = get_docs_client() is not None
        except Exception:
            services["docs"] = False

        return jsonify({
            "services": services,
            "registry": registry.summary(),
        })

    @app.route("/api/workspace/news/fetch", methods=["POST"])
    def workspace_news_fetch_route():
        """Fetch news articles via RSS and optionally store in Nexus.

        Body: {categories?: ["ai_research","tech",...], max_articles?: 20, store?: true}
        Returns: {status, articles, categories}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(silent=True) or {}
        categories = data.get("categories", ["ai_research"])
        max_articles = data.get("max_articles", 20)
        store = data.get("store", True)

        pipeline = get_workspace_pipeline()
        try:
            run = pipeline.run_stages(
                [{"name": "fetch_news"}],
                topic=f"News fetch: {', '.join(categories)}",
                categories=categories,
                max_articles=max_articles,
                store_articles=store,
            )
            return jsonify(run.to_dict())
        except Exception as exc:
            logger.error("workspace news fetch failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/news/digest", methods=["POST"])
    def workspace_news_digest_route():
        """Run the full news pipeline: fetch → research → store.

        Body: {topic: str, sources?: [url,...]}
        Returns: Pipeline run result.
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(silent=True) or {}
        topic = data.get("topic", "latest AI news")
        sources = data.get("sources")

        pipeline = get_workspace_pipeline()
        try:
            run = pipeline.news_digest(topic=topic, sources=sources)
            return jsonify(run.to_dict())
        except Exception as exc:
            logger.error("workspace news digest failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── v1.19b Drive v2internal & Sheets Extended Routes ─────────────────

    @app.route("/api/workspace/drive/copy", methods=["POST"])
    def workspace_drive_copy_route():
        """Copy a Google Drive file via v2internal.

        Body: {file_id: str, title?: str, parent_id?: str, description?: str}
        Returns: New file metadata (id, title, alternateLink).
        """
        from engine.integrations.google_drive_client import get_drive_client

        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400

        try:
            client = get_drive_client()
            result = client.v2_copy_file(
                file_id=file_id,
                title=data.get("title"),
                parent_id=data.get("parent_id"),
                description=data.get("description"),
            )
            return jsonify(result)
        except Exception as exc:
            logger.error("workspace drive copy failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/drive/export", methods=["POST"])
    def workspace_drive_export_route():
        """Export a Google Workspace file to a different format.

        Body: {file_id: str, mime_type?: str}
        Returns: {content: str, size: int, mime_type: str, is_text: bool}
        """
        import base64

        from engine.integrations.google_drive_client import get_drive_client

        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400

        mime_type = data.get("mime_type", "text")
        try:
            client = get_drive_client()
            content = client.v2_export_file(file_id, mime_type)
            is_text = mime_type in ("text", "html", "csv", "text/plain", "text/html", "text/csv")
            payload = {
                "file_id": file_id,
                "mime_type": mime_type,
                "size": len(content),
                "is_text": is_text,
                "content": content.decode("utf-8", errors="replace") if is_text else base64.b64encode(content).decode(),
            }
            return jsonify(payload)
        except Exception as exc:
            logger.error("workspace drive export failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/drive/permissions", methods=["POST"])
    def workspace_drive_permissions_route():
        """Manage Drive file permissions via v2internal.

        Body: {file_id: str, action?: "list"|"set", role?: str,
               perm_type?: str, email?: str}
        Returns: Permission list or created permission.
        """
        from engine.integrations.google_drive_client import get_drive_client

        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400

        action = data.get("action", "list")
        try:
            client = get_drive_client()
            if action == "set":
                result = client.v2_insert_permission(
                    file_id=file_id,
                    role=data.get("role", "reader"),
                    perm_type=data.get("perm_type", "anyone"),
                    email=data.get("email"),
                    with_link=data.get("with_link", True),
                    send_notification=data.get("send_notification", False),
                )
                return jsonify({"permission": result, "action": "set"})
            else:
                perms = client.v2_get_permissions(file_id)
                return jsonify({"permissions": perms, "action": "list", "count": len(perms)})
        except Exception as exc:
            logger.error("workspace drive permissions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/workspace/sheets/revisions", methods=["GET"])
    def workspace_sheets_revisions_route():
        """Get revision history of a spreadsheet.

        Query: ?spreadsheet_id=...&max_results=50
        Returns: {revisions: [...], count: int}
        """
        from engine.integrations.gsheets_client import get_sheets_client

        spreadsheet_id = request.args.get("spreadsheet_id")
        if not spreadsheet_id:
            return jsonify({"error": "spreadsheet_id required"}), 400

        max_results = int(request.args.get("max_results", "50"))
        try:
            client = get_sheets_client()
            revisions = client.get_revision_history(spreadsheet_id, max_results=max_results)
            return jsonify({"revisions": revisions, "count": len(revisions)})
        except Exception as exc:
            logger.error("workspace sheets revisions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Colab Proxy Routes (v1.19c) ──────────────────────────────────────

    @app.route("/api/colab/ask", methods=["POST"])
    def colab_ask_route():
        """Ask the Colab Gemini agent a question.

        Body: {prompt: str, context?: str, timeout?: int}
        Returns: {answer: str, prompt: str}
        """
        from engine.integrations.colab_client import get_colab_client

        data = request.get_json(force=True)
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        context_text = data.get("context", "")
        timeout = int(data.get("timeout", 120))
        try:
            client = get_colab_client()
            answer = client.ask(prompt, context=context_text, timeout=timeout)
            return jsonify({"answer": answer, "prompt": prompt})
        except Exception as exc:
            logger.error("colab ask failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/colab/execute", methods=["POST"])
    def colab_execute_route():
        """Execute Python code in a Colab GPU runtime.

        Body: {code: str, timeout?: int}
        Returns: {output: str, success: bool, runtime_id: str}
        """
        from engine.integrations.colab_client import get_colab_client

        data = request.get_json(force=True)
        code = data.get("code")
        if not code:
            return jsonify({"error": "code required"}), 400

        timeout = int(data.get("timeout", 120))
        try:
            client = get_colab_client()
            result = client.run_python(code, timeout=timeout)
            return jsonify(result)
        except Exception as exc:
            logger.error("colab execute failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/colab/build", methods=["POST"])
    def colab_build_route():
        """Build a Colab notebook from a task description.

        Body: {task_description: str, timeout?: int}
        Returns: {task_id: str, status: str, notebook_content: str}
        """
        from engine.integrations.colab_client import get_colab_client
        import time as _time

        data = request.get_json(force=True)
        description = data.get("task_description")
        if not description:
            return jsonify({"error": "task_description required"}), 400

        timeout = int(data.get("timeout", 180))
        try:
            client = get_colab_client()
            task_id = client.create_task()
            client.update_task(task_id, description)

            deadline = _time.time() + timeout
            notebook_content = None
            while _time.time() < deadline:
                result = client.query_task(task_id)
                if result is not None:
                    notebook_content = result
                    break
                _time.sleep(3)

            if notebook_content is None:
                return jsonify({"task_id": task_id, "status": "timeout", "notebook_content": ""})
            return jsonify({"task_id": task_id, "status": "complete", "notebook_content": notebook_content})
        except Exception as exc:
            logger.error("colab build failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/colab/status", methods=["GET"])
    def colab_status_route():
        """Check Colab runtime status and user info.

        Returns: {user_info: dict, assignments: list}
        """
        from engine.integrations.colab_client import get_colab_client

        try:
            client = get_colab_client()
            user_info = client.get_user_info()
            assignments = client.list_assignments()
            return jsonify({
                "user_info": user_info,
                "assignments": assignments,
                "active_runtimes": len(assignments),
            })
        except Exception as exc:
            logger.error("colab status failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/colab/pipeline", methods=["POST"])
    def colab_pipeline_route():
        """Run a Colab-oriented workspace pipeline template.

        Body: {template: str, params: dict}
        Templates: research_and_compute, data_analysis, nlm_colab_loop, colab_build_and_store
        Returns: {results: list, stage_count: int, errors: list}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(force=True)
        template = data.get("template")
        if not template:
            return jsonify({"error": "template required"}), 400

        colab_templates = {"research_and_compute", "data_analysis", "nlm_colab_loop", "colab_build_and_store"}
        if template not in colab_templates:
            return jsonify({"error": f"Unknown Colab template. Choose from: {sorted(colab_templates)}"}), 400

        params = data.get("params", {})
        try:
            pipeline = get_workspace_pipeline()
            results = pipeline.run(template, params)
            errors = [r for r in results if "error" in r]
            return jsonify({"results": results, "stage_count": len(results), "errors": errors})
        except Exception as exc:
            logger.error("colab pipeline failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ──── AI Studio Routes (v1.21b) ────

    @app.route("/api/aistudio/generate", methods=["POST"])
    def aistudio_generate_route():
        """Generate content via AI Studio.

        Body: {prompt: str, model?: str, temperature?: float, max_tokens?: int, system_instruction?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        try:
            client = get_aistudio_client()
            result = client.generate_content(
                prompt,
                model_name=data.get("model"),
                temperature=data.get("temperature"),
                max_tokens=data.get("max_tokens"),
                system_instruction=data.get("system_instruction"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio generate failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/stream_generate", methods=["POST"])
    def aistudio_stream_generate_route():
        """Stream generated content via AI Studio.

        Body: {model: str, contents: list, generation_config?: dict, safety_settings?: list, system_instruction?: str}
        Returns: text/event-stream
        """
        from flask import Response
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        model = data.get("model")
        contents = data.get("contents")
        if not model or not contents:
            return jsonify({"error": "model and contents required"}), 400

        try:
            client = get_aistudio_client()
            stream = client.stream_generate_content(
                model,
                contents,
                generation_config=data.get("generation_config"),
                safety_settings=data.get("safety_settings"),
                system_instruction=data.get("system_instruction"),
            )

            def _generate():
                try:
                    for chunk in stream:
                        yield f"data: {json.dumps(chunk)}\n\n"
                except Exception as inner_exc:
                    yield f"data: {json.dumps({'error': str(inner_exc)})}\n\n"

            return Response(_generate(), mimetype="text/event-stream")
        except Exception as exc:
            logger.error("aistudio stream generate failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/models", methods=["GET"])
    def aistudio_models_route():
        """List available AI Studio models.

        Returns: {models: list}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        try:
            client = get_aistudio_client()
            models = client.list_models()
            return jsonify({"models": models})
        except Exception as exc:
            logger.error("aistudio list models failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/count_tokens", methods=["POST"])
    def aistudio_count_tokens_route():
        """Count tokens for content via AI Studio.

        Body: {model: str, contents: list}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        model = data.get("model")
        contents = data.get("contents")
        if not model or not contents:
            return jsonify({"error": "model and contents required"}), 400

        try:
            client = get_aistudio_client()
            result = client.count_tokens(model, contents)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio count tokens failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/embed", methods=["POST"])
    def aistudio_embed_route():
        """Generate embeddings via AI Studio.

        Body: {model: str, content: str, task_type?: str, title?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        model = data.get("model")
        content = data.get("content")
        if not model or not content:
            return jsonify({"error": "model and content required"}), 400

        try:
            client = get_aistudio_client()
            result = client.embed_content(
                model, content,
                task_type=data.get("task_type"),
                title=data.get("title"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio embed failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/batch_embed", methods=["POST"])
    def aistudio_batch_embed_route():
        """Batch embed content via AI Studio.

        Body: {model: str, requests: [{content: str, task_type?: str, title?: str}]}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        model = data.get("model")
        requests_list = data.get("requests")
        if not model or not requests_list:
            return jsonify({"error": "model and requests required"}), 400

        try:
            client = get_aistudio_client()
            result = client.batch_embed_contents(model, requests_list)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio batch embed failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/enhance_prompt", methods=["POST"])
    def aistudio_enhance_prompt_route():
        """Enhance a prompt via AI Studio.

        Body: {prompt: str, model?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        try:
            client = get_aistudio_client()
            result = client.enhance_prompt(prompt, model=data.get("model"))
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio enhance prompt failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/generate_image", methods=["POST"])
    def aistudio_generate_image_route():
        """Generate images via AI Studio.

        Body: {prompt: str, model?: str, n?: int, size?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        try:
            client = get_aistudio_client()
            result = client.generate_image(
                prompt,
                model=data.get("model"),
                n=data.get("n", 1),
                size=data.get("size"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio generate image failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/generate_video", methods=["POST"])
    def aistudio_generate_video_route():
        """Generate video via AI Studio.

        Body: {prompt: str, model?: str, duration?: int, aspect_ratio?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        try:
            client = get_aistudio_client()
            result = client.generate_video(
                prompt,
                model=data.get("model"),
                duration=data.get("duration"),
                aspect_ratio=data.get("aspect_ratio"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio generate video failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/tts", methods=["POST"])
    def aistudio_tts_route():
        """Text-to-speech via AI Studio.

        Body: {text: str, voice?: str, model?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        text = data.get("text")
        if not text:
            return jsonify({"error": "text required"}), 400

        try:
            client = get_aistudio_client()
            result = client.text_to_speech(
                text,
                voice=data.get("voice"),
                model=data.get("model"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio tts failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/stt", methods=["POST"])
    def aistudio_stt_route():
        """Speech-to-text via AI Studio.

        Body: {audio_data: str (base64), model?: str, language?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        audio_data = data.get("audio_data")
        if not audio_data:
            return jsonify({"error": "audio_data required"}), 400

        try:
            client = get_aistudio_client()
            result = client.gemini_speech_to_text(
                audio_data,
                model=data.get("model"),
                language=data.get("language"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio stt failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/prompts", methods=["GET"])
    def aistudio_list_prompts_route():
        """List saved AI Studio prompts.

        Query: page_size?, page_token?
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        page_size = request.args.get("page_size", type=int)
        page_token = request.args.get("page_token")
        try:
            client = get_aistudio_client()
            result = client.list_prompts(
                page_size=page_size,
                page_token=page_token,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio list prompts failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/prompts", methods=["POST"])
    def aistudio_create_prompt_route():
        """Create a saved prompt in AI Studio.

        Body: {display_name: str, prompt_data: dict}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        display_name = data.get("display_name")
        prompt_data = data.get("prompt_data")
        if not display_name or not prompt_data:
            return jsonify({"error": "display_name and prompt_data required"}), 400

        try:
            client = get_aistudio_client()
            result = client.create_prompt(display_name, prompt_data)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio create prompt failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/applets", methods=["GET"])
    def aistudio_list_applets_route():
        """List AI Studio applets.

        Query: page_size?, page_token?
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        page_size = request.args.get("page_size", type=int)
        page_token = request.args.get("page_token")
        try:
            client = get_aistudio_client()
            result = client.list_applets(
                page_size=page_size,
                page_token=page_token,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio list applets failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/applets", methods=["POST"])
    def aistudio_create_applet_route():
        """Create an AI Studio applet.

        Body: {display_name: str, code: str, model?: str, system_instruction?: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        display_name = data.get("display_name")
        code = data.get("code")
        if not display_name or not code:
            return jsonify({"error": "display_name and code required"}), 400

        try:
            client = get_aistudio_client()
            result = client.create_applet(
                display_name, code,
                model=data.get("model"),
                system_instruction=data.get("system_instruction"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio create applet failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/applets/deploy", methods=["POST"])
    def aistudio_deploy_applet_route():
        """Deploy an AI Studio applet.

        Body: {applet_name: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        applet_name = data.get("applet_name")
        if not applet_name:
            return jsonify({"error": "applet_name required"}), 400

        try:
            client = get_aistudio_client()
            result = client.deploy_applet(applet_name)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio deploy applet failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/files", methods=["GET"])
    def aistudio_list_files_route():
        """List files in AI Studio.

        Query: page_size?, page_token?
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        page_size = request.args.get("page_size", type=int)
        page_token = request.args.get("page_token")
        try:
            client = get_aistudio_client()
            result = client.list_files(
                page_size=page_size,
                page_token=page_token,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio list files failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/files", methods=["POST"])
    def aistudio_create_file_route():
        """Upload a file to AI Studio.

        Body: {display_name: str, file_data: str (base64), mime_type: str}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        display_name = data.get("display_name")
        file_data = data.get("file_data")
        mime_type = data.get("mime_type")
        if not display_name or not file_data or not mime_type:
            return jsonify({"error": "display_name, file_data, and mime_type required"}), 400

        try:
            client = get_aistudio_client()
            result = client.create_file(display_name, file_data, mime_type)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio create file failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/check_safety", methods=["POST"])
    def aistudio_check_safety_route():
        """Check content safety via AI Studio.

        Body: {content: str, safety_settings?: list}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        content = data.get("content")
        if not content:
            return jsonify({"error": "content required"}), 400

        try:
            client = get_aistudio_client()
            result = client.check_safety(
                content,
                safety_settings=data.get("safety_settings"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio check safety failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/batch_job", methods=["POST"])
    def aistudio_batch_job_route():
        """Create a batch processing job in AI Studio.

        Body: {model: str, input_config: dict, output_config: dict}
        Returns: {result: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        data = request.get_json(force=True)
        model = data.get("model")
        input_config = data.get("input_config")
        output_config = data.get("output_config")
        if not model or not input_config or not output_config:
            return jsonify({"error": "model, input_config, and output_config required"}), 400

        try:
            client = get_aistudio_client()
            result = client.create_batch_job(model, input_config, output_config)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("aistudio batch job failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/status", methods=["GET"])
    def aistudio_status_route():
        """Check AI Studio user status and quota.

        Returns: {user_status: dict, quota: dict}
        """
        from engine.integrations.aistudio_client import get_aistudio_client

        try:
            client = get_aistudio_client()
            user_status = client.check_user_status()
            quota = client.check_quota()
            return jsonify({"user_status": user_status, "quota": quota})
        except Exception as exc:
            logger.error("aistudio status failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/aistudio/pipeline", methods=["POST"])
    def aistudio_pipeline_route():
        """Run an AI Studio pipeline template.

        Body: {template: str, params: dict}
        Templates: generate_and_embed, safety_check_and_generate, batch_generate, prompt_enhance_and_run
        Returns: {results: list, stage_count: int, errors: list}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(force=True)
        template = data.get("template")
        if not template:
            return jsonify({"error": "template required"}), 400

        aistudio_templates = {
            "generate_and_embed", "safety_check_and_generate",
            "batch_generate", "prompt_enhance_and_run",
        }
        if template not in aistudio_templates:
            return jsonify({"error": f"Unknown AI Studio template. Choose from: {sorted(aistudio_templates)}"}), 400

        params = data.get("params", {})
        try:
            pipeline = get_workspace_pipeline()
            results = pipeline.run(template, params)
            errors = [r for r in results if "error" in r]
            return jsonify({"results": results, "stage_count": len(results), "errors": errors})
        except Exception as exc:
            logger.error("aistudio pipeline failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ──── Apps Script Routes (v1.21b) ────

    @app.route("/api/appscript/executions", methods=["GET"])
    def appscript_executions_route():
        """List recent Apps Script executions.

        Query params: project_id (required), max_results (default 50)
        Returns: {executions: [...]}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        max_results = int(request.args.get("max_results", 50))
        try:
            client = get_appscript_client()
            executions = client.list_executions(project_id, max_results=max_results)
            return jsonify({"executions": executions})
        except Exception as exc:
            logger.error("appscript list_executions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/run", methods=["POST"])
    def appscript_run_route():
        """Run a function in an Apps Script project.

        Body: {project_id: str, function_name: str, parameters?: list}
        Returns: {result: ...}
        """
        from engine.integrations.appscript_client import get_appscript_client

        data = request.get_json(force=True)
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400
        function_name = data.get("function_name")
        if not function_name:
            return jsonify({"error": "function_name required"}), 400

        parameters = data.get("parameters")
        try:
            client = get_appscript_client()
            result = client.run_function(project_id, function_name, parameters=parameters)
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("appscript run_function failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/project/files", methods=["GET"])
    def appscript_project_files_route():
        """Get files in an Apps Script project.

        Query params: project_id (required)
        Returns: {files: [...]}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        try:
            client = get_appscript_client()
            files = client.get_project_files(project_id)
            return jsonify({"files": files})
        except Exception as exc:
            logger.error("appscript get_project_files failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/project/info", methods=["GET"])
    def appscript_project_info_route():
        """Get Apps Script project info.

        Query params: project_id (required)
        Returns: {info: ...}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        try:
            client = get_appscript_client()
            info = client.get_project_info(project_id)
            return jsonify({"info": info})
        except Exception as exc:
            logger.error("appscript get_project_info failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/project/save", methods=["POST"])
    def appscript_project_save_route():
        """Save code to an Apps Script project file.

        Body: {project_id: str, file_id: str, code: str}
        Returns: {saved: true}
        """
        from engine.integrations.appscript_client import get_appscript_client

        data = request.get_json(force=True)
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400
        file_id = data.get("file_id")
        if not file_id:
            return jsonify({"error": "file_id required"}), 400
        code = data.get("code")
        if code is None:
            return jsonify({"error": "code required"}), 400

        try:
            client = get_appscript_client()
            client.save_code(project_id, file_id, code)
            return jsonify({"saved": True})
        except Exception as exc:
            logger.error("appscript save_code failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/triggers", methods=["GET"])
    def appscript_triggers_route():
        """List triggers for an Apps Script project.

        Query params: project_id (required)
        Returns: {triggers: [...]}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        try:
            client = get_appscript_client()
            triggers = client.list_triggers(project_id)
            return jsonify({"triggers": triggers})
        except Exception as exc:
            logger.error("appscript list_triggers failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/versions", methods=["GET"])
    def appscript_versions_route():
        """List versions of an Apps Script project.

        Query params: project_id (required), max_results (default 50)
        Returns: {versions: [...]}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        max_results = int(request.args.get("max_results", 50))
        try:
            client = get_appscript_client()
            versions = client.list_versions(project_id, max_results=max_results)
            return jsonify({"versions": versions})
        except Exception as exc:
            logger.error("appscript list_versions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/history", methods=["GET"])
    def appscript_history_route():
        """Get revision history for an Apps Script project.

        Query params: project_id (required), max_results (default 50)
        Returns: {history: [...]}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        max_results = int(request.args.get("max_results", 50))
        try:
            client = get_appscript_client()
            history = client.get_project_history(project_id, max_results=max_results)
            return jsonify({"history": history})
        except Exception as exc:
            logger.error("appscript get_project_history failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/pipeline", methods=["POST"])
    def appscript_pipeline_route():
        """Run an Apps Script pipeline template.

        Body: {template: str, params?: dict}
        Returns: {results: [...], stage_count: int, errors: [...]}
        """
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        data = request.get_json(force=True)
        template = data.get("template")
        if not template:
            return jsonify({"error": "template required"}), 400

        appscript_templates = {"appscript_automation", "appscript_deploy_and_test"}
        if template not in appscript_templates:
            return jsonify({"error": f"Unknown Apps Script template. Choose from: {sorted(appscript_templates)}"}), 400

        params = data.get("params", {})
        try:
            pipeline = get_workspace_pipeline()
            results = pipeline.run(template, params)
            errors = [r for r in results if "error" in r]
            return jsonify({"results": results, "stage_count": len(results), "errors": errors})
        except Exception as exc:
            logger.error("appscript pipeline failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/appscript/status", methods=["GET"])
    def appscript_status_route():
        """Combined Apps Script project info and metadata.

        Query params: project_id (required)
        Returns: {info: ..., metadata: ...}
        """
        from engine.integrations.appscript_client import get_appscript_client

        project_id = request.args.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        try:
            client = get_appscript_client()
            info = client.get_project_info(project_id)
            metadata = client.get_project_metadata(project_id)
            return jsonify({"info": info, "metadata": metadata})
        except Exception as exc:
            logger.error("appscript status failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── gRPC-web proxy routes (heap-discovered NLM methods) ──────────────
    # These routes delegate to NLMDirectClient which uses gRPC-web method
    # names rather than batchexecute rpcids.

    def _get_direct_client() -> Optional[Any]:
        """Lazy-import and return an NLMDirectClient, or None."""
        try:
            from engine.integrations.nlm_direct_client import get_nlm_direct_client
            return get_nlm_direct_client()
        except Exception as exc:
            logger.warning("Failed to get NLMDirectClient: %s", exc)
            return None

    def _no_direct_client():
        return jsonify({
            "error": "no_nlm_account",
            "detail": (
                "No NotebookLM account available for gRPC operations. "
                "Import an account via the account pool first."
            ),
        }), 503

    # ── Artifact routes ──────────────────────────────────────────────────

    @app.route("/api/grpc/artifact/create", methods=["POST"])
    def grpc_artifact_create():
        """Create a new artifact in a notebook via gRPC CreateArtifact.

        Body: {notebook_id, artifact_type?, title?, content?}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        try:
            result = client.create_artifact(
                notebook_id=notebook_id,
                artifact_type=body.get("artifact_type", "note"),
                title=body.get("title", ""),
                content=body.get("content", ""),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc artifact create failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/artifact/generate", methods=["POST"])
    def grpc_artifact_generate():
        """Generate an artifact from a prompt via gRPC GenerateArtifact.

        Body: {notebook_id, prompt, artifact_type?}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        prompt = body.get("prompt", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not prompt:
            return jsonify({"error": "prompt is required"}), 400
        try:
            result = client.generate_artifact(
                notebook_id=notebook_id,
                prompt=prompt,
                artifact_type=body.get("artifact_type", "note"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc artifact generate failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Source routes ─────────────────────────────────────────────────────

    @app.route("/api/grpc/source/freshness", methods=["POST"])
    def grpc_source_freshness():
        """Check source freshness via gRPC CheckSourceFreshness.

        Body: {notebook_id, source_ids?}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        try:
            result = client.check_source_freshness(
                notebook_id=notebook_id,
                source_ids=body.get("source_ids"),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc source freshness failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/source/discover", methods=["POST"])
    def grpc_source_discover():
        """Start async source discovery via gRPC DiscoverSourcesAsync.

        Body: {notebook_id, query, max_results?}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        query = body.get("query", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not query:
            return jsonify({"error": "query is required"}), 400
        try:
            result = client.discover_sources_async(
                notebook_id=notebook_id,
                query=query,
                max_results=body.get("max_results", 10),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc source discover failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/source/refresh", methods=["POST"])
    def grpc_source_refresh():
        """Refresh a source via gRPC RefreshSource.

        Body: {notebook_id, source_id}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        source_id = body.get("source_id", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not source_id:
            return jsonify({"error": "source_id is required"}), 400
        try:
            result = client.refresh_source(
                notebook_id=notebook_id,
                source_id=source_id,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc source refresh failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/source/mutate", methods=["POST"])
    def grpc_source_mutate():
        """Apply mutations to a source via gRPC MutateSource.

        Body: {notebook_id, source_id, mutations}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        source_id = body.get("source_id", "")
        mutations = body.get("mutations", {})
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not source_id:
            return jsonify({"error": "source_id is required"}), 400
        try:
            result = client.mutate_source(
                notebook_id=notebook_id,
                source_id=source_id,
                mutations=mutations,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc source mutate failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/source/delete-bulk", methods=["POST"])
    def grpc_source_delete_bulk():
        """Bulk-delete sources via gRPC DeleteSources.

        Body: {notebook_id, source_ids}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        source_ids = body.get("source_ids", [])
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not source_ids:
            return jsonify({"error": "source_ids is required"}), 400
        try:
            result = client.delete_sources_bulk(
                notebook_id=notebook_id,
                source_ids=source_ids,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc source delete-bulk failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Project routes ────────────────────────────────────────────────────

    @app.route("/api/grpc/project/mutate", methods=["POST"])
    def grpc_project_mutate():
        """Apply mutations to a project/notebook via gRPC MutateProject.

        Body: {notebook_id, mutations}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        mutations = body.get("mutations", {})
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        try:
            result = client.mutate_project(
                notebook_id=notebook_id,
                mutations=mutations,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc project mutate failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Chat routes ───────────────────────────────────────────────────────

    @app.route("/api/grpc/chat/sessions", methods=["POST"])
    def grpc_chat_sessions():
        """List chat sessions in a notebook via gRPC ListChatSessions.

        Body: {notebook_id}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        try:
            result = client.list_chat_sessions(
                notebook_id=notebook_id,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc chat sessions failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/chat/delete-turns", methods=["POST"])
    def grpc_chat_delete_turns():
        """Delete specific chat turns via gRPC DeleteChatTurns.

        Body: {notebook_id, turn_ids}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        turn_ids = body.get("turn_ids", [])
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not turn_ids:
            return jsonify({"error": "turn_ids is required"}), 400
        try:
            result = client.delete_chat_turns(
                notebook_id=notebook_id,
                turn_ids=turn_ids,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc chat delete-turns failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Note routes ───────────────────────────────────────────────────────

    @app.route("/api/grpc/note/mutate", methods=["POST"])
    def grpc_note_mutate():
        """Apply mutations to a note via gRPC MutateNote.

        Body: {notebook_id, note_id, mutations}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        note_id = body.get("note_id", "")
        mutations = body.get("mutations", {})
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        if not note_id:
            return jsonify({"error": "note_id is required"}), 400
        try:
            result = client.mutate_note(
                notebook_id=notebook_id,
                note_id=note_id,
                mutations=mutations,
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc note mutate failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Account routes ────────────────────────────────────────────────────

    @app.route("/api/grpc/account", methods=["GET"])
    def grpc_account():
        """Get or create the NLM account via gRPC GetOrCreateAccount.

        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        try:
            result = client.get_or_create_account()
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc account failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    # ── Suggestion routes ─────────────────────────────────────────────────

    @app.route("/api/grpc/suggestions/prompts", methods=["POST"])
    def grpc_suggestions_prompts():
        """Generate prompt suggestions via gRPC GeneratePromptSuggestions.

        Body: {notebook_id, context?, count?}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        try:
            result = client.generate_prompt_suggestions(
                notebook_id=notebook_id,
                context=body.get("context", ""),
                count=body.get("count", 5),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc suggestions prompts failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/grpc/suggestions/reports", methods=["POST"])
    def grpc_suggestions_reports():
        """Generate report suggestions via gRPC GenerateReportSuggestions.

        Body: {notebook_id, report_type?, context?}
        Returns: {result: ...}
        """
        client = _get_direct_client()
        if client is None:
            return _no_direct_client()
        body = request.get_json(force=True, silent=True) or {}
        notebook_id = body.get("notebook_id", "")
        if not notebook_id:
            return jsonify({"error": "notebook_id is required"}), 400
        try:
            result = client.generate_report_suggestions(
                notebook_id=notebook_id,
                report_type=body.get("report_type", "summary"),
                context=body.get("context", ""),
            )
            return jsonify({"result": result})
        except Exception as exc:
            logger.error("grpc suggestions reports failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

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
                _nlm_auth._COOKIES_FILE,
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
    logger.info("Cookie file: %s", _nlm_auth._COOKIES_FILE)
    logger.info("To import cookies: POST /cookies/import with {har_path: '...'}")
    create_nlm_proxy_app().run(
        host="0.0.0.0", port=port, debug=False, threaded=True
    )
