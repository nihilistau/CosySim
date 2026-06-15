"""Tests for BackupManager."""
from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.backup_manager import (
    BackupEntry,
    BackupManager,
    BackupResult,
    get_backup_manager,
)


# ──── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def backup_dir(tmp_path) -> Path:
    d = tmp_path / "backups"
    d.mkdir()
    return d


# v1.62.0 [2026-06-15] — Mock get_config per-key: returning the backup_dir
# string for *every* key (incl. the int "nexus.backup_max_per_db" added in
# v1.51.0) made the count-based prune slice fail with a non-int index. Honor
# each key's own default instead of a blanket return value.
def _cfg_get(backup_dir):
    def _get(key, default=None):
        if key == "nexus.backup_dir":
            return str(backup_dir)
        return default
    return _get


@pytest.fixture
def mgr(backup_dir) -> BackupManager:
    with patch("engine.nexus.backup_manager.get_config") as mock_cfg:
        mock_cfg.return_value.get.side_effect = _cfg_get(backup_dir)
        return BackupManager(backup_dir=backup_dir, retention_days=14, full_backup_days=7)


def _make_sqlite_db(path: Path) -> Path:
    """Create a minimal valid SQLite database at path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'smoke_test_value')")
    conn.commit()
    conn.close()
    return path


# ──── BackupEntry / BackupResult ───────────────────────────────────────────────

class TestBackupResult:
    def test_to_dict_has_required_keys(self):
        r = BackupResult(started_at="2026-01-01T00:00:00Z", finished_at="2026-01-01T00:00:05Z")
        d = r.to_dict()
        for key in ("started_at", "finished_at", "succeeded", "failed", "skipped",
                    "total_size_kb", "pruned"):
            assert key in d, f"Missing key: {key}"

    def test_default_counts_are_zero(self):
        r = BackupResult()
        assert r.succeeded == 0
        assert r.failed == 0
        assert r.skipped == 0
        assert r.pruned == 0


# ──── BackupManager core ──────────────────────────────────────────────────────

class TestBackupManagerInit:
    def test_creates_backup_dir(self, tmp_path):
        d = tmp_path / "new_backup_dir"
        assert not d.exists()
        with patch("engine.nexus.backup_manager.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = str(d)
            BackupManager(backup_dir=d)
        assert d.exists()


class TestBackupManagerRun:
    def test_run_backup_skips_missing_dbs(self, mgr):
        """If all known databases don't exist, skipped count matches."""
        with patch.object(mgr, "_discover_databases", return_value={}):
            result = mgr.run_backup()
        assert result.succeeded == 0
        assert result.skipped == 0  # no targets at all

    def test_run_backup_backs_up_real_db(self, mgr, tmp_path):
        db_path = _make_sqlite_db(tmp_path / "test.db")
        with patch.object(mgr, "_discover_databases", return_value={"test": db_path}):
            result = mgr.run_backup()
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.total_size_kb > 0

    def test_run_backup_creates_gz_file(self, mgr, tmp_path, backup_dir):
        db_path = _make_sqlite_db(tmp_path / "test.db")
        with patch.object(mgr, "_discover_databases", return_value={"test": db_path}):
            mgr.run_backup()
        gz_files = list(backup_dir.glob("*.db.gz"))
        assert len(gz_files) == 1, f"Expected 1 .db.gz, got {gz_files}"

    def test_run_backup_gz_is_valid_sqlite(self, mgr, tmp_path, backup_dir):
        """The compressed backup decompresses to a valid SQLite file."""
        db_path = _make_sqlite_db(tmp_path / "test.db")
        with patch.object(mgr, "_discover_databases", return_value={"test": db_path}):
            mgr.run_backup()
        gz = list(backup_dir.glob("*.db.gz"))[0]
        restored = tmp_path / "restored.db"
        with gzip.open(gz, "rb") as f_in:
            restored.write_bytes(f_in.read())
        conn = sqlite3.connect(str(restored))
        rows = conn.execute("SELECT * FROM test").fetchall()
        conn.close()
        assert rows == [(1, "smoke_test_value")]

    def test_run_backup_manifest_written(self, mgr, tmp_path, backup_dir):
        db_path = _make_sqlite_db(tmp_path / "test.db")
        with patch.object(mgr, "_discover_databases", return_value={"test": db_path}):
            mgr.run_backup()
        manifest = backup_dir / "last_backup.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert "succeeded" in data

    def test_run_backup_stores_last_result(self, mgr, tmp_path):
        db_path = _make_sqlite_db(tmp_path / "real.db")
        with patch.object(mgr, "_discover_databases", return_value={"real": db_path}):
            mgr.run_backup()
        last = mgr.get_last_result()
        assert last is not None
        assert last["succeeded"] == 1


class TestBackupManagerList:
    def test_list_backups_empty_dir(self, mgr):
        entries = mgr.list_backups()
        assert entries == []

    def test_list_backups_returns_entries(self, mgr, tmp_path, backup_dir):
        db_path = _make_sqlite_db(tmp_path / "test.db")
        with patch.object(mgr, "_discover_databases", return_value={"test": db_path}):
            mgr.run_backup()
        entries = mgr.list_backups()
        assert len(entries) == 1
        assert "filename" in entries[0]
        assert "size_kb" in entries[0]
        assert "age_days" in entries[0]
        assert entries[0]["filename"].endswith(".db.gz")


class TestBackupManagerRestore:
    def test_restore_valid_backup(self, mgr, tmp_path, backup_dir):
        db_path = _make_sqlite_db(tmp_path / "source.db")
        with patch.object(mgr, "_discover_databases", return_value={"source": db_path}):
            mgr.run_backup()
        gz = list(backup_dir.glob("*.db.gz"))[0]
        target = tmp_path / "restored.db"
        result = mgr.restore_backup(str(gz), str(target))
        assert result["success"] is True
        assert target.exists()
        # Verify content
        conn = sqlite3.connect(str(target))
        rows = conn.execute("SELECT * FROM test").fetchall()
        conn.close()
        assert rows == [(1, "smoke_test_value")]

    def test_restore_missing_backup(self, mgr, tmp_path):
        result = mgr.restore_backup("/nonexistent/backup.db.gz", str(tmp_path / "out.db"))
        assert result["success"] is False
        assert "error" in result

    def test_restore_wrong_extension(self, mgr, tmp_path):
        fake = tmp_path / "not_a_backup.txt"
        fake.write_text("data")
        result = mgr.restore_backup(str(fake), str(tmp_path / "out.db"))
        assert result["success"] is False


class TestBackupManagerPrune:
    def test_old_backups_pruned(self, mgr, tmp_path, backup_dir):
        """Files older than retention_days should be removed."""
        import time

        # Create a fake old .db.gz
        old_file = backup_dir / "test_old.db.gz"
        old_file.write_bytes(b"fake")
        # Modify mtime to 20 days ago
        old_mtime = time.time() - (20 * 86400)
        import os
        os.utime(str(old_file), (old_mtime, old_mtime))

        pruned = mgr._prune_old()
        assert pruned >= 1
        assert not old_file.exists()

    def test_recent_backups_not_pruned(self, mgr, backup_dir):
        recent = backup_dir / "test_recent.db.gz"
        recent.write_bytes(b"fake")
        # mtime is just now (default)
        pruned = mgr._prune_old()
        assert pruned == 0
        assert recent.exists()


class TestBackupManagerSingleton:
    def test_get_backup_manager_returns_instance(self):
        with patch("engine.nexus.backup_manager.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = "data/backups"
            mgr = get_backup_manager()
        assert isinstance(mgr, BackupManager)
