"""MCP skills for the in-game world news system.

Provides agent-accessible skills for querying the NeonCity Chronicle —
headlines, articles, breaking news, faction/district news, ticker feed,
editorial digests, and news tips.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="world_news",
    description="Get latest news headlines from the NeonCity Chronicle",
    category="COMMUNICATION",
    cooldown=2.0,
    cost=0.5,
    tags=["news", "headlines", "information"],
)
def latest_headlines(limit: int = 10, category: str = "") -> str:
    """Get the latest news headlines, optionally filtered by category.

    Args:
        limit: Number of headlines to return (default 10).
        category: Filter by category (crime/economy/faction/tech/social/breaking/sports/underworld).

    Returns:
        Formatted list of latest headlines.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    cat = category if category else None
    headlines = gen.get_headlines(limit=limit, category=cat)

    if not headlines:
        return "No news articles available. The city is quiet."

    severity_icons = {1: "○", 2: "◐", 3: "●", 4: "◆", 5: "⚡"}
    lines = [f"NEONCITY CHRONICLE — {len(headlines)} Headlines", ""]
    for h in headlines:
        icon = severity_icons.get(h.get("severity", 1), "○")
        age = h.get("age_minutes", 0)
        age_str = f"{age}m ago" if age < 60 else f"{age // 60}h ago"
        cat_tag = f"[{h.get('category', '').upper()}]"
        lines.append(f"  {icon} {cat_tag} {h['headline']}  ({age_str})")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Read the full text of a news article by its ID",
    category="COMMUNICATION",
    cooldown=1.0,
    cost=0.5,
    tags=["news", "article", "read"],
)
def read_article(article_id: str) -> str:
    """Read a full news article by its ID.

    Args:
        article_id: The article ID from the headlines list.

    Returns:
        Full article text with headline, body, and metadata.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    article = gen.get_article(article_id)

    if article is None:
        return f"Article '{article_id}' not found."

    lines = [
        f"━━━ {article['headline']} ━━━",
        f"Category: {article['category'].upper()} | "
        f"Severity: {'⚡' * article['severity']}",
    ]

    if article.get("district"):
        lines.append(f"District: {article['district']}")
    if article.get("related_factions"):
        lines.append(f"Factions: {', '.join(article['related_factions'])}")

    lines.append(f"By: {article.get('byline', 'Staff')}")
    lines.append("")
    lines.append(article["body"])

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Search news articles by keyword",
    category="COMMUNICATION",
    cooldown=2.0,
    cost=0.5,
    tags=["news", "search"],
)
def search_world_news(query: str, limit: int = 5) -> str:
    """Search news articles by keyword in headlines and body text.

    Args:
        query: Search term to find in articles.
        limit: Maximum results to return.

    Returns:
        Matching articles with headlines and summaries.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    results = gen.search_articles(query, limit)

    if not results:
        return f"No articles found matching '{query}'."

    lines = [f"Search results for '{query}' — {len(results)} articles", ""]
    for r in results:
        first_sentence = r["body"].split(". ")[0] + "."
        lines.append(f"  [{r['article_id']}] {r['headline']}")
        lines.append(f"    {first_sentence}")
        lines.append("")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Get breaking news alerts — high-severity events",
    category="COMMUNICATION",
    cooldown=2.0,
    cost=0.5,
    tags=["news", "breaking", "alerts"],
)
def breaking_news(limit: int = 5) -> str:
    """Get breaking news — only MAJOR and BREAKING severity articles.

    Args:
        limit: Maximum number of breaking articles.

    Returns:
        Breaking news articles with full details.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    articles = gen.get_breaking_news(limit)

    if not articles:
        return "No breaking news at this time. The city is relatively calm."

    lines = ["⚡ BREAKING NEWS ⚡", ""]
    for a in articles:
        lines.append(f"  ⚡ {a['headline']}")
        first_sentence = a["body"].split(". ")[0] + "."
        lines.append(f"    {first_sentence}")
        if a.get("district"):
            lines.append(f"    District: {a['district']}")
        lines.append("")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Get the news ticker feed for display",
    category="COMMUNICATION",
    cooldown=3.0,
    cost=0.3,
    tags=["news", "ticker"],
)
def ticker_feed(count: int = 8) -> str:
    """Get the formatted news ticker feed.

    Args:
        count: Number of ticker items.

    Returns:
        Ticker-formatted headlines for the news crawl.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    ticker_lines = gen.get_ticker_feed(count)

    if not ticker_lines:
        return "TICKER: No news at this time."

    return " ┃ ".join(ticker_lines)


@skill(
    pack="world_news",
    description="Get news about a specific faction",
    category="COMMUNICATION",
    cooldown=2.0,
    cost=0.5,
    tags=["news", "faction"],
)
def news_about_faction(faction: str, limit: int = 5) -> str:
    """Get news articles mentioning a specific faction.

    Args:
        faction: Faction name (OmniCorp, NeoTech, BlackMarket, Ghost_Net, SynthSec, DeepState).
        limit: Maximum articles to return.

    Returns:
        Articles related to the specified faction.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    articles = gen.get_by_faction(faction, limit)

    if not articles:
        return f"No recent news about {faction}."

    lines = [f"News about {faction} — {len(articles)} articles", ""]
    for a in articles:
        lines.append(f"  [{a['category'].upper()}] {a['headline']}")
        first_sentence = a["body"].split(". ")[0] + "."
        lines.append(f"    {first_sentence}")
        lines.append("")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Get news about a specific district",
    category="COMMUNICATION",
    cooldown=2.0,
    cost=0.5,
    tags=["news", "district", "local"],
)
def news_about_district(district: str, limit: int = 5) -> str:
    """Get news articles about a specific district.

    Args:
        district: District name (DOWNTOWN, COMBAT_ZONE, HIGHRISE, UNDERWORLD, TECH_DISTRICT, OUTSKIRTS).
        limit: Maximum articles to return.

    Returns:
        Local news for the specified district.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    articles = gen.get_by_district(district, limit)

    if not articles:
        return f"No recent news from {district}."

    lines = [f"Local news from {district} — {len(articles)} articles", ""]
    for a in articles:
        lines.append(f"  [{a['category'].upper()}] {a['headline']}")
        first_sentence = a["body"].split(". ")[0] + "."
        lines.append(f"    {first_sentence}")
        lines.append("")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Get editorial digest — narrative summary of recent events for NPC awareness",
    category="COMMUNICATION",
    cooldown=5.0,
    cost=1.0,
    tags=["news", "digest", "summary", "npc"],
)
def editorial_digest(count: int = 5) -> str:
    """Get editorial digest of recent news for NPC awareness.

    Args:
        count: Number of top stories to include.

    Returns:
        Narrative digest suitable for NPC system prompt injection.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    return gen.get_editorial_digest(count)


@skill(
    pack="world_news",
    description="Get news generator statistics",
    category="SYSTEM",
    cooldown=5.0,
    cost=0.3,
    tags=["news", "stats", "system"],
)
def news_stats() -> str:
    """Get statistics about the news generator system.

    Returns:
        Stats including articles generated, events received, categories.
    """
    from engine.world.news_generator import get_news_generator
    from engine.world.news_ticker import get_news_ticker

    gen = get_news_generator()
    ticker = get_news_ticker()

    gen_stats = gen.stats()
    ticker_stats = ticker.stats()

    lines = [
        "NeonCity Chronicle — System Stats",
        "",
        f"  Articles in buffer: {gen_stats['buffer_size']}/{gen_stats['buffer_max']}",
        f"  Total generated: {gen_stats['articles_generated']}",
        f"  Events received: {gen_stats['events_received']}",
        f"  Duplicates skipped: {gen_stats['duplicates_skipped']}",
        "",
        "  By Category:",
    ]

    for cat, count in gen_stats.get("articles_by_category", {}).items():
        if count > 0:
            lines.append(f"    {cat}: {count}")

    lines.append("")
    lines.append(f"  Ticker requests: {ticker_stats.get('ticker_requests', 0)}")
    lines.append(f"  Breaking alerts: {ticker_stats.get('breaking_alerts', 0)}")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Get news filtered by category",
    category="COMMUNICATION",
    cooldown=2.0,
    cost=0.5,
    tags=["news", "category", "filter"],
)
def news_by_category(category: str, limit: int = 5) -> str:
    """Get news filtered by a specific category.

    Args:
        category: Category (crime/economy/faction/tech/social/breaking/sports/underworld).
        limit: Maximum articles.

    Returns:
        Articles in the specified category.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    articles = gen.get_by_category(category, limit)

    if not articles:
        return f"No articles in category '{category}'."

    lines = [f"{category.upper()} News — {len(articles)} articles", ""]
    for a in articles:
        age = a.get("age_minutes", 0)
        age_str = f"{age}m ago" if age < 60 else f"{age // 60}h ago"
        lines.append(f"  [{a['article_id']}] {a['headline']}  ({age_str})")

    return "\n".join(lines)


@skill(
    pack="world_news",
    description="Publish a custom news article to the NeonCity Chronicle ticker",
    category="COMMUNICATION",
    cooldown=10.0,
    cost=2.0,
    tags=["news", "publish", "custom", "ticker"],
)
def publish_news(
    headline: str,
    body: str,
    category: str = "social",
    severity: int = 2,
    district: str = "",
    byline: str = "",
) -> str:
    """Publish a custom news article visible in the city news ticker.

    Use this when conversations, events, or character actions should become
    public news. The article will appear in the NeonCity Chronicle ticker,
    phone news app, and NPC awareness system.

    Args:
        headline: Short headline (shown in ticker scroll).
        body: Full article body text (1-3 paragraphs).
        category: One of: crime, economy, faction, tech, social, breaking, sports, underworld.
        severity: 1=routine, 2=notable, 3=significant, 4=major, 5=breaking.
        district: District the event occurred in (optional).
        byline: Author credit (defaults to 'NeonCity Chronicle Staff').

    Returns:
        Confirmation with article ID or error message.
    """
    from engine.world.news_generator import get_news_generator

    gen = get_news_generator()
    article_id = gen.publish_custom_article(
        headline=headline,
        body=body,
        category=category,
        severity=severity,
        district=district,
        byline=byline or "NeonCity Chronicle Staff",
    )

    if article_id:
        return f"Published: [{article_id}] \"{headline}\" — category={category}, severity={severity}"
    return f"Article not published (possible duplicate): \"{headline}\""
