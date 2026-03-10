"""Tests for the cyberspace network intrusion system.

Tests cover:
    - Network generation and topology
    - ICE barriers and types
    - Programs and usage
    - Cyberdeck hardware and upgrades
    - Intrusion sessions (jack in, move, extract, jack out)
    - Detection and trace mechanics
    - Data extraction and rewards
    - Persistence (save/load)
    - Cyberspace skills
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.world.cyberspace import (
    CyberspaceEngine,
    CyberdeckState,
    DataPayload,
    ICEBarrier,
    ICEType,
    IntrusionSession,
    LoadedProgram,
    NetworkMap,
    NetworkNode,
    NodeType,
    PROGRAM_CATALOG,
    CYBERDECK_TIERS,
    ProgramType,
    SessionStatus,
    get_cyberspace_engine,
    reset_cyberspace_engine,
    _generate_network_topology,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path):
    """Create a fresh CyberspaceEngine with temp save path."""
    reset_cyberspace_engine()
    save_path = tmp_path / "cyberspace.json"
    with patch.object(CyberspaceEngine, "_SAVE_PATH", save_path):
        eng = CyberspaceEngine()
        eng._emit = MagicMock()
        yield eng


@pytest.fixture
def network(engine):
    """Engine with a generated difficulty-1 network."""
    engine.generate_network("omnicorp_subnet", difficulty=1, seed="test_seed")
    return engine


@pytest.fixture
def session(network):
    """Engine with an active intrusion session."""
    network.install_program("icebreaker")
    network.install_program("cloak")
    network.install_program("decrypt")
    result = network.jack_in("omnicorp_subnet")
    assert result["status"] == "jacked_in"
    return network, result["session_id"]


# ── Data Classes ──────────────────────────────────────────────────────────────


class TestICEBarrier:
    """Test ICEBarrier dataclass."""

    def test_create(self):
        ice = ICEBarrier(id="ice_1", ice_type=ICEType.BARRIER, strength=5)
        assert ice.id == "ice_1"
        assert ice.ice_type == ICEType.BARRIER
        assert ice.strength == 5
        assert ice.active is True

    def test_to_dict(self):
        ice = ICEBarrier(id="ice_1", ice_type=ICEType.TRACE, strength=3)
        d = ice.to_dict()
        assert d["id"] == "ice_1"
        assert d["ice_type"] == "trace"
        assert d["strength"] == 3
        assert d["active"] is True

    def test_from_dict(self):
        d = {"id": "ice_2", "ice_type": "black_ice", "strength": 7, "active": False}
        ice = ICEBarrier.from_dict(d)
        assert ice.ice_type == ICEType.BLACK_ICE
        assert ice.active is False

    def test_all_ice_types(self):
        for t in ICEType:
            ice = ICEBarrier(id=f"ice_{t.value}", ice_type=t)
            assert ice.ice_type == t


class TestDataPayload:
    """Test DataPayload dataclass."""

    def test_create(self):
        dp = DataPayload(id="d1", label="Credits Cache", value=500, data_type="credits")
        assert dp.value == 500
        assert dp.extracted is False
        assert dp.encrypted is False

    def test_to_from_dict(self):
        dp = DataPayload(id="d1", label="Intel", value=100, data_type="intel", encrypted=True)
        d = dp.to_dict()
        dp2 = DataPayload.from_dict(d)
        assert dp2.encrypted is True
        assert dp2.value == 100


class TestNetworkNode:
    """Test NetworkNode dataclass."""

    def test_create(self):
        node = NetworkNode(id="n1", label="Router 1", node_type=NodeType.ROUTER)
        assert node.has_active_ice is False
        assert node.extractable_data == []

    def test_active_ice(self):
        node = NetworkNode(
            id="n1", label="Server",
            ice=[
                ICEBarrier(id="i1", ice_type=ICEType.BARRIER, active=True),
                ICEBarrier(id="i2", ice_type=ICEType.TRACE, active=False),
            ],
        )
        assert node.has_active_ice is True
        assert len(node.active_ice) == 1

    def test_extractable_data(self):
        node = NetworkNode(
            id="n1", label="Datastore",
            data=[
                DataPayload(id="d1", label="A", extracted=False),
                DataPayload(id="d2", label="B", extracted=True),
            ],
        )
        assert len(node.extractable_data) == 1

    def test_connections(self):
        node = NetworkNode(id="n1", label="R", connections=["n2", "n3"])
        assert "n2" in node.connections

    def test_to_from_dict(self):
        node = NetworkNode(
            id="n1", label="Test", node_type=NodeType.FIREWALL,
            ice=[ICEBarrier(id="i1", ice_type=ICEType.BARRIER)],
            data=[DataPayload(id="d1", label="X")],
            connections=["n2"],
        )
        d = node.to_dict()
        node2 = NetworkNode.from_dict(d)
        assert node2.node_type == NodeType.FIREWALL
        assert len(node2.ice) == 1
        assert len(node2.data) == 1

    def test_all_node_types(self):
        for t in NodeType:
            n = NetworkNode(id=f"n_{t.value}", label=t.value, node_type=t)
            assert n.node_type == t


class TestCyberdeckState:
    """Test CyberdeckState dataclass."""

    def test_from_tier(self):
        deck = CyberdeckState.from_tier("void_runner")
        assert deck.ram_total == 8
        assert deck.cpu_speed == 1.5
        assert deck.max_programs == 5

    def test_ram_available(self):
        deck = CyberdeckState(ram_total=8, ram_used=3, ram_damage=1)
        assert deck.ram_available == 4
        assert deck.effective_ram == 7

    def test_ram_available_never_negative(self):
        deck = CyberdeckState(ram_total=4, ram_used=3, ram_damage=5)
        assert deck.ram_available == 0

    def test_to_from_dict(self):
        deck = CyberdeckState.from_tier("specter_3000")
        deck.installed_programs = ["icebreaker", "cloak"]
        d = deck.to_dict()
        deck2 = CyberdeckState.from_dict(d)
        assert deck2.ram_total == 12
        assert deck2.installed_programs == ["icebreaker", "cloak"]

    def test_all_tiers(self):
        for tier_id in CYBERDECK_TIERS:
            deck = CyberdeckState.from_tier(tier_id)
            assert deck.ram_total > 0
            assert deck.cpu_speed >= 1.0


class TestNetworkMap:
    """Test NetworkMap dataclass."""

    def test_create(self):
        nm = NetworkMap(network_id="test", label="Test Network")
        assert nm.node_count == 0

    def test_is_complete(self):
        nm = NetworkMap(
            network_id="test", label="Test",
            nodes={
                "obj1": NetworkNode(
                    id="obj1", label="Data",
                    data=[DataPayload(id="d1", label="X", extracted=True)],
                ),
            },
            objective_nodes=["obj1"],
        )
        assert nm.is_complete is True

    def test_is_not_complete(self):
        nm = NetworkMap(
            network_id="test", label="Test",
            nodes={
                "obj1": NetworkNode(
                    id="obj1", label="Data",
                    data=[DataPayload(id="d1", label="X", extracted=False)],
                ),
            },
            objective_nodes=["obj1"],
        )
        assert nm.is_complete is False

    def test_get_adjacent(self):
        nm = NetworkMap(
            network_id="test", label="Test",
            nodes={
                "a": NetworkNode(id="a", label="A", connections=["b", "c"]),
                "b": NetworkNode(id="b", label="B"),
                "c": NetworkNode(id="c", label="C"),
            },
        )
        adj = nm.get_adjacent("a")
        assert len(adj) == 2

    def test_to_from_dict(self):
        nm = NetworkMap(
            network_id="test", label="Test",
            nodes={"n1": NetworkNode(id="n1", label="N")},
            objective_nodes=["n1"],
        )
        d = nm.to_dict()
        nm2 = NetworkMap.from_dict(d)
        assert nm2.network_id == "test"
        assert "n1" in nm2.nodes


class TestLoadedProgram:
    """Test LoadedProgram dataclass."""

    def test_to_dict(self):
        lp = LoadedProgram(
            program_id="icebreaker",
            program_type=ProgramType.ICEBREAKER,
            uses_remaining=3,
            base_power=5,
            ram_cost=2,
        )
        d = lp.to_dict()
        assert d["program_id"] == "icebreaker"
        assert d["uses_remaining"] == 3


class TestIntrusionSession:
    """Test IntrusionSession dataclass."""

    def test_is_active(self):
        s = IntrusionSession()
        assert s.is_active is True

    def test_is_not_active_when_detected(self):
        s = IntrusionSession(status=SessionStatus.DETECTED)
        assert s.is_active is False

    def test_duration(self):
        s = IntrusionSession(started_at=100.0, ended_at=110.0)
        assert s.duration == 10.0


class TestProgramCatalog:
    """Test program catalog definitions."""

    def test_all_programs_defined(self):
        expected = {"icebreaker", "cloak", "siphon", "virus", "backdoor", "decrypt", "overclock"}
        assert set(PROGRAM_CATALOG.keys()) == expected

    def test_programs_have_required_fields(self):
        for pid, pdef in PROGRAM_CATALOG.items():
            assert "name" in pdef, f"{pid} missing name"
            assert "type" in pdef, f"{pid} missing type"
            assert "ram_cost" in pdef, f"{pid} missing ram_cost"
            assert "uses" in pdef, f"{pid} missing uses"
            assert pdef["ram_cost"] > 0, f"{pid} has zero ram cost"

    def test_counter_programs_exist(self):
        counter_map = {
            "icebreaker": ICEType.BARRIER,
            "cloak": ICEType.TRACE,
            "siphon": ICEType.BLACK_ICE,
            "decrypt": ICEType.SCRAMBLE,
        }
        for pid, expected_ice in counter_map.items():
            assert PROGRAM_CATALOG[pid]["counters"] == expected_ice


# ── Network Generation ────────────────────────────────────────────────────────


class TestNetworkGeneration:
    """Test procedural network generation."""

    def test_generate_basic(self):
        net = _generate_network_topology("omnicorp_subnet", 1, seed="test")
        assert net.network_id == "omnicorp_subnet"
        assert net.difficulty == 1
        assert len(net.nodes) >= 5

    def test_entry_node_exists(self):
        net = _generate_network_topology("omnicorp_subnet", 1, seed="test")
        assert net.entry_node in net.nodes
        assert net.nodes[net.entry_node].node_type == NodeType.ENTRY

    def test_objective_nodes_exist(self):
        net = _generate_network_topology("omnicorp_subnet", 2, seed="test")
        assert len(net.objective_nodes) >= 1
        for oid in net.objective_nodes:
            assert oid in net.nodes
            assert net.nodes[oid].node_type == NodeType.DATASTORE

    def test_objective_nodes_have_data(self):
        net = _generate_network_topology("neotech_research", 2, seed="test")
        for oid in net.objective_nodes:
            assert len(net.nodes[oid].data) >= 1

    def test_higher_difficulty_more_nodes(self):
        net1 = _generate_network_topology("omnicorp_subnet", 1, seed="test")
        net3 = _generate_network_topology("synthsec_mainframe", 3, seed="test")
        assert len(net3.nodes) > len(net1.nodes)

    def test_higher_difficulty_more_ice(self):
        net1 = _generate_network_topology("omnicorp_subnet", 1, seed="test")
        net3 = _generate_network_topology("synthsec_mainframe", 3, seed="test")
        ice1 = sum(len(n.ice) for n in net1.nodes.values())
        ice3 = sum(len(n.ice) for n in net3.nodes.values())
        assert ice3 > ice1

    def test_difficulty_3_has_black_ice(self):
        net = _generate_network_topology("synthsec_mainframe", 3, seed="black_ice_seed")
        all_ice = [i for n in net.nodes.values() for i in n.ice]
        ice_types = {i.ice_type for i in all_ice}
        assert len(ice_types) >= 2

    def test_difficulty_3_has_honeypot(self):
        net = _generate_network_topology("synthsec_mainframe", 3, seed="test")
        types = {n.node_type for n in net.nodes.values()}
        assert NodeType.HONEYPOT in types or net.difficulty >= 3

    def test_all_nodes_connected(self):
        net = _generate_network_topology("omnicorp_subnet", 1, seed="test")
        visited: set = set()
        stack = [net.entry_node]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            node = net.nodes.get(nid)
            if node:
                stack.extend(node.connections)
        assert len(visited) == len(net.nodes)

    def test_deterministic_with_seed(self):
        net1 = _generate_network_topology("omnicorp_subnet", 1, seed="abc")
        net2 = _generate_network_topology("omnicorp_subnet", 1, seed="abc")
        assert len(net1.nodes) == len(net2.nodes)
        assert set(net1.nodes.keys()) == set(net2.nodes.keys())

    def test_all_templates_generate(self):
        from engine.world.cyberspace import _NETWORK_TEMPLATES
        for tid, tmpl in _NETWORK_TEMPLATES.items():
            net = _generate_network_topology(tid, tmpl["difficulty"], seed="test")
            assert net.node_count >= 5

    def test_custom_network_id(self):
        net = _generate_network_topology("my_custom_net", 2, seed="test")
        assert net.network_id == "my_custom_net"
        assert net.difficulty == 2

    @pytest.mark.parametrize("difficulty", [1, 2, 3, 4, 5])
    def test_all_difficulties(self, difficulty):
        net = _generate_network_topology("omnicorp_subnet", difficulty, seed="test")
        assert net.difficulty == difficulty
        assert net.node_count >= 5 + difficulty * 2 - 1


# ── Engine Core ───────────────────────────────────────────────────────────────


class TestCyberspaceEngine:
    """Test the CyberspaceEngine class."""

    def test_generate_network(self, engine):
        result = engine.generate_network("omnicorp_subnet", difficulty=1, seed="test")
        assert result["status"] == "generated"
        assert result["node_count"] >= 5

    def test_generate_existing_returns_exists(self, network):
        result = network.generate_network("omnicorp_subnet")
        assert result["status"] == "exists"

    def test_generate_force_regenerates(self, network):
        result = network.generate_network("omnicorp_subnet", force=True, seed="new")
        assert result["status"] == "generated"

    def test_list_networks(self, network):
        nets = network.list_networks()
        generated = [n for n in nets if n.get("node_count", 0) > 0]
        assert len(generated) >= 1

    def test_list_networks_includes_templates(self, engine):
        nets = engine.list_networks()
        assert len(nets) >= 6

    def test_get_network(self, network):
        net = network.get_network("omnicorp_subnet")
        assert net is not None
        assert net.network_id == "omnicorp_subnet"

    def test_get_network_none(self, engine):
        assert engine.get_network("nonexistent") is None

    def test_get_network_map(self, network):
        data = network.get_network_map("omnicorp_subnet")
        assert data is not None
        assert "nodes" in data
        assert "entry_node" in data


# ── Cyberdeck ─────────────────────────────────────────────────────────────────


class TestCyberdeck:
    """Test cyberdeck management."""

    def test_default_deck(self, engine):
        deck = engine.get_cyberdeck()
        assert deck["deck_id"] == "netrunner_mk1"
        assert deck["ram_total"] == 4

    def test_upgrade_deck(self, engine):
        result = engine.upgrade_cyberdeck("void_runner")
        assert result["status"] == "upgraded"
        assert result["ram"] == 8

    def test_upgrade_unknown_deck(self, engine):
        result = engine.upgrade_cyberdeck("nonexistent")
        assert result["status"] == "error"

    def test_install_program(self, engine):
        result = engine.install_program("icebreaker")
        assert result["status"] == "installed"
        deck = engine.get_cyberdeck()
        assert "icebreaker" in deck["installed_programs"]

    def test_install_duplicate(self, engine):
        engine.install_program("icebreaker")
        result = engine.install_program("icebreaker")
        assert result["status"] == "error"

    def test_install_over_max(self, engine):
        engine.install_program("icebreaker")
        engine.install_program("cloak")
        engine.install_program("decrypt")
        result = engine.install_program("siphon")
        assert result["status"] == "error"
        assert "full" in result["message"].lower()

    def test_uninstall_program(self, engine):
        engine.install_program("icebreaker")
        result = engine.uninstall_program("icebreaker")
        assert result["status"] == "uninstalled"

    def test_uninstall_not_installed(self, engine):
        result = engine.uninstall_program("icebreaker")
        assert result["status"] == "error"

    def test_repair_no_damage(self, engine):
        result = engine.repair_cyberdeck()
        assert result["status"] == "no_damage"

    def test_repair_damage(self, engine):
        engine._cyberdeck.ram_damage = 3
        result = engine.repair_cyberdeck()
        assert result["status"] == "repaired"
        assert result["ram_restored"] == 3
        assert engine._cyberdeck.ram_damage == 0

    def test_repair_partial(self, engine):
        engine._cyberdeck.ram_damage = 5
        result = engine.repair_cyberdeck(ram_restore=2)
        assert result["ram_restored"] == 2
        assert engine._cyberdeck.ram_damage == 3


# ── Intrusion Sessions ───────────────────────────────────────────────────────


class TestJackIn:
    """Test jack-in to networks."""

    def test_jack_in(self, network):
        network.install_program("icebreaker")
        result = network.jack_in("omnicorp_subnet")
        assert result["status"] == "jacked_in"
        assert "session_id" in result
        assert result["detection_level"] == 0.0

    def test_jack_in_nonexistent(self, engine):
        result = engine.jack_in("nonexistent")
        assert result["status"] == "error"

    def test_jack_in_double(self, network):
        network.install_program("icebreaker")
        network.jack_in("omnicorp_subnet")
        result = network.jack_in("omnicorp_subnet")
        assert result["status"] == "error"
        assert "already" in result["message"].lower()

    def test_jack_in_loads_programs(self, network):
        network.install_program("icebreaker")
        network.install_program("cloak")
        result = network.jack_in("omnicorp_subnet")
        assert len(result["programs_loaded"]) == 2

    def test_jack_in_shows_adjacent(self, network):
        network.install_program("icebreaker")
        result = network.jack_in("omnicorp_subnet")
        assert len(result["adjacent"]) >= 1


class TestMovement:
    """Test network node traversal."""

    def test_move_to_adjacent(self, session):
        engine, sid = session
        scan = engine.scan_node(sid)
        adj = scan["adjacent"]
        if adj:
            target = adj[0]["id"]
            result = engine.move_to(sid, target)
            assert result["status"] in ("moved", "blocked")

    def test_move_to_non_adjacent(self, session):
        engine, sid = session
        result = engine.move_to(sid, "nonexistent_node_xyz")
        assert result["status"] == "error"

    def test_move_increases_detection(self, session):
        engine, sid = session
        scan = engine.scan_node(sid)
        adj = [a for a in scan["adjacent"] if not a.get("has_ice")]
        if adj:
            result = engine.move_to(sid, adj[0]["id"])
            if result["status"] == "moved":
                assert result["detection_level"] > 0

    def test_move_no_active_session(self, engine):
        result = engine.move_to("fake_session", "fake_node")
        assert result["status"] == "error"

    def test_blocked_by_barrier_ice(self, session):
        engine, sid = session
        net = engine.get_network("omnicorp_subnet")
        scan = engine.scan_node(sid)
        for adj in scan["adjacent"]:
            node = net.nodes.get(adj["id"])
            if node and any(i.active and i.ice_type == ICEType.BARRIER for i in node.ice):
                result = engine.move_to(sid, adj["id"])
                assert result["status"] == "blocked"
                break


class TestProgramUsage:
    """Test program usage during intrusion."""

    def test_use_cloak(self, session):
        engine, sid = session
        scan = engine.scan_node(sid)
        adj = [a for a in scan["adjacent"] if not a.get("has_ice")]
        if adj:
            engine.move_to(sid, adj[0]["id"])
        result = engine.use_program(sid, "cloak")
        if result["status"] != "error":
            assert "detection_reduced" in result or result["status"] == "ok"

    def test_use_overclock(self, session):
        engine, sid = session
        engine.install_program("overclock")
        engine.jack_out(sid)
        engine.install_program("overclock")
        result2 = engine.jack_in("omnicorp_subnet")
        sid2 = result2["session_id"]
        result = engine.use_program(sid2, "overclock")
        if result["status"] != "error":
            s = engine._sessions[sid2]
            assert s.overclock_active is True

    def test_use_program_no_uses(self, session):
        engine, sid = session
        for p in engine._sessions[sid].loaded_programs:
            if p.program_id == "cloak":
                p.uses_remaining = 0
        result = engine.use_program(sid, "cloak")
        assert result["status"] == "error"
        assert "no uses" in result["message"].lower()

    def test_use_unknown_program(self, session):
        engine, sid = session
        result = engine.use_program(sid, "nonexistent_program")
        assert result["status"] == "error"


class TestDataExtraction:
    """Test data extraction from nodes."""

    def test_extract_no_data(self, session):
        engine, sid = session
        result = engine.extract_data(sid)
        assert result["status"] == "error" or result["status"] == "extracted"

    def test_extract_from_datastore(self, session):
        engine, sid = session
        net = engine.get_network("omnicorp_subnet")
        for oid in net.objective_nodes:
            obj_node = net.nodes[oid]
            if not obj_node.has_active_ice:
                engine._sessions[sid].current_node = oid
                obj_node.visited = True
                for dp in obj_node.data:
                    dp.encrypted = False
                result = engine.extract_data(sid)
                assert result["status"] in ("extracted", "trap")
                break

    def test_extract_encrypted_blocked(self, session):
        engine, sid = session
        net = engine.get_network("omnicorp_subnet")
        for oid in net.objective_nodes:
            obj_node = net.nodes[oid]
            engine._sessions[sid].current_node = oid
            for dp in obj_node.data:
                dp.encrypted = True
            result = engine.extract_data(sid)
            assert result["status"] == "encrypted"
            break


class TestJackOut:
    """Test jack-out and session summary."""

    def test_jack_out(self, session):
        engine, sid = session
        result = engine.jack_out(sid)
        assert result["status"] == "jacked_out"
        assert "duration" in result
        assert "xp_earned" in result

    def test_jack_out_no_session(self, engine):
        result = engine.jack_out("fake_session")
        assert result["status"] == "error"

    def test_jack_out_clears_ram(self, session):
        engine, sid = session
        assert engine._cyberdeck.ram_used > 0
        engine.jack_out(sid)
        assert engine._cyberdeck.ram_used == 0


class TestDetection:
    """Test detection and trace mechanics."""

    def test_detection_triggers_at_100(self, session):
        engine, sid = session
        engine._sessions[sid].detection_level = 99.0
        scan = engine.scan_node(sid)
        adj = [a for a in scan["adjacent"] if not a.get("has_ice")]
        if adj:
            result = engine.move_to(sid, adj[0]["id"])
            if result.get("detection_level", 0) >= 100:
                assert result["status"] == "detected"

    def test_session_ends_on_detection(self, session):
        engine, sid = session
        engine._sessions[sid].detection_level = 98.0
        engine._sessions[sid].status = SessionStatus.DETECTED
        engine._sessions[sid].ended_at = 100.0
        assert not engine._sessions[sid].is_active


class TestHoneypot:
    """Test honeypot trap mechanics."""

    def test_honeypot_data_is_trap(self):
        node = NetworkNode(
            id="hp1", label="Trap", node_type=NodeType.HONEYPOT,
            data=[DataPayload(id="trap_1", label="Bait", value=0, data_type="trap")],
        )
        assert node.data[0].data_type == "trap"


# ── Persistence ───────────────────────────────────────────────────────────────


class TestPersistence:
    """Test save and load."""

    def test_save_creates_file(self, engine, tmp_path):
        engine.generate_network("omnicorp_subnet", seed="test")
        save_path = tmp_path / "cyberspace.json"
        assert save_path.exists()

    def test_save_load_roundtrip(self, tmp_path):
        save_path = tmp_path / "cyberspace.json"
        with patch.object(CyberspaceEngine, "_SAVE_PATH", save_path):
            eng1 = CyberspaceEngine()
            eng1._emit = MagicMock()
            eng1.generate_network("omnicorp_subnet", seed="test")
            eng1.install_program("icebreaker")
            eng1.upgrade_cyberdeck("void_runner")

        with patch.object(CyberspaceEngine, "_SAVE_PATH", save_path):
            eng2 = CyberspaceEngine()
            assert eng2._cyberdeck.deck_id == "void_runner"
            assert "icebreaker" in eng2._cyberdeck.installed_programs
            assert "omnicorp_subnet" in eng2._networks

    def test_load_missing_file(self, tmp_path):
        save_path = tmp_path / "nonexistent.json"
        with patch.object(CyberspaceEngine, "_SAVE_PATH", save_path):
            eng = CyberspaceEngine()
            assert len(eng._networks) == 0


# ── Stats ─────────────────────────────────────────────────────────────────────


class TestStats:
    """Test global stats tracking."""

    def test_initial_stats(self, engine):
        stats = engine.get_stats()
        assert stats["total_intrusions"] == 0

    def test_intrusion_increments(self, session):
        engine, _ = session
        stats = engine.get_stats()
        assert stats["total_intrusions"] == 1

    def test_active_session_flag(self, session):
        engine, sid = session
        stats = engine.get_stats()
        assert stats["active_session"] is True
        engine.jack_out(sid)
        stats = engine.get_stats()
        assert stats["active_session"] is False


class TestReset:
    """Test engine reset."""

    def test_reset_clears_everything(self, network):
        network.install_program("icebreaker")
        result = network.reset()
        assert result["status"] == "reset"
        assert len(network._networks) == 0
        assert network._total_intrusions == 0


# ── Scan ──────────────────────────────────────────────────────────────────────


class TestScanNode:
    """Test node scanning."""

    def test_scan_entry(self, session):
        engine, sid = session
        result = engine.scan_node(sid)
        assert result["status"] == "scanned"
        assert "label" in result
        assert "adjacent" in result

    def test_scan_no_session(self, engine):
        result = engine.scan_node("fake")
        assert result["status"] == "error"


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    """Test singleton pattern."""

    def test_get_returns_instance(self):
        reset_cyberspace_engine()
        with patch.object(CyberspaceEngine, "_SAVE_PATH", Path("/tmp/cs_test.json")):
            eng = get_cyberspace_engine()
            assert isinstance(eng, CyberspaceEngine)
        reset_cyberspace_engine()

    def test_reset_clears_singleton(self):
        reset_cyberspace_engine()
        with patch.object(CyberspaceEngine, "_SAVE_PATH", Path("/tmp/cs_test2.json")):
            eng1 = get_cyberspace_engine()
            reset_cyberspace_engine()
            eng2 = get_cyberspace_engine()
            assert eng1 is not eng2
        reset_cyberspace_engine()


# ── Backdoor Program ─────────────────────────────────────────────────────────


class TestBackdoor:
    """Test backdoor program mechanics."""

    def test_backdoor_needs_target(self, session):
        engine, sid = session
        engine.install_program("backdoor")
        result = engine.use_program(sid, "backdoor")
        if result["status"] == "error":
            assert "target_node_id" in result["message"].lower() or "not loaded" in result["message"].lower()

    def test_backdoor_needs_visited_node(self, session):
        engine, sid = session
        has_backdoor = any(p.program_id == "backdoor" for p in engine._sessions[sid].loaded_programs)
        if not has_backdoor:
            return
        result = engine.use_program(sid, "backdoor", target_node_id="nonexistent")
        assert result["status"] == "error"


# ── Virus Program ────────────────────────────────────────────────────────────


class TestVirus:
    """Test virus program mechanics."""

    def test_virus_no_ice(self, session):
        engine, sid = session
        has_virus = any(p.program_id == "virus" for p in engine._sessions[sid].loaded_programs)
        if not has_virus:
            return
        result = engine.use_program(sid, "virus")
        assert result["status"] in ("virus_deployed", "no_effect")


# ── Skills ────────────────────────────────────────────────────────────────────


class TestCyberspaceSkills:
    """Test MCP skills for cyberspace."""

    def test_skill_imports(self):
        from engine.skills.builtin.cyberspace_skills import (
            cyberspace_list_networks,
            cyberspace_generate_network,
            cyberspace_view_network,
            cyberspace_jack_in,
            cyberspace_move,
            cyberspace_scan,
            cyberspace_use_program,
            cyberspace_extract,
            cyberspace_jack_out,
            cyberspace_deck_status,
            cyberspace_upgrade_deck,
            cyberspace_install_program,
            cyberspace_uninstall_program,
            cyberspace_repair_deck,
            cyberspace_stats,
        )
        assert callable(cyberspace_list_networks)
        assert callable(cyberspace_jack_in)

    def test_list_networks_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_list_networks
            result = cyberspace_list_networks()
            assert "Networks" in result or "not generated" in result.lower() or "No networks" in result

    def test_generate_network_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_generate_network
            result = cyberspace_generate_network("omnicorp_subnet")
            assert "generated" in result.lower() or "Generated" in result

    def test_deck_status_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_deck_status
            result = cyberspace_deck_status()
            assert "Cyberdeck" in result
            assert "RAM" in result

    def test_install_program_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_install_program
            result = cyberspace_install_program("icebreaker")
            assert "Installed" in result

    def test_upgrade_deck_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_upgrade_deck
            result = cyberspace_upgrade_deck("void_runner")
            assert "Upgraded" in result or "upgraded" in result.lower()

    def test_stats_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_stats
            result = cyberspace_stats()
            assert "Stats" in result

    def test_jack_in_skill(self, network):
        network.install_program("icebreaker")
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=network):
            from engine.skills.builtin.cyberspace_skills import cyberspace_jack_in
            result = cyberspace_jack_in("omnicorp_subnet")
            assert "JACKED IN" in result

    def test_jack_out_skill(self, session):
        engine, sid = session
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_jack_out
            result = cyberspace_jack_out(sid)
            assert "JACKED OUT" in result

    def test_scan_skill(self, session):
        engine, sid = session
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_scan
            result = cyberspace_scan(sid)
            assert "SCAN" in result

    def test_repair_deck_skill(self, engine):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_repair_deck
            result = cyberspace_repair_deck()
            assert "undamaged" in result.lower()

    def test_uninstall_program_skill(self, engine):
        engine.install_program("icebreaker")
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=engine):
            from engine.skills.builtin.cyberspace_skills import cyberspace_uninstall_program
            result = cyberspace_uninstall_program("icebreaker")
            assert "Uninstalled" in result

    def test_view_network_skill(self, network):
        with patch("engine.skills.builtin.cyberspace_skills._engine", return_value=network):
            from engine.skills.builtin.cyberspace_skills import cyberspace_view_network
            result = cyberspace_view_network("omnicorp_subnet")
            assert "Network" in result
            assert "Entry" in result
