# CosySim Universal Neon HUD

> Universal player-state strip injected into every scene. v0.75 "NEON CITY".
> `engine/world/player_state.py` · `content/shared/templates/neon_hud.html`
> `content/shared/static/css/cosysim-neon-hud.css` · `content/shared/static/js/cosysim-neon-hud.js`

---

## Overview

The Universal Neon HUD is a 32px accent strip mounted inside `navbar_v2.html` on all 15 scenes.
It surfaces the player's **credits**, **reputation**, **heat**, and **faction standings** as live
glyphs that update in real time via Socket.IO with a 30-second polling fallback.

Design goals:

- **One source of truth.** `PlayerState` is a process-level singleton. All scenes read and write
  the same object; no per-scene credit/heat shadow copies.
- **Zero scene code.** Injection is handled entirely by `navbar_v2.html`. Scene authors do not
  wire the HUD manually.
- **Low bandwidth.** The full HUD payload is ≈ 300 bytes. Socket.IO pushes delta dicts; the
  polling endpoint returns the full state for clients that miss events.
- **Non-blocking.** All state mutations are synchronous in-process calls. The HUD never waits on
  LMStudio or Nexus.

---

## PlayerState Singleton

### Import & Access

```python
from engine.world.player_state import get_player_state

ps = get_player_state()   # always returns the same singleton instance
```

### Fields

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `credits` | `int` | `5000` | `0 – ∞` | In-world currency (₵) |
| `reputation` | `int` | `0` | `0 – 100` | Global standing across Neon City |
| `heat` | `int` | `0` | `0 – 100` | Law-enforcement attention level |
| `faction_standings` | `dict[str, int]` | all `0` | `−100 – 100` | Per-faction relationship scores |
| `active_location` | `str` | `""` | — | Current in-world district or scene name |

**Faction keys:** `omnicorp`, `neotech`, `blackmarket`, `ghost_net`, `synthsec`, `deepstate`

---

### Methods

#### Economy

```python
ps.earn_credits(amount: int, source: str = "") -> int
```
Add `amount` to `credits`. Returns new balance. Fires `hud_update` Socket.IO event.

```python
ps.spend_credits(amount: int, reason: str = "") -> bool
```
Deduct `amount` if balance permits. Returns `True` on success, `False` if insufficient funds.
Does **not** allow balance below zero.

```python
# Example
ok = ps.spend_credits(150, reason="grid_market_buy")
if not ok:
    return {"error": "Insufficient credits"}
```

---

#### Reputation

```python
ps.update_reputation(delta: int) -> int
```
Clamp-adjust `reputation` by `delta` (positive or negative). Returns new value (0–100).

```python
ps.reputation    # 42
ps.update_reputation(+10)  # → 52
ps.update_reputation(-60)  # → 0   (clamped)
```

---

#### Heat

```python
ps.adjust_heat(delta: int) -> int
```
Clamp-adjust `heat` by `delta`. Returns new value (0–100). Scenes read `heat` to gate
VIP access or trigger law-enforcement events.

```python
# Casino: lock table if heat >= 80
if ps.heat >= 80:
    return {"error": "heat_locked", "message": "Too hot — lie low."}
```

---

#### Location

```python
ps.set_location(location: str) -> None
```
Update `active_location`. Stored in the HUD and available to all scenes via `to_dict()`.
Call this whenever the player moves between districts or scenes.

---

#### Faction Standings

```python
ps.update_faction_standing(faction: str, delta: int) -> int
```
Clamp-adjust the standing for `faction` by `delta` (−100 to +100). Returns new standing.
Unknown faction keys are created automatically.

```python
ps.update_faction_standing("omnicorp", +15)   # → 15
ps.update_faction_standing("ghost_net", -30)  # → -30
ps.get_faction_standings()                    # → {"omnicorp": 15, "ghost_net": -30, …}
```

---

#### World-Event Hooks

These are called internally by `WorldSim`. Scene authors rarely call them directly.

```python
ps.on_economy_tick(event: dict) -> None
```
Receives `ECONOMY_EVENTS` payloads from `WorldSim`'s 90-second economy tick. May adjust
credits and reputation based on the event type.

```python
ps.on_faction_shift(faction: str, delta: int) -> None
```
Propagates a world-level faction shift into the player's `faction_standings`.

---

#### Serialisation

```python
ps.to_dict() -> dict
```
Returns the full state as a JSON-serialisable dict. This is the exact payload returned by
`GET /api/hud/state` and emitted on the `hud_update` Socket.IO event.

```python
{
  "credits": 4850,
  "reputation": 42,
  "heat": 15,
  "active_location": "THE GRID / MARKET",
  "faction_standings": {
    "omnicorp":   15,
    "neotech":     0,
    "blackmarket": 30,
    "ghost_net":  -10,
    "synthsec":    5,
    "deepstate":   0
  }
}
```

---

## HUD State Endpoint

Registered automatically by `BaseScene` on every scene.

```
GET /api/hud/state
```

**Response** — `200 OK`

```json
{
  "credits": 4850,
  "reputation": 42,
  "heat": 15,
  "active_location": "THE GRID / MARKET",
  "faction_standings": {
    "omnicorp":   15,
    "neotech":     0,
    "blackmarket": 30,
    "ghost_net":  -10,
    "synthsec":    5,
    "deepstate":   0
  }
}
```

The endpoint always returns the live singleton state; it is safe to poll at any cadence.
The JavaScript client polls every **30 seconds** as a fallback behind Socket.IO push.

---

## Socket.IO Events

### `hud_update` (server → client)

Emitted by `PlayerState` whenever any field changes (credits, reputation, heat, location,
or any faction standing). The payload is the full `to_dict()` snapshot — clients replace
their local state rather than applying partial patches.

```json
{
  "event": "hud_update",
  "data": {
    "credits": 4700,
    "reputation": 44,
    "heat": 15,
    "active_location": "THE GRID / BROKER",
    "faction_standings": { "omnicorp": 15, "ghost_net": -10, ... }
  }
}
```

### `economy_tick` (server → client)

Broadcast by `WorldSim` every 90 seconds alongside the `hud_update`. Contains the economy
event description for display in scene notification feeds.

```json
{
  "event": "economy_tick",
  "data": {
    "description": "OmniCorp supply chain disruption — black market prices surge.",
    "credits_delta": -50,
    "reputation_delta": 0
  }
}
```

---

## HUD Strip Layout

The 32px strip renders inside `navbar_v2.html` immediately below the scene navigation bar.
Visual structure (left → right):

```
 ₵ 4,850   ★ REP 42   🌡 HEAT 15   📍 THE GRID / MARKET   [faction dot ×6]
```

| Element | CSS class | Updates on |
|---------|-----------|-----------|
| Credits glyph | `.neon-hud-credits` | `hud_update` |
| Reputation bar | `.neon-hud-rep` | `hud_update` |
| Heat bar | `.neon-hud-heat` | `hud_update` — turns red at ≥ 70, pulses at ≥ 90 |
| Location label | `.neon-hud-location` | `hud_update` |
| Faction dot row | `.neon-hud-factions` | `hud_update` — colour-coded by standing |

**Faction dot colours:**

| Standing range | Colour |
|----------------|--------|
| ≥ 50 | `--cs-accent` (neon green) |
| 20 – 49 | `--cs-gold` |
| −19 – 19 | `--cs-glass-border` (neutral) |
| −20 – −49 | `--cs-amber` |
| ≤ −50 | `--cs-danger` (red) |

---

## Integration Guide

### For Scene Authors

No manual wiring is needed. `navbar_v2.html` includes:

```html
{% include 'neon_hud.html' %}
```

`neon_hud.html` loads `cosysim-neon-hud.css` and `cosysim-neon-hud.js`, connects to Socket.IO,
and starts the 30s polling loop. The strip is live as soon as the page loads.

### Mutating State from Scene Routes

```python
from engine.world.player_state import get_player_state

@app.route("/api/buy_item", methods=["POST"])
def buy_item():
    ps = get_player_state()
    ok = ps.spend_credits(request.json["price"], reason="grid_buy")
    if not ok:
        return jsonify({"error": "insufficient_credits"}), 400
    ps.update_reputation(+2)
    return jsonify(ps.to_dict())
```

After `spend_credits` the singleton emits `hud_update` automatically. The caller's return
value (including `ps.to_dict()`) is a convenience for the client, not a requirement.

### Reading State from Skills

```python
from engine.world.player_state import get_player_state

@skill(pack="world", tags=["economy"])
def get_player_state_info() -> dict:
    """Return current credits, reputation, heat, location and faction standings."""
    return get_player_state().to_dict()
```

---

## Neon City Factions

Six factions govern Neon City's power landscape. Faction standings affect scene access,
NPC dialogue, and economy events.

| ID | Display Name | Domain | Neutral Standing |
|----|-------------|--------|-----------------|
| `omnicorp` | **OmniCorp** | Megacorp / finance | 0 |
| `neotech` | **NeoTech** | Tech / hardware | 0 |
| `blackmarket` | **BlackMarket** | Underground trade | 0 |
| `ghost_net` | **Ghost\_Net** | Hacker collective | 0 |
| `synthsec` | **SynthSec** | Private security | 0 |
| `deepstate` | **DeepState** | Shadow government | 0 |

**Standing thresholds used by scenes:**

| Scene | Faction | Threshold | Effect |
|-------|---------|-----------|--------|
| Casino | `omnicorp` | ≥ 30 | Unlocks VIP access |
| Casino | — | heat ≥ 80 | Tables locked (`heat_locked`) |
| THE GRID / DEN | any | ≥ 50 | Allegiance pledge available |
| NeonCity | `ghost_net` | ≥ 20 | Broker ghost terminal unlocked |

---

## See Also

- [LIVING\_WORLD.md](./LIVING_WORLD.md) — WorldSim, economy tick, event lifecycle
- [THE\_GRID.md](./THE_GRID.md) — Scene that most heavily uses PlayerState
- [WORLD\_SYSTEM.md](./WORLD_SYSTEM.md) — WorldSim daemon, EventBus, NPCScheduler
- [SKILLS.md](./SKILLS.md) — `world` skill pack (10 skills)
