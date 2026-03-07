# CosySim

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![Version: 0.90b](https://img.shields.io/badge/version-0.90b-blueviolet.svg)]() [![Scenes: 16](https://img.shields.io/badge/scenes-16-6f42c1.svg)]() [![Scheduler: 55](https://img.shields.io/badge/scheduler-55-0a7f5a.svg)]()

> v0.90b — "THE BASELINE" — Multi-scene AI simulation framework

## Overview

CosySim is a local-first AI simulation framework built around **16 launcher-managed scenes** and **12 launcher-managed services**. The runtime combines Flask/Socket.IO scenes, LMStudio inference, Nexus knowledge tooling, a canonical port registry, **31 auto-registered skill packs / 278 registered skills** (`import engine.skills`), and **42 extracted MCP tool modules** (`engine/mcp/tools/`).

## Runtime Snapshot

| Metric | Value |
|--------|-------|
| Version | **0.90b** — "THE BASELINE" (`launcher.py`, `config/default.yaml`) |
| Pytest collection | **9,646 total / 9,260 default-selected** (`python -m pytest tests/ --collect-only -q`) |
| Scenes | **16** launcher-managed scenes (`launcher.SCENES`) |
| Services | **12** launcher-managed services (`launcher.SERVICES`) |
| Skill registry | **31 packs / 278 skills** after `import engine.skills` |
| MCP tool modules | **42** modules in `engine/mcp/tools/` |
| Scheduler tasks | **55** builtin tasks (`tests/test_scheduler_daemon.py`) |
| Canonical ports | **35** named endpoints in `engine.port_registry._DEFAULT_PORTS` |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (Neon HUD v2: glass panels · phone overlay · announcer)    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Socket.IO / REST
┌────────────────────────────▼────────────────────────────────────────┐
│              16 Scenes  (Flask / Socket.IO)                         │
│  phone·bedroom·lounge·tavern·casino·gallery·arena·realm·neoncity   │
│  coders·heist·command_center·games·asset_studio·grid·intel_hub      │
└──────────┬──────────────────────────────────────┬───────────────────┘
           │                                      │
┌──────────▼──────────┐              ┌────────────▼────────────────────┐
│ 278 Skills          │              │  MCP Pipeline  (26 interceptors) │
│ (31 skill packs)    │◄────────────►│  auto-registry · @mcp_tool       │
└──────────┬──────────┘              └────────────┬────────────────────┘
           │                                      │
┌──────────▼──────────────────────────────────────▼───────────────────┐
│                        Engine Layer                                  │
│  agents/mcp/scenes · lmstudio · nexus · world · integrations        │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐   │
│  │  engine/mcp/tools/ (42)     │  │  engine/nexus/models.py     │   │
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

### THE LOOP (v0.89b) — Latest

- **ARGUS → NotebookLM → Nexus loop** — `scripts/argus/nlm_pipeline.py` creates and reuses per-target notebooks, asks distillation questions, and stores resulting Q&A back into Nexus.
- **Browser-attached NotebookLM auth** — live Chrome CDP refresh (`scripts\har_capture.py`) and ARGUS token harvesting now keep the modern cookie/session pool aligned with real NotebookLM session metadata (`bl`, `f_sid`, `at`, notebook context).
- **Scheduler task #53** — `engine/nexus/scheduler_daemon.py` adds `argus-nlm-distil` to keep the knowledge loop running automatically.
- **Focused coverage** — `tests/test_argus_nlm_pipeline.py` validates state persistence, notebook create/cache flow, upload, distillation, and offline fallback handling.
- **Current testing snapshot** — default pytest selection currently collects **9,125** tests out of **9,497** total.

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
| `command_center` | Command Center | 5566 | utility |
| `games` | THE ARCADE | 5567 | utility |
| `asset_studio` | ASSET STUDIO | 5568 | utility |
| `grid` | THE GRID | 5569 | game |
| `intel_hub` | THE BRIEFING ROOM | 5580 | utility |

---

## Skill Packs

- Importing `engine.skills` currently registers **31 packs / 278 skills**.
- Frequently used packs include `autonomy`, `nexus`, `notebooklm`, `nlm_forge`, `coding`, `coder`, `comfyui`, `tts`, `voice`, `training`, `homeassistant`, `relationships`, and `player_profile`.
- Source of truth: `engine/skills/builtin/` and the runtime registry in `engine/skills/registry.py`.

---

## Key Engine Systems

- **MCPFramework** — State tree singleton, tool routing, `@skill` integration, governed tool calls
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
- **Training Pipeline** — ModelZoo 14 types, DataCollector, FinetuneOrchestrator (Unsloth QLoRA), BenchmarkRunner, scheduler-driven upkeep
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

# Run the default pytest selection
python -m pytest tests/ -v --tb=short

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
│   ├── mcp/          # MCP framework, dialog system, governor, tool handlers
│   │   ├── tools/    # 42 extracted domain tool modules
│   │   └── decorators.py  # @mcp_tool unified decorator
│   ├── skills/       # @skill decorator, registry, 31 auto-registered packs
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
├── tests/            # pytest suite + manual harnesses
├── docs/             # Documentation (INDEX.md entry point)
├── training/         # Fine-tuning pipelines and data
├── main.py           # Application entry point
└── launcher.py       # Scene launcher CLI
```

---

## Testing

Current pytest collection snapshot: **9,497 total tests**, with **9,125 selected by default** under the repository's marker filter (`not slow and not integration`). The live-wire harness in `tests/live_wire_test.py` is manual script entrypoint code and no longer executes during collection.

```bash
# Default suite
python -m pytest tests/ -v --tb=short

# Single file
python -m pytest tests/test_port_registry.py -v

# By marker
python -m pytest -m "integration" tests/
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
