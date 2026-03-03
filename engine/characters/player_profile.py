"""PlayerProfile — persistent player identity and relationship system.

Tracks sessions, scene visits, NPC relationship scores, key decisions,
and reputation scores. Backed by Nexus KMS for cross-session persistence.
All data is stored under category='player_profile' in Nexus.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from engine.config import get_config
from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

_NEXUS_CATEGORY = "player_profile"
_NEXUS_KEY = "player_profile_v1"

# ──── Relationship types ────

RELATIONSHIP_TYPES = [
    "stranger",
    "acquaintance",
    "friend",
    "close_friend",
    "lover",
    "partner",
    "co_worker",
    "crew",
    "brother",     # crew-level bond
    "rival",
    "enemy",
    "family",
]

# Score → auto-upgraded type thresholds (only upgrade, never auto-downgrade past explicit set)
_SCORE_TO_TYPE: List[tuple] = [
    (90,  "brother"),
    (75,  "close_friend"),
    (50,  "friend"),
    (20,  "acquaintance"),
    (-20, "stranger"),
    (-50, "rival"),
    (-80, "enemy"),
]


def _auto_type_from_score(score: float, current_type: str) -> str:
    """Suggest a relationship type based on score.

    Only suggests upgrades for positive scores; negative scores suggest rival/enemy.
    Explicit relationship types (lover, partner, crew, family) are never auto-overridden.
    """
    protected = {"lover", "partner", "crew", "family", "brother", "co_worker"}
    if current_type in protected:
        return current_type
    for threshold, rel_type in _SCORE_TO_TYPE:
        if score >= threshold:
            return rel_type
    return "enemy"


# ──── Sentiment thresholds ────

def _sentiment_from_score(score: float) -> str:
    if score > 50:
        return "close"
    if score < -50:
        return "hostile"
    return "neutral"


# ──── Data containers ────

@dataclass
class RelationshipEntry:
    character_id: str
    score: float = 0.0
    sentiment: str = "neutral"
    rel_type: str = "stranger"       # see RELATIONSHIP_TYPES
    last_interaction: float = 0.0
    interaction_count: int = 0
    notes: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)  # "crew", "crew:hackers", etc.

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "score": self.score,
            "sentiment": self.sentiment,
            "rel_type": self.rel_type,
            "last_interaction": self.last_interaction,
            "interaction_count": self.interaction_count,
            "notes": list(self.notes),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RelationshipEntry":
        return cls(
            character_id=data["character_id"],
            score=float(data.get("score", 0.0)),
            sentiment=data.get("sentiment", "neutral"),
            rel_type=data.get("rel_type", "stranger"),
            last_interaction=float(data.get("last_interaction", 0.0)),
            interaction_count=int(data.get("interaction_count", 0)),
            notes=list(data.get("notes", [])),
            tags=list(data.get("tags", [])),
        )


@dataclass
class DecisionEntry:
    decision_id: str
    scene: str
    description: str
    timestamp: float
    consequences: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "scene": self.scene,
            "description": self.description,
            "timestamp": self.timestamp,
            "consequences": list(self.consequences),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionEntry":
        return cls(
            decision_id=data["decision_id"],
            scene=data["scene"],
            description=data["description"],
            timestamp=float(data["timestamp"]),
            consequences=list(data.get("consequences", [])),
        )


# ──── Singleton ────

class PlayerProfile:
    """Persistent player identity, history, and relationship tracker."""

    _instance: Optional["PlayerProfile"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        cfg = get_config()
        self.player_id: str = cfg.get("player.id", "") or str(uuid.uuid4())
        self.display_name: str = cfg.get("player.display_name", "") or "Player"
        self.sessions: List[dict] = []
        self.scene_visits: Dict[str, int] = {}
        self.relationships: Dict[str, RelationshipEntry] = {}
        self.decisions: List[DecisionEntry] = []
        self.reputation: Dict[str, float] = {}
        self._nexus_key: str = _NEXUS_KEY
        self._nexus_entry_id: Optional[str] = None

    # ──── Nexus persistence ────

    def load(self) -> None:
        """Load profile from Nexus; silently no-ops if not found."""
        try:
            client = get_nexus_client()
            results = client.search(self._nexus_key, limit=5)
            for entry in results:
                if entry.get("title") == self._nexus_key:
                    self._nexus_entry_id = entry.get("id")
                    raw = entry.get("content", "{}")
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    self.from_dict(data)
                    logger.debug("PlayerProfile loaded (entry %s)", self._nexus_entry_id)
                    return
        except Exception as exc:  # noqa: BLE001
            logger.warning("PlayerProfile.load failed: %s", exc)

    def save(self) -> None:
        """Serialize and upsert profile in Nexus."""
        try:
            client = get_nexus_client()
            content = json.dumps(self.to_dict())
            if self._nexus_entry_id:
                client.update_entry(
                    self._nexus_entry_id,
                    content=content,
                )
            else:
                entry_id = client.add_entry(
                    title=self._nexus_key,
                    content=content,
                    content_type="memory",
                    category=_NEXUS_CATEGORY,
                    tags=["player", "profile", "persistent"],
                )
                if entry_id:
                    self._nexus_entry_id = entry_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("PlayerProfile.save failed: %s", exc)

    # ──── Session tracking ────

    def record_session_start(self, scene: str) -> str:
        """Start a new session in *scene* and return its session_id."""
        session_id = str(uuid.uuid4())
        self.sessions.append(
            {
                "session_id": session_id,
                "scene": scene,
                "start_time": time.time(),
                "end_time": None,
            }
        )
        self.scene_visits[scene] = self.scene_visits.get(scene, 0) + 1
        return session_id

    def record_session_end(self, session_id: str) -> None:
        """Mark an existing session as ended."""
        for sess in self.sessions:
            if sess["session_id"] == session_id:
                sess["end_time"] = time.time()
                return
        logger.warning("record_session_end: unknown session_id %s", session_id)

    # ──── Relationships ────

    def update_relationship(
        self,
        character_id: str,
        delta: float,
        notes: str = "",
    ) -> RelationshipEntry:
        """Apply *delta* to the relationship with *character_id*, clamping to [-100, 100]."""
        if character_id not in self.relationships:
            self.relationships[character_id] = RelationshipEntry(character_id=character_id)
        entry = self.relationships[character_id]
        entry.score = max(-100.0, min(100.0, entry.score + delta))
        entry.sentiment = _sentiment_from_score(entry.score)
        # Auto-upgrade type unless it's a protected type
        entry.rel_type = _auto_type_from_score(entry.score, entry.rel_type)
        entry.last_interaction = time.time()
        entry.interaction_count += 1
        if notes:
            entry.notes.append(notes)
        return entry

    def set_relationship_type(
        self,
        character_id: str,
        rel_type: str,
        notes: str = "",
    ) -> RelationshipEntry:
        """Explicitly set the relationship type for *character_id*.

        This overrides the auto-calculated type. Use for story-driven
        relationship changes (lover, crew, partner, etc.).

        Args:
            character_id: The NPC's identifier.
            rel_type: One of RELATIONSHIP_TYPES.
            notes: Optional note to record.

        Returns:
            Updated RelationshipEntry.
        """
        if character_id not in self.relationships:
            self.relationships[character_id] = RelationshipEntry(character_id=character_id)
        entry = self.relationships[character_id]
        if rel_type not in RELATIONSHIP_TYPES:
            logger.warning("set_relationship_type: unknown type '%s'", rel_type)
        entry.rel_type = rel_type
        entry.last_interaction = time.time()
        if notes:
            entry.notes.append(notes)
        return entry

    def add_crew_member(
        self,
        character_id: str,
        crew_tag: str = "crew",
        notes: str = "",
    ) -> RelationshipEntry:
        """Add *character_id* to the player's crew.

        Sets rel_type to 'crew' and adds a crew tag. Also bumps score to
        at least 50 if it's currently lower (can't be crew with a stranger).

        Args:
            character_id: The NPC's identifier.
            crew_tag: Optional specific crew role tag (e.g. 'crew:hacker').
            notes: Optional note.

        Returns:
            Updated RelationshipEntry.
        """
        if character_id not in self.relationships:
            self.relationships[character_id] = RelationshipEntry(character_id=character_id)
        entry = self.relationships[character_id]
        entry.rel_type = "crew"
        entry.score = max(entry.score, 50.0)
        entry.sentiment = _sentiment_from_score(entry.score)
        if crew_tag not in entry.tags:
            entry.tags.append(crew_tag)
        entry.last_interaction = time.time()
        if notes:
            entry.notes.append(notes)
        logger.info("add_crew_member: %s joined crew as '%s'", character_id, crew_tag)
        return entry

    def get_crew(self) -> List[RelationshipEntry]:
        """Return all characters with rel_type='crew' or crew tag."""
        return [
            r for r in self.relationships.values()
            if r.rel_type == "crew" or "crew" in r.tags
        ]

    # ──── Decisions ────

    def record_decision(
        self,
        scene: str,
        description: str,
        consequences: Optional[List[str]] = None,
    ) -> DecisionEntry:
        """Record a player decision and return the entry."""
        entry = DecisionEntry(
            decision_id=str(uuid.uuid4()),
            scene=scene,
            description=description,
            timestamp=time.time(),
            consequences=list(consequences or []),
        )
        self.decisions.append(entry)
        return entry

    # ──── Summaries ────

    def get_relationship_summary(self) -> str:
        """Human-readable top-5 relationships by absolute score."""
        if not self.relationships:
            return "No relationships tracked yet."
        top = sorted(
            self.relationships.values(),
            key=lambda r: abs(r.score),
            reverse=True,
        )[:5]
        lines = [
            f"{r.character_id}: {r.score:+.1f} [{r.rel_type}] ({r.sentiment}, {r.interaction_count} interactions)"
            for r in top
        ]
        return "\n".join(lines)

    def get_scene_summary(self) -> str:
        """Human-readable scene visit counts."""
        if not self.scene_visits:
            return "No scenes visited yet."
        lines = [
            f"Visited {scene} {count} time{'s' if count != 1 else ''}"
            for scene, count in sorted(self.scene_visits.items())
        ]
        return "\n".join(lines)

    # ──── Serialization ────

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "display_name": self.display_name,
            "sessions": list(self.sessions),
            "scene_visits": dict(self.scene_visits),
            "relationships": {k: v.to_dict() for k, v in self.relationships.items()},
            "decisions": [d.to_dict() for d in self.decisions],
            "reputation": dict(self.reputation),
        }

    def from_dict(self, data: dict) -> None:
        """Hydrate this instance from a serialized dict."""
        self.player_id = data.get("player_id", self.player_id)
        self.display_name = data.get("display_name", self.display_name)
        self.sessions = list(data.get("sessions", []))
        self.scene_visits = dict(data.get("scene_visits", {}))
        self.relationships = {
            k: RelationshipEntry.from_dict(v)
            for k, v in data.get("relationships", {}).items()
        }
        self.decisions = [
            DecisionEntry.from_dict(d) for d in data.get("decisions", [])
        ]
        self.reputation = {k: float(v) for k, v in data.get("reputation", {}).items()}


# ──── Singleton accessor ────

def get_player_profile() -> PlayerProfile:
    """Return the process-wide PlayerProfile singleton."""
    if PlayerProfile._instance is None:
        with PlayerProfile._lock:
            if PlayerProfile._instance is None:
                PlayerProfile._instance = PlayerProfile()
    return PlayerProfile._instance
