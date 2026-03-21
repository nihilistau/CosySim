# CosySim Documentation Index

> v1.42 -- Three-Pillar Architecture, Smart Test System, Managed Nexus KMS.

## Quick Reference

| Metric | Value |
|--------|-------|
| Version | v1.42 Pillar Wiring and Hub Modernization |
| Scenes | 20 Flask (14 game + 11 service + 5 creation) |
| Skills | 178+ across 38 packs via @skill decorator |
| Interceptors | 26 pre/post-call hooks in the agent pipeline |
| Tests | ~15K across 400+ files (smart runner: ~53s smoke) |
| Scheduler | 86 autonomous tasks |
| Pillars | Game (NeonCity) / Service / Creation |

### Three-Pillar Architecture

All targets defined in `engine/control_plane_registry.py`:

| Pillar | Count | Targets |
|--------|-------|---------|
| Game | 14 | phone, penthouse, lounge, tavern, casino, gallery, arena, realm, neoncity, coders, heist, games, grid, lab_break |
| Service | 11 | nexus_kms, hub, nexus_panel, dashboard, admin, tts, bridge, nlm_proxy, system_control, command_center, intel_hub |
| Creation | 5 | canvas, canvas_api, assets, creator, asset_studio |

### Key Ports

| Port | Service | Managed |
|------|---------|---------|
| 1234 | LMStudio (local inference) | External |
| 5555-5571 | Game scenes | Auto |
| 5570-5580 | Service scenes | Auto |
| 5590-5595 | Creation tools | Auto |
| 8500 | Hub (scene launcher) | Auto |
| 8600 | TTS Server | Manual |
| 8700 | Nexus KMS (auto-start, priority 0) | Auto |
| 8800 | NLM Proxy | Auto |

---

## Architecture and Design

| Doc | Description |
|-----|-------------|
| [Architecture](ARCHITECTURE.md) | System design, layers, data flow, interceptor pipeline, singletons |
| [MCP Framework](MCP_FRAMEWORK.md) | Skill dispatch, governance, state coordination, dialog system |
| [Interceptors](INTERCEPTORS.md) | 26 pre/post-call hooks, priorities, auto-registry, scene filtering |
| [Configuration](CONFIGURATION.md) | YAML config hierarchy, get_config() pattern, environment overrides |
| [Decisions](DECISIONS.md) | Key architecture decisions and rationale |

## Deployment and Operations

| Doc | Description |
|-----|-------------|
| [Deployment](DEPLOYMENT.md) | Three-pillar architecture, startup, PM2, port registry, troubleshooting |
| [Operations](OPERATIONS.md) | Logging, scheduling, admin panel, system control, news pipeline, local agents |
| [Testing](TESTING.md) | Smart test system (--affected, --smoke-only, --since), fixtures, conventions |

## Scenes and Content

| Doc | Description |
|-----|-------------|
| [Scenes Reference](SCENES.md) | All 20 scenes, mechanics, APIs, routes, Socket.IO events |
| [Skills](SKILLS.md) | @skill decorator, 38 packs, runtime registry, MCP-facing metadata |
| [Game Systems](GAME_SYSTEMS.md) | WorldSim, economy, factions, NPCs, events, inventory |
| [Character System](CHARACTER_SYSTEM.md) | Profiles, personality, stats, relationships, speech patterns |
| [Economy Guide](ECONOMY_GUIDE.md) | EconomyManager, cross-scene credits, betting, consequences |
| [Arena Guide](ARENA_GUIDE.md) | THE COLOSSEUM, card game mechanics, betting, NLM commentary |
| [The Grid](THE_GRID.md) | THE GRID, 4 zones, GridSkills |
| [Content Guide](CONTENT_GUIDE.md) | ContentEngine, ContentGate, profiles, seeding |
| [Neon HUD](NEON_HUD.md) | Universal HUD v2, glass panels, phone overlay, announcer |
| [Asset Studio](ASSET_STUDIO.md) | ComfyUI integration, workflows, tuning engine |

## Knowledge and Integration

| Doc | Description |
|-----|-------------|
| [Nexus Integration](NEXUS_INTEGRATION.md) | NexusClient, smart query router, Q&A cache, training flywheel |
| [Agent Onboarding](AGENT_ONBOARDING.md) | Copilot/Claude Code onboarding, Nexus-first workflow, session logging |
| [NLM Reference](NLM_REFERENCE.md) | NotebookLM architecture, NLMDirectClient, RPC catalogue, proxy API |
| [NLM API Reference](NLM_API_REFERENCE.md) | batchexecute protocol, rpcid decoding, request/response schemas |
| [LMStudio](LMSTUDIO.md) | InferenceOrchestrator, ServerController, LMLink, bearer auth (v1 API) |
| [External APIs](EXTERNAL_APIS.md) | AI Studio, Gemini, Colab, Apps Script, Workspace, ARGUS API catalogue |

## Infrastructure

| Doc | Description |
|-----|-------------|
| [ARGUS](ARGUS.md) | Browser automation, Playwright + CDP, crawlers, decoders |
| [TTS](TTS.md) | Qwen3-TTS server, voice design, streaming audio |
| [Training](TRAINING.md) | Data flywheel, DataCollector, AutoTrain, LoRA fine-tuning, benchmarks |

## Development

| Doc | Description |
|-----|-------------|
| [Contributing](CONTRIBUTING.md) | Scene creation, skill writing, interceptors, testing conventions |
| [API Reference](API.md) | REST endpoints, Socket.IO events, all scene and service routes |

## Project History

Archived narrative docs are in `docs/archive/`:
- PROJECT_JOURNAL.md - Sprint history from v0.51b through v0.84b
- PROJECT_JOURNAL_NLM.md - NotebookLM development journal
- NLM_JOURNEY.md - Reverse engineering story
- PROJECT_HINDSIGHT.md - v0.83b refactor retrospective
- SYSTEM_AUDIT.md - Historical system audits
- GAP_ANALYSIS.md - v1.26 gap analysis (24 gaps)
