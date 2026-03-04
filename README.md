# CosySim

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![Tests: 8811](https://img.shields.io/badge/tests-8%2C811%2B%20passing-brightgreen.svg)]() [![Grade: A++](https://img.shields.io/badge/audit-A%2B%2B-gold.svg)]() [![Version: 0.85b](https://img.shields.io/badge/version-0.85b-blueviolet.svg)]()

> v0.85b — "THE MAINTENANCE LAYER" — Multi-scene AI simulation framework

## Overview

CosySim orchestrates virtual AI agents across **16 interactive scenes**, each a self-contained Flask+Socket.IO web app with its own LLM agents, MCP skill packs, game logic, and real-time state. The **Universal Neon HUD v2** (glass slide panels, phone overlay, world announcer) surfaces player vitals, inventory, crew, and faction standings live across all scenes via the `PlayerState` singleton. A **214-tool MCP pipeline**, 25+ `@skill` packs, 26-interceptor governance (auto-registry), Nexus KMS knowledge layer, and local LMStudio GPU inference make CosySim a complete agentic simulation OS.

v0.85b — **THE MAINTENANCE LAYER** — the system begins taking care of itself: Google auth cookies are renewed automatically via CDP from the running Chrome instance, test suite regressions are benchmarked and logged to Nexus weekly, the Nexus bridge CLI is fully operational, and the project has a complete narrative history document (`docs/PROJECT_JOURNAL.md`) for agent onboarding.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (Neon HUD v2: glass panels · phone overlay · announcer)    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Socket.IO / REST
┌────────────────────────────▼────────────────────────────────────────┐
│              16 Scenes  (Flask / Socket.IO)                         │
│  phone·bedroom·lounge·tavern·casino·gallery·arena·realm·neoncity   │
│  coders·heist·command·games·asset_studio·grid·intel_hub             │
└──────────┬──────────────────────────────────────┬───────────────────┘
           │                                      │
┌──────────▼──────────┐              ┌────────────▼────────────────────┐
│ 214+ Skills         │              │  MCP Pipeline  (26 interceptors) │
│ (25+ skill packs)   │◄────────────►│  auto-registry · @mcp_tool       │
└──────────┬──────────┘              └────────────┬────────────────────┘
           │                                      │
┌──────────▼──────────────────────────────────────▼───────────────────┐
│                        Engine Layer                                  │
│  agents/mcp/scenes · lmstudio · nexus · world · integrations        │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐   │
│  │  engine/mcp/tools/ (43)     │  │  engine/nexus/models.py     │   │
│  │  domain tool logic          │  │  Pydantic v2 typed models   │   │
│  └─────────────────────────────┘  └─────────────────────────────┘   │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐   │
│  │  Inventory / Crew           │  │  WorldSim / PlayerState      │   │
│  │  engine/world/              │  │  economy tick · event cascade│   │
│  └─────────────────────────────┘  └─────────────────────────────┘   │
└────────┬──────────────────────────────────────────┬─────────────────┘
         │                                          │
┌────────▼──────────────┐              ┌────────────▼──────────────────┐
│  LMStudio v1 API      │              │  Nexus KMS  :8700             │
│  :1234 (CUDA)         │              │  FTS5 · NLM · Q&A · news      │
└───────────────────────┘              └───────────────────────────────┘
         │
┌────────▼─────────────────────────────────────────────────────────────┐
│  External Services                                                    │
│  Qwen3 TTS :8600 · ComfyUI :8188 · Asset Studio :5568               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Features by Version Wave

### THE MAINTENANCE LAYER (v0.85b) — Latest

- **`scripts/har_capture.py`** — 3-mode Google cookie refresh: CDP direct (connects to running Chrome port 9222, `Network.getCookies()`, ~1s zero-UI), launch mode, macro fallback
- **`scripts/har_watchfolder.py`** — drop-folder auto-import for `.har` files (30s poll)
- **`GoogleAccountPool`** — staleness API: `cookie_age_days()`, `is_stale()`, `get_stale_accounts()`
- **Scheduler tasks #48–50** — `cookie-health-check` (daily), `cookie-auto-refresh` (every 72h), `test-suite-benchmark` (weekly, Nexus trend logging + regression alert)
- **`engine/skills/builtin/google_account_skills.py`** — `google_accounts` pack (4 skills)
- **Nexus bridge CLI fixed** — `_parse_entry`/`_parse_rule` handle JSON-string DB fields; `bridge health/search/ask/store` all working
- **`docs/PROJECT_JOURNAL.md`** — 5,000+ word project narrative (v0.51b→v0.84b, 17 chapters) — agent onboarding + alignment source
- **8,811+ tests, 50 scheduler tasks**

---

### THE HINDSIGHT LAYER (v0.84b)

> Complete architectural refactoring — no new features, pure structural improvement.

- **`@mcp_tool` Decorator** — `engine/mcp/decorators.py`: unified error handling, auto JSON serialization, `ToolExecutionError` typed exception. Eliminates ~150 scattered try/except blocks.
- **Domain Tool Modules** — `engine/mcp/tools/` (43 files, 8,147 lines): all MCP tool logic extracted from monolithic servers. Servers become thin routing wrappers.
- **Interceptor Registry** — `engine/agents/interceptors/` (26 individual modules, avg 105 lines each). `@register_interceptor` auto-discovery. `INTERCEPTOR_CACHE` singleton.
- **Pydantic Nexus Models** — `engine/nexus/models.py`: 14 typed models (`NexusEntry`, `NexusRule`, `AgentMemory`, `SessionLog`, etc.) with `_DictCompat` backward-compat mixin.
- **Typed NexusClient** — All `client.py` query methods return typed models. Three domain facades: `rules`, `sessions`, `memory`.
- **Engine-wide HTTP cleanup** — All raw `requests.*` Nexus HTTP calls replaced with `get_nexus_client()`.
- **8,771 tests, 0 failures · Grade A++ (up from B+)**

---

### THE SOCIAL LAYER (v0.83b)

- **Shop System** — `InventoryManager.buy_item()`, `sell_item()`, 26 catalog items with prices; 5 REST shop endpoints
- **Shop Modal UI** — Universal shop overlay (`window.CosyShop.open()`), BLACK MARKET HUD button
- **Crew HUD** — Loyalty bars, trust tier stars, role icons rendered in right panel
- **NeonCity HUD fix** — Jinja2 ChoiceLoader for shared templates across Tavern, Lounge, NeonCity

---

### THE LIVING CITY (v0.81b)

- **Inventory System** — `engine/world/inventory.py`: 25 catalog items, 10 categories, 14 equipment slots, thread-safe, persistent JSON storage
- **Crew System** — `engine/world/crew.py`: 9 roles, loyalty 0–100, XP/levelling (1–5), operations (recon / heist / extraction / deal / hit / hack)
- **HUD v2 — Glass Slide Panels**: Left panel (health/hunger/energy bars, economy, implants, 12-slot inventory grid) + Right panel (phone overlay, crew status, system health)
- **Relationship Types**: 12 types (brother / friend / lover / crew / enemy / etc.), auto-upgrade from score
- **7,800+ tests, 25+ skill packs, 16 scenes**

---

### THE COPILOT LAYER (v0.80b)

- **GitHub Copilot internal API** — 26 frontier models (Claude Opus 4.6, Sonnet 4.6, GPT-5.2 Codex, Gemini 3.1 Pro Preview, etc.)
- `GithubCopilotClient` — auto-refresh token, thread management, SSE streaming, 9 `@skill` tools
- **Compute Router**: tunnel → copilot → lmstudio priority chain
- **8,811 tests**

---

### NEON CITY + FIRST MIND (v0.75–v0.78b)

- Universal Neon HUD, THE GRID scene (4 zones, faction hub), 70+ world events
- **Unified Training System**: ModelZoo (14 types), DataCollector, VoiceTrainer, CoderPipeline
- **NLM news pipeline**: 12 RSS sources, 4 categories, distillation, rating signal
- Router v3 (2,080 examples, 16-class, live fine-tuned), 44 scheduler tasks

---

### Dark Renaissance (v0.68–v0.73b)

- 13 engine modules: EventBus, EconomyManager, ContentGate, ContentEngine, CharacterMemory, ReputationManager, SceneDirector, ConsequenceStore, InvestigationBoard, ArenaEngine, WorldState, WorldSim, EventCascade
- Black glass design system, Three.js 3D particles (12 presets), `navbar_v2`, admin overlay (8 tabs)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (Neon HUD v2: glass panels · phone overlay · announcer)    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Socket.IO / REST
┌────────────────────────────▼────────────────────────────────────────┐
│              16 Scenes  (Flask / Socket.IO)                         │
│  phone·bedroom·lounge·tavern·casino·gallery·arena·realm·neoncity   │
│  coders·heist·command·games·asset_studio·grid·intel_hub             │
└──────────┬──────────────────────────────────────┬───────────────────┘
           │                                      │
┌──────────▼──────────┐              ┌────────────▼────────────────────┐
│ 214+ Skills         │              │  MCP Pipeline  (25 interceptors) │
│ (25+ skill packs)   │◄────────────►│  pre/post hooks · governance     │
└──────────┬──────────┘              └────────────┬────────────────────┘
           │                                      │
┌──────────▼──────────────────────────────────────▼───────────────────┐
│                        Engine Layer                                  │
│  agents/mcp/scenes · lmstudio · nexus · world · integrations        │
│  ┌──────────────────────────┐  ┌────────────────────────────────┐   │
│  │  Inventory / Crew        │  │  WorldSim / PlayerState        │   │
│  │  engine/world/           │  │  economy tick · event cascade  │   │
│  └──────────────────────────┘  └────────────────────────────────┘   │
└────────┬──────────────────────────────────────────┬─────────────────┘
         │                                          │
┌────────▼──────────────┐              ┌────────────▼──────────────────┐
│  LMStudio v1 API      │              │  Nexus KMS  :8700             │
│  :1234 (CUDA)         │              │  FTS5 · NLM · Q&A · news      │
└───────────────────────┘              └───────────────────────────────┘
         │
┌────────▼─────────────────────────────────────────────────────────────┐
│  External Services                                                    │
│  Qwen3 TTS :8600 · ComfyUI :8188 · Asset Studio :5568               │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Features by Version Wave

### THE LIVING CITY (v0.81b) — Latest

- **Inventory System** — `engine/world/inventory.py`: 25 catalog items, 10 categories, 14 equipment slots, thread-safe, persistent JSON storage
- **Crew System** — `engine/world/crew.py`: 9 roles, loyalty 0–100, XP/levelling (1–5), operations (recon / heist / extraction / deal / hit / hack), persistent JSON storage
- **HUD v2 — Glass Slide Panels**: Left panel (health/hunger/energy bars, economy, implants, 12-slot inventory grid, skill pips) + Right panel (phone overlay iframe, quick travel, crew status, system health, Nexus search)
- **Phone Overlay**: Lazy-loaded iframe to SIGNAL :5555, slide-in animation, detach button
- **World Announcer**: 5 station themes, 7 badge categories, Socket.IO live feed, fallback messages
- **PlayerState Expanded**: `health` / `hunger` / `energy` vitals (0–100), `skills` dict, `implants` list
- **Relationship Types**: 12 types (brother / friend / lover / crew / enemy / etc.), auto-upgrade from score, protected types
- **15 new `@skill` tools**: `inventory_skills` (7) + `crew_skills` (8)
- **REST APIs**: `/api/inventory` (5 endpoints), `/api/crew` (6 endpoints)
- **socket.io CDN fix**: local copy served across all 24+ scene templates
- **50 new tests**: `TestInventoryManager`, `TestCrewManager`, `TestInventorySkills`, `TestCrewSkills`
- **7,800+ tests passing · 25+ skill packs · 16 scenes**

---

### THE COPILOT LAYER (v0.80b)

- **GitHub Copilot internal API** — 26 frontier models (Claude Opus 4.6, Sonnet 4.6, GPT-5.2 Codex, Gemini 3.1 Pro Preview, etc.)
- `GithubCopilotClient` — auto-refresh token, thread management, SSE streaming, 9 `@skill` tools
- **Compute Router**: tunnel → copilot → lmstudio priority chain
- **Nexus Canvas** — `CopilotPanel` with model selector and streaming chat
- **8,811 tests**

---

### THE COMPUTE LAYER (v0.79b)

- Google Account Pool + HAR auth, Colab AI Agent RPC client, NotebookLM Direct HTTP client
- Google Drive integration, JIT tunnel server (FastAPI + cloudflared on free Colab GPUs)
- **ComputeRouter**: tunnel → colab_agent → lmstudio; `JITSession` context manager
- **Nexus Canvas**: `ComputePanel`, `HarExplorer`, `RpcExplorer`, `NexusPanel`
- 13 new `@skill` tools, 46 scheduler tasks

---

### NEON CITY (v0.75–v0.78b)

- Universal Neon HUD, THE GRID scene (4 zones, faction hub), 70+ world events
- Economy tick (90s), WorldSim, EventCascade 3-tier fan-out, 6 factions
- **Unified Training System**: ModelZoo (14 types), DataCollector, VoiceTrainer, CoderPipeline
- **NLM news pipeline**: 12 RSS sources, 4 categories, distillation, rating signal
- Router v3 (2,080 examples, 16-class, live fine-tuned), 44 scheduler tasks

---

### Dark Renaissance (v0.68–v0.73b)

- 13 engine modules: EventBus, EconomyManager, ContentGate, ContentEngine, CharacterMemory, ReputationManager, SceneDirector, ConsequenceStore, InvestigationBoard, ArenaEngine, WorldState, WorldSim, EventCascade
- Black glass design system, Three.js 3D particles (12 presets), `navbar_v2`, admin overlay (8 tabs)
- Asset Studio (9-tab, Wan 2.2 GGUF video, A++ tuning engine), Arena scene, news pipeline

---

## Scenes

| Scene | Display Name | Port | Type |
|-------|-------------|------|------|
| `phone` | SIGNAL | 5555 | game |
| `bedroom` | THE PENTHOUSE | 5556 | game |
| `lounge` | THE VELVET PIT | 5557 | game |
| `tavern` | THE RUSTY ANCHOR | 5558 | game |
| `casino` | CLUB NOIR | 5559 | game |
| `gallery` | THE OBSCURA | 5560 | game |
| `arena` | THE COLOSSEUM | 5561 | game |
| `realm` | THE SHATTERED THRONE | 5562 | game |
| `neoncity` | NEON CITY | 5563 | game |
| `coders` | THE LAB | 5564 | utility |
| `heist` | THE SCORE | 5565 | utility |
| `command` | Command Center | 5566 | utility |
| `games` | THE ARCADE | 5567 | utility |
| `asset_studio` | ASSET STUDIO | 5568 | utility |
| `grid` | THE GRID | 5569 | game |
| `intel_hub` | THE BRIEFING ROOM | 5580 | utility |

---

## Skill Packs

| Pack | Skills | Description |
|------|-------:|-------------|
| `world` | 10 | PlayerState, economy, heat, factions |
| `inventory` | 7 | Items, equipment slots, catalog |
| `crew` | 8 | Recruitment, loyalty, operations |
| `relationship` | 8 | NPC relationships, crew tags, types |
| `nexus` | 12 | Knowledge search, Q&A, research |
| `coding` | 8 | Code gen, review, explain, snippets |
| `copilot` | 9 | 26 frontier models via Copilot API |
| `colab` | 13 | Colab GPU, Drive, NLM direct |
| `training` | 10 | Fine-tuning, datasets, benchmarks |
| `profile` | 11 | User profile, conversation analysis, backups |
| `media` | 8 | ComfyUI portraits, video, audio |
| `tts` | 6 | Voice synthesis, Piper/Orpheus/Qwen3 |
| `home` | 15 | Home Assistant 15 skills |
| `news` | 6 | RSS pipeline, distillation, rating |
| `arena` | 8 | Card game, betting, commentary |
| `grid` | 10 | Zone navigation, vendors, faction ops |
| `scene` | 6 | Scene management, transitions |
| `lore` | 5 | NPC backstories, world lore, seeding |
| `economy` | 8 | EconomyManager, transactions, debt |
| `narrative` | 6 | Story arcs, faction events, daily challenges |
| `characters` | 8 | CharacterMemory, reputation, emotions |
| `comms` | 6 | Phone assistant, AnythingLLM bridge |
| `system` | 10 | Scheduler, health, admin, config |
| `debug` | 5 | Diagnostics, trace, hot-reload |
| `nlm` | 10 | NotebookLM forge, batch-ask, distill |

---

## Key Engine Systems

- **MCPFramework** — State tree singleton, 214 tools (106 main + 108 devtools), `@skill` decorator, governed skill calls
- **`@mcp_tool` Decorator** — Unified error handling + JSON serialization for all MCP tools (`engine/mcp/decorators.py`)
- **InterceptorPipeline** — 26 hooks (pre/post), auto-registry via `@register_interceptor`, personality enforcement, content gating, context injection
- **`INTERCEPTOR_CACHE`** — TTL-based cache for interceptor instances (`engine/agents/interceptors/cache.py`)
- **Pydantic Model Layer** — 14 typed models in `engine/nexus/models.py` (`NexusEntry`, `NexusRule`, `AgentMemory`, etc.) with `_DictCompat`
- **PlayerState** — Credits / rep / heat / faction / health / hunger / energy / skills / implants singleton, Socket.IO `hud_update`
- **InventoryManager** — 25 catalog items, 10 categories, 14 equipment slots, thread-safe, persistent to JSON
- **CrewManager** — 9 roles, loyalty 0–100, XP levels 1–5, async operations with auto-reward
- **LMStudio Orchestrator** — v1 API, stateful `response_id` threading, SSE streaming, multi-model routing (big / small / router / draft / copilot / tunnel)
- **WorldSim** — 90s economy tick, 70+ event templates, EventCascade 3-tier fan-out to all 16 scenes
- **Nexus KMS** — FTS5 + 4-tier NLM router (cache → FTS → NLM → LLM), Q&A distillation, prompt versioning, news pipeline
- **NexusClient** — Typed returns (`List[NexusEntry]`), domain sub-clients (`rules`, `sessions`, `memory`)
- **HUD v2** — 32px strip + left/right glass slide panels, phone overlay iframe, world announcer widget
- **Training Pipeline** — ModelZoo 14 types, DataCollector, FinetuneOrchestrator (Unsloth QLoRA), BenchmarkRunner, 44 scheduler tasks
- **DialogSystem** — Conversation threading, context windows, per-character memory
- **AgentGovernor** — Budget tracking, cooldown enforcement, prerequisite checking

---

## External Services

| Service | Port | Purpose |
|---------|-----:|---------|
| LMStudio | 1234 | LLM inference (v1 API, CUDA) |
| ComfyUI | 8188 | Image/video generation |
| Nexus KMS | 8700 | Knowledge management REST API |
| Nexus Panel | 5570 | Nexus control dashboard |
| Qwen3 TTS | 8600 | Text-to-speech server |
| Web Bridge | 8601 | Socket.IO real-time bridge |
| Hub | 8500 | Scene launcher landing page |
| Dashboard | 8501 | System metrics |
| Admin | 8502 | Diagnostic center (GOD mode) |

---

## Quick Start

```bash
# Install
pip install -r requirements.txt && npm install

# Run tests (~7,800 tests)
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Launch a scene
python launcher.py --mode bedroom    # http://localhost:5556

# Launch the hub
python launcher.py                   # http://localhost:8500

# All services (Windows)
.\start_servers.ps1
```

---

## Project Structure

```
CosySim/
├── engine/
│   ├── agents/       # CharacterAgent, VirtualAgent, InterceptorPipeline
│   │   └── interceptors/  # 26 auto-registered interceptor modules
│   ├── mcp/          # MCPFramework, DialogSystem, Governor, MCP Server (214 tools)
│   │   ├── tools/    # 43 domain tool files (Hindsight extraction)
│   │   └── decorators.py  # @mcp_tool unified decorator
│   ├── skills/       # @skill decorator, registry, 25+ builtin packs
│   ├── lmstudio/     # Orchestrator, model manager, router, SSE streaming
│   ├── nexus/        # Nexus KMS client, NLM engine, news pipeline, CLI
│   │   └── models.py # 14 Pydantic v2 typed models
│   ├── world/        # PlayerState, InventoryManager, CrewManager, WorldSim, EventCascade
│   ├── integrations/ # Copilot, Colab, Drive, NLM Direct, ComputeRouter
│   ├── scenes/       # BaseScene, SceneManager, SceneRegistry
│   ├── tts/          # Qwen3-TTS server
│   ├── services/     # ActivityBus, resilience, housekeeping
│   └── config.py     # ConfigManager singleton
├── content/
│   ├── scenes/       # 16 scene implementations
│   └── simulation/   # Database, character system, services
├── config/           # YAML/JSON config (default, dev, prod, voices, skills, mcp)
├── tests/            # pytest suite (8,771+ tests)
├── docs/             # Documentation (INDEX.md entry point)
├── training/         # Fine-tuning pipelines and data
├── main.py           # Application entry point
└── launcher.py       # Scene launcher CLI
```

---

## Testing

CosySim has **8,771 automated tests** covering engine modules, skill packs, scene logic, REST APIs, and integration flows.

```bash
# Full suite (parallel, ~6 min)
python -m pytest tests/ -n auto --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Single file
python -m pytest tests/test_inventory.py -v

# By marker
python -m pytest -m "not slow" tests/
```

---

## Documentation

- **[docs/INDEX.md](./docs/INDEX.md)** — Central navigation hub for all documentation
- **[docs/PROJECT_HINDSIGHT.md](./docs/PROJECT_HINDSIGHT.md)** — Architecture refactoring guide (v0.84b)
- **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — System architecture deep-dive
- **[CHANGELOG.md](./CHANGELOG.md)** — Full sprint-by-sprint history
- **[ROADMAP.md](./ROADMAP.md)** — Upcoming features and planned work

---

## License

MIT — see [LICENSE](./LICENSE)
