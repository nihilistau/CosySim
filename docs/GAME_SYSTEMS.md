# CosySim Game Systems Reference

> CosySim Documentation — v1.52.0 [2026-03-26]
>
> Covers: WorldSim · WorldState · PlayerState · EventCascade · Economy · Factions · NPCs · Events · Inventory.
> Living world simulation with 32 launch targets, 6 factions, and threaded daemons that keep
> the city alive even when the player is idle.

All systems use `threading.RLock` for thread safety and the singleton pattern for global access.

---

## Overview

The game systems make CosySim a living simulation. Even when the player is idle, the world
ticks forward: factions shift, characters move, time passes, events fire, NPCs carry on with
their lives, and the economy fluctuates. Background daemons fire economy ticks, NPC actions,
faction shifts, and ghost messages on independent cadences. Each event propagates through a
three-tier delivery chain into scene UIs and the Universal Neon HUD.

### System Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│  OPEN WORLD LAYER                                                    │
│  CityMap · MissionManager · WorldAnnouncer · City/Mission/Announcer │
│  Skills · Intel Hub CITY PULSE panel                                │
├─────────────────────────────────────────────────────────────────────┤
│  PLAYER LAYER                                                        │
│  PlayerState · InventoryManager · CrewManager · SkillProgression     │
├─────────────────────────────────────────────────────────────────────┤
│  SIMULATION LAYER                                                    │
│  WorldSim · WorldState · EventBus · EventCascade                    │
├─────────────────────────────────────────────────────────────────────┤
│  NPC LAYER                                                          │
│  NPCScheduler · NPCState · SceneDirector · CharacterMemory          │
│  Neurochemistry · NPC Routines                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Event Delivery Chain

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

## WorldSim

### WorldState (`engine/world/world_state.py`)

Game clock (1 real min = 1 game hour). Tracks weather, time-of-day, and NPC daily schedules.

```python
from engine.world.world_state import get_world_state
ws = get_world_state()
time = ws.get_time()        # WorldTime(hour=14, day=3, weather=Weather.RAIN)
ws.tick(minutes=5)          # advance by 5 real minutes = 5 game hours
```

Config key: `world.sim_enabled` (bool, default `true`) — set to `false` to freeze time.

### WorldSim Daemon (`engine/world/world_sim.py`)

Background daemon thread. Fires world events on independent timer loops and broadcasts via
EventBus. Started by the launcher once all scenes are running.

```python
from engine.world.world_sim import get_world_sim
sim = get_world_sim()
sim.start()   # start daemon (called by launcher after scenes start)
sim.stop()    # graceful shutdown
```

Config key: `world.tick_interval_seconds` (int, default `60`).

#### Tick Intervals

| Task | Interval | Handler |
|------|----------|---------|
| NPC action | 60 s | `_fire_npc_action()` |
| World event | 90 s | `_fire_world_event()` |
| Economy tick | 90 s | `_fire_economy_tick()` |
| Ghost message | 120 s | `_fire_ghost_message()` |
| Faction shift | 300 s | `_fire_faction_shift()` |

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

`GHOST_MESSAGES_RICH` entries are dicts with `message`, `intensity`, and `heat_impact` fields:

```python
msg = random.choice(GHOST_MESSAGES_RICH)
description  = msg["message"]
intensity    = msg["intensity"]     # "low" | "medium" | "high"
heat_impact  = msg["heat_impact"]   # int delta, e.g. +5
ps.adjust_heat(heat_impact)
emit("ghost_message", {"message": description, "intensity": intensity})
```

### EventBus (`engine/events/event_bus.py`)

Thread-safe in-process pub/sub backbone. Carries cross-scene events and persists significant
events to Nexus history for post-session analysis.

```python
from engine.events.event_bus import get_event_bus
bus = get_event_bus()
bus.subscribe("casino.major_win", my_handler)
bus.publish("casino.major_win", {"player": "lola", "amount": 500})
```

### EventCascade (`engine/world/event_cascade.py`)

`WorldEventCascade` provides 3-tier fan-out for every world event:

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
    "penthouse": ["world.tick"],
    "grid":      ["world.tick", "world.economy_tick", "world.faction_shift",
                  "world.npc_action", "world.ghost_message"],
    # ... additional scenes
}
```

### Event Templates (`engine/world/neon_city_events.py`)

Static module defining all named event pools. Import anywhere; no I/O or side effects.

| Constant | Count | Description |
|----------|-------|-------------|
| `NPC_ACTIONS_RICH` | 25+ | Freeform NPC activity descriptions |
| `WORLD_EVENTS_RICH` | 20+ | District-level world events |
| `FACTION_EVENTS_RICH` | 6 | One pool per faction (turf wars, power plays) |
| `ECONOMY_EVENTS` | 7 | Market disruptions, supply shifts, windfalls |
| `GHOST_MESSAGES_RICH` | 12 | Dicts with `message`, `intensity`, `heat_impact` |

```python
from engine.world.neon_city_events import get_events_for_scene, get_all_world_events

actions = get_events_for_scene("casino", NPC_ACTIONS_RICH)
all_events = get_all_world_events()
```

### Weather System

Markov chain with 5 states:
Clear -> Overcast -> Rain -> Acid Rain -> Storm -> Clear

Weather affects NPC behavior, market prices, and visibility.

### Standard Event Names

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

### Event Lifecycle

```
1. WorldSim timer fires (e.g., economy_tick every 90 s)
2. WorldSim calls neon_city_events helper -> picks template
3. WorldSim mutates PlayerState (credits, heat, reputation)
4. PlayerState emits Socket.IO `hud_update` to ALL connected browsers
5. WorldSim publishes EventBus event (e.g., "world.economy_tick")
6. EventCascade fan-out:
     a. In-process subscribers (scene._on_economy_tick handlers) called synchronously
     b. Socket.IO `economy_tick` emitted to subscribed scene rooms
     c. Event appended to scene MCP poll queues
7. Scene UI receives `economy_tick` -> renders notification in feed
8. HUD strip receives `hud_update` -> updates credits/rep/heat glyphs in real time
```

### World Skills (pack `"world"`)

10 skills in `engine/skills/builtin/world_skills.py`:

| Skill | Description |
|-------|-------------|
| `get_world_time` | Current game clock (hour, day, weather) |
| `get_world_weather` | Current weather string |
| `get_active_events` | List of recent world events from ring buffer |
| `get_player_state_info` | Full `PlayerState.to_dict()` |
| `get_faction_standings` | Faction standings dict |
| `earn_credits` | Add credits (source: string) |
| `spend_credits` | Spend credits (reason: string), fails gracefully |
| `set_player_location` | Set active_location |
| `adjust_heat` | Increase or decrease heat |
| `get_recent_sim_events` | Last N events from WorldSim ring buffer |

### Wiring a Scene

```python
from engine.world.event_cascade import get_event_cascade
from engine.world.player_state import get_player_state
from engine.world.world_state import get_world_state
from engine.events.event_bus import get_event_bus

class MyScene(BaseScene):
    def start(self) -> None:
        super().start()
        cascade = get_event_cascade()
        cascade.subscribe("world.economy_tick", self._on_economy_tick)
        cascade.subscribe("world.faction_shift", self._on_faction_shift)

        self._world_state = get_world_state()
        self._bus = get_event_bus()
        self._bus.subscribe("world.tick", self._on_world_tick)
        self._bus.subscribe("npc.activity", self._on_npc_activity)

    def _on_economy_tick(self, event: dict) -> None:
        # event = {"description": "...", "credits_delta": -50, "reputation_delta": 0}
        self.emit_socket("economy_notification", event)

    def _on_faction_shift(self, event: dict) -> None:
        # event = {"faction": "ghost_net", "delta": +5, "reason": "data_raid"}
        ps = get_player_state()
        ps.on_faction_shift(event["faction"], event["delta"])

    def _on_world_tick(self, event: dict) -> None:
        time = self._world_state.get_time()

    def _on_npc_activity(self, event: dict) -> None:
        # event = {"character_id": "lola", "activity": "...", "mood": "happy"}
        self.emit_socket("npc_activity_update", event)
```

### Adding a New World Event Type

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

2. If it needs a new fire cadence, add a handler in `WorldSim`.
3. Register the timer in `WorldSim.start()`.
4. Subscribe in any scene that should react to it via `EventCascade`.

---

## Economy

### Economy Events (`ECONOMY_EVENTS`)

Seven named economy events fire in rotation:

| Event | Credits delta | Reputation delta | Description |
|-------|--------------|-----------------|-------------|
| `supply_disruption` | -50 to -150 | 0 | Supply chain blocked — prices spike |
| `faction_windfall` | +100 to +300 | +2 | Faction pays out contracts |
| `market_crash` | -200 to -400 | -5 | Exchange volatility wipes portfolios |
| `black_market_surge` | +150 to +250 | -3 | Underground trade boom |
| `corporate_bounty` | +200 | +5 | OmniCorp posts open bounty contract |
| `ghost_dividend` | +50 to +100 | +8 | Ghost_Net data payload pays out |
| `heat_relief` | 0 | +3 | SynthSec stands down — pressure eases |

Deltas are sampled from ranges at fire time. `PlayerState.on_economy_tick` applies them.

Economy tick interval: **90 seconds** (configurable via `world.economy_tick_interval_seconds`).

### Market System

**Module:** `engine/world/market.py`

30 goods across 8 categories with supply/demand pricing:

| Category | Examples |
|----------|----------|
| Weapons | Pistol, SMG, Sniper Rifle |
| Cyberware | Neural Interface, Reflex Booster |
| Consumables | Stim Pack, Med Kit |
| Data | Encrypted Files, Access Codes |

12 shops located across districts. Prices affected by:
- Supply and demand
- Territory control multipliers
- Random market events
- Player bulk purchases

### Cross-Scene Economy Effects

| Scene | Economy event handler | Effect |
|-------|-----------------------|--------|
| Casino | `_on_economy_tick` | Adjusts table odds +/-5-15 % |
| NeonCity | `_on_economy_tick` | Updates district price index |
| THE GRID | `_on_economy_tick` | Refreshes vendor prices |
| Phone | `_on_economy_tick` | Triggers NEXUS FEED news item |
| Penthouse | `_on_economy_tick` | Updates world status widget |

### PlayerState (`engine/world/player_state.py`)

Singleton tracking credits, heat, reputation, faction standings, health, hunger, energy, XP, and location.

```python
from engine.world.player_state import get_player_state

ps = get_player_state()
ps.earn_credits(500, source="heist")
ps.spend_energy(10)
ps.add_heat(5)
ps.adjust_reputation(+3)
ps.adjust_faction("arasaka", -10)
ps.add_xp(200)                     # every 500 XP boundary triggers random skill level-up (max 5)
print(ps.active_location)          # "casino"
ps.active_location = "hub"
```

Key methods:

| Method | Description |
|--------|-------------|
| `on_economy_tick(event)` | Adjusts credits/reputation based on economy event |
| `on_faction_shift(faction, delta)` | Propagates world-level faction movement into personal standings |
| `spend_energy(amount)` | Deduct energy; floors at 0 |
| `add_heat(amount)` | Add heat score; clamps to `[0, 100]` |
| `adjust_reputation(delta)` | Adjust reputation; clamps to `[0, 100]` |
| `adjust_faction(faction_name, delta)` | Adjust standing for a named faction |
| `add_xp(amount)` | Add XP with auto skill level-up |
| `active_location` *(property)* | Read/write current city node ID |

Every mutating call emits `hud_update` via Socket.IO automatically.

---

## Factions

### Faction AI (`engine/world/faction_ai.py`)

6 factions with personality-driven decision making:

| Faction | Personality | Territory |
|---------|------------|-----------|
| OmniCorp | Corporate, methodical | Downtown |
| Yakuza | Traditional, honor-bound | Neon District |
| Iron Syndicate | Industrial, brute force | Industrial Zone |
| Ghost Net | Tech-savvy, decentralized | The Grid |
| Street Kings | Aggressive, territorial | Lower sectors |
| The Collective | Idealistic, grassroots | Various |

Each faction makes 1 strategic decision per 5 ticks: expand, fortify, negotiate, attack,
recruit, or withdraw.

### Standing Scale

```
 -100 ──────────── 0 ──────────── +100
  Hostile          Neutral         Allied
```

Five zones:

| Range | Label |
|-------|-------|
| 80 - 100 | **Champion** — deep bonuses |
| 50 - 79 | **Allied** — faction content unlocked |
| -19 - 49 | **Neutral** |
| -20 - -49 | **Hostile** — reduced access |
| -50 - -100 | **Enemy** — locked out, potential ambush |

### World-Level Faction Shifts

`_fire_faction_shift()` fires every 300 seconds. It selects one of the six factions and
applies a small world-level standing delta (+/-3 to +/-10) to ALL players. This simulates
the faction's global power rising or falling independent of the player's actions.

Scenes that subscribe to `world.faction_shift` can trigger narrative events: faction wars
in NeonCity, VIP access changes in Casino, new intel in BROKER.

### Territory System (`engine/world/territory.py`)

**Skills:** `engine/skills/builtin/territory_skills.py` (14 skills)

16 districts with faction control percentages (sum to 100%):

| District | Type | Key Faction |
|----------|------|-------------|
| Downtown | Commercial | OmniCorp |
| Neon District | Entertainment | Yakuza |
| Industrial Zone | Manufacturing | Iron Syndicate |
| Port District | Shipping | Triads |

#### Crew HQ

Players establish a headquarters in one district with 5 room types:
- **Barracks** — Crew capacity
- **Armory** — Weapon storage, upgrades
- **Lab** — Cyberware research
- **Vault** — Credits storage
- **Comms** — Intelligence gathering

#### Territory Missions

- **Capture** — Seize territory from a faction
- **Defend** — Protect controlled territory
- **Sabotage** — Weaken enemy faction presence
- **Recon** — Gather intelligence

---

## NPCs

### NPCState (`engine/world/npc_state.py`)

Thread-safe registry of per-NPC runtime state.

```python
from engine.world.npc_state import get_npc_state_registry, NPCState
registry = get_npc_state_registry()

state: NPCState = registry.get("lola")
print(state.activity)       # "browsing nearby goods"
print(state.location)       # "The Velvet Pit"

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
| `mood` | str | Emotional tone (`neutral`, `happy`, `tense`, ...) |
| `is_busy` | bool | True while NPC has an active scheduled activity |

### NPCScheduler (`engine/agents/npc_scheduler.py`)

Drives autonomous NPC activity via a periodic tick loop integrated with `SchedulerDaemon` as the
`npc-world-tick` task. Each tick selects up to `max_npcs_per_tick` idle NPCs, sends a short context
prompt to the LMStudio `small` model profile, and updates `NPCStateRegistry` with the result. A
`npc_activity` Socket.IO event is emitted so scene UIs refresh without polling.

```python
from engine.agents.npc_scheduler import get_npc_scheduler
scheduler = get_npc_scheduler()
scheduler.start()
scheduler.stop()
await scheduler.tick()  # force a single tick (useful for testing)
```

**Graceful degradation:**
- WorldSim unavailable -> uses `npc_scheduler.fallback_npcs` config list.
- LMStudio unavailable -> picks randomly from the built-in `ACTIVITY_POOL`.
- No exception ever propagates out of `tick()`.

**Config keys:**

| Key | Default | Description |
|-----|---------|-------------|
| `npc.tick_interval` | `60` | Seconds between autonomous ticks |
| `npc_scheduler.max_npcs_per_tick` | `3` | Max NPCs to tick per interval |
| `npc_scheduler.fallback_npcs` | `["lola","viktor","aria"]` | NPCs to use if WorldSim unavailable |

**SchedulerDaemon integration:**

```yaml
# config/default.yaml
scheduler:
  tasks:
    npc-world-tick:
      interval: every_1m
      enabled: true
```

#### Cross-Scene NPC Tracking

`NPCScheduler` calls `_track_npc_in_city_map()` on every tick, keeping city map NPC
positions current. The `npc_location` Socket.IO event fires only when the location changes.

```python
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

### NPC Routines (`engine/world/npc_routines.py`)

9 archetypes with time-based location schedules:
- **Worker** — Factory by day, bar by night
- **Criminal** — Streets at night, hideout by day
- **Vendor** — Shop during business hours
- **Guard** — Patrol routes, shift changes
- **Fixer** — Various meeting locations

NPCs can be interrupted from routines and will resume afterward.

### Character Neurochemistry (`engine/characters/neurochemistry.py`)

**Skills:** `engine/skills/builtin/neurochemistry_skills.py` (3 skills)
**Config:** `config/default.yaml` -> `neurochemistry:`

Every NPC has 6 neurotransmitters (0.0-1.0) that drive their emotional state:

| Neurotransmitter | Role |
|-----------------|------|
| Dopamine | Pleasure, reward, motivation |
| Serotonin | Mood stability, well-being |
| Oxytocin | Trust, bonding, social connection |
| Cortisol | Stress, anxiety, fear |
| Adrenaline | Excitement, fight-or-flight |
| Endorphins | Pain relief, euphoria |

**Derived emotions** from neurotransmitter combinations:
- **Happy**: high dopamine + high serotonin
- **Anxious**: high cortisol + low serotonin
- **Trusting**: high oxytocin + low cortisol
- **Excited**: high adrenaline + high dopamine

**30+ stimuli** mapped to neurotransmitter deltas (e.g., `compliment` -> dopamine +0.15,
serotonin +0.1, oxytocin +0.05).

```python
from engine.characters.neurochemistry import get_neurochemistry_engine

engine = get_neurochemistry_engine()
engine.apply_stimulus("npc_lola", "compliment")
state = engine.get_state("npc_lola")
# -> {dopamine: 0.65, serotonin: 0.6, ..., emotions: ["happy", "trusting"]}
```

**MCP Skills:** `check_mood`, `stimulate`, `read_neurochem`

### SceneDirector (`engine/director/scene_director.py`)

Schedules narrative beats — timed story events that fire across the active scene lifecycle.

```python
from engine.director.scene_director import get_scene_director
director = get_scene_director()
director.schedule_beat("intro_monologue", delay_seconds=30, scene="penthouse")
director.on_beat("intro_monologue", my_callback)
```

### Adding New NPC Behaviors

1. **Extend the activity pool** — add entries to `npc_scheduler.activity_pool` in `config/default.yaml`.
2. **Custom prompt builder** — subclass `NPCScheduler` and override `_build_prompt(npc_id, state)`.
3. **React to `npc.activity` events** — subscribe in your scene's `start()`.
4. **Add a scheduled task** — register a new task in `SchedulerDaemon` for different cadences.

---

## Events

### World Events

10 stochastic event templates with 20% spawn rate per tick:
- Power outage in district
- Gang shootout
- Corporate raid
- Data leak
- Street festival

### WorldAnnouncer (`engine/world/world_announcer.py`)

EventBus-driven city pulse system. Subscribes to all major event types on startup, maintains
a thread-safe 50-event ring buffer, and emits `city_pulse` Socket.IO events.

```python
from engine.world.world_announcer import get_world_announcer, reset_world_announcer

ann = get_world_announcer()
ann.announce(
    title="Corporate Raid",
    body="Arasaka forces sweep the Tech Quarter.",
    category="faction",
    scene="grid",
    actor="arasaka",
    intensity=2,
)

feed = ann.get_feed(limit=20, category="hacker")
summary = ann.get_summary()
ann.mute_station("economy")
ann.unmute_station("economy")
```

**EventBus subscriptions:**

| Station | Event Types | Badge Color |
|---------|-------------|-------------|
| `npc` | `npc.*` | Purple |
| `faction` | `faction.*` | Red |
| `world` | `world.*` | Blue |
| `hacker` | `hacker.*` | Green |
| `economy` | `economy.*`, `casino.*` | Gold |
| `all` | Master mute — silences all stations | -- |

**Ring buffer:** 50-event capacity, thread-safe, each entry has
`{id, title, body, category, scene, actor, intensity, timestamp}`.

**Socket.IO:** emits `city_pulse` on every new announcement.

**REST endpoints** (registered by `base_scene.register_world_events_route()`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/world/events?limit=50&category=&scene=` | Ring buffer + announcer feed |
| `GET` | `/api/world/events/summary` | Narrative summary of last 10 events |
| `GET` | `/api/world/npc_locations` | All NPC city-map locations |

**Announcer Skills** (pack `"announcer"`, 5 skills):
`announcer_get_feed`, `announcer_announce`, `world_event_summary`,
`world_get_recent_events`, `announcer_set_station`

### In-Game World News

**Modules:** `engine/world/news_generator.py`, `engine/world/news_ticker.py`
**Skills:** `engine/skills/builtin/world_news_skills.py` (10 skills)
**Frontend:** `cosysim-news-ticker.css` + `cosysim-news-ticker.js`

`WorldNewsGenerator` subscribes to 8 EventBus event types and transforms game events into
cyberpunk-themed news articles with 50+ headline/body templates across 8 categories. Articles
include headline, body, category, severity (1-5), related factions/districts/NPCs, byline
(10 fictional journalists), and fingerprint dedup (120s window).

**News Ticker:** bottom-of-screen crawling ticker visible in every scene. Horizontally-scrolling
headlines with category color tags, breaking news flash for severity 5. Auto-fetches from
`/api/news/ticker` every 30s, with Socket.IO live updates.

**API endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/news/ticker` | GET | Formatted ticker items |
| `/api/news/headlines` | GET | Latest headlines (limit param) |
| `/api/news/article/<id>` | GET | Full article detail |
| `/api/news/breaking` | GET | High-severity articles only |
| `/api/news/search?q=` | GET | Full-text search |
| `/api/news/digest` | GET | Editorial summary |
| `/api/news/stats` | GET | Generator/ticker statistics |

**MCP Skills:** `latest_headlines`, `read_article`, `search_world_news`, `breaking_news`,
`ticker_feed`, `news_about_faction`, `news_about_district`, `editorial_digest`, `news_stats`,
`news_by_category`

### Intel Hub CITY PULSE Panel

Full-width panel in the Intel Hub scene with category filter buttons
(ALL | NPC | FACTION | WORLD | HACKER | ECONOMY), polling `/api/world/events` every 30s
with Socket.IO `city_pulse` live injection.

Category badge colors: npc=#9b59b6, faction=#e74c3c, world=#3498db, hacker=#2ecc71, economy=#f39c12.

---

## Inventory & Missions

### CityMap (`engine/world/city_map.py`)

Singleton graph of the entire city. Tracks player location, NPC positions, and provides
BFS pathfinding between nodes.

```python
from engine.world.city_map import get_city_map, reset_city_map

city = get_city_map()
path = city.find_path("hub", "casino")          # ["hub", "neoncity", "casino"]
city.travel("neoncity")                          # updates PlayerState.active_location
city.set_npc_location("lola", "casino")
loc  = city.get_npc_location("lola")            # "casino"
```

**City graph:** 16 nodes across 6 districts, connected by 24 bidirectional edges:

| District | Nodes |
|----------|-------|
| **Downtown** | `hub` (Signal HQ), `intel_hub` (Intel Hub) |
| **Neon Strip** | `neoncity` (Neon City), `casino` (Club Noir), `lounge` (The Lounge) |
| **Tech Quarter** | `grid` (The Grid / Coders), `asset_studio` (Asset Studio) |
| **Underworld** | `heist` (The Score), `arena` (The Colosseum) |
| **Residential** | `penthouse` (The Penthouse), `realm` (The Realm) |
| **Comms** | `phone` (GhostSignal), `coders` (Coder Den), `tavern` (The Tavern), `gallery` (The Gallery) |

Each node carries: `node_id`, `display_name`, `district`, `scene_port`, `description`.
Each edge carries: `travel_cost` (minutes), `energy_cost`, `heat_add`.

**REST endpoints** (registered by `base_scene.register_city_route()`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/city/map` | Full map JSON |
| `GET` | `/api/city/node/<node_id>` | Single node details |
| `GET` | `/api/city/path?from=X&to=Y` | BFS path list |
| `GET` | `/api/city/npcs` | All NPC city-map locations |
| `POST` | `/api/city/travel` | Update player location |
| `GET` | `/api/city/district/<name>` | All nodes in a district |
| `GET` | `/api/city/nearby?location=X` | Adjacent nodes |

**City Skills** (pack `"city"`, 8 skills):
`city_get_map`, `city_get_node`, `city_find_path`, `city_travel`, `city_get_nearby`,
`city_get_npcs`, `city_get_district`, `city_map_summary`

### MissionManager (`engine/world/mission.py`)

Singleton mission system. Ships 15 builtin missions; custom missions can be created at runtime.
Full lifecycle: `pending -> active -> completed / failed`.

```python
from engine.world.mission import get_mission_manager, reset_mission_manager

mgr = get_mission_manager()
missions = mgr.list_missions(status="pending", type="data_theft")
mgr.accept_mission("mission_001")
mgr.complete_mission("mission_001", outcome={"bonus": True})
mgr.fail_mission("mission_001", reason="timed out")
mgr.create_mission(
    title="Retrieve the Blacklist",
    description="Steal the corporate blacklist from the data vault.",
    type="data_theft",
    rewards={"credits": 2500, "xp": 120, "reputation": 5},
)
```

**Builtin missions** (5 per type):

| Type | Examples |
|------|---------|
| `data_theft` | "Corporate Espionage", "The Blackmail File", "Ghost in the Wire" |
| `extraction` | "Extract the Asset", "Safe Passage", "Cold Pick-Up" |
| `assassination` | "Silent Night", "The Severance", "Clean Slate" |
| `sabotage` | "Burn It Down", "The Signal Jammer", "Cascade Fault" |
| `courier` | "Dead Drop", "Hot Package", "The Last Mile" |

**Rewards** apply to PlayerState: `credits` -> `earn_credits()`, `xp` -> `add_xp()`,
`reputation` -> `adjust_reputation()`, `faction` -> `adjust_faction()`.
Abandon penalty: -3 reputation. Fail penalty: -difficulty x 3 reputation.

**REST endpoints** (registered by `base_scene.register_mission_route()`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/missions` | All missions; supports `?status=` and `?type=` filters |
| `GET` | `/api/missions/<id>` | Single mission detail |
| `POST` | `/api/missions/<id>/accept` | Accept a mission |
| `POST` | `/api/missions/<id>/complete` | Complete with outcome |
| `POST` | `/api/missions/<id>/fail` | Fail with reason |
| `POST` | `/api/missions/create` | Create custom mission |
| `GET` | `/api/missions/active` | Active mission list |
| `GET` | `/api/missions/completed` | Completed mission history |
| `GET` | `/api/missions/stats` | Statistics |
| `DELETE` | `/api/missions/<id>` | Remove a mission |

**Mission Skills** (pack `"mission"`, 9 skills):
`mission_list`, `mission_get`, `mission_accept`, `mission_complete`, `mission_fail`,
`mission_create`, `mission_get_active`, `mission_get_stats`, `mission_summary`

### Skill Progression (`engine/world/skill_progression.py`)

**Skills:** `engine/skills/builtin/progression_skills.py` (3 skills)

8 player skills with use-based XP (diminishing returns):

| Skill | Description |
|-------|-------------|
| Hacking | ICE breaking, network intrusion |
| Combat | Physical/ranged combat |
| Stealth | Sneaking, lockpicking |
| Charisma | Persuasion, negotiation |
| Engineering | Hardware, cyberware |
| Medicine | Healing, chemistry |
| Streetwise | Underground contacts, navigation |
| Leadership | Crew management, morale |

**Level thresholds:**

| Level | XP Required | Title |
|-------|-------------|-------|
| 0 | 0 | Novice |
| 1 | 100 | Apprentice |
| 2 | 300 | Journeyman |
| 3 | 600 | Expert |
| 4 | 1000 | Master |
| 5 | 2000 | Legendary |

**Skill checks:** Roll vs difficulty + skill level + modifiers:
```python
result = progression.skill_check("player_1", "hacking", difficulty=3)
# -> {success: True, roll: 14, threshold: 12, margin: 2}
```

**MCP Skills:** `check_skill`, `attempt_action`, `view_xp`

### Cyberspace Hacking (`engine/world/cyberspace.py`)

**Skills:** `engine/skills/builtin/cyberspace_skills.py` (15 skills)
**Tests:** `tests/test_cyberspace.py` (115 tests)

Each target system is a graph of nodes: Access Points, Data Stores, CPU Nodes, ICE Nodes.

**ICE types:**

| ICE | Effect | Break Method |
|-----|--------|--------------|
| Barrier | Blocks path | Icebreaker program |
| Trace | Alerts security | Cloak program |
| Black ICE | Damages hacker | High-power icebreaker |
| Data Wall | Encrypts data | Siphon program |
| Honeypot | Traps hacker | Detection skill check |

**Programs:**

| Program | Slots | Effect |
|---------|-------|--------|
| Icebreaker | 2 | Breaks ICE barriers |
| Cloak | 1 | Hides from trace programs |
| Siphon | 2 | Extracts data from nodes |
| Virus | 3 | Disables node functions |
| Backdoor | 1 | Creates persistent access |

**Cyberdeck hardware:** RAM (concurrent programs), CPU (ICE-breaking speed), Slots (program capacity).

**MCP Skills:** `hack_connect`, `hack_move`, `hack_break_ice`, `hack_run_program`,
`hack_extract_data`, `hack_scan_node`, `hack_install_backdoor`, `cyberdeck_status`,
`cyberdeck_upgrade`, etc.

### Onboarding Quest System (`engine/world/onboarding.py`)

**Skills:** `engine/skills/builtin/onboarding_skills.py` (12 skills)
**Tests:** `tests/test_onboarding.py` (83 tests)

7 sequential quests introducing new players:

| # | Quest | Introduction |
|---|-------|-------------|
| 1 | First Contact | Phone system, encrypted messages |
| 2 | Street Smarts | Navigation, district exploration |
| 3 | Making Contacts | NPC interaction, The Rusty Anchor |
| 4 | First Score | Basic hacking, The Grid |
| 5 | Building Rep | Faction reputation, missions |
| 6 | Crew Assembly | First crew recruitment |
| 7 | Welcome to NeonCity | Full access unlocked |

### Multiplayer Foundation

**Modules:** `engine/multiplayer/session_manager.py`, `presence.py`, `messaging.py`, `leaderboards.py`
**Skills:** `engine/skills/builtin/multiplayer_skills.py` (12 skills)

- **Session Management** — `PlayerSession` with unique ID, heartbeat/timeout (60s), per-session state isolation
- **Presence** — Real-time online/away/busy tracking, scene occupancy, auto-cleanup
- **Messaging** — P2P direct messages with read/unread, threading, pagination
- **Leaderboards** — 6 categories (Credits, Reputation, Kills, Heists, Hacking, Territory), weekly + all-time

---

## Threading Safety

**Critical pattern**: All manager classes use `threading.RLock()` (reentrant lock), NOT `threading.Lock()`.

**Why**: Manager methods often call other methods on the same instance. With a regular `Lock`,
if method A holds the lock and calls method B which also acquires the lock, the thread deadlocks.
`RLock` allows the same thread to acquire the lock multiple times.

```python
# Correct
self._lock = threading.RLock()

# WRONG — will deadlock
self._lock = threading.Lock()
```

---

## Configuration

All systems are configurable via `config/default.yaml`:

```yaml
neurochemistry:
  decay_rate: 0.01
  recovery_rate: 0.005
  baseline_variance: 0.1

skill_progression:
  xp_diminishing_factor: 0.95
  level_thresholds: [0, 100, 300, 600, 1000, 2000]

territory:
  districts: 16
  war_threshold: 0.1

living_world:
  tick_interval: 30
  event_probability: 0.2
  weather_change_probability: 0.15

news:
  max_articles: 200
  dedup_window: 120
  ticker_poll_interval: 30

multiplayer:
  heartbeat_timeout: 60
  max_sessions: 100
  message_page_size: 20

npc:
  tick_interval: 60

npc_scheduler:
  max_npcs_per_tick: 3
  fallback_npcs: ["lola", "viktor", "aria"]

scheduler:
  tasks:
    npc-world-tick:
      interval: every_1m
      enabled: true

world:
  sim_enabled: true
  tick_interval_seconds: 60
  economy_tick_interval_seconds: 90
```

---

## See Also

- [Scenes](SCENES.md) — Per-scene configuration and launch targets
- [Economy Guide](ECONOMY_GUIDE.md) — EconomyManager, cross-scene credits, market system
- [Architecture](ARCHITECTURE.md) — BaseScene, MCP pipeline, interceptor chain
- [Neon HUD](NEON_HUD.md) — PlayerState API, HUD strip, Socket.IO events
- [Character System](CHARACTER_SYSTEM.md) — NPCState, CharacterMemory, relationship system
- [Configuration](CONFIGURATION.md) — `world.*`, `npc.*`, `npc_scheduler.*` config keys
- [Skills](SKILLS.md) — `@skill` decorator, pack registration
- [MCP Framework](MCP_FRAMEWORK.md) — Full MCP system deep dive

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated to v1.50; fixed PlayerState fields (added health, hunger); confirmed 6 factions with power %; 60s WorldSim tick; removed stale cross-refs |
| v1.42 | 2025-12-15 | Consolidated from NeonCity 2 game systems, living world, and world system docs |
| v1.04b | 2025-09-01 | Initial game systems documentation |
