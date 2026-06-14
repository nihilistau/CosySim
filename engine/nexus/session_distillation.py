"""session_distillation.py — Distills Copilot session history into NLM notebooks.

Version: v1.50.2 [2026-03-24]

Change Log:
    v1.50.2 [2026-03-24] — Replace raw urllib.request with governed get_nexus_client()

Pipeline (runs daily via scheduler):
  1. Fetch recent session history entries from Nexus (copilot-history category)
  2. Build a digest document from checkpoints, decisions, and patterns
  3. Upload digest to the `copilot-session-history` NLM notebook
  4. Ask targeted distillation questions via NLM batch chat
  5. Store the Q&A pairs back in Nexus (copilot-decisions category)

This creates a compounding knowledge loop:
  Session work → Nexus history → NLM digest → Q&A pairs → Nexus decisions
  → Future Copilot sessions query decisions before coding
  → Better decisions, less rework, growing institutional memory

Usage:
    python engine/nexus/session_distillation.py              # run pipeline
    python engine/nexus/session_distillation.py --upload-only  # only update notebook
    python engine/nexus/session_distillation.py --distill-only # only ask questions
    python engine/nexus/session_distillation.py --days 14      # cover last 14 days
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def _get_nexus_url() -> str:
    env = os.environ.get("NEXUS_URL")
    if env:
        return env
    from engine.port_registry import get_service_url
    return get_service_url("nexus")


def _get_nlm_proxy_url() -> str:
    env = os.environ.get("NLM_PROXY_URL")
    if env:
        return env
    from engine.port_registry import get_service_url
    return get_service_url("nlm_proxy")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_FILE = (
    REPO_ROOT / ".github" / "hooks" / "logs" / "session_distillation.json"
)

# Name of the NLM notebook to update with session history
SESSION_HISTORY_NOTEBOOK = "copilot-session-history"

# Questions asked after uploading fresh session digests
DISTILLATION_QUESTIONS: List[str] = [
    "What architectural decisions were made in recent sessions and what were the reasons?",
    "What recurring patterns emerge in how the CosySim system is being improved?",
    "What bugs or issues were fixed, and what root causes were identified?",
    "What new modules, skills, or MCP tools were added to the system?",
    "What testing strategies and mock patterns were established or refined?",
    "What are the key learnings about NLM and Nexus integration from recent sessions?",
    "What performance benchmarks or improvements were recorded?",
    "What knowledge workflows — seeding, distillation, query routing — were created or improved?",
    "What are the most important open questions or next steps surfaced in recent sessions?",
    "What coding conventions or standards were explicitly codified?",
    "What scheduler tasks, daemon callbacks, or automated processes were added?",
    "What mistakes or dead ends were encountered and how were they resolved?",
]


# ── Nexus helpers (governed client) ───────────────────────────────────────────
# v1.50.2 [2026-03-24] — Replaced raw urllib.request with governed get_nexus_client()
# CONNECTS: NexusClient — ensures embedding hooks, governance, and error aggregation


def _nexus_get(path: str, timeout: int = 8) -> Optional[Any]:
    """GET from Nexus API via governed client. Returns parsed JSON or None."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        # Route based on path pattern
        if "/search" in path:
            # Parse query params from path
            import urllib.parse
            parts = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parts.query)
            q = params.get("q", [""])[0].replace("+", " ")
            limit = int(params.get("limit", ["20"])[0])
            return client.search(q, limit=limit)
        if "/qa" in path:
            return client.find_qa("", limit=20)
        if "/entries" in path:
            return client.list_entries(limit=20)
        return None
    except Exception as exc:
        logger.debug("[SessionDistillation] Nexus GET %s failed (operation=fetch): %s", path, exc)
        return None


def _nexus_post(path: str, data: Dict[str, Any], timeout: int = 8) -> Optional[Dict]:
    """POST to Nexus API via governed client. Returns response dict or None."""
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if "/qa" in path:
            result = client.add_qa(
                question=data.get("question", ""),
                answer=data.get("answer", ""),
                category=data.get("category", ""),
                tags=data.get("tags", []),
            )
            return {"id": result, "ok": bool(result)} if result else None
        if "/entries" in path:
            result = client.add_entry(
                title=data.get("title", ""),
                content=data.get("content", ""),
                content_type=data.get("content_type", "note"),
                category=data.get("category", ""),
                tags=data.get("tags", []),
            )
            return {"id": result, "ok": bool(result)} if result else None
        return None
    except Exception as exc:
        logger.debug("[SessionDistillation] Nexus POST %s failed (operation=store): %s", path, exc)
        return None


def _nlm_post(path: str, data: Dict[str, Any], timeout: int = 60) -> Optional[Dict]:
    """POST to NLM proxy. Returns response dict or None."""
    try:
        url = f"{_get_nlm_proxy_url()}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.debug("NLM POST %s failed: %s", path, exc)
        return None


def _nlm_get(path: str, timeout: int = 10) -> Optional[Any]:
    """GET from NLM proxy. Returns parsed JSON or None."""
    try:
        url = f"{_get_nlm_proxy_url()}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.debug("NLM GET %s failed: %s", path, exc)
        return None


# ── State helpers ─────────────────────────────────────────────────────────────


def _load_state() -> Dict[str, Any]:
    """Load distillation run state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "last_run": None,
        "last_notebook_id": None,
        "last_source_id": None,
        "total_qa_stored": 0,
    }


def _save_state(state: Dict[str, Any]) -> None:
    """Persist distillation state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Nexus data fetching ───────────────────────────────────────────────────────


def _fetch_session_history(days: int = 7) -> List[Dict[str, Any]]:
    """Fetch recent session history entries from Nexus.

    Args:
        days: How many days back to fetch.

    Returns:
        List of Nexus entry dicts with title and content.
    """
    result = _nexus_get(
        f"/search?q=copilot+session&category=copilot-history&limit=20&content_type=history"
    )
    if not result:
        return []

    entries = result.get("results", result if isinstance(result, list) else [])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Filter to recent entries
    recent = []
    for e in entries:
        created = e.get("created_at", "")
        if created >= cutoff or not created:
            recent.append(e)

    logger.info("Fetched %d session history entries from Nexus.", len(recent))
    return recent


def _fetch_decisions(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch existing copilot decisions from Nexus (to avoid duplication)."""
    result = _nexus_get("/search?q=decision&category=copilot-decisions&limit=20")
    if not result:
        return []
    return result.get("results", result if isinstance(result, list) else [])


# ── Digest building ───────────────────────────────────────────────────────────


def _build_digest(
    history_entries: List[Dict[str, Any]],
    days: int = 7,
) -> str:
    """Build a consolidated digest document from session history entries.

    Args:
        history_entries: List of Nexus session history entries.
        days: Number of days covered (for the header).

    Returns:
        Markdown string suitable for NLM source upload.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# CosySim Session History Digest ({now})",
        f"Period: last {days} days | Sessions: {len(history_entries)}",
        "",
        "This document is a consolidated digest of recent Copilot development sessions.",
        "It captures architectural decisions, code changes, bug fixes, and patterns.",
        "",
        "---",
    ]

    for entry in history_entries:
        title = entry.get("title", "Unknown Session")
        content = entry.get("content", "")
        if content:
            lines += ["", f"## {title}", content]

    if not history_entries:
        lines += [
            "",
            "No session history entries found for this period.",
            "Sessions are synced to Nexus via sync_sessions_to_nexus.py.",
        ]

    return "\n".join(lines)


# ── NLM notebook management ───────────────────────────────────────────────────


def _find_session_history_notebook() -> Optional[str]:
    """Find the copilot-session-history NLM notebook. Returns ID or None."""
    notebooks = _nlm_get("/notebooks")
    if not notebooks:
        return None

    nb_list = notebooks if isinstance(notebooks, list) else notebooks.get("notebooks", [])
    for nb in nb_list:
        name = (nb.get("name") or nb.get("title") or "").lower()
        if "session" in name and ("history" in name or "copilot" in name):
            return nb.get("id") or nb.get("notebook_id")

    return None


def _create_session_history_notebook() -> Optional[str]:
    """Create the copilot-session-history NLM notebook."""
    result = _nlm_post(
        "/notebooks",
        {
            "name": "CosySim Copilot Session History",
            "description": (
                "Consolidated digest of all Copilot development sessions. "
                "Contains architectural decisions, code changes, bug fixes, "
                "and patterns from recent work sessions."
            ),
        },
    )
    if result:
        nb_id = result.get("id") or result.get("notebook_id")
        logger.info("Created session history notebook: %s", nb_id)
        return nb_id
    return None


def _upload_digest_to_notebook(notebook_id: str, digest: str) -> Optional[str]:
    """Upload the session digest as a text source to the NLM notebook.

    Args:
        notebook_id: Target notebook ID.
        digest: Markdown digest text.

    Returns:
        Source ID if successful, None otherwise.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = _nlm_post(
        f"/notebooks/{notebook_id}/sources",
        {
            "type": "text",
            "title": f"Session Digest {now}",
            "content": digest[:50000],  # NLM source size limit
        },
    )
    if result:
        src_id = result.get("id") or result.get("source_id")
        logger.info("Uploaded digest to notebook %s as source %s", notebook_id, src_id)
        return src_id

    logger.warning("Failed to upload digest to notebook %s", notebook_id)
    return None


# ── Q&A distillation ─────────────────────────────────────────────────────────


def _ask_distillation_questions(
    notebook_id: str,
    questions: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Ask distillation questions to the NLM notebook.

    Args:
        notebook_id: NLM notebook ID containing session history.
        questions: Questions to ask. Defaults to DISTILLATION_QUESTIONS.

    Returns:
        List of {question, answer} dicts.
    """
    if questions is None:
        questions = DISTILLATION_QUESTIONS

    result = _nlm_post(
        f"/notebooks/{notebook_id}/chat_batch",
        {"questions": questions},
        timeout=120,
    )

    if not result:
        logger.warning("NLM batch chat returned no results for notebook %s", notebook_id)
        return []

    qa_pairs = []
    results_list = result.get("results", [])
    for item in results_list:
        answer = item.get("answer", "").strip()
        question = item.get("question", "").strip()
        if answer and question and len(answer) > 20:
            qa_pairs.append({"question": question, "answer": answer})

    logger.info("Got %d Q&A pairs from NLM distillation.", len(qa_pairs))
    return qa_pairs


# ── Nexus storage ─────────────────────────────────────────────────────────────


def _store_qa_pairs(qa_pairs: List[Dict[str, str]]) -> int:
    """Store Q&A pairs in Nexus as copilot-decisions entries.

    Args:
        qa_pairs: List of {question, answer} dicts.

    Returns:
        Number of pairs successfully stored.
    """
    stored = 0
    for qa in qa_pairs:
        result = _nexus_post(
            "/qa",
            {
                "question": qa["question"],
                "answer": qa["answer"],
                "category": "copilot-decisions",
                "tags": ["copilot", "session-distillation", "auto-generated"],
                "source": "session-distillation-pipeline",
            },
        )
        if result:
            stored += 1
        else:
            # Fallback: store as knowledge entry
            _nexus_post(
                "/entries",
                {
                    "title": f"Decision: {qa['question'][:80]}",
                    "content": f"**Q:** {qa['question']}\n\n**A:** {qa['answer']}",
                    "content_type": "note",
                    "category": "copilot-decisions",
                    "tags": ["copilot", "decision", "session-distillation"],
                },
            )
            stored += 1

    logger.info("Stored %d Q&A pairs in Nexus.", stored)
    return stored


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run_distillation(
    days: int = 7,
    upload_only: bool = False,
    distill_only: bool = False,
) -> Dict[str, Any]:
    """Run the full session → NLM → Nexus distillation pipeline.

    Args:
        days: Fetch session history from last N days.
        upload_only: Only upload digest to NLM, skip distillation.
        distill_only: Only ask questions (assume notebook already has content).

    Returns:
        Dict with pipeline stats: history_entries, notebook_id, source_id,
        qa_pairs, qa_stored.
    """
    state = _load_state()
    stats: Dict[str, Any] = {
        "history_entries": 0, "notebook_id": None,
        "source_id": None, "qa_pairs": 0, "qa_stored": 0,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    # Step 1: Find or create the session history notebook
    notebook_id = state.get("last_notebook_id")
    if not distill_only:
        notebook_id = _find_session_history_notebook()
        if not notebook_id:
            logger.info("Session history notebook not found — creating...")
            notebook_id = _create_session_history_notebook()

    if not notebook_id:
        logger.error(
            "Cannot proceed: NLM proxy unavailable or notebook creation failed. "
            "Start the NLM proxy at %s first.", _get_nlm_proxy_url()
        )
        stats["error"] = "NLM proxy unavailable"
        return stats

    stats["notebook_id"] = notebook_id

    if not distill_only:
        # Step 2: Fetch session history from Nexus
        history_entries = _fetch_session_history(days=days)
        stats["history_entries"] = len(history_entries)

        # Step 3: Build digest and upload
        digest = _build_digest(history_entries, days=days)
        source_id = _upload_digest_to_notebook(notebook_id, digest)
        stats["source_id"] = source_id

        if source_id:
            state["last_source_id"] = source_id
        state["last_notebook_id"] = notebook_id

    if not upload_only:
        # Step 4: Ask distillation questions
        qa_pairs = _ask_distillation_questions(notebook_id)
        stats["qa_pairs"] = len(qa_pairs)

        if qa_pairs:
            # Step 5: Store Q&A in Nexus
            stored = _store_qa_pairs(qa_pairs)
            stats["qa_stored"] = stored
            state["total_qa_stored"] = state.get("total_qa_stored", 0) + stored

    state["last_run"] = stats["run_at"]
    _save_state(state)

    logger.info(
        "Session distillation complete: %d history entries, %d Q&A pairs → %d stored.",
        stats.get("history_entries", 0),
        stats.get("qa_pairs", 0),
        stats.get("qa_stored", 0),
    )
    return stats


# ── Scheduler callback ────────────────────────────────────────────────────────


def run_session_distillation() -> Dict[str, Any]:
    """Scheduler callback: run daily session distillation pipeline."""
    return run_distillation(days=7)


# ── CLI ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Distill session history into NLM notebooks")
    parser.add_argument("--days", type=int, default=7, help="Days of history to process")
    parser.add_argument("--upload-only", action="store_true", help="Only upload digest to NLM")
    parser.add_argument("--distill-only", action="store_true", help="Only ask distillation questions")
    args = parser.parse_args()

    result = run_distillation(
        days=args.days,
        upload_only=args.upload_only,
        distill_only=args.distill_only,
    )
    print(json.dumps(result, indent=2))
