# CosySim Project Structure — v3.1

## Three-Layer Architecture

```
engine/     ← Reusable framework (stable tech layer)
content/    ← Game content (scenes, characters, simulation logic)
config/     ← YAML settings (tune without code changes)
```

---

## engine/ — The Framework

```
engine/
├── __init__.py              # Top-level exports (get_config, BaseScene, etc.)
│
├── agents/                  # Agent Framework
│   ├── character_agent.py   # CharacterAgent — persona + RAG + skills + MCP
│   ├── scene_agent.py       # SceneAgent — one-shot tasks (title, summarize, classify)
│   ├── virtual_agent.py     # VirtualAgent — state container + inference request building
│   ├── virtual_agent_manager.py  # VirtualAgentManager — inference router + conversation mgr
│   ├── agent_loop.py        # Tick-based perceive→decide→execute loop
│   ├── stream_processor.py  # StreamProcessor — real-time tag extraction from SSE
│   ├── content_router.py    # Response routing to appropriate handlers
│   ├── evaluator.py         # Post-inference quality evaluation
│   ├── interceptors.py      # Built-in interceptor implementations
│   └── protocols.py         # IAgent protocol, type definitions
│
├── lmstudio/                # LMStudio Integration
│   ├── client.py            # LMStudioManager — model lifecycle (load/unload/VRAM)
│   ├── lms_client.py        # LMSClient — v1 native API (/api/v1/chat), SSE streaming
│   └── conversation.py      # Conversation — stateful threading, branching, fork
│
├── mcp/                     # MCP Framework (Model Context Protocol)
│   ├── framework.py         # MCPFramework, MCPSceneMixin, MCPCharacterNode, MCPSceneNode
│   ├── dialog_system.py     # DialogSystem, DialogTree, ConversationState, SpeechEnhancer
│   ├── scene_state.py       # SceneStateManager, NarrativeLog
│   ├── game_mcp.py          # MCPGameSession, MCPGameNode, GameSessionInterceptor
│   ├── scene_rules_engine.py # SceneRulesEngine, PermissionMatrix, ConversationHeat
│   ├── interaction_trees.py # InteractionTrees
│   ├── character_registry.py # CharacterProfile, CharacterState
│   ├── comms_framework.py   # SceneManifest, SkillManifest
│   ├── shared_boards.py     # SharedBoardManager
│   ├── state_coordinator.py # CharacterStateCoordinator
│   ├── tag_registry.py      # TagRegistry, TagDef, TagMatch
│   ├── cosysim_server.py    # FastMCP server (9 tools + 5 resources)
│   ├── skills_server.py     # MCP skills server for ephemeral tool exposure
│   └── web_bridge.py        # FastAPI bridge (SSE proxy, CORS, file upload)
│
├── skills/                  # Skill System
│   ├── skill.py             # @skill decorator, SkillCategory enum
│   ├── registry.py          # SKILL_REGISTRY, get_pack_tools(), mcp_skill_pack()
│   ├── chain_context.py     # Thread-local chain_id propagation
│   └── builtin/             # Core skill packs
│       ├── memory_skills.py     # search_memory, store_memory, chain summary
│       ├── character_skills.py  # get_state, adjust_trait, set_mood, adjust_relationship
│       ├── comfyui_skills.py    # generate_image, portraits, workflows
│       ├── voice_skills.py      # voice messages
│       ├── tts_skills.py        # TTS generation, casting, presets
│       ├── social_skills.py     # social interactions
│       └── board_skills.py      # shared board game mechanics
│
├── scenes/                  # Scene Framework
│   ├── base_scene.py        # BaseScene + _ACTIVE_SCENES + get_active_scene()
│   ├── scene_manager.py     # Scene lifecycle management
│   └── scene_registry.py    # Auto-discover BaseScene subclasses
│
├── assets/                  # Asset Management
│   ├── manager.py           # AssetManager — central registry
│   ├── types.py             # Asset type definitions
│   └── base.py              # Base asset classes
│
├── config.py                # Config system (dot-notation, env overrides)
├── config_validator.py      # Schema-based config validation
├── paths.py                 # Project path resolution
│
├── logging/                 # Observability
│   ├── cosy_logger.py       # Ring-buffer logger with install_logger()
│   ├── benchmark.py         # @timed decorator, BenchmarkStore
│   └── monitor.py           # SystemMonitor (CPU/RAM/GPU/services)
│
├── media/                   # Media Standards
│   └── media_config.py      # MediaConfig singleton from YAML
│
├── spatial/                 # Spatial System
│   ├── location.py          # Location dataclass (capacity, properties)
│   └── scene_map.py         # SceneMap (place, move, nearby, interact)
│
├── services/                # Infrastructure
│   └── resilience.py        # @retry, CircuitBreaker
│
├── tts/                     # Voice Generation
│   ├── qwen3_server.py      # FastAPI + FastMCP TTS server
│   └── voice_designer.py    # VoiceDesign, CASTING_OFFICE, presets
│
├── deployment/              # Deployment configs (runtime/)
├── observability/           # Metrics, alerts, training capture
├── overlay/                 # UI overlay blueprint
├── pipeline/                # Inference pipeline (token routing, kill switch)
├── testing/                 # Testing framework
└── third_party/             # Third-party libs (Matcha-TTS)
```

---

## content/ — Game Content

```
content/
├── scenes/                  # Scene Implementations
│   │
│   ├── phone/               # Port 5555 — CosyPhone OS
│   │   ├── phone_scene.py   # Flask app, messaging, mood/arousal engine
│   │   ├── apps/            # messages.py, gallery.py, voice_studio.py
│   │   ├── static/          # CSS, JS, images
│   │   └── templates/       # phone_ui.html, video_call.html, voice_call.html
│   │
│   ├── bedroom/             # Port 5556 — Multi-agent spatial
│   │   ├── bedroom_scene.py # 2-character AgentLoop, 7 locations
│   │   ├── static/          # CSS, JS, audio, images
│   │   └── templates/       # bedroom.html
│   │
│   ├── lounge/              # Port 5557 — The Velvet Lounge
│   ├── casino/              # Port 5559 — Midnight Casino
│   ├── gallery/             # Port 5560 — Art evaluation
│   ├── warzone/             # Port 5561 — Tactical combat
│   │
│   ├── realm/               # Port 5562 — The Realm (LitRPG)
│   │   ├── realm_scene.py   # Dual-agent (Director + Assistant)
│   │   ├── realm_state.py   # Inventory, stats, murder mystery
│   │   ├── realm_skills.py  # 11 MCP skills
│   │   └── templates/       # realm.html
│   │
│   ├── neoncity/            # Port 5563 — NeonCity
│   │   ├── neoncity_scene.py    # Cyberpunk strategy board
│   │   ├── neoncity_state.py    # Grid, players, storm, prefabs
│   │   ├── neoncity_skills.py   # 8 MCP skills
│   │   └── templates/           # neoncity.html
│   │
│   ├── coders/              # Port 5564 — The Coders Room
│   │   ├── coders_scene.py  # AI agent code simulation
│   │   ├── coders_state.py  # Pipeline, sandbox, feature queue
│   │   ├── coders_skills.py # 6 MCP skills
│   │   └── templates/       # coders.html
│   │
│   ├── heist/               # Port 5565 — Heist
│   │   ├── heist_scene.py   # HeistScene
│   │   ├── heist_game.py    # Heist game logic
│   │   ├── heist_rules.py   # Heist rules
│   │   ├── heist_skills.py  # MCP skills
│   │   └── templates/       # heist.html
│   │
│   ├── command_center/      # Port 5566 — Command Center
│   │   ├── command_center_scene.py  # CommandCenterScene
│   │   └── templates/       # command_center.html
│   │
│   ├── hub/                 # Port 8500 — Central dashboard (Streamlit)
│   ├── dashboard/           # Port 8501 — Metrics (Streamlit)
│   ├── admin/               # Port 8502 — Admin panel (Streamlit, 13 pages)
│   ├── assets/              # Port 8503 — Asset generator (Streamlit)
│   ├── games/               # Shared game utilities
│   └── media/               # Media utilities
│
├── shared/                  # Shared Streamlit theme
│
└── simulation/              # Simulation Engine
    ├── character_system/    # Character, Personality, Role
    ├── database/            # db.py (SQLite), rag.py (ChromaDB), events.py (EventChain)
    └── services/            # ComfyUI client, media gen, voice/video services
```

---

## config/ — Settings

```
config/
├── default.yaml       # Base configuration (ports, paths, LMStudio, ComfyUI)
├── development.yaml   # Dev overrides (debug mode)
├── production.yaml    # Production overrides
└── voices.yaml        # Character voice designs
```

---

## docs/ — Documentation

```
docs/
├── ProjectNext/             # Future project planning
├── STRUCTURE_GUIDE.md       # This file
├── MCP_ARCHITECTURE.md      # MCP design & protocol docs
├── AGENTS_GUIDE.md          # Agent system guide
├── SKILLS.md                # Skill system reference
└── ...                      # API, logging, TTS, admin guides
```

---

## Adding a New Scene

1. Create directory: `content/scenes/myScene/`
2. Create scene file inheriting BaseScene:

```python
from engine.scenes.base_scene import BaseScene

class MyScene(BaseScene):
    def __init__(self):
        super().__init__("myScene", port=5570)
        # register routes, init state...
```

3. Add to `config/default.yaml`:
```yaml
scenes:
  myScene:
    port: 5570
    enabled: true
```

4. Add to `launcher.py` mode dispatch
5. Optionally add scene-specific skills in `myScene_skills.py`
6. Import skills in `__init__.py` for auto-registration

---

## Data Flow: User Message → Agent Response

```
User types message in scene UI
  → Flask route POST /api/chat
    → AgentGovernor pre-call interceptors (inject context, enforce rules)
      → VirtualAgentManager.infer()
        → ConversationManager: get/create Conversation
        → LMSClient.chat_stateful(messages, tools=[skill_pack_tools])
          → LMStudio /api/v1/chat (SSE stream)
            → LMStudio calls MCP tool: search_memory(...)
              → CosySim skill → result
            → LMStudio generates response
          ← StreamProcessor: extract [MOOD:], [IMAGE:], [ACTION:] tags
        → ProcessedResponse with clean_text, mood_tags, tool_calls
      → AgentGovernor post-call interceptors (mood sync, stat updates)
    ← Response JSON
  ← UI renders reply
```
