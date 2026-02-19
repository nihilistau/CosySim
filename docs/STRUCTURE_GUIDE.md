# 🏗️ CosySim Architecture Guide

## 📊 The Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CosySim System                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌────────────┐             │
│  │  ENGINE/  │  │ CONTENT/  │  │  CONFIG/   │             │
│  │  (Tech)   │  │ (Game)    │  │ (Settings) │             │
│  └─────┬─────┘  └─────┬─────┘  └──────┬─────┘             │
│        │              │                │                   │
│        ▼              ▼                ▼                   │
│   TTS, Assets    Scenes, Chars    YAML Files              │
│   Audio, Video   Database, RAG    Ports, Paths            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 1️⃣ ENGINE/ - The Foundation (Don't Modify Often)

**What:** Core technical systems that power everything
**Purpose:** Reusable components for ANY simulation project

```
engine/
├── __init__.py          ⭐ Top-level exports (get_config, BaseScene, etc.)
│
├── agents/              🤖 Agent Framework
│   ├── character_agent.py → LLM-backed character with skills
│   └── agent_loop.py     → Tick-based perceive→decide→execute loop
│
├── assets/              ⭐ Asset Management System
│   ├── manager.py       → Central registry for all media
│   ├── types.py         → Asset type definitions
│   └── base.py          → Base asset classes
│
├── config.py            ⭐ Configuration System (dot-notation, env overrides)
├── config_validator.py  🛡️ Schema-based config validation
│
├── logging/             📊 Logging, Benchmarking & Monitoring
│   ├── cosy_logger.py   → Ring-buffer logger with install_logger()
│   ├── benchmark.py     → @timed decorator, BenchmarkStore (min/max/avg/p95)
│   └── monitor.py       → SystemMonitor (CPU/RAM/GPU/services)
│
├── lmstudio/            🧠 LMStudio Integration
│   └── client.py        → HTTP client for LMStudio API
│
├── media/               🖼️ Media Standards
│   └── media_config.py  → MediaConfig singleton from YAML
│
├── scenes/              🎮 Scene Framework
│   ├── base_scene.py    → Base class + get_health() + register_health_route()
│   ├── scene_manager.py → Scene lifecycle management
│   └── scene_registry.py → Auto-discover BaseScene subclasses
│
├── services/            🔧 Service Infrastructure
│   └── resilience.py    → @retry, CircuitBreaker (closed→open→half_open)
│
├── skills/              ⚡ Skill System
│   ├── skill.py         → @skill decorator
│   ├── registry.py      → SKILL_REGISTRY, get_pack_tools()
│   ├── chain_context.py → Thread-local chain_id propagation
│   └── packs/           → Skill packs (memory, character, comfyui)
│
├── spatial/             📍 Spatial System
│   ├── location.py      → Location dataclass (capacity, properties)
│   └── scene_map.py     → SceneMap (place, move, nearby, interact)
│
├── tts/                 🎤 Text-to-Speech (CosyVoice)
│   └── cosyvoice/       → Complete TTS implementation
│
└── testing/             🧪 Testing Framework
    └── framework/       → Automated test system
```

**Key Insight:** This is the **"game engine"** - stable, reusable tech.

---

## 2️⃣ CONTENT/ - Your Simulation (Customize This!)

**What:** Your specific game/simulation content
**Purpose:** Characters, scenes, stories, gameplay

```
content/
├── scenes/              ⭐ Scene Implementations
│   ├── hub/            🏠 Central Hub (Tutorial & Launcher)
│   │   ├── hub_scene.py   → Landing page with health strip & scene cards
│   │   └── scene_creator.py → Guided scene scaffolding wizard
│   │
│   ├── phone/          📱 Phone Scene (Messages, Calls, Adult)
│   │   ├── phone_scene.py → Phone interface with mood/arousal engine
│   │   ├── apps/
│   │   │   ├── messages.py  → Messaging app
│   │   │   └── gallery.py   → Photo gallery
│   │   ├── static/     → CSS, JavaScript, images
│   │   └── templates/  → HTML UI
│   │
│   ├── bedroom/        🛏️ Bedroom Scene (Multi-Agent, Adult)
│   │   ├── bedroom_scene.py → 2-character spatial environment
│   │   ├── static/     → Assets, CSS, JS
│   │   └── templates/  → HTML
│   │
│   ├── admin/          🛠️ Admin Panel (Multi-Panel Diagnostic Center)
│   │   ├── admin_panel.py → Thin Streamlit router (120 lines)
│   │   └── pages/         → 12 page modules
│   │       ├── dashboard.py      → Service health, system metrics
│   │       ├── logs.py           → Log viewer + benchmarks
│   │       ├── chains.py         → EventChain browser (tree view)
│   │       ├── config_editor.py  → Type-aware config editor
│   │       ├── rag_editor.py     → RAG message editor with guards
│   │       ├── god_mode.py       → Raw SQL, force ops, danger zone
│   │       ├── character_manager.py
│   │       ├── scene_manager.py
│   │       ├── media.py
│   │       ├── lmstudio.py
│   │       ├── backup.py
│   │       └── assets.py
│   │
│   └── dashboard/      📊 Dashboard (Overview)
│       └── dashboard_v2.py → System metrics
│
└── simulation/          ⭐ Simulation Engine
    ├── character_system/     👤 Characters
    │   ├── character.py      → Character class
    │   ├── personality.py    → Personality traits
    │   └── role.py           → Roles (girlfriend, friend, etc.)
    │
    ├── database/             💾 Data Storage
    │   ├── db.py             → SQLite (10 tables, full CRUD)
    │   └── rag.py            → ChromaDB vector store
    │
    ├── services/             🎬 Media & Communication Services
    │   ├── comfyui_client.py → ComfyUI API + PromptBuilder (5 tiers)
    │   ├── media_generator.py → Generate images/videos
    │   ├── voice_call.py     → Real-time voice calls
    │   ├── video_call.py     → Video calls with lip-sync
    │   ├── voice_message.py  → Voice messages
    │   ├── video_message.py  → Video messages
    │   └── autonomous_messenger.py → Auto messaging
    │
    └── shared/               🎨 Shared UI
        └── streamlit_theme.py → Dark theme injection
```

**Key Insight:** This is your **"game content"** - customize freely!

---

## 3️⃣ CONFIG/ - Settings (Tune Without Code)

**What:** Configuration files that control behavior
**Purpose:** Change settings without modifying code

```
config/
├── default.yaml      ⭐ Base Configuration
│   ├── database:     → SQLite paths
│   ├── scenes:       → Port numbers (hub: 8500, phone: 5555)
│   ├── tts:          → Voice settings
│   ├── llm:          → LLM API settings
│   └── logging:      → Log levels
│
├── development.yaml  🛠️ Dev Overrides
│   └── debug: true   → Extra logging, no caching
│
└── production.yaml   🚀 Production Overrides
    └── optimized     → Performance tuning
```

**Example Config:**
```yaml
scenes:
  hub:
    port: 8500
  phone:
    port: 5555
  bedroom:
    port: 5003

database:
  sqlite_path: "conversation_history.db"
  chroma_path: "content/simulation/chroma_db"
```

---

## 🗂️ Supporting Directories

```
docs/                    📚 Documentation
├── ARCHITECTURE.md      → System design (135KB!)
├── DEVELOPMENT.md       → Dev guide (138KB!)
├── API_REFERENCE.md     → API docs
└── archive/            → Old docs

tests/                   🧪 Tests
└── integration/         → End-to-end tests

deployment/              🚀 Production
├── systemd/            → Linux service files
└── docker/             → Docker configs

.github/                 ⚙️ CI/CD
└── workflows/          → Automated testing

pretrained_models/       🔗 Symlink → CosyVoice models
asset/                   🔗 Symlink → Voice samples
```

---

## 🎯 How It All Connects

### Launching a Scene:

```
1. launcher.py              ┐
   ↓                        │ Entry Point
2. Loads config/default.yaml    │
   ↓                        ┘
3. Imports scene            ┐
   engine/scenes/base_scene.py  │ Framework
   content/scenes/phone/    │
   ↓                        ┘
4. Initializes systems      ┐
   engine/assets/manager.py │ Core Systems
   content/simulation/db.py │
   ↓                        ┘
5. Starts Flask server      ┐
   Serves templates/        │ Runtime
   Handles API calls        │
   ↓                        ┘
6. Browser → localhost:5555 → Phone UI
```

---

## 💡 Key Files Explained

### Root Level (Entry Points)

| File | Purpose |
|------|---------|
| `launcher.py` | Main menu - choose which scene to launch |
| `launch_simulation.py` | Quick launcher for simulation |
| `start_servers.ps1` | Launch all scenes at once |
| `main.py` | Alternative entry point |

### Configuration

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python package config (pip install -e .) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |
| `docker-compose.prod.yml` | Production Docker setup |

### Documentation

| File | Purpose |
|------|---------|
| `README.md` | Project overview |
| `QUICK_START.md` | 5-minute setup |
| `DEPLOYMENT.md` | Production deployment |
| `MIGRATION.md` | CosyVoice → CosySim changes |
| `CLEANUP_SUMMARY.md` | What was removed/kept |

---

## 🎮 Scene Structure (Detailed)

All scenes follow the same pattern:

```
content/scenes/phone/
├── phone_scene.py       ⭐ Main Flask app
│   ├── routes           → /messages, /call, /gallery
│   ├── socketio events  → Real-time communication
│   └── initialization   → Setup database, assets
│
├── apps/                 📱 Feature Modules
│   ├── messages.py      → Messaging logic
│   └── gallery.py       → Photo management
│
├── static/               🎨 Frontend Assets
│   ├── css/
│   │   ├── phone.css    → Phone UI styling
│   │   ├── video_call.css
│   │   └── voice_call.css
│   ├── js/
│   │   ├── phone.js     → Phone interactions
│   │   ├── video.js     → Video call logic
│   │   └── voice.js     → Voice call logic
│   └── images/          → UI icons
│
└── templates/            📄 HTML Pages
    ├── phone_ui.html    → Main phone interface
    ├── video_call.html  → Video call page
    └── voice_call.html  → Voice call page
```

---

## 🔄 Data Flow Example: Sending a Message

```
User types message in phone UI
    ↓
frontend: phone.js → socketio.emit('send_message')
    ↓
backend: phone_scene.py → @socketio.on('send_message')
    ↓
simulation/database/db.py → save_message()
    ↓
simulation/database/rag.py → add_to_memory()
    ↓
content/simulation/character_system/character.py → generate_response()
    ↓
engine/tts/cosyvoice/ → generate_audio()
    ↓
engine/assets/manager.py → register_asset()
    ↓
socketio.emit('new_message') → frontend receives response
    ↓
UI updates with character's reply + audio
```

---

## 🎭 Character System Flow

```
Character Definition
    ↓
character_system/character.py
    ├── Basic Info (name, age, appearance)
    ├── Personality (via personality.py)
    │   ├── Traits (playful, caring, etc.)
    │   └── Communication style
    ├── Role (via role.py)
    │   ├── Relationship type
    │   └── Interaction patterns
    └── Memory (via rag.py)
        ├── Short-term (recent messages)
        └── Long-term (ChromaDB vectors)
```

**5 Pre-made Characters:**
1. Sophia - Bubbly, energetic, playful
2. Emma - Sweet, caring, gentle  
3. Isabella - Confident, flirty, mysterious
4. Olivia - Witty, sarcastic, loyal
5. Mia - Shy, thoughtful, creative

---

## 🎨 Asset System

Everything is tracked as an "Asset":

```
engine/assets/manager.py (AssetManager)
    ├── Images    → Photos, avatars, backgrounds
    ├── Audio     → Voice messages, TTS output
    ├── Video     → Video messages, calls
    ├── Text      → Messages, conversations
    └── Documents → Any file type

Storage: asset_registry.db (SQLite)
    ├── asset_id (UUID)
    ├── type (image/audio/video/text)
    ├── path (file location)
    ├── metadata (JSON)
    ├── created_at
    └── tags
```

---

## 🔧 Configuration System

```python
# Anywhere in the code:
from engine.config import get_config

config = get_config()

# Dot notation access:
port = config.get('scenes.phone.port')  # 5555
db_path = config.get('database.sqlite_path')  # "conversation_history.db"

# Environment override:
export PHONE_PORT=6000  # Overrides YAML
```

**Config Priority:**
1. Environment variables (highest)
2. environment-specific YAML (production.yaml)
3. default.yaml (lowest)

---

## 🚀 Deployment Options

### Option 1: Development (Current)
```bash
python launcher.py  # Run locally
```

### Option 2: Docker
```bash
docker-compose -f docker-compose.prod.yml up
# Runs all 5 services in containers
```

### Option 3: Systemd (Linux)
```bash
sudo systemctl start cosyvoice-hub
sudo systemctl start cosyvoice-phone
sudo systemctl start cosyvoice-bedroom
# Runs as background services
```

---

## 📝 Adding a New Scene (Example)

1. **Create scene file:**
   ```
   content/scenes/cafe/cafe_scene.py
   ```

2. **Inherit from base:**
   ```python
   from engine.scenes.base_scene import BaseScene
   
   class CafeScene(BaseScene):
       def __init__(self):
           super().__init__("cafe", port=5556)
   ```

3. **Add to config:**
   ```yaml
   # config/default.yaml
   scenes:
     cafe:
       port: 5556
       enabled: true
   ```

4. **Add to launcher:**
   ```python
   # launcher.py
   elif choice == "6":
       from content.scenes.cafe.cafe_scene import CafeScene
       scene = CafeScene()
       scene.run()
   ```

---

## 🎯 Key Principles

### Separation of Concerns
- **ENGINE** = Reusable tech (rarely change)
- **CONTENT** = Your story/game (change often)
- **CONFIG** = Settings (tune without code)

### Scene Independence
- Each scene is a standalone Flask app
- Can run individually or together
- Shared database for communication

### Asset Centralization
- Everything goes through AssetManager
- Single source of truth
- Easy to import/export

### Configuration Over Code
- Change ports, paths, settings in YAML
- No need to modify code for deployment
- Environment-specific overrides

---

## 🔍 Quick Reference

### Find a Scene:
```
content/scenes/{scene_name}/{scene_name}_scene.py
```

### Find Character Logic:
```
content/simulation/character_system/character.py
```

### Change a Port:
```
config/default.yaml → scenes.{scene_name}.port
```

### Add a Character:
```python
from content.simulation.character_system.character import Character
char = Character(name="Alice", personality=...)
```

### Register an Asset:
```python
from engine.assets import AssetManager
am = AssetManager()
asset_id = am.register_asset(type="image", path="photo.jpg")
```

---

## 💡 Summary

**Think of it like a game engine:**

- **ENGINE** = Unity/Unreal (the tech)
- **CONTENT** = Your game (characters, levels)
- **CONFIG** = Settings menu (resolution, controls)

**You work in CONTENT, use ENGINE, configure via CONFIG.**

---

Need help with any specific part? I can deep-dive into:
- Character creation
- Scene customization  
- Asset management
- Database queries
- Configuration options
- Adding new features
