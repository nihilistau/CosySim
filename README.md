![CosySim Banner](https://svg-banners.vercel.app/api?type=origin&text1=CosySim&text2=AI%20Agent%20Simulation%20Framework&width=800&height=210)

# CosySim — AI Agent Simulation Framework v3.1

> **A local-first AI simulation platform with pluggable scenes, MCP-driven tool use, multi-agent orchestration, and media generation — all powered by LMStudio.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 699](https://img.shields.io/badge/tests-699%20passing-brightgreen.svg)]()

---

## What Is This?

An AI agent simulation framework where every scene is a self-contained Flask app with its own agents, state, and game logic — orchestrated through a **Model Context Protocol (MCP)** pipeline that gives the LLM tools, memory, governance rules, and real-time state management.

- **9 Flask scenes** — phone, bedroom, lounge, casino, gallery, warzone, realm, neoncity, coders
- **MCP pipeline** — agents use tool calls for memory, media generation, game mechanics, and state mutation
- **LMStudio v1 native API** — stateful conversations with `response_id` threading, SSE streaming, `store` control
- **Multi-agent** — VirtualAgentManager routes inference with governance interceptors, skill packs, and conversation branching
- **Media generation** — ComfyUI images/video, Qwen3-TTS voice, all wired as MCP tools

---

## Quick Start

```bash
# Install
cd CosySim
pip install -e .

# Launch (hub is the default entry point)
python launcher.py                # Hub → http://localhost:8500

# Or launch a specific scene
python launcher.py --mode phone   # Phone → http://localhost:5555
python launcher.py --mode realm   # The Realm → http://localhost:5562
```

**Prerequisites:** Python 3.10+, LMStudio running on port 1234 with a model loaded. ComfyUI (port 8188) optional for image generation.

---

## Scenes

### Flask Scenes (interactive)

| Scene | Port | Mode | Description |
|-------|------|------|-------------|
| **Phone** | 5555 | `phone` | Messaging app with mood/arousal engine, selfies, voice messages |
| **Bedroom** | 5556 | `bedroom` | Multi-agent spatial environment, 7 locations, tick-based agent loop |
| **Lounge** | 5557 | `lounge` | Social scene with ambient characters |
| **Casino** | 5559 | `casino` | Blackjack, poker, slots with MCP game sessions |
| **Gallery** | 5560 | `gallery` | Art evaluation, structured critique, image generation |
| **Warzone** | 5561 | `warzone` | Turn-based tactical combat |
| **Realm** | 5562 | `realm` | Director-guided LitRPG with dual-agent orchestration |
| **NeonCity** | 5563 | `neoncity` | Cyberpunk strategy board game with procedural city |
| **Coders** | 5564 | `coders` | AI agent idle sim — agents write real code in sandboxed Python |

### Streamlit Apps (management)

| App | Port | Mode | Description |
|-----|------|------|-------------|
| **Hub** | 8500 | `hub` | Landing page, service health, scene launcher |
| **Dashboard** | 8501 | `dashboard` | System metrics overview |
| **Admin** | 8502 | `admin` | 13-page diagnostic center with GOD mode |
| **Assets** | 8503 | `assets` | Asset generator |
| **Creator** | 8504 | `creator` | Scene scaffolding wizard |

### Services

| Service | Port | Mode | Description |
|---------|------|------|-------------|
| **TTS** | 8600 | `tts` | Qwen3-TTS voice generation (FastAPI + MCP) |
| **Bridge** | 8601 | `bridge` | MCP web bridge (SSE proxy, file upload) |

```bash
python launcher.py --mode all      # Launch phone + bedroom + hub + tts + bridge
python launcher.py --status        # Check service health
python launcher.py --mode test     # Run 699 tests
```

---

## Architecture

```
engine/                    # Reusable framework (stable)
├── agents/               # CharacterAgent, SceneAgent, VirtualAgent, VirtualAgentManager
├── lmstudio/             # LMSClient (v1 native API), LMStudioManager (model lifecycle)
│   └── conversation.py   # Stateful threading: response_id, branching, fork
├── mcp/                  # MCP Framework (governance, dialog, state, game sessions)
│   ├── framework.py      # MCPFramework, MCPSceneMixin, MCPCharacterNode
│   ├── governance.py     # AgentGovernor, InterceptorPipeline
│   ├── dialog.py         # DialogSystem, DialogTree, ConversationState
│   ├── game_mcp.py       # MCPGameSession, MCPGameNode, rules engine
│   ├── cosysim_server.py # FastMCP server (9 tools + 5 resources)
│   └── skills_server.py  # MCP skills server for ephemeral tool exposure
├── skills/               # @skill decorator, SKILL_REGISTRY, pack system
│   └── builtin/          # 7 core packs: memory, character, comfyui, voice, tts, social, boards
├── scenes/               # BaseScene, SceneRegistry, get_active_scene()
├── logging/              # CosyLogger, @timed, BenchmarkStore, SystemMonitor
├── services/             # @retry, CircuitBreaker
├── spatial/              # Location, SceneMap
├── media/                # MediaConfig (image/video/audio standards)
└── tts/                  # Qwen3-TTS server + VoiceDesigner

content/                   # Game content (customize freely)
├── scenes/               # 9 Flask scenes + 5 Streamlit apps
│   ├── phone/            # + apps/, static/, templates/
│   ├── realm/            # + realm_skills.py (11 MCP skills)
│   ├── neoncity/         # + neoncity_skills.py (8 MCP skills)
│   ├── coders/           # + coders_skills.py (6 MCP skills)
│   └── ...
└── simulation/           # Database, RAG, character system, media services

config/                    # YAML configuration (tune without code)
tests/                     # 699 tests across 27 files
```

---

## MCP Pipeline

The core innovation: agents don't just generate text — they call **tools** during inference via LMStudio's MCP integration.

```
User message → AgentGovernor → InterceptorPipeline → VirtualAgentManager
  → LMSClient.chat_stateful(messages, tools=[...])
    → LMStudio /api/v1/chat (SSE stream)
      → LMStudio calls MCP tool: search_memory("birthday")
        → CosySim skill → ChromaDB → result
      → LMStudio generates response using tool result
    ← StreamProcessor extracts [MOOD:], [IMAGE:], [ACTION:] tags
  → AgentGovernor post-call interceptors (mood sync, stat updates)
← Response to UI
```

**Key features:**
- **Stateful conversations** — `response_id` + `previous_response_id` for server-side KV cache reuse
- **Governance** — interceptors can modify prompts, block responses, inject context pre/post inference
- **Streaming** — real-time SSE with inline tag extraction and stat updates
- **Tool calls** — skills execute as Python functions, results fed back to the LLM mid-turn

---

## Skill Packs

| Pack | Skills | Scope |
|------|--------|-------|
| `memory` | search_memory, store_memory, get_event_chain_summary, summarize_chain | Core |
| `character` | get_character_state, adjust_trait, set_mood, adjust_relationship | Core |
| `comfyui` | generate_image, generate_character_portrait, list_comfyui_workflows | Core |
| `voice` | generate_voice_message, list_voice_messages | Core |
| `tts` | generate_voice_message, cast_voice, list_voice_presets, list_voicemails | Core |
| `social` | Social interaction skills | Core |
| `boards` | Shared board game mechanics | Core |
| `realm` | 11 skills: inventory, stats, skill checks, director, murder mystery | Scene |
| `neoncity` | 8 skills: movement, combat, hacking, storm, events | Scene |
| `coders` | 6 skills: feature queue, pipeline, sandbox execution | Scene |

```python
from engine.skills import skill, SkillCategory

@skill(pack="my_pack", tags=["custom"], category=SkillCategory.GAME, cooldown=5.0)
def my_tool(param: str) -> str:
    """Do something useful."""
    return f"Result: {param}"
```

---

## Testing

```bash
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
# 699 tests passing
```

---

## Configuration

Edit `config/default.yaml` or use environment variables:

```yaml
lmstudio:
  host: "127.0.0.1"
  port: 1234
  api_version: "v1"
  mcp_enabled: true

scenes:
  phone: { port: 5555 }
  bedroom: { port: 5556 }
  realm: { port: 5562 }
  # ...
```

```python
from engine.config import get_config
config = get_config()
port = config.get("scenes.phone.port", 5555)
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [`AGENT_NOTES.md`](AGENT_NOTES.md) | Comprehensive system reference (2500+ lines) |
| [`QUICK_START.md`](QUICK_START.md) | 5-minute setup guide |
| [`CHEATSHEET.md`](CHEATSHEET.md) | Quick reference card |
| [`docs/SKILLS.md`](docs/SKILLS.md) | Skill authoring guide |
| [`docs/LMSTUDIO.md`](docs/LMSTUDIO.md) | LMStudio integration (v1 API, MCP, streaming) |
| [`docs/THREE_PILLARS.md`](docs/THREE_PILLARS.md) | Architecture overview |
| [`docs/API.md`](docs/API.md) | REST API reference |
| [`docs/TTS.md`](docs/TTS.md) | Voice generation & voice designer |
| [`docs/STRUCTURE_GUIDE.md`](docs/STRUCTURE_GUIDE.md) | Project structure walkthrough |
| [`docs/MCP_FRAMEWORK.md`](docs/MCP_FRAMEWORK.md) | MCP framework developer guide |
| [`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) | MCP architecture deep dive |
| [`CHANGELOG.md`](CHANGELOG.md) | Full version history |

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center"><strong>Built with ❤️ — GodSpeed! 🚀</strong></p>
