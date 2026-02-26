"""Tests for engine.nexus.self_maintenance — Nexus knowledge base health and quality management."""
from __future__ import annotations

import time
from collections import defaultdict
from unittest.mock import MagicMock, patch, call

import pytest

from engine.nexus.self_maintenance import (
    _title_similarity,
    nexus_compact_sessions,
    nexus_find_duplicates,
    nexus_full_maintenance,
    nexus_health_report,
    nexus_merge_duplicates,
    nexus_score_entries,
)

# Patch target — _get_client imports get_nexus_client lazily
_PATCH_CLIENT = "engine.nexus.self_maintenance._get_client"


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_entry(
    id: str = "e1",
    title: str = "Test Entry",
    content: str = "A" * 60,
    tags: list | None = None,
    category: str = "general",
    content_type: str = "note",
) -> dict:
    """Build a minimal entry dict matching what NexusClient.list_entries returns."""
    return {
        "id": id,
        "title": title,
        "content": content,
        "tags": tags or ["tag1"],
        "category": category,
        "content_type": content_type,
    }


def _make_session(
    id: str = "s1",
    created_at: str = "2024-01-01T00:00:00Z",
    summary: str = "Session summary",
    project: str = "CosySim",
) -> dict:
    return {
        "id": id,
        "created_at": created_at,
        "summary": summary,
        "project": project,
    }


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
    client.delete_entry.return_value = True
    client.add_entry.return_value = "new-entry-id"
    return client


# ════════════════════════════════════════════════════════════════════════
#  _title_similarity — Jaccard similarity (pure function, no mocking)
# ════════════════════════════════════════════════════════════════════════


class TestTitleSimilarity:
    """Tests for the Jaccard word-set similarity helper."""

    def test_identical_strings_return_one(self):
        assert _title_similarity("hello world", "hello world") == 1.0

    def test_completely_different_return_zero(self):
        assert _title_similarity("alpha beta", "gamma delta") == 0.0

    def test_partial_overlap(self):
        # {"how", "to", "cook"} & {"how", "to", "bake"} = {"how", "to"} / {"how", "to", "cook", "bake"}
        sim = _title_similarity("how to cook", "how to bake")
        assert sim == pytest.approx(0.5)

    def test_empty_first_string(self):
        assert _title_similarity("", "something") == 0.0

    def test_empty_second_string(self):
        assert _title_similarity("something", "") == 0.0

    def test_both_empty(self):
        assert _title_similarity("", "") == 0.0

    def test_single_word_match(self):
        assert _title_similarity("hello", "hello") == 1.0

    def test_single_word_no_match(self):
        assert _title_similarity("hello", "world") == 0.0

    def test_superset_relationship(self):
        # {"a", "b"} & {"a", "b", "c"} = {"a", "b"} / {"a", "b", "c"} = 2/3
        sim = _title_similarity("a b", "a b c")
        assert sim == pytest.approx(2 / 3)

    def test_case_sensitivity(self):
        """_title_similarity itself is case-sensitive; callers lowercase first."""
        assert _title_similarity("Hello", "hello") == 0.0

    def test_whitespace_only_strings(self):
        assert _title_similarity("   ", "   ") == 0.0


# ════════════════════════════════════════════════════════════════════════
#  nexus_health_report
# ════════════════════════════════════════════════════════════════════════


class TestNexusHealthReport:
    """Tests for the health-report generator."""

    @patch(_PATCH_CLIENT)
    def test_offline_when_unavailable(self, mock_gc):
        mock_gc.return_value = _mock_client(available=False)
        report = nexus_health_report()
        assert report["status"] == "offline"
        assert "unreachable" in report["issues"][0].lower()

    @patch(_PATCH_CLIENT)
    def test_error_when_stats_fail(self, mock_gc):
        client = _mock_client()
        client.stats.side_effect = RuntimeError("connection refused")
        mock_gc.return_value = client
        report = nexus_health_report()
        assert report["status"] == "error"
        assert any("Failed to get stats" in i for i in report["issues"])

    @patch(_PATCH_CLIENT)
    def test_healthy_report_structure(self, mock_gc):
        mock_gc.return_value = _mock_client()
        report = nexus_health_report()
        assert report["status"] == "healthy"
        assert "timestamp" in report
        assert report["metrics"]["total_entries"] == 42
        assert report["metrics"]["total_qa"] == 10
        assert report["metrics"]["total_sessions"] == 5

    @patch(_PATCH_CLIENT)
    def test_empty_knowledge_base_flagged(self, mock_gc):
        mock_gc.return_value = _mock_client(stats={
            "total_entries": 0, "total_qa": 0,
            "total_sessions": 0, "total_rules": 0, "total_prompts": 0,
        })
        report = nexus_health_report()
        assert any("empty" in i.lower() for i in report["issues"])
        assert any("seed" in r.lower() for r in report["recommendations"])

    @patch(_PATCH_CLIENT)
    def test_no_qa_recommendation(self, mock_gc):
        mock_gc.return_value = _mock_client(stats={
            "total_entries": 10, "total_qa": 0,
            "total_sessions": 2, "total_rules": 0, "total_prompts": 0,
        })
        report = nexus_health_report()
        assert any("Q&A" in r for r in report["recommendations"])

    @patch(_PATCH_CLIENT)
    def test_duplicate_detection_in_health(self, mock_gc):
        """Entries with duplicate titles produce an issue + recommendation."""
        entries = [
            _make_entry(id="e1", title="Setup Guide"),
            _make_entry(id="e2", title="Setup Guide"),
            _make_entry(id="e3", title="Unique Title"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        report = nexus_health_report()
        assert report["metrics"].get("potential_duplicates", 0) >= 1
        assert any("duplicate" in i.lower() for i in report["issues"])
        assert any("dedup" in r.lower() for r in report["recommendations"])

    @patch(_PATCH_CLIENT)
    def test_duplicate_check_is_case_insensitive(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="Setup Guide"),
            _make_entry(id="e2", title="setup guide"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        report = nexus_health_report()
        assert report["metrics"].get("potential_duplicates", 0) >= 1

    @patch(_PATCH_CLIENT)
    def test_content_type_counts_populated(self, mock_gc):
        client = _mock_client()
        # Content-type loop runs FIRST (note, memory, history, code, document),
        # then list_entries(limit=100) for the duplicate check.
        client.list_entries.side_effect = [
            [_make_entry()],                  # note
            [],                               # memory
            [_make_entry(), _make_entry()],    # history
            [],                               # code
            [],                               # document
            [],                               # duplicate-check (limit=100)
        ]
        mock_gc.return_value = client
        report = nexus_health_report()
        assert report["metrics"]["count_note"] == 1
        assert report["metrics"]["count_history"] == 2

    @patch(_PATCH_CLIENT)
    def test_list_entries_exception_does_not_crash(self, mock_gc):
        """Exceptions in the duplicate-check or content-type loops are swallowed."""
        client = _mock_client()
        client.list_entries.side_effect = RuntimeError("boom")
        mock_gc.return_value = client
        report = nexus_health_report()
        # Should still return a valid report (healthy after stats succeed)
        assert report["status"] == "healthy"


# ════════════════════════════════════════════════════════════════════════
#  nexus_find_duplicates
# ════════════════════════════════════════════════════════════════════════


class TestNexusFindDuplicates:
    """Tests for the deduplication scanner."""

    @patch(_PATCH_CLIENT)
    def test_no_entries_returns_empty(self, mock_gc):
        mock_gc.return_value = _mock_client(entries=[])
        assert nexus_find_duplicates() == []

    @patch(_PATCH_CLIENT)
    def test_no_duplicates_returns_empty(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="Alpha"),
            _make_entry(id="e2", title="Beta"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        assert nexus_find_duplicates() == []

    @patch(_PATCH_CLIENT)
    def test_exact_duplicates_found(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="Setup Guide"),
            _make_entry(id="e2", title="setup guide"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates(threshold=0.85)
        assert len(groups) == 1
        assert groups[0]["original"]["id"] == "e1"
        assert groups[0]["duplicates"][0]["id"] == "e2"
        assert groups[0]["count"] == 2

    @patch(_PATCH_CLIENT)
    def test_threshold_filters_low_similarity(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="how to cook pasta"),
            _make_entry(id="e2", title="how to bake bread"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        # Similarity = 2/6 ≈ 0.33 — below default 0.85
        groups = nexus_find_duplicates(threshold=0.85)
        assert len(groups) == 0

    @patch(_PATCH_CLIENT)
    def test_low_threshold_catches_partial_matches(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="how to cook pasta"),
            _make_entry(id="e2", title="how to bake bread"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates(threshold=0.3)
        assert len(groups) == 1

    @patch(_PATCH_CLIENT)
    def test_entries_without_titles_skipped(self, mock_gc):
        entries = [
            _make_entry(id="e1", title=""),
            _make_entry(id="e2", title="Real Title"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        assert nexus_find_duplicates() == []

    @patch(_PATCH_CLIENT)
    def test_multiple_duplicate_groups(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="Setup Guide"),
            _make_entry(id="e2", title="setup guide"),
            _make_entry(id="e3", title="Deployment Notes"),
            _make_entry(id="e4", title="deployment notes"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates(threshold=0.85)
        assert len(groups) == 2

    @patch(_PATCH_CLIENT)
    def test_list_entries_exception_returns_empty(self, mock_gc):
        client = _mock_client()
        client.list_entries.side_effect = RuntimeError("API error")
        mock_gc.return_value = client
        assert nexus_find_duplicates() == []

    @patch(_PATCH_CLIENT)
    def test_duplicate_similarity_score_recorded(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="identical title"),
            _make_entry(id="e2", title="identical title"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates()
        assert groups[0]["duplicates"][0]["similarity"] == 1.0

    @patch(_PATCH_CLIENT)
    def test_entry_only_grouped_once(self, mock_gc):
        """An entry already marked as a duplicate should not start another group."""
        entries = [
            _make_entry(id="e1", title="same title"),
            _make_entry(id="e2", title="same title"),
            _make_entry(id="e3", title="same title"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        groups = nexus_find_duplicates()
        # e1 is original; e2 and e3 are duplicates of e1 → 1 group
        assert len(groups) == 1
        assert groups[0]["count"] == 3


# ════════════════════════════════════════════════════════════════════════
#  nexus_merge_duplicates
# ════════════════════════════════════════════════════════════════════════


class TestNexusMergeDuplicates:
    """Tests for the merge-duplicates workflow."""

    @patch(_PATCH_CLIENT)
    def test_dry_run_does_not_delete(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="same title"),
            _make_entry(id="e2", title="same title"),
        ]
        client = _mock_client(entries=entries)
        mock_gc.return_value = client
        result = nexus_merge_duplicates(dry_run=True)
        assert result["dry_run"] is True
        assert result["duplicate_groups"] >= 1
        assert result["merged"] == 0
        client.delete_entry.assert_not_called()

    @patch(_PATCH_CLIENT)
    def test_apply_deletes_duplicates(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="same title"),
            _make_entry(id="e2", title="same title"),
        ]
        client = _mock_client(entries=entries)
        mock_gc.return_value = client
        result = nexus_merge_duplicates(dry_run=False)
        assert result["dry_run"] is False
        assert result["merged"] == 1
        client.delete_entry.assert_called_once_with("e2")

    @patch(_PATCH_CLIENT)
    def test_no_duplicates_no_action(self, mock_gc):
        entries = [_make_entry(id="e1", title="unique")]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_merge_duplicates(dry_run=False)
        assert result["duplicate_groups"] == 0
        assert result["merged"] == 0

    @patch(_PATCH_CLIENT)
    def test_delete_failure_is_resilient(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="same"),
            _make_entry(id="e2", title="same"),
            _make_entry(id="e3", title="same"),
        ]
        client = _mock_client(entries=entries)
        client.delete_entry.side_effect = [RuntimeError("fail"), True]
        mock_gc.return_value = client
        result = nexus_merge_duplicates(dry_run=False)
        # One failed, one succeeded
        assert result["merged"] == 1

    @patch(_PATCH_CLIENT)
    def test_groups_capped_at_ten(self, mock_gc):
        """Result includes at most 10 group details for display."""
        # Create 12 distinct duplicate pairs (24 entries)
        entries = []
        for i in range(12):
            entries.append(_make_entry(id=f"a{i}", title=f"title{i} word"))
            entries.append(_make_entry(id=f"b{i}", title=f"title{i} word"))
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_merge_duplicates(dry_run=True)
        assert len(result["groups"]) <= 10

    @patch(_PATCH_CLIENT)
    def test_total_duplicates_count(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="aaa bbb"),
            _make_entry(id="e2", title="aaa bbb"),
            _make_entry(id="e3", title="aaa bbb"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_merge_duplicates(dry_run=True)
        # 1 group with 3 entries → 2 duplicates
        assert result["total_duplicates"] == 2


# ════════════════════════════════════════════════════════════════════════
#  nexus_compact_sessions
# ════════════════════════════════════════════════════════════════════════


class TestNexusCompactSessions:
    """Tests for the session compaction workflow."""

    @patch(_PATCH_CLIENT)
    def test_old_session_compacted(self, mock_gc):
        old_session = _make_session(created_at="2020-01-01T00:00:00Z")
        client = _mock_client(sessions=[old_session])
        mock_gc.return_value = client
        result = nexus_compact_sessions(max_age_days=7)
        assert result["compacted"] == 1
        assert result["skipped"] == 0
        client.add_entry.assert_called_once()
        add_kwargs = client.add_entry.call_args
        assert "Compacted session" in add_kwargs.kwargs.get("title", "") or \
               "Compacted session" in (add_kwargs[0][0] if add_kwargs[0] else "")

    @patch(_PATCH_CLIENT)
    def test_recent_session_skipped(self, mock_gc):
        # Session created 1 second ago — should be skipped with max_age_days=7
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        recent = _make_session(created_at=now_iso)
        mock_gc.return_value = _mock_client(sessions=[recent])
        result = nexus_compact_sessions(max_age_days=7)
        assert result["skipped"] == 1
        assert result["compacted"] == 0

    @patch(_PATCH_CLIENT)
    def test_empty_sessions_list(self, mock_gc):
        mock_gc.return_value = _mock_client(sessions=[])
        result = nexus_compact_sessions()
        assert result == {"compacted": 0, "errors": 0, "skipped": 0}

    @patch(_PATCH_CLIENT)
    def test_list_sessions_failure(self, mock_gc):
        client = _mock_client()
        client.list_sessions.side_effect = RuntimeError("offline")
        mock_gc.return_value = client
        result = nexus_compact_sessions()
        assert result == {"compacted": 0, "errors": 0, "skipped": 0}

    @patch(_PATCH_CLIENT)
    def test_add_entry_failure_counted_as_error(self, mock_gc):
        old_session = _make_session(created_at="2020-01-01T00:00:00Z")
        client = _mock_client(sessions=[old_session])
        client.add_entry.side_effect = RuntimeError("write failed")
        mock_gc.return_value = client
        result = nexus_compact_sessions(max_age_days=7)
        assert result["errors"] == 1
        assert result["compacted"] == 0

    @patch(_PATCH_CLIENT)
    def test_session_without_summary_gets_fallback(self, mock_gc):
        old_session = _make_session(id="abc12345", created_at="2020-06-15T10:00:00Z", summary="")
        client = _mock_client(sessions=[old_session])
        mock_gc.return_value = client
        nexus_compact_sessions(max_age_days=7)
        add_call = client.add_entry.call_args
        content_arg = add_call.kwargs.get("content", add_call[0][1] if len(add_call[0]) > 1 else "")
        assert "abc12345" in content_arg or "2020-06-15" in content_arg

    @patch(_PATCH_CLIENT)
    def test_session_with_invalid_created_at_skipped(self, mock_gc):
        bad_session = _make_session(created_at="not-a-date")
        mock_gc.return_value = _mock_client(sessions=[bad_session])
        result = nexus_compact_sessions()
        # Unparseable date → continue (neither compacted nor skipped nor error)
        assert result["compacted"] == 0

    @patch(_PATCH_CLIENT)
    def test_session_without_created_at_skipped(self, mock_gc):
        session = {"id": "s1", "summary": "test"}  # No created_at key
        mock_gc.return_value = _mock_client(sessions=[session])
        result = nexus_compact_sessions()
        assert result["compacted"] == 0

    @patch(_PATCH_CLIENT)
    def test_compacted_entry_metadata(self, mock_gc):
        """Verify correct content_type, category, tags on the compacted entry."""
        old_session = _make_session(
            id="deadbeef-1234",
            created_at="2020-01-01T00:00:00Z",
            project="MyProject",
        )
        client = _mock_client(sessions=[old_session])
        mock_gc.return_value = client
        nexus_compact_sessions()
        add_kwargs = client.add_entry.call_args.kwargs
        assert add_kwargs["content_type"] == "history"
        assert add_kwargs["category"] == "sessions"
        assert "compacted" in add_kwargs["tags"]
        assert "session" in add_kwargs["tags"]
        assert add_kwargs["created_by"] == "self_maintenance"

    @patch(_PATCH_CLIENT)
    def test_max_age_days_custom(self, mock_gc):
        """A session 2 days old should be compacted with max_age_days=1."""
        from datetime import datetime, timezone, timedelta
        two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        session = _make_session(created_at=two_days_ago)
        mock_gc.return_value = _mock_client(sessions=[session])
        result = nexus_compact_sessions(max_age_days=1)
        assert result["compacted"] == 1

    @patch(_PATCH_CLIENT)
    def test_mixed_old_and_recent_sessions(self, mock_gc):
        from datetime import datetime, timezone, timedelta
        old = _make_session(id="s1", created_at="2020-01-01T00:00:00Z")
        recent_dt = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        recent = _make_session(id="s2", created_at=recent_dt)
        mock_gc.return_value = _mock_client(sessions=[old, recent])
        result = nexus_compact_sessions(max_age_days=7)
        assert result["compacted"] == 1
        assert result["skipped"] == 1


# ════════════════════════════════════════════════════════════════════════
#  nexus_score_entries
# ════════════════════════════════════════════════════════════════════════


class TestNexusScoreEntries:
    """Tests for the quality scoring engine."""

    @patch(_PATCH_CLIENT)
    def test_perfect_entry_scores_one(self, mock_gc):
        entry = _make_entry(
            title="Good Title",
            content="A" * 60,  # >50 chars
            tags=["t1"],
            category="general",
            content_type="note",
        )
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries()
        assert result["total_scored"] == 1
        assert result["avg_quality"] == 1.0
        assert result["distribution"]["high"] == 1

    @patch(_PATCH_CLIENT)
    def test_empty_entry_scores_zero(self, mock_gc):
        entry = {"id": "e1", "title": "", "content": "", "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries()
        assert result["avg_quality"] == 0.0
        assert result["distribution"]["low"] == 1

    @patch(_PATCH_CLIENT)
    def test_title_only_scores_point_two(self, mock_gc):
        entry = {"id": "e1", "title": "Has Title", "content": "", "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries()
        assert result["avg_quality"] == 0.2

    @patch(_PATCH_CLIENT)
    def test_medium_content_bonus(self, mock_gc):
        """Content between 10-50 chars gets 0.15 instead of 0.3."""
        entry = {"id": "e1", "title": "", "content": "A" * 20, "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries()
        assert result["avg_quality"] == 0.15

    @patch(_PATCH_CLIENT)
    def test_short_content_no_bonus(self, mock_gc):
        """Content ≤ 10 chars gets no content score."""
        entry = {"id": "e1", "title": "", "content": "short", "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries()
        assert result["avg_quality"] == 0.0

    @patch(_PATCH_CLIENT)
    def test_low_quality_flagged(self, mock_gc):
        entry = {"id": "e1", "content": "", "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries(min_quality=0.3)
        assert result["low_quality_count"] == 1
        assert result["low_quality_entries"][0]["id"] == "e1"
        # .get("title", "(untitled)") → "(untitled)" when key is absent
        assert result["low_quality_entries"][0]["title"] == "(untitled)"

    @patch(_PATCH_CLIENT)
    def test_high_quality_not_flagged(self, mock_gc):
        entry = _make_entry()  # fully populated → score 1.0
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries(min_quality=0.3)
        assert result["low_quality_count"] == 0

    @patch(_PATCH_CLIENT)
    def test_distribution_buckets(self, mock_gc):
        entries = [
            _make_entry(id="e1"),  # perfect → high (1.0)
            {"id": "e2", "title": "T", "content": "A" * 20, "tags": [], "category": "", "content_type": ""},
            # title(0.2) + medium_content(0.15) = 0.35 → low (<0.4)
            {"id": "e3", "title": "T", "content": "A" * 60, "tags": ["t"], "category": "", "content_type": ""},
            # title(0.2) + content(0.3) + tags(0.2) = 0.7 → high (>=0.7)
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_score_entries()
        assert result["distribution"]["high"] == 2
        assert result["distribution"]["low"] == 1

    @patch(_PATCH_CLIENT)
    def test_medium_bucket(self, mock_gc):
        """Entry with score 0.4 ≤ s < 0.7 → medium."""
        # title(0.2) + content>50(0.3) = 0.5 → medium
        entry = {"id": "e1", "title": "T", "content": "B" * 60, "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries()
        assert result["distribution"]["medium"] == 1

    @patch(_PATCH_CLIENT)
    def test_no_entries_returns_defaults(self, mock_gc):
        mock_gc.return_value = _mock_client(entries=[])
        result = nexus_score_entries()
        assert result["total_scored"] == 0
        assert result["avg_quality"] == 0.0

    @patch(_PATCH_CLIENT)
    def test_list_entries_exception_returns_defaults(self, mock_gc):
        client = _mock_client()
        client.list_entries.side_effect = RuntimeError("boom")
        mock_gc.return_value = client
        result = nexus_score_entries()
        assert result["total_scored"] == 0

    @patch(_PATCH_CLIENT)
    def test_low_quality_entries_capped_at_twenty(self, mock_gc):
        entries = [
            {"id": f"e{i}", "title": "", "content": "", "tags": [], "category": "", "content_type": ""}
            for i in range(30)
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        result = nexus_score_entries(min_quality=0.5)
        assert len(result["low_quality_entries"]) <= 20

    @patch(_PATCH_CLIENT)
    def test_custom_min_quality_threshold(self, mock_gc):
        # Score = 0.2 (title only). With min_quality=0.1 → not flagged.
        entry = {"id": "e1", "title": "T", "content": "", "tags": [], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        result = nexus_score_entries(min_quality=0.1)
        assert result["low_quality_count"] == 0

    @patch(_PATCH_CLIENT)
    def test_all_score_components_contribute(self, mock_gc):
        """Verify each quality factor independently contributes."""
        # Only tags
        entry = {"id": "e1", "title": "", "content": "", "tags": ["x"], "category": "", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        r = nexus_score_entries()
        assert r["avg_quality"] == 0.2  # tags = 0.2

        # Only category
        entry = {"id": "e1", "title": "", "content": "", "tags": [], "category": "general", "content_type": ""}
        mock_gc.return_value = _mock_client(entries=[entry])
        r = nexus_score_entries()
        assert r["avg_quality"] == 0.15

        # Only content_type
        entry = {"id": "e1", "title": "", "content": "", "tags": [], "category": "", "content_type": "note"}
        mock_gc.return_value = _mock_client(entries=[entry])
        r = nexus_score_entries()
        assert r["avg_quality"] == 0.15


# ════════════════════════════════════════════════════════════════════════
#  nexus_full_maintenance
# ════════════════════════════════════════════════════════════════════════


class TestNexusFullMaintenance:
    """Tests for the combined maintenance runner."""

    @patch(_PATCH_CLIENT)
    def test_dry_run_skips_compaction(self, mock_gc):
        mock_gc.return_value = _mock_client()
        report = nexus_full_maintenance(dry_run=True)
        assert "health" in report
        assert "dedup" in report
        assert "quality" in report
        assert "compact" not in report  # skipped in dry_run
        assert report["summary"]["dry_run"] is True

    @patch(_PATCH_CLIENT)
    def test_apply_includes_compaction(self, mock_gc):
        mock_gc.return_value = _mock_client()
        report = nexus_full_maintenance(dry_run=False)
        assert "compact" in report
        assert report["summary"]["dry_run"] is False

    @patch(_PATCH_CLIENT)
    def test_summary_aggregates_results(self, mock_gc):
        entries = [
            _make_entry(id="e1", title="same"),
            _make_entry(id="e2", title="same"),
        ]
        mock_gc.return_value = _mock_client(entries=entries)
        report = nexus_full_maintenance(dry_run=True)
        summary = report["summary"]
        assert summary["status"] == "healthy"
        assert summary["total_entries"] == 42
        assert summary["duplicates_found"] >= 1
        assert "low_quality" in summary
        assert "avg_quality" in summary

    @patch(_PATCH_CLIENT)
    def test_offline_propagates_to_summary(self, mock_gc):
        mock_gc.return_value = _mock_client(available=False)
        report = nexus_full_maintenance(dry_run=True)
        assert report["summary"]["status"] == "offline"

    @patch(_PATCH_CLIENT)
    def test_dedup_dry_run_matches_flag(self, mock_gc):
        """The dry_run flag is passed through to nexus_merge_duplicates."""
        mock_gc.return_value = _mock_client()
        report = nexus_full_maintenance(dry_run=True)
        assert report["dedup"]["dry_run"] is True

        report = nexus_full_maintenance(dry_run=False)
        assert report["dedup"]["dry_run"] is False

    @patch(_PATCH_CLIENT)
    def test_full_report_keys(self, mock_gc):
        mock_gc.return_value = _mock_client()
        report = nexus_full_maintenance(dry_run=True)
        assert set(report.keys()) == {"health", "dedup", "quality", "summary"}
