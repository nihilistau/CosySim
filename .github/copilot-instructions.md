# Copilot Instructions — CosySim

> This file provides repository-level context. Modular path-specific rules
> are in `.github/instructions/`. Custom agents are in `.github/agents/`.
> Global system rules are in `~/.copilot/copilot-instructions.md` and
> `~/.config/copilot/shared-rules/`.

## Project Overview

CosySim is a multi-scene AI simulation framework (v0.59b) built on
a custom MCP pipeline with LMStudio v1 API integration and Nexus knowledge system.
It orchestrates virtual agents across 18 interactive scenes, each with real-time
state management, skill-based tool calling, dialog systems, and interceptor-governed
agent behavior. Nexus provides central knowledge management, rules engine,
session tracking, and prompt versioning.

**Core systems:** MCPFramework state tree · DialogSystem conversation threading
· InterceptorPipeline agent governance · @skill decorator tools · EventChain
audit logging · LMStudio v1 streaming with stateful conversations · Nexus knowledge system
· InferenceOrchestrator multi-model routing · RouterDataCollector training capture

**Test suite:** 4,660+ tests across 140 files — run before and after changes.

**MCP Server:** 108+ tools available via `.vscode/mcp.json` — includes Nexus bridge,
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
from engine.lmstudio.router_data import get_router_data_collector  # Training data
from engine.nexus.governance_rules import get_governance_manager  # Governance enforcement
from engine.assistant.phone_assistant import get_phone_assistant  # Phone assistant
from engine.integrations.anythingllm import get_anythingllm_client  # AnythingLLM
```

### Project Structure
```
CosySim/
├── engine/         # Core framework — modify carefully
│   ├── mcp/        # MCPFramework, DialogSystem, GameMCP, Governor, MCP Server (108+ tools)
│   ├── agents/     # VirtualAgent, InterceptorPipeline, StreamProcessor
│   ├── lmstudio/   # LMS client, router, conversation, model manager, orchestrator, router_data
│   ├── scenes/     # BaseScene, SceneManager, SceneRegistry
│   ├── skills/     # @skill decorator, registry, 21 builtin packs (188 skills)
│   ├── services/   # Activity bus, resilience, housekeeping
│   ├── pipeline/   # VirtualPipeline, token routing
│   ├── tts/        # TTS manager (Piper, Orpheus, Qwen3)
│   ├── nexus/      # Nexus client, NLM engine, governance, scheduler, deep storage
│   ├── assistant/  # System assistant (Aria) + phone assistant
│   ├── integrations/ # AnythingLLM, Home Assistant, phone news
│   └── config.py   # ConfigManager singleton
├── content/        # Game content
│   ├── scenes/     # 18 scene implementations
│   └── simulation/ # Database, character system, services
├── config/         # YAML/JSON config (default, dev, prod, voices, skills, mcp)
├── tests/          # pytest suite (140 files, 4,660+ tests)
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
| Nexus Panel | 5570 | Nexus dashboard + Librarian |

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
- **Search Nexus first** — before writing any code, `nexus_search("topic")` or `nexus_ask("question?")`
- **Store audit results in Nexus** — all audit/rating results must be stored as Nexus entries with content_type="audit"
- **Governance is enforced** — `@governed` decorator and `enforce_governance()` block unauthorized operations
- **On context compaction**: run `python engine/nexus/nexus_session_logger.py compact` to export checkpoint and decision data to Nexus before context is lost
- **After major work blocks**: run `python engine/nexus/nexus_session_logger.py checkpoint` to export new checkpoints to Nexus
- **New agents**: see `docs/AGENT_ONBOARDING.md` for full onboarding guide

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
| `Code Reviewer` | Review code changes against conventions |
| `Bug Fixer` | Diagnose and fix bugs from task tickets |
| `Feature Builder` | Implement features from structured tickets |
| `Refactoring Agent` | Structural refactoring without behavior change |
| `Benchmark Runner` | Execute LMStudio benchmarks, store results |
| `Config Optimizer` | Optimize YAML configs based on benchmark data |
| `Knowledge Curator` | Maintain Nexus knowledge quality |
| `Integration Tester` | Test inter-system integration points |

## Documentation
- Entry point: `docs/INDEX.md`
- Architecture: `docs/ARCHITECTURE.md`
- System audit: `docs/SYSTEM_AUDIT.md` (v0.55b, grade A-)
- Full doc list: 26 files covering framework, scenes, skills, config, API, testing, training, LMStudio, TTS, characters, admin, Nexus, NLM

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
nexus_add_url(url, tags="ai,research")        — Add URL and optionally scrape
nexus_list_urls(domain="github.com")          — List stored URLs
nexus_scrape_url(url)                         — Scrape URL into Nexus fragments
nexus_url_stats()                             — URL system statistics
nexus_track_feature(name, description)        — Track feature implementation status
nexus_list_features()                         — List features and their status
llmster_status()                              — Daemon/server/model status
llmster_load(model, n_parallel=4)             — Load model with continuous batching
llmster_unload(model)                         — Unload model
llmster_models()                              — List available models on disk
llmster_download(model)                       — Download model from catalog
governance_enforce(filepath, agent_id)        — Active enforcement (raises on violations)
phone_assistant_chat(message, mode, voice)    — Chat via 4-tier cascade
phone_assistant_status()                      — Assistant mode + connectivity
phone_assistant_set_mode(mode)                — Set routing mode
allm_chat(workspace, message, instance)       — Chat with AnythingLLM
deep_storage_archive(notebook_id)             — Archive notebook to Nexus
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

### NLM Forge Skills (NotebookLM-powered)
| Skill | Use For |
|-------|---------|
| `nlm_ask` | Route question through 4-tier NLM-first pipeline |
| `nlm_batch_ask` | Batch-ask multiple questions via NLM router |
| `nlm_create_notebook` | Create NLM notebook with sources |
| `nlm_add_codebase` | Add source files to NLM notebook |
| `nlm_generate_doc` | Generate study guides, FAQs, briefings |
| `nlm_distill` | Distill Q&A pairs from notebook |
| `nlm_decompose` | Break plan into small-model steps |
| `nlm_analyze` | Analyze source code via NLM |
| `nlm_solve` | Solve problems with NLM + code context |
| `nlm_build_topic` | End-to-end knowledge building pipeline |

### NLM CLI (terminal)
```bash
python -m engine.nexus.nlm_cli ask "How does the interceptor pipeline work?"
python -m engine.nexus.nlm_cli batch-ask -f questions.txt -n nb-123
python -m engine.nexus.nlm_cli distill nb-123 --topic "MCP state" --count 20
python -m engine.nexus.nlm_cli forge "MCP Framework" --sources https://docs.example.com
python -m engine.nexus.nlm_cli stats
```

See `instructions/nexus.instructions.md` for full usage guide.

## NLM-First Workflow — MANDATORY

**Every question should go through the NLM-first router.** This saves compute
and compounds knowledge over time.

### The 4-Tier Pipeline
```
Tier 1: Nexus Q&A Cache  → instant, free (prior answers)
Tier 2: Nexus FTS Search → fast, free (synthesize from entries)
Tier 3: NotebookLM Ask   → free Gemini compute (auto-stores for Tier 1)
Tier 4: LMStudio LLM     → local GPU, LAST RESORT
```

### Before Every Task
1. **Search Nexus** — `nexus_search("task topic")` to find existing knowledge
2. **Check Q&A** — `nexus_ask("key question")` for cached answers
3. **Batch-ask NLM** — Write out 10-20 questions, send via `nlm_batch_ask`
4. **Work from answers** — Use NLM knowledge instead of burning LLM tokens

### After Every Task
1. **Store decisions** — `nexus_add("Decision: ...", content, "decision")`
2. **Cache Q&A** — `nexus_add_qa("How does X?", "X works by...")`
3. **Log session** — `nexus_log_session("CosySim")`

### The Compound Effect
Every answer stored in Nexus is one fewer LLM call in the future.
Cache hit rate increases over time. NLM calls decrease. The system
gets smarter the more it's used.
