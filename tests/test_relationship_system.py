"""
tests/test_relationship_system.py — Unit tests for the CharacterMemory
relationship graph and the relationship @skill wrappers.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.agents.character_memory import CharacterMemory, get_character_memory


# ══════════════════════════════════════════════════════════════════════
#  CharacterMemory — core API
# ══════════════════════════════════════════════════════════════════════

class TestCharacterMemory:
    """Tests for CharacterMemory relationship graph methods."""

    def _mem(self, character_id: str = "lola") -> CharacterMemory:
        """Return a fresh CharacterMemory (not from registry)."""
        return CharacterMemory(character_id)

    # ── get_relationship default ──────────────────────────────────────

    def test_neutral_default_when_no_relationship_set(self):
        """Unrecorded relationship returns 0.0 (neutral)."""
        mem = self._mem()
        assert mem.get_relationship("player") == 0.0

    # ── set_relationship ──────────────────────────────────────────────

    def test_set_relationship_stores_score(self):
        mem = self._mem()
        mem.set_relationship("player", 0.5)
        assert mem.get_relationship("player") == pytest.approx(0.5)

    def test_set_relationship_clamps_above_one(self):
        mem = self._mem()
        mem.set_relationship("player", 1.5)
        assert mem.get_relationship("player") == pytest.approx(1.0)

    def test_set_relationship_clamps_below_minus_one(self):
        mem = self._mem()
        mem.set_relationship("player", -2.0)
        assert mem.get_relationship("player") == pytest.approx(-1.0)

    def test_set_relationship_exact_boundaries(self):
        mem = self._mem()
        mem.set_relationship("a", 1.0)
        mem.set_relationship("b", -1.0)
        assert mem.get_relationship("a") == pytest.approx(1.0)
        assert mem.get_relationship("b") == pytest.approx(-1.0)

    def test_set_relationship_stores_reason_in_nexus(self):
        """set_relationship calls _nexus_log without raising."""
        mem = self._mem()
        with patch.object(mem, "_nexus_log") as mock_log:
            mem.set_relationship("player", 0.3, reason="helped me")
            mock_log.assert_called_once_with("player", pytest.approx(0.3), "helped me", action="set")

    # ── update_relationship ───────────────────────────────────────────

    def test_update_relationship_from_neutral(self):
        mem = self._mem()
        new = mem.update_relationship("player", 0.2)
        assert new == pytest.approx(0.2)
        assert mem.get_relationship("player") == pytest.approx(0.2)

    def test_update_relationship_accumulates(self):
        mem = self._mem()
        mem.set_relationship("player", 0.3)
        mem.update_relationship("player", 0.2)
        assert mem.get_relationship("player") == pytest.approx(0.5)

    def test_update_relationship_clamps_at_one(self):
        mem = self._mem()
        mem.set_relationship("player", 0.9)
        new = mem.update_relationship("player", 0.5)
        assert new == pytest.approx(1.0)

    def test_update_relationship_clamps_at_minus_one(self):
        mem = self._mem()
        mem.set_relationship("player", -0.8)
        new = mem.update_relationship("player", -0.5)
        assert new == pytest.approx(-1.0)

    def test_update_relationship_returns_new_score(self):
        mem = self._mem()
        result = mem.update_relationship("player", 0.4)
        assert result == pytest.approx(0.4)

    # ── get_all_relationships ─────────────────────────────────────────

    def test_get_all_relationships_empty(self):
        mem = self._mem()
        assert mem.get_all_relationships() == {}

    def test_get_all_relationships_returns_dict(self):
        mem = self._mem()
        mem.set_relationship("player", 0.5)
        mem.set_relationship("viktor", -0.3)
        rels = mem.get_all_relationships()
        assert isinstance(rels, dict)
        assert rels["player"] == pytest.approx(0.5)
        assert rels["viktor"] == pytest.approx(-0.3)

    def test_get_all_relationships_is_copy(self):
        """Modifying the returned dict does not affect internal state."""
        mem = self._mem()
        mem.set_relationship("player", 0.5)
        rels = mem.get_all_relationships()
        rels["player"] = 0.0
        assert mem.get_relationship("player") == pytest.approx(0.5)

    def test_get_all_relationships_multiple_characters(self):
        mem = self._mem("aria")
        for name, score in [("lola", 0.8), ("viktor", 0.1), ("frankie", -0.4)]:
            mem.set_relationship(name, score)
        rels = mem.get_all_relationships()
        assert len(rels) == 3

    # ── score_label ───────────────────────────────────────────────────

    def test_score_label_trusted(self):
        mem = self._mem()
        assert mem.score_label(0.9) == "trusted"

    def test_score_label_friendly(self):
        mem = self._mem()
        assert mem.score_label(0.5) == "friendly"

    def test_score_label_neutral(self):
        mem = self._mem()
        assert mem.score_label(0.0) == "neutral"

    def test_score_label_wary(self):
        mem = self._mem()
        assert mem.score_label(-0.4) == "wary"

    def test_score_label_hostile(self):
        mem = self._mem()
        assert mem.score_label(-0.9) == "hostile"

    # ── nexus log suppressed on failure ──────────────────────────────

    def test_nexus_log_never_raises(self):
        """_nexus_log must not propagate exceptions even when nexus is unavailable."""
        mem = self._mem()
        # Call _nexus_log directly with a broken nexus import
        with patch("engine.nexus.client.get_nexus_client", side_effect=RuntimeError("nexus down")):
            mem._nexus_log("player", 0.5, "test", "set")  # must not raise


# ══════════════════════════════════════════════════════════════════════
#  get_character_memory — registry
# ══════════════════════════════════════════════════════════════════════

class TestGetCharacterMemory:
    def test_returns_character_memory_instance(self):
        mem = get_character_memory("test_char_abc")
        assert isinstance(mem, CharacterMemory)

    def test_same_instance_returned(self):
        a = get_character_memory("singleton_test_xyz")
        b = get_character_memory("singleton_test_xyz")
        assert a is b

    def test_different_ids_different_instances(self):
        a = get_character_memory("char_alpha_1")
        b = get_character_memory("char_beta_2")
        assert a is not b


# ══════════════════════════════════════════════════════════════════════
#  Relationship @skills
# ══════════════════════════════════════════════════════════════════════

class TestRelationshipSkills:
    """Tests for the @skill wrappers in relationship_skills.py."""

    def _mock_mem(self, character_id: str, **scores) -> CharacterMemory:
        """Return a CharacterMemory pre-seeded with *scores*."""
        mem = CharacterMemory(character_id)
        for other, score in scores.items():
            mem.set_relationship(other, score)
        return mem

    def _patch_registry(self, mem: CharacterMemory):
        """Patch get_character_memory to return *mem* for its character_id."""
        return patch(
            "engine.agents.character_memory.get_character_memory",
            side_effect=lambda cid: mem if cid == mem.character_id else CharacterMemory(cid),
        )

    # ── get_relationship_score ────────────────────────────────────────

    def test_get_relationship_score_returns_string(self):
        from engine.skills.builtin.relationship_skills import get_relationship_score
        mem = self._mock_mem("lola", player=0.6)
        with self._patch_registry(mem):
            result = get_relationship_score("lola", "player")
        assert isinstance(result, str)
        assert "lola" in result
        assert "player" in result

    def test_get_relationship_score_neutral_default(self):
        from engine.skills.builtin.relationship_skills import get_relationship_score
        mem = self._mock_mem("lola")
        with self._patch_registry(mem):
            result = get_relationship_score("lola", "unknown")
        assert "0.00" in result or "neutral" in result

    # ── update_relationship_score ─────────────────────────────────────

    def test_update_relationship_score_shows_change(self):
        from engine.skills.builtin.relationship_skills import update_relationship_score
        mem = self._mock_mem("lola", player=0.3)
        with self._patch_registry(mem):
            result = update_relationship_score("lola", "player", 0.2, reason="kind gesture")
        assert "→" in result or "lola" in result

    def test_update_relationship_score_applies_delta(self):
        from engine.skills.builtin.relationship_skills import update_relationship_score
        mem = self._mock_mem("lola", player=0.3)
        with self._patch_registry(mem):
            update_relationship_score("lola", "player", 0.2)
        assert mem.get_relationship("player") == pytest.approx(0.5)

    # ── get_character_relationships ───────────────────────────────────

    def test_get_character_relationships_empty(self):
        from engine.skills.builtin.relationship_skills import get_character_relationships
        mem = self._mock_mem("lola")
        with self._patch_registry(mem):
            result = get_character_relationships("lola")
        assert "neutral" in result or "no recorded" in result

    def test_get_character_relationships_lists_all(self):
        from engine.skills.builtin.relationship_skills import get_character_relationships
        mem = self._mock_mem("lola", player=0.7, viktor=-0.2)
        with self._patch_registry(mem):
            result = get_character_relationships("lola")
        assert "player" in result
        assert "viktor" in result


# ══════════════════════════════════════════════════════════════════════
#  RelationshipContextInterceptor
# ══════════════════════════════════════════════════════════════════════

class TestRelationshipContextInterceptor:
    """Tests for the system-prompt injection interceptor."""

    def _make_interceptor(self):
        from engine.agents.interceptors import RelationshipContextInterceptor
        return RelationshipContextInterceptor()

    def _ctx(self, agent_id: str = "lola", other_id: str = "player") -> dict:
        return {
            "agent_id": agent_id,
            "interlocutor_id": other_id,
            "system_prompt": "You are Lola.",
        }

    # v1.62.0 [2026-06-15] — Test rewritten to match the interceptor's real
    # contract: it reads PlayerProfile.relationships (keyed by agent_id) via
    # get_player_profile() and injects a "[RELATIONSHIP CONTEXT — <ID>]" block.
    # The previous version patched engine.agents.character_memory.get_character_memory
    # and asserted a "relationship with player" string — neither the patched
    # function nor that output format is used by RelationshipContextInterceptor
    # (stale since the interceptor was switched to PlayerProfile). Pre-existing
    # failure on origin/master; not related to the NPC↔NPC pair work on this branch.
    def test_injects_relationship_note(self):
        from engine.characters.player_profile import PlayerProfile

        interceptor = self._make_interceptor()
        profile = PlayerProfile()
        profile.update_relationship("lola", 80.0, notes="helped me out")
        ctx = self._ctx()
        # The interceptor looks up the agent_id ("lola") in PlayerProfile.relationships.
        with patch(
            "engine.agents.relationship_interceptor.get_player_profile",
            return_value=profile,
        ):
            interceptor.pre_call(ctx)
        assert "[RELATIONSHIP CONTEXT — LOLA]" in ctx["system_prompt"]
        assert "helped me out" in ctx["system_prompt"]

    def test_missing_agent_id_skips_injection(self):
        interceptor = self._make_interceptor()
        ctx = {"agent_id": "", "system_prompt": "base"}
        interceptor.pre_call(ctx)  # should not raise or modify
        assert ctx["system_prompt"] == "base"

    def test_nexus_error_does_not_raise(self):
        interceptor = self._make_interceptor()
        ctx = self._ctx()
        with patch(
            "engine.agents.character_memory.get_character_memory",
            side_effect=RuntimeError("boom"),
        ):
            interceptor.pre_call(ctx)  # must not raise
        assert ctx["system_prompt"] == "You are Lola."
