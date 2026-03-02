"""World interaction skills for CosySim v0.75.

Exposes the living-world systems — PlayerState, WorldSim, WorldState —
as :func:`@skill`-decorated callables that LLM agents and scene code can
call directly.

Pack: ``world``
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── helpers ────────────────────────────────────────────────────────────────


def _get_player_state():
    """Return the singleton PlayerState instance (lazy import)."""
    from engine.world.player_state import get_player_state

    return get_player_state()


def _get_world_state():
    from engine.world.world_state import get_world_state

    return get_world_state()


def _get_world_sim():
    from engine.world.world_sim import get_world_sim

    return get_world_sim()


# ──── skills ─────────────────────────────────────────────────────────────────


@skill(
    pack="world",
    description="Return the current in-game world time (day, hour, time-of-day).",
    category="ENVIRONMENT",
    tags=["world", "time", "hud"],
)
def get_world_time() -> str:
    """Return a human-readable world-time string.

    Returns:
        E.g. ``"Day 3  22:00 (NIGHT)"``.
    """
    try:
        ws = _get_world_state()
        t = ws.get_time()
        return f"Day {t.game_day}  {t.game_hour:02d}:00  ({t.time_of_day.upper()})"
    except Exception as exc:
        logger.debug("get_world_time failed: %s", exc)
        return "Day 1  00:00  (NIGHT)"


@skill(
    pack="world",
    description="Return the current Neon City weather for a given scene (or globally).",
    category="ENVIRONMENT",
    tags=["world", "weather", "hud"],
)
def get_world_weather(scene: str = "global") -> str:
    """Return the current weather condition for *scene*.

    Args:
        scene: Scene key (e.g. ``"neoncity"``) or ``"global"`` for the
               default weather.

    Returns:
        Weather string e.g. ``"NEON_RAIN"``.
    """
    try:
        ws = _get_world_state()
        weather = ws.get_weather(scene)
        return weather.value if hasattr(weather, "value") else str(weather)
    except Exception as exc:
        logger.debug("get_world_weather failed: %s", exc)
        return "CLEAR"


@skill(
    pack="world",
    description="Return the top active world events (up to 5).",
    category="ENVIRONMENT",
    tags=["world", "events", "hud"],
)
def get_active_events(scene: str = "") -> str:
    """Return a newline-separated list of active world events.

    Args:
        scene: Optional scene filter.  Empty string returns all events.

    Returns:
        Newline-delimited string of event titles and descriptions.
    """
    try:
        ws = _get_world_state()
        events = ws.get_active_events(scene)[:5]
        if not events:
            return "No active world events."
        lines = [f"[{e.event_type}] {e.name}: {e.description}" for e in events]
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("get_active_events failed: %s", exc)
        return "No active world events."


@skill(
    pack="world",
    description="Return the player's current state: credits, reputation, heat, location.",
    category="ENVIRONMENT",
    tags=["world", "player", "hud"],
)
def get_player_state_info() -> str:
    """Return a formatted summary of the player's current state.

    Returns:
        Human-readable summary string.
    """
    try:
        ps = _get_player_state()
        d = ps.to_dict()
        heat_str = f"{d['heat']:.0f}%"
        rep_bar = "█" * int(d["reputation"] / 10) + "░" * (10 - int(d["reputation"] / 10))
        return (
            f"Location: {d['active_location'] or 'UNKNOWN'} | "
            f"Credits: ₵{d['credits']:,} | "
            f"Rep: {rep_bar} {d['reputation']}/100 | "
            f"Heat: 🔥 {heat_str}"
        )
    except Exception as exc:
        logger.debug("get_player_state_info failed: %s", exc)
        return "Player state unavailable."


@skill(
    pack="world",
    description="Return faction standings for all 6 city factions.",
    category="ENVIRONMENT",
    tags=["world", "faction", "hud"],
)
def get_faction_standings() -> str:
    """Return a formatted summary of all faction power levels.

    Returns:
        Newline-delimited faction standings string.
    """
    try:
        ps = _get_player_state()
        standings = ps.to_dict().get("faction_standings", {})
        if not standings:
            return "No faction data available."
        lines = []
        for faction, power in sorted(standings.items(), key=lambda x: -x[1]):
            bar = "█" * int(max(0, power + 100) / 20) + "░" * (10 - int(max(0, power + 100) / 20))
            lines.append(f"{faction:<14} {power:+d}")
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("get_faction_standings failed: %s", exc)
        return "Faction standings unavailable."


@skill(
    pack="world",
    description="Earn credits for the player (e.g. completing a task, winning a game).",
    category="GAME",
    cooldown=2.0,
    tags=["world", "economy", "player"],
)
def earn_credits(amount: int, reason: str = "task_reward") -> str:
    """Add *amount* credits to the player's balance.

    Args:
        amount: Number of credits to add (must be > 0).
        reason: Short label describing the source (logged in history).

    Returns:
        Confirmation string with new balance.
    """
    if amount <= 0:
        return "Amount must be positive."
    try:
        ps = _get_player_state()
        new_bal = ps.earn_credits(amount, reason)
        return f"Earned ₵{amount:,} ({reason}). New balance: ₵{new_bal:,}."
    except Exception as exc:
        logger.warning("earn_credits failed: %s", exc)
        return "Could not update credits."


@skill(
    pack="world",
    description="Spend credits from the player's balance (purchase, bribe, etc.).",
    category="GAME",
    cooldown=2.0,
    tags=["world", "economy", "player"],
)
def spend_credits(amount: int, reason: str = "purchase") -> str:
    """Deduct *amount* credits from the player's balance.

    Args:
        amount: Number of credits to deduct (must be > 0).
        reason: Short label describing the expense.

    Returns:
        Confirmation string, or an error if insufficient funds.
    """
    if amount <= 0:
        return "Amount must be positive."
    try:
        ps = _get_player_state()
        state = ps.to_dict()
        if state["credits"] < amount:
            return f"Insufficient credits. Balance: ₵{state['credits']:,}, required: ₵{amount:,}."
        remaining = ps.spend_credits(amount, reason)
        return f"Spent ₵{amount:,} ({reason}). Remaining balance: ₵{remaining:,}."
    except Exception as exc:
        logger.warning("spend_credits failed: %s", exc)
        return "Could not update credits."


@skill(
    pack="world",
    description="Set the player's current location (updates the HUD location display).",
    category="ENVIRONMENT",
    tags=["world", "location", "hud"],
)
def set_player_location(location: str) -> str:
    """Update the player's active location in the HUD.

    Args:
        location: Location label (e.g. ``"THE PENTHOUSE"``, ``"CLUB NOIR"``).

    Returns:
        Confirmation string.
    """
    try:
        ps = _get_player_state()
        ps.set_location(location)
        return f"Location updated to: {location}."
    except Exception as exc:
        logger.warning("set_player_location failed: %s", exc)
        return "Could not update location."


@skill(
    pack="world",
    description="Adjust the player's heat level (0-100). Heat rises with illegal activity.",
    category="GAME",
    tags=["world", "heat", "player"],
)
def adjust_heat(delta: int) -> str:
    """Increase or decrease the player's heat by *delta*.

    Args:
        delta: Positive = more heat, negative = less heat.

    Returns:
        Confirmation string with new heat level.
    """
    try:
        ps = _get_player_state()
        new_heat = ps.adjust_heat(delta)
        return f"Heat adjusted by {delta:+d}. Current heat: {new_heat}%."
    except Exception as exc:
        logger.warning("adjust_heat failed: %s", exc)
        return "Could not adjust heat."


@skill(
    pack="world",
    description="Return recent world simulation events from the ring buffer (last 10).",
    category="ENVIRONMENT",
    tags=["world", "events", "lore"],
)
def get_recent_sim_events(limit: int = 10) -> str:
    """Return the most recent world simulation events.

    Args:
        limit: Maximum number of events to return (default 10).

    Returns:
        Newline-delimited event log entries.
    """
    try:
        sim = _get_world_sim()
        events = sim.get_event_log()[-limit:]
        if not events:
            return "No recent world events."
        lines = [f"[{e.created_at}] {e.title}: {e.description}" for e in events]
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("get_recent_sim_events failed: %s", exc)
        return "World simulation events unavailable."
