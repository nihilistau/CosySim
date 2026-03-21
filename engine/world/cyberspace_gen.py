"""Cyberspace network generation — templates, tables, and topology generator.

Extracted from ``cyberspace.py`` to reduce file size.
All names are re-exported from the parent module for backward compatibility.
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional

from engine.world.cyberspace_models import (
    CYBERDECK_TIERS,
    PROGRAM_CATALOG,
    DataPayload,
    ICEBarrier,
    ICEType,
    NetworkMap,
    NetworkNode,
    NodeType,
)


# ──── Network Templates ──────────────────────────────────────────────────────


_NETWORK_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "omnicorp_subnet": {
        "label": "OmniCorp Subnet Alpha",
        "faction": "OmniCorp",
        "description": "Standard corporate subnet. Light security, decent payoffs.",
        "difficulty": 1,
    },
    "neotech_research": {
        "label": "NeoTech R&D Cluster",
        "faction": "NeoTech",
        "description": "Research network. Moderate ICE, valuable data.",
        "difficulty": 2,
    },
    "synthsec_mainframe": {
        "label": "SynthSec Mainframe",
        "faction": "SynthSec",
        "description": "Security corp mainframe. Heavy ICE, high-value intel.",
        "difficulty": 3,
    },
    "deepstate_archive": {
        "label": "DeepState Archive",
        "faction": "DeepState",
        "description": "Encrypted government archive. Black ICE everywhere.",
        "difficulty": 4,
    },
    "ghost_net_nexus": {
        "label": "Ghost_Net Hidden Nexus",
        "faction": "Ghost_Net",
        "description": "The legendary hidden network. Maximum difficulty.",
        "difficulty": 5,
    },
    "blackmarket_exchange": {
        "label": "Black Market Exchange",
        "faction": "BlackMarket",
        "description": "Underground trading hub. Scramble ICE and honeypots.",
        "difficulty": 2,
    },
}


# ──── ICE Generation Tables ──────────────────────────────────────────────────

_ICE_NAMES: Dict[ICEType, List[str]] = {
    ICEType.BARRIER: ["Firewall", "Gatekeeper", "Iron Curtain", "Aegis Shield"],
    ICEType.TRACE: ["Tracker v2", "Bloodhound", "Net Spider", "Eye of Sauron"],
    ICEType.BLACK_ICE: ["Razor Wire", "Neural Spike", "Cortex Bomb", "Flatline"],
    ICEType.SCRAMBLE: ["Data Storm", "Signal Jammer", "Maze Protocol", "Entropy Wave"],
}

_NODE_LABELS: Dict[NodeType, List[str]] = {
    NodeType.ENTRY: ["Access Point", "Gateway", "Public Terminal"],
    NodeType.ROUTER: ["Relay Node", "Switch Hub", "Signal Router", "Data Pipe"],
    NodeType.SERVER: ["Core Server", "Auth Server", "Process Node", "Compute Cluster"],
    NodeType.FIREWALL: ["ICE Wall", "Security Gate", "Checkpoint", "Barrier Node"],
    NodeType.DATASTORE: ["Data Vault", "Archive Node", "Storage Array", "Memory Bank"],
    NodeType.TERMINAL: ["Admin Console", "Control Panel", "Root Terminal", "System Core"],
    NodeType.HONEYPOT: ["Decoy Server", "Trap Node", "Bait Terminal", "False Archive"],
    NodeType.EXIT: ["Exit Node", "Disconnect Point", "Escape Vector"],
}


# ──── Detection Rates ────────────────────────────────────────────────────────

_DETECTION_PER_MOVE: Dict[int, float] = {
    1: 3.0, 2: 5.0, 3: 8.0, 4: 12.0, 5: 15.0,
}

_DETECTION_PER_ICE_BREAK: Dict[int, float] = {
    1: 5.0, 2: 8.0, 3: 12.0, 4: 16.0, 5: 20.0,
}

_DETECTION_PER_EXTRACT: Dict[int, float] = {
    1: 8.0, 2: 12.0, 3: 15.0, 4: 20.0, 5: 25.0,
}

_BLACK_ICE_RAM_DAMAGE: Dict[int, int] = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 3,
}

_XP_PER_ICE: Dict[int, int] = {
    1: 10, 2: 15, 3: 25, 4: 40, 5: 60,
}

_XP_PER_EXTRACT: Dict[int, int] = {
    1: 15, 2: 25, 3: 40, 4: 60, 5: 100,
}

_XP_COMPLETION_BONUS: Dict[int, int] = {
    1: 50, 2: 100, 3: 200, 4: 400, 5: 750,
}


# ──── Network Generator ──────────────────────────────────────────────────────


def _generate_network_topology(
    network_id: str,
    difficulty: int,
    seed: Optional[str] = None,
) -> NetworkMap:
    """Procedurally generate a network topology for the given difficulty.

    Args:
        network_id: Template ID from _NETWORK_TEMPLATES.
        difficulty: 1-5 difficulty scale.
        seed: Optional deterministic seed.

    Returns:
        Fully populated NetworkMap.
    """
    template = _NETWORK_TEMPLATES.get(network_id, {})
    difficulty = max(1, min(5, difficulty or template.get("difficulty", 1)))

    rng = random.Random(seed or f"{network_id}_{time.time()}")

    node_count = 5 + difficulty * 2
    ice_count = difficulty * 2
    data_count = 1 + difficulty

    nodes: Dict[str, NetworkNode] = {}
    node_ids: List[str] = []

    entry_id = f"{network_id}_entry"
    nodes[entry_id] = NetworkNode(
        id=entry_id,
        label=rng.choice(_NODE_LABELS[NodeType.ENTRY]),
        node_type=NodeType.ENTRY,
        description="Network entry point. You jack in here.",
        x=0.0,
        y=0.5,
    )
    node_ids.append(entry_id)

    interior_types = [
        NodeType.ROUTER, NodeType.SERVER, NodeType.FIREWALL,
        NodeType.ROUTER, NodeType.SERVER,
    ]
    if difficulty >= 3:
        interior_types.append(NodeType.HONEYPOT)

    for i in range(node_count - 2):
        ntype = rng.choice(interior_types)
        nid = f"{network_id}_n{i:02d}"
        label = rng.choice(_NODE_LABELS[ntype])
        nodes[nid] = NetworkNode(
            id=nid,
            label=f"{label} #{i+1}",
            node_type=ntype,
            description=f"Level {difficulty} {ntype.value} node",
            x=round((i + 1) / (node_count - 1), 3),
            y=round(rng.uniform(0.1, 0.9), 3),
        )
        node_ids.append(nid)

    objective_count = max(1, difficulty // 2 + 1)
    objective_ids: List[str] = []
    for i in range(objective_count):
        nid = f"{network_id}_obj{i:02d}"
        nodes[nid] = NetworkNode(
            id=nid,
            label=rng.choice(_NODE_LABELS[NodeType.DATASTORE]),
            node_type=NodeType.DATASTORE,
            description="Objective node — extract data here.",
            x=round(0.8 + i * 0.05, 3),
            y=round(rng.uniform(0.2, 0.8), 3),
        )
        node_ids.append(nid)
        objective_ids.append(nid)

    for idx in range(1, len(node_ids)):
        parent_idx = rng.randint(max(0, idx - 3), idx - 1)
        parent_id = node_ids[parent_idx]
        child_id = node_ids[idx]
        if child_id not in nodes[parent_id].connections:
            nodes[parent_id].connections.append(child_id)
        if parent_id not in nodes[child_id].connections:
            nodes[child_id].connections.append(parent_id)

    extra_edges = difficulty
    for _ in range(extra_edges):
        a = rng.choice(node_ids)
        b = rng.choice(node_ids)
        if a != b and b not in nodes[a].connections:
            nodes[a].connections.append(b)
            nodes[b].connections.append(a)

    ice_types_pool = [ICEType.BARRIER, ICEType.TRACE]
    if difficulty >= 2:
        ice_types_pool.append(ICEType.SCRAMBLE)
    if difficulty >= 3:
        ice_types_pool.append(ICEType.BLACK_ICE)

    eligible_for_ice = [
        nid for nid in node_ids
        if nodes[nid].node_type not in (NodeType.ENTRY, NodeType.HONEYPOT)
    ]
    ice_placed = 0
    rng.shuffle(eligible_for_ice)
    for nid in eligible_for_ice:
        if ice_placed >= ice_count:
            break
        ice_type = rng.choice(ice_types_pool)
        strength = rng.randint(max(1, difficulty - 1), difficulty + 1)
        ice_id = f"ice_{nid}_{ice_placed}"
        nodes[nid].ice.append(ICEBarrier(
            id=ice_id,
            ice_type=ice_type,
            strength=min(10, strength),
            description=rng.choice(_ICE_NAMES[ice_type]),
        ))
        ice_placed += 1

    for i, obj_id in enumerate(objective_ids):
        for j in range(data_count):
            data_type = rng.choice(["credits", "intel", "faction_secret", "crypto"])
            value = (difficulty * 200 + rng.randint(50, 300)) * (j + 1)
            encrypted = difficulty >= 3 and rng.random() > 0.5
            nodes[obj_id].data.append(DataPayload(
                id=f"data_{obj_id}_{j}",
                label=f"{data_type.replace('_', ' ').title()} #{j+1}",
                value=value,
                data_type=data_type,
                encrypted=encrypted,
                description=f"{'Encrypted ' if encrypted else ''}{data_type} payload",
            ))

    if difficulty >= 3:
        honeypots = [nid for nid, n in nodes.items() if n.node_type == NodeType.HONEYPOT]
        for hp_id in honeypots:
            nodes[hp_id].data.append(DataPayload(
                id=f"trap_{hp_id}",
                label="Suspicious Data Cache",
                value=0,
                data_type="trap",
                description="This data is a trap — extracting raises detection by 30.",
            ))

    return NetworkMap(
        network_id=network_id,
        label=template.get("label", network_id),
        difficulty=difficulty,
        nodes=nodes,
        entry_node=entry_id,
        objective_nodes=objective_ids,
        faction=template.get("faction", ""),
        description=template.get("description", ""),
    )
