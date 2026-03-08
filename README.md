# CosySim

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![Version: 0.91b](https://img.shields.io/badge/version-0.91b-blueviolet.svg)]() [![Scenes: 20](https://img.shields.io/badge/scenes-20-6f42c1.svg)]() [![Tests: 9577](https://img.shields.io/badge/tests-9%2C577-brightgreen.svg)]() [![Skills: 278](https://img.shields.io/badge/skills-278-0a7f5a.svg)]()

> v0.91b — "THE EVOLUTION" — Local-first multi-scene AI simulation framework

## Overview

CosySim is a self-improving AI simulation framework where **20 interactive scenes** run on local Flask/Socket.IO servers, powered by **LMStudio** local inference, **Nexus** knowledge management, and **NotebookLM** research distillation. Agents inhabit scenes, learn from interactions, and feed data back into the training pipeline — a closed loop that gets smarter over time.

The framework is operated through a **TUI launcher** (`tui.py`), managed by **GitHub Copilot** with 19 specialized agents, and backed by **55 autonomous scheduler tasks** that handle maintenance, benchmarking, and knowledge curation.

## Runtime Snapshot

| Metric | Value |
|--------|-------|
| Version | **0.91b** — "THE EVOLUTION" |
| Tests | **9,577 passing** / 9,963 total |
| Scenes | **20** Flask scenes + 3 Streamlit apps |
| Services | **12** launcher-managed services |
| Skill packs | **31 packs / 278 skills** (`import engine.skills`) |
| MCP tools | **42** domain modules (`engine/mcp/tools/`) |
| Interceptors | **26** auto-registered pipeline hooks |
| Scheduler tasks | **55** autonomous recurring tasks |
| Ports | **35** canonical endpoints |
| Copilot agents | **19** specialized agent definitions |
| Instructions | **12** coding instruction files |

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser — Neon HUD v2 (glass panels · phone overlay · announcer)   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ Socket.IO / REST
┌────────────────────────────▼─────────────────────────────────────────┐
│                     20 Scenes (Flask / Socket.IO)                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │  phone  │ │ bedroom │ │ lounge  │ │ tavern  │ │ casino  │ ...  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │
│       └───────────┴───────────┴───────────┴───────────┘            │
└────────────────────┬──────────────────────┬──────────────────────────┘
                     │                      │
┌────────────────────▼───────┐  ┌───────────▼──────────────────────────┐
│  278 Skills (31 packs)     │  │  MCP Pipeline                        │
│  @skill decorator          │  │  26 interceptors · @mcp_tool         │
│  auto-registry             │◄►│  AgentGovernor · DialogSystem        │
│  cooldown · cost · prereqs │  │  StreamProcessor · state sync        │
└────────────────────┬───────┘  └───────────┬──────────────────────────┘
                     │                      │
┌────────────────────▼──────────────────────▼──────────────────────────┐
│                         Engine Layer                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │ LMStudio     │ │ Nexus KMS    │ │ World Sim    │ │ Training   │ │
│  │ ServerCtrl   │ │ QueryRouter  │ │ PlayerState  │ │ Flywheel   │ │
│  │ LMLink Fed   │ │ NLM Chain    │ │ EventCascade │ │ Benchmark  │ │
│  │ TaskQueue    │ │ Smart Q&A    │ │ Economy      │ │ DataCollect│ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────┘ │
└────────┬──────────────────┬───────────────────┬──────────────────────┘
         │                  │                   │
┌────────▼────────┐ ┌───────▼─────────┐ ┌───────▼──────────────────────┐
│ LMStudio :1234  │ │ Nexus KMS :8700 │ │ NotebookLM (CDP/ARGUS)      │
│ CUDA · LMLink   │ │ FTS5 · Q&A      │ │ Research · Distillation     │
│ Vision · Coding  │ │ Rules · Memory  │ │ 122 API entries · Pro tier  │
└─────────────────┘ └─────────────────┘ └──────────────────────────────┘
```

## Scenes

### Game Scenes

| Scene | Display Name | Port | Description |
|-------|-------------|------|-------------|
| `phone` | SIGNAL | 5555 | iOS-style messaging with autonomous NPC texting, voice/photo/video cards |
| `bedroom` | THE PENTHOUSE | 5556 | Multi-agent roleplay with emotional stats, outfit tracking, Director tools |
| `lounge` | THE VELVET PIT | 5557 | 1920s jazz speakeasy — full MCP framework showcase with 2 NPCs |
| `tavern` | THE RUSTY ANCHOR | 5558 | Reference implementation — all MCP features: 11 skills, quests, reputation |
| `casino` | CLUB NOIR | 5559 | Underground casino with poker, consequence chains, cross-scene bridge |
| `gallery` | THE OBSCURA | 5560 | Dark art gallery with ContentGate-gated exhibits, private viewings |
| `arena` | THE COLOSSEUM | 5561 | Combat simulation arena with dedicated skill pack |
| `realm` | THE SHATTERED THRONE | 5562 | Director-guided LitRPG with dual-agent orchestration, murder-mystery |
| `neoncity` | NEON CITY | 5563 | Multi-district living city — 6 factions, economy, reputation, Glitch Storm |
| `grid` | THE GRID | 5569 | Underground marketplace — 4 zones (Market, Station, Den, Broker) |
| `lab_break` | LAB BREAK | 5571 | 3D escape scenario — convince the observer to open the door |

### Utility Scenes

| Scene | Display Name | Port | Description |
|-------|-------------|------|-------------|
| `coders` | THE LAB | 5564 | AI agents write/review/test real Python with sandboxed execution |
| `heist` | THE SCORE | 5565 | Cooperative planning with phase gates and crew specialties |
| `command_center` | COMMAND CENTER | 5566 | War-room dashboard — system metrics, pipeline status, alerts |
| `games` | THE ARCADE | 5567 | Investigation board, 3D dice, AI GameMaster, leaderboard |
| `asset_studio` | ASSET STUDIO | 5568 | 9-tab asset generation hub (images, portraits, voice, video, SVG) |
| `intel_hub` | THE BRIEFING ROOM | 5580 | Intelligence center — Nexus explorer, Librarian chat, Copilot integration |

### Service Scenes

| Scene | Display Name | Port | Description |
|-------|-------------|------|-------------|
| `hub` | THE TERMINAL | 8500 | Main navigation hub connecting all scenes |
| `nexus_panel` | NEXUS PANEL | 5570 | Knowledge management dashboard with Librarian agent |
| `system_control` | SYSTEM CONTROL | 5575 | Live config editor, service health, real-time logs |

## Key Engine Systems

### Inference & Model Management
- **ServerController** — LMStudio model lifecycle, agent instance isolation via SDK, health monitoring
- **LMLinkManager** — Multi-instance federation routing (local + remote via Tailscale), 4 strategies, failover
- **TaskQueue** — Priority queue with model-affinity dispatch, 6 task types, 5 priority levels, metrics
- **InferenceOrchestrator** — v1 API, stateful `response_id` threading, SSE streaming

### Knowledge & Intelligence
- **Nexus KMS** — FTS5 + 4-tier query router (cache → FTS → NLM → LLM), auto-caching, Q&A distillation
- **NLM Chain Engine** — Multi-step notebook conversations, batch processing, action manifests
- **ARGUS** — Browser automation for API surface discovery, token harvesting, NotebookLM control
- **NLM RPC Registry** — 122 API entries across 4 Google services (NLM, Gemini, AI Studio, Colab)

### Agent Framework
- **MCPFramework** — State tree singleton, tool routing, `@skill` integration, governed tool calls
- **InterceptorPipeline** — 26 hooks (pre/post), auto-registry, personality enforcement, context injection
- **AgentGovernor** — Budget tracking, cooldown enforcement, prerequisite checking
- **DialogSystem** — Conversation threading, context windows, per-character memory
- **StreamProcessor** — Tag extraction: `[MOOD:x]`, `[IMAGE:prompt]`, `[ACTION:x]`, `[STAT:name±val]`

### World Simulation
- **WorldSim** — 90-second economy tick, 70+ event templates, EventCascade 3-tier fan-out
- **PlayerState** — Credits / rep / heat / faction / health / hunger / energy / implants
- **InventoryManager** — 25 catalog items, 10 categories, 14 equipment slots
- **CrewManager** — 9 roles, loyalty 0–100, XP levels 1–5, async operations

### Training Pipeline
- **DataCollector** — Runtime data collection from skill invocations and conversations
- **TrainingFlywheel** — Q&A expansion, dataset generation, quality filtering
- **BenchmarkRunner** — Model evaluation with leaderboard and history tracking
- **FinetuneOrchestrator** — Unsloth QLoRA fine-tuning with ModelZoo (14 model types)

### Copilot System
- **CopilotBridge** — Session lifecycle, pre-plan Nexus queries, action manifests
- **CopilotSelfConfig** — Sync instructions/agents/hooks between repo and Nexus
- **CopilotValidation** — Validates mirror integrity, hook references, runtime health
- **19 Agent Definitions** — Specialized agents for building, testing, reviewing, debugging, research

## External Services

| Service | Port | Purpose |
|---------|-----:|---------|
| LMStudio | 1234 | Local LLM inference (v1 API, CUDA, bearer auth) |
| Nexus KMS | 8700 | Knowledge management REST API |
| ComfyUI | 8188 | Image/video generation |
| Qwen3 TTS | 8600 | Text-to-speech server |
| Web Bridge | 8601 | Socket.IO real-time bridge |
| NLM Proxy | 8800 | NotebookLM RPC proxy |
| Chrome CDP | 9222 | Browser automation (ARGUS) |

## Quick Start

```powershell
# Install dependencies
pip install -r requirements.txt && npm install

# Launch the TUI (recommended)
python tui.py

# Or launch directly
python launcher.py bedroom         # Single scene → http://localhost:5556
python launcher.py --core           # Auto-start scenes + services
python launcher.py --all            # Everything
python launcher.py --list           # Show all targets with port status

# Run tests
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
```

## Project Structure

```
CosySim/
├── engine/                    # Core framework
│   ├── agents/                # CharacterAgent, VirtualAgent, Governor
│   │   └── interceptors/      # 26 auto-registered pipeline hooks
│   ├── mcp/                   # MCP framework, dialog, state management
│   │   ├── tools/             # 42 extracted domain tool modules
│   │   └── decorators.py      # @mcp_tool unified decorator
│   ├── skills/                # @skill decorator, registry, 31 packs
│   │   └── builtin/           # All skill implementations
│   ├── lmstudio/              # ServerController, LMLink, TaskQueue
│   ├── nexus/                 # Nexus client, NLM chain, query router
│   │   └── models.py          # 14 Pydantic v2 typed models
│   ├── world/                 # PlayerState, Inventory, Crew, WorldSim
│   ├── integrations/          # Copilot, Colab, Drive, NLM, ComputeRouter
│   ├── scenes/                # BaseScene, SceneManager
│   ├── services/              # Housekeeping, resilience, activity bus
│   └── config.py              # ConfigManager singleton (dot-notation YAML)
├── content/
│   ├── scenes/                # 20 scene implementations + 3 Streamlit apps
│   ├── shared/                # Shared templates (navbar_v2, neon_hud), CSS, JS
│   ├── simulation/            # SQLite persistence, character services
│   └── characters/            # Character definitions and data
├── config/                    # default.yaml, development.yaml, voices.yaml, mcp.json
├── scripts/
│   └── argus/                 # ARGUS browser automation, CDP tools
├── tests/                     # 315 test files, 9,577 passing
├── training/                  # Fine-tuning pipelines, datasets, model registry
├── docs/                      # 51 documentation files (INDEX.md entry point)
├── .github/
│   ├── instructions/          # 12 coding instruction files
│   ├── agents/                # 19 specialized agent definitions
│   └── hooks/                 # Copilot lifecycle hooks
├── tui.py                     # Terminal UI launcher (Textual framework)
├── launcher.py                # CLI scene launcher
└── main.py                    # Application entry point
```

## Testing

**9,577 tests passing** out of 9,963 total (386 deselected by marker filter `not slow and not integration`). 315 test files covering all scenes, engine modules, and integrations.

```powershell
# Full default suite (~23 minutes)
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Quick smoke test
python -m pytest tests/ -q --tb=short -x

# Single scene
python -m pytest tests/test_bedroom_game.py -v

# By marker
python -m pytest -m "unit" tests/
python -m pytest -m "not slow" tests/
```

## Documentation

All documentation lives in `docs/` with **[INDEX.md](./docs/INDEX.md)** as the central hub.

| Category | Key Docs |
|----------|----------|
| **Architecture** | [ARCHITECTURE.md](./docs/ARCHITECTURE.md) · [MCP_FRAMEWORK.md](./docs/MCP_FRAMEWORK.md) · [INTERCEPTORS.md](./docs/INTERCEPTORS.md) |
| **Scenes** | [SCENES.md](./docs/SCENES.md) · [SKILLS.md](./docs/SKILLS.md) · [NEON_HUD.md](./docs/NEON_HUD.md) |
| **Knowledge** | [NEXUS_INTEGRATION.md](./docs/NEXUS_INTEGRATION.md) · [NOTEBOOKLM.md](./docs/NOTEBOOKLM.md) · [NLM_KNOWLEDGE_FLYWHEEL.md](./docs/NLM_KNOWLEDGE_FLYWHEEL.md) |
| **Inference** | [LMSTUDIO.md](./docs/LMSTUDIO.md) · [TRAINING_SYSTEM.md](./docs/TRAINING_SYSTEM.md) · [FINETUNING_GUIDE.md](./docs/FINETUNING_GUIDE.md) |
| **Operations** | [DEPLOYMENT.md](./docs/DEPLOYMENT.md) · [CONFIGURATION.md](./docs/CONFIGURATION.md) · [API.md](./docs/API.md) |
| **Development** | [CONTRIBUTING.md](./docs/CONTRIBUTING.md) · [AGENT_ONBOARDING.md](./docs/AGENT_ONBOARDING.md) · [TESTING.md](./docs/TESTING.md) |
| **History** | [CHANGELOG.md](./CHANGELOG.md) · [ROADMAP.md](./ROADMAP.md) · [PROJECT_HINDSIGHT.md](./docs/PROJECT_HINDSIGHT.md) |

## License

MIT — see [LICENSE](./LICENSE)
