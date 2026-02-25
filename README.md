# CosySim — AI Agent Simulation Framework

> A local-first AI simulation platform powered by LMStudio with a custom MCP framework.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 1756](https://img.shields.io/badge/tests-1756%20passing-brightgreen.svg)]()

## Overview

CosySim is an AI agent simulation framework where every scene is a self-contained web application with its own agents, state, and game logic. Scenes range from a messaging app with dynamic mood tracking to a full LitRPG with dual-agent orchestration, a cyberpunk strategy board game, and an AI coding sandbox — all running locally against LMStudio.

What makes CosySim unique is its **Model Context Protocol (MCP) pipeline**. Agents don't just generate text — they call tools during inference for memory retrieval, media generation, game mechanics, and state mutation. A 25-interceptor governance pipeline wraps every inference call, injecting context, enforcing personality constraints, syncing mood and relationship state, and shaping responses before they reach the user.

The framework is designed for builders who want to experiment with multi-agent orchestration, tool-augmented LLMs, and interactive simulations without cloud dependencies. Everything runs on your machine: LMStudio for inference, ChromaDB for memory, ComfyUI for image generation, and Qwen3-TTS for voice — all wired together through MCP skill packs.

## Quick Start

**Prerequisites:** Python 3.11+, LMStudio running on port 1234 with a model loaded. ComfyUI (port 8188) and TTS (port 8600) are optional.

```bash
# 1. Install dependencies
pip install -r requirements.txt && npm install

# 2. Launch a scene
python launcher.py --mode phone      # Phone → http://localhost:5555

# 3. Or launch the hub
python launcher.py                   # Hub → http://localhost:8500

# 4. Run tests
python -m pytest tests/ -q --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
```

Other launch options:
```bash
python launcher.py --mode all        # Phone + Bedroom + Hub + TTS + Bridge
python launcher.py --status          # Check service health
.\start_servers.ps1                  # Hub + Phone + Admin (Windows)
.\INSTALL.ps1                        # Full install script (Windows)
```

## Scenes

### Game Scenes

| Scene | Port | Type | Description |
|-------|------|------|-------------|
| **Phone** | 5555 | Flask | Messaging app with mood/arousal engine, selfies, voice messages |
| **Bedroom** | 5556 | Flask | Multi-agent spatial environment, 7 locations, tick-based agent loop |
| **Lounge** | 5557 | Flask | Social scene with ambient characters |
| **Casino** | 5559 | Flask | Blackjack, poker, slots with MCP game sessions |
| **Gallery** | 5560 | Flask | Art evaluation, structured critique, image generation |
| **Warzone** | 5561 | Flask | Turn-based tactical combat |
| **Realm** | 5562 | Flask | Director-guided LitRPG with dual-agent orchestration |
| **NeonCity** | 5563 | Flask | Cyberpunk strategy board game with procedural city |
| **Coders** | 5564 | Flask | AI agent idle sim — agents write real code in sandboxed Python |
| **Heist** | 5565 | Flask | Cooperative multi-agent heist with planning, execution, and escape phases |
| **Command Center** | 5566 | Flask | War-room dashboard with live scene controls and system monitoring |

### Utility Scenes

| Scene | Port | Type | Description |
|-------|------|------|-------------|
| **Hub** | 8500 | Streamlit | Landing page, service health, scene launcher |
| **Dashboard** | 8501 | Streamlit | System metrics overview |
| **Admin** | 8502 | Streamlit | 13-page diagnostic center with GOD mode |
| **Assets** | 8503 | Streamlit | Asset generator |

### Services

| Service | Port | Type | Description |
|---------|------|------|-------------|
| **TTS** | 8600 | FastAPI | Qwen3-TTS voice generation with MCP integration |
| **Bridge** | 8601 | FastAPI | MCP web bridge (SSE proxy, file upload) |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      User / UI                          │
├─────────────────────────────────────────────────────────┤
│  content/scenes/       Flask & Streamlit web apps       │
│  ├── phone/            Each scene has its own agents,   │
│  ├── realm/            state, templates, and skill pack │
│  ├── neoncity/                                          │
│  └── ...               (11 game + 4 utility scenes)     │
├─────────────────────────────────────────────────────────┤
│  engine/               Reusable framework               │
│  ├── agents/           CharacterAgent, VirtualAgent,    │
│  │                     VirtualAgentManager               │
│  ├── mcp/              MCPFramework, InterceptorPipeline│
│  │                     DialogSystem, GameSession         │
│  ├── skills/           @skill decorator, 9 builtin packs│
│  ├── lmstudio/         LMSClient (v1 API), streaming,  │
│  │                     response_id threading             │
│  ├── tts/              Qwen3-TTS server + VoiceDesigner │
│  └── scenes/           BaseScene, SceneRegistry         │
├─────────────────────────────────────────────────────────┤
│  config/               YAML + JSON configuration        │
│  content/simulation/   Characters, RAG, media services  │
└─────────────────────────────────────────────────────────┘
         │                    │                  │
    LMStudio:1234       ComfyUI:8188       ChromaDB
```

## Key Systems

- **MCP Pipeline** — 25-interceptor governance pipeline wrapping every inference call. Interceptors inject context, enforce rules, sync state, and shape responses pre- and post-inference.
- **Governance** — `AgentGovernor` + `InterceptorPipeline` with priority-ordered interceptors: personality guards, policy enforcers, mood sync, relationship tracking, activity logging, and more.
- **Skill Packs** — 9 core packs (memory, character, comfyui, voice, tts, social, boards, training, notebooklm) + per-scene packs. Skills are Python functions exposed as MCP tools via the `@skill` decorator.
- **Character System** — Stats, traits, mood, arousal, relationship scores, buffs, and tag-based personality modeling. Characters evolve through interactions.
- **LMStudio Integration** — Native v1 API with `response_id` threading for KV cache reuse, SSE streaming with inline tag extraction, and stateful conversation branching.
- **TTS** — Qwen3-TTS voice generation server with voice designer, presets, and MCP tool integration.
- **Media Generation** — ComfyUI integration for images and video, wired as MCP tools with workflow templates.

## Project Stats

| Metric | Count |
|--------|-------|
| Tests | 1,756 |
| Game scenes | 11 |
| Interceptors | 25 |
| MCP tools | 50+ |
| Core skill packs | 9 |
| Scene skill packs | 11 |

## Documentation

- [Architecture & Structure](docs/STRUCTURE_GUIDE.md)
- [API Reference](docs/API.md)
- [MCP Framework](docs/MCP_FRAMEWORK.md)
- [MCP Architecture](docs/MCP_ARCHITECTURE.md)
- [Agents Guide](docs/AGENTS_GUIDE.md)
- [LMStudio Integration](docs/LMSTUDIO.md)
- [TTS & Voice](docs/TTS.md)
- [Skills](docs/SKILLS.md)
- [Admin Guide](docs/ADMIN_GUIDE.md)
- [KPI & Metrics](docs/KPI.md)
- [Contributing](docs/CONTRIBUTING.md)
- [NotebookLM](docs/NOTEBOOKLM.md)
- [Changelog](CHANGELOG.md)
- [Onboarding](ONBOARDING.md)
- [Security](SECURITY.md)

## License

MIT — see [LICENSE](LICENSE).
