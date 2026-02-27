# CosySim Agent Onboarding Guide

> Everything an AI agent (Copilot CLI or local LMStudio model) needs to start
> contributing to the CosySim codebase.

## Environment Setup

### Prerequisites
- **Python 3.10+** (verify: `python --version`)
- **NVIDIA GPU** with CUDA (verify: `nvidia-smi`)
- **LMStudio** running at localhost:1234 (verify: `curl http://localhost:1234/api/v1/models`)
- **Git** configured (verify: `git --no-pager status`)

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Verify Environment
```bash
python -c "from engine.config import get_config; print('Config OK')"
python -m pytest tests/test_config.py -v --tb=short  # Quick sanity check
```

## System Map

| Project | Path | Purpose |
|---------|------|---------|
| CosySim | C:\Files\Models\CosySim | Multi-scene AI simulation framework (v0.59b) |
| Nexus KMS | C:\Files\Nexus | Knowledge management system |
| MCP Servers | C:\Files\MCP | LMStudio + AnythingLLM bridges |

### Services

| Service | Port | Health Check |
|---------|------|-------------|
| LMStudio | 1234 | `GET /api/v1/models` |
| Nexus API | 8700 | `GET /api/health` |
| Nexus Panel | 5570 | `GET /` |
| TTS Server | 8600 | `GET /health` |
| Web Bridge | 8601 | `GET /health` |
| Hub | 8500 | `GET /health` |
| ComfyUI | 8188 | `GET /` (optional) |

### Service Startup Order
1. **LMStudio** — must be running first (external)
2. **ComfyUI** — if image generation needed (external)
3. **Nexus KMS**: `cd C:\Files\Nexus && python -m nexus`
4. **CosySim TTS**: `powershell start_servers.ps1`
5. **CosySim Scenes**: `python launcher.py --scene bedroom`
6. **CosySim Hub**: `python launcher.py --hub`

## Step 1: Search Nexus First

> **Nexus-First Mandate:** BEFORE any work, search Nexus. If Nexus has the answer,
> use it (zero compute cost). If Nexus misses, use `nlm_ask()` (free Gemini compute,
> auto-stored). AFTER work, store decisions, patterns, and Q&A back in Nexus.
> Every skip wastes compute that compounds forever.

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
│   ├── mcp/        # MCPFramework, DialogSystem, GameMCP, Governor, MCP Server
│   ├── agents/     # VirtualAgent, InterceptorPipeline, StreamProcessor
│   ├── lmstudio/   # LMS client, router, orchestrator, model manager
│   ├── scenes/     # BaseScene, SceneManager, SceneRegistry
│   ├── skills/     # @skill decorator, registry, 20+ builtin packs
│   ├── services/   # Activity bus, resilience, housekeeping
│   ├── pipeline/   # VirtualPipeline, token routing
│   ├── tts/        # TTS manager (Piper, Orpheus, Qwen3)
│   ├── nexus/      # Nexus client, NLM engine, governance, scheduler
│   ├── assistant/  # System + phone assistants
│   ├── integrations/ # AnythingLLM, Home Assistant
│   └── config.py   # ConfigManager singleton
├── content/        # Game content
│   ├── scenes/     # 18 scene implementations
│   └── simulation/ # Database, character system, services
├── config/         # YAML/JSON config
├── tests/          # pytest suite (136 files, 4,476+ tests)
├── docs/           # Documentation (INDEX.md entry point)
└── .github/        # Copilot agents, instructions, hooks
```

## Step 3: Know the Rules

### Governance Enforcement

CosySim has **active** governance enforcement at three levels:
1. **Copilot hooks** (`check-tool-safety.ps1`) — blocks edits with reject/block violations
2. **Python decorator** (`@governed`) — blocks function calls for unauthorized agents
3. **`enforce_governance()`** — raises `GovernanceError` on blocking violations

```python
from engine.nexus.governance_rules import governed, enforce_governance, GovernanceError

# Decorator-based enforcement
@governed(operation="write", agent_id="qwen3-0.6b")
def my_function(): ...

# Manual enforcement
try:
    enforce_governance(filepath="engine/config.py", agent_id="tiny-0.6b", operation="write")
except GovernanceError as e:
    print(f"Blocked: {e.rule} — {e}")
```

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

The CosySim MCP server provides **108+ tools**. Key categories:
- **Nexus**: search, ask, smart_query, add, add_qa, rules, prompts, research, maintain
- **NLM**: notebook management, deep storage, knowledge distillation
- **Governance**: validate, enforce, check permissions, seed rules
- **System**: status, skills, benchmarks, scheduler, metrics, diagnostics
- **News**: fetch, store, digest, sources
- **AnythingLLM**: connect, status, workspaces, chat, sync
- **Home Assistant**: entities, states, toggle, notify, sensors
- **Phone Assistant**: chat, status, mode, history
- **Knowledge Graph**: build, gaps, clusters, research tasks
- **Training**: stats, export, sync to Nexus

## Troubleshooting

### Common Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: Default configuration not found!` | Config not loaded | Ensure `config/default.yaml` exists and run from project root |
| `ConnectionError` on Nexus calls | Nexus server not running | `cd C:\Files\Nexus && python -m nexus` |
| `ConnectionRefusedError` on LMStudio | LMStudio not started | Start LMStudio, verify `curl localhost:1234/api/v1/models` |
| Tests failing with `ModuleNotFoundError` | Wrong directory | Run from `C:\Files\Models\CosySim` |
| `GovernanceError` on file edit | Coding standard violation | Fix relative imports, remove print(), add logger |

### Emergency Debug Commands
```bash
# Check service health
curl http://localhost:1234/api/v1/models    # LMStudio
curl http://localhost:8700/api/health        # Nexus
python -c "from engine.config import get_config; print(get_config().get('version'))"

# Quick test run (fast subset)
python -m pytest tests/test_config.py tests/test_skill_registry.py -v

# Check governance
python -m engine.nexus.governance_rules validate engine/config.py

# Nexus health
python -m engine.nexus.bridge health
```

## Quick Reference Card

| Action | Command |
|--------|---------|
| Run tests | `python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py` |
| Search Nexus | `python -m engine.nexus.cli search "query"` |
| Ask Nexus | `python -m engine.nexus.cli ask "question"` |
| Check health | `python launcher.py --status` |
| Launch scene | `python launcher.py --mode {scene_name}` |
| List skills | `python -c "from engine.skills.registry import get_skill_registry; r=get_skill_registry(); print(r.list_packs())"` |
