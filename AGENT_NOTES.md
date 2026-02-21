# CosySim — Agent Notes & System Architecture

Generated: 2026-02-21T18:45:09Z

> Complete structural summary of the CosySim AI simulation framework.  
> Covers file dependencies, game loop, MCP skill system, scene architecture,  
> bus/integration layer, and LMStudio integration.

---

## Table of Contents

1. [File Dependency Order](#1-file-dependency-order)
2. [Game Loop & Logic Sequences](#2-game-loop--logic-sequences)
3. [MCP Skill System](#3-mcp-skill-system)
4. [Scene System](#4-scene-system)
5. [Bus System & Integration Layer](#5-bus-system--integration-layer)
6. [LMStudio Integration](#6-lmstudio-integration)
7. [Configuration & Admin](#7-configuration--admin)

---

## 1. File Dependency Order

### Layer 0 — Foundation (no internal dependencies)

| File | Provides |
|------|----------|
| `engine/config.py` | `get_config()` singleton, dot-notation YAML access, env var overrides |
| `engine/logging/cosy_logger.py` | Structured logging with scene/character context |
| `engine/logging/benchmark.py` | `@timed` decorator, timing KPIs |
| `engine/skills/chain_context.py` | Thread-local `chain_id` propagation for EventChain |

### Layer 1 — Data & Storage

| File | Provides | Depends On |
|------|----------|-----------|
| `content/simulation/database/db.py` | `Database` — SQLite CRUD for characters, states, conversations, memories, media. 9 tables. | config |
| `engine/assets/base.py` | `Asset` base class, UUID generation, serialization | — |
| `engine/assets/types.py` | `CharacterAsset`, `PersonalityAsset`, `RoleAsset`, `SceneAsset` | base |
| `engine/assets/advanced_types.py` | `AudioAsset`, `ImageAsset`, `VideoAsset`, `MessageAsset` | base |
| `engine/assets/manager.py` | `AssetManager` singleton — CRUD + query for all asset types | types, advanced_types |

### Layer 2 — Character & Spatial

| File | Provides | Depends On |
|------|----------|-----------|
| `content/simulation/character_system/character.py` | `Character` class — loads from DB, mood/energy/arousal state, personality | Database |
| `engine/spatial/location.py` | `Location` dataclass with props, actions, connections | — |
| `engine/spatial/scene_map.py` | `SceneMap` — grid of locations with movement + interaction | Location |

### Layer 3 — MCP Core (the backbone)

| File | Provides | Depends On |
|------|----------|-----------|
| `engine/skills/skill.py` | `@skill` decorator, `SkillMeta`, `SkillCategory`, `CooldownTracker`, `SkillPack` | — |
| `engine/skills/registry.py` | `SKILL_REGISTRY` singleton — global skill store | skill.py |
| `engine/skills/builtin/*.py` | 24 built-in skills across 8 packs (character, comfyui, environment, memory, narrative, social, tts, voice) | skill.py, registry.py |
| `engine/mcp/framework.py` | **MCPFramework** singleton: `MCPSceneNode`, `MCPCharacterNode`, `MCPSceneMixin`, `AgentProfile`, `FrameworkEvent`, event bus, timers, consequences, cross-scene messaging, state persistence | config, skill registry |
| `engine/mcp/character_registry.py` | `CharacterRegistry` — identity/mood/skills store for interceptors | — |
| `engine/mcp/scene_state.py` | `SceneStateManager` — wardrobe, stats (0-100), timed actions, narrative log | — |
| `engine/mcp/scene_rules_engine.py` | `SceneRulesEngine` — declarative rules, actions, permissions | scene_state |
| `engine/mcp/dialog_system.py` | `DialogSystem` — speech styles, dialog trees, response directives | — |
| `engine/mcp/interaction_trees.py` | `InteractionType` / `InteractionSubtype` — data-driven interaction definitions for bedroom/phone | — |
| `engine/mcp/game_mcp.py` | `MCPGameSession`, `MCPGameNode` — game session tracking with stat sync | framework, scene_state |

### Layer 4 — Governance Pipeline

| File | Provides | Depends On |
|------|----------|-----------|
| `engine/mcp/comms_framework.py` | `AgentGovernor`, `InterceptorPipeline`, `ResponseContext`, `SkillManifest`, `GameState`, `AgentRouter` | framework, character_registry, dialog_system, scene_rules |
| `engine/agents/interceptors.py` | 17 concrete interceptors (CharacterRegistry, DialogDirective, BedroomScene, PhoneScene, SkillAwareness, GameSession, PersonalityGuard, PolicyEnforcer, MemoryEnhancer, ResponseShaper, ActivityLogger, etc.) | comms_framework |

### Layer 5 — LLM Integration

| File | Provides | Depends On |
|------|----------|-----------|
| `engine/lmstudio/client.py` | `LMStudioManager` — CLI + SDK bridge, model load/unload, VRAM guard | config |
| `engine/lmstudio/model_manager.py` | `ModelManager` — load modes (CONCURRENT/JIT/JIT_TTL), agent sizing, runtime config | client, framework (agent profiles) |
| `engine/lmstudio/tool_factory.py` | `ToolSpec`, `run_with_tools()`, `@tool` — ephemeral function-calling | — |
| `engine/lmstudio/concurrency.py` | `ConcurrentExecutor` — parallel LLM requests with scatter/gather | client |

### Layer 6 — Agent Layer

| File | Provides | Depends On |
|------|----------|-----------|
| `engine/agents/character_agent.py` | `CharacterAgent` — RAG + system prompt + LLM call + EventChain logging + tool-calling | Character, Database, LMStudio, skills |
| `engine/agents/agent_loop.py` | `AgentLoop` — tick-based perceive→decide→execute cycle for multi-agent scenes | CharacterAgent, SceneMap |
| `engine/agents/scene_agent.py` | `SceneAgent` — scene-level director agent | CharacterAgent |

### Layer 7 — Services

| File | Provides | Depends On |
|------|----------|-----------|
| `engine/services/activity_bus.py` | `ActivityBus` — real-time activity tracking (thinking/tool_call/tts/image_gen) | — |
| `engine/services/housekeeping.py` | `HousekeepingService` — media ingest, health checks, integrity | Database, AssetManager |
| `engine/services/resilience.py` | Retry/circuit-breaker utilities | — |
| `engine/mcp/cosysim_server.py` | FastMCP server — exposes tools + resources to external LLM clients | framework, Database |
| `engine/mcp/web_bridge.py` | FastAPI proxy + MCP mount — SSE streaming, file upload | cosysim_server |

### Layer 8 — Scenes (content)

| File | Provides | Depends On |
|------|----------|-----------|
| `engine/scenes/base_scene.py` | `BaseScene` — Flask app factory, character load/unload, save/restore | AssetManager, framework |
| `content/scenes/phone/phone_scene_v2.py` | `PhoneSceneV2` — messaging companion with autotxt, games | BaseScene, MCPSceneMixin, AgentGovernor |
| `content/scenes/phone/phone_rules_v2.py` | Phone rules — heat gates, autonomous cooldowns, truth-or-dare | SceneRulesEngine |
| `content/scenes/bedroom/bedroom_scene.py` | `BedroomScene` — multi-agent intimate roleplay with wardrobe/stats | BaseScene, MCPSceneMixin, AgentLoop, SceneMap |
| `content/scenes/bedroom/bedroom_rules.py` | Bedroom rules — intimacy gates, actions, director controls | SceneRulesEngine |
| `content/scenes/lounge/lounge_scene.py` | `LoungeScene` — 1920s speakeasy with Lola & Viktor | BaseScene, MCPSceneMixin |
| `content/scenes/casino/casino_scene.py` | `CasinoScene` — noir poker night (framework showcase) | BaseScene, MCPSceneMixin |
| `content/scenes/hub/hub_scene.py` | Hub — Streamlit launcher/dashboard | AssetManager, config |
| `content/scenes/admin/admin_panel.py` | Admin — Streamlit asset/config manager | AssetManager, config |

---

## 2. Game Loop & Logic Sequences

### 2.1 Phone Scene — Message Loop

```
User types message
    │
    ▼
POST /api/thread/<id>/send
    │
    ├── Save user message to PhoneDB
    ├── Emit "message_new" via SocketIO
    │
    └── Spawn _reply_worker (background thread)
            │
            ├── For each character in thread:
            │     │
            │     ├── Emit typing indicator (active: true)
            │     ├── Sleep 0.5-2s (natural delay)
            │     │
            │     ├── _generate_reply(char_id, content)
            │     │     │
            │     │     ├── Refresh character state from DB
            │     │     ├── Wrap in AgentGovernor
            │     │     │     ├── pre-call interceptors run:
            │     │     │     │   ├── CharacterRegistry: inject identity/mood
            │     │     │     │   ├── PhoneSceneInterceptor: inject heat/stats
            │     │     │     │   ├── SkillAwareness: list available tools
            │     │     │     │   ├── PersonalityGuard: tone guidance
            │     │     │     │   └── PolicyEnforcer: length/topic limits
            │     │     │     │
            │     │     │     ├── CharacterAgent.reply()
            │     │     │     │   ├── RAG memory search
            │     │     │     │   ├── Build system prompt (persona + memories)
            │     │     │     │   ├── LLM call via lmstudio SDK
            │     │     │     │   └── Log to EventChain
            │     │     │     │
            │     │     │     └── post-call interceptors:
            │     │     │         ├── ResponseShaper: trim/reshape
            │     │     │         └── ActivityLogger: log to EventChain
            │     │     │
            │     │     └── Return reply text
            │     │
            │     ├── Save AI message to PhoneDB
            │     ├── Emit typing indicator (active: false)
            │     └── Emit "message_new" via SocketIO
            │
            └── (next character in thread, if group chat)
```

### 2.2 Phone Scene — Autonomous Text Loop

```
_start_ticker() → spawn background thread
    │
    └── _ticker_loop() (every 10 seconds):
            │
            ├── For each character with scheduled deadline:
            │     │
            │     ├── Is deadline passed?
            │     │     │
            │     │     YES → _fire_autotxt(char_id)
            │     │     │       ├── Generate reply (same pipeline as above)
            │     │     │       ├── Save to PhoneDB
            │     │     │       ├── Broadcast via SocketIO
            │     │     │       └── _schedule_autotxt(char_id)
            │     │     │             └── Calculate new deadline:
            │     │     │                   trust → base cooldown
            │     │     │                   affection → modifier
            │     │     │                   Result: 20s - 30min
            │     │     │
            │     │     NO → skip
            │     │
            └── sleep(10)
```

### 2.3 Bedroom Scene — Agent Loop Cycle

```
AgentLoop.start(interval=30)
    │
    └── _run() thread loop:
            │
            ├── For each registered character (round-robin):
            │     │
            │     ├── _perceive(char_id)
            │     │     ├── Current location + nearby characters
            │     │     ├── Recent shared_log entries (last 20)
            │     │     ├── Active story beats
            │     │     ├── Props in room + inventory
            │     │     ├── Own stats (arousal, happiness, etc.)
            │     │     └── Other characters' visible state
            │     │
            │     ├── _decide(char_id, perception)
            │     │     ├── Build system prompt:
            │     │     │   ├── Character persona + traits
            │     │     │   ├── Perception context
            │     │     │   ├── Available actions (from location)
            │     │     │   └── "Respond as JSON: {action, target, message}"
            │     │     │
            │     │     ├── Call LLM via AgentGovernor
            │     │     │     └── Full interceptor pipeline
            │     │     │
            │     │     └── Parse JSON action from response
            │     │
            │     ├── _execute(char_id, action)
            │     │     ├── "speak" → add to shared_log, emit chat_message
            │     │     ├── "move" → update location, log movement
            │     │     ├── "interact" → apply prop effects, log
            │     │     ├── "kiss/touch/intimate" → apply stat drifts
            │     │     └── "idle" → small stat decay
            │     │
            │     └── _on_agent_action() callback
            │           ├── Apply stat_drifts to character profiles
            │           ├── Pop first story beat (if any)
            │           ├── Emit chat_message to SocketIO
            │           └── Broadcast full scene_state
            │
            ├── MCPFramework.tick("bedroom")
            │     ├── Increment turn counter
            │     ├── Fire due consequences
            │     └── Emit "scene_tick" event
            │
            └── sleep(interval)
```

### 2.4 Stat Drift & Consequence Flow

```
Action happens (speak/kiss/intimate/etc.)
    │
    ├── Immediate stat drifts:
    │     speak → tiredness +1
    │     kiss → arousal +5, pleasure +3
    │     intimate → arousal +15, pleasure +10, openness +5
    │     idle → tiredness +2, arousal -1
    │
    ├── Prop effects (from interaction):
    │     "+20 pleasure +10 arousal" → parse → apply 50% to all chars
    │
    ├── Outfit effects:
    │     lingerie/nothing → arousal +10, explicitness +5
    │
    └── Scheduled consequences:
          schedule_consequence("mood_shift", {mood: "suspicious"},
                              trigger_after_turns=3)
          │
          └── On tick() after 3 turns:
                ├── Fire consequence
                ├── Apply effects
                └── Log to narrative
```

---

## 3. MCP Skill System

### 3.1 What It Is

The MCP (Model Context Protocol) skill system is a **structured tool-calling framework** that gives LLM agents controlled access to the simulation world. Instead of giving the LLM free-form access to everything, skills are:

- **Registered** — declared via `@skill` decorator at module load time
- **Categorized** — grouped by function (COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM, NARRATIVE)
- **Gated** — cooldowns, prerequisites, cost weights limit abuse
- **Manifested** — per-scene skill manifests control which skills are available where
- **Triggered** — three trigger types control when skills execute

### 3.2 How It Functions

```
@skill decorator
    │
    ├── Creates SkillMeta (name, pack, description, tags, category,
    │                       cooldown_secs, prerequisites, cost)
    │
    ├── Registers in SKILL_REGISTRY singleton
    │     └── Indexed by name and pack
    │
    └── Function remains unchanged (no wrapper overhead)

At scene startup:
    │
    ├── SkillManifest loads config/skill_manifests.yaml
    │     └── Maps scene → skill names + trigger types
    │
    └── AgentGovernor reads manifest for each reply() call

During an LLM call:
    │
    ├── SkillAwarenessInterceptor (pre-call, priority 30):
    │     ├── Reads manifest for current scene
    │     ├── Collects "optional" skills → converts to OpenAI tool specs
    │     ├── Collects "required" skills → adds to tool list + prompt reminder
    │     ├── Checks cooldowns via COOLDOWN_TRACKER
    │     └── Injects available_tools into ResponseContext
    │
    ├── AutoResultInjector (pre-call, priority 20):
    │     ├── Finds "auto" skills in manifest
    │     ├── Executes them immediately (before LLM sees anything)
    │     └── Injects results into system prompt
    │
    ├── LLM generates response (may include tool_calls)
    │     └── tool_factory.execute_tool_calls() runs them
    │         └── Results fed back to LLM for final response
    │
    └── ActivityLoggerInterceptor (post-call, priority 90):
          └── Logs skill usage to EventChain
```

### 3.3 Skill Trigger Types

| Trigger | When | Who Decides | Example |
|---------|------|------------|---------|
| `auto` | Before every LLM call | System | `search_memory`, `get_character_scene_stats` |
| `optional` | During LLM call | The LLM | `mood_contagion`, `generate_image`, `inject_story_beat` |
| `required` | During LLM call | Enforced | `set_game_state` (must record game result) |

### 3.4 Why This Architecture

**Agent Control on Both Sides:**

The skill system creates a **sandwich of control** around the LLM:

```
┌─────────────────────────────────────────┐
│  PRE-CALL (system-controlled)           │
│  • Auto skills inject ground truth      │
│  • Rules engine checks permissions      │
│  • Character identity injected          │
│  • Dialog directives applied            │
├─────────────────────────────────────────┤
│  LLM GENERATION (agent freedom)         │
│  • Agent chooses from optional tools    │
│  • Agent decides tone, content, action  │
│  • Agent may use 0 or many tools        │
├─────────────────────────────────────────┤
│  POST-CALL (system-controlled)          │
│  • Response shaped to fit policy        │
│  • Stats updated from actions           │
│  • Activity logged to EventChain        │
│  • Speech enhanced to match voice       │
└─────────────────────────────────────────┘
```

This gives the illusion of autonomous agents while maintaining:
- **Consistency** — characters stay in-persona via PersonalityGuard
- **Safety** — PolicyEnforcer blocks forbidden topics
- **Continuity** — auto skills ensure the agent always knows current state
- **Progression** — stat gates control what actions become available
- **Auditability** — every tool call logged in EventChain

### 3.5 State Management

**Three-tier state:**

1. **SceneStateManager** (engine/mcp/scene_state.py)
   - Per-character stats: 12 dimensions (arousal, happiness, anger, fear, etc.) on 0-100 scale
   - Wardrobe: layered clothing with progressive removal
   - Timed actions: multi-phase activities (striptease, massage)
   - Narrative log: rolling event journal

2. **CharacterRegistry** (engine/mcp/character_registry.py)
   - Identity: name, age, appearance, personality vector, voice style
   - Runtime state: mood, focus, restrictions, energy, inhibition
   - Skills: named capabilities with enabled/disabled flags

3. **MCPFramework** (engine/mcp/framework.py)
   - Scene membership: which characters are in which scenes
   - Cross-scene inbox: messages between characters in different scenes
   - Timers: passive countdown timers (turn-driven)
   - Consequences: deferred effects queued for N turns in the future
   - Event log: bounded history of all framework events
   - State persistence: JSON snapshot to survive restarts

**State flows downward:**
```
MCPFramework (global truth)
    ↓
MCPSceneNode (scene-level truth)
    ↓
CharacterRegistry + SceneStateManager (character-level truth)
    ↓
InterceptorPipeline (injected into LLM context)
    ↓
LLM (reads state, decides action)
    ↓
Action callback (updates state back up the chain)
```

### 3.6 How LMStudio v1 API Is Used

CosySim talks to LMStudio via the **OpenAI-compatible v1 API**:

```python
# Text generation (no tools)
POST http://localhost:1234/v1/chat/completions
{
    "model": "qwen3-30b-a3b",
    "messages": [
        {"role": "system", "content": "You are Aria, a warm and playful companion..."},
        {"role": "user", "content": "Hey, what are you up to?"}
    ],
    "temperature": 0.85,
    "max_tokens": 4096
}

# Tool-calling (function-calling)
POST http://localhost:1234/v1/chat/completions
{
    "model": "qwen3-30b-a3b",
    "messages": [...],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Search past conversations",
                "parameters": {"type": "object", "properties": {...}}
            }
        }
    ]
}
# Response may include tool_calls → execute → feed results → re-call
```

**Two calling paths:**

1. **SDK path** (`lmstudio` Python package):
   - `lms.llm(model).respond(chat)` — text-only
   - `lms.llm(model).act(chat, tools)` — with tool-calling loop
   - Used by `CharacterAgent.reply()`

2. **REST path** (`tool_factory.run_with_tools()`):
   - Direct HTTP via `httpx` to `/v1/chat/completions`
   - Manual tool-call loop (up to 6 rounds)
   - Used by `CharacterAgent._reply_via_rest()` and one-off queries

**Model management:**
- `ModelManager` handles load/unload via LMStudio CLI (`lms load`, `lms unload`)
- Three modes: CONCURRENT (one model, parallel slots), JIT (load on demand), JIT_TTL (auto-evict after idle)
- VRAM guard: estimates model VRAM needs, refuses to load if it would exceed cap (11,500 MB for RTX 2060 12GB)

---

## 4. Scene System

### 4.1 What a Scene Is

A scene is a **self-contained Flask+SocketIO application** that runs on its own port. Each scene:
- Has its own HTML UI served via Jinja2 templates
- Manages its own characters and conversation state
- Registers with MCPFramework for cross-scene communication
- Defines its own rules via SceneRulesEngine
- Has a skill manifest declaring which tools its agents can use

### 4.2 Scene Class Hierarchy

```
BaseScene (engine/scenes/base_scene.py)
    │
    ├── Flask app factory
    ├── Character load/unload lifecycle
    ├── Asset save/restore
    └── _mcp_register_scene()

MCPSceneMixin (engine/mcp/framework.py)
    │
    ├── _mcp_init() → registers scene + loads rules
    ├── .mcp property → MCPSceneNode
    ├── mcp_on_enter(char_id) → track character entry
    └── mcp_on_leave(char_id) → track character departure

Your Scene (content/scenes/X/X_scene.py)
    │
    class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
        def __init__(self): ...; self._mcp_init()
        def start(self): ...
        def stop(self): get_framework().save_state(); ...
```

### 4.3 Creating a New Scene — Walkthrough

**Step 1: Directory structure**
```
content/scenes/my_scene/
├── __init__.py
├── my_scene.py           # Scene class
├── my_scene_rules.py     # MCP rules registration
├── templates/
│   └── my_scene.html     # Jinja2 UI template
└── static/
    ├── css/my_scene.css
    └── js/my_scene.js
```

**Step 2: Define rules** (`my_scene_rules.py`)
```python
from engine.mcp.scene_rules_engine import get_scene_rules_engine

def register_my_scene_rules(scene_node):
    engine = get_scene_rules_engine()

    # Actions characters can take
    engine.add_action("my_scene", "greet", {
        "description": "Greet the player warmly",
        "conditions": {},  # always available
        "effects": [{"type": "stat_adjust", "target": "happiness", "delta": 5}]
    })

    engine.add_action("my_scene", "share_secret", {
        "description": "Share a personal secret",
        "conditions": {"trust": 60},  # requires trust ≥ 60
        "effects": [{"type": "stat_adjust", "target": "trust", "delta": 10}]
    })

    # Rules (always-on, triggered, or director-only)
    engine.add_rule("my_scene", "warmth_gate", {
        "type": "triggered",
        "conditions": {"warmth": 50},
        "effects": [{"type": "add_narrative", "text": "The atmosphere grows warmer..."}]
    })
```

**Step 3: Create scene class** (`my_scene.py`)
```python
from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework

class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
    def __init__(self):
        super().__init__(
            scene_id="my_scene",
            template_folder="templates",
            static_folder="static",
            host="localhost",
            port=5560
        )
        # Setup characters, routes, socket handlers
        self._setup_routes()
        self._setup_socketio()
        self._mcp_init()  # MUST be last

    def start(self):
        fw = get_framework()
        self.mcp_on_enter("npc_a")
        self.mcp_on_enter("npc_b")
        fw.on("story_beat", self._on_story_beat)
        fw.on("mood_contagion", self._on_mood)
        super().start()

    def stop(self):
        get_framework().save_state()
        super().stop()
```

**Step 4: Add to config** (`config/default.yaml`)
```yaml
scenes:
  my_scene:
    port: 5560
    characters: ["npc_a", "npc_b"]
```

**Step 5: Add skill manifest** (`config/skill_manifests.yaml`)
```yaml
scenes:
  my_scene:
    - name: search_memory
      trigger: auto
      when: always
    - name: get_character_scene_stats
      trigger: auto
      when: always
    - name: mood_contagion
      trigger: optional
      when: always
```

**Step 6: Add to launcher** (`launcher.py`)
```python
elif args.mode == "my_scene":
    from content.scenes.my_scene.my_scene import MyScene
    MyScene().start()
```

### 4.4 Cross-Scene Linking

Scenes communicate through the MCPFramework event bus and cross-scene messaging:

```python
# Scene A sends message to character in Scene B
fw.cross_scene_send(
    from_char="npc_a", from_scene="my_scene",
    to_char="aria", to_scene="phone",
    message="Hey, come check this out!",
    message_type="invite"
)

# Scene B's character picks it up on next tick
messages = fw.get_cross_scene_inbox("aria")

# Or use the event bus for broadcast communication
fw.emit_event("world_event", {
    "type": "power_outage",
    "affects": ["phone", "bedroom", "my_scene"]
}, source="my_scene")
```

### 4.5 Nudging & Controlling Agents

**Nudging** (soft guidance — agent can deviate):
- **System prompt injection**: Personality traits, mood description, recent context
- **Story beats**: Narrative hints injected into context ("Aria is feeling distant today")
- **Dialog options**: Weighted choices the LLM can pick from
- **Autonomous text cooldowns**: Trust-based timing creates natural conversation rhythm

**Controlling** (hard enforcement — agent cannot deviate):
- **Required skills**: LLM must call specific tools before replying
- **PolicyEnforcer**: Hard reply length limits, forbidden topic blocking
- **PersonalityGuard**: In-character tone enforcement
- **Stat gates**: Actions physically unavailable below stat thresholds
- **PermissionMatrix**: Per-character action allow/deny lists
- **ResponseShaper**: Post-call trimming/reshaping

**Intercepting** (modify the response after generation):
- **DialogDirective**: If `force_response` set, skip LLM entirely and return canned text
- **ResponseShaper**: Trim to max_length, remove out-of-character fragments
- **SpeechEnhancer**: Apply voice style (playful, dominant, vulnerable, etc.)
- **MoodSync**: Adjust emotional markers in response to match current state

```
Example: Escalating intimacy in bedroom scene

1. Characters start with low arousal (20)
2. "kiss" action requires arousal ≥ 30 (stat gate)
3. Casual conversation with stat drifts gradually raises arousal
4. At arousal 30, kiss becomes available in the actions list
5. LLM sees kiss as an option and may choose it
6. Kiss applies +5 arousal, +3 pleasure
7. At arousal 55, "striptease" unlocks
8. Director can inject story beat: "The lights dim suggestively"
9. This nudges the agent toward the new options
10. At arousal 70, full intimacy unlocks
```

---

## 5. Bus System & Integration Layer

### 5.1 The Three Bus Systems

CosySim has three complementary communication channels:

#### A. MCPFramework Event Bus (framework.py)
- **Scope**: Global, all scenes and characters
- **Pattern**: Pub/sub with typed events
- **Usage**: Lifecycle events, cross-scene notifications, state change broadcasts
- **API**: `fw.on(event_type, callback)`, `fw.emit_event(type, payload, source)`
- **Built-in events**: `framework_ready`, `scene_registered`, `character_registered`, `scene_tick`, `state_saved`, `state_loaded`

#### B. ActivityBus (activity_bus.py)
- **Scope**: Global, all agents
- **Pattern**: Push/pop activity stack with history
- **Usage**: Real-time status display ("Aria is thinking...", "Generating image...")
- **API**: `bus.push(Activity(...))` → token, `bus.pop(token)`, `bus.activity()` context manager

#### C. AgentRouter (comms_framework.py)
- **Scope**: Inter-agent within governance pipeline
- **Pattern**: Named mailbox (send/receive)
- **Usage**: Agent A sends message to Agent B for next tick
- **API**: `router.send(target_id, message)`, inbox drained by `RouterMessageInjector`

### 5.2 MCP Skills Integration with LMStudio

```
                    ┌──────────────────┐
                    │   LMStudio       │
                    │   (localhost:1234)│
                    └────────┬─────────┘
                             │ OpenAI v1 API
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼─────────┐      ┌────────────▼────────────┐
    │  SDK Path          │      │  REST Path               │
    │  lms.llm().act()   │      │  tool_factory.           │
    │  (tool loop in SDK)│      │  run_with_tools()        │
    └─────────┬─────────┘      │  (manual 6-round loop)   │
              │                 └────────────┬────────────┘
              │                              │
              └──────────────┬───────────────┘
                             │
                    ┌────────▼────────┐
                    │  Tool Execution  │
                    │                  │
                    │  @skill funcs    │ ← SKILL_REGISTRY
                    │  @tool funcs     │ ← ToolFactory (ephemeral)
                    │  MCP server tools│ ← FastMCP (external)
                    └──────────────────┘
```

### 5.3 The Three Tool Systems

| System | Registration | Lifetime | Execution | Use Case |
|--------|-------------|----------|-----------|----------|
| **@skill** (registry) | `@skill(pack="X")` at import | Permanent | In-process | Core game mechanics |
| **@tool** (factory) | `from_callable()` | Per-request | In-process | One-off agent tools |
| **FastMCP** (server) | `@mcp.tool()` | Server lifetime | Network hop | External LLM clients |

### 5.4 MCP Server as Ephemeral Bridge

The `cosysim_server.py` FastMCP server can be mounted as an **ephemeral MCP server** inside LMStudio:

```
LMStudio loads model
    ↓
Model config references MCP server: http://localhost:8700/mcp/sse
    ↓
LMStudio connects via SSE (Server-Sent Events)
    ↓
LLM can now call CosySim tools directly:
    - search_memory(query, char_id)
    - get_character_state(char_id)
    - adjust_relationship(char_a, char_b, field, delta)
    - generate_image(prompt, w, h)
    - log_event(chain_id, type, actor, summary)
    - roll_dice(sides, count)
    ↓
Results flow back through SSE to LLM context
```

This creates a **bidirectional bridge**: CosySim calls LMStudio for generation, and LMStudio calls CosySim for world state. The `web_bridge.py` FastAPI app also proxies chat requests and exposes an SSE streaming endpoint for web UIs.

### 5.5 Game MCP Integration

```
Game starts (via API or story beat)
    ↓
MCPGameSession created in game_mcp.py
    ├── Session ID, game type, scene ID, player list
    ├── Turn history (GameTurnEntry list)
    └── Stat sync map (game events → character stat deltas)
    ↓
GameSessionInterceptor (priority 35) activates:
    ├── pre_call: inject game state + available actions into prompt
    ├── Detects [GAME_ACTION:xxx] markers in LLM response
    └── post_call: log action, apply stat sync, broadcast
    ↓
GameRulesInterceptor (priority 40):
    ├── Inject game-specific rules
    └── Add required tools (e.g., roll_dice for truth-or-dare)
    ↓
On game end:
    ├── Session archived
    ├── Post-game consequence scheduled (e.g., mood shift)
    └── Stats finalized
```

---

## 6. LMStudio Integration

### 6.1 Connection Architecture

```
CosySim Python Process
    │
    ├── LMStudioManager (client.py)
    │     ├── CLI interface: lms load, lms unload, lms ps
    │     ├── HTTP probe: GET /v1/models
    │     └── SDK client: lmstudio.LMStudio(base_url)
    │
    ├── ModelManager (model_manager.py)
    │     ├── Load modes: CONCURRENT / JIT / JIT_TTL
    │     ├── VRAM guard: 11,500 MB cap (RTX 2060 12GB)
    │     ├── Agent profiles: big → 16K ctx, small → 4K ctx
    │     └── Session tracking: loaded_at, last_used_at, request_count
    │
    ├── ConcurrentExecutor (concurrency.py)
    │     ├── ThreadPoolExecutor with configurable workers
    │     ├── scatter(): same prompt → N models
    │     ├── gather(): wait for all, return ordered
    │     └── stream_results(): yield as they complete
    │
    └── ToolFactory (tool_factory.py)
          ├── Ephemeral tool specs from callables
          ├── run_with_tools(): 6-round tool-call loop
          └── OpenAI-compatible tool schema generation
```

### 6.2 Model Loading Strategies

| Mode | Behavior | Best For |
|------|----------|----------|
| **CONCURRENT** | Load one model at startup, serve N parallel requests | Single powerful model, multiple agents |
| **JIT** | Load on demand, evict previous model before loading new | Different models per agent role |
| **JIT_TTL** | Load on demand, auto-unload after idle timeout | Memory-constrained multi-model |

### 6.3 Agent Profile → Model Mapping

```python
agent_profiles:
  big:           # Main conversation agent
    model: "qwen3-30b-a3b"
    context_length: 16384
    max_tokens: 4096
    temperature: 0.85

  small:         # Quick decisions, narration
    model: "qwen3-8b"
    context_length: 4096
    max_tokens: 1024
    temperature: 0.7

  router:        # Intent classification
    model: "qwen3-8b"
    context_length: 2048
    max_tokens: 256
    temperature: 0.3

  narrator:      # Scene prose, descriptions
    model: "qwen3-30b-a3b"
    context_length: 8192
    max_tokens: 2048
    temperature: 0.9

  game_master:   # Rule enforcement, game logic
    model: "qwen3-14b"
    context_length: 4096
    max_tokens: 512
    temperature: 0.5
```

---

## 8. Phase 2 — MCP Integration Upgrade

### What Changed (Phone Scene)

The phone scene (`content/scenes/phone/phone_scene_v2.py`) now:

1. **MCP state sync**: Characters are registered with the framework via `enter_scene()` on load
2. **Event bus integration**: Every message (user reply and autotxt) emits a `message_sent` event through the framework event bus
3. **Framework tick**: The ticker loop calls `fw.tick(SCENE_ID)` each cycle to process MCP timers and consequences
4. **MCP admin API**: 6 new endpoints under `/api/mcp/*` expose framework status, agent profiles, event logs, timers, consequences, and LMStudio config
5. **Skill packs**: Plugin info now declares `["memory", "character", "social", "narrative"]` skill packs

### What Changed (Bedroom Scene)

The bedroom scene (`content/scenes/bedroom/bedroom_scene.py`) now:

1. **`_sync_to_mcp()` method**: Every `_broadcast_state()` call also pushes character stats, outfit, position, personality, and scene state into the MCP framework
2. **Typed events**: Key actions emit named events through the framework bus:
   - `stat_adjusted`, `outfit_changed`, `position_changed`, `character_moved`
   - `scenario_started`, `scene_event`, `agent_action`
3. **Agent profiles**: Agent loop creation checks MCP agent profiles for model hints
4. **MCP admin API**: 5 new endpoints for framework status, scene state, event log, LMStudio, and runtime config
5. **Version bumped to 4.1.0** with `"mcp"` tag

### What Changed (MCPFramework Core)

`engine/mcp/framework.py` additions:

1. **`MCPSceneNode.update_state(data)`** — Merge arbitrary key-value pairs into scene-level MCP state
2. **`MCPSceneNode.get_state()`** — Return the scene's MCP state dict
3. **`MCPCharacterNode.update_state(data)`** — Push state updates to the CharacterRegistry

### Duplicate Skill Fix

`tts_skills.py:generate_voice_message` renamed to `tts_generate_voice` to avoid Python-level collision with `voice_skills.py:generate_voice_message`. Both skills are still registered in their respective packs ("tts" and "voice").

### MCP API Endpoints (Available on All Scenes)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/mcp/status` | GET | Framework status (turn, scenes, characters, timers, consequences) |
| `/api/mcp/scene-state` | GET | Scene's MCP state dict |
| `/api/mcp/event-log` | GET | Recent framework events (filterable by type, limit) |
| `/api/mcp/timers` | GET | Active MCP timers |
| `/api/mcp/consequences` | GET | Pending consequences for this scene |
| `/api/mcp/lmstudio` | GET | LMStudio connection config and status |
| `/api/mcp/config` | GET/POST | Read/update runtime config (agent_profiles, framework, scene settings) |
    model: "qwen3-30b-a3b"
    context_length: 12288
    max_tokens: 3072
    temperature: 0.75
```

### 6.4 Context Window Management

The system ensures each agent has enough context by:

1. **Profile-based allocation**: Agent profiles define context_length per role
2. **Memory injection budget**: RAG results are top-k limited (usually 5-10 results)
3. **History truncation**: Shared log is windowed (last 20 entries for perception)
4. **System prompt budgeting**: Fixed-size character persona + variable context
5. **Max token enforcement**: PolicyEnforcer limits response length

```
Total context budget (e.g., 16,384 tokens for "big" agent):
├── System prompt:    ~2,000 tokens (character persona + rules)
├── RAG memories:     ~1,500 tokens (top-5 × ~300 each)
├── Interceptor context: ~2,000 tokens (stats, wardrobe, narrative, skills list)
├── Conversation history: ~6,000 tokens (last 20 messages)
├── Tool schemas:     ~1,000 tokens (available tools definitions)
└── Generation budget: ~3,884 tokens (max_tokens setting)
```

---

## 7. Configuration & Admin

### 7.1 Config Structure (config/default.yaml)

```yaml
system:
  name: "CosySim AI Playground"
  version: "2.0.0"

database:
  sqlite: simulation.db
  chromadb: chroma_db

llm:
  provider: lmstudio
  base_url: http://localhost:1234/v1
  model: qwen3-vl-8b

lmstudio:
  host: http://localhost:1234
  load_mode: concurrent          # concurrent | jit | jit_ttl
  vram_cap_mb: 11500
  default_gpu_fraction: 0.85
  jit_ttl_seconds: 300
  concurrent_max_slots: 4

mcp:
  port: 8700
  governance_enabled: true

scenes:
  phone:     { port: 5555, characters: [...] }
  bedroom:   { port: 5556, characters: [...] }
  lounge:    { port: 5557, characters: [...] }
  casino:    { port: 5559, characters: [...] }

agent_profiles:
  big:         { model: qwen3-30b-a3b, context_length: 16384, ... }
  small:       { model: qwen3-8b, context_length: 4096, ... }
  router:      { model: qwen3-8b, context_length: 2048, ... }
  narrator:    { model: qwen3-30b-a3b, context_length: 8192, ... }
  game_master: { model: qwen3-30b-a3b, context_length: 12288, ... }

framework:
  state_persistence: true
  state_file: data/mcp_framework_state.json
  max_event_log: 500
  max_consequence_age_turns: 50

comfyui:
  host: http://localhost:8188
  generation: { steps: 20, cfg: 7.0, width: 512, height: 768, ... }

tts:
  host: http://localhost:8600
  model: cosyvoice2
```

### 7.2 Environment Variable Overrides

Any config key can be overridden via environment variable:
```
COSYSIM_LMSTUDIO_HOST=http://remote:1234
COSYSIM_LLM_MODEL=different-model
COSYSIM_SCENES_PHONE_PORT=6666
```

### 7.3 Port Allocation

| Port | Service |
|------|---------|
| 1234 | LMStudio (external) |
| 5555 | Phone Scene |
| 5556 | Bedroom Scene |
| 5557 | Lounge Scene |
| 5559 | Casino Scene |
| 8188 | ComfyUI (external) |
| 8500 | Hub (Streamlit) |
| 8501 | Dashboard (Streamlit) |
| 8502 | Admin Panel (Streamlit) |
| 8503 | Asset Generator (Streamlit) |
| 8600 | TTS Server |
| 8601 | Web Bridge |
| 8700 | MCP Server |

### 7.4 Admin Panel

The admin panel (Streamlit, port 8502) provides:
- **Dashboard**: Asset counts, character stats, scene status
- **Asset Browser**: CRUD for all 8 asset types (Character, Personality, Role, Scene, Audio, Image, Video, Message)
- **Character Manager**: Full character editor (traits, personality, appearance, mood)
- **Config Inspector**: View/edit YAML configuration
- **Log Viewer**: Diagnostic event streams

### 7.5 Testing

```bash
# Core tests (fast, always pass)
python -m pytest tests/test_config.py tests/test_skills.py tests/test_event_chain.py -v --tb=short

# Full suite (some tests may hang due to LMStudio dependency)
python -m pytest tests/ -v --tb=short --timeout=30
```

Test coverage:
- Config dot-notation + env overrides (5 tests)
- Skill decorator + pack registration (3 tests)
- Chain context thread-local (3 tests)
- EventChain tree/query (12 tests)

---

## Appendix: Key Singletons

| Singleton | Module | Accessor |
|-----------|--------|----------|
| MCPFramework | engine.mcp.framework | `get_framework()` |
| SKILL_REGISTRY | engine.skills.registry | Direct import |
| COOLDOWN_TRACKER | engine.skills.skill | Direct import |
| LMStudioManager | engine.lmstudio.client | `get_lmstudio_manager()` |
| ModelManager | engine.lmstudio.model_manager | `get_model_manager()` |
| SceneStateManager | engine.mcp.scene_state | `get_scene_state_manager()` |
| SceneRulesEngine | engine.mcp.scene_rules_engine | `get_scene_rules_engine()` |
| CharacterRegistry | engine.mcp.character_registry | `get_character_registry()` |
| DialogSystem | engine.mcp.dialog_system | `get_dialog_system()` |
| ActivityBus | engine.services.activity_bus | `get_activity_bus()` |
| AgentRouter | engine.mcp.comms_framework | `get_router()` |
| GameState | engine.mcp.comms_framework | `get_game_state()` |
| ConcurrentExecutor | engine.lmstudio.concurrency | `get_executor()` |
