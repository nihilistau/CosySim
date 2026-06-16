"""Unit tests for the hybrid emergent planner (Task A4).

Covers the PURE planner (``plan_action`` driven entirely by a hand-built goal
list + ctx) and the defensive dispatcher (``execute``). Every manager the
dispatcher talks to is mocked AT THE BOUNDARY with monkeypatch — no live
TerritoryManager / Market / CrewManager / phone_hack / relationship_effects /
npc_comms is constructed, and no real database or sim store is touched. An
explicit ``EmergentStore(path=tmp)`` captures world events.

These tests assert the behaviour the spec pins down:
    * a LAY_LOW-topped goal set never plans an aggressive verb;
    * a WEALTH top goal plans ``trade`` and execute calls the (mocked) Market;
    * a TERRITORY goal + faction + district plans ``contest`` and execute calls
      ``shift_control`` with a delta inside ``CONTROL_SHIFT_RANGE`` and
      ``source_faction`` set;
    * a REVENGE goal with a hostile target plans ``hack`` or ``betray`` and
      execute routes to the mocked hack / relationship path;
    * llm gating: ``llm_chance=0`` never sets ``use_llm``; a pivotal action with
      ``llm_chance=1`` does;
    * execute logs a world_event via an explicit-path store and returns ok;
    * execute survives a manager raising (returns ok:False, does not propagate).

Version: v1.63.0 [2026-06-15]

Change Log:
    v1.63.0 [2026-06-15] — Initial tests for the emergent hybrid planner (A4):
                            goal→verb mapping, lay-low suppression, utility
                            scoring, llm gating, manager dispatch (mocked at the
                            boundary), world-event logging, and defensive
                            never-raises execute.
"""
from __future__ import annotations

import random

import pytest

from engine.world.emergent.goals import (
    LAY_LOW,
    RANK,
    REVENGE,
    ROMANCE,
    TERRITORY,
    WEALTH,
    Goal,
)
from engine.world.emergent import planner as planner_mod
from engine.world.emergent.planner import PlannedAction, execute, plan_action
from engine.world.emergent.store import EmergentStore
from engine.world.territory import CONTROL_SHIFT_RANGE


@pytest.fixture
def store(tmp_path) -> EmergentStore:
    """Return an EmergentStore backed by an isolated temp database."""
    return EmergentStore(path=tmp_path / "emergent.db")


@pytest.fixture
def seeded_rng() -> random.Random:
    """A seeded RNG so tie-breaks/llm rolls are deterministic in tests."""
    return random.Random(1234)


# ══════════════════════════════════════════════════════════════════════
#  plan_action — goal → verb mapping + scoring
# ══════════════════════════════════════════════════════════════════════


def test_plan_action_none_when_no_goals(seeded_rng) -> None:
    assert plan_action("npc-1", goals=[], ctx={}, rng=seeded_rng) is None


def test_wealth_top_goal_plans_trade(seeded_rng) -> None:
    goals = [Goal(type=WEALTH, target="", priority=0.9)]
    action = plan_action("npc-1", goals=goals, ctx={"district": "DOWNTOWN"}, rng=seeded_rng)
    assert action is not None
    assert action.verb == "trade"


def test_territory_goal_plans_contest(seeded_rng) -> None:
    goals = [Goal(type=TERRITORY, target="OmniCorp", priority=0.9)]
    ctx = {"faction": "OmniCorp", "district": "DOWNTOWN"}
    action = plan_action("npc-1", goals=goals, ctx=ctx, rng=seeded_rng)
    assert action is not None
    assert action.verb == "contest"
    assert action.target == "DOWNTOWN"


def test_territory_goal_without_faction_does_not_contest(seeded_rng) -> None:
    # No faction → contest is infeasible; planner must not pick it.
    goals = [Goal(type=TERRITORY, target="", priority=0.9)]
    action = plan_action("npc-1", goals=goals, ctx={"district": "DOWNTOWN"}, rng=seeded_rng)
    assert action is None or action.verb != "contest"


def test_rank_goal_plans_crew_op(seeded_rng) -> None:
    goals = [Goal(type=RANK, target="OmniCorp", priority=0.9)]
    ctx = {"faction": "OmniCorp", "crew": ["lola", "dex"]}
    action = plan_action("npc-1", goals=goals, ctx=ctx, rng=seeded_rng)
    assert action is not None
    assert action.verb == "crew_op"


def test_revenge_goal_plans_hack_or_betray(seeded_rng) -> None:
    goals = [Goal(type=REVENGE, target="rival", priority=0.95)]
    action = plan_action("npc-1", goals=goals, ctx={}, rng=seeded_rng)
    assert action is not None
    assert action.verb in ("hack", "betray")
    assert action.target == "rival"


def test_romance_goal_plans_romance(seeded_rng) -> None:
    goals = [Goal(type=ROMANCE, target="lover", priority=0.9)]
    action = plan_action("npc-1", goals=goals, ctx={}, rng=seeded_rng)
    assert action is not None
    assert action.verb == "romance"
    assert action.target == "lover"


# ══════════════════════════════════════════════════════════════════════
#  LAY_LOW suppresses aggressive verbs
# ══════════════════════════════════════════════════════════════════════


def test_lay_low_top_goal_never_aggressive(seeded_rng) -> None:
    # LAY_LOW is boosted above everything; even with a tempting revenge/territory
    # opportunity present, the planner must not pick an aggressive verb.
    goals = [
        Goal(type=LAY_LOW, target="", priority=1.5),
        Goal(type=REVENGE, target="rival", priority=0.95),
        Goal(type=TERRITORY, target="OmniCorp", priority=0.9),
    ]
    ctx = {"faction": "OmniCorp", "district": "DOWNTOWN"}
    action = plan_action("npc-1", goals=goals, ctx=ctx, rng=seeded_rng)
    assert action is not None
    assert action.verb not in ("hack", "betray", "contest", "crew_op")
    assert action.verb == "lay_low"


# ══════════════════════════════════════════════════════════════════════
#  LLM gating
# ══════════════════════════════════════════════════════════════════════


def test_llm_chance_zero_never_uses_llm(monkeypatch, seeded_rng) -> None:
    monkeypatch.setattr(planner_mod, "_planner_cfg", lambda key: _cfg_with(key, llm_chance=0.0))
    goals = [Goal(type=REVENGE, target="rival", priority=0.99)]
    action = plan_action("npc-1", goals=goals, ctx={"pivotal": True}, rng=seeded_rng)
    assert action is not None
    assert action.use_llm is False


def test_pivotal_action_with_llm_chance_one_uses_llm(monkeypatch, seeded_rng) -> None:
    monkeypatch.setattr(planner_mod, "_planner_cfg", lambda key: _cfg_with(key, llm_chance=1.0))
    goals = [Goal(type=REVENGE, target="rival", priority=0.99)]
    action = plan_action("npc-1", goals=goals, ctx={"pivotal": True}, rng=seeded_rng)
    assert action is not None
    assert action.use_llm is True


# ══════════════════════════════════════════════════════════════════════
#  execute — dispatch to the EXISTING managers (mocked at the boundary)
# ══════════════════════════════════════════════════════════════════════


def test_execute_trade_calls_market(monkeypatch, store) -> None:
    calls = {}

    class FakeMarket:
        def buy(self, district, good_id, quantity=1, **kw):
            calls["buy"] = (district, good_id, quantity)
            return {"status": "ok", "total": 100, "good_id": good_id}

        def sell(self, district, good_id, quantity=1, **kw):
            calls["sell"] = (district, good_id, quantity)
            return {"status": "ok", "total": 60, "good_id": good_id}

    monkeypatch.setattr(planner_mod, "get_market", lambda: FakeMarket())
    action = PlannedAction(verb="trade", target="", params={"district": "DOWNTOWN", "good_id": "stim_pack"})
    result = execute("npc-1", action, ctx={"district": "DOWNTOWN", "store": store})
    assert result["ok"] is True
    assert result["verb"] == "trade"
    assert "buy" in calls or "sell" in calls


def test_execute_contest_calls_shift_control(monkeypatch, store) -> None:
    calls = {}

    class FakeEvent:
        def __init__(self):
            self.delta = 3.0
            self.district = "DOWNTOWN"
            self.faction = "OmniCorp"
            self.triggered_war = False

        def to_dict(self):
            return {"district": self.district, "faction": self.faction, "delta": self.delta}

    class FakeTerritory:
        def shift_control(self, district, faction, delta, reason="", source_faction=None):
            calls["args"] = dict(
                district=district, faction=faction, delta=delta,
                reason=reason, source_faction=source_faction,
            )
            return FakeEvent()

    monkeypatch.setattr(planner_mod, "get_territory_manager", lambda: FakeTerritory())
    action = PlannedAction(
        verb="contest", target="DOWNTOWN",
        params={"faction": "OmniCorp", "district": "DOWNTOWN"},
    )
    result = execute("npc-1", action, ctx={"faction": "OmniCorp", "store": store})
    assert result["ok"] is True
    args = calls["args"]
    assert args["district"] == "DOWNTOWN"
    assert args["faction"] == "OmniCorp"
    # source_faction must be set to the NPC's own faction.
    assert args["source_faction"] == "OmniCorp"
    # delta must be within CONTROL_SHIFT_RANGE.
    lo, hi = CONTROL_SHIFT_RANGE
    assert lo <= abs(args["delta"]) <= hi


def test_execute_crew_op_calls_crew_manager(monkeypatch, store) -> None:
    calls = {}

    class FakeCrew:
        def compute_success_chance(self, op_type, assigned_crew):
            return 0.5, {}

        def start_operation(self, op_type, assigned_crew, **kw):
            calls["start"] = (op_type, list(assigned_crew))
            return True, "Operation started!"

    monkeypatch.setattr(planner_mod, "get_crew_manager", lambda: FakeCrew())
    action = PlannedAction(verb="crew_op", target="OmniCorp", params={"crew": ["lola", "dex"]})
    result = execute("npc-1", action, ctx={"faction": "OmniCorp", "crew": ["lola", "dex"], "store": store})
    assert result["ok"] is True
    assert "start" in calls


def test_execute_hack_routes_to_hack_phone(monkeypatch, store) -> None:
    calls = {}

    def fake_hack_phone(target_id="", action="intercept"):
        calls["hack"] = (target_id, action)
        return {"success": True, "action": action, "target": target_id}

    monkeypatch.setattr(planner_mod, "hack_phone", fake_hack_phone)
    action = PlannedAction(verb="hack", target="rival")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is True
    assert calls["hack"][0] == "rival"
    assert calls["hack"][1] == "intercept"


def test_execute_betray_routes_to_relationship_path(monkeypatch, store) -> None:
    calls = {}

    def fake_apply(db, sender, recipient, content, tone="neutral"):
        calls["exchange"] = (sender, recipient, tone)
        return 0.2

    monkeypatch.setattr(planner_mod, "apply_exchange_effect", fake_apply)
    monkeypatch.setattr(planner_mod, "_get_database", lambda ctx: object())
    action = PlannedAction(verb="betray", target="rival")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is True
    assert calls["exchange"][0] == "npc-1"
    assert calls["exchange"][1] == "rival"


def test_execute_romance_routes_to_relationship_path(monkeypatch, store) -> None:
    calls = {}

    def fake_apply(db, sender, recipient, content, tone="neutral"):
        calls["exchange"] = (sender, recipient, tone)
        return 0.5

    monkeypatch.setattr(planner_mod, "apply_exchange_effect", fake_apply)
    monkeypatch.setattr(planner_mod, "_get_database", lambda ctx: object())
    action = PlannedAction(verb="romance", target="lover")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is True
    assert calls["exchange"][1] == "lover"
    assert calls["exchange"][2] == "warm"


def test_execute_message_routes_to_npc_comms(monkeypatch, store) -> None:
    calls = {}

    class FakeScheduler:
        def run_exchange(self, a, b):
            calls["run"] = (a, b)
            return {"sender": a, "recipient": b, "content": "hi"}

    monkeypatch.setattr(planner_mod, "get_npc_comms_scheduler", lambda: FakeScheduler())
    action = PlannedAction(verb="message", target="friend")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is True
    assert calls["run"] == ("npc-1", "friend")


def test_execute_lay_low_is_noop_ok(store) -> None:
    action = PlannedAction(verb="lay_low", target="")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is True
    assert result["verb"] == "lay_low"


# ══════════════════════════════════════════════════════════════════════
#  execute — world-event logging + never-raises
# ══════════════════════════════════════════════════════════════════════


def test_execute_logs_world_event(monkeypatch, store) -> None:
    def fake_hack_phone(target_id="", action="intercept"):
        return {"success": True, "action": action, "target": target_id}

    monkeypatch.setattr(planner_mod, "hack_phone", fake_hack_phone)
    assert store.count_events() == 0
    action = PlannedAction(verb="hack", target="rival")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is True
    assert store.count_events() == 1
    events = store.recent_events(1)
    assert events[0]["kind"] == "hack"
    assert events[0]["actor"] == "npc-1"


def test_execute_survives_manager_raising(monkeypatch, store) -> None:
    class BoomMarket:
        def buy(self, *a, **k):
            raise RuntimeError("market down")

        def sell(self, *a, **k):
            raise RuntimeError("market down")

    monkeypatch.setattr(planner_mod, "get_market", lambda: BoomMarket())
    action = PlannedAction(verb="trade", target="", params={"district": "DOWNTOWN", "good_id": "stim_pack"})
    # Must NOT raise — defensive execute returns ok:False instead.
    result = execute("npc-1", action, ctx={"district": "DOWNTOWN", "store": store})
    assert result["ok"] is False
    assert result["verb"] == "trade"
    # A failed dispatch must not log a world event.
    assert store.count_events() == 0


def test_execute_unknown_verb_returns_not_ok(store) -> None:
    action = PlannedAction(verb="explode", target="")
    result = execute("npc-1", action, ctx={"store": store})
    assert result["ok"] is False


# ══════════════════════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════════════════════


def _cfg_with(key: str, *, llm_chance: float) -> float:
    """Return a planner-config value with a forced ``llm_chance`` override.

    Used by the llm-gating tests to monkeypatch ``planner._planner_cfg`` so the
    chance is deterministic while every other weight keeps its real default.
    """
    if key == "llm_chance":
        return llm_chance
    return planner_mod._PLANNER_DEFAULTS[key]
