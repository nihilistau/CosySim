"""Unit tests for FACTION-driven NPC→PLAYER phone hacking (L2).

These extend the PH-T4 reverse-hack coverage (see
``tests/test_npc_hack_player.py``) with the v1.62.1 L2 loop: faction hostility
— not just per-NPC standing — now makes an NPC eligible to hack the player.

Covered:

* **Derived faction path** — an NPC whose faction the player is hostile toward
  (player faction standing <= ``faction_hostile_threshold``) is hostile, even
  with no per-NPC standing and an empty ``hostile_factions`` list.
* **Neutral / allied faction** — an NPC in a faction the player is on good terms
  with is NOT hostile (when per-NPC standing is fine).
* **Explicit override** — listing the attacker's faction in ``hostile_factions``
  forces hostility regardless of the player's standing with it.
* **Gate still holds** — the faction path still respects the
  ``trigger_probability`` gate (prob=0 never fires) and the firewall defence
  (a high-firewall player BLOCKS a faction-triggered hack).

The faction-standing accessor (``PlayerState.faction_standings``) and the
character→faction map are mocked / driven at the boundary; PhoneDB /
GlobalCommsLog / Database use isolated temp files. No live services.

Version: v1.62.1 [2026-06-15]
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pytest

from content.scenes.phone.phone_db import PhoneDB
from content.simulation.database.db import Database
from engine.world.comms_log import GlobalCommsLog
from engine.world.phone_os import PhoneOS
import content.scenes.phone.phone_hack as ph
from content.scenes.phone.phone_hack import (
    NpcHackPlayerService,
    is_hostile_to_player,
    maybe_npc_hack_player,
)


# ── mock player state ───────────────────────────────────────────────────


class FakePlayerState:
    """Minimal PlayerState stand-in exposing ``faction_standings`` + heat."""

    def __init__(self, factions: Optional[Dict[str, int]] = None) -> None:
        self.heat = 0
        self.faction_standings: Dict[str, int] = dict(factions or {})

    def add_heat(self, amount: int, reason: str = "") -> int:
        self.heat += int(amount)
        return self.heat

    def get_skill(self, skill: str) -> int:  # unused by the reverse hack
        return 0


class _FixedRng(random.Random):
    """Deterministic RNG: fixed die roll + fixed ``random()`` value."""

    def __init__(self, roll: int = 10, rand: float = 0.0) -> None:
        super().__init__()
        self._roll = roll
        self._rand = rand

    def randint(self, a: int, b: int) -> int:  # type: ignore[override]
        return self._roll

    def random(self) -> float:  # type: ignore[override]
        return self._rand


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def phone_db(tmp_path) -> PhoneDB:
    """Isolated PhoneDB on a temp file."""
    return PhoneDB(tmp_path / "faction_hack_phone.db")


@pytest.fixture()
def phone_os(phone_db: PhoneDB) -> PhoneOS:
    """PhoneOS wired to the temp PhoneDB."""
    return PhoneOS(db=phone_db)


@pytest.fixture()
def comms(tmp_path) -> GlobalCommsLog:
    """Isolated comms log on a temp file."""
    return GlobalCommsLog(path=tmp_path / "faction_hack_comms.db")


@pytest.fixture()
def sim_db(tmp_path) -> Database:
    """Isolated simulation Database on a temp file (no seeded relationships)."""
    return Database(db_path=str(tmp_path / "faction_hack_sim.db"))


def _patch_npc_cfg(monkeypatch, **overrides: Any) -> None:
    """Patch ``phone_hack._npc_cfg`` with a fixed config view for the gate.

    Defaults match config, then apply ``overrides``. This isolates the test from
    the on-disk YAML so the faction thresholds and probability are deterministic.
    """
    cfg = {
        "enabled": True,
        "trigger_probability": 1.0,
        "hostility_standing_threshold": 0.3,
        "hostile_factions": [],
        "faction_hostile_threshold": -40,
    }
    cfg.update(overrides)
    monkeypatch.setattr(
        ph, "_npc_cfg", lambda key: cfg.get(key, ph._NPC_DEFAULTS.get(key))
    )


def _seed_player_comms(comms: GlobalCommsLog, n: int = 2) -> None:
    """Seed *n* comms entries involving the player so a breach has data to read."""
    for i in range(n):
        comms.log(
            "phone_dm", "user", ["netrunner"], f"player secret {i}",
            thread_id="t-user", kind="message",
        )


# NB: in ``faction_context._FACTION_CHARACTERS`` the id "netrunner" maps to the
# faction "ghost_net"; the player's faction_standings key is "Ghost_Net" — the
# lookup is intentionally case-insensitive, which these tests exercise.
_GHOST_NET_NPC = "netrunner"
_OMNICORP_NPC = "corporate_exec"
_INDEPENDENT_NPC = "viktor"  # not in any faction map


# ── derived faction path ────────────────────────────────────────────────


def test_hostile_via_attackers_faction(monkeypatch, sim_db):
    """An NPC whose faction the player is hostile toward is hostile (faction path).

    No per-NPC standing is seeded and ``hostile_factions`` is empty, so ONLY the
    derived faction path can fire.
    """
    _patch_npc_cfg(monkeypatch)  # empty hostile_factions, threshold -40
    player = FakePlayerState({"Ghost_Net": -80})  # player is an enemy of Ghost_Net
    assert is_hostile_to_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player
    ) is True


def test_neutral_faction_is_not_hostile(monkeypatch, sim_db):
    """An NPC in a faction the player is on good terms with is NOT hostile.

    Per-NPC standing is unset (DB empty → fine) and the player's standing with
    the NPC's faction is well above threshold.
    """
    _patch_npc_cfg(monkeypatch)
    player = FakePlayerState({"Ghost_Net": 30})  # neutral/positive standing
    assert is_hostile_to_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player
    ) is False


def test_allied_other_faction_npc_is_not_hostile(monkeypatch, sim_db):
    """A hostile standing with ONE faction does not make OTHER factions' NPCs hostile."""
    _patch_npc_cfg(monkeypatch)
    # Player hates Ghost_Net but is allied with OmniCorp.
    player = FakePlayerState({"Ghost_Net": -80, "OmniCorp": 60})
    assert is_hostile_to_player(
        _OMNICORP_NPC, db=sim_db, player_state=player
    ) is False
    # ...while the Ghost_Net member IS hostile.
    assert is_hostile_to_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player
    ) is True


def test_independent_npc_with_no_standing_is_not_hostile(monkeypatch, sim_db):
    """An NPC in no faction, with fine per-NPC standing, is NOT hostile."""
    _patch_npc_cfg(monkeypatch)
    player = FakePlayerState({"Ghost_Net": -80})
    assert is_hostile_to_player(
        _INDEPENDENT_NPC, db=sim_db, player_state=player
    ) is False


# ── explicit override ───────────────────────────────────────────────────


def test_explicit_hostile_factions_override_forces_hostility(monkeypatch, sim_db):
    """Listing the attacker's faction in hostile_factions forces hostility.

    The player's standing with Ghost_Net is POSITIVE, so only the explicit
    override can make this NPC hostile.
    """
    _patch_npc_cfg(monkeypatch, hostile_factions=["ghost_net"])
    player = FakePlayerState({"Ghost_Net": 75})  # would NOT be hostile by standing
    assert is_hostile_to_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player
    ) is True


def test_override_does_not_affect_other_factions(monkeypatch, sim_db):
    """An override list only forces the listed faction's members hostile."""
    _patch_npc_cfg(monkeypatch, hostile_factions=["ghost_net"])
    player = FakePlayerState({"OmniCorp": 0})
    assert is_hostile_to_player(
        _OMNICORP_NPC, db=sim_db, player_state=player
    ) is False


# ── per-NPC standing path still works ───────────────────────────────────


def test_per_npc_standing_path_still_triggers(monkeypatch, sim_db):
    """The original per-NPC standing path still fires (faction-independent)."""
    _patch_npc_cfg(monkeypatch)
    sim_db.get_or_create_relationship(_INDEPENDENT_NPC, "user", relationship_level=0.1)
    # Independent NPC, no faction standing — only the per-NPC path can fire.
    player = FakePlayerState({})
    assert is_hostile_to_player(
        _INDEPENDENT_NPC, db=sim_db, player_state=player
    ) is True


# ── gate + firewall still hold on the faction path ──────────────────────


def test_faction_trigger_respects_probability_gate(monkeypatch, sim_db):
    """prob=0 → a faction-hostile NPC never rolls a hack."""
    _patch_npc_cfg(monkeypatch, trigger_probability=0.0)
    player = FakePlayerState({"Ghost_Net": -80})
    result = maybe_npc_hack_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player, rng=_FixedRng(rand=0.0),
    )
    assert result is None


def test_faction_triggered_hack_is_blocked_by_high_firewall(
    monkeypatch, phone_os, comms, phone_db, sim_db
):
    """A faction-triggered hack against a HIGH-firewall player is BLOCKED.

    The faction path makes the NPC eligible; the player's firewall still decides
    the outcome — install PH-T2 upgrades and the same attacker is blocked.
    """
    _patch_npc_cfg(monkeypatch, trigger_probability=1.0)
    _seed_player_comms(comms, n=2)
    # PH-T2 firewall upgrades installed → high effective firewall/security.
    phone_db.set_phone_fields(
        "user", security_level=1, firewall=1,
        installed_apps=["security_suite", "shadow_protocol"],
    )
    player = FakePlayerState({"Ghost_Net": -80})
    # Weak attacker + low roll vs the player's high defence.
    phone_os.hack_power = lambda cid: 5 if cid == _GHOST_NET_NPC else 0  # type: ignore
    svc = NpcHackPlayerService(
        phone_os=phone_os, comms=comms, phone_db=phone_db, db=sim_db,
        player_state=player, rng=_FixedRng(roll=1, rand=0.0),
    )

    result = maybe_npc_hack_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player,
        rng=_FixedRng(rand=0.0), service=svc,
    )
    # The faction path fired the attempt...
    assert result is not None
    assert result["attacker"] == _GHOST_NET_NPC
    # ...but the firewall blocked it: no material effect.
    assert result["blocked"] is True
    assert result["success"] is False
    assert result["heat_delta"] == 0
    assert player.heat == 0
    assert result["leaked"] is None
    assert result["planted"] is None


def test_faction_triggered_hack_breaches_low_firewall(
    monkeypatch, phone_os, comms, phone_db, sim_db
):
    """A faction-triggered hack against a LOW-firewall player breaches (recoverable)."""
    _patch_npc_cfg(monkeypatch, trigger_probability=1.0)
    _seed_player_comms(comms, n=2)
    phone_db.set_phone_fields("user", security_level=1, firewall=1)
    player = FakePlayerState({"Ghost_Net": -80})
    phone_os.hack_power = lambda cid: 20 if cid == _GHOST_NET_NPC else 0  # type: ignore
    svc = NpcHackPlayerService(
        phone_os=phone_os, comms=comms, phone_db=phone_db, db=sim_db,
        player_state=player, rng=_FixedRng(roll=20, rand=0.0),
    )

    result = maybe_npc_hack_player(
        _GHOST_NET_NPC, db=sim_db, player_state=player,
        rng=_FixedRng(rand=0.0), service=svc,
    )
    assert result is not None
    assert result["success"] is True
    assert result["blocked"] is False
    # last_hacked stamped on the player.
    assert phone_db.get_phone("user")["last_hacked"] is not None
