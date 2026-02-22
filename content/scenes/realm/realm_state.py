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
        self._lock = threading.Lock()

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
                "murder": self.murder.to_dict() if self.murder else None,
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
