# CosySim Roadmap

> Current: **v1.08b** "GAME SYSTEM INTEGRATION" ✅ | Last updated: 2026-03

## Philosophy

CosySim is a **meta-system** — a playground for designing, testing, benchmarking, and evolving AI agent interactions. Every scene is a self-contained experiment combining agents, state, game logic, and UI. The framework exists so that agents (and humans) can methodically explore what works, feed results back into the system, and continuously improve.

The system's ultimate goal: **inhabit itself** — AI agents that maintain, improve, and expand CosySim autonomously, guided by Nexus knowledge, NotebookLM intelligence, and fine-tuned local models.

---

## Current Shipped State: v1.02b — "NEONCITY 2: THE LIVING CITY" ✅

The v1.0 milestone represents a complete overhaul from a loose scene collection
into a unified cyberpunk RPG framework with deep game systems.

**Shipped in this release (8 phases):**
- **Phase 1** — Character neurochemistry (6 neurotransmitters), skill progression
  (8 skills, 6 levels), territory system (16 districts, crew HQ)
- **Phase 2** — Unified neon_base.html template for all 17 scenes with cyberpunk
  aesthetic (glass panels, scan-lines, particle system)
- **Phase 3** — Phone panel CSS/JS rewrite + onboarding quest system (7 quests)
- **Phase 4** — Cyberspace hacking engine (ICE barriers, programs, cyberdecks)
- **Phase 5** — Living world (market economy, NPC routines, faction AI, weather)
- **Phase 6** — Multiplayer foundation (sessions, presence, messaging, leaderboards)
- **Phase 7** — In-game world news system + bottom-of-screen ticker in every scene
- **Phase 8** — Documentation, version, and polish

**Baseline: 20 scenes, 55+ skill packs / ~420 skills, 10,988 tests passing (337 files), v1.07b.**

---

## Shipped: v1.03b — "THE PENTHOUSE UPDATE" ✅

- [x] Penthouse overlay layout — 3D canvas + overlay panels
- [x] 8-tab director panel (Scene, Cast, Dialog, Actions, Scenario, World, Settings, Debug)
- [x] Lab Break survival mechanics — 6 stats, death system, crafting, 30 items
- [x] Phone scene click-blocking fix
- [x] ARGUS LiveDebugger CDP diagnostics toolbox
- [x] Version bump, docs update

---

## Shipped: v1.04b — "SYSTEM INTEGRATION" ✅

- [x] Penthouse LMStudio auth fix — backend proxy for Bearer token
- [x] Character picker overlay modal with personality selection
- [x] Agent loop UI — Start/Stop/Tick with live status indicator
- [x] Model assignment per character
- [x] First-person camera mode — WASD, pointer-lock, room bounds
- [x] YAML-driven penthouse settings
- [x] Smart test runner — 4-tier strategy: Tier 1 in 14s, Tier 2 in 106s vs 20+ min full
- [x] Automated test scheduler with MCP skills
- [x] Pytest markers: unit, integration, slow, scene, browser, nexus, smoke
- [x] Documentation overhaul: 22 files bedroom→penthouse, 3 stubs expanded, 4 system docs updated
- [x] Nexus rules reseeded
- **Tests: 10,988 passing** (330 files, 2,751 in tier-2 suite)

## Shipped: v1.05b — "AUTONOMY SPRINT" ✅

- [x] Priority-based task queue with retry logic and load balancing
- [x] Agent task scheduler with MCP skill integration
- [x] Backup, restore, diagnostics, and auto-heal skills (8 MCP skills)
- [x] Self-recovery workflows for common failure modes
- [x] Versioned prompt templates with expansion and A/B testing (20 built-in)
- [x] Template management MCP skills (5 skills)
- [x] Flask blueprint at `/metrics/dashboard` (cyberpunk glass-morphism UI)
- [x] Real-time system metrics and performance tracking (6 API endpoints)

---

## Shipped: v1.06b — "AAA+++ ANIMATION" ✅

- [x] 55-state animation state machine with procedural bone animation
- [x] 111 built-in poses across 12 categories
- [x] 5-tab Animation Studio UI (Poses, Expressions, Sequences, Library, Models)
- [x] Director avatar with full AnimManager registration and interactive controls
- [x] 6 MCP animation skills for agent-driven animation control
- [x] YAML content system (animations.yaml, interactions.yaml, catalog.yaml)
- [x] Reusable engine/animation/ framework (AnimationConfig, PoseLibrary, ModelCatalog)
- [x] Model browser with search/filter for 21 cataloged models
- [x] Code quality polish (silent exception logging, config constants, validation helpers)
- [x] 128 new tests (14 skill + 114 framework)

---

## Shipped: v1.07b — "PIPELINE INTELLIGENCE" ✅

### NotebookLM Research Pipeline
- [x] Automated topic discovery and source curation (NewsSourceRegistry, 30+ sources, 7 categories)
- [x] NLM-driven knowledge distillation into Nexus (NewsNLMPipeline, 10 distillation questions)
- [x] News ingestion system: fetch → notebook → distill → store (full pipeline with scheduler)
- [x] Code documentation notebooks for implementation guidance (4 bootstrap notebooks)

### Nexus Knowledge Deepening
- [x] Query router NLM-backed deep research tier (5-tier pipeline, tier 4 = direct NLM)
- [x] Automated knowledge freshness checks and stale entry cleanup (per-category TTL, quality scoring)
- [x] Training flywheel: feed all Q&A into fine-tuning pipeline (query router → flywheel wiring)

### Local Agent Autonomy
- [x] Fine-tune local models on CosySim-specific Q&A and code patterns (Unsloth QLoRA orchestrator)
- [x] Agent self-improvement: benchmark → learn → adapt loop (BenchmarkRunner + auto-promotion)
- [x] Router agent: classify tasks → delegate to appropriate model/agent (ContentRouter)

### System Polish
- [x] Scene health monitoring with auto-restart (scene_health_check.py + CDP diagnostics)
- [x] Performance profiling and caching optimization (InterceptorCache + Nexus cache + LMStudio bench)
- [x] Comprehensive integration test suite across all game systems (337 test files, 10,988 tests)

---

## Shipped: v1.08b — "GAME SYSTEM INTEGRATION" ✅

### Game System Integration
- [x] Wire neurochemistry into NPC conversation interceptors (NeurochemistryInterceptor registered, priority 4)
- [x] Hack engine → territory control reward multiplier (up to +50% bonus)
- [x] Custom news publishing from conversations/skills/player actions
- [x] `publish_news` skill for LLM-driven article generation
- [x] `get_character_modifier()` utility for game system neurochemistry queries

### Live Pipeline Validation
- [ ] End-to-end news pipeline run: fetch → NLM distill → Nexus store → training flywheel
- [ ] Bootstrap notebook refresh with live NLM distillation
- [ ] Scheduler daemon live test: verify all 47 tasks fire correctly
- [ ] Training flywheel export and fine-tune dry run

### TUI & Operator Dashboard
- [ ] TUI dashboard enhancements: real-time metrics, task queue display
- [ ] Operator HUD: queue, health, retry/resume, force-complete
- [ ] Multiplayer presence visible in scene UIs

### Runtime Hardening
- [ ] Remove remaining silent-success fallbacks across scenes
- [ ] Add missing error recovery paths in agent loop
- [ ] Nexus server startup reliability improvements

---

## Post-v1.0 Roadmap (2026-Q3+)

### 1. Game System Integration
- Wire neurochemistry into NPC conversation interceptors
- Connect cyberspace to territory control outcomes
- Living world events affect market prices and faction decisions
- Player actions generate news articles visible in ticker
- Multiplayer presence visible in scene UIs

### 2. Advanced NLM Automation
- Architecture research: use NLM to evaluate design alternatives autonomously
- Multi-notebook orchestration for complex research sessions
- NLM-driven code generation with distilled implementation guides
- Automated notebook lifecycle management (create → populate → distill → archive)

### 3. System Evolution
- TUI dashboard enhancements: real-time metrics, task queue display
- Full autonomous operation: local agents maintain system without human input
- Cross-scene interaction and shared world state

### 6. Continue runtime hardening in follow-on sweeps
- Keep removing silent-success fallbacks from remaining scene/service paths as
  they are discovered.
- Preserve the explicit degraded-state contract added in the current tranche.

### 7. Build richer control surfaces after the foundation holds
- The first **operator-cockpit** slice is now in place inside Intel Hub:
  - LAN/mobile-friendly operator console
  - Nexus-backed off-turn inbox ingestion
  - scheduler queue visibility
  - git + live activity visibility
  - live Command Center passthrough hooks
- Next in this lane:
  - broaden from Intel Hub into a fuller cross-device control panel
  - add notifications/ticket ergonomics and deeper command routing
  - keep folding operator notes back into Copilot/Nexus planning automatically
- system-control MCP rewrite
- browser control platform
- assistant interface platform
- scene plugin boundaries

---

## Completed

### v0.50a–v0.65 — Foundation, Integration, Training Pipeline ✅
*(All previous milestones shipped — see CHANGELOG.md for full details)*

**Key milestones:**
- v0.55b: Full 18-scene framework, 188 skills, 21 packs, 4,747 tests, Grade A
- v0.58b: Project Autonomy — scheduler daemon, self-maintenance, autonomous skills
- v0.59b: Connected System — phone, Home Assistant, AnythingLLM, NLM deep storage
- v0.60–v0.63: NLM v2 live API, QA cache pipeline (10-stage, Stages A–J), review sheets
- v0.64: Training pipeline — FinetuneOrchestrator, ModelRegistry, BenchmarkRunner, Intel Hub
- v0.65: Profile system, conversation analyzer, backup manager, 5,582 tests
- v0.66: First finetuning cycle, router_v2 dataset (364 examples), Master Control Panel revamp, 5,609 tests
- v0.67: 26 news sources, category-aware filtering, Intel Hub news UI, 5,695 tests

---

### v0.68 — "Dark Renaissance" ✅ COMPLETE

- [x] Track A: Unified design system — design_tokens.css, cosysim-components.css, cosysim-animations.css, 3D particles
- [x] Track B: Navbar v2, admin loft overlay (8-tab), Aria floating widget
- [x] Track C: VoiceManager JS (Piper/Orpheus/Qwen3 backends, STT), voice settings panel, BaseScene TTS endpoint
- [x] Track D: Aria widget wired to all scenes (portrait placeholder, modes pending v0.69)
- [x] Track E: All 14 scenes revamped with black glass design, scene accents, adult content, BenchHUD
- [x] Track F: 13 engine modules — EventBus, EconomyManager, ContentGate, ContentEngine, CharacterMemory,
      ReputationManager, SceneDirector, ConsequenceStore, InvestigationBoard, SceneArtManager, WorldState, WorldSim, ArenaEngine
- [x] Track G: Arena — THE COLOSSEUM (port 5561): tactical card game, agent betting, NLM commentary
- [x] Track H: BaseScene bench/TTS endpoints, BenchHUD component, Nexus bench tracking
- [x] Track I: NLM content framework wired (seeding pending v0.69)
- [x] Tests: 6,679 passing (up from 4,747)

---

### v0.69 — "The Living System" ✅ COMPLETE

- [x] Track A: World state wired to casino, lounge, tavern, heist, gallery; WorldSim daemon in launcher
- [x] Track B: Universal phone panel (slide-in SIGNAL drawer on every scene via navbar)
- [x] Track C: Aria animated portrait — 4 modes, 4 CSS states, SVG face, voice event wiring
- [x] Track D: ContentEngine seeded, NLM distillation cycle, 34-task scheduler verified
- [x] Track E: Test isolation — 74 failures → **0 failures, 0 errors** (module-scoped singleton reset)
- [x] Track F: Router v3 dataset (2,080 examples, 16 classes), finetune cycle, benchmark runner
- [x] Track G: Docs refreshed — SYSTEM_AUDIT v0.69, INDEX.md, ROADMAP, 4 new guide docs
- [x] Track H: Scene director beats (per-scene BEAT_CONFIGS), cross-scene relay (4 ripple routes), NLM content generator
- [x] Tests: **6,921 passing** (up from 6,679)

---

## Completed: v0.70 — "The Character Web" ✅

- [x] Track A: EconomyManager wired to all 9 scenes (`/api/economy` on every scene); ConsequenceStore UI panel in Tavern, Realm, NeonCity
- [x] Track B: `CharacterMemory` relationship graph (0–100 scores, 5-tier labels); `relationship_skills` pack + `RelationshipContextInterceptor`; NLM backstory + lore seeder
- [x] Track C: Fixed finetune pipeline (`start_job→submit` bug); `router_v3` in `RECOMMENDED_MODELS`; pipeline end-to-end runnable
- [x] Track D: TTS route wiring on all 9 scenes; `cosysim-voice.js` in all templates; global TTS/STT toggle in admin overlay [SYSTEM] tab
- [x] Track E: 3 new guide docs (SCENE_GUIDE, CHARACTER_SYSTEM, FINETUNING_GUIDE); INDEX + SYSTEM_AUDIT updated to v0.69b reality; Grade A+
- [x] Track F: `generate_scene_lore`, `generate_npc_backstory`, `seed_lore_all_scenes`; `scene-lore-seed` weekly scheduler task (total: **35 tasks**)
- [x] Tests: **7,066 passing** (up from 6,921)

---

## Completed: v0.71b — "Full Immersion" ✅

> Made the world unmistakably alive: particle engines, story arcs, dialogue gating, NPC backstories, Nexus admin tabs, push-to-talk STT, ambient audio, and the first model fine-tuned and promoted.

- [x] Track A: Scene visual polish — particles, scene-fx CSS, portrait overlays, 200ms transitions
- [x] Track B: Narrative engine — StoryArcEngine, FactionManager, DailyChallengeManager, 9 arc templates
- [x] Track C: Dialogue & character depth — DialogueGateInterceptor, reputation HUD, VoiceProfileManager, NPC backstories
- [x] Track D: Live finetuning — router_v3 trained (1872 ex, 3 epochs, loss 0.17), promoted to ModelRegistry (model_id 6115d0f2)
- [x] Track E: Nexus admin — [NEXUS]/[KNOWLEDGE] tabs, NexusAwareSkillMixin, NexusContextInjector interceptor
- [x] Track F: Audio immersion — cosysim-stt.js push-to-talk, cosysim-ambient.js procedural audio, 9 scene profiles
- [x] Tests: **7,443 passing**, 25 interceptors, 13 active scenes, 36 scheduler tasks

---

## Active: v0.72 — "The Asset Studio" ✅ COMPLETE

> v0.72 brought the Asset Studio: ComfyUI-powered portrait and video generation,
> NPC autonomous schedules, persistent player identity, router v3 in production,
> real-time metrics, and the full Wan 2.2 GGUF dual-model video pipeline.

- [x] Track A: PortraitGenerator engine — ComfyUI API wrapper, per-character prompt templates, generate/batch/admin skills
- [x] Track B: NPCScheduler + npc_state + NPC activity badge in admin overlay; npc-world-tick scheduler task
- [x] Track C: PlayerProfile singleton (Nexus-backed), PROFILE admin tab, RelationshipContextInterceptor
- [x] Track D: Router v3 production client; training flywheel (router-data-export, router-v3-retrain scheduler tasks)
- [x] Track E: MetricsCollector + /api/metrics; Intel Hub mission control (scene health grid, metrics ticker, training panel)
- [x] Track F: Docs — WORLD_SYSTEM, TRAINING_FLYWHEEL, PLAYER_IDENTITY, SYSTEM_AUDIT v0.72b
- [x] Wan 2.2 GGUF Video System: 15 workflow variants, dual-model architecture, all params exposed
- [x] A++ Tuning System: proven profiles, benchmark runner, Qwen3-VL visual scoring, auto-tuner
- [x] Smart Test Runner: 24-domain git-diff-based selector (scripts/smart_test.py)
- [x] Tests: **7,500+ passing**, 39 scheduler tasks, 15 workflow variants

---

## Active: v0.73b — "The Living Nexus" ✅ COMPLETE

> v0.73b makes the Nexus truly live: curated news intelligence that agents consume,
> scene-integrated asset injection (ComfyUI → scene UI in one click), world event
> cascade propagating WorldSim events to every scene, and Intel Hub as a real
> mission control dashboard with benchmark tracking and news feeds.

- [x] Track A: Scene visual polish — cosysim-scene-fx.css (9 per-scene FX), cosysim-particles.js, portrait overlay, transitions wired to all 9 templates
- [x] Track A1: Inject-to-scene — `/api/inject_to_scene`, UI panel in Images/Portraits, scene selector dropdown
- [x] Track B: News pipeline — `engine/nexus/news/` (12 RSS sources, 4 categories, dedup, NLM), 28 tests
- [x] Track B2: Intel Hub news ticker + Phone news feed — `/api/news/ticker`, `/api/news/feed`, scrolling bar
- [x] Track C: Intel Hub benchmark dashboard — `/api/benchmark/workflows|run|trend`, SVG sparklines, score cards
- [x] Track D: Nexus seeded — 32 new entries, 4 Q&A pairs, 310 dupes removed, session log stored
- [x] Track E: `engine/world/event_cascade.py` — WorldSim→scene fan-out, 3-tier delivery, 41 tests
- [x] Track F: ASSET_STUDIO.md, NEWS_SYSTEM.md, SYSTEM_AUDIT v0.73b (grade A++), CHANGELOG, README, ROADMAP
- [x] Tests: **7,500+ passing**, 39 scheduler tasks, 15 workflow variants, system audit **A++**

---

## Active: v0.77b — "The First Mind" ✅ COMPLETE

> v0.77b builds the full unified training system: a coder pipeline (10 strategies, 5000+ examples),
> voice acoustic fine-tuning, conversation model training, NLM notebook-backed news distillation,
> news rating signal, and 4 new scheduler tasks. The system can now train all model types
> from automatically collected data.

- [x] Track A: Finetune status panel in Intel Hub — `/api/finetune/status`, job cards, 30s refresh
- [x] Track A2: News skills — `summarize_news_category()` 300-word digest
- [x] Track B: News rating signal — thumbs up/down → `news_ratings.jsonl` → `output_evaluator` training
- [x] Track B2: Live world-events ticker in Intel Hub (real-time WorldSim events)
- [x] Track C: Unified training system — ModelZoo (14 types), DataCollector, VoiceTrainer, ConversationTrainer
- [x] Track C2: Coder pipeline — 10 generation strategies, `coder_pipeline.py`, 8 @skill tools
- [x] Track C3: Micro-datasets expanded — 5 new model types
- [x] Track D: NLM news pipeline — 4 real notebook IDs, article digest injection, 5 Q&A per cycle
- [x] Scheduler: 39 → 44 tasks (collect-flush, model-zoo-train, voice-auto-train, coder-dataset-refresh)
- [x] 7 new test files, all 6 count-assertion files updated
- [x] Tests: **~8,700+ passing**, 44 scheduler tasks, 15 scenes

---

## v0.78 — "The Data Flywheel" (Rolled into v0.79b–v0.91b)

> The v0.78 items were absorbed into the subsequent version sprints rather than
> shipping as a standalone release. DataCollector wiring, training dashboard,
> grammar scanning, and output evaluation were built incrementally across
> v0.79b–v0.91b as supporting infrastructure matured.

---

## Completed: v0.75 — "NEON CITY" ✅ COMPLETE

## Completed: v0.80b — "THE COPILOT LAYER" ✅ COMPLETE

- GitHub Copilot Internal API — 26 frontier models, auto-refresh token, SSE streaming
- ComputeRouter: tunnel → copilot → lmstudio priority chain
- Nexus Canvas CopilotPanel, 9 @skill tools, 8,811 tests

---

## Completed: v0.81b — "THE LIVING CITY" ✅ COMPLETE

- InventoryManager (engine/world/inventory.py): 25 catalog items, 10 categories, 14 slots, 7 skills
- CrewManager (engine/world/crew.py): 9 roles, loyalty, XP/5-level, 6 operation types, 8 skills
- HUD v2: glass slide panels, phone overlay iframe, world announcer (5 stations, 7 badges)
- PlayerState expanded: health/hunger/energy/skills/implants, inventory + crew snapshots
- Relationship types: 12 types, auto-upgrade, protected types, 4 new skills
- socket.io CDN → local fix across all 24+ scene templates
- 50 new tests; ~7,800+ total passing

---

## Completed: v0.82b — "THE OPEN WORLD" ✅ COMPLETE

> v0.82b opens the simulation up: multi-scene player traversal, a persistent city map, NPC
> schedules visible across scenes, a full mission system, a live world announcer, and the
> Intel Hub CITY PULSE panel.

### Track A — City Map & Multi-Scene Traversal ✅
- [x] `engine/world/city_map.py` — CityMap singleton, 16 nodes, 6 districts, 24 bidirectional edges, BFS pathfinding
- [x] `engine/skills/builtin/city_skills.py` — 8 @skill tools (city pack)
- [x] `base_scene.register_city_route()` — 7 REST endpoints
- [x] PlayerState extensions: `spend_energy`, `add_heat`, `adjust_reputation`, `adjust_faction`, `add_xp`, `active_location`
- [x] `tests/test_city_map.py` — 35 tests passing

### Track B — Cross-Scene NPC Presence ✅
- [x] `NPCScheduler._track_npc_in_city_map()` — called every tick, updates city map NPC positions
- [x] `npc_location` Socket.IO event emitted only on location change
- [x] `tests/test_npc_scheduler_location.py` — 6 tests passing

### Track C — Mission System ✅
- [x] `engine/world/mission.py` — MissionManager, 15 builtin missions, 5 types, objectives, rewards
- [x] `engine/skills/builtin/mission_skills.py` — 9 @skill tools (mission pack)
- [x] `base_scene.register_mission_route()` — 10 REST endpoints
- [x] `tests/test_mission.py` — 55 tests passing

### Track D — World Events Feed ✅
- [x] `engine/world/world_announcer.py` — WorldAnnouncer, 50-event ring buffer, EventBus subscriptions, station muting
- [x] `engine/skills/builtin/announcer_skills.py` — 5 @skill tools (announcer pack)
- [x] `base_scene.register_world_events_route()` — 3 REST endpoints
- [x] Intel Hub CITY PULSE panel — full-width, category filters, live Socket.IO injection via `city_pulse`
- [x] `tests/test_announcer.py` — 17 tests passing

### Test Suite Overhaul ✅
- [x] pytest-xdist `-n auto`: **30 min → 6 min** (8,327 tests, 0 failures)
- [x] Two-tier: `slow` + `integration` markers; default run skips them
- [x] 7 incompatible fastmcp files excluded from default run

### Track E — Docs + Audit v0.82b ✅
- [x] `docs/WORLD_SYSTEM.md` — complete open world system documentation
- [x] `SYSTEM_AUDIT.md` — v0.82b section (Grade A++)
- [x] CHANGELOG + ROADMAP finalized

- **Tests: 8,327+ passing**, 0 failures

---
## Completed: v0.83b — "THE SOCIAL LAYER" ✅ COMPLETE

- **Shop System** — `InventoryManager.get_catalog()`, `buy_item()`, `sell_item()`; 5 REST endpoints; 26 ITEM_CATALOG entries with prices
- **Shop Modal UI** — `content/shared/templates/shop_modal.html`, `cosysim-shop.css`, `cosysim-shop.js`; `window.CosyShop.open()` API
- **Crew HUD** — loyalty bars, trust tier stars, role icons in right HUD panel
- **NeonCity HUD fix** — Jinja2 ChoiceLoader for shared templates
- **Tests: 8,380+ passing**, 0 failures

---
## Completed: v0.84b — "THE HINDSIGHT LAYER" ✅ COMPLETE

> Project Hindsight: full architectural refactoring — DDD, Pydantic models, interceptor auto-registry.
> Grade upgraded from B+ → A++.

- **`@mcp_tool` decorator** — unified error handling, auto JSON serialisation, `ToolExecutionError`
- **Domain tool modules** — 43 files in `engine/mcp/tools/`, servers slimmed to thin wrappers
- **Interceptor auto-registry** — 26 individual modules, `@register_interceptor`, `INTERCEPTOR_CACHE`
- **Pydantic Nexus models** — 14 typed models in `engine/nexus/models.py` with `_DictCompat`
- **Typed NexusClient** — all methods return `NexusEntry`/`NexusRule`; 3 domain sub-clients
- **Engine-wide cleanup** — all raw `requests.*` Nexus HTTP replaced; 0 bare except in tool layer
- **Tests: 8,771 passing**, 0 failures

---
## Completed: v0.85b — "THE MAINTENANCE LAYER" ✅ COMPLETE

> The system begins taking care of itself. Google auth is auto-renewed via CDP.
> Test regressions are tracked. The Nexus bridge CLI works. The project has a journal.

- **`scripts/har_capture.py`** — CDP cookie capture: connects to running Chrome port 9222, `Network.getCookies()`, ~1s, zero UI. Falls back to launch/macro if needed.
- **`scripts/har_watchfolder.py`** — drop-folder auto-importer (30s poll, `imported/`/`failed/` dirs)
- **`GoogleAccountPool`** — `cookie_age_days()`, `is_stale()`, `get_stale_accounts()`, `get_available_accounts()`
- **Scheduler #48** `cookie-health-check` (daily) — probes NLM/Colab, Nexus alert if stale
- **Scheduler #49** `cookie-auto-refresh` (every 72h) — silent CDP refresh, no user action needed
- **Scheduler #50** `test-suite-benchmark` (weekly) — times full pytest suite, logs to Nexus, warns on >20% regression
- **`google_accounts` skill pack** — 4 skills: `cookie_status`, `har_import`, `cookie_probe`, `har_watchfolder_start`
- **Nexus bridge CLI** — `_parse_entry`/`_parse_rule` fixed for JSON-string DB fields; fully operational
- **`docs/PROJECT_JOURNAL.md`** — 5,000+ word project narrative (17 chapters, v0.51b→v0.84b)
- **Tests: 8,811+ passing**, 50 scheduler tasks

---
## Completed: v0.86b — "THE RECON LAYER" ✅ COMPLETE

> ARGUS comes online. CosySim now has eyes inside Google's infrastructure.
> The ARGUS console toolkit provides live DOM scanning, JS eval, and direct
> CDP token harvesting — replacing manual HAR exports permanently.

### ARGUS — Automated Reconnaissance & Google Universal Surveyor ✅
- [x] 19-file API intelligence platform (`scripts/argus/`) — crawlers, decoders, discovery, reporting
- [x] CDP bridge, network monitor, batchexecute/gRPC-web decoders
- [x] NLM/Gemini/AI Studio crawlers + endpoint registry
- [x] rpcid detector, feature flag prober, proto reconstructor
- [x] Nexus sink — all discoveries stored as Nexus entries (category: argus)
- [x] Scheduler tasks 51+52: `argus-weekly-scan`, `argus-diff-report`

### ARGUS Console Toolkit (`scripts/argus/tools/`) ✅
- [x] `selector_scanner.py` — live DOM scan → unique CSS selectors, saves JSON
- [x] `token_harvester.py` — CDP cookie harvest → pool.json, SAPISIDHASH generation
- [x] `console_eval.py` — JS REPL + 10 built-in helpers (buttons, inputs, cookies, etc.)
- [x] `__main__.py` — unified CLI: `python -m scripts.argus.tools <tabs|scan|eval|tokens|snap|watch|repl>`
- [x] Token refresh flow wired into `cookie-auto-refresh` scheduler task (prefers ARGUS harvester)
- [x] 19 tests in `tests/test_argus_tools.py` — all passing

### Documentation ✅
- [x] `docs/ARGUS.md` — complete ARGUS system reference

- **Tests: 8,830+ passing**, 52 scheduler tasks

---
## Completed: v0.87b — "THE KNOWLEDGE LAYER" ✅ COMPLETE

- GAS SDK fully mapped with V8 heap + HAR replay evidence
- ARGUS gold artifact analysis completed with evidence classification
- `heap_analyzer.py` and `protocol_monitor_parser.py` shipped with test coverage
- `scripts/nlm_qa_seeder.py` added the first dedicated NLM Q&A seeding loop

## Completed: v0.88b — "THE SDK LAYER" ✅ COMPLETE

- All 5 Google service SDKs brought to 100% coverage against the ARGUS registry
- 110+ client methods implemented across AI Studio, NLM, GAS, Gemini, and Sheets
- HAR scanner added for recursive rpcid discovery/reporting

## Completed: v0.89b — "THE LOOP" ✅ COMPLETE

- ARGUS discoveries now flow into NotebookLM and back into Nexus automatically
- Weekly `argus-nlm-distil` scheduler task closes the research → distillation → reuse loop
- History mirror fixes carried forward to keep ARGUS agent conversations durable

---
## Completed: v0.50a–v0.54b — Early Foundation ✅

*(Master consolidation, Nexus integration, multi-model orchestration, NLM intelligence.
See CHANGELOG.md for full details.)*
- [x] HAR extractor for NotebookLM

### v0.55b — Full-Project Audit & Hardening ✅
- [x] 3,521 tests passing (was ~3,012), 0 failures
- [x] ResourceManager deadlock fix (Lock → RLock)
- [x] Router training data capture system for 270M model fine-tuning
- [x] Bedroom scene mixin refactor (2,610 → 1,300 lines) — combat, dialog, inventory, social
- [x] Frontend polish — 30s timeout, toast notifications, button guards
- [x] Config hardening — all 18 scenes in production.yaml
- [x] unittest → pytest migration
- [x] Project grade: A- (was B+)

### v0.56b — Games, Coders & Scene Expansion ✅
- [x] Games scene — GameMaster with Socket.IO real-time play
- [x] Coders scene — session persistence and coding sandbox
- [x] 3,617 tests across 80+ files

### v0.57b — System Assistant & Navigation ✅
- [x] System Assistant Aria (`engine/assistant/`)
- [x] cosysim-navbar.js — floating nav bar auto-injected via shared assets
- [x] Flask hub (`hub_flask.py` on :8500) replacing Streamlit
- [x] 3,747 tests across 85+ files

### v0.58b — Project Autonomy: Self-Improving System ✅
- [x] Scheduler daemon for autonomous task execution
- [x] Self-maintenance module (health, dedup, compaction, scoring)
- [x] Autonomous skill pack (67 skills for agent self-management)
- [x] Local agent guide and onboarding documentation

### v0.59b — Connected System: Phone, HA & Deep Storage ✅
- [x] Phone news feed with user feedback loop
- [x] Home Assistant integration (11 MCP tools, safety governance)
- [x] NLM deep storage (3-tier notebook archival, HAR extraction)
- [x] Phone assistant with 4-tier cascade routing
- [x] System dashboard app (overview, agents, scheduler, chat)
- [x] AnythingLLM integration (multi-instance, bidirectional Nexus sync)
- [x] Central CORS for all scenes, health routes on all 18 scenes
- [x] Nexus Panel fixes (dashboard stats, entry clicks, HAR timeout, switchTab)
- [x] Three.js character rendering fixes (buildHead return type, defensive guards)
- [x] 188 skills across 21 packs, 214 MCP server tools
- [x] 4,747 tests across 176 files

### v0.60 — NLM v2: Live Write API, CDP Auth & QA Distiller ✅
- [x] NLM batchexecute write RPCs: CYK0Xb (ask), ciyUvf (generate doc), R7cb6c (save note)
- [x] Multi-question batching — 5 questions per HTTP request
- [x] Chrome CDP automated cookie capture (`engine/nexus/nlm_har_capture.py`)
- [x] Build label (bl) + f.sid management via `data/nlm_meta.json`
- [x] NLM QA Distiller — 75 topic questions → Nexus expansion
- [x] 7 new NLM live skills in autonomy pack
- [x] Comprehensive NLM SDK documentation (`docs/NOTEBOOKLM_SDK.md`)
- [x] 195 skills across 21 packs, 4,800 tests

### v0.60.1 — Bug Fixes, NLM v2.1, HAR Ingestion ✅
- [x] NLM v2.1: 18 fully catalogued RPCs with response schemas
- [x] Configure Chat API — set conversation goals, roles, response length per notebook
- [x] Source management RPCs: list, rename, delete, get content
- [x] NLM proxy auto-start (`config/launcher.yaml`) with bl staleness detection
- [x] HAR ingestion background thread — no timeout on large files, polling progress
- [x] Fixed command_center and heist scenes (incorrect `scene_name` kwarg)
- [x] Fixed nexus bridge `seed` command (function-based API, no class)
- [x] 4,827 tests across 176 files

### v0.61 — Copilot-Nexus Deep Integration ✅
- [x] Session→Nexus sync (`sync_sessions_to_nexus.py`) — 8 historical sessions seeded
- [x] NLM session distillation pipeline (`session_distillation.py`) — daily scheduler task
- [x] Copilot governance gate (`consensus_gate`) — architecture change enforcement
- [x] Copilot memory structure — `get_onboarding_context()`, `get_decision_history()`
- [x] NLM hybrid media skills — `nlm_audio`, `nlm_video`, `nlm_data_tables`, `nlm_chat_history`
- [x] NLM user plan API — `/user/plan` and `/user/queries` endpoints
- [x] Hooks upgrade — onboarding context on sessionStart, compact on preCompaction
- [x] Nexus copilot namespace extended — history, decisions, plans, micro-versions, rules
- [x] Scheduler: 17 builtin tasks (was 16)
- [x] 5,133 tests across 178 files

### v0.62 — NLM QA Cache Pipeline ✅
- [x] NLM-driven Q&A cache pipeline — 10-stage orchestrator (history_miner, source_pyramid, consumer_briefing, review_sheet)
- [x] HistoryMiner — 10 themed session history dumps for NLM source loading
- [x] SourcePyramid — 6-layer meta-document system shaping all generation tiles
- [x] ConsumerBriefing — living query taxonomy for 5 consumer classes
- [x] ReviewSheet — openpyxl Excel output with formulas, dropdowns, conditional formatting
- [x] CachePipeline — Stages A–J with CSV/code-exec/data-table Gemini output modes
- [x] 23 scheduler tasks (+ qa-history-mine, qa-cache-prune)
- [x] 4 MCP cache tools + 2 autonomy skills
- [x] 5,437 tests across 183 files

### v0.63 — NLM QA Cache Enhancements ✅
- [x] QA pair expander with deduplication and batch processing
- [x] Cache pipeline bug fixes and rate-limit handling
- [x] Master notebook builder for cross-session knowledge synthesis
- [x] 5,437 tests

### v0.64 — Training Pipeline + Intelligence Hub ✅
- [x] **NLM Teacher Pipeline** (`engine/nexus/teacher_pipeline.py`) — Gemini 3.0 generates per-type JSONL datasets for 5 micro-model types
- [x] **MicroDatasetManager** (`training/micro_datasets.py`) — augmentation, dedup, Alpaca formatting, 80/10/10 splits
- [x] **FinetuneOrchestrator** (`training/finetune_orchestrator.py`) — Unsloth QLoRA subprocess runner with live progress tracking, LoRA merge
- [x] **ModelRegistry** (`training/model_registry.py`) — tracks all fine-tuned models, benchmark scores, auto-promotion
- [x] **BenchmarkRunner** (`training/benchmark_runner.py`) — accuracy/F1/exact-match, rule-based baseline, auto-promote on improvement
- [x] **FinetunedRouter** (`engine/lmstudio/finetuned_router.py`) — routes task requests to local fine-tuned models; Stage F integration
- [x] **Intel Hub Scene** (`:5580`) — glassmorphism admin panel, 12 sections: Nexus Explorer, NLM Lab, Fine-tune Lab, Scheduler, Copilot Rules, Cache Pipeline, Model Registry, Backups, Conversation Analyzer, User Profile, TTS/VTT config, assistant chat
- [x] **Scheduler distillation loop** — 4 new tasks: teacher-dataset-gen, finetune-if-ready, model-benchmark, backup-databases (27 total)
- [x] **Cache pipeline Stage F** — tries fine-tuned evaluator first, falls back to NLM Gemini batch evaluation
- [x] **18 new MCP tools** in devtools_server.py for training pipeline control
- [x] 5,505 tests across 183 files

### v0.65 — Profile Skills, Conversation Analyzer, Backup Manager ✅ ← CURRENT
- [x] **Profile Skills Pack** (`engine/skills/builtin/profile_skills.py`) — 11 new MCP skills across 3 groups: conversation analysis, user profile, backups
- [x] **Scheduler Task #28** — `conversation-analyze` daily task: analyzes recent Copilot session turns, stores facts/preferences/tech background to UserProfileStore + Nexus
- [x] **Training Smoke Test** (`training/smoke_test.py`) — 8-check end-to-end pipeline validation without GPU
- [x] 57 new tests: `test_conversation_analyzer.py`, `test_backup_manager.py`, `test_profile_skills.py`
- [x] 28 scheduler builtin tasks, 206 skills across 22 packs
- [x] 5,582 tests across 186 files

*(v0.66–v0.68 details above in Completed section)*

---
