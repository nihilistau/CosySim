"""Cyberspace data models — enums, dataclasses, and catalogs.

Extracted from ``cyberspace.py`` to reduce file size.
All names are re-exported from the parent module for backward compatibility.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ──── Enums ───────────────────────────────────────────────────────────────────


class NodeType(Enum):
    """Types of network nodes."""
    ENTRY = "entry"
    ROUTER = "router"
    SERVER = "server"
    FIREWALL = "firewall"
    DATASTORE = "datastore"
    TERMINAL = "terminal"
    HONEYPOT = "honeypot"
    EXIT = "exit"


class ICEType(Enum):
    """Intrusion Countermeasure Electronics types."""
    BARRIER = "barrier"
    TRACE = "trace"
    BLACK_ICE = "black_ice"
    SCRAMBLE = "scramble"


class ProgramType(Enum):
    """Cyberdeck software programs."""
    ICEBREAKER = "icebreaker"
    CLOAK = "cloak"
    SIPHON = "siphon"
    VIRUS = "virus"
    BACKDOOR = "backdoor"
    DECRYPT = "decrypt"
    OVERCLOCK = "overclock"


class SessionStatus(Enum):
    """Intrusion session states."""
    ACTIVE = "active"
    COMPLETED = "completed"
    DETECTED = "detected"
    JACKED_OUT = "jacked_out"
    CRASHED = "crashed"


# ──── Program Definitions ─────────────────────────────────────────────────────


PROGRAM_CATALOG: Dict[str, Dict[str, Any]] = {
    "icebreaker": {
        "name": "Icebreaker v3",
        "type": ProgramType.ICEBREAKER,
        "ram_cost": 2,
        "uses": 3,
        "description": "Shatters Barrier ICE. 3 uses per load.",
        "counters": ICEType.BARRIER,
        "base_power": 5,
    },
    "cloak": {
        "name": "Ghost Cloak",
        "type": ProgramType.CLOAK,
        "ram_cost": 2,
        "uses": 4,
        "description": "Masks your signal from Trace ICE. 4 uses.",
        "counters": ICEType.TRACE,
        "base_power": 4,
    },
    "siphon": {
        "name": "Siphon Drain",
        "type": ProgramType.SIPHON,
        "ram_cost": 3,
        "uses": 2,
        "description": "Absorbs Black ICE damage into power. 2 uses.",
        "counters": ICEType.BLACK_ICE,
        "base_power": 6,
    },
    "virus": {
        "name": "Neurovirus",
        "type": ProgramType.VIRUS,
        "ram_cost": 3,
        "uses": 1,
        "description": "Permanently disables all ICE on a node. Single use.",
        "counters": None,
        "base_power": 10,
    },
    "backdoor": {
        "name": "Backdoor Implant",
        "type": ProgramType.BACKDOOR,
        "ram_cost": 2,
        "uses": 2,
        "description": "Creates a shortcut link between two nodes. 2 uses.",
        "counters": None,
        "base_power": 3,
    },
    "decrypt": {
        "name": "Decrypt Module",
        "type": ProgramType.DECRYPT,
        "ram_cost": 1,
        "uses": 5,
        "description": "Counters Scramble ICE and reveals hidden paths. 5 uses.",
        "counters": ICEType.SCRAMBLE,
        "base_power": 3,
    },
    "overclock": {
        "name": "Overclock Pulse",
        "type": ProgramType.OVERCLOCK,
        "ram_cost": 2,
        "uses": 2,
        "description": "Doubles the power of your next program use. 2 uses.",
        "counters": None,
        "base_power": 0,
    },
}


# ──── Cyberdeck Tiers ─────────────────────────────────────────────────────────


CYBERDECK_TIERS: Dict[str, Dict[str, Any]] = {
    "netrunner_mk1": {
        "name": "Netrunner MK1",
        "ram": 4,
        "cpu": 1.0,
        "max_programs": 3,
        "description": "Basic deck. Gets the job done — barely.",
    },
    "void_runner": {
        "name": "Void Runner",
        "ram": 8,
        "cpu": 1.5,
        "max_programs": 5,
        "description": "Mid-tier runner deck. Smooth and reliable.",
    },
    "specter_3000": {
        "name": "Specter 3000",
        "ram": 12,
        "cpu": 2.0,
        "max_programs": 8,
        "description": "Military-grade. Silent entry, devastating power.",
    },
    "phantom_x": {
        "name": "Phantom X",
        "ram": 16,
        "cpu": 2.5,
        "max_programs": 10,
        "description": "Prototype. Rumoured to have AI co-processing.",
    },
    "archon_prime": {
        "name": "Archon Prime",
        "ram": 20,
        "cpu": 3.0,
        "max_programs": 12,
        "description": "The apex. Only three exist in NeonCity.",
    },
}


# ──── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class ICEBarrier:
    """A single ICE defense on a network node."""
    id: str
    ice_type: ICEType
    strength: int = 3
    active: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ice_type": self.ice_type.value,
            "strength": self.strength,
            "active": self.active,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ICEBarrier:
        return cls(
            id=data["id"],
            ice_type=ICEType(data["ice_type"]),
            strength=data.get("strength", 3),
            active=data.get("active", True),
            description=data.get("description", ""),
        )


@dataclass
class DataPayload:
    """Extractable data on a network node."""
    id: str
    label: str
    value: int = 100
    data_type: str = "credits"
    extracted: bool = False
    encrypted: bool = False
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "data_type": self.data_type,
            "extracted": self.extracted,
            "encrypted": self.encrypted,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DataPayload:
        return cls(
            id=data["id"],
            label=data["label"],
            value=data.get("value", 100),
            data_type=data.get("data_type", "credits"),
            extracted=data.get("extracted", False),
            encrypted=data.get("encrypted", False),
            description=data.get("description", ""),
        )


@dataclass
class NetworkNode:
    """A single node in a hackable network."""
    id: str
    label: str
    node_type: NodeType = NodeType.ROUTER
    ice: List[ICEBarrier] = field(default_factory=list)
    data: List[DataPayload] = field(default_factory=list)
    connections: List[str] = field(default_factory=list)
    visited: bool = False
    compromised: bool = False
    description: str = ""
    x: float = 0.0
    y: float = 0.0

    @property
    def has_active_ice(self) -> bool:
        return any(i.active for i in self.ice)

    @property
    def active_ice(self) -> List[ICEBarrier]:
        return [i for i in self.ice if i.active]

    @property
    def extractable_data(self) -> List[DataPayload]:
        return [d for d in self.data if not d.extracted]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type.value,
            "ice": [i.to_dict() for i in self.ice],
            "data": [d.to_dict() for d in self.data],
            "connections": self.connections,
            "visited": self.visited,
            "compromised": self.compromised,
            "description": self.description,
            "x": self.x,
            "y": self.y,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NetworkNode:
        return cls(
            id=data["id"],
            label=data["label"],
            node_type=NodeType(data.get("node_type", "router")),
            ice=[ICEBarrier.from_dict(i) for i in data.get("ice", [])],
            data=[DataPayload.from_dict(d) for d in data.get("data", [])],
            connections=data.get("connections", []),
            visited=data.get("visited", False),
            compromised=data.get("compromised", False),
            description=data.get("description", ""),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
        )


@dataclass
class LoadedProgram:
    """A program loaded into cyberdeck RAM during an intrusion."""
    program_id: str
    program_type: ProgramType
    uses_remaining: int
    base_power: int
    ram_cost: int
    overclocked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "program_id": self.program_id,
            "program_type": self.program_type.value,
            "uses_remaining": self.uses_remaining,
            "base_power": self.base_power,
            "ram_cost": self.ram_cost,
            "overclocked": self.overclocked,
        }


@dataclass
class CyberdeckState:
    """Player's cyberdeck hardware state."""
    deck_id: str = "netrunner_mk1"
    ram_total: int = 4
    ram_used: int = 0
    cpu_speed: float = 1.0
    max_programs: int = 3
    installed_programs: List[str] = field(default_factory=list)
    ram_damage: int = 0

    @property
    def ram_available(self) -> int:
        return max(0, self.ram_total - self.ram_used - self.ram_damage)

    @property
    def effective_ram(self) -> int:
        return max(0, self.ram_total - self.ram_damage)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deck_id": self.deck_id,
            "ram_total": self.ram_total,
            "ram_used": self.ram_used,
            "cpu_speed": self.cpu_speed,
            "max_programs": self.max_programs,
            "installed_programs": list(self.installed_programs),
            "ram_damage": self.ram_damage,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CyberdeckState:
        return cls(
            deck_id=data.get("deck_id", "netrunner_mk1"),
            ram_total=data.get("ram_total", 4),
            ram_used=data.get("ram_used", 0),
            cpu_speed=data.get("cpu_speed", 1.0),
            max_programs=data.get("max_programs", 3),
            installed_programs=data.get("installed_programs", []),
            ram_damage=data.get("ram_damage", 0),
        )

    @classmethod
    def from_tier(cls, deck_id: str) -> CyberdeckState:
        """Create a CyberdeckState from a tier definition."""
        tier = CYBERDECK_TIERS.get(deck_id, CYBERDECK_TIERS["netrunner_mk1"])
        return cls(
            deck_id=deck_id,
            ram_total=tier["ram"],
            cpu_speed=tier["cpu"],
            max_programs=tier["max_programs"],
        )


@dataclass
class NetworkMap:
    """A complete hackable network topology."""
    network_id: str
    label: str
    difficulty: int = 1
    nodes: Dict[str, NetworkNode] = field(default_factory=dict)
    entry_node: str = ""
    objective_nodes: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    faction: str = ""
    description: str = ""

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def is_complete(self) -> bool:
        return all(
            all(d.extracted for d in self.nodes[nid].data)
            for nid in self.objective_nodes
            if nid in self.nodes
        )

    def get_node(self, node_id: str) -> Optional[NetworkNode]:
        return self.nodes.get(node_id)

    def get_adjacent(self, node_id: str) -> List[NetworkNode]:
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[cid] for cid in node.connections if cid in self.nodes]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "network_id": self.network_id,
            "label": self.label,
            "difficulty": self.difficulty,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "entry_node": self.entry_node,
            "objective_nodes": self.objective_nodes,
            "created_at": self.created_at,
            "faction": self.faction,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NetworkMap:
        nodes = {
            nid: NetworkNode.from_dict(nd)
            for nid, nd in data.get("nodes", {}).items()
        }
        return cls(
            network_id=data["network_id"],
            label=data["label"],
            difficulty=data.get("difficulty", 1),
            nodes=nodes,
            entry_node=data.get("entry_node", ""),
            objective_nodes=data.get("objective_nodes", []),
            created_at=data.get("created_at", 0),
            faction=data.get("faction", ""),
            description=data.get("description", ""),
        )


@dataclass
class IntrusionSession:
    """Active hacking session state."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    network_id: str = ""
    current_node: str = ""
    detection_level: float = 0.0
    status: SessionStatus = SessionStatus.ACTIVE
    loaded_programs: List[LoadedProgram] = field(default_factory=list)
    nodes_visited: List[str] = field(default_factory=list)
    data_extracted: List[Dict[str, Any]] = field(default_factory=list)
    ice_broken: int = 0
    moves: int = 0
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    overclock_active: bool = False
    backdoor_links: List[Tuple[str, str]] = field(default_factory=list)
    xp_earned: int = 0
    credits_earned: int = 0
    ram_damage_taken: int = 0

    @property
    def is_active(self) -> bool:
        return self.status == SessionStatus.ACTIVE

    @property
    def duration(self) -> float:
        end = self.ended_at or time.time()
        return end - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "network_id": self.network_id,
            "current_node": self.current_node,
            "detection_level": round(self.detection_level, 1),
            "status": self.status.value,
            "loaded_programs": [p.to_dict() for p in self.loaded_programs],
            "nodes_visited": self.nodes_visited,
            "data_extracted": self.data_extracted,
            "ice_broken": self.ice_broken,
            "moves": self.moves,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "overclock_active": self.overclock_active,
            "backdoor_links": self.backdoor_links,
            "xp_earned": self.xp_earned,
            "credits_earned": self.credits_earned,
            "ram_damage_taken": self.ram_damage_taken,
        }
