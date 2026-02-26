# CosySim Agent Onboarding Guide

> Everything an AI agent (Copilot CLI or local LMStudio model) needs to start
> contributing to the CosySim codebase.

## System Map

| Project | Path | Purpose |
|---------|------|---------|
| CosySim | C:\Files\Models\CosySim | Multi-scene AI simulation framework (v0.52b) |
| Nexus KMS | C:\Files\Nexus | Knowledge management system |
| MCP Servers | C:\Files\MCP | LMStudio + AnythingLLM bridges |

### Services

| Service | Port | Health Check |
|---------|------|-------------|
| LMStudio | 1234 | `GET /api/v1/models` |
| Nexus API | 8700 | `GET /api/health` |
| Nexus Dashboard | 8701 | `GET /` |
| Nexus Control Panel | 8702 | Streamlit |
| TTS Server | 8600 | `GET /health` |
| Web Bridge | 8601 | `GET /health` |
| Hub | 8500 | `GET /health` |
| ComfyUI | 8188 | `GET /` (optional) |

## Step 1: Search Nexus First

Before writing ANY code, search Nexus for existing knowledge:

```python
# Via Python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
results = client.search("interceptor pipeline")
answer = client.ask("How does state persistence work?")
```

```bash
# Via CLI
python -m engine.nexus.cli search "interceptor pipeline"
python -m engine.nexus.cli ask "How does state work?"
```

## Step 2: Understand the Architecture

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
from engine.nexus.client import get_nexus_client   # Nexus KMS client
from engine.lmstudio.orchestrator import get_orchestrator  # Multi-model orchestrator
```

### Inference Flow
```
VirtualAgent.reply() → build_request() → InferenceRequest
  → VirtualAgentManager.infer()
    → InferenceOrchestrator.infer()
      → _select_tier(task_type, priority, profile)
      → resource_manager.acquire(agent_id, role)
      → client.chat(messages, model, config)
      → return LMSResponse
```

### Project Structure
```
CosySim/
├── engine/         # Core framework — modify carefully
│   ├── mcp/        # MCPFramework, DialogSystem, GameMCP, Governor
│   ├── agents/     # VirtualAgent, InterceptorPipeline, StreamProcessor
│   ├── lmstudio/   # LMS client, router, orchestrator, model manager
│   ├── scenes/     # BaseScene, SceneManager, SceneRegistry
│   ├── skills/     # @skill decorator, registry, 13 builtin packs
│   ├── services/   # Activity bus, resilience, housekeeping
│   ├── pipeline/   # VirtualPipeline, token routing
│   ├── tts/        # Qwen3 TTS server
│   ├── nexus/      # Nexus KMS client + CLI tools
│   └── config.py   # ConfigManager singleton
├── content/        # Game content
│   ├── scenes/     # 13 scene implementations
│   └── simulation/ # Database, character system, services
├── config/         # YAML/JSON config
├── tests/          # pytest suite (75+ files, 2613+ tests)
├── docs/           # Documentation (INDEX.md entry point)
└── .github/        # Copilot agents, instructions, hooks
```

## Step 3: Know the Rules

### Always
- Use absolute imports: `from engine.config import get_config`
- Add type hints to ALL function signatures
- Use `logger = logging.getLogger(__name__)` — never `print()`
- Mock external services in tests (LMStudio, ComfyUI, TTS, Nexus)
- Sync mutable state to MCPFramework tree
- Use `get_config().get("dot.path", default)` for config
- Run tests after changes
- Store decisions/findings in Nexus

### Never
- Store game state in local Python variables
- Make real API calls in tests
- Use relative imports
- Hardcode ports, paths, or model names
- Use `print()` for output
- Skip tests

## Step 4: Run Tests

```bash
# Full suite (must pass before and after changes)
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Single file
python -m pytest tests/test_bedroom_game.py -v

# By pattern
python -m pytest tests/ -k "test_inference" -v
```

## Step 5: Common Tasks

### Add a New Skill
```python
# engine/skills/builtin/my_skills.py or content/scenes/{name}/{name}_skills.py
from engine.skills.skill import skill

@skill(
    pack="my_pack",
    description="What this skill does (LLM-facing)",
    category="game",
    cooldown=5.0,
    cost=1.0,
    tags=["tag1", "tag2"]
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

### Add a New Scene
1. Create directory: `content/scenes/{name}/`
2. Create `__init__.py` with class inheriting `BaseScene`
3. Override: `start()`, `stop()`, `get_plugin_info()`
4. Create `{name}_skills.py` with `@skill` functions
5. Create `templates/` and `static/` directories
6. Register scene node: `fw.get_or_create("scenes.{name}", MCPSceneNode)`
7. Add tests in `tests/test_{name}.py`

### Fix a Bug
1. Search Nexus for known issues: `nexus_search("bug topic")`
2. Reproduce with a test
3. Trace the call chain (check interceptors, governor, agent flow)
4. Make minimal fix
5. Verify tests pass
6. Store fix in Nexus: `nexus_add("Bug Fix: ...", details, "note")`
7. Commit: `git commit -m "fix: description"`

## Step 6: Git Conventions

```bash
# Conventional commits
git commit -m "feat: add new skill for X" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git commit -m "fix: resolve state sync issue in lounge" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git commit -m "test: add gallery scene tests" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Prefixes: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`

## Step 7: After Completing Work

1. **Store decisions**: `nexus_add("Decision: ...", content, "decision")`
2. **Store Q&A**: `nexus_add_qa("How does X work?", "X works by...")`
3. **Log session**: `nexus_log_session("CosySim")`
4. **Update tests**: Ensure new code has test coverage
5. **Update docs**: If you changed APIs or behavior

## MCP Tools Available

The CosySim MCP server provides 144 tools. Key categories:
- **Memory**: get/set character memory, search memories
- **Character**: stats, relationships, inventory, buffs
- **Game**: sessions, actions, scoring
- **Scene**: state, events, transitions
- **Dialog**: conversations, history, threading
- **Media**: ComfyUI image/video generation
- **Nexus**: search, ask, add, rules, prompts, research
- **Utility**: health checks, config, system status

## Quick Reference Card

| Action | Command |
|--------|---------|
| Run tests | `python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py` |
| Search Nexus | `python -m engine.nexus.cli search "query"` |
| Ask Nexus | `python -m engine.nexus.cli ask "question"` |
| Check health | `python launcher.py --status` |
| Launch scene | `python launcher.py --mode {scene_name}` |
| List skills | `python -c "from engine.skills.registry import get_skill_registry; r=get_skill_registry(); print(r.list_packs())"` |
