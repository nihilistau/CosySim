"""Tests for engine.nexus.news.realtime_distiller — RealtimeDistiller.

All external calls (NLM, Nexus) are mocked. Tests use tmp_path for DB
isolation.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_scorer():
    """ArticleScorer that always returns 0.8."""
    scorer = MagicMock()
    scorer.score.return_value = 0.8
    return scorer


@pytest.fixture()
def low_scorer():
    """ArticleScorer that always returns 0.1 (below threshold)."""
    scorer = MagicMock()
    scorer.score.return_value = 0.1
    return scorer


@pytest.fixture()
def distiller(tmp_path: Path, mock_scorer):
    """RealtimeDistiller with isolated DB and mocked scorer."""
    from engine.nexus.news.realtime_distiller import RealtimeDistiller
    return RealtimeDistiller(
        quality_threshold=0.6,
        db_path=tmp_path / "test_queue.db",
        scorer=mock_scorer,
    )


@pytest.fixture()
def low_threshold_distiller(tmp_path: Path, low_scorer):
    """Distiller that won't process anything (low scorer)."""
    from engine.nexus.news.realtime_distiller import RealtimeDistiller
    return RealtimeDistiller(
        quality_threshold=0.6,
        db_path=tmp_path / "test_queue_low.db",
        scorer=low_scorer,
    )


@pytest.fixture()
def sample_article() -> Dict:
    return {
        "url": "https://arxiv.org/abs/1234",
        "title": "GPT-4 Technical Report: Architecture and Training",
        "summary": "OpenAI presents the technical details of GPT-4.",
        "category": "ai_ml",
        "source_name": "arxiv",
        "published_at": time.time() - 1800,
    }


@pytest.fixture()
def mock_nexus_client():
    client = MagicMock()
    client.add_entry.return_value = {"id": "nexus-entry-abc123"}
    return client


# ── Test: on_articles_stored ──────────────────────────────────────────────────

def test_on_articles_stored_empty_list(distiller):
    distiller.on_articles_stored([])  # should not raise


def test_on_articles_stored_queues_high_quality(distiller, sample_article):
    distiller.on_articles_stored([sample_article])
    queue = distiller.get_distillation_queue()
    assert len(queue) == 1


def test_on_articles_stored_skips_low_quality(low_threshold_distiller, sample_article):
    low_threshold_distiller.on_articles_stored([sample_article])
    queue = low_threshold_distiller.get_distillation_queue()
    assert len(queue) == 0


def test_on_articles_stored_multiple_articles(distiller, sample_article):
    articles = [dict(sample_article, url=f"http://example.com/{i}") for i in range(5)]
    distiller.on_articles_stored(articles)
    queue = distiller.get_distillation_queue()
    assert len(queue) == 5


def test_on_articles_stored_only_above_threshold(tmp_path, sample_article):
    """Mixed scoring: only above-threshold articles get queued."""
    from engine.nexus.news.realtime_distiller import RealtimeDistiller

    call_count = [0]
    scores = [0.8, 0.3, 0.7, 0.4, 0.9]  # 3 above 0.6

    scorer = MagicMock()
    scorer.score.side_effect = lambda a, now=None: scores[call_count[0] % len(scores)]

    def score_side_effect(a, now=None):
        idx = call_count[0]
        call_count[0] += 1
        return scores[idx] if idx < len(scores) else 0.5

    scorer.score.side_effect = score_side_effect

    d = RealtimeDistiller(
        quality_threshold=0.6,
        db_path=tmp_path / "mixed.db",
        scorer=scorer,
    )
    articles = [dict(sample_article, url=f"http://example.com/{i}") for i in range(5)]
    d.on_articles_stored(articles)
    queue = d.get_distillation_queue()
    # Scores: 0.8✓ 0.3✗ 0.7✓ 0.4✗ 0.9✓ → 3 queued
    assert len(queue) == 3


# ── Test: distill_article ─────────────────────────────────────────────────────

def test_distill_article_below_threshold_returns_none(low_threshold_distiller, sample_article):
    result = low_threshold_distiller.distill_article(sample_article)
    assert result is None


@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._get_or_create_notebook", return_value=None)
@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._store_in_nexus")
def test_distill_article_with_fallback(mock_store, mock_notebook, distiller, sample_article):
    mock_store.return_value = "nexus-fallback-id"
    result = distiller.distill_article(sample_article)
    # No notebook → uses fallback answers → store should still be called
    assert mock_store.called


@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._get_or_create_notebook", return_value=None)
@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._store_in_nexus", return_value="entry-abc")
def test_distill_article_returns_entry_id(mock_store, mock_nb, distiller, sample_article):
    result = distiller.distill_article(sample_article)
    assert result == "entry-abc"


@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._get_or_create_notebook", return_value=None)
@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._store_in_nexus", return_value=None)
def test_distill_article_nexus_failure_returns_none(mock_store, mock_nb, distiller, sample_article):
    result = distiller.distill_article(sample_article)
    assert result is None


@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._get_or_create_notebook", side_effect=RuntimeError("NLM down"))
@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller._store_in_nexus", return_value="entry-xyz")
def test_distill_article_nlm_exception_doesnt_crash(mock_store, mock_nb, distiller, sample_article):
    # Even if NLM errors, should not crash the pipeline — returns None gracefully
    result = distiller.distill_article(sample_article)
    assert result is None  # logs warning, returns None without raising


# ── Test: distill_batch ───────────────────────────────────────────────────────

@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller.distill_article")
def test_distill_batch_empty_list(mock_distill, distiller):
    result = distiller.distill_batch([])
    assert result == []
    mock_distill.assert_not_called()


@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller.distill_article", return_value="entry-x")
def test_distill_batch_returns_entry_ids(mock_distill, distiller, sample_article):
    articles = [sample_article, dict(sample_article, url="http://other.com")]
    results = distiller.distill_batch(articles)
    assert len(results) == 2
    assert all(r == "entry-x" for r in results)


@patch("engine.nexus.news.realtime_distiller.RealtimeDistiller.distill_article", return_value=None)
def test_distill_batch_filters_none_results(mock_distill, distiller, sample_article):
    results = distiller.distill_batch([sample_article])
    assert results == []


def test_distill_batch_respects_threshold(low_threshold_distiller, sample_article):
    """Articles below threshold should not be processed."""
    articles = [sample_article] * 3
    results = low_threshold_distiller.distill_batch(articles)
    assert results == []


def test_distill_batch_max_concurrent_respected(tmp_path, mock_scorer, sample_article):
    """distill_batch should cap concurrency at max_concurrent."""
    from engine.nexus.news.realtime_distiller import RealtimeDistiller
    import threading

    call_count = [0]
    active_count = [0]
    max_active = [0]
    lock = threading.Lock()

    def fake_distill(article):
        with lock:
            active_count[0] += 1
            if active_count[0] > max_active[0]:
                max_active[0] = active_count[0]
        time.sleep(0.05)
        with lock:
            active_count[0] -= 1
        return "entry"

    d = RealtimeDistiller(
        quality_threshold=0.5,
        db_path=tmp_path / "concurrent.db",
        scorer=mock_scorer,
    )
    articles = [dict(sample_article, url=f"http://a.com/{i}") for i in range(6)]
    with patch.object(d, "distill_article", side_effect=fake_distill):
        d.distill_batch(articles, max_concurrent=2)

    assert max_active[0] <= 2


# ── Test: get_distillation_queue ──────────────────────────────────────────────

def test_get_distillation_queue_empty(distiller):
    queue = distiller.get_distillation_queue()
    assert queue == []


def test_get_distillation_queue_has_expected_keys(distiller, sample_article):
    distiller.on_articles_stored([sample_article])
    queue = distiller.get_distillation_queue()
    assert len(queue) == 1
    item = queue[0]
    assert "queue_id" in item
    assert "url" in item
    assert "quality_score" in item
    assert "status" in item


# ── Test: get_distillation_stats ──────────────────────────────────────────────

def test_get_distillation_stats_returns_dict(distiller):
    stats = distiller.get_distillation_stats(hours=24)
    assert isinstance(stats, dict)


def test_get_distillation_stats_keys(distiller):
    stats = distiller.get_distillation_stats(hours=24)
    assert "total" in stats
    assert "pending" in stats
    assert "done" in stats
    assert "failed" in stats
    assert "window_hours" in stats


def test_get_distillation_stats_counts_correctly(distiller, sample_article):
    distiller.on_articles_stored([sample_article])
    stats = distiller.get_distillation_stats(hours=24)
    assert stats["pending"] >= 1
    assert stats["total"] >= 1


# ── Test: quality threshold ────────────────────────────────────────────────────

def test_threshold_attribute(distiller):
    assert distiller.quality_threshold == 0.6


def test_custom_threshold(tmp_path, mock_scorer):
    from engine.nexus.news.realtime_distiller import RealtimeDistiller
    d = RealtimeDistiller(quality_threshold=0.9, db_path=tmp_path / "t.db", scorer=mock_scorer)
    assert d.quality_threshold == 0.9


def test_default_threshold():
    from engine.nexus.news.realtime_distiller import RealtimeDistiller
    assert RealtimeDistiller.QUALITY_THRESHOLD == 0.6


# ── Test: singleton ────────────────────────────────────────────────────────────

def test_get_realtime_distiller_returns_instance():
    from engine.nexus.news.realtime_distiller import get_realtime_distiller
    d = get_realtime_distiller()
    assert d is not None


def test_get_realtime_distiller_same_instance():
    from engine.nexus.news.realtime_distiller import get_realtime_distiller
    d1 = get_realtime_distiller()
    d2 = get_realtime_distiller()
    assert d1 is d2
