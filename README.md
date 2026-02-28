# CosySim

> v0.60.1 — Multi-scene AI simulation framework

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 4827](https://img.shields.io/badge/tests-4%2C827%20passing-brightgreen.svg)]()

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

**Simulation Engine**
- 18 scenes (8 game + 10 utility/support) with independent agents, state, and UI
- Bedroom scene refactored into 4 mixins (combat, dialog, inventory, social)
- Cross-scene agent state persistence (reputation, relationships, achievements)
- Character system with traits, emotions (0–100), relationships, speech patterns

**MCP Framework**
- 195 skills across 21 packs via `@skill` decorator
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
- 4,827 tests, 0 failures across 176 files
- 18 Copilot custom agents, 9 instruction files
- Config hardening — all 18 scenes in production.yaml
- Central CORS and health routes on all scenes

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
├── tests/               # pytest suite (176 files, 4,827 tests)
├── docs/                # Documentation (INDEX.md entry point)
├── training/            # Fine-tuning pipelines and data
├── main.py              # Application entry point
└── launcher.py          # Scene launcher CLI
```

## Service Ports

| Service | Port | Description |
|---------|------|-------------|
| LMStudio | 1234 | LLM inference (v1 API) |
| Phone | 5555 | Messaging app with mood engine |
| Bedroom | 5556 | Multi-agent spatial environment |
| Lounge | 5557 | Social scene with ambient characters |
| Tavern | 5558 | Fantasy tavern with NPC patrons |
| Casino | 5559 | Blackjack, poker, slots |
| Gallery | 5560 | Art evaluation and image generation |
| Warzone | 5561 | Turn-based tactical combat |
| Realm | 5562 | Director-guided LitRPG |
| NeonCity | 5563 | Cyberpunk strategy board game |
| Coders | 5564 | AI coding sandbox |
| Heist | 5565 | Cooperative multi-agent heist |
| Command Center | 5566 | System monitoring dashboard |
| Games | 5567 | Multi-game arcade |
| Nexus Panel | 5570 | Nexus control interface |
| Hub | 8500 | Landing page and scene launcher |
| Dashboard | 8501 | System metrics |
| Admin | 8502 | Diagnostic center with GOD mode |
| Assets | 8503 | Asset generator |
| TTS | 8600 | Qwen3-TTS voice generation |
| Web Bridge | 8601 | Socket.IO real-time bridge |
| Nexus API | 8700 | Knowledge management REST API |
| ComfyUI | 8188 | Image/video generation |

## Testing

```bash
# Full suite — 4,827 tests
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
