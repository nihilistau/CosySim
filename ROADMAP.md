# CosySim Roadmap

> Current: **v0.72** | Last updated: 2026-03-02

## Philosophy

CosySim is a **meta-system** — a playground for designing, testing, benchmarking, and evolving AI agent interactions. Every scene is a self-contained experiment combining agents, state, game logic, and UI. The framework exists so that agents (and humans) can methodically explore what works, feed results back into the system, and continuously improve.

The system's ultimate goal: **inhabit itself** — AI agents that maintain, improve, and expand CosySim autonomously, guided by Nexus knowledge, NotebookLM intelligence, and fine-tuned local models.

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

## Active: v0.72 — "The Living World"

> v0.71 polished the surface. v0.72 makes the world breathe on its own.
> ComfyUI-generated character portraits, NPCs with autonomous schedules,
> persistent player identity across scenes, the router_v3 model serving
> live traffic and growing its own dataset, and Intel Hub as mission control.

### Track A: ComfyUI Character Portraits
- [ ] `engine/art/portrait_generator.py` — `PortraitGenerator` wrapping ComfyUI `/prompt` API
- [ ] Per-character prompt templates stored in Nexus (face, style, background per character)
- [ ] `generate_portrait(character_id, emotion)` skill → ComfyUI → saves to `content/shared/static/img/portraits/{id}_{emotion}.png`
- [ ] Portrait overlay wired to load from file path; CSS gradient fallback if not generated
- [ ] Batch generation skill `generate_all_portraits` — generates all named NPCs at scene start
- [ ] Admin overlay [PORTRAITS] tab — grid of generated portraits, regenerate button
- [ ] `tests/test_portrait_generator.py` — mock ComfyUI API, test prompt building, caching

### Track B: Autonomous NPC Behavior
- [ ] `engine/agents/npc_scheduler.py` — `NPCScheduler` with async tick loop per character
- [ ] NPC tick actions: drift reputation, send ambient message, change scene price, log activity
- [ ] `engine/world/npc_state.py` — per-NPC: location, activity, last_action, schedule
- [ ] WorldSim → NPC state bridge: world events affect NPC mood/activity
- [ ] Scheduler task `npc-world-tick` (every 15 min) → total 37 tasks
- [ ] NPC activity badge in scene UI: pulsing dot when NPC is "doing something"
- [ ] `tests/test_npc_scheduler.py` — tick logic, state transitions, WorldSim bridge

### Track C: Persistent Player Identity
- [ ] `engine/characters/player_profile.py` — `PlayerProfile` singleton, Nexus-backed
- [ ] Tracks: session count, scenes visited, NPCs met, relationship scores, key decisions, reputation summary
- [ ] `player_profile_skills.py` — `get_player_profile`, `update_player_reputation`, `get_relationship_summary`, `record_decision`
- [ ] Admin overlay **[PROFILE]** tab — identity card, relationship web, timeline
- [ ] `RelationshipContextInterceptor` extended to inject player profile summary into every LLM call
- [ ] `tests/test_player_profile.py` — profile CRUD, Nexus persistence, interceptor injection

### Track D: Training Flywheel
- [ ] `engine/lmstudio/router_v3_client.py` — thin wrapper loading trained adapter via ModelRegistry
- [ ] `InferenceRouter` updated to use router_v3 model for routing decisions (fallback to rule_predictor)
- [ ] `RouterDataCollector` weekly export: auto-merge incremental JSONL, trigger `RouterFinetuneCycle`
- [ ] Scheduler tasks `router-data-export` + `router-retrain-cycle` → total **38 tasks** (6 test files updated)
- [ ] Retrain report generated post-cycle: val_loss, sample_count, model_id — stored in Nexus
- [ ] Intel Hub training dashboard: val_loss history chart, dataset size trend, last retrain time
- [ ] `tests/test_training_flywheel.py` — export trigger, retrain cycle, report generation

### Track E: Intel Hub Mission Control
- [ ] `engine/monitoring/metrics_collector.py` — in-process metrics: LLM call latency, error rate, token usage
- [ ] `/api/metrics` on shared blueprint → returns JSON snapshot
- [ ] Intel Hub scene enhanced: live scene health grid (ping all 13 scenes), metrics ticker, training panel
- [ ] World events feed: WorldSim events displayed as news ticker in Intel Hub
- [ ] Scene health badge in navbar_v2.html — green/amber/red dot per scene based on last ping
- [ ] `tests/test_metrics_collector.py` — metric recording, snapshot serialisation

### Track F: Docs + System Audit
- [ ] `docs/WORLD_SYSTEM.md` — WorldSim, WorldEvents, FactionManager, NPC schedules, cross-scene continuity
- [ ] `docs/TRAINING_FLYWHEEL.md` — router_v3 lifecycle: dataset → train → benchmark → promote → serve → collect
- [ ] `docs/PLAYER_IDENTITY.md` — PlayerProfile, relationship web, session persistence
- [ ] `ROADMAP.md` — mark v0.71 complete, update v0.72 as active
- [ ] `docs/SYSTEM_AUDIT.md` — update to v0.72b, reassess grade, update test count + module list

---

## Architecture Principles

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
