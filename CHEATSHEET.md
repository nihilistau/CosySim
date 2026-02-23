# CosySim v3.1 — Quick Reference

## Launch

```bash
python launcher.py                  # Hub → http://localhost:8500
python launcher.py --mode phone     # Phone → http://localhost:5555
python launcher.py --mode realm     # The Realm → http://localhost:5562
python launcher.py --mode all       # Phone + Bedroom + Hub + TTS + Bridge
python launcher.py --status         # Service health check
python launcher.py --mode test      # Run 734 tests
```

## All Scenes & Ports

| Mode | Port | Type | Scene |
|------|------|------|-------|
| `phone` | 5555 | Flask | CosyPhone OS — messaging, selfies, voice |
| `bedroom` | 5556 | Flask | The Bedroom — multi-agent spatial |
| `lounge` | 5557 | Flask | The Velvet Lounge |
| `casino` | 5559 | Flask | Midnight Casino — blackjack, poker, slots |
| `gallery` | 5560 | Flask | The Gallery — art evaluation |
| `warzone` | 5561 | Flask | Global Strike — tactical combat |
| `realm` | 5562 | Flask | The Realm — LitRPG, dual-agent |
| `neoncity` | 5563 | Flask | NeonCity — cyberpunk strategy |
| `coders` | 5564 | Flask | The Coders Room — AI code sim |
| `hub` | 8500 | Streamlit | Central dashboard |
| `dashboard` | 8501 | Streamlit | System metrics |
| `admin` | 8502 | Streamlit | Admin panel (13 pages + GOD mode) |
| `assets` | 8503 | Streamlit | Asset generator |
| `creator` | 8504 | Streamlit | Scene scaffolding wizard |
| `tts` | 8600 | FastAPI | Qwen3-TTS voice server |
| `bridge` | 8601 | FastAPI | MCP web bridge |

**External:** LMStudio (1234), ComfyUI (8188)

## Directory Structure

```
engine/          ← Framework (stable, reusable)
  agents/        ← CharacterAgent, VirtualAgent, VirtualAgentManager, SceneAgent
  lmstudio/      ← LMSClient (v1 API), LMStudioManager, Conversation
  mcp/           ← MCPFramework, AgentGovernor, DialogSystem, GameSession
  skills/        ← @skill decorator, SKILL_REGISTRY, 7 core packs
  scenes/        ← BaseScene, get_active_scene()
  logging/       ← CosyLogger, @timed, SystemMonitor
content/         ← Game content (customize freely)
  scenes/        ← 9 Flask scenes + 5 Streamlit apps
  simulation/    ← Database, RAG, characters, media services
config/          ← YAML settings (tune without code)
tests/           ← 734 tests, 28 files
```

## Skill Packs

| Pack | Count | Scope |
|------|-------|-------|
| `memory` | 4 | search, store, chain summary |
| `character` | 4 | state, traits, mood, relationship |
| `comfyui` | 3 | image gen, portraits, workflows |
| `voice` | 2 | voice messages |
| `tts` | 4 | TTS gen, casting, presets |
| `social` | — | social interactions |
| `boards` | — | shared board mechanics |
| `realm` | 11 | inventory, stats, director, murder mystery |
| `neoncity` | 8 | movement, combat, hacking, storm |
| `coders` | 6 | features, pipeline, sandbox |

## Config

```python
from engine.config import get_config
config = get_config()
val = config.get("scenes.phone.port", 5555)
```

Config priority: env vars > production.yaml > default.yaml

## Tests

```bash
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
python -m pytest tests/test_realm.py -v        # Single file
python -m pytest tests/ -k "neoncity"          # Pattern match
```

## Media Drop Paths

```
content/simulation/media/images/   → .png .jpg .gif .webp
content/simulation/media/video/    → .mp4 .webm
content/simulation/media/voice/    → .wav .mp3
```

Then: `python launcher.py --housekeep`

## Key Docs

| Doc | What |
|-----|------|
| `AGENT_NOTES.md` | Complete system reference (2500+ lines) |
| `docs/SKILLS.md` | Skill authoring |
| `docs/LMSTUDIO.md` | LMStudio v1 API, MCP, streaming |
| `docs/MCP_FRAMEWORK.md` | MCP framework guide |
| `docs/API.md` | REST API reference |
| `CHANGELOG.md` | Version history |
