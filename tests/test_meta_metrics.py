"""Tests for engine.nexus.meta_metrics."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.meta_metrics import (
    MetaMetrics,
    MetricAlert,
    MetricPoint,
    get_meta_metrics,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def mm(tmp_path: Path) -> MetaMetrics:
    """Fresh MetaMetrics instance backed by a temporary database."""
    return MetaMetrics(db_path=tmp_path / "test_metrics.db")


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset the module-level singleton between tests."""
    import engine.nexus.meta_metrics as mod

    mod._metrics = None


# ── Record & get ────────────────────────────────────────────────────────


class TestRecordAndGet:
    """Tests for record() and get()."""

    def test_record_single(self, mm: MetaMetrics) -> None:
        """Record one metric and retrieve it."""
        mm.record("nexus.entries.total", 100.0)
        points = mm.get("nexus.entries.total", hours=1)

        assert len(points) == 1
        assert points[0].name == "nexus.entries.total"
        assert points[0].value == 100.0

    def test_record_with_tags(self, mm: MetaMetrics) -> None:
        """Tags are preserved round-trip."""
        mm.record("llm.calls.total", 42.0, tags={"source": "agent"})
        points = mm.get("llm.calls.total", hours=1)

        assert points[0].tags == {"source": "agent"}

    def test_get_empty(self, mm: MetaMetrics) -> None:
        """Querying a non-existent metric returns empty list."""
        assert mm.get("does.not.exist", hours=1) == []

    def test_get_respects_hours(self, mm: MetaMetrics) -> None:
        """Points outside the look-back window are excluded."""
        mm.record("nexus.entries.total", 10.0)
        # Insert an old point directly to simulate age
        with mm._cursor() as cur:
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("nexus.entries.total", 5.0, time.time() - 7200, "{}"),
            )
        points = mm.get("nexus.entries.total", hours=1)
        assert len(points) == 1
        assert points[0].value == 10.0

    def test_get_returns_metric_point_type(self, mm: MetaMetrics) -> None:
        """All items in get() are MetricPoint instances."""
        mm.record("tests.total", 500)
        points = mm.get("tests.total", hours=1)
        assert all(isinstance(p, MetricPoint) for p in points)

    def test_get_timestamp_is_utc(self, mm: MetaMetrics) -> None:
        """MetricPoint timestamps are UTC-aware datetimes."""
        mm.record("system.uptime_s", 60.0)
        points = mm.get("system.uptime_s", hours=1)
        assert points[0].timestamp.tzinfo == timezone.utc

    def test_record_multiple_same_name(self, mm: MetaMetrics) -> None:
        """Multiple recordings of the same metric are all stored."""
        for v in (1.0, 2.0, 3.0):
            mm.record("tests.passed", v)
        points = mm.get("tests.passed", hours=1)
        assert len(points) == 3
        values = [p.value for p in points]
        assert values == [1.0, 2.0, 3.0]


# ── Record batch ────────────────────────────────────────────────────────


class TestRecordBatch:
    """Tests for record_batch()."""

    def test_batch_returns_count(self, mm: MetaMetrics) -> None:
        """record_batch returns the number of metrics stored."""
        count = mm.record_batch([
            ("nexus.entries.total", 100),
            ("nexus.qa.total", 50),
        ])
        assert count == 2

    def test_batch_stores_all(self, mm: MetaMetrics) -> None:
        """All batch items are retrievable."""
        mm.record_batch([
            ("tests.total", 300),
            ("tests.passed", 295),
            ("tests.failed", 5),
        ])
        assert len(mm.get("tests.total", hours=1)) == 1
        assert len(mm.get("tests.passed", hours=1)) == 1
        assert len(mm.get("tests.failed", hours=1)) == 1

    def test_batch_empty(self, mm: MetaMetrics) -> None:
        """Empty batch records zero metrics."""
        assert mm.record_batch([]) == 0


# ── Trend ───────────────────────────────────────────────────────────────


class TestTrend:
    """Tests for trend()."""

    def test_trend_up(self, mm: MetaMetrics) -> None:
        """Trend detects upward movement."""
        now = time.time()
        with mm._cursor() as cur:
            for i, v in enumerate([10, 20, 30]):
                cur.execute(
                    "INSERT INTO metrics (name, value, ts, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("nexus.entries.total", v, now - 3600 + i * 60, "{}"),
                )
        t = mm.trend("nexus.entries.total", days=1)
        assert t["direction"] == "up"
        assert t["first"] == 10
        assert t["last"] == 30
        assert t["count"] == 3
        assert t["rate_of_change"] > 0

    def test_trend_down(self, mm: MetaMetrics) -> None:
        """Trend detects downward movement."""
        now = time.time()
        with mm._cursor() as cur:
            for i, v in enumerate([50, 40, 30]):
                cur.execute(
                    "INSERT INTO metrics (name, value, ts, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("tests.passed", v, now - 3600 + i * 60, "{}"),
                )
        t = mm.trend("tests.passed", days=1)
        assert t["direction"] == "down"
        assert t["rate_of_change"] < 0

    def test_trend_stable(self, mm: MetaMetrics) -> None:
        """Identical values yield stable direction."""
        now = time.time()
        with mm._cursor() as cur:
            for i in range(3):
                cur.execute(
                    "INSERT INTO metrics (name, value, ts, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("tests.total", 100, now - 3600 + i * 60, "{}"),
                )
        t = mm.trend("tests.total", days=1)
        assert t["direction"] == "stable"
        assert t["rate_of_change"] == 0.0

    def test_trend_empty(self, mm: MetaMetrics) -> None:
        """No data yields stable with zero values."""
        t = mm.trend("nonexistent", days=1)
        assert t["direction"] == "stable"
        assert t["count"] == 0

    def test_trend_min_max_avg(self, mm: MetaMetrics) -> None:
        """Min, max, avg are computed correctly."""
        now = time.time()
        with mm._cursor() as cur:
            for i, v in enumerate([10, 20, 30]):
                cur.execute(
                    "INSERT INTO metrics (name, value, ts, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("llm.latency.avg_ms", v, now - 3600 + i * 60, "{}"),
                )
        t = mm.trend("llm.latency.avg_ms", days=1)
        assert t["min"] == 10
        assert t["max"] == 30
        assert t["avg"] == 20.0


# ── Compare ─────────────────────────────────────────────────────────────


class TestCompare:
    """Tests for compare()."""

    def test_compare_improvement(self, mm: MetaMetrics) -> None:
        """Higher-is-better metric shows improved when current > baseline."""
        now = time.time()
        with mm._cursor() as cur:
            # Baseline period
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("nexus.entries.total", 100, now - 86400 * 3, "{}"),
            )
            # Current period
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("nexus.entries.total", 200, now - 3600, "{}"),
            )
        result = mm.compare("nexus.entries.total", current_hours=24, baseline_hours=168)
        assert result["current_avg"] == 200.0
        assert result["change_pct"] > 0
        assert result["improved"] is True

    def test_compare_no_data(self, mm: MetaMetrics) -> None:
        """No data returns zeroes."""
        result = mm.compare("nonexistent")
        assert result["current_avg"] == 0.0
        assert result["baseline_avg"] == 0.0
        assert result["change_pct"] == 0.0

    def test_compare_lower_is_better(self, mm: MetaMetrics) -> None:
        """For latency metrics, lower current is an improvement."""
        now = time.time()
        with mm._cursor() as cur:
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("llm.latency.avg_ms", 300, now - 86400 * 3, "{}"),
            )
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("llm.latency.avg_ms", 200, now - 3600, "{}"),
            )
        result = mm.compare("llm.latency.avg_ms", current_hours=24, baseline_hours=168)
        assert result["change_pct"] < 0
        assert result["improved"] is True


# ── Baselines & regressions ─────────────────────────────────────────────


class TestBaselines:
    """Tests for set_baseline, auto_baseline, and check_regressions."""

    def test_set_baseline(self, mm: MetaMetrics) -> None:
        """Baseline is stored and retrievable."""
        mm.set_baseline("tests.passed", 250.0)
        with mm._cursor() as cur:
            cur.execute(
                "SELECT value FROM baselines WHERE name = ?",
                ("tests.passed",),
            )
            row = cur.fetchone()
        assert row["value"] == 250.0

    def test_set_baseline_overwrite(self, mm: MetaMetrics) -> None:
        """Overwriting a baseline replaces the old value."""
        mm.set_baseline("tests.passed", 100.0)
        mm.set_baseline("tests.passed", 200.0)
        with mm._cursor() as cur:
            cur.execute(
                "SELECT value FROM baselines WHERE name = ?",
                ("tests.passed",),
            )
            assert cur.fetchone()["value"] == 200.0

    def test_auto_baseline(self, mm: MetaMetrics) -> None:
        """auto_baseline computes the average from recent points."""
        now = time.time()
        with mm._cursor() as cur:
            for v in [10, 20, 30]:
                cur.execute(
                    "INSERT INTO metrics (name, value, ts, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("tests.total", v, now - 3600, "{}"),
                )
        baseline = mm.auto_baseline("tests.total", days=7)
        assert baseline == 20.0

    def test_auto_baseline_no_data(self, mm: MetaMetrics) -> None:
        """auto_baseline with no data sets baseline to 0."""
        baseline = mm.auto_baseline("nonexistent", days=7)
        assert baseline == 0.0

    def test_regression_detected(self, mm: MetaMetrics) -> None:
        """A higher-is-better metric that drops fires a regression alert."""
        mm.set_baseline("tests.passed", 100.0)
        mm.record("tests.passed", 80.0)  # 20% drop
        alerts = mm.check_regressions(threshold_pct=10.0)
        assert len(alerts) == 1
        assert alerts[0].metric_name == "tests.passed"
        assert alerts[0].alert_type == "regression"
        assert "regressed" in alerts[0].message

    def test_regression_lower_is_better(self, mm: MetaMetrics) -> None:
        """A lower-is-better metric that increases fires a regression."""
        mm.set_baseline("llm.latency.avg_ms", 200.0)
        mm.record("llm.latency.avg_ms", 250.0)  # 25% increase
        alerts = mm.check_regressions(threshold_pct=10.0)
        assert len(alerts) == 1
        assert alerts[0].metric_name == "llm.latency.avg_ms"

    def test_no_regression(self, mm: MetaMetrics) -> None:
        """No alert when metric is within threshold."""
        mm.set_baseline("tests.passed", 100.0)
        mm.record("tests.passed", 95.0)  # only 5% drop
        alerts = mm.check_regressions(threshold_pct=10.0)
        assert len(alerts) == 0

    def test_regressions_stored_in_alerts_table(self, mm: MetaMetrics) -> None:
        """Detected regressions are persisted in the alerts table."""
        mm.set_baseline("tests.passed", 100.0)
        mm.record("tests.passed", 50.0)
        mm.check_regressions(threshold_pct=10.0)
        with mm._cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM alerts")
            assert cur.fetchone()["cnt"] == 1

    def test_check_regressions_no_baselines(self, mm: MetaMetrics) -> None:
        """No baselines → no alerts."""
        mm.record("tests.passed", 100)
        assert mm.check_regressions() == []


# ── Snapshot ────────────────────────────────────────────────────────────


class TestSnapshot:
    """Tests for snapshot()."""

    def test_snapshot_returns_latest(self, mm: MetaMetrics) -> None:
        """Snapshot returns the most recent value per metric."""
        mm.record("tests.total", 100)
        mm.record("tests.total", 200)
        mm.record("tests.passed", 195)

        snap = mm.snapshot()
        assert snap["tests.total"]["value"] == 200
        assert snap["tests.passed"]["value"] == 195

    def test_snapshot_empty(self, mm: MetaMetrics) -> None:
        """Empty DB yields empty snapshot."""
        assert mm.snapshot() == {}

    def test_snapshot_contains_timestamp(self, mm: MetaMetrics) -> None:
        """Each snapshot entry includes an ISO timestamp."""
        mm.record("system.uptime_s", 60)
        snap = mm.snapshot()
        assert "timestamp" in snap["system.uptime_s"]


# ── Dashboard ───────────────────────────────────────────────────────────


class TestDashboard:
    """Tests for dashboard()."""

    def test_dashboard_returns_markdown(self, mm: MetaMetrics) -> None:
        """Dashboard produces markdown with expected sections."""
        mm.record("nexus.entries.total", 523)
        mm.record("tests.passed", 3500)
        md = mm.dashboard(hours=24)
        assert "# System Dashboard" in md
        assert "## Knowledge" in md
        assert "## Inference" in md
        assert "## Tasks" in md
        assert "## Tests" in md
        assert "## System" in md
        assert "## Alerts" in md

    def test_dashboard_empty_db(self, mm: MetaMetrics) -> None:
        """Dashboard renders without error on empty DB."""
        md = mm.dashboard(hours=24)
        assert "# System Dashboard" in md

    def test_dashboard_shows_no_regressions(self, mm: MetaMetrics) -> None:
        """Dashboard shows clean status when there are no regressions."""
        md = mm.dashboard()
        assert "No regressions detected" in md

    def test_dashboard_shows_alerts(self, mm: MetaMetrics) -> None:
        """Dashboard includes regression alerts when present."""
        mm.set_baseline("tests.passed", 100.0)
        mm.record("tests.passed", 50.0)
        md = mm.dashboard()
        assert "⚠️" in md
        assert "regressed" in md


# ── Collect system metrics ──────────────────────────────────────────────


class TestCollectSystemMetrics:
    """Tests for collect_system_metrics()."""

    def test_uptime_present(self, mm: MetaMetrics) -> None:
        """System metrics include uptime."""
        result = mm.collect_system_metrics()
        assert "system.uptime_s" in result
        assert result["system.uptime_s"] >= 0

    @patch("engine.nexus.meta_metrics.subprocess.run")
    def test_vram_from_nvidia_smi(
        self, mock_run: MagicMock, mm: MetaMetrics
    ) -> None:
        """VRAM is parsed from nvidia-smi output."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="4096\n"
        )
        result = mm.collect_system_metrics()
        assert result["system.vram_used_mb"] == 4096.0

    @patch("engine.nexus.meta_metrics.subprocess.run")
    def test_vram_nvidia_smi_failure(
        self, mock_run: MagicMock, mm: MetaMetrics
    ) -> None:
        """VRAM defaults to 0 when nvidia-smi fails."""
        mock_run.side_effect = FileNotFoundError("not found")
        result = mm.collect_system_metrics()
        assert result["system.vram_used_mb"] == 0.0

    def test_nlm_defaults_to_zero(self, mm: MetaMetrics) -> None:
        """NLM metrics default to 0."""
        result = mm.collect_system_metrics()
        assert result["nlm.notebooks.active"] == 0.0
        assert result["nlm.research.sessions"] == 0.0


# ── Collect Nexus metrics ──────────────────────────────────────────────


class TestCollectNexusMetrics:
    """Tests for collect_nexus_metrics()."""

    def test_nexus_metrics_from_status(self, mm: MetaMetrics) -> None:
        """Nexus metrics are populated from client.status()."""
        mock_client = MagicMock()
        mock_client.status.return_value = {
            "total_entries": 500,
            "total_qa": 200,
            "cache_hits": 150,
            "avg_quality": 0.85,
        }
        with patch(
            "engine.nexus.client.get_nexus_client",
            return_value=mock_client,
        ):
            result = mm.collect_nexus_metrics()
        assert result["nexus.entries.total"] == 500.0
        assert result["nexus.qa.total"] == 200.0
        assert result["nexus.qa.cache_hits"] == 150.0
        assert result["nexus.quality.average"] == 0.85

    def test_nexus_metrics_fallback(self, mm: MetaMetrics) -> None:
        """Nexus unreachable → all metrics 0."""
        with patch.dict(
            "sys.modules",
            {"engine.nexus.client": MagicMock(
                get_nexus_client=MagicMock(side_effect=Exception("offline"))
            )},
        ):
            result = mm.collect_nexus_metrics()
        assert result["nexus.entries.total"] == 0.0
        assert result["nexus.qa.total"] == 0.0


# ── Collect all ─────────────────────────────────────────────────────────


class TestCollectAll:
    """Tests for collect_all()."""

    def test_collect_all_records_metrics(self, mm: MetaMetrics) -> None:
        """collect_all records metrics and returns them."""
        with patch.object(
            mm, "collect_system_metrics",
            return_value={"system.uptime_s": 120.0},
        ), patch.object(
            mm, "collect_nexus_metrics",
            return_value={"nexus.entries.total": 300.0},
        ):
            result = mm.collect_all()

        assert result["system.uptime_s"] == 120.0
        assert result["nexus.entries.total"] == 300.0
        # Verify they were recorded
        points = mm.get("system.uptime_s", hours=1)
        assert len(points) == 1
        assert points[0].value == 120.0


# ── Stats ───────────────────────────────────────────────────────────────


class TestStats:
    """Tests for stats()."""

    def test_stats_empty(self, mm: MetaMetrics) -> None:
        """Stats on empty DB show zeroes."""
        s = mm.stats()
        assert s["total_points"] == 0
        assert s["unique_metrics"] == 0
        assert s["date_range"]["first"] is None
        assert s["total_alerts"] == 0

    def test_stats_populated(self, mm: MetaMetrics) -> None:
        """Stats reflect recorded data."""
        mm.record("tests.total", 100)
        mm.record("tests.passed", 95)
        mm.record("tests.total", 101)
        s = mm.stats()
        assert s["total_points"] == 3
        assert s["unique_metrics"] == 2
        assert s["date_range"]["first"] is not None
        assert s["date_range"]["last"] is not None


# ── Singleton ───────────────────────────────────────────────────────────


class TestSingleton:
    """Tests for get_meta_metrics singleton."""

    def test_singleton_returns_same_instance(self, tmp_path: Path) -> None:
        """Multiple calls return the same instance."""
        db = tmp_path / "singleton.db"
        a = get_meta_metrics(db_path=db)
        b = get_meta_metrics(db_path=db)
        assert a is b

    def test_singleton_is_usable(self, tmp_path: Path) -> None:
        """Singleton can record and retrieve metrics."""
        db = tmp_path / "singleton2.db"
        mm = get_meta_metrics(db_path=db)
        mm.record("tests.total", 42)
        points = mm.get("tests.total", hours=1)
        assert len(points) == 1


# ── Data classes ────────────────────────────────────────────────────────


class TestDataClasses:
    """Tests for MetricPoint and MetricAlert data classes."""

    def test_metric_point_fields(self) -> None:
        """MetricPoint stores all expected fields."""
        mp = MetricPoint(
            name="tests.total",
            value=100.0,
            timestamp=datetime.now(tz=timezone.utc),
            tags={"period": "daily"},
        )
        assert mp.name == "tests.total"
        assert mp.value == 100.0
        assert mp.tags == {"period": "daily"}

    def test_metric_alert_fields(self) -> None:
        """MetricAlert stores all expected fields."""
        ma = MetricAlert(
            metric_name="llm.latency.avg_ms",
            alert_type="regression",
            message="latency regressed",
            current_value=250.0,
            baseline_value=200.0,
            threshold_pct=10.0,
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert ma.alert_type == "regression"
        assert ma.current_value == 250.0

    def test_metric_point_default_tags(self) -> None:
        """MetricPoint defaults to empty tags dict."""
        mp = MetricPoint(
            name="x", value=1.0,
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert mp.tags == {}


# ── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_trend_zero_first_value(self, mm: MetaMetrics) -> None:
        """Trend handles first_val == 0 gracefully."""
        now = time.time()
        with mm._cursor() as cur:
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("tasks.created", 0, now - 3600, "{}"),
            )
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                ("tasks.created", 5, now - 1800, "{}"),
            )
        t = mm.trend("tasks.created", days=1)
        assert t["direction"] == "up"
        assert t["rate_of_change"] == 1.0

    def test_trend_zero_to_zero(self, mm: MetaMetrics) -> None:
        """Trend with all-zero values is stable."""
        now = time.time()
        with mm._cursor() as cur:
            for i in range(3):
                cur.execute(
                    "INSERT INTO metrics (name, value, ts, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    ("tasks.failed", 0, now - 3600 + i * 60, "{}"),
                )
        t = mm.trend("tasks.failed", days=1)
        assert t["direction"] == "stable"
        assert t["rate_of_change"] == 0.0

    def test_regression_zero_baseline_skipped(self, mm: MetaMetrics) -> None:
        """Zero baseline avoids division by zero."""
        mm.set_baseline("tasks.failed", 0.0)
        mm.record("tasks.failed", 5.0)
        alerts = mm.check_regressions(threshold_pct=10.0)
        assert len(alerts) == 0

    def test_record_negative_value(self, mm: MetaMetrics) -> None:
        """Negative metric values are stored correctly."""
        mm.record("tests.failed", -1.0)
        points = mm.get("tests.failed", hours=1)
        assert points[0].value == -1.0

    def test_concurrent_db_path_creation(self, tmp_path: Path) -> None:
        """MetaMetrics creates parent directories as needed."""
        deep = tmp_path / "a" / "b" / "c" / "metrics.db"
        mm = MetaMetrics(db_path=deep)
        mm.record("tests.total", 1)
        assert len(mm.get("tests.total", hours=1)) == 1

    def test_latest_value_helper(self, mm: MetaMetrics) -> None:
        """_latest_value returns last recorded value."""
        mm.record("tests.total", 10)
        mm.record("tests.total", 20)
        assert mm._latest_value("tests.total") == 20.0

    def test_latest_value_missing(self, mm: MetaMetrics) -> None:
        """_latest_value returns 0 for unknown metric."""
        assert mm._latest_value("nonexistent") == 0.0
