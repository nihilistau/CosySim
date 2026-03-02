# CosySim Scene Guide

> Per-scene game mechanics reference for all 9 active scenes. v0.69b.
> For system scenes (coders, heist, games, hub, intel_hub) see [SCENES.md](./SCENES.md).

---

## Overview

CosySim runs 9 active user-facing scenes on ports 5555–5563. Every scene shares the
Dark Renaissance design system: black glass UI, Three.js 3D particles, BenchHUD, universal
chrome (navbar_v2, admin_overlay, Aria widget), and the MCP v3.x governance framework.

### Common Scene Architecture

```
BaseScene
  ├── MCPSceneMixin          — MCP tool registration, skill packs, scene node
  ├── NexusSceneMixin        — scene data persistence in Nexus
  └── Flask + SocketIO       — HTTP REST + real-time Socket.IO events
```

Every scene exposes:

| Endpoint | Description |
|----------|-------------|
| `GET /` | Main scene UI |
| `POST /api/chat` | Primary LLM interaction |
| `GET /api/state` | Current scene state |
| `POST /api/tts/speak` | Text-to-speech synthesis |
| `GET /health` | Health check |

---

## 1. THE PENTHOUSE — Bedroom Scene

**Scene ID:** `bedroom` | **Port:** `5555` | **Accent:** `#e91e8c` (pink)

### Theme

A private, adult roleplay space. Multiple AI agents inhabit the room simultaneously,
each with a full emotional stat vector, tracked outfit and position, and a Director
orchestrating scene narrative. Designed as the premier intimacy and companion scene.

### Characters

| Character | Role | Personality |
|-----------|------|-------------|
| Luna | Primary companion | Warm, playful, responsive to emotional depth |
| Aria | Narrator / Director voice | Observant, scene-aware, atmospheric |
| *(loadable from DB)* | Scene guests | Pulled from `content/simulation/database` |

### Emotion Stats (10 bars, 0–100 each)

| Stat | Unlocks |
|------|---------|
| `warmth` | Kissing gate (≥ 30) |
| `comfort` | Kissing gate (≥ 25) |
| `arousal` | Caress gate (≥ 40) → Striptease (≥ 55) → Intimate (≥ 70) → Explicit (≥ 80) → Depraved (≥ 90) |
| `openness` | Caress gate (≥ 40), Intimate gate (≥ 60) |
| `compliance` | Striptease gate (≥ 50) |
| `happiness` | General mood |
| `horniness` | Explicit gate (≥ 60), Depraved (≥ 80) |
| `fear` | Fear-play scenes |
| `affection` | Aftercare mode (≥ 60) |
| `trust` | Scene unlocks |

### Intimacy Gate System

Gates are MCP rules evaluated by the `SceneRulesEngine`. Each gate has a condition
(stat thresholds + optional consent flags) and a set of effects (narrative injections,
directive locks, atmosphere changes):

```
light_touch_gate  → always available
kiss_gate         → warmth ≥ 30, comfort ≥ 25
caress_gate       → arousal ≥ 40, openness ≥ 40
striptease_gate   → arousal ≥ 55, compliance ≥ 50
intimate_gate     → arousal ≥ 70, openness ≥ 60, consent=True
explicit_gate     → arousal ≥ 80, horniness ≥ 60
depraved_gate     → arousal ≥ 90, horniness ≥ 80
aftercare_rule    → arousal ≤ 20, affection ≥ 60
```

### Positions & Outfits

Characters track position (20 options: standing, sitting, kneeling, laying down,
crouching, leaning, dancing, etc.) and outfit (15 options: dressed, swimwear, lingerie,
nightgown, silk robe, towel, costume, nothing, topless, etc.).

### Props System

Each prop modifies stats on use:

| Prop | Effect |
|------|--------|
| Wine Glass | +10 drunkenness |
| Champagne | +15 drunkenness, +5 happiness |
| Massage Oil | +20 pleasure, +10 arousal |
| Vibrator | +25 arousal, +15 horniness |
| Blindfold | +15 arousal, +10 fear |
| Feather Tickler | +10 pleasure, +5 happiness |

### Director Tools

The `SceneDirector` can inject into the scene via 7 tools:

- **Whisper** — secret nudge to one agent's system prompt
- **Give Line** — agent must voice an exact line (may resist)
- **Give Action** — agent performs a described action
- **Story Beat** — upcoming plot point injected as scene context
- **Set Scenario** — load a premade scenario arc
- **Env Event** — environmental events (dim lights, lock door)
- **Adjust Stat** — directly tweak any stat for any character

### Key Skills

`bedroom_skills.py` registers the scene skill pack. Skills include:
`adjust_stat`, `set_outfit`, `set_position`, `whisper`, `give_line`,
`give_action`, `story_beat`, `set_atmosphere`, `inject_prop`, `use_prop`

### Special Features

- **CharacterMemory**: Characters recall past interactions via Nexus semantic search;
  `CharacterMemoryInterceptor` (priority 7) injects memories into every system prompt
- **Director beats**: `SceneDirector` fires narrative beats based on stat progression
- **ContentGate**: Explicit content gated by player's content intensity profile (0–3)
- **Competition escalation**: When arousal ≥ 50, characters try to outdo each other

---

## 2. SIGNAL — Phone Scene

**Scene ID:** `phone` | **Port:** `5556` | **Accent:** `#00ff88` (neon green)

### Theme

A phone messaging scene where the player texts AI companions. Features an overarching
5-act mystery arc involving a character called `0xGH0ST` who reveals themselves across
escalating trust levels. Autonomous texting keeps the scene alive between player turns.

### Characters

| Character | Role |
|-----------|------|
| 0xGH0ST | Primary contact — mysterious hacker identity, 5-act reveal arc |
| Aria | Narrator / call handler |
| *(loadable)* | Additional contacts |

### Heat Gate System

Conversation intensity unlocks new dialogue modes:

| Gate | Threshold | Unlocks |
|------|-----------|---------|
| `always_friendly` | Always | Normal warm conversation |
| `flirt_mode` | warmth ≥ 35, happiness ≥ 30 | Flirty messages, playful style |
| `sext_gate` | arousal ≥ 55, openness ≥ 50, trust ≥ 40 | Explicit texting mode |

### Autonomous Texting

Characters text the player unprompted based on relationship warmth:

| Relationship State | Cooldown Range |
|--------------------|---------------|
| Cold (low trust/affection) | 10–30 minutes |
| Warm (growing relationship) | 3–10 minutes |
| Hot (intimate/flirty) | 1–4 minutes |
| Obsessed (affection ≥ 75 or trust ≥ 80) | 20–90 seconds |

### Phone Apps

The phone scene includes simulated phone apps (`content/scenes/phone/apps/`) for
realistic mobile UX: contacts list, media gallery, settings.

### Mystery Arc — 0xGH0ST

The `0xGH0ST` character follows a 5-act reveal structure:
- **Act 1**: Anonymous contact; cryptic messages
- **Act 2**: Trust-based clues emerge; investigation board activates
- **Act 3**: Identity hints; player must solve cipher-style puzzles
- **Act 4**: Partial reveal; emotional investment deepens
- **Act 5**: Full reveal; relationship transforms based on choices

### Key Skills

`phone_skills.py`: `send_message`, `receive_message`, `change_heat`, `unlock_media`,
`advance_mystery_arc`, `trigger_autotxt`, `set_relationship_mode`

---

## 3. THE VELVET PIT — Lounge Scene

**Scene ID:** `lounge` | **Port:** `5557` | **Accent:** `#d97706` (amber)

### Theme

A 1920s underground jazz speakeasy. Smoke-and-neon atmosphere with jazz music,
cocktails, and two resident characters — Lola Voss (singer/owner) and Viktor Marlowe
(bartender). All interactions are governed via MCP rules and consequence chains.

### Characters

| Character | Role | Secrets |
|-----------|------|---------|
| Lola Voss | Singer, owner, hostess | 3 unlockable secrets gated by trust |
| Viktor Marlowe | Bartender, confidant | 3 unlockable secrets gated by trust |

### Heat Meter

A scene-level `heat` stat (0–100) evolves the atmosphere:

| Heat Level | Atmosphere |
|------------|-----------|
| 0–30 | Quiet — intimate tables, soft music |
| 31–60 | Lively — dance floor fills, conversation buzzes |
| 61–85 | Rowdy — crowd noise, Lola performs, Viktor busy |
| 86–100 | Brawl — MCPTimer triggers consequence chain |

The heat meter ticks via `MCPTimer` and responds to drink orders, stage performances,
and random atmospheric events.

### Cocktail System

`COCKTAILS` dict defines drinks with stat effects. Orders trigger `MCPFramework`
consequence chains: e.g., premium whisky → `+10 trust, +5 heat`; absinthe →
`+20 heat, -10 inhibition` (with 3-turn delayed drunkenness consequence).

### Stage Performance

Lola's stage performances are timed events (`MCPTimer` → song duration). On completion,
`mood_contagion` fires: all character moods shift towards the song's mood tag
(e.g., `melancholy`, `sensual`, `upbeat`).

### Trust Economy

Trust gates access to:
- **Back room** (`trust ≥ 65`) — private table, premium pours, secrets
- **Lola's full secret set** (`trust ≥ 50`)
- **Viktor's candid stories** (`trust ≥ 40`)

### Cross-Agent Communication

Lola and Viktor communicate via `MCPFramework.cross_scene_send`, enabling reactions
like Viktor alerting Lola when a VIP arrives, or Lola asking Viktor to cut someone off.

### Key Skills

`lounge_skills.py`: `order_drink`, `request_song`, `tip_performer`, `enter_back_room`,
`unlock_secret`, `increase_heat`, `cool_atmosphere`, `mood_contagion`

---

## 4. THE RUSTY ANCHOR — Tavern Scene

**Scene ID:** `tavern` | **Port:** `5558` | **Accent:** `#b45309` (brown/copper)

### Theme

A gritty dockside tavern and reference implementation for new scene developers — it
demonstrates every major MCP framework feature in one scene. Ember particles, rough-hewn
UI, time-of-day cycle, and 4 NPCs with distinct personalities.

### Characters (4 NPCs)

| NPC | Role | Personality |
|-----|------|-------------|
| Griggs | Barkeep | Gruff, loyal, knows everything |
| Old Marta | Village elder | Cryptic, rumour-laden |
| Dax | Mercenary | Bold, mercenary, quest-giver |
| The Stranger | Mystery arrival | Unpredictable, scripted entrance |

### Time-of-Day Cycle

The tavern cycles through: `morning` → `afternoon` → `evening` → `night` → `midnight`
via `MCPTimer`. Each phase changes available NPCs, quest availability, and atmosphere.

### Quest Board System

- **Accept Quest**: Player selects from available quests; `EventChain` fires quest-start
- **Progress Quest**: Multi-stage objectives tracked in `GameState`
- **Complete Quest**: Rewards (gold, reputation, lore unlocks) distributed via `EconomyManager`

### Dice Gambling

Three dice games run on a gold economy:
- **Simple dice** — bet gold, roll d6, highest wins
- **High/Low** — bet on outcome band
- **Sequence** — three dice in order (high payout, low odds)

Results use `MCPTimer` for dramatic timing.

### Rumour System

NPCs drop rumours at trust thresholds. Rumours unlock quest board entries — e.g., Old Marta's
rumour about the harbour reveals the smuggling quest. All rumours tracked in `GameState`.

### Atmosphere System

`heat_meter` + `time_of_day` combine to produce a compound atmosphere descriptor injected
into every NPC system prompt:

```
quiet_morning → loud_evening → rowdy_night → brawl_midnight
```

### Key Skills

`tavern_skills.py` (11 skills): `order_drink`, `accept_quest`, `roll_dice`, `tip_bard`,
`ask_rumour`, `pick_fight`, `make_peace`, `buy_equipment`, `hire_mercenary`, `rest_room`

---

## 5. CLUB NOIR — Casino Scene

**Scene ID:** `casino` | **Port:** `5559` | **Accent:** `#f97316` (neon orange)

### Theme

A high-stakes underground casino. Sparks and neon particles, two resident characters
(Dealer Jack, Hustler Mira), and a full economy integration with debt consequences.
Demonstrates MCPGameSession (tracked hands with turn history) and cross-scene bridging.

### Characters

| Character | Role | Personality |
|-----------|------|-------------|
| Dealer Jack | House dealer | Calm, precise, slightly ominous |
| Hustler Mira | Fellow player | Charming, unpredictable, reads people |

### Card Game — Blackjack

- Standard Blackjack rules: beat the dealer without exceeding 21
- `MCPGameSession` tracks every hand with full turn history
- Hands dealt via `deal_hand()` utility; evaluated by `evaluate_hand_simple()`
- Jack has tell-detection: `TELL_DESCRIPTIONS` define player tells that Mira narrates

### Economy Integration

- All bets deducted via `EconomyManager` at hand start
- Winnings credited via `TransactionType.GAMBLING_WIN`
- **Debt system**: players below 0 credits enter debt — `ConsequenceStore` schedules
  consequences (reputation drop with SYNDICATE, Mira turns cold, Jack adds interest)
- `luck_streak` stat: win 3+ hands → luck bonus; lose 3+ → luck penalty

### Cross-Scene Reputation Ripples

Casino events trigger `ReputationManager.apply_cross_scene_ripple()`:

| Event | Reputation Effect |
|-------|-------------------|
| `debt_created` | SYNDICATE −10, Mira −5 |
| `cheat_detected` | CORPORATE −30, SYNDICATE −20 |

### Random Atmospheric Events

`pick_random_event()` fires each turn from `RANDOM_EVENTS` pool:
security sweep, VIP arrival, chip shortage, power flicker, mysterious win streak.

### Drink System

`CASINO_DRINKS` catalogue with stat effects. Ordering drinks triggers consequence chains:
`confidence +10, focus −5` for whisky; `luck +5` for champagne.

### Key Skills

`casino_skills.py`: `place_bet`, `deal_cards`, `hit`, `stand`, `double_down`, `split`,
`buy_drinks`, `read_tell`, `challenge_mira`, `cash_out`, `settle_debt`

---

## 6. THE OBSCURA — Gallery Scene

**Scene ID:** `gallery` | **Port:** `5560` | **Accent:** `#7c3aed` (violet)

### Theme

A dark art gallery with disturbing and adult exhibits. Spotlight framing, slow ambient
audio, and characters who inhabit the roles of curator, critic, and private collector.
Art confronts the viewer across comfort boundaries. ComfyUI generates dynamic new works.

### Characters

| Character | Role |
|-----------|------|
| The Curator | Cold, precise, knows the darkness behind every piece |
| The Critic | Intellectual, provocative, tests the viewer's reactions |
| *(Private collector)* | Appears during private viewings |

### Exhibit System

Exhibits are stored in a catalogue with:
- `title`, `artist`, `medium`, `description`
- `content_intensity` (0–3) — pieces above the player's ContentGate profile are blurred
- `price` — for private viewing or purchase

### ContentGate Integration

Adult or disturbing pieces are gated by `ContentGate`:

```python
# Intensity levels:
# 0 — All audiences
# 1 — Mature themes (blurred unless profile ≥ 1)
# 2 — Adult content (blurred unless profile ≥ 2)
# 3 — Extreme content (blurred unless profile ≥ 3)
```

Private viewings are unlocked per-exhibit for **250 credits** via `EconomyManager`.

### SceneArtManager — AI Art Generation

The gallery is the primary consumer of `SceneArtManager`:
- **Commission new works**: Player or Curator commissions a piece via ComfyUI prompt
- **Character portraits**: NPCs have AI-generated portraits tied to their emotional state
- **Generated works cached in Nexus**: `SceneArtManager` stores generated images in Nexus
  with ContentGate tags for reuse

### SceneDirector Integration

The gallery uses `SceneDirector` narrative beats to evolve the exhibit's mood:
- As the player spends more time (or credits), darker exhibits become accessible
- Director beats: `GALLERY_OPENING`, `PRIVATE_VIEWING`, `DARK_REVELATION`, `COMMISSION_COMPLETE`

### Key Skills

`gallery_skills.py`: `view_exhibit`, `request_private_viewing`, `commission_art`,
`purchase_artwork`, `speak_with_curator`, `read_artist_statement`, `unlock_exhibit`

---

## 7. THE COLOSSEUM — Arena Scene

**Scene ID:** `arena` | **Port:** `5561` | **Accent:** `#dc2626` (crimson)

### Theme

A tactical card-game arena. Players choose fighters, place bets, and watch AI-driven
combat resolved through the `ArenaEngine`. NLM provides live commentary. The Arena Guild
faction tracks reputation across scenes.

### Game Mechanics — ArenaEngine

The `ArenaEngine` runs turn-based card combat:

```
Fighter A draws 3 cards → plays 1 attack card → Fighter B defends → calculate damage
```

**Card types:**

| Card | Effect |
|------|--------|
| Strike | Direct damage based on strength stat |
| Block | Reduces incoming damage this turn |
| Dodge | Chance to negate all damage |
| Power | Charges special ability |
| Combo | Multi-hit if previous card was Strike |
| Finisher | High damage, once per match |

**Fighter stats:** `strength`, `agility`, `endurance`, `speed`, `special`

### AI Fighters

The arena features pre-built AI fighter profiles that use the `ArenaEngine` AI:
- `BruteForce` — high strike, low dodge
- `Shadowstep` — high dodge/block, medium damage
- `BerserkMode` — escalating damage multiplier
- `TacticalMind` — reads opponent patterns

### Betting System

- Pre-fight: Place bet on fighter A or B (via `EconomyManager`)
- Mid-fight: Live odds update based on health delta
- Post-fight: Winnings distributed; ARENA_GUILD reputation adjusted:
  - Win: `ARENA_GUILD +10`
  - Upset win: `ARENA_GUILD +20`
  - Loss: no change

### NLM Commentary

The arena is the only scene with live NLM commentary — each round sends a summary to
the Nexus Q&A pipeline, which returns a narration style conditioned on fight state.

### Key Skills

`arena_skills.py`: `choose_fighter`, `place_bet`, `play_card`, `activate_special`,
`use_item`, `call_timeout`, `surrender`, `watch_replay`, `challenge_ai`

### Special Features

- **Spectator mode**: Watch AI vs. AI fights without betting
- **Tournament bracket**: Multi-fight bracket tracked in `GameState`
- **Reputation cross-scene**: Arena Guild standing affects welcome in NeonCity's
  Underground Club district

---

## 8. THE SHATTERED THRONE — Realm Scene

**Scene ID:** `realm` | **Port:** `5562` | **Accent:** `#6d28d9` (dark purple)

### Theme

A dark fantasy RPG realm. Turn-based d20 combat, skill checks, exploration, and a
sanity system that warps narrative as it drops. The typewriter effect and gothic UI
create an oppressive, literary atmosphere.

### Combat System (d20)

Initiative roll: `d20 + agility`. Higher initiative acts first.

**Attack resolution:**
```
Roll d20 + strength_mod (stat // 2 − 5)
≥ enemy AC → hit → damage = weapon.damage + strength_mod
Natural 20 → critical hit (2× damage)
```

**Death on 0 HP:** Lose a random inventory item, respawn at camp with 50% HP.

**Consumable healing:** Health potions restore their `heal` value; max 1 per combat turn.

### Skill Check System

```
Roll d20 + stat_modifier   vs.   Difficulty Class (DC)
≥ DC → success
Natural 20 → critical success (bonus loot or extra effect)
Natural 1  → critical fail (negative consequence)
```

Skill checks use the relevant stat modifier: `strength`, `agility`, `intelligence`,
`charisma`, `perception`.

### Sanity System

`sanity` stat (0–100). Events that drain sanity:
- Witnessing eldritch events: −10 to −30
- Combat deaths of companions: −15
- Dark arc revelations: −20

At sanity thresholds, narrative style changes:
- sanity ≤ 50: Typewriter text stutters
- sanity ≤ 25: NPC dialogue becomes unreliable (may be hallucinated)
- sanity ≤ 10: Full horror mode — Director injects paranoid narration

### Inventory System

Items tracked in `SceneStateManager`. Item categories:
`weapon`, `armour`, `consumable`, `key_item`, `relic`

Relics have unique passive effects injected into the system prompt.

### Dark Arc System

Pre-scripted story arcs (`SET_SCENARIO` Director tool):
- **The Fallen King** — political intrigue, 5 acts
- **The Abyss Gate** — cosmic horror, sanity-heavy
- **The Cursed Bloodline** — family tragedy, 4 acts

### Key Skills

`realm_skills.py`: `attack`, `cast_spell`, `use_item`, `skill_check`, `explore_area`,
`talk_to_npc`, `rest_camp`, `examine_relic`, `open_chest`, `flee_combat`

---

## 9. NEON CITY — NeonCity Scene

**Scene ID:** `neoncity` | **Port:** `5563` | **Accent:** `#06b6d4` (cyan)

### Theme

A living cyberpunk city hub — the most fully wired scene in terms of engine module
integration. Six factions fight for control across five districts. The night never ends.
Also includes the `Glitch Storm` board game at `/board`.

### Factions (6)

| Faction | Engine ID | Color | Power | Motto |
|---------|-----------|-------|-------|-------|
| OmniCorp | CORPORATE | `#3b82f6` | 78 | Control through compliance |
| NeoTech | ARENA_GUILD | `#8b5cf6` | 52 | The future is a product |
| BlackMarket | UNDERGROUND | `#f97316` | 22 | Everything has a price |
| Ghost_Net | HACKER | `#22c55e` | 81 | Data is the new oxygen |
| SynthSec | SYNDICATE | `#ec4899` | 43 | We keep the peace — at a cost |
| DeepState | STREET | `#06b6d4` | 70 | The shadows run deeper than you know |

Faction power shifts dynamically via `WorldSim` events and player actions.

### Districts (5)

| District | Icon | Controlling Faction | Activity | NPCs |
|----------|------|---------------------|----------|------|
| Black Market | 🔫 | BlackMarket | Busy | FIXER, ARMORER, INFO_BROKER |
| Corporate Tower | 🏢 | OmniCorp | Quiet | EXEC, SEC_AGENT, CORP_LIAISON |
| Underground Club | 🎵 | SynthSec | Party | DJ, DEALER, CROWD |
| Hacker Den | 💻 | Ghost_Net | Always-on | NETRUNNER, SYSOP, GHOST |
| Arena Quarter | ⚔️ | NeoTech | Fight-night | PROMOTER, FIGHTER, BOOKIE |

### WorldState Integration

NeonCity is the **only scene fully wired to WorldState**:
- `get_world_state()` powers the game clock, weather, and faction power display
- `WorldSim` daemon advances faction power every 5 min via `world-sim-tick` scheduler task
- `EventBus` events from other scenes ripple faction power: casino debt → SynthSec +2

### Reputation System

NeonCity is the reputation hub — all 6 factions map to `FactionId` enum values:

```python
SYNDICATE  → SynthSec standing
CORPORATE  → OmniCorp standing
UNDERGROUND → BlackMarket standing
HACKER     → Ghost_Net standing
ARENA_GUILD → NeoTech standing
STREET     → DeepState standing
```

Faction reputation gates district access and NPC behaviour.

### Glitch Storm Board Game (`/board`)

A cyberpunk board game preserved from a prior version:
- Hex grid city map
- Players move through districts, triggering faction encounters
- Card-based event deck (40 cards, 6 categories)
- Win condition: control 3/5 districts or eliminate rival faction

### Economy Integration

- Credits earned/spent via `EconomyManager`
- Black Market purchases: contraband, weapons, intel
- Hacker Den: buy exploits, sell data
- Arena Quarter: fighter betting via `ArenaEngine`

### Key Skills

`neoncity_skills.py`: `move_district`, `talk_faction`, `buy_contraband`,
`run_hack`, `place_bounty`, `bribe_official`, `trigger_event`, `check_faction_power`,
`shift_power_balance`, `enter_underground`

---

## Cross-Scene Systems

All active scenes participate in shared cross-scene systems:

### Economy (EconomyManager)

Credits are shared across all scenes via `EconomyManager`. Transactions are typed
(`GAMBLING_WIN`, `PURCHASE`, `REWARD`, `DEBT`, `FINE`) and stored in Nexus.

### Reputation (ReputationManager)

Cross-scene ripple effects defined in `_RIPPLE_MAP`:

```python
("casino", "debt_created")   → SYNDICATE −10, mira −5
("heist",  "job_complete")   → UNDERGROUND +15
("arena",  "bet_win")        → ARENA_GUILD +10
("casino", "cheat_detected") → CORPORATE −30, SYNDICATE −20
```

### Memory (CharacterMemory)

Characters in all scenes remember the player via Nexus-backed `CharacterMemory`.
Memories persist across scene restarts. `CharacterMemoryInterceptor` (priority 7)
injects the top 5 relevant memories into every LLM call.

### EventBus

Scenes publish events via `EventBus.publish(event_type, payload)`. Other scenes and
engine modules subscribe to react. Key event types:
`scene.transition`, `economy.transaction`, `reputation.label_changed`,
`combat.outcome`, `quest.completed`, `investigation.clue_found`

---

*See [ARCHITECTURE.md](./ARCHITECTURE.md) for engine layer details.*
*See [SKILLS.md](./SKILLS.md) for the @skill decorator and full skill pack list.*
*See [ECONOMY_GUIDE.md](./ECONOMY_GUIDE.md) for EconomyManager deep-dive.*
*See [CHARACTER_SYSTEM.md](./CHARACTER_SYSTEM.md) for CharacterMemory and ReputationManager.*
