"""MCP skills for the cyberspace network intrusion system.

Phase 4 — Hacking Depth.  Provides 15 skills for LLM agents to interact
with the cyberspace engine: network navigation, ICE breaking, program
management, cyberdeck upgrades, and data extraction.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _engine():
    """Lazy import to avoid circular dependencies."""
    from engine.world.cyberspace import get_cyberspace_engine
    return get_cyberspace_engine()


# ── Network Skills ────────────────────────────────────────────────────────────


@skill(
    pack="cyberspace",
    description="List all available hackable networks with difficulty and faction info",
    category=SkillCategory.GAME,
    tags=["hacking", "network", "cyberspace"],
)
def cyberspace_list_networks() -> str:
    """List available networks for intrusion."""
    nets = _engine().list_networks()
    if not nets:
        return "No networks available. Generate one first."
    lines = []
    for n in nets:
        status = "✅ complete" if n.get("is_complete") else (
            f"🔢 {n['node_count']} nodes" if n.get("node_count", 0) > 0 else "⬜ not generated"
        )
        lines.append(
            f"• {n['network_id']} — {n['label']} "
            f"[Diff {n['difficulty']}] [{n.get('faction', '?')}] {status}"
        )
    return "Available Networks:\n" + "\n".join(lines)


@skill(
    pack="cyberspace",
    description="Generate a hackable network topology from a template",
    category=SkillCategory.GAME,
    tags=["hacking", "network", "generate"],
)
def cyberspace_generate_network(
    network_id: str,
    difficulty: int = 0,
    force: bool = False,
) -> str:
    """Generate a network topology.

    Args:
        network_id: Template ID (e.g. omnicorp_subnet, neotech_research).
        difficulty: Override difficulty 1-5 (0 = use template default).
        force: Regenerate even if already exists.
    """
    result = _engine().generate_network(
        network_id,
        difficulty=difficulty if difficulty > 0 else None,
        force=force,
    )
    if result["status"] == "exists":
        return (
            f"Network '{result['label']}' already exists "
            f"({result['node_count']} nodes, difficulty {result['difficulty']}). "
            f"Use force=True to regenerate."
        )
    return (
        f"Generated network: {result['label']} "
        f"[{result['node_count']} nodes, difficulty {result['difficulty']}, "
        f"faction: {result.get('faction', 'none')}]"
    )


@skill(
    pack="cyberspace",
    description="View the network map topology — nodes, connections, and ICE",
    category=SkillCategory.GAME,
    tags=["hacking", "network", "map"],
)
def cyberspace_view_network(network_id: str) -> str:
    """View a network's topology.

    Args:
        network_id: Network to inspect.
    """
    data = _engine().get_network_map(network_id)
    if not data:
        return f"Network '{network_id}' not found. Generate it first."
    lines = [f"Network: {data['label']} [Difficulty {data['difficulty']}]"]
    lines.append(f"Entry: {data['entry_node']}")
    lines.append(f"Objectives: {', '.join(data['objective_nodes'])}")
    lines.append("")
    for nid, nd in data["nodes"].items():
        ice_str = f" 🛡️{len([i for i in nd['ice'] if i['active']])} ICE" if nd["ice"] else ""
        data_str = f" 📦{len([d for d in nd['data'] if not d['extracted']])} data" if nd["data"] else ""
        visited = " ✓" if nd["visited"] else ""
        lines.append(f"  [{nd['node_type']}] {nid}: {nd['label']}{ice_str}{data_str}{visited}")
        for conn in nd["connections"]:
            lines.append(f"    → {conn}")
    return "\n".join(lines)


# ── Session Skills ────────────────────────────────────────────────────────────


@skill(
    pack="cyberspace",
    description="Jack into a network to start an intrusion session",
    category=SkillCategory.GAME,
    tags=["hacking", "intrusion", "session"],
    cooldown=5.0,
)
def cyberspace_jack_in(network_id: str) -> str:
    """Start a hacking session on a network.

    Args:
        network_id: Network to infiltrate.
    """
    result = _engine().jack_in(network_id)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    lines = [
        f"🔌 JACKED IN to {network_id}",
        f"Session: {result['session_id']}",
        f"Entry: {result['node_label']}",
        f"Programs loaded: {result['programs_loaded']}",
        f"RAM: {result['ram_used']}/{result['ram_used'] + result['ram_available']}",
        "",
        "Adjacent nodes:",
    ]
    for adj in result.get("adjacent", []):
        ice = " 🛡️" if adj["has_ice"] else ""
        lines.append(f"  → {adj['id']}: {adj['label']} [{adj['type']}]{ice}")
    return "\n".join(lines)


@skill(
    pack="cyberspace",
    description="Move to an adjacent node in the network during an intrusion",
    category=SkillCategory.GAME,
    tags=["hacking", "movement", "intrusion"],
)
def cyberspace_move(session_id: str, target_node: str) -> str:
    """Navigate to an adjacent network node.

    Args:
        session_id: Active intrusion session ID.
        target_node: Node ID to move to.
    """
    result = _engine().move_to(session_id, target_node)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    if result["status"] == "blocked":
        return f"🛡️ BLOCKED: {result['message']}"
    if result["status"] == "detected":
        return f"🚨 {result['message']}"

    lines = [
        f"→ Moved to: {result['node_label']} [{result['node_type']}]",
        f"Detection: {result['detection_level']}% (+{result['detection_delta']})",
    ]
    if result["is_objective"]:
        lines.append("⭐ This is an OBJECTIVE node!")
    if result["has_ice"]:
        lines.append(f"⚠️ Active ICE detected ({len(result['ice'])})")
    if result["data_available"] > 0:
        lines.append(f"📦 {result['data_available']} data payload(s) available")
    lines.append("")
    lines.append("Adjacent:")
    for adj in result.get("adjacent", []):
        ice = " 🛡️" if adj["has_ice"] else ""
        lines.append(f"  → {adj['id']}: {adj['label']} [{adj['type']}]{ice}")
    return "\n".join(lines)


@skill(
    pack="cyberspace",
    description="Scan the current node for ICE, data, and connections",
    category=SkillCategory.GAME,
    tags=["hacking", "scan", "reconnaissance"],
)
def cyberspace_scan(session_id: str) -> str:
    """Scan the current node.

    Args:
        session_id: Active intrusion session ID.
    """
    result = _engine().scan_node(session_id)
    if result["status"] == "error":
        return f"❌ {result['message']}"

    lines = [
        f"📡 SCAN: {result['label']} [{result['type']}]",
        f"Description: {result['description']}",
    ]
    if result["is_objective"]:
        lines.append("⭐ OBJECTIVE NODE")
    if result["compromised"]:
        lines.append("💀 Node compromised (ICE disabled)")

    if result["ice"]:
        lines.append(f"\nICE ({result['active_ice_count']} active):")
        for ice in result["ice"]:
            status = "🟢 active" if ice["active"] else "🔴 broken"
            lines.append(f"  {ice['id']}: {ice['ice_type']} str:{ice['strength']} [{status}] — {ice['description']}")

    if result["data"]:
        lines.append("\nData:")
        for d in result["data"]:
            enc = " 🔒" if d["encrypted"] else ""
            ext = " ✅" if d["extracted"] else ""
            lines.append(f"  {d['id']}: {d['label']} ({d['data_type']}){enc}{ext}")

    lines.append("\nConnections:")
    for adj in result["adjacent"]:
        ice = " 🛡️" if adj["has_ice"] else ""
        vis = " ✓" if adj["visited"] else ""
        lines.append(f"  → {adj['id']}: {adj['label']} [{adj['type']}]{ice}{vis}")

    return "\n".join(lines)


@skill(
    pack="cyberspace",
    description="Use a loaded program (icebreaker, cloak, siphon, virus, backdoor, decrypt, overclock)",
    category=SkillCategory.GAME,
    tags=["hacking", "program", "ICE"],
    cooldown=2.0,
)
def cyberspace_use_program(
    session_id: str,
    program_id: str,
    target_ice_id: str = "",
    target_node_id: str = "",
) -> str:
    """Use a cyberdeck program during intrusion.

    Args:
        session_id: Active session ID.
        program_id: Program to use (icebreaker, cloak, siphon, virus, backdoor, decrypt, overclock).
        target_ice_id: Optional ICE barrier to target.
        target_node_id: Optional node to target (for virus, backdoor, icebreaker on adjacent).
    """
    result = _engine().use_program(
        session_id,
        program_id,
        target_ice_id=target_ice_id or None,
        target_node_id=target_node_id or None,
    )
    if result["status"] == "error":
        return f"❌ {result['message']}"

    msg = result.get("message", f"Program {program_id} used")
    parts = [msg]
    if "uses_remaining" in result:
        parts.append(f"Uses remaining: {result['uses_remaining']}")
    if "xp_earned" in result:
        parts.append(f"+{result['xp_earned']} XP")
    if "detection_level" in result:
        parts.append(f"Detection: {result['detection_level']}%")
    if "ram_damage" in result:
        parts.append(f"⚠️ RAM damage: {result['ram_damage']}")
    return " | ".join(parts)


@skill(
    pack="cyberspace",
    description="Extract data from the current node",
    category=SkillCategory.GAME,
    tags=["hacking", "data", "extraction"],
    cooldown=3.0,
)
def cyberspace_extract(session_id: str, data_id: str = "") -> str:
    """Extract a data payload from the current node.

    Args:
        session_id: Active session ID.
        data_id: Specific data ID (or empty for first available).
    """
    result = _engine().extract_data(session_id, data_id=data_id or None)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    if result["status"] == "encrypted":
        return f"🔒 {result['message']}"
    if result["status"] == "trap":
        return f"⚠️ {result['message']}"
    return result.get("message", "Data extracted")


@skill(
    pack="cyberspace",
    description="Disconnect from the network (jack out) and end the intrusion session",
    category=SkillCategory.GAME,
    tags=["hacking", "disconnect", "session"],
)
def cyberspace_jack_out(session_id: str) -> str:
    """Jack out of the network.

    Args:
        session_id: Active session ID.
    """
    result = _engine().jack_out(session_id)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    return (
        f"🔌 JACKED OUT\n"
        f"Duration: {result['duration']}s | Nodes: {result['nodes_visited']} | "
        f"Data: {result['data_extracted']} | ICE: {result['ice_broken']} | "
        f"Credits: {result['credits_earned']} | XP: {result['xp_earned']} | "
        f"Detection: {result['detection_level']}% | RAM damage: {result['ram_damage_taken']}"
        + (" | 🏆 NETWORK COMPLETE!" if result["network_complete"] else "")
    )


# ── Cyberdeck Skills ──────────────────────────────────────────────────────────


@skill(
    pack="cyberspace",
    description="View cyberdeck status — RAM, CPU, installed programs, damage",
    category=SkillCategory.GAME,
    tags=["cyberdeck", "hardware", "status"],
)
def cyberspace_deck_status() -> str:
    """Show current cyberdeck hardware and program loadout."""
    deck = _engine().get_cyberdeck()
    lines = [
        f"💻 Cyberdeck: {deck['name']}",
        f"RAM: {deck['ram_available']}/{deck['ram_total']}"
        + (f" ({deck['ram_damage']} damaged)" if deck["ram_damage"] > 0 else ""),
        f"CPU: {deck['cpu_speed']}× | Max Programs: {deck['max_programs']}",
        "",
        "Installed Programs:",
    ]
    from engine.world.cyberspace import PROGRAM_CATALOG
    for pid in deck["installed_programs"]:
        pdef = PROGRAM_CATALOG.get(pid, {})
        lines.append(f"  • {pdef.get('name', pid)} [RAM: {pdef.get('ram_cost', '?')}] — {pdef.get('description', '')}")
    if not deck["installed_programs"]:
        lines.append("  (none)")
    return "\n".join(lines)


@skill(
    pack="cyberspace",
    description="Upgrade to a better cyberdeck (netrunner_mk1, void_runner, specter_3000, phantom_x, archon_prime)",
    category=SkillCategory.GAME,
    tags=["cyberdeck", "upgrade", "hardware"],
)
def cyberspace_upgrade_deck(deck_id: str) -> str:
    """Upgrade the cyberdeck.

    Args:
        deck_id: Tier ID to upgrade to.
    """
    result = _engine().upgrade_cyberdeck(deck_id)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    return (
        f"⬆️ Upgraded to {result['name']}! "
        f"RAM: {result['ram']} | CPU: {result['cpu']}× | "
        f"Max Programs: {result['max_programs']}"
    )


@skill(
    pack="cyberspace",
    description="Install a program onto the cyberdeck (icebreaker, cloak, siphon, virus, backdoor, decrypt, overclock)",
    category=SkillCategory.GAME,
    tags=["cyberdeck", "program", "install"],
)
def cyberspace_install_program(program_id: str) -> str:
    """Install a program onto the cyberdeck.

    Args:
        program_id: Program to install.
    """
    result = _engine().install_program(program_id)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    return (
        f"✅ Installed {result['name']} "
        f"[RAM cost: {result['ram_cost']}, Uses: {result['uses']}]"
    )


@skill(
    pack="cyberspace",
    description="Uninstall a program from the cyberdeck",
    category=SkillCategory.GAME,
    tags=["cyberdeck", "program", "uninstall"],
)
def cyberspace_uninstall_program(program_id: str) -> str:
    """Remove a program from the cyberdeck.

    Args:
        program_id: Program to remove.
    """
    result = _engine().uninstall_program(program_id)
    if result["status"] == "error":
        return f"❌ {result['message']}"
    return f"🗑️ Uninstalled {program_id}"


@skill(
    pack="cyberspace",
    description="Repair RAM damage on the cyberdeck",
    category=SkillCategory.GAME,
    tags=["cyberdeck", "repair"],
)
def cyberspace_repair_deck(ram_amount: int = 0) -> str:
    """Repair cyberdeck RAM damage.

    Args:
        ram_amount: How much RAM to restore (0 = full repair).
    """
    result = _engine().repair_cyberdeck(ram_amount)
    if result["status"] == "no_damage":
        return "💻 Cyberdeck is undamaged — no repair needed"
    return f"🔧 Repaired {result['ram_restored']} RAM"


# ── Stats Skills ──────────────────────────────────────────────────────────────


@skill(
    pack="cyberspace",
    description="View overall cyberspace hacking statistics and career progress",
    category=SkillCategory.GAME,
    tags=["hacking", "stats", "progress"],
)
def cyberspace_stats() -> str:
    """Show hacking career stats."""
    stats = _engine().get_stats()
    return (
        f"🌐 Cyberspace Stats\n"
        f"Intrusions: {stats['total_intrusions']} | "
        f"Data Extracted: {stats['total_data_extracted']} | "
        f"ICE Broken: {stats['total_ice_broken']} | "
        f"Total XP: {stats['total_xp']}\n"
        f"Networks: {stats['networks_generated']}/{stats['networks_available']} generated, "
        f"{len(stats['completed_networks'])} completed\n"
        f"Active session: {'Yes' if stats['active_session'] else 'No'}"
    )
