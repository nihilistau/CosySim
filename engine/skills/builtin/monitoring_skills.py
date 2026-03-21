"""MCP monitoring skills — anomaly detection, trends, pack tracking, alerts, dashboard."""
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

def _pct(v: float) -> str: return f"{v:.2f}%"

def _dur(seconds: float) -> str:
    if seconds < 60: return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m" if seconds < 3600 else f"{seconds / 3600:.1f}h"

def _bar(value: float, width: int = 20) -> str:
    filled = int(min(max(value / 100.0, 0.0), 1.0) * width)
    return "█" * filled + "░" * (width - filled)

def _tbl(headers: List[str], rows: List[List[str]], indent: int = 2) -> List[str]:
    """Build a simple aligned table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    pad = " " * indent
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [pad + fmt.format(*headers), pad + "─" * (sum(widths) + 2 * (len(widths) - 1))]
    for row in rows:
        out.append(pad + fmt.format(*(row + [""] * (len(headers) - len(row)))))
    return out


# ──── Snapshot & Health ────────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Full unified monitoring snapshot: health, packs, anomalies, trends, alerts. Use detail='full' for extended output.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "snapshot", "overview"],
    cooldown=2.0,
)
def monitoring_snapshot(detail: str = "summary") -> str:
    """Comprehensive monitoring snapshot. detail='full' for extended output."""
    from engine.observability.anomaly_detector import get_anomaly_detector
    from engine.observability.alert_router import get_alert_router
    from engine.observability.pack_tracker import get_pack_tracker
    from engine.observability.trend_predictor import get_trend_predictor
    from engine.observability.unified_dashboard import get_unified_dashboard

    full = detail.lower() == "full"
    lines: List[str] = ["═══ MONITORING SNAPSHOT ═══"]

    try:
        health = get_unified_dashboard().health_score()
        bd = health.get("breakdown", {})
        bd_str = "  " + ", ".join(f"{k}={v}" for k, v in bd.items()) if bd else ""
        lines.append(f"  Health: {health.get('score', -1)}/100 ({health.get('status', '?')})")
        if bd_str:
            lines.append(f"  Breakdown:{bd_str}")
    except Exception as exc:
        lines.append(f"  Health: unavailable ({exc})")

    try:
        top = get_pack_tracker().top_packs(n=5 if not full else 10)
        lines += ["", "─── Top Packs (by CPU) ───"]
        if top:
            for i, p in enumerate(top, 1):
                name = p.get("pack", p.get("name", "?"))
                lines.append(f"  {i}. {name:20s}  CPU {p.get('total_cpu_seconds', 0.0):.1f}s  calls {p.get('total_calls', 0)}")
        else:
            lines.append("  No pack activity recorded.")
    except Exception as exc:
        lines.append(f"  Packs: unavailable ({exc})")

    try:
        recent = get_anomaly_detector().recent_anomalies(n=5 if not full else 15)
        lines += ["", "─── Recent Anomalies ───"]
        if recent:
            for a in recent:
                lines.append(f"  [{a.get('severity', '?').upper()}] {a.get('node', '?')}.{a.get('metric', '?')} = {a.get('value', 0):.2f} — {a.get('message', '')}")
        else:
            lines.append("  No anomalies detected.")
    except Exception as exc:
        lines.append(f"  Anomalies: unavailable ({exc})")

    try:
        trends = get_trend_predictor().all_trends()
        dirs = {}
        for t in trends:
            d = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
            dirs[d] = dirs.get(d, 0) + 1
        lines += ["", "─── Trend Summary ───"]
        lines.append(f"  Tracked: {len(trends)}  " + "  ".join(f"{k.title()}: {v}" for k, v in dirs.items()))
        if full:
            for t in sorted(trends, key=lambda x: abs(x.slope), reverse=True)[:10]:
                lines.append(f"  {t.metric_key:30s}  {t.direction.value:8s}  slope={t.slope:+.4f}  r²={t.r_squared:.2f}")
    except Exception as exc:
        lines.append(f"  Trends: unavailable ({exc})")

    try:
        alerts = get_alert_router().recent_routed(n=5 if not full else 15)
        active = [a for a in alerts if not a.get("suppressed")]
        lines += ["", "─── Active Alerts ───"]
        if active:
            for a in active:
                lines.append(f"  [{a.get('level', '?')}] {a.get('node', '?')}: {a.get('message', '')}")
        else:
            lines.append("  No active alerts.")
    except Exception as exc:
        lines.append(f"  Alerts: unavailable ({exc})")

    lines += ["", f"═══ END SNAPSHOT ({_ts()}) ═══"]
    return "\n".join(lines)


@skill(
    pack="monitoring",
    description="System health score 0–100 with per-subsystem breakdown (resources, pipeline, packs, trends).",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "health", "score"],
    cooldown=2.0,
)
def monitoring_health() -> str:
    """System health score and per-subsystem breakdown."""
    from engine.observability.unified_dashboard import get_unified_dashboard
    try:
        health = get_unified_dashboard().health_score()
    except Exception as exc:
        return f"Health check failed: {exc}"

    score = health.get("score", -1)
    lines = [
        "═══ HEALTH REPORT ═══",
        f"  Overall: {score}/100 — {health.get('status', 'unknown').upper()}",
        f"  {_bar(score)}",
        "",
    ]
    breakdown = health.get("breakdown", {})
    if breakdown:
        lines.append("─── Subsystem Scores ───")
        for sub, val in breakdown.items():
            lines.append(f"  {sub.replace('_', ' ').title():20s}  {val:6.1f}  {_bar(val)}")
    lines.append(f"\n  Measured at: {_ts(health.get('ts'))}")
    return "\n".join(lines)


# ──── Pack Tracking ────────────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Pack activity overview — top packs by CPU, call counts, success rates, and execution times.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "packs", "leaderboard"],
    cooldown=2.0,
)
def monitoring_packs(hours: float = 24.0, top_n: int = 10) -> str:
    """Pack activity leaderboard with CPU, call count, and error stats."""
    from engine.observability.pack_tracker import get_pack_tracker
    tracker = get_pack_tracker()
    top = tracker.top_packs(n=top_n)
    summary = tracker.pack_summary(hours=hours)

    lines = [f"═══ PACK ACTIVITY (last {hours:.0f}h) ═══", f"  Active packs: {len(summary)}", ""]
    if not top:
        lines.append("  No pack activity recorded.")
        return "\n".join(lines)

    rows: List[List[str]] = []
    for i, p in enumerate(top, 1):
        name = p.get("pack", p.get("name", "?"))
        act = summary.get(name)
        d = (act.to_dict() if hasattr(act, "to_dict") else act) if act else p
        rows.append([
            str(i), name,
            str(d.get("total_calls", 0)),
            f"{d.get('total_cpu_seconds', 0.0):.1f}",
            f"{d.get('avg_duration_s', 0.0):.3f}",
            str(d.get("error_count", 0)),
            _pct(d.get("success_rate", 100.0)),
        ])
    lines += _tbl(["#", "Pack", "Calls", "CPU(s)", "Avg(s)", "Err", "Rate"], rows)
    return "\n".join(lines)


@skill(
    pack="monitoring",
    description="Detailed info about a specific skill pack — stats, processes, recent calls, and errors.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "packs", "detail"],
    cooldown=2.0,
)
def monitoring_pack_detail(pack_name: str) -> str:
    """Detailed pack report with process cross-references."""
    from engine.observability.pack_tracker import get_pack_tracker
    tracker = get_pack_tracker()
    summary = tracker.pack_summary(hours=24.0)
    activity = summary.get(pack_name)
    if not activity:
        return f"Pack '{pack_name}' has no recorded activity in the last 24 hours."

    d = activity.to_dict() if hasattr(activity, "to_dict") else activity
    lines = [
        f"═══ PACK: {pack_name} ═══",
        f"  Calls: {d.get('total_calls', 0)}  CPU: {d.get('total_cpu_seconds', 0.0):.1f}s  Duration: {d.get('total_duration_s', 0.0):.1f}s",
        f"  Avg: {d.get('avg_duration_s', 0.0):.3f}s  P95: {d.get('p95_duration_s', 0.0):.3f}s  P99: {d.get('p99_duration_s', 0.0):.3f}s",
        f"  Success: {_pct(d.get('success_rate', 100.0))}  Errors: {d.get('error_count', 0)}  Peak mem: {d.get('memory_mb_peak', 0.0):.1f}MB",
        f"  PIDs: {d.get('pid_count', 0)}  Categories: {', '.join(d.get('categories', [])) or 'none'}",
    ]
    last = d.get("last_execution")
    if last:
        lines.append(f"  Last execution: {_ts(last)}")

    skills_used = d.get("skills_used", {})
    if skills_used:
        lines += ["", "─── Skills Used ───"]
        for sname, count in sorted(skills_used.items(), key=lambda x: -x[1]):
            lines.append(f"  {sname:30s}  {count:5d} calls")

    try:
        procs = tracker.pack_processes(pack_name, hours=1.0)
        if procs:
            lines += ["", "─── Associated Processes (1h) ───"]
            for p in procs[:10]:
                lines.append(f"  PID {p.get('pid', '?'):>6}  {p.get('process_name', '?'):20s}  [{p.get('process_category', '?')}]  CPU {p.get('cpu_s', 0.0):.1f}s  Mem {p.get('mem_mb', 0.0):.1f}MB")
    except Exception:
        logger.debug("Failed to fetch pack processes for %s", pack_name, exc_info=True)

    try:
        recent = tracker.recent_executions(n=5, pack=pack_name)
        if recent:
            lines += ["", "─── Recent Executions ───"]
            for ex in recent:
                ok = "✓" if ex.get("success", True) else "✗"
                lines.append(f"  {ok} {ex.get('skill', ex.get('skill_name', '?')):25s}  {ex.get('duration_s', 0.0):.3f}s  {_ts(ex.get('ts'))}")
    except Exception:
        logger.debug("Failed to fetch recent executions for %s", pack_name, exc_info=True)

    return "\n".join(lines)


@skill(
    pack="monitoring",
    description="Skill execution leaderboard ranked by total CPU time and call count across all packs.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "skills", "leaderboard", "performance"],
    cooldown=2.0,
)
def monitoring_skill_leaderboard(top_n: int = 20) -> str:
    """Top skills ranked by CPU consumption and call frequency."""
    from engine.observability.pack_tracker import get_pack_tracker
    board = get_pack_tracker().skill_leaderboard(top_n=top_n)

    lines = [f"═══ SKILL LEADERBOARD (top {top_n}) ═══"]
    if not board:
        lines.append("  No skill execution data available.")
        return "\n".join(lines)

    rows = []
    for i, e in enumerate(board, 1):
        rows.append([
            str(i), e.get("skill_name", "?"), e.get("pack", "?"),
            str(e.get("cnt", 0)), f"{e.get('total_cpu', 0.0):.1f}",
            f"{e.get('avg_dur', 0.0):.3f}", str(e.get("err_cnt", 0)),
        ])
    lines += _tbl(["#", "Skill", "Pack", "Calls", "CPU(s)", "Avg(s)", "Err"], rows)
    return "\n".join(lines)


# ──── Anomaly Detection ────────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Recent anomaly events detected by z-score, IQR, or MAD. Filter by severity: low/medium/high/critical.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "anomalies", "detection"],
    cooldown=2.0,
)
def monitoring_anomalies(hours: float = 4.0, severity: str = "") -> str:
    """Recent anomaly events with severity and deviation details."""
    from engine.observability.anomaly_detector import get_anomaly_detector
    detector = get_anomaly_detector()
    cutoff = time.time() - (hours * 3600)
    raw = detector.recent_anomalies(n=100, severity=severity)
    events = [a for a in raw if a.get("ts", 0) >= cutoff]

    sev_label = f", severity≥{severity.upper()}" if severity else ""
    lines = [f"═══ ANOMALIES (last {hours:.0f}h{sev_label}) ═══", f"  Total: {len(events)}", ""]
    if not events:
        lines.append("  No anomalies detected in this window.")
        return "\n".join(lines)

    counts: Dict[str, int] = {}
    for a in events:
        s = a.get("severity", "unknown")
        counts[s] = counts.get(s, 0) + 1
    lines.append("  By severity: " + ", ".join(f"{k.upper()}: {v}" for k, v in sorted(counts.items())))
    lines.append("")

    rows = []
    for a in events[:30]:
        rows.append([
            a.get("severity", "?").upper(), a.get("node", "?"),
            a.get("metric", "?"), f"{a.get('value', 0.0):.2f}",
            f"{a.get('expected_mean', 0.0):.2f}", a.get("method", "?"),
        ])
    lines += _tbl(["Severity", "Node", "Metric", "Value", "Expected", "Method"], rows)

    if len(events) > 30:
        lines.append(f"  ... and {len(events) - 30} more events")
    return "\n".join(lines)


# ──── Trend Prediction ─────────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Current metric trends — direction, slope, confidence, and predictions for 1h/4h/24h ahead.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "trends", "prediction"],
    cooldown=2.0,
)
def monitoring_trends() -> str:
    """All tracked metric trends with direction and predictions."""
    from engine.observability.trend_predictor import get_trend_predictor
    trends = get_trend_predictor().all_trends()

    lines = [f"═══ METRIC TRENDS ({len(trends)} tracked) ═══"]
    if not trends:
        lines.append("  Insufficient data for trend analysis.")
        return "\n".join(lines)

    by_dir: Dict[str, List[Any]] = {}
    for t in trends:
        d = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
        by_dir.setdefault(d, []).append(t)

    icons = {"rising": "↑", "falling": "↓", "volatile": "~", "stable": "─"}
    for direction in ("rising", "falling", "volatile", "stable"):
        group = by_dir.get(direction, [])
        if not group:
            continue
        lines += ["", f"─── {icons.get(direction, '?')} {direction.upper()} ({len(group)}) ───"]
        for t in sorted(group, key=lambda x: abs(x.slope), reverse=True)[:10]:
            sev = t.severity.value if hasattr(t.severity, "value") else str(t.severity)
            lines.append(f"  {t.metric_key:30s}  slope={t.slope:+.4f}  r²={t.r_squared:.2f}  now={t.current_value:.2f}")
            lines.append(f"    pred 1h={t.predicted_1h:.2f}  4h={t.predicted_4h:.2f}  24h={t.predicted_24h:.2f}  [{sev}]")
    return "\n".join(lines)


@skill(
    pack="monitoring",
    description="Capacity planning warnings — resources approaching thresholds within the given horizon.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "capacity", "planning", "prediction"],
    cooldown=5.0,
)
def monitoring_capacity(horizon_hours: int = 24) -> str:
    """Capacity warnings for resources approaching limits."""
    from engine.observability.trend_predictor import get_trend_predictor
    warnings = get_trend_predictor().capacity_warnings(horizon_minutes=horizon_hours * 60)

    lines = [f"═══ CAPACITY WARNINGS (horizon: {horizon_hours}h) ═══"]
    if not warnings:
        lines.append("  All resources within safe operating limits.")
        return "\n".join(lines)

    lines.append(f"  Warnings: {len(warnings)}")
    breached = [w for w in warnings if w.get("status") == "breached"]
    approaching = [w for w in warnings if w.get("status") == "approaching"]

    if breached:
        lines += ["", "─── ⚠ BREACHED ───"]
        for w in breached:
            lines.append(f"  {w.get('metric_key', '?'):30s}  current={w.get('current_value', 0.0):.2f}  threshold={w.get('threshold', 0.0):.2f}  [{w.get('severity', '?')}]")

    if approaching:
        lines += ["", "─── ⏳ APPROACHING ───"]
        for w in approaching:
            ttb = w.get("time_to_breach_min", 0)
            lines.append(f"  {w.get('metric_key', '?'):30s}  current={w.get('current_value', 0.0):.2f}  threshold={w.get('threshold', 0.0):.2f}  [{w.get('severity', '?')}]")
            lines.append(f"    breach in ~{_dur(ttb * 60)}  predicted={w.get('predicted_at_horizon', 0.0):.2f}  slope/min={w.get('slope_per_min', 0.0):+.4f}")
    return "\n".join(lines)


# ──── Correlation Analysis ─────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Strong metric correlations — shows which metrics move together and how strongly.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "correlations", "analysis"],
    cooldown=5.0,
)
def monitoring_correlations(min_r: float = 0.7) -> str:
    """Strongest metric-to-metric correlations above the threshold."""
    from engine.observability.correlation_engine import get_correlation_engine
    raw = get_correlation_engine().strongest_correlations(n=20)
    corrs = [c for c in raw if abs(c.get("pearson_r", 0)) >= min_r]

    lines = [f"═══ METRIC CORRELATIONS (|r| ≥ {min_r:.1f}) ═══"]
    if not corrs:
        lines += [f"  No correlations above |r| = {min_r:.1f}.", "  Try lowering min_r."]
        return "\n".join(lines)

    lines.append(f"  Found: {len(corrs)} significant correlations")
    lines.append("")

    rows = []
    for c in corrs:
        rows.append([
            c.get("metric_a", "?"), c.get("metric_b", "?"),
            f"{c.get('pearson_r', 0.0):+.3f}", c.get("strength", "?"),
            c.get("direction", "?"), str(c.get("sample_count", 0)),
        ])
    lines += _tbl(["Metric A", "Metric B", "r", "Strength", "Dir", "N"], rows)
    return "\n".join(lines)


# ──── Alerting ─────────────────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Recent routed alerts — severity, node, message, channels, and suppression status.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "alerts", "feed"],
    cooldown=2.0,
)
def monitoring_alerts(hours: float = 4.0) -> str:
    """Recent alert feed with routing and suppression details."""
    from engine.observability.alert_router import get_alert_router
    router = get_alert_router()
    cutoff = time.time() - (hours * 3600)
    raw = router.recent_routed(n=100)
    alerts = [a for a in raw if a.get("ts", 0) >= cutoff]

    stats = router.routing_stats()
    lines = [
        f"═══ ALERT FEED (last {hours:.0f}h) ═══",
        f"  Total: {stats.get('total', 0)}  Suppressed: {stats.get('suppressed', 0)}  Ack'd: {stats.get('acknowledged', 0)}",
        "",
    ]
    if not alerts:
        lines.append("  No alerts in this window.")
        return "\n".join(lines)

    for a in alerts:
        sup = " [SUPPRESSED]" if a.get("suppressed") else ""
        ch = ", ".join(a.get("channels", [])) or "none"
        lines.append(f"  [{a.get('level', '?')}/{a.get('severity', '?')}] {a.get('node', '?')}.{a.get('metric', '?')}{sup}")
        lines.append(f"    {a.get('message', '')}  routed: {ch}  at: {_ts(a.get('ts'))}")
    return "\n".join(lines)


@skill(
    pack="monitoring",
    description="Suppress alerts for a node+metric for N minutes. Prevents noisy alerts during maintenance.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "alerts", "suppress", "maintenance"],
    cooldown=2.0,
)
def monitoring_suppress(node: str, metric: str, minutes: int = 30) -> str:
    """Suppress alerts for a node+metric for the specified duration."""
    from engine.observability.alert_router import get_alert_router
    if minutes < 1 or minutes > 1440:
        return f"Invalid duration: {minutes}m. Must be 1–1440 minutes."
    get_alert_router().suppress(node, metric, duration_seconds=minutes * 60.0)
    logger.info("Alert suppressed: %s.%s for %dm", node, metric, minutes)
    return (
        f"✓ Suppressed {node}.{metric} for {minutes}m.\n"
        f"  Expires: {_ts(time.time() + minutes * 60)}"
    )


# ──── Dashboard ────────────────────────────────────────────────────────


@skill(
    pack="monitoring",
    description="Full dashboard state — health, gauges, top packs, trends, anomalies, alerts, and active issues.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "dashboard", "overview"],
    cooldown=5.0,
)
def monitoring_dashboard(hours: float = 1.0) -> str:
    """Full monitoring dashboard with all widget data."""
    from engine.observability.unified_dashboard import get_unified_dashboard
    try:
        state = get_unified_dashboard().full_state()
    except Exception as exc:
        return f"Dashboard unavailable: {exc}"

    lines = [
        "╔══════════════════════════════════════════╗",
        "║        UNIFIED MONITORING DASHBOARD      ║",
        "╚══════════════════════════════════════════╝",
    ]

    health = state.get("health", {})
    score = health.get("score", -1)
    lines += [f"  Health: {score}/100 ({health.get('status', '?')})", f"  {_bar(score)}", ""]

    cards = state.get("summary_cards", {})
    if cards:
        lines.append("─── Summary ───")
        for k, v in cards.items():
            lines.append(f"  {k.replace('_', ' ').title():25s}  {v}")
        lines.append("")

    current = state.get("current_values", {})
    if current:
        lines.append("─── System Gauges ───")
        for m, v in current.items():
            label = m.replace("_", " ").title()
            if isinstance(v, (int, float)):
                lines.append(f"  {label:20s}  {v:8.1f}  {_bar(v)}")
            else:
                lines.append(f"  {label:20s}  {v}")
        lines.append("")

    top_packs = state.get("top_packs", [])
    if top_packs:
        lines.append("─── Top Packs ───")
        for i, p in enumerate(top_packs, 1):
            lines.append(f"  {i}. {p.get('pack', p.get('name', '?')):20s}  CPU {p.get('total_cpu_seconds', p.get('cpu', 0.0)):.1f}s")
        lines.append("")

    trends = state.get("trends", {})
    if trends:
        lines.append("─── Trends ───")
        lines.append(f"  Degrading: {trends.get('degrading_count', 0)}  Volatile: {trends.get('volatile_count', 0)}  Worst: {trends.get('worst_severity', 'none')}")
        lines.append("")

    for key, label in [("anomalies", "Anomalies"), ("recent_alerts", "Alerts")]:
        items = state.get(key, [])
        if items:
            lines.append(f"─── {label} ───")
            for a in items[:5]:
                sev = a.get("severity", a.get("level", "?"))
                lines.append(f"  [{sev}] {a.get('node', '?')}.{a.get('metric', '')} {a.get('message', '')}")
            lines.append("")

    issues = state.get("active_issues", {})
    if isinstance(issues, dict) and sum(issues.values()):
        lines.append("─── Active Issues ───")
        for sev, count in issues.items():
            if count:
                lines.append(f"  {sev:10s}  {count}")
        lines.append("")

    lines.append(f"  Generated: {_ts()}")
    return "\n".join(lines)


# ──── Cross-Reference & Diagnostics ───────────────────────────────────


@skill(
    pack="monitoring",
    description="Cross-reference packs ↔ OS processes ↔ CPU consumption. Shows process categories per pack.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "cross-reference", "packs", "processes"],
    cooldown=5.0,
)
def monitoring_cross_reference() -> str:
    """Pack-to-process cross-reference map."""
    from engine.observability.pack_tracker import get_pack_tracker
    try:
        xref = get_pack_tracker().cross_reference(hours=24.0)
    except Exception as exc:
        return f"Cross-reference unavailable: {exc}"

    lines = ["═══ PACK ↔ PROCESS CROSS-REFERENCE ═══"]
    if not xref:
        lines.append("  No cross-reference data available.")
        return "\n".join(lines)

    for pack_name, categories in xref.items():
        lines.append(f"\n─── {pack_name} ───")
        if isinstance(categories, dict):
            for cat, stats in categories.items():
                if isinstance(stats, dict):
                    lines.append(f"  {cat:20s}  CPU {stats.get('cpu_seconds', 0.0):.1f}s  Mem {stats.get('memory_mb_peak', 0.0):.1f}MB  execs {stats.get('execution_count', 0)}")
                else:
                    lines.append(f"  {cat}: {stats}")
        else:
            lines.append(f"  {categories}")
    return "\n".join(lines)


@skill(
    pack="monitoring",
    description="Degradation report — metrics with worsening trends or volatile behavior indicating emerging problems.",
    category=SkillCategory.SYSTEM,
    tags=["monitoring", "degradation", "trends", "diagnostic"],
    cooldown=5.0,
)
def monitoring_degradation() -> str:
    """Degradation and volatility report for worsening metrics."""
    from engine.observability.trend_predictor import get_trend_predictor
    try:
        report = get_trend_predictor().degradation_report()
    except Exception as exc:
        return f"Degradation report unavailable: {exc}"

    degrading = report.get("degrading", [])
    volatile = report.get("volatile", [])
    worst = report.get("worst_severity", "none")

    lines = [
        "═══ DEGRADATION REPORT ═══",
        f"  Degrading: {report.get('degrading_count', len(degrading))}  Volatile: {report.get('volatile_count', len(volatile))}  Worst: {worst}",
        f"  Report time: {_ts(report.get('ts'))}",
    ]

    if not degrading and not volatile:
        lines += ["", "  ✓ No degradation or volatility detected."]
        return "\n".join(lines)

    def _fmt_trend(t: Any, icon: str) -> List[str]:
        out: List[str] = []
        if hasattr(t, "metric_key"):
            sev = t.severity.value if hasattr(t.severity, "value") else str(t.severity)
            out.append(f"  {icon} {t.metric_key:30s}  slope={t.slope:+.4f}  now={t.current_value:.2f}  [{sev}]")
            if hasattr(t, "predicted_1h"):
                out.append(f"    pred 1h={t.predicted_1h:.2f}  4h={t.predicted_4h:.2f}  24h={t.predicted_24h:.2f}")
        elif isinstance(t, dict):
            out.append(f"  {icon} {t.get('metric_key', '?'):30s}  slope={t.get('slope', 0.0):+.4f}  now={t.get('current_value', 0.0):.2f}  [{t.get('severity', '?')}]")
        return out

    if degrading:
        lines += ["", "─── Degrading Metrics ───"]
        for t in degrading:
            lines += _fmt_trend(t, "↓")

    if volatile:
        lines += ["", "─── Volatile Metrics ───"]
        for t in volatile:
            lines += _fmt_trend(t, "~")

    return "\n".join(lines)
