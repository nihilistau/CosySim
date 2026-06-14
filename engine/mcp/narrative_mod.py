"""
Narrative Mod Engine — Stage-based storytelling with measurable targets
========================================================================

Manages narrative mods (story modules) with stages and completion targets.
Inspired by OpenRoom's mod system where AI characters progress through
narrative stages, each with specific objectives that advance the plot.

The AI agent's system prompt is dynamically injected with the current
stage's description and targets, guiding the narrative.

Usage:
    from engine.mcp.narrative_mod import get_narrative_engine

    engine = get_narrative_engine()
    mod = engine.start_mod("space_adventure", "Bounty Hunter Fugue", stages=[
        ModStage(stage_id="act1", title="Reunion", description="...",
                 prompt_injection="You are reuniting with the player...",
                 targets=[ModTarget(target_id="greet", description="Exchange introductions")])
    ])
    engine.complete_target("space_adventure", "greet")  # Advances if all targets done

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial narrative mod system (OpenRoom-inspired)

CONNECTS: MCPFramework (event bus), InterceptorPipeline (prompt injection),
          NarrativeModInterceptor (pre_call stage context), narrative_skills
CALLED BY: Scene code, narrative skills, NarrativeModInterceptor
EMITS: mod_started, mod_target_completed, mod_stage_advanced, mod_completed events
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ──── Data Structures ────────────────────────────────────────────────────────

@dataclass
class ModTarget:
    """A single objective within a narrative stage."""
    target_id: str
    description: str
    condition: str = ""          # Python expression or "manual" (default)
    completed: bool = False
    completed_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def complete(self) -> None:
        self.completed = True
        self.completed_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id, "description": self.description,
            "completed": self.completed, "completed_at": self.completed_at,
        }


@dataclass
class ModStage:
    """One stage in a narrative mod."""
    stage_id: str
    title: str
    description: str
    prompt_injection: str        # Text injected into agent system prompt
    targets: List[ModTarget] = field(default_factory=list)
    on_complete_note: str = ""   # Narrative text when all targets done

    @property
    def all_targets_complete(self) -> bool:
        return all(t.completed for t in self.targets) if self.targets else False

    @property
    def progress_pct(self) -> float:
        if not self.targets:
            return 0.0
        return sum(1 for t in self.targets if t.completed) / len(self.targets)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_id": self.stage_id, "title": self.title,
            "description": self.description[:100],
            "targets": [t.to_dict() for t in self.targets],
            "progress_pct": round(self.progress_pct, 2),
            "all_complete": self.all_targets_complete,
        }


@dataclass
class ModState:
    """Runtime state for one active narrative mod."""
    mod_id: str
    mod_name: str
    stages: List[ModStage]
    stage_index: int = 0
    is_finished: bool = False
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    scene_id: str = ""
    character_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def current_stage(self) -> Optional[ModStage]:
        if 0 <= self.stage_index < len(self.stages):
            return self.stages[self.stage_index]
        return None

    @property
    def total_stages(self) -> int:
        return len(self.stages)

    def complete_target(self, target_id: str) -> bool:
        """Mark a target as completed. Returns True if found and newly completed."""
        stage = self.current_stage
        if not stage:
            return False
        for target in stage.targets:
            if target.target_id == target_id and not target.completed:
                target.complete()
                logger.info(
                    "[NarrativeMod] Target completed (operation=complete_target, mod=%s, "
                    "stage=%s, target=%s)", self.mod_id, stage.stage_id, target_id,
                )
                return True
        return False

    def advance_stage(self) -> bool:
        """Advance to the next stage. Returns True if advanced, False if finished."""
        if self.stage_index >= len(self.stages) - 1:
            self.is_finished = True
            self.completed_at = time.time()
            logger.info(
                "[NarrativeMod] Mod completed (operation=mod_complete, mod=%s, "
                "stages=%d, elapsed=%.0fs)", self.mod_id, len(self.stages),
                time.time() - self.started_at,
            )
            return False
        self.stage_index += 1
        logger.info(
            "[NarrativeMod] Stage advanced (operation=advance_stage, mod=%s, "
            "new_stage=%d/%d, title=%s)", self.mod_id, self.stage_index,
            len(self.stages), self.current_stage.title if self.current_stage else "?",
        )
        return True

    def get_progress(self) -> Dict[str, Any]:
        """Return full progress snapshot."""
        stage = self.current_stage
        return {
            "mod_id": self.mod_id,
            "mod_name": self.mod_name,
            "stage_index": self.stage_index,
            "total_stages": self.total_stages,
            "is_finished": self.is_finished,
            "current_stage": stage.to_dict() if stage else None,
            "elapsed_seconds": round(time.time() - self.started_at, 1),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.get_progress(),
            "scene_id": self.scene_id,
            "character_id": self.character_id,
            "stages": [s.to_dict() for s in self.stages],
        }


# ──── Narrative Mod Engine ───────────────────────────────────────────────────

class NarrativeModEngine:
    """Manages active narrative mods across all scenes.

    Thread-safe singleton. Scenes call start_mod() to begin a narrative,
    then complete_target() as the player progresses. The NarrativeModInterceptor
    reads get_prompt_injection() to inject stage context into agent prompts.

    CONNECTS: MCPFramework (event bus), InterceptorPipeline
    CALLED BY: narrative_skills, scene code, NarrativeModInterceptor
    EMITS: mod events (logged, can be wired to SocketIO)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_mods: Dict[str, ModState] = {}
        self._callbacks: List[Callable] = []

    def start_mod(
        self,
        mod_id: str,
        mod_name: str,
        stages: List[ModStage],
        scene_id: str = "",
        character_id: str = "",
        metadata: Dict[str, Any] = None,
    ) -> ModState:
        """Start a new narrative mod.

        Args:
            mod_id: Unique mod identifier.
            mod_name: Human-readable name.
            stages: List of ModStage objects defining the narrative.
            scene_id: Scene this mod is active in.
            character_id: Character running this mod.

        Returns:
            The created ModState.
        """
        with self._lock:
            mod = ModState(
                mod_id=mod_id, mod_name=mod_name, stages=stages,
                scene_id=scene_id, character_id=character_id,
                metadata=metadata or {},
            )
            self._active_mods[mod_id] = mod

        logger.info(
            "[NarrativeMod] Mod started (operation=start_mod, mod=%s, name=%s, "
            "stages=%d, scene=%s)", mod_id, mod_name, len(stages), scene_id,
        )
        self._fire_event("mod_started", mod)
        return mod

    def complete_target(self, mod_id: str, target_id: str) -> Dict[str, Any]:
        """Complete a target in an active mod.

        Auto-advances the stage if all targets in the current stage are done.

        Returns:
            Progress dict with stage advancement info.
        """
        with self._lock:
            mod = self._active_mods.get(mod_id)
            if not mod:
                return {"error": f"Mod '{mod_id}' not found"}

            if not mod.complete_target(target_id):
                return {"error": f"Target '{target_id}' not found or already completed"}

            self._fire_event("mod_target_completed", mod, target_id=target_id)

            # Auto-advance if all targets in current stage are done
            stage = mod.current_stage
            if stage and stage.all_targets_complete:
                advanced = mod.advance_stage()
                if advanced:
                    self._fire_event("mod_stage_advanced", mod)
                elif mod.is_finished:
                    self._fire_event("mod_completed", mod)

            return mod.get_progress()

    def advance_stage(self, mod_id: str) -> Dict[str, Any]:
        """Manually advance to the next stage (skip remaining targets)."""
        with self._lock:
            mod = self._active_mods.get(mod_id)
            if not mod:
                return {"error": f"Mod '{mod_id}' not found"}
            mod.advance_stage()
            return mod.get_progress()

    def get_mod(self, mod_id: str) -> Optional[ModState]:
        """Get a specific mod by ID."""
        return self._active_mods.get(mod_id)

    def get_active_mods(self, scene_id: str = "") -> List[ModState]:
        """Get all active (unfinished) mods, optionally filtered by scene."""
        with self._lock:
            mods = [m for m in self._active_mods.values() if not m.is_finished]
            if scene_id:
                mods = [m for m in mods if m.scene_id == scene_id]
            return mods

    def get_prompt_injection(self, scene_id: str) -> str:
        """Get the combined prompt injection for all active mods in a scene.

        Called by NarrativeModInterceptor.pre_call() to inject stage context.

        Returns:
            Multi-line string of stage context, or empty string.
        """
        mods = self.get_active_mods(scene_id)
        if not mods:
            return ""

        lines = []
        for mod in mods:
            stage = mod.current_stage
            if not stage:
                continue
            lines.append(f"[NARRATIVE: {mod.mod_name} — Stage {mod.stage_index + 1}/{mod.total_stages}: {stage.title}]")
            lines.append(stage.prompt_injection)
            incomplete = [t for t in stage.targets if not t.completed]
            if incomplete:
                lines.append("Current objectives:")
                for t in incomplete:
                    lines.append(f"  - {t.description}")
            lines.append("")

        return "\n".join(lines)

    def on_event(self, callback: Callable) -> None:
        """Register a callback for mod events."""
        self._callbacks.append(callback)

    def _fire_event(self, event_type: str, mod: ModState, **kwargs: Any) -> None:
        """Fire event to all registered callbacks."""
        event = {"type": event_type, "mod_id": mod.mod_id, "mod_name": mod.mod_name,
                 "progress": mod.get_progress(), **kwargs}
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass


# ──── Singleton ──────────────────────────────────────────────────────────────

_engine: Optional[NarrativeModEngine] = None
_engine_lock = threading.Lock()


def get_narrative_engine() -> NarrativeModEngine:
    """Get or create the singleton NarrativeModEngine."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = NarrativeModEngine()
    return _engine
