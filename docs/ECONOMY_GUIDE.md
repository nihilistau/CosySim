# CosySim Economy Guide

> CosySim Documentation — v1.52.0 [2026-03-26]
>
> Complete reference for NeonCity's cross-scene credit economy, dynamic market
> system, territory-driven bonuses, and consequence engine. Every credit earned
> in the Casino can be spent in the Heist — the economy is global and persistent.

---

## Quick Start

```python
from engine.economy.economy import get_economy_manager, TransactionType

em = get_economy_manager()
em.transact(100, TransactionType.EARN, "casino", "Won at blackjack")
balance = em.get_balance("player")      # 1100 (default start: 1000)
history = em.get_history("player")      # List[Transaction]
```

```python
from engine.world.market import get_market

mkt = get_market()
prices = mkt.get_prices("DOWNTOWN")
result = mkt.buy("DOWNTOWN", "stim_pack", quantity=2, player_id="player")
mkt.tick()                              # advance supply/demand simulation
```

---

## 1. EconomyManager

Source: `engine/economy/economy.py`

The `EconomyManager` provides persistent credit balances and full transaction
history for all players across every scene. Balances are backed by Nexus and
cached in-process for performance.

### Default Balance

New players start with **C1,000** (configurable via `_DEFAULT_BALANCE`).

### TransactionType Enum

| Type | Description |
|------|-------------|
| `EARN` | Generic income (mini-games, missions, rewards) |
| `SPEND` | Purchases, service fees, entry costs |
| `BET_WIN` | Winnings from arena or casino bets |
| `BET_LOSS` | Losses from bets (deducted at placement) |
| `TRANSFER` | Player-to-player or NPC-to-player transfer |
| `DEBT` | Forced negative balance (loan shark, penalties) |
| `DEBT_PAYMENT` | Paying off an existing debt |
| `REWARD` | System-granted reward (quests, achievements) |
| `PENALTY` | Forced deduction (fines, faction punishment) |

### Core Methods

```python
em = get_economy_manager()

# Record a transaction (returns Transaction dataclass)
txn = em.transact(50, TransactionType.EARN, "heist", "Fence payout")
print(txn.balance_after)   # updated balance

# Query balance
balance = em.get_balance("player")

# Query transaction history
history = em.get_history("player")   # List[Transaction]

# Leaderboard across all players
leaders = em.get_leaderboard()

# Check for debt
debt = em.check_debt("player")       # absolute debt amount or 0
```

### Transaction Dataclass

```python
@dataclass
class Transaction:
    id: str               # Unique UUID
    type: TransactionType
    amount: int           # Signed delta (positive = gain)
    scene: str            # Source scene identifier
    description: str      # Human-readable note
    timestamp: float      # Unix epoch
    balance_after: int    # Balance immediately after
```

### InsufficientFundsError

Raised when a spend/loss would push balance below zero. Debt-type transactions
are exempt — they intentionally allow negative balances:

```python
from engine.economy.economy import InsufficientFundsError

try:
    em.transact(-500, TransactionType.SPEND, "shop", "Tried to buy")
except InsufficientFundsError as e:
    print(f"Need {e.amount}, have {e.balance}")
```

### MCP Integration

Every transaction emits an `economy.transaction` event via the EventBus,
allowing other systems to react (UI updates, news ticker, faction AI).

### Nexus Persistence

Balances and transaction logs are stored as Nexus entries, surviving restarts
and remaining queryable by agents and the knowledge layer.

---

## 2. Market System

Source: `engine/world/market.py`

NeonCity's dynamic market models **27 tradable goods** across **12 shops** in
**6 districts**. Prices shift with supply, demand, territory control, and
world events.

### Good Categories

| Category | Examples | Typical Price Range |
|----------|----------|---------------------|
| **Weapons** | Street Pistol, Plasma Cutter, Smart Rifle, Mono Blade, EMP Grenade | C250–C1,500 |
| **Tech** | Basic Cyberdeck, Neural Booster, Stealth Module, Icebreaker v2 | C200–C1,200 |
| **Consumables** | Stim Pack, Medkit, Synth Food, Neuro Stim, Trauma Patch | C15–C200 |
| **Contraband** | Synth Dust, Forged ID, Stolen Data, Black ICE Chip | C300–C1,000 |
| **Intel** | Faction Dossier, Access Codes, Street Rumor, Blueprint | C100–C800 |
| **Luxury** | Designer Jacket, Vintage Whiskey, Holo Art, Synth Pet | C250–C1,000 |

### Price Formula

Prices are computed dynamically from supply and demand:

```
current_price = base_price x (1 + (demand - supply) / 100)
```

- **Supply** (0–100): High supply -> lower price
- **Demand** (0–100): High demand -> higher price
- Default equilibrium: supply=50, demand=50 -> price = base_price

Shop `price_modifier` applies on top (e.g., 0.85 for discount shops, 1.3 for
luxury stores).

### Good Dataclass

```python
@dataclass
class Good:
    id: str
    name: str
    category: str          # GoodCategory value
    base_price: int
    supply: float = 50.0   # 0-100
    demand: float = 50.0   # 0-100
    description: str = ""
    illegal: bool = False   # triggers heat if True
    rarity: int = 1        # 1 (common) to 5 (legendary)

    @property
    def current_price(self) -> int:
        modifier = 1.0 + (self.demand - self.supply) / 100.0
        return max(1, int(self.base_price * modifier))
```

### Districts & Shops

| District | Shops | Specialty |
|----------|-------|-----------|
| **Downtown** | Neon Arms (weapons/tech), Velvet Boutique (luxury/consumables) | High-end, +10–20% markup |
| **Combat Zone** | Iron Market (weapons), Back Alley Deals (contraband) | Discount, -10–15% |
| **Highrise** | Corp Store (tech/luxury), Skyline Pharmacy (consumables) | Premium, +15–30% |
| **Underworld** | Shadow Bazaar (contraband/intel), Data Den (intel/tech) | Black market, -5–20% |
| **Tech District** | Tech Emporium (tech), Hacker Supply (tech/intel) | Tech specialist, +/-0–10% |
| **Outskirts** | Scrapyard Shop (mixed), Wanderer Trade Post (mixed) | Cheapest, -15–25% |

Shops may require minimum reputation to access (e.g., Back Alley Deals
requires reputation >= -50).

### Market API

```python
mkt = get_market()

# Browse
prices = mkt.get_prices("DOWNTOWN")        # all goods with current prices
good = mkt.get_good("stim_pack")           # single Good dataclass
shops = mkt.get_shops("COMBAT_ZONE")       # shops in a district

# Trade
result = mkt.buy("DOWNTOWN", "stim_pack", quantity=3, player_id="player")
trade_log = mkt.get_history()              # List[TradeRecord]

# Simulation
mkt.tick()   # advance supply/demand one step toward equilibrium
```

### Simulation Tick

Calling `mkt.tick()` advances the economy one step:
- Supply drifts toward equilibrium (50)
- Demand responds to recent trades and world events
- Territory control multipliers are recomputed
- State is auto-saved to `data/market_state.json`

---

## 3. Territory Bonuses

Source: `engine/world/territory.py`

Six factions compete for control across 16 NeonCity districts. Territory
control grants economic bonuses.

### Faction Specialties

| Faction | Specialty Goods | Economic Bonus |
|---------|-----------------|----------------|
| **OmniCorp** | Tech, Luxury | Cheaper tech in controlled districts |
| **NeoTech** | Tech, Weapons | Weapons discounts |
| **BlackMarket** | Contraband, Intel | Reduced heat, lower contraband prices |
| **Ghost_Net** | Intel, Tech | Intel availability boost |
| **SynthSec** | Weapons, Consumables | Cheaper stims and arms |
| **DeepState** | Intel, Contraband | Secret shop access |

### Control -> Price Effect

The dominant faction in a district nudges prices for their specialty goods
downward (-5% to -15%) while competing goods may rise.

```python
from engine.world.territory import get_territory_manager

mgr = get_territory_manager()
status = mgr.get_district_control("DOWNTOWN")
mgr.shift_control("DOWNTOWN", "Ghost_Net", +5.0, reason="completed mission")
```

---

## 4. Black Market

Contraband goods are marked with `illegal: True` and trigger **heat** — the
player's wanted level. Higher heat means:
- Increased prices from legitimate shops
- SynthSec patrols and random encounters
- Reputation penalties with law-aligned factions

Black market shops (Back Alley Deals, Shadow Bazaar) have lower prices but
require negative reputation thresholds to access.

---

## 5. Consequence Engine

Source: `engine/mechanics/consequences.py`

Actions in one scene produce delayed consequences that surface later — even in
a different scene. A casino debt triggers a loan shark call 24 hours later.

### ConsequenceType Enum

| Type | Description |
|------|-------------|
| `CONTACT` | NPC contacts or visits the player |
| `ITEM_DELIVERY` | An item arrives for the player |
| `REPUTATION_SHIFT` | Scheduled reputation adjustment |
| `ECONOMY_TRANSACTION` | Monetary credit or debit |
| `WORLD_EVENT` | Change to global world state |
| `CHARACTER_MESSAGE` | Character sends the player a message |
| `THREAT` | Ambush, debt collector, bounty hunter |

### Scheduling a Consequence

```python
from engine.mechanics.consequences import get_consequence_store, ConsequenceType

store = get_consequence_store()

# Casino scene -- player owes Mira 5000cr
c = store.build_debt_consequence(
    scene="casino",
    amount=5000,
    debtor="player",
    creditor_char="mira",
)

# Poll for due consequences (from any scene's tick loop)
due = store.poll(scene="lounge", player_id="player")
for consequence in due:
    execute_consequence(consequence)
    store.mark_fired(consequence.id)
```

Consequences are persisted in Nexus and survive restarts.

---

## 6. Cross-Scene Economy Flow

The economy connects all scenes in a living world:

```
Casino loss > C100 -> debt scheduled -> 24h later "Mira" calls in Lounge
Arena bet win -> credits added -> NeonCity faction economy updated via EventBus
Heist payout -> fence cut -> territory reputation shift -> market prices adjust
Shop purchase -> supply drops -> demand rises -> prices tick upward
```

### EventBus Integration

Every transaction fires `economy.transaction` on the global EventBus:

```python
from engine.events.event_bus import get_event_bus

bus = get_event_bus()
bus.subscribe("economy.transaction", lambda evt: update_news_ticker(evt))
```

### News System

Major economic events (large transactions, market crashes, faction economy
shifts) automatically feed into the news ticker via the World Announcer.

---

## 7. Economy Skills

Economy-related MCP skills available to LLM agents:

| Skill | Pack | Description |
|-------|------|-------------|
| `earn_credits(amount, reason)` | `world` | Award credits (2s cooldown) |
| `spend_credits(amount, reason)` | `world` | Deduct credits with validation |
| `get_player_state_info()` | `world` | Location, credits, reputation, heat |
| `place_arena_bet(match_id, target, amount)` | `arena` | Bet on arena match |

Example skill:

```python
@skill(pack="world", category=SkillCategory.GAME, cooldown=2,
       description="Award credits to the player")
def earn_credits(amount: int, reason: str = "reward") -> str:
    em = get_economy_manager()
    txn = em.transact(amount, TransactionType.EARN, "world", reason)
    return f"Earned C{amount}. Balance: C{txn.balance_after}"
```

---

## 8. Configuration

Economy tuning in `config/default.yaml`:

```yaml
economy:
  default_balance: 1000        # starting credits for new players
  max_debt: -5000              # minimum allowed balance for DEBT type
  transaction_log_limit: 500   # max history entries per player

market:
  tick_interval: 300           # seconds between simulation ticks
  supply_drift_rate: 0.5       # speed of supply returning to equilibrium
  demand_response: 1.2         # demand multiplier from trades
  territory_bonus: 0.15        # max faction discount (15%)

consequences:
  poll_interval: 60            # seconds between consequence polls
  max_pending: 100             # max pending consequences per player
```

Access via:

```python
cfg = get_config()
start_balance = cfg.get("economy.default_balance", 1000)
tick_rate = cfg.get("market.tick_interval", 300)
```

---

## 9. Living World Integration

The economy is deeply woven into NeonCity's living world:

- **Faction AI** (`engine/world/faction_ai.py`) adjusts faction behavior based
  on economic control of districts
- **NPC Routines** (`engine/world/npc_routines.py`) have NPCs visit shops,
  make purchases, and generate organic market activity
- **World Events** (`engine/world/neon_city_events.py`) can crash or boom
  markets (supply raids, tech breakthroughs, faction wars)
- **News Generator** (`engine/world/news_generator.py`) reports significant
  market movements and economic events
- **Territory** (`engine/world/territory.py`) — district control shifts
  economic advantages between factions

---

## Cross-References

- [Architecture](ARCHITECTURE.md) — System overview
- [Game Systems](GAME_SYSTEMS.md) — All game mechanics
- [Scenes](SCENES.md) — Scene listing and ports
- [Arena Guide](ARENA_GUIDE.md) — Arena betting integration
- [Character System](CHARACTER_SYSTEM.md) — Character economy interactions
- [Contributing](CONTRIBUTING.md) — Creating new content
- [Configuration](CONFIGURATION.md) — Full config reference

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated header to v1.50, fixed cross-references (CONTENT_GUIDE -> CONTRIBUTING), removed duplicate Game Systems link |
| v1.04 | 2026-03-15 | Initial comprehensive economy documentation with market system, territory, consequences |
