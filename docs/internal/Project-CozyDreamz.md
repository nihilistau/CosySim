# Project CozyDreamz — The Dream Architecture

**Generated:** 2026-02-24
**Status:** Living design document — the blueprint for CosySim v4.0
**Purpose:** Define the complete, fully-wired, framework-driven system

---

## Executive Summary

CosySim has excellent infrastructure but fragmented adoption. The framework provides
24 interceptors, a rules engine, dialog system, state coordinator, conversation heat,
interaction trees, MCPTimers, game sessions, cross-scene messaging, a 3-tier inference
router, stream watcher with kill switch, and a training pipeline. **Most scenes use
less than 30% of these features.**

**The Dream:** Every scene is a thin declarative shell. The framework drives ALL behavior.
Scenes declare rules, register handlers, provide templates. They don't contain logic.

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Architecture Overview](#2-architecture-overview)
3. [Critical Bugs](#3-critical-bugs)
4. [Framework Adoption Matrix](#4-framework-adoption-matrix)
5. [The Thin Scene Pattern](#5-the-thin-scene-pattern)
6. [State Management Architecture](#6-state-management-architecture)
7. [Agent Pipeline Architecture](#7-agent-pipeline-architecture)
8. [LMStudio Integration Layer](#8-lmstudio-integration-layer)
9. [MCP Skills & Tools](#9-mcp-skills--tools)
10. [Scene Migration Plans](#10-scene-migration-plans)
11. [Port Map](#11-port-map)
12. [Test Strategy](#12-test-strategy)
13. [Documentation Plan](#13-documentation-plan)
14. [Long-Horizon Implementation Plan](#14-long-horizon-implementation-plan)
15. [File Inventory](#15-file-inventory)

---

## 1. Current State Assessment

### What Works Well (Keep & Extend)
- **Interceptor pipeline** — 24 interceptors, priority 8-92, composable
- **CharacterStateCoordinator** — unified state write-through (NEW)
- **LMSClient** — native v1 API, SSE streaming, stateful conversations
- **InferenceRouter** — 3-tier priority queue with affinity tracking
- **Skill system** — @skill decorator, registry, cooldowns, packs (Training Skills ×4, NotebookLM Skills ×5 built-in)
- **VirtualPipeline** — stream watcher + kill switch + pre-warm
- **TagRegistry** — extensible inline tag routing
- **ConversationHeat** — thermal conversation model with auto-decay
- **Training pipeline** — dataset generation + auto-train + Colab notebook
- **TTS streaming** — real-time text-to-speech endpoint (Sprint 13)

### What Needs Work (Fix & Wire)
- **7 of 11 scenes** don't use Governor/Interceptor pipeline
- **ALL scenes** bypass DialogSystem with hardcoded system prompts
- **Port conflicts** — Realm/Heist share 5562, NeonCity/CommandCenter share 5563
- **Phone scene** maintains parallel state universe (PhoneDB vs framework)
- **MCPTimer** underused (only 2 of 11 scenes)
- **Only 3 of 11 scenes** have tests
- **InteractionTree phases** — rich data, zero consumers
- **Clothing system** — fully built, zero calls
- **Cross-scene messaging** — works, only 1 consumer
- **cosysim_server.py** — 4,255 lines monolith

### Dead Code & Orphans
- `content/characters/` — empty directory
- `games/truth_or_dare.py`, `games/mystery_investigation.py` — orphaned modules
- Clothing wardrobe methods — never called
- `NarrativeLog.search()` — never called
- `DialogTree.export_to_json()` — never called
- `get_available_interactions()` — never called
- `MCPTimer` class — defined but never instantiated

---

## 2. Architecture Overview

### Target Architecture (v4.0 Dream)

```
                        ┌─────────────────────────┐
                        │      LAUNCHER            │
                        │   (scene discovery,      │
                        │    service orchestration) │
                        └──────────┬──────────────┘
                                   │
                 ┌─────────────────┼─────────────────┐
                 ▼                 ▼                  ▼
         ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
         │  SCENE A     │ │  SCENE B     │ │  OVERLAY/ADMIN   │
         │  (thin shell)│ │  (thin shell)│ │  (monitoring)    │
         └──────┬───────┘ └──────┬───────┘ └──────┬───────────┘
                │                │                 │
                └────────────────┼─────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     MCP FRAMEWORK       │
                    │  ┌──────────────────┐   │
                    │  │ AgentGovernor    │   │
                    │  │  └─Interceptors  │   │
                    │  │    (18 stages)   │   │
                    │  ├──────────────────┤   │
                    │  │ StateCoordinator │   │
                    │  │  ├─Registry      │   │
                    │  │  ├─SSM           │   │
                    │  │  └─Database      │   │
                    │  ├──────────────────┤   │
                    │  │ SceneRulesEngine │   │
                    │  │  └─Threshold     │   │
                    │  │    auto-fire     │   │
                    │  ├──────────────────┤   │
                    │  │ DialogSystem     │   │
                    │  │  └─build_prompt()│   │
                    │  ├──────────────────┤   │
                    │  │ ConversationHeat │   │
                    │  │  └─feeds rules   │   │
                    │  ├──────────────────┤   │
                    │  │ MCPTimer         │   │
                    │  │  └─all scheduling│   │
                    │  ├──────────────────┤   │
                    │  │ MCPGameSession   │   │
                    │  │  └─all games     │   │
                    │  ├──────────────────┤   │
                    │  │ InteractionTree  │   │
                    │  │  └─multi-turn    │   │
                    │  │    sequences     │   │
                    │  ├──────────────────┤   │
                    │  │ CrossSceneComms  │   │
                    │  │  └─agent-to-agent│   │
                    │  └──────────────────┘   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    LMSTUDIO LAYER       │
                    │  ┌──────────────────┐   │
                    │  │ InferenceRouter  │   │
                    │  │  (3-tier queue)  │   │
                    │  ├──────────────────┤   │
                    │  │ VirtualPipeline  │   │
                    │  │  (watcher+kill)  │   │
                    │  ├──────────────────┤   │
                    │  │ LMSClient        │   │
                    │  │  (v1 API + SSE)  │   │
                    │  ├──────────────────┤   │
                    │  │ ConversationMgr  │   │
                    │  │  (stateful+branch│   │
                    │  ├──────────────────┤   │
                    │  │ ResourceManager  │   │
                    │  │  (6 strategies)  │   │
                    │  └──────────────────┘   │
                    └─────────────────────────┘
```

### Key Principle: Scenes Are Configuration, Not Code

CURRENT (anti-pattern):
```python
class PhoneScene:
    def on_message(self, user_msg):
        system = f"You are {name}. Be flirty..."  # hardcoded
        mgr = get_virtual_agent_manager()         # bypasses governor
        req = InferenceRequest(messages=[...])     # manual construction
        response = mgr.infer_processed(req)        # no interceptors
        self.db.update_stats(char, arousal=+5)     # direct state write
```

TARGET (framework-driven):
```python
class PhoneScene(BaseScene, MCPSceneMixin):
    def setup(self):
        self.register_rules(PHONE_RULES)           # declarative rules
        self.register_character_agents()            # auto-creates governors
        # That's it. Framework handles everything.

    def on_message(self, char_id, user_msg):
        governor = self.get_governor(char_id)       # framework-managed
        result = governor.reply(user_msg)           # full pipeline fires
        # State updates happen automatically via interceptors
```

---

## 3. Critical Bugs

### BUG-001: ResourceManager._load_model() — Undefined Variable
**File:** `engine/lmstudio/resource_manager.py` line ~442
**Issue:** Returns `success` which is never defined. Will raise `NameError`.
**Fix:** Replace `return success` with `return result.status == "loaded"`
**Priority:** HIGH — blocks any model loading via ResourceManager

### BUG-002: PipelineResult.pipeline_started — Shared Timestamp
**File:** `engine/pipeline/pipeline_result.py` line ~161
**Issue:** `pipeline_started: float = time.time()` evaluates ONCE at class definition.
All instances share the same timestamp.
**Fix:** `pipeline_started: float = field(default_factory=time.time)`
**Priority:** MEDIUM — affects pipeline timing metrics

### BUG-003: ConfigManager.set() — Missing Nested Dict Creation
**File:** `engine/config.py` line ~180
**Issue:** `set("a.b.c", value)` crashes if intermediate dict `a` doesn't exist.
`get()` handles this gracefully with auto-traversal but `set()` doesn't.
**Fix:** Add intermediate dict creation in set() path
**Priority:** LOW — most config is read-only at runtime

---

## 4. Framework Adoption Matrix

Current state of framework feature adoption per scene:

| Scene | Port | Governor | Interceptors | DialogSys | Heat | Rules | Timer | GameSess | Coord | CrossMsg | Tests |
|-------|------|----------|-------------|-----------|------|-------|-------|----------|-------|----------|-------|
| Phone | 5555 | YES | YES | NO | Partial | NO | YES | NO | NO | NO | NO |
| Bedroom | 5556 | YES | YES | NO | YES | YES | Manual | NO | Partial | NO | NO |
| Lounge | 5557 | YES | YES | Partial | YES | NO | YES | NO | NO | YES | NO |
| Casino | 5559 | YES | YES | Partial | YES | NO | YES | YES | NO | NO | NO |
| Gallery | 5560 | NO | NO | NO | NO | NO | Manual | NO | NO | NO | NO |
| Warzone | 5561 | NO | NO | NO | NO | NO | Manual | NO | NO | NO | NO |
| Realm | 5562 | NO | NO | NO | NO | NO | NO | NO | NO | NO | YES |
| NeonCity | 5563 | NO | NO | NO | NO | NO | NO | NO | NO | NO | YES |
| Coders | 5564 | NO | NO | NO | NO | NO | Manual | NO | NO | NO | YES |
| Heist | 5562! | NO | NO | NO | NO | YES | Manual | YES | NO | NO | NO |
| CmdCtr | 5563! | NO | NO | NO | NO | NO | Manual | NO | NO | NO | NO |

**Legend:** YES = fully using, Partial = partially, NO = not using, Manual = own threading

**Target:** Every cell should be YES (or N/A where genuinely not applicable).

---

## 5. The Thin Scene Pattern

### Scene Lifecycle (Framework-Driven)

```
1. Scene.__init__()
   └─ super().__init__()
      ├─ _mcp_init()  ← registers with MCPFramework
      ├─ BaseScene.__init__()  ← registers in _ACTIVE_SCENES
      └─ _init_flask_app()  ← sets up routes

2. Scene.setup()  ← SCENE'S ONLY JOB
   ├─ register_rules(SCENE_RULES)      ← declarative rules
   ├─ register_characters([...])       ← characters for this scene
   ├─ register_interactions([...])     ← interaction tree bindings
   ├─ register_game(type, config)      ← optional game session
   └─ register_timers([...])           ← optional periodic tasks

3. Framework takes over:
   ├─ Creates AgentGovernor per character
   ├─ Loads character profiles from DB
   ├─ Builds system prompts via DialogSystem
   ├─ Wires ConversationHeat per conversation
   ├─ Activates threshold rules
   ├─ Starts MCPTimers
   └─ Opens cross-scene message channels

4. Scene.on_message(char_id, user_msg)  ← only handler needed
   └─ governor.reply(user_msg)  ← full pipeline fires automatically
```

### What Scenes Should NOT Do
- Construct system prompts (DialogSystem does this)
- Update stats directly (Coordinator does this via interceptors)
- Manage threading (MCPTimer does this)
- Build InferenceRequests (Governor does this)
- Track conversation state (ConversationManager does this)
- Manage game turns (MCPGameSession does this)

### What Scenes SHOULD Do
- Define rules as data structures (conditions, effects, thresholds)
- Register scene-specific routes (Flask/Streamlit UI)
- Provide HTML/CSS templates
- Define scene-specific MCP skills
- Configure scene-specific interceptor behavior via metadata

---

## 6. State Management Architecture

### Current State Flow (Fragmented)
```
Scene writes stats ──► SceneStateManager (memory only)
Interceptors write mood ──► CharacterRegistry (memory only)
Nobody writes to ──► Database (persistent)
                          │
Result: Three stores, never synced
```

### Target State Flow (Unified via Coordinator)
```
ANY state change ──► CharacterStateCoordinator.update()
                         │
                    ┌────┼────┐
                    ▼    ▼    ▼
               Registry SSM  Database
              (runtime)(scene)(persist)
                    │
                    ▼
               ActivityBus("state_changed")
                    │
               ┌────┼────┐
               ▼    ▼    ▼
          Overlay  Rules  Logging
```

### State Coordinator Field Map

| Category | Fields | Store |
|----------|--------|-------|
| **Identity** | mood, mood_intensity, focus, current_role, energy, inhibition | CharacterRegistry |
| **Stats** | arousal, horniness, pleasure, happiness, anger, fear, drunkenness, tiredness, explicitness, openness, affection, dominance | SceneStateManager |
| **Restrictions** | add_restriction, remove_restriction | CharacterRegistry |
| **Flags** | Any unknown field | CharacterRegistry (flags dict) |
| **Persistence** | persist=True triggers DB write-through | Database (mood, energy columns) |

### Migration Path
Every direct call to `registry.set_state()` or `ssm.update_stats()` in scenes
must be replaced with `get_coordinator().update(char_id, **fields)`.

**Call sites to migrate:** ~40 across all scene files.

---

## 7. Agent Pipeline Architecture

### Full Request Flow

```
User Message
    │
    ▼
AgentGovernor.reply(msg)
    │
    ├─ PRE-CALL INTERCEPTORS (priority order 8→70):
    │  8  CharacterRegistryInterceptor ── identity, force_response
    │  10 RouterMessageInjector ──────── inbox messages
    │  12 DialogDirectiveInterceptor ─── must_include, style_lock
    │  15 SceneInterceptor ──────────── scene-specific context
    │  20 AutoResultInjector ─────────── auto-triggered skill results
    │  30 SkillAwarenessInterceptor ──── available tools list
    │  35 GameInterceptor ────────────── game state + rules
    │  50 PersonalityGuardInterceptor ── tone enforcement
    │  55 ConversationVarietyInterceptor anti-repetition + heat
    │  60 PolicyEnforcerInterceptor ──── token budget
    │  70 MemoryEnhancerInterceptor ──── RAG results
    │
    ▼
Agent.reply(msg, governance_context=<all injections>)
    │
    ▼
VirtualAgentManager.infer_with_pipeline(request)
    │
    ├─ InferenceRouter assigns tier + priority
    ├─ StreamWatcher monitors tokens in real-time
    ├─ KillSwitch can abort + retry with modified prompt
    ├─ TokenAheadRouter pre-warms tools on intent detection
    │
    ▼
LMSClient.chat(messages, stream=True)  ← v1 API + SSE
    │
    ▼
StreamProcessor extracts tags:
    [MOOD:happy] [IMAGE:desc] [ACTION:sit] [STAT:energy-5]
    [VOICE:whisper] [SEND:aria] [EVENT:name] [MEMORY:fact]
    │
    ▼
ProcessedResponse (clean_text + metadata)
    │
    ├─ POST-CALL INTERCEPTORS (priority order 80→92):
    │  80 ResponseShaperInterceptor ──── strip markers
    │  85 TTSStyleInterceptor ─────────── voice mapping
    │  90 ActivityLoggerInterceptor ───── event chain log
    │  92 MoodSyncInterceptor ─────────── state writeback + threshold rules
    │
    ▼
Final Response ← returned to scene/UI
```

### Key Insight: The Pipeline IS the Framework

Everything a scene needs happens in the interceptor pipeline:
- Identity injection (who am I)
- Context injection (what's happening)
- Skill awareness (what can I do)
- Game rules (what game am I in)
- Personality enforcement (how should I talk)
- Anti-repetition (don't repeat yourself)
- Policy (response length)
- Memory (what do I remember)
- Post-processing (clean up, log, sync state)

**Scenes that bypass the governor bypass ALL of this.**

---

## 8. LMStudio Integration Layer

### Architecture

```
                     ┌──────────────────────┐
                     │   InferenceRouter    │
                     │  (priority queue)    │
                     │  T1: GPU Primary     │
                     │  T2: CPU Utility     │
                     │  T3: CPU Router      │
                     └──────────┬───────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                   ▼
     ┌──────────────┐ ┌──────────────────┐ ┌──────────────┐
     │ LMSClient    │ │ ResourceManager  │ │ SDKClient    │
     │ (v1 REST)    │ │ (6 strategies)   │ │ (WebSocket)  │
     │ - chat       │ │ - SINGLE_BIG     │ │ - .act()     │
     │ - stream     │ │ - CONCURRENT     │ │ - embeddings │
     │ - stateful   │ │ - MULTI_SMALL    │ │ - streaming  │
     │ - tools      │ │ - JIT_SWAP       │ │              │
     │ - models     │ │ - SPECULATIVE    │ │              │
     │              │ │ - HYBRID         │ │              │
     └──────────────┘ └──────────────────┘ └──────────────┘
```

### Key v1 API Features Used
- **Stateful conversations:** `previous_response_id` for KV cache reuse
- **SSE streaming:** 19 event types (chat, model_load, reasoning, tool_call, message, error)
- **Ephemeral MCP:** Per-request tool servers (no persistent server needed)
- **Structured output:** JSON schema enforcement
- **Speculative decoding:** Draft model for speed
- **Image input:** VLM support for visual scenes

### Configuration Surface (50+ YAML keys)
```yaml
lmstudio:
  host: localhost
  port: 1234
  vram_cap_mb: 11500
  load_mode: CONCURRENT          # CONCURRENT | JIT | JIT_TTL
  resource_manager:
    strategy: CONCURRENT         # 6 strategies
    default_ttl: 3600
  router:
    max_queue_depth: 50
    preempt_on_priority: true
  models:
    primary:
      key: "model-name"
      slots: 4
      device: gpu
    utility:
      key: "small-model"
      slots: 2
      device: cpu
    router:
      key: "gemma-270m"
      slots: 1
      device: cpu
  inference_defaults:
    temperature: 0.8
    max_output_tokens: 4000
    context_length: 4096
```

---

## 9. MCP Skills & Tools

### Skill Architecture
```
@skill(name="remember", pack="memory", cooldown=5)
def remember(fact: str, character_id: str) -> str:
    """Store a fact in long-term memory."""
    ...

# Auto-registered in SKILL_REGISTRY
# Available via MCP server tools
# Exposed to LLM via SkillAwarenessInterceptor
# Cooldown enforced by CooldownTracker
```

### Skill Packs (Builtin)
| Pack | Skills | Purpose |
|------|--------|---------|
| memory | remember, recall, forget | Long-term memory via RAG |
| voice | generate_voice, voice_message | TTS integration |
| character | get_profile, set_mood, describe_self | Character state access |
| social | send_message, react, compliment | Social interactions |
| board | view_highscores, submit_score, post_board | Shared boards |
| tts | cast_voice, list_voices, generate_speech | CosyVoice TTS |

### MCP Server Tools (~50 in cosysim_server.py)
Categories: character management, state updates, game control, memory/RAG,
scene management, interaction trees, rules engine, conversation management,
image generation, consequence scheduling, director tools.

### Tool Registry Scopes
```
CHARACTER  — per-character tools (mood, memory, describe)
GAME       — game-specific tools (draw_card, roll_dice)
SYSTEM     — infrastructure (health, metrics, config)
ROUTER     — routing/classification tools
SCENE      — scene management (transition, state)
CONVERSATION — chat tools (send, history)
ADMIN      — admin-only tools (god_mode, config)
```

---

## 10. Scene Migration Plans

### Priority Order (by user impact)

#### Phase 1: Fix Bugs (immediate)
- [ ] BUG-001: ResourceManager undefined variable
- [ ] BUG-002: PipelineResult shared timestamp
- [ ] BUG-003: ConfigManager.set() crash

#### Phase 2: High-Traffic Scenes (Phone + Bedroom)
**Phone Scene Migration:**
- Replace `_PhoneCharacterAgent.reply()` hardcoded prompt with DialogSystem
- Route PhoneDB runtime state through Coordinator
- Replace `_ticker_loop()` with MCPTimer
- Wire ConversationHeat into phone scene interceptor
- Wire cross-scene messaging (incoming texts from other scenes)
- Keep PhoneDB for message persistence only

**Bedroom Scene Migration:**
- Replace manual stat_drifts with Coordinator.update()
- Wire InteractionTree phases into multi-turn sequences
- Wire clothing system (or remove it)
- Ensure ALL agent calls go through Governor (verify no fallback paths)

#### Phase 3: Medium-Traffic Scenes (Lounge + Casino)
- Lounge: already well-integrated, just wire Coordinator
- Casino: wire Coordinator, ensure MCPGameSession is primary

#### Phase 4: Framework-Lite Scenes (Gallery, Warzone, Realm, NeonCity, Coders, Heist)
- Each needs: Governor wrapping, scene interceptor, Coordinator
- Realm: wire DialogSystem (currently 288-line hardcoded prompts)
- Heist: wire Governor + interceptors
- Gallery: add Governor for curator/critic agents
- Warzone: add Governor for narrator
- Coders: add Governor for agent roles
- NeonCity: add Governor for narrator

#### Phase 5: Infrastructure
- Fix port conflicts (new port map)
- Delete dead code (clothing if unused, orphaned games, empty dirs)
- Split cosysim_server.py into domain modules
- Expand test coverage to all scenes

---

## 11. Port Map

### Current (with conflicts)
| Port | Scene | Conflict? |
|------|-------|-----------|
| 5555 | Phone + Dashboard | Shared |
| 5556 | Bedroom | OK |
| 5557 | Lounge + Admin | Shared |
| 5559 | Casino | OK |
| 5560 | Gallery | OK |
| 5561 | Warzone | OK |
| 5562 | Realm + Heist | CONFLICT |
| 5563 | NeonCity + CommandCenter | CONFLICT |
| 5564 | Coders | OK |

### Target (no conflicts)
| Port | Scene |
|------|-------|
| 5555 | Phone |
| 5556 | Bedroom |
| 5557 | Lounge |
| 5558 | Admin Panel |
| 5559 | Casino |
| 5560 | Gallery |
| 5561 | Warzone |
| 5562 | Realm |
| 5563 | NeonCity |
| 5564 | Coders |
| 5565 | Heist |
| 5566 | CommandCenter |
| 5567 | Dashboard |
| 5570 | Overlay |

---

## 12. Test Strategy

### Current Coverage
- 1,175 tests passing
- 3 of 11 scenes tested (Realm, NeonCity, Coders via test_scene_routes.py)
- Good unit test coverage for: interceptors, coordinator, pipeline, stream processor,
  skills, tags, LMS client, router, database, events, config

### Target Coverage
- Every scene has route tests (Flask test_client)
- Every scene has state sync tests (stats go through coordinator)
- Every scene has governor integration test (interceptors fire)
- Game logic tests for all game-bearing scenes
- ConversationHeat integration tests
- Cross-scene messaging tests
- End-to-end pipeline tests (request → router → LMS → response → interceptors)

### Test Categories
```
tests/
  test_scene_routes.py       ── all scene HTTP routes
  test_scene_state.py        ── state coordinator per scene
  test_scene_governor.py     ── interceptor pipeline per scene
  test_game_sessions.py      ── game logic (poker, truth/dare, mystery, heist)
  test_heat_integration.py   ── heat → rules → effects
  test_cross_scene.py        ── agent-to-agent messaging
  test_pipeline_e2e.py       ── full inference pipeline
  test_lms_*.py              ── LMStudio integration
  test_*.py                  ── existing unit tests (keep all)
```

---

## 13. Documentation Plan

### Current Docs (15 files in docs/)
Most are reasonably current but reference old patterns. Need updates for:
- Coordinator (not mentioned in any doc)
- ConversationHeat (not in any guide)
- New overlay API endpoints
- Scene migration patterns

### Target Docs
| File | Status | Action |
|------|--------|--------|
| MCP_FRAMEWORK.md | Needs update | Add coordinator, heat, threshold rules |
| MCP_ARCHITECTURE.md | Needs update | Add pipeline, router, resource manager |
| AGENTS_GUIDE.md | Needs update | Add governor flow, interceptor list |
| SKILLS.md | OK | Minor update for new skills |
| LMSTUDIO.md | Needs update | Add v1 API details, router config |
| API.md | Needs update | Add overlay endpoints |
| STRUCTURE_GUIDE.md | Needs update | Reflect current file layout |
| THREE_PILLARS.md | OK | Core philosophy still valid |
| TTS.md | OK | Minor updates |
| ADMIN_GUIDE.md | Needs update | New admin endpoints |
| docs/ProjectNext/ | NEW | This document + component docs |

---

## 14. Long-Horizon Implementation Plan

### Sprint 1: Critical Fixes & Foundation
**Goal:** Fix bugs, ensure baseline stability

1. Fix ResourceManager._load_model() undefined variable
2. Fix PipelineResult.pipeline_started shared timestamp
3. Fix ConfigManager.set() nested dict creation
4. Fix port conflicts in scene configs
5. Remove dead code (empty dirs, unused methods)
6. Clean up bare except:pass blocks in framework.py
7. Run full test suite, verify 1337+ pass

### Sprint 2: Phone Scene Framework Migration
**Goal:** Transform the biggest anti-pattern scene

1. Make _PhoneCharacterAgent use DialogSystem.build_prompt()
2. Accept governance_context from governor (don't override)
3. Route phone character stats through Coordinator
4. Replace _ticker_loop() with MCPTimer
5. Wire ConversationHeat into PhoneSceneInterceptor
6. Add phone scene tests
7. Verify all phone AI goes through governor (no fallback paths)

### Sprint 3: Bedroom Scene Polish
**Goal:** Complete framework integration

1. Replace all direct stat writes with Coordinator.update()
2. Wire InteractionTree phases into DialogDirective
3. Decide: use clothing system or remove it
4. Ensure AgentLoop uses governor exclusively
5. Add bedroom scene tests
6. Test heat-gated content progression

### Sprint 4: Scene-by-Scene Migration (Gallery → Warzone → Realm → NeonCity → Coders → Heist)
**Goal:** Every scene uses Governor + Interceptors

For each scene:
1. Create scene-specific interceptor (if missing)
2. Wrap all LLM calls in AgentGovernor
3. Route state through Coordinator
4. Replace manual threading with MCPTimer
5. Replace hardcoded prompts with DialogSystem
6. Add route + state tests

### Sprint 5: Cross-Scene Features
**Goal:** Activate underused framework features

1. Wire cross-scene messaging through phone scene
2. Wire InteractionTree multi-turn sequences
3. Activate ConversationHeat in ALL governor-wrapped scenes
4. Wire MCPGameSession for all game-bearing scenes
5. Build consequence chains for scene transitions
6. Test cross-scene agent communication

### Sprint 6: Infrastructure & Polish
**Goal:** Production readiness

1. Split cosysim_server.py into domain modules
2. Add comprehensive error handling (replace bare except blocks)
3. Add resource cleanup (SQLite connections, httpx clients)
4. Full documentation update
5. Training pipeline integration test
6. Performance profiling (interceptor overhead, state sync latency)

### Sprint 7: Advanced Features
**Goal:** Unlock dream capabilities

1. Build ConsequenceEngine (unifies rules → effects → state → scheduling)
2. Data-driven scene definitions (YAML/JSON rules, not Python code)
3. Hot-reload scene rules without restart
4. Agent-to-agent conversation (not just message passing)
5. Voice pipeline integration (ASR → LLM → TTS)
6. Mobile interface (phone agent → assistant relay)

---

## 15. File Inventory

### Engine (~28,000 lines)

| Directory | Files | Lines | Purpose |
|-----------|-------|-------|---------|
| engine/mcp/ | 14 | ~14,100 | MCP framework core |
| engine/agents/ | 11 | ~6,085 | Agent subsystem |
| engine/lmstudio/ | 12 | ~6,400 | LMStudio integration |
| engine/pipeline/ | 6 | ~1,420 | Virtual pipeline |
| engine/skills/ | 10 | ~700 | Skill system |
| engine/services/ | 5 | ~960 | Services layer |
| engine/overlay/ | 1 | ~650 | Admin overlay |
| engine/config*.py | 2 | ~330 | Configuration |
| engine/other | ~5 | ~400 | Paths, logging, spatial |

### Content (~15,000 lines estimated)

| Directory | Files | Purpose |
|-----------|-------|---------|
| content/scenes/ | ~40 | All 11 scenes + admin + hub |
| content/simulation/ | ~15 | Database, characters, services |
| content/shared/ | ~3 | Themes, static assets |

### Tests (~9,000 lines estimated)
- 47+ test files
- 1,337 tests passing (Sprint 13)
- Coverage: engine subsystems well-tested, scenes under-tested

### Total Project: ~51,000+ lines of Python

---

*This is a living document. Update as implementation progresses.*
*Each sprint should update the Framework Adoption Matrix (§4) to track progress.*

---

## Sprint 13 Completion Log

**Completed items:**
- ✅ Training pipeline fully wired (dataset generation, auto-train, Colab notebook)
- ✅ NotebookLM MCP integration (5 skills)
- ✅ TTS streaming endpoint added
- ✅ Dead code cleanup pass
- ✅ All 11 scenes now have @skill files (Training Skills ×4, NotebookLM Skills ×5 as built-in packs)
- ✅ 24 interceptors in pipeline (up from 18)
- ✅ 1,337 tests passing (up from 1,175)
