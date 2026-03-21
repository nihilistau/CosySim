# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

CosySim is a local-first multi-scene AI simulation framework. 20 interactive scenes run as Flask/Socket.IO servers, powered by LMStudio (local inference), Nexus KMS (knowledge management), and NotebookLM (research distillation). The MCP skill pipeline governs all agent behavior.

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
20 Flask scenes  (content/scenes/{name}/)  ports 5555–5580, 8500
    ↓
Skills (engine/skills/builtin/)     ←→    MCP Pipeline (engine/mcp/)
@skill decorator · 38 packs              26 interceptors · AgentGovernor
                    ↓
Engine Layer (engine/)
  lmstudio/   — ServerController, LMLink federation, TaskQueue
  nexus/      — Nexus client, NLM chain, 4-tier query router
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
```

### Interceptor Pipeline Priority Order

```
Pri 4  → NexusPrompt (context hydration)
Pri 5  → NaturalMoodDrift (neurochemistry tagging)
Pri 8–16 → Identity & scene injection
Pri 92–93 → Post-call sync (mood parsing, relationship events)
```
All agent replies pass through this pipeline. Register interceptors in `config/default.yaml` under `comms.interceptors`.

### Stream Tags

`StreamProcessor` extracts inline tags from LLM output:
`[MOOD:x]` · `[IMAGE:prompt]` · `[ACTION:x]` · `[STAT:name±val]` · `[VOICE:style]`

Use `infer_processed()` for tag extraction, `infer_stream()` for raw streaming.

## Python Conventions

- **Imports**: Absolute only (`from engine.config import get_config`). Group: stdlib → third-party → engine → content → local. No relative imports.
- **Types**: Required on all function signatures. Use `from __future__ import annotations` for forward refs.
- **Docstrings**: Google style (summary, `Args:`, `Returns:`, `Raises:`).
- **Naming**: PascalCase classes, snake_case functions/files, UPPER_SNAKE constants, `_underscore` private.
- **Format**: 4-space indent, double quotes, f-strings, 88–100 char soft limit, 120 max.
- **Logging**: `logger = logging.getLogger(__name__)` per module. Never use `print()`. Use structured logging patterns — include context (scene, agent, operation) in log messages.
- **Monitoring**: Every new feature must include monitoring hooks. Log errors structurally, not silently. Use health check endpoints, EventChain for activity tracking, and Nexus for persistent metrics. Embedding/API errors must be caught and surfaced, not swallowed.
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
- Current: **v1.42** (Pillar Wiring & Hub Modernization)

### Rules

- Always add/update the Change Log when modifying a file
- Use section dividers to organize files with 100+ lines
- Add inline comments for non-obvious logic (not for self-evident code)
- Never remove existing version stamps — they are historical record

## Docs

All documentation is in `docs/` with `docs/INDEX.md` as the entry point. `docs/ARCHITECTURE.md` and `docs/MCP_FRAMEWORK.md` are the best starting points for deep dives.
