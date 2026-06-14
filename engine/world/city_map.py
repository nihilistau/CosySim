"""City map engine for CosySim v0.82 "THE OPEN WORLD".

Models Neon City as a graph of 16 scene nodes grouped into districts.
Tracks player's current location, computes travel costs, fires world
events on travel, and integrates with PlayerState (energy/heat).

Districts:
  DOWNTOWN      — THE VELVET PIT, CLUB NOIR, THE OBSCURA
  COMBAT_ZONE   — THE COLOSSEUM, THE RUSTY ANCHOR
  HIGHRISE      — THE PENTHOUSE, Command Center
  UNDERWORLD    — THE SCORE, THE BRIEFING ROOM
  TECH_DISTRICT — THE LAB, THE GRID, THE ARCADE, SIGNAL
  OUTSKIRTS     — THE SHATTERED THRONE, NEON CITY (hub), ASSET STUDIO

Usage::

    from engine.world.city_map import get_city_map

    cm = get_city_map()
    result = cm.travel("THE GRID")   # moves player, returns cost info
    nodes = cm.get_all_nodes()
    route = cm.get_route("SIGNAL", "THE PENTHOUSE")
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Module-level wrapper for patching in tests
def get_player_state():  # noqa: N802
    from engine.world.player_state import get_player_state as _get
    return _get()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Adjacency graph — (node_a, node_b, travel_cost_seconds, energy_cost, heat_add)
# Travel cost in in-game minutes; energy_cost 0–10; heat_add 0–5
_EDGES: List[Tuple[str, str, int, int, int]] = [
    # Downtown connections
    ("THE VELVET PIT",       "CLUB NOIR",              5,  1, 0),
    ("THE VELVET PIT",       "THE OBSCURA",            8,  2, 0),
    ("CLUB NOIR",            "THE OBSCURA",            6,  1, 0),
    # Combat zone
    ("THE COLOSSEUM",        "THE RUSTY ANCHOR",       7,  2, 0),
    ("THE RUSTY ANCHOR",     "THE VELVET PIT",         10, 3, 1),
    # Highrise
    ("THE PENTHOUSE",        "Command Center",         4,  1, 1),
    ("THE PENTHOUSE",        "CLUB NOIR",              12, 2, 2),
    # Underworld
    ("THE SCORE",            "THE BRIEFING ROOM",      5,  1, 1),
    ("THE SCORE",            "THE COLOSSEUM",          8,  3, 1),
    ("THE BRIEFING ROOM",    "THE OBSCURA",            10, 2, 2),
    # Tech district
    ("THE LAB",              "THE GRID",               6,  1, 0),
    ("THE GRID",             "THE ARCADE",             5,  1, 0),
    ("THE ARCADE",           "SIGNAL",                 4,  1, 0),
    ("SIGNAL",               "THE LAB",                8,  2, 0),
    # Cross-district routes
    ("SIGNAL",               "Command Center",         15, 3, 1),
    ("THE GRID",             "THE SCORE",              12, 3, 2),
    ("THE LAB",              "THE PENTHOUSE",          20, 5, 2),
    ("THE ARCADE",           "THE VELVET PIT",         10, 2, 0),
    ("THE COLOSSEUM",        "NEON CITY",              8,  2, 0),
    ("NEON CITY",            "THE SHATTERED THRONE",   15, 4, 2),
    ("NEON CITY",            "ASSET STUDIO",           10, 1, 0),
    ("NEON CITY",            "THE VELVET PIT",         7,  1, 0),
    ("NEON CITY",            "SIGNAL",                 10, 2, 0),
    ("THE SHATTERED THRONE", "THE BRIEFING ROOM",      12, 3, 3),
    # v1.52.0 — THE ORACLE (deep in tech district, accessible from Grid and NeonCity)
    ("THE GRID",             "THE ORACLE",             8,  2, 0),
    ("NEON CITY",            "THE ORACLE",             12, 3, 0),
]

# District definitions
DISTRICTS: Dict[str, List[str]] = {
    "DOWNTOWN":       ["THE VELVET PIT", "CLUB NOIR", "THE OBSCURA"],
    "COMBAT_ZONE":    ["THE COLOSSEUM", "THE RUSTY ANCHOR"],
    "HIGHRISE":       ["THE PENTHOUSE", "Command Center"],
    "UNDERWORLD":     ["THE SCORE", "THE BRIEFING ROOM"],
    "TECH_DISTRICT":  ["THE LAB", "THE GRID", "THE ARCADE", "SIGNAL", "THE ORACLE"],
    "OUTSKIRTS":      ["THE SHATTERED THRONE", "NEON CITY", "ASSET STUDIO"],
}

# Scene ports (for UI deep-link)
SCENE_PORTS: Dict[str, int] = {
    "SIGNAL":               5555,
    "THE PENTHOUSE":        5556,
    "THE VELVET PIT":       5557,
    "THE RUSTY ANCHOR":     5558,
    "CLUB NOIR":            5559,
    "THE OBSCURA":          5560,
    "THE COLOSSEUM":        5561,
    "THE SHATTERED THRONE": 5562,
    "NEON CITY":            5563,
    "THE LAB":              5564,
    "THE SCORE":            5565,
    "Command Center":       5566,
    "THE ARCADE":           5567,
    "ASSET STUDIO":         5568,
    "THE GRID":             5569,
    "THE BRIEFING ROOM":    5580,
    "THE ORACLE":           5572,  # v1.52.0 — Claude's signature scene
}

# Starting location
_DEFAULT_LOCATION = "SIGNAL"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CityNode:
    """A single location in Neon City."""

    name: str
    district: str
    port: int
    # runtime state
    npc_names: List[str] = field(default_factory=list)
    player_count: int = 0
    is_active: bool = False  # scene server running

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "district": self.district,
            "port": self.port,
            "npc_names": self.npc_names,
            "player_count": self.player_count,
            "is_active": self.is_active,
        }


@dataclass
class TravelResult:
    """Result of a player.travel() call."""

    success: bool
    from_location: str
    to_location: str
    travel_time: int   # in-game minutes
    energy_cost: int
    heat_add: int
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "from": self.from_location,
            "to": self.to_location,
            "travel_time_min": self.travel_time,
            "energy_cost": self.energy_cost,
            "heat_add": self.heat_add,
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# CityMap
# ---------------------------------------------------------------------------

class CityMap:
    """Singleton city map for Neon City.

    Maintains the graph of scene nodes, adjacency edges, NPC locations,
    and travel logic. Thread-safe via internal lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: Dict[str, CityNode] = {}
        self._adjacency: Dict[str, Dict[str, Tuple[int, int, int]]] = {}
        self._npc_locations: Dict[str, str] = {}  # npc_id → node_name
        self._build_graph()

    # ── Graph Construction ────────────────────────────────────────────────

    def _build_graph(self) -> None:
        # Create nodes
        node_to_district = {}
        for district, names in DISTRICTS.items():
            for name in names:
                node_to_district[name] = district

        for name, port in SCENE_PORTS.items():
            district = node_to_district.get(name, "UNKNOWN")
            self._nodes[name] = CityNode(name=name, district=district, port=port)

        # Build adjacency (bidirectional)
        for src, dst, cost, energy, heat in _EDGES:
            if src not in self._adjacency:
                self._adjacency[src] = {}
            if dst not in self._adjacency:
                self._adjacency[dst] = {}
            self._adjacency[src][dst] = (cost, energy, heat)
            self._adjacency[dst][src] = (cost, energy, heat)

    # ── Node Access ───────────────────────────────────────────────────────

    def get_node(self, name: str) -> Optional[CityNode]:
        """Return a CityNode by name."""
        return self._nodes.get(name)

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        """Return all nodes as dicts."""
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    def get_district_nodes(self, district: str) -> List[CityNode]:
        """Return all nodes in a district."""
        return [n for n in self._nodes.values() if n.district == district]

    def get_neighbors(self, location: str) -> List[Dict[str, Any]]:
        """Return adjacent nodes with travel costs."""
        result = []
        for dst, (cost, energy, heat) in self._adjacency.get(location, {}).items():
            node = self._nodes.get(dst)
            if node:
                result.append({
                    "name": dst,
                    "district": node.district,
                    "port": node.port,
                    "travel_time_min": cost,
                    "energy_cost": energy,
                    "heat_add": heat,
                })
        return result

    # ── Pathfinding ───────────────────────────────────────────────────────

    def get_route(self, origin: str, destination: str) -> Optional[Dict[str, Any]]:
        """BFS shortest path between two nodes.

        Returns first hop, total travel time, energy and heat totals.
        Returns None if no path exists.
        """
        if origin == destination:
            return {"path": [origin], "total_time": 0, "total_energy": 0, "total_heat": 0}

        from collections import deque
        queue: deque = deque()
        queue.append((origin, [origin], 0, 0, 0))
        visited = {origin}

        while queue:
            current, path, t_time, t_energy, t_heat = queue.popleft()
            for nxt, (cost, energy, heat) in self._adjacency.get(current, {}).items():
                if nxt in visited:
                    continue
                new_path = path + [nxt]
                new_time = t_time + cost
                new_energy = t_energy + energy
                new_heat = t_heat + heat
                if nxt == destination:
                    return {
                        "path": new_path,
                        "total_time": new_time,
                        "total_energy": new_energy,
                        "total_heat": new_heat,
                        "first_hop": new_path[1] if len(new_path) > 1 else destination,
                    }
                visited.add(nxt)
                queue.append((nxt, new_path, new_time, new_energy, new_heat))

        return None

    # ── Travel ────────────────────────────────────────────────────────────

    def travel(self, destination: str) -> TravelResult:
        """Move the player to *destination*.

        Validates the destination exists, checks adjacency (direct travel only),
        applies energy/heat costs to PlayerState, updates active_location, and
        fires a ``player_travel`` event via EventCascade.

        Args:
            destination: Node name to travel to.

        Returns:
            TravelResult with success flag and cost breakdown.
        """
        ps = get_player_state()
        origin = ps.active_location or _DEFAULT_LOCATION

        if destination not in self._nodes:
            return TravelResult(
                success=False,
                from_location=origin,
                to_location=destination,
                travel_time=0,
                energy_cost=0,
                heat_add=0,
                message=f"Unknown location: {destination}",
            )

        if origin == destination:
            return TravelResult(
                success=True,
                from_location=origin,
                to_location=destination,
                travel_time=0,
                energy_cost=0,
                heat_add=0,
                message=f"Already at {destination}.",
            )

        # Check direct adjacency
        edge = self._adjacency.get(origin, {}).get(destination)
        if edge is None:
            # Find route to give useful next-hop hint
            route = self.get_route(origin, destination)
            if route:
                hint = f"Travel via {route['first_hop']} first."
            else:
                hint = "No known route."
            return TravelResult(
                success=False,
                from_location=origin,
                to_location=destination,
                travel_time=0,
                energy_cost=0,
                heat_add=0,
                message=f"Cannot travel directly from {origin} to {destination}. {hint}",
            )

        travel_time, energy_cost, heat_add = edge

        # Check energy
        if ps.energy < energy_cost:
            return TravelResult(
                success=False,
                from_location=origin,
                to_location=destination,
                travel_time=travel_time,
                energy_cost=energy_cost,
                heat_add=heat_add,
                message=f"Not enough energy to travel (need {energy_cost}, have {ps.energy}).",
            )

        # Apply costs
        ps.spend_energy(energy_cost, reason=f"travel:{destination}")
        if heat_add:
            ps.add_heat(heat_add, reason=f"travel:{destination}")
        ps.set_location(destination)

        # Fire event cascade
        self._fire_travel_event(origin, destination, travel_time, energy_cost, heat_add)

        logger.info("Player travelled %s → %s (t=%dmin e=-%d h=+%d)",
                    origin, destination, travel_time, energy_cost, heat_add)

        return TravelResult(
            success=True,
            from_location=origin,
            to_location=destination,
            travel_time=travel_time,
            energy_cost=energy_cost,
            heat_add=heat_add,
            message=f"Arrived at {destination}. ({travel_time} min travel)",
        )

    def _fire_travel_event(
        self,
        origin: str,
        destination: str,
        travel_time: int,
        energy_cost: int,
        heat_add: int,
    ) -> None:
        payload = {
            "from": origin,
            "to": destination,
            "travel_time_min": travel_time,
            "energy_cost": energy_cost,
            "heat_add": heat_add,
            "timestamp": time.time(),
        }
        # v1.52.0 — Fire via both EventCascade and EventBus for broader reach
        try:
            from engine.world.event_cascade import get_event_cascade
            get_event_cascade().fire("player_travel", payload)
        except Exception as exc:
            logger.debug("Could not fire travel event (cascade): %s", exc)
        try:
            from engine.events.event_bus import get_event_bus
            get_event_bus().publish("player_travel", payload)
        except Exception as exc:
            logger.debug("Could not fire travel event (bus): %s", exc)

    # ── NPC Location Tracking ─────────────────────────────────────────────

    def set_npc_location(self, npc_id: str, location: str) -> None:
        """Update an NPC's current location on the map."""
        with self._lock:
            old = self._npc_locations.get(npc_id)
            self._npc_locations[npc_id] = location
            # Update node npc_names lists
            if old and old in self._nodes:
                names = self._nodes[old].npc_names
                if npc_id in names:
                    names.remove(npc_id)
            if location in self._nodes:
                names = self._nodes[location].npc_names
                if npc_id not in names:
                    names.append(npc_id)

    def get_npc_location(self, npc_id: str) -> Optional[str]:
        """Return an NPC's current location."""
        return self._npc_locations.get(npc_id)

    def get_npcs_at(self, location: str) -> List[str]:
        """Return list of NPC IDs at a location."""
        return list(self._nodes[location].npc_names) if location in self._nodes else []

    def get_all_npc_locations(self) -> Dict[str, str]:
        """Return {npc_id: location} for all tracked NPCs."""
        with self._lock:
            return dict(self._npc_locations)

    # ── Scene Active Status ───────────────────────────────────────────────

    def set_scene_active(self, location: str, active: bool) -> None:
        """Mark a scene node as running (scene server up)."""
        if location in self._nodes:
            self._nodes[location].is_active = active

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Full map state for REST/Socket.IO delivery."""
        ps = get_player_state()
        with self._lock:
            return {
                "nodes": [n.to_dict() for n in self._nodes.values()],
                "districts": DISTRICTS,
                "player_location": ps.active_location or _DEFAULT_LOCATION,
                "npc_locations": dict(self._npc_locations),
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_CITY_MAP: Optional[CityMap] = None
_MAP_LOCK = threading.Lock()


def get_city_map() -> CityMap:
    """Return the CityMap singleton."""
    global _CITY_MAP
    if _CITY_MAP is None:
        with _MAP_LOCK:
            if _CITY_MAP is None:
                _CITY_MAP = CityMap()
    return _CITY_MAP


def reset_city_map() -> None:
    """Reset the singleton — for tests only."""
    global _CITY_MAP
    with _MAP_LOCK:
        _CITY_MAP = None
