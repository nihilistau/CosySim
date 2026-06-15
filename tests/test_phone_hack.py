"""Unit tests for player→NPC phone hacking (PH-T3).

Covers :class:`content.scenes.phone.phone_hack.HackPhoneService` and the
``hack_phone`` skill:

* The check: high player hack_power vs low NPC security → success; low hack_power
  vs high security → failure (a fixed-roll RNG makes the outcome deterministic).
* Success + intercept: returns a bounded slice of the NPC's comms AND marks each
  returned entry observed by ``user``.
* Success + plant: writes exactly ONE planted comms_log entry (metadata.planted)
  and persists it to the NPC's phone thread.
* Success + steal: grants a bounded credit reward inside the configured band.
* Failure: adds bounded heat + a bounded/recoverable standing hit toward the
  player AND stamps last_hacked.
* Graceful: an NPC with no comms yields a clean "nothing to read" result.

All tests use isolated temp DBs (PhoneDB / GlobalCommsLog / Database) + a mock
player state at the boundary, so no real data or live services are touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pytest

from content.scenes.phone.phone_db import PhoneDB
from content.simulation.database.db import Database
from engine.world.comms_log import GlobalCommsLog
from engine.world.phone_os import PhoneOS
from content.scenes.phone.phone_hack import (
    HackPhoneService,
    ACTION_INTERCEPT,
    ACTION_PLANT,
    ACTION_STEAL,
)


# ── mock player state ───────────────────────────────────────────────────


class FakePlayerState:
    """Minimal PlayerState stand-in capturing heat/skill/credit mutations."""

    def __init__(self, hacking: int = 0, credits: int = 0) -> None:
        self.heat = 0
        self.credits = credits
        self._skills = {"hacking": hacking}
        self.heat_calls: List[int] = []
        self.credit_calls: List[int] = []

    def get_skill(self, skill: str) -> int:
        return int(self._skills.get(skill, 0))

    def add_heat(self, amount: int, reason: str = "") -> int:
        self.heat += int(amount)
        self.heat_calls.append(int(amount))
        return self.heat

    def earn_credits(self, amount: int, reason: str = "") -> int:
        self.credits += int(amount)
        self.credit_calls.append(int(amount))
        return self.credits


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def phone_db(tmp_path) -> PhoneDB:
    """Isolated PhoneDB on a temp file."""
    return PhoneDB(tmp_path / "phone_hack_phone.db")


@pytest.fixture()
def phone_os(phone_db: PhoneDB) -> PhoneOS:
    """PhoneOS wired to the temp PhoneDB."""
    return PhoneOS(db=phone_db)


@pytest.fixture()
def comms(tmp_path) -> GlobalCommsLog:
    """Isolated comms log on a temp file."""
    return GlobalCommsLog(path=tmp_path / "phone_hack_comms.db")


@pytest.fixture()
def sim_db(tmp_path) -> Database:
    """Isolated simulation Database on a temp file."""
    return Database(db_path=str(tmp_path / "phone_hack_sim.db"))


def _service(
    phone_os: PhoneOS,
    comms: GlobalCommsLog,
    phone_db: PhoneDB,
    sim_db: Optional[Database] = None,
    player: Optional[FakePlayerState] = None,
    roll: int = 10,
) -> HackPhoneService:
    """Build a HackPhoneService with a fixed-roll RNG for determinism."""

    class _FixedRng(random.Random):
        def randint(self, a: int, b: int) -> int:  # type: ignore[override]
            return roll

    return HackPhoneService(
        phone_os=phone_os,
        comms=comms,
        phone_db=phone_db,
        db=sim_db,
        player_state=player or FakePlayerState(),
        rng=_FixedRng(),
    )


def _seed_comms(comms: GlobalCommsLog, target: str, n: int = 8) -> List[int]:
    """Seed *n* comms entries involving *target*; return their ids."""
    ids = []
    for i in range(n):
        ids.append(
            comms.log(
                "phone_dm", target, ["lola"], f"msg {i}",
                thread_id=f"t-{target}", kind="message",
            )
        )
    return ids


# ── the check ────────────────────────────────────────────────────────────


def test_high_power_low_security_succeeds(phone_os, comms, phone_db):
    """High player hack_power vs a low-security NPC → success."""
    phone_db.set_phone_fields("user", installed_apps=["data_mine", "ice_breaker_v1"])
    phone_db.set_phone_fields("aria", security_level=1, firewall=1)
    # Give the player a big offensive edge via many offensive apps.
    phone_db.set_phone_fields(
        "user", installed_apps=["data_mine", "ice_breaker_v1"],
    )
    svc = _service(phone_os, comms, phone_db, roll=20)
    # Force a large hack_power independent of inventory.
    phone_os.hack_power = lambda cid: 30 if cid == "user" else 0  # type: ignore
    result = svc.hack("aria", action=ACTION_INTERCEPT)
    assert result["success"] is True
    assert result["attack"] >= result["defence"]
    assert result["margin"] >= 0


def test_low_power_high_security_fails(phone_os, comms, phone_db, sim_db):
    """Low player hack_power vs a high-security NPC → failure."""
    phone_db.set_phone_fields("viktor", security_level=5, firewall=5)
    svc = _service(phone_os, comms, phone_db, sim_db=sim_db, roll=1)
    phone_os.hack_power = lambda cid: 0  # type: ignore
    result = svc.hack("viktor", action=ACTION_INTERCEPT)
    assert result["success"] is False
    assert result["margin"] < 0


# ── success + intercept ────────────────────────────────────────────────────


def test_success_intercept_marks_observed_and_bounded(phone_os, comms, phone_db):
    """Intercept returns a bounded slice and marks each entry observed by user."""
    ids = _seed_comms(comms, "aria", n=8)
    phone_db.set_phone_fields("aria", security_level=1, firewall=1)
    player = FakePlayerState()
    svc = _service(phone_os, comms, phone_db, player=player, roll=20)
    phone_os.hack_power = lambda cid: 30 if cid == "user" else 0  # type: ignore

    result = svc.hack("aria", action=ACTION_INTERCEPT)
    assert result["success"] is True
    # read_limit default = 5 → bounded
    assert 0 < len(result["read"]) <= 5
    # every returned entry is now observed by 'user'
    for entry in result["read"]:
        refetched = comms.query(thread_id="t-aria", limit=20)
        match = [e for e in refetched if e["id"] == entry["id"]][0]
        assert "user" in match["observed_by"]
    # success heat is small/quiet
    assert result["heat_delta"] == 2
    assert len(ids) == 8  # sanity: we seeded more than the limit


def test_success_intercept_no_comms_is_graceful(phone_os, comms, phone_db):
    """An NPC with no comms yields a clean empty 'nothing to read' result."""
    phone_db.set_phone_fields("ghost", security_level=1, firewall=1)
    svc = _service(phone_os, comms, phone_db, roll=20)
    phone_os.hack_power = lambda cid: 30 if cid == "user" else 0  # type: ignore
    result = svc.hack("ghost", action=ACTION_INTERCEPT)
    assert result["success"] is True
    assert result["read"] == []
    assert "nothing to read" in result["message"]


# ── success + plant ────────────────────────────────────────────────────────


def test_success_plant_writes_exactly_one_entry(phone_os, comms, phone_db):
    """Plant writes exactly ONE planted comms_log entry (metadata.planted)."""
    phone_db.set_phone_fields("aria", security_level=1, firewall=1)
    svc = _service(phone_os, comms, phone_db, roll=20)
    phone_os.hack_power = lambda cid: 30 if cid == "user" else 0  # type: ignore

    before = comms.count()
    result = svc.hack("aria", action=ACTION_PLANT)
    after = comms.count()

    assert result["success"] is True
    assert result["planted"] is not None
    assert after - before == 1  # exactly one comms entry written
    planted = [e for e in comms.recent(10) if e["metadata"].get("planted")]
    assert len(planted) == 1
    assert planted[0]["metadata"]["by"] == "user"
    assert planted[0]["sender_id"] == "user"


# ── success + steal ────────────────────────────────────────────────────────


def test_success_steal_grants_bounded_reward(phone_os, comms, phone_db):
    """Steal grants a credit reward inside the configured [min, max] band."""
    phone_db.set_phone_fields("aria", security_level=1, firewall=1)
    player = FakePlayerState(credits=0)
    svc = _service(phone_os, comms, phone_db, player=player, roll=20)
    phone_os.hack_power = lambda cid: 30 if cid == "user" else 0  # type: ignore

    result = svc.hack("aria", action=ACTION_STEAL)
    assert result["success"] is True
    granted = result["stolen"]["credits"]
    assert 40 <= granted <= 120  # config band defaults
    assert player.credits == granted


# ── failure consequences ───────────────────────────────────────────────────


def test_failure_adds_heat_rel_hit_and_last_hacked(phone_os, comms, phone_db, sim_db):
    """Failure → bounded heat + a recoverable standing hit + last_hacked stamp."""
    phone_db.set_phone_fields("viktor", security_level=5, firewall=5)
    # Seed an existing positive standing so we can prove a recoverable drop.
    sim_db.get_or_create_relationship("viktor", "user", relationship_level=0.8)
    player = FakePlayerState()
    svc = _service(phone_os, comms, phone_db, sim_db=sim_db, player=player, roll=1)
    phone_os.hack_power = lambda cid: 0  # type: ignore

    result = svc.hack("viktor", action=ACTION_INTERCEPT)
    assert result["success"] is False
    assert result["heat_delta"] == 8       # fail_heat default
    assert player.heat == 8
    assert result["rel_delta"] < 0          # standing dropped
    # recoverable: the drop is bounded (small), not a wipe
    rel = sim_db.get_relationship("viktor", "user")
    assert rel["relationship_level"] == pytest.approx(0.72, abs=0.001)
    assert rel["relationship_level"] > 0.0  # not zeroed
    # last_hacked stamped on failure too
    assert phone_db.get_phone("viktor")["last_hacked"] is not None


def test_success_stamps_last_hacked(phone_os, comms, phone_db):
    """A successful hack also stamps last_hacked on the target."""
    phone_db.set_phone_fields("aria", security_level=1, firewall=1)
    svc = _service(phone_os, comms, phone_db, roll=20)
    phone_os.hack_power = lambda cid: 30 if cid == "user" else 0  # type: ignore
    assert phone_db.get_phone("aria")["last_hacked"] is None
    svc.hack("aria", action=ACTION_INTERCEPT)
    assert phone_db.get_phone("aria")["last_hacked"] is not None


# ── skill surface ──────────────────────────────────────────────────────────


def test_hack_phone_skill_requires_target():
    """The skill returns a clean error when no target is given (no crash)."""
    from content.scenes.phone.phone_hack import hack_phone
    result = hack_phone("", action=ACTION_INTERCEPT)
    assert result["success"] is False
    assert "target_id" in result["message"]
