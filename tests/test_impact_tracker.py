"""Tests for engine.nexus.impact_tracker.

Covers initialisation, change recording, snapshots, impact computation,
finalization, queries, reports, edge cases, and integration helpers.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# Patch get_config before importing the module under test so the
# constructor never touches real config files.
_CFG_PATCH = "engine.nexus.impact_tracker.get_config"


def _make_mock_config() -> MagicMock:
    """Return a mock config with sensible defaults."""
    cfg = MagicMock()
    cfg.get = lambda key, default=None: default
    return cfg


def _stub_metrics() -> Dict[str, float]:
    """A small deterministic metric set used across tests."""
    return {
        "pipeline.avg_latency_ms": 120.0,
        "pipeline.avg_tps": 45.0,
        "nexus.entries.total": 500.0,
        "system.cpu_pct": 35.0,
    }


def _make_tracker(tmp_path: Path) -> "ImpactTracker":
    """Create an ImpactTracker backed by a temp database."""
    from engine.nexus.impact_tracker import ImpactTracker

    with patch(_CFG_PATCH, return_value=_make_mock_config()):
        return ImpactTracker(db_path=tmp_path / "impact.db")


# ──── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def tracker(tmp_path: Path) -> "ImpactTracker":
    """Fresh ImpactTracker with an isolated temp database."""
    return _make_tracker(tmp_path)


@pytest.fixture()
def patched_tracker(tmp_path: Path) -> "ImpactTracker":
    """ImpactTracker with all metric collectors returning deterministic data."""
    t = _make_tracker(tmp_path)
    t._collect_system_metrics = lambda: {"system.cpu_pct": 35.0}
    t._collect_pipeline_metrics = lambda: {"pipeline.avg_latency_ms": 120.0, "pipeline.avg_tps": 45.0}
    t._collect_nexus_metrics = lambda: {"nexus.entries.total": 500.0}
    t._collect_scheduler_metrics = lambda: {}
    t._collect_training_metrics = lambda: {}
    return t


# ──── Initialisation ────────────────────────────────────────────────────────


class TestInitialisation:
    """Verify database bootstrapping and pragma setup."""

    def test_creates_database(self, tmp_path: Path) -> None:
        """Database file should be created on disk."""
        db_file = tmp_path / "test_init.db"
        with patch(_CFG_PATCH, return_value=_make_mock_config()):
            from engine.nexus.impact_tracker import ImpactTracker
            ImpactTracker(db_path=db_file)
        assert db_file.exists()

    def test_wal_mode(self, tracker: "ImpactTracker") -> None:
        """Database should use WAL journal mode for concurrency."""
        conn = tracker._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_tables_created(self, tracker: "ImpactTracker") -> None:
        """Schema should contain changes, metric_snapshots, and impact_scores."""
        conn = tracker._get_conn()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "changes" in tables
        assert "metric_snapshots" in tables
        assert "impact_scores" in tables


# ──── Change Recording ──────────────────────────────────────────────────────


class TestChangeRecording:
    """Verify record_change() behaviour."""

    def test_record_change_basic(self, patched_tracker: "ImpactTracker") -> None:
        """Recording a change should persist and return a SystemChange."""
        from engine.nexus.impact_tracker import ChangeType, SystemChange

        change = patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE,
            title="Bump timeout",
            description="Increased request timeout to 60s",
        )
        assert isinstance(change, SystemChange)
        assert change.change_id.startswith("chg-")
        assert change.change_type == ChangeType.CONFIG_CHANGE
        assert change.title == "Bump timeout"

    def test_record_change_with_metadata(self, patched_tracker: "ImpactTracker") -> None:
        """Metadata dict should be stored and retrievable."""
        from engine.nexus.impact_tracker import ChangeType

        meta = {"key": "lmstudio.timeout", "old": 30, "new": 60}
        change = patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE,
            title="Timeout",
            description="desc",
            metadata=meta,
        )
        fetched = patched_tracker.get_change(change.change_id)
        assert fetched is not None
        assert fetched.metadata == meta

    def test_record_change_auto_snapshot(self, patched_tracker: "ImpactTracker") -> None:
        """With auto_snapshot=True a baseline snapshot id should be set."""
        from engine.nexus.impact_tracker import ChangeType

        change = patched_tracker.record_change(
            ChangeType.MODEL_PROMOTION,
            title="Promote model",
            description="desc",
            auto_snapshot=True,
        )
        assert change.baseline_snapshot_id is not None
        assert change.baseline_snapshot_id.startswith("snap-")

    def test_record_change_all_types(self, patched_tracker: "ImpactTracker") -> None:
        """Every ChangeType enum value should be accepted."""
        from engine.nexus.impact_tracker import ChangeType

        for ct in ChangeType:
            change = patched_tracker.record_change(
                ct, title=f"test-{ct.value}", description="d", auto_snapshot=False,
            )
            assert change.change_type == ct

    def test_record_change_generates_unique_ids(
        self, patched_tracker: "ImpactTracker"
    ) -> None:
        """Each recorded change must receive a distinct id."""
        from engine.nexus.impact_tracker import ChangeType

        ids = set()
        for _ in range(20):
            c = patched_tracker.record_change(
                ChangeType.CODE_DEPLOY, title="t", description="d", auto_snapshot=False,
            )
            ids.add(c.change_id)
        assert len(ids) == 20


# ──── Snapshots ─────────────────────────────────────────────────────────────


class TestSnapshots:
    """Verify capture_snapshot() behaviour."""

    def test_capture_snapshot_before(self, patched_tracker: "ImpactTracker") -> None:
        """A 'before' snapshot should be linked to the change."""
        from engine.nexus.impact_tracker import ChangeType

        change = patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE, "t", "d", auto_snapshot=False,
        )
        snap = patched_tracker.capture_snapshot(change.change_id, "before")
        assert snap.snapshot_id.startswith("snap-")
        assert snap.phase == "before"
        assert snap.change_id == change.change_id

        refreshed = patched_tracker.get_change(change.change_id)
        assert refreshed is not None
        assert refreshed.baseline_snapshot_id == snap.snapshot_id

    def test_capture_snapshot_after(self, patched_tracker: "ImpactTracker") -> None:
        """An 'after' snapshot should update the after_snapshot_id column."""
        from engine.nexus.impact_tracker import ChangeType

        change = patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE, "t", "d", auto_snapshot=False,
        )
        snap = patched_tracker.capture_snapshot(change.change_id, "after")
        assert snap.phase == "after"

        refreshed = patched_tracker.get_change(change.change_id)
        assert refreshed is not None
        assert refreshed.after_snapshot_id == snap.snapshot_id

    def test_capture_multiple_metrics(self, patched_tracker: "ImpactTracker") -> None:
        """Snapshot should include metrics from all collectors."""
        from engine.nexus.impact_tracker import ChangeType

        change = patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE, "t", "d", auto_snapshot=False,
        )
        snap = patched_tracker.capture_snapshot(change.change_id, "before")
        assert "system.cpu_pct" in snap.metrics
        assert "pipeline.avg_latency_ms" in snap.metrics
        assert "nexus.entries.total" in snap.metrics

    def test_capture_snapshot_invalid_change_id(
        self, patched_tracker: "ImpactTracker"
    ) -> None:
        """Capturing for a non-existent change_id should still persist the row.

        The foreign key is enforced at schema level, so this should raise.
        """
        with pytest.raises(Exception):
            patched_tracker.capture_snapshot("nonexistent-id", "before")


# ──── Impact Computation ────────────────────────────────────────────────────


class TestImpactComputation:
    """Verify compute_impact() logic and severity classification."""

    def _record_with_snapshots(
        self,
        tracker: "ImpactTracker",
        before_metrics: Dict[str, float],
        after_metrics: Dict[str, float],
    ) -> str:
        """Helper: record a change and insert custom before/after snapshots."""
        from engine.nexus.impact_tracker import ChangeType

        # Temporarily override collectors to return controlled data
        tracker._collect_system_metrics = lambda: {}
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        change = tracker.record_change(
            ChangeType.EXPERIMENT_RESULT, "exp", "desc", auto_snapshot=False,
        )
        cid = change.change_id

        # Inject controlled metrics for the before snapshot
        tracker._collect_system_metrics = lambda: before_metrics
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}
        tracker.capture_snapshot(cid, "before")

        # Inject controlled metrics for the after snapshot
        tracker._collect_system_metrics = lambda: after_metrics
        tracker.capture_snapshot(cid, "after")

        return cid

    def test_compute_impact_improvement(self, tmp_path: Path) -> None:
        """A positive metric increase should yield a POSITIVE severity."""
        from engine.nexus.impact_tracker import ImpactSeverity

        tracker = _make_tracker(tmp_path)
        cid = self._record_with_snapshots(
            tracker,
            {"nexus.entries.total": 100.0},
            {"nexus.entries.total": 120.0},
        )
        scores = tracker.compute_impact(cid)
        assert len(scores) == 1
        assert scores[0].percentage_delta > 0
        assert scores[0].severity in (
            ImpactSeverity.POSITIVE_HIGH, ImpactSeverity.POSITIVE_LOW,
        )

    def test_compute_impact_regression(self, tmp_path: Path) -> None:
        """A metric decrease (non-inverted) should yield NEGATIVE severity."""
        from engine.nexus.impact_tracker import ImpactSeverity

        tracker = _make_tracker(tmp_path)
        cid = self._record_with_snapshots(
            tracker,
            {"nexus.entries.total": 100.0},
            {"nexus.entries.total": 70.0},
        )
        scores = tracker.compute_impact(cid)
        assert len(scores) == 1
        assert scores[0].percentage_delta < 0
        assert scores[0].severity in (
            ImpactSeverity.NEGATIVE_HIGH, ImpactSeverity.NEGATIVE_LOW,
        )

    def test_compute_impact_neutral(self, tmp_path: Path) -> None:
        """A tiny change should be classified as NEUTRAL."""
        from engine.nexus.impact_tracker import ImpactSeverity

        tracker = _make_tracker(tmp_path)
        cid = self._record_with_snapshots(
            tracker,
            {"nexus.entries.total": 100.0},
            {"nexus.entries.total": 100.5},
        )
        scores = tracker.compute_impact(cid)
        assert len(scores) == 1
        assert scores[0].severity == ImpactSeverity.NEUTRAL

    def test_compute_impact_severity_levels(self, tmp_path: Path) -> None:
        """Inverted metrics (latency) should treat decreases as positive."""
        from engine.nexus.impact_tracker import ImpactSeverity

        tracker = _make_tracker(tmp_path)
        # Latency drops from 200 → 100 = –50%, inverted → positive
        cid = self._record_with_snapshots(
            tracker,
            {"pipeline.avg_latency_ms": 200.0},
            {"pipeline.avg_latency_ms": 100.0},
        )
        scores = tracker.compute_impact(cid)
        assert len(scores) == 1
        assert scores[0].severity == ImpactSeverity.POSITIVE_HIGH

    def test_compute_impact_no_snapshots(self, tmp_path: Path) -> None:
        """Without both snapshots, compute_impact returns an empty list."""
        from engine.nexus.impact_tracker import ChangeType

        tracker = _make_tracker(tmp_path)
        tracker._collect_system_metrics = lambda: {}
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        change = tracker.record_change(
            ChangeType.CONFIG_CHANGE, "t", "d", auto_snapshot=False,
        )
        scores = tracker.compute_impact(change.change_id)
        assert scores == []


# ──── Finalization ──────────────────────────────────────────────────────────


class TestFinalization:
    """Verify finalize_change() orchestration."""

    def _setup_finalizable(self, tracker: "ImpactTracker") -> str:
        """Record a change with a before snapshot so finalize can do its job."""
        from engine.nexus.impact_tracker import ChangeType

        tracker._collect_system_metrics = lambda: {"system.cpu_pct": 40.0}
        tracker._collect_pipeline_metrics = lambda: {"pipeline.avg_tps": 50.0}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        change = tracker.record_change(
            ChangeType.CONFIG_CHANGE, "Tune batch", "desc", auto_snapshot=True,
        )
        # Simulate changed metrics for the after snapshot
        tracker._collect_system_metrics = lambda: {"system.cpu_pct": 30.0}
        tracker._collect_pipeline_metrics = lambda: {"pipeline.avg_tps": 60.0}
        return change.change_id

    @patch("engine.nexus.client.get_nexus_client")
    def test_finalize_change_success(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """Finalize should return a dict with change_id, scores, and summary."""
        mock_nexus.return_value = MagicMock()
        tracker = _make_tracker(tmp_path)
        cid = self._setup_finalizable(tracker)

        result = tracker.finalize_change(cid)
        assert result["change_id"] == cid
        assert isinstance(result["impact_scores"], list)
        assert len(result["impact_scores"]) > 0
        assert "summary" in result
        assert "Tune batch" in result["summary"]

    @patch("engine.nexus.client.get_nexus_client")
    def test_finalize_change_stores_nexus(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """Finalize should call Nexus client.add_entry for mirroring."""
        mock_client = MagicMock()
        mock_nexus.return_value = mock_client
        tracker = _make_tracker(tmp_path)
        cid = self._setup_finalizable(tracker)

        tracker.finalize_change(cid)
        mock_client.add_entry.assert_called_once()
        call_kwargs = mock_client.add_entry.call_args
        assert "Impact:" in call_kwargs.kwargs.get("title", "") or "Impact:" in call_kwargs[1].get("title", call_kwargs[0][0] if call_kwargs[0] else "")

    @patch("engine.nexus.client.get_nexus_client")
    def test_finalize_change_no_change(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """Finalizing a non-existent change should still return gracefully."""
        mock_nexus.return_value = MagicMock()
        tracker = _make_tracker(tmp_path)
        tracker._collect_system_metrics = lambda: {}
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        # Foreign key violation expected for a bogus change_id
        with pytest.raises(Exception):
            tracker.finalize_change("bogus-id")


# ──── Queries ───────────────────────────────────────────────────────────────


class TestQueries:
    """Verify read-path query methods."""

    def test_get_change_existing(self, patched_tracker: "ImpactTracker") -> None:
        """get_change should return the stored SystemChange."""
        from engine.nexus.impact_tracker import ChangeType, SystemChange

        change = patched_tracker.record_change(
            ChangeType.CODE_DEPLOY, "Deploy v2", "d", auto_snapshot=False,
        )
        fetched = patched_tracker.get_change(change.change_id)
        assert fetched is not None
        assert isinstance(fetched, SystemChange)
        assert fetched.title == "Deploy v2"

    def test_get_change_nonexistent(self, patched_tracker: "ImpactTracker") -> None:
        """get_change should return None for unknown ids."""
        assert patched_tracker.get_change("nope-12345678") is None

    def test_list_changes_all(self, patched_tracker: "ImpactTracker") -> None:
        """list_changes with no filter should return all recent changes."""
        from engine.nexus.impact_tracker import ChangeType

        for i in range(5):
            patched_tracker.record_change(
                ChangeType.CONFIG_CHANGE, f"c{i}", "d", auto_snapshot=False,
            )
        results = patched_tracker.list_changes()
        assert len(results) == 5

    def test_list_changes_by_type(self, patched_tracker: "ImpactTracker") -> None:
        """list_changes should filter by change_type when specified."""
        from engine.nexus.impact_tracker import ChangeType

        patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE, "cfg", "d", auto_snapshot=False,
        )
        patched_tracker.record_change(
            ChangeType.MODEL_PROMOTION, "model", "d", auto_snapshot=False,
        )
        patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE, "cfg2", "d", auto_snapshot=False,
        )

        cfg_only = patched_tracker.list_changes(change_type=ChangeType.CONFIG_CHANGE)
        assert len(cfg_only) == 2
        assert all(r["change_type"] == "config_change" for r in cfg_only)

    def test_list_changes_with_days_filter(self, patched_tracker: "ImpactTracker") -> None:
        """list_changes should respect the days lookback window."""
        from engine.nexus.impact_tracker import ChangeType

        patched_tracker.record_change(
            ChangeType.CONFIG_CHANGE, "recent", "d", auto_snapshot=False,
        )
        # Manually insert an old change
        old_ts = time.time() - 100 * 86400  # 100 days ago
        conn = patched_tracker._get_conn()
        conn.execute(
            "INSERT INTO changes (change_id, change_type, title, description, "
            "timestamp, source, metadata, impact_computed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            ("chg-old00001", "config_change", "ancient", "d", old_ts, "test", "{}"),
        )
        conn.commit()

        recent = patched_tracker.list_changes(days=30)
        assert all(r["title"] != "ancient" for r in recent)

        all_time = patched_tracker.list_changes(days=365)
        titles = [r["title"] for r in all_time]
        assert "ancient" in titles


# ──── Reports ───────────────────────────────────────────────────────────────


class TestReports:
    """Verify report-generation methods."""

    def _seed_data(self, tracker: "ImpactTracker") -> None:
        """Insert multiple changes with computed impact for report tests."""
        from engine.nexus.impact_tracker import ChangeType

        # Change 1: improvement (tps goes up, latency goes down)
        tracker._collect_system_metrics = lambda: {}
        tracker._collect_pipeline_metrics = lambda: {"pipeline.avg_tps": 40.0, "pipeline.avg_latency_ms": 150.0}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        c1 = tracker.record_change(
            ChangeType.CONFIG_CHANGE, "Optimise pipeline", "d",
            source="auto-tuner", auto_snapshot=True,
        )
        tracker._collect_pipeline_metrics = lambda: {"pipeline.avg_tps": 55.0, "pipeline.avg_latency_ms": 100.0}
        tracker.capture_snapshot(c1.change_id, "after")
        tracker.compute_impact(c1.change_id)

        # Change 2: regression (tps drops)
        tracker._collect_pipeline_metrics = lambda: {"pipeline.avg_tps": 55.0}
        c2 = tracker.record_change(
            ChangeType.CODE_DEPLOY, "Deploy refactor", "d",
            source="ci-cd", auto_snapshot=True,
        )
        tracker._collect_pipeline_metrics = lambda: {"pipeline.avg_tps": 30.0}
        tracker.capture_snapshot(c2.change_id, "after")
        tracker.compute_impact(c2.change_id)

    def test_attribution_report(self, tmp_path: Path) -> None:
        """attribution_report should return structured data with expected keys."""
        tracker = _make_tracker(tmp_path)
        self._seed_data(tracker)

        report = tracker.attribution_report(days=30)
        assert "total_changes" in report
        assert report["total_changes"] >= 2
        assert "top_positive" in report
        assert "top_negative" in report
        assert "by_type" in report
        assert "by_source" in report
        assert "uncomputed" in report

    def test_top_improvements(self, tmp_path: Path) -> None:
        """top_improvements should rank changes with positive avg delta."""
        tracker = _make_tracker(tmp_path)
        self._seed_data(tracker)

        top = tracker.top_improvements(days=30)
        assert isinstance(top, list)
        assert len(top) >= 1
        assert all(item["avg_pct_delta"] > 0 for item in top)
        assert "change_id" in top[0]
        assert "title" in top[0]

    def test_impact_timeline(self, tmp_path: Path) -> None:
        """impact_timeline should return chronological entries with impact data."""
        tracker = _make_tracker(tmp_path)
        self._seed_data(tracker)

        timeline = tracker.impact_timeline(days=30)
        assert isinstance(timeline, list)
        assert len(timeline) >= 2
        # Entries with computed impact should have non-None impact dict
        computed = [e for e in timeline if e.get("impact") is not None]
        assert len(computed) >= 2
        assert "metric_count" in computed[0]["impact"]
        assert "avg_delta" in computed[0]["impact"]

    def test_improvement_history(self, tmp_path: Path) -> None:
        """improvement_history should return deltas for a specific metric."""
        tracker = _make_tracker(tmp_path)
        self._seed_data(tracker)

        history = tracker.improvement_history("pipeline.avg_tps", days=30)
        assert isinstance(history, list)
        assert len(history) >= 1
        assert "delta" in history[0]
        assert "title" in history[0]
        assert "change_id" in history[0]


# ──── Integration ───────────────────────────────────────────────────────────


class TestIntegration:
    """Verify singleton, registration, and Nexus mirroring."""

    def test_register_impact_tasks(self) -> None:
        """register_impact_tasks should call daemon.register once."""
        from engine.nexus.impact_tracker import register_impact_tasks

        daemon = MagicMock()
        register_impact_tasks(daemon)
        daemon.register.assert_called_once()
        call_kwargs = daemon.register.call_args
        assert call_kwargs.kwargs.get("task_id") == "impact-summary" or call_kwargs[1].get("task_id") == "impact-summary"

    def test_singleton_pattern(self, tmp_path: Path) -> None:
        """get_impact_tracker should return the same instance on repeated calls."""
        import engine.nexus.impact_tracker as mod

        # Reset module-level singleton
        mod._instance = None
        try:
            with patch(_CFG_PATCH, return_value=_make_mock_config()):
                a = mod.get_impact_tracker(db_path=tmp_path / "singleton.db")
                b = mod.get_impact_tracker()
            assert a is b
        finally:
            mod._instance = None

    @patch("engine.nexus.client.get_nexus_client")
    def test_nexus_storage(
        self, mock_nexus: MagicMock, tmp_path: Path
    ) -> None:
        """Nexus failure in finalize should not raise; it is best-effort."""
        mock_client = MagicMock()
        mock_client.add_entry.side_effect = ConnectionError("Nexus offline")
        mock_nexus.return_value = mock_client

        tracker = _make_tracker(tmp_path)
        tracker._collect_system_metrics = lambda: {"system.cpu_pct": 50.0}
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        from engine.nexus.impact_tracker import ChangeType

        change = tracker.record_change(
            ChangeType.CONFIG_CHANGE, "test", "d", auto_snapshot=True,
        )
        tracker._collect_system_metrics = lambda: {"system.cpu_pct": 40.0}
        result = tracker.finalize_change(change.change_id)
        # Should succeed despite Nexus error
        assert "summary" in result


# ──── Edge Cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary conditions and stress-ish scenarios."""

    def test_empty_database_queries(self, tracker: "ImpactTracker") -> None:
        """All query methods should return empty results on a fresh database."""
        assert tracker.get_change("nope") is None
        assert tracker.list_changes() == []
        assert tracker.get_impact("nope") == []
        assert tracker.improvement_history("any.metric") == []
        assert tracker.top_improvements() == []
        assert tracker.impact_timeline() == []
        report = tracker.attribution_report()
        assert report["total_changes"] == 0
        assert report["top_positive"] == []
        assert report["top_negative"] == []

    def test_large_dataset_performance(self, tmp_path: Path) -> None:
        """100 changes with computed impact should query in < 2 seconds."""
        tracker = _make_tracker(tmp_path)
        tracker._collect_system_metrics = lambda: {"m1": 10.0, "m2": 20.0}
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        from engine.nexus.impact_tracker import ChangeType

        for i in range(100):
            c = tracker.record_change(
                ChangeType.CONFIG_CHANGE, f"c{i}", "d", auto_snapshot=True,
            )
            tracker._collect_system_metrics = lambda: {"m1": 10.0 + i, "m2": 20.0 - i * 0.1}
            tracker.capture_snapshot(c.change_id, "after")
            tracker.compute_impact(c.change_id)

        start = time.time()
        tracker.attribution_report(days=30)
        tracker.top_improvements(days=30)
        tracker.impact_timeline(days=30)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Queries took {elapsed:.2f}s on 100 changes"

    def test_concurrent_changes(self, tmp_path: Path) -> None:
        """Multiple threads recording changes should not corrupt the database."""
        tracker = _make_tracker(tmp_path)
        tracker._collect_system_metrics = lambda: {"m": 1.0}
        tracker._collect_pipeline_metrics = lambda: {}
        tracker._collect_nexus_metrics = lambda: {}
        tracker._collect_scheduler_metrics = lambda: {}
        tracker._collect_training_metrics = lambda: {}

        from engine.nexus.impact_tracker import ChangeType

        errors: list = []

        def _worker(idx: int) -> None:
            try:
                tracker.record_change(
                    ChangeType.CONFIG_CHANGE,
                    f"thread-{idx}",
                    "d",
                    auto_snapshot=False,
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Concurrent recording errors: {errors}"
        results = tracker.list_changes(limit=100)
        assert len(results) == 10


# ──── Severity Classification ───────────────────────────────────────────────


class TestSeverityClassification:
    """Verify _classify_severity boundary values."""

    def test_positive_high(self) -> None:
        """Percentage delta > +10 → POSITIVE_HIGH."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        assert _classify_severity(15.0, "some.metric") == ImpactSeverity.POSITIVE_HIGH

    def test_positive_low(self) -> None:
        """Percentage delta +1 to +10 → POSITIVE_LOW."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        assert _classify_severity(5.0, "some.metric") == ImpactSeverity.POSITIVE_LOW

    def test_neutral(self) -> None:
        """Percentage delta –1 to +1 → NEUTRAL."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        assert _classify_severity(0.5, "some.metric") == ImpactSeverity.NEUTRAL
        assert _classify_severity(-0.5, "some.metric") == ImpactSeverity.NEUTRAL

    def test_negative_low(self) -> None:
        """Percentage delta –10 to –1 → NEGATIVE_LOW."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        assert _classify_severity(-5.0, "some.metric") == ImpactSeverity.NEGATIVE_LOW

    def test_negative_high(self) -> None:
        """Percentage delta < –10 → NEGATIVE_HIGH."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        assert _classify_severity(-15.0, "some.metric") == ImpactSeverity.NEGATIVE_HIGH

    def test_inverted_metric_decrease_is_positive(self) -> None:
        """For inverted metrics, a decrease should be treated as positive."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        # –50% on latency → effective = +50% → POSITIVE_HIGH
        assert _classify_severity(-50.0, "pipeline.avg_latency_ms") == ImpactSeverity.POSITIVE_HIGH

    def test_inverted_metric_increase_is_negative(self) -> None:
        """For inverted metrics, an increase should be treated as negative."""
        from engine.nexus.impact_tracker import ImpactSeverity, _classify_severity
        # +20% on error_rate → effective = –20% → NEGATIVE_HIGH
        assert _classify_severity(20.0, "pipeline.error_rate") == ImpactSeverity.NEGATIVE_HIGH
