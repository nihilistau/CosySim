"""
THE AUCTION HOUSE — CosySim Scene
=================================

Underground black market auction house.  Rare items, contraband, stolen data,
and secrets go to the highest bidder.  Six NPC bidders with distinct
personalities compete against the player in real-time Socket.IO auctions.

The Gavel — an AI auctioneer entity — narrates every lot with dramatic flair.

Version: v1.50.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.50.0 [2026-03-22] — Full implementation: 24-item catalog, 6 NPC bidders,
                            real-time auction engine, Socket.IO events,
                            REST API, inventory integration, session history
    v1.0.0  [2026-03-22] — Initial scaffold via Creation Kit

Usage:
    python launcher.py auction
    python launcher_game.py auction
"""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene
from engine.port_registry import get_port
from engine.world.player_state import get_player_state

logger = logging.getLogger(__name__)

SCENE_ID = "auction"
DEFAULT_PORT = get_port(SCENE_ID, 5574)


# ══════════════════════════════════════════════════════════════════════════
#  AUCTION CATALOG — 24 items across 7 categories
# ══════════════════════════════════════════════════════════════════════════
# v1.50.0 [2026-03-22] — Full catalog: weapon, tech, intel, contraband,
#                          medical, vehicle, art

AUCTION_CATALOG: List[Dict[str, Any]] = [
    # ── Weapons ────────────────────────────────────────────────────────
    {"id": "plasma_pistol", "name": "Plasma Pistol 'Sunburn'", "category": "weapon",
     "description": "Military-grade sidearm. Serial numbers dissolved.",
     "base_value": 800, "rarity": "rare"},
    {"id": "mono_blade", "name": "Monofilament Blade", "category": "weapon",
     "description": "Cuts through anything. Handle with extreme care.",
     "base_value": 1200, "rarity": "epic"},
    {"id": "emp_grenades", "name": "EMP Grenade Pack (x3)", "category": "weapon",
     "description": "Fries every circuit in a 10m radius. No refunds.",
     "base_value": 600, "rarity": "uncommon"},
    {"id": "railgun_prototype", "name": "Prototype Railgun 'Mercy'", "category": "weapon",
     "description": "SynthSec R&D prototype. Fires tungsten slugs at Mach 7.",
     "base_value": 3500, "rarity": "legendary"},

    # ── Tech ───────────────────────────────────────────────────────────
    {"id": "neural_jack", "name": "Neural Interface v7", "category": "tech",
     "description": "Direct brain-to-net connection. Illegal in 12 districts.",
     "base_value": 2000, "rarity": "legendary"},
    {"id": "ghost_deck", "name": "Ghost Deck", "category": "tech",
     "description": "Portable hacking rig. Leaves zero trace on any subnet.",
     "base_value": 1500, "rarity": "epic"},
    {"id": "signal_scrambler", "name": "Signal Scrambler Mk-IV", "category": "tech",
     "description": "Makes you invisible to surveillance for 45 minutes.",
     "base_value": 900, "rarity": "rare"},
    {"id": "quantum_chip", "name": "Quantum Decryption Chip", "category": "tech",
     "description": "Breaks 256-bit encryption in under 3 seconds.",
     "base_value": 2800, "rarity": "legendary"},

    # ── Intel ──────────────────────────────────────────────────────────
    {"id": "corp_secrets", "name": "OmniCorp Executive Emails", "category": "intel",
     "description": "Enough dirt to topple a board member.",
     "base_value": 1500, "rarity": "epic"},
    {"id": "district_map", "name": "SynthSec Patrol Routes", "category": "intel",
     "description": "Real-time patrol data for Districts 4-7. Updated nightly.",
     "base_value": 700, "rarity": "rare"},
    {"id": "blackmail_dossier", "name": "Senator Voss Dossier", "category": "intel",
     "description": "Photos, financial records, and a signed confession.",
     "base_value": 2200, "rarity": "epic"},

    # ── Contraband ─────────────────────────────────────────────────────
    {"id": "synth_dust", "name": "Synth-Dust (50g)", "category": "contraband",
     "description": "Crystallized neural stimulant. Highly addictive.",
     "base_value": 400, "rarity": "uncommon"},
    {"id": "red_ice", "name": "Red Ice Vial", "category": "contraband",
     "description": "Boosts reflexes 300% for 90 seconds. Then the shaking starts.",
     "base_value": 1100, "rarity": "rare"},
    {"id": "null_id", "name": "Null Identity Kit", "category": "contraband",
     "description": "New face, new prints, new life. One use only.",
     "base_value": 1800, "rarity": "epic"},
    {"id": "cloned_credits", "name": "Cloned Credit Chips (10k face)", "category": "contraband",
     "description": "Spendable for 48 hours before the bank notices.",
     "base_value": 500, "rarity": "uncommon"},

    # ── Medical ────────────────────────────────────────────────────────
    {"id": "military_medkit", "name": "Military Medkit", "category": "medical",
     "description": "Field surgery in a box. Heals everything short of death.",
     "base_value": 950, "rarity": "rare"},
    {"id": "cortex_booster", "name": "Cortex Booster Implant", "category": "medical",
     "description": "+40 IQ for 6 hours. Side effects include nosebleeds.",
     "base_value": 1600, "rarity": "epic"},
    {"id": "nanobot_swarm", "name": "Nanobot Repair Swarm", "category": "medical",
     "description": "Inject and forget. Heals tissue damage over 24 hours.",
     "base_value": 2400, "rarity": "legendary"},

    # ── Vehicles ───────────────────────────────────────────────────────
    {"id": "stealth_bike", "name": "Wraith Stealth Bike", "category": "vehicle",
     "description": "Zero-emission, radar-invisible. Top speed: 280 km/h.",
     "base_value": 3000, "rarity": "legendary"},
    {"id": "cargo_drone", "name": "Cargo Drone 'Mule'", "category": "vehicle",
     "description": "Autonomous delivery. 50kg capacity. No questions asked.",
     "base_value": 1200, "rarity": "rare"},

    # ── Art / Luxury ───────────────────────────────────────────────────
    {"id": "neon_painting", "name": "Original Neon Banksy", "category": "art",
     "description": "Glows in the dark. Authenticated on-chain.",
     "base_value": 2000, "rarity": "epic"},
    {"id": "chrome_skull", "name": "Chrome Skull of District Zero", "category": "art",
     "description": "Pulled from the ruins. Some say it's cursed.",
     "base_value": 1400, "rarity": "rare"},
    {"id": "synth_violin", "name": "Synthetic Stradivarius", "category": "art",
     "description": "AI-composed instrument. Plays itself on voice command.",
     "base_value": 3200, "rarity": "legendary"},
    {"id": "holo_diamond", "name": "Holographic Diamond", "category": "art",
     "description": "Looks real. Feels real. Technically isn't. Nobody cares.",
     "base_value": 750, "rarity": "uncommon"},
]

# Quick lookup by item id
_CATALOG_BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in AUCTION_CATALOG}

# Rarity multipliers — controls how high NPC bidding can push prices
RARITY_MULTIPLIER: Dict[str, float] = {
    "common": 1.2,
    "uncommon": 1.5,
    "rare": 2.0,
    "epic": 2.5,
    "legendary": 3.0,
}

# Rarity colors for UI
RARITY_COLORS: Dict[str, str] = {
    "common": "#9ca3af",
    "uncommon": "#22c55e",
    "rare": "#3b82f6",
    "epic": "#a855f7",
    "legendary": "#f59e0b",
}


# ══════════════════════════════════════════════════════════════════════════
#  NPC BIDDERS — 6 AI opponents with unique bidding personalities
# ══════════════════════════════════════════════════════════════════════════
# v1.50.0 [2026-03-22] — NPC bidder profiles + flavor text templates

NPC_BIDDERS: Dict[str, Dict[str, Any]] = {
    "cipher": {
        "name": "Cipher",
        "personality": "aggressive",
        "budget": 5000,
        "interests": ["tech", "intel"],
        "bid_style": "Always bids 20% above current. Gives up at 80% of budget.",
        "aggression": 0.20,        # bids 20% above current
        "give_up_ratio": 0.80,     # stops at 80% of remaining budget
        "bid_delay_range": (1.5, 4.0),   # fast bidder
        "flavor_templates": [
            "{amount}. Don't waste my time.",
            "I'll take that. {amount}.",
            "{amount}. Next.",
            "Cipher bids {amount}. *adjusts visor*",
            "{amount}. I know what this is worth.",
        ],
    },
    "mama_lo": {
        "name": "Mama Lo",
        "personality": "patient",
        "budget": 8000,
        "interests": ["medical", "contraband"],
        "bid_style": "Waits until final seconds, then snipes. Never exceeds budget.",
        "aggression": 0.10,        # conservative increments
        "give_up_ratio": 0.95,     # will spend almost everything on the right item
        "bid_delay_range": (20.0, 28.0),  # waits until the very end
        "flavor_templates": [
            "*silence* ... {amount}.",
            "Mama Lo nods slowly. {amount}.",
            "{amount}. *fans herself with credit chips*",
            "Oh? {amount}, dear.",
            "*waits* ... {amount}. You're welcome.",
        ],
    },
    "the_broker": {
        "name": "The Broker",
        "personality": "calculated",
        "budget": 10000,
        "interests": ["intel", "art"],
        "bid_style": "Only bids on items worth 2x+ base value. Precise increments.",
        "aggression": 0.12,        # precise, small increments
        "give_up_ratio": 0.70,     # knows when to walk away
        "bid_delay_range": (5.0, 12.0),  # measured pace
        "flavor_templates": [
            "The data alone is worth twice that. {amount}.",
            "{amount}. A calculated investment.",
            "My sources value this higher. {amount}.",
            "{amount}. *adjusts cufflinks*",
            "I'll go {amount}. The provenance checks out.",
        ],
    },
    "nyx": {
        "name": "Nyx",
        "personality": "impulsive",
        "budget": 4000,
        "interests": ["weapon", "contraband", "vehicle"],
        "bid_style": "Bids emotionally on weapons. Drops out randomly.",
        "aggression": 0.30,        # aggressive jumps
        "give_up_ratio": 0.60,     # easily discouraged
        "bid_delay_range": (2.0, 6.0),
        "flavor_templates": [
            "HELL YEAH. {amount}!",
            "{amount}! I need this!",
            "*slams table* {amount}.",
            "Nyx throws down {amount}. Try me.",
            "{amount}! *eyes gleaming*",
        ],
    },
    "silk": {
        "name": "Silk",
        "personality": "strategic",
        "budget": 6000,
        "interests": ["art", "medical", "tech"],
        "bid_style": "Targets undervalued lots. Drops early on hot items.",
        "aggression": 0.15,
        "give_up_ratio": 0.50,     # only buys bargains
        "bid_delay_range": (6.0, 15.0),
        "flavor_templates": [
            "{amount}. I know a collector who'd pay double.",
            "Silk raises a gloved hand. {amount}.",
            "{amount}. *smiles cryptically*",
            "An informed offer: {amount}.",
            "{amount}. Aesthetics have a price.",
        ],
    },
    "zero": {
        "name": "Zero-Day",
        "personality": "chaotic",
        "budget": 3500,
        "interests": ["tech", "weapon", "intel"],
        "bid_style": "Bids randomly. Sometimes wildly overbids, sometimes drops out instantly.",
        "aggression": 0.35,        # chaotic jumps
        "give_up_ratio": 0.90,     # unpredictable persistence
        "bid_delay_range": (1.0, 20.0),  # completely random timing
        "flavor_templates": [
            "{amount}?? Sure, why not. {amount}.",
            "*laughing* {amount}!",
            "Zero-Day yawns. {amount}.",
            "{amount}. I flipped a coin.",
            "Random number says... {amount}.",
        ],
    },
}


# ══════════════════════════════════════════════════════════════════════════
#  THE GAVEL — AI Auctioneer narration templates
# ══════════════════════════════════════════════════════════════════════════
# v1.50.0 [2026-03-22] — Dramatic auctioneer narration system

GAVEL_INTRO_TEMPLATES: List[str] = [
    "Ladies, gentlemen, and those who prefer anonymity... welcome to THE AUCTION HOUSE.",
    "The Gavel strikes the podium. Silence. Let the bidding commence.",
    "Another night, another fortune to be made — or lost. The Gavel presides.",
    "Smoke curls through amber light. The Gavel scans the room. We begin.",
]

GAVEL_ITEM_TEMPLATES: List[str] = [
    "Lot {lot_num}: {name}. {description} Starting bid: {start_price} credits.",
    "Next up — Lot {lot_num}. *The Gavel lifts {name} into the light.* {description} We open at {start_price}.",
    "Lot {lot_num} now. {name}. {description} The floor opens at {start_price} credits. Who dares?",
    "*The Gavel's eye gleams.* Lot {lot_num}: {name}. {description} {start_price} to start. Don't be shy.",
]

GAVEL_GOING_ONCE: List[str] = [
    "Going once at {amount} credits...",
    "{amount} credits on the floor. Going once...",
    "Do I hear more than {amount}? Going once...",
]

GAVEL_GOING_TWICE: List[str] = [
    "Going twice at {amount}...",
    "{amount}... going twice. Last chance.",
    "Going... going... {amount} credits. Speak now.",
]

GAVEL_SOLD: List[str] = [
    "SOLD! {item} to {winner} for {amount} credits!",
    "*BANG* — Sold! {item} belongs to {winner}. {amount} credits.",
    "The Gavel falls. {item} — {winner}, {amount} credits. A fine acquisition.",
    "SOLD to {winner} for {amount}. *The Gavel smirks.* Pleasure doing business.",
]

GAVEL_NO_BIDS: List[str] = [
    "No takers? {item} is withdrawn. Your loss.",
    "*The Gavel sighs.* No bids on {item}. Moving on.",
    "{item} goes unsold. The shadows keep their secrets tonight.",
]

GAVEL_SESSION_END: List[str] = [
    "That concludes tonight's auction. Collect your purchases at the back. Cash only.",
    "The Gavel rests. Tonight's session is closed. See you in the dark.",
    "All lots sold. The Gavel thanks you for your... patronage.",
]


# ══════════════════════════════════════════════════════════════════════════
#  AUCTION ENGINE — Core data structures
# ══════════════════════════════════════════════════════════════════════════
# v1.50.0 [2026-03-22] — BidderState, AuctionLot, AuctionSession dataclasses

@dataclass
class BidderState:
    """Tracks a player's auction session state.

    CONNECTS: PlayerState (credits), InventoryManager (items_won)
    """

    credits: int = 3000
    items_won: List[Dict[str, Any]] = field(default_factory=list)
    total_spent: int = 0
    auctions_attended: int = 0
    bid_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for REST / Socket.IO transport."""
        return {
            "credits": self.credits,
            "items_won": list(self.items_won),
            "total_spent": self.total_spent,
            "auctions_attended": self.auctions_attended,
            "bid_count": self.bid_count,
        }


@dataclass
class Bid:
    """A single bid on a lot.

    CONNECTS: AuctionLot.bid_history
    """

    bidder: str          # "player" or NPC id
    display_name: str    # display name for UI
    amount: int
    timestamp: float = field(default_factory=time.time)
    is_player: bool = False
    flavor_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bidder": self.bidder,
            "display_name": self.display_name,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "is_player": self.is_player,
            "flavor_text": self.flavor_text,
        }


@dataclass
class AuctionLot:
    """A single item being auctioned.

    CONNECTS: AUCTION_CATALOG (item data), Bid (bid_history)
    EMITS: auction_item, bid_placed, sold Socket.IO events
    """

    lot_number: int
    item: Dict[str, Any]             # catalog entry
    starting_price: int = 0          # computed from base_value
    current_price: int = 0
    current_winner: str = ""         # bidder id
    current_winner_name: str = ""    # display name
    bid_history: List[Bid] = field(default_factory=list)
    status: str = "pending"          # pending | active | going_once | going_twice | sold | unsold
    timer_start: float = 0.0
    duration: float = 30.0           # seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lot_number": self.lot_number,
            "item": dict(self.item),
            "starting_price": self.starting_price,
            "current_price": self.current_price,
            "current_winner": self.current_winner,
            "current_winner_name": self.current_winner_name,
            "bid_count": len(self.bid_history),
            "bid_history": [b.to_dict() for b in self.bid_history[-10:]],  # last 10
            "status": self.status,
            "time_remaining": max(0.0, self.duration - (time.time() - self.timer_start))
                if self.status in ("active", "going_once", "going_twice") else 0.0,
            "rarity_color": RARITY_COLORS.get(self.item.get("rarity", "common"), "#9ca3af"),
        }


@dataclass
class AuctionSession:
    """A full auction session containing multiple lots.

    CONNECTS: AuctionLot (lots), BidderState (player), NPC_BIDDERS
    CALLED BY: AuctionScene._start_session()
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    lots: List[AuctionLot] = field(default_factory=list)
    current_lot_index: int = -1
    status: str = "idle"             # idle | active | complete
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    npc_budgets: Dict[str, int] = field(default_factory=dict)  # runtime budgets

    def to_dict(self) -> Dict[str, Any]:
        current_lot = None
        if 0 <= self.current_lot_index < len(self.lots):
            current_lot = self.lots[self.current_lot_index].to_dict()
        return {
            "session_id": self.session_id,
            "status": self.status,
            "total_lots": len(self.lots),
            "current_lot_index": self.current_lot_index,
            "current_lot": current_lot,
            "lots_summary": [
                {
                    "lot_number": lot.lot_number,
                    "item_name": lot.item["name"],
                    "status": lot.status,
                    "sold_for": lot.current_price if lot.status == "sold" else None,
                    "winner": lot.current_winner_name if lot.status == "sold" else None,
                }
                for lot in self.lots
            ],
        }


# ══════════════════════════════════════════════════════════════════════════
#  NPC BIDDING AI ENGINE
# ══════════════════════════════════════════════════════════════════════════
# v1.50.0 [2026-03-22] — NPC bidding logic: interest matching,
#                          personality-driven timing, budget management

class NPCBiddingEngine:
    """Evaluates and generates NPC bids for a given lot.

    Each NPC has an interest match score, aggression level, and budget.
    The engine decides IF an NPC bids, HOW MUCH, and WHEN (delay).

    CONNECTS: NPC_BIDDERS (profiles), AuctionLot (current lot)
    CALLED BY: AuctionScene._schedule_npc_bids()
    """

    @staticmethod
    def interest_score(npc_id: str, item: Dict[str, Any]) -> float:
        """Compute how interested an NPC is in this item (0.0 to 1.0).

        Args:
            npc_id: NPC identifier key.
            item: Catalog item dict.

        Returns:
            Float interest score. 1.0 = perfect match, 0.0 = no interest.
        """
        profile = NPC_BIDDERS.get(npc_id)
        if not profile:
            return 0.0
        category = item.get("category", "")
        rarity = item.get("rarity", "common")
        # Base interest: does the NPC care about this category?
        if category in profile["interests"]:
            base = 0.7
        else:
            base = 0.15  # slight chance they bid on anything

        # Rarity bonus
        rarity_bonus = {"common": 0.0, "uncommon": 0.05, "rare": 0.1, "epic": 0.15, "legendary": 0.25}
        base += rarity_bonus.get(rarity, 0.0)

        # Personality modifier
        if profile["personality"] == "chaotic":
            base += random.uniform(-0.2, 0.3)  # wild swings
        elif profile["personality"] == "impulsive" and category in ("weapon", "contraband"):
            base += 0.15

        return max(0.0, min(1.0, base))

    @staticmethod
    def should_bid(
        npc_id: str,
        item: Dict[str, Any],
        current_price: int,
        npc_remaining_budget: int,
        time_elapsed: float,
        lot_duration: float,
    ) -> Optional[int]:
        """Decide if an NPC should bid and for how much.

        Args:
            npc_id: NPC identifier key.
            item: Catalog item dict.
            current_price: Current highest bid.
            npc_remaining_budget: Credits remaining for this NPC.
            time_elapsed: Seconds since lot opened.
            lot_duration: Total lot duration in seconds.

        Returns:
            Bid amount (int) or None if the NPC declines.
        """
        profile = NPC_BIDDERS.get(npc_id)
        if not profile:
            return None

        interest = NPCBiddingEngine.interest_score(npc_id, item)

        # No interest = no bid
        if interest < 0.2:
            return None

        # The Broker only bids if price is still below 2x base_value
        if npc_id == "the_broker":
            max_value = item.get("base_value", 500) * RARITY_MULTIPLIER.get(
                item.get("rarity", "common"), 1.5
            )
            if current_price > max_value * 0.8:
                return None

        # Budget check — give_up_ratio determines max willingness
        give_up_amount = int(npc_remaining_budget * profile["give_up_ratio"])
        max_bid = min(give_up_amount, npc_remaining_budget)

        # Aggression determines increment
        aggression = profile["aggression"]
        increment = max(int(current_price * aggression), int(item["base_value"] * 0.10))
        proposed_bid = current_price + increment

        # Chaotic NPC: sometimes wildly overbids
        if profile["personality"] == "chaotic" and random.random() < 0.25:
            proposed_bid = current_price + random.randint(increment, increment * 3)

        # Patient NPC (Mama Lo): only bids in final seconds
        if profile["personality"] == "patient":
            time_ratio = time_elapsed / lot_duration if lot_duration > 0 else 1.0
            if time_ratio < 0.65:
                return None  # waiting...

        # Impulsive NPC (Nyx): random dropout
        if profile["personality"] == "impulsive" and random.random() < 0.15:
            return None  # lost interest

        # Cap at max affordable
        if proposed_bid > max_bid:
            return None  # over budget, drop out

        if proposed_bid <= current_price:
            return None  # no point bidding at or below current

        return proposed_bid

    @staticmethod
    def get_bid_delay(npc_id: str) -> float:
        """Get randomized delay before this NPC places a bid.

        Args:
            npc_id: NPC identifier key.

        Returns:
            Delay in seconds.
        """
        profile = NPC_BIDDERS.get(npc_id)
        if not profile:
            return 5.0
        lo, hi = profile["bid_delay_range"]
        return random.uniform(lo, hi)

    @staticmethod
    def get_flavor_text(npc_id: str, amount: int) -> str:
        """Generate flavor text for an NPC bid.

        Args:
            npc_id: NPC identifier key.
            amount: Bid amount.

        Returns:
            Flavor text string.
        """
        profile = NPC_BIDDERS.get(npc_id)
        if not profile:
            return f"{amount} credits."
        template = random.choice(profile["flavor_templates"])
        return template.format(amount=f"{amount:,}")


# ══════════════════════════════════════════════════════════════════════════
#  AUCTION SCENE CLASS
# ══════════════════════════════════════════════════════════════════════════
# v1.50.0 [2026-03-22] — Complete AuctionScene with real-time bidding,
#                          NPC AI, session management, REST API, Socket.IO

class AuctionScene(FlaskScene):
    """THE AUCTION HOUSE — Underground black market auction scene.

    Players compete against 6 NPC bidders in real-time Socket.IO auctions.
    5 items per session, 30-second bidding windows, dramatic AI auctioneer.

    CONNECTS: FlaskScene, PlayerState, InventoryManager, NPCBiddingEngine
    CALLED BY: launcher.py, launcher_game.py, TUI
    EMITS: auction_item, bid_placed, bid_rejected, going_once, going_twice,
           sold, auction_complete, scene_state, hud_update
    """

    SCENE_METADATA = {
        "name": SCENE_ID,
        "display_name": "THE AUCTION HOUSE",
        "port": DEFAULT_PORT,
        "type": "scene",
        "accent_color": "#fbbf24",
        "accent_rgb": "251 191 36",
        "description": "Underground black market auctions. Bid on rare items, contraband, and secrets.",
    }

    ITEMS_PER_SESSION: int = 5
    LOT_DURATION: float = 30.0       # seconds per item
    GOING_ONCE_AT: float = 20.0      # seconds elapsed → going once
    GOING_TWICE_AT: float = 25.0     # seconds elapsed → going twice
    MIN_BID_INCREMENT: float = 0.10  # 10% of current price

    # v1.50.0 [2026-03-22] — Full constructor with auction engine state
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(host=host, port=port)

        # ── Auction Engine State ───────────────────────────────────────
        self._lock = threading.Lock()
        self._session: Optional[AuctionSession] = None
        self._bidder_state = BidderState()
        self._session_history: List[Dict[str, Any]] = []  # completed sessions
        self._npc_timers: List[threading.Timer] = []       # active NPC bid timers
        self._lot_timer: Optional[threading.Timer] = None  # lot countdown timer
        self._phase_timer: Optional[threading.Timer] = None  # going_once/twice timer

        # Sync starting credits with PlayerState
        try:
            ps = get_player_state()
            self._bidder_state.credits = ps.credits
        except Exception:
            logger.warning("[%s] Could not sync PlayerState credits, using default", SCENE_ID)

        # ── Setup ──────────────────────────────────────────────────────
        self._setup_routes()
        self._setup_socketio()

        logger.info("[%s] Auction scene initialized (operation=init)", SCENE_ID)

    # ══════════════════════════════════════════════════════════════════
    #  HTTP ROUTES
    # ══════════════════════════════════════════════════════════════════
    # v1.50.0 [2026-03-22] — REST API: state, start, bid, history, catalog

    def _setup_routes(self) -> None:
        """Register HTTP routes for THE AUCTION HOUSE.

        CONNECTS: Flask app router
        """

        @self.app.route("/")
        def index() -> str:
            return render_template("auction.html")

        @self.app.route("/api/scene/state")
        def scene_state() -> Any:
            """Return current scene state snapshot."""
            return jsonify(self._build_state())

        # v1.50.0 — GET /api/auction/state
        @self.app.route("/api/auction/state")
        def auction_state() -> Any:
            """Return current auction item, bids, timer, NPC bidders.

            Returns:
                JSON with session state, current lot, bidder state, active NPCs.
            """
            return jsonify(self._build_auction_state())

        # v1.50.0 — POST /api/auction/start
        @self.app.route("/api/auction/start", methods=["POST"])
        def auction_start() -> Any:
            """Start a new auction session with 5 random items.

            Returns:
                JSON with new session data or error if session already active.
            """
            with self._lock:
                if self._session and self._session.status == "active":
                    return jsonify({"error": "Auction already in progress"}), 409

            result = self._start_session()
            return jsonify(result)

        # v1.50.0 — POST /api/auction/bid
        @self.app.route("/api/auction/bid", methods=["POST"])
        def auction_bid() -> Any:
            """Place a player bid on the current lot.

            Expects JSON body: {"amount": int}

            Returns:
                JSON with bid result or rejection reason.
            """
            data = request.get_json(silent=True) or {}
            amount = data.get("amount")
            if amount is None:
                return jsonify({"error": "Missing 'amount' field"}), 400
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                return jsonify({"error": "Amount must be an integer"}), 400

            result = self._place_player_bid(amount)
            status_code = 200 if result.get("accepted") else 400
            return jsonify(result), status_code

        # v1.50.0 — GET /api/auction/history
        @self.app.route("/api/auction/history")
        def auction_history() -> Any:
            """Return past auction session results.

            Returns:
                JSON list of completed session summaries.
            """
            return jsonify({
                "history": list(self._session_history),
                "total_sessions": len(self._session_history),
            })

        # v1.50.0 — GET /api/auction/catalog
        @self.app.route("/api/auction/catalog")
        def auction_catalog() -> Any:
            """Browse all possible auction items.

            Returns:
                JSON list of catalog items with rarity colors.
            """
            catalog = []
            for item in AUCTION_CATALOG:
                entry = dict(item)
                entry["rarity_color"] = RARITY_COLORS.get(item.get("rarity", "common"), "#9ca3af")
                catalog.append(entry)
            return jsonify({"catalog": catalog, "total_items": len(catalog)})

    # ══════════════════════════════════════════════════════════════════
    #  SOCKET.IO HANDLERS
    # ══════════════════════════════════════════════════════════════════
    # v1.50.0 [2026-03-22] — Real-time bidding via Socket.IO

    def _setup_socketio(self) -> None:
        """Register Socket.IO event handlers.

        CONNECTS: Flask-SocketIO
        EMITS: scene_state, auction_item, bid_placed, bid_rejected,
               going_once, going_twice, sold, auction_complete
        """

        @self.socketio.on("connect")
        def on_connect() -> None:
            logger.info("[%s] Client connected (operation=socket)", SCENE_ID)
            emit("scene_state", self._build_state())
            # If auction is active, send current lot state
            if self._session and self._session.status == "active":
                emit("auction_state", self._build_auction_state())

        @self.socketio.on("get_state")
        def on_get_state() -> None:
            """Client requests full state refresh."""
            emit("scene_state", self._build_state())
            if self._session and self._session.status == "active":
                emit("auction_state", self._build_auction_state())

        @self.socketio.on("auction_start")
        def on_auction_start() -> None:
            """Client requests a new auction session via Socket.IO."""
            with self._lock:
                if self._session and self._session.status == "active":
                    emit("error", {"message": "Auction already in progress"})
                    return
            result = self._start_session()
            # Session start is broadcast via _emit_to_all in _start_session

        @self.socketio.on("auction_bid")
        def on_auction_bid(data: Dict[str, Any]) -> None:
            """Client places a bid via Socket.IO.

            Args:
                data: Dict with ``amount`` (int).
            """
            data = data or {}
            amount = data.get("amount")
            if amount is None:
                emit("bid_rejected", {"reason": "Missing bid amount"})
                return
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                emit("bid_rejected", {"reason": "Amount must be a number"})
                return
            result = self._place_player_bid(amount)
            # bid_placed / bid_rejected emitted inside _place_player_bid

        @self.socketio.on("action")
        def on_action(data: Dict[str, Any]) -> None:
            """Handle generic client actions.

            Args:
                data: Dict with ``action`` (str) and optional payload keys.
            """
            action = (data or {}).get("action", "")
            logger.debug("[%s] action '%s' payload=%s (operation=action)", SCENE_ID, action, data)

            if action == "start_auction":
                on_auction_start()
            elif action == "place_bid":
                on_auction_bid(data)
            elif action == "get_catalog":
                emit("catalog", {"catalog": AUCTION_CATALOG})

    # ══════════════════════════════════════════════════════════════════
    #  AUCTION SESSION MANAGEMENT
    # ══════════════════════════════════════════════════════════════════
    # v1.50.0 [2026-03-22] — Session lifecycle: start, advance, finish

    def _start_session(self) -> Dict[str, Any]:
        """Start a new auction session with 5 randomly drawn items.

        Selects items from the catalog, initializes NPC budgets, and
        begins the first lot.

        CONNECTS: AUCTION_CATALOG, NPC_BIDDERS, BidderState
        EMITS: auction_item (first lot), gavel_narration (intro)

        Returns:
            Dict with session info for REST response.
        """
        # Refresh player credits from PlayerState
        try:
            ps = get_player_state()
            self._bidder_state.credits = ps.credits
        except Exception as e:
            logger.debug("[%s] PlayerState credit sync failed (operation=start_session): %s", SCENE_ID, e)

        # Select 5 random items from catalog (no duplicates within session)
        items = random.sample(AUCTION_CATALOG, min(self.ITEMS_PER_SESSION, len(AUCTION_CATALOG)))

        lots: List[AuctionLot] = []
        for i, item in enumerate(items):
            # Starting price = 60-80% of base value (creates bidding headroom)
            start_pct = random.uniform(0.60, 0.80)
            starting_price = max(50, int(item["base_value"] * start_pct))
            # Round to nearest 10 for clean numbers
            starting_price = (starting_price // 10) * 10
            lots.append(AuctionLot(
                lot_number=i + 1,
                item=dict(item),
                starting_price=starting_price,
                current_price=starting_price,
                duration=self.LOT_DURATION,
            ))

        # Initialize NPC budgets for this session
        npc_budgets = {}
        for npc_id, profile in NPC_BIDDERS.items():
            # Add some randomness to budget (80-120% of base)
            budget_variance = random.uniform(0.80, 1.20)
            npc_budgets[npc_id] = int(profile["budget"] * budget_variance)

        session = AuctionSession(
            lots=lots,
            status="active",
            started_at=time.time(),
            npc_budgets=npc_budgets,
        )
        self._session = session
        self._bidder_state.auctions_attended += 1

        logger.info(
            "[%s] New auction session %s with %d lots (operation=session_start)",
            SCENE_ID, session.session_id, len(lots),
        )

        # Narrate the intro
        intro = random.choice(GAVEL_INTRO_TEMPLATES)
        self._emit_to_all("gavel_narration", {"text": intro, "type": "intro"})

        # Begin first lot after a brief dramatic pause
        timer = threading.Timer(2.0, self._advance_to_next_lot)
        timer.daemon = True
        timer.start()
        self._lot_timer = timer

        return {
            "session_id": session.session_id,
            "total_lots": len(lots),
            "lots_preview": [
                {"lot_number": lot.lot_number, "item_name": lot.item["name"],
                 "rarity": lot.item["rarity"], "starting_price": lot.starting_price}
                for lot in lots
            ],
            "player_credits": self._bidder_state.credits,
            "status": "started",
        }

    def _advance_to_next_lot(self) -> None:
        """Advance to the next lot in the session.

        If all lots are done, finalize the session.

        CONNECTS: AuctionSession, AuctionLot
        EMITS: auction_item (new lot data), gavel_narration (item intro)
        """
        if not self._session or self._session.status != "active":
            return

        self._cancel_npc_timers()

        with self._lock:
            self._session.current_lot_index += 1
            idx = self._session.current_lot_index

        if idx >= len(self._session.lots):
            # All lots done — finalize session
            self._finalize_session()
            return

        lot = self._session.lots[idx]
        lot.status = "active"
        lot.timer_start = time.time()

        # Narrate the item
        template = random.choice(GAVEL_ITEM_TEMPLATES)
        narration = template.format(
            lot_num=lot.lot_number,
            name=lot.item["name"],
            description=lot.item["description"],
            start_price=f"{lot.starting_price:,}",
        )

        logger.info(
            "[%s] Lot %d: %s (base=%d, start=%d) (operation=lot_start)",
            SCENE_ID, lot.lot_number, lot.item["name"],
            lot.item["base_value"], lot.starting_price,
        )

        self._emit_to_all("gavel_narration", {"text": narration, "type": "item_intro"})
        self._emit_to_all("auction_item", lot.to_dict())

        # Schedule NPC bids for this lot
        self._schedule_npc_bids(lot)

        # Schedule going_once / going_twice / sold timers
        self._schedule_lot_phases(lot)

    def _schedule_lot_phases(self, lot: AuctionLot) -> None:
        """Schedule the going_once, going_twice, and sold phases.

        Args:
            lot: The active auction lot.

        CONNECTS: AuctionLot timer
        EMITS: going_once, going_twice, sold
        """
        # going_once at GOING_ONCE_AT seconds
        t1 = threading.Timer(self.GOING_ONCE_AT, self._phase_going_once, args=[lot])
        t1.daemon = True
        t1.start()

        # going_twice at GOING_TWICE_AT seconds
        t2 = threading.Timer(self.GOING_TWICE_AT, self._phase_going_twice, args=[lot])
        t2.daemon = True
        t2.start()

        # sold at LOT_DURATION seconds
        t3 = threading.Timer(self.LOT_DURATION, self._phase_sold, args=[lot])
        t3.daemon = True
        t3.start()

        self._npc_timers.extend([t1, t2, t3])

    def _phase_going_once(self, lot: AuctionLot) -> None:
        """Trigger 'going once' phase at 10 seconds remaining.

        Args:
            lot: The active auction lot.

        EMITS: going_once
        """
        if lot.status != "active":
            return
        lot.status = "going_once"
        narration = random.choice(GAVEL_GOING_ONCE).format(amount=f"{lot.current_price:,}")
        self._emit_to_all("going_once", {
            "lot_number": lot.lot_number,
            "current_price": lot.current_price,
            "current_winner": lot.current_winner_name,
            "narration": narration,
            "seconds_remaining": self.LOT_DURATION - self.GOING_ONCE_AT,
        })
        self._emit_to_all("gavel_narration", {"text": narration, "type": "going_once"})
        logger.info("[%s] Lot %d: GOING ONCE at %d (operation=phase)", SCENE_ID, lot.lot_number, lot.current_price)

    def _phase_going_twice(self, lot: AuctionLot) -> None:
        """Trigger 'going twice' phase at 5 seconds remaining.

        Args:
            lot: The active auction lot.

        EMITS: going_twice
        """
        if lot.status not in ("active", "going_once"):
            return
        lot.status = "going_twice"
        narration = random.choice(GAVEL_GOING_TWICE).format(amount=f"{lot.current_price:,}")
        self._emit_to_all("going_twice", {
            "lot_number": lot.lot_number,
            "current_price": lot.current_price,
            "current_winner": lot.current_winner_name,
            "narration": narration,
            "seconds_remaining": self.LOT_DURATION - self.GOING_TWICE_AT,
        })
        self._emit_to_all("gavel_narration", {"text": narration, "type": "going_twice"})
        logger.info("[%s] Lot %d: GOING TWICE at %d (operation=phase)", SCENE_ID, lot.lot_number, lot.current_price)

    def _phase_sold(self, lot: AuctionLot) -> None:
        """Finalize a lot — sold to highest bidder or unsold.

        Awards item to winner, deducts credits, updates inventories.

        Args:
            lot: The auction lot to finalize.

        CONNECTS: PlayerState (credits), InventoryManager (item add)
        EMITS: sold / unsold
        """
        if lot.status == "sold" or lot.status == "unsold":
            return  # already finalized (late bid may have triggered early)

        if lot.current_winner:
            lot.status = "sold"
            winner_name = lot.current_winner_name
            winner_id = lot.current_winner
            amount = lot.current_price

            narration = random.choice(GAVEL_SOLD).format(
                item=lot.item["name"],
                winner=winner_name,
                amount=f"{amount:,}",
            )

            # Credit deduction and item award
            if winner_id == "player":
                self._award_item_to_player(lot)
            else:
                # NPC won — deduct from their session budget
                if self._session and winner_id in self._session.npc_budgets:
                    self._session.npc_budgets[winner_id] = max(
                        0, self._session.npc_budgets[winner_id] - amount
                    )

            self._emit_to_all("sold", {
                "lot_number": lot.lot_number,
                "item": lot.item,
                "winner": winner_id,
                "winner_name": winner_name,
                "amount": amount,
                "is_player": winner_id == "player",
                "narration": narration,
            })
            self._emit_to_all("gavel_narration", {"text": narration, "type": "sold"})
            logger.info(
                "[%s] Lot %d SOLD: %s → %s for %d (operation=sold)",
                SCENE_ID, lot.lot_number, lot.item["name"], winner_name, amount,
            )
        else:
            lot.status = "unsold"
            narration = random.choice(GAVEL_NO_BIDS).format(item=lot.item["name"])
            self._emit_to_all("unsold", {
                "lot_number": lot.lot_number,
                "item": lot.item,
                "narration": narration,
            })
            self._emit_to_all("gavel_narration", {"text": narration, "type": "unsold"})
            logger.info("[%s] Lot %d UNSOLD: %s (operation=unsold)", SCENE_ID, lot.lot_number, lot.item["name"])

        # Advance to next lot after a pause
        timer = threading.Timer(3.0, self._advance_to_next_lot)
        timer.daemon = True
        timer.start()
        self._lot_timer = timer

    def _award_item_to_player(self, lot: AuctionLot) -> None:
        """Award a won item to the player.

        Deducts credits from PlayerState and adds item to inventory.

        Args:
            lot: The won auction lot.

        CONNECTS: PlayerState.spend_credits, InventoryManager.add_item
        EMITS: hud_update (via PlayerState)
        """
        amount = lot.current_price

        # Deduct from PlayerState
        try:
            ps = get_player_state()
            result = ps.spend_credits(amount, reason=f"auction:{lot.item['name']}")
            if result is not None:
                self._bidder_state.credits = result
            else:
                logger.warning("[%s] PlayerState credit deduction failed for %d (operation=award)", SCENE_ID, amount)
        except Exception as exc:
            logger.error("[%s] PlayerState integration error: %s (operation=award)", SCENE_ID, exc)

        # Track locally
        self._bidder_state.total_spent += amount
        self._bidder_state.items_won.append({
            "item_id": lot.item["id"],
            "name": lot.item["name"],
            "category": lot.item["category"],
            "rarity": lot.item["rarity"],
            "paid": amount,
            "base_value": lot.item["base_value"],
            "won_at": time.time(),
        })

        # Add to inventory system
        try:
            from engine.world.inventory import InventoryManager
            inv = InventoryManager.get()
            inv.add_item(lot.item["id"], tags=["auction_purchase"])
            logger.info("[%s] Item %s added to inventory (operation=award)", SCENE_ID, lot.item["id"])
        except Exception as exc:
            logger.warning("[%s] InventoryManager unavailable, using PlayerState fallback: %s", SCENE_ID, exc)
            try:
                ps = get_player_state()
                ps.add_item(lot.item["id"])
            except Exception as exc2:
                logger.error("[%s] Could not add item to any inventory: %s (operation=award)", SCENE_ID, exc2)

    def _finalize_session(self) -> None:
        """Finalize the current auction session.

        Computes summary, archives to history, and broadcasts completion.

        CONNECTS: AuctionSession, BidderState
        EMITS: auction_complete, gavel_narration (closing)
        """
        if not self._session:
            return

        self._cancel_npc_timers()
        self._session.status = "complete"
        self._session.ended_at = time.time()

        # Build session summary
        items_sold = [lot for lot in self._session.lots if lot.status == "sold"]
        items_unsold = [lot for lot in self._session.lots if lot.status == "unsold"]
        player_wins = [lot for lot in items_sold if lot.current_winner == "player"]
        total_revenue = sum(lot.current_price for lot in items_sold)

        summary = {
            "session_id": self._session.session_id,
            "total_lots": len(self._session.lots),
            "items_sold": len(items_sold),
            "items_unsold": len(items_unsold),
            "total_revenue": total_revenue,
            "player_wins": len(player_wins),
            "player_spent": sum(lot.current_price for lot in player_wins),
            "player_items": [
                {"name": lot.item["name"], "paid": lot.current_price, "rarity": lot.item["rarity"]}
                for lot in player_wins
            ],
            "all_results": [
                {
                    "lot_number": lot.lot_number,
                    "item_name": lot.item["name"],
                    "status": lot.status,
                    "sold_for": lot.current_price if lot.status == "sold" else None,
                    "winner": lot.current_winner_name if lot.status == "sold" else None,
                    "bid_count": len(lot.bid_history),
                }
                for lot in self._session.lots
            ],
            "player_credits_remaining": self._bidder_state.credits,
            "ended_at": datetime.now().isoformat(),
        }

        self._session_history.append(summary)
        # Keep last 20 sessions
        if len(self._session_history) > 20:
            self._session_history = self._session_history[-20:]

        # Narrate closing
        narration = random.choice(GAVEL_SESSION_END)
        self._emit_to_all("gavel_narration", {"text": narration, "type": "session_end"})
        self._emit_to_all("auction_complete", summary)

        logger.info(
            "[%s] Session %s complete: %d sold, %d unsold, revenue=%d (operation=session_end)",
            SCENE_ID, self._session.session_id, len(items_sold), len(items_unsold), total_revenue,
        )

    # ══════════════════════════════════════════════════════════════════
    #  BIDDING ENGINE
    # ══════════════════════════════════════════════════════════════════
    # v1.50.0 [2026-03-22] — Player bid processing + NPC bid scheduling

    def _place_player_bid(self, amount: int) -> Dict[str, Any]:
        """Process a player bid on the current lot.

        Validates the bid amount, checks funds, and records it.

        Args:
            amount: Bid amount in credits.

        CONNECTS: BidderState, AuctionLot
        EMITS: bid_placed (broadcast) or bid_rejected (to caller)

        Returns:
            Dict with acceptance status and details.
        """
        # Validate session is active
        if not self._session or self._session.status != "active":
            result = {"accepted": False, "reason": "No active auction session"}
            self._emit_to_all("bid_rejected", result)
            return result

        idx = self._session.current_lot_index
        if idx < 0 or idx >= len(self._session.lots):
            result = {"accepted": False, "reason": "No active lot"}
            self._emit_to_all("bid_rejected", result)
            return result

        lot = self._session.lots[idx]
        if lot.status not in ("active", "going_once", "going_twice"):
            result = {"accepted": False, "reason": "Bidding on this lot has ended"}
            self._emit_to_all("bid_rejected", result)
            return result

        # Check minimum bid increment (10% of current price)
        min_bid = lot.current_price + max(1, int(lot.current_price * self.MIN_BID_INCREMENT))
        if amount < min_bid:
            result = {
                "accepted": False,
                "reason": f"Bid too low. Minimum bid: {min_bid:,} credits (current: {lot.current_price:,} + 10%)",
                "minimum_bid": min_bid,
                "current_price": lot.current_price,
            }
            self._emit_to_all("bid_rejected", result)
            return result

        # Check player funds (use live PlayerState)
        try:
            ps = get_player_state()
            available = ps.credits
            self._bidder_state.credits = available
        except Exception as e:
            logger.debug("[%s] PlayerState credit check failed (operation=place_bid): %s", SCENE_ID, e)
            available = self._bidder_state.credits

        if amount > available:
            result = {
                "accepted": False,
                "reason": f"Insufficient funds. You have {available:,} credits.",
                "available_credits": available,
            }
            self._emit_to_all("bid_rejected", result)
            return result

        # Place the bid
        with self._lock:
            bid = Bid(
                bidder="player",
                display_name="You",
                amount=amount,
                is_player=True,
                flavor_text=f"Player bids {amount:,} credits.",
            )
            lot.bid_history.append(bid)
            lot.current_price = amount
            lot.current_winner = "player"
            lot.current_winner_name = "You"
            self._bidder_state.bid_count += 1

        # Reset to "active" if bid came during going_once/twice (extends the auction)
        if lot.status in ("going_once", "going_twice"):
            lot.status = "active"
            # Reschedule phases from the bid time
            self._reschedule_lot_phases(lot)

        bid_data = {
            "accepted": True,
            "bidder": "player",
            "display_name": "You",
            "amount": amount,
            "is_player": True,
            "lot_number": lot.lot_number,
            "flavor_text": f"Player bids {amount:,} credits.",
        }
        self._emit_to_all("bid_placed", bid_data)

        logger.info("[%s] Player bid %d on lot %d (operation=bid)", SCENE_ID, amount, lot.lot_number)

        # Trigger reactive NPC bids — some NPCs respond to player bids
        self._schedule_reactive_npc_bids(lot)

        return bid_data

    def _place_npc_bid(self, npc_id: str, lot: AuctionLot) -> None:
        """Process an NPC bid on a lot.

        Called by NPC timer threads. Evaluates if the NPC should bid
        using NPCBiddingEngine, then places the bid if appropriate.

        Args:
            npc_id: NPC identifier.
            lot: The auction lot being bid on.

        CONNECTS: NPCBiddingEngine, NPC_BIDDERS, AuctionSession.npc_budgets
        EMITS: bid_placed (broadcast)
        """
        if not self._session or self._session.status != "active":
            return
        if lot.status not in ("active", "going_once", "going_twice"):
            return

        profile = NPC_BIDDERS.get(npc_id)
        if not profile:
            return

        # Get NPC's remaining budget for this session
        remaining_budget = self._session.npc_budgets.get(npc_id, 0)
        if remaining_budget <= 0:
            return

        time_elapsed = time.time() - lot.timer_start

        # Ask the bidding engine if this NPC should bid
        proposed_amount = NPCBiddingEngine.should_bid(
            npc_id=npc_id,
            item=lot.item,
            current_price=lot.current_price,
            npc_remaining_budget=remaining_budget,
            time_elapsed=time_elapsed,
            lot_duration=lot.duration,
        )

        if proposed_amount is None:
            return  # NPC declines

        # Validate bid is above current + minimum increment
        min_bid = lot.current_price + max(1, int(lot.current_price * self.MIN_BID_INCREMENT))
        if proposed_amount < min_bid:
            proposed_amount = min_bid

        # Cap at remaining budget
        if proposed_amount > remaining_budget:
            return

        # Place the bid
        flavor = NPCBiddingEngine.get_flavor_text(npc_id, proposed_amount)
        with self._lock:
            bid = Bid(
                bidder=npc_id,
                display_name=profile["name"],
                amount=proposed_amount,
                is_player=False,
                flavor_text=flavor,
            )
            lot.bid_history.append(bid)
            lot.current_price = proposed_amount
            lot.current_winner = npc_id
            lot.current_winner_name = profile["name"]

        # Reset to "active" if bid came during going_once/twice
        if lot.status in ("going_once", "going_twice"):
            lot.status = "active"
            self._reschedule_lot_phases(lot)

        bid_data = {
            "accepted": True,
            "bidder": npc_id,
            "display_name": profile["name"],
            "amount": proposed_amount,
            "is_player": False,
            "lot_number": lot.lot_number,
            "flavor_text": flavor,
        }
        self._emit_to_all("bid_placed", bid_data)

        logger.info(
            "[%s] NPC %s bid %d on lot %d (operation=npc_bid)",
            SCENE_ID, profile["name"], proposed_amount, lot.lot_number,
        )

        # Some NPCs may trigger further reactive bids from others
        self._schedule_reactive_npc_bids(lot, exclude=npc_id)

    def _schedule_npc_bids(self, lot: AuctionLot) -> None:
        """Schedule initial NPC bids for a new lot.

        Each NPC gets a timer based on their personality-driven delay.

        Args:
            lot: The active auction lot.

        CONNECTS: NPCBiddingEngine, NPC_BIDDERS
        """
        for npc_id in NPC_BIDDERS:
            interest = NPCBiddingEngine.interest_score(npc_id, lot.item)
            if interest < 0.15:
                continue  # not interested at all

            delay = NPCBiddingEngine.get_bid_delay(npc_id)
            timer = threading.Timer(delay, self._place_npc_bid, args=[npc_id, lot])
            timer.daemon = True
            timer.start()
            self._npc_timers.append(timer)

    def _schedule_reactive_npc_bids(self, lot: AuctionLot, exclude: str = "") -> None:
        """Schedule reactive NPC bids in response to a new bid.

        NPCs that are interested may counter-bid after a personality delay.

        Args:
            lot: The active auction lot.
            exclude: NPC ID to exclude (the one who just bid).

        CONNECTS: NPCBiddingEngine, NPC_BIDDERS
        """
        for npc_id, profile in NPC_BIDDERS.items():
            if npc_id == exclude:
                continue
            if npc_id == lot.current_winner:
                continue  # already the highest bidder

            interest = NPCBiddingEngine.interest_score(npc_id, lot.item)
            if interest < 0.3:
                continue  # not interested enough to react

            # Reactive delay is shorter than initial (2-8 seconds)
            delay = random.uniform(2.0, 8.0)
            # Aggressive bidders react faster
            if profile["personality"] == "aggressive":
                delay *= 0.5
            elif profile["personality"] == "patient":
                # Patient NPCs don't do reactive bids unless very late in the auction
                time_elapsed = time.time() - lot.timer_start
                if time_elapsed < lot.duration * 0.6:
                    continue
                delay = random.uniform(1.0, 3.0)

            timer = threading.Timer(delay, self._place_npc_bid, args=[npc_id, lot])
            timer.daemon = True
            timer.start()
            self._npc_timers.append(timer)

    def _reschedule_lot_phases(self, lot: AuctionLot) -> None:
        """Reschedule going_once/going_twice/sold timers after a late bid.

        When a bid comes in during going_once or going_twice, the lot
        resets to "active" and phases are rescheduled from a shorter window
        (15 seconds instead of full 30) to keep the auction moving.

        Args:
            lot: The active auction lot.
        """
        # Cancel existing phase timers (they're mixed in with npc_timers)
        # We can't selectively cancel, so we just add new ones — the
        # phase handlers check lot.status to avoid double-firing.

        # Shortened window: 15 seconds after a late bid
        extension = 15.0
        lot.timer_start = time.time()
        lot.duration = extension

        t1 = threading.Timer(extension - 10.0, self._phase_going_once, args=[lot])
        t1.daemon = True
        t1.start()

        t2 = threading.Timer(extension - 5.0, self._phase_going_twice, args=[lot])
        t2.daemon = True
        t2.start()

        t3 = threading.Timer(extension, self._phase_sold, args=[lot])
        t3.daemon = True
        t3.start()

        self._npc_timers.extend([t1, t2, t3])

        logger.debug("[%s] Lot %d phases rescheduled (+%.0fs extension) (operation=reschedule)",
                     SCENE_ID, lot.lot_number, extension)

    def _cancel_npc_timers(self) -> None:
        """Cancel all active NPC bid timers and phase timers."""
        for timer in self._npc_timers:
            try:
                timer.cancel()
            except Exception as e:
                logger.debug("[%s] NPC timer cancel failed (operation=cancel_timers): %s", SCENE_ID, e)
        self._npc_timers.clear()

        if self._lot_timer:
            try:
                self._lot_timer.cancel()
            except Exception as e:
                logger.debug("[%s] Lot timer cancel failed (operation=cancel_timers): %s", SCENE_ID, e)
            self._lot_timer = None

    # ══════════════════════════════════════════════════════════════════
    #  STATE BUILDERS
    # ══════════════════════════════════════════════════════════════════
    # v1.50.0 [2026-03-22] — Scene state + auction state builders

    def _build_state(self) -> Dict[str, Any]:
        """Build a scene state snapshot for the client.

        Returns:
            Dict with scene metadata, player state, and auction summary.
        """
        ps = get_player_state()
        self._bidder_state.credits = ps.credits
        return {
            "scene_id": SCENE_ID,
            "display_name": "THE AUCTION HOUSE",
            "player": {
                "credits": ps.credits,
                "health": ps.health,
                "energy": ps.energy,
                "reputation": ps.reputation,
            },
            "auction": {
                "session_active": bool(self._session and self._session.status == "active"),
                "bidder_state": self._bidder_state.to_dict(),
                "session_count": len(self._session_history),
            },
        }

    def _build_auction_state(self) -> Dict[str, Any]:
        """Build detailed auction state for the client.

        Returns:
            Dict with full session data, current lot, bids, NPC info, timer.
        """
        state: Dict[str, Any] = {
            "session": None,
            "bidder_state": self._bidder_state.to_dict(),
            "npcs": {},
        }

        if self._session:
            state["session"] = self._session.to_dict()

            # Include NPC info (names, personalities, remaining budget hints)
            for npc_id, profile in NPC_BIDDERS.items():
                remaining = self._session.npc_budgets.get(npc_id, 0)
                # Don't reveal exact budgets — give hints
                if remaining > profile["budget"] * 0.7:
                    budget_hint = "flush"
                elif remaining > profile["budget"] * 0.3:
                    budget_hint = "moderate"
                elif remaining > 0:
                    budget_hint = "tight"
                else:
                    budget_hint = "broke"

                state["npcs"][npc_id] = {
                    "name": profile["name"],
                    "personality": profile["personality"],
                    "interests": profile["interests"],
                    "budget_hint": budget_hint,
                    "active": remaining > 0,
                }

        return state

    # ══════════════════════════════════════════════════════════════════
    #  SOCKET.IO HELPERS
    # ══════════════════════════════════════════════════════════════════
    # v1.50.0 [2026-03-22] — Broadcast helper for thread-safe emission

    def _emit_to_all(self, event: str, data: Dict[str, Any]) -> None:
        """Emit a Socket.IO event to all connected clients.

        Thread-safe — can be called from NPC timer threads.

        Args:
            event: Socket.IO event name.
            data: Event payload.
        """
        try:
            self.socketio.emit(event, data)
        except Exception as exc:
            logger.warning(
                "[%s] Failed to emit '%s': %s (operation=emit)",
                SCENE_ID, event, exc,
            )

    # ══════════════════════════════════════════════════════════════════
    #  LIFECYCLE HOOKS
    # ══════════════════════════════════════════════════════════════════

    def on_before_serve(self) -> None:
        """Scene-specific setup before serving.

        Logs readiness and catalog stats.
        """
        logger.info(
            "[%s] THE AUCTION HOUSE ready on port %d — %d items in catalog, %d NPC bidders (operation=lifecycle)",
            SCENE_ID, DEFAULT_PORT, len(AUCTION_CATALOG), len(NPC_BIDDERS),
        )
