# CosySim — Complete System Context

> v1.53.0 [2026-03-26] — Everything an agent needs to understand and work with CosySim.
>
> Read this file to gain full context on architecture, conventions, systems, tools,
> protocols, and workflows. After reading, you should be able to modify any part of
> the system confidently.

---

## 1. What CosySim Is

CosySim is a **local-first multi-scene AI simulation framework**. 35 launch targets (18 game scenes, 11 services, 6 creation tools) run as Flask/Socket.IO servers on localhost. AI characters are LLM-powered agents governed by a 30-interceptor pipeline, ~1,040 skills across 99 packs, and a persistent knowledge layer (Nexus KMS). Local inference via LMStudio — no cloud dependency for core gameplay.

**Design Principles:**
- **Engine is reusable framework. Content is swappable. Config tunes without code.**
- **Nexus-first.** If the answer exists in Nexus, use it. Found it elsewhere? Write it back.
- **Local inference.** LMStudio provides all LLM calls.
- **Three pillars.** Game, Service, and Creation targets are independently launchable.

---

## 2. Three-Pillar Architecture

All targets defined in `engine/control_plane_registry.py`, ports in `engine/port_registry.py`.

```
┌─ GAME (18) ────────────────────────────────────────────────┐
│ phone:5555 · penthouse:5556 · lounge:5557 · tavern:5558    │
│ casino:5559 · gallery:5560 · arena:5561 · realm:5562       │
│ neoncity:5563 · coders:5564 · heist:5565 · games:5567      │
│ grid:5569 · lab_break:5571 · oracle:5572 · neonos:5593     │
│ cyberspace:5573 · auction:5574                              │
├─ SERVICE (11) ──────────────────────────────────────────────┤
│ nexus_kms:8700 · hub:8500 · nexus_panel:5570 · bridge:8601 │
│ nlm_proxy:8800 · system_control:5575 · command_center:5566  │
│ intel_hub:5580 · dashboard:8501 · admin:8502 · tts:8600     │
├─ CREATION (6) ──────────────────────────────────────────────┤
│ canvas:5590 · canvas_api:5595 · assets:8503 · creator:8504  │
│ asset_studio:5568 · creation_kit:5592                       │
└─────────────────────────────────────────────────────────────┘

External (manual start):
  LMStudio:1234 · ComfyUI:8188 (optional)
```

---

## 3. How to Launch

```bash
python tui.py                     # Terminal UI (recommended)
python launcher.py penthouse      # Single scene → http://localhost:5556
python launcher.py --core         # Auto-start core services + scenes
python launcher.py --all          # Everything
python launcher.py --list         # Show targets with port status
```

**PowerShell scripts (alternative):**
```powershell
.\scripts\start_services.ps1 -NoCanvas   # Nexus + Hub (services first)
.\scripts\start_scenes.ps1 -Scene oracle # Then individual scenes
.\scripts\start_scenes.ps1               # Or all auto-start scenes
.\scripts\start_scenes.ps1 -List         # Show available scenes
```

**Start order:** Nexus KMS auto-starts first (priority 0, external type). LMStudio must be running manually on :1234.

**Known issue:** `Start-Process` launched Flask-SocketIO scenes may timeout on some Windows configs. Use `python launcher.py <scene>` in foreground or the TUI as workaround.

---

## 4. Core Engine Layer

### 4.1 LMStudio Wrapper (`engine/lmstudio/`)

**Primary API — `engine/lmstudio/chat.py`:**
```python
from engine.lmstudio.chat import chat, chat_response, chat_stream, is_ready

# Simple: returns string
reply = chat([{"role": "user", "content": "Hello"}], system="You are helpful.")

# Full: returns LMSResponse with latency_ms, token counts, response_id
resp = chat_response(messages, system="...", temperature=0.7, max_tokens=500)

# Stateful: KV cache persistence via response_id chaining
resp = chat_stateful("Follow-up question", previous_response_id=resp.response_id)

# Structured: JSON schema enforcement
resp = chat_structured(messages, schema={"type": "object", ...})

# Streaming: yields content chunks
for chunk in chat_stream(messages, system="..."):
    print(chunk, end="")

# Quick one-liner
reply = quick_reply("Summarize this in one sentence")
```

**Server Controller — `engine/lmstudio/server_controller.py`:**
```python
from engine.lmstudio.server_controller import get_server_controller

ctrl = get_server_controller()
health = ctrl.get_server_status()         # ServerHealth dataclass
ctrl.load_model("model-key", context_length=8192, gpu_offload=0.9)
ctrl.create_agent_instance("agent-1", "model-key")  # Isolated KV cache
ctrl.unload_model("model-key")
```

**Task Queue — `engine/lmstudio/task_queue.py`:**
```python
from engine.lmstudio.task_queue import get_task_queue, TaskType, TaskPriority

queue = get_task_queue()
task = queue.submit(TaskType.CHAT, prompt="Hello", priority=TaskPriority.HIGH)
result = queue.wait_for(task.id, timeout=60)
```

**LMLink Federation — `engine/lmstudio/lmlink_manager.py`:**
Multi-instance routing across multiple LMStudio servers. Strategies: `local_first`, `round_robin`, `least_loaded`, `capability_first`. Config in `config/lmlink.yaml`.

### 4.2 Configuration (`engine/config.py`)

```python
from engine.config import get_config

config = get_config()
port = config.get("scenes.penthouse.port", 5556)     # Dot-notation access
config.set("custom.key", "value")                      # Runtime override
```

**Config hierarchy:** `config/default.yaml` → `config/{environment}.yaml` → env vars.

**Key config sections:** `llm`, `lmstudio`, `scenes`, `database`, `tts`, `nexus`, `comfyui`, `mcp`, `characters`, `agent_profiles`, `hardware`, `media_standards`.

### 4.3 MCPFramework — State Tree (`engine/mcp/framework.py`)

```python
from engine.mcp.framework import get_framework

fw = get_framework()

# Scene nodes (auto-created on access)
scene = fw.get_scene("penthouse")
scene.update_state({"mood": "tense"})
scene.emit("custom_event", {"detail": "something happened"})

# Character nodes
char = fw.get_character("lola")
char.enter_scene("penthouse")
char.update_state({"mood": "flirty"})

# Cross-scene messaging
fw.cross_scene_send("lola", "penthouse", "viktor", "casino", "Meet me at midnight")

# Timers and consequences
fw.start_timer("bomb_timer", duration_secs=300, on_complete_note="BOOM")
fw.schedule_consequence("penthouse", "lola", "mood_shift", {"to": "angry"}, trigger_after_turns=3)

# Tick (advance turn, fire due consequences)
fired = fw.tick("penthouse")

# Events
fw.on("player_action", lambda e: print(e))
fw.emit_event("player_action", {"action": "opened_door"})
```

### 4.4 Skills System (`engine/skills/`)

```python
from engine.skills.skill import skill

@skill(
    pack="scene_name",
    description="LLM-facing description of what this does",
    category="GAME",       # COMMUNICATION|MEMORY|MEDIA|GAME|SOCIAL|ENVIRONMENT|SYSTEM|NARRATIVE
    cooldown=5.0,          # Seconds between uses
    cost=1.0,              # Budget cost
    tags=["combat", "action"],
    prerequisites=["other_skill"],
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief docstring for the LLM."""
    return "Result string shown to agent"
```

**Registry:** `SKILL_REGISTRY` in `engine/skills/registry.py`. Skills auto-register at import time via `@skill` decorator. ~1,040 skills across 99 packs. 8 categories.

**Governance:** `AgentGovernor` in `engine/mcp/comms_framework.py` filters the full registry to ~50-80 contextual skills per call based on scene, pack membership, cooldowns, and prerequisites.

### 4.5 Interceptor Pipeline (`engine/agents/interceptors/`)

28 interceptors run pre-call (before LLM) and post-call (after LLM) on every agent response.

```python
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

class MyInterceptor(InterceptorBase):
    name = "my_interceptor"
    priority = 50  # Lower = runs earlier

    def pre_call(self, ctx: ResponseContext) -> None:
        ctx["system_prompt"] += "\nExtra context here"

    def post_call(self, ctx: ResponseContext) -> None:
        reply = ctx.get("reply", "")
        # Modify reply, extract tags, sync state
```

**Priority order:**
```
Pri  5 → NaturalMoodDrift (neurochemistry)
Pri  6 → NexusPrompt (knowledge hydration)
Pri  7–12 → Identity, scene injection, routing, dialog
Pri 15 → NarrativeModInterceptor (stage context)
Pri 20–70 → Skills, games, guardrails, personality, policy
  Pri 40 → FactionContextInterceptor (faction standing injection)
Pri 71–93 → Response shaping, TTS, mood sync, relationships
  Pri 75 → HeatAwarenessInterceptor (wanted level awareness)
  Pri 92 → SpectatorBroadcastInterceptor (danmaku)
```

Register in `engine/agents/interceptors/__init__.py` `_REGISTRY` list.

### 4.6 Stream Tags (`engine/mcp/stream_processor.py`)

`StreamProcessor` extracts inline tags from LLM output:
```
[MOOD:happy]        → Mood change event
[IMAGE:cyberpunk city at night]  → Image generation trigger
[ACTION:leans against wall]      → Character action
[STAT:reputation+5]              → Stat modification
[VOICE:whisper]                  → TTS voice style change
```

Use `infer_processed()` for tag extraction, `infer_stream()` for raw streaming.

### 4.7 AgentGovernor Reply Flow

```
User message
  ↓
AgentGovernor.reply(user_message)
  ↓
1. Build ResponseContext (scene, agent, skills, policy, game state)
2. Execute AUTO skills → ctx["auto_results"]
3. PRE-CALL pipeline (ascending priority) — inject context
4. Call LMStudio (or skip if ctx["skip_llm"])
5. Parse response (ContentRouter)
6. POST-CALL pipeline — shape response, extract tags, sync mood
7. Return reply string
```

---

## 5. Knowledge Layer — Nexus KMS

### 5.1 Nexus Client (`engine/nexus/client.py`)

```python
from engine.nexus.client import get_nexus_client

nx = get_nexus_client()

# CRUD
entry_id = nx.add_entry("Title", "Content", content_type="knowledge", category="fact", tags=["tag1"])
entry = nx.get_entry(entry_id)
results = nx.search("query text", limit=10)

# Q&A (cached)
answer = nx.ask("What is the player's reputation?", depth="auto")

# NLM (NotebookLM)
answer = nx.nlm_ask("Explain the faction system", notebook_id="...")

# Session logging
nx.log_session(session_id="sess-1", project="CosySim", agent_id="claude")
```

### 5.2 Query Router — 6-Tier Pipeline (`engine/nexus/query_router.py`)

```python
from engine.nexus.query_router import get_query_router

router = get_query_router()
result = router.query("How does the economy work?")
# result.answer, result.source ("cache"|"vector"|"fts"|"nexus"|"nlm"|"llm"),
# result.confidence (0.0-1.0), result.tokens_saved
```

**Tiers:** Q&A Cache (0.90) → Vector Search (0.82) → FTS (0.75) → Nexus Ask → NLM → LLM Fallback (0.60). Each tier auto-stores results for future cache hits.

### 5.3 Embedding Service (`engine/nexus/embedding_service.py`)

```python
from engine.nexus.embedding_service import get_embedding_service

emb = get_embedding_service()
vector = emb.embed("text to embed", purpose="knowledge")
vectors = emb.embed_batch(["text1", "text2"])
score = emb.cosine_similarity(vec_a, vec_b)
```

**Providers:** Gemini Embedding 2 (primary, via AIStudio REST) → LMStudio (fallback, local). Circuit breaker per provider (5 transient failures → 300s cooldown).

### 5.4 Virtual Filesystem (`engine/nexus/filesystem.py`)

```python
from engine.nexus.filesystem import get_filesystem

fs = get_filesystem()
fs.write("/home/player/notes/todo.txt", "Buy milk\nFix generator")
content = fs.read("/home/player/notes/todo.txt")
entries = fs.list_dir("/home/player/")
fs.mkdir("/home/player/evidence/")
tree = fs.tree("/home/player/", max_depth=3)
```

Maps virtual paths to Nexus entries via `content_type="filesystem"` + path tags. Auto-seeds `/home/player/`, `/shared/`, `/system/`.

### 5.5 RAG Memory (`content/simulation/database/rag.py`)

```python
from content.simulation.database.rag import RAGMemory

rag = RAGMemory()
mem_id = rag.add_memory("lola", "Player likes whiskey", memory_type="preference", importance=0.8)
results = rag.query_memories("lola", "What does the player like?", n_results=5)
```

ChromaDB-backed vector store. Per-character memories with type, importance, emotion, chain_id.

### 5.6 Training Flywheel (`engine/nexus/training_flywheel.py`)

```python
from engine.nexus.training_flywheel import get_training_flywheel

fw = get_training_flywheel()
fw.collect_from_qa("question", "answer", source="nlm", confidence=0.8)
export_path = fw.export_jsonl(min_quality=0.7)  # JSONL for fine-tuning
```

Collects Q&A pairs, routing decisions, task results, and preferences → exports as JSONL/ShareGPT/DPO for fine-tuning.

---

## 6. Character & World Systems

### 6.1 Character Registry (`engine/mcp/character_registry.py`)

```python
from engine.mcp.character_registry import get_character_registry

reg = get_character_registry()
reg.register("lola", name="Lola", personality={"warmth": 0.9}, voice_style="playful")
profile = reg.get_profile("lola")
reg.set_state("lola", mood="happy", energy=90.0)
reg.assign_skill("lola", "flirt", skill_type="speech_enhance")
```

### 6.2 Character Creation Wizard (`engine/creation/character_wizard.py`)

6-stage pipeline: Archetype → Appearance → Voice → Stats → Story → Memory Seed.

```python
from engine.creation.character_wizard import get_character_wizard

wizard = get_character_wizard()
state = wizard.start("Aoi")
wizard.set_archetype(state.wizard_id, "trickster")
wizard.set_appearance(state.wizard_id, {"hair": "electric blue", "eyes": "gold"})
wizard.set_voice(state.wizard_id, "playful", "voice_aria")
wizard.set_stats(state.wizard_id, {"warmth": 0.6, "mystery": 0.8})
wizard.set_backstory(state.wizard_id, "A data thief from District 9...")
wizard.set_seed_memories(state.wizard_id, [
    {"content": "Stole from Axiom Corp CEO", "category": "event"},
])
char_id = wizard.finalize(state.wizard_id)  # Registers + seeds memories
```

**5 archetypes:** companion (warm), rival (competitive), mentor (wise), trickster (chaotic), guardian (protective).

### 6.3 Neurochemistry (`engine/characters/neurochemistry.py`)

6 neurotransmitters (dopamine, serotonin, oxytocin, cortisol, adrenaline, endorphins) with stimulus-response model and derived emotions. `NeurochemistryInterceptor` (priority 5) injects state into agent prompts.

```python
from engine.characters.neurochemistry import get_neurochemistry_manager

neuro = get_neurochemistry_manager()
neuro.apply_stimulus("lola", "received_compliment")  # ↑ dopamine, ↑ oxytocin
emotions = neuro.get_derived_emotions("lola")        # [("confident", 0.8), ("happy", 0.7)]
prompt_ctx = neuro.get_prompt_context("lola")         # Formatted for LLM
```

### 6.4 Player State & World Sim (`engine/world/`)

```python
from engine.world.player_state import get_player_state
from engine.world.world_sim import WorldSim

player = get_player_state()
player.earn_credits(500, "quest reward")
player.adjust_reputation(10)

# WorldSim runs as daemon thread — economy ticks, NPC actions, faction shifts
# Events: NPC_ACTION, FACTION_SHIFT, ECONOMY_TICK, WORLD_EVENT, HACKER_MESSAGE
```

---

## 7. Narrative System (`engine/mcp/narrative_mod.py`)

Stage-based storytelling with measurable targets. Agent prompts are dynamically injected with current stage context.

```python
from engine.mcp.narrative_mod import ModStage, ModTarget, get_narrative_engine

engine = get_narrative_engine()
mod = engine.start_mod("quest_1", "The Missing Merchant", stages=[
    ModStage(stage_id="act1", title="Investigation",
             prompt_injection="You are investigating the merchant's disappearance...",
             targets=[
                 ModTarget(target_id="search", description="Search the forest"),
                 ModTarget(target_id="ask", description="Ask at the tavern"),
             ]),
    ModStage(stage_id="act2", title="Resolution", ...),
])

engine.complete_target("quest_1", "search")  # Auto-advances when all targets done
injection = engine.get_prompt_injection("realm")  # Used by NarrativeModInterceptor
```

**Wired into:** Realm (quest branches), Lab Break (personality arcs).

---

## 8. Danmaku / Spectator System

### SpectatorBus (`engine/services/spectator_bus.py`)

```python
from engine.services.spectator_bus import get_spectator_bus, SpectatorMessage

bus = get_spectator_bus()
bus.broadcast(SpectatorMessage(kind="chat", text="Hello!", agent_id="lola", scene="penthouse", color="#4ade80"))
recent = bus.get_recent(limit=50)
token = bus.subscribe(lambda msg: print(msg.text))
```

`SpectatorBroadcastInterceptor` (priority 92) auto-broadcasts every agent reply. Frontend: `cosysim-danmaku.js` renders floating bullet comments, F7 toggle.

---

## 9. NeonOS Virtual Desktop (`content/scenes/neonos/`)

```bash
python launcher.py neonos  # → http://localhost:5593
```

Desktop shell rendering every CosySim scene as a draggable/resizable iframe window. `/api/apps` returns all targets with online/offline status. `cosysim-desktop.js` handles window management.

---

## 10. Signal Desktop App (`content/scenes/phone/`)

The Phone/Signal scene has a **Desktop Mode** with 4 tabs:

- **Messages** — DM + group chat threads (existing)
- **Email** — inbox from `/home/player/inbox/`, read/star/delete, unread badges
- **Files** — virtual filesystem browser with breadcrumbs and file viewer
- **Music** — playlist browser, song list, play/next/stop, now-playing bar

Backend: `content/scenes/phone/apps/email_app.py`, `files_app.py`, `music_app.py`
Routes: `/api/email/*`, `/api/files/*`, `/api/music/*` (11 routes)

Desktop mode activates via dock button → replaces home grid with tab bar.

---

## 11. Oracle Persistent Companion (`engine/agents/oracle_companion.py`)

A background agent that autonomously uses Signal, filesystem, and content skills:

```python
from engine.agents.oracle_companion import get_oracle_companion

companion = get_oracle_companion(socketio=scene.socketio)
companion.start()  # 5-min interval, weighted random actions
```

**5 actions** (weighted): diary (30%), Signal message (25%), observation (20%), playlist (15%), email (10%)

- Writes diary entries to `/home/oracle/journal/`
- Sends cryptic messages to player's phone
- Curates mood playlists (midnight_meditation, neon_pulse, etc.)
- Composes intel emails to player's inbox
- Writes field observations to `/home/oracle/notes/`

Auto-started when Oracle scene serves. Registered in CharacterRegistry with personality: mystery 0.99, curiosity 0.95, warmth 0.4.

---

## 12. Co-Op Heist Squad System (`engine/multiplayer/squad.py`)

Groups 2-4 players for shared heist objectives with role assignment and loot splitting.

```python
from engine.multiplayer.squad import get_squad_manager

mgr = get_squad_manager()
squad = mgr.create_squad("player_1", "Knack", scene="heist")
mgr.join_squad(squad.squad_id, "player_2", "Viktor")
mgr.set_role(squad.squad_id, "player_1", "hacker")
mgr.set_role(squad.squad_id, "player_2", "muscle")
mgr.set_ready(squad.squad_id, "player_1", True)
mgr.set_ready(squad.squad_id, "player_2", True)

heist_id = mgr.start_heist(squad.squad_id)  # All must be ready
shares = mgr.complete_heist(squad.squad_id, total_loot=10000)
# → {"player_1": 5000, "player_2": 5000}
```

**Roles:** hacker, muscle, talker, driver, demo, recon
**Lifecycle:** forming → ready → in_heist → completed/disbanded
**Loot split:** equal base + 10% bonus per obstacle cleared - 5% per argument

Skills: `form_heist_squad`, `invite_to_squad`, `vote_phase_advance`

---

## 13. Scene Development Pattern

### Creating a Scene

Every scene extends `FlaskScene`:

```python
from engine.scenes.flask_scene import FlaskScene

class MyScene(FlaskScene):
    SCENE_METADATA = {
        "name": "my_scene",
        "display_name": "MY SCENE",
        "port": 5599,
        "type": "game",
        "accent_color": "#ff6b9d",
        "description": "A cool scene.",
    }

    def __init__(self):
        super().__init__(host="0.0.0.0", port=self.SCENE_METADATA["port"])
        self._register_routes()

    def _register_routes(self):
        @self.app.route("/")
        def index():
            return render_template("my_scene.html",
                scene_key="my_scene",
                scene_display_name="MY SCENE",
                scene_accent="#ff6b9d",
                scene_accent_rgb="255 107 157")

    def on_before_serve(self):
        """Called after MCP/Nexus wired, before serve."""
        pass
```

### Template Pattern

Templates extend `neon_base.html`:
```jinja2
{% extends "neon_base.html" %}
{% block scene_content %}
  <div id="my-content">...</div>
{% endblock %}
{% block body_scripts %}
  <script src="{{ url_for('scene_static', filename='my_scene.js') }}"></script>
{% endblock %}
```

**neon_base.html provides:** Socket.IO, cosysim-core.js, cosysim-telemetry.js, neon HUD, particles, news ticker, and CSS design system. Accent colors injected as CSS custom properties.

### Frontend Conventions

- Vanilla JS (no React/Vue/build step)
- 2-space indent in JS/CSS. Single quotes in JS, double in HTML.
- `const socket = io()` for Socket.IO. `fetch()` for REST. Never `XMLHttpRequest` or `var`.
- CSS custom properties for theming (`--scene-accent`).

---

## 14. ARGUS — First-Class Reconnaissance Toolkit

### Overview

ARGUS is CosySim's **integrated web application analysis framework** — a first-class tool with 21 reusable functions, 13 documented techniques, and proven results against production AI applications. Use it automatically whenever encountering HAR files, heap snapshots, or web applications.

### CLI Usage

```bash
# Single HAR analysis
python -m scripts.argus.analyze har path/to/file.har
python -m scripts.argus.analyze har file.har --report    # Generate Markdown report

# V8 heap snapshot (regex scan)
python -m scripts.argus.analyze heap file.heapsnapshot

# V8 heap deep parse (full graph walk)
python scripts/heap_deep_parser.py file.heapsnapshot --out data/heap_output/

# Auto-analyze: full pipeline on a directory of captures
python -m scripts.argus.analyze auto path/to/captures/

# Compare two captures
python -m scripts.argus.analyze compare a.har b.har
```

### Toolkit Functions (`scripts/argus/toolkit.py`)

| Function | Purpose |
|----------|---------|
| `mine_heap()` | 100+ regex patterns on V8 heap (JWTs, API keys, internal URLs) |
| `mine_heap_deep()` | Full V8 graph walk — all strings, objects, scripts |
| `extract_agent_messages()` | Multi-agent orchestration trace extraction |
| `extract_chain_of_thought()` | Leaked model reasoning fragments |
| `extract_app_schemas()` | Tool definitions from YAML configs |
| `extract_protobuf_definitions()` | Proto3 schema extraction |
| `decompile_bundle()` | Feature flags, API routes, env vars from minified JS |
| `inject_statsig_gates()` | Flip Statsig gates via localStorage/CDP |
| `cdp_eval()` / `cdp_find_tab()` | Chrome DevTools Protocol scripting |
| `refresh_firebase_token()` | Exchange refresh_token for fresh JWT |
| `auto_analyze()` | Full automated pipeline (detect → mine → extract → report) |

### Proven Results

Extracted from Sesame AI + OpenRoom.ai: 555+ credentials, 375+ URLs, 73 API methods, 5 JWTs, 5 sub-agents (MiniMax-M2.5), 12 apps, 1 protobuf schema, 15+ chain-of-thought fragments, 14 security findings. All from V8 heap snapshots.

### Key Documentation

- `scripts/argus/README.md` — Full usage guide with regex patterns
- `docs/ARGUS_METHODOLOGY.md` — 13 reusable recon techniques
- `docs/ARGUS_DISCOVERY_JOURNAL.md` — Narrative of all exploration sessions
- `docs/ARGUS_SESAME_REPORT.md` — Sesame AI complete intelligence (876 lines)
- `docs/ARGUS_OPENROOM_REPORT.md` — OpenRoom/Talkie/MiniMax intelligence (1,138 lines)

### Analyzers (`scripts/argus/analyzers/`)

| Analyzer | File | Discovers |
|----------|------|-----------|
| **ProtocolDetector** | `protocol_detector.py` | REST, GraphQL, gRPC-web, batchexecute, WebSocket, Protobuf |
| **HARAnalyzer** | `har_analyzer.py` | Endpoints, auth schemes, tokens, rate limits, GraphQL ops, service groups |
| **HeapAnalyzer** | `heap_analyzer.py` | URLs, API paths, RPC IDs, method names, config objects, API keys |
| **DeepAnalyzer** | `deep_analyzer.py` | JWT claims, Firebase config, feature flags, WS protocols, GCS buckets |

### Protocol Detection Priority

1. URL patterns (confidence 1.0): WebSocket `wss://`, batchexecute `/_/.../data/batchexecute`, gRPC `$rpc/`, GraphQL `/graphql`
2. Content-Type headers (0.9–0.95): `application/grpc-web`, `application/protobuf`
3. Body heuristics (0.8–0.85): JSON with `query`/`mutation` → GraphQL, `f.req=` → batchexecute
4. Fallback: REST_JSON or REST_FORM

### Token Patterns Detected

Google API keys (`AIza...`), OpenAI/Stripe secrets (`sk-...`), GitHub PATs (`ghp_...`), GitLab PATs (`glpat-...`), Slack tokens (`xoxb-...`), and custom patterns via regex.

---

## 15. ARGUS Clients

### Sesame AI Explorer (`scripts/argus/clients/sesame_client.py`)

```bash
python -m scripts.argus.clients.sesame_client              # Menu
python -m scripts.argus.clients.sesame_client interactive  # REPL
python -m scripts.argus.clients.sesame_client flags        # Statsig feature flags
python -m scripts.argus.clients.sesame_client user         # User profile
python -m scripts.argus.clients.sesame_client bucket       # GCS bucket explorer
python -m scripts.argus.clients.sesame_client agents       # Probe agent services
python -m scripts.argus.clients.sesame_client staff        # Test staff gates
python -m scripts.argus.clients.sesame_client export       # Export API spec JSON
python -m scripts.argus.clients.sesame_client full         # Run everything
```

**Key discoveries:** Firebase Auth (RS256 JWT), Statsig feature flags (client key `client-TGCzy...`), 5 agent-service instances behind Google IAP, GCS bucket `sesame-dev-public`, WebSocket agent protocol with 13 message types. `@sesame.com`/`@sesameai.com` emails unlock 19/27 feature gates vs 7/27 for normal users.

### OpenRoom Explorer (`scripts/argus/clients/openroom_client.py`)

```bash
python -m scripts.argus.clients.openroom_client              # Menu
python -m scripts.argus.clients.openroom_client sessions     # Chat sessions
python -m scripts.argus.clients.openroom_client characters   # Available characters
python -m scripts.argus.clients.openroom_client chat <sid>   # Chat in session
python -m scripts.argus.clients.openroom_client rooms        # Live chatrooms
python -m scripts.argus.clients.openroom_client danmaku <rid># Watch live danmaku
python -m scripts.argus.clients.openroom_client credits      # Check wallet
python -m scripts.argus.clients.openroom_client conversations # Hidden conversation API
python -m scripts.argus.clients.openroom_client view <rid>   # Full room viewer
python -m scripts.argus.clients.openroom_client apps <sid>   # Virtual OS apps
python -m scripts.argus.clients.openroom_client files <sid>  # Storage filesystem
python -m scripts.argus.clients.openroom_client create       # Create character
python -m scripts.argus.clients.openroom_client models       # Test LLM models
python -m scripts.argus.clients.openroom_client repl         # Interactive REPL
python -m scripts.argus.clients.openroom_client full         # Run everything
```

**Key discoveries:** Weaver API (`/weaver/api/v1/`), Virtual OS with 8 apps, stage-based narrative with targets, MiniMax-M2.5 + "Modern" LLM models, protobuf WebSocket framing, credits system, hidden conversation APIs, UGC character creation, `ADMIN_ONLY_OPERATION` flag. Live stats: ~10K concurrent viewers, 3.6M likes.

---

## 16. CDP Authentication (`engine/nexus/cdp_auth_recovery.py`)

Chrome DevTools Protocol on **port 9223** (always 9223, never change). Auto-recovers Google auth for NLM and Gemini.

```python
from engine.nexus.cdp_auth_recovery import run_check, run_recovery

status = run_check()           # Read-only health check
if not status.healthy:
    status = run_recovery()    # Full recovery: cookies, BL token, API keys
print(status.summary())        # "CDP=ok | NLM=in | AIStudio=in | keys=3ok"
```

```bash
python -m engine.nexus.cdp_auth_recovery            # Full check + recover
python -m engine.nexus.cdp_auth_recovery --check    # Health check only
python -m engine.nexus.cdp_auth_recovery --keys     # API key rotation only
```

**Recovery flow:** Detect CDP → inject cookies → navigate NLM → extract BL/f.sid/at → navigate AIStudio → validate/harvest API keys → sync to GoogleAccountPool.

---

## 17. Observability — The Oracle

### CLI Diagnostics

```bash
python scripts/oracle.py                # Full diagnostic
python scripts/oracle.py --health       # Service health grid
python scripts/oracle.py --errors       # Top errors by count
python scripts/oracle.py --perf         # LLM latency + benchmarks
python scripts/oracle.py --trace ID     # Trace waterfall
python scripts/oracle.py --logs 20      # Last N errors
```

### Python API

```python
from engine.observability.oracle import get_logger, diagnose

logger = get_logger(__name__)
logger.info("[module] Something happened (operation=chat)")
logger.error("[module] Failed (operation=embed): %s", exc)

diagnose()  # Prints health + errors + perf to console
```

**Log format (mandatory):** `"[SCENE_OR_MODULE] Description (operation=what): details"`

The Oracle auto-initializes when any scene starts. Installs 3 handlers on Python root logger: StructuredLogger (SQLite + JSONL), CosyLogger (ring buffer), OracleHandler (ERROR+ → ErrorAggregator → dashboard).

---

## 18. Testing

```bash
# Smart runner (preferred — git-diff aware)
python scripts/smart_test.py                  # Tests for uncommitted changes
python scripts/smart_test.py --smoke          # ~15 files, ~30s
python scripts/smart_test.py --domain nexus   # All tests for a domain
python scripts/smart_test.py --since HEAD~3   # Tests for last 3 commits
python scripts/smart_test.py --list           # Dry-run

# pytest with smart flags
python -m pytest tests/ --affected            # Uncommitted changes only
python -m pytest tests/ --smoke-only          # Smoke suite
python -m pytest tests/ --since HEAD~1        # Since last commit

# Browser testing (MANDATORY after JS/CSS/HTML changes)
python scripts/browser_test.py
python scripts/browser_test.py --report       # Read telemetry
```

**Conventions:** pytest with plain `assert`. Mock all external services. Fixtures: `temp_db`, `event_chain`, `mock_config`. Seeded characters: lola, viktor, aria, frankie, mira.

---

## 19. Key Singletons Reference

```python
# Engine core
get_config()              # ConfigManager — dot-path YAML access
get_framework()           # MCPFramework — state tree (scenes, characters, timers)
get_governor(agent, scene) # AgentGovernor — skill selection + pipeline execution

# LMStudio
get_server_controller()   # ServerController — model lifecycle
get_task_queue()          # TaskQueue — priority dispatch
get_lmlink_manager()     # LMLinkManager — multi-instance federation

# Knowledge
get_nexus_client()        # NexusClient — Nexus REST API
get_query_router()        # NexusQueryRouter — 6-tier query pipeline
get_embedding_service()   # EmbeddingService — Gemini/LMStudio embeddings
get_filesystem()          # NexusFilesystem — virtual FS over Nexus

# Characters & world
get_character_registry()  # CharacterRegistry — profiles, states, skills
get_player_state()        # PlayerState — credits, rep, heat, inventory
get_neurochemistry_manager() # NeurochemistryManager — 6 neurotransmitters
get_character_wizard()    # CharacterWizard — 6-stage creation pipeline

# Narrative & spectator
get_narrative_engine()    # NarrativeModEngine — stages + targets
get_spectator_bus()       # SpectatorBus — danmaku broadcast

# Multiplayer
get_squad_manager()       # SquadManager — co-op heist squads

# Dialog & governance
get_dialog_system()       # DialogSystem — conversation management
get_rules_engine()        # SceneRulesEngine — scene-specific rules
get_scene_state_manager() # SceneStateManager — scene state persistence
get_skill_manifest()      # SkillManifest — scene→skill mappings
get_game_state()          # GameState — cross-scene key-value store
get_router()              # AgentRouter — agent-to-agent messaging

# Observability
get_logger(__name__)      # BoundLogger — structured logging with Oracle
get_error_aggregator()    # ErrorAggregator — fingerprinted error counts

# Training
get_training_flywheel()   # TrainingFlywheel — data collection for fine-tuning
```

---

## 20. Python Conventions

- **Imports:** Absolute only (`from engine.config import get_config`). Group: stdlib → third-party → engine → content → local.
- **Types:** Required on all function signatures. Use `from __future__ import annotations`.
- **Docstrings:** Google style (summary, `Args:`, `Returns:`, `Raises:`).
- **Naming:** PascalCase classes, snake_case functions/files, UPPER_SNAKE constants, `_underscore` private.
- **Format:** 4-space indent, double quotes, f-strings, 88–100 char soft limit, 120 max.
- **Logging:** `logger = logging.getLogger(__name__)` per module. Never `print()`. Oracle format: `"[module] Description (operation=X): detail"`.
- **State:** Mutable game state syncs to MCPFramework. Config via `get_config().get("dot.path", default)`. Never hardcode ports, paths, or model names.
- **Clients:** Always use existing singletons (`get_lms_client`, `get_nexus_client`, etc.) — never write raw HTTP calls.

---

## 21. Frontend Conventions

- **Vanilla JS** (no build step — no React/Vue)
- 2-space indent in JS/CSS. Single quotes in JS, double in HTML.
- `const socket = io()` for Socket.IO. `fetch()` for REST. Never `XMLHttpRequest` or `var`.
- CSS custom properties for theming (`--scene-accent`, `--primary-color`).
- Templates: Jinja2 in `content/scenes/{name}/templates/`. Static in `content/scenes/{name}/static/`.

---

## 22. Code Versioning

Every file you create or significantly modify MUST include:

```python
"""
Module Title
============
Brief description.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — What changed
"""
```

**Section dividers:**
```python
# ──── Section Name ────────────────────────────────────────────────
```

**Version stamps on code blocks:**
```python
# v1.51.0 [2026-03-25] — Description of what this code does
```

**Navigational comments:**
```python
# CONNECTS: PlayerState, EconomyManager
# CALLED BY: district_chat handler
# EMITS: hud_update SocketIO event
```

---

## 23. File Structure

```
CosySim/
├── engine/                    # Core framework
│   ├── agents/                # VirtualAgent, AgentGovernor, 28 interceptors
│   │   └── interceptors/      # Pre/post-call pipeline hooks
│   ├── mcp/                   # MCPFramework, dialog, state, narrative_mod
│   │   └── tools/             # 43 domain tool modules
│   ├── skills/                # @skill decorator, registry, 98 packs
│   │   └── builtin/           # 795 engine-level skills (memory, fs, narrative, creation)
│   ├── lmstudio/              # chat.py, ServerController, LMLink, TaskQueue
│   ├── nexus/                 # NexusClient, QueryRouter, EmbeddingService, filesystem
│   ├── world/                 # PlayerState, Inventory, Crew, WorldSim, economy
│   ├── characters/            # Neurochemistry, personality
│   ├── creation/              # CharacterWizard
│   ├── services/              # SpectatorBus
│   ├── scenes/                # FlaskScene base class
│   ├── tts/                   # Qwen3-TTS, Orpheus, Piper
│   ├── observability/         # Oracle, ErrorAggregator, StructuredLogger
│   ├── config.py              # ConfigManager singleton
│   ├── control_plane_registry.py  # All target definitions
│   └── port_registry.py       # Port assignments
├── content/
│   ├── scenes/                # 24 scene implementations
│   │   ├── phone/             # SIGNAL — encrypted messaging
│   │   ├── penthouse/         # THE PENTHOUSE — multi-agent roleplay
│   │   ├── neoncity/          # NEON CITY — living city simulation
│   │   ├── realm/             # SHATTERED THRONE — LitRPG with quests
│   │   ├── lab_break/         # LAB BREAK — escape scenario
│   │   ├── oracle/            # THE ORACLE — AI consciousness terminal
│   │   ├── neonos/            # NEON OS — virtual desktop shell
│   │   └── ...                # arena, casino, gallery, lounge, tavern, etc.
│   ├── shared/                # Shared templates + static assets
│   │   ├── templates/         # neon_base.html, navbar_v2.html, HUD, phone panel
│   │   └── static/            # 21 JS files, 26 CSS files (cosysim-*.js/css)
│   └── simulation/            # SQLite persistence, character services, RAG
├── scripts/
│   ├── argus/                 # ARGUS API discovery system
│   │   ├── analyze.py         # CLI entry point
│   │   ├── analyzers/         # HAR, heap, protocol, deep analyzers
│   │   └── clients/           # Sesame AI + OpenRoom interactive clients
│   ├── oracle.py              # System diagnostics CLI
│   ├── smart_test.py          # Git-diff-aware test runner
│   └── browser_test.py        # Playwright headless testing
├── config/
│   ├── default.yaml           # All settings (source of truth)
│   ├── development.yaml       # Dev overrides
│   ├── voices.yaml            # TTS voice definitions
│   └── mcp.json               # MCP server definitions
├── tests/                     # 404 test files
├── training/                  # Fine-tuning pipelines, datasets
├── docs/                      # 34 documentation files
│   ├── INDEX.md               # Central hub
│   ├── ARCHITECTURE.md        # System design
│   ├── OPENROOM_FEATURES.md   # 6 OpenRoom-inspired features
│   └── ...
├── tui.py                     # Terminal UI
├── launcher.py                # CLI launcher
├── CHANGELOG.md               # Version history
└── context.md                 # THIS FILE
```

---

## 24. Quick Reference — Common Tasks

**Add a new skill:**
```python
# engine/skills/builtin/my_skills.py
@skill(pack="my_pack", description="Does a thing", category="GAME", cooldown=5.0)
def my_skill(target: str) -> str:
    return f"Did the thing to {target}"
```

**Add a new interceptor:**
1. Create `engine/agents/interceptors/my_interceptor.py`
2. Import and add to `_REGISTRY` in `engine/agents/interceptors/__init__.py`

**Add a new scene:**
1. Create `content/scenes/my_scene/` with scene file, templates/, static/
2. Add to `engine/control_plane_registry.py` SCENE_DEFS
3. Add port to `engine/port_registry.py`

**Start a narrative:**
```python
engine = get_narrative_engine()
engine.start_mod("my_story", "Story Name", stages=[...], scene_id="my_scene")
```

**Create a character:**
```python
wizard = get_character_wizard()
state = wizard.start("Name")
wizard.set_archetype(state.wizard_id, "companion")
char_id = wizard.finalize(state.wizard_id)
```

**Run diagnostics:**
```bash
python scripts/oracle.py          # Health + errors + perf
python scripts/smart_test.py      # Tests for changes
```
