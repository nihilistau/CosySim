![CosySim Banner](https://svg-banners.vercel.app/api?type=origin&text1=CosySim&text2=Virtual%20Companion%20System&width=800&height=210)

# CosySim - Virtual Companion Simulation System v2.0

> **A professional-grade virtual companion platform with AI-driven characters, real-time voice/video interactions, and immersive interactive scenes.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 🌟 What is This?

An AI agent simulation framework with pluggable scenes for exploring LLM-driven characters, multi-agent interactions, media generation, and tool use — all orchestrated through **EventChain** ground truth.

- 🎮 **Framework** — `engine/` is a reusable toolkit: agents, skills, spatial system, media standards, logging, benchmarking
- 📱 **Phone Scene** — adult-themed chat with mood/arousal engine, NSFW selfies, autonomous messaging
- 🛏️ **Bedroom Scene** — multi-agent spatial environment: 2 characters, 7 locations, tick-based agent loop
- 🎛️ **Admin Panel** — 12-page diagnostic center with EventChain browser, GOD mode, RAG editor
- 🏠 **Hub** — landing page with service health strip and scene launcher
- 🎨 **Scene Creator** — guided wizard for scaffolding new scenes

---

## 🚀 Quick Start (< 5 minutes)

### 1. Install
```bash
# Clone repository
git clone https://github.com/yourusername/CosySim.git
cd CosySim

# Install dependencies
pip install -e .

# TTS models are symlinked (no download needed if you have them)
```

### 2. Launch
```bash
# Launch central hub (recommended)
python launcher.py

# Select option 1: Central Hub
# Navigate to: http://localhost:8500
```

### 3. Explore
- **Phone Scene** → Voice/video calls, messaging, photo sharing
- **Bedroom Scene** → 3D environment, character interactions
- **Admin Panel** → Character creation, system management

---

## 📱 Features

### 🎭 AI Character System
- **Expressive Characters** with distinct personalities (warmth, formality, humor, flirtiness, intelligence, creativity)
- **Role System** with goals, constraints, and capabilities
- **RAG Memory** via ChromaDB for long-term episodic context
- **Autonomous Messaging** — characters message you proactively on a configurable schedule
- **EventChain diagnostics** — every LLM call, tool use, and autonomous trigger fully logged

### 🤖 Agent Framework
| Component | Module | Description |
|---|---|---|
| **CharacterAgent** | `engine/agents/character_agent.py` | Persona + RAG + tools + MCP + EventChain |
| **SceneAgent** | `engine/agents/scene_agent.py` | Quick one-shot tasks (title, summarise, classify) |
| **LMStudioManager** | `engine/lmstudio/client.py` | LM Studio server + model management via SDK & CLI |
| **LMStudioClient** | `engine/lmstudio/client_v2.py` | REST client with MCP integrations + SSE streaming |
| **SkillRegistry** | `engine/skills/registry.py` | `@skill` decorator registry, pack tools, MCP bridge |

### 🔧 Built-in Skill Packs
| Pack | Skills |
|---|---|
| `memory` | `search_memory`, `store_memory`, `get_event_chain_summary`, `summarize_chain` |
| `character` | `get_character_state`, `adjust_trait`, `set_mood`, `adjust_relationship` |
| `comfyui` | `generate_image`, `generate_character_portrait`, `list_comfyui_workflows` |
| `voice` | `generate_voice_message`, `list_voice_messages` |
| `tts` | `generate_voice_message`, `cast_voice`, `list_voice_presets`, `list_voicemails` |

### 📞 Communication Features
| Feature | Description | Status |
|---|---|---|
| **Voice Calls** | Real-time voice with CosyVoice TTS | ✅ Working |
| **Video Calls** | Live video with generated faces | ✅ Working |
| **Voice Messages** | Async audio messages + gallery | ✅ Working |
| **Video Messages** | Short video clips + gallery | ✅ Working |
| **Text Messaging** | Rich text chat | ✅ Working |
| **Photo Sharing** | AI-generated selfies via ComfyUI | ✅ Working |

### 🏗️ System Architecture
```
engine/                  # Reusable framework
├── agents/             # CharacterAgent + AgentLoop (tick-based)
├── assets/             # Asset management system
├── config.py           # YAML config with env var overrides
├── config_validator.py # Schema-based config validation
├── logging/            # CosyLogger, @timed + LLM KPIs, SystemMonitor
├── lmstudio/           # LMStudio SDK (client.py) + REST v2 (client_v2.py)
├── mcp/                # CosySim MCP server + FastAPI web bridge
├── media/              # MediaConfig singleton (image/video/audio standards)
├── scenes/             # BaseScene, SceneRegistry (auto-discover)
├── services/           # @retry, CircuitBreaker
├── skills/             # @skill decorator, packs (memory, character, comfyui, tts)
├── spatial/            # Location, SceneMap (capacity, occupancy, nearby)
└── tts/                # Qwen3-TTS server + VoiceDesigner

content/                # Example scenes (customize freely)
├── scenes/
│   ├── phone/          # Port 5555 — adult phone scene
│   ├── bedroom/        # Port 5556 — multi-agent spatial
│   ├── admin/          # Port 8502 — 13-page admin panel (+ KPI Dashboard)
│   ├── hub/            # Port 8500 — landing page + scene creator
│   └── dashboard/      # Port 8501 — metrics
└── simulation/
    ├── database/       # SQLite (10 tables) + ChromaDB + EventChain
    ├── character_system/
    └── services/       # ComfyUI client, media gen, voice/video

config/                 # YAML configuration files
tests/                  # 281 tests
```

---

## 🎯 Usage

### Launch Modes

```bash
python launcher.py                # Hub (default, port 8500)
python launcher.py --mode phone   # Phone Scene (port 5555)
python launcher.py --mode bedroom # Bedroom Scene (port 5556)
python launcher.py --mode admin   # Admin Panel (port 8502)
python launcher.py --mode creator # Scene Creator (port 8504)
python launcher.py --mode test    # Run 315+ tests
python launcher.py --status       # System status check
```

---

## 🎨 The 5 Characters

| Character | Personality | Best For | Messaging Frequency |
|-----------|-------------|----------|---------------------|
| **Maya** | Playful & Affectionate | Romantic interactions, fun conversations | Every 3 min |
| **Luna** | Mysterious & Creative | Deep discussions, artistic topics | Every 7 min |
| **Dr. Sophia Reed** | Professional & Intelligent | Intellectual debates, sophisticated chat | Every 10 min |
| **Jade Harper** | Adventurous & Energetic | Outdoor activities, fitness challenges | Every 4 min |
| **Emma Rose** | Nurturing & Caring | Emotional support, comfort | Every 5 min |

Each character has:
- ✅ Unique personality (6 parameters)
- ✅ Full physical description
- ✅ Background story
- ✅ Custom voice settings
- ✅ Behavioral traits

---

## 🛠️ Admin Panel (port 8502)

| Page | Features |
|------|----------|
| 📊 **Dashboard** | Service health (LMStudio/ComfyUI/DB), system metrics (CPU/RAM/GPU), benchmark table |
| 📋 **Logs** | Ring buffer + file logs, level/search filters, export |
| 🔗 **EventChain** | Chain browser with tree view, scene/character/type filters |
| ⚙️ **Config Editor** | Type-aware inputs, validation, save & apply to YAML |
| ✏️ **RAG Editor** | Edit conversations/memories with logic guards |
| 🔴 **GOD Mode** | Raw SQL, event injection, force character state, danger zone |
| 👤 **Characters** | Character CRUD with personality traits |
| 🎬 **Scenes** | Scene registry, status monitoring |
| 🖼️ **Media** | Gallery browser |
| 🧠 **LMStudio** | Model management |
| 💾 **Backup** | Backup & restore |
| 🗂️ **Assets** | Browser, search, personality library |

---

## 📚 Documentation

| Doc | Description |
|-----|-------------|
| [THREE_PILLARS.md](docs/THREE_PILLARS.md) | Architecture: CosySim + LMStudio + ComfyUI |
| [STRUCTURE_GUIDE.md](docs/STRUCTURE_GUIDE.md) | Three-layer architecture, file map |
| [API.md](docs/API.md) | REST API reference for all scenes |
| [SKILLS.md](docs/SKILLS.md) | Skill authoring guide |
| [COMFYUI.md](docs/COMFYUI.md) | ComfyUI integration + PromptBuilder tiers |
| [LMSTUDIO.md](docs/LMSTUDIO.md) | LMStudio v2 client, MCP server, streaming |
| [TTS.md](docs/TTS.md) | Qwen3-TTS server, voice designer, casting |
| [KPI.md](docs/KPI.md) | Benchmarking, LLM KPIs, system monitoring |
| [LOGGING.md](docs/LOGGING.md) | @timed, SystemMonitor, ring buffer |
| [ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | Admin panel usage + GOD mode |
| [AGENTS_GUIDE.md](AGENTS_GUIDE.md) | Agent handoff guide |

---

## 🧪 Testing

```bash
# Run all 281 tests
python -m pytest tests/ -v --tb=short

# Run specific suite
python -m pytest tests/test_database.py -v
python -m pytest tests/test_spatial.py -v
```

**Coverage:** Database (66 tests), EventChain (20), Skills (18), Spatial (30), AgentLoop (18), MediaConfig (16), PromptBuilder (17)

---

## 🔧 Configuration

Edit `config/default.yaml` or set environment variables:

```bash
# Environment
export ENVIRONMENT=production

# Database
export DATABASE_PATH=/path/to/database.db

# Ports
export PHONE_PORT=5555
export ADMIN_PORT=8502
export HUB_PORT=8500

# Security
export SECRET_KEY=your-secret-key

# LLM
export LLM_API_BASE=http://localhost:1234/v1
export LLM_MODEL=your-model-name
```

---

## 🚢 Deployment

### Docker (Recommended)

```bash
# Build image
docker-compose build

# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

### Systemd (Linux)

```bash
# Copy service files
sudo cp deployment/systemd/*.service /etc/systemd/system/

# Enable and start
sudo systemctl enable cosyvoice-hub
sudo systemctl start cosyvoice-hub
```

### Manual

```bash
# Set environment
export ENVIRONMENT=production

# Start services (use screen or tmux)
python content/simulation/scenes/hub/hub_scene.py &
python content/simulation/scenes/phone/phone_scene.py &
python content/simulation/scenes/bedroom/bedroom_scene.py &
```

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Credits

- **CosyVoice** - Text-to-Speech engine
- **ChromaDB** - Vector database for RAG memory
- **Three.js** - 3D rendering
- **Flask** - Backend framework
- **Streamlit** - Admin/Hub interfaces

---

## 📞 Support

- 📧 **Email**: support@example.com
- 💬 **Discord**: [Join our server](https://discord.gg/example)
- 🐛 **Issues**: [GitHub Issues](https://github.com/yourusername/CosySim/issues)
- 📖 **Docs**: [Full Documentation](docs/)

---

## 🗺️ Roadmap

### Completed ✅
- [x] EventChain ground truth system (chain_id/parent_id causal trees, 16+ event types)
- [x] LMStudio SDK integration (load/unload models, VRAM management)
- [x] Skills system (`@skill` decorator, pack registry, MCP bridge)
- [x] CharacterAgent with RAG + tools + EventChain logging
- [x] Multi-agent bedroom scene (AgentLoop, spatial system, 7 locations)
- [x] Phone scene: mood engine, arousal engine, 5 NSFW tiers, autonomous messaging
- [x] Media standards: MediaConfig singleton, PromptBuilder with escalation tiers
- [x] Logging/benchmarking/monitoring (`@timed`, SystemMonitor, ring buffer)
- [x] Admin panel: 12-page diagnostic center with GOD mode, RAG editor, chain browser
- [x] Config validation, retry/circuit breaker, scene registry
- [x] Per-pair relationship table (character_relationships with canonical ordering)
- [x] 315+ tests covering all framework components
- [x] Scene Creator wizard with 4 templates
- [x] LMStudio Deep Integration: REST v2 client, per-request MCP, SSE streaming
- [x] FastMCP server: 9 tools + 5 resources exposing CosySim to LMStudio
- [x] FastAPI web bridge with SSE streaming proxy
- [x] Qwen3-TTS voice generation server (real inference + placeholder fallback)
- [x] Voice Designer with CASTING_OFFICE, 6 presets, zero-shot support
- [x] KPI dashboard: LLM timing, token throughput, system monitor, chain analytics
- [x] CharacterAgent wired into all scenes with skill packs
- [x] AgentLoop with location-aware perception and enriched idle actions
- [x] Voice message pipeline: AutonomousMessenger → TTS server → WAV
- [x] End-to-end integration tests across all three pillars

### Upcoming
- [ ] Real-time EventChain streaming via WebSocket
- [ ] Plugin system for community skill packs
- [ ] Additional TTS models (CosyVoice, StyleTTS2)
- [ ] Video generation via ComfyUI AnimateDiff workflows

---

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=yourusername/CosySim&type=Date)](https://star-history.com/#yourusername/CosySim&Date)

---

<p align="center">
  <strong>Built with ❤️ by the CosySim Team</strong>
</p>

<p align="center">
  <sub>If you find this project helpful, please consider giving it a ⭐️</sub>
</p>
