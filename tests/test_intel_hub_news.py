"""Tests for Intel Hub news ticker API endpoints."""
import os
import pytest
from unittest.mock import patch, MagicMock


def test_news_ticker_endpoint_exists():
    """Test that the /api/news/ticker route exists in intel_hub_scene.py."""
    content = open("content/scenes/intel_hub/intel_hub_scene.py", encoding="utf-8").read()
    assert "/api/news/ticker" in content


def test_news_feed_endpoint_exists():
    """Test that the /api/news/feed route exists in intel_hub_scene.py."""
    content = open("content/scenes/intel_hub/intel_hub_scene.py", encoding="utf-8").read()
    assert "/api/news/feed" in content


def test_news_ticker_html_present():
    """Test that the news ticker HTML is in the template."""
    content = open("content/scenes/intel_hub/templates/intel_hub.html", encoding="utf-8").read()
    assert "news-ticker-container" in content
    assert "news-ticker-items" in content
    assert "INTEL FEED" in content


def test_news_ticker_filter_buttons():
    """Test filter buttons for categories are present."""
    content = open("content/scenes/intel_hub/templates/intel_hub.html", encoding="utf-8").read()
    assert "ticker-filter-btn" in content
    assert "ai_research" in content or "AI" in content


def test_ticker_css_exists():
    """Test that ticker CSS is in intel_hub.css."""
    content = open("content/scenes/intel_hub/static/css/intel_hub.css", encoding="utf-8").read()
    assert "news-ticker" in content


def test_ticker_js_load_logic():
    """Test that ticker JS loading logic is present."""
    html = open("content/scenes/intel_hub/templates/intel_hub.html", encoding="utf-8").read()
    js_dir = "content/scenes/intel_hub/static/js"
    js_content = ""
    if os.path.exists(js_dir):
        for f in os.listdir(js_dir):
            if f.endswith(".js"):
                js_content += open(os.path.join(js_dir, f), encoding="utf-8").read()

    combined = html + js_content
    assert "loadTicker" in combined or "news-ticker" in combined
    assert "/api/news/ticker" in combined


def test_phone_news_feed_endpoint_exists():
    """Test that /api/news/feed exists in phone_scene_v2.py."""
    content = open("content/scenes/phone/phone_scene_v2.py", encoding="utf-8").read()
    assert "/api/news/feed" in content or "news_feed" in content
