# CosySim — Onboarding & System Guide

## What Is CosySim?

CosySim is an AI agent simulation framework built on **three pillars**:

| Pillar | Purpose | Port |
|--------|---------|------|
| **CosySim Engine** | Agent framework, skills, events, database, scenes | Various |
| **LMStudio** | Local LLM inference, MCP tool host | :1234 |
| **ComfyUI** | Image/video generation via diffusion workflows | :8188 |

The framework orchestrates the other two — agents use LMStudio for thinking and ComfyUI for creating media.

---

## Quick Start

```powershell
# 1. Install
pip install -e .

# 2. Start external services
#    - LMStudio on :1234 (load a model like qwen3-4b)
#    - ComfyUI on :8188

# 3. Launch everything in one terminal
python launcher.py --mode all

# Or launch individual scenes:
python launcher.py --mode phone      # Phone scene on :5555
python launcher.py --mode bedroom    # Bedroom scene on :5556
python launcher.py --mode hub        # Hub dashboard on :8500
python launcher.py --mode admin      # Admin panel on :8502
python launcher.py --mode tts        # TTS server on :8600
python launcher.py --mode bridge     # MCP bridge on :8601
```

---

## Architecture Overview

```
CosySim/
├── engine/                    # Core framework (reusable)
│   ├── agents/                # CharacterAgent, AgentLoop, perception
│   ├── skills/                # Chat, voice, image, spatial skills
│   ├── services/              # Resilience, housekeeping
│   ├── tts/                   # Qwen3-TTS server + voice designer + audio processor
│   ├── lmstudio/              # LMStudio client v2 (REST + streaming)
│   ├── mcp/                   # MCP server + web bridge
│   ├── media/                 # MediaConfig standards
│   ├── spatial/               # 2D spatial system for multi-agent scenes
│   ├── logging/               # Structured logging + benchmarks
│   └── config.py              # YAML config loader
│
├── content/                   # Content layer (your scenes + data)
│   ├── scenes/                # All playable scenes
│   │   ├── phone/             # Phone companion (Flask + SocketIO)
│   │   ├── bedroom/           # Multi-agent bedroom (Flask + SocketIO)
│   │   ├── hub/               # Central hub (Streamlit)
│   │   ├── admin/             # Admin panel (Streamlit)
│   │   ├── dashboard/         # KPI dashboard (Streamlit)
│   │   └── assets/            # Asset generator (Streamlit)
│   ├── simulation/            # Simulation services + database
│   │   ├── database/          # SQLite DB, EventChain, migrations
│   │   ├── services/          # MediaGenerator, ComfyUI client
│   │   └── media/             # Generated media files
│   └── characters/            # Character definitions + RAG data
│
├── config/                    # Configuration files
│   └── default.yaml           # Master config (ports, models, thresholds)
│
├── tests/                     # 315+ tests
└── docs/                      # Documentation
```

---

## Scenes

### Phone Scene (:5555)
A companion chat app with:
- Real-time messaging via WebSocket
- Photo sharing (selfies, gallery)
- Voice messages (TTS generation)
- Video messages
- Voice Studio app (voice design, batch generation)
- Image Settings (ComfyUI workflow tuning)
- Autonomous messaging (agent sends messages on its own)

### Bedroom Scene (:5556)
Multi-agent spatial simulation:
- 2 AI characters in a shared 3D room
- 7 locations (bed, couch, bar, bathroom, balcony, vanity, doorway)
- Tick-based agent loop (perceive → decide → act)
- Characters move, interact, respond to environment
- Per-agent model selection (choose different LMStudio models per character)
- Ambient audio system (drop tracks in `content/scenes/bedroom/static/audio/`)
- 😈 Menace Menu — god-mode pranks that agents perceive and react to

### Hub (:8500)
Central dashboard showing:
- Three Pillars status (CosySim, LMStudio, ComfyUI)
- Scene cards for launching
- System health overview

### Admin Panel (:8502)
12-page modular admin with:
- GOD mode (full override)
- RAG editor
- EventChain browser
- Config editor
- Character manager

---

## Media Pipeline

### Image Generation
1. Agent decides to send a photo
2. `MediaGenerator.generate_selfie()` builds a prompt via `PromptBuilder`
3. `ComfyUIClient.generate_image()` sends workflow to ComfyUI API
4. ComfyUI generates the image using SDXL / loaded model
5. Image saved to `content/simulation/media/images/`
6. Registered in gallery DB with UUID

### Voice Generation
1. Text is sent to TTS server (:8600)
2. `Qwen3TTSEngine.generate()` processes text
3. Model selection: `auto` (length-based), `0.6b`, `1.7b`, or `escalate`
4. Audio post-processing: trim silence, normalize, fade in/out
5. WAV saved to `content/simulation/media/voice/`
6. Logged to EventChain

### Multi-Model Escalation (`model_size: "escalate"`)
- **0.6B Scout**: Fast model generates first take
- **Quality Check**: Energy + spectral analysis scores the output
- **1.7B Actor**: If score < 0.75, escalates to higher-quality model
- Best of both worlds: speed for easy lines, quality for complex ones

---

## Adding Your Own Media

### Drop Files Into Folders
Place media files directly into:
```
content/simulation/media/images/   → .png, .jpg, .jpeg, .gif, .webp
content/simulation/media/video/    → .mp4, .webm, .avi, .mov
content/simulation/media/voice/    → .wav, .mp3, .ogg, .flac
```

### Register With Housekeeping
```powershell
# Run once — scans folders, registers new files in DB + EventChain
python launcher.py --housekeep

# Run continuously (checks every 60s)
python launcher.py --housekeep --watch
```

Housekeeping also:
- Checks all service health (LMStudio, ComfyUI, TTS, MCP)
- Finds orphan DB records (files deleted from disk)
- Finds unregistered files (no DB entry)
- Cleans stale cache files

---

## Configuration

All settings live in `config/default.yaml`:

```yaml
# Service URLs
lmstudio:
  base_url: "http://localhost:1234"

comfyui:
  base_url: "http://127.0.0.1:8188"
  generation:
    steps: 20
    cfg: 7.0
    sampler_name: "euler"
    scheduler: "normal"
    denoise: 1.0

tts:
  base_url: "http://localhost:8600"

# Media standards
media_standards:
  image:
    width: 512
    height: 768
```

### Image Generation Settings
Adjustable at runtime via the Phone Scene → Image Settings app:
- Steps, CFG scale, sampler, scheduler, denoise strength
- Model selection (auto-detected from ComfyUI)
- Width / height

### Voice Settings
Set per-character via Voice Studio or `config/voices.yaml`:
- Voice design description (triggers model features)
- Model size (0.6b / 1.7b)
- Reference audio (for zero-shot cloning)
- Tags for organization

---

## EventChain — The Audit Trail

**If it's not in EventChain, it didn't happen.**

Every interaction gets a `chain_id` and causal tree:
```python
from content.simulation.database.events import EventChain

ec = EventChain()
ec.log(
    event_type="message_sent",
    actor="user",
    payload={"text": "Hello!"},
    summary="User sent greeting",
    chain_id="conv_abc123",
    character_id="luna",
)
```

Browse the chain in the Admin Panel → Chain Browser.

---

## Creating a New Scene

Use the Scene Creator wizard:
```powershell
python launcher.py --mode creator
```

Or manually:
1. Create `content/scenes/myscene/`
2. Add `myscene.py` with a class that has a `start()` method
3. For Flask scenes: inherit patterns from `phone_scene.py`
4. For Streamlit scenes: standard Streamlit script
5. Register in `launcher.py` mode_map

Templates available: chat, exploration, management, creative.

---

## Voice Studio

The Voice Studio phone app lets you:

### Create Voice Designs
- Name + description (the acoustic instruction for Qwen3-TTS)
- Select model size (0.6b fast / 1.7b quality)
- Tag for organization

### Premade Voices
8 ready-to-use voices: Luna Flirty, Maya Whisper, Commander, AI Mother, Hacker Girl, Smooth Narrator, Seductive Whisper, Energetic Youth.

### Batch Generation
Process scripts in format:
```
CHARACTER (emotion): "Dialogue text here"
NARRATOR: "Description or narration"
```

### Zero-Shot Cloning
Upload a WAV reference → model matches that voice's characteristics.

---

## Batch / Long-Form Audio (Books)

For generating 10+ minute audio or entire books:

### Via TTS API
```python
import requests

# Build your script as lines
lines = [
    {"text": "Chapter 1. The ship drifted through the void.",
     "voice_design": "Deep narrator", "model_size": "1.7b"},
    {"text": "Warning: hull breach detected.",
     "voice_design": "Clinical female AI", "model_size": "0.6b"},
]

response = requests.post("http://localhost:8600/batch", json={
    "lines": lines,
    "stitch": True,      # Combine all clips into one WAV
    "gap_ms": 150,        # Silence between clips
    "post_process": True, # Trim + normalize + fade
})
print(response.json())
# Returns: batch_id, stitched file download URL, per-clip results
```

### Via Voice Studio
1. Open Voice Studio → Batch tab
2. Paste your script
3. Select voice designs per character
4. Generate → all clips created and downloadable

---

## Extending the System

### Adding a Skill
```python
# engine/skills/my_skill.py
from engine.skills.base import BaseSkill

class MySkill(BaseSkill):
    name = "my_skill"

    def execute(self, context: dict) -> str:
        # Your logic here
        return "Result string"
```

### Adding a Character
Edit `content/characters/` or use Admin Panel → Character Manager.

### Adding Voice Presets
Edit `engine/tts/voice_designer.py` VOICE_PRESETS dict or use Voice Studio.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ComfyUI not connecting | Check it's running on :8188, try `curl http://127.0.0.1:8188/system_stats` |
| LMStudio not responding | Ensure a model is loaded, check :1234 |
| TTS in placeholder mode | Normal if Qwen3-TTS models not in `pretrained_models/` |
| Images not displaying | Check `content/simulation/media/images/` has files |
| Voice download 404 | Run housekeeping to register files |
| DB errors | Run `python launcher.py --init-db` |

### Health Check
```powershell
python launcher.py --housekeep
# Shows status of all services + DB integrity
```

---

## Key Design Principles

1. **Three Pillars** — CosySim + LMStudio + ComfyUI. Framework orchestrates, doesn't replace.
2. **EventChain is truth** — Every interaction gets chain_id + causal tree.
3. **Skills are the interface** — Agents → skills → services.
4. **Graceful degradation** — Every external service has placeholder/offline mode.
5. **Config over code** — Ports, URLs, models, thresholds — all in YAML.
6. **Framework ≠ content** — Engine is reusable. Scenes are examples.
7. **Media standards enforced** — MediaConfig dimensions for all generated media.
8. **Voice has character** — Every character has a voice design. Consistency matters.
