"""Announcer skills — city-pulse feed tools for CosySim agents.

Pack: ``announcer``
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _get_announcer():
    from engine.world.world_announcer import get_world_announcer
    return get_world_announcer()


def _get_world_sim():
    from engine.world.world_sim import get_world_sim
    return get_world_sim()


@skill(
    pack="announcer",
    description=(
        "Get the city-pulse event feed. Returns recent world events as a list."
        " Optionally filter by category (npc|faction|world|hacker|economy)."
    ),
    category="ENVIRONMENT",
    tags=["city", "events", "feed", "announcer"],
)
def announcer_get_feed(limit: int = 20, category: str = "") -> str:
    """Return recent city-pulse announcements.

    Args:
        limit: Maximum number of entries to return (1–50).
        category: Optional filter: npc|faction|world|hacker|economy.

    Returns:
        Formatted string of recent announcements.
    """
    try:
        ann = _get_announcer()
        cat = category.strip() or None
        feed = ann.get_feed(limit=max(1, min(50, limit)), category=cat)
        if not feed:
            return "No announcements in the city-pulse feed."
        lines = [f"[{a['timestamp']} {a['category'].upper()}] {a['title']}: {a['body']}" for a in feed]
        return "\n".join(lines)
    except Exception as exc:
        logger.error("announcer_get_feed error: %s", exc)
        return f"Error reading feed: {exc}"


@skill(
    pack="announcer",
    description="Push a custom announcement into the city-pulse feed.",
    category="ENVIRONMENT",
    tags=["city", "events", "announcer", "announce"],
)
def announcer_announce(
    title: str,
    body: str,
    category: str = "world",
    scene: str = "",
    actor: str = "",
) -> str:
    """Push a manual announcement into the city-pulse feed.

    Args:
        title: Short headline (max 80 chars).
        body: Detailed announcement text.
        category: One of npc|faction|world|hacker|economy.
        scene: Optional scene ID this relates to.
        actor: Optional character or faction name.

    Returns:
        Confirmation with announcement ID.
    """
    try:
        ann = _get_announcer()
        entry = ann.announce(
            title=title[:80],
            body=body,
            category=category or "world",
            scene=scene,
            actor=actor,
        )
        return f"Announced [{entry.category.upper()}] {entry.title} (id:{entry.id})"
    except Exception as exc:
        logger.error("announcer_announce error: %s", exc)
        return f"Error announcing: {exc}"


@skill(
    pack="announcer",
    description="Get a narrative summary of the last 10 city-pulse events.",
    category="ENVIRONMENT",
    tags=["city", "events", "summary", "world"],
)
def world_event_summary() -> str:
    """Return a narrative summary of recent world events.

    Returns:
        One-paragraph string summarising the last 10 city events.
    """
    try:
        return _get_announcer().get_summary()
    except Exception as exc:
        logger.error("world_event_summary error: %s", exc)
        return f"Error getting summary: {exc}"


@skill(
    pack="announcer",
    description=(
        "Get recent world events directly from the WorldSim ring buffer."
        " Filter by scene or leave empty for all scenes. Returns event objects."
    ),
    category="ENVIRONMENT",
    tags=["world", "events", "worldsim", "city"],
)
def world_get_recent_events(limit: int = 20, scene: str = "") -> str:
    """Return recent raw WorldSim events.

    Args:
        limit: Maximum number of events (1–50).
        scene: Optional scene filter (e.g. ``"neoncity"``, ``"arena"``).

    Returns:
        Formatted string of recent events.
    """
    try:
        sim = _get_world_sim()
        events = sim.get_all_events(limit=max(1, min(50, limit)))
        if scene:
            events = [e for e in events if getattr(e, "scene", "") == scene]
        if not events:
            return "No world events recorded yet."
        lines = []
        for e in events:
            ts = getattr(e, "created_at", "")
            scene_tag = getattr(e, "scene", "")
            title = getattr(e, "title", "?")
            desc = getattr(e, "description", "")
            lines.append(f"[{ts} {scene_tag.upper()}] {title}: {desc}")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("world_get_recent_events error: %s", exc)
        return f"Error fetching events: {exc}"


@skill(
    pack="announcer",
    description="Mute or unmute a city-pulse station (npc|faction|world|hacker|economy|all).",
    category="SYSTEM",
    tags=["announcer", "mute", "station"],
)
def announcer_set_station(station: str, muted: bool = True) -> str:
    """Mute or unmute a city-pulse event station.

    Args:
        station: Station name: npc|faction|world|hacker|economy|all.
        muted: ``True`` to mute, ``False`` to unmute (default True).

    Returns:
        Confirmation string.
    """
    try:
        ann = _get_announcer()
        if muted:
            ann.mute_station(station)
            return f"Station '{station}' muted."
        else:
            ann.unmute_station(station)
            return f"Station '{station}' unmuted."
    except Exception as exc:
        logger.error("announcer_set_station error: %s", exc)
        return f"Error: {exc}"
