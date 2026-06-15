"""
EventCascade ↔ WorldSim wiring tests (v1.59.0)
==============================================

Verifies WorldSim.on_event() subscriber fan-out and that EventCascade
receives world events, maps SimEventType → WorldEventType, and dispatches
to subscribed scenes.

Version: v1.59.0 [2026-06-13]
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_worldsim_on_event_fanout():
    from engine.world.world_sim import WorldSim, SimEvent, SimEventType
    sim = WorldSim()
    received = []
    sim.on_event(lambda e: received.append(e))
    # duplicate registration is ignored
    cb = received.append
    sim.on_event(cb)
    sim.on_event(cb)

    evt = SimEvent(id="e1", event_type=SimEventType.ECONOMY_TICK, title="t",
                   description="d", scene="")
    sim._log_event(evt)

    assert evt in received


@pytest.mark.unit
def test_cascade_maps_and_dispatches_sim_event():
    from engine.world.event_cascade import EventCascade, WorldEventType
    from engine.world.world_sim import SimEvent, SimEventType

    cascade = EventCascade()
    cascade.subscribe("neoncity", [WorldEventType.ECONOMY])

    delivered = {}
    # Stub _deliver so we don't need a live EventBus / Socket.IO
    cascade._deliver = lambda evt: delivered.setdefault(evt.scene, evt) or True

    evt = SimEvent(id="e2", event_type=SimEventType.ECONOMY_TICK, title="Crash",
                   description="markets dip", scene="")
    cascade._on_world_sim_event(evt)

    assert "neoncity" in delivered
    # mapped from economy_tick → economy
    assert delivered["neoncity"].event_type == WorldEventType.ECONOMY


@pytest.mark.unit
def test_cascade_start_connects_to_worldsim(monkeypatch):
    from engine.world.event_cascade import EventCascade
    from engine.world import world_sim as ws

    sim = ws.WorldSim()
    monkeypatch.setattr(ws, "get_world_sim", lambda: sim)

    cascade = EventCascade()
    cascade.start()
    # start() should have registered cascade's handler on the sim
    assert getattr(sim, "_event_subscribers", []), "cascade did not subscribe to WorldSim"
