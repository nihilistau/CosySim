# Copilot Instructions — CosySim

> This file provides repository-level context. Modular path-specific rules
> are in `.github/instructions/`. Custom agents are in `.github/agents/`.
> Global system rules are in `~/.copilot/copilot-instructions.md` and
> `~/.config/copilot/shared-rules/`.

## Project Overview

CosySim is a multi-scene AI simulation framework (v3.2, Sprint 15) built on
a custom MCP pipeline with LMStudio v1 API integration. It orchestrates
virtual agents across 15 interactive scenes, each with real-time state
management, skill-based tool calling, dialog systems, and interceptor-governed
agent behavior.

**Core systems:** MCPFramework state tree · DialogSystem conversation threading
· InterceptorPipeline agent governance · @skill decorator tools · EventChain
audit logging · LMStudio v1 streaming with stateful conversations

**Test suite:** 1,756 tests across 69 files — run before and after changes.

## Quick Reference

### Run Tests
```bash
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
```

### Key Singletons
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

### Project Structure
```
CosySim/
├── engine/         # Core framework — modify carefully
│   ├── mcp/        # MCPFramework, DialogSystem, GameMCP, Governor
│   ├── agents/     # VirtualAgent, InterceptorPipeline, StreamProcessor
│   ├── lmstudio/   # LMS client, router, conversation, model manager
│   ├── scenes/     # BaseScene, SceneManager, SceneRegistry
│   ├── skills/     # @skill decorator, registry, 10 builtin packs
│   ├── services/   # Activity bus, resilience, housekeeping
│   ├── pipeline/   # VirtualPipeline, token routing
│   ├── tts/        # Qwen3 TTS server
│   ├── nexus/      # Nexus KMS client
│   └── config.py   # ConfigManager singleton
├── content/        # Game content
│   ├── scenes/     # 15 scene implementations
│   └── simulation/ # Database, character system, services
├── config/         # YAML/JSON config (default, dev, prod, voices, skills, mcp)
├── tests/          # pytest suite (69 files)
├── docs/           # Documentation (INDEX.md entry point)
├── .github/        # Copilot customization (instructions, agents, hooks)
├── main.py         # Application entry point
└── launcher.py     # Scene launcher CLI
```

### External Services
| Service | Port | Purpose |
|---------|------|---------|
| LMStudio | 1234 | LLM inference (v1 API) |
| ComfyUI | 8188 | Image/video generation |
| Nexus KMS | 8700 | Knowledge management |
| TTS Server | 8600 | Text-to-speech (Qwen3) |
| Web Bridge | 8601 | Socket.IO real-time |
| Hub | 8500 | Scene hub + navigation |

## Critical Rules

### Always
- Sync ALL mutable state to the MCPFramework tree
- Use `@skill` for any function an LLM agent should call
- Use absolute imports: `from engine.config import get_config`
- Add type hints to all function signatures
- Use `get_config().get("dot.path", default)` for configuration
- Use `logger = logging.getLogger(__name__)` — never `print()`
- Mock external services in tests (LMStudio, ComfyUI, TTS, Nexus)
- Run tests after changes
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in commits

### Never
- Store game state in local Python variables
- Make real API calls in tests
- Use relative imports
- Hardcode ports, paths, or model names
- Bypass the InterceptorPipeline for agent calls
- Use `print()` for output
- Skip tests

## Modular Rules

Path-specific rules auto-apply based on file patterns:

| File | Applies To |
|------|-----------|
| `instructions/python.instructions.md` | `**/*.py` |
| `instructions/scenes.instructions.md` | `content/scenes/**/*.py` |
| `instructions/mcp-framework.instructions.md` | `engine/mcp/**`, `engine/skills/**`, `engine/agents/**` |
| `instructions/testing.instructions.md` | `tests/**/*.py` |
| `instructions/lmstudio.instructions.md` | `engine/lmstudio/**/*.py` |
| `instructions/config.instructions.md` | `config/**/*.yaml` |
| `instructions/frontend.instructions.md` | `content/scenes/**/templates/**`, `content/scenes/**/static/**` |
| `instructions/deployment.instructions.md` | Startup scripts, deployment files |

## Custom Agents

| Agent | Purpose |
|-------|---------|
| `Scene Builder` | Scaffold new scenes from scratch |
| `Scene Debugger` | Diagnose and fix scene/agent issues |
| `Scene Auditor` | Rate scenes against AAA quality standard |
| `Skill Developer` | Create and register MCP skill packs |
| `Test Writer` | Generate pytest test suites |
| `Doc Writer` | Maintain documentation system |
| `Codebase Navigator` | Explain architecture, trace call chains |
| `System Architect` | Cross-project architecture decisions |

## Documentation
- Entry point: `docs/INDEX.md`
- Architecture: `docs/ARCHITECTURE.md`
- Full doc list: 20 files covering framework, scenes, skills, config, API, testing, training, LMStudio, TTS, characters, admin
