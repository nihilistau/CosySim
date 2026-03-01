# CosySim Architecture Guide

> Comprehensive architecture reference. Consolidates STRUCTURE_GUIDE, MCP_ARCHITECTURE, and AGENTS_GUIDE.

---

## System Overview

CosySim is a framework for building AI agent simulation scenes — a game engine where NPCs are LLM-powered agents.

### Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CONFIG LAYER                                 │
│  default.yaml · mcp.json · voices.yaml · skill_manifests.yaml       │
│  Tune everything without touching code                              │
└────────────────────────────┬────────────────────────────────────────┘
                             │ reads
┌────────────────────────────▼────────────────────────────────────────┐
│                        ENGINE LAYER                                 │
│  engine/                                                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  agents/  │ │   mcp/   │ │ lmstudio/│ │pipeline/ │ │  skills/ │ │
│  │VirtualAgt │ │Governor  │ │LMSClient │ │VirtPipe  │ │@skill()  │ │
│  │AgentLoop  │ │Intercept │ │ModelMgr  │ │StreamW   │ │9 builtin │ │
│  │StreamProc │ │DialogSys │ │InfRouter │ │TokenRtr  │ │11 scene  │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ scenes/  │ │   tts/   │ │ spatial/ │ │ logging/ │              │
│  │BaseScene │ │Qwen3TTS  │ │SceneMap  │ │RingBuf   │              │
│  │Registry  │ │VoiceDsgn │ │Location  │ │Benchmark │              │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘              │
│                                                                     │
│  ┌─────────────────────── v0.68 ──────────────────────────────────┐│
│  │ events/EventBus (cross-scene pub/sub backbone)                  ││
│  │ economy/EconomyManager · content/ContentGate+ContentEngine      ││
│  │ characters/CharacterMemory+ReputationInterceptor                ││
│  │ director/SceneDirector · mechanics/ConsequenceStore+InvBoard    ││
│  │ art/SceneArtManager · world/WorldState+WorldSim                 ││
│  │ arena/ArenaEngine                                               ││
│  └────────────────────────────────────────────────────────────────┘│
└────────────────────────────┬────────────────────────────────────────┘
                             │ subclasses / uses
┌────────────────────────────▼────────────────────────────────────────┐
│                       CONTENT LAYER                                 │
│  content/                                                           │
│  ┌──────────────────────────┐  ┌─────────────────────────────────┐ │
│  │  scenes/                  │  │  simulation/                    │ │
│  │  signal · penthouse · pit │  │  character_system/ (Personality)│ │
│  │  noir · obscura · throne  │  │  database/ (SQLite, RAG, Events)│ │
│  │  neon · lab · score       │  │  services/ (ComfyUI, media)    │ │
│  │  anchor · colosseum       │  └─────────────────────────────────┘ │
│  └──────────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────────┘
```

**Principle:** Engine is reusable framework. Content is swappable. Config tunes without code.

---

## Engine Layer

### New Modules (v0.68 "Dark Renaissance")

13 cross-scene engine modules added in v0.68. All live under `engine/` and are wired into scenes via BaseScene helpers.

| Module | File | Key Class | Purpose |
|--------|------|-----------|---------|
| **EventBus** | `engine/events/event_bus.py` | `EventBus` | Cross-scene pub/sub backbone — scenes publish typed events, subscribers react without direct coupling |
| **EconomyManager** | `engine/economy/economy.py` | `EconomyManager` | Cross-scene credit ledger — earn, spend, transfer, escrow with persistent balance |
| **ContentGate** | `engine/content/content_gate.py` | `ContentIntensityInterceptor` | Adult content gating — intensity profiles 0–3 per category, interceptor-enforced |
| **ContentEngine** | `engine/content/content_engine.py` | `ContentEngine` | Nexus-backed content pool management — fetch, rank, and serve dynamic content variants |
| **CharacterMemory** | `engine/characters/memory.py` | `CharacterMemoryInterceptor` | Persistent cross-session character memory — stores and recalls facts across restarts |
| **ReputationManager** | `engine/characters/reputation.py` | `ReputationInterceptor` | Faction/reputation standings — per-character, per-faction scores, injected into pre-call context |
| **SceneDirector** | `engine/director/scene_director.py` | `DirectorBeat`, `BeatType` | AI scene director — emits `DirectorBeat` objects to guide narrative pacing and tone |
| **ConsequenceStore** | `engine/mechanics/consequences.py` | `ConsequenceStore` | Scheduled cross-session consequences — fire deferred narrative/stat effects on next session start |
| **InvestigationBoard** | `engine/mechanics/investigation.py` | `InvestigationBoard` | Investigation board + NLM reasoning — pin clues, run NLM deduction, surface conclusions |
| **SceneArtManager** | `engine/art/scene_art.py` | `SceneArtManager` | ComfyUI portrait/scene art — request, queue, and cache generated imagery per scene context |
| **WorldState** | `engine/world/world_state.py` | `WorldStateInterceptor` | Game clock + NPC schedules — global time-of-day and NPC availability injected every turn |
| **WorldSim** | `engine/world/world_sim.py` | `WorldSim` | Living world daemon — background tick loop evolving NPC states, events, and economy |
| **ArenaEngine** | `engine/arena/arena_engine.py` | `ArenaEngine` | Tactical card game engine — RPS mechanics, combos, hand management, round resolution |

#### EventBus Usage

```python
from engine.events.event_bus import get_event_bus, EventType

bus = get_event_bus()

# Publish
bus.publish(EventType.ECONOMY_CREDIT_EARNED, {"character_id": "luna", "amount": 50})

# Subscribe
bus.subscribe(EventType.ROUND_WON, on_round_won)
```

EventBus is the integration backbone — ArenaEngine, WorldSim, EconomyManager, and SceneDirector all publish through it.

---

### Agents (`engine/agents/`)

The agent system decouples identity/state from LLM execution:

| Component | File | Role |
|-----------|------|------|
| **VirtualAgent** | `virtual_agent.py` | State container, prompt builder, RAG integration. Implements `IAgent` |
| **VirtualAgentManager** | `virtual_agent_manager.py` | Centralized inference router, concurrency control, model lifecycle |
| **CharacterAgent** | `character_agent.py` | Thin adapter — always delegates to VirtualAgent internally |
| **SceneAgent** | `scene_agent.py` | One-shot utility agent (title, summarize, classify) |
| **AgentLoop** | `agent_loop.py` | Tick-based `perceive → decide → execute` cycle for multi-agent scenes |
| **StreamProcessor** | `stream_processor.py` | Real-time tag extraction from SSE (`[MOOD:x]`, `[ACTION:x]`, `[IMAGE:x]`) |
| **ContentRouter** | `content_router.py` | Routes response chunks to appropriate handlers |
| **Evaluator** | `evaluator.py` | Post-inference quality evaluation |
| **Interceptors** | `interceptors.py` | Built-in interceptor implementations (24 interceptors) |
| **Protocols** | `protocols.py` | `IAgent` protocol, `AgentCapability` enum, type definitions |

#### IAgent Protocol

```python
@runtime_checkable
class IAgent(Protocol):
    character: Any
    capabilities: Set[AgentCapability]

    def reply(self, user_message: str, *, chain_id=None, history=None, **kwargs) -> str: ...
    def quick_query(self, prompt: str, *, max_tokens: int = 200) -> str: ...
    def cancel(self) -> None: ...
```

#### AgentCapability Enum

`text` · `tools` · `memory` · `streaming` · `tts` · `vision` · `image_gen` · `governed` · `policy` · `game_player` · `game_host`

#### Quick Start

```python
from engine.agents.virtual_agent_manager import get_virtual_agent_manager

mgr = get_virtual_agent_manager()
agent = mgr.create_agent(character, scene="bedroom")
reply = agent.reply("Hello!")
```

---

### MCP Framework (`engine/mcp/`)

Model Context Protocol layer — governance, state, dialog, rules, and 107 MCP tools.

#### Core Modules

| Module | Key Classes | Purpose |
|--------|-------------|---------|
| `cosysim_server.py` | FastMCP server | 107 `@mcp.tool()` functions across all domains |
| `tools/` | 8 domain modules | Organized tool implementations (see below) |
| `framework.py` | MCPFramework, MCPSceneMixin, MCPCharacterNode, MCPSceneNode | Framework integration for scenes |
| `comms_framework.py` | AgentGovernor, InterceptorPipeline, GameState, AgentRouter, SkillManifest | Governance and communication |
| `dialog_system.py` | DialogSystem, DialogTree, ConversationState, SpeechEnhancer | Structured dialog and speech |
| `scene_state.py` | SceneStateManager, NarrativeLog | Scene state persistence |
| `scene_rules_engine.py` | SceneRulesEngine, PermissionMatrix, ConversationHeat | Rule evaluation and heat tracking |
| `interaction_trees.py` | InteractionTree, InteractionResolver | Branching interaction flows |
| `character_registry.py` | CharacterProfile, CharacterState | Character state registry |
| `state_coordinator.py` | CharacterStateCoordinator | Cross-agent state sync |
| `game_mcp.py` | MCPGameSession, MCPGameNode, GameSessionInterceptor | Game session management |
| `tag_registry.py` | TagRegistry, TagDef, TagMatch | Response tag definitions |
| `shared_boards.py` | SharedBoardManager | Shared game board state |
| `skills_server.py` | MCP skills server | Ephemeral tool exposure |
| `web_bridge.py` | FastAPI bridge | SSE proxy, CORS, file upload |

#### MCP Tools — 8 Domain Modules (`engine/mcp/tools/`)

| Module | Domain | Example Tools |
|--------|--------|---------------|
| `memory_tools.py` | Vector memory | `search_memory`, `store_memory` |
| `character_tools.py` | Character state | `get_character_state`, `adjust_relationship`, `character_register` |
| `game_tools.py` | Game lifecycle | `start_game`, `end_game`, `game_action`, `get_game_state` |
| `scene_tools.py` | Scene context | `get_scene_context`, `set_scene_atmosphere`, `apply_scene_rule` |
| `dialog_tools.py` | Dialogue | `get_dialog_options`, `speech_enhance`, `get_conversation_heat` |
| `wardrobe_tools.py` | Clothing | `wardrobe_get`, `wardrobe_add_item`, `wardrobe_redress` |
| `media_tools.py` | Image/voice | `generate_image_request` |
| `utility_tools.py` | Misc | `roll_dice`, `send_to_agent`, `get_system_stats`, `search_web` |

#### AgentGovernor Lifecycle

```
AgentGovernor(agent, scene="bedroom", pipeline=pipeline)
      │
      ▼
  governor.reply(user_message)
      │
      ├─ Build ResponseContext {
      │      system_prompt, policy, skill_manifest,
      │      user_message, agent_id, scene
      │  }
      │
      ├─ pipeline.run_pre(ctx)         ← 16 PRE interceptors inject context
      │
      ├─ agent.reply(user_message,     ← single LLM call
      │              system_prompt=ctx["system_prompt"],
      │              skip_gov=True)
      │
      ├─ ctx["reply"] = llm_response
      │
      └─ pipeline.run_post(ctx)        ← 4 POST interceptors shape response
            │
            └─► return ctx["reply"]
```

#### Shared Singletons

```python
from engine.mcp import get_game_state, get_router, get_skill_manifest
```

| Singleton | Purpose |
|-----------|---------|
| `GameState` | Game session key/value store with observer bus |
| `AgentRouter` | Async inter-agent inbox messaging |
| `SkillManifest` | Per-scene skill registry (auto/optional/required triggers) |

---

### LMStudio Integration (`engine/lmstudio/`)

11 modules providing full LLM lifecycle management:

| Module | Key Classes | Purpose |
|--------|-------------|---------|
| `lms_client.py` | **LMSClient**, LMSModel, LMSModelInfo | v1 REST API (`/api/v1/chat`), SSE streaming |
| `client.py` | **LMStudioManager** | Model lifecycle (load/unload/VRAM monitoring) |
| `model_manager.py` | **ModelManager**, ModelSession, LoadMode | CONCURRENT / JIT / JIT_TTL loading strategies |
| `resource_manager.py` | **ResourceManager**, Strategy, ModelSlot | 6 hardware-aware resource strategies |
| `router.py` | **InferenceRouter**, Priority, Tier, Channel | 3-tier priority queue (REALTIME / BATCH / BACKGROUND) |
| `conversation.py` | **ConversationManager**, Conversation | Stateful threading, branching, `response_id` tracking |
| `concurrency.py` | **ConcurrentExecutor** | Parallel inference execution |
| `sdk_client.py` | **SDKClient** | LMStudio SDK integration |
| `inference_config.py` | **InferenceConfig**, LoadConfig | Inference parameter configuration |
| `tool_registry.py` | **ToolRegistry**, ToolSpec, ToolScope | Dynamic tool registration per inference |
| `tool_factory.py` | **ToolSpec** | Tool specification builder |

**Config:** SDK host `127.0.0.1:1234`, 4 parallel slots, VRAM cap 11,500 MB.

---

### Pipeline (`engine/pipeline/`)

Streaming inference pipeline with content quality gates:

| Module | Key Classes | Purpose |
|--------|-------------|---------|
| `virtual_pipeline.py` | **VirtualPipeline** | Request → interceptors → inference → post-process |
| `stream_watcher.py` | **StreamWatcher**, RuleBasedWatcher, ModelBasedWatcher, WatchContext | Token-by-token monitoring and content analysis |
| `token_router.py` | **TokenAheadRouter** | Classify tokens → route to appropriate tier |
| `kill_switch.py` | **KillSwitch**, KillDecision | Emergency stop on policy violation |
| `pipeline_result.py` | WatcherSignal, WatcherAnalysis, PipelineConfig, PipelineResult | Pipeline data types and results |

---

### Skills (`engine/skills/`)

Skills are Python functions decorated with `@skill()` and grouped into packs.

```python
from engine.skills.registry import skill, SkillPack

@skill(name="search_memories", description="Search character memories")
def search_memories(query: str, character_id: str = "", top_k: int = 5) -> str:
    ctx = get_chain_context()   # thread-local chain context
    ...
```

#### Core Modules

| Module | Purpose |
|--------|---------|
| `skill.py` | `@skill` decorator, `SkillCategory` enum |
| `registry.py` | `SKILL_REGISTRY`, `get_pack_tools()`, `mcp_skill_pack()` |
| `chain_context.py` | Thread-local `chain_id` propagation (skills can't receive kwargs from LMStudio SDK) |

#### 9 Built-in Packs (`engine/skills/builtin/`)

| Pack | Skills |
|------|--------|
| `memory_skills.py` | search_memory, store_memory, chain summary |
| `character_skills.py` | get_state, adjust_trait, set_mood, adjust_relationship |
| `comfyui_skills.py` | generate_image, portraits, workflows |
| `voice_skills.py` | voice messages |
| `tts_skills.py` | TTS generation, casting, presets |
| `social_skills.py` | social interactions |
| `board_skills.py` | shared board game mechanics |
| `training_skills.py` | training data capture |
| `notebooklm_skills.py` | NotebookLM integration |

#### 11 Scene-Specific Packs (`content/scenes/`)

`phone_skills.py` · `bedroom_skills.py` · `lounge_skills.py` · `casino_skills.py` · `gallery_skills.py` · `warzone_skills.py` · `realm_skills.py` · `neoncity_skills.py` · `coders_skills.py` · `heist_skills.py` · `command_center_skills.py`

#### Skill Triggers

| Trigger | Behavior |
|---------|----------|
| `auto` | Fires every turn; result injected into pre-call context |
| `optional` | LLM is informed the skill exists, chooses whether to call |
| `required` | LLM must call this skill in its reply |

#### ChainContext Pattern

Skills can't receive `chain_id` as kwargs because LMStudio SDK invokes them directly. Solution: `chain_context.py` stores chain context in thread-local storage. `CharacterAgent._act()` sets it before the LLM call and clears it after.

---

### TTS (`engine/tts/`)

| Module | Key Classes | Purpose |
|--------|-------------|---------|
| `qwen3_server.py` | **Qwen3TTSEngine**, TTSJob, GenerateRequest/Response, CastRequest | FastAPI + FastMCP TTS server |
| `voice_designer.py` | **VoiceDesigner**, VoiceDesign, CASTING_OFFICE | Voice profiles, presets, casting |
| `audio_processor.py` | **AudioProcessor** | Audio post-processing |

**Endpoints:** SSE + WebSocket streaming. Port 8600.
**Config:** `voices.yaml` for per-character voice profiles.

---

### Scenes Framework (`engine/scenes/`)

| Module | Purpose |
|--------|---------|
| `base_scene.py` | BaseScene — Flask + SocketIO, auto-register via `_ACTIVE_SCENES`, `SCENE_METADATA` |
| `scene_manager.py` | Scene lifecycle management |
| `scene_registry.py` | Auto-discover BaseScene subclasses |

---

## Content Layer

### Scenes (`content/scenes/`)

Each scene is a self-contained directory: `*_scene.py`, `*_rules.py`, `*_skills.py`, `templates/`, `static/`.

All scenes inherit `BaseScene` and optionally mix in `MCPSceneMixin` for governance integration.

| Scene | Port | Description |
|-------|------|-------------|
| phone (SIGNAL) | 5555 | CosyPhone OS — messaging, gallery, voice studio, 52+ routes |
| bedroom (THE PENTHOUSE) | 5556 | Multi-agent spatial — 2 characters, 7 locations, Three.js 3D |
| lounge (THE VELVET PIT) | 5557 | The Velvet Pit — speakeasy |
| tavern (THE RUSTY ANCHOR) | 5558 | Fantasy tavern with gold economy, quests, reputation |
| casino (CLUB NOIR) | 5559 | Club Noir — card/table games |
| gallery (THE OBSCURA) | 5560 | Art evaluation and ComfyUI generation |
| arena (THE COLOSSEUM) | 5561 | Tactical card game — agent vs agent, betting, NLM commentary |
| realm (THE SHATTERED THRONE) | 5562 | The Shattered Throne — LitRPG, dual-agent (Director + Assistant) |
| neoncity (NEON CITY) | 5563 | NeonCity — cyberpunk strategy board, grid, storm, prefabs |
| coders (THE LAB) | 5564 | The Lab — AI agent code simulation, pipeline, sandbox |
| heist (THE SCORE) | 5565 | The Score — cooperative heist planning |
| command_center | 5566 | Command Center — operations dashboard |

#### Adding a New Scene

```python
from engine.scenes.base_scene import BaseScene

class MyScene(BaseScene):
    def __init__(self):
        super().__init__("myScene", port=5570)
```

1. Create `content/scenes/myScene/` with `__init__.py`
2. Create `myScene_scene.py` inheriting `BaseScene`
3. Implement `start()`, `stop()`, `get_plugin_info()`
4. Add template in `templates/`, static files in `static/`
5. Add to `config/default.yaml` under `scenes:`
6. Add to `launcher.py` mode dispatch
7. Optionally add `myScene_skills.py` for scene-specific skills

### Streamlit Dashboards

| Dashboard | Port | Purpose |
|-----------|------|---------|
| hub | 8500 | Central dashboard |
| dashboard | 8501 | Metrics and monitoring |
| admin | 8502 | Admin panel (13 pages) |
| assets | 8503 | Asset generator |
| creator | 8504 | Content creator |

### Characters (`content/simulation/`)

| Module | Purpose |
|--------|---------|
| `character_system/` | Character, Personality, Role definitions |
| `database/db.py` | SQLite persistence — 9 tables, full CRUD |
| `database/rag.py` | ChromaDB vector memory |
| `database/events.py` | EventChain — causal audit trail (16 event types) |
| `services/` | ComfyUI client, media generation, voice/video services |

#### Database Schema (9 Tables)

| Table | Purpose |
|-------|---------|
| characters | id, name, age, sex, personality_id, tags, metadata |
| personalities | id, name, system_prompt, traits, warmth–creativity |
| roles | id, name, description, required_traits |
| memories | id, character_id, content, importance, emotion |
| conversations | id, character_id, chain_id, messages, started_at |
| interactions | id, type, character_id, content, chain_id |
| media | id, character_id, type, filepath, metadata |
| character_states | character_id, mood, energy, relationship_level |
| events | id, chain_id, parent_id, event_type, actor, payload |

#### EventChain — Ground Truth

**If it's not in EventChain, it didn't happen.**

Every interaction gets a `chain_id` (UUID). Events link via `parent_id` forming a causal tree:

```
message_in → rag_query → rag_result → llm_request → tool_call → tool_result → llm_response → message_out
```

16 event types: `message_in/out`, `llm_request/response/cancelled`, `rag_query/result`, `memory_stored`, `skill_called/result`, `tool_call/result`, `media_generated`, `autonomous_trigger`, `scene_state_change`, `error`

---

## Config Layer

| File | Purpose |
|------|---------|
| `config/default.yaml` | Master configuration — ports, paths, LMStudio, ComfyUI, all settings |
| `config/development.yaml` | Dev overrides (debug mode) |
| `config/production.yaml` | Production overrides |
| `config/voices.yaml` | Per-character TTS voice profiles |

**Access:** `get_config().get("services.lmstudio.port", 1234)`
**Override:** `COSYSIM_SERVICES__LMSTUDIO__PORT=5678` env var

---

## Data Flow

### Full Request Pipeline

```
User types message in scene UI
  → Flask route POST /api/chat
    → set_chain_context(chain_id, scene_id)
    → AgentGovernor.reply(user_message)
      │
      ├─ Build ResponseContext (sys-prompt, policy, manifest)
      ├─ InterceptorPipeline.run_pre(ctx)     ← 16 PRE interceptors
      │    ├─ NaturalMoodDrift       [5]  mood/stat drift
      │    ├─ CharacterRegistry      [8]  sync mood/energy to prompt
      │    ├─ RouterMessageInjector  [10] inject agent inbox
      │    ├─ DialogDirective        [12] scene dialog directives
      │    ├─ Scene-specific         [15] bedroom/phone/lounge context
      │    ├─ AutoResultInjector     [20] auto-triggered skill results
      │    ├─ SkillAwareness         [30] list REQUIRED/AVAILABLE tools
      │    ├─ GameSession            [35] inject game state
      │    ├─ GameRules              [40] inject game rules
      │    ├─ PersonalityGuard       [50] forbidden topics, required tone
      │    ├─ ConversationVariety    [55] ConversationHeat directives
      │    ├─ PolicyEnforcer         [60] max token reminder
      │    └─ MemoryEnhancer         [70] top-k semantic memories
      │
      ├─ VirtualAgentManager.infer()
      │    → ConversationManager: get/create Conversation
      │    → LMSClient.chat_stateful(messages, tools=[skill_pack_tools])
      │      → LMStudio /api/v1/chat (SSE stream)
      │        → LMStudio calls MCP tool: search_memory(...)
      │          → CosySim skill → result
      │        → LMStudio generates response
      │      ← StreamProcessor: extract [MOOD:], [IMAGE:], [ACTION:] tags
      │    → ProcessedResponse with clean_text, mood_tags, tool_calls
      │
      ├─ InterceptorPipeline.run_post(ctx)    ← 4 POST interceptors
      │    ├─ ResponseShaper         [80] strip leaked skill sections, trim
      │    ├─ TTSStyle               [85] build ctx["tts_meta"] for CosyVoice
      │    ├─ ActivityLogger         [90] log interaction to DB
      │    └─ MoodSync               [92] strip [MOOD:xxx], sync registry
      │
    ← Response JSON
  ← UI renders reply + emits SocketIO events
```

---

## Interceptor Pipeline

24 interceptors sorted by priority. PRE interceptors build context before the LLM call. POST interceptors shape the response after.

### Full Pipeline (priority order)

| Priority | Interceptor | Phase | What It Does |
|----------|-------------|-------|--------------|
| 5 | `NaturalMoodDriftInterceptor` | PRE | Applies subtle per-interaction stat drift and inner-thought hints |
| 8 | `CharacterRegistryInterceptor` | PRE | Syncs character mood/energy into system prompt |
| 10 | `RouterMessageInjector` | PRE | Drains agent inbox, injects pending messages into context |
| 12 | `DialogDirectiveInterceptor` | PRE | Applies scene dialog directives |
| 15 | `BedroomSceneInterceptor` | PRE | Bedroom-specific system prompt additions |
| 15 | `PhoneSceneInterceptor` | PRE | Phone scene prompt additions + ConversationHeat |
| 15 | `LoungeSceneInterceptor` | PRE | Lounge scene prompt additions |
| 20 | `AutoResultInjector` | PRE | Injects auto-triggered skill results |
| 30 | `SkillAwarenessInterceptor` | PRE | Lists REQUIRED / AVAILABLE tools for LLM |
| 35 | `GameSessionInterceptor` | PRE | Injects active game session state |
| 40 | `GameRulesInterceptor` | PRE | Injects game rules if game is active |
| 50 | `PersonalityGuardInterceptor` | PRE | Adds forbidden topics / required tone |
| 55 | `ConversationVarietyInterceptor` | PRE | Adjusts tone using ConversationHeat directives |
| 60 | `PolicyEnforcerInterceptor` | PRE | Enforces max token prompt reminder |
| 70 | `MemoryEnhancerInterceptor` | PRE | Injects top-k semantic memories from RAG |
| 80 | `ResponseShaperInterceptor` | POST | Strips leaked skill sections, trims reply |
| 85 | `TTSStyleInterceptor` | POST | Builds `ctx["tts_meta"]` for CosyVoice |
| 90 | `ActivityLoggerInterceptor` | POST | Logs interaction to database |
| 92 | `MoodSyncInterceptor` | POST | Strips `[MOOD:xxx]` tag, syncs to registry |

**Abort flag:** Any PRE interceptor can set `ctx["abort"] = True` to skip the LLM call entirely.

### Adding a Custom Interceptor

```python
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

class WeatherInjector(InterceptorBase):
    name     = "weather_injector"
    priority = 45

    def pre_call(self, ctx: ResponseContext) -> None:
        ctx["system_prompt"] += f"\n[Current weather: {fetch_weather()}]"

    def post_call(self, ctx: ResponseContext) -> None:
        pass

# Register
gov = get_governor(my_agent, scene="lounge")
gov.pipeline.add(WeatherInjector())    # sorted by priority
gov.pipeline.remove("weather_injector") # remove by name
```

---

## Port Map

### Scene Ports (Flask + SocketIO)

| Port | Scene | Description |
|------|-------|-------------|
| 5555 | phone (SIGNAL) | CosyPhone OS |
| 5556 | bedroom (THE PENTHOUSE) | Multi-agent spatial |
| 5557 | lounge (THE VELVET PIT) | Speakeasy |
| 5558 | tavern (THE RUSTY ANCHOR) | Fantasy tavern |
| 5559 | casino (CLUB NOIR) | Club Noir |
| 5560 | gallery (THE OBSCURA) | Art gallery |
| 5561 | arena (THE COLOSSEUM) | Tactical card game |
| 5562 | realm (THE SHATTERED THRONE) | LitRPG |
| 5563 | neoncity (NEON CITY) | Cyberpunk strategy |
| 5564 | coders (THE LAB) | Coding simulation |
| 5565 | heist (THE SCORE) | Cooperative heist |
| 5566 | command_center | Command Center |
| 5567 | games (THE ARCADE) | Games arcade |
| 5580 | intel_hub (THE BRIEFING ROOM) | Intelligence Hub |

### Dashboard Ports (Streamlit)

| Port | Dashboard | Description |
|------|-----------|-------------|
| 8500 | hub | Central dashboard |
| 8501 | dashboard | Metrics and monitoring |
| 8502 | admin | Admin panel (13 pages) |
| 8503 | assets | Asset generator |
| 8504 | creator | Content creator |

### Service Ports

| Port | Service | Protocol |
|------|---------|----------|
| 1234 | LMStudio | REST API (v1) |
| 8188 | ComfyUI | REST API |
| 8600 | Qwen3-TTS | FastAPI + FastMCP |
| 8700 | MCP Server | FastMCP |
| 8800 | NotebookLM Proxy | REST API |

---

## Inter-Agent Communication

### AgentRouter — Inbox Messaging

```python
from engine.mcp import get_router

router = get_router()
router.send("luna", "remind me of the deal", sender_id="player", meta={"priority": "high"})

messages = router.drain("luna")     # destructive read
messages = router.peek("luna")      # non-destructive
```

`RouterMessageInjector` (priority 10) automatically pipes pending messages into the system prompt before the LLM call.

### GameState — Observable Key/Value Store

```python
from engine.mcp import get_game_state

gs = get_game_state()
gs.set("blackjack-001", "player_score", 17)
gs.increment("blackjack-001", "player_score", 4)   # → 21
gs.subscribe("blackjack-001", on_score_change)      # observer
```

Observers fire synchronously. Exceptions in observers are silently swallowed.

---

## Architecture Principles

1. **If it's not in EventChain, it didn't happen.** Every service must propagate `chain_id`.
2. **Skills are the interface.** Agents talk to services through skills. Skills return strings.
3. **Graceful degradation.** Every external service has a placeholder/offline mode.
4. **Config over code.** Ports, URLs, models, thresholds — all in YAML.
5. **Framework ≠ content.** Engine is reusable. Scenes are examples.
6. **Test the ground truth.** EventChain tests are the most important tests.

---

## Module Exports Quick Reference

### `from engine.mcp import ...`

| Symbol | Type | Purpose |
|--------|------|---------|
| `get_governor` | function | Create/get a governor for an agent |
| `AgentGovernor` | class | Governance wrapper for any IAgent |
| `InterceptorBase` | class | Base for custom interceptors |
| `InterceptorPipeline` | class | Ordered interceptor container |
| `ResponseContext` | class | Dict-like context bag for one turn |
| `InteractionPolicy` | dataclass | Per-turn policy configuration |
| `GameState` | class | Game key/value store |
| `get_game_state` | function | Get singleton GameState |
| `AgentRouter` | class | Inter-agent message inbox |
| `get_router` | function | Get singleton AgentRouter |
| `SkillManifest` | class | Scene→skill registry |
| `get_skill_manifest` | function | Get singleton SkillManifest |
| `TRIGGER_AUTO` | str | Auto-fire each turn |
| `TRIGGER_OPTIONAL` | str | Available, LLM chooses |
| `TRIGGER_REQUIRED` | str | LLM must call this |

### `from engine.agents import ...`

| Symbol | Type | Purpose |
|--------|------|---------|
| `CharacterAgent` | class | Primary LLM conversational agent |
| `AgentLoop` | class | Multi-turn agent orchestrator |
| `SceneAgent` | class | Scene-level orchestration wrapper |
| `VirtualAgent` | class | State container + inference request building |
| `VirtualAgentManager` | class | Centralized inference router |
| `AgentGovernor` | class | Re-export from mcp |
| `get_governor` | function | Re-export from mcp |
| `IAgent` | Protocol | Structural interface contract |
| `AgentCapability` | Enum | Declared agent capabilities |

---

## Running the Project

```bash
pip install -e .

# Launch scenes
python launcher.py --mode phone      # Port 5555
python launcher.py --mode bedroom    # Port 5556
python launcher.py --mode hub        # Port 8500 (Streamlit)
python launcher.py --mode admin      # Port 8502 (Streamlit)

# Tests (75 tests)
python -m pytest tests/ -v --tb=short

# Health checks
python launcher.py --status
python launcher.py --init-db
```

**Hardware:** RTX 2060 12GB, VRAM cap 11.5GB.
**Environment:** Windows, Python 3.10.19, conda env "cosyvoice".

---

*Consolidates: STRUCTURE_GUIDE.md, MCP_ARCHITECTURE.md, AGENTS_GUIDE.md*
