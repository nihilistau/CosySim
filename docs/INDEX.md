# CosySim Documentation Index

> v1.56.0 — Nexus v1.5.0, Agent Registry, KnowledgePipeline, Three-Pillar Architecture + ARGUS Recon Framework, 1,040+ Skills.

## Quick Reference

| Metric | Value |
|--------|-------|
| Version | v1.56.0 [2026-03-26] |
| Targets | 35 (18 game + 11 service + 6 creation) |
| Skills | ~1,040 across 99 packs via @skill decorator |
| Interceptors | 36 pipeline hooks in the agent governance layer |
| MCP Tools | 43 domain modules |
| ARGUS | 21 toolkit functions, 13 recon techniques |
| Tests | 417 test files (smart runner: ~53s smoke) |
| Pillars | Game (NeonCity) / Service / Creation |

### Three-Pillar Architecture

All targets defined in `engine/control_plane_registry.py`:

| Pillar | Count | Key Targets |
|--------|-------|-------------|
| Game | 15 | phone, penthouse, lounge, tavern, casino, gallery, arena, realm, neoncity, coders, heist, games, grid, lab_break, oracle |
| Service | 11 | nexus_kms, hub, nexus_panel, dashboard, admin, tts, bridge, nlm_proxy, system_control, command_center, intel_hub |
| Creation | 7 | canvas, canvas_api, assets, creator, asset_studio, creation_kit, neonos |

### Key Ports

| Port | Service | Managed |
|------|---------|---------|
| 1234 | LMStudio (local inference) | External |
| 5555–5572 | Game scenes | Auto |
| 5570–5580 | Service scenes | Auto |
| 5590–5595 | Creation tools | Auto |
| 8500 | Hub (scene launcher) | Auto |
| 8501–8504 | Streamlit apps (dashboard, admin, assets, creator) | Auto |
| 8600 | TTS Server | Launcher |
| 8700 | Nexus KMS (auto-start, priority 0) | Auto |
| 5800 | Model Proxy (OpenAI-compat, FastAPI) | Manual |
| 5593 | Advanced Assistant (chat UI + proxy) | Manual |
| 8800 | NLM Proxy | Auto |

---

## Architecture and Design

| Doc | Description |
|-----|-------------|
| [Architecture](ARCHITECTURE.md) | System design, layers, data flow, three-pillar targets, singletons |
| [MCP Framework](MCP_FRAMEWORK.md) | Skill dispatch, governance, state coordination, dialog system |
| [Interceptors](INTERCEPTORS.md) | 36 pre/post-call hooks, priorities, auto-registry, scene filtering |
| [Configuration](CONFIGURATION.md) | YAML config hierarchy, get_config() pattern, environment overrides |
| [Decisions](DECISIONS.md) | 14 architecture decision records with rationale |

## Scenes and Content

| Doc | Description |
|-----|-------------|
| [Scenes](SCENES.md) | All 32 targets, mechanics, APIs, routes, Socket.IO events |
| [Skills](SKILLS.md) | @skill decorator, 95 packs, runtime registry, governance filtering |
| [Game Systems](GAME_SYSTEMS.md) | WorldSim, factions, NPCs, missions, inventory, cyberspace |
| [Character System](CHARACTER_SYSTEM.md) | Profiles, personality, stats, neurochemistry, relationships |
| [Economy Guide](ECONOMY_GUIDE.md) | EconomyManager, cross-scene credits, markets, consequences |
| [Arena Guide](ARENA_GUIDE.md) | THE COLOSSEUM, card game mechanics, betting |
| [The Grid](THE_GRID.md) | THE GRID, underground marketplace, 4 zones |
| [Neon HUD](NEON_HUD.md) | Universal HUD v2, glass panels, phone overlay, announcer |
| [OpenRoom Features](OPENROOM_FEATURES.md) | 6 OpenRoom-inspired features: memory, danmaku, NeonOS, virtual FS, narrative, character creator |

## Knowledge and Integration

| Doc | Description |
|-----|-------------|
| [Nexus](NEXUS.md) | Nexus KMS v1.5.0, agent registry, KnowledgePipeline, 6-tier query router, NLM integration, training flywheel |
| [Nexus System](NEXUS_SYSTEM.md) | Nexus internals, self-maintenance, governance, agent registry (planned) |
| [Nexus API Reference](NEXUS_API_REFERENCE.md) | Complete Nexus REST API endpoint catalog (planned) |
| [LMStudio](LMSTUDIO.md) | InferenceOrchestrator, ServerController, LMLink federation, SSE streaming |
| [ARGUS](ARGUS.md) | Browser automation, CDP, API surface discovery, RPC registry |
| [ARGUS Methodology](ARGUS_METHODOLOGY.md) | 13 reusable recon techniques: heap mining, bundle decompilation, flag injection, CDP scripting, agent extraction |
| [ARGUS Discovery Journal](ARGUS_DISCOVERY_JOURNAL.md) | Narrative of reverse-engineering Sesame AI + OpenRoom.ai — timeline, techniques born, insights |
| [ARGUS: Sesame AI Report](ARGUS_SESAME_REPORT.md) | Complete intelligence: 53 API methods, WebRTC, Statsig, RLHF pipeline, security assessment |
| [ARGUS: OpenRoom Report](ARGUS_OPENROOM_REPORT.md) | Complete intelligence: 5-brand mapping, multi-agent architecture, virtual OS, protobuf protocol |

## Infrastructure

| Doc | Description |
|-----|-------------|
| [Operations](OPERATIONS.md) | Launcher, TUI, ports, logging, monitoring, scheduler, admin panels |
| [TTS](TTS.md) | Qwen3-TTS server, voice design, streaming audio |
| [Asset Studio](ASSET_STUDIO.md) | ComfyUI integration, workflows, tuning engine |
| [Training](TRAINING.md) | Data flywheel, DataCollector, AutoTrain, LoRA fine-tuning, benchmarks |

## Tools and SDKs

| Doc | Description |
|-----|-------------|
| [Advanced Assistant](../apps/assistant/README.md) | Standalone chat UI + OpenAI proxy — 80+ models, branching, comparison, playground, caching, auth |
| [Exploration Journal](EXPLORATION_JOURNAL.md) | Narrative of reverse-engineering Google APIs — batchexecute, CDP, ARGUS, Chrome MCP |
| [Integrations SDK](INTEGRATIONS_SDK.md) | Complete API reference — LMStudio, NotebookLM (56 methods), Copilot, Colab, Sheets |
| [NotebookLM SDK Design](NLM_SDK_DESIGN.md) | SDK internals — 42 rpcids, 25 gRPC methods, payload formats, gotchas |
| [NLM API Reference](NLM_API_REFERENCE.md) | Auto-generated ARGUS API catalog for NotebookLM |
| [Gemini API Reference](GEMINI_API_REFERENCE.md) | Auto-generated ARGUS API catalog for Gemini |
| [AI Studio API Reference](AISTUDIO_API_REFERENCE.md) | Auto-generated ARGUS API catalog for AI Studio |

## Development

| Doc | Description |
|-----|-------------|
| [Contributing](CONTRIBUTING.md) | Scene creation, skill writing, code conventions, testing |
| [Testing](TESTING.md) | Smart test system, fixtures, pytest conventions |
| [API Reference](API.md) | REST endpoints, Socket.IO events, all scene and service routes |

## Project History

Archived narrative docs are in `docs/archive/` — see [archive/README.md](archive/README.md):
- PROJECT_JOURNAL.md — Sprint history from v0.51b through v0.84b
- PROJECT_JOURNAL_NLM.md — NotebookLM development journal
- NLM_JOURNEY.md — Reverse engineering story
- PROJECT_HINDSIGHT.md — v0.83b refactor retrospective
- SYSTEM_AUDIT.md — Historical system audits
- GAP_ANALYSIS.md — v1.26 gap analysis
- AGENT_ONBOARDING.md — Copilot workflow (superseded by .github/agents/)
- animation_creation.md — Penthouse animation guide
