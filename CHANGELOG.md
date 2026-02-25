# Changelog

All notable changes to CosySim are documented here.

## v0.50b — Nexus Q&A, Research Manager & YouTube Import

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
