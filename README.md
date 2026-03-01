# CosySim

> v0.68b — Multi-scene AI simulation framework

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 6679](https://img.shields.io/badge/tests-6%2C679%20passing-brightgreen.svg)]()

## Overview

CosySim is a local-first AI simulation framework that orchestrates virtual agents across 18 interactive scenes. Each scene is a self-contained web application with its own agents, state machine, game logic, and skill pack — from a messaging app with mood tracking to a LitRPG with dual-agent orchestration, a cyberpunk board game, and an AI coding sandbox. Everything runs locally against LMStudio on an NVIDIA GPU.

The core of CosySim is its **Model Context Protocol (MCP) pipeline**. Agents call 188 skills during inference for memory retrieval, media generation, game mechanics, and state mutation. A 22-interceptor governance pipeline wraps every LLM call, injecting context, enforcing personality constraints, syncing state, and shaping responses. The **Nexus Knowledge System** provides central knowledge management with an NLM intelligence layer, FTS5 search, prompt versioning, and Q&A distillation.

CosySim is a meta-system — a playground for designing, testing, and evolving AI agent interactions. Router training data is captured automatically during inference for fine-tuning a 270M routing model. The framework is built for builders who want to experiment with multi-agent orchestration and tool-augmented LLMs without cloud dependencies.

## Architecture

```
User / Browser
      │
      ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  18 Scenes   │───▶│  160+ Skills │───▶│ MCP Pipeline │
│  Flask/      │    │  @skill deco │    │ 25 intercept │
│  Streamlit   │    │  25+ packs   │    │ governance   │
└──────┬───────┘    └──────────────┘    └──────┬───────┘
       │                                       │
       ▼                                       ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Engine     │───▶│  LMStudio    │    │  Nexus KMS   │
│  agents/mcp/ │    │  v1 API      │    │  NLM + FTS5  │
│  scenes/     │    │  :1234       │    │  :8700       │
└──────────────┘    └──────────────┘    └──────────────┘
       │
       ▼
┌──────────────┐    ┌──────────────┐
│  Qwen3 TTS   │    │  ComfyUI     │
│  :8600       │    │  :8188       │
└──────────────┘    └──────────────┘
```

## Features

**Dark Renaissance** (v0.68)
- 13 new engine modules: EventBus (cross-scene pub/sub), EconomyManager (credits), ContentGate (adult content), ContentEngine (Nexus-backed pools), CharacterMemory, ReputationManager, SceneDirector, ConsequenceStore, InvestigationBoard, SceneArtManager (ComfyUI), WorldState (game clock + NPC schedules), WorldSim (living world daemon), ArenaEngine (tactical card game)
- New scene: Arena — THE COLOSSEUM (port 5561): card game, agent betting, NLM commentary, BenchHUD
- Black glass design system with Three.js 3D particles (12 presets, 10k particles at 60fps)
- Universal chrome: navbar_v2, admin_overlay (8-tab hacker loft), Aria floating widget
- VoiceManager JS: Piper/Orpheus/Qwen3 backends, STT, localStorage persistence
- ContentIntensityInterceptor: adult content profiles 0–3 per category
- 14 scene revamps with new display names, scene accent system, all new engine modules wired
- BenchHUD on every scene: live latency, model name, Nexus tier, token count
- 6,679 tests passing

**Simulation Engine**
- 18 scenes (8 game + 10 utility/support) with independent agents, state, and UI
- Bedroom scene refactored into 4 mixins (combat, dialog, inventory, social)
- Cross-scene agent state persistence (reputation, relationships, achievements)
- Character system with traits, emotions (0–100), relationships, speech patterns

**MCP Framework**
- 195 skills across 21 packs via `@skill` decorator (206 with profile pack)
- 214 tools exposed via CosySim MCP server (106 main + 108 devtools)
- 22-interceptor governance pipeline (10 active, pre/post inference)
- `AgentGovernor` + `InterceptorPipeline` for personality enforcement

**LMStudio Integration**
- v1 API with stateful conversations and `response_id` threading
- SSE streaming with inline tag extraction (`[MOOD]`, `[IMAGE]`, `[ACTION]`)
- InferenceOrchestrator with multi-model routing (big/small/router/draft)
- 6 ResourceManager strategies, JIT model loading with TTL eviction
- Automatic router training data capture for 270M router fine-tuning

**Nexus Knowledge System**
- FTS5 search, NLM intelligence layer (4-tier: cache → FTS → synthesis → deep research)
- Prompt versioning, Q&A distillation, YouTube transcript ingestion
- NLM v2.1: 18 catalogued RPCs, Configure Chat API, source management, multi-question batching
- NLM proxy auto-start with CDP cookie capture, bl/f.sid management
- HAR ingestion background processing (large files, no timeout)
- NLM deep storage (3-tier notebook archival with HAR extraction)
- 10 NLM forge skills, NLM CLI (16 commands), Knowledge Forge
- Rules engine, session tracking, namespace separation
- REST API (:8700), dashboard (:5570)

**Connected System** (v0.59b)
- Phone assistant with 4-tier cascade routing (Aria → Nexus → AnythingLLM → static)
- Home Assistant integration (15 MCP skills, safety governance)
- AnythingLLM integration (multi-instance, bidirectional Nexus sync)
- System dashboard (overview, agents, scheduler, chat)
- System Assistant Aria with cosysim-navbar floating navigation

**DevOps**
- 6,679 tests, 0 failures across 186 files
- 18 Copilot custom agents, 9 instruction files
- Config hardening — all 18 scenes in production.yaml
- Central CORS and health routes on all scenes

**Training Pipeline** (v0.64–v0.65)
- NLM teacher pipeline: Gemini 3.0 → per-model-type JSONL datasets
- Unsloth QLoRA fine-tuning orchestrator (subprocess-based, progress tracking)
- Model registry with auto-promote on benchmark improvement
- Benchmark runner: accuracy/F1/exact-match with rule-based baseline
- Fine-tuned router integrates into cache pipeline Stage F (local model first, NLM fallback)
- 28 scheduler builtin tasks (teacher-dataset-gen, finetune-if-ready, model-benchmark, backup-databases, conversation-analyze)
- 18 new MCP tools for training pipeline control; smoke test (training/smoke_test.py)

**Profile System** (v0.65)
- ConversationAnalyzer — 3-tier extraction (NLM → LM → heuristic), extracts facts/preferences/tech bg/action items
- UserProfileStore — persists to data/user_profile.json + syncs to Nexus (category: copilot)
- BackupManager — gzip-compressed SQLite backups, full/incremental, retention pruning, manifest
- 11 profile MCP skills: analyze_conversation, user_profile_get/set/update, backup_run/list/restore
- conversation-analyze scheduler task (#28) — daily analysis of recent Copilot session turns

**Intelligence Hub** (v0.64)
- Unified glassmorphism admin panel at :5580
- Sections: Nexus Explorer, NLM Lab, Fine-tune Lab, Scheduler, Conversation Analyzer, User Profile, Backup Manager
- TTS config + voice selection, VTT config, assistant chat panel
- Glassmorphism CSS with neon accent design

## Quick Start

**Prerequisites:** Python 3.10+, Windows 11, NVIDIA GPU (CUDA), LMStudio running on localhost:1234.

```bash
# Install
pip install -r requirements.txt && npm install

# Run tests
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Launch a scene
python launcher.py --mode bedroom    # http://localhost:5556

# Launch the hub
python launcher.py                   # http://localhost:8500

# All services (Windows)
.\start_servers.ps1
```

## Project Structure

```
CosySim/
├── engine/              # Core framework
│   ├── agents/          # CharacterAgent, VirtualAgent, InterceptorPipeline
│   ├── mcp/             # MCPFramework, DialogSystem, Governor, MCP Server
│   ├── skills/          # @skill decorator, registry, 21 builtin packs
│   ├── lmstudio/        # LMS client, orchestrator, model manager, router
│   ├── nexus/           # Nexus KMS client, NLM engine, CLI tools
│   ├── scenes/          # BaseScene, SceneManager, SceneRegistry
│   ├── tts/             # Qwen3 TTS server
│   ├── services/        # Activity bus, resilience, housekeeping
│   └── config.py        # ConfigManager singleton
├── content/
│   ├── scenes/          # 18 scene implementations
│   └── simulation/      # Database, character system, services
├── config/              # YAML/JSON config (default, dev, prod, voices, skills)
├── tests/               # pytest suite (186 files, 5,582 tests)
├── docs/                # Documentation (INDEX.md entry point)
├── training/            # Fine-tuning pipelines and data
├── main.py              # Application entry point
└── launcher.py          # Scene launcher CLI
```

## Service Ports

| Service | Port | Description |
|---------|------|-------------|
| LMStudio | 1234 | LLM inference (v1 API) |
| Phone — SIGNAL | 5555 | Messaging app with mood engine |
| Bedroom — THE PENTHOUSE | 5556 | Multi-agent spatial environment |
| Lounge — THE VELVET PIT | 5557 | Social scene with ambient characters |
| Tavern — THE RUSTY ANCHOR | 5558 | Fantasy tavern with NPC patrons |
| Casino — CLUB NOIR | 5559 | Blackjack, poker, slots |
| Gallery — THE OBSCURA | 5560 | Art evaluation and image generation |
| Arena — THE COLOSSEUM | 5561 | Tactical card game, agent betting |
| Realm — THE SHATTERED THRONE | 5562 | Director-guided LitRPG |
| NeonCity — NEON CITY | 5563 | Cyberpunk strategy board game |
| Coders — THE LAB | 5564 | AI coding sandbox |
| Heist — THE SCORE | 5565 | Cooperative multi-agent heist |
| Command Center | 5566 | System monitoring dashboard |
| Games — THE ARCADE | 5567 | Multi-game arcade |
| Intel Hub — THE BRIEFING ROOM | 5580 | Training, NLM lab, fine-tune, scheduler, profile, backups |
| Nexus Panel | 5570 | Nexus control interface |
| Hub — THE TERMINAL | 8500 | Landing page and scene launcher |
| Dashboard | 8501 | System metrics |
| Admin | 8502 | Diagnostic center with GOD mode |
| Assets | 8503 | Asset generator |
| TTS | 8600 | Qwen3-TTS voice generation |
| Web Bridge | 8601 | Socket.IO real-time bridge |
| Nexus API | 8700 | Knowledge management REST API |
| ComfyUI | 8188 | Image/video generation |

## Testing

```bash
# Full suite — 6,679 tests
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Single file
python -m pytest tests/test_bedroom_game.py -v

# By marker
python -m pytest tests/ -m "not slow"
```

## Documentation

Full documentation at [docs/INDEX.md](docs/INDEX.md) — covers architecture, API, MCP framework, scenes, skills, LMStudio, TTS, Nexus, configuration, testing, training, and admin.

- [Changelog](CHANGELOG.md) · [Roadmap](ROADMAP.md)

## License

MIT — see [LICENSE](LICENSE).
