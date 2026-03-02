# CosySim Living World System

> Architecture overview for the living world stack — v0.75 "NEON CITY".
> Covers: `WorldSim` · `PlayerState` · `EventCascade` · `neon_city_events.py`

---

## Overview

The Living World system makes Neon City feel alive even when the player is idle. Background
daemons fire economy ticks, NPC actions, faction shifts, and ghost messages on independent
cadences. Each event propagates through a three-tier delivery chain into scene UIs and the
Universal Neon HUD.

### Component Map

```
neon_city_events.py           — 70+ event templates (static data)
        │
        ▼
WorldSim daemon               — fires events on timed intervals
        │         │         │
        ▼         ▼         ▼
  PlayerState  EventBus  Socket.IO
  (credits,    (cross-   (per-scene
   heat, rep)   scene)    push)
        │         │         │
        └────────►▼◄────────┘
               Neon HUD
              (hud_update)
```

---

## Components

### `engine/world/neon_city_events.py` — Event Templates

Static module that defines all named event pools. Import anywhere; no I/O or side effects.

#### Template Sets

| Constant | Count | Description |
|----------|-------|-------------|
| `NPC_ACTIONS_RICH` | 25+ | Freeform NPC activity descriptions |
| `WORLD_EVENTS_RICH` | 20+ | District-level world events |
| `FACTION_EVENTS_RICH` | 6 | One pool per faction (turf wars, power plays) |
| `ECONOMY_EVENTS` | 7 | Market disruptions, supply shifts, windfalls |
| `GHOST_MESSAGES_RICH` | 12 | Dicts with `message`, `intensity`, `heat_impact` |

#### Helper Functions

```python
from engine.world.neon_city_events import get_events_for_scene, get_all_world_events

# Filter NPC_ACTIONS_RICH for relevance to a scene
actions = get_events_for_scene("casino", NPC_ACTIONS_RICH)

# Combined pool of all world + faction events
all_events = get_all_world_events()
```

`get_events_for_scene(scene, event_list)` checks each event's optional `scenes` tag and
returns matching entries, or the full list if no tag is present.

---

### `engine/world/world_sim.py` — WorldSim Daemon

Background daemon started by the launcher. Fires world events on independent timer loops.

#### Tick Intervals

| Task | Interval | Handler |
|------|----------|---------|
| NPC action | 60 s | `_fire_npc_action()` |
| World event | 90 s | `_fire_world_event()` |
| Economy tick | 90 s | `_fire_economy_tick()` |
| Ghost message | 120 s | `_fire_ghost_message()` |
| Faction shift | 300 s | `_fire_faction_shift()` |

```python
from engine.world.world_sim import get_world_sim

sim = get_world_sim()
sim.start()   # starts all daemon threads
sim.stop()    # graceful shutdown
```

#### `_fire_economy_tick()`

1. Selects a random entry from `ECONOMY_EVENTS`.
2. Calls `PlayerState.on_economy_tick(event)` — may adjust credits and reputation.
3. Emits `economy_tick` Socket.IO event to all connected clients.
4. Publishes `world.economy_tick` on the EventBus for cross-scene listeners.

#### `_fire_npc_action()`

1. Selects from `NPC_ACTIONS_RICH` (filtered for active scene if known).
2. Calls `PlayerState.on_faction_shift(faction, delta)` if the action carries faction data.
3. Emits `world_event` Socket.IO event with `{type: "npc_action", description, faction}`.

#### `_fire_ghost_message()`

`GHOST_MESSAGES_RICH` entries are dicts, not strings. WorldSim extracts fields explicitly:

```python
msg = random.choice(GHOST_MESSAGES_RICH)
description  = msg["message"]
intensity    = msg["intensity"]     # "low" | "medium" | "high"
heat_impact  = msg["heat_impact"]   # int delta, e.g. +5
ps.adjust_heat(heat_impact)
emit("ghost_message", {"message": description, "intensity": intensity})
```

---

### `engine/world/player_state.py` — PlayerState Singleton

See [NEON\_HUD.md](./NEON_HUD.md) for full API. From the living-world perspective:

- `on_economy_tick(event)` — called by `_fire_economy_tick()`, adjusts credits/reputation
  based on event type.
- `on_faction_shift(faction, delta)` — called by `_fire_npc_action()` or `_fire_faction_shift()`,
  propagates world-level faction movement into the player's personal standings.
- Every mutating call emits `hud_update` via Socket.IO automatically.

---

### `engine/world/event_cascade.py` — EventCascade

`WorldEventCascade` (introduced v0.73) provides 3-tier fan-out:

```
WorldSim fires event
        │
   Tier 1: EventBus.publish()   — in-process subscribers (scene handlers)
   Tier 2: Socket.IO emit()     — browser clients on all subscribed scenes
   Tier 3: MCP poll queue       — agents that poll /api/world/events
```

Scenes register subscriptions in `DEFAULT_SCENE_SUBSCRIPTIONS`:

```python
DEFAULT_SCENE_SUBSCRIPTIONS = {
    "casino":    ["world.economy_tick", "world.faction_shift"],
    "neoncity":  ["world.tick", "world.faction_shift", "world.npc_action"],
    "phone":     ["world.ghost_message"],
    "bedroom":   ["world.tick"],
    "grid":      ["world.tick", "world.economy_tick", "world.faction_shift",
                  "world.npc_action", "world.ghost_message"],
    # … 10 more scenes
}
```

---

## Event Lifecycle

```
1. WorldSim timer fires (e.g., economy_tick every 90 s)
2. WorldSim calls neon_city_events helper → picks template
3. WorldSim mutates PlayerState (credits, heat, reputation)
4. PlayerState emits Socket.IO `hud_update` to ALL connected browsers
5. WorldSim publishes EventBus event (e.g., "world.economy_tick")
6. EventCascade fan-out:
     a. In-process subscribers (scene._on_economy_tick handlers) called synchronously
     b. Socket.IO `economy_tick` emitted to subscribed scene rooms
     c. Event appended to scene MCP poll queues
7. Scene UI receives `economy_tick` → renders notification in feed
8. HUD strip receives `hud_update` → updates credits/rep/heat glyphs in real time
```

---

## Economy System

### Economy Events (`ECONOMY_EVENTS`)

Seven named economy events fire in rotation:

| Event | Credits delta | Reputation delta | Description |
|-------|--------------|-----------------|-------------|
| `supply_disruption` | −50 to −150 | 0 | Supply chain blocked — prices spike |
| `faction_windfall` | +100 to +300 | +2 | Faction pays out contracts |
| `market_crash` | −200 to −400 | −5 | Exchange volatility wipes portfolios |
| `black_market_surge` | +150 to +250 | −3 | Underground trade boom |
| `corporate_bounty` | +200 | +5 | OmniCorp posts open bounty contract |
| `ghost_dividend` | +50 to +100 | +8 | Ghost\_Net data payload pays out |
| `heat_relief` | 0 | +3 | SynthSec stands down — pressure eases |

Deltas are sampled from ranges at fire time. `PlayerState.on_economy_tick` applies them.

### Economy Tick Interval

Default: **90 seconds** (configurable via `world.economy_tick_interval_seconds`).

### Cross-Scene Effects

| Scene | Economy event handler | Effect |
|-------|-----------------------|--------|
| Casino | `_on_economy_tick` | Adjusts table odds ±5–15 % |
| NeonCity | `_on_economy_tick` | Updates district price index |
| THE GRID | `_on_economy_tick` | Refreshes vendor prices |
| Phone | `_on_economy_tick` | Triggers NEXUS FEED news item |
| Bedroom | `_on_economy_tick` | Updates world status widget |

---

## Faction System

### Standing Scale

```
 −100 ──────────── 0 ──────────── +100
  Hostile          Neutral         Allied
```

Five zones:

| Range | Label |
|-------|-------|
| 80 – 100 | **Champion** — deep bonuses |
| 50 – 79 | **Allied** — faction content unlocked |
| −19 – 49 | **Neutral** |
| −20 – −49 | **Hostile** — reduced access |
| −50 – −100 | **Enemy** — locked out, potential ambush |

### World-Level Faction Shifts

`_fire_faction_shift()` fires every 300 seconds. It selects one of the six factions and
applies a small world-level standing delta (±3 to ±10) to ALL players. This simulates
the faction's global power rising or falling independent of the player's actions.

Scenes that subscribe to `world.faction_shift` can trigger narrative events: faction wars
in NeonCity, VIP access changes in Casino, new intel in BROKER.

---

## Scene Subscriptions

How a scene hooks into the living world:

```python
# content/scenes/my_scene/my_scene.py
from engine.world.event_cascade import get_event_cascade
from engine.world.player_state import get_player_state

class MyScene(BaseScene):
    def start(self) -> None:
        super().start()
        cascade = get_event_cascade()
        cascade.subscribe("world.economy_tick", self._on_economy_tick)
        cascade.subscribe("world.faction_shift", self._on_faction_shift)

    def _on_economy_tick(self, event: dict) -> None:
        # event = {"description": "...", "credits_delta": -50, "reputation_delta": 0}
        self.emit_socket("economy_notification", event)

    def _on_faction_shift(self, event: dict) -> None:
        # event = {"faction": "ghost_net", "delta": +5, "reason": "data_raid"}
        ps = get_player_state()
        ps.on_faction_shift(event["faction"], event["delta"])
```

### World Skills (pack `"world"`)

The 10 world skills in `engine/skills/builtin/world_skills.py` give agents read/write
access to the living world state.

| Skill | Description |
|-------|-------------|
| `get_world_time` | Current game clock (hour, day, weather) |
| `get_world_weather` | Current weather string |
| `get_active_events` | List of recent world events from ring buffer |
| `get_player_state_info` | Full `PlayerState.to_dict()` |
| `get_faction_standings` | Faction standings dict |
| `earn_credits` | Add credits (source: string) |
| `spend_credits` | Spend credits (reason: string), fails gracefully |
| `set_player_location` | Set active\_location |
| `adjust_heat` | Increase or decrease heat |
| `get_recent_sim_events` | Last N events from WorldSim ring buffer |

---

## Adding a New World Event Type

1. Add entries to the appropriate pool in `neon_city_events.py`:

```python
ECONOMY_EVENTS.append({
    "id": "data_heist_payout",
    "description": "Ghost_Net data heist pays out — underground channels flush with credits.",
    "credits_delta": (200, 500),
    "reputation_delta": (-2, 0),
    "faction": "ghost_net",
    "heat_impact": 5,
})
```

2. If it needs a new fire cadence, add a handler in `WorldSim`:

```python
async def _fire_data_heist(self) -> None:
    event = random.choice([e for e in ECONOMY_EVENTS if e["faction"] == "ghost_net"])
    ps = get_player_state()
    ps.earn_credits(random.randint(*event["credits_delta"]), source="data_heist")
    self._emit("economy_tick", event)
    self._bus.publish("world.economy_tick", event)
```

3. Register the timer in `WorldSim.start()`.

4. Subscribe in any scene that should react to it via `EventCascade`.

---

## See Also

- [NEON\_HUD.md](./NEON_HUD.md) — PlayerState API, HUD strip, Socket.IO events
- [THE\_GRID.md](./THE_GRID.md) — Scene with deepest living-world integration
- [WORLD\_SYSTEM.md](./WORLD_SYSTEM.md) — WorldState, NPCScheduler, SceneDirector
- [ECONOMY\_GUIDE.md](./ECONOMY_GUIDE.md) — EconomyManager, cross-scene credits
