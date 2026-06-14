"""Arena Engine — full tactical card game engine for CosySim v0.68 'Dark Renaissance'.

Two AI fighters (LMStudio small models) play a tactical card game while the
player watches and bets on rounds.  Showcases real-time agent reasoning.

Typical usage::

    from engine.arena.arena_engine import get_arena_engine

    engine = get_arena_engine()
    match  = engine.create_match("shadow", "blaze")
    bet    = engine.place_bet(match.id, "match_winner", "fighter_a", 50)
    round1 = engine.play_round(match.id)
    engine.resolve_bets(match.id)
"""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

import requests

from engine.config import get_config
from engine.economy.economy import TransactionType, get_economy_manager
from engine.events.event_bus import get_event_bus
from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

def _lmstudio_default_url() -> str:
    from engine.port_registry import get_service_url
    return get_service_url("lmstudio")
_AGENT_MAX_TOKENS: int = 150
_AGENT_TEMPERATURE: float = 0.8
_COMMENTARY_MAX_TOKENS: int = 120

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CardType(str, Enum):
    """Mechanical types governing arena resolution rules."""

    ATTACK = "ATTACK"
    DEFENSE = "DEFENSE"
    SPECIAL = "SPECIAL"
    WILD = "WILD"
    TRAP = "TRAP"
    COUNTER = "COUNTER"


class MatchStatus(str, Enum):
    """Lifecycle phases of an arena match."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    ABANDONED = "ABANDONED"


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


@dataclass
class Card:
    """A single tactical card.

    Attributes:
        id: Unique card identifier (UUID-derived short string).
        name: Human-readable display name.
        card_type: Mechanical type governing resolution rules.
        power: Base damage/defence value (1–10).
        special_effect: Effect keyword string, e.g. ``"double_damage"``.
        flavor_text: Lore text shown to viewers.
    """

    id: str
    name: str
    card_type: CardType
    power: int
    special_effect: str = ""
    flavor_text: str = ""

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation.

        Returns:
            Dict suitable for Nexus storage or JSON serialisation.
        """
        return {
            "id": self.id,
            "name": self.name,
            "card_type": self.card_type.value,
            "power": self.power,
            "special_effect": self.special_effect,
            "flavor_text": self.flavor_text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        """Construct a Card from a serialised dict.

        Args:
            data: Dict produced by :meth:`to_dict`.

        Returns:
            Reconstructed :class:`Card` instance.
        """
        return cls(
            id=data["id"],
            name=data["name"],
            card_type=CardType(data["card_type"]),
            power=int(data["power"]),
            special_effect=data.get("special_effect", ""),
            flavor_text=data.get("flavor_text", ""),
        )


# ---------------------------------------------------------------------------
# RoundOutcome
# ---------------------------------------------------------------------------


@dataclass
class RoundOutcome:
    """Complete record of a single arena round.

    Attributes:
        round_num: 1-based round number.
        fighter_a_card: Card played by fighter A.
        fighter_b_card: Card played by fighter B.
        fighter_a_reasoning: Tactical reasoning from fighter A's LLM.
        fighter_b_reasoning: Tactical reasoning from fighter B's LLM.
        winner: ``"fighter_a"`` | ``"fighter_b"`` | ``"draw"``.
        damage_a: HP damage dealt *to* fighter A this round.
        damage_b: HP damage dealt *to* fighter B this round.
        commentary: NLM-generated play-by-play text.
        special_triggered: Label of any special effect that fired.
    """

    round_num: int
    fighter_a_card: Card
    fighter_b_card: Card
    fighter_a_reasoning: str
    fighter_b_reasoning: str
    winner: str
    damage_a: int
    damage_b: int
    commentary: str
    special_triggered: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation."""
        return {
            "round_num": self.round_num,
            "fighter_a_card": self.fighter_a_card.to_dict(),
            "fighter_b_card": self.fighter_b_card.to_dict(),
            "fighter_a_reasoning": self.fighter_a_reasoning,
            "fighter_b_reasoning": self.fighter_b_reasoning,
            "winner": self.winner,
            "damage_a": self.damage_a,
            "damage_b": self.damage_b,
            "commentary": self.commentary,
            "special_triggered": self.special_triggered,
        }


# ---------------------------------------------------------------------------
# Fighter
# ---------------------------------------------------------------------------


@dataclass
class Fighter:
    """Arena AI fighter with deck, hand, HP and career statistics.

    Attributes:
        id: Unique fighter identifier used as Nexus lookup key.
        name: Display name.
        persona: LLM persona description fed as system context.
        model_id: LMStudio model ID used for card selection.
        hp: Current hit points.
        max_hp: Maximum / starting hit points.
        deck: Ordered draw pile (15 cards at match start).
        hand: Currently held cards (max 5 at any time).
        wins: Career match wins.
        losses: Career match losses.
        draws: Career match draws.
        stats: Free-form metrics dict (e.g. ``last_response_ms``).
    """

    id: str
    name: str
    persona: str
    model_id: str
    hp: int = 100
    max_hp: int = 100
    deck: List[Card] = field(default_factory=list)
    hand: List[Card] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    draws: int = 0
    stats: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Gameplay helpers
    # ------------------------------------------------------------------

    def draw_card(self, count: int = 1) -> List[Card]:
        """Draw *count* cards from the deck into the hand.

        Args:
            count: Number of cards to draw.

        Returns:
            List of cards added to the hand (may be fewer if deck empties).
        """
        drawn: List[Card] = []
        for _ in range(count):
            if not self.deck:
                break
            card = self.deck.pop(0)
            self.hand.append(card)
            drawn.append(card)
        return drawn

    def play_card(self, card_id: str) -> Card:
        """Remove a card from the hand by id and return it.

        Args:
            card_id: The ``id`` of the card to play.

        Returns:
            The played :class:`Card`.

        Raises:
            ValueError: If no card with that id exists in the hand.
        """
        for idx, card in enumerate(self.hand):
            if card.id == card_id:
                return self.hand.pop(idx)
        raise ValueError(
            f"Card {card_id!r} not found in hand of fighter {self.id!r}."
        )

    def is_alive(self) -> bool:
        """Return ``True`` when the fighter still has HP remaining."""
        return self.hp > 0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "name": self.name,
            "persona": self.persona,
            "model_id": self.model_id,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "deck": [c.to_dict() for c in self.deck],
            "hand": [c.to_dict() for c in self.hand],
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Fighter":
        """Construct a Fighter from a serialised dict.

        Args:
            data: Dict produced by :meth:`to_dict`.

        Returns:
            Reconstructed :class:`Fighter` instance.
        """
        return cls(
            id=data["id"],
            name=data["name"],
            persona=data["persona"],
            model_id=data["model_id"],
            hp=data.get("hp", 100),
            max_hp=data.get("max_hp", 100),
            deck=[Card.from_dict(c) for c in data.get("deck", [])],
            hand=[Card.from_dict(c) for c in data.get("hand", [])],
            wins=data.get("wins", 0),
            losses=data.get("losses", 0),
            draws=data.get("draws", 0),
            stats=data.get("stats", {}),
        )


# ---------------------------------------------------------------------------
# Bet
# ---------------------------------------------------------------------------


@dataclass
class Bet:
    """A wager placed on a match or individual round.

    Attributes:
        id: Unique bet identifier.
        player_id: Betting player (defaults to ``"player"``).
        bet_type: ``"match_winner"`` | ``"round_winner"`` | ``"special_move"``.
        target: ``"fighter_a"`` | ``"fighter_b"`` | card name.
        amount: Credits wagered (must be positive).
        round_num: Target round for ``"round_winner"`` bets.
        resolved: Whether the bet has been settled.
        won: ``True`` if the bettor won the wager.
        payout: Credits returned (0 until resolved).
    """

    id: str
    player_id: str = "player"
    bet_type: str = "match_winner"
    target: str = ""
    amount: int = 0
    round_num: Optional[int] = None
    resolved: bool = False
    won: bool = False
    payout: int = 0

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "player_id": self.player_id,
            "bet_type": self.bet_type,
            "target": self.target,
            "amount": self.amount,
            "round_num": self.round_num,
            "resolved": self.resolved,
            "won": self.won,
            "payout": self.payout,
        }


# ---------------------------------------------------------------------------
# ArenaMatch
# ---------------------------------------------------------------------------


@dataclass
class ArenaMatch:
    """Full state for a match between two fighters.

    Attributes:
        id: Unique match identifier.
        fighter_a: First fighter.
        fighter_b: Second fighter.
        status: Lifecycle status.
        rounds: History of completed :class:`RoundOutcome` instances.
        bets: All bets placed on this match.
        max_rounds: Hard cap; match is decided on HP ratio if reached.
        winner: ``"fighter_a"`` | ``"fighter_b"`` | ``"draw"`` | ``None``.
        started_at: ISO 8601 creation timestamp.
        ended_at: ISO 8601 end timestamp or ``None`` if ongoing.
        pending_trap_a: Trap card queued to detonate against fighter A
            on the next round.
        pending_trap_b: Trap card queued to detonate against fighter B
            on the next round.
    """

    id: str
    fighter_a: Fighter
    fighter_b: Fighter
    status: MatchStatus = MatchStatus.PENDING
    rounds: List[RoundOutcome] = field(default_factory=list)
    bets: List[Bet] = field(default_factory=list)
    max_rounds: int = 7
    winner: Optional[str] = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: Optional[str] = None
    pending_trap_a: Optional[Card] = None
    pending_trap_b: Optional[Card] = None

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation."""
        return {
            "id": self.id,
            "fighter_a": self.fighter_a.to_dict(),
            "fighter_b": self.fighter_b.to_dict(),
            "status": self.status.value,
            "rounds": [r.to_dict() for r in self.rounds],
            "bets": [b.to_dict() for b in self.bets],
            "max_rounds": self.max_rounds,
            "winner": self.winner,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "pending_trap_a": (
                self.pending_trap_a.to_dict() if self.pending_trap_a else None
            ),
            "pending_trap_b": (
                self.pending_trap_b.to_dict() if self.pending_trap_b else None
            ),
        }


# ---------------------------------------------------------------------------
# ArenaEngine
# ---------------------------------------------------------------------------


class ArenaEngine:
    """Full tactical card game engine for the Arena scene.

    Manages fighter profiles, match lifecycle, RPS-style card resolution,
    NLM commentary generation, and economy-integrated betting.
    """

    def __init__(self) -> None:
        """Initialise engine, load config and bind Nexus/Economy/EventBus."""
        self._cfg = get_config()
        self._nexus_client = get_nexus_client()
        self._economy = get_economy_manager()
        self._event_bus = get_event_bus()
        self._matches: Dict[str, ArenaMatch] = {}
        self._fighter_profiles: Dict[str, Fighter] = {}
        self._lmstudio_url: str = self._cfg.get(
            "lmstudio.base_url", _lmstudio_default_url()
        )
        logger.info("ArenaEngine initialised (lmstudio=%s)", self._lmstudio_url)

    # ------------------------------------------------------------------
    # Match management
    # ------------------------------------------------------------------

    def create_match(self, fighter_a_id: str, fighter_b_id: str) -> ArenaMatch:
        """Create a new match between two fighters.

        Loads fighter profiles from Nexus (or generates defaults), resets HP,
        shuffles and deals starting hands (5 cards each), persists the match
        to Nexus, and fires the ``arena.match_created`` event.

        Args:
            fighter_a_id: Identifier for fighter A.
            fighter_b_id: Identifier for fighter B.

        Returns:
            The newly created :class:`ArenaMatch` with status ``IN_PROGRESS``.
        """
        fa = self._load_fighter(fighter_a_id)
        fb = self._load_fighter(fighter_b_id)

        # Reset per-match mutable state
        for fighter in (fa, fb):
            fighter.hp = fighter.max_hp
            fighter.deck = self._default_deck()
            random.shuffle(fighter.deck)
            fighter.hand = []
            fighter.draw_card(5)

        match = ArenaMatch(
            id=str(uuid.uuid4()),
            fighter_a=fa,
            fighter_b=fb,
            status=MatchStatus.IN_PROGRESS,
        )
        self._matches[match.id] = match

        try:
            self._nexus_client.add_entry(
                title=f"arena:match:{match.id}",
                content=str(match.to_dict()),
                content_type="memory",
                category="arena_matches",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist match to Nexus: %s", exc)

        self._event_bus.publish(
            "arena.match_created",
            {
                "match_id": match.id,
                "fighter_a": fa.name,
                "fighter_b": fb.name,
            },
            scene="arena",
        )
        logger.info("Match created: %s (%s vs %s)", match.id, fa.name, fb.name)
        return match

    def _load_fighter(self, fighter_id: str) -> Fighter:
        """Load a fighter profile from Nexus or generate a default.

        Args:
            fighter_id: The fighter's unique identifier.

        Returns:
            :class:`Fighter` instance ready for a match.
        """
        if fighter_id in self._fighter_profiles:
            return self._fighter_profiles[fighter_id]

        try:
            results = self._nexus_client.search(f"fighter:{fighter_id}", limit=5)
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                if f"fighter:{fighter_id}" not in entry.get("title", ""):
                    continue
                import json as _json  # local to avoid top-level cycle risk

                content = entry.get("content", "{}")
                if isinstance(content, str):
                    content = _json.loads(content)
                fighter = Fighter.from_dict(content)
                self._fighter_profiles[fighter_id] = fighter
                logger.info("Loaded fighter %r from Nexus", fighter_id)
                return fighter
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Nexus fighter lookup failed for %r: %s", fighter_id, exc
            )

        # Generate a default fighter
        fighter = Fighter(
            id=fighter_id,
            name=fighter_id.title(),
            persona=f"A fierce arena fighter known as {fighter_id}",
            model_id="qwen3-4b",
            deck=self._default_deck(),
        )
        self._fighter_profiles[fighter_id] = fighter
        logger.info("Generated default fighter for %r", fighter_id)
        return fighter

    def _default_deck(self) -> List[Card]:
        """Build a balanced 15-card default deck.

        Composition: 4 attacks, 3 defences, 3 specials, 3 wilds, 1 trap,
        1 counter.

        Returns:
            List of 15 :class:`Card` instances.
        """

        def uid() -> str:
            return str(uuid.uuid4())[:8]

        return [
            # --- Attacks (4, power 3–6) ---
            Card(uid(), "Iron Fist", CardType.ATTACK, 4,
                 flavor_text="A direct, bone-jarring strike."),
            Card(uid(), "Blade Rush", CardType.ATTACK, 5,
                 flavor_text="Swift and utterly merciless."),
            Card(uid(), "War Hammer", CardType.ATTACK, 6,
                 flavor_text="Bone-crushing momentum."),
            Card(uid(), "Quick Jab", CardType.ATTACK, 3,
                 flavor_text="Fast — rarely lethal alone."),
            # --- Defences (3, power 4–7) ---
            Card(uid(), "Iron Shield", CardType.DEFENSE, 5,
                 flavor_text="Solid steel between you and death."),
            Card(uid(), "Stone Ward", CardType.DEFENSE, 7,
                 flavor_text="Nearly impenetrable."),
            Card(uid(), "Dodge Roll", CardType.DEFENSE, 4,
                 flavor_text="Nimble evasion."),
            # --- Specials (3, unique effects) ---
            Card(uid(), "Blood Surge", CardType.SPECIAL, 5,
                 special_effect="double_damage",
                 flavor_text="Harness raw pain as power."),
            Card(uid(), "Mend Wounds", CardType.SPECIAL, 4,
                 special_effect="heal",
                 flavor_text="Battle-honed battlefield recovery."),
            Card(uid(), "Soul Steal", CardType.SPECIAL, 3,
                 special_effect="steal",
                 flavor_text="Rip strength from the foe."),
            # --- Wilds (3, power 2–4) ---
            Card(uid(), "Chaos Strike", CardType.WILD, 4,
                 flavor_text="Unpredictable mayhem."),
            Card(uid(), "Fog of War", CardType.WILD, 2,
                 flavor_text="Confusion reigns."),
            Card(uid(), "Gambit", CardType.WILD, 3,
                 flavor_text="Fortune favours the bold."),
            # --- Trap (1) ---
            Card(uid(), "Pit Snare", CardType.TRAP, 5,
                 special_effect="trap",
                 flavor_text="Wait for them to step right in."),
            # --- Counter (1) ---
            Card(uid(), "Riposte", CardType.COUNTER, 6,
                 special_effect="counter",
                 flavor_text="Turn their own strength against them."),
        ]

    # ------------------------------------------------------------------
    # Round play
    # ------------------------------------------------------------------

    def play_round(
        self,
        match_id: str,
        on_card_chosen: Optional[Callable] = None,
    ) -> RoundOutcome:
        """Play one full round of an in-progress match.

        Both fighters select a card via their LMStudio model.  Cards are
        resolved, damage applied, commentary generated, and the outcome
        appended to the match history.  The ``arena.round_complete`` event
        is fired, and match-end logic is evaluated.

        Args:
            match_id: ID of the target match.
            on_card_chosen: Optional callback ``(fighter, card)`` called
                after each fighter commits a card.

        Returns:
            The completed :class:`RoundOutcome`.

        Raises:
            ValueError: If the match is not found, not ``IN_PROGRESS``, or
                a fighter is already eliminated.
        """
        match = self._matches.get(match_id)
        if match is None:
            raise ValueError(f"Match {match_id!r} not found.")
        if match.status != MatchStatus.IN_PROGRESS:
            raise ValueError(
                f"Match {match_id!r} is {match.status.value}, not IN_PROGRESS."
            )
        if not match.fighter_a.is_alive() or not match.fighter_b.is_alive():
            raise ValueError(
                "Cannot play round — a fighter has already been eliminated."
            )

        round_num = len(match.rounds) + 1

        # Refill hands to 5 if deck allows
        for fighter in (match.fighter_a, match.fighter_b):
            deficit = 5 - len(fighter.hand)
            if deficit > 0 and fighter.deck:
                fighter.draw_card(deficit)

        # Fighter A picks a card
        t0 = time.monotonic()
        card_a, reasoning_a = self._agent_pick_card(match.fighter_a, match)
        match.fighter_a.stats["last_response_ms"] = int(
            (time.monotonic() - t0) * 1000
        )

        # Fighter B picks a card
        t0 = time.monotonic()
        card_b, reasoning_b = self._agent_pick_card(match.fighter_b, match)
        match.fighter_b.stats["last_response_ms"] = int(
            (time.monotonic() - t0) * 1000
        )

        if on_card_chosen:
            on_card_chosen(match.fighter_a, card_a)
            on_card_chosen(match.fighter_b, card_b)

        # Resolve mechanics and apply damage
        resolution = self._resolve_round(
            card_a, card_b, match.fighter_a, match.fighter_b, match
        )

        commentary = self._generate_commentary(
            {
                **resolution,
                "card_a_name": card_a.name,
                "card_b_name": card_b.name,
                "round_num": round_num,
            },
            match,
        )

        outcome = RoundOutcome(
            round_num=round_num,
            fighter_a_card=card_a,
            fighter_b_card=card_b,
            fighter_a_reasoning=reasoning_a,
            fighter_b_reasoning=reasoning_b,
            winner=resolution["winner"],
            damage_a=resolution["damage_a"],
            damage_b=resolution["damage_b"],
            commentary=commentary,
            special_triggered=resolution.get("special_triggered", ""),
        )
        match.rounds.append(outcome)

        # Persist round record
        try:
            self._nexus_client.add_entry(
                title=f"arena:match:{match.id}:round:{round_num}",
                content=str(outcome.to_dict()),
                content_type="memory",
                category="arena_rounds",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Round Nexus persist failed: %s", exc)

        self._event_bus.publish(
            "arena.round_complete",
            {
                "match_id": match.id,
                "round_num": round_num,
                "winner": outcome.winner,
                "damage_a": outcome.damage_a,
                "damage_b": outcome.damage_b,
            },
            scene="arena",
        )

        self._check_match_end(match)
        return outcome

    def _agent_pick_card(
        self,
        fighter: Fighter,
        match: ArenaMatch,
    ) -> Tuple[Card, str]:
        """Ask the fighter's LMStudio model to choose a card.

        Builds a tactical prompt with current HP and hand state, calls the
        configured LMStudio endpoint, and parses ``CARD:`` / ``REASON:``
        lines from the response.  Falls back to a random hand card if the
        response cannot be parsed or the request fails.

        Args:
            fighter: The fighter making a card selection.
            match: Current match state (used for opponent HP context).

        Returns:
            Tuple of (chosen :class:`Card`, reasoning string).

        Raises:
            ValueError: If the fighter's hand is completely empty.
        """
        opponent = (
            match.fighter_b
            if fighter.id == match.fighter_a.id
            else match.fighter_a
        )
        round_num = len(match.rounds) + 1

        hand_lines = "\n".join(
            f"  - {c.name} [{c.card_type.value}] power={c.power}"
            + (f" effect={c.special_effect}" if c.special_effect else "")
            for c in fighter.hand
        )

        prompt = (
            f"You are {fighter.name}: {fighter.persona}\n\n"
            f"Current match state:\n"
            f"- Your HP: {fighter.hp}/{fighter.max_hp}\n"
            f"- Opponent HP: {opponent.hp}/{opponent.max_hp}\n"
            f"- Round: {round_num}\n\n"
            f"Your hand:\n{hand_lines}\n\n"
            f"Pick ONE card to play. Consider your opponent's likely strategy.\n"
            f"Respond with:\n"
            f"CARD: <card_name>\n"
            f"REASON: <1-2 sentences of tactical reasoning>"
        )

        chosen_card: Optional[Card] = None
        reasoning: str = "No reasoning provided."

        # v1.43.1 [2026-03-21] — Use unified chat()
        try:
            from engine.lmstudio.chat import chat
            content: str = chat(
                [{"role": "user", "content": prompt}],
                system=(
                    f"You are {fighter.name}, a fighter in the Arena. "
                    f"Pick one card from your hand to play this turn."
                ),
                model=fighter.model_id if fighter.model_id != "auto" else None,
                max_tokens=_AGENT_MAX_TOKENS,
                temperature=_AGENT_TEMPERATURE,
            )

            card_name: str = ""
            for line in content.splitlines():
                stripped = line.strip()
                upper = stripped.upper()
                if upper.startswith("CARD:"):
                    card_name = stripped[5:].strip()
                elif upper.startswith("REASON:"):
                    reasoning = stripped[7:].strip()

            # Fuzzy match by name substring (case-insensitive)
            if card_name:
                name_lower = card_name.lower()
                for card in fighter.hand:
                    if (
                        name_lower in card.name.lower()
                        or card.name.lower() in name_lower
                    ):
                        chosen_card = card
                        break

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LMStudio call failed for fighter %r: %s — using random card.",
                fighter.id,
                exc,
            )

        # Fallback: random card
        if chosen_card is None:
            if not fighter.hand:
                raise ValueError(
                    f"Fighter {fighter.id!r} has an empty hand and cannot play."
                )
            chosen_card = random.choice(fighter.hand)
            reasoning = "Tactical intuition (fallback random selection)."

        # Remove the chosen card from the hand
        fighter.play_card(chosen_card.id)
        return chosen_card, reasoning

    def _resolve_round(
        self,
        card_a: Card,
        card_b: Card,
        fa: Fighter,
        fb: Fighter,
        match: Optional[ArenaMatch] = None,
    ) -> dict:
        """Resolve card interaction, apply HP damage, and return outcome data.

        Resolution order:

        1. Fire any pending traps from a previous round.
        2. Randomise WILD cards to a concrete type.
        3. Set new TRAP cards to fire next round (no immediate damage).
        4. Apply COUNTER > ATTACK, ATTACK ↔ DEFENCE, ATTACK ↔ ATTACK,
           DEFENCE ↔ DEFENCE, SPECIAL effects, or generic fallback.

        Args:
            card_a: Card played by fighter A.
            card_b: Card played by fighter B.
            fa: Fighter A (HP mutated in-place).
            fb: Fighter B (HP mutated in-place).
            match: Match state for trap storage (``None`` in isolated tests).

        Returns:
            Dict with keys ``winner``, ``damage_a``, ``damage_b``,
            ``special_triggered``.
        """
        damage_a: int = 0
        damage_b: int = 0
        winner: str = "draw"
        special_triggered: str = ""

        # 1. Fire pending traps
        if match is not None:
            if match.pending_trap_b:
                trap = match.pending_trap_b
                damage_b += trap.power * 2
                special_triggered = f"trap_fires:{trap.name}"
                match.pending_trap_b = None
            if match.pending_trap_a:
                trap = match.pending_trap_a
                damage_a += trap.power * 2
                if not special_triggered:
                    special_triggered = f"trap_fires:{trap.name}"
                match.pending_trap_a = None

        # 2. Resolve WILD — substitute a random concrete type
        _concrete = [
            CardType.ATTACK,
            CardType.DEFENSE,
            CardType.SPECIAL,
            CardType.COUNTER,
        ]
        effective_a = card_a.card_type
        effective_b = card_b.card_type
        if effective_a == CardType.WILD:
            effective_a = random.choice(_concrete)
            if not special_triggered:
                special_triggered = f"wild_a:{effective_a.value}"
        if effective_b == CardType.WILD:
            effective_b = random.choice(_concrete)
            if not special_triggered:
                special_triggered = f"wild_b:{effective_b.value}"

        # 3. Handle TRAP (set pending; no direct damage this round)
        if card_a.card_type == CardType.TRAP:
            if match is not None:
                match.pending_trap_b = card_a
            if not special_triggered:
                special_triggered = f"trap_set:{card_a.name}"
        elif card_b.card_type == CardType.TRAP:
            if match is not None:
                match.pending_trap_a = card_b
            if not special_triggered:
                special_triggered = f"trap_set:{card_b.name}"

        # 4a. COUNTER beats ATTACK (double damage)
        elif effective_a == CardType.COUNTER and effective_b == CardType.ATTACK:
            damage_b += card_b.power * 2
            winner = "fighter_a"
            if not special_triggered:
                special_triggered = "counter"

        elif effective_b == CardType.COUNTER and effective_a == CardType.ATTACK:
            damage_a += card_a.power * 2
            winner = "fighter_b"
            if not special_triggered:
                special_triggered = "counter"

        # 4b. ATTACK vs DEFENCE — net damage to loser
        elif effective_a == CardType.ATTACK and effective_b == CardType.DEFENSE:
            net = card_a.power - card_b.power
            if net > 0:
                damage_b += net
                winner = "fighter_a"
            elif net < 0:
                damage_a += abs(net)
                winner = "fighter_b"
            else:
                winner = "draw"

        elif effective_b == CardType.ATTACK and effective_a == CardType.DEFENSE:
            net = card_b.power - card_a.power
            if net > 0:
                damage_a += net
                winner = "fighter_b"
            elif net < 0:
                damage_b += abs(net)
                winner = "fighter_a"
            else:
                winner = "draw"

        # 4c. ATTACK vs ATTACK — both take opponent's card power
        elif effective_a == CardType.ATTACK and effective_b == CardType.ATTACK:
            damage_a += card_b.power
            damage_b += card_a.power
            if card_a.power > card_b.power:
                winner = "fighter_a"
            elif card_b.power > card_a.power:
                winner = "fighter_b"
            else:
                winner = "draw"

        # 4d. DEFENCE vs DEFENCE — draw, no damage
        elif effective_a == CardType.DEFENSE and effective_b == CardType.DEFENSE:
            winner = "draw"

        # 4e. SPECIAL (A plays special)
        elif effective_a == CardType.SPECIAL:
            dmg_b, dmg_a, spec = self._apply_special(
                card_a.special_effect, card_a, card_b, fa, fb
            )
            damage_b += dmg_b
            damage_a += dmg_a
            if not special_triggered:
                special_triggered = spec
            if damage_b > damage_a:
                winner = "fighter_a"
            elif damage_a > damage_b:
                winner = "fighter_b"
            else:
                winner = "draw"

        # 4f. SPECIAL (B plays special)
        elif effective_b == CardType.SPECIAL:
            dmg_a, dmg_b, spec = self._apply_special(
                card_b.special_effect, card_b, card_a, fb, fa
            )
            damage_a += dmg_a
            damage_b += dmg_b
            if not special_triggered:
                special_triggered = spec
            if damage_a > damage_b:
                winner = "fighter_b"
            elif damage_b > damage_a:
                winner = "fighter_a"
            else:
                winner = "draw"

        # 4g. Generic fallback — both deal card power
        else:
            damage_a += card_b.power
            damage_b += card_a.power
            if card_a.power > card_b.power:
                winner = "fighter_a"
            elif card_b.power > card_a.power:
                winner = "fighter_b"
            else:
                winner = "draw"

        # Apply damage
        fa.hp = max(0, fa.hp - damage_a)
        fb.hp = max(0, fb.hp - damage_b)

        return {
            "winner": winner,
            "damage_a": damage_a,
            "damage_b": damage_b,
            "special_triggered": special_triggered,
        }

    def _apply_special(
        self,
        effect: str,
        attacker_card: Card,
        defender_card: Card,
        attacker: Fighter,
        defender: Fighter,
    ) -> Tuple[int, int, str]:
        """Compute damage and side-effects for a SPECIAL card.

        Supported effect keywords (matched via ``in``):

        - ``"double_damage"`` — deal ``power * 2`` to the opponent.
        - ``"heal"`` — restore ``power * 2`` HP to the attacker, plus deal
          ``power`` to the opponent.
        - ``"steal"`` — rip the top card from the opponent's deck into the
          attacker's hand, plus deal ``power + 2`` to the opponent.
        - ``"skip"`` — deal ``power`` damage; opponent's card is nullified
          (their damage contribution is zeroed by the caller's logic).

        Unrecognised effects deal plain ``power`` damage.

        Args:
            effect: Effect keyword string (case-insensitive).
            attacker_card: The SPECIAL card being played.
            defender_card: The opponent's card (unused for most effects).
            attacker: Fighter using the special (may be mutated for HP/hand).
            defender: Opponent fighter (may have deck mutated for steal).

        Returns:
            Tuple of ``(damage_to_defender, damage_to_attacker, effect_label)``.
        """
        eff = effect.lower()

        if "double_damage" in eff:
            return attacker_card.power * 2, 0, "double_damage"

        if "heal" in eff:
            heal = min(
                attacker_card.power * 2,
                attacker.max_hp - attacker.hp,
            )
            attacker.hp = min(attacker.max_hp, attacker.hp + heal)
            return attacker_card.power, 0, "heal"

        if "steal" in eff:
            if defender.deck:
                stolen = defender.deck.pop(0)
                attacker.hand.append(stolen)
            return attacker_card.power + 2, 0, "steal"

        if "skip" in eff:
            # Attacker deals power; this call returns 0 damage to the attacker
            return attacker_card.power, 0, "skip"

        # Generic special
        return attacker_card.power, 0, "special"

    def _generate_commentary(
        self,
        outcome_data: dict,
        match: ArenaMatch,
    ) -> str:
        """Generate NLM play-by-play commentary for a completed round.

        Calls ``nexus_client.ask()``; falls back to a template string on any
        error (network failure, Nexus unavailable, etc.).

        Args:
            outcome_data: Merged resolution + metadata dict (card names,
                damage values, round number, winner).
            match: Current match state.

        Returns:
            Commentary string (max ~100 words).
        """
        fa = match.fighter_a
        fb = match.fighter_b
        card_a_name: str = outcome_data.get("card_a_name", "a card")
        card_b_name: str = outcome_data.get("card_b_name", "a card")
        round_num = outcome_data.get("round_num", "?")
        winner: str = outcome_data.get("winner", "draw")
        damage_a: int = outcome_data.get("damage_a", 0)
        damage_b: int = outcome_data.get("damage_b", 0)

        winner_name = (
            fa.name
            if winner == "fighter_a"
            else (fb.name if winner == "fighter_b" else "Neither fighter")
        )
        fallback = (
            f"{fa.name} played {card_a_name}! "
            f"{fb.name} countered with {card_b_name}! "
            f"{winner_name} wins the round!"
        )

        try:
            prompt = (
                f"Generate exciting arena fight commentary (max 50 words) "
                f"for round {round_num}: "
                f"{fa.name} played {card_a_name} vs {fb.name}'s {card_b_name}. "
                f"Damage dealt: {fa.name} -{damage_a}HP, {fb.name} -{damage_b}HP. "
                f"Round winner: {winner_name}."
            )
            result = self._nexus_client.ask(prompt, depth="fast")
            if isinstance(result, dict):
                text: str = result.get("answer") or result.get("content") or ""
                return text if text else fallback
            return str(result) if result else fallback
        except Exception as exc:  # noqa: BLE001
            logger.debug("Commentary generation failed: %s", exc)
            return fallback

    def _check_match_end(self, match: ArenaMatch) -> None:
        """Evaluate whether the match should end and finalise if so.

        A match ends when:

        - At least one fighter's HP reaches 0 (KO), or
        - ``max_rounds`` rounds have been played.

        When both fighters survive to the round cap, the fighter with the
        higher remaining HP wins; exact equality is a draw.

        Args:
            match: The match to evaluate (mutated if it ends).
        """
        fa, fb = match.fighter_a, match.fighter_b
        ko_a = not fa.is_alive()
        ko_b = not fb.is_alive()
        rounds_exhausted = len(match.rounds) >= match.max_rounds

        if not (ko_a or ko_b or rounds_exhausted):
            return  # Match continues

        match.status = MatchStatus.COMPLETE
        match.ended_at = datetime.now(timezone.utc).isoformat()

        if ko_a and not ko_b:
            match.winner = "fighter_b"
            fb.wins += 1
            fa.losses += 1
        elif ko_b and not ko_a:
            match.winner = "fighter_a"
            fa.wins += 1
            fb.losses += 1
        else:
            # Both KO'd simultaneously or rounds exhausted — decide by HP
            if fa.hp > fb.hp:
                match.winner = "fighter_a"
                fa.wins += 1
                fb.losses += 1
            elif fb.hp > fa.hp:
                match.winner = "fighter_b"
                fb.wins += 1
                fa.losses += 1
            else:
                match.winner = "draw"
                fa.draws += 1
                fb.draws += 1

        # Persist updated career stats
        for fighter in (fa, fb):
            try:
                self._nexus_client.add_entry(
                    title=f"fighter:{fighter.id}",
                    content=str(fighter.to_dict()),
                    content_type="memory",
                    category="arena_fighters",
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Fighter Nexus persist failed: %s", exc)

        self._event_bus.publish(
            "arena.match_complete",
            {
                "match_id": match.id,
                "winner": match.winner,
                "rounds": len(match.rounds),
            },
            scene="arena",
        )
        logger.info(
            "Match %s complete — winner: %s (rounds played: %d)",
            match.id,
            match.winner,
            len(match.rounds),
        )

    # ------------------------------------------------------------------
    # Betting
    # ------------------------------------------------------------------

    def place_bet(
        self,
        match_id: str,
        bet_type: str,
        target: str,
        amount: int,
        player_id: str = "player",
        round_num: Optional[int] = None,
    ) -> Bet:
        """Place a wager on a match or round outcome.

        Validates the match status, deducts credits via :class:`EconomyManager`,
        and records the bet on the match.

        Args:
            match_id: Target match identifier.
            bet_type: ``"match_winner"`` | ``"round_winner"`` |
                ``"special_move"``.
            target: ``"fighter_a"`` | ``"fighter_b"`` | card name.
            amount: Credits to wager (must be positive).
            player_id: Identifier of the betting player.
            round_num: Target round number for ``"round_winner"`` bets.

        Returns:
            The created :class:`Bet` instance.

        Raises:
            ValueError: If the match is not found, not bettable, the amount
                is not positive, or the economy deduction fails.
        """
        match = self._matches.get(match_id)
        if match is None:
            raise ValueError(f"Match {match_id!r} not found.")
        if match.status not in (MatchStatus.PENDING, MatchStatus.IN_PROGRESS):
            raise ValueError(
                f"Match {match_id!r} is {match.status.value}; bets are closed."
            )
        if amount <= 0:
            raise ValueError("Bet amount must be positive.")

        try:
            self._economy.transact(
                -amount,
                TransactionType.BET_LOSS,
                "arena",
                f"Bet placed — {bet_type}:{target}",
                player_id,
            )
        except Exception as exc:
            raise ValueError(f"Economy deduction failed: {exc}") from exc

        bet = Bet(
            id=str(uuid.uuid4()),
            player_id=player_id,
            bet_type=bet_type,
            target=target,
            amount=amount,
            round_num=round_num,
        )
        match.bets.append(bet)
        logger.info(
            "Bet placed: %s (%s → %s, ×%d credits, by %s)",
            bet.id,
            bet_type,
            target,
            amount,
            player_id,
        )
        return bet

    def resolve_bets(self, match_id: str) -> List[Bet]:
        """Resolve all pending bets for a completed match.

        Odds applied:

        - ``match_winner`` — 2.0×
        - ``round_winner`` — 1.8×
        - ``special_move`` — 1.5× (informational; not auto-resolved)

        Winning payouts are credited via :class:`EconomyManager`.

        Args:
            match_id: ID of the completed match.

        Returns:
            List of all :class:`Bet` instances (now resolved).

        Raises:
            ValueError: If the match is not found or not ``COMPLETE``.
        """
        match = self._matches.get(match_id)
        if match is None:
            raise ValueError(f"Match {match_id!r} not found.")
        if match.status != MatchStatus.COMPLETE:
            raise ValueError(
                f"Match {match_id!r} is {match.status.value}, not COMPLETE."
            )

        resolved: List[Bet] = []
        for bet in match.bets:
            if bet.resolved:
                resolved.append(bet)
                continue

            won: bool = False
            odds: float = 1.5

            if bet.bet_type == "match_winner":
                won = match.winner == bet.target
                odds = 2.0
            elif bet.bet_type == "round_winner":
                odds = 1.8
                rn = bet.round_num
                if rn is not None and 1 <= rn <= len(match.rounds):
                    won = match.rounds[rn - 1].winner == bet.target
            # "special_move" — not auto-evaluated; won remains False

            payout: int = 0
            if won:
                payout = int(bet.amount * odds)
                try:
                    self._economy.transact(
                        payout,
                        TransactionType.BET_WIN,
                        "arena",
                        f"Bet payout — {bet.bet_type}:{bet.target}",
                        bet.player_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Payout failed for bet %s: %s", bet.id, exc
                    )
                    payout = 0

            bet.resolved = True
            bet.won = won
            bet.payout = payout
            resolved.append(bet)

        return resolved

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_match(self, match_id: str) -> Optional[ArenaMatch]:
        """Return the :class:`ArenaMatch` for the given id, or ``None``.

        Args:
            match_id: Match identifier.

        Returns:
            :class:`ArenaMatch` or ``None``.
        """
        return self._matches.get(match_id)

    def get_fighter_profile(self, fighter_id: str) -> Optional[Fighter]:
        """Return a cached fighter profile or ``None``.

        Args:
            fighter_id: Fighter identifier.

        Returns:
            :class:`Fighter` or ``None``.
        """
        return self._fighter_profiles.get(fighter_id)

    def get_leaderboard(self, limit: int = 10) -> List[dict]:
        """Return the top fighters ranked by win count.

        Supplements in-memory profiles with any additional fighters found in
        Nexus under the ``"arena_fighters"`` category.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of dicts with keys ``id``, ``name``, ``wins``, ``losses``,
            ``draws``, ``win_rate``.
        """
        fighters: Dict[str, Fighter] = dict(self._fighter_profiles)

        try:
            results = self._nexus_client.search("fighter:", limit=50)
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                title: str = entry.get("title", "")
                if not title.startswith("fighter:"):
                    continue
                fid = title.split("fighter:", 1)[1]
                if fid in fighters:
                    continue
                import json as _json

                try:
                    content = entry.get("content", "{}")
                    if isinstance(content, str):
                        content = _json.loads(content)
                    fighters[fid] = Fighter.from_dict(content)
                except Exception as e:  # noqa: BLE001
                    logger.debug("[ArenaEngine] Failed to parse fighter entry %s (operation=leaderboard): %s", fid, e)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Leaderboard Nexus search failed: %s", exc)

        board: List[dict] = []
        for fighter in fighters.values():
            total = fighter.wins + fighter.losses + fighter.draws
            board.append(
                {
                    "id": fighter.id,
                    "name": fighter.name,
                    "wins": fighter.wins,
                    "losses": fighter.losses,
                    "draws": fighter.draws,
                    "win_rate": round(fighter.wins / total, 3) if total else 0.0,
                }
            )
        board.sort(key=lambda x: (x["wins"], x["win_rate"]), reverse=True)
        return board[:limit]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[ArenaEngine] = None
_engine_lock = threading.Lock()


def get_arena_engine() -> ArenaEngine:
    """Return the module-level singleton :class:`ArenaEngine`.

    Uses double-checked locking for thread safety.

    Returns:
        The singleton :class:`ArenaEngine` instance.
    """
    global _engine_instance  # noqa: PLW0603
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ArenaEngine()
    return _engine_instance
