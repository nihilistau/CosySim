# Nexus Integration Guide — v0.50b

Nexus is CosySim's central knowledge management system. It provides persistent storage, full-text search, rules enforcement, session tracking, and prompt versioning — accessible from agents, scenes, skills, and external tools.

## Architecture

```
┌──────────────────────────────────────────────────┐
│  CosySim (Agents, Scenes, Skills)                │
│  ├── engine/nexus/client.py   NexusClient HTTP   │
│  ├── engine/skills/builtin/nexus_skills.py  16   │
│  └── engine/agents/interceptors.py  (activity)   │
├──────────────────────────────────────────────────┤
│              HTTP REST API (port 8700)            │
├──────────────────────────────────────────────────┤
│  Nexus Server (C:\Files\Nexus)                   │
│  ├── nexus/db/store.py      NexusStore (SQLite)  │
│  ├── nexus/api/routes.py    Flask routes (~640)   │
│  ├── nexus/nlm/             NotebookLM backends  │
│  └── nexus/db/schema.py     v2 schema            │
├──────────────────────────────────────────────────┤
│  SQLite + FTS5                                    │
│  ├── knowledge_entries      (content + search)   │
│  ├── rules                  (scope-based rules)  │
│  ├── sessions               (activity tracking)  │
│  └── 11 more tables         (tags, refs, NLM)    │
└──────────────────────────────────────────────────┘
```

## Content Types

| Type | Purpose | Category Examples |
|------|---------|-------------------|
| `note` | General knowledge | system, scene, agent |
| `prompt` | System/agent prompts | system, scene, character |
| `session` | Work session records | copilot, agent, experiment |
| `experiment` | A/B tests, benchmarks | improvement, training |
| `changelog` | Version change logs | system |
| `rule` | Governance rules | global, scene, agent |
| `scene_template` | Scene definitions | game, utility |
| `agent_profile` | Agent configs | character, npc |
| `skill_definition` | Skill metadata | builtin, scene |
| `benchmark` | Performance data | latency, quality |

## NexusClient

Located at `engine/nexus/client.py`. Singleton via `get_nexus_client()`.

### Key Methods

```python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()

# Knowledge CRUD
results = client.search("combat mechanics", limit=10)
entry_id = client.add_entry("Title", "Content", content_type="note")
client.update_entry(entry_id, content="Updated")
client.delete_entry(entry_id)

# Sessions
sid = client.log_session(project="CosySim", repo="CosySim", branch="master")
client.update_session(sid, summary="Fixed bugs", commits=["abc123"])
sessions = client.list_sessions(project="CosySim", status="active")

# Rules
rules = client.get_rules(scope="scene:tavern", rule_type="validation")
rule_id = client.add_rule("global", "quality_gate", "min_length",
                          condition={"min_words": 10}, action={"reject": True})

# Prompts
pid = client.store_prompt("tavern_host", "You are a gruff bartender...",
                          category="scene", version="2")
prompts = client.get_prompts(category="scene", name="tavern")

# Batch
ids = client.batch_add([
    {"title": "A", "content": "...", "content_type": "note"},
    {"title": "B", "content": "...", "content_type": "note"},
])

# Changelog
client.store_changelog("v0.50a", "Nexus integration overhaul", commits=["abc123"])

# Q&A
results = client.find_qa("How does combat work?", limit=5)
qa_id = client.add_qa("What is Nexus?", "Central knowledge management system.")
answer = client.ask("Explain the rules engine")

# Research
session = client.research("combat mechanics analysis")
reply = client.converse(session["id"], "What about critical hits?")
summary = client.finish_research(session["id"])
sessions = client.list_research(status="active")

# YouTube
entry_id = client.import_youtube("https://youtube.com/watch?v=...", tags=["tutorial"])

# Plugins
plugins = client.list_plugins()
client.add_plugin("my_hook", hook="post_ingest", script="plugins/my_hook.py")
```

### Retry & Resilience

The client retries failed requests up to `max_retries` times with exponential backoff (0.5s × attempt). If Nexus is unavailable, methods return graceful defaults (`None`, `[]`, `False`).

## MCP Skills (16)

| Skill | Description |
|-------|-------------|
| `nexus_search` | Full-text search across all entries |
| `nexus_add` | Store a knowledge entry |
| `nexus_nlm_ask` | Query NotebookLM backends |
| `nexus_status` | Database stats + backend health |
| `nexus_log_session` | Create/update session records |
| `nexus_store_prompt` | Store prompt with version tag |
| `nexus_search_prompts` | Find prompts by name/category |
| `nexus_get_rules` | Get active rules for a scope |
| `nexus_submit_idea` | Submit improvement ideas |
| `nexus_changelog` | Query change history |
| `nexus_ask` | Ask a question against the Q&A cache and NLM pipeline |
| `nexus_research` | Start a multi-turn research session |
| `nexus_converse` | Continue a research conversation with follow-up questions |
| `nexus_finish_research` | Close a research session and return a summary |
| `nexus_youtube` | Import a YouTube video transcript into the knowledge base |

All skills are in the `nexus` pack and available to any agent via `mcp_skill_pack("nexus")`.

## Rules Engine

Rules are scope-based governance policies stored in Nexus. Each rule has:
- **scope**: `global`, `collection:{type}`, `agent:{id}`, `scene:{id}`
- **rule_type**: `validation`, `access`, `auto_action`, `quality_gate`
- **condition**: JSON expression evaluated against context
- **action**: JSON action to take when condition matches
- **priority**: 0–100 (higher = evaluated first)

Example: Require minimum response length for scene agents:
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

Every agent session, experiment run, or coding session can be logged:

```python
# Start session
sid = client.log_session(project="CosySim", repo="CosySim", branch="master")

# Update as work progresses
client.update_session(sid,
    summary="Upgraded Nexus skills",
    commits=["abc123", "def456"],
    files_changed=["engine/nexus/client.py", "engine/skills/builtin/nexus_skills.py"],
    skills_used=["nexus_add", "nexus_search"],
    status="completed"
)
```

## Integration Patterns

### Scene → Nexus
Scenes can query Nexus for rules, prompts, and context during initialization:
```python
class MyScene(BaseScene):
    def setup_mcp(self):
        rules = get_nexus_client().get_rules(scope=f"scene:{self.name}")
        prompts = get_nexus_client().get_prompts(category="scene", name=self.name)
```

### Agent → Nexus (via Skills)
Agents call Nexus skills during inference to search knowledge, log activities, or check rules. The MCP framework exposes these as tool calls.

### Interceptor → Nexus
The interceptor pipeline can auto-log agent activity to Nexus post-inference, tracking conversation quality and skill usage patterns.

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
| POST | `/api/batch` | Bulk entry creation |
| POST | `/api/agent/submit` | Agent knowledge submission |
| GET | `/api/stats` | Database statistics |
| GET | `/api/health` | Health check |

## Q&A Distillation Cache

The Q&A cache stores distilled question-answer pairs extracted from knowledge entries and research sessions. When a question is asked via `nexus_ask`, the pipeline checks the Q&A cache first for an instant hit before falling back to FTS5 search and NLM backends.

```python
# Add a Q&A pair directly
client.add_qa("What is the rules engine?", "Scope-based governance policies with condition/action JSON.")

# Search the cache
results = client.find_qa("rules engine", limit=5)

# Ask — checks Q&A cache → FTS5 → NLM pipeline
answer = client.ask("How do rules work?")
```

## Research Manager

The Research Manager supports multi-turn investigative sessions. A research session opens a conversational context backed by the Q&A cache → FTS5 → NLM pipeline, allowing iterative exploration of a topic.

```python
# Start a research session
session = client.research("combat mechanics deep dive")

# Ask follow-up questions within the session
reply = client.converse(session["id"], "How do critical hits work?")
reply = client.converse(session["id"], "What about armor penetration?")

# List active sessions
active = client.list_research(status="active")

# Close session and get a summary
summary = client.finish_research(session["id"])
```

The Research Manager pipeline: **Q&A cache** (instant) → **FTS5 full-text search** (fast) → **NLM backends** (deep). Each step only runs if the previous step didn't produce a confident answer.

## YouTube Transcript Import

Nexus can ingest YouTube video transcripts as knowledge entries. The `import_youtube` method downloads the transcript, chunks it into manageable segments, and stores each chunk as a searchable knowledge entry.

```python
entry_id = client.import_youtube(
    "https://youtube.com/watch?v=abc123",
    tags=["tutorial", "combat"],
    content_type="note",
    category="reference"
)
```

The corresponding `nexus_youtube` skill exposes this to agents during inference.

## Plugin System

The plugin system provides lifecycle hooks for extending Nexus ingestion and query pipelines. Plugins are Python scripts registered with a specific hook point.

Available hooks:
- `post_ingest` — Runs after a knowledge entry is stored
- `pre_query` — Modifies or enriches queries before search
- `post_query` — Post-processes search results before returning
- `on_research_close` — Triggered when a research session finishes

```python
# Register a plugin
client.add_plugin("my_enricher", hook="post_ingest", script="plugins/enrich.py")

# List registered plugins
plugins = client.list_plugins()
```

## Configuration

In `config/default.yaml`:
```yaml
nexus:
  url: http://localhost:8700
  enabled: true
  auto_submit: false        # Auto-log agent activity
  submit_threshold: 0.7     # Quality gate for auto-submission
```
