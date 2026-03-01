"""
NeonCity Skills — v0.68 "Dark Renaissance"
==========================================

MCP skill functions for the NeonCity Living World Hub.

Covers faction intelligence, live city news, economy exchange, lore purchase,
and reputation standing — all callable by LMS agents via tool use.
"""
from __future__ import annotations

import logging
from typing import Dict

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: NeonCity faction → engine FactionId mapping (mirrors scene constants,
#: kept local to avoid circular import).
_FACTION_ENGINE_IDS: Dict[str, str] = {
    "OmniCorp":    "CORPORATE",
    "NeoTech":     "ARENA_GUILD",
    "BlackMarket": "UNDERGROUND",
    "Ghost_Net":   "HACKER",
    "SynthSec":    "SYNDICATE",
    "DeepState":   "STREET",
}

_BASE_POWERS: Dict[str, int] = {
    "OmniCorp": 78, "NeoTech": 52, "BlackMarket": 22,
    "Ghost_Net": 81, "SynthSec": 43, "DeepState": 70,
}


# ── Faction Status ────────────────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "faction", "city"],
    category=SkillCategory.GAME,
    description=(
        "Get the current status of all six NeonCity factions, "
        "including power levels and player standing with each."
    ),
)
def get_faction_status() -> str:
    """Return a formatted summary of all NeonCity faction standings.

    Queries the reputation manager for the player's standing with each
    faction and blends it with the faction's base power level.

    Returns:
        Multi-line string with faction names, power bars, and standing labels.
    """
    try:
        from engine.characters.reputation import get_reputation_manager
        standings = get_reputation_manager().get_faction_standings("player")
    except Exception as exc:
        logger.warning("Reputation manager unavailable: %s", exc)
        standings = {}

    lines = ["⚡ NEON CITY — FACTION STATUS", "─" * 44]
    for faction, engine_id in _FACTION_ENGINE_IDS.items():
        rep_entry = standings.get(engine_id)
        power = _BASE_POWERS.get(faction, 50)
        label = rep_entry.label if rep_entry else "Neutral"
        standing = rep_entry.standing if rep_entry else 0
        bar = "█" * (power // 10) + "░" * (10 - power // 10)
        sign = "+" if standing >= 0 else ""
        lines.append(
            f"  {faction:<14} [{bar}] {power:>3}  "
            f"Standing: {sign}{standing} ({label})"
        )
    return "\n".join(lines)


# ── City Intel ────────────────────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "intel", "economy"],
    category=SkillCategory.GAME,
    description=(
        "Buy intelligence about a city topic from the information broker. "
        "Costs credits. Topic examples: 'OmniCorp', 'ghost_net', 'blackmarket'."
    ),
    cooldown=10.0,
)
def buy_city_intel(topic: str, budget: int = 50) -> str:
    """Purchase intelligence on a topic from the NeonCity information broker.

    Deducts *budget* credits from the player's economy balance and queries
    the ContentEngine for lore relevant to *topic*.

    Args:
        topic: Subject to research (e.g. ``"OmniCorp"``, ``"ghost_net"``).
        budget: Credits to spend; defaults to ``50``, clamped to 10–200.

    Returns:
        Intelligence report string, or an error if insufficient credits.
    """
    from engine.economy.economy import get_economy_manager, TransactionType

    budget = max(10, min(200, int(budget)))
    try:
        economy = get_economy_manager()
        balance = economy.get_balance("player")
        if balance < budget:
            return (
                f"[BROKER] Insufficient credits. Need {budget}¢, have {balance}¢. "
                "Try a cheaper query (minimum 10¢)."
            )
        economy.transact(-budget, TransactionType.SPEND, "neoncity", f"intel: {topic}")
        new_bal = economy.get_balance("player")
    except Exception as exc:
        logger.warning("Economy error in buy_city_intel: %s", exc)
        new_bal = 0

    lore_text = ""
    try:
        from engine.content.content_engine import get_content_engine
        item = get_content_engine().get_lore(topic.lower(), scene="neoncity")
        if item:
            lore_text = item.body if hasattr(item, "body") else str(item)
    except Exception as exc:
        logger.debug("ContentEngine unavailable: %s", exc)

    if not lore_text:
        lore_text = (
            f"[BROKER] No current intel on '{topic}'. "
            "The city's information network is dark on that topic."
        )
    return f"[INTEL — {topic.upper()}] (Cost: {budget}¢ | Balance: {new_bal}¢)\n{lore_text}"


# ── City News Feed ────────────────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "world", "news"],
    category=SkillCategory.GAME,
    description=(
        "Get what's happening right now in the city — "
        "world events, faction news, and city alerts."
    ),
)
def city_news_feed() -> str:
    """Return the current NeonCity news feed from the world simulation.

    Reads events from WorldSim and the WorldState active event list to
    produce a live news ticker.

    Returns:
        Formatted multi-line news feed string.
    """
    lines = ["📡 NEON CITY NEWS FEED", "─" * 44]
    event_count = 0

    try:
        from engine.world.world_state import get_world_state
        wt = get_world_state().get_time()
        lines.insert(
            1,
            f"  🕐 {wt.game_day_name.upper()} — {wt.game_hour:02d}:00"
            f" | {wt.time_of_day.upper()}",
        )
    except Exception as exc:
        logger.debug("WorldState time unavailable: %s", exc)

    try:
        from engine.world.world_sim import get_world_sim
        for ev in get_world_sim().get_all_events(limit=6):
            desc = getattr(ev, "description", str(ev))
            scene = getattr(ev, "scene", "CITY")
            lines.append(f"  [{scene.upper()}] {desc}")
            event_count += 1
    except Exception as exc:
        logger.debug("WorldSim unavailable: %s", exc)

    try:
        from engine.world.world_state import get_world_state
        for ev in get_world_state().get_active_events(scene="neoncity"):
            label = getattr(ev, "label", str(ev))
            lines.append(f"  ⚠️  ACTIVE: {label}")
            event_count += 1
    except Exception as exc:
        logger.debug("WorldState active events unavailable: %s", exc)

    if event_count == 0:
        lines.append("  [ALL QUIET] No major city events. Stay sharp, runner.")
    return "\n".join(lines)


# ── Credit Exchange ───────────────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "economy", "credits"],
    category=SkillCategory.GAME,
    description=(
        "Convert credits at the NeonCity exchange kiosk. "
        "Direction 'in' deposits credits, 'out' withdraws them."
    ),
    cooldown=5.0,
)
def credit_exchange(amount: int, direction: str = "in") -> str:
    """Convert credits at the city exchange kiosk.

    Args:
        amount: Number of credits to exchange (1–10 000).
        direction: ``"in"`` to deposit credits, ``"out"`` to withdraw.

    Returns:
        Transaction summary string with updated balance.
    """
    from engine.economy.economy import get_economy_manager, TransactionType

    amount = max(1, min(10_000, int(amount)))
    direction = direction.strip().lower()
    if direction not in ("in", "out"):
        return f"[EXCHANGE] Invalid direction '{direction}'. Use 'in' or 'out'."

    try:
        economy = get_economy_manager()
        if direction == "in":
            economy.transact(amount, TransactionType.EARN, "neoncity", "credit_exchange deposit")
            new_bal = economy.get_balance("player")
            return (
                f"[EXCHANGE] ✅ Deposited {amount}¢. New balance: {new_bal}¢. "
                "The exchange kiosk hums quietly."
            )
        # direction == "out"
        balance = economy.get_balance("player")
        if balance < amount:
            return f"[EXCHANGE] ❌ Insufficient funds. Have {balance}¢, need {amount}¢."
        economy.transact(-amount, TransactionType.SPEND, "neoncity", "credit_exchange withdrawal")
        new_bal = economy.get_balance("player")
        return (
            f"[EXCHANGE] ✅ Withdrew {amount}¢. New balance: {new_bal}¢. "
            "Credits dispensed. Watch your back."
        )
    except Exception as exc:
        logger.error("credit_exchange failed: %s", exc)
        return f"[EXCHANGE] ❌ Exchange terminal offline: {exc}"


# ── Reputation Check ──────────────────────────────────────────────────────────

@skill(
    pack="neoncity",
    tags=["game", "reputation", "city"],
    category=SkillCategory.GAME,
    description=(
        "Check your reputation standing across all NeonCity factions. "
        "Shows your label and numeric standing with each faction."
    ),
)
def check_reputation() -> str:
    """Return the player's full reputation summary for NeonCity.

    Queries the reputation manager for standings with the six engine
    factions that correspond to NeonCity factions.

    Returns:
        Formatted reputation report string with overall city standing.
    """
    try:
        from engine.characters.reputation import get_reputation_manager
        standings = get_reputation_manager().get_faction_standings("player")
    except Exception as exc:
        logger.warning("Reputation unavailable: %s", exc)
        return "[REP] Reputation terminal offline. Try again later."

    lines = ["🏙️  NEON CITY — YOUR REPUTATION", "─" * 44]
    total_standing = 0
    for faction, engine_id in _FACTION_ENGINE_IDS.items():
        entry = standings.get(engine_id)
        if entry:
            standing = entry.standing
            label = entry.label
            total_standing += standing
            if standing >= 50:
                icon = "💚"
            elif standing >= 0:
                icon = "🟡"
            else:
                icon = "🔴"
            sign = "+" if standing >= 0 else ""
            lines.append(f"  {icon} {faction:<14} {label:<12} ({sign}{standing})")
        else:
            lines.append(f"  ⬜ {faction:<14} {'Unknown':<12} (0)")

    lines.append("─" * 44)
    avg = total_standing // len(_FACTION_ENGINE_IDS) if _FACTION_ENGINE_IDS else 0
    if avg >= 50:
        overall = "RESPECTED"
    elif avg >= 10:
        overall = "KNOWN"
    elif avg >= -10:
        overall = "NEUTRAL"
    else:
        overall = "HUNTED"
    sign = "+" if avg >= 0 else ""
    lines.append(f"  Overall city standing: {overall} (avg {sign}{avg})")
    return "\n".join(lines)
