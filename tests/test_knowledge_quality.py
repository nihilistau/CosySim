"""Tests for Nexus knowledge quality scoring (KnowledgeScorer + quality_report)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.self_maintenance import (
    KnowledgeScorer,
    _classify_score,
    quality_report,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_entry(
    title: str = "Test Entry",
    content: str = "Some content here",
    content_type: str = "note",
    category: str = "dev",
    tags: list | None = None,
    age_days: int = 0,
    entry_id: str = "e1",
) -> dict:
    """Build a synthetic Nexus entry dict."""
    created = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    return {
        "id": entry_id,
        "title": title,
        "content": content,
        "content_type": content_type,
        "category": category,
        "tags": tags if tags is not None else ["test"],
        "created_at": created,
        "updated_at": created,
    }


def _rich_entry(age_days: int = 0) -> dict:
    """Entry with long structured content."""
    content = (
        "# Architecture Overview\n\n"
        "This document describes the system architecture.\n\n"
        "## Components\n\n"
        "- Engine core\n"
        "- MCP framework\n"
        "- Nexus knowledge system\n\n"
        "```python\nfrom engine.config import get_config\n```\n\n"
        + "Detail paragraph. " * 30
    )
    return _make_entry(
        title="Architecture overview for CosySim engine",
        content=content,
        content_type="document",
        category="architecture",
        tags=["architecture", "design"],
        age_days=age_days,
    )


# ── Freshness ───────────────────────────────────────────────────────────

class TestFreshness:
    """Freshness scoring tests."""

    def test_brand_new_entry_scores_one(self):
        """Entry created just now should score ~1.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(age_days=0)
        score = scorer.freshness(entry)
        assert score >= 0.99

    def test_old_entry_scores_low(self):
        """Entry older than max_age should score 0.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(age_days=100)
        assert scorer.freshness(entry) == 0.0

    def test_half_age_scores_mid(self):
        """Entry at half max_age should score ~0.5."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(age_days=45)
        score = scorer.freshness(entry)
        assert 0.4 <= score <= 0.6

    def test_missing_timestamp_scores_zero(self):
        """Entry without timestamps returns 0.0."""
        scorer = KnowledgeScorer()
        entry = {"id": "x", "title": "No date"}
        assert scorer.freshness(entry) == 0.0

    def test_custom_max_age(self):
        """Short max_age_days makes entries stale faster."""
        scorer = KnowledgeScorer(max_age_days=10)
        entry = _make_entry(age_days=5)
        assert scorer.freshness(entry) == pytest.approx(0.5, abs=0.02)


# ── Quality ─────────────────────────────────────────────────────────────

class TestQuality:
    """Quality scoring tests."""

    def test_rich_content_scores_high(self):
        """Long structured content with good title scores high."""
        scorer = KnowledgeScorer()
        entry = _rich_entry()
        score = scorer.quality(entry)
        assert score >= 0.8

    def test_empty_content_scores_low(self):
        """Empty content and short title score low."""
        scorer = KnowledgeScorer()
        entry = _make_entry(title="X", content="")
        score = scorer.quality(entry)
        assert score <= 0.1

    def test_medium_content_scores_mid(self):
        """Moderate content length without structure scores mid."""
        scorer = KnowledgeScorer()
        entry = _make_entry(content="A " * 110)  # ~220 chars
        score = scorer.quality(entry)
        assert 0.3 <= score <= 0.7

    def test_code_blocks_add_structure(self):
        """Content with code blocks scores higher than plain text of same length."""
        scorer = KnowledgeScorer()
        plain = _make_entry(content="word " * 100)
        structured = _make_entry(content="word " * 80 + "\n```python\nx=1\n```\n")
        assert scorer.quality(structured) >= scorer.quality(plain)

    def test_descriptive_title_bonus(self):
        """Multi-word title gets bonus over single-word title."""
        scorer = KnowledgeScorer()
        short_title = _make_entry(title="Fix", content="x" * 100)
        long_title = _make_entry(
            title="Fix the interceptor pipeline bug",
            content="x" * 100,
        )
        assert scorer.quality(long_title) > scorer.quality(short_title)


# ── Uniqueness ──────────────────────────────────────────────────────────

class TestUniqueness:
    """Uniqueness scoring tests."""

    def test_unique_title_scores_high(self):
        """Title with no overlap to others scores 1.0."""
        entries = [
            _make_entry(title="Alpha bravo charlie", entry_id="e1"),
            _make_entry(title="Delta echo foxtrot", entry_id="e2"),
        ]
        scorer = KnowledgeScorer(all_entries=entries)
        assert scorer.uniqueness(entries[0]) >= 0.9

    def test_duplicate_title_scores_low(self):
        """Nearly identical titles score low uniqueness."""
        entries = [
            _make_entry(title="Fix auth bug in login", entry_id="e1"),
            _make_entry(title="Fix auth bug in login page", entry_id="e2"),
        ]
        scorer = KnowledgeScorer(all_entries=entries)
        score = scorer.uniqueness(entries[0])
        assert score < 0.3

    def test_identical_titles_score_zero(self):
        """Exact same title (aside from self) results in 0.0 uniqueness."""
        entries = [
            _make_entry(title="same title", entry_id="e1"),
            _make_entry(title="same title", entry_id="e2"),
        ]
        scorer = KnowledgeScorer(all_entries=entries)
        assert scorer.uniqueness(entries[0]) == 0.0

    def test_no_other_entries_scores_one(self):
        """Single entry in the knowledge base is fully unique."""
        entries = [_make_entry(title="Only entry", entry_id="e1")]
        scorer = KnowledgeScorer(all_entries=entries)
        assert scorer.uniqueness(entries[0]) == 1.0

    def test_empty_title_scores_one(self):
        """Entry with empty title should default to 1.0."""
        scorer = KnowledgeScorer(all_entries=[_make_entry(title="something")])
        assert scorer.uniqueness({"title": ""}) == 1.0


# ── Completeness ────────────────────────────────────────────────────────

class TestCompleteness:
    """Completeness scoring tests."""

    def test_all_fields_present_scores_one(self):
        """Entry with all metadata fields scores 1.0."""
        scorer = KnowledgeScorer()
        entry = _make_entry()
        assert scorer.completeness(entry) == pytest.approx(1.0)

    def test_missing_all_fields_scores_zero(self):
        """Empty entry scores 0.0."""
        scorer = KnowledgeScorer()
        assert scorer.completeness({}) == 0.0

    def test_missing_tags_loses_point(self):
        """Entry without tags loses 0.2."""
        scorer = KnowledgeScorer()
        entry = _make_entry(tags=[])
        # tags empty list → not counted
        assert scorer.completeness(entry) == pytest.approx(0.8)

    def test_missing_category_loses_point(self):
        """Entry without category loses 0.2."""
        scorer = KnowledgeScorer()
        entry = _make_entry(category="")
        assert scorer.completeness(entry) == pytest.approx(0.8)

    def test_partial_fields(self):
        """Entry with only title and content scores 0.4."""
        scorer = KnowledgeScorer()
        entry = {"title": "Hello", "content": "World"}
        assert scorer.completeness(entry) == pytest.approx(0.4)


# ── Composite Score ─────────────────────────────────────────────────────

class TestCompositeScore:
    """Composite score weighting tests."""

    def test_perfect_entry_scores_near_one(self):
        """Fresh, rich, unique, complete entry scores close to 1.0."""
        entries = [_rich_entry(age_days=0)]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=entries)
        comp = scorer.composite_score(entries[0])
        assert comp >= 0.8

    def test_terrible_entry_scores_low(self):
        """Old, empty, duplicate, incomplete entry scores very low."""
        entries = [
            {"id": "bad", "title": "x", "created_at": "2020-01-01T00:00:00+00:00"},
            {"id": "bad2", "title": "x"},
        ]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=entries)
        comp = scorer.composite_score(entries[0])
        assert comp < 0.25

    def test_weights_sum_to_one(self):
        """Verify configured weights sum to 1.0."""
        total = sum(KnowledgeScorer.WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_score_entry_returns_full_dict(self):
        """score_entry returns all expected keys."""
        entries = [_make_entry()]
        scorer = KnowledgeScorer(all_entries=entries)
        result = scorer.score_entry(entries[0])
        expected_keys = {
            "entry_id", "title", "freshness", "quality",
            "uniqueness", "completeness", "composite", "issues",
        }
        assert set(result.keys()) == expected_keys

    def test_score_all_returns_list(self):
        """score_all returns one result per input entry."""
        entries = [_make_entry(entry_id=f"e{i}") for i in range(5)]
        scorer = KnowledgeScorer(all_entries=entries)
        results = scorer.score_all(entries)
        assert len(results) == 5
        assert all("composite" in r for r in results)


# ── Score Classification ────────────────────────────────────────────────

class TestClassifyScore:
    """Score distribution bucketing tests."""

    def test_excellent(self):
        assert _classify_score(0.9) == "excellent"
        assert _classify_score(0.7) == "excellent"

    def test_good(self):
        assert _classify_score(0.6) == "good"
        assert _classify_score(0.5) == "good"

    def test_fair(self):
        assert _classify_score(0.4) == "fair"
        assert _classify_score(0.3) == "fair"

    def test_poor(self):
        assert _classify_score(0.2) == "poor"
        assert _classify_score(0.0) == "poor"


# ── quality_report() ────────────────────────────────────────────────────

class TestQualityReport:
    """Integration tests for quality_report()."""

    @patch("engine.nexus.self_maintenance._get_client")
    def test_report_structure(self, mock_get_client):
        """Report contains all expected top-level keys."""
        client = MagicMock()
        client.list_entries.return_value = [
            _make_entry(entry_id="e1"),
            _rich_entry(age_days=5),
        ]
        mock_get_client.return_value = client

        report = quality_report()

        assert "total_entries" in report
        assert "average_score" in report
        assert "score_distribution" in report
        assert "low_quality" in report
        assert "duplicates" in report
        assert "stale" in report
        assert "recommendations" in report

    @patch("engine.nexus.self_maintenance._get_client")
    def test_report_counts_match(self, mock_get_client):
        """Total entries in report equals number of entries returned."""
        entries = [_make_entry(entry_id=f"e{i}") for i in range(10)]
        client = MagicMock()
        client.list_entries.return_value = entries
        mock_get_client.return_value = client

        report = quality_report()
        assert report["total_entries"] == 10

    @patch("engine.nexus.self_maintenance._get_client")
    def test_distribution_sums_to_total(self, mock_get_client):
        """Score distribution buckets should sum to total_entries."""
        entries = [_make_entry(entry_id=f"e{i}") for i in range(7)]
        client = MagicMock()
        client.list_entries.return_value = entries
        mock_get_client.return_value = client

        report = quality_report()
        dist = report["score_distribution"]
        assert sum(dist.values()) == report["total_entries"]

    @patch("engine.nexus.self_maintenance._get_client")
    def test_stale_entries_flagged(self, mock_get_client):
        """Entries older than max_age should appear in stale list."""
        entries = [_make_entry(entry_id="old", age_days=200)]
        client = MagicMock()
        client.list_entries.return_value = entries
        mock_get_client.return_value = client

        report = quality_report()
        assert len(report["stale"]) == 1
        assert report["stale"][0]["entry_id"] == "old"

    @patch("engine.nexus.self_maintenance._get_client")
    def test_duplicates_flagged(self, mock_get_client):
        """Entries with near-identical titles appear in duplicates list."""
        entries = [
            _make_entry(title="fix login bug", entry_id="d1"),
            _make_entry(title="fix login bug", entry_id="d2"),
        ]
        client = MagicMock()
        client.list_entries.return_value = entries
        mock_get_client.return_value = client

        report = quality_report()
        assert len(report["duplicates"]) >= 1

    @patch("engine.nexus.self_maintenance._get_client")
    def test_empty_kb_returns_defaults(self, mock_get_client):
        """Empty knowledge base returns zero counts and a recommendation."""
        client = MagicMock()
        client.list_entries.return_value = []
        mock_get_client.return_value = client

        report = quality_report()
        assert report["total_entries"] == 0
        assert report["average_score"] == 0.0
        assert sum(report["score_distribution"].values()) == 0

    @patch("engine.nexus.self_maintenance._get_client")
    def test_client_error_returns_safe_default(self, mock_get_client):
        """If client.list_entries raises, report returns gracefully."""
        client = MagicMock()
        client.list_entries.side_effect = ConnectionError("offline")
        mock_get_client.return_value = client

        report = quality_report()
        assert report["total_entries"] == 0
        assert "Could not fetch entries" in report["recommendations"][0]


# ── Recommendations ─────────────────────────────────────────────────────

class TestRecommendations:
    """Recommendation generation tests."""

    @patch("engine.nexus.self_maintenance._get_client")
    def test_poor_entries_trigger_recommendation(self, mock_get_client):
        """Many poor entries trigger a review recommendation."""
        # Create entries that will score poorly (old, empty content, no metadata)
        entries = [
            {
                "id": f"p{i}",
                "title": f"p{i}",
                "content": "",
                "created_at": "2020-01-01T00:00:00+00:00",
            }
            for i in range(10)
        ]
        client = MagicMock()
        client.list_entries.return_value = entries
        mock_get_client.return_value = client

        report = quality_report()
        recs = " ".join(report["recommendations"])
        assert "poor" in recs.lower() or "quality" in recs.lower()

    @patch("engine.nexus.self_maintenance._get_client")
    def test_healthy_kb_gets_positive_recommendation(self, mock_get_client):
        """A healthy knowledge base gets a positive message."""
        distinct_titles = [
            "Alpha bravo charlie delta",
            "Echo foxtrot golf hotel",
            "India juliet kilo lima",
            "Mike november oscar papa",
            "Quebec romeo sierra tango",
        ]
        entries = [_rich_entry(age_days=i) for i in range(5)]
        for i, e in enumerate(entries):
            e["id"] = f"h{i}"
            e["title"] = distinct_titles[i]
        client = MagicMock()
        client.list_entries.return_value = entries
        mock_get_client.return_value = client

        report = quality_report()
        recs = " ".join(report["recommendations"])
        assert "healthy" in recs.lower()


# ── Issues Detection ────────────────────────────────────────────────────

class TestIssuesDetection:
    """Tests for per-entry issue flagging."""

    def test_stale_issue_flagged(self):
        """Entries with low freshness get 'stale' issue."""
        entry = _make_entry(age_days=200)
        scorer = KnowledgeScorer(max_age_days=90, all_entries=[entry])
        result = scorer.score_entry(entry)
        assert "stale" in result["issues"]

    def test_low_quality_issue_flagged(self):
        """Entries with empty content get 'low_quality_content' issue."""
        entry = _make_entry(title="X", content="")
        scorer = KnowledgeScorer(all_entries=[entry])
        result = scorer.score_entry(entry)
        assert "low_quality_content" in result["issues"]

    def test_duplicate_issue_flagged(self):
        """Entries with near-identical titles get 'likely_duplicate'."""
        entries = [
            _make_entry(title="same thing", entry_id="e1"),
            _make_entry(title="same thing", entry_id="e2"),
        ]
        scorer = KnowledgeScorer(all_entries=entries)
        result = scorer.score_entry(entries[0])
        assert "likely_duplicate" in result["issues"]

    def test_incomplete_issue_flagged(self):
        """Entries missing metadata get 'incomplete_metadata'."""
        entry = {"id": "x", "title": "Hello"}
        scorer = KnowledgeScorer(all_entries=[entry])
        result = scorer.score_entry(entry)
        assert "incomplete_metadata" in result["issues"]

    def test_good_entry_has_no_issues(self):
        """Well-formed fresh entry has empty issues list."""
        entry = _rich_entry(age_days=1)
        scorer = KnowledgeScorer(max_age_days=90, all_entries=[entry])
        result = scorer.score_entry(entry)
        assert result["issues"] == []
