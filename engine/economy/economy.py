"""Cross-scene credit economy backed by Nexus.

Provides persistent credit balances and full transaction history for all
players across every CosySim scene.  Balance records and transaction logs
are stored as Nexus entries so they survive restarts and are queryable by
the wider knowledge layer.

Usage::

    from engine.economy import get_economy_manager, TransactionType

    em = get_economy_manager()
    txn = em.transact(50, TransactionType.EARN, "bedroom", "Won mini-game")
    print(txn.balance_after)   # 1050
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-safe top-level imports — needed so patch() can target these names
# ---------------------------------------------------------------------------

try:
    from engine.nexus.client import get_nexus_client
except Exception:  # pragma: no cover
    get_nexus_client = None  # type: ignore[assignment]

try:
    from engine.mcp.framework import get_framework
except Exception:  # pragma: no cover
    get_framework = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Sentinel so callers can distinguish "no Nexus" from "balance is 0"
# ---------------------------------------------------------------------------
_DEFAULT_BALANCE = 1000
_NEXUS_CREATED_BY = "cosysim"


# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------


class TransactionType(str, Enum):
    """All possible directions a credit balance can move."""

    EARN = "EARN"
    SPEND = "SPEND"
    BET_WIN = "BET_WIN"
    BET_LOSS = "BET_LOSS"
    TRANSFER = "TRANSFER"
    DEBT = "DEBT"
    DEBT_PAYMENT = "DEBT_PAYMENT"
    REWARD = "REWARD"
    PENALTY = "PENALTY"


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass
class Transaction:
    """An immutable record of a single credit movement.

    Attributes:
        id: Unique UUID string for this transaction.
        type: The :class:`TransactionType` that describes the movement.
        amount: Signed credit delta (positive = gain, negative = loss).
        scene: Scene identifier where the transaction originated.
        description: Human-readable description for UI / Nexus.
        timestamp: Unix epoch float when the transaction was recorded.
        balance_after: Player balance immediately after this transaction.
    """

    id: str
    type: TransactionType
    amount: int
    scene: str
    description: str
    timestamp: float
    balance_after: int

    def to_dict(self) -> Dict:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "id": self.id,
            "type": self.type.value,
            "amount": self.amount,
            "scene": self.scene,
            "description": self.description,
            "timestamp": self.timestamp,
            "balance_after": self.balance_after,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Transaction":
        """Deserialise from a plain dict produced by :meth:`to_dict`.

        Args:
            data: Dictionary previously produced by :meth:`to_dict`.

        Returns:
            A reconstructed :class:`Transaction`.
        """
        return cls(
            id=data["id"],
            type=TransactionType(data["type"]),
            amount=int(data["amount"]),
            scene=data["scene"],
            description=data["description"],
            timestamp=float(data["timestamp"]),
            balance_after=int(data["balance_after"]),
        )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InsufficientFundsError(Exception):
    """Raised when a spend/loss transaction would push a balance below zero.

    Not raised for :attr:`TransactionType.DEBT` transactions, which are
    explicitly allowed to go negative.
    """

    def __init__(self, player_id: str, balance: int, amount: int) -> None:
        self.player_id = player_id
        self.balance = balance
        self.amount = amount
        super().__init__(
            f"Player '{player_id}' has {balance} credits — "
            f"cannot spend {abs(amount)} (shortfall {abs(amount) - balance})."
        )


# ---------------------------------------------------------------------------
# Types where going below zero is intentional
# ---------------------------------------------------------------------------
_DEBT_TYPES = frozenset({TransactionType.DEBT})


# ---------------------------------------------------------------------------
# Main manager
# ---------------------------------------------------------------------------


class EconomyManager:
    """Cross-scene economy manager backed by Nexus for persistence.

    Stores balance records and transaction history as Nexus entries so that
    credit data survives process restarts and is queryable by other CosySim
    systems.

    Nexus storage layout:

    * **Balance**: ``content_type="memory"``, ``category="economy"``,
      ``title="balance:{player_id}"``, content = integer as string.
    * **Transaction**: ``content_type="history"``, ``category="economy"``,
      ``title="txn:{player_id}:{txn_id}"``, content = JSON of
      :meth:`Transaction.to_dict`.

    Args:
        nexus_client: Optional pre-built Nexus client.  When omitted the
            global singleton returned by :func:`get_nexus_client` is used.
    """

    def __init__(self, nexus_client=None) -> None:
        if nexus_client is None:
            nexus_client = get_nexus_client()
        self._nexus = nexus_client
        self._lock = threading.Lock()
        # In-process balance cache: {player_id: balance}
        self._cache: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_balance(self, player_id: str = "player") -> int:
        """Return the current credit balance for *player_id*.

        Loads from Nexus on first access; subsequent calls within the same
        process use a thread-safe in-process cache that is invalidated on
        every successful :meth:`transact` call.

        Args:
            player_id: Identifier of the player whose balance to query.

        Returns:
            Integer credit balance (always >= 0 unless DEBT was used).
        """
        with self._lock:
            if player_id not in self._cache:
                self._cache[player_id] = self._load_balance(player_id)
            return self._cache[player_id]

    def transact(
        self,
        amount: int,
        type: TransactionType,
        scene: str,
        description: str,
        player_id: str = "player",
    ) -> Transaction:
        """Apply a credit movement and persist it.

        A positive *amount* always increases the balance (regardless of
        :class:`TransactionType`).  Pass a **negative** *amount* to decrease
        the balance.

        Args:
            amount: Signed credit delta.  Positive = gain, negative = loss.
            type: Category of the movement (affects debt rules and UI).
            scene: Scene identifier where the transaction originated.
            description: Human-readable description (stored in Nexus).
            player_id: Target player.  Defaults to ``"player"``.

        Returns:
            A fully-populated :class:`Transaction` dataclass.

        Raises:
            InsufficientFundsError: If the resulting balance would be
                negative and *type* is not :attr:`TransactionType.DEBT`.
        """
        with self._lock:
            current = self._cache.get(player_id) or self._load_balance(player_id)
            new_balance = current + amount

            if new_balance < 0 and type not in _DEBT_TYPES:
                raise InsufficientFundsError(player_id, current, amount)

            txn = Transaction(
                id=str(uuid.uuid4()),
                type=type,
                amount=amount,
                scene=scene,
                description=description,
                timestamp=time.time(),
                balance_after=new_balance,
            )

            # Persist balance + transaction record
            self._save_balance(player_id, new_balance)
            self._save_transaction(player_id, txn)

            # Update cache
            self._cache[player_id] = new_balance

        # Fire event outside the lock to avoid potential deadlocks
        self._fire_event(player_id, txn)
        logger.info(
            "Economy [%s] %s %+d -> %d (%s)",
            player_id,
            type.value,
            amount,
            txn.balance_after,
            scene,
        )
        return txn

    def get_history(
        self, player_id: str = "player", limit: int = 50
    ) -> List[Transaction]:
        """Retrieve transaction history for *player_id* from Nexus.

        Results are sorted newest-first.

        Args:
            player_id: Target player.
            limit: Maximum number of records to return.

        Returns:
            List of :class:`Transaction` objects, newest first.
        """
        raw = self._nexus.search(f"txn:{player_id}:", limit=limit)
        transactions: List[Transaction] = []
        for entry in raw:
            if (
                entry.get("category") == "economy"
                and entry.get("content_type") == "history"
                and entry.get("title", "").startswith(f"txn:{player_id}:")
            ):
                try:
                    data = json.loads(entry.get("content", "{}"))
                    transactions.append(Transaction.from_dict(data))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    logger.debug("Skipping malformed transaction entry: %s", exc)
        return sorted(transactions, key=lambda t: t.timestamp, reverse=True)

    def get_leaderboard(self) -> List[dict]:
        """Return the top credit holders across all players.

        Queries Nexus for all ``balance:`` entries in the ``economy``
        category and returns them sorted by balance descending.

        Returns:
            List of dicts with keys ``player_id`` and ``balance``, sorted
            by balance highest-first.
        """
        raw = self._nexus.search("balance:", limit=100)
        leaders: List[dict] = []
        for entry in raw:
            title: str = entry.get("title", "")
            if title.startswith("balance:") and entry.get("category") == "economy":
                player_id = title[len("balance:"):]
                try:
                    balance = int(entry.get("content", "0"))
                    leaders.append({"player_id": player_id, "balance": balance})
                except (ValueError, TypeError):
                    continue
        return sorted(leaders, key=lambda x: x["balance"], reverse=True)

    def reset_balance(self, player_id: str, amount: int = 1000) -> None:
        """Hard-reset a player balance to *amount*.

        Intended for new-player setup and test fixtures.  Does **not** write
        a transaction record so it does not appear in history.

        Args:
            player_id: Target player.
            amount: New balance value (default 1000).
        """
        with self._lock:
            self._save_balance(player_id, amount)
            self._cache[player_id] = amount
        logger.info("Economy: balance reset for '%s' -> %d", player_id, amount)

    def check_debt(self, player_id: str = "player") -> int:
        """Return the amount by which the player's balance is negative.

        A return value of 0 means the player is not in debt.

        Args:
            player_id: Target player.

        Returns:
            Absolute debt amount (>= 0).  Zero when not in debt.
        """
        balance = self.get_balance(player_id)
        return abs(balance) if balance < 0 else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_balance(self, player_id: str) -> int:
        """Load balance from Nexus; returns ``_DEFAULT_BALANCE`` if absent.

        Args:
            player_id: Target player.

        Returns:
            Integer balance.
        """
        title = f"balance:{player_id}"
        try:
            results = self._nexus.search(title, limit=5)
            for entry in results:
                if entry.get("title") == title and entry.get("category") == "economy":
                    return int(entry.get("content", str(_DEFAULT_BALANCE)))
        except Exception as exc:
            logger.warning("Could not load balance for '%s' from Nexus: %s", player_id, exc)
        return _DEFAULT_BALANCE

    def _save_balance(self, player_id: str, balance: int) -> None:
        """Persist balance to Nexus, creating or updating as required.

        Args:
            player_id: Target player.
            balance: New balance value to store.
        """
        title = f"balance:{player_id}"
        try:
            results = self._nexus.search(title, limit=5)
            existing_id: Optional[str] = None
            for entry in results:
                if entry.get("title") == title and entry.get("category") == "economy":
                    existing_id = entry.get("id")
                    break

            if existing_id:
                self._nexus.update_entry(existing_id, content=str(balance))
            else:
                self._nexus.add_entry(
                    title=title,
                    content=str(balance),
                    content_type="memory",
                    category="economy",
                    tags=["balance", player_id],
                    created_by=_NEXUS_CREATED_BY,
                )
        except Exception as exc:
            logger.error("Could not save balance for '%s' to Nexus: %s", player_id, exc)

    def _save_transaction(self, player_id: str, txn: Transaction) -> None:
        """Persist a transaction record to Nexus.

        Args:
            player_id: Owner of the transaction.
            txn: The :class:`Transaction` to persist.
        """
        try:
            self._nexus.add_entry(
                title=f"txn:{player_id}:{txn.id}",
                content=json.dumps(txn.to_dict()),
                content_type="history",
                category="economy",
                tags=["transaction", player_id, txn.type.value],
                created_by=_NEXUS_CREATED_BY,
            )
        except Exception as exc:
            logger.error(
                "Could not save transaction %s for '%s' to Nexus: %s",
                txn.id,
                player_id,
                exc,
            )

    def _fire_event(self, player_id: str, txn: Transaction) -> None:
        """Emit an ``economy.transaction`` event on the MCPFramework bus.

        Failures are silently logged — the economy must keep working even
        when the framework is not yet initialised (e.g., during unit tests).

        Args:
            player_id: Player whose balance changed.
            txn: The completed transaction.
        """
        try:
            fw = get_framework()
            fw.emit_event(
                "economy.transaction",
                payload={
                    "player_id": player_id,
                    "transaction_id": txn.id,
                    "type": txn.type.value,
                    "amount": txn.amount,
                    "scene": txn.scene,
                    "description": txn.description,
                    "balance_after": txn.balance_after,
                    "timestamp": txn.timestamp,
                },
                source="economy",
            )
        except Exception as exc:
            logger.debug("Could not fire economy.transaction event: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[EconomyManager] = None
_manager_lock = threading.Lock()


def get_economy_manager() -> EconomyManager:
    """Return the global :class:`EconomyManager` singleton.

    Thread-safe; the first call initialises the instance.

    Returns:
        The process-wide :class:`EconomyManager`.
    """
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = EconomyManager()
                logger.info("EconomyManager: singleton initialised")
    return _manager
