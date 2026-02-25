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

## Test Inventory

**54 test files** · **1,781 test functions**

### Scenes (11 files, ~370 tests)

| File | Tests | Description |
|------|-------|-------------|
| test_pipeline_smoke.py | 148 | End-to-end pipeline smoke tests |
| test_realm.py | 58 | Realm scene logic |
| test_scene_rules_engine.py | 65 | Scene rules engine |
| test_casino_game.py | 42 | Casino game mechanics |
| test_bedroom_game.py | 40 | Bedroom scene interactions |
| test_heist.py | 43 | Heist scene |
| test_command_center.py | 32 | Command center scene |
| test_neoncity.py | 26 | Neon City scene |
| test_warzone.py | 25 | Warzone scene |
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
