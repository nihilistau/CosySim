# CosySim World System

> Living world infrastructure — WorldSim, WorldState, NPCScheduler, NPCState, EventBus, SceneDirector.
> Core system added in v0.68 "Dark Renaissance"; NPC autonomy layer added in v0.72b "The Asset Studio".

---

## Overview

The world system makes CosySim a living simulation. Even when you're not in a scene, the world ticks
forward: factions shift, characters move, time passes, events fire, and NPCs carry on with their lives.
The system is composed of five cooperating layers: world time (`WorldState`), simulation advancement
(`WorldSim`), cross-scene messaging (`EventBus`), narrative scheduling (`SceneDirector`), and autonomous
NPC activity (`NPCScheduler` + `NPCState`).

---

## Components

### WorldState (`engine/world/world_state.py`)

Game clock (1 real min = 1 game hour). Tracks weather, time-of-day, and NPC daily schedules.

```python
from engine.world.world_state import get_world_state
ws = get_world_state()
time = ws.get_time()        # WorldTime(hour=14, day=3, weather=Weather.RAIN)
ws.tick(minutes=5)          # advance by 5 real minutes = 5 game hours
```

Config key: `world.sim_enabled` (bool, default `true`) — set to `false` to freeze time.

---

### WorldSim (`engine/world/world_sim.py`)

Background daemon thread. Fires `world.tick` events at a fixed interval and broadcasts via EventBus.
Started by the launcher once all scenes are running.

```python
from engine.world.world_sim import get_world_sim
sim = get_world_sim()
sim.start()   # start daemon (called by launcher after scenes start)
sim.stop()    # graceful shutdown
```

Config key: `world.tick_interval_seconds` (int, default `60`).

---

### EventBus (`engine/events/event_bus.py`)

Thread-safe in-process pub/sub backbone. Carries cross-scene events and persists significant events
to Nexus history for post-session analysis.

```python
from engine.events.event_bus import get_event_bus
bus = get_event_bus()
bus.subscribe("casino.major_win", my_handler)
bus.publish("casino.major_win", {"player": "lola", "amount": 500})
```

---

### NPCState (`engine/world/npc_state.py`)

Thread-safe registry of per-NPC runtime state. Each entry tracks location, current activity, last
generated action, timestamp, mood, and a busy flag. Used by `NPCScheduler` to update state and by
scene UIs to render NPC activity badges in the admin overlay.

```python
from engine.world.npc_state import get_npc_state_registry, NPCState
registry = get_npc_state_registry()

# Read state
state: NPCState = registry.get("lola")
print(state.activity)       # "browsing nearby goods"
print(state.location)       # "The Velvet Pit"

# Update state (done internally by NPCScheduler)
registry.update("lola", activity="chatting with someone", mood="happy")
```

**NPCState fields:**

| Field | Type | Description |
|-------|------|-------------|
| `character_id` | str | Unique NPC identifier |
| `location` | str | Current in-world location |
| `activity` | str | Short description of current activity |
| `last_action` | str | Most recent LLM-generated action text |
| `last_action_time` | float | Unix timestamp of last action |
| `mood` | str | Emotional tone (`neutral`, `happy`, `tense`, …) |
| `is_busy` | bool | True while NPC has an active scheduled activity |

---

### NPCScheduler (`engine/agents/npc_scheduler.py`)

Drives autonomous NPC activity via a periodic tick loop integrated with `SchedulerDaemon` as the
`npc-world-tick` task. Each tick selects up to `max_npcs_per_tick` idle NPCs, sends a short context
prompt to the LMStudio `small` model profile, and updates `NPCStateRegistry` with the result. A
`npc_activity` Socket.IO event is emitted so scene UIs refresh without polling.

**Graceful degradation:**
- WorldSim unavailable → uses `npc_scheduler.fallback_npcs` config list.
- LMStudio unavailable → picks randomly from the built-in `ACTIVITY_POOL`.
- No exception ever propagates out of `tick()`.

```python
from engine.agents.npc_scheduler import get_npc_scheduler
scheduler = get_npc_scheduler()
scheduler.start()   # begins periodic ticking (called by SchedulerDaemon)
scheduler.stop()    # graceful shutdown
await scheduler.tick()  # force a single tick (useful for testing)
```

**Config keys:**

| Key | Default | Description |
|-----|---------|-------------|
| `npc.tick_interval` | `60` | Seconds between autonomous ticks |
| `npc_scheduler.max_npcs_per_tick` | `3` | Max NPCs to tick per interval |
| `npc_scheduler.fallback_npcs` | `["lola","viktor","aria"]` | NPCs to use if WorldSim unavailable |

**SchedulerDaemon integration (`npc-world-tick` task):**

```yaml
# config/default.yaml — scheduler section
scheduler:
  tasks:
    npc-world-tick:
      interval: every_1m
      enabled: true
```

The `SchedulerDaemon` calls `get_npc_scheduler().tick()` on this cadence. The task shows up in the
admin overlay **[SCHEDULER]** tab with last-run time and success/error status.

---

### SceneDirector (`engine/director/scene_director.py`)

Schedules narrative beats — timed story events that fire across the active scene lifecycle. Registered
beats can trigger dialogue, faction shifts, economy events, or custom callbacks.

```python
from engine.director.scene_director import get_scene_director
director = get_scene_director()
director.schedule_beat("intro_monologue", delay_seconds=30, scene="bedroom")
director.on_beat("intro_monologue", my_callback)
```

---

## Standard Event Names

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `world.tick` | WorldSim | All scenes (state refresh) |
| `world.time_change` | WorldSim | Scenes with time-gated content |
| `world.weather_change` | WorldSim | Outdoor scenes |
| `npc.activity` | NPCScheduler | Scene UIs (activity badges) |
| `casino.major_win` | Casino | NeonCity (faction +economy) |
| `arena.match_end` | Arena | NeonCity (faction shift), Hub (stats) |
| `heist.completed` | Heist | Hub (economy), Intel Hub (news) |
| `faction.shift` | NeonCity | All faction-aware scenes |

---

## Wiring a Scene

```python
from engine.world.world_state import get_world_state
from engine.events.event_bus import get_event_bus

class MyScene(BaseScene):
    def start(self) -> None:
        ...
        self._world_state = get_world_state()
        self._bus = get_event_bus()
        self._bus.subscribe("world.tick", self._on_world_tick)
        self._bus.subscribe("npc.activity", self._on_npc_activity)

    def _on_world_tick(self, event: dict) -> None:
        time = self._world_state.get_time()
        # update scene state based on time

    def _on_npc_activity(self, event: dict) -> None:
        # event = {"character_id": "lola", "activity": "...", "mood": "happy"}
        self.emit_socket("npc_activity_update", event)
```

---

## Adding New NPC Behaviors

1. **Extend the activity pool** — add entries to `npc_scheduler.activity_pool` in `config/default.yaml`
   for deterministic fallback behavior without LLM calls.

2. **Custom prompt builder** — subclass `NPCScheduler` and override `_build_prompt(npc_id, state)` to
   inject scene-specific context (current faction standings, weather, active arcs).

3. **React to `npc.activity` events** — subscribe in your scene's `start()` and update local UI state.
   The `NPCState` registry is the authoritative source; read it directly for batch queries.

4. **Add a scheduled task** — for behaviors that need a different cadence, register a new task in
   `SchedulerDaemon` rather than overloading `npc-world-tick`.

```python
# Example: custom NPC greeting behavior every 5 minutes
scheduler_daemon.register_task(
    task_id="npc-greetings",
    interval="every_5m",
    callback=my_greeting_tick,
)
```
