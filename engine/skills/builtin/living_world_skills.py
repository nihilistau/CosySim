"""MCP skills for the Living World systems — market, NPC routines, factions.

These skills expose the Phase 5 Living World modules to LLM agents and
scene code:

* **Market** — browse goods, buy, sell, check prices, view trade history
* **NPC Routines** — find NPCs by location, check schedules, see who's nearby
* **Faction AI** — view faction decisions, active wars, territory shifts
* **Living World** — overall status, event log, manual tick

Pack: ``living_world``
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── Lazy helpers ────


def _market():
    from engine.world.market import get_market
    return get_market()


def _routines():
    from engine.world.npc_routines import get_routine_manager
    return get_routine_manager()


def _faction_ai():
    from engine.world.faction_ai import get_faction_ai
    return get_faction_ai()


def _living_world():
    from engine.world.living_world import get_living_world
    return get_living_world()


# ──────────────────────────────────────────────────────────────────────────────
# Market Skills
# ──────────────────────────────────────────────────────────────────────────────


@skill(
    pack="living_world",
    description="Browse goods available for purchase. Filter by category: weapons, tech, consumables, contraband, intel, luxury.",
    category="GAME",
    tags=["market", "economy", "shop"],
)
def browse_goods(category: str = "") -> str:
    """List all tradable goods, optionally filtered by category."""
    goods = _market().get_goods(category)
    if not goods:
        return f"No goods found{' in category: ' + category if category else ''}."
    lines = [f"📦 **{g['name']}** ({g['category']}) — ¤{g['current_price']} "
             f"[base ¤{g['base_price']}] supply:{g['supply']:.0f} demand:{g['demand']:.0f}"
             f"{' ⚠️ILLEGAL' if g.get('illegal') else ''}"
             for g in goods]
    return f"**Market Goods** ({len(goods)} items):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="Check prices at shops in a district. Shows adjusted prices including shop markup and territory control effects.",
    category="GAME",
    tags=["market", "prices", "shop"],
)
def check_prices(district: str = "DOWNTOWN", category: str = "") -> str:
    """Get shop prices in a district."""
    prices = _market().get_prices(district, category)
    if not prices:
        return f"No shops selling{' ' + category if category else ''} in {district}."
    lines = [f"  {p['name']}: ¤{p['shop_price']} at {p['shop_name']}"
             f"{' ⚠️' if p.get('illegal') else ''}"
             for p in prices[:20]]
    return f"**Prices in {district}** ({len(prices)} items):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="Buy an item from a district shop. Specify the good_id and quantity.",
    category="GAME",
    tags=["market", "buy", "shop"],
    cost=1.0,
)
def buy_item(good_id: str, district: str = "DOWNTOWN", quantity: int = 1) -> str:
    """Purchase goods from a shop."""
    result = _market().buy(district, good_id, quantity)
    if result["status"] == "error":
        return f"❌ Cannot buy: {result['reason']}"
    return (f"✅ Bought {result['quantity']}× {result['good_name']} "
            f"from {result['shop']} for ¤{result['total']} total "
            f"(¤{result['unit_price']}/each)"
            f"{' ⚠️ This item is illegal!' if result.get('illegal') else ''}")


@skill(
    pack="living_world",
    description="Sell an item to a district shop. Sell price is ~60% of market value.",
    category="GAME",
    tags=["market", "sell", "shop"],
    cost=1.0,
)
def sell_item(good_id: str, district: str = "DOWNTOWN", quantity: int = 1) -> str:
    """Sell goods to a shop."""
    result = _market().sell(district, good_id, quantity)
    if result["status"] == "error":
        return f"❌ Cannot sell: {result['reason']}"
    return (f"✅ Sold {result['quantity']}× {result['good_name']} "
            f"for ¤{result['total']} (¤{result['unit_price']}/each)")


@skill(
    pack="living_world",
    description="View recent trade history — your buys and sells.",
    category="GAME",
    tags=["market", "history"],
)
def trade_history(limit: int = 10) -> str:
    """Show recent market transactions."""
    records = _market().get_history(limit)
    if not records:
        return "No trade history yet."
    lines = [f"  {r['action'].upper()} {r['quantity']}× {r['good_id']} "
             f"@ ¤{r['unit_price']} = ¤{r['total']} ({r['district']})"
             for r in records]
    return f"**Trade History** ({len(records)} records):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="View market statistics — total goods, shops, trade volume, average prices.",
    category="GAME",
    tags=["market", "stats"],
)
def market_stats() -> str:
    """Get overall market statistics."""
    stats = _market().get_stats()
    return (f"**Market Stats**: {stats['total_goods']} goods, "
            f"{stats['total_shops']} shops, "
            f"avg price ¤{stats['avg_good_price']:.0f}, "
            f"trade volume ¤{stats['trade_volume']}, "
            f"{stats['total_buys']} buys / {stats['total_sells']} sells, "
            f"tick #{stats['tick_count']}")


# ──────────────────────────────────────────────────────────────────────────────
# NPC Routine Skills
# ──────────────────────────────────────────────────────────────────────────────


@skill(
    pack="living_world",
    description="Find where an NPC currently is and what they're doing.",
    category="GAME",
    tags=["npc", "location", "routine"],
)
def find_npc(character_id: str) -> str:
    """Locate an NPC and see their current activity."""
    info = _routines().get_npc_location(character_id)
    if not info:
        return f"NPC '{character_id}' not found in routine system."
    status = "⚠️ INTERRUPTED" if info.get("interrupted") else "🟢 On schedule"
    return (f"**{character_id}** ({info.get('archetype', 'unknown')}) — {status}\n"
            f"  📍 Location: {info['location']}\n"
            f"  🎭 Activity: {info['activity']}")


@skill(
    pack="living_world",
    description="See all NPCs currently at a specific location/scene.",
    category="GAME",
    tags=["npc", "location"],
)
def npcs_at_location(location: str) -> str:
    """List all NPCs currently at a given location."""
    npcs = _routines().get_npcs_at(location)
    if not npcs:
        return f"No NPCs currently at '{location}'."
    lines = [f"  {n['character_id']} ({n.get('archetype', '?')}): {n['activity']}"
             for n in npcs]
    return f"**NPCs at {location}** ({len(npcs)}):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="View the full daily schedule for an NPC.",
    category="GAME",
    tags=["npc", "routine", "schedule"],
)
def npc_schedule(character_id: str) -> str:
    """Show an NPC's complete daily routine."""
    routine = _routines().get_routine(character_id)
    if not routine:
        return f"No routine found for '{character_id}'."
    lines = [f"  {e['time_of_day']:12s} → {e['location']:20s} | {e['activity']}"
             for e in routine.get("schedule", [])]
    return (f"**{character_id}** ({routine['archetype']}) — "
            f"Home: {routine['home_district']}\n" + "\n".join(lines))


@skill(
    pack="living_world",
    description="Get NPC routine system statistics — how many NPCs, who's interrupted, etc.",
    category="GAME",
    tags=["npc", "stats"],
)
def npc_routine_stats() -> str:
    """Show NPC routine system overview."""
    stats = _routines().get_stats()
    arch = ", ".join(f"{k}={v}" for k, v in stats.get("archetypes", {}).items())
    return (f"**NPC Routines**: {stats['total_npcs']} registered, "
            f"{stats['active']} active, {stats['interrupted']} interrupted\n"
            f"  Last time slot: {stats['last_time_slot']}\n"
            f"  Archetypes: {arch}")


# ──────────────────────────────────────────────────────────────────────────────
# Faction AI Skills
# ──────────────────────────────────────────────────────────────────────────────


@skill(
    pack="living_world",
    description="View recent faction AI decisions — what each faction chose to do.",
    category="GAME",
    tags=["faction", "ai", "decisions"],
)
def faction_decisions(faction: str = "", limit: int = 10) -> str:
    """Show recent faction AI decisions."""
    decisions = _faction_ai().get_history(faction, limit)
    if not decisions:
        return "No faction decisions recorded yet."
    lines = [f"  [{d['faction']}] {d['action'].upper()} in {d['target_district']}"
             f"{' vs ' + d['target_faction'] if d.get('target_faction') else ''}"
             f" (Δ{d['control_delta']:+.1f}%) — {d['narrative'][:80]}"
             for d in decisions]
    return f"**Faction Decisions** ({len(decisions)}):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="Check if any faction wars are currently active.",
    category="GAME",
    tags=["faction", "war"],
)
def active_wars() -> str:
    """Show currently active faction wars."""
    wars = _faction_ai().get_active_wars()
    if not wars:
        return "No active faction wars. The streets are quiet... for now."
    lines = [f"  ⚔️ {district}: {info['attacker']} vs {info['defender']}"
             for district, info in wars.items()]
    return f"**Active Wars** ({len(wars)}):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="Get faction AI statistics — decision distribution, war count, ticks.",
    category="GAME",
    tags=["faction", "stats"],
)
def faction_ai_stats() -> str:
    """Show faction AI overview."""
    stats = _faction_ai().get_stats()
    dist = ", ".join(f"{k}={v}" for k, v in stats.get("action_distribution", {}).items())
    return (f"**Faction AI**: {stats['total_decisions']} decisions over "
            f"{stats['tick_count']} ticks, {stats['active_wars']} active wars\n"
            f"  Actions: {dist}")


# ──────────────────────────────────────────────────────────────────────────────
# Living World Skills
# ──────────────────────────────────────────────────────────────────────────────


@skill(
    pack="living_world",
    description="Get the full living world status — market, NPCs, factions, weather, events.",
    category="SYSTEM",
    tags=["world", "status"],
)
def world_status() -> str:
    """Comprehensive living world snapshot."""
    status = _living_world().get_status()
    parts = [
        f"**Living World** — {'🟢 Running' if status['running'] else '🔴 Stopped'} "
        f"(tick #{status['tick_count']})",
        f"  🕐 Game Time: {status.get('game_time', 'unknown')}",
        f"  🌤️ Weather: {status.get('weather', 'unknown')}",
    ]

    mkt = status.get("market", {})
    if mkt:
        parts.append(f"  📊 Market: {mkt.get('total_goods', 0)} goods, "
                      f"¤{mkt.get('trade_volume', 0)} traded")

    npc = status.get("npc_routines", {})
    if npc:
        parts.append(f"  👥 NPCs: {npc.get('total_npcs', 0)} registered, "
                      f"{npc.get('interrupted', 0)} interrupted")

    fai = status.get("faction_ai", {})
    if fai:
        parts.append(f"  ⚔️ Factions: {fai.get('total_decisions', 0)} decisions, "
                      f"{fai.get('active_wars', 0)} wars")

    events = status.get("recent_events", [])
    if events:
        parts.append(f"  📰 Recent events: {len(events)}")
        for e in events[:3]:
            parts.append(f"    • {e.get('name', '?')}: {e.get('narrative', '')[:60]}...")

    return "\n".join(parts)


@skill(
    pack="living_world",
    description="View recent world events — what's been happening in NeonCity.",
    category="GAME",
    tags=["world", "events"],
)
def world_events(limit: int = 10) -> str:
    """Show recent world events."""
    events = _living_world().get_event_log(limit)
    if not events:
        return "No world events have occurred yet."
    lines = [f"  [{e.get('type', '?')}] {e['name']} in {e['district']}: "
             f"{e.get('narrative', '')[:80]}"
             for e in events]
    return f"**World Events** ({len(events)}):\n" + "\n".join(lines)


@skill(
    pack="living_world",
    description="Get living world statistics — ticks, events, weather history.",
    category="SYSTEM",
    tags=["world", "stats"],
)
def living_world_stats() -> str:
    """Show living world system statistics."""
    stats = _living_world().get_stats()
    dist = ", ".join(f"{k}={v}" for k, v in stats.get("event_type_distribution", {}).items())
    return (f"**Living World Stats**: {stats['tick_count']} ticks, "
            f"{'🟢 running' if stats['running'] else '🔴 stopped'}\n"
            f"  Events: {stats['total_events']} total\n"
            f"  Distribution: {dist}\n"
            f"  Weather: {stats['current_weather']}")


@skill(
    pack="living_world",
    description="Manually trigger one living-world tick cycle (for testing/debugging).",
    category="SYSTEM",
    tags=["world", "debug"],
    cost=2.0,
)
def manual_tick() -> str:
    """Execute one tick of the living world manually."""
    lw = _living_world()
    lw._init_subsystems()
    result = lw.tick()
    parts = [
        f"**Tick #{result.tick_number}** — {result.game_time}",
        f"  NPCs moved: {result.npc_transitions}",
        f"  Faction decisions: {result.faction_decisions}",
        f"  Market changes: {result.market_changes}",
        f"  Weather changed: {result.weather_changed}",
        f"  Wars active: {result.wars_active}",
    ]
    for e in result.events_generated:
        parts.append(f"  📰 {e['name']}: {e.get('narrative', '')[:60]}")
    return "\n".join(parts)
