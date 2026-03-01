"""
Tests for engine/characters/memory.py — CharacterMemory, CharacterMemoryInterceptor,
and the get_character_memory singleton factory.

All Nexus I/O is mocked via ``patch("engine.characters.memory.get_nexus_client")``.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from unittest.mock import MagicMock, call, patch

import pytest

from engine.characters.memory import (
    CharacterMemory,
    CharacterMemoryInterceptor,
    MemoryEntry,
    get_character_memory,
    _character_memory_registry,
)
from engine.mcp.comms_framework import ResponseContext


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures & helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_raw_nexus_entry(entry: MemoryEntry) -> dict:
    """Build a fake Nexus search/list result from a MemoryEntry."""
    return {
        "id": f"nexus-{entry.id}",
        "title": f"memory:{entry.character_id}:{entry.id}",
        "content": json.dumps(entry.to_dict()),
        "content_type": "memory",
        "category": f"character_memory:{entry.character_id}",
    }


def _make_entry(
    character_id: str = "luna",
    player_id: str = "player",
    content: str = "The player gave Luna a red rose.",
    emotional_weight: float = 0.7,
    scene: str = "bedroom",
    tags: List[str] = None,
    days_old: int = 0,
) -> MemoryEntry:
    """Factory for MemoryEntry instances with sensible defaults."""
    now = datetime.now(timezone.utc) - timedelta(days=days_old)
    iso = now.isoformat()
    return MemoryEntry(
        id=str(uuid.uuid4()),
        character_id=character_id,
        player_id=player_id,
        content=content,
        emotional_weight=emotional_weight,
        scene=scene,
        created_at=iso,
        accessed_at=iso,
        access_count=0,
        tags=tags or [],
    )


@pytest.fixture()
def mock_nexus():
    """Return a MagicMock wired as the Nexus client singleton."""
    client = MagicMock()
    client.add_entry.return_value = "nexus-entry-id-001"
    client.delete_entry.return_value = True
    client.search.return_value = []
    client.list_by_type.return_value = []
    client.ask.return_value = {"answer": "You've known each other for a while."}
    client.update_entry.return_value = True
    return client


@pytest.fixture()
def mem(mock_nexus):
    """CharacterMemory for 'luna' with an injected mock client."""
    return CharacterMemory("luna", nexus_client=mock_nexus)


# ══════════════════════════════════════════════════════════════════════════════
#  MemoryEntry serialisation
# ══════════════════════════════════════════════════════════════════════════════


def test_entry_serialization():
    """MemoryEntry round-trips perfectly through to_dict / from_dict."""
    entry = _make_entry(tags=["gift", "flowers"])
    data = entry.to_dict()

    assert data["id"] == entry.id
    assert data["character_id"] == "luna"
    assert data["emotional_weight"] == pytest.approx(0.7)
    assert data["tags"] == ["gift", "flowers"]

    restored = MemoryEntry.from_dict(data)
    assert restored.id == entry.id
    assert restored.content == entry.content
    assert restored.emotional_weight == pytest.approx(entry.emotional_weight)
    assert restored.tags == entry.tags


def test_entry_from_dict_defaults():
    """from_dict tolerates missing fields and fills defaults."""
    entry = MemoryEntry.from_dict({})
    assert entry.id == ""
    assert entry.player_id == "player"
    assert entry.emotional_weight == pytest.approx(0.5)
    assert entry.access_count == 0
    assert entry.tags == []


# ══════════════════════════════════════════════════════════════════════════════
#  remember()
# ══════════════════════════════════════════════════════════════════════════════


def test_remember_creates_entry(mem, mock_nexus):
    """remember() creates a MemoryEntry and stores it in Nexus."""
    entry = mem.remember(
        "The player asked Luna to wear the red dress",
        player_id="player",
        emotional_weight=0.9,
        scene="bedroom",
        tags=["wardrobe"],
    )

    assert isinstance(entry, MemoryEntry)
    assert entry.character_id == "luna"
    assert entry.player_id == "player"
    assert entry.content == "The player asked Luna to wear the red dress"
    assert entry.emotional_weight == pytest.approx(0.9)
    assert entry.scene == "bedroom"
    assert "wardrobe" in entry.tags

    # Verify Nexus was called with correct arguments
    mock_nexus.add_entry.assert_called_once()
    call_kwargs = mock_nexus.add_entry.call_args
    assert call_kwargs.kwargs.get("content_type") == "memory" or (
        len(call_kwargs.args) >= 3 and call_kwargs.args[2] == "memory"
    )
    assert "character_memory:luna" in (
        call_kwargs.kwargs.get("category", "")
        or (call_kwargs.args[3] if len(call_kwargs.args) > 3 else "")
    )


def test_remember_clamps_emotional_weight(mem, mock_nexus):
    """emotional_weight is clamped to [0.0, 1.0]."""
    entry_high = mem.remember("Test", emotional_weight=999.0)
    assert entry_high.emotional_weight == pytest.approx(1.0)

    entry_low = mem.remember("Test2", emotional_weight=-5.0)
    assert entry_low.emotional_weight == pytest.approx(0.0)


def test_remember_nexus_failure_returns_entry(mock_nexus):
    """If Nexus fails (returns None), remember() still returns the entry."""
    mock_nexus.add_entry.return_value = None
    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    entry = mem.remember("Something happened")
    assert isinstance(entry, MemoryEntry)


# ══════════════════════════════════════════════════════════════════════════════
#  recall()
# ══════════════════════════════════════════════════════════════════════════════


def test_recall_returns_relevant_memories(mock_nexus):
    """recall() parses Nexus search results and returns matching entries."""
    e1 = _make_entry(content="Luna kissed the player.", emotional_weight=0.9)
    e2 = _make_entry(content="The player complimented Luna's hair.", emotional_weight=0.5)
    # Entry for a different character — should be filtered out
    e_other = _make_entry(character_id="aria", content="Aria waved hello.")

    mock_nexus.search.return_value = [
        _make_raw_nexus_entry(e1),
        _make_raw_nexus_entry(e2),
        _make_raw_nexus_entry(e_other),
    ]
    mock_nexus.update_entry.return_value = True

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    results = mem.recall("kiss", player_id="player", limit=5)

    assert len(results) == 2
    contents = [r.content for r in results]
    assert "Luna kissed the player." in contents
    assert "The player complimented Luna's hair." in contents
    # aria entry must NOT appear
    assert "Aria waved hello." not in contents


def test_recall_respects_limit(mock_nexus):
    """recall() never returns more entries than limit."""
    entries = [
        _make_entry(content=f"Memory {i}", emotional_weight=float(i) / 10)
        for i in range(1, 9)
    ]
    mock_nexus.search.return_value = [_make_raw_nexus_entry(e) for e in entries]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    results = mem.recall("anything", limit=3)

    assert len(results) <= 3


def test_recall_filters_by_player(mock_nexus):
    """recall() filters entries by player_id."""
    e_player = _make_entry(player_id="player", content="Player memory.")
    e_other = _make_entry(player_id="npc_bob", content="Bob memory.")

    mock_nexus.search.return_value = [
        _make_raw_nexus_entry(e_player),
        _make_raw_nexus_entry(e_other),
    ]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    results = mem.recall("memory", player_id="player", limit=10)

    assert all(r.player_id == "player" for r in results)
    assert len(results) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  recall_recent()
# ══════════════════════════════════════════════════════════════════════════════


def test_recall_recent(mock_nexus):
    """recall_recent() returns entries sorted by created_at descending."""
    old_entry = _make_entry(content="Older memory.", days_old=5)
    new_entry = _make_entry(content="Newer memory.", days_old=0)

    mock_nexus.list_by_type.return_value = [
        _make_raw_nexus_entry(old_entry),
        _make_raw_nexus_entry(new_entry),
    ]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    results = mem.recall_recent(player_id="player", limit=10)

    assert len(results) == 2
    # Newer should come first
    assert results[0].content == "Newer memory."
    assert results[1].content == "Older memory."


def test_recall_recent_respects_limit(mock_nexus):
    """recall_recent() never returns more than limit entries."""
    entries = [_make_entry(content=f"Mem {i}") for i in range(20)]
    mock_nexus.list_by_type.return_value = [_make_raw_nexus_entry(e) for e in entries]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    results = mem.recall_recent(limit=5)

    assert len(results) <= 5


# ══════════════════════════════════════════════════════════════════════════════
#  get_memory_summary()
# ══════════════════════════════════════════════════════════════════════════════


def test_memory_summary_format(mock_nexus):
    """get_memory_summary() produces 'You remember: …' lines."""
    e1 = _make_entry(content="Luna kissed the player.", emotional_weight=0.9)
    e2 = _make_entry(content="Player gave Luna roses.", emotional_weight=0.6)
    mock_nexus.list_by_type.return_value = [
        _make_raw_nexus_entry(e1),
        _make_raw_nexus_entry(e2),
    ]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    summary = mem.get_memory_summary(player_id="player")

    lines = summary.strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert line.startswith("You remember: ")

    # Higher emotional_weight entry should appear first
    assert lines[0] == "You remember: Luna kissed the player."


def test_memory_summary_empty_returns_empty_string(mock_nexus):
    """get_memory_summary() returns '' when no memories exist."""
    mock_nexus.list_by_type.return_value = []

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    assert mem.get_memory_summary() == ""


# ══════════════════════════════════════════════════════════════════════════════
#  summarize()
# ══════════════════════════════════════════════════════════════════════════════


def test_summarize_calls_nexus_ask(mock_nexus):
    """summarize() calls nexus.ask() and returns the answer string."""
    entry = _make_entry(content="Player brought flowers.")
    mock_nexus.list_by_type.return_value = [_make_raw_nexus_entry(entry)]
    mock_nexus.ask.return_value = {"answer": "A warm and growing friendship."}

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    result = mem.summarize(player_id="player")

    assert result == "A warm and growing friendship."
    mock_nexus.ask.assert_called_once()
    question_arg = mock_nexus.ask.call_args.args[0]
    assert "Player brought flowers." in question_arg


def test_summarize_returns_empty_when_no_memories(mock_nexus):
    """summarize() returns '' when there are no memories to summarise."""
    mock_nexus.list_by_type.return_value = []

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    result = mem.summarize()

    assert result == ""
    mock_nexus.ask.assert_not_called()


def test_summarize_handles_alternative_response_keys(mock_nexus):
    """summarize() can extract the answer from 'response' or 'text' keys."""
    entry = _make_entry(content="They danced together.")
    mock_nexus.list_by_type.return_value = [_make_raw_nexus_entry(entry)]
    mock_nexus.ask.return_value = {"response": "They share a dance."}

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    assert mem.summarize() == "They share a dance."


# ══════════════════════════════════════════════════════════════════════════════
#  forget_old()
# ══════════════════════════════════════════════════════════════════════════════


def test_forget_old(mock_nexus):
    """forget_old() deletes entries older than the given threshold."""
    old_entry = _make_entry(content="Ancient memory.", days_old=60)
    fresh_entry = _make_entry(content="Recent memory.", days_old=5)

    nexus_old = _make_raw_nexus_entry(old_entry)
    nexus_fresh = _make_raw_nexus_entry(fresh_entry)

    # list_by_type returns both; search is used to find the Nexus id for deletion
    mock_nexus.list_by_type.return_value = [nexus_old, nexus_fresh]
    mock_nexus.search.side_effect = lambda query, limit=1: (
        [nexus_old] if old_entry.id in query else
        [nexus_fresh] if fresh_entry.id in query else []
    )
    mock_nexus.delete_entry.return_value = True

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    deleted = mem.forget_old(days=30, player_id="player")

    assert deleted == 1
    mock_nexus.delete_entry.assert_called_once_with(nexus_old["id"])


def test_forget_old_returns_zero_when_nothing_old(mock_nexus):
    """forget_old() returns 0 when all entries are within the threshold."""
    fresh = _make_entry(days_old=1)
    mock_nexus.list_by_type.return_value = [_make_raw_nexus_entry(fresh)]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    deleted = mem.forget_old(days=30)

    assert deleted == 0
    mock_nexus.delete_entry.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  forget_entry()
# ══════════════════════════════════════════════════════════════════════════════


def test_forget_entry(mock_nexus):
    """forget_entry() deletes the specific Nexus entry and returns True."""
    entry = _make_entry()
    raw = _make_raw_nexus_entry(entry)
    mock_nexus.search.return_value = [raw]
    mock_nexus.delete_entry.return_value = True

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    result = mem.forget_entry(entry.id)

    assert result is True
    mock_nexus.delete_entry.assert_called_once_with(raw["id"])


def test_forget_entry_returns_false_when_not_found(mock_nexus):
    """forget_entry() returns False when no matching Nexus entry exists."""
    mock_nexus.search.return_value = []

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    result = mem.forget_entry("nonexistent-id")

    assert result is False
    mock_nexus.delete_entry.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  get_all()
# ══════════════════════════════════════════════════════════════════════════════


def test_get_all(mock_nexus):
    """get_all() returns all memory entries for this character and player."""
    e1 = _make_entry(content="First memory.")
    e2 = _make_entry(content="Second memory.")
    e_wrong_player = _make_entry(player_id="npc_bob", content="Bob's memory.")

    mock_nexus.list_by_type.return_value = [
        _make_raw_nexus_entry(e1),
        _make_raw_nexus_entry(e2),
        _make_raw_nexus_entry(e_wrong_player),
    ]

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    results = mem.get_all(player_id="player")

    assert len(results) == 2
    contents = {r.content for r in results}
    assert "First memory." in contents
    assert "Second memory." in contents
    assert "Bob's memory." not in contents


def test_get_all_returns_empty_list_on_nexus_failure(mock_nexus):
    """get_all() returns [] when Nexus returns nothing."""
    mock_nexus.list_by_type.return_value = []

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    assert mem.get_all() == []


# ══════════════════════════════════════════════════════════════════════════════
#  CharacterMemoryInterceptor
# ══════════════════════════════════════════════════════════════════════════════


def test_interceptor_injects_memories(mock_nexus):
    """pre_call() prepends [CHARACTER MEMORY] block when memories exist."""
    entry = _make_entry(content="The player asked for a dance.", emotional_weight=0.9)
    mock_nexus.search.return_value = [_make_raw_nexus_entry(entry)]
    mock_nexus.list_by_type.return_value = [_make_raw_nexus_entry(entry)]
    mock_nexus.update_entry.return_value = True

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    interceptor = CharacterMemoryInterceptor(character_registry={"luna": mem})

    ctx = ResponseContext(
        character_id="luna",
        player_id="player",
        user_message="Let's dance",
        system_prompt="You are Luna, a graceful dancer.",
    )
    interceptor.pre_call(ctx)

    assert "[CHARACTER MEMORY]" in ctx["system_prompt"]
    assert "[/CHARACTER MEMORY]" in ctx["system_prompt"]
    assert "You remember: The player asked for a dance." in ctx["system_prompt"]
    # Original system prompt preserved
    assert "You are Luna, a graceful dancer." in ctx["system_prompt"]


def test_interceptor_no_character_id_skips(mock_nexus):
    """pre_call() does nothing when character_id is absent."""
    interceptor = CharacterMemoryInterceptor()
    ctx = ResponseContext(
        player_id="player",
        user_message="Hello",
        system_prompt="Original.",
    )
    interceptor.pre_call(ctx)

    # System prompt must not change
    assert ctx["system_prompt"] == "Original."


def test_interceptor_empty_memories_skips(mock_nexus):
    """pre_call() does not modify system_prompt when no memories are found."""
    mock_nexus.search.return_value = []
    mock_nexus.list_by_type.return_value = []

    mem = CharacterMemory("luna", nexus_client=mock_nexus)
    interceptor = CharacterMemoryInterceptor(character_registry={"luna": mem})

    ctx = ResponseContext(
        character_id="luna",
        player_id="player",
        user_message="Hi there",
        system_prompt="Original prompt.",
    )
    interceptor.pre_call(ctx)

    assert ctx["system_prompt"] == "Original prompt."


def test_interceptor_post_call_passthrough(mock_nexus):
    """post_call() does not alter the context."""
    interceptor = CharacterMemoryInterceptor()
    ctx = ResponseContext(reply="I love you.", character_id="luna")
    interceptor.post_call(ctx)
    assert ctx["reply"] == "I love you."


def test_interceptor_lazy_init_memory():
    """get_memory() lazily initialises CharacterMemory for unknown characters."""
    with patch("engine.characters.memory.get_nexus_client") as mock_factory:
        mock_factory.return_value = MagicMock()
        interceptor = CharacterMemoryInterceptor()
        mem1 = interceptor.get_memory("aria")
        mem2 = interceptor.get_memory("aria")
        assert mem1 is mem2  # same object returned on repeat call


def test_interceptor_uses_agent_id_fallback(mock_nexus):
    """pre_call() falls back to agent_id when character_id is not set."""
    entry = _make_entry(character_id="nova", content="Nova memory.")
    mock_nexus.search.return_value = [_make_raw_nexus_entry(entry)]
    mock_nexus.list_by_type.return_value = [_make_raw_nexus_entry(entry)]
    mock_nexus.update_entry.return_value = True

    mem = CharacterMemory("nova", nexus_client=mock_nexus)
    interceptor = CharacterMemoryInterceptor(character_registry={"nova": mem})

    ctx = ResponseContext(
        agent_id="nova",      # character_id not set — falls back to agent_id
        player_id="player",
        user_message="Hello Nova",
        system_prompt="",
    )
    interceptor.pre_call(ctx)

    assert "[CHARACTER MEMORY]" in ctx.get("system_prompt", "")


# ══════════════════════════════════════════════════════════════════════════════
#  get_character_memory() singleton
# ══════════════════════════════════════════════════════════════════════════════


def test_per_character_singleton():
    """get_character_memory() returns the same instance for the same id."""
    # Clear any pre-existing singletons from other tests
    _character_memory_registry.clear()

    with patch("engine.characters.memory.get_nexus_client") as mock_factory:
        mock_factory.return_value = MagicMock()
        m1 = get_character_memory("test_char_singleton")
        m2 = get_character_memory("test_char_singleton")
        assert m1 is m2


def test_per_character_singleton_different_chars():
    """get_character_memory() returns different instances for different ids."""
    _character_memory_registry.clear()

    with patch("engine.characters.memory.get_nexus_client") as mock_factory:
        mock_factory.return_value = MagicMock()
        m_luna = get_character_memory("luna_singleton_test")
        m_aria = get_character_memory("aria_singleton_test")
        assert m_luna is not m_aria
        assert m_luna._character_id == "luna_singleton_test"
        assert m_aria._character_id == "aria_singleton_test"
