"""Tests for engine/economy/economy.py.

All external services (Nexus, MCPFramework) are fully mocked so the suite
runs offline without any running servers.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_nexus_mock(initial_balance: int | None = None) -> MagicMock:
    """Return a configured MagicMock that behaves like NexusClient.

    Args:
        initial_balance: When provided, the mock's search() will return a
            matching ``balance:player`` entry so the manager sees that value
            on load.  When *None*, search returns nothing (first-run default).

    Returns:
        Configured MagicMock.
    """
    mock = MagicMock()
    mock.add_entry.return_value = "entry-abc"
    mock.update_entry.return_value = True

    if initial_balance is not None:
        balance_entry = {
            "id": "bal-001",
            "title": "balance:player",
            "content": str(initial_balance),
            "content_type": "memory",
            "category": "economy",
        }
        mock.search.return_value = [balance_entry]
    else:
        mock.search.return_value = []

    return mock


def _make_fw_mock() -> MagicMock:
    """Return a MagicMock that behaves like MCPFramework."""
    mock = MagicMock()
    mock.emit_event.return_value = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# Reusable patch context — avoids repeating the long patch path everywhere.
# ---------------------------------------------------------------------------

NEXUS_PATH = "engine.economy.economy.get_nexus_client"
FRAMEWORK_PATH = "engine.economy.economy.get_framework"


# ---------------------------------------------------------------------------
# Tests: balance
# ---------------------------------------------------------------------------


class TestGetInitialBalance:
    """test_get_initial_balance — new player gets 1000 credits by default."""

    def test_get_initial_balance(self) -> None:
        mock_nexus = _make_nexus_mock()  # search returns []
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            # Avoid polluting the global singleton
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            balance = em.get_balance("player")

        assert balance == 1000

    def test_get_initial_balance_uses_nexus_value(self) -> None:
        """When Nexus has a stored balance it is used instead of 1000."""
        mock_nexus = _make_nexus_mock(initial_balance=500)
        with patch(NEXUS_PATH, return_value=mock_nexus):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            assert em.get_balance("player") == 500


# ---------------------------------------------------------------------------
# Tests: earn / spend
# ---------------------------------------------------------------------------


class TestEarnCredits:
    """test_earn_credits — positive amount increases balance."""

    def test_earn_increases_balance(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            txn = em.transact(200, TransactionType.EARN, "bedroom", "Chore reward")

        assert txn.amount == 200
        assert txn.balance_after == 1200
        assert txn.type == TransactionType.EARN

    def test_earn_stores_correct_balance_in_nexus(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            em.transact(100, TransactionType.REWARD, "library", "Quiz win")

        # add_entry should be called for the balance and the transaction
        assert mock_nexus.add_entry.call_count >= 1
        # The balance save should use content_type="memory", category="economy"
        save_calls = [
            c
            for c in mock_nexus.add_entry.call_args_list
            if c.kwargs.get("content_type") == "memory"
            or (len(c.args) >= 3 and c.args[2] == "memory")
        ]
        assert len(save_calls) >= 1


class TestSpendCredits:
    """test_spend_credits — negative amount decreases balance."""

    def test_spend_decreases_balance(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            txn = em.transact(-300, TransactionType.SPEND, "shop", "Bought item")

        assert txn.amount == -300
        assert txn.balance_after == 700
        assert txn.type == TransactionType.SPEND


# ---------------------------------------------------------------------------
# Tests: InsufficientFundsError
# ---------------------------------------------------------------------------


class TestInsufficientFunds:
    """test_insufficient_funds_raises — guard against overspending."""

    def test_spend_more_than_balance_raises(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import (
                EconomyManager,
                InsufficientFundsError,
                TransactionType,
            )

            em = EconomyManager(nexus_client=mock_nexus)
            with pytest.raises(InsufficientFundsError) as exc_info:
                em.transact(-1500, TransactionType.SPEND, "casino", "Big bet")

        assert exc_info.value.player_id == "player"
        assert exc_info.value.balance == 1000
        assert exc_info.value.amount == -1500

    def test_balance_unchanged_after_failed_spend(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import (
                EconomyManager,
                InsufficientFundsError,
                TransactionType,
            )

            em = EconomyManager(nexus_client=mock_nexus)
            try:
                em.transact(-9999, TransactionType.BET_LOSS, "casino", "Massive loss")
            except InsufficientFundsError:
                pass

            assert em.get_balance("player") == 1000

    def test_exact_zero_is_allowed(self) -> None:
        mock_nexus = _make_nexus_mock(initial_balance=200)
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            txn = em.transact(-200, TransactionType.SPEND, "shop", "Exact spend")

        assert txn.balance_after == 0


# ---------------------------------------------------------------------------
# Tests: DEBT type
# ---------------------------------------------------------------------------


class TestDebtTransactionAllowedBelowZero:
    """test_debt_transaction_allowed_below_zero."""

    def test_debt_goes_negative(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            txn = em.transact(-1500, TransactionType.DEBT, "loan_office", "Took loan")

        assert txn.balance_after == -500
        assert txn.type == TransactionType.DEBT

    def test_check_debt_returns_owed_amount(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            em.transact(-1500, TransactionType.DEBT, "loan_office", "Took loan")
            debt = em.check_debt("player")

        assert debt == 500

    def test_check_debt_zero_when_positive_balance(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            assert em.check_debt("player") == 0


# ---------------------------------------------------------------------------
# Tests: transaction history
# ---------------------------------------------------------------------------


class TestTransactionHistory:
    """test_transaction_history — history is stored and retrievable."""

    def test_transaction_is_stored_in_nexus(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            em.transact(50, TransactionType.EARN, "bedroom", "Test earn")

        # Should have called add_entry with content_type="history"
        history_calls = [
            c
            for c in mock_nexus.add_entry.call_args_list
            if c.kwargs.get("content_type") == "history"
            or (len(c.args) >= 3 and c.args[2] == "history")
        ]
        assert len(history_calls) == 1

    def test_get_history_parses_nexus_entries(self) -> None:
        from engine.economy.economy import Transaction, TransactionType

        txn = Transaction(
            id="test-uuid-1",
            type=TransactionType.EARN,
            amount=100,
            scene="bedroom",
            description="Test",
            timestamp=time.time(),
            balance_after=1100,
        )
        history_entry = {
            "id": "nexus-1",
            "title": "txn:player:test-uuid-1",
            "content": json.dumps(txn.to_dict()),
            "content_type": "history",
            "category": "economy",
        }

        mock_nexus = _make_nexus_mock()
        mock_nexus.search.return_value = [history_entry]

        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            history = em.get_history("player", limit=10)

        assert len(history) == 1
        assert history[0].id == "test-uuid-1"
        assert history[0].type == TransactionType.EARN
        assert history[0].amount == 100

    def test_get_history_ignores_malformed_entries(self) -> None:
        bad_entry = {
            "id": "bad-1",
            "title": "txn:player:bad-uuid",
            "content": "NOT JSON {{{",
            "content_type": "history",
            "category": "economy",
        }
        mock_nexus = _make_nexus_mock()
        mock_nexus.search.return_value = [bad_entry]

        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            history = em.get_history("player")

        assert history == []

    def test_get_history_sorted_newest_first(self) -> None:
        from engine.economy.economy import Transaction, TransactionType

        now = time.time()
        entries = []
        for i, (ts, amt) in enumerate([(now - 100, 10), (now - 50, 20), (now, 30)]):
            txn = Transaction(
                id=f"uuid-{i}",
                type=TransactionType.EARN,
                amount=amt,
                scene="s",
                description="d",
                timestamp=ts,
                balance_after=1000 + amt,
            )
            entries.append(
                {
                    "id": f"ne-{i}",
                    "title": f"txn:player:uuid-{i}",
                    "content": json.dumps(txn.to_dict()),
                    "content_type": "history",
                    "category": "economy",
                }
            )

        mock_nexus = _make_nexus_mock()
        mock_nexus.search.return_value = entries

        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            history = em.get_history("player")

        amounts = [t.amount for t in history]
        assert amounts == [30, 20, 10]


# ---------------------------------------------------------------------------
# Tests: reset balance
# ---------------------------------------------------------------------------


class TestResetBalance:
    """test_reset_balance — hard-reset a player's credits."""

    def test_reset_sets_exact_amount(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            em.reset_balance("alice", amount=500)
            assert em.get_balance("alice") == 500

    def test_reset_default_is_1000(self) -> None:
        mock_nexus = _make_nexus_mock(initial_balance=50)
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            em.reset_balance("player")
            assert em.get_balance("player") == 1000

    def test_reset_does_not_create_transaction_record(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            mock_nexus.add_entry.reset_mock()
            em.reset_balance("player", 500)

        # Only the balance save call, no history call
        history_calls = [
            c
            for c in mock_nexus.add_entry.call_args_list
            if c.kwargs.get("content_type") == "history"
            or (len(c.args) >= 3 and c.args[2] == "history")
        ]
        assert len(history_calls) == 0


# ---------------------------------------------------------------------------
# Tests: singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """test_singleton — get_economy_manager returns same instance."""

    def test_singleton_returns_same_object(self) -> None:
        import engine.economy.economy as _mod

        # Reset singleton so this test is independent
        original = _mod._manager
        _mod._manager = None
        try:
            mock_nexus = _make_nexus_mock()
            with patch(NEXUS_PATH, return_value=mock_nexus):
                from engine.economy.economy import get_economy_manager

                a = get_economy_manager()
                b = get_economy_manager()
            assert a is b
        finally:
            _mod._manager = original  # restore so other tests are unaffected


# ---------------------------------------------------------------------------
# Tests: EventBus event firing
# ---------------------------------------------------------------------------


class TestFiresEconomyEvent:
    """test_fires_economy_event — emit_event called on successful transact."""

    def test_event_fired_on_earn(self) -> None:
        mock_nexus = _make_nexus_mock()
        mock_fw = _make_fw_mock()

        with (
            patch(NEXUS_PATH, return_value=mock_nexus),
            patch(FRAMEWORK_PATH, return_value=mock_fw),
        ):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            em.transact(75, TransactionType.EARN, "kitchen", "Cooked dinner")

        mock_fw.emit_event.assert_called_once()
        evt_type, *_ = mock_fw.emit_event.call_args.args
        assert evt_type == "economy.transaction"

    def test_event_payload_contains_expected_keys(self) -> None:
        mock_nexus = _make_nexus_mock()
        mock_fw = _make_fw_mock()

        with (
            patch(NEXUS_PATH, return_value=mock_nexus),
            patch(FRAMEWORK_PATH, return_value=mock_fw),
        ):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            em.transact(25, TransactionType.REWARD, "bar", "Tip received", player_id="alice")

        payload = mock_fw.emit_event.call_args.kwargs.get("payload") or {}
        for key in ("player_id", "type", "amount", "scene", "balance_after", "timestamp"):
            assert key in payload, f"Missing key '{key}' in event payload"
        assert payload["player_id"] == "alice"
        assert payload["amount"] == 25

    def test_no_event_fired_on_insufficient_funds(self) -> None:
        mock_nexus = _make_nexus_mock()
        mock_fw = _make_fw_mock()

        with (
            patch(NEXUS_PATH, return_value=mock_nexus),
            patch(FRAMEWORK_PATH, return_value=mock_fw),
        ):
            from engine.economy.economy import (
                EconomyManager,
                InsufficientFundsError,
                TransactionType,
            )

            em = EconomyManager(nexus_client=mock_nexus)
            try:
                em.transact(-9999, TransactionType.SPEND, "shop", "Failed spend")
            except InsufficientFundsError:
                pass

        mock_fw.emit_event.assert_not_called()

    def test_event_fired_even_if_framework_unavailable(self) -> None:
        """Economy must not crash if get_framework raises."""
        mock_nexus = _make_nexus_mock()

        with (
            patch(NEXUS_PATH, return_value=mock_nexus),
            patch(FRAMEWORK_PATH, side_effect=RuntimeError("no framework")),
        ):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            # Should NOT raise — framework errors are swallowed
            txn = em.transact(10, TransactionType.EARN, "test", "Framework down")

        assert txn.balance_after == 1010


# ---------------------------------------------------------------------------
# Tests: TransactionType enum
# ---------------------------------------------------------------------------


class TestTransactionTypes:
    """test_transaction_types — all required enum members present."""

    @pytest.mark.parametrize(
        "name",
        [
            "EARN",
            "SPEND",
            "BET_WIN",
            "BET_LOSS",
            "TRANSFER",
            "DEBT",
            "DEBT_PAYMENT",
            "REWARD",
            "PENALTY",
        ],
    )
    def test_type_member_exists(self, name: str) -> None:
        from engine.economy.economy import TransactionType

        assert hasattr(TransactionType, name)
        assert TransactionType[name].value == name

    def test_transaction_type_is_str(self) -> None:
        from engine.economy.economy import TransactionType

        # TransactionType(str, Enum) — values must be plain strings
        assert isinstance(TransactionType.EARN.value, str)
        # Can compare directly with string
        assert TransactionType.EARN == "EARN"


# ---------------------------------------------------------------------------
# Tests: Transaction dataclass
# ---------------------------------------------------------------------------


class TestTransactionDataclass:
    """Round-trip serialisation and field validation."""

    def test_to_dict_round_trip(self) -> None:
        from engine.economy.economy import Transaction, TransactionType

        original = Transaction(
            id="abc-123",
            type=TransactionType.BET_WIN,
            amount=500,
            scene="casino",
            description="Jackpot",
            timestamp=1_700_000_000.0,
            balance_after=1500,
        )
        restored = Transaction.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.amount == original.amount
        assert restored.scene == original.scene
        assert restored.balance_after == original.balance_after

    def test_transaction_id_is_unique(self) -> None:
        mock_nexus = _make_nexus_mock()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            t1 = em.transact(10, TransactionType.EARN, "s", "a")
            t2 = em.transact(10, TransactionType.EARN, "s", "b")

        assert t1.id != t2.id

    def test_transaction_timestamp_is_recent(self) -> None:
        mock_nexus = _make_nexus_mock()
        before = time.time()
        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            txn = em.transact(1, TransactionType.EARN, "s", "t")
        after = time.time()

        assert before <= txn.timestamp <= after


# ---------------------------------------------------------------------------
# Tests: Leaderboard
# ---------------------------------------------------------------------------


class TestLeaderboard:
    """get_leaderboard returns top credit holders sorted descending."""

    def test_leaderboard_sorted_descending(self) -> None:
        entries = [
            {
                "id": f"bal-{i}",
                "title": f"balance:player{i}",
                "content": str(v),
                "category": "economy",
            }
            for i, v in enumerate([300, 1500, 750])
        ]
        mock_nexus = _make_nexus_mock()
        mock_nexus.search.return_value = entries

        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            lb = em.get_leaderboard()

        balances = [x["balance"] for x in lb]
        assert balances == sorted(balances, reverse=True)

    def test_leaderboard_ignores_non_economy_entries(self) -> None:
        entries = [
            {"id": "x1", "title": "balance:alice", "content": "500", "category": "economy"},
            {"id": "x2", "title": "balance:bob", "content": "200", "category": "other"},
        ]
        mock_nexus = _make_nexus_mock()
        mock_nexus.search.return_value = entries

        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager

            em = EconomyManager(nexus_client=mock_nexus)
            lb = em.get_leaderboard()

        # Only the economy category entry should appear
        assert len(lb) == 1
        assert lb[0]["player_id"] == "alice"


# ---------------------------------------------------------------------------
# Tests: Multiple players
# ---------------------------------------------------------------------------


class TestMultiplePlayers:
    """Each player_id is tracked independently."""

    def test_separate_balances(self) -> None:
        mock_nexus = _make_nexus_mock()
        mock_nexus.search.return_value = []  # No stored balances

        with patch(NEXUS_PATH, return_value=mock_nexus), patch(FRAMEWORK_PATH):
            from engine.economy.economy import EconomyManager, TransactionType

            em = EconomyManager(nexus_client=mock_nexus)
            em.transact(200, TransactionType.EARN, "s", "d", player_id="alice")
            em.transact(-100, TransactionType.SPEND, "s", "d", player_id="bob")

            # alice starts at 1000 + 200 = 1200
            assert em.get_balance("alice") == 1200
            # bob starts at 1000 - 100 = 900
            assert em.get_balance("bob") == 900
