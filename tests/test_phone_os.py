"""Unit tests for full NPC phone records + PhoneOS derived security (PH-T1).

Covers:
* PhoneDB ``npc_phone`` record CRUD — default creation, field updates,
  install/remove app, last_hacked stamping, and ``list_phones``.
* Migration: an existing CB-T3 stub table (char_id/enabled/created_at) is
  upgraded in place without dropping data.
* :class:`engine.world.phone_os.PhoneOS` derived stats — effective security /
  firewall / hack_power / app_slots change when software is "installed", the
  player path adds equipped-cyberdeck bonuses while NPCs do not, seeding
  creates varied records, and reads fall back safely when the DB is broken.

All tests use a temp DB path (PhoneDB(db_path=...)) so no real data is touched
and no live services are needed.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from content.scenes.phone.phone_db import PhoneDB
from engine.world.phone_os import PhoneOS, PLAYER_ID


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path) -> PhoneDB:
    """Return a PhoneDB backed by an isolated temp database file."""
    return PhoneDB(tmp_path / "phone_os_test.db")


@pytest.fixture()
def phone_os(db: PhoneDB) -> PhoneOS:
    """Return a PhoneOS wired to the isolated temp PhoneDB."""
    return PhoneOS(db=db)


# ── PhoneDB record CRUD ─────────────────────────────────────────────────


def test_get_phone_creates_default(db: PhoneDB) -> None:
    rec = db.get_phone("aria")
    assert rec["char_id"] == "aria"
    assert rec["enabled"] is True
    assert rec["installed_apps"] == []
    assert rec["security_level"] == 1
    assert rec["firewall"] == 1
    assert rec["last_hacked"] is None
    assert rec["created_at"]  # stamped


def test_get_phone_is_idempotent(db: PhoneDB) -> None:
    first = db.get_phone("viktor")
    second = db.get_phone("viktor")
    assert first["created_at"] == second["created_at"]
    assert len(db.list_phones()) == 1


def test_set_phone_fields(db: PhoneDB) -> None:
    rec = db.set_phone_fields("lola", security_level=5, os_version="NeonOS 2.0")
    assert rec["security_level"] == 5
    assert rec["os_version"] == "NeonOS 2.0"
    # unknown fields ignored, valid ones persisted
    again = db.set_phone_fields("lola", bogus="x", firewall=3)
    assert again["firewall"] == 3
    assert "bogus" not in again


def test_install_and_remove_app(db: PhoneDB) -> None:
    db.add_installed_app("mira", "ice_breaker_v1")
    db.add_installed_app("mira", "ice_breaker_v1")  # dedup
    db.add_installed_app("mira", "shadow_protocol")
    rec = db.get_phone("mira")
    assert rec["installed_apps"] == ["ice_breaker_v1", "shadow_protocol"]

    db.remove_installed_app("mira", "ice_breaker_v1")
    db.remove_installed_app("mira", "not_installed")  # no-op
    assert db.get_phone("mira")["installed_apps"] == ["shadow_protocol"]


def test_set_last_hacked(db: PhoneDB) -> None:
    assert db.get_phone("frankie")["last_hacked"] is None
    db.set_last_hacked("frankie", "2026-06-15T00:00:00+00:00")
    assert db.get_phone("frankie")["last_hacked"] == "2026-06-15T00:00:00+00:00"
    # default timestamp when omitted
    db.set_last_hacked("frankie")
    assert db.get_phone("frankie")["last_hacked"] != "2026-06-15T00:00:00+00:00"


def test_list_phones(db: PhoneDB) -> None:
    db.get_phone("aria")
    db.get_phone("viktor")
    db.set_phone_fields(PLAYER_ID, security_level=2)
    ids = {p["char_id"] for p in db.list_phones()}
    assert ids == {"aria", "viktor", PLAYER_ID}


def test_migration_preserves_stub_rows(tmp_path) -> None:
    """A CB-T3-shaped stub table is upgraded without dropping data."""
    import sqlite3

    db_path = tmp_path / "stub.db"
    # Simulate the pre-PH-T1 stub table with one marked NPC.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE npc_phone (char_id TEXT PRIMARY KEY, "
        "enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO npc_phone(char_id, enabled, created_at) VALUES (?,?,?)",
        ("legacy_npc", 1, "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    # PhoneDB init must migrate columns in place, keeping the legacy row.
    db = PhoneDB(db_path)
    rec = db.get_phone("legacy_npc")
    assert rec["char_id"] == "legacy_npc"
    assert rec["created_at"] == "2026-01-01T00:00:00+00:00"  # not dropped
    assert rec["security_level"] == 1  # new column defaulted
    assert rec["installed_apps"] == []


# ── PhoneOS derived stats ───────────────────────────────────────────────


def test_effective_security_rises_with_software(phone_os: PhoneOS, db: PhoneDB) -> None:
    db.set_phone_fields("aria", security_level=2)
    base = phone_os.effective_security("aria")
    db.add_installed_app("aria", "shadow_protocol")  # +2 security
    assert phone_os.effective_security("aria") == base + 2


def test_effective_firewall_rises_with_software(phone_os: PhoneOS, db: PhoneDB) -> None:
    base = phone_os.effective_firewall("viktor")
    db.add_installed_app("viktor", "tracer_kill")  # +2 firewall
    assert phone_os.effective_firewall("viktor") == base + 2


def test_hack_power_rises_with_offensive_software(phone_os: PhoneOS, db: PhoneDB) -> None:
    assert phone_os.hack_power("mira") == 0
    db.add_installed_app("mira", "ice_breaker_v1")  # +1 hack_power
    db.add_installed_app("mira", "data_mine")       # +1 hack_power
    assert phone_os.hack_power("mira") == 2


def test_app_slots_scale_with_security(phone_os: PhoneOS, db: PhoneDB) -> None:
    db.set_phone_fields("aria", security_level=1)
    low = phone_os.app_slots("aria")
    db.set_phone_fields("aria", security_level=4)
    assert phone_os.app_slots("aria") > low


def test_player_path_adds_equipment_bonus(phone_os: PhoneOS, db: PhoneDB, monkeypatch) -> None:
    """Player firewall/hack_power gain from the equipped cyberdeck; NPCs don't."""

    class _FakeInv:
        def get_cyberdeck_stats(self) -> Dict[str, int]:
            return {"crack_speed": 6, "trace_resist": 6}

        def get_equipment_bonuses(self) -> Dict[str, int]:
            return {"hacking": 1}

    monkeypatch.setattr(
        "engine.world.inventory.get_inventory", lambda: _FakeInv()
    )

    npc_fw = phone_os.effective_firewall("aria")
    player_fw = phone_os.effective_firewall(PLAYER_ID)
    # Player firewall includes +6 trace_resist; NPC at the same base does not.
    assert player_fw == npc_fw + 6
    # Player hack_power = crack_speed(6) + hacking(1) = 7; NPC gets 0.
    assert phone_os.hack_power(PLAYER_ID) == 7
    assert phone_os.hack_power("aria") == 0


def test_seed_npc_phones_varied(phone_os: PhoneOS, db: PhoneDB) -> None:
    out = phone_os.seed_npc_phones(["lola", "viktor", "aria", "frankie", "mira"])
    assert set(out) == {"lola", "viktor", "aria", "frankie", "mira"}
    secs = {cid: rec["security_level"] for cid, rec in out.items()}
    # All seeded with a valid base security and the spread produces variety.
    assert all(s >= 1 for s in secs.values())
    assert len(set(secs.values())) > 1


def test_seed_is_idempotent(phone_os: PhoneOS, db: PhoneDB) -> None:
    phone_os.seed_npc_phones(["lola"])
    db.set_phone_fields("lola", security_level=9)  # player-modified afterwards
    phone_os.seed_npc_phones(["lola"])  # must NOT clobber
    assert db.get_phone("lola")["security_level"] == 9


def test_defensive_fallback_when_db_unavailable() -> None:
    """A broken DB yields safe defaults, never an exception."""

    class _BrokenDB:
        def get_phone(self, *a, **k):
            raise RuntimeError("db down")

        def list_phones(self):
            raise RuntimeError("db down")

        def set_phone_fields(self, *a, **k):
            raise RuntimeError("db down")

    pos = PhoneOS(db=_BrokenDB())
    # None of these raise; all return sane defaults.
    assert isinstance(pos.effective_security("ghost"), int)
    assert pos.effective_firewall("ghost") >= 0
    assert pos.hack_power("ghost") == 0
    assert pos.app_slots("ghost") >= 1
    rec = pos.get_phone("ghost")
    assert rec["char_id"] == "ghost"
