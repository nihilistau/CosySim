"""Tests for engine/world/neon_city_events.py — CosySim v0.75."""
from __future__ import annotations

import pytest


def test_npc_actions_rich_count():
    from engine.world.neon_city_events import NPC_ACTIONS_RICH
    assert len(NPC_ACTIONS_RICH) >= 20


def test_world_events_rich_count():
    from engine.world.neon_city_events import WORLD_EVENTS_RICH
    assert len(WORLD_EVENTS_RICH) >= 10


def test_faction_events_rich_count():
    from engine.world.neon_city_events import FACTION_EVENTS_RICH
    assert len(FACTION_EVENTS_RICH) >= 5


def test_economy_events_count():
    from engine.world.neon_city_events import ECONOMY_EVENTS
    assert len(ECONOMY_EVENTS) >= 5


def test_ghost_messages_rich_count():
    from engine.world.neon_city_events import GHOST_MESSAGES_RICH
    assert len(GHOST_MESSAGES_RICH) >= 8


def test_npc_actions_have_required_fields():
    from engine.world.neon_city_events import NPC_ACTIONS_RICH
    required = {"scene", "actor", "title", "desc", "event_type"}
    for item in NPC_ACTIONS_RICH:
        missing = required - set(item.keys())
        assert not missing, f"NPC action missing fields: {missing} — {item.get('title')}"


def test_world_events_have_required_fields():
    from engine.world.neon_city_events import WORLD_EVENTS_RICH
    required = {"title", "desc", "scene", "event_type"}
    for item in WORLD_EVENTS_RICH:
        missing = required - set(item.keys())
        assert not missing, f"World event missing fields: {missing} — {item.get('title')}"


def test_economy_events_have_required_fields():
    from engine.world.neon_city_events import ECONOMY_EVENTS
    required = {"title", "desc", "event_type", "economy_impact"}
    for item in ECONOMY_EVENTS:
        missing = required - set(item.keys())
        assert not missing, f"Economy event missing fields: {missing} — {item.get('title')}"


def test_npc_actions_have_economy_impact():
    from engine.world.neon_city_events import NPC_ACTIONS_RICH
    has_impact = [a for a in NPC_ACTIONS_RICH if a.get("economy_impact", 0) != 0]
    assert len(has_impact) > 0, "No NPC actions have non-zero economy_impact"


def test_world_events_have_intensity():
    from engine.world.neon_city_events import WORLD_EVENTS_RICH
    for ev in WORLD_EVENTS_RICH:
        assert "intensity" in ev, f"Missing intensity in world event: {ev['title']}"
        assert ev["intensity"] > 0


def test_ghost_messages_have_message_field():
    from engine.world.neon_city_events import GHOST_MESSAGES_RICH
    for msg in GHOST_MESSAGES_RICH:
        assert isinstance(msg, dict), "Ghost message should be a dict"
        assert "message" in msg and len(msg["message"]) > 5
        assert "intensity" in msg


def test_get_events_for_scene():
    from engine.world.neon_city_events import NPC_ACTIONS_RICH, get_events_for_scene
    casino_events = get_events_for_scene("casino", NPC_ACTIONS_RICH)
    assert len(casino_events) > 0
    for ev in casino_events:
        assert "casino" in ev.get("affected_scenes", []) or ev["scene"] == "casino"


def test_get_events_for_scene_unknown():
    from engine.world.neon_city_events import NPC_ACTIONS_RICH, get_events_for_scene
    result = get_events_for_scene("definitely_not_a_scene", NPC_ACTIONS_RICH)
    assert isinstance(result, list)


def test_get_all_world_events():
    from engine.world.neon_city_events import WORLD_EVENTS_RICH, get_all_world_events
    all_events = get_all_world_events()
    assert len(all_events) >= len(WORLD_EVENTS_RICH)


def test_faction_events_have_faction_field():
    from engine.world.neon_city_events import FACTION_EVENTS_RICH
    for ev in FACTION_EVENTS_RICH:
        assert ev.get("faction"), f"Missing faction in: {ev.get('title')}"


def test_npc_actions_unique_titles():
    from engine.world.neon_city_events import NPC_ACTIONS_RICH
    titles = [a["title"] for a in NPC_ACTIONS_RICH]
    assert len(titles) == len(set(titles)), "Duplicate titles in NPC_ACTIONS_RICH"


def test_world_events_unique_titles():
    from engine.world.neon_city_events import WORLD_EVENTS_RICH
    titles = [e["title"] for e in WORLD_EVENTS_RICH]
    assert len(titles) == len(set(titles)), "Duplicate titles in WORLD_EVENTS_RICH"
