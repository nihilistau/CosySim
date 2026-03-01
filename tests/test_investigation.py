"""Tests for engine/mechanics/investigation.py — CosySim v0.68 "Dark Renaissance".

All tests use isolated InvestigationBoard instances (not the process
singleton) and mock both the Nexus client and EventBus so no real HTTP
calls or side-effects occur.

Singleton tests temporarily manipulate the module-level ``_boards`` dict.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import engine.mechanics.investigation as _inv_mod
from engine.mechanics.investigation import (
    BOARD_ARENA,
    BOARD_HACKER,
    BOARD_HEIST,
    BOARD_MYSTERY,
    Clue,
    ClueType,
    Connection,
    InvestigationBoard,
    get_investigation_board,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_nexus():
    """Minimal mock NexusClient."""
    client = MagicMock()
    client.add_entry.return_value = "nexus-entry-001"
    client.list_entries.return_value = []
    client.delete_entry.return_value = True
    client.ask.return_value = {"answer": "The butler did it."}
    return client


@pytest.fixture()
def mock_bus():
    """Minimal mock EventBus."""
    bus = MagicMock()
    return bus


@pytest.fixture()
def board(mock_nexus):
    """Isolated InvestigationBoard (not the singleton) for each test."""
    return InvestigationBoard(board_id="test_board", scene="games", nexus_client=mock_nexus)


@pytest.fixture()
def board_with_clues(board):
    """Board pre-populated with two revealed clues and one hidden clue."""
    board.add_clue("Bloody Knife", "Monogrammed 'V'", ClueType.ITEM, importance=0.9)
    board.add_clue("Witness A", "Saw someone leaving", ClueType.WITNESS, importance=0.6)
    board.add_clue("Secret Note", "Encrypted message", ClueType.MESSAGE,
                   importance=0.8, revealed=False)
    return board


# ---------------------------------------------------------------------------
# ClueType
# ---------------------------------------------------------------------------

class TestClueType:
    def test_all_variants_defined(self):
        """All eight ClueType variants are present."""
        expected = {
            "EVIDENCE", "WITNESS", "LOCATION", "PERSON",
            "ITEM", "MESSAGE", "TIMELINE", "THEORY",
        }
        assert {ct.value for ct in ClueType} == expected

    def test_is_str_subclass(self):
        """ClueType is a str subclass (JSON-serialisable without extra code)."""
        assert isinstance(ClueType.EVIDENCE, str)
        assert ClueType.EVIDENCE == "EVIDENCE"


# ---------------------------------------------------------------------------
# test_add_clue
# ---------------------------------------------------------------------------

class TestAddClue:
    def test_add_clue_returns_clue(self, board):
        """add_clue returns a Clue with correct fields."""
        clue = board.add_clue(
            "Victim Photo", "Crime scene photo", ClueType.EVIDENCE,
            importance=0.8, tags=["photo", "crime"],
        )
        assert isinstance(clue, Clue)
        assert clue.title == "Victim Photo"
        assert clue.content == "Crime scene photo"
        assert clue.clue_type == ClueType.EVIDENCE
        assert clue.importance == pytest.approx(0.8)
        assert clue.tags == ["photo", "crime"]
        assert clue.board_id == "test_board"
        assert clue.scene == "games"
        assert clue.revealed is True

    def test_add_clue_id_unique(self, board):
        """Every clue receives a unique ID."""
        c1 = board.add_clue("Clue A", "Content A")
        c2 = board.add_clue("Clue B", "Content B")
        assert c1.id != c2.id
        assert c1.id.startswith("clue_")
        assert c2.id.startswith("clue_")

    def test_add_clue_default_position(self, board):
        """Default canvas position is {"x": 100, "y": 100}."""
        clue = board.add_clue("Pos Test", "body")
        assert clue.position == {"x": 100, "y": 100}

    def test_add_clue_custom_position(self, board):
        """Custom canvas position is stored correctly."""
        clue = board.add_clue("Pos Test", "body", position={"x": 300, "y": 450})
        assert clue.position == {"x": 300, "y": 450}

    def test_add_clue_hidden(self, board):
        """Clues can be created as hidden (revealed=False)."""
        clue = board.add_clue("Secret", "Hidden body", revealed=False)
        assert clue.revealed is False

    def test_add_clue_persists_to_nexus(self, board, mock_nexus):
        """add_clue calls nexus_client.add_entry with the correct arguments."""
        clue = board.add_clue("Nexus Persist", "Some content", ClueType.PERSON)
        mock_nexus.add_entry.assert_called_once()
        call_kwargs = mock_nexus.add_entry.call_args
        assert call_kwargs.kwargs["title"] == f"clue:{clue.id}"
        assert call_kwargs.kwargs["content_type"] == "note"
        assert call_kwargs.kwargs["category"] == "investigation:test_board"


# ---------------------------------------------------------------------------
# test_add_connection
# ---------------------------------------------------------------------------

class TestAddConnection:
    def test_add_connection_returns_connection(self, board):
        """add_connection returns a Connection with correct fields."""
        c1 = board.add_clue("A", "content A")
        c2 = board.add_clue("B", "content B")
        conn = board.add_connection(c1.id, c2.id, label="leads to", strength=0.9)

        assert isinstance(conn, Connection)
        assert conn.from_clue_id == c1.id
        assert conn.to_clue_id == c2.id
        assert conn.label == "leads to"
        assert conn.strength == pytest.approx(0.9)
        assert conn.board_id == "test_board"

    def test_add_connection_id_unique(self, board):
        """Each connection gets a unique ID."""
        c1 = board.add_clue("A", "x")
        c2 = board.add_clue("B", "y")
        c3 = board.add_clue("C", "z")
        conn1 = board.add_connection(c1.id, c2.id)
        conn2 = board.add_connection(c2.id, c3.id)
        assert conn1.id != conn2.id
        assert conn1.id.startswith("conn_")

    def test_add_connection_persists_to_nexus(self, board, mock_nexus):
        """add_connection calls nexus_client.add_entry."""
        c1 = board.add_clue("A", "x")
        c2 = board.add_clue("B", "y")
        mock_nexus.reset_mock()
        conn = board.add_connection(c1.id, c2.id, label="contradicts", strength=0.4)

        mock_nexus.add_entry.assert_called_once()
        call_kwargs = mock_nexus.add_entry.call_args.kwargs
        assert call_kwargs["title"] == f"connection:{conn.id}"
        assert call_kwargs["content_type"] == "note"
        assert call_kwargs["category"] == "investigation:test_board"


# ---------------------------------------------------------------------------
# test_connection_strength
# ---------------------------------------------------------------------------

class TestConnectionStrength:
    """Verify strength boundaries are stored faithfully (frontend uses them
    for rendering: strong=red, weak=grey)."""

    @pytest.mark.parametrize("strength", [0.0, 0.5, 0.7, 1.0])
    def test_connection_strength_range(self, board, strength):
        c1 = board.add_clue("X", "x")
        c2 = board.add_clue("Y", "y")
        conn = board.add_connection(c1.id, c2.id, strength=strength)
        assert conn.strength == pytest.approx(strength)


# ---------------------------------------------------------------------------
# test_get_clues_revealed_only
# ---------------------------------------------------------------------------

class TestGetCluesRevealedOnly:
    def test_get_clues_revealed_only_default(self, board_with_clues):
        """get_clues() returns only revealed clues by default."""
        clues = board_with_clues.get_clues()
        assert all(c.revealed for c in clues)

    def test_get_clues_revealed_only_explicit(self, board_with_clues):
        """get_clues(revealed_only=True) excludes hidden clues."""
        clues = board_with_clues.get_clues(revealed_only=True)
        assert len(clues) == 2
        titles = {c.title for c in clues}
        assert "Secret Note" not in titles

    def test_get_clues_sorted_by_importance(self, board_with_clues):
        """Revealed clues are returned sorted by importance descending."""
        clues = board_with_clues.get_clues(revealed_only=True)
        importances = [c.importance for c in clues]
        assert importances == sorted(importances, reverse=True)


# ---------------------------------------------------------------------------
# test_get_clues_all
# ---------------------------------------------------------------------------

class TestGetCluesAll:
    def test_get_clues_all_includes_hidden(self, board_with_clues):
        """get_clues(revealed_only=False) returns all clues."""
        clues = board_with_clues.get_clues(revealed_only=False)
        assert len(clues) == 3
        titles = {c.title for c in clues}
        assert "Secret Note" in titles


# ---------------------------------------------------------------------------
# test_get_board_state
# ---------------------------------------------------------------------------

class TestGetBoardState:
    def test_get_board_state_structure(self, board_with_clues):
        """get_board_state returns the expected top-level keys."""
        state = board_with_clues.get_board_state()
        assert set(state.keys()) == {"board_id", "scene", "clues", "connections", "deduction_count"}

    def test_get_board_state_board_id(self, board_with_clues):
        state = board_with_clues.get_board_state()
        assert state["board_id"] == "test_board"
        assert state["scene"] == "games"

    def test_get_board_state_includes_hidden_clues(self, board_with_clues):
        """Board state includes ALL clues (hidden and revealed) for the frontend."""
        state = board_with_clues.get_board_state()
        assert len(state["clues"]) == 3

    def test_get_board_state_clue_type_is_string(self, board_with_clues):
        """Clue dicts in board state have string clue_type (JSON-safe)."""
        state = board_with_clues.get_board_state()
        for clue_dict in state["clues"]:
            assert isinstance(clue_dict["clue_type"], str)

    def test_get_board_state_deduction_count_zero_initially(self, board):
        state = board.get_board_state()
        assert state["deduction_count"] == 0


# ---------------------------------------------------------------------------
# test_reveal_clue
# ---------------------------------------------------------------------------

class TestRevealClue:
    def test_reveal_clue_sets_revealed(self, board_with_clues):
        """reveal_clue flips revealed=False to revealed=True."""
        hidden = next(c for c in board_with_clues.get_clues(revealed_only=False) if not c.revealed)
        result = board_with_clues.reveal_clue(hidden.id)
        assert result is not None
        assert result.revealed is True

    def test_reveal_clue_unknown_id_returns_none(self, board):
        """reveal_clue returns None for an unknown clue ID."""
        result = board.reveal_clue("clue_doesnotexist")
        assert result is None

    def test_reveal_clue_fires_event_bus(self, board_with_clues):
        """reveal_clue publishes investigation.clue_revealed on the EventBus."""
        hidden = next(c for c in board_with_clues.get_clues(revealed_only=False) if not c.revealed)
        with patch("engine.mechanics.investigation.get_event_bus") as mock_bus_factory:
            mock_bus_instance = MagicMock()
            mock_bus_factory.return_value = mock_bus_instance
            board_with_clues.reveal_clue(hidden.id)

        mock_bus_instance.publish.assert_called_once()
        event_type = mock_bus_instance.publish.call_args.args[0]
        assert event_type == "investigation.clue_revealed"

    def test_reveal_clue_event_payload(self, board_with_clues):
        """The clue_revealed event payload contains expected keys."""
        hidden = next(c for c in board_with_clues.get_clues(revealed_only=False) if not c.revealed)
        with patch("engine.mechanics.investigation.get_event_bus") as mock_bus_factory:
            mock_bus_instance = MagicMock()
            mock_bus_factory.return_value = mock_bus_instance
            board_with_clues.reveal_clue(hidden.id)

        payload = mock_bus_instance.publish.call_args.args[1]
        assert payload["board_id"] == "test_board"
        assert payload["clue_id"] == hidden.id
        assert "title" in payload
        assert "clue_type" in payload

    def test_reveal_clue_updates_nexus(self, board_with_clues, mock_nexus):
        """reveal_clue calls nexus_client.add_entry to persist the update."""
        hidden = next(c for c in board_with_clues.get_clues(revealed_only=False) if not c.revealed)
        mock_nexus.reset_mock()
        with patch("engine.mechanics.investigation.get_event_bus"):
            board_with_clues.reveal_clue(hidden.id)
        mock_nexus.add_entry.assert_called_once()


# ---------------------------------------------------------------------------
# test_reason_calls_nexus_ask
# ---------------------------------------------------------------------------

class TestReasonCallsNexusAsk:
    def test_reason_calls_ask(self, board, mock_nexus):
        """reason() invokes nexus_client.ask exactly once."""
        board.add_clue("Clue A", "Evidence body", ClueType.EVIDENCE)
        board.reason()
        mock_nexus.ask.assert_called_once()

    def test_reason_increments_deduction_count(self, board, mock_nexus):
        """reason() increments the deduction counter."""
        board.add_clue("Clue A", "body")
        assert board._deduction_count == 0
        board.reason()
        assert board._deduction_count == 1
        board.reason()
        assert board._deduction_count == 2

    def test_reason_no_revealed_clues_returns_empty(self, board):
        """reason() returns '' when no revealed clues exist."""
        board.add_clue("Hidden", "body", revealed=False)
        result = board.reason()
        assert result == ""

    def test_reason_returns_answer_from_nexus(self, board, mock_nexus):
        """reason() returns the 'answer' value from nexus_client.ask response."""
        mock_nexus.ask.return_value = {"answer": "The suspect is Dr. Plum."}
        board.add_clue("Clue", "Some evidence")
        result = board.reason()
        assert result == "The suspect is Dr. Plum."

    def test_reason_handles_nexus_failure_gracefully(self, board, mock_nexus):
        """reason() returns '' and does not raise if nexus_client.ask raises."""
        mock_nexus.ask.side_effect = ConnectionError("Nexus offline")
        board.add_clue("Clue", "body")
        result = board.reason()
        assert result == ""


# ---------------------------------------------------------------------------
# test_reason_format
# ---------------------------------------------------------------------------

class TestReasonFormat:
    def test_reason_prompt_contains_scene(self, board, mock_nexus):
        """The NLM prompt includes the scene name."""
        board.add_clue("Evidence X", "Details here", ClueType.EVIDENCE)
        board.reason()
        prompt = mock_nexus.ask.call_args.args[0]
        assert "games" in prompt

    def test_reason_prompt_contains_clue_title(self, board, mock_nexus):
        """The NLM prompt contains each revealed clue title."""
        board.add_clue("Fingerprint Match", "Found on the weapon", ClueType.EVIDENCE)
        board.reason()
        prompt = mock_nexus.ask.call_args.args[0]
        assert "Fingerprint Match" in prompt

    def test_reason_prompt_excludes_hidden_clues(self, board, mock_nexus):
        """Hidden clues are NOT included in the NLM prompt."""
        board.add_clue("Visible Clue", "Can be seen", ClueType.EVIDENCE)
        board.add_clue("Hidden Clue", "Cannot be seen", ClueType.MESSAGE, revealed=False)
        board.reason()
        prompt = mock_nexus.ask.call_args.args[0]
        assert "Visible Clue" in prompt
        assert "Hidden Clue" not in prompt

    def test_reason_prompt_contains_connection_label(self, board, mock_nexus):
        """The NLM prompt includes connection labels."""
        c1 = board.add_clue("A", "a body")
        c2 = board.add_clue("B", "b body")
        board.add_connection(c1.id, c2.id, label="same_person")
        board.reason()
        prompt = mock_nexus.ask.call_args.args[0]
        assert "same_person" in prompt

    def test_reason_prompt_ends_with_instruction(self, board, mock_nexus):
        """The NLM prompt ends with the 2-3 paragraph instruction."""
        board.add_clue("C", "c body")
        board.reason()
        prompt = mock_nexus.ask.call_args.args[0]
        assert "2-3 paragraphs" in prompt


# ---------------------------------------------------------------------------
# test_add_theory
# ---------------------------------------------------------------------------

class TestAddTheory:
    def test_add_theory_returns_theory_clue(self, board):
        """add_theory returns a THEORY type clue."""
        clue = board.add_theory("Maybe the chef poisoned the food.")
        assert clue.clue_type == ClueType.THEORY

    def test_add_theory_contains_theory_text(self, board):
        """add_theory stores the theory string in content."""
        theory_text = "The mastermind is hiding behind a false identity."
        clue = board.add_theory(theory_text)
        assert clue.content == theory_text

    def test_add_theory_title_prefix(self, board):
        """add_theory title starts with 'Theory:'."""
        clue = board.add_theory("Someone inside the crew leaked the plan.")
        assert clue.title.startswith("Theory:")

    def test_add_theory_long_truncated_in_title(self, board):
        """Very long theory text is truncated with ellipsis in the title."""
        long_theory = "X" * 200
        clue = board.add_theory(long_theory)
        assert "…" in clue.title
        assert len(clue.title) < 100  # title remains reasonably short

    def test_add_theory_tag(self, board):
        """Theories are automatically tagged with 'theory'."""
        clue = board.add_theory("Some theory.")
        assert "theory" in clue.tags


# ---------------------------------------------------------------------------
# test_export
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_structure(self, board_with_clues):
        """export() contains 'board_state', 'clues', and 'connections'."""
        c1 = board_with_clues.get_clues(revealed_only=False)[0]
        c2 = board_with_clues.get_clues(revealed_only=False)[1]
        board_with_clues.add_connection(c1.id, c2.id)
        exported = board_with_clues.export()
        assert set(exported.keys()) == {"board_state", "clues", "connections"}

    def test_export_clues_are_dicts(self, board_with_clues):
        """Clue records in export are plain dicts (JSON-serialisable)."""
        exported = board_with_clues.export()
        for clue_dict in exported["clues"]:
            assert isinstance(clue_dict, dict)
            assert "id" in clue_dict
            assert isinstance(clue_dict["clue_type"], str)

    def test_export_connections_are_dicts(self, board_with_clues):
        """Connection records in export are plain dicts."""
        all_clues = board_with_clues.get_clues(revealed_only=False)
        board_with_clues.add_connection(all_clues[0].id, all_clues[1].id)
        exported = board_with_clues.export()
        for conn_dict in exported["connections"]:
            assert isinstance(conn_dict, dict)
            assert "strength" in conn_dict

    def test_export_includes_all_clues(self, board_with_clues):
        """export() includes hidden clues, not just revealed ones."""
        exported = board_with_clues.export()
        assert len(exported["clues"]) == 3


# ---------------------------------------------------------------------------
# test_clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_empties_in_memory_clues(self, board_with_clues):
        """After clear(), get_clues(revealed_only=False) returns []."""
        board_with_clues.clear()
        assert board_with_clues.get_clues(revealed_only=False) == []

    def test_clear_empties_connections(self, board_with_clues):
        """After clear(), get_connections() returns []."""
        all_clues = board_with_clues.get_clues(revealed_only=False)
        board_with_clues.add_connection(all_clues[0].id, all_clues[1].id)
        board_with_clues.clear()
        assert board_with_clues.get_connections() == []

    def test_clear_resets_deduction_count(self, board, mock_nexus):
        """clear() resets deduction_count to 0."""
        board.add_clue("X", "x")
        board.reason()
        assert board._deduction_count == 1
        board.clear()
        assert board._deduction_count == 0

    def test_clear_calls_nexus_delete(self, board, mock_nexus):
        """clear() deletes Nexus entries for the board category."""
        mock_nexus.list_entries.return_value = [
            {"id": "entry-001"},
            {"id": "entry-002"},
        ]
        board.clear()
        mock_nexus.list_entries.assert_called_once()
        call_kwargs = mock_nexus.list_entries.call_args.kwargs
        assert "investigation:test_board" in call_kwargs.get("category", "")
        assert mock_nexus.delete_entry.call_count == 2


# ---------------------------------------------------------------------------
# test_singleton_per_board_id
# ---------------------------------------------------------------------------

class TestSingletonPerBoardId:
    def test_same_board_id_returns_same_instance(self):
        """get_investigation_board returns the same instance for the same ID."""
        original_boards = dict(_inv_mod._boards)
        _inv_mod._boards.clear()
        try:
            b1 = get_investigation_board("singleton_test", scene="games")
            b2 = get_investigation_board("singleton_test", scene="arena")
            assert b1 is b2
        finally:
            _inv_mod._boards.clear()
            _inv_mod._boards.update(original_boards)

    def test_different_board_ids_return_different_instances(self):
        """Different board IDs produce different InvestigationBoard instances."""
        original_boards = dict(_inv_mod._boards)
        _inv_mod._boards.clear()
        try:
            b1 = get_investigation_board("board_alpha", scene="games")
            b2 = get_investigation_board("board_beta", scene="heist")
            assert b1 is not b2
        finally:
            _inv_mod._boards.clear()
            _inv_mod._boards.update(original_boards)


# ---------------------------------------------------------------------------
# test_board_id_constants
# ---------------------------------------------------------------------------

class TestBoardIdConstants:
    def test_board_hacker_value(self):
        assert BOARD_HACKER == "hacker_trail"

    def test_board_heist_value(self):
        assert BOARD_HEIST == "heist_plan"

    def test_board_mystery_value(self):
        assert BOARD_MYSTERY == "mystery"

    def test_board_arena_value(self):
        assert BOARD_ARENA == "arena_analysis"

    def test_constants_are_strings(self):
        """All board ID constants are plain str values."""
        for constant in (BOARD_HACKER, BOARD_HEIST, BOARD_MYSTERY, BOARD_ARENA):
            assert isinstance(constant, str)
            assert len(constant) > 0


# ---------------------------------------------------------------------------
# Clue / Connection serialisation round-trips
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_clue_to_dict_and_from_dict_round_trip(self, board):
        """Clue.to_dict() / Clue.from_dict() is lossless."""
        original = board.add_clue(
            "Serialise Me",
            "Round-trip body",
            ClueType.LOCATION,
            importance=0.75,
            tags=["rt", "test"],
            position={"x": 250, "y": 300},
        )
        d = original.to_dict()
        restored = Clue.from_dict(d)

        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.content == original.content
        assert restored.clue_type == original.clue_type
        assert restored.importance == pytest.approx(original.importance)
        assert restored.tags == original.tags
        assert restored.position == original.position

    def test_clue_to_dict_clue_type_is_str(self, board):
        """clue_type in to_dict() output is a plain string, not a ClueType."""
        clue = board.add_clue("T", "c", ClueType.PERSON)
        d = clue.to_dict()
        assert isinstance(d["clue_type"], str)
        assert d["clue_type"] == "PERSON"

    def test_connection_round_trip(self, board):
        """Connection.to_dict() / Connection.from_dict() is lossless."""
        c1 = board.add_clue("A", "a")
        c2 = board.add_clue("B", "b")
        original = board.add_connection(c1.id, c2.id, label="same person", strength=0.55)
        d = original.to_dict()
        restored = Connection.from_dict(d)

        assert restored.id == original.id
        assert restored.from_clue_id == original.from_clue_id
        assert restored.to_clue_id == original.to_clue_id
        assert restored.label == original.label
        assert restored.strength == pytest.approx(original.strength)
