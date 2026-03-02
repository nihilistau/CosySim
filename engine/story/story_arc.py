"""StoryArcEngine — multi-step narrative arc tracking for CosySim scenes."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ArcStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ArcStep:
    id: str
    description: str
    required: bool = True
    completed: bool = False
    failed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryArc:
    id: str
    name: str
    scene: str
    steps: List[ArcStep] = field(default_factory=list)
    status: ArcStatus = ArcStatus.INACTIVE
    progress: float = 0.0  # 0.0–1.0
    outcome: Optional[str] = None  # "win" | "lose" | "neutral"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def advance(self, step_id: str, success: bool = True) -> bool:
        """Mark a step complete/failed and recalculate progress.

        Args:
            step_id: ID of the step to advance.
            success: True to complete the step, False to fail it.

        Returns:
            True if the step was found and updated, False otherwise.
        """
        if self.status in (ArcStatus.FAILED, ArcStatus.COMPLETED):
            return False
        for step in self.steps:
            if step.id == step_id:
                if success:
                    step.completed = True
                else:
                    step.failed = True
                    if step.required:
                        self.status = ArcStatus.FAILED
                        self.outcome = "lose"
                self._recalculate()
                return True
        return False

    def _recalculate(self) -> None:
        if self.status in (ArcStatus.FAILED, ArcStatus.COMPLETED):
            return
        completed = sum(1 for s in self.steps if s.completed)
        total = len(self.steps)
        self.progress = completed / total if total else 0.0
        if completed == total:
            self.status = ArcStatus.COMPLETED
            self.outcome = "win"
        elif self.status == ArcStatus.INACTIVE and completed > 0:
            self.status = ArcStatus.ACTIVE


class StoryArcEngine:
    """Manages story arcs across all scenes. Singleton via get_story_arc_engine()."""

    _instance: Optional["StoryArcEngine"] = None

    def __init__(self) -> None:
        self._arcs: Dict[str, StoryArc] = {}
        self._scene_arcs: Dict[str, List[str]] = {}
        self._hooks: Dict[str, List[Callable]] = {}
        logger.info("StoryArcEngine initialised")

    @classmethod
    def get_instance(cls) -> "StoryArcEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create_arc(self, arc: StoryArc) -> StoryArc:
        """Register a story arc with the engine.

        Args:
            arc: The StoryArc to register.

        Returns:
            The registered arc.
        """
        self._arcs[arc.id] = arc
        self._scene_arcs.setdefault(arc.scene, []).append(arc.id)
        logger.debug("Arc created: %s for scene %s", arc.id, arc.scene)
        return arc

    def get_arc(self, arc_id: str) -> Optional[StoryArc]:
        """Return a registered arc by ID, or None if not found."""
        return self._arcs.get(arc_id)

    def get_scene_arcs(self, scene: str) -> List[StoryArc]:
        """Return all arcs for the given scene."""
        return [self._arcs[aid] for aid in self._scene_arcs.get(scene, []) if aid in self._arcs]

    def advance_arc(self, arc_id: str, step_id: str, success: bool = True) -> Optional[StoryArc]:
        """Advance a step in an arc and fire relevant hooks.

        Args:
            arc_id: ID of the arc to advance.
            step_id: ID of the step to advance.
            success: True to complete the step, False to fail it.

        Returns:
            The updated arc, or None if arc_id was not found.
        """
        arc = self._arcs.get(arc_id)
        if not arc:
            return None
        arc.advance(step_id, success)
        self._fire_hooks("arc_advanced", arc)
        if arc.status in (ArcStatus.COMPLETED, ArcStatus.FAILED):
            self._fire_hooks(f"arc_{arc.status.value}", arc)
        return arc

    def get_scene_state(self, scene: str) -> Dict[str, Any]:
        """Return a summary of all arc states for a scene.

        Args:
            scene: Scene name to query.

        Returns:
            Dict with counts and per-arc summaries.
        """
        arcs = self.get_scene_arcs(scene)
        active = [a for a in arcs if a.status == ArcStatus.ACTIVE]
        completed = [a for a in arcs if a.status == ArcStatus.COMPLETED]
        failed = [a for a in arcs if a.status == ArcStatus.FAILED]
        avg_progress = sum(a.progress for a in arcs) / len(arcs) if arcs else 0.0
        return {
            "scene": scene,
            "total_arcs": len(arcs),
            "active": len(active),
            "completed": len(completed),
            "failed": len(failed),
            "overall_progress": avg_progress,
            "arcs": [
                {
                    "id": a.id,
                    "name": a.name,
                    "status": a.status,
                    "progress": a.progress,
                    "outcome": a.outcome,
                }
                for a in arcs
            ],
        }

    def register_hook(self, event: str, callback: Callable) -> None:
        """Register a callback to fire on a named arc event.

        Args:
            event: One of "arc_advanced", "arc_completed", "arc_failed".
            callback: Callable that receives the StoryArc as its only argument.
        """
        self._hooks.setdefault(event, []).append(callback)

    def _fire_hooks(self, event: str, arc: StoryArc) -> None:
        for cb in self._hooks.get(event, []):
            try:
                cb(arc)
            except Exception as exc:
                logger.warning("Arc hook error [%s]: %s", event, exc)

    def reset(self) -> None:
        """Clear all arcs, scene mappings, and hooks."""
        self._arcs.clear()
        self._scene_arcs.clear()
        self._hooks.clear()


def get_story_arc_engine() -> StoryArcEngine:
    """Return the global StoryArcEngine singleton."""
    return StoryArcEngine.get_instance()
