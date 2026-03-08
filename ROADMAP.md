# CosySim Roadmap

> Current: **v0.91b** "THE EVOLUTION" ✅ | Last updated: 2026-03

## Philosophy

CosySim is a **meta-system** — a playground for designing, testing, benchmarking, and evolving AI agent interactions. Every scene is a self-contained experiment combining agents, state, game logic, and UI. The framework exists so that agents (and humans) can methodically explore what works, feed results back into the system, and continuously improve.

The system's ultimate goal: **inhabit itself** — AI agents that maintain, improve, and expand CosySim autonomously, guided by Nexus knowledge, NotebookLM intelligence, and fine-tuned local models.

---

## Current Shipped State: v0.91b — "THE EVOLUTION" ✅

- **v0.89b — THE LOOP** closed the ARGUS → NotebookLM → Nexus distillation loop.
- **v0.90b — THE BASELINE** reconciled all doc surfaces, fixed stale test assertions,
  and committed 145 files of accumulated control-plane, runtime enforcement,
  operator cockpit, and flywheel work as one coherent baseline.
- **v0.91b — THE EVOLUTION** added Lab Break scene, NLM chain-prompting engine,
  LMLink federation, bidirectional LMStudio server control, vision/evaluation
  MCP skills, training pipeline wiring, and template/navbar repairs.
- Current baseline: **20 scenes, 55 scheduler tasks, 9,575 tests passing
  (9,963 total), version 0.91b**.

## Current Planning Focus (2026-03)

The next work should follow the already-started system-first program rather than
the historical pre-0.87 roadmap snapshots below.

The control-plane stabilization tranche is now closed enough to move on:
- shared control-plane truth now drives launcher, hub surfaces, system control,
  intel hub, TUI, and scene health tooling
- the default regression gate is green after the remaining legacy hardcoded
  control-plane URLs were removed
- the first runtime-enforcement tranche is also closed:
  - lounge/casino runtime failures now surface explicit degraded state
  - Canvas push failures no longer pretend success
  - compute-router Copilot routing no longer depends on a hardcoded username

### 1. Keep the developer loop fast while foundation work continues
- Prefer `python scripts\smart_test.py` for diff-based validation during active work.
- Use `python scripts\smart_test.py --smoke` for quick sanity checks and
  `python scripts\smart_test.py --domain <name>` for targeted domain runs.
- Keep the standard repo pytest command as the tranche-closing regression gate,
  but avoid paying the full-suite cost on every iteration.

### 2. Strengthen the Nexus flywheel
- Deepen NotebookLM, ARGUS, and Nexus ingestion/distillation now that the
  control plane and first runtime-enforcement tranche are both closed.
- Focus on reusable Q&A capture, scheduled refresh, and compounding retrieval.
- Current flywheel tranche progress:
  - history notebook ingress is aligned with the real Nexus search/category path
  - deep query-router asks now pass depth through to the NotebookLM-backed route
  - Q&A compounding now distills stored answers and feeds successful generated
    pairs into the training flywheel instead of caching raw entry dumps
  - the dedicated `copilot-system-control` notebook now feeds a recurring
    two-pass control artifact loop that stores Nexus artifacts, creates
    TaskScheduler tasks, and compounds the training flywheel
- Next inside this lane:
  - scheduled/session/news ingress tightening
  - wider deep-query exposure on MCP-facing Nexus tool surfaces where needed
  - flywheel observability and quality metrics

### 3. Continue runtime hardening in follow-on sweeps
- Keep removing silent-success fallbacks from remaining scene/service paths as
  they are discovered.
- Preserve the explicit degraded-state contract added in the current tranche.

### 4. Build richer control surfaces after the foundation holds
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

## Next: v0.78 — "The Data Flywheel"

> v0.78 activates the flywheel: everything that runs collects data, all data gets used
> to train, all training feeds back into production. The system improves on every cycle.

### Track A — Hot-Path Data Collection
- [ ] Wire `DataCollector.collect_tool_call()` into `VirtualAgent.reply()` on every skill call
- [ ] Wire `DataCollector.collect_conversation()` into `DialogSystem.close_conversation()`
- [ ] Wire `DataCollector.collect_grammar_error()` into `InterceptorPipeline` grammar check
- [ ] Wire `DataCollector.collect_output_rating()` into news rating API endpoint
- [ ] Wire `DataCollector.collect_code()` into `coder_skills.coder_fix/coder_complete`

### Track B — First Training Jobs
- [ ] Run `generate_coder.py` — build initial 5,000+ example dataset, verify quality
- [ ] Submit `coder` training job via `CoderPipeline.check_and_train(force=True)`
- [ ] Submit `tool_dispatch` training job (270M Gemma) — 3 epochs
- [ ] Submit `conversational` training job (Qwen 1.7B) — from EventChain data
- [ ] Evaluate all 3 models via `BenchmarkRunner`, auto-promote winners

### Track C — Training Dashboard
- [ ] Admin panel [TRAINING] tab expansion: one card per MODEL_ZOO entry
- [ ] Each card: dataset size, last training run, current benchmark score, status badge
- [ ] "Trigger training" button per model → calls `auto_train.check_and_train_all_zoo()`
- [ ] Live log stream during training (SSE endpoint)
- [ ] Sparkline of benchmark scores over time (last 10 runs)

### Track D — Grammar Scanner Interceptor
- [ ] `engine/agents/interceptors/grammar_scanner_interceptor.py` — post_call, scans for missing
  punctuation, broken symbols, incomplete sentences; logs to DataCollector
- [ ] Register in `config/default.yaml` under `comms.interceptors`
- [ ] Wire results to `grammar_scanner` training dataset
- [ ] 5 tests in `tests/test_grammar_scanner.py`

### Track E — Output Evaluator Loop
- [ ] Auto-score every LLM response via `output_evaluator` model (rule-based until trained)
- [ ] Low-scoring responses flagged in Nexus as `category="improvement"`
- [ ] Flagged responses reviewed by NLM notebook weekly, best fixes stored as training examples
- [ ] Close the loop: output quality rises each week without manual intervention

### Track F — Docs + SYSTEM_AUDIT v0.78b
- [ ] `docs/TRAINING_SYSTEM.md` — full unified training pipeline documentation
- [ ] `docs/CODER_MODEL.md` — coder model strategy, strategies, deployment
- [ ] `CHANGELOG.md` + `SYSTEM_AUDIT.md` updated to v0.78b
- [ ] `config/default.yaml` bumped to `0.78b`

---

## Completed: v0.75 — "NEON CITY" ✅ COMPLETE


---

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
## Completed: v0.81b — "THE LIVING CITY" ✅ COMPLETE

1. **Everything through MCP** — Skills, state, events, and cross-system communication all go through the MCP pipeline
2. **Nexus as truth** — Prompts, rules, configurations, session history, and experiment results live in Nexus
3. **NLM-first** — Research, analysis, and knowledge generation go through NotebookLM (free Gemini) before LMStudio
4. **Local-first** — No cloud dependencies. LMStudio, ChromaDB, ComfyUI, TTS all run locally
5. **Test-driven** — Every feature gets tests. 7,443 passing at v0.71b
6. **Scene independence** — Scenes are self-contained. Adding a scene shouldn't break others
7. **Agent freedom within rails** — Governance pipeline enforces consistency without killing creativity
8. **Profile-aware** — Conversation analyzer builds persistent user profile; all agents use it
9. **Self-improving** — Scheduler runs autonomously: news fetch, QA mining, benchmark cycles, fine-tuning
10. **Voice-first** — Every character speaks. Every input has a mic. TTS/STT on every scene


### v0.50a — Master Consolidation & Nexus Integration
- Unified 13 scenes on BaseScene + MCP pipeline
- 194 MCP skills across 26 packs
- 25-interceptor governance pipeline
- LMStudio v1 API with stateful conversations, branching, streaming
- Nexus knowledge system with ChromaDB, FTS5, plugin hooks
- Session logger, knowledge seeding, experiment framework
- Cross-scene agent state persistence
- Training pipeline Nexus integration

### v0.50b — Nexus Expansion & Scene Polish
- Nexus Q&A distillation cache, Research Manager, YouTube ingestion
- Plugin system with lifecycle hooks
- Scene quality uplift (22 new skills across 5 scenes)
- Experiment framework with 4 skills
- Bedroom v5→v6 (furniture overhaul, director avatar, camera views, room layout)
- Deprecation cleanup (88 warnings → 2 third-party)
- 1,839 tests passing, 263 Nexus tests

### v0.51 — Multi-Model Orchestration & Agent Intelligence ✅
- [x] InferenceOrchestrator — unified facade bridging ModelManager, InferenceRouter, ResourceManager
- [x] Big/small agent routing via tier selection (classify→router, act→gpu_primary, background→cpu_utility)
- [x] JIT model loading with TTL-based eviction (ModelManager JIT_TTL mode with reaper thread)
- [x] Concurrency controls — 6 ResourceManager strategies (SINGLE_BIG, CONCURRENT, MULTI_SMALL, JIT_SWAP, SPECULATIVE, HYBRID)
- [x] Model capability profiles (InferenceConfig + LoadConfig with from_agent_profile/from_yaml)
- [x] Nexus 4-tier query router (Q&A cache → FTS5 → NLM synthesis → deep research)
- [x] Nexus control panel (8-page Streamlit dashboard on :8702)
- [x] URL system — ingestion, chunking, heading extraction
- [x] Config validator — 22-key schema validation with enum + range checks
- [x] 10 Copilot agents (.github/agents/) + 9 instruction files (.github/instructions/)
- [x] 1,903 tests passing

### v0.51b — Sprint 6+7: URL System, llmster, Audit Hardening ✅
- [x] URL manager with heading/chunking patterns for web content ingestion
- [x] llmster CLI bridge — 5 MCP tools wrapping `lms.exe` commands
- [x] 92 MCP tools batch-hardened with try/except error handling
- [x] 3 critical bug fixes (LoadConfig import, duplicate nexus_maintain, hardcoded port)
- [x] 4 YAML sections annotated as RESERVED (stt, security, testing, observability)
- [x] `llm.custom_context` config key for agent context injection
- [x] 5 new test files: lounge (79), gallery (49), games (60), activity_bus (33), resilience (30)
- [x] All 11 scenes migrated to governance framework (build_governance_context + StateCoordinator)
- [x] 144 MCP server tools, 160 MCP skills across 25 packs
- [x] 2,613 tests passing across 75+ files

### v0.52b — Sprint 8: Knowledge Seeding, Tuning, Agent System ✅
- [x] Nexus knowledge dump — 49-model catalog, settings guide, technical findings stored
- [x] Nexus audit rules — structured audit requirements enforced

### v0.53b — Training Pipeline & Metrics ✅
- [x] Training pipeline wiring and metrics collection
- [x] Metrics backup and audit systems

### v0.54b — NLM Intelligence Layer ✅
- [x] NLM Engine, Knowledge Forge, NLM Router (4-tier: cache → FTS → synthesis → deep research)
- [x] Copilot Bridge session hooks
- [x] 10 NLM forge MCP skills
- [x] NLM CLI (16 commands)
- [x] Nexus Control Panel upgrades — 28 new routes, NLM Lab tab
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
