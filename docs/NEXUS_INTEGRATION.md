# Nexus Integration Guide

> v0.91b — 85 engine modules, 5-tier query router, 55 scheduler tasks, 93 skills

Nexus is CosySim's central knowledge management system — a persistent SQLite + FTS5
backbone that stores entries, rules, Q&A pairs, session history, prompts, benchmarks,
and training data. Every agent, scene, skill, and Copilot session consumes and
contributes to Nexus. The system is designed to compound: every interaction makes
future interactions cheaper and more accurate.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Copilot CLI / GitHub Copilot Agent                          │
│  ├── CopilotBridge       session start/end, pre-plan, metrics│
│  ├── CopilotSelfConfig   sync instructions/agents/hooks      │
│  ├── CopilotValidation   drift detection, hook integrity      │
│  ├── SeedCopilotRules    mirror repo assets into Nexus        │
│  └── SessionLogger       checkpoint/compact/end export        │
├──────────────────────────────────────────────────────────────┤
│  CosySim Engine (Agents, Scenes, Skills)                      │
│  ├── NexusClient          HTTP client for Nexus API (40+ methods)
│  ├── NexusQueryRouter     5-tier smart routing (cache→FTS→NLM→LLM)
│  ├── TrainingFlywheel     auto-collect training data from runtime│
│  ├── TaskScheduler        agent task ticketing with templates   │
│  ├── SchedulerDaemon      55 recurring tasks (cron-like)       │
│  ├── OperatorInbox        off-turn directive intake            │
│  ├── KnowledgeCapture     dual-write backfill helper           │
│  ├── ActionManifest       structured pre-plan artifacts        │
│  ├── BootstrapNotebooks   NLM notebook fleet management        │
│  ├── NLMChain             multi-step chain-prompting           │
│  ├── NotebookLMFlywheel   control notebook → tasks → training  │
│  ├── QAExpander           reverse-generate Q&A from entries    │
│  ├── QAGenerator          rule-based + LLM Q&A generation      │
│  ├── NewsPipeline         fetch → dedup → store → distill      │
│  ├── GoogleAccountManager multi-account cookie pool            │
│  └── 85 total modules in engine/nexus/                        │
├──────────────────────────────────────────────────────────────┤
│  Skills Layer (93 Nexus-aware skills)                         │
│  ├── nexus_skills.py      17 skills (search, ask, store, NLM) │
│  ├── coding_skills.py      9 skills (snippets, decisions, bugs)│
│  └── autonomy_skills.py   67 skills (scheduler, training, gov)│
├──────────────────────────────────────────────────────────────┤
│              Nexus HTTP REST API (port 8700)                  │
├──────────────────────────────────────────────────────────────┤
│  Nexus Server (C:\Files\Nexus)                                │
│  ├── SQLite + FTS5         Full-text search engine             │
│  ├── Flask REST API        CRUD + search + rules + sessions    │
│  └── 3-layer DB            entries, rules, Q&A cache           │
└──────────────────────────────────────────────────────────────┘
```

### Database Layers

| Layer | Table | Purpose |
|-------|-------|---------|
| Knowledge | `entries` | Notes, code, docs, prompts, transcripts, memories, plans |
| Rules | `rules` | Governance rules with scope, conditions, actions |
| Q&A Cache | `qa_pairs` | Direct question→answer lookup (fastest tier) |

### Content Types

| Type | Use For |
|------|---------|
| `note` | General knowledge, observations, decisions |
| `code` | Code snippets, patterns, templates |
| `prompt` | System/agent prompts (versioned) |
| `document` | Design docs, specs, guides |
| `transcript` | YouTube/video transcripts |
| `research` | Research session artifacts |
| `memory` | Agent memories/observations |
| `history` | Session histories, changelogs |
| `plan` | Implementation plans, action manifests |

---

## Nexus-First Workflow

Every agent must follow this pattern:

### Before Work
1. **Query Nexus first** — `nexus_smart_query("question")` or `nexus_ask("question")`
2. **Check rules** — `nexus_get_rules(scope="scene:X")`
3. **Load prompts** — `nexus_get_prompts(category="system")`

### During Work
4. **Store decisions** — `nexus_add(title, content, content_type="note", category="architecture")`
5. **Log sessions** — `nexus_log_session(project="CosySim", summary="...")`
6. **Store snippets** — `coding_store_snippet(title, code, language, tags)`

### After Work
7. **Store Q&A** — `nexus_add_qa(question, answer, category)`
8. **Backfill misses** — if Nexus didn't have the answer and you found it elsewhere, write it back
9. **Distill research** — `nexus_finish_research(research_id)`

---

## NexusClient API

`engine/nexus/client.py` — HTTP client for the Nexus REST API.

```python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
```

### Core Operations

```python
# Search
results = client.search("interceptor pipeline", limit=10)

# Add entry
entry_id = client.add_entry(
    title="Decision: Use FTS5",
    content="Chose FTS5 over vector search for...",
    content_type="note",
    category="architecture",
    tags=["database", "search"]
)

# Get / Update / Delete
entry = client.get_entry(entry_id)
client.update_entry(entry_id, content="Updated content")
client.delete_entry(entry_id)

# List by type
notes = client.list_by_type("note", category="architecture", limit=50)
```

### Q&A Operations

```python
# Smart ask (4-tier routing)
result = client.ask("How does the interceptor pipeline work?", depth="auto")
# → {answer, source, confidence, sources, qa_id}

# Direct Q&A
pairs = client.find_qa("interceptor pipeline", limit=5)
client.add_qa("How does X work?", "X works by...", category="dev")
```

### Research Sessions

```python
# Multi-turn research via NotebookLM
session = client.research("MCP state management best practices")
followup = client.converse(session["research_id"], "What about persistence?")
done = client.finish_research(session["research_id"])
```

### Session Management

```python
session_id = client.log_session(
    project="CosySim", branch="main",
    summary="Implemented query router", status="completed"
)
client.update_session(session_id, summary="Added NLM fallback tier")
```

### Rules Engine

```python
rules = client.get_rules(scope="scene:bedroom", rule_type="governance")
client.add_rule(
    scope="global", rule_type="enforcement",
    name="nexus-first", condition="before_task",
    action="query_nexus"
)
```

### NotebookLM Integration

```python
answer = client.nlm_ask("What are the core components?", notebook_id="abc")
unified = client.nlm_unified_ask("Architecture overview")
status = client.nlm_status()
notebooks = client.nlm_list_notebooks()
```

### Health & Benchmarks

```python
health = client.health()            # {status, entries, qa_pairs, rules}
stats = client.stats()              # Detailed statistics
available = client.is_available()   # Quick connectivity check

client.store_benchmark("qwen3-0.6b", "routing", {"accuracy": 0.92})
leaderboard = client.get_leaderboard("routing", limit=10)
```

### Sub-Clients

```python
client.rules.get_rules(scope="global")    # NexusRulesClient
client.sessions.list(project="CosySim")   # NexusSessionClient
client.memory.recall(agent_id="copilot")  # NexusMemoryClient
```

---

## NexusQueryRouter — 5-Tier Smart Routing

`engine/nexus/query_router.py` — the preferred entry point for all information retrieval.

### Pipeline

```
Question arrives
    │
    ▼
1. Q&A Cache ──────── Direct lookup in Nexus Q&A pairs
    │ miss              Instant, high confidence
    ▼
2. FTS Knowledge ──── Full-text search across entries
    │ miss              Fast, medium confidence
    ▼
3. Nexus Smart Ask ── Server-side pipeline (cache → FTS → NLM)
    │ miss              Medium speed, high confidence
    ▼
4. Direct NLM Ask ─── NotebookLM unified ask
    │ miss              Slower, high confidence (grounded)
    ▼
5. LLM Fallback ───── Local LMStudio inference
                        Variable confidence, uses tokens
```

### Auto-Store Behavior

Every answer from tiers 4 and 5 is automatically stored back into Nexus as a Q&A
pair. This creates a self-improving loop: the first time a question is asked it
costs tokens; every subsequent time it's served from cache for free.

### Usage

```python
from engine.nexus.query_router import get_query_router

router = get_query_router()

# Query with smart routing
result = router.query("How does state sync work?", min_confidence=0.3)
# → QueryResult(answer="...", source="cache", confidence=0.95, cached=True,
#               tokens_saved=450, query_time_ms=12.3)

# Check router effectiveness
stats = router.stats
# → RouterStats(total_queries=142, cache_hits=98, search_hits=22,
#               nlm_hits=15, llm_fallbacks=7, total_tokens_saved=45000)
```

### QueryResult Fields

| Field | Type | Description |
|-------|------|-------------|
| `answer` | str | The answer text |
| `source` | str | Which tier answered: `cache`, `search`, `nexus-*`, `nlm*`, `llm` |
| `confidence` | float | 0.0–1.0 confidence score |
| `cached` | bool | Whether this was a cache hit |
| `tokens_saved` | int | Estimated tokens saved vs direct LLM |
| `query_time_ms` | float | Total query time in milliseconds |

---

## Training Flywheel

`engine/nexus/training_flywheel.py` — automatic training data collection from every
system interaction, exportable in JSONL, ShareGPT, and DPO formats.

### Collection Sources

```python
from engine.nexus.training_flywheel import TrainingFlywheel
flywheel = TrainingFlywheel()

# From task completions
flywheel.collect_from_task(task_id, description, result, model="qwen3-0.6b")

# From Q&A pairs (auto-wired from QA Expander and Generator)
flywheel.collect_from_qa(question, answer, source="cache", quality=0.7)

# From NotebookLM research
flywheel.collect_from_nlm(question, answer, notebook_id="abc", quality=0.8)

# From router decisions (DPO training)
flywheel.collect_from_routing(question, chosen_source="cache", rejected_source="llm")

# Direct preference pairs
flywheel.collect_preference(question, preferred_answer, rejected_answer)
```

### Export Formats

```python
# Instruction-tuning format: {instruction, output}
jsonl = flywheel.export_jsonl(min_quality=0.5)

# Conversational format: {conversations: [{from, value}]}
sharegpt = flywheel.export_sharegpt(min_quality=0.5)

# Preference format: {prompt, chosen, rejected}
dpo = flywheel.export_dpo()

# Sync from Nexus Q&A
flywheel.sync_from_nexus()
```

---

## Scheduler Daemon — 55 Recurring Tasks

`engine/nexus/scheduler_daemon.py` — lightweight cron-like daemon with persistent
state, schedule parsing, and thread-pool execution.

### Task Categories

| Category | Count | Key Tasks |
|----------|-------|-----------|
| Nexus Maintenance | 3 | `nexus-health`, `nexus-dedup`, `nexus-quality-eval` |
| Knowledge | 5 | `qa-expansion`, `qa-cache-prune`, `coverage-eval` |
| Training | 6 | `training-sync`, `model-zoo-train`, `coder-dataset-refresh` |
| Notebooks | 4 | `notebook-bootstrap`, `master-notebook-refresh`, `nlm-content-seed` |
| Control Plane | 3 | `copilot-rules-refresh`, `copilot-self-sync`, `control-notebook-flywheel` |
| Router | 3 | `router-data-export`, `router-v3-retrain`, `router-finetune-cycle` |
| Experiments | 2 | `experiment-scan`, `improvement-review` |
| News | 3 | `news-fetch`, `news-distill-nlm`, `ha-news-push` |
| Sessions | 2 | `session-distillation`, `qa-generation` |
| System | 4 | `system-reflection`, `doc-sync`, `metrics-collect` |
| NotebookLM | 5 | `nlm-cookie-refresh`, `argus-weekly-scan`, `argus-diff-report` |
| World Sim | 3 | `npc-world-tick`, `world-sim-tick`, `director-tick` |
| Scene/Content | 4 | `scene-lore-seed`, `daily-challenge-seed`, `content-refresh` |
| Auth/Health | 4 | `cookie-health-check`, `cookie-auto-refresh`, `test-suite-benchmark` |
| Governance | 1 | `governance-audit` |
| Operator | 1 | `operator-inbox-sync` |
| Testing | 1 | `test-monitor` |

### Usage

```python
from engine.nexus.scheduler_daemon import TaskSchedulerDaemon

daemon = TaskSchedulerDaemon()
daemon.start(interval_seconds=60)   # Check due tasks every 60s

# Manual trigger
result = daemon.run_task("nexus-health")

# Status
status = daemon.status()
tasks = daemon.list_tasks()

daemon.stop()
```

### CLI

```powershell
# Start daemon
python -m engine.nexus.scheduler_daemon start

# Run specific task
python -m engine.nexus.scheduler_daemon run nexus-health

# List all tasks
python -m engine.nexus.scheduler_daemon list
```

---

## Task Scheduler — Agent Ticketing

`engine/nexus/task_scheduler.py` — ticketing system for local and Copilot agents
with priorities, dependencies, templates, and auto-generation.

### AgentTask Model

```python
@dataclass
class AgentTask:
    id: str                        # UUID
    title: str                     # Short name
    description: str               # Full description
    priority: int                  # CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, BACKGROUND=4
    complexity: str                # LOW, MEDIUM, HIGH
    status: str                    # PENDING, CLAIMED, IN_PROGRESS, COMPLETED, FAILED, BLOCKED
    claimed_by: str                # Agent ID
    parent_id: str                 # Parent task (subtask support)
    subtask_ids: List[str]         # Child tasks
    target_files: List[str]        # Files to modify
    allowed_operations: List[str]  # read, edit, create, test, execute
```

### Task Workflow

```python
from engine.nexus.task_scheduler import TaskScheduler

scheduler = TaskScheduler()

# Create task
task = scheduler.create_task(
    title="Fix interceptor ordering",
    description="Reorder interceptors to run safety check first",
    priority=1,  # HIGH
    target_files=["engine/agents/interceptors/pipeline.py"]
)

# Agent claims next available
task = scheduler.claim_task(agent_id="local-agent-1", priority_filter=2)

# Complete or fail
scheduler.complete_task(task.id, result="Fixed ordering", quality_score=0.9)
scheduler.fail_task(task.id, reason="Dependency missing", retry=True)
```

### Auto-Generation

```python
# From test failures
tasks = scheduler.generate_from_test_failures(pytest_output)

# From benchmark regressions
tasks = scheduler.generate_from_benchmark(benchmark_output, regression_pct=10.0)

# From stale knowledge
tasks = scheduler.generate_from_stale_knowledge(days=30)

# From templates
task = scheduler.from_template("feature", title="Add vision skills")
```

---

## Operator Inbox

`engine/nexus/operator_inbox.py` — durable communication path for off-turn user
directives, notes, questions, and feature requests.

### Workflow States

```
pending → queued → integrated → done
                 → blocked (with reason)
```

### Usage

```python
from engine.nexus.operator_inbox import OperatorInbox

inbox = OperatorInbox()

# Submit directive
item_id = inbox.submit_item(
    item_type="feature",
    title="Add vision model support",
    description="Wire Qwen2-VL into ARGUS",
    priority="high",
    tags=["vision", "argus"]
)

# Process pending items
inbox.process_items(query="vision", processor_fn=my_handler)

# Get items for Copilot onboarding
directives = inbox.pending_for_onboarding(limit=5)
```

### Integration Points
- **Scheduler**: `operator-inbox-sync` task processes pending items
- **Intel Hub**: `/api/operator/*` routes for web UI
- **Copilot Bridge**: `session_start()` loads pending operator directives

---

## Copilot Bridge

`engine/nexus/copilot_bridge.py` — makes Copilot CLI self-improving via Nexus and
NotebookLM integration.

### Session Lifecycle

```python
from engine.nexus.copilot_bridge import CopilotBridge

bridge = CopilotBridge()

# Session start — warm-load all services, build context
context = bridge.session_start(task_description="Fix interceptor ordering")
# Returns: {nexus, nlm, router, forge, context, resume_handoff,
#           operator_directives, control_context_packet, startup_services}

# Pre-plan — ask NLM, build action manifest
plan = bridge.pre_plan(
    task_description="Fix interceptor ordering",
    context_files=["engine/agents/interceptors/pipeline.py"]
)
# Returns: {preplan_qa, action_manifest, recommendations}

# Session end — distill learnings, store metrics
bridge.session_end(summary="Fixed interceptor ordering, added safety-first rule")
```

### What Gets Loaded at Session Start

| Resource | Source | Purpose |
|----------|--------|---------|
| Resume handoff | Nexus entry | Previous session state and decisions |
| Context packets | Nexus entries | Architecture docs, control-plane rules |
| Control context | Nexus flywheel | Latest control notebook summary |
| Operator directives | Operator inbox | Pending user notes/questions |
| Startup services | Runtime | Nexus, router, forge, scheduler, inbox health |

### Metrics Tracked

```python
bridge.metrics  # SessionMetrics
# → searches, nlm_asks, cache_hits, files_edited, tools_used,
#   errors, decisions_stored, qa_stored, tokens_saved
```

---

## Copilot Self-Configuration

### CopilotSelfConfig (`engine/nexus/copilot_self_config.py`)

Synchronizes Copilot configuration between the repository and Nexus:

```python
from engine.nexus.copilot_self_config import CopilotSelfConfig

config = CopilotSelfConfig()

# Sync repo → Nexus (hash-based dedup)
result = config.sync_all_to_nexus()
# → {instructions: {stored, updated, skipped}, agents: {...}, hooks: {...}}

# Read from Nexus
instructions = config.get_instructions_from_nexus()

# Preferences (session-learned)
config.store_preference("preferred_model", "qwen3-0.6b")
model = config.get_preference("preferred_model", "default-model")
```

### SeedCopilotRules (`engine/nexus/seed_copilot_rules.py`)

Seeds all Copilot rules, instructions, agents, and docs into Nexus:

```powershell
python -m engine.nexus.seed_copilot_rules
# → "8 stored / 3 updated / 37 skipped / 0 errors / 9 deduped"
```

**Sources seeded:**
- `~/.copilot/copilot-instructions.md` (global)
- `.github/copilot-instructions.md` (project)
- `.github/instructions/*.instructions.md` (12 path-specific)
- `.github/agents/*.agent.md` (19 agent definitions)
- `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_ONBOARDING.md`

### CopilotValidation (`engine/nexus/copilot_validation.py`)

Validates three surfaces:

1. **Nexus Sync Drift** — are Copilot mirrors current in Nexus?
2. **Hook Integrity** — do all hook manifests and referenced scripts exist?
3. **Runtime Health** — can CopilotBridge and CopilotSelfConfig initialize?

```powershell
python -m engine.nexus.copilot_validation --json
# → {ok: true, issue_count: 0, warning_count: 0, error_count: 0}
```

---

## Knowledge Capture

`engine/nexus/knowledge_capture.py` — standardized dual-write pattern for
backfilling external discoveries.

### The Pattern

When Nexus doesn't have the answer and you find it elsewhere:

```python
from engine.nexus.knowledge_capture import capture_external_discovery

result = capture_external_discovery(
    question="How does SceneStateManager work?",
    answer="SceneStateManager coordinates...",
    source="engine/mcp/scene_state.py",
    category="architecture"
)
# Writes BOTH:
# 1. A reusable knowledge entry (discoverable via search)
# 2. A direct Q&A pair (instant via question match)
```

### CLI

```powershell
python -m engine.nexus.bridge backfill "How does X work?" "X works by..." --source docs
```

---

## Action Manifest

`engine/nexus/action_manifest.py` — structured artifact from pre-plan Q&A that
agents can consume without reloading task context.

### Format

```json
{
  "manifest_id": "preplan-fix-interceptor-ordering",
  "task": "Fix interceptor ordering",
  "summary": "Reorder interceptors to run safety check first",
  "context_files": ["engine/agents/interceptors/pipeline.py"],
  "steps": [
    {
      "step_id": "step-1",
      "action_type": "edit",
      "title": "Move SafetyInterceptor to position 0",
      "target_file": "engine/agents/interceptors/pipeline.py",
      "dependencies": [],
      "validation": ["Import succeeds", "Tests pass"]
    }
  ],
  "milestones": [
    {
      "milestone_id": "m1",
      "title": "Safety-first ordering implemented",
      "step_ids": ["step-1"],
      "dependencies": []
    }
  ],
  "next_actions": ["Run interceptor tests", "Verify governance chain"]
}
```

### Action Types

| Type | Description |
|------|-------------|
| `RESEARCH` | Investigate before implementing |
| `EDIT` | Modify existing file |
| `SHELL` | Run a command |
| `TEST` | Run tests to verify |

---

## Session Logger

`engine/nexus/nexus_session_logger.py` — exports Copilot CLI session events to Nexus.

### Commands

```powershell
# Checkpoint — export current checkpoint to Nexus
python engine/nexus/nexus_session_logger.py checkpoint

# Compact — full snapshot before context compaction
python engine/nexus/nexus_session_logger.py compact

# End — finalize session, distill Q&A, store summary
python engine/nexus/nexus_session_logger.py end
```

### What Gets Exported

| Command | Captures |
|---------|----------|
| `checkpoint` | Checkpoint title, overview, modified files, git context |
| `compact` | All checkpoints, decisions, plan state, git diff |
| `end` | Full session history, distilled Q&A, key decisions, metrics |

### Hook Integration

The session logger is wired into Copilot hooks via `.github/hooks/`:
- `sessionStart` → `handle_start()`
- `sessionEnd` → `handle_end()`
- `userPromptSubmitted` → `handle_prompt()` (auto-detects new checkpoints)
- `preCompaction` → `handle_compaction()`

---

## Bridge CLI

`engine/nexus/bridge.py` — standalone CLI for Nexus operations when MCP tools
are unavailable.

### Commands

```powershell
# Search knowledge
python -m engine.nexus.bridge search "interceptor pipeline" --limit 10

# Smart ask (5-tier routing)
python -m engine.nexus.bridge ask "How does state sync work?" --depth auto

# Store entry
python -m engine.nexus.bridge store "Decision: Use FTS5" "content..." --type note --category architecture

# Store Q&A
python -m engine.nexus.bridge qa "How does X work?" "X works by..." --category dev

# Backfill external discovery (entry + Q&A)
python -m engine.nexus.bridge backfill "Question?" "Answer." --source docs

# System inventory
python -m engine.nexus.bridge inventory --store

# Rules lookup
python -m engine.nexus.bridge rules global

# Health check
python -m engine.nexus.bridge health

# Seed knowledge base
python -m engine.nexus.bridge seed all

# Maintenance
python -m engine.nexus.bridge maintain health
python -m engine.nexus.bridge maintain dedup
python -m engine.nexus.bridge maintain cleanup
```

---

## NotebookLM Integration

### Bootstrap Notebooks (`engine/nexus/bootstrap_notebooks.py`)

Manages a fleet of purpose-built NotebookLM notebooks:

| Notebook | Sources | Purpose |
|----------|---------|---------|
| `cosysim-architecture` | README, docs/, engine structure | Design and architecture questions |
| `copilot-instructions` | .github/ rules, agents, instructions | Runtime rules for agents |
| `copilot-session-history` | Recent session checkpoints | Session history distillation |
| `cosysim-codebase` | Engine Python source (chunked) | Code analysis and patterns |
| `copilot-system-control` | System state, plans, configs | Control-plane orchestration |

```python
from engine.nexus.bootstrap_notebooks import bootstrap_all

# Bootstrap all notebooks with distillation
result = bootstrap_all(distill=True)

# Scheduler: "notebook-bootstrap" task runs weekly
```

### NLM Chain Engine (`engine/nexus/nlm_chain.py`)

Multi-step chain-prompting with progressive research:

```python
from engine.nexus.nlm_chain import NLMChainEngine

engine = NLMChainEngine()

# Single notebook distillation
result = engine.distill_notebook(notebook_id, questions=[
    "What are the core components?",
    "How does governance work?",
    "What are the key patterns?"
])

# Multi-step chain
result = engine.execute_chain("architecture-review", notebook_id,
    initial_question="What are the architectural gaps?"
)

# Batch across notebooks
result = engine.run_batch("weekly-review")

# Generate action manifest from Q&A
manifest = engine.generate_action_manifest("Fix gaps", qa_pairs)
```

### NotebookLM Flywheel (`engine/nexus/notebooklm_flywheel.py`)

Control notebook → structured artifact → tasks → training data:

```
1. Multi-Ask Phase    — Ask grounded control-plane questions
2. Report Phase       — Generate strict JSON artifact
3. Storage Phase      — Store artifact + context packet in Nexus
4. Task Phase         — Create TaskScheduler items for agents
5. Training Phase     — Feed TrainingFlywheel with Q&A + task envelopes
```

```python
from engine.nexus.notebooklm_flywheel import NotebookLMFlywheel

flywheel = NotebookLMFlywheel()
result = flywheel.run(
    questions=["What is the system state?", "What needs attention?"],
    create_tasks=True,
    collect_training=True
)
```

---

## Q&A Generation

### QA Expander (`engine/nexus/qa_expander.py`)

Reverse-generates Q&A from existing Nexus entries via NotebookLM:

```
For each entry:
  1. Ask NLM: "What 5 questions does this entry answer?"
  2. For each question: distill the answer via NLM
  3. Store as Nexus Q&A pair
  4. Feed into TrainingFlywheel
```

```python
from engine.nexus.qa_expander import QAExpander

expander = QAExpander()
result = expander.run(batch_size=20)  # Expand next 20 entries
stats = expander.stats()               # Progress: expanded, remaining
```

### QA Generator (`engine/nexus/qa_generator.py`)

Two-mode Q&A generation:

| Mode | Speed | Quality | Pairs/Run |
|------|-------|---------|-----------|
| Rule-based | Instant | Medium | 200–800 |
| LLM-based | Slower | High | ~200 |

```python
from engine.nexus.qa_generator import run_rule_based, run_llm_based

# Rule-based: parse titles → generate questions
count = run_rule_based(limit=800)

# LLM-based: send content to LMStudio → generate Q&A
count = run_llm_based(limit=200, n_pairs_each=2)
```

---

## News Pipeline

`engine/nexus/news/` — automated news ingestion with 4-stage pipeline.

### Pipeline Stages

```
1. Fetch     — RSS feeds per category (tech, AI, world, science)
2. Dedup     — Content-hash deduplication
3. Store     — Create Nexus entries with category="news"
4. Distill   — Generate Q&A from article summaries
```

### Components

| File | Purpose |
|------|---------|
| `news_pipeline.py` | Main orchestration |
| `rss_fetcher.py` | RSS feed fetching |
| `dedup_filter.py` | Content hash dedup |
| `source_registry.py` | Category → sources mapping |
| `news_models.py` | NewsItem, NewsDigest models |

### Scheduler Integration

- `news-fetch` — runs 3×/day, fetches from all sources
- `news-distill-nlm` — runs 1 hour after fetch, distills via NLM

---

## Google Account Manager

`engine/nexus/google_account_manager.py` — multi-account cookie pool for
authenticated access to Google services.

### Services Supported

| Service | Auth Method | Cookie Keys |
|---------|------------|-------------|
| NotebookLM | batchexecute + cookies | SAPISID, SID, NID, HSID |
| AI Studio | gRPC-Web + cookies | Same |
| Colab | gRPC + cookies | Same |

### Features

- **Round-robin rotation** — auto-selects next available account
- **Rate-limit backoff** — skips rate-limited accounts
- **HAR import** — extract cookies from browser HAR files
- **Cookie health** — `cookie_age_days()`, `is_stale()`
- **Service sessions** — per-service session metadata (bl, f_sid, at tokens)

### Usage

```python
from engine.nexus.google_account_manager import GoogleAccountManager

mgr = GoogleAccountManager()
account = mgr.get_account(service="notebooklm")
mgr.mark_rate_limited("account-1", "notebooklm", backoff_minutes=30)
```

---

## Skills Reference

### Nexus Skills (17 skills, pack="nexus")

| Skill | Description |
|-------|-------------|
| `nexus_search` | Search the Nexus knowledge base |
| `nexus_add` | Add a knowledge entry |
| `nexus_ask` | Smart Q&A — cache → knowledge → NLM research |
| `nexus_nlm_ask` | Query NotebookLM via best backend |
| `nexus_status` | Check Nexus and NLM backend status |
| `nexus_log_session` | Log a session to Nexus |
| `nexus_store_prompt` | Store a versioned prompt |
| `nexus_search_prompts` | Search stored prompts |
| `nexus_get_rules` | Get active governance rules |
| `nexus_submit_idea` | Submit an improvement idea |
| `nexus_changelog` | Query change history |
| `nexus_research` | Start deep research via NLM |
| `nexus_converse` | Continue a research conversation |
| `nexus_finish_research` | Complete and distill research |
| `nexus_youtube` | Import YouTube transcript |
| `nexus_smart_query` | Smart query with 5-tier routing |
| `nexus_router_stats` | Get router effectiveness stats |

### Coding Skills (9 skills, pack="coding")

| Skill | Description |
|-------|-------------|
| `coding_store_snippet` | Store reusable code snippet |
| `coding_search` | Search code patterns and dev knowledge |
| `coding_store_decision` | Store architecture/design decision |
| `coding_log_session` | Log development session |
| `coding_research` | Research API/library/tech topic |
| `coding_store_bug` | Store bug analysis or debugging note |
| `coding_store_test_pattern` | Store test strategy or pattern |
| `coding_project_status` | Get project status from Nexus |
| `coding_search_qa` | Search Q&A pairs for dev answers |

### Autonomy Skills (67 skills, pack="autonomy")

| Category | Count | Key Skills |
|----------|-------|------------|
| Scheduler | 3 | `scheduler_status`, `scheduler_run_now`, `scheduler_list_tasks` |
| News | 4 | `news_fetch`, `news_fetch_and_store`, `news_digest`, `news_list_sources` |
| NLM Notebooks | 5 | `nlm_notebook_list`, `nlm_notebook_seed_docs`, `nlm_notebook_rotate` |
| Nexus Quality | 3 | `nexus_quality_report`, `nexus_full_maintenance`, `nexus_backup` |
| Governance | 6 | `governance_validate_file`, `governance_enforce`, `governance_stats` |
| Task Management | 4 | `tasks_from_test_failures`, `task_from_template`, `task_list_templates` |
| Test Diagnostics | 2 | `diagnose_failures`, `diagnose_test_file` |
| Training | 7 | `training_collect_task`, `training_export_jsonl`, `training_sync_nexus` |
| Metrics | 10 | `metrics_record`, `metrics_trend`, `metrics_dashboard`, `reflection_run` |
| Copilot | 1 | `copilot_validate_runtime` |
| Smart Query | 2 | `nexus_smart_query`, `nexus_router_stats` |
| Other | 20 | Various system, health, knowledge, and research skills |

---

## Module Inventory

85 Python files in `engine/nexus/`:

| Category | Files | Key Modules |
|----------|-------|-------------|
| Core Client | 5 | `client.py`, `models.py`, `rules_client.py`, `session_client.py`, `memory_client.py` |
| Query Routing | 3 | `query_router.py`, `cache_pipeline.py`, `source_pyramid.py` |
| Copilot Integration | 7 | `copilot_bridge.py`, `copilot_self_config.py`, `copilot_validation.py`, `copilot_context.py`, `copilot_helpers.py`, `copilot_hook_control.py`, `seed_copilot_rules.py` |
| Session Management | 4 | `nexus_session_logger.py`, `session_distillation.py`, `sync_sessions_to_nexus.py`, `session_client.py` |
| Knowledge | 8 | `knowledge_capture.py`, `knowledge_forge.py`, `knowledge_graph.py`, `knowledge_evaluator.py`, `nexus_distiller.py`, `nexus_memory.py`, `nexus_namespaces.py`, `nexus_seeder.py` |
| Training | 5 | `training_flywheel.py`, `training_pipeline.py`, `teacher_pipeline.py`, `dataset_curator.py`, `router_finetune_cycle.py` |
| Q&A Generation | 2 | `qa_expander.py`, `qa_generator.py` |
| NotebookLM | 12 | `bootstrap_notebooks.py`, `nlm_chain.py`, `notebooklm_flywheel.py`, `nlm_engine.py`, `nlm_automation.py`, `nlm_router.py`, `nlm_deep_storage.py`, `nlm_qa_distiller.py`, `nlm_notebook_manager.py`, `nlm_rpc_mapper.py`, `nlm_cookie_refresh.py`, `nlm_har_capture.py` |
| Scheduling | 3 | `scheduler_daemon.py`, `task_scheduler.py`, `action_manifest.py` |
| News | 6 | `news/` directory: `news_pipeline.py`, `rss_fetcher.py`, `dedup_filter.py`, `source_registry.py`, `news_models.py`, `news_feed_api.py` |
| Google Auth | 2 | `google_account_manager.py`, `har_extractor.py` |
| Integrations | 4 | `aistudio_client.py`, `canvas_api.py`, `lms_task_bridge.py`, `local_agent_bridge.py` |
| Governance | 2 | `governance_rules.py`, `seed_nexus.py` |
| Operator | 2 | `operator_inbox.py`, `consumer_briefing.py` |
| Metrics | 3 | `meta_metrics.py`, `experiment_framework.py`, `experiment_proposals.py` |
| System | 6 | `self_maintenance.py`, `system_reflection.py`, `auto_diagnosis.py`, `backup_manager.py`, `history_miner.py`, `conversation_analyzer.py` |
| Content | 4 | `daily_challenge.py`, `url_ingest.py`, `url_manager.py`, `vscode_history_extractor.py` |
| CLI | 3 | `bridge.py`, `cli.py`, `nlm_cli.py` |
| Misc | 4 | `workflows.py`, `control_panel.py`, `user_profile.py`, `space_exporter.py`, `agent_tags.py`, `review_sheet.py` |

---

## Configuration

All Nexus-related config lives in `config/default.yaml`:

```yaml
nexus:
  host: localhost
  port: 8700
  timeout: 30
  max_retries: 3
  retry_delay: 0.5

  operator_inbox:
    enabled: true
    state_file: data/operator_inbox_state.json
    auto_promote: true

  scheduler:
    interval_seconds: 60
    state_file: data/scheduler_state.json
    enabled: true

  query_router:
    min_confidence: 0.3
    use_llm: false
    local_cache_ttl: 300

notebooklm:
  flywheel:
    interval_hours: 24
    max_tasks_per_run: 10
    distillation_category: control-plane-report
    control_questions:
      - "Summarize the current system state"
      - "What gaps need attention?"
      - "What actions should continue?"
```

---

## Testing

```powershell
# Core Nexus tests
python -m pytest tests/test_query_router.py tests/test_training_flywheel.py -v

# Copilot integration
python -m pytest tests/test_copilot_bridge.py tests/test_copilot_validation.py -v

# Scheduler and tasks
python -m pytest tests/test_scheduler_daemon.py tests/test_task_scheduler.py -v

# Full Nexus-related suite
python -m pytest tests/test_query_router.py tests/test_copilot_bridge.py tests/test_copilot_validation.py tests/test_copilot_self_config.py tests/test_seed_copilot_rules.py tests/test_bootstrap_notebooks.py tests/test_scheduler_daemon.py tests/test_training_flywheel.py tests/test_operator_inbox.py tests/test_knowledge_capture.py tests/test_action_manifest.py tests/test_qa_expander.py tests/test_qa_generator.py -v
```

---

## See Also

- [Architecture](ARCHITECTURE.md) — Full engine subsystem overview
- [MCP Framework](MCP_FRAMEWORK.md) — Skill decorator and interceptor patterns
- [Scenes](SCENES.md) — Scene-level Nexus integration via NexusSceneMixin
- [Configuration](CONFIGURATION.md) — `config/default.yaml` Nexus settings
- [Agent Onboarding](AGENT_ONBOARDING.md) — How agents consume Nexus context
