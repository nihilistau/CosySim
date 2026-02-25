"""Tavern scene state management — reputation, inventory, quests, atmosphere.

Centralises all mutable game state so the scene file stays focused on
Flask routing and LLM orchestration.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
#  Enums
# ---------------------------------------------------------------------------

class Atmosphere(Enum):
    QUIET = "quiet"
    LIVELY = "lively"
    ROWDY = "rowdy"
    BRAWL = "brawl"


class TimeOfDay(Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    MIDNIGHT = "midnight"


class QuestStatus(Enum):
    AVAILABLE = "available"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
#  Data classes
# ---------------------------------------------------------------------------

@dataclass
class DrinkItem:
    id: str
    name: str
    price: int
    description: str
    effects: Dict[str, int] = field(default_factory=dict)


@dataclass
class Quest:
    id: str
    title: str
    giver: str
    description: str
    objective: str
    reward_gold: int
    reward_reputation: Dict[str, int] = field(default_factory=dict)
    status: QuestStatus = QuestStatus.AVAILABLE
    progress: int = 0
    max_progress: int = 1


@dataclass
class RumorEntry:
    id: str
    text: str
    source: str
    unlocks_quest: Optional[str] = None
    heard: bool = False


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

DRINKS_MENU: List[DrinkItem] = [
    DrinkItem("ale", "Dragon's Breath Ale", 3,
              "A dark, smoky ale that warms the belly.",
              {"warmth": 10, "courage": 5, "clarity": -5}),
    DrinkItem("wine", "Elven Starlight Wine", 8,
              "Pale silver wine imported from the elven courts.",
              {"charm": 10, "clarity": 5, "warmth": 5}),
    DrinkItem("mead", "Honey Mead", 5,
              "Sweet golden mead, a tavern favourite.",
              {"warmth": 15, "happiness": 10, "clarity": -10}),
    DrinkItem("spirits", "Dwarf-Fire Spirits", 12,
              "Burns all the way down. Not for the faint-hearted.",
              {"courage": 20, "clarity": -15, "warmth": 20}),
    DrinkItem("tea", "Herbalist's Calm Tea", 2,
              "A soothing herbal blend. Clears the mind.",
              {"clarity": 15, "warmth": 5, "courage": -5}),
    DrinkItem("mystery", "The Stranger's Draught", 15,
              "Nobody knows what's in it. The stranger orders it nightly.",
              {"mystery": 20, "courage": 10, "clarity": -5}),
]

QUEST_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "lost_heirloom",
        "title": "The Lost Heirloom",
        "giver": "greta",
        "description": "Greta's grandmother's locket was stolen by rats in the cellar.",
        "objective": "Search the cellar and recover the locket",
        "reward_gold": 25,
        "reward_reputation": {"greta": 15, "bard": 5},
    },
    {
        "id": "bards_rival",
        "title": "The Bard's Rival",
        "giver": "bard",
        "description": "A rival bard is spreading lies. Gather evidence of plagiarism.",
        "objective": "Find three witnesses who heard the rival steal songs",
        "reward_gold": 20,
        "reward_reputation": {"bard": 20},
        "max_progress": 3,
    },
    {
        "id": "merchant_debt",
        "title": "Collect the Debt",
        "giver": "merchant",
        "description": "A customer owes 50 gold for enchanted goods. Convince them to pay.",
        "objective": "Persuade the debtor to settle their account",
        "reward_gold": 15,
        "reward_reputation": {"merchant": 15, "greta": -5},
    },
    {
        "id": "stranger_errand",
        "title": "A Quiet Favour",
        "giver": "stranger",
        "description": "The stranger needs a sealed letter delivered to the docks at midnight.",
        "objective": "Deliver the letter without reading it",
        "reward_gold": 40,
        "reward_reputation": {"stranger": 25},
    },
    {
        "id": "tavern_brawl",
        "title": "Keep the Peace",
        "giver": "greta",
        "description": "Trouble is brewing between two regulars. Defuse the situation.",
        "objective": "Resolve the conflict before it becomes a full brawl",
        "reward_gold": 10,
        "reward_reputation": {"greta": 20, "bard": 10, "merchant": 5},
    },
]

RUMOR_POOL: List[Dict[str, Any]] = [
    {"id": "r1", "text": "They say the cellar has rats the size of dogs.",
     "source": "greta", "unlocks_quest": "lost_heirloom"},
    {"id": "r2", "text": "A hooded figure has been meeting someone at the docks.",
     "source": "bard", "unlocks_quest": "stranger_errand"},
    {"id": "r3", "text": "The merchant's been complaining about unpaid debts all week.",
     "source": "greta", "unlocks_quest": "merchant_debt"},
    {"id": "r4", "text": "Two regulars have been glaring at each other for hours.",
     "source": "bard", "unlocks_quest": "tavern_brawl"},
    {"id": "r5", "text": "A rival bard passed through town last week, playing suspiciously familiar tunes.",
     "source": "merchant", "unlocks_quest": "bards_rival"},
    {"id": "r6", "text": "The king's tax collector is due any day now.",
     "source": "merchant"},
    {"id": "r7", "text": "Something howls in the forest on moonless nights.",
     "source": "stranger"},
    {"id": "r8", "text": "The wine shipment from the elven lands was late again.",
     "source": "greta"},
]

NPC_PROFILES = {
    "greta": {
        "name": "Greta Ironhearth",
        "role": "Barkeeper",
        "personality": "Warm but no-nonsense. Knows everyone's secrets. Fiercely protective of her tavern.",
        "speech_style": "Direct, motherly, occasional dry humour. Uses tavern metaphors.",
    },
    "bard": {
        "name": "Finnegan Strings",
        "role": "Traveling Bard",
        "personality": "Charismatic storyteller, flirtatious, embellishes everything. Collects rumours.",
        "speech_style": "Flowery, dramatic, breaks into verse. Loves an audience.",
    },
    "merchant": {
        "name": "Durgin Copperscale",
        "role": "Merchant",
        "personality": "Shrewd trader, values fairness, loves haggling. Pragmatic and cautious.",
        "speech_style": "Business-like but fair. Uses trade jargon. Counts coins mid-sentence.",
    },
    "stranger": {
        "name": "The Stranger",
        "role": "Mysterious Figure",
        "personality": "Quiet, observant, dangerous aura. Speaks in riddles. Has hidden agenda.",
        "speech_style": "Sparse, cryptic, measured. Never wastes words. Hints at deeper knowledge.",
    },
}


# ---------------------------------------------------------------------------
#  Tavern State
# ---------------------------------------------------------------------------

class TavernState:
    """Central mutable state for the Tavern scene."""

    def __init__(self) -> None:
        self.gold: int = 50
        self.atmosphere: Atmosphere = Atmosphere.QUIET
        self.time_of_day: TimeOfDay = TimeOfDay.EVENING
        self.turn: int = 0
        self.heat: int = 0  # 0-100, drives atmosphere

        # Per-NPC reputation (0-100, start neutral at 50)
        self.reputation: Dict[str, int] = {
            npc_id: 50 for npc_id in NPC_PROFILES
        }

        # Player stats
        self.stats: Dict[str, int] = {
            "warmth": 50,
            "courage": 50,
            "clarity": 80,
            "charm": 50,
            "happiness": 60,
            "mystery": 0,
        }

        # Inventory (item_id → count)
        self.inventory: Dict[str, int] = {}

        # Active drinks (recent, affect stats)
        self.drinks_consumed: List[str] = []

        # Quests
        self.quests: Dict[str, Quest] = {}
        self._seed_quests()

        # Rumors
        self.rumors: Dict[str, RumorEntry] = {}
        self._seed_rumors()

        # Dice game state
        self.dice_game_active: bool = False
        self.dice_bet: int = 0
        self.dice_score: int = 0

        # NPC presence (which NPCs are in the tavern right now)
        self.npcs_present: List[str] = ["greta", "bard", "merchant"]
        # Stranger appears randomly or by event
        self._stranger_appeared: bool = False

        # Narrative log
        self.narrative: List[Dict[str, Any]] = []

        self._created_at = time.time()

    # -- Seeding --

    def _seed_quests(self) -> None:
        for qt in QUEST_TEMPLATES:
            self.quests[qt["id"]] = Quest(
                id=qt["id"],
                title=qt["title"],
                giver=qt["giver"],
                description=qt["description"],
                objective=qt["objective"],
                reward_gold=qt["reward_gold"],
                reward_reputation=qt.get("reward_reputation", {}),
                max_progress=qt.get("max_progress", 1),
            )

    def _seed_rumors(self) -> None:
        for r in RUMOR_POOL:
            self.rumors[r["id"]] = RumorEntry(
                id=r["id"], text=r["text"], source=r["source"],
                unlocks_quest=r.get("unlocks_quest"),
            )

    # -- Gold --

    def spend_gold(self, amount: int) -> bool:
        if self.gold >= amount:
            self.gold -= amount
            return True
        return False

    def earn_gold(self, amount: int) -> None:
        self.gold += amount

    # -- Stats --

    def adjust_stats(self, **deltas: int) -> Dict[str, int]:
        changed = {}
        for stat, delta in deltas.items():
            if stat in self.stats:
                old = self.stats[stat]
                self.stats[stat] = max(0, min(100, old + delta))
                changed[stat] = self.stats[stat] - old
        return changed

    # -- Reputation --

    def adjust_reputation(self, npc_id: str, delta: int) -> int:
        if npc_id in self.reputation:
            old = self.reputation[npc_id]
            self.reputation[npc_id] = max(0, min(100, old + delta))
            return self.reputation[npc_id] - old
        return 0

    def get_reputation_tier(self, npc_id: str) -> str:
        rep = self.reputation.get(npc_id, 50)
        if rep >= 80:
            return "trusted"
        if rep >= 60:
            return "friendly"
        if rep >= 40:
            return "neutral"
        if rep >= 20:
            return "wary"
        return "hostile"

    # -- Atmosphere --

    def update_atmosphere(self) -> Atmosphere:
        if self.heat >= 80:
            self.atmosphere = Atmosphere.BRAWL
        elif self.heat >= 55:
            self.atmosphere = Atmosphere.ROWDY
        elif self.heat >= 25:
            self.atmosphere = Atmosphere.LIVELY
        else:
            self.atmosphere = Atmosphere.QUIET
        return self.atmosphere

    def adjust_heat(self, delta: int) -> int:
        old = self.heat
        self.heat = max(0, min(100, self.heat + delta))
        self.update_atmosphere()
        return self.heat - old

    # -- Stranger --

    def maybe_stranger_appears(self) -> bool:
        if self._stranger_appeared:
            return False
        if self.time_of_day in (TimeOfDay.EVENING, TimeOfDay.MIDNIGHT):
            if random.random() < 0.3 or self.turn >= 5:
                self._stranger_appeared = True
                self.npcs_present.append("stranger")
                return True
        return False

    # -- Dice game --

    def start_dice_game(self, bet: int) -> bool:
        if not self.spend_gold(bet):
            return False
        self.dice_game_active = True
        self.dice_bet = bet
        self.dice_score = 0
        return True

    def roll_dice(self) -> Dict[str, Any]:
        if not self.dice_game_active:
            return {"error": "No dice game active"}
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        self.dice_score += total
        result = {"die1": d1, "die2": d2, "total": total, "running_score": self.dice_score}

        # Doubles = bonus roll
        if d1 == d2:
            result["doubles"] = True
            result["message"] = f"Doubles! Roll again. Running total: {self.dice_score}"
        elif self.dice_score >= 21:
            # Bust
            self.dice_game_active = False
            result["bust"] = True
            result["message"] = f"Bust! Score {self.dice_score} exceeds 21. You lose {self.dice_bet} gold."
        else:
            result["can_hold"] = True
            result["message"] = f"Score: {self.dice_score}. Roll again or hold?"
        return result

    def hold_dice(self) -> Dict[str, Any]:
        if not self.dice_game_active:
            return {"error": "No dice game active"}
        house = random.randint(2, 12) + random.randint(1, 6)  # House rolls 3 dice
        self.dice_game_active = False
        if self.dice_score > house:
            winnings = self.dice_bet * 2
            self.earn_gold(winnings)
            return {"player": self.dice_score, "house": house, "won": True,
                    "winnings": winnings, "message": f"You win! {winnings} gold earned."}
        elif self.dice_score == house:
            self.earn_gold(self.dice_bet)
            return {"player": self.dice_score, "house": house, "tie": True,
                    "message": "Tie — bet returned."}
        else:
            return {"player": self.dice_score, "house": house, "won": False,
                    "message": f"House wins with {house}. You lose {self.dice_bet} gold."}

    # -- Quests --

    def accept_quest(self, quest_id: str) -> Optional[Quest]:
        q = self.quests.get(quest_id)
        if q and q.status == QuestStatus.AVAILABLE:
            q.status = QuestStatus.ACTIVE
            return q
        return None

    def advance_quest(self, quest_id: str, amount: int = 1) -> Optional[Quest]:
        q = self.quests.get(quest_id)
        if q and q.status == QuestStatus.ACTIVE:
            q.progress = min(q.max_progress, q.progress + amount)
            if q.progress >= q.max_progress:
                q.status = QuestStatus.COMPLETED
                self.earn_gold(q.reward_gold)
                for npc, rep in q.reward_reputation.items():
                    self.adjust_reputation(npc, rep)
            return q
        return None

    def get_available_quests(self) -> List[Quest]:
        return [q for q in self.quests.values() if q.status == QuestStatus.AVAILABLE]

    def get_active_quests(self) -> List[Quest]:
        return [q for q in self.quests.values() if q.status == QuestStatus.ACTIVE]

    # -- Rumors --

    def hear_rumor(self) -> Optional[RumorEntry]:
        unheard = [r for r in self.rumors.values() if not r.heard]
        if not unheard:
            return None
        rumor = random.choice(unheard)
        rumor.heard = True
        if rumor.unlocks_quest and rumor.unlocks_quest in self.quests:
            quest = self.quests[rumor.unlocks_quest]
            if quest.status == QuestStatus.AVAILABLE:
                pass  # Quest now discoverable
        return rumor

    # -- Narrative --

    def log_event(self, text: str, event_type: str = "narrative") -> None:
        self.narrative.append({
            "text": text, "type": event_type,
            "turn": self.turn, "time": time.time(),
        })
        if len(self.narrative) > 50:
            self.narrative = self.narrative[-50:]

    # -- Serialisation --

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "gold": self.gold,
            "atmosphere": self.atmosphere.value,
            "time_of_day": self.time_of_day.value,
            "turn": self.turn,
            "heat": self.heat,
            "reputation": dict(self.reputation),
            "stats": dict(self.stats),
            "inventory": dict(self.inventory),
            "npcs_present": list(self.npcs_present),
            "quests": {
                qid: {"title": q.title, "status": q.status.value,
                       "progress": q.progress, "max": q.max_progress}
                for qid, q in self.quests.items()
            },
            "rumors_heard": sum(1 for r in self.rumors.values() if r.heard),
            "rumors_total": len(self.rumors),
            "dice_game_active": self.dice_game_active,
            "narrative_count": len(self.narrative),
        }
