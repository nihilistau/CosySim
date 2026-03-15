"""Config drift detection and remediation for CosySim.

Detects when disk configuration diverges from a known-good baseline
stored in a local SQLite database and optionally mirrored to Nexus.
Provides rollback, change tracking, and periodic drift checks.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Severity ────────────────────────────────────────────────────────────────


class DriftSeverity(enum.Enum):
    """Severity level for a detected configuration change."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ──── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class ConfigChange:
    """A single detected configuration change between baseline and current.

    Attributes:
        key: Dot-notation config path (e.g. ``lmstudio.port``).
        old_value: Value stored in the baseline.
        new_value: Value present in the current config.
        change_type: One of ``modified``, ``added``, ``removed``,
            ``type_changed``.
        severity: How dangerous this change is.
        timestamp: Unix timestamp of detection.
        source: How the change originated — ``disk``, ``env_override``,
            ``runtime_set``, ``reload``, or ``unknown``.
        auto_remediated: Whether the monitor already rolled the change back.
    """

    key: str
    old_value: Any
    new_value: Any
    change_type: str
    severity: DriftSeverity
    timestamp: float
    source: str
    auto_remediated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON storage."""
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class DriftResult:
    """Aggregate result of a single drift check.

    Attributes:
        check_time: Unix timestamp of the check.
        total_changes: Total number of differences found.
        drifted_keys: Keys whose values changed.
        added_keys: Keys present in current but not in baseline.
        removed_keys: Keys present in baseline but not in current.
        type_changes: Keys whose value type changed.
        severity_summary: Counts per severity level.
        baseline_hash: SHA-256 digest of the baseline snapshot.
        current_hash: SHA-256 digest of the live config.
        has_drift: ``True`` if any change was found.
    """

    check_time: float
    total_changes: int
    drifted_keys: List[ConfigChange] = field(default_factory=list)
    added_keys: List[ConfigChange] = field(default_factory=list)
    removed_keys: List[ConfigChange] = field(default_factory=list)
    type_changes: List[ConfigChange] = field(default_factory=list)
    severity_summary: Dict[str, int] = field(default_factory=dict)
    baseline_hash: str = ""
    current_hash: str = ""
    has_drift: bool = False

    # ── helpers ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialise entire result to a JSON-safe dict."""
        return {
            "check_time": self.check_time,
            "total_changes": self.total_changes,
            "drifted_keys": [c.to_dict() for c in self.drifted_keys],
            "added_keys": [c.to_dict() for c in self.added_keys],
            "removed_keys": [c.to_dict() for c in self.removed_keys],
            "type_changes": [c.to_dict() for c in self.type_changes],
            "severity_summary": self.severity_summary,
            "baseline_hash": self.baseline_hash,
            "current_hash": self.current_hash,
            "has_drift": self.has_drift,
        }

    def summary(self) -> str:
        """Return a concise human-readable summary string."""
        if not self.has_drift:
            return "No configuration drift detected."
        parts: List[str] = [
            f"Config drift detected: {self.total_changes} change(s).",
        ]
        for sev in ("critical", "warning", "info"):
            count = self.severity_summary.get(sev, 0)
            if count:
                parts.append(f"  {sev.upper()}: {count}")
        if self.drifted_keys:
            parts.append(
                f"  Modified keys: {', '.join(c.key for c in self.drifted_keys[:10])}"
            )
        if self.added_keys:
            parts.append(
                f"  Added keys: {', '.join(c.key for c in self.added_keys[:10])}"
            )
        if self.removed_keys:
            parts.append(
                f"  Removed keys: {', '.join(c.key for c in self.removed_keys[:10])}"
            )
        if self.type_changes:
            parts.append(
                f"  Type changes: {', '.join(c.key for c in self.type_changes[:10])}"
            )
        return "\n".join(parts)


# ──── Critical Keys ───────────────────────────────────────────────────────────

CRITICAL_KEYS: frozenset[str] = frozenset(
    {
        # Database
        "database.sqlite.path",
        "database.sqlite.wal_mode",
        # LLM / LMStudio
        "llm.default.base_url",
        "lmstudio.host",
        "lmstudio.port",
        "lmstudio.api_token",
        "lmstudio.vram_cap_mb",
        # Governance / security
        "comms.governance_enabled",
        "comms.safety.enabled",
        "comms.safety.blocked_categories",
        "security.auth_enabled",
        "security.allowed_origins",
        # Logging
        "logging.level",
        "logging.file",
        # Scene ports
        "scenes.phone.port",
        "scenes.penthouse.port",
        "scenes.dashboard.port",
        "scenes.bedroom.port",
        "scenes.neoncity.port",
        "scenes.hub.port",
        # Nexus
        "nexus.url",
        "nexus.enabled",
        # TTS
        "tts.engine",
        "tts.port",
        # ComfyUI
        "comfyui.host",
        "comfyui.port",
    }
)

# Keys matching any of these prefixes get WARNING by default even for value
# changes (rather than INFO).
_WARNING_PREFIXES: Tuple[str, ...] = (
    "comms.",
    "security.",
    "scenes.",
    "lmstudio.",
    "llm.",
    "database.",
    "nexus.",
    "tts.",
    "comfyui.",
)

# ──── SQLite Schema ───────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS config_baselines (
    id           TEXT    PRIMARY KEY,
    label        TEXT    NOT NULL,
    config_json  TEXT    NOT NULL,
    config_hash  TEXT    NOT NULL,
    created_at   REAL    NOT NULL,
    key_count    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS config_changes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    key              TEXT    NOT NULL,
    old_value        TEXT,
    new_value        TEXT,
    change_type      TEXT    NOT NULL,
    severity         TEXT    NOT NULL,
    source           TEXT    NOT NULL DEFAULT 'unknown',
    auto_remediated  INTEGER NOT NULL DEFAULT 0,
    timestamp        REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS drift_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_id     TEXT,
    total_changes   INTEGER NOT NULL,
    critical_count  INTEGER NOT NULL,
    warning_count   INTEGER NOT NULL,
    info_count      INTEGER NOT NULL,
    has_drift       INTEGER NOT NULL,
    baseline_hash   TEXT,
    current_hash    TEXT,
    result_json     TEXT,
    checked_at      REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_changes_key ON config_changes(key);
CREATE INDEX IF NOT EXISTS idx_changes_ts  ON config_changes(timestamp);
CREATE INDEX IF NOT EXISTS idx_checks_ts   ON drift_checks(checked_at);
CREATE INDEX IF NOT EXISTS idx_baselines_ts ON config_baselines(created_at);
"""

# ──── Monitor ─────────────────────────────────────────────────────────────────


class ConfigDriftMonitor:
    """Detects and tracks configuration drift between disk and stored baseline.

    Uses a local SQLite database to persist baselines, change logs, and drift
    check history.  Optionally mirrors important events to Nexus for
    cross-session visibility.

    Args:
        db_path: Path to the SQLite database file.  Created if absent.
    """

    def __init__(self, db_path: str = "data/config_drift.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        logger.debug("ConfigDriftMonitor initialised (db=%s)", self._db_path)

    # ── database helpers ──

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection (SQLite is per-thread safe)."""
        if self._conn is None or not _connection_alive(self._conn):
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            conn = self._get_conn()
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

    # ── baseline management ──

    def store_baseline(self, label: str = "auto") -> str:
        """Snapshot current config to SQLite and Nexus.

        Args:
            label: Human-readable label for this baseline (e.g.
                ``"daily_auto"``, ``"pre_deploy"``).

        Returns:
            The generated ``baseline_id``.
        """
        cfg = _get_current_config()
        flat = self._flatten_dict(cfg)
        config_hash = self._compute_hash(cfg)
        baseline_id = str(uuid.uuid4())
        now = time.time()

        config_json = _safe_json(cfg)

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO config_baselines
                    (id, label, config_json, config_hash, created_at, key_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (baseline_id, label, config_json, config_hash, now, len(flat)),
            )
            conn.commit()

        logger.info(
            "Stored config baseline %s (label=%s, keys=%d, hash=%s…)",
            baseline_id,
            label,
            len(flat),
            config_hash[:12],
        )

        # Best-effort mirror to Nexus
        _nexus_store(
            title=f"Config Baseline: {label} ({baseline_id[:8]})",
            content=(
                f"Baseline stored at {_iso(now)}.\n"
                f"Keys: {len(flat)} | Hash: {config_hash}\n"
                f"Label: {label}\n"
                f"Sample keys: {', '.join(sorted(flat)[:20])}"
            ),
            tags=["drift", "baseline", label],
        )

        return baseline_id

    def get_baseline(
        self, baseline_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the latest or a specific baseline config dict.

        Args:
            baseline_id: If ``None``, the most recent baseline is returned.

        Returns:
            The stored configuration dictionary, or ``None`` if no baseline
            exists.
        """
        with self._lock:
            conn = self._get_conn()
            if baseline_id:
                row = conn.execute(
                    "SELECT config_json FROM config_baselines WHERE id = ?",
                    (baseline_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT config_json FROM config_baselines "
                    "ORDER BY created_at DESC LIMIT 1",
                ).fetchone()

        if row is None:
            return None
        try:
            return json.loads(row["config_json"])
        except (json.JSONDecodeError, TypeError):
            logger.error("Corrupt baseline JSON for id=%s", baseline_id)
            return None

    def _get_latest_baseline_id(self) -> Optional[str]:
        """Return the id of the newest baseline, or ``None``."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT id FROM config_baselines ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    # ── drift checking ──

    def check_drift(self, auto_store: bool = True) -> DriftResult:
        """Compare current disk config against the stored baseline.

        The algorithm:

        1. Flatten both configs to dot-notation keys.
        2. Identify added / removed / modified keys.
        3. Detect type-only changes (same key, different Python type).
        4. Assign severity via :meth:`_classify_severity`.
        5. Persist the result in the ``drift_checks`` table.

        If no baseline exists yet, one is created automatically.

        Args:
            auto_store: Persist the drift result in the database.

        Returns:
            A :class:`DriftResult` summarising all detected changes.
        """
        now = time.time()

        baseline_dict = self.get_baseline()
        baseline_id = self._get_latest_baseline_id()
        if baseline_dict is None:
            logger.info("No baseline found — creating initial baseline.")
            baseline_id = self.store_baseline(label="initial_auto")
            baseline_dict = self.get_baseline(baseline_id)
            if baseline_dict is None:
                return DriftResult(check_time=now, total_changes=0)

        current_dict = _get_current_config()

        baseline_flat = self._flatten_dict(baseline_dict)
        current_flat = self._flatten_dict(current_dict)

        baseline_hash = self._compute_hash(baseline_dict)
        current_hash = self._compute_hash(current_dict)

        # Quick path — hashes match
        if baseline_hash == current_hash:
            result = DriftResult(
                check_time=now,
                total_changes=0,
                baseline_hash=baseline_hash,
                current_hash=current_hash,
                has_drift=False,
                severity_summary={"critical": 0, "warning": 0, "info": 0},
            )
            if auto_store:
                self._persist_drift_result(result, baseline_id)
            return result

        baseline_keys = set(baseline_flat.keys())
        current_keys = set(current_flat.keys())

        added_keys_set = current_keys - baseline_keys
        removed_keys_set = baseline_keys - current_keys
        common_keys = baseline_keys & current_keys

        drifted: List[ConfigChange] = []
        added: List[ConfigChange] = []
        removed: List[ConfigChange] = []
        type_changes: List[ConfigChange] = []

        for key in sorted(added_keys_set):
            sev = self._classify_severity(key, "added")
            change = ConfigChange(
                key=key,
                old_value=None,
                new_value=current_flat[key],
                change_type="added",
                severity=sev,
                timestamp=now,
                source="disk",
            )
            added.append(change)

        for key in sorted(removed_keys_set):
            sev = self._classify_severity(key, "removed")
            change = ConfigChange(
                key=key,
                old_value=baseline_flat[key],
                new_value=None,
                change_type="removed",
                severity=sev,
                timestamp=now,
                source="disk",
            )
            removed.append(change)

        for key in sorted(common_keys):
            old_val = baseline_flat[key]
            new_val = current_flat[key]
            if old_val == new_val:
                continue

            # Detect type-only changes
            if type(old_val) is not type(new_val) and old_val is not None and new_val is not None:
                sev = self._classify_severity(key, "type_changed")
                change = ConfigChange(
                    key=key,
                    old_value=old_val,
                    new_value=new_val,
                    change_type="type_changed",
                    severity=sev,
                    timestamp=now,
                    source="disk",
                )
                type_changes.append(change)
            else:
                sev = self._classify_severity(key, "modified")
                change = ConfigChange(
                    key=key,
                    old_value=old_val,
                    new_value=new_val,
                    change_type="modified",
                    severity=sev,
                    timestamp=now,
                    source="disk",
                )
                drifted.append(change)

        all_changes = drifted + added + removed + type_changes
        severity_summary = {"critical": 0, "warning": 0, "info": 0}
        for c in all_changes:
            severity_summary[c.severity.value] = (
                severity_summary.get(c.severity.value, 0) + 1
            )

        result = DriftResult(
            check_time=now,
            total_changes=len(all_changes),
            drifted_keys=drifted,
            added_keys=added,
            removed_keys=removed,
            type_changes=type_changes,
            severity_summary=severity_summary,
            baseline_hash=baseline_hash,
            current_hash=current_hash,
            has_drift=len(all_changes) > 0,
        )

        if auto_store:
            self._persist_drift_result(result, baseline_id)

        if result.has_drift:
            logger.warning(
                "Config drift detected: %d change(s) (critical=%d, warning=%d, info=%d)",
                result.total_changes,
                severity_summary["critical"],
                severity_summary["warning"],
                severity_summary["info"],
            )
            # Store individual changes
            for c in all_changes:
                self._persist_change(c)

            # Nexus alert for critical drift
            if severity_summary["critical"] > 0:
                critical_keys = [
                    c.key
                    for c in all_changes
                    if c.severity == DriftSeverity.CRITICAL
                ]
                _nexus_store(
                    title=f"CRITICAL Config Drift ({severity_summary['critical']} keys)",
                    content=(
                        f"Detected at {_iso(now)}.\n"
                        f"Critical keys: {', '.join(critical_keys)}\n\n"
                        f"{result.summary()}"
                    ),
                    tags=["drift", "critical", "alert"],
                )
        else:
            logger.debug("No config drift detected (hash=%s…)", current_hash[:12])

        return result

    def _persist_drift_result(
        self, result: DriftResult, baseline_id: Optional[str]
    ) -> None:
        """Write a drift check row to the database."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO drift_checks
                    (baseline_id, total_changes, critical_count, warning_count,
                     info_count, has_drift, baseline_hash, current_hash,
                     result_json, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline_id,
                    result.total_changes,
                    result.severity_summary.get("critical", 0),
                    result.severity_summary.get("warning", 0),
                    result.severity_summary.get("info", 0),
                    1 if result.has_drift else 0,
                    result.baseline_hash,
                    result.current_hash,
                    _safe_json(result.to_dict()),
                    result.check_time,
                ),
            )
            conn.commit()

    def _persist_change(self, change: ConfigChange) -> None:
        """Write a single config change row to the database."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO config_changes
                    (key, old_value, new_value, change_type, severity, source,
                     auto_remediated, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    change.key,
                    _safe_json(change.old_value),
                    _safe_json(change.new_value),
                    change.change_type,
                    change.severity.value,
                    change.source,
                    1 if change.auto_remediated else 0,
                    change.timestamp,
                ),
            )
            conn.commit()

    # ── history queries ──

    def get_drift_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent drift check results.

        Args:
            limit: Maximum number of rows.

        Returns:
            List of dicts with check metadata.
        """
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """
                SELECT id, baseline_id, total_changes, critical_count,
                       warning_count, info_count, has_drift,
                       baseline_hash, current_hash, checked_at
                FROM drift_checks
                ORDER BY checked_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_change_log(
        self, key: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Return recent config change events.

        Args:
            key: If provided, filter to a specific dot-notation key.
            limit: Maximum number of rows.

        Returns:
            List of change event dicts.
        """
        with self._lock:
            conn = self._get_conn()
            if key:
                rows = conn.execute(
                    """
                    SELECT id, key, old_value, new_value, change_type,
                           severity, source, auto_remediated, timestamp
                    FROM config_changes
                    WHERE key = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (key, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, key, old_value, new_value, change_type,
                           severity, source, auto_remediated, timestamp
                    FROM config_changes
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            # Deserialise stored JSON values
            for fld in ("old_value", "new_value"):
                if d[fld] is not None:
                    try:
                        d[fld] = json.loads(d[fld])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results

    # ── rollback ──

    def rollback_key(self, key: str) -> bool:
        """Revert a specific config key to its baseline value.

        1. Look up the baseline value for *key*.
        2. Call ``config.set(key, baseline_value)``.
        3. Record the rollback in the change log.

        Args:
            key: Dot-notation config path.

        Returns:
            ``True`` if the key was reverted, ``False`` if baseline is
            missing or the key was not found.
        """
        baseline = self.get_baseline()
        if baseline is None:
            logger.warning("Cannot rollback %s: no baseline stored.", key)
            return False

        flat = self._flatten_dict(baseline)
        if key not in flat:
            logger.warning("Key %s not found in baseline — cannot rollback.", key)
            return False

        baseline_value = flat[key]
        try:
            cfg = _get_config_manager()
            current_value = cfg.get(key)
            cfg.set(key, baseline_value)
        except Exception:
            logger.exception("Failed to rollback key %s", key)
            return False

        self.record_change(
            key=key,
            old_value=current_value,
            new_value=baseline_value,
            source="rollback",
        )
        logger.info("Rolled back %s to baseline value.", key)
        return True

    def rollback_all(self) -> int:
        """Revert ALL drifted keys to their baseline values.

        Returns:
            Number of keys successfully reverted.
        """
        result = self.check_drift(auto_store=False)
        if not result.has_drift:
            logger.info("No drift to rollback.")
            return 0

        all_changes = (
            result.drifted_keys
            + result.added_keys
            + result.removed_keys
            + result.type_changes
        )

        count = 0
        for change in all_changes:
            if change.change_type == "added":
                # Key was added (not in baseline) — we cannot "unset" via
                # the config manager, so skip.
                logger.debug(
                    "Skipping rollback of added key %s (no unset API).",
                    change.key,
                )
                continue
            if self.rollback_key(change.key):
                count += 1

        logger.info("Rolled back %d/%d drifted keys.", count, len(all_changes))
        return count

    # ── change recording ──

    def record_change(
        self,
        key: str,
        old_value: Any,
        new_value: Any,
        source: str = "unknown",
    ) -> None:
        """Record a config change event in the change log table.

        Called by the config hook wrapper or manually by callers who know a
        change has occurred.

        Args:
            key: Dot-notation config path.
            old_value: Previous value.
            new_value: New value.
            source: Origin of the change (``runtime_set``, ``reload``,
                ``disk``, ``rollback``, ``unknown``).
        """
        if old_value is not None and new_value is not None and type(old_value) is not type(new_value):
            change_type = "type_changed"
        elif old_value is None:
            change_type = "added"
        elif new_value is None:
            change_type = "removed"
        else:
            change_type = "modified"

        severity = self._classify_severity(key, change_type)
        now = time.time()

        change = ConfigChange(
            key=key,
            old_value=old_value,
            new_value=new_value,
            change_type=change_type,
            severity=severity,
            timestamp=now,
            source=source,
        )
        self._persist_change(change)

        if severity == DriftSeverity.CRITICAL:
            logger.warning(
                "CRITICAL config change: %s (%s → %s) [source=%s]",
                key,
                _truncate(old_value),
                _truncate(new_value),
                source,
            )
        else:
            logger.debug(
                "Config change recorded: %s (%s) [source=%s]",
                key,
                change_type,
                source,
            )

    # ── health ──

    def get_health(self) -> Dict[str, Any]:
        """Return drift monitor health status.

        Returns:
            Dict with ``last_check_time``, ``last_baseline_time``,
            ``drift_count``, ``critical_drift_count``, and ``status``
            (one of ``healthy``, ``drifted``, ``critical``).
        """
        with self._lock:
            conn = self._get_conn()

            last_check_row = conn.execute(
                "SELECT checked_at, has_drift, critical_count "
                "FROM drift_checks ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()

            last_baseline_row = conn.execute(
                "SELECT created_at FROM config_baselines "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

            # Count drift in last 24 hours
            cutoff = time.time() - 86400
            drift_24h_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM drift_checks "
                "WHERE checked_at > ? AND has_drift = 1",
                (cutoff,),
            ).fetchone()
            critical_24h_row = conn.execute(
                "SELECT SUM(critical_count) as cnt FROM drift_checks "
                "WHERE checked_at > ? AND critical_count > 0",
                (cutoff,),
            ).fetchone()

        last_check_time = last_check_row["checked_at"] if last_check_row else None
        last_baseline_time = (
            last_baseline_row["created_at"] if last_baseline_row else None
        )
        drift_count = drift_24h_row["cnt"] if drift_24h_row else 0
        critical_drift_count = (
            int(critical_24h_row["cnt"]) if critical_24h_row and critical_24h_row["cnt"] else 0
        )

        if critical_drift_count > 0:
            status = "critical"
        elif drift_count > 0:
            status = "drifted"
        else:
            status = "healthy"

        return {
            "last_check_time": last_check_time,
            "last_baseline_time": last_baseline_time,
            "drift_count": drift_count,
            "critical_drift_count": critical_drift_count,
            "status": status,
            "db_path": str(self._db_path),
        }

    # ── static helpers ──

    @staticmethod
    def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        """Flatten a nested dict to dot-notation keys.

        Args:
            d: The nested dictionary.
            prefix: Current key prefix (used in recursion).

        Returns:
            Flat dict mapping ``"a.b.c"`` to leaf values.
        """
        items: Dict[str, Any] = {}
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                items.update(ConfigDriftMonitor._flatten_dict(value, full_key))
            else:
                items[full_key] = value
        return items

    @staticmethod
    def _compute_hash(config: Dict[str, Any]) -> str:
        """SHA-256 digest of a deterministically serialised config dict.

        Args:
            config: Configuration dictionary.

        Returns:
            Hex-encoded SHA-256 hash string.
        """
        serialised = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(serialised).hexdigest()

    def _classify_severity(self, key: str, change_type: str) -> DriftSeverity:
        """Determine severity based on the key and type of change.

        Args:
            key: Dot-notation config key.
            change_type: One of ``modified``, ``added``, ``removed``,
                ``type_changed``.

        Returns:
            The appropriate :class:`DriftSeverity`.
        """
        # Critical keys are always CRITICAL regardless of change type
        if key in CRITICAL_KEYS:
            return DriftSeverity.CRITICAL

        # Type changes are at least WARNING
        if change_type == "type_changed":
            return DriftSeverity.WARNING

        # Removed keys are at least WARNING
        if change_type == "removed":
            return DriftSeverity.WARNING

        # Keys under sensitive prefixes get WARNING
        if any(key.startswith(p) for p in _WARNING_PREFIXES):
            if change_type in ("modified", "added"):
                return DriftSeverity.WARNING

        return DriftSeverity.INFO

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


# ──── Singleton ───────────────────────────────────────────────────────────────

_monitor: Optional[ConfigDriftMonitor] = None
_monitor_lock = threading.Lock()


def get_drift_monitor(db_path: str = "data/config_drift.db") -> ConfigDriftMonitor:
    """Get or create the global :class:`ConfigDriftMonitor` singleton.

    Args:
        db_path: Database path (only used on first call).

    Returns:
        The singleton monitor instance.
    """
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = ConfigDriftMonitor(db_path=db_path)
    return _monitor


# ──── Config Hooks ────────────────────────────────────────────────────────────


def install_config_hooks(monitor: Optional[ConfigDriftMonitor] = None) -> None:
    """Monkey-patch ``Config.set()`` to track changes via the drift monitor.

    Wraps the original ``set()`` so that every programmatic config change is
    recorded in the change log.

    Args:
        monitor: The monitor to record changes with.  Defaults to the
            global singleton.
    """
    if monitor is None:
        monitor = get_drift_monitor()

    try:
        cfg = _get_config_manager()
    except Exception:
        logger.warning("Cannot install config hooks: config manager unavailable.")
        return

    # Guard against double-wrapping
    if getattr(cfg.set, "_drift_hooked", False):
        logger.debug("Config hooks already installed — skipping.")
        return

    original_set = cfg.set

    def tracked_set(path: str, value: Any) -> None:
        """Wrapped ``Config.set()`` that records changes."""
        old_value = cfg.get(path)
        original_set(path, value)
        if old_value != value:
            monitor.record_change(path, old_value, value, source="runtime_set")

    tracked_set._drift_hooked = True  # type: ignore[attr-defined]
    cfg.set = tracked_set  # type: ignore[assignment]
    logger.debug("Config drift hooks installed.")


def uninstall_config_hooks() -> None:
    """Remove the drift-tracking wrapper from ``Config.set()``.

    Restores the original ``set()`` method if a wrapped version is active.
    """
    try:
        cfg = _get_config_manager()
    except Exception:
        return

    original = getattr(cfg.set, "__wrapped__", None)
    if original is not None:
        cfg.set = original  # type: ignore[assignment]
        logger.debug("Config drift hooks uninstalled.")


# ──── Scheduler Integration ───────────────────────────────────────────────────


def register_drift_tasks(
    monitor: Optional[ConfigDriftMonitor] = None,
) -> None:
    """Register periodic drift check and baseline refresh with the scheduler.

    Silently no-ops if the scheduler is unavailable.

    Args:
        monitor: The monitor to use.  Defaults to the global singleton.
    """
    if monitor is None:
        monitor = get_drift_monitor()

    try:
        from engine.nexus.scheduler_daemon import TaskSchedulerDaemon

        daemon = TaskSchedulerDaemon()
        daemon.register(
            task_id="config_drift_check",
            name="Config Drift Check",
            schedule="every_30m",
            callback=lambda: monitor.check_drift(auto_store=True),
            enabled=True,
        )
        daemon.register(
            task_id="config_baseline_refresh",
            name="Config Baseline Refresh",
            schedule="daily",
            callback=lambda: monitor.store_baseline(label="daily_auto"),
            enabled=True,
        )
        logger.info("Registered drift tasks with scheduler daemon.")
    except Exception:
        logger.debug("Scheduler unavailable — drift tasks not registered.", exc_info=True)


# ──── Convenience CLI ─────────────────────────────────────────────────────────


def run_cli() -> None:
    """Minimal CLI entry-point for ad-hoc drift operations.

    Usage::

        python -m engine.nexus.config_drift check
        python -m engine.nexus.config_drift baseline [label]
        python -m engine.nexus.config_drift history
        python -m engine.nexus.config_drift health
        python -m engine.nexus.config_drift rollback <key>
        python -m engine.nexus.config_drift rollback-all
        python -m engine.nexus.config_drift changelog [key]
    """
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print(run_cli.__doc__)
        return

    cmd = args[0].lower()
    monitor = get_drift_monitor()

    if cmd == "check":
        result = monitor.check_drift()
        print(result.summary())

    elif cmd == "baseline":
        label = args[1] if len(args) > 1 else "manual"
        bid = monitor.store_baseline(label=label)
        print(f"Baseline stored: {bid}")

    elif cmd == "history":
        limit = int(args[1]) if len(args) > 1 else 20
        for row in monitor.get_drift_history(limit=limit):
            ts = _iso(row["checked_at"])
            drift_flag = "DRIFTED" if row["has_drift"] else "clean"
            print(
                f"  {ts}  {drift_flag}  "
                f"changes={row['total_changes']}  "
                f"crit={row['critical_count']}  "
                f"warn={row['warning_count']}  "
                f"info={row['info_count']}"
            )

    elif cmd == "health":
        health = monitor.get_health()
        for k, v in health.items():
            print(f"  {k}: {v}")

    elif cmd == "rollback":
        if len(args) < 2:
            print("Usage: rollback <key>")
            return
        key = args[1]
        ok = monitor.rollback_key(key)
        print(f"Rollback {'succeeded' if ok else 'failed'} for {key}")

    elif cmd == "rollback-all":
        count = monitor.rollback_all()
        print(f"Rolled back {count} key(s)")

    elif cmd == "changelog":
        key = args[1] if len(args) > 1 else None
        limit = int(args[2]) if len(args) > 2 else 30
        for row in monitor.get_change_log(key=key, limit=limit):
            ts = _iso(row["timestamp"])
            print(
                f"  {ts}  [{row['severity']}] {row['key']}  "
                f"{row['change_type']}  {_truncate(row['old_value'])} → "
                f"{_truncate(row['new_value'])}  (src={row['source']})"
            )

    else:
        print(f"Unknown command: {cmd}")
        print(run_cli.__doc__)


# ──── Private Helpers ─────────────────────────────────────────────────────────


def _get_config_manager() -> Any:
    """Import and return the active ConfigManager."""
    from engine.config import get_config

    return get_config()


def _get_current_config() -> Dict[str, Any]:
    """Return the current full config dict from the config manager."""
    try:
        cfg = _get_config_manager()
        raw = cfg.get_all()
        if isinstance(raw, dict):
            return raw
        return {}
    except Exception:
        logger.warning("Failed to read current config — returning empty dict.")
        return {}


def _safe_json(obj: Any) -> str:
    """JSON-serialise *obj*, falling back to ``str()`` for non-serialisable types."""
    try:
        return json.dumps(obj, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(obj))


def _truncate(value: Any, max_len: int = 60) -> str:
    """Truncate a value's repr for log lines."""
    s = repr(value)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _iso(ts: float) -> str:
    """Format a Unix timestamp as an ISO-8601 string."""
    import datetime

    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _nexus_store(title: str, content: str, tags: Optional[List[str]] = None) -> None:
    """Best-effort store to Nexus.  Never raises."""
    try:
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        client.add_entry(
            title=title,
            content=content,
            content_type="note",
            category="config",
            tags=tags or ["drift"],
        )
    except Exception:
        logger.debug("Nexus store skipped (unavailable).", exc_info=True)


def _connection_alive(conn: sqlite3.Connection) -> bool:
    """Check whether a SQLite connection is still usable."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


# ──── Module Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    run_cli()
