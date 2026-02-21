# LMStudio Agent Framework — Design Document

> **Generated:** Phase 3 — For agents and developers working with CosySim

---

## 1. Purpose

This document gives AI agents and human developers everything they need to
**understand, use, and extend** the CosySim agent framework.  It covers the
complete loop from config → agent → LLM → skill execution → response → state update.

Read this document before making changes to scenes, agents, or the MCP system.

---

## 2. Core Concepts

### 2.1 The Sandwich Control Pattern

CosySim controls LLM agents using a **sandwich** approach:

```
 ┌─────────────────────────────┐
 │     SYSTEM PROMPT           │  ← We control this (personality, rules, context)
 │     (top bread)             │
 ├─────────────────────────────┤
 │     LLM GENERATION          │  ← Agent has freedom here
 │     (filling)               │
 ├─────────────────────────────┤
 │     POST-PROCESSING         │  ← We control this (governor pipeline, state update)
 │     (bottom bread)          │
 └─────────────────────────────┘
```

**Before the LLM sees anything:**
1. System prompt is assembled from character profile + scene context + rules + stats
2. Conversation history is curated (summarised, trimmed, enriched)
3. Active game state, mood vectors, location info injected into context

**The LLM generates freely** — its creativity is the "filling" that makes each
response unique.  We don't template or script its output.

**After the LLM replies:**
1. Governor pipeline validates (profanity, OOC detection, length checks)
2. Response directives are applied (nudge, redirect, stat consequences)
3. State is updated (mood, relationships, game progress, memories)
4. Events are emitted to the framework bus

### 2.2 Why This Works

- **Rules without rigidity** — The agent follows constraints without sounding scripted
- **Rich state** — Emotional stats, relationships, memories create emergent behaviour
- **Interception** — Post-processing catches problems without re-generating
- **MCP tools** — The agent can call skills (mood changes, image gen, etc.) as part of generation

---

## 3. Architecture Overview

```
config/default.yaml
        │
        ▼
┌───────────────┐    ┌──────────────────┐    ┌────────────────┐
│  MCPFramework │◄───│  Scene (Flask)   │◄───│  Browser/Admin │
│  (singleton)  │    │  + SocketIO      │    │  + Overlay     │
└───────┬───────┘    └────────┬─────────┘    └────────────────┘
        │                     │
        ▼                     ▼
┌───────────────┐    ┌──────────────────┐
│ AgentProfiles │    │  CharacterAgent  │
│ Timers        │    │  AgentLoop       │
│ EventBus      │    │  CharacterLoop   │
│ Consequences  │    └────────┬─────────┘
│ StatePersist  │             │
└───────────────┘             ▼
                     ┌──────────────────┐    ┌────────────────┐
                     │    LMSClient     │───▶│   LMStudio     │
                     │  InferenceConfig │    │   Server       │
                     │  ResourceManager │    └────────────────┘
                     └──────────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  MCP Skills      │
                     │  24 skills       │
                     │  8 packs         │
                     └──────────────────┘
```

### 3.1 Three-Layer Architecture

| Layer | Directory | Purpose |
|-------|-----------|---------|
| **Engine** | `engine/` | Reusable framework code — agents, LLM client, MCP, skills, overlay |
| **Content** | `content/` | Game-specific scenes, characters, templates, media |
| **Config** | `config/` | YAML settings, no code |

**Rule:** Engine code never imports from content.  Content imports from engine.

---

## 4. The MCP Framework

`engine/mcp/framework.py` — The root singleton (`get_framework()`).

### 4.1 What It Provides

| Feature | API | Purpose |
|---------|-----|---------|
| **Agent Profiles** | `get_agent_profile(role)` | Per-role inference config (model, tokens, temperature) |
| **Event Bus** | `emit_event(name, data)` / `on(name, fn)` | Decoupled inter-system communication |
| **Lifecycle Hooks** | `on("framework_ready", fn)` | Scene startup/shutdown coordination |
| **Timers** | `MCPTimer(name, interval, fn)` | Periodic ticks (agent autonomy, decay, cleanup) |
| **Consequences** | `add_consequence(trigger, effects)` | Delayed state changes from actions |
| **State Persistence** | `save_state()` / `load_state()` | Cross-restart data survival |
| **Scene Registry** | `register_scene(node)` / `get_scene(id)` | Scene discovery and cross-scene comms |
| **Random Events** | `random_pick(pool, weights)` | Weighted random selection for atmospheric events |
| **Cross-Scene Send** | `cross_scene_send(from, to, msg)` | Phone notifications during casino, etc. |

### 4.2 Agent Profiles

Defined in YAML, used to configure inference per agent role:

```yaml
# config/default.yaml
llm:
  profiles:
    big:
      model: "qwen2.5-14b-instruct"
      max_tokens: 3000
      temperature: 0.8
      top_p: 0.95
    small:
      model: "qwen2.5-3b-instruct"
      max_tokens: 1000
      temperature: 0.7
    game_master:
      model: "qwen2.5-7b-instruct"
      max_tokens: 2000
      temperature: 0.5
```

Usage:
```python
from engine.lmstudio.inference_config import InferenceConfig
cfg = InferenceConfig.from_agent_profile("big")
# → temperature=0.8, max_output_tokens=3000, model="qwen2.5-14b-instruct"
```

### 4.3 Event Bus

```python
fw = get_framework()

# Listen
fw.on("mood_changed", lambda evt: handle_mood(evt))

# Emit
fw.emit_event("mood_changed", {
    "character": "Luna",
    "mood": "happy",
    "source": "compliment",
})
```

Events propagate instantly and synchronously.  Use for:
- Stat changes that affect other systems
- Cross-agent notifications
- UI updates (via SocketIO relay)

### 4.4 Timers & Consequences

```python
# Timer: tick every 30 seconds
timer = MCPTimer("agent_tick", interval=30, callback=agent_think)
fw.register_timer(timer)

# Consequence: delayed effect
fw.add_consequence(
    trigger="drink_cocktail",
    effects=[
        {"type": "stat_adjust", "stat": "focus", "delta": -5, "delay": 60},
        {"type": "emit_event", "event": "drunk_stumble", "delay": 120},
    ],
)
```

---

## 5. Skills System

`engine/skills/` — 24 registered skills across 8 packs.

### 5.1 How Skills Work

Skills are Python functions decorated with `@skill(...)`.  They auto-register at
import time and are exposed to the LLM as callable tools via MCP.

```python
from engine.skills.skill import skill

@skill(pack="social", tags=["mood", "emotion"])
def mood_contagion(source_char: str, target_char: str, emotion: str, strength: float = 0.5) -> str:
    """Spread an emotion from one character to nearby characters."""
    # ... implementation ...
    return f"{target_char} catches {source_char}'s {emotion}"
```

### 5.2 Skill Execution Flow

```
LLM decides to call a skill
        │
        ▼
MCP Server receives tool_call
        │
        ▼
SKILL_REGISTRY.execute(name, args)
        │
        ▼
Skill function runs, returns str
        │
        ▼
Result fed back to LLM as tool_result
        │
        ▼
LLM incorporates result into response
```

### 5.3 Current Skill Packs

| Pack | Skills | Purpose |
|------|--------|---------|
| `core` | check_time, wait, log | Basic utilities |
| `social` | mood_contagion, relationship_adjust, gossip, empathy_read | Social dynamics |
| `media` | generate_image, generate_voice, generate_video | Content generation |
| `memory` | remember, recall, forget | Long-term memory |
| `scene` | change_location, describe_environment | Scene navigation |
| `communication` | send_message, check_messages | Cross-agent messaging |
| `game` | roll_dice, draw_card, check_score | Game mechanics |
| `admin` | get_status, set_config | System administration |

### 5.4 Creating a New Skill

1. Create a file in `engine/skills/builtin/` (or a scene-specific skills file)
2. Decorate with `@skill(pack="my_pack", tags=[...])`
3. Return a string (the LLM sees this as the tool result)
4. Import the file somewhere so the decorator runs at startup

```python
# engine/skills/builtin/weather_skills.py
from engine.skills.skill import skill

@skill(pack="environment", tags=["weather", "atmosphere"])
def set_weather(condition: str, intensity: float = 0.5) -> str:
    """Change the weather in the current scene."""
    from engine.mcp.framework import get_framework
    fw = get_framework()
    fw.emit_event("weather_changed", {"condition": condition, "intensity": intensity})
    return f"Weather changed to {condition} (intensity: {intensity})"
```

---

## 6. Creating a Scene

Scenes are Flask+SocketIO apps in `content/scenes/<scene_name>/`.

### 6.1 Minimal Scene Structure

```
content/scenes/my_scene/
├── my_scene.py          # Main scene class
├── templates/
│   └── index.html       # Browser UI
├── static/
│   ├── css/style.css
│   └── js/app.js
└── (optional) my_scene_skills.py
```

### 6.2 Scene Class Template

```python
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from pathlib import Path
import sys

# Ensure project root on path
_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_root))

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework

SCENE_ID = "my_scene"
SCENE_PORT = 5560

class MyScene(BaseScene, MCPSceneMixin):
    def __init__(self, host="0.0.0.0", port=SCENE_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "my_scene_secret"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", manage_session=False)

        # Mount control overlay
        from engine.overlay import mount_overlay
        mount_overlay(self.app, self.socketio)

        self._setup_routes()
        self._setup_socketio()
        self._mcp_init()

    def _mcp_init(self):
        fw = get_framework()
        node = fw.register_scene(SCENE_ID, port=SCENE_PORT)
        # Register event handlers, timers, consequences...

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            return render_template("index.html")

        @self.app.route("/api/state")
        def get_state():
            return jsonify({"scene": SCENE_ID, "status": "running"})

    def _setup_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            emit("connected", {"scene": SCENE_ID})

    def start(self):
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False)
```

### 6.3 Registering with the Hub

Add to the scene registry in the hub or launcher so it appears in the scene selector.

### 6.4 Agent Integration

Each character in a scene needs:
1. A `CharacterAgent` instance (or use `CharacterLoop` for autonomous agents)
2. A system prompt built from profile + scene context + rules
3. Conversation management (history, summarisation, trimming)
4. An `InferenceConfig` (from agent profile or custom)

```python
from engine.agents.character_agent import CharacterAgent
from engine.lmstudio.inference_config import InferenceConfig

agent = CharacterAgent(
    name="Luna",
    system_prompt="You are Luna, a curious stargazer...",
    inference_config=InferenceConfig.from_agent_profile("big"),
)

# Get agent response
reply = agent.respond(user_message, context={
    "location": "rooftop",
    "time": "midnight",
    "mood": {"happiness": 70, "curiosity": 90},
})
```

---

## 7. The Governor Pipeline

Every LLM response passes through a governor pipeline before reaching the user:

```
LLM raw response
        │
        ▼
┌─────────────────────┐
│  Profanity filter    │  (optional, per-scene)
├─────────────────────┤
│  OOC detection       │  catches "(OOC: ...)" or meta-commentary
├─────────────────────┤
│  Length check        │  truncates if exceeds max
├─────────────────────┤
│  ResponseDirective   │  applies nudges, redirects, stat effects
├─────────────────────┤
│  State update        │  mood shifts, relationship changes
├─────────────────────┤
│  Event emission      │  bus events for other systems
└─────────────────────┘
        │
        ▼
Final response to user
```

### ResponseDirective

Scenes can attach directives that steer the agent without regenerating:

```python
directive = ResponseDirective(
    character="Luna",
    nudge="Express growing curiosity about the stars",
    stat_effects={"curiosity": +10},
    forbidden_topics=["politics", "religion"],
    required_elements=["mention the constellation"],
)
```

The directive is injected into the system prompt before the next generation,
and stat effects are applied after.

---

## 8. LMStudio Integration

### 8.1 Call Flow

```
Scene receives user input
    │
    ▼
CharacterAgent.respond()
    │
    ▼
Build system prompt + history + InferenceConfig
    │
    ▼
LMSClient.chat(messages, config=cfg)
    │
    └─── /api/v1/chat (native v1 — ALL requests)
              │
              ├─── integrations: [ephemeral_mcp]
              │         │
              │         ▼
              │    LLM calls skills as tools during inference
              │         │
              │         ▼
              │    tool_calls? → execute → feed back → re-call
              │
              └─── LMSResponse
                     │
                     ▼
                Governor pipeline
                     │
                     ▼
                Final response + state update
```

### 8.2 Inference Parameters

All parameters flow through `InferenceConfig`:

```python
# YAML defaults (applied to every request)
# config/default.yaml → lmstudio.inference_defaults

# Per-profile overrides
cfg = InferenceConfig.from_agent_profile("big")

# Per-request overrides
cfg = InferenceConfig(temperature=0.3, reasoning=True)

# Merge chain
final = InferenceConfig.merge(
    InferenceConfig.from_yaml(),          # YAML defaults
    InferenceConfig.from_agent_profile(), # profile overrides
    InferenceConfig(temperature=0.3),     # request overrides
)
```

### 8.3 MCP Tool Calling

When the LLM needs to call a skill, it happens via MCP:

1. System prompt includes available skills as tool descriptions
2. LLM generates a `tool_call` in its response
3. `tool_factory.run_with_tools()` detects the call and executes the skill
4. Skill result is sent back as a `tool` message
5. LLM continues generation with the result

Ephemeral MCP: Skills can also be attached per-request via `integrations` field.
LMStudio's MCP integration handles the tool execution loop on the server side.

### 8.4 ResourceManager Integration

Before every inference call, check model readiness:

```python
rm = get_resource_manager()
model_id = rm.acquire("luna", role="big")  # ensures model is loaded
# ... inference ...
rm.release("luna")
```

The ResourceManager handles:
- Loading the right model for the strategy
- Evicting idle models when VRAM is tight
- Queuing background tasks for CPU execution
- Switching strategies at runtime via admin panel

---

## 9. State Management

### 9.1 Scene State (SceneStateManager)

Per-character stats tracked in the scene:

```python
from engine.state import SceneStateManager
ssm = SceneStateManager()

# Set stats
ssm.set("bedroom", "Luna", "mood", {"happiness": 70, "arousal": 40})
ssm.set("bedroom", "Luna", "outfit", "silk robe")

# Get stats
mood = ssm.get("bedroom", "Luna", "mood")

# Adjust (atomic increment)
ssm.adjust("bedroom", "Luna", "mood.happiness", delta=10)
```

### 9.2 Game State (GameState)

Key-value store for game mechanics:

```python
from engine.state import GameState
gs = GameState()

gs.set("casino", "pot", 500)
gs.set("casino", "round", 3)
pot = gs.get("casino", "pot")
```

### 9.3 Conversation Memory

Characters have layered memory:
1. **Short-term**: Recent messages in conversation history
2. **Summary**: Periodic summarisation of older messages
3. **Long-term**: Key facts stored via `remember` skill → SQLite
4. **RAG**: Personality files, backstory, scene lore (if configured)

### 9.4 Persistence

State survives restarts:
```python
fw = get_framework()
fw.save_state()   # saves to asset_registry.db
fw.load_state()   # restores from DB
```

---

## 10. The Control Overlay

Mounted on every scene at `/overlay/`.  Provides real-time admin access.

### 10.1 Tabs

| Tab | Function |
|-----|----------|
| **Status** | System health, loaded models, active agents, VRAM usage |
| **Agents** | Per-agent stats, mood, history, edit personality |
| **Models** | Load/unload models, view context length, VRAM estimates |
| **Config** | Edit inference defaults, resource manager strategy, TTL |
| **Skills** | Browse registered skills, test execution, cooldown status |
| **Events** | Live event stream from ActivityBus |
| **Act** | Send messages as any agent, inject events, override responses |
| **Inference** | Test inference calls, view request/response, benchmark |

### 10.2 Access

Navigate to any scene's URL + `/overlay/`:
- Phone: `http://localhost:5555/overlay/`
- Bedroom: `http://localhost:5556/overlay/`
- Casino: `http://localhost:5559/overlay/`

### 10.3 API Endpoints

All under `/overlay/api/`:
- `GET /overlay/api/status` — System overview
- `GET /overlay/api/agents` — All agent states
- `POST /overlay/api/agents/<id>/message` — Send message as agent
- `GET /overlay/api/models` — Loaded models
- `POST /overlay/api/models/load` — Load a model
- `POST /overlay/api/models/unload` — Unload a model
- `GET /overlay/api/config` — Current config
- `POST /overlay/api/config` — Update config
- `GET /overlay/api/skills` — Registered skills
- `GET /overlay/api/events/stream` — SSE event stream
- `POST /overlay/api/inference/test` — Test inference call

---

## 11. Balancing Rules vs Freedom

The key challenge is giving the LLM enough freedom to be creative while
maintaining narrative consistency and rule compliance.

### 11.1 Guidance Spectrum

```
STRICT ◄─────────────────────────────────► FREE

Scripted    Directed    Guided    Nudged    Open
responses   responses   responses responses responses
```

| Approach | When to Use |
|----------|-------------|
| **Scripted** | Game rules, factual answers, system responses |
| **Directed** | "Give Line" tool — agent must say specific text |
| **Guided** | ResponseDirective nudges toward topic/mood |
| **Nudged** | System prompt hints, soft suggestions |
| **Open** | Freeform conversation, creative moments |

### 11.2 Techniques

1. **System prompt engineering** — The most important lever.  Include personality,
   current situation, mood stats, and soft guidelines.

2. **ResponseDirective** — Post-generation steering.  Inject nudges for next turn.

3. **Stat-driven context** — "Your happiness is 30/100.  You feel melancholy."
   The LLM naturally adjusts tone.

4. **Consequence chains** — Actions have delayed effects that reshape future context.

5. **Structured output** — For game mechanics (action selection, dice rolls),
   use JSON schema enforcement so the LLM produces parseable output.

6. **Governor pipeline** — Catch and correct problems after generation.

### 11.3 Anti-Patterns

- ❌ Don't over-constrain — if every response is directed, it feels scripted
- ❌ Don't under-constrain — agents will go off-topic or break character
- ❌ Don't ignore stats — if an agent is "terrified" but acts brave, break immersion
- ❌ Don't re-generate — governor pipeline should fix, not regenerate (expensive)

---

## 12. Scene Walkthroughs

### 12.1 Phone Scene

**Port 5555** — iOS-style messaging.

- **Agents:** Multiple contacts, each a `CharacterAgent` with autonomous texting
- **Key feature:** Stateful chats (`previous_response_id`) for efficient long conversations
- **MCP:** Governor pipeline on every AI reply, truth-or-dare game via MCPGameSession
- **Media:** Voice messages, photo sharing, video messages
- **State:** Per-thread message history in PhoneDB (SQLite)

### 12.2 Bedroom Scene

**Port 5556** — Multi-agent roleplay with Director tools.

- **Agents:** 2-3 characters with full emotional stat vectors
- **Key feature:** Director tools (whisper, give line, story beat, env event)
- **MCP:** Scene state sync, consequence chains for mood/outfit changes
- **Structured output:** Agent action parsing (speak/move/emote)
- **State:** Location tracking, outfit tracking, relationship meters

### 12.3 Casino Scene

**Port 5559** — Texas Hold'em poker.

- **Agents:** Dealer Jack, Hustler Mira
- **Key feature:** Full poker game engine with MCPGameSession
- **MCP:** Every framework feature demonstrated
- **Skills:** mood_contagion, relationship_adjust, random atmospheric events
- **State:** Chips, confidence, focus, luck meters

### 12.4 Lounge Scene

**Port 5557** — 1920s jazz speakeasy.

- **Agents:** Lola Voss (singer), Viktor Marlowe (bartender)
- **Key feature:** Trust economy gates secrets, back room, premium pours
- **MCP:** Heat meter, consequence chains (drink effects), cross-agent comms
- **Skills:** Performance system, mood contagion on song finish
- **State:** Heat level, guest trust, secrets revealed

---

## 13. Port Allocation

| Service | Port |
|---------|------|
| LMStudio | 1234 |
| Phone Scene | 5555 |
| Bedroom Scene | 5556 |
| Lounge Scene | 5557 |
| Casino Scene | 5559 |
| Hub/Launcher | 8500 |
| Admin Panel | 8502 |
| TTS Service | 8600 |
| Scene Bridge | 8601 |
| MCP Skills Server | 8700 |

---

## 14. Quick Reference: Common Tasks

### Add a new character to an existing scene

1. Define character profile (name, personality, system prompt)
2. Create `CharacterAgent` instance with `InferenceConfig`
3. Add to scene's character roster
4. Set initial stats in `SceneStateManager`
5. Register autonomous timer if needed

### Change inference settings at runtime

```python
# Via overlay panel: Config tab → edit and save
# Via API:
POST /api/mcp/inference-defaults
{"temperature": 0.5, "max_output_tokens": 3000}
```

### Switch model strategy

```python
# Via overlay panel: Config tab → strategy dropdown
# Via API:
POST /api/mcp/resources/config
{"strategy": "jit_swap", "default_ttl": 600}
```

### Debug an agent's behaviour

1. Open overlay → Agents tab → select agent
2. View current stats, mood, recent history
3. Check Events tab for recent framework events
4. Use Act tab to inject test messages
5. Adjust stats directly via API

### Run a background task

```python
rm = get_resource_manager()
rm.queue_background_task(
    "generate_profile_pic",
    generate_image_fn,
    args=("portrait of Luna under stars",),
    device="cpu",
)
```

---

## 14. VirtualAgent Framework

### 14.1 Concept: Separating Agent Identity from LLM Execution

CosySim's VirtualAgent framework decouples the *concept* of an agent (identity,
state, conversation, prompt building) from the *execution* of LLM inference.

**Our agents act like LLM agents, but we control every call to LMStudio.**

```
┌────────────────────┐     InferenceRequest     ┌──────────────────────────┐
│  VirtualAgent      │ ──────────────────────▶  │  VirtualAgentManager     │
│  - character data  │                          │  - model routing         │
│  - state (mood,    │                          │  - concurrency control   │
│    energy, etc.)   │  InferenceResponse       │  - JIT load/unload       │
│  - RAG memories    │ ◀──────────────────────  │  - conversation state    │
│  - prompt building │                          │  - batch inference       │
│  - IAgent protocol │                          │  - hooks (pre/post)      │
└────────────────────┘                          └──────────────────────────┘
                                                          │
                                                    ┌─────┴─────┐
                                                    │ LMSClient │
                                                    │ /api/v1   │
                                                    └───────────┘
```

### 14.2 Key Classes

**VirtualAgent** (`engine/agents/virtual_agent.py`):
- Implements `IAgent` protocol (drop-in replacement for CharacterAgent)
- Manages local state: mood, energy, arousal, custom keys
- Builds system prompts with persona, RAG memories, MCP brief
- Produces `InferenceRequest` objects
- Processes `InferenceResponse` objects (logs events, updates state)
- Never calls LMSClient directly

**VirtualAgentManager** (`engine/agents/virtual_agent_manager.py`):
- Singleton: `get_virtual_agent_manager()`
- Creates/registers/unregisters agents
- Routes `InferenceRequest` → LMSClient via ConversationManager
- `infer()` — single request
- `infer_batch()` — parallel requests via ConcurrentExecutor
- Pre/post hooks for logging, monitoring, custom logic

**InferenceRequest** / **InferenceResponse** — typed dataclasses for the
request/response contract between agents and the manager.

### 14.3 Using VirtualAgent in a Scene

```python
from engine.agents.virtual_agent_manager import get_virtual_agent_manager

mgr = get_virtual_agent_manager()

# Create agent (auto-registers + sets up ConversationManager)
agent = mgr.create_agent(character, scene="bedroom", model="gemma-3-4b")

# Interactive reply — goes through manager → ConversationManager → LMSClient
reply = agent.reply("Hey, what are you thinking about?")

# Batch decisions for multiple agents
requests = [a.build_request(context) for a in agents]
responses = mgr.infer_batch(requests)

# Stats for overlay
stats = mgr.get_stats()
```

---

## 15. v2.5 — VirtualAgent as Primary

**As of v2.5, VirtualAgent is the ONLY path for all LLM calls.**

### What Changed

| Component | Before (v2) | After (v2.5) |
|-----------|-------------|--------------|
| CharacterAgent | Full LLM client, VirtualAgent opt-in | Thin wrapper — always delegates to VirtualAgent |
| AgentLoop._decide() | Direct `agent.reply()` or `agent.quick_query()` | `agent.quick_query()` → VirtualAgentManager; structured output schema |
| AgentLoop.tick() | Sequential per-character | 3-phase: perceive-all → batch-decide → execute-all |
| SceneAgent.run() | Direct `get_lms_client().chat()` | `VirtualAgentManager.infer()` |
| State persistence | None | Auto-persist to `data/agent_state.db` after every inference |

### Creating Agents (v2.5)

```python
from engine.agents import CharacterAgent

# CharacterAgent always creates a VirtualAgent internally
agent = CharacterAgent(char, scene="bedroom", skill_packs=["memory"])
reply = agent.reply("Hello!")

# Or use VirtualAgent directly
from engine.agents import get_virtual_agent_manager
mgr = get_virtual_agent_manager()
agent = mgr.create_agent(char, scene="bedroom")
reply = agent.reply("Hello!")
```

### Batch Inference

```python
# Build requests for multiple agents
requests = [agent.build_request(context) for agent in agents]
responses = mgr.infer_batch(requests)
for agent, resp in zip(agents, responses):
    agent.process_response(resp)
```

### State Persistence

```python
agent.update_state(mood="excited", energy=0.8)  # auto-persists to DB
state = agent.get_state()  # includes all custom keys
agent.save_state()  # explicit persist
agent.load_state()  # explicit load (auto-called on init)
```

### Structured Output

```python
from engine.agents.virtual_agent import InferenceRequest

request = InferenceRequest(
    agent_id=agent.id,
    messages=[...],
    structured_schema={
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["speak", "move"]}},
        "required": ["action"],
    },
    schema_name="agent_decision",
)
response = mgr.infer(request)
import json
decision = json.loads(response.content)
```
