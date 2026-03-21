"""Skills for THE GRID scene — pack ``grid``.

CosySim v0.75.  Exposes all four zone interactions as @skill-decorated
functions that LLM agents can call.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _grid_state():
    from content.scenes.grid.grid_scene import _get_grid_state
    return _get_grid_state()


@skill(
    pack="grid",
    description="Buy an item from THE GRID market by item_id.",
    category="GAME",
    cooldown=2.0,
    tags=["grid", "market", "buy"],
)
def grid_buy_item(item_id: str, quantity: int = 1) -> str:
    """Purchase *quantity* units of *item_id* from the Grid market.

    Args:
        item_id: Catalogue item identifier (e.g. ``"stim_v1"``).
        quantity: Number of units to buy (default 1).

    Returns:
        Confirmation or error string.
    """
    result = _grid_state().buy_item(item_id, quantity)
    if result["success"]:
        return f"Bought {result['quantity']}× {result['item']} for ₵{result['paid']:,}."
    return f"Purchase failed: {result['error']}"


@skill(
    pack="grid",
    description="Sell an item from your inventory back to THE GRID market.",
    category="GAME",
    cooldown=2.0,
    tags=["grid", "market", "sell"],
)
def grid_sell_item(item_id: str, quantity: int = 1) -> str:
    """Sell *quantity* units of *item_id* back to the Grid.

    Args:
        item_id: Catalogue item identifier.
        quantity: Number of units to sell (default 1).

    Returns:
        Confirmation or error string.
    """
    result = _grid_state().sell_item(item_id, quantity)
    if result["success"]:
        return f"Sold {result['quantity']}× {result['item']} for ₵{result['earned']:,}."
    return f"Sale failed: {result['error']}"


@skill(
    pack="grid",
    description="Return current market prices and stock levels for all Grid items.",
    category="ENVIRONMENT",
    tags=["grid", "market", "prices"],
)
def grid_get_market_prices() -> str:
    """Return a formatted list of current market prices.

    Returns:
        Newline-delimited price list.
    """
    items = _grid_state().get_market_items()
    lines = [
        f"{item['name']:<22} ₵{item['price']:>6,}  [{item['rarity']}]  stock:{item['stock']}  {item['trend']}"
        for item in items
    ]
    return "\n".join(lines) if lines else "Market unavailable."


@skill(
    pack="grid",
    description="Pledge allegiance to a Neon City faction for reputation benefits.",
    category="SOCIAL",
    cooldown=30.0,
    tags=["grid", "faction", "allegiance"],
)
def grid_faction_pledge(faction_id: str) -> str:
    """Pledge allegiance to *faction_id*.

    Args:
        faction_id: One of: ``OmniCorp``, ``NeoTech``, ``BlackMarket``,
                    ``Ghost_Net``, ``SynthSec``, ``DeepState``.

    Returns:
        Confirmation string.
    """
    result = _grid_state().pledge_allegiance(faction_id)
    if result["success"]:
        return result["message"]
    return f"Pledge failed: {result['error']}"


@skill(
    pack="grid",
    description="Accept a faction mission/quest from THE DEN.",
    category="GAME",
    tags=["grid", "faction", "quest"],
)
def grid_accept_quest(faction_id: str) -> str:
    """Accept the available quest from *faction_id*.

    Args:
        faction_id: Faction to accept quest from.

    Returns:
        Quest brief or error.
    """
    result = _grid_state().accept_quest(faction_id)
    if result["success"]:
        q = result["quest"]
        return (
            f"Quest accepted: [{q['faction']}] {q['title']}\n"
            f"{q['desc']}\n"
            f"Reward: ₵{q['reward_credits']:,} + {q['reward_rep']} REP"
        )
    return f"Quest unavailable: {result['error']}"


@skill(
    pack="grid",
    description="Return the Neon City travel map — all scene nodes with online status.",
    category="ENVIRONMENT",
    tags=["grid", "station", "map", "travel"],
)
def grid_get_travel_map() -> str:
    """Return a formatted list of all Neon City locations.

    Returns:
        Newline-delimited scene location list with online status.
    """
    from content.scenes.grid.grid_scene import CITY_MAP_NODES
    from engine.utils import port_is_open
    lines = []
    for node in CITY_MAP_NODES:
        online = port_is_open(node["port"], timeout=0.2)
        status = "🟢 ONLINE" if online else "🔴 OFFLINE"
        current = " [YOU ARE HERE]" if node.get("is_current") else ""
        lines.append(f"{status}  {node['label']:<22}  port:{node['port']}{current}")
    return "\n".join(lines)


@skill(
    pack="grid",
    description="Query the Broker's intel feed for recent world events and street tips.",
    category="MEMORY",
    tags=["grid", "broker", "intel", "nexus"],
)
def grid_broker_intel(query: str = "") -> str:
    """Return the broker's most recent intel entries, optionally filtered.

    Args:
        query: Optional keyword filter (searches title and desc).

    Returns:
        Newline-delimited intel entries.
    """
    feed = _grid_state().get_intel_feed(15)
    if query:
        query_lower = query.lower()
        feed = [e for e in feed if query_lower in e.get("title", "").lower() or query_lower in e.get("desc", "").lower()]
    if not feed:
        return "No intel available."
    lines = [f"[{e.get('type', '?').upper()}] {e.get('title', 'Unknown')}: {e.get('desc', '')[:80]}" for e in feed]
    return "\n".join(lines)
