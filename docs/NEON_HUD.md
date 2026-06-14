# CosySim Universal Neon HUD

> CosySim Documentation — v1.52.0 [2026-03-26]
>
> Universal player-state strip and glass slide panels injected into every scene.
> `engine/world/player_state.py` · `content/shared/templates/neon_hud.html`
> `content/shared/static/css/cosysim-neon-hud.css` · `content/shared/static/js/cosysim-neon-hud.js`

---

## Overview

The Universal Neon HUD is a 32px accent strip mounted inside `navbar_v2.html` on all 20 scenes.
It surfaces the player's **credits**, **reputation**, **heat**, and **faction standings** as live
glyphs that update in real time via Socket.IO with a 30-second polling fallback.

Design goals:

- **One source of truth.** `PlayerState` is a process-level singleton. All scenes read and write
  the same object; no per-scene credit/heat shadow copies.
- **Zero scene code.** Injection is handled entirely by `navbar_v2.html`. Scene authors do not
  wire the HUD manually.
- **Low bandwidth.** The full HUD payload is approximately 300 bytes. Socket.IO pushes delta dicts; the
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
| `credits` | `int` | `5000` | `0 – inf` | In-world currency (C) |
| `reputation` | `int` | `0` | `0 – 100` | Global standing across Neon City |
| `heat` | `int` | `0` | `0 – 100` | Law-enforcement attention level |
| `health` | `int` | `100` | `0 – 100` | Physical health |
| `hunger` | `int` | `80` | `0 – 100` | Satiation level (100 = full) |
| `energy` | `int` | `100` | `0 – 100` | Stamina / fatigue |
| `faction_standings` | `dict[str, int]` | all `0` | `-100 – 100` | Per-faction relationship scores |
| `active_location` | `str` | `""` | — | Current in-world district or scene name |
| `skills` | `dict[str, int]` | 8 defaults | `0 – 100` | Named skill levels |
| `implants` | `list[str]` | `[]` | — | Active cyberware implant IDs |

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
ps.update_reputation(+10)  # -> 52
ps.update_reputation(-60)  # -> 0   (clamped)
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
    return {"error": "heat_locked", "message": "Too hot -- lie low."}
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
Clamp-adjust the standing for `faction` by `delta` (-100 to +100). Returns new standing.
Unknown faction keys are created automatically.

```python
ps.update_faction_standing("omnicorp", +15)   # -> 15
ps.update_faction_standing("ghost_net", -30)  # -> -30
ps.get_faction_standings()                    # -> {"omnicorp": 15, "ghost_net": -30, ...}
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
  "health": 87,
  "hunger": 60,
  "energy": 95,
  "active_location": "THE GRID / MARKET",
  "faction_standings": {
    "omnicorp":   15,
    "neotech":     0,
    "blackmarket": 30,
    "ghost_net":  -10,
    "synthsec":    5,
    "deepstate":   0
  },
  "skills": { "hacking": 55, "stealth": 30, "...": 10 },
  "implants": ["reflex_booster", "optic_cam"],
  "inventory_snapshot": [
    { "slot": 0, "item_id": "pistol_mk2", "qty": 1, "equipped": true }
  ],
  "crew_snapshot": [
    { "name": "Viktor", "role": "muscle", "loyalty": 72, "level": 2 }
  ]
}
```

---

## HUD State Endpoint

Registered automatically by `BaseScene` on every scene.

```
GET /api/hud/state
```

**Response** — `200 OK`

The response body is the full `to_dict()` payload shown above. The endpoint always returns
the live singleton state; it is safe to poll at any cadence. The JavaScript client polls
every **30 seconds** as a fallback behind Socket.IO push.

---

## Socket.IO Events

### `hud_update` (server -> client)

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
    "faction_standings": { "omnicorp": 15, "ghost_net": -10 }
  }
}
```

### `economy_tick` (server -> client)

Broadcast by `WorldSim` every 90 seconds alongside the `hud_update`. Contains the economy
event description for display in scene notification feeds.

```json
{
  "event": "economy_tick",
  "data": {
    "description": "OmniCorp supply chain disruption -- black market prices surge.",
    "credits_delta": -50,
    "reputation_delta": 0
  }
}
```

---

## HUD Strip Layout

The 32px strip renders inside `navbar_v2.html` immediately below the scene navigation bar.
Visual structure (left to right):

```
 C 4,850   * REP 42   HEAT 15   THE GRID / MARKET   [faction dot x6]
```

| Element | CSS class | Updates on |
|---------|-----------|-----------|
| Credits glyph | `.neon-hud-credits` | `hud_update` |
| Reputation bar | `.neon-hud-rep` | `hud_update` |
| Heat bar | `.neon-hud-heat` | `hud_update` — turns red at >= 70, pulses at >= 90 |
| Location label | `.neon-hud-location` | `hud_update` |
| Faction dot row | `.neon-hud-factions` | `hud_update` — colour-coded by standing |

**Faction dot colours:**

| Standing range | Colour |
|----------------|--------|
| >= 50 | `--cs-accent` (neon green) |
| 20 – 49 | `--cs-gold` |
| -19 – 19 | `--cs-glass-border` (neutral) |
| -20 – -49 | `--cs-amber` |
| <= -50 | `--cs-danger` (red) |

---

## HUD v2 — Glass Slide Panels

### Overview

HUD v2 adds two **glass slide panels** flanking the viewport and a **World Announcer** widget
in the bottom bar. The existing 32px Neon HUD strip is retained; the panels extend it with full
player vitals, inventory, crew, phone access, and live world feed.

```
+------------------+--------------------------------------------+------------------+
|  LEFT PANEL      |            SCENE VIEWPORT                  |  RIGHT PANEL     |
|  (slide in <)    |                                            |  (> slide in)    |
|                  |                                            |                  |
|  HEALTH  ####    |                                            |  PHONE           |
|  HUNGER  ##--    |      [scene content]                       |  QUICK TRAVEL    |
|  ENERGY  ###-    |                                            |  CREW            |
|                  |                                            |  SYSTEM          |
|  C 4850          |                                            |  NEXUS SEARCH    |
|  * 42  HEAT 15   |                                            |                  |
|                  |                                            |                  |
|  [IMPLANTS]      |                                            |                  |
|  [INVENTORY 12]  |                                            |                  |
|  [SKILL PIPS]    |                                            |                  |
+------------------+--[ C 4,850  *42  H15  THE GRID  xxxxxx ]--+------------------+
                                     [ WORLD ANNOUNCER TICKER ]
```

### Left Slide Panel

Toggled with keyboard shortcut **I** or the inventory button in the Neon HUD strip.

| Widget | Content |
|--------|---------|
| Vitals bars | `health`, `hunger`, `energy` — animated progress bars (0–100) |
| Economy row | credits (C), reputation (*), heat |
| Cyberdeck status | model name, storage used |
| Implants list | active cyberware implants from `PlayerState.implants` |
| Inventory grid | 12-slot visual grid (3x4), item icons, equipped indicator |
| Skill pips | 8 default skills displayed as named pip rows |

**CSS animation:** panel slides in from the left edge (`transform: translateX(-100%) -> 0`) with
a 240ms ease-out transition. Panel has `backdrop-filter: blur(12px)` glass effect.

### Right Slide Panel

Toggled with keyboard shortcut **C** (command panel).

| Widget | Content |
|--------|---------|
| GhostSignal phone launch | Opens phone overlay (keyboard **P**) |
| Quick travel | Destination buttons wired to scene nav |
| Crew status | Crew count, current operation if active |
| System health | Coloured dots: LMStudio, Nexus, TTS, ComfyUI |
| Nexus search | Input -> `GET /api/nexus/quick_search?q=` -> inline results |

### Phone Overlay

Keyboard shortcut **P** (or "Launch GhostSignal" button in right panel).

- Lazy-loaded `<iframe>` pointing to `http://localhost:5555` (SIGNAL scene)
- Slide-in from right with 300ms ease-out
- Detach button opens SIGNAL in a new browser tab
- Overlay backdrop blurs the scene behind it
- Socket.IO passthrough — SIGNAL's own HUD syncs independently

### World Announcer Widget

A persistent bottom ticker below the Neon HUD strip. Keyboard shortcut **A**.

**5 Station Themes:**

| Station | Theme | Colour |
|---------|-------|--------|
| `NEON_FM` | Music / culture | `--cs-accent` neon green |
| `DARKWIRE` | Hacker / underground | `--cs-gold` |
| `CORP_FEED` | OmniCorp press | `--cs-amber` |
| `GHOST_NET` | Ghost_Net dispatches | `--cs-info` cyan |
| `STREET_ECHO` | Street-level events | `--cs-glass-border` neutral |

**7 Badge Categories:**

`BREAKING` / `ALERT` / `FACTION` / `ECONOMY` / `WORLD` / `INTEL` / `GHOST`

**Socket.IO event:** `announcer_update` — server pushes new announcements, client
appends to the scrolling ticker. Falls back to periodic `GET /api/announcer/feed` polling.

**Fallback messages** are rendered when the announcer has no live feed (e.g., Nexus offline).

---

### Default Skills Dict

```python
{
    "hacking":    10,
    "stealth":    10,
    "persuasion": 10,
    "combat":     10,
    "tech":       10,
    "medical":    10,
    "driving":    10,
    "athletics":  10,
}
```

---

## REST API Endpoints

### `/api/announcer/feed`

```
GET /api/announcer/feed?limit=20
```

Returns the latest world announcements as a JSON array. Each item:

```json
{
  "id": "ann_001",
  "station": "DARKWIRE",
  "badge": "INTEL",
  "text": "Ghost_Net operatives spotted in THE GRID sector 3.",
  "timestamp": "2026-03-12T14:22:00Z"
}
```

### `/api/inventory` — 5 endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/inventory` | Full inventory + equipped items |
| `POST` | `/api/inventory/add` | Add item `{item_id, qty}` |
| `POST` | `/api/inventory/remove` | Remove item `{item_id, qty}` |
| `POST` | `/api/inventory/equip` | Equip item to slot `{item_id, slot}` |
| `POST` | `/api/inventory/unequip` | Unequip from slot `{slot}` |

### `/api/crew` — 6 endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/crew` | All crew members + active operations |
| `POST` | `/api/crew/recruit` | Recruit NPC `{character_id}` |
| `POST` | `/api/crew/dismiss` | Dismiss crew member `{member_id}` |
| `POST` | `/api/crew/loyalty` | Adjust loyalty `{member_id, delta}` |
| `POST` | `/api/crew/operation/start` | Start operation `{type, member_ids}` |
| `GET` | `/api/crew/operation/check` | Poll active operations |

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

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `I` | Toggle left panel (inventory/vitals) |
| `C` | Toggle right panel (command/crew/phone) |
| `P` | Toggle phone overlay (SIGNAL iframe) |
| `A` | Toggle world announcer expanded view |

---

## HUD Micro-Animations

| Effect | Trigger | CSS |
|--------|---------|-----|
| Button ripple | Click on any HUD button | `@keyframes ripple` |
| Stat bar transition | Any vitals change | `transition: width 400ms ease` |
| Credits bounce | Credit change | `@keyframes credits-bounce` |
| Inventory hover | Mouse over grid slot | `transform: scale(1.08)` |
| Panel slide | Open/close | `transform: translateX` 240ms ease-out |
| Announcer scroll | Continuous | `@keyframes ticker-scroll` |

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
| Casino | `omnicorp` | >= 30 | Unlocks VIP access |
| Casino | — | heat >= 80 | Tables locked (`heat_locked`) |
| THE GRID / DEN | any | >= 50 | Allegiance pledge available |
| NeonCity | `ghost_net` | >= 20 | Broker ghost terminal unlocked |

---

## Cross-References

- [Architecture](ARCHITECTURE.md) — System overview and engine layers
- [Scenes](SCENES.md) — Full scene listing and port assignments
- [Game Systems](GAME_SYSTEMS.md) — WorldSim, economy, factions, NPCs, events
- [THE GRID](THE_GRID.md) — Scene that most heavily uses PlayerState
- [Skills](SKILLS.md) — `world` skill pack (10 skills), `inventory` (7), `crew` (8)

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated scene count to 20, consolidated v2 fields into main reference, fixed cross-references |
| v1.04 | 2026-03-15 | Added economy tick and faction quest thresholds |
| v0.81 | 2026-03-12 | HUD v2 overhaul: glass slide panels, phone overlay, world announcer, expanded PlayerState fields |
| v0.75 | 2026-03-10 | Initial Neon HUD strip — credits, reputation, heat, faction dots |
