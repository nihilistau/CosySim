"""Tests for the phone news feed (PhoneDB news methods + scene routes)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def news_db(tmp_path):
    """Create a PhoneDB with news tables in a temp directory."""
    from pathlib import Path
    db_path = tmp_path / "phone_test.db"
    with patch("engine.paths.DB_PHONE", db_path):
        from content.scenes.phone.phone_db import PhoneDB
        db = PhoneDB(db_path)
    return db


@pytest.fixture()
def sample_items():
    """Sample news items for testing."""
    return [
        {
            "id": "news-001",
            "title": "AI Breakthrough in 2025",
            "summary": "Major advances in reasoning",
            "url": "https://example.com/ai",
            "source_id": "tech_news",
            "category": "ai",
            "relevance": 0.9,
            "markup": "<p>AI content</p>",
            "nexus_id": "nx-001",
        },
        {
            "id": "news-002",
            "title": "Python 3.14 Released",
            "summary": "New features in Python",
            "url": "https://example.com/python",
            "source_id": "python_weekly",
            "category": "python",
            "relevance": 0.6,
            "markup": "<p>Python content</p>",
            "nexus_id": "nx-002",
        },
        {
            "id": "news-003",
            "title": "Local LLMs Getting Faster",
            "summary": "Optimization techniques",
            "url": "https://example.com/llm",
            "source_id": "ai_daily",
            "category": "llm",
            "relevance": 0.3,
            "markup": "<p>LLM content</p>",
            "nexus_id": "nx-003",
        },
    ]


def _seed(db, items):
    """Insert sample items into the news table."""
    for item in items:
        db.upsert_news_item(
            item_id=item["id"],
            title=item["title"],
            summary=item["summary"],
            url=item["url"],
            source_id=item["source_id"],
            category=item["category"],
            relevance=item["relevance"],
            markup=item["markup"],
            nexus_id=item.get("nexus_id", ""),
        )


# ── PhoneDB News Methods ──────────────────────────────────────────────


class TestPhoneDBNews:
    """Test the PhoneDB news feed methods."""

    def test_upsert_creates_item(self, news_db, sample_items):
        """Upsert inserts new items."""
        _seed(news_db, sample_items[:1])
        feed = news_db.get_news_feed()
        assert len(feed) == 1
        assert feed[0]["title"] == "AI Breakthrough in 2025"

    def test_upsert_skips_existing(self, news_db, sample_items):
        """Upsert skips existing items (returns False for duplicates)."""
        _seed(news_db, sample_items[:1])
        result = news_db.upsert_news_item(
            item_id="news-001",
            title="AI Breakthrough Updated",
            summary="Updated summary",
            url="https://example.com/ai-v2",
            source_id="tech_news",
            category="ai",
            relevance=0.95,
            markup="<p>updated</p>",
        )
        assert result is False
        feed = news_db.get_news_feed()
        assert len(feed) == 1
        assert feed[0]["title"] == "AI Breakthrough in 2025"

    def test_get_news_feed_ordered(self, news_db, sample_items):
        """Feed returns items in reverse chronological order."""
        _seed(news_db, sample_items)
        feed = news_db.get_news_feed()
        assert len(feed) == 3

    def test_get_news_feed_limit(self, news_db, sample_items):
        """Feed respects limit parameter."""
        _seed(news_db, sample_items)
        feed = news_db.get_news_feed(limit=2)
        assert len(feed) == 2

    def test_get_news_feed_unread_only(self, news_db, sample_items):
        """Feed can filter to unread only."""
        _seed(news_db, sample_items)
        news_db.set_news_read("news-001")
        feed = news_db.get_news_feed(unread_only=True)
        assert len(feed) == 2
        assert all(not item["is_read"] for item in feed)

    def test_get_news_feed_excludes_deleted(self, news_db, sample_items):
        """Feed excludes deleted items by default."""
        _seed(news_db, sample_items)
        news_db.delete_news_item("news-001")
        feed = news_db.get_news_feed()
        assert len(feed) == 2
        assert all(item["id"] != "news-001" for item in feed)

    def test_get_news_stats(self, news_db, sample_items):
        """Stats returns correct counts."""
        _seed(news_db, sample_items)
        stats = news_db.get_news_stats()
        assert stats["total"] == 3
        assert stats["unread"] == 3
        assert stats["liked"] == 0
        assert stats["disliked"] == 0

    def test_set_news_read(self, news_db, sample_items):
        """Mark item as read updates is_read and read_at."""
        _seed(news_db, sample_items[:1])
        news_db.set_news_read("news-001")
        feed = news_db.get_news_feed()
        assert feed[0]["is_read"] == 1
        assert feed[0]["read_at"] is not None

    def test_set_news_feedback_positive(self, news_db, sample_items):
        """Positive feedback sets feedback to 1."""
        _seed(news_db, sample_items[:1])
        news_db.set_news_feedback("news-001", 1)
        stats = news_db.get_news_stats()
        assert stats["liked"] == 1

    def test_set_news_feedback_negative(self, news_db, sample_items):
        """Negative feedback sets feedback to -1."""
        _seed(news_db, sample_items[:1])
        news_db.set_news_feedback("news-001", -1)
        stats = news_db.get_news_stats()
        assert stats["disliked"] == 1

    def test_delete_news_item(self, news_db, sample_items):
        """Delete marks item as deleted (soft delete)."""
        _seed(news_db, sample_items[:1])
        news_db.delete_news_item("news-001")
        stats = news_db.get_news_stats()
        assert stats["total"] == 0

    def test_get_feedback_summary(self, news_db, sample_items):
        """Feedback summary groups by source and category."""
        _seed(news_db, sample_items)
        news_db.set_news_feedback("news-001", 1)
        news_db.set_news_feedback("news-002", -1)
        summary = news_db.get_feedback_summary()
        assert "liked_sources" in summary
        assert "disliked_sources" in summary
        assert "liked_categories" in summary

    def test_stats_after_mixed_operations(self, news_db, sample_items):
        """Stats accurate after read, feedback, and delete operations."""
        _seed(news_db, sample_items)
        news_db.set_news_read("news-001")
        news_db.set_news_feedback("news-001", 1)
        news_db.set_news_feedback("news-002", -1)
        news_db.delete_news_item("news-003")
        stats = news_db.get_news_stats()
        assert stats["total"] == 2
        assert stats["unread"] == 1
        assert stats["liked"] == 1
        assert stats["disliked"] == 1


# ── HA Skills ──────────────────────────────────────────────────────────


class TestHASkills:
    """Test that HA skills are importable and have correct metadata."""

    def test_skills_importable(self):
        """All HA skills can be imported."""
        from engine.skills.builtin import homeassistant_skills  # noqa: F401

    def test_skill_pack_name(self):
        """HA skills use 'homeassistant' pack name."""
        from engine.skills.registry import SKILL_REGISTRY
        ha_tools = SKILL_REGISTRY.get_pack_tools("homeassistant")
        assert len(ha_tools) >= 14, f"Expected ≥14 HA skills, got {len(ha_tools)}"

    def test_ha_connect_skill(self):
        """ha_connect skill calls connect on client."""
        from engine.skills.builtin.homeassistant_skills import ha_connect
        with patch("engine.skills.builtin.homeassistant_skills._ha") as mock_get:
            mock_client = MagicMock()
            mock_client.connect.return_value = {"connected": True}
            mock_get.return_value = mock_client
            result = json.loads(ha_connect())
        assert result["connected"] is True

    def test_ha_list_entities_skill(self):
        """ha_list_entities returns entity list."""
        from engine.skills.builtin.homeassistant_skills import ha_list_entities
        with patch("engine.skills.builtin.homeassistant_skills._ha") as mock_get:
            mock_client = MagicMock()
            mock_client.list_entities.return_value = [
                {"entity_id": "light.test", "state": "on"},
            ]
            mock_get.return_value = mock_client
            result = json.loads(ha_list_entities())
        assert result["count"] == 1

    def test_ha_get_state_skill(self):
        """ha_get_state returns entity state."""
        from engine.skills.builtin.homeassistant_skills import ha_get_state
        with patch("engine.skills.builtin.homeassistant_skills._ha") as mock_get:
            mock_client = MagicMock()
            mock_client.get_state.return_value = {"entity_id": "light.x", "state": "on"}
            mock_get.return_value = mock_client
            result = json.loads(ha_get_state(entity_id="light.x"))
        assert result["state"] == "on"

    def test_ha_send_notification_skill(self):
        """ha_send_notification sends a push notification."""
        from engine.skills.builtin.homeassistant_skills import ha_send_notification
        with patch("engine.skills.builtin.homeassistant_skills._ha") as mock_get:
            mock_client = MagicMock()
            mock_client.send_notification.return_value = {"sent": True}
            mock_get.return_value = mock_client
            result = json.loads(ha_send_notification(message="Hello"))
        assert result["sent"] is True

    def test_ha_phone_sensors_skill(self):
        """ha_phone_sensors returns phone sensor data."""
        from engine.skills.builtin.homeassistant_skills import ha_phone_sensors
        with patch("engine.skills.builtin.homeassistant_skills._ha") as mock_get:
            mock_client = MagicMock()
            mock_client.get_phone_sensors.return_value = {
                "sensor.sm_s908b_battery": {"state": "85"},
            }
            mock_get.return_value = mock_client
            result = json.loads(ha_phone_sensors())
        assert result["count"] == 1

    def test_ha_status_skill(self):
        """ha_status returns connection status."""
        from engine.skills.builtin.homeassistant_skills import ha_status
        with patch("engine.skills.builtin.homeassistant_skills._ha") as mock_get:
            mock_client = MagicMock()
            mock_client.status.return_value = {"connected": False, "url": "test"}
            mock_get.return_value = mock_client
            result = json.loads(ha_status())
        assert "connected" in result


# ── HA MCP Tools ──────────────────────────────────────────────────────


class TestHAMCPTools:
    """Test HA MCP tools in devtools_server."""

    def test_ha_tools_registered(self):
        """HA tools are defined in devtools_server."""
        import engine.mcp.devtools_server as ds
        source = open(ds.__file__, encoding="utf-8").read()
        ha_tools = [
            "ha_connect", "ha_list_entities", "ha_get_state",
            "ha_toggle", "ha_turn_on", "ha_turn_off",
            "ha_call_service", "ha_send_notification",
            "ha_phone_sensors", "ha_push_metrics", "ha_status",
        ]
        for tool in ha_tools:
            assert f"def {tool}" in source, f"MCP tool {tool} not found in devtools_server"


# ── HA News Push Callback ────────────────────────────────────────────


class TestHANewsPush:
    """Test the scheduler callback that pushes news to HA notifications."""

    @patch("engine.integrations.homeassistant.get_ha_client")
    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.config.get_config")
    def test_push_skips_when_ha_not_connected(self, mock_cfg, mock_nexus, mock_ha):
        """Callback skips when HA is not reachable."""
        from engine.nexus.scheduler_daemon import _ha_news_push_callback
        mock_ha.return_value.is_connected.return_value = False
        mock_ha.return_value.connect.return_value = {"connected": False}
        result = _ha_news_push_callback()
        assert result.get("skipped") is True

    @patch("engine.integrations.homeassistant.get_ha_client")
    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.config.get_config")
    def test_push_sends_high_relevance_articles(self, mock_cfg, mock_nexus, mock_ha):
        """Callback pushes articles with high relevance or 'breaking'."""
        from engine.nexus.scheduler_daemon import _ha_news_push_callback
        from datetime import datetime, timezone

        mock_ha.return_value.is_connected.return_value = True
        mock_cfg.return_value.get.return_value = 0.7

        now = datetime.now(timezone.utc).isoformat()
        mock_nexus.return_value.search.return_value = [
            {
                "title": "Breaking: AI News",
                "content": "relevance: 0.9 https://example.com/news",
                "created_at": now,
            },
            {
                "title": "Low relevance article",
                "content": "relevance: 0.2 boring stuff",
                "created_at": now,
            },
        ]

        result = _ha_news_push_callback()
        assert result["pushed"] >= 1
        mock_ha.return_value.send_news_alert.assert_called()

    @patch("engine.integrations.homeassistant.get_ha_client")
    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.config.get_config")
    def test_push_skips_old_articles(self, mock_cfg, mock_nexus, mock_ha):
        """Callback skips articles older than 24 hours."""
        from engine.nexus.scheduler_daemon import _ha_news_push_callback

        mock_ha.return_value.is_connected.return_value = True
        mock_cfg.return_value.get.return_value = 0.7

        mock_nexus.return_value.search.return_value = [
            {
                "title": "Breaking: Old News",
                "content": "relevance: 0.95",
                "created_at": "2020-01-01T00:00:00+00:00",
            },
        ]

        result = _ha_news_push_callback()
        assert result["pushed"] == 0
