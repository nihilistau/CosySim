"""Tests for engine.skills.builtin.character_skills.

Covers:
    - get_character_state: found / not found / exception
    - adjust_trait:        valid trait / invalid trait / not found / exception
    - set_mood:            success / not found / exception
    - adjust_relationship: with reason / without reason / not found / exception
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DB_PATH = "content.simulation.database.db.Database"
_CHAR_PATH = "content.simulation.character_system.character.Character"


def _make_character(**overrides) -> MagicMock:
    """Build a mock Character with sensible defaults.

    Args:
        **overrides: Any attribute to override on the mock.

    Returns:
        A MagicMock configured to behave like a Character instance.
    """
    char = MagicMock()
    char.warmth = overrides.get("warmth", 0.60)
    char.formality = overrides.get("formality", 0.50)
    char.humor = overrides.get("humor", 0.45)
    char.flirtiness = overrides.get("flirtiness", 0.30)
    char.intelligence = overrides.get("intelligence", 0.70)
    char.creativity = overrides.get("creativity", 0.55)
    char.relationship_level = overrides.get("relationship_level", 0.40)

    char.to_dict.return_value = {
        "name": overrides.get("name", "Luna"),
        "mood": overrides.get("mood", "happy"),
        "energy": overrides.get("energy", 0.8),
        "relationship_level": char.relationship_level,
        "arousal": overrides.get("arousal", 0.2),
        "warmth": char.warmth,
        "formality": char.formality,
        "humor": char.humor,
        "flirtiness": char.flirtiness,
        "intelligence": char.intelligence,
        "creativity": char.creativity,
    }
    return char


# ---------------------------------------------------------------------------
# get_character_state
# ---------------------------------------------------------------------------

class TestGetCharacterState:
    """Tests for the get_character_state skill."""

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_found_character_returns_formatted_state(self, mock_db_cls, mock_char_cls):
        """A found character should produce a multi-line formatted summary."""
        char = _make_character(name="Luna", mood="happy", energy=0.8)
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import get_character_state

        result = get_character_state("char-1")

        assert "Name: Luna" in result
        assert "Mood: happy" in result
        assert "Energy: 0.8" in result
        assert "Relationship: 0.4" in result
        assert "Arousal: 0.2" in result
        assert "Warmth:" in result
        assert "0.60" in result  # warmth value
        mock_char_cls.load.assert_called_once_with("char-1", db=mock_db_cls.return_value)

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_not_found_character_returns_error(self, mock_db_cls, mock_char_cls):
        """When Character.load returns None, report a clear not-found message."""
        mock_char_cls.load.return_value = None

        from engine.skills.builtin.character_skills import get_character_state

        result = get_character_state("missing-id")

        assert "not found" in result.lower()
        assert "missing-id" in result

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_all_personality_traits_appear(self, mock_db_cls, mock_char_cls):
        """Every personality trait should be present in the output."""
        char = _make_character()
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import get_character_state

        result = get_character_state("char-1")

        for trait in ("Warmth", "Formality", "Humor", "Flirtiness",
                      "Intelligence", "Creativity"):
            assert trait in result, f"Missing trait {trait!r} in output"

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_missing_dict_keys_use_defaults(self, mock_db_cls, mock_char_cls):
        """Missing keys in to_dict() should fall back to '?' or 0.5."""
        char = MagicMock()
        char.to_dict.return_value = {}  # empty dict — all keys missing
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import get_character_state

        result = get_character_state("char-1")

        assert "Name: ?" in result
        assert "Mood: ?" in result
        assert "0.50" in result  # default trait value

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_database_error_returns_failure_message(self, mock_db_cls, mock_char_cls):
        """An exception during load should be caught and reported."""
        mock_char_cls.load.side_effect = RuntimeError("db connection lost")

        from engine.skills.builtin.character_skills import get_character_state

        result = get_character_state("char-1")

        assert "Failed to get character state" in result
        assert "db connection lost" in result


# ---------------------------------------------------------------------------
# adjust_trait
# ---------------------------------------------------------------------------

class TestAdjustTrait:
    """Tests for the adjust_trait skill."""

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_valid_trait_adjusts_and_saves(self, mock_db_cls, mock_char_cls):
        """Adjusting a valid trait should call adjust_trait, save, and report."""
        char = _make_character(warmth=0.60)
        # After adjust_trait is called, the attribute should reflect the new value
        char.warmth = 0.70  # simulate post-adjustment value
        mock_char_cls.load.return_value = char

        # The first getattr(char, trait, None) reads old_val before we change it.
        # We use PropertyMock to return 0.60 first, then 0.70 after adjust_trait.
        warmth_values = iter([0.60, 0.70])
        type(char).warmth = property(lambda self: next(warmth_values))

        from engine.skills.builtin.character_skills import adjust_trait

        result = adjust_trait("char-1", "warmth", 0.10)

        assert "warmth" in result
        assert "0.60" in result  # old value
        assert "0.70" in result  # new value
        char.adjust_trait.assert_called_once_with("warmth", 0.10)
        char.save.assert_called_once()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_negative_delta_decreases_trait(self, mock_db_cls, mock_char_cls):
        """A negative delta should lower the trait value."""
        char = _make_character(humor=0.45)
        humor_values = iter([0.45, 0.35])
        type(char).humor = property(lambda self: next(humor_values))
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_trait

        result = adjust_trait("char-1", "humor", -0.10)

        assert "humor" in result
        assert "0.45" in result
        assert "0.35" in result
        char.adjust_trait.assert_called_once_with("humor", -0.10)
        char.save.assert_called_once()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_invalid_trait_returns_error(self, mock_db_cls, mock_char_cls):
        """An unknown trait name should produce an error listing valid traits."""
        char = _make_character()
        # Make getattr(char, "charisma", None) return None
        del char.charisma  # ensure attribute doesn't exist
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_trait

        result = adjust_trait("char-1", "charisma", 0.10)

        assert "Unknown trait" in result
        assert "charisma" in result
        assert "warmth" in result  # valid traits listed
        char.adjust_trait.assert_not_called()
        char.save.assert_not_called()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_not_found_character_returns_error(self, mock_db_cls, mock_char_cls):
        """Adjusting a trait on a missing character should report not found."""
        mock_char_cls.load.return_value = None

        from engine.skills.builtin.character_skills import adjust_trait

        result = adjust_trait("ghost-id", "warmth", 0.10)

        assert "not found" in result.lower()
        assert "ghost-id" in result

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_exception_during_save_returns_failure(self, mock_db_cls, mock_char_cls):
        """An exception during save should be caught and reported."""
        char = _make_character()
        char.save.side_effect = IOError("disk full")
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_trait

        result = adjust_trait("char-1", "warmth", 0.05)

        assert "Failed to adjust trait" in result
        assert "disk full" in result


# ---------------------------------------------------------------------------
# set_mood
# ---------------------------------------------------------------------------

class TestSetMood:
    """Tests for the set_mood skill."""

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_success_sets_mood_and_saves(self, mock_db_cls, mock_char_cls):
        """Setting mood should call set_mood, save, and confirm."""
        char = _make_character()
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import set_mood

        result = set_mood("char-1", "excited")

        assert "excited" in result
        assert "Mood set to" in result
        char.set_mood.assert_called_once_with("excited")
        char.save.assert_called_once()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_different_mood_values(self, mock_db_cls, mock_char_cls):
        """Various mood strings should all be accepted and echoed."""
        char = _make_character()
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import set_mood

        for mood in ("happy", "sad", "nervous", "angry", "playful"):
            char.reset_mock()
            result = set_mood("char-1", mood)
            assert mood in result
            char.set_mood.assert_called_once_with(mood)

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_not_found_character_returns_error(self, mock_db_cls, mock_char_cls):
        """Setting mood on a missing character should report not found."""
        mock_char_cls.load.return_value = None

        from engine.skills.builtin.character_skills import set_mood

        result = set_mood("nope", "happy")

        assert "not found" in result.lower()
        assert "nope" in result
        # No set_mood or save should have been attempted
        mock_char_cls.return_value.set_mood.assert_not_called()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_database_instantiation(self, mock_db_cls, mock_char_cls):
        """A Database instance should be created and passed to Character.load."""
        char = _make_character()
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import set_mood

        set_mood("char-1", "happy")

        mock_db_cls.assert_called_once()
        mock_char_cls.load.assert_called_once_with(
            "char-1", db=mock_db_cls.return_value
        )

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_exception_returns_failure_message(self, mock_db_cls, mock_char_cls):
        """An exception during set_mood should be caught and reported."""
        char = _make_character()
        char.set_mood.side_effect = ValueError("invalid mood enum")
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import set_mood

        result = set_mood("char-1", "INVALID")

        assert "Failed to set mood" in result
        assert "invalid mood enum" in result


# ---------------------------------------------------------------------------
# adjust_relationship
# ---------------------------------------------------------------------------

class TestAdjustRelationship:
    """Tests for the adjust_relationship skill."""

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_success_with_reason(self, mock_db_cls, mock_char_cls):
        """Adjusting with a reason should include the reason in the output."""
        char = _make_character(relationship_level=0.40)
        # Simulate relationship change: first read → 0.40, after adjust → 0.50
        levels = iter([0.40, 0.50])
        type(char).relationship_level = property(lambda self: next(levels))
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_relationship

        result = adjust_relationship("char-1", 0.10, reason="helped with homework")

        assert "0.40" in result
        assert "0.50" in result
        assert "helped with homework" in result
        assert "reason:" in result.lower()
        char.adjust_relationship.assert_called_once_with(0.10)
        char.save.assert_called_once()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_success_without_reason(self, mock_db_cls, mock_char_cls):
        """Adjusting without a reason should omit the reason suffix."""
        char = _make_character(relationship_level=0.50)
        levels = iter([0.50, 0.60])
        type(char).relationship_level = property(lambda self: next(levels))
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_relationship

        result = adjust_relationship("char-1", 0.10)

        assert "0.50" in result
        assert "0.60" in result
        assert "reason" not in result.lower()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_empty_reason_treated_as_no_reason(self, mock_db_cls, mock_char_cls):
        """An explicit empty-string reason should behave like no reason."""
        char = _make_character(relationship_level=0.30)
        levels = iter([0.30, 0.25])
        type(char).relationship_level = property(lambda self: next(levels))
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_relationship

        result = adjust_relationship("char-1", -0.05, reason="")

        assert "reason" not in result.lower()

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_negative_delta_decreases_relationship(self, mock_db_cls, mock_char_cls):
        """A negative delta should decrease the relationship level."""
        char = _make_character(relationship_level=0.60)
        levels = iter([0.60, 0.40])
        type(char).relationship_level = property(lambda self: next(levels))
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_relationship

        result = adjust_relationship("char-1", -0.20, reason="argument")

        assert "0.60" in result
        assert "0.40" in result
        assert "argument" in result
        char.adjust_relationship.assert_called_once_with(-0.20)

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_not_found_character_returns_error(self, mock_db_cls, mock_char_cls):
        """Adjusting relationship on a missing character should report not found."""
        mock_char_cls.load.return_value = None

        from engine.skills.builtin.character_skills import adjust_relationship

        result = adjust_relationship("vanished", 0.10, reason="test")

        assert "not found" in result.lower()
        assert "vanished" in result

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_exception_returns_failure_message(self, mock_db_cls, mock_char_cls):
        """An exception during adjust_relationship should be caught and reported."""
        char = _make_character()
        char.adjust_relationship.side_effect = RuntimeError("overflow")
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_relationship

        result = adjust_relationship("char-1", 999.0)

        assert "Failed to adjust relationship" in result
        assert "overflow" in result

    @patch(_CHAR_PATH)
    @patch(_DB_PATH)
    def test_save_called_after_adjust(self, mock_db_cls, mock_char_cls):
        """Save must happen after adjust_relationship, not before."""
        call_order = []
        char = _make_character(relationship_level=0.50)
        levels = iter([0.50, 0.55])
        type(char).relationship_level = property(lambda self: next(levels))
        char.adjust_relationship.side_effect = lambda d: call_order.append("adjust")
        char.save.side_effect = lambda: call_order.append("save")
        mock_char_cls.load.return_value = char

        from engine.skills.builtin.character_skills import adjust_relationship

        adjust_relationship("char-1", 0.05)

        assert call_order == ["adjust", "save"]
