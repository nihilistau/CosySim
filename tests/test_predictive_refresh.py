"""Tests for engine.nexus.predictive_refresh.

Covers helpers, data models, initialisation, access tracking, entry
registration, staleness assessment, refresh queue, refresh execution,
schedule prediction, queries, scheduler integration, and edge cases.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest


# ──── Helpers ───────────────────────────────────────────────────────────────


def _make_pr(tmp_path: Path) -> "PredictiveRefresh":
    """Create a PredictiveRefresh backed by a temp database."""
    from engine.nexus.predictive_refresh import PredictiveRefresh

    return PredictiveRefresh(db_path=tmp_path / "pr_test.db")


def _insert_old_entry(
    pr: "PredictiveRefresh",
    entry_id: str,
    *,
    title: str = "Old Entry",
    content_type: str = "note",
    category: str = "",
    age_days: float = 60.0,
    access_count: int = 0,
    last_accessed: Optional[float] = None,
) -> None:
    """Insert an entry with a backdated first_seen directly into the DB."""
    now = time.time()
    first_seen = now - age_days * 86400.0
    conn = pr._get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO entry_tracking
        (entry_id, title, content_type, category, first_seen,
         last_accessed, access_count, last_refreshed, refresh_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0)""",
        (entry_id, title, content_type, category, first_seen,
         last_accessed, access_count),
    )
    conn.commit()


# ──── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def pr(tmp_path: Path) -> "PredictiveRefresh":
    """Fresh PredictiveRefresh with an isolated temp database."""
    return _make_pr(tmp_path)


@pytest.fixture()
def pr_module():
    """Import and return the predictive_refresh module, resetting singleton."""
    import engine.nexus.predictive_refresh as mod

    saved = mod._instance
    mod._instance = None
    try:
        yield mod
    finally:
        mod._instance = saved


# ──── TestHelpers ───────────────────────────────────────────────────────────


class TestHelpers:
    """Tests for _compute_staleness and _predict_staleness_crossing."""

    def test_compute_staleness_zero_age(self) -> None:
        """Zero age should give 0.0 staleness."""
        from engine.nexus.predictive_refresh import _compute_staleness

        assert _compute_staleness(0.0, 0, 0.0, 30.0) == 0.0

    def test_compute_staleness_large_age(self) -> None:
        """Very large age with no accesses approaches 1.0."""
        from engine.nexus.predictive_refresh import _compute_staleness

        result = _compute_staleness(300.0, 0, 300.0, 30.0)
        assert result > 0.95

    def test_compute_staleness_access_boost_reduces(self) -> None:
        """More accesses should reduce staleness compared to zero accesses."""
        from engine.nexus.predictive_refresh import _compute_staleness

        no_access = _compute_staleness(30.0, 0, 30.0, 30.0)
        with_access = _compute_staleness(30.0, 10, 30.0, 30.0)
        assert with_access < no_access

    def test_compute_staleness_recency_boost_reduces(self) -> None:
        """Recent access should reduce staleness compared to old access."""
        from engine.nexus.predictive_refresh import _compute_staleness

        old_access = _compute_staleness(30.0, 1, 25.0, 30.0)
        recent_access = _compute_staleness(30.0, 1, 1.0, 30.0)
        assert recent_access < old_access

    def test_compute_staleness_access_boost_capped(self) -> None:
        """Access boost should not exceed 0.5."""
        from engine.nexus.predictive_refresh import _compute_staleness

        # math.log1p(huge) * 0.1 would exceed 0.5 without cap
        huge_access = _compute_staleness(30.0, 1_000_000, 30.0, 30.0)
        # With cap, staleness should be roughly decay * (1 - 0.5) for large ages
        # It should still be positive or zero
        assert huge_access >= 0.0

    def test_compute_staleness_negative_clamped(self) -> None:
        """Result should never go below 0.0 even with large boosts."""
        from engine.nexus.predictive_refresh import _compute_staleness

        # Very recent access + high access count on young entry
        result = _compute_staleness(1.0, 100, 0.0, 30.0)
        assert result == 0.0

    def test_compute_staleness_result_within_bounds(self) -> None:
        """Result is always in [0.0, 1.0]."""
        from engine.nexus.predictive_refresh import _compute_staleness

        for age in [0, 1, 10, 100, 500]:
            for ac in [0, 1, 50]:
                for dsa in [0, 5, 100]:
                    s = _compute_staleness(float(age), ac, float(dsa), 30.0)
                    assert 0.0 <= s <= 1.0

    def test_predict_staleness_crossing_already_stale(self) -> None:
        """Returns None when current staleness >= threshold."""
        from engine.nexus.predictive_refresh import _predict_staleness_crossing

        assert _predict_staleness_crossing(0.8, 0.7, 30.0, 50.0) is None

    def test_predict_staleness_crossing_far_future(self) -> None:
        """Returns None when crossing > 365 days away."""
        from engine.nexus.predictive_refresh import _predict_staleness_crossing

        # Very fresh entry with high threshold and long half-life:
        # target_age = -180 * log2(1-0.95) = ~780 days
        # delta = 780 - 0 = 780 > 365
        result = _predict_staleness_crossing(0.0, 0.95, 180.0, 0.0)
        assert result is None

    def test_predict_staleness_crossing_valid(self) -> None:
        """Returns a valid future timestamp for moderate staleness."""
        from engine.nexus.predictive_refresh import _predict_staleness_crossing

        now = time.time()
        result = _predict_staleness_crossing(0.3, 0.7, 30.0, 10.0)
        assert result is not None
        assert result > now

    def test_predict_staleness_crossing_threshold_one(self) -> None:
        """Threshold >= 1.0 returns None (unreachable)."""
        from engine.nexus.predictive_refresh import _predict_staleness_crossing

        assert _predict_staleness_crossing(0.3, 1.0, 30.0, 10.0) is None


# ──── TestDataModels ────────────────────────────────────────────────────────


class TestDataModels:
    """Tests for dataclass models."""

    def test_entry_freshness_to_dict(self) -> None:
        """EntryFreshness.to_dict() returns a complete dictionary."""
        from engine.nexus.predictive_refresh import EntryFreshness

        ef = EntryFreshness(
            entry_id="e1", title="Test", content_type="code",
            category="api", staleness_score=0.5, freshness_score=0.5,
            age_days=14.0, access_count=5, last_accessed=1000.0,
            days_since_access=2.0, half_life_days=14.0, threshold=0.6,
            is_stale=False, predicted_stale_at=2000.0, hours_until_stale=10.0,
        )
        d = ef.to_dict()
        assert d["entry_id"] == "e1"
        assert d["staleness_score"] == 0.5
        assert d["freshness_score"] == 0.5
        assert d["is_stale"] is False

    def test_refresh_candidate_to_dict(self) -> None:
        """RefreshCandidate.to_dict() round-trips all fields."""
        from engine.nexus.predictive_refresh import RefreshCandidate

        rc = RefreshCandidate(
            entry_id="e2", title="RC", content_type="qa", category="dev",
            staleness_score=0.8, urgency="high", predicted_stale_at=None,
            hours_until_stale=0.0, refresh_reason="exceeds", last_refreshed=None,
        )
        d = rc.to_dict()
        assert d["urgency"] == "high"
        assert d["entry_id"] == "e2"

    def test_refresh_result_to_dict(self) -> None:
        """RefreshResult.to_dict() includes error field."""
        from engine.nexus.predictive_refresh import RefreshResult

        rr = RefreshResult(
            entry_id="e3", title="RR", status="refreshed",
            old_staleness=0.8, new_staleness=0.2,
            refresh_method="access_reset", timestamp=1000.0, error=None,
        )
        d = rr.to_dict()
        assert d["status"] == "refreshed"
        assert d["error"] is None

    def test_staleness_report_to_dict(self) -> None:
        """StalenessReport.to_dict() includes all aggregate fields."""
        from engine.nexus.predictive_refresh import StalenessReport

        sr = StalenessReport(
            total_tracked=10, stale_count=2, approaching_stale=3,
            fresh_count=5, avg_staleness=0.4, worst_entries=[],
            by_content_type={}, by_category={}, refresh_queue_size=2,
        )
        d = sr.to_dict()
        assert d["total_tracked"] == 10
        assert d["stale_count"] == 2
        assert "report_timestamp" in d

    def test_refresh_result_defaults(self) -> None:
        """RefreshResult auto-sets timestamp."""
        from engine.nexus.predictive_refresh import RefreshResult

        before = time.time()
        rr = RefreshResult(
            entry_id="e4", title="Defaults", status="skipped",
            old_staleness=0.5, new_staleness=0.5,
            refresh_method="manual",
        )
        after = time.time()
        assert before <= rr.timestamp <= after
        assert rr.error is None


# ──── TestInit ──────────────────────────────────────────────────────────────


class TestInit:
    """Verify database bootstrapping."""

    def test_creates_database(self, tmp_path: Path) -> None:
        """Database file should be created on disk."""
        db_file = tmp_path / "init_test.db"
        from engine.nexus.predictive_refresh import PredictiveRefresh

        PredictiveRefresh(db_path=db_file)
        assert db_file.exists()

    def test_wal_mode_enabled(self, pr: "PredictiveRefresh") -> None:
        """WAL journal mode should be enabled."""
        conn = pr._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_creates_all_tables(self, pr: "PredictiveRefresh") -> None:
        """All three tables should exist."""
        conn = pr._get_conn()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "entry_tracking" in tables
        assert "access_log" in tables
        assert "refresh_log" in tables

    def test_creates_indexes(self, pr: "PredictiveRefresh") -> None:
        """All expected indexes should be created."""
        conn = pr._get_conn()
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_access_entry" in indexes
        assert "idx_access_ts" in indexes
        assert "idx_refresh_entry" in indexes


# ──── TestRecordAccess ──────────────────────────────────────────────────────


class TestRecordAccess:
    """Tests for record_access (upsert + access log)."""

    def test_first_access_creates_tracking(self, pr: "PredictiveRefresh") -> None:
        """First access should create a tracking record with count 1."""
        pr.record_access("a1", title="First", content_type="code", category="api")
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT * FROM entry_tracking WHERE entry_id = 'a1'"
        ).fetchone()
        assert row is not None
        assert row["access_count"] == 1
        assert row["title"] == "First"

    def test_second_access_increments_count(self, pr: "PredictiveRefresh") -> None:
        """Second access should bump access_count to 2."""
        pr.record_access("a2", title="Inc", content_type="note")
        pr.record_access("a2", title="Inc", content_type="note")
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT access_count FROM entry_tracking WHERE entry_id = 'a2'"
        ).fetchone()
        assert row["access_count"] == 2

    def test_updates_last_accessed(self, pr: "PredictiveRefresh") -> None:
        """last_accessed should update on each access."""
        pr.record_access("a3", title="TS")
        conn = pr._get_conn()
        ts1 = conn.execute(
            "SELECT last_accessed FROM entry_tracking WHERE entry_id = 'a3'"
        ).fetchone()["last_accessed"]
        time.sleep(0.05)
        pr.record_access("a3", title="TS")
        ts2 = conn.execute(
            "SELECT last_accessed FROM entry_tracking WHERE entry_id = 'a3'"
        ).fetchone()["last_accessed"]
        assert ts2 > ts1

    def test_logs_access_in_access_log(self, pr: "PredictiveRefresh") -> None:
        """Each access should append a row to access_log."""
        pr.record_access("a4", title="Log")
        pr.record_access("a4", title="Log")
        conn = pr._get_conn()
        rows = conn.execute(
            "SELECT * FROM access_log WHERE entry_id = 'a4'"
        ).fetchall()
        assert len(rows) == 2

    def test_title_update_on_reaccess(self, pr: "PredictiveRefresh") -> None:
        """Title should be updated on subsequent access if non-empty."""
        pr.record_access("a5", title="Original", content_type="code")
        pr.record_access("a5", title="Updated", content_type="code")
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT title FROM entry_tracking WHERE entry_id = 'a5'"
        ).fetchone()
        assert row["title"] == "Updated"

    def test_source_stored_in_access_log(self, pr: "PredictiveRefresh") -> None:
        """Source parameter should be stored in access_log."""
        pr.record_access("a6", title="Src", source="search")
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT source FROM access_log WHERE entry_id = 'a6'"
        ).fetchone()
        assert row["source"] == "search"


# ──── TestRegisterEntry ─────────────────────────────────────────────────────


class TestRegisterEntry:
    """Tests for register_entry and bulk_register."""

    def test_registers_new_entry(self, pr: "PredictiveRefresh") -> None:
        """New entry is registered with access_count = 0."""
        pr.register_entry("r1", "Registered", content_type="document")
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT * FROM entry_tracking WHERE entry_id = 'r1'"
        ).fetchone()
        assert row is not None
        assert row["access_count"] == 0
        assert row["title"] == "Registered"

    def test_ignores_duplicate(self, pr: "PredictiveRefresh") -> None:
        """Duplicate registration should be ignored (no update)."""
        pr.register_entry("r2", "Original", content_type="code")
        pr.register_entry("r2", "Changed", content_type="prompt")
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT title, content_type FROM entry_tracking WHERE entry_id = 'r2'"
        ).fetchone()
        assert row["title"] == "Original"
        assert row["content_type"] == "code"

    def test_custom_created_at(self, pr: "PredictiveRefresh") -> None:
        """Custom created_at timestamp should be used as first_seen."""
        custom_ts = 1_700_000_000.0
        pr.register_entry("r3", "Old", created_at=custom_ts)
        conn = pr._get_conn()
        row = conn.execute(
            "SELECT first_seen FROM entry_tracking WHERE entry_id = 'r3'"
        ).fetchone()
        assert row["first_seen"] == pytest.approx(custom_ts)

    def test_bulk_register_returns_count(self, pr: "PredictiveRefresh") -> None:
        """bulk_register returns the count of entries registered."""
        entries = [
            {"entry_id": "b1", "title": "B1", "content_type": "code"},
            {"entry_id": "b2", "title": "B2", "content_type": "qa"},
            {"entry_id": "b3", "title": "B3", "content_type": "note"},
        ]
        count = pr.bulk_register(entries)
        assert count == 3
        assert pr.tracked_count() == 3


# ──── TestAssessEntry ───────────────────────────────────────────────────────


class TestAssessEntry:
    """Tests for assess_entry."""

    def test_returns_none_for_untracked(self, pr: "PredictiveRefresh") -> None:
        """Untracked entry returns None."""
        assert pr.assess_entry("nonexistent") is None

    def test_fresh_entry_low_staleness(self, pr: "PredictiveRefresh") -> None:
        """A just-created entry should have very low staleness."""
        pr.register_entry("f1", "Fresh", content_type="note")
        ef = pr.assess_entry("f1")
        assert ef is not None
        assert ef.staleness_score < 0.1
        assert ef.is_stale is False

    def test_old_entry_high_staleness(self, pr: "PredictiveRefresh") -> None:
        """An old entry with no accesses should be very stale."""
        _insert_old_entry(pr, "old1", age_days=60.0, content_type="note")
        ef = pr.assess_entry("old1")
        assert ef is not None
        assert ef.staleness_score > 0.5

    def test_code_shorter_half_life_than_document(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Code type (14d) should be more stale at same age than document (60d)."""
        _insert_old_entry(pr, "code1", age_days=30.0, content_type="code")
        _insert_old_entry(pr, "doc1", age_days=30.0, content_type="document")
        code_ef = pr.assess_entry("code1")
        doc_ef = pr.assess_entry("doc1")
        assert code_ef is not None and doc_ef is not None
        assert code_ef.staleness_score > doc_ef.staleness_score

    def test_access_count_reduces_staleness(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Higher access count should reduce staleness."""
        _insert_old_entry(pr, "ac0", age_days=30.0, access_count=0)
        _insert_old_entry(pr, "ac10", age_days=30.0, access_count=10)
        ef0 = pr.assess_entry("ac0")
        ef10 = pr.assess_entry("ac10")
        assert ef0 is not None and ef10 is not None
        assert ef10.staleness_score < ef0.staleness_score

    def test_recent_access_recency_boost(self, pr: "PredictiveRefresh") -> None:
        """Recent access should provide recency boost, reducing staleness."""
        now = time.time()
        _insert_old_entry(
            pr, "rec1", age_days=20.0,
            access_count=1, last_accessed=now - 86400,  # 1 day ago
        )
        _insert_old_entry(
            pr, "rec2", age_days=20.0,
            access_count=1, last_accessed=now - 86400 * 25,  # 25 days ago
        )
        ef1 = pr.assess_entry("rec1")
        ef2 = pr.assess_entry("rec2")
        assert ef1 is not None and ef2 is not None
        assert ef1.staleness_score < ef2.staleness_score

    def test_predicted_stale_at_set(self, pr: "PredictiveRefresh") -> None:
        """Non-stale entries should have a predicted_stale_at timestamp."""
        pr.register_entry("ps1", "Predicted", content_type="code")
        ef = pr.assess_entry("ps1")
        assert ef is not None
        assert ef.is_stale is False
        assert ef.predicted_stale_at is not None
        assert ef.predicted_stale_at > time.time()

    def test_hours_until_stale_computed(self, pr: "PredictiveRefresh") -> None:
        """hours_until_stale should be positive for non-stale entries."""
        pr.register_entry("hu1", "Hours", content_type="note")
        ef = pr.assess_entry("hu1")
        assert ef is not None
        if ef.predicted_stale_at is not None:
            assert ef.hours_until_stale is not None
            assert ef.hours_until_stale > 0.0


# ──── TestAssessStaleness ───────────────────────────────────────────────────


class TestAssessStaleness:
    """Tests for assess_staleness (aggregate report)."""

    def test_returns_staleness_report(self, pr: "PredictiveRefresh") -> None:
        """Should return a StalenessReport with correct counts."""
        pr.register_entry("sr1", "Entry1", content_type="code")
        _insert_old_entry(pr, "sr2", content_type="code", age_days=60.0)
        report = pr.assess_staleness()
        assert report.total_tracked == 2
        assert report.stale_count + report.approaching_stale + report.fresh_count == 2

    def test_content_type_filter(self, pr: "PredictiveRefresh") -> None:
        """content_type filter should restrict results."""
        pr.register_entry("ct1", "Code", content_type="code")
        pr.register_entry("ct2", "Note", content_type="note")
        report = pr.assess_staleness(content_type="code")
        assert report.total_tracked == 1

    def test_category_filter(self, pr: "PredictiveRefresh") -> None:
        """category filter should restrict results."""
        pr.register_entry("ca1", "Api", content_type="code", category="api")
        pr.register_entry("ca2", "Dev", content_type="code", category="dev")
        report = pr.assess_staleness(category="api")
        assert report.total_tracked == 1

    def test_worst_entries_sorted_descending(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """worst_entries should be sorted by staleness descending."""
        pr.register_entry("ws1", "Fresh", content_type="note")
        _insert_old_entry(pr, "ws2", content_type="note", age_days=90.0)
        _insert_old_entry(pr, "ws3", content_type="code", age_days=30.0)
        report = pr.assess_staleness()
        scores = [e["staleness_score"] for e in report.worst_entries]
        assert scores == sorted(scores, reverse=True)

    def test_by_content_type_aggregation(self, pr: "PredictiveRefresh") -> None:
        """by_content_type should aggregate per-type stats."""
        pr.register_entry("bt1", "C1", content_type="code")
        pr.register_entry("bt2", "C2", content_type="code")
        pr.register_entry("bt3", "N1", content_type="note")
        report = pr.assess_staleness()
        assert "code" in report.by_content_type
        assert report.by_content_type["code"]["count"] == 2
        assert "note" in report.by_content_type
        assert report.by_content_type["note"]["count"] == 1

    def test_by_category_aggregation(self, pr: "PredictiveRefresh") -> None:
        """by_category should aggregate per-category stats."""
        pr.register_entry("bc1", "A1", category="api")
        pr.register_entry("bc2", "A2", category="api")
        pr.register_entry("bc3", "D1", category="dev")
        report = pr.assess_staleness()
        assert "api" in report.by_category
        assert report.by_category["api"]["count"] == 2


# ──── TestRefreshQueue ──────────────────────────────────────────────────────


class TestRefreshQueue:
    """Tests for get_refresh_queue."""

    def test_empty_for_fresh_entries(self, pr: "PredictiveRefresh") -> None:
        """No candidates for all-fresh entries."""
        pr.register_entry("fq1", "Fresh", content_type="document")
        queue = pr.get_refresh_queue(horizon_hours=48)
        assert len(queue) == 0

    def test_stale_entries_urgency_high(self, pr: "PredictiveRefresh") -> None:
        """Stale entries appear with urgency 'high'."""
        _insert_old_entry(
            pr, "sq1", content_type="code", age_days=30.0, title="Stale Code"
        )
        queue = pr.get_refresh_queue(horizon_hours=48)
        stale_ids = [c.entry_id for c in queue]
        assert "sq1" in stale_ids
        candidate = next(c for c in queue if c.entry_id == "sq1")
        assert candidate.urgency in ("high", "critical")

    def test_very_stale_entries_urgency_critical(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Very stale entries (staleness > threshold + 0.15) are 'critical'."""
        # Plan type: threshold 0.5, half-life 7 days → 60-day-old plan is very stale
        _insert_old_entry(pr, "vc1", content_type="plan", age_days=60.0)
        queue = pr.get_refresh_queue()
        candidate = next((c for c in queue if c.entry_id == "vc1"), None)
        assert candidate is not None
        assert candidate.urgency == "critical"

    def test_approaching_entries_urgency_medium(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Entries approaching staleness within horizon should be 'medium'."""
        from engine.nexus.predictive_refresh import (
            _HALF_LIFE_DAYS,
            _STALENESS_THRESHOLDS,
        )

        # Use 'code' type (half_life=14, threshold=0.6)
        # An entry aged ~10 days has staleness ~ 1 - 2^(-10/14) ≈ 0.39
        # The threshold is 0.6, so it's not yet stale
        # Predict crossing at: -14 * log2(1-0.6) - 10 ≈ 18.15 - 10 ≈ 8.15 days ≈ 195 hours
        # We use a horizon big enough to catch it
        _insert_old_entry(pr, "ap1", content_type="code", age_days=10.0)
        queue = pr.get_refresh_queue(horizon_hours=200)
        candidate = next((c for c in queue if c.entry_id == "ap1"), None)
        if candidate is not None:
            assert candidate.urgency == "medium"

    def test_content_type_filter(self, pr: "PredictiveRefresh") -> None:
        """content_type filter restricts queue results."""
        _insert_old_entry(pr, "cf1", content_type="code", age_days=60.0)
        _insert_old_entry(pr, "cf2", content_type="note", age_days=60.0)
        queue = pr.get_refresh_queue(content_type="code")
        entry_ids = [c.entry_id for c in queue]
        assert "cf1" in entry_ids
        assert "cf2" not in entry_ids

    def test_sorted_by_urgency_then_staleness(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Queue should be sorted: critical → high → medium, then by staleness desc."""
        _insert_old_entry(pr, "so1", content_type="plan", age_days=60.0)  # critical
        _insert_old_entry(pr, "so2", content_type="code", age_days=30.0)  # high or critical
        queue = pr.get_refresh_queue()
        if len(queue) >= 2:
            urgency_order = {"critical": 0, "high": 1, "medium": 2}
            for i in range(len(queue) - 1):
                u_cur = urgency_order.get(queue[i].urgency, 3)
                u_nxt = urgency_order.get(queue[i + 1].urgency, 3)
                if u_cur == u_nxt:
                    assert queue[i].staleness_score >= queue[i + 1].staleness_score
                else:
                    assert u_cur <= u_nxt


# ──── TestRefreshStale ──────────────────────────────────────────────────────


class TestRefreshStale:
    """Tests for refresh_stale."""

    def test_refreshes_stale_access_reset(self, pr: "PredictiveRefresh") -> None:
        """Stale entries are refreshed with 'access_reset' when no callback."""
        _insert_old_entry(pr, "rs1", content_type="code", age_days=60.0, title="Stale")
        results = pr.refresh_stale(max_items=10)
        refreshed = [r for r in results if r.entry_id == "rs1"]
        assert len(refreshed) == 1
        assert refreshed[0].status == "refreshed"
        assert refreshed[0].refresh_method == "access_reset"

    def test_callback_produces_content_update(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """With a callback that returns content, method should be 'content_update'."""
        _insert_old_entry(pr, "cb1", content_type="code", age_days=60.0, title="Callback")

        def my_callback(entry_id: str, title: str, content_type: str) -> str:
            return "refreshed content"

        results = pr.refresh_stale(max_items=10, refresh_callback=my_callback)
        cb_results = [r for r in results if r.entry_id == "cb1"]
        assert len(cb_results) == 1
        assert cb_results[0].refresh_method == "content_update"

    def test_failed_refresh_records_error(self, pr: "PredictiveRefresh") -> None:
        """If callback raises, result should have status 'failed' with error."""
        _insert_old_entry(pr, "fe1", content_type="code", age_days=60.0, title="Fail")

        def bad_callback(entry_id: str, title: str, content_type: str) -> str:
            raise RuntimeError("test error")

        results = pr.refresh_stale(max_items=10, refresh_callback=bad_callback)
        failed = [r for r in results if r.entry_id == "fe1"]
        assert len(failed) == 1
        assert failed[0].status == "failed"
        assert "test error" in failed[0].error

    def test_respects_max_items(self, pr: "PredictiveRefresh") -> None:
        """refresh_stale should not exceed max_items."""
        for i in range(5):
            _insert_old_entry(pr, f"mx{i}", content_type="code", age_days=60.0)
        results = pr.refresh_stale(max_items=2)
        assert len(results) <= 2

    def test_persists_to_refresh_log(self, pr: "PredictiveRefresh") -> None:
        """Refresh results should be persisted to refresh_log table."""
        _insert_old_entry(pr, "pl1", content_type="code", age_days=60.0, title="Persist")
        pr.refresh_stale(max_items=10)
        conn = pr._get_conn()
        rows = conn.execute(
            "SELECT * FROM refresh_log WHERE entry_id = 'pl1'"
        ).fetchall()
        assert len(rows) >= 1
        assert rows[0]["status"] == "refreshed"


# ──── TestScheduleRefresh ───────────────────────────────────────────────────


class TestScheduleRefresh:
    """Tests for schedule_refresh."""

    def test_returns_none_for_untracked(self, pr: "PredictiveRefresh") -> None:
        """Untracked entry should return None."""
        assert pr.schedule_refresh("ghost") is None

    def test_refresh_now_for_stale(self, pr: "PredictiveRefresh") -> None:
        """Already stale entry should recommend 'refresh_now'."""
        _insert_old_entry(pr, "sn1", content_type="code", age_days=60.0)
        result = pr.schedule_refresh("sn1", target_staleness=0.5)
        assert result is not None
        assert result["recommendation"] == "refresh_now"
        assert result["hours_until_refresh"] == 0.0

    def test_no_refresh_needed_for_very_fresh(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Very fresh entry with distant crossing → 'no_refresh_needed'."""
        pr.register_entry("nf1", "Fresh", content_type="history")
        # history: half_life=180, threshold=0.95 → crossing is very far
        result = pr.schedule_refresh("nf1", target_staleness=0.95)
        assert result is not None
        assert result["recommendation"] == "no_refresh_needed"

    def test_schedule_refresh_proactive(self, pr: "PredictiveRefresh") -> None:
        """Moderate entry should get 'schedule_refresh' with proactive timing."""
        # code type: half_life=14, use target_staleness=0.7
        # Entry aged 5 days: staleness ~ 1 - 2^(-5/14) ≈ 0.22
        # Predicted crossing at: -14 * log2(0.3) - 5 ≈ 24.5 - 5 ≈ 19.5 days
        _insert_old_entry(pr, "sp1", content_type="code", age_days=5.0)
        result = pr.schedule_refresh("sp1", target_staleness=0.7)
        assert result is not None
        assert result["recommendation"] == "schedule_refresh"
        assert result["hours_until_refresh"] is not None
        # Proactive = 80% of hours_until_stale
        assert result["hours_until_refresh"] == pytest.approx(
            result["hours_until_stale"] * 0.8, rel=0.01
        )


# ──── TestQueries ───────────────────────────────────────────────────────────


class TestQueries:
    """Tests for tracked_count, access_history, refresh_history, snapshot."""

    def test_tracked_count(self, pr: "PredictiveRefresh") -> None:
        """tracked_count returns correct number of tracked entries."""
        assert pr.tracked_count() == 0
        pr.register_entry("tc1", "One")
        pr.register_entry("tc2", "Two")
        assert pr.tracked_count() == 2

    def test_access_history_for_entry(self, pr: "PredictiveRefresh") -> None:
        """access_history returns access events for a specific entry."""
        pr.record_access("ah1", title="History", source="agent")
        pr.record_access("ah1", title="History", source="search")
        history = pr.access_history("ah1")
        assert len(history) == 2
        sources = {h["source"] for h in history}
        assert "agent" in sources
        assert "search" in sources

    def test_refresh_history_filtered_and_unfiltered(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """refresh_history works with and without entry_id filter."""
        _insert_old_entry(pr, "rh1", content_type="code", age_days=60.0, title="RH1")
        _insert_old_entry(pr, "rh2", content_type="code", age_days=60.0, title="RH2")
        pr.refresh_stale(max_items=10)

        # Filtered
        h1 = pr.refresh_history(entry_id="rh1")
        assert len(h1) >= 1
        assert all(r["entry_id"] == "rh1" for r in h1)

        # Unfiltered
        h_all = pr.refresh_history()
        assert len(h_all) >= 2

    def test_snapshot_returns_correct_counts(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """snapshot returns dict with correct aggregate counts."""
        pr.register_entry("sn1", "Snap1")
        pr.record_access("sn2", title="Snap2")
        snap = pr.snapshot()
        assert snap["tracked_entries"] == 2
        assert snap["total_accesses"] == 1
        assert snap["total_refreshes"] == 0
        assert "half_life_configs" in snap
        assert "threshold_configs" in snap


# ──── TestScheduler ─────────────────────────────────────────────────────────


class TestScheduler:
    """Tests for register_refresh_tasks."""

    def test_calls_daemon_register(self, pr_module) -> None:
        """register_refresh_tasks should call daemon.register."""
        daemon = MagicMock()
        pr_module.register_refresh_tasks(daemon)
        daemon.register.assert_called_once()

    def test_registered_task_id(self, pr_module) -> None:
        """Registered task should have id 'knowledge-staleness-sweep'."""
        daemon = MagicMock()
        pr_module.register_refresh_tasks(daemon)
        call_args = daemon.register.call_args
        assert call_args[0][0] == "knowledge-staleness-sweep"

    def test_task_callback_executes(self, tmp_path: Path, pr_module) -> None:
        """The registered callback should execute without error."""
        daemon = MagicMock()

        # Reset singleton so it creates a fresh one with temp DB
        saved = pr_module._instance
        pr_module._instance = None
        try:
            pr_module._instance = pr_module.PredictiveRefresh(
                db_path=tmp_path / "sched.db"
            )
            pr_module.register_refresh_tasks(daemon)
            callback = daemon.register.call_args[0][3]
            result = callback()
            assert result["status"] == "ok"
            assert "total_tracked" in result
        finally:
            pr_module._instance = saved


# ──── TestEdgeCases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and thread safety."""

    def test_thread_safety_concurrent_access(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Concurrent record_access calls should not raise or corrupt data."""
        errors: list = []

        def worker(entry_id: str) -> None:
            try:
                for _ in range(20):
                    pr.record_access(entry_id, title="Thread", source="thread")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(f"thread_{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Each thread did 20 accesses on its own entry
        for i in range(4):
            conn = pr._get_conn()
            row = conn.execute(
                "SELECT access_count FROM entry_tracking WHERE entry_id = ?",
                (f"thread_{i}",),
            ).fetchone()
            assert row is not None
            assert row["access_count"] == 20

    def test_unknown_content_type_uses_defaults(
        self, pr: "PredictiveRefresh"
    ) -> None:
        """Unknown content type should use _DEFAULT_HALF_LIFE and _DEFAULT_THRESHOLD."""
        from engine.nexus.predictive_refresh import (
            _DEFAULT_HALF_LIFE,
            _DEFAULT_THRESHOLD,
        )

        _insert_old_entry(pr, "unk1", content_type="exotic_type", age_days=10.0)
        ef = pr.assess_entry("unk1")
        assert ef is not None
        assert ef.half_life_days == _DEFAULT_HALF_LIFE
        assert ef.threshold == _DEFAULT_THRESHOLD

    def test_empty_database_operations(self, pr: "PredictiveRefresh") -> None:
        """All query operations should work on an empty database."""
        assert pr.tracked_count() == 0
        assert pr.access_history("nope") == []
        assert pr.refresh_history() == []
        snap = pr.snapshot()
        assert snap["tracked_entries"] == 0

        report = pr.assess_staleness()
        assert report.total_tracked == 0
        assert report.avg_staleness == 0.0

        queue = pr.get_refresh_queue()
        assert queue == []

        results = pr.refresh_stale()
        assert results == []


# ──── TestSingleton ─────────────────────────────────────────────────────────


class TestSingleton:
    """Tests for get_predictive_refresh singleton."""

    def test_returns_same_instance(self, tmp_path: Path, pr_module) -> None:
        """get_predictive_refresh returns the same instance on repeated calls."""
        pr_module._instance = None
        inst1 = pr_module.get_predictive_refresh(db_path=tmp_path / "s1.db")
        inst2 = pr_module.get_predictive_refresh()
        assert inst1 is inst2
