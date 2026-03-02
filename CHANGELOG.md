# Changelog

All notable changes to CosySim are documented here.

## v0.69 "The Living System" — March 2026

### New
- **Cross-scene relay** (`engine/events/cross_scene_relay.py`): EventBus events ripple across scenes —
  Arena results → NeonCity faction shifts + Lounge rumors; Casino wins → Intel Hub alerts;
  Heist completions → faction events; World shifts → Tavern rumors
- **Universal phone panel** (`cosysim-phone-panel.css/js`): slide-in SIGNAL panel available on every scene
  via navbar; live contacts, chat, notifications, auto-injected via shared after_request hook
- **Aria animated portrait** (`cosysim-aria-portrait.css/js`): 4 display modes (floating/messenger/
  voice-call/full-portrait), 4 CSS states (idle/talking/thinking/listening), inline SVG face,
  backward-compat `window.ariaWidget` shim
- **Router v3 dataset** (`training/datasets/router_v3.jsonl`): 2,080 examples, 16-class taxonomy
  (expanded from v2's 8 classes): small_talk, game_action, story_narrative, character_emotion,
  world_query, skill_call, memory_recall, scene_transition, system_command, creative_generation,
  information_lookup, emotional_support, adult_content, combat_narrative, economic_action, investigation
- **Router finetune cycle** (`engine/nexus/router_finetune_cycle.py`): orchestrates train/val split →
  Alpaca conversion → FinetuneOrchestrator.start_job()
- **Content seeder** (`engine/content/seed_all.py`): 40 content items across 8 scenes + 5 Nexus QA pairs
- **World state wiring**: casino, lounge, tavern, heist, gallery all connected to WorldState + EventBus
  with per-scene time handlers (happy hour, quest refresh, exhibit rotation)
- **Scene beat configs**: per-scene `SCENE_BEAT_CONFIGS` in SceneDirector (7 scenes: bedroom, arena,
  casino, lounge, neoncity, heist, tavern) with preferred_beats, avoid_beats, escalation_threshold
- New docs: WORLD_SYSTEM.md, ECONOMY_GUIDE.md, ARENA_GUIDE.md, CONTENT_GUIDE.md

### Changed
- `launcher.py`: WorldSim daemon started after scenes; CrossSceneRelay.start() called after WorldSim
- `engine/nexus/scheduler_daemon.py`: 3 new tasks (world-sim-tick 5m, director-tick 15m, content-refresh 6h)
- `content/shared/templates/aria_widget.html`: replaced 157-line inline HTML with 2 asset tags
- `config/default.yaml`: version corrected to 0.68b
- `ROADMAP.md`: v0.68 marked complete, v0.69 tracks added
- `docs/INDEX.md`, `docs/SYSTEM_AUDIT.md`: updated to v0.68 (A+ grade)

### Fixed
- **Test isolation** (Track E): 74 failures + 38 errors → **6,882 passed, 0 failures, 0 errors**
  - `tests/conftest.py`: module-scoped autouse fixture resets 7 singletons between test modules
  - `pyproject.toml`: `norecursedirs` excludes tests/tmp from pytest collection

### Tests
- **6,882 tests passing** (up from 6,679 at v0.68)
- 203 new tests across: cross_scene_relay, router_v3_dataset, content seeder, world wiring, Aria portrait

---


### New
- 13 engine modules: EventBus, EconomyManager, ContentGate, ContentEngine, CharacterMemory,
  ReputationManager, SceneDirector, ConsequenceStore, InvestigationBoard, SceneArtManager,
  WorldState, WorldSim, ArenaEngine
- New scene: Arena — THE COLOSSEUM (port 5561): tactical card game, agent vs agent (RPS mechanics),
  live betting, NLM commentary, BenchHUD showing both model latencies
- Voice system: VoiceManager JS (Piper/Orpheus/Qwen3 backends, STT, localStorage persistence)
- Universal chrome: navbar_v2, admin_overlay (8-tab hacker loft), Aria floating widget
- Black glass design system: extended design_tokens.css, cosysim-components.css, cosysim-animations.css
- Three.js 3D particle system: 12 presets, 10,000 particles at 60fps
- BenchHUD: live agent latency, model, Nexus tier, token count per scene
- Adult content system: ContentIntensityInterceptor, intensity profiles 0–3 per category
- BaseScene: `register_tts_route()`, `register_bench_route()`, `inject_navbar_context()`

### Changed
- 14 scene revamps with new display names, black glass UI, scene accent system,
  adult content wired, all new engine modules integrated
- All scenes: dark glass panels, 3D particles, TTS wired, BenchHUD, living world connected
- `config/default.yaml`: arena scene added (5561), warzone archived, content_intensity interceptor added
- Scene display names: THE PENTHOUSE, NEON CITY, SIGNAL, THE VELVET PIT, THE RUSTY ANCHOR,
  CLUB NOIR, THE OBSCURA, THE SCORE, THE SHATTERED THRONE, THE LAB, THE ARCADE,
  THE TERMINAL, THE BRIEFING ROOM, THE COLOSSEUM

### Tests
- 6,679 tests passing (up from 4,747 at v0.59b)
- 16 new revamp test suites added

---

## v0.67 — Curated World

### Track A: News System Expansion

- **`config/news_sources.yaml`**: Expanded from 5 → 26 curated sources across 7 categories
  - `ai_ml` (9): ArXiv cs.AI/cs.LG/cs.CL, HN Top/Best, Reddit r/ML/r/artificial/r/singularity, VentureBeat AI
  - `local_inference` (3): Reddit r/LocalLLaMA, r/ollama, r/Oobabooga
  - `open_source` (4): GitHub Trending (all + Python), Lobsters, Changelog
  - `python` (4): Reddit r/Python, Real Python, Python Insider, PyPI Updates
  - `security` (3): Reddit r/netsec, Krebs on Security, Schneier on Security
  - `science` (2): ScienceAlert, MIT Technology Review
  - `dev_tools` (1): Dev.to Top Posts
  - Added `category_filters` with per-category include keyword lists
  - Added `keyword_filters.exclude` (crypto/blockchain/nft/bitcoin/etc.)

- **`engine/nexus/news_sources.py`**: Category-aware filtering + reliability fixes
  - `NewsSource` dataclass: added `last_fetch_status: str = "pending"` field
  - `filter_articles()`: rewritten to be category-aware — each category uses its own include keywords; categories without a filter only have global excludes applied (enables python/security/science to pass without AI keywords)
  - `score_relevance()`: uses category-specific keywords with source quality_score as base
  - `store_to_nexus()`: fixed `content_type="news"` (was `"note"`)
  - `stats()`: now includes `category`, `quality_score`, `last_fetch_status` per source

### Track B: Intel Hub News Section

- **`content/scenes/intel_hub/intel_hub_scene.py`**: 3 new news API endpoints
  - `GET /api/news/latest?limit=&category=` — articles from Nexus content_type=news
  - `POST /api/news/fetch-now` — trigger full fetch cycle, returns stats + digest preview
  - `GET /api/news/sources` — all configured sources with status

- **`content/scenes/intel_hub/templates/intel_hub.html`**: Full news section added
  - Nav button: 📰 News (between Overview and Assistant)
  - Category tabs: All / AI-ML / Inference / Python / Security / Science / Open Source / Dev Tools
  - Source panel (left) + article cards feed (right)
  - Search/filter bar, Fetch Now button, empty-state handling
  - Version badge: v0.66 → v0.67

- **`content/scenes/intel_hub/static/js/intel_hub.js`**: News section wired
  - `initNewsSection()`, `loadNewsSources()`, `loadNewsArticles()`, `renderNewsArticles()`
  - `sectionLoaders` dict updated: `news: initNewsSection`

- **`content/scenes/intel_hub/static/css/intel_hub.css`**: News styles added
  - `.cat-tab`, `.news-article-card`, `.news-article-meta`, `.news-cat-chip`, `.news-score-bar`
  - `.source-row`, `.source-dot-ok/error/pending`

### Track C: Scene Health Audit

- All 18 scene modules verified to import cleanly post-v0.66 engine changes
- `tests/test_scene_imports.py`: parametrized import test for all 18 scenes (19 tests)

### New Tests (+42, total 5,695)

- `tests/test_news_system.py` (28 tests): config structure, registry load, category-aware filtering, scoring, Nexus storage
- `tests/test_scene_imports.py` (19 tests): all 18 scene imports + count guard
- Updated `tests/test_news_sources.py`: aligned to category-aware filter design

### Nexus Knowledge

- Stored 3 v0.67 architecture decisions: category-aware filtering design, sources inventory, Intel Hub news API

---

## v0.66 — The Living Loop (Track A)

### Improved: `training/micro_datasets.py` — Router V2 Dataset Generation

- Expanded `_ROUTER_V2_TEMPLATES` from 8 → 120 entries (15 per label × 8 labels)
- Labels: `nexus_search`, `nexus_ask`, `scene_control`, `tts_request`, `backup_request`, `stt_request`, `nlm_research`, `config_update`
- Fixed `_generate_synthetic` cycling bug — only unique template examples are returned (no duplicates from `i % len(base)` cycling)
- Rewrote `_augment_router` with 4 deterministic transforms: prefix, question-form, noun-wrap, synonym-swap
- Fixed `_augment` loop to pass `_aug_index = cycle` so each base × cycle combination is unique
- Router-v2 uses all examples as `base_pool` to ensure full label coverage during augmentation
- Fixed `_generate_via_teacher` to always supplement teacher output with synthetic templates for full label coverage
- Result: 364 examples (291 train / 36 val / 37 test) with all 8 labels balanced (~30–42 per label)

### Updated: Scheduler Daemon (28 → 30 tasks)

- Added `router-finetune-cycle` (weekly): end-to-end router_v2 pipeline (dataset gen → finetune submit → benchmark)
- Added `dataset-augment` (weekly): re-augments all 5 micro-model datasets without teacher pipeline
- Added `_router_finetune_cycle_callback()` and `_dataset_augment_callback()` implementations

### New Tests (17 new, 5,609 total)

- `tests/test_router_finetune_cycle.py` — 17 tests for router v2 finetune cycle
  - `TestRouterV2Templates` (4): label coverage, min examples/label, no duplicates, required keys
  - `TestMicroDatasetManagerRouterV2` (4): synthetic labels, 3 splits, Alpaca format, dedup
  - `TestRouterFinetuneSchedulerCallbacks` (4): success path, queued skip, all models, error tolerance
  - `TestAutoPromoteWiring` (5): auto-promote flow, router registration, singleton, 30 tasks, new tasks registered
- Updated 4 existing scheduler task count assertions: 28 → 30

---

## v0.65 — Profile Skills, Conversation Analyzer, Backup Manager

### New: `engine/skills/builtin/profile_skills.py`
- 11 MCP skills across 3 groups: conversation analysis, user profile, backup
- `analyze_conversation`, `analyze_recent_conversation`, `conversation_analyzer_status`
- `user_profile_get`, `user_profile_context`, `user_profile_facts`, `user_profile_add_fact`, `user_profile_set_preference`, `user_profile_update`
- `backup_run`, `backup_list`, `backup_restore`

### Updated: Scheduler Daemon (28 tasks)
- Added `conversation-analyze` task (#28) — daily, analyzes recent Copilot session turns
- Auto-stores salient facts, preferences, and technical background into UserProfileStore + Nexus

### New: `training/smoke_test.py`
- 8-check end-to-end pipeline smoke test, runs without GPU
- Verifies: dataset sizes, model registry, benchmark runner, finetune orchestrator, teacher pipeline, router

### New Tests (57 new, 5,582 total)
- `tests/test_conversation_analyzer.py` — 19 tests for ConversationAnalyzer + UserProfileStore
- `tests/test_backup_manager.py` — 16 tests for BackupManager
- `tests/test_profile_skills.py` — 22 tests for profile skills pack

---

## v0.64 — Training Pipeline + Intelligence Hub

### New: TeacherPipeline (`engine/nexus/teacher_pipeline.py`)
- NLM teacher that drives Gemini 3.0 via NotebookLM to generate per-type JSONL datasets
- 5 micro-model types: `qa_evaluator`, `router_v2`, `syntax_fixer`, `knowledge_synthesizer`, `conversation_analyzer`
- Per-type NLM notebooks with source pyramid loading
- Generates datasets via `generate_report_with_prompt` with per-type CSV/JSONL prompts
- Synthetic fallback when NLM unavailable
- `TrainingExample` dataclass, saves as JSONL, stores metadata in Nexus
- `get_teacher_pipeline()` singleton

### New: MicroDatasetManager (`training/micro_datasets.py`)
- Loads existing examples, generates via teacher pipeline, augments, deduplicates
- Model-specific augmenters (rephrase, synonym, filler words, question reformulation)
- Converts to Alpaca instruction format (`{instruction, input, output}`)
- 80/10/10 train/val/test splits saved as separate JSONL files
- `MODELS` list exported for scheduler and benchmark runner

### New: FinetuneOrchestrator (`training/finetune_orchestrator.py`)
- Job queue with `pending`, `running`, `done`, `failed`, `cancelled` states
- Generates standalone `train.py` using Unsloth QLoRA (subprocess — avoids import conflicts)
- Live log parsing: step progress + loss tracking
- Auto-merges LoRA adapters on completion (`save_pretrained_merged`)
- Persists job state to `training/jobs.jsonl`
- Notifies ModelRegistry on completion
- `BASE_MODEL_ALIASES`: `qwen-270m`, `qwen-1.7b`, `llama-3b`, `qwen-7b`
- `FinetuneConfig` auto-selects hyperparams by model size (r, batch_size)
- `get_finetune_orchestrator()` singleton

### New: ModelRegistry (`training/model_registry.py`)
- Tracks all fine-tuned models with benchmark scores and active flags
- `promote(model_type, model_id)` / `auto_promote(model_type)` → swap active model
- `update_benchmark(model_id, score, metrics)` for score tracking
- Persists to `training/model_registry.json` (full rewrite on save)
- Notifies `finetuned_router` on promotion
- `get_model_registry()` singleton

### New: BenchmarkRunner (`training/benchmark_runner.py`)
- Runs held-out test sets against active fine-tuned models
- Per-type rule-based baseline predictor as fallback (no LMStudio needed)
- Computes accuracy, F1 (token overlap), exact-match, aggregate score
- `auto_promote()` on score improvement
- Appends results to `training/benchmarks.jsonl` + stores in Nexus
- `get_leaderboard()` returns best score per model type
- `get_benchmark_runner()` singleton

### New: FinetunedRouter (`engine/lmstudio/finetuned_router.py`)
- Routes task-specific requests to fine-tuned models when available
- `is_available(task_type)` check before routing — returns `None` gracefully when unavailable
- `load_from_registry()` auto-loads all active models on startup
- Formats as Alpaca prompt, calls LMStudio `/v1/completions`
- Convenience methods: `route_qa_evaluation()`, `route_request_classification()`
- `get_finetuned_router()` singleton

### New: Intelligence Hub Scene (`:5580`)
- Unified glassmorphism admin panel with 12 sections
- **Nexus Explorer** — search, browse, add entries; live stats
- **NLM Lab** — create notebooks, upload sources, run generation tiles, batch-ask
- **Fine-tune Lab** — submit jobs, track progress, view leaderboard, promote models
- **Scheduler** — view tasks, trigger runs, view history
- **Copilot Rules** — view/edit governance rules
- **Cache Pipeline** — run stages, view cycle results, download review sheet
- **Model Registry** — browse all fine-tuned models, promote, delete
- **Backup Manager** — create/restore backups, view history
- **Conversation Analyzer** — analyze session history, extract insights
- **User Profile** — preferences, system config
- **TTS Config** — select backend, voice, test TTS; VTT config
- **Assistant Panel** — chat interface, mic input, avatar display area
- `intel_hub_skills.py` — 6 @skill functions for agent access
- Glassmorphism CSS with neon accent design system

### Modified: Scheduler Daemon (`engine/nexus/scheduler_daemon.py`)
- 4 new builtin tasks (27 total, was 23):
  - `teacher-dataset-gen` (weekly) — NLM teacher generates JSONL datasets
  - `finetune-if-ready` (weekly) — submits finetune job if dataset ≥500 examples
  - `model-benchmark` (daily) — runs benchmark on all active fine-tuned models
  - `backup-databases` (daily) — creates Nexus + SQLite backups
- 4 new callback functions: `_teacher_dataset_gen_callback`, `_finetune_if_ready_callback`, `_model_benchmark_callback`, `_backup_databases_callback`

### Modified: Cache Pipeline Stage F (`engine/nexus/cache_pipeline.py`)
- Stage F now tries `finetuned_router.route_qa_evaluation()` first (local, free)
- Falls back to NLM Gemini batch evaluation if fine-tuned model unavailable
- `_run_stage_f_finetuned()` added as dual-path method
- This is the core self-improvement loop: fine-tuned model replaces Gemini calls over time

### Modified: DevTools Server (`engine/mcp/devtools_server.py`)
- 18 new MCP tools:
  - `finetune_submit`, `finetune_run_next`, `finetune_list_jobs`, `finetune_build_dataset`, `finetune_dataset_status`
  - `model_registry_list`, `model_benchmark_run`, `model_benchmark_leaderboard`, `model_promote`
  - `teacher_generate_dataset`
  - `finetuned_router_status`, `finetuned_router_load_registry`
  - `backup_run`, `backup_list`, `backup_restore`
  - `user_profile_get`, `user_profile_update`

### Tests
- `tests/test_teacher_pipeline.py` — full coverage for TeacherPipeline
- `tests/test_micro_datasets.py` — MicroDatasetManager, augmentation, formatting, dedup
- `tests/test_finetune_orchestrator.py` — FinetuneOrchestrator job lifecycle, script gen, persist
- `tests/test_model_registry_and_benchmark.py` — ModelRegistry CRUD + BenchmarkRunner F1/accuracy
- `tests/test_finetuned_router.py` — FinetunedRouter routing, registry loading, graceful fallback
- `tests/test_intel_hub_scene.py` — Intel Hub scene, skills, config
- **5,505 tests, 0 failures** (was 5,437)

---



### New: CachePipeline (`engine/nexus/cache_pipeline.py`)
- 10-stage orchestrator (A–J) for NLM-driven Q&A cache generation
- Stage A: Direct seed from high-quality session turns (200–400 pairs, no NLM)
- Stage B: Upload source pyramid + themed history chunks to Notebook A
- Stage C: Raw generation — `extract_flashcards`, `extract_quiz`, `extract_data_tables`
- Stage D: Structured generation — CSV mode × 3 consumer focuses + Python code-gen mode
- Stage E: Parse + deduplicate candidates (normalise, length filter, Nexus dedup)
- Stage F: NLM self-evaluation — ESSENTIAL / USEFUL / SKIP rating + gap list
- Stage G: Store approved pairs in Nexus Q&A cache with consumer/priority/category metadata
- Stage H: Generate Excel review sheet for human approval
- Stage I: Upload approved pairs back as source (compounding — each cycle improves next)
- Stage J: Log gap list → create scheduler tasks for gap-fill notebooks
- `CycleResult` dataclass with full accounting per stage
- `CandidatePair` and `EvalResult` dataclasses for typed pipeline data
- Sandbox `_exec_code_mode()` — executes Gemini-generated `build_qa_pairs()` safely

### New: HistoryMiner (`engine/nexus/history_miner.py`)
- Reads `~/.copilot/session-store.db` via sqlite3 (read-only URI mode)
- `mine_checkpoints(theme)` → themed `SourceDocument` (keyword-matched, markdown)
- `mine_all_themes()` → 10 themed documents for full pyramid upload
- `mine_turns(min_answer_len)` → direct-seed `QAPair` list from real session history
- `mine_full_dump()` → all checkpoints concatenated for mega-notebook upload
- `get_stats()` → session/checkpoint/turn counts + store size

### New: SourcePyramid (`engine/nexus/source_pyramid.py`)
- Builds 6 meta-documents that shape all NLM generation tile output
- Layer 0: Consumer Briefing, Layer 1: Output Schema, Layer 2: Good Examples
- Layer 3: Bad Examples, Layer 4: Existing Coverage, Layer 5: Priority Rubric
- `build_all(existing_questions)` → `{layer_name: content}` dict
- `upload_pyramid(notebook_id, skip_layer_4, existing_questions)` → count
- `upload_content(notebook_id, docs)` → count
- `refresh_coverage(notebook_id, client)` → skips if client unavailable (fixed)

### New: ConsumerBriefing (`engine/nexus/consumer_briefing.py`)
- Living query taxonomy for 5 consumer classes (copilot-startup, agent-task, governance, developer, news-retrieval)
- `build_briefing()`, `get_schema_doc()`, `get_good_examples()`, `get_bad_examples()`, `build_priority_rubric()`
- `build_csv_prompt(consumer_focus)` — targeted CSV generation per consumer class
- `build_code_gen_prompt()` — Gemini generates `build_qa_pairs() -> list[dict]`
- `build_evaluation_prompt(pairs_csv)` — self-evaluation: ESSENTIAL/USEFUL/SKIP
- `build_gap_prompt(covered_questions)` — identifies missing query patterns
- Stored in Nexus as governance document; editable without code changes

### New: ReviewSheet (`engine/nexus/review_sheet.py`)
- openpyxl Excel review sheet for human Q&A pair approval
- Columns: Question, Answer, Consumer, Priority, Category, NLM_Rating, Include, Duplicate, Notes
- `Include` formula: `=IF(OR(F{r}="ESSENTIAL",F{r}="USEFUL"),"YES","REVIEW")`
- `Duplicate` formula: `=COUNTIF($A$1:A{prev},A{r})>0`
- Data validation dropdowns for Consumer, Category, NLM_Rating
- Conditional formatting: SKIP rows → grey; Priority color scale red→yellow→green
- `import_reviewed(path, client)` — reads Include=="YES" rows back to Nexus

### Updated: SchedulerDaemon — 21→23 tasks
- Added `qa-history-mine` (weekly) — runs full cache pipeline cycle
- Added `qa-cache-prune` (weekly) — removes zero-hit pairs older than 30 days

### Updated: DevTools MCP Server — 4 new tools
- `cache_pipeline_run(stages)` — run full cycle or specific stages
- `cache_pipeline_status()` — last cycle result + gap list
- `review_sheet_generate(output_path)` — generate Excel from pending pairs
- `review_sheet_import(path)` — import reviewed xlsx back to Nexus

### Updated: Autonomy Skills — 2 new @skills
- `cache_generate_pairs(consumer_focus, count)` — targeted NLM generation for one consumer
- `cache_review_sheet(output_path)` — generate Excel review sheet on demand

### Tests
- `tests/test_history_miner.py` — 19 tests for HistoryMiner (themes, mine_checkpoints, mine_turns, full_dump, get_stats)
- `tests/test_source_pyramid.py` — 21 tests for SourcePyramid (build_all, upload_pyramid, upload_content, refresh_coverage)
- `tests/test_consumer_briefing.py` — 27 tests for ConsumerBriefing (briefing, prompts, schema, Nexus persistence)
- `tests/test_cache_pipeline.py` — 27 tests for CachePipeline (stages, code_mode sandbox, dedup, full cycle dry run)
- `tests/test_review_sheet.py` — 27 tests for ReviewSheet (generate xlsx, formulas, import_reviewed)
- Scheduler task count assertions updated 21→23



### New: LocalAgentBridge (`engine/nexus/local_agent_bridge.py`)
- Enables local LMStudio agents to discover, claim, execute, and complete tasks
- `get_ready_tasks(model_size, limit, tags)` — filters by complexity tier (router/mini/worker/expert)
- `claim_task(task_id, agent_id)` — atomically claims a specific task
- `get_task_context(task_id)` — loads task + Nexus knowledge + coding rules + execution steps
- `complete_task(task_id, result, files_changed, store_to_nexus)` — marks complete, optionally stores in Nexus
- `fail_task(task_id, reason, retry)` — marks failed or resets to pending for retry
- `get_agent_manifest(model_size)` — produces formatted system prompt fragment for LLM injection
- 6 MCP tools in `devtools_server.py`: `local_agent_get_tasks`, `local_agent_claim_task`, `local_agent_task_context`, `local_agent_complete_task`, `local_agent_fail_task`, `local_agent_manifest`

### New: MasterNotebookBuilder (`engine/nexus/master_notebook_builder.py`)
- Builds the "CosySim Master Intelligence" notebook in NotebookLM with full system knowledge
- 13 categorised text bundles (hardware spec, engine source, nexus, lmstudio, MCP, skills, services, scenes, config/rules, docs, frontend JS, tests, dependencies)
- 19 official SDK/API URL sources (LMStudio Python+REST API, Flask, Python stdlib, pytest, requests, Pydantic, MCP Protocol, HuggingFace, ONNX Runtime, GitHub Copilot CLI)
- Runs all NotebookLM generators: audio (standard + deep dive), video, study guide, briefing, FAQ, data tables
- 35-question Q&A distillation → stored in Nexus for cache hits
- State persistence in `.github/hooks/logs/master_notebook_state.json` — resumable builds
- CLI: `python -m engine.nexus.master_notebook_builder [--dry-run] [--sources-only] [--generators-only]`
- 4 MCP tools: `master_notebook_build`, `master_notebook_status`, `master_notebook_reset`, `master_notebook_list_sources`
- Weekly scheduler task: `master-notebook-refresh`

### Updated: Nexus Panel NLM Skills (`content/scenes/nexus_panel/nexus_panel_skills.py`)
- `librarian_ask` upgraded with confidence-based NLM escalation (threshold 0.35)
  - When Nexus confidence is low, escalates to NLM hybrid, stores answer back for future cache hits
  - Returns `[Routed to NLM]` tag in response when escalation occurs
- `librarian_route_stats` — new skill showing routing breakdown and tokens saved
- `nlm_panel_list_notebooks` — lists all NLM notebooks with IDs and source counts
- `nlm_panel_distill` — triggers knowledge_forge distillation into Q&A pairs
- `nlm_panel_audio` — generates NLM audio overview (standard/deep_dive)
- `nlm_panel_bulk_ask` — bulk-asks questions to NLM, optionally stores to Nexus
- `nlm_panel_news_digest` — manually triggers news NLM pipeline
- `nlm_panel_setup_auth` — sets up/refreshes NLM browser authentication

### Updated: TaskScheduler (`engine/nexus/task_scheduler.py`)
- Added `claim_task_by_id(task_id, agent_id)` — claim a specific task by ID
- Added `get_pending_tasks()` — returns all pending tasks sorted by priority
- Updated `fail_task(retry=True)` — resets task to pending, clears agent assignment for retry

### Updated: SchedulerDaemon — 19→20 tasks
- Added `master-notebook-refresh` (weekly) — calls `refresh_master_notebook()`
- Fixed missing `def complete_task(...)` signature in `task_scheduler.py`
- Fixed `news_nlm_pipeline._run_distillation()` exception handling (moved `_get_hybrid()` inside try block)

### Tests
- `tests/test_master_notebook_builder.py` — 39 new tests for master notebook builder, state persistence, scheduler integration, singleton
- `tests/test_local_agent_bridge.py` — 60 new tests for local agent bridge
- `tests/test_nexus_panel.py` — ~40 new tests for NLM panel skills and librarian routing
- Scheduler task count assertions updated 19→20



### New: Session → Nexus → NLM Knowledge Pipeline

**`engine/nexus/sync_sessions_to_nexus.py`** (new)
- Bulk-syncs Copilot CLI session history from `~/.copilot/session-store/store.sqlite` to Nexus
- Hash-based change detection — only syncs changed sessions
- Stores checkpoints, file changes, turn count, and refs as `copilot-history` entries
- CLI: `python engine/nexus/sync_sessions_to_nexus.py --days 7 --force`
- Scheduler callback: `run_session_sync()` (syncs last 7 days)

**`engine/nexus/session_distillation.py`** (new)
- Distills recent session history into NLM notebook Q&A pairs
- Pipeline: Nexus history entries → digest text → NLM notebook source → batch-ask → store Q&A
- 12 targeted distillation questions covering decisions, patterns, bugs, conventions, NLM learnings
- Scheduler callback: `run_session_distillation()` (daily)
- CLI: `python engine/nexus/session_distillation.py --days 7 --upload-only`
- Support for `--upload-only` (update NLM only) and `--distill-only` (skip upload, just ask)

### Updated: Copilot Bridge — Governance & Memory

**`engine/nexus/copilot_bridge.py`**
- `consensus_gate(operation, description)` — checks Nexus governance rules before high-impact ops
  - Returns `True` (allow) or `False` (block) based on matching `block`/`deny` rules
  - Always stores gate check as a `copilot-decisions` entry for audit trail
  - Operations: `arch-change`, `rule-change`, `major-refactor`, `new-dependency`, `config-change`
- `get_onboarding_context()` — loads complete context at session start: rules (coding/global/copilot), last 10 architectural decisions, architecture overview, active scheduler todos
- `get_decision_history(topic, n=5)` — retrieves past decisions from Nexus matching a topic; checks both knowledge entries and Q&A cache

### Updated: Nexus Namespace — Copilot Subcategories

**`engine/nexus/nexus_namespaces.py`**
- Extended `copilot` namespace `allowed_categories` to include:
  `copilot-rules`, `copilot-history`, `copilot-decisions`, `copilot-plans`, `copilot-micro-versions`

### Updated: NLM Proxy — User Plan API

**`engine/mcp/nlm_live_proxy.py`**
- `get_user_plan(cookies)` standalone function (ZwVcOc RPC) — returns `plan_name`, `daily_limit`, `queries_remaining`
- `NLMClient.get_user_plan()` method
- `GET /user/plan` Flask endpoint
- `GET /user/queries` Flask endpoint — fast path for queries remaining (clean integer from JFMDGd)
- Helper `_walk_ints(obj)` — recursively extracts integers from nested structures

### Updated: Scheduler — Session Distillation Task

**`engine/nexus/scheduler_daemon.py`**
- Added `session-distillation` daily task (17th builtin task)
- Callback: `_session_distillation_callback()` → `run_session_distillation()`

### Tests
- `tests/test_sync_sessions_to_nexus.py` — 35 tests for session sync utility
- `tests/test_session_distillation.py` — 42 tests for distillation pipeline
- `tests/test_copilot_bridge.py` — 22 new tests for `consensus_gate`, `get_onboarding_context`, `get_decision_history`
- `tests/test_scheduler_daemon.py` — updated builtin task count: 16 → 17

---

## v0.60.9 — NLM Lab Panel: Full Sub-Nav UI

### Nexus Panel (`content/scenes/nexus_panel/`)

#### New: NLM Lab Sub-Navigation (6 tabs)
Replaced the flat NLM Lab panel with a fully organised sub-navigation layout:

- **Query** — NLM-first query, multi-ask (3–10 questions in one session), tier badge + source metadata
- **Studio** — All quota-free Studio tile operations:
  - Extract Flashcards → parse `{front, back}[]`, optionally store in Nexus
  - Extract Quiz → parse `{question, answer, options[]}[]`, optionally store in Nexus
  - Report with Custom Prompt → inject any prompt into Reports tile, get custom Gemini output
  - Distill to Nexus (one-shot) → flashcards + quiz → parse all → store all Q&A atomically
- **Batch** — Batch Q&A Workshop with auto question generation
- **Analysis** — Plan Decomposer, Code Analyzer, Topic Builder
- **Metrics** — NLM Savings Dashboard (cache/FTS/NLM/LLM hits, tokens saved), Quota Usage display
- **Admin** — Auth Status + Setup, Quota Tier Override (all 5 tiers), Export Nexus → NLM Notebook

#### New: Backend Routes (10 new endpoints)
- `POST /api/nlm/studio/extract-flashcards` — quota-free flashcard extraction
- `POST /api/nlm/studio/extract-quiz` — quota-free quiz extraction
- `POST /api/nlm/studio/generate-report` — custom-prompted report generation
- `POST /api/nlm/studio/ask-multi` — multi-question single-session ask
- `POST /api/nlm/studio/distill` — one-shot distil pipeline
- `GET /api/nlm/quota` — quota status
- `POST /api/nlm/quota/set-tier` — override quota tier
- `GET /api/nlm/auth/status` — Node server health + auth state
- `POST /api/nlm/auth/setup` — trigger interactive browser auth
- `POST /api/nlm/export-nexus` — assemble Nexus entries → upload as NLM text source

#### NLM Node Bridge (`engine/mcp/nlm_node_bridge.py`)
- Added `is_initialized` public property
- Added convenience bridge methods: `extract_flashcards`, `extract_quiz`, `generate_report_with_prompt`, `ask_multi`, `distill_to_nexus`, `set_quota_tier` (with appropriate long timeouts for browser ops)

---


### NLM Structured Extraction (`C:\Files\MCP\notebooklm-mcp`)

#### New: Quota-Free Q&A Distillation
- **`extract_flashcards`** — Generates flashcards via Studio tile (quota-free), parses into `{front, back}[]` pairs, optionally stores all pairs directly in Nexus KMS
- **`extract_quiz`** — Generates quiz via Studio tile (quota-free), parses into `{question, answer, options[], explanation}[]` items, with Nexus auto-store
- **`distill_to_nexus`** — One-shot pipeline: generates flashcards + quiz, parses everything, stores all Q&A pairs in Nexus atomically. This replaces the old sprint distillation scripts.

#### New: Custom-Prompted Report Generation
- **`generate_report_with_prompt`** — Injects a custom text prompt into the Reports Studio tile dialog before generation fires. Enables: "Generate 20 Q&A pairs", "Write a Python script that...", "Rank these concepts by complexity" — anything Gemini 3 can produce.

#### New: Multi-Question Sessions
- **`ask_multi`** — Ask 3-10 questions in a single call, all within the same conversation thread (same session_id). Questions build on each other's context. Great for drill-down sequences and progressive knowledge extraction.

#### New: Content Parsers (`src/notebook-creation/studio-extractor.ts`)
- `parseFlashcards(text)` — 5 parsing strategies: Front/Back blocks, Card N dividers, Q/A pairs, paragraph pairs, line-pair fallback
- `parseQuiz(text)` — 3 strategies: Question blocks with lettered options, numbered blocks, Q/A simple pairs  
- `parseMindMap(text)` — Indented hierarchy parser returning `{topic, subtopics[], depth}[]`
- `storeQaPairsInNexus(pairs, nexusUrl, category, tags)` — HTTP poster to Nexus KMS API

#### Extended: Studio Generator
- `StudioGenerator.generateWithCustomPrompt()` — tiles with prompt dialog support
- `StudioGenerator.generateAndGetStructured()` — end-to-end: generate → wait → extract → parse → return structured data
- `GetArtifactStructuredResult` type with `parsed` field containing typed flashcards/quiz/mind_map arrays

### Key Benefits
- **Zero quota usage** for flashcard/quiz distillation — replaces all chat-based Q&A extraction
- **25-40 Q&A pairs per notebook** from a single `distill_to_nexus` call
- **Context continuity** via `ask_multi` — all questions share same NLM thread



### NLM Studio Generation (`C:\Files\MCP\notebooklm-mcp`)
- Live DOM discovery confirmed all 9 current Studio tiles (Audio Overview, Video Overview, Mind Map, Reports, Flashcards, Quiz, Infographic, Slide deck, Data table)
- OLD tiles (Study Guide, FAQ, Briefing Doc) confirmed REMOVED from current NotebookLM
- New `src/notebook-creation/studio-generator.ts` — `StudioGenerator` class for all text-based Studio tiles
- New MCP tools: `generate_studio_artifact`, `get_studio_artifact`, `generate_and_get_studio_artifact`
- Studio generation is **quota-free** (bypasses /chat RPC entirely)

### Quota Pro Fix
- `NLM_TIER=pro` env var added to `.vscode/mcp.json` — forces 500 queries/day
- `config.ts` — new `nlmTier` field, applied in `applyEnvOverrides()`
- `quota-manager.ts` — `loadSettings()` applies tier override; `updateFromUI()` skips auto-detection when `NLM_TIER` is set

### Auth Backup System
- New `backup-auth.ps1` — backs up `state.json.pqenc`, `quota.json`, `library.json`
- Keeps 14 rolling daily backups under `Data/backups/YYYY-MM-DD/`
- `-Check` flag for health check, `-Install` for weekly Windows Scheduled Task
- Weekly `NLM-AuthBackup` task installed (Monday 6AM)

### Nexus Knowledge Stored
- Studio tile discovery (all 9 tiles with icon/jslog/aria-label) — entry `eba21dc68b6e480e`
- Quota system internals + NLM_TIER override — entry `561f37c7bbbc4f2c`
- Auth/cookie methods + subprocess deadlock pattern — entry `16ffff5f583b47aa`

## v0.60.6 — NLM Governance Gating, Devtools Tools, Auto-Doc Agent

### Governance Gating (`engine/skills/builtin/notebooklm_skills.py`)
- All 12 NLM skills now gated with `@governed` decorator
- Read gate: `ask`, `list_notebooks`, `search`, `ask_node`, `batch_ask`, `extract_tables`, `hybrid_health`
- Write gate: `add_source`, `generate_audio`, `generate_audio_node`, `generate_video`
- Admin gate: `setup_auth`
- Agent size enforcement: sub-1B → read-only, 1B+ → read+write, copilot → full access

### Devtools MCP Tools (`engine/mcp/devtools_server.py`)
Added 11 new NLM Node bridge tools (total MCP tool count now 225+):
- `notebooklm_node_ask` — single Q&A with session continuity
- `notebooklm_node_batch_ask` — JSON array of questions, returns array of answers
- `notebooklm_node_add_source` — add URL or text source
- `notebooklm_node_create_notebook` — create with sources + topic hints
- `notebooklm_node_list_notebooks` — list all notebooks
- `notebooklm_node_generate_audio` — trigger audio overview generation
- `notebooklm_node_generate_video` — trigger video overview (style param)
- `notebooklm_node_extract_tables` — extract data tables with optional query
- `notebooklm_node_chat_history` — get recent chat turns
- `notebooklm_node_health` — combined Node + proxy health check
- `notebooklm_node_setup_auth` — one-time Chrome login trigger
- `notebooklm_node_sync_nexus` — **key tool**: batch Q&A → auto-stores all answers in Nexus Q&A cache

### Auto-Documentation Agent (`.github/agents/auto-documenter.agent.md`)
- New autonomous agent that detects changed files via git diff
- File→doc mapping (e.g. engine/skills/ → docs/SKILLS.md)
- NLM research flow: loads changed code into notebook, asks targeted questions
- Writes Nexus note flagging pending doc updates; writes CHANGELOG entries
- Registered as 13th builtin scheduler task (`doc-sync`, daily)

### VS Code MCP Config (`.vscode/mcp.json`)
- Fixed NLM server env var names (`HEADLESS`, `STEALTH_ENABLED`, `MAX_SESSIONS`)
- Set `autoStart: true` — VS Code now starts Node MCP server automatically
- Copilot gets all 31 Node MCP tools on startup (31 vs 47 — secure server is leaner)

### Live Proxy Auth Gate (`engine/mcp/nlm_live_proxy.py`)
- `/chat` and `/chat_batch` routes now check cookie file exists before delegating
- Returns 401 if not authenticated (instead of 502 from Node bridge auth failure)
- Auth semantics preserved: missing cookie file → 401, bridge failure → 502

### Tests
- `tests/test_notebooklm_devtools.py` — 21 tests for all new devtools tools
  - Uses `tool.fn` pattern to call underlying async functions from `FunctionTool` objects
- `tests/test_autonomy_skills.py` — scheduler task count updated to 13
- `tests/test_nlm_live_proxy.py` — chat tests updated for hybrid router mock pattern
- **Total: 5054 tests, 0 failures**

---

## v0.60.5 — NLM Node MCP Integration + Hybrid Router

### Node MCP Server (C:\Files\MCP\notebooklm-mcp\)
- Cloned and built `@pan-sec/notebooklm-mcp` v2026.2.9 (47 tools)
- Registered in `.vscode/mcp.json` — Copilot gets all 47 NLM tools directly
- Uses Patchright (undetectable Playwright) + persistent Chrome profile auth
- First-time setup: run `notebooklm_setup_auth` skill once, then headless forever

### Python Bridge (`engine/mcp/nlm_node_bridge.py`)
- Full JSON-RPC 2.0 stdio bridge to the Node MCP process
- Singleton `get_nlm_node_bridge()`, thread-safe with background reader thread
- `ask_question(notebook_id, question, session_id)` — session continuity via `session_id`
- `ask_batch(notebook_id, questions, keep_session=True)` — Q&A chain with session reuse
- `create_notebook(name, sources)`, `add_notebook(url, name, ...)`, `select_notebook(id)`
- `add_source(nb_id, url|text)` — uses `{type, value}` source schema
- `generate_audio_overview(nb_id)`, `get_audio_status(nb_id)`
- `generate_video_overview(nb_id, style)` — 10 visual styles
- `extract_data_tables(nb_id, query)`, `get_chat_history(nb_id, limit)`
- Parameter corrections from Node tool definitions (e.g. `id` not `notebook_id` for select_notebook)

### Hybrid Router (`engine/mcp/nlm_hybrid.py`)
- Routes ops to correct backend automatically:
  - **Chat/Q&A** → Node bridge (browser-based, 400-error-free)
  - **Audio/Video/Data tables** → Node bridge (only available there)
  - **Source add / rename** → batchexecute proxy (fast HTTP, with Node fallback)
- Singleton `get_nlm_hybrid()`, lazy-imports Node bridge on first use
- `ask(notebook_id, question, session_id, reset_history)` — multi-turn capable
- `ask_batch(notebook_id, questions)` — delegates to `node.ask_batch`

### Chrome Auth Extractor (`engine/mcp/nlm_chrome_auth.py`)
- Reads Chrome Cookies SQLite DB from Node server's profile
- Windows DPAPI decryption for legacy cookies + AES-256-GCM for Chrome v80+
- `get_cookies_from_chrome_profile()` → dict of auth cookie name → value
- `update_proxy_cookies_from_chrome()` → writes to proxy cookie file (no more HAR!)

### NLM Live Proxy Fix (`engine/mcp/nlm_live_proxy.py`)
- `/chat` endpoint now delegates to `get_nlm_hybrid().ask()` instead of broken `_grpc_ask`
- `/chat_batch` endpoint delegates to `get_nlm_hybrid().ask_batch()`
- Eliminates HTTP 400 errors — all Q&A now goes through browser automation

### New Skills (`engine/skills/builtin/notebooklm_skills.py`)
- `notebooklm_ask_node` — Q&A via Node bridge with session_id continuity
- `notebooklm_batch_ask` — batch Q&A with session threading
- `notebooklm_generate_audio_node` — trigger audio overview
- `notebooklm_generate_video` — trigger video overview (10 styles)
- `notebooklm_extract_tables` — extract structured data tables
- `notebooklm_hybrid_health` — combined health check (Node + proxy)
- `notebooklm_setup_auth` — one-time Chrome login setup

### Tests
- `tests/test_nlm_node_bridge.py` — 23 tests covering all bridge methods
- `tests/test_nlm_hybrid.py` — 18 tests covering routing logic and fallbacks
- 41 new tests total, all passing



### NLM Live Proxy v3.0 (engine/mcp/nlm_live_proxy.py)
- **21 confirmed RPCs** — upgraded from 18 via 8-HAR cross-session analysis
- **6 RPC descriptions corrected** (were misidentified in v2.1):
  - `sqTeoe` → "List Audio Overview Types" (was "List All Notebooks")
  - `hPTbtc` → "Get Conversation Thread IDs" (was "List Sources Paginated")
  - `khqZz` → "Read Conversation Thread Messages" (was "Sub-notebook sources")
  - `JFMDGd` → "User Profile + Queries Remaining" (was "Sources Condensed")
  - `cFji9` → "Generate/Get Mind Map" (was "Conversation History")
  - `CYK0Xb` → "Save Notebook Note" (was "Legacy Chat RPC")
- **3 newly decoded write RPCs**:
  - `CCqFvf` — Resume Session / Load Last Active Notebook
  - `Ljjv0c` — Start Fast Research Session (returns session_id)
  - `LBwxtb` — Add URL Sources batch (uses session_id from Ljjv0c)
- **`_RateLimiter` class** — thread-safe per-host rate limiter (default 1.5s gap)
  - Applied to every outbound NLM batchexecute call
  - Configurable via `notebooklm.rate_limit_seconds` in config
  - Runtime control via `GET/POST /rate_limit`
- **RPC registry integration** — imports `engine.nexus.nlm_rpc_mapper.get_rpc_id()`
  - Loads live IDs from `data/nlm_rpc_registry.json` (updated by automation)
  - Falls back to hardcoded constants when registry unavailable
- **10 new REST API routes**:
  - `POST /notebooks` — create notebook (UUID v4, lazy backend creation)
  - `POST /notebooks/<id>/sources` — add URL sources (Ljjv0c + LBwxtb flow)
  - `GET /notebooks/<id>/sources/wait` — poll until sources processed (rLM1Ne)
  - `POST /notebooks/<id>/research` — start fast research session (Ljjv0c)
  - `GET /notebooks/<id>/threads` — get conversation thread IDs (hPTbtc)
  - `GET /notebooks/<id>/threads/<tid>` — read thread messages (khqZz)
  - `GET /notebooks/<id>/mindmap` — get/generate mind map D3 JSON (cFji9)
  - `GET /user/profile` — user profile + queries remaining (JFMDGd)
  - `GET/POST /rate_limit` — rate limiter status and control
  - `GET /rpc_registry` — RPC registry status (sources, staleness)
- **`/health` updated**: `rpc_catalog_version: v3.0`, `known_rpcs: 21`, rate limit + registry status
- **`/history` route rewritten**: now returns `{threads: [...]}` using hPTbtc+khqZz correctly

### New Modules
- **`engine/nexus/nlm_rpc_mapper.py`** — Dynamic RPC ID registry:
  - `NLMRPCRegistry` class with hardcoded fallbacks for all 24 operations
  - File-backed persistence at `data/nlm_rpc_registry.json` (auto-created by automation)
  - Staleness detection (10-day TTL)
  - `get_rpc_id(operation)` convenience function used by proxy
  - `update_from_automation()` merges results from nlm_automation.py
  - `invalidate()` forces singleton reload
  - CLI: `python -m engine.nexus.nlm_rpc_mapper` for status report
- **`engine/nexus/nlm_automation.py`** — Playwright automation for RPC discovery:
  - Launches Chrome with user profile, intercepts all network traffic
  - Performs every known NLM operation with 3s delays between ops
  - Captures batchexecute request/response pairs with operation labels
  - Saves structured JSON log to `data/nlm_automation_log.json`
  - Updates `data/nlm_rpc_registry.json` after each run
  - CLI: `python -m engine.nexus.nlm_automation [--headless] [--ops op1,op2]`

### Documentation
- **`docs/NOTEBOOKLM_SDK.md`** — Updated to v3.0:
  - Complete REST API reference (35+ routes with curl examples)
  - Corrected RPC catalogue (21 RPCs with descriptions)
  - Source data structure schema (all JSPB fields)
  - GenerateFreeFormStreamed proto endpoint
  - Rate limiter behaviour section
- **`docs/NOTEBOOKLM_PROTOCOL.md`** — New 1,100-line deep-dive:
  - batchexecute wire protocol (f.req format, wrb.fr parsing, JSPB)
  - Authentication deep dive (SAPISIDHASH, BL management, session tokens)
  - All 21 RPCs with examples, args, response structures
  - Source data schema with all field positions
  - Notebook lifecycle (create → add → poll → ask → read)
  - RPC ID rotation and 3-layer resilience architecture
  - Known gaps table (10 uncaptured operations)
  - CosySim proxy architecture diagram

### Config
- **`config/default.yaml`**: Added `notebooklm.rate_limit_seconds: 1.5`

### Nexus Knowledge Base
- Stored 9 new entries: full RPC catalogue document + 8 Q&A pairs covering
  authentication, source adding, fast research, RPC rotation, notebook creation

### Tests
- **`tests/test_nlm_live_proxy.py`**: 88 → **109 tests** (+21)
  - New: `TestCreateNotebook`, `TestAddSources`, `TestStartResearch`,
    `TestThreadRoutes`, `TestRateLimiterRoute`, `TestRPCRegistryRoute`, `TestRateLimiter`
- **`tests/test_nlm_rpc_mapper.py`**: New test file for RPC registry
- **`tests/test_nlm_automation.py`**: New test file for automation/capture




### System Control Panel (NEW — port 5575)
- **`content/scenes/system_control/system_control_scene.py`** — New Flask scene (20+ API routes):
  - Config Editor: read/write/validate all YAML+JSON configs with .bak backup
  - Service Health: parallel health checks of all 19 services (3s timeout per)
  - Launcher auto-start toggle per service/scene (persisted to launcher.yaml)
  - NLM Proxy control: HAR import, Chrome CDP cookie capture, notebook list, proxy status
  - Nexus quick search and health overview
  - LMStudio status and loaded model listing
  - Real-time log viewer (tail any log file)
  - Git status: branch, last 10 commits, working tree changes
  - System metrics: CPU, RAM, GPU (psutil + pynvml with graceful fallback)
- **`content/scenes/system_control/templates/system_control_ui.html`** — Dark-theme 9-tab UI
- **`content/scenes/system_control/static/css/system_control.css`** — Complete CSS
- **`content/scenes/system_control/static/js/system_control.js`** — Full JavaScript
- Added to `launcher.py` SERVICES dict, `config/default.yaml`, `config/production.yaml`, `config/launcher.yaml`

### NLM Proxy Class Refactor
- **`engine/mcp/nlm_live_proxy.py`** — Added `NLMClient` class:
  - Delegates to all module-level RPC functions (no duplication)
  - `get_nlm_client()` singleton factory
  - New `GET /notebooks/<id>/history` Flask route (hPTbtc RPC)
- **`engine/nexus/nlm_engine.py`** — Removed all `:3000` / Node.js dead code:
  - Removed `_nexus_nlm_url`, `_post_any`/`_get_any` dual-backend fallback
  - Imports and re-exports `NLMClient`, `get_nlm_client` for callers
  - All operations route through `:8800` proxy only

### Tests
- **4,827 tests passing** (0 failures, 21 warnings)



### NLM v2.1 Protocol (NEW — commit 2ff3698)
- **`engine/mcp/nlm_live_proxy.py`** — Major v2.1 update (11 HAR files analyzed):
  - **18 RPC ID constants** catalogued: RPC_LIST_NOTEBOOKS, RPC_GET_SOURCES, RPC_CHAT_MESSAGE, RPC_ANNOTATE_TEXT, RPC_GENERATE_DOC, RPC_SAVE_NOTE, RPC_READ_SOURCE, RPC_GET_CONVERSATIONS, RPC_LIST_NOTES, RPC_GET_SUMMARY, RPC_AUDIO_OVERVIEW, RPC_AUDIO_STATUS, RPC_CREATE_NOTEBOOK, RPC_DELETE_NOTEBOOK, RPC_ADD_SOURCE, RPC_DELETE_SOURCE, RPC_GET_QUOTA
  - **s0tc2d** (RPC_CHAT_MESSAGE) — async chat with configure-chat role injection and response length
  - **CYK0Xb** (RPC_ANNOTATE_TEXT) — synchronous citation-annotate (preferred for Q&A distillation)
  - **tr032e** (RPC_READ_SOURCE) — reads full markdown content of any source document (NEW)
  - **ozz5Z** (RPC_GET_QUOTA) — user account info and storage quota (NEW)
  - Response length constants: `RESP_LEN_DEFAULT=4` (HAR-confirmed), `RESP_LEN_LONGER=1`, `RESP_LEN_SHORTER=2`
  - Document type constants: `DOC_TYPE_BRIEF=2`, `DOC_TYPE_NOTE=9`
  - BL staleness tracking: warns when build label is ≥8 days old; `GET /health` returns `bl_age_days`, `bl_stale`
  - New Flask routes: `POST /notebooks/<id>/chat`, `/chat_batch`, `GET /sources/<id>/content`, `/user/quota`
  - Updated `/ask` and `/ask_batch` with `mode` parameter (annotate vs chat)
  - `_REQUEST_TIMEOUT` increased 45→60s for async s0tc2d calls
- **`engine/mcp/notebooklm_proxy.py`** — v2.1 wrapper methods:
  - `chat_message()`, `chat_messages_batch()`, `read_source()`, `get_user_quota()`
- **`docs/NOTEBOOKLM_SDK.md`** — Complete v2.1 rewrite (11 HAR sessions, all 18 RPCs documented):
  - Build Label Management section, Configure Chat guide (5 role examples)
  - s0tc2d vs CYK0Xb comparison table, async polling strategy
  - 6 Use Case Playbooks, BL monitoring guide, Known Limitations
- **launcher.yaml**: `nlm_proxy` now `auto_start: true`

### NLM v2.1 Skills (+4 new skills in autonomy pack — commit 8e658b4)
- `nlm_chat(notebook_id, question, role, response_length)` — configure-chat with role injection
- `nlm_chat_batch(notebook_id, questions, role, response_length)` — batched s0tc2d
- `nlm_read_source(source_id)` — extract full source markdown
- `nlm_user_quota()` — fetch account quota info
- Total NLM skills: 7 → **16**

### Tests (+13 new tests — commit 72f8018)
- `TestV21Routes`: all 4 new v2.1 routes fully covered (auth guards, success, error paths)
- Total NLM proxy tests: 54 → **67**
- Total test suite: 4,800 → **4,823**

---

## v0.60 — NLM v2: Live Write API, CDP Auth, QA Distiller & Launch Overhaul

### NotebookLM Live Write API (NEW)
- **`engine/mcp/nlm_live_proxy.py`** — Complete v2 rewrite of the batchexecute proxy:
  - **CYK0Xb RPC** — Ask questions with full answer + citation extraction
  - **ciyUvf RPC** — Generate documents/reports from notebook sources
  - **R7cb6c RPC** — Create and save note artifacts in notebooks
  - **Multi-question batching** — up to 5 questions in a single HTTP request (5× efficiency)
  - **`_batchexecute_multi()`** — packs N calls into one request, parses all `wrb.fr` blocks
  - **Build label management** — `bl` and `f.sid` stored in `data/nlm_meta.json`, auto-extracted from HAR
  - **`_WRITE_CONFIG`** — canonical write config object reverse-engineered from HAR
  - New REST routes: `POST /notebooks/<id>/ask`, `ask_batch`, `generate`, `save_note`, `GET|POST /meta`
- **`engine/nexus/nlm_har_capture.py`** (NEW) — Chrome CDP automated cookie capture:
  - `CDPSession` class — WebSocket-based Chrome DevTools Protocol client
  - `capture_nlm_cookies()` — launch Chrome, navigate to NLM, extract all session cookies
  - `WIZ_global_data` extraction for `bl` and `f.sid` without HAR
  - Fallback: uses existing profile so no login required

### NLM QA Distiller (NEW)
- **`engine/nexus/nlm_qa_distiller.py`** — systematically expands Nexus QA pairs via NLM:
  - 75 hand-crafted questions across 7 topic templates: `cosysim_architecture`, `nlm_integration`,
    `nexus_knowledge_system`, `agent_operations`, `lmstudio_integration`, `scene_development`,
    `self_improvement`
  - `NLMQADistiller.bulk_distill()` — runs all templates in 15 batches of 5
  - Auto-stores Q&A pairs directly in Nexus SQLite (with Nexus server fallback)
  - `QUESTION_DESIGN_GUIDE` — instructions for local models to write effective NLM questions
  - CLI: `python -m engine.nexus.nlm_qa_distiller --bulk --notebook <id>`

### NLM SDK Documentation (NEW)
- **`docs/NOTEBOOKLM_SDK.md`** — comprehensive 19KB protocol reference:
  - Full batchexecute endpoint spec (URL params, headers, SAPISIDHASH computation)
  - Complete RPC catalogue: 9 RPCs documented with args/returns
  - Multi-question batching format with examples
  - 5 maximization strategies for agent workflows
  - HAR analysis findings (Chrome 130+ cookie redaction, `wrb.fr` parsing)
  - Session refresh strategy and build label maintenance

### NLM Live Skills (NEW — 7 skills in autonomy pack)
- `nlm_live_ask(notebook_id, question)` — direct CYK0Xb ask
- `nlm_live_batch_ask(notebook_id, questions)` — batch up to 5 questions
- `nlm_generate_document(notebook_id, source_ids, doc_type)` — ciyUvf document generation
- `nlm_save_note(notebook_id, source_ids, note_type)` — R7cb6c note creation
- `nlm_capture_cookies()` — Chrome CDP automatic auth capture
- `nlm_proxy_meta()` — get current bl/f.sid metadata
- `nlm_distill_notebook(notebook_id, topic, num_questions)` — distill Q&A → Nexus

### High-Level Proxy Updates
- **`engine/mcp/notebooklm_proxy.py`** — updated to use live write API:
  - `ask()` → real CYK0Xb via live proxy (was stub)
  - Added `batch_ask()`, `generate_document()`, `save_note()`, `capture_cookies()`, `get_meta()`

### Test Suite
- **4,800 tests** across 176+ files (+53 new NLM v2 tests):
  - `TestWriteOperationParsing` — CYK0Xb/ciyUvf/R7cb6c response parsers
  - `TestMultiBatchParsing` — multi-wrb.fr block extraction
  - `TestWriteFlaskEndpoints` — ask, ask_batch, meta GET/POST, 401 guard
  - `TestNLMQADistiller` — question templates, fallback, offline behaviour

---



### Phone News Feed (NEW)
- **`engine/integrations/phone_news.py`** — curated news feed for mobile phone scene
- Markdown-rendered news cards with read/delete/thumbs up/down interactions
- User feedback loop into training flywheel for preference learning
- Socket.IO real-time push for breaking news

### Home Assistant Integration (NEW)
- **`engine/integrations/homeassistant.py`** — HA REST API client (entities, services, states)
- Auto-discover entities on homeassistant.local
- 11 MCP tools for agent HA control (toggle, automate, notify, sensor read)
- HA news bridge: push high-relevance articles as mobile notifications (12th scheduler task)
- Safety governance rules for HA actions

### NLM Deep Storage (NEW)
- **`engine/nexus/nlm_deep_storage.py`** — 3-tier notebook archival system (~500 lines)
  - **Ground Truth**: complete notebook snapshots (metadata, sources, conversations, notes)
  - **Knowledge Layer**: distilled Q&A with category tagging
  - **Working Layer**: active notebook references in JSON metadata
- Conversation chains with UUID-based chain IDs and parent linking
- HAR extraction support for Google batchexecute RPC responses
- Local JSON index at `data/nlm_archives/` for fast lookup
- 9 @skill functions + 8 MCP tools for deep storage operations
- 27 tests covering archive, retrieve, search, chain, delete flows

### Phone Assistant (NEW)
- **`engine/assistant/phone_assistant.py`** — cascade routing with 4-tier fallback
  - Tier 1: System Assistant (Aria) — full CosySim intelligence
  - Tier 2: Nexus Q&A — cached knowledge (confidence > 0.3)
  - Tier 3: AnythingLLM — offline/local fallback (phone instance)
  - Tier 4: Static fallback — graceful degradation
- Mode control: auto (cascade all), passthrough (server only), offline (local only)
- Voice synthesis via TTS manager for spoken responses
- Conversation history with capped buffer and stats tracking
- 3 @skill functions + 4 MCP tools
- 35 tests covering cascade, modes, tiers, TTS, history, stats

### System Dashboard (NEW)
- **Phone system app** — 4-tab dashboard (overview, agents, scheduler, chat)
- Aggregated system status: LMStudio, Nexus, scheduler, scenes, agents
- Chat with assistant from mobile via PhoneAssistant cascade
- 13 tests for dashboard API endpoints

### AnythingLLM Integration (NEW)
- **`engine/integrations/anythingllm.py`** — REST client with multi-instance support
- Workspace CRUD, chat, threads, documents, bidirectional Nexus sync
- 10 @skill functions + 6 MCP tools
- Config: laptop (localhost:3001) + phone instances
- 19 tests for client, workspaces, chat, sync

### Convention Fixes
- All `print()` calls in CLI modules converted to `logging.getLogger(__name__)`
  (cli.py, nlm_cli.py, nexus_distiller.py, nexus_seeder.py, nexus_session_logger.py,
  self_maintenance.py, har_extractor.py, space_exporter.py)
- 19 f-string logger calls in cli.py converted to %-formatting
- `bridge.py._output()` kept as `print()` (CLI contract for machine-readable JSON)
- Governance enforcement: `check-tool-safety.ps1` now denies edits with reject/block severity

### System Hardening (v0.59b patch)
- **YAML config fix** — repaired `config/default.yaml` agent_profiles nesting (router,
  narrator, game_master were incorrectly nested under training.datasets). Fixed 50 tests.
- **Skill registration** — registered 5 orphaned skill packs (anythingllm, codespace,
  inference, nlm_forge, prompts_chat) adding 36 previously undiscoverable skills.
  Total: 188 builtin skills across 21 packs.
- **Silent exception logging** — replaced 9 bare `except: pass` blocks with
  `logger.debug/warning` calls (system_assistant, phone_assistant, copilot_bridge,
  scheduler_daemon, self_maintenance).

### Web Infrastructure (v0.59b patch)
- **Central CORS** — added `CORS(app)` in `register_shared_assets()` so all 18 scenes
  get cross-origin support automatically (was missing from 7 scenes).
- **Health routes** — added `/api/health` to 7 scenes that were missing it (bedroom,
  lounge, casino, heist, phone, nexus_panel, gallery) via `BaseScene.register_health_route()`.
- **Nexus Panel fixes**:
  - Fixed `nexus_panel.js` syntax error (missing closing brace in chat command handler)
  - Fixed dashboard stats display — unwrapped `data` layer in API response, mapped correct
    keys (`knowledge_entries`/`qa_pairs`/`sessions`/`rules` instead of wrong names)
  - Added `switchTab()` function and click handlers on dashboard recent entries
  - Made `api()` timeout configurable; increased HAR commit timeout from 30s to 120s
- **Three.js character rendering** — fixed `_buildHead()` return type in `character_models.js`
  (was returning bare Group, callers expected `{group: g}`). Added defensive guards in
  `setCharacterExpression` and `applyState` so 3D errors never block UI updates.
- **NeonCity scroll** — added `min-height:0` to `.event-log` flex child for proper overflow.
- **NLM enabled** — set `notebooklm.enabled: true` in config (was false).

### Test Suite
- **4,747 tests** across 176 files (87 new NLM/ComfyUI skill tests + 119 board/character/
  memory/social skill tests + 50 fixed by YAML repair)

---

## v0.58b — Project Autonomy: Self-Improving System

### Autonomous Heartbeat (NEW)
- **`engine/nexus/scheduler_daemon.py`** — cron-like task daemon with 12 builtin callbacks:
  nexus-maintenance, nexus-dedup, knowledge-quality, notebook-rotation, news-fetch,
  test-monitor, metrics-collect, training-sync, system-reflection, experiment-scan,
  task-auto-gen, ha-news-push
- Configurable intervals, persistent state, thread-safe scheduling

### Knowledge Intelligence (NEW)
- **`engine/nexus/knowledge_graph.py`** — topic graph from Nexus entries with gap detection,
  co-occurrence edges, clustering, and auto-research task generation
- **`engine/nexus/nlm_notebook_manager.py`** — NLM notebook fleet management (create, seed, rotate)
- **`engine/nexus/governance_rules.py`** — 18 executable governance rules with validation engine
- **Knowledge quality scoring** in `self_maintenance.py` — freshness, relevance, structure scoring

### Self-Repair & Diagnosis (NEW)
- **`engine/nexus/auto_diagnosis.py`** — parse test failures → Nexus cache → heuristics →
  NLM diagnosis → fix task generation. Covers 7 error types.
- **`engine/nexus/system_reflection.py`** — weekly/monthly NLM-driven analysis of system metrics,
  auto-generates improvement tasks from insights
- **`engine/nexus/experiment_proposals.py`** — auto-proposes A/B experiments from metric trends
  with 5 built-in templates

### Training & Metrics (NEW)
- **`engine/nexus/training_flywheel.py`** — training data collection from tasks, Q&A, conversations.
  Export to JSONL, ShareGPT, DPO formats. SQLite-backed at `data/training_flywheel.db`
- **`engine/nexus/meta_metrics.py`** — system metrics dashboard with trend analysis, regression
  detection, snapshots. SQLite-backed at `data/meta_metrics.db`

### News & Information (NEW)
- **`engine/nexus/news_sources.py`** — news source registry (HN, RSS, web scrape) with
  Nexus storage and daily digest generation
- **`engine/nexus/news_feed_api.py`** — Flask blueprint REST API (5 endpoints: latest,
  digest, search, sources, stats)
- **`config/news_sources.yaml`** — 5 curated source definitions

### Copilot Self-Configuration (NEW)
- **`engine/nexus/copilot_self_config.py`** — sync instruction files, agent definitions,
  hooks, and preferences to/from Nexus

### Skills & Tools
- **`engine/skills/builtin/autonomy_skills.py`** — 68 @skill functions across 12 categories
  exposing all autonomy modules to LLM agents
- **`engine/mcp/devtools_server.py`** — 95+ MCP tools (added ~58 new autonomy tools)
- Full test suite: **4,409 tests** (492 new) across 100+ files

## v0.57b — UX Overhaul, System Assistant & Voice Interface

### Voice Interface (NEW)
- **`engine/tts/tts_manager.py`** — unified TTS manager routing between backends:
  - **Piper** (fast, CPU-only): ~250ms for 3s audio, 14x faster than real-time
  - **Orpheus** (quality, 24 voices): LMStudio-backed with emotion tags
  - **Qwen3** (GPU, 0.6B/1.7B): escalation mode with speculative decoding
- Auto-selects backend: short text → Piper, long text → Orpheus, fallback chain
- Performance benchmarking: per-backend latency, RTF, call counts, failure tracking
- **Voice API endpoints** on assistant Blueprint:
  - `POST /api/assistant/voice` — TTS synthesis (returns audio/wav)
  - `POST /api/assistant/listen` — STT via Whisper (forwards to :5051)
  - `GET /api/assistant/tts/health` — backend health check
  - `GET /api/assistant/tts/benchmarks` — performance metrics
- **Push-to-talk** in assistant overlay: hold 🎤 to record, auto-transcribes via Whisper
- **Audio playback**: toggle 🔊 to hear Aria's responses spoken aloud
- Keyboard shortcuts: Ctrl+Shift+V (toggle voice mode)
- STT config added: `stt.server_url` in default.yaml
- Piper config added: `tts.piper.model_path` in default.yaml

### Scene Navigation Bar (NEW)
- **`cosysim-navbar.js`** — floating navigation bar auto-injected into every scene
- Back/Forward/Home buttons with session-based history tracking
- Scene selector dropdown with live health status (green/red dots)
- Keyboard shortcuts: Ctrl+Shift+H (home), Ctrl+Shift+←/→ (navigate), Ctrl+Shift+N (toggle)
- Minimizable, persistent state across page loads

### System Assistant "Aria" (NEW)
- **`engine/assistant/system_assistant.py`** — singleton AI assistant character
- Floating overlay widget injected into every scene (Ctrl+Shift+A to toggle)
- Chat interface with text input and quick action buttons
- Built-in commands: system status, scene list, navigation ("go to bedroom")
- LLM-powered responses with fallback when LLM unavailable
- Registered in CharacterRegistry with personality, backstory, voice style
- **`engine/assistant/assistant_bp.py`** — Flask Blueprint with `/api/assistant/chat` and `/api/assistant/status`

### Hub Rebuild (Streamlit → Flask)
- **`content/scenes/hub/hub_flask.py`** — complete rewrite as Flask scene
- Scene grid with live health status indicators
- System metrics bar (scenes online, agent count, VRAM usage)
- Modern dark UI using CosySim design tokens
- `/api/scenes` and `/api/system` REST endpoints
- Hub now starts as Flask scene on port 8500 (no Streamlit dependency)

### Shared Asset Injection
- `register_shared_assets()` now auto-injects navbar + assistant via `after_request` hook
- All 14 Flask scenes get navigation + assistant automatically
- Added `register_shared_assets()` to 4 scenes that were missing it (games, coders, tavern, nexus_panel)
- Assistant Blueprint auto-mounted on every scene

### Launcher
- Hub moved from Streamlit to Flask in launcher catalogue
- Version bumped to 0.57b

## v0.56b — Deep Polish Sprint

### Games Scene: THIN → DEEP
- AI GameMaster agent with character registration, governance context, and personality
- Socket.IO real-time events: mystery investigation, truth-or-dare, game chat
- MCP state tree with score persistence and active game tracking
- Interactive playable UI with game cards, mystery panel, T&D panel, chat widget
- Full JavaScript client with typewriter text effects and event handling

### Coders Scene: MEDIUM → DEEP
- Session persistence: save/load/list coding sessions as JSON
- Auto-save on scene stop with agent stats, tick count, completed features
- Three new API routes: `/api/sessions`, `/api/session/save`, `/api/session/load`

### Router Training Pipeline
- Three new API routes: `/api/router-data/stats`, `/export`, `/readiness`
- `training/deploy_router.py` — auto-deploy trained GGUF to LMStudio models directory

### NLM Graceful Degradation
- `/api/nlm/status` route with tier-aware health checks
- NLM status widget in Nexus Panel dashboard header
- `source_tier` field in Librarian chat responses
- Periodic NLM health polling in frontend

### Tests
- Updated Games scene tests for new health/plugin_info fields
- +111 tests → 3,521+ total

## v0.55b — Full-Project Audit & Hardening

### Code Quality
- Hardened 10+ silent exception handlers with `exc_info=True` logging
- Added `NotImplementedError` to 3 abstract methods in `engine/assets/base.py`
- Phone scene: RLock for thread-safe background ticker loop
- LMStudio client: `DEFAULT_LMSTUDIO_PORT` constant (no more hardcoded 1234)

### Test Coverage (+398 tests → 3,410 total)
- `test_resource_manager.py` — 82 tests: VRAM strategies, slots, eviction, TTL
- `test_model_manager.py` — 100 tests: lifecycle, tiers, reaper, CLI
- `test_conversation.py` — 78 tests: stateful threading, branching, fork
- `test_copilot_bridge.py` — 94 tests: full session lifecycle, savings tracking
- `test_housekeeping.py` — 44 tests: service checks, integrity, media scan

### Frontend Polish
- `api()` helper: 30s AbortController timeout + HTTP status error handling
- Toast notification system (info/success/error/warning with auto-dismiss)
- `withButton()` helper: auto-disable buttons during async operations
- `checkStatus()`: graceful offline handling instead of crash
- Librarian chat: NLM router (4-tier) integration with Q&A fallback

### Config & Deployment
- `production.yaml`: all 18 scenes with host/port/debug overrides
- `config/mcp.json`: env var support for Nexus path
- `pyproject.toml`: synced missing framework deps (fastmcp, flask, streamlit, etc.)
- `start_servers.ps1`: port conflict detection + try/catch error handling

## v0.54b — Sprint 14 Phase 2: NLM Intelligence Layer

### NLM Engine Modules (NEW)
- **`engine/nexus/har_extractor.py`** — Extract NotebookLM data from HAR files
  - 5-layer decode pipeline (XSSI → length-prefix → wrb.fr → inner JSON → content)
  - NotebookData/IngestResult dataclasses, cookie extraction, Nexus ingest
- **`engine/nexus/nlm_engine.py`** — Unified NLM client with dual backend (proxy:8800 + Nexus:3000)
  - Notebook CRUD, source management, batch Q&A, conversation, document generation
  - Graceful fallback between backends, NLMStats tracking
- **`engine/nexus/knowledge_forge.py`** — NLM knowledge orchestration
  - distill, decompose, analyze, polish, solve, export_training, build_topic, score
  - Question generation templates, ForgeResult/QAPair dataclasses
- **`engine/nexus/nlm_router.py`** — 4-tier NLM-first query router
  - Cache → FTS → NLM → LLM pipeline, all answers auto-stored
  - RouteResult with source_tier, confidence, savings metrics

### Copilot Self-Improvement (NEW)
- **`engine/nexus/copilot_bridge.py`** — Session lifecycle hooks
  - pre_plan, analyze_files, get_guide, track_tool_use, track_error, store_decision
  - Session metrics: compute savings, tool usage, file edits, errors
- **`.github/hooks/`** — Upgraded preToolUse/postToolUse/errorOccurred hooks
  - Nexus-first workflow enforcement (reminders on code edit without Nexus search)
  - CopilotBridge integration for tool tracking and error pattern analysis
- **All 18 `.agent.md` files** updated with Nexus-First Mandate preamble

### NLM MCP Skills (NEW)
- **`engine/skills/builtin/nlm_forge_skills.py`** — 10 @skill(pack="nlm_forge") functions
  - nlm_ask, nlm_batch_ask, nlm_create_notebook, nlm_add_codebase, nlm_generate_doc
  - nlm_distill, nlm_decompose, nlm_analyze, nlm_solve, nlm_build_topic

### NLM CLI (NEW)
- **`engine/nexus/nlm_cli.py`** — 16 terminal subcommands
  - ask, batch-ask, converse, create, list, delete, add-source, add-codebase
  - generate, distill, decompose, analyze, solve, forge, extract, stats

### Nexus Control Panel Upgrades
- **28 new API routes** — HAR ingestion, NLM queries, batch Q&A, forge operations
- **Ingestion Tab** — HAR drag-and-drop upload, codebase indexer, notebook browser
- **NLM Lab Tab** — 4-tier router query, batch Q&A workshop, plan decomposer,
  code analyzer, topic builder, savings dashboard
- **Explorer Upgrades** — Inline editing, bulk selection/delete, code syntax styling
- **Socket.IO** — Real-time progress streaming for batch operations

### Training Pipeline
- **`training/prepare_training.py`** — Added `--augment-nlm` flag
  - Connects KnowledgeForge.export_training() to dataset pipeline
  - NLM-distilled Q&A exported as fine-tuning JSONL

### Documentation
- **`docs/NOTEBOOKLM_HAR_SDK.md`** — 1,472-line SDK reference for batchexecute protocol

### Tests
- **113 new tests** across 4 files (har_extractor, nlm_engine, knowledge_forge, nlm_router)
- Total suite: 2,995 tests, all passing

## v0.53b — Sprint 14: Agent Infrastructure & Training Pipeline

### Port Registry (NEW)
- **`engine/port_registry.py`** — Central service port management
  - 25 default services, config integration, conflict detection
  - Service groups (scenes, streamlit, tts, infrastructure)
  - URL builder, summary report, singleton access via `get_port_registry()`

### MCP Server Split
- **`engine/mcp/devtools_server.py`** (NEW) — Extracted 38 Nexus/Copilot/System/Agent tools
  - FastMCP("CosySim-DevTools") — separate development workflow server
  - Nexus bridge (18 tools), Copilot (5), Agent (4), System (11)
- **`engine/mcp/cosysim_server.py`** — Now 106 game/scene/character tools only

### Agent Workflows (NEW)
- **`engine/workflows/agent_workflows.py`** — 5 configurable workflow patterns
  - `knowledge_distill` — Nexus → structured JSONL datasets
  - `dataset_curate` — Multi-source curation with quality scoring
  - `research_pipeline` — Automated Nexus Q&A + FTS research
  - `metrics_extract` — Test, codebase, training data metrics
  - `quality_audit` — Docstring/type-hint coverage, anti-pattern detection
  - CLI: `python -m engine.workflows.agent_workflows {workflow}`

### Dataset Curator (NEW)
- **`engine/nexus/dataset_curator.py`** — Nexus→training data pipeline
  - 4 output formats: instruction (Alpaca), chat_ml, sharegpt, raw
  - Quality filtering, deduplication, CurationStats tracking

### Training Data Quality
- **Deduplication:** Generators now over-generate 3x then dedup
  - Fixed 76-98% duplicate rates in tool_routing/priority/response datasets
- **Enhanced diversity:** Richer templates for all generators
- **Combined multi-task dataset:** 3185 unique examples (2865 train + 320 val)
- **`training/prepare_training.py`** — Preflight validation, multi-task combiner

### Doc Automation (NEW)
- **`.github/workflows/copilot-autofix.yml`** — Triggers on labeled issues + weekly
- Issue template + label definitions for documentation tasks

### Test Suite
- **2882 tests** passing (64 new: port registry 20, dataset curator 25, workflows 19)

---

## v0.52b — Sprint 13: Orpheus TTS & Nexus Cleanup

### Orpheus-FastAPI TTS Integration (NEW)
- **`engine/tts/orpheus_client.py`** — Second TTS backend alongside Qwen3
  - 25 named voices with mood→emotion mapping (CosySim moods → Orpheus tags)
  - Voice matching by gender/mood, streaming support, health checks
  - LMStudio-hosted inference (orpheus-3b-0.1-ft GGUF)
- **Skills:** `orpheus_speak`, `list_orpheus_voices` in tts_skills.py
- **Config:** `tts.orpheus` section in default.yaml

### Nexus KMS Cleanup
- **Routes split:** Monolithic routes.py (965 lines) → 5 Flask blueprints
  - entries.py (12 routes), nlm.py (11), admin.py (7), ingress.py (11), research.py (11)
- **Archive:** browser_bridge.py + notebooklm-skill/ → data/archive/ (preserved, not deleted)
- **Manager cleanup:** NLM manager now HTTP-only, browser_bridge fallback removed
- **Q&A telemetry:** _query_stats tracking (cache/FTS/NLM/none hit rates)
  - `/api/stats/query-resolution` endpoint for monitoring
  - Persistent logging to agent_activity table

### Test Suite
- **2818 tests** passing (22 new Orpheus tests)
- Nexus: 263 tests passing

---

## v0.52b — Sprint 10–12: Inference Bridge & System Improvements

### Copilot → LMStudio Task Bridge (NEW)
- **`engine/nexus/lms_task_bridge.py`** — Delegate subtasks to local LMStudio models
  - `run_prompt()` — Single prompt execution with metrics
  - `run_batch()` — Sequential batch execution with Nexus storage
  - `run_task()` — Structured tasks (evaluate, summarize, generate, classify, compare)
  - `check_lmstudio()` — Health check with loaded model listing
  - `TaskResult` dataclass with ok/tps/latency tracking

### Inference Leaderboard Skills (NEW)
- **`engine/skills/builtin/inference_skills.py`** — 5 MCP skills for benchmarking
  - `benchmark_model` — Run quick benchmark against loaded model
  - `store_benchmark` — Store results in Nexus leaderboard
  - `get_leaderboard` — Retrieve and compare performance data
  - `check_lmstudio_status` — Check server status and loaded models
  - `delegate_task` — Delegate structured tasks to LMStudio

### Nexus Client Enhancements
- **Access tracking** — `track_access()` and `search_ranked()` for relevance scoring
- **Benchmark storage** — `store_benchmark()` and `get_leaderboard()` for inference data

### Git → Nexus Auto-Sync (NEW)
- **`.git/hooks/post-commit`** — Every commit auto-stores in Nexus (message, files, branch)

### Copilot Instructions Updated
- Added "READ FIRST" section: full system access, LMStudio always running, proactive installs
- Added LMStudio task delegation documentation
- Strengthened pre-compaction dump instructions

### Tests
- 29 new tests (test_lms_task_bridge.py) — all passing
- Total: 2,758 tests passing

---

## v0.52b — Sprint 9: CI/CD & Agent Infrastructure

### GitHub Actions CI Pipeline (NEW)
- **`.github/workflows/ci.yml`** — Automated test pipeline
  - Triggers on push/PR to master
  - Python 3.12, pip cache, core deps only (no GPU)
  - Runs full test suite (2,729 tests)
  - 15-minute timeout with summary output

### Copilot Coding Agent Environment (NEW)
- **`.github/workflows/copilot-setup-steps.yml`** — Pre-install dependencies for remote Copilot agent
  - Installs core Python packages (pytest, flask, pydantic, etc.)
  - Verifies test collection before agent starts working
  - Enables autonomous issue resolution by Copilot

### Copilot Hook Scripts (NEW)
- **`.github/hooks/scripts/log-tool-usage.ps1`** — JSONL audit trail for all tool calls
- **`.github/hooks/scripts/check-tool-safety.ps1`** — Block destructive ops (delete/remove/drop/destroy/purge/truncate)
- **`.github/hooks/scripts/log-session.ps1`** — Session lifecycle logging
- **`.github/hooks/scripts/log-errors.ps1`** — Error logging to JSONL
- Updated `cosysim-hooks.json` to delegate to script files instead of inline commands

---

## v0.52b — Sprint 8.5: External Service Integration, URL Ingestion

### Sprint 8.5: External Services, URL Ingestion, Prompt Engineering

#### prompts.chat Integration (NEW)
- **`engine/skills/builtin/prompts_chat_skills.py`** — 5 MCP skills for prompt discovery
  - `search_prompts()` — Search prompts.chat by keyword, type, category
  - `get_prompt()` — Retrieve specific prompt by ID
  - `get_skill_from_prompts()` — Get Agent Skills with all files
  - `improve_prompt()` — AI-powered prompt enhancement
  - `ingest_prompts_to_nexus()` — Search & store best prompts in Nexus

#### URL Ingestion Pipeline (NEW)
- **`engine/nexus/url_ingest.py`** — Fetch web pages → markdown → Nexus
  - HTML-to-markdown converter (strips scripts/styles/nav, converts headers/lists/code/links)
  - `fetch_url()` for single page retrieval
  - `ingest_url()` for single URL → Nexus storage
  - `ingest_batch()` for bulk ingestion with result tracking
  - `IngestResult` / `IngestBatch` dataclasses with summary stats

#### GitHub Models Prompt Templates (NEW)
- **`prompts/character-dialog.prompt.yml`** — Character dialog quality evaluation
- **`prompts/skill-response.prompt.yml`** — Skill output format testing
- **`prompts/narration.prompt.yml`** — Scene narration quality evaluation

#### Copilot Agent Hooks (NEW)
- **`.github/hooks/cosysim-hooks.json`** — Session logging, tool audit, destructive op blocking
  - `sessionStart/End` — Log session lifecycle
  - `preToolUse` — Block delete/remove/drop operations
  - `postToolUse` — Audit trail for all tool calls
  - `errorOccurred` — Error logging

#### Nexus Knowledge Seeded (13 entries)
- 8 documents: GitHub Models (evaluators, .prompt.yml, API, prototyping), Copilot (hooks, best practices, environment, firewall), prompts.chat API
- 5 Q&A pairs: evaluation workflow, .prompt.yml format, hooks system, prompts.chat API, GitHub Models API

#### Tests: 2,729 passing (+47 new)
- `tests/test_prompts_chat_skills.py` — 17 tests
- `tests/test_url_ingest.py` — 30 tests

## v0.52b — Sprint 8: Knowledge, Tuning, Agents, QoL

### Sprint 8: Knowledge System, Inference Tuning, Agent Infrastructure, QoL

#### LMStudio Inference Tuning System (NEW)
- **`engine/lmstudio/auto_tuner.py`** — Iterative settings optimizer
  - `find_optimal()` tests configs per task type (roleplay, code, routing, chat, narration)
  - `test_hypothesis()` for CPU overflow, speculative decoding, context reduction
  - Stores optimal configs in Nexus as structured audit entries
- **`engine/lmstudio/inference_monitor.py`** — Live transaction monitoring
  - Per-model and per-tier rolling metrics (latency, TPS, error rate)
  - Queue depth tracking, bottleneck detection, periodic Nexus snapshots
  - Thread-safe singleton via `get_inference_monitor()`

#### Agent Task Scheduler (NEW)
- **`engine/nexus/task_scheduler.py`** — Priority-based task queue
  - `AgentTask` dataclass with priority, complexity, dependencies, allowed operations
  - `claim_task()` with preferred complexity/tag filtering
  - Dependency-aware scheduling, subtask support, Nexus sync
  - Singleton via `get_task_scheduler()`

#### Agent Onboarding Documentation (NEW)
- **`docs/AGENT_ONBOARDING.md`** — Self-onboarding guide for Copilot/local agents
- **`docs/LOCAL_AGENT_GUIDE.md`** — Safety rails for local LMStudio agents

#### Custom Agent Templates (8 NEW)
- `code-reviewer`, `bug-fixer`, `feature-builder`, `refactoring-agent`
- `benchmark-runner`, `config-optimizer`, `knowledge-curator`, `integration-tester`

#### QoL Automations (NEW)
- **Chrome Extension** (`deployment/chrome-nexus/`) — Right-click → Nexus, YouTube auto-import
- **PowerShell Scripts** (`deployment/scripts/`) — 5 scripts with toast notifications
- **AutoHotkey Hotkeys** (`deployment/autohotkey/`) — Win+Shift global shortcuts
- **Logitech Setup Guide** (`deployment/logitech/`) — M720 + MX Keys Mini mapping
- **Windows Scheduler** (`deployment/scheduler/`) — Automated overnight tasks

#### Nexus Knowledge Seeded
- Model catalog (49 models with tier assignments)
- Settings guide (temperature, concurrency, CPU/GPU)
- Sprint 7 technical audit findings
- 5 rating system entries (scenes, framework, Nexus, tools, Copilot)
- Audit storage rules

#### Documentation Updates
- ROADMAP.md: v0.51 marked done, v0.51b + v0.52b sections added
- README.md: Badge fixed (2682+), tool/skill counts updated
- INDEX.md: Scene count fixed (13), dead refs removed
- LMSTUDIO.md: Orchestrator, ResourceManager, ModelManager docs added
- copilot-instructions.md: v0.52b, 18 agents, Nexus-first rules

#### Test Count: 2,613 → 2,682 (+69)
- `tests/test_benchmark.py` — 11 tests: prompt bank, result/summary, run_quick, matrix, Nexus storage
- `tests/test_auto_tuner.py` — 14 tests: configs, find_optimal, hypotheses, Nexus storage
- `tests/test_inference_monitor.py` — 16 tests: metrics, transactions, bottlenecks, snapshots
- `tests/test_task_scheduler.py` — 28 tests: CRUD, claiming, dependencies, priorities, Nexus sync

## v0.52b — URL System, llmster, Audit Hardening, and Smart Infrastructure

### Sprint 7: System Audit & Hardening
- **CRITICAL FIX**: Added missing `LoadConfig` import in `resource_manager.py` — prevented NameError on model loading
- **FIX**: Removed duplicate `nexus_maintain()` in `cosysim_server.py` (was defined twice)
- **FIX**: `agent_state.py` migrated from hardcoded port 9400 to `NexusClient` — state persistence now works
- **Error handling**: All 144 MCP tools now wrapped with try/except — no more unhandled crashes
- **Config cleanup**: Annotated unused YAML sections (stt, security, testing, observability) as RESERVED
- **Config fix**: Added missing `llm.custom_context` key to `default.yaml`
- **Removed**: Empty `content/scenes/media/` placeholder directory
- **Docs accuracy**: Fixed `nexus_search_prompts` → `nexus_get_prompts`, clarified 4-tier query router
- **Test count**: 2,362 → 2,613 tests (+251)

### New Tests (Sprint 7)
- `tests/test_lounge.py` — 79 tests: heat management, song selection, drink system, trust gates, MCP syncing
- `tests/test_gallery.py` — 49 tests: gallery tick, mood drift, artworks, governor context, exhibitions
- `tests/test_games.py` — 60 tests: route registration, health, plugin info, game tracking, MCP wiring
- `tests/test_activity_bus.py` — 33 tests: push/pop, context manager, snapshot, concurrency, thread safety
- `tests/test_resilience.py` — 30 tests: circuit breaker states, recovery timeout, retry decorator, backoff

## v0.52b — URL System, llmster, and Smart Infrastructure

### Nexus URL Manager (NEW)
- **`engine/nexus/url_manager.py`** — Store, scrape, and dissect web content into Nexus knowledge
- `URLEntry` dataclass with metadata (title, synopsis, tags, domain)
- `WebScraper` — stdlib-based HTML scraping with guardrails (500KB max, domain blocklist, rate limiting)
- `ContentDissector` — intelligent chunking by headings, paragraphs, and sentence boundaries
- `URLManager` singleton — full lifecycle: add → scrape → dissect → store in Nexus
- Content types: `url` (bookmarks), `webpage` (full pages), `note` (dissected fragments)
- 33 tests covering all components

### LlmsterManager (NEW)
- **`engine/lmstudio/llmster_manager.py`** — wraps `lms` CLI for daemon/server management
- Daemon control: `daemon_up()`, `daemon_down()`, `daemon_status()`
- Server control: `server_start()`, `server_stop()`
- Model operations: `load_model()` with `n_parallel` (continuous batching), `unload_model()`, `list_models()`, `list_loaded()`, `download_model()`
- Runtime update: `runtime_update("llama.cpp")`
- Config: `lmstudio.llmster` section in `default.yaml` (n_parallel, unified_kv_cache)
- 29 tests covering CLI mocking, lifecycle, error handling

### Remote Inference (NEW)
- **`deployment/colab_lmstudio_setup.ipynb`** — Colab Pro setup notebook
- Install llmster, mount Drive, download models, start server, expose via ngrok
- GPU recommendations: L4 (Qwen3-30B-A3B), A100 (Llama-3.1-70B)
- Config: `lmstudio.remote_hosts` and `lmstudio.link` sections

### New MCP Tools
- **URL tools**: `nexus_add_url`, `nexus_list_urls`, `nexus_scrape_url`, `nexus_url_stats`
- **Llmster tools**: `llmster_status`, `llmster_load`, `llmster_unload`, `llmster_models`, `llmster_download`
- **Feature tracking**: `nexus_track_feature`, `nexus_list_features`
- **Total MCP tools**: 133 → 144

### Nexus Panel Routes
- `GET/POST /api/urls` — Add and list URLs
- `POST /api/urls/scrape` — Trigger URL scraping
- `GET /api/urls/stats` — URL system statistics

### Test Suite
- **2362 tests** across 70+ files — all passing
- New test files: `test_url_manager.py` (33), `test_llmster_manager.py` (29)

## v0.51b — Copilot CLI + Nexus Integration

### MCP Server — Nexus Bridge (NEW)
- **16 Nexus tools** added to CosySim MCP server — search, ask, add, Q&A, rules, prompts, research, converse, finish_research, import_youtube, log_session, status, list_plugins, seed_nexus, nexus_maintain
- **Skill discovery tools** — `list_all_skills()` shows all 194 skills by pack, `get_skill_info()` returns parameters and metadata
- **System status tool** — `system_status()` reports service health, model status, scene activity, skill counts
- **Knowledge seeder** — `seed_nexus(source)` populates Nexus with project docs, Q&A, rules, prompts, conventions
- **Knowledge maintenance** — `nexus_maintain(action)` for health stats, dedup, cleanup, reindex
- **Memory tools** — `nexus_remember`, `nexus_recall`, `nexus_memory_context` for agent/Copilot memory
- **Training tools** — `capture_training_data` for fine-tuning data capture
- **Content tools** — `generate_content` for pre-built dialog generation
- **Total MCP tools**: 107 → 133

### Nexus Namespace Separation (NEW)
- **7 namespaces** — system, scene, agent, copilot, training, research, content
- **Access control** — Per-namespace read/write rules, cross-namespace access matrix
- **Validation** — `validate_entry()` enforces content type, category, and tag rules
- **Auto-detection** — `detect_namespace()` infers namespace from category/tags
- **38 enforcement rules** installed (16 original + 22 namespace rules)
- **All entries retagged** with proper namespace tags

### NexusMemory System (NEW)
- **`engine/nexus/nexus_memory.py`** — Unified memory for Copilot and characters
- Methods: `remember()`, `recall()`, `get_context_window()`, `compact()`, `forget()`
- Factory functions: `get_copilot_memory()`, `get_character_memory(character_id)`
- Importance scoring, memory type classification, time decay
- FTS5-backed semantic recall via Nexus search

### Training Pipeline (NEW)
- **`engine/nexus/training_pipeline.py`** — Capture LLM interactions for fine-tuning
- Methods: `capture_interaction()`, `export_dataset()`, `generate_synthetic()`, `get_stats()`
- Exports JSONL compatible with `training/finetune_local.py`
- 5 dataset types: conversation, tag_extraction, tool_routing, response_quality, decision_classify
- Singleton via `get_training_pipeline()`

### Content & Research Workflows (NEW)
- **`engine/nexus/workflows.py`** — Three workflow classes
- **ContentWorkflow**: Generate greetings, reactions, scene descriptions per character/mood
- **ResearchWorkflow**: 3-tier lookup (Q&A cache → FTS → NLM), store findings
- **NotebookWorkflow**: Seed NotebookLM reference notebooks, check NLM status
- 72+ content entries generated (greetings, reactions, scene descriptions for 5 characters)

### Nexus Control Panel (NEW)
- **`engine/nexus/control_panel.py`** — Streamlit dashboard on port 8702
- Pages: Dashboard, Knowledge Browser, Rules Engine, Memory Viewer, Training Data, Research, Content Generator, Maintenance
- Namespace-filtered browsing, rule creation, memory management
- Training data capture/export, synthetic data generation
- Run: `streamlit run engine/nexus/control_panel.py --server.port 8702`

### Copilot CLI Wiring (NEW)
- **`.vscode/mcp.json`** created — CosySim + Nexus MCP servers now accessible from Copilot CLI
- **Copilot Workflow agent** — New master agent (`copilot-workflow.agent.md`) with Nexus-first workflow
- **Updated copilot-instructions.md** — v0.51b, MCP tool docs, Nexus workflow, 10 agents
- **Updated global instructions** — `~/.copilot/copilot-instructions.md` with Nexus-first workflow

### Nexus CLI Bridge (NEW)
- **`python -m engine.nexus.bridge`** — Standalone CLI for Nexus access without MCP server
- Commands: search, ask, store, qa, rules, health, seed, maintain
- JSON output for machine parsing
- Fallback when MCP server is not running

### Nexus Knowledge Seeder (NEW)
- **`engine/nexus/nexus_seeder.py`** — Idempotent knowledge seeder utility
- Seeds: 16 doc entries, 20+ Q&A pairs, 16 governance rules, 9 agent prompts, 4 coding conventions
- CLI: `python -m engine.nexus.nexus_seeder [docs|qa|rules|prompts|conventions|all]`

### NexusPromptInterceptor (NEW)
- **Priority 4** interceptor that enriches agent prompts with Nexus knowledge
- Loads base agent prompt, governance rules, and scene-specific context at runtime
- TTL-cached (5 min) to avoid excessive Nexus API calls
- Registered in `config/default.yaml` under `comms.interceptors`

### Infrastructure Fixes
- Fixed `system_status` tool — corrected stale `get_skill_registry()` → `SKILL_REGISTRY`
- Fixed `list_all_skills` and `get_skill_info` — same stale import fix
- Fixed session logger — `nexus_session_logger.py` now uses `/api/entries` (was broken `/api/agent/submit`)
- Enhanced session logger — captures git context (branch, commits, modified files)
- Fixed `test_nexus_bridge.py` — updated for fastmcp 3.0 API (`mcp.list_tools()`)
- Added `autoStart: true` to `.vscode/mcp.json` for both servers

### Knowledge Distillers (NEW)
- **`engine/nexus/nexus_distiller.py`** — 4 knowledge distillers
- **NexusDistiller** — Extracts decisions, bug fixes, file conventions from conversation logs; compacts daily sessions; generates context primers
- **QADeduplicator** — Finds and merges near-duplicate Q&A pairs using word-level Jaccard similarity (threshold: 0.75)
- **SkillUsageDistiller** — Analyses session logs for MCP skill/tool usage frequency, errors, underutilisation
- **PromptEvolutionDistiller** — Tracks prompt version lineage, analyses structural patterns (role defs, constraints, guardrails, output formats)
- **`run_all_distillers()`** — Runs all 4 distillers in sequence
- CLI: `python -m engine.nexus.nexus_distiller [distill|compact|stats|primer|dedup|skills|prompts|lineage|all]`
- MCP tool: `nexus_distill(action)` supports all 10 actions
- **Session export tool** — `nexus_export_session()` exports current Copilot session to Nexus

### Session Logger Upgrade
- **Full conversation export** — Reads from Copilot session_store SQLite DB on session end
- Exports: conversation log, session summary, checkpoints, plan, auto-extracted decisions as Q&A
- Stores complete turn history (USER/ASSISTANT) with truncation for large sessions
- Session start/end entries tagged with git branch for filtering

### Documentation Overhaul
- **New: `docs/COPILOT_SYSTEM.md`** — Complete Copilot CLI system documentation: hooks, memory loop, MCP tools, distillers, CLI bridge, instruction hierarchy, custom agents, token reduction strategy
- **Rewritten: `docs/NEXUS_INTEGRATION.md`** — Full v0.51b coverage: namespaces, memory, distillers, training pipeline, workflows, control panel, seeder, bridge, interceptor
- **Updated: `docs/INDEX.md`** — Added COPILOT_SYSTEM.md, updated Nexus description
- **Updated: `README.md`** — Test count (2,048+), MCP tool count (133), Nexus Control Panel in services, project stats refresh

### Nexus CLI (NEW)
- **`python -m engine.nexus.cli`** — Full CLI for Nexus: search, ask, add, qa, status, prompts, rules, youtube
- JSON output mode with `--json` flag
- Argument parsing with subcommands and options

### Tests
- **155 new tests** — Nexus bridge (24), seeder & bridge (79), Phase 2 (52)
- Total tests: 2,048 passing (10 pre-existing sdk_client failures)

## v0.51 — Multi-Model Orchestration & Skill Wiring

### InferenceOrchestrator (NEW)
- **Unified inference API** — Single `infer()` call bridges ModelManager, InferenceRouter, and ResourceManager
- **Agent profiles** — Register per-agent model preferences (tier, temperature, token budget)
- **Tier-aware routing** — Automatic tier selection: classify→router, act/tools→GPU, background→utility
- **Performance tracking** — Rolling TPS/latency per tier with adaptive routing (high error rate → fallback)
- **Runtime config** — Update model mode, strategy, VRAM caps, concurrency at runtime via `update_config()`
- **Comprehensive status** — Unified status API aggregating orchestrator + model manager + resource manager

### Phone Skills — Wired to Database
- `phone_send_message` — Now persists via `phone_db.save_message()` with Socket.IO broadcast
- `phone_check_messages` — Enhanced with total unread count, message previews, and unread markers
- `phone_start_game` — Creates persistent game session via `phone_db.create_game_session()`
- `phone_game_action` — Updates game state with action history and round tracking
- `phone_generate_image` — Integrates ComfyUI for real image generation, saves to gallery thread
- `phone_toggle_autotxt` — Sets scene `_autotxt_muted` flag with Socket.IO status broadcast

### Config Validator Upgrade
- Added 11 LMStudio config validations: `load_mode`, `concurrent_slots`, `jit_ttl_seconds`, `vram_cap_mb`, `strategy`, `default_ttl`, `gpu`, `context_length`
- Added `values` validation support (enum-like allowed value checking)
- Added `logging.level` allowed values validation
- Schema expanded from 8 → 22 validated keys

### Gallery Scene Upgrade
- Added background ticker (45s interval) for ambient mood drift and visitor events
- Characters now evolve mood autonomously between skill calls
- Ambient gallery events (visitors, lighting shifts) add atmosphere
- State broadcast on each tick for real-time UI updates
- Proper `stop()` cleanup with ticker thread join

### Scene Consistency
- Fixed 5 scene `__init__.py` files (bedroom, casino, lounge, tavern, warzone)
- All 13 graded scenes properly export scene class in `__all__`

### Tests
- **64 new tests** (1,839 → 1,903 total): orchestrator (25), phone skills (19), config validator (20)

## v0.50b — Nexus Q&A, Research Manager & YouTube Import

### Bedroom v6 — Camera Views & Layout Overhaul
- **Camera view presets** — 8 preset views (Overview, Bed, Couch, Bath, Fireplace, Vanity, Bar, Balcony) with smooth animated transitions
- **Room layout reorganized** — 16×14 room with 4 distinct wall areas: bed (left), couch+bath (right), bar+vanity (back), fireplace+balcony (front)
- **View controls** — Prev/Next cycle buttons, zoom slider, expanded orbit controls
- **Stats fix** — `compliance_score` field name mismatch fixed between backend and frontend
- **Furniture scaling** — Bed 3.4×4.6, bathtub 2.2 z-axis, all sized for avatar containment

### Scene Consistency Fix
- Fixed 5 scene `__init__.py` files missing scene class imports (bedroom, casino, lounge, tavern, warzone)
- All 13 graded scenes now properly export their scene class in `__all__`

### Project Documentation
- Added `ROADMAP.md` — Structured roadmap from v0.51 through v0.55+ with scene quality targets

### NexusClient — 10 New Methods
- `ask()`: Query the Q&A cache → FTS5 → NLM pipeline
- `find_qa()`: Search the Q&A distillation cache
- `add_qa()`: Store a question-answer pair in the cache
- `research()`: Start a multi-turn research session
- `converse()`: Continue a research conversation with follow-ups
- `finish_research()`: Close a research session and return summary
- `list_research()`: List research sessions by status
- `import_youtube()`: Ingest a YouTube video transcript into Nexus
- `list_plugins()`: List registered plugin hooks
- `add_plugin()`: Register a plugin script for a lifecycle hook

### Nexus Skills (10→16)
- `nexus_ask`: Ask against Q&A cache and NLM pipeline
- `nexus_research`: Start a multi-turn research session
- `nexus_converse`: Continue a research conversation
- `nexus_finish_research`: Close research session with summary
- `nexus_youtube`: Import YouTube transcript into knowledge base

### New Subsystems
- **Q&A Distillation Cache** — Stores distilled question-answer pairs for instant lookup before falling back to FTS5/NLM
- **Research Manager** — Multi-turn investigative sessions backed by Q&A cache → FTS5 → NLM pipeline
- **YouTube Transcript Ingestion** — Downloads, chunks, and indexes video transcripts as knowledge entries
- **Plugin System** — Lifecycle hooks (post_ingest, pre_query, post_query, on_research_close) for extending Nexus pipelines

### Stats
- **MCP Skills**: 165 across 23 packs (10 core + 13 scene)
- **Nexus Skills**: 16

---

## v0.50a — Master Consolidation & Nexus Integration

### Nexus Schema v2
- Added `rules` table: scope-based governance with condition/action JSON, priority, enabled flag
- Added `sessions` table: project/repo/branch tracking, commits, files_changed, skills_used
- Schema version bumped 1→2
- Added 9 new NexusStore methods: rules CRUD, sessions CRUD, batch_add_entries
- Added 14 new API routes for rules, sessions, batch, type-filtered entries
- 19 new Nexus tests (150→169 passing)

### NexusClient Upgrade
- Session tracking: log_session, update_session, get_session, list_sessions
- Rules engine: get_rules, add_rule
- Prompt management: store_prompt, get_prompts
- Batch operations: batch_add
- Changelog tracking: store_changelog
- list_by_type shortcut
- Retry logic with exponential backoff (configurable max_retries)

### Nexus Skills (4→10)
- `nexus_log_session`: Session tracking
- `nexus_store_prompt`: Prompt versioning
- `nexus_search_prompts`: Prompt discovery
- `nexus_get_rules`: Rules retrieval
- `nexus_submit_idea`: Improvement ideas
- `nexus_changelog`: Change history

### Documentation
- Created `docs/NEXUS_INTEGRATION.md` — comprehensive integration guide
- Updated README.md to v0.50a with Nexus-first philosophy, 1832 tests, 13 game scenes
- Updated SKILLS.md to v0.50a with all 148+ skills documented
- Updated SCENES.md port map with Tavern + Games

### Stats
- **Tests**: 1,832 passing (CosySim) + 169 passing (Nexus) = **2,001 total**
- **MCP Skills**: 148+ across 23 packs (10 core + 13 scene)
- **Game Scenes**: 13
- **Nexus Skills**: 10

## Sprint 16 — Scene Upgrades & Framework Showcase

### 16a — Dragon's Flagon Tavern (New Showcase Scene)
- **New scene**: Fantasy tavern on port 5558, demonstrates every MCP framework feature
- **State**: TavernState with gold economy, 6-stat system, 4-NPC reputation (5 tiers), atmosphere/heat meter, quest board (5 quests), rumor system (8 rumors), dice gambling, time-of-day cycle, stranger appearances
- **Skills**: 10 MCP skills — status, order_drink, check_reputation, hear_rumor, quest_board, dice, influence, request_song, trade, advance_time
- **Rules**: Atmosphere directives, time directives, reputation gates, stat-gated actions, full LLM directive builder
- **Web UI**: NPC cards, rep bars, stat displays, action buttons, dice game, quest board, merchant, event feed, real-time SocketIO
- **Tests**: 76 tests covering state, rules, and constants

### 16b — Games Scene Upgrade (F→C+)
- Converted from bare Flask Blueprint to proper `GamesScene(BaseScene)` on port 5567
- 7 MCP skills wrapping MysteryGame and TruthOrDareGame programmatic APIs
- Skills: games_status, mystery_start/clue/accuse, tod_start/roll/answer

### 16c — Gallery Skills Upgrade (C+→B-)
- 5→8 skills with module-level state tracking (prestige, patron_mood, visitor_count, artworks)
- New: gallery_set_theme (6 themes), gallery_auction (simulated bidding war), gallery_patron_interact
- Upgraded: create_art (10 style validation), critique (3-axis scoring, masterpiece detection), change_room (prestige gate)

### 16d — Warzone Skills Upgrade (stubs→real)
- 5→7 skills wired to actual GameState.process_action() engine
- attack (weapon vs defense with crits/intercepts), build (4 building types), upgrade (weapon/defense)
- special_op (spy/emp/sabotage/shield/taunt), recon, end_turn (AI turn + income + weather)

### 16e — Lounge Skills Upgrade (stubs→real)
- 5→10 skills wired to trust/heat/secrets/song state
- Trust-gated cocktails, intimacy-leveled secret sharing, progressive secret unlocks
- Back room access (trust ≥70), heat management, dream whisper & mirror soul (trust-gated)

### 16f — Casino Skills Upgrade
- 6→9 skills with new poker mechanics
- check (stay in hand), raise (minimum $10), bluff (style-based success rates)

### Skill Count Summary
| Scene | Before | After |
|-------|--------|-------|
| Tavern | NEW | 10 |
| Games | 0 | 7 |
| Gallery | 5 | 8 |
| Warzone | 5 (stubs) | 7 |
| Lounge | 5 (stubs) | 10 |
| Casino | 6 | 9 |
| **Total** | **21** | **51** (+30 skills)

## Sprint 15 — Nexus Knowledge System & Documentation Overhaul

### 15a — Documentation Overhaul
- Consolidated 31 → 20 docs, zero duplicates
- **New docs**: ARCHITECTURE, SCENES, CHARACTERS, CONFIGURATION, TESTING, TRAINING, INDEX
- **Rewrote**: README (absorbed QUICK_START+CHEATSHEET), MCP_FRAMEWORK (consolidated with MCP_ARCHITECTURE), API (538 lines from source), ONBOARDING, CONTRIBUTING
- **Deleted**: 11 stale/duplicate files (-7,476 lines)
- **Archived**: AGENT_NOTES + AGENT_REVELATIONS → docs/internal/

### 15b — Nexus Knowledge Management System (C:\Files\Nexus)
- New standalone project: 33 Python files, 3,253 lines
- 3-layer database: NLM Mirror, Ground Truth, Working Layer (14 tables + FTS5)
- REST API: 38 routes on port 8700
- MCP Server: 21 tools via FastMCP (stdio/SSE)
- Dashboard: Dark-themed web UI on port 8701
- 4 ingress adapters: NLM sync, manual, agent, pipeline
- CosySim integration: NexusClient + 4 nexus skills + mcp.json wiring
- Tests: 150 passing (Nexus), 1,756 passing (CosySim)

### 15c — NotebookLM Dual Backend
- Browser bridge: Patchright-based browser automation (notebooklm-skill submodule)
- NLMManager: Auto backend selection (HTTP → browser fallback)
- 7 new API routes, 3 new MCP tools
- Config: prefer_backend: auto | http | browser

## Sprint 14 — Framework Adoption & Scene AAA Upgrade
- **Monolith split**: cosysim_server.py → engine/mcp/tools/ (8 domain modules, 67 functions extracted)
- **Governance migration**: All 11 scenes now use build_governance_context() + StateCoordinator
- **CommandCenter**: Live scene feed, status cards, character viewer, scene control, system metrics
- **Realm gameplay**: d20 combat, 10 locations, equipment (12 items), economy (gold/shop/levels)
- **Tests**: 1,756 (was 1,397, +359 new tests)
- Test files: dialog_system, scene_rules_engine, character_registry, interaction_trees, character_agent, bedroom_game, casino_game, phone_routing

## Sprint 13 — Training Pipeline, NotebookLM MCP, TTS Streaming
- **Training**: merge_adapters.py, 4 training skills, evaluate_model(), 2100 dataset examples
- **NotebookLM MCP**: proxy server, 5 skills, config, Phone Research app
- **TTS streaming**: sentence-level chunking, SSE endpoint, WebSocket endpoint
- **Dead code**: Removed shadowed functions + unused protocol
- **Tests**: 1,397 (was 1,313, +84 new tests)

## [4.0.1] — 2026-02-24

### TagRegistry — Extensible Tag System
- **TagRegistry singleton** (`engine/mcp/tag_registry.py`) — thread-safe, extensible tag definitions
- **9 built-in tags**: MOOD, IMAGE, ACTION, STAT, VOICE (original) + SEND, EVENT, MEMORY, THINK (routing)
- **Scene-specific tags**: Heist `[PLAN:]`, Warzone `[ORDER:]`, NeonCity `[HACK:]`
- **Consumer refactoring**: StreamProcessor, StreamWatcher, TokenRouter all use TagRegistry for strip patterns and intent maps
- **52 new tests** for TagRegistry (detection, stripping, custom tags, dispatch, integration)

### Scene Framework Upgrades (all 10 scenes)
- **Shared frontend assets** — `register_shared_assets()` Blueprint serving `/shared/css/` and `/shared/js/`
- **SceneStateManager** wired into all scenes for unified state bridge to MCP skills/interceptors
- **TagRegistry** initialized in all scene `__init__` methods
- **Casino** — state sync bridge (chips, pot, round, phase) to SceneStateManager
- **NeonCity** — upgraded with TagRegistry, shared assets, SceneStateManager, custom [HACK:] tag

### Overlay Router Monitoring
- **`/overlay/api/router`** (GET) — live queue depth, tier counts, priority distribution, slot usage
- **`/overlay/api/router`** (POST) — live config changes: queue depth, preemption, per-tier slot/enabled
- **`/overlay/api/router/tiers`** (GET) — per-tier model key, device, max/busy/available slots
- **Conversation overlay bugfix** — fixed `_history` attribute error (now uses `turn_count` property)

### Testing
- **1143 tests passing** across 40 test files (up from 1084)
- New: `test_tag_registry.py` (52 tests), `test_overlay_router.py` (7 tests)

## [0.49] — 2026-02-23

### API-Complete LMStudio v1 REST Client
- **Authentication** — Optional Bearer token support (`lmstudio.api_token` in config); injected into all HTTP requests
- **Rich model listing** — `LMSModel` dataclass with full API fields: publisher, quantization (name, bits_per_weight), size_bytes, format, capabilities (vision, trained_for_tool_use), description, max_context_length
- **Model load response** — `LMSLoadResult` with instance_id, load_time_seconds, status, optional echoed load_config
- **Model download** — `download_model()` for catalog/HuggingFace downloads; `download_status()` for progress tracking
- **Unload fix** — Now sends `instance_id` field per API spec (was `model`)
- **LoadConfig fix** — Correct field name `offload_kv_cache_to_gpu` (was `keep_model_in_memory`)
- **MCP completeness** — `allowed_tools` and `headers` support on `MCP.ephemeral()` and `MCP.plugin()` helpers
- **Speculative decoding** — `enable_speculative(main, draft)` / `disable_speculative(draft)` convenience methods; `draft_model` wired through to chat payload via `InferenceConfig.to_native_v1()`
- **invalid_tool_call** — Properly parsed from output array (logged as warning, not appended to tool_calls)

### New Dataclasses
- `LMSModel`, `LMSModelInstance`, `LMSQuantization`, `LMSCapabilities` — Rich model metadata
- `LMSLoadResult` — Structured load response (replaces bool)
- `LMSDownloadJob`, `LMSDownloadStatus` — Download lifecycle tracking

### Testing
- **734 tests passing** across 28 test files (up from 699)
- 35 new tests covering: auth injection, rich model parsing, load result parsing, unload fix, download endpoints, MCP helpers, speculative decoding, invalid_tool_call parsing

## [0.48] — 2026-02-22

### Showcase Scenes (MCP Framework Demos)
- **The Realm** (port 5562) — Director-guided LitRPG with dual-agent orchestration (Director + Assistant), inventory/stats system, Murder Mystery sub-module, Memory Echoes, Desperation Dice, Fourth-Wall Inventory, Mutiny Mode
- **NeonCity** (port 5563) — Cyberpunk strategy board game with procedural city grid, Glitch Storm mechanic, 5 prefab nodes (AI Corp, Implant Shop, Mr. Wong's, Black Market, Noodle Stand), movement/combat/hacking phases
- **The Coders Room** (port 5564) — AI agent idle simulation where agents write real Python code in sandboxed environments, 3 roles (Writer, Reviewer, QA), feature request pipeline, live code output

### MCP Skills for Showcase Scenes
- **realm_skills.py** — 11 @skill functions: inventory CRUD, stat checks, director control, murder mystery management, fourth-wall mechanics, desperation dice
- **neoncity_skills.py** — 8 @skill functions: player status, movement, combat, hacking, storm queries, event triggers, turn management
- **coders_skills.py** — 6 @skill functions: feature queue, pipeline control, sandbox execution, agent status, tick advancement

### Framework Enhancements
- **BaseScene `_ACTIVE_SCENES` registry** — Module-level dict + `get_active_scene(name)` for in-process scene→skill bridge
- **Error hardening** — Realm `_director_infer()` wrapped in try/except with graceful fallback narration; NeonCity `_narrate()` logs failures
- **NeonCity state helpers** — `get_player()`, `is_in_storm()` methods on NeonCityState
- **29 Flask route integration tests** — Index renders, scene_info, error states, /api/health, skill registration verification

### Testing
- **699 tests passing** across 27 test files (up from 670)
- New: test_realm.py (35), test_neoncity.py (26), test_coders.py (22), test_scene_routes.py (29), test_pipeline_smoke.py (4)

## [0.47] — 2026-02-22

### MCP Framework v2 — Complete Rewrite
- **MCPFramework** — Central orchestrator: scene registration, character nodes, event bus, cross-scene messaging
- **MCPSceneMixin** — Drop-in mixin for Flask scenes: auto-registers with framework, provides state manager, rules engine
- **MCPCharacterNode** — Per-character state container: mood, energy, relationship, conversation history, streaming state
- **AgentGovernor** — Pre/post inference interceptors: content filtering, mood sync, stat injection
- **InterceptorPipeline** — Ordered chain of InterceptorBase subclasses for prompt/response modification
- **DialogSystem** — DialogTree with DialogNode branching, ConversationState tracking, SpeechEnhancer
- **MCPGameSession** — Turn-based game state: MCPGameNode, GameSessionInterceptor, rules engine integration
- **SceneRulesEngine** — Permission matrix, conversation heat tracking, threshold rules
- **AgentRouter** — Multi-agent routing with priority, load balancing, fallback chains
- **CharacterRegistry** — CharacterProfile + CharacterState + CharacterRecord persistence
- **SceneStateManager** — NarrativeLog, StatsSnapshot, state persistence
- **SharedBoardManager** — Cross-agent shared state for board games
- **InteractionTrees** — Branching interaction flows with conditions

### MCP Skills Server
- **skills_server.py** — FastMCP server exposing SKILL_REGISTRY packs as MCP tools
- **game_mcp.py** — Game-specific MCP tools for session management

### Scenes Added
- **Warzone** (port 5561) — Turn-based tactical combat with MCP game sessions
- **Gallery** (port 5560) — Art evaluation showcase with structured JSON critique and image generation

### Pipeline Consolidation
- **Unified inference path** — All agents route through VirtualAgentManager → LMSClient
- **Evaluator system** — Post-inference quality evaluation with configurable thresholds
- **Content router** — Automatic routing of responses to appropriate handlers

## [0.46] — 2026-02-22

### Pipeline Consolidation
- **VirtualAgentManager** — Single inference router: request building, model selection, conversation management
- **InferenceRequest / InferenceResponse** — Typed dataclasses for all inference calls
- **ConversationManager** — Manages Conversation objects per agent, auto-creates on first use
- **Evaluator** — Post-inference response quality checks

### Agent Governance
- **AgentGovernor** — Wraps VirtualAgentManager with interceptor pipeline
- **Pre-call interceptors** — Modify system prompt, inject context, enforce rules
- **Post-call interceptors** — Extract mood tags, validate content, update stats

## [0.45] — 2026-02-22

### Stateful Conversations
- **ConversationManager** — Thread management with response_id tracking
- **Conversation** — `branch_at()`, `fork()`, `send_stateless()` for conversation branching
- **Pipeline fixes** — Corrected governance_context flow, fixed interceptor ordering

## [0.44] — 2026-02-24

### Scene Upgrades
- **Phone scene** — `infer_processed()` streaming, rich responses (mood/image/voice tags), ComfyUI image gen on `[IMAGE:]` tags
- **Agent loop** — `infer_processed()` for mood/stat extraction, `store=False`, framework mood sync
- **Gallery scene** (NEW) — v2.7 framework showcase: streaming art evaluation, structured JSON critique, debate with branching, image generation

### StreamProcessor — Real-Time Response Processing
- **New `engine/agents/stream_processor.py`** — Consumes LMSStreamEvent objects in real-time
- **Inline tag extraction** — `[MOOD:x]`, `[IMAGE:prompt]`, `[ACTION:x]`, `[STAT:name±val]`, `[VOICE:style]`
- **ProcessedResponse dataclass** — Rich response with clean_text, mood_tags, image_requests, action_tags, tool_calls, reasoning
- **Real-time callbacks** — on_delta, on_mood, on_tool_call, on_image_request, on_action, on_stat_delta
- **Tool call lifecycle tracking** — start → arguments → success/failure with ToolCallRecord

### VirtualAgentManager Streaming Integration
- **`infer_processed()`** — Combines `infer_stream()` + StreamProcessor for rich responses
- **InferenceResponse v2.7.1** — `from_processed()` factory, mood_tags/image_requests/action_tags fields
- **VirtualAgent `_last_response`** — Stored for governor access to rich metadata
- **AgentGovernor context bridge** — Post-call interceptors get mood_tags, image_requests, action_tags, processed, reasoning, tool_calls

### SceneAgent v2.7.1
- **`run_structured()`** — JSON schema enforcement via structured output, store=False
- **`run_stream()`** — Streaming with StreamProcessor, returns ProcessedResponse
- **`decide()`** — Structured decision-making for game/narrative choices
- **Store=False default** — All SceneAgent calls are stateless by default

### MessagesApp Rewrite
- **ConversationManager-backed threads** — Each DM thread = stateful conversation
- **Rich messages** — MessageEntry with image_url, voice_url, mood, actions, response_id
- **Agent-integrated send()** — Routes through AgentGovernor or VirtualAgentManager with streaming
- **Unsolicited messages** — Characters can initiate messages via `receive_unsolicited()`

### CosySim MCP Server — New Tools
- **`send_selfie()`** — ComfyUI image generation with structured JSON + display_hint
- **`send_voice_message()`** — TTS generation with structured response
- **`query_stateless()`** — Disposable store=False utility queries
- **`get_conversation_info()`** — Conversation state + forkable response_ids
- **`fork_conversation()`** — Create conversation branch at specific turn

### Dialog System Branching
- **ConversationState** — Tracks response_ids and mood_history
- **`try_alternatives()`** — Generates multiple store=False responses, scores them
- **`branch_point()`** — Fork conversation at decision points

### Game MCP Structured Turns
- **`process_turn_structured()`** — JSON schema output for game decisions
- **Response ID tracking** — Game turn replay/undo via recorded response_ids

### Rules Engine Streaming
- **`apply_stream_deltas()`** — Real-time stat updates from StreamProcessor StatDelta objects
- **`evaluate_threshold_rules()`** — Check triggered rules after mid-stream stat changes

### Framework Events & Scene Lifecycle
- **MCPCharacterNode streaming state** — is_streaming, stream_tokens, last_mood
- **`emit_stream_event()`** — Real-time UI events via MCPFramework
- **BaseScene streaming** — streaming_enabled toggle, active_streams/total_stream_tokens in health
- **466 tests pass** (up from 424)

## [0.43] — 2026-02-23

### LMStudio v1 Native API (Full Support)
- **Native v1 protocol** — All inference via `/api/v1/chat` (input + system_prompt format)
- **Typed SSE streaming** — `event: <type>\ndata: <json>` parsing for all 18 v1 event types
- **Stateful conversations** — `response_id` / `previous_response_id` for server-side KV cache
- **Conversation branching** — `branch_at()`, `fork()`, `send_stateless()` on Conversation
- **Store control** — `store=False` for one-off queries, `store=True` for stateful chats
- **System prompt evolution** — Automatic detection and replay on system prompt changes

### Agent Stack v2.7
- **Stateful-first routing** — VirtualAgentManager routes through ConversationManager as primary path
- **Streaming inference** — `infer_stream()` with typed `LMSStreamEvent` callbacks
- **Response tracking** — `response_id` tracked in VirtualAgent._state and Conversation._response_id_history
- **InferenceRequest** — New fields: `store`, `stream`, `on_event`
- **InferenceResponse** — New fields: `reasoning_tokens`, `server_tps`, `time_to_first_token_s`, `is_stateful`

### Governance Context Bridge (Critical Fix)
- **Interceptor → Agent prompt flow** — `governance_context` kwarg passes interceptor pipeline output to VirtualAgent.build_request()
- **ResponseContext v2.7 keys** — `response_id`, `is_stateful`, `store`, `reasoning`, `tool_calls`
- **Governor populates response metadata** — Post-call interceptors can make branching decisions

### Cleanup
- **Deleted** `engine/lmstudio/lms_sdk.py` (unused Python SDK wrapper)
- **Deprecated** `engine/lmstudio/client_v2.py` (test-only)
- **424 tests pass** (up from 359)

## [0.20] — 2026-02-20

### Three Pillars Architecture
- **LMStudio Deep Integration** — REST client v2 (`engine/lmstudio/client_v2.py`) with `/api/v1/` protocol support, per-request MCP integrations, SSE streaming, abort support
- **FastMCP Server** — 9 tools + 5 resources exposing CosySim capabilities to LMStudio (`engine/mcp/cosysim_server.py`)
- **FastAPI Web Bridge** — SSE streaming proxy, file upload, CORS (`engine/mcp/web_bridge.py`)
- **CharacterAgent MCP Mode** — Agents use REST API with MCP integrations when enabled, fallback to SDK

### Voice Generation
- **Qwen3-TTS Server** — FastAPI + FastMCP on port 8600, real model loading from `pretrained_models/`, placeholder WAV fallback
- **Voice Designer** — `CASTING_OFFICE` registry with 6 presets, zero-shot support, character voice persistence
- **Voice Message Pipeline** — VoiceMessageGenerator → Qwen3-TTS HTTP → WAV files in `content/media/voice_messages/`
- **Long-form Audio** — Sentence-boundary chunking for 10s to 60min generation
- **TTS Skills** — 4 skills: generate_voice_message, list_voicemails, cast_voice, get_voice_status

### KPI & Benchmarking
- **KPI Dashboard** — LLM latency, token throughput, system monitor (CPU/RAM/VRAM), chain analytics
- **LLM KPI Tracking** — Per-call timing, tokens/sec, model comparison
- **Timeseries Store** — Rolling window benchmarks with export support

### Agent System
- **CharacterAgent in Scenes** — Phone and bedroom scenes use CharacterAgent with skill packs
- **AgentLoop Skill Cascade** — agent.reply() → quick_query() → HTTP → random fallback
- **Location-Aware Perception** — Agents know what activities are available and whether location is private
- **Enriched Idle Actions** — Context-sensitive idle descriptions based on current location

### Scenes
- **Phone Scene** — Arousal engine (5 NSFW tiers), spontaneous media, autonomous voice messages, dynamic mood
- **Bedroom Scene** — Multi-agent spatial system, 7 locations, 2-character AgentLoop, emergent behavior
- **Hub Scene** — Three Pillars status panel, health strip (4 services), scene launcher cards
- **Admin Panel** — 12-page modular admin with GOD mode, RAG editor, chain browser, config editor, KPI dashboard
- **Scene Creator** — Wizard with 4 templates, scaffolding, onboarding

### Framework
- **EventChain Ground Truth** — chain_id/parent_id causal trees, 16+ event types, complete interaction logging
- **DB CRUD** — 10 tables (incl. character_relationships), full CRUD + search/pagination
- **Media Standards** — MediaConfig singleton from YAML: selfie 512×768, video 640×480, audio 22050Hz
- **PromptBuilder** — 5-tier escalation for image/video prompts
- **Logging & Monitoring** — `@timed` decorator, SystemMonitor, ring buffer, structured logging
- **Resilience** — Retry with exponential backoff, circuit breaker, config validation
- **Scene Registry** — Dynamic scene discovery and registration

### Testing
- **315 tests** across 15 test files
- **18 integration tests** spanning all three pillars
- **22 live wire tests** validating real service connections
- Test command: `python -m pytest tests/ -v`

### Documentation
- `docs/THREE_PILLARS.md` — Architecture overview
- `docs/LMSTUDIO.md` — Deep integration guide, MCP setup, streaming
- `docs/TTS.md` — Qwen3-TTS voice design, casting office
- `docs/KPI.md` — Benchmarking, metrics, dashboard usage
- `docs/STRUCTURE_GUIDE.md` — Complete project structure
- `docs/SKILLS.md` — Skill system and MCP tools
- `docs/COMFYUI.md` — ComfyUI integration guide
- `docs/API.md` — API reference

---

## [1.0.0] — Initial Release

- Basic phone scene with LLM chat
- ComfyUI image generation
- SQLite database
- Character system with personalities
- RAG memory via ChromaDB
