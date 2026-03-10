"""Tests for Phase 7 — World News System.

Tests WorldNewsGenerator, NewsTicker, world_news_skills, and the Flask
blueprint API endpoints.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from engine.world.news_generator import (
    NewsArticle,
    NewsCategory,
    NewsSeverity,
    WorldNewsGenerator,
    get_news_generator,
    reset_news_generator,
)
from engine.world.news_ticker import (
    NewsTicker,
    TickerItem,
    get_news_ticker,
    reset_news_ticker,
)


# ──── Fixtures ────


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singletons before each test."""
    reset_news_generator()
    reset_news_ticker()
    yield
    reset_news_generator()
    reset_news_ticker()


@pytest.fixture
def gen() -> WorldNewsGenerator:
    return WorldNewsGenerator()


@pytest.fixture
def ticker() -> NewsTicker:
    return NewsTicker()


# ──── NewsArticle Tests ────


class TestNewsArticle:
    """Tests for the NewsArticle dataclass."""

    def test_defaults(self):
        """Article has sensible defaults."""
        a = NewsArticle()
        assert a.article_id
        assert a.severity == NewsSeverity.ROUTINE.value
        assert a.category == NewsCategory.CRIME.value
        assert a.read_count == 0
        assert a.fingerprint

    def test_to_dict(self):
        """to_dict includes all fields plus age_minutes."""
        a = NewsArticle(headline="Test", body="Body text")
        d = a.to_dict()
        assert d["headline"] == "Test"
        assert d["body"] == "Body text"
        assert "age_minutes" in d
        assert isinstance(d["age_minutes"], int)

    def test_to_headline(self):
        """to_headline returns compact format."""
        a = NewsArticle(
            headline="Big News",
            category="economy",
            severity=3,
            district="DOWNTOWN",
        )
        h = a.to_headline()
        assert h["headline"] == "Big News"
        assert h["category"] == "economy"
        assert h["severity"] == 3
        assert h["district"] == "DOWNTOWN"
        assert "age_minutes" in h

    def test_fingerprint_auto(self):
        """Fingerprint auto-generated from event_type + headline."""
        a = NewsArticle(
            headline="Test Headline",
            source_event_type="world_event",
        )
        assert a.fingerprint == "world_event:Test Headline"

    def test_fingerprint_custom(self):
        """Custom fingerprint preserved."""
        a = NewsArticle(headline="Test", fingerprint="custom_fp")
        assert a.fingerprint == "custom_fp"

    def test_related_entities(self):
        """Related entities stored correctly."""
        a = NewsArticle(
            related_factions=["OmniCorp", "NeoTech"],
            related_npcs=["viktor"],
            related_players=["player1"],
        )
        assert "OmniCorp" in a.related_factions
        assert "viktor" in a.related_npcs
        assert "player1" in a.related_players


# ──── WorldNewsGenerator Core Tests ────


class TestWorldNewsGenerator:
    """Tests for the WorldNewsGenerator engine."""

    def test_inject_article(self, gen: WorldNewsGenerator):
        """Manually injected articles appear in buffer."""
        article = NewsArticle(headline="Injected News", body="Test body")
        result = gen.inject_article(article)
        assert result is True
        assert gen.stats()["articles_generated"] == 1

    def test_inject_dedup(self, gen: WorldNewsGenerator):
        """Duplicate articles within dedup window are rejected."""
        a1 = NewsArticle(headline="Same News", fingerprint="fp1")
        a2 = NewsArticle(headline="Same News", fingerprint="fp1")
        assert gen.inject_article(a1) is True
        assert gen.inject_article(a2) is False
        assert gen.stats()["duplicates_skipped"] == 1
        assert gen.stats()["articles_generated"] == 1

    def test_inject_different_fingerprints(self, gen: WorldNewsGenerator):
        """Articles with different fingerprints both accepted."""
        a1 = NewsArticle(headline="News A", fingerprint="fp_a")
        a2 = NewsArticle(headline="News B", fingerprint="fp_b")
        assert gen.inject_article(a1) is True
        assert gen.inject_article(a2) is True
        assert gen.stats()["articles_generated"] == 2

    def test_get_headlines(self, gen: WorldNewsGenerator):
        """get_headlines returns ordered headlines."""
        for i in range(5):
            gen.inject_article(
                NewsArticle(headline=f"News {i}", fingerprint=f"fp_{i}")
            )
        headlines = gen.get_headlines(limit=3)
        assert len(headlines) == 3
        assert headlines[0]["headline"] == "News 4"

    def test_get_headlines_by_category(self, gen: WorldNewsGenerator):
        """get_headlines filters by category."""
        gen.inject_article(
            NewsArticle(headline="Crime News", category="crime", fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Tech News", category="tech", fingerprint="fp2")
        )
        crime = gen.get_headlines(category="crime")
        assert len(crime) == 1
        assert crime[0]["headline"] == "Crime News"

    def test_get_article(self, gen: WorldNewsGenerator):
        """get_article returns full article and increments read_count."""
        a = NewsArticle(headline="Full Article", body="Full body text")
        gen.inject_article(a)
        result = gen.get_article(a.article_id)
        assert result is not None
        assert result["headline"] == "Full Article"
        assert result["body"] == "Full body text"

    def test_get_article_not_found(self, gen: WorldNewsGenerator):
        """get_article returns None for unknown ID."""
        assert gen.get_article("nonexistent") is None

    def test_get_breaking_news(self, gen: WorldNewsGenerator):
        """get_breaking_news returns only MAJOR+ severity."""
        gen.inject_article(
            NewsArticle(headline="Minor", severity=1, fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Major", severity=4, fingerprint="fp2")
        )
        gen.inject_article(
            NewsArticle(headline="Breaking", severity=5, fingerprint="fp3")
        )
        breaking = gen.get_breaking_news()
        assert len(breaking) == 2
        headlines = [a["headline"] for a in breaking]
        assert "Major" in headlines
        assert "Breaking" in headlines
        assert "Minor" not in headlines

    def test_get_by_category(self, gen: WorldNewsGenerator):
        """get_by_category filters correctly."""
        gen.inject_article(
            NewsArticle(headline="A", category="economy", fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="B", category="crime", fingerprint="fp2")
        )
        econ = gen.get_by_category("economy")
        assert len(econ) == 1
        assert econ[0]["headline"] == "A"

    def test_get_by_district(self, gen: WorldNewsGenerator):
        """get_by_district filters by district name."""
        gen.inject_article(
            NewsArticle(headline="Downtown", district="DOWNTOWN", fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Other", district="OUTSKIRTS", fingerprint="fp2")
        )
        results = gen.get_by_district("DOWNTOWN")
        assert len(results) == 1
        assert results[0]["headline"] == "Downtown"

    def test_get_by_faction(self, gen: WorldNewsGenerator):
        """get_by_faction matches related_factions and text."""
        gen.inject_article(
            NewsArticle(
                headline="OmniCorp Moves",
                related_factions=["OmniCorp"],
                fingerprint="fp1",
            )
        )
        gen.inject_article(
            NewsArticle(headline="Other News", fingerprint="fp2")
        )
        results = gen.get_by_faction("OmniCorp")
        assert len(results) == 1

    def test_search_articles(self, gen: WorldNewsGenerator):
        """search_articles matches headline and body text."""
        gen.inject_article(
            NewsArticle(
                headline="Data Breach Alert",
                body="Hackers compromised systems",
                fingerprint="fp1",
            )
        )
        gen.inject_article(
            NewsArticle(headline="Market Update", body="Prices rose", fingerprint="fp2")
        )
        results = gen.search_articles("breach")
        assert len(results) == 1
        assert results[0]["headline"] == "Data Breach Alert"

    def test_get_ticker_feed(self, gen: WorldNewsGenerator):
        """get_ticker_feed returns formatted strings."""
        gen.inject_article(
            NewsArticle(headline="Ticker Test", severity=3, fingerprint="fp1")
        )
        ticker = gen.get_ticker_feed(5)
        assert len(ticker) == 1
        assert "Ticker Test" in ticker[0]
        assert "●" in ticker[0]

    def test_get_editorial_digest(self, gen: WorldNewsGenerator):
        """get_editorial_digest returns narrative text."""
        gen.inject_article(
            NewsArticle(
                headline="Big Event",
                body="Something big happened in downtown.",
                fingerprint="fp1",
            )
        )
        digest = gen.get_editorial_digest(5)
        assert "NEONCITY CHRONICLE" in digest
        assert "Big Event" in digest

    def test_get_editorial_digest_empty(self, gen: WorldNewsGenerator):
        """Empty generator returns quiet message."""
        digest = gen.get_editorial_digest()
        assert "quiet" in digest.lower()

    def test_buffer_limit(self, gen: WorldNewsGenerator):
        """Buffer respects MAX_ARTICLES limit."""
        gen.MAX_ARTICLES = 5
        gen._articles = __import__("collections").deque(maxlen=5)
        for i in range(10):
            gen.inject_article(
                NewsArticle(headline=f"News {i}", fingerprint=f"fp_{i}")
            )
        assert len(gen._articles) == 5

    def test_stats(self, gen: WorldNewsGenerator):
        """Stats track all metrics."""
        gen.inject_article(
            NewsArticle(headline="A", category="crime", severity=3, fingerprint="fp1")
        )
        stats = gen.stats()
        assert stats["articles_generated"] == 1
        assert stats["buffer_size"] == 1
        assert stats["articles_by_category"]["crime"] == 1
        assert stats["articles_by_severity"][3] == 1

    def test_reset(self, gen: WorldNewsGenerator):
        """reset() clears everything."""
        gen.inject_article(NewsArticle(headline="Test", fingerprint="fp1"))
        gen.reset()
        assert gen.stats()["articles_generated"] == 0
        assert gen.stats()["buffer_size"] == 0


# ──── Event Handler Tests ────


class TestWorldNewsEventHandlers:
    """Tests for the event handler methods."""

    def test_handle_world_event_crackdown(self, gen: WorldNewsGenerator):
        """Crackdown world events generate crime articles."""
        event = {
            "payload": {
                "type": "crackdown",
                "district": "DOWNTOWN",
                "narrative": "A crackdown occurred.",
                "tick": 42,
            }
        }
        gen._handle_world_event(event)
        assert gen.stats()["articles_generated"] == 1
        articles = gen.get_all_articles()
        assert articles[0]["district"] == "DOWNTOWN"
        assert articles[0]["category"] == "crime"

    def test_handle_world_event_hack(self, gen: WorldNewsGenerator):
        """Hack events generate tech articles."""
        event = {
            "payload": {
                "type": "hack",
                "district": "TECH_DISTRICT",
                "tick": 10,
            }
        }
        gen._handle_world_event(event)
        articles = gen.get_all_articles()
        assert articles[0]["category"] == "tech"

    def test_handle_world_event_disaster(self, gen: WorldNewsGenerator):
        """Disaster events generate breaking articles."""
        event = {
            "payload": {
                "type": "disaster",
                "district": "TECH_DISTRICT",
                "tick": 5,
            }
        }
        gen._handle_world_event(event)
        articles = gen.get_all_articles()
        assert articles[0]["severity"] == NewsSeverity.BREAKING.value

    def test_handle_world_event_unknown_type(self, gen: WorldNewsGenerator):
        """Unknown event types generate generic articles."""
        event = {
            "payload": {
                "type": "alien_invasion",
                "name": "Alien Invasion",
                "district": "OUTSKIRTS",
                "narrative": "Aliens landed in the outskirts.",
                "tick": 99,
            }
        }
        gen._handle_world_event(event)
        assert gen.stats()["articles_generated"] == 1

    def test_handle_faction_decision_expand(self, gen: WorldNewsGenerator):
        """Faction expand decisions generate articles."""
        event = {
            "payload": {
                "faction": "OmniCorp",
                "action": "expand",
                "target_district": "DOWNTOWN",
                "target_faction": "NeoTech",
                "control_delta": 2.5,
            }
        }
        gen._handle_faction_decision(event)
        assert gen.stats()["articles_generated"] == 1
        articles = gen.get_all_articles()
        assert "OmniCorp" in articles[0]["headline"]

    def test_handle_faction_decision_idle_skipped(self, gen: WorldNewsGenerator):
        """Idle faction decisions are skipped."""
        event = {
            "payload": {
                "faction": "NeoTech",
                "action": "idle",
                "target_district": "HIGHRISE",
                "control_delta": 0.0,
            }
        }
        gen._handle_faction_decision(event)
        assert gen.stats()["articles_generated"] == 0

    def test_handle_faction_decision_low_delta_skipped(self, gen: WorldNewsGenerator):
        """Low control delta decisions are skipped."""
        event = {
            "payload": {
                "faction": "NeoTech",
                "action": "defend",
                "target_district": "HIGHRISE",
                "control_delta": 0.3,
            }
        }
        gen._handle_faction_decision(event)
        assert gen.stats()["articles_generated"] == 0

    def test_handle_faction_decision_high_delta_upgrades_severity(
        self, gen: WorldNewsGenerator
    ):
        """High control delta upgrades severity."""
        event = {
            "payload": {
                "faction": "SynthSec",
                "action": "raid",
                "target_district": "COMBAT_ZONE",
                "target_faction": "BlackMarket",
                "control_delta": 4.5,
            }
        }
        gen._handle_faction_decision(event)
        articles = gen.get_all_articles()
        assert articles[0]["severity"] >= NewsSeverity.MAJOR.value

    def test_handle_faction_war(self, gen: WorldNewsGenerator):
        """Faction wars always generate BREAKING articles."""
        event = {
            "payload": {
                "attacker": "SynthSec",
                "defender": "BlackMarket",
                "district": "COMBAT_ZONE",
                "intensity": 12.0,
            }
        }
        gen._handle_faction_war(event)
        articles = gen.get_all_articles()
        assert articles[0]["severity"] == NewsSeverity.BREAKING.value
        assert articles[0]["category"] == NewsCategory.BREAKING.value
        assert "SynthSec" in articles[0]["related_factions"]
        assert "BlackMarket" in articles[0]["related_factions"]

    def test_handle_market_tick_notable(self, gen: WorldNewsGenerator):
        """Market ticks with enough changes generate articles."""
        event = {
            "payload": {"price_changes": 5, "tick": 100}
        }
        gen._handle_market_tick(event)
        assert gen.stats()["articles_generated"] == 1

    def test_handle_market_tick_quiet(self, gen: WorldNewsGenerator):
        """Market ticks with few changes are skipped."""
        event = {
            "payload": {"price_changes": 1, "tick": 101}
        }
        gen._handle_market_tick(event)
        assert gen.stats()["articles_generated"] == 0

    def test_handle_player_action_heist(self, gen: WorldNewsGenerator):
        """Heist completion generates crime articles."""
        event = {
            "event_type": "heist.job_complete",
            "payload": {"player_id": "test_player", "id": "heist_42"},
        }
        gen._handle_player_action(event)
        articles = gen.get_all_articles()
        assert len(articles) == 1
        assert articles[0]["category"] == "crime"

    def test_handle_player_action_casino(self, gen: WorldNewsGenerator):
        """Casino wins generate social articles."""
        event = {
            "event_type": "casino.major_win",
            "payload": {"player_id": "lucky_player"},
        }
        gen._handle_player_action(event)
        articles = gen.get_all_articles()
        assert len(articles) == 1
        assert articles[0]["category"] == "social"

    def test_handle_player_action_unknown(self, gen: WorldNewsGenerator):
        """Unknown player action types are silently ignored."""
        event = {
            "event_type": "unknown.event",
            "payload": {},
        }
        gen._handle_player_action(event)
        assert gen.stats()["articles_generated"] == 0


# ──── WorldNewsGenerator Singleton Tests ────


class TestNewsGeneratorSingleton:
    """Tests for singleton lifecycle."""

    def test_singleton(self):
        """get_news_generator returns same instance."""
        g1 = get_news_generator()
        g2 = get_news_generator()
        assert g1 is g2

    def test_reset(self):
        """reset_news_generator creates fresh instance."""
        g1 = get_news_generator()
        reset_news_generator()
        g2 = get_news_generator()
        assert g1 is not g2


# ──── NewsTicker Tests ────


class TestNewsTicker:
    """Tests for the NewsTicker formatting system."""

    def test_get_ticker_items(self, ticker: NewsTicker):
        """get_ticker_items returns formatted TickerItems."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Test Headline",
                category="crime",
                severity=3,
                fingerprint="fp1",
            )
        )
        items = ticker.get_ticker_items(count=5)
        assert len(items) == 1
        assert "Test Headline" in items[0].text
        assert items[0].severity == 3
        assert "[CRIME]" in items[0].text

    def test_breaking_first(self, ticker: NewsTicker):
        """Breaking news items sorted to front."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Minor", severity=1, fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Breaking", severity=5, fingerprint="fp2")
        )
        items = ticker.get_ticker_items(count=5)
        assert items[0].is_breaking is True
        assert items[0].severity == 5

    def test_mute_category(self, ticker: NewsTicker):
        """Muted categories are excluded from ticker."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Crime News", category="crime", fingerprint="fp1"
            )
        )
        gen.inject_article(
            NewsArticle(
                headline="Tech News", category="tech", fingerprint="fp2"
            )
        )
        ticker.mute_category("crime")
        items = ticker.get_ticker_items()
        texts = [i.text for i in items]
        assert all("Crime" not in t for t in texts)
        assert any("Tech" in t for t in texts)

    def test_unmute_category(self, ticker: NewsTicker):
        """Unmuting re-includes category."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Crime News", category="crime", fingerprint="fp1"
            )
        )
        ticker.mute_category("crime")
        assert len(ticker.get_ticker_items()) == 0

        ticker.unmute_category("crime")
        assert len(ticker.get_ticker_items()) == 1

    def test_get_ticker_strings(self, ticker: NewsTicker):
        """get_ticker_strings returns simple string list."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Simple", fingerprint="fp1")
        )
        strings = ticker.get_ticker_strings()
        assert len(strings) == 1
        assert "Simple" in strings[0]

    def test_display_duration(self, ticker: NewsTicker):
        """Breaking news has longer display duration."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Normal", severity=1, fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Breaking", severity=5, fingerprint="fp2")
        )
        items = ticker.get_ticker_items()
        breaking = [i for i in items if i.is_breaking]
        normal = [i for i in items if not i.is_breaking]
        assert breaking[0].display_duration_ms > normal[0].display_duration_ms

    def test_stats(self, ticker: NewsTicker):
        """Stats track ticker requests."""
        gen = get_news_generator()
        gen.inject_article(NewsArticle(headline="A", fingerprint="fp1"))
        ticker.get_ticker_items()
        ticker.get_ticker_items()
        stats = ticker.stats()
        assert stats["ticker_requests"] == 2

    def test_reset(self, ticker: NewsTicker):
        """reset() clears muted and stats."""
        ticker.mute_category("crime")
        ticker.get_ticker_items()
        ticker.reset()
        assert ticker.get_muted() == []
        assert ticker.stats()["ticker_requests"] == 0

    def test_category_filter(self, ticker: NewsTicker):
        """Category filter in get_ticker_items works."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Crime", category="crime", fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Tech", category="tech", fingerprint="fp2")
        )
        items = ticker.get_ticker_items(category="tech")
        assert len(items) == 1
        assert "Tech" in items[0].text


class TestNewsTickerSingleton:
    """Tests for ticker singleton."""

    def test_singleton(self):
        """get_news_ticker returns same instance."""
        t1 = get_news_ticker()
        t2 = get_news_ticker()
        assert t1 is t2

    def test_reset(self):
        """reset_news_ticker creates fresh instance."""
        t1 = get_news_ticker()
        reset_news_ticker()
        t2 = get_news_ticker()
        assert t1 is not t2


# ──── TickerItem Tests ────


class TestTickerItem:
    """Tests for the TickerItem dataclass."""

    def test_to_dict(self):
        """TickerItem.to_dict returns all fields."""
        item = TickerItem(
            article_id="abc",
            text="Test headline",
            category="crime",
            severity=3,
            is_breaking=False,
        )
        d = item.to_dict()
        assert d["article_id"] == "abc"
        assert d["text"] == "Test headline"
        assert d["display_duration_ms"] == 8000

    def test_breaking_item(self):
        """Breaking TickerItem has correct defaults."""
        item = TickerItem(is_breaking=True, display_duration_ms=12000)
        assert item.is_breaking is True
        assert item.display_duration_ms == 12000


# ──── World News Skills Tests ────


class TestWorldNewsSkills:
    """Tests for the world_news_skills MCP skills."""

    def test_imports(self):
        """All skills import successfully."""
        from engine.skills.builtin.world_news_skills import (
            breaking_news,
            editorial_digest,
            latest_headlines,
            news_about_district,
            news_about_faction,
            news_by_category,
            news_stats,
            read_article,
            search_world_news,
            ticker_feed,
        )

        assert callable(latest_headlines)
        assert callable(read_article)
        assert callable(search_world_news)
        assert callable(breaking_news)
        assert callable(ticker_feed)
        assert callable(news_about_faction)
        assert callable(news_about_district)
        assert callable(editorial_digest)
        assert callable(news_stats)
        assert callable(news_by_category)

    def test_latest_headlines_empty(self):
        """latest_headlines returns quiet message when no news."""
        from engine.skills.builtin.world_news_skills import latest_headlines

        result = latest_headlines()
        assert "quiet" in result.lower()

    def test_latest_headlines_with_articles(self):
        """latest_headlines shows articles when available."""
        from engine.skills.builtin.world_news_skills import latest_headlines

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Test News", category="crime", fingerprint="fp1")
        )
        result = latest_headlines()
        assert "Test News" in result
        assert "CHRONICLE" in result

    def test_read_article_found(self):
        """read_article shows full article text."""
        from engine.skills.builtin.world_news_skills import read_article

        gen = get_news_generator()
        a = NewsArticle(headline="Full Story", body="Full body of the article.")
        gen.inject_article(a)
        result = read_article(a.article_id)
        assert "Full Story" in result
        assert "Full body of the article" in result

    def test_read_article_not_found(self):
        """read_article handles missing articles."""
        from engine.skills.builtin.world_news_skills import read_article

        result = read_article("nonexistent")
        assert "not found" in result

    def test_search_world_news_match(self):
        """search_world_news finds matching articles."""
        from engine.skills.builtin.world_news_skills import search_world_news

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Cyberattack Alert",
                body="Networks compromised.",
                fingerprint="fp1",
            )
        )
        result = search_world_news("cyber")
        assert "Cyberattack" in result

    def test_search_world_news_no_match(self):
        """search_world_news handles no results."""
        from engine.skills.builtin.world_news_skills import search_world_news

        result = search_world_news("xyznonexistent")
        assert "No articles" in result

    def test_breaking_news_skill(self):
        """breaking_news skill returns high-severity articles."""
        from engine.skills.builtin.world_news_skills import breaking_news

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Minor", severity=1, fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="EMERGENCY", severity=5, fingerprint="fp2")
        )
        result = breaking_news()
        assert "EMERGENCY" in result
        assert "BREAKING" in result

    def test_breaking_news_empty(self):
        """breaking_news handles no breaking news."""
        from engine.skills.builtin.world_news_skills import breaking_news

        result = breaking_news()
        assert "calm" in result.lower()

    def test_ticker_feed_skill(self):
        """ticker_feed returns formatted ticker string."""
        from engine.skills.builtin.world_news_skills import ticker_feed

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Ticker Item", fingerprint="fp1")
        )
        result = ticker_feed()
        assert "Ticker Item" in result

    def test_ticker_feed_empty(self):
        """ticker_feed handles empty state."""
        from engine.skills.builtin.world_news_skills import ticker_feed

        result = ticker_feed()
        assert "No news" in result

    def test_news_about_faction_skill(self):
        """news_about_faction returns faction-specific articles."""
        from engine.skills.builtin.world_news_skills import news_about_faction

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="OmniCorp Moves",
                related_factions=["OmniCorp"],
                fingerprint="fp1",
            )
        )
        result = news_about_faction("OmniCorp")
        assert "OmniCorp" in result

    def test_news_about_faction_none(self):
        """news_about_faction handles no results."""
        from engine.skills.builtin.world_news_skills import news_about_faction

        result = news_about_faction("UnknownFaction")
        assert "No recent" in result

    def test_news_about_district_skill(self):
        """news_about_district returns district-specific articles."""
        from engine.skills.builtin.world_news_skills import news_about_district

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Downtown News",
                district="DOWNTOWN",
                fingerprint="fp1",
            )
        )
        result = news_about_district("DOWNTOWN")
        assert "Downtown News" in result

    def test_editorial_digest_skill(self):
        """editorial_digest returns narrative summary."""
        from engine.skills.builtin.world_news_skills import editorial_digest

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Big Story",
                body="Something happened in the city.",
                fingerprint="fp1",
            )
        )
        result = editorial_digest()
        assert "NEONCITY CHRONICLE" in result
        assert "Big Story" in result

    def test_news_stats_skill(self):
        """news_stats returns system statistics."""
        from engine.skills.builtin.world_news_skills import news_stats

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Test", category="crime", fingerprint="fp1")
        )
        result = news_stats()
        assert "Chronicle" in result
        assert "crime" in result

    def test_news_by_category_skill(self):
        """news_by_category filters correctly."""
        from engine.skills.builtin.world_news_skills import news_by_category

        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Econ", category="economy", fingerprint="fp1")
        )
        gen.inject_article(
            NewsArticle(headline="Crime", category="crime", fingerprint="fp2")
        )
        result = news_by_category("economy")
        assert "Econ" in result
        assert "Crime" not in result

    def test_news_by_category_empty(self):
        """news_by_category handles empty category."""
        from engine.skills.builtin.world_news_skills import news_by_category

        result = news_by_category("nonexistent")
        assert "No articles" in result


# ──── Flask Blueprint Tests ────


class TestNewsTickerBlueprint:
    """Tests for the Flask API endpoints."""

    @pytest.fixture
    def client(self):
        """Create Flask test client with news ticker blueprint."""
        from flask import Flask

        from engine.world.news_ticker import create_news_ticker_blueprint

        app = Flask(__name__)
        app.register_blueprint(create_news_ticker_blueprint())
        app.config["TESTING"] = True
        return app.test_client()

    def test_ticker_endpoint(self, client):
        """GET /api/news/ticker returns items."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="API Test", fingerprint="fp1")
        )
        resp = client.get("/api/news/ticker")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        assert data["count"] >= 1

    def test_headlines_endpoint(self, client):
        """GET /api/news/headlines returns headlines."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Headline API", fingerprint="fp1")
        )
        resp = client.get("/api/news/headlines?limit=5")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "headlines" in data

    def test_article_endpoint(self, client):
        """GET /api/news/article/<id> returns full article."""
        gen = get_news_generator()
        a = NewsArticle(headline="Detail", body="Detail body")
        gen.inject_article(a)
        resp = client.get(f"/api/news/article/{a.article_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["headline"] == "Detail"

    def test_article_not_found(self, client):
        """GET /api/news/article/<bad_id> returns 404."""
        resp = client.get("/api/news/article/nonexistent")
        assert resp.status_code == 404

    def test_breaking_endpoint(self, client):
        """GET /api/news/breaking returns high-severity articles."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(headline="Emergency", severity=5, fingerprint="fp1")
        )
        resp = client.get("/api/news/breaking")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["articles"]) == 1

    def test_search_endpoint(self, client):
        """GET /api/news/search?q= returns matching articles."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Searchable Story",
                body="Unique content here.",
                fingerprint="fp1",
            )
        )
        resp = client.get("/api/news/search?q=searchable")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["results"]) == 1

    def test_search_missing_query(self, client):
        """GET /api/news/search without q returns 400."""
        resp = client.get("/api/news/search")
        assert resp.status_code == 400

    def test_digest_endpoint(self, client):
        """GET /api/news/digest returns editorial digest."""
        gen = get_news_generator()
        gen.inject_article(
            NewsArticle(
                headline="Digest Story",
                body="A full story for the digest.",
                fingerprint="fp1",
            )
        )
        resp = client.get("/api/news/digest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "digest" in data
        assert "Digest Story" in data["digest"]

    def test_stats_endpoint(self, client):
        """GET /api/news/stats returns statistics."""
        resp = client.get("/api/news/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "generator" in data
        assert "ticker" in data
