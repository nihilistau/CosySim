"""Tests for News NLM Pipeline (engine/nexus/news_nlm_pipeline.py).

All NLM and Nexus calls are mocked — no real HTTP or subprocess calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.nexus.news_nlm_pipeline import (
    NewsNLMPipeline,
    get_news_nlm_pipeline,
    DISTILLATION_QUESTIONS,
    _get_week_label,
    _load_state,
    _save_state,
)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def pipeline(tmp_path):
    """Fresh pipeline with mocked state file in tmp_path."""
    p = NewsNLMPipeline()
    p._state = {}
    p._direct_client = None
    p._proxy_client = None
    return p


@pytest.fixture
def mock_direct_client():
    """Mocked NLMDirectClient for notebook creation/upload."""
    client = MagicMock()
    client.create_notebook.return_value = "nb-news-123"
    client.add_source_text.return_value = "src-abc"
    return client


@pytest.fixture
def mock_proxy_client():
    """Mocked NLMClient for batch asking."""
    client = MagicMock()
    client.has_cookies.return_value = True
    client.ask_batch.return_value = [
        {"answer": f"Answer {i}"} for i in range(len(DISTILLATION_QUESTIONS))
    ]
    return client


@pytest.fixture
def mock_nexus():
    n = MagicMock()
    n.search.return_value = [{"content": "Cached digest text"}]
    n.add_qa.return_value = None
    n.add_entry.return_value = None
    return n


@pytest.fixture
def sample_articles():
    articles = []
    for i in range(5):
        a = MagicMock()
        a.title = f"AI News Article {i}"
        a.url = f"https://example.com/news/{i}"
        a.summary = f"Summary of article {i} about AI developments."
        a.score = 0.9 - i * 0.1
        a.category = "ai"
        articles.append(a)
    return articles


# ── Distillation questions ────────────────────────────────────────────────

def test_distillation_questions_count():
    """Pipeline has exactly 10 distillation questions."""
    assert len(DISTILLATION_QUESTIONS) == 10


def test_distillation_questions_are_nonempty():
    """All distillation questions are non-empty strings."""
    for q in DISTILLATION_QUESTIONS:
        assert isinstance(q, str)
        assert len(q) > 10


def test_distillation_questions_cover_key_topics():
    """Questions cover the key news intelligence topics."""
    combined = " ".join(DISTILLATION_QUESTIONS).lower()
    assert "ai" in combined or "machine learning" in combined or "developer" in combined
    assert "risk" in combined or "security" in combined or "threat" in combined
    assert "tool" in combined or "framework" in combined or "library" in combined


# ── Week label ────────────────────────────────────────────────────────────

def test_get_week_label_format():
    """Week label matches YYYY-WNN format."""
    import re
    label = _get_week_label()
    assert re.match(r"^\d{4}-W\d{2}$", label)


# ── State helpers ─────────────────────────────────────────────────────────

def test_load_state_missing_file():
    """_load_state returns empty dict when state file doesn't exist."""
    with patch("engine.nexus.news_nlm_pipeline._STATE_FILE", Path("/nonexistent/state.json")):
        state = _load_state()
    assert state == {}


def test_save_and_load_state(tmp_path):
    """State round-trips through save and load."""
    state_file = tmp_path / "news_state.json"
    with patch("engine.nexus.news_nlm_pipeline._STATE_FILE", state_file):
        _save_state({"news_notebook_2026-W09": "nb-abc"})
        loaded = _load_state()
    assert loaded["news_notebook_2026-W09"] == "nb-abc"


# ── Notebook creation ─────────────────────────────────────────────────────

def test_get_or_create_notebook_reuses_existing(pipeline):
    """Reuses notebook ID from state without calling NLM."""
    week = _get_week_label()
    pipeline._state[f"news_notebook_{week}"] = "nb-existing"

    nb_id = pipeline._get_or_create_notebook()

    assert nb_id == "nb-existing"


def test_get_or_create_notebook_creates_new(pipeline, mock_direct_client):
    """Creates new notebook via NLMDirectClient when none exists for current week."""
    pipeline._direct_client = mock_direct_client
    with patch("engine.nexus.news_nlm_pipeline._save_state"):
        nb_id = pipeline._get_or_create_notebook()

    assert nb_id == "nb-news-123"
    mock_direct_client.create_notebook.assert_called_once()


def test_get_or_create_notebook_returns_none_on_failure(pipeline):
    """Returns None when no NLM client is available."""
    with patch.object(pipeline, "_get_nlm_direct_client", return_value=None):
        nb_id = pipeline._get_or_create_notebook()

    assert nb_id is None


def test_get_or_create_notebook_handles_direct_client_exception(pipeline, mock_direct_client):
    """Returns None when NLMDirectClient raises during creation."""
    mock_direct_client.create_notebook.side_effect = Exception("RPC failed")
    pipeline._direct_client = mock_direct_client

    nb_id = pipeline._get_or_create_notebook()
    assert nb_id is None


# ── Digest building ───────────────────────────────────────────────────────

def test_build_digest_includes_all_articles(pipeline, sample_articles):
    """Digest text includes all article titles."""
    text = pipeline._build_digest_text(sample_articles, max_articles=5)
    for art in sample_articles:
        assert art.title in text


def test_build_digest_respects_max_articles(pipeline, sample_articles):
    """Digest is capped at max_articles."""
    text = pipeline._build_digest_text(sample_articles, max_articles=2)
    assert "AI News Article 0" in text
    assert "AI News Article 1" in text
    # Article 2+ should not appear
    assert "AI News Article 3" not in text


def test_build_digest_has_header(pipeline, sample_articles):
    """Digest has a dated header line."""
    text = pipeline._build_digest_text(sample_articles)
    assert "CosySim Daily News Digest" in text


def test_build_digest_includes_urls(pipeline, sample_articles):
    """Digest includes article URLs."""
    text = pipeline._build_digest_text(sample_articles[:1])
    assert "https://example.com/news/0" in text


# ── Upload ────────────────────────────────────────────────────────────────

def test_upload_digest_success_direct(pipeline, mock_direct_client):
    """Returns True when direct client upload succeeds."""
    pipeline._direct_client = mock_direct_client
    success = pipeline._upload_digest("nb-123", "# Digest\nContent here")

    assert success is True
    mock_direct_client.add_source_text.assert_called_once()


def test_upload_digest_falls_back_to_proxy(pipeline):
    """Falls back to nlm_live_proxy when direct client fails."""
    pipeline._direct_client = None
    mock_cookies = {"SID": "abc"}
    with patch("engine.mcp.nlm_live_proxy.add_text_source", return_value={"source_id": "s1"}) as mock_add, \
         patch("engine.mcp.nlm_live_proxy._load_cookies", return_value=mock_cookies):
        success = pipeline._upload_digest("nb-123", "text")

    assert success is True
    mock_add.assert_called_once()


def test_upload_digest_failure_returns_false(pipeline):
    """Returns False when all upload paths fail."""
    pipeline._direct_client = None
    with patch("engine.mcp.nlm_live_proxy.add_text_source", side_effect=Exception("down")), \
         patch("engine.mcp.nlm_live_proxy._load_cookies", return_value={"SID": "abc"}):
        success = pipeline._upload_digest("nb-123", "text")

    assert success is False


def test_upload_digest_no_clients_returns_false(pipeline):
    """Returns False when no NLM clients are available."""
    with patch.object(pipeline, "_get_nlm_direct_client", return_value=None), \
         patch("engine.mcp.nlm_live_proxy._load_cookies", return_value=None):
        success = pipeline._upload_digest("nb-123", "text")

    assert success is False


# ── Distillation ──────────────────────────────────────────────────────────

def test_run_distillation_returns_qa_pairs(pipeline, mock_proxy_client):
    """Distillation returns Q&A pairs for all questions."""
    pipeline._proxy_client = mock_proxy_client
    pairs = pipeline._run_distillation("nb-123")

    assert len(pairs) == len(DISTILLATION_QUESTIONS)
    assert all("question" in p and "answer" in p for p in pairs)
    mock_proxy_client.ask_batch.assert_called_once()


def test_run_distillation_skips_error_answers(pipeline):
    """Distillation skips pairs where the answer indicates an error."""
    mock_client = MagicMock()
    mock_client.has_cookies.return_value = True
    responses = [{"answer": "error: quota exceeded"}] + [{"answer": "Valid answer"}] * (len(DISTILLATION_QUESTIONS) - 1)
    mock_client.ask_batch.return_value = responses
    pipeline._proxy_client = mock_client

    pairs = pipeline._run_distillation("nb-123")
    assert len(pairs) == len(DISTILLATION_QUESTIONS) - 1


def test_run_distillation_falls_back_to_hybrid(pipeline):
    """Falls back to hybrid when proxy client is unavailable."""
    pipeline._proxy_client = None
    mock_hybrid = MagicMock()
    mock_hybrid.ask_batch.return_value = [
        {"answer": f"Hybrid answer {i}"} for i in range(len(DISTILLATION_QUESTIONS))
    ]
    with patch.object(pipeline, "_get_nlm_proxy_client", return_value=None), \
         patch.object(pipeline, "_get_hybrid", return_value=mock_hybrid):
        pairs = pipeline._run_distillation("nb-123")

    assert len(pairs) == len(DISTILLATION_QUESTIONS)
    mock_hybrid.ask_batch.assert_called_once()


def test_run_distillation_handles_exception(pipeline):
    """Returns empty list when all ask paths raise."""
    pipeline._proxy_client = None
    with patch.object(pipeline, "_get_nlm_proxy_client", return_value=None), \
         patch.object(pipeline, "_get_hybrid", side_effect=Exception("offline")):
        pairs = pipeline._run_distillation("nb-123")

    assert pairs == []


# ── Nexus storage ─────────────────────────────────────────────────────────

def test_store_qa_to_nexus_stores_all(pipeline, mock_nexus):
    """All Q&A pairs are stored."""
    qa_pairs = [
        {"question": "Q1?", "answer": "A1"},
        {"question": "Q2?", "answer": "A2"},
    ]
    with patch("engine.nexus.client.get_nexus_client", return_value=mock_nexus):
        count = pipeline._store_qa_to_nexus(qa_pairs, "2026-03-01")

    assert count == 2
    assert mock_nexus.add_qa.call_count == 2


def test_store_qa_tags_with_date(pipeline, mock_nexus):
    """Stored Q&A questions include the date label."""
    qa_pairs = [{"question": "What happened?", "answer": "Things happened."}]
    with patch("engine.nexus.client.get_nexus_client", return_value=mock_nexus):
        pipeline._store_qa_to_nexus(qa_pairs, "2026-03-01")

    call_args = mock_nexus.add_qa.call_args
    assert "2026-03-01" in call_args[0][0]


def test_store_qa_handles_nexus_failure(pipeline):
    """Gracefully handles Nexus storage failure."""
    with patch("engine.nexus.client.get_nexus_client", side_effect=Exception("nexus down")):
        count = pipeline._store_qa_to_nexus([{"question": "Q?", "answer": "A"}], "2026-03-01")

    assert count == 0


# ── Full pipeline run ─────────────────────────────────────────────────────

def test_run_dry_run_skips_upload(pipeline, sample_articles):
    """Dry run returns digest length without uploading."""
    result = pipeline.run(articles=sample_articles, dry_run=True)
    assert result["dry_run"] is True
    assert "digest_length" in result
    assert result["digest_length"] > 0
    assert result["uploaded"] is False


def test_run_skips_when_notebook_unavailable(pipeline, sample_articles):
    """Returns error when NLM notebook cannot be created."""
    with patch.object(pipeline, "_get_nlm_direct_client", return_value=None):
        result = pipeline.run(articles=sample_articles)

    assert "error" in result
    assert result["uploaded"] is False


def test_run_full_pipeline_success(pipeline, sample_articles, mock_direct_client, mock_proxy_client, mock_nexus):
    """Full pipeline run stores Q&A pairs and consolidated insight."""
    week = _get_week_label()
    pipeline._state[f"news_notebook_{week}"] = "nb-news-123"
    pipeline._direct_client = mock_direct_client
    pipeline._proxy_client = mock_proxy_client

    with patch("engine.nexus.client.get_nexus_client", return_value=mock_nexus), \
         patch("time.sleep"):
        result = pipeline.run(articles=sample_articles)

    assert result["uploaded"] is True
    assert result["qa_count"] == len(DISTILLATION_QUESTIONS)
    assert result["stored"] == len(DISTILLATION_QUESTIONS)
    assert mock_nexus.add_entry.called  # consolidated insight entry


def test_run_skips_distillation_when_upload_fails(pipeline, sample_articles):
    """Distillation is skipped when upload fails."""
    week = _get_week_label()
    pipeline._state[f"news_notebook_{week}"] = "nb-news-123"

    with patch.object(pipeline, "_upload_digest", return_value=False), \
         patch("time.sleep"):
        result = pipeline.run(articles=sample_articles)

    assert result["uploaded"] is False
    assert result["qa_count"] == 0


def test_run_falls_back_to_nexus_digest(pipeline, mock_direct_client, mock_proxy_client, mock_nexus):
    """When no articles provided, reads digest from Nexus."""
    week = _get_week_label()
    pipeline._state[f"news_notebook_{week}"] = "nb-news-123"
    pipeline._direct_client = mock_direct_client
    pipeline._proxy_client = mock_proxy_client
    mock_nexus.search.return_value = [{"content": "# Digest from Nexus\nFull content."}]

    with patch("engine.nexus.client.get_nexus_client", return_value=mock_nexus), \
         patch("time.sleep"):
        result = pipeline.run()  # no articles

    assert result["uploaded"] is True


def test_run_returns_error_when_no_content(pipeline):
    """Returns error when no articles and no Nexus digest found."""
    week = _get_week_label()
    pipeline._state[f"news_notebook_{week}"] = "nb-news-123"

    with patch("engine.nexus.client.get_nexus_client") as mock_nx:
        mock_nx.return_value = MagicMock(search=MagicMock(return_value=[]))
        result = pipeline.run()

    assert "error" in result


# ── Singleton ─────────────────────────────────────────────────────────────

def test_singleton_returns_same_instance():
    """get_news_nlm_pipeline() returns the same instance each call."""
    import engine.nexus.news_nlm_pipeline as mod
    mod._PIPELINE = None
    p1 = get_news_nlm_pipeline()
    p2 = get_news_nlm_pipeline()
    assert p1 is p2
    mod._PIPELINE = None  # cleanup
