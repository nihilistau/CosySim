# CosySim Documentation Index

> Central navigation for all CosySim documentation. 53 docs covering architecture,
> 20 scenes, game systems, the Nexus knowledge backbone, NotebookLM research
> integration, LMStudio local inference, and the full Google ecosystem SDK.

## Quick Reference — v1.02b

| Metric | Value |
|--------|-------|
| Version | **1.02b** "NEONCITY 2: THE LIVING CITY" (2026) |
| Engine | **280+ Python files** across 12 subsystems |
| Tests | **10,720+ passed** / 345 test files |
| Scenes | **20 Flask** (11 game + 6 utility + 3 service) + 3 Streamlit apps |
| Skills | **38 packs · 373 skills** via `@skill` decorator |
| MCP tools | **42 modules** in `engine/mcp/tools/` |
| Game systems | neurochemistry · cyberspace · territory · market · factions · multiplayer · news |
| Scheduler | **55 autonomous tasks** (maintenance, distillation, training, benchmarks) |
| Interceptors | **30+ pre/post-call hooks** in the agent pipeline |
| NLM registry | **122 API entries** across 4 Google services (YAML-driven) |

### Scene Port Map

| Port | ID | Display Name | Type |
|------|----|-------------|------|
| 5555 | phone | SIGNAL | Game |
| 5556 | bedroom | THE PENTHOUSE | Game |
| 5557 | lounge | THE VELVET PIT | Game |
| 5558 | tavern | THE RUSTY ANCHOR | Game |
| 5559 | casino | CLUB NOIR | Game |
| 5560 | gallery | THE OBSCURA | Game |
| 5561 | arena | THE COLOSSEUM | Game |
| 5562 | realm | THE SHATTERED THRONE | Game |
| 5563 | neoncity | NEON CITY | Game |
| 5564 | coders | THE LAB | Utility |
| 5565 | heist | THE SCORE | Game |
| 5566 | command_center | COMMAND CENTER | Utility |
| 5567 | games | THE ARCADE | Utility |
| 5568 | asset_studio | ASSET STUDIO | Utility |
| 5569 | grid | THE GRID | Game |
| 5570 | nexus_panel | NEXUS PANEL | Service |
| 5571 | lab_break | THE LAB BREAK | Game |
| 5575 | system_control | SYSTEM CONTROL | Service |
| 5580 | intel_hub | THE BRIEFING ROOM | Utility |
| 8500 | hub | HUB | Service |

### Service Ports

| Port | Service |
|------|---------|
| 1234 | LMStudio (local inference) |
| 5590 | Nexus Canvas (React notebook UI) |
| 8500 | Hub (scene launcher + navigation) |
| 8700 | Nexus KMS (knowledge management API) |
| 8800 | NLM Proxy (NotebookLM batchexecute bridge) |
| 9222 | Chrome CDP (browser automation) |

### Engine Subsystem Map

| Subsystem | Files | Lines | Purpose |
|-----------|-------|-------|---------|
| `engine/nexus/` | 85 | 27,400 | Knowledge backbone, Copilot self-config, scheduling, Q&A, training flywheel |
| `engine/integrations/` | 25 | 19,700 | Google accounts, Colab, NLM direct client, Drive, compute routing |
| `engine/mcp/` | 23 | 15,700 | MCP framework, RPC servers, dialog, state, governance |
| `engine/lmstudio/` | 23 | 13,100 | Local inference, fine-tuning, model registry, ServerController, LMLink |
| `engine/skills/builtin/` | 46 | 11,500 | 278 `@skill` functions across 31 packs |
| `engine/agents/` | 17 | 9,200 | Agent framework, VirtualAgent, Governor, 30+ interceptors |
| `engine/scenes/` | 6 | 2,471 | BaseScene, SceneStateManager, scene lifecycle |
| `engine/services/` | 6 | 1,214 | EventBus, WorldAnnouncer, TTS |
| `engine/` (root) | 7 | 1,270 | Config, paths, port_registry, control_plane_registry |

---

## Getting Started

| Doc | Description |
|-----|-------------|
| [README](../README.md) | Project overview, quick start, architecture diagram, full scene catalog |
| [Deployment](DEPLOYMENT.md) | Service startup order, ports, health checks, PowerShell scripts |
| [Configuration](CONFIGURATION.md) | YAML config hierarchy, `get_config()` pattern, environment overrides |
| [Roadmap](../ROADMAP.md) | Version history from v0.51b through v0.91b and future plans |

## Architecture & Design

| Doc | Description |
|-----|-------------|
| [Architecture](ARCHITECTURE.md) | System design — 10 domains, layers, data flow, interceptor pipeline |
| [Game Systems](GAME_SYSTEMS.md) | NeonCity 2 game systems — neurochemistry, cyberspace, territory, market, factions, multiplayer, news |
| [MCP Framework](MCP_FRAMEWORK.md) | `@mcp_tool` decorator, governance, state coordination, dialog system, rules engine |
| [Interceptors](INTERCEPTORS.md) | 30+ pre/post-call hooks — priorities, auto-registry, scene-specific interceptors |
| [LMStudio](LMSTUDIO.md) | InferenceOrchestrator, ServerController, LMLink federation, TaskQueue, bearer auth |
| [Characters](CHARACTERS.md) | Personality, stats, buffs, tags, relationships, emotion model |
| [Character System](CHARACTER_SYSTEM.md) | CharacterMemory, ReputationManager, speech patterns, relationship tiers |
| [Project Hindsight](PROJECT_HINDSIGHT.md) | v0.83b → v0.84b refactor — `@mcp_tool`, Pydantic models, domain extraction |
| [Architecture Decisions](DECISIONS.md) | Key design decisions and rationale (ADRs) |

## Scenes & Content

| Doc | Description |
|-----|-------------|
| [Scenes Reference](SCENES.md) | All 20 scenes — mechanics, APIs, routes, Socket.IO events |
| [Skills](SKILLS.md) | `@skill` decorator, 31 builtin packs, runtime registry, MCP-facing metadata |
| [Asset Studio](ASSET_STUDIO.md) | ComfyUI integration — 15 workflow variants, tuning engine, benchmarking |
| [The Grid](THE_GRID.md) | THE GRID — 4 zones (Market, Station, Den, Broker), GridSkills |
| [Neon HUD](NEON_HUD.md) | Universal HUD v2 — glass slide panels, phone overlay, announcer, inventory |
| [Living World](LIVING_WORLD.md) | WorldSim + PlayerState + EventCascade + economy ticks + faction system |
| [World System](WORLD_SYSTEM.md) | WorldSim, WorldState, NPCScheduler, SceneDirector, InventoryManager, CrewManager |
| [Player Identity](PLAYER_IDENTITY.md) | PlayerProfile, NPC relationships, RelationshipTypes, crew tags |
| [News System](NEWS_SYSTEM.md) | RSS ingestion, NLM distillation, Nexus Q&A feeds, Intel Hub ticker |
| [Economy Guide](ECONOMY_GUIDE.md) | EconomyManager, cross-scene credits, betting, consequences |
| [Arena Guide](ARENA_GUIDE.md) | THE COLOSSEUM — card game mechanics, betting, NLM commentary |
| [Content Guide](CONTENT_GUIDE.md) | ContentEngine, ContentGate, adult profiles, seeding |
| [Admin Guide](ADMIN_GUIDE.md) | Admin panel pages and operations |
| [System Control Panel](SYSTEM_CONTROL.md) | Config editor, service health, launcher proxy, Git — port 5575 |

## Nexus Knowledge System

| Doc | Description |
|-----|-------------|
| [Nexus Integration](NEXUS_INTEGRATION.md) | NexusClient, smart query router, Q&A cache, training flywheel, research sessions |
| [Agent Onboarding](AGENT_ONBOARDING.md) | Copilot/local agent onboarding — Nexus-first workflow, session logging, self-config |

## NotebookLM & Google Research Layer

| Doc | Description |
|-----|-------------|
| [NotebookLM Overview](NOTEBOOKLM.md) | Browser-attached RPC architecture, CDP/HAR auth, dual-backend integration |
| [NotebookLM SDK](NOTEBOOKLM_SDK.md) | Full RPC catalogue, rate limiter, :8800 proxy API, source schema |
| [NLM SDK Design](NLM_SDK_DESIGN.md) | NLMDirectClient architecture, all methods, error handling, distillation |
| [NLM API Reference](NLM_API_REFERENCE.md) | batchexecute protocol — rpcid decoding, request/response schemas |
| [NLM Capabilities](NLM_CAPABILITIES.md) | Full CRUD, source discovery, Drive export, multi-model, sharing |
| [NLM Multimodal Workflows](NLM_MULTIMODAL_WORKFLOWS.md) | Audio overviews, video generation, data tables, multi-source notebooks |
| [NLM Journey](NLM_JOURNEY.md) | Reverse engineering story — V8 heap mining, 61 methods, WebRTC discovery |
| [AI Studio API Reference](AISTUDIO_API_REFERENCE.md) | 34 gRPC-Web methods for Google AI Studio |
| [Google Ecosystem SDK](GOOGLE_ECOSYSTEM_SDK.md) | Drive, Sheets, Colab, NLM — cookie auth, Artifact Bus, GPU/venv managers |
| [Google Apps Script](GOOGLE_APPS_SCRIPT.md) | GAS as webhook receiver, scheduled intelligence layer |

## ARGUS Browser Automation

| Doc | Description |
|-----|-------------|
| [ARGUS](ARGUS.md) | Browser automation system — Playwright + CDP, crawlers, decoders, discovery |

## APIs & Integration

| Doc | Description |
|-----|-------------|
| [API Reference](API.md) | REST endpoints, Socket.IO events — all scene and service routes |
| [TTS](TTS.md) | Qwen3-TTS server, voice design, streaming audio |

## Observability & Operations

| Doc | Description |
|-----|-------------|
| [Logging](LOGGING.md) | CosyLogger ring buffer, SystemMonitor, structured logging patterns |
| [System Audit](SYSTEM_AUDIT.md) | Historical system audits with grades, module counts, test results |

## Training & Fine-Tuning

| Doc | Description |
|-----|-------------|
| [Training System](TRAINING_SYSTEM.md) | Data flywheel — DataCollector, Model Zoo (14 types), AutoTrain, scheduler tasks |
| [Coder Model](CODER_MODEL.md) | Local coder model — Llama 3.2-3B + LoRA, 10 dataset strategies, benchmark promotion |
| [Fine-Tuning Guide](FINETUNING_GUIDE.md) | End-to-end: datasets → MicroDatasetManager → FinetuneOrchestrator → ModelRegistry |

## Development & Testing

| Doc | Description |
|-----|-------------|
| [Contributing](CONTRIBUTING.md) | Scene creation, skill writing, interceptors, testing conventions |
| [Testing](TESTING.md) | pytest commands, fixtures (`temp_db`, `event_chain`, `mock_config`), markers |
| [Local Agent Guide](LOCAL_AGENT_GUIDE.md) | Running local LLM agents, task delegation, LMSTaskBridge |

## Project History

| Doc | Description |
|-----|-------------|
| [Changelog](../CHANGELOG.md) | Sprint-by-sprint change history |
| [Project Journal](PROJECT_JOURNAL.md) | Narrative project history from v0.51b through v0.84b |
| [Project Journal — NLM](PROJECT_JOURNAL_NLM.md) | NotebookLM-focused development journal (3,356 lines) |
