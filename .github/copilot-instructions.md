# Copilot Instructions — CosySim

## Project Overview

CosySim is a multi-scene AI simulation framework (v3.2) built on a custom MCP
(Model Context Protocol) pipeline with LMStudio integration. It orchestrates
virtual agents across 15+ interactive scenes (Bedroom, Casino, Realm RPG,
NeonCity, Warzone, etc.), each with real-time state management, skill-based
tool calling, dialog systems, and interceptor-governed agent behavior.

**Key systems:** MCPFramework state tree, DialogSystem conversation threading,
InterceptorPipeline agent governance, @skill decorator tool system,
EventChain audit logging, LMStudio v1 API streaming with stateful
conversations.

## Language & Runtime

- **Primary language:** Python 3.10+
- **Frontend:** HTML/CSS/JS (Jinja2 templates per scene, no build step)
- **Config:** YAML (`config/default.yaml`, `config/development.yaml`)
- **Package manager:** pip (requirements.txt + pyproject.toml)

## Code Style

### Python

- **Indentation:** 4 spaces, no tabs
- **Line length:** 88–100 chars (soft limit); up to 120 for long type hints
- **Imports:** Absolute imports only — `from engine.config import get_config`
- **Type hints:** Required on all function signatures (args + return type)
- **Docstrings:** Google style — summary line, then `Args:`, `Returns:`, `Raises:`
- **Logging:** `logger = logging.getLogger(__name__)` per module
- **String quotes:** Double quotes for strings
- **f-strings:** Preferred over `.format()` or `%`
- **Section dividers:** Use `# ──── Section Name ────` for major sections in long files

### Naming Conventions

- **Classes:** PascalCase — `MCPFramework`, `BaseScene`, `AgentGovernor`
- **Functions/methods:** snake_case — `get_active_scene()`, `load_character()`
- **Constants:** UPPER_SNAKE — `SKILL_REGISTRY`, `_ACTIVE_SCENES`
- **Private:** Single underscore prefix — `_resolve_backend()`, `_build_request()`
- **Files:** snake_case — `base_scene.py`, `character_registry.py`
- **Scene skills:** `{scene_name}_skills.py` in `content/scenes/{scene_name}/`

## Architecture Patterns

### Scene Creation

Every scene inherits from `BaseScene` and must implement:

```python
from engine.scenes.base_scene import BaseScene

class MyScene(BaseScene):
    SCENE_METADATA = {"name": "my_scene", "port": 5567, "type": "game"}

    def start(self):
        """Initialize scene, register MCP nodes, start Flask server."""

    def stop(self):
        """Persist state and shut down."""

    def get_plugin_info(self) -> dict:
        """Return scene metadata for the hub."""
```

Scenes auto-register in `BaseScene._ACTIVE_SCENES` on `__init__` and
deregister on `stop()`. Access running scenes via `get_active_scene(name)`.

### MCP Framework

All state flows through the MCPFramework singleton tree:

```python
from engine.mcp import get_framework, MCPSceneNode, MCPCharacterNode

fw = get_framework()
scene_node = fw.get_or_create("scenes.bedroom", MCPSceneNode)
char_node = fw.get_or_create("characters.lola", MCPCharacterNode)
```

Never store game state in local variables — always sync to the MCP tree so
interceptors, skills, and the admin panel can observe and modify it.

### Skills

Use the `@skill` decorator to register tools that LLM agents can call:

```python
from engine.skills.skill import skill

@skill(pack="my_scene", description="Do something useful", category="game")
def my_tool(target: str, amount: int = 1) -> str:
    """Brief description for the LLM.

    Args:
        target: Who to target.
        amount: How much (default 1).

    Returns:
        Result message string.
    """
    return f"Did something to {target} x{amount}"
```

Key parameters: `pack` (grouping), `description` (LLM-facing), `category`
(one of: COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM,
NARRATIVE), `cooldown` (seconds between calls), `cost` (budget tracking).

Scene skills live in `content/scenes/{name}/{name}_skills.py` and are
imported in the scene's `__init__.py`.

### Interceptors

Interceptors modify agent requests/responses in the governance pipeline:

```python
from engine.mcp import InterceptorBase

class MyInterceptor(InterceptorBase):
    def pre_call(self, request, context):
        """Modify request before LLM call."""
        return request

    def post_call(self, response, context):
        """Modify response after LLM call."""
        return response
```

Interceptors are registered in `config/default.yaml` under `comms.interceptors`.

### Config Access

```python
from engine.config import get_config
cfg = get_config()
port = cfg.get("scenes.bedroom.port", 5555)
model = cfg.get("lmstudio.models.primary", "default-model")
```

Dot-notation paths into the YAML config tree. Always provide defaults.

### Dialog System

```python
from engine.mcp import get_dialog_system
ds = get_dialog_system()
ds.add_speech_style("lola", {"tone": "playful", "vocabulary": "casual"})
```

### Character Registry

```python
from engine.mcp import get_character_registry
registry = get_character_registry()
profile = registry.get_character("lola")
```

Characters have: personality traits, emotions (0–100 scale), relationship
stats, speech patterns, attraction attributes, and buff/debuff timers.

## Testing

### Framework

- **Test runner:** pytest 9.0+
- **Test location:** `tests/` directory (69 files, 1,756+ tests)
- **Assertion style:** Plain `assert` statements (no unittest.TestCase)
- **Mocking:** `unittest.mock.MagicMock`, `patch`, `AsyncMock`
- **Fixtures:** Defined in `tests/conftest.py` — `temp_db`, `event_chain`,
  `mock_config`

### Running Tests

```bash
# Full suite (ignoring integration-only tests)
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Single file
python -m pytest tests/test_bedroom_game.py -v

# By marker
python -m pytest tests/ -m unit
python -m pytest tests/ -m "not slow"
```

### Writing Tests

```python
import pytest
from unittest.mock import MagicMock, patch

def test_my_feature(temp_db, mock_config):
    """Test description — what behavior is being verified."""
    # Arrange
    scene = MyScene(config=mock_config)

    # Act
    result = scene.do_thing("input")

    # Assert
    assert result["status"] == "ok"
    assert "expected_key" in result
```

- Name test files `test_{module}.py`
- Name test functions `test_{behavior_being_tested}`
- Use `temp_db` fixture for database-dependent tests
- Use `mock_config` for config-dependent tests
- Mock external services (LMStudio, ComfyUI, TTS) — never make real API calls
- Test both happy path and edge cases

## Project Structure

```
CosySim/
├── engine/                  # Core framework (do not modify lightly)
│   ├── mcp/                 # MCPFramework, DialogSystem, GameMCP, Governor
│   ├── agents/              # VirtualAgent, InterceptorPipeline, StreamProcessor
│   ├── lmstudio/            # LMS client, router, conversation, model manager
│   ├── scenes/              # BaseScene, SceneManager, SceneRegistry
│   ├── skills/              # @skill decorator, registry, 10 builtin packs
│   ├── services/            # Activity bus, resilience, housekeeping
│   ├── pipeline/            # VirtualPipeline, token routing
│   ├── tts/                 # Qwen3 TTS server
│   ├── nexus/               # Nexus KMS client
│   └── config.py            # ConfigManager singleton
├── content/                 # Game content (scenes, characters, simulation)
│   ├── scenes/              # 15 scene implementations
│   └── simulation/          # Database, character system, services
├── config/                  # YAML/JSON configuration files
├── tests/                   # pytest test suite
├── training/                # Model fine-tuning scripts
├── docs/                    # Documentation (INDEX.md is the entry point)
├── main.py                  # Application entry point
└── launcher.py              # Scene launcher CLI
```

## Key Singletons (import patterns)

```python
from engine.config import get_config              # ConfigManager
from engine.mcp import get_framework              # MCPFramework
from engine.mcp import get_character_registry      # CharacterRegistry
from engine.mcp import get_dialog_system           # DialogSystem
from engine.mcp import get_rules_engine            # SceneRulesEngine
from engine.mcp import get_scene_state_manager     # SceneStateManager
from engine.mcp import get_governor                # AgentGovernor
from engine.mcp import get_router                  # AgentRouter
from engine.scenes.base_scene import BaseScene     # Scene base class
from engine.skills.skill import skill              # @skill decorator
```

## LMStudio Integration

- **API:** LMStudio v1 at `http://localhost:1234`
- **Stateful conversations:** `store: true` + `previous_response_id` for threading
- **Streaming:** SSE with event types: `message.delta`, `reasoning.delta`,
  `chat.start`, `chat.end`
- **Input format:** `{"type": "text", "text": "..."}` (NOT `"content"`)
- **Model profiles:** `agent_profiles` in config — big (70B), small (9B),
  router (270M)

## External Services

| Service | Port | Purpose |
|---------|------|---------|
| LMStudio | 1234 | LLM inference |
| ComfyUI | 8188 | Image/video generation |
| Nexus KMS | 8700 | Knowledge management |
| TTS Server | 8600 | Text-to-speech (Qwen3) |
| Web Bridge | 8601 | Socket.IO real-time |

## Do's and Don'ts

### Do

- Sync all mutable state to the MCPFramework tree
- Use `@skill` for any function an LLM agent should be able to call
- Write tests for new features (target: every scene, every skill pack)
- Use `get_config()` with dot-notation and defaults for all config access
- Use `EventChain` for audit-worthy actions
- Use absolute imports everywhere
- Add type hints to all function signatures
- Keep scene skills in `content/scenes/{name}/{name}_skills.py`

### Don't

- Don't store game state in local Python variables (use MCP nodes)
- Don't make real API calls in tests (mock LMStudio, ComfyUI, TTS)
- Don't use relative imports
- Don't hardcode ports, paths, or model names (use config)
- Don't bypass the InterceptorPipeline for agent calls
- Don't add new top-level directories without updating `docs/INDEX.md`
- Don't use `print()` — use `logger.info/debug/warning/error`

## Commit Messages

Follow conventional commits:

```
feat: add new bedroom mini-game mechanic
fix: correct stat decay timer in character system
docs: update SCENES.md with realm combat rules
test: add casino blackjack edge case tests
chore: remove stale config entries
refactor: extract dialog system from scene base
```

Always include the co-author trailer:
```
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```
