"""sync_sessions_to_nexus.py — Bulk-sync Copilot CLI session history to Nexus KMS.

Reads sessions from the Copilot session store SQLite database
(~/.copilot/session-store.db) and syncs them to Nexus as
copilot-history entries with full checkpoint, file-change, and summary data.

Uses hash-based change detection — already-synced unchanged sessions are
skipped unless --force is passed.

Usage:
    python engine/nexus/sync_sessions_to_nexus.py              # last 30 days
    python engine/nexus/sync_sessions_to_nexus.py --days 7     # last 7 days
    python engine/nexus/sync_sessions_to_nexus.py --session <id>  # one session
    python engine/nexus/sync_sessions_to_nexus.py --all --force   # full re-sync
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8700")
# Actual path: ~/.copilot/session-store.db (flat file, no subdirectory)
SESSION_STORE_DB = Path.home() / ".copilot" / "session-store.db"
STATE_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / ".github"
    / "hooks"
    / "logs"
    / "session_sync.json"
)


# ── Nexus helpers ─────────────────────────────────────────────────────────────


def _post_nexus(path: str, data: Dict[str, Any], timeout: int = 8) -> Optional[Dict]:
    """POST to Nexus API. Returns response dict or None on failure."""
    try:
        url = f"{NEXUS_URL}/api{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.debug("Nexus POST %s failed: %s", path, exc)
        return None


# ── State helpers ─────────────────────────────────────────────────────────────


def _load_state() -> Dict[str, Any]:
    """Load sync state tracking which sessions have been synced."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"synced": {}}


def _save_state(state: Dict[str, Any]) -> None:
    """Persist sync state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Session store queries ─────────────────────────────────────────────────────


def _get_sessions(
    days: Optional[int] = 30,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read sessions from the Copilot session store SQLite database.

    Args:
        days: Limit to last N days. None = all sessions.
        session_id: Return only this specific session ID.

    Returns:
        List of session metadata dicts ordered newest-first.
    """
    if not SESSION_STORE_DB.exists():
        logger.warning("Session store not found: %s", SESSION_STORE_DB)
        return []

    sessions: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{SESSION_STORE_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            query = (
                "SELECT id, cwd, repository, branch, summary, created_at, updated_at "
                "FROM sessions"
            )
            params: List[Any] = []

            if session_id:
                query += " WHERE id = ?"
                params.append(session_id)
            elif days is not None:
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=days)
                ).isoformat()
                query += " WHERE created_at >= ?"
                params.append(cutoff)

            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            for row in rows:
                sessions.append({
                    "id": row["id"],
                    "cwd": row["cwd"] or "",
                    "repository": row["repository"] or "",
                    "branch": row["branch"] or "",
                    "summary": row["summary"] or "",
                    "created_at": row["created_at"] or "",
                    "updated_at": row["updated_at"] or "",
                })
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Failed to read session store: %s", exc)

    return sessions


def _get_session_detail(session_id: str) -> Dict[str, Any]:
    """Return full detail for one session: checkpoints, files, turn count, refs."""
    detail: Dict[str, Any] = {
        "checkpoints": [], "files": [], "refs": [], "turn_count": 0,
    }

    if not SESSION_STORE_DB.exists():
        return detail

    try:
        conn = sqlite3.connect(f"file:{SESSION_STORE_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            cps = conn.execute(
                "SELECT checkpoint_number, title, overview, work_done, "
                "technical_details, next_steps "
                "FROM checkpoints WHERE session_id = ? ORDER BY checkpoint_number",
                (session_id,),
            ).fetchall()
            detail["checkpoints"] = [
                {
                    "number": r["checkpoint_number"],
                    "title": r["title"] or "",
                    "overview": (r["overview"] or "")[:800],
                    "work_done": (r["work_done"] or "")[:800],
                    "technical_details": (r["technical_details"] or "")[:500],
                    "next_steps": (r["next_steps"] or "")[:400],
                }
                for r in cps
            ]

            files = conn.execute(
                "SELECT file_path, tool_name FROM session_files "
                "WHERE session_id = ? ORDER BY first_seen_at",
                (session_id,),
            ).fetchall()
            detail["files"] = [
                {"path": r["file_path"], "action": r["tool_name"]}
                for r in files
            ]

            count_row = conn.execute(
                "SELECT COUNT(*) FROM turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            detail["turn_count"] = count_row[0] if count_row else 0

            refs = conn.execute(
                "SELECT ref_type, ref_value FROM session_refs WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            detail["refs"] = [
                {"type": r["ref_type"], "value": r["ref_value"]} for r in refs
            ]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Detail query failed for %s: %s", session_id[:8], exc)

    return detail


# ── Entry building ────────────────────────────────────────────────────────────


def _build_nexus_content(
    session: Dict[str, Any],
    detail: Dict[str, Any],
) -> str:
    """Build a rich Markdown content string for the Nexus entry."""
    short_id = session["id"][:8]
    lines = [
        f"# Session {short_id}",
        f"Date: {session['created_at'][:19]}",
        f"Repo: {session['repository'] or session['cwd']}",
        f"Branch: {session['branch']}",
        f"Turns: {detail['turn_count']}  Files: {len(detail['files'])}",
    ]

    if session["summary"]:
        lines += ["", "## Summary", session["summary"]]

    if detail["checkpoints"]:
        lines += [f"", f"## Checkpoints ({len(detail['checkpoints'])})"]
        for cp in detail["checkpoints"]:
            lines.append(f"\n### [{cp['number']}] {cp['title']}")
            if cp["overview"]:
                lines.append(cp["overview"])
            if cp["work_done"]:
                lines += ["\n**Work Done:**", cp["work_done"]]
            if cp["next_steps"]:
                lines += ["\n**Next Steps:**", cp["next_steps"]]
            if cp["technical_details"]:
                lines += ["\n**Technical:**", cp["technical_details"]]

    if detail["files"]:
        edited = [f["path"] for f in detail["files"] if f["action"] == "edit"]
        created = [f["path"] for f in detail["files"] if f["action"] == "create"]
        if edited:
            lines += ["", "## Files Edited"]
            lines += [f"- {p}" for p in edited[:25]]
        if created:
            lines += ["", "## Files Created"]
            lines += [f"- {p}" for p in created[:15]]

    if detail.get("refs"):
        lines += ["", "## References"]
        for r in detail["refs"]:
            lines.append(f"- {r['type']}: {r['value']}")

    return "\n".join(lines)


def _session_hash(session: Dict[str, Any], detail: Dict[str, Any]) -> str:
    """Compute a content hash to detect session changes."""
    payload = json.dumps({
        "summary": session.get("summary"),
        "updated_at": session.get("updated_at"),
        "checkpoints": len(detail.get("checkpoints", [])),
        "files": len(detail.get("files", [])),
        "turns": detail.get("turn_count", 0),
    }, sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()


# ── Sync logic ────────────────────────────────────────────────────────────────


def sync_session(
    session: Dict[str, Any],
    state: Dict[str, Any],
    force: bool = False,
) -> bool:
    """Sync a single session to Nexus.

    Args:
        session: Session metadata dict from session store.
        state: Sync state dict (mutated in place with new sync record).
        force: Re-sync even if hash is unchanged.

    Returns:
        True if entry was posted to Nexus, False if skipped.
    """
    session_id = session["id"]
    short_id = session_id[:8]
    detail = _get_session_detail(session_id)
    new_hash = _session_hash(session, detail)

    if not force and state["synced"].get(session_id, {}).get("hash") == new_hash:
        logger.debug("Session %s unchanged — skipping", short_id)
        return False

    content = _build_nexus_content(session, detail)
    cp_count = len(detail["checkpoints"])
    title_base = (
        session["summary"][:60] if session["summary"]
        else f"{session['branch']} ({cp_count} checkpoints)"
    )
    title = f"Session {short_id}: {title_base}"

    entry = {
        "title": title,
        "content": content,
        "content_type": "history",
        "category": "copilot-history",
        "tags": [
            "copilot", "session", f"session-{short_id}",
            session["branch"] or "master",
            session["repository"] or "cosysim",
        ],
    }

    result = _post_nexus("/entries", entry)
    if result:
        state["synced"][session_id] = {
            "hash": new_hash,
            "nexus_id": result.get("id"),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Synced session %s → Nexus #%s", short_id, result.get("id"))
        return True

    logger.warning("Failed to sync session %s", short_id)
    return False


def sync_all(
    days: Optional[int] = 30,
    session_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, int]:
    """Sync Copilot session history to Nexus.

    Args:
        days: Sync sessions from last N days. None = all sessions.
        session_id: Sync only this specific session ID.
        force: Re-sync sessions even if hash is unchanged.

    Returns:
        Dict with: total, synced, skipped, failed counts.
    """
    sessions = _get_sessions(days=days, session_id=session_id)
    if not sessions:
        logger.info("No sessions found to sync.")
        return {"total": 0, "synced": 0, "skipped": 0, "failed": 0}

    logger.info("Found %d session(s) to process.", len(sessions))
    state = _load_state()

    synced = skipped = failed = 0
    for sess in sessions:
        try:
            if sync_session(sess, state, force=force):
                synced += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("Error syncing %s: %s", sess["id"][:8], exc)
            failed += 1

    _save_state(state)
    logger.info(
        "Sync complete: %d synced, %d skipped, %d failed (total=%d).",
        synced, skipped, failed, len(sessions),
    )
    return {
        "total": len(sessions), "synced": synced,
        "skipped": skipped, "failed": failed,
    }


# ── Scheduler callback ────────────────────────────────────────────────────────


def run_session_sync() -> Dict[str, int]:
    """Scheduler callback: sync last 7 days of sessions to Nexus."""
    return sync_all(days=7)


# ── CLI ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Copilot sessions to Nexus")
    parser.add_argument("--session", help="Sync a specific session ID")
    parser.add_argument(
        "--days", type=int, default=30,
        help="Sync sessions from last N days (default: 30)",
    )
    parser.add_argument("--all", action="store_true", help="Sync all sessions")
    parser.add_argument("--force", action="store_true", help="Re-sync unchanged sessions")
    args = parser.parse_args()

    result = sync_all(
        days=None if args.all else args.days,
        session_id=args.session,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
