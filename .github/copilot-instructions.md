# Copilot Instructions — CosySim

> This file provides repository-level context. Modular path-specific rules
> are in `.github/instructions/`. Custom agents are in `.github/agents/`.
> Global system rules are in `~/.copilot/copilot-instructions.md` and
> `~/.config/copilot/shared-rules/`.

## Project Overview

CosySim is a multi-scene AI simulation framework (v0.51b) built on
a custom MCP pipeline with LMStudio v1 API integration and Nexus knowledge system.
It orchestrates virtual agents across 18 interactive scenes, each with real-time
state management, skill-based tool calling, dialog systems, and interceptor-governed
agent behavior. Nexus provides central knowledge management, rules engine,
session tracking, and prompt versioning.

**Core systems:** MCPFramework state tree · DialogSystem conversation threading
· InterceptorPipeline agent governance · @skill decorator tools · EventChain
audit logging · LMStudio v1 streaming with stateful conversations · Nexus knowledge system
· InferenceOrchestrator multi-model routing

**Test suite:** 1,903+ tests across 70+ files — run before and after changes.

**MCP Server:** 131 tools available via `.vscode/mcp.json` — includes Nexus bridge,
skill discovery, and system monitoring tools.

## MCP Tools Available

This workspace has a CosySim MCP server configured in `.vscode/mcp.json`.
You can call these tools directly:

### Nexus Knowledge Tools (use before coding)
- `nexus_smart_query(question)` — **PRIMARY** query tool (cache → FTS → ask → LLM, auto-stores)
- `nexus_router_stats()` — Query router hit rates, tokens saved
- `nexus_search(query)` — Search knowledge base
- `nexus_ask(question)` — Smart Q&A (cache → FTS → NLM)
- `nexus_add(title, content, content_type)` — Store knowledge
- `nexus_add_qa(question, answer)` — Store Q&A pair
- `nexus_get_rules(scope)` — Get governance rules
- `nexus_store_prompt(name, content)` — Version prompts
- `nexus_get_prompts(category)` — Retrieve prompts
- `nexus_research(question)` — Start deep research
- `nexus_converse(research_id, message)` — Continue research
- `nexus_finish_research(research_id)` — Distill findings
- `nexus_import_youtube(url)` — Import video transcripts
- `nexus_log_session(project)` — Track work session
- `nexus_status()` — Check Nexus health

### Nexus Maintenance
- `seed_nexus(source)` — Seed knowledge (docs/qa/rules/prompts/conventions/all)
- `nexus_maintain(action)` — Maintenance (health/dedup/cleanup/reindex)

### Nexus CLI Bridge (fallback when MCP server is not running)
```powershell
python -m engine.nexus.bridge search "query"
python -m engine.nexus.bridge ask "question"
python -m engine.nexus.bridge store "Title" "Content" --type note --category dev
python -m engine.nexus.bridge health
python -m engine.nexus.bridge seed all
python -m engine.nexus.bridge maintain dedup
```

### System Discovery
- `list_all_skills()` — All skills grouped by pack
- `get_skill_info(skill_name)` — Skill details + parameters
- `system_status()` — Full system health check

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
from engine.nexus.client import get_nexus_client   # Nexus KMS client
from engine.lmstudio.orchestrator import get_orchestrator  # Multi-model orchestrator
```

### Project Structure
```
CosySim/
├── engine/         # Core framework — modify carefully
│   ├── mcp/        # MCPFramework, DialogSystem, GameMCP, Governor, CosySim MCP Server
│   ├── agents/     # VirtualAgent, InterceptorPipeline, StreamProcessor
│   ├── lmstudio/   # LMS client, router, conversation, model manager, orchestrator
│   ├── scenes/     # BaseScene, SceneManager, SceneRegistry
│   ├── skills/     # @skill decorator, registry, 13 builtin packs
│   ├── services/   # Activity bus, resilience, housekeeping
│   ├── pipeline/   # VirtualPipeline, token routing
│   ├── tts/        # Qwen3 TTS server
│   ├── nexus/      # Nexus KMS client + CLI tools
│   └── config.py   # ConfigManager singleton
├── content/        # Game content
│   ├── scenes/     # 18 scene implementations
│   └── simulation/ # Database, character system, services
├── config/         # YAML/JSON config (default, dev, prod, voices, skills, mcp)
├── tests/          # pytest suite (70+ files, 1903+ tests)
├── docs/           # Documentation (INDEX.md entry point)
├── .github/        # Copilot customization (instructions, agents, hooks)
├── .vscode/        # VS Code config + MCP server definitions
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
- **On context compaction**: run `python engine/nexus/nexus_session_logger.py compact` to export checkpoint and decision data to Nexus before context is lost
- **After major work blocks**: run `python engine/nexus/nexus_session_logger.py checkpoint` to export new checkpoints to Nexus

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
| `instructions/nexus.instructions.md` | `engine/nexus/**`, `engine/skills/builtin/nexus_skills.py`, `engine/skills/builtin/coding_skills.py` |
| `instructions/testing.instructions.md` | `tests/**/*.py` |
| `instructions/lmstudio.instructions.md` | `engine/lmstudio/**/*.py` |
| `instructions/config.instructions.md` | `config/**/*.yaml` |
| `instructions/frontend.instructions.md` | `content/scenes/**/templates/**`, `content/scenes/**/static/**` |
| `instructions/deployment.instructions.md` | Startup scripts, deployment files |

## Custom Agents

| Agent | Purpose |
|-------|---------|
| `Copilot Workflow` | Master agent — uses all MCP tools, Nexus-first workflow |
| `Scene Builder` | Scaffold new scenes from scratch |
| `Scene Debugger` | Diagnose and fix scene/agent issues |
| `Scene Auditor` | Rate scenes against AAA quality standard |
| `Skill Developer` | Create and register MCP skill packs |
| `Test Writer` | Generate pytest test suites |
| `Doc Writer` | Maintain documentation system |
| `Codebase Navigator` | Explain architecture, trace call chains |
| `System Architect` | Cross-project architecture decisions |
| `Nexus Researcher` | Research topics, store findings, manage knowledge |

## Documentation
- Entry point: `docs/INDEX.md`
- Architecture: `docs/ARCHITECTURE.md`
- Full doc list: 20 files covering framework, scenes, skills, config, API, testing, training, LMStudio, TTS, characters, admin

## Nexus Knowledge System

Nexus is the **first port of call** for information retrieval and storage.
Before writing code, search Nexus. After making decisions, store them in Nexus.

### MCP Tools (Preferred — call directly via tool use)
These 14 Nexus tools are available via the CosySim MCP server (`.vscode/mcp.json`):
```
nexus_search("interceptor pipeline")          — Search knowledge base
nexus_ask("How does state persistence work?") — Smart Q&A (cache → FTS → NLM)
nexus_add("Title", content, "decision")       — Store knowledge entry
nexus_add_qa("How does X?", "X works by...")  — Store Q&A pair
nexus_get_rules("coding")                     — Get governance rules
nexus_store_prompt("system_v2", content)       — Version a prompt
nexus_get_prompts("system")                   — Retrieve stored prompts
nexus_research("Best approach for X?")        — Start deep NLM research
nexus_converse(research_id, "follow up")      — Continue research
nexus_finish_research(research_id)            — Distill Q&A from research
nexus_import_youtube(url)                     — Import video transcript
nexus_log_session("CosySim")                  — Track work session
nexus_status()                                — Check Nexus health
nexus_list_plugins()                          — List plugins
seed_nexus("all")                             — Seed/refresh knowledge base
nexus_maintain("health")                      — Maintenance: health/dedup/cleanup/reindex
```

### Python API (for project code)
```python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
results = client.search("interceptor pipeline")
answer = client.ask("How does state persistence work?")
client.add_entry("Decision: Use FTS5", content, content_type="document", category="architecture")
```

### CLI Bridge (standalone — works without MCP server)
```bash
python -m engine.nexus.bridge search "interceptor pipeline"
python -m engine.nexus.bridge ask "How does state work?"
python -m engine.nexus.bridge store "Title" "content" --type note --category dev
python -m engine.nexus.bridge qa "Question?" "Answer."
python -m engine.nexus.bridge rules "global"
python -m engine.nexus.bridge health
python -m engine.nexus.bridge seed all
python -m engine.nexus.bridge maintain dedup
```

### Legacy CLI
```bash
python -m engine.nexus.cli search "interceptor pipeline"
python -m engine.nexus.cli ask "How does state work?"
python -m engine.nexus.cli status
```

### Nexus Skills for LLM Agents
| Skill | Use For |
|-------|---------|
| `nexus_ask` | Smart Q&A (cache → FTS → NLM) |
| `nexus_search` | Full-text knowledge search |
| `nexus_research` | Start deep NLM research |
| `nexus_converse` | Continue research conversation |
| `nexus_finish_research` | Complete and distill research |
| `nexus_youtube` | Import video transcripts |
| `coding_store_snippet` | Store reusable code |
| `coding_store_decision` | Record architecture decisions |
| `coding_research` | Research APIs/libraries |
| `coding_store_bug` | Record bug analysis + fix |
| `coding_log_session` | Track dev sessions |

See `instructions/nexus.instructions.md` for full usage guide.
