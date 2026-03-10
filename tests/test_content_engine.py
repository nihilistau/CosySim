"""Tests for engine.content.content_engine.

Covers the full ContentEngine public API, ContentPool helpers, ContentItem
dataclass behaviour, Nexus integration, NLM refill logic, and the module-level
singleton.

All Nexus and NLM calls are mocked so the suite runs entirely offline.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Dict, List
from unittest.mock import MagicMock, call, patch

import pytest

from engine.content.content_engine import (
    ContentEngine,
    ContentItem,
    ContentPool,
    get_content_engine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = "2025-01-01T00:00:00+00:00"


def _make_entry(
    scene: str,
    content_type: str,
    intensity: int = 2,
    adult_categories: List[str] = None,
    title: str = "",
    content: str = "",
    entry_id: str = "",
) -> Dict:
    """Build a minimal Nexus-style entry dict."""
    tags = [
        f"scene:{scene}",
        f"type:{content_type}",
        f"intensity:{intensity}",
    ]
    for cat in adult_categories or []:
        tags.append(f"adult:{cat}")
    return {
        "id": entry_id or str(uuid.uuid4()),
        "title": title or f"{content_type.capitalize()} in {scene}",
        "content": content or f"Sample {content_type} content for {scene}.",
        "tags": tags,
        "created_at": _NOW,
    }


def _make_mock_nexus(entries: List[Dict] = None, ask_answer: str = "") -> MagicMock:
    """Return a fully-wired mock NexusClient."""
    client = MagicMock()
    client.search.return_value = entries or []
    client.ask.return_value = {"answer": ask_answer or "", "source": "mock"}
    # Each add_entry call must return a *distinct* UUID so the pool's
    # ID-based deduplication does not accidentally collapse multiple items.
    client.add_entry.side_effect = lambda *args, **kwargs: str(uuid.uuid4())
    return client


def _engine(nexus: MagicMock = None) -> ContentEngine:
    """Create a fresh ContentEngine with an isolated mock nexus."""
    return ContentEngine(nexus_client=nexus or _make_mock_nexus())


# ---------------------------------------------------------------------------
# ContentItem
# ---------------------------------------------------------------------------


class TestContentItemFields:
    """test_content_item_fields – dataclass validation."""

    def test_all_fields_stored(self):
        """All constructor fields are accessible as attributes."""
        item = ContentItem(
            id="abc",
            title="Dark Quest",
            content="Go kill the dragon.",
            scene="tavern",
            content_type="quest",
            intensity=2,
            adult_categories=["violence"],
            tags=["scene:tavern", "type:quest", "intensity:2"],
            used=False,
            created_at=_NOW,
        )
        assert item.id == "abc"
        assert item.title == "Dark Quest"
        assert item.content == "Go kill the dragon."
        assert item.scene == "tavern"
        assert item.content_type == "quest"
        assert item.intensity == 2
        assert item.adult_categories == ["violence"]
        assert item.used is False
        assert item.created_at == _NOW

    def test_used_defaults_false(self):
        """``used`` defaults to ``False`` when not supplied."""
        item = ContentItem(
            id="x",
            title="T",
            content="C",
            scene="s",
            content_type="quest",
            intensity=1,
            adult_categories=[],
            tags=[],
        )
        assert item.used is False

    def test_created_at_auto_set(self):
        """``created_at`` is auto-populated when omitted."""
        item = ContentItem(
            id="y",
            title="T",
            content="C",
            scene="s",
            content_type="lore",
            intensity=0,
            adult_categories=[],
            tags=[],
        )
        assert item.created_at  # non-empty string

    def test_intensity_clamped_high(self):
        """Intensity > 3 is clamped to 3."""
        item = ContentItem(
            id="z",
            title="T",
            content="C",
            scene="s",
            content_type="event",
            intensity=99,
            adult_categories=[],
            tags=[],
        )
        assert item.intensity == 3

    def test_intensity_clamped_low(self):
        """Negative intensity is clamped to 0."""
        item = ContentItem(
            id="z2",
            title="T",
            content="C",
            scene="s",
            content_type="event",
            intensity=-5,
            adult_categories=[],
            tags=[],
        )
        assert item.intensity == 0


# ---------------------------------------------------------------------------
# ContentPool
# ---------------------------------------------------------------------------


class TestContentPool:
    """Unit tests for ContentPool helpers."""

    def _pool(self, n_items: int = 0, low_water: int = 5) -> ContentPool:
        pool = ContentPool("tavern", "quest", low_water_mark=low_water)
        for i in range(n_items):
            pool.add(
                ContentItem(
                    id=str(i),
                    title=f"Quest {i}",
                    content="...",
                    scene="tavern",
                    content_type="quest",
                    intensity=2,
                    adult_categories=[],
                    tags=["scene:tavern", "type:quest", "intensity:2"],
                )
            )
        return pool

    def test_is_depleted_when_empty(self):
        """Empty pool is depleted."""
        assert self._pool(0).is_depleted() is True

    def test_is_depleted_below_watermark(self):
        """Pool with fewer unused items than low_water_mark is depleted."""
        pool = self._pool(3, low_water=5)
        assert pool.is_depleted() is True

    def test_not_depleted_above_watermark(self):
        """Pool with sufficient unused items is NOT depleted."""
        pool = self._pool(10, low_water=5)
        assert pool.is_depleted() is False

    def test_available_count_excludes_used(self):
        """available_count counts only unused items."""
        pool = self._pool(4)
        pool.items[0].used = True
        pool.items[1].used = True
        assert pool.available_count() == 2

    def test_add_deduplicates_by_id(self):
        """Adding an item with a duplicate ID is a no-op."""
        pool = self._pool(0)
        item = ContentItem(
            id="dup",
            title="T",
            content="C",
            scene="tavern",
            content_type="quest",
            intensity=2,
            adult_categories=[],
            tags=[],
        )
        pool.add(item)
        pool.add(item)
        assert pool.total_count() == 1

    def test_get_unused_intensity_filter(self):
        """get_unused filters by exact intensity."""
        pool = self._pool(0)
        pool.add(ContentItem("a", "Hi", "...", "s", "quest", 3, [], []))
        pool.add(ContentItem("b", "Lo", "...", "s", "quest", 1, [], []))
        result = pool.get_unused(intensity=1)
        assert result is not None
        assert result.id == "b"

    def test_get_unused_tag_filter(self):
        """get_unused filters so all required tags must be present."""
        pool = self._pool(0)
        pool.add(ContentItem("a", "T1", "...", "s", "quest", 2, [], ["combat"]))
        pool.add(ContentItem("b", "T2", "...", "s", "quest", 2, [], ["stealth"]))
        result = pool.get_unused(tags=["stealth"])
        assert result is not None
        assert result.id == "b"

    def test_get_unused_adult_filter(self):
        """get_unused filters by adult_category membership."""
        pool = self._pool(0)
        pool.add(ContentItem("a", "T1", "...", "s", "scenario", 2, [], []))
        pool.add(ContentItem("b", "T2", "...", "s", "scenario", 2, ["sexual"], []))
        result = pool.get_unused(adult_category="sexual")
        assert result is not None
        assert result.id == "b"

    def test_get_unused_none_when_all_used(self):
        """Returns None when all items are consumed."""
        pool = self._pool(2)
        for item in pool.items:
            item.used = True
        assert pool.get_unused() is None


# ---------------------------------------------------------------------------
# ContentEngine – basic retrieval
# ---------------------------------------------------------------------------


class TestGetQuestReturnsItem:
    """test_get_quest_returns_item"""

    def test_returns_item_from_nexus(self):
        """get_quest returns a ContentItem populated from Nexus."""
        entry = _make_entry("tavern", "quest", title="Dark Quest", content="Kill the bandit lord.")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_quest("tavern")

        assert item is not None
        assert item.title == "Dark Quest"
        assert item.content_type == "quest"
        assert item.scene == "tavern"

    def test_search_called_with_scene_type(self):
        """Nexus search is invoked with scene and type in the query."""
        entry = _make_entry("tavern", "quest")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        engine.get_quest("tavern", intensity=2)

        nexus.search.assert_called_once()
        query_arg = nexus.search.call_args[0][0]
        assert "scene:tavern" in query_arg
        assert "type:quest" in query_arg

    def test_tags_filter_applied(self):
        """Only items containing all requested tags are returned."""
        entry_match = _make_entry("tavern", "quest")
        entry_match["tags"].append("combat")
        entry_no_match = _make_entry("tavern", "quest")

        nexus = _make_mock_nexus(entries=[entry_no_match, entry_match])
        engine = _engine(nexus)

        item = engine.get_quest("tavern", tags=["combat"])

        assert item is not None
        assert "combat" in item.tags


class TestNoItemsReturnsNone:
    """test_no_items_returns_none"""

    def test_empty_nexus_returns_none(self):
        """Returns None when Nexus has no matching entries."""
        nexus = _make_mock_nexus(entries=[])
        engine = _engine(nexus)
        assert engine.get_quest("tavern") is None

    def test_all_used_returns_none(self):
        """Returns None when all pool items are already consumed."""
        entry = _make_entry("tavern", "quest")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        first = engine.get_quest("tavern")
        assert first is not None
        engine.mark_used(first.id)

        second = engine.get_quest("tavern")
        assert second is None


# ---------------------------------------------------------------------------
# ContentEngine – scenario with intensity and adult filter
# ---------------------------------------------------------------------------


class TestGetScenarioRespectsIntensity:
    """test_get_scenario_respects_intensity"""

    def test_intensity_match(self):
        """get_scenario returns item whose intensity matches the request."""
        low = _make_entry("penthouse", "scenario", intensity=1, title="Mild")
        high = _make_entry("penthouse", "scenario", intensity=3, title="Intense")
        nexus = _make_mock_nexus(entries=[low, high])
        engine = _engine(nexus)

        item = engine.get_scenario("penthouse", intensity=3)

        assert item is not None
        assert item.intensity == 3
        assert item.title == "Intense"

    def test_adult_category_filter(self):
        """Adult-category filter correctly restricts results."""
        plain = _make_entry("penthouse", "scenario", title="Mild Scenario")
        explicit = _make_entry("penthouse", "scenario", adult_categories=["sexual"], title="Explicit")
        nexus = _make_mock_nexus(entries=[plain, explicit])
        engine = _engine(nexus)

        item = engine.get_scenario("penthouse", adult_category="sexual")

        assert item is not None
        assert "sexual" in item.adult_categories


# ---------------------------------------------------------------------------
# ContentEngine – lore
# ---------------------------------------------------------------------------


class TestGetLoreByTopic:
    """test_get_lore_by_topic"""

    def test_lore_requires_topic_tag(self):
        """get_lore only returns items that include the topic in their tags."""
        magic_lore = _make_entry("global", "lore", title="The Arcane Laws")
        magic_lore["tags"].append("magic")
        history_lore = _make_entry("global", "lore", title="The First War")
        history_lore["tags"].append("history")

        nexus = _make_mock_nexus(entries=[magic_lore, history_lore])
        engine = _engine(nexus)

        item = engine.get_lore("history")

        assert item is not None
        assert item.title == "The First War"

    def test_lore_scene_defaults_to_global(self):
        """When scene is empty, lore is fetched under 'global' pool."""
        entry = _make_entry("global", "lore", title="Ancient Lore")
        entry["tags"].append("ancient")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_lore("ancient")

        assert item is not None

    def test_lore_with_scene(self):
        """A scene argument constrains the Nexus search query."""
        entry = _make_entry("dungeon", "lore", title="Dungeon Secret")
        entry["tags"].append("ruins")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        engine.get_lore("ruins", scene="dungeon")

        query = nexus.search.call_args[0][0]
        assert "scene:dungeon" in query


# ---------------------------------------------------------------------------
# ContentEngine – mark_used
# ---------------------------------------------------------------------------


class TestMarkUsed:
    """test_mark_used"""

    def test_marks_item_used(self):
        """mark_used sets ``used=True`` on the matching item."""
        entry = _make_entry("tavern", "quest")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_quest("tavern")
        assert item is not None
        assert item.used is False

        engine.mark_used(item.id)

        assert item.used is True

    def test_mark_used_unknown_id_noop(self):
        """Calling mark_used with an unknown ID does not raise."""
        engine = _engine()
        engine.mark_used("nonexistent-id-xyz")  # should not raise

    def test_item_not_returned_after_mark_used(self):
        """A marked item is no longer returned by subsequent get_* calls."""
        entry = _make_entry("tavern", "quest")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_quest("tavern")
        engine.mark_used(item.id)

        second = engine.get_quest("tavern")
        assert second is None


# ---------------------------------------------------------------------------
# ContentEngine – pool status
# ---------------------------------------------------------------------------


class TestGetPoolStatus:
    """test_get_pool_status"""

    def test_status_contains_scene_and_type(self):
        """get_pool_status includes the expected scene/type keys."""
        entry = _make_entry("tavern", "quest")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)
        engine.get_quest("tavern")  # trigger pool load

        status = engine.get_pool_status()

        assert "tavern" in status
        assert "quest" in status["tavern"]

    def test_status_available_and_total(self):
        """Status reports correct available and total counts."""
        entries = [_make_entry("tavern", "quest") for _ in range(3)]
        nexus = _make_mock_nexus(entries=entries)
        engine = _engine(nexus)
        engine.get_quest("tavern")  # load pool (no intensity filter here)

        status = engine.get_pool_status()
        pool_stats = status["tavern"]["quest"]

        assert pool_stats["total"] == 3
        assert pool_stats["available"] == 3

    def test_status_after_mark_used(self):
        """Available count decrements after mark_used."""
        entries = [_make_entry("tavern", "quest") for _ in range(2)]
        nexus = _make_mock_nexus(entries=entries)
        engine = _engine(nexus)

        item = engine.get_quest("tavern")
        engine.mark_used(item.id)

        status = engine.get_pool_status()
        assert status["tavern"]["quest"]["available"] == 1

    def test_empty_status_before_any_get(self):
        """Status is an empty dict before any get_* call is made."""
        engine = _engine()
        assert engine.get_pool_status() == {}


# ---------------------------------------------------------------------------
# ContentEngine – dialogue starter
# ---------------------------------------------------------------------------


class TestDialogueStarter:
    """test_dialogue_starter"""

    def test_dialogue_uses_character_as_scene(self):
        """Dialogue pool is keyed by character_id as the scene."""
        entry = _make_entry("npc_mira", "dialogue", title="Hey stranger")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_dialogue_starter("npc_mira")

        assert item is not None
        assert item.title == "Hey stranger"

    def test_mood_tag_applied(self):
        """Mood string is used as a tag filter."""
        angry = _make_entry("npc_mira", "dialogue", title="I hate you")
        angry["tags"].append("angry")
        happy = _make_entry("npc_mira", "dialogue", title="Good day!")
        happy["tags"].append("happy")

        nexus = _make_mock_nexus(entries=[angry, happy])
        engine = _engine(nexus)

        item = engine.get_dialogue_starter("npc_mira", mood="happy")

        assert item is not None
        assert item.title == "Good day!"

    def test_no_mood_returns_any(self):
        """Without mood filter, the first available item is returned."""
        entry = _make_entry("npc_mira", "dialogue")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_dialogue_starter("npc_mira")
        assert item is not None


# ---------------------------------------------------------------------------
# ContentEngine – refill_pool
# ---------------------------------------------------------------------------


class TestRefillPool:
    """test_refill_pool"""

    def _nlm_json(self, n: int, scene: str, ctype: str) -> str:
        items = [
            {
                "title": f"Generated {ctype} {i}",
                "content": f"Content for {ctype} {i}.",
                "intensity": 2,
                "adult_categories": [],
                "tags": [f"scene:{scene}", f"type:{ctype}", "intensity:2"],
            }
            for i in range(n)
        ]
        return json.dumps(items)

    def test_refill_adds_items(self):
        """refill_pool adds generated items to the pool."""
        nexus = _make_mock_nexus(entries=[])
        nexus.ask.return_value = {
            "answer": self._nlm_json(5, "tavern", "quest"),
            "source": "nlm",
        }
        engine = _engine(nexus)

        added = engine.refill_pool("tavern", "quest", count=5)

        assert added == 5
        status = engine.get_pool_status()
        assert status["tavern"]["quest"]["available"] == 5

    def test_refill_persists_to_nexus(self):
        """Each generated item is stored in Nexus via add_entry."""
        nexus = _make_mock_nexus(entries=[])
        nexus.ask.return_value = {
            "answer": self._nlm_json(3, "dungeon", "event"),
            "source": "nlm",
        }
        engine = _engine(nexus)

        engine.refill_pool("dungeon", "event", count=3)

        assert nexus.add_entry.call_count == 3

    def test_refill_returns_zero_on_empty_answer(self):
        """Returns 0 when NLM returns an empty answer."""
        nexus = _make_mock_nexus(entries=[])
        nexus.ask.return_value = {"answer": "", "source": "mock"}
        engine = _engine(nexus)

        added = engine.refill_pool("arena", "fighter", count=5)

        assert added == 0

    def test_refill_fallback_single_item(self):
        """Non-JSON NLM response is wrapped as a single fallback item."""
        nexus = _make_mock_nexus(entries=[])
        nexus.ask.return_value = {
            "answer": "A mysterious wanderer with a dark past seeks battle.",
            "source": "nlm",
        }
        engine = _engine(nexus)

        added = engine.refill_pool("arena", "fighter", count=1)

        assert added == 1

    def test_refill_asks_nlm_with_scene_and_type(self):
        """The NLM prompt mentions the scene and content_type."""
        nexus = _make_mock_nexus(entries=[])
        nexus.ask.return_value = {
            "answer": self._nlm_json(1, "penthouse", "scenario"),
            "source": "nlm",
        }
        engine = _engine(nexus)

        engine.refill_pool("penthouse", "scenario", count=1)

        prompt = nexus.ask.call_args[0][0]
        assert "penthouse" in prompt
        assert "scenario" in prompt


# ---------------------------------------------------------------------------
# ContentEngine – auto-refill when depleted
# ---------------------------------------------------------------------------


class TestPoolDepletedTriggersRefill:
    """test_pool_depleted_triggers_refill"""

    def test_background_refill_triggered(self):
        """A background thread refill is scheduled when pool is depleted."""
        # Pool has 2 items; low_water_mark default is 5 → depleted immediately.
        entries = [_make_entry("tavern", "quest") for _ in range(2)]
        refill_json = json.dumps(
            [
                {
                    "title": f"NLM Quest {i}",
                    "content": "...",
                    "intensity": 2,
                    "adult_categories": [],
                    "tags": ["scene:tavern", "type:quest", "intensity:2"],
                }
                for i in range(10)
            ]
        )
        nexus = _make_mock_nexus(entries=entries)
        nexus.ask.return_value = {"answer": refill_json, "source": "nlm"}

        engine = _engine(nexus)
        engine.get_quest("tavern")  # triggers background refill

        # Allow background thread to complete.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if nexus.ask.called:
                break
            time.sleep(0.05)

        assert nexus.ask.called, "NLM ask was never called for refill"

    def test_no_double_refill(self):
        """A second depleted check does not start a second refill thread."""
        entries = [_make_entry("tavern", "quest")]  # 1 item → depleted
        nexus = _make_mock_nexus(entries=entries)
        # Slow refill to allow race condition to manifest if protection fails.
        refill_event = threading.Event()

        def _slow_ask(*args, **kwargs):
            refill_event.wait(timeout=2.0)
            return {"answer": "[]", "source": "mock"}

        nexus.ask.side_effect = _slow_ask
        engine = _engine(nexus)

        # Both calls should only ever schedule ONE refill.
        engine.get_quest("tavern")
        engine.get_quest("tavern")

        refill_event.set()
        time.sleep(0.2)

        assert nexus.ask.call_count == 1


# ---------------------------------------------------------------------------
# ContentEngine – world_event and fighter convenience wrappers
# ---------------------------------------------------------------------------


class TestWorldEventAndFighter:
    def test_get_world_event(self):
        """get_world_event queries the 'global' scene."""
        entry = _make_entry("global", "world_event", title="A Blood Moon Rises")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_world_event()

        assert item is not None
        assert item.content_type == "world_event"

    def test_get_fighter_defaults_arena(self):
        """get_fighter defaults to the 'arena' scene pool."""
        entry = _make_entry("arena", "fighter", title="Iron Fist Gordo")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_fighter()

        assert item is not None
        assert item.title == "Iron Fist Gordo"

    def test_get_arc(self):
        """get_arc returns a story arc item."""
        entry = _make_entry("tavern", "arc", title="The Heist Arc")
        entry["tags"].append("crime")
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_arc("tavern", arc_type="crime")

        assert item is not None
        assert item.title == "The Heist Arc"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """test_singleton"""

    def test_same_instance_returned(self):
        """get_content_engine returns the same object on repeated calls."""
        # Patch the module-level instance to avoid polluting other tests.
        with patch("engine.content.content_engine._engine_instance", None):
            with patch("engine.content.content_engine.get_nexus_client") as mock_gc:
                mock_gc.return_value = _make_mock_nexus()
                engine_a = get_content_engine()
                engine_b = get_content_engine()
                assert engine_a is engine_b

    def test_singleton_reuses_existing(self):
        """If an instance already exists, get_content_engine returns it."""
        existing = _engine()
        with patch("engine.content.content_engine._engine_instance", existing):
            returned = get_content_engine()
        assert returned is existing


# ---------------------------------------------------------------------------
# Edge cases / malformed Nexus data
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_nexus_search_exception_handled(self):
        """Nexus search failure returns None gracefully (no crash)."""
        nexus = _make_mock_nexus()
        nexus.search.side_effect = RuntimeError("Nexus down")
        engine = _engine(nexus)

        item = engine.get_quest("tavern")
        assert item is None

    def test_entry_without_title_and_content_skipped(self):
        """Entries with no title and no content are discarded."""
        bad_entry = {"id": "bad", "title": "", "content": "", "tags": []}
        nexus = _make_mock_nexus(entries=[bad_entry])
        engine = _engine(nexus)

        item = engine.get_quest("tavern")
        assert item is None

    def test_comma_separated_tags_parsed(self):
        """Tags stored as a comma-separated string are parsed correctly."""
        entry = {
            "id": "x",
            "title": "Weird Entry",
            "content": "Some content.",
            "tags": "scene:dungeon,type:event,intensity:1",
            "created_at": _NOW,
        }
        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_event("dungeon", intensity=1)

        assert item is not None
        assert item.scene == "dungeon"
        assert item.intensity == 1

    def test_intensity_tag_malformed_defaults_two(self):
        """Malformed intensity tag falls back to default intensity 2."""
        entry = _make_entry("tavern", "quest")
        # Replace the valid intensity tag with a bad one.
        entry["tags"] = [t for t in entry["tags"] if not t.startswith("intensity:")]
        entry["tags"].append("intensity:bad")

        nexus = _make_mock_nexus(entries=[entry])
        engine = _engine(nexus)

        item = engine.get_quest("tavern")
        assert item is not None
        assert item.intensity == 2

    def test_multiple_pools_independent(self):
        """Two different (scene, type) pools do not interfere with each other."""
        quest = _make_entry("tavern", "quest", title="A Quest")
        event = _make_entry("dungeon", "event", title="An Event")

        def _search_side_effect(query, limit=50):
            if "scene:tavern" in query and "type:quest" in query:
                return [quest]
            if "scene:dungeon" in query and "type:event" in query:
                return [event]
            return []

        nexus = _make_mock_nexus()
        nexus.search.side_effect = _search_side_effect
        engine = _engine(nexus)

        q = engine.get_quest("tavern")
        e = engine.get_event("dungeon")

        assert q is not None and q.title == "A Quest"
        assert e is not None and e.title == "An Event"
