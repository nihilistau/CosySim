"""Tests for engine.nexus.news.source_monitor — SourceHealthMonitor.

External HTTP calls are mocked. All DB operations use tmp_path.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def monitor(tmp_path: Path):
    """SourceHealthMonitor backed by isolated DB."""
    from engine.nexus.news.source_monitor import SourceHealthMonitor
    return SourceHealthMonitor(db_path=tmp_path / "test_health.db")


@pytest.fixture()
def mock_registry():
    """Mocked news source registry."""
    source = MagicMock()
    source.id = "hn-topstories"
    source.url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    source.category = "ai_ml"
    source.enabled = True

    registry = MagicMock()
    registry.get_source.return_value = source
    registry.list_sources.return_value = [source]
    return registry


# ── Test: check_source HTTP probe ─────────────────────────────────────────────

@patch("engine.nexus.news.source_monitor.SourceHealthMonitor._probe_url")
def test_check_source_up(mock_probe, monitor, mock_registry):
    mock_probe.return_value = {"success": True, "status_code": 200, "duration_ms": 150.0, "error": ""}
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        health = monitor.check_source("hn-topstories")
    assert health.status == "UP"
    assert health.consecutive_failures == 0


@patch("engine.nexus.news.source_monitor.SourceHealthMonitor._probe_url")
def test_check_source_down(mock_probe, monitor, mock_registry):
    mock_probe.return_value = {"success": False, "status_code": 0, "duration_ms": 30000.0, "error": "Connection refused"}
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        health = monitor.check_source("hn-topstories")
    assert health.status in ("DOWN", "FLAKY")
    assert health.consecutive_failures == 1


@patch("engine.nexus.news.source_monitor.SourceHealthMonitor._probe_url")
def test_check_source_slow(mock_probe, monitor, mock_registry):
    mock_probe.return_value = {"success": True, "status_code": 200, "duration_ms": 9000.0, "error": ""}
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        health = monitor.check_source("hn-topstories")
    assert health.status == "SLOW"


@patch("engine.nexus.news.source_monitor.SourceHealthMonitor._probe_url")
def test_check_source_response_time_recorded(mock_probe, monitor, mock_registry):
    mock_probe.return_value = {"success": True, "status_code": 200, "duration_ms": 250.5, "error": ""}
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        health = monitor.check_source("hn-topstories")
    assert health.response_time_ms == 250.5


# ── Test: consecutive failures tracked ────────────────────────────────────────

@patch("engine.nexus.news.source_monitor.SourceHealthMonitor._probe_url")
def test_consecutive_failures_increment(mock_probe, monitor, mock_registry):
    mock_probe.return_value = {"success": False, "status_code": 0, "duration_ms": 100.0, "error": "err"}
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        h1 = monitor.check_source("hn-topstories")
        h2 = monitor.check_source("hn-topstories")
    assert h2.consecutive_failures == 2


@patch("engine.nexus.news.source_monitor.SourceHealthMonitor._probe_url")
def test_consecutive_failures_reset_on_success(mock_probe, monitor, mock_registry):
    # Two failures, then success
    mock_probe.side_effect = [
        {"success": False, "status_code": 0, "duration_ms": 100.0, "error": "err"},
        {"success": False, "status_code": 0, "duration_ms": 100.0, "error": "err"},
        {"success": True, "status_code": 200, "duration_ms": 100.0, "error": ""},
    ]
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        monitor.check_source("hn-topstories")
        monitor.check_source("hn-topstories")
        h3 = monitor.check_source("hn-topstories")
    assert h3.consecutive_failures == 0


# ── Test: disable/re-enable lifecycle ────────────────────────────────────────

def test_disable_source(monitor, mock_registry):
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        monitor.disable_source("hn-topstories", reason="Test disable")
    failing = monitor.get_failing_sources(threshold_failures=0)
    # Disabled source should have updated DB entry
    report = monitor.get_health_report()
    assert isinstance(report, dict)


def test_re_enable_source(monitor, mock_registry):
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        monitor.disable_source("hn-topstories", reason="Test")
        monitor.re_enable_source("hn-topstories")


def test_re_enable_resets_failures(tmp_path, mock_registry):
    from engine.nexus.news.source_monitor import SourceHealthMonitor
    monitor = SourceHealthMonitor(db_path=tmp_path / "h2.db")
    monitor.record_fetch_result("hn-topstories", "http://x.com", 0, False, "err")
    monitor.record_fetch_result("hn-topstories", "http://x.com", 0, False, "err")
    monitor.record_fetch_result("hn-topstories", "http://x.com", 0, False, "err")

    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        monitor.re_enable_source("hn-topstories")

    health = monitor._load_health("hn-topstories")
    assert health is not None
    assert health.consecutive_failures == 0


# ── Test: get_failing_sources ─────────────────────────────────────────────────

def test_get_failing_sources_empty(monitor):
    failing = monitor.get_failing_sources()
    assert failing == []


def test_get_failing_sources_after_failures(monitor):
    monitor.record_fetch_result("test-source", "http://x.com", 0, False, "error1")
    monitor.record_fetch_result("test-source", "http://x.com", 0, False, "error2")
    monitor.record_fetch_result("test-source", "http://x.com", 0, False, "error3")
    failing = monitor.get_failing_sources(threshold_failures=3)
    assert "test-source" in failing


def test_get_failing_sources_below_threshold(monitor):
    monitor.record_fetch_result("marginal-source", "http://y.com", 0, False, "err")
    monitor.record_fetch_result("marginal-source", "http://y.com", 0, False, "err")
    failing = monitor.get_failing_sources(threshold_failures=3)
    assert "marginal-source" not in failing


# ── Test: health report aggregation ──────────────────────────────────────────

def test_get_health_report_structure(monitor):
    report = monitor.get_health_report()
    assert isinstance(report, dict)
    assert "total" in report
    assert "up" in report
    assert "down" in report


def test_get_health_report_empty_db(monitor):
    report = monitor.get_health_report()
    assert report["total"] == 0
    assert report["up"] == 0


def test_get_health_report_after_checks(monitor):
    monitor.record_fetch_result("s1", "http://a.com", 5, True)
    monitor.record_fetch_result("s2", "http://b.com", 0, False, "err")
    report = monitor.get_health_report()
    assert report["total"] == 2
    assert report["up"] >= 1


def test_get_health_report_avg_response_ms(monitor):
    monitor._upsert_health(
        __import__("engine.nexus.news.source_monitor", fromlist=["SourceHealth"]).SourceHealth(
            source_id="x", url="http://x.com", status="UP", response_time_ms=200.0,
            last_checked=time.time(),
        )
    )
    report = monitor.get_health_report()
    assert report["avg_response_ms"] == 200.0


# ── Test: suggest_replacements ────────────────────────────────────────────────

def test_suggest_replacements_returns_list(monitor, mock_registry):
    with patch("engine.nexus.news_sources.get_news_registry", return_value=mock_registry):
        suggestions = monitor.suggest_replacements({"source_id": "bad-source", "category": "ai_ml"})
    assert isinstance(suggestions, list)


# ── Test: record_fetch_result ─────────────────────────────────────────────────

def test_record_fetch_result_success(monitor):
    monitor.record_fetch_result("rss-1", "http://rss.com", 10, True)
    health = monitor._load_health("rss-1")
    assert health is not None
    assert health.consecutive_failures == 0
    assert health.status == "UP"


def test_record_fetch_result_failure(monitor):
    monitor.record_fetch_result("rss-1", "http://rss.com", 0, False, "timeout")
    health = monitor._load_health("rss-1")
    assert health.consecutive_failures == 1


def test_record_fetch_result_avg_articles_updated(monitor):
    monitor.record_fetch_result("rss-1", "http://rss.com", 10, True)
    monitor.record_fetch_result("rss-1", "http://rss.com", 20, True)
    health = monitor._load_health("rss-1")
    assert health.avg_articles_per_fetch > 0


# ── Test: singleton ────────────────────────────────────────────────────────────

def test_get_source_health_monitor_returns_instance():
    from engine.nexus.news.source_monitor import get_source_health_monitor
    m = get_source_health_monitor()
    assert m is not None


def test_get_source_health_monitor_same_instance():
    from engine.nexus.news.source_monitor import get_source_health_monitor
    m1 = get_source_health_monitor()
    m2 = get_source_health_monitor()
    assert m1 is m2
