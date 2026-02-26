"""Tests for RouterDataCollector — router training data capture."""
from __future__ import annotations

import json
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.router_data import (
    RouterDataCollector,
    RouterRecord,
    get_router_data_collector,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def db_path(tmp_path):
    """Temporary DB path."""
    return str(tmp_path / "router_test.db")


@pytest.fixture()
def collector(db_path):
    """Fresh RouterDataCollector with temp DB."""
    return RouterDataCollector(db_path=db_path)


@pytest.fixture()
def sample_record():
    """A typical routing record."""
    return RouterRecord(
        agent_id="aria",
        task_type="chat",
        priority="interactive",
        prompt_tokens=150,
        has_tools=True,
        has_system_prompt=True,
        tier_selected="gpu_primary",
        model_used="qwen3-30b",
        latency_ms=450.5,
        tokens_generated=200,
        tokens_per_sec=44.3,
        success=True,
    )


# ── RouterRecord dataclass ──────────────────────────────────────────────


class TestRouterRecord:
    """Tests for the RouterRecord dataclass."""

    def test_defaults(self):
        """Default values are sensible."""
        rec = RouterRecord()
        assert rec.agent_id == ""
        assert rec.task_type == "chat"
        assert rec.priority == "interactive"
        assert rec.prompt_tokens == 0
        assert rec.has_tools is False
        assert rec.has_system_prompt is False
        assert rec.tier_selected == ""
        assert rec.model_used == ""
        assert rec.latency_ms == 0.0
        assert rec.tokens_generated == 0
        assert rec.tokens_per_sec == 0.0
        assert rec.success is True
        assert rec.error == ""
        assert rec.quality_score == -1
        assert rec.metadata == {}

    def test_metadata_default_not_shared(self):
        """Each record gets its own metadata dict."""
        r1 = RouterRecord()
        r2 = RouterRecord()
        r1.metadata["key"] = "value"
        assert "key" not in r2.metadata

    def test_custom_values(self, sample_record):
        """Custom values assigned correctly."""
        assert sample_record.agent_id == "aria"
        assert sample_record.has_tools is True
        assert sample_record.latency_ms == 450.5

    def test_error_field(self):
        """Error field stores failure reason."""
        rec = RouterRecord(success=False, error="Connection refused")
        assert rec.success is False
        assert rec.error == "Connection refused"


# ── Initialization ──────────────────────────────────────────────────────


class TestInit:
    """Tests for RouterDataCollector initialization."""

    def test_creates_db_file(self, db_path):
        """DB file created on init."""
        RouterDataCollector(db_path=db_path)
        assert os.path.exists(db_path)

    def test_creates_schema(self, db_path):
        """Schema tables and indices created."""
        import sqlite3
        RouterDataCollector(db_path=db_path)
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "router_decisions" in table_names
        conn.close()

    def test_creates_indices(self, db_path):
        """Indices created for performance."""
        import sqlite3
        RouterDataCollector(db_path=db_path)
        conn = sqlite3.connect(db_path)
        indices = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i[0] for i in indices]
        assert "idx_router_timestamp" in index_names
        assert "idx_router_task" in index_names
        conn.close()

    def test_idempotent_init(self, db_path):
        """Creating collector twice on same DB is safe."""
        c1 = RouterDataCollector(db_path=db_path)
        c1.record(RouterRecord(tier_selected="gpu_primary", task_type="chat", priority="interactive"))
        c1.flush()
        c2 = RouterDataCollector(db_path=db_path)
        stats = c2.get_stats()
        assert stats["total_records"] == 1

    def test_default_path_uses_config(self, tmp_path):
        """Without db_path, uses config training.datasets.base_dir."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = str(tmp_path / "train_data")
        with patch("engine.config.get_config", return_value=mock_cfg):
            c = RouterDataCollector()
            assert "router_training.db" in c._db_path
            assert str(tmp_path) in c._db_path


# ── record() and buffering ──────────────────────────────────────────────


class TestRecord:
    """Tests for record() buffering behavior."""

    def test_record_buffers(self, collector, sample_record):
        """Records go to buffer, not DB, until flush."""
        collector.record(sample_record)
        assert len(collector._buffer) == 1
        stats = collector.get_stats()
        assert stats["total_records"] == 0

    def test_auto_flush_at_buffer_size(self, collector):
        """Buffer auto-flushes when full."""
        collector._buffer_size = 5
        for i in range(5):
            collector.record(RouterRecord(
                tier_selected="gpu_primary", task_type="chat", priority="interactive",
            ))
        assert len(collector._buffer) == 0
        stats = collector.get_stats()
        assert stats["total_records"] == 5

    def test_no_auto_flush_below_size(self, collector):
        """Buffer does not flush below threshold."""
        collector._buffer_size = 10
        for i in range(9):
            collector.record(RouterRecord(
                tier_selected="gpu_primary", task_type="chat", priority="interactive",
            ))
        assert len(collector._buffer) == 9
        stats = collector.get_stats()
        assert stats["total_records"] == 0


# ── flush() ─────────────────────────────────────────────────────────────


class TestFlush:
    """Tests for manual flush()."""

    def test_flush_returns_count(self, collector, sample_record):
        """flush() returns number of records written."""
        collector.record(sample_record)
        collector.record(sample_record)
        count = collector.flush()
        assert count == 2

    def test_flush_empty_returns_zero(self, collector):
        """Flushing empty buffer returns 0."""
        assert collector.flush() == 0

    def test_flush_writes_to_db(self, collector, sample_record):
        """Flushed records appear in DB."""
        collector.record(sample_record)
        collector.flush()
        stats = collector.get_stats()
        assert stats["total_records"] == 1

    def test_flush_clears_buffer(self, collector, sample_record):
        """Buffer is empty after flush."""
        collector.record(sample_record)
        collector.flush()
        assert len(collector._buffer) == 0

    def test_double_flush(self, collector, sample_record):
        """Second flush is a no-op."""
        collector.record(sample_record)
        collector.flush()
        assert collector.flush() == 0
        stats = collector.get_stats()
        assert stats["total_records"] == 1


# ── get_stats() ─────────────────────────────────────────────────────────


class TestGetStats:
    """Tests for get_stats()."""

    def test_empty_stats(self, collector):
        """Stats on empty DB."""
        stats = collector.get_stats()
        assert stats["total_records"] == 0
        assert stats["by_task_type"] == {}
        assert stats["by_tier"] == {}
        assert stats["success_rate"] == 0.0
        assert stats["first_record"] is None

    def test_populated_stats(self, collector):
        """Stats with mixed records."""
        collector.record(RouterRecord(
            task_type="chat", priority="interactive",
            tier_selected="gpu_primary", success=True,
        ))
        collector.record(RouterRecord(
            task_type="act", priority="realtime",
            tier_selected="gpu_primary", success=True,
        ))
        collector.record(RouterRecord(
            task_type="chat", priority="background",
            tier_selected="cpu_utility", success=False,
        ))
        collector.flush()
        stats = collector.get_stats()
        assert stats["total_records"] == 3
        assert stats["by_task_type"]["chat"] == 2
        assert stats["by_task_type"]["act"] == 1
        assert stats["by_tier"]["gpu_primary"] == 2
        assert stats["by_tier"]["cpu_utility"] == 1
        assert stats["success_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_stats_buffer_pending(self, collector, sample_record):
        """Stats includes pending buffer count."""
        collector.record(sample_record)
        stats = collector.get_stats()
        assert stats["buffer_pending"] == 1

    def test_stats_db_path(self, collector, db_path):
        """Stats includes db_path."""
        stats = collector.get_stats()
        assert stats["db_path"] == db_path


# ── export_jsonl() ──────────────────────────────────────────────────────


class TestExportJsonl:
    """Tests for JSONL export."""

    def test_export_creates_file(self, collector, sample_record, tmp_path):
        """Export creates JSONL file."""
        collector.record(sample_record)
        collector.flush()
        out = str(tmp_path / "export.jsonl")
        count = collector.export_jsonl(out)
        assert count == 1
        assert os.path.exists(out)

    def test_export_format(self, collector, tmp_path):
        """Each line is valid JSON with expected fields."""
        collector.record(RouterRecord(
            agent_id="aria", task_type="chat", priority="interactive",
            tier_selected="gpu_primary", model_used="qwen3",
            has_tools=True, has_system_prompt=False, success=True,
        ))
        collector.flush()
        out = str(tmp_path / "export.jsonl")
        collector.export_jsonl(out)
        with open(out, "r", encoding="utf-8") as f:
            line = f.readline()
            data = json.loads(line)
            assert data["agent_id"] == "aria"
            assert data["has_tools"] is True
            assert data["has_system_prompt"] is False
            assert data["success"] is True
            assert "timestamp" in data
            assert "id" in data

    def test_export_empty(self, collector, tmp_path):
        """Export on empty DB writes empty file."""
        out = str(tmp_path / "empty.jsonl")
        count = collector.export_jsonl(out)
        assert count == 0
        with open(out, "r", encoding="utf-8") as f:
            assert f.read() == ""

    def test_export_limit(self, collector, tmp_path):
        """Export respects limit parameter."""
        for _ in range(10):
            collector.record(RouterRecord(
                tier_selected="gpu_primary", task_type="chat", priority="interactive",
            ))
        collector.flush()
        out = str(tmp_path / "limited.jsonl")
        count = collector.export_jsonl(out, limit=3)
        assert count == 3

    def test_export_multiple_records(self, collector, tmp_path):
        """Export writes one line per record."""
        for i in range(5):
            collector.record(RouterRecord(
                agent_id=f"agent_{i}",
                tier_selected="gpu_primary", task_type="chat", priority="interactive",
            ))
        collector.flush()
        out = str(tmp_path / "multi.jsonl")
        collector.export_jsonl(out)
        with open(out, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 5


# ── rate_last() ─────────────────────────────────────────────────────────


class TestRateLast:
    """Tests for quality rating."""

    def test_rate_last(self, collector, sample_record):
        """Rate most recent record."""
        collector.record(sample_record)
        collector.flush()
        assert collector.rate_last(4) is True
        out = str(os.path.join(os.path.dirname(collector._db_path), "check.jsonl"))
        collector.export_jsonl(out)
        with open(out, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
            assert data["quality_score"] == 4

    def test_rate_clamps_high(self, collector, sample_record):
        """Score clamped to max 5."""
        collector.record(sample_record)
        collector.flush()
        collector.rate_last(99)
        out = str(os.path.join(os.path.dirname(collector._db_path), "check.jsonl"))
        collector.export_jsonl(out)
        with open(out, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
            assert data["quality_score"] == 5

    def test_rate_clamps_low(self, collector, sample_record):
        """Score clamped to min 0."""
        collector.record(sample_record)
        collector.flush()
        collector.rate_last(-5)
        out = str(os.path.join(os.path.dirname(collector._db_path), "check.jsonl"))
        collector.export_jsonl(out)
        with open(out, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
            assert data["quality_score"] == 0

    def test_rate_empty_db(self, collector):
        """Rating empty DB returns True (no-op update)."""
        assert collector.rate_last(3) is True


# ── cleanup() ───────────────────────────────────────────────────────────


class TestCleanup:
    """Tests for old record cleanup."""

    def test_cleanup_removes_old(self, collector):
        """Records older than keep_days are removed."""
        import sqlite3
        collector.record(RouterRecord(
            tier_selected="gpu_primary", task_type="chat", priority="interactive",
        ))
        collector.flush()
        # Manually backdate the record
        conn = sqlite3.connect(collector._db_path)
        old_ts = time.time() - (100 * 86400)  # 100 days ago
        conn.execute("UPDATE router_decisions SET timestamp = ?", (old_ts,))
        conn.commit()
        conn.close()
        deleted = collector.cleanup(keep_days=90)
        assert deleted == 1
        stats = collector.get_stats()
        assert stats["total_records"] == 0

    def test_cleanup_keeps_recent(self, collector, sample_record):
        """Recent records are kept."""
        collector.record(sample_record)
        collector.flush()
        deleted = collector.cleanup(keep_days=90)
        assert deleted == 0
        stats = collector.get_stats()
        assert stats["total_records"] == 1

    def test_cleanup_empty_db(self, collector):
        """Cleanup on empty DB returns 0."""
        assert collector.cleanup() == 0


# ── Singleton ───────────────────────────────────────────────────────────


class TestSingleton:
    """Tests for get_router_data_collector() singleton."""

    def test_singleton_returns_same_instance(self, tmp_path):
        """Singleton returns the same object."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = str(tmp_path / "singleton_test")
        # Reset singleton
        RouterDataCollector._instance = None
        with patch("engine.config.get_config", return_value=mock_cfg):
            c1 = get_router_data_collector()
            c2 = get_router_data_collector()
            assert c1 is c2
        RouterDataCollector._instance = None  # cleanup

    def test_singleton_reset(self, tmp_path):
        """Resetting _instance creates new collector."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = str(tmp_path / "reset_test")
        RouterDataCollector._instance = None
        with patch("engine.config.get_config", return_value=mock_cfg):
            c1 = get_router_data_collector()
            RouterDataCollector._instance = None
            c2 = get_router_data_collector()
            assert c1 is not c2
        RouterDataCollector._instance = None  # cleanup


# ── Thread safety ───────────────────────────────────────────────────────


class TestThreadSafety:
    """Tests for concurrent access."""

    def test_concurrent_records(self, collector):
        """Multiple threads can record concurrently without errors."""
        collector._buffer_size = 100  # prevent auto-flush during test
        errors = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(20):
                    collector.record(RouterRecord(
                        agent_id=f"thread_{thread_id}",
                        tier_selected="gpu_primary",
                        task_type="chat",
                        priority="interactive",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        collector.flush()
        stats = collector.get_stats()
        assert stats["total_records"] == 100

    def test_concurrent_flush(self, collector):
        """Concurrent flushes don't duplicate records."""
        for i in range(20):
            collector.record(RouterRecord(
                tier_selected="gpu_primary", task_type="chat", priority="interactive",
            ))
        errors = []

        def flusher() -> None:
            try:
                collector.flush()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=flusher) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        stats = collector.get_stats()
        assert stats["total_records"] == 20


# ── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests."""

    def test_long_error_truncated(self, collector):
        """Error strings longer than 500 chars are truncated."""
        long_error = "x" * 1000
        collector.record(RouterRecord(
            tier_selected="gpu_primary", task_type="chat", priority="interactive",
            success=False, error=long_error,
        ))
        collector.flush()
        import sqlite3
        conn = sqlite3.connect(collector._db_path)
        row = conn.execute("SELECT error FROM router_decisions").fetchone()
        assert len(row[0]) == 500
        conn.close()

    def test_metadata_stored_as_json(self, collector, tmp_path):
        """Metadata dict is serialized to JSON."""
        collector.record(RouterRecord(
            tier_selected="gpu_primary", task_type="chat", priority="interactive",
            metadata={"scene": "bedroom", "turn": 5},
        ))
        collector.flush()
        out = str(tmp_path / "meta.jsonl")
        collector.export_jsonl(out)
        with open(out, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
            meta = json.loads(data["metadata"])
            assert meta["scene"] == "bedroom"
            assert meta["turn"] == 5

    def test_record_with_empty_metadata(self, collector):
        """Empty metadata serializes to '{}'."""
        collector.record(RouterRecord(
            tier_selected="gpu_primary", task_type="chat", priority="interactive",
        ))
        collector.flush()
        import sqlite3
        conn = sqlite3.connect(collector._db_path)
        row = conn.execute("SELECT metadata FROM router_decisions").fetchone()
        assert row[0] == "{}"
        conn.close()

    def test_bool_fields_stored_as_int(self, collector):
        """Boolean fields stored as 0/1 in SQLite."""
        collector.record(RouterRecord(
            tier_selected="gpu_primary", task_type="chat", priority="interactive",
            has_tools=True, has_system_prompt=False, success=True,
        ))
        collector.flush()
        import sqlite3
        conn = sqlite3.connect(collector._db_path)
        row = conn.execute(
            "SELECT has_tools, has_system_prompt, success FROM router_decisions"
        ).fetchone()
        assert row == (1, 0, 1)
        conn.close()

    def test_latency_rounded(self, collector):
        """Latency rounded to 1 decimal place."""
        collector.record(RouterRecord(
            tier_selected="gpu_primary", task_type="chat", priority="interactive",
            latency_ms=123.456789,
        ))
        collector.flush()
        import sqlite3
        conn = sqlite3.connect(collector._db_path)
        row = conn.execute("SELECT latency_ms FROM router_decisions").fetchone()
        assert row[0] == 123.5
        conn.close()
