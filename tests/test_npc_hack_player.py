"""Unit tests for NPC→PLAYER phone hacking (PH-T4, the reverse direction).

Covers :class:`content.scenes.phone.phone_hack.NpcHackPlayerService`, the
``npc_hack_player`` skill, and the hostile-driven trigger
``maybe_npc_hack_player``:

* Reverse check: the defence is the PLAYER's effective_security + firewall, so a
  low-firewall player gets breached and a HIGH-firewall player (after a PH-T2
  firewall upgrade) BLOCKS the SAME attacker.
* Success is bounded & recoverable: exactly ONE of leak-or-plant, a capped heat
  delta, a small recoverable (player, attacker) standing hit, and last_hacked
  stamped on the player.
* Failure is fully blocked: no leak/plant, no heat, no standing change, but
  last_hacked is still stamped and ``blocked`` is set.
* Surfacing: a ``phone_hacked`` event is emitted (via a stub emitter) and a
  breach notification is persisted as a system comms entry.
* Trigger gate: only fires for hostile/low-standing attackers and respects the
  probability gate (prob=1.0 fires for a hostile NPC; prob=0.0 never fires; a
  friendly NPC never fires).

All tests use isolated temp DBs (PhoneDB / GlobalCommsLog / Database) + a mock
player state at the boundary + a stub socket emitter, so no real data or live
services are touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import pytest

from content.scenes.phone.phone_db import PhoneDB
from content.simulation.database.db import Database
from engine.world.comms_log import GlobalCommsLog
from engine.world.phone_os import PhoneOS
from content.scenes.phone.phone_hack import (
    NpcHackPlayerService,
    NPC_ACTION_LEAK,
    NPC_ACTION_PLANT,
    NPC_ACTION_OBSERVE,
    is_hostile_to_player,
    maybe_npc_hack_player,
)


# ── mock player state ───────────────────────────────────────────────────


class FakePlayerState:
    """Minimal PlayerState stand-in capturing heat + exposing faction standings."""

    def __init__(self, factions: Optional[Dict[str, int]] = None) -> None:
        self.heat = 0
        self.heat_calls: List[int] = []
        self.faction_standings: Dict[str, int] = dict(factions or {})

    def add_heat(self, amount: int, reason: str = "") -> int:
        self.heat += int(amount)
        self.heat_calls.append(int(amount))
        return self.heat

    def get_skill(self, skill: str) -> int:  # unused by the reverse hack
        return 0


class StubEmitter:
    """Captures Socket.IO events emitted by the service."""

    def __init__(self) -> None:
        self.events: List[Tuple[str, Dict[str, Any]]] = []

    def __call__(self, event: str, payload: Dict[str, Any]) -> None:
        self.events.append((event, payload))

    def names(self) -> List[str]:
        return [e for e, _ in self.events]


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def phone_db(tmp_path) -> PhoneDB:
    """Isolated PhoneDB on a temp file."""
    return PhoneDB(tmp_path / "npc_hack_phone.db")


@pytest.fixture()
def phone_os(phone_db: PhoneDB) -> PhoneOS:
    """PhoneOS wired to the temp PhoneDB."""
    return PhoneOS(db=phone_db)


@pytest.fixture()
def comms(tmp_path) -> GlobalCommsLog:
    """Isolated comms log on a temp file."""
    return GlobalCommsLog(path=tmp_path / "npc_hack_comms.db")


@pytest.fixture()
def sim_db(tmp_path) -> Database:
    """Isolated simulation Database on a temp file."""
    return Database(db_path=str(tmp_path / "npc_hack_sim.db"))


class _FixedRng(random.Random):
    """Deterministic RNG: fixed die roll + a fixed ``random()`` value."""

    def __init__(self, roll: int = 10, rand: float = 0.0) -> None:
        super().__init__()
        self._roll = roll
        self._rand = rand

    def randint(self, a: int, b: int) -> int:  # type: ignore[override]
        return self._roll

    def random(self) -> float:  # type: ignore[override]
        return self._rand


def _service(
    phone_os: PhoneOS,
    comms: GlobalCommsLog,
    phone_db: PhoneDB,
    sim_db: Optional[Database] = None,
    player: Optional[FakePlayerState] = None,
    emit: Optional[StubEmitter] = None,
    rng: Optional[random.Random] = None,
) -> NpcHackPlayerService:
    """Build an NpcHackPlayerService with isolated collaborators."""
    return NpcHackPlayerService(
        phone_os=phone_os,
        comms=comms,
        phone_db=phone_db,
        db=sim_db,
        player_state=player or FakePlayerState(),
        emit=emit,
        rng=rng or _FixedRng(roll=10, rand=0.0),
    )


def _seed_player_comms(comms: GlobalCommsLog, n: int = 4) -> List[int]:
    """Seed *n* comms entries involving the player; return their ids."""
    ids = []
    for i in range(n):
        ids.append(
            comms.log(
                "phone_dm", "user", ["aria"], f"player secret {i}",
                thread_id="t-user", kind="message",
            )
        )
    return ids


# ── reverse check: defence = player firewall/security ───────────────────


def test_low_firewall_player_is_breached(phone_os, comms, phone_db, sim_db):
    """A low-firewall player is breached by a hostile NPC (bounded, recoverable)."""
    _seed_player_comms(comms, n=4)
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    player = FakePlayerState()
    # rand=0.0 → coin-flip picks LEAK (< 0.5).
    svc = _service(phone_os, comms, phone_db, sim_db, player,
                   rng=_FixedRng(roll=20, rand=0.0))
    # Strong attacker, weak player defence.
    phone_os.hack_power = lambda cid: 20 if cid == "viktor" else 0  # type: ignore

    result = svc.hack("viktor")
    assert result["success"] is True
    assert result["blocked"] is False
    assert result["attack"] >= result["defence"]
    # last_hacked stamped on the PLAYER.
    assert phone_db.get_phone("user")["last_hacked"] is not None


def test_high_firewall_player_blocks_same_attacker(phone_os, comms, phone_db, sim_db):
    """After a PH-T2 firewall upgrade the SAME attacker is BLOCKED (no effect)."""
    _seed_player_comms(comms, n=4)
    # PH-T2 firewall upgrade installed → high effective firewall/security.
    phone_db.set_phone_fields(
        "user", security_level=1, firewall=1,
        installed_apps=["security_suite", "shadow_protocol"],
    )
    player = FakePlayerState()
    before = comms.count()
    svc = _service(phone_os, comms, phone_db, sim_db, player,
                   rng=_FixedRng(roll=1, rand=0.0))
    # Same attacker power as the breach test, but a roll of 1 + high defence.
    phone_os.hack_power = lambda cid: 5 if cid == "viktor" else 0  # type: ignore

    result = svc.hack("viktor")
    assert result["success"] is False
    assert result["blocked"] is True
    assert result["action"] == NPC_ACTION_OBSERVE
    assert result["margin"] < 0
    # No material effect: no heat, no standing, nothing read/leaked/planted.
    assert result["heat_delta"] == 0
    assert player.heat == 0
    assert result["rel_delta"] == 0.0
    assert result["read"] == []
    assert result["leaked"] is None
    assert result["planted"] is None
    # Only the persisted notification entry was added (no leak/plant comms).
    assert comms.count() - before == 1
    # last_hacked still stamped (a breach was attempted).
    assert phone_db.get_phone("user")["last_hacked"] is not None


# ── success is bounded: exactly ONE of leak-or-plant ────────────────────


def test_success_leak_is_bounded(phone_os, comms, phone_db, sim_db):
    """Coin-flip < 0.5 → exactly ONE leak entry, capped heat, recoverable rel hit."""
    _seed_player_comms(comms, n=4)
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    sim_db.get_or_create_relationship("user", "viktor", relationship_level=0.5)
    player = FakePlayerState()
    svc = _service(phone_os, comms, phone_db, sim_db, player,
                   rng=_FixedRng(roll=20, rand=0.0))  # rand 0.0 → leak
    phone_os.hack_power = lambda cid: 20 if cid == "viktor" else 0  # type: ignore

    result = svc.hack("viktor")
    assert result["action"] == NPC_ACTION_LEAK
    assert result["leaked"] is not None
    assert result["planted"] is None  # at most ONE side-effect
    # exactly one leaked system entry, by the attacker.
    leaked = [e for e in comms.recent(20) if e["metadata"].get("leaked")]
    assert len(leaked) == 1
    assert leaked[0]["metadata"]["by"] == "viktor"
    # the player's threads were read AND marked observed by the attacker.
    assert 0 < len(result["read"]) <= 3   # npc read_limit default = 3
    for entry in result["read"]:
        refetched = comms.query(thread_id="t-user", limit=20)
        match = [e for e in refetched if e["id"] == entry["id"]][0]
        assert "viktor" in match["observed_by"]
    # capped heat (success_heat default 3) + bounded recoverable standing hit.
    assert result["heat_delta"] == 3
    assert player.heat == 3
    rel = sim_db.get_relationship("user", "viktor")
    assert rel["relationship_level"] == pytest.approx(0.42, abs=0.001)
    assert rel["relationship_level"] > 0.0  # not wiped


def test_success_plant_is_bounded(phone_os, comms, phone_db, sim_db):
    """Coin-flip >= 0.5 → exactly ONE planted inbox message (metadata.planted)."""
    _seed_player_comms(comms, n=4)
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    player = FakePlayerState()
    svc = _service(phone_os, comms, phone_db, sim_db, player,
                   rng=_FixedRng(roll=20, rand=0.9))  # rand 0.9 → plant
    phone_os.hack_power = lambda cid: 20 if cid == "viktor" else 0  # type: ignore

    result = svc.hack("viktor")
    assert result["action"] == NPC_ACTION_PLANT
    assert result["planted"] is not None
    assert result["leaked"] is None  # at most ONE side-effect
    planted = [e for e in comms.recent(20) if e["metadata"].get("planted")]
    assert len(planted) == 1
    assert planted[0]["metadata"]["by"] == "viktor"
    assert planted[0]["sender_id"] == "viktor"
    assert "user" in planted[0]["recipient_ids"]


# ── surfacing: event + persisted notification ───────────────────────────


def test_breach_emits_event_and_persists_notification(phone_os, comms, phone_db, sim_db):
    """A successful breach emits phone_hacked + persists a notification entry."""
    _seed_player_comms(comms, n=4)
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    emit = StubEmitter()
    svc = _service(phone_os, comms, phone_db, sim_db, emit=emit,
                   rng=_FixedRng(roll=20, rand=0.0))
    phone_os.hack_power = lambda cid: 20 if cid == "viktor" else 0  # type: ignore

    result = svc.hack("viktor")
    assert result["success"] is True
    assert "phone_hacked" in emit.names()
    # message_intercepted also emitted because threads were read.
    assert "message_intercepted" in emit.names()
    # a persisted notification record the UI can read.
    notifs = [
        e for e in comms.recent(20)
        if e["metadata"].get("notification") == "phone_hacked"
    ]
    assert len(notifs) == 1
    assert notifs[0]["metadata"]["attacker"] == "viktor"
    assert notifs[0]["metadata"]["blocked"] is False


def test_blocked_emits_event_with_blocked_flag(phone_os, comms, phone_db, sim_db):
    """A blocked breach still emits phone_hacked with blocked=True."""
    phone_db.set_phone_fields(
        "user", security_level=1, firewall=1, installed_apps=["security_suite"],
    )
    emit = StubEmitter()
    svc = _service(phone_os, comms, phone_db, sim_db, emit=emit,
                   rng=_FixedRng(roll=1, rand=0.0))
    phone_os.hack_power = lambda cid: 0  # type: ignore

    result = svc.hack("viktor")
    assert result["blocked"] is True
    hacked = [p for e, p in emit.events if e == "phone_hacked"]
    assert len(hacked) == 1
    assert hacked[0]["blocked"] is True
    assert "message_intercepted" not in emit.names()  # nothing read


# ── trigger gate: hostility + probability ───────────────────────────────


def test_hostile_by_low_standing(sim_db):
    """An NPC with low (npc, user) standing is classified hostile."""
    sim_db.get_or_create_relationship("viktor", "user", relationship_level=0.1)
    assert is_hostile_to_player("viktor", db=sim_db) is True


def test_friendly_is_not_hostile(sim_db):
    """An NPC with high standing toward the player is NOT hostile."""
    sim_db.get_or_create_relationship("aria", "user", relationship_level=0.9)
    assert is_hostile_to_player("aria", db=sim_db) is False


def test_trigger_fires_for_hostile_at_prob_one(monkeypatch, phone_os, comms, phone_db, sim_db):
    """prob=1.0 + hostile attacker → the trigger fires a hack."""
    _seed_player_comms(comms, n=2)
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    sim_db.get_or_create_relationship("viktor", "user", relationship_level=0.1)
    phone_os.hack_power = lambda cid: 20 if cid == "viktor" else 0  # type: ignore

    import content.scenes.phone.phone_hack as ph
    monkeypatch.setattr(ph, "_npc_cfg", lambda key: {
        "enabled": True, "trigger_probability": 1.0,
        "hostility_standing_threshold": 0.3,
        "hostile_factions": [], "faction_hostile_threshold": -40,
    }.get(key, ph._NPC_DEFAULTS.get(key)))

    svc = _service(phone_os, comms, phone_db, sim_db,
                   rng=_FixedRng(roll=20, rand=0.0))
    result = maybe_npc_hack_player("viktor", db=sim_db, rng=_FixedRng(rand=0.0),
                                   service=svc)
    assert result is not None
    assert result["attacker"] == "viktor"


def test_trigger_never_fires_at_prob_zero(monkeypatch, sim_db):
    """prob=0.0 → the trigger never fires even for a hostile attacker."""
    sim_db.get_or_create_relationship("viktor", "user", relationship_level=0.1)
    import content.scenes.phone.phone_hack as ph
    monkeypatch.setattr(ph, "_npc_cfg", lambda key: {
        "enabled": True, "trigger_probability": 0.0,
        "hostility_standing_threshold": 0.3,
        "hostile_factions": [], "faction_hostile_threshold": -40,
    }.get(key, ph._NPC_DEFAULTS.get(key)))
    result = maybe_npc_hack_player("viktor", db=sim_db, rng=_FixedRng(rand=0.0))
    assert result is None


def test_trigger_never_fires_for_friendly(monkeypatch, sim_db):
    """A friendly NPC never triggers a hack, even at prob=1.0."""
    sim_db.get_or_create_relationship("aria", "user", relationship_level=0.9)
    import content.scenes.phone.phone_hack as ph
    monkeypatch.setattr(ph, "_npc_cfg", lambda key: {
        "enabled": True, "trigger_probability": 1.0,
        "hostility_standing_threshold": 0.3,
        "hostile_factions": [], "faction_hostile_threshold": -40,
    }.get(key, ph._NPC_DEFAULTS.get(key)))
    result = maybe_npc_hack_player("aria", db=sim_db, rng=_FixedRng(rand=0.0))
    assert result is None


# ── skill surface ───────────────────────────────────────────────────────


def test_npc_hack_player_skill_requires_attacker():
    """The skill returns a clean error when no attacker is given (no crash)."""
    from content.scenes.phone.phone_hack import npc_hack_player
    result = npc_hack_player("")
    assert result["success"] is False
    assert "attacker_id" in result["message"]
