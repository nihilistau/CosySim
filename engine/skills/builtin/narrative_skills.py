"""
Narrative Skills — Stage-based storytelling for AI agents
==========================================================

Skills for managing narrative mods: starting stories, completing objectives,
tracking progress, and advancing stages. Agents use these to drive
interactive narratives with measurable progression.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: NarrativeModEngine
CALLED BY: AgentGovernor (auto/optional skills), scene code
"""
from __future__ import annotations

import json
import logging
from typing import List

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="narrative",
    description=(
        "Start a new narrative mod/story with stages and objectives. "
        "Each stage has a description injected into your prompts and "
        "targets that must be completed to advance."
    ),
    tags=["narrative", "story", "mod", "start"],
    category="NARRATIVE",
    cooldown=5.0,
)
def start_narrative(
    mod_id: str,
    mod_name: str,
    stages_json: str,
    scene_id: str = "",
    character_id: str = "",
) -> str:
    """Start a narrative mod with stages and targets.

    Args:
        mod_id: Unique identifier for this mod.
        mod_name: Human-readable name.
        stages_json: JSON array of stages, each with:
            stage_id, title, description, prompt_injection,
            targets: [{target_id, description}]
        scene_id: Scene this mod runs in.
        character_id: Character running the mod.

    Returns:
        Confirmation with stage count and first stage info.
    """
    try:
        from engine.mcp.narrative_mod import (
            ModStage, ModTarget, get_narrative_engine,
        )

        raw_stages = json.loads(stages_json)
        stages = []
        for s in raw_stages:
            targets = [
                ModTarget(target_id=t["target_id"], description=t["description"])
                for t in s.get("targets", [])
            ]
            stages.append(ModStage(
                stage_id=s["stage_id"],
                title=s["title"],
                description=s.get("description", ""),
                prompt_injection=s.get("prompt_injection", s.get("description", "")),
                targets=targets,
                on_complete_note=s.get("on_complete_note", ""),
            ))

        engine = get_narrative_engine()
        mod = engine.start_mod(
            mod_id=mod_id, mod_name=mod_name, stages=stages,
            scene_id=scene_id, character_id=character_id,
        )

        stage = mod.current_stage
        return (
            f"Narrative '{mod_name}' started with {len(stages)} stages. "
            f"Stage 1: {stage.title} — {len(stage.targets)} targets."
        )

    except Exception as exc:
        logger.error("[NarrativeSkills] start_narrative failed: %s", exc)
        return f"Failed to start narrative: {exc}"


@skill(
    pack="narrative",
    description=(
        "Complete an objective/target in the current narrative. "
        "The story may automatically advance to the next stage when "
        "all targets in the current stage are done."
    ),
    tags=["narrative", "target", "complete", "objective"],
    category="NARRATIVE",
)
def complete_target(mod_id: str, target_id: str) -> str:
    """Mark a narrative target as completed.

    Args:
        mod_id: The mod identifier.
        target_id: The target to complete.

    Returns:
        Progress update including stage advancement info.
    """
    try:
        from engine.mcp.narrative_mod import get_narrative_engine

        result = get_narrative_engine().complete_target(mod_id, target_id)
        if "error" in result:
            return result["error"]

        stage_info = result.get("current_stage", {})
        return (
            f"Target '{target_id}' completed! "
            f"Stage {result['stage_index'] + 1}/{result['total_stages']}: "
            f"{stage_info.get('title', '?')} "
            f"({stage_info.get('progress_pct', 0):.0%} complete)"
            + (" — MOD FINISHED!" if result.get("is_finished") else "")
        )

    except Exception as exc:
        return f"Failed to complete target: {exc}"


@skill(
    pack="narrative",
    description="Get progress on an active narrative mod/story.",
    tags=["narrative", "progress", "status"],
    category="NARRATIVE",
)
def get_narrative_progress(mod_id: str = "") -> str:
    """Get progress for active narrative mods.

    Args:
        mod_id: Specific mod to check. If empty, returns all active mods.

    Returns:
        Formatted progress report.
    """
    try:
        from engine.mcp.narrative_mod import get_narrative_engine

        engine = get_narrative_engine()

        if mod_id:
            mod = engine.get_mod(mod_id)
            if not mod:
                return f"No mod found with ID '{mod_id}'."
            return json.dumps(mod.get_progress(), indent=2)

        mods = engine.get_active_mods()
        if not mods:
            return "No active narratives."

        lines = [f"Active narratives: {len(mods)}"]
        for mod in mods:
            stage = mod.current_stage
            lines.append(
                f"  [{mod.mod_id}] {mod.mod_name} — "
                f"Stage {mod.stage_index + 1}/{mod.total_stages}: "
                f"{stage.title if stage else '?'} "
                f"({stage.progress_pct:.0%})" if stage else ""
            )
        return "\n".join(lines)

    except Exception as exc:
        return f"Failed to get progress: {exc}"


@skill(
    pack="narrative",
    description="Manually advance to the next stage of a narrative (skips remaining targets).",
    tags=["narrative", "advance", "stage"],
    category="NARRATIVE",
    cooldown=5.0,
)
def advance_narrative_stage(mod_id: str) -> str:
    """Force-advance to the next narrative stage.

    Args:
        mod_id: The mod to advance.

    Returns:
        New stage info or completion message.
    """
    try:
        from engine.mcp.narrative_mod import get_narrative_engine

        result = get_narrative_engine().advance_stage(mod_id)
        if "error" in result:
            return result["error"]

        if result.get("is_finished"):
            return f"Narrative '{result.get('mod_name', mod_id)}' is complete!"

        stage = result.get("current_stage", {})
        return (
            f"Advanced to Stage {result['stage_index'] + 1}/{result['total_stages']}: "
            f"{stage.get('title', '?')}"
        )

    except Exception as exc:
        return f"Failed to advance stage: {exc}"


# ──── Story Packs ────────────────────────────────────────────────────────
# v1.51.0 [2026-03-25] — Load pre-built narrative story packs

@skill(
    pack="narrative",
    description=(
        "Load a pre-built story pack to start a guided narrative experience. "
        "Available packs: welcome_to_neoncity (4 stages), "
        "realm_dragonfire_chain (5 stages), oracle_awakening (3 stages)."
    ),
    tags=["narrative", "story", "pack", "load", "start"],
    category="NARRATIVE",
    cooldown=10.0,
)
def load_story_pack(
    pack_id: str,
    scene_id: str = "",
    character_id: str = "",
) -> str:
    """Load and start a pre-built narrative story pack.

    Args:
        pack_id: Pack to load. Options: welcome_to_neoncity,
                 realm_dragonfire_chain, oracle_awakening.
        scene_id: Override scene (default: from pack).
        character_id: Character running the narrative.

    Returns:
        Pack start confirmation with stage count.
    """
    try:
        from engine.mcp.narrative_packs import load_pack, PACK_CATALOG

        if pack_id not in PACK_CATALOG:
            available = ", ".join(PACK_CATALOG.keys())
            return f"Unknown pack '{pack_id}'. Available: {available}"

        mod = load_pack(pack_id, scene_id=scene_id, character_id=character_id)
        if not mod:
            return f"Failed to load pack '{pack_id}'"

        info = PACK_CATALOG[pack_id]
        stage = mod.current_stage
        return (
            f"Story pack '{info['name']}' started with {mod.total_stages} stages. "
            f"Stage 1: {stage.title} — {len(stage.targets)} targets."
        )

    except Exception as exc:
        return f"Failed to load story pack: {exc}"


@skill(
    pack="narrative",
    description="List available narrative story packs that can be loaded.",
    tags=["narrative", "story", "pack", "list"],
    category="NARRATIVE",
)
def list_story_packs() -> str:
    """List all available pre-built narrative story packs.

    Returns:
        Formatted list of available packs.
    """
    try:
        from engine.mcp.narrative_packs import list_packs

        packs = list_packs()
        if not packs:
            return "No story packs available."

        lines = [f"Available story packs: {len(packs)}"]
        for pack_id, info in packs.items():
            lines.append(
                f"  [{pack_id}] {info['name']} — "
                f"{info['stages']} stages — {info['description']}"
            )
        return "\n".join(lines)

    except Exception as exc:
        return f"Failed to list packs: {exc}"
