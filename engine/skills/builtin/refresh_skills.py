"""MCP knowledge refresh skills — staleness assessment, refresh scheduling, predictive refresh."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── Helpers ──────────────────────────────────────────────────────────


def _ts(epoch: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(epoch or time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _get_pr() -> Any:
    from engine.nexus.predictive_refresh import get_predictive_refresh
    return get_predictive_refresh()


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _bar(value: float, width: int = 20) -> str:
    filled = int(min(max(value, 0.0), 1.0) * width)
    return "█" * filled + "░" * (width - filled)


# ──── Skills ───────────────────────────────────────────────────────────


@skill(
    pack="knowledge_refresh",
    description="Assess knowledge staleness across all tracked Nexus entries and return a detailed report.",
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=2.0,
    tags=["knowledge", "staleness", "nexus", "refresh"],
)
def knowledge_staleness_report(
    content_type: str = "",
    category: str = "",
    limit: int = 100,
) -> str:
    """Assess staleness of tracked knowledge entries.

    Args:
        content_type: Filter by content type (empty = all).
        category: Filter by category (empty = all).
        limit: Maximum entries to analyze.

    Returns:
        Staleness report with statistics and worst entries.
    """
    pr = _get_pr()
    report = pr.assess_staleness(
        content_type=content_type or None,
        category=category or None,
        limit=limit,
    )

    lines = [
        "Knowledge Staleness Report",
        f"  Total tracked: {report.total_tracked}",
        f"  Stale: {report.stale_count}",
        f"  Approaching stale: {report.approaching_stale}",
        f"  Fresh: {report.fresh_count}",
        f"  Average staleness: {_pct(report.avg_staleness)}",
        f"  Refresh queue: {report.refresh_queue_size} items",
    ]

    if report.by_content_type:
        lines.extend(["", "By content type:"])
        for ct, data in sorted(report.by_content_type.items()):
            lines.append(
                f"  {ct}: {data['count']} entries,"
                f" {data['stale']} stale,"
                f" avg staleness {_pct(data['avg_staleness'])}"
            )

    if report.by_category:
        lines.extend(["", "By category:"])
        for cat, data in sorted(report.by_category.items()):
            lines.append(
                f"  {cat}: {data['count']} entries,"
                f" {data['stale']} stale,"
                f" avg staleness {_pct(data['avg_staleness'])}"
            )

    if report.worst_entries:
        lines.extend(["", "Worst entries (most stale):"])
        for entry in report.worst_entries[:5]:
            lines.append(
                f"  {_bar(entry['staleness_score'])} {_pct(entry['staleness_score'])}"
                f"  {entry['title'][:50]}"
                f"  ({entry['content_type']}, age={entry['age_days']:.0f}d)"
            )

    return "\n".join(lines)


@skill(
    pack="knowledge_refresh",
    description="Get the refresh queue — entries that are stale or predicted to go stale soon.",
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
    tags=["knowledge", "refresh", "queue", "nexus"],
)
def knowledge_refresh_queue(
    horizon_hours: float = 48.0,
    content_type: str = "",
    max_items: int = 20,
) -> str:
    """Get entries queued for refresh, ordered by urgency.

    Args:
        horizon_hours: Look-ahead window in hours.
        content_type: Filter by content type (empty = all).
        max_items: Maximum entries to return.

    Returns:
        Refresh queue with urgency levels.
    """
    pr = _get_pr()
    queue = pr.get_refresh_queue(
        horizon_hours=horizon_hours,
        content_type=content_type or None,
        max_items=max_items,
    )

    if not queue:
        return f"Refresh queue is empty (horizon: {horizon_hours:.0f}h). All entries are fresh."

    lines = [
        f"Refresh Queue ({len(queue)} entries, horizon: {horizon_hours:.0f}h)",
        "",
    ]

    urgency_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡"}

    for candidate in queue:
        icon = urgency_icons.get(candidate.urgency, "⚪")
        hours_str = (
            f"{candidate.hours_until_stale:.1f}h"
            if candidate.hours_until_stale is not None and candidate.hours_until_stale > 0
            else "NOW"
        )
        lines.append(
            f"  {icon} [{candidate.urgency.upper()}] {candidate.title[:45]}"
            f"  (staleness={_pct(candidate.staleness_score)},"
            f" {hours_str})"
        )
        lines.append(f"     Reason: {candidate.refresh_reason}")

    return "\n".join(lines)


@skill(
    pack="knowledge_refresh",
    description="Trigger refresh of stale knowledge entries to reset their staleness timers.",
    category=SkillCategory.SYSTEM,
    cooldown=10.0,
    cost=3.0,
    tags=["knowledge", "refresh", "nexus", "maintenance"],
)
def knowledge_refresh_stale(
    max_items: int = 10,
    horizon_hours: float = 48.0,
) -> str:
    """Refresh stale entries by resetting their access timers.

    Args:
        max_items: Maximum entries to refresh.
        horizon_hours: Look-ahead window.

    Returns:
        Refresh results for each processed entry.
    """
    pr = _get_pr()
    results = pr.refresh_stale(max_items=max_items, horizon_hours=horizon_hours)

    if not results:
        return "No entries needed refreshing."

    refreshed = [r for r in results if r.status == "refreshed"]
    failed = [r for r in results if r.status == "failed"]

    lines = [
        f"Refresh Results: {len(refreshed)} refreshed, {len(failed)} failed",
        "",
    ]

    for r in results:
        status_icon = "✅" if r.status == "refreshed" else "❌"
        lines.append(
            f"  {status_icon} {r.title[:45]}"
            f"  (staleness: {_pct(r.old_staleness)} → {_pct(r.new_staleness)},"
            f" method={r.refresh_method})"
        )
        if r.error:
            lines.append(f"     Error: {r.error}")

    return "\n".join(lines)


@skill(
    pack="knowledge_refresh",
    description="Calculate the optimal refresh schedule for a specific knowledge entry.",
    category=SkillCategory.SYSTEM,
    cooldown=2.0,
    cost=1.0,
    tags=["knowledge", "schedule", "refresh", "prediction"],
)
def knowledge_schedule_refresh(
    entry_id: str,
    target_staleness: float = 0.5,
) -> str:
    """Calculate when an entry should next be refreshed.

    Args:
        entry_id: Nexus entry ID.
        target_staleness: Desired maximum staleness (0.0–1.0).

    Returns:
        Refresh schedule recommendation.
    """
    pr = _get_pr()
    schedule = pr.schedule_refresh(entry_id, target_staleness=target_staleness)

    if schedule is None:
        return f"Entry {entry_id} is not tracked. Register it first."

    lines = [
        f"Refresh Schedule: {schedule['title'][:50]}",
        f"  Current staleness: {_pct(schedule['current_staleness'])}",
        f"  Target staleness: {_pct(schedule['target_staleness'])}",
        f"  Recommendation: {schedule['recommendation']}",
    ]

    if schedule.get("hours_until_refresh") is not None:
        lines.append(f"  Next refresh in: {schedule['hours_until_refresh']:.1f}h")
    if schedule.get("next_refresh_at"):
        lines.append(f"  Scheduled at: {_ts(schedule['next_refresh_at'])}")
    if schedule.get("hours_until_stale") is not None:
        lines.append(f"  Predicted stale in: {schedule['hours_until_stale']:.1f}h")

    return "\n".join(lines)


@skill(
    pack="knowledge_refresh",
    description="Get a snapshot of the predictive refresh engine status.",
    category=SkillCategory.SYSTEM,
    cooldown=1.0,
    cost=0.5,
    tags=["knowledge", "refresh", "status"],
)
def knowledge_refresh_status() -> str:
    """Get current status of the predictive refresh engine.

    Returns:
        Engine status with tracked entries, access counts, and refresh history.
    """
    pr = _get_pr()
    snap = pr.snapshot()

    lines = [
        "Predictive Refresh Engine Status",
        f"  Tracked entries: {snap['tracked_entries']}",
        f"  Total accesses: {snap['total_accesses']}",
        f"  Total refreshes: {snap['total_refreshes']}",
        f"  Half-life configs: {snap['half_life_configs']} content types",
        f"  Threshold configs: {snap['threshold_configs']} content types",
    ]

    return "\n".join(lines)
