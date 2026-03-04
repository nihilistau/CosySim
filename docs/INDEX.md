# CosySim Documentation Index

> All project documentation in one place. v0.84b — 8,771 tests, 214 MCP tools, 25+ skill packs, 16 scenes.

## Quick Facts — v0.84b

| Metric | Value |
|--------|-------|
| Version | **0.84b** (2026) — "THE HINDSIGHT LAYER" |
| Tests passing | **8,771** across ~220 files |
| MCP tools | **214** (in 43 domain files) |
| Skill packs | **25+ packs · 220+ skills** |
| Game scenes | **10** (phone, bedroom, lounge, tavern, casino, gallery, arena, realm, neoncity, grid) |
| Utility scenes | **6** (coders, heist, command, games, asset_studio, intel_hub) |
| Scheduler tasks | **44** builtin autonomous tasks |
| Engine modules (v0.68+) | **15** new living-world modules |
| Workflow variants | **15** (image + Wan 2.2 video) |

### Scene Ports (All 16)

| Scene | Display Name | Port |
|-------|-------------|------|
| phone | SIGNAL | 5555 |
| bedroom | THE PENTHOUSE | 5556 |
| lounge | THE VELVET PIT | 5557 |
| tavern | THE RUSTY ANCHOR | 5558 |
| casino | CLUB NOIR | 5559 |
| gallery | THE OBSCURA | 5560 |
| arena | THE COLOSSEUM | 5561 |
| realm | THE SHATTERED THRONE | 5562 |
| neoncity | NEON CITY | 5563 |
| coders | THE LAB | 5564 |
| heist | THE SCORE | 5565 |
| command | Command Center | 5566 |
| games | THE ARCADE | 5567 |
| asset_studio | ASSET STUDIO | 5568 |
| grid | THE GRID | 5569 |
| intel_hub | THE BRIEFING ROOM | 5580 |

### v0.68 Engine Modules

`EventBus` · `EconomyManager` · `ContentGate` · `ContentEngine` · `CharacterMemory` ·
`ReputationManager` · `SceneDirector` · `ConsequenceStore` · `InvestigationBoard` ·
`SceneArtManager` · `WorldState` · `WorldSim` · `ArenaEngine`

### v0.73 New Modules

`EventCascade` · `NewsPipeline` · `RSSFetcher` · `DedupFilter` · `TuningEngine`

### v0.75 New Modules

`PlayerState` · `NeonCityEvents` · `WorldSkills` · `GridScene` · `GridSkills`

### v0.81b New Modules

`InventoryManager` · `CrewManager` · `RelationshipTypes` · `HUDv2` · `WorldAnnouncer`

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
| [Interceptors](INTERCEPTORS.md) | Interceptor pipeline — all 26 hooks, priorities, auto-registry (`@register_interceptor`) |
| [MCP Framework](MCP_FRAMEWORK.md) | Tools, `@mcp_tool` decorator, governance, state, dialog, rules, skills |
| [Project Hindsight](PROJECT_HINDSIGHT.md) | v0.83b → v0.84b architectural refactor — migration guide, before/after, 9 phases |
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
| [Scenes Reference](SCENES.md) | All 16 scenes — mechanics, APIs, rules |
| [Skills](SKILLS.md) | @skill decorator, 25+ built-in packs (220+ skills) |
| [Admin Guide](ADMIN_GUIDE.md) | Admin panel pages and operations |
| [System Control Panel](SYSTEM_CONTROL.md) | Config editor, service health, launcher, NLM proxy, Git — port 5575 |
| [World System](WORLD_SYSTEM.md) | WorldSim, WorldState, NPCScheduler, NPCState, SceneDirector, autonomous NPC ticks |
| [Living World](LIVING_WORLD.md) | WorldSim + PlayerState + EventCascade + neon_city_events — economy ticks, faction system |
| [Neon HUD](NEON_HUD.md) | Universal Neon HUD v2 — glass slide panels, phone overlay, world announcer, inventory/crew |
| [The Grid](THE_GRID.md) | THE GRID scene (port 5569) — 4 zones, market vendors, travel map, GridSkills |
| [Player Identity](PLAYER_IDENTITY.md) | PlayerProfile, NPC relationships, RelationshipTypes (12 types), crew tags |
| [Economy Guide](ECONOMY_GUIDE.md) | EconomyManager, cross-scene credits, betting, consequences |
| [Arena Guide](ARENA_GUIDE.md) | THE COLOSSEUM — card game mechanics, betting, NLM commentary |
| [Content Guide](CONTENT_GUIDE.md) | ContentEngine, ContentGate, adult profiles, NLM seeding |
| [World System](WORLD_SYSTEM.md) | InventoryManager (25 items, 14 slots), CrewManager (9 roles), PlayerState vitals |

## APIs & Integration

| Doc | Description |
|-----|-------------|
| [API Reference](API.md) | REST endpoints, Socket.IO events, all scenes (incl. /api/inventory, /api/crew, /api/announcer) |
| [TTS](TTS.md) | Qwen3-TTS server, voice design, streaming |
| [NotebookLM & Nexus](NOTEBOOKLM.md) | NotebookLM integration via Nexus dual-backend |
| [NotebookLM SDK v3.0](NOTEBOOKLM_SDK.md) | Full 21-RPC catalogue, rate limiter, complete :8800 proxy API reference, source schema |
| [NLM Reverse Engineering Journey](NLM_JOURNEY.md) | How we unlocked NLM — V8 heap mining, 61 methods, WebRTC discovery |
| [NLM API Reference](NLM_API_REFERENCE.md) | Complete batchexecute protocol — 24 rpcids decoded, request/response schemas |
| [NLM Capabilities](NLM_CAPABILITIES.md) | What we can do: full CRUD, source discovery, Drive export, multi-model, sharing |
| [NLM SDK Design](NLM_SDK_DESIGN.md) | NLMDirectClient architecture, all methods, error handling, distillation patterns |
| [Nexus Integration](NEXUS_INTEGRATION.md) | NexusClient, 25+ skills, namespaces, memory, distillers, training, workflows |

## External Systems

| Doc | Description |
|-----|-------------|
| [Nexus Architecture](../../Nexus/docs/ARCHITECTURE.md) | Knowledge Management System design |
| [Nexus README](../../Nexus/README.md) | Nexus quick start, API endpoints, MCP tools |

## Observability

| Doc | Description |
|-----|-------------|
| [Logging](LOGGING.md) | CosyLogger ring buffer, SystemMonitor, structured logging patterns |
| [System Audit](SYSTEM_AUDIT.md) | v0.81b system audit — grade A++, inventory/crew, HUD v2, 16 scenes, 7,800+ tests |

## Training & Testing

| Doc | Description |
|-----|-------------|
| [Training System](TRAINING_SYSTEM.md) | v0.81b Data Flywheel — DataCollector, Model Zoo (14 types), AutoTrain, scheduler tasks, admin dashboard |
| [Coder Model](CODER_MODEL.md) | Local coder model — Llama 3.2-3B + LoRA, 10 data strategies, 8 coder skills, benchmark promotion |
| [Fine-Tuning Guide](FINETUNING_GUIDE.md) | End-to-end: datasets → MicroDatasetManager → FinetuneOrchestrator → ModelRegistry → promote |
| [Testing](TESTING.md) | Test commands, fixtures, writing tests (7,800+ tests, ~220 files) |

## Development

| Doc | Description |
|-----|-------------|
| [Contributing](CONTRIBUTING.md) | Scene creation, skill writing, interceptors, tests |
| [Agent Onboarding](AGENT_ONBOARDING.md) | How to onboard new Copilot/local agents to the project |
| [Local Agent Guide](LOCAL_AGENT_GUIDE.md) | Running local LLM agents as sub-agents, task delegation |
| [Changelog](../CHANGELOG.md) | Sprint history and changes |
