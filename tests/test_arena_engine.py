"""Tests for engine.arena.arena_engine — 25+ test cases.

All external dependencies (Nexus, EconomyManager, EventBus, LMStudio HTTP,
get_config) are mocked.  No network calls are made.

Run with::

    python -m pytest tests/test_arena_engine.py -v --tb=short
"""
from __future__ import annotations

import importlib
import json
import sys
import uuid
from typing import List
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Patch paths (all resolved relative to the arena_engine module namespace)
# ---------------------------------------------------------------------------
_MOD = "engine.arena.arena_engine"
_NEXUS_PATH = f"{_MOD}.get_nexus_client"
_ECONOMY_PATH = f"{_MOD}.get_economy_manager"
_EVENTBUS_PATH = f"{_MOD}.get_event_bus"
_CONFIG_PATH = f"{_MOD}.get_config"
_REQUESTS_POST = f"{_MOD}.requests.post"  # legacy — kept for other tests
_CHAT_FN = "engine.lmstudio.chat.chat"

# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_nexus_mock() -> MagicMock:
    """Return a pre-configured Nexus client mock."""
    mock = MagicMock()
    mock.search.return_value = []
    mock.add_entry.return_value = str(uuid.uuid4())
    mock.ask.return_value = {"answer": "Dramatic clash of titans!"}
    return mock


def _make_economy_mock() -> MagicMock:
    """Return a pre-configured EconomyManager mock."""
    mock = MagicMock()
    mock.get_balance.return_value = 1000
    mock.transact.return_value = MagicMock()
    return mock


def _make_event_bus_mock() -> MagicMock:
    """Return a pre-configured EventBus mock."""
    mock = MagicMock()
    mock.publish.return_value = None
    return mock


def _make_config_mock(base_url: str = "http://localhost:1234") -> MagicMock:
    """Return a config mock whose ``get()`` returns *base_url*."""
    mock = MagicMock()
    mock.get.return_value = base_url
    return mock


def _make_lmstudio_response(card_name: str, reason: str = "Good choice.") -> MagicMock:
    """Return a mock ``requests.Response`` for LMStudio."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "content": f"CARD: {card_name}\nREASON: {reason}",
    }
    return resp


def _make_chat_reply(card_name: str, reason: str = "Good choice.") -> str:
    """Return a plain text reply for the unified chat() mock."""
    return f"CARD: {card_name}\nREASON: {reason}"


# ---------------------------------------------------------------------------
# Session-scoped fixture: import the module with patches active
# ---------------------------------------------------------------------------


@pytest.fixture()
def arena_mod():
    """Import (or reload) arena_engine with all singletons cleared."""
    # Ensure a fresh module each fixture invocation by forcing reload
    mod_name = "engine.arena.arena_engine"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
        # Reset singleton so tests don't bleed into each other
        mod._engine_instance = None  # type: ignore[attr-defined]
    return importlib.import_module(mod_name)


@pytest.fixture()
def mocks():
    """Return a dict of all external mocks."""
    return {
        "nexus": _make_nexus_mock(),
        "economy": _make_economy_mock(),
        "event_bus": _make_event_bus_mock(),
        "config": _make_config_mock(),
    }


@pytest.fixture()
def engine(arena_mod, mocks):
    """Return an ArenaEngine with all external deps mocked."""
    with (
        patch(_NEXUS_PATH, return_value=mocks["nexus"]),
        patch(_ECONOMY_PATH, return_value=mocks["economy"]),
        patch(_EVENTBUS_PATH, return_value=mocks["event_bus"]),
        patch(_CONFIG_PATH, return_value=mocks["config"]),
    ):
        eng = arena_mod.ArenaEngine()
    eng._mocks = mocks  # attach for assertions
    return eng


# ---------------------------------------------------------------------------
# Helper: create a minimal match inside an engine
# ---------------------------------------------------------------------------


def _quick_match(engine):
    """Create and return a match inside *engine* (no LMStudio calls)."""
    return engine.create_match("alpha", "beta")


# ===========================================================================
# Card tests
# ===========================================================================


class TestCard:
    def test_to_dict_roundtrip(self, arena_mod) -> None:
        """Card serialises and deserialises without data loss."""
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        card = Card("c1", "Iron Fist", CardType.ATTACK, 5,
                    special_effect="", flavor_text="Hits hard.")
        restored = Card.from_dict(card.to_dict())
        assert restored.id == card.id
        assert restored.name == card.name
        assert restored.card_type == CardType.ATTACK
        assert restored.power == 5
        assert restored.flavor_text == "Hits hard."

    def test_from_dict_handles_missing_optional_fields(self, arena_mod) -> None:
        """from_dict works when optional fields are absent."""
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        data = {"id": "x", "name": "Zap", "card_type": "ATTACK", "power": 3}
        card = Card.from_dict(data)
        assert card.special_effect == ""
        assert card.flavor_text == ""


# ===========================================================================
# Fighter tests
# ===========================================================================


class TestFighter:
    def test_fighter_draw_card(self, arena_mod) -> None:
        """draw_card moves cards from deck to hand."""
        Fighter = arena_mod.Fighter
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        deck = [Card(str(i), f"Card{i}", CardType.ATTACK, i) for i in range(5)]
        fighter = Fighter("f1", "Alpha", "Fighter", "qwen3-4b", deck=list(deck))
        drawn = fighter.draw_card(3)
        assert len(drawn) == 3
        assert len(fighter.hand) == 3
        assert len(fighter.deck) == 2

    def test_fighter_draw_card_exhausted_deck(self, arena_mod) -> None:
        """draw_card returns fewer cards when deck is shorter than count."""
        Fighter = arena_mod.Fighter
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        fighter = Fighter(
            "f1", "Alpha", "Fighter", "qwen3-4b",
            deck=[Card("c0", "Only", CardType.ATTACK, 3)],
        )
        drawn = fighter.draw_card(10)
        assert len(drawn) == 1
        assert len(fighter.deck) == 0

    def test_fighter_play_card(self, arena_mod) -> None:
        """play_card removes the card from hand and returns it."""
        Fighter = arena_mod.Fighter
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        c = Card("cX", "Strike", CardType.ATTACK, 4)
        fighter = Fighter("f1", "Alpha", "Fighter", "qwen3-4b", hand=[c])
        played = fighter.play_card("cX")
        assert played is c
        assert fighter.hand == []

    def test_fighter_play_card_not_found_raises(self, arena_mod) -> None:
        """play_card raises ValueError for an unknown card id."""
        Fighter = arena_mod.Fighter
        fighter = Fighter("f1", "Alpha", "Fighter", "qwen3-4b")
        with pytest.raises(ValueError, match="not found in hand"):
            fighter.play_card("ghost-id")

    def test_fighter_is_alive_with_hp(self, arena_mod) -> None:
        """is_alive returns True when HP > 0."""
        Fighter = arena_mod.Fighter
        fighter = Fighter("f1", "Alpha", "Fighter", "qwen3-4b", hp=1)
        assert fighter.is_alive() is True

    def test_fighter_is_alive_at_zero(self, arena_mod) -> None:
        """is_alive returns False when HP == 0."""
        Fighter = arena_mod.Fighter
        fighter = Fighter("f1", "Alpha", "Fighter", "qwen3-4b", hp=0)
        assert fighter.is_alive() is False

    def test_fighter_to_dict_roundtrip(self, arena_mod) -> None:
        """Fighter serialises and deserialises without data loss."""
        Fighter = arena_mod.Fighter
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        card = Card("c1", "Strike", CardType.ATTACK, 3)
        f = Fighter("f1", "Alpha", "Test persona", "qwen3-4b",
                    hp=80, max_hp=100, deck=[card], wins=2, losses=1)
        restored = Fighter.from_dict(f.to_dict())
        assert restored.id == f.id
        assert restored.hp == 80
        assert restored.wins == 2
        assert len(restored.deck) == 1
        assert restored.deck[0].name == "Strike"


# ===========================================================================
# Default deck
# ===========================================================================


class TestDefaultDeck:
    def test_default_deck_has_15_cards(self, engine, arena_mod) -> None:
        """_default_deck returns exactly 15 cards."""
        deck = engine._default_deck()
        assert len(deck) == 15

    def test_default_deck_card_type_composition(self, engine, arena_mod) -> None:
        """Default deck has correct type distribution."""
        CardType = arena_mod.CardType
        deck = engine._default_deck()
        counts = {}
        for card in deck:
            counts[card.card_type] = counts.get(card.card_type, 0) + 1
        assert counts[CardType.ATTACK] == 4
        assert counts[CardType.DEFENSE] == 3
        assert counts[CardType.SPECIAL] == 3
        assert counts[CardType.WILD] == 3
        assert counts[CardType.TRAP] == 1
        assert counts[CardType.COUNTER] == 1

    def test_default_deck_all_powers_in_range(self, engine) -> None:
        """All cards in default deck have power between 1 and 10."""
        deck = engine._default_deck()
        for card in deck:
            assert 1 <= card.power <= 10, f"{card.name} has out-of-range power {card.power}"


# ===========================================================================
# Match creation
# ===========================================================================


class TestCreateMatch:
    def test_create_match_returns_in_progress_match(self, engine, arena_mod) -> None:
        """create_match returns a match with status IN_PROGRESS."""
        MatchStatus = arena_mod.MatchStatus
        match = engine.create_match("red", "blue")
        assert match.status == MatchStatus.IN_PROGRESS
        assert match.id != ""

    def test_create_match_loads_default_fighter(self, engine, arena_mod) -> None:
        """create_match generates default fighters when not in Nexus."""
        match = engine.create_match("shadow", "blaze")
        assert match.fighter_a.id == "shadow"
        assert match.fighter_a.name == "Shadow"
        assert match.fighter_b.name == "Blaze"

    def test_create_match_loads_fighter_from_nexus(self, engine, arena_mod) -> None:
        """create_match deserialises a fighter stored in Nexus."""
        Fighter = arena_mod.Fighter
        Card = arena_mod.Card
        CardType = arena_mod.CardType

        stored_fighter = Fighter(
            id="nexus_hero",
            name="Nexus Hero",
            persona="A Nexus-trained champion",
            model_id="llama3",
            hp=100,
            max_hp=100,
            deck=[],
            wins=5,
        )
        nexus_entry = {
            "title": "fighter:nexus_hero",
            "content": json.dumps(stored_fighter.to_dict()),
        }
        engine._nexus_client.search.return_value = [nexus_entry]

        match = engine.create_match("nexus_hero", "beta")
        assert match.fighter_a.name == "Nexus Hero"
        assert match.fighter_a.wins == 5

    def test_create_match_deals_5_cards_each(self, engine) -> None:
        """Each fighter starts with exactly 5 cards in hand."""
        match = engine.create_match("a", "b")
        assert len(match.fighter_a.hand) == 5
        assert len(match.fighter_b.hand) == 5

    def test_create_match_fires_event(self, engine, arena_mod) -> None:
        """create_match fires arena.match_created on the EventBus."""
        match = engine.create_match("x", "y")
        engine._event_bus.publish.assert_called_with(
            "arena.match_created",
            {
                "match_id": match.id,
                "fighter_a": match.fighter_a.name,
                "fighter_b": match.fighter_b.name,
            },
            scene="arena",
        )

    def test_create_match_stored_in_engine(self, engine) -> None:
        """create_match registers the match so get_match can find it."""
        match = engine.create_match("p", "q")
        assert engine.get_match(match.id) is match


# ===========================================================================
# Round resolution (isolated — no LMStudio)
# ===========================================================================


class TestResolveRound:
    """Isolated _resolve_round tests using pre-built cards."""

    def _card(self, arena_mod, ctype, power, effect=""):
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        return Card(str(uuid.uuid4())[:8], ctype.value.title(), ctype, power,
                    special_effect=effect)

    def _fighters(self, arena_mod):
        Fighter = arena_mod.Fighter
        fa = Fighter("a", "Alpha", "p", "m", hp=100, max_hp=100)
        fb = Fighter("b", "Beta", "p", "m", hp=100, max_hp=100)
        return fa, fb

    def test_resolve_attack_vs_defense_attack_wins(self, engine, arena_mod) -> None:
        """ATTACK(6) vs DEFENCE(3) → fighter_a wins, damage_b=3."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.ATTACK, 6)
        cb = self._card(arena_mod, CardType.DEFENSE, 3)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["winner"] == "fighter_a"
        assert result["damage_b"] == 3
        assert result["damage_a"] == 0
        assert fb.hp == 97

    def test_resolve_attack_vs_defense_defense_wins(self, engine, arena_mod) -> None:
        """ATTACK(2) vs DEFENCE(5) → fighter_b wins (defence reflects)."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.ATTACK, 2)
        cb = self._card(arena_mod, CardType.DEFENSE, 5)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["winner"] == "fighter_b"
        assert result["damage_a"] == 3
        assert result["damage_b"] == 0

    def test_resolve_attack_vs_attack(self, engine, arena_mod) -> None:
        """ATTACK(5) vs ATTACK(3) → both take damage from opponent's power."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.ATTACK, 5)
        cb = self._card(arena_mod, CardType.ATTACK, 3)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["damage_a"] == 3
        assert result["damage_b"] == 5
        assert result["winner"] == "fighter_a"
        assert fa.hp == 97
        assert fb.hp == 95

    def test_resolve_counter_vs_attack(self, engine, arena_mod) -> None:
        """COUNTER vs ATTACK → counter wins, attacker takes double damage."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.COUNTER, 4)
        cb = self._card(arena_mod, CardType.ATTACK, 5)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["winner"] == "fighter_a"
        assert result["damage_b"] == 10  # 5 × 2
        assert result["damage_a"] == 0
        assert result["special_triggered"] == "counter"

    def test_resolve_attack_vs_counter(self, engine, arena_mod) -> None:
        """ATTACK vs COUNTER → fighter_b wins, attacker takes double damage."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.ATTACK, 4)
        cb = self._card(arena_mod, CardType.COUNTER, 3)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["winner"] == "fighter_b"
        assert result["damage_a"] == 8  # 4 × 2

    def test_resolve_defense_vs_defense(self, engine, arena_mod) -> None:
        """DEFENCE vs DEFENCE → draw, no damage."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.DEFENSE, 5)
        cb = self._card(arena_mod, CardType.DEFENSE, 7)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["winner"] == "draw"
        assert result["damage_a"] == 0
        assert result["damage_b"] == 0

    def test_resolve_special_double_damage(self, engine, arena_mod) -> None:
        """SPECIAL(double_damage, power=4) deals 8 damage to opponent."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.SPECIAL, 4, effect="double_damage")
        cb = self._card(arena_mod, CardType.ATTACK, 3)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        assert result["damage_b"] == 8
        assert result["special_triggered"] == "double_damage"

    def test_resolve_special_heal(self, engine, arena_mod) -> None:
        """SPECIAL(heal) restores HP to the attacker."""
        CardType = arena_mod.CardType
        Fighter = arena_mod.Fighter
        ca = self._card(arena_mod, CardType.SPECIAL, 4, effect="heal")
        cb = self._card(arena_mod, CardType.ATTACK, 3)
        fa = Fighter("a", "Alpha", "p", "m", hp=60, max_hp=100)
        fb = Fighter("b", "Beta", "p", "m", hp=100, max_hp=100)
        engine._resolve_round(ca, cb, fa, fb)
        # Heal = min(4*2, 100-60) = 8
        assert fa.hp == 68

    def test_resolve_wild_randomizes(self, engine, arena_mod) -> None:
        """WILD card results in a special_triggered label with its resolved type."""
        CardType = arena_mod.CardType
        ca = self._card(arena_mod, CardType.WILD, 3)
        cb = self._card(arena_mod, CardType.DEFENSE, 2)
        fa, fb = self._fighters(arena_mod)
        result = engine._resolve_round(ca, cb, fa, fb)
        # WILD resolves to some concrete type; special_triggered should reflect it
        # (may also be empty if WILD resolved to DEFENSE → draw scenario)
        assert isinstance(result["special_triggered"], str)
        assert isinstance(result["winner"], str)

    def test_resolve_trap_sets_pending(self, engine, arena_mod) -> None:
        """Playing a TRAP card sets pending_trap on the match for next round."""
        CardType = arena_mod.CardType
        ArenaMatch = arena_mod.ArenaMatch
        Fighter = arena_mod.Fighter
        fa = Fighter("a", "Alpha", "p", "m", hp=100, max_hp=100)
        fb = Fighter("b", "Beta", "p", "m", hp=100, max_hp=100)
        match = ArenaMatch(
            id="m1", fighter_a=fa, fighter_b=fb,
            status=arena_mod.MatchStatus.IN_PROGRESS,
        )
        trap = self._card(arena_mod, CardType.TRAP, 5)
        cb = self._card(arena_mod, CardType.ATTACK, 3)
        engine._resolve_round(trap, cb, fa, fb, match)
        assert match.pending_trap_b is trap
        # No immediate damage from trap
        assert fb.hp == 100

    def test_pending_trap_fires_next_round(self, engine, arena_mod) -> None:
        """A pending trap doubles its power and deals damage in the next round."""
        CardType = arena_mod.CardType
        ArenaMatch = arena_mod.ArenaMatch
        Fighter = arena_mod.Fighter
        Card = arena_mod.Card
        fa = Fighter("a", "Alpha", "p", "m", hp=100, max_hp=100)
        fb = Fighter("b", "Beta", "p", "m", hp=100, max_hp=100)
        trap = Card("t1", "Pit Snare", CardType.TRAP, 5)
        match = ArenaMatch(
            id="m1", fighter_a=fa, fighter_b=fb,
            status=arena_mod.MatchStatus.IN_PROGRESS,
            pending_trap_b=trap,
        )
        ca = self._card(arena_mod, CardType.ATTACK, 2)
        cb = self._card(arena_mod, CardType.ATTACK, 2)
        result = engine._resolve_round(ca, cb, fa, fb, match)
        # Trap fires: 5 * 2 = 10 damage to B, plus 2 from A's attack
        assert result["damage_b"] >= 10
        assert match.pending_trap_b is None


# ===========================================================================
# play_round integration
# ===========================================================================


class TestPlayRound:
    def test_play_round_updates_hp(self, engine, arena_mod) -> None:
        """HP changes after a round (at least one fighter takes damage or healing)."""
        match = engine.create_match("a", "b")
        initial_hp_a = match.fighter_a.hp
        initial_hp_b = match.fighter_b.hp

        card_a = match.fighter_a.hand[0]
        card_b = match.fighter_b.hand[0]

        replies = iter([_make_chat_reply(card_a.name), _make_chat_reply(card_b.name)])
        with patch(_CHAT_FN, side_effect=lambda *a, **kw: next(replies)):
            outcome = engine.play_round(match.id)

        assert isinstance(outcome, arena_mod.RoundOutcome)
        assert outcome.round_num == 1
        # At least one HP changed or it was a draw with no damage
        total_damage = outcome.damage_a + outcome.damage_b
        if total_damage > 0:
            assert (
                match.fighter_a.hp < initial_hp_a
                or match.fighter_b.hp < initial_hp_b
            )

    def test_play_round_fires_event_bus(self, engine, arena_mod) -> None:
        """play_round fires arena.round_complete on the EventBus."""
        match = engine.create_match("a", "b")
        card_a = match.fighter_a.hand[0]
        card_b = match.fighter_b.hand[0]

        replies = iter([_make_chat_reply(card_a.name), _make_chat_reply(card_b.name)])
        with patch(_CHAT_FN, side_effect=lambda *a, **kw: next(replies)):
            engine.play_round(match.id)

        calls = [
            str(c) for c in engine._event_bus.publish.call_args_list
        ]
        assert any("round_complete" in c for c in calls)

    def test_play_round_appends_to_history(self, engine, arena_mod) -> None:
        """Each play_round call appends to match.rounds."""
        match = engine.create_match("a", "b")

        def side_effects(*args, **kwargs):
            name = (match.fighter_a.hand[0].name
                    if match.fighter_a.hand else "Iron Fist")
            return _make_chat_reply(name)

        with patch(_CHAT_FN, side_effect=side_effects):
            for _ in range(3):
                if match.status == arena_mod.MatchStatus.IN_PROGRESS:
                    engine.play_round(match.id)

        assert len(match.rounds) == 3

    def test_play_round_bad_match_id_raises(self, engine) -> None:
        """play_round raises ValueError for an unknown match id."""
        with pytest.raises(ValueError, match="not found"):
            engine.play_round("nonexistent-id")

    def test_match_ends_at_max_rounds(self, engine, arena_mod) -> None:
        """Match status becomes COMPLETE after max_rounds rounds."""
        match = engine.create_match("a", "b")
        match.max_rounds = 2

        with patch(_CHAT_FN, return_value=_make_chat_reply("Iron Fist")):
            for _ in range(2):
                if match.status == arena_mod.MatchStatus.IN_PROGRESS:
                    engine.play_round(match.id)

        assert match.status == arena_mod.MatchStatus.COMPLETE
        assert match.winner is not None

    def test_match_ends_on_ko(self, engine, arena_mod) -> None:
        """Match ends immediately when a fighter's HP reaches 0."""
        match = engine.create_match("a", "b")
        # Force fighter_b to be nearly dead
        match.fighter_b.hp = 1

        card_a = next(
            c for c in match.fighter_a.hand
            if c.card_type == arena_mod.CardType.ATTACK
        ) if any(c.card_type == arena_mod.CardType.ATTACK
                 for c in match.fighter_a.hand) else match.fighter_a.hand[0]
        card_b = match.fighter_b.hand[0]

        replies = iter([_make_chat_reply(card_a.name), _make_chat_reply(card_b.name)])
        with patch(_CHAT_FN, side_effect=lambda *a, **kw: next(replies)):
            engine.play_round(match.id)

        # fighter_b is dead → match should be complete with fighter_a winning
        # (assuming ATTACK dealt at least 1 damage)
        if match.fighter_b.hp == 0:
            assert match.status == arena_mod.MatchStatus.COMPLETE
            assert match.winner == "fighter_a"


# ===========================================================================
# Agent card selection
# ===========================================================================


class TestAgentPickCard:
    def test_agent_pick_card_parses_response(self, engine, arena_mod) -> None:
        """_agent_pick_card returns the card named in the LMStudio response."""
        match = engine.create_match("x", "y")
        fa = match.fighter_a
        target_card = fa.hand[0]

        with patch(_CHAT_FN, return_value=_make_chat_reply(target_card.name, "Best play here.")):
            card, reasoning = engine._agent_pick_card(fa, match)

        assert card.name == target_card.name
        assert "Best play here." in reasoning

    def test_agent_pick_card_fallback_on_bad_response(self, engine, arena_mod) -> None:
        """_agent_pick_card picks a random card when the LLM response is garbled."""
        match = engine.create_match("x", "y")
        fa = match.fighter_a

        with patch(_CHAT_FN, return_value="I don't know what to play!"):
            card, reasoning = engine._agent_pick_card(fa, match)

        assert card is not None
        assert "fallback" in reasoning.lower()

    def test_agent_pick_card_fallback_on_request_error(self, engine, arena_mod) -> None:
        """_agent_pick_card picks randomly when HTTP request raises."""
        match = engine.create_match("x", "y")
        fa = match.fighter_a

        with patch(_CHAT_FN, side_effect=Exception("Connection refused")):
            card, reasoning = engine._agent_pick_card(fa, match)

        assert card is not None

    def test_agent_pick_card_removes_from_hand(self, engine, arena_mod) -> None:
        """The chosen card is removed from the fighter's hand."""
        match = engine.create_match("x", "y")
        fa = match.fighter_a
        initial_hand_size = len(fa.hand)
        target = fa.hand[0]

        with patch(_CHAT_FN, return_value=_make_chat_reply(target.name)):
            engine._agent_pick_card(fa, match)

        assert len(fa.hand) == initial_hand_size - 1
        assert all(c.id != target.id for c in fa.hand)


# ===========================================================================
# Commentary generation
# ===========================================================================


class TestGenerateCommentary:
    def test_generate_commentary_uses_nexus(self, engine, arena_mod) -> None:
        """_generate_commentary calls nexus_client.ask."""
        match = engine.create_match("x", "y")
        engine._generate_commentary(
            {"card_a_name": "Strike", "card_b_name": "Shield",
             "winner": "fighter_a", "damage_a": 0, "damage_b": 5,
             "round_num": 1},
            match,
        )
        engine._nexus_client.ask.assert_called_once()

    def test_generate_commentary_fallback_on_nexus_error(self, engine, arena_mod) -> None:
        """_generate_commentary returns template string when Nexus fails."""
        match = engine.create_match("x", "y")
        engine._nexus_client.ask.side_effect = Exception("Nexus offline")
        commentary = engine._generate_commentary(
            {"card_a_name": "Iron Fist", "card_b_name": "Shield",
             "winner": "fighter_a", "damage_a": 0, "damage_b": 4,
             "round_num": 1},
            match,
        )
        assert match.fighter_a.name in commentary or "Iron Fist" in commentary
        assert isinstance(commentary, str)
        assert len(commentary) > 0


# ===========================================================================
# Betting
# ===========================================================================


class TestBetting:
    def test_place_bet_deducts_economy(self, engine, arena_mod) -> None:
        """place_bet calls economy.transact with a negative amount."""
        match = engine.create_match("a", "b")
        engine.place_bet(match.id, "match_winner", "fighter_a", 100)
        calls = engine._economy.transact.call_args_list
        assert any(args[0][0] == -100 for args in calls)

    def test_place_bet_returns_bet_object(self, engine, arena_mod) -> None:
        """place_bet returns a Bet dataclass with correct fields."""
        match = engine.create_match("a", "b")
        bet = engine.place_bet(match.id, "match_winner", "fighter_b", 50)
        assert bet.target == "fighter_b"
        assert bet.amount == 50
        assert bet.resolved is False

    def test_place_bet_added_to_match(self, engine, arena_mod) -> None:
        """The placed bet appears in match.bets."""
        match = engine.create_match("a", "b")
        bet = engine.place_bet(match.id, "match_winner", "fighter_a", 25)
        assert any(b.id == bet.id for b in match.bets)

    def test_place_bet_invalid_amount_raises(self, engine) -> None:
        """place_bet rejects non-positive amounts."""
        match = engine.create_match("a", "b")
        with pytest.raises(ValueError, match="positive"):
            engine.place_bet(match.id, "match_winner", "fighter_a", 0)

    def test_place_bet_economy_failure_raises(self, engine, arena_mod) -> None:
        """place_bet raises ValueError when economy.transact fails."""
        match = engine.create_match("a", "b")
        engine._economy.transact.side_effect = Exception("Insufficient funds")
        with pytest.raises(ValueError, match="Economy deduction failed"):
            engine.place_bet(match.id, "match_winner", "fighter_a", 999)

    def test_resolve_bets_match_winner_win(self, engine, arena_mod) -> None:
        """Winning match_winner bet pays out at 2.0× odds."""
        match = engine.create_match("a", "b")
        bet = engine.place_bet(match.id, "match_winner", "fighter_a", 100)
        # Force match completion
        match.status = arena_mod.MatchStatus.COMPLETE
        match.winner = "fighter_a"

        # Reset transact mock so we can check the payout call specifically
        engine._economy.transact.reset_mock()
        resolved = engine.resolve_bets(match.id)
        winning_bet = next(b for b in resolved if b.id == bet.id)
        assert winning_bet.won is True
        assert winning_bet.payout == 200  # 100 × 2.0
        # Payout credited via economy
        engine._economy.transact.assert_called_once()
        call_args = engine._economy.transact.call_args[0]
        assert call_args[0] == 200

    def test_resolve_bets_match_winner_loss(self, engine, arena_mod) -> None:
        """Losing match_winner bet results in zero payout."""
        match = engine.create_match("a", "b")
        bet = engine.place_bet(match.id, "match_winner", "fighter_a", 50)
        match.status = arena_mod.MatchStatus.COMPLETE
        match.winner = "fighter_b"  # bettor picked wrong

        engine._economy.transact.reset_mock()
        resolved = engine.resolve_bets(match.id)
        losing_bet = next(b for b in resolved if b.id == bet.id)
        assert losing_bet.won is False
        assert losing_bet.payout == 0
        engine._economy.transact.assert_not_called()

    def test_resolve_bets_round_winner(self, engine, arena_mod) -> None:
        """Winning round_winner bet pays out at 1.8× odds."""
        RoundOutcome = arena_mod.RoundOutcome
        Card = arena_mod.Card
        CardType = arena_mod.CardType
        match = engine.create_match("a", "b")
        fake_card = Card("cx", "Fake", CardType.ATTACK, 3)
        fake_round = RoundOutcome(
            round_num=1,
            fighter_a_card=fake_card,
            fighter_b_card=fake_card,
            fighter_a_reasoning="",
            fighter_b_reasoning="",
            winner="fighter_b",
            damage_a=3,
            damage_b=0,
            commentary="test",
        )
        match.rounds.append(fake_round)
        bet = engine.place_bet(
            match.id, "round_winner", "fighter_b", 100, round_num=1
        )
        match.status = arena_mod.MatchStatus.COMPLETE
        match.winner = "fighter_b"

        engine._economy.transact.reset_mock()
        resolved = engine.resolve_bets(match.id)
        winning_bet = next(b for b in resolved if b.id == bet.id)
        assert winning_bet.won is True
        assert winning_bet.payout == 180  # 100 × 1.8

    def test_resolve_bets_not_complete_raises(self, engine) -> None:
        """resolve_bets raises ValueError for a non-COMPLETE match."""
        match = engine.create_match("a", "b")
        with pytest.raises(ValueError, match="not COMPLETE"):
            engine.resolve_bets(match.id)


# ===========================================================================
# Query methods
# ===========================================================================


class TestQueryMethods:
    def test_get_match_returns_match(self, engine) -> None:
        """get_match returns the correct ArenaMatch by id."""
        match = engine.create_match("a", "b")
        found = engine.get_match(match.id)
        assert found is match

    def test_get_match_unknown_returns_none(self, engine) -> None:
        """get_match returns None for an unknown id."""
        assert engine.get_match("totally-fake-id") is None

    def test_get_fighter_profile(self, engine) -> None:
        """get_fighter_profile returns a fighter after match creation."""
        engine.create_match("warrior", "mage")
        assert engine.get_fighter_profile("warrior") is not None
        assert engine.get_fighter_profile("ghost") is None

    def test_leaderboard_returns_list(self, engine) -> None:
        """get_leaderboard returns a list (possibly empty) of dicts."""
        board = engine.get_leaderboard()
        assert isinstance(board, list)

    def test_leaderboard_sorted_by_wins(self, engine, arena_mod) -> None:
        """get_leaderboard entries are sorted descending by wins."""
        engine.create_match("lion", "tiger")
        engine._fighter_profiles["lion"].wins = 10
        engine._fighter_profiles["tiger"].wins = 3
        board = engine.get_leaderboard()
        wins = [e["wins"] for e in board]
        assert wins == sorted(wins, reverse=True)

    def test_leaderboard_respects_limit(self, engine, arena_mod) -> None:
        """get_leaderboard(limit=1) returns at most 1 entry."""
        for i in range(5):
            engine.create_match(f"f{i}", f"g{i}")
        board = engine.get_leaderboard(limit=1)
        assert len(board) <= 1


# ===========================================================================
# Singleton
# ===========================================================================


class TestSingleton:
    def test_singleton_same_instance(self, arena_mod, mocks) -> None:
        """get_arena_engine returns the same object on repeated calls."""
        arena_mod._engine_instance = None  # reset
        with (
            patch(_NEXUS_PATH, return_value=mocks["nexus"]),
            patch(_ECONOMY_PATH, return_value=mocks["economy"]),
            patch(_EVENTBUS_PATH, return_value=mocks["event_bus"]),
            patch(_CONFIG_PATH, return_value=mocks["config"]),
        ):
            eng1 = arena_mod.get_arena_engine()
            eng2 = arena_mod.get_arena_engine()
        assert eng1 is eng2

    def test_singleton_reset_creates_new(self, arena_mod, mocks) -> None:
        """Resetting _engine_instance forces a new object on next call."""
        arena_mod._engine_instance = None
        with (
            patch(_NEXUS_PATH, return_value=mocks["nexus"]),
            patch(_ECONOMY_PATH, return_value=mocks["economy"]),
            patch(_EVENTBUS_PATH, return_value=mocks["event_bus"]),
            patch(_CONFIG_PATH, return_value=mocks["config"]),
        ):
            eng1 = arena_mod.get_arena_engine()
        arena_mod._engine_instance = None
        with (
            patch(_NEXUS_PATH, return_value=mocks["nexus"]),
            patch(_ECONOMY_PATH, return_value=mocks["economy"]),
            patch(_EVENTBUS_PATH, return_value=mocks["event_bus"]),
            patch(_CONFIG_PATH, return_value=mocks["config"]),
        ):
            eng2 = arena_mod.get_arena_engine()
        assert eng1 is not eng2
