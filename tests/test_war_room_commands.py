"""Unit tests for the War Room faction commands (v1.63.0 C-T4).

Exercises the command dispatch + per-command handlers on
:class:`WarRoomScene` against in-memory fakes for the engine managers
(territory, crew, faction-AI, faction-politics, player state). Covers:

* dispatch: unknown command, no-allegiance guard, never-raises shell;
* contest → shifts control toward the player's faction (delta in range);
* assign_op → preview + start_operation, gated message when crew too small;
* recruit → honours the CrewManager gate (success + clean failure);
* build_hq / upgrade_room → establish + build/upgrade via TerritoryManager;
* diplomacy → flips the rival's relation to war/ally in the assembled state;
* op_preview → success-chance preview shape, invalid op_type rejected.

The handlers act for ``faction = get_player_state().allegiance``; the
state assembler's rival relation reads PlayerState standings, so a declared
war is observable in ``state['rivals'][*]['relation']``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

import content.scenes.war_room.war_room_scene as wr
from engine.world.territory import (
    CONTROL_SHIFT_RANGE,
    DISTRICT_NAMES,
    HQ_ROOM_TYPES,
)


# ──── Fakes ────────────────────────────────────────────────────


class _FakeHQ:
    def __init__(self, crew_id: str, district: str) -> None:
        self.crew_id = crew_id
        self.district = district
        self.rooms: Dict[str, int] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {"crew_id": self.crew_id, "district": self.district,
                "rooms": dict(self.rooms)}


class _FakeTerritory:
    """Stand-in for TerritoryManager that actually mutates control."""

    def __init__(self) -> None:
        # district -> faction -> pct
        self._control: Dict[str, Dict[str, float]] = {
            d: {"OmniCorp": 30.0, "Ghost_Net": 20.0, "NeoTech": 50.0}
            for d in DISTRICT_NAMES
        }
        self._hqs: Dict[str, _FakeHQ] = {}
        self.shift_calls: List[Dict[str, Any]] = []

    def shift_control(self, district, faction, delta, reason="", source_faction=None):
        self.shift_calls.append({
            "district": district, "faction": faction, "delta": delta,
            "reason": reason, "source_faction": source_faction,
        })
        ctrl = self._control.setdefault(district, {})
        ctrl[faction] = ctrl.get(faction, 0.0) + delta

        class _Ev:
            pass
        ev = _Ev()
        ev.delta = delta
        return ev

    def get_district_control(self, district):
        return dict(self._control.get(district, {}))

    def get_all_control(self):
        return {d: dict(c) for d, c in self._control.items()}

    def get_faction_total_control(self, faction):
        return sum(c.get(faction, 0.0) for c in self._control.values())

    def establish_hq(self, district, crew_id):
        hq = self._hqs.get(crew_id)
        if hq is None:
            hq = _FakeHQ(crew_id, district)
            self._hqs[crew_id] = hq
        return hq

    def get_hq(self, crew_id):
        return self._hqs.get(crew_id)

    def build_room(self, crew_id, room_type):
        hq = self._hqs.get(crew_id)
        if not hq or room_type in hq.rooms:
            return False
        hq.rooms[room_type] = 1
        return True

    def upgrade_room(self, crew_id, room_type):
        hq = self._hqs.get(crew_id)
        if not hq or room_type not in hq.rooms:
            return False
        hq.rooms[room_type] += 1
        return True


class _FakeMember:
    def __init__(self, cid: str, role: str = "hacker") -> None:
        self.character_id = cid
        self.role = role

    def to_dict(self) -> Dict[str, Any]:
        return {"character_id": self.character_id, "role": self.role}


class _FakeCrew:
    def __init__(self, members: Optional[List[str]] = None) -> None:
        self._members = [_FakeMember(c) for c in (members or ["nyx", "rook"])]
        self.recruit_calls: List[Tuple[str, str]] = []
        self.start_calls: List[Dict[str, Any]] = []
        self.recruit_ok = True

    def get_all_members(self):
        return list(self._members)

    def get_available(self):
        return list(self._members)

    def preview_success_chance(self, op_type, crew):
        return 0.42

    def compute_success_chance(self, op_type, crew):
        return 0.42, {"chance": 0.42}

    def start_operation(self, op_type, assigned_crew, label="", duration_secs=3600,
                        reward_credits=0, reward_xp=25):
        self.start_calls.append({
            "op_type": op_type, "crew": list(assigned_crew),
            "duration_secs": duration_secs, "reward_credits": reward_credits,
            "reward_xp": reward_xp,
        })
        # Honour the real min_crew gate so the gated path is testable.
        from engine.world.crew import OPERATION_TYPES
        min_crew = OPERATION_TYPES.get(op_type, {}).get("min_crew", 1)
        if len(assigned_crew) < min_crew:
            return False, f"{op_type} requires at least {min_crew} crew member(s)"
        return True, f"Operation started. Odds: 42%."

    def recruit(self, character_id, role="unknown", notes="", skip_check=False):
        self.recruit_calls.append((character_id, role))
        if self.recruit_ok:
            return True, f"{character_id} joined your crew as {role}!"
        return False, f"{character_id} doesn't trust you enough."


class _FakeFactionAI:
    def __init__(self) -> None:
        self._war_active: Dict[str, Dict[str, str]] = {}
        self.context_calls: List[Dict[str, Any]] = []

    def get_history(self, faction="", limit=20):
        return []

    def get_active_wars(self):
        return dict(self._war_active)

    def end_war(self, district):
        return self._war_active.pop(district, None) is not None

    def set_player_context(self, standings=None, district=""):
        self.context_calls.append({"standings": standings, "district": district})


class _FakeFactionManager:
    def __init__(self) -> None:
        self.modify_calls: List[Tuple[str, int, bool]] = []

    def get(self, faction_id):
        return None

    def modify_standing(self, faction_id, delta, cascade=True):
        self.modify_calls.append((faction_id, delta, cascade))
        return {faction_id: delta}


class _FakePlayerState:
    def __init__(self, allegiance: Optional[str] = "Ghost_Net") -> None:
        self._allegiance = allegiance
        self.faction_standings = {
            "OmniCorp": 0, "NeoTech": 0, "BlackMarket": 0,
            "Ghost_Net": 0, "SynthSec": 0, "DeepState": 0,
        }
        self.active_location = "DOWNTOWN"
        self.standing_calls: List[Tuple[str, int]] = []

    @property
    def allegiance(self):
        return self._allegiance

    def update_faction_standing(self, faction, delta):
        self.standing_calls.append((faction, delta))
        cur = self.faction_standings.get(faction, 0)
        new = max(-100, min(100, cur + delta))
        self.faction_standings[faction] = new
        return new


@pytest.fixture()
def scene(monkeypatch):
    """Boot a WarRoomScene with all manager accessors patched to fakes."""
    s = wr.WarRoomScene()
    s._fake_terr = _FakeTerritory()
    s._fake_crew = _FakeCrew()
    s._fake_ai = _FakeFactionAI()
    s._fake_mgr = _FakeFactionManager()
    s._fake_player = _FakePlayerState("Ghost_Net")
    monkeypatch.setattr(s, "_territory", lambda: s._fake_terr)
    monkeypatch.setattr(s, "_crew", lambda: s._fake_crew)
    monkeypatch.setattr(s, "_faction_ai", lambda: s._fake_ai)
    monkeypatch.setattr(s, "_faction_mgr", lambda: s._fake_mgr)
    monkeypatch.setattr(s, "_player", lambda: s._fake_player)
    # Avoid socket emits during command dispatch tests.
    monkeypatch.setattr(s, "_broadcast_update", lambda: None)
    return s


def _dispatch(scene, body: Dict[str, Any]) -> Dict[str, Any]:
    """Call the command handler directly, bypassing Flask's request object."""
    cmd = body.get("cmd", "")
    faction = scene._player_faction()
    if not faction:
        return {"ok": False, "reason": "no allegiance", "cmd": cmd}
    handlers = {
        "contest": scene._cmd_contest,
        "assign_op": scene._cmd_assign_op,
        "recruit": scene._cmd_recruit,
        "build_hq": scene._cmd_build_hq,
        "upgrade_room": scene._cmd_upgrade_room,
        "diplomacy": scene._cmd_diplomacy,
    }
    handler = handlers.get(cmd)
    if handler is None:
        return {"ok": False, "error": "unknown command", "cmd": cmd}
    result = handler(faction, body)
    result.setdefault("cmd", cmd)
    if result.get("ok"):
        result["state"] = scene._assemble_state()
    return result


# ──── dispatch guards ────


def test_no_allegiance_blocks_command(scene, monkeypatch):
    monkeypatch.setattr(scene, "_player", lambda: _FakePlayerState(None))
    res = _dispatch(scene, {"cmd": "contest", "district": "DOWNTOWN"})
    assert res["ok"] is False
    assert res["reason"] == "no allegiance"


def test_unknown_command_rejected(scene):
    res = _dispatch(scene, {"cmd": "frobnicate"})
    assert res["ok"] is False
    assert "unknown" in res["error"]


# ──── contest ────


def test_contest_raises_your_control(scene):
    before = scene._fake_terr.get_district_control("DOWNTOWN").get("Ghost_Net", 0.0)
    res = scene._cmd_contest("Ghost_Net", {"district": "downtown"})
    assert res["ok"] is True
    assert res["district"] == "DOWNTOWN"
    after = scene._fake_terr.get_district_control("DOWNTOWN").get("Ghost_Net", 0.0)
    assert after > before
    # delta clamped into CONTROL_SHIFT_RANGE
    lo, hi = CONTROL_SHIFT_RANGE
    assert lo <= res["delta"] <= hi
    # source faction is the manager's choice (None) per spec
    assert scene._fake_terr.shift_calls[-1]["faction"] == "Ghost_Net"
    assert scene._fake_terr.shift_calls[-1]["reason"] == "war_room"


def test_contest_invalid_district(scene):
    res = scene._cmd_contest("Ghost_Net", {"district": "MOON_BASE"})
    assert res["ok"] is False
    assert res["error"] == "invalid district"


# ──── assign_op ────


def test_assign_op_starts_with_preview(scene):
    res = scene._cmd_assign_op("Ghost_Net", {"op_type": "recon", "crew": ["nyx"]})
    assert res["ok"] is True
    assert res["preview"]["ok"] is True
    assert res["preview"]["percent"] == 42.0
    assert scene._fake_crew.start_calls[-1]["op_type"] == "recon"


def test_assign_op_gated_when_too_few_crew(scene):
    # heist needs >=3 crew; one member → clean gated failure, not a 500.
    res = scene._cmd_assign_op("Ghost_Net", {"op_type": "heist", "crew": ["nyx"]})
    assert res["ok"] is False
    assert "requires at least" in res["error"]
    assert res["preview"]["enough_crew"] is False


def test_assign_op_invalid_type(scene):
    res = scene._cmd_assign_op("Ghost_Net", {"op_type": "nope", "crew": ["nyx"]})
    assert res["ok"] is False
    assert res["error"] == "invalid op_type"


# ──── recruit ────


def test_recruit_success(scene):
    res = scene._cmd_recruit("Ghost_Net", {"character_id": "lola", "role": "fixer"})
    assert res["ok"] is True
    assert scene._fake_crew.recruit_calls[-1] == ("lola", "fixer")


def test_recruit_gated(scene):
    scene._fake_crew.recruit_ok = False
    res = scene._cmd_recruit("Ghost_Net", {"character_id": "stranger"})
    assert res["ok"] is False
    assert "trust" in res["error"]


def test_recruit_requires_id(scene):
    res = scene._cmd_recruit("Ghost_Net", {})
    assert res["ok"] is False


# ──── build_hq / upgrade_room ────


def test_build_hq_then_upgrade_room(scene):
    res = scene._cmd_build_hq("Ghost_Net", {"district": "TECH_DISTRICT"})
    assert res["ok"] is True
    assert res["district"] == "TECH_DISTRICT"
    crew_id = res["crew_id"]
    assert scene._fake_terr.get_hq(crew_id) is not None

    room = sorted(HQ_ROOM_TYPES.keys())[0]
    # First call builds the room.
    r1 = scene._cmd_upgrade_room("Ghost_Net", {"room_type": room})
    assert r1["ok"] is True and r1["action"] == "built"
    # Second call upgrades it.
    r2 = scene._cmd_upgrade_room("Ghost_Net", {"room_type": room})
    assert r2["ok"] is True and r2["action"] == "upgraded"


def test_upgrade_room_without_hq(scene):
    # Fresh scene with no HQ established.
    res = scene._cmd_upgrade_room("Ghost_Net", {"room_type": "lab", "crew_id": "ghost_hq"})
    assert res["ok"] is False
    assert "HQ" in res["error"]


def test_build_hq_invalid_district(scene):
    res = scene._cmd_build_hq("Ghost_Net", {"district": "NOWHERE"})
    assert res["ok"] is False


# ──── diplomacy ────


def test_diplomacy_war_flips_relation_in_state(scene):
    res = _dispatch(scene, {"cmd": "diplomacy", "target_faction": "OmniCorp", "kind": "war"})
    assert res["ok"] is True
    assert res["relation"] == "war"
    assert res["standing"] <= -25
    # observable in the assembled state's rivals
    rivals = {r["faction"]: r for r in res["state"]["rivals"]}
    assert rivals["OmniCorp"]["relation"] <= -25
    # a war was registered with FactionAI
    assert any(v.get("defender") == "OmniCorp"
               for v in scene._fake_ai.get_active_wars().values())


def test_diplomacy_ally_flips_relation(scene):
    res = _dispatch(scene, {"cmd": "diplomacy", "target_faction": "NeoTech", "kind": "ally"})
    assert res["ok"] is True
    assert res["relation"] == "ally"
    rivals = {r["faction"]: r for r in res["state"]["rivals"]}
    assert rivals["NeoTech"]["relation"] >= 25


def test_diplomacy_rejects_self(scene):
    res = scene._cmd_diplomacy("Ghost_Net", {"target_faction": "Ghost_Net", "kind": "war"})
    assert res["ok"] is False


def test_diplomacy_invalid_kind(scene):
    res = scene._cmd_diplomacy("Ghost_Net", {"target_faction": "OmniCorp", "kind": "smooch"})
    assert res["ok"] is False


# ──── op_preview ────


def test_op_preview_shape(scene):
    res = scene._op_preview("recon", ["nyx"])
    assert res["ok"] is True
    assert res["percent"] == 42.0
    assert res["enough_crew"] is True


def test_op_preview_invalid_type(scene):
    res = scene._op_preview("nope", ["nyx"])
    assert res["ok"] is False
