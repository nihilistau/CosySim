"""Cyberspace network engine for CosySim v1.0 "NeonCity 2".

Phase 4 — Hacking Depth.  Builds on top of the existing ``hack_engine``
(puzzle / target / heat mechanics) by adding a **network topology layer**:

Network Model
~~~~~~~~~~~~~
A hackable network is a directed graph of ``NetworkNode`` objects connected
by edges.  Each node can host ICE barriers, data payloads, and sub-systems.
The player navigates from an entry node toward objective nodes while
breaking ICE and avoiding traces.

ICE (Intrusion Countermeasure Electronics)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Four ICE types, each requiring different tactics:

- **Barrier** — blocks traversal; must be broken with an Icebreaker program.
- **Trace** — begins a trace countdown; neutralised with Cloak.
- **Black ICE** — damages the player's cyberdeck (reduce RAM); needs Siphon.
- **Scramble** — randomises node connections; countered with Decrypt.

Programs
~~~~~~~~
Software loaded into cyberdeck RAM slots:

- Icebreaker  (cost 2 RAM)  — breaks Barrier ICE
- Cloak       (cost 2 RAM)  — hides from Trace ICE
- Siphon      (cost 3 RAM)  — absorbs Black ICE damage
- Virus       (cost 3 RAM)  — disables a node's defenses permanently
- Backdoor    (cost 2 RAM)  — creates a shortcut between two nodes
- Decrypt     (cost 1 RAM)  — counters Scramble ICE
- Overclock   (cost 2 RAM)  — doubles next program's effectiveness

Cyberdeck Hardware
~~~~~~~~~~~~~~~~~~
Extends the inventory cyberdeck model with:

- **RAM** — total slots available for programs (3–12)
- **CPU** — speed modifier for ICE-breaking (1.0–3.0×)
- **Max Programs** — how many programs can be installed (3–8)

Intrusion Sessions
~~~~~~~~~~~~~~~~~~
When a player "jacks in" to a network, an ``IntrusionSession`` tracks:

- Current node position
- Detection level (0–100; 100 = full trace, session terminated)
- Programs loaded and their remaining uses
- Nodes visited, data extracted
- Session timer

Usage::

    from engine.world.cyberspace import get_cyberspace_engine

    cs = get_cyberspace_engine()
    net = cs.generate_network("omnicorp_subnet", difficulty=3)
    session = cs.jack_in("omnicorp_subnet")
    result = cs.move_to(session.id, "node_02")
    result = cs.use_program(session.id, "icebreaker", target_ice="barrier_01")
    result = cs.extract_data(session.id, "node_05")
    summary = cs.jack_out(session.id)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── Re-exports from sub-modules (backward compatibility) ─────────────────────
from engine.world.cyberspace_models import (  # noqa: F401
    CYBERDECK_TIERS,
    PROGRAM_CATALOG,
    CyberdeckState,
    DataPayload,
    ICEBarrier,
    ICEType,
    IntrusionSession,
    LoadedProgram,
    NetworkMap,
    NetworkNode,
    NodeType,
    ProgramType,
    SessionStatus,
)
from engine.world.cyberspace_gen import (  # noqa: F401
    _NETWORK_TEMPLATES,
    _DETECTION_PER_EXTRACT,
    _DETECTION_PER_ICE_BREAK,
    _DETECTION_PER_MOVE,
    _BLACK_ICE_RAM_DAMAGE,
    _XP_COMPLETION_BONUS,
    _XP_PER_EXTRACT,
    _XP_PER_ICE,
    _generate_network_topology,
)

logger = logging.getLogger(__name__)


# ──── Cyberspace Engine ──────────────────────────────────────────────────────


class CyberspaceEngine:
    """Main engine for cyberspace network intrusion gameplay.

    Manages network generation, intrusion sessions, program usage,
    ICE breaking, and data extraction.  Thread-safe.
    """

    _SAVE_PATH: Path = Path("data") / "cyberspace.json"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._networks: Dict[str, NetworkMap] = {}
        self._sessions: Dict[str, IntrusionSession] = {}
        self._cyberdeck: CyberdeckState = CyberdeckState.from_tier("netrunner_mk1")
        self._completed_networks: List[str] = []
        self._total_intrusions: int = 0
        self._total_data_extracted: int = 0
        self._total_ice_broken: int = 0
        self._total_xp: int = 0
        self._callbacks: Dict[str, List[Callable]] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load persisted cyberspace state."""
        if not self._SAVE_PATH.exists():
            logger.info("CyberspaceEngine: no save file, starting fresh")
            return
        try:
            raw = json.loads(self._SAVE_PATH.read_text(encoding="utf-8"))
            self._cyberdeck = CyberdeckState.from_dict(raw.get("cyberdeck", {}))
            self._completed_networks = raw.get("completed_networks", [])
            self._total_intrusions = raw.get("total_intrusions", 0)
            self._total_data_extracted = raw.get("total_data_extracted", 0)
            self._total_ice_broken = raw.get("total_ice_broken", 0)
            self._total_xp = raw.get("total_xp", 0)
            for nid, nd in raw.get("networks", {}).items():
                self._networks[nid] = NetworkMap.from_dict(nd)
            logger.info(
                "CyberspaceEngine: loaded state — %d networks, %d intrusions",
                len(self._networks), self._total_intrusions,
            )
        except Exception as exc:
            logger.warning("CyberspaceEngine: load failed: %s", exc)

    def _save(self) -> None:
        """Persist cyberspace state to disk."""
        try:
            self._SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "cyberdeck": self._cyberdeck.to_dict(),
                "completed_networks": self._completed_networks,
                "total_intrusions": self._total_intrusions,
                "total_data_extracted": self._total_data_extracted,
                "total_ice_broken": self._total_ice_broken,
                "total_xp": self._total_xp,
                "networks": {
                    nid: n.to_dict() for nid, n in self._networks.items()
                },
            }
            self._SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("CyberspaceEngine: save failed: %s", exc)

    # ── Events ────────────────────────────────────────────────────────────

    def on(self, event: str, callback: Callable) -> None:
        """Register an event callback."""
        with self._lock:
            self._callbacks.setdefault(event, []).append(callback)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Fire event callbacks and EventCascade."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as exc:
                logger.warning("CyberspaceEngine callback error: %s", exc)
        try:
            from engine.world.event_cascade import get_event_cascade
            get_event_cascade().emit(f"cyberspace_{event}", data)
        except Exception as e:
            logger.debug("[CyberspaceEngine] Event cascade emit failed (operation=fire_event): %s", e)

    # ── Network Management ────────────────────────────────────────────────

    def generate_network(
        self,
        network_id: str,
        difficulty: Optional[int] = None,
        seed: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Generate or retrieve a network topology.

        Args:
            network_id: Template ID or custom name.
            difficulty: 1-5 difficulty override.
            seed: Deterministic generation seed.
            force: Regenerate even if network exists.

        Returns:
            Dict with network info and node count.
        """
        with self._lock:
            if network_id in self._networks and not force:
                net = self._networks[network_id]
                return {
                    "status": "exists",
                    "network_id": net.network_id,
                    "label": net.label,
                    "node_count": net.node_count,
                    "difficulty": net.difficulty,
                }

            template = _NETWORK_TEMPLATES.get(network_id, {})
            diff = difficulty or template.get("difficulty", 1)
            net = _generate_network_topology(network_id, diff, seed)
            self._networks[network_id] = net
            self._save()

        self._emit("network_generated", {
            "network_id": network_id,
            "difficulty": net.difficulty,
            "node_count": net.node_count,
        })

        return {
            "status": "generated",
            "network_id": net.network_id,
            "label": net.label,
            "node_count": net.node_count,
            "difficulty": net.difficulty,
            "faction": net.faction,
        }

    def get_network(self, network_id: str) -> Optional[NetworkMap]:
        """Return a network by ID, or None."""
        with self._lock:
            return self._networks.get(network_id)

    def list_networks(self) -> List[Dict[str, Any]]:
        """Return summary of all available networks."""
        with self._lock:
            result = []
            for nid, net in self._networks.items():
                result.append({
                    "network_id": nid,
                    "label": net.label,
                    "difficulty": net.difficulty,
                    "node_count": net.node_count,
                    "faction": net.faction,
                    "is_complete": net.is_complete,
                })
            for tid, tmpl in _NETWORK_TEMPLATES.items():
                if tid not in self._networks:
                    result.append({
                        "network_id": tid,
                        "label": tmpl["label"],
                        "difficulty": tmpl["difficulty"],
                        "faction": tmpl.get("faction", ""),
                        "node_count": 0,
                        "generated": False,
                    })
            return result

    def get_network_map(self, network_id: str) -> Optional[Dict[str, Any]]:
        """Return full network topology as dict for visualization."""
        with self._lock:
            net = self._networks.get(network_id)
            if not net:
                return None
            return net.to_dict()

    # ── Cyberdeck Management ──────────────────────────────────────────────

    def get_cyberdeck(self) -> Dict[str, Any]:
        """Return current cyberdeck state."""
        with self._lock:
            deck = self._cyberdeck
            tier = CYBERDECK_TIERS.get(deck.deck_id, {})
            return {
                **deck.to_dict(),
                "name": tier.get("name", deck.deck_id),
                "description": tier.get("description", ""),
                "ram_available": deck.ram_available,
                "effective_ram": deck.effective_ram,
            }

    def upgrade_cyberdeck(self, deck_id: str) -> Dict[str, Any]:
        """Upgrade to a new cyberdeck tier.

        Args:
            deck_id: Tier ID from CYBERDECK_TIERS.

        Returns:
            Dict with upgrade result.
        """
        if deck_id not in CYBERDECK_TIERS:
            return {"status": "error", "message": f"Unknown deck: {deck_id}"}

        with self._lock:
            old_deck = self._cyberdeck.deck_id
            tier = CYBERDECK_TIERS[deck_id]
            self._cyberdeck = CyberdeckState(
                deck_id=deck_id,
                ram_total=tier["ram"],
                cpu_speed=tier["cpu"],
                max_programs=tier["max_programs"],
                installed_programs=self._cyberdeck.installed_programs[:tier["max_programs"]],
            )
            self._save()

        self._emit("cyberdeck_upgraded", {
            "old_deck": old_deck,
            "new_deck": deck_id,
            "ram": tier["ram"],
            "cpu": tier["cpu"],
        })

        return {
            "status": "upgraded",
            "deck_id": deck_id,
            "name": tier["name"],
            "ram": tier["ram"],
            "cpu": tier["cpu"],
            "max_programs": tier["max_programs"],
        }

    def install_program(self, program_id: str) -> Dict[str, Any]:
        """Install a program onto the cyberdeck.

        Args:
            program_id: Program ID from PROGRAM_CATALOG.

        Returns:
            Dict with install result.
        """
        if program_id not in PROGRAM_CATALOG:
            return {"status": "error", "message": f"Unknown program: {program_id}"}

        with self._lock:
            deck = self._cyberdeck
            if len(deck.installed_programs) >= deck.max_programs:
                return {
                    "status": "error",
                    "message": f"Cyberdeck full ({deck.max_programs} programs max)",
                }
            if program_id in deck.installed_programs:
                return {"status": "error", "message": "Program already installed"}

            deck.installed_programs.append(program_id)
            self._save()

        prog = PROGRAM_CATALOG[program_id]
        return {
            "status": "installed",
            "program_id": program_id,
            "name": prog["name"],
            "ram_cost": prog["ram_cost"],
            "uses": prog["uses"],
        }

    def uninstall_program(self, program_id: str) -> Dict[str, Any]:
        """Remove a program from the cyberdeck."""
        with self._lock:
            if program_id not in self._cyberdeck.installed_programs:
                return {"status": "error", "message": "Program not installed"}
            self._cyberdeck.installed_programs.remove(program_id)
            self._save()
        return {"status": "uninstalled", "program_id": program_id}

    def repair_cyberdeck(self, ram_restore: int = 0) -> Dict[str, Any]:
        """Repair RAM damage on cyberdeck.

        Args:
            ram_restore: Amount of RAM to restore (0 = full repair).

        Returns:
            Dict with repair result.
        """
        with self._lock:
            if self._cyberdeck.ram_damage == 0:
                return {"status": "no_damage", "message": "Cyberdeck is undamaged"}
            if ram_restore <= 0:
                restored = self._cyberdeck.ram_damage
                self._cyberdeck.ram_damage = 0
            else:
                restored = min(ram_restore, self._cyberdeck.ram_damage)
                self._cyberdeck.ram_damage -= restored
            self._save()
        return {"status": "repaired", "ram_restored": restored}

    # ── Intrusion Sessions ────────────────────────────────────────────────

    def jack_in(
        self,
        network_id: str,
        programs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Start an intrusion session on a network.

        Args:
            network_id: Network to jack into.
            programs: Optional list of program IDs to load (defaults to all installed).

        Returns:
            Dict with session info and entry node.
        """
        with self._lock:
            net = self._networks.get(network_id)
            if not net:
                return {"status": "error", "message": f"Network '{network_id}' not found. Generate it first."}

            active = [s for s in self._sessions.values() if s.is_active]
            if active:
                return {
                    "status": "error",
                    "message": f"Already in an active session: {active[0].id}",
                }

            prog_ids = programs or list(self._cyberdeck.installed_programs)
            loaded: List[LoadedProgram] = []
            ram_used = 0
            for pid in prog_ids:
                pdef = PROGRAM_CATALOG.get(pid)
                if not pdef:
                    continue
                if ram_used + pdef["ram_cost"] > self._cyberdeck.effective_ram:
                    break
                loaded.append(LoadedProgram(
                    program_id=pid,
                    program_type=pdef["type"],
                    uses_remaining=pdef["uses"],
                    base_power=pdef["base_power"],
                    ram_cost=pdef["ram_cost"],
                ))
                ram_used += pdef["ram_cost"]

            self._cyberdeck.ram_used = ram_used

            session = IntrusionSession(
                network_id=network_id,
                current_node=net.entry_node,
                loaded_programs=loaded,
                nodes_visited=[net.entry_node],
            )
            self._sessions[session.id] = session
            self._total_intrusions += 1

            entry = net.nodes.get(net.entry_node)
            if entry:
                entry.visited = True

            self._save()

        self._emit("jack_in", {
            "session_id": session.id,
            "network_id": network_id,
            "programs_loaded": len(loaded),
            "ram_used": ram_used,
        })

        entry_node = net.nodes.get(net.entry_node)
        return {
            "status": "jacked_in",
            "session_id": session.id,
            "network_id": network_id,
            "current_node": net.entry_node,
            "node_label": entry_node.label if entry_node else "",
            "adjacent": [
                {"id": n.id, "label": n.label, "type": n.node_type.value, "has_ice": n.has_active_ice}
                for n in net.get_adjacent(net.entry_node)
            ],
            "programs_loaded": [p.to_dict() for p in loaded],
            "detection_level": 0.0,
            "ram_used": ram_used,
            "ram_available": self._cyberdeck.ram_available,
        }

    def move_to(self, session_id: str, target_node_id: str) -> Dict[str, Any]:
        """Move to an adjacent node in the network.

        Args:
            session_id: Active session ID.
            target_node_id: Node to move to.

        Returns:
            Dict with move result, node info, and detection change.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.is_active:
                return {"status": "error", "message": "No active session"}

            net = self._networks.get(session.network_id)
            if not net:
                return {"status": "error", "message": "Network not found"}

            current = net.nodes.get(session.current_node)
            if not current:
                return {"status": "error", "message": "Current node invalid"}

            all_connections = list(current.connections)
            for link in session.backdoor_links:
                if link[0] == session.current_node and link[1] not in all_connections:
                    all_connections.append(link[1])
                elif link[1] == session.current_node and link[0] not in all_connections:
                    all_connections.append(link[0])

            if target_node_id not in all_connections:
                return {
                    "status": "error",
                    "message": f"Node '{target_node_id}' not adjacent to current node",
                    "adjacent": all_connections,
                }

            target = net.nodes.get(target_node_id)
            if not target:
                return {"status": "error", "message": "Target node not found"}

            if target.has_active_ice:
                blocking = [i for i in target.active_ice if i.ice_type == ICEType.BARRIER]
                if blocking:
                    return {
                        "status": "blocked",
                        "message": f"Barrier ICE blocks entry: {blocking[0].description}",
                        "ice": [i.to_dict() for i in blocking],
                        "node_id": target_node_id,
                    }

            detection_delta = _DETECTION_PER_MOVE.get(net.difficulty, 5.0)
            cpu_reduction = (self._cyberdeck.cpu_speed - 1.0) * 2.0
            detection_delta = max(1.0, detection_delta - cpu_reduction)

            session.current_node = target_node_id
            session.moves += 1
            session.detection_level += detection_delta

            if target_node_id not in session.nodes_visited:
                session.nodes_visited.append(target_node_id)
            target.visited = True

            if target.node_type == NodeType.HONEYPOT and not target.compromised:
                session.detection_level += 20.0
                target.compromised = True

            for ice in target.active_ice:
                if ice.ice_type == ICEType.TRACE:
                    trace_delta = _DETECTION_PER_ICE_BREAK.get(net.difficulty, 8.0) * 0.5
                    session.detection_level += trace_delta

            result: Dict[str, Any] = {
                "status": "moved",
                "node_id": target_node_id,
                "node_label": target.label,
                "node_type": target.node_type.value,
                "detection_level": round(session.detection_level, 1),
                "detection_delta": round(detection_delta, 1),
                "has_ice": target.has_active_ice,
                "ice": [i.to_dict() for i in target.active_ice],
                "data_available": len(target.extractable_data),
                "is_objective": target_node_id in net.objective_nodes,
                "adjacent": [
                    {"id": n.id, "label": n.label, "type": n.node_type.value, "has_ice": n.has_active_ice}
                    for n in net.get_adjacent(target_node_id)
                ],
                "moves": session.moves,
            }

            if session.detection_level >= 100.0:
                session.status = SessionStatus.DETECTED
                session.ended_at = time.time()
                result["status"] = "detected"
                result["message"] = "TRACE COMPLETE — You've been detected! Session terminated."

            self._save()

        if result["status"] == "detected":
            self._emit("detected", {
                "session_id": session_id,
                "network_id": session.network_id,
                "moves": session.moves,
            })

        return result

    def use_program(
        self,
        session_id: str,
        program_id: str,
        target_ice_id: Optional[str] = None,
        target_node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Use a loaded program during an intrusion.

        Args:
            session_id: Active session ID.
            program_id: Program to use.
            target_ice_id: ICE barrier to target (for counter programs).
            target_node_id: Node to target (for backdoor, virus).

        Returns:
            Dict with program use result.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.is_active:
                return {"status": "error", "message": "No active session"}

            net = self._networks.get(session.network_id)
            if not net:
                return {"status": "error", "message": "Network not found"}

            prog = None
            for p in session.loaded_programs:
                if p.program_id == program_id:
                    prog = p
                    break
            if not prog:
                return {"status": "error", "message": f"Program '{program_id}' not loaded"}
            if prog.uses_remaining <= 0:
                return {"status": "error", "message": f"Program '{program_id}' has no uses remaining"}

            power = prog.base_power
            if session.overclock_active:
                power *= 2
                session.overclock_active = False

            current_node = net.nodes.get(session.current_node)
            if not current_node:
                return {"status": "error", "message": "Current node invalid"}

            result: Dict[str, Any] = {
                "status": "ok",
                "program": program_id,
                "power": power,
            }

            if prog.program_type == ProgramType.ICEBREAKER:
                result = self._use_icebreaker(session, net, current_node, target_ice_id, target_node_id, power)
            elif prog.program_type == ProgramType.CLOAK:
                reduction = min(session.detection_level, power * 3.0)
                session.detection_level -= reduction
                result["detection_reduced"] = round(reduction, 1)
                result["detection_level"] = round(session.detection_level, 1)
                result["message"] = f"Cloak activated — detection reduced by {reduction:.0f}"
            elif prog.program_type == ProgramType.SIPHON:
                result = self._use_siphon(session, net, current_node, target_ice_id, power)
            elif prog.program_type == ProgramType.VIRUS:
                result = self._use_virus(session, net, current_node, target_node_id)
            elif prog.program_type == ProgramType.BACKDOOR:
                result = self._use_backdoor(session, net, target_node_id)
            elif prog.program_type == ProgramType.DECRYPT:
                result = self._use_decrypt(session, net, current_node, target_ice_id, power)
            elif prog.program_type == ProgramType.OVERCLOCK:
                session.overclock_active = True
                result["message"] = "Overclock active — next program use has 2× power"
            else:
                result = {"status": "error", "message": f"Unknown program type: {prog.program_type}"}

            if result.get("status") != "error":
                prog.uses_remaining -= 1
                result["uses_remaining"] = prog.uses_remaining

            self._save()

        return result

    def _use_icebreaker(
        self,
        session: IntrusionSession,
        net: NetworkMap,
        current_node: NetworkNode,
        target_ice_id: Optional[str],
        target_node_id: Optional[str],
        power: int,
    ) -> Dict[str, Any]:
        """Break barrier ICE on current or adjacent node."""
        search_node = current_node
        if target_node_id and target_node_id in current_node.connections:
            search_node = net.nodes.get(target_node_id, current_node)

        target_ice = None
        if target_ice_id:
            for ice in search_node.ice:
                if ice.id == target_ice_id and ice.active:
                    target_ice = ice
                    break
        else:
            for ice in search_node.active_ice:
                if ice.ice_type == ICEType.BARRIER:
                    target_ice = ice
                    break

        if not target_ice:
            return {"status": "error", "message": "No barrier ICE found to break"}

        if power >= target_ice.strength:
            target_ice.active = False
            session.ice_broken += 1
            self._total_ice_broken += 1
            xp = _XP_PER_ICE.get(net.difficulty, 10)
            session.xp_earned += xp
            self._total_xp += xp
            detection_delta = _DETECTION_PER_ICE_BREAK.get(net.difficulty, 8.0)
            session.detection_level += detection_delta
            return {
                "status": "ice_broken",
                "ice_id": target_ice.id,
                "ice_type": target_ice.ice_type.value,
                "xp_earned": xp,
                "detection_delta": round(detection_delta, 1),
                "detection_level": round(session.detection_level, 1),
                "message": f"Barrier ICE '{target_ice.description}' shattered!",
            }
        else:
            return {
                "status": "failed",
                "message": f"Power {power} insufficient vs ICE strength {target_ice.strength}",
                "power": power,
                "ice_strength": target_ice.strength,
            }

    def _use_siphon(
        self,
        session: IntrusionSession,
        net: NetworkMap,
        current_node: NetworkNode,
        target_ice_id: Optional[str],
        power: int,
    ) -> Dict[str, Any]:
        """Absorb Black ICE damage."""
        target_ice = None
        if target_ice_id:
            for ice in current_node.ice:
                if ice.id == target_ice_id and ice.active:
                    target_ice = ice
                    break
        else:
            for ice in current_node.active_ice:
                if ice.ice_type == ICEType.BLACK_ICE:
                    target_ice = ice
                    break

        if not target_ice:
            return {"status": "error", "message": "No Black ICE found to siphon"}

        if power >= target_ice.strength:
            target_ice.active = False
            session.ice_broken += 1
            self._total_ice_broken += 1
            xp = _XP_PER_ICE.get(net.difficulty, 10) * 2
            session.xp_earned += xp
            self._total_xp += xp
            return {
                "status": "ice_siphoned",
                "ice_id": target_ice.id,
                "xp_earned": xp,
                "message": f"Black ICE '{target_ice.description}' absorbed! +{xp} XP",
            }
        else:
            ram_dmg = _BLACK_ICE_RAM_DAMAGE.get(net.difficulty, 1)
            session.ram_damage_taken += ram_dmg
            self._cyberdeck.ram_damage += ram_dmg
            return {
                "status": "siphon_failed",
                "ram_damage": ram_dmg,
                "message": f"Siphon failed! Black ICE deals {ram_dmg} RAM damage.",
            }

    def _use_virus(
        self,
        session: IntrusionSession,
        net: NetworkMap,
        current_node: NetworkNode,
        target_node_id: Optional[str],
    ) -> Dict[str, Any]:
        """Disable all ICE on a node."""
        target = current_node
        if target_node_id:
            target = net.nodes.get(target_node_id, current_node)

        disabled = 0
        for ice in target.ice:
            if ice.active:
                ice.active = False
                disabled += 1
                session.ice_broken += 1
                self._total_ice_broken += 1

        if disabled == 0:
            return {"status": "no_effect", "message": "No active ICE on this node"}

        target.compromised = True
        xp = disabled * _XP_PER_ICE.get(net.difficulty, 10)
        session.xp_earned += xp
        self._total_xp += xp

        return {
            "status": "virus_deployed",
            "ice_disabled": disabled,
            "node_id": target.id,
            "xp_earned": xp,
            "message": f"Neurovirus deployed — {disabled} ICE disabled on '{target.label}'!",
        }

    def _use_backdoor(
        self,
        session: IntrusionSession,
        net: NetworkMap,
        target_node_id: Optional[str],
    ) -> Dict[str, Any]:
        """Create a shortcut link to any visited node."""
        if not target_node_id:
            return {"status": "error", "message": "Specify target_node_id for backdoor"}
        if target_node_id not in session.nodes_visited:
            return {"status": "error", "message": "Can only backdoor previously visited nodes"}
        if target_node_id == session.current_node:
            return {"status": "error", "message": "Can't backdoor to current node"}

        link = (session.current_node, target_node_id)
        session.backdoor_links.append(link)

        return {
            "status": "backdoor_planted",
            "from_node": session.current_node,
            "to_node": target_node_id,
            "message": f"Backdoor planted: {session.current_node} ↔ {target_node_id}",
        }

    def _use_decrypt(
        self,
        session: IntrusionSession,
        net: NetworkMap,
        current_node: NetworkNode,
        target_ice_id: Optional[str],
        power: int,
    ) -> Dict[str, Any]:
        """Counter Scramble ICE or decrypt data."""
        target_ice = None
        if target_ice_id:
            for ice in current_node.ice:
                if ice.id == target_ice_id and ice.active:
                    target_ice = ice
                    break
        else:
            for ice in current_node.active_ice:
                if ice.ice_type == ICEType.SCRAMBLE:
                    target_ice = ice
                    break

        if target_ice:
            if power >= target_ice.strength:
                target_ice.active = False
                session.ice_broken += 1
                self._total_ice_broken += 1
                xp = _XP_PER_ICE.get(net.difficulty, 10)
                session.xp_earned += xp
                self._total_xp += xp
                return {
                    "status": "ice_decrypted",
                    "ice_id": target_ice.id,
                    "xp_earned": xp,
                    "message": f"Scramble ICE '{target_ice.description}' neutralised!",
                }
            else:
                return {
                    "status": "failed",
                    "message": f"Power {power} insufficient vs ICE strength {target_ice.strength}",
                }

        decrypted = 0
        for dp in current_node.data:
            if dp.encrypted and not dp.extracted:
                dp.encrypted = False
                decrypted += 1

        if decrypted > 0:
            return {
                "status": "data_decrypted",
                "count": decrypted,
                "message": f"Decrypted {decrypted} data payload(s)",
            }

        return {"status": "no_effect", "message": "Nothing to decrypt on this node"}

    def extract_data(self, session_id: str, data_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract data from the current node.

        Args:
            session_id: Active session ID.
            data_id: Specific data payload ID, or None for first available.

        Returns:
            Dict with extraction result.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.is_active:
                return {"status": "error", "message": "No active session"}

            net = self._networks.get(session.network_id)
            if not net:
                return {"status": "error", "message": "Network not found"}

            node = net.nodes.get(session.current_node)
            if not node:
                return {"status": "error", "message": "Current node invalid"}

            target_data = None
            if data_id:
                for dp in node.data:
                    if dp.id == data_id and not dp.extracted:
                        target_data = dp
                        break
            else:
                for dp in node.extractable_data:
                    target_data = dp
                    break

            if not target_data:
                return {"status": "error", "message": "No extractable data on this node"}

            if target_data.encrypted:
                return {
                    "status": "encrypted",
                    "data_id": target_data.id,
                    "message": "Data is encrypted — use Decrypt program first",
                }

            if target_data.data_type == "trap":
                session.detection_level += 30.0
                target_data.extracted = True
                result = {
                    "status": "trap",
                    "message": "IT'S A TRAP! Detection level surged by 30!",
                    "detection_level": round(session.detection_level, 1),
                }
                if session.detection_level >= 100.0:
                    session.status = SessionStatus.DETECTED
                    session.ended_at = time.time()
                    result["detected"] = True
                self._save()
                return result

            target_data.extracted = True
            session.data_extracted.append({
                "data_id": target_data.id,
                "label": target_data.label,
                "value": target_data.value,
                "data_type": target_data.data_type,
            })

            if target_data.data_type == "credits":
                session.credits_earned += target_data.value

            self._total_data_extracted += 1
            xp = _XP_PER_EXTRACT.get(net.difficulty, 15)
            session.xp_earned += xp
            self._total_xp += xp

            detection_delta = _DETECTION_PER_EXTRACT.get(net.difficulty, 8.0)
            session.detection_level += detection_delta

            result: Dict[str, Any] = {
                "status": "extracted",
                "data_id": target_data.id,
                "label": target_data.label,
                "value": target_data.value,
                "data_type": target_data.data_type,
                "xp_earned": xp,
                "detection_delta": round(detection_delta, 1),
                "detection_level": round(session.detection_level, 1),
                "message": f"Extracted: {target_data.label} ({target_data.data_type}: {target_data.value})",
            }

            if session.detection_level >= 100.0:
                session.status = SessionStatus.DETECTED
                session.ended_at = time.time()
                result["detected"] = True
                result["message"] += " — BUT YOU'VE BEEN DETECTED!"

            if net.is_complete:
                result["network_complete"] = True
                if net.network_id not in self._completed_networks:
                    self._completed_networks.append(net.network_id)
                    bonus_xp = _XP_COMPLETION_BONUS.get(net.difficulty, 50)
                    session.xp_earned += bonus_xp
                    self._total_xp += bonus_xp
                    result["completion_bonus_xp"] = bonus_xp
                    result["message"] += f" Network COMPLETE! +{bonus_xp} bonus XP!"

            self._save()

        return result

    def jack_out(self, session_id: str) -> Dict[str, Any]:
        """Voluntarily disconnect from the network.

        Args:
            session_id: Active session ID.

        Returns:
            Dict with session summary.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.is_active:
                return {"status": "error", "message": "No active session"}

            session.status = SessionStatus.JACKED_OUT
            session.ended_at = time.time()
            self._cyberdeck.ram_used = 0

            net = self._networks.get(session.network_id)
            network_complete = net.is_complete if net else False

            if network_complete and session.network_id not in self._completed_networks:
                self._completed_networks.append(session.network_id)
                bonus_xp = _XP_COMPLETION_BONUS.get(net.difficulty if net else 1, 50)
                session.xp_earned += bonus_xp
                self._total_xp += bonus_xp

            self._save()

        self._emit("jack_out", {
            "session_id": session_id,
            "network_id": session.network_id,
            "data_extracted": len(session.data_extracted),
            "ice_broken": session.ice_broken,
            "xp_earned": session.xp_earned,
            "credits_earned": session.credits_earned,
        })

        return {
            "status": "jacked_out",
            "session_id": session_id,
            "duration": round(session.duration, 1),
            "nodes_visited": len(session.nodes_visited),
            "data_extracted": len(session.data_extracted),
            "credits_earned": session.credits_earned,
            "ice_broken": session.ice_broken,
            "xp_earned": session.xp_earned,
            "detection_level": round(session.detection_level, 1),
            "ram_damage_taken": session.ram_damage_taken,
            "network_complete": network_complete,
        }

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return session state."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return session.to_dict()

    def get_active_session(self) -> Optional[Dict[str, Any]]:
        """Return the currently active intrusion session, or None."""
        with self._lock:
            for s in self._sessions.values():
                if s.is_active:
                    return s.to_dict()
            return None

    # ── Node Scan ─────────────────────────────────────────────────────────

    def scan_node(self, session_id: str) -> Dict[str, Any]:
        """Scan the current node for details.

        Args:
            session_id: Active session ID.

        Returns:
            Dict with full node details.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.is_active:
                return {"status": "error", "message": "No active session"}

            net = self._networks.get(session.network_id)
            if not net:
                return {"status": "error", "message": "Network not found"}

            node = net.nodes.get(session.current_node)
            if not node:
                return {"status": "error", "message": "Current node invalid"}

            return {
                "status": "scanned",
                "node_id": node.id,
                "label": node.label,
                "type": node.node_type.value,
                "description": node.description,
                "is_objective": node.id in net.objective_nodes,
                "compromised": node.compromised,
                "ice": [i.to_dict() for i in node.ice],
                "active_ice_count": len(node.active_ice),
                "data": [
                    {
                        "id": d.id,
                        "label": d.label,
                        "data_type": d.data_type,
                        "encrypted": d.encrypted,
                        "extracted": d.extracted,
                    }
                    for d in node.data
                ],
                "adjacent": [
                    {
                        "id": n.id,
                        "label": n.label,
                        "type": n.node_type.value,
                        "has_ice": n.has_active_ice,
                        "visited": n.visited,
                    }
                    for n in net.get_adjacent(session.current_node)
                ],
                "connections": node.connections,
            }

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return global cyberspace stats."""
        with self._lock:
            return {
                "total_intrusions": self._total_intrusions,
                "total_data_extracted": self._total_data_extracted,
                "total_ice_broken": self._total_ice_broken,
                "total_xp": self._total_xp,
                "completed_networks": list(self._completed_networks),
                "networks_available": len(_NETWORK_TEMPLATES),
                "networks_generated": len(self._networks),
                "cyberdeck": self.get_cyberdeck(),
                "active_session": self.get_active_session() is not None,
            }

    # ── Reset ─────────────────────────────────────────────────────────────

    def reset(self) -> Dict[str, Any]:
        """Reset all cyberspace state (for testing/debug)."""
        with self._lock:
            self._networks.clear()
            self._sessions.clear()
            self._cyberdeck = CyberdeckState.from_tier("netrunner_mk1")
            self._completed_networks.clear()
            self._total_intrusions = 0
            self._total_data_extracted = 0
            self._total_ice_broken = 0
            self._total_xp = 0
            if self._SAVE_PATH.exists():
                self._SAVE_PATH.unlink()
        return {"status": "reset"}


# ──── Singleton ───────────────────────────────────────────────────────────────

_INSTANCE: Optional[CyberspaceEngine] = None
_INSTANCE_LOCK = threading.Lock()


def get_cyberspace_engine() -> CyberspaceEngine:
    """Return the singleton CyberspaceEngine."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = CyberspaceEngine()
    return _INSTANCE


def reset_cyberspace_engine() -> None:
    """Reset the singleton (for testing)."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE:
            _INSTANCE.reset()
        _INSTANCE = None
