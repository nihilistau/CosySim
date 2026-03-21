"""Tests for engine.nexus.news.article_scorer — ArticleScorer quality scoring.

All tests use tmp_path to isolate SQLite state. External calls (Nexus,
RSS) are mocked where necessary.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def scorer(tmp_path: Path):
    """ArticleScorer backed by an isolated temporary DB."""
    from engine.nexus.news.article_scorer import ArticleScorer
    return ArticleScorer(db_path=tmp_path / "test_news.db", recent_titles=[])


@pytest.fixture()
def base_article() -> Dict:
    """A minimal valid article dict with a recent timestamp."""
    return {
        "title": "New Open Source LLM Released by Hugging Face Team",
        "summary": " ".join(["word"] * 300),  # ~300 words
        "url": "https://huggingface.co/blog/new-llm",
        "source_name": "hugging face",
        "category": "ai_ml",
        "published_at": time.time() - 3600,  # 1 hour ago
    }


# ── Test: score() returns float in [0.0, 1.0] ──────────────────────────────

def test_score_returns_float(scorer, base_article):
    score = scorer.score(base_article)
    assert isinstance(score, float)


def test_score_in_range(scorer, base_article):
    score = scorer.score(base_article)
    assert 0.0 <= score <= 1.0


def test_score_deterministic(scorer, base_article):
    """Same article + same reference time → same score."""
    now = time.time()
    s1 = scorer.score(base_article, now=now)
    s2 = scorer.score(base_article, now=now)
    assert s1 == s2


def test_score_empty_article(scorer):
    score = scorer.score({})
    assert 0.0 <= score <= 1.0


def test_score_minimal_article(scorer):
    article = {"title": "x", "summary": "", "url": "http://example.com"}
    score = scorer.score(article)
    assert 0.0 <= score <= 1.0


# ── Test: content length scoring ─────────────────────────────────────────────

def test_short_article_penalised(scorer):
    short = {"title": "T", "summary": "five words only here", "url": "http://x.com"}
    long_good = {"title": "T", "summary": " ".join(["word"] * 300), "url": "http://x.com"}
    now = time.time()
    assert scorer.score(short, now=now) < scorer.score(long_good, now=now)


def test_ideal_length_scores_well(scorer):
    article = {"title": "Good Title Here", "summary": " ".join(["word"] * 500), "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.length == 1.0


def test_very_long_article_penalised(scorer):
    article = {"title": "T", "summary": " ".join(["word"] * 15000), "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.length < 0.5


def test_too_short_article_penalised(scorer):
    article = {"title": "T", "summary": "hi", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.length <= 0.2


# ── Test: source reputation scoring ─────────────────────────────────────────

def test_tier1_source_scores_max(scorer, base_article):
    base_article["source_name"] = "Reuters"
    breakdown = scorer.score_detailed(base_article)
    assert breakdown.reputation == 1.0


def test_unknown_source_neutral(scorer):
    article = {"title": "T", "summary": "text", "url": "http://unknown-blog.io/post",
               "source_name": "some unknown blog"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.reputation == 0.5


def test_bbc_scores_high(scorer):
    article = {"title": "T", "summary": "text", "url": "https://bbc.com/news/article",
               "source_name": "BBC News"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.reputation == 1.0


def test_arxiv_in_url_scores_high(scorer):
    article = {"title": "T", "summary": "text", "url": "https://arxiv.org/abs/1234",
               "source_name": "unknown"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.reputation == 1.0


# ── Test: recency scoring ─────────────────────────────────────────────────────

def test_fresh_article_max_recency(scorer):
    now = time.time()
    article = {"title": "T", "summary": "text", "url": "http://x.com",
               "published_at": now - 1800}  # 30 min ago
    breakdown = scorer.score_detailed(article, now=now)
    assert breakdown.recency == 1.0


def test_old_article_zero_recency(scorer):
    now = time.time()
    article = {"title": "T", "summary": "text", "url": "http://x.com",
               "published_at": now - 50 * 3600}  # 50 hours ago
    breakdown = scorer.score_detailed(article, now=now)
    assert breakdown.recency == 0.0


def test_recency_decay(scorer):
    now = time.time()
    article_2h = {"title": "T", "summary": "text", "url": "http://x.com",
                  "published_at": now - 2 * 3600}
    article_24h = {"title": "T", "summary": "text", "url": "http://x.com",
                   "published_at": now - 24 * 3600}
    r2h = scorer.score_detailed(article_2h, now=now).recency
    r24h = scorer.score_detailed(article_24h, now=now).recency
    assert r2h > r24h


def test_no_published_at_neutral(scorer):
    article = {"title": "T", "summary": "text", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.recency == 0.5


def test_iso_string_published_at(scorer):
    now = time.time()
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(now - 1800, tz=timezone.utc)
    article = {"title": "T", "summary": "text", "url": "http://x.com",
               "published_at": dt.isoformat()}
    breakdown = scorer.score_detailed(article, now=now)
    assert breakdown.recency == 1.0


# ── Test: title quality scoring ───────────────────────────────────────────────

def test_good_title_scores_well(scorer):
    article = {"title": "Researchers Develop New Quantum Error Correction Algorithm",
               "summary": "text", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.title >= 0.8


def test_clickbait_title_penalised(scorer):
    article = {"title": "You won't believe what happened to this LLM!",
               "summary": "text", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.title <= 0.15


def test_shocking_clickbait_penalised(scorer):
    article = {"title": "SHOCKING: 10 things developers hate about Python",
               "summary": "text", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.title <= 0.15


def test_numbered_list_clickbait_penalised(scorer):
    article = {"title": "5 things you need to know about AI safety",
               "summary": "text", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.title <= 0.15


def test_empty_title_penalised(scorer):
    article = {"title": "", "summary": "text", "url": "http://x.com"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.title <= 0.25


# ── Test: category relevance scoring ─────────────────────────────────────────

def test_ai_ml_category_scores_max(scorer):
    article = {"title": "T", "summary": "text", "url": "http://x.com", "category": "ai_ml"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.category == 1.0


def test_celebrity_category_scores_low(scorer):
    article = {"title": "T", "summary": "text", "url": "http://x.com", "category": "celebrity"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.category <= 0.15


def test_unknown_category_neutral(scorer):
    article = {"title": "T", "summary": "text", "url": "http://x.com", "category": "unknown_category"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.category == 0.5


# ── Test: score_batch ─────────────────────────────────────────────────────────

def test_score_batch_returns_list(scorer, base_article):
    articles = [base_article, {"title": "x", "url": "http://a.com"}]
    results = scorer.score_batch(articles)
    assert isinstance(results, list)
    assert len(results) == 2


def test_score_batch_sorted_descending(scorer):
    now = time.time()
    high_quality = {
        "title": "Major AI Breakthrough at Stanford University Research Lab",
        "summary": " ".join(["word"] * 500),
        "url": "https://arxiv.org/abs/1234",
        "source_name": "arxiv",
        "category": "ai_ml",
        "published_at": now - 1800,
    }
    low_quality = {
        "title": "5 things you won't believe about cats",
        "summary": "short",
        "url": "http://celebrity.blog/cats",
        "source_name": "unknown",
        "category": "celebrity",
        "published_at": now - 47 * 3600,
    }
    results = scorer.score_batch([low_quality, high_quality], now=now)
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)


def test_score_batch_returns_tuples(scorer, base_article):
    results = scorer.score_batch([base_article])
    assert len(results) == 1
    article, score = results[0]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


# ── Test: get_top ─────────────────────────────────────────────────────────────

def test_get_top_returns_list(scorer, base_article):
    top = scorer.get_top([base_article], n=5)
    assert isinstance(top, list)


def test_get_top_respects_threshold(scorer):
    now = time.time()
    # Article that will have a very low score
    low = {
        "title": "5 reasons you won't believe",
        "summary": "hi",
        "url": "http://celebrity.blog/x",
        "category": "celebrity",
        "published_at": now - 47 * 3600,
    }
    top = scorer.get_top([low], n=10, threshold=0.9, now=now)
    assert len(top) == 0


def test_get_top_respects_n(scorer, base_article):
    articles = [base_article] * 20
    top = scorer.get_top(articles, n=5, threshold=0.0)
    assert len(top) <= 5


def test_get_top_empty_input(scorer):
    top = scorer.get_top([], n=10)
    assert top == []


# ── Test: novelty scoring ─────────────────────────────────────────────────────

def test_novelty_no_history_returns_high(scorer):
    article = {"title": "Brand new topic never seen before", "summary": "text"}
    breakdown = scorer.score_detailed(article, now=time.time())
    assert breakdown.novelty == 1.0


def test_novelty_duplicate_penalised(tmp_path):
    from engine.nexus.news.article_scorer import ArticleScorer
    scorer_with_history = ArticleScorer(
        db_path=tmp_path / "news.db",
        recent_titles=["New Open Source LLM Released by Hugging Face"],
    )
    article = {"title": "New Open Source LLM Released by Hugging Face", "summary": "text"}
    breakdown = scorer_with_history.score_detailed(article, now=time.time())
    assert breakdown.novelty < 0.5


# ── Test: DB operations ────────────────────────────────────────────────────────

def test_db_created_on_init(tmp_path):
    from engine.nexus.news.article_scorer import ArticleScorer
    db_path = tmp_path / "news.db"
    ArticleScorer(db_path=db_path)
    assert db_path.exists()


def test_save_score_doesnt_crash(scorer):
    scorer.save_score("http://example.com/article", 0.75)


# ── Test: singleton ────────────────────────────────────────────────────────────

def test_get_article_scorer_returns_instance():
    from engine.nexus.news.article_scorer import get_article_scorer
    scorer = get_article_scorer()
    assert scorer is not None


def test_get_article_scorer_same_instance():
    from engine.nexus.news.article_scorer import get_article_scorer
    s1 = get_article_scorer()
    s2 = get_article_scorer()
    assert s1 is s2
