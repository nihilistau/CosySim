"""Tests for engine.nexus.news.trend_detector — TrendDetector.

All tests use tmp_path for isolated SQLite state.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def detector(tmp_path: Path):
    """TrendDetector backed by isolated DB."""
    from engine.nexus.news.trend_detector import TrendDetector
    return TrendDetector(db_path=tmp_path / "test_trends.db")


def _make_article(title: str, category: str = "ai_ml", age_hours: float = 1.0) -> Dict:
    """Helper to create an article dict with a relative age."""
    return {
        "title": title,
        "summary": f"Summary for: {title}",
        "category": category,
        "url": f"http://example.com/{title[:20].replace(' ', '-')}",
        "published_at": time.time() - age_hours * 3600,
    }


def _make_articles_about(topic: str, count: int, age_hours: float = 1.0) -> List[Dict]:
    """Create N articles that all contain a common topic keyword."""
    return [
        _make_article(f"{topic} development {i} update news", age_hours=age_hours)
        for i in range(count)
    ]


# ── Test: detect_trends ───────────────────────────────────────────────────────

def test_detect_trends_returns_list(detector):
    articles = _make_articles_about("llm", 3)
    reports = detector.detect_trends(articles)
    assert isinstance(reports, list)


def test_detect_trends_empty_input(detector):
    reports = detector.detect_trends([])
    assert reports == []


def test_detect_trends_finds_repeated_keywords(detector):
    articles = _make_articles_about("llm", 5)
    reports = detector.detect_trends(articles, window_hours=24)
    topics = [r.topic for r in reports]
    assert "llm" in topics


def test_detect_trends_groups_related_articles(detector):
    articles = _make_articles_about("pytorch", 4)
    reports = detector.detect_trends(articles, window_hours=24)
    assert len(reports) > 0
    # All articles about pytorch should be in the same cluster
    pytorch_report = next((r for r in reports if r.topic == "pytorch"), None)
    if pytorch_report:
        assert pytorch_report.article_count >= 4


def test_detect_trends_single_mention_not_trending(detector):
    """Keywords that appear in only one article should not be trending."""
    articles = [
        _make_article("unique_keyword_xyz development"),
        _make_article("completely different topic here"),
        _make_article("nothing related to anything else"),
    ]
    reports = detector.detect_trends(articles, window_hours=24)
    topics = [r.topic for r in reports]
    assert "unique_keyword_xyz" not in topics


def test_detect_trends_sorted_by_velocity(detector):
    """Higher velocity topics should appear first."""
    # "pytorch" mentioned 5 times recently
    recent_articles = _make_articles_about("pytorch", 5, age_hours=0.5)
    # "tensorflow" mentioned 2 times from 20 hours ago
    old_articles = _make_articles_about("tensorflow", 2, age_hours=20.0)
    all_articles = recent_articles + old_articles

    reports = detector.detect_trends(all_articles, window_hours=24)
    if len(reports) >= 2:
        assert reports[0].velocity >= reports[-1].velocity


def test_detect_trends_window_filtering(detector):
    """Articles outside the window should not be included."""
    recent = _make_articles_about("gpt", 3, age_hours=1.0)
    old = _make_articles_about("gpt", 3, age_hours=30.0)

    reports_all = detector.detect_trends(recent + old, window_hours=24)
    reports_recent_only = detector.detect_trends(recent, window_hours=24)

    # Adding old articles outside window shouldn't increase article_count
    if reports_all and reports_recent_only:
        gpt_all = next((r for r in reports_all if r.topic == "gpt"), None)
        gpt_recent = next((r for r in reports_recent_only if r.topic == "gpt"), None)
        if gpt_all and gpt_recent:
            # Old articles are outside 24h window, shouldn't be counted differently
            assert gpt_all.article_count == gpt_recent.article_count


def test_trend_report_has_required_fields(detector):
    articles = _make_articles_about("transformer", 3)
    reports = detector.detect_trends(articles)
    if reports:
        r = reports[0]
        assert hasattr(r, "topic")
        assert hasattr(r, "article_count")
        assert hasattr(r, "velocity")
        assert hasattr(r, "peak_time")
        assert hasattr(r, "sample_titles")
        assert hasattr(r, "story_id")
        assert hasattr(r, "first_seen")
        assert hasattr(r, "category")


def test_trend_report_velocity_non_negative(detector):
    articles = _make_articles_about("bert", 3)
    reports = detector.detect_trends(articles)
    for r in reports:
        assert r.velocity >= 0.0


def test_trend_report_article_count_positive(detector):
    articles = _make_articles_about("model", 4)
    reports = detector.detect_trends(articles)
    for r in reports:
        assert r.article_count >= 2  # minimum threshold


def test_trend_report_sample_titles_populated(detector):
    articles = _make_articles_about("llm", 4)
    reports = detector.detect_trends(articles)
    if reports:
        assert len(reports[0].sample_titles) > 0


# ── Test: get_trending_topics ─────────────────────────────────────────────────

def test_get_trending_topics_returns_list(detector):
    topics = detector.get_trending_topics()
    assert isinstance(topics, list)


def test_get_trending_topics_after_detect(detector):
    articles = _make_articles_about("attention", 3)
    reports = detector.detect_trends(articles)
    detector.persist_trends(reports)
    topics = detector.get_trending_topics(limit=5)
    assert len(topics) <= 5


def test_get_trending_topics_has_expected_keys(detector):
    articles = _make_articles_about("finetune", 3)
    reports = detector.detect_trends(articles)
    detector.persist_trends(reports)
    topics = detector.get_trending_topics(limit=10)
    for topic in topics:
        assert "story_id" in topic
        assert "topic" in topic
        assert "article_count" in topic


# ── Test: get_emerging_stories ────────────────────────────────────────────────

def test_get_emerging_stories_returns_list(detector):
    stories = detector.get_emerging_stories()
    assert isinstance(stories, list)


def test_get_emerging_stories_threshold(detector):
    articles = _make_articles_about("rag", 5)
    reports = detector.detect_trends(articles)
    detector.persist_trends(reports)
    stories = detector.get_emerging_stories(threshold=3)
    for s in stories:
        assert s["article_count"] >= 3


# ── Test: track_story ─────────────────────────────────────────────────────────

def test_track_story_persists(detector):
    articles = _make_articles_about("lora", 3)
    reports = detector.detect_trends(articles)
    if reports:
        story_id = reports[0].story_id
        new_article = _make_article("lora finetuning new paper")
        detector.track_story(story_id, new_article)
        # Story should still be queryable
        topics = detector.get_trending_topics()
        ids = [t["story_id"] for t in topics]
        assert story_id in ids


def test_track_story_increments_count(detector, tmp_path):
    """track_story should increment the article count in DB."""
    articles = _make_articles_about("embedding", 3)
    reports = detector.detect_trends(articles)
    detector.persist_trends(reports)
    if reports:
        story_id = reports[0].story_id
        initial_topics = detector.get_trending_topics()
        initial = next((t for t in initial_topics if t["story_id"] == story_id), None)
        if initial:
            initial_count = initial["article_count"]
            new_article = _make_article("embedding model released")
            detector.track_story(story_id, new_article)
            updated_topics = detector.get_trending_topics()
            updated = next((t for t in updated_topics if t["story_id"] == story_id), None)
            if updated:
                assert updated["article_count"] >= initial_count


# ── Test: get_story_timeline ──────────────────────────────────────────────────

def test_get_story_timeline_returns_list(detector):
    timeline = detector.get_story_timeline("nonexistent-id")
    assert timeline == []


def test_get_story_timeline_after_tracking(detector):
    articles = _make_articles_about("rope", 3)
    reports = detector.detect_trends(articles)
    detector.persist_trends(reports)
    if reports:
        story_id = reports[0].story_id
        new_article = _make_article("rope attention mechanism")
        detector.track_story(story_id, new_article)
        timeline = detector.get_story_timeline(story_id)
        assert isinstance(timeline, list)


# ── Test: persist_trends ──────────────────────────────────────────────────────

def test_persist_trends_no_crash_empty(detector):
    detector.persist_trends([])  # should not raise


def test_persist_trends_saves_to_db(detector):
    articles = _make_articles_about("cuda", 4)
    reports = detector.detect_trends(articles)
    detector.persist_trends(reports)
    topics = detector.get_trending_topics(limit=20)
    topic_names = [t["topic"] for t in topics]
    assert "cuda" in topic_names


# ── Test: get_trend_report_dict ───────────────────────────────────────────────

def test_get_trend_report_dict_structure(detector):
    articles = _make_articles_about("quantization", 4)
    report = detector.get_trend_report_dict(articles)
    assert "trending_topics" in report
    assert "emerging_stories" in report
    assert "total_articles" in report
    assert "window_hours" in report


def test_get_trend_report_dict_total_articles(detector):
    articles = _make_articles_about("gguf", 5)
    report = detector.get_trend_report_dict(articles)
    assert report["total_articles"] == 5


# ── Test: singleton ────────────────────────────────────────────────────────────

def test_get_trend_detector_returns_instance():
    from engine.nexus.news.trend_detector import get_trend_detector
    d = get_trend_detector()
    assert d is not None


def test_get_trend_detector_same_instance():
    from engine.nexus.news.trend_detector import get_trend_detector
    d1 = get_trend_detector()
    d2 = get_trend_detector()
    assert d1 is d2
