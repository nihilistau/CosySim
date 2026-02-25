"""
Cross-Scene Agent State — Persistent agent identity across scenes.

Manages agent state that persists across scene boundaries:
- Reputation and relationships
- Inventory and achievements
- Mood and personality drift
- Scene visit history

State is stored in-memory with optional Nexus persistence.

Usage:
    from engine.scenes.agent_state import get_agent_state_manager
    asm = get_agent_state_manager()
    state = asm.get_state("lola")
    state["reputation"]["casino"] = 85
    asm.save_state("lola")
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentPersistentState:
    """Persistent state for a single agent across scenes."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.reputation: Dict[str, int] = {}  # scene_name → reputation score (0-100)
        self.relationships: Dict[str, int] = {}  # other_agent_id → trust (-100 to 100)
        self.achievements: List[str] = []
        self.scene_visits: List[Dict[str, Any]] = []  # [{scene, entered_at, left_at}]
        self.inventory: List[Dict[str, Any]] = []  # cross-scene items
        self.mood: str = "neutral"
        self.mood_history: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = {
            "scenes_visited": 0,
            "conversations": 0,
            "skills_used": 0,
            "games_won": 0,
            "games_lost": 0,
        }
        self.last_scene: Optional[str] = None
        self.last_active: float = time.time()

    def enter_scene(self, scene_name: str) -> None:
        """Record entering a scene."""
        self.scene_visits.append({
            "scene": scene_name,
            "entered_at": time.time(),
            "left_at": None,
        })
        self.last_scene = scene_name
        self.stats["scenes_visited"] += 1
        self.last_active = time.time()
        if scene_name not in self.reputation:
            self.reputation[scene_name] = 50  # Start neutral

    def leave_scene(self, scene_name: str) -> None:
        """Record leaving a scene."""
        for visit in reversed(self.scene_visits):
            if visit["scene"] == scene_name and visit["left_at"] is None:
                visit["left_at"] = time.time()
                break
        self.last_active = time.time()

    def adjust_reputation(self, scene_name: str, delta: int) -> int:
        """Adjust reputation for a scene. Returns new value."""
        current = self.reputation.get(scene_name, 50)
        new_val = max(0, min(100, current + delta))
        self.reputation[scene_name] = new_val
        return new_val

    def set_relationship(self, other_id: str, delta: int) -> int:
        """Adjust relationship with another agent."""
        current = self.relationships.get(other_id, 0)
        new_val = max(-100, min(100, current + delta))
        self.relationships[other_id] = new_val
        return new_val

    def add_achievement(self, achievement: str) -> bool:
        """Add an achievement. Returns False if already earned."""
        if achievement in self.achievements:
            return False
        self.achievements.append(achievement)
        return True

    def set_mood(self, mood: str) -> None:
        """Update mood and track history."""
        self.mood_history.append({"mood": self.mood, "changed_at": time.time()})
        if len(self.mood_history) > 50:
            self.mood_history = self.mood_history[-50:]
        self.mood = mood

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "reputation": self.reputation,
            "relationships": self.relationships,
            "achievements": self.achievements,
            "scene_visits": self.scene_visits[-10:],  # Last 10 visits
            "inventory": self.inventory,
            "mood": self.mood,
            "stats": self.stats,
            "last_scene": self.last_scene,
            "last_active": self.last_active,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f"Agent: {self.agent_id} | Mood: {self.mood}"]
        if self.reputation:
            rep_str = ", ".join(f"{s}:{v}" for s, v in self.reputation.items())
            lines.append(f"Reputation: {rep_str}")
        if self.relationships:
            rel_str = ", ".join(f"{a}:{v:+d}" for a, v in self.relationships.items())
            lines.append(f"Relationships: {rel_str}")
        if self.achievements:
            lines.append(f"Achievements: {len(self.achievements)}")
        lines.append(f"Stats: {self.stats['scenes_visited']} scenes, "
                     f"{self.stats['conversations']} convos, "
                     f"{self.stats['games_won']}W/{self.stats['games_lost']}L")
        return "\n".join(lines)


class AgentStateManager:
    """Manages persistent state for all agents across scenes."""

    def __init__(self, nexus_url: str = "http://localhost:9400"):
        self.nexus_url = nexus_url
        self._states: Dict[str, AgentPersistentState] = {}

    def get_state(self, agent_id: str) -> AgentPersistentState:
        """Get or create persistent state for an agent."""
        if agent_id not in self._states:
            self._states[agent_id] = AgentPersistentState(agent_id)
        return self._states[agent_id]

    def get_all_states(self) -> Dict[str, AgentPersistentState]:
        """Get all agent states."""
        return dict(self._states)

    def agent_enters_scene(self, agent_id: str, scene_name: str) -> AgentPersistentState:
        """Record an agent entering a scene."""
        state = self.get_state(agent_id)
        state.enter_scene(scene_name)
        logger.debug("Agent %s entered scene %s", agent_id, scene_name)
        return state

    def agent_leaves_scene(self, agent_id: str, scene_name: str) -> None:
        """Record an agent leaving a scene."""
        state = self.get_state(agent_id)
        state.leave_scene(scene_name)
        self._save_to_nexus(state)

    def get_reputation_context(self, agent_id: str) -> str:
        """Get reputation context string for prompt injection."""
        state = self.get_state(agent_id)
        if not state.reputation:
            return ""
        lines = [f"[Agent {agent_id} cross-scene reputation:]"]
        for scene, rep in state.reputation.items():
            label = (
                "Legendary" if rep >= 90 else
                "Renowned" if rep >= 75 else
                "Respected" if rep >= 60 else
                "Known" if rep >= 40 else
                "Unknown" if rep >= 20 else
                "Distrusted"
            )
            lines.append(f"  {scene}: {label} ({rep}/100)")
        if state.achievements:
            lines.append(f"  Achievements: {', '.join(state.achievements[-5:])}")
        return "\n".join(lines)

    def _save_to_nexus(self, state: AgentPersistentState) -> None:
        """Persist agent state to Nexus (best-effort)."""
        try:
            import urllib.request
            data = json.dumps({
                "content": json.dumps(state.to_dict()),
                "content_type": "agent_state",
                "tags": ["agent", state.agent_id, "persistent_state"],
                "metadata": {"agent_id": state.agent_id},
                "quality_score": 0.7,
            }).encode()
            req = urllib.request.Request(
                f"{self.nexus_url}/api/knowledge",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


# Module-level singleton
_manager: Optional[AgentStateManager] = None


def get_agent_state_manager() -> AgentStateManager:
    """Get or create the global AgentStateManager."""
    global _manager
    if _manager is None:
        _manager = AgentStateManager()
    return _manager
