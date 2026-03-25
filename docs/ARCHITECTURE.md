# Architecture

> CosySim Documentation — v1.51.1 [2026-03-25]
>
> System design, data flow, layers, and the three-pillar architecture.

---

## Overview

CosySim is a local-first multi-scene AI simulation framework. Every NPC is an LLM-powered agent governed by a 30-interceptor pipeline, ~1,030 skills across 100 packs, and a persistent knowledge layer (Nexus KMS). The system runs 33 launch targets as Flask, FastAPI, Streamlit, and Node servers, all orchestrated by a unified launcher and TUI.

**Design principles:**

- **Engine is reusable framework.** Content is swappable. Config tunes without code.
- **Nexus-first.** If the answer exists in Nexus, use it. If you found it elsewhere, write it back.
- **Local inference.** LMStudio provides all LLM calls — no cloud API dependency for core gameplay.
- **Three pillars.** Game, Service, and Creation targets are independently launchable and monitorable.

---

## Three-Pillar Architecture

All 32 launch targets are assigned to one of three pillars. Each pillar has its own launcher preset and TUI panel. Pillar membership is defined in `engine/control_plane_registry.py` via the `pillar` field on every `SERVICE_DEFS` and `SCENE_DEFS` entry.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        THREE PILLARS                                │
│                                                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐   │
│  │  GAME (15)    │  │  SERVICE (11) │  │  CREATION (6)         │   │
│  │               │  │               │  │                       │   │
│  │  Flask scenes │  │  Infra, KMS,  │  │  Canvas, asset gen,   │   │
│  │  with agents, │  │  dashboards,  │  │  visual editors,      │   │
│  │  combat, RPG, │  │  TTS, proxies,│  │  scene creator        │   │
│  │  economy      │  │  monitoring   │  │                       │   │
│  └───────────────┘  └───────────────┘  └───────────────────────┘   │
│                                                                     │
│  Launcher: --game    Launcher: --core    Launcher: --create         │
│  TUI: Game panel     TUI: System panel   TUI: Creation panel        │
└─────────────────────────────────────────────────────────────────────┘
```

### GAME Pillar — 15 Targets

Interactive Flask scenes with Socket.IO, LLM agents, and game mechanics.

| Port | Target | Label | Description |
|------|--------|-------|-------------|
| 5555 | phone | SIGNAL | Mobile messaging interface, cyberdeck terminal |
| 5556 | penthouse | THE PENTHOUSE | Multi-agent roleplay with combat, dialog, inventory |
| 5557 | lounge | THE VELVET PIT | Social hangout scene |
| 5558 | tavern | THE RUSTY ANCHOR | Dockside tavern with quest board |
| 5559 | casino | CLUB NOIR | High-stakes poker and gambling |
| 5560 | gallery | THE OBSCURA | Dark art gallery with private viewings |
| 5561 | arena | THE COLOSSEUM | Investigation board, mystery games, 3D dice |
| 5562 | realm | THE SHATTERED THRONE | AI-directed LitRPG with murder mystery |
| 5563 | neoncity | NEON CITY | Living world hub — 6 factions, economy, reputation |
| 5564 | coders | THE LAB | Multi-agent code simulation |
| 5565 | heist | THE SCORE | Multi-agent cooperative planning |
| 5567 | games | THE ARCADE | Mystery, dice, truth-or-dare with AI GameMaster |
| 5569 | grid | THE GRID | Underground marketplace, faction den, broker |
| 5571 | lab_break | LAB BREAK | 3D escape simulation with vitals |
| 5572 | oracle | THE ORACLE | Claude's signature scene |

### SERVICE Pillar — 11 Targets

Infrastructure, monitoring, dashboards, and backend services.

| Port | Target | Type | Label | Description |
|------|--------|------|-------|-------------|
| 8700 | nexus_kms | external | Nexus KMS | Knowledge backbone (auto-start priority 0) |
| 8500 | hub | flask | CosySim Hub | Central launcher and scene navigator |
| 5570 | nexus_panel | flask | Nexus Control Panel | Knowledge management with Librarian agent |
| 8501 | dashboard | streamlit | System Dashboard | System metrics and monitoring |
| 8502 | admin | streamlit | Admin Panel | Administration interface |
| 8600 | tts | fastapi | TTS Server | Qwen3 text-to-speech |
| 8601 | bridge | fastapi | MCP Bridge | MCP web bridge |
| 8800 | nlm_proxy | flask | NLM Live Proxy | NotebookLM RPC proxy |
| 5575 | system_control | flask | System Control | Live config editor, service manager |
| 5566 | command_center | flask | Command Center | War-room dashboard with system metrics |
| 5580 | intel_hub | flask | THE BRIEFING ROOM | Intelligence command center |

### CREATION Pillar — 6 Targets

Content authoring, asset generation, and visual editing tools.

| Port | Target | Type | Label | Description |
|------|--------|------|-------|-------------|
| 5590 | canvas | node | Nexus Canvas | Knowledge notebook editor |
| 5595 | canvas_api | fastapi | Canvas API | Canvas backend REST API |
| 8503 | assets | streamlit | Asset Generator | Batch asset generation |
| 8504 | creator | streamlit | Scene Creator | Visual scene scaffolding |
| 5568 | asset_studio | flask | ASSET STUDIO | 9-tab asset hub (images, portraits, voice, video) |
| 5592 | creation_kit | flask | CREATION KIT | Visual scene editor |

**Streamlit apps (4):** dashboard, admin, assets, creator. These run as standalone Streamlit processes managed by the launcher.

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER LAYER                               │
│  Neon HUD v2 · vanilla JS · Jinja2 templates · Socket.IO client    │
│  cosysim-telemetry.js · cosysim-particles.js · design_tokens.css   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ Socket.IO / REST
┌────────────────────────────────▼────────────────────────────────────┐
│                         CONTENT LAYER                               │
│                                                                     │
│  content/scenes/{name}/          content/simulation/                │
│    *_scene.py (BaseScene)          character_system/                │
│    *_skills.py (@skill)            database/ (SQLite, RAG)          │
│    templates/, static/             services/ (ComfyUI, media)       │
│                                                                     │
│  content/shared/                                                    │
│    navbar_v2.html · neon_hud.html · portrait_overlay.html           │
│    cosysim-particles.js · cosysim-scene-fx.css · aria_widget.html  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ subclasses / uses
┌────────────────────────────────▼────────────────────────────────────┐
│                         ENGINE LAYER                                │
│                                                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│  │   nexus/     │ │    mcp/      │ │  lmstudio/   │               │
│  │ Knowledge    │ │ 43 tool mods │ │ Inference    │               │
│  │ Q&A router   │ │ Governance   │ │ ServerCtrl   │               │
│  │ Copilot sync │ │ Dialog       │ │ LMLink       │               │
│  │ Scheduling   │ │ State coord  │ │ TaskQueue    │               │
│  └──────────────┘ └──────────────┘ └──────────────┘               │
│                                                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│  │ skills/ (95) │ │  agents/     │ │   world/     │               │
│  │ ~1000 skills │ │ VirtualAgent │ │ WorldSim     │               │
│  │ @skill deco  │ │ 26 intrcptrs │ │ PlayerState  │               │
│  └──────────────┘ └──────────────┘ └──────────────┘               │
│                                                                     │
│  pipeline/ · services/ · tts/ · asset_studio/ · characters/        │
│  events/ · economy/ · arena/ · director/ · mechanics/ · art/       │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ reads
┌────────────────────────────────▼────────────────────────────────────┐
│                         CONFIG LAYER                                │
│  default.yaml · development.yaml · production.yaml · voices.yaml   │
│  skill_manifests.yaml · mcp.json · lmlink.yaml · launcher.yaml     │
│  nlm_rpcids.yaml · nlm_notebooks.yaml · news_sources.yaml          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Engine Layer

The engine is a reusable framework under `engine/`. Content layer scenes subclass and configure it. Config tunes behavior without code changes.

### Nexus — Knowledge Backbone

`engine/nexus/` — Knowledge management, Q&A routing, Copilot integration, and the training flywheel. See [Nexus](NEXUS.md) for the full reference.

**Smart Query Router** — 5-tier pipeline that progressively escalates:

```
Request → ① Q&A Cache (instant, 0 tokens)
        → ② FTS5 Search (fast, synthesize from entries)
        → ③ Nexus Ask (server-side pipeline)
        → ④ Direct NotebookLM Ask (grounded, free)
        → ⑤ LMStudio Fallback (local inference, auto-stored)
```

Every LLM answer is auto-cached. The next identical question gets an instant Nexus answer.

**Key modules:** NexusClient (CRUD), NexusQueryRouter (5-tier), CopilotBridge (session context), TrainingFlywheel (data collection), SchedulerDaemon (55 recurring tasks), KnowledgeCapture (entry + Q&A pair storage).

### LMStudio — Local Inference

`engine/lmstudio/` — Stateful conversations, SSE streaming, model profiles, and multi-instance federation. See [LMStudio](LMSTUDIO.md) for details.

**Inference chain:**

```
AgentRouter.resolve_model()          # pick model profile
  → LMSClient.infer_stream()        # SSE to localhost:1234
    → StreamProcessor.extract_tags() # [MOOD:x], [IMAGE:p], etc.
    → OutputEvaluator.score()        # quality 0.0–1.0
    → DataCollector.collect()        # training flywheel capture
```

**Model profiles:** `big` (complex reasoning, 32k context), `small` (fast dialog, 8k), `router` (classification, 2k), `draft` (speculative decoding, 2k).

**LMLink federation:** Connects multiple LMStudio instances (local or remote via Tailscale). Config in `config/lmlink.yaml`. Remote models appear alongside local models. Automatic failover on peer disconnect.

**Input format:** Messages use `{"type": "text", "text": "..."}` or `{"type": "image", "data_url": "data:..."}`. All API calls require `Authorization: Bearer <token>` from config.

### Agents — Inference Governance

`engine/agents/` — Agent lifecycle, governance, and the interceptor pipeline.

**Agent chain:**

```
AgentGovernor
  └→ AgentRouter (picks model/backend)
       └→ VirtualAgent.reply()
            └→ VirtualAgentManager (pool management)
                 └→ build_request() ← governance_context injected
                      └→ LMSClient.infer_stream()
```

**Key modules:** VirtualAgent (system prompt, skill awareness, conversation threading), VirtualAgentManager (named agent pool per scene), AgentGovernor (safety, policy, context injection), AgentRouter (model selection), StreamProcessor (tag extraction), OutputEvaluator (quality scoring), CommsFramework (interceptor orchestrator).

### World Simulation

`engine/world/` — Persistent game world with faction dynamics, economy, missions, and NPC autonomy.

**World event flow:**

```
WorldSim tick (every 60s)
  → generate SimEvent (economy_tick / faction_shift / npc_action / weather)
  → EventCascade broadcasts to all subscribed scenes
  → Scenes update local state + emit Socket.IO events
  → HUD ticker displays event text
  → PlayerState receives credits/rep/heat deltas
```

**Key modules:** WorldSim (faction dynamics, economy ticks, weather), PlayerState (credits, rep, heat, faction standings, auto-save), CityMap (location graph, travel routes), Missions (accept, track, complete, rewards), Crew (formation, roles, trust), Inventory (24 slots, equipped dict, consumable effects).

### Skills — Agent Capabilities

`engine/skills/builtin/` — ~1,000 skills across 95 packs (45 builtin + 19 scene-specific + meta packs). See [Skills](SKILLS.md) for the full registry.

**Skill decorator:**

```python
@skill(
    pack="scene_name",
    description="LLM-facing description",
    category="GAME",       # COMMUNICATION|MEMORY|MEDIA|GAME|SOCIAL|ENVIRONMENT|SYSTEM|NARRATIVE
    cooldown=5.0,
    cost=1.0,
    tags=["tag"],
    prerequisites=["other_skill"],
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

Skills are auto-discovered by the registry. Scene-specific skills live in `content/scenes/{name}/{name}_skills.py`.

### Pipeline and Services

| Subsystem | Key Modules |
|-----------|-------------|
| `engine/pipeline/` | VirtualPipeline (multi-step chains), StreamWatcher, KillSwitch, TokenRouter |
| `engine/services/` | ActivityBus (cross-scene tracking), WorldAnnouncer, HackEngine, Resilience (retry/circuit breaker) |
| `engine/tts/` | Qwen3 TTS, Orpheus native, CosyVoice, voice profiles |
| `engine/asset_studio/` | WorkflowBuilder (ComfyUI nodes), TuningEngine (A++ profiles), 8 content generators |
| `engine/characters/` | CharacterMemory, reputation, player profile |
| `engine/events/` | EventBus, cross-scene relay |
| `engine/economy/` | EconomyManager |
| `engine/arena/` | ArenaEngine |
| `engine/director/` | SceneDirector, narrative orchestration |
| `engine/content/` | ContentEngine, ContentGate, NLM generator |

### Training System

`training/` — Model zoo, dataset generators, finetune orchestrator, benchmarks. See [Training](TRAINING.md).

```
Runtime data → DataCollector → JSONL datasets
                                     ↓
              LMStudio ← promote ← BenchmarkRunner
                  ↓                      ↓
            better responses      FinetuneOrchestrator
                  ↓                      ↓
            more data ──────────→ trained model
```

14 model types tracked by ModelZoo (router, coder, conversational, tool_dispatch, voice, output_evaluator, and more). Every conversation, skill call, and grammar scan becomes training data.

---

## Content Layer

Each scene lives in `content/scenes/{name}/` and subclasses `BaseScene`:

```
content/scenes/{name}/
├── __init__.py           # Scene class
├── {name}_scene.py       # Class implementation
├── {name}_skills.py      # @skill-decorated functions (pack="{name}")
├── templates/
│   └── {name}.html       # Jinja2 template with {% include 'navbar_v2.html' %}
└── static/
    ├── css/
    ├── js/
    └── img/
```

**BaseScene contract:**

```python
class MyScene(BaseScene):
    SCENE_METADATA = {"name": "my_scene", "port": 5567, "type": "game"}

    def start(self):
        register_shared_assets(self.app)        # /shared/* — REQUIRED
        self.register_health_route(self.app)     # /api/health
        self.register_hud_route(self.app)        # /api/hud/state
        self.register_announcer_route(self.app)  # /api/announcer/feed

    def stop(self):
        # Persist state, cleanup resources
```

**Shared frontend assets** (`content/shared/`): navbar_v2.html (self-contained nav bar), neon_hud.html (credits/rep/heat strip), portrait_overlay.html (character panel with mood badges), cosysim-particles.js (per-scene particle effects), cosysim-scene-fx.css (ambient animations via `[data-scene]`), design_tokens.css (CSS custom properties for theming).

**Scene registration checklist:**

1. `engine/port_registry.py` — port assignment
2. `engine/control_plane_registry.py` — target metadata and pillar
3. `config/default.yaml` — scene config block
4. `content/scenes/{name}/` — scene directory with required files

See [Scenes](SCENES.md) for the full scene reference.

---

## MCP Pipeline

`engine/mcp/` — 23 core framework files + 43 tool modules = 66 files. See [MCP Framework](MCP_FRAMEWORK.md) for the full reference.

**Core modules:** MCPFramework (root state tree), DialogSystem (conversation tracking), SceneStateManager (mutable state coordination), SceneRulesEngine (declarative game rules), AgentGovernor runtime (policy enforcement), NLM proxy (NotebookLM bridge).

**43 MCP tool modules** in `engine/mcp/tools/`, each exposing domain-specific tools via `@mcp_tool`:

| Domain | Modules |
|--------|---------|
| Game & Narrative | game, narrative, story, character, social, emotion, relationship, reputation, npc, npc_backstory, memory, inventory, crew, mission, city, hacking, board, investigation |
| Knowledge & System | nexus, knowledge, coding, evaluation, experiment, training, benchmark |
| Media & Assets | comfyui, tts, voice, vision, art, asset, media |
| Infrastructure | lmstudio, inference, config, system, autonomy, copilot, colab, google_account, cdp, homeassistant, notebooklm |

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

---

## Interceptor Pipeline

24 interceptors in `engine/agents/interceptors/`, auto-discovered at import. Each has a priority (lower = runs first) and a phase (PRE = before LLM call, POST = after). See [Interceptors](INTERCEPTORS.md) for the full reference.

### Priority Bands

| Range | Phase | Purpose | Examples |
|-------|-------|---------|----------|
| 5–10 | PRE | Identity, knowledge, mood | MoodDrift (5), NexusPrompt (6), Recap (7), CharRegistry (8) |
| 10–20 | PRE | Routing, scene context, events | Router (10), Dialog (12), Scene interceptors (15–16), Ambient (17) |
| 20–40 | PRE | Skills, games, auto-results | AutoResult (20), SkillAwareness (30), Game (35) |
| 50–70 | PRE | Behavioral guardrails | PersonalityGuard (50), Variety (55), PolicyEnforcer (60), Memory (70) |
| 80–93 | POST | Response processing, logging | ResponseShaper (80), TTS (85), Logger (90), MoodSync (92), Relationship (93) |

Some interceptors (DialogDirective, Game, ConversationVariety) run in **both** PRE and POST phases.

**Abort flag:** Any PRE interceptor can set `ctx["abort"] = True` to skip the LLM call entirely.

---

## Data Flow — Chat Request Lifecycle

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
  │   │   └─ 21 PRE interceptors inject context
  │   │
  │   ├─ LMSClient.infer_stream(request)
  │   │   └─ SSE to localhost:1234
  │   │
  │   └─ InterceptorPipeline.run_post(response, context)
  │       └─ 7 POST interceptors process response
  │
  ├─ StreamProcessor.extract_tags(response)
  │   ├─ [MOOD:happy]      → character registry update
  │   ├─ [IMAGE:prompt]    → ComfyUI generation queue
  │   ├─ [ACTION:x]        → game event trigger
  │   ├─ [STAT:health+10]  → player state update
  │   └─ [VOICE:style]     → TTS style override
  │
  └─ Scene emits response via Socket.IO
      ├─ Chat message to client
      ├─ HUD update (if stats changed)
      ├─ Portrait mood update
      └─ Optional TTS audio
```

### Stream Tags

`StreamProcessor` extracts inline tags from LLM output in real-time:

| Tag | Effect |
|-----|--------|
| `[MOOD:x]` | Updates character mood in CharacterRegistry |
| `[IMAGE:prompt]` | Queues image generation via ComfyUI |
| `[ACTION:x]` | Triggers a game event |
| `[STAT:name±val]` | Adjusts player stat (health, credits, etc.) |
| `[VOICE:style]` | Overrides TTS voice style for this response |

Use `infer_processed()` for tag extraction, `infer_stream()` for raw streaming.

---

## State Management — Key Singletons

These are obtained via `get_*()` factory functions from `engine/mcp/` and are shared process-wide:

```python
get_framework()              # MCPFramework — root state tree
get_character_registry()     # CharacterRegistry — all loaded characters
get_dialog_system()          # DialogSystem — conversation tracking
get_rules_engine()           # SceneRulesEngine — declarative game rules
get_scene_state_manager()    # SceneStateManager — mutable scene state
get_governor()               # AgentGovernor — policy enforcement
get_router()                 # AgentRouter — model selection
get_game_state()             # GameState — current game session
get_skill_manifest()         # SkillManifest — skill registry metadata
```

Additional singletons from other subsystems:

```python
get_config()                 # ConfigManager — dot-notation config access
get_nexus_client()           # NexusClient — knowledge CRUD
get_query_router()           # NexusQueryRouter — 5-tier smart query
get_port_registry()          # PortRegistry — port lookups with config override
```

### Configuration Access

```python
from engine.config import get_config
cfg = get_config()
port = cfg.get("scenes.penthouse.port", 5556)
model = cfg.get("lmstudio.models.primary", "default-model")
```

Always provide sensible defaults in `get()` calls. Never hardcode ports, paths, model names, or API URLs. Configuration hierarchy: `config/default.yaml` (base) → `config/development.yaml` or `config/production.yaml` (environment overrides).

---

## External Services

Services not managed by the CosySim launcher that must be running independently.

| Port | Service | Status | Purpose |
|------|---------|--------|---------|
| 1234 | LMStudio | Manual start required | Local LLM inference (all agent calls) |
| 8700 | Nexus KMS | Auto-managed (priority 0) | Knowledge backbone, Q&A, rules |
| 8188 | ComfyUI | Optional, manual start | Image/video generation |
| 8600 | TTS | Launcher-managed | Text-to-speech (Qwen3) |

**Infrastructure ports** (not launcher-managed):

| Port | Service |
|------|---------|
| 5005 | Orpheus TTS |
| 5050 | CosyVoice TTS |
| 5051 | Whisper STT |

Health check: `GET http://localhost:{port}/health` on all Flask/FastAPI targets.

---

## Testing

404 test files under `tests/`. See [Operations](OPERATIONS.md) for test commands.

**Smart runner** (preferred): `python scripts/smart_test.py` — git-diff aware, runs only tests affected by changes. Supports `--smoke` (15 files, one per domain), `--domain`, `--since`, and `--list` modes.

**Pytest flags**: `--affected`, `--staged`, `--smoke-only`, `--since HEAD~N`, `--cap N`.

**Browser testing**: `python scripts/browser_test.py` (Playwright) — mandatory before committing UI changes. Telemetry via `cosysim-telemetry.js` captures clicks, errors, and hotkeys.

---

## Cross-References

| Document | Covers |
|----------|--------|
| [MCP Framework](MCP_FRAMEWORK.md) | Tool modules, state tree, governance, dialog system |
| [Skills](SKILLS.md) | Skill packs, decorator reference, registration |
| [Interceptors](INTERCEPTORS.md) | Full interceptor reference with examples |
| [Scenes](SCENES.md) | Scene reference, BaseScene contract, shared assets |
| [Nexus](NEXUS.md) | Knowledge layer, query router, Copilot integration |
| [LMStudio](LMSTUDIO.md) | Inference client, model profiles, LMLink federation |
| [Operations](OPERATIONS.md) | Launcher, TUI, testing, monitoring |
| [Configuration](CONFIGURATION.md) | Config files, dot-notation access, environment overrides |
| [Training](TRAINING.md) | Model zoo, dataset generators, finetune pipeline |
| [Game Systems](GAME_SYSTEMS.md) | Economy, factions, missions, crew, inventory |
| [Character System](CHARACTER_SYSTEM.md) | Personality, memory, relationships |
| [ARGUS](ARGUS.md) | Browser automation, CDP bridge, decoders |
| [TTS](TTS.md) | Voice synthesis, profiles, CosyVoice |
| [Asset Studio](ASSET_STUDIO.md) | ComfyUI workflows, tuning engine, generators |

---

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| v1.50 | 2026-03-22 | Full rewrite — three-pillar architecture, accurate counts (32 targets, ~1,000 skills, 24 interceptors, 43 tool modules, 404 tests), tightened structure |
| v0.91b | 2026-03-21 | Previous version — 20 scenes, outdated counts, pre-pillar architecture |
