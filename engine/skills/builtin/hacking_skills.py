"""Hacking skill pack for CosySim v0.81 "THE LIVING CITY".

Exposes hacking mini-game mechanics as @skill tools so LLM agents and the
game engine can initiate, query, and complete hacking sessions.

All skills are idempotent and return human-readable strings suitable
for direct inclusion in agent dialogue.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import SkillCategory, skill

logger = logging.getLogger(__name__)


def _engine():
    """Lazy import to avoid circular deps at module load time."""
    from engine.services.hack_engine import get_hack_engine
    return get_hack_engine()


def _player():
    from engine.world.player_state import get_player_state
    return get_player_state()


def _deck_stats() -> Dict[str, int]:
    try:
        from engine.world.inventory import get_inventory
        return get_inventory().get_cyberdeck_stats()
    except Exception:
        return {"crack_speed": 0, "trace_resist": 0}


def _hacking_skill_level() -> int:
    try:
        return _player().skills.get("hacking", 1)
    except Exception:
        return 1


# ──── Skills ───────────────────────────────────────────────────────────────────


@skill(
    pack="hacking",
    description="List all hackable targets nearby, optionally filtered by scene location.",
    category=SkillCategory.GAME,
    tags=["hacking", "targets", "recon"],
)
def list_hack_targets(location: str = "") -> str:
    """Return a formatted list of nearby hackable targets.

    Args:
        location: Filter to targets in this scene/area. Empty = all targets.

    Returns:
        Formatted string with target names, security levels, and lock status.
    """
    targets = _engine().list_targets(location=location)
    if not targets:
        label = f" in {location}" if location else ""
        return f"No hackable targets found{label}."

    lines = ["HACKABLE TARGETS:"]
    for t in targets:
        locked_str = " [LOCKED]" if t["locked"] else ""
        lines.append(
            f"  [{t['security_level']}★] {t['label']}{locked_str} — {t['location']}"
        )
    return "\n".join(lines)


@skill(
    pack="hacking",
    description="Begin hacking a target device. Returns a puzzle the player must solve.",
    category=SkillCategory.GAME,
    cooldown=3.0,
    tags=["hacking", "puzzle", "initiate"],
)
def initiate_hack(target_id: str) -> str:
    """Generate a hacking puzzle for the specified target.

    The puzzle contains a grid of hex codes and a sequence the player
    must identify. The puzzle ID is needed to submit a solution.

    Args:
        target_id: The target device ID (from list_hack_targets).

    Returns:
        Puzzle description including grid size, time limit, and puzzle_id.
    """
    stats = _deck_stats()
    skill_level = _hacking_skill_level()

    puzzle = _engine().generate_puzzle(
        target_id,
        hacking_skill=skill_level,
        trace_resist=stats["trace_resist"],
        crack_speed=stats["crack_speed"],
    )

    if "error" in puzzle:
        return f"HACK FAILED: {puzzle['error']}"

    deck_info = ""
    if stats["crack_speed"] > 0 or stats["trace_resist"] > 0:
        deck_info = (
            f" [Cyberdeck: crack+{stats['crack_speed']} trace+{stats['trace_resist']}]"
        )

    return (
        f"HACK INITIATED — {target_id}\n"
        f"Puzzle ID: {puzzle['puzzle_id']}\n"
        f"Grid: {puzzle['grid_size']}×{puzzle['grid_size']} | "
        f"Sequence: {puzzle['sequence_length']} cells | "
        f"Time limit: {puzzle['time_limit']}s{deck_info}\n"
        f"[Use the hack interface to solve the matrix puzzle]"
    )


@skill(
    pack="hacking",
    description="Submit a solution to an active hacking puzzle.",
    category=SkillCategory.GAME,
    tags=["hacking", "solve", "submit"],
)
def submit_hack_solution(
    puzzle_id: str,
    cells: str,
    elapsed_seconds: float = 0.0,
) -> str:
    """Submit a cell sequence as the solution to a hacking puzzle.

    Args:
        puzzle_id: The puzzle ID returned by initiate_hack.
        cells: JSON-encoded list of [row, col] pairs e.g. ``"[[0,1],[0,3],[2,1]]"``.
        elapsed_seconds: Seconds elapsed since the puzzle was generated.

    Returns:
        Outcome string: ACCESS GRANTED or failure with heat penalty.
    """
    import json

    try:
        parsed = json.loads(cells)
        submitted = [tuple(c) for c in parsed]
    except Exception:
        return "HACK ERROR: Invalid cell format. Expected JSON array of [row, col] pairs."

    result = _engine().evaluate_attempt(puzzle_id, submitted, elapsed_seconds)

    if result.success:
        rewards_str = ", ".join(result.rewards_granted) if result.rewards_granted else "none"
        xp_str = f" | Hacking XP +{result.xp_delta}" if result.xp_delta else ""
        return f"✅ {result.message} | Rewards: {rewards_str}{xp_str}"
    else:
        heat_str = f" | Heat +{result.heat_delta}" if result.heat_delta else ""
        return f"❌ {result.message}{heat_str}"


@skill(
    pack="hacking",
    description="Get the current hacking skill level and cyberdeck stats.",
    category=SkillCategory.GAME,
    tags=["hacking", "stats", "profile"],
)
def get_hacking_profile() -> str:
    """Return the player's hacking capability summary.

    Returns:
        String with hacking skill level and cyberdeck stats.
    """
    level = _hacking_skill_level()
    stats = _deck_stats()

    try:
        from engine.world.inventory import get_inventory
        deck = get_inventory().get_cyberdeck()
        deck_name = deck.item_id if deck else "None equipped"
    except Exception:
        deck_name = "Unknown"

    level_label = ["Novice", "Script Kiddie", "Netrunner", "Black Hat", "Ghost", "Phantom"][min(level, 5)]
    return (
        f"HACKING PROFILE\n"
        f"  Skill: Lv{level} {level_label}\n"
        f"  Cyberdeck: {deck_name}\n"
        f"  Crack Speed: +{stats['crack_speed']}\n"
        f"  Trace Resist: +{stats['trace_resist']}"
    )


@skill(
    pack="hacking",
    description="Check if the player can hack a specific target (skill check).",
    category=SkillCategory.GAME,
    tags=["hacking", "check", "feasibility"],
)
def can_hack_target(target_id: str) -> str:
    """Check whether the player has sufficient skill to attempt hacking a target.

    Args:
        target_id: The target device ID.

    Returns:
        String indicating whether the hack is feasible and any warnings.
    """
    target = _engine().get_target(target_id)
    if target is None:
        return f"TARGET NOT FOUND: {target_id}"
    if target.is_locked():
        import time
        secs_left = int(target.locked_until - time.time())
        return f"TARGET LOCKED — retryable in {secs_left}s"

    skill_level = _hacking_skill_level()
    stats = _deck_stats()
    level = target.security_level

    # Recommend minimum skill level = security level - 1
    min_skill = max(1, level - 1)
    feasible = skill_level >= min_skill

    lines = [f"TARGET: {target.label} (Security Lv{level})"]
    lines.append(f"Player Skill: Lv{skill_level} | Required: Lv{min_skill}+")
    if feasible:
        lines.append("STATUS: ✅ Feasible — proceed with caution")
    else:
        lines.append(f"STATUS: ⚠️ Underskilled — upgrade hacking skill first")

    if not stats["crack_speed"] and not stats["trace_resist"] and level >= 3:
        lines.append("⚠️ No cyberdeck equipped — higher-level hacks need a deck")

    return "\n".join(lines)


@skill(
    pack="hacking",
    description="Register a new hackable device in the current scene.",
    category=SkillCategory.SYSTEM,
    tags=["hacking", "admin", "register"],
)
def register_hack_target(
    target_id: str,
    security_level: int = 1,
    label: str = "",
    location: str = "",
    rewards: str = "",
) -> str:
    """Register a hackable device (director/admin tool).

    Args:
        target_id: Unique device ID.
        security_level: 1–5.
        label: Human-readable name.
        location: Scene/area name.
        rewards: Comma-separated reward strings e.g. ``"credits:500,intel:faction_data"``.

    Returns:
        Confirmation string.
    """
    reward_list = [r.strip() for r in rewards.split(",") if r.strip()] if rewards else []
    t = _engine().register_target(
        target_id,
        security_level=security_level,
        label=label,
        location=location,
        rewards=reward_list,
    )
    return f"REGISTERED: {t.label} (Lv{t.security_level}) at {t.location or 'unspecified'}"


@skill(
    pack="hacking",
    description="Reset the cooldown lock on a target device (admin/debug use).",
    category=SkillCategory.SYSTEM,
    tags=["hacking", "admin", "reset"],
)
def reset_hack_target_lock(target_id: str) -> str:
    """Remove the hack cooldown lock from a target.

    Args:
        target_id: The target device ID.

    Returns:
        Confirmation or error string.
    """
    ok = _engine().reset_target_lock(target_id)
    return f"LOCK RESET: {target_id}" if ok else f"TARGET NOT FOUND: {target_id}"
