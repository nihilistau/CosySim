"""
CosySim Scene State Manager
============================
Single source of truth for per-scene, per-character state that needs to be
accessible from MCP tools, interceptors, and the game framework simultaneously.

Everything here is designed to survive a hot-reload: all state lives in a
module-level singleton so Flask restarts don't reset clothing mid-striptease.

Classes
-------
ClothingItem        — one wearable item with category, style, worn state
CharacterWardrobe   — ordered clothing inventory for a character
InteractionRecord   — log entry for a completed interaction
TimedAction         — a long-form action playing out over real time
NarrativeLog        — rolling scene continuity journal (last N events)
SceneStateManager   — singleton; everything goes through here

Quick start::

    from engine.mcp.scene_state import get_scene_state_manager

    mgr = get_scene_state_manager()

    # Clothing
    mgr.give_clothing("char_1", ClothingItem("red_bra","Red Satin Bra","bra","red","lingerie"))
    item = mgr.remove_clothing("char_1", "red_bra")          # returns item or None

    # Character stats
    mgr.update_stats("char_1", arousal=+15, happiness=-5)
    snap = mgr.get_stats("char_1")                           # StatsSnapshot

    # Scene state
    mgr.set_scene_state("penthouse", heat_level=35, phase="afterglow")
    state = mgr.get_scene_state("penthouse")

    # Narrative
    mgr.add_narrative("penthouse", "char_1 kisses char_2 softly on the neck.")
    tail = mgr.get_narrative("penthouse", limit=10)

    # Timed actions
    tok = mgr.start_timed_action("char_1", "striptease", duration=45)
    status = mgr.poll_timed_action(tok)
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════
#  CLOTHING
# ══════════════════════════════════════════════════════════════════════

#: Ordered clothing layers — used to decide what comes off first
CLOTHING_LAYER_ORDER = [
    "accessory",
    "outerwear",
    "shoes",
    "top",
    "bottom",
    "full_outfit",
    "bra",
    "underwear",
    "socks",
]

#: Starter wardrobe pools by style theme
WARDROBE_POOLS: Dict[str, List[Dict]] = {
    "casual": [
        {"id": "jeans",        "name": "Dark Skinny Jeans",     "category": "bottom",    "color": "dark blue", "style": "casual"},
        {"id": "crop_top",     "name": "White Crop Top",        "category": "top",       "color": "white",     "style": "casual"},
        {"id": "trainers",     "name": "White Trainers",        "category": "shoes",     "color": "white",     "style": "casual"},
        {"id": "cotton_bra",   "name": "Cotton Bra",            "category": "bra",       "color": "nude",      "style": "casual"},
        {"id": "cotton_pants", "name": "Cotton Underwear",      "category": "underwear", "color": "nude",      "style": "casual"},
        {"id": "hair_tie",     "name": "Hair Tie",              "category": "accessory", "color": "black",     "style": "casual"},
    ],
    "lingerie": [
        {"id": "lace_bra",     "name": "Sheer Lace Bra",        "category": "bra",       "color": "black",     "style": "lingerie"},
        {"id": "lace_thong",   "name": "Lace Thong",            "category": "underwear", "color": "black",     "style": "lingerie"},
        {"id": "silk_robe",    "name": "Silk Robe",             "category": "outerwear", "color": "ivory",     "style": "lingerie"},
        {"id": "heels",        "name": "Strappy Heels",         "category": "shoes",     "color": "black",     "style": "lingerie"},
        {"id": "choker",       "name": "Black Velvet Choker",   "category": "accessory", "color": "black",     "style": "lingerie"},
    ],
    "party": [
        {"id": "mini_dress",   "name": "Red Mini Dress",        "category": "full_outfit","color": "red",      "style": "party"},
        {"id": "party_heels",  "name": "Gold Stilettos",        "category": "shoes",     "color": "gold",      "style": "party"},
        {"id": "strapless_bra","name": "Strapless Push-up Bra", "category": "bra",       "color": "nude",      "style": "party"},
        {"id": "thong",        "name": "Seamless Thong",        "category": "underwear", "color": "nude",      "style": "party"},
        {"id": "clutch",       "name": "Rhinestone Clutch",     "category": "accessory", "color": "silver",    "style": "party"},
        {"id": "earrings",     "name": "Drop Earrings",         "category": "accessory", "color": "gold",      "style": "party"},
    ],
    "nightwear": [
        {"id": "silk_nightgown","name":"Silk Nightgown",         "category": "full_outfit","color": "champagne","style": "nightwear"},
        {"id": "soft_bra",     "name": "Soft Sleep Bra",        "category": "bra",       "color": "blush",     "style": "nightwear"},
        {"id": "sleep_shorts", "name": "Sleep Shorts",          "category": "bottom",    "color": "blush",     "style": "nightwear"},
        {"id": "fluffy_socks", "name": "Fluffy Socks",          "category": "socks",     "color": "white",     "style": "nightwear"},
    ],
    "swimwear": [
        {"id": "bikini_top",   "name": "Bright Bikini Top",     "category": "bra",       "color": "turquoise", "style": "swimwear"},
        {"id": "bikini_bottom","name": "Bikini Bottoms",        "category": "underwear", "color": "turquoise", "style": "swimwear"},
        {"id": "sarong",       "name": "Wrap Sarong",           "category": "outerwear", "color": "white",     "style": "swimwear"},
        {"id": "sandals",      "name": "Flat Sandals",          "category": "shoes",     "color": "tan",       "style": "swimwear"},
    ],
}


@dataclass
class ClothingItem:
    id:         str
    name:       str
    category:   str    # bra, underwear, top, bottom, full_outfit, shoes, outerwear, accessory, socks
    color:      str    = "black"
    style:      str    = "casual"  # casual, lingerie, party, nightwear, swimwear
    is_worn:    bool   = True
    removed_at: float  = 0.0
    removed_by: str    = ""        # character_id who removed it

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def layer(self) -> int:
        try:
            return CLOTHING_LAYER_ORDER.index(self.category)
        except ValueError:
            return 99


@dataclass
class CharacterWardrobe:
    character_id: str
    items: List[ClothingItem] = field(default_factory=list)

    def worn_items(self) -> List[ClothingItem]:
        return sorted([i for i in self.items if i.is_worn], key=lambda x: x.layer)

    def removed_items(self) -> List[ClothingItem]:
        return [i for i in self.items if not i.is_worn]

    def get_item(self, item_id: str) -> Optional[ClothingItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def is_wearing(self, item_id: str) -> bool:
        item = self.get_item(item_id)
        return item is not None and item.is_worn

    def coverage_description(self) -> str:
        worn = self.worn_items()
        if not worn:
            return "wearing nothing"
        cats = {i.category for i in worn}
        if "full_outfit" in cats:
            outfit = next(i for i in worn if i.category == "full_outfit")
            extras = [i.name for i in worn if i.category not in ("full_outfit", "accessory")]
            base = outfit.name
            return base + (f" with {', '.join(extras)}" if extras else "")
        parts = []
        for cat in CLOTHING_LAYER_ORDER:
            matching = [i for i in worn if i.category == cat]
            for m in matching:
                parts.append(m.name)
        return ", ".join(parts) if parts else "wearing nothing"

    def outermost_removable(self) -> Optional[ClothingItem]:
        """Return the topmost layer item (highest layer index = outermost)."""
        worn = self.worn_items()
        if not worn:
            return None
        return max(worn, key=lambda x: x.layer, default=None)

    def add(self, item: ClothingItem) -> None:
        existing = self.get_item(item.id)
        if existing:
            existing.is_worn = True
            existing.removed_at = 0.0
        else:
            self.items.append(item)

    def remove(self, item_id: str, removed_by: str = "") -> Optional[ClothingItem]:
        item = self.get_item(item_id)
        if item and item.is_worn:
            item.is_worn = False
            item.removed_at = time.time()
            item.removed_by = removed_by
            return item
        return None

    def to_dict(self) -> Dict:
        return {
            "character_id":  self.character_id,
            "worn":          [i.to_dict() for i in self.worn_items()],
            "removed":       [i.to_dict() for i in self.removed_items()],
            "description":   self.coverage_description(),
            "is_naked":      len(self.worn_items()) == 0,
        }


# ══════════════════════════════════════════════════════════════════════
#  CHARACTER STATS SNAPSHOT
# ══════════════════════════════════════════════════════════════════════

STAT_KEYS = [
    "arousal", "horniness", "pleasure", "happiness",
    "anger", "fear", "drunkenness", "tiredness",
    "explicitness", "openness", "affection", "dominance",
]


@dataclass
class StatsSnapshot:
    """Extended emotional/physical state (0–100 scale)."""
    arousal:      float = 20.0
    horniness:    float = 15.0
    pleasure:     float = 10.0
    happiness:    float = 60.0
    anger:        float = 5.0
    fear:         float = 5.0
    drunkenness:  float = 0.0
    tiredness:    float = 20.0
    explicitness: float = 60.0
    openness:     float = 65.0
    affection:    float = 50.0
    dominance:    float = 50.0

    def clamp(self) -> "StatsSnapshot":
        for k in STAT_KEYS:
            setattr(self, k, max(0.0, min(100.0, getattr(self, k, 50.0))))
        return self

    def adjust(self, **kwargs) -> "StatsSnapshot":
        for k, v in kwargs.items():
            if k in STAT_KEYS:
                setattr(self, k, getattr(self, k, 50.0) + float(v))
        return self.clamp()

    def to_dict(self) -> Dict:
        return {k: round(getattr(self, k, 50.0), 1) for k in STAT_KEYS}

    def emotional_state_text(self) -> str:
        tags = []
        if self.arousal > 75:   tags.append("intensely aroused")
        elif self.arousal > 45: tags.append("aroused")
        if self.horniness > 70: tags.append("very horny")
        elif self.horniness > 40: tags.append("turned on")
        if self.pleasure > 65:  tags.append("lost in pleasure")
        elif self.pleasure > 35: tags.append("pleasured")
        if self.drunkenness > 70: tags.append("drunk")
        elif self.drunkenness > 35: tags.append("tipsy")
        if self.happiness > 70: tags.append("happy")
        elif self.happiness < 25: tags.append("unhappy")
        if self.anger > 55:     tags.append("angry")
        if self.fear > 50:      tags.append("nervous")
        if self.affection > 75: tags.append("deeply affectionate")
        if self.dominance > 75: tags.append("feeling dominant")
        elif self.dominance < 25: tags.append("feeling submissive")
        return ", ".join(tags) if tags else "calm and present"


# ══════════════════════════════════════════════════════════════════════
#  INTERACTIONS
# ══════════════════════════════════════════════════════════════════════

@dataclass
class InteractionRecord:
    interaction_id: str
    scene_id:       str
    interaction_type: str    # cuddle | kiss | caress | striptease | intimate | deep_talk
    subtype:         str    = ""
    initiator_id:    str    = ""
    target_id:       str    = ""
    description:     str    = ""
    duration_secs:   float  = 0.0
    timestamp:       float  = field(default_factory=time.time)
    stat_effects:    Dict   = field(default_factory=dict)
    phase:           str    = "complete"  # building | peak | afterglow | complete


@dataclass
class TimedAction:
    token:          str
    character_id:   str
    action_type:    str
    description:    str
    start_time:     float   = field(default_factory=time.time)
    duration_secs:  float   = 30.0
    phase_labels:   List[str] = field(default_factory=list)
    complete:       bool    = False
    aborted:        bool    = False

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def progress(self) -> float:
        return min(1.0, self.elapsed / max(1.0, self.duration_secs))

    @property
    def current_phase(self) -> str:
        if self.complete:
            return "complete"
        if not self.phase_labels:
            pct = self.progress
            if pct < 0.33:    return "beginning"
            elif pct < 0.66:  return "building"
            else:             return "peak"
        idx = min(int(self.progress * len(self.phase_labels)), len(self.phase_labels) - 1)
        return self.phase_labels[idx]


# ══════════════════════════════════════════════════════════════════════
#  NARRATIVE LOG
# ══════════════════════════════════════════════════════════════════════

@dataclass
class NarrativeEntry:
    event:        str
    character_id: str   = ""
    timestamp:    float = field(default_factory=time.time)
    entry_type:   str   = "action"  # action | dialogue | environment | system

    def to_dict(self) -> Dict:
        return asdict(self)


class NarrativeLog:
    """Rolling journal — keeps the last ``maxlen`` entries per scene."""

    def __init__(self, maxlen: int = 100) -> None:
        self._maxlen = maxlen
        self._lock   = threading.Lock()
        self._logs: Dict[str, List[NarrativeEntry]] = {}

    def add(self, scene_id: str, event: str, *, character_id: str = "", entry_type: str = "action") -> None:
        entry = NarrativeEntry(event=event, character_id=character_id, entry_type=entry_type)
        with self._lock:
            if scene_id not in self._logs:
                self._logs[scene_id] = []
            self._logs[scene_id].append(entry)
            if len(self._logs[scene_id]) > self._maxlen:
                self._logs[scene_id] = self._logs[scene_id][-self._maxlen:]

    def get(self, scene_id: str, limit: int = 20) -> List[NarrativeEntry]:
        with self._lock:
            entries = self._logs.get(scene_id, [])
            return list(entries[-limit:])

    def get_text(self, scene_id: str, limit: int = 20) -> str:
        entries = self.get(scene_id, limit)
        return "\n".join(e.event for e in entries)

    def clear(self, scene_id: str) -> None:
        with self._lock:
            self._logs.pop(scene_id, None)


# ══════════════════════════════════════════════════════════════════════
#  SCENE STATE MANAGER  (singleton)
# ══════════════════════════════════════════════════════════════════════

class SceneStateManager:
    """
    Global singleton — manages wardrobe, stats, narrative, and timed actions
    for all scenes and characters simultaneously.
    """

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._wardrobes:  Dict[str, CharacterWardrobe] = {}     # keyed by character_id
        self._stats:      Dict[str, StatsSnapshot]     = {}     # keyed by character_id
        self._timed:      Dict[str, TimedAction]       = {}     # keyed by token
        self._interactions: Dict[str, List[InteractionRecord]] = {}  # keyed by scene_id
        self._narrative   = NarrativeLog(maxlen=200)
        self._scene_atmospheres: Dict[str, Dict] = {}           # keyed by scene_id
        self._scene_state: Dict[str, Dict[str, Any]] = {}       # keyed by scene_id

    # ── Wardrobe ──────────────────────────────────────────────────────

    def get_wardrobe(self, character_id: str) -> CharacterWardrobe:
        with self._lock:
            if character_id not in self._wardrobes:
                self._wardrobes[character_id] = CharacterWardrobe(character_id=character_id)
        return self._wardrobes[character_id]

    def initialise_wardrobe(self, character_id: str, style: str = "casual") -> CharacterWardrobe:
        """Give a character a full default wardrobe for their style."""
        wardrobe = CharacterWardrobe(character_id=character_id)
        pool = WARDROBE_POOLS.get(style, WARDROBE_POOLS["casual"])
        for item_data in pool:
            wardrobe.add(ClothingItem(**item_data))
        with self._lock:
            self._wardrobes[character_id] = wardrobe
        return wardrobe

    def add_clothing(self, character_id: str, item: ClothingItem) -> None:
        self.get_wardrobe(character_id).add(item)

    def remove_clothing(self, character_id: str, item_id: str, removed_by: str = "") -> Optional[ClothingItem]:
        return self.get_wardrobe(character_id).remove(item_id, removed_by=removed_by)

    def remove_outermost(self, character_id: str, removed_by: str = "") -> Optional[ClothingItem]:
        """Strip the outermost layer — used for striptease."""
        wardrobe = self.get_wardrobe(character_id)
        item = wardrobe.outermost_removable()
        if item:
            return wardrobe.remove(item.id, removed_by=removed_by)
        return None

    def re_dress(self, character_id: str) -> int:
        """Put all removed items back on.  Returns count re-worn."""
        wardrobe = self.get_wardrobe(character_id)
        count = 0
        for item in wardrobe.items:
            if not item.is_worn:
                item.is_worn = True
                item.removed_at = 0.0
                item.removed_by = ""
                count += 1
        return count

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self, character_id: str) -> StatsSnapshot:
        with self._lock:
            if character_id not in self._stats:
                self._stats[character_id] = StatsSnapshot()
        return self._stats[character_id]

    def _validate_stat_keys(self, values: Dict[str, Any]) -> None:
        unsupported = sorted(k for k in values if k not in STAT_KEYS)
        if unsupported:
            raise ValueError(
                "Unsupported SceneStateManager stats: "
                f"{', '.join(unsupported)}. "
                "Use set_scene_state() for scene-level fields or StateCoordinator "
                "for non-stat character fields."
            )

    def update_stats(self, character_id: str, **deltas) -> StatsSnapshot:
        self._validate_stat_keys(deltas)
        stats = self.get_stats(character_id)
        stats.adjust(**deltas)
        return stats

    def set_stats(self, character_id: str, **values) -> StatsSnapshot:
        self._validate_stat_keys(values)
        stats = self.get_stats(character_id)
        for k, v in values.items():
            setattr(stats, k, float(v))
        stats.clamp()
        return stats

    def reset_stats(self, character_id: str) -> StatsSnapshot:
        with self._lock:
            self._stats[character_id] = StatsSnapshot()
        return self._stats[character_id]

    # ── Timed actions ─────────────────────────────────────────────────

    def start_timed_action(
        self,
        character_id: str,
        action_type: str,
        duration: float = 30.0,
        description: str = "",
        phase_labels: Optional[List[str]] = None,
    ) -> str:
        token = str(uuid.uuid4())[:8]
        action = TimedAction(
            token=token,
            character_id=character_id,
            action_type=action_type,
            description=description,
            duration_secs=duration,
            phase_labels=phase_labels or [],
        )
        with self._lock:
            self._timed[token] = action
        return token

    def poll_timed_action(self, token: str) -> Optional[Dict]:
        with self._lock:
            action = self._timed.get(token)
        if not action:
            return None
        if action.elapsed >= action.duration_secs:
            action.complete = True
        return {
            "token":        token,
            "character_id": action.character_id,
            "action_type":  action.action_type,
            "description":  action.description,
            "progress":     round(action.progress, 2),
            "phase":        action.current_phase,
            "complete":     action.complete,
            "aborted":      action.aborted,
            "elapsed_secs": round(action.elapsed, 1),
            "duration_secs": action.duration_secs,
        }

    def abort_timed_action(self, token: str) -> bool:
        with self._lock:
            action = self._timed.get(token)
            if action:
                action.aborted = True
                return True
        return False

    def active_timed_actions(self, character_id: Optional[str] = None) -> List[Dict]:
        with self._lock:
            actions = list(self._timed.values())
        results = []
        for a in actions:
            if a.complete or a.aborted:
                continue
            if character_id and a.character_id != character_id:
                continue
            a_dict = self.poll_timed_action(a.token) or {}
            results.append(a_dict)
        return results

    # ── Narrative ─────────────────────────────────────────────────────

    def add_narrative(self, scene_id: str, event: str, character_id: str = "", entry_type: str = "action") -> None:
        self._narrative.add(scene_id, event, character_id=character_id, entry_type=entry_type)

    def get_narrative(self, scene_id: str, limit: int = 20) -> str:
        return self._narrative.get_text(scene_id, limit=limit)

    def get_narrative_entries(self, scene_id: str, limit: int = 20) -> List[Dict]:
        return [e.to_dict() for e in self._narrative.get(scene_id, limit=limit)]

    # ── Interactions ──────────────────────────────────────────────────

    def log_interaction(self, scene_id: str, record: InteractionRecord) -> None:
        with self._lock:
            if scene_id not in self._interactions:
                self._interactions[scene_id] = []
            self._interactions[scene_id].append(record)
            if len(self._interactions[scene_id]) > 500:
                self._interactions[scene_id] = self._interactions[scene_id][-500:]

    def recent_interactions(self, scene_id: str, limit: int = 10) -> List[Dict]:
        with self._lock:
            records = self._interactions.get(scene_id, [])[-limit:]
        return [asdict(r) for r in records]

    def last_interaction_type(self, scene_id: str) -> Optional[str]:
        with self._lock:
            records = self._interactions.get(scene_id, [])
        return records[-1].interaction_type if records else None

    # ── Scene atmosphere ──────────────────────────────────────────────

    def set_atmosphere(self, scene_id: str, **kwargs) -> None:
        with self._lock:
            if scene_id not in self._scene_atmospheres:
                self._scene_atmospheres[scene_id] = {}
            self._scene_atmospheres[scene_id].update(kwargs)

    def get_atmosphere(self, scene_id: str) -> Dict:
        with self._lock:
            return dict(self._scene_atmospheres.get(scene_id, {}))

    # ── Scene state ───────────────────────────────────────────────────

    def set_scene_state(self, scene_id: str, **values: Any) -> Dict[str, Any]:
        with self._lock:
            if scene_id not in self._scene_state:
                self._scene_state[scene_id] = {}
            self._scene_state[scene_id].update(values)
            return dict(self._scene_state[scene_id])

    def get_scene_state(self, scene_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._scene_state.get(scene_id, {}))

    # ── Full snapshot ─────────────────────────────────────────────────

    def get_scene_snapshot(self, scene_id: str, character_ids: Optional[List[str]] = None) -> Dict:
        characters_data: Dict[str, Any] = {}
        with self._lock:
            all_char_ids = character_ids or list(self._wardrobes.keys())
        for cid in all_char_ids:
            wardrobe = self.get_wardrobe(cid)
            stats    = self.get_stats(cid)
            characters_data[cid] = {
                "wardrobe":       wardrobe.to_dict(),
                "stats":          stats.to_dict(),
                "emotional_state": stats.emotional_state_text(),
                "active_actions": self.active_timed_actions(character_id=cid),
            }
        return {
            "scene_id":           scene_id,
            "characters":         characters_data,
            "atmosphere":         self.get_atmosphere(scene_id),
            "scene_state":        self.get_scene_state(scene_id),
            "recent_narrative":   self.get_narrative(scene_id, limit=15),
            "recent_interactions": self.recent_interactions(scene_id, limit=5),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_SSM_INSTANCE: Optional[SceneStateManager] = None
_SSM_LOCK = threading.Lock()


def get_scene_state_manager() -> SceneStateManager:
    global _SSM_INSTANCE
    if _SSM_INSTANCE is None:
        with _SSM_LOCK:
            if _SSM_INSTANCE is None:
                _SSM_INSTANCE = SceneStateManager()
    return _SSM_INSTANCE
