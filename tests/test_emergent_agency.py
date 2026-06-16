"""Unit tests for the emergent agency driver (Task A5).

The agency is the DRIVER that runs the per-NPC goals→plan→execute loop on the
EXISTING LivingWorld cadence. It does not start a second daemon: it subscribes
to the ``living_world_tick`` event on the shared :class:`EventBus`, and on each
tick runs one bounded *agency pass* over a handful of NPCs.

These tests mock the seam (a fake EventBus) and every collaborator the agency
talks to (planner ``plan_action`` / ``execute``, goal ``generate_goals`` /
``load_goals`` / ``save_goals`` / ``reprioritize``, the roster source, and the
ctx-building managers). No live LivingWorld, EventBus, Database, or manager is
constructed; an explicit-path :class:`EmergentStore` captures any persistence.

They pin the behaviour the spec requires:
    * ``start()`` subscribes to the ``living_world_tick`` seam; ``stop()``
      unsubscribes cleanly (idempotent both ways);
    * a simulated tick runs ``run_pass``: at least one NPC goes
      goals→plan→execute, a goal set is persisted, and an ``emergent_action``
      event is published to the existing feed;
    * the per-tick cap (``emergent.agency.active_npcs_per_tick``) is honoured
      even when more NPCs exist;
    * ``pivotal``/LLM stays rare (the pivotal cap is honoured);
    * a planner / execute / manager raising NEVER propagates out of the tick
      handler (the tick survives and the error is logged);
    * with ``emergent.agency.enabled = false`` ``start()`` is a no-op.

Version: v1.63.0 [2026-06-15]

Change Log:
    v1.63.0 [2026-06-15] — Initial tests for the emergent agency driver (A5):
                            tick-seam subscribe/unsubscribe, bounded agency
                            pass (goals→plan→execute→reprioritize→persist→emit),
                            active-npcs cap, pivotal-rarity cap, never-raises
                            tick handler, and disabled-config no-op.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pytest

from engine.world.emergent import agency as agency_mod
from engine.world.emergent.agency import EmergentAgency, get_emergent_agency
from engine.world.emergent.goals import Goal, WEALTH
from engine.world.emergent.planner import PlannedAction
from engine.world.emergent.store import EmergentStore

#: The genuine module-level _build_ctx, captured before any monkeypatch swaps it
#: (the pivotal test restores it after _stub_collaborators replaces it).
_REAL_BUILD_CTX = agency_mod._build_ctx


# ══════════════════════════════════════════════════════════════════════
#  Test doubles
# ══════════════════════════════════════════════════════════════════════


class FakeBus:
    """A minimal EventBus stand-in recording subscribe/unsubscribe/publish."""

    def __init__(self) -> None:
        self.subs: Dict[str, tuple] = {}
        self.published: List[tuple] = []
        self._n = 0

    def subscribe(self, event_type, handler, subscriber_id=""):
        self._n += 1
        sid = f"sub-{self._n}"
        self.subs[sid] = (event_type, handler, subscriber_id)
        return sid

    def unsubscribe(self, sub_id) -> bool:
        return self.subs.pop(sub_id, None) is not None

    def publish(self, event_type, payload, scene="") -> None:
        self.published.append((event_type, payload, scene))

    def fire_tick(self, payload: Optional[Dict[str, Any]] = None) -> None:
        """Invoke every ``living_world_tick`` handler (simulate a real tick)."""
        event = {"event_type": "living_world_tick", "payload": payload or {}}
        for event_type, handler, _sid in list(self.subs.values()):
            if event_type == "living_world_tick":
                handler(event)


class _Cfg:
    """A tiny get_config() stand-in returning values from a dict."""

    def __init__(self, values: Dict[str, Any]) -> None:
        self._values = values

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


@pytest.fixture
def store(tmp_path) -> EmergentStore:
    """An EmergentStore backed by an isolated temp database."""
    return EmergentStore(path=tmp_path / "emergent.db")


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure the agency singleton never leaks between tests."""
    agency_mod._instance = None
    yield
    agency_mod._instance = None


def _install_cfg(monkeypatch, **overrides) -> None:
    """Patch the agency module's get_config to return controlled values."""
    values = {
        "emergent.agency.enabled": True,
        "emergent.agency.active_npcs_per_tick": 3,
        "emergent.agency.pivotal_per_tick": 1,
        "emergent.agency.pivotal_chance": 0.0,
    }
    values.update(overrides)
    monkeypatch.setattr(agency_mod, "get_config", lambda: _Cfg(values))


def _stub_collaborators(
    monkeypatch,
    *,
    roster: List[str],
    store: EmergentStore,
    plan_returns: Optional[PlannedAction] = None,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wire all agency seams to controllable fakes; return a call recorder."""
    rec: Dict[str, Any] = record if record is not None else {}
    rec.setdefault("planned", [])
    rec.setdefault("executed", [])
    rec.setdefault("saved", [])
    rec.setdefault("generated", [])

    monkeypatch.setattr(agency_mod, "_enumerate_npcs", lambda self: list(roster))
    monkeypatch.setattr(agency_mod, "_build_ctx", lambda self, npc_id: {"npc": npc_id})
    monkeypatch.setattr(agency_mod, "_default_store", lambda: store)

    def fake_load(npc_id, store=None):
        return [Goal(type=WEALTH, target="", priority=0.5)]

    def fake_generate(npc_id, *, ctx, rng=None):
        rec["generated"].append(npc_id)
        return [Goal(type=WEALTH, target="", priority=0.5)]

    def fake_save(npc_id, goals, store=None):
        rec["saved"].append(npc_id)
        return True

    def fake_reprioritize(goals, outcome):
        return goals

    def fake_plan(npc_id, *, goals, ctx, rng=None):
        rec["planned"].append(npc_id)
        return plan_returns if plan_returns is not None else PlannedAction(verb="lay_low")

    def fake_execute(npc_id, action, *, ctx):
        rec["executed"].append((npc_id, action.verb))
        return {"verb": action.verb, "ok": True, "detail": "stub"}

    monkeypatch.setattr(agency_mod, "load_goals", fake_load)
    monkeypatch.setattr(agency_mod, "generate_goals", fake_generate)
    monkeypatch.setattr(agency_mod, "save_goals", fake_save)
    monkeypatch.setattr(agency_mod, "reprioritize", fake_reprioritize)
    monkeypatch.setattr(agency_mod, "plan_action", fake_plan)
    monkeypatch.setattr(agency_mod, "execute", fake_execute)
    return rec


# ══════════════════════════════════════════════════════════════════════
#  start() / stop() — the tick seam
# ══════════════════════════════════════════════════════════════════════


def test_start_subscribes_to_living_world_tick(monkeypatch) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)

    a = EmergentAgency()
    a.start()

    assert len(bus.subs) == 1
    event_type = next(iter(bus.subs.values()))[0]
    assert event_type == "living_world_tick"


def test_start_is_idempotent(monkeypatch) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)

    a = EmergentAgency()
    a.start()
    a.start()  # second call must not double-subscribe
    assert len(bus.subs) == 1


def test_stop_unsubscribes(monkeypatch) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)

    a = EmergentAgency()
    a.start()
    assert len(bus.subs) == 1
    a.stop()
    assert len(bus.subs) == 0
    a.stop()  # idempotent


def test_disabled_config_makes_start_a_noop(monkeypatch) -> None:
    _install_cfg(monkeypatch, **{"emergent.agency.enabled": False})
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)

    a = EmergentAgency()
    a.start()
    assert len(bus.subs) == 0
    assert a.is_running() is False


# ══════════════════════════════════════════════════════════════════════
#  run_pass — the goals→plan→execute loop on a simulated tick
# ══════════════════════════════════════════════════════════════════════


def test_tick_runs_full_pass_for_at_least_one_npc(monkeypatch, store) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)
    rec = _stub_collaborators(
        monkeypatch, roster=["lola"], store=store,
        plan_returns=PlannedAction(verb="message", target="viktor"),
    )

    a = EmergentAgency()
    a.start()
    bus.fire_tick()

    # one NPC went goals -> plan -> execute (non-trade verb takes the execute path)
    assert rec["planned"] == ["lola"]
    assert rec["executed"] == [("lola", "message")]
    # a goal set was persisted (reprioritize + save)
    assert "lola" in rec["saved"]
    # an emergent_action event reached the existing feed
    kinds = [p[0] for p in bus.published]
    assert "emergent_action" in kinds


def test_npc_trade_nudges_market_not_execute(monkeypatch, store) -> None:
    # The trade verb must NOT route through execute (which would drain the player
    # wallet via global Market settlement); it takes the non-settling supply
    # nudge via Market.apply_event instead.
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)
    rec = _stub_collaborators(
        monkeypatch, roster=["lola"], store=store,
        plan_returns=PlannedAction(verb="trade", target="", params={"side": "buy"}),
    )

    calls = {"apply_event": [], "buy": 0, "sell": 0}

    class FakeMarket:
        def apply_event(self, event_type, magnitude=1.0):
            calls["apply_event"].append(event_type)
            return {"status": "ok", "applied": True}

        def buy(self, *a, **k):
            calls["buy"] += 1
            return {"status": "ok"}

        def sell(self, *a, **k):
            calls["sell"] += 1
            return {"status": "ok"}

    fake_market = FakeMarket()
    monkeypatch.setattr("engine.world.market.get_market", lambda: fake_market)

    a = EmergentAgency()
    a.start()
    bus.fire_tick()

    # supply/demand was moved via apply_event; no settling buy/sell ran;
    # the planner execute() path was NOT taken for the trade.
    assert calls["apply_event"] == ["shortage"]  # buy-pressure
    assert calls["buy"] == 0 and calls["sell"] == 0
    assert rec["executed"] == []
    # still emits an emergent_action for the trade.
    assert any(p[0] == "emergent_action" for p in bus.published)


def test_tick_generates_goals_when_none_persisted(monkeypatch, store) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)
    rec = _stub_collaborators(monkeypatch, roster=["viktor"], store=store)
    # No persisted goals -> agency must generate + save.
    monkeypatch.setattr(agency_mod, "load_goals", lambda npc_id, store=None: [])

    a = EmergentAgency()
    a.start()
    bus.fire_tick()

    assert rec["generated"] == ["viktor"]
    assert "viktor" in rec["saved"]


def test_run_pass_respects_active_npcs_cap(monkeypatch, store) -> None:
    _install_cfg(monkeypatch, **{"emergent.agency.active_npcs_per_tick": 2})
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)
    rec = _stub_collaborators(
        monkeypatch, roster=["lola", "viktor", "aria", "frankie", "mira"],
        store=store,
    )

    a = EmergentAgency()
    a.start()
    bus.fire_tick()

    # Cap = 2 → exactly two NPCs acted even though five exist.
    assert len(rec["planned"]) == 2
    assert len(rec["executed"]) == 2


def test_pivotal_is_capped_per_tick(monkeypatch, store) -> None:
    # pivotal_chance = 1.0 would flag every NPC, but the cap clamps it.
    _install_cfg(
        monkeypatch,
        **{
            "emergent.agency.active_npcs_per_tick": 5,
            "emergent.agency.pivotal_per_tick": 1,
            "emergent.agency.pivotal_chance": 1.0,
        },
    )
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)

    pivotal_flags: List[bool] = []

    rec: Dict[str, Any] = {}
    _stub_collaborators(
        monkeypatch, roster=["lola", "viktor", "aria", "frankie", "mira"],
        store=store, record=rec,
    )

    def capture_plan(npc_id, *, goals, ctx, rng=None):
        pivotal_flags.append(bool(ctx.get("pivotal")))
        return PlannedAction(verb="lay_low")

    monkeypatch.setattr(agency_mod, "plan_action", capture_plan)
    # _stub_collaborators replaced _build_ctx with a cheap stub; restore the REAL
    # module-level _build_ctx so the pivotal flag threaded into ctx is genuine.
    monkeypatch.setattr(agency_mod, "_build_ctx", _REAL_BUILD_CTX)
    monkeypatch.setattr(
        agency_mod, "_enumerate_npcs",
        lambda self: ["lola", "viktor", "aria", "frankie", "mira"],
    )
    monkeypatch.setattr(agency_mod, "_relationships_for", lambda self, npc, others: {})
    monkeypatch.setattr(agency_mod, "_faction_for", lambda self, npc: None)
    monkeypatch.setattr(agency_mod, "_district_for", lambda self, npc: "")
    monkeypatch.setattr(agency_mod, "_crew_for", lambda self, npc: [])
    monkeypatch.setattr(agency_mod, "_recently_hacked", lambda self, npc: False)

    a = EmergentAgency(rng=random.Random(7))
    a.start()
    bus.fire_tick()

    assert sum(1 for f in pivotal_flags if f) <= 1


# ══════════════════════════════════════════════════════════════════════
#  defensive — a failure must NEVER propagate into the tick
# ══════════════════════════════════════════════════════════════════════


def test_planner_raising_does_not_propagate(monkeypatch, store) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)
    _stub_collaborators(monkeypatch, roster=["lola", "viktor"], store=store)

    def boom(npc_id, *, goals, ctx, rng=None):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(agency_mod, "plan_action", boom)

    a = EmergentAgency()
    a.start()
    # Must not raise — the tick survives the planner blowing up.
    bus.fire_tick()


def test_execute_raising_does_not_propagate(monkeypatch, store) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)
    _stub_collaborators(
        monkeypatch, roster=["lola"], store=store,
        plan_returns=PlannedAction(verb="trade"),
    )

    def boom(npc_id, action, *, ctx):
        raise RuntimeError("execute exploded")

    monkeypatch.setattr(agency_mod, "execute", boom)

    a = EmergentAgency()
    a.start()
    bus.fire_tick()  # must not raise


def test_enumerate_raising_does_not_propagate(monkeypatch, store) -> None:
    _install_cfg(monkeypatch)
    bus = FakeBus()
    monkeypatch.setattr(agency_mod, "get_event_bus", lambda: bus)

    def boom(self):
        raise RuntimeError("roster exploded")

    monkeypatch.setattr(agency_mod, "_enumerate_npcs", boom)

    a = EmergentAgency()
    a.start()
    bus.fire_tick()  # must not raise


# ══════════════════════════════════════════════════════════════════════
#  singleton
# ══════════════════════════════════════════════════════════════════════


def test_get_emergent_agency_is_singleton() -> None:
    a = get_emergent_agency()
    b = get_emergent_agency()
    assert a is b
