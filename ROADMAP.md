# CosySim Roadmap

> Current: **v0.68** | Last updated: 2026-03-01

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

## Active: v0.69 — "The Living System"

> All the machinery built in v0.68 starts actually running.
> The world ticks. Content generates. The system benchmarks and improves itself.

### Track A: Complete the Living World
- [ ] Wire `world_state` to casino, lounge, tavern, heist, gallery (only neoncity complete)
- [ ] Activate WorldSim daemon in launcher
- [ ] Cross-scene EventBus (arena result → faction shift → lounge gossip)

### Track B: Universal Phone Panel
- [ ] `cosysim-phone-panel.js` — slide-in drawer from any scene via navbar phone button
- [ ] Phone panel CSS + HTML template, included in all 14 scene templates

### Track C: Aria Animated Portrait
- [ ] CSS `@keyframes` states: idle-breathe, talk-pulse, think-blink, listen-glow
- [ ] Mode toggle: floating-widget → messenger → voice-call → full-portrait
- [ ] Wire to VoiceManager events (speaking/done/listening → CSS state classes)

### Track D: Self-Improvement Activation
- [ ] NLM TeacherPipeline → seed ContentEngine pools for all 10 content scenes
- [ ] 10-stage QA distillation cycle → 2,000+ Q&A pairs in Nexus
- [ ] Verify all 27+ scheduler tasks firing; add `world_sim_tick` + `director_tick`

### Track E: Test Isolation Fix
- [ ] `SKILL_REGISTRY.reset()` + conftest autouse fixture
- [ ] Target: 0 failures, 0 errors in full suite (6,679+ clean)

### Track F: Router V3 Finetuning
- [ ] 16-class dataset (2,000+ examples) via TeacherPipeline
- [ ] Finetune Qwen3-0.6B, benchmark, auto-promote if improved

### Track G: Documentation Refresh
- [ ] New docs: WORLD_SYSTEM.md, ECONOMY_GUIDE.md, ARENA_GUIDE.md, CONTENT_GUIDE.md
- [ ] SYSTEM_AUDIT.md v0.68 — honest A++ assessment
- [ ] INDEX.md and ROADMAP.md up to date

### Track H: Scene Intelligence
- [ ] Director scheduler task — SceneDirector.tick() every 5 min per active scene
- [ ] NLM-generated content pools (dialogue, quests, arcs)
- [ ] Cross-scene character travel skeleton

---

## Architecture Principles

1. **Everything through MCP** — Skills, state, events, and cross-system communication all go through the MCP pipeline
2. **Nexus as truth** — Prompts, rules, configurations, session history, and experiment results live in Nexus
3. **NLM-first** — Research, analysis, and knowledge generation go through NotebookLM (free Gemini) before LMStudio
4. **Local-first** — No cloud dependencies. LMStudio, ChromaDB, ComfyUI, TTS all run locally
5. **Test-driven** — Every feature gets tests. Target: 6,000+ tests post-v0.68
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

---

## v0.66 — The Living Loop (Next)

- [ ] **First Finetuning Cycle** — generate router_v2 training data via TeacherPipeline, finetune Qwen3-0.6B as router, benchmark, auto-promote
- [ ] **router-finetune-cycle scheduler task** (28 → 30 tasks) — weekly end-to-end finetuning loop
- [ ] **Conversation Profile Activation** — run ConversationAnalyzer against real session history (lookback_sessions param), bootstrap UserProfileStore with name/prefs/tech stack
- [ ] **Profile API routes** — GET/POST /api/user-profile in Command Center, profile context injection into PhoneAssistant
- [ ] **Master Control Panel redesign** — sidebar navigation, glassmorphism design system, dedicated pages: Assistant (TTS/STT/avatar/mic), Training dashboard (jobs/registry/benchmarks), Knowledge panel (nexus stats/search/notebooks), Profile page, System page
- [ ] **Assistant Panel** — full chat canvas, TTS backend selection (Piper/Orpheus/Qwen3), STT selection (3 backends), file upload, avatar frame (static/animated/video)

### v0.67+ — Advanced Features

**Multi-agent orchestration:**
- [ ] Agent teams with role specialization
- [ ] Debate/consensus protocols
- [ ] Agent-to-agent teaching (knowledge transfer)
- [ ] Emergent behavior detection and logging

**Production readiness:**
- [ ] Scene packaging (export/import scenes as packages)
- [ ] Remote agent support (agents running on different machines)
- [ ] Performance profiling and bottleneck detection
- [ ] Plugin marketplace (share skills, interceptors, scenes)

---

## Architecture Principles

1. **Everything through MCP** — Skills, state, events, and cross-system communication all go through the MCP pipeline
2. **Nexus as truth** — Prompts, rules, configurations, session history, and experiment results live in Nexus
3. **Local-first** — No cloud dependencies. LMStudio, ChromaDB, ComfyUI, TTS all run locally
4. **Test-driven** — Every feature gets tests. Current: 4,827 CosySim tests
5. **Scene independence** — Scenes are self-contained. Adding a scene shouldn't break others
6. **Agent freedom within rails** — Governance pipeline enforces consistency without killing creativity
7. **Nexus-first workflow** — Search Nexus before coding, store decisions after. Audit results always go to Nexus
8. **Profile-aware agents** — Conversation analyzer builds a persistent user profile; agents use it for personalised, context-aware interactions
