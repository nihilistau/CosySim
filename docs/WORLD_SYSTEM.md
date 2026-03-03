# CosySim World System

> Living world infrastructure — CityMap, MissionManager, WorldAnnouncer, WorldSim, WorldState,
> NPCScheduler, NPCState, EventBus, SceneDirector, PlayerState.
> Core system: v0.68 "Dark Renaissance" · NPC autonomy: v0.72b "The Asset Studio"
> Open world layer: v0.82b "THE OPEN WORLD"

---

## Overview

The world system makes CosySim a living simulation. Even when you're not in a scene, the world ticks
forward: factions shift, characters move, time passes, events fire, and NPCs carry on with their lives.

**v0.82b adds the open-world layer:** a persistent city map players traverse between scenes, a full
mission system with lifecycle and rewards, a real-time world announcer fed by the EventBus, and
cross-scene NPC location tracking that makes the city feel populated.

### System Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│  OPEN WORLD LAYER (v0.82b)                                          │
│  CityMap · MissionManager · WorldAnnouncer · City/Mission/Announcer │
│  Skills · Intel Hub CITY PULSE panel                                │
├─────────────────────────────────────────────────────────────────────┤
│  PLAYER LAYER                                                       │
│  PlayerState · InventoryManager · CrewManager                       │
├─────────────────────────────────────────────────────────────────────┤
│  SIMULATION LAYER                                                    │
│  WorldSim · WorldState · EventBus · EventCascade                    │
├─────────────────────────────────────────────────────────────────────┤
│  NPC LAYER                                                          │
│  NPCScheduler · NPCState · SceneDirector · CharacterMemory          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Open World Components (v0.82b)

### CityMap (`engine/world/city_map.py`)

Singleton graph of the entire city. Tracks player location, NPC positions, and provides
BFS pathfinding between nodes. Registered as REST endpoints via `base_scene.register_city_route()`.

```python
from engine.world.city_map import get_city_map, reset_city_map

city = get_city_map()

# Pathfinding
path = city.find_path("hub", "casino")          # ["hub", "neoncity", "casino"]

# Player location
city.travel("neoncity")                          # updates PlayerState.active_location

# NPC tracking
city.set_npc_location("lola", "casino")
loc  = city.get_npc_location("lola")            # "casino"
all_ = city.get_all_npc_locations()             # {"lola": "casino", "viktor": "arena"}

# Test isolation
reset_city_map()
```

#### City Graph

16 nodes across 6 districts, connected by 24 bidirectional edges:

| District | Nodes |
|----------|-------|
| **Downtown** | `hub` (Signal HQ), `intel_hub` (Intel Hub) |
| **Neon Strip** | `neoncity` (Neon City), `casino` (Club Noir), `lounge` (The Lounge) |
| **Tech Quarter** | `grid` (The Grid / Coders), `asset_studio` (Asset Studio) |
| **Underworld** | `heist` (The Score), `arena` (The Colosseum) |
| **Residential** | `bedroom` (The Bedroom), `realm` (The Realm) |
| **Comms** | `phone` (GhostSignal), `coders` (Coder Den), `tavern` (The Tavern), `gallery` (The Gallery) |

Each node carries: `node_id`, `display_name`, `district`, `scene_port`, `description`.
Each edge carries: `travel_cost` (minutes), `energy_cost`, `heat_add`.

#### REST Endpoints

All endpoints registered by `base_scene.register_city_route()`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/city/map` | Full map JSON — nodes, edges, npc_locations, player_location |
| `GET` | `/api/city/node/<node_id>` | Single node details |
| `GET` | `/api/city/path?from=X&to=Y` | BFS path list |
| `GET` | `/api/city/npcs` | All NPC city-map locations |
| `POST` | `/api/city/travel` | Update player location `{"location": "casino"}` |
| `GET` | `/api/city/district/<name>` | All nodes in a district |
| `GET` | `/api/city/nearby?location=X` | Adjacent nodes to X |

#### City Skills Pack (`engine/skills/builtin/city_skills.py`)

Pack name: `"city"` — 8 `@skill` tools:

| Skill | Description |
|-------|-------------|
| `city_get_map` | Returns full city map JSON |
| `city_get_node(node_id)` | Details for a single node |
| `city_find_path(from_node, to_node)` | BFS path as list of node IDs |
| `city_travel(location)` | Move player to location, deducts energy/adds heat |
| `city_get_nearby(location)` | Nodes adjacent to the given location |
| `city_get_npcs` | All NPC city-map positions |
| `city_get_district(name)` | All nodes in a named district |
| `city_map_summary` | Narrative text summary of map state |

---

### MissionManager (`engine/world/mission.py`)

Singleton mission system. Ships 15 builtin missions at first run; custom missions can be created
at runtime. Full lifecycle: `pending → active → completed / failed`.

```python
from engine.world.mission import get_mission_manager, reset_mission_manager

mgr = get_mission_manager()

# Browse
missions = mgr.list_missions(status="pending", type="data_theft")
m = mgr.get_mission("mission_001")

# Lifecycle
mgr.accept_mission("mission_001")
mgr.complete_mission("mission_001", outcome={"bonus": True})
mgr.fail_mission("mission_001", reason="timed out")

# Custom
mgr.create_mission(
    title="Retrieve the Blacklist",
    description="Steal the corporate blacklist from the data vault.",
    type="data_theft",
    rewards={"credits": 2500, "xp": 120, "reputation": 5},
)

# Test isolation
reset_mission_manager()
```

#### Builtin Missions (15)

5 missions per major type:

| Type | Count | Example |
|------|-------|---------|
| `data_theft` | 3 | "Corporate Espionage", "The Blackmail File", "Ghost in the Wire" |
| `extraction` | 3 | "Extract the Asset", "Safe Passage", "Cold Pick-Up" |
| `assassination` | 3 | "Silent Night", "The Severance", "Clean Slate" |
| `sabotage` | 3 | "Burn It Down", "The Signal Jammer", "Cascade Fault" |
| `courier` | 3 | "Dead Drop", "Hot Package", "The Last Mile" |

#### Rewards

Each mission completion applies to `PlayerState`:

| Reward Field | PlayerState Method |
|---|---|
| `credits` | `earn_credits(amount)` |
| `xp` | `add_xp(amount)` |
| `reputation` | `adjust_reputation(delta)` |
| `faction` | `adjust_faction(faction_name, delta)` |

Abandon penalty: `−3 reputation`. Fail penalty: `−difficulty × 3 reputation`.

#### REST Endpoints

All endpoints registered by `base_scene.register_mission_route()`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/missions` | All missions; supports `?status=` and `?type=` filters |
| `GET` | `/api/missions/<id>` | Single mission detail |
| `POST` | `/api/missions/<id>/accept` | Accept a mission |
| `POST` | `/api/missions/<id>/complete` | Complete with `{"outcome": {...}}` |
| `POST` | `/api/missions/<id>/fail` | Fail with `{"reason": "..."}` |
| `POST` | `/api/missions/create` | Create custom mission |
| `GET` | `/api/missions/active` | Active mission list |
| `GET` | `/api/missions/completed` | Completed mission history |
| `GET` | `/api/missions/stats` | Statistics (counts, total rewards earned) |
| `DELETE` | `/api/missions/<id>` | Remove a mission |

#### Mission Skills Pack (`engine/skills/builtin/mission_skills.py`)

Pack name: `"mission"` — 9 `@skill` tools:

| Skill | Description |
|-------|-------------|
| `mission_list(status, type)` | List missions with optional filters |
| `mission_get(mission_id)` | Single mission details |
| `mission_accept(mission_id)` | Accept a pending mission |
| `mission_complete(mission_id, outcome)` | Complete active mission |
| `mission_fail(mission_id, reason)` | Fail active mission |
| `mission_create(title, description, type, rewards)` | Create custom mission |
| `mission_get_active` | All currently active missions |
| `mission_get_stats` | Mission statistics object |
| `mission_summary` | Narrative summary of mission board |

---

### WorldAnnouncer (`engine/world/world_announcer.py`)

EventBus-driven city pulse system. Subscribes to all major event types on startup, maintains
a thread-safe 50-event ring buffer, and emits `city_pulse` Socket.IO events for live UI injection.

```python
from engine.world.world_announcer import get_world_announcer, reset_world_announcer

ann = get_world_announcer()

# Manual push
ann.announce(
    title="Corporate Raid",
    body="Arasaka forces sweep the Tech Quarter.",
    category="faction",
    scene="grid",
    actor="arasaka",
    intensity=2,
)

# Read feed (newest first)
feed = ann.get_feed(limit=20, category="hacker")

# Narrative summary of last 10 events
summary = ann.get_summary()

# Station muting
ann.mute_station("economy")
ann.unmute_station("economy")

# Test isolation
reset_world_announcer()
```

#### EventBus Subscriptions

The announcer subscribes to these event types on `start()`:

| Station | Event Types | Badge Color |
|---------|-------------|-------------|
| `npc` | `npc.*` | Purple |
| `faction` | `faction.*` | Red |
| `world` | `world.*` | Blue |
| `hacker` | `hacker.*` | Green |
| `economy` | `economy.*`, `casino.*` | Gold |
| `all` | Master mute — silences all stations | — |

#### Ring Buffer

- 50-event capacity (oldest discarded when full)
- Thread-safe via `threading.Lock`
- Each entry: `{id, title, body, category, scene, actor, intensity, timestamp}`
- `get_feed(limit, category)` — optional category filter, newest first
- `get_summary()` — Jinja-style narrative of last 10 events

#### Socket.IO Integration

On every new announcement, emits `city_pulse` event:

```json
{
  "id": "ann_1712345678_003",
  "title": "Corporate Raid",
  "body": "Arasaka forces sweep the Tech Quarter.",
  "category": "faction",
  "scene": "grid",
  "actor": "arasaka",
  "intensity": 2,
  "timestamp": "2026-03-15T22:14:03Z"
}
```

#### REST Endpoints

Registered by `base_scene.register_world_events_route()`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/world/events?limit=50&category=&scene=` | Ring buffer + announcer feed |
| `GET` | `/api/world/events/summary` | Narrative summary of last 10 events |
| `GET` | `/api/world/npc_locations` | All NPC city-map locations |

#### Announcer Skills Pack (`engine/skills/builtin/announcer_skills.py`)

Pack name: `"announcer"` — 5 `@skill` tools:

| Skill | Description |
|-------|-------------|
| `announcer_get_feed(limit, category)` | City pulse feed, newest first |
| `announcer_announce(title, body, category, scene, actor)` | Manual push to announcer |
| `world_event_summary` | Narrative of last 10 world events |
| `world_get_recent_events(limit, scene)` | Raw WorldSim events (unfiltered) |
| `announcer_set_station(station, muted)` | Mute or unmute a station |

---

### Cross-Scene NPC Tracking (`engine/agents/npc_scheduler.py`)

`NPCScheduler` calls `_track_npc_in_city_map()` on every tick, after each NPC activity is generated.
This keeps the city map NPC positions current at all times.

```python
# Internal method — called automatically after each npc tick
def _track_npc_in_city_map(self, char_id: str, location: str) -> None:
    if not location:
        return
    city = get_city_map()
    previous = city.get_npc_location(char_id)
    city.set_npc_location(char_id, location)
    if location != previous:
        get_framework().emit("npc_location", {
            "character_id": char_id,
            "location": location,
            "previous_location": previous,
        })
```

The `npc_location` Socket.IO event fires **only when the location changes**, keeping network
traffic minimal. Scene UIs listen for this event to update city map overlays without polling.

---

### PlayerState Extensions (`engine/world/player_state.py`)

New methods added in v0.82b:

| Method | Description |
|--------|-------------|
| `spend_energy(amount)` | Deduct energy; floors at 0 |
| `add_heat(amount)` | Add heat score; clamps to `[0, 100]` |
| `adjust_reputation(delta)` | Adjust reputation; clamps to `[0, 100]` |
| `adjust_faction(faction_name, delta)` | Adjust standing for a named faction |
| `add_xp(amount)` | Add XP; every 500 XP boundary triggers a random skill level-up (max 5) |
| `active_location` *(property)* | Read/write current city node ID |

```python
from engine.world.player_state import get_player_state

ps = get_player_state()
ps.spend_energy(10)
ps.add_heat(5)
ps.adjust_reputation(+3)
ps.adjust_faction("arasaka", -10)
ps.add_xp(200)
print(ps.active_location)   # "casino"
ps.active_location = "hub"
```

---

### Intel Hub CITY PULSE Panel

Full-width panel added to the Intel Hub scene (`grid-column: 1 / -1`).

**Features:**
- Category filter buttons: `ALL | NPC | FACTION | WORLD | HACKER | ECONOMY`
- Polls `/api/world/events` every 30 seconds for catchup
- Socket.IO `city_pulse` live injection — new events **prepend instantly**, no poll lag
- Each entry renders:
  - Relative timestamp (`2 min ago`)
  - Color-coded category badge
  - Event title (bold)
  - Body description
  - Scene tag (italic, muted)

**Category badge colors:**

| Category | Color |
|----------|-------|
| `npc` | `#9b59b6` (purple) |
| `faction` | `#e74c3c` (red) |
| `world` | `#3498db` (blue) |
| `hacker` | `#2ecc71` (green) |
| `economy` | `#f39c12` (gold) |

---

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

---

## Related Documentation

- [SKILLS.md](./SKILLS.md) — `@skill` decorator, pack registration
- [ARCHITECTURE.md](./ARCHITECTURE.md) — BaseScene, MCP pipeline, interceptor chain
- [MCP_FRAMEWORK.md](./MCP_FRAMEWORK.md) — full MCP system deep dive
- [CHARACTERS.md](./CHARACTERS.md) — NPCState, CharacterMemory, relationship system
- [CONFIGURATION.md](./CONFIGURATION.md) — `world.*`, `npc.*`, `npc_scheduler.*` config keys
