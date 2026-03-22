"""THE GRID — CosySim v0.75 "NEON CITY".
==========================================

The underground marketplace, travel hub, faction den, and information broker
of Neon City.  Port 5569.

Four zones accessible via tab navigation:

- **MARKET** — buy/sell items with fluctuating prices tied to economy events
- **STATION** — SVG travel map showing all live scene locations
- **DEN** — faction headquarters, allegiance pledging, faction quests
- **BROKER** — Nexus-powered intel trading and 0xGH0ST terminal

All zones react to the living world via Socket.IO and the EventCascade.

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — 18 tiered faction quests (3 per faction), 3 vendor NPCs with dialogue
    v1.51.0 [2026-03-22] — Migrated to FlaskScene base class
    v1.49.2 [2026-03-22] — API-first: template is a pure structural shell
    v0.75   [2026-03-21] — Initial THE GRID scene
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import Response, json, request

from engine.scenes.flask_scene import FlaskScene
from engine.skills.skill import skill

logger = logging.getLogger(__name__)

SCENE_ID = "grid"
# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)

# ──── Catalogue ──────────────────────────────────────────────────────────────

MARKET_CATALOGUE: List[Dict[str, Any]] = [
    # Tech (Mira)
    {"id": "stim_v1",    "name": "Stim-Pack v1",      "vendor": "mira",   "category": "tech",        "base_price": 120,  "stock": 10, "rarity": "common"},
    {"id": "data_chip",  "name": "Data Chip",          "vendor": "mira",   "category": "tech",        "base_price": 250,  "stock": 5,  "rarity": "uncommon"},
    {"id": "jammer",     "name": "Signal Jammer",      "vendor": "mira",   "category": "tech",        "base_price": 600,  "stock": 2,  "rarity": "rare"},
    {"id": "neural_tap", "name": "Neural Tap",         "vendor": "mira",   "category": "tech",        "base_price": 1200, "stock": 1,  "rarity": "legendary"},
    {"id": "dec_key",    "name": "Decrypt Key",        "vendor": "mira",   "category": "tech",        "base_price": 350,  "stock": 3,  "rarity": "uncommon"},
    # Contraband (Viktor)
    {"id": "ghost_id",   "name": "Ghost ID",           "vendor": "viktor", "category": "contraband",  "base_price": 800,  "stock": 4,  "rarity": "rare"},
    {"id": "exp_round",  "name": "Explosive Rounds",   "vendor": "viktor", "category": "contraband",  "base_price": 450,  "stock": 6,  "rarity": "uncommon"},
    {"id": "holo_mask",  "name": "Holo Mask",          "vendor": "viktor", "category": "contraband",  "base_price": 1100, "stock": 2,  "rarity": "rare"},
    {"id": "corp_key",   "name": "Corp Access Card",   "vendor": "viktor", "category": "contraband",  "base_price": 2000, "stock": 1,  "rarity": "legendary"},
    {"id": "wire_tap",   "name": "Wire-Tap Device",    "vendor": "viktor", "category": "contraband",  "base_price": 320,  "stock": 5,  "rarity": "uncommon"},
    # Meds/Stims (Frankie)
    {"id": "nano_heal",  "name": "Nano-Healer",        "vendor": "frankie","category": "meds",        "base_price": 180,  "stock": 8,  "rarity": "common"},
    {"id": "rush_dose",  "name": "Rush Dose",          "vendor": "frankie","category": "meds",        "base_price": 80,   "stock": 15, "rarity": "common"},
    {"id": "trauma_kit", "name": "Trauma Kit",         "vendor": "frankie","category": "meds",        "base_price": 450,  "stock": 3,  "rarity": "uncommon"},
    {"id": "synth_calm", "name": "Synth-Calm",         "vendor": "frankie","category": "meds",        "base_price": 200,  "stock": 6,  "rarity": "common"},
    {"id": "blackout_p", "name": "Blackout Patch",     "vendor": "frankie","category": "meds",        "base_price": 550,  "stock": 2,  "rarity": "rare"},
    # Information
    {"id": "tip_bunker", "name": "Bunker Location Tip","vendor": "broker", "category": "intel",       "base_price": 750,  "stock": 3,  "rarity": "rare"},
    {"id": "tip_route",  "name": "Safe Route Map",     "vendor": "broker", "category": "intel",       "base_price": 300,  "stock": 5,  "rarity": "uncommon"},
]

FACTION_DATA: List[Dict[str, Any]] = [
    {"id": "OmniCorp",    "label": "OmniCorp",    "accent": "#3b82f6",  "archetype": "megacorp"},
    {"id": "NeoTech",     "label": "NeoTech",     "accent": "#8b5cf6",  "archetype": "corp"},
    {"id": "BlackMarket", "label": "BlackMarket", "accent": "#ef4444",  "archetype": "syndicate"},
    {"id": "Ghost_Net",   "label": "Ghost Net",   "accent": "#06b6d4",  "archetype": "hacker"},
    {"id": "SynthSec",    "label": "SynthSec",    "accent": "#f59e0b",  "archetype": "security"},
    {"id": "DeepState",   "label": "DeepState",   "accent": "#a3a3a3",  "archetype": "shadow"},
]

# v1.49.5 [2026-03-22] — Expanded faction quest chain system (18 quests, 3 per faction)
# Each faction has a 3-tier quest chain: tier 1 (intro) -> tier 2 (escalation) -> tier 3 (climax).
# Higher tiers require completing the previous tier. Rival faction rep costs increase with tier.
# CONNECTS: _GridState.accept_quest, _GridState.complete_quest, PlayerState
# CALLED BY: /api/faction/quest/accept, /api/faction/quest/complete
FACTION_QUESTS: List[Dict[str, Any]] = [
    # ── OmniCorp — Corporate warfare ─────────────────────────────────────
    {
        "id": "omni_t1", "faction": "OmniCorp", "tier": 1,
        "title": "Data Retrieval",
        "desc": "Steal competitive analysis files from NeoTech's cloud backup. The data is stored on an unsecured mirror — get in, grab it, get out.",
        "objective": "Deliver data chip to OmniCorp handler.",
        "reward_credits": 500, "reward_rep": 15,
        "rival_rep_cost": {"NeoTech": -8},
    },
    {
        "id": "omni_t2", "faction": "OmniCorp", "tier": 2, "requires": "omni_t1",
        "title": "Corporate Espionage",
        "desc": "Infiltrate NeoTech R&D and copy their neural interface prototype specs. Security is tighter this time — they know someone's watching.",
        "objective": "Upload specs to OmniCorp secure server.",
        "reward_credits": 1500, "reward_rep": 25,
        "rival_rep_cost": {"NeoTech": -15, "SynthSec": -5},
    },
    {
        "id": "omni_t3", "faction": "OmniCorp", "tier": 3, "requires": "omni_t2",
        "title": "Hostile Takeover",
        "desc": "Plant evidence of fraud on NeoTech's CEO. One corporation falls, another rises. This changes the power balance in Neon City forever.",
        "objective": "Deliver evidence package to media contact.",
        "reward_credits": 5000, "reward_rep": 40,
        "rival_rep_cost": {"NeoTech": -30, "BlackMarket": -10},
    },
    # ── NeoTech — Tech sabotage ──────────────────────────────────────────
    {
        "id": "neo_t1", "faction": "NeoTech", "tier": 1,
        "title": "Virus Payload",
        "desc": "Deploy a surveillance virus into OmniCorp's internal network via a compromised vendor terminal. Subtle. Deniable.",
        "objective": "Install the payload on 3 vendor terminals in the Grid.",
        "reward_credits": 600, "reward_rep": 15,
        "rival_rep_cost": {"OmniCorp": -8},
    },
    {
        "id": "neo_t2", "faction": "NeoTech", "tier": 2, "requires": "neo_t1",
        "title": "Prototype Theft",
        "desc": "OmniCorp has a working quantum decryption chip in their R&D vault. NeoTech wants it. Break in, steal it, leave no trace.",
        "objective": "Extract the prototype chip and deliver it to NeoTech labs.",
        "reward_credits": 1800, "reward_rep": 25,
        "rival_rep_cost": {"OmniCorp": -15, "Ghost_Net": -5},
    },
    {
        "id": "neo_t3", "faction": "NeoTech", "tier": 3, "requires": "neo_t2",
        "title": "AI Weaponization",
        "desc": "NeoTech wants to weaponize an experimental AI core for autonomous defense drones. You must retrieve the AI kernel from a decommissioned military server farm. The ethical cost is yours to bear.",
        "objective": "Upload the AI kernel to NeoTech's secure forge server.",
        "reward_credits": 6000, "reward_rep": 40,
        "rival_rep_cost": {"OmniCorp": -20, "Ghost_Net": -15, "SynthSec": -10},
    },
    # ── BlackMarket — Criminal ops ───────────────────────────────────────
    {
        "id": "bm_t1", "faction": "BlackMarket", "tier": 1,
        "title": "Smuggler's Run",
        "desc": "A shipment of unregistered stim-packs needs to cross three SynthSec checkpoints. Drive the van, avoid the scans, deliver the goods.",
        "objective": "Deliver the shipment to the BlackMarket warehouse.",
        "reward_credits": 400, "reward_rep": 12,
        "heat_cost": 8,
        "rival_rep_cost": {"SynthSec": -10},
    },
    {
        "id": "bm_t2", "faction": "BlackMarket", "tier": 2, "requires": "bm_t1",
        "title": "The Vault Job",
        "desc": "A private collector has a vault full of pre-Collapse tech. The BlackMarket wants it all. Plan the heist, crack the vault, split the haul.",
        "objective": "Crack the vault and deliver the tech haul to the fence.",
        "reward_credits": 2500, "reward_rep": 25,
        "heat_cost": 15,
        "rival_rep_cost": {"SynthSec": -15, "OmniCorp": -5},
    },
    {
        "id": "bm_t3", "faction": "BlackMarket", "tier": 3, "requires": "bm_t2",
        "title": "Territory Grab",
        "desc": "The BlackMarket is making a power play — seize the docks from SynthSec-aligned gangs. Bribe, intimidate, or eliminate the opposition. After tonight, the docks belong to the Market.",
        "objective": "Secure all 3 dock zones and report to the BlackMarket boss.",
        "reward_credits": 7000, "reward_rep": 40,
        "heat_cost": 25,
        "rival_rep_cost": {"SynthSec": -30, "DeepState": -10},
    },
    # ── Ghost_Net — Information warfare ──────────────────────────────────
    {
        "id": "gn_t1", "faction": "Ghost_Net", "tier": 1,
        "title": "Expose the Lie",
        "desc": "OmniCorp is running a secret medical trial on unknowing Grid residents. Ghost_Net has partial evidence — find the rest and leak it to the public feeds.",
        "objective": "Collect 3 evidence nodes and upload to the Ghost_Net relay.",
        "reward_credits": 450, "reward_rep": 15,
        "rival_rep_cost": {"OmniCorp": -10},
    },
    {
        "id": "gn_t2", "faction": "Ghost_Net", "tier": 2, "requires": "gn_t1",
        "title": "Database Raid",
        "desc": "SynthSec keeps a blacklist of unregistered citizens — people who vanish into labor camps. Hack their central database, copy the list, and broadcast it.",
        "objective": "Exfiltrate the blacklist and transmit via Ghost_Net broadcast.",
        "reward_credits": 1600, "reward_rep": 25,
        "rival_rep_cost": {"SynthSec": -15, "DeepState": -8},
    },
    {
        "id": "gn_t3", "faction": "Ghost_Net", "tier": 3, "requires": "gn_t2",
        "title": "The Great Leak",
        "desc": "Ghost_Net's masterplan: simultaneously leak financial records from all major factions, exposing corruption across Neon City. Every corp, every agency, every syndicate — laid bare. The city will never be the same.",
        "objective": "Deploy leak payloads to 6 faction servers simultaneously.",
        "reward_credits": 5500, "reward_rep": 40,
        "rival_rep_cost": {"OmniCorp": -15, "NeoTech": -15, "DeepState": -20},
    },
    # ── SynthSec — Enforcement ───────────────────────────────────────────
    {
        "id": "ss_t1", "faction": "SynthSec", "tier": 1,
        "title": "Bounty Hunt",
        "desc": "A wanted hacker known as 'Pixel' is operating out of the Grid's lower levels. SynthSec wants them tagged and tracked — alive, for now.",
        "objective": "Locate Pixel and attach a SynthSec tracker beacon.",
        "reward_credits": 550, "reward_rep": 15,
        "heat_cost": 5,
        "rival_rep_cost": {"Ghost_Net": -8, "BlackMarket": -5},
    },
    {
        "id": "ss_t2", "faction": "SynthSec", "tier": 2, "requires": "ss_t1",
        "title": "Evidence Planting",
        "desc": "SynthSec needs a BlackMarket boss taken down but lacks probable cause. Plant fabricated evidence in their warehouse and tip off a raid. Justice is flexible in Neon City.",
        "objective": "Plant 3 evidence packages and trigger the anonymous tip.",
        "reward_credits": 2000, "reward_rep": 25,
        "heat_cost": 10,
        "rival_rep_cost": {"BlackMarket": -20, "Ghost_Net": -5},
    },
    {
        "id": "ss_t3", "faction": "SynthSec", "tier": 3, "requires": "ss_t2",
        "title": "Protection Racket",
        "desc": "SynthSec is establishing a 'security fee' for all Grid merchants — pay or lose your stall. Enforce the new policy by visiting every vendor. Some will resist. Handle them.",
        "objective": "Collect compliance from all 6 Grid merchant zones.",
        "reward_credits": 6500, "reward_rep": 40,
        "heat_cost": 20,
        "rival_rep_cost": {"BlackMarket": -25, "Ghost_Net": -15},
    },
    # ── DeepState — Conspiracy ───────────────────────────────────────────
    {
        "id": "ds_t1", "faction": "DeepState", "tier": 1,
        "title": "Surveillance Tap",
        "desc": "Install hidden listening devices in three key locations: the Grid's comm relay, OmniCorp's lobby, and a Ghost_Net safe house. No one can know.",
        "objective": "Install all 3 surveillance devices without detection.",
        "reward_credits": 700, "reward_rep": 12,
        "rival_rep_cost": {"Ghost_Net": -5},
    },
    {
        "id": "ds_t2", "faction": "DeepState", "tier": 2, "requires": "ds_t1",
        "title": "Blackmail Material",
        "desc": "A prominent NeoTech executive has a secret — DeepState wants leverage. Photograph the meeting, record the conversation, acquire the documents. Discretion is everything.",
        "objective": "Deliver the blackmail dossier to the DeepState handler.",
        "reward_credits": 2200, "reward_rep": 25,
        "rival_rep_cost": {"NeoTech": -12, "OmniCorp": -5},
    },
    {
        "id": "ds_t3", "faction": "DeepState", "tier": 3, "requires": "ds_t2",
        "title": "Political Manipulation",
        "desc": "Neon City's council vote is tomorrow. DeepState needs three council members to vote a specific way. Use the blackmail, the surveillance, and whatever else it takes. Democracy is a tool — use it.",
        "objective": "Ensure 3 council votes align with DeepState's directive.",
        "reward_credits": 8000, "reward_rep": 40,
        "rival_rep_cost": {"Ghost_Net": -20, "NeoTech": -10, "OmniCorp": -10},
    },
]

# v1.49.5 [2026-03-22] — Vendor NPCs with dialogue triggers and faction-aware reactions
# CONNECTS: MARKET_CATALOGUE vendors, PlayerState faction standings
# CALLED BY: /api/vendor/dialogue, front-end vendor interaction
# EMITS: vendor_dialogue Socket.IO event
VENDOR_NPCS: Dict[str, Dict[str, Any]] = {
    "mira": {
        "name": "Mira",
        "role": "Tech Dealer",
        "location": "Market Zone — East Wing",
        "personality": "Sharp-tongued ex-engineer. Distrusts corps but loves their tech.",
        "backstory": (
            "Mira ran R&D for NeoTech until they buried her whistleblower report "
            "about defective neural implants. Now she sells the same tech on the "
            "Grid — but she tests everything herself first. She has a soft spot "
            "for Ghost_Net operatives and overcharges OmniCorp loyalists."
        ),
        "faction_reactions": {
            "Ghost_Net": {"min_standing": 60, "discount": 0.15, "greeting": "Ghost_Net, huh? You're one of the good ones. Take a look — special stock for friends."},
            "OmniCorp": {"min_standing": 60, "price_hike": 0.20, "greeting": "OmniCorp credits spend the same, I guess. Don't expect any favors though."},
            "NeoTech": {"min_standing": 40, "greeting": "NeoTech... I used to wear that badge. Don't remind me. What do you need?"},
        },
        "purchase_triggers": {
            0: "First time? Browse carefully. Everything here actually works — unlike the trash upstairs.",
            3: "Back again? You're becoming a regular. I might have something special in the back...",
            10: "Ten purchases. You've earned my trust. Ask about the Neural Tap — I keep it off the shelf for serious buyers.",
        },
        "default_greeting": "Welcome to the workshop. Touch it, you buy it. Break it, you buy two.",
    },
    "viktor": {
        "name": "Viktor",
        "role": "Contraband Specialist",
        "location": "Market Zone — Shadow Alley",
        "personality": "Paranoid, professional, speaks in coded language.",
        "backstory": (
            "Viktor was SynthSec internal affairs before he realized the agency "
            "was dirtier than the criminals. He flipped, took his contacts list, "
            "and set up shop in the Grid's deepest corner. He sells what SynthSec "
            "confiscates — Ghost IDs, Corp Access Cards, weapons-grade tech. "
            "He never forgets a face and never forgives a snitch."
        ),
        "faction_reactions": {
            "SynthSec": {"min_standing": 60, "price_hike": 0.30, "greeting": "SynthSec badge? You've got nerve showing that here. Prices just doubled. For you."},
            "BlackMarket": {"min_standing": 60, "discount": 0.10, "greeting": "Market family gets Market prices. What are you looking for, friend?"},
            "DeepState": {"min_standing": 50, "discount": 0.05, "greeting": "DeepState... I don't ask questions. You don't ask questions. We understand each other."},
        },
        "purchase_triggers": {
            0: "New face. Cash up front, no refunds, no names. We clear?",
            5: "You keep coming back. Good. I'll start keeping the real inventory out for you.",
            15: "Fifteen deals, zero problems. You want Corp Access Cards? I might know a guy.",
        },
        "default_greeting": "Eyes forward. Don't look at the other customers. What do you need?",
    },
    "frankie": {
        "name": "Frankie",
        "role": "Med-Tech Dealer",
        "location": "Market Zone — The Clinic",
        "personality": "Warm, motherly, secretly ruthless about debts.",
        "backstory": (
            "Frankie ran an unlicensed clinic in the lower Grid for fifteen "
            "years, patching up anyone who stumbled in — no questions, no "
            "credits required. Then SynthSec shut her down. Now she sells "
            "meds and stims from a market stall, but she still treats anyone "
            "who's bleeding for free. Cross her on payment, though, and "
            "you'll find out why they call her 'Frankie the Fixer.'"
        ),
        "faction_reactions": {
            "SynthSec": {"min_standing": 60, "price_hike": 0.15, "greeting": "SynthSec. You shut my clinic down. I'll still sell to you — everyone deserves medicine. But you're paying full price. Plus interest."},
            "BlackMarket": {"min_standing": 50, "discount": 0.10, "greeting": "Market crew! How's the family? Sit down, let me check your vitals while you shop."},
            "Ghost_Net": {"min_standing": 50, "discount": 0.05, "greeting": "Ghost_Net keeps the truth flowing. That's medicine for the soul. Here — first Nano-Healer is on the house."},
        },
        "purchase_triggers": {
            0: "Welcome, sweetie. Everyone needs a little help sometimes. No judgment here.",
            5: "You're taking care of yourself — good. I worry about the regulars. Here, try this new batch.",
            20: "Twenty visits! You're practically family. I've got a private stock of Blackout Patches — interested?",
        },
        "default_greeting": "Come in, come in. You look like you could use a Nano-Healer. Or at least a cup of something warm.",
    },
}

# Scene map for THE STATION — all known scene ports
CITY_MAP_NODES: List[Dict[str, Any]] = [
    {"key": "bedroom",  "label": "THE PENTHOUSE",   "port": 5556, "x": 72, "y": 15,  "accent": "#c084fc"},
    {"key": "phone",    "label": "SIGNAL",          "port": 5555, "x": 18, "y": 15,  "accent": "#00e5ff"},
    {"key": "lounge",   "label": "VELVET PIT",      "port": 5557, "x": 50, "y": 30,  "accent": "#f43f5e"},
    {"key": "tavern",   "label": "RUSTY ANCHOR",    "port": 5558, "x": 25, "y": 45,  "accent": "#f97316"},
    {"key": "casino",   "label": "CLUB NOIR",       "port": 5559, "x": 70, "y": 45,  "accent": "#eab308"},
    {"key": "gallery",  "label": "THE OBSCURA",     "port": 5560, "x": 12, "y": 60,  "accent": "#a78bfa"},
    {"key": "arena",    "label": "COLOSSEUM",       "port": 5561, "x": 85, "y": 60,  "accent": "#22c55e"},
    {"key": "realm",    "label": "SHATTERED THRONE","port": 5562, "x": 40, "y": 72,  "accent": "#e879f9"},
    {"key": "neoncity", "label": "NEON CITY",       "port": 5563, "x": 55, "y": 55,  "accent": "#00e5ff"},
    {"key": "coders",   "label": "THE LAB",         "port": 5564, "x": 30, "y": 82,  "accent": "#34d399"},
    {"key": "heist",    "label": "THE SCORE",       "port": 5565, "x": 65, "y": 80,  "accent": "#e11d48"},
    {"key": "games",    "label": "THE ARCADE",      "port": 5567, "x": 45, "y": 88,  "accent": "#fb7185"},
    {"key": "grid",     "label": "THE GRID",        "port": 5569, "x": 50, "y": 50,  "accent": "#00ff88", "is_current": True},
    {"key": "intel",    "label": "THE BRIEFING",    "port": 5580, "x": 80, "y": 25,  "accent": "#38bdf8"},
    {"key": "hub",      "label": "THE LOFT",        "port": 8500, "x": 50, "y": 5,   "accent": "#94a3b8"},
]


# ──── GridState singleton ─────────────────────────────────────────────────────

class _GridState:
    """Runtime state for THE GRID scene — market prices, inventory, quests."""

    def __init__(self) -> None:
        self._prices: Dict[str, float] = {item["id"]: float(item["base_price"]) for item in MARKET_CATALOGUE}
        self._stock: Dict[str, int] = {item["id"]: item["stock"] for item in MARKET_CATALOGUE}
        self._player_inventory: List[Dict[str, Any]] = []
        self._active_quest: Optional[str] = None  # faction id with active quest
        self._quest_complete: Dict[str, bool] = {}  # quest ID -> completed
        self._intel_feed: List[Dict[str, Any]] = []
        self._price_trend: Dict[str, str] = {item["id"]: "stable" for item in MARKET_CATALOGUE}
        # v1.49.5 — Track cumulative purchases per vendor for dialogue triggers
        self._vendor_purchase_count: Dict[str, int] = {}

    # ── Market ────────────────────────────────────────────────────────────────

    def get_market_items(self) -> List[Dict[str, Any]]:
        """Return current market catalogue with live prices."""
        items = []
        for item in MARKET_CATALOGUE:
            iid = item["id"]
            items.append({
                **item,
                "price": int(self._prices[iid]),
                "stock": self._stock[iid],
                "trend": self._price_trend[iid],
            })
        return items

    def buy_item(self, item_id: str, quantity: int = 1) -> Dict[str, Any]:
        """Process a purchase. Returns result dict."""
        item = next((i for i in MARKET_CATALOGUE if i["id"] == item_id), None)
        if not item:
            return {"success": False, "error": "Item not found."}
        price = int(self._prices[item_id])
        total = price * quantity
        stock = self._stock[item_id]
        if stock < quantity:
            return {"success": False, "error": f"Insufficient stock ({stock} available)."}
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            if ps.credits < total:
                return {"success": False, "error": f"Insufficient credits (need ₵{total:,})."}
            ps.spend_credits(total, f"grid_buy:{item_id}")
        except Exception:
            pass  # PlayerState optional
        self._stock[item_id] = max(0, stock - quantity)
        self._player_inventory.append({"item_id": item_id, "name": item["name"], "qty": quantity, "paid": total})
        # v1.49.5 — Track vendor purchase count for dialogue triggers
        vendor_id = item.get("vendor", "unknown")
        self._vendor_purchase_count[vendor_id] = self._vendor_purchase_count.get(vendor_id, 0) + quantity
        return {"success": True, "item": item["name"], "quantity": quantity, "paid": total, "remaining_stock": self._stock[item_id]}

    def sell_item(self, item_id: str, quantity: int = 1) -> Dict[str, Any]:
        """Process a sale of player inventory."""
        owned = sum(e["qty"] for e in self._player_inventory if e["item_id"] == item_id)
        if owned < quantity:
            return {"success": False, "error": f"You only own {owned} of that item."}
        item = next((i for i in MARKET_CATALOGUE if i["id"] == item_id), None)
        if not item:
            return {"success": False, "error": "Item not found."}
        sell_price = int(self._prices[item_id] * 0.65)  # 65 % sell-back rate
        total = sell_price * quantity
        try:
            from engine.world.player_state import get_player_state
            get_player_state().earn_credits(total, f"grid_sell:{item_id}")
        except Exception:
            pass
        # Remove from inventory
        remaining = quantity
        new_inv = []
        for e in self._player_inventory:
            if e["item_id"] == item_id and remaining > 0:
                taken = min(e["qty"], remaining)
                remaining -= taken
                if e["qty"] - taken > 0:
                    new_inv.append({**e, "qty": e["qty"] - taken})
            else:
                new_inv.append(e)
        self._player_inventory = new_inv
        self._stock[item_id] = min(self._stock[item_id] + quantity, item["stock"])
        return {"success": True, "item": item["name"], "quantity": quantity, "earned": total}

    def economy_shock(self, event_type: str, economy_impact: int) -> List[Dict[str, Any]]:
        """Apply an economy event to market prices.  Returns list of changed items."""
        changed = []
        for item in MARKET_CATALOGUE:
            iid = item["id"]
            base = float(item["base_price"])
            factor = 1.0
            if event_type in ("market_crash", "corp_tax", "blackout"):
                factor = random.uniform(0.75, 0.95)  # prices drop
                self._price_trend[iid] = "falling"
            elif event_type in ("black_market_sale", "corp_raid"):
                factor = random.uniform(1.05, 1.30)  # prices spike
                self._price_trend[iid] = "rising"
            elif event_type == "festival":
                if item["category"] in ("meds", "tech"):
                    factor = random.uniform(0.85, 0.95)
                    self._price_trend[iid] = "falling"
            else:
                factor = random.uniform(0.95, 1.05)
                self._price_trend[iid] = "stable"
            new_price = max(1, int(base * factor))
            if new_price != int(self._prices[iid]):
                self._prices[iid] = float(new_price)
                changed.append({"id": iid, "price": new_price, "trend": self._price_trend[iid]})
        return changed

    # ── Faction ───────────────────────────────────────────────────────────────

    def pledge_allegiance(self, faction_id: str) -> Dict[str, Any]:
        """Pledge allegiance to a faction."""
        faction = next((f for f in FACTION_DATA if f["id"] == faction_id), None)
        if not faction:
            return {"success": False, "error": "Unknown faction."}
        rivals = {
            "OmniCorp": ["BlackMarket", "Ghost_Net"],
            "BlackMarket": ["OmniCorp", "SynthSec"],
            "Ghost_Net": ["OmniCorp", "DeepState"],
            "SynthSec": ["BlackMarket"],
            "NeoTech": ["Ghost_Net"],
            "DeepState": [],
        }
        rep_gain = 15
        rival_loss = 8
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            ps.update_faction_standing(faction_id, rep_gain)
            for rival in rivals.get(faction_id, []):
                ps.update_faction_standing(rival, -rival_loss)
        except Exception:
            pass
        return {
            "success": True,
            "faction": faction_id,
            "rep_gained": rep_gain,
            "rivals_lost": rival_loss,
            "message": f"Allegiance pledged to {faction['label']}. Rivals grow hostile.",
        }

    # v1.49.5 [2026-03-22] — Tiered quest chain system (3 tiers per faction)
    # CONNECTS: FACTION_QUESTS, PlayerState, rival_rep_cost
    # CALLED BY: /api/faction/quest/accept, /api/faction/quest/complete
    def _get_next_quest(self, faction_id: str) -> Optional[Dict[str, Any]]:
        """Find the next available quest for a faction in the tier chain.

        Walks the quest chain for the given faction and returns the first
        quest whose prerequisites are met (i.e., the 'requires' quest ID
        has been completed). Returns None if all quests are done.

        Args:
            faction_id: The faction ID to look up quests for.

        Returns:
            The next available quest dict, or None if the chain is complete.
        """
        faction_quests = [q for q in FACTION_QUESTS if q["faction"] == faction_id]
        # Sort by tier to ensure we process in order
        faction_quests.sort(key=lambda q: q.get("tier", 1))

        for quest in faction_quests:
            qid = quest.get("id", quest.get("title", ""))
            # Already completed? Skip to next tier
            if self._quest_complete.get(qid):
                continue
            # Check prerequisite
            requires = quest.get("requires")
            if requires and not self._quest_complete.get(requires):
                # Prerequisite not met — can't access this or higher tiers
                return None
            return quest
        return None  # All quests in chain completed

    def get_faction_quest_status(self, faction_id: str) -> Dict[str, Any]:
        """Get the full quest chain status for a faction.

        Returns:
            Dict with completed quests, next available quest, and chain progress.
        """
        faction_quests = [q for q in FACTION_QUESTS if q["faction"] == faction_id]
        faction_quests.sort(key=lambda q: q.get("tier", 1))
        completed = []
        for q in faction_quests:
            qid = q.get("id", q.get("title", ""))
            if self._quest_complete.get(qid):
                completed.append(qid)
        next_quest = self._get_next_quest(faction_id)
        return {
            "faction": faction_id,
            "total_quests": len(faction_quests),
            "completed": completed,
            "completed_count": len(completed),
            "next_quest": next_quest,
            "chain_complete": len(completed) == len(faction_quests),
        }

    def accept_quest(self, faction_id: str) -> Dict[str, Any]:
        """Accept the next available faction quest in the tier chain.

        The quest chain is tier-gated: tier 2 requires tier 1 completion, etc.
        Only one quest can be active at a time (across all factions).
        """
        if self._active_quest:
            return {"success": False, "error": f"Already have an active quest (faction: {self._active_quest})."}

        quest = self._get_next_quest(faction_id)
        if not quest:
            # Check if all quests are completed
            faction_quests = [q for q in FACTION_QUESTS if q["faction"] == faction_id]
            all_done = all(
                self._quest_complete.get(q.get("id", q.get("title", "")))
                for q in faction_quests
            )
            if all_done:
                return {"success": False, "error": f"All {faction_id} quests completed. Chain finished."}
            return {"success": False, "error": "No quest available — prerequisite not met."}

        self._active_quest = faction_id
        return {"success": True, "quest": quest}

    def complete_quest(self, faction_id: str) -> Dict[str, Any]:
        """Mark the current active faction quest as complete and award rewards.

        Applies credits, reputation gain, heat cost, and rival faction rep
        penalties from the quest's rival_rep_cost dict.
        """
        if faction_id != self._active_quest:
            return {"success": False, "error": "No active quest for this faction."}

        quest = self._get_next_quest(faction_id)
        if not quest:
            return {"success": False, "error": "Quest not found in chain."}

        qid = quest.get("id", quest.get("title", ""))
        self._quest_complete[qid] = True
        self._active_quest = None

        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            ps.earn_credits(quest["reward_credits"], f"quest_{qid}")
            ps.update_reputation(quest["reward_rep"], f"quest_{qid}")
            if quest.get("heat_cost"):
                ps.adjust_heat(quest["heat_cost"])
            # v1.49.5 — Apply rival faction reputation costs
            for rival_id, rep_delta in quest.get("rival_rep_cost", {}).items():
                ps.update_faction_standing(rival_id, rep_delta)
        except Exception:
            pass

        # Check if the entire chain is now complete
        chain_status = self.get_faction_quest_status(faction_id)
        logger.info(
            "[%s] Quest complete (operation=quest, quest=%s, tier=%d, faction=%s, chain=%d/%d)",
            SCENE_ID, qid, quest.get("tier", 1), faction_id,
            chain_status["completed_count"], chain_status["total_quests"],
        )

        return {
            "success": True,
            "quest": quest,
            "rewards_applied": True,
            "chain_status": chain_status,
        }

    # ── Vendor Dialogue System ─────────────────────────────────────────────
    # v1.49.5 [2026-03-22] — Vendor NPCs with faction-aware dialogue triggers
    # CONNECTS: VENDOR_NPCS, PlayerState faction standings, purchase history
    # CALLED BY: /api/vendor/dialogue
    # EMITS: vendor_dialogue Socket.IO event

    def get_vendor_dialogue(self, vendor_id: str) -> Dict[str, Any]:
        """Generate context-aware dialogue from a vendor NPC.

        Considers the player's faction standings and purchase count to
        select the most appropriate greeting and any price modifiers.

        Args:
            vendor_id: The vendor NPC key (e.g., "mira", "viktor", "frankie").

        Returns:
            Dict with vendor info, dialogue text, and any price modifiers.
        """
        vendor = VENDOR_NPCS.get(vendor_id)
        if not vendor:
            return {"success": False, "error": f"Unknown vendor: {vendor_id}"}

        # Count purchases from this vendor
        purchase_count = sum(
            e["qty"] for e in self._player_inventory
            if any(
                item["vendor"] == vendor_id and item["id"] == e["item_id"]
                for item in MARKET_CATALOGUE
            )
        )
        # Also count historical purchases (items already sold back still count)
        purchase_count = max(purchase_count, self._vendor_purchase_count.get(vendor_id, 0))

        # Get player faction standings
        standings: Dict[str, int] = {}
        try:
            from engine.world.player_state import get_player_state
            standings = get_player_state().faction_standings
        except Exception:
            standings = {f["id"]: 50 for f in FACTION_DATA}

        # Determine greeting based on faction reactions
        greeting = vendor["default_greeting"]
        price_modifier = 0.0  # percentage discount (negative) or hike (positive)
        faction_reaction = None

        for faction_id, reaction in vendor.get("faction_reactions", {}).items():
            player_standing = standings.get(faction_id, 50)
            min_standing = reaction.get("min_standing", 50)
            if player_standing >= min_standing:
                # Player qualifies for this faction-based reaction
                greeting = reaction.get("greeting", greeting)
                if "discount" in reaction:
                    price_modifier = -reaction["discount"]
                elif "price_hike" in reaction:
                    price_modifier = reaction["price_hike"]
                faction_reaction = faction_id
                break  # Use the first matching faction reaction

        # Check purchase-based dialogue triggers (milestone greetings)
        purchase_dialogue = None
        triggers = vendor.get("purchase_triggers", {})
        # Find the highest matching trigger threshold
        best_threshold = -1
        for threshold, dialogue in triggers.items():
            threshold_int = int(threshold)
            if purchase_count >= threshold_int and threshold_int > best_threshold:
                best_threshold = threshold_int
                purchase_dialogue = dialogue

        return {
            "success": True,
            "vendor_id": vendor_id,
            "name": vendor["name"],
            "role": vendor["role"],
            "location": vendor["location"],
            "personality": vendor["personality"],
            "greeting": greeting,
            "purchase_dialogue": purchase_dialogue,
            "purchase_count": purchase_count,
            "price_modifier": round(price_modifier, 2),
            "faction_reaction": faction_reaction,
        }

    # ── Intel / Broker ────────────────────────────────────────────────────────

    def add_intel(self, entry: Dict[str, Any]) -> None:
        self._intel_feed.insert(0, entry)
        if len(self._intel_feed) > 30:
            self._intel_feed.pop()

    def get_intel_feed(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._intel_feed[:limit]

    def get_player_inventory(self) -> List[Dict[str, Any]]:
        return list(self._player_inventory)


_grid_state_instance: Optional[_GridState] = None


def _get_grid_state() -> _GridState:
    global _grid_state_instance
    if _grid_state_instance is None:
        _grid_state_instance = _GridState()
    return _grid_state_instance


# ──── Scene ───────────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class GridScene(FlaskScene):
    """THE GRID — underground market, travel hub, faction den, broker.

    Port 5569.  Accent #00ff88.

    CONNECTS: FlaskScene, EventBus, PlayerState, NexusKMS, WorldState
    CALLED BY: launcher.py, TUI
    EMITS: price_update, inventory_update, faction_update, quest_complete,
           intel_update, world_event Socket.IO events
    """

    SCENE_METADATA = {
        "name": "grid",
        "display_name": "THE GRID",
        "port": 5569,
        "type": "hub",
        "accent_color": "#00ff88",
        "accent_rgb": "0 255 136",
        "description": "The underground backbone of Neon City. Market. Map. Faction den. Intel broker.",
        "characters": ["mira", "viktor", "frankie"],
    }

    def __init__(self, config: Any = None) -> None:
        super().__init__(host="0.0.0.0", port=self.SCENE_METADATA["port"])
        self._state = _get_grid_state()
        self._event_sub_id: Optional[str] = None

        # Scene-specific route registrations (FlaskScene handles Flask, SocketIO,
        # CORS, shared assets, Jinja2 ChoiceLoader, health, hud, announcer,
        # inventory, and TTS routes automatically)
        self._register_routes()
        self.register_bench_route(self.app, self.socketio)
        self.register_shop_route(self.app)
        self.register_hack_route(self.app)
        self.register_city_route(self.app)
        self.register_mission_route(self.app)

    # ── FlaskScene Lifecycle Hooks ────────────────────────────────────────────
    # v1.51.0 [2026-03-22] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup: wire event cascade and register skills."""
        self._wire_event_cascade()

        # Import skills so they register with SKILL_REGISTRY
        import content.scenes.grid.grid_skills  # noqa: F401

    def on_shutdown(self) -> None:
        """Scene-specific cleanup on shutdown."""
        try:
            from engine.mcp import get_framework
            fw = get_framework()
            node = fw.register_scene(self.scene_name)
            node.update_state({"status": "stopped"})
        except Exception:
            pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all HTTP and Socket.IO routes."""
        app = self.app

        @app.route("/")
        def index():
            from flask import render_template
            # v1.49.2 [2026-03-22] — API-first: template is a pure structural
            # shell. All data (market items, factions, player state) loads
            # client-side via JS fetch to /api/* endpoints. No Jinja2 data.
            return render_template("grid.html")

        # ── Market API ────────────────────────────────────────────────────────

        @app.route("/api/market/items")
        def api_market_items():
            return Response(
                json.dumps({"items": self._state.get_market_items(), "inventory": self._state.get_player_inventory()}),
                mimetype="application/json",
            )

        @app.route("/api/market/buy", methods=["POST"])
        def api_market_buy():
            data = request.get_json(silent=True) or {}
            result = self._state.buy_item(data.get("item_id", ""), data.get("quantity", 1))
            if result.get("success") and self.socketio:
                self.socketio.emit("inventory_update", {"inventory": self._state.get_player_inventory()})
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/market/sell", methods=["POST"])
        def api_market_sell():
            data = request.get_json(silent=True) or {}
            result = self._state.sell_item(data.get("item_id", ""), data.get("quantity", 1))
            if result.get("success") and self.socketio:
                self.socketio.emit("inventory_update", {"inventory": self._state.get_player_inventory()})
            return Response(json.dumps(result, default=str), mimetype="application/json")

        # ── Station / Map API ─────────────────────────────────────────────────

        @app.route("/api/station/map")
        def api_station_map():
            from engine.utils import port_is_open
            nodes = []
            for node in CITY_MAP_NODES:
                online = port_is_open(node["port"], timeout=0.3)
                nodes.append({**node, "online": online})
            return Response(json.dumps({"nodes": nodes}), mimetype="application/json")

        # ── Faction API ───────────────────────────────────────────────────────

        @app.route("/api/faction/standings")
        def api_faction_standings():
            standings = {}
            try:
                from engine.world.player_state import get_player_state
                standings = get_player_state().faction_standings
            except Exception:
                standings = {f["id"]: 50 for f in FACTION_DATA}
            try:
                from engine.world.world_state import get_world_state
                ws_summary = get_world_state().get_world_summary()
                factions_live = ws_summary.get("factions", {})
            except Exception:
                factions_live = {}
            result = []
            for f in FACTION_DATA:
                fid = f["id"]
                power = factions_live.get(fid, {}).get("power", standings.get(fid, 50)) if factions_live else standings.get(fid, 50)
                result.append({**f, "power": power, "player_standing": standings.get(fid, 50)})
            return Response(json.dumps({"factions": result, "quests": FACTION_QUESTS}), mimetype="application/json")

        @app.route("/api/faction/pledge", methods=["POST"])
        def api_faction_pledge():
            data = request.get_json(silent=True) or {}
            result = self._state.pledge_allegiance(data.get("faction_id", ""))
            if result.get("success") and self.socketio:
                self.socketio.emit("faction_update", {"faction_id": data.get("faction_id"), "action": "pledge"})
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/faction/quest/accept", methods=["POST"])
        def api_faction_quest_accept():
            data = request.get_json(silent=True) or {}
            result = self._state.accept_quest(data.get("faction_id", ""))
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/faction/quest/complete", methods=["POST"])
        def api_faction_quest_complete():
            data = request.get_json(silent=True) or {}
            result = self._state.complete_quest(data.get("faction_id", ""))
            if result.get("success") and self.socketio:
                self.socketio.emit("quest_complete", result)
            return Response(json.dumps(result, default=str), mimetype="application/json")

        # v1.49.5 [2026-03-22] — Quest chain status endpoint
        @app.route("/api/faction/quest/status")
        def api_faction_quest_status():
            """Get quest chain progress for all factions or a specific one."""
            faction_id = request.args.get("faction_id")
            if faction_id:
                status = self._state.get_faction_quest_status(faction_id)
                return Response(json.dumps(status, default=str), mimetype="application/json")
            # Return status for all factions
            all_status = {}
            for f in FACTION_DATA:
                all_status[f["id"]] = self._state.get_faction_quest_status(f["id"])
            return Response(json.dumps({"quest_chains": all_status}, default=str), mimetype="application/json")

        # v1.49.5 [2026-03-22] — Vendor NPC dialogue endpoint
        # CONNECTS: VENDOR_NPCS, _GridState.get_vendor_dialogue, PlayerState
        # CALLED BY: Front-end vendor interaction panel
        # EMITS: vendor_dialogue Socket.IO event
        @app.route("/api/vendor/dialogue")
        def api_vendor_dialogue():
            """Get context-aware dialogue from a vendor NPC.

            Query params:
                vendor_id: The vendor key (mira, viktor, frankie)
            """
            vendor_id = request.args.get("vendor_id", "")
            if not vendor_id:
                return Response(
                    json.dumps({"success": False, "error": "vendor_id required"}),
                    mimetype="application/json",
                )
            result = self._state.get_vendor_dialogue(vendor_id)
            if result.get("success") and self.socketio:
                self.socketio.emit("vendor_dialogue", result)
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/vendor/list")
        def api_vendor_list():
            """List all vendor NPCs with basic info."""
            vendors = []
            for vid, vdata in VENDOR_NPCS.items():
                vendors.append({
                    "id": vid,
                    "name": vdata["name"],
                    "role": vdata["role"],
                    "location": vdata["location"],
                })
            return Response(json.dumps({"vendors": vendors}), mimetype="application/json")

        # ── Broker / Intel API ────────────────────────────────────────────────

        @app.route("/api/broker/intel")
        def api_broker_intel():
            feed = self._state.get_intel_feed(20)
            # Augment with recent world events from WorldState
            try:
                from engine.world.world_state import get_world_state
                ws = get_world_state()
                for ev in ws.get_active_events()[:5]:
                    feed.insert(0, {
                        "id": ev.id,
                        "title": ev.name,
                        "desc": ev.description,
                        "type": ev.event_type,
                        "timestamp": ev.started_at,
                        "source": "world_state",
                    })
            except Exception:
                pass
            return Response(json.dumps({"intel": feed}), mimetype="application/json")

        @app.route("/api/broker/sell_info", methods=["POST"])
        def api_broker_sell_info():
            data = request.get_json(silent=True) or {}
            tip = data.get("text", "").strip()
            if not tip:
                return Response(json.dumps({"success": False, "error": "No information provided."}), mimetype="application/json")
            reward = random.randint(50, 300)
            # Store in Nexus
            try:
                from engine.nexus.client import get_nexus_client
                get_nexus_client().add_entry(
                    title=f"grid_intel:{uuid.uuid4()!s:.8}",
                    content=tip,
                    content_type="note",
                    category="street_intel",
                    tags=["grid", "player_tip"],
                )
            except Exception:
                pass
            try:
                from engine.world.player_state import get_player_state
                get_player_state().earn_credits(reward, "sell_intel")
            except Exception:
                pass
            entry = {"id": str(uuid.uuid4()), "title": "Player Intel", "desc": tip[:120], "type": "tip", "timestamp": time.time(), "source": "player"}
            self._state.add_intel(entry)
            if self.socketio:
                self.socketio.emit("intel_update", {"intel": self._state.get_intel_feed()})
            return Response(json.dumps({"success": True, "reward": reward, "message": f"Intel stored. Earned ₵{reward}."}), mimetype="application/json")

        @app.route("/api/broker/ghost_message")
        def api_broker_ghost_message():
            try:
                from engine.nexus.client import get_nexus_client
                results = get_nexus_client().search("ghost_msg", limit=5)
                messages = [r.get("content", "") for r in results if r.get("content")]
            except Exception:
                messages = []
            from engine.world.neon_city_events import GHOST_MESSAGES_RICH
            fallback = [random.choice(GHOST_MESSAGES_RICH)]
            messages = messages or fallback
            return Response(json.dumps({"messages": messages[-5:]}), mimetype="application/json")

        # ── Socket.IO events ──────────────────────────────────────────────────

        @self.socketio.on("connect")
        def on_connect():
            logger.debug("THE GRID: client connected")

        @self.socketio.on("request_prices")
        def on_request_prices():
            self.socketio.emit("price_update", {"items": self._state.get_market_items()})

    def _wire_event_cascade(self) -> None:
        """Subscribe to economy and world events so market prices react."""
        try:
            from engine.events.event_bus import get_event_bus

            def _on_economy_tick(data: Dict[str, Any]) -> None:
                changed = self._state.economy_shock(
                    data.get("event_type", "market_shift"),
                    data.get("economy_impact", 0),
                )
                if changed and self.socketio:
                    self.socketio.emit("price_update", {"changes": changed, "items": self._state.get_market_items()})
                    logger.debug("THE GRID: price update — %d items changed", len(changed))

            def _on_world_event(data: Dict[str, Any]) -> None:
                entry = {
                    "id": data.get("sim_event_id", str(uuid.uuid4())),
                    "title": data.get("title", "City Event"),
                    "desc": data.get("desc", ""),
                    "type": data.get("event_type", "world"),
                    "timestamp": time.time(),
                    "source": "world_sim",
                }
                self._state.add_intel(entry)
                if self.socketio:
                    self.socketio.emit("intel_update", {"intel": self._state.get_intel_feed()})
                    self.socketio.emit("world_event", data)

            bus = get_event_bus()
            bus.subscribe("world.economy_tick", _on_economy_tick, subscriber_id="grid")
            bus.subscribe("world.major_event", _on_world_event, subscriber_id="grid")
            logger.debug("THE GRID: EventBus wired")
        except Exception as exc:
            logger.warning("[%s] EventBus wiring failed (operation=lifecycle): %s", SCENE_ID, exc)
