# CosySim Testing Guide

## Running Tests

```bash
# Run all tests (excluding known interactive/live tests)
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Run a specific test file
python -m pytest tests/test_router.py -v

# Run with coverage
python -m pytest tests/ --cov=engine --cov=content --tb=short
```

Test configuration is defined in `pyproject.toml` under `[tool.pytest.ini_options]`.

**Test Inventory**

**176 test files** · **4,827 test functions**

### Scenes (10 files, ~345 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_pipeline_smoke.py | 148 | End-to-end pipeline smoke tests |
| test_realm.py | 58 | Realm scene logic |
| test_scene_rules_engine.py | 65 | Scene rules engine |
| test_casino_game.py | 42 | Casino game mechanics |
| test_penthouse_game.py | 40 | Penthouse scene interactions |
| test_heist.py | 43 | Heist scene |
| test_command_center.py | 32 | Command center scene |
| test_neoncity.py | 26 | Neon City scene |
| test_coders.py | 22 | Coders scene |
| test_vam_pipeline_integration.py | 9 | VaM pipeline integration |

### Framework / Core (10 files, ~390 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_governance.py | 80 | Governance interceptor chain |
| test_dialog_system.py | 62 | Dialog system and conversation flow |
| test_character_registry.py | 44 | Character profile registry |
| test_state_coordinator.py | 41 | State coordination and persistence |
| test_interaction_trees.py | 34 | Branching interaction trees |
| test_character_agent.py | 32 | Character agent behavior |
| test_agent_loop.py | 25 | Agent loop (excluded by default) |
| test_evaluator.py | 20 | Response evaluator |
| test_interceptor_upgrades.py | 10 | Interceptor upgrade system |
| test_event_chain.py | 12 | Event chain processing |

### LLM / Inference (8 files, ~310 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_lms_client_v27.py | 80 | LMS client v27 API |
| test_lmstudio_infra.py | 72 | LM Studio infrastructure |
| test_virtual_pipeline.py | 18 | Virtual pipeline |
| test_virtual_agent_v27.py | 20 | Virtual agent v27 |
| test_benchmarks.py | 24 | Performance benchmarks |
| test_training_pipeline.py | 27 | Training pipeline integration |
| test_training_capture.py | 11 | Training data capture |
| test_prompt_builder.py | 16 | Prompt construction |

### Routing / Infrastructure (10 files, ~250 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_scene_routes.py | 44 | Scene route definitions |
| test_phone_routing.py | 40 | Phone call routing |
| test_router.py | 33 | Main router |
| test_content_router.py | 29 | Content routing |
| test_stream_watcher.py | 31 | Stream watcher |
| test_stream_processor.py | 42 | Stream processing |
| test_token_router.py | 16 | Token-level routing |
| test_overlay_router.py | 7 | Overlay routing |
| test_kill_switch.py | 22 | Kill switch / safety |
| test_pipeline_result.py | 16 | Pipeline result handling |

### MCP / SDK / Integration (5 files, ~95 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_mcp_server.py | 28 | MCP server endpoints |
| test_sdk_client.py | 28 | SDK client |
| test_integration.py | 18 | Integration tests |
| test_skills.py | 11 | Skill execution |
| test_tool_registry.py | 22 | Tool registry |

### Database / Monitoring (4 files, ~110 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_database.py | 66 | Database CRUD operations |
| test_metrics_db.py | 16 | Metrics database |
| test_metrics_collector.py | 10 | Metrics collection |
| test_alerts.py | 18 | Alert system |

### Configuration / Utilities (6 files, ~130 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_tag_registry.py | 52 | Tag registry and parsing |
| test_tts.py | 34 | Text-to-speech |
| test_spatial.py | 32 | Spatial/location system |
| test_media_config.py | 17 | Media configuration |
| test_web_bridge.py | 6 | Web bridge |
| test_config.py | 5 | Configuration loading |

## Writing Tests

### Guidelines

- **Mock external dependencies**: Use `unittest.mock` for LLM calls, database, TTS, and RAG.
- **Self-contained**: Each test must set up its own state; don't depend on test execution order.
- **Follow existing patterns**: Mirror the structure of nearby test files.
- **New engine modules need test files**: Add `tests/test_{module_name}.py` for any new module.

### Fixtures (conftest.py)

| Fixture | Provides |
|---------|----------|
| `temp_db_path(tmp_path)` | Temporary SQLite database file path |
| `temp_db(temp_db_path)` | Fresh `Database` instance from `content.simulation.database.db` |
| `event_chain(temp_db)` | `EventChain` backed by the temporary database |
| `mock_config()` | Dict with keys: `lmstudio.base_url`, `comfyui.base_url`, `tts.engine`, `database.path`, `hardware.vram_cap_mb` |

### Common Mock Patterns

```python
# LMSClient — mock streaming responses
from unittest.mock import MagicMock, patch, AsyncMock

mock_client = MagicMock()
mock_client.chat.return_value = {"choices": [{"message": {"content": "response"}}]}

# Database — mock CRUD
mock_db = MagicMock()
mock_db.get_character.return_value = {"name": "Luna", "mood": "happy"}

# RAG — mock retrieval
mock_rag = MagicMock()
mock_rag.query.return_value = [{"text": "memory context", "score": 0.9}]

# Config — use mock_config fixture or dict
with patch("engine.config.get_config") as mock_cfg:
    mock_cfg.return_value.get.side_effect = lambda k, d=None: config_dict.get(k, d)
```

### Example Test

```python
def test_router_selects_correct_tool(mock_config):
    from unittest.mock import MagicMock
    router = Router(config=mock_config)
    router.client = MagicMock()
    router.client.chat.return_value = {"choices": [{"message": {"content": "search"}}]}

    result = router.route("find nearby restaurants")
    assert result.tool_name == "web_search"
```

---

## Smart Test Runner

> Updated for v1.04b

`scripts/smart_test_runner.py` provides a tiered test execution strategy with
git-diff detection, timing cache, and JSON report generation.

### 4-Tier Strategy

| Tier | Name | Timeout | Purpose | Typical Duration |
|------|------|---------|---------|-----------------|
| 1 | **Smoke** | 30s | Quick validation — imports, config, decorators | ~14 seconds |
| 2 | **Core** | 120s | Scene + system tests — penthouse, phone, database | ~2 minutes |
| 3 | **Integration** | 300s | Pipeline, Copilot, Nexus, LMStudio integration | ~5 minutes |
| 4 | **Full** | 1800s | Complete test suite (all `test_*` files) | ~10–30 minutes |

Tiers are **cumulative** — running tier 3 also runs tiers 1 and 2.

### CLI Usage

```powershell
# Run tier 1 (smoke tests only)
python scripts/smart_test_runner.py --tier 1

# Run tier 2 (smoke + core)
python scripts/smart_test_runner.py --tier 2

# Run only tests affected by git changes
python scripts/smart_test_runner.py --changed

# Run specific test files
python scripts/smart_test_runner.py --file "test_penthouse*" "test_phone*"

# Full suite
python scripts/smart_test_runner.py --full

# Show timing report from cache (no tests run)
python scripts/smart_test_runner.py --report

# With parallel workers (requires pytest-xdist)
python scripts/smart_test_runner.py --tier 2 -j 4

# Verbose debug output
python scripts/smart_test_runner.py --tier 1 --verbose
```

### CLI Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--tier {1,2,3,4}` | int | — | Run tests for specified tier (cumulative) |
| `--full` | flag | — | Run complete test suite (tier 4) |
| `--changed` | flag | — | Only run tests for git-changed files |
| `--file` | patterns | — | Run specific test files or glob patterns |
| `--report` | flag | — | Show timing report from cache |
| `--workers` / `-j` | int | 0 | Parallel workers (pytest-xdist) |
| `--timing-cache` | path | `data/test_timing.json` | Timing cache location |
| `--reports-dir` | path | `data/test_reports` | Report output directory |
| `--verbose` | flag | — | Enable DEBUG logging |

### Features

- **Timing Cache** (`data/test_timing.json`) — Records per-test execution times;
  used to order tests fastest-first for early failure feedback.
- **Git-Diff Detection** — Runs `git diff --name-only --cached` to identify
  changed source files, then maps them to corresponding test files.
- **Speed Ranking** — `order_by_speed()` reorders discovered tests using
  historical timing data so fast tests run first.
- **JSON Reports** — Each run generates a timestamped JSON report in
  `data/test_reports/` with pass/fail counts, timing, and tier breakdown.

### YAML Configuration

```yaml
testing:
  smart_runner:
    enabled: true
    default_tier: 2
    parallel_workers: 4
    timing_cache: "data/test_timing.json"
    reports_dir: "data/test_reports"
    skip_patterns:
      - "test_agent_loop.py"
      - "live_wire_test.py"
    tier_1_patterns:
      - "test_scene_imports"
      - "test_skill_registry"
      - "test_config"
    tier_2_patterns:
      - "test_penthouse*"
      - "test_phone*"
      - "test_lab*"
      - "test_multiplayer*"
    tier_3_patterns:
      - "test_pipeline*"
      - "test_copilot*"
      - "test_nexus*"
```

See [Configuration](CONFIGURATION.md) for the full `testing` YAML block.

---

## Automated Test Scheduler

> Updated for v1.04b

`scripts/test_scheduler.py` provides scheduled and on-demand test execution
with Nexus result storage and MCP state coordination.

### Scheduling Modes

| Mode | CLI Flag | Description |
|------|----------|-------------|
| **Immediate** | `--run-now` | Execute once and exit |
| **Recurring** | `--schedule N` | Run every N minutes via `threading.Timer` |
| **Suite-specific** | `--suite {unit\|health\|browser\|full}` | Target a specific test suite |

### Test Suites

| Suite | What It Does |
|-------|-------------|
| `unit` | Runs pytest with default args and timeout |
| `health` | Scene health checks on configured ports (default: 5555, 5556, 5571, 8500) |
| `browser` | CDP-based browser diagnostics (console errors, network failures, DOM health) |
| `full` | All three suites in sequence |

### CLI Usage

```powershell
# Run full suite immediately
python scripts/test_scheduler.py --run-now

# Run unit tests only
python scripts/test_scheduler.py --run-now --suite unit

# Schedule recurring runs every 30 minutes
python scripts/test_scheduler.py --schedule 30

# Health check on a specific port
python scripts/test_scheduler.py --run-now --suite health --port 5556

# Store results in Nexus
python scripts/test_scheduler.py --run-now --store-nexus

# JSON output
python scripts/test_scheduler.py --run-now --json-output data/test_results.json
```

### MCP Integration

The scheduler updates scene state via `engine.mcp.state_coordinator` and
optionally stores results in Nexus. When `--store-nexus` is passed (or
`testing.store_results_in_nexus: true` in config), test outcomes are persisted
as Nexus knowledge entries for later retrieval by agents.

### YAML Configuration

```yaml
testing:
  default_suite: "full"
  scene_ports: [5555, 5556, 5571, 8500]
  unit_test_timeout: 300
  health_check_timeout: 30
  browser_checks:
    - console_errors
    - network_failures
    - dom_health
  store_results_in_nexus: true
  schedule_interval_minutes: 0        # 0 = disabled
```

---

## Pytest Markers

> Defined in `pyproject.toml` under `[tool.pytest.ini_options]`

| Marker | Description | Example Filter |
|--------|-------------|----------------|
| `unit` | Fast tests, no external dependencies | `-m unit` |
| `integration` | Integration tests (may need services) | `-m integration` |
| `slow` | Long-running tests | `-m "not slow"` |
| `scene` | Scene-specific tests | `-m scene` |
| `browser` | Tests requiring browser / CDP | `-m browser` |
| `nexus` | Tests requiring Nexus server | `-m nexus` |
| `smoke` | Quick smoke tests for CI | `-m smoke` |

```powershell
# Run only unit tests
python -m pytest tests/ -m unit -v

# Skip slow tests
python -m pytest tests/ -m "not slow" -v

# Run smoke + scene tests
python -m pytest tests/ -m "smoke or scene" -v
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Full suite (manual) | `python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py` |
| Smart runner — smoke | `python scripts/smart_test_runner.py --tier 1` |
| Smart runner — core | `python scripts/smart_test_runner.py --tier 2` |
| Smart runner — integration | `python scripts/smart_test_runner.py --tier 3` |
| Smart runner — full | `python scripts/smart_test_runner.py --full` |
| Smart runner — changed only | `python scripts/smart_test_runner.py --changed` |
| Smart runner — timing report | `python scripts/smart_test_runner.py --report` |
| Scheduler — run now | `python scripts/test_scheduler.py --run-now` |
| Scheduler — recurring 30min | `python scripts/test_scheduler.py --schedule 30` |
| Scheduler — health check | `python scripts/test_scheduler.py --run-now --suite health` |
| Single file | `python -m pytest tests/test_penthouse_game.py -v` |
| By marker | `python -m pytest tests/ -m smoke -v` |
| With coverage | `python -m pytest tests/ --cov=engine --cov=content --tb=short` |
| Scene health | `python scripts/scene_health_check.py --port 5556 --fix` |
| All scene health | `python scripts/scene_health_check.py --all` |
