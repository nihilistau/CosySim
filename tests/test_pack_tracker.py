"""Tests for engine.observability.pack_tracker — PackTracker module.

Covers construction, recording, aggregation, cross-referencing,
hook wiring, hourly rollup, thread safety, persistence, and edge cases.
"""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.pack_tracker import (
    PackActivity,
    PackTracker,
    SkillExecution,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def tracker(tmp_path):
    """Fresh PackTracker backed by a temp SQLite database."""
    return PackTracker(db_path=str(tmp_path / "test.db"))


@pytest.fixture()
def db_path(tmp_path):
    """Reusable temp DB path string for persistence tests."""
    return str(tmp_path / "persist.db")


# ── Data-model unit tests ──────────────────────────────────────────────


def test_skill_execution_cpu_delta():
    """cpu_delta returns the positive difference between after and before."""
    ex = SkillExecution(
        pack="world",
        skill_name="describe",
        duration_s=0.5,
        timestamp=time.time(),
        pid=1,
        cpu_seconds_before=1.0,
        cpu_seconds_after=1.8,
    )
    assert ex.cpu_delta == pytest.approx(0.8)


def test_skill_execution_cpu_delta_clamps_negative():
    """cpu_delta never goes below zero even if after < before."""
    ex = SkillExecution(
        pack="world",
        skill_name="describe",
        duration_s=0.1,
        timestamp=time.time(),
        pid=1,
        cpu_seconds_before=2.0,
        cpu_seconds_after=1.0,
    )
    assert ex.cpu_delta == 0.0


def test_skill_execution_to_dict():
    """to_dict includes all expected keys with rounded values."""
    ex = SkillExecution(
        pack="system",
        skill_name="ping",
        duration_s=0.12345,
        timestamp=100.0,
        pid=42,
        cpu_seconds_before=0.0,
        cpu_seconds_after=0.05,
        memory_mb=128.567,
        success=False,
        error="timeout",
    )
    d = ex.to_dict()
    assert d["pack"] == "system"
    assert d["skill"] == "ping"
    assert d["duration_s"] == pytest.approx(0.1235, abs=1e-4)
    assert d["cpu_delta_s"] == pytest.approx(0.05, abs=1e-4)
    assert d["memory_mb"] == pytest.approx(128.6, abs=0.1)
    assert d["pid"] == 42
    assert d["success"] is False
    assert d["error"] == "timeout"
    assert d["ts"] == 100.0


def test_pack_activity_to_dict_success_rate():
    """PackActivity.to_dict computes success_rate correctly."""
    pa = PackActivity(
        pack="combat",
        total_calls=10,
        success_count=7,
        error_count=3,
    )
    d = pa.to_dict()
    assert d["success_rate"] == pytest.approx(0.7)
    assert d["error_count"] == 3


def test_pack_activity_to_dict_zero_calls():
    """PackActivity.to_dict avoids division by zero when total_calls is 0."""
    pa = PackActivity(pack="empty", total_calls=0, success_count=0)
    d = pa.to_dict()
    assert d["success_rate"] == pytest.approx(0.0)


# ── Construction ────────────────────────────────────────────────────────


def test_construction_with_custom_db_path(tmp_path):
    """PackTracker initialises its DB schema at the given db_path."""
    path = str(tmp_path / "custom.db")
    pt = PackTracker(db_path=path)

    assert pt._db_path == path
    assert os.path.isfile(path)


def test_construction_creates_tables(tracker):
    """DB schema contains the three expected tables."""
    conn = tracker._get_db()
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "pack_executions" in tables
    assert "pack_pid_map" in tables
    assert "pack_hourly_rollup" in tables


def test_construction_default_params(tracker):
    """Default max_history and rollup_interval are applied."""
    assert tracker._max_history == 5000
    assert tracker._rollup_interval == 3600.0


def test_construction_custom_params(tmp_path):
    """Custom max_history and rollup_interval propagate."""
    pt = PackTracker(
        db_path=str(tmp_path / "c.db"),
        max_history=100,
        rollup_interval=600.0,
    )
    assert pt._max_history == 100
    assert pt._rollup_interval == 600.0


# ── record_execution ───────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_returns_skill_execution(mock_pid, tracker):
    """record_execution returns a populated SkillExecution object."""
    ex = tracker.record_execution("world", "look", 0.25, pid=99)

    assert isinstance(ex, SkillExecution)
    assert ex.pack == "world"
    assert ex.skill_name == "look"
    assert ex.duration_s == 0.25
    assert ex.pid == 99
    assert ex.success is True


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_stores_in_memory(mock_pid, tracker):
    """In-memory aggregates update after record_execution."""
    tracker.record_execution("world", "look", 0.5, pid=10)
    tracker.record_execution("world", "move", 0.3, pid=10)

    assert tracker._pack_calls["world"] == 2
    assert len(tracker._pack_durations["world"]) == 2
    assert 10 in tracker._pack_pids["world"]
    assert tracker._pack_skills["world"]["look"] == 1
    assert tracker._pack_skills["world"]["move"] == 1


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_persists_to_db(mock_pid, tracker):
    """Execution data is written to the pack_executions table."""
    tracker.record_execution("combat", "attack", 1.23, pid=7)

    conn = tracker._get_db()
    rows = conn.execute("SELECT * FROM pack_executions").fetchall()
    assert len(rows) == 1
    assert rows[0]["pack"] == "combat"
    assert rows[0]["skill_name"] == "attack"
    assert rows[0]["duration_s"] == pytest.approx(1.23)
    assert rows[0]["pid"] == 7
    assert rows[0]["success"] == 1


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_failed_skill(mock_pid, tracker):
    """Failed executions set success=0 and store error text."""
    tracker.record_execution(
        "combat", "attack", 0.1, pid=1, success=False, error="miss"
    )

    assert tracker._pack_errors["combat"] == 1
    conn = tracker._get_db()
    row = conn.execute("SELECT * FROM pack_executions").fetchone()
    assert row["success"] == 0
    assert row["error"] == "miss"


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_default_pid(mock_pid, tracker):
    """When pid is omitted, os.getpid() is used."""
    ex = tracker.record_execution("system", "ping", 0.01)
    assert ex.pid == os.getpid()


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_cpu_fields(mock_pid, tracker):
    """cpu_before / cpu_after propagate into the SkillExecution."""
    ex = tracker.record_execution(
        "world", "render", 0.5, pid=1,
        cpu_before=10.0, cpu_after=10.4,
    )
    assert ex.cpu_delta == pytest.approx(0.4)

    conn = tracker._get_db()
    row = conn.execute("SELECT cpu_delta_s FROM pack_executions").fetchone()
    assert row["cpu_delta_s"] == pytest.approx(0.4)


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_metadata(mock_pid, tracker):
    """Metadata dict is JSON-serialised into the DB."""
    import json
    tracker.record_execution(
        "world", "look", 0.1, pid=1,
        metadata={"scene": "bedroom", "turn": 3},
    )
    conn = tracker._get_db()
    row = conn.execute("SELECT metadata_json FROM pack_executions").fetchone()
    meta = json.loads(row["metadata_json"])
    assert meta["scene"] == "bedroom"
    assert meta["turn"] == 3


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_zero_duration(mock_pid, tracker):
    """Zero-duration executions are recorded without error."""
    ex = tracker.record_execution("world", "noop", 0.0, pid=1)
    assert ex.duration_s == 0.0
    assert tracker._pack_calls["world"] == 1


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_caps_history(tmp_path):
    """In-memory list is capped at max_history."""
    pt = PackTracker(db_path=str(tmp_path / "cap.db"), max_history=5)
    for i in range(10):
        pt.record_execution("world", f"s{i}", 0.01, pid=1)

    assert len(pt._executions) == 5
    assert pt._executions[0].skill_name == "s5"


# ── pack_summary ────────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_pack_summary_empty(mock_pid, tracker):
    """pack_summary returns empty dict when no data recorded."""
    summary = tracker.pack_summary(hours=24.0)
    assert summary == {}


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_pack_summary_aggregates(mock_pid, tracker):
    """pack_summary aggregates calls, duration, and errors per pack."""
    tracker.record_execution("world", "look", 0.5, pid=1)
    tracker.record_execution("world", "move", 1.0, pid=1)
    tracker.record_execution("combat", "attack", 0.3, pid=2, success=False, error="miss")

    summary = tracker.pack_summary(hours=24.0)

    assert "world" in summary
    assert "combat" in summary

    w = summary["world"]
    assert w.total_calls == 2
    assert w.total_duration_s == pytest.approx(1.5)
    assert w.success_count == 2
    assert w.error_count == 0

    c = summary["combat"]
    assert c.total_calls == 1
    assert c.error_count == 1


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_pack_summary_skills_used(mock_pid, tracker):
    """pack_summary includes per-skill breakdown within each pack."""
    tracker.record_execution("world", "look", 0.1, pid=1)
    tracker.record_execution("world", "look", 0.2, pid=1)
    tracker.record_execution("world", "move", 0.3, pid=1)

    summary = tracker.pack_summary(hours=24.0)
    skills = summary["world"].skills_used
    assert skills["look"] == 2
    assert skills["move"] == 1


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_pack_summary_percentiles(mock_pid, tracker):
    """pack_summary computes p95 and p99 duration percentiles."""
    for i in range(20):
        tracker.record_execution("world", "tick", float(i), pid=1)

    summary = tracker.pack_summary(hours=24.0)
    w = summary["world"]
    assert w.p95_duration_s > 0
    assert w.p99_duration_s >= w.p95_duration_s


# ── top_packs ───────────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_top_packs_sort_by_calls(mock_pid, tracker):
    """top_packs sorted by 'calls' returns highest call count first."""
    for _ in range(5):
        tracker.record_execution("world", "look", 0.1, pid=1)
    for _ in range(10):
        tracker.record_execution("combat", "hit", 0.05, pid=1)
    tracker.record_execution("system", "ping", 0.01, pid=1)

    top = tracker.top_packs(n=3, sort_by="calls")
    assert len(top) == 3
    assert top[0]["pack"] == "combat"
    assert top[1]["pack"] == "world"
    assert top[2]["pack"] == "system"


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_top_packs_sort_by_duration(mock_pid, tracker):
    """top_packs sorted by 'duration' returns highest total duration first."""
    tracker.record_execution("slow", "wait", 10.0, pid=1)
    tracker.record_execution("fast", "go", 0.01, pid=1)

    top = tracker.top_packs(n=2, sort_by="duration")
    assert top[0]["pack"] == "slow"
    assert top[1]["pack"] == "fast"


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_top_packs_sort_by_errors(mock_pid, tracker):
    """top_packs sorted by 'errors' returns most errors first."""
    tracker.record_execution("buggy", "crash", 0.1, pid=1, success=False, error="boom")
    tracker.record_execution("buggy", "crash2", 0.1, pid=1, success=False, error="boom2")
    tracker.record_execution("stable", "ok", 0.1, pid=1)

    top = tracker.top_packs(n=2, sort_by="errors")
    assert top[0]["pack"] == "buggy"
    assert top[0]["error_count"] == 2


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_top_packs_limit(mock_pid, tracker):
    """top_packs respects the n parameter."""
    for i in range(5):
        tracker.record_execution(f"pack{i}", "skill", 0.1, pid=1)

    top = tracker.top_packs(n=2, sort_by="calls")
    assert len(top) == 2


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_top_packs_empty(mock_pid, tracker):
    """top_packs returns empty list when no data."""
    assert tracker.top_packs(n=5) == []


# ── cross_reference ────────────────────────────────────────────────────


def test_cross_reference_empty(tracker):
    """cross_reference returns empty dict with no PID mappings."""
    assert tracker.cross_reference(hours=24.0) == {}


def test_cross_reference_with_pid_mapping(tracker):
    """cross_reference builds matrix from pack_pid_map rows."""
    conn = tracker._get_db()
    now = time.time()
    conn.execute(
        "INSERT INTO pack_pid_map "
        "(ts, pack, pid, cpu_seconds, memory_mb, process_category, process_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, "world", 100, 5.5, 256.0, "python", "scene_worker"),
    )
    conn.execute(
        "INSERT INTO pack_pid_map "
        "(ts, pack, pid, cpu_seconds, memory_mb, process_category, process_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, "world", 101, 3.0, 128.0, "python", "scene_worker2"),
    )
    conn.execute(
        "INSERT INTO pack_pid_map "
        "(ts, pack, pid, cpu_seconds, memory_mb, process_category, process_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, "combat", 200, 1.0, 64.0, "gpu", "inference"),
    )
    conn.commit()

    matrix = tracker.cross_reference(hours=24.0)

    assert "world" in matrix
    assert "python" in matrix["world"]
    assert matrix["world"]["python"]["cpu_seconds"] == pytest.approx(8.5)
    assert matrix["world"]["python"]["execution_count"] == 2

    assert "combat" in matrix
    assert "gpu" in matrix["combat"]


# ── hook_skill_registry ─────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_hook_skill_registry_patches_execute(mock_pid, tracker):
    """hook_skill_registry replaces SKILL_REGISTRY.execute_skill."""
    mock_meta = MagicMock()
    mock_meta.pack = "test_pack"

    mock_registry = MagicMock()
    mock_registry.execute_skill = MagicMock(return_value="result")
    mock_registry.get_skill = MagicMock(return_value=mock_meta)

    with patch.dict(
        "sys.modules",
        {"psutil": MagicMock()},
    ):
        with patch(
            "engine.skills.registry.SKILL_REGISTRY", mock_registry
        ):
            result = tracker.hook_skill_registry()

    assert result is True
    assert tracker._hooked is True
    assert tracker._original_execute is not None


def test_hook_skill_registry_idempotent(tracker):
    """Calling hook_skill_registry twice returns True without re-patching."""
    tracker._hooked = True
    assert tracker.hook_skill_registry() is True


def test_hook_skill_registry_import_failure(tracker):
    """hook_skill_registry returns False when imports fail."""
    with patch.dict("sys.modules", {"engine.skills.registry": None}):
        result = tracker.hook_skill_registry()
    assert result is False
    assert tracker._hooked is False


# ── unhook_skill_registry ──────────────────────────────────────────────


def test_unhook_restores_original(tracker):
    """unhook_skill_registry restores the original execute_skill method."""
    original_fn = MagicMock()
    tracker._hooked = True
    tracker._original_execute = original_fn

    mock_registry = MagicMock()
    with patch("engine.skills.registry.SKILL_REGISTRY", mock_registry):
        tracker.unhook_skill_registry()

    assert mock_registry.execute_skill == original_fn
    assert tracker._hooked is False
    assert tracker._original_execute is None


# ── Lifecycle (start / stop) ───────────────────────────────────────────


def test_start_sets_running(tracker):
    """start() sets _running and attempts hook."""
    with patch.object(tracker, "hook_skill_registry"):
        tracker.start()
    assert tracker._running is True


def test_start_idempotent(tracker):
    """Calling start() twice does not re-hook."""
    tracker._running = True
    with patch.object(tracker, "hook_skill_registry") as mock_hook:
        tracker.start()
    mock_hook.assert_not_called()


def test_stop_clears_running(tracker):
    """stop() clears _running and unhooks."""
    tracker._running = True
    with patch.object(tracker, "unhook_skill_registry"):
        tracker.stop()
    assert tracker._running is False


# ── _hourly_rollup ──────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_hourly_rollup_writes_aggregates(mock_pid, tracker):
    """_do_rollup writes aggregate rows to pack_hourly_rollup."""
    now = time.time()
    hour_ts = now - (now % 3600)
    prev_hour_start = hour_ts - 3600

    conn = tracker._get_db()
    for i in range(5):
        conn.execute(
            "INSERT INTO pack_executions "
            "(ts, pack, skill_name, duration_s, cpu_delta_s, memory_mb, pid, success, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (prev_hour_start + i, "world", "tick", float(i + 1), 0.1, 50.0, 1, 1, ""),
        )
    conn.commit()

    tracker._do_rollup()

    rows = conn.execute("SELECT * FROM pack_hourly_rollup").fetchall()
    assert len(rows) == 1
    assert rows[0]["pack"] == "world"
    assert rows[0]["call_count"] == 5
    assert rows[0]["total_duration_s"] == pytest.approx(15.0)


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_hourly_rollup_triggered_by_interval(mock_pid, tmp_path):
    """record_execution triggers rollup when rollup_interval elapsed."""
    pt = PackTracker(
        db_path=str(tmp_path / "rollup.db"),
        rollup_interval=0.0,
    )
    pt._last_rollup = 0.0

    with patch.object(pt, "_do_rollup") as mock_rollup:
        pt.record_execution("world", "look", 0.1, pid=1)
    mock_rollup.assert_called_once()


# ── recent_executions ──────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_recent_executions_returns_latest(mock_pid, tracker):
    """recent_executions returns the N most recent rows."""
    for i in range(5):
        tracker.record_execution("world", f"s{i}", float(i), pid=1)

    recent = tracker.recent_executions(n=3)
    assert len(recent) == 3
    assert recent[0]["skill_name"] == "s4"


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_recent_executions_filter_by_pack(mock_pid, tracker):
    """recent_executions filters by pack when specified."""
    tracker.record_execution("world", "look", 0.1, pid=1)
    tracker.record_execution("combat", "hit", 0.2, pid=1)

    world_only = tracker.recent_executions(n=10, pack="world")
    assert len(world_only) == 1
    assert world_only[0]["pack"] == "world"


# ── skill_leaderboard ──────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_skill_leaderboard(mock_pid, tracker):
    """skill_leaderboard returns skills ranked by CPU time."""
    tracker.record_execution("world", "look", 0.1, pid=1, cpu_before=0, cpu_after=5)
    tracker.record_execution("world", "move", 0.1, pid=1, cpu_before=0, cpu_after=1)
    tracker.record_execution("combat", "hit", 0.1, pid=1, cpu_before=0, cpu_after=3)

    board = tracker.skill_leaderboard(hours=24.0, top_n=2)
    assert len(board) == 2
    assert board[0]["skill_name"] == "look"


# ── pack_processes ─────────────────────────────────────────────────────


def test_pack_processes_empty(tracker):
    """pack_processes returns empty list for unknown pack."""
    assert tracker.pack_processes("nonexistent") == []


def test_pack_processes_returns_data(tracker):
    """pack_processes returns PID data from pack_pid_map."""
    conn = tracker._get_db()
    now = time.time()
    conn.execute(
        "INSERT INTO pack_pid_map "
        "(ts, pack, pid, cpu_seconds, memory_mb, process_category, process_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, "world", 42, 2.5, 100.0, "python", "worker"),
    )
    conn.commit()

    procs = tracker.pack_processes("world", hours=1.0)
    assert len(procs) == 1
    assert procs[0]["pid"] == 42
    assert procs[0]["process_category"] == "python"


# ── hourly_trends ──────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_hourly_trends_empty(mock_pid, tracker):
    """hourly_trends returns empty list with no rollup data."""
    assert tracker.hourly_trends(hours=24) == []


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_hourly_trends_returns_rollup_data(mock_pid, tracker):
    """hourly_trends returns rows from pack_hourly_rollup."""
    conn = tracker._get_db()
    now = time.time()
    conn.execute(
        "INSERT INTO pack_hourly_rollup "
        "(hour_ts, pack, call_count, total_duration_s, total_cpu_s, "
        "avg_duration_s, p95_duration_s, error_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now, "world", 100, 50.0, 10.0, 0.5, 1.2, 3),
    )
    conn.commit()

    trends = tracker.hourly_trends(pack="world", hours=24)
    assert len(trends) == 1
    assert trends[0]["call_count"] == 100


# ── prune ──────────────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_prune_removes_old_data(mock_pid, tracker):
    """prune deletes rows older than max_age_hours."""
    conn = tracker._get_db()
    old_ts = time.time() - 999999
    conn.execute(
        "INSERT INTO pack_executions "
        "(ts, pack, skill_name, duration_s, pid, success) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (old_ts, "old", "skill", 0.1, 1, 1),
    )
    conn.commit()

    deleted = tracker.prune(max_age_hours=1.0)
    assert deleted >= 1

    rows = conn.execute("SELECT * FROM pack_executions").fetchall()
    assert len(rows) == 0


# ── snapshot ────────────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_snapshot_structure(mock_pid, tracker):
    """snapshot returns expected top-level keys."""
    tracker.record_execution("world", "look", 0.1, pid=1)

    snap = tracker.snapshot()
    assert "total_calls" in snap
    assert "total_cpu_seconds" in snap
    assert "active_packs" in snap
    assert "hooked" in snap
    assert "running" in snap
    assert "top_packs" in snap
    assert "cross_reference" in snap
    assert snap["total_calls"] == 1
    assert snap["active_packs"] == 1


# ── Thread safety ──────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_concurrent_record_execution(mock_pid, tmp_path):
    """Concurrent record_execution calls do not corrupt in-memory state."""
    pt = PackTracker(db_path=str(tmp_path / "thread.db"))
    n_threads = 8
    calls_per_thread = 50
    barrier = threading.Barrier(n_threads)

    def worker(thread_id):
        barrier.wait()
        for i in range(calls_per_thread):
            pt.record_execution(
                f"pack_{thread_id % 3}",
                f"skill_{i}",
                0.001,
                pid=thread_id,
            )

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = sum(pt._pack_calls.values())
    assert total == n_threads * calls_per_thread

    conn = pt._get_db()
    db_count = conn.execute("SELECT COUNT(*) FROM pack_executions").fetchone()[0]
    assert db_count == n_threads * calls_per_thread


# ── Database persistence ───────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_persistence_across_instances(mock_pid, db_path):
    """Data written by one PackTracker instance is readable by another."""
    # Arrange — write with instance 1
    pt1 = PackTracker(db_path=db_path)
    pt1.record_execution("world", "look", 0.42, pid=10)
    pt1.record_execution("combat", "hit", 0.88, pid=20)

    # Act — read with instance 2
    pt2 = PackTracker(db_path=db_path)
    summary = pt2.pack_summary(hours=24.0)

    # Assert
    assert "world" in summary
    assert "combat" in summary
    assert summary["world"].total_calls == 1
    assert summary["combat"].total_calls == 1


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_persistence_recent_executions(mock_pid, db_path):
    """recent_executions reads rows persisted by a previous instance."""
    pt1 = PackTracker(db_path=db_path)
    pt1.record_execution("world", "look", 0.5, pid=1)

    pt2 = PackTracker(db_path=db_path)
    recent = pt2.recent_executions(n=10)
    assert len(recent) == 1
    assert recent[0]["pack"] == "world"


# ── Edge cases ─────────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_unknown_pack_name(mock_pid, tracker):
    """Arbitrary / unknown pack names are recorded without issue."""
    ex = tracker.record_execution("__unknown__", "mystery", 0.01, pid=1)
    assert ex.pack == "__unknown__"
    summary = tracker.pack_summary(hours=24.0)
    assert "__unknown__" in summary


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_empty_strings_accepted(mock_pid, tracker):
    """Empty pack and skill names are accepted (graceful, not crash)."""
    ex = tracker.record_execution("", "", 0.0, pid=1)
    assert ex.pack == ""
    assert ex.skill_name == ""


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_very_large_duration(mock_pid, tracker):
    """Very large duration values are stored without overflow."""
    ex = tracker.record_execution("slow", "wait", 999999.99, pid=1)
    assert ex.duration_s == pytest.approx(999999.99)


def test_percentile_empty():
    """_percentile returns 0.0 for empty data."""
    assert PackTracker._percentile([], 95) == 0.0


def test_percentile_single_element():
    """_percentile with one element returns that element."""
    assert PackTracker._percentile([42.0], 95) == pytest.approx(42.0)


def test_percentile_known_values():
    """_percentile computes correctly for known sorted input."""
    data = list(range(1, 101))  # 1..100
    p50 = PackTracker._percentile(data, 50)
    assert 49 < p50 < 52

    p95 = PackTracker._percentile(data, 95)
    assert 94 < p95 < 97


@patch("engine.observability.pack_tracker.PackTracker._record_pid_mapping")
def test_record_execution_memory_field(mock_pid, tracker):
    """memory_mb field propagates into the execution and DB."""
    ex = tracker.record_execution("gpu", "render", 0.5, pid=1, memory_mb=4096.5)
    assert ex.memory_mb == pytest.approx(4096.5)

    conn = tracker._get_db()
    row = conn.execute("SELECT memory_mb FROM pack_executions").fetchone()
    assert row["memory_mb"] == pytest.approx(4096.5)
