"""Tests for engine.characters.player_profile and player_profile_skills."""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from engine.characters.player_profile import (
    DecisionEntry,
    PlayerProfile,
    RelationshipEntry,
    _sentiment_from_score,
    get_player_profile,
)


# ──── helpers ────

def _fresh_profile() -> PlayerProfile:
    """Return a new, isolated PlayerProfile (not the singleton)."""
    with patch("engine.characters.player_profile.get_config") as mock_cfg:
        mock_cfg.return_value.get = lambda key, default="": default
        profile = PlayerProfile()
    return profile


def _mock_nexus_client(search_results: list | None = None) -> MagicMock:
    client = MagicMock()
    client.search.return_value = search_results or []
    client.add_entry.return_value = "nexus-entry-001"
    client.update_entry.return_value = True
    return client


# ──── RelationshipEntry ────

class TestRelationshipEntry:
    def test_defaults(self) -> None:
        entry = RelationshipEntry(character_id="lola")
        assert entry.score == 0.0
        assert entry.sentiment == "neutral"
        assert entry.interaction_count == 0
        assert entry.notes == []

    def test_to_dict_round_trip(self) -> None:
        entry = RelationshipEntry(
            character_id="viktor",
            score=42.0,
            sentiment="neutral",
            last_interaction=1_000_000.0,
            interaction_count=3,
            notes=["helped with quest"],
        )
        d = entry.to_dict()
        restored = RelationshipEntry.from_dict(d)
        assert restored.character_id == "viktor"
        assert restored.score == 42.0
        assert restored.interaction_count == 3
        assert restored.notes == ["helped with quest"]


# ──── DecisionEntry ────

class TestDecisionEntry:
    def test_to_dict_round_trip(self) -> None:
        entry = DecisionEntry(
            decision_id="d-001",
            scene="bedroom",
            description="Chose to help Lola",
            timestamp=999.0,
            consequences=["lola relationship +10"],
        )
        d = entry.to_dict()
        restored = DecisionEntry.from_dict(d)
        assert restored.decision_id == "d-001"
        assert restored.scene == "bedroom"
        assert restored.consequences == ["lola relationship +10"]


# ──── Sentiment helper ────

class TestSentimentFromScore:
    def test_close(self) -> None:
        assert _sentiment_from_score(51.0) == "close"
        assert _sentiment_from_score(100.0) == "close"

    def test_hostile(self) -> None:
        assert _sentiment_from_score(-51.0) == "hostile"
        assert _sentiment_from_score(-100.0) == "hostile"

    def test_neutral(self) -> None:
        assert _sentiment_from_score(0.0) == "neutral"
        assert _sentiment_from_score(50.0) == "neutral"
        assert _sentiment_from_score(-50.0) == "neutral"


# ──── PlayerProfile ────

class TestPlayerProfileInstantiation:
    def test_defaults(self) -> None:
        profile = _fresh_profile()
        assert profile.display_name == "Player"
        assert isinstance(profile.player_id, str) and len(profile.player_id) > 0
        assert profile.sessions == []
        assert profile.scene_visits == {}
        assert profile.relationships == {}
        assert profile.decisions == []
        assert profile.reputation == {}

    def test_nexus_key(self) -> None:
        profile = _fresh_profile()
        assert profile._nexus_key == "player_profile_v1"


class TestSessionTracking:
    def test_record_session_start_returns_string_id(self) -> None:
        profile = _fresh_profile()
        sid = profile.record_session_start("bedroom")
        assert isinstance(sid, str) and len(sid) > 0

    def test_record_session_start_increments_scene_visits(self) -> None:
        profile = _fresh_profile()
        profile.record_session_start("bedroom")
        profile.record_session_start("bedroom")
        profile.record_session_start("kitchen")
        assert profile.scene_visits["bedroom"] == 2
        assert profile.scene_visits["kitchen"] == 1

    def test_record_session_start_appends_session(self) -> None:
        profile = _fresh_profile()
        sid = profile.record_session_start("bedroom")
        assert len(profile.sessions) == 1
        assert profile.sessions[0]["session_id"] == sid
        assert profile.sessions[0]["scene"] == "bedroom"
        assert profile.sessions[0]["end_time"] is None

    def test_record_session_end_sets_end_time(self) -> None:
        profile = _fresh_profile()
        sid = profile.record_session_start("bedroom")
        before = time.time()
        profile.record_session_end(sid)
        after = time.time()
        end_time = profile.sessions[0]["end_time"]
        assert end_time is not None
        assert before <= end_time <= after

    def test_record_session_end_unknown_id_warns(self, caplog: Any) -> None:
        profile = _fresh_profile()
        import logging
        with caplog.at_level(logging.WARNING, logger="engine.characters.player_profile"):
            profile.record_session_end("nonexistent-id")
        assert "unknown session_id" in caplog.text


class TestRelationships:
    def test_update_relationship_creates_entry(self) -> None:
        profile = _fresh_profile()
        entry = profile.update_relationship("lola", 10.0)
        assert "lola" in profile.relationships
        assert entry.score == 10.0

    def test_update_relationship_clamps_max(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", 90.0)
        entry = profile.update_relationship("lola", 50.0)
        assert entry.score == 100.0

    def test_update_relationship_clamps_min(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", -90.0)
        entry = profile.update_relationship("lola", -50.0)
        assert entry.score == -100.0

    def test_update_relationship_increments_score(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", 5.0)
        entry = profile.update_relationship("lola", 15.0)
        assert entry.score == 20.0

    def test_update_relationship_sentiment_close(self) -> None:
        profile = _fresh_profile()
        entry = profile.update_relationship("lola", 80.0)
        assert entry.sentiment == "close"

    def test_update_relationship_sentiment_hostile(self) -> None:
        profile = _fresh_profile()
        entry = profile.update_relationship("lola", -80.0)
        assert entry.sentiment == "hostile"

    def test_update_relationship_sentiment_neutral(self) -> None:
        profile = _fresh_profile()
        entry = profile.update_relationship("lola", 10.0)
        assert entry.sentiment == "neutral"

    def test_update_relationship_increments_interaction_count(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", 5.0)
        profile.update_relationship("lola", 5.0)
        assert profile.relationships["lola"].interaction_count == 2

    def test_update_relationship_stores_notes(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", 5.0, notes="helped out")
        assert "helped out" in profile.relationships["lola"].notes


class TestDecisions:
    def test_record_decision_creates_entry(self) -> None:
        profile = _fresh_profile()
        entry = profile.record_decision("bedroom", "Chose to confess to Lola")
        assert isinstance(entry, DecisionEntry)
        assert entry.scene == "bedroom"
        assert entry.description == "Chose to confess to Lola"
        assert len(profile.decisions) == 1

    def test_record_decision_with_consequences(self) -> None:
        profile = _fresh_profile()
        entry = profile.record_decision("bedroom", "Helped Lola", ["lola +10"])
        assert entry.consequences == ["lola +10"]

    def test_record_decision_default_consequences_empty(self) -> None:
        profile = _fresh_profile()
        entry = profile.record_decision("bedroom", "Did nothing")
        assert entry.consequences == []

    def test_record_decision_has_unique_id(self) -> None:
        profile = _fresh_profile()
        e1 = profile.record_decision("s1", "d1")
        e2 = profile.record_decision("s2", "d2")
        assert e1.decision_id != e2.decision_id


class TestSummaries:
    def test_get_relationship_summary_no_relationships(self) -> None:
        profile = _fresh_profile()
        result = profile.get_relationship_summary()
        assert "No relationships" in result

    def test_get_relationship_summary_returns_string(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", 20.0)
        result = profile.get_relationship_summary()
        assert isinstance(result, str)
        assert "lola" in result

    def test_get_scene_summary_no_visits(self) -> None:
        profile = _fresh_profile()
        result = profile.get_scene_summary()
        assert "No scenes" in result

    def test_get_scene_summary_returns_string(self) -> None:
        profile = _fresh_profile()
        profile.record_session_start("bedroom")
        result = profile.get_scene_summary()
        assert "bedroom" in result


class TestSerialization:
    def test_to_dict_from_dict_round_trip(self) -> None:
        profile = _fresh_profile()
        profile.display_name = "Alice"
        sid = profile.record_session_start("bedroom")
        profile.record_session_end(sid)
        profile.update_relationship("lola", 30.0, notes="met her")
        profile.record_decision("bedroom", "Chose friendship", ["lola +5"])
        profile.reputation["bedroom"] = 42.0

        data = profile.to_dict()

        profile2 = _fresh_profile()
        profile2.from_dict(data)

        assert profile2.display_name == "Alice"
        assert profile2.scene_visits["bedroom"] == 1
        assert "lola" in profile2.relationships
        assert profile2.relationships["lola"].score == 30.0
        assert len(profile2.decisions) == 1
        assert profile2.reputation["bedroom"] == 42.0

    def test_to_dict_is_json_serializable(self) -> None:
        profile = _fresh_profile()
        profile.update_relationship("lola", 10.0)
        profile.record_decision("bedroom", "some choice")
        data = profile.to_dict()
        # Must not raise
        json.dumps(data)


class TestNexusPersistence:
    def test_save_calls_add_entry_first_time(self) -> None:
        profile = _fresh_profile()
        client = _mock_nexus_client()
        with patch("engine.characters.player_profile.get_nexus_client", return_value=client):
            profile.save()
        client.add_entry.assert_called_once()
        assert profile._nexus_entry_id == "nexus-entry-001"

    def test_save_calls_update_entry_on_second_save(self) -> None:
        profile = _fresh_profile()
        client = _mock_nexus_client()
        with patch("engine.characters.player_profile.get_nexus_client", return_value=client):
            profile.save()
            profile.save()
        client.update_entry.assert_called_once()

    def test_load_hydrates_profile_from_nexus(self) -> None:
        profile = _fresh_profile()
        stored_data = profile.to_dict()
        stored_data["display_name"] = "StoredPlayer"
        stored_content = json.dumps(stored_data)

        search_result = [{"id": "nexus-entry-001", "title": "player_profile_v1", "content": stored_content}]
        client = _mock_nexus_client(search_results=search_result)
        with patch("engine.characters.player_profile.get_nexus_client", return_value=client):
            profile.load()
        assert profile.display_name == "StoredPlayer"
        assert profile._nexus_entry_id == "nexus-entry-001"

    def test_load_silent_when_no_entry_found(self) -> None:
        profile = _fresh_profile()
        client = _mock_nexus_client(search_results=[])
        with patch("engine.characters.player_profile.get_nexus_client", return_value=client):
            profile.load()  # Must not raise
        assert profile.display_name == "Player"

    def test_load_silent_on_nexus_error(self) -> None:
        profile = _fresh_profile()
        client = MagicMock()
        client.search.side_effect = ConnectionError("Nexus offline")
        with patch("engine.characters.player_profile.get_nexus_client", return_value=client):
            profile.load()  # Must not raise


# ──── Singleton ────

class TestSingleton:
    def test_get_player_profile_returns_same_instance(self) -> None:
        # Reset singleton so test is self-contained
        original = PlayerProfile._instance
        PlayerProfile._instance = None
        try:
            with patch("engine.characters.player_profile.get_config") as mock_cfg:
                mock_cfg.return_value.get = lambda key, default="": default
                p1 = get_player_profile()
                p2 = get_player_profile()
            assert p1 is p2
        finally:
            PlayerProfile._instance = original


# ──── Skills ────

class TestPlayerProfileSkills:
    def test_skills_are_importable(self) -> None:
        import engine.skills.builtin.player_profile_skills as mod
        assert mod is not None

    def test_all_five_skills_exist(self) -> None:
        from engine.skills.builtin import player_profile_skills as mod
        for name in (
            "get_player_summary",
            "update_npc_relationship",
            "record_player_decision",
            "get_relationship_with",
            "get_player_reputation",
        ):
            assert hasattr(mod, name), f"Missing skill: {name}"

    def test_skills_have_correct_pack(self) -> None:
        from engine.skills.builtin import player_profile_skills  # noqa: F401 — ensures registration
        from engine.skills.registry import SKILL_REGISTRY

        skill_names = [
            "get_player_summary",
            "update_npc_relationship",
            "record_player_decision",
            "get_relationship_with",
            "get_player_reputation",
        ]
        for name in skill_names:
            meta = SKILL_REGISTRY.get_skill(name)
            assert meta is not None, f"Skill {name!r} not in registry"
            assert meta.pack == "player_profile", (
                f"Skill {name!r} has pack={meta.pack!r}, expected 'player_profile'"
            )
