"""Tests for engine.nexus.self_maintenance — KnowledgeScorer, helpers, and Nexus maintenance functions.

Covers:
- KnowledgeScorer (pure logic — freshness, quality, uniqueness, completeness, composite)
- Module-level Nexus functions (health report, duplicates, scoring, backup, full maintenance)
- Helper functions (_title_similarity, _classify_score)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.self_maintenance import (
    KnowledgeScorer,
    _classify_score,
    _title_similarity,
    nexus_backup,
    nexus_find_duplicates,
    nexus_full_maintenance,
    nexus_health_report,
    nexus_list_backups,
    nexus_merge_duplicates,
    nexus_prune_backups,
    nexus_score_entries,
    quality_report,
)

# Patch target — lazy import inside _get_client()
_PATCH_CLIENT = "engine.nexus.self_maintenance._get_client"
_PATCH_BACKUP_DIR = "engine.nexus.self_maintenance._get_backup_dir"
_PATCH_CONFIG = "engine.nexus.self_maintenance.KnowledgeScorer._load_category_ttl_from_config"


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_entry(
    id: str = "entry-1",
    title: str = "Test Entry",
    content: str = "Some content here with enough text to score well on quality checks",
    content_type: str = "note",
    category: str = "architecture",
    tags: list | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict:
    """Build a Nexus entry dict for testing."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "id": id,
        "title": title,
        "content": content,
        "content_type": content_type,
        "category": category,
        "tags": tags if tags is not None else ["test", "example"],
        "created_at": created_at or now_iso,
        "updated_at": updated_at or now_iso,
    }


def _make_old_entry(age_days: int = 180, **overrides) -> dict:
    """Build an entry with a created_at timestamp in the past."""
    past = datetime.now(timezone.utc) - timedelta(days=age_days)
    defaults = {
        "id": "old-entry",
        "title": "Old Entry",
        "content": "Stale content from long ago that is no longer relevant",
        "created_at": past.isoformat(),
        "updated_at": past.isoformat(),
    }
    defaults.update(overrides)
    return _make_entry(**defaults)


def _mock_client(**overrides) -> MagicMock:
    """Return a pre-configured NexusClient mock with sensible defaults."""
    client = MagicMock()
    client.is_available.return_value = overrides.get("available", True)
    client.stats.return_value = overrides.get("stats", {
        "total_entries": 42,
        "total_qa": 10,
        "total_sessions": 5,
        "total_rules": 3,
        "total_prompts": 2,
    })
    client.list_entries.return_value = overrides.get("entries", [])
    client.list_sessions.return_value = overrides.get("sessions", [])
    client.list_by_type.return_value = overrides.get("by_type", [])
    client.search.return_value = overrides.get("search", [])
    client.delete_entry.return_value = True
    client.add_entry.return_value = "new-entry-id"
    client.add_qa.return_value = True
    return client


# ════════════════════════════════════════════════════════════════════════
#  KnowledgeScorer — pure logic, no mocking required
# ════════════════════════════════════════════════════════════════════════


class TestKnowledgeScorerFreshness:
    """Tests for KnowledgeScorer.freshness — age-based scoring."""

    @patch(_PATCH_CONFIG)
    def test_freshness_new_entry_scores_high(self, _mock_cfg):
        """An entry created today should score very close to 1.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(created_at=datetime.now(timezone.utc).isoformat())
        score = scorer.freshness(entry)
        assert score >= 0.95, f"New entry freshness {score} should be >= 0.95"

    @patch(_PATCH_CONFIG)
    def test_freshness_old_entry_scores_low(self, _mock_cfg):
        """An entry 180 days old (max_age=90) should score 0.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_old_entry(age_days=180)
        score = scorer.freshness(entry)
        assert score == 0.0, f"Old entry freshness {score} should be 0.0"

    @patch(_PATCH_CONFIG)
    def test_freshness_half_age_scores_around_half(self, _mock_cfg):
        """An entry at 50% of max age should score ~0.5."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_old_entry(age_days=45)
        score = scorer.freshness(entry)
        assert 0.4 <= score <= 0.6, f"Half-age freshness {score} should be ~0.5"

    @patch(_PATCH_CONFIG)
    def test_freshness_uses_category_ttl(self, _mock_cfg):
        """News (ttl=2 days) should go stale much faster than architecture (ttl=365)."""
        category_ttl = {"news": 2, "architecture": 365}
        scorer = KnowledgeScorer(max_age_days=90, category_ttl_days=category_ttl)

        # 3-day-old news → past its TTL → 0.0
        news_entry = _make_old_entry(age_days=3, category="news")
        news_score = scorer.freshness(news_entry)

        # 3-day-old architecture → still very fresh
        arch_entry = _make_old_entry(age_days=3, category="architecture")
        arch_score = scorer.freshness(arch_entry)

        assert news_score == 0.0, f"3-day news should be stale, got {news_score}"
        assert arch_score >= 0.95, f"3-day architecture should be fresh, got {arch_score}"

    @patch(_PATCH_CONFIG)
    def test_freshness_missing_timestamp_returns_zero(self, _mock_cfg):
        """Entry without created_at or updated_at scores 0.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = {"id": "no-ts", "title": "No Timestamp"}
        assert scorer.freshness(entry) == 0.0

    @patch(_PATCH_CONFIG)
    def test_freshness_uses_updated_at_over_created_at(self, _mock_cfg):
        """updated_at should be preferred if present."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(
            created_at=(datetime.now(timezone.utc) - timedelta(days=80)).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        score = scorer.freshness(entry)
        assert score >= 0.95, "Should use fresh updated_at, not old created_at"

    @patch(_PATCH_CONFIG)
    def test_freshness_numeric_timestamp_supported(self, _mock_cfg):
        """Numeric (epoch) timestamps should be handled."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = {"id": "e1", "title": "T", "updated_at": time.time()}
        score = scorer.freshness(entry)
        assert score >= 0.95


class TestKnowledgeScorerQuality:
    """Tests for KnowledgeScorer.quality — content richness scoring."""

    @patch(_PATCH_CONFIG)
    def test_quality_long_content_scores_high(self, _mock_cfg):
        """500+ character content should get the full 0.4 length contribution."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(
            title="A very descriptive multi-word title for testing quality",
            content="x" * 500,
        )
        score = scorer.quality(entry)
        assert score >= 0.6, f"Long content quality {score} should be >= 0.6"

    @patch(_PATCH_CONFIG)
    def test_quality_short_content_scores_low(self, _mock_cfg):
        """10 character content should score very low."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(title="T", content="tiny text!")
        score = scorer.quality(entry)
        assert score <= 0.3, f"Short content quality {score} should be <= 0.3"

    @patch(_PATCH_CONFIG)
    def test_quality_empty_content_scores_minimal(self, _mock_cfg):
        """Empty content yields only title contribution, if any."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(title="", content="")
        score = scorer.quality(entry)
        assert score == 0.0

    @patch(_PATCH_CONFIG)
    def test_quality_structured_content_bonus(self, _mock_cfg):
        """Content with headers, bullets, and code blocks gets structure bonus."""
        scorer = KnowledgeScorer(max_age_days=90)
        structured_content = (
            "# Architecture Overview\n\n"
            "- Component A handles routing\n"
            "- Component B manages state\n\n"
            "```python\ndef example():\n    pass\n```\n"
        )
        entry = _make_entry(
            title="Architecture overview for CosySim engine",
            content=structured_content,
        )
        score = scorer.quality(entry)
        # Structured content of decent length with multi-word title → high quality
        assert score >= 0.7, f"Structured quality {score} should be >= 0.7"

    @patch(_PATCH_CONFIG)
    def test_quality_header_detection(self, _mock_cfg):
        """Markdown headers (# Section) contribute to structure score."""
        scorer = KnowledgeScorer(max_age_days=90)
        with_header = _make_entry(content="# Heading\nSome content after heading")
        without_header = _make_entry(content="Some content without heading")
        assert scorer.quality(with_header) > scorer.quality(without_header)

    @patch(_PATCH_CONFIG)
    def test_quality_bullet_list_detection(self, _mock_cfg):
        """Bullet lists (- item) contribute to structure score."""
        scorer = KnowledgeScorer(max_age_days=90)
        with_bullets = _make_entry(content="Overview:\n- item one\n- item two\n- item three")
        without_bullets = _make_entry(content="Overview: item one, item two, item three")
        assert scorer.quality(with_bullets) > scorer.quality(without_bullets)

    @patch(_PATCH_CONFIG)
    def test_quality_multiword_title_bonus(self, _mock_cfg):
        """Titles with 3+ words get a bonus over single-word titles."""
        scorer = KnowledgeScorer(max_age_days=90)
        multi = _make_entry(title="Detailed multi word descriptive title", content="c" * 60)
        single = _make_entry(title="X", content="c" * 60)
        assert scorer.quality(multi) > scorer.quality(single)

    @patch(_PATCH_CONFIG)
    def test_quality_capped_at_one(self, _mock_cfg):
        """Quality score must not exceed 1.0 even with all bonuses."""
        scorer = KnowledgeScorer(max_age_days=90)
        maxed = _make_entry(
            title="A very descriptive multi-word title for max quality scoring",
            content="# Big Heading\n" + "- bullet\n" * 20 + "```code\nblock\n```\n" + "x" * 600,
        )
        assert scorer.quality(maxed) <= 1.0


class TestKnowledgeScorerUniqueness:
    """Tests for KnowledgeScorer.uniqueness — title distinctness scoring."""

    @patch(_PATCH_CONFIG)
    def test_uniqueness_distinct_titles(self, _mock_cfg):
        """A title unique among all entries should score ~1.0."""
        all_entries = [
            _make_entry(id="e1", title="Alpha Design Patterns"),
            _make_entry(id="e2", title="Beta Configuration Guide"),
            _make_entry(id="e3", title="Gamma Deployment Steps"),
        ]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=all_entries)
        entry = _make_entry(title="Completely Unrelated Unique Topic")
        score = scorer.uniqueness(entry)
        assert score >= 0.8, f"Unique title should score >= 0.8, got {score}"

    @patch(_PATCH_CONFIG)
    def test_uniqueness_identical_titles(self, _mock_cfg):
        """An exact duplicate title should score very low (near 0.0)."""
        all_entries = [
            _make_entry(id="e1", title="setup guide"),
            _make_entry(id="e2", title="setup guide"),
        ]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=all_entries)
        # Score entry e1 — it should see e2 as an exact match
        entry = _make_entry(title="setup guide")
        score = scorer.uniqueness(entry)
        assert score == 0.0, f"Identical title uniqueness should be 0.0, got {score}"

    @patch(_PATCH_CONFIG)
    def test_uniqueness_similar_titles(self, _mock_cfg):
        """Near-duplicate titles should score below 0.5."""
        all_entries = [
            _make_entry(id="e1", title="how to configure database settings"),
            _make_entry(id="e2", title="how to configure database connections"),
        ]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=all_entries)
        entry = _make_entry(title="how to configure database settings")
        score = scorer.uniqueness(entry)
        assert score < 0.5, f"Similar title uniqueness {score} should be < 0.5"

    @patch(_PATCH_CONFIG)
    def test_uniqueness_no_other_entries(self, _mock_cfg):
        """With no other entries, uniqueness defaults to 1.0."""
        scorer = KnowledgeScorer(max_age_days=90, all_entries=[])
        entry = _make_entry(title="Sole Entry")
        assert scorer.uniqueness(entry) == 1.0

    @patch(_PATCH_CONFIG)
    def test_uniqueness_empty_title(self, _mock_cfg):
        """Empty title defaults to 1.0 (nothing to compare)."""
        scorer = KnowledgeScorer(max_age_days=90, all_entries=[_make_entry()])
        entry = _make_entry(title="")
        assert scorer.uniqueness(entry) == 1.0


class TestKnowledgeScorerCompleteness:
    """Tests for KnowledgeScorer.completeness — metadata presence scoring."""

    @patch(_PATCH_CONFIG)
    def test_completeness_full_metadata(self, _mock_cfg):
        """Entry with all 5 fields (title, content, content_type, category, tags) → 1.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(
            title="Present",
            content="Has content",
            content_type="note",
            category="architecture",
            tags=["tag1"],
        )
        assert scorer.completeness(entry) == 1.0

    @patch(_PATCH_CONFIG)
    def test_completeness_partial_metadata(self, _mock_cfg):
        """Entry missing some fields scores proportionally lower."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = {
            "id": "e1",
            "title": "Only Title",
            "content": "Some content",
            # missing: content_type, category, tags
        }
        score = scorer.completeness(entry)
        # title (0.2) + content (0.2) = 0.4
        assert score == pytest.approx(0.4)

    @patch(_PATCH_CONFIG)
    def test_completeness_empty_entry(self, _mock_cfg):
        """Entry with no metadata scores 0.0."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = {"id": "e-empty"}
        assert scorer.completeness(entry) == 0.0

    @patch(_PATCH_CONFIG)
    def test_completeness_empty_tags_list_not_counted(self, _mock_cfg):
        """An empty tags list [] should not contribute 0.2."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(tags=[])
        score = scorer.completeness(entry)
        # 4 fields present (title, content, content_type, category) = 0.8
        assert score == pytest.approx(0.8)

    @patch(_PATCH_CONFIG)
    def test_completeness_each_field_contributes_point_two(self, _mock_cfg):
        """Each present field adds exactly 0.2."""
        scorer = KnowledgeScorer(max_age_days=90)
        # Only title
        assert scorer.completeness({"title": "T"}) == pytest.approx(0.2)
        # Title + content
        assert scorer.completeness({"title": "T", "content": "C"}) == pytest.approx(0.4)
        # Title + content + content_type
        assert scorer.completeness({
            "title": "T", "content": "C", "content_type": "note",
        }) == pytest.approx(0.6)


class TestKnowledgeScorerComposite:
    """Tests for composite_score, score_entry, and score_all."""

    @patch(_PATCH_CONFIG)
    def test_composite_score_weights_correctly(self, _mock_cfg):
        """Composite should be: f*0.2 + q*0.4 + u*0.2 + c*0.2."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry()

        f = scorer.freshness(entry)
        q = scorer.quality(entry)
        u = scorer.uniqueness(entry)
        c = scorer.completeness(entry)
        expected = round(f * 0.2 + q * 0.4 + u * 0.2 + c * 0.2, 4)

        assert scorer.composite_score(entry) == pytest.approx(expected, abs=1e-4)

    @patch(_PATCH_CONFIG)
    def test_composite_weights_sum_to_one(self, _mock_cfg):
        """Weights should total exactly 1.0."""
        total = sum(KnowledgeScorer.WEIGHTS.values())
        assert total == pytest.approx(1.0)

    @patch(_PATCH_CONFIG)
    def test_score_entry_returns_all_dimensions(self, _mock_cfg):
        """score_entry returns dict with all dimension keys + issues."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry()
        result = scorer.score_entry(entry)

        assert "entry_id" in result
        assert "title" in result
        assert "freshness" in result
        assert "quality" in result
        assert "uniqueness" in result
        assert "completeness" in result
        assert "composite" in result
        assert "issues" in result
        assert isinstance(result["issues"], list)

    @patch(_PATCH_CONFIG)
    def test_score_entry_flags_stale_issue(self, _mock_cfg):
        """Old entries (freshness < 0.2) get 'stale' flag."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_old_entry(age_days=180)
        result = scorer.score_entry(entry)
        assert "stale" in result["issues"]

    @patch(_PATCH_CONFIG)
    def test_score_entry_flags_low_quality(self, _mock_cfg):
        """Entries with short content (quality < 0.3) get 'low_quality_content' flag."""
        scorer = KnowledgeScorer(max_age_days=90)
        entry = _make_entry(title="X", content="tiny")
        result = scorer.score_entry(entry)
        assert "low_quality_content" in result["issues"]

    @patch(_PATCH_CONFIG)
    def test_score_entry_flags_likely_duplicate(self, _mock_cfg):
        """Entry with low uniqueness gets 'likely_duplicate' flag."""
        all_entries = [
            _make_entry(id="e1", title="duplicate title here"),
            _make_entry(id="e2", title="duplicate title here"),
        ]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=all_entries)
        result = scorer.score_entry(all_entries[0])
        assert "likely_duplicate" in result["issues"]

    @patch(_PATCH_CONFIG)
    def test_score_entry_flags_incomplete_metadata(self, _mock_cfg):
        """Entry missing most metadata (completeness < 0.4) gets 'incomplete_metadata' flag."""
        scorer = KnowledgeScorer(max_age_days=90)
        sparse_entry = {"id": "e-sparse", "title": "Only Title"}
        result = scorer.score_entry(sparse_entry)
        assert "incomplete_metadata" in result["issues"]

    @patch(_PATCH_CONFIG)
    def test_score_entry_no_issues_for_perfect_entry(self, _mock_cfg):
        """A well-formed, fresh, unique entry should have no issues."""
        all_entries = [
            _make_entry(id="e1", title="Unique topic about quantum physics"),
            _make_entry(id="e2", title="Unrelated topic about marine biology"),
        ]
        scorer = KnowledgeScorer(max_age_days=90, all_entries=all_entries)
        entry = _make_entry(
            title="Unique topic about quantum physics",
            content="# Quantum Physics\n\n- Topic 1\n- Topic 2\n\n" + "x" * 500,
        )
        result = scorer.score_entry(entry)
        # Fresh, high-quality, complete metadata, and unique enough
        assert result["freshness"] >= 0.2
        assert result["quality"] >= 0.3
        assert result["completeness"] >= 0.4
        assert len(result["issues"]) == 0, f"Expected no issues, got {result['issues']}"

    @patch(_PATCH_CONFIG)
    def test_score_all_returns_list(self, _mock_cfg):
        """score_all returns a list of scored dicts, same length as input."""
        scorer = KnowledgeScorer(max_age_days=90)
        entries = [
            _make_entry(id="e1", title="First Entry"),
            _make_entry(id="e2", title="Second Entry"),
            _make_entry(id="e3", title="Third Entry"),
        ]
        results = scorer.score_all(entries)
        assert isinstance(results, list)
        assert len(results) == 3
        assert all("composite" in r for r in results)
        assert all("issues" in r for r in results)

    @patch(_PATCH_CONFIG)
    def test_score_all_preserves_order(self, _mock_cfg):
        """Results are in the same order as input entries."""
        scorer = KnowledgeScorer(max_age_days=90)
        entries = [
            _make_entry(id=f"e{i}", title=f"Entry {i}") for i in range(5)
        ]
        results = scorer.score_all(entries)
        for i, r in enumerate(results):
            assert r["entry_id"] == f"e{i}"

    @patch(_PATCH_CONFIG)
    def test_score_all_empty_list(self, _mock_cfg):
        """Empty input returns empty output."""
        scorer = KnowledgeScorer(max_age_days=90)
        assert scorer.score_all([]) == []


# ════════════════════════════════════════════════════════════════════════
#  _title_similarity — Jaccard similarity (pure function)
# ════════════════════════════════════════════════════════════════════════


class TestTitleSimilarity:
    """Tests for the Jaccard word-set similarity helper."""

    def test_title_similarity_identical(self):
        """Identical strings return 1.0."""
        assert _title_similarity("hello world", "hello world") == 1.0

    def test_title_similarity_different(self):
        """Completely disjoint word sets return 0.0."""
        assert _title_similarity("alpha beta", "gamma delta") == 0.0

    def test_title_similarity_partial(self):
        """Partial overlap returns a value between 0 and 1."""
        # {"how", "to", "cook"} ∩ {"how", "to", "bake"} = 2; union = 4 → 0.5
        sim = _title_similarity("how to cook", "how to bake")
        assert sim == pytest.approx(0.5)
        assert 0.0 < sim < 1.0

    def test_title_similarity_empty_first(self):
        """Empty first string returns 0.0."""
        assert _title_similarity("", "something") == 0.0

    def test_title_similarity_empty_second(self):
        """Empty second string returns 0.0."""
        assert _title_similarity("something", "") == 0.0

    def test_title_similarity_both_empty(self):
        """Two empty strings return 0.0."""
        assert _title_similarity("", "") == 0.0

    def test_title_similarity_single_word_match(self):
        """Single identical word gives 1.0."""
        assert _title_similarity("hello", "hello") == 1.0

    def test_title_similarity_superset(self):
        """Superset relationship: {a,b} vs {a,b,c} = 2/3."""
        sim = _title_similarity("a b", "a b c")
        assert sim == pytest.approx(2 / 3)


# ════════════════════════════════════════════════════════════════════════
#  _classify_score — score-to-label mapping
# ════════════════════════════════════════════════════════════════════════


class TestClassifyScore:
    """Tests for _classify_score — composite → label bucketing."""

    def test_classify_score_excellent(self):
        """Score >= 0.7 is 'excellent'."""
        assert _classify_score(0.85) == "excellent"
        assert _classify_score(0.7) == "excellent"
        assert _classify_score(1.0) == "excellent"

    def test_classify_score_good(self):
        """Score in [0.5, 0.7) is 'good'."""
        assert _classify_score(0.5) == "good"
        assert _classify_score(0.65) == "good"

    def test_classify_score_fair(self):
        """Score in [0.3, 0.5) is 'fair'."""
        assert _classify_score(0.3) == "fair"
        assert _classify_score(0.45) == "fair"

    def test_classify_score_poor(self):
        """Score < 0.3 is 'poor'."""
        assert _classify_score(0.1) == "poor"
        assert _classify_score(0.0) == "poor"
        assert _classify_score(0.29) == "poor"

    def test_classify_score_boundary_values(self):
        """Boundary values are assigned to the higher bucket."""
        assert _classify_score(0.7) == "excellent"  # not "good"
        assert _classify_score(0.5) == "good"        # not "fair"
        assert _classify_score(0.3) == "fair"         # not "poor"


# ════════════════════════════════════════════════════════════════════════
#  nexus_health_report — requires mocked NexusClient
# ════════════════════════════════════════════════════════════════════════


class TestNexusHealthReport:
    """Tests for the health-report generator."""

    @patch(_PATCH_CLIENT)
    def test_health_report_returns_status(self, mock_gc):
        """Healthy report includes 'healthy' status and metric counts."""
        mock_gc.return_value = _mock_client()
        report = nexus_health_report()
        assert report["status"] == "healthy"
        assert "timestamp" in report
        assert report["metrics"]["total_entries"] == 42
        assert report["metrics"]["total_qa"] == 10

    @patch(_PATCH_CLIENT)
    def test_health_report_offline(self, mock_gc):
        """Unavailable Nexus returns 'offline' status."""
        mock_gc.return_value = _mock_client(available=False)
        report = nexus_health_report()
        assert report["status"] == "offline"
        assert len(report["issues"]) >= 1

    @patch(_PATCH_CLIENT)
    def test_health_report_stats_exception(self, mock_gc):
        """Exception from stats() yields 'error' status."""
        client = _mock_client()
        client.stats.side_effect = RuntimeError("connection refused")
        mock_gc.return_value = client
        report = nexus_health_report()
        assert report["status"] == "error"
        assert any("Failed" in i for i in report["issues"])

    @patch(_PATCH_CLIENT)
    def test_health_report_empty_knowledge_base(self, mock_gc):
        """Zero entries triggers appropriate issue and recommendation."""
        mock_gc.return_value = _mock_client(stats={
            "total_entries": 0, "total_qa": 0,
            "total_sessions": 0, "total_rules": 0, "total_prompts": 0,
        })
        report = nexus_health_report()
        assert any("empty" in i.lower() for i in report["issues"])


# ════════════════════════════════════════════════════════════════════════
#  nexus_find_duplicates — requires mocked NexusClient
# ════════════════════════════════════════════════════════════════════════


class TestNexusFindDuplicates:
    """Tests for duplicate detection."""

    @patch(_PATCH_CLIENT)
    def test_find_duplicates_groups_similar(self, mock_gc):
        """Entries with identical titles (case-insensitive in caller) are grouped."""
        entries = [
            _make_entry(id="e1", title="setup guide for deployment"),
            _make_entry(id="e2", title="setup guide for deployment"),
            _make_entry(id="e3", title="unrelated topic entirely"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates(threshold=0.85)
        assert len(groups) >= 1
        assert groups[0]["count"] >= 2

    @patch(_PATCH_CLIENT)
    def test_find_duplicates_no_duplicates(self, mock_gc):
        """Entries with completely different titles return no groups."""
        entries = [
            _make_entry(id="e1", title="alpha bravo charlie"),
            _make_entry(id="e2", title="delta echo foxtrot"),
            _make_entry(id="e3", title="golf hotel india"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates(threshold=0.85)
        assert len(groups) == 0

    @patch(_PATCH_CLIENT)
    def test_find_duplicates_respects_threshold(self, mock_gc):
        """Higher threshold filters out partial matches."""
        entries = [
            _make_entry(id="e1", title="how to configure database"),
            _make_entry(id="e2", title="how to configure cache"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)

        # Jaccard("how to configure database", "how to configure cache") = 3/5 = 0.6
        high = nexus_find_duplicates(threshold=0.85)
        assert len(high) == 0, "High threshold should filter partial matches"

        low = nexus_find_duplicates(threshold=0.5)
        assert len(low) >= 1, "Low threshold should catch partial matches"

    @patch(_PATCH_CLIENT)
    def test_find_duplicates_exception_returns_empty(self, mock_gc):
        """Client exception returns empty list gracefully."""
        client = _mock_client()
        client.list_entries.side_effect = RuntimeError("connection lost")
        mock_gc.return_value = client
        assert nexus_find_duplicates() == []


# ════════════════════════════════════════════════════════════════════════
#  nexus_merge_duplicates
# ════════════════════════════════════════════════════════════════════════


class TestNexusMergeDuplicates:
    """Tests for duplicate merging."""

    @patch(_PATCH_CLIENT)
    def test_merge_duplicates_dry_run(self, mock_gc):
        """dry_run=True reports duplicates but does not delete."""
        entries = [
            _make_entry(id="e1", title="same exact title"),
            _make_entry(id="e2", title="same exact title"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_merge_duplicates(dry_run=True)
        assert result["dry_run"] is True
        assert result["duplicate_groups"] >= 1
        assert result["merged"] == 0

    @patch(_PATCH_CLIENT)
    def test_merge_duplicates_apply_deletes(self, mock_gc):
        """dry_run=False actually calls delete_entry on duplicates."""
        entries = [
            _make_entry(id="e1", title="same exact title"),
            _make_entry(id="e2", title="same exact title"),
        ]
        client = _mock_client(entries=entries)
        mock_gc.return_value = client
        result = nexus_merge_duplicates(dry_run=False)
        assert result["merged"] >= 1
        client.delete_entry.assert_called()

    @patch(_PATCH_CLIENT)
    def test_merge_duplicates_no_groups(self, mock_gc):
        """No duplicates → merged=0 regardless of dry_run."""
        entries = [_make_entry(id="e1", title="unique")]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_merge_duplicates(dry_run=False)
        assert result["merged"] == 0
        assert result["duplicate_groups"] == 0


# ════════════════════════════════════════════════════════════════════════
#  nexus_score_entries — quality scoring via NexusClient
# ════════════════════════════════════════════════════════════════════════


class TestNexusScoreEntries:
    """Tests for the entry quality scorer."""

    @patch(_PATCH_CLIENT)
    def test_score_entries_distribution(self, mock_gc):
        """Mock entries produce correct high/medium/low distribution."""
        entries = [
            # High quality: has everything
            _make_entry(id="e1", title="Complete Entry", content="x" * 100,
                        tags=["t1"], category="arch", content_type="note"),
            # Medium quality: partial fields
            _make_entry(id="e2", title="Partial", content="x" * 30,
                        tags=[], category="", content_type="note"),
            # Low quality: nearly empty
            {"id": "e3", "title": "", "content": "", "tags": [], "category": "",
             "content_type": ""},
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_score_entries()

        assert result["total_scored"] == 3
        assert result["distribution"]["high"] >= 1
        assert result["distribution"]["low"] >= 1

    @patch(_PATCH_CLIENT)
    def test_score_entries_avg_quality(self, mock_gc):
        """Average quality is computed across all scored entries."""
        entries = [
            _make_entry(id="e1", title="Good Entry", content="x" * 200,
                        tags=["a"], category="arch", content_type="note"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_score_entries()
        assert result["avg_quality"] > 0.0
        assert result["total_scored"] == 1

    @patch(_PATCH_CLIENT)
    def test_score_entries_low_quality_flagging(self, mock_gc):
        """Entries below min_quality threshold appear in low_quality_entries."""
        entries = [
            {"id": "e-bad", "title": "", "content": "", "tags": [],
             "category": "", "content_type": ""},
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_score_entries(min_quality=0.3)
        assert result["low_quality_count"] >= 1
        assert any(e["id"] == "e-bad" for e in result["low_quality_entries"])

    @patch(_PATCH_CLIENT)
    def test_score_entries_empty_returns_defaults(self, mock_gc):
        """No entries → zero counts."""
        mock_gc.return_value = _mock_client(entries=[])
        result = nexus_score_entries()
        assert result["total_scored"] == 0
        assert result["avg_quality"] == 0.0

    @patch(_PATCH_CLIENT)
    def test_score_entries_exception_returns_defaults(self, mock_gc):
        """Client exception returns safe default dict."""
        client = _mock_client()
        client.list_entries.side_effect = RuntimeError("boom")
        mock_gc.return_value = client
        result = nexus_score_entries()
        assert result["total_scored"] == 0


# ════════════════════════════════════════════════════════════════════════
#  nexus_full_maintenance — orchestrates all tasks
# ════════════════════════════════════════════════════════════════════════


class TestNexusFullMaintenance:
    """Tests for the combined maintenance runner."""

    @patch(_PATCH_CLIENT)
    def test_full_maintenance_combines_reports(self, mock_gc):
        """Full maintenance includes health, dedup, and quality sub-reports."""
        mock_gc.return_value = _mock_client()
        result = nexus_full_maintenance(dry_run=True)

        assert "health" in result
        assert "dedup" in result
        assert "quality" in result
        assert "summary" in result

    @patch(_PATCH_CLIENT)
    def test_full_maintenance_dry_run_skips_compaction(self, mock_gc):
        """dry_run=True skips session compaction."""
        mock_gc.return_value = _mock_client()
        result = nexus_full_maintenance(dry_run=True)
        assert "compact" not in result

    @patch(_PATCH_CLIENT)
    def test_full_maintenance_apply_includes_compaction(self, mock_gc):
        """dry_run=False includes compaction in the report."""
        mock_gc.return_value = _mock_client()
        result = nexus_full_maintenance(dry_run=False)
        assert "compact" in result

    @patch(_PATCH_CLIENT)
    def test_full_maintenance_summary_structure(self, mock_gc):
        """Summary aggregates key metrics from sub-reports."""
        mock_gc.return_value = _mock_client()
        result = nexus_full_maintenance(dry_run=True)
        summary = result["summary"]
        assert "status" in summary
        assert "total_entries" in summary
        assert "duplicates_found" in summary
        assert "low_quality" in summary
        assert "avg_quality" in summary
        assert summary["dry_run"] is True


# ════════════════════════════════════════════════════════════════════════
#  nexus_backup / nexus_list_backups / nexus_prune_backups
# ════════════════════════════════════════════════════════════════════════


class TestNexusBackup:
    """Tests for backup, list, and prune functions (use tmp_path for I/O)."""

    @patch(_PATCH_BACKUP_DIR)
    @patch(_PATCH_CLIENT)
    def test_backup_creates_json_file(self, mock_gc, mock_dir, tmp_path):
        """Backup writes a timestamped JSON file with entry data."""
        mock_dir.return_value = tmp_path
        client = _mock_client()
        client.list_by_type.return_value = [
            _make_entry(id="e1", title="Entry One"),
        ]
        client.search.return_value = []
        mock_gc.return_value = client

        result = nexus_backup(label="test")
        assert result["success"] is True
        assert result["entry_count"] >= 1
        assert result["size_bytes"] > 0

        # Verify file exists and is valid JSON
        backup_files = list(tmp_path.glob("nexus_backup_*.json"))
        assert len(backup_files) == 1
        data = json.loads(backup_files[0].read_text(encoding="utf-8"))
        assert data["label"] == "test"
        assert data["entry_count"] >= 1

    @patch(_PATCH_BACKUP_DIR)
    @patch(_PATCH_CLIENT)
    def test_backup_unavailable_returns_error(self, mock_gc, mock_dir, tmp_path):
        """Backup with unavailable Nexus returns error dict."""
        mock_dir.return_value = tmp_path
        mock_gc.return_value = _mock_client(available=False)
        result = nexus_backup()
        assert result["success"] is False
        assert "error" in result

    @patch(_PATCH_BACKUP_DIR)
    @patch(_PATCH_CLIENT)
    def test_backup_label_in_filename(self, mock_gc, mock_dir, tmp_path):
        """Label appears as suffix in the backup filename."""
        mock_dir.return_value = tmp_path
        client = _mock_client()
        client.list_by_type.return_value = []
        client.search.return_value = []
        mock_gc.return_value = client

        nexus_backup(label="pre-upgrade")
        files = list(tmp_path.glob("*pre-upgrade*"))
        assert len(files) == 1

    @patch(_PATCH_BACKUP_DIR)
    def test_list_backups_finds_files(self, mock_dir, tmp_path):
        """nexus_list_backups discovers all nexus_backup_*.json files."""
        mock_dir.return_value = tmp_path
        # Create a couple of fake backup files
        for i in range(3):
            path = tmp_path / f"nexus_backup_2026010{i}_120000.json"
            path.write_text(json.dumps({
                "entry_count": i * 10,
                "qa_count": i,
                "label": f"backup-{i}",
            }), encoding="utf-8")

        backups = nexus_list_backups()
        assert len(backups) == 3
        assert all("filename" in b for b in backups)
        assert all("size_bytes" in b for b in backups)
        assert all("entry_count" in b for b in backups)

    @patch(_PATCH_BACKUP_DIR)
    def test_list_backups_sorted_reverse_chronological(self, mock_dir, tmp_path):
        """Backups are listed newest-first."""
        mock_dir.return_value = tmp_path
        for ts in ["20260101_000000", "20260301_000000", "20260201_000000"]:
            path = tmp_path / f"nexus_backup_{ts}.json"
            path.write_text(json.dumps({"entry_count": 0, "qa_count": 0}),
                            encoding="utf-8")

        backups = nexus_list_backups()
        filenames = [b["filename"] for b in backups]
        assert filenames[0] > filenames[1] > filenames[2]

    @patch(_PATCH_BACKUP_DIR)
    def test_list_backups_empty_directory(self, mock_dir, tmp_path):
        """No backup files → empty list."""
        mock_dir.return_value = tmp_path
        assert nexus_list_backups() == []

    @patch(_PATCH_BACKUP_DIR)
    def test_prune_backups_deletes_old(self, mock_dir, tmp_path):
        """prune_backups keeps only the most recent N files."""
        mock_dir.return_value = tmp_path
        for i in range(15):
            path = tmp_path / f"nexus_backup_2026{i:04d}01_120000.json"
            path.write_text("{}", encoding="utf-8")

        result = nexus_prune_backups(keep=5)
        assert result["deleted"] == 10
        assert result["remaining"] == 5

        remaining_files = list(tmp_path.glob("nexus_backup_*.json"))
        assert len(remaining_files) == 5

    @patch(_PATCH_BACKUP_DIR)
    def test_prune_backups_fewer_than_keep(self, mock_dir, tmp_path):
        """If fewer than 'keep' backups exist, nothing is deleted."""
        mock_dir.return_value = tmp_path
        for i in range(3):
            path = tmp_path / f"nexus_backup_2026010{i}_120000.json"
            path.write_text("{}", encoding="utf-8")

        result = nexus_prune_backups(keep=10)
        assert result["deleted"] == 0
        assert result["remaining"] == 3


# ════════════════════════════════════════════════════════════════════════
#  quality_report — full quality report via KnowledgeScorer + NexusClient
# ════════════════════════════════════════════════════════════════════════


class TestQualityReport:
    """Tests for the aggregate quality_report function."""

    @patch(_PATCH_CONFIG)
    @patch(_PATCH_CLIENT)
    def test_quality_report_structure(self, mock_gc, _mock_cfg):
        """Report contains expected keys."""
        entries = [_make_entry(id="e1")]
        mock_gc.return_value = _mock_client(entries=entries)
        report = quality_report()
        assert "total_entries" in report
        assert "average_score" in report
        assert "score_distribution" in report
        assert "low_quality" in report
        assert "duplicates" in report
        assert "stale" in report
        assert "recommendations" in report

    @patch(_PATCH_CONFIG)
    @patch(_PATCH_CLIENT)
    def test_quality_report_distribution_buckets(self, mock_gc, _mock_cfg):
        """Score distribution has all four buckets."""
        mock_gc.return_value = _mock_client(entries=[_make_entry()])
        report = quality_report()
        dist = report["score_distribution"]
        assert set(dist.keys()) == {"excellent", "good", "fair", "poor"}

    @patch(_PATCH_CONFIG)
    @patch(_PATCH_CLIENT)
    def test_quality_report_exception_returns_safe_defaults(self, mock_gc, _mock_cfg):
        """Exception from list_entries returns zeroed report."""
        client = _mock_client()
        client.list_entries.side_effect = RuntimeError("boom")
        mock_gc.return_value = client
        report = quality_report()
        assert report["total_entries"] == 0
        assert report["average_score"] == 0.0

    @patch(_PATCH_CONFIG)
    @patch(_PATCH_CLIENT)
    def test_quality_report_identifies_stale_entries(self, mock_gc, _mock_cfg):
        """Old entries appear in the 'stale' list."""
        old = _make_old_entry(age_days=200, id="stale-1")
        mock_gc.return_value = _mock_client(entries=[old])
        report = quality_report()
        assert len(report["stale"]) >= 1

    @patch(_PATCH_CONFIG)
    @patch(_PATCH_CLIENT)
    def test_quality_report_identifies_duplicates(self, mock_gc, _mock_cfg):
        """Duplicate-titled entries appear in the 'duplicates' list."""
        entries = [
            _make_entry(id="e1", title="same title here"),
            _make_entry(id="e2", title="same title here"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        report = quality_report()
        assert len(report["duplicates"]) >= 1

    @patch(_PATCH_CONFIG)
    @patch(_PATCH_CLIENT)
    def test_quality_report_recommendations_healthy(self, mock_gc, _mock_cfg):
        """When quality is high, recommendations say 'healthy'."""
        good_entry = _make_entry(
            title="A very descriptive multi-word title for quality",
            content="# Overview\n\n- Item 1\n- Item 2\n\n" + "x" * 500,
        )
        mock_gc.return_value = _mock_client(entries=[good_entry])
        report = quality_report()
        assert any("healthy" in r.lower() for r in report["recommendations"])
