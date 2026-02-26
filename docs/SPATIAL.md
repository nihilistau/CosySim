# CosySim Spatial System

> Location management, character positioning, and proximity-based interaction for multi-agent scenes.

---

## Overview

The spatial system gives every scene a physical layout. Characters occupy discrete **Locations** within a **SceneMap**, and the engine uses co-location to gate interactions — two characters can only talk, touch, or fight if they share the same location. Movement, capacity limits, and LLM context injection all flow from this system.

```
engine/spatial/
├── __init__.py      — public API (Location, SceneMap)
├── location.py      — Location dataclass
└── scene_map.py     — SceneMap container + character positioning
```

### Key Rules

| Rule | Detail |
|------|--------|
| Co-location gating | `can_interact(a, b)` returns `True` only if both share a location |
| Capacity enforcement | `place_character()` and `move_character()` reject moves to full locations |
| Single location | Each character occupies exactly one location at a time |
| Auto-eviction | Removing a location evicts all its occupants |
| Event publishing | Every placement and departure emits an `ActivityBus` event |
| Registry sync | Character location state is written to `CharacterRegistry` on every move |

---

## Location

A `Location` is a named, bounded place inside a scene. It defines what activities are available, how many characters it holds, and environmental properties that influence agent behaviour.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | auto UUID | Unique identifier |
| `name` | `str` | `""` | Human-readable label (e.g. "Bed", "Bar") |
| `description` | `str` | `""` | Prose description injected into LLM context |
| `interactions` | `List[str]` | `[]` | Activities available here (e.g. "cuddle", "make a drink") |
| `capacity` | `int` | `4` | Maximum simultaneous occupants |
| `properties` | `Dict` | `{}` | Arbitrary metadata — privacy, comfort, spiciness, pos, etc. |
| `scene_id` | `str` | `""` | Set automatically by `SceneMap.add_location()` |

### Property Shortcuts

The `properties` dict supports three well-known keys with convenience accessors:

| Property | Accessor | Range | Default | Meaning |
|----------|----------|-------|---------|---------|
| `privacy` | `loc.privacy` | 0.0–1.0 | 0.5 | How secluded (0 = public, 1 = private) |
| `comfort` | `loc.comfort` | 0.0–1.0 | 0.5 | Physical comfort level |
| `spiciness` | `loc.spiciness` | 0–10 | 1 | How intimate interactions can get here |

Scenes may add additional properties. The Bedroom scene, for example, uses `pos` (3D coordinates), `mountable`, `mount_positions`, and `allowed_positions`.

### Occupancy

```python
loc.add_occupant("aria")       # True if space available, False if full
loc.remove_occupant("aria")    # always True (idempotent)
loc.has_occupant("aria")       # bool
loc.occupants                  # List[str] — current occupant IDs
loc.is_full                    # bool — at capacity?
```

### Serialisation

```python
loc.to_dict()
# → {"id": "bed", "name": "Bed", "description": "...",
#    "interactions": [...], "capacity": 3,
#    "properties": {...}, "occupants": ["aria"]}
```

### LLM Context

```python
loc.context_for_llm({"aria": "Aria", "lola": "Lola"})
# → "You are at the Bed. A large king-size bed... People here: Aria, Lola. You can: cuddle, kiss, ..."
```

When no name mapping is provided, occupants are listed as "no one else".

---

## SceneMap

`SceneMap` is the container for all locations in a single scene. It tracks which character is where, enforces capacity, and provides the query API used by `AgentLoop` and scene classes.

### Construction

```python
from engine.spatial import Location, SceneMap

sm = SceneMap(scene_id="bedroom")

sm.add_location(Location(
    id="bed", name="Bed",
    description="A king-size bed with silk sheets.",
    interactions=["sleep", "cuddle", "kiss"],
    capacity=3,
    properties={"privacy": 0.95, "comfort": 1.0, "spiciness": 10},
))

sm.add_location(Location(
    id="bar", name="Bar",
    description="A home bar with mood lighting.",
    interactions=["make a drink", "chat", "flirt"],
    capacity=2,
    properties={"privacy": 0.35, "comfort": 0.5, "spiciness": 6},
))
```

### Location Management

| Method | Returns | Description |
|--------|---------|-------------|
| `add_location(loc)` | `None` | Register a location; sets `loc.scene_id` |
| `remove_location(id)` | `None` | Unregister + evict all occupants |
| `get_location(id)` | `Location \| None` | Lookup by ID |
| `get_location_by_name(name)` | `Location \| None` | Case-insensitive name lookup |
| `locations` | `List[Location]` | All registered locations |
| `location_names` | `List[str]` | All location display names |

### Character Positioning

| Method | Returns | Description |
|--------|---------|-------------|
| `place_character(char_id, loc_id)` | `bool` | Place at a location (removes from previous) |
| `move_character(char_id, loc_id)` | `bool` | Alias for `place_character` |
| `remove_character(char_id)` | `None` | Remove from scene entirely |
| `get_character_location(char_id)` | `Location \| None` | Where is this character? |

Both `place_character` and `move_character` return `False` if the target location doesn't exist or is full. On success, they:

1. Remove the character from their previous location (if any)
2. Add them to the new location
3. Sync the `CharacterRegistry` state (`{"location": loc.name}`)
4. Publish a `character_moved` event to the `ActivityBus`

`remove_character` publishes a `character_left_location` event.

### Proximity Queries

| Method | Returns | Description |
|--------|---------|-------------|
| `get_nearby_characters(char_id)` | `List[str]` | Character IDs at the same location (excluding self) |
| `can_interact(char_a, char_b)` | `bool` | `True` if both share a location |
| `get_occupants(loc_id)` | `List[str]` | All character IDs at a location |
| `get_empty_locations()` | `List[Location]` | Locations with zero occupants |

### Serialisation

#### Full Snapshot

```python
sm.snapshot()
# → {
#     "locations": {"bed": {...}, "bar": {...}},
#     "character_locations": {"aria": "bed", "lola": "bar"}
# }
```

Used by `EventChain` for state logging and by scenes for UI broadcast.

#### Per-Character LLM Context

```python
sm.context_for_character("aria", names={"aria": "Aria", "lola": "Lola"})
# → "You are at the Bed. A large king-size bed... People here: Lola.
#    You can: sleep, cuddle, kiss. Other places you could go: Bar."
```

Returns `"You are nowhere in particular."` for unplaced characters.

---

## Integration with Scenes

### How Scenes Build a Map

Each scene constructs its own `SceneMap` with locations tailored to its theme. The pattern is a builder function that returns a fully populated map:

```python
# content/scenes/bedroom/bedroom_scene.py
def _build_bedroom_map() -> SceneMap:
    sm = SceneMap()
    locations = [
        Location(id="bed",      name="Bed",          capacity=3, ...),
        Location(id="couch",    name="Couch",        capacity=2, ...),
        Location(id="bar",      name="Bar",          capacity=2, ...),
        Location(id="bathroom", name="Bathroom",     capacity=2, ...),
        Location(id="balcony",  name="Balcony",      capacity=2, ...),
        Location(id="vanity",   name="Vanity Mirror", capacity=2, ...),
        Location(id="doorway",  name="Doorway",      capacity=2, ...),
        Location(id="fireplace",name="Fireplace",    capacity=2, ...),
    ]
    for loc in locations:
        sm.add_location(loc)
    return sm
```

The scene stores the map as `self.scene_map` and passes it to `AgentLoop`:

```python
class BedroomScene(BaseScene, MCPSceneMixin):
    def __init__(self, ...):
        self.scene_map = _build_bedroom_map()
        ...
        self.agent_loop = AgentLoop(scene_map=self.scene_map, scene_id="bedroom")
```

### Character Placement on Join

When a character joins a scene, they are placed at a random empty location (falling back to a default like `"doorway"`):

```python
empty = self.scene_map.get_empty_locations()
loc = random.choice(empty) if empty else self.scene_map.get_location("doorway")
self.scene_map.place_character(char.id, loc.id)
```

### Scene State Broadcast

Scenes periodically refresh UI state from the spatial system:

```python
def _refresh_location_state(self):
    for loc in self.scene_map.locations:
        self.scene_state["locations"][loc.id] = {
            "name": loc.name,
            "occupants": loc.occupants,
            "pos": loc.properties.get("pos", {"x": 0, "y": 0, "z": 0}),
            "spiciness": loc.spiciness,
            ...
        }

def _refresh_character_state(self):
    for cid, char in self.characters.items():
        loc = self.scene_map.get_character_location(cid)
        self.scene_state["characters"][cid]["location"] = loc.name if loc else None
```

---

## Integration with AgentLoop

The `AgentLoop` is the tick-based perceive→decide→execute cycle for multi-agent scenes. It relies on `SceneMap` at every phase.

### Perceive Phase

The agent's perception prompt is assembled from spatial context:

```
## Your State
Mood: happy, Arousal: 30%, Energy: 85%

## Location
You are at the Bed. A large king-size bed... People here: Lola.
You can: cuddle, kiss, sleep. Other places you could go: Bar, Balcony.

## People in Scene
Lola (nearby): mood=flirty, arousal=45%
Viktor (at Bar): mood=calm, arousal=10%

## Available Locations
Bed, Bar, Balcony, Doorway, Fireplace

## Location Activities
At the Bed: cuddle, kiss, sleep, massage, ...
```

Key spatial calls during perception:

| Call | Purpose |
|------|---------|
| `scene_map.context_for_character(cid, names)` | Location description + available interactions |
| `scene_map.get_nearby_characters(cid)` | Who is co-located (labeled "nearby") |
| `scene_map.get_character_location(oid)` | Where other characters are (labeled "at X") |
| `scene_map.location_names` | List of all places the agent could move to |

### Decide Phase (Fallback)

When the LLM is unavailable, the agent loop generates random actions weighted by spatial state:

```python
if nearby and arousal > 0.5:
    actions = ["flirt", "speak", "touch", "speak", "kiss"]
elif nearby:
    actions = ["speak", "speak", "speak", "idle", "flirt", "move"]
else:
    actions = ["move", "move", "idle", "idle"]  # alone → likely move
```

Movement targets are chosen from non-current locations:

```python
candidates = [l for l in scene_map.locations if l.id != cur_loc.id]
target = random.choice(candidates).name
```

### Execute Phase

Movement actions are resolved through the spatial system:

```python
if action == "move":
    loc = scene_map.get_location_by_name(target)
    if loc:
        success = scene_map.move_character(character_id, loc.id)
```

Physical interactions (`flirt`, `touch`, `kiss`, `cuddle`, `intimate`) are only valid when `get_nearby_characters` returns the target — enforcing the co-location rule.

---

## ActivityBus Events

The spatial system publishes two event types through the `ActivityBus`:

| Event Type | Trigger | Data |
|------------|---------|------|
| `character_moved` | `place_character` / `move_character` | `{"location": name, "location_id": id}` |
| `character_left_location` | `remove_character` | `{"location": name, "location_id": id}` |

Both events include `agent_id` (the character) and `scene` (the scene ID).

---

## Bedroom Scene Locations (Reference)

The Bedroom scene — the AAA reference implementation — defines 7 locations:

| ID | Name | Capacity | Privacy | Comfort | Spiciness |
|----|------|----------|---------|---------|-----------|
| `bed` | Bed | 3 | 0.95 | 1.0 | 10 |
| `couch` | Couch | 2 | 0.50 | 0.85 | 8 |
| `bar` | Bar | 2 | 0.35 | 0.50 | 6 |
| `bathroom` | Bathroom | 2 | 1.00 | 0.80 | 10 |
| `balcony` | Balcony | 2 | 0.15 | 0.45 | 8 |
| `vanity` | Vanity Mirror | 2 | 0.40 | 0.50 | 9 |
| `doorway` | Doorway | 2 | 0.10 | 0.20 | 7 |
| `fireplace` | Fireplace | 2 | 0.70 | 0.90 | 8 |

Each location also carries `pos` (3D coordinates for rendering), `mountable` flag, `mount_positions`, and `allowed_positions` — used by the Bedroom scene's 3D avatar system.

---

## Quick Reference

### Imports

```python
from engine.spatial import Location, SceneMap
# or individually:
from engine.spatial.location import Location
from engine.spatial.scene_map import SceneMap
```

### Minimal Scene Setup

```python
sm = SceneMap(scene_id="my_scene")
sm.add_location(Location(id="lobby", name="Lobby", capacity=6))
sm.add_location(Location(id="office", name="Office", capacity=2))

sm.place_character("char_1", "lobby")   # → True
sm.place_character("char_2", "lobby")   # → True
sm.can_interact("char_1", "char_2")     # → True

sm.move_character("char_2", "office")   # → True
sm.can_interact("char_1", "char_2")     # → False
```

### Creating a New Scene Map

1. Define locations with IDs, names, descriptions, interactions, and properties
2. Build a `SceneMap` and call `add_location()` for each
3. Store as `self.scene_map` in your `BaseScene` subclass
4. Pass to `AgentLoop(scene_map=self.scene_map, ...)`
5. Place characters with `scene_map.place_character(char_id, loc_id)` on join

---

## Related Docs

- [Architecture](./ARCHITECTURE.md) — system layers and data flow
- [Scenes Guide](./SCENES.md) — all 13 scenes and their mechanics
- [Characters](./CHARACTERS.md) — personality, stats, buffs, tags
- [Skills](./SKILLS.md) — `@skill` decorator and scene packs
- [Contributing](./CONTRIBUTING.md) — scene creation workflow
