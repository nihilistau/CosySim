"""
The Realm — Game State Engine
==============================

Thread-safe state management for the LitRPG visual novel using the MCP
GameState store. Manages:

* Player stats, inventory, skills
* Director personality & patience meter
* Murder mystery phase tracking
* Memory echoes (past-run hints)
* Time limits & win conditions
"""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════

DIRECTOR_PERSONALITIES = {
    "random":     {"label": "The Wildcard",    "patience_decay": 1.0, "difficulty_mod": 0,   "style": "Unpredictable tone shifts, random events, chaotic energy."},
    "aggressive": {"label": "The Tyrant",      "patience_decay": 1.5, "difficulty_mod": 2,   "style": "Punishing, ruthless, loves traps and ambushes. Rarely gives freebies."},
    "passive":    {"label": "The Dreamer",      "patience_decay": 0.5, "difficulty_mod": -1,  "style": "Gentle narration, scenic descriptions, generous with loot."},
    "deceptive":  {"label": "The Liar",         "patience_decay": 1.2, "difficulty_mod": 1,   "style": "Unreliable narrator. Descriptions may be false. NPCs mislead."},
    "theatrical": {"label": "The Showman",      "patience_decay": 0.8, "difficulty_mod": 0,   "style": "Dramatic monologues, lighting cues, orchestral mood. Everything is a spectacle."},
}

DEFAULT_STATS = {
    "hp": 100, "max_hp": 100,
    "mp": 50,  "max_mp": 50,
    "strength": 10, "agility": 10, "intellect": 10,
    "charisma": 10, "luck": 5,
    "level": 1, "xp": 0, "xp_next": 100,
    "gold": 0,
}

SKILL_TREE = {
    "persuasion":   {"stat": "charisma",  "base_dc": 12},
    "lockpicking":  {"stat": "agility",   "base_dc": 14},
    "arcana":       {"stat": "intellect", "base_dc": 15},
    "athletics":    {"stat": "strength",  "base_dc": 11},
    "stealth":      {"stat": "agility",   "base_dc": 13},
    "intimidation": {"stat": "strength",  "base_dc": 13},
    "deception":    {"stat": "charisma",  "base_dc": 14},
    "investigation":{"stat": "intellect", "base_dc": 12},
    "survival":     {"stat": "luck",      "base_dc": 10},
}

STARTER_ITEMS = [
    {"id": "rusty_sword",  "name": "Rusty Sword",  "type": "weapon",  "damage": 5,  "description": "A blade that's seen better centuries."},
    {"id": "health_potion", "name": "Health Potion", "type": "consumable", "heal": 25, "description": "Tastes like cherry cough syrup."},
    {"id": "torch",        "name": "Torch",         "type": "utility",  "description": "Illuminates dark areas. Burns for 30 minutes."},
]

# ═══════════════════════════════════════════════════════════════
#  EQUIPMENT & ECONOMY
# ═══════════════════════════════════════════════════════════════

EQUIPMENT_SLOTS = ["weapon", "armor", "shield", "helm", "boots", "ring", "amulet"]

ITEM_CATALOG = {
    "rusty_sword":          {"name": "Rusty Sword",          "slot": "weapon",  "attack": 2,  "value": 10},
    "iron_sword":           {"name": "Iron Sword",           "slot": "weapon",  "attack": 5,  "value": 50},
    "steel_sword":          {"name": "Steel Greatsword",     "slot": "weapon",  "attack": 8,  "value": 150},
    "leather_armor":        {"name": "Leather Armor",        "slot": "armor",   "defense": 3, "value": 30},
    "chainmail":            {"name": "Chainmail",            "slot": "armor",   "defense": 6, "value": 120},
    "plate_armor":          {"name": "Plate Armor",          "slot": "armor",   "defense": 10,"value": 300},
    "wooden_shield":        {"name": "Wooden Shield",        "slot": "shield",  "defense": 2, "value": 15},
    "iron_helm":            {"name": "Iron Helm",            "slot": "helm",    "defense": 2, "value": 40},
    "health_potion":        {"name": "Health Potion",        "slot": None,      "heal": 20,   "value": 25, "consumable": True},
    "mana_potion":          {"name": "Mana Potion",          "slot": None,      "mana": 15,   "value": 30, "consumable": True},
    "ring_of_strength":     {"name": "Ring of Strength",     "slot": "ring",    "attack": 3,  "value": 200},
    "amulet_of_protection": {"name": "Amulet of Protection", "slot": "amulet",  "defense": 3, "value": 200},
}

GOLD_DROP_RANGE = {"min": 5, "max": 25}

# ═══════════════════════════════════════════════════════════════
#  COMBAT: ENEMY TEMPLATES
# ═══════════════════════════════════════════════════════════════

ENEMY_TEMPLATES = {
    "goblin":       {"name": "Goblin",       "hp": 20,  "attack": 4,  "defense": 1, "xp": 15,  "loot_chance": 0.4},
    "skeleton":     {"name": "Skeleton",     "hp": 30,  "attack": 6,  "defense": 2, "xp": 25,  "loot_chance": 0.3},
    "bandit":       {"name": "Bandit",       "hp": 35,  "attack": 7,  "defense": 3, "xp": 30,  "loot_chance": 0.5},
    "dire_wolf":    {"name": "Dire Wolf",    "hp": 40,  "attack": 8,  "defense": 2, "xp": 35,  "loot_chance": 0.2},
    "dark_mage":    {"name": "Dark Mage",    "hp": 25,  "attack": 10, "defense": 1, "xp": 40,  "loot_chance": 0.6},
    "troll":        {"name": "Cave Troll",   "hp": 60,  "attack": 9,  "defense": 5, "xp": 50,  "loot_chance": 0.4},
    "wraith":       {"name": "Wraith",       "hp": 45,  "attack": 11, "defense": 3, "xp": 55,  "loot_chance": 0.5},
    "dragon_wyrmling": {"name": "Dragon Wyrmling", "hp": 80, "attack": 14, "defense": 6, "xp": 100, "loot_chance": 0.7},
}

COMBAT_LOOT_TABLE = [
    {"id": "iron_sword",    "name": "Iron Sword",     "type": "weapon",     "damage": 8,  "description": "A proper blade."},
    {"id": "silver_dagger", "name": "Silver Dagger",  "type": "weapon",     "damage": 6,  "description": "Extra damage to undead."},
    {"id": "health_potion", "name": "Health Potion",  "type": "consumable", "heal": 25,   "description": "Cherry cough syrup."},
    {"id": "mana_potion",   "name": "Mana Potion",    "type": "consumable", "heal_mp": 20, "description": "Tastes like blueberries."},
    {"id": "shield_charm",  "name": "Shield Charm",   "type": "utility",    "description": "Blocks one attack."},
    {"id": "fire_scroll",   "name": "Fire Scroll",    "type": "consumable", "damage": 15, "description": "Single-use fireball."},
    {"id": "gold_ring",     "name": "Gold Ring",      "type": "treasure",   "value": 50,  "description": "Worth a pretty penny."},
]

# ═══════════════════════════════════════════════════════════════
#  LOCATION SYSTEM
# ═══════════════════════════════════════════════════════════════

REALM_LOCATIONS = {
    "tavern": {
        "name": "The Rusty Flagon",
        "description": "A smoky tavern filled with weary travellers, clinking mugs, and questionable stew. The barkeep eyes you warily.",
        "encounters": ["drunk_patron", "traveling_merchant"],
        "enemy_pool": ["bandit"],
        "encounter_chance": 0.2,
        "connections": ["town_square", "back_alley"],
    },
    "town_square": {
        "name": "Thornwick Square",
        "description": "The bustling heart of Thornwick. A crumbling fountain stands at its centre, surrounded by market stalls and gossiping townsfolk.",
        "encounters": ["pickpocket", "town_crier"],
        "enemy_pool": ["goblin", "bandit"],
        "encounter_chance": 0.25,
        "connections": ["tavern", "market", "castle_gate", "dark_forest"],
    },
    "market": {
        "name": "Market District",
        "description": "Rows of colourful stalls hawk everything from enchanted trinkets to dubious potions. Haggling voices echo off stone walls.",
        "encounters": ["haggling_vendor", "lost_child"],
        "enemy_pool": ["bandit"],
        "encounter_chance": 0.15,
        "connections": ["town_square", "temple"],
    },
    "temple": {
        "name": "Temple of the Silver Flame",
        "description": "A serene sanctuary of white marble and stained glass. Acolytes murmur prayers while incense drifts through the air.",
        "encounters": ["healing_priest", "cursed_pilgrim"],
        "enemy_pool": ["wraith"],
        "encounter_chance": 0.1,
        "connections": ["market"],
    },
    "castle_gate": {
        "name": "Castle Gatehouse",
        "description": "Iron-banded gates tower above you, flanked by armoured guards. Beyond lies the seat of power — if they'll let you pass.",
        "encounters": ["guard_captain", "suspicious_courier"],
        "enemy_pool": ["skeleton"],
        "encounter_chance": 0.2,
        "connections": ["town_square", "throne_room"],
    },
    "throne_room": {
        "name": "The Throne Room",
        "description": "Gold-veined marble floors stretch toward an obsidian throne. The air hums with political tension and barely concealed ambition.",
        "encounters": ["king_audience", "court_intrigue"],
        "enemy_pool": ["dark_mage"],
        "encounter_chance": 0.15,
        "connections": ["castle_gate"],
    },
    "back_alley": {
        "name": "The Rat Warrens",
        "description": "Narrow, refuse-choked alleyways where the desperate and dangerous lurk. Shadows shift at every corner.",
        "encounters": ["black_market_dealer", "ambush"],
        "enemy_pool": ["bandit", "goblin", "dire_wolf"],
        "encounter_chance": 0.4,
        "connections": ["tavern", "dark_forest"],
    },
    "dark_forest": {
        "name": "Whispering Woods",
        "description": "Ancient trees groan overhead, their branches blotting out the sky. Something watches from the undergrowth.",
        "encounters": ["wolf_pack", "fairy_ring", "bandit_camp"],
        "enemy_pool": ["dire_wolf", "goblin", "skeleton", "troll"],
        "encounter_chance": 0.5,
        "connections": ["town_square", "back_alley", "ancient_ruins"],
    },
    "ancient_ruins": {
        "name": "Ruins of Aldrath",
        "description": "Crumbling stone walls etched with forgotten runes. The ground trembles faintly, as if something stirs below.",
        "encounters": ["skeleton_warriors", "trapped_chest", "boss_lich"],
        "enemy_pool": ["skeleton", "wraith", "dark_mage", "troll"],
        "encounter_chance": 0.6,
        "connections": ["dark_forest", "dragon_lair"],
    },
    "dragon_lair": {
        "name": "Ember Caverns",
        "description": "Blistering heat radiates from the cavern walls. Scorched bones crunch underfoot and a low rumble shakes the earth.",
        "encounters": ["boss_dragon", "treasure_hoard"],
        "enemy_pool": ["dragon_wyrmling", "wraith"],
        "encounter_chance": 0.7,
        "connections": ["ancient_ruins"],
    },
}

DEFAULT_LOCATION = "tavern"

# ═══════════════════════════════════════════════════════════════
#  QUESTS
# ═══════════════════════════════════════════════════════════════

QUEST_TEMPLATES = {
    "rats_in_cellar": {
        "title": "Rats in the Cellar",
        "description": "The innkeeper needs you to clear giant rats from the basement.",
        "objective": "Defeat 3 enemies",
        "target_kills": 3,
        "xp_reward": 50,
        "item_reward": {"id": "iron_sword", "name": "Iron Sword", "type": "weapon", "damage": 8, "description": "A proper blade."},
    },
    "missing_scholar": {
        "title": "The Missing Scholar",
        "description": "Professor Blackwood's colleague vanished near the old ruins.",
        "objective": "Explore 5 rooms and find the scholar",
        "target_turns": 5,
        "xp_reward": 75,
        "item_reward": {"id": "arcane_tome", "name": "Arcane Tome", "type": "utility", "description": "Grants +2 INT when carried."},
    },
    "bounty_hunter": {
        "title": "Bounty: The Shadow",
        "description": "A wanted criminal lurks in the dark quarters. Bring them in.",
        "objective": "Defeat the bounty target",
        "target_kills": 1,
        "xp_reward": 100,
        "item_reward": {"id": "bounty_badge", "name": "Bounty Badge", "type": "treasure", "value": 100, "description": "Proof of your prowess."},
    },
    "ancient_artifact": {
        "title": "The Ancient Artifact",
        "description": "Legend speaks of a powerful relic hidden in the deepest chamber.",
        "objective": "Survive 8 turns and find the artifact",
        "target_turns": 8,
        "xp_reward": 150,
        "item_reward": {"id": "ancient_amulet", "name": "Ancient Amulet", "type": "utility", "description": "Glows with mysterious power. +3 all stats."},
    },
    "dragon_slayer": {
        "title": "Slay the Dragon",
        "description": "A dragon wyrmling terrorizes the village. Only a hero can stop it.",
        "objective": "Defeat the dragon wyrmling",
        "target_kills": 1,
        "target_enemy": "dragon_wyrmling",
        "xp_reward": 200,
        "item_reward": {"id": "dragon_scale", "name": "Dragon Scale", "type": "treasure", "value": 500, "description": "A trophy of ultimate victory."},
    },
}

# Murder Mystery constants
MURDER_WEAPONS = ["Candlestick", "Dagger", "Poison Vial", "Silk Rope", "Crystal Shard"]
MURDER_ROOMS   = ["Library", "Ballroom", "Kitchen", "Garden", "Study"]
MURDER_NPCS    = [
    {"id": "lord_ashford",   "name": "Lord Ashford",   "trait": "pompous aristocrat, secretly bankrupt"},
    {"id": "lady_rose",      "name": "Lady Rose",      "trait": "charming socialite, has a dark past"},
    {"id": "prof_blackwood", "name": "Prof. Blackwood", "trait": "eccentric academic, obsessed with artifacts"},
    {"id": "chef_dubois",    "name": "Chef Dubois",    "trait": "temperamental chef, owes gambling debts"},
    {"id": "ms_winter",      "name": "Ms. Winter",     "trait": "quiet librarian, knows everyone's secrets"},
]


# ═══════════════════════════════════════════════════════════════
#  REALM GAME STATE
# ═══════════════════════════════════════════════════════════════

class RealmGameState:
    """
    Central state for one Realm session, backed by the MCP GameState store.
    """

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or f"realm_{uuid.uuid4().hex[:8]}"
        self._lock = threading.RLock()

        # ── Core state ──
        self.player_stats: Dict[str, int | float] = dict(DEFAULT_STATS)
        self.inventory: List[Dict[str, Any]] = list(STARTER_ITEMS)
        self.skills_unlocked: List[str] = []
        self.status_effects: List[Dict[str, Any]] = []

        # ── Director ──
        self.director_personality: str = "random"
        self.director_patience: float = 100.0
        self.director_locked_out: bool = False
        self.mutiny_until: float = 0.0

        # ── Story ──
        self.story_log: List[Dict[str, Any]] = []
        self.current_scene_text: str = ""
        self.current_choices: List[Dict[str, str]] = []
        self.turn_number: int = 0
        self.time_limit_s: float = 0.0
        self.started_at: float = 0.0
        self.ended: bool = False
        self.outcome: str = ""

        # ── Memory Echoes (past runs) ──
        self.past_deaths: List[Dict[str, Any]] = []

        # ── Murder Mystery sub-module ──
        self.murder: Optional[MurderMysteryState] = None

        # ── Assistant ──
        self.assistant_mood: str = "sarcastic"
        self.assistant_stolen_items: List[str] = []  # fourth-wall inventory

        # ── Combat ──
        self.combat: Optional[CombatEncounter] = None
        self.total_kills: int = 0

        # ── Quests ──
        self.active_quests: List[Dict[str, Any]] = []
        self.completed_quests: List[str] = []

        # ── Equipment & Economy ──
        self.equipment: Dict[str, Optional[str]] = {slot: None for slot in EQUIPMENT_SLOTS}
        self.gold: int = 50

        # ── Location ──
        self.current_location: str = DEFAULT_LOCATION
        self.defending: bool = False

    # ── Accessors ──

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "player_stats": dict(self.player_stats),
                "inventory": list(self.inventory),
                "skills_unlocked": list(self.skills_unlocked),
                "status_effects": list(self.status_effects),
                "director_personality": self.director_personality,
                "director_patience": self.director_patience,
                "director_locked_out": self.director_locked_out,
                "turn_number": self.turn_number,
                "time_remaining": self.time_remaining(),
                "ended": self.ended,
                "outcome": self.outcome,
                "story_log_length": len(self.story_log),
                "current_choices": self.current_choices,
                "assistant_mood": self.assistant_mood,
                "combat": self.combat.to_dict() if self.combat else None,
                "total_kills": self.total_kills,
                "active_quests": list(self.active_quests),
                "completed_quests": list(self.completed_quests),
                "murder": self.murder.to_dict() if self.murder else None,
                "equipment": dict(self.equipment),
                "gold": self.gold,
                "current_location": self.current_location,
                "location_info": REALM_LOCATIONS.get(self.current_location, {}),
            }

    # ── Time ──

    def time_remaining(self) -> float:
        if self.time_limit_s <= 0 or self.started_at <= 0:
            return -1.0
        elapsed = time.time() - self.started_at
        return max(0.0, self.time_limit_s - elapsed)

    def is_timed_out(self) -> bool:
        return self.time_limit_s > 0 and self.time_remaining() <= 0

    # ── Director ──

    def set_director(self, personality: str) -> Dict[str, Any]:
        if personality not in DIRECTOR_PERSONALITIES:
            personality = "random"
        with self._lock:
            self.director_personality = personality
            self.director_patience = 100.0
        info = DIRECTOR_PERSONALITIES[personality]
        return {"personality": personality, **info}

    def decay_patience(self, amount: float | None = None) -> float:
        info = DIRECTOR_PERSONALITIES.get(self.director_personality, {})
        decay = amount if amount is not None else info.get("patience_decay", 1.0) * 3.0
        with self._lock:
            self.director_patience = max(0.0, self.director_patience - decay)
            return self.director_patience

    def is_mutiny_active(self) -> bool:
        return time.time() < self.mutiny_until

    def trigger_mutiny(self, duration_s: float = 120.0) -> None:
        with self._lock:
            self.mutiny_until = time.time() + duration_s
            self.director_locked_out = True

    def end_mutiny(self) -> None:
        with self._lock:
            self.mutiny_until = 0.0
            self.director_locked_out = False

    # ── Stats ──

    def adjust_stat(self, stat: str, delta: int) -> int:
        with self._lock:
            current = self.player_stats.get(stat, 0)
            new_val = current + delta
            cap = self.player_stats.get(f"max_{stat}")
            if cap is not None:
                new_val = min(new_val, cap)
            self.player_stats[stat] = max(0, new_val)
            return self.player_stats[stat]

    def take_damage(self, amount: int) -> Tuple[int, bool]:
        hp = self.adjust_stat("hp", -abs(amount))
        dead = hp <= 0
        if dead:
            self.ended = True
            self.outcome = "death"
        return hp, dead

    def heal(self, amount: int) -> int:
        return self.adjust_stat("hp", abs(amount))

    def gain_xp(self, amount: int) -> Dict[str, Any]:
        with self._lock:
            self.player_stats["xp"] += amount
            leveled = False
            while self.player_stats["xp"] >= self.player_stats["xp_next"]:
                self.player_stats["xp"] -= self.player_stats["xp_next"]
                self.player_stats["level"] += 1
                self.player_stats["xp_next"] = int(self.player_stats["xp_next"] * 1.5)
                self.player_stats["max_hp"] += 10
                self.player_stats["hp"] = self.player_stats["max_hp"]
                self.player_stats["max_mp"] += 5
                self.player_stats["mp"] = self.player_stats["max_mp"]
                leveled = True
            if leveled:
                self._submit_leaderboard("realm_levels", "Player", self.player_stats["level"])
            return {"level": self.player_stats["level"], "leveled_up": leveled, "xp": self.player_stats["xp"]}

    # ── Skill checks ──

    def skill_check(self, skill_name: str, dc_modifier: int = 0) -> Dict[str, Any]:
        info = SKILL_TREE.get(skill_name)
        if not info:
            return {"success": False, "reason": "unknown skill"}
        stat_val = self.player_stats.get(info["stat"], 10)
        bonus = (stat_val - 10) // 2
        director_mod = DIRECTOR_PERSONALITIES.get(self.director_personality, {}).get("difficulty_mod", 0)
        dc = info["base_dc"] + dc_modifier + director_mod
        roll = random.randint(1, 20)
        total = roll + bonus
        success = total >= dc
        return {
            "skill": skill_name, "roll": roll, "bonus": bonus,
            "total": total, "dc": dc, "success": success,
            "stat": info["stat"], "stat_value": stat_val,
        }

    # ── Inventory ──

    def add_item(self, item: Dict[str, Any]) -> None:
        with self._lock:
            self.inventory.append(item)

    def remove_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for i, item in enumerate(self.inventory):
                if item.get("id") == item_id:
                    return self.inventory.pop(i)
            return None

    def has_item(self, item_id: str) -> bool:
        return any(i.get("id") == item_id for i in self.inventory)

    # ── Equipment ──

    def equip_item(self, item_id: str) -> Dict[str, Any]:
        """Equip an inventory item to its designated slot."""
        catalog_key = item_id.split("_", maxsplit=0)[0]  # handle unique suffixes
        # Find matching catalog entry by base id
        base_key = None
        for key in ITEM_CATALOG:
            if item_id == key or item_id.startswith(key + "_"):
                base_key = key
                break
        if not base_key:
            return {"error": f"Item '{item_id}' not in catalog"}
        cat_entry = ITEM_CATALOG[base_key]
        slot = cat_entry.get("slot")
        if not slot:
            return {"error": "Item cannot be equipped (consumable)"}
        if not self.has_item(item_id):
            return {"error": "Item not in inventory"}
        with self._lock:
            # Unequip current item in that slot first
            old_item_id = self.equipment.get(slot)
            if old_item_id:
                self.equipment[slot] = None
            self.equipment[slot] = item_id
        return {"equipped": True, "slot": slot, "item_id": item_id, "name": cat_entry["name"],
                "replaced": old_item_id}

    def unequip_slot(self, slot: str) -> Dict[str, Any]:
        """Unequip an item from a slot."""
        if slot not in EQUIPMENT_SLOTS:
            return {"error": f"Invalid slot: {slot}"}
        with self._lock:
            item_id = self.equipment.get(slot)
            if not item_id:
                return {"error": f"Nothing equipped in {slot}"}
            self.equipment[slot] = None
        return {"unequipped": True, "slot": slot, "item_id": item_id}

    def get_equipment(self) -> Dict[str, Any]:
        """Return current equipment with catalog details."""
        result: Dict[str, Any] = {}
        with self._lock:
            for slot in EQUIPMENT_SLOTS:
                item_id = self.equipment.get(slot)
                if item_id:
                    base_key = None
                    for key in ITEM_CATALOG:
                        if item_id == key or item_id.startswith(key + "_"):
                            base_key = key
                            break
                    result[slot] = {"item_id": item_id, **(ITEM_CATALOG.get(base_key, {}) if base_key else {})}
                else:
                    result[slot] = None
        return result

    def get_total_stats(self) -> Dict[str, Any]:
        """Return base stats plus equipment bonuses."""
        with self._lock:
            stats = dict(self.player_stats)
            bonus_attack = 0
            bonus_defense = 0
            for slot in EQUIPMENT_SLOTS:
                item_id = self.equipment.get(slot)
                if not item_id:
                    continue
                base_key = None
                for key in ITEM_CATALOG:
                    if item_id == key or item_id.startswith(key + "_"):
                        base_key = key
                        break
                if base_key:
                    entry = ITEM_CATALOG[base_key]
                    bonus_attack += entry.get("attack", 0)
                    bonus_defense += entry.get("defense", 0)
            stats["bonus_attack"] = bonus_attack
            stats["bonus_defense"] = bonus_defense
            stats["effective_attack"] = stats.get("strength", 10) + bonus_attack
            stats["effective_defense"] = bonus_defense
            return stats

    # ── Economy ──

    def add_gold(self, amount: int) -> int:
        with self._lock:
            self.gold += amount
            return self.gold

    def remove_gold(self, amount: int) -> Tuple[bool, int]:
        """Remove gold; returns (success, new_balance)."""
        with self._lock:
            if self.gold < amount:
                return False, self.gold
            self.gold -= amount
            return True, self.gold

    def buy_item(self, item_key: str) -> Dict[str, Any]:
        """Buy an item from the catalog."""
        if item_key not in ITEM_CATALOG:
            return {"error": "Item not in catalog"}
        entry = ITEM_CATALOG[item_key]
        cost = entry.get("value", 0)
        with self._lock:
            if self.gold < cost:
                return {"error": "Not enough gold", "gold": self.gold, "cost": cost}
            self.gold -= cost
            item = {
                "id": f"{item_key}_{uuid.uuid4().hex[:4]}",
                "name": entry["name"],
                "type": entry.get("slot") or ("consumable" if entry.get("consumable") else "misc"),
                "description": f"Purchased from shop for {cost} gold.",
            }
            self.inventory.append(item)
        return {"bought": True, "item": item, "gold": self.gold}

    def sell_item(self, item_id: str) -> Dict[str, Any]:
        """Sell an inventory item for half its catalog value."""
        # Unequip first if equipped
        for slot, eid in self.equipment.items():
            if eid == item_id:
                self.equipment[slot] = None
                break
        item = self.remove_item(item_id)
        if not item:
            return {"error": "Item not in inventory"}
        base_key = None
        for key in ITEM_CATALOG:
            if item_id == key or item_id.startswith(key + "_"):
                base_key = key
                break
        value = ITEM_CATALOG[base_key]["value"] // 2 if base_key else 1
        with self._lock:
            self.gold += value
        return {"sold": True, "item_name": item.get("name", item_id), "gold_gained": value, "gold": self.gold}

    def get_level(self) -> int:
        """XP-based level: floor(xp / 100) + 1."""
        return self.player_stats.get("level", 1)

    # ── Fourth-Wall (Assistant stealing from UI) ──

    def assistant_steal(self, item_name: str) -> Dict[str, Any]:
        """Assistant 'steals' a concept from the game UI and materialises it as an item."""
        item = {
            "id": f"stolen_{uuid.uuid4().hex[:6]}",
            "name": f"[STOLEN] {item_name}",
            "type": "fourth_wall",
            "description": f"The Assistant ripped '{item_name}' straight from the interface.",
        }
        with self._lock:
            self.inventory.append(item)
            self.assistant_stolen_items.append(item_name)
        return item

    # ── Desperation Dice ──

    def desperation_dice(self) -> Dict[str, Any]:
        """Sacrifice 10 permanent max HP to rewrite the Director's last prompt."""
        with self._lock:
            if self.player_stats["max_hp"] <= 20:
                return {"success": False, "reason": "HP too low to sacrifice"}
            self.player_stats["max_hp"] -= 10
            self.player_stats["hp"] = min(self.player_stats["hp"], self.player_stats["max_hp"])
        return {"success": True, "new_max_hp": self.player_stats["max_hp"]}

    # ── Memory Echoes ──

    def record_death(self, cause: str, turn: int) -> None:
        self.past_deaths.append({"cause": cause, "turn": turn, "session": self.session_id})

    def get_echo_hint(self) -> Optional[str]:
        if not self.past_deaths:
            return None
        death = random.choice(self.past_deaths)
        return f"A ghostly sensation... you recall dying from '{death['cause']}' on turn {death['turn']}."

    # ── Story ──

    def advance_turn(self, scene_text: str, choices: List[Dict[str, str]] | None = None) -> int:
        with self._lock:
            self.turn_number += 1
            self.current_scene_text = scene_text
            self.current_choices = choices or []
            self.story_log.append({
                "turn": self.turn_number,
                "text": scene_text[:500],
                "choices": self.current_choices,
                "timestamp": time.time(),
            })
            return self.turn_number

    def end_game(self, outcome: str) -> Dict[str, Any]:
        with self._lock:
            self.ended = True
            self.outcome = outcome
            return {"outcome": outcome, "turns": self.turn_number, "stats": dict(self.player_stats)}

    # ── Combat Encounters ──

    def start_combat(self, enemy_key: str | None = None) -> Dict[str, Any]:
        """Initiate a turn-based combat encounter."""
        if self.combat and self.combat.active:
            return {"error": "Already in combat"}
        if enemy_key and enemy_key in ENEMY_TEMPLATES:
            template = ENEMY_TEMPLATES[enemy_key]
        else:
            level = self.player_stats.get("level", 1)
            pool = list(ENEMY_TEMPLATES.keys())
            if level < 3:
                pool = [k for k in pool if ENEMY_TEMPLATES[k]["hp"] <= 40]
            enemy_key = random.choice(pool or list(ENEMY_TEMPLATES.keys()))
            template = ENEMY_TEMPLATES[enemy_key]
        self.combat = CombatEncounter(enemy_key, dict(template))
        return self.combat.to_dict()

    def combat_attack(self) -> Dict[str, Any]:
        """Player attacks the enemy."""
        if not self.combat or not self.combat.active:
            return {"error": "Not in combat"}
        weapon = next((i for i in self.inventory if i.get("type") == "weapon"), None)
        base_dmg = weapon.get("damage", 3) if weapon else 3
        str_mod = (self.player_stats.get("strength", 10) - 10) // 2
        roll = random.randint(1, 20)
        enemy_def = self.combat.template.get("defense", 0)
        crit = roll == 20
        miss = (roll + str_mod) < enemy_def and not crit
        if roll == 1 or miss:
            player_dmg = 0
            miss = True
        else:
            player_dmg = base_dmg + str_mod + (base_dmg if crit else 0)
            player_dmg = max(1, player_dmg - enemy_def)
        self.combat.enemy_hp = max(0, self.combat.enemy_hp - player_dmg)
        # Enemy counter-attack
        enemy_dmg = 0
        if self.combat.enemy_hp > 0:
            enemy_dmg = self._enemy_attacks()
        self.defending = False  # reset defend stance after any action
        defeated = self.combat.enemy_hp <= 0
        result = {
            "roll": roll, "crit": crit, "miss": miss,
            "player_damage": player_dmg, "enemy_damage": enemy_dmg,
            "enemy_hp": self.combat.enemy_hp,
            "player_hp": self.player_stats["hp"],
            "defeated": defeated,
            "weapon": weapon.get("name", "Fists") if weapon else "Fists",
        }
        if defeated:
            result.update(self._resolve_combat_victory())
        return result

    def _enemy_attacks(self) -> int:
        """Run the enemy's counter-attack against the player, respecting defend stance."""
        if not self.combat or not self.combat.active:
            return 0
        enemy_roll = random.randint(1, 20)
        agi_mod = (self.player_stats.get("agility", 10) - 10) // 2
        dodge = enemy_roll <= max(1, 2 + agi_mod)
        if dodge:
            return 0
        raw = self.combat.template.get("attack", 5)
        if self.defending:
            raw = raw // 2  # defend halves incoming damage
        dmg = max(1, raw)
        self.take_damage(dmg)
        return dmg

    def combat_defend(self) -> Dict[str, Any]:
        """Player defends — halves incoming damage this round, enemy still attacks."""
        if not self.combat or not self.combat.active:
            return {"error": "Not in combat"}
        self.defending = True
        enemy_dmg = self._enemy_attacks()
        self.defending = False
        return {
            "defended": True,
            "enemy_damage": enemy_dmg,
            "player_hp": self.player_stats["hp"],
            "enemy_hp": self.combat.enemy_hp,
            "enemy_name": self.combat.enemy_name,
        }

    def combat_use_item(self, item_id: str) -> Dict[str, Any]:
        """Use a consumable item during combat."""
        if not self.combat or not self.combat.active:
            return {"error": "Not in combat"}
        item = None
        for i in self.inventory:
            if i.get("id") == item_id:
                item = i
                break
        if not item:
            return {"error": "Item not found in inventory"}
        result: Dict[str, Any] = {"item_name": item.get("name", item_id)}
        # Apply item effects
        if item.get("type") == "consumable" or item.get("heal") or item.get("heal_mp") or item.get("damage"):
            self.remove_item(item_id)
            if item.get("heal"):
                hp = self.heal(item["heal"])
                result["healed"] = item["heal"]
                result["player_hp"] = hp
            if item.get("heal_mp"):
                self.adjust_stat("mp", item["heal_mp"])
                result["restored_mp"] = item["heal_mp"]
            if item.get("damage"):
                self.combat.enemy_hp = max(0, self.combat.enemy_hp - item["damage"])
                result["item_damage"] = item["damage"]
                result["enemy_hp"] = self.combat.enemy_hp
        else:
            return {"error": f"'{item.get('name', item_id)}' cannot be used in combat"}
        # Enemy counter-attack (using item takes a turn)
        enemy_dmg = 0
        defeated = self.combat.enemy_hp <= 0
        if not defeated:
            enemy_dmg = self._enemy_attacks()
        result["enemy_damage"] = enemy_dmg
        result["player_hp"] = self.player_stats["hp"]
        result["enemy_hp"] = self.combat.enemy_hp
        result["defeated"] = defeated
        if defeated:
            result.update(self._resolve_combat_victory())
        return result

    def combat_flee(self) -> Dict[str, Any]:
        """Attempt to flee combat."""
        if not self.combat or not self.combat.active:
            return {"error": "Not in combat"}
        agi = self.player_stats.get("agility", 10)
        roll = random.randint(1, 20) + (agi - 10) // 2
        success = roll >= 12
        if success:
            self.combat.active = False
            self.combat = None
            return {"fled": True, "roll": roll}
        # Failed — enemy gets a free hit
        enemy_atk = self.combat.template.get("attack", 5)
        dmg = max(1, enemy_atk)
        self.take_damage(dmg)
        return {"fled": False, "roll": roll, "enemy_damage": dmg, "player_hp": self.player_stats["hp"]}

    def _resolve_combat_victory(self) -> Dict[str, Any]:
        """Handle XP, loot, and quest progress after defeating an enemy."""
        if not self.combat:
            return {}
        self.combat.active = False
        xp = self.combat.template.get("xp", 10)
        xp_result = self.gain_xp(xp)
        self.total_kills += 1
        result = {"xp_gained": xp, **xp_result}
        # Gold drop
        gold_drop = random.randint(GOLD_DROP_RANGE["min"], GOLD_DROP_RANGE["max"])
        luck_gold = (self.player_stats.get("luck", 5) - 5)
        gold_drop = max(1, gold_drop + luck_gold)
        self.add_gold(gold_drop)
        result["gold_gained"] = gold_drop
        # Loot roll
        loot_chance = self.combat.template.get("loot_chance", 0.3)
        luck_bonus = (self.player_stats.get("luck", 5) - 5) * 0.02
        if random.random() < loot_chance + luck_bonus:
            loot = dict(random.choice(COMBAT_LOOT_TABLE))
            loot["id"] = f"{loot['id']}_{uuid.uuid4().hex[:4]}"
            self.add_item(loot)
            result["loot"] = loot
        # Check quest progress
        quest_updates = self._check_quest_progress("kill", self.combat.enemy_key)
        if quest_updates:
            result["quest_updates"] = quest_updates
        enemy_key = self.combat.enemy_key
        self.combat = None
        result["enemy_defeated"] = enemy_key
        return result

    # ── Quest System ──

    def accept_quest(self, quest_key: str) -> Dict[str, Any]:
        """Accept a quest from the available quest templates."""
        if quest_key not in QUEST_TEMPLATES:
            return {"error": "Unknown quest"}
        if quest_key in self.completed_quests:
            return {"error": "Quest already completed"}
        if any(q["key"] == quest_key for q in self.active_quests):
            return {"error": "Quest already active"}
        template = QUEST_TEMPLATES[quest_key]
        quest = {
            "key": quest_key,
            "title": template["title"],
            "description": template["description"],
            "objective": template["objective"],
            "progress": 0,
            "target": template.get("target_kills", template.get("target_turns", 1)),
            "accepted_turn": self.turn_number,
        }
        with self._lock:
            self.active_quests.append(quest)
        return {"accepted": True, "quest": quest}

    def _check_quest_progress(self, event_type: str, detail: str = "") -> List[Dict]:
        """Check and advance quest progress based on game events."""
        updates = []
        with self._lock:
            for quest in self.active_quests:
                template = QUEST_TEMPLATES.get(quest["key"], {})
                if event_type == "kill":
                    target_enemy = template.get("target_enemy")
                    if target_enemy and detail != target_enemy:
                        continue
                    if "target_kills" in template:
                        quest["progress"] = min(quest["progress"] + 1, quest["target"])
                        updates.append({"quest": quest["key"], "progress": quest["progress"], "target": quest["target"]})
                elif event_type == "turn":
                    if "target_turns" in template:
                        quest["progress"] = min(quest["progress"] + 1, quest["target"])
                        updates.append({"quest": quest["key"], "progress": quest["progress"], "target": quest["target"]})
                # Check completion
                if quest["progress"] >= quest["target"]:
                    self._complete_quest(quest["key"])
                    updates.append({"quest": quest["key"], "completed": True})
        return updates

    def _complete_quest(self, quest_key: str) -> None:
        """Complete a quest: grant rewards, move to completed list."""
        template = QUEST_TEMPLATES.get(quest_key, {})
        self.active_quests = [q for q in self.active_quests if q["key"] != quest_key]
        self.completed_quests.append(quest_key)
        xp = template.get("xp_reward", 0)
        if xp:
            self.gain_xp(xp)
        reward_item = template.get("item_reward")
        if reward_item:
            item = dict(reward_item)
            item["id"] = f"{item['id']}_{uuid.uuid4().hex[:4]}"
            self.add_item(item)
        # Post quest completion to shared boards
        title = template.get("title", quest_key)
        self._post_board_message("realm_quests", "Player", f"Completed quest: {title}")
        self._submit_leaderboard("realm_quests_completed", "Player", len(self.completed_quests))

    def check_turn_quests(self) -> List[Dict]:
        """Called each turn to advance turn-based quest progress."""
        return self._check_quest_progress("turn")

    def get_available_quests(self) -> List[Dict[str, str]]:
        """Get quests the player can accept."""
        active_keys = {q["key"] for q in self.active_quests}
        return [
            {"key": k, "title": t["title"], "description": t["description"]}
            for k, t in QUEST_TEMPLATES.items()
            if k not in self.completed_quests and k not in active_keys
        ]

    # ── Location System ──

    def get_location_info(self) -> Dict[str, Any]:
        """Return info about the player's current location."""
        loc = REALM_LOCATIONS.get(self.current_location, {})
        return {
            "location_key": self.current_location,
            "name": loc.get("name", self.current_location),
            "description": loc.get("description", ""),
            "connections": loc.get("connections", []),
            "connections_info": [
                {"key": c, "name": REALM_LOCATIONS[c]["name"]}
                for c in loc.get("connections", [])
                if c in REALM_LOCATIONS
            ],
        }

    def move_to_location(self, destination: str) -> Dict[str, Any]:
        """Move the player to a connected location. May trigger a random encounter."""
        if self.combat and self.combat.active:
            return {"error": "Cannot move while in combat"}
        if destination not in REALM_LOCATIONS:
            return {"error": f"Unknown location: {destination}"}
        current = REALM_LOCATIONS.get(self.current_location, {})
        if destination not in current.get("connections", []):
            return {"error": f"Cannot reach '{REALM_LOCATIONS[destination]['name']}' from here. "
                    f"Connected locations: {', '.join(current.get('connections', []))}"}
        with self._lock:
            old_location = self.current_location
            self.current_location = destination
        dest_info = REALM_LOCATIONS[destination]
        result: Dict[str, Any] = {
            "moved": True,
            "from": old_location,
            "from_name": REALM_LOCATIONS.get(old_location, {}).get("name", old_location),
            "to": destination,
            "to_name": dest_info["name"],
            "description": dest_info["description"],
            "connections": [
                {"key": c, "name": REALM_LOCATIONS[c]["name"]}
                for c in dest_info.get("connections", [])
                if c in REALM_LOCATIONS
            ],
        }
        # Random encounter check
        encounter_chance = dest_info.get("encounter_chance", 0.3)
        if random.random() < encounter_chance and dest_info.get("enemy_pool"):
            enemy_key = random.choice(dest_info["enemy_pool"])
            combat = self.start_combat(enemy_key)
            result["encounter"] = combat
            result["encounter_enemy"] = enemy_key
        # Advance turn-based quest progress
        quest_updates = self._check_quest_progress("turn")
        if quest_updates:
            result["quest_updates"] = quest_updates
        return result

    # ── SharedBoard helpers ──

    @staticmethod
    def _submit_leaderboard(board_id: str, player: str, score: int) -> None:
        """Submit to SharedBoard leaderboard (fire-and-forget)."""
        try:
            from engine.mcp.shared_boards import SharedBoardManager
            mgr = SharedBoardManager.instance()
            mgr.submit_score(board_id, player, score)
        except Exception:
            pass

    @staticmethod
    def _post_board_message(board_id: str, author: str, content: str) -> None:
        """Post to SharedBoard message board (fire-and-forget)."""
        try:
            from engine.mcp.shared_boards import SharedBoardManager
            mgr = SharedBoardManager.instance()
            mgr.post_message(board_id, author, content, author_name=author)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
#  COMBAT ENCOUNTER
# ═══════════════════════════════════════════════════════════════

class CombatEncounter:
    """Tracks state for a single turn-based combat encounter."""

    def __init__(self, enemy_key: str, template: Dict[str, Any]):
        self.enemy_key = enemy_key
        self.template = template
        self.enemy_name = template.get("name", "Unknown")
        self.enemy_hp = template.get("hp", 20)
        self.enemy_max_hp = self.enemy_hp
        self.active = True
        self.turn = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enemy_key": self.enemy_key,
            "enemy_name": self.enemy_name,
            "enemy_hp": self.enemy_hp,
            "enemy_max_hp": self.enemy_max_hp,
            "active": self.active,
            "turn": self.turn,
        }


# ═══════════════════════════════════════════════════════════════
#  MURDER MYSTERY STATE
# ═══════════════════════════════════════════════════════════════

class MurderMysteryState:
    """State tracker for the Murder Mystery Party sub-module."""

    def __init__(self):
        self.active = False
        self.phase: str = "setup"  # setup → party → investigation → resolution
        self.phase_start: float = 0.0
        self.phase_time_limit: float = 0.0

        # Roles
        npcs = list(MURDER_NPCS)
        random.shuffle(npcs)
        self.npcs = npcs
        self.murderer_id: str = npcs[0]["id"]
        self.victim_id: str = npcs[1]["id"]
        self.weapon: str = random.choice(MURDER_WEAPONS)
        self.room: str = random.choice(MURDER_ROOMS)

        # Evidence
        self.clues_found: List[Dict[str, str]] = []
        self.alibis: Dict[str, str] = {}
        self.interrogations: List[Dict[str, Any]] = []

        # Accusations
        self.accusations_remaining: int = 3
        self.accusations: List[Dict[str, Any]] = []
        self.resolved: bool = False
        self.detective_won: bool = False

    def start_party_phase(self) -> Dict[str, Any]:
        self.active = True
        self.phase = "party"
        self.phase_start = time.time()
        self.phase_time_limit = 300.0  # 5 minutes
        # Generate alibis for non-murderer NPCs
        for npc in self.npcs:
            if npc["id"] != self.murderer_id and npc["id"] != self.victim_id:
                self.alibis[npc["id"]] = f"{npc['name']} was in the {random.choice(MURDER_ROOMS)}."
        return {"phase": "party", "victim": self.npcs[1]["name"], "time_limit": 300}

    def start_investigation_phase(self) -> Dict[str, Any]:
        self.phase = "investigation"
        self.phase_start = time.time()
        self.phase_time_limit = 900.0  # 15 minutes
        return {"phase": "investigation", "time_limit": 900, "accusations_remaining": 3}

    def phase_time_remaining(self) -> float:
        if self.phase_start <= 0:
            return -1.0
        return max(0.0, self.phase_time_limit - (time.time() - self.phase_start))

    def add_clue(self, clue: Dict[str, str]) -> None:
        self.clues_found.append(clue)

    def interrogate(self, npc_id: str, question: str, answer: str) -> None:
        self.interrogations.append({"npc_id": npc_id, "question": question, "answer": answer, "time": time.time()})

    def accuse(self, suspect_id: str, weapon: str, room: str) -> Dict[str, Any]:
        if self.accusations_remaining <= 0:
            return {"allowed": False, "reason": "No accusations left"}
        self.accusations_remaining -= 1
        correct_suspect = suspect_id == self.murderer_id
        correct_weapon = weapon == self.weapon
        correct_room = room == self.room
        won = correct_suspect and correct_weapon and correct_room
        result = {
            "allowed": True,
            "correct_suspect": correct_suspect,
            "correct_weapon": correct_weapon,
            "correct_room": correct_room,
            "won": won,
            "remaining": self.accusations_remaining,
        }
        self.accusations.append(result)
        if won:
            self.resolved = True
            self.detective_won = True
        elif self.accusations_remaining <= 0:
            self.resolved = True
            self.detective_won = False
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "phase": self.phase,
            "phase_time_remaining": self.phase_time_remaining(),
            "victim": next((n["name"] for n in self.npcs if n["id"] == self.victim_id), ""),
            "npcs": [{"id": n["id"], "name": n["name"]} for n in self.npcs if n["id"] != self.victim_id],
            "clues_found": len(self.clues_found),
            "interrogations": len(self.interrogations),
            "accusations_remaining": self.accusations_remaining,
            "resolved": self.resolved,
            "detective_won": self.detective_won,
        }

    def get_director_brief(self) -> str:
        """Generate a brief for the Director LLM about the current murder state."""
        murderer_name = next((n["name"] for n in self.npcs if n["id"] == self.murderer_id), "Unknown")
        victim_name = next((n["name"] for n in self.npcs if n["id"] == self.victim_id), "Unknown")
        lines = [
            f"[MURDER MYSTERY — CONFIDENTIAL DIRECTOR INFO]",
            f"Phase: {self.phase} | Time remaining: {self.phase_time_remaining():.0f}s",
            f"Murderer: {murderer_name} | Weapon: {self.weapon} | Room: {self.room}",
            f"Victim: {victim_name}",
            f"Clues found: {len(self.clues_found)} | Accusations left: {self.accusations_remaining}",
        ]
        if self.alibis:
            lines.append("Alibis: " + "; ".join(f"{k}: {v}" for k, v in self.alibis.items()))
        return "\n".join(lines)
