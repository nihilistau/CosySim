"""Comprehensive tests for the Schema Migration Engine.

Tests cover all public classes (Migration, SchemaSnapshot, SchemaDiff,
SchemaMigrationEngine) and the module-level singleton factory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.schema_migration import (
    ColumnInfo,
    DatabaseInfo,
    DiffType,
    Migration,
    MigrationDirection,
    MigrationStatus,
    SchemaDiff,
    SchemaMigrationEngine,
    SchemaSnapshot,
    TableInfo,
    capture_snapshot,
    compare_snapshots,
)


# ──── Helpers ────


def _create_test_db(db_path: str, sql: str = "") -> None:
    """Create a SQLite database at *db_path* and optionally run *sql*."""
    conn = sqlite3.connect(db_path)
    if sql:
        conn.executescript(sql)
    conn.close()


def _make_engine(tmp_path: Path) -> SchemaMigrationEngine:
    """Return a fresh engine with a temp registry DB."""
    registry = str(tmp_path / "registry" / "schema_migrations.db")
    return SchemaMigrationEngine(registry_path=registry)


# ──── TestMigration ────


class TestMigration:
    """Tests for the Migration dataclass."""

    def test_creation_with_sql(self) -> None:
        """Migration can be created with an up_sql string."""
        m = Migration(
            db_name="testdb",
            version=1,
            description="add column",
            up_sql="ALTER TABLE t ADD COLUMN c TEXT",
        )
        assert m.db_name == "testdb"
        assert m.version == 1
        assert m.description == "add column"
        assert m.up_sql == "ALTER TABLE t ADD COLUMN c TEXT"
        assert m.up_fn is None
        assert m.down_sql is None
        assert m.down_fn is None
        assert m.applied_at is None

    def test_creation_with_callable(self) -> None:
        """Migration can be created with an up_fn callable."""

        def _apply(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE x (id INTEGER)")

        m = Migration(db_name="db", version=2, description="callable", up_fn=_apply)
        assert m.up_fn is _apply
        assert m.up_sql is None

    def test_creation_with_both_sql_and_callable(self) -> None:
        """Migration accepts both up_sql and up_fn simultaneously."""
        fn = lambda conn: None
        m = Migration(
            db_name="db",
            version=3,
            description="both",
            up_sql="SELECT 1",
            up_fn=fn,
        )
        assert m.up_sql == "SELECT 1"
        assert m.up_fn is fn

    def test_repr_contains_fields(self) -> None:
        """Migration repr includes key dataclass fields."""
        m = Migration(db_name="alpha", version=42, description="test repr")
        r = repr(m)
        assert "alpha" in r
        assert "42" in r
        assert "test repr" in r


# ──── TestSchemaSnapshot ────


class TestSchemaSnapshot:
    """Tests for SchemaSnapshot creation and serialization."""

    def test_capture_snapshot_from_live_db(self, tmp_path: Path) -> None:
        """capture_snapshot reads tables and columns from a real database."""
        db_path = str(tmp_path / "live.db")
        _create_test_db(
            db_path,
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);",
        )
        snap = capture_snapshot(db_path, "live")

        assert snap.db_name == "live"
        assert "users" in snap.tables
        cols = {c.name: c for c in snap.tables["users"].columns}
        assert "id" in cols
        assert "name" in cols
        assert cols["name"].notnull is True
        assert snap.captured_at != ""

    def test_snapshot_roundtrip_json(self) -> None:
        """to_json/from_json round-trips without data loss."""
        original = SchemaSnapshot(
            db_name="roundtrip",
            tables={
                "items": TableInfo(
                    name="items",
                    columns=[
                        ColumnInfo(name="id", col_type="INTEGER", pk=True),
                        ColumnInfo(name="val", col_type="TEXT", default_value="''"),
                    ],
                    indexes=["idx_val"],
                )
            },
            captured_at="2025-01-01T00:00:00+00:00",
        )
        raw = original.to_json()
        restored = SchemaSnapshot.from_json(raw)

        assert restored.db_name == "roundtrip"
        assert "items" in restored.tables
        assert len(restored.tables["items"].columns) == 2
        assert restored.tables["items"].indexes == ["idx_val"]
        assert restored.captured_at == "2025-01-01T00:00:00+00:00"

    def test_empty_database_snapshot(self, tmp_path: Path) -> None:
        """Snapshot of a database with no tables returns empty tables dict."""
        db_path = str(tmp_path / "empty.db")
        _create_test_db(db_path)
        snap = capture_snapshot(db_path, "empty")

        assert snap.db_name == "empty"
        assert snap.tables == {}

    def test_snapshot_with_indexes(self, tmp_path: Path) -> None:
        """Indexes are captured in the snapshot."""
        db_path = str(tmp_path / "indexed.db")
        _create_test_db(
            db_path,
            """
            CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, price REAL);
            CREATE INDEX idx_sku ON products(sku);
            CREATE INDEX idx_price ON products(price);
            """,
        )
        snap = capture_snapshot(db_path, "indexed")

        assert "products" in snap.tables
        indexes = snap.tables["products"].indexes
        assert "idx_sku" in indexes
        assert "idx_price" in indexes


# ──── TestSchemaDiff ────


class TestSchemaDiff:
    """Tests for the compare_snapshots function and SchemaDiff output."""

    def test_identical_snapshots_no_diffs(self) -> None:
        """Comparing identical snapshots yields an empty diff list."""
        table = TableInfo(
            name="t",
            columns=[ColumnInfo(name="id", col_type="INTEGER")],
        )
        a = SchemaSnapshot(db_name="db", tables={"t": table})
        b = SchemaSnapshot(db_name="db", tables={"t": table})
        diffs = compare_snapshots(a, b)
        assert diffs == []

    def test_missing_table_detected(self) -> None:
        """A table present in expected but missing in actual is reported."""
        expected = SchemaSnapshot(
            db_name="db",
            tables={
                "existing": TableInfo(
                    name="existing",
                    columns=[ColumnInfo(name="id", col_type="INTEGER")],
                ),
                "missing": TableInfo(
                    name="missing",
                    columns=[ColumnInfo(name="x", col_type="TEXT")],
                ),
            },
        )
        actual = SchemaSnapshot(
            db_name="db",
            tables={
                "existing": TableInfo(
                    name="existing",
                    columns=[ColumnInfo(name="id", col_type="INTEGER")],
                ),
            },
        )
        diffs = compare_snapshots(expected, actual)

        assert len(diffs) == 1
        assert diffs[0].diff_type == DiffType.MISSING_TABLE
        assert diffs[0].table == "missing"

    def test_column_diffs_detected(self) -> None:
        """Missing column, extra column, and type mismatch are all reported."""
        expected = SchemaSnapshot(
            db_name="db",
            tables={
                "t": TableInfo(
                    name="t",
                    columns=[
                        ColumnInfo(name="id", col_type="INTEGER"),
                        ColumnInfo(name="name", col_type="TEXT"),
                        ColumnInfo(name="age", col_type="INTEGER"),
                    ],
                )
            },
        )
        actual = SchemaSnapshot(
            db_name="db",
            tables={
                "t": TableInfo(
                    name="t",
                    columns=[
                        ColumnInfo(name="id", col_type="INTEGER"),
                        ColumnInfo(name="name", col_type="BLOB"),  # type mismatch
                        # 'age' missing
                        ColumnInfo(name="extra", col_type="REAL"),  # extra
                    ],
                )
            },
        )
        diffs = compare_snapshots(expected, actual)
        diff_types = {d.diff_type for d in diffs}

        assert DiffType.MISSING_COLUMN in diff_types
        assert DiffType.EXTRA_COLUMN in diff_types
        assert DiffType.TYPE_MISMATCH in diff_types
        assert len(diffs) == 3

        type_diff = [d for d in diffs if d.diff_type == DiffType.TYPE_MISMATCH][0]
        assert type_diff.expected == "TEXT"
        assert type_diff.actual == "BLOB"


# ──── TestSchemaMigrationEngine ────


class TestSchemaMigrationEngine:
    """Tests for the core SchemaMigrationEngine class."""

    def test_constructor_creates_registry_tables(self, tmp_path: Path) -> None:
        """Engine constructor creates the three registry tables."""
        engine = _make_engine(tmp_path)
        conn = engine._registry_conn()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cur.fetchall()}
        assert "_db_versions" in tables
        assert "_migration_history" in tables
        assert "_schema_snapshots" in tables
        engine.close()

    def test_register_single_migration(self, tmp_path: Path) -> None:
        """A registered migration appears in the internal registry."""
        engine = _make_engine(tmp_path)
        m = Migration(db_name="testdb", version=1, description="first", up_sql="SELECT 1")
        engine.register_migration(m)

        assert "testdb" in engine._migrations
        assert len(engine._migrations["testdb"]) == 1
        assert engine._migrations["testdb"][0].version == 1
        engine.close()

    def test_register_duplicate_version_raises(self, tmp_path: Path) -> None:
        """Registering two migrations with the same db_name+version raises ValueError."""
        engine = _make_engine(tmp_path)
        m1 = Migration(db_name="db", version=1, description="first", up_sql="SELECT 1")
        m2 = Migration(db_name="db", version=1, description="dupe", up_sql="SELECT 2")
        engine.register_migration(m1)

        with pytest.raises(ValueError, match="already registered"):
            engine.register_migration(m2)
        engine.close()

    def test_run_pending_happy_path(self, tmp_path: Path) -> None:
        """run_pending applies migrations in order and updates version."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "app.db")
        _create_test_db(db_path)
        engine.set_db_path("app", db_path)

        engine.register_migration(
            Migration(
                db_name="app",
                version=1,
                description="create table",
                up_sql="CREATE TABLE items (id INTEGER PRIMARY KEY);",
            )
        )
        engine.register_migration(
            Migration(
                db_name="app",
                version=2,
                description="add column",
                up_sql="ALTER TABLE items ADD COLUMN name TEXT;",
            )
        )

        applied = engine.run_pending("app")
        assert applied == [1, 2]

        # Verify table exists with column
        conn = sqlite3.connect(db_path)
        cur = conn.execute("PRAGMA table_info(items)")
        col_names = [row[1] for row in cur.fetchall()]
        conn.close()
        assert "id" in col_names
        assert "name" in col_names

        # Version updated
        assert engine._get_current_version("app") == 2
        engine.close()

    def test_run_pending_with_no_migrations(self, tmp_path: Path) -> None:
        """run_pending returns empty list when no migrations are registered."""
        engine = _make_engine(tmp_path)
        applied = engine.run_pending("nonexistent")
        assert applied == []
        engine.close()

    @patch("engine.nexus.schema_migration.SchemaMigrationEngine._log_to_nexus")
    def test_run_migration_that_fails_raises(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """A migration with invalid SQL raises RuntimeError and records failure."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "fail.db")
        _create_test_db(db_path)
        engine.set_db_path("fail", db_path)

        engine.register_migration(
            Migration(
                db_name="fail",
                version=1,
                description="bad sql",
                up_sql="THIS IS NOT VALID SQL;",
            )
        )

        with pytest.raises(RuntimeError, match="failed"):
            engine.run_pending("fail")

        # Version should remain at 0
        assert engine._get_current_version("fail") == 0

        # History records the failure
        history = engine.get_history("fail")
        assert len(history) == 1
        assert history[0]["success"] == 0
        assert history[0]["error_message"] is not None
        engine.close()

    def test_run_python_callable_migration(self, tmp_path: Path) -> None:
        """Migration with up_fn callable is executed correctly."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "callable.db")
        _create_test_db(db_path)
        engine.set_db_path("callable", db_path)

        call_log = []

        def _migrate(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE from_fn (id INTEGER)")
            call_log.append("called")

        engine.register_migration(
            Migration(
                db_name="callable",
                version=1,
                description="python migration",
                up_fn=_migrate,
            )
        )
        applied = engine.run_pending("callable")

        assert applied == [1]
        assert call_log == ["called"]

        # Verify table exists
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='from_fn'"
        )
        assert cur.fetchone() is not None
        conn.close()
        engine.close()

    def test_rollback_to_specific_version(self, tmp_path: Path) -> None:
        """rollback reverses migrations down to (but not including) the target."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "rollback.db")
        _create_test_db(db_path)
        engine.set_db_path("rb", db_path)

        engine.register_migration(
            Migration(
                db_name="rb",
                version=1,
                description="create table",
                up_sql="CREATE TABLE t (id INTEGER);",
                down_sql="DROP TABLE IF EXISTS t;",
            )
        )
        engine.register_migration(
            Migration(
                db_name="rb",
                version=2,
                description="add col",
                up_sql="ALTER TABLE t ADD COLUMN name TEXT;",
                down_sql="CREATE TABLE t_new (id INTEGER); "
                "INSERT INTO t_new SELECT id FROM t; "
                "DROP TABLE t; ALTER TABLE t_new RENAME TO t;",
            )
        )

        engine.run_pending("rb")
        assert engine._get_current_version("rb") == 2

        rolled = engine.rollback("rb", target_version=0)
        assert 2 in rolled
        assert 1 in rolled
        assert engine._get_current_version("rb") == 0
        engine.close()

    def test_rollback_when_already_at_target(self, tmp_path: Path) -> None:
        """rollback returns empty list when target >= current version."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "noop.db")
        _create_test_db(db_path)
        engine.set_db_path("noop", db_path)

        engine.register_migration(
            Migration(
                db_name="noop",
                version=1,
                description="first",
                up_sql="CREATE TABLE x (id INTEGER);",
                down_sql="DROP TABLE x;",
            )
        )
        engine.run_pending("noop")
        assert engine._get_current_version("noop") == 1

        rolled = engine.rollback("noop", target_version=1)
        assert rolled == []
        assert engine._get_current_version("noop") == 1

        rolled2 = engine.rollback("noop", target_version=5)
        assert rolled2 == []
        engine.close()

    def test_rollback_negative_target_raises(self, tmp_path: Path) -> None:
        """rollback raises ValueError for negative target_version."""
        engine = _make_engine(tmp_path)
        with pytest.raises(ValueError, match="target_version must be >= 0"):
            engine.rollback("db", target_version=-1)
        engine.close()

    def test_get_status_for_registered_db(self, tmp_path: Path) -> None:
        """get_status returns correct current_version and pending info."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "status.db")
        _create_test_db(db_path)
        engine.set_db_path("status", db_path)

        engine.register_migration(
            Migration(db_name="status", version=1, description="v1", up_sql="SELECT 1")
        )
        engine.register_migration(
            Migration(db_name="status", version=2, description="v2", up_sql="SELECT 1")
        )

        status = engine.get_status("status")
        assert status.db_name == "status"
        assert status.current_version == 0
        assert status.pending_count == 2
        assert status.pending_versions == [1, 2]

        # Apply one
        db_path_real = str(tmp_path / "status.db")
        engine.run_pending("status")

        status2 = engine.get_status("status")
        assert status2.current_version == 2
        assert status2.pending_count == 0
        engine.close()

    def test_get_status_for_unknown_db(self, tmp_path: Path) -> None:
        """get_status for an unknown DB returns version 0 with no pending."""
        engine = _make_engine(tmp_path)
        status = engine.get_status("unknown_db")
        assert status.db_name == "unknown_db"
        assert status.current_version == 0
        assert status.pending_count == 0
        engine.close()

    def test_get_all_status(self, tmp_path: Path) -> None:
        """get_all_status covers all registered databases."""
        engine = _make_engine(tmp_path)
        for name in ["alpha", "beta", "gamma"]:
            db_path = str(tmp_path / f"{name}.db")
            _create_test_db(db_path)
            engine.set_db_path(name, db_path)
            engine.register_migration(
                Migration(db_name=name, version=1, description="init", up_sql="SELECT 1")
            )

        all_status = engine.get_all_status()
        assert "alpha" in all_status
        assert "beta" in all_status
        assert "gamma" in all_status
        assert all(isinstance(v, MigrationStatus) for v in all_status.values())
        engine.close()

    def test_get_history_with_limit(self, tmp_path: Path) -> None:
        """get_history respects the limit parameter."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "hist.db")
        _create_test_db(db_path)
        engine.set_db_path("hist", db_path)

        for v in range(1, 6):
            engine.register_migration(
                Migration(
                    db_name="hist",
                    version=v,
                    description=f"migration {v}",
                    up_sql="SELECT 1",
                )
            )
        engine.run_pending("hist")

        full = engine.get_history("hist", limit=50)
        assert len(full) == 5

        limited = engine.get_history("hist", limit=2)
        assert len(limited) == 2
        engine.close()

    def test_get_history_all_dbs(self, tmp_path: Path) -> None:
        """get_history without db_name returns history for all databases."""
        engine = _make_engine(tmp_path)
        for name in ["a", "b"]:
            db_path = str(tmp_path / f"{name}.db")
            _create_test_db(db_path)
            engine.set_db_path(name, db_path)
            engine.register_migration(
                Migration(db_name=name, version=1, description="init", up_sql="SELECT 1")
            )
            engine.run_pending(name)

        history = engine.get_history(limit=50)
        db_names_in_history = {h["db_name"] for h in history}
        assert "a" in db_names_in_history
        assert "b" in db_names_in_history
        engine.close()

    @patch("engine.nexus.schema_migration.SchemaMigrationEngine._log_to_nexus")
    def test_detect_drift_clean_db(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """detect_drift returns empty list when schema matches the baseline."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "drift.db")
        _create_test_db(
            db_path, "CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);"
        )
        engine.set_db_path("drift", db_path)

        # First call captures baseline
        diffs1 = engine.detect_drift("drift")
        assert diffs1 == []

        # Second call compares against baseline — same schema, no drift
        diffs2 = engine.detect_drift("drift")
        assert diffs2 == []
        engine.close()

    @patch("engine.nexus.schema_migration.SchemaMigrationEngine._log_to_nexus")
    def test_detect_drift_with_schema_changes(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """detect_drift reports diffs when the schema has changed since baseline."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "drift2.db")
        _create_test_db(db_path, "CREATE TABLE t (id INTEGER);")
        engine.set_db_path("drift2", db_path)

        # Capture baseline
        engine.detect_drift("drift2")

        # Alter schema outside migration engine
        conn = sqlite3.connect(db_path)
        conn.execute("ALTER TABLE t ADD COLUMN extra TEXT")
        conn.execute("CREATE TABLE new_table (x TEXT)")
        conn.commit()
        conn.close()

        diffs = engine.detect_drift("drift2")
        diff_types = {d.diff_type for d in diffs}
        assert DiffType.EXTRA_TABLE in diff_types or DiffType.EXTRA_COLUMN in diff_types
        assert len(diffs) >= 2
        engine.close()

    @patch("engine.nexus.schema_migration.SchemaMigrationEngine._log_to_nexus")
    def test_detect_all_drift(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """detect_all_drift scans discovered databases for drift."""
        engine = _make_engine(tmp_path)

        # Create two databases in a discoverable directory
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db1 = str(data_dir / "one.db")
        db2 = str(data_dir / "two.db")
        _create_test_db(db1, "CREATE TABLE a (id INTEGER);")
        _create_test_db(db2, "CREATE TABLE b (id INTEGER);")

        engine.set_db_path("one", db1)
        engine.set_db_path("two", db2)

        # Capture baselines
        engine.detect_drift("one")
        engine.detect_drift("two")

        # Alter one of them
        conn = sqlite3.connect(db1)
        conn.execute("CREATE TABLE extra (z TEXT)")
        conn.commit()
        conn.close()

        # Patch discover to return our test DBs
        with patch.object(engine, "discover_databases") as mock_disc:
            mock_disc.return_value = [
                DatabaseInfo(name="one", path=db1),
                DatabaseInfo(name="two", path=db2),
            ]
            results = engine.detect_all_drift()

        assert "one" in results
        assert "two" not in results  # no drift
        engine.close()

    def test_thread_safe_registration(self, tmp_path: Path) -> None:
        """Concurrent registration from multiple threads does not corrupt state."""
        engine = _make_engine(tmp_path)
        errors: list = []

        def _register(start_version: int) -> None:
            try:
                for v in range(start_version, start_version + 10):
                    engine.register_migration(
                        Migration(
                            db_name="threaded",
                            version=v,
                            description=f"v{v}",
                            up_sql="SELECT 1",
                        )
                    )
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_register, args=(1,))
        t2 = threading.Thread(target=_register, args=(11,))
        t3 = threading.Thread(target=_register, args=(21,))
        t1.start()
        t2.start()
        t3.start()
        t1.join()
        t2.join()
        t3.join()

        assert errors == []
        assert len(engine._migrations["threaded"]) == 30
        versions = [m.version for m in engine._migrations["threaded"]]
        assert versions == sorted(versions)
        engine.close()

    def test_discover_databases(self, tmp_path: Path) -> None:
        """discover_databases finds .db files in known directories."""
        engine = _make_engine(tmp_path)

        search_dir = tmp_path / "search"
        search_dir.mkdir()
        _create_test_db(str(search_dir / "alpha.db"), "CREATE TABLE a (id INTEGER);")
        _create_test_db(str(search_dir / "beta.db"), "CREATE TABLE b (id INTEGER);")
        _create_test_db(str(search_dir / "gamma.db"))

        with patch(
            "engine.nexus.schema_migration._KNOWN_DB_DIRS", [search_dir]
        ):
            found = engine.discover_databases()

        names = [d.name for d in found]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names
        engine.close()

    def test_database_info_with_size_and_tables(self, tmp_path: Path) -> None:
        """get_database_info returns file size and table count."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "info.db")
        _create_test_db(
            db_path,
            "CREATE TABLE t1 (id INTEGER); CREATE TABLE t2 (name TEXT);",
        )
        engine.set_db_path("info", db_path)

        info = engine.get_database_info("info")
        assert info.name == "info"
        assert info.path == db_path
        assert info.table_count == 2
        assert info.size_bytes > 0
        assert info.last_modified != ""
        engine.close()

    @patch("engine.nexus.schema_migration.SchemaMigrationEngine._log_to_nexus")
    def test_nexus_logging_best_effort(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """_log_to_nexus is called on successful migration and does not raise."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "nexus.db")
        _create_test_db(db_path)
        engine.set_db_path("nexus_test", db_path)

        engine.register_migration(
            Migration(
                db_name="nexus_test",
                version=1,
                description="nexus log test",
                up_sql="CREATE TABLE logged (id INTEGER);",
            )
        )
        engine.run_pending("nexus_test")

        assert mock_nexus.called
        # Check it was called with a success title
        call_args = mock_nexus.call_args_list
        any_success = any("applied" in str(c).lower() for c in call_args)
        assert any_success
        engine.close()

    def test_nexus_logging_swallows_errors(self, tmp_path: Path) -> None:
        """_log_to_nexus never raises, even when Nexus client is unavailable."""
        engine = _make_engine(tmp_path)
        with patch(
            "engine.nexus.schema_migration.get_nexus_client",
            side_effect=ImportError("no nexus"),
            create=True,
        ):
            # Should not raise
            engine._log_to_nexus("test", "content", tags=["test"])
        engine.close()

    def test_set_db_path_persists(self, tmp_path: Path) -> None:
        """set_db_path updates both in-memory and registry."""
        engine = _make_engine(tmp_path)
        target = str(tmp_path / "custom.db")
        engine.set_db_path("custom", target)

        assert engine._get_db_path("custom") == target

        # Check registry
        conn = engine._registry_conn()
        row = conn.execute(
            "SELECT registered_path FROM _db_versions WHERE db_name = ?",
            ("custom",),
        ).fetchone()
        assert row is not None
        assert row["registered_path"] == target
        engine.close()

    def test_register_migrations_batch(self, tmp_path: Path) -> None:
        """register_migrations registers multiple migrations for a database."""
        engine = _make_engine(tmp_path)
        migrations = [
            Migration(db_name="batch", version=1, description="v1", up_sql="SELECT 1"),
            Migration(db_name="batch", version=2, description="v2", up_sql="SELECT 1"),
            Migration(db_name="batch", version=3, description="v3", up_sql="SELECT 1"),
        ]
        engine.register_migrations("batch", migrations)

        assert len(engine._migrations["batch"]) == 3
        engine.close()


# ──── TestSchemaSnapshotCapture ────


class TestSchemaSnapshotCapture:
    """Tests for the capture_snapshot standalone function."""

    def test_capture_tables_correctly(self, tmp_path: Path) -> None:
        """All user tables are captured (internal sqlite_ tables excluded)."""
        db_path = str(tmp_path / "cap.db")
        _create_test_db(
            db_path,
            "CREATE TABLE a (id INTEGER); "
            "CREATE TABLE b (name TEXT); "
            "CREATE TABLE c (val REAL);",
        )
        snap = capture_snapshot(db_path)
        assert set(snap.tables.keys()) == {"a", "b", "c"}

    def test_capture_columns_with_types(self, tmp_path: Path) -> None:
        """Column names and types are correctly captured."""
        db_path = str(tmp_path / "cols.db")
        _create_test_db(
            db_path,
            "CREATE TABLE metrics (id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, value REAL, created_at TIMESTAMP);",
        )
        snap = capture_snapshot(db_path)
        cols = {c.name: c for c in snap.tables["metrics"].columns}

        assert cols["id"].col_type == "INTEGER"
        assert cols["id"].pk is True
        assert cols["name"].col_type == "TEXT"
        assert cols["name"].notnull is True
        assert cols["value"].col_type == "REAL"
        assert cols["created_at"].col_type == "TIMESTAMP"

    def test_capture_indexes(self, tmp_path: Path) -> None:
        """Indexes on tables are included in the snapshot."""
        db_path = str(tmp_path / "idx.db")
        _create_test_db(
            db_path,
            "CREATE TABLE data (k TEXT, v TEXT); "
            "CREATE UNIQUE INDEX idx_k ON data(k);",
        )
        snap = capture_snapshot(db_path)
        assert "idx_k" in snap.tables["data"].indexes

    def test_handle_wal_mode_databases(self, tmp_path: Path) -> None:
        """capture_snapshot handles WAL mode databases without error."""
        db_path = str(tmp_path / "wal.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE w (id INTEGER)")
        conn.commit()
        conn.close()

        snap = capture_snapshot(db_path, "wal")
        assert "w" in snap.tables

    def test_handle_nonexistent_database(self, tmp_path: Path) -> None:
        """capture_snapshot returns an empty snapshot for a missing file."""
        db_path = str(tmp_path / "does_not_exist.db")
        snap = capture_snapshot(db_path, "ghost")
        assert snap.db_name == "ghost"
        assert snap.tables == {}


# ──── TestMigrationTaskRegistration ────


class TestMigrationTaskRegistration:
    """Tests for scheduler task registration."""

    def test_register_tasks_with_scheduler(self, tmp_path: Path) -> None:
        """register_migration_tasks calls scheduler.register correctly."""
        engine = _make_engine(tmp_path)
        scheduler = MagicMock()

        engine.register_migration_tasks(scheduler)

        scheduler.register.assert_called_once()
        call_kwargs = scheduler.register.call_args
        assert call_kwargs[1]["task_id"] == "schema_drift_check"
        assert call_kwargs[1]["schedule"] == "daily"
        assert call_kwargs[1]["enabled"] is True
        engine.close()

    def test_handle_scheduler_unavailable(self, tmp_path: Path) -> None:
        """register_migration_tasks does not raise when scheduler.register fails."""
        engine = _make_engine(tmp_path)
        scheduler = MagicMock()
        scheduler.register.side_effect = RuntimeError("scheduler broken")

        # Should not raise
        engine.register_migration_tasks(scheduler)
        engine.close()

    def test_scheduled_callback_is_callable(self, tmp_path: Path) -> None:
        """The callback passed to the scheduler is the drift check method."""
        engine = _make_engine(tmp_path)
        scheduler = MagicMock()

        engine.register_migration_tasks(scheduler)

        call_kwargs = scheduler.register.call_args[1]
        callback = call_kwargs["callback"]
        assert callable(callback)
        # The callback should be _scheduled_drift_check
        assert callback.__name__ == "_scheduled_drift_check"
        engine.close()


# ──── TestSingleton ────


class TestSingleton:
    """Tests for the module-level get_migration_engine singleton."""

    def test_get_migration_engine_returns_same_instance(
        self, tmp_path: Path
    ) -> None:
        """Repeated calls return the same object."""
        registry = str(tmp_path / "singleton.db")
        with patch(
            "engine.nexus.schema_migration._engine", None
        ), patch(
            "engine.nexus.schema_migration._engine_lock", threading.Lock()
        ):
            from engine.nexus.schema_migration import get_migration_engine

            e1 = get_migration_engine(registry)
            e2 = get_migration_engine()
            assert e1 is e2
            e1.close()

    def test_thread_safe_singleton_creation(self, tmp_path: Path) -> None:
        """Multiple threads calling get_migration_engine get the same instance."""
        registry = str(tmp_path / "threaded_singleton.db")
        instances: list = []

        with patch(
            "engine.nexus.schema_migration._engine", None
        ), patch(
            "engine.nexus.schema_migration._engine_lock", threading.Lock()
        ):
            from engine.nexus.schema_migration import get_migration_engine

            def _get() -> None:
                inst = get_migration_engine(registry)
                instances.append(inst)

            threads = [threading.Thread(target=_get) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(instances) == 5
        assert all(inst is instances[0] for inst in instances)
        instances[0].close()


# ──── TestEdgeCases ────


class TestEdgeCases:
    """Edge-case and stress tests."""

    def test_very_long_migration_sql(self, tmp_path: Path) -> None:
        """A migration with very long SQL executes without truncation."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "long.db")
        _create_test_db(db_path)
        engine.set_db_path("long", db_path)

        # Build a long SQL creating many columns
        cols = ", ".join(f"col_{i} TEXT" for i in range(200))
        long_sql = f"CREATE TABLE wide_table (id INTEGER PRIMARY KEY, {cols});"

        engine.register_migration(
            Migration(db_name="long", version=1, description="wide table", up_sql=long_sql)
        )
        applied = engine.run_pending("long")
        assert applied == [1]

        # Verify all columns exist
        conn = sqlite3.connect(db_path)
        cur = conn.execute("PRAGMA table_info(wide_table)")
        col_count = len(cur.fetchall())
        conn.close()
        assert col_count == 201  # id + 200 cols
        engine.close()

    def test_migration_with_both_sql_and_callable_runs_both(
        self, tmp_path: Path
    ) -> None:
        """When both up_sql and up_fn are provided, both are executed."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "both.db")
        _create_test_db(db_path)
        engine.set_db_path("both", db_path)

        fn_called = []

        def _fn(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE from_fn (x TEXT)")
            fn_called.append(True)

        engine.register_migration(
            Migration(
                db_name="both",
                version=1,
                description="sql + fn",
                up_sql="CREATE TABLE from_sql (id INTEGER);",
                up_fn=_fn,
            )
        )
        applied = engine.run_pending("both")
        assert applied == [1]
        assert fn_called == [True]

        # Both tables should exist
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        assert "from_sql" in tables
        assert "from_fn" in tables
        engine.close()

    def test_unicode_in_descriptions(self, tmp_path: Path) -> None:
        """Migration descriptions with unicode characters are stored correctly."""
        engine = _make_engine(tmp_path)
        db_path = str(tmp_path / "unicode.db")
        _create_test_db(db_path)
        engine.set_db_path("uni", db_path)

        desc = "Add über column — données françaises 🎯"
        engine.register_migration(
            Migration(
                db_name="uni",
                version=1,
                description=desc,
                up_sql="CREATE TABLE t (id INTEGER);",
            )
        )
        engine.run_pending("uni")

        history = engine.get_history("uni")
        assert history[0]["description"] == desc
        engine.close()

    def test_database_path_with_spaces(self, tmp_path: Path) -> None:
        """Engine handles database paths that contain spaces."""
        space_dir = tmp_path / "path with spaces" / "sub dir"
        space_dir.mkdir(parents=True)
        db_path = str(space_dir / "my database.db")
        _create_test_db(db_path, "CREATE TABLE s (id INTEGER);")

        engine = _make_engine(tmp_path)
        engine.set_db_path("spaced", db_path)

        engine.register_migration(
            Migration(
                db_name="spaced",
                version=1,
                description="spaces ok",
                up_sql="ALTER TABLE s ADD COLUMN v TEXT;",
            )
        )
        applied = engine.run_pending("spaced")
        assert applied == [1]

        snap = capture_snapshot(db_path, "spaced")
        col_names = [c.name for c in snap.tables["s"].columns]
        assert "v" in col_names
        engine.close()

    def test_run_migrations_on_empty_registry(self, tmp_path: Path) -> None:
        """run_all_pending on an engine with no registered migrations returns empty."""
        engine = _make_engine(tmp_path)
        results = engine.run_all_pending()
        assert results == {}
        engine.close()

    def test_concurrent_migration_runs(self, tmp_path: Path) -> None:
        """Concurrent run_pending calls on different DBs do not interfere."""
        engine = _make_engine(tmp_path)
        errors: list = []
        applied_all: dict = {}

        def _run(name: str) -> None:
            try:
                db_path = str(tmp_path / f"{name}.db")
                _create_test_db(db_path)
                engine.set_db_path(name, db_path)
                engine.register_migration(
                    Migration(
                        db_name=name,
                        version=1,
                        description=f"init {name}",
                        up_sql=f"CREATE TABLE {name}_tbl (id INTEGER);",
                    )
                )
                result = engine.run_pending(name)
                applied_all[name] = result
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_run, args=(f"db{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(applied_all) == 5
        for name, versions in applied_all.items():
            assert versions == [1]
        engine.close()


# ──── Additional Coverage ────


class TestSchemaDiffStr:
    """Tests for SchemaDiff string representation."""

    def test_str_with_all_fields(self) -> None:
        """SchemaDiff __str__ includes table, column, expected, actual."""
        d = SchemaDiff(
            table="users",
            column="age",
            diff_type=DiffType.TYPE_MISMATCH,
            expected="INTEGER",
            actual="TEXT",
        )
        s = str(d)
        assert "TYPE_MISMATCH" in s
        assert "users" in s
        assert "age" in s
        assert "INTEGER" in s
        assert "TEXT" in s

    def test_str_table_level_diff(self) -> None:
        """SchemaDiff __str__ for a table-level diff omits column info."""
        d = SchemaDiff(table="orders", column="", diff_type=DiffType.MISSING_TABLE)
        s = str(d)
        assert "MISSING_TABLE" in s
        assert "orders" in s


class TestTableInfoSerialization:
    """Tests for TableInfo to_dict / from_dict."""

    def test_to_dict_roundtrip(self) -> None:
        """TableInfo survives to_dict → from_dict without data loss."""
        original = TableInfo(
            name="events",
            columns=[
                ColumnInfo(
                    name="id", col_type="INTEGER", notnull=True, pk=True
                ),
                ColumnInfo(
                    name="payload",
                    col_type="TEXT",
                    default_value="'{}'",
                ),
            ],
            indexes=["idx_events_id"],
        )
        d = original.to_dict()
        restored = TableInfo.from_dict(d)

        assert restored.name == "events"
        assert len(restored.columns) == 2
        assert restored.columns[0].name == "id"
        assert restored.columns[0].pk is True
        assert restored.columns[1].default_value == "'{}'"
        assert restored.indexes == ["idx_events_id"]

    def test_from_dict_handles_missing_keys(self) -> None:
        """TableInfo.from_dict uses defaults for missing optional keys."""
        data = {"name": "minimal", "columns": [{"name": "x"}]}
        t = TableInfo.from_dict(data)
        assert t.name == "minimal"
        assert t.columns[0].col_type == ""
        assert t.columns[0].notnull is False
        assert t.columns[0].pk is False
        assert t.indexes == []


class TestCaptureSnapshotDbName:
    """Tests for db_name inference in capture_snapshot."""

    def test_db_name_defaults_to_stem(self, tmp_path: Path) -> None:
        """When db_name is omitted, it defaults to the file stem."""
        db_path = str(tmp_path / "my_database.db")
        _create_test_db(db_path)
        snap = capture_snapshot(db_path)
        assert snap.db_name == "my_database"
