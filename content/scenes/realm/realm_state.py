"""
The Realm — Game State Engine
==============================

Thread-safe state management for the LitRPG visual novel using the MCP
GameState store. Manages:

* Player stats, inventory, skills
* Character classes with unique stat bonuses and abilities
* Director personality & patience meter
* Murder mystery phase tracking
* Memory echoes (past-run hints)
* Time limits & win conditions
* 12-quest library with branching narrative paths

Version: v1.49.5 [2026-03-22]

Change Log:
    v1.49.5 [2026-03-22] — Character classes (4) + branching quest library (12 quests, 3 tiers)
    v1.49.3 [2026-03-22] — Structured logging context
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
#  CHARACTER CLASSES
# ═══════════════════════════════════════════════════════════════

# v1.49.5 [2026-03-22] — Character classes with unique stat bonuses and abilities
CHARACTER_CLASSES: Dict[str, Dict[str, Any]] = {
    "fighter": {
        "name": "Fighter",
        "description": "A battle-hardened warrior. Strong, tough, straightforward.",
        "stat_bonus": {"STR": 2, "CON": 1, "DEX": 0, "INT": 0, "WIS": 0, "CHA": 0},
        "abilities": [
            {"name": "Shield Wall", "description": "+3 DEF for 2 turns", "cooldown": 3, "type": "defensive"},
            {"name": "Cleave", "description": "Hit all enemies for 75% damage", "cooldown": 4, "type": "offensive"},
        ],
    },
    "rogue": {
        "name": "Rogue",
        "description": "Quick, cunning, and deadly from the shadows.",
        "stat_bonus": {"DEX": 2, "INT": 1, "STR": 0, "CON": 0, "WIS": 0, "CHA": 0},
        "abilities": [
            {"name": "Backstab", "description": "2x damage from stealth (first strike only)", "cooldown": 2, "type": "offensive"},
            {"name": "Pickpocket", "description": "Steal a random item from enemy", "cooldown": 5, "type": "utility"},
        ],
    },
    "cleric": {
        "name": "Cleric",
        "description": "A healer and protector guided by faith.",
        "stat_bonus": {"WIS": 2, "CHA": 1, "STR": 0, "DEX": 0, "CON": 0, "INT": 0},
        "abilities": [
            {"name": "Heal", "description": "Restore 20 HP", "cooldown": 3, "type": "healing"},
            {"name": "Turn Undead", "description": "Fear effect on undead enemies (skip turn)", "cooldown": 4, "type": "offensive"},
        ],
    },
    "mage": {
        "name": "Mage",
        "description": "Master of arcane power. Fragile but devastating.",
        "stat_bonus": {"INT": 2, "WIS": 1, "STR": 0, "DEX": 0, "CON": 0, "CHA": 0},
        "abilities": [
            {"name": "Fireball", "description": "25 damage to all enemies", "cooldown": 4, "type": "offensive"},
            {"name": "Arcane Shield", "description": "Absorb next 15 damage", "cooldown": 3, "type": "defensive"},
        ],
    },
}

# Mapping from class stat abbreviation to game stat key
# Why: CHARACTER_CLASSES use D&D-style abbreviations (STR, DEX) but
# DEFAULT_STATS uses full names (strength, agility). This bridge lets
# apply_class_bonus() translate correctly.
_CLASS_STAT_MAP: Dict[str, str] = {
    "STR": "strength",
    "CON": "max_hp",     # CON bonus adds to max HP pool (10 HP per point)
    "DEX": "agility",
    "INT": "intellect",
    "WIS": "max_mp",     # WIS bonus adds to max MP pool (10 MP per point)
    "CHA": "charisma",
}


# ═══════════════════════════════════════════════════════════════
#  QUEST LIBRARY — 12 QUESTS WITH BRANCHING PATHS
# ═══════════════════════════════════════════════════════════════

# v1.49.5 [2026-03-22] — 12 narrative quests across 3 tiers with branching choices
# Each quest has 2-3 branches that lead to different outcomes and bonus rewards.
# The quest system feeds into the Director pipeline — branches inform the LLM narration.

QUEST_LIBRARY: Dict[str, Dict[str, Any]] = {

    # ── Tier 1 — Beginner (levels 1-3) ──────────────────────────────

    "missing_merchant": {
        "name": "The Missing Merchant", "tier": 1, "xp": 50, "gold": 100,
        "intro": "A merchant named Aldric hasn't returned from the forest trail. His wife begs you to find him.",
        "branches": {
            "search_forest": {
                "description": "Search the forest trail",
                "outcome": "You find Aldric tied up by bandits. Combat encounter with 3 bandits.",
                "reward_bonus": {"gold": 50},
            },
            "ask_tavern": {
                "description": "Ask around the tavern first",
                "outcome": "A drunk mentions seeing Aldric gambling at the crossroads. He's alive but lost everything. No combat.",
                "reward_bonus": {"xp": 25},
            },
            "follow_tracks": {
                "description": "Follow the wagon tracks",
                "outcome": "The tracks lead to a hidden cave. Aldric made a deal with smugglers. You can join them or turn them in.",
                "reward_bonus": {"item": "smuggler_map"},
            },
        },
    },

    "haunted_well": {
        "name": "The Haunted Well", "tier": 1, "xp": 40, "gold": 75,
        "intro": "Children have been hearing whispers from the village well at night. The elders fear a restless spirit.",
        "branches": {
            "descend_well": {
                "description": "Climb down into the well",
                "outcome": "You discover an underground chamber with a trapped ghost. She was a healer, murdered and hidden here decades ago. Free her spirit or bind it as a servant.",
                "reward_bonus": {"item": "spectral_lantern"},
            },
            "research_history": {
                "description": "Visit the village records",
                "outcome": "You find records of a woman who vanished 40 years ago. The current mayor's father was the last person to see her alive. Confronting the mayor opens a political subplot.",
                "reward_bonus": {"xp": 30},
            },
            "set_trap": {
                "description": "Set a trap at the well at midnight",
                "outcome": "The whispers are actually a colony of rare cave sprites using the well as an echo chamber. They're harmless — and valuable to the right buyer.",
                "reward_bonus": {"gold": 100},
            },
        },
    },

    "rat_kings_court": {
        "name": "The Rat King's Court", "tier": 1, "xp": 45, "gold": 60,
        "intro": "The cellar rats have organized. The innkeeper swears he saw them marching in formation. Something intelligent is leading them.",
        "branches": {
            "exterminate": {
                "description": "Poison the cellar and kill them all",
                "outcome": "The poison works, but you discover the rats were guarding a clutch of eggs from a much larger creature below. Now nothing stands between it and the surface.",
                "reward_bonus": {"xp": 20},
            },
            "negotiate": {
                "description": "Attempt to communicate with the Rat King",
                "outcome": "The Rat King is a polymorphed wizard trapped in rat form. He offers powerful knowledge in exchange for lifting his curse — which requires a rare ingredient from the mountain.",
                "reward_bonus": {"item": "rat_kings_signet"},
            },
            "observe": {
                "description": "Watch from hiding to learn their patterns",
                "outcome": "You discover the rats are stockpiling a glowing mineral. They're not attacking anyone — they're building something. An alchemist would pay well for samples.",
                "reward_bonus": {"gold": 80},
            },
        },
    },

    "the_toll_bridge": {
        "name": "The Toll Bridge", "tier": 1, "xp": 35, "gold": 80,
        "intro": "A troll has claimed the only bridge to the eastern farmlands. Farmers can't reach their fields. But the troll says the bridge is rightfully his — he built it.",
        "branches": {
            "fight_troll": {
                "description": "Challenge the troll to combat",
                "outcome": "The troll is surprisingly tough but honorable. If you win, he leaves peacefully. If you lose, he takes your weapon as a toll and lets you cross anyway.",
                "reward_bonus": {"xp": 30},
            },
            "find_deed": {
                "description": "Investigate whether the troll really built the bridge",
                "outcome": "He did build it — 200 years ago. The village's founding charter actually acknowledges troll bridge rights. You can negotiate a fair toll or expose the village council's dishonesty.",
                "reward_bonus": {"gold": 50},
            },
            "build_alternative": {
                "description": "Help the farmers build a second crossing",
                "outcome": "While building, you discover an ancient ford the river has exposed. Below the waterline: ruins of a pre-human civilization. The troll knows more than he's letting on.",
                "reward_bonus": {"item": "ancient_river_stone"},
            },
        },
    },

    # ── Tier 2 — Intermediate (levels 4-7) ──────────────────────────

    "the_clockwork_plague": {
        "name": "The Clockwork Plague", "tier": 2, "xp": 100, "gold": 200,
        "intro": "People in the mining district are turning mechanical — skin becoming brass, eyes becoming gears. It's spreading. The Artificers' Guild claims innocence.",
        "branches": {
            "quarantine": {
                "description": "Enforce a quarantine and study the afflicted",
                "outcome": "The plague is caused by nanite-like constructs in the water supply. They're not random — they're upgrading people according to a blueprint. Someone designed this. Following the signal leads to an abandoned workshop beneath the guild.",
                "reward_bonus": {"xp": 50, "item": "nanite_sample"},
            },
            "infiltrate_guild": {
                "description": "Go undercover in the Artificers' Guild",
                "outcome": "The Guild is split: a radical faction believes flesh is weakness and has been seeding the water. The moderates want to stop them but fear a civil war. You must choose a side — or play both.",
                "reward_bonus": {"gold": 150},
            },
            "find_patient_zero": {
                "description": "Track down whoever was first afflicted",
                "outcome": "Patient zero is a child who found a brass music box in the old mines. The box is an artifact from an ancient machine civilization. The 'plague' is actually a calling — the machines want their people back.",
                "reward_bonus": {"item": "clockwork_heart"},
            },
        },
    },

    "the_mirrors_lie": {
        "name": "The Mirror's Lie", "tier": 2, "xp": 120, "gold": 175,
        "intro": "A noble's enchanted mirror has begun showing impossible reflections — scenes of a world where the noble made different choices. Now his reflection is trying to switch places.",
        "branches": {
            "destroy_mirror": {
                "description": "Shatter the mirror before the switch happens",
                "outcome": "Destroying the mirror releases the reflection as a shadow-entity. It's furious, powerful, and knows all the noble's secrets. It begins blackmailing the entire court. You created a bigger problem.",
                "reward_bonus": {"xp": 60},
            },
            "enter_mirror": {
                "description": "Step into the mirror world",
                "outcome": "The mirror world is a version of the realm where a great war was averted. It's better in many ways — but the cost was terrible. The reflection-noble sacrificed his family to stop the war. He wants a second chance at happiness. Let him cross, or seal the portal?",
                "reward_bonus": {"item": "mirror_shard"},
            },
            "negotiate_terms": {
                "description": "Broker a deal between the noble and his reflection",
                "outcome": "Both versions agree to merge — combining the best of both timelines. The process requires a rare ritual component and a willing sacrifice of one memory from each. The merged noble becomes unnervingly wise and grateful.",
                "reward_bonus": {"gold": 200, "xp": 40},
            },
        },
    },

    "the_singing_dead": {
        "name": "The Singing Dead", "tier": 2, "xp": 110, "gold": 150,
        "intro": "Every full moon, the cemetery sings. Beautiful harmonies rise from the graves. The priests call it an abomination, but the music heals the sick who listen.",
        "branches": {
            "silence_graves": {
                "description": "Perform the rites to silence the dead",
                "outcome": "The singing stops — but so does the healing. A child who was recovering from plague relapses. The dead weren't singing for themselves; they were singing for the living. The priests are hiding something about why the dead have this power.",
                "reward_bonus": {"xp": 50},
            },
            "join_chorus": {
                "description": "Visit the cemetery during the full moon and listen",
                "outcome": "The dead sing a story: a bard buried here centuries ago made a pact with a god of mercy. Her song would heal as long as someone remembered her name. No one does anymore. Find her name, and the song becomes permanent.",
                "reward_bonus": {"item": "song_of_mercy_scroll"},
            },
            "follow_melody": {
                "description": "Trace the melody to its source underground",
                "outcome": "Beneath the cemetery is a crystalline cave where sound resonates perfectly. The bard's bones rest here, wrapped around a divine instrument. Taking the instrument stops the automatic singing but lets YOU play healing songs.",
                "reward_bonus": {"item": "bards_lyre"},
            },
        },
    },

    "the_debt_collector": {
        "name": "The Debt Collector", "tier": 2, "xp": 90, "gold": 250,
        "intro": "A shadowy figure called 'The Ledger' is collecting on debts nobody remembers making. People are paying with years of their life. The contracts are magically binding — and your name is in his book.",
        "branches": {
            "pay_debt": {
                "description": "Negotiate your debt and pay it",
                "outcome": "Your debt is 7 years of life — but The Ledger offers an alternative. Collect three other debts for him, and yours is forgiven. The three debtors are a beggar, a queen, and a dragon. Each has a reason they can't pay.",
                "reward_bonus": {"gold": 100},
            },
            "steal_ledger": {
                "description": "Attempt to steal The Ledger's book",
                "outcome": "The book is alive — it screams when touched and The Ledger appears instantly. But you notice the book has a page about The Ledger himself. He owes a debt too — to Death. His entire operation is him trying to avoid his own reckoning.",
                "reward_bonus": {"xp": 50, "item": "page_of_debts"},
            },
            "expose_fraud": {
                "description": "Investigate whether the contracts are truly legitimate",
                "outcome": "The contracts are real — but the debts were inherited. Your ancestor made a deal during a famine: food for the village in exchange for a future debt from each bloodline. The Ledger is just enforcing a 300-year-old promise. Breaking it would undo the magic that saved the village.",
                "reward_bonus": {"gold": 150, "xp": 30},
            },
        },
    },

    # ── Tier 3 — Advanced (levels 8+) ───────────────────────────────

    "the_throne_of_echoes": {
        "name": "The Throne of Echoes", "tier": 3, "xp": 200, "gold": 400,
        "intro": "The shattered throne whispers to those who approach. Each shard contains the consciousness of a dead king. Reassemble the throne to gain ultimate power — or let the kings rest and lose the only weapon against the coming darkness.",
        "branches": {
            "reassemble": {
                "description": "Gather all shards and rebuild the throne",
                "outcome": "The kings' consciousnesses merge into a gestalt intelligence that offers to advise you — but they demand sacrifices. One king was a tyrant, one was a saint, one was a madman. Their conflicting advice will tear at your sanity unless you can silence two of them.",
                "reward_bonus": {"item": "throne_shard_crown", "xp": 100},
            },
            "destroy_shards": {
                "description": "Destroy the shards to free the dead kings",
                "outcome": "The kings' spirits are released. The saint blesses you before departing. The madman curses you. The tyrant lingers — he has nowhere to go. He offers to haunt your enemies in exchange for a vessel to inhabit. Do you trust a dead tyrant?",
                "reward_bonus": {"gold": 300},
            },
            "use_one_shard": {
                "description": "Take only the shard of the wisest king",
                "outcome": "The shard of King Alderon the Wise bonds with you. His ghost becomes a permanent advisor — calm, strategic, but haunted by guilt. He tells you the throne was shattered on purpose. The real threat isn't outside the realm — it's inside the shards themselves.",
                "reward_bonus": {"item": "alderens_wisdom", "xp": 75},
            },
        },
    },

    "the_gods_wager": {
        "name": "The God's Wager", "tier": 3, "xp": 250, "gold": 350,
        "intro": "Two gods are betting on your life. The God of Order bet you'll follow the prophecy. The God of Chaos bet you'll defy it. Both are offering you power. Accepting either enrages the other.",
        "branches": {
            "accept_order": {
                "description": "Accept the God of Order's blessing",
                "outcome": "You gain incredible power — but the prophecy locks in. Every future event becomes fated. You know exactly when you'll die (turn 100). But every action until then succeeds perfectly. Is a perfect life worth a known ending?",
                "reward_bonus": {"xp": 150, "item": "seal_of_order"},
            },
            "accept_chaos": {
                "description": "Accept the God of Chaos's blessing",
                "outcome": "Reality warps around you. Random events intensify. Enemies become allies, allies become enemies, gold rains from the sky one moment and turns to ash the next. You're untouchable — but everyone around you suffers from the instability.",
                "reward_bonus": {"gold": 500, "item": "chaos_brand"},
            },
            "reject_both": {
                "description": "Refuse both gods and forge your own path",
                "outcome": "Both gods are furious — but a third entity notices your defiance. The Forgotten God, erased from all records, whispers: 'Finally, someone who won't play their game.' It offers you the one thing the other gods can't — freedom from the game itself.",
                "reward_bonus": {"item": "forgotten_gods_eye", "xp": 200},
            },
        },
    },

    "the_last_library": {
        "name": "The Last Library", "tier": 3, "xp": 180, "gold": 300,
        "intro": "The world's last library is burning. Inside are the only copies of spells, histories, and prophecies that could save the realm. You can save some — but not all. What matters most?",
        "branches": {
            "save_spells": {
                "description": "Rush to the arcane wing and save the spellbooks",
                "outcome": "You rescue 12 legendary spellbooks, including the lost art of resurrection. But the history wing burns — and with it, the only record of who built the shattered throne and why. Mages worship you. Historians despair. Some spells should have stayed lost.",
                "reward_bonus": {"item": "resurrection_tome", "xp": 80},
            },
            "save_histories": {
                "description": "Prioritize the historical records and prophecies",
                "outcome": "You save the complete history of the realm — including a terrifying truth. The 'realm' is a prison. The shattered throne was a lock. The darkness outside isn't invading — it's the real world trying to break in. Everything you know is a lie.",
                "reward_bonus": {"xp": 120, "item": "truth_codex"},
            },
            "save_people": {
                "description": "Forget the books — save the trapped scholars",
                "outcome": "You rescue 8 scholars, including the last living keeper of oral history. She knows things no book contains — living knowledge passed down for millennia. She tells you: the library fire wasn't an accident. Someone wants this knowledge destroyed before you find it.",
                "reward_bonus": {"gold": 200, "xp": 60},
            },
        },
    },

    "the_hollow_crown": {
        "name": "The Hollow Crown", "tier": 3, "xp": 300, "gold": 500,
        "intro": "You've been offered the crown. The realm needs a ruler. But the crown is cursed — every monarch who wore it lost themselves within a year, consumed by the crown's ancient intelligence. Yet without a ruler, civil war is inevitable.",
        "branches": {
            "wear_crown": {
                "description": "Accept the crown and fight its influence",
                "outcome": "The crown's intelligence is not malevolent — it's the accumulated wisdom (and trauma) of every past ruler. It tries to override your personality not from malice but from habit. You can coexist with it, but it means hearing the whispers of 400 dead monarchs forever. The realm stabilizes under your rule.",
                "reward_bonus": {"item": "hollow_crown", "xp": 200},
            },
            "destroy_crown": {
                "description": "Destroy the crown and establish a republic",
                "outcome": "The crown shatters and releases 400 ghosts, each with unfinished business. The realm erupts into temporary chaos as spectral kings try to reclaim their old territories. But once they fade, the people are truly free for the first time. Building a republic from nothing is the hardest quest of all.",
                "reward_bonus": {"gold": 400, "xp": 100},
            },
            "find_worthy": {
                "description": "Search for someone strong enough to bear the crown",
                "outcome": "You scour the realm and find one person who can wear it safely: a child born during a solar eclipse with no family name. The crown accepts them without a fight. But a child-ruler needs a regent — and every faction wants to be that regent. You've solved one problem and created a dozen more.",
                "reward_bonus": {"xp": 150, "item": "regents_seal"},
            },
        },
    },
}



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

        # v1.49.5 [2026-03-22] — Character class system
        self.player_class: Optional[str] = None  # Key into CHARACTER_CLASSES
        self.class_abilities: List[Dict[str, Any]] = []  # Active abilities from class
        self.ability_cooldowns: Dict[str, int] = {}  # ability_name → turns until ready

        # v1.49.5 [2026-03-22] — Branching quest library tracking
        self.quest_branches_chosen: Dict[str, str] = {}  # quest_key → branch_key

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
                # v1.49.5 [2026-03-22] — Class & branching quest data
                "player_class": self.player_class,
                "class_info": CHARACTER_CLASSES.get(self.player_class, {}) if self.player_class else None,
                "class_abilities": list(self.class_abilities),
                "ability_cooldowns": dict(self.ability_cooldowns),
                "quest_branches_chosen": dict(self.quest_branches_chosen),
            }

    # ── Time ──

    def time_remaining(self) -> float:
        if self.time_limit_s <= 0 or self.started_at <= 0:
            return -1.0
        elapsed = time.time() - self.started_at
        return max(0.0, self.time_limit_s - elapsed)

    def is_timed_out(self) -> bool:
        return self.time_limit_s > 0 and self.time_remaining() <= 0

    # ── Character Class System ─────────────────────────────────────
    # v1.49.5 [2026-03-22] — Class selection with stat bonuses and abilities
    # CONNECTS: CHARACTER_CLASSES, _CLASS_STAT_MAP, player_stats
    # CALLED BY: /api/game/new (with class_id), /api/game/select_class
    # EMITS: class_selected SocketIO event (via scene)

    def apply_class_bonus(self, class_id: str) -> Dict[str, Any]:
        """Apply a character class to the player, modifying stats and granting abilities.

        Args:
            class_id: Key in CHARACTER_CLASSES (e.g. "fighter", "rogue").

        Returns:
            Dict with class details and applied stat changes, or error dict.
        """
        if class_id not in CHARACTER_CLASSES:
            return {"error": f"Unknown class '{class_id}'. Valid: {list(CHARACTER_CLASSES.keys())}"}

        cls = CHARACTER_CLASSES[class_id]
        applied_bonuses: Dict[str, int] = {}

        with self._lock:
            self.player_class = class_id
            self.class_abilities = list(cls["abilities"])
            self.ability_cooldowns = {a["name"]: 0 for a in cls["abilities"]}

            # Apply stat bonuses via the mapping
            for abbrev, bonus in cls["stat_bonus"].items():
                if bonus == 0:
                    continue
                stat_key = _CLASS_STAT_MAP.get(abbrev)
                if not stat_key:
                    continue
                # CON and WIS bonuses multiply by 10 (HP/MP pools)
                if abbrev in ("CON", "WIS"):
                    actual_bonus = bonus * 10
                else:
                    actual_bonus = bonus
                self.player_stats[stat_key] = self.player_stats.get(stat_key, 0) + actual_bonus
                applied_bonuses[stat_key] = actual_bonus

                # Also bump current HP/MP if max was raised
                if stat_key == "max_hp":
                    self.player_stats["hp"] = self.player_stats.get("hp", 0) + actual_bonus
                elif stat_key == "max_mp":
                    self.player_stats["mp"] = self.player_stats.get("mp", 0) + actual_bonus

        logger.info("Player selected class '%s', bonuses applied: %s", class_id, applied_bonuses)
        return {
            "class_id": class_id,
            "class_info": cls,
            "applied_bonuses": applied_bonuses,
            "abilities": cls["abilities"],
            "player_stats": dict(self.player_stats),
        }

    def use_class_ability(self, ability_name: str) -> Dict[str, Any]:
        """Attempt to use a class ability, respecting cooldowns.

        Args:
            ability_name: Name of the ability to use.

        Returns:
            Dict with ability details and effect description, or error dict.
        """
        if not self.player_class:
            return {"error": "No class selected"}

        ability = next((a for a in self.class_abilities if a["name"] == ability_name), None)
        if not ability:
            return {"error": f"Unknown ability '{ability_name}'"}

        current_cd = self.ability_cooldowns.get(ability_name, 0)
        if current_cd > 0:
            return {"error": f"'{ability_name}' on cooldown ({current_cd} turns remaining)"}

        with self._lock:
            # Set cooldown
            self.ability_cooldowns[ability_name] = ability["cooldown"]

            # Apply ability effects based on type
            effect_description = ability["description"]
            stat_changes: Dict[str, int] = {}

            if ability["type"] == "healing":
                heal_amt = 20
                old_hp = self.player_stats.get("hp", 0)
                max_hp = self.player_stats.get("max_hp", 100)
                self.player_stats["hp"] = min(max_hp, old_hp + heal_amt)
                stat_changes["hp"] = self.player_stats["hp"] - old_hp

            elif ability["type"] == "defensive":
                # Add a temporary status effect
                self.status_effects.append({
                    "name": ability_name,
                    "type": "defense_boost",
                    "value": 3,
                    "turns_remaining": 2,
                })

            # Offensive and utility abilities are narrated by the Director
            # — they don't have direct stat effects here

        return {
            "success": True,
            "ability": ability,
            "effect": effect_description,
            "cooldown_set": ability["cooldown"],
            "stat_changes": stat_changes,
        }

    def tick_ability_cooldowns(self) -> None:
        """Reduce all ability cooldowns by 1 (called each turn)."""
        with self._lock:
            for name in list(self.ability_cooldowns.keys()):
                if self.ability_cooldowns[name] > 0:
                    self.ability_cooldowns[name] -= 1

    # ── Branching Quest Library ────────────────────────────────────
    # v1.49.5 [2026-03-22] — 12-quest library with branching paths
    # CONNECTS: QUEST_LIBRARY, QUEST_TEMPLATES, active_quests
    # CALLED BY: /api/quests/library, /api/quests/branch
    # EMITS: quest_branch_chosen SocketIO event (via scene)

    def get_quest_library(self, tier: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return quests from the branching library, optionally filtered by tier.

        Args:
            tier: If set, only return quests of this tier (1, 2, or 3).

        Returns:
            List of quest dicts with name, tier, intro, and branch summaries.
        """
        quests = []
        for key, quest in QUEST_LIBRARY.items():
            if tier is not None and quest.get("tier") != tier:
                continue
            quests.append({
                "key": key,
                "name": quest["name"],
                "tier": quest["tier"],
                "xp": quest["xp"],
                "gold": quest["gold"],
                "intro": quest["intro"],
                "completed": key in self.completed_quests,
                "active": any(q["key"] == key for q in self.active_quests),
                "branch_chosen": self.quest_branches_chosen.get(key),
                "branches": {
                    bk: {"description": bv["description"]}
                    for bk, bv in quest["branches"].items()
                },
            })
        return quests

    def accept_library_quest(self, quest_key: str) -> Dict[str, Any]:
        """Accept a quest from the branching QUEST_LIBRARY.

        Args:
            quest_key: Key in QUEST_LIBRARY.

        Returns:
            Dict with quest details, or error dict.
        """
        if quest_key not in QUEST_LIBRARY:
            return {"error": f"Unknown library quest '{quest_key}'"}
        if quest_key in self.completed_quests:
            return {"error": "Quest already completed"}
        if any(q["key"] == quest_key for q in self.active_quests):
            return {"error": "Quest already active"}

        template = QUEST_LIBRARY[quest_key]
        quest = {
            "key": quest_key,
            "title": template["name"],
            "description": template["intro"],
            "objective": f"Choose a path and complete the quest (Tier {template['tier']})",
            "progress": 0,
            "target": 1,  # Complete when branch is resolved
            "accepted_turn": self.turn_number,
            "source": "library",
            "tier": template["tier"],
            "branches": list(template["branches"].keys()),
        }
        with self._lock:
            self.active_quests.append(quest)
        return {"accepted": True, "quest": quest}

    def choose_quest_branch(self, quest_key: str, branch_key: str) -> Dict[str, Any]:
        """Choose a branching path for an active library quest.

        Resolves the quest: grants base XP/gold plus branch-specific bonuses.
        Moves the quest to completed and records the branch choice.

        Args:
            quest_key: Key of the active quest.
            branch_key: Key of the chosen branch within the quest.

        Returns:
            Dict with outcome narrative, rewards, and updated state.
        """
        if quest_key not in QUEST_LIBRARY:
            return {"error": f"Unknown library quest '{quest_key}'"}

        quest_data = QUEST_LIBRARY[quest_key]

        # Verify quest is active
        active_quest = next(
            (q for q in self.active_quests if q["key"] == quest_key),
            None,
        )
        if not active_quest:
            return {"error": "Quest not active"}

        if branch_key not in quest_data["branches"]:
            return {"error": f"Unknown branch '{branch_key}'. Valid: {list(quest_data['branches'].keys())}"}

        branch = quest_data["branches"][branch_key]
        rewards: Dict[str, Any] = {
            "xp": quest_data["xp"],
            "gold": quest_data["gold"],
        }

        # Apply branch-specific bonus rewards
        bonus = branch.get("reward_bonus", {})
        rewards["xp"] += bonus.get("xp", 0)
        rewards["gold"] += bonus.get("gold", 0)
        bonus_item = bonus.get("item")

        with self._lock:
            # Record branch choice
            self.quest_branches_chosen[quest_key] = branch_key

            # Grant XP
            xp_result = {}
            if rewards["xp"] > 0:
                xp_result = self.gain_xp(rewards["xp"])

            # Grant gold
            if rewards["gold"] > 0:
                self.gold += rewards["gold"]
                self.player_stats["gold"] = self.player_stats.get("gold", 0) + rewards["gold"]

            # Grant bonus item
            granted_item = None
            if bonus_item:
                item = {
                    "id": f"{bonus_item}_{uuid.uuid4().hex[:4]}",
                    "name": bonus_item.replace("_", " ").title(),
                    "type": "quest_reward",
                    "description": f"Reward from '{quest_data['name']}' ({branch_key})",
                }
                self.add_item(item)
                granted_item = item

            # Complete the quest
            self.active_quests = [q for q in self.active_quests if q["key"] != quest_key]
            self.completed_quests.append(quest_key)

        # Post to shared boards
        self._post_board_message(
            "realm_quests", "Player",
            f"Completed '{quest_data['name']}' via [{branch_key}]",
        )
        self._submit_leaderboard(
            "realm_quests_completed", "Player", len(self.completed_quests),
        )

        return {
            "success": True,
            "quest_name": quest_data["name"],
            "branch": branch_key,
            "outcome": branch["outcome"],
            "description": branch["description"],
            "rewards": rewards,
            "bonus_item": granted_item,
            "leveled_up": xp_result.get("leveled_up", False) if isinstance(xp_result, dict) else False,
            "total_completed": len(self.completed_quests),
        }

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
