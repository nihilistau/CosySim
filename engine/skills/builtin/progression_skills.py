"""Skill progression skills — query levels, attempt skill checks, view XP."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="progression",
    description="Attempt a skill check (roll d20 + skill vs difficulty)",
    category="GAME",
    cost=1.0,
)
def attempt_action(
    skill_name: str,
    difficulty: str = "medium",
    modifier: int = 0,
    advantage: bool = False,
) -> str:
    """Perform a skill check with a d20 roll against a difficulty class.

    Args:
        skill_name: Skill to check (hacking, combat, stealth, social, tech, driving, medicine, trading).
        difficulty: Difficulty tier (trivial, easy, medium, hard, very_hard, legendary).
        modifier: Situational bonus/penalty.
        advantage: Roll twice take higher.
    """
    from engine.world.skill_progression import get_skill_manager, DIFFICULTY_TIERS

    mgr = get_skill_manager()
    dc = DIFFICULTY_TIERS.get(difficulty, 12)

    try:
        result = mgr.skill_check(
            skill_name, difficulty=dc,
            modifier=modifier, advantage=advantage,
        )
    except ValueError as e:
        return f"❌ {e}"

    return result.narrative()


@skill(
    pack="progression",
    description="Check current skill level and XP progress",
    category="GAME",
)
def check_skill(skill_name: str) -> str:
    """Display current level, XP, and progress for a specific skill."""
    from engine.world.skill_progression import get_skill_manager, SKILL_ICONS, SKILL_DESCRIPTIONS

    mgr = get_skill_manager()
    level = mgr.get_level(skill_name)
    xp = mgr.get_xp(skill_name)

    skills = mgr.get_all_skills()
    state = skills.get(skill_name)
    if not state:
        return f"❌ Unknown skill '{skill_name}'."

    icon = SKILL_ICONS.get(skill_name, "🎯")
    desc = SKILL_DESCRIPTIONS.get(skill_name, "")
    progress = state.get("xp", 0)

    # Calculate progress
    from engine.world.skill_progression import LEVEL_THRESHOLDS, MAX_SKILL_LEVEL
    if level < MAX_SKILL_LEVEL:
        current_t = LEVEL_THRESHOLDS[level]
        next_t = LEVEL_THRESHOLDS[level + 1]
        remaining = next_t - xp
        pct = (xp - current_t) / (next_t - current_t) * 100
        level_info = f"Level {level} → {level + 1}: {pct:.0f}% ({remaining} XP needed)"
    else:
        level_info = "MASTERED"

    # Unlocked abilities
    unlocked = mgr.get_unlocked_abilities(skill_name)
    locked = mgr.get_locked_abilities(skill_name)

    lines = [
        f"{icon} {skill_name.title()} — {desc}",
        f"  Level: {level}/5 | XP: {xp} | {level_info}",
        f"  Uses: {state.get('uses', 0)} total",
    ]
    if unlocked:
        lines.append(f"  ✅ Unlocked: {', '.join(unlocked)}")
    if locked:
        lock_str = ", ".join(f"{n} (Lv{req})" for n, req in locked[:5])
        lines.append(f"  🔒 Locked: {lock_str}")

    return "\n".join(lines)


@skill(
    pack="progression",
    description="View all skills and player level overview",
    category="GAME",
)
def view_xp() -> str:
    """Display a full overview of all skills, XP, and global player level."""
    from engine.world.skill_progression import get_skill_manager

    mgr = get_skill_manager()
    return mgr.get_skill_summary()


@skill(
    pack="progression",
    description="Award XP to a skill for completing an action",
    category="GAME",
    cost=1.0,
)
def award_skill_xp(
    skill_name: str,
    amount: int = 10,
    reason: str = "",
    difficulty: str = "medium",
) -> str:
    """Award XP to a skill. Used by scenes and the game master.

    Args:
        skill_name: Target skill.
        amount: Base XP amount.
        reason: Why the XP was awarded.
        difficulty: Difficulty tier for XP multiplier.
    """
    from engine.world.skill_progression import get_skill_manager

    mgr = get_skill_manager()
    try:
        actual_xp, leveled_up = mgr.award_xp(
            skill_name, amount, reason=reason, difficulty=difficulty,
        )
    except ValueError as e:
        return f"❌ {e}"

    msg = f"✨ +{actual_xp} XP to {skill_name}"
    if reason:
        msg += f" ({reason})"
    if leveled_up:
        new_level = mgr.get_level(skill_name)
        msg += f"\n🎉 LEVEL UP! {skill_name} is now level {new_level}!"

    msg += f"\n  Global level: {mgr.get_global_level()} | Total XP: {mgr.get_total_xp()}"
    return msg


@skill(
    pack="progression",
    description="Check if player can use a specific ability",
    category="GAME",
)
def can_use(skill_name: str, ability: str) -> str:
    """Check if a specific ability is unlocked for the player.

    Args:
        skill_name: Parent skill.
        ability: Ability name to check.
    """
    from engine.world.skill_progression import get_skill_manager, SKILL_UNLOCKS

    mgr = get_skill_manager()
    unlocks = SKILL_UNLOCKS.get(skill_name, {})
    required = unlocks.get(ability)

    if required is None:
        return f"⚠️ Unknown ability '{ability}' for skill '{skill_name}'."

    current = mgr.get_level(skill_name)
    if current >= required:
        return f"✅ {ability} is UNLOCKED (requires {skill_name} Lv{required}, you have Lv{current})"
    return f"🔒 {ability} is LOCKED (requires {skill_name} Lv{required}, you have Lv{current})"


@skill(
    pack="progression",
    description="View recent skill check history",
    category="GAME",
)
def check_history(limit: int = 5) -> str:
    """Show recent skill check results."""
    from engine.world.skill_progression import get_skill_manager

    mgr = get_skill_manager()
    history = mgr.get_check_history(limit=limit)

    if not history:
        return "No skill checks performed yet."

    lines = [f"📋 Last {len(history)} skill checks:"]
    for entry in reversed(history):
        r = entry.get("result", {})
        icon = "✅" if r.get("success") else "❌"
        lines.append(
            f"  {icon} {r.get('skill', '?')}: "
            f"rolled {r.get('roll', 0)} + {r.get('effective', 0)} = {r.get('total', 0)} "
            f"vs DC{r.get('difficulty', 0)} ({r.get('difficulty_name', '?')})"
        )
    return "\n".join(lines)
