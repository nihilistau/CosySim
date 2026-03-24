# Nexus — Knowledge Pipeline

> CosySim Documentation — v1.50.2 [2026-03-24]
>
> Nexus KMS, NotebookLM integration, query routing, and the training flywheel.

---

## 1. Overview

Nexus is CosySim's central knowledge management system — a persistent SQLite + FTS5
backbone that stores entries, rules, Q&A pairs, session history, prompts, benchmarks,
and training data. Every agent, scene, skill, and development session consumes and
contributes to Nexus. The system is designed to compound: every interaction makes
future interactions cheaper and more accurate.

Nexus runs as a managed service on port `8700`. It auto-starts via `--core` / `--all` /
TUI autostart (priority 0 — launches first). Manual start:

```bash
cd C:\Files\Nexus && python -m nexus api
```

The knowledge pipeline connects three tiers of intelligence:

| Tier | System | Role |
|------|--------|------|
| **Nexus KMS** | SQLite + FTS5 on `:8700` | Persistent knowledge, rules, Q&A, sessions |
| **NotebookLM** | Google Gemini via NLM Proxy on `:8800` | Free Gemini inference, research distillation |
| **LMStudio** | Local LLM on `:1234` | Last-resort fallback for novel queries |

Together these form a self-improving loop: the first time a question is asked it costs
compute; every subsequent time it is served from Nexus cache for free.

### Database Layers

| Layer | Table | Purpose |
|-------|-------|---------|
| Knowledge | `entries` | Notes, code, docs, prompts, transcripts, memories, plans |
| Rules | `rules` | Governance rules with scope, conditions, actions |
| Q&A Cache | `qa_pairs` | Direct question-to-answer lookup (fastest tier) |

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

### Nexus-First Workflow

Every agent and session follows this discipline:

1. **Before work** — `nexus_smart_query(question)` or `nexus_search(topic)` to check
   for existing knowledge, decisions, and patterns.
2. **Check rules** — `nexus_get_rules(scope)` for governance constraints.
3. **During work** — store architecture decisions, code snippets, and reusable patterns
   as they are discovered.
4. **After work** — persist session outcomes: Q&A pairs, changelog notes, histories,
   improvements, and learnings.
5. **Backfill misses** — if knowledge is found outside Nexus, write it back as both a
   knowledge entry and a Q&A pair.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Copilot CLI / Claude Code / GitHub Copilot                  │
│  ├── CopilotBridge       session start/end, pre-plan, metrics│
│  ├── CopilotSelfConfig   bidirectional config sync (v1.50.2) │
│  ├── CopilotValidation   drift detection, hook integrity     │
│  ├── SeedCopilotRules    mirror repo assets into Nexus       │
│  └── SessionLogger       checkpoint/compact/end export       │
├──────────────────────────────────────────────────────────────┤
│  CosySim Engine (Agents, Scenes, Skills)                     │
│  ├── NexusClient          HTTP client for Nexus API          │
│  ├── NexusQueryRouter     6-tier smart routing (v1.50.2)     │
│  ├── EmbeddingService     Gemini Embedding 2 + LMStudio      │
│  ├── NexusVectorStore     ChromaDB semantic search            │
│  ├── TrainingFlywheel     auto-collect training data         │
│  ├── TaskScheduler        agent task ticketing + auto-assign │
│  ├── SchedulerDaemon      84 recurring tasks (cron-like)     │
│  ├── OperatorInbox        off-turn directive intake          │
│  ├── KnowledgeCapture     dual-write backfill helper         │
│  ├── NLMChain             multi-step chain-prompting         │
│  ├── NotebookLMFlywheel   control notebook → tasks → train   │
│  └── 103 total modules in engine/nexus/                      │
├──────────────────────────────────────────────────────────────┤
│  Skills Layer (93 Nexus-aware skills)                        │
│  ├── nexus_skills.py      17 skills (search, ask, store, NLM)│
│  ├── coding_skills.py      9 skills (snippets, decisions)    │
│  └── autonomy_skills.py   67 skills (scheduler, training)    │
├──────────────────────────────────────────────────────────────┤
│              Nexus HTTP REST API (port 8700)                  │
├──────────────────────────────────────────────────────────────┤
│  Nexus Server (C:\Files\Nexus)                               │
│  ├── SQLite + FTS5         Full-text search engine            │
│  ├── Flask REST API        CRUD + search + rules + sessions   │
│  └── 3-layer DB            entries, rules, Q&A cache          │
└──────────────────────────────────────────────────────────────┘
```

### Query Router — 6-Tier Pipeline (v1.50.2)

The query router is the heart of the knowledge pipeline. Every information retrieval
request passes through confidence-scored tiers, cheapest first. Provenance logging
tracks which tier answered each query for Oracle observability:

```
Question arrives
    │
    ▼
1. Q&A Cache ──────── Direct lookup in Nexus Q&A pairs
    │ miss              Instant, high confidence, 0 compute
    ▼
2. Vector Search ──── Gemini Embedding 2 + ChromaDB cosine similarity
    │ miss              Fast, high confidence (semantic match)
    ▼
3. FTS Knowledge ──── Full-text search across Nexus entries
    │ miss              Fast, medium confidence
    ▼
4. Nexus Smart Ask ── Server-side pipeline (FTS + NLM hybrid)
    │ miss              Medium, variable confidence
    ▼
5. NLM Direct Ask ─── NotebookLM unified ask (free Gemini)
    │ miss              Slower, high confidence (grounded)
    ▼
6. LLM Fallback ───── Local LMStudio inference
                        Variable confidence, uses local GPU
```

**Auto-store behavior:** Every answer from tiers 3–6 is automatically stored back
into Nexus as a Q&A pair. This promotes the answer to tier 1 for all future queries,
creating a self-improving loop where cache hit rate climbs and expensive calls decrease
over time.

**Vector search (Tier 2):** Uses `EmbeddingService` (Gemini Embedding 2 primary,
LMStudio fallback) with L2-normalized vectors stored in ChromaDB. Controlled by
`nexus.vector_store.enabled` config flag. Health check: `get_vector_store().health()`.

### NotebookLM Data Flow

```
CosySim skill / agent
        │
        ├── engine/integrations/nlm_direct_client.py
        │
        ├── engine/mcp/nlm_live_proxy.py  (Flask :8800 — batchexecute bridge)
        │              │
        │              ▼  HTTPS
        │    notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
        │     (using live browser cookies + NotebookLM session metadata)
        │
        └── Higher-level abstractions:
              ├── nlm_engine.py         Unified NLM client with stats
              ├── nlm_notebook_manager  Named notebook fleet management
              ├── nlm_qa_distiller      Batch Q&A distillation to Nexus
              ├── nlm_router.py         4-tier query router (cache→FTS→NLM→LLM)
              ├── bootstrap_notebooks   Control notebook seeding
              └── notebooklm_flywheel   Control→artifact→tasks→training
```

---

## 3. NexusClient API

`engine/nexus/client.py` — HTTP client for the Nexus REST API. Singleton access via
`get_nexus_client()`.

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
# Returns: {answer, source, confidence, sources, qa_id}

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
rules = client.get_rules(scope="scene:penthouse", rule_type="governance")
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

### Health and Benchmarks

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

### Data Models

All API responses are typed via Pydantic v2 models in `engine/nexus/models.py`:

```python
from engine.nexus.models import NexusEntry, NexusEntryCreate, AgentMemory

entry = NexusEntry(id="abc", title="My note", content="...", created_by="cosysim")
entry.get("title")           # dict-style access (backward compat)
entry["content"]             # dict-style index (backward compat)
entry.model_dump_json()      # Pydantic v2 serialization
```

---

## 4. Smart Query Router

`engine/nexus/query_router.py` — the preferred entry point for all information retrieval.

### Usage

```python
from engine.nexus.query_router import get_query_router

router = get_query_router()

# Query with smart routing
result = router.query("How does state sync work?", min_confidence=0.3)
# Returns: QueryResult(answer="...", source="cache", confidence=0.95, cached=True,
#                       tokens_saved=450, query_time_ms=12.3)

# Check router effectiveness
stats = router.stats
# Returns: RouterStats(total_queries=142, cache_hits=98, vector_hits=10,
#                      search_hits=22, nlm_hits=5, llm_fallbacks=7,
#                      total_tokens_saved=45000)
```

### QueryResult Fields

| Field | Type | Description |
|-------|------|-------------|
| `answer` | `str` | The answer text |
| `source` | `str` | Which tier answered: `cache`, `search`, `nexus-*`, `nlm*`, `llm` |
| `confidence` | `float` | 0.0--1.0 confidence score |
| `cached` | `bool` | Whether this was a cache hit |
| `tokens_saved` | `int` | Estimated tokens saved vs direct LLM |
| `query_time_ms` | `float` | Total query time in milliseconds |
| `sources` | `List[str]` | Contributing source references |

### RouterStats Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_queries` | `int` | Total queries processed |
| `cache_hits` | `int` | Answered by Q&A cache |
| `vector_hits` | `int` | Answered by vector semantic search |
| `search_hits` | `int` | Answered by FTS5 |
| `nlm_hits` | `int` | Answered by NotebookLM |
| `llm_fallbacks` | `int` | Required local LLM |
| `total_tokens_saved` | `int` | Estimated tokens saved |
| `answers_stored` | `int` | Answers auto-stored to cache |

### NLM-First Router Variant

`engine/nexus/nlm_router.py` extends the base router with dedicated NLM tier tracking
and a savings report:

```python
from engine.nexus.nlm_router import get_nlm_router

router = get_nlm_router()
result = router.query("How does the interceptor pipeline work?")
print(result.source)           # "cache", "search", "nlm", or "llm"
print(router.savings_report()) # Token/compute savings summary
```

### Knowledge Backfill Pattern

When Nexus does not have an answer and you find it elsewhere, always write it back:

```python
from engine.nexus.knowledge_capture import capture_external_discovery

result = capture_external_discovery(
    question="How does SceneStateManager work?",
    answer="SceneStateManager coordinates...",
    source="engine/mcp/scene_state.py",
    category="architecture"
)
# Writes BOTH a knowledge entry (discoverable via search)
# AND a Q&A pair (instant via question match)
```

CLI equivalent:

```bash
python -m engine.nexus.bridge backfill "How does X work?" "X works by..." --source docs
```

---

## 5. NotebookLM Integration

CosySim uses Google NotebookLM as a free Gemini intelligence layer for knowledge
distillation, research, and Q&A. Control is via browser-attached auth combined with a
private RPC stack.

### Authentication

Every `batchexecute` request requires:

```http
POST /_/LabsTailwindUi/data/batchexecute HTTP/1.1
Host: notebooklm.google.com
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
Origin: https://notebooklm.google.com
Cookie: SID=...; SSID=...; APISID=...; SAPISID=...; __Secure-1PSID=...
Authorization: SAPISIDHASH <timestamp>_<sha1>
```

**SAPISIDHASH computation:**

```python
import hashlib, time

def compute_sapisidhash(sapisid: str) -> str:
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} https://notebooklm.google.com"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"
```

**Cookie acquisition methods:**

| Method | Command | Notes |
|--------|---------|-------|
| Chrome CDP (recommended) | `python scripts\har_capture.py --mode cdp --account knack112358` | Attaches to running Chrome on port 9222 |
| ARGUS token harvesting | `python -m scripts.argus.tools tokens --account knack112358` | Alternative path |
| HAR import | `POST http://localhost:8800/cookies/import` with `{"har_path": "..."}` | Recovery path |

Cookies are stored in `data/accounts/pool.json` with per-service entries including
`extracted_at` and `source` metadata.

**Build Label (BL):** Format `boq_labs-tailwind-frontend_YYYYMMDD.NN_p0`. Changes
roughly weekly with Google frontend deployments. If stale (>8 days), requests may fail.
Stored in `data/nlm_meta.json`; auto-extracted from imported HARs. Check staleness via
`GET /health` which returns `bl_age_days` and `bl_stale`.

### NLMDirectClient

`engine/integrations/nlm_direct_client.py` — the low-level client for direct
batchexecute RPC calls.

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client

client = get_nlm_direct_client()  # Singleton, uses pool.json cookies
```

**Key methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `ask_question(notebook_uuid, question, source_uuids=None)` | `str` | Gemini-grounded answer with citations |
| `ask_question_stream(notebook_uuid, question)` | `Generator[str]` | Streaming text chunks |
| `list_notebooks()` | `List[dict]` | All notebooks with uuid, title, source/artifact counts |
| `get_notebook_info(notebook_uuid)` | `dict` | Notebook metadata |
| `list_sources(notebook_uuid)` | `List[dict]` | Sources with uuid, type, status, title |
| `get_source_content(notebook_uuid, source_uuid)` | `str` | Raw source text |
| `get_notebook_analysis(notebook_uuid)` | `str` | AI-generated markdown analysis |
| `list_artifacts(notebook_uuid)` | `List[dict]` | Generated artifacts |
| `create_artifact(notebook_uuid, artifact_type)` | `str` | Trigger async artifact generation |
| `get_suggested_questions(notebook_uuid, hint, count)` | `List[str]` | AI-suggested questions |
| `create_note(notebook_uuid, title, content_html)` | `str` | Create pinned note |
| `rename_notebook(notebook_uuid, new_title)` | `None` | Rename notebook |
| `batchexecute(rpcid, payload, notebook_uuid)` | `dict` | Direct RPC access |

**Error types:**

```python
from engine.integrations.nlm_direct_client import (
    NLMAuthError,       # Cookies expired/invalid
    NLMRateLimitError,  # 50 queries/day exceeded
    NLMNotFoundError,   # Notebook UUID not found
    NLMTimeoutError,    # Request timed out
    NLMResponseError,   # Malformed response
)
```

### GoogleAccountPool

Multi-account cookie management for scaling NLM throughput:

```python
from engine.integrations.google_account_pool import get_account_pool

pool = get_account_pool()
cookies = pool.get_cookies("knack112358")
pool.is_stale("knack112358", max_age_hours=48)
pool.refresh_via_cdp("knack112358")
pool.mark_rate_limited("knack112358")
next_account = pool.get_available_account()
```

| Accounts | Queries/Day | Notebooks |
|----------|-------------|-----------|
| 1 | 50 | 100 |
| 5 | 250 | 500 |
| 10 | 500 | 1,000 |

### Notebook Fleet

`engine/nexus/bootstrap_notebooks.py` manages a fleet of purpose-built notebooks:

| Notebook | Sources | Purpose |
|----------|---------|---------|
| `cosysim-architecture` | README, docs/, engine structure | Design and architecture questions |
| `copilot-instructions` | .github/ rules, agents, instructions | Runtime rules for agents |
| `copilot-session-history` | Recent session checkpoints | Session history distillation |
| `cosysim-codebase` | Engine Python source (chunked) | Code analysis and patterns |
| `copilot-system-control` | System state, plans, configs | Control-plane orchestration |

```python
from engine.nexus.bootstrap_notebooks import bootstrap_all

result = bootstrap_all(distill=True)
# Scheduler: "notebook-bootstrap" task runs weekly
```

### Control Notebook Flywheel

The `copilot-system-control` notebook is treated as a control-plane orchestrator.
`engine/nexus/notebooklm_flywheel.py` runs a five-phase pipeline:

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

### NLM Chain Engine

`engine/nexus/nlm_chain.py` — multi-step chain-prompting with progressive research:

```python
from engine.nexus.nlm_chain import NLMChainEngine

engine = NLMChainEngine()

# Single notebook distillation
result = engine.distill_notebook(notebook_id, questions=[
    "What are the core components?",
    "How does governance work?",
])

# Multi-step chain
result = engine.execute_chain("architecture-review", notebook_id,
    initial_question="What are the architectural gaps?"
)

# Batch across notebooks
result = engine.run_batch("weekly-review")
```

### NLM Live Proxy Routes (`:8800`)

`engine/mcp/nlm_live_proxy.py` — Flask REST API bridge to NotebookLM. The proxy has been
refactored into sub-modules for maintainability (`nlm_rpc_constants.py`, `nlm_auth.py`,
`nlm_transport.py`, `nlm_operations.py`, `nlm_archive.py`, `nlm_client.py`,
`nlm_proxy_routes.py`).

**Authentication and setup:**

```
GET  /health               — Status, cookie count, BL age, RPC version
POST /cookies/import        — Import cookies from HAR file
POST /cookies/capture       — Auto-capture cookies via Chrome CDP
POST /cookies/refresh       — Refresh f.sid and at token
GET  /cookies               — List stored cookie names
DELETE /cookies             — Clear all cookies
GET  /meta                  — Current BL and session metadata
POST /meta                  — Update BL or f.sid manually
```

**Notebook operations:**

```
GET  /notebooks                         — List all notebooks
POST /notebooks                         — Create notebook
GET  /notebooks/<id>                    — Full notebook data
POST /notebooks/<id>/rename             — Rename notebook
```

**Source operations:**

```
GET    /notebooks/<id>/sources          — List sources
POST   /notebooks/<id>/sources          — Add URL/YouTube source
GET    /notebooks/<id>/sources/wait     — Poll source processing completion
GET    /notebooks/<id>/sources/content  — Download all source texts
DELETE /sources/<id>                    — Delete source
GET    /sources/<id>/content            — Read source text
```

**AI features:**

```
GET  /notebooks/<id>/summary            — AI overview
GET  /notebooks/<id>/mindmap            — Mind map D3 JSON
POST /notebooks/<id>/ask                — Synchronous Q&A with citations
POST /notebooks/<id>/ask_batch          — Batch up to 5 questions
POST /notebooks/<id>/chat               — Streaming multi-turn chat
```

**Research workflow:**

```
POST /notebooks/<id>/research           — Start fast research
POST /notebooks/<id>/research/deep      — Start deep research
POST /notebooks/<id>/research/source    — Add AI research doc as source
```

**Archive and export:**

```
GET /notebooks/<id>/archive             — Full notebook archive
GET /notebooks/archive                  — Export all notebooks
GET /sources/<id>/export                — Single source as text file
```

**User and rate limiting:**

```
GET  /user/profile?notebook_id=<id>     — Profile + queries remaining
GET  /user/quota                        — Account quota and plan tier
GET  /rate_limit                        — Current rate limit
POST /rate_limit                        — Override rate limit (0.5-30.0s)
POST /rpc/<rpc_id>                      — Call any RPC directly
```

---

## 6. NLM RPC Protocol

**Endpoint:** `POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute`

**Format:** `f.req=[[['rpcid','json_payload',null,'generic']]]`

**Auth:** Session cookies (`__Secure-1PSID`, `__Secure-1PAPISID`) + SAPISIDHASH

**Response:** `)]}' ` prefix + `wrb.fr` JSON frames

### URL Parameters

| Parameter | Example | Notes |
|-----------|---------|-------|
| `rpcids` | `CYK0Xb` or `CYK0Xb;s0tc2d` | Semicolon-separated for batch |
| `source-path` | `/notebook/<nb_id>` | Optional — sets auth context |
| `bl` | `boq_labs-tailwind-frontend_...` | Build label — critical |
| `f.sid` | `-1` or extracted from HAR | Session ID |
| `hl` | `en` | Language |
| `_reqid` | `100000` | Auto-incrementing request ID |
| `rt` | `c` | Response type (always `c`) |

### Response Parsing

```python
def parse_batchexecute_response(raw: str) -> dict:
    # 1. Strip XSSI security prefix
    if raw.startswith(")]}'"):
        raw = raw[5:]

    # 2. Parse chunked transfer — skip hex chunk size lines
    chunks = []
    for line in raw.strip().split("\n"):
        if line.startswith("[["):
            try:
                chunks.extend(json.loads(line))
            except json.JSONDecodeError:
                pass

    # 3. Find wrb.fr response
    for item in chunks:
        if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
            rpcid = item[1]
            payload = json.loads(item[2]) if isinstance(item[2], str) else item[2]
            return {"rpcid": rpcid, "payload": payload}
    return {}
```

### Shared Config Object

Several write RPCs share a common config object as their first argument:

```python
_WRITE_CONFIG = [2, None, None,
    [1, None, None, None, None, None, None, None, None, None, [1]],
    [[2, 1]]
]
```

### Read RPCs

| rpcid | Operation | Request Args | Response Summary |
|-------|-----------|--------------|------------------|
| `ZwVcOc` | Get session limits | `[None, [1, None, ...]]` | `[max_notebooks, max_sources, ?, max_chars_per_source]` |
| `ub2Bae` | List notebooks | `[[2]]` | `[[[title, [[sources]], notebook_id, ...]]]` |
| `wXbhsf` | Get notebook sources | `[None, 1, None, [2]]` | Full source list |
| `rLM1Ne` | Load notebook (poll) | `[notebook_id, None, [2], None, 0]` | Notebook with sources (for polling) |
| `e3bVqc` | Full notebook info | `[None, None, notebook_id]` | Complete notebook record (80-100KB) |
| `hPTbtc` | Get thread IDs | `[[], None, notebook_id, page_size]` | `[[[thread_id]]]` |
| `khqZz` | Read thread messages | `[[], None, None, thread_id, page_size]` | Messages with role (2=user, 1=assistant) |
| `VfAZjd` | AI overview | `[notebook_id, [2]]` | Markdown overview text |
| `gArtLc` | List artifacts | `[_WRITE_CONFIG, notebook_id, filter]` | Artifact list with type and status |
| `sqTeoe` | Audio overview types | `[_WRITE_CONFIG, None, 1]` | Deep dive, Brief, Critique, Debate options |
| `JFMDGd` | User profile | `[notebook_id, [2]]` | Email, display name, queries remaining |
| `ozz5Z` | Feature flags | `[[[[None, "1", plan_tier_id], ...]]]` | Account state and storage quota |
| `CCqFvf` | Resume session | `["", None, None, [2], ...]` | Last notebook ID, state, thread ID |
| `tr032e` | Read source text | `[[[[source_id]]]]` | Raw source markdown |
| `cFji9` | Mind map | `[notebook_id, None, cursor, [2]]` | D3-compatible hierarchical tree |

### Write RPCs

| rpcid | Operation | Request Args | Response Summary |
|-------|-----------|--------------|------------------|
| `s0tc2d` | Rename notebook | `[notebook_id, [[None, None, None, [None, "name"]]]]` | Confirmation |
| `CYK0Xb` | Q&A with citations | `[notebook_id, question_text]` | `[note_id, answer_with_citations]` |
| `R7cb6c` | Generate report | `[_WRITE_CONFIG, notebook_id, [None, None, type, sources]]` | Report artifact |
| `ciyUvf` | Report preview | `[_WRITE_CONFIG, notebook_id, source_arrays]` | Suggested report |
| `izAoDd` | Add source (URL) | `[[[source_obj]], notebook_id, [2], config]` | Source ID |
| `o4cbdc` | Add source (file) | `[[filename], nb_id, [2], config]` | `[source_id, filename, [upload_url]]` |
| `tGMBJ` | Delete source | `[[[source_id]], [2]]` | Confirmation |
| `Ljjv0c` | Fast research | `[[query, 1], None, 1, notebook_id]` | Research session ID |
| `QA9ei` | Deep research | `[None, [1], ["topic", 1], 5, notebook_id]` | Session ID |
| `LBwxtb` | Add research source | `[None, [1], session_id, notebook_id, [[None, [title, content]]]]` | Source added |

### Source Data Structure

```python
source = [
    [source_id],              # position 0: UUID
    "filename_or_title",      # position 1: display name
    [
        None,
        word_count,           # position 1: int
        [unix_sec, nano_sec], # position 2: created_at
        [process_id, [unix_sec, nano_sec]],  # position 3: job info
        format_type,          # position 4: 1=Doc, 2=Slides, 3=PDF, 5=URL, 7=YouTube, 8=Markdown
        None,
        status,               # position 6: 1=private, 2=processed
        [url],                # position 7: source URL (web/YouTube only)
        char_count,           # position 8: optional
    ],
    [None, add_method]        # position 3: 2=url, 1=upload
]
```

### Streaming Chat (GenerateFreeFormStreamed)

Uses server-streaming gRPC over HTTP/1.1, separate from batchexecute:

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
  google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/
  GenerateFreeFormStreamed
?bl=<build_label>&rt=c
```

Auth uses cookies only (no `at` CSRF token). `f.sid` and `_reqid` are not required.

**Request body (`f.req`):**

```python
inner_args = [
    [[[src_id]] for src_id in source_ids],  # source context
    question_text,                           # the question
    None,                                    # reserved
    [2, None, [1], [1]],                    # response config
    thread_id,                               # same=continue, new=fresh
    None, None,
    notebook_id,                             # notebook UUID
    1,                                       # mode flag
]
```

**Response:** Each chunk contains the full text so far (not deltas). Do not concatenate.

### Multi-Question Batching

Up to 5 RPCs per batchexecute request:

```python
calls = [
    ("CYK0Xb", json.dumps([notebook_id, q]))
    for q in questions[:5]
]
# rpcids URL param: "CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb"
```

Each `wrb.fr` block in the response corresponds to one call, in order.

### Deep Research Flow

```
1. QA9ei  — start deep research → session_id
2. (NLM generates AI document asynchronously, 10-60s)
3. LBwxtb — add research source to notebook
4. (Optional) R7cb6c — generate structured note from all sources
```

| Aspect | Fast Research | Deep Research |
|--------|---------------|---------------|
| RPC | `Ljjv0c` then `izAoDd` | `QA9ei` then `LBwxtb` |
| Source type | Existing web pages | AI-generated document |
| Input | Search query | Research topic |
| Output | Multiple URL sources | Single AI research doc |

### ARGUS Observed RPCs

ARGUS has observed 33 of 50 known rpcids. Additional observed but undocumented rpcids
include `xqEXEf` (GenerateNotebookGuide, 34 observations), `otmP3b` (unknown, 54
observations), and `b7Wfje` (unknown, 4 observations). Feature flags are probed via
`ozz5Z` with the full flag ID map stored in `data/argus/feature_flags.json`.

### Discovered but Unwired Capabilities

| Capability | Notes |
|------------|-------|
| Source Discovery | Autonomous web source discovery (`DiscoverSources`, `DiscoverSourcesAsync`) |
| Magic View | AI visual organization (`CCqFvf`, `yyryJe`, `VfAZjd`) |
| Multi-Model | Switch between Gemini 2.5, 3.0, Ultra (`ListModelOptions`) |
| Drive Export | Export artifacts to Google Drive/Sheets (`Krh3pd`) |
| Writing Functions | AI editing — rewrite, expand, summarize (`ExecuteWritingFunction`) |
| Source Freshness | Verify URL sources are up-to-date (`CheckSourceFreshness`) |
| Mutation API | Full CRUD mutations (`MutateProject`, `MutateNote`, etc.) |
| WebRTC Audio | Programmatic audio stream (`GetIceConfig`, `SendSdpOffer`) |
| Sharing | Auto-share notebooks (`ShareProject`, `CreateAccessRequest`) |

### Multimodal Workflows

**Supported source types:**

```
Sources IN                          Generation OUT
text          → izAoDd (paste)      CYK0Xb  → report / analysis / code
URL           → izAoDd (url)        QA9ei   → 30-min podcast (MP3)
YouTube URL   → izAoDd (native)     ciyUvf  → flashcard Q&A pairs
Google Sheets → izAoDd (url)        R7cb6c  → quiz with citations
image (.png)  → o4cbdc + PUT        yyryJe  → concept mind map (JSON)
audio (.mp3)  → o4cbdc + PUT        LBwxtb  → long-form narrative
video (.mp4)  → o4cbdc + PUT        Krh3pd  → export to Google Sheets
PDF           → o4cbdc + PUT        Ljjv0c  → deep research
```

Every output can become the next call's input — generated MP3 can be uploaded back,
Sheets URLs can be added as sources, report artifacts can feed the flashcard generator.

**File upload flow:**

```
1. o4cbdc([filename], nb_id, [2], [1, null, null, [1]])
   → returns [[source_id, filename, [gcs_signed_upload_url]]]
2. PUT file_bytes to gcs_signed_upload_url (timeout: 300s)
3. Poll rLM1Ne until source_id has word_count > 0
```

### Rate Limiting

All outbound calls pass through `_RateLimiter`:

| Setting | Default | Range |
|---------|---------|-------|
| `min_gap_seconds` | 1.5 | 0.5--30.0 |

Batch calls count as one request. Thread-safe via `threading.Lock`. Aggressive calls
(>40 questions/minute) may trigger Google soft-limits.

### Known Limitations

1. `s0tc2d` is rename, not chat — use `GenerateFreeFormStreamed` for chat.
2. `CYK0Xb` is synchronous Q&A with citations — best for programmatic extraction.
3. `GenerateFreeFormStreamed` uses cookies-only auth — no `at` CSRF token.
4. Streaming response contains full text, not deltas — do not concatenate chunks.
5. YouTube sources use position 7 in the source object, not position 2.
6. Chrome 130+ redacts cookies from HAR exports — use CDP capture instead.
7. Build label changes weekly — monitor `bl_stale` in `/health`.
8. Batch limit: 5 RPCs per batchexecute request.
9. Source UUIDs are per-notebook — always fetch fresh from `wXbhsf`.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `/notebooks` returns `no_data` | Run CDP cookie capture; if still fails, import fresh HAR |
| HTTP 502 from proxy | Refresh browser auth; check `data/nlm_meta.json` for valid `bl`, `f_sid`, `at` |
| `cookie_count: 0` in `/health` | Run CDP refresh or import HAR |
| Proxy not starting | Check port 8800 is free; `python -m engine.mcp.nlm_live_proxy` |
| RPC returns 404 | BL may be stale; import fresh HAR or run `/cookies/capture` |

---

## 7. Training Flywheel

`engine/nexus/training_flywheel.py` — automatic training data collection from every
system interaction, exportable in formats suitable for fine-tuning local LMStudio models.

### Collection Sources

```python
from engine.nexus.training_flywheel import get_training_flywheel

fw = get_training_flywheel()

# From task completions
fw.collect_from_task(task_id, description, result, model="qwen3-0.6b")

# From Q&A pairs (auto-wired from QA Expander and Generator)
fw.collect_from_qa(question, answer, source="cache", quality=0.7)

# From NotebookLM research
fw.collect_from_nlm(question, answer, notebook_id="abc", quality=0.8)

# From router decisions (DPO training)
fw.collect_from_routing(question, chosen_source="cache", rejected_source="llm")

# Direct preference pairs
fw.collect_preference(question, preferred_answer, rejected_answer)
```

### Export Formats

| Format | Schema | Use Case |
|--------|--------|----------|
| JSONL | `{instruction, output}` | Instruction-tuning |
| ShareGPT | `{conversations: [{from, value}]}` | Conversational fine-tuning |
| DPO | `{prompt, chosen, rejected}` | Preference optimization |

```python
jsonl = fw.export_jsonl(min_quality=0.5)
sharegpt = fw.export_sharegpt(min_quality=0.5)
dpo = fw.export_dpo()
fw.sync_from_nexus()   # Pull Q&A pairs from Nexus
```

### Q&A Generation

**QA Expander** (`engine/nexus/qa_expander.py`) — reverse-generates Q&A from existing
Nexus entries via NotebookLM:

```
For each entry:
  1. Ask NLM: "What 5 questions does this entry answer?"
  2. For each question: distill the answer via NLM
  3. Store as Nexus Q&A pair
  4. Feed into TrainingFlywheel
```

**QA Generator** (`engine/nexus/qa_generator.py`) — two-mode generation:

| Mode | Speed | Quality | Pairs/Run |
|------|-------|---------|-----------|
| Rule-based | Instant | Medium | 200--800 |
| LLM-based | Slower | High | ~200 |

### How Nexus Feeds Fine-Tuning

The complete loop:

```
Runtime interactions (agent replies, Q&A, research, tasks)
    │
    ▼
TrainingFlywheel collects examples with quality scores
    │
    ▼
Export to JSONL/ShareGPT/DPO files
    │
    ▼
training/auto_train.py picks up datasets → fine-tune local models
    │
    ▼
Better local models → cheaper LLM fallback → more cache hits
    │
    ▼
Cycle repeats — each generation improves the next
```

---

## 8. MCP Skills

### Nexus Skills (17 skills, pack="nexus")

| Skill | Description |
|-------|-------------|
| `nexus_search` | Search the Nexus knowledge base |
| `nexus_add` | Add a knowledge entry |
| `nexus_ask` | Smart Q&A — cache, knowledge, NLM research |
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
| `nexus_smart_query` | Smart query with 4-tier routing |
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

### NotebookLM Skills (pack="notebooklm")

| Skill | Description |
|-------|-------------|
| `notebooklm_ask` | Ask a question against a notebook with citations |
| `notebooklm_add_source` | Add a URL, text, PDF, or YouTube link |
| `notebooklm_generate_audio` | Generate a podcast-style Audio Overview |
| `notebooklm_list_notebooks` | List all visible notebooks |
| `notebooklm_search` | Search across all notebooks by keyword |

### NLM Live Skills (via proxy)

```python
nlm_live_ask(notebook_id, "What is X?")
nlm_live_batch_ask(notebook_id, ["Q1?", "Q2?", "Q3?"])
nlm_generate_document(notebook_id, source_ids)
nlm_save_note(notebook_id, source_ids)
nlm_capture_cookies()
nlm_distill_notebook(notebook_id)
```

### Autonomy Skills (67 skills, pack="autonomy")

| Category | Count | Key Skills |
|----------|-------|------------|
| Scheduler | 3 | `scheduler_status`, `scheduler_run_now`, `scheduler_list_tasks` |
| News | 4 | `news_fetch`, `news_fetch_and_store`, `news_digest` |
| NLM Notebooks | 5 | `nlm_notebook_list`, `nlm_notebook_seed_docs`, `nlm_notebook_rotate` |
| Nexus Quality | 3 | `nexus_quality_report`, `nexus_full_maintenance`, `nexus_backup` |
| Governance | 6 | `governance_validate_file`, `governance_enforce`, `governance_stats` |
| Task Management | 4 | `tasks_from_test_failures`, `task_from_template` |
| Training | 7 | `training_collect_task`, `training_export_jsonl`, `training_sync_nexus` |
| Metrics | 10 | `metrics_record`, `metrics_trend`, `metrics_dashboard`, `reflection_run` |

---

## 9. Configuration

All Nexus-related config lives in `config/default.yaml`.

### Nexus KMS

```yaml
nexus:
  enabled: true
  base_url: "http://localhost:8700"
  auto_submit: false
  knowledge_expiry:
    default_max_age_days: 90
    category_ttl_days:
      news: 2
      session: 30
      memory: 60
      architecture: 365
      api: 180
      system: 365
    stale_threshold: 0.2
    auto_archive_stale: false
  operator_inbox:
    state_path: "data/operator_inbox_state.json"
    auto_sync_schedule: "every_15m"
  embeddings:
    enabled: true
    provider: "auto"                  # gemini | local | auto
    model: "gemini-embedding-001"
    dimensions: 768                   # MRL: 768/1536/3072
    local_model: "text-embedding-nomic-embed-text-v1.5"
    cache_size: 10000
    batch_size: 100
    auto_embed: true
  vector_store:
    enabled: true
    persist_dir: "data/nexus_vectors"
    default_top_k: 5
    min_score: 0.5
```

### NotebookLM

```yaml
notebooklm:
  enabled: true
  proxy_url: "http://localhost:8800"
  base_url: "http://localhost:8800"
  default_notebook_id: ""
  timeout: 120
  metadata_path: "data/nlm_notebooks.json"
  rate_limit_seconds: 1.5
  flywheel:
    enabled: true
    min_interval_hours: 8
    max_tasks: 6
    distill_category: "notebooklm-flywheel"
```

### Query Router

Configured in `engine/nexus/query_router.py` via `get_config()`:

| Key | Default | Description |
|-----|---------|-------------|
| `nexus.query_router.min_confidence` | `0.3` | Minimum confidence to accept an answer |
| `nexus.query_router.use_llm` | `false` | Enable LLM fallback tier |
| `nexus.query_router.local_cache_ttl` | `300` | In-memory cache TTL (seconds) |

### Scheduler Daemon

Key scheduler tasks related to Nexus and NLM:

| Task | Schedule | Description |
|------|----------|-------------|
| `nexus-health` | Daily | Health check and stats collection |
| `nexus-dedup` | Weekly | Deduplication scan |
| `qa-expansion` | Daily | Expand entries into Q&A pairs |
| `notebook-bootstrap` | Weekly | Notebook refresh + control follow-up |
| `control-notebook-flywheel` | 8h | Control-plane artifact refresh |
| `cookie-auto-refresh` | 72h | CDP cookie refresh for all accounts |
| `cookie-health-check` | Daily | Verify cookie freshness |
| `news-distill-nlm` | Daily | Distill Q&A from news notebooks |
| `training-sync` | Daily | Sync training data from Nexus |
| `router-finetune-cycle` | Weekly | Retrain router model |

---

## 10. Cross-References

- [Architecture](ARCHITECTURE.md) — Full engine subsystem overview
- [MCP Framework](MCP_FRAMEWORK.md) — Skill decorator and interceptor patterns
- [Training](TRAINING.md) — Fine-tuning pipeline and dataset management
- [ARGUS](ARGUS.md) — Browser automation, NLM protocol observation, feature flag probing

---

## Change Log

```
v1.50 [2026-03-22] — Consolidated from NEXUS_INTEGRATION.md, NLM_REFERENCE.md,
                      and NLM_API_REFERENCE.md into unified knowledge pipeline doc.
                      Updated query router to 4-tier (vector search merged into tier 2).
                      Added ARGUS observed RPC coverage (33/50 rpcids).
                      Added multimodal workflow reference.
                      Added full configuration reference with current default.yaml keys.
```
