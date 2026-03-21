"""Tests for engine.skills.builtin.news_extended_skills — all 10 skills.

Skills use lazy imports (inside try blocks), so all patches target the
original module paths (e.g., 'engine.nexus.news.nexus_feed.get_nexus_feed').
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── Shared mock builders ──────────────────────────────────────────────────────

def _make_feed_item(url: str = "https://example.com/a", category: str = "ai_ml"):
    item = MagicMock()
    item.url = url
    item.title = "Test Article"
    item.summary = "Summary."
    item.category = category
    item.published_at = 1700000000.0
    item.quality_score = 0.8
    item.trend_score = 0.0
    item.to_dict.return_value = {
        "url": url,
        "title": "Test Article",
        "summary": "Summary.",
        "category": category,
        "published_at": 1700000000.0,
        "quality_score": 0.8,
    }
    return item


def _mock_nexus_feed():
    feed = MagicMock()
    feed.get_feed.return_value = [_make_feed_item()]
    feed.get_trending_feed.return_value = [_make_feed_item()]
    feed.get_daily_digest.return_value = {
        "date": "2024-01-15",
        "top_stories": [_make_feed_item().to_dict()],
        "trending_topics": [],
        "categories": {"ai_ml": 5},
        "total_articles": 5,
        "generated_at": 1700000000.0,
    }
    feed.get_interest_profile.return_value = {
        "top_categories": ["ai_ml", "tech"],
        "top_keywords": ["LLM"],
        "read_count": 10,
        "useful_count": 3,
    }
    feed.mark_useful.return_value = None
    return feed


def _mock_scorer():
    scorer = MagicMock()
    bd = MagicMock()
    bd.total = 0.85
    bd.length = 0.9
    bd.reputation = 0.8
    bd.recency = 0.9
    bd.title = 0.7
    bd.category = 0.8
    bd.novelty = 0.95
    scorer.score_detailed.return_value = bd
    return scorer


def _mock_monitor():
    m = MagicMock()
    m.get_health_report.return_value = {
        "total": 5,
        "up": 4,
        "down": 1,
        "slow": 0,
        "flaky": 0,
        "avg_response_ms": 250.0,
    }
    return m


def _mock_distiller():
    d = MagicMock()
    d.get_distillation_stats.return_value = {
        "total": 50,
        "pending": 3,
        "done": 45,
        "failed": 2,
        "window_hours": 24,
    }
    d.get_distillation_queue.return_value = [{"queue_id": 1, "url": "http://x.com", "status": "pending", "quality_score": 0.8}]
    d.distill_batch.return_value = ["entry-1", "entry-2"]
    d.process_pending_queue.return_value = ["entry-3"]
    return d


def _mock_trend_detector():
    det = MagicMock()
    det.get_trending_topics.return_value = [{"topic": "GPT-4", "velocity": 5.0}]
    det.get_trend_report_dict.return_value = {
        "window_hours": 24,
        "trending_topics": [{"topic": "AI", "velocity": 4.0}],
    }
    return det


# ── JSON parse helper ─────────────────────────────────────────────────────────

def _j(result: str) -> dict:
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. get_news_feed
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetNewsFeed:
    PATCH = "engine.nexus.news.nexus_feed.get_nexus_feed"

    def _run(self, **kwargs):
        from engine.skills.builtin.news_extended_skills import get_news_feed
        with patch(self.PATCH, return_value=_mock_nexus_feed()):
            return get_news_feed(**kwargs)

    def test_returns_string(self):
        assert isinstance(self._run(), str)

    def test_valid_json(self):
        data = _j(self._run())
        assert "items" in data

    def test_count_equals_items_len(self):
        data = _j(self._run())
        assert data["count"] == len(data["items"])

    def test_category_defaults_to_all(self):
        data = _j(self._run())
        assert data["category"] == "all"

    def test_category_filter_echoed(self):
        data = _j(self._run(category="ai_ml"))
        assert data["category"] == "ai_ml"

    def test_hours_field(self):
        data = _j(self._run(hours=12))
        assert data["hours"] == 12

    def test_items_have_url(self):
        data = _j(self._run())
        for item in data["items"]:
            assert "url" in item

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import get_news_feed
        with patch(self.PATCH, side_effect=RuntimeError("boom")):
            data = _j(get_news_feed())
        assert "error" in data
        assert data["items"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. get_trending_news
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetTrendingNews:
    FEED_PATCH = "engine.nexus.news.nexus_feed.get_nexus_feed"
    TREND_PATCH = "engine.nexus.news.trend_detector.get_trend_detector"

    def _run(self, **kwargs):
        from engine.skills.builtin.news_extended_skills import get_trending_news
        with patch(self.FEED_PATCH, return_value=_mock_nexus_feed()), \
             patch(self.TREND_PATCH, return_value=_mock_trend_detector()):
            return get_trending_news(**kwargs)

    def test_valid_json(self):
        data = _j(self._run())
        assert "trending_items" in data
        assert "trending_topics" in data

    def test_count_present(self):
        assert "count" in _j(self._run())

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import get_trending_news
        with patch(self.FEED_PATCH, side_effect=RuntimeError("fail")):
            data = _j(get_trending_news())
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 3. get_daily_digest
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetDailyDigest:
    PATCH = "engine.nexus.news.nexus_feed.get_nexus_feed"

    def _run(self):
        from engine.skills.builtin.news_extended_skills import get_daily_digest
        with patch(self.PATCH, return_value=_mock_nexus_feed()):
            return get_daily_digest()

    def test_valid_json(self):
        data = _j(self._run())
        assert isinstance(data, dict)

    def test_has_expected_keys(self):
        data = _j(self._run())
        # Digest keys as returned by get_daily_digest()
        assert "date" in data or "top_stories" in data or "articles" in data

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import get_daily_digest
        with patch(self.PATCH, side_effect=RuntimeError("fail")):
            data = _j(get_daily_digest())
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 4. score_article
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreArticle:
    PATCH = "engine.nexus.news.article_scorer.get_article_scorer"

    def _run(self, **kwargs):
        from engine.skills.builtin.news_extended_skills import score_article
        with patch(self.PATCH, return_value=_mock_scorer()):
            return score_article(**kwargs)

    def test_valid_json(self):
        data = _j(self._run(url="https://arxiv.org/abs/1234"))
        assert "url" in data
        assert "total_score" in data

    def test_breakdown_present(self):
        data = _j(self._run(url="https://arxiv.org/abs/1234"))
        bd = data["breakdown"]
        for key in ("length", "reputation", "recency", "title_quality", "category_relevance", "novelty"):
            assert key in bd

    def test_total_score_is_float(self):
        data = _j(self._run(url="https://arxiv.org/abs/1234"))
        assert isinstance(data["total_score"], float)

    def test_url_echoed(self):
        url = "https://nature.com/article"
        assert _j(self._run(url=url))["url"] == url

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import score_article
        with patch(self.PATCH, side_effect=RuntimeError("crash")):
            data = _j(score_article(url="http://x.com"))
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 5. get_source_health
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSourceHealth:
    PATCH = "engine.nexus.news.source_monitor.get_source_health_monitor"

    def _run(self):
        from engine.skills.builtin.news_extended_skills import get_source_health
        with patch(self.PATCH, return_value=_mock_monitor()):
            return get_source_health()

    def test_valid_json(self):
        data = _j(self._run())
        assert "total" in data

    def test_up_down_present(self):
        data = _j(self._run())
        assert "up" in data
        assert "down" in data

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import get_source_health
        with patch(self.PATCH, side_effect=RuntimeError("x")):
            data = _j(get_source_health())
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 6. get_distillation_stats
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetDistillationStats:
    PATCH = "engine.nexus.news.realtime_distiller.get_realtime_distiller"

    def _run(self, **kwargs):
        from engine.skills.builtin.news_extended_skills import get_distillation_stats
        with patch(self.PATCH, return_value=_mock_distiller()):
            return get_distillation_stats(**kwargs)

    def test_valid_json(self):
        data = _j(self._run())
        assert "total" in data

    def test_pending_in_queue_added(self):
        data = _j(self._run())
        assert "pending_in_queue" in data

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import get_distillation_stats
        with patch(self.PATCH, side_effect=RuntimeError("x")):
            data = _j(get_distillation_stats())
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 7. get_news_trends
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetNewsTrends:
    CLIENT_PATCH = "engine.nexus.client.get_nexus_client"
    TREND_PATCH = "engine.nexus.news.trend_detector.get_trend_detector"

    def _run(self, **kwargs):
        from engine.skills.builtin.news_extended_skills import get_news_trends
        mock_c = MagicMock()
        mock_c.search.return_value = [
            {"title": "AI Paper", "content": "LLMs", "created_at": "2024-01-15T10:00:00Z"},
        ]
        with patch(self.CLIENT_PATCH, return_value=mock_c), \
             patch(self.TREND_PATCH, return_value=_mock_trend_detector()):
            return get_news_trends(**kwargs)

    def test_valid_json(self):
        data = _j(self._run())
        assert "trending_topics" in data

    def test_exception_returns_error_json_with_trending_topics(self):
        from engine.skills.builtin.news_extended_skills import get_news_trends
        with patch(self.CLIENT_PATCH, side_effect=RuntimeError("x")):
            data = _j(get_news_trends())
        assert "error" in data
        assert "trending_topics" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 8. mark_article_useful
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkArticleUseful:
    PATCH = "engine.nexus.news.nexus_feed.get_nexus_feed"

    def _run(self, article_id="http://x.com", useful=True):
        from engine.skills.builtin.news_extended_skills import mark_article_useful
        with patch(self.PATCH, return_value=_mock_nexus_feed()):
            return mark_article_useful(article_id=article_id, useful=useful)

    def test_valid_json(self):
        data = _j(self._run())
        assert "recorded" in data

    def test_useful_true_feedback(self):
        data = _j(self._run(useful=True))
        assert data["feedback"] == "useful"
        assert data["recorded"] is True

    def test_useful_false_feedback(self):
        data = _j(self._run(useful=False))
        assert data["feedback"] == "not_useful"
        assert data["recorded"] is True

    def test_article_id_echoed(self):
        data = _j(self._run(article_id="https://test.com/a"))
        assert data["article_id"] == "https://test.com/a"

    def test_mark_useful_called(self):
        from engine.skills.builtin.news_extended_skills import mark_article_useful
        mock_feed = _mock_nexus_feed()
        with patch(self.PATCH, return_value=mock_feed):
            mark_article_useful(article_id="url", useful=True)
        mock_feed.mark_useful.assert_called_once_with("url", useful=True)

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import mark_article_useful
        with patch(self.PATCH, side_effect=RuntimeError("x")):
            data = _j(mark_article_useful(article_id="url"))
        assert "error" in data
        assert data["recorded"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. get_interest_profile
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetInterestProfile:
    PATCH = "engine.nexus.news.nexus_feed.get_nexus_feed"

    def _run(self):
        from engine.skills.builtin.news_extended_skills import get_interest_profile
        with patch(self.PATCH, return_value=_mock_nexus_feed()):
            return get_interest_profile()

    def test_valid_json(self):
        result = self._run()
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_has_categories(self):
        data = json.loads(self._run())
        assert "top_categories" in data

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import get_interest_profile
        with patch(self.PATCH, side_effect=RuntimeError("x")):
            data = json.loads(get_interest_profile())
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 10. trigger_distillation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTriggerDistillation:
    DIST_PATCH = "engine.nexus.news.realtime_distiller.get_realtime_distiller"
    REG_PATCH = "engine.nexus.news_sources.get_news_registry"

    def _run_no_category(self):
        from engine.skills.builtin.news_extended_skills import trigger_distillation
        with patch(self.DIST_PATCH, return_value=_mock_distiller()):
            return trigger_distillation(category="")

    def _run_with_category(self, cat="ai_ml"):
        from engine.skills.builtin.news_extended_skills import trigger_distillation
        mock_d = _mock_distiller()
        mock_reg = MagicMock()
        mock_art = MagicMock()
        mock_art.url = "http://arxiv.org/123"
        mock_art.title = "Test"
        mock_art.summary = "Sum"
        mock_art.category = cat
        mock_art.source_id = "arxiv"
        mock_art.fetched_at = 1700000000.0
        mock_reg.fetch_all.return_value = [mock_art]
        with patch(self.DIST_PATCH, return_value=mock_d), \
             patch(self.REG_PATCH, return_value=mock_reg):
            return trigger_distillation(category=cat)

    def test_valid_json_no_category(self):
        data = _j(self._run_no_category())
        assert "distilled_count" in data

    def test_category_all_when_empty(self):
        data = _j(self._run_no_category())
        assert data["category"] == "all"

    def test_category_echoed(self):
        data = _j(self._run_with_category("ai_ml"))
        assert data["category"] == "ai_ml"

    def test_distilled_count_is_int(self):
        data = _j(self._run_no_category())
        assert isinstance(data["distilled_count"], int)

    def test_nexus_entry_ids_list(self):
        data = _j(self._run_no_category())
        assert isinstance(data["nexus_entry_ids"], list)

    def test_queue_stats_present(self):
        data = _j(self._run_no_category())
        assert "queue_stats" in data

    def test_process_pending_queue_called_no_category(self):
        from engine.skills.builtin.news_extended_skills import trigger_distillation
        mock_d = _mock_distiller()
        with patch(self.DIST_PATCH, return_value=mock_d):
            trigger_distillation(category="")
        mock_d.process_pending_queue.assert_called_once()

    def test_distill_batch_called_with_category(self):
        from engine.skills.builtin.news_extended_skills import trigger_distillation
        mock_d = _mock_distiller()
        mock_reg = MagicMock()
        mock_reg.fetch_all.return_value = []
        with patch(self.DIST_PATCH, return_value=mock_d), \
             patch(self.REG_PATCH, return_value=mock_reg):
            trigger_distillation(category="ai_ml")
        mock_d.distill_batch.assert_called_once()

    def test_exception_returns_error_json(self):
        from engine.skills.builtin.news_extended_skills import trigger_distillation
        with patch(self.DIST_PATCH, side_effect=RuntimeError("boom")):
            data = _j(trigger_distillation())
        assert "error" in data
        assert data["distilled_count"] == 0
