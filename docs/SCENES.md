# Scenes

> CosySim Documentation — v1.52.0 [2026-03-26]
>
> Complete catalog of all 33 launch targets across three pillars.

CosySim organizes its launch targets into three pillars: **GAME** (15 interactive scenes), **SERVICE** (11 infrastructure and monitoring targets), and **CREATION** (6 content authoring tools). Every target is defined in `engine/control_plane_registry.py` and resolved to a port by `engine/port_registry.py`. The launcher, TUI, and Hub all derive their catalogues from these two files.

---

## GAME Pillar — 15 Targets

Interactive game scenes. Each is a Flask/Socket.IO app on its own port, inheriting from `BaseScene`.

| Target | Label | Port | Type | Auto-Start | Description |
|--------|-------|------|------|------------|-------------|
| `phone` | SIGNAL | 5555 | flask | Yes | Cyberdeck messaging, calls, social media, arcade mini-games |
| `penthouse` | THE PENTHOUSE | 5556 | flask | Yes | Adult roleplay with 3D animation, emotion system, agent loop |
| `lounge` | THE VELVET PIT | 5557 | flask | No | Speakeasy social scene with drinking games and ambient events |
| `tavern` | THE RUSTY ANCHOR | 5558 | flask | No | Fantasy RPG tavern with barter economy and dice games |
| `casino` | CLUB NOIR | 5559 | flask | No | Neon-noir casino with blackjack, poker, slots, and VIP area |
| `gallery` | THE OBSCURA | 5560 | flask | No | AI art gallery with ComfyUI generation, critiques, and auctions |
| `arena` | THE COLOSSEUM | 5561 | flask | No | Tactical card battle arena with deck building and tournaments |
| `realm` | THE SHATTERED THRONE | 5562 | flask | No | LitRPG with dual-agent system, d20 combat, murder mysteries |
| `neoncity` | NEON CITY | 5563 | flask | Yes | Cyberpunk battle-royale board game on a shrinking grid |
| `coders` | THE LAB | 5564 | flask | No | AI coding room with 5-phase pipeline and sandboxed execution |
| `heist` | THE SCORE | 5565 | flask | No | Cooperative heist planning with crew roles and phase-gated ops |
| `games` | THE ARCADE | 5567 | flask | No | Multi-game arcade hub with trivia, chess puzzles, leaderboards |
| `grid` | THE GRID | 5569 | flask | No | Underground marketplace with dynamic economy and factions |
| `lab_break` | LAB BREAK | 5571 | flask | No | Psychological survival horror escape room with vitals and crafting |
| `oracle` | THE ORACLE | 5572 | flask | No | Narrative oracle scene (auto-registered by Creation Kit) |

---

## SERVICE Pillar — 11 Targets

Infrastructure services, monitoring dashboards, APIs, and proxies.

| Target | Label | Port | Type | Auto-Start | Description |
|--------|-------|------|------|------------|-------------|
| `nexus_kms` | Nexus KMS | 8700 | external | Yes | Knowledge management system (priority 0, starts first) |
| `hub` | CosySim Hub | 8500 | flask | Yes | Central navigation hub and scene launcher |
| `nexus_panel` | Nexus Control Panel | 5570 | flask | Yes | Full Nexus CRUD, search, research sessions, analytics |
| `dashboard` | System Dashboard | 8501 | streamlit | No | Streamlit system metrics dashboard |
| `admin` | Admin Panel | 8502 | streamlit | No | Streamlit administration panel |
| `tts` | TTS Server | 8600 | fastapi | No | Text-to-speech server (Qwen3/Piper/Orpheus) |
| `bridge` | MCP Bridge | 8601 | fastapi | Yes | WebSocket bridge for MCP skill invocation |
| `nlm_proxy` | NLM Live Proxy | 8800 | flask | Yes | NotebookLM live proxy for research distillation |
| `system_control` | System Control Panel | 5575 | flask | Yes | Service management, port registry, config viewer |
| `command_center` | Command Center | 5566 | flask | No | Real-time monitoring, command execution, scheduler |
| `intel_hub` | THE BRIEFING ROOM | 5580 | flask | Yes | Intelligence dashboard with operator console and health |

---

## CREATION Pillar — 6 Targets

Content authoring and asset generation tools.

| Target | Label | Port | Type | Auto-Start | Description |
|--------|-------|------|------|------------|-------------|
| `canvas` | Nexus Canvas | 5590 | node | Yes | Interactive notebook canvas for knowledge authoring |
| `canvas_api` | Canvas API | 5595 | fastapi | Yes | Backend API for Nexus Canvas |
| `assets` | Asset Generator | 8503 | streamlit | No | Streamlit-based asset generation interface |
| `creator` | Scene Creator | 8504 | streamlit | No | Wizard for scaffolding new scenes |
| `asset_studio` | ASSET STUDIO | 5568 | flask | No | ComfyUI-powered generation studio for portraits and backgrounds |
| `creation_kit` | CREATION KIT | 5592 | flask | No | Visual scene editor for building and previewing scenes |

---

## Scene Architecture

### BaseScene

Every game scene inherits from `BaseScene` (`engine/scenes/base_scene.py`) and runs as an independent Flask web server on a dedicated port. The base class provides:

- **Lifecycle hooks** -- `start()`, `stop()`, `get_plugin_info()`
- **Character management** -- `active_characters` dict, `on_character_added/removed`
- **Shared route registration** -- `register_health_route()`, `register_hud_route()`, `register_announcer_route()`, `register_bench_route()`
- **Shared assets** -- `register_shared_assets(app)` mounts `/shared/*` CSS/JS/templates
- **Save/load** -- `save_state()`, `load_state()` for persistence across restarts

Scenes may additionally mix in:

| Mixin | Purpose | Usage |
|-------|---------|-------|
| `MCPSceneMixin` | MCP governance: skills, rules, timers, event bus | 14 scenes |
| `NexusSceneMixin` | Nexus KMS integration: knowledge, state persistence | 16 scenes |
| `PenthouseCombatMixin` | Combat system decomposition | Penthouse only |
| `PenthouseSocialMixin` | Social interaction decomposition | Penthouse only |

### SCENE_METADATA

Every scene class declares a `SCENE_METADATA` dict used by the Hub and control plane for discovery:

```python
SCENE_METADATA = {
    "name": "my_scene",
    "display_name": "MY SCENE",
    "type": "game",          # game | service | creation
    "port": 5570,
    "description": "...",
    "features": ["chat", "economy"],
}
```

### Directory Structure

```
content/scenes/my_scene/
├── __init__.py            # exports MyScene
├── my_scene_scene.py      # BaseScene subclass
├── my_scene_skills.py     # @skill decorated functions
├── templates/
│   └── my_scene.html      # Jinja2 UI template
└── static/
    ├── css/
    │   └── my_scene.css
    └── js/
        └── my_scene.js
```

### Required start() Pattern

Every scene's `start()` method must register shared routes after Flask setup:

```python
def start(self):
    self.app = Flask(__name__, template_folder="templates")
    self.socketio = SocketIO(self.app, cors_allowed_origins="*")

    from content.shared import register_shared_assets
    register_shared_assets(self.app)        # /shared/* routes
    self.register_health_route(self.app)    # /api/health
    self.register_hud_route(self.app)       # /api/hud/state
    self.register_announcer_route(self.app) # /api/announcer/feed
    self.register_bench_route(self.app)     # /api/bench

    # ... scene-specific routes, Socket.IO handlers, character loading ...
    self.socketio.run(self.app, host=self.host, port=self.port)
```

### Shared Visual System

All scenes share a unified cyberpunk "dark glass" design language implemented in `content/shared/static/`. Each scene declares its own accent colour:

| Scene | Accent | Scene | Accent |
|-------|--------|-------|--------|
| penthouse | `#ec4899` | arena | `#f59e0b` |
| phone | `#10b981` | realm | `#059669` |
| lounge | `#f59e0b` | neoncity | `#06b6d4` |
| tavern | `#92400e` | coders | `#4ade80` |
| casino | `#f97316` | heist | `#e11d48` |
| gallery | `#7c3aed` | games | `#8b5cf6` |
| hub | `#3b82f6` | intel_hub | `#06b6d4` |
| grid | `#00ff88` | lab_break | `#22d3ee` |

### Shared Components

| Component | Files | Purpose |
|-----------|-------|---------|
| **Navbar v2** | `navbar_v2.{html,css,js}` | Top nav: scene switcher, bench, voice, Aria |
| **Admin Overlay** | `admin_overlay.{html,css,js}` | 8-tab hacker panel (State, Characters, Engine, Economy, Events, Content, Director, Debug) |
| **Aria Widget** | `aria_widget.{html,css,js}` | Floating assistant -- expands to chat |
| **Voice Settings** | `voice_settings.html` | TTS/STT config modal |
| **BenchHUD** | `cosysim-bench.js` | Live inference metrics overlay |
| **VoiceManager** | `cosysim-voice.js` | TTS (Piper/Orpheus/Qwen3) + STT |
| **Particle System** | `cosysim-particles.js` | Per-scene canvas particle effects |
| **Scene FX** | `cosysim-scene-fx.css` | Per-scene ambient CSS animations |
| **Transitions** | `cosysim-transitions.js` | Cross-scene page fade transitions |
| **Portrait Overlay** | `portrait.{html,css,js}` | Character portrait + mood badge |

---

## Scene-Specific Deep Dives

### Phone -- SIGNAL (port 5555)

**Class:** `PhoneSceneV2` -- An iOS-style phone interface with messaging, calls, and character social media. Characters send autonomous texts and maintain relationships.

**Apps:** Messages (thread-based DMs and group chats), Hacker (character state inspection, message interception), Games (arcade mini-games: trivia, would-you-rather, story chain, truth-or-dare), Gallery (photo/video browser), Voice Messages, Voice Studio (TTS voice collection), Research (NotebookLM knowledge-base Q&A).

**Skills:** `phone_send_message`, `phone_check_messages`, `phone_start_game`, `phone_game_action`, `phone_generate_image`, `phone_toggle_autotxt`

**State:** `phone_v2.db` -- message threads, game state, contact list. Auto-texting system with configurable intervals per character. Message threading with read/unread tracking.

---

### Penthouse -- THE PENTHOUSE (port 5556)

**Class:** `PenthouseScene` -- An adult roleplay scene featuring multi-character support with a full emotion system, outfit management, room-based location mechanics, and an AI agent loop. Includes a complete AAA 3D animation system built on Three.js procedural bone animation with 55 animation states.

**Director Panel (8 Tabs):** Scene (lighting, time-of-day), Cast (character picker, personality assignment), Dialog (chat, agent loop Start/Stop/Tick), Actions (dice rolls, activity suggestions), Scenario (scenario selection with mood shifts), World (world tick, location graph, furniture), Settings (camera mode, model assignment, YAML overrides), Debug (ARGUS LiveDebugger, Socket.IO monitor).

**Mechanics:** Emotion system (0-100 per axis: arousal, pleasure, happiness, horniness, and more). Room graph with connected locations (bed, couch, fireplace, bar, bathroom, vanity, balcony, doorway). Outfit system with 10 outfit states. Time-of-day cycle. Combat via PenthouseCombatMixin. Agent loop with configurable interval. First-person camera mode (WASD + pointer lock).

**Skills:** `penthouse_status`, `penthouse_suggestion`, `penthouse_set_mood`, `penthouse_change_outfit`, `penthouse_game_action`, `penthouse_roll_dice`, `penthouse_move_room`, `penthouse_inventory`, `penthouse_combat_attack`, `penthouse_combat_defend`, `penthouse_combat_status`

**Animation:** 55-state machine (idle, movement, standing, seated, lying, ground, furniture, action, intimate, special). 6 MCP animation skills. Animation Studio UI with 5 tabs (Poses, Expressions, Sequences, Library, Models). YAML configuration in `config/penthouse/`.

---

### Lounge -- THE VELVET PIT (port 5557)

**Class:** `LoungeScene` -- A speakeasy social scene with character conversations, drinking games, and ambient event generation.

**Mechanics:** Patron list with mood tracking. Economy integration (drink prices, credits). Ambient event generation (arguments, music changes, arrivals).

**Skills:** `lounge_status`, `lounge_order_drink`, `lounge_start_game`, `lounge_gossip`

---

### Tavern -- THE RUSTY ANCHOR (port 5558)

**Class:** `TavernScene` -- A fantasy RPG tavern with character interactions, dice games, and a barter economy.

**Mechanics:** Menu system with item prices. Barter mechanic with haggling. Dice game with wager system.

**Skills:** `tavern_status`, `tavern_order`, `tavern_barter`, `tavern_dice_game`

---

### Casino -- CLUB NOIR (port 5559)

**Class:** `CasinoScene` -- A neon-noir casino with blackjack, poker, slots, and a high-roller VIP area. Economy is wired through the chip/credit system.

**Mechanics:** Chip balance per player. Card deck state for blackjack/poker. Slot machine RNG with jackpot accumulation. Economy degraded-fallback tracking.

**Skills:** `casino_status`, `casino_blackjack`, `casino_slots`, `casino_poker_bet`, `casino_exchange`, `casino_vip_access`

---

### Gallery -- THE OBSCURA (port 5560)

**Class:** `GalleryScene` -- An interactive art gallery where AI generates artworks via ComfyUI, characters critique them, and exhibitions rotate on schedule.

**Mechanics:** Exhibition collections with artwork metadata. Auction system with bidding history. Art generation history linked to ComfyUI.

**Skills:** `gallery_status`, `gallery_create_art`, `gallery_critique`, `gallery_curate`, `gallery_auction`, `gallery_visit`

---

### Arena -- THE COLOSSEUM (port 5561)

**Class:** `ArenaScene` -- A tactical card battle arena with deck building, turn-based combat, and tournament brackets.

**Mechanics:** Deck system with card types, costs, and effects. Match state (turns, HP, hand, graveyard). Tournament brackets with elimination tracking.

**Skills:** `arena_status`, `arena_challenge`, `arena_play_card`, `arena_draw_card`, `arena_view_hand`, `arena_deck_build`, `arena_tournament`

See [Arena Guide](ARENA_GUIDE.md) for the full card system reference.

---

### Realm -- THE SHATTERED THRONE (port 5562)

**Class:** `RealmScene` -- A full-featured LitRPG with a dual-agent system (Director narrates, Assistant provides fourth-wall commentary), d20 combat, inventory, and murder mystery sub-games.

**Mechanics:**
- **Dual-agent** -- Director (game master) + Assistant (fourth-wall companion)
- **Combat** -- d20 + stat_mod vs DC. Nat 20 = critical. Death at HP <= 0 triggers item loss and respawn
- **Exploration** -- Room discovery: 30% encounter, 40% loot, 30% empty
- **Murder mystery** -- Investigation phases, 3+ clues to unlock accusation
- **Director patience** -- Decreases each turn; at 0 triggers mutiny (forced narrative)
- **Skill checks** -- persuasion, lockpicking, arcana, athletics, stealth, intimidation, deception, investigation, survival

**Skills:** `realm_status`, `realm_inventory`, `realm_equip`, `realm_use_item`, `realm_adjust_hp`, `realm_start_combat`, `realm_combat_attack`, `realm_combat_defend`, `realm_combat_flee`, `realm_combat_use_item`, `realm_director_status`, `realm_fourth_wall_steal`, `realm_desperation_dice`, `realm_murder_status`

---

### Neon City -- NEON CITY (port 5563)

**Class:** `NeonCityScene` -- A cyberpunk battle-royale board game on a shrinking 12x12 grid with hacking, factions, and dynamic street events.

**Mechanics:** Glitch Storm shrinking safe zone (15 damage/turn outside). Turn-based combat with weapons, accuracy, criticals (10%, 2x damage). Progressive firewall breaching to defeat AI at grid center. Up to 3 AI opponents with behavior profiles. 30% per-turn random events (blackouts, drone strikes, supply drops).

**Skills:** `neoncity_status`, `neoncity_player_info`, `neoncity_move`, `neoncity_attack`, `neoncity_hack`, `neoncity_storm_status`, `neoncity_trigger_event`, `neoncity_end_turn`

---

### Coders Room -- THE LAB (port 5564)

**Class:** `CodersRoomScene` -- An AI coding room where agents collaboratively write, review, and test Python code in an idle-simulation loop.

**Mechanics:** 5-phase pipeline (FEATURE, DESIGN, CODING, REVIEW, TESTING). Role-based agents (Reviewer, Writer, QA). Real code generation via LLM. Sandboxed execution with 10-second subprocess and pytest. Consecutive failures trigger rollback to DESIGN.

**Skills:** `coders_status`, `coders_agent_info`, `coders_add_feature`, `coders_feature_list`, `coders_run_code`, `coders_tick`

---

### Heist -- THE SCORE (port 5565)

**Class:** `HeistScene` -- Cooperative heist planning and execution with specialized crew roles and phase-gated operations.

**Mechanics:** Phase-gated flow (Planning, Recon, Execution, Getaway). Crew roles (Hacker, Muscle, Thief, Driver, Inside Man). Heat system -- failed checks increase heat; too high triggers police. Multiple targets (bank, casino vault, corp server, museum). Crew synergy -- role combinations unlock special actions.

**Skills:** `heist_status`, `heist_plan`, `heist_assign_role`, `heist_execute`, `heist_abort`, `heist_intel`, `heist_getaway`

---

### Games -- THE ARCADE (port 5567)

**Class:** `GamesScene` -- A multi-game arcade hub with trivia, chess puzzles, word games, and leaderboards.

**Mechanics:** Multiple game types (trivia, chess puzzles, word association, memory). Per-game leaderboard rankings with score tracking. AI opponents with configurable difficulty. Player-vs-character challenge mode.

**Skills:** `games_status`, `games_start`, `games_action`, `games_leaderboard`, `games_challenge`, `games_hint`

---

### Grid -- THE GRID (port 5569)

**Class:** `GridScene` -- An underground marketplace and faction hub with dynamic economy, price fluctuations driven by WorldSim events, and faction allegiance mechanics.

**Zones:** THE MARKET (buy/sell items, prices fluctuate with economy_tick events), THE STATION (Neon City travel hub, SVG map of scene locations), THE DEN (faction headquarters, allegiance, and faction quests), THE BROKER (information trading, Nexus-powered intel feed).

**Skills:** `grid_status`, `grid_buy_item`, `grid_sell_item`, `grid_get_market_prices`, `grid_faction_pledge`, `grid_broker_intel`

See [The Grid](THE_GRID.md) for the full marketplace and faction reference. See [Economy Guide](ECONOMY_GUIDE.md) for the credit/chip system.

---

### Lab Break -- LAB BREAK (port 5571)

**Class:** `LabBreakScene` -- A psychological survival horror escape room where characters have vitals (hunger, energy, stress, sanity), emotional bonds, and must be persuaded to cooperate for escape.

**Survival Stats:** 6 stats with continuous decay timers -- hunger (-1/min), energy (-0.5/min), hydration (-0.8/min), health (no natural decay), stress (+0.3/min), sanity (-0.2/min). Death occurs when health reaches 0; cause is tracked for post-mortem display.

**Crafting:** 4 recipes (Lockpick, EMP Device, Medkit+, Rope Ladder) from 30 items across 5 categories (food, medical, tools, key items, materials).

**Escape Routes:** Main Door (keycard + EMP, medium), Ventilation (rope ladder + energy >= 50, hard), Sewers (flashlight + sanity >= 40, hard), Negotiate (persuasion + trust >= 70, very hard).

**Skills:** `lab_status`, `lab_inspect`, `lab_move`, `lab_interact`, `lab_persuade`, `lab_rest`, `lab_feed`, `lab_escape_attempt`

---

### Oracle -- THE ORACLE (port 5572)

**Class:** `OracleScene` -- A narrative oracle scene auto-registered by the Creation Kit. Provides oracle-style interactions and narrative guidance.

---

## Service Target Details

### Hub -- CosySim Hub (port 8500)

**Class:** `HubScene` -- The central navigation hub and scene launcher. Renders discovery cards for all registered scenes using the port registry.

**Features:** Auto-generated scene cards from the port registry. Green/red status dots per scene based on health checks. Quick actions (launch scene, view health, open admin). Scene creator wizard for scaffolding new scenes.

---

### Nexus Panel -- Nexus Control Panel (port 5570)

**Class:** `NexusPanelScene` -- The richest route surface in CosySim (114 routes). Full Nexus knowledge management with CRUD, search, research sessions, rule management, and analytics dashboards.

**Features:** Knowledge CRUD. FTS5-powered full-text search. Multi-turn NotebookLM research sessions. Rule browser for governance rules. Entry counts, growth trends, Q&A cache stats. Bulk import/export. Query router stats (cache hit rates, tier usage).

---

### Intel Hub -- THE BRIEFING ROOM (port 5580)

**Class:** `IntelHubScene` -- Intelligence dashboard with operator console, system health monitoring, news feeds, benchmark tracking, and operator inbox integration.

**Features:** Operator console (submit notes, view queue, process directives). Real-time service health (Nexus, LMStudio, TTS, NLM). Curated AI/tech/world news feed. Benchmark dashboard with SVG sparkline charts. World events live ticker from WorldSim. Git summary and activity log.

---

### Command Center (port 5566)

**Class:** `CommandCenterScene` -- Real-time system monitoring dashboard with command execution, scheduler visibility, and system metrics (CPU, memory, GPU, network). Log streaming via Socket.IO. Configurable alert thresholds.

---

### System Control -- System Control Panel (port 5575)

**Class:** `SystemControlScene` -- System administration panel exposing service start/stop/restart, port registry view, configuration viewer, log tailing, and aggregate health status.

---

## Creation Target Details

### Asset Studio -- ASSET STUDIO (port 5568)

**Class:** `AssetStudioScene` -- ComfyUI-powered asset generation studio for character portraits, scene backgrounds, and UI elements. Workflow library (portrait, landscape, video via Wan 2.2 GGUF, upscale). Asset database (`data/asset_registry.db`). Scene injection to push generated assets directly into templates. Tab UI: Generate, Library, Images, Portraits, Workflows.

See [Asset Studio](ASSET_STUDIO.md) for the full reference.

---

### Creation Kit -- CREATION KIT (port 5592)

**Class:** `CreationKitScene` -- Visual scene editor for building and previewing new scenes. Can auto-register new scenes into the control plane registry.

---

## Adding a New Scene

1. Create the directory structure under `content/scenes/my_scene/`
2. Implement a `BaseScene` subclass with `SCENE_METADATA`
3. Create a skills file with `@skill` decorated functions
4. Register in these files:

| File | What to add |
|------|-------------|
| `engine/port_registry.py` | Port assignment and service group membership |
| `engine/control_plane_registry.py` | Entry in `SCENE_DEFS` with class path, label, pillar |
| `config/default.yaml` | `scenes.my_scene` config block |

5. Create a Jinja2 template extending `neon_base.html`:

```html
{% set scene_key = "my_scene" %}
{% set accent = "#00ff88" %}
{% extends "neon_base.html" %}
```

**Never** explicitly load `navbar_v2.css` or `navbar_v2.js` -- `navbar_v2.html` is self-contained. **Never** load `aria_widget.js` directly -- use the include.

---

## Socket.IO Event Reference

| Event | Direction | Scenes | Purpose |
|-------|-----------|--------|---------|
| `message` | Server to Client | All chat scenes | Character message |
| `state_update` | Server to Client | Most scenes | Game state change |
| `hud_update` | Server to Client | All via HUD | Player state / world update |
| `world_event` | Server to Client | All via HUD | World event notification |
| `price_update` | Server to Client | Grid, Casino | Economy price change |
| `connect` | Client to Server | All | Socket.IO connection |
| `chat` | Client to Server | Chat scenes | Player chat message |
| `action` | Client to Server | Game scenes | Player action |
| `typing` | Server to Client | Phone, Penthouse | Character typing indicator |
| `new_message` | Server to Client | Phone | Incoming text message |
| `game_update` | Server to Client | Games, Arena | Game state change |
| `combat_update` | Server to Client | Arena, Realm | Combat state change |
| `economy_banner` | Server to Client | Grid, Casino | Major economy event |

---

## Health Checking

Run after any scene change:

```bash
python scripts/scene_health_check.py --port <PORT> --fix
```

This validates: `/api/health` returns 200, all shared assets load (`/shared/css/`, `/shared/js/`), navbar v2 renders, Socket.IO connects, and scene-specific routes respond.

Full scene health sweep:

```bash
python scripts/scene_health_check.py --all
```

---

## See Also

- [Architecture](ARCHITECTURE.md) -- Engine subsystem details
- [Arena Guide](ARENA_GUIDE.md) -- Card battle system reference
- [The Grid](THE_GRID.md) -- Marketplace and faction reference
- [Economy Guide](ECONOMY_GUIDE.md) -- Credit/chip economy system
- [Neon HUD](NEON_HUD.md) -- HUD overlay and design tokens
- [Asset Studio](ASSET_STUDIO.md) -- ComfyUI asset generation
- [MCP Framework](MCP_FRAMEWORK.md) -- Skill and interceptor patterns
- [Configuration](CONFIGURATION.md) -- `config/default.yaml` scene settings
- [Contributing](CONTRIBUTING.md) -- Development workflow and conventions
- [Operations](OPERATIONS.md) -- Service management and monitoring

---

## Change Log

- **v1.50 [2026-03-22]** -- Complete rewrite for three-pillar architecture. 32 targets (15 game, 11 service, 6 creation). Accurate port map from control_plane_registry.py. Added Oracle scene. Reorganized into pillar tables with deep dives.
- **v1.06b [2026-03-18]** -- Original version. 20 Flask scenes, AAA overlay system, 55-state animation system, survival mechanics.
