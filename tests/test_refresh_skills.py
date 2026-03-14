"""Tests for engine.skills.builtin.refresh_skills — MCP knowledge refresh skills."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

PATCH_PR = "engine.skills.builtin.refresh_skills._get_pr"


# ──── Helpers ──────────────────────────────────────────────────────────────


class TestHelpers:
    """Tests for module-level helper functions."""

    def test_pct_formats_float_as_percentage(self) -> None:
        """_pct converts a float to a rounded percentage string."""
        from engine.skills.builtin.refresh_skills import _pct

        assert _pct(0.453) == "45.3%"
        assert _pct(0.0) == "0.0%"
        assert _pct(1.0) == "100.0%"
        assert _pct(0.999) == "99.9%"

    def test_bar_produces_correct_length_and_fill(self) -> None:
        """_bar returns a bar of the requested width with correct fill ratio."""
        from engine.skills.builtin.refresh_skills import _bar

        bar_full = _bar(1.0, width=10)
        assert bar_full == "██████████"
        assert len(bar_full) == 10

        bar_empty = _bar(0.0, width=10)
        assert bar_empty == "░" * 10
        assert bar_empty.count("█") == 0

        bar_half = _bar(0.5, width=20)
        assert bar_half.count("█") == 10
        assert bar_half.count("░") == 10
        assert len(bar_half) == 20

        # Clamp above 1.0
        assert _bar(1.5, width=5) == "█████"
        # Clamp below 0.0
        assert _bar(-0.3, width=5) == "░░░░░"

    def test_ts_formats_utc_timestamp(self) -> None:
        """_ts converts an epoch float to a human-readable UTC string."""
        from engine.skills.builtin.refresh_skills import _ts

        # 0.0 is falsy so _ts falls back to time.time(); use a positive epoch
        result = _ts(1.0)
        assert result == "1970-01-01 00:00:01 UTC"

        result = _ts(1_700_000_000.0)
        assert "UTC" in result
        assert "2023" in result

        # None triggers time.time() fallback — just verify format
        result = _ts(None)
        assert result.endswith("UTC")
        assert len(result) == len("YYYY-MM-DD HH:MM:SS UTC")


# ──── Staleness Report ─────────────────────────────────────────────────────


def _make_report(
    by_content_type: dict | None = None,
    by_category: dict | None = None,
    worst_entries: list | None = None,
) -> MagicMock:
    """Build a mock staleness report with sane defaults."""
    report = MagicMock()
    report.total_tracked = 50
    report.stale_count = 5
    report.approaching_stale = 10
    report.fresh_count = 35
    report.avg_staleness = 0.35
    report.refresh_queue_size = 8
    report.by_content_type = by_content_type if by_content_type is not None else {}
    report.by_category = by_category if by_category is not None else {}
    report.worst_entries = worst_entries if worst_entries is not None else []
    return report


class TestStalenessReport:
    """Tests for knowledge_staleness_report skill."""

    @patch(PATCH_PR)
    def test_full_report_includes_all_sections(self, mock_pr: MagicMock) -> None:
        """A report with all data sections populated includes every section."""
        from engine.skills.builtin.refresh_skills import knowledge_staleness_report

        report = _make_report(
            by_content_type={"code": {"count": 20, "stale": 3, "avg_staleness": 0.45}},
            by_category={"api": {"count": 15, "stale": 2, "avg_staleness": 0.40}},
            worst_entries=[
                {"title": "Old API doc", "staleness_score": 0.95, "content_type": "document", "age_days": 90},
            ],
        )
        mock_pr.return_value.assess_staleness.return_value = report

        result = knowledge_staleness_report()

        assert "Knowledge Staleness Report" in result
        assert "Total tracked: 50" in result
        assert "Stale: 5" in result
        assert "Approaching stale: 10" in result
        assert "Fresh: 35" in result
        assert "35.0%" in result  # avg staleness
        assert "Refresh queue: 8 items" in result
        # By content type section
        assert "By content type:" in result
        assert "code:" in result
        # By category section
        assert "By category:" in result
        assert "api:" in result
        # Worst entries section
        assert "Worst entries" in result
        assert "Old API doc" in result
        assert "95.0%" in result

    @patch(PATCH_PR)
    def test_empty_content_type_section_is_skipped(self, mock_pr: MagicMock) -> None:
        """When by_content_type is empty, its section is omitted."""
        from engine.skills.builtin.refresh_skills import knowledge_staleness_report

        report = _make_report(by_content_type={})
        mock_pr.return_value.assess_staleness.return_value = report

        result = knowledge_staleness_report()

        assert "By content type:" not in result

    @patch(PATCH_PR)
    def test_empty_category_section_is_skipped(self, mock_pr: MagicMock) -> None:
        """When by_category is empty, its section is omitted."""
        from engine.skills.builtin.refresh_skills import knowledge_staleness_report

        report = _make_report(by_category={})
        mock_pr.return_value.assess_staleness.return_value = report

        result = knowledge_staleness_report()

        assert "By category:" not in result

    @patch(PATCH_PR)
    def test_worst_entries_formatting(self, mock_pr: MagicMock) -> None:
        """Worst entries show a bar chart, percentage, title, and age."""
        from engine.skills.builtin.refresh_skills import knowledge_staleness_report

        entries = [
            {"title": "Entry Alpha", "staleness_score": 0.75, "content_type": "note", "age_days": 30.0},
            {"title": "Entry Beta", "staleness_score": 0.50, "content_type": "code", "age_days": 14.0},
        ]
        report = _make_report(worst_entries=entries)
        mock_pr.return_value.assess_staleness.return_value = report

        result = knowledge_staleness_report()

        assert "Entry Alpha" in result
        assert "Entry Beta" in result
        assert "75.0%" in result
        assert "50.0%" in result
        assert "█" in result
        assert "░" in result
        assert "age=30d" in result
        assert "age=14d" in result

    @patch(PATCH_PR)
    def test_empty_string_params_converted_to_none(self, mock_pr: MagicMock) -> None:
        """Empty content_type/category strings are converted to None for the API."""
        from engine.skills.builtin.refresh_skills import knowledge_staleness_report

        report = _make_report()
        mock_pr.return_value.assess_staleness.return_value = report

        knowledge_staleness_report(content_type="", category="", limit=50)

        mock_pr.return_value.assess_staleness.assert_called_once_with(
            content_type=None, category=None, limit=50,
        )

    @patch(PATCH_PR)
    def test_nonempty_params_passed_through(self, mock_pr: MagicMock) -> None:
        """Non-empty content_type/category strings are passed as-is."""
        from engine.skills.builtin.refresh_skills import knowledge_staleness_report

        report = _make_report()
        mock_pr.return_value.assess_staleness.return_value = report

        knowledge_staleness_report(content_type="code", category="api", limit=25)

        mock_pr.return_value.assess_staleness.assert_called_once_with(
            content_type="code", category="api", limit=25,
        )


# ──── Refresh Queue ────────────────────────────────────────────────────────


def _make_candidate(
    urgency: str = "high",
    title: str = "Stale entry",
    staleness_score: float = 0.8,
    hours_until_stale: float | None = 12.5,
    refresh_reason: str = "Staleness 0.80 exceeds threshold 0.70",
) -> MagicMock:
    """Build a mock RefreshCandidate."""
    c = MagicMock()
    c.urgency = urgency
    c.title = title
    c.staleness_score = staleness_score
    c.hours_until_stale = hours_until_stale
    c.refresh_reason = refresh_reason
    return c


class TestRefreshQueue:
    """Tests for knowledge_refresh_queue skill."""

    @patch(PATCH_PR)
    def test_empty_queue_message(self, mock_pr: MagicMock) -> None:
        """An empty queue returns the 'all fresh' message."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_queue

        mock_pr.return_value.get_refresh_queue.return_value = []

        result = knowledge_refresh_queue(horizon_hours=24.0)

        assert "Refresh queue is empty" in result
        assert "24h" in result

    @patch(PATCH_PR)
    def test_queue_with_entries_shows_details(self, mock_pr: MagicMock) -> None:
        """Queue with candidates shows urgency, titles, and reasons."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_queue

        candidates = [
            _make_candidate(urgency="high", title="API Docs"),
            _make_candidate(urgency="medium", title="Schema Ref"),
        ]
        mock_pr.return_value.get_refresh_queue.return_value = candidates

        result = knowledge_refresh_queue()

        assert "Refresh Queue (2 entries" in result
        assert "API Docs" in result
        assert "Schema Ref" in result
        assert "Reason:" in result

    @patch(PATCH_PR)
    def test_urgency_icon_mapping(self, mock_pr: MagicMock) -> None:
        """Each urgency level maps to the correct emoji icon."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_queue

        candidates = [
            _make_candidate(urgency="critical"),
            _make_candidate(urgency="high"),
            _make_candidate(urgency="medium"),
            _make_candidate(urgency="low"),
        ]
        mock_pr.return_value.get_refresh_queue.return_value = candidates

        result = knowledge_refresh_queue()

        assert "🔴" in result
        assert "🟠" in result
        assert "🟡" in result
        assert "⚪" in result  # fallback for unknown urgency

    @patch(PATCH_PR)
    def test_hours_until_stale_none_shows_now(self, mock_pr: MagicMock) -> None:
        """When hours_until_stale is None or 0 the output shows 'NOW'."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_queue

        candidates = [
            _make_candidate(hours_until_stale=None),
            _make_candidate(hours_until_stale=0),
        ]
        mock_pr.return_value.get_refresh_queue.return_value = candidates

        result = knowledge_refresh_queue()

        assert result.count("NOW") == 2

    @patch(PATCH_PR)
    def test_parameter_passthrough(self, mock_pr: MagicMock) -> None:
        """horizon_hours, content_type, and max_items are forwarded correctly."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_queue

        mock_pr.return_value.get_refresh_queue.return_value = []

        knowledge_refresh_queue(horizon_hours=72.0, content_type="code", max_items=5)

        mock_pr.return_value.get_refresh_queue.assert_called_once_with(
            horizon_hours=72.0, content_type="code", max_items=5,
        )

    @patch(PATCH_PR)
    def test_empty_content_type_converted_to_none(self, mock_pr: MagicMock) -> None:
        """Empty content_type string is converted to None."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_queue

        mock_pr.return_value.get_refresh_queue.return_value = []

        knowledge_refresh_queue(content_type="")

        _, kwargs = mock_pr.return_value.get_refresh_queue.call_args
        assert kwargs["content_type"] is None


# ──── Refresh Stale ────────────────────────────────────────────────────────


def _make_result(
    status: str = "refreshed",
    title: str = "Updated entry",
    old_staleness: float = 0.8,
    new_staleness: float = 0.1,
    refresh_method: str = "access_reset",
    error: str | None = None,
) -> MagicMock:
    """Build a mock RefreshResult."""
    r = MagicMock()
    r.status = status
    r.title = title
    r.old_staleness = old_staleness
    r.new_staleness = new_staleness
    r.refresh_method = refresh_method
    r.error = error
    return r


class TestRefreshStale:
    """Tests for knowledge_refresh_stale skill."""

    @patch(PATCH_PR)
    def test_no_entries_needed(self, mock_pr: MagicMock) -> None:
        """Empty results list returns 'no entries needed' message."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_stale

        mock_pr.return_value.refresh_stale.return_value = []

        result = knowledge_refresh_stale()

        assert "No entries needed refreshing" in result

    @patch(PATCH_PR)
    def test_refreshed_entries_show_checkmark(self, mock_pr: MagicMock) -> None:
        """Successfully refreshed entries display a ✅ icon."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_stale

        mock_pr.return_value.refresh_stale.return_value = [
            _make_result(status="refreshed", title="Good entry"),
        ]

        result = knowledge_refresh_stale()

        assert "✅" in result
        assert "Good entry" in result
        assert "1 refreshed" in result
        assert "0 failed" in result

    @patch(PATCH_PR)
    def test_failed_entries_show_cross_and_error(self, mock_pr: MagicMock) -> None:
        """Failed entries display a ❌ icon and the error message."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_stale

        mock_pr.return_value.refresh_stale.return_value = [
            _make_result(status="failed", title="Bad entry", error="Connection timeout"),
        ]

        result = knowledge_refresh_stale()

        assert "❌" in result
        assert "Bad entry" in result
        assert "Error: Connection timeout" in result
        assert "0 refreshed" in result
        assert "1 failed" in result

    @patch(PATCH_PR)
    def test_mixed_results(self, mock_pr: MagicMock) -> None:
        """Mixed refreshed/failed results are counted and displayed correctly."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_stale

        mock_pr.return_value.refresh_stale.return_value = [
            _make_result(status="refreshed", title="OK one"),
            _make_result(status="failed", title="Bad one", error="disk full"),
            _make_result(status="refreshed", title="OK two"),
        ]

        result = knowledge_refresh_stale()

        assert "2 refreshed" in result
        assert "1 failed" in result
        assert "✅" in result
        assert "❌" in result
        assert "OK one" in result
        assert "Bad one" in result
        assert "OK two" in result
        assert "Error: disk full" in result

    @patch(PATCH_PR)
    def test_staleness_arrow_displayed(self, mock_pr: MagicMock) -> None:
        """Each result shows old → new staleness percentages."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_stale

        mock_pr.return_value.refresh_stale.return_value = [
            _make_result(old_staleness=0.8, new_staleness=0.1),
        ]

        result = knowledge_refresh_stale()

        assert "80.0%" in result
        assert "10.0%" in result
        assert "→" in result


# ──── Schedule Refresh ─────────────────────────────────────────────────────


class TestScheduleRefresh:
    """Tests for knowledge_schedule_refresh skill."""

    @patch(PATCH_PR)
    def test_untracked_entry_returns_not_tracked(self, mock_pr: MagicMock) -> None:
        """An untracked entry (None schedule) returns a 'not tracked' message."""
        from engine.skills.builtin.refresh_skills import knowledge_schedule_refresh

        mock_pr.return_value.schedule_refresh.return_value = None

        result = knowledge_schedule_refresh(entry_id="missing-123")

        assert "not tracked" in result
        assert "missing-123" in result

    @patch(PATCH_PR)
    def test_schedule_with_full_data(self, mock_pr: MagicMock) -> None:
        """A schedule with all fields populated renders every line."""
        from engine.skills.builtin.refresh_skills import knowledge_schedule_refresh

        mock_pr.return_value.schedule_refresh.return_value = {
            "title": "Core API Reference",
            "current_staleness": 0.4,
            "target_staleness": 0.5,
            "recommendation": "Refresh in 12 hours",
            "hours_until_refresh": 12.0,
            "next_refresh_at": 1_700_000_000.0,
            "hours_until_stale": 36.0,
        }

        result = knowledge_schedule_refresh(entry_id="abc-1")

        assert "Refresh Schedule:" in result
        assert "Core API Reference" in result
        assert "Current staleness: 40.0%" in result
        assert "Target staleness: 50.0%" in result
        assert "Recommendation: Refresh in 12 hours" in result
        assert "Next refresh in: 12.0h" in result
        assert "Scheduled at:" in result
        assert "Predicted stale in: 36.0h" in result

    @patch(PATCH_PR)
    def test_schedule_without_optional_fields(self, mock_pr: MagicMock) -> None:
        """When optional fields are absent, their lines are omitted."""
        from engine.skills.builtin.refresh_skills import knowledge_schedule_refresh

        mock_pr.return_value.schedule_refresh.return_value = {
            "title": "Minimal",
            "current_staleness": 0.2,
            "target_staleness": 0.5,
            "recommendation": "No action needed",
        }

        result = knowledge_schedule_refresh(entry_id="min-1")

        assert "Minimal" in result
        assert "Next refresh in:" not in result
        assert "Scheduled at:" not in result
        assert "Predicted stale in:" not in result

    @patch(PATCH_PR)
    def test_entry_id_and_target_passed_to_engine(self, mock_pr: MagicMock) -> None:
        """entry_id and target_staleness are forwarded to the PR engine."""
        from engine.skills.builtin.refresh_skills import knowledge_schedule_refresh

        mock_pr.return_value.schedule_refresh.return_value = None

        knowledge_schedule_refresh(entry_id="xyz-9", target_staleness=0.3)

        mock_pr.return_value.schedule_refresh.assert_called_once_with(
            "xyz-9", target_staleness=0.3,
        )


# ──── Refresh Status ───────────────────────────────────────────────────────


class TestRefreshStatus:
    """Tests for knowledge_refresh_status skill."""

    @patch(PATCH_PR)
    def test_basic_status_output(self, mock_pr: MagicMock) -> None:
        """Status output includes all snapshot fields."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_status

        mock_pr.return_value.snapshot.return_value = {
            "tracked_entries": 100,
            "total_accesses": 500,
            "total_refreshes": 25,
            "half_life_configs": 12,
            "threshold_configs": 12,
        }

        result = knowledge_refresh_status()

        assert "Predictive Refresh Engine Status" in result
        assert "Tracked entries: 100" in result
        assert "Total accesses: 500" in result
        assert "Total refreshes: 25" in result
        assert "Half-life configs: 12 content types" in result
        assert "Threshold configs: 12 content types" in result

    @patch(PATCH_PR)
    def test_correct_field_labels(self, mock_pr: MagicMock) -> None:
        """Every expected label appears in the output regardless of values."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_status

        mock_pr.return_value.snapshot.return_value = {
            "tracked_entries": 0,
            "total_accesses": 0,
            "total_refreshes": 0,
            "half_life_configs": 0,
            "threshold_configs": 0,
        }

        result = knowledge_refresh_status()

        for label in [
            "Tracked entries:",
            "Total accesses:",
            "Total refreshes:",
            "Half-life configs:",
            "Threshold configs:",
        ]:
            assert label in result

    @patch(PATCH_PR)
    def test_snapshot_called_on_pr_engine(self, mock_pr: MagicMock) -> None:
        """The skill calls snapshot() exactly once on the PR engine."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_status

        mock_pr.return_value.snapshot.return_value = {
            "tracked_entries": 1,
            "total_accesses": 2,
            "total_refreshes": 3,
            "half_life_configs": 4,
            "threshold_configs": 5,
        }

        knowledge_refresh_status()

        mock_pr.return_value.snapshot.assert_called_once()

    @patch(PATCH_PR)
    def test_status_returns_string(self, mock_pr: MagicMock) -> None:
        """The skill returns a plain string."""
        from engine.skills.builtin.refresh_skills import knowledge_refresh_status

        mock_pr.return_value.snapshot.return_value = {
            "tracked_entries": 10,
            "total_accesses": 20,
            "total_refreshes": 5,
            "half_life_configs": 3,
            "threshold_configs": 3,
        }

        result = knowledge_refresh_status()

        assert isinstance(result, str)
