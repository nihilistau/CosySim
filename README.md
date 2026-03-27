# CosySim

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![Version: 1.57](https://img.shields.io/badge/version-1.57-blueviolet.svg)]() [![Targets: 35](https://img.shields.io/badge/targets-35-6f42c1.svg)]() [![Tests: 417 files](https://img.shields.io/badge/tests-417_files-brightgreen.svg)]() [![Skills: 1040+](https://img.shields.io/badge/skills-1%2C040%2B-0a7f5a.svg)]()

> v1.57 — Gemini Native — Local-first multi-scene AI simulation framework

## Overview

CosySim is a self-improving AI simulation framework where **35 interactive targets** (18 game scenes, 11 services, 6 creation tools) run on local Flask/Socket.IO servers, powered by **LMStudio** local inference, **Nexus KMS** knowledge management, **NotebookLM** research distillation, and **Gemini Native APIs** (File Search, structured output, context caching, multimodal embeddings). Agents inhabit scenes, learn from interactions, and feed data back into the training pipeline — a closed loop that gets smarter over time. The **7-tier query pipeline** (with Gemini File Search at Tier 2.5) routes knowledge retrieval through confidence-scored tiers, the **Nexus agent registry** with tiered access control governs 8 agent types, and the **KnowledgePipeline** auto-generates Q&A pairs for continuous self-improvement.

The framework features a **unified cyberpunk aesthetic** (NeonCity theme), **character neurochemistry**, **cyberspace hacking**, a **living world engine** (markets, NPC routines, faction AI), **multiplayer foundation**, an **in-game news system**, a **virtual desktop shell (NeonOS)**, **stage-based narrative engine**, **danmaku spectator mode**, a **6-stage character creation wizard**, a **Signal Desktop app** (email, files, music), and an **Oracle persistent AI companion** — all driven by the MCP skill pipeline with ~1,040 skills across 99 packs.

## Runtime Snapshot

| Metric | Value |
|--------|-------|
| Version | **v1.57** — Gemini Native |
| Targets | **35** (18 game + 11 service + 6 creation) |
| Skills | **~1,040** across **99 packs** |
| Interceptors | **36** agent pipeline hooks |
| MCP tools | **43** domain modules |
| Tests | **417** test files |
| Agent types | **8** (copilot, claude_code, scene_agent, scheduler, training, observer, player, system) |
| Scheduler tasks | **92** autonomous maintenance jobs |
| Gemini APIs | File Search (managed RAG), structured output, context caching, multimodal embeddings |
| Nexus tables | **35** (knowledge, agent_registry, access_log, subscriptions, ...) |
| Streamlit apps | **4** (dashboard, admin, assets, creator) |
| Game systems | neurochemistry · cyberspace · territory · market · factions · multiplayer · news · narrative · danmaku · virtual FS · faction politics · heist planning · group chat · Signal Desktop · Oracle companion |

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser — Neon HUD v2 (glass panels · phone overlay · announcer)   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ Socket.IO / REST
┌────────────────────────────▼─────────────────────────────────────────┐
│              35 Targets across 3 Pillars                             │
│  ┌─ GAME (15) ──────────────────────────────────────────────────┐   │
│  │ phone · penthouse · lounge · tavern · casino · gallery      │   │
│  │ arena · realm · neoncity · coders · heist · games           │   │
│  │ grid · lab_break · oracle                                    │   │
│  ├─ SERVICE (11) ───────────────────────────────────────────────┤   │
│  │ nexus_kms · hub · nexus_panel · dashboard · admin · tts     │   │
│  │ bridge · nlm_proxy · system_control · command_center         │   │
│  │ intel_hub                                                    │   │
│  ├─ CREATION (7) ───────────────────────────────────────────────┤   │
│  │ canvas · canvas_api · assets · creator · asset_studio        │   │
│  │ creation_kit · neonos                                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────┬──────────────────────┬──────────────────────────┘
                     │                      │
┌────────────────────▼───────┐  ┌───────────▼──────────────────────────┐
│  ~1,040 Skills (99 packs)  │  │  MCP Pipeline                        │
│  @skill decorator          │  │  36 interceptors · @mcp_tool         │
│  auto-registry             │◄►│  AgentGovernor · DialogSystem        │
│  cooldown · cost · prereqs │  │  StreamProcessor · state sync        │
└────────────────────┬───────┘  └───────────┬──────────────────────────┘
                     │                      │
┌────────────────────▼──────────────────────▼──────────────────────────┐
│                         Engine Layer                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │ LMStudio     │ │ Nexus KMS    │ │ World Sim    │ │ Training   │ │
│  │ ServerCtrl   │ │ 7-Tier Query │ │ PlayerState  │ │ Flywheel   │ │
│  │ LMLink Fed   │ │ File Search  │ │ EventCascade │ │ Benchmark  │ │
│  │ TaskQueue    │ │ Smart Q&A    │ │ Economy      │ │ DataCollect│ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────┘ │
└────────┬──────────────────┬──────────────┬──────────────────────────┘
         │                  │              │
┌────────▼────────┐ ┌───────▼───────┐ ┌───▼────────────────────────────┐
│ LMStudio :1234  │ │ Nexus :8700   │ │ Gemini APIs                    │
│ CUDA · LMLink   │ │ FTS5 · Q&A    │ │ File Search · Structured Out   │
│ Vision · Coding  │ │ Rules · Memory│ │ Context Cache · Embeddings     │
└─────────────────┘ └───────────────┘ └────────────────────────────────┘
```

## Game Scenes (18)

| Scene | Display Name | Port | Description |
|-------|-------------|------|-------------|
| `phone` | SIGNAL | 5555 | Encrypted messaging with autonomous NPC texting, voice/photo/video |
| `penthouse` | THE PENTHOUSE | 5556 | Multi-agent roleplay with emotional stats, outfit tracking, Director |
| `lounge` | THE VELVET PIT | 5557 | 1920s jazz speakeasy — full MCP showcase with 2 NPCs |
| `tavern` | THE RUSTY ANCHOR | 5558 | Reference implementation — all MCP features: quests, reputation |
| `casino` | CLUB NOIR | 5559 | Underground casino with poker, consequence chains, cross-scene bridge |
| `gallery` | THE OBSCURA | 5560 | Dark art gallery with ContentGate-gated exhibits |
| `arena` | THE COLOSSEUM | 5561 | Combat simulation with card game mechanics |
| `realm` | THE SHATTERED THRONE | 5562 | Director-guided LitRPG with dual-agent orchestration |
| `neoncity` | NEON CITY | 5563 | Multi-district living city — 6 factions, economy, Glitch Storm |
| `coders` | THE LAB | 5564 | AI agents write/review/test real Python with sandboxed execution |
| `heist` | THE SCORE | 5565 | Cooperative planning with phase gates and crew specialties |
| `games` | THE ARCADE | 5567 | Investigation board, 3D dice, AI GameMaster, leaderboard |
| `grid` | THE GRID | 5569 | Underground marketplace — 4 zones (Market, Station, Den, Broker) |
| `lab_break` | LAB BREAK | 5571 | 3D escape scenario — convince the observer to open the door |
| `oracle` | THE ORACLE | 5572 | Claude's signature scene |

## External Services

| Service | Port | Purpose |
|---------|-----:|---------|
| LMStudio | 1234 | Local LLM inference (v1 API, CUDA, bearer auth) |
| Nexus KMS | 8700 | Knowledge management REST API (auto-managed) |
| Gemini APIs | cloud | File Search, structured output, context caching, embeddings (API key) |
| ComfyUI | 8188 | Image/video generation (optional) |
| Qwen3 TTS | 8600 | Text-to-speech server |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt && npm install

# Launch the TUI (recommended)
python tui.py

# Or launch directly
python launcher.py penthouse       # Single scene → http://localhost:5556
python launcher.py --core           # Auto-start core scenes + services
python launcher.py --all            # Everything
python launcher.py --list           # Show all targets with port status

# Unified CLI (auto-handles venv — no activation needed)
python cli.py ask "prompt"          # AI query (38 frontier models)
python cli.py oracle --health       # System diagnostics
python cli.py account list          # Account pool management
python cli.py nexus search "query"  # Knowledge management
python cli.py filestore bootstrap   # Gemini File Search RAG
python cli.py test --smoke          # Smart test runner

# Standalone apps (same thing, separate entry points)
python apps/nexus.py search "query"
python apps/argus.py har file.har   # Web app analysis
python apps/lmstudio.py status      # LMStudio management

# Run tests
python scripts/smart_test.py        # Smart runner — tests for uncommitted changes
python scripts/smart_test.py --smoke # ~15 files, ~53s
```

## Project Structure

```
CosySim/
├── engine/                    # Core framework
│   ├── agents/                # VirtualAgent, AgentGovernor, 36 interceptors
│   ├── mcp/                   # MCP framework, dialog, state management
│   │   └── tools/             # 43 domain tool modules
│   ├── skills/                # @skill decorator, registry, 100 packs
│   │   └── builtin/           # 815 engine-level skill implementations
│   ├── lmstudio/              # ServerController, LMLink, TaskQueue
│   ├── nexus/                 # Nexus client, NLM chain, query router
│   ├── world/                 # PlayerState, Inventory, Crew, WorldSim
│   ├── tts/                   # Qwen3-TTS, Orpheus, CosyVoice
│   └── config.py              # ConfigManager singleton (dot-notation YAML)
├── content/
│   ├── scenes/                # 24 scene implementations (19 Flask + 4 Streamlit + node)
│   ├── shared/                # Shared templates (navbar_v2, neon_hud), CSS, JS
│   └── simulation/            # SQLite persistence, character services
├── config/                    # default.yaml, development.yaml, voices.yaml, mcp.json
├── apps/                      # 15 standalone CLI apps (venv auto-bootstrap)
├── scripts/                   # Smart test runner, browser tests, ARGUS tools
├── tests/                     # 417 test files
├── training/                  # Fine-tuning pipelines, datasets, model registry
├── docs/                      # 34 documentation files (INDEX.md entry point)
├── tui.py                     # Terminal UI launcher (Textual framework)
├── cli.py                     # Unified CLI (16 commands, venv auto-exec)
├── launcher.py                # CLI scene launcher
└── main.py                    # Application entry point
```

## Documentation

All documentation lives in `docs/` with **[INDEX.md](./docs/INDEX.md)** as the central hub.

| Category | Key Docs |
|----------|----------|
| **Architecture** | [ARCHITECTURE.md](./docs/ARCHITECTURE.md) · [MCP_FRAMEWORK.md](./docs/MCP_FRAMEWORK.md) · [INTERCEPTORS.md](./docs/INTERCEPTORS.md) |
| **Scenes** | [SCENES.md](./docs/SCENES.md) · [SKILLS.md](./docs/SKILLS.md) · [NEON_HUD.md](./docs/NEON_HUD.md) · [OPENROOM_FEATURES.md](./docs/OPENROOM_FEATURES.md) |
| **Knowledge** | [NEXUS.md](./docs/NEXUS.md) · [LMSTUDIO.md](./docs/LMSTUDIO.md) |
| **Operations** | [OPERATIONS.md](./docs/OPERATIONS.md) · [CONFIGURATION.md](./docs/CONFIGURATION.md) · [API.md](./docs/API.md) · [APPS.md](./docs/APPS.md) |
| **Development** | [CONTRIBUTING.md](./docs/CONTRIBUTING.md) · [TESTING.md](./docs/TESTING.md) |

## License

MIT — see [LICENSE](./LICENSE)
