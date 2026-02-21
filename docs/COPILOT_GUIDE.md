# CosySim — The Complete Developer & AI Agent Guide

> Battle-tested lessons, architecture deep-dives, templates for everything,
> pitfalls that cost hours, and the full picture of what this system can do.
> Read this before touching anything.

---

## Table of Contents

1. [What CosySim Actually Is](#1-what-cosysim-actually-is)
2. [The Three Pillars](#2-the-three-pillars)
3. [Core Concepts You Must Understand](#3-core-concepts-you-must-understand)
4. [The Governor Trap — Lesson One](#4-the-governor-trap--lesson-one)
5. [Architecture Rules (Non-Negotiable)](#5-architecture-rules-non-negotiable)
6. [Complete Skeleton Templates](#6-complete-skeleton-templates)
7. [Skill System — Deep Dive](#7-skill-system--deep-dive)
8. [Agent Loop — How Autonomous Agents Work](#8-agent-loop--how-autonomous-agents-work)
9. [The AgentGovernor & Interceptor Pipeline](#9-the-agentgovernor--interceptor-pipeline)
10. [EventChain — The Ground Truth](#10-eventchain--the-ground-truth)
11. [Spatial System](#11-spatial-system)
12. [Scene Frontend Patterns (Three.js + SocketIO)](#12-scene-frontend-patterns-threejs--socketio)
13. [Config System](#13-config-system)
14. [Logging, Benchmarking & Monitoring](#14-logging-benchmarking--monitoring)
15. [Testing Best Practices](#15-testing-best-practices)
16. [What the System Can Do](#16-what-the-system-can-do)
17. [Pitfalls & Things to Watch Out For](#17-pitfalls--things-to-watch-out-for)
18. [Lessons Learned — The Good, the Bad, the Ugly](#18-lessons-learned--the-good-the-bad-the-ugly)
19. [Common Workflows with Copilot](#19-common-workflows-with-copilot)
20. [Quick Reference](#20-quick-reference)

---

## 1. What CosySim Actually Is

CosySim is a **framework for building multi-agent simulation scenes powered by local LLMs**.

Think of it this way:

- The **characters are real LLM agents** — they perceive their environment, make decisions, and execute actions autonomously.
- The **scenes are the game worlds** — a bedroom, a phone interface, a hub, a dashboard.
- The **engine is the platform** — reusable systems: agent loop, skill registry, event chain, spatial map, TTS, image generation.
- The **three pillars** are the services: CosySim orchestrates, LMStudio does inference, ComfyUI does generation.

```
┌──────────────────────────────────────────────────────────────────┐
│                        USER                                      │
│            browser ↔ socket / HTTP ↔ Flask scene                │
├───────────────────────┬──────────────────────────────────────────┤
│   COSYSIM FRAMEWORK   │         EXTERNAL SERVICES                │
│                       │                                          │
│  engine/agents/       │  LMStudio (port 1234)                    │
│  engine/skills/       │  → /v1/chat/completions                  │
│  engine/spatial/      │  → MCP tool host                         │
│  engine/mcp/          │  → SDK for tool-calling agents           │
│  engine/logging/      │                                          │
│  content/scenes/      │  ComfyUI (port 8188)                     │
│  content/simulation/  │  → image/video generation                │
│  config/              │  → workflow API                          │
│                       │                                          │
│                       │  Qwen3-TTS (port 8600)                   │
│                       │  → voice generation                      │
└───────────────────────┴──────────────────────────────────────────┘
```

**Everything routes through the framework.** Scenes don't call LMStudio directly —
they use `CharacterAgent`. Agents don't emit socket events directly — the scene
handles that. Keep the layers clean.

---

## 2. The Three Pillars

### Pillar 1 — CosySim (the Orchestrator)

Manages characters, state, scenes, logging, routing, skills. Never does inference
itself — always delegates to LMStudio. Lives in `engine/` and `content/`.

### Pillar 2 — LMStudio (the Brain)

Local LLM inference at `http://localhost:1234`. Two integration modes:

| Mode | Used For | File |
|------|----------|------|
| **SDK (`lmstudio`)** | Tool-calling agents (skills as tools) | `engine/agents/character_agent.py` |
| **REST `client_v2`** | MCPs, streaming, autonomous decisions | `engine/lmstudio/client_v2.py` |

> **Critical:** The SDK path and the REST path behave differently.
> SDK gives you structured tool calls. REST gives you raw text completions.
> `AgentLoop._decide()` uses REST via `client_v2` — it needs raw JSON, not tool calls.

### Pillar 3 — ComfyUI (the Artist)

Image and video generation via workflow JSON at `http://localhost:8188`.
`PromptBuilder` constructs prompts through a 5-tier escalation system.
`MediaConfig` enforces dimension standards (512×768 selfies, 640×480 video).

### The Golden Rule of the Three Pillars

```
CosySim    orchestrates        (decides WHAT to do)
LMStudio   infers              (decides HOW to say it)
ComfyUI    generates           (decides HOW to draw it)
```

Never collapse these roles. A skill should not call `requests.post()` to LMStudio
directly — use `CharacterAgent.reply()` or `get_lmstudio_client().chat()`.

---

## 3. Core Concepts You Must Understand

### 3.1 The EventChain

> **"If it's not in EventChain, it didn't happen."**

Every interaction gets a `chain_id` (UUID). Every event in that chain links to
its parent via `parent_id`. The result is a causal tree you can replay, debug,
and audit.

```
chain_id = "abc-123"

   message_in          (parent=None)
     └─ rag_query      (parent=message_in)
         └─ rag_result (parent=rag_query)
     └─ llm_request    (parent=message_in)
         └─ tool_call  (parent=llm_request)
             └─ tool_result
         └─ llm_response
     └─ message_out    (parent=llm_response)
```

**16 event types:**

| Type | When |
|------|------|
| `message_in` | User sends a message |
| `message_out` | Agent sends a reply |
| `llm_request` | Before calling LMStudio |
| `llm_response` | After LMStudio responds |
| `llm_cancelled` | Request aborted |
| `rag_query` | Before querying ChromaDB |
| `rag_result` | ChromaDB returns results |
| `memory_stored` | New memory written |
| `skill_called` | Before a skill executes |
| `skill_result` | After a skill executes |
| `tool_call` | LLM invokes a tool |
| `tool_result` | Tool returns a result |
| `media_generated` | Image/video generated |
| `autonomous_trigger` | Autonomous agent action |
| `scene_state_change` | Scene state mutated |
| `error` | Any error |

**How to use it:**

```python
from content.simulation.database.events import EventChain

ec = EventChain(db)
chain_id = ec.start_chain(scene_id="bedroom", character_id=char_id, summary="Agent speaks")
ec.log(
    event_type="autonomous_trigger",
    actor="agent_loop",
    payload={"action": "speak", "message": "Hey..."},
    summary="Agent spoke",
    chain_id=chain_id,
    scene_id="bedroom",
    character_id=char_id,
)
```

**Never bypass it.** Every skill, every agent reply, every generated media item
must be logged. This is how the admin panel's chain browser works.

---

### 3.2 Chain Context (Thread-Local)

The LMStudio SDK calls skill functions directly — you can't pass `chain_id` as a
kwarg because the SDK controls the call signature. Solution: thread-local storage.

```python
# Before calling LLM (in CharacterAgent._act):
from engine.skills.chain_context import set_chain_context, clear_chain_context
set_chain_context(chain_id, scene_id)

# Inside any skill (runs in same thread as LLM call):
from engine.skills.chain_context import get_chain_context
ctx = get_chain_context()  # → {"chain_id": "abc-123", "scene_id": "bedroom"}

# After LLM returns:
clear_chain_context()
```

> **Pitfall:** If you call a skill from a different thread (e.g. asyncio, executor),
> the thread-local context is gone. Always propagate chain_id explicitly in that case.

---

### 3.3 The AgentGovernor

`AgentGovernor` wraps a `CharacterAgent` with a 15-interceptor pipeline.
When `gov.reply("message")` is called:

1. `ResponseContext` is built with system prompt, user message, scene, policy
2. **Pre-call interceptors** run (inject skills, reframe system prompt, add rules)
3. Actual `CharacterAgent.reply()` is called
4. **Post-call interceptors** run (shape output, enforce rules, log)

This is powerful for conversational replies. It is **destructive for JSON action queries**.

See Section 9 for full details.

---

### 3.4 The AgentLoop

Tick-based autonomous decision loop (`engine/agents/agent_loop.py`).

Every N seconds, for every registered character:

```
_perceive(char_id)       →  builds a text context (location, nearby chars, recent convo)
_decide(char_id, ctx)    →  LLM returns JSON: {"action": "...", "target": "...", "message": "..."}
_execute(char_id, decision)  →  applies action to SceneMap, emits socket events, logs to EventChain
```

Valid actions: `speak`, `move`, `interact`, `idle`, `flirt`, `touch`, `kiss`, `cuddle`, `intimate`

---

## 4. The Governor Trap — Lesson One

> **This is the single most important lesson from all development.**
> Read it twice.

### What happened

The bedroom scene had perfectly working agent output — LLMs were responding,
thinking was visible, agents knew to return JSON. But **avatars sat frozen** on
every tick. The scene was fully functional in every other way.

### Root cause

`AgentLoop._decide()` used `agent.reply()` where `agent` was an `AgentGovernor`.

The governor ran its full pipeline on every tick:
- `BedroomSceneInterceptor` (priority 15) → injected a roleplay persona system prompt
- `PersonalityGuardInterceptor` (priority 50) → enforced personality tone
- `ResponseShaperInterceptor` (priority 80) → shaped output for conversational style

The LLM received a completely rewritten system prompt optimised for natural conversation,
not for JSON output. It responded with prose: `"I feel like moving to the bed with you..."`.

`_parse_decision()` scanned for `{` and `}`, found none, returned `{"action": "idle"}`.
Every character. Every tick. Forever.

### The fix

```python
# WRONG — governor pipeline rewrites the prompt for conversation
response = agent.reply(context, history=[{"role": "system", "content": system}])

# CORRECT — skip governance, get raw LLM output for JSON action query
response = agent.reply(
    context,
    history=[{"role": "system", "content": system}],
    use_tools=False,
    skip_gov=True,    # ← THIS IS THE FIX
)
```

`AgentGovernor.reply(skip_gov=True)` calls `self.agent.reply(...)` directly,
bypassing every interceptor. The LLM receives the raw JSON-request prompt.

### The rule

```
Governor pipeline = for CONVERSATIONAL replies (user ↔ character dialogue)
skip_gov=True     = for STRUCTURED queries     (agent loop, game state, JSON output)
quick_query()     = also governance-free        (same as skip_gov=True shorthand)
```

Never call `governor.reply()` without `skip_gov=True` when you need structured output.

---

## 5. Architecture Rules (Non-Negotiable)

### Rule 1: EventChain is sacred

Every user message, every LLM call, every skill invocation, every media item
must be logged to the EventChain. The Admin panel's chain browser, KPI dashboard,
and replay system all depend on this.

### Rule 2: Skills return strings

Skills are the interface between agents and services. They must return `str`.
The LMStudio SDK wraps the result as a `tool_result` message back to the LLM.
Never return dicts, never return None silently.

```python
# WRONG
def search_memory(query: str) -> dict:
    return {"memories": [...]}

# CORRECT
def search_memory(query: str) -> str:
    results = rag.search(query)
    return f"Found {len(results)} memories: " + "; ".join(r.content for r in results)
```

### Rule 3: Config over code

Every port, every URL, every model name, every dimension — lives in YAML.

```python
# WRONG
url = "http://localhost:1234"

# CORRECT
from engine.config import get_config
url = get_config().get("services.lmstudio.base_url", "http://localhost:1234")
```

### Rule 4: Graceful degradation

Every external call (LMStudio, ComfyUI, TTS, ChromaDB) must have a fallback.
A scene must load and function even when all three pillars are offline.

```python
try:
    result = await comfyui.generate(workflow)
except Exception:
    result = get_placeholder_image()  # always works
```

### Rule 5: Engine ≠ Content

`engine/` is the reusable platform. `content/` is instance-specific.
Never import from `content/` inside `engine/`. The dependency arrow is one-way.

```
engine/  ←  content/    ✅ content imports engine
content/ ←  engine/     ❌ engine must not import content
```

### Rule 6: Thread safety on shared state

`AgentLoop.shared_log` is written by multiple character threads and read by the
perceive step of every character. Always use `_log_lock`:

```python
with self._log_lock:
    self.shared_log.append(entry)
    self.shared_log = self.shared_log[-self._shared_log_max:]
```

### Rule 7: Cap unbounded lists

The `shared_log` is capped at 200 entries. Apply the same discipline to any
list that grows over time. Uncapped lists are memory leaks in long-running scenes.

```python
# Always prune after appending
self.my_list.append(item)
self.my_list = self.my_list[-MAX_ITEMS:]
```

---

## 6. Complete Skeleton Templates

### 6.1 New Scene (Flask + SocketIO + Three.js)

**Directory structure:**

```
content/scenes/myscene/
├── __init__.py
├── myscene_scene.py
├── templates/
│   └── myscene.html
└── static/
    ├── css/
    │   └── myscene.css
    └── js/
        └── myscene.js
```

**`myscene_scene.py`:**

```python
"""
MyScene — brief description.
"""
from __future__ import annotations
import logging
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

from engine.scenes.base_scene import BaseScene
from engine.config import get_config

logger = logging.getLogger(__name__)


class MyScene(BaseScene):
    """One-line description."""

    scene_id = "myscene"
    default_port = 5557

    def __init__(self, config=None):
        super().__init__(config)
        self.app = Flask(__name__, template_folder="templates", static_folder="static")
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")
        self._register_routes()
        self._register_socket_handlers()

    # ── Lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        self._before_start()
        port = get_config().get("scenes.myscene.port", self.default_port)
        logger.info("MyScene starting on port %d", port)
        self.socketio.run(self.app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self._before_stop()
        logger.info("MyScene stopped")

    def get_plugin_info(self) -> dict:
        return {
            "name": "My Scene",
            "scene_id": self.scene_id,
            "description": "Brief description",
            "port": get_config().get("scenes.myscene.port", self.default_port),
            "status": "running" if self._started else "stopped",
        }

    # ── Routes ───────────────────────────────────────────────────────
    def _register_routes(self) -> None:
        self.register_health_route(self.app)   # GET /health → always works

        @self.app.route("/")
        def index():
            return render_template("myscene.html")

        @self.app.route("/api/status")
        def api_status():
            return jsonify({"scene": self.scene_id, "status": "ok"})

    # ── Socket handlers ──────────────────────────────────────────────
    def _register_socket_handlers(self) -> None:

        @self.socketio.on("connect")
        def on_connect():
            logger.debug("Client connected: %s", request.sid)
            emit("connected", {"scene": self.scene_id})

        @self.socketio.on("disconnect")
        def on_disconnect():
            logger.debug("Client disconnected: %s", request.sid)

        @self.socketio.on("user_message")
        def on_user_message(data: dict):
            text = data.get("message", "").strip()
            if not text:
                return
            emit("reply", {"message": "...", "timestamp": _now()})


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")
```

**`templates/myscene.html`:**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>My Scene</title>
  <link rel="stylesheet" href="/static/css/myscene.css" />
</head>
<body>
  <div id="app"></div>
  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <script src="/static/js/myscene.js"></script>
</body>
</html>
```

**`static/js/myscene.js`:**

```javascript
'use strict';
const socket = io({ transports: ['websocket'] });
socket.on('connect',    ()  => console.log('connected'));
socket.on('disconnect', ()  => console.log('disconnected'));
socket.on('reply',      (d) => console.log('reply:', d));
function sendMessage(text) { socket.emit('user_message', { message: text }); }
```

---

### 6.2 New Multi-Agent Scene (with AgentLoop)

Add the following to your scene's `__init__` and lifecycle:

```python
from engine.agents.agent_loop import AgentLoop
from engine.spatial.scene_map import SceneMap
from engine.spatial.location import Location

# __init__:
self.scene_map = SceneMap()
bed   = Location(id="bed",   name="Bed",   capacity=2,
                 interactions=["lie down", "cuddle"],
                 properties={"privacy": 0.9, "spiciness": 4})
couch = Location(id="couch", name="Couch", capacity=3,
                 interactions=["sit", "talk"],
                 properties={"privacy": 0.5, "spiciness": 1})
self.scene_map.add_location(bed)
self.scene_map.add_location(couch)
self.agent_loop = AgentLoop(
    scene_map=self.scene_map, db=self.db,
    socketio=self.socketio, scene_id=self.scene_id,
)
self.agent_loop.set_action_callback(self._on_agent_action)

# start():
self.agent_loop.start(interval=30.0)

# stop():
self.agent_loop.stop()

# Action callback — wire up BOTH agent_action AND chat_message:
def _on_agent_action(self, character_id: str, action: dict) -> None:
    self.socketio.emit("agent_action", action)
    if action.get("action") == "speak" and action.get("message"):
        char = self.characters.get(character_id)
        self.socketio.emit("chat_message", {
            "name":         char.name if char else character_id,
            "message":      action["message"],
            "character_id": character_id,
            "timestamp":    action.get("timestamp", ""),
        })
    self.socketio.emit("scene_state", self._build_state())
```

---

### 6.3 New Skill

```python
# engine/skills/builtin/my_skills.py
from __future__ import annotations
from engine.skills.skill import skill
from engine.skills.chain_context import get_chain_context


@skill(
    name="do_something",
    pack="my_pack",
    description="Does something useful. Returns a human-readable result string.",
    tags=["utility"],
)
def do_something(input_text: str, intensity: float = 0.5) -> str:
    """
    Perform an operation on the input.

    Args:
        input_text:  The text to process.
        intensity:   How strongly to apply the effect (0.0–1.0).

    Returns:
        Human-readable description of what happened.
    """
    ctx = get_chain_context()  # may be empty outside agent context
    # ... do the work ...
    return f"Processed '{input_text}' at {intensity:.0%} intensity."
```

---

### 6.4 New Interceptor

```python
from engine.mcp.comms_framework import InterceptorBase, ResponseContext


class MyInterceptor(InterceptorBase):
    """Injects a custom instruction into the system prompt."""
    name     = "my_interceptor"
    priority = 60  # after BedroomScene(15), before ResponseShaper(80)

    def pre_call(self, ctx: ResponseContext) -> None:
        ctx["system_prompt"] = (ctx.get("system_prompt", "") +
                                "\n\nExtra instruction added here.")

    def post_call(self, ctx: ResponseContext) -> None:
        reply = ctx.get("reply", "")
        if reply:
            ctx["reply"] = reply.strip()


# Register on your governor:
# gov.pipeline.add(MyInterceptor())
```

---

### 6.5 New MCP Tool

```python
# In engine/mcp/cosysim_server.py
from engine.mcp.cosysim_server import mcp  # FastMCP instance

@mcp.tool()
def get_scene_weather(scene_id: str) -> str:
    """Return the current atmosphere for a scene. Called by LMStudio agents."""
    return f"The {scene_id} feels warm and intimate tonight."
```

---

### 6.6 New Character

```python
from content.simulation.character_system.character import Character

char = Character(
    id="char-001",
    name="Aria",
    age=24,
    personality_id="warm_playful",
    tags=["romantic", "curious"],
    metadata={"voice": "warm_female", "hair": "dark_wavy"},
)
db.create_character(char.to_dict())
```

---

### 6.7 Test File

```python
# tests/test_myscene.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_character.return_value = {"id": "char-001", "name": "Aria", "mood": "happy"}
    return db


@pytest.fixture
def scene(mock_db):
    from content.scenes.myscene.myscene_scene import MyScene
    with patch("engine.lmstudio.client_v2.get_lmstudio_client"):
        s = MyScene()
        s.db = mock_db
        return s


class TestMyScene:

    def test_health(self, scene):
        client = scene.app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_plugin_info(self, scene):
        info = scene.get_plugin_info()
        assert "name" in info
        assert "scene_id" in info
        assert "port" in info

    def test_empty_message_ignored(self, scene):
        with scene.app.test_request_context():
            scene._handle_user_message({"message": ""})  # should not raise
```

---

## 7. Skill System — Deep Dive

### The Full `@skill` Decorator

```python
@skill(
    name="skill_registry_key",    # default: function name
    pack="pack_name",             # group for get_pack_tools("pack_name")
    description="...",            # default: first docstring line
    tags=["tag1", "tag2"],        # for SKILL_REGISTRY.all_tools(tags=["tag1"])
)
def my_skill(param: str, optional: int = 5) -> str:
    ...
```

### Type Annotations Are the JSON Schema

| Python | JSON Schema | Notes |
|--------|-------------|-------|
| `str` | `string` | |
| `int` | `integer` | |
| `float` | `number` | |
| `bool` | `boolean` | |
| `List[str]` | `array` of `string` | |
| `Optional[str]` | `string`, nullable | Use `= None` as default |
| `Literal["a","b"]` | `enum` | Restricts choices |

Always annotate every parameter AND the return type. Missing annotations = broken tool calls.

### Skill Trigger Types

| Trigger | When | Effect |
|---------|------|--------|
| `auto` | Before every LLM call | Result injected into context automatically |
| `optional` | Always available | LLM decides whether to call it |
| `required` | Every LLM call | LLM is prompted it MUST call this |

Configure in `config/skill_manifests.yaml`:

```yaml
scenes:
  myscene:
    - name: search_memory
      trigger: auto
      description: "Recall relevant memories before replying"
    - name: adjust_relationship
      trigger: optional
      description: "Update relationship metrics when significant things happen"
```

### Testing Skills Directly

```python
# Skills are just Python functions — test without LLM
from engine.skills.builtin.memory_skills import search_memory
from engine.skills.chain_context import set_chain_context

set_chain_context("test-chain", "test")
result = search_memory("birthday plans", character_id="char-001", top_k=3)
assert "Found" in result
```

### Built-in Pack Summary

| Pack | Skills | Purpose |
|------|--------|---------|
| `memory` | `search_memory`, `store_memory`, `get_event_chain_summary`, `summarize_chain` | RAG + EventChain |
| `character` | `get_character_state`, `adjust_trait`, `set_mood`, `adjust_relationship` | State management |
| `comfyui` | `generate_image`, `generate_character_portrait`, `list_comfyui_workflows` | Image generation |
| `voice` | `generate_voice_message`, `list_voice_messages` | TTS audio |

---

## 8. Agent Loop — How Autonomous Agents Work

### The Full Tick Cycle

```
timer fires every N seconds
  │
  ├─ shuffle character order (prevent same-agent-first-mover advantage)
  │
  └─ for each character:
       │
       ├─ _perceive()
       │   ├─ location context (SceneMap.context_for_character)
       │   ├─ nearby characters (name, mood, arousal)
       │   ├─ recent conversation log (last 10 shared_log entries)
       │   ├─ available locations list
       │   ├─ location mood hints (bed → intimacy, balcony → freedom, etc.)
       │   └─ JSON instruction: {"action", "target", "message"}
       │
       ├─ _decide()  ← MUST use skip_gov=True
       │   ├─ try: agent.reply(ctx, skip_gov=True, use_tools=False)
       │   ├─ try: agent.quick_query(...)            [fallback 1]
       │   └─ try: client_v2.chat(...)               [fallback 2]
       │       └─ _random_action()                   [last resort]
       │
       ├─ _execute()
       │   ├─ "move"     → SceneMap.move_character()
       │   ├─ "speak"    → append to shared_log, emit socket event
       │   ├─ "flirt/touch/kiss/cuddle/intimate" → adjust_arousal, log
       │   ├─ "interact" → log activity at current location
       │   └─ "idle"     → random flavour description
       │
       ├─ _log_action()  → EventChain "autonomous_trigger"
       ├─ on_action callback → scene UI updates
       └─ ActivityBus.publish() → admin panel visibility
```

### Registering Characters

```python
from engine.agents.character_agent import CharacterAgent
from engine.mcp.comms_framework import get_governor

agent = CharacterAgent(char, db=db, llm_url=llm_url)
gov   = get_governor(agent, scene="bedroom")   # wrap for conversation

loop.register_character(char, agent=gov)
```

> **Why pass the governor?** For conversational replies (user talks to character),
> the full pipeline runs. For action decisions in `_decide()`, `skip_gov=True`
> bypasses it. Same wrapped agent, two clean code paths.

### Tuning the Tick Rate

```python
loop.start(interval=15.0)   # aggressive — agents act every 15s
loop.start(interval=30.0)   # default
loop.start(interval=60.0)   # relaxed — agents act every 60s
```

---

## 9. The AgentGovernor & Interceptor Pipeline

### Pipeline Diagram

```
gov.reply("Hey!")
    │
    ├─ 1. Build ResponseContext
    │
    ├─ 2. PRE interceptors (ascending priority):
    │      BedroomSceneInterceptor     priority=15   inject persona
    │      SkillInjectorInterceptor    priority=20   run auto-skills
    │      PolicyInterceptor           priority=30   enforce policy
    │      PersonalityGuardInterceptor priority=50   enforce character voice
    │      ResponseShaperInterceptor   priority=80   shape natural output
    │
    ├─ 3. CharacterAgent.reply() — actual LLM call
    │
    ├─ 4. POST interceptors — LoggingInterceptor, etc.
    │
    └─ 5. Return ctx["reply"]
```

### When to Use Full Pipeline vs. skip_gov

```python
# Conversation (user talks to character) — full pipeline
reply = gov.reply("How are you feeling?")

# JSON action query (agent loop) — ALWAYS skip_gov
decision = gov.reply(
    perception_context,
    history=[{"role": "system", "content": json_system_prompt}],
    use_tools=False,
    skip_gov=True,
)
```

### Priority Reference

| Range | Runs | Use for |
|-------|------|---------|
| 10–20 | Very early | Scene setup, initial context injection |
| 20–40 | Early | Skill injection, context enrichment |
| 40–60 | Middle | Personality, policy enforcement |
| 60–80 | Late | Output shaping, format enforcement |
| 80–100 | Very late | Logging, post-processing |

### ResponseContext Keys

| Key | Type | Description |
|-----|------|-------------|
| `system_prompt` | `str` | Modify pre-call to change system prompt |
| `user_message` | `str` | The user's message |
| `messages` | `list` | Full message list sent to LLM |
| `reply` | `str` | LLM reply (modify post-call) |
| `scene` | `str` | Current scene name |
| `agent_id` | `str` | Character ID |
| `skill_manifest` | `SceneManifest` | Available skills |
| `policy` | `InteractionPolicy` | Interaction constraints |
| `abort` | `bool` | Set True to stop pipeline |
| `skip_llm` | `bool` | Set True to bypass LLM (interceptor provides reply) |
| `auto_results` | `dict` | Results from auto-triggered skills |

---

## 10. EventChain — The Ground Truth

```python
from content.simulation.database.events import EventChain

ec = EventChain(db)

# Start chain
chain_id = ec.start_chain(scene_id="bedroom", character_id="char-001",
                           summary="User initiated conversation")

# Log events
e1 = ec.log(event_type="message_in", actor="user",
            payload={"text": "Hey..."}, chain_id=chain_id,
            scene_id="bedroom", character_id="char-001")

e2 = ec.log(event_type="llm_request", actor="character_agent",
            payload={"tokens": 512}, chain_id=chain_id, parent_id=e1,
            scene_id="bedroom", character_id="char-001")

# Get full chain tree
tree = ec.get_chain(chain_id)

# List recent chains
chains = ec.list_chains(scene_id="bedroom", limit=20)
```

---

## 11. Spatial System

```python
from engine.spatial.scene_map import SceneMap
from engine.spatial.location import Location

sm = SceneMap()
sm.add_location(Location(
    id="bed", name="Bed", capacity=2,
    interactions=["lie down", "cuddle", "sleep"],
    properties={"privacy": 0.9, "spiciness": 4, "capacity": 2},
))

# Placing and moving characters
sm.place_character("char-001", "couch")
sm.move_character("char-001", "bed")           # returns bool (False if full)
loc    = sm.get_character_location("char-001") # Location | None
nearby = sm.get_nearby_characters("char-001")  # [char_id, ...]
sm.remove_character("char-001")

# Perception context string (fed directly into _perceive)
ctx = sm.context_for_character("char-001", names={"char-001": "Aria"})
```

**Location `properties` keys and their effects on _perceive:**

| Property | Range | Effect |
|----------|-------|--------|
| `privacy` | 0–1 | >0.7: "intimate actions feel natural"; <0.3: "bold actions take courage" |
| `spiciness` | 0–5 | >=4: "sensual and inviting"; >=2: "subtle romantic tension" |
| `capacity` | int | Enforced by `move_character()` |

---

## 12. Scene Frontend Patterns (Three.js + SocketIO)

### Socket Event Contract

| Direction | Event | Payload | Purpose |
|-----------|-------|---------|---------|
| server → client | `scene_state` | `{characters, locations}` | Full state sync — move avatars |
| server → client | `agent_action` | `{character_id, action, message, description, timestamp}` | Activity feed |
| server → client | `chat_message` | `{name, message, character_id, timestamp}` | Chat panel |
| server → client | `agent_tick` | `{tick, actions, timestamp}` | Tick heartbeat |
| client → server | `user_message` | `{message}` | User speaks |

### Avatar Sprite Pattern

```javascript
// Always include bubble: null — required for speech bubble cleanup
charSprites[charId] = {
    group:      new THREE.Group(),
    ring:       ringMesh,
    targetPos:  new THREE.Vector3(0, 0, 0),
    currentPos: new THREE.Vector3(0, 0, 0),
    bubble:     null,   // active speech bubble sprite or null
};

// animate() — lerp avatars to target positions smoothly
function animate() {
    requestAnimationFrame(animate);
    for (const [id, s] of Object.entries(charSprites)) {
        s.group.position.lerp(s.targetPos, 0.05);
    }
    renderer.render(scene, camera);
}
```

### Speech Bubble Pattern

```javascript
function showSpeechBubble(charId, text, durationMs) {
    const s = charSprites[charId];
    if (!s) return;
    // Remove existing bubble — ALWAYS dispose textures (VRAM leak if not)
    if (s.bubble) {
        s.group.remove(s.bubble);
        s.bubble.material.map.dispose();   // ← REQUIRED
        s.bubble.material.dispose();       // ← REQUIRED
        s.bubble = null;
    }
    const sprite = makeBubbleSprite(text);
    sprite.position.y = 2.85;   // above name label at y=2.2
    s.group.add(sprite);
    s.bubble = sprite;
    setTimeout(() => {
        if (s && s.bubble === sprite) {
            s.group.remove(sprite);
            sprite.material.map.dispose();
            sprite.material.dispose();
            s.bubble = null;
        }
    }, durationMs || 5000);
}

// Hook to socket
socket.on('agent_action', (data) => {
    addFeedEntry(data);
    if (data.action === 'speak' && data.message && data.character_id) {
        showSpeechBubble(data.character_id, data.message, 5000);
    }
});
```

> **GPU resource law:** Every `THREE.CanvasTexture` and `SpriteMaterial` you create
> is VRAM. On an RTX 2060 12GB, forgetting to `.dispose()` adds up fast in long sessions.
> Always dispose when removing any sprite, mesh, or material.

### Socket Reconnection

```javascript
socket.on('disconnect', () => updateStatus('Reconnecting...'));
socket.on('connect',    () => {
    updateStatus('Connected');
    socket.emit('request_state');   // re-sync on reconnect
});
```

---

## 13. Config System

```yaml
# config/default.yaml
scenes:
  myscene:
    port: 5557
    title: "My Scene"

services:
  lmstudio:
    host: localhost
    port: 1234
    base_url: "http://localhost:1234/v1"
  comfyui:
    host: localhost
    port: 8188

media:
  selfie:    { width: 512, height: 768 }
  video:     { width: 640, height: 480 }

logging:
  level: "INFO"
  max_entries: 5000
```

**Reading:**

```python
from engine.config import get_config
cfg  = get_config()
port = cfg.get("scenes.myscene.port", 5557)
url  = cfg.get("services.lmstudio.base_url", "http://localhost:1234/v1")
```

**Environment override** (double-underscore = dot):

```
COSYSIM_SCENES__MYSCENE__PORT=6000
COSYSIM_SERVICES__LMSTUDIO__HOST=192.168.1.5
```

---

## 14. Logging, Benchmarking & Monitoring

### Setup

```python
from engine.logging import install_logger, timed, get_system_monitor, get_benchmarks
install_logger(level="DEBUG", max_entries=5000)   # call once at app startup
```

### @timed

```python
from engine.logging import timed

@timed("lmstudio_chat")
def call_llm(prompt: str) -> str: ...

# Read stats
stats = get_benchmarks()
# {"lmstudio_chat": {"count": 42, "avg_ms": 340, "p95_ms": 520, ...}}
```

### Log Levels

| Level | Use for |
|-------|---------|
| `DEBUG` | Per-tick decisions, socket events, internal state |
| `INFO` | Scene start/stop, character spawn, significant state |
| `WARNING` | Non-fatal failures with fallback |
| `ERROR` | Fatal or user-visible failures |

### System Monitor

```python
snap = get_system_monitor().snapshot()
# {"cpu_percent": 23, "ram_used_mb": 4096, "gpu": {"vram_used_mb": 8200}, ...}
```

---

## 15. Testing Best Practices

```powershell
# Run all tests
python -m pytest tests/ -v --tb=short

# One file
python -m pytest tests/test_agent_loop.py -v

# One test
python -m pytest tests/test_agent_loop.py::TestAgentLoop::test_decide_uses_skip_gov -v
```

### Always Mock LLM Calls

```python
@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    from engine.lmstudio import client_v2
    mock = MagicMock()
    mock.chat.return_value = MagicMock(content='{"action":"speak","message":"Hi"}')
    monkeypatch.setattr(client_v2, "get_lmstudio_client", lambda: mock)
```

### Testing That skip_gov Is Passed (Critical)

```python
def test_decide_uses_skip_gov():
    """If this test fails, agents will idle forever in production."""
    loop = AgentLoop(scene_map=SceneMap(), scene_id="test")
    mock_agent = MagicMock()
    mock_agent.reply.return_value = '{"action": "move", "target": "bed", "message": ""}'
    loop._agents["c1"] = mock_agent
    loop._perceive = MagicMock(return_value="ctx")

    loop._decide("c1", "ctx")

    kwargs = mock_agent.reply.call_args.kwargs
    assert kwargs.get("skip_gov") is True, \
        "skip_gov=True MUST be passed — governor rewrites prompt and agents idle without it"
```

### Testing EventChain

```python
def test_action_logs_to_eventchain(db):
    ec = EventChain(db)
    # ... trigger an action ...
    chains = ec.list_chains(scene_id="bedroom", limit=1)
    assert chains
    events = ec.get_chain(chains[0]["chain_id"])
    assert any(e["event_type"] == "autonomous_trigger" for e in events)
```

---

## 16. What the System Can Do

### Conversational Agents with Memory

Characters hold conversations with real RAG-backed memory. They remember past
interactions, have personality traits, and responses are shaped per-scene by
interceptors — without any changes to `CharacterAgent`.

```
User: "Do you remember what we talked about last night?"
Agent: [auto-skill: search_memory("last night")]
       [3 memories injected into context]
       "Of course... you told me about your sister. Is everything okay with her?"
```

### Autonomous Multi-Agent Scenes

Without user input, multiple agents move around a 3D space, speak to each other,
flirt, interact with locations, and escalate based on mood and arousal — all driven
by tick-based LLM decisions. No scripted behaviour.

### Real-Time 3D Rendering

Three.js avatars lerp smoothly to new positions. Speech bubbles float above avatars
when they speak. Glow rings pulse at their feet. All driven by SocketIO state pushes
from Python. The 3D scene and the agent AI are fully decoupled — the frontend is
pure presentation.

### Media Generation Pipeline

ComfyUI generates selfies, portraits, and video on demand. The 5-tier `PromptBuilder`
escalates from safe to explicit based on scene context and character state.
`MediaConfig` enforces standard dimensions across all generated content.

### Voice Messages

Qwen3-TTS generates character-voiced WAV files. Each character has a `VoiceDesign`
(pitch, speed, emotion, voice preset). Messages are served over HTTP and playable
directly in the browser.

### MCP Tool Calling (Bidirectional)

LMStudio can call back into CosySim via FastMCP:
- `search_memory` — query character memories
- `store_memory` — write new memories
- `adjust_relationship` — change relationship metrics
- `get_character_state` — read mood, energy, arousal
- `get_scene_info` — read current scene state
- And 4 more...

CosySim reads LMStudio as a REST service for inference. LMStudio reads CosySim
via MCP for data and tools. **True bidirectional integration.**

### Admin Panel (13 Pages)

Full diagnostic and management centre:
- Real-time service health strip
- EventChain browser (tree view, parent linking)
- KPI dashboard (4 tabs: ops, LLM latency, system resources, chain analytics)
- Log viewer with benchmark charts
- Config editor (type-aware, changes persist to YAML)
- RAG message editor with guards
- God Mode (raw SQL, force operations — danger zone)
- Character manager, scene manager, media browser, backup tools

### ActivityBus

Every agent action, every scene event, every tick is published to a cross-scene
ActivityBus. Admin panel subscribes live. Any service can subscribe for event-driven
reactions across scenes.

---

## 17. Pitfalls & Things to Watch Out For

### P1 — The Governor Trap (Agents Always Idle)

**Symptom:** Agents spawn, LLM output is visible, avatars don't move.  
**Cause:** `agent.reply()` on a governor without `skip_gov=True`.  
**Fix:** Always pass `skip_gov=True` for structured/JSON queries.

```python
# WRONG — agents idle forever
response = gov.reply(context)

# CORRECT
response = gov.reply(context, use_tools=False, skip_gov=True)
```

---

### P2 — Agent Speech Not Appearing in Chat

**Symptom:** Speak actions in activity feed, but nothing in chat panel.  
**Cause:** `agent_action` triggers `addFeedEntry()` only, not chat rendering.  
**Fix:** Emit `chat_message` separately in `_on_agent_action()`.

---

### P3 — Three.js VRAM Leak

**Symptom:** GPU memory climbs continuously.  
**Cause:** Sprites removed without disposing textures/materials.  
**Fix:** Always: `sprite.material.map.dispose(); sprite.material.dispose();`

---

### P4 — Thread-Local Chain Context Lost

**Symptom:** Skills log `chain_id = None`.  
**Cause:** `get_chain_context()` returns nothing in different threads.  
**Fix:** Pass `chain_id` explicitly when crossing thread boundaries.

---

### P5 — Shared List Grows Without Bound

**Symptom:** Memory grows continuously over long sessions.  
**Fix:** Always cap after append: `self.my_list = self.my_list[-MAX_ITEMS:]`

---

### P6 — Silent `except` Blocks

**Symptom:** Feature silently does nothing. Impossible to debug.  
**Fix:** `except Exception as exc: logger.debug("failed: %s", exc)`

---

### P7 — None Safety on `.strip()`

**Symptom:** `AttributeError: 'NoneType' object has no attribute 'strip'`  
**Fix:** `text = (response.content or "").strip()`

---

### P8 — Hardcoded Ports / URLs

**Fix:** `port = get_config().get("scenes.bedroom.port", 5556)`

---

### P9 — Missing `use_tools=False` in Action Queries

**Symptom:** Agent loop stalls while LLM tries to call memory skills.  
**Fix:** Pass `use_tools=False` alongside `skip_gov=True`.

---

### P10 — `engine/` imports from `content/`

**Symptom:** Circular imports, test isolation failures.  
**Fix:** Engine never imports content. One-way only.

---

### P11 — Not Running Tests After Changes

**Fix:** `python -m pytest tests/ -q --tb=short` after every non-trivial change.

---

## 18. Lessons Learned — The Good, the Bad, the Ugly

### The Good 🎉

**The interceptor pipeline is elegant when used right.**
Stacking interceptors by scene — `BedroomSceneInterceptor` for intimacy context,
`PersonalityGuardInterceptor` for character voice — without touching `CharacterAgent`
is genuinely powerful. New scenes get new behaviour just by adding an interceptor.

**The EventChain is worth every line of code.**
Being able to pull the full causal tree for any interaction during debugging —
"show me every event in this conversation, in order, with parents" — makes complex
multi-agent debugging tractable. Without this, autonomous agent bugs are invisible.

**The spatial system makes agents feel alive.**
When an agent "decides" to move to the bed because the perception context says
`"Soft pillows and warm sheets invite closeness"` — and then another agent follows
and things escalate naturally — it feels like the characters are genuinely sentient.
Location mood hints are a small touch with outsized impact on perceived agent intelligence.

**`skip_gov=True` is perfect separation of concerns.**
The same wrapped agent serves two completely different use cases:
full conversational pipeline for user dialogue, raw output for action decisions.
Clean, no duplication, and once you know about it — obvious.

**Speech bubbles — immediate visual payoff.**
The difference between silent frozen avatars and visibly speaking characters with
floating text is the entire feeling of the scene. One `showSpeechBubble()` function
transforms the experience.

**ChromaDB RAG memory is seamless.**
A character saying "remember when you told me X three days ago?" with no special
prompting — just `search_memory` as an auto-triggered skill — makes the character
feel genuinely continuous. Works reliably with minimal maintenance.

---

### The Bad 😤

**The Governor Trap cost hours.**
Everything looked right. LLM was producing output. The JSON prompt was being sent.
`_parse_decision()` was being called. Every agent idled every tick. The cause —
interceptors silently rewriting the system prompt — was invisible because idle
is a valid return value. Lesson: always trace the *actual* message list the LLM
receives, not the one you think you sent. Add logs temporarily if needed.

**Silent `except` blocks are debugging poison.**
Multiple times a feature "didn't work" and the cause was a swallowed exception.
The rule now: never `except Exception: pass` without a `logger.debug(exc)`.

**Three.js VRAM leak from Canvas textures.**
Speech bubbles were created and removed without disposing textures. On a long
session GPU memory climbed noticeably. `.material.map.dispose()` + `.material.dispose()`
is now in every sprite lifecycle template.

**Circular imports between engine/ and content/.**
Early in development some engine modules imported from content/simulation/.
Subtle import-order issues only manifested in tests. Untangling it took a full
session. One-way dependency is now a non-negotiable rule.

---

### The Ugly 😬

**The "it works in my terminal" port collision.**
One scene already bound to 5556, another trying to start on the same port.
Now: `launcher.py --status` checks all ports before starting, and every scene
has a `/health` route that can be poked independently.

**The `NoneType has no attribute 'rstrip'` cascade.**
When an LLM returns None (rare — timeouts, context overflow), any code that
calls `.strip()` without a guard throws. In a scene with multiple agents all
calling the LLM simultaneously, this can take down the whole tick. Lesson:
every LLM response is guarded: `(response or "").strip()`.

**Database migrations the hard way.**
Adding a new column to a SQLite table with existing data. ALTER TABLE ADD
COLUMN with defaults was fine, but forgetting to handle the migration in
existing test fixtures caused cascading failures. Now: always add columns
with safe defaults, always test against existing fixture data, see `MIGRATION.md`.

---

## 19. Common Workflows with Copilot

### Debugging Agent Behaviour

```
Agents in the [scene] are [symptom].
Trace through: what system prompt actually reaches the LLM, what the raw
LLM output looks like before _parse_decision, and whether skip_gov=True
is being passed in _decide(). Show me file + line for each step.
```

### Adding a New Scene

```
Create a new scene called '[name]' following the pattern in
content/scenes/bedroom/. Port: [N]. Characters: [list].
Add to launcher.py. Register the health route.
Write tests mirroring the test_integration.py pattern.
Make sure all LLM calls go through CharacterAgent, not direct HTTP.
```

### Adding a New Skill Pack

```
Create a skill pack called '[pack]' in engine/skills/builtin/[pack]_skills.py.
Follow the pattern of memory_skills.py exactly.
Skills needed: [list with descriptions and param types].
Each skill must: use get_chain_context(), log to EventChain (skill_called/result),
return a str, have full type annotations on every param + return.
Register in engine/skills/__init__.py. Write tests.
```

### Tracing a Feature End-to-End

```
Trace the complete flow from user message arriving at the phone scene
socket handler to the LLM response being emitted back.
Show every function call in order with file:line.
```

### Pre-Commit Audit

```
Audit these changed files before I commit:
- Silent except blocks without log lines
- .strip()/.rstrip() on potentially None values
- Hardcoded ports or URLs (should use get_config())
- New lists appended to without a max-cap
- Any LLM query needing structured output — does it pass skip_gov=True?
- New socket events — are both emit() and on() implemented?
- New DB queries — are they parameterised (no string formatting)?
```

### Debugging a Chain Issue

```
EventChain isn't recording [feature]. Trace the flow from
[entry_point] through to the DB insert and find where the chain
breaks. Show me what chain_id value is at each step.
```

---

## 20. Quick Reference

### Scene Ports

| Scene | Port | Launch |
|-------|------|--------|
| Hub | 8500 | `python launcher.py --mode hub` |
| Dashboard | 8501 | `python launcher.py --mode dashboard` |
| Admin | 8502 | `python launcher.py --mode admin` |
| Phone | 5555 | `python launcher.py --mode phone` |
| Bedroom | 5556 | `python launcher.py --mode bedroom` |
| TTS | 8600 | `python launcher.py --mode tts` |

### Key Files

| What | File |
|------|------|
| Agent loop | `engine/agents/agent_loop.py` |
| Character agent | `engine/agents/character_agent.py` |
| Governor + pipeline | `engine/mcp/comms_framework.py` |
| EventChain | `content/simulation/database/events.py` |
| Database CRUD | `content/simulation/database/db.py` |
| RAG memory | `content/simulation/database/rag.py` |
| Skill registry | `engine/skills/registry.py` |
| Chain context | `engine/skills/chain_context.py` |
| Config | `engine/config.py` |
| BaseScene | `engine/scenes/base_scene.py` |
| SceneMap | `engine/spatial/scene_map.py` |
| LMStudio REST | `engine/lmstudio/client_v2.py` |
| Benchmarks | `engine/logging/benchmark.py` |
| Bedroom scene (Python) | `content/scenes/bedroom/bedroom_scene.py` |
| Bedroom scene (JS) | `content/scenes/bedroom/static/js/bedroom.js` |
| Phone scene | `content/scenes/phone/phone_scene.py` |

### Valid Agent Actions

```python
VALID_ACTIONS = frozenset([
    "speak",     # say something (message field)
    "move",      # go to location (target = location name)
    "interact",  # activity at current location
    "idle",      # do nothing
    "flirt",     # flirtatious interaction with nearby character
    "touch",     # gentle physical contact
    "kiss",      # escalation
    "cuddle",    # closeness
    "intimate",  # highest escalation
])
```

### Governor Pipeline Priority Reference

| Priority | Interceptor | Effect |
|----------|-------------|--------|
| 15 | `BedroomSceneInterceptor` | Injects scene persona |
| 20 | `SkillInjectorInterceptor` | Runs auto-skills, injects results |
| 30 | `PolicyInterceptor` | Enforces token limits, forbidden topics |
| 50 | `PersonalityGuardInterceptor` | Enforces character voice |
| 80 | `ResponseShaperInterceptor` | Shapes natural output |
| 90+ | Logging interceptors | EventChain, metrics |

> This pipeline = for conversation. For JSON output = `skip_gov=True`.

### One-Liners

```python
# Config
from engine.config import get_config; get_config().get("scenes.bedroom.port", 5556)

# Start EventChain
from content.simulation.database.events import EventChain
chain_id = EventChain(db).start_chain(scene_id="x", character_id="y", summary="z")

# Direct LLM call (no agent, no governance)
from engine.lmstudio.client_v2 import get_lmstudio_client
r = get_lmstudio_client().chat([{"role": "user", "content": "Hello"}])

# Governor with skip_gov (structured query)
from engine.mcp.comms_framework import get_governor
reply = get_governor(agent, scene="bedroom").reply("ctx", skip_gov=True, use_tools=False)

# Search memories
from engine.skills.builtin.memory_skills import search_memory
result = search_memory("beach trip", character_id="char-001")

# Run tests
python -m pytest tests/ -q --tb=short
```

---

*Last updated: 2026-02-21 — after the great bedroom agent silence.*
*Major lessons: The Governor Trap, VRAM leaks, thread-local chain context, uncapped lists.*
*Current state: agents move, speak, flirt, and kiss of their own free will.*
*Speech bubbles float. The good times are real. GodSpeed.*
