# Changelog

All notable changes to CosySim are documented here.

## v0.60.2 — System Control Panel + NLM Client Class

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
