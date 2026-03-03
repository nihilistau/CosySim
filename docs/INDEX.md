# CosySim Documentation Index

> All project documentation in one place. v0.78b — 7,500+ tests, 214 MCP tools, 22 skill packs (198+ skills), 15 scenes.

## Quick Facts — v0.75

| Metric | Value |
|--------|-------|
| Version | **0.75** (2026) — "NEON CITY" |
| Tests passing | **7,500+** across ~210 files |
| MCP tools | **214** |
| Skill packs | **22 packs · 198+ skills** |
| Active scenes | **10** (bedroom, phone, lounge, tavern, casino, gallery, arena, realm, neoncity, grid) |
| System scenes | **5** (coders, heist, games, hub, intel_hub) |
| Scheduler tasks | **39** builtin autonomous tasks |
| Engine modules (v0.68+) | **13** new living-world modules |
| Workflow variants | **15** (image + Wan 2.2 video) |

### Active Scene Ports

| Scene | Display Name | Port |
|-------|-------------|------|
| bedroom | THE PENTHOUSE | 5555 |
| phone | SIGNAL | 5556 |
| lounge | THE VELVET PIT | 5557 |
| tavern | THE RUSTY ANCHOR | 5558 |
| casino | CLUB NOIR | 5559 |
| gallery | THE OBSCURA | 5560 |
| arena | THE COLOSSEUM | 5561 |
| realm | THE SHATTERED THRONE | 5562 |
| neoncity | NEON CITY | 5563 |
| grid | THE GRID | 5569 |

### System Scene Ports

| Scene | Display Name | Port |
|-------|-------------|------|
| coders | THE LAB | 5564 |
| heist | THE SCORE | 5565 |
| games | THE ARCADE | 5566 |
| hub | THE TERMINAL | 8500 |
| intel_hub | THE BRIEFING ROOM | 5580 |

### v0.68 Engine Modules

`EventBus` · `EconomyManager` · `ContentGate` · `ContentEngine` · `CharacterMemory` ·
`ReputationManager` · `SceneDirector` · `ConsequenceStore` · `InvestigationBoard` ·
`SceneArtManager` · `WorldState` · `WorldSim` · `ArenaEngine`

### v0.73 New Modules

`EventCascade` · `NewsPipeline` · `RSSFetcher` · `DedupFilter` · `TuningEngine`

### v0.75 New Modules

`PlayerState` · `NeonCityEvents` · `WorldSkills` · `GridScene` · `GridSkills`

---

## Getting Started

| Doc | Description |
|-----|-------------|
| [README](../README.md) | Project overview, quick start, architecture |
| [Deployment](DEPLOYMENT.md) | Service architecture, startup, ports, health checks |
| [Configuration](CONFIGURATION.md) | All config files and settings |
| [Roadmap](../ROADMAP.md) | Version history and future plans |

## Architecture & Design

| Doc | Description |
|-----|-------------|
| [Architecture](ARCHITECTURE.md) | System design, layers, data flow, interceptor pipeline |
| [Interceptors](INTERCEPTORS.md) | Interceptor pipeline — all 25 hooks, priorities, custom interceptors |
| [MCP Framework](MCP_FRAMEWORK.md) | Tools, governance, state, dialog, rules, skills |
| [Characters](CHARACTERS.md) | Personality, stats, buffs, tags, relationships |
| [Character System](CHARACTER_SYSTEM.md) | CharacterMemory, ReputationManager, emotion model, speech patterns |
| [LMStudio](LMSTUDIO.md) | InferenceOrchestrator, model management, routing, streaming, branching |
| [Spatial System](SPATIAL.md) | SceneMap, Location, character positioning, proximity gating |
| [Architecture Decisions](DECISIONS.md) | Key design decisions and rationale (ADRs) |

## Scenes & Content

| Doc | Description |
|-----|-------------|
| [Asset Studio](ASSET_STUDIO.md) | ComfyUI integration — 15 workflow variants, tuning engine, scene injection, benchmarking |
| [News System](NEWS_SYSTEM.md) | Automated news ingestion, NLM distillation, Nexus Q&A feeds, Intel Hub ticker |
| [Scene Guide](SCENE_GUIDE.md) | Per-scene game mechanics — all 10 active scenes |
| [Scenes Reference](SCENES.md) | All scenes — mechanics, APIs, rules (legacy reference) |
| [Skills](SKILLS.md) | @skill decorator, 22 built-in packs (198+ skills) |
| [Admin Guide](ADMIN_GUIDE.md) | Admin panel pages and operations |
| [System Control Panel](SYSTEM_CONTROL.md) | Config editor, service health, launcher, NLM proxy, Git — port 5575 |
| [World System](WORLD_SYSTEM.md) | WorldSim, WorldState, NPCScheduler, NPCState, SceneDirector, autonomous NPC ticks |
| [Living World](LIVING_WORLD.md) | WorldSim + PlayerState + EventCascade + neon_city_events — economy ticks, faction system |
| [Neon HUD](NEON_HUD.md) | Universal Neon HUD — PlayerState API, Socket.IO, faction standings, integration guide |
| [The Grid](THE_GRID.md) | THE GRID scene (port 5569) — 4 zones, market vendors, travel map, GridSkills |
| [Training Flywheel](TRAINING_FLYWHEEL.md) | RouterDataCollector, RouterV3Client, Alpaca export, automated weekly retrain |
| [Player Identity](PLAYER_IDENTITY.md) | PlayerProfile, NPC relationships (−100..+100), RelationshipContextInterceptor, admin PROFILE tab |
| [Economy Guide](ECONOMY_GUIDE.md) | EconomyManager, cross-scene credits, betting, consequences |
| [Arena Guide](ARENA_GUIDE.md) | THE COLOSSEUM — card game mechanics, betting, NLM commentary |
| [Content Guide](CONTENT_GUIDE.md) | ContentEngine, ContentGate, adult profiles, NLM seeding |

## APIs & Integration

| Doc | Description |
|-----|-------------|
| [API Reference](API.md) | REST endpoints, Socket.IO events, all scenes |
| [TTS](TTS.md) | Qwen3-TTS server, voice design, streaming |
| [NotebookLM & Nexus](NOTEBOOKLM.md) | NotebookLM integration via Nexus dual-backend |
| [NotebookLM HAR SDK](NOTEBOOKLM_HAR_SDK.md) | Batchexecute protocol, RPC endpoints, HAR extraction script |
| [NotebookLM SDK v3.0](NOTEBOOKLM_SDK.md) | Full 21-RPC catalogue, rate limiter, complete :8800 proxy API reference, source schema |
| [NotebookLM Protocol](NOTEBOOKLM_PROTOCOL.md) | Deep dive — batchexecute wire protocol, auth, all 21 RPCs with examples, discovery methodology, notebook lifecycle |
| [NotebookLM Journey](NOTEBOOKLM_JOURNEY.md) | Sprint log — NLM integration from HAR capture to Node bridge hybrid |
| [Nexus Integration](NEXUS_INTEGRATION.md) | NexusClient, 16 skills, namespaces, memory, distillers, training, workflows |

## External Systems

| Doc | Description |
|-----|-------------|
| [Nexus Architecture](../../Nexus/docs/ARCHITECTURE.md) | Knowledge Management System design |
| [Nexus README](../../Nexus/README.md) | Nexus quick start, API endpoints, MCP tools |

## Observability

| Doc | Description |
|-----|-------------|
| [Logging](LOGGING.md) | CosyLogger ring buffer, SystemMonitor, structured logging patterns |
| [KPI](KPI.md) | `@timed` decorator, LLM KPIs, benchmarking dashboard |
| [System Audit](SYSTEM_AUDIT.md) | v0.75 system audit — grade A++, Universal Neon HUD, THE GRID, 15 scenes, 7,500+ tests |

## Training & Testing

| Doc | Description |
|-----|-------------|
| [Training System](TRAINING_SYSTEM.md) | v0.78b Data Flywheel — DataCollector, Model Zoo (9 types), AutoTrain, scheduler tasks, admin dashboard |
| [Coder Model](CODER_MODEL.md) | Local coder model — Llama 3.2-3B + LoRA, 10 data strategies, 8 coder skills, benchmark promotion |
| [Fine-Tuning Guide](FINETUNING_GUIDE.md) | End-to-end: datasets → MicroDatasetManager → FinetuneOrchestrator → ModelRegistry → promote |
| [Training](TRAINING.md) | Gemma 270M fine-tuning pipeline, datasets, Colab |
| [Training Flywheel](TRAINING_FLYWHEEL.md) | RouterDataCollector, RouterV3Client, Alpaca export, automated weekly retrain |
| [Testing](TESTING.md) | Test commands, fixtures, writing tests (6,921 tests, ~190 files) |

## Development

| Doc | Description |
|-----|-------------|
| [Contributing](CONTRIBUTING.md) | Scene creation, skill writing, interceptors, tests |
| [Agent Onboarding](AGENT_ONBOARDING.md) | How to onboard new Copilot/local agents to the project |
| [Local Agent Guide](LOCAL_AGENT_GUIDE.md) | Running local LLM agents as sub-agents, task delegation |
| [Changelog](../CHANGELOG.md) | Sprint history and changes |

## Internal (Development Logs)

| Doc | Description |
|-----|-------------|
| [Agent Revelations](internal/AGENT_REVELATIONS.md) | Sprint implementation logs |
| [Project CozyDreamz](internal/Project-CozyDreamz.md) | Original project design document |
