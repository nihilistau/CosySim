# THE GRID

> CosySim Documentation — v1.50 [2026-03-22]
>
> THE GRID is Neon City's central hub — a four-zone underground marketplace for commerce,
> travel, faction politics, and intelligence gathering.
> Scene: `content/scenes/grid/` · Port **5569** · Accent `#00ff88`

---

## Overview

THE GRID is Neon City's central hub — a four-zone underground marketplace where the player
buys gear, plans travel, pledges faction allegiance, and intercepts ghost-net intelligence.
It is the primary scene for interacting with `PlayerState` (credits, heat, faction standings)
and the `world` skill pack.

```
THE GRID
+-- MARKET    -- buy / sell items from three vendors
+-- STATION   -- SVG city map, fast-travel to 15 nodes
+-- DEN       -- faction HQ, pledge allegiance, accept quests
+-- BROKER    -- intel feed, ghost terminal
```

**Key stats:** 7 GridSkills / 4 zones / 3 vendors / 15 travel nodes / 6 factions

---

## Zones

### MARKET

The MARKET zone hosts three resident vendors. Each vendor carries a rotating catalogue of
items with buy and sell prices. Transactions deduct/credit `PlayerState.credits` and may
shift faction standings or heat depending on item category.

#### Vendors

| Vendor | Specialty | Price range | Faction alignment |
|--------|-----------|-------------|------------------|
| **Mira** | Street tech, stims, data chips | C50–C800 | `blackmarket` |
| **Viktor** | Military surplus, weapons mods | C200–C2,000 | `synthsec` |
| **Frankie** | Rare intel, forged IDs, ghosts | C100–C3,000 | `ghost_net` |

Item categories: `hardware`, `consumable`, `intel`, `weapon_mod`, `identity`.

Price modifier formula:

```
final_price = base_price x (1 - faction_discount)
faction_discount = clamp(faction_standing / 200, 0, 0.25)
```

Selling returns 40–60% of base price depending on item condition.

---

### STATION

The STATION zone renders an SVG city map showing all **15 travel nodes** across Neon City's
districts. Clicking a node calls `grid_get_travel_map` and then initiates fast-travel via
`ps.set_location(node)`.

#### Travel Nodes

| # | Node | District | Faction territory |
|---|------|----------|------------------|
| 1 | THE GRID | Central | neutral |
| 2 | OmniCorp Plaza | Uptown | `omnicorp` |
| 3 | NeoTech Quarter | Uptown | `neotech` |
| 4 | SynthSec Barracks | Uptown | `synthsec` |
| 5 | The Neon Strip | Midtown | neutral |
| 6 | Club Noir (Casino) | Midtown | `omnicorp` |
| 7 | The Velvet Pit | Midtown | `blackmarket` |
| 8 | The Penthouse | Midtown | neutral |
| 9 | Junkyard Sprawl | Downzone | `blackmarket` |
| 10 | Ghost Alley | Downzone | `ghost_net` |
| 11 | Ripper Street | Downzone | `blackmarket` |
| 12 | The Rusty Anchor | Downzone | neutral |
| 13 | DeepState Bunker | Shadow | `deepstate` |
| 14 | SynthSec Grid Point | Shadow | `synthsec` |
| 15 | THE COLOSSEUM | Arena | neutral |

Fast-travel to faction-controlled nodes requires a standing of >= -30 for that faction; nodes
in `deepstate` territory additionally require heat <= 40.

---

### DEN

The DEN is the faction political centre. Six faction banners line the walls. The player can:

1. **View standings** — live faction_standings from `PlayerState`.
2. **Pledge allegiance** — requires standing >= 50 with target faction; sets that faction as
   `active_faction` and grants a bonus quest slot.
3. **Accept quests** — each faction offers one active quest at a time drawn from
   `FACTION_EVENTS_RICH` templates in `neon_city_events.py`.

Quest completion rewards credits, reputation, and faction standing. Quest failure or betrayal
triggers a standing penalty across rival factions.

#### Faction Quest Rewards (baseline)

| Faction | Credits | Rep | Standing delta |
|---------|---------|-----|---------------|
| OmniCorp | C800 | +5 | `omnicorp` +20 |
| NeoTech | C600 | +8 | `neotech` +20 |
| BlackMarket | C1,200 | +3 | `blackmarket` +20, heat +10 |
| Ghost\_Net | C400 | +12 | `ghost_net` +20 |
| SynthSec | C700 | +6 | `synthsec` +20, heat -5 |
| DeepState | C1,500 | -2 | `deepstate` +20, heat +5 |

---

### BROKER

The BROKER zone is an intel clearinghouse. Two panels:

**Intel Feed** — a live scrolling ticker drawing from `FACTION_EVENTS_RICH` and
`WORLD_EVENTS_RICH`. Updates every 30 seconds via Socket.IO `world_event` broadcast.

**Ghost Terminal** — a locked terminal that opens when `ghost_net` standing >= 20 or when
the 0xGH0ST mystery arc is active (Phone scene). The terminal accepts freeform input and
routes through `ghost_net` NPC dialogue with elevated mystery context. Outputs are logged
to the Nexus `ghost_terminal` namespace.

---

## Skills Reference

Pack: `"grid"` / File: `content/scenes/grid/grid_skills.py`

| Skill | Description | Key params |
|-------|-------------|-----------|
| `grid_buy_item` | Purchase an item from a vendor. Deducts credits, adjusts faction standing. | `vendor: str`, `item_id: str` |
| `grid_sell_item` | Sell an item for credits. | `item_id: str`, `condition: str` |
| `grid_get_market_prices` | Return current catalogue for all three vendors. | — |
| `grid_faction_pledge` | Pledge allegiance to a faction (requires standing >= 50). | `faction: str` |
| `grid_accept_quest` | Accept the current quest for a faction. | `faction: str` |
| `grid_get_travel_map` | Return the 15-node SVG map and current node standings. | — |
| `grid_broker_intel` | Fetch latest intel feed entries. | `count: int = 5` |

### Skill Signatures

```python
@skill(pack="grid")
def grid_buy_item(vendor: str, item_id: str) -> dict:
    """Buy item_id from vendor (mira|viktor|frankie). Returns updated credits and item."""

@skill(pack="grid")
def grid_sell_item(item_id: str, condition: str = "good") -> dict:
    """Sell an item. condition: good|fair|poor. Returns credits received and new balance."""

@skill(pack="grid")
def grid_get_market_prices() -> dict:
    """Return full market catalogue: {vendor: [{id, name, price, category}]}."""

@skill(pack="grid")
def grid_faction_pledge(faction: str) -> dict:
    """Pledge to faction. Requires standing >= 50. Returns pledge status and bonuses."""

@skill(pack="grid")
def grid_accept_quest(faction: str) -> dict:
    """Accept active quest for faction. Returns quest description, objectives, rewards."""

@skill(pack="grid")
def grid_get_travel_map() -> dict:
    """Return travel node list and current faction territory status."""

@skill(pack="grid")
def grid_broker_intel(count: int = 5) -> list:
    """Return the last `count` intel feed entries from FACTION_EVENTS_RICH + WORLD_EVENTS_RICH."""
```

---

## API Endpoints

All routes are registered on the `GridScene` Flask app.

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/grid/market` | Full vendor catalogue |
| `POST` | `/api/grid/buy` | `{vendor, item_id}` -> buy result |
| `POST` | `/api/grid/sell` | `{item_id, condition}` -> sell result |
| `GET` | `/api/grid/factions` | Current faction standings + active quests |
| `POST` | `/api/grid/faction/pledge` | `{faction}` -> pledge result |
| `POST` | `/api/grid/faction/quest/accept` | `{faction}` -> quest details |
| `GET` | `/api/grid/map` | SVG map + 15 travel nodes |
| `POST` | `/api/grid/travel` | `{node_id}` -> fast-travel result, updates `active_location` |
| `GET` | `/api/grid/broker/intel` | Latest intel feed entries |
| `POST` | `/api/grid/broker/ghost` | `{message}` -> ghost terminal response |
| `GET` | `/api/hud/state` | Universal HUD state (inherited from BaseScene) |
| `GET` | `/api/world/status` | WorldSim status + active events |

---

## Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `hud_update` | server -> client | Full `PlayerState.to_dict()` |
| `world_event` | server -> client | `{type, description, faction, intensity}` |
| `market_update` | server -> client | Updated catalogue after buy/sell |
| `quest_complete` | server -> client | `{faction, reward, standing_delta}` |
| `ghost_message` | server -> client | `{message, intensity, heat_impact}` from `GHOST_MESSAGES_RICH` |

---

## Scene Configuration

```yaml
# config/default.yaml
scenes:
  grid:
    port: 5569
    accent_color: "#00ff88"
    enabled: true
```

```python
# content/scenes/grid/__init__.py
from .grid_scene import GridScene
__all__ = ["GridScene"]
```

---

## Cross-References

- [Scenes](SCENES.md) — Full scene listing and port assignments
- [Economy Guide](ECONOMY_GUIDE.md) — EconomyManager, market system, territory bonuses
- [Game Systems](GAME_SYSTEMS.md) — WorldSim, economy, factions, NPCs, events
- [Neon HUD](NEON_HUD.md) — PlayerState API, HUD strip, faction standings
- [Skills](SKILLS.md) — `world` pack (10 shared world skills)

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated header to v1.50, fixed cross-references |
| v1.04 | 2026-03-15 | Added Ghost Terminal 0xGH0ST integration |
| v0.75 | 2026-03-10 | Initial THE GRID documentation — 4 zones, 7 skills, 15 travel nodes |
