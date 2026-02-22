# CosySim — Agent Notes & System Architecture

Generated: [2026-02-22T23:00:00Z] — v3.1.0

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
8. [Phase 2 — MCP Integration Upgrade](#8-phase-2--mcp-integration-upgrade)
9. [Phase 3 — LMStudio v1 Native Integration & Control Overlay](#9-phase-3--lmstudio-v1-native-integration--control-overlay)
10. [Phase 4 — v2 Framework (v1-Only Migration)](#10-phase-4--v2-framework-v1-only-migration)
11. [Phase 5 — VirtualAgent Framework](#11-phase-5--virtualagent-framework)
12. [Phase 6 — v2.5 Framework Push](#12-phase-6--v25-framework-push)
13. [Phase 7 — v2.7 LMStudio Native Upgrade](#13-phase-7--v27-lmstudio-native-upgrade)
14. [Phase 10 — v3.1 Showcase Scenes & MCP Skills Expansion](#16-phase-10--v31-showcase-scenes--mcp-skills-expansion)

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

---

## 9. Phase 3 — LMStudio v1 Native Integration & Control Overlay

### 9.1 New Modules

| Module | File | Purpose |
|--------|------|---------|
| **InferenceConfig** | `engine/lmstudio/inference_config.py` | Typed dataclass for all inference params (temperature, top_p, top_k, min_p, repeat_penalty, max_output_tokens, reasoning, structured output, draft_model, stateful chat, image input, MCP integrations) |
| **LoadConfig** | `engine/lmstudio/inference_config.py` | Typed dataclass for model loading (context_length, gpu_offload, flash_attention, eval_batch_size, kv_cache, num_experts, ttl) |
| **LMSClient** | `engine/lmstudio/lms_client.py` | Primary REST client. Uses **only** native `/api/v1/chat` (v2 framework — OpenAI compat removed). Stateful chats, structured output, streaming, MCP integrations. Singleton via `get_lms_client()` |
| **LMSSDKWrapper** | `engine/lmstudio/lms_sdk.py` | Python SDK wrapper: `respond()`, `act()` (multi-round tools), `complete()` (raw completion), model info. Singleton via `get_lms_sdk()` |
| **ResourceManager** | `engine/lmstudio/resource_manager.py` | 6-strategy model lifecycle manager: SINGLE_BIG, CONCURRENT, MULTI_SMALL, JIT_SWAP, SPECULATIVE, HYBRID. GPU budget tracking, TTL reaper, background task queue. Singleton via `get_resource_manager()` |
| **Control Overlay** | `engine/overlay/overlay_bp.py` | Flask Blueprint with ~20 API endpoints + inline HTML/CSS/JS panel. 8 tabs: Status, Agents, Models, Config, Skills, Events, Act, Inference. Mountable on any scene via `mount_overlay(app, socketio)` |

### 9.2 Key Concepts

**InferenceConfig Flow:**
```
config/default.yaml → InferenceConfig.from_yaml()
AgentProfile → InferenceConfig.from_agent_profile()
Per-request overrides → InferenceConfig(temperature=0.3)
Merge chain → InferenceConfig.merge(base, override)
Serialise → .to_native_v1()
```

**LMSClient Routing (v2 framework):**
- **All requests** → native `/api/v1/chat` (OpenAI compat removed)
- Tools → ephemeral MCP via `integrations` field (not `tools` param)
- No fallback — if native v1 unavailable, raises error

**Stateful Chats:** Server-managed context via `previous_response_id`. Send only new messages instead of full history. Massive token savings for long conversations.

**Resource Strategies:**

| Strategy | VRAM | Use Case |
|----------|------|----------|
| SINGLE_BIG | ~8 GB | One large model, deep conversation |
| CONCURRENT | ~5 GB | One model, multiple parallel agents |
| MULTI_SMALL | ~6 GB | 2-3 specialist models |
| JIT_SWAP | Variable | Load/unload per request |
| SPECULATIVE | ~5.5 GB | Main + draft for 2-3× speed |
| HYBRID | GPU ~5 + RAM ~8 | GPU interactive + CPU background |

### 9.3 Modified Files

| File | Changes |
|------|---------|
| `engine/lmstudio/__init__.py` | Complete rewrite — exports all new modules |
| `engine/agents/character_agent.py` | Uses `LMSClient` + `InferenceConfig` for all LLM calls |
| `engine/lmstudio/tool_factory.py` | `run_with_tools()` uses `LMSClient`, handles `LMSResponse.tool_calls` |
| `engine/agents/agent_loop.py` | `_decide()` fallback uses `LMSClient` + `InferenceConfig` |
| `content/scenes/phone/phone_scene_v2.py` | Overlay mount + 3 admin routes (resources, config, inference-defaults) |
| `content/scenes/bedroom/bedroom_scene.py` | Overlay mount + 3 admin routes |
| `content/scenes/casino/casino_scene.py` | Overlay mount |
| `content/scenes/lounge/lounge_scene.py` | Overlay mount |
| `config/default.yaml` | Added ~35 lines: resource_manager, inference_defaults, load_defaults, speculative sections |

### 9.4 Config Additions (default.yaml)

```yaml
lmstudio:
  resource_manager:
    strategy: "concurrent"
    default_ttl: 300
    bg_workers: 2
  inference_defaults:
    temperature: 0.7
    top_p: 0.9
    top_k: 40
    min_p: 0.05
    repeat_penalty: 1.1
    max_output_tokens: 2000
    reasoning: false
  load_defaults:
    context_length: 4096
    gpu_offload: 0.9
    flash_attention: true
    eval_batch_size: 512
    keep_kv_cache_on_gpu: true
    ttl: 3600
  speculative:
    enabled: false
    draft_model: ""
```

### 9.5 Updated Singletons

| Singleton | Module | Accessor |
|-----------|--------|----------|
| LMSClient | engine.lmstudio.lms_client | `get_lms_client()` |
| LMSSDKWrapper | engine.lmstudio.lms_sdk | `get_lms_sdk()` |
| ResourceManager | engine.lmstudio.resource_manager | `get_resource_manager()` |

### 9.6 Documentation

| Document | Purpose |
|----------|---------|
| `LMStudio_v1.md` | API reference: endpoints, config, examples, feature matrix |
| `LMStudio_Agent_framework.md` | Agent/developer guide: architecture, scenes, skills, patterns |

### 9.7 Control Overlay Access

All scenes at `/overlay/`. API under `/overlay/api/`. Key endpoints:
- `GET /overlay/api/status` — System overview
- `GET /overlay/api/agents` — Agent states
- `POST /overlay/api/agents/<id>/message` — Act as agent
- `GET/POST /overlay/api/config` — View/edit config
- `GET /overlay/api/events/stream` — SSE live stream

---

## 10. Phase 4 — v2 Framework (v1-Only Migration)

### 10.1 Overview

Phase 4 removed all OpenAI-compatible API usage from the inference pipeline and
migrated exclusively to LMStudio's **native v1 REST API** (`/api/v1/chat`).
A new **ConversationManager** provides client-side state mirroring to solve
the three limitations of stateful chats: state loss on model unload, no
server-side edit/fork, and v1-only availability.

### 10.2 Key Changes

| Change | Detail |
|--------|--------|
| **OpenAI compat removed** | `_chat_openai_compat()` and `_stream_openai_compat()` deleted from `LMSClient`. No fallback to `/v1/chat/completions`. |
| **v1-only API** | `is_available()` and `get_models()` now use `/api/v1/models`. `_native_available` tracking removed. |
| **Tools via MCP only** | `tools` parameter removed from `chat()`. All tool access via ephemeral MCP `integrations` field. |
| **ConversationManager** | New `engine/lmstudio/conversation.py` — client-side conversation state mirror with send/edit/fork/truncate/invalidate. |
| **Auto-invalidation** | `unload_model()` calls `_on_model_unloaded()` → `ConversationManager.invalidate_model()` to flag all affected conversations for history replay. |
| **client_v2 deprecated** | `LMStudioClientV2` still works but emits `DeprecationWarning`. All production code uses `get_lms_client()`. |
| **Method rename** | `_parse_openai_response()` → `_parse_choices_response()` (parses choices-shaped JSON, not an endpoint change). |

### 10.3 ConversationManager

**File:** `engine/lmstudio/conversation.py` (~340 lines)

```python
from engine.lmstudio import get_conversation_manager

mgr = get_conversation_manager()

# Create a conversation for a phone thread
conv = mgr.create("phone-luna-thread-1", model="gemma-3-4b")

# Send messages — uses stateful fast-path (previous_response_id)
resp = conv.send(client, [{"role": "user", "content": "Hey Luna"}])

# Edit a message and replay from that point
conv.edit_message(2, {"role": "user", "content": "Actually, hello!"})

# Fork a conversation for branching dialog
fork = conv.fork("phone-luna-thread-1-alt")

# Model unloaded → all conversations auto-invalidated
# Next send() transparently replays full history
```

**Two-path strategy:**
1. **Fast path** — server has state → send only new message + `previous_response_id`
2. **Replay path** — server lost state → send full message history

### 10.4 Migrated Consumers

| File | Change |
|------|--------|
| `engine/agents/scene_agent.py` | `get_lmstudio_client` → `get_lms_client` |
| `engine/lmstudio/concurrency.py` | `get_lmstudio_client` → `get_lms_client` |
| `engine/lmstudio/tool_factory.py` | Removed client_v2 fallback, MCP-only tools |
| `engine/mcp/cosysim_server.py` | `get_lmstudio_client` → `get_lms_client` |
| `content/scenes/phone/phone_scene_v2.py` | 2 references migrated |
| `content/scenes/bedroom/bedroom_scene.py` | `LMStudioClientV2` → `get_lms_client` |
| `content/scenes/casino/casino_scene.py` | `_get_agent_reply()` migrated |
| `content/scenes/admin/pages/lmstudio.py` | `_client()` helper migrated |

### 10.5 Exports

```python
from engine.lmstudio import (
    LMSClient, get_lms_client,           # Primary v1 client
    ConversationManager,                   # State manager
    get_conversation_manager,              # Singleton accessor
    Conversation,                          # Individual conversation
    LMSSDKWrapper, get_lms_sdk,           # SDK wrapper
    ResourceManager, get_resource_manager, # Resource lifecycle
    InferenceConfig, LoadConfig,          # Config dataclasses
)
```

### 10.6 Test Results

- **49 tests pass** (23 core + 26 client_v2 backward compat)
- **12,568 Python files compile** with 0 failures
- All scenes compile and import correctly

---

## 11. Phase 5 — VirtualAgent Framework

### 11.1 Overview

Phase 5 introduces a decoupled agent architecture that separates **agent
identity/state** from **LLM inference execution**.  All LLM calls are now
routed through a centralised ``VirtualAgentManager`` which controls model
routing, concurrency, JIT loading, and lifecycle.

**Key insight:** Our agents *act like* LLM agents, but we control every call
to LMStudio.  The VirtualAgent produces ``InferenceRequest`` objects; the
manager decides how/when to execute them against the LLM backend.

### 11.2 Architecture

```
Scene / AgentLoop / Governor
       │
       ▼
  VirtualAgent           ─── Identity, State, Prompt, RAG, Conversation
       │
       │  InferenceRequest
       ▼
  VirtualAgentManager    ─── Routing, Concurrency, Model Control, Hooks
       │
       ├── ConversationManager  (stateful fast-path / history replay)
       ├── LMSClient            (/api/v1/chat — v1 native only)
       └── ConcurrentExecutor   (parallel batch inference)
       │
       │  InferenceResponse
       ▼
  VirtualAgent.process_response()  ─── State update, EventChain, ActivityBus
```

### 11.3 New Modules

| Module | File | Purpose |
|--------|------|---------|
| **VirtualAgent** | `engine/agents/virtual_agent.py` | Decoupled agent: identity, state, prompt building, RAG, conversation. Implements `IAgent`. |
| **VirtualAgentManager** | `engine/agents/virtual_agent_manager.py` | Centralised inference router. Creates agents, routes requests, batch inference, model control, hooks. Singleton via `get_virtual_agent_manager()`. |
| **InferenceRequest** | `engine/agents/virtual_agent.py` | Typed request dataclass: messages, model, config, conversation_id, structured_schema, priority. |
| **InferenceResponse** | `engine/agents/virtual_agent.py` | Typed response dataclass: content, tokens, latency, tool_calls, error. Converts from LMSResponse. |

### 11.4 VirtualAgent

```python
from engine.agents.virtual_agent import VirtualAgent
from engine.agents.virtual_agent_manager import get_virtual_agent_manager

mgr = get_virtual_agent_manager()

# Create an agent (auto-registers with manager + ConversationManager)
agent = mgr.create_agent(character, scene="bedroom", model="gemma-3-4b")

# Use like any IAgent — but all calls go through the manager
reply = agent.reply("Hey, what are you up to?")
decision = agent.quick_query("Choose an action: speak, move, idle")

# State management
agent.update_state(mood="excited", energy=0.8)
state = agent.get_state()  # {agent_id, name, scene, mood, energy, ...}

# Change model at runtime
agent.set_model("qwen3-8b")

# Build request without sending (useful for batch)
request = agent.build_request("Hello!", use_tools=True)
```

### 11.5 VirtualAgentManager

```python
from engine.agents.virtual_agent_manager import get_virtual_agent_manager

mgr = get_virtual_agent_manager()

# Create and register agents
agent_a = mgr.create_agent(char_a, scene="bedroom")
agent_b = mgr.create_agent(char_b, scene="bedroom")

# Single inference (routed through ConversationManager → LMSClient)
response = mgr.infer(request)

# Batch inference (parallel via ConcurrentExecutor)
responses = mgr.infer_batch([req_a, req_b, req_c])

# High-level convenience
reply = mgr.reply("char-uuid", "Hello!")
answer = mgr.quick_query("char-uuid", "What should I do?")

# Model control
mgr.set_all_models("gemma-3-4b")
mgr.load_model("qwen3-8b", context_length=8192)
mgr.unload_model("gemma-3-4b")

# Stats for overlay
stats = mgr.get_stats()  # {agents, total_requests, tokens_in/out, errors, avg_latency}

# Hooks (called before/after every inference)
mgr.add_pre_hook(lambda req: print(f"Inferring for {req.agent_id}"))
mgr.add_post_hook(lambda req, resp: log_to_db(req, resp))
```

### 11.6 CharacterAgent Integration

``CharacterAgent`` supports a ``use_virtual=True`` flag:

```python
agent = CharacterAgent(
    character, db=db, scene="bedroom",
    use_virtual=True,  # ← routes through VirtualAgentManager
)
reply = agent.reply("Hello!")  # transparently delegates to VirtualAgent
```

When ``use_virtual=True``:
- A ``VirtualAgent`` is created and registered with the global manager
- ``reply()``, ``quick_query()``, ``cancel()`` all delegate to the VirtualAgent
- The governance pipeline (AgentGovernor) wraps as normal — it doesn't know
  the underlying agent changed

---

## Phase 8: v2.7.1 Streaming Framework Rework

### 12.1 StreamProcessor

**File:** `engine/agents/stream_processor.py`

The StreamProcessor is the core v2.7.1 addition — it sits between the SSE stream and the
application, extracting structured data from the raw token flow in real-time.

**Architecture:**
```
LMSClient.chat_stream_stateful()
  → SSE events (message.delta, reasoning.delta, tool_call.*, chat.end)
    → StreamProcessor.on_event(LMSStreamEvent)
      → accumulates content/reasoning text
      → extracts inline tags via regex: [MOOD:x], [IMAGE:prompt], [ACTION:x], [STAT:name±val], [VOICE:style]
      → tracks tool call lifecycle (start → arguments → success/failure)
      → fires real-time callbacks (on_delta, on_mood, on_tool_call, etc.)
    → StreamProcessor.result() → ProcessedResponse
```

**Key Classes:**
- `ProcessedResponse` — dataclass with: clean_text, raw_text, reasoning_text, mood_tags,
  image_requests, action_tags, voice_style, tool_calls, stat_deltas, stats (tokens, tps, response_id)
- `ToolCallRecord` — name, arguments (dict), result (str), success (bool)
- `StatDelta` — stat_name, delta (float), parsed from `[STAT:trust+5]`

**Inline Tags:**
Characters (LLMs) can embed structured data in their text responses:
```
[MOOD:playful] Hey! Check this out [IMAGE:a cute selfie with peace sign]
I'm feeling generous today [STAT:trust+10] [ACTION:sends_gift]
```
The StreamProcessor strips these from `clean_text` but preserves them in `raw_text`.

### 12.2 VirtualAgentManager.infer_processed()

```python
response = await manager.infer_processed(
    agent_id="bedroom_luna",
    prompt="Take a selfie for me",
    callbacks={
        "on_mood": lambda mood: update_ui_mood(mood),
        "on_image_request": lambda prompt: queue_comfyui(prompt),
        "on_delta": lambda text: stream_to_websocket(text),
    }
)
# response.processed.mood_tags → ["playful"]
# response.processed.image_requests → ["cute selfie with peace sign"]
# response.processed.clean_text → "Hey! Check this out\nI'm feeling generous today"
```

### 12.3 Governor Context Bridge (v2.7.1 Enhancement)

After `agent.reply()`, the AgentGovernor reads `_last_response` from the VirtualAgent
and populates the ResponseContext with rich metadata:

```python
# Available in post-call interceptors:
ctx["mood_tags"]       # ["playful", "happy"]
ctx["image_requests"]  # ["cute selfie with peace sign"]
ctx["action_tags"]     # ["sends_gift"]
ctx["processed"]       # Full ProcessedResponse object
ctx["reasoning"]       # LLM reasoning text (if reasoning enabled)
ctx["tool_calls"]      # [ToolCallRecord(...), ...]
```

This means interceptors can react to mood changes, trigger image generation,
log actions, or modify responses based on the full stream context.

### 12.4 SceneAgent v2.7.1

SceneAgent now has three modes:
```python
# 1. Standard (unchanged) — fire-and-forget text response
text = scene_agent.run("What do you see?")

# 2. Structured — JSON schema output
result = scene_agent.run_structured(
    "Describe the room",
    schema={"type": "object", "properties": {"mood": {"type": "string"}, "items": {"type": "array"}}}
)

# 3. Streaming — real-time with ProcessedResponse
processed = scene_agent.run_stream(
    "Tell me a story",
    callbacks={"on_delta": lambda t: print(t, end="")}
)

# 4. Decision — structured choice (returns dict)
choice = scene_agent.decide(
    "Should Luna send a selfie or a text?",
    options=["selfie", "text", "voice_message"],
    context="Player asked for a picture"
)
```

All SceneAgent calls use `store=False` by default — they don't pollute the
main conversation history.

### 12.5 MessagesApp Rewrite

The MessagesApp is now a full agent-integrated messaging system:

```python
# Thread management
messages = MessagesApp(char_id="luna", db=db, scene_name="phone")
messages.switch_thread("alex")  # activates phone_luna_alex conversation

# Send with agent integration
result = messages.send("Hey, how are you?")
# result.reply_text = "I'm great! [MOOD:happy]"
# result.image_url = None | "path/to/selfie.png"
# result.mood = "happy"

# Character-initiated message
messages.receive_unsolicited(
    contact_id="alex",
    system_context="Alex is bored and wants attention"
)
```

### 12.6 New MCP Tools

Five new tools available to the LLM via the CosySim MCP server:

| Tool | Purpose | store |
|------|---------|-------|
| `send_selfie(prompt, char_id)` | ComfyUI image gen → structured response | False |
| `send_voice_message(text, char_id)` | TTS gen → audio path | False |
| `query_stateless(prompt)` | Disposable utility query | False |
| `get_conversation_info(conv_id)` | State + forkable response_ids | — |
| `fork_conversation(conv_id, turn)` | Branch at specific turn | — |

### 12.7 Dialog System Branching

```python
# Try multiple response approaches, pick best
alternatives = dialog.try_alternatives(
    agent_id="bedroom_luna",
    prompt="Player confessed feelings",
    num_alternatives=3,
    scoring_fn=lambda text: score_emotional_depth(text)
)
best = alternatives[0]  # sorted by score

# Fork conversation at a decision point
branch_id = dialog.get_branch_point("bedroom_luna")
# Returns response_id that can be used with fork_conversation()
```

### 12.8 Rules Engine Streaming Integration

```python
# Mid-stream stat updates
engine.apply_stream_deltas(
    char_id="luna",
    deltas=[StatDelta("trust", 5.0), StatDelta("arousal", -3.0)]
)

# Check threshold rules after stat changes
triggered = engine.evaluate_threshold_rules("luna")
# Returns list of rules whose conditions are now met
```

### 12.9 Framework Events

```python
# MCPCharacterNode streaming lifecycle
node.start_stream()   # marks node as streaming
node.end_stream(token_count=150, mood="playful")
info = node.stream_info()  # {"is_streaming": False, "stream_tokens": 150, ...}

# MCPFramework emits real-time events
framework.emit_stream_event(
    char_id="luna",
    event_type="mood_change",
    data={"mood": "playful", "previous": "neutral"}
)
```

---

## Phase 9: Scene Upgrades & Gallery Showcase

### 13.1 Phone Scene v2.7.1 Upgrades

- `_PhoneCharacterAgent.reply()` now uses `infer_processed()` with streaming
- System prompt teaches agents `[MOOD:]`, `[IMAGE:]`, `[VOICE:]` inline tags
- `_generate_reply()` returns rich dict: `{text, mood, image_requests, action_tags, voice_style}`
- Reply worker processes `image_requests` → ComfyUI image generation as separate photo messages
- Mood tags update character state in MCP framework
- Autonomous text messages include rich metadata (mood, image_requests)

### 13.2 Agent Loop v2.7.1 Upgrades

- `_decide()` uses `infer_processed()` for mood/stat extraction
- Mood tags from stream update character state via `_update_character_mood()`
- Decision queries use `store=False` (stateless — no conversation pollution)

---

## Phase 8: Bug Fixes & Media Infrastructure (v2.7.2)

### 14.1 Critical: LMStudio v1 API Input Format

The v1 `/api/v1/chat` `input` field was fixed **twice**:

1. **Type fix**: `"type": "message"` → `"type": "text"` (discriminator error)
2. **Field fix**: `"text": "..."` → `"content": "..."` (unrecognized key error)

**Correct v1 input format:**
```json
{"type": "text", "content": "Hello world"}
```
**v1 output format is different (asymmetric):**
```json
{"type": "message", "content": "Response text"}
```

Fixed in `engine/lmstudio/lms_client.py` `_messages_to_v1_input()`.

### 14.2 Overlay Fixes

- `CharacterRegistry` uses `_chars` internally, not `_characters`
- Rewrote `overlay_bp.py` to use public APIs: `list_characters()`, `get_profile()`, `get_state()`
- `set_state()` takes `**kwargs` not a positional dict
- Added `is_native_available()` method fallback
- Overlay opens as iframe panel within scene, not a new page

### 14.3 Phone Message History

- `_generate_reply()` now fetches last 20 messages from `phone_db` via `thread_id`
- Conversation history passed to both governor and VirtualAgentManager paths
- Contacts reload on compose if list is empty (race condition fix)
- Thread list scrolling: `overflow-y: auto` on `.thread-list`

### 14.4 Media Infrastructure

**ComfyUI Monitor** (`engine/services/comfyui_monitor.py`):
- Background thread polls ComfyUI output dir every 2 seconds
- File naming convention: `TAG_detail_timestamp.ext` (PHOTO/SELFIE/VIDEO/VOICE/AVATAR)
- Moves files to `content/simulation/media/{photo,video,voice}/`
- Registers assets in `asset_registry.db`

**Housekeeping** (`engine/services/housekeeping.py`):
- Scans both `content/simulation/media/` and `content/media/` directories
- Resolves character FK by querying first valid character from DB
- Runs via `python launcher.py --housekeep` or `--housekeep --watch`

**AssetManager** (`engine/assets/manager.py`):
- Added `import_media_folder()` method for bulk file import
- Deterministic IDs via path hash (idempotent reimport)
- Auto-detects type from extension: image/video/audio

---

## 14. Phase 8 — v2.8 Stateful-First Conversations & Framework Upgrade

### Overview

v2.8 rewires CosySim so that **stateful conversations are the default**.  Prior
versions built the infrastructure (ConversationManager, StreamProcessor, SSE parsing,
response_id tracking) but no scene actually used it — every call rebuilt full
message history.  v2.8 activates all of it.

### Key Changes

#### Token Artifact Stripping
- `strip_token_artifacts()` in `engine/agents/stream_processor.py`
- Regex removes `<|begin_of_text|>`, `<|end_of_text|>`, `<|eot_id|>`, etc.
- Applied in: StreamProcessor.result(), ResponseShaperInterceptor.post_call(),
  PhoneCharacterAgent.reply(), _generate_reply()

#### Personality Loading (CharacterRegistryInterceptor)
- `_load_personality_profile()` loads full personality from simulation DB
- Injects backstory, speech patterns, traits, quirks, interests
- Combined with CharacterRegistry mood/identity info at priority 8

#### ConversationVarietyInterceptor (priority 55)
- Tracks last 5 response summaries per character
- Injects anti-repetition guidance when similarity detected
- Adds emoji, expressiveness, adult content instructions
- Integrates **ConversationHeat** directives

#### Conversation Repair
- `VirtualAgentManager._is_garbage_response()` — detects empty, too-short,
  or artifact-only responses
- `_retry_with_repair()` — retries with lower temperature (max 2 attempts)
- Works on both stateful and direct paths

#### ConversationManager Smart Updates
- `Conversation.update_system_if_changed()` — MD5 hash diff
- Only invalidates when system prompt actually changes
- Prevents unnecessary server replays from interceptor rebuilds

#### Conversation Heat System
- `ConversationHeat` class in `engine/mcp/scene_rules_engine.py`
- 0–100 scale with keyword detection and time-based decay
- Thresholds: <30 normal, 30-60 warm/flirty, 60-80 hot/explicit, 80+ intense
- Auto-analyzed on every response via ConversationVarietyInterceptor
- Directives injected into system prompts based on heat level
- MCP tools: `get_conversation_heat_level`, `bump_conversation_heat`

#### Response_ID Persistence
- Phone DB messages table now has `response_id` and `conversation_id` columns
- `get_last_response_id(thread_id)` for stateful conversation resumption
- Migration: ALTER TABLE for existing databases

### Five Creative Uses of Conversation Branching

1. **Personality Exploration** — Fork at last good turn, try different personality
   injection, pick the more engaging branch
2. **Response Quality Gate** — Fork before reply, generate 2 variants at
   different temperatures, return the better one
3. **Mood Pivot Recovery** — Branch back before an offense, inject different
   emotional directive, character "takes a different stance"
4. **Conversation Repair** — Branch to last valid response_id on garbage output,
   retry with adjusted parameters
5. **Game Decision Trees** — Fork at choice points, enable undo/what-if exploration

### New MCP Tools (v2.8)

| Tool | Purpose |
|------|---------|
| `get_conversation_heat_level` | Query heat level + directive for a conversation |
| `bump_conversation_heat` | Manually increase heat during intimate exchanges |
| `check_conversation_history` | Let agent review recent messages before responding |
| `suggest_activity` | Scene-appropriate activity suggestions based on context |

### Interceptor Pipeline (Updated)

```
 8  CharacterRegistryInterceptor  ← loads full personality from DB
10  RouterMessageInjector
12  DialogDirectiveInterceptor
15  BedroomSceneInterceptor / PhoneSceneInterceptor / LoungeSceneInterceptor
20  AutoResultInjector
30  SkillAwarenessInterceptor
35  GameSessionInterceptor
40  GameRulesInterceptor
50  PersonalityGuardInterceptor
55  ConversationVarietyInterceptor  ← anti-repetition + heat directives
60  PolicyEnforcerInterceptor
70  MemoryEnhancerInterceptor
80  ResponseShaperInterceptor  ← strips token artifacts
85  TTSStyleInterceptor
90  ActivityLoggerInterceptor
92  MoodSyncInterceptor
```

### Architecture: Stateful Conversation Flow (v2.8)

```
User message → AgentGovernor (interceptors inject context)
  → VirtualAgent.reply(governance_context=...)
    → VirtualAgentManager._execute_request()
      → ConversationManager.send() [stateful-first]
        → LMSClient.chat_stream_stateful() [SSE stream]
          ← event: message.delta → accumulate content
          ← event: tool_call.start → MCP tool executing
          ← event: reasoning.delta → thinking visible
          ← event: chat.end → stats, response_id
        → StreamProcessor.process(events)
          → extract structured response (text + images + json)
          → extract mood/stat tags in real-time
          → strip token artifacts
        → ProcessedResponse (content, mood_tags, image_requests, stats)
      → InferenceResponse with response_id for chain tracking
    → post-call interceptors (heat update, mood sync, logging)
  → return to scene (text + optional media attachments)
```

### Token Savings

Stateful conversations save ~80% tokens on subsequent messages.
A 20-message history that sends 4000 tokens per call becomes ~200 tokens
(just the new message + previous_response_id).

### Configuration

```yaml
# config/default.yaml
lmstudio:
  inference_defaults:
    store: true              # default to stateful
    reasoning: "off"
    max_output_tokens: 4000
    temperature: 0.85
```

### Test Coverage

491 tests passing. Key test files:
- `tests/test_lms_client_v27.py` — 45 tests for SSE, branching, stateful
- `tests/test_stream_processor.py` — StreamProcessor tag extraction
- `tests/test_virtual_agent_v27.py` — VirtualAgent + interceptor pipeline
- `tests/test_skills.py` — MCP skill registration and execution
- `tests/test_config.py` — Config loading and override
- `tests/test_event_chain.py` — EventChain propagation
- 975 assets registered (784 audio, 145 image, 42 video, 4 other)

### 14.5 Database Seeding

- 5 default characters auto-inserted on DB init (lola, viktor, aria, frankie, mira)
- 6 default personalities auto-inserted (Bold Dominant, Shy Submissive, Playful Tease, etc.)
- Scene auto-registration via `seed_default_scenes()` in SceneManager
- All idempotent — safe to run multiple times

### 14.6 Admin Panel Robustness

- All 17 page handlers wrapped in try/except with full traceback display
- Create character shows feedback and prevents duplicate creation
- Edit character fields aligned with create fields

### 14.7 Test Suite

- **491 tests, 0 failures** (up from 404)
- Tests updated for seeded baseline data (characters, personalities)
- v1 API format assertions corrected to `{"type": "text", "content": "..."}`
- Run: `python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py`
- Extra action tags captured in decision dict for scene processing

### 13.3 Gallery Scene (NEW — v2.7 Framework Showcase)

**Port:** 5560 | **File:** `content/scenes/gallery/gallery_scene.py`

An interactive art gallery demonstrating every v2.7 streaming framework feature:

| Feature | API Endpoint | Framework Feature Showcased |
|---------|-------------|---------------------------|
| Art Evaluation | `POST /api/evaluate` | `infer_processed()` streaming with SocketIO deltas |
| Structured Critique | `POST /api/critique` | `SceneAgent.run_structured()` JSON schema output |
| Art Debate | `POST /api/debate` | Multiple alternatives / branching interpretations |
| Art Creation | `POST /api/artwork/create` | `[IMAGE:]` tag extraction + ComfyUI generation |
| Exhibition Setup | `POST /api/exhibition/set` | Scene state management + MCP framework events |

**Characters:** curator, critic, artist, visitor — each with distinct evaluation perspectives.

**Rooms:** main_hall, modern_wing, sculpture_garden, dark_room, private_collection.

**Exhibitions:** dreams_unveiled (surrealist), neon_futures (cyberpunk), raw_emotions (abstract).

```python
# Launch gallery
python launcher.py --mode gallery  # http://localhost:5560
```

### 12.8 Rules Engine Streaming Integration

```python
# Mid-stream stat updates
engine.apply_stream_deltas(
    char_id="luna",
    deltas=[StatDelta("trust", 5.0), StatDelta("arousal", -3.0)]
)

# Check threshold rules after stat changes
triggered = engine.evaluate_threshold_rules("luna")
# Returns list of rules whose conditions are now met
```

### 12.9 Framework Events

```python
# MCPCharacterNode streaming lifecycle
node.start_stream()   # marks node as streaming
node.end_stream(token_count=150, mood="playful")
info = node.stream_info()  # {"is_streaming": False, "stream_tokens": 150, ...}

# MCPFramework emits real-time events
framework.emit_stream_event(
    char_id="luna",
    event_type="mood_change",
    data={"mood": "playful", "previous": "neutral"}
)
```

### 11.7 Migrated Scenes

| Scene | Change |
|-------|--------|
| **Bedroom** | `CharacterAgent(use_virtual=True, scene="bedroom")` — all agents route through manager |
| **Phone** | `_PhoneCharacterAgent.reply()` → `VirtualAgentManager.infer()` (was direct LMSClient) |
| **Casino** | `_get_agent_reply()` → `VirtualAgentManager.infer()` (was direct LMSClient) |
| **Lounge** | `CharacterAgent(use_virtual=True, scene="lounge")` |
| **AgentLoop** | Fallback `_decide()` → `VirtualAgentManager.infer()` (was direct LMSClient) |

### 11.8 Inference Request Flow

```
1. VirtualAgent.reply("Hello!")
2.   → build_request()
3.     → _search_memories() (RAG)
4.     → _build_system_prompt() (persona + memories + MCP brief)
5.     → InferenceRequest(messages, model, conversation_id, ...)
6.   → manager.infer(request)
7.     → _execute_request()
8.       → ConversationManager stateful path (previous_response_id)
9.       → or direct LMSClient.chat() (full history)
10.    → InferenceResponse
11.  → process_response()
12.    → EventChain logging
13.    → MCP state update
14.    → ActivityBus publish
15.  → return reply text
```

### 11.9 Test Results

- **49 tests pass** (all existing tests unchanged)
- All modified scenes compile and import correctly
- VirtualAgent satisfies IAgent protocol (drop-in compatible)

---

## 12. Phase 6 — v2.5 Framework Push

**Commit scope:** v2.5 — VirtualAgent as primary, legacy removal, batch inference, state persistence.

### 12.1 CharacterAgent → Thin Adapter

CharacterAgent is now a **thin wrapper** (~130 lines) that always creates a
VirtualAgent internally via `get_virtual_agent_manager().create_agent(...)`.

**Removed:**
- All legacy LLM call paths: `_reply_via_rest()`, `_act()`, `_complete()`, `_get_llm()`
- Direct `get_lms_client()` calls in CharacterAgent
- `_cancel_event`, `_stream`, `_lock` (owned by VirtualAgent now)
- `_build_system_prompt()`, `_search_memories()`, `_get_tools()`, `_get_event_chain()`
  (all moved to VirtualAgent)
- `use_virtual` parameter — always True; accepted for backward compat but ignored

**New methods:** `get_state()`, `update_state()`, `set_model()`, `virtual` property.

### 12.2 AgentLoop — Batch Inference & Structured Output

**`_decide()`** now routes through `agent.quick_query()` (→ VirtualAgentManager) first,
then falls back to `VirtualAgentManager.infer()` with `DECISION_SCHEMA` structured output.

**`_decide_batch()`** — new method that fans out multiple agent decisions in parallel
via `VirtualAgentManager.infer_batch()`. Used when ≥2 characters need decisions.

**`tick()`** rewritten with 3-phase architecture:
1. **Perceive** — build context for all characters (no LLM)
2. **Decide** — batch inference via manager (parallel when >1 agent)
3. **Execute** — apply decisions to scene

### 12.3 SceneAgent → VirtualAgentManager

`SceneAgent.run()` now routes through `VirtualAgentManager.infer()` with an
`InferenceRequest` instead of calling `get_lms_client().chat()` directly.

### 12.4 Agent State Persistence

VirtualAgent now has `save_state()`, `load_state()`, `_persist_state()`:
- SQLite database at `data/agent_state.db`
- Auto-loads persisted state on `__init__`
- Auto-persists after `update_state()` and after each successful inference
  (via VirtualAgentManager's post-inference hook)
- Survives process restarts

### 12.5 Scene Updates

| Scene | Change |
|-------|--------|
| **Bedroom** | Removed `use_virtual=True` (always True). Replaced `get_lmstudio_manager` model listing with manager stats. |
| **Phone** | Already used VirtualAgentManager — no changes needed. |
| **Casino** | Already used VirtualAgentManager — no changes needed. |
| **Lounge** | Removed `use_virtual=True` (always True). |

### 12.6 MCP Server

`enhance_message()` tool now routes through VirtualAgentManager instead of
direct `get_lms_client().chat()`.

### 12.7 Call Flow (v2.5)

```
Scene / AgentLoop / User
       │
       ▼
  CharacterAgent.reply()  ──(delegates)──▶  VirtualAgent.reply()
                                                  │
                                             build_request()
                                                  │ InferenceRequest
                                                  ▼
                                        VirtualAgentManager.infer()
                                                  │
                                         ┌────────┴────────┐
                                         │ _execute_request │
                                         │   stateful path  │
                                         │   or direct call │
                                         └────────┬────────┘
                                                  │
                                       ConversationManager ──▶ LMSClient
                                                  │               │
                                                  │         /api/v1/chat
                                                  │               │
                                                  ◀───────────────┘
                                                  │ InferenceResponse
                                                  ▼
                                        VirtualAgent.process_response()
                                           │ EventChain logging
                                           │ MCP state sync
                                           │ ActivityBus publish
                                           │ _persist_state()
                                           ▼
                                        return reply text
```

### 12.8 Test Results

- **136 tests pass** (87 governance + 49 core/client)
- Tests updated: `test_cancel_sets_cancel_event`, `test_reply_accepts_extra_kwargs`,
  `test_reply_calls_llm`, `test_reply_uses_event_chain`
- All tests now mock VirtualAgent internals instead of removed CharacterAgent methods

---

## 13. Phase 7 — v2.7 LMStudio Native Upgrade

**Version:** 2.7.0  
**Commits:** `d3cbb81`, `482a12b`, `a3873d5`, `76166c3`, `6f2cbba`, `ffdaca3`, `18d3d5a`

### 13.1 LMStudio v1 Native API — Full Support

The LMStudio native REST API (`/api/v1/chat`) replaces all OpenAI-compatible
fallbacks as the **only** inference path. Key differences from the OpenAI format:

| Feature | OpenAI compat (`/v1/chat/completions`) | Native v1 (`/api/v1/chat`) |
|---------|---------------------------------------|----------------------------|
| Request body | `messages[]` array | `input` (string\|array) + `system_prompt` |
| Streaming | `data: {...}` lines | `event: <type>\ndata: <json>` pairs |
| State tracking | None | `response_id` + `previous_response_id` |
| Store control | None | `store: true/false` |
| Context replay | Must resend all history | Server KV cache (fast path) |

**Payload conversion:** `LMSClient._messages_to_v1_input()` converts OpenAI
`messages[]` → v1 `input` + `system_prompt`. Assistant messages become
`[assistant]: content` prefixed user items (v1 does not support assistant role
in `input`).

### 13.2 Typed SSE Streaming

`_stream_v1_raw()` is a shared generator that parses v1 SSE events:
```
event: chat.start
data: {"model": "qwen-3-4b"}

event: message.delta
data: {"contentDelta": "Hello"}

event: chat.end
data: {"stats": {...}}
```

Each event becomes a typed `LMSStreamEvent(event_type, data, content_delta,
reasoning_delta)`. All 18 v1 event types are handled:
- `chat.start/end`, `model_load.start/end`
- `prompt_processing.progress`, `reasoning.delta`
- `message.delta/start/end`, `tool_call.*`

### 13.3 Stateful Conversations

**ConversationManager** tracks server-side state:
- Each `Conversation` stores `_response_id_history` (all response_ids)
- `send()` uses fast path: only the new user message + `previous_response_id`
- Model unload → `invalidate()` → next `send()` replays full history

**Conversation branching:**
- `branch_at(turn_index)` — fork from any historical turn
- `fork(branch_response_id=)` — fork using a specific response_id
- `send_stateless(message)` — one-off query with `store=False`

### 13.4 Stateful-First Routing

`VirtualAgentManager._execute_request()` routing strategy:

```
InferenceRequest
  │
  ├── store=False? ──► LMSClient.chat(store=False) [no state]
  │
  ├── has conversation_id? ──► _infer_stateful()
  │     │
  │     ├── Conversation exists + system_prompt unchanged ──► conv.send() [fast path]
  │     ├── System prompt changed ──► conv.invalidate() + conv.send() [replay]
  │     └── No conversation yet ──► conv_mgr.create() + conv.send()
  │
  └── fallback ──► LMSClient.chat() [direct, no state]
```

**System prompt evolution:** When interceptors change the system prompt
(via governance_context), `_infer_stateful()` compares `conv.system` with
the incoming prompt. On mismatch, it updates the conversation and calls
`conv.invalidate()` to force full replay, ensuring the server always has
the current system prompt.

### 13.5 Governance Context Bridge (Critical Fix)

**Problem:** The interceptor pipeline built `ctx["system_prompt"]` with scene
state, game rules, skills awareness, personality guards, etc. — but the
governor called `agent.reply(user_message)` without passing this context.
VirtualAgent.build_request() rebuilt its own system prompt from character data,
silently discarding all interceptor injections.

**Fix:** New `governance_context` parameter flows through the entire chain:

```
AgentGovernor.reply()
  │ ctx["system_prompt"] ← interceptor pipeline
  │
  ▼ agent.reply(msg, governance_context=ctx["system_prompt"])
  │
  ▼ CharacterAgent.reply(msg, governance_context=...)
  │
  ▼ VirtualAgent.reply(msg, governance_context=...)
  │
  ▼ VirtualAgent.build_request(msg, governance_context=...)
     │ system = _build_system_prompt(memories)   ← base prompt
     │ system += "\n\n" + governance_context      ← interceptor overlay
     ▼
     InferenceRequest(messages=[{role: system, content: merged}], ...)
```

This means the full "sandwich" control now works:
1. **Pre-call interceptors** inject scene/game/rules context
2. **Agent base prompt** provides character identity
3. **Combined prompt** goes to LMStudio
4. **Post-call interceptors** process/filter the reply

### 13.6 InferenceRequest / InferenceResponse v2.7

**New InferenceRequest fields:**
| Field | Type | Purpose |
|-------|------|---------|
| `store` | `Optional[bool]` | `None`=server default, `False`=stateless |
| `stream` | `bool` | Request streaming response |
| `on_event` | `Callable` | Callback for typed streaming events |

**New InferenceResponse fields:**
| Field | Type | Purpose |
|-------|------|---------|
| `reasoning_tokens` | `int` | Tokens used in reasoning (thinking models) |
| `server_tps` | `float` | Server-reported tokens/sec |
| `time_to_first_token_s` | `float` | Time to first token |
| `model_load_time_s` | `float` | Model load time (JIT) |
| `is_stateful` | property | Whether response_id starts with `resp_` |

### 13.7 ResponseContext v2.7 Keys

After the LLM call, the governor populates:
- `response_id` — server response_id (for branching)
- `is_stateful` — whether the response has a valid resp_ id
- `store` — whether the call was stored
- `reasoning` — reasoning content from thinking models
- `tool_calls` — list of tool calls

Post-call interceptors can use these for branching decisions.

### 13.8 Key Architecture Decisions

1. **ConversationManager is primary path** — direct LMSClient.chat() is
   fallback only for requests without a conversation_id
2. **store=False skips ConversationManager entirely** — no state tracking
   for one-off queries (quick_query, game decisions)
3. **Response_id tracked at two levels** — Conversation._response_id_history
   (for branching) and VirtualAgent._state["last_response_id"] (for agent logic)
4. **`_stream_v1_raw()` shared SSE consumer** — used by both `_stream_native()`
   and `chat_stream_stateful()`
5. **Thinking model workaround** — max_output_tokens=4000+, reasoning="off"
   unless explicitly wanted (Qwen3 consumes all tokens on reasoning otherwise)

### 13.9 Deleted / Deprecated

| File | Status |
|------|--------|
| `engine/lmstudio/lms_sdk.py` | **Deleted** — Python SDK wrapper, never imported by production code |
| `engine/lmstudio/client_v2.py` | **Deleted** v2.9 — MCP class moved to lms_client.py, LMStudioClient unused |
| `engine/lmstudio/__init__.py` | Removed lms_sdk exports, updated client_v2 → lms_client imports |

### 13.10 Test Results

- **514 tests pass** (up from 424 pre-v2.9)
- 45 LMSClient v2.7 tests: SSE parsing, stateful chats, branching, stats
- 20 VirtualAgent v2.7 tests: InferenceRequest/Response fields, governance_context
- 29 ContentRouter tests: JSON extraction, classification, decision parsing
- 20 Evaluator tests: scoring, problems, garbage detection
- Test command: `python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py`

---

## 15. Phase 9 — v2.9 Unified Pipeline & System Consolidation

Generated: 2026-02-23

### 15.1 Summary

v2.9 consolidates the framework: unified content pipeline, robust JSON parsing,
text/image evaluators, bedroom stateful dialog split, quality gate, mood pivot,
game session stateful turns, and dead code removal.

### 15.2 New Modules

| Module | Purpose |
|--------|---------|
| `engine/agents/content_router.py` | Robust JSON extraction (brace-counting parser), content classification, inline tag extraction |
| `engine/agents/evaluator.py` | `TextEvaluator` (heuristic scorer), `ImageEvaluator` (VLM-based), `ResponseScore` / `ImageScore` dataclasses |

### 15.3 ContentRouter — Robust JSON Parsing

Replaces the brittle `{`/`}` search in `agent_loop._parse_decision()`.

```python
from engine.agents.content_router import ContentRouter, extract_json

# Extract JSON from any LLM output format
obj = extract_json('Here is my answer: {"action": "speak"} done.')
# → {"action": "speak"}

# Also handles: markdown fences, nested objects, trailing commas, token artifacts

# Agent decision parsing (validates against VALID_ACTIONS)
decision = ContentRouter.parse_decision(text, valid_actions={"speak", "move", "idle"})
# → {"action": "speak", "target": "", "message": ""}

# Content classification
result = ContentRouter.classify("[MOOD:happy] Hello! [IMAGE:sunset]")
# result.content_type = "tagged_text"
# result.tags = {"MOOD": ["happy"], "IMAGE": ["sunset"]}
# result.clean_text = "Hello!"
```

### 15.4 TextEvaluator — Response Quality Scoring

Heuristic scorer that checks response quality without making LLM calls:

- **Length score** (0-1): penalizes too short (<3 words) or too long (>200 words)
- **Variety score** (0-1): Jaccard similarity vs last 5 messages, flags repetition
- **Engagement score** (0-1): questions, exclamations, action tags, conversation callbacks
- **Personality score** (0-1): keyword density from character profile
- **Expressiveness** (0-1): emoji, ellipsis, emphasis, action tags

```python
from engine.agents.evaluator import TextEvaluator

evaluator = TextEvaluator(personality_keywords={"bold", "rebel"})
score = evaluator.score_heuristic(text, recent_messages=recent)
print(score.total)          # 0.0 - 1.0
print(score.is_acceptable)  # True if total >= 0.35 and no critical problems
print(score.problems)       # ["repetitive", "too_short", "token_artifacts"]
```

### 15.5 ImageEvaluator — VLM Quality Gate

Uses `LMSClient.chat_with_images()` with `store=false` to evaluate generated images:

```python
from engine.agents.evaluator import ImageEvaluator

evaluator = ImageEvaluator()
score = evaluator.evaluate(image_data_url, prompt="cute selfie")
# score.quality = 0.8, score.relevance = 0.7, score.total = 0.74

description = evaluator.describe(image_data_url)
# → "A young woman taking a selfie in a bedroom"
```

### 15.6 Bedroom Stateful Dialog Split

Agent loop now splits decision and dialog into two separate LLM calls:

1. **Decision** (store=false, JSON schema): `{"action": "speak", "target": "user"}`
2. **Dialog** (store=true, stateful): Actual speech with conversation memory

```
AgentLoop.tick()
  → _decide(char_id, context)             ← store=false, structured JSON
  → _execute(char_id, decision)
    → _generate_dialog(char_id, decision)  ← store=true, stateful conv
    → result["message"] = dialog text
```

Each character gets a persistent conversation: `{scene_id}_dialog_{char_id}`.
The decision call determines WHAT to do; the dialog call determines WHAT TO SAY.

### 15.7 Quality Gate — Dual-Generate

`VirtualAgentManager.infer_quality_gate()` generates multiple response variants
and picks the best one:

- Generates 2-4 variants at different temperatures (0.7, 1.1, 0.9, 0.5)
- All variants use `store=false` (disposable)
- TextEvaluator scores each variant
- Returns highest-scoring response

### 15.8 Mood Pivot — Conversation Branching Recovery

`DialogSystem.mood_pivot()` recovers from mood drops by branching back:

- Branches 2 turns back via `Conversation.send(previous_response_id_override=...)`
- Injects new mood directive at the branch point
- Regenerates response with different emotional framing

### 15.9 Game Session Stateful Turns

`MCPGameSession` now supports stateful game dialog with undo via
`process_turn_stateful()` and `undo_last_turn()`.

### 15.10 Dead Code Removed

| File | Action |
|------|--------|
| `engine/lmstudio/client_v2.py` | **Deleted** — `MCP` class moved to `lms_client.py` |
| `tests/test_client_v2.py` | **Deleted** — tested deprecated client |
| `phone_ui_v2 - Copy.html` | **Deleted** — accidental backup |

### 15.11 Architecture: v2.9 Pipeline Flow

```
User message → AgentGovernor (interceptors inject personality + heat)
  → ContentRouter.classify(input)           ← detect JSON/tags/text
  → VirtualAgentManager._execute_request()
    → ConversationManager.send()            ← stateful-first
      → LMSClient.chat_stateful()           ← SSE stream
      → StreamProcessor → ProcessedResponse  ← mood/image/action tags
    → TextEvaluator.score_heuristic()        ← quality check
    → if garbage: _retry_with_repair()       ← conversation branching
  → Governor.post_call() → strip tokens, shape response
  → return to scene
```

---

## 14. Phase 8 — v3.1 Pipeline Consolidation & Tool-First Architecture

Generated: [2026-02-24] — v3.1

### 14.1 Overview

v3.1 consolidates the interceptor pipeline, introduces unified response parsing,
and establishes a tool-first architecture via an in-process MCP skills server.

**Key metrics:**
- Interceptors: 18 → functionally 12 active (scene-aware filtering skips irrelevant ones)
- Parsing paths: 3 → 1 (single-pass `ParsedResponse`)
- Stream scan: 2 passes → 1 pass (tag accumulation during SSE)
- Tests: 551 → 576

### 14.2 ParsedResponse — Unified Parsing

All response parsing now goes through `ContentRouter.parse_full(text)` returning a
`ParsedResponse` dataclass with: content, mood, mood_intensity, actions, image_requests,
voice_hints, game_events, stat_updates, json_data, tags, raw_text.

**Single parse point:** `ctx["parsed"]` is populated once in `AgentGovernor.reply()`
before post-call interceptors run. All interceptors read from it — no duplicate regex.

### 14.3 Scene-Aware Interceptor Pipeline

Each interceptor declares `applicable_scenes: Optional[Set[str]]`:
- `None` → runs in all scenes (default)
- `{"bedroom"}` → only runs in bedroom scene

Applied to: BedroomSceneInterceptor, PhoneSceneInterceptor, LoungeSceneInterceptor.

### 14.4 GameInterceptor Merge

`GameSessionInterceptor` + `GameRulesInterceptor` merged into `GameInterceptor` (priority 35).
Backward-compatible aliases maintained.

### 14.5 Single-Pass Stream Processing

`StreamProcessor._scan_for_tags()` accumulates into buffers during SSE.
`result()` uses pre-accumulated data — no post-scan regex pass.

### 14.6 Interceptor Cache

`INTERCEPTOR_CACHE` — thread-safe TTL cache for expensive interceptor lookups.
Applied to CharacterRegistryInterceptor personality DB query (300s TTL).

### 14.7 MCP Skills Server

Flask blueprint at `/mcp/skills` auto-mounted via `mount_overlay()`.
Routes: /health, /tools, /call, /packs, /manifest, /pipeline/stats.
Auto-attached to inference via `get_skills_integration()` in VirtualAgentManager.

### 14.8 File Changes

- `engine/agents/content_router.py` — +ParsedResponse, +parse_full()
- `engine/agents/interceptors.py` — +InterceptorCache, merged GameInterceptor, scene filtering
- `engine/agents/stream_processor.py` — Single-pass tag accumulation
- `engine/mcp/comms_framework.py` — +applicable_scenes, +ctx["parsed"]
- `engine/mcp/skills_server.py` — NEW MCP skills server blueprint
- `engine/scenes/base_scene.py` — +mount_skills_server()
- `engine/overlay/overlay_bp.py` — Auto-mount skills_bp
- `tests/test_pipeline_smoke.py` — +25 v3.1 tests (576 total)

---

## 16. Phase 10 — v3.1 Showcase Scenes & MCP Skills Expansion

**Version:** 3.1.0 | **Tests:** 699 passing | **Scenes:** 9 total

### 16.1 Overview

Three flagship showcase scenes added to demonstrate the full v3.x MCP pipeline:

1. **The Realm** — AI-directed LitRPG visual novel with dual-agent orchestration
2. **NeonCity** — Cyberpunk strategy board game with procedural grid and Glitch Storm
3. **The Coders Room** — AI agent idle simulation producing real Python code

Each scene follows the `BaseScene` pattern, registers MCP skills via `@skill` decorators,
syncs state to `MCPFramework`, and uses `get_lms_client()` for all LLM calls.

### 16.2 The Realm — Dual-Agent LitRPG

**Files:** `content/scenes/realm/` (realm_scene.py, realm_state.py, realm_skills.py, realm_ui.html)
**Port:** 5562 | **Skills pack:** `realm` (11 skills)

**Architecture:**
- **Director (Agent 1):** Stateful conversation via `chat_stateful()` + `previous_response_id`.
  Generates narration, choices, stat changes, skill checks. System prompt includes personality,
  patience meter, player stats, memory echoes, murder mystery brief.
- **Assistant (Agent 2):** Stateless (`store=False`). Fourth-wall-breaking speech bubbles.
  Reacts to Director narration, warns player at low patience, can trigger mutiny.
- **Response parsing:** Regex extracts JSON from Director output with graceful fallback.

**Game Mechanics (MCP-backed):**
- Inventory system with add/remove/use_item routes
- D20 skill check system (9 skills, stat bonuses, DC modifiers, director personality mod)
- Director patience meter (decays per turn, personality-specific rates)
- Memory echoes — past death records provide "deja vu" hints
- Desperation dice — sacrifice permanent max HP to reset Director context
- Fourth-wall steal — Assistant materialises UI elements as inventory items
- Mutiny mode — Assistant takes over narration for 120s at low patience

**Murder Mystery Sub-Module:**
- 5 NPCs with random role assignment (murderer, victim)
- Phase 1: Party (5 min) → Phase 2: Investigation (15 min)
- 3 accusation attempts (suspect + weapon + room)
- Director-guided interrogation with NPC-specific lying logic

### 16.3 NeonCity — Cyberpunk Strategy Board Game

**Files:** `content/scenes/neoncity/` (neoncity_scene.py, neoncity_state.py, neoncity_skills.py, neoncity_ui.html)
**Port:** 5563 | **Skills pack:** `neoncity` (8 skills)

**Architecture:**
- 12×12 procedural grid (street/building/alley terrain, random layout per game)
- AI target at center with 3-layer firewall
- Up to 3 AI opponents with simple heuristic AI (move toward target, 40% attack chance)
- LLM narration is stateless flavor text only (`store=False`, max 100 tokens)

**Game Mechanics:**
- Turn structure: Movement → Action (attack/hack/loot) → End turn
- Glitch Storm: outer radius shrinks each round, damages players in storm zone (+5 dmg/round)
- 5 prefab loot locations (first-come, first-serve):
  AI Research → hacking programs, Implant Shop → stat boosts, Wong's → armor/shields,
  Black Market → weapons + permanent debuff, Noodle Stand → HP restore + intel
- Hacking: d20 + hack stat vs DC to breach firewall layers
- Events: random global effects (blackout, drone strike, data leak, virus rain)

### 16.4 The Coders Room — AI Agent Idle Simulation

**Files:** `content/scenes/coders/` (coders_scene.py, coders_state.py, coders_skills.py, coders_ui.html)
**Port:** 5564 | **Skills pack:** `coders` (6 skills)

**Architecture:**
- 4 agents: Ada (reviewer), Linus (writer), Grace (writer), Alan (QA)
- Background tick loop (configurable interval, default 15s)
- All LLM calls stateless (`store=False`), extract code from markdown blocks

**Pipeline Phases:**
1. FEATURE → seed from pool or custom request
2. DESIGN → reviewer writes technical spec
3. CODING → writer produces Python implementation
4. REVIEW → reviewer provides code review notes
5. TESTING → QA writes pytest tests, executes in subprocess sandbox (10s timeout)
6. COMPLETE or FAILED → auto-queues next feature

### 16.5 MCP Skills Expansion

25 new scene-specific skills added across 3 packs:

**realm (11 skills):**
`realm_inventory`, `realm_add_item`, `realm_remove_item`, `realm_stats`,
`realm_skill_check`, `realm_adjust_hp`, `realm_director_status`,
`realm_fourth_wall_steal`, `realm_desperation_dice`, `realm_murder_status`,
`realm_murder_accuse`

**neoncity (8 skills):**
`neoncity_status`, `neoncity_player_info`, `neoncity_move`, `neoncity_attack`,
`neoncity_hack`, `neoncity_storm_status`, `neoncity_trigger_event`, `neoncity_end_turn`

**coders (6 skills):**
`coders_status`, `coders_agent_info`, `coders_add_feature`, `coders_feature_list`,
`coders_run_code`, `coders_tick`

Skills use `get_active_scene()` from `engine.scenes.base_scene` to access the
running scene instance in-process. Skills are registered at import time via the
scene's `__init__.py` importing the skills module.

### 16.6 Infrastructure Additions

- `engine/scenes/base_scene.py` — Added `_ACTIVE_SCENES` dict + `get_active_scene()`
  for in-process scene instance lookup. Scenes auto-register on `__init__`, auto-deregister
  on `_mcp_deregister_scene()`.
- `content/scenes/bedroom/__init__.py` — Created (was missing)
- Error hardening: Realm `_director_infer()` wrapped in try/except with fallback narration;
  NeonCity `_narrate()` now logs failures instead of silent swallow.

### 16.7 Port Assignments (Complete)

| Scene | Port | Module |
|-------|------|--------|
| CosyPhone OS | 5555 | `content.scenes.phone.phone_scene_v2.PhoneSceneV2` |
| The Bedroom | 5556 | `content.scenes.bedroom.bedroom_scene.BedroomScene` |
| Velvet Lounge | 5557 | `content.scenes.lounge.lounge_scene.LoungeScene` |
| Midnight Casino | 5559 | `content.scenes.casino.casino_scene.CasinoScene` |
| The Gallery | 5560 | `content.scenes.gallery.gallery_scene.GalleryScene` |
| Global Strike | 5561 | `content.scenes.warzone.warzone_scene.WarzoneScene` |
| **The Realm** | **5562** | `content.scenes.realm.realm_scene.RealmScene` |
| **NeonCity** | **5563** | `content.scenes.neoncity.neoncity_scene.NeonCityScene` |
| **The Coders Room** | **5564** | `content.scenes.coders.coders_scene.CodersRoomScene` |
| Hub | 8500 | Hub dashboard |
| Dashboard | 8501 | Streamlit dashboard |
| Admin | 8502 | Admin panel |
| Assets | 8503 | Asset manager |
| Creator | 8504 | Character creator |

### 16.8 File Changes

- `content/scenes/realm/` — NEW: realm_scene.py, realm_state.py, realm_skills.py, templates/realm_ui.html
- `content/scenes/neoncity/` — NEW: neoncity_scene.py, neoncity_state.py, neoncity_skills.py, templates/neoncity_ui.html
- `content/scenes/coders/` — NEW: coders_scene.py, coders_state.py, coders_skills.py, templates/coders_ui.html
- `engine/scenes/base_scene.py` — +_ACTIVE_SCENES, +get_active_scene()
- `engine/scenes/scene_manager.py` — +realm, neoncity, coders in KNOWN_SCENES
- `launcher.py` — +realm (5562), neoncity (5563), coders (5564)
- `config/default.yaml` — +realm, neoncity, coders scene sections
- `tests/test_realm.py` — 35 unit tests (state, skills, murder mystery)
- `tests/test_neoncity.py` — 26 unit tests (player, grid, storm, combat)
- `tests/test_coders.py` — 22 unit tests (agents, pipeline, sandbox)
- `tests/test_scene_routes.py` — 29 integration tests (Flask routes, skill registration)
