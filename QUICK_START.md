# 🎮 CosySim — Quick Start Guide

## Prerequisites

- **Python 3.10+** (conda recommended)
- **LMStudio** running on port 1234 with a model loaded
- **ComfyUI** running on port 8188 (optional, for image/video generation)

## 🚀 Installation

```bash
# Clone and install
cd CosySim
pip install -r requirements.txt
pip install -e .
```

Or use the install script:
```powershell
.\INSTALL.ps1
```

## ✅ Verify Setup

```bash
# Run all 699 tests
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Check system status
python launcher.py --status
```

## 🎯 Launch Modes

```bash
python launcher.py                   # Hub (default, port 8500)
python launcher.py --mode phone      # Phone Scene (port 5555)
python launcher.py --mode bedroom    # Bedroom Scene (port 5556)
python launcher.py --mode realm      # The Realm — LitRPG (port 5562)
python launcher.py --mode neoncity   # NeonCity — strategy (port 5563)
python launcher.py --mode coders     # Coders Room — AI code sim (port 5564)
python launcher.py --mode casino     # Midnight Casino (port 5559)
python launcher.py --mode warzone    # Global Strike (port 5561)
python launcher.py --mode admin      # Admin Panel (port 8502)
python launcher.py --mode all        # Phone + Bedroom + Hub + TTS + Bridge
```

### Start All Servers
```powershell
.\start_servers.ps1    # Hub + Phone + Admin
```

## 📱 Phone Scene (Your First Scene)

1. Launch: `python launcher.py --mode phone`
2. Open: `http://localhost:5555`
3. Select a character from the control panel
4. Send messages — the agent uses LMStudio for responses
5. Watch for autonomous messages, mood changes, and spontaneous media

**Features:** Dynamic mood, relationship engine, arousal system, voice messages, image selfies, typing indicators, read receipts.

## 🛏️ Bedroom Scene (Multi-Agent)

1. Launch: `python launcher.py --mode bedroom`
2. Open: `http://localhost:5556`
3. Watch two agents interact autonomously across 7 locations
4. Agents move, speak, flirt, and exhibit emergent behavior

## ⚔️ The Realm (Dual-Agent LitRPG)

1. Launch: `python launcher.py --mode realm`
2. Open: `http://localhost:5562`
3. A Director agent runs the story, an Assistant agent helps (and heckles)
4. Inventory, stats, skill checks, and Murder Mystery sub-module

## 🔧 Three Pillars

CosySim runs on three services:

| Service | Port | Purpose |
|---------|------|---------|
| **LMStudio** | 1234 | LLM inference via v1 native API, MCP host |
| **ComfyUI** | 8188 | Image/video generation |
| **TTS Server** | 8600 | Voice generation (optional) |

Start the TTS server:
```bash
python launcher.py --mode tts
```

## 📊 Admin Panel

Launch: `python launcher.py --mode admin` → `http://localhost:8502`

13 pages: Characters, RAG Editor, Event Chain Browser, Config Editor, KPI Dashboard, System Monitor, GOD mode, and more.

## 📖 Documentation

| Doc | Contents |
|-----|----------|
| `AGENT_NOTES.md` | Complete system reference (2500+ lines) |
| `docs/SKILLS.md` | Skill system, MCP tools, scene packs |
| `docs/LMSTUDIO.md` | LMStudio v1 API, MCP, streaming |
| `docs/THREE_PILLARS.md` | Architecture overview |
| `docs/MCP_FRAMEWORK.md` | MCP framework developer guide |
| `docs/API.md` | REST API reference |
| `docs/TTS.md` | Voice generation & voice designer |
| `docs/STRUCTURE_GUIDE.md` | Project structure |
| `CHANGELOG.md` | Full version history |

## 🎉 You're Ready!

```bash
python launcher.py              # Start the Hub
# Open http://localhost:8500 and launch scenes from there
```

GodSpeed! 🚀
