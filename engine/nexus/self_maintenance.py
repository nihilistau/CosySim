"""
Nexus Self-Maintenance — Automated knowledge base health and quality management.

Provides scheduled tasks for deduplication, compaction, health monitoring,
and quality scoring of Nexus knowledge entries.  Can be run as a standalone
CLI or integrated via the CosySim MCP server.

Usage:
    python -m engine.nexus.self_maintenance [action]

Actions:
    health       — Full health report (entry counts, duplicates, staleness)
    dedup        — Deduplicate similar entries (dry-run by default)
    dedup --apply — Actually merge duplicates
    compact      — Compact old session logs into summaries
    score        — Score knowledge entries by quality and flag low-quality
    full         — Run all maintenance tasks
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _get_client():
    """Get a NexusClient instance."""
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


# ── Health Report ───────────────────────────────────────────────────────

def nexus_health_report() -> Dict[str, Any]:
    """Generate a comprehensive health report for the Nexus knowledge base.

    Returns:
        Dict with counts, quality metrics, and recommendations.
    """
    client = _get_client()
    report: Dict[str, Any] = {
        "timestamp": time.time(),
        "status": "unknown",
        "metrics": {},
        "issues": [],
        "recommendations": [],
    }

    # Check availability
    if not client.is_available():
        report["status"] = "offline"
        report["issues"].append("Nexus API is unreachable")
        return report

    try:
        stats = client.stats()
    except Exception as exc:
        report["status"] = "error"
        report["issues"].append(f"Failed to get stats: {exc}")
        return report

    report["status"] = "healthy"
    report["metrics"] = {
        "total_entries": stats.get("total_entries", 0),
        "total_qa": stats.get("total_qa", 0),
        "total_sessions": stats.get("total_sessions", 0),
        "total_rules": stats.get("total_rules", 0),
        "total_prompts": stats.get("total_prompts", 0),
    }

    # Check for issues
    total = report["metrics"]["total_entries"]
    if total == 0:
        report["issues"].append("Knowledge base is empty")
        report["recommendations"].append("Seed knowledge base with project documentation")

    # Check entry distribution by type
    for content_type in ["note", "memory", "history", "code", "document"]:
        try:
            entries = client.list_entries(content_type=content_type, limit=1)
            report["metrics"][f"count_{content_type}"] = len(entries)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    # Check for potential duplicates
    try:
        all_entries = client.list_entries(limit=100)
        titles = [e.get("title", "") for e in all_entries]
        title_counts = defaultdict(int)
        for t in titles:
            title_counts[t.lower().strip()] += 1
        dupes = {t: c for t, c in title_counts.items() if c > 1}
        if dupes:
            report["metrics"]["potential_duplicates"] = len(dupes)
            report["issues"].append(f"Found {len(dupes)} potential duplicate title groups")
            report["recommendations"].append("Run 'dedup' to merge duplicates")
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Quality assessment
    if total > 0 and report["metrics"].get("total_qa", 0) == 0:
        report["recommendations"].append("No Q&A pairs — run distillers to extract Q&A from entries")

    return report


# ── Deduplication ───────────────────────────────────────────────────────

def nexus_find_duplicates(threshold: float = 0.85) -> List[Dict]:
    """Find potential duplicate entries based on title similarity.

    Args:
        threshold: Similarity threshold (0-1). Default 0.85.

    Returns:
        List of duplicate groups, each with original and duplicate entries.
    """
    client = _get_client()
    try:
        all_entries = client.list_entries(limit=200)
    except Exception as exc:
        logger.error("Failed to list entries: %s", exc)
        return []

    groups: List[Dict] = []
    seen: set = set()

    for i, entry_a in enumerate(all_entries):
        if entry_a.get("id") in seen:
            continue
        title_a = entry_a.get("title", "").lower().strip()
        if not title_a:
            continue

        duplicates = []
        for j, entry_b in enumerate(all_entries):
            if i >= j or entry_b.get("id") in seen:
                continue
            title_b = entry_b.get("title", "").lower().strip()
            sim = _title_similarity(title_a, title_b)
            if sim >= threshold:
                duplicates.append({
                    "id": entry_b.get("id"),
                    "title": entry_b.get("title"),
                    "similarity": round(sim, 3),
                })
                seen.add(entry_b.get("id"))

        if duplicates:
            groups.append({
                "original": {
                    "id": entry_a.get("id"),
                    "title": entry_a.get("title"),
                },
                "duplicates": duplicates,
                "count": len(duplicates) + 1,
            })
            seen.add(entry_a.get("id"))

    return groups


def nexus_merge_duplicates(dry_run: bool = True) -> Dict[str, Any]:
    """Find and optionally merge duplicate entries.

    Args:
        dry_run: If True, report duplicates without merging.

    Returns:
        Summary of found/merged duplicates.
    """
    groups = nexus_find_duplicates()
    result = {
        "duplicate_groups": len(groups),
        "total_duplicates": sum(g["count"] - 1 for g in groups),
        "merged": 0,
        "dry_run": dry_run,
        "groups": groups[:10],  # First 10 groups for display
    }

    if dry_run or not groups:
        return result

    client = _get_client()
    merged = 0
    for group in groups:
        for dup in group["duplicates"]:
            try:
                client.delete_entry(dup["id"])
                merged += 1
            except Exception as exc:
                logger.warning("Failed to delete duplicate %s: %s", dup["id"], exc)

    result["merged"] = merged
    return result


def _title_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two title strings."""
    if not a or not b:
        return 0.0
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# ── Session Compaction ──────────────────────────────────────────────────

def nexus_compact_sessions(max_age_days: int = 7) -> Dict[str, Any]:
    """Compact old session logs into summary entries.

    Sessions older than max_age_days are summarised into a single entry
    and their individual turn-level data is removed.

    Args:
        max_age_days: Sessions older than this are compacted.

    Returns:
        Summary of compacted sessions.
    """
    client = _get_client()
    result = {"compacted": 0, "errors": 0, "skipped": 0}

    try:
        sessions = client.list_sessions(limit=100)
    except Exception as exc:
        logger.error("Failed to list sessions: %s", exc)
        return result

    cutoff = time.time() - (max_age_days * 86400)

    for session in sessions:
        created = session.get("created_at", "")
        # Parse ISO timestamp
        try:
            from datetime import datetime
            if isinstance(created, str) and created:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                session_ts = dt.timestamp()
            else:
                continue
        except (ValueError, TypeError):
            continue

        if session_ts > cutoff:
            result["skipped"] += 1
            continue

        summary = session.get("summary", "")
        if not summary:
            summary = f"Session {session.get('id', 'unknown')} from {created}"

        try:
            client.add_entry(
                title=f"Compacted session: {session.get('id', '')[:8]}",
                content=summary,
                content_type="history",
                category="sessions",
                tags=["compacted", "session", session.get("project", "")],
                created_by="self_maintenance",
            )
            result["compacted"] += 1
        except Exception as exc:
            logger.warning("Failed to compact session: %s", exc)
            result["errors"] += 1

    return result


# ── Quality Scoring ─────────────────────────────────────────────────────

def nexus_score_entries(min_quality: float = 0.3) -> Dict[str, Any]:
    """Score knowledge entries by quality and flag low-quality ones.

    Quality factors:
    - Has title (0.2)
    - Has content > 50 chars (0.3)
    - Has tags (0.2)
    - Has category (0.15)
    - Has content_type (0.15)

    Args:
        min_quality: Entries below this score are flagged.

    Returns:
        Quality distribution and flagged entries.
    """
    client = _get_client()
    result = {
        "total_scored": 0,
        "avg_quality": 0.0,
        "low_quality_count": 0,
        "low_quality_entries": [],
        "distribution": {"high": 0, "medium": 0, "low": 0},
    }

    try:
        entries = client.list_entries(limit=200)
    except Exception:
        return result

    scores = []
    for entry in entries:
        score = 0.0
        if entry.get("title"):
            score += 0.2
        content = entry.get("content", "")
        if len(content) > 50:
            score += 0.3
        elif len(content) > 10:
            score += 0.15
        if entry.get("tags"):
            score += 0.2
        if entry.get("category"):
            score += 0.15
        if entry.get("content_type"):
            score += 0.15

        scores.append(score)

        if score >= 0.7:
            result["distribution"]["high"] += 1
        elif score >= 0.4:
            result["distribution"]["medium"] += 1
        else:
            result["distribution"]["low"] += 1

        if score < min_quality:
            result["low_quality_entries"].append({
                "id": entry.get("id"),
                "title": entry.get("title", "(untitled)"),
                "score": round(score, 2),
            })

    result["total_scored"] = len(scores)
    result["avg_quality"] = round(sum(scores) / len(scores), 3) if scores else 0.0
    result["low_quality_count"] = len(result["low_quality_entries"])
    # Limit output
    result["low_quality_entries"] = result["low_quality_entries"][:20]

    return result


# ── Full Maintenance ────────────────────────────────────────────────────

def nexus_full_maintenance(dry_run: bool = True) -> Dict[str, Any]:
    """Run all maintenance tasks and return a combined report.

    Args:
        dry_run: If True, don't apply destructive changes.

    Returns:
        Combined report from all tasks.
    """
    report = {}

    logger.info("Running Nexus health report...")
    report["health"] = nexus_health_report()

    logger.info("Running duplicate scan...")
    report["dedup"] = nexus_merge_duplicates(dry_run=dry_run)

    logger.info("Running quality scoring...")
    report["quality"] = nexus_score_entries()

    if not dry_run:
        logger.info("Running session compaction...")
        report["compact"] = nexus_compact_sessions()

    # Summary
    report["summary"] = {
        "status": report["health"].get("status", "unknown"),
        "total_entries": report["health"].get("metrics", {}).get("total_entries", 0),
        "duplicates_found": report["dedup"].get("total_duplicates", 0),
        "low_quality": report["quality"].get("low_quality_count", 0),
        "avg_quality": report["quality"].get("avg_quality", 0),
        "dry_run": dry_run,
    }

    return report


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point for Nexus self-maintenance."""
    import sys
    import json

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    args = sys.argv[1:]
    action = args[0] if args else "health"
    apply_flag = "--apply" in args

    actions = {
        "health": lambda: nexus_health_report(),
        "dedup": lambda: nexus_merge_duplicates(dry_run=not apply_flag),
        "compact": lambda: nexus_compact_sessions(),
        "score": lambda: nexus_score_entries(),
        "full": lambda: nexus_full_maintenance(dry_run=not apply_flag),
    }

    if action not in actions:
        print(f"Unknown action: {action}")
        print(f"Available: {', '.join(actions.keys())}")
        sys.exit(1)

    result = actions[action]()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
