"""Tests for engine.nexus.session_distillation — Session → NLM pipeline."""
from __future__ import annotations

import json
import urllib.error
from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import pytest

from engine.nexus.session_distillation import (
    DISTILLATION_QUESTIONS,
    SESSION_HISTORY_NOTEBOOK,
    _ask_distillation_questions,
    _build_digest,
    _fetch_session_history,
    _find_session_history_notebook,
    _store_qa_pairs,
    _upload_digest_to_notebook,
    run_distillation,
    run_session_distillation,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Block all real HTTP calls."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        MagicMock(side_effect=urllib.error.URLError("offline")),
    )


@pytest.fixture
def sample_history_entries() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Session abc: Added caching layer",
            "content": "# Session abc\nDate: 2026-01-01\nBranch: main\n\n## Checkpoints\n...",
            "category": "copilot-history",
            "created_at": "2026-01-01T10:00:00Z",
        },
        {
            "title": "Session def: NLM proxy fix",
            "content": "# Session def\nDate: 2026-01-02\nBranch: main\n\n## Checkpoints\n...",
            "category": "copilot-history",
            "created_at": "2026-01-02T10:00:00Z",
        },
    ]


# ──── DISTILLATION_QUESTIONS ──────────────────────────────────────────────────


class TestDistillationQuestions:
    def test_has_twelve_or_more_questions(self) -> None:
        """Module defines at least 12 distillation questions."""
        assert len(DISTILLATION_QUESTIONS) >= 12

    def test_all_questions_are_strings(self) -> None:
        """All questions are non-empty strings."""
        for q in DISTILLATION_QUESTIONS:
            assert isinstance(q, str)
            assert len(q) > 10

    def test_questions_end_with_question_mark(self) -> None:
        """Most questions end with a question mark."""
        with_qmark = sum(1 for q in DISTILLATION_QUESTIONS if q.strip().endswith("?"))
        assert with_qmark >= len(DISTILLATION_QUESTIONS) // 2


# ──── _fetch_session_history ──────────────────────────────────────────────────


class TestFetchSessionHistory:
    def test_returns_empty_on_nexus_failure(self) -> None:
        """Returns empty list when Nexus is unreachable."""
        result = _fetch_session_history(days=7)
        assert result == []

    def test_parses_nexus_results(self) -> None:
        """Parses entries from Nexus search response."""
        mock_response = {
            "results": [
                {"title": "Session abc", "content": "...", "created_at": "2099-01-01T00:00:00Z"}
            ]
        }
        with patch(
            "engine.nexus.session_distillation._nexus_get",
            return_value=mock_response,
        ):
            result = _fetch_session_history(days=365)
        assert len(result) == 1
        assert result[0]["title"] == "Session abc"

    def test_filters_stale_entries(self) -> None:
        """Entries older than the cutoff are excluded."""
        mock_response = {
            "results": [
                {"title": "Old session", "content": "...", "created_at": "2000-01-01T00:00:00Z"},
                {"title": "New session", "content": "...", "created_at": "2099-12-01T00:00:00Z"},
            ]
        }
        with patch(
            "engine.nexus.session_distillation._nexus_get",
            return_value=mock_response,
        ):
            result = _fetch_session_history(days=7)
        # Only the future-dated entry passes the filter
        titles = [e["title"] for e in result]
        assert "New session" in titles
        assert "Old session" not in titles


# ──── _build_digest ───────────────────────────────────────────────────────────


class TestBuildDigest:
    def test_includes_header(
        self, sample_history_entries: List[Dict]
    ) -> None:
        """Digest includes the CosySim header."""
        digest = _build_digest(sample_history_entries)
        assert "CosySim Session History Digest" in digest

    def test_includes_session_count(
        self, sample_history_entries: List[Dict]
    ) -> None:
        """Digest includes session count."""
        digest = _build_digest(sample_history_entries, days=7)
        assert "2" in digest  # 2 sessions

    def test_includes_session_content(
        self, sample_history_entries: List[Dict]
    ) -> None:
        """Digest includes content from each session entry."""
        digest = _build_digest(sample_history_entries)
        assert "Added caching layer" in digest
        assert "NLM proxy fix" in digest

    def test_empty_entries_message(self) -> None:
        """Digest with no entries includes empty-message text."""
        digest = _build_digest([])
        assert "No session history entries found" in digest

    def test_returns_string(self, sample_history_entries: List[Dict]) -> None:
        """Returns a non-empty string."""
        digest = _build_digest(sample_history_entries)
        assert isinstance(digest, str)
        assert len(digest) > 100


# ──── _find_session_history_notebook ─────────────────────────────────────────


class TestFindSessionHistoryNotebook:
    def test_returns_none_when_nlm_offline(self) -> None:
        """Returns None when NLM proxy is unreachable."""
        result = _find_session_history_notebook()
        assert result is None

    def test_finds_notebook_by_name(self) -> None:
        """Finds notebook matching 'session history' in name."""
        mock_nbs = [
            {"id": "nb-001", "name": "CosySim Architecture"},
            {"id": "nb-002", "name": "Copilot Session History"},
        ]
        with patch("engine.nexus.session_distillation._nlm_get", return_value=mock_nbs):
            result = _find_session_history_notebook()
        assert result == "nb-002"

    def test_returns_none_if_not_found(self) -> None:
        """Returns None if no matching notebook exists."""
        mock_nbs = [
            {"id": "nb-001", "name": "Architecture"},
            {"id": "nb-002", "name": "News Feed"},
        ]
        with patch("engine.nexus.session_distillation._nlm_get", return_value=mock_nbs):
            result = _find_session_history_notebook()
        assert result is None


# ──── _upload_digest_to_notebook ─────────────────────────────────────────────


class TestUploadDigestToNotebook:
    def test_returns_source_id_on_success(self) -> None:
        """Returns source ID when NLM responds with id."""
        with patch(
            "engine.nexus.session_distillation._nlm_post",
            return_value={"id": "src-xyz", "status": "ok"},
        ):
            result = _upload_digest_to_notebook("nb-001", "Some digest text")
        assert result == "src-xyz"

    def test_returns_none_on_failure(self) -> None:
        """Returns None when NLM POST fails."""
        with patch("engine.nexus.session_distillation._nlm_post", return_value=None):
            result = _upload_digest_to_notebook("nb-001", "Some digest text")
        assert result is None

    def test_truncates_long_digest(self) -> None:
        """Digest is truncated to 50,000 chars before upload."""
        long_digest = "A" * 100_000
        captured = {}

        def capture_post(path, data, **_):
            captured["content"] = data.get("content", "")
            return {"id": "src-1"}

        with patch(
            "engine.nexus.session_distillation._nlm_post",
            side_effect=capture_post,
        ):
            _upload_digest_to_notebook("nb-001", long_digest)

        assert len(captured["content"]) == 50_000

    def test_sends_text_type(self) -> None:
        """Upload uses type='text' in the POST payload."""
        captured_data: Dict = {}

        def capture(path, data, **_):
            captured_data.update(data)
            return {"id": "src-1"}

        with patch("engine.nexus.session_distillation._nlm_post", side_effect=capture):
            _upload_digest_to_notebook("nb-001", "Digest text")

        assert captured_data.get("type") == "text"


# ──── _ask_distillation_questions ─────────────────────────────────────────────


class TestAskDistillationQuestions:
    def test_returns_empty_when_nlm_offline(self) -> None:
        """Returns empty list when NLM proxy is down."""
        with patch("engine.nexus.session_distillation._nlm_post", return_value=None):
            result = _ask_distillation_questions("nb-001")
        assert result == []

    def test_parses_qa_pairs(self) -> None:
        """Parses Q&A pairs from NLM batch chat response."""
        mock_resp = {
            "results": [
                {"question": "What decisions?", "answer": "We decided to use Redis for caching."},
                {"question": "What bugs?", "answer": "Fixed the session sync timeout issue."},
            ]
        }
        with patch(
            "engine.nexus.session_distillation._nlm_post",
            return_value=mock_resp,
        ):
            result = _ask_distillation_questions("nb-001")
        assert len(result) == 2
        assert result[0]["question"] == "What decisions?"
        assert "Redis" in result[0]["answer"]

    def test_filters_short_answers(self) -> None:
        """Q&A pairs with answers shorter than 20 chars are filtered out."""
        mock_resp = {
            "results": [
                {"question": "Q1?", "answer": "Yes."},  # too short
                {"question": "Q2?", "answer": "We used Redis because it provides atomic operations."},
            ]
        }
        with patch(
            "engine.nexus.session_distillation._nlm_post",
            return_value=mock_resp,
        ):
            result = _ask_distillation_questions("nb-001")
        assert len(result) == 1
        assert result[0]["question"] == "Q2?"

    def test_uses_default_questions(self) -> None:
        """Default DISTILLATION_QUESTIONS are used when none provided."""
        with patch(
            "engine.nexus.session_distillation._nlm_post",
            return_value={"results": []},
        ) as mock_post:
            _ask_distillation_questions("nb-001")
        call_data = mock_post.call_args[0][1]
        assert call_data["questions"] == DISTILLATION_QUESTIONS

    def test_uses_custom_questions(self) -> None:
        """Custom questions override the default set."""
        custom_qs = ["Q_custom?"]
        with patch(
            "engine.nexus.session_distillation._nlm_post",
            return_value={"results": []},
        ) as mock_post:
            _ask_distillation_questions("nb-001", questions=custom_qs)
        call_data = mock_post.call_args[0][1]
        assert call_data["questions"] == custom_qs


# ──── _store_qa_pairs ─────────────────────────────────────────────────────────


class TestStoreQAPairs:
    def test_stores_via_qa_endpoint(self) -> None:
        """Q&A pairs are stored via the /qa endpoint first."""
        qa_pairs = [{"question": "Q1?", "answer": "Answer 1 which is long enough."}]
        with patch(
            "engine.nexus.session_distillation._nexus_post",
            return_value={"id": 1},
        ) as mock_post:
            count = _store_qa_pairs(qa_pairs)
        assert count == 1
        mock_post.assert_called_once()
        assert mock_post.call_args[0][0] == "/qa"

    def test_fallback_to_entry_on_qa_failure(self) -> None:
        """Falls back to /entries endpoint when /qa POST fails."""
        qa_pairs = [{"question": "Q?", "answer": "Answer that is long enough to store."}]
        call_paths: List[str] = []

        def fake_post(path, data, **_):
            call_paths.append(path)
            if path == "/qa":
                return None  # fail
            return {"id": 2}

        with patch("engine.nexus.session_distillation._nexus_post", side_effect=fake_post):
            count = _store_qa_pairs(qa_pairs)

        assert count == 1
        assert "/qa" in call_paths
        assert "/entries" in call_paths

    def test_returns_zero_on_empty_input(self) -> None:
        """Returns 0 for empty Q&A list."""
        count = _store_qa_pairs([])
        assert count == 0

    def test_correct_category(self) -> None:
        """Q&A entries use copilot-decisions category."""
        qa_pairs = [{"question": "Q?", "answer": "An answer that is definitely long enough."}]
        captured: Dict = {}

        def fake_post(path, data, **_):
            captured.update(data)
            return {"id": 1}

        with patch("engine.nexus.session_distillation._nexus_post", side_effect=fake_post):
            _store_qa_pairs(qa_pairs)

        assert captured.get("category") == "copilot-decisions"


# ──── run_distillation ────────────────────────────────────────────────────────


class TestRunDistillation:
    def test_returns_stats_dict(self) -> None:
        """Always returns a dict with expected keys."""
        result = run_distillation(days=7)
        assert isinstance(result, dict)
        assert "run_at" in result
        assert "history_entries" in result or "error" in result

    def test_returns_error_when_nlm_offline(self) -> None:
        """Returns error key when NLM proxy unavailable."""
        with (
            patch("engine.nexus.session_distillation._find_session_history_notebook",
                  return_value=None),
            patch("engine.nexus.session_distillation._nlm_post", return_value=None),
        ):
            result = run_distillation(days=7)
        assert "error" in result

    def test_full_pipeline(self) -> None:
        """End-to-end pipeline with all steps mocked."""
        with (
            patch(
                "engine.nexus.session_distillation._find_session_history_notebook",
                return_value="nb-session",
            ),
            patch(
                "engine.nexus.session_distillation._fetch_session_history",
                return_value=[{"title": "S1", "content": "Content 1"}],
            ),
            patch(
                "engine.nexus.session_distillation._upload_digest_to_notebook",
                return_value="src-001",
            ),
            patch(
                "engine.nexus.session_distillation._ask_distillation_questions",
                return_value=[{"question": "Q?", "answer": "A meaningful answer."}],
            ),
            patch(
                "engine.nexus.session_distillation._store_qa_pairs",
                return_value=1,
            ),
            patch("engine.nexus.session_distillation._save_state"),
            patch("engine.nexus.session_distillation._load_state",
                  return_value={"last_run": None, "last_notebook_id": None,
                                "last_source_id": None, "total_qa_stored": 0}),
        ):
            result = run_distillation(days=7)

        assert result["notebook_id"] == "nb-session"
        assert result["history_entries"] == 1
        assert result["source_id"] == "src-001"
        assert result["qa_pairs"] == 1
        assert result["qa_stored"] == 1

    def test_upload_only_skips_distillation(self) -> None:
        """upload_only=True skips distillation questions."""
        with (
            patch("engine.nexus.session_distillation._find_session_history_notebook",
                  return_value="nb-session"),
            patch("engine.nexus.session_distillation._fetch_session_history",
                  return_value=[]),
            patch("engine.nexus.session_distillation._upload_digest_to_notebook",
                  return_value="src-001"),
            patch("engine.nexus.session_distillation._ask_distillation_questions") as mock_ask,
            patch("engine.nexus.session_distillation._save_state"),
            patch("engine.nexus.session_distillation._load_state",
                  return_value={"last_run": None, "last_notebook_id": None,
                                "last_source_id": None, "total_qa_stored": 0}),
        ):
            result = run_distillation(days=7, upload_only=True)

        mock_ask.assert_not_called()
        assert result.get("qa_pairs", 0) == 0

    def test_distill_only_skips_upload(self) -> None:
        """distill_only=True skips fetching history and uploading digest."""
        with (
            patch("engine.nexus.session_distillation._fetch_session_history") as mock_fetch,
            patch("engine.nexus.session_distillation._upload_digest_to_notebook") as mock_upload,
            patch(
                "engine.nexus.session_distillation._ask_distillation_questions",
                return_value=[{"question": "Q?", "answer": "A meaningful long enough answer."}],
            ),
            patch("engine.nexus.session_distillation._store_qa_pairs", return_value=1),
            patch("engine.nexus.session_distillation._save_state"),
            patch(
                "engine.nexus.session_distillation._load_state",
                return_value={"last_run": None, "last_notebook_id": "nb-existing",
                              "last_source_id": None, "total_qa_stored": 0},
            ),
        ):
            result = run_distillation(days=7, distill_only=True)

        mock_fetch.assert_not_called()
        mock_upload.assert_not_called()
        assert result["qa_stored"] == 1


# ──── run_session_distillation ────────────────────────────────────────────────


class TestRunSessionDistillation:
    def test_scheduler_callback(self) -> None:
        """Scheduler callback calls run_distillation with days=7."""
        with patch(
            "engine.nexus.session_distillation.run_distillation",
            return_value={"qa_stored": 5, "run_at": "x"},
        ) as mock_run:
            result = run_session_distillation()
        mock_run.assert_called_once_with(days=7)
        assert result["qa_stored"] == 5
