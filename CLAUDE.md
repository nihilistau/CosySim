# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Rules

These rules override all defaults. Follow them exactly — no exceptions.

1. **Never declare "fixed" without proof.** Run the app or tests and show passing output before reporting success. "This should work now" is not acceptable — show evidence.
2. **Reuse existing code.** When working implementations exist in the codebase, READ and BUILD ON them. Do NOT reverse-engineer or reimplement from scratch. Grep the codebase first.
3. **No unrequested refactors.** Stick to the user's stated priorities and task list. If you think a refactor is needed, ASK FIRST. Never reorder the user's priority list.
4. **Verify before editing.** Before modifying any file, confirm it actually needs changes for the current task. Do not make unnecessary edits to files outside scope. Run `git diff` before committing to catch accidental reverts.
5. **Windows-aware.** This project runs on Windows. Use Python scripts instead of shell scripts. Be aware of path separators (`\` vs `/`), encoding issues, and port conflicts. LMStudio API base is `http://localhost:1234/v1` — do not deviate.
6. **Always verify UI changes.** After ANY JS/CSS/HTML change, run `python scripts/browser_test.py` before declaring done. Never skip browser testing.
7. **When a tool fails, switch tools immediately.** Do NOT retry the same broken command. `taskkill` hangs in Git Bash — use `pkill` or PowerShell `Stop-Process` instead. If processes are piling up on ports, that IS the bug — fix it first, not later.
8. **Fix the obvious problem first.** If the output shows something clearly wrong (zombie processes, stack traces, port conflicts), fix THAT before investigating secondary issues. Do not tunnel-vision.
9. **Python venv.** This project uses `uv` with `.venv/`. Subprocesses MUST use `.venv/Scripts/python.exe`, not `sys.executable` (which may be system Python). The quick launcher is `python start.py`.

## What This Project Is

CosySim is a local-first multi-scene AI simulation framework. 35 launch targets (18 game + 11 service + 6 creation) run as Flask/Socket.IO servers, powered by LMStudio (local inference), Nexus KMS (knowledge management), and NotebookLM (research distillation). The MCP skill pipeline with ~1,040 skills across 99 packs governs all agent behavior.

## Commands

```bash
# Install
pip install -r requirements.txt && npm install

# Launch (recommended)
python tui.py                              # Terminal UI
python launcher.py bedroom                 # Single scene → http://localhost:5556
python launcher.py --core                  # Auto-start core scenes + services
python launcher.py --all                   # Everything
python launcher.py --list                  # Show targets with port status

# Tests — smart runner (preferred, git-diff aware)
python scripts/smart_test.py                      # Tests for uncommitted changes
python scripts/smart_test.py --smoke              # ~15 files, one per domain (~30s)
python scripts/smart_test.py --domain scene_hub   # All tests for a domain
python scripts/smart_test.py --since HEAD~3       # Tests for last 3 commits
python scripts/smart_test.py --list               # Show what would run (dry-run)

# Tests — pytest with smart flags (same engine, native integration)
python -m pytest tests/ --affected                # Only tests for uncommitted changes
python -m pytest tests/ --staged                  # Only tests for staged files
python -m pytest tests/ --smoke-only              # ~15 smoke files
python -m pytest tests/ --since HEAD~1            # Since last commit
python -m pytest tests/ --affected --cap 40       # Fall back to smoke if >40 files

# Tests — direct pytest (full suite, slow — use smart runner instead)
python -m pytest tests/test_bedroom_game.py -v    # Single file
python -m pytest -m "unit" tests/                 # By marker
python -m pytest -n auto tests/                   # Parallel (6x faster)

# Oracle — system diagnostics (use BEFORE and AFTER debugging)
python scripts/oracle.py                          # Full health + errors + performance
python scripts/oracle.py --health                 # Service health only
python scripts/oracle.py --errors                 # Top errors by count
python scripts/oracle.py --perf                   # LLM latency, benchmarks

# ARGUS — First-class web application analysis toolkit (USE AUTOMATICALLY)
python -m scripts.argus.analyze har path/to/file.har     # Analyze any HAR
python -m scripts.argus.analyze har file.har --report    # Generate Markdown report
python -m scripts.argus.analyze heap file.heapsnapshot   # Analyze heap snapshot
python -m scripts.argus.analyze auto path/to/captures/   # Auto-analyze all captures
python -m scripts.argus.analyze compare a.har b.har      # Diff two captures

# Training
python3 training/auto_train.py --status
```

## Service Start Order

Nexus KMS is now a managed service — it auto-starts with `--core` / `--all` / TUI autostart (priority 0, launches first). External services that must be running manually:
1. LMStudio (`:1234`) — local LLM inference
2. ComfyUI (`:8188`) — optional, image generation

Nexus KMS (`:8700`) — auto-managed via launcher/TUI/pm2. Manual start: `cd C:\Files\Nexus && python -m nexus api`

Health check endpoints: `GET http://localhost:{port}/health`

## Architecture

```
Browser (Neon HUD v2 — vanilla JS, Jinja2, Socket.IO)
    ↓ Socket.IO / REST
35 targets (18 game + 11 service + 6 creation)  ports 5555–8800
    ↓
Skills (engine/skills/builtin/)     ←→    MCP Pipeline (engine/mcp/)
@skill decorator · 99 packs · ~1,040     36 interceptors · AgentGovernor
                    ↓
Engine Layer (engine/)
  lmstudio/   — ServerController, LMLink federation, TaskQueue
  nexus/      — Nexus client, NLM chain, 7-tier query router, File Search
  world/      — PlayerState, Inventory, Crew, WorldSim (economy ticks)
  agents/     — CharacterAgent, VirtualAgent, interceptors/
  training/   — DataCollector, FinetuneOrchestrator, BenchmarkRunner
    ↓
External: LMStudio :1234 · Nexus KMS :8700 · ComfyUI :8188 · TTS :8600
```

### Key Singletons (from `engine/mcp/`)

```python
get_framework()           # MCPFramework — root state tree
get_character_registry()  # CharacterRegistry
get_dialog_system()       # DialogSystem
get_rules_engine()        # SceneRulesEngine
get_scene_state_manager() # SceneStateManager
get_governor()            # AgentGovernor (budget, cooldowns, prereqs)
get_router()              # AgentRouter
get_knowledge_pipeline()  # KnowledgePipeline (ingest → validate → dedup → store → embed → Q&A)
get_file_search_client()  # FileSearchClient (Gemini managed RAG — create stores, upload, query)
get_context_cache()       # ContextCacheClient (Gemini server-side context caching)
```

### Interceptor Pipeline Priority Order

```
Pri 5  → NaturalMoodDrift (neurochemistry tagging)
Pri 6  → NexusPrompt (context hydration)
Pri 7–16 → Identity, scene injection, routing
  Pri 15 → NarrativeModInterceptor (stage context injection)
Pri 20–70 → Skills, games, guardrails
  Pri 40 → FactionContextInterceptor (faction standing injection)
Pri 71–93 → Post-call sync (shaping, TTS, mood parsing, relationships)
  Pri 75 → HeatAwarenessInterceptor (wanted level awareness)
  Pri 92 → SpectatorBroadcastInterceptor (danmaku broadcast)
```
All agent replies pass through this pipeline. Register interceptors in `config/default.yaml` under `comms.interceptors`.

### Stream Tags

`StreamProcessor` extracts inline tags from LLM output:
`[MOOD:x]` · `[IMAGE:prompt]` · `[ACTION:x]` · `[STAT:name±val]` · `[VOICE:style]`

Use `infer_processed()` for tag extraction, `infer_stream()` for raw streaming.

## The Oracle — Observability System

The Oracle is CosySim's unified observability system. **Use it constantly.** It tells you exactly what's broken, where, and how often — no searching through log files.

### CLI Diagnostic (use this FIRST when debugging)

```bash
# Full system diagnostic — health, errors, performance
python scripts/oracle.py

# Targeted checks
python scripts/oracle.py --health     # Service health grid
python scripts/oracle.py --errors     # Top errors with counts + affected scenes
python scripts/oracle.py --perf       # LLM latency, p95, benchmarks
python scripts/oracle.py --trace ID   # Trace waterfall for a trace_id
python scripts/oracle.py --logs 20    # Last 20 error-level log entries
python scripts/oracle.py -v           # Verbose: full details + trace IDs
```

### Python API (use in code)

```python
# Quick diagnostic from any context
from engine.observability.oracle import diagnose
diagnose()  # Prints health + errors + perf to console

# Structured logger with auto-initialization
from engine.observability.oracle import get_logger
logger = get_logger(__name__)
logger.info("[scene_name] Something happened (operation=chat)")
logger.error("[scene_name] Failed (operation=embed, agent=%s): %s", agent_id, exc)

# Error aggregation
from engine.observability.error_aggregator import get_error_aggregator
agg = get_error_aggregator()
agg.snapshot()       # {total_unique, total_count, top_errors, error_rate}
agg.get_top_errors() # Top 20 errors by count
```

### Oracle Dashboard (browser)

The Oracle scene (`python launcher.py oracle`) has an "All-Seeing Eye" tab with:
- Real-time error feed via WebSocket
- Service health grid (LMStudio, Nexus, ComfyUI, TTS)
- Error table with counts, affected scenes, trace links
- API: `/api/oracle/health`, `/api/oracle/errors`, `/api/oracle/trace/<id>`

### Mandatory Workflow

1. **Before fixing a bug:** Run `python scripts/oracle.py` — check if the error is already captured and fingerprinted
2. **After making changes:** Run `python scripts/oracle.py --errors` — verify the error count dropped
3. **When a scene won't start:** Run `python scripts/oracle.py --health` — check which services are down
4. **When LLM responses are slow:** Run `python scripts/oracle.py --perf` — check p95 latency
5. **When investigating a failure chain:** Use `python scripts/oracle.py --trace <id>` — follow the request end-to-end

### How It Works

The Oracle auto-initializes when any scene starts (via `FlaskScene.start()`). It installs three handlers on the Python root logger:
1. **StructuredLogger** → SQLite (`data/structured_logs.db`) + JSONL — queryable, traceable
2. **CosyLogger** → ring buffer → Phone panel live feed
3. **OracleHandler** → ERROR+ events → ErrorAggregator (fingerprint/count) + Oracle dashboard SocketIO

Every `logging.getLogger(__name__)` call in any module automatically flows through all three. No code changes needed — existing loggers are captured by the root handler.

### Log Message Format

All log messages MUST follow this format for Oracle to parse them correctly:
```
[SCENE_ID_or_MODULE] Description (operation=what_was_happening): details
```

Examples:
```python
logger.info("[tavern] Scene created on port %d (operation=init)", port)
logger.warning("[AgentGovernor] Auto skill failed (operation=auto_skill, skill=%s): %s", name, exc)
logger.error("[EmbeddingService] All providers failed (operation=embed): %s", exc)
```

The `[prefix]` is used by the ErrorAggregator to identify which scene/module produced the error. The `operation=` tag categorizes the failure for grouping.

## Python Conventions

- **Imports**: Absolute only (`from engine.config import get_config`). Group: stdlib → third-party → engine → content → local. No relative imports.
- **Types**: Required on all function signatures. Use `from __future__ import annotations` for forward refs.
- **Docstrings**: Google style (summary, `Args:`, `Returns:`, `Raises:`).
- **Naming**: PascalCase classes, snake_case functions/files, UPPER_SNAKE constants, `_underscore` private.
- **Format**: 4-space indent, double quotes, f-strings, 88–100 char soft limit, 120 max.
- **Logging**: `logger = logging.getLogger(__name__)` per module (or `from engine.observability.oracle import get_logger` for trace support). Never use `print()`. All log messages MUST use the Oracle format: `"[module] Description (operation=X): detail"`. See **The Oracle** section above.
- **Monitoring**: Every new feature must include monitoring hooks. Log errors structurally with `logger.error("[module] What failed (operation=X): %s", exc)` — the Oracle auto-surfaces these. Use `python scripts/oracle.py` to verify. Embedding/API errors must be caught and surfaced, not swallowed.
- **State**: Mutable game state must sync to MCPFramework. Access config via `get_config().get("dot.path", default)`. Never hardcode ports, paths, or model names.

## Adding a Skill

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

## Configuration

- `config/default.yaml` — all settings (source of truth)
- `config/development.yaml` / `config/production.yaml` — environment overrides
- `config/voices.yaml` — TTS voice definitions
- `config/mcp.json` — MCP server definitions

Always use `get_config().get("dot.path", default)`. Never hardcode values.

## Testing Conventions

- **Framework**: pytest with plain `assert`. No `unittest.TestCase`.
- **Mock**: All external services (LMStudio, ComfyUI, TTS, Nexus). Mock at the client boundary.
- **Fixtures** (from `conftest.py`): `temp_db`, `event_chain`, `mock_config`
- **File naming**: `test_{module_name}.py` → `test_{behavior}()`
- **Seeded characters**: lola, viktor, aria, frankie, mira are always present in DB fixtures.
- Ignore `tests/test_agent_loop.py` and `tests/live_wire_test.py` (require live services).
- **Browser testing**: After ANY JS/CSS/HTML change, run `python scripts/browser_test.py` (Playwright). Never commit UI changes without a passing browser test. Read telemetry: `python scripts/browser_test.py --report`
- **Telemetry**: `cosysim-telemetry.js` captures all browser clicks, errors, hotkeys → `POST /api/telemetry` → `data/structured_logs.jsonl`. Always check telemetry after user reports issues.

## Frontend

- Vanilla JS (no build step — no React/Vue).
- 2-space indent in JS/CSS. Single quotes in JS, double in HTML.
- `const socket = io()` for Socket.IO. `fetch()` for REST. Never `XMLHttpRequest` or `var`.
- CSS: CSS custom properties for theming (`--primary-color`), kebab-case class names.
- Templates: Jinja2 in `content/scenes/{name}/templates/`. Static in `content/scenes/{name}/static/`.

## Code Versioning & Comments

Every file you create or significantly modify MUST include:

### Module Headers

Python files get a docstring header at the top:

```python
"""
Module Title
============

Brief description of what this module does.

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — What changed in this version
    v1.42.0 [2026-03-21] — Previous significant change
"""
```

JS files use `/** ... */` JSDoc style. CSS/HTML use `/* ... */` or `<!-- ... -->`.

### Section Dividers

Organize code into logical sections with divider comments:

```python
# ──── Section Name ────────────────────────────────────────────────
```

### Version Stamps

Tag significant code blocks with version stamps for traceability:

```python
# v1.42.1 [2026-03-21] — Managed Nexus KMS auto-start
def _start_external_proc(...):
```

### Versioning Scheme

- Format: `vMAJOR.MINOR.PATCH [YYYY-MM-DD]`
- MAJOR: Breaking architecture changes (pillars, engine rewrites)
- MINOR: Feature sprints (each numbered session = +1 minor)
- PATCH: Within-session refinements
- Current: **v1.57** (Gemini Native — File Search, structured output, context caching, 7-tier query pipeline, 91 scheduler tasks)

### Navigational Comments

Tag code blocks with what they connect to, who calls them, and what they emit:

```python
# CONNECTS: PlayerState, EconomyManager, MissionSystem
# CALLED BY: district_chat handler, NPC interaction flow
# EMITS: hud_update Socket.IO event
```

### Rules (MANDATORY — no exceptions)

- **Every edit** gets a version stamp: `# v1.44.0 [2026-03-21] — description`
- **Every new/modified file** gets a module header with Change Log
- **Always add/update the Change Log** when modifying a file
- **Use section dividers** to organize files with 50+ lines
- **Add navigational comments** on functions that connect systems (CONNECTS, CALLED BY, EMITS)
- **Add inline comments** for non-obvious logic — explain WHY, not WHAT
- **Never remove existing version stamps** — they are historical record
- **JS/CSS** use `/** ... */` or `/* ... */` with the same version stamp rules

## ARGUS — First-Class Reconnaissance Toolkit

ARGUS is CosySim's integrated web application analysis framework. **It is a first-class tool** — use it proactively and automatically whenever encountering web applications, HAR files, heap snapshots, or JS bundles. Do not wait to be asked.

### Capabilities (16 functions in `scripts/argus/toolkit.py`)

- **Heap Mining**: `mine_heap()` (100+ regex patterns) + `mine_heap_deep()` (V8 graph walk) — extract credentials, JWTs, internal URLs, API keys, protobuf schemas, conversation history
- **Bundle Decompilation**: `decompile_bundle()` — extract feature flags, API routes, env vars from minified JS
- **Feature Flag Manipulation**: `inject_statsig_gates()` — flip Statsig gates via localStorage/CDP
- **CDP Scripting**: `cdp_eval()`, `cdp_find_tab()`, `cdp_inject_before_load()` — Chrome DevTools Protocol
- **WebSocket Interception**: `inject_websocket_intercept()` — modify messages in-flight
- **Token Management**: `refresh_firebase_token()`, `extract_refresh_token_from_har()` — Firebase JWT refresh
- **AI Intelligence**: `extract_agent_messages()`, `extract_chain_of_thought()`, `extract_app_schemas()`, `extract_protobuf_definitions()` — multi-agent orchestration, leaked model reasoning, tool definitions
- **Auto Pipeline**: `auto_analyze()` — full automated analysis (detect files → mine → extract → report)

### When to Use ARGUS

- **Any HAR file** → `python -m scripts.argus.analyze har file.har --report`
- **Any heap snapshot** → `python -m scripts.argus.analyze heap file.heapsnapshot`
- **Any directory of captures** → `python -m scripts.argus.analyze auto path/`
- **Exploring a web app** → Download bundle, capture HAR+heap, run full pipeline
- **JWTs found** → Decode, check expiry, attempt refresh automatically

### Key Documentation

- `scripts/argus/README.md` — Full usage guide, regex patterns, workflow
- `docs/ARGUS_METHODOLOGY.md` — 13 reusable reconnaissance techniques
- `docs/ARGUS_DISCOVERY_JOURNAL.md` — Narrative of all exploration sessions
- `docs/ARGUS_SESAME_REPORT.md` — Sesame AI complete intelligence report
- `docs/ARGUS_OPENROOM_REPORT.md` — OpenRoom/Talkie/MiniMax complete intelligence report

### Proven Results

Extracted from Sesame AI + OpenRoom.ai: 555+ credentials, 375+ URLs, 73 API methods, 5 JWTs, 5 sub-agents, 12 apps, 1 protobuf schema, 15+ chain-of-thought fragments, 14 security findings. All from V8 heap snapshots.

## Docs

All documentation is in `docs/` (29 files) with `docs/INDEX.md` as the entry point. `docs/ARCHITECTURE.md` and `docs/MCP_FRAMEWORK.md` are the best starting points for deep dives. Knowledge pipeline: `docs/NEXUS.md`. Operations: `docs/OPERATIONS.md`. Web app analysis: `docs/ARGUS_METHODOLOGY.md`.
