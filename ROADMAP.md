# CosySim Roadmap

> Current: **v1.28** "UNIFIED MODULAR MONITORING" ✅ | Last updated: 2026-07

## Philosophy

CosySim is a **meta-system** — a playground for designing, testing, benchmarking, and evolving AI agent interactions. Every scene is a self-contained experiment combining agents, state, game logic, and UI. The framework exists so that agents (and humans) can methodically explore what works, feed results back into the system, and continuously improve.

The system's ultimate goal: **inhabit itself** — AI agents that maintain, improve, and expand CosySim autonomously, guided by Nexus knowledge, NotebookLM intelligence, and fine-tuned local models.

---

## Current Shipped State: v1.28 — "UNIFIED MODULAR MONITORING" ✅

**Baseline: 20 scenes, 68 scheduler tasks, 81+ workspace/NLM/monitoring skills, 12,458+ tests, 31 pipeline stages, 35 templates, 302 API ops across 34+ YAML sections, 7 MetaMetrics categories (55+ metrics), 10 process monitor skills, 14 monitoring skills.**

v1.28 adds a complete unified modular monitoring system: PackTracker for skill
pack execution tracking with PID/CPU cross-referencing, AnomalyDetector with
z-score/IQR/MAD statistical detection, CorrelationEngine for Pearson/Spearman
metric correlation analysis, TrendPredictor with linear regression forecasting,
AlertRouter for severity-based alert routing with escalation chains,
UnifiedMonitor as the top-level orchestrator facade, UnifiedDashboard with
time-range queries and widget data, 14 MCP monitoring skills, and 453 tests.
Closes 5 of 7 HIGH/CRITICAL gaps from the gap analysis.

---

## Shipped: v1.28 — "UNIFIED MODULAR MONITORING" ✅
- [x] `engine/observability/pack_tracker.py` — PackTracker singleton: skill pack execution tracking, PID/CPU cross-referencing, hourly rollups, SkillRegistry hook
- [x] `engine/observability/anomaly_detector.py` — AnomalyDetector: z-score, IQR, MAD methods with configurable thresholds, SQLite persistence
- [x] `engine/observability/correlation_engine.py` — CorrelationEngine: Pearson/Spearman correlation analysis with significance testing
- [x] `engine/observability/trend_predictor.py` — TrendPredictor: linear regression forecasting with background analysis thread
- [x] `engine/observability/alert_router.py` — AlertRouter: severity-based routing with escalation chains, suppression windows, routing rules
- [x] `engine/observability/unified_monitor.py` — UnifiedMonitor: top-level orchestrator facade composing all 3 existing layers + 5 new modules
- [x] `engine/observability/unified_dashboard.py` — UnifiedDashboard: dashboard API with time-range queries, widget data, period comparison
- [x] `engine/skills/builtin/monitoring_skills.py` — 14 @skill(pack="monitoring") MCP skills for agent access
- [x] `engine/observability/__init__.py` — Updated with 15 class + 9 singleton exports
- [x] 7 scheduler tasks registered for monitoring modules
- [x] Fix news_pipeline test categories (ai_research→ai_ml, tech→science)
- [x] Update 7 scheduler count assertions (61→67/68) for new monitoring tasks
- [x] 453/453 new tests passing across 8 test files

---

## Shipped: v1.27 — "SYSTEM PROCESS MONITOR" ✅

- [x] `engine/system/` package — ProcessMonitor, ProcessInfo, GitOperation, TrackedOperation, StallInfo
- [x] Category classification — 12 categories via name + cmdline pattern matching
- [x] Git operation detection — push/pull/fetch/clone/gc/repack from cmdline patterns
- [x] Stall detection — dual-sample CPU measurement, stalled/slow/active verdicts
- [x] Tracked operations — manual tracking with PID sets, metadata, elapsed time
- [x] System snapshots — CPU, memory, disk, GPU, processes, git ops, tracked ops, top consumers
- [x] CLI: `python -m engine.system` with 10+ flags
- [x] 10 MCP skills for agent access
- [x] MetricsDB: `process_snapshots` table + 3 methods
- [x] MetricsCollector: `_collect_processes()` wired into tick loop + 3 AlertRules
- [x] Alert routing: process/worker/stall → "process" node
- [x] 3 scheduler tasks: snapshot (5min), git check (2min), stall detection (10min)
- [x] Config: `observability.process_monitoring` section
- [x] 48/48 tests passing

---

## Shipped: v1.26 — "PIPELINE ENGINE v2" ✅

**Baseline: 20 scenes, 64 scheduler tasks, 67+ workspace/NLM skills, 11,843+ tests, 31 pipeline stages, 35 templates, 302 API ops across 34+ YAML sections, 7 MetaMetrics categories (55+ metrics).**

v1.26 adds a full meta-stage engine to WorkspacePipeline: retry/backoff with
exponential/linear strategies, conditional branching (if/then/else with 10+
operators), parallel branch execution, for-each iteration with optional
parallelism, sub-pipeline composition, and context validation — all dispatched
through a unified `_dispatch_stage()` router.

---

## Shipped: v1.26 — "PIPELINE ENGINE v2" ✅

- [x] `_dispatch_stage()` — unified router for all stage types (normal + 4 meta-stage types)
- [x] Retry/backoff: configurable max retries, exponential/linear backoff, fallback executors
- [x] Conditional branching: `if/then/else` with `_evaluate_condition()` supporting 10+ operators
- [x] Parallel execution: `ThreadPoolExecutor`-based branch isolation with merge strategies (all/first/concat)
- [x] For-each iteration: collection iteration with `max_items` cap, optional parallel execution
- [x] Sub-pipeline composition: `run_pipeline` stages that recursively call `run()` with template lookup
- [x] Context validation: `input_requires` pre-check with optional stage skip
- [x] `_stage_label()` for human-readable meta-stage naming in logs and templates
- [x] `_cast_value()` for auto-casting condition operands (int, float, bool, null)
- [x] Refactored `run()` to use `_dispatch_stage()` instead of inline stage loop
- [x] 155/155 pipeline tests passing (88 existing + 67 new v2 tests)

---

## Shipped: v1.25 — "NEWS PIPELINE HARDENING" ✅

- [x] Embedding service returns `[]` instead of raising RuntimeError when all providers fail
- [x] Added `check_all_feeds()` to RSSFetcher — probes all sources, auto-trips circuit-breaker, emits meta-metrics
- [x] Staggered news scheduler intervals: fetch 8h, distill 6h, retry 12h, feed-health 12h
- [x] Registered `feed-health` scheduler task (every 12h)
- [x] Added NLM notebook existence validation in distill callback — skips with warning if notebook not found
- [x] 211/211 focused tests passing

---

## Shipped: v1.24 — "FEED HEALTH & RESILIENCE" ✅

- [x] Replaced 4 dead RSS feeds: Reuters→Guardian World, AP News→NPR, Changelog→HN Best, Python Insider→blog.python.org
- [x] Added `_nexus_reachable()` TCP check (2s timeout) to news pipeline
- [x] Guarded `store_items_to_nexus`, `store_qa_to_nexus`, `get_latest_digest` with reachability check
- [x] Live end-to-end validation: 32 items fetched and stored across 8 categories
- [x] 211/211 focused tests passing

## Shipped: v1.23 — "NEWS SYSTEM CONSOLIDATION" ✅

- [x] Fixed critical category mismatch bug between news fetch and distillation
- [x] Added YAML-driven distillation config: category_mapping (8→4), curated questions (5×4), NLM notebook UUIDs
- [x] Added "world" category with 3 RSS sources (Reuters, BBC World, AP News)
- [x] Removed all hardcoded NEWS_SOURCES_BY_CATEGORY and CURATED_QUESTIONS dicts
- [x] Added ~10 new registry methods to NewsSourceRegistry
- [x] Rewired scheduler callback, news skills, and NLM pipeline to use YAML config
- [x] 211/211 focused tests pass

---

## Shipped: v1.22 — "NLM gRPC METHODS" ✅

- [x] Generic `_grpc_call()` transport layer with retry, CDP refresh, graceful 404 handling
- [x] 3-strategy `_parse_grpc_response()` parser (wrb.fr → raw JSON → raw text)
- [x] 24 public methods across 8 categories (Artifacts, Sources, Projects, Chat, Notes, Account, Moderation, Suggestions)
- [x] 14 @skill(pack="nlm_grpc") MCP skills
- [x] 24 GRPC_* constants and 14 /api/grpc/* Flask routes in proxy
- [x] YAML registry expanded to 302 operations (version 5.0)
- [x] 211/211 focused tests pass

---

## Shipped: v1.21c — "DEEP HAR ENRICHMENT" ✅

- [x] Parsed 5 new HAR/JS/WASM files: NLM gold (11 rpcids), Sheets Gemini (14 streamGenerate), postshellbase (446 methods), gbar toolbar, calcworker WASM
- [x] YAML expansion: 95 AI Studio methods, 12 AppletControl methods, 5 workspace gRPC services
- [x] HAR enrichment: streamGenerate templates, gRPC endpoint, BigQuery ops, Sheets REST, JS modules
- [x] Registry: 302 operations across 34+ top-level sections

---

## Shipped: v1.21b — "AI STUDIO + APPS SCRIPT WIRING" ✅

- [x] Apps Script batchexecute client (14 operations, ~730 lines)
- [x] 22 AI Studio proxy routes in nlm_live_proxy.py
- [x] 10 Apps Script proxy routes in nlm_live_proxy.py
- [x] 13 AI Studio MCP skills (workspace_aistudio_*)
- [x] 7 Apps Script MCP skills (workspace_appscript_*)
- [x] 7 pipeline stages (24→31), 10 pipeline templates (25→35)
- [x] 72 appscript client tests + pipeline test assertions updated
- [x] All 237 targeted tests pass

---

## Shipped: v1.21a — "YAML REGISTRY EXPANSION" ✅

- [x] HAR mining tools: v121_har_extract.py, v121_payload_extractor.py, v121_yaml_expand.py
- [x] YAML registry expansion 3216→3624 lines (version 5.0)
- [x] Apps Script section: 14 batchexecute rpcids with payload templates
- [x] NLM gRPC section: 2 service methods
- [x] NLM heap-discovered section: 24 methods from heap analysis
- [x] All 77 registry tests pass

---

## Shipped: v1.20b — "SYSTEM BENCHMARKING & SELF-IMPROVEMENT" ✅

- [x] `flush_to_meta_metrics()` bridges benchmark.py → MetaMetrics SQLite (10 metrics)
- [x] BENCHMARK_METRICS category (10 metrics) in MetaMetrics, dashboard 5→7 sections
- [x] `collect_benchmark_metrics()` wired into `collect_all()` pipeline
- [x] `auto_repair()` in copilot_validation.py with drift classification → sync routing
- [x] `benchmark-flush` scheduler task (every 5 min)
- [x] `copilot-auto-repair` scheduler task (daily)
- [x] 23 new tests (11 benchmark + 12 auto-repair), all pass
- [x] Full suite green

---

## Shipped: v1.20a — "NEWS INTELLIGENCE HARDENING" ✅

- [x] DedupFilter rewritten with SQLite persistence (data/news_dedup.db)
- [x] RSSFetcher rewritten with retry (3 attempts, exponential backoff)
- [x] Circuit breaker (5 failures → skip, 1hr auto-reset)
- [x] Per-source health tracking (_SourceHealth class)
- [x] NEWS_METRICS category (13 metrics) added to MetaMetrics
- [x] Full metrics wiring in NewsPipeline (fetch/dedup/store/cycle)
- [x] 31 news pipeline tests, all pass (was 7)
- [x] Full suite green

---

## Shipped: v1.19c — "COLAB PIPELINE INTEGRATION" ✅

- [x] 3 new Colab pipeline stages (colab_execute, colab_ask, colab_build)
- [x] 4 new Colab pipeline templates (research_and_compute, data_analysis, nlm_colab_loop, colab_build_and_store)
- [x] 4 new Colab MCP skills (workspace_colab_execute, _ask, _build, _pipeline)
- [x] 6 new Colab proxy routes (/api/colab/ask, /execute, /build, /status, /pipeline)
- [x] 14 new tests (88 workspace pipeline total, all pass)
- [x] Pipeline stages: 21 → 24, templates: 21 → 25, workspace skills: 27 → 31
- [x] Full suite green (~11,748 passed)

---

## Shipped: v1.19b — "DRIVE V2INTERNAL + SHEETS EXTENDED LIVE-WIRING" ✅

- [x] 6 Drive v2internal methods (copy, trash, export, permissions, metadata)
- [x] 4 Sheets extended methods (batch_save, session_prefs, external_data, revisions)
- [x] 4 new pipeline stages (drive_copy, drive_export, drive_permissions, sheet_revisions)
- [x] 4 new pipeline templates (clone, export_distill, audit, revision_audit)
- [x] 4 new MCP skills + 4 new proxy routes
- [x] 74 workspace pipeline tests pass (11 new v1.19b tests)
- [x] Full suite green (~11,748 passed)

---

## Shipped: v1.19a — "DEEP HAR API EXPLORATION" ✅

- [x] 25 new YAML sections: sheets_gemini, docs_gemini, drive_gemini, drive_v2internal,
  sheets_extended, people_stack, experiments, feedback, workspace_analytics, addons,
  ogads, consent, growth_promos, api_key_catalog, auth_cookie_catalog, client_side_gating
- [x] 50 total workspace operations documented with full payload maps
- [x] 16 API keys cataloged across 12 Google services
- [x] 8 new WorkspaceGeminiClient methods (14 total)
- [x] Client-side tier gating bypass documented (body[0][5][0] = [2])
- [x] HAR mining tools: har_deep_explorer.py, har_payload_analyzer.py
- [x] 127 workspace tests pass

---

## Shipped: v1.18c — "CROSS-SERVICE CHAIN PROMPTS" ✅

- [x] 4 new pipeline stages: docs_to_sheets, sheets_to_doc, gemini_enrich, prewarm
- [x] 8 new cross-service chain templates (docs_nlm_distill, full_cross_service, etc.)
- [x] 4 new workspace skills (23 total)
- [x] 10 new HAR-discovered endpoints (workspace_support section)
- [x] Pipeline stages: 13 → 17, templates: 9 → 17
- [x] Tests: 63 workspace pipeline, 102 workspace RPC registry, 11,737+ total

---

## Shipped: v1.18b — "SCHEDULER INTEGRATION" ✅

- [x] 4 workspace pipeline scheduler tasks: news-pipeline (8h), news-to-knowledge (daily),
  research-cycle (12h), pipeline-health (6h)
- [x] End-to-end workspace smoke test (`scripts/workspace_smoke_test.py`)
- [x] SCHEDULER.md and WORKSPACE_PIPELINE.md documentation
- [x] Scheduler tasks: 57 → 61
- [x] Tests: 44 scheduler tests (7 new), 11,721+ total

---

## Shipped: v1.18a — "PIPELINE STAGE EXPANSION" ✅

- [x] `workspace_generate` stage — direct WorkspaceGeminiClient.stream_generate
- [x] `fetch_news` stage — bridges standalone NewsPipeline RSS fetcher
- [x] Pipeline stages: 11 → 13, templates: 7 → 9
- [x] `workspace_generate` + `workspace_fetch_news` MCP skills (17 → 19)
- [x] `/api/workspace/news/fetch` + `/api/workspace/news/digest` proxy routes (11 → 13)
- [x] 22 new tests (13 pipeline + 9 skills)
- [x] Tests: 11,721 passing

---

## Shipped: v1.17c — "HAR PAYLOAD VERIFICATION" ✅

- [x] Rewrote all WorkspaceGeminiClient payloads to protobuf-JSON arrays (HAR-verified)
- [x] Added operation codes, context codes, 3 HAR-verified API keys
- [x] Updated nlm_rpcids.yaml workspace sections with correct formats
- [x] Tests: 166 workspace + 39 registry passing

---

## Shipped: v1.17b — "WORKSPACE PIPELINE" ✅

- [x] WorkspaceGeminiClient — stream_generate, get_settings, list_gems, quota_summary, cloud_search
- [x] GoogleDocsClient — full CRUD + Gemini generation (create, get, update, export, generate)
- [x] GoogleSheetsClient expanded — fill_with_gemini, build_with_gemini, execute_columnsmith, fetch_external_data
- [x] GoogleDriveClient expanded — ai_overview_search, ask_gemini
- [x] WorkspacePipeline — 11 stages, 7 templates, cross-service orchestrator
- [x] WorkspaceRPCRegistry — parallel registry for Workspace endpoints
- [x] 17 workspace @skill functions + 11 proxy routes
- [x] 166 new tests, 11,706 total

---

## Shipped: v1.16b — "EMBEDDING AUTO-WIRE" ✅

- [x] Auto-embed every Nexus write into ChromaDB vector store
- [x] Batch re-indexing of unembedded entries via scheduler task
- [x] Content-type → collection mapping (10 types → 8 collections)
- [x] Scheduler tasks: 56 → 57
- [x] 31 new tests

---

## Shipped: v1.15b — "GEMINI EMBEDDING 2 + MRL VECTOR SEARCH" ✅

- [x] EmbeddingService with Gemini + LMStudio provider chain, MRL support (768/1536/3072 dims)
- [x] ChromaDB-backed NexusVectorStore with 8 collection types
- [x] 4 embedding MCP skills (semantic_search, vector_add, text_similarity, embedding_stats)
- [x] Query router: 5 → 6 tiers (new Tier 2: Vector Semantic Search)
- [x] Tests: 11,507 passing

---

## Shipped: v1.14b — "ERROR VISIBILITY" ✅

- [x] Structured logging for 10 silent exception blocks across 4 pipeline files
- [x] cache_pipeline (4), system_reflection (3), auto_diagnosis (2), qa_expander (1)

---

## Shipped: v1.13b — "FACTORY MIGRATION COMPLETE" ✅

- [x] All 6 remaining notebook creation paths routed through NLMNotebookFactory
- [x] Engine-level nlm_engine.create_from_files() uses factory with fallback
- [x] ARGUS pipeline tests updated to mock factory

---

## Shipped: v1.12b — "NLM PIPELINE HARDENING" ✅

- [x] 5 more files migrated to NLMNotebookFactory (teacher, reflection, qa_expander, forge, bootstrap)
- [x] news-nlm-retry scheduler task (every 8h) with retry queue processing
- [x] Failed distillations now queue to retry (not just uploads)

---

## Shipped: v1.11b — "NLM NOTEBOOK FACTORY" ✅

- [x] Centralised NLMNotebookFactory with dedup keys, weekly rotation, persistent tracking
- [x] Single state file replaces 6 separate state files
- [x] News NLM pipeline refactored to use factory
- [x] 14 new tests

---

## Shipped: v1.10b — "SYSTEM CONSOLIDATION" ✅

- [x] Consolidated duplicate news source registries into single module
- [x] Training flywheel auto-export (≥50 examples → JSONL at 0.7 quality)
- [x] Scene health test suite (24 scenes, 74 parametrized tests)
- [x] Skill registration test suite (57 skills, 118 parametrized tests)

---

## Shipped: v1.09b — "PIPELINE VALIDATION" ✅

- [x] Real-time training flywheel feed (bypass 24h daily sync delay)
- [x] Credential guard with cookie/staleness checks before NLM calls
- [x] Retry queue for failed distillations (persist, 3 attempts, max 10)
- [x] Runtime hardening: bare except → logged handlers in admin panel

---

## Shipped: v1.08b — "GAME SYSTEM INTEGRATION" ✅

- [x] Wire neurochemistry into NPC conversation interceptors
- [x] Hack engine → territory control reward multiplier
- [x] Custom news publishing + `publish_news` skill

---

## Shipped: v1.07b — "PIPELINE INTELLIGENCE" ✅

- [x] Automated topic discovery, NLM-driven knowledge distillation, news ingestion pipeline
- [x] Query router NLM-backed deep research tier (5-tier pipeline)
- [x] Training flywheel wiring, Unsloth QLoRA orchestrator, ContentRouter
- [x] Tests: 10,988 passing

---

## Shipped: v1.06b — "AAA+++ ANIMATION" ✅

- [x] 55-state animation state machine, 111 poses, 5-tab Animation Studio UI
- [x] 6 MCP animation skills, YAML content system, model browser
- [x] 128 new tests

---

## Shipped: v1.05b — "AUTONOMY SPRINT" ✅

- [x] Priority-based task queue, agent task scheduler, backup/restore skills
- [x] Versioned prompt templates (20 built-in), Flask metrics dashboard

---

## Shipped: v1.04b — "SYSTEM INTEGRATION" ✅

- [x] LMStudio auth, character picker, agent loop UI, first-person camera
- [x] Smart test runner (4-tier strategy), automated test scheduler
- [x] Tests: 10,988 passing

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

---

## Shipped: v1.02b — "NEONCITY 2: THE LIVING CITY" ✅

- [x] Character neurochemistry (6 neurotransmitters), skill progression (8 skills, 6 levels)
- [x] Unified neon_base.html template, phone panel rewrite, onboarding quests
- [x] Cyberspace hacking engine, living world, multiplayer foundation
- [x] In-game world news system + bottom-of-screen ticker

---

## Post-v1.18 Roadmap (2026-Q3+)

### Cross-Service Chain Prompts
- Docs→NLM chain: draft doc → upload to NLM → distill → store
- Sheets enrichment chain: create → fill with Gemini → export
- Drive→NLM→Nexus chain: semantic search → NLM research → store
- News automation: 3x daily scheduler-driven news cycles

### Advanced NLM Automation
- Architecture research: use NLM to evaluate design alternatives autonomously
- Multi-notebook orchestration for complex research sessions
- NLM-driven code generation with distilled implementation guides
- Automated notebook lifecycle management (create → populate → distill → archive)

### System Evolution
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
