# CosySim Architecture Guide

> v0.91b "THE EVOLUTION" — 262 engine modules, 20 scenes, 10 subsystems, ~85k lines.
> This document covers the full system architecture from config through engine to content.

---

## System Overview

CosySim is a multi-scene AI simulation framework where every NPC is an LLM-powered
agent governed by a full interceptor pipeline, skill system, and state coordination
layer. The system operates across 10 logical domains backed by a persistent
knowledge layer (Nexus) and local inference (LMStudio).

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CONFIG LAYER                                   │
│  default.yaml · development.yaml · production.yaml · voices.yaml         │
│  skill_manifests.yaml · mcp.json · lmlink.yaml · nlm_rpcids.yaml        │
│  nlm_notebooks.yaml                                                      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ reads
┌───────────────────────────────▼──────────────────────────────────────────┐
│                           ENGINE LAYER (262 files)                        │
│                                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │  nexus/ (85)  │ │integrations/ │ │   mcp/ (23)  │ │lmstudio/ (23)│    │
│  │ Knowledge     │ │   (25)       │ │ Governance   │ │ Inference    │    │
│  │ Q&A router    │ │ Google accts │ │ Dialog       │ │ ServerCtrl   │    │
│  │ Copilot sync  │ │ NLM client   │ │ State coord  │ │ LMLink       │    │
│  │ Scheduling    │ │ Colab/Drive  │ │ 42 tool mods │ │ Fine-tuning  │    │
│  │ Training fly  │ │ Compute rtr  │ │ Rules engine │ │ TaskQueue    │    │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
│                                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │ skills/ (46) │ │ agents/ (17) │ │ scenes/ (6)  │ │services/ (6) │    │
│  │ 31 packs     │ │ VirtualAgent │ │ BaseScene    │ │ EventBus     │    │
│  │ 278 skills   │ │ Governor     │ │ StateManager │ │ Announcer    │    │
│  │ @skill deco  │ │ 30+ intrcptr │ │ SceneRules   │ │ TTS          │    │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
│                                                                           │
│  ┌──────────────┐                                                        │
│  │  root (7)    │  port_registry · control_plane_registry · config       │
│  └──────────────┘  system_registry · paths                               │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ subclasses / uses
┌───────────────────────────────▼──────────────────────────────────────────┐
│                          CONTENT LAYER                                    │
│                                                                           │
│  ┌─────────────────────────────┐  ┌──────────────────────────────────┐   │
│  │  scenes/ (20 Flask scenes)   │  │  simulation/                     │   │
│  │  11 game · 6 utility · 3 svc │  │  character_system/ (Personality) │   │
│  │  Each: *_scene.py, templates │  │  database/ (SQLite, RAG, Events) │   │
│  │  static/, optional skills    │  │  services/ (ComfyUI, media)      │   │
│  └─────────────────────────────┘  └──────────────────────────────────┘   │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐│
│  │  shared/ — navbar_v2, HUD, portrait overlay, particles, animations  ││
│  └──────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘
```

### 10 Logical Domains

The system is organized into 10 canonical domains (defined in `engine/system_registry.py`):

| # | Domain | Purpose |
|---|--------|---------|
| 1 | **Control Plane** | Launcher, port registry, health surfaces, operator panels |
| 2 | **Copilot / Assistant** | CLI rules, hooks, agents, self-config, session logger |
| 3 | **Nexus** | Knowledge/rules/history backbone, mandatory first-query layer |
| 4 | **LMStudio / Agents** | Local inference, routing, fine-tuning, benchmarking |
| 5 | **MCP / Skills / Communication** | Tools, governance, interceptors, skill registry |
| 6 | **Services / Integrations** | TTS, EventBus, bridges, external APIs |
| 7 | **Google Research Layer** | NotebookLM, AI Studio, Colab, Gemini, Drive |
| 8 | **Scenes** | Game logic, GUIs, simulations, evaluation harnesses |
| 9 | **Home Assistant / Device** | HA integration, automations (planned) |
| 10 | **ARGUS / Browser Control** | Playwright, CDP, vision, capture, browser automation |

**Principle:** Engine is reusable framework. Content is swappable. Config tunes without code.

---

## Engine Subsystem Map

Every Python file lives under one of these directories. The counts are current
as of v0.91b.

| Subsystem | Files | Purpose |
|-----------|-------|---------|
| `engine/nexus/` | 91 | Knowledge backbone, Q&A router, Copilot sync, scheduling, training flywheel |
| `engine/skills/builtin/` | 46 | 45 builtin skill packs + registry init |
| `engine/mcp/tools/` | 43 | Domain-specific MCP tool modules |
| `engine/agents/interceptors/` | 28 | 27 interceptors + auto-discovery init |
| `engine/integrations/` | 25 | Google accounts, NLM client, Colab, Drive, compute router |
| `engine/mcp/` (core) | 23 | MCP framework, governance, dialog, state coordinator, rules engine |
| `engine/lmstudio/` | 23 | LMSClient, ServerController, LMLink, TaskQueue, fine-tuning |
| `engine/agents/` (root) | 17 | VirtualAgent, AgentGovernor, StreamProcessor, evaluators |
| `engine/asset_studio/` | 16 | Workflow builder, tuning engine, 8 content generators |
| `engine/world/` | 12 | WorldSim, PlayerState, city map, missions, crew, inventory |
| `engine/tts/` | 8 | Qwen3 TTS, Orpheus native, voice profiles |
| `engine/` (root) | 7 | config, port_registry, control_plane_registry, system_registry |
| `engine/scenes/` | 6 | BaseScene, SceneManager, NexusMixin, SceneRulesEngine |
| `engine/services/` | 6 | ActivityBus, world announcer, hack engine, housekeeping |
| `engine/pipeline/` | 6 | VirtualPipeline, StreamWatcher, KillSwitch, TokenRouter |
| `engine/content/` | 6 | ContentEngine, ContentGate, NLM generator |
| `engine/characters/` | 4 | CharacterMemory, reputation, player profile |
| `engine/events/` | 3 | EventBus, cross-scene relay |
| `engine/art/` | 3 | SceneArt, portrait cache |
| `engine/mechanics/` | 3 | ConsequenceStore, InvestigationBoard |
| `engine/economy/` | 2 | EconomyManager |
| `engine/arena/` | 2 | ArenaEngine |
| `engine/director/` | 2 | SceneDirector, narrative orchestration |
| `engine/api/` | 2 | Canvas API, REST bridge |
| **Total** | **386** | All engine subsystems |

Supporting top-level directories outside `engine/`:

| Directory | Files | Purpose |
|-----------|-------|---------|
| `training/` | 31 | Model zoo, dataset generators, finetune orchestrator, benchmarks |
| `scripts/argus/` | 18+ | Browser automation, CDP bridge, decoders, explorer |
| `content/scenes/` | 20 dirs | Flask BaseScene subclasses with templates and static assets |
| `tests/` | 315+ | pytest suite (9,577 passing) |

---

## Nexus — Knowledge Backbone

`engine/nexus/` — **91 files**

Nexus is the mandatory knowledge layer. Every agent queries Nexus first and
stores discoveries back. The system operates on a Nexus-first principle: if the
answer exists in Nexus, use it; if you found it elsewhere, write it back.

### Core Modules

| Module | Purpose |
|--------|---------|
| `client.py` | NexusClient — CRUD for entries, Q&A, rules, search, sessions |
| `query_router.py` | NexusQueryRouter — 5-tier pipeline: Q&A cache → FTS5 → Nexus ask → NLM → LMStudio |
| `bridge.py` | CLI bridge — `python -m engine.nexus.bridge search/ask/store/backfill/inventory` |
| `scheduler_daemon.py` | 55 recurring tasks — maintenance, training, news, copilot sync, world ticks |
| `task_scheduler.py` | AgentTask tracking — template-based and generated tasks for agents |
| `training_flywheel.py` | Collects Q&A, NLM turns, tool calls → fine-tuning datasets |
| `knowledge_capture.py` | Reusable helper — stores entry + matching Q&A pair together |
| `action_manifest.py` | Converts pre-plan Q&A into structured, dependency-aware action steps |

### Copilot Integration

| Module | Purpose |
|--------|---------|
| `copilot_bridge.py` | Session start/end — pulls task context, operator directives, resume handoff |
| `copilot_self_config.py` | Synchronizes repo instructions/agents/hooks with Nexus mirrors |
| `copilot_validation.py` | Validates Nexus mirror drift, hook integrity, runtime health |
| `seed_copilot_rules.py` | Refreshes Copilot/doc mirrors in Nexus, deduplicates stale entries |
| `nexus_session_logger.py` | Exports checkpoints, compaction snapshots, git context to Nexus |

### NotebookLM Flywheel

| Module | Purpose |
|--------|---------|
| `bootstrap_notebooks.py` | Weekly notebook refresh — seed sources, distill Q&A, browser-bundle support |
| `notebooklm_flywheel.py` | Control-notebook orchestrator — grounded ask, JSON report, Nexus storage |
| `nlm_chain.py` | Multi-step chain-prompting engine for NotebookLM conversations |
| `nlm_cookie_refresh.py` | CDP-based cookie refresh for NotebookLM session maintenance |
| `har_extractor.py` | HAR file parsing for session token extraction |

### Knowledge Processing

| Module | Purpose |
|--------|---------|
| `qa_expander.py` | Generates Q&A pairs from knowledge entries via NLM-backed asks |
| `qa_generator.py` | Batch Q&A generation through LMStudio |
| `news/` | News pipeline — fetch, parse, deduplicate, distill, store |
| `operator_inbox.py` | Off-turn operator directives — notes, questions, features, bugs |
| `google_account_manager.py` | Multi-account Google cookie pool and rotation |

### Smart Query Router Pipeline

```
Request → ① Q&A Cache (instant, 0 tokens)
        → ② FTS5 Search (fast, synthesize from entries)
        → ③ Nexus Ask (server-side pipeline)
        → ④ Direct NotebookLM Ask (grounded, free)
        → ⑤ LMStudio Fallback (local inference, auto-stored)
```

Every LLM answer is auto-cached. The next time anyone asks the same question,
Nexus answers instantly. This is the core of the always-improving knowledge loop.

---

## Agents — Inference Governance

`engine/agents/` — **17 root files + 28 interceptor files**

### Agent Chain

```
AgentGovernor
  └→ AgentRouter (picks model/backend)
       └→ VirtualAgent.reply()
            └→ VirtualAgentManager (pool management)
                 └→ build_request() ← governance_context injected here
                      └→ LMSClient.infer_stream() / infer_processed()
```

### Root Agent Modules

| Module | Purpose |
|--------|---------|
| `virtual_agent.py` | Core agent — system prompt, skill awareness, conversation threading |
| `virtual_agent_manager.py` | Agent pool — manages multiple named agents per scene |
| `agent_governor.py` | Top-level governance — safety, policy, context injection |
| `agent_router.py` | Model selection — routes requests to appropriate LMStudio model |
| `stream_processor.py` | Tag extraction from streamed responses: `[MOOD:x]`, `[IMAGE:p]`, `[ACTION:x]`, `[STAT:n±v]`, `[VOICE:s]` |
| `output_evaluator.py` | Quality scoring (0.0–1.0) — length, coherence, truncation, repetition |
| `comms_framework.py` | Interceptor pipeline orchestrator — PRE/POST phases |

### Interceptor Pipeline

28 interceptor files in `engine/agents/interceptors/`, auto-discovered via
`__init__.py`. Each interceptor has a priority (lower = runs first) and a phase
(PRE = before LLM call, POST = after).

**PRE interceptors** inject context into the request before inference:

| Priority | Interceptor | What It Does |
|----------|-------------|--------------|
| 1 | `NexusPromptInterceptor` | Injects Nexus-sourced context and rules |
| 3 | `AmbientEventInterceptor` | Injects active world events from WorldSim |
| 5 | `NaturalMoodDriftInterceptor` | Applies subtle per-interaction stat drift |
| 8 | `CharacterRegistryInterceptor` | Syncs character mood/energy into system prompt |
| 10 | `RouterMessageInjector` | Drains agent inbox, injects pending messages |
| 12 | `DialogDirectiveInterceptor` | Applies scene dialog directives |
| 15 | `PenthouseSceneInterceptor` | Penthouse-specific system prompt additions |
| 15 | `PhoneSceneInterceptor` | Phone scene prompt additions + ConversationHeat |
| 15 | `LoungeSceneInterceptor` | Lounge scene prompt additions |
| 15 | `GallerySceneInterceptor` | Gallery-specific prompt additions |
| 20 | `AutoResultInjector` | Injects auto-triggered skill results |
| 25 | `ConversationRecapInterceptor` | Summarizes long conversations for context |
| 30 | `SkillAwarenessInterceptor` | Lists REQUIRED/AVAILABLE tools for LLM |
| 35 | `GameSessionInterceptor` | Injects active game session state |
| 40 | `GameRulesInterceptor` | Injects game rules if game is active |
| 50 | `PersonalityGuardInterceptor` | Adds forbidden topics / required tone |
| 55 | `ConversationVarietyInterceptor` | Adjusts tone using ConversationHeat directives |
| 60 | `PolicyEnforcerInterceptor` | Enforces max token prompt reminder |
| 65 | `RelationshipContextInterceptor` | Injects relationship tier + memory snippets |
| 67 | `RelationshipEventInterceptor` | Fires relationship-triggered events |
| 70 | `MemoryEnhancerInterceptor` | Injects top-k semantic memories from RAG |

**POST interceptors** process the response after inference:

| Priority | Interceptor | What It Does |
|----------|-------------|--------------|
| 75 | `CacheInterceptor` | Caches responses for repeated queries |
| 80 | `ResponseShaperInterceptor` | Strips leaked skill sections, trims reply |
| 85 | `TTSStyleInterceptor` | Builds `ctx["tts_meta"]` for CosyVoice |
| 88 | `GrammarScannerInterceptor` | Scans for truncation, repetition, broken symbols |
| 90 | `ActivityLoggerInterceptor` | Logs interaction to database + training flywheel |
| 92 | `MoodSyncInterceptor` | Strips `[MOOD:xxx]` tag, syncs to character registry |
| 95 | `UniversalSceneInterceptor` | Cross-scene post-processing |

**Abort flag:** Any PRE interceptor can set `ctx["abort"] = True` to skip the
LLM call entirely.

---

## MCP Framework — Tools & Governance

`engine/mcp/` — **23 core + 43 tool modules = 66 files**

### Core Framework

| Module | Purpose |
|--------|---------|
| `mcp_framework.py` | MCPFramework singleton — root state tree, node management |
| `mcp_server.py` | Flask MCP server — tool registration, request routing |
| `decorators.py` | `@mcp_tool` decorator — error handling, JSON serialization |
| `dialog_system.py` | DialogSystem — conversation tracking, turn management |
| `scene_state.py` | SceneStateManager — mutable scene state coordination |
| `scene_rules.py` | SceneRulesEngine — declarative game rules evaluation |
| `governance.py` | AgentGovernor runtime — policy enforcement |
| `notebooklm_proxy.py` | NLM Live Proxy — 42 RPC constants, batchexecute bridge |
| `nlm_live_proxy.py` | Extended NLM proxy — full NotebookLM API surface |

### MCP State Tree

```
MCPFramework (singleton)
├── scenes/
│   ├── penthouse/     (MCPSceneNode)
│   │   ├── characters/
│   │   │   ├── lola/  (MCPCharacterNode — stats, inventory, relationships)
│   │   │   └── aria/
│   │   └── state/    (SceneStateManager)
│   ├── casino/
│   └── ...
├── world/
│   ├── player/      (PlayerState — credits, rep, heat, faction standings)
│   ├── factions/    (6 factions with power %, trends)
│   └── events/      (WorldSim ring buffer)
└── system/
    ├── timers/      (MCPTimer — scheduled callbacks)
    └── config/      (live config surface)
```

### MCP Tool Modules (43 files)

Each file in `engine/mcp/tools/` exposes domain-specific tools decorated with
`@mcp_tool`. The decorator handles error wrapping and JSON serialization.

**Game & Narrative:** game_tools, narrative_tools, story_tools, character_tools,
social_tools, emotion_tools, relationship_tools, reputation_tools, npc_tools,
npc_backstory_tools, memory_tools, inventory_tools, crew_tools, mission_tools,
city_tools, hacking_tools, board_tools, investigation_tools

**Knowledge & System:** nexus_tools, knowledge_tools, coding_tools, evaluation_tools,
experiment_tools, training_tools, benchmark_tools

**Media & Assets:** comfyui_tools, tts_tools, voice_tools, vision_tools,
art_tools, asset_tools, media_tools

**Infrastructure:** lmstudio_tools, inference_tools, config_tools, system_tools,
autonomy_tools, copilot_tools, colab_tools, google_account_tools, cdp_tools,
homeassistant_tools, notebooklm_tools

---

## Skills — Agent Capabilities

`engine/skills/builtin/` — **46 files, 64 total packs, ~300+ skills**

### Skill Decorator

```python
@skill(
    pack="scene_name",
    description="LLM-facing description",
    category="game",        # COMMUNICATION|MEMORY|MEDIA|GAME|SOCIAL|ENVIRONMENT|SYSTEM|NARRATIVE
    cooldown=5.0,
    cost=1.0,
    tags=["combat", "rpg"],
    prerequisites=["other_skill"],
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

### Builtin Skill Packs (45)

| Category | Packs |
|----------|-------|
| **Agent/System** | agent_state, autonomy, coding, evaluation, experiment, inference, vision |
| **Knowledge** | nexus, nlm_forge, notebooklm, prompts_chat, news |
| **Character** | character, memory, npc, npc_backstory, player_profile, profile, relationship, reputation, social |
| **Game Mechanics** | board, city, crew, hacking, inventory, mission, story, world |
| **Media** | art, comfyui, tts, tts_profile, voice |
| **Infrastructure** | cdp, coder, codespace, colab, copilot, google_account, homeassistant, lmstudio_server, training |
| **Scene-Specific** | announcer |

### Scene Skill Packs (19)

Every scene directory can contain a `*_skills.py` file with scene-specific skills:

arena, asset_studio, penthouse, casino, coders, command_center, gallery, games,
grid, heist, hub, intel_hub, lab_break, lounge, neoncity, nexus_panel, phone,
realm, tavern

---

## LMStudio — Local Inference

`engine/lmstudio/` — **23 files**

### Core Client

| Module | Purpose |
|--------|---------|
| `client.py` | LMSClient — stateful conversations, SSE streaming, model profiles |
| `server_controller.py` | ServerController — start/stop/restart LMStudio, model loading |
| `lmlink.py` | LMLink federation — multi-instance model routing via Tailscale |
| `task_queue.py` | TaskQueue — priority queue with model affinity routing |
| `conversation_manager.py` | Conversation threading via `store: true` + `previous_response_id` |

### Inference Pipeline

```
Request
  → AgentRouter.resolve_model()      # pick model profile (big/small/router/draft)
  → LMSClient.infer_stream()         # SSE to localhost:1234
    → event: chat.start
    → event: message.delta (tokens)   # StreamProcessor extracts tags
    → event: reasoning.delta          # reasoning traces (if enabled)
    → event: tool_call.start/end      # tool calling
    → event: chat.end
  → StreamProcessor.extract_tags()    # [MOOD:x], [IMAGE:p], etc.
  → OutputEvaluator.score()           # quality 0.0–1.0
  → DataCollector.collect()           # training flywheel capture
```

### Model Profiles (from config)

| Profile | Use Case | Context | Max Tokens |
|---------|----------|---------|------------|
| `big` | Complex reasoning, long scenes | 32k+ | 4096 |
| `small` | Fast responses, simple dialog | 8k | 1024 |
| `router` | Request classification (270M) | 2k | 256 |
| `draft` | Speculative decoding draft | 2k | 512 |

### LMLink Federation

LMLink connects multiple LMStudio instances (local or remote via Tailscale).
Config lives in `config/lmlink.yaml`. Remote models appear alongside local
models in `GET /api/v1/models`. The client resolves model→peer affinity and
fails over gracefully when a remote peer goes down.

### Input Format (Critical)

```python
# Correct — input items use type: "text" or type: "image"
{"type": "text", "text": "Hello"}
{"type": "image", "data_url": "data:image/png;base64,..."}

# WRONG — input/output formats are asymmetric
{"type": "message", "content": "Hello"}  # This will fail
```

### Bearer Authentication

All API calls require `Authorization: Bearer <token>`. The token is sourced
from `config.get("lmstudio.api_token")`, never hardcoded.

---

## Scenes — Content Layer

`content/scenes/` — **20 Flask scenes across 23 directories**

### Scene Types

**Game Scenes (11):**

| Port | Scene | Class | Description |
|------|-------|-------|-------------|
| 5556 | penthouse | PenthouseScene | Multi-agent roleplay engine with combat/dialog/inventory |
| 5558 | tavern | TavernScene | Gritty dockside tavern with quest board |
| 5559 | casino | CasinoScene | High-stakes poker and gambling at Club Noir |
| 5560 | gallery | GalleryScene | Dark art gallery with private viewings |
| 5561 | arena | ArenaScene | Investigation board, mystery games, 3D dice |
| 5562 | realm | RealmScene | AI-directed LitRPG with murder mystery subplot |
| 5564 | coders | CodersRoomScene | AI agent code simulation with multi-agent collaboration |
| 5565 | heist | HeistScene | Multi-agent cooperative planning and execution |
| 5567 | games | GamesScene | The Arcade — mystery/dice/truth-or-dare with AI GameMaster |
| 5571 | lab_break | LabBreakScene | 3D escape simulation with vitals (hunger, health, energy, stress) |
| 5557 | lounge | LoungeScene | The Velvet Lounge social hangout |

**Utility Scenes (6):**

| Port | Scene | Class | Description |
|------|-------|-------|-------------|
| 5555 | phone | PhoneSceneV2 | Mobile device interface with messaging |
| 5568 | asset_studio | AssetStudioScene | Asset generation hub (9 tabs: images, portraits, voice, video) |
| 5570 | nexus_panel | NexusPanelScene | Knowledge management dashboard with Librarian agent |
| 5575 | system_control | SystemControlScene | Live config editor, service manager, metrics |
| 5580 | intel_hub | IntelHubScene | Intelligence command center — The Briefing Room |
| 8500 | hub | HubScene | Central launcher and scene navigator |

**Service Scenes (3):**

| Port | Scene | Class | Description |
|------|-------|-------|-------------|
| 5563 | neoncity | NeonCityScene | Living world hub — 6 factions, economy, reputation |
| 5566 | command_center | CommandCenterScene | War-room dashboard with system metrics |
| 5569 | grid | GridScene | Underground marketplace, travel hub, faction den, broker |

### BaseScene Contract

Every scene inherits from `BaseScene` and must implement:

```python
class MyScene(BaseScene):
    SCENE_METADATA = {"name": "my_scene", "port": 5567, "type": "game"}

    def start(self):
        # Flask app setup, route registration, Socket.IO wiring
        from content.shared import register_shared_assets
        register_shared_assets(self.app)        # /shared/* — REQUIRED
        self.register_health_route(self.app)     # /api/health
        self.register_hud_route(self.app)        # /api/hud/state
        self.register_announcer_route(self.app)  # /api/announcer/feed

    def stop(self):
        # Persist state, cleanup resources

    def get_plugin_info(self):
        # Return metadata for hub discovery
```

### Scene Directory Structure

```
content/scenes/{name}/
├── __init__.py           # Scene class
├── {name}_scene.py       # Optional split (class impl)
├── {name}_skills.py      # @skill-decorated functions (pack="{name}")
├── templates/
│   └── {name}.html       # Jinja2 template with {% include 'navbar_v2.html' %}
└── static/
    ├── css/
    ├── js/
    └── img/
```

### Scene Registration

Adding a new scene requires updates in these locations:

1. `engine/port_registry.py` — `_PORTS`, `SERVICE_GROUPS["scenes"]`, health/catalogue targets
2. `engine/control_plane_registry.py` — `SCENE_DEFS` with metadata
3. `config/default.yaml` — scene-specific config block
4. `content/scenes/{name}/` — scene directory with all required files

### Shared Frontend Assets

All scenes include shared templates and assets from `content/shared/`:

| Asset | Purpose |
|-------|---------|
| `navbar_v2.html` | Self-contained navigation bar (includes its own CSS/JS) |
| `neon_hud.html` | Universal HUD strip — credits, reputation, heat, world events |
| `portrait_overlay.html` | Character portrait panel with mood badges |
| `cosysim-particles.js` | Canvas particle engine with per-scene effect presets |
| `cosysim-scene-fx.css` | Per-scene ambient CSS animations via `[data-scene]` |
| `cosysim-transitions.js` | Page transition animations between scenes |
| `design_tokens.css` | CSS custom properties for theming |
| `cosysim-animations.css` | Shared keyframe animations |
| `aria_widget.html` | AI assistant widget (self-contained) |

**Rules:**
- Never explicitly load `navbar_v2.css` or `navbar_v2.js` — the template is self-contained
- Never load `aria_widget.js` — use `{% include 'aria_widget.html' %}` instead
- Always call `register_shared_assets(self.app)` in `start()` or `/shared/*` routes will 404

---

## Integrations — External Services

`engine/integrations/` — **25 files**

### Google Service Layer

| Module | Purpose |
|--------|---------|
| `google_account_pool.py` | Multi-account cookie pool with rotation and staleness tracking |
| `google_service_profiles.py` | Service-aware profile registry for Google services |
| `nlm_direct_client.py` | NotebookLM RPC client — 41 `_rpc_call` sites via YAML registry |
| `colab_client.py` | Colab RPC client — notebook execution, GPU management |
| `drive_client.py` | Google Drive file operations |
| `har_parser.py` | HAR file parsing for cookie/session extraction |
| `compute_router.py` | Routes compute requests: tunnel → Copilot → LMStudio |
| `rpc_proxy.py` | Generic batchexecute RPC proxy |

### NLM RPC Registry

All NotebookLM RPC IDs flow through `config/nlm_rpcids.yaml` (98 operations)
→ `engine/integrations/nlm_rpc_registry.py`. No hardcoded rpcid strings in
client or proxy code.

```python
from engine.integrations.nlm_rpc_registry import get_rpc_registry
registry = get_rpc_registry()
rpcid = registry.get_rpcid("list_notebooks")   # → "wXbhsf"
payload = registry.build_payload("list_notebooks", page_size=50)
```

Dual-purpose rpcids change behavior based on context:
- `CCqFvf`: WITHOUT notebook context = `create_notebook`; WITH = `open_notebook`
- `wXbhsf`: WITHOUT notebook context = `list_notebooks`; WITH = `list_sources`

---

## World Simulation

`engine/world/` — **12 files**

| Module | Purpose |
|--------|---------|
| `world_sim.py` | WorldSim — faction dynamics, economy ticks, NPC actions, weather |
| `player_state.py` | PlayerState singleton — credits, rep, heat, faction standings, auto-save |
| `city_map.py` | Location graph, travel routes, scene-to-district mapping |
| `neon_city_events.py` | 50+ event templates — heists, festivals, blackouts, corp raids |
| `event_cascade.py` | WorldSim → all scenes via Socket.IO event propagation |
| `missions.py` | Mission system — accept, track, complete, rewards |
| `crew.py` | Crew formation — roles, trust requirements, management |
| `inventory.py` | Item system — 24 slots, equipped dict, consumable effects |

### World Event Flow

```
WorldSim tick (every 60s)
  → generate SimEvent (economy_tick / faction_shift / npc_action / weather)
  → EventCascade broadcasts to all subscribed scenes
  → Scenes update local state + emit Socket.IO events
  → HUD ticker displays event text
  → PlayerState receives credits/rep/heat deltas
```

---

## Pipeline & Services

### Pipeline (`engine/pipeline/` — 6 files)

| Module | Purpose |
|--------|---------|
| `virtual_pipeline.py` | VirtualPipeline — orchestrates multi-step inference chains |
| `stream_watcher.py` | StreamWatcher — monitors streaming output for anomalies |
| `kill_switch.py` | KillSwitch — emergency inference termination |
| `token_router.py` | TokenRouter — routes tokens to appropriate handlers |

### Services (`engine/services/` — 6 files)

| Module | Purpose |
|--------|---------|
| `activity_bus.py` | ActivityBus — cross-scene activity tracking and routing |
| `world_announcer.py` | Polls EventChain + faction standings, generates radio-style lines |
| `hack_engine.py` | Hacking mini-game — grid puzzle generator, cyberdeck integration |
| `housekeeping.py` | System maintenance — cleanup, health checks, resource management |
| `resilience.py` | Service resilience — retry, circuit breaker, fallback management |
| `comfyui_monitor.py` | ComfyUI workflow monitoring and status tracking |

### TTS (`engine/tts/` — 8 files)

| Module | Purpose |
|--------|---------|
| `qwen3_tts.py` | Qwen3 TTS integration — text-to-speech via local model |
| `orpheus_native.py` | Orpheus TTS — native voice synthesis |
| `voice_profiles.py` | Voice profile management — per-character voice settings |
| `cosyvoice.py` | CosyVoice integration — multi-speaker voice synthesis |

### Asset Studio (`engine/asset_studio/` — 16 files)

| Module | Purpose |
|--------|---------|
| `workflow_builder.py` | ComfyUI workflow construction — builds node graphs |
| `tuning_engine.py` | A++ tuning system — proven profiles, benchmark runner, VL scoring |
| `auto_tuner.py` | Auto-tuner state machine — iterates settings for quality |
| 8 generators | Image, video, portrait, voice, Wan 2.2 GGUF, and more |

---

## Training System

`training/` — **31 files** (top-level, separate from engine)

### Model Zoo

14 model types tracked by `ModelZoo`:

| Type | Base Model | Purpose |
|------|-----------|---------|
| `router_v3` | Gemma 270M | Request classification and routing |
| `coder` | Llama 3.2-3B | Code generation and completion |
| `conversational` | Qwen 1.7B | Dialog and character responses |
| `tool_dispatch` | Gemma 270M | Tool/skill selection |
| `voice` | Various | Voice style adaptation |
| `output_evaluator` | — | Response quality scoring |
| + 8 more | Various | Specialized fine-tuned models |

### Training Pipeline

```
Runtime data → DataCollector → JSONL datasets
                                     ↓
              LMStudio ← promote ← BenchmarkRunner
                  ↓                      ↓
            better responses      FinetuneOrchestrator
                  ↓                      ↓
            more data ──────────→ trained model
```

Every conversation, skill call, and grammar scan becomes training data. Every
trained model improves runtime. The system gets smarter each cycle.

### Dataset Generators

Located in `training/datasets/`:

| Generator | Output |
|-----------|--------|
| `generate_coder.py` | Code completion examples |
| `generate_conversation.py` | Dialog training pairs |
| `generate_router_v3.py` | Request classification examples |
| `generate_tool_dispatch.py` | Tool calling examples |

---

## Configuration Layer

### File Hierarchy

| File | Purpose |
|------|---------|
| `config/default.yaml` | Base configuration — all settings with defaults |
| `config/development.yaml` | Dev overrides — debug=true, test paths |
| `config/production.yaml` | Prod overrides — debug=false, real paths |
| `config/voices.yaml` | TTS voice definitions per character |
| `config/skill_manifests.yaml` | Skill pack metadata and registration |
| `config/mcp.json` | MCP server definitions |
| `config/nlm_rpcids.yaml` | NotebookLM RPC registry (98 operations, v4.0) |
| `config/nlm_notebooks.yaml` | NLM notebook fleet definitions |
| `config/lmlink.yaml` | LMLink peer configuration |
| `config/news_sources.yaml` | News feed source URLs |
| `config/launcher.yaml` | Launcher-specific settings |

### Access Pattern

```python
from engine.config import get_config
cfg = get_config()
port = cfg.get("scenes.penthouse.port", 5556)
model = cfg.get("lmstudio.models.primary", "default-model")
```

Always provide sensible defaults in `get()` calls. Never hardcode ports, paths,
model names, or API URLs.

---

## Data Flow — Request Lifecycle

### Chat Request Pipeline

```
User message (Socket.IO or REST)
  │
  ├─ Scene receives message
  │   └─ DialogSystem.add_turn(user_message)
  │
  ├─ AgentGovernor.process()
  │   ├─ Safety check
  │   └─ Governance context assembly
  │
  ├─ VirtualAgent.reply(message, governance_context)
  │   ├─ build_request()
  │   │   ├─ System prompt (character personality + scene context)
  │   │   ├─ Conversation history (last N turns)
  │   │   ├─ Governance context (from Governor)
  │   │   └─ Available skills list
  │   │
  │   ├─ InterceptorPipeline.run_pre(request, context)
  │   │   ├─ NexusPromptInterceptor → inject Nexus rules
  │   │   ├─ AmbientEventInterceptor → inject world events
  │   │   ├─ CharacterRegistryInterceptor → sync character state
  │   │   ├─ SkillAwarenessInterceptor → list available tools
  │   │   ├─ MemoryEnhancerInterceptor → inject relevant memories
  │   │   └─ ... (21 PRE interceptors total)
  │   │
  │   ├─ LMSClient.infer_stream(request)
  │   │   └─ SSE to localhost:1234
  │   │
  │   └─ InterceptorPipeline.run_post(response, context)
  │       ├─ ResponseShaperInterceptor → clean response
  │       ├─ TTSStyleInterceptor → build TTS metadata
  │       ├─ ActivityLoggerInterceptor → log to DB + training flywheel
  │       ├─ MoodSyncInterceptor → extract [MOOD:x], sync to registry
  │       └─ ... (7 POST interceptors total)
  │
  ├─ StreamProcessor.extract_tags(response)
  │   ├─ [MOOD:happy] → character registry update
  │   ├─ [IMAGE:prompt] → ComfyUI generation queue
  │   ├─ [ACTION:x] → game event trigger
  │   ├─ [STAT:health+10] → player state update
  │   └─ [VOICE:style] → TTS style override
  │
  └─ Scene emits response via Socket.IO
      ├─ Chat message to client
      ├─ HUD update (if stats changed)
      ├─ Portrait mood update
      └─ Optional TTS audio
```

---

## ARGUS — Browser Automation

`scripts/argus/` — **18+ files**

ARGUS provides browser automation via Playwright + Chrome DevTools Protocol.
Three operational paths:

1. **Live orchestrator crawlers** — Playwright + CDP browser automation
2. **LMStudio ArgusAgent** — AI-driven browser control via tool calling
3. **Offline tools** — HAR parsing, heap analysis, protocol monitoring

### Key Components

| Component | Purpose |
|-----------|---------|
| `agent.py` | ArgusAgent — LMStudio-powered browser agent with tool calling |
| `browser_tools.py` | Playwright browser control + CDP bridge |
| `explorer.py` | AutoExplorer — automated API surface testing |
| `orchestrator.py` | Master crawl controller |
| `decoders/batchexecute.py` | `f.req` → rpcid + payload parsing |
| `decoders/grpc_web.py` | Binary gRPC-web frame decoding |
| `decoders/heap_diffing.py` | CDP heap snapshot diffing |
| `tools/token_harvester.py` | CDP token + cookie extraction |
| `tools/har_replay.py` | HAR file replay and analysis |

---

## Scheduler — Recurring Tasks

`engine/nexus/scheduler_daemon.py` manages **55 recurring tasks**:

| Category | Count | Examples |
|----------|-------|---------|
| Maintenance & Quality | 8 | nexus-maintenance, governance-audit, test-monitor |
| Notebook & NLM | 8 | notebook-rotation, master-notebook-refresh, news-distill-nlm |
| Knowledge & QA | 5 | qa-generation, qa-expansion, doc-sync |
| Training & Datasets | 8 | training-sync, coder-dataset-refresh, router-finetune-cycle |
| Model Training | 6 | finetune-if-ready, model-benchmark, voice-auto-train |
| World Simulation | 6 | world-sim-tick, npc-world-tick, director-tick |
| News & Notifications | 3 | news-fetch, ha-news-push, operator-inbox-sync |
| Copilot & Agent | 3 | copilot-rules-refresh, copilot-self-sync |
| System & Monitoring | 4 | system-reflection, metrics-collect, control-notebook-flywheel |
| Advanced Features | 4 | cdp-mine, cookie-health-check, argus-nlm-distil |

---

## Port Registry

All service ports are managed by `engine/port_registry.py`. No hardcoded ports
in scene or service code.

### Scene Ports

| Port | Scene | Type |
|------|-------|------|
| 5555 | phone | utility |
| 5556 | penthouse | game |
| 5557 | lounge | social |
| 5558 | tavern | adventure |
| 5559 | casino | game |
| 5560 | gallery | game |
| 5561 | arena | game |
| 5562 | realm | game |
| 5563 | neoncity | service |
| 5564 | coders | game |
| 5565 | heist | game |
| 5566 | command_center | utility |
| 5567 | games | game |
| 5568 | asset_studio | utility |
| 5569 | grid | service |
| 5570 | nexus_panel | utility |
| 5571 | lab_break | game |
| 5575 | system_control | utility |
| 5580 | intel_hub | utility |
| 8500 | hub | utility |

### Infrastructure Ports

| Port | Service |
|------|---------|
| 1234 | LMStudio inference |
| 5005 | Orpheus TTS |
| 5050 | CosyVoice TTS |
| 5051 | Whisper STT |
| 5590 | Canvas |
| 5595 | Canvas API |
| 8188 | ComfyUI |
| 8700 | Nexus KMS |
| 8800 | NLM Proxy |

---

## Key Singletons

These are obtained via `get_*()` factory functions and are shared across the
entire process:

```python
get_framework()              # MCPFramework — root state tree
get_character_registry()     # CharacterRegistry — all loaded characters
get_dialog_system()          # DialogSystem — conversation tracking
get_rules_engine()           # SceneRulesEngine — declarative game rules
get_scene_state_manager()    # SceneStateManager — mutable scene state
get_governor()               # AgentGovernor — policy enforcement
get_router()                 # AgentRouter — model selection
get_config()                 # ConfigManager — dot-notation config access
get_nexus_client()           # NexusClient — knowledge CRUD
get_query_router()           # NexusQueryRouter — 5-tier smart query
```

---

## Adding New Scenes

1. Create `content/scenes/{name}/` with `__init__.py`, `{name}_scene.py`,
   `templates/`, `static/`
2. Subclass `BaseScene`, set `SCENE_METADATA`
3. In `start()`: call `register_shared_assets()`, `register_health_route()`,
   `register_hud_route()`, `register_announcer_route()`
4. Register port in `engine/port_registry.py` (`_PORTS`, `SERVICE_GROUPS`,
   health/catalogue targets)
5. Add scene definition in `engine/control_plane_registry.py`
6. Add config block in `config/default.yaml`
7. Create optional `{name}_skills.py` with `@skill(pack="{name}")`
8. Run `python scripts/scene_health_check.py --port {PORT} --fix`

## Adding New Skills

1. Create `engine/skills/builtin/{name}_skills.py`
2. Decorate functions with `@skill(pack="{name}", description="...", category="...")`
3. Import the skills module in the relevant scene's `__init__.py`
4. Skills are auto-discovered by the skill registry
5. Test with `python -m pytest tests/test_{name}_skills.py -v`

