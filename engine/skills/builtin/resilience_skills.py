"""Resilience and config drift MCP skills for CosySim agents.

Exposes circuit breaker state, history, and reset operations alongside
config drift detection, baseline management, rollback, and aggregate
system-resilience health — all as JSON-returning MCP skills.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from engine.skills.skill import skill, SkillCategory
from engine.skills.utils import to_json

logger = logging.getLogger(__name__)


# ── JSON helpers ────────────────────────────────────────────────────────


def _default_serializer(obj: Any) -> Any:
    """Handle datetimes, enums, and other non-JSON-native types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)


def _to_json(data: Any) -> str:
    """Serialize *data* to a compact JSON string."""
    return to_json(data, default=_default_serializer, ensure_ascii=False)


# ── Lazy accessors (best-effort imports) ────────────────────────────────


def _registry():
    """Return the global CircuitBreakerRegistry singleton."""
    from engine.resilience.circuit_breaker import get_breaker_registry
    return get_breaker_registry()


def _drift_monitor():
    """Return the global ConfigDriftMonitor singleton."""
    from engine.nexus.config_drift import get_drift_monitor
    return get_drift_monitor()


# ════════════════════════════════════════════════════════════════════════
#  CIRCUIT BREAKER SKILLS
# ════════════════════════════════════════════════════════════════════════


@skill(
    pack="resilience",
    description="Get the current state of all circuit breakers (or filter by name)",
    tags=["resilience", "circuit_breaker", "status"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def get_circuit_status(name: str = "") -> str:
    """Return JSON with every registered circuit breaker's stats."""
    try:
        reg = _registry()
        all_status = reg.all_status()
        if name:
            filtered = {k: v for k, v in all_status.items() if name in k}
            return _to_json({"breakers": filtered, "matched": len(filtered)})
        return _to_json({"breakers": all_status, "total": len(all_status)})
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Force-reset a tripped circuit breaker back to CLOSED",
    tags=["resilience", "circuit_breaker", "reset"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def reset_circuit(name: str) -> str:
    """Reset a named circuit breaker to CLOSED."""
    try:
        reg = _registry()
        breaker = reg.get(name)
        if breaker is None:
            return _to_json({
                "success": False,
                "error": f"Circuit breaker '{name}' not found",
                "available": list(reg.all_status().keys()),
            })
        old_state = breaker.state.value
        breaker.reset()
        return _to_json({
            "success": True,
            "name": name,
            "previous_state": old_state,
            "current_state": breaker.state.value,
        })
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Get state transition history for a circuit breaker",
    tags=["resilience", "circuit_breaker", "history"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def get_circuit_history(name: str = "", limit: int = 20) -> str:
    """Return recent state transitions for a named breaker (or all)."""
    try:
        reg = _registry()
        all_status = reg.all_status()

        transitions: List[Dict[str, Any]] = []
        names = [name] if name else list(all_status.keys())
        for bname in names:
            breaker = reg.get(bname)
            if breaker is None:
                continue
            for t in breaker.transitions:
                transitions.append({
                    "breaker_name": t.breaker_name,
                    "from_state": t.from_state.value,
                    "to_state": t.to_state.value,
                    "timestamp": t.timestamp,
                    "reason": t.reason,
                    "failure_count": t.failure_count,
                })

        # Sort newest-first and apply limit
        transitions.sort(key=lambda x: x["timestamp"], reverse=True)
        transitions = transitions[:limit]
        return _to_json({"transitions": transitions, "total": len(transitions)})
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Get aggregate circuit breaker health summary (counts by state)",
    tags=["resilience", "circuit_breaker", "stats"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def get_retry_stats() -> str:
    """Return registry-level health summary with total/open/closed/half_open counts."""
    try:
        reg = _registry()
        summary = reg.get_health_summary()
        return _to_json(summary)
    except Exception as e:
        return _to_json({"error": str(e)})


# ════════════════════════════════════════════════════════════════════════
#  CONFIG DRIFT SKILLS
# ════════════════════════════════════════════════════════════════════════


@skill(
    pack="resilience",
    description="Trigger a config drift check and return the result",
    tags=["resilience", "config", "drift"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def check_config_drift() -> str:
    """Run a drift check against the stored baseline and return the result."""
    try:
        monitor = _drift_monitor()
        result = monitor.check_drift(auto_store=True)
        return _to_json(result.to_dict())
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Get recent config drift check results",
    tags=["resilience", "config", "drift", "report"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def get_drift_report(limit: int = 5) -> str:
    """Return the most recent drift check history entries."""
    try:
        monitor = _drift_monitor()
        history = monitor.get_drift_history(limit=limit)
        return _to_json({"checks": history, "total": len(history)})
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Snapshot current config as a new baseline",
    tags=["resilience", "config", "baseline"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def store_config_baseline(label: str = "manual") -> str:
    """Store the current configuration as a named baseline."""
    try:
        monitor = _drift_monitor()
        baseline_id = monitor.store_baseline(label=label)
        return _to_json({
            "success": True,
            "baseline_id": baseline_id,
            "label": label,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Revert a specific config key to its baseline value",
    tags=["resilience", "config", "rollback"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def rollback_config_key(key: str) -> str:
    """Roll back a single config key to the stored baseline value."""
    try:
        monitor = _drift_monitor()
        success = monitor.rollback_key(key)
        if success:
            return _to_json({
                "success": True,
                "key": key,
                "message": f"Key '{key}' reverted to baseline value",
            })
        return _to_json({
            "success": False,
            "key": key,
            "message": f"Could not rollback '{key}' — baseline missing or key not found",
        })
    except Exception as e:
        return _to_json({"error": str(e)})


@skill(
    pack="resilience",
    description="Get recent config change history (optionally filtered by key)",
    tags=["resilience", "config", "changes", "history"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def get_config_changes(key: str = "", limit: int = 50) -> str:
    """Return recent config change log entries."""
    try:
        monitor = _drift_monitor()
        changes = monitor.get_change_log(
            key=key if key else None,
            limit=limit,
        )
        return _to_json({"changes": changes, "total": len(changes)})
    except Exception as e:
        return _to_json({"error": str(e)})


# ════════════════════════════════════════════════════════════════════════
#  AGGREGATE
# ════════════════════════════════════════════════════════════════════════


@skill(
    pack="resilience",
    description="Overall system resilience health combining circuit breakers and config drift",
    tags=["resilience", "health", "aggregate"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def get_system_resilience() -> str:
    """Return a combined resilience report: circuit breakers + config drift + status."""
    result: Dict[str, Any] = {
        "timestamp": time.time(),
        "circuit_breakers": {},
        "config_drift": {},
        "overall_status": "healthy",
    }

    # Circuit breaker health
    try:
        reg = _registry()
        cb_summary = reg.get_health_summary()
        result["circuit_breakers"] = cb_summary
    except Exception as e:
        result["circuit_breakers"] = {"error": str(e)}

    # Config drift health
    try:
        monitor = _drift_monitor()
        drift_health = monitor.get_health()
        result["config_drift"] = drift_health
    except Exception as e:
        result["config_drift"] = {"error": str(e)}

    # Derive overall status
    try:
        cb_open = result["circuit_breakers"].get("open", 0)
        drift_status = result["config_drift"].get("status", "healthy")

        if cb_open > 0 or drift_status == "critical":
            result["overall_status"] = "critical"
        elif drift_status == "drifted":
            result["overall_status"] = "degraded"
        else:
            result["overall_status"] = "healthy"
    except Exception:
        result["overall_status"] = "unknown"

    return _to_json(result)
