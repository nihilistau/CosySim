# CosySim Game Systems Reference

> Added in v1.02b "NeonCity 2: The Living City" — 8-phase overhaul

This document covers all game systems introduced in the NeonCity 2 overhaul.
Each system is a standalone Python module with its own MCP skills, tests, and
configuration. All systems use `threading.RLock` for thread safety and the
singleton pattern for global access.

---

## 1. Character Neurochemistry

**Module:** `engine/characters/neurochemistry.py`
**Skills:** `engine/skills/builtin/neurochemistry_skills.py` (3 skills)
**Tests:** `tests/test_neurochemistry.py`
**Config:** `config/default.yaml` → `neurochemistry:`

### Concept

Every NPC has 6 neurotransmitters (0.0–1.0) that drive their emotional state:

| Neurotransmitter | Role |
|-----------------|------|
| Dopamine | Pleasure, reward, motivation |
| Serotonin | Mood stability, well-being |
| Oxytocin | Trust, bonding, social connection |
| Cortisol | Stress, anxiety, fear |
| Adrenaline | Excitement, fight-or-flight |
| Endorphins | Pain relief, euphoria |

### Derived Emotions

Emotions are computed from neurotransmitter combinations:
- **Happy**: high dopamine + high serotonin
- **Anxious**: high cortisol + low serotonin
- **Trusting**: high oxytocin + low cortisol
- **Excited**: high adrenaline + high dopamine

### Stimulus Catalog

30+ stimuli mapped to neurotransmitter deltas. Examples:
- `compliment` → dopamine +0.15, serotonin +0.1, oxytocin +0.05
- `threat` → cortisol +0.3, adrenaline +0.25, serotonin -0.1
- `gift` → dopamine +0.2, oxytocin +0.15

### Usage

```python
from engine.characters.neurochemistry import get_neurochemistry_engine

engine = get_neurochemistry_engine()
engine.apply_stimulus("npc_lola", "compliment")
state = engine.get_state("npc_lola")
# → {dopamine: 0.65, serotonin: 0.6, ..., emotions: ["happy", "trusting"]}
```

### MCP Skills

- `check_mood(character_id)` — Get current emotional state
- `stimulate(character_id, stimulus)` — Apply a stimulus
- `read_neurochem(character_id)` — Raw neurotransmitter values

---

## 2. Skill Progression

**Module:** `engine/world/skill_progression.py`
**Skills:** `engine/skills/builtin/progression_skills.py` (3 skills)
**Tests:** `tests/test_neurochemistry.py` (same file)

### Skills

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

### Level Thresholds

| Level | XP Required | Title |
|-------|-------------|-------|
| 0 | 0 | Novice |
| 1 | 100 | Apprentice |
| 2 | 300 | Journeyman |
| 3 | 600 | Expert |
| 4 | 1000 | Master |
| 5 | 2000 | Legendary |

### Skill Checks

Roll vs difficulty + skill level + modifiers:
```python
result = progression.skill_check("player_1", "hacking", difficulty=3)
# → {success: True, roll: 14, threshold: 12, margin: 2}
```

### MCP Skills

- `check_skill(player_id, skill)` — Current skill level and XP
- `attempt_action(player_id, skill, difficulty)` — Perform skill check
- `view_xp(player_id)` — All skills overview

---

## 3. Territory System

**Module:** `engine/world/territory.py`
**Skills:** `engine/skills/builtin/territory_skills.py` (14 skills)
**Tests:** `tests/test_neurochemistry.py` (same file)

### Districts

16 districts with faction control percentages (sum to 100%):

| District | Type | Key Faction |
|----------|------|-------------|
| Downtown | Commercial | OmniCorp |
| Neon District | Entertainment | Yakuza |
| Industrial Zone | Manufacturing | Iron Syndicate |
| Port District | Shipping | Triads |
| ... | ... | ... |

### Crew HQ

Players establish a headquarters in one district with 5 room types:
- **Barracks** — Crew capacity
- **Armory** — Weapon storage, upgrades
- **Lab** — Cyberware research
- **Vault** — Credits storage
- **Comms** — Intelligence gathering

### Territory Missions

- **Capture** — Seize territory from a faction
- **Defend** — Protect controlled territory
- **Sabotage** — Weaken enemy faction presence
- **Recon** — Gather intelligence

---

## 4. Cyberspace Hacking

**Module:** `engine/world/cyberspace.py` (~1200 lines)
**Skills:** `engine/skills/builtin/cyberspace_skills.py` (15 skills)
**Tests:** `tests/test_cyberspace.py` (115 tests)

### Network Topology

Each target system is a graph of nodes connected by edges:
- **Access Points** — Entry nodes
- **Data Stores** — Contain credits, intel, secrets
- **CPU Nodes** — Processing power
- **ICE Nodes** — Security barriers

### ICE Types

| ICE | Effect | Break Method |
|-----|--------|--------------|
| Barrier | Blocks path | Icebreaker program |
| Trace | Alerts security | Cloak program |
| Black ICE | Damages hacker | High-power icebreaker |
| Data Wall | Encrypts data | Siphon program |
| Honeypot | Traps hacker | Detection skill check |

### Programs

| Program | Slots | Effect |
|---------|-------|--------|
| Icebreaker | 2 | Breaks ICE barriers |
| Cloak | 1 | Hides from trace programs |
| Siphon | 2 | Extracts data from nodes |
| Virus | 3 | Disables node functions |
| Backdoor | 1 | Creates persistent access |

### Cyberdeck Hardware

Upgradable hardware that determines capabilities:
- **RAM** — How many programs can run simultaneously
- **CPU** — Processing speed for breaking ICE
- **Slots** — Available program slots

### MCP Skills

15 skills including: `hack_connect`, `hack_move`, `hack_break_ice`,
`hack_run_program`, `hack_extract_data`, `hack_scan_node`,
`hack_install_backdoor`, `cyberdeck_status`, `cyberdeck_upgrade`, etc.

---

## 5. Living World Engine

**Modules:**
- `engine/world/market.py` — Economy
- `engine/world/npc_routines.py` — NPC schedules
- `engine/world/faction_ai.py` — Faction decisions
- `engine/world/living_world.py` — Orchestrator

**Skills:** `engine/skills/builtin/living_world_skills.py` (16 skills)
**Tests:** `tests/test_living_world.py` (92 tests)

### Market System

30 goods across 8 categories with supply/demand pricing:

| Category | Examples |
|----------|----------|
| Weapons | Pistol, SMG, Sniper Rifle |
| Cyberware | Neural Interface, Reflex Booster |
| Consumables | Stim Pack, Med Kit |
| Data | Encrypted Files, Access Codes |
| ... | ... |

12 shops located across districts. Prices affected by:
- Supply and demand
- Territory control multipliers
- Random market events
- Player bulk purchases

### NPC Routines

9 archetypes with time-based location schedules:
- **Worker** — Factory by day, bar by night
- **Criminal** — Streets at night, hideout by day
- **Vendor** — Shop during business hours
- **Guard** — Patrol routes, shift changes
- **Fixer** — Various meeting locations
- ... (4 more)

NPCs can be interrupted from routines and will resume afterward.

### Faction AI

6 factions with personality-driven decision making:

| Faction | Personality | Territory |
|---------|------------|-----------|
| OmniCorp | Corporate, methodical | Downtown |
| Yakuza | Traditional, honor-bound | Neon District |
| Iron Syndicate | Industrial, brute force | Industrial Zone |
| Ghost Net | Tech-savvy, decentralized | The Grid |
| Street Kings | Aggressive, territorial | Lower sectors |
| The Collective | Idealistic, grassroots | Various |

Each faction makes 1 strategic decision per 5 ticks: expand, fortify,
negotiate, attack, recruit, or withdraw.

### Weather System

Markov chain with 5 states:
Clear → Overcast → Rain → Acid Rain → Storm → Clear

Weather affects NPC behavior, market prices, and visibility.

### World Events

10 stochastic event templates with 20% spawn rate per tick:
- Power outage in district
- Gang shootout
- Corporate raid
- Data leak
- Street festival
- ... (5 more)

---

## 6. Multiplayer Foundation

**Modules:**
- `engine/multiplayer/session_manager.py` — Sessions
- `engine/multiplayer/presence.py` — Presence tracking
- `engine/multiplayer/messaging.py` — P2P messages
- `engine/multiplayer/leaderboards.py` — Rankings

**Skills:** `engine/skills/builtin/multiplayer_skills.py` (12 skills)
**Tests:** `tests/test_multiplayer.py` (85 tests)

### Session Management

Each player gets a `PlayerSession` with:
- Unique session ID
- Connected scene tracking
- Heartbeat/timeout (60s)
- Per-session state isolation

### Presence

Real-time tracking of who is where:
- Online/Away/Busy status
- Scene occupancy queries
- Auto-cleanup on disconnect
- Status change events via EventBus

### Messaging

P2P direct messages between players:
- Read/unread tracking
- Conversation threading by sender+receiver
- Message history with pagination
- Separate from NPC conversations

### Leaderboards

6 categories with weekly and all-time splits:
- Credits, Reputation, Kills, Heists, Hacking, Territory

---

## 7. In-Game World News

**Modules:**
- `engine/world/news_generator.py` — Article generation
- `engine/world/news_ticker.py` — Ticker + Flask API

**Skills:** `engine/skills/builtin/world_news_skills.py` (10 skills)
**Tests:** `tests/test_world_news.py` (103 tests)
**Frontend:** `cosysim-news-ticker.css` + `cosysim-news-ticker.js`

### WorldNewsGenerator

Subscribes to 8 EventBus event types and transforms game events into
cyberpunk-themed news articles:

| Event Source | Event Type |
|-------------|-----------|
| Living World | `world_event` |
| Faction AI | `faction_decision`, `faction_war` |
| Market | `world.economy_tick` |
| Player | `heist.job_complete`, `arena.match_end`, `casino.major_win`, `economy.transaction` |

50+ headline/body templates across 8 categories. Articles include:
- Headline, body text, category, severity (1-5)
- Related factions, districts, NPCs
- Byline (10 fictional journalists)
- Fingerprint dedup (120s window)

### News Ticker

Bottom-of-screen crawling ticker visible in every scene:
- Horizontally-scrolling headlines
- Category color tags
- Breaking news flash/glitch interrupts (severity 5)
- Keyboard toggle (N key), mute, close
- Auto-fetches from `/api/news/ticker` every 30s
- Socket.IO live updates (`news_article`, `breaking_news`)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/news/ticker` | GET | Formatted ticker items |
| `/api/news/headlines` | GET | Latest headlines (limit param) |
| `/api/news/article/<id>` | GET | Full article detail |
| `/api/news/breaking` | GET | High-severity articles only |
| `/api/news/search?q=` | GET | Full-text search |
| `/api/news/digest` | GET | Editorial summary |
| `/api/news/stats` | GET | Generator/ticker statistics |

### MCP Skills

- `latest_headlines(limit)` — Recent headlines
- `read_article(article_id)` — Full article text
- `search_world_news(query)` — Search articles
- `breaking_news()` — High-severity alerts
- `ticker_feed(limit)` — Ticker-formatted output
- `news_about_faction(faction)` — Faction-specific news
- `news_about_district(district)` — District-specific news
- `editorial_digest()` — AI editorial summary
- `news_stats()` — System statistics
- `news_by_category(category)` — Category filter

---

## 8. Onboarding Quest System

**Module:** `engine/world/onboarding.py` (~750 lines)
**Skills:** `engine/skills/builtin/onboarding_skills.py` (12 skills)
**Tests:** `tests/test_onboarding.py` (83 tests)

### Quest Chain

7 sequential quests that introduce new players to the world:

| # | Quest | Introduction |
|---|-------|-------------|
| 1 | First Contact | Phone system, encrypted messages |
| 2 | Street Smarts | Navigation, district exploration |
| 3 | Making Contacts | NPC interaction, The Rusty Anchor |
| 4 | First Score | Basic hacking, The Grid |
| 5 | Building Rep | Faction reputation, missions |
| 6 | Crew Assembly | First crew recruitment |
| 7 | Welcome to NeonCity | Full access unlocked |

Each quest has: objectives, dialogue, rewards (credits, XP, items), and
unlock conditions for the next quest.

---

## Threading Safety

**Critical pattern**: All manager classes use `threading.RLock()` (reentrant lock),
NOT `threading.Lock()`. This was a recurring bug that caused deadlocks in 4
separate modules during development.

**Why**: Manager methods often call other methods on the same instance. With a
regular `Lock`, if method A holds the lock and calls method B which also
acquires the lock, the thread deadlocks. `RLock` allows the same thread to
acquire the lock multiple times.

```python
# ✅ Correct
self._lock = threading.RLock()

# ❌ WRONG — will deadlock
self._lock = threading.Lock()
```

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
```
