"""Tests for engine.services.housekeeping — health checks, media ingest, integrity, cleanup."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

# Patch paths before importing so HousekeepingService never touches real dirs
_PATCH_PATHS = "engine.services.housekeeping"


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_response(status_code: int = 200, elapsed_ms: float = 12.0):
    """Build a fake requests.Response with .status_code and .elapsed."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.elapsed = SimpleNamespace(total_seconds=lambda: elapsed_ms / 1000)
    return resp


def _populate_media_dir(base: Path, folder: str, files: list[str]):
    """Create fake media files inside base/folder."""
    d = base / folder
    d.mkdir(parents=True, exist_ok=True)
    for fname in files:
        (d / fname).write_text("dummy")


def _make_db_mock(known_paths: list[str] | None = None,
                  records: list[tuple] | None = None,
                  character_row: tuple | None = ("char-1",)):
    """Return a MagicMock that behaves like Database for housekeeping queries."""
    db = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    db.get_connection.return_value = conn
    conn.cursor.return_value = cursor

    # Build a side-effect that answers different SQL queries
    _paths = known_paths or []
    _records = records or []

    def _fetchone_side_effect():
        # character lookup always returns character_row
        return character_row

    def _fetchall_side_effect():
        # Return based on what was last executed
        last_sql = cursor.execute.call_args[0][0] if cursor.execute.call_args else ""
        if "filepath" in last_sql and "type" not in last_sql:
            return [(p,) for p in _paths]
        if "filepath" in last_sql and "type" in last_sql:
            return _records
        return []

    cursor.fetchone.side_effect = _fetchone_side_effect
    cursor.fetchall.side_effect = _fetchall_side_effect
    return db


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def hk_service(mock_config):
    """HousekeepingService with injected config (no disk config loading)."""
    from engine.services.housekeeping import HousekeepingService
    return HousekeepingService(config=mock_config)


@pytest.fixture
def media_tree(tmp_path):
    """Create a temp media directory tree matching MEDIA_DIRS layout."""
    dirs = {
        "images": tmp_path / "asset" / "media" / "images",
        "video": tmp_path / "asset" / "media" / "video",
        "voice": tmp_path / "asset" / "media" / "voice",
        "images2": tmp_path / "content" / "media" / "images",
        "video2": tmp_path / "content" / "media" / "video",
        "voice2": tmp_path / "content" / "media" / "voice",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


# ═════════════════════════════════════════════════════════════════════════
#  check_services
# ═════════════════════════════════════════════════════════════════════════


class TestCheckServices:
    """Tests for check_services() — service health endpoint pinging."""

    @patch("requests.get")
    def test_all_services_healthy(self, mock_get, hk_service):
        """When every endpoint returns 200, all services are 'healthy'."""
        mock_get.return_value = _make_response(200, elapsed_ms=15.0)

        result = hk_service.check_services()

        assert set(result.keys()) == {"lmstudio", "comfyui", "tts", "mcp_bridge"}
        for info in result.values():
            assert info["status"] == "healthy"
            assert "response_ms" in info

    @patch("requests.get")
    def test_service_returns_non_200(self, mock_get, hk_service):
        """A 500 response should produce an error status, not 'healthy'."""
        mock_get.return_value = _make_response(500)

        result = hk_service.check_services()

        for info in result.values():
            assert info["status"] == "error (500)"
            assert "response_ms" not in info

    @patch("requests.get")
    def test_service_offline_connection_refused(self, mock_get, hk_service):
        """ConnectionError → status 'offline'."""
        import requests as _req
        mock_get.side_effect = _req.ConnectionError("refused")

        result = hk_service.check_services()

        for info in result.values():
            assert info["status"] == "offline"

    @patch("requests.get")
    def test_service_unexpected_error(self, mock_get, hk_service):
        """Unexpected exception → status includes error message."""
        mock_get.side_effect = RuntimeError("dns fail")

        result = hk_service.check_services()

        for info in result.values():
            assert "error" in info["status"]
            assert "dns fail" in info["status"]

    @patch("requests.get")
    def test_mixed_service_states(self, mock_get, hk_service):
        """Services can independently be healthy, offline, or errored."""
        import requests as _req
        responses = iter([
            _make_response(200, 10),                # lmstudio
            _req.ConnectionError("refused"),        # comfyui
            _make_response(503),                    # tts
            _make_response(200, 5),                 # mcp_bridge
        ])

        def _side_effect(*args, **kwargs):
            r = next(responses)
            if isinstance(r, Exception):
                raise r
            return r

        mock_get.side_effect = _side_effect

        result = hk_service.check_services()

        assert result["lmstudio"]["status"] == "healthy"
        assert result["comfyui"]["status"] == "offline"
        assert result["tts"]["status"] == "error (503)"
        assert result["mcp_bridge"]["status"] == "healthy"

    @patch("requests.get")
    def test_results_stored_on_instance(self, mock_get, hk_service):
        """check_services() saves results to self._results['services']."""
        mock_get.return_value = _make_response(200)

        hk_service.check_services()

        assert "services" in hk_service._results
        assert len(hk_service._results["services"]) == 4

    @patch("requests.get")
    def test_response_ms_only_on_200(self, mock_get, hk_service):
        """response_ms should only appear when status_code == 200."""
        mock_get.return_value = _make_response(404)

        result = hk_service.check_services()

        for info in result.values():
            assert "response_ms" not in info


# ═════════════════════════════════════════════════════════════════════════
#  check_integrity
# ═════════════════════════════════════════════════════════════════════════


class TestCheckIntegrity:
    """Tests for check_integrity() — orphan records and orphan files."""

    @patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {})
    @patch("content.simulation.database.db.Database")
    def test_empty_db_and_dirs(self, mock_db_cls, hk_service):
        """No records, no dirs → all zeroes, no orphans."""
        db = _make_db_mock(known_paths=[], records=[])
        mock_db_cls.return_value = db

        result = hk_service.check_integrity()

        assert result["orphan_records"] == []
        assert result["orphan_files"] == []
        assert result["total_records"] == 0
        assert result["total_files"] == 0

    @patch("content.simulation.database.db.Database")
    def test_orphan_record_missing_file(self, mock_db_cls, hk_service):
        """DB record pointing to non-existent file → orphan record."""
        ghost_path = "/nonexistent/photo.png"
        db = _make_db_mock(records=[("id-1", ghost_path, "image")])
        # Override fetchall to return records for both queries
        conn = db.get_connection.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [
            [("id-1", ghost_path, "image")],  # SELECT id, filepath, type
        ]

        mock_db_cls.return_value = db

        # Patch MEDIA_DIRS to empty so we skip orphan-file scanning
        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {}):
            result = hk_service.check_integrity()

        assert len(result["orphan_records"]) == 1
        assert result["orphan_records"][0]["filepath"] == ghost_path
        assert result["total_records"] == 1

    @patch("content.simulation.database.db.Database")
    def test_valid_record_with_existing_file(self, mock_db_cls, hk_service, tmp_path):
        """DB record pointing to a real file → no orphan."""
        real_file = tmp_path / "photo.png"
        real_file.write_text("img data")
        fp_str = str(real_file)

        db = _make_db_mock()
        conn = db.get_connection.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [
            [("id-1", fp_str, "image")],
        ]
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {}):
            result = hk_service.check_integrity()

        assert result["orphan_records"] == []
        assert result["total_records"] == 1

    @patch("content.simulation.database.db.Database")
    def test_orphan_file_not_in_db(self, mock_db_cls, hk_service, tmp_path):
        """File on disk with no matching DB record → orphan file."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "stray.png").write_text("data")

        db = _make_db_mock()
        conn = db.get_connection.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [
            [],  # no DB records at all
        ]
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}):
            result = hk_service.check_integrity()

        assert len(result["orphan_files"]) == 1
        assert result["orphan_files"][0]["name"] == "stray.png"
        assert result["total_files"] == 1

    @patch("content.simulation.database.db.Database")
    def test_file_known_in_db_not_orphan(self, mock_db_cls, hk_service, tmp_path):
        """File on disk that IS in DB → not an orphan file."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        f = img_dir / "known.png"
        f.write_text("data")
        fp_str = str(f)

        db = _make_db_mock()
        conn = db.get_connection.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [
            [("id-1", fp_str, "image")],  # record exists
        ]
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}):
            result = hk_service.check_integrity()

        assert result["orphan_files"] == []

    @patch("content.simulation.database.db.Database")
    def test_db_connection_failure(self, mock_db_cls, hk_service):
        """If DB is unreachable, return error in result."""
        mock_db_cls.side_effect = Exception("DB locked")

        result = hk_service.check_integrity()

        assert "error" in result
        assert "DB locked" in result["error"]

    @patch("content.simulation.database.db.Database")
    def test_results_stored_on_instance(self, mock_db_cls, hk_service):
        """check_integrity() saves to self._results['integrity']."""
        db = _make_db_mock()
        conn = db.get_connection.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[]]
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {}):
            hk_service.check_integrity()

        assert "integrity" in hk_service._results

    @patch("content.simulation.database.db.Database")
    def test_skips_directories_in_media_folder(self, mock_db_cls, hk_service, tmp_path):
        """Subdirectories inside a media folder should be skipped."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "subdir").mkdir()  # should be skipped

        db = _make_db_mock()
        conn = db.get_connection.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[]]
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}):
            result = hk_service.check_integrity()

        assert result["total_files"] == 0
        assert result["orphan_files"] == []


# ═════════════════════════════════════════════════════════════════════════
#  ingest_new_media (scan_for_new_media equivalent)
# ═════════════════════════════════════════════════════════════════════════


class TestIngestNewMedia:
    """Tests for ingest_new_media() — discovering and registering new files."""

    @patch("content.simulation.database.events.EventChain")
    @patch("content.simulation.database.db.Database")
    def test_ingests_new_image_file(self, mock_db_cls, mock_ec_cls, hk_service, tmp_path):
        """A new .png in the images folder should be ingested."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "new_photo.png").write_text("pixels")

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}):
            result = hk_service.ingest_new_media("char-1")

        assert len(result) == 1
        assert result[0]["name"] == "new_photo.png"
        assert result[0]["type"] == "image"

    @patch("content.simulation.database.db.Database")
    def test_skips_already_known_file(self, mock_db_cls, hk_service, tmp_path):
        """Files already in DB should not be re-ingested."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        f = img_dir / "old.png"
        f.write_text("pixels")

        db = _make_db_mock(known_paths=[str(f)])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}):
            result = hk_service.ingest_new_media("char-1")

        assert result == []

    @patch("content.simulation.database.db.Database")
    def test_skips_unsupported_extension(self, mock_db_cls, hk_service, tmp_path):
        """Files with unsupported extensions should be ignored."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "readme.txt").write_text("nope")

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png", ".jpg"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}):
            result = hk_service.ingest_new_media("char-1")

        assert result == []

    @patch("content.simulation.database.db.Database")
    def test_creates_missing_media_dir(self, mock_db_cls, hk_service, tmp_path):
        """If a media dir doesn't exist, it should be created (not crash)."""
        missing_dir = tmp_path / "nonexistent" / "voice"

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"voice": missing_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"voice": {".wav"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"voice": "voice"}):
            result = hk_service.ingest_new_media("char-1")

        assert result == []
        assert missing_dir.exists()

    @patch("content.simulation.database.db.Database")
    def test_skips_subdirectories(self, mock_db_cls, hk_service, tmp_path):
        """Subdirectories inside media dirs should be skipped."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "subdir").mkdir()

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}):
            result = hk_service.ingest_new_media("char-1")

        assert result == []

    @patch("content.simulation.database.db.Database")
    def test_db_failure_returns_empty(self, mock_db_cls, hk_service):
        """If DB connection fails, return empty list gracefully."""
        mock_db_cls.side_effect = Exception("connection refused")

        result = hk_service.ingest_new_media("char-1")

        assert result == []

    @patch("content.simulation.database.events.EventChain")
    @patch("content.simulation.database.db.Database")
    def test_multiple_files_multiple_types(self, mock_db_cls, mock_ec_cls,
                                           hk_service, tmp_path):
        """Ingest should handle files across different media types."""
        img_dir = tmp_path / "images"
        vid_dir = tmp_path / "video"
        img_dir.mkdir()
        vid_dir.mkdir()
        (img_dir / "pic.jpg").write_text("img")
        (vid_dir / "clip.mp4").write_text("vid")

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir, "video": vid_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS",
                   {"images": {".jpg"}, "video": {".mp4"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE",
                   {"images": "image", "video": "video"}):
            result = hk_service.ingest_new_media("char-1")

        assert len(result) == 2
        types = {r["type"] for r in result}
        assert types == {"image", "video"}

    @patch("content.simulation.database.events.EventChain")
    @patch("content.simulation.database.db.Database")
    def test_event_chain_logged_on_ingest(self, mock_db_cls, mock_ec_cls,
                                          hk_service, tmp_path):
        """When files are ingested, an event should be logged."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "a.png").write_text("px")

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}):
            hk_service.ingest_new_media("char-1")

        mock_ec_cls.return_value.log.assert_called_once()
        log_call = mock_ec_cls.return_value.log.call_args
        assert log_call[0][0] == "media_ingested"

    @patch("content.simulation.database.db.Database")
    def test_no_event_logged_when_nothing_ingested(self, mock_db_cls, hk_service, tmp_path):
        """No EventChain.log call when nothing is ingested."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        # Empty dir — nothing to ingest

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}), \
             patch("content.simulation.database.events.EventChain") as mock_ec_cls:
            hk_service.ingest_new_media("char-1")
            mock_ec_cls.return_value.log.assert_not_called()

    @patch("content.simulation.database.events.EventChain")
    @patch("content.simulation.database.db.Database")
    def test_ingested_item_has_uuid_id(self, mock_db_cls, mock_ec_cls,
                                       hk_service, tmp_path):
        """Each ingested item should have a UUID-format id."""
        import uuid
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "x.png").write_text("px")

        db = _make_db_mock(known_paths=[])
        mock_db_cls.return_value = db

        with patch(f"{_PATCH_PATHS}.MEDIA_DIRS", {"images": img_dir}), \
             patch(f"{_PATCH_PATHS}.SUPPORTED_EXTENSIONS", {"images": {".png"}}), \
             patch(f"{_PATCH_PATHS}.FOLDER_TO_TYPE", {"images": "image"}):
            result = hk_service.ingest_new_media("char-1")

        assert len(result) == 1
        uuid.UUID(result[0]["id"])  # should not raise


# ═════════════════════════════════════════════════════════════════════════
#  cleanup_temp_files
# ═════════════════════════════════════════════════════════════════════════


class TestCleanupTempFiles:
    """Tests for cleanup_temp_files() — stale __pycache__ removal."""

    def test_removes_old_cache_files(self, hk_service, tmp_path):
        """Files older than max_age_hours in __pycache__ should be removed."""
        cache_dir = tmp_path / "pkg" / "__pycache__"
        cache_dir.mkdir(parents=True)
        old_file = cache_dir / "module.cpython-311.pyc"
        old_file.write_text("bytecode")
        # Backdate mtime by 48 hours
        old_mtime = time.time() - (48 * 3600)
        os.utime(old_file, (old_mtime, old_mtime))

        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path):
            removed = hk_service.cleanup_temp_files(max_age_hours=24)

        assert removed == 1
        assert not old_file.exists()

    def test_keeps_recent_cache_files(self, hk_service, tmp_path):
        """Recently modified cache files should NOT be removed."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        recent_file = cache_dir / "fresh.pyc"
        recent_file.write_text("bytecode")
        # File just created — mtime is now, well within 24h

        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path):
            removed = hk_service.cleanup_temp_files(max_age_hours=24)

        assert removed == 0
        assert recent_file.exists()

    def test_no_pycache_dirs(self, hk_service, tmp_path):
        """No __pycache__ dirs at all → 0 removed, no crash."""
        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path):
            removed = hk_service.cleanup_temp_files()

        assert removed == 0

    def test_multiple_cache_dirs(self, hk_service, tmp_path):
        """Should scan nested __pycache__ dirs recursively."""
        old_time = time.time() - (48 * 3600)
        for sub in ["a", "b", "c"]:
            d = tmp_path / sub / "__pycache__"
            d.mkdir(parents=True)
            f = d / f"{sub}.pyc"
            f.write_text("data")
            os.utime(f, (old_time, old_time))

        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path):
            removed = hk_service.cleanup_temp_files(max_age_hours=24)

        assert removed == 3

    def test_custom_max_age(self, hk_service, tmp_path):
        """Custom max_age_hours should be respected."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        f = cache_dir / "test.pyc"
        f.write_text("data")
        # Set mtime to 2 hours ago
        mtime = time.time() - (2 * 3600)
        os.utime(f, (mtime, mtime))

        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path):
            # With 1h max age → should be removed
            removed = hk_service.cleanup_temp_files(max_age_hours=1)
            assert removed == 1

    def test_custom_max_age_keeps_newer(self, hk_service, tmp_path):
        """File within max_age window should be kept."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        f = cache_dir / "test.pyc"
        f.write_text("data")
        # Set mtime to 2 hours ago
        mtime = time.time() - (2 * 3600)
        os.utime(f, (mtime, mtime))

        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path):
            # With 4h max age → file is only 2h old, should be kept
            removed = hk_service.cleanup_temp_files(max_age_hours=4)
            assert removed == 0

    def test_unlink_failure_suppressed(self, hk_service, tmp_path):
        """If unlink fails (permission error), it should be suppressed."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        f = cache_dir / "locked.pyc"
        f.write_text("data")
        old_time = time.time() - (48 * 3600)
        os.utime(f, (old_time, old_time))

        with patch(f"{_PATCH_PATHS}._PROJECT_ROOT", tmp_path), \
             patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            removed = hk_service.cleanup_temp_files(max_age_hours=24)

        # unlink failed, so removed count stays 0
        assert removed == 0


# ═════════════════════════════════════════════════════════════════════════
#  run_all
# ═════════════════════════════════════════════════════════════════════════


class TestRunAll:
    """Tests for run_all() — orchestrates all housekeeping tasks."""

    def test_calls_all_checks_and_returns_report(self, hk_service):
        """run_all() should call check_services, check_integrity,
        ingest_new_media, and cleanup_temp_files, returning a combined report."""
        with patch.object(hk_service, "check_services", return_value={"lmstudio": {"status": "healthy"}}) as m_svc, \
             patch.object(hk_service, "check_integrity", return_value={"orphan_records": [], "orphan_files": [], "total_records": 5, "total_files": 5}) as m_int, \
             patch.object(hk_service, "ingest_new_media", return_value=[]) as m_ing, \
             patch.object(hk_service, "cleanup_temp_files", return_value=0) as m_cln:

            report = hk_service.run_all("char-1")

        m_svc.assert_called_once()
        m_int.assert_called_once()
        m_ing.assert_called_once_with("char-1")
        m_cln.assert_called_once()

    def test_report_structure(self, hk_service):
        """Report should have timestamp, services, integrity, ingested, cleaned."""
        with patch.object(hk_service, "check_services", return_value={}), \
             patch.object(hk_service, "check_integrity", return_value={"orphan_records": [], "orphan_files": [], "total_records": 0, "total_files": 0}), \
             patch.object(hk_service, "ingest_new_media", return_value=[]), \
             patch.object(hk_service, "cleanup_temp_files", return_value=3):

            report = hk_service.run_all()

        assert "timestamp" in report
        assert "services" in report
        assert "integrity" in report
        assert "ingested" in report
        assert report["cleaned"] == 3

    def test_report_timestamp_is_iso(self, hk_service):
        """Report timestamp should be a valid ISO-format datetime."""
        with patch.object(hk_service, "check_services", return_value={}), \
             patch.object(hk_service, "check_integrity", return_value={"orphan_records": [], "orphan_files": [], "total_records": 0, "total_files": 0}), \
             patch.object(hk_service, "ingest_new_media", return_value=[]), \
             patch.object(hk_service, "cleanup_temp_files", return_value=0):

            report = hk_service.run_all()

        # Should parse without error
        datetime.fromisoformat(report["timestamp"])

    def test_execution_order(self, hk_service):
        """Tasks must execute in order: services → integrity → ingest → cleanup."""
        call_order = []

        def _track(name):
            def _fn(*a, **kw):
                call_order.append(name)
                if name == "check_integrity":
                    return {"orphan_records": [], "orphan_files": [],
                            "total_records": 0, "total_files": 0}
                if name == "ingest_new_media":
                    return []
                if name == "cleanup_temp_files":
                    return 0
                return {}
            return _fn

        with patch.object(hk_service, "check_services", side_effect=_track("check_services")), \
             patch.object(hk_service, "check_integrity", side_effect=_track("check_integrity")), \
             patch.object(hk_service, "ingest_new_media", side_effect=_track("ingest_new_media")), \
             patch.object(hk_service, "cleanup_temp_files", side_effect=_track("cleanup_temp_files")):

            hk_service.run_all()

        assert call_order == [
            "check_services",
            "check_integrity",
            "ingest_new_media",
            "cleanup_temp_files",
        ]

    def test_default_character_id(self, hk_service):
        """run_all() without character_id should pass 'default' to ingest."""
        with patch.object(hk_service, "check_services", return_value={}), \
             patch.object(hk_service, "check_integrity", return_value={"orphan_records": [], "orphan_files": [], "total_records": 0, "total_files": 0}), \
             patch.object(hk_service, "ingest_new_media", return_value=[]) as m_ing, \
             patch.object(hk_service, "cleanup_temp_files", return_value=0):

            hk_service.run_all()

        m_ing.assert_called_once_with("default")


# ═════════════════════════════════════════════════════════════════════════
#  watch
# ═════════════════════════════════════════════════════════════════════════


class TestWatch:
    """Tests for watch() — continuous monitoring loop."""

    def test_watch_calls_run_all(self, hk_service):
        """watch() should call run_all() repeatedly until interrupted."""
        call_count = 0

        def _run_all_side_effect(cid):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise KeyboardInterrupt
            return {}

        with patch.object(hk_service, "run_all", side_effect=_run_all_side_effect), \
             patch(f"{_PATCH_PATHS}.time.sleep") as mock_sleep:

            hk_service.watch(interval=10, character_id="c1")

        assert call_count == 3
        # sleep should have been called between iterations (before the interrupt)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(10)

    def test_watch_keyboard_interrupt_stops_cleanly(self, hk_service):
        """KeyboardInterrupt should stop the loop without raising."""
        with patch.object(hk_service, "run_all", side_effect=KeyboardInterrupt), \
             patch(f"{_PATCH_PATHS}.time.sleep"):
            # Should not raise
            hk_service.watch(interval=5)

    def test_watch_passes_character_id(self, hk_service):
        """watch() passes the character_id to run_all."""
        def _stop(*a, **kw):
            raise KeyboardInterrupt

        with patch.object(hk_service, "run_all", side_effect=_stop) as m_run, \
             patch(f"{_PATCH_PATHS}.time.sleep"):
            hk_service.watch(interval=1, character_id="test-char")

        m_run.assert_called_with("test-char")


# ═════════════════════════════════════════════════════════════════════════
#  Constructor / config
# ═════════════════════════════════════════════════════════════════════════


class TestInit:
    """Tests for HousekeepingService construction and config loading."""

    def test_accepts_config_dict(self):
        """Passing a config dict skips _load_config()."""
        from engine.services.housekeeping import HousekeepingService
        cfg = {"key": "value"}
        hk = HousekeepingService(config=cfg)
        assert hk.config == cfg

    def test_empty_results_on_init(self):
        """Fresh instance should have empty _results."""
        from engine.services.housekeeping import HousekeepingService
        hk = HousekeepingService(config={})
        assert hk._results == {}

    @patch("engine.services.housekeeping.HousekeepingService._load_config")
    def test_loads_config_when_none_given(self, mock_load):
        """When no config passed, _load_config() is called."""
        mock_load.return_value = {"auto": True}
        from engine.services.housekeeping import HousekeepingService
        hk = HousekeepingService()
        assert hk.config == {"auto": True}

    def test_load_config_fallback_on_error(self):
        """_load_config() returns {} if engine.config is unavailable."""
        from engine.services.housekeeping import HousekeepingService
        with patch("engine.services.housekeeping.HousekeepingService._load_config",
                   wraps=HousekeepingService._load_config):
            with patch.dict("sys.modules", {"engine.config": None}):
                cfg = HousekeepingService._load_config()
                assert isinstance(cfg, dict)
