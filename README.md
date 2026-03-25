# CosySim

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![Version: 1.51](https://img.shields.io/badge/version-1.51-blueviolet.svg)]() [![Targets: 33](https://img.shields.io/badge/targets-33-6f42c1.svg)]() [![Tests: 404 files](https://img.shields.io/badge/tests-404_files-brightgreen.svg)]() [![Skills: 1010+](https://img.shields.io/badge/skills-1%2C010%2B-0a7f5a.svg)]()

> v1.51 — OpenRoom-Inspired Features — Local-first multi-scene AI simulation framework

## Overview

CosySim is a self-improving AI simulation framework where **33 interactive targets** (15 game scenes, 11 services, 7 creation tools) run on local Flask/Socket.IO servers, powered by **LMStudio** local inference, **Nexus KMS** knowledge management, and **NotebookLM** research distillation. Agents inhabit scenes, learn from interactions, and feed data back into the training pipeline — a closed loop that gets smarter over time.

The framework features a **unified cyberpunk aesthetic** (NeonCity theme), **character neurochemistry**, **cyberspace hacking**, a **living world engine** (markets, NPC routines, faction AI), **multiplayer foundation**, an **in-game news system**, a **virtual desktop shell (NeonOS)**, **stage-based narrative engine**, **danmaku spectator mode**, and a **6-stage character creation wizard** — all driven by the MCP skill pipeline with ~1,010 skills across 98 packs.

## Runtime Snapshot

| Metric | Value |
|--------|-------|
| Version | **v1.51** — OpenRoom-Inspired Features |
| Targets | **33** (15 game + 11 service + 7 creation) |
| Skills | **~1,030** across **100 packs** |
| Interceptors | **30** agent pipeline hooks |
| MCP tools | **43** domain modules |
| Tests | **404** test files |
| Streamlit apps | **4** (dashboard, admin, assets, creator) |
| Game systems | neurochemistry · cyberspace · territory · market · factions · multiplayer · news · narrative · danmaku · virtual FS · faction politics · heist planning · group chat |

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser — Neon HUD v2 (glass panels · phone overlay · announcer)   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ Socket.IO / REST
┌────────────────────────────▼─────────────────────────────────────────┐
│              32 Targets across 3 Pillars                             │
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
│  ~1,030 Skills (100 packs) │  │  MCP Pipeline                        │
│  @skill decorator          │  │  30 interceptors · @mcp_tool         │
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
│ Vision · Coding  │ │ Rules · Memory  │ │ RPC Registry · Pro tier     │
└─────────────────┘ └─────────────────┘ └──────────────────────────────┘
```

## Game Scenes (15)

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

# Run tests
python scripts/smart_test.py        # Smart runner — tests for uncommitted changes
python scripts/smart_test.py --smoke # ~15 files, ~53s
```

## Project Structure

```
CosySim/
├── engine/                    # Core framework
│   ├── agents/                # VirtualAgent, AgentGovernor, 30 interceptors
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
├── scripts/                   # Smart test runner, browser tests, ARGUS tools
├── tests/                     # 404 test files
├── training/                  # Fine-tuning pipelines, datasets, model registry
├── docs/                      # 34 documentation files (INDEX.md entry point)
├── tui.py                     # Terminal UI launcher (Textual framework)
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
| **Operations** | [OPERATIONS.md](./docs/OPERATIONS.md) · [CONFIGURATION.md](./docs/CONFIGURATION.md) · [API.md](./docs/API.md) |
| **Development** | [CONTRIBUTING.md](./docs/CONTRIBUTING.md) · [TESTING.md](./docs/TESTING.md) |

## License

MIT — see [LICENSE](./LICENSE)
