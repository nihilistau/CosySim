# CosySim Scenes Guide

> v1.06b — 20 Flask scenes, ~613 HTTP routes, ~51 Socket.IO event types, AAA overlay UI, 55-state animation system, survival mechanics, 8-tab director panels

Complete reference for every scene in the CosySim simulation framework.

---

## Scene Architecture

Every scene inherits from `BaseScene` (`engine/scenes/base_scene.py`) and runs as
an independent Flask web server on a dedicated port. The base class provides:

- **Lifecycle hooks** — `start()`, `stop()`, `get_plugin_info()`
- **Character management** — `active_characters` dict, `on_character_added/removed`
- **Shared route registration** — `register_health_route()`, `register_hud_route()`,
  `register_announcer_route()`, `register_bench_route()`
- **Shared assets** — `register_shared_assets(app)` mounts `/shared/*` CSS/JS/templates
- **Save/load** — `save_state()`, `load_state()` for persistence across restarts

Scenes may additionally mix in:

| Mixin | Purpose | Scenes using it |
|-------|---------|-----------------|
| `MCPSceneMixin` | MCP governance: skills, rules, timers, event bus | 14 |
| `NexusSceneMixin` | Nexus KMS integration: knowledge, state persistence | 16 |
| Custom mixins | Scene-specific decomposition (e.g., PenthouseCombatMixin) | 1 (penthouse) |

### SCENE_METADATA

Every scene class declares a `SCENE_METADATA` dict used by the Hub and control
plane for discovery:

```python
SCENE_METADATA = {
    "name": "my_scene",
    "display_name": "MY SCENE",
    "type": "game",          # game | utility | service
    "port": 5570,
    "description": "...",
    "features": ["chat", "economy"],
}
```

### Port Map

| Port | Scene | Display Name | Type |
|------|-------|-------------|------|
| 5555 | phone | SIGNAL | Game |
| 5556 | penthouse | THE PENTHOUSE | Game |
| 5557 | lounge | THE VELVET PIT | Game |
| 5558 | tavern | THE RUSTY ANCHOR | Game |
| 5559 | casino | CLUB NOIR | Game |
| 5560 | gallery | THE OBSCURA | Game |
| 5561 | arena | THE COLOSSEUM | Game |
| 5562 | realm | THE SHATTERED THRONE | Game |
| 5563 | neoncity | NEON CITY | Service |
| 5564 | coders | THE LAB | Game |
| 5565 | heist | THE SCORE | Game |
| 5566 | command_center | Command Center | Service |
| 5567 | games | THE ARCADE | Game |
| 5568 | asset_studio | ASSET STUDIO | Utility |
| 5569 | grid | THE GRID | Service |
| 5570 | nexus_panel | Nexus Control Panel | Utility |
| 5571 | lab_break | LAB BREAK | Game |
| 5575 | system_control | System Control Panel | Utility |
| 5580 | intel_hub | THE BRIEFING ROOM | Utility |
| 8500 | hub | THE TERMINAL | Utility |

Service ports: Nexus (8700), TTS (8600), NLM Proxy (8800), Canvas (5590/5595).

---

## Penthouse AAA Overlay System

The Penthouse scene uses a full AAA-grade overlay architecture with stacked
z-index layers and glass-morphism styling.

### Layer Stack

| Layer | z-index | Element | Position |
|-------|---------|---------|----------|
| 3D Canvas | z-0 | Background canvas | Full viewport |
| Character Panel | z-100 | Character info | Left side |
| Chat Dock | z-200 | Chat interface | Bottom |
| Director Panel | z-500 | 8-tab control panel | Right side |
| Toggle Button | z-600 | Director toggle | Top-right |

### 8-Tab Director Panel

| Tab | Purpose |
|-----|---------|
| Scene | Scene-wide settings, lighting, time of day |
| Cast | Character roster, active/inactive management |
| Direct | AI direction: tone, pacing, narrative constraints |
| Interact | Interaction modes, relationship controls |
| Story | Story arc tracking, plot points, branching |
| Props | Prop inventory, placement, visibility |
| Events | Scheduled events, triggers, timers |
| Settings | Audio, visual, performance configuration |

### Styling

All panels use the `ph-` CSS prefix and glass-morphism design:

```css
.ph-panel {
    backdrop-filter: blur(20px);
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.08);
}
```

### Template Architecture

The Penthouse template extends `neon_base.html` and configures scene-specific
variables via Jinja2 `{% set %}` blocks:

```html
{% set scene_key = "penthouse" %}
{% set accent = "#ec4899" %}
{% set accent_rgb = "236, 72, 153" %}
{% extends "neon_base.html" %}
```

### Required Context

`render_template()` must pass these context variables:

| Variable | Type | Description |
|----------|------|-------------|
| `scenarios` | `list[dict]` | Available scenario definitions |
| `props` | `list[dict]` | Prop catalog with placement data |
| `lighting_presets` | `list[dict]` | Named lighting configurations |

### JavaScript

The `PenthouseScene` class manages UI state, and global director functions
use a `_directorState` cache object to avoid redundant DOM queries:

```javascript
const _directorState = { activeTab: 'scene', panelOpen: false, cache: {} };

class PenthouseScene {
    constructor() { /* initializes overlay layers */ }
    openDirector(tab) { /* switches to tab, updates _directorState */ }
    closeDirector() { /* hides panel, clears cache */ }
}
```

### Animation System (v1.06b)

The Penthouse scene includes a complete AAA+++ 3D animation system built on
Three.js procedural bone animation.

#### Script Load Order (11 scripts, ORDER MATTERS)

```
Three.js r128 → OrbitControls → penthouse_3d.js → character_models.js →
penthouse_anim.js → character_bridge.js → penthouse_config.js →
penthouse_customizer.js → penthouse_model_import.js →
penthouse_anim_studio.js → penthouse.js
```

#### Animation State Machine — 55 States

| Category | States | Priority |
|----------|--------|----------|
| Idle | idle | 0 |
| Movement | walk, run, crawl | 1 |
| Standing | lean, arms_crossed, hands_behind | 2 |
| Seated | sit, sit_cross, sit_lean, sit_floor | 2 |
| Lying | lie, lie_side, lie_front, lounge | 2 |
| Ground | kneel, kneel_sit, all_fours, sprawl, crouching | 3 |
| Furniture | interact, drink, gaze, warm, primp, bathe | 3 |
| Action | dance_slow, dance_sway, stretch, undress, dressing, massage, beckon, hair_flip, blow_kiss, shrug, phone, smoke, flirt, celebrating, eating, dancing, drinking | 4 |
| Intimate | embrace, kiss_standing, lap_sit, straddle, ride, going_down, missionary, doggy, spooning, dominant_pose, submissive, seductive_pose, intimate_touch | 5 |
| Special | pose | 6 |

#### Y-Position Math (CRITICAL)

Character model origin is at feet level. For furniture interactions:

```
group.y = furniture_surface_height - body_reference_point
```

| Surface | Height | Reference | group.y |
|---------|--------|-----------|---------|
| Couch seat | 0.50 | hipY (0.82) | **-0.32** |
| Bed mattress | 0.70 | torsoY (0.80) | **-0.10** |
| Floor | 0.00 | kneeH (0.39) | **-0.44** |
| Bathtub | 0.35 | hipY (0.82) | **-0.47** |

All Y-position values must be **negative** (lowering from standing to surface).

#### MCP Animation Skills

6 skills in `penthouse_skills.py`:
- `set_animation(character_id, state)` — Set animation state
- `set_expression(character_id, expression)` — Set facial expression
- `paired_animation(char1, char2, animation)` — Paired interaction
- `change_outfit(character_id, outfit)` — Change clothing
- `interaction_chain(character_id, chain)` — Multi-step sequence
- `list_animations()` — List all available animations

#### Animation Studio UI (5 tabs)

| Tab | Purpose |
|-----|---------|
| Poses | Per-joint rotation editing with real-time 3D preview |
| Expressions | Morph value sliders for 15 expression states |
| Sequences | Chain animations with timing and transitions |
| Library | Browse/save/load pose presets (111 built-in) |
| Models | Search/filter 21 cataloged GLB models |

#### YAML Configuration

- `config/penthouse/animations.yaml` — State categories, blend overrides, paired configs
- `config/penthouse/interactions.yaml` — Location→action→state mappings, chains
- `config/penthouse/models/catalog.yaml` — Model registry with bone mapping

#### Reusable Framework (`engine/animation/`)

```python
from engine.animation import AnimationConfig, PoseLibrary, ModelCatalog

config = AnimationConfig("config/penthouse")
poses = PoseLibrary("data/penthouse/animations/poses.json")
catalog = ModelCatalog("config/penthouse/models/catalog.yaml")
```

---

## Required start() Pattern

Every scene's `start()` method MUST register these shared routes after Flask
setup to ensure health checks, HUD state, announcer feeds, and shared CSS/JS
work correctly:

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

---

## Creating a New Scene

### 1. Directory Structure

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

### 2. Scene Class

```python
from engine.scenes.base_scene import BaseScene

class MyScene(BaseScene):
    SCENE_METADATA = {
        "name": "my_scene",
        "display_name": "MY SCENE",
        "type": "game",
        "port": 5570,
        "description": "What this scene does.",
        "features": ["chat", "economy"],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = 5570):
        super().__init__(scene_name="my_scene", host=host, port=port)
```

### 3. Skills File

Use the `@skill` decorator pattern — skills are auto-registered when the module
is imported:

```python
from engine.skills.registry import skill
from engine.scenes.base_scene import BaseScene

@skill(
    pack="my_scene",
    description="Get the current scene state",
    category="game",
)
def my_scene_status() -> str:
    scene = BaseScene.get_active_scene("my_scene")
    if not scene:
        return "Scene not running"
    return str(scene.get_state_dict())
```

### 4. Registration

Add the scene to these files:

| File | What to add |
|------|-------------|
| `engine/port_registry.py` | `_PORTS["my_scene"] = 5570`, `SERVICE_GROUPS["scenes"]`, `SCENE_HEALTH_TARGETS`, `HUB_CATALOGUE_TARGETS` |
| `engine/control_plane_registry.py` | Entry in `SCENE_DEFS` with class path, label, type |
| `config/default.yaml` | `scenes.my_scene` config block |
| `launcher.py` | Entry in `SCENES` dict |

### 5. Template

```html
{% include 'navbar_v2.html' %}
{% include 'aria_widget.html' %}
<body data-scene="my_scene">
  <!-- Scene content -->
  <script src="/shared/js/socket.io.min.js"></script>
  <script src="/shared/js/cosysim-particles.js"></script>
</body>
```

**NEVER** explicitly load `navbar_v2.css` or `navbar_v2.js` — `navbar_v2.html`
is self-contained. **NEVER** load `aria_widget.js` — use the include.

---

## Visual System

All scenes share a unified cyberpunk "dark glass" design language implemented
in `content/shared/static/`.

### Design Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--glass-bg` | `rgba(0,0,0,0.65)` | Panel backgrounds |
| `--glass-border` | `rgba(255,255,255,0.08)` | Panel borders |
| `--glass-blur` | `blur(18px)` | `backdrop-filter` |
| `--accent` | Per-scene hex | Primary highlight colour |
| `--accent-glow` | `0 0 24px var(--accent)` | Neon glow shadow |

Each scene declares its own accent colour:

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
| **Aria Widget** | `aria_widget.{html,css,js}` | Floating assistant — expands to chat |
| **Voice Settings** | `voice_settings.html` | TTS/STT config modal |
| **BenchHUD** | `cosysim-bench.js` | Live inference metrics overlay |
| **VoiceManager** | `cosysim-voice.js` | TTS (Piper/Orpheus/Qwen3) + STT |
| **Particle System** | `cosysim-particles.js` | Per-scene canvas particle effects |
| **Scene FX** | `cosysim-scene-fx.css` | Per-scene ambient CSS animations |
| **Transitions** | `cosysim-transitions.js` | Cross-scene page fade transitions |
| **Portrait Overlay** | `portrait.{html,css,js}` | Character portrait + mood badge |

---

## Scene Reference — Game Scenes

---

### Phone — SIGNAL (port 5555)

**Class:** `PhoneSceneV2` · **Routes:** 66 · **Skills:** 6

An iOS-style phone interface with messaging, calls, and character social media.
Characters send autonomous texts and maintain relationships.

#### Apps

- **Messages** — Thread-based DMs and group chats
- **Hacker** — Character state inspection, profile reading, message interception
- **Games** — Arcade mini-games (trivia, would-you-rather, story chain, truth-or-dare)
- **Gallery** — Photo and video browser
- **Voice Messages** — Audio clip playback
- **Voice Studio** — TTS voice collection
- **Research (NotebookLM)** — Knowledge-base Q&A

#### Skills

| Skill | Description |
|-------|-------------|
| `phone_send_message` | Text a character |
| `phone_check_messages` | Get threads and unread counts |
| `phone_start_game` | Start arcade game |
| `phone_game_action` | Submit a game move |
| `phone_generate_image` | Generate AI images |
| `phone_toggle_autotxt` | Mute/unmute autonomous texting |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/messages/send` | Send message to character |
| GET | `/api/messages/threads` | List message threads |
| GET | `/api/messages/thread/<id>` | Get thread history |
| POST | `/api/games/start` | Start arcade game |
| POST | `/api/tts/speak` | Text-to-speech for messages |
| GET | `/api/nlm/ask` | NotebookLM Q&A |

#### State

- `phone_v2.db` — message threads, game state, contact list
- Auto-texting system with configurable intervals per character
- Message threading with read/unread tracking

> **Phone Panel Injection Fix:** `content/shared/__init__.py` skips phone-panel
> injection when `data-scene="phone"` is present in the response body. This
> prevents a duplicate overlay at z-index 8999 that was blocking all clicks
> on the phone UI.

---

### Penthouse — THE PENTHOUSE (port 5556)

**Class:** `PenthouseScene` · **Routes:** 67 · **Skills:** 11 · **Mixins:** PenthouseCombatMixin, PenthouseSocialMixin

> Updated for v1.04b — character picker, agent loop UI, first-person camera, YAML-driven config

An adult roleplay scene featuring multi-character support with full emotion
system, outfit management, room-based location mechanics, and an AI agent loop.

#### v1.04b Features

##### Character Picker Overlay

A modal overlay for selecting and loading characters into the scene:

- **`GET /api/characters/list`** — Lists all available database characters with load status
- **`POST /api/character/load`** — Loads a character with optional personality profile
  assignment (`bold_dominant`, `shy_submissive`, `playful_tease`,
  `intellectual_aloof`, `nurturing_warm`). Max 2 characters enforced.
- **`POST /api/character/remove`** — Removes a character from the active scene
- **`GET /api/characters/loaded`** — Lists currently loaded characters with full state

##### Agent Loop UI (Start / Stop / Tick)

The director panel exposes agent loop controls with a live status indicator:

- **Start** — Activates the `AgentLoop`, enabling autonomous character decisions
- **Stop** — Pauses the agent loop while preserving state
- **Tick** — Manually triggers a single agent decision cycle
- Scene state includes `agent_loop_running: bool` flag broadcast via Socket.IO
- Player chat messages are injected into the loop via `_inject_to_loop()`

##### Model Assignment

Per-character LMStudio model selection via the director panel:

- Dropdown lists available models from the LMStudio backend
- Each character can be assigned a different model for inference
- API calls proxy through the backend — **no direct frontend-to-LMStudio calls**

##### First-Person Camera Mode

Pointer-lock first-person view with room-bounded movement:

- **WASD** — Movement within room bounds
- **Mouse look** — Free camera rotation via pointer lock
- Configurable via `scenes.penthouse.enable_first_person: true` in YAML
- Toggle between overview and first-person via `default_camera_view` setting

##### Director Mode (8 Tabs)

| Tab | Purpose |
|-----|---------|
| Scene | Lighting presets, time-of-day, room overview |
| Cast | Character picker, load/remove, personality assignment |
| Dialog | Chat controls, agent loop Start/Stop/Tick |
| Actions | Game actions, dice rolls, activity suggestions |
| Scenario | Scenario selection with mood shifts |
| World | World tick, location graph, furniture interaction |
| Settings | Camera mode, model assignment, YAML overrides |
| Debug | ARGUS LiveDebugger, state inspection, Socket.IO monitor |

##### Backend Proxy for LMStudio

All LMStudio API calls route through the Flask backend, not directly from the
frontend. This ensures:
- Bearer token (`lmstudio.api_token`) stays server-side
- Request shaping and governance interceptors apply
- No CORS or token-exposure issues in the browser

##### YAML-Configurable Settings

All scene parameters are exposed in `config/default.yaml` under
`scenes.penthouse`. See [Configuration](CONFIGURATION.md) for the full block
including positions, outfits, personality profiles, stats, agent loop interval,
and camera settings.

#### Skills

| Skill | Description |
|-------|-------------|
| `penthouse_status` | Scene state — mood, outfit, time, location |
| `penthouse_suggestion` | Suggest an activity |
| `penthouse_set_mood` | Set room mood lighting |
| `penthouse_change_outfit` | Change character outfit |
| `penthouse_game_action` | Trigger a game mechanic |
| `penthouse_roll_dice` | Roll dice for outcomes |
| `penthouse_move_room` | Change room location |
| `penthouse_inventory` | View inventory |
| `penthouse_combat_attack` | Combat attack action |
| `penthouse_combat_defend` | Combat defense action |
| `penthouse_combat_status` | Current combat state |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/chat` | Chat with character |
| POST | `/api/suggest` | Get activity suggestion |
| POST | `/api/mood` | Set room mood |
| POST | `/api/outfit` | Change outfit |
| GET | `/api/characters` | List characters |
| GET | `/api/state` | Full game state |
| GET | `/api/characters/list` | Character picker — available characters |
| POST | `/api/character/load` | Load character with personality |
| POST | `/api/character/remove` | Remove character from scene |
| GET | `/api/characters/loaded` | Currently loaded characters |
| POST | `/api/character/stats/adjust` | Adjust stat by delta |
| POST | `/api/location/move` | Move character to position |
| GET | `/api/scenario/list` | Available scenarios |
| POST | `/api/scenario/set` | Load scenario with mood shifts |

#### Socket.IO Events

| Event | Direction | Purpose |
|-------|-----------|---------|
| `chat_message` | Client→Server | Inject player message into agent loop |
| `quick_stat` | Client→Server | Adjust character stat |
| `director_nudge` | Client→Server | Nudge direction (escalation/cool_down/revelation) |
| `load_scenario` | Client→Server | Load scenario beat |
| `world_tick` | Client→Server | Push world state update |
| `request_state` | Client→Server | Request full state broadcast |

#### State

- Emotion system (0–100 per axis: arousal, pleasure, happiness, horniness, and 6 more)
- Room graph with connected locations (bed, couch, fireplace, bar, bathroom, vanity, balcony, doorway)
- Outfit system with 10 outfit states
- Time-of-day cycle affecting dialogue context
- Combat system via PenthouseCombatMixin
- Agent loop with configurable interval (`agent_loop_interval: 8`)

---

### Lounge — THE VELVET PIT (port 5557)

**Class:** `LoungeScene` · **Routes:** 16 · **Skills:** 4

A speakeasy social scene with character conversations, drinking games, and
ambient event generation.

#### Skills

| Skill | Description |
|-------|-------------|
| `lounge_status` | Scene state — patrons, vibe, events |
| `lounge_order_drink` | Order a drink for credits |
| `lounge_start_game` | Start a drinking game |
| `lounge_gossip` | Get gossip from characters |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/chat` | Chat with lounge character |
| POST | `/api/order` | Order a drink |
| GET | `/api/state` | Current lounge state |
| GET | `/api/events` | Recent lounge events |

#### State

- Patron list with mood tracking
- Economy integration (drink prices, credits)
- Ambient event generation (arguments, music changes, arrivals)

---

### Tavern — THE RUSTY ANCHOR (port 5558)

**Class:** `TavernScene` · **Routes:** 15 · **Skills:** 4

A fantasy RPG tavern with character interactions, dice games, and a barter
economy.

#### Skills

| Skill | Description |
|-------|-------------|
| `tavern_status` | Tavern state — patrons, atmosphere |
| `tavern_order` | Order food or drink |
| `tavern_barter` | Negotiate prices |
| `tavern_dice_game` | Play a dice game |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/chat` | Chat with tavern character |
| POST | `/api/order` | Order food/drink |
| POST | `/api/barter` | Barter with merchant |
| POST | `/api/dice` | Roll dice |

#### State

- Menu system with item prices
- Barter mechanic with haggling
- Dice game with wager system

---

### Casino — CLUB NOIR (port 5559)

**Class:** `CasinoScene` · **Routes:** 16 · **Skills:** 6

A neon-noir casino with blackjack, poker, slots, and a high-roller VIP area.
Economy is wired through the chip/credit system.

#### Skills

| Skill | Description |
|-------|-------------|
| `casino_status` | Casino state — chips, tables, jackpot |
| `casino_blackjack` | Play blackjack |
| `casino_slots` | Pull the slots |
| `casino_poker_bet` | Place poker bet |
| `casino_exchange` | Exchange credits ↔ chips |
| `casino_vip_access` | Check VIP status |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/chat` | Chat with casino character |
| POST | `/api/blackjack/hit` | Blackjack hit |
| POST | `/api/blackjack/stand` | Blackjack stand |
| POST | `/api/slots/pull` | Pull slot machine |
| POST | `/api/exchange` | Credit ↔ chip exchange |
| GET | `/api/state` | Casino game state |

#### State

- Chip balance per player
- Card deck state for blackjack/poker
- Slot machine RNG with jackpot accumulation
- Economy degraded-fallback tracking

---

### Gallery — THE OBSCURA (port 5560)

**Class:** `GalleryScene` · **Routes:** 20 · **Skills:** 6

An interactive art gallery where AI generates artworks, characters critique
them, and exhibitions rotate on schedule.

#### Skills

| Skill | Description |
|-------|-------------|
| `gallery_status` | Gallery state — exhibitions, visitors |
| `gallery_create_art` | Generate new artwork via ComfyUI |
| `gallery_critique` | Get AI critique of artwork |
| `gallery_curate` | Arrange exhibition layout |
| `gallery_auction` | Start art auction |
| `gallery_visit` | Visit a gallery section |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/generate` | Generate artwork |
| GET | `/api/gallery` | List current exhibitions |
| POST | `/api/critique` | Get AI art critique |
| POST | `/api/auction/bid` | Place auction bid |
| GET | `/api/state` | Gallery state |

#### State

- Exhibition collections with artwork metadata
- Auction system with bidding history
- Art generation history linked to ComfyUI

---

### Arena — THE COLOSSEUM (port 5561)

**Class:** `ArenaScene` · **Routes:** 14 · **Skills:** 7

A tactical card battle arena with deck building, turn-based combat, and
tournament brackets.

#### Skills

| Skill | Description |
|-------|-------------|
| `arena_status` | Arena state — matches, standings |
| `arena_challenge` | Challenge another fighter |
| `arena_play_card` | Play a card from hand |
| `arena_draw_card` | Draw from deck |
| `arena_view_hand` | View current hand |
| `arena_deck_build` | Modify deck composition |
| `arena_tournament` | Join or view tournament |

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/match/start` | Start arena match |
| POST | `/api/match/play` | Play card |
| POST | `/api/match/draw` | Draw card |
| GET | `/api/deck` | View deck |
| GET | `/api/tournament` | Tournament bracket |
| GET | `/api/state` | Arena state |

#### State

- Deck system with card types, costs, and effects
- Match state (turns, HP, hand, graveyard)
- Tournament brackets with elimination tracking

---

### Realm — THE SHATTERED THRONE (port 5562)

**Class:** `RealmScene` · **Routes:** 31 · **Skills:** 14

A full-featured LitRPG with a dual-agent system (Director narrates, Assistant
provides fourth-wall commentary), d20 combat, inventory, and murder mystery
sub-games.

#### Skills

| Skill | Description |
|-------|-------------|
| `realm_status` | Full game state |
| `realm_inventory` | View/manage inventory |
| `realm_equip` | Equip weapon or armor |
| `realm_use_item` | Consume item |
| `realm_adjust_hp` | Heal or damage |
| `realm_start_combat` | Initiate encounter |
| `realm_combat_attack` | Roll d20 + STR to attack |
| `realm_combat_defend` | Halve incoming damage |
| `realm_combat_flee` | Attempt escape |
| `realm_combat_use_item` | Use consumable in combat |
| `realm_director_status` | Check patience, mutiny state |
| `realm_fourth_wall_steal` | Break fourth wall |
| `realm_desperation_dice` | Sacrifice max HP to reset Director context |
| `realm_murder_status` | Murder mystery: phase, clues, accusations |

#### Mechanics

- **Dual-agent** — Director (game master) + Assistant (fourth-wall companion)
- **Combat** — d20 + stat_mod vs DC. Nat 20 = critical. Death at HP ≤ 0 → lose item, respawn
- **Exploration** — Room discovery: 30% encounter, 40% loot, 30% empty
- **Murder mystery** — Investigation phases, 3+ clues to unlock accusation
- **Director patience** — Decreases each turn; at 0 → mutiny (forced narrative)
- **Skill checks** — persuasion, lockpicking, arcana, athletics, stealth, intimidation, deception, investigation, survival

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/game/new` | Initialize new game |
| POST | `/api/game/action` | Execute player action |
| POST | `/api/choice` | Submit player choice |
| POST | `/api/director/infer` | Get Director narration + choices |
| POST | `/api/assistant/infer` | Get Assistant commentary |
| GET | `/api/game` | Fetch current game state |

#### State

- `RealmGameState` — HP, MP, XP, Level, STR/AGI/INT/CHA/LCK, inventory, location graph, quests, combat, murder mystery
- Stateful Director/Assistant conversation IDs
- Director patience meter

---

### Neon City — NEON CITY (port 5563)

**Class:** `NeonCityScene` · **Routes:** 17 · **Skills:** 8

A cyberpunk battle-royale board game on a shrinking grid with hacking, factions,
and dynamic street events.

#### Skills

| Skill | Description |
|-------|-------------|
| `neoncity_status` | Turn, storm radius, alive players |
| `neoncity_player_info` | HP, position, weapons, implants |
| `neoncity_move` | Move on grid (may discover loot) |
| `neoncity_attack` | Attack player with weapon |
| `neoncity_hack` | Breach AI firewall |
| `neoncity_storm_status` | Storm boundary and danger zones |
| `neoncity_trigger_event` | Trigger random event |
| `neoncity_end_turn` | Process AI turns, advance round |

#### Mechanics

- **12×12 grid** with procedural loot locations
- **Glitch Storm** — Shrinking safe zone; outside = 15 damage/turn
- **Combat** — Turn-based with weapons, accuracy, criticals (10%, 2× damage)
- **Hacking** — Progressive firewall breaching to defeat AI at grid center
- **AI opponents** — Up to 3 AI players with behavior profiles
- **Events** — 30% per turn: blackouts, drone strikes, supply drops

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/game/new` | Start new game |
| POST | `/api/game/move` | Move player |
| POST | `/api/game/attack` | Combat attack |
| POST | `/api/game/hack` | Breach firewall |
| POST | `/api/game/end_turn` | End turn, process AI |

---

### Coders Room — THE LAB (port 5564)

**Class:** `CodersRoomScene` · **Routes:** 10 · **Skills:** 6

An AI coding room where agents collaboratively write, review, and test Python
code in an idle-simulation loop with a 5-phase pipeline.

#### Skills

| Skill | Description |
|-------|-------------|
| `coders_status` | Simulation state (ticks, features, agents) |
| `coders_agent_info` | Agent stats (lines written, reviews, tests) |
| `coders_add_feature` | Queue a feature request |
| `coders_feature_list` | List pipeline and completed features |
| `coders_run_code` | Execute Python in sandbox (10s timeout) |
| `coders_tick` | Advance pipeline by one tick |

#### Mechanics

- **5-phase pipeline** — FEATURE → DESIGN → CODING → REVIEW → TESTING
- **Role-based agents** — Reviewer (specs), Writer (code), QA (tests)
- **Real code generation** — LLM generates actual Python
- **Sandboxed execution** — 10-second subprocess with pytest
- **Failure handling** — Consecutive failures trigger rollback to DESIGN

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/start` | Start simulation |
| POST | `/api/stop` | Stop simulation |
| GET | `/api/state` | Current state |
| POST | `/api/feature/add` | Queue feature |
| POST | `/api/tick` | Manual pipeline advance |

---

### Heist — THE SCORE (port 5565)

**Class:** `HeistScene` · **Routes:** 14 · **Skills:** 7

Cooperative heist planning and execution with specialized crew roles and
phase-gated operations.

#### Skills

| Skill | Description |
|-------|-------------|
| `heist_status` | Current heist state |
| `heist_plan` | Start planning phase |
| `heist_assign_role` | Assign crew member role |
| `heist_execute` | Execute heist phase |
| `heist_abort` | Abort current heist |
| `heist_intel` | Gather intel on target |
| `heist_getaway` | Initiate getaway |

#### Mechanics

- **Phase-gated** — Planning → Recon → Execution → Getaway
- **Crew roles** — Hacker, Muscle, Thief, Driver, Inside Man
- **Heat system** — Failed checks increase heat; too high triggers police
- **Multiple targets** — Bank, casino vault, corp server, museum
- **Crew synergy** — Role combinations unlock special actions

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/heist/start` | Begin heist planning |
| POST | `/api/heist/assign` | Assign crew roles |
| POST | `/api/heist/execute` | Execute phase |
| POST | `/api/heist/abort` | Abort heist |
| GET | `/api/heist/state` | Current heist state |

---

### Games — THE ARCADE (port 5567)

**Class:** `GamesScene` · **Routes:** 20 · **Skills:** 6

A multi-game arcade hub with trivia, chess puzzles, word games, and
leaderboards.

#### Skills

| Skill | Description |
|-------|-------------|
| `games_status` | Arcade state, available games |
| `games_start` | Start a new game session |
| `games_action` | Submit game action |
| `games_leaderboard` | View leaderboard |
| `games_challenge` | Challenge another player |
| `games_hint` | Get hint for current puzzle |

#### Mechanics

- **Multiple game types** — Trivia, chess puzzles, word association, memory
- **Leaderboard system** — Per-game rankings with score tracking
- **AI opponents** — Configurable difficulty levels
- **Challenge mode** — Player-vs-character matches

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/game/start` | Start game session |
| POST | `/api/game/action` | Submit action |
| GET | `/api/leaderboard` | View scores |
| GET | `/api/games/list` | Available games |
| GET | `/api/state` | Arcade state |

---

### Lab Break — LAB BREAK (port 5571)

**Class:** `LabBreakScene` · **Routes:** 13 · **Skills:** 8

A psychological survival horror escape room where characters have vitals
(hunger, energy, stress, sanity), emotional bonds, and must be persuaded to
cooperate for escape.

#### Skills

| Skill | Description |
|-------|-------------|
| `lab_status` | Full lab state — areas, vitals, bonds |
| `lab_inspect` | Inspect an area or object |
| `lab_move` | Move to adjacent area |
| `lab_interact` | Interact with object or character |
| `lab_persuade` | Attempt persuasion (difficulty check) |
| `lab_rest` | Rest to restore energy/sanity |
| `lab_feed` | Feed a character (reduces hunger) |
| `lab_escape_attempt` | Attempt escape (requires conditions) |

#### Mechanics

- **Vitals system** — hunger, energy, stress, sanity (0–100 each)
- **Emotional bonds** — trust/fear/loyalty between characters
- **Persuasion** — Difficulty checks based on relationship + sanity
- **Area exploration** — Connected rooms with discoverable objects
- **Escape conditions** — Multiple requirements must be met
- **Degradation** — Vitals decay over time; low sanity → hallucinations

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/game/new` | Start new lab scenario |
| POST | `/api/game/action` | Execute action |
| GET | `/api/game/state` | Current lab state |
| GET | `/api/game/vitals` | Character vitals |
| POST | `/api/game/persuade` | Attempt persuasion |

---

## Lab Break Survival System

Lab Break (port 5571) implements a full survival simulation with stat decay,
crafting, item management, death tracking, and multiple escape routes.

### Survival Stats

6 stats with continuous decay timers:

| Stat | Decay Rate | Death Trigger |
|------|-----------|---------------|
| Hunger | −1 / min | health damage at 0 |
| Energy | −0.5 / min | collapse at 0 |
| Hydration | −0.8 / min | health damage at 0 |
| Health | no natural decay | death at 0 |
| Stress | +0.3 / min | sanity damage at threshold |
| Sanity | −0.2 / min | hallucinations at low values |

Death occurs when health reaches 0. The system tracks cause of death
(starvation, dehydration, injury, stress collapse) for post-mortem display.

### Item Catalog

30 items across 5 categories:

| Category | Count | Examples |
|----------|-------|---------|
| Food | 8 | Rations, canned goods, protein bars |
| Medical | 6 | Bandages, painkillers, medkit |
| Tools | 7 | Wrench, wire cutters, flashlight |
| Key Items | 5 | Keycard, fuse, circuit board |
| Materials | 4 | Scrap metal, chemicals, tape |

### Crafting

4 crafting recipes combining found items:

| Recipe | Ingredients | Result |
|--------|-------------|--------|
| Lockpick | Wire + Wrench | Opens locked doors |
| EMP Device | Circuit board + Chemicals | Disables cameras |
| Medkit+ | Bandages + Painkillers | Full health restore |
| Rope Ladder | Tape + Scrap metal | Enables vent escape |

### Escape Routes

4 escape routes, each with stat and item requirements:

| Route | Requirements | Difficulty |
|-------|-------------|-----------|
| Main Door | Keycard + EMP Device | Medium |
| Ventilation | Rope Ladder, Energy ≥ 50 | Hard |
| Sewers | Flashlight, Sanity ≥ 40 | Hard |
| Negotiate | Persuasion skill, Trust ≥ 70 | Very Hard |

### Agent Grid

Characters occupy positions on a room-based grid. Movement between adjacent
rooms costs energy. Interaction with objects and other characters is
position-dependent — agents must be in the same room.

### Checkpoint System

Game state is saved to `localStorage` at key moments (room transitions,
item pickups, stat thresholds). Players can load from the last checkpoint
on death or page reload.

---

## Scene Reference — Utility Scenes

---

### Hub — THE TERMINAL (port 8500)

**Class:** `HubScene` · **Routes:** 14

The central navigation hub and scene launcher. Renders discovery cards for all
registered scenes using the port registry.

#### Features

- **Scene cards** — Auto-generated from `HUB_CATALOGUE_TARGETS` in port registry
- **Status dots** — Green/red indicator per scene based on health checks
- **Quick actions** — Launch scene, view health, open admin
- **Scene creator** — `scene_creator.py` wizard for scaffolding new scenes

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Hub landing page |
| GET | `/api/scenes/list` | All discoverable scenes |
| GET | `/api/scenes/status` | Health check all scenes |
| GET | `/api/health` | Hub health |

---

### Asset Studio — ASSET STUDIO (port 5568)

**Class:** `AssetStudioScene` · **Routes:** 33 · **Skills:** 8

ComfyUI-powered asset generation studio for character portraits, scene
backgrounds, and UI elements.

#### Skills

| Skill | Description |
|-------|-------------|
| `studio_status` | Studio state, queue status |
| `studio_generate` | Generate image via ComfyUI |
| `studio_list_assets` | List generated assets |
| `studio_get_asset` | Get specific asset details |
| `studio_delete_asset` | Delete asset |
| `studio_workflows` | List available workflows |
| `studio_queue_status` | ComfyUI queue position |
| `studio_inject` | Inject asset into scene |

#### Features

- **Workflow library** — Portrait, landscape, video (Wan 2.2 GGUF), upscale
- **Asset database** — `data/asset_registry.db` with tags, metadata, character links
- **Scene injection** — Push generated assets directly into scene templates
- **Batch generation** — Queue multiple prompts
- **Tab UI** — Generate, Library, Images, Portraits, Workflows

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/generate` | Submit generation job |
| GET | `/api/assets` | List all assets |
| GET | `/api/assets/<id>` | Get asset details |
| DELETE | `/api/assets/<id>` | Delete asset |
| GET | `/api/workflows` | Available ComfyUI workflows |
| GET | `/api/queue` | Queue status |

---

### Nexus Panel — Nexus Control Panel (port 5570)

**Class:** `NexusPanelScene` · **Routes:** 114 · **Skills:** 6

The richest route surface in CosySim. Full Nexus knowledge management with
CRUD, search, research sessions, rule management, and analytics dashboards.

#### Skills

| Skill | Description |
|-------|-------------|
| `nexus_panel_status` | Panel state, entry counts |
| `nexus_panel_search` | Search knowledge base |
| `nexus_panel_add` | Add knowledge entry |
| `nexus_panel_stats` | Knowledge analytics |
| `nexus_panel_rules` | List governance rules |
| `nexus_panel_health` | Nexus system health |

#### Features

- **Knowledge CRUD** — Create, read, update, delete Nexus entries
- **Full-text search** — FTS5-powered search across all knowledge
- **Research sessions** — Multi-turn NotebookLM research management
- **Rule browser** — View and manage governance rules
- **Analytics** — Entry counts by category, growth trends, Q&A cache stats
- **Import/Export** — Bulk knowledge import and backup
- **Query router stats** — Cache hit rates, tier usage

#### Key Routes (subset of 114)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/entries` | List/search entries |
| POST | `/api/entries` | Create entry |
| GET | `/api/entries/<id>` | Get entry |
| PUT | `/api/entries/<id>` | Update entry |
| DELETE | `/api/entries/<id>` | Delete entry |
| GET | `/api/search` | Full-text search |
| GET | `/api/rules` | List rules |
| GET | `/api/stats` | Knowledge stats |
| POST | `/api/research/start` | Start research session |
| GET | `/api/qa` | Q&A cache entries |

---

### Intel Hub — THE BRIEFING ROOM (port 5580)

**Class:** `IntelHubScene` · **Routes:** 77 · **Skills:** 5

Intelligence dashboard with operator console, system health monitoring, news
feeds, benchmark tracking, and operator inbox integration.

#### Skills

| Skill | Description |
|-------|-------------|
| `intel_status` | Intel Hub state |
| `intel_news` | Latest curated news |
| `intel_benchmarks` | Benchmark history |
| `intel_system_health` | System service health |
| `intel_operator_notes` | Operator inbox digest |

#### Features

- **Operator console** — Submit notes, view queue, process directives
- **System health** — Real-time service status (Nexus, LMStudio, TTS, NLM)
- **News feed** — Curated AI/tech/world news from pipeline
- **Benchmark dashboard** — SVG sparkline charts, quality trends
- **World events** — Live ticker from WorldSim
- **Git summary** — Recent commits and branch status
- **Activity log** — Recent system operations

#### Key Routes (subset of 77)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/intel/status` | System overview |
| GET | `/api/intel/news` | News feed |
| GET | `/api/intel/benchmarks` | Benchmark data |
| GET | `/api/intel/health` | Service health checks |
| POST | `/api/operator/submit` | Submit operator note |
| GET | `/api/operator/queue` | Operator queue |
| POST | `/api/operator/process` | Process pending notes |

---

### System Control — System Control Panel (port 5575)

**Class:** `SystemControlScene` · **Routes:** 12

System administration panel exposing service management, port registry, and
configuration controls.

#### Features

- **Service management** — Start/stop/restart individual services
- **Port registry** — View canonical port assignments
- **Config viewer** — Read current `default.yaml` configuration
- **Log viewer** — Tail service log files
- **Health dashboard** — Aggregate health status

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/services` | List all services |
| POST | `/api/services/<name>/restart` | Restart service |
| GET | `/api/ports` | Port registry dump |
| GET | `/api/config` | Config viewer |
| GET | `/api/logs/<service>` | Tail log file |

---

## Scene Reference — Service Scenes

---

### Command Center (port 5566)

**Class:** `CommandCenterScene` · **Routes:** 38 · **Skills:** 5

Real-time system monitoring dashboard with command execution, scheduler
visibility, and system metrics.

#### Skills

| Skill | Description |
|-------|-------------|
| `cmd_status` | Command center state |
| `cmd_execute` | Execute system command |
| `cmd_scheduler` | View scheduler tasks |
| `cmd_metrics` | System performance metrics |
| `cmd_logs` | View system logs |

#### Features

- **Command execution** — Run system commands with output capture
- **Scheduler dashboard** — All 55 scheduler tasks with status
- **System metrics** — CPU, memory, GPU, network
- **Log streaming** — Real-time log output via Socket.IO
- **Alert system** — Configurable thresholds for health alerts

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/command/execute` | Execute command |
| GET | `/api/scheduler/tasks` | List scheduler tasks |
| GET | `/api/metrics` | System metrics |
| GET | `/api/logs/stream` | Log stream (SSE) |
| GET | `/api/state` | Center state |

---

### Grid — THE GRID (port 5569)

**Class:** `GridScene` · **Routes:** 15 · **Skills:** 6

An underground marketplace and faction hub with dynamic economy, price
fluctuations driven by WorldSim events, and faction allegiance mechanics.

#### Skills

| Skill | Description |
|-------|-------------|
| `grid_status` | Grid state — market, factions |
| `grid_buy_item` | Buy from market |
| `grid_sell_item` | Sell to market |
| `grid_get_market_prices` | Current price list |
| `grid_faction_pledge` | Pledge to a faction |
| `grid_broker_intel` | Buy intel from broker |

#### Zones

- **THE MARKET** — Buy/sell items, prices fluctuate with economy_tick events
- **THE STATION** — Neon City travel hub, SVG map of scene locations
- **THE DEN** — Faction headquarters, allegiance, and faction quests
- **THE BROKER** — Information trading, Nexus-powered intel feed

#### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/market/items` | Market catalogue |
| POST | `/api/market/buy` | Buy item |
| POST | `/api/market/sell` | Sell item |
| GET | `/api/market/price_history/<id>` | Price history |
| POST | `/api/faction/pledge` | Faction pledge |
| GET | `/api/state` | Grid state |

---

## Socket.IO Event Reference

| Event | Direction | Scenes | Purpose |
|-------|-----------|--------|---------|
| `message` | Server→Client | All chat scenes | Character message |
| `state_update` | Server→Client | Most scenes | Game state change |
| `hud_update` | Server→Client | All via HUD | Player state / world update |
| `world_event` | Server→Client | All via HUD | World event notification |
| `price_update` | Server→Client | Grid, Casino | Economy price change |
| `connect` | Client→Server | All | Socket.IO connection |
| `chat` | Client→Server | Chat scenes | Player chat message |
| `action` | Client→Server | Game scenes | Player action |
| `typing` | Server→Client | Phone, Penthouse | Character typing indicator |
| `new_message` | Server→Client | Phone | Incoming text message |
| `game_update` | Server→Client | Games, Arena | Game state change |
| `combat_update` | Server→Client | Arena, Realm | Combat state change |
| `economy_banner` | Server→Client | Grid, Casino | Major economy event |

---

## Route Distribution

| Rank | Scene | Routes | Type |
|------|-------|--------|------|
| 1 | nexus_panel | 114 | Utility |
| 2 | intel_hub | 77 | Utility |
| 3 | penthouse | 67 | Game |
| 4 | phone | 66 | Game |
| 5 | command_center | 38 | Service |
| 6 | asset_studio | 33 | Utility |
| 7 | realm | 31 | Game |
| 8 | games | 20 | Game |
| 9 | gallery | 20 | Game |
| 10 | neoncity | 17 | Service |

**Total routes:** ~613 across 20 Flask scenes
**Average:** 30.6 per scene · **Median:** 17

---

## Mixin Usage

| Mixin | Count | Scenes |
|-------|-------|--------|
| `NexusSceneMixin` | 16 | penthouse, phone, lounge, tavern, casino, gallery, arena, realm, neoncity, coders, heist, games, grid, lab_break, intel_hub, nexus_panel |
| `MCPSceneMixin` | 14 | penthouse, phone, lounge, tavern, casino, gallery, arena, realm, neoncity, coders, heist, games, grid, lab_break |
| `PenthouseCombatMixin` | 1 | penthouse |

---

## Health Checking

Run after any scene change:

```powershell
python scripts/scene_health_check.py --port <PORT> --fix
```

This validates:
- `/api/health` returns 200
- All shared assets load (`/shared/css/`, `/shared/js/`)
- Navbar v2 renders
- Socket.IO connects
- Scene-specific routes respond

Full scene health sweep:

```powershell
python scripts/scene_health_check.py --all
```

---

## See Also

- [Architecture](ARCHITECTURE.md) — Engine subsystem details
- [MCP Framework](MCP_FRAMEWORK.md) — Skill and interceptor patterns
- [Nexus Integration](NEXUS_INTEGRATION.md) — Knowledge system wiring
- [Configuration](CONFIGURATION.md) — `config/default.yaml` scene settings
