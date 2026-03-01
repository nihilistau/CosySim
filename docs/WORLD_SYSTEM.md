# CosySim World System

> Living world infrastructure — WorldSim, WorldState, EventBus, cross-scene events.
> Added in v0.68 "Dark Renaissance".

## Overview

The world system makes CosySim a living simulation. Even when you're not in a scene,
the world ticks forward: factions shift, characters move, time passes, events fire.

## Components

### WorldState (`engine/world/world_state.py`)
Game clock (1 real min = 1 game hour). Weather enum. NPC daily schedules.
```python
from engine.world.world_state import get_world_state
ws = get_world_state()
time = ws.get_time()        # WorldTime(hour=14, day=3, weather=Weather.RAIN)
ws.tick(minutes=5)          # advance by 5 real minutes = 5 game hours
```

### WorldSim (`engine/world/world_sim.py`)
Background daemon thread. Fires world events at intervals. Broadcasts via EventBus.
```python
from engine.world.world_sim import get_world_sim
sim = get_world_sim()
sim.start()   # start daemon (called in launcher after scenes start)
sim.stop()    # stop daemon
```

### EventBus (`engine/events/event_bus.py`)
Thread-safe in-process pub/sub. Cross-scene events. Nexus history persistence.
```python
from engine.events.event_bus import get_event_bus
bus = get_event_bus()
bus.subscribe("casino.major_win", my_handler)
bus.publish("casino.major_win", {"player": "lola", "amount": 500})
```

## Standard Event Names

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `world.tick` | WorldSim | All scenes (state refresh) |
| `world.time_change` | WorldSim | Scenes with time-gated content |
| `world.weather_change` | WorldSim | Outdoor scenes |
| `casino.major_win` | Casino | NeonCity (faction +economy) |
| `arena.match_end` | Arena | NeonCity (faction shift), Hub (stats) |
| `heist.completed` | Heist | Hub (economy), Intel Hub (news) |
| `faction.shift` | NeonCity | All faction-aware scenes |

## Wiring a Scene
```python
from engine.world.world_state import get_world_state
from engine.events.event_bus import get_event_bus

class MyScene(BaseScene):
    def start(self):
        ...
        self._world_state = get_world_state()
        self._bus = get_event_bus()
        self._bus.subscribe("world.tick", self._on_world_tick)

    def _on_world_tick(self, event: dict) -> None:
        time = self._world_state.get_time()
        # update scene state based on time
```
