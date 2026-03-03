"""Crew skills for CosySim LLM agents.

Exposes the CrewManager as @skill tools so agents can recruit, dismiss,
manage loyalty, and start operations with the player's crew.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="crew",
    description="Check the player's current crew roster, roles, loyalty, and status.",
    category="GAME",
    tags=["crew", "roster"],
)
def crew_status() -> str:
    """Return a full crew status report."""
    try:
        from engine.world.crew import get_crew_manager, CREW_ROLES
        cm = get_crew_manager()
        members = cm.get_all_members()
        if not members:
            return "You have no crew. Build relationships with NPCs to recruit them."

        lines = [f"Crew: {cm._crew_name} ({len(members)} members)"]
        for m in members:
            avail = "✓ available" if m.available else "✗ on mission"
            lines.append(
                f"  {m.role_icon} {m.character_id.upper()} — {m.role_label}"
                f"  | Loyalty: {int(m.loyalty)}/100 | Lv.{m.level} | {avail}"
            )

        # Active operations
        ops = cm.get_active_operations()
        if ops:
            lines.append(f"\nActive operations ({len(ops)}):")
            for op in ops:
                remaining = op.time_remaining
                mins = remaining // 60
                lines.append(f"  ⚡ {op.label} — {mins}m remaining, crew: {', '.join(op.assigned_crew)}")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("crew_status failed: %s", exc)
        return f"Error getting crew status: {exc}"


@skill(
    pack="crew",
    description="Attempt to recruit an NPC into the player's crew. Requires high relationship trust (40+).",
    category="GAME",
    tags=["crew", "recruit"],
)
def crew_recruit(character_id: str, role: str = "unknown", notes: str = "") -> str:
    """Recruit *character_id* into the crew.

    Args:
        character_id: The NPC's identifier (e.g. 'lola', 'viktor').
        role: Crew role — fixer/hacker/muscle/medic/driver/tech/lookout/face/supplier.
        notes: Optional note about the recruitment circumstances.
    """
    try:
        from engine.world.crew import get_crew_manager, CREW_ROLES
        if role not in CREW_ROLES:
            valid = ", ".join(CREW_ROLES.keys())
            return f"Unknown role '{role}'. Valid roles: {valid}"
        cm = get_crew_manager()
        ok, msg = cm.recruit(character_id, role=role, notes=notes)
        return msg
    except Exception as exc:
        logger.warning("crew_recruit failed: %s", exc)
        return f"Error recruiting crew: {exc}"


@skill(
    pack="crew",
    description="Dismiss a crew member, removing them from the active roster.",
    category="GAME",
    tags=["crew", "dismiss"],
)
def crew_dismiss(character_id: str, reason: str = "") -> str:
    """Dismiss *character_id* from the crew.

    Args:
        character_id: The crew member to dismiss.
        reason: Optional reason for dismissal.
    """
    try:
        from engine.world.crew import get_crew_manager
        cm = get_crew_manager()
        ok = cm.dismiss(character_id, reason=reason)
        if not ok:
            return f"{character_id} is not in your crew."
        return f"{character_id} has been dismissed from the crew."
    except Exception as exc:
        logger.warning("crew_dismiss failed: %s", exc)
        return f"Error dismissing crew member: {exc}"


@skill(
    pack="crew",
    description="Adjust a crew member's loyalty score (positive = more loyal, negative = less).",
    category="GAME",
    tags=["crew", "loyalty"],
)
def crew_adjust_loyalty(character_id: str, delta: float, reason: str = "") -> str:
    """Adjust *character_id*'s loyalty by *delta*.

    Args:
        character_id: Crew member to update.
        delta: Amount to adjust (e.g. +10 for favour, -15 for betrayal).
        reason: Optional reason (logged in member notes).
    """
    try:
        from engine.world.crew import get_crew_manager
        cm = get_crew_manager()
        val = cm.adjust_loyalty(character_id, delta=delta, reason=reason)
        if val is None:
            return f"{character_id} is not in your crew."
        direction = "up" if delta > 0 else "down"
        return f"{character_id}'s loyalty moved {direction} to {int(val)}/100."
    except Exception as exc:
        logger.warning("crew_adjust_loyalty failed: %s", exc)
        return f"Error adjusting loyalty: {exc}"


@skill(
    pack="crew",
    description="Deploy crew members on an operation (recon/heist/extraction/deal/hit/hack). They earn XP and credits on success.",
    category="GAME",
    tags=["crew", "operation", "mission"],
)
def crew_start_operation(
    op_type: str,
    crew_members: str,
    label: str = "",
    duration_minutes: int = 60,
    reward_credits: int = 0,
) -> str:
    """Start a crew operation.

    Args:
        op_type: Operation type — recon/heist/extraction/deal/hit/hack.
        crew_members: Comma-separated list of character IDs to assign.
        label: Optional operation label/description.
        duration_minutes: How long the operation takes (default 60 min).
        reward_credits: Credits earned on completion.
    """
    try:
        from engine.world.crew import get_crew_manager, OPERATION_TYPES
        if op_type not in OPERATION_TYPES:
            valid = ", ".join(OPERATION_TYPES.keys())
            return f"Unknown operation type '{op_type}'. Valid types: {valid}"
        crew = [c.strip() for c in crew_members.split(",") if c.strip()]
        if not crew:
            return "No crew members specified."
        cm = get_crew_manager()
        ok, msg = cm.start_operation(
            op_type=op_type,
            assigned_crew=crew,
            label=label,
            duration_secs=duration_minutes * 60,
            reward_credits=reward_credits,
            reward_xp=25,
        )
        return msg
    except Exception as exc:
        logger.warning("crew_start_operation failed: %s", exc)
        return f"Error starting operation: {exc}"


@skill(
    pack="crew",
    description="Check if any crew operations have completed and collect their rewards.",
    category="GAME",
    tags=["crew", "operation", "rewards"],
)
def crew_check_operations() -> str:
    """Check for completed crew operations and collect rewards.

    Returns a summary of what was completed and what was earned.
    """
    try:
        from engine.world.crew import get_crew_manager
        cm = get_crew_manager()
        results = cm.check_operations()
        if not results:
            ops = cm.get_active_operations()
            if ops:
                lines = [f"No operations complete yet. {len(ops)} active:"]
                for op in ops:
                    mins = op.time_remaining // 60
                    lines.append(f"  ⚡ {op.label} — {mins}m remaining")
                return "\n".join(lines)
            return "No active operations."

        lines = [f"{len(results)} operation(s) complete!"]
        total_credits = 0
        for result in results:
            total_credits += result.get("credits_earned", 0)
            lines.append(
                f"  ✓ {result['label']} ({result['op_type']})"
                f"  — ₵{result['credits_earned']:,} earned, "
                f"{result['reward_xp']} XP per crew"
            )
        if total_credits:
            lines.append(f"Total earned: ₵{total_credits:,}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("crew_check_operations failed: %s", exc)
        return f"Error checking operations: {exc}"


@skill(
    pack="crew",
    description="Set a custom name for the player's crew.",
    category="GAME",
    tags=["crew", "name"],
)
def crew_set_name(name: str) -> str:
    """Set the crew's name.

    Args:
        name: New crew name (e.g. 'The Ghost Circuit').
    """
    try:
        from engine.world.crew import get_crew_manager
        cm = get_crew_manager()
        cm.set_crew_name(name)
        return f"Crew renamed to '{name}'."
    except Exception as exc:
        logger.warning("crew_set_name failed: %s", exc)
        return f"Error setting crew name: {exc}"


@skill(
    pack="crew",
    description="Check if a specific NPC can be recruited (relationship score, available slots, etc.).",
    category="GAME",
    tags=["crew", "recruit", "check"],
)
def crew_can_recruit(character_id: str) -> str:
    """Check whether *character_id* is eligible for recruitment.

    Args:
        character_id: The NPC to check.
    """
    try:
        from engine.world.crew import get_crew_manager
        cm = get_crew_manager()
        ok, reason = cm.can_recruit(character_id)
        if ok:
            return f"{character_id} CAN be recruited. Use crew_recruit to bring them in."
        return f"{character_id} CANNOT be recruited: {reason}"
    except Exception as exc:
        logger.warning("crew_can_recruit failed: %s", exc)
        return f"Error checking recruitment eligibility: {exc}"
