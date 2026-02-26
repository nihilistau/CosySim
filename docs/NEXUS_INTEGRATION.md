# Nexus Integration Guide — v0.51b

Nexus is CosySim's central knowledge management system. It provides persistent
storage, full-text search, namespace-separated knowledge, rules enforcement,
session tracking, prompt versioning, memory systems, training data capture,
knowledge distillation, and a control panel — accessible from agents, scenes,
skills, Copilot CLI, and external tools.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Copilot CLI (GitHub Copilot Agent)                     │
│  ├── Session hooks     → auto-log sessions              │
│  ├── CLI bridge        → search/ask/store from terminal  │
│  ├── Distillers        → extract reusable knowledge      │
│  └── Memory loop       → persist context across sessions │
├─────────────────────────────────────────────────────────┤
│  CosySim Engine (Agents, Scenes, Skills)                │
│  ├── engine/nexus/client.py        NexusClient HTTP     │
│  ├── engine/nexus/nexus_memory.py  NexusMemory system   │
│  ├── engine/nexus/nexus_namespaces.py  Namespace rules  │
│  ├── engine/nexus/nexus_distiller.py   4 distillers     │
│  ├── engine/nexus/training_pipeline.py  Training data   │
│  ├── engine/nexus/workflows.py     Content/Research     │
│  ├── engine/nexus/control_panel.py Streamlit dashboard  │
│  ├── engine/skills/builtin/nexus_skills.py   16 skills  │
│  ├── engine/skills/builtin/coding_skills.py  8 skills   │
│  └── engine/agents/interceptors.py  NexusPromptIntcptr  │
├─────────────────────────────────────────────────────────┤
│              HTTP REST API (port 8700)                   │
├─────────────────────────────────────────────────────────┤
│  Nexus Server (C:\Files\Nexus)                          │
│  ├── nexus/db/store.py      NexusStore (SQLite + FTS5)  │
│  ├── nexus/api/routes.py    Flask routes (~640)          │
│  ├── nexus/nlm/             NotebookLM backends          │
│  └── nexus/db/schema.py     v2 schema (14 tables)       │
├─────────────────────────────────────────────────────────┤
│  Dashboard / Control Panel                               │
│  ├── port 8701  Nexus Dashboard (Flask)                  │
│  └── port 8702  Control Panel (Streamlit, 8 pages)       │
└─────────────────────────────────────────────────────────┘
```

## Namespaces

All knowledge entries are namespace-tagged to enforce separation between
systems. Seven namespaces exist, each with allowed content types, categories,
and access control rules.

| Namespace | Purpose | Allowed Types | Example Tags |
|-----------|---------|---------------|--------------|
| `system` | Core framework docs, architecture, API | note, code, prompt, document | `system`, `architecture` |
| `scene` | Per-scene knowledge, configs, templates | note, prompt, code | `scene:bedroom`, `scene:realm` |
| `agent` | Character profiles, personality, behavior | note, prompt, memory | `agent`, `agent:lola` |
| `copilot` | Session logs, decisions, conventions | history, note, document | `copilot`, `session` |
| `training` | Fine-tuning data, datasets, experiments | code, note, document | `training`, `finetune` |
| `research` | Research sessions, NLM outputs, findings | document, note | `research`, `nlm` |
| `content` | Greetings, reactions, scene descriptions | note, code | `content`, `greetings` |

### Namespace Enforcement

`engine/nexus/nexus_namespaces.py` provides:
- `detect_namespace(category, tags)` — auto-detect namespace from entry metadata
- `validate_entry(entry)` — check entry matches namespace rules
- `enforce_namespace(entry)` — auto-tag and validate before storing
- `can_access(agent_id, namespace)` — check access permissions

22 enforcement rules are installed in Nexus governing cross-namespace access.

## NexusClient

Located at `engine/nexus/client.py`. Singleton via `get_nexus_client()`.

```python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()

# Knowledge CRUD
results = client.search("combat mechanics", limit=10)
entry_id = client.add_entry("Title", "Content", content_type="note")
client.update_entry(entry_id, content="Updated")
client.delete_entry(entry_id)

# Q&A Pipeline (cache → FTS5 → NLM)
answer = client.ask("How does the interceptor pipeline work?")
qa_id = client.add_qa("What is Nexus?", "Central knowledge management system.")
results = client.find_qa("rules engine", limit=5)

# Rules Engine
rules = client.get_rules(scope="scene:tavern", rule_type="validation")
rule_id = client.add_rule("global", "quality_gate", "min_length",
                          condition={"min_words": 10}, action={"reject": True})

# Prompt Versioning
pid = client.store_prompt("tavern_host", "You are a gruff bartender...",
                          category="scene", version="2")
prompts = client.get_prompts(category="scene", name="tavern")

# Sessions
sid = client.log_session(project="CosySim", repo="CosySim", branch="master")
client.update_session(sid, summary="Fixed bugs", commits=["abc123"])

# Research (multi-turn with NLM)
session = client.research("combat mechanics deep dive")
reply = client.converse(session["id"], "What about critical hits?")
summary = client.finish_research(session["id"])

# YouTube Import
entry_id = client.import_youtube("https://youtube.com/watch?v=...", tags=["tutorial"])

# Batch Operations
ids = client.batch_add([
    {"title": "A", "content": "...", "content_type": "note"},
    {"title": "B", "content": "...", "content_type": "note"},
])
```

### Retry & Resilience

The client retries failed requests up to `max_retries` times with exponential
backoff (0.5s × attempt). If Nexus is unavailable, methods return graceful
defaults (`None`, `[]`, `False`).

## MCP Skills

### Nexus Pack (16 skills)

| Skill | Description |
|-------|-------------|
| `nexus_search` | Full-text search across all entries |
| `nexus_add` | Store a knowledge entry |
| `nexus_ask` | Smart Q&A (cache → FTS5 → NLM pipeline) |
| `nexus_nlm_ask` | Query NotebookLM backends directly |
| `nexus_status` | Database stats + backend health |
| `nexus_log_session` | Create/update session records |
| `nexus_store_prompt` | Store prompt with version tag |
| `nexus_search_prompts` | Find prompts by name/category |
| `nexus_get_rules` | Get active rules for a scope |
| `nexus_submit_idea` | Submit improvement ideas |
| `nexus_changelog` | Query change history |
| `nexus_research` | Start a multi-turn research session |
| `nexus_converse` | Continue a research conversation |
| `nexus_finish_research` | Close research session, return summary |
| `nexus_youtube` | Import YouTube transcript into knowledge base |

### Coding Pack (8 skills)

| Skill | Description |
|-------|-------------|
| `coding_store_snippet` | Store reusable code snippets |
| `coding_store_decision` | Record architecture decisions |
| `coding_research` | Research APIs and libraries |
| `coding_store_bug` | Record bug analysis and fix |
| `coding_log_session` | Track development sessions |

### MCP Server Tools (in cosysim_server.py)

| Tool | Description |
|------|-------------|
| `nexus_remember` | Store a memory for a character or Copilot |
| `nexus_recall` | Retrieve relevant memories by query |
| `nexus_memory_context` | Get formatted context window for prompt injection |
| `capture_training_data` | Capture an interaction for fine-tuning datasets |
| `generate_content` | Generate greetings/reactions for characters |
| `seed_nexus` | Run the knowledge seeder (docs/rules/prompts/qa/all) |
| `nexus_maintain` | Run maintenance (health/dedup/cleanup/reindex) |
| `nexus_distill` | Run distillers (stats/distill/compact/primer/dedup/skills/prompts/lineage/all) |
| `nexus_export_session` | Export current Copilot session to Nexus |

## Memory System

`engine/nexus/nexus_memory.py` provides a unified memory layer for both
Copilot sessions and CosySim characters. Memories are stored as Nexus entries
with namespace separation and importance scoring.

```python
from engine.nexus.nexus_memory import get_copilot_memory, get_character_memory

# Copilot memory
mem = get_copilot_memory()
mem.remember("Project uses FTS5 for search", importance=0.8)
relevant = mem.recall("search implementation", top_k=5)
context = mem.get_context_window(max_chars=2000)

# Character memory
lola_mem = get_character_memory("lola")
lola_mem.remember("User prefers casual conversation", importance=0.7)
```

### Memory Types

| Type | Default Importance | Use For |
|------|--------------------|---------|
| `observation` | 0.5 | What happened |
| `preference` | 0.7 | What user/character likes |
| `fact` | 0.8 | Established facts |
| `emotion` | 0.6 | Emotional states observed |
| `decision` | 0.9 | Decisions made |
| `summary` | 0.7 | Compacted summaries |
| `interaction` | 0.3 | Routine interactions |

### Memory Operations

- `remember(content, importance, memory_type)` — Store with auto-namespace
- `recall(query, top_k)` — Search by relevance
- `get_context_window(max_chars)` — Format for prompt injection
- `compact(max_memories)` — Merge old memories into summaries
- `forget()` — Clear all memories for this agent

## Knowledge Distillers

`engine/nexus/nexus_distiller.py` provides 4 distillers that process raw
session data into reusable knowledge, keeping the knowledge base lean.

### NexusDistiller (Session Distiller)

Extracts decisions, bug fixes, and file conventions from conversation logs.

```python
from engine.nexus.nexus_distiller import NexusDistiller
d = NexusDistiller()
d.distill()             # Extract from conversation logs
d.compact_sessions()    # Merge daily session entries
d.get_stats()           # Knowledge base statistics
d.generate_context_primer()  # Compact context for new sessions
```

### QADeduplicator

Finds and merges near-duplicate Q&A pairs using word-level Jaccard similarity.

```python
from engine.nexus.nexus_distiller import QADeduplicator
dedup = QADeduplicator(similarity_threshold=0.75)
dedup.deduplicate(dry_run=True)   # Preview duplicates
dedup.deduplicate(dry_run=False)  # Remove duplicates (keeps longer answer)
```

### SkillUsageDistiller

Analyses session logs for MCP skill/tool usage patterns: frequency, errors,
underutilisation.

```python
from engine.nexus.nexus_distiller import SkillUsageDistiller
su = SkillUsageDistiller()
su.analyse()             # Get usage statistics
su.distill_and_store()   # Analyse and store findings in Nexus
```

### PromptEvolutionDistiller

Tracks prompt versions over time, analyses structural patterns (role defs,
constraints, guardrails, output formats), and stores best-practice findings.

```python
from engine.nexus.nexus_distiller import PromptEvolutionDistiller
pe = PromptEvolutionDistiller()
pe.get_lineage()         # Prompt version history
pe.distill_patterns()    # Analyse and store prompt patterns
```

### Running All Distillers

```bash
python -m engine.nexus.nexus_distiller all     # Run all distillers
python -m engine.nexus.nexus_distiller stats    # Knowledge base stats
python -m engine.nexus.nexus_distiller dedup    # Deduplicate Q&A
python -m engine.nexus.nexus_distiller skills   # Skill usage analysis
python -m engine.nexus.nexus_distiller prompts  # Prompt pattern analysis
python -m engine.nexus.nexus_distiller lineage  # Prompt version history
```

Or via MCP tool: `nexus_distill(action="all")`

## Training Pipeline

`engine/nexus/training_pipeline.py` captures agent interactions for
fine-tuning datasets. Interactions are stored in Nexus and exported as JSONL.

```python
from engine.nexus.training_pipeline import get_training_pipeline
tp = get_training_pipeline()

# Capture an interaction
tp.capture_interaction(
    user_message="Hello",
    agent_response="Hi there!",
    context={"scene": "bedroom"},
    quality_score=0.9,
)

# Export dataset
tp.export_dataset(dataset_type="chat", output_dir="training/data")

# Generate synthetic training data
synthetic = tp.generate_synthetic(dataset_type="chat", count=50)
```

## Content & Research Workflows

`engine/nexus/workflows.py` provides 3 workflow classes.

### ContentWorkflow

Generates pre-baked content (greetings, reactions, scene descriptions) to reduce
runtime LLM calls.

```python
from engine.nexus.workflows import ContentWorkflow
cw = ContentWorkflow()
cw.generate_greetings("lola", personality_tags=["flirty", "warm"])
cw.generate_reactions("lola")
cw.generate_scene_descriptions("bedroom")
content = cw.lookup_content("lola", "greetings", mood="happy")
```

### ResearchWorkflow

Wraps the Nexus Q&A → FTS5 → NLM pipeline for structured research.

```python
from engine.nexus.workflows import ResearchWorkflow
rw = ResearchWorkflow()
result = rw.research("How should we handle agent memory persistence?", depth="deep")
rw.store_findings(result)
```

### NotebookWorkflow

Seeds NotebookLM notebooks with project knowledge and generates Q&A pairs.

```python
from engine.nexus.workflows import NotebookWorkflow
nw = NotebookWorkflow()
nw.seed_notebook_knowledge(scope="architecture")
nw.check_nlm_status()
```

## Knowledge Seeder

`engine/nexus/nexus_seeder.py` performs idempotent knowledge seeding from
project documentation. Run manually or via MCP tool.

```bash
python -m engine.nexus.nexus_seeder all       # Seed everything
python -m engine.nexus.nexus_seeder docs       # Documentation only
python -m engine.nexus.nexus_seeder rules      # Governance rules only
python -m engine.nexus.nexus_seeder qa         # Q&A pairs only
python -m engine.nexus.nexus_seeder prompts    # Agent prompts only
```

Or via MCP tool: `seed_nexus(source="all")`

## Nexus CLI Bridge

`engine/nexus/bridge.py` provides standalone Nexus access from the terminal
without requiring the MCP server.

```bash
python -m engine.nexus.bridge search "interceptor pipeline"
python -m engine.nexus.bridge ask "How does state management work?"
python -m engine.nexus.bridge store "Decision" "Use FTS5 for search"
python -m engine.nexus.bridge qa "What is X?" "X is..."
python -m engine.nexus.bridge rules global
python -m engine.nexus.bridge health
python -m engine.nexus.bridge seed all
python -m engine.nexus.bridge maintain health
```

## NexusPromptInterceptor

`engine/agents/interceptors.py` includes a `NexusPromptInterceptor` (priority 4)
that enriches agent prompts with Nexus knowledge at runtime:

- Fetches governance rules for the current scope
- Injects relevant knowledge from Nexus search
- Loads stored character/scene prompts
- TTL-cached (5 min) to avoid hammering the API

Registered in `config/default.yaml` under `comms.interceptors`.

## Control Panel

`engine/nexus/control_panel.py` is a Streamlit dashboard on port 8702 with
8 pages: Knowledge Browser, Q&A Manager, Rules Editor, Session Viewer,
Memory Explorer, Training Data, Distiller Dashboard, System Health.

```bash
streamlit run engine/nexus/control_panel.py --server.port 8702
```

## Rules Engine

Rules are scope-based governance policies. Each rule has:
- **scope**: `global`, `collection:{type}`, `agent:{id}`, `scene:{id}`
- **rule_type**: `validation`, `access`, `auto_action`, `quality_gate`
- **condition**: JSON expression evaluated against context
- **action**: JSON action to take when condition matches
- **priority**: 0–100 (higher = evaluated first)

```python
client.add_rule(
    scope="scene:tavern",
    rule_type="quality_gate",
    name="min_response_length",
    condition={"min_words": 15},
    action={"reject_if_below": True, "fallback": "Please elaborate."},
    priority=80
)
```

## Session Tracking

The session logger (`engine/nexus/nexus_session_logger.py`) automatically
captures Copilot CLI session lifecycle events via `.github/hooks/`:

- **Session start**: Records git context, CWD, branch
- **Session end**: Exports full conversation history, checkpoints, plans,
  extracts key decisions as Q&A
- **Prompt count**: Tracks number of prompts per session

See [Copilot System](COPILOT_SYSTEM.md) for full details.

## API Routes

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/search?q=...` | Full-text search |
| GET/POST | `/api/entries` | List/create entries |
| GET/PUT/DELETE | `/api/entries/<id>` | Entry CRUD |
| GET | `/api/entries/by-type/<type>` | Type-filtered listing |
| GET/POST | `/api/rules` | List/create rules |
| PUT/DELETE | `/api/rules/<id>` | Rule CRUD |
| GET/POST | `/api/sessions` | List/create sessions |
| GET/PUT | `/api/sessions/<id>` | Session CRUD |
| GET/POST | `/api/qa` | List/create Q&A pairs |
| DELETE | `/api/qa/<id>` | Delete Q&A pair |
| POST | `/api/batch` | Bulk entry creation |
| GET | `/api/stats` | Database statistics |
| GET | `/api/health` | Health check |

## Configuration

```yaml
# config/default.yaml
nexus:
  url: http://localhost:8700
  enabled: true
  auto_submit: false
  submit_threshold: 0.7
```

## Content Types

| Type | Purpose |
|------|---------|
| `note` | General knowledge, observations |
| `code` | Code snippets, patterns, templates |
| `prompt` | System/agent prompts (versioned) |
| `document` | Design docs, specs, guides |
| `history` | Session logs, conversation records |
| `transcript` | YouTube/video transcripts |
| `research` | Research session artifacts |
| `memory` | Agent/Copilot memories |
