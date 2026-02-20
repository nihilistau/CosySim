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
# Run all 315 tests
python -m pytest tests/ -v

# Check system status
python launcher.py --status
```

## 🎯 Launch Modes

```bash
python launcher.py                # Hub (default, port 8500)
python launcher.py --mode phone   # Phone Scene (port 5555)
python launcher.py --mode bedroom # Bedroom Scene (port 5556)
python launcher.py --mode admin   # Admin Panel (port 8502)
python launcher.py --mode creator # Scene Creator (port 8504)
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

## 🔧 Three Pillars

CosySim runs on three services:

| Service | Port | Purpose |
|---------|------|---------|
| **LMStudio** | 1234 | LLM inference, MCP host |
| **ComfyUI** | 8188 | Image/video generation |
| **TTS Server** | 8600 | Voice generation (optional) |

Start the TTS server:
```bash
python -m engine.tts.qwen3_server --port 8600
```

## 📊 Admin Panel

Launch: `python launcher.py --mode admin` → `http://localhost:8502`

12 pages: Characters, RAG Editor, Event Chain Browser, Config Editor, KPI Dashboard, System Monitor, and more. Use GOD mode for full override access.

## 📖 Documentation

| Doc | Contents |
|-----|----------|
| `docs/THREE_PILLARS.md` | Architecture overview |
| `docs/LMSTUDIO.md` | LMStudio integration guide |
| `docs/TTS.md` | Voice generation & voice designer |
| `docs/KPI.md` | Benchmarking & metrics |
| `docs/STRUCTURE_GUIDE.md` | Project structure |
| `docs/SKILLS.md` | Skill system & MCP tools |
| `CHANGELOG.md` | Full version history |

## 🎉 You're Ready!

```bash
python launcher.py              # Start the Hub
# Open http://localhost:8500 and launch scenes from there
```

GodSpeed! 🚀
