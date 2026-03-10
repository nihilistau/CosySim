"""Dynamic market & trade system for CosySim v1.0 "NeonCity 2".

Models supply-and-demand economics across NeonCity's districts.  Each
district hosts shops with dynamically priced goods; prices shift in
response to territory control, world events, and player activity.

Goods are divided into 6 categories:

* **weapons** — firearms, melee, explosives
* **tech** — cyberdecks, programs, implants
* **consumables** — stims, medkits, food
* **contraband** — drugs, stolen data, forged IDs
* **intel** — faction secrets, blueprints, access codes
* **luxury** — art, fashion, collectibles

Each good tracks a *base_price*, a *supply* level (0–100, where high supply
pushes price down), and a *demand* level (0–100, where high demand pushes
price up).  Current price is computed as:

    current = base_price * (1 + (demand - supply) / 100)

Territory control multipliers apply on top: the dominant faction in each
district nudges prices for their specialty goods.

Usage::

    from engine.world.market import get_market, GoodCategory

    mkt = get_market()
    prices = mkt.get_prices("DOWNTOWN")
    result = mkt.buy("DOWNTOWN", "stim_pack", quantity=3, player_id="player1")
    mkt.tick()  # advance supply/demand one step

"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Lazy imports ────

try:
    from engine.events.event_bus import get_event_bus as _get_event_bus
    _HAS_BUS = True
except ImportError:  # pragma: no cover
    _get_event_bus = lambda: None  # type: ignore[assignment]
    _HAS_BUS = False


# ──── Enums ────


class GoodCategory(str, Enum):
    """Categories of tradable goods."""
    WEAPONS = "weapons"
    TECH = "tech"
    CONSUMABLES = "consumables"
    CONTRABAND = "contraband"
    INTEL = "intel"
    LUXURY = "luxury"


# ──── Data classes ────


@dataclass
class Good:
    """A single tradable good.

    Attributes:
        id: Unique identifier.
        name: Display name.
        category: Which GoodCategory it belongs to.
        base_price: Price before supply/demand adjustments.
        supply: Current supply level (0–100).
        demand: Current demand level (0–100).
        description: Flavour text.
        illegal: Whether possessing this triggers heat.
        rarity: 1 (common) to 5 (legendary).
    """
    id: str
    name: str
    category: str
    base_price: int
    supply: float = 50.0
    demand: float = 50.0
    description: str = ""
    illegal: bool = False
    rarity: int = 1

    @property
    def current_price(self) -> int:
        """Compute price from supply/demand."""
        modifier = 1.0 + (self.demand - self.supply) / 100.0
        return max(1, int(self.base_price * modifier))

    def to_dict(self) -> Dict[str, Any]:
        """Serializable snapshot."""
        d = asdict(self)
        d["current_price"] = self.current_price
        return d


@dataclass
class Shop:
    """A shop in a district that stocks a subset of goods.

    Attributes:
        id: Unique shop identifier.
        name: Display name.
        district: Which district this shop is in.
        owner_npc: NPC who runs the shop (optional).
        categories: Which good categories this shop stocks.
        price_modifier: Multiplier on top of good's current_price (1.0 = normal).
        reputation_required: Min player reputation to access (-100..100).
    """
    id: str
    name: str
    district: str
    owner_npc: str = ""
    categories: List[str] = field(default_factory=list)
    price_modifier: float = 1.0
    reputation_required: int = -100

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeRecord:
    """A single buy/sell transaction in the market."""
    good_id: str
    quantity: int
    unit_price: int
    total: int
    action: str  # "buy" or "sell"
    district: str
    player_id: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──── Good Catalog ────

GOOD_CATALOG: Dict[str, Dict[str, Any]] = {
    # Weapons
    "street_pistol": {"name": "Street Pistol", "category": "weapons", "base_price": 250, "rarity": 1,
                      "description": "Cheap but reliable sidearm for street-level protection."},
    "plasma_cutter": {"name": "Plasma Cutter", "category": "weapons", "base_price": 800, "rarity": 3,
                      "description": "Industrial cutting tool repurposed as a close-range weapon."},
    "smart_rifle": {"name": "Smart Rifle", "category": "weapons", "base_price": 1500, "rarity": 4,
                    "description": "Self-aiming rifle with targeting VI. Corp-grade hardware."},
    "mono_blade": {"name": "Mono Blade", "category": "weapons", "base_price": 600, "rarity": 2,
                   "description": "Monomolecular-edged melee weapon. Cuts through most armor."},
    "emp_grenade": {"name": "EMP Grenade", "category": "weapons", "base_price": 350, "rarity": 2,
                    "description": "Disables electronics in a 10m radius. Single-use."},

    # Tech
    "basic_cyberdeck": {"name": "Basic Cyberdeck", "category": "tech", "base_price": 500, "rarity": 1,
                        "description": "Entry-level hacking hardware. 4 RAM slots."},
    "neural_booster": {"name": "Neural Booster", "category": "tech", "base_price": 1200, "rarity": 3,
                       "description": "Implant that speeds cognitive processing by 40%."},
    "stealth_module": {"name": "Stealth Module", "category": "tech", "base_price": 900, "rarity": 3,
                       "description": "Optical camouflage addon for cyberdecks."},
    "data_shard": {"name": "Data Shard", "category": "tech", "base_price": 200, "rarity": 1,
                   "description": "Encrypted portable storage. 1TB capacity."},
    "icebreaker_v2": {"name": "Icebreaker v2", "category": "tech", "base_price": 750, "rarity": 2,
                      "description": "Premium ICE-breaking software. Works on level-3 barriers."},

    # Consumables
    "stim_pack": {"name": "Stim Pack", "category": "consumables", "base_price": 50, "rarity": 1,
                  "description": "Quick-boost stimulant. +20% reaction speed for 1 hour."},
    "medkit": {"name": "Medkit", "category": "consumables", "base_price": 100, "rarity": 1,
               "description": "Standard trauma kit. Heals moderate injuries."},
    "synth_food": {"name": "Synth Food", "category": "consumables", "base_price": 15, "rarity": 1,
                   "description": "Nutritionally complete. Tastes like cardboard."},
    "neuro_stim": {"name": "Neuro Stim", "category": "consumables", "base_price": 200, "rarity": 2,
                   "description": "Brain chemistry enhancer. Temporary skill boost."},
    "trauma_patch": {"name": "Trauma Patch", "category": "consumables", "base_price": 150, "rarity": 2,
                     "description": "Emergency stabiliser. Prevents bleedout for 30 minutes."},

    # Contraband
    "synth_dust": {"name": "Synth Dust", "category": "contraband", "base_price": 300, "rarity": 2,
                   "description": "Illegal cognitive enhancer. Addictive.", "illegal": True},
    "forged_id": {"name": "Forged ID", "category": "contraband", "base_price": 500, "rarity": 3,
                  "description": "Fake identity papers. Passes basic scanners.", "illegal": True},
    "stolen_data": {"name": "Stolen Data Chip", "category": "contraband", "base_price": 400, "rarity": 2,
                    "description": "Corporate data extracted via hacking.", "illegal": True},
    "black_ice_chip": {"name": "Black ICE Chip", "category": "contraband", "base_price": 1000, "rarity": 4,
                       "description": "Military-grade counter-intrusion program.", "illegal": True},
    "weapon_mod": {"name": "Illegal Weapon Mod", "category": "contraband", "base_price": 350, "rarity": 2,
                   "description": "Unlicensed weapon modification kit.", "illegal": True},

    # Intel
    "faction_dossier": {"name": "Faction Dossier", "category": "intel", "base_price": 600, "rarity": 3,
                        "description": "Detailed intel on a faction's operations and leadership."},
    "access_codes": {"name": "Access Codes", "category": "intel", "base_price": 450, "rarity": 3,
                     "description": "One-time-use codes for a secure facility."},
    "street_rumor": {"name": "Street Rumor", "category": "intel", "base_price": 100, "rarity": 1,
                     "description": "Unverified gossip. May contain useful leads."},
    "blueprint": {"name": "Blueprint", "category": "intel", "base_price": 800, "rarity": 4,
                  "description": "Schematics for a prototype device or weapon."},

    # Luxury
    "designer_jacket": {"name": "Designer Jacket", "category": "luxury", "base_price": 400, "rarity": 2,
                        "description": "NeoTech fashion label. Boosts social standing."},
    "vintage_whiskey": {"name": "Vintage Whiskey", "category": "luxury", "base_price": 250, "rarity": 2,
                        "description": "Pre-collapse single malt. Impressive gift or bribe."},
    "holo_art": {"name": "Holo Art Piece", "category": "luxury", "base_price": 1000, "rarity": 4,
                 "description": "Collectible holographic art by a famous digital artist."},
    "synth_pet": {"name": "Synth Pet", "category": "luxury", "base_price": 350, "rarity": 2,
                  "description": "AI-powered companion animal. Low maintenance, high companionship."},
}

# ──── Shop Templates ────

DISTRICT_SHOPS: Dict[str, List[Dict[str, Any]]] = {
    "DOWNTOWN": [
        {"id": "neon_arms", "name": "Neon Arms", "categories": ["weapons", "tech"],
         "price_modifier": 1.1, "owner_npc": "dex"},
        {"id": "velvet_boutique", "name": "Velvet Boutique", "categories": ["luxury", "consumables"],
         "price_modifier": 1.2, "owner_npc": "mira"},
    ],
    "COMBAT_ZONE": [
        {"id": "iron_market", "name": "Iron Market", "categories": ["weapons", "consumables"],
         "price_modifier": 0.9, "owner_npc": "crusher"},
        {"id": "back_alley_deals", "name": "Back Alley Deals", "categories": ["contraband", "weapons"],
         "price_modifier": 0.85, "reputation_required": -50, "owner_npc": "shade"},
    ],
    "HIGHRISE": [
        {"id": "corp_store", "name": "Corp Store", "categories": ["tech", "luxury"],
         "price_modifier": 1.3, "owner_npc": "assistant_vi"},
        {"id": "skyline_pharmacy", "name": "Skyline Pharmacy", "categories": ["consumables"],
         "price_modifier": 1.15},
    ],
    "UNDERWORLD": [
        {"id": "shadow_bazaar", "name": "Shadow Bazaar", "categories": ["contraband", "intel", "weapons"],
         "price_modifier": 0.8, "reputation_required": -30, "owner_npc": "whisper"},
        {"id": "data_den", "name": "Data Den", "categories": ["intel", "tech"],
         "price_modifier": 0.95, "owner_npc": "zero"},
    ],
    "TECH_DISTRICT": [
        {"id": "tech_emporium", "name": "Tech Emporium", "categories": ["tech"],
         "price_modifier": 0.9, "owner_npc": "circuit"},
        {"id": "hacker_supply", "name": "Hacker Supply", "categories": ["tech", "intel"],
         "price_modifier": 1.0, "owner_npc": "ghost"},
    ],
    "OUTSKIRTS": [
        {"id": "scrapyard_shop", "name": "Scrapyard Shop", "categories": ["weapons", "tech", "consumables"],
         "price_modifier": 0.75},
        {"id": "wanderer_trade", "name": "Wanderer Trade Post", "categories": ["consumables", "contraband", "luxury"],
         "price_modifier": 0.85},
    ],
}

# Faction specialty goods — dominant faction in district nudges these
FACTION_SPECIALTIES: Dict[str, List[str]] = {
    "OmniCorp": ["tech", "luxury"],
    "NeoTech": ["tech", "weapons"],
    "BlackMarket": ["contraband", "intel"],
    "Ghost_Net": ["intel", "tech"],
    "SynthSec": ["weapons", "consumables"],
    "DeepState": ["intel", "contraband"],
}


# ──── Market Engine ────


class Market:
    """Dynamic market engine with supply/demand simulation.

    The market stores the global goods catalog, per-district shops, and
    a price history.  Calling :meth:`tick` advances the simulation one
    step — supply drifts toward equilibrium, demand responds to events,
    and territory-control multipliers are recomputed.
    """

    _SAVE_PATH: Path = Path("data/market_state.json")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._goods: Dict[str, Good] = {}
        self._shops: Dict[str, Shop] = {}
        self._history: List[TradeRecord] = []
        self._tick_count: int = 0
        self._territory_multipliers: Dict[str, Dict[str, float]] = {}
        self._load_or_seed()
        logger.info("Market initialized with %d goods, %d shops",
                     len(self._goods), len(self._shops))

    # ──── Bootstrap ────

    def _load_or_seed(self) -> None:
        """Load persisted state or seed from catalog."""
        if self._SAVE_PATH.exists():
            try:
                data = json.loads(self._SAVE_PATH.read_text(encoding="utf-8"))
                for gid, gdata in data.get("goods", {}).items():
                    cat = gdata.pop("current_price", None)  # strip computed field
                    self._goods[gid] = Good(**gdata)
                for sid, sdata in data.get("shops", {}).items():
                    self._shops[sid] = Shop(**sdata)
                self._tick_count = data.get("tick_count", 0)
                logger.debug("Market loaded from %s", self._SAVE_PATH)
                return
            except Exception as exc:
                logger.warning("Market load failed, reseeding: %s", exc)

        self._seed()

    def _seed(self) -> None:
        """Seed goods and shops from catalogs."""
        for gid, gdef in GOOD_CATALOG.items():
            self._goods[gid] = Good(id=gid, **gdef)

        for district, shops in DISTRICT_SHOPS.items():
            for sdef in shops:
                sid = sdef["id"]
                self._shops[sid] = Shop(district=district, **sdef)

    def _save(self) -> None:
        """Persist market state to disk."""
        try:
            self._SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "goods": {gid: g.to_dict() for gid, g in self._goods.items()},
                "shops": {sid: s.to_dict() for sid, s in self._shops.items()},
                "tick_count": self._tick_count,
            }
            self._SAVE_PATH.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Market save failed: %s", exc)

    # ──── Read API ────

    def get_goods(self, category: str = "") -> List[Dict[str, Any]]:
        """Return all goods, optionally filtered by category.

        Args:
            category: Filter to this category (empty = all).

        Returns:
            List of good dicts with current prices.
        """
        with self._lock:
            goods = self._goods.values()
            if category:
                goods = [g for g in goods if g.category == category]
            return [g.to_dict() for g in sorted(goods, key=lambda g: g.name)]

    def get_good(self, good_id: str) -> Optional[Dict[str, Any]]:
        """Return a single good by ID.

        Args:
            good_id: The good's identifier.

        Returns:
            Good dict or None.
        """
        with self._lock:
            g = self._goods.get(good_id)
            return g.to_dict() if g else None

    def get_shops(self, district: str = "") -> List[Dict[str, Any]]:
        """Return shops, optionally filtered by district.

        Args:
            district: Filter to this district (empty = all).

        Returns:
            List of shop dicts.
        """
        with self._lock:
            shops = self._shops.values()
            if district:
                shops = [s for s in shops if s.district == district]
            return [s.to_dict() for s in shops]

    def get_prices(self, district: str = "", category: str = "") -> List[Dict[str, Any]]:
        """Return prices of goods available in a district's shops.

        Args:
            district: District name (empty = global prices).
            category: Filter by good category (empty = all).

        Returns:
            List of dicts with good info, shop info, and adjusted prices.
        """
        with self._lock:
            results: List[Dict[str, Any]] = []
            shops = list(self._shops.values())
            if district:
                shops = [s for s in shops if s.district == district]

            for shop in shops:
                for gid, good in self._goods.items():
                    if good.category not in shop.categories:
                        continue
                    if category and good.category != category:
                        continue
                    adjusted = max(1, int(good.current_price * shop.price_modifier))
                    terr_mult = self._get_territory_modifier(shop.district, good.category)
                    final_price = max(1, int(adjusted * terr_mult))
                    results.append({
                        "good_id": gid,
                        "name": good.name,
                        "category": good.category,
                        "base_price": good.base_price,
                        "current_price": good.current_price,
                        "shop_price": final_price,
                        "shop_id": shop.id,
                        "shop_name": shop.name,
                        "district": shop.district,
                        "supply": round(good.supply, 1),
                        "demand": round(good.demand, 1),
                        "illegal": good.illegal,
                        "rarity": good.rarity,
                    })

            return sorted(results, key=lambda r: r["name"])

    def get_history(self, limit: int = 20, player_id: str = "") -> List[Dict[str, Any]]:
        """Return recent trade records.

        Args:
            limit: Maximum records to return.
            player_id: Filter by player (empty = all).

        Returns:
            List of trade record dicts (newest first).
        """
        with self._lock:
            records = self._history
            if player_id:
                records = [r for r in records if r.player_id == player_id]
            return [r.to_dict() for r in records[-limit:]][::-1]

    # ──── Trade API ────

    def buy(
        self,
        district: str,
        good_id: str,
        quantity: int = 1,
        player_id: str = "player1",
        shop_id: str = "",
    ) -> Dict[str, Any]:
        """Buy goods from a district shop.

        Args:
            district: District to buy in.
            good_id: Which good to purchase.
            quantity: How many to buy.
            player_id: Who is buying.
            shop_id: Specific shop (empty = cheapest available).

        Returns:
            Dict with status, total cost, and updated balance info.
        """
        with self._lock:
            good = self._goods.get(good_id)
            if not good:
                return {"status": "error", "reason": f"Unknown good: {good_id}"}

            shops = [s for s in self._shops.values() if s.district == district]
            if shop_id:
                shops = [s for s in shops if s.id == shop_id]

            eligible = [s for s in shops if good.category in s.categories]
            if not eligible:
                return {"status": "error", "reason": f"No shop in {district} sells {good_id}"}

            shop = min(eligible, key=lambda s: s.price_modifier)
            terr_mult = self._get_territory_modifier(district, good.category)
            unit_price = max(1, int(good.current_price * shop.price_modifier * terr_mult))
            total = unit_price * quantity

            # Demand increases on purchase
            good.demand = min(100.0, good.demand + quantity * 0.5)
            good.supply = max(0.0, good.supply - quantity * 0.3)

            record = TradeRecord(
                good_id=good_id,
                quantity=quantity,
                unit_price=unit_price,
                total=total,
                action="buy",
                district=district,
                player_id=player_id,
            )
            self._history.append(record)
            if len(self._history) > 500:
                self._history = self._history[-500:]

            self._save()

        self._emit("market_buy", {
            "good_id": good_id, "quantity": quantity,
            "total": total, "district": district,
        })

        return {
            "status": "ok",
            "action": "buy",
            "good_id": good_id,
            "good_name": good.name,
            "quantity": quantity,
            "unit_price": unit_price,
            "total": total,
            "shop": shop.name,
            "district": district,
            "illegal": good.illegal,
        }

    def sell(
        self,
        district: str,
        good_id: str,
        quantity: int = 1,
        player_id: str = "player1",
    ) -> Dict[str, Any]:
        """Sell goods to a district shop.

        Sell price is 60% of buy price.

        Args:
            district: District to sell in.
            good_id: Which good to sell.
            quantity: How many to sell.
            player_id: Who is selling.

        Returns:
            Dict with status, total proceeds.
        """
        with self._lock:
            good = self._goods.get(good_id)
            if not good:
                return {"status": "error", "reason": f"Unknown good: {good_id}"}

            shops = [s for s in self._shops.values()
                     if s.district == district and good.category in s.categories]
            if not shops:
                return {"status": "error", "reason": f"No buyer in {district} for {good_id}"}

            shop = max(shops, key=lambda s: s.price_modifier)
            terr_mult = self._get_territory_modifier(district, good.category)
            sell_rate = 0.6
            unit_price = max(1, int(good.current_price * shop.price_modifier * terr_mult * sell_rate))
            total = unit_price * quantity

            good.supply = min(100.0, good.supply + quantity * 0.3)
            good.demand = max(0.0, good.demand - quantity * 0.2)

            record = TradeRecord(
                good_id=good_id,
                quantity=quantity,
                unit_price=unit_price,
                total=total,
                action="sell",
                district=district,
                player_id=player_id,
            )
            self._history.append(record)
            if len(self._history) > 500:
                self._history = self._history[-500:]

            self._save()

        self._emit("market_sell", {
            "good_id": good_id, "quantity": quantity,
            "total": total, "district": district,
        })

        return {
            "status": "ok",
            "action": "sell",
            "good_id": good_id,
            "good_name": good.name,
            "quantity": quantity,
            "unit_price": unit_price,
            "total": total,
            "district": district,
        }

    # ──── Simulation ────

    def tick(self) -> Dict[str, Any]:
        """Advance the market one simulation step.

        Supply drifts toward equilibrium (50), demand decays slightly,
        random events perturb individual goods.

        Returns:
            Summary of price changes this tick.
        """
        with self._lock:
            self._tick_count += 1
            changes: List[Dict[str, Any]] = []

            for gid, good in self._goods.items():
                old_price = good.current_price

                # Supply drifts toward 50 (equilibrium)
                if good.supply < 50:
                    good.supply = min(100.0, good.supply + random.uniform(0.5, 2.0))
                elif good.supply > 50:
                    good.supply = max(0.0, good.supply - random.uniform(0.5, 2.0))

                # Demand decays toward 50
                if good.demand > 50:
                    good.demand = max(0.0, good.demand - random.uniform(0.3, 1.5))
                elif good.demand < 50:
                    good.demand = min(100.0, good.demand + random.uniform(0.3, 1.5))

                # Random perturbation (10% chance)
                if random.random() < 0.10:
                    shock = random.uniform(-8.0, 8.0)
                    good.supply = max(0.0, min(100.0, good.supply + shock))
                    good.demand = max(0.0, min(100.0, good.demand - shock * 0.5))

                new_price = good.current_price
                if old_price != new_price:
                    pct = ((new_price - old_price) / max(1, old_price)) * 100
                    changes.append({
                        "good_id": gid,
                        "name": good.name,
                        "old_price": old_price,
                        "new_price": new_price,
                        "change_pct": round(pct, 1),
                    })

            self._save()

        return {
            "tick": self._tick_count,
            "price_changes": len(changes),
            "notable_changes": [c for c in changes if abs(c["change_pct"]) > 5.0],
        }

    def apply_event(self, event_type: str, magnitude: float = 1.0) -> None:
        """Apply a world event's effect on supply/demand.

        Predefined event types cause shifts in specific categories:
        - ``war`` → weapons demand up, consumables demand up, luxury demand down
        - ``crackdown`` → contraband supply down, weapon supply down
        - ``festival`` → luxury demand up, consumables demand up
        - ``hack`` → tech demand up, intel demand up
        - ``shortage`` → consumables supply down
        - ``surplus`` → random category supply up
        - ``crash`` → all demand down

        Args:
            event_type: The kind of event.
            magnitude: Multiplier on effect size (default 1.0).
        """
        effects: Dict[str, List[Tuple[str, str, float]]] = {
            "war": [
                ("weapons", "demand", 15),
                ("consumables", "demand", 10),
                ("luxury", "demand", -10),
                ("contraband", "demand", 8),
            ],
            "crackdown": [
                ("contraband", "supply", -20),
                ("weapons", "supply", -10),
                ("intel", "demand", 10),
            ],
            "festival": [
                ("luxury", "demand", 15),
                ("consumables", "demand", 10),
                ("weapons", "demand", -5),
            ],
            "hack": [
                ("tech", "demand", 15),
                ("intel", "demand", 12),
                ("contraband", "demand", 5),
            ],
            "shortage": [
                ("consumables", "supply", -20),
                ("consumables", "demand", 10),
            ],
            "surplus": [
                ("consumables", "supply", 15),
                ("tech", "supply", 10),
            ],
            "crash": [
                ("weapons", "demand", -10),
                ("tech", "demand", -10),
                ("luxury", "demand", -15),
                ("consumables", "demand", -5),
            ],
        }

        event_effects = effects.get(event_type)
        if not event_effects:
            return

        with self._lock:
            for cat, attr, delta in event_effects:
                scaled = delta * magnitude
                for g in self._goods.values():
                    if g.category == cat:
                        if attr == "supply":
                            g.supply = max(0.0, min(100.0, g.supply + scaled))
                        else:
                            g.demand = max(0.0, min(100.0, g.demand + scaled))
            self._save()

    def update_territory_multipliers(
        self, district_control: Dict[str, Dict[str, float]]
    ) -> None:
        """Update price multipliers based on territory control.

        The dominant faction in each district makes their specialty goods
        cheaper (better supply chains) and rival specialties more expensive.

        Args:
            district_control: {district: {faction: control_pct}}.
        """
        with self._lock:
            self._territory_multipliers.clear()
            for district, factions in district_control.items():
                if not factions:
                    continue
                dominant = max(factions, key=factions.get)
                control_pct = factions[dominant]
                specialties = FACTION_SPECIALTIES.get(dominant, [])

                mults: Dict[str, float] = {}
                for cat in GoodCategory:
                    if cat.value in specialties and control_pct > 30:
                        # Dominant faction reduces prices for their goods
                        mults[cat.value] = max(0.7, 1.0 - (control_pct - 30) * 0.005)
                    elif cat.value not in specialties and control_pct > 50:
                        # Non-specialty goods get slightly more expensive
                        mults[cat.value] = min(1.3, 1.0 + (control_pct - 50) * 0.003)
                    else:
                        mults[cat.value] = 1.0
                self._territory_multipliers[district] = mults

    def _get_territory_modifier(self, district: str, category: str) -> float:
        """Return territory price modifier for category in district."""
        mults = self._territory_multipliers.get(district, {})
        return mults.get(category, 1.0)

    # ──── Stats ────

    def get_stats(self) -> Dict[str, Any]:
        """Return market statistics.

        Returns:
            Summary dict with counts, averages, and trade volume.
        """
        with self._lock:
            total_volume = sum(r.total for r in self._history)
            buys = sum(1 for r in self._history if r.action == "buy")
            sells = sum(1 for r in self._history if r.action == "sell")
            avg_price = (
                sum(g.current_price for g in self._goods.values()) / len(self._goods)
                if self._goods else 0
            )
            return {
                "total_goods": len(self._goods),
                "total_shops": len(self._shops),
                "tick_count": self._tick_count,
                "trade_volume": total_volume,
                "total_buys": buys,
                "total_sells": sells,
                "avg_good_price": round(avg_price, 0),
                "categories": list(set(g.category for g in self._goods.values())),
            }

    # ──── Reset ────

    def reset(self) -> None:
        """Reset market to initial state."""
        with self._lock:
            self._goods.clear()
            self._shops.clear()
            self._history.clear()
            self._tick_count = 0
            self._territory_multipliers.clear()
            self._seed()

    # ──── Events ────

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish market event on EventBus."""
        if not _HAS_BUS:
            return
        try:
            bus = _get_event_bus()
            if bus:
                bus.publish(event_type, data)
        except Exception as exc:
            logger.debug("Market event emit failed: %s", exc)


# ──── Singleton ────

_instance: Optional[Market] = None
_instance_lock = threading.Lock()


def get_market() -> Market:
    """Return the singleton Market instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Market()
    return _instance


def reset_market() -> None:
    """Reset the singleton for testing."""
    global _instance
    _instance = None
