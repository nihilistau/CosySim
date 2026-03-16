"""Schema Migration Engine for CosySim.

Centralized schema version tracking, drift detection, and migration system
for all 24+ SQLite databases across the project.

Usage::

    from engine.nexus.schema_migration import get_migration_engine, Migration

    engine = get_migration_engine()
    engine.register_migration(Migration(
        db_name="metrics",
        version=1,
        description="Add tags column to entries",
        up_sql="ALTER TABLE entries ADD COLUMN tags TEXT DEFAULT ''",
        down_sql="ALTER TABLE entries_backup ...",
    ))
    engine.run_pending("metrics")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ──── Constants ────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_REGISTRY_DB_PATH = _DATA_DIR / "schema_migrations.db"

_CONTENT_SIMULATION_DB = _PROJECT_ROOT / "content" / "simulation" / "simulation.db"

_KNOWN_DB_DIRS: List[Path] = [
    _DATA_DIR,
    _PROJECT_ROOT / "content" / "simulation",
]


# ──── Enums ────

class DiffType(Enum):
    """Types of schema differences detected during drift analysis."""

    MISSING_TABLE = "MISSING_TABLE"
    EXTRA_TABLE = "EXTRA_TABLE"
    MISSING_COLUMN = "MISSING_COLUMN"
    EXTRA_COLUMN = "EXTRA_COLUMN"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_INDEX = "MISSING_INDEX"


class MigrationDirection(Enum):
    """Direction a migration is applied in."""

    UP = "up"
    DOWN = "down"


# ──── Dataclasses ────

@dataclass
class Migration:
    """A single schema migration for a specific database.

    Args:
        db_name: Logical database name (e.g. ``"metrics"``).
        version: Monotonically increasing version number.
        description: Human-readable description of the change.
        up_sql: SQL string to apply the migration.
        up_fn: Python callable to apply the migration.  Receives a
            ``sqlite3.Connection`` as its sole argument.
        down_sql: SQL string to rollback the migration.
        down_fn: Python callable to rollback the migration.
        applied_at: ISO-8601 timestamp when the migration was applied.
    """

    db_name: str
    version: int
    description: str
    up_sql: Optional[str] = None
    up_fn: Optional[Callable[[sqlite3.Connection], None]] = None
    down_sql: Optional[str] = None
    down_fn: Optional[Callable[[sqlite3.Connection], None]] = None
    applied_at: Optional[str] = None


@dataclass
class SchemaDiff:
    """A single difference between two schema snapshots.

    Args:
        table: The table that differs.
        column: The column involved (empty for table-level diffs).
        diff_type: Category of difference.
        expected: Expected value (type, presence, etc.).
        actual: Actual value found in the database.
    """

    table: str
    column: str
    diff_type: DiffType
    expected: str = ""
    actual: str = ""

    def __str__(self) -> str:
        parts = [f"{self.diff_type.value}: table={self.table}"]
        if self.column:
            parts.append(f"column={self.column}")
        if self.expected:
            parts.append(f"expected={self.expected}")
        if self.actual:
            parts.append(f"actual={self.actual}")
        return ", ".join(parts)


@dataclass
class ColumnInfo:
    """Metadata for a single column in a table.

    Args:
        name: Column name.
        col_type: Column type as declared in the schema.
        notnull: Whether the column has a NOT NULL constraint.
        default_value: Default value expression, if any.
        pk: Whether the column is part of the primary key.
    """

    name: str
    col_type: str
    notnull: bool = False
    default_value: Optional[str] = None
    pk: bool = False


@dataclass
class TableInfo:
    """Metadata for a single table in a schema snapshot.

    Args:
        name: Table name.
        columns: Ordered list of columns in the table.
        indexes: List of index names on this table.
    """

    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    indexes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "name": self.name,
            "columns": [
                {
                    "name": c.name,
                    "type": c.col_type,
                    "notnull": c.notnull,
                    "default": c.default_value,
                    "pk": c.pk,
                }
                for c in self.columns
            ],
            "indexes": self.indexes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TableInfo:
        """Deserialise from a dictionary (inverse of ``to_dict``)."""
        columns = [
            ColumnInfo(
                name=c["name"],
                col_type=c.get("type", ""),
                notnull=c.get("notnull", False),
                default_value=c.get("default"),
                pk=c.get("pk", False),
            )
            for c in data.get("columns", [])
        ]
        return cls(
            name=data["name"],
            columns=columns,
            indexes=data.get("indexes", []),
        )


@dataclass
class SchemaSnapshot:
    """Complete schema state of a database at a point in time.

    Args:
        db_name: Logical database name.
        tables: Mapping of table name → ``TableInfo``.
        captured_at: ISO-8601 timestamp of capture.
    """

    db_name: str
    tables: Dict[str, TableInfo] = field(default_factory=dict)
    captured_at: str = ""

    def to_json(self) -> str:
        """Serialise the snapshot to a JSON string."""
        return json.dumps(
            {
                "db_name": self.db_name,
                "tables": {n: t.to_dict() for n, t in self.tables.items()},
                "captured_at": self.captured_at,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> SchemaSnapshot:
        """Deserialise from a JSON string."""
        data = json.loads(raw)
        tables = {
            n: TableInfo.from_dict(t) for n, t in data.get("tables", {}).items()
        }
        return cls(
            db_name=data.get("db_name", ""),
            tables=tables,
            captured_at=data.get("captured_at", ""),
        )


@dataclass
class DatabaseInfo:
    """Metadata about a discovered database file.

    Args:
        name: Logical database name (stem of the file).
        path: Absolute path to the ``.db`` file.
        current_version: Current migration version (0 if untracked).
        table_count: Number of user tables in the database.
        size_bytes: File size in bytes.
        last_modified: ISO-8601 timestamp of last modification.
    """

    name: str
    path: str
    current_version: int = 0
    table_count: int = 0
    size_bytes: int = 0
    last_modified: str = ""


@dataclass
class MigrationStatus:
    """Status report for a single database's migrations.

    Args:
        db_name: Logical database name.
        current_version: Highest applied version.
        pending_count: Number of registered but unapplied migrations.
        pending_versions: List of unapplied version numbers.
        registered_path: Filesystem path for the database, if known.
    """

    db_name: str
    current_version: int = 0
    pending_count: int = 0
    pending_versions: List[int] = field(default_factory=list)
    registered_path: str = ""


# ──── Schema Snapshot Capture ────

def capture_snapshot(db_path: str, db_name: str = "") -> SchemaSnapshot:
    """Capture the current schema of a SQLite database.

    Args:
        db_path: Filesystem path to the ``.db`` file.
        db_name: Logical name to store in the snapshot (defaults to stem).

    Returns:
        A ``SchemaSnapshot`` reflecting the live schema.
    """
    if not db_name:
        db_name = Path(db_path).stem

    snapshot = SchemaSnapshot(
        db_name=db_name,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )

    if not os.path.exists(db_path):
        logger.warning("Database file does not exist: %s", db_path)
        return snapshot

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Discover tables (skip internal SQLite tables)
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        table_names = [row["name"] for row in cur.fetchall()]

        for tbl in table_names:
            cur.execute(f"PRAGMA table_info([{tbl}])")
            columns: List[ColumnInfo] = []
            for col in cur.fetchall():
                columns.append(
                    ColumnInfo(
                        name=col["name"],
                        col_type=col["type"] or "",
                        notnull=bool(col["notnull"]),
                        default_value=col["dflt_value"],
                        pk=bool(col["pk"]),
                    )
                )

            cur.execute(f"PRAGMA index_list([{tbl}])")
            indexes = [idx["name"] for idx in cur.fetchall() if idx["name"]]

            snapshot.tables[tbl] = TableInfo(
                name=tbl, columns=columns, indexes=indexes
            )
    finally:
        conn.close()

    return snapshot


def compare_snapshots(
    expected: SchemaSnapshot, actual: SchemaSnapshot
) -> List[SchemaDiff]:
    """Compare two schema snapshots and return a list of differences.

    Args:
        expected: The schema we expect to find.
        actual: The schema we actually found.

    Returns:
        A list of ``SchemaDiff`` objects describing every discrepancy.
    """
    diffs: List[SchemaDiff] = []

    expected_tables = set(expected.tables.keys())
    actual_tables = set(actual.tables.keys())

    # Missing tables
    for tbl in sorted(expected_tables - actual_tables):
        diffs.append(
            SchemaDiff(table=tbl, column="", diff_type=DiffType.MISSING_TABLE)
        )

    # Extra tables
    for tbl in sorted(actual_tables - expected_tables):
        diffs.append(
            SchemaDiff(table=tbl, column="", diff_type=DiffType.EXTRA_TABLE)
        )

    # Compare columns in common tables
    for tbl in sorted(expected_tables & actual_tables):
        exp_tbl = expected.tables[tbl]
        act_tbl = actual.tables[tbl]

        exp_cols = {c.name: c for c in exp_tbl.columns}
        act_cols = {c.name: c for c in act_tbl.columns}

        for col_name in sorted(set(exp_cols) - set(act_cols)):
            diffs.append(
                SchemaDiff(
                    table=tbl,
                    column=col_name,
                    diff_type=DiffType.MISSING_COLUMN,
                )
            )

        for col_name in sorted(set(act_cols) - set(exp_cols)):
            diffs.append(
                SchemaDiff(
                    table=tbl,
                    column=col_name,
                    diff_type=DiffType.EXTRA_COLUMN,
                )
            )

        for col_name in sorted(set(exp_cols) & set(act_cols)):
            exp_type = (exp_cols[col_name].col_type or "").upper()
            act_type = (act_cols[col_name].col_type or "").upper()
            if exp_type != act_type:
                diffs.append(
                    SchemaDiff(
                        table=tbl,
                        column=col_name,
                        diff_type=DiffType.TYPE_MISMATCH,
                        expected=exp_type,
                        actual=act_type,
                    )
                )

        # Compare indexes
        exp_idxs = set(exp_tbl.indexes)
        act_idxs = set(act_tbl.indexes)
        for idx_name in sorted(exp_idxs - act_idxs):
            diffs.append(
                SchemaDiff(
                    table=tbl,
                    column=idx_name,
                    diff_type=DiffType.MISSING_INDEX,
                )
            )

    return diffs


# ──── Thread-Local Connection Pool ────

class _ConnectionPool:
    """Thread-local SQLite connection pool.

    Each thread gets its own connection per database path, avoiding
    SQLite's single-thread constraint.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def get(self, db_path: str) -> sqlite3.Connection:
        """Return (or create) a connection for the current thread.

        Args:
            db_path: Filesystem path to the SQLite database.

        Returns:
            A ``sqlite3.Connection`` bound to the current thread.
        """
        if not hasattr(self._local, "connections"):
            self._local.connections: Dict[str, sqlite3.Connection] = {}

        if db_path not in self._local.connections:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.connections[db_path] = conn

        return self._local.connections[db_path]

    def close_all(self) -> None:
        """Close all connections held by the current thread."""
        if not hasattr(self._local, "connections"):
            return
        for conn in self._local.connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._local.connections.clear()


# ──── Database Path Resolution ────

def _resolve_db_path(db_name: str) -> str:
    """Resolve a logical database name to a filesystem path.

    Checks common locations in order:
    1. ``data/{db_name}.db``
    2. ``content/simulation/{db_name}.db`` (for simulation DB)

    Args:
        db_name: Logical name such as ``"metrics"`` or ``"simulation"``.

    Returns:
        Absolute path string to the database file.
    """
    # Direct path supplied
    if os.path.isabs(db_name) or db_name.endswith(".db"):
        return str(Path(db_name).resolve())

    primary = _DATA_DIR / f"{db_name}.db"
    if primary.exists():
        return str(primary)

    content_path = _PROJECT_ROOT / "content" / "simulation" / f"{db_name}.db"
    if content_path.exists():
        return str(content_path)

    # Default to data/ even if the file doesn't exist yet
    return str(primary)


# ──── SchemaMigrationEngine ────

class SchemaMigrationEngine:
    """Centralized schema migration engine for all CosySim databases.

    Manages a migration registry, tracks schema versions, detects drift,
    and applies or rolls back migrations.  The registry itself is stored
    in ``data/schema_migrations.db``.
    """

    def __init__(self, registry_path: Optional[str] = None) -> None:
        self._registry_path = str(registry_path or _REGISTRY_DB_PATH)
        self._lock = threading.Lock()
        self._pool = _ConnectionPool()
        self._migrations: Dict[str, List[Migration]] = {}  # db_name → sorted list
        self._db_paths: Dict[str, str] = {}  # db_name → resolved path

        os.makedirs(os.path.dirname(self._registry_path), exist_ok=True)
        self._init_registry()

    # ──── Registry Initialisation ────

    def _init_registry(self) -> None:
        """Create the migration registry tables if they don't exist."""
        conn = self._registry_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS _migration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_name TEXT NOT NULL,
                version INTEGER NOT NULL,
                description TEXT,
                direction TEXT NOT NULL DEFAULT 'up',
                applied_at TEXT NOT NULL,
                duration_ms REAL,
                success INTEGER NOT NULL DEFAULT 1,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS _db_versions (
                db_name TEXT PRIMARY KEY,
                current_version INTEGER NOT NULL DEFAULT 0,
                last_migrated_at TEXT,
                registered_path TEXT
            );

            CREATE TABLE IF NOT EXISTS _schema_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_name TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                captured_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()

    def _registry_conn(self) -> sqlite3.Connection:
        """Return the thread-local connection to the migration registry DB."""
        return self._pool.get(self._registry_path)

    # ──── Migration Registration ────

    def register_migration(self, migration: Migration) -> None:
        """Register a single migration.

        Args:
            migration: The ``Migration`` to register.

        Raises:
            ValueError: If a migration with the same db_name and version
                already exists.
        """
        with self._lock:
            db_name = migration.db_name
            if db_name not in self._migrations:
                self._migrations[db_name] = []

            existing_versions = {m.version for m in self._migrations[db_name]}
            if migration.version in existing_versions:
                raise ValueError(
                    f"Migration version {migration.version} already registered "
                    f"for database '{db_name}'"
                )

            self._migrations[db_name].append(migration)
            self._migrations[db_name].sort(key=lambda m: m.version)

            # Ensure version tracking row exists
            self._ensure_db_tracked(db_name)

        logger.debug(
            "Registered migration v%d for '%s': %s",
            migration.version,
            db_name,
            migration.description,
        )

    def register_migrations(
        self, db_name: str, migrations: Sequence[Migration]
    ) -> None:
        """Register multiple migrations for a database.

        Args:
            db_name: Target database name (overrides each migration's
                ``db_name`` if they differ).
            migrations: Sequence of migrations to register.
        """
        for m in migrations:
            if m.db_name != db_name:
                m = Migration(
                    db_name=db_name,
                    version=m.version,
                    description=m.description,
                    up_sql=m.up_sql,
                    up_fn=m.up_fn,
                    down_sql=m.down_sql,
                    down_fn=m.down_fn,
                    applied_at=m.applied_at,
                )
            self.register_migration(m)

    def _ensure_db_tracked(self, db_name: str) -> None:
        """Ensure a ``_db_versions`` row exists for *db_name*."""
        conn = self._registry_conn()
        row = conn.execute(
            "SELECT 1 FROM _db_versions WHERE db_name = ?", (db_name,)
        ).fetchone()
        if not row:
            resolved = _resolve_db_path(db_name)
            conn.execute(
                "INSERT INTO _db_versions (db_name, current_version, registered_path) "
                "VALUES (?, 0, ?)",
                (db_name, resolved),
            )
            conn.commit()
            self._db_paths[db_name] = resolved

    def set_db_path(self, db_name: str, path: str) -> None:
        """Explicitly set the filesystem path for a logical database name.

        Args:
            db_name: Logical database name.
            path: Absolute or relative filesystem path.
        """
        resolved = str(Path(path).resolve())
        with self._lock:
            self._db_paths[db_name] = resolved
            conn = self._registry_conn()
            conn.execute(
                "INSERT INTO _db_versions (db_name, current_version, registered_path) "
                "VALUES (?, 0, ?) "
                "ON CONFLICT(db_name) DO UPDATE SET registered_path = excluded.registered_path",
                (db_name, resolved),
            )
            conn.commit()

    def _get_db_path(self, db_name: str) -> str:
        """Resolve the filesystem path for a database name.

        Args:
            db_name: Logical database name.

        Returns:
            Absolute path string.
        """
        if db_name in self._db_paths:
            return self._db_paths[db_name]

        # Check registry
        conn = self._registry_conn()
        row = conn.execute(
            "SELECT registered_path FROM _db_versions WHERE db_name = ?",
            (db_name,),
        ).fetchone()
        if row and row["registered_path"]:
            self._db_paths[db_name] = row["registered_path"]
            return row["registered_path"]

        resolved = _resolve_db_path(db_name)
        self._db_paths[db_name] = resolved
        return resolved

    # ──── Version Queries ────

    def _get_current_version(self, db_name: str) -> int:
        """Read the current schema version from the registry.

        Args:
            db_name: Logical database name.

        Returns:
            Current version integer (0 if untracked).
        """
        conn = self._registry_conn()
        row = conn.execute(
            "SELECT current_version FROM _db_versions WHERE db_name = ?",
            (db_name,),
        ).fetchone()
        return row["current_version"] if row else 0

    def _set_current_version(self, db_name: str, version: int) -> None:
        """Update the current version for a database.

        Args:
            db_name: Logical database name.
            version: New current version.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._registry_conn()
        conn.execute(
            "INSERT INTO _db_versions (db_name, current_version, last_migrated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(db_name) DO UPDATE SET "
            "current_version = excluded.current_version, "
            "last_migrated_at = excluded.last_migrated_at",
            (db_name, version, now),
        )
        conn.commit()

    # ──── Migration Execution ────

    def run_pending(self, db_name: str) -> List[int]:
        """Run all pending (unapplied) migrations for a database.

        Migrations are applied in version order.  Each migration runs in
        its own transaction.

        Args:
            db_name: Logical database name.

        Returns:
            List of version numbers that were successfully applied.

        Raises:
            RuntimeError: If a migration fails (partial application is
                possible — already-applied migrations are not rolled back).
        """
        current = self._get_current_version(db_name)
        pending = self._get_pending_migrations(db_name, current)

        if not pending:
            logger.debug("No pending migrations for '%s' (at v%d)", db_name, current)
            return []

        db_path = self._get_db_path(db_name)
        applied: List[int] = []

        for mig in pending:
            logger.info(
                "Applying migration v%d to '%s': %s",
                mig.version,
                db_name,
                mig.description,
            )
            start = time.monotonic()
            error_msg: Optional[str] = None
            success = True

            try:
                self._apply_migration(db_path, mig, MigrationDirection.UP)
            except Exception as exc:
                error_msg = str(exc)
                success = False
                logger.error(
                    "Migration v%d for '%s' failed: %s",
                    mig.version,
                    db_name,
                    exc,
                )

            duration_ms = (time.monotonic() - start) * 1000.0
            self._record_history(
                db_name=db_name,
                version=mig.version,
                description=mig.description,
                direction=MigrationDirection.UP,
                duration_ms=duration_ms,
                success=success,
                error_message=error_msg,
            )

            if not success:
                self._log_to_nexus(
                    f"Migration FAILED: {db_name} v{mig.version}",
                    f"Error applying migration v{mig.version} "
                    f"({mig.description}) to {db_name}: {error_msg}",
                    tags=["migration", "schema", "error"],
                )
                raise RuntimeError(
                    f"Migration v{mig.version} for '{db_name}' failed: {error_msg}"
                )

            self._set_current_version(db_name, mig.version)
            applied.append(mig.version)

        if applied:
            self._log_to_nexus(
                f"Migrations applied: {db_name} → v{applied[-1]}",
                f"Applied {len(applied)} migration(s) to '{db_name}': "
                f"versions {applied}. "
                f"Descriptions: {[m.description for m in pending if m.version in applied]}",
                tags=["migration", "schema"],
            )

        return applied

    def run_all_pending(self) -> Dict[str, List[int]]:
        """Run pending migrations for ALL registered databases.

        Returns:
            Mapping of db_name → list of applied version numbers.
        """
        results: Dict[str, List[int]] = {}
        with self._lock:
            db_names = list(self._migrations.keys())

        for db_name in sorted(db_names):
            try:
                applied = self.run_pending(db_name)
                if applied:
                    results[db_name] = applied
            except RuntimeError as exc:
                logger.error("Migration run halted for '%s': %s", db_name, exc)
                results[db_name] = []

        return results

    def rollback(self, db_name: str, target_version: int) -> List[int]:
        """Rollback a database to a target version.

        Migrations are reversed in descending version order from the
        current version down to (but not including) *target_version*.

        Args:
            db_name: Logical database name.
            target_version: Version to roll back to.  Migrations with
                version > target_version are undone.

        Returns:
            List of version numbers that were rolled back.

        Raises:
            ValueError: If target_version is invalid.
            RuntimeError: If a rollback step fails.
        """
        current = self._get_current_version(db_name)
        if target_version < 0:
            raise ValueError("target_version must be >= 0")
        if target_version >= current:
            logger.debug(
                "Nothing to rollback for '%s': target v%d >= current v%d",
                db_name,
                target_version,
                current,
            )
            return []

        with self._lock:
            all_migs = self._migrations.get(db_name, [])

        to_rollback = sorted(
            [m for m in all_migs if target_version < m.version <= current],
            key=lambda m: m.version,
            reverse=True,
        )

        if not to_rollback:
            logger.warning(
                "No registered migrations to rollback for '%s' from v%d to v%d",
                db_name,
                current,
                target_version,
            )
            return []

        db_path = self._get_db_path(db_name)
        rolled_back: List[int] = []

        skipped: List[int] = []

        for mig in to_rollback:
            if mig.down_sql is None and mig.down_fn is None:
                logger.warning(
                    "Migration v%d for '%s' has no rollback defined — "
                    "marking as rolled back (no-op)",
                    mig.version,
                    db_name,
                )
                skipped.append(mig.version)
                rolled_back.append(mig.version)
                continue

            logger.info(
                "Rolling back migration v%d from '%s': %s",
                mig.version,
                db_name,
                mig.description,
            )
            start = time.monotonic()
            error_msg: Optional[str] = None
            success = True

            try:
                self._apply_migration(db_path, mig, MigrationDirection.DOWN)
            except Exception as exc:
                error_msg = str(exc)
                success = False
                logger.error(
                    "Rollback v%d for '%s' failed: %s",
                    mig.version,
                    db_name,
                    exc,
                )

            duration_ms = (time.monotonic() - start) * 1000.0
            self._record_history(
                db_name=db_name,
                version=mig.version,
                description=mig.description,
                direction=MigrationDirection.DOWN,
                duration_ms=duration_ms,
                success=success,
                error_message=error_msg,
            )

            if not success:
                self._log_to_nexus(
                    f"Rollback FAILED: {db_name} v{mig.version}",
                    f"Error rolling back v{mig.version} ({mig.description}) "
                    f"on {db_name}: {error_msg}",
                    tags=["migration", "schema", "rollback", "error"],
                )
                raise RuntimeError(
                    f"Rollback v{mig.version} for '{db_name}' failed: {error_msg}"
                )

            rolled_back.append(mig.version)

        # Set version to target
        if rolled_back:
            self._set_current_version(db_name, target_version)
            skipped_note = (
                f" (skipped no-op: {skipped})" if skipped else ""
            )
            self._log_to_nexus(
                f"Rollback complete: {db_name} → v{target_version}",
                f"Rolled back {len(rolled_back)} migration(s) on '{db_name}': "
                f"versions {rolled_back}{skipped_note} → now at v{target_version}.",
                tags=["migration", "schema", "rollback"],
            )

        return rolled_back

    def _apply_migration(
        self,
        db_path: str,
        migration: Migration,
        direction: MigrationDirection,
    ) -> None:
        """Execute a single migration step (up or down).

        Args:
            db_path: Filesystem path to the target database.
            migration: The migration to apply.
            direction: Whether to apply ``up`` or ``down``.

        Raises:
            RuntimeError: If both sql and fn are ``None`` for the direction.
            Exception: Re-raises any error from the migration body.
        """
        if direction == MigrationDirection.UP:
            sql = migration.up_sql
            fn = migration.up_fn
        else:
            sql = migration.down_sql
            fn = migration.down_fn

        if sql is None and fn is None:
            raise RuntimeError(
                f"No {direction.value} migration defined for "
                f"v{migration.version} on '{migration.db_name}'"
            )

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            if sql:
                conn.executescript(sql)
            if fn:
                fn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _get_pending_migrations(
        self, db_name: str, current_version: int
    ) -> List[Migration]:
        """Return migrations with version > *current_version*, sorted.

        Args:
            db_name: Logical database name.
            current_version: Highest applied version.

        Returns:
            Sorted list of unapplied ``Migration`` objects.
        """
        with self._lock:
            all_migs = self._migrations.get(db_name, [])
        return [m for m in all_migs if m.version > current_version]

    # ──── History Recording ────

    def _record_history(
        self,
        db_name: str,
        version: int,
        description: str,
        direction: MigrationDirection,
        duration_ms: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Write a row to ``_migration_history``.

        Args:
            db_name: Target database.
            version: Migration version.
            description: Migration description.
            direction: ``UP`` or ``DOWN``.
            duration_ms: Elapsed wall-clock milliseconds.
            success: Whether the migration succeeded.
            error_message: Error text if it failed.
        """
        conn = self._registry_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO _migration_history "
            "(db_name, version, description, direction, applied_at, "
            "duration_ms, success, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                db_name,
                version,
                description,
                direction.value,
                now,
                duration_ms,
                1 if success else 0,
                error_message,
            ),
        )
        conn.commit()

    # ──── Status Queries ────

    def get_status(self, db_name: str) -> MigrationStatus:
        """Get migration status for a single database.

        Args:
            db_name: Logical database name.

        Returns:
            ``MigrationStatus`` with current version and pending info.
        """
        current = self._get_current_version(db_name)
        pending = self._get_pending_migrations(db_name, current)
        path = self._get_db_path(db_name)

        return MigrationStatus(
            db_name=db_name,
            current_version=current,
            pending_count=len(pending),
            pending_versions=[m.version for m in pending],
            registered_path=path,
        )

    def get_all_status(self) -> Dict[str, MigrationStatus]:
        """Get migration status for all registered databases.

        Returns:
            Mapping of db_name → ``MigrationStatus``.
        """
        with self._lock:
            db_names = list(self._migrations.keys())

        # Also include databases tracked in the registry but not in memory
        conn = self._registry_conn()
        rows = conn.execute("SELECT db_name FROM _db_versions").fetchall()
        for row in rows:
            if row["db_name"] not in db_names:
                db_names.append(row["db_name"])

        return {name: self.get_status(name) for name in sorted(set(db_names))}

    # ──── Database Discovery ────

    def discover_databases(self) -> List[DatabaseInfo]:
        """Scan known directories for ``.db`` files and return metadata.

        Returns:
            List of ``DatabaseInfo`` objects for every discovered database.
        """
        found: Dict[str, DatabaseInfo] = {}

        for search_dir in _KNOWN_DB_DIRS:
            if not search_dir.exists():
                continue
            for db_file in search_dir.glob("*.db"):
                name = db_file.stem
                if name in found:
                    continue
                found[name] = self._build_db_info(name, str(db_file))

        return sorted(found.values(), key=lambda d: d.name)

    def get_database_info(self, db_name: str) -> DatabaseInfo:
        """Get detailed info for a specific database.

        Args:
            db_name: Logical database name.

        Returns:
            ``DatabaseInfo`` with size, table count, version, etc.
        """
        db_path = self._get_db_path(db_name)
        return self._build_db_info(db_name, db_path)

    def _build_db_info(self, name: str, path: str) -> DatabaseInfo:
        """Construct a ``DatabaseInfo`` from a database file.

        Args:
            name: Logical database name.
            path: Filesystem path.

        Returns:
            Populated ``DatabaseInfo``.
        """
        info = DatabaseInfo(name=name, path=path)

        p = Path(path)
        if p.exists():
            stat = p.stat()
            info.size_bytes = stat.st_size
            info.last_modified = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()

            try:
                conn = sqlite3.connect(path)
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                info.table_count = cur.fetchone()[0]
                conn.close()
            except Exception as exc:
                logger.debug("Could not read table count from %s: %s", path, exc)

        info.current_version = self._get_current_version(name)
        return info

    # ──── Schema Drift Detection ────

    def detect_drift(
        self, db_name: str, expected: Optional[SchemaSnapshot] = None
    ) -> List[SchemaDiff]:
        """Detect schema drift for a database.

        If *expected* is not provided, the most recent stored snapshot is
        used as the baseline.  If no snapshot exists either, the actual
        schema is captured and stored, and an empty diff list is returned
        (first-run baseline).

        Args:
            db_name: Logical database name.
            expected: Optional expected schema to compare against.

        Returns:
            List of ``SchemaDiff`` objects.
        """
        db_path = self._get_db_path(db_name)
        actual = capture_snapshot(db_path, db_name)

        if expected is None:
            expected = self._load_latest_snapshot(db_name)

        if expected is None:
            # First time — store baseline
            self.save_snapshot(db_name, actual)
            logger.info(
                "No baseline snapshot for '%s' — captured initial snapshot "
                "(%d tables)",
                db_name,
                len(actual.tables),
            )
            return []

        diffs = compare_snapshots(expected, actual)
        if diffs:
            logger.warning(
                "Schema drift detected in '%s': %d difference(s)",
                db_name,
                len(diffs),
            )
        return diffs

    def detect_all_drift(self) -> Dict[str, List[SchemaDiff]]:
        """Run drift detection across all discovered databases.

        Returns:
            Mapping of db_name → list of ``SchemaDiff`` (only includes
            databases with actual drift).
        """
        results: Dict[str, List[SchemaDiff]] = {}
        for db_info in self.discover_databases():
            diffs = self.detect_drift(db_info.name)
            if diffs:
                results[db_info.name] = diffs
        return results

    # ──── Snapshot Persistence ────

    def save_snapshot(self, db_name: str, snapshot: SchemaSnapshot) -> None:
        """Store a schema snapshot in the registry.

        Args:
            db_name: Logical database name.
            snapshot: The snapshot to persist.
        """
        conn = self._registry_conn()
        conn.execute(
            "INSERT INTO _schema_snapshots (db_name, snapshot_json) VALUES (?, ?)",
            (db_name, snapshot.to_json()),
        )
        conn.commit()

    def _load_latest_snapshot(self, db_name: str) -> Optional[SchemaSnapshot]:
        """Load the most recently stored snapshot for a database.

        Args:
            db_name: Logical database name.

        Returns:
            The latest ``SchemaSnapshot``, or ``None`` if none exists.
        """
        conn = self._registry_conn()
        row = conn.execute(
            "SELECT snapshot_json FROM _schema_snapshots "
            "WHERE db_name = ? ORDER BY captured_at DESC LIMIT 1",
            (db_name,),
        ).fetchone()
        if not row:
            return None
        return SchemaSnapshot.from_json(row["snapshot_json"])

    def capture_and_save_snapshot(self, db_name: str) -> SchemaSnapshot:
        """Capture a live snapshot and save it to the registry.

        Args:
            db_name: Logical database name.

        Returns:
            The newly captured ``SchemaSnapshot``.
        """
        db_path = self._get_db_path(db_name)
        snapshot = capture_snapshot(db_path, db_name)
        self.save_snapshot(db_name, snapshot)
        return snapshot

    # ──── Migration History Queries ────

    def get_history(
        self, db_name: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Query migration history from the registry.

        Args:
            db_name: Optional filter by database name.
            limit: Maximum rows to return.

        Returns:
            List of history row dicts ordered newest-first.
        """
        conn = self._registry_conn()
        if db_name:
            rows = conn.execute(
                "SELECT * FROM _migration_history WHERE db_name = ? "
                "ORDER BY applied_at DESC LIMIT ?",
                (db_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM _migration_history ORDER BY applied_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ──── Nexus Integration ────

    def _log_to_nexus(
        self, title: str, content: str, tags: Optional[List[str]] = None
    ) -> None:
        """Best-effort log an event to Nexus.

        Never raises — all errors are swallowed to avoid breaking
        migration execution.

        Args:
            title: Entry title.
            content: Entry body text.
            tags: Optional list of tags.
        """
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            client.add_entry(
                title=title,
                content=content,
                content_type="note",
                category="operations",
                tags=tags or ["migration", "schema"],
                created_by="schema_migration_engine",
            )
        except Exception as exc:
            logger.debug("Could not log migration event to Nexus: %s", exc)

    # ──── Scheduler Integration ────

    def register_migration_tasks(self, scheduler: Any) -> None:
        """Register recurring migration/drift-check tasks with the scheduler.

        Registers a daily task that runs ``detect_all_drift`` and logs
        any findings to Nexus.

        Args:
            scheduler: A ``SchedulerDaemon`` instance with a ``register``
                method.
        """
        try:
            scheduler.register(
                task_id="schema_drift_check",
                name="Daily Schema Drift Check",
                schedule="daily",
                callback=self._scheduled_drift_check,
                enabled=True,
            )
            logger.info("Registered daily schema drift check task")
        except Exception as exc:
            logger.warning("Could not register drift check task: %s", exc)

    def _scheduled_drift_check(self) -> None:
        """Callback for the scheduled daily drift check."""
        logger.info("Running scheduled schema drift check")
        drift_results = self.detect_all_drift()

        if not drift_results:
            logger.info("No schema drift detected across all databases")
            return

        summary_lines = []
        total_diffs = 0
        for db_name, diffs in sorted(drift_results.items()):
            total_diffs += len(diffs)
            summary_lines.append(f"  {db_name}: {len(diffs)} difference(s)")
            for d in diffs:
                summary_lines.append(f"    - {d}")

        summary = "\n".join(summary_lines)
        logger.warning(
            "Schema drift detected in %d database(s) (%d total diffs):\n%s",
            len(drift_results),
            total_diffs,
            summary,
        )

        self._log_to_nexus(
            f"Schema drift detected: {len(drift_results)} database(s)",
            f"Daily drift check found {total_diffs} difference(s) in "
            f"{len(drift_results)} database(s):\n{summary}",
            tags=["migration", "schema", "drift", "scheduled"],
        )

    # ──── Cleanup ────

    def close(self) -> None:
        """Close all thread-local connections held by this engine."""
        self._pool.close_all()


# ──── Module-Level Singleton ────

_engine: Optional[SchemaMigrationEngine] = None
_engine_lock = threading.Lock()


def get_migration_engine(
    registry_path: Optional[str] = None,
) -> SchemaMigrationEngine:
    """Return the singleton ``SchemaMigrationEngine``.

    Thread-safe lazy initialisation with double-checked locking.

    Args:
        registry_path: Optional override for the registry database path.
            Only used on first call.

    Returns:
        The global ``SchemaMigrationEngine`` instance.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SchemaMigrationEngine(registry_path)
    return _engine
