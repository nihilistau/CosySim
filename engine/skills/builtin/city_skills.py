"""City map skill pack for CosySim v0.82 "THE OPEN WORLD".

Provides LLM-agent-callable skills for navigating Neon City,
querying the city map, and tracking NPC locations.

All skills are registered under pack="city".
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _map():
    from engine.world.city_map import get_city_map
    return get_city_map()


# ---------------------------------------------------------------------------
# Navigation Skills
# ---------------------------------------------------------------------------

@skill(
    pack="city",
    description="Travel to a named location in Neon City. Returns travel cost and result.",
    category="ENVIRONMENT",
    cooldown=2.0,
)
def city_travel(destination: str) -> str:
    """Move the player to *destination*.

    Args:
        destination: Exact scene name (e.g. 'THE GRID', 'SIGNAL').

    Returns:
        JSON string with success, from/to, travel_time_min, energy_cost, heat_add, message.
    """
    import json
    result = _map().travel(destination)
    return json.dumps(result.to_dict())


@skill(
    pack="city",
    description="Get the player's current location in Neon City.",
    category="ENVIRONMENT",
)
def city_get_location() -> str:
    """Return the player's current scene/location name."""
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    return ps.active_location or "UNKNOWN"


@skill(
    pack="city",
    description="List all locations adjacent to the player's current position with travel costs.",
    category="ENVIRONMENT",
)
def city_get_neighbors(location: Optional[str] = None) -> str:
    """Return adjacent nodes from *location* (defaults to player location).

    Args:
        location: Node name to query from; defaults to current player location.

    Returns:
        JSON list of neighbor dicts with name, district, port, travel_time_min, energy_cost.
    """
    import json
    from engine.world.player_state import get_player_state
    if not location:
        location = get_player_state().active_location or "SIGNAL"
    neighbors = _map().get_neighbors(location)
    return json.dumps(neighbors)


@skill(
    pack="city",
    description="Find the shortest route between two locations in Neon City.",
    category="ENVIRONMENT",
)
def city_get_route(origin: str, destination: str) -> str:
    """Return the shortest path and total costs between *origin* and *destination*.

    Args:
        origin: Starting location name.
        destination: Target location name.

    Returns:
        JSON with path list, total_time, total_energy, total_heat, first_hop.
    """
    import json
    route = _map().get_route(origin, destination)
    if route is None:
        return json.dumps({"error": f"No route from {origin} to {destination}"})
    return json.dumps(route)


@skill(
    pack="city",
    description="List all locations in Neon City grouped by district.",
    category="ENVIRONMENT",
)
def city_list_locations(district: Optional[str] = None) -> str:
    """Return all city nodes, optionally filtered by district.

    Args:
        district: District name to filter by (e.g. 'TECH_DISTRICT'). None = all.

    Returns:
        JSON list of node dicts.
    """
    import json
    from engine.world.city_map import DISTRICTS
    nodes = _map().get_all_nodes()
    if district:
        upper = district.upper()
        nodes = [n for n in nodes if n.get("district", "").upper() == upper]
    return json.dumps({"nodes": nodes, "districts": list(DISTRICTS.keys())})


# ---------------------------------------------------------------------------
# NPC Location Skills
# ---------------------------------------------------------------------------

@skill(
    pack="city",
    description="Find where an NPC currently is in Neon City.",
    category="ENVIRONMENT",
)
def city_find_npc(npc_id: str) -> str:
    """Return the current location of *npc_id*.

    Args:
        npc_id: NPC identifier (e.g. 'lola', 'viktor').

    Returns:
        Location name string, or 'unknown' if not tracked.
    """
    loc = _map().get_npc_location(npc_id)
    return loc if loc else "unknown"


@skill(
    pack="city",
    description="List all NPCs currently at a given location.",
    category="ENVIRONMENT",
)
def city_who_is_at(location: str) -> str:
    """Return NPCs present at *location*.

    Args:
        location: Scene name to query.

    Returns:
        Comma-separated NPC IDs, or 'nobody' if empty.
    """
    npcs = _map().get_npcs_at(location)
    return ", ".join(npcs) if npcs else "nobody"


@skill(
    pack="city",
    description="Get a full snapshot of all NPC locations across Neon City.",
    category="ENVIRONMENT",
)
def city_all_npc_locations() -> str:
    """Return all tracked NPC locations as a JSON dict.

    Returns:
        JSON dict mapping npc_id to location name.
    """
    import json
    return json.dumps(_map().get_all_npc_locations())
