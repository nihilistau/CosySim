# Nexus KMS — The Brain of CosySim

> CosySim Documentation — v1.57.0 [2026-03-26]
>
> Complete technical reference for Nexus, the central knowledge management and
> command-control system that powers CosySim's self-improving AI agents.

---

## 1. What Nexus Is

Nexus is CosySim's **local-first knowledge backbone** — a persistent SQLite database
with FTS5 full-text search, agent registry, Q&A cache, ground truth layer, and
NotebookLM mirroring that runs on `localhost:8700`. It is the single source of truth
for everything the system has ever learned, decided, or observed.

Nexus stores and serves:

- **71,000+ knowledge entries** across 9 content types (note, code, document, prompt,
  transcript, research, memory, history, plan)
- **3,700+ Q&A pairs** — instant answers that bypass GPU inference entirely
- **361 governance rules** — coding standards, testing gates, agent permissions,
  workflow reminders
- **371 session records** — every Copilot/Claude Code session logged with commits,
  files, and summaries
- **Agent registry** — typed agents with tiered access control (readonly through admin)

Every agent, scene, skill, and development session both consumes from and contributes
to Nexus. The system is designed to compound: each interaction makes future interactions
cheaper and more accurate.

### Why Nexus Exists

Without Nexus, every new conversation with an AI agent starts from zero. Nexus solves
this by providing:

1. **Persistent memory** — decisions, patterns, and solutions survive across sessions
2. **Cost reduction** — cached answers serve instantly without GPU compute
3. **Quality compounding** — answers improve over time as more Q&A pairs accumulate
4. **Governance** — codified rules prevent agents from repeating known mistakes
5. **Training data** — every interaction feeds the fine-tuning pipeline for local models

### How Nexus Runs

Nexus is a managed service that auto-starts with CosySim:

```bash
# Auto-start (recommended) — launches as priority 0 (first)
python launcher.py --core
python launcher.py --all
python tui.py              # TUI autostart

# Manual start
cd C:\Files\Nexus && python -m nexus api
```

Health check: `GET http://localhost:8700/api/health`

The knowledge pipeline connects three tiers of intelligence:

| Tier | System | Role |
|------|--------|------|
| **Nexus KMS** | SQLite + FTS5 on `:8700` | Persistent knowledge, rules, Q&A, sessions |
| **NotebookLM** | Google Gemini via NLM Proxy on `:8800` | Free Gemini inference, research distillation |
| **LMStudio** | Local LLM on `:1234` | Last-resort fallback for novel queries |

Together these form a self-improving loop: the first time a question is asked it costs
compute; every subsequent time it is served from Nexus cache for free.

---

## 2. Architecture

### System Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│  Copilot CLI / Claude Code / GitHub Copilot                       │
│  ├── CopilotBridge       session start/end, pre-plan, metrics     │
│  ├── CopilotSelfConfig   bidirectional config sync                │
│  ├── CopilotValidation   drift detection, hook integrity          │
│  ├── SeedCopilotRules    mirror repo assets into Nexus            │
│  └── SessionLogger       checkpoint/compact/end export            │
├───────────────────────────────────────────────────────────────────┤
│  CosySim Engine (Agents, Scenes, Skills)                          │
│  ├── NexusClient          HTTP client for Nexus API               │
│  ├── NexusQueryRouter     7-tier smart routing (+ Gemini File Search) │
│  ├── EmbeddingService     Gemini Embedding 2 Preview + LMStudio   │
│  ├── NexusVectorStore     ChromaDB semantic search                 │
│  ├── KnowledgePipeline    Unified ingest: validate→dedup→store    │
│  ├── TrainingFlywheel     auto-collect training data              │
│  ├── TaskScheduler        agent task ticketing + auto-assign      │
│  ├── SchedulerDaemon      91 recurring tasks (cron-like)          │
│  ├── OperatorInbox        off-turn directive intake               │
│  ├── KnowledgeCapture     dual-write backfill helper              │
│  ├── NLMChain             multi-step chain-prompting              │
│  ├── NotebookLMFlywheel   control notebook → tasks → train        │
│  └── 103 total modules in engine/nexus/                           │
├───────────────────────────────────────────────────────────────────┤
│  Skills Layer (93 Nexus-aware skills)                             │
│  ├── nexus_skills.py      17 skills (search, ask, store, NLM)     │
│  ├── coding_skills.py      9 skills (snippets, decisions)         │
│  └── autonomy_skills.py   67 skills (scheduler, training)         │
├───────────────────────────────────────────────────────────────────┤
│                Nexus HTTP REST API (port 8700)                    │
├───────────────────────────────────────────────────────────────────┤
│  Nexus Server (C:\Files\Nexus)                                    │
│  ├── SQLite + FTS5         Full-text search engine                 │
│  ├── Flask REST API        CRUD + search + rules + sessions        │
│  └── 4-layer DB            see below                              │
└───────────────────────────────────────────────────────────────────┘
```

### 4-Layer Database Architecture

The Nexus database is organized into four conceptual layers, each with distinct
durability and access patterns:

#### Layer 1: NLM Mirror Layer (4 tables)

Cached NotebookLM data — notebooks, sources, artifacts, and thread histories pulled
from the NLM proxy. These are regenerable from the upstream notebooks but cached for
offline access and fast retrieval.

| Table | Purpose |
|-------|---------|
| `nlm_notebooks` | Notebook registry with UUID, title, source count, last sync |
| `nlm_sources` | Per-notebook sources with content hashes and processing status |
| `nlm_artifacts` | Generated reports, audio overviews, flashcards |
| `nlm_threads` | Chat thread history with role and content |

#### Layer 2: Ground Truth Layer (2 tables)

Immutable versioned records. Once written, ground truth entries are never modified —
only new versions are appended. This layer holds the canonical facts that all other
layers reference.

| Table | Purpose |
|-------|---------|
| `ground_truth` | Versioned immutable records (e.g., transcript imports, validated facts) |
| `ground_truth_versions` | Version chain linking successive revisions |

#### Layer 3: Working Layer (3 tables + FTS)

Mutable knowledge entries that agents read and write during normal operation. FTS5
indexes provide sub-millisecond full-text search across all content.

| Table | Purpose |
|-------|---------|
| `entries` | Notes, code, docs, prompts, transcripts, memories, plans |
| `qa_pairs` | Direct question-to-answer lookup (fastest tier) |
| `entries_fts` | FTS5 virtual table — tokenized index of title + content |

#### Layer 4: System Layer (26 tables)

Agent registry, access logs, sessions, rules, metrics, subscriptions, benchmarks,
tasks, experiments, and operational state.

| Table | Purpose |
|-------|---------|
| `agent_registry` | Typed agents with tiers and allowed operations |
| `access_log` | Per-agent access audit trail |
| `sessions` | Development session records |
| `rules` | Governance rules with scope, condition, action |
| `benchmarks` | Model benchmark results for leaderboard |
| `metrics` | System metrics time series |
| `subscriptions` | Knowledge change notification subscriptions |
| `tasks` | Agent task queue with assignment and status |
| `experiments` | Experiment proposals and execution results |
| `plugins` | Registered plugins and hooks |
| ... | Additional operational tables |

### Content Types

Every knowledge entry has a `content_type` field that determines how it is indexed,
searched, and presented:

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

### Knowledge Namespaces

Entries are further organized by namespace (defined in
`engine/nexus/nexus_namespaces.py`), each with type and category constraints:

| Namespace | Description | Allowed Types |
|-----------|-------------|---------------|
| `system` | Core engine, framework, infrastructure | document, code, note, prompt |
| `scene` | Scene-specific state, rules, content | note, memory, document, plan |
| `agent` | Agent personalities, behaviors, memories | memory, note, prompt |
| `copilot` | Copilot CLI sessions, decisions, prompts | note, code, document, history |
| `training` | Fine-tuning data, datasets, model configs | document, code, note |
| `research` | Research sessions, design docs, analysis | research, document, note |
| `content` | Pre-built dialog, descriptions, assets | note, prompt, document |

---

## 3. The 7-Tier Query Pipeline

The query router (`engine/nexus/query_router.py`) is the heart of the knowledge
pipeline. Every information retrieval request passes through confidence-scored tiers,
cheapest first. Provenance logging tracks which tier answered each query for Oracle
observability.

### Pipeline Flow

```
Question arrives → NexusQueryRouter.query()
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Tier 1: Q&A Cache                                               │
│   ├── Direct lookup in Nexus Q&A pairs (client.find_qa)         │
│   ├── Confidence: 0.90 (configurable)                           │
│   ├── Cost: 0 tokens, instant                                   │
│   └── On hit → return immediately                               │
├─────────────────────────────────────────────────────────────────┤
│ Tier 2: Vector Semantic Search                                   │
│   ├── Gemini Embedding 2 Preview + ChromaDB cosine similarity   │
│   ├── Searches: knowledge, qa, code, news collections            │
│   ├── Confidence: 0.82 (configurable)                           │
│   ├── Cost: 1 embedding API call (~0.001 cents)                 │
│   ├── Feature flag: nexus.vector_store.enabled                   │
│   └── On hit → return immediately                               │
├─────────────────────────────────────────────────────────────────┤
│ Tier 2.5: Gemini File Search (Managed RAG)              [NEW]    │
│   ├── FileSearchClient queries Gemini managed RAG stores         │
│   ├── Grounded citations with source document references         │
│   ├── Confidence: 0.85 (configurable)                           │
│   ├── Cost: 1 Gemini API call                                   │
│   ├── Auto-distills answers into Nexus Q&A cache                 │
│   └── On hit → return immediately                               │
├─────────────────────────────────────────────────────────────────┤
│ Tier 3: FTS Knowledge Search                                     │
│   ├── Full-text search across Nexus entries (FTS5)               │
│   ├── Synthesize answer from matching entries                    │
│   ├── Confidence: 0.75 (high match) / 0.50 (medium) / 0.30     │
│   ├── Cost: 0 tokens, fast                                      │
│   └── On hit → auto-store as Q&A pair, then return              │
├─────────────────────────────────────────────────────────────────┤
│ Tier 4: Nexus Smart Ask                                          │
│   ├── Server-side pipeline (FTS + NLM hybrid)                    │
│   ├── Supports depth: shallow, auto, deep                        │
│   ├── Confidence: variable                                       │
│   └── On hit → return                                           │
├─────────────────────────────────────────────────────────────────┤
│ Tier 5: Direct NotebookLM Ask                                    │
│   ├── Free Gemini compute via unified NLM backend                │
│   ├── Grounded in notebook sources (high quality)                │
│   ├── Confidence: variable (typically high)                      │
│   └── On hit → auto-store as Q&A pair, then return              │
├─────────────────────────────────────────────────────────────────┤
│ Tier 6: LLM Fallback                                             │
│   ├── LMStudio local GPU inference                               │
│   ├── Confidence: 0.60 (variable)                                │
│   ├── Cost: GPU tokens                                           │
│   └── On answer → auto-store as Q&A pair for future reuse       │
└─────────────────────────────────────────────────────────────────┘
```

### Self-Improving Behavior

Every answer from tiers 2-6 is automatically stored back into Nexus as a Q&A pair.
This promotes the answer to tier 1 for all future queries, creating a flywheel:

```
First query:  Tier 6 (LLM) → GPU cost → store as Q&A
Second query: Tier 1 (cache) → 0 cost → instant
Third query:  Tier 1 (cache) → 0 cost → instant
...forever:   Tier 1 (cache) → 0 cost → instant
```

Over time, as more answers accumulate in Nexus, fewer LLM calls are needed. The
`RouterStats` dataclass tracks this progression:

```python
from engine.nexus.query_router import get_query_router

router = get_query_router()
result = router.query("How does state sync work?")
# Returns: QueryResult(answer="...", source="cache", confidence=0.95,
#          cached=True, tokens_saved=450, query_time_ms=12.3)

stats = router.stats
# RouterStats(total_queries=142, cache_hits=98, vector_hits=10,
#             search_hits=22, nlm_hits=5, llm_fallbacks=7,
#             total_tokens_saved=45000, nexus_hit_rate="91.5%")
```

### Configuration

| Config Key | Default | Description |
|-----------|---------|-------------|
| `nexus.query_router.cache_confidence` | `0.90` | Confidence assigned to Q&A cache hits |
| `nexus.query_router.vector_confidence` | `0.82` | Confidence assigned to vector search hits |
| `nexus.query_router.search_high` | `0.75` | Confidence for strong FTS matches |
| `nexus.query_router.search_medium` | `0.50` | Confidence for decent FTS matches |
| `nexus.query_router.search_low` | `0.30` | Confidence for weak FTS matches |
| `nexus.query_router.min_answer_length` | `20` | Minimum chars for a valid answer |
| `nexus.query_router.local_cache_ttl` | `300` | In-memory session cache TTL (seconds) |

---

## 4. Agent Registry & Access Control

### Agent Type System

Nexus implements a formal agent type system (`engine/nexus/governance_rules.py`)
backed by the `agent_registry` table. Each agent type has a tier that determines
its allowed operations:

```python
AGENT_TYPES = {
    "copilot":      {"tier": "expert",   "ops": ["read", "write", "delete", "admin"]},
    "claude_code":  {"tier": "expert",   "ops": ["read", "write", "delete", "admin"]},
    "scene_agent":  {"tier": "worker",   "ops": ["read", "write"]},
    "scheduler":    {"tier": "system",   "ops": ["read", "write", "admin"]},
    "training":     {"tier": "system",   "ops": ["read", "write"]},
    "observer":     {"tier": "readonly", "ops": ["read"]},
    "player":       {"tier": "worker",   "ops": ["read", "write"]},
    "system":       {"tier": "admin",    "ops": ["read", "write", "delete", "admin"]},
}
```

### Access Tiers

| Tier | Operations | Use Case |
|------|-----------|----------|
| `readonly` | read | Monitoring agents, dashboards |
| `worker` | read, write | Scene agents, players — can contribute knowledge |
| `expert` | read, write, delete, admin | Copilot, Claude Code — full access |
| `system` | read, write, admin | Scheduler, training — system operations |
| `admin` | read, write, delete, admin | System-level full control |

### Governance Check Flow

Every mutating operation on the NexusClient goes through `_check_governance()`:

```
NexusClient.add_entry(agent_id="scene_agent")
    │
    ▼
1. _resolve_governance_actor() → resolve identity from agent_id or created_by
    │
    ▼
2. _check_access_registry() → query Nexus /api/agents/{id} for allowed_operations
    │
    ├── Agent found + has ops → return True/False definitively
    ├── Agent found + no ops → resolve from AGENT_TYPES dict
    └── Agent not found / registry unavailable → fall through
    │
    ▼
3. GovernanceManager.check_permissions() → heuristic fallback
    │
    ├── Allowed → return actor identity
    └── Denied → raise PermissionError
```

### Auto-Registration

Agents auto-register with Nexus when they start:
- **SchedulerDaemon** registers as `agent_type="scheduler"` on `start()`
- **CopilotBridge** registers as `agent_type="copilot"` on session begin
- **AgentLoop** registers scene agents as `agent_type="scene_agent"`

### Trusted Actor Resolution

The `_resolve_governance_actor()` function maps `created_by` strings to known
trusted actors. Strings starting with these prefixes are treated as trusted:

```
copilot, nexus, session, research, content, workflow, benchmark,
api, system, filesystem, oracle, scheduler, training
```

Strings ending with these suffixes are also trusted:

```
_workflow, _sync, _logger, _bridge, _pipeline, _distiller, _generator
```

---

## 5. Knowledge Pipeline

### Unified Ingestion

The `KnowledgePipeline` class (`engine/nexus/knowledge_pipeline.py`) provides a
single entry point for ALL knowledge ingestion. Every source — sessions, URLs,
agents, NLM distillation, manual entry — routes through this pipeline.

### Pipeline Stages

```
ingest(title, content, content_type, category, tags, agent_id)
    │
    ▼
┌──────────────────────────────────────────────────┐
│ Step 1: Validate                                  │
│   ├── Title and content must be non-empty          │
│   └── Content minimum 20 characters               │
├──────────────────────────────────────────────────┤
│ Step 2: Deduplicate (SHA-256 content hash)        │
│   ├── Hash title + first 500 chars of content      │
│   ├── Search Nexus for existing hash               │
│   └── If duplicate found → skip, return success    │
├──────────────────────────────────────────────────┤
│ Step 3: Quality Score (heuristic)                 │
│   └── Score based on content length, structure     │
├──────────────────────────────────────────────────┤
│ Step 4: Store in Nexus                            │
│   ├── Tags: original tags + hash:{sha} + source   │
│   └── NexusClient.add_entry() with governance      │
├──────────────────────────────────────────────────┤
│ Step 5: Auto-Embed in Vector Store                │
│   ├── Push to ChromaDB via EmbeddingService        │
│   └── Uses Gemini Embedding 2 Preview (768/1536/3072) │
├──────────────────────────────────────────────────┤
│ Step 6: Auto-Generate Q&A Pairs                   │
│   ├── Only if quality_score >= 0.5                 │
│   └── Creates searchable Q&A pairs from content    │
├──────────────────────────────────────────────────┤
│ Step 7: Notify Subscribers                        │
│   └── Alert watchers of new content in category    │
├──────────────────────────────────────────────────┤
│ Step 8: Feed Training Flywheel                    │
│   └── Generate instruction-tuning training data    │
└──────────────────────────────────────────────────┘
    │
    ▼
PipelineResult(success, entry_id, qa_pairs_generated,
               was_duplicate, quality_score, embedded,
               subscribers_notified, duration_ms)
```

### Usage

```python
from engine.nexus.knowledge_pipeline import get_knowledge_pipeline

pipeline = get_knowledge_pipeline()
result = pipeline.ingest(
    title="Architecture Decision: Use FTS5 for Search",
    content="After evaluating options, we chose FTS5 because...",
    content_type="document",
    category="architecture",
    tags=["database", "search", "decision"],
    agent_id="copilot",
    auto_qa=True,
    auto_embed=True,
    source="session_logger",
)
# PipelineResult(success=True, entry_id="abc123",
#                qa_pairs_generated=3, quality_score=0.85,
#                embedded=True, duration_ms=245.0)
```

### Knowledge Backfill Pattern

When knowledge is found outside Nexus, always write it back as both a knowledge
entry AND a Q&A pair:

```python
from engine.nexus.knowledge_capture import capture_external_discovery

result = capture_external_discovery(
    question="How does SceneStateManager work?",
    answer="SceneStateManager coordinates scene state via...",
    source="engine/mcp/scene_state.py",
    category="architecture"
)
```

CLI equivalent:

```bash
python -m engine.nexus.bridge backfill "How does X work?" "X works by..." --source docs
```

---

## 6. NotebookLM Integration

CosySim uses Google NotebookLM as a free Gemini intelligence layer for knowledge
distillation, research, and Q&A. This provides Gemini-class inference at zero cost,
grounded in uploaded source documents.

### Three Transport Layers

```
CosySim skill / agent
    │
    ├── 1. NLMDirectClient (engine/integrations/nlm_direct_client.py)
    │      └── Direct batchexecute RPC calls to notebooklm.google.com
    │
    ├── 2. NLM Live Proxy (engine/mcp/nlm_live_proxy.py — Flask :8800)
    │      └── Batchexecute bridge with cookie management, rate limiting
    │
    └── 3. Higher-level abstractions:
           ├── nlm_engine.py         — Unified NLM client with stats
           ├── nlm_notebook_manager  — Named notebook fleet management
           ├── nlm_qa_distiller      — Batch Q&A distillation to Nexus
           ├── nlm_router.py         — 4-tier NLM query router
           ├── bootstrap_notebooks   — Control notebook seeding
           └── notebooklm_flywheel   — Control→artifact→tasks→training
```

### Authentication Chain

Every `batchexecute` request requires Google session cookies and a computed
SAPISIDHASH authorization header:

```python
import hashlib, time

def compute_sapisidhash(sapisid: str) -> str:
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} https://notebooklm.google.com"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"
```

**Cookie acquisition methods:**

| Method | Command | Priority |
|--------|---------|----------|
| Chrome CDP (recommended) | `python scripts/har_capture.py --mode cdp` | Primary |
| ARGUS token harvesting | `python -m scripts.argus.tools tokens` | Alternative |
| HAR import | `POST http://localhost:8800/cookies/import` | Recovery |

### Notebook Fleet

`engine/nexus/bootstrap_notebooks.py` manages purpose-built notebooks:

| Notebook | Sources | Purpose |
|----------|---------|---------|
| `cosysim-architecture` | README, docs/, engine structure | Design & architecture questions |
| `copilot-instructions` | .github/ rules, agents | Runtime rules for agents |
| `copilot-session-history` | Recent session checkpoints | Session history distillation |
| `cosysim-codebase` | Engine Python source (chunked) | Code analysis and patterns |
| `copilot-system-control` | System state, plans, configs | Control-plane orchestration |

### Control Notebook Flywheel

The `copilot-system-control` notebook acts as a control-plane orchestrator.
`engine/nexus/notebooklm_flywheel.py` runs a five-phase pipeline:

```
Phase 1: Multi-Ask      → Ask grounded control-plane questions
Phase 2: Report          → Generate strict JSON artifact
Phase 3: Storage         → Store artifact + context packet in Nexus
Phase 4: Task Creation   → Create TaskScheduler items for agents
Phase 5: Training        → Feed TrainingFlywheel with Q&A + task envelopes
```

---

## 7. Self-Improvement Loop

Nexus enables a fully closed self-improvement loop where the system gets smarter
and cheaper with every interaction:

```
┌─────────────────────────────────────────────────────────┐
│                   The Nexus Flywheel                      │
│                                                           │
│  Agent receives question                                  │
│      │                                                    │
│      ▼                                                    │
│  QueryRouter (Nexus cache before GPU)                     │
│      │                                                    │
│      ├── Cache hit? → Serve instantly (0 tokens)         │
│      └── Cache miss? → LLM/NLM generates answer         │
│                            │                              │
│                            ▼                              │
│                   Auto-store Q&A in Nexus                 │
│                            │                              │
│                            ▼                              │
│              DataCollector captures training data          │
│              (agent_decision_live.jsonl)                   │
│                            │                              │
│                            ▼                              │
│              auto_train.py (threshold → finetune)         │
│                            │                              │
│                            ▼                              │
│              BenchmarkRunner evaluates new model          │
│                            │                              │
│                            ▼                              │
│              ModelRegistry.promote() → hot-reload         │
│                            │                              │
│                            ▼                              │
│              Agent uses improved model                    │
│                            │                              │
│                            ▼                              │
│              Better answers → more cache hits             │
│              → fewer GPU calls → loop closes              │
└─────────────────────────────────────────────────────────┘
```

### Training Data Collection

The `TrainingFlywheel` (`engine/nexus/training_flywheel.py`) automatically collects
training data from every system interaction:

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
```

### Export Formats

| Format | Schema | Use Case |
|--------|--------|----------|
| JSONL | `{instruction, output}` | Instruction-tuning |
| ShareGPT | `{conversations: [{from, value}]}` | Conversational fine-tuning |
| DPO | `{prompt, chosen, rejected}` | Preference optimization |

### Q&A Generation

Two Q&A generation systems feed the cache and training pipeline:

**QA Expander** (`engine/nexus/qa_expander.py`) — reverse-generates Q&A from
existing entries via NotebookLM:

```
For each high-quality entry:
  1. Ask NLM: "What 5 questions does this entry answer?"
  2. For each question: distill the answer via NLM
  3. Store as Nexus Q&A pair
  4. Feed into TrainingFlywheel
```

**QA Generator** (`engine/nexus/qa_generator.py`) — two-mode generation:

| Mode | Speed | Quality | Pairs/Run |
|------|-------|---------|-----------|
| Rule-based | Instant | Medium | 200-800 |
| LLM-based | Slower | High | ~200 |

---

## 8. Scheduler Tasks

The `TaskSchedulerDaemon` (`engine/nexus/scheduler_daemon.py`) manages 91 recurring
tasks organized into 16 categories. The daemon runs in a background thread, checking
for due tasks every 60 seconds.

### Task Categories

#### Knowledge Management (6 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `nexus-maintenance` | Daily | Health report and stats collection |
| `nexus-dedup` | Weekly | Deduplication scan |
| `knowledge-quality` | Weekly | Knowledge quality scoring |
| `notebook-rotation` | Weekly | NLM notebook rotation |
| `coverage-eval` | Daily | Knowledge coverage evaluation |
| `doc-sync` | Daily | Auto documentation sync |

#### Q&A Generation (5 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `qa-generation` | Daily | Nexus Q&A pair generation |
| `qa-expansion` | Daily | Reverse-generate Q&A pairs from entries |
| `qa-history-mine` | Weekly | NLM-driven Q&A cache pipeline |
| `qa-cache-prune` | Weekly | Remove stale zero-hit pairs |
| `nlm-auto-distill` | Every 6h | Auto-distill Q&A from high-traffic topics |

#### Session / Conversation (4 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `session-distillation` | Daily | Copilot session distillation |
| `conversation-analyze` | Daily | Post-session conversation analysis |
| `copilot-self-sync` | Weekly | Copilot config sync to Nexus |
| `session-bulk-sync` | Daily | Bulk sync from ~/.copilot to Nexus |

#### Notebook / Bootstrap (4 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `notebook-bootstrap` | Weekly | NLM notebook bootstrap |
| `master-notebook-refresh` | Weekly | Master notebook weekly refresh |
| `master-notebook-rebuild` | Weekly | Rebuild master intelligence notebook |
| `control-notebook-flywheel` | Every 8h | Control-plane artifact refresh |

#### Training (9 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `training-sync` | Daily | Training data sync from Nexus |
| `teacher-dataset-gen` | Weekly | NLM teacher dataset generation |
| `finetune-if-ready` | Weekly | Auto fine-tune when 500+ examples |
| `router-finetune-cycle` | Weekly | Router v2 full finetune cycle |
| `dataset-augment` | Weekly | Dataset augmentation from sessions |
| `model-benchmark` | Daily | Daily micro-model benchmarks |
| `model-zoo-train` | Daily | Model zoo auto-train |
| `router-data-export` | Every 4h | Router training data export |
| `router-v3-retrain` | Weekly | Router v3 retrain cycle |

#### Auth / Cookies (3 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `cdp-auth-health` | Every 30m | Google auth health + auto-recovery |
| `cookie-health-check` | Daily | Probe cookie pool, warn if stale |
| `cookie-auto-refresh` | Every 12h | CDP cookie extraction from Chrome |

#### News Intelligence (6 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `news-fetch` | Every 8h | News fetch and digest |
| `news-nlm-retry` | Every 12h | News NLM retry queue |
| `news-distill-nlm` | Every 1h | News NLM distillation |
| `feed-health` | Every 12h | RSS feed health check |
| `ha-news-push` | Every 8h | Push news to Home Assistant |
| `workspace-news-pipeline` | Every 8h | Workspace RSS → NLM → Nexus |

#### Scene / World Simulation (5 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `world-sim-tick` | Every 5m | World simulation time advance |
| `director-tick` | Every 15m | Scene director narrative beat |
| `content-refresh` | Every 6h | Content pool NLM refill |
| `nlm-content-seed` | Weekly | Deep-seed all scene pools via NLM |
| `scene-lore-seed` | Weekly | NLM lore generation for all scenes |

#### Testing / Monitoring (4 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `test-monitor` | Daily | Test suite monitor |
| `test-suite-benchmark` | Weekly | Time the full pytest suite |
| `metrics-collect` | Every 4h | System metrics collection |
| `benchmark-flush` | Every 5m | Flush benchmarks to MetricsDB |

#### ARGUS (4 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `argus-periodic-crawl` | Weekly | API surface scan |
| `argus-weekly-scan` | Weekly | NLM/Gemini Playwright crawl |
| `argus-diff-report` | Weekly | Compare latest vs prior scan |
| `argus-nlm-distil` | Weekly | Upload discoveries to NLM for Q&A |

#### System Maintenance (8 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `backup-databases` | Daily | Database backups |
| `system-cleanup` | Daily | Chrome caches, HAR files, logs |
| `conversation-evict` | Every 1h | Remove idle conversations |
| `governance-audit` | Weekly | Governance rules audit |
| `copilot-rules-refresh` | Weekly | Copilot rules refresh |
| `copilot-auto-repair` | Daily | Detect and repair Copilot drift |
| `system-reflection` | Weekly | Weekly system reflection |
| `experiment-scan` | Weekly | Experiment proposal scan |

#### Other Tasks

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `npc-world-tick` | Every 1m | NPC world tick |
| `daily-challenge-seed` | Daily | Pre-generate scene challenges |
| `operator-inbox-sync` | Every 15m | Operator inbox sync |
| `task-auto-assign` | Every 5m | Push tasks to available agents |
| `auto-embedding` | Every 4h | Batch-embed new entries to ChromaDB |
| `collect-flush` | Every 4h | DataCollector flush to datasets |
| `cdp-mine` | Daily | CDP log miner for training data |
| `process-monitor-snapshot` | Every 4h | Process snapshot to MetricsDB |
| `git-operation-check` | Every 15m | Check for stalled git operations |
| `stall-detection-sweep` | Every 4h | Scan for stalled processes |
| Additional dynamic tasks | Various | Registered by sub-modules |

#### Gemini Integration (2 tasks)

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `file-search-sync` | Weekly | Sync project docs to Gemini File Search stores |
| `context-cache-refresh` | Every 8h | Refresh Gemini server-side context cache |

---

## 9. Gemini Native Integration

v1.57.0 introduced full Gemini API integration across embeddings, managed RAG,
structured output, and context caching.

### Gemini Embedding 2 Preview

Upgraded from `gemini-embedding-exp-03-07` to `gemini-embedding-2-preview`:

- ChromaDB native `GoogleGenerativeAiEmbeddingFunction` (replaces custom bridge)
- Multimodal `embed_image()` for PNG/JPEG/GIF/WEBP via google.genai SDK
- All 5 API keys confirmed working, round-robin rotation

### Gemini File Search (Managed RAG)

`FileSearchClient` (`engine/nexus/gemini/file_search.py`) provides Gemini managed RAG:

```python
from engine.nexus.gemini.file_search import get_file_search_client

client = get_file_search_client()
store = client.create_store("project-docs")
client.upload_document(store.id, "path/to/doc.md")
results = client.query(store.id, "How does the query router work?")
# Returns grounded citations with source document references
```

- Integrated as QueryRouter **Tier 2.5** between vector search and FTS
- Every File Search answer auto-distilled into Nexus Q&A cache
- `bootstrap_project_stores()` uploads 9 core docs (README, CLAUDE.md, context.md, etc.)
- Q&A cache relevance scoring with 40% word overlap threshold

### Structured Output

`generate_structured()` (`engine/nexus/gemini/structured_output.py`) enforces JSON
schema on Gemini responses:

```python
from engine.nexus.gemini.structured_output import generate_structured

result = generate_structured(
    prompt="Extract Q&A pairs from this text...",
    schema="QA_BATCH",
)
```

6 extraction schemas:

| Schema | Use Case |
|--------|----------|
| `QA_BATCH` | Extract question-answer pairs from text |
| `TASK_DECOMPOSITION` | Break complex tasks into steps |
| `KNOWLEDGE_ENTRY` | Extract structured knowledge entries |
| `AGENT_DECISION` | Structure agent decision reasoning |
| `GROUNDED_ANSWER` | Answer with source citations |

NLM Flywheel, QA Distiller, and Knowledge Forge all prefer structured output over regex parsing.

### Context Caching

`ContextCacheClient` (`engine/nexus/gemini/context_cache.py`) caches large context
documents server-side in Gemini:

```python
from engine.nexus.gemini.context_cache import get_context_cache

cache = get_context_cache()
cache.cache_files(["context.md", "CLAUDE.md"])
```

- Copilot Bridge uses cached context for plan decomposition
- Scheduler task `context-cache-refresh` refreshes every 8h
- Reduces per-request token costs for repeated context

### Oracle Integration

The Oracle dashboard now includes a **GEMINI SERVICES** section:
- File Search store count and document inventory
- Context cache status (TTL, size, last refresh)
- Embedding model health (gemini-embedding-2-preview)

---

## 10. Governance Rules

Governance rules are stored in the `rules` table and enforced via both Nexus server-side
checks and client-side validation in `GovernanceManager`.

### Rule Categories

#### Coding Standards (5 rules, scope=global, type=validation)

| Rule | Severity | What It Enforces |
|------|----------|------------------|
| `absolute-imports` | reject | No relative imports (`from .` forbidden) |
| `type-hints-required` | warn | Functions need type annotations |
| `no-print` | reject | Use logger, not print() |
| `logger-required` | warn | Modules need `logger = logging.getLogger(__name__)` |
| `google-docstrings` | warn | Public functions need Google-style docstrings |
| `future-annotations` | warn | `from __future__ import annotations` required |

#### Testing Standards (4 rules, scope=global, type=quality_gate)

| Rule | Severity | What It Enforces |
|------|----------|------------------|
| `tests-required` | block | New modules must have a test file |
| `mock-external` | warn | Tests importing HTTP libs need mocks |
| `no-unittest` | warn | Use pytest, not unittest.TestCase |
| `min-test-count` | warn | At least 3 test functions per test file |

#### Nexus Workflow (3 rules, scope=global, type=auto_action)

| Rule | Trigger | Reminder |
|------|---------|----------|
| `nexus-first` | editing_code | Search Nexus before editing |
| `store-decisions` | architecture_decision | Store decisions in Nexus |
| `post-session-log` | session_ending | Log session to Nexus |

#### Agent Permissions (3 rules, scope=agent:*, type=access)

| Rule | Condition | Access Level |
|------|-----------|-------------|
| `router-read-only` | Model < 1B params | read only |
| `worker-limited-scope` | Model 1-10B params | read + write (assigned files) |
| `expert-full-access` | Model >= 10B or copilot | full access |

### Enforcement

Rules are enforced at two levels:
1. **Client-side** — `_check_governance()` in NexusClient runs before every mutation
2. **Server-side** — Nexus API validates against stored rules

The `@governed` decorator can be applied to any function for active enforcement:

```python
from engine.nexus.governance_rules import governed

@governed(operation="write", scope="global")
def store_knowledge(title: str, content: str) -> str:
    # Only runs if the calling agent has write permission
    ...
```

---

## 11. Configuration

All Nexus-related configuration is in `config/default.yaml`.

### Core Nexus Settings

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
```

### Embedding Settings

```yaml
  embeddings:
    enabled: true
    provider: "auto"                  # gemini | local | auto
    model: "gemini-embedding-001"
    dimensions: 768                   # MRL: 768 / 1536 / 3072
    local_model: "text-embedding-nomic-embed-text-v1.5"
    cache_size: 10000
    batch_size: 100
    auto_embed: true
```

### Vector Store Settings

```yaml
  vector_store:
    enabled: true
    persist_dir: "data/nexus_vectors"
    default_top_k: 5
    min_score: 0.5
```

### Agent Cache (Nexus-First Inference)

```yaml
  agent_cache:
    enabled: true                    # Master toggle for Nexus-first agent inference
    min_confidence: 0.75             # Minimum confidence to accept a Nexus answer
    skip_tool_calls: true            # Skip Nexus check when request has tool integrations
```

### NotebookLM Settings

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

### Interceptor Flags

```yaml
comms:
  interceptors:
    nexus_prompt: true               # Inject Nexus knowledge/rules into agent context
    nexus_context_injector: true     # Inject search results before each LLM call
```

---

## 12. API Quick Reference

All endpoints are on `http://localhost:8700` unless noted otherwise.

### Knowledge Entries

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/search?q=...&limit=N` | Full-text search |
| `POST` | `/api/entries` | Create entry |
| `GET` | `/api/entries/{id}` | Get entry by ID |
| `PUT` | `/api/entries/{id}` | Update entry |
| `DELETE` | `/api/entries/{id}` | Delete entry |
| `GET` | `/api/entries?type=X&category=Y&limit=N` | List entries |
| `GET` | `/api/entries/by-type/{type}?limit=N` | List by type |
| `POST` | `/api/entries/{id}/annotate` | Annotate (access tracking) |
| `POST` | `/api/batch` | Batch create entries |

### Agent Registry

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/agents/register` | Register agent |
| `GET` | `/api/agents/{id}` | Get agent details |
| `GET` | `/api/agents` | List agents |
| `PUT` | `/api/agents/{id}` | Update agent |
| `DELETE` | `/api/agents/{id}` | Remove agent |
| `POST` | `/api/agent/submit` | Agent knowledge submission |

### Q&A Cache

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/qa/ask?q=...&limit=N` | Search Q&A pairs |
| `POST` | `/api/qa` | Store Q&A pair |
| `POST` | `/api/research/ask` | Smart Q&A (cache→FTS→NLM) |

### Research Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/research/deep` | Start deep research |
| `POST` | `/api/research/{id}/converse` | Continue conversation |
| `POST` | `/api/research/{id}/finish` | Complete and distill |
| `GET` | `/api/research?status=X&limit=N` | List sessions |

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/sessions` | Create session |
| `PUT` | `/api/sessions/{id}` | Update session |
| `GET` | `/api/sessions/{id}` | Get session |
| `GET` | `/api/sessions?project=X&limit=N` | List sessions |

### Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/rules?scope=X&type=Y` | Get rules |
| `POST` | `/api/rules` | Create rule |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/stats` | Database statistics |
| `POST` | `/api/import/youtube` | Import YouTube transcript |
| `GET` | `/api/plugins?scope=X` | List plugins |
| `POST` | `/api/plugins` | Register plugin |

### NotebookLM Proxy (port 8700)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/nlm/ask` | Ask via HTTP backend |
| `POST` | `/api/nlm/unified/ask` | Ask via best backend |
| `GET` | `/api/nlm/status` | NLM backend status |
| `GET` | `/api/nlm/notebooks` | List NLM notebooks |
| `POST` | `/api/nlm/sync` | Sync NLM data |

---

## 13. MCP Tools

### Nexus Skills (17 skills, pack="nexus")

| Skill | Description |
|-------|-------------|
| `nexus_search` | Full-text search across knowledge base |
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
| `nexus_smart_query` | Smart query with 6-tier routing |
| `nexus_flywheel_stats` | Get flywheel metrics |

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

### NotebookLM Skills (5 skills, pack="notebooklm")

| Skill | Description |
|-------|-------------|
| `notebooklm_ask` | Ask question with citations |
| `notebooklm_add_source` | Add URL/text/PDF/YouTube source |
| `notebooklm_generate_audio` | Generate podcast Audio Overview |
| `notebooklm_list_notebooks` | List all notebooks |
| `notebooklm_search` | Search across notebooks |

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

## 14. CLI Reference

### Nexus Bridge CLI

```bash
# Search
python -m engine.nexus.bridge search "interceptor pipeline"
python -m engine.nexus.bridge search "state management" --limit 20

# Smart Q&A
python -m engine.nexus.bridge ask "How does the query router work?"
python -m engine.nexus.bridge ask "What is the interceptor pipeline?" --depth deep

# Store knowledge
python -m engine.nexus.bridge store "Decision: Use FTS5" "Chose FTS5 because..."
python -m engine.nexus.bridge store "Code Pattern" "def helper()..." --type code --category patterns

# Q&A pairs
python -m engine.nexus.bridge qa "How does X work?" "X works by..."
python -m engine.nexus.bridge qa "What is Y?" "Y is..." --category architecture

# Backfill external discoveries
python -m engine.nexus.bridge backfill "How does X?" "X works by..." --source docs

# System inventory
python -m engine.nexus.bridge inventory --store
python -m engine.nexus.bridge inventory --format text

# Governance rules
python -m engine.nexus.bridge rules
python -m engine.nexus.bridge rules global

# Health check
python -m engine.nexus.bridge health

# Seed knowledge
python -m engine.nexus.bridge seed all
python -m engine.nexus.bridge seed docs
python -m engine.nexus.bridge seed qa

# Maintenance
python -m engine.nexus.bridge maintain health
python -m engine.nexus.bridge maintain dedup
python -m engine.nexus.bridge maintain cleanup

# News
python -m engine.nexus.bridge news-fetch --category ai_ml --store --max 20
python -m engine.nexus.bridge news-digest --category ai_ml
python -m engine.nexus.bridge news-sources
```

### Oracle Integration

```bash
# Full system diagnostic (includes Nexus health)
python scripts/oracle.py

# Nexus-specific checks
python scripts/oracle.py --health    # Service health grid (includes Nexus)
python scripts/oracle.py --errors    # Top errors (Nexus errors are tagged)
```

### Scheduler CLI

```bash
# Status of all tasks
python -m engine.nexus.scheduler_daemon status

# Run a specific task
python -m engine.nexus.scheduler_daemon run nexus-maintenance

# Start the daemon loop
python -m engine.nexus.scheduler_daemon start
```

### NLM CLI

```bash
# NLM operations
python -m engine.nexus.nlm_cli list-notebooks
python -m engine.nexus.nlm_cli ask "What is X?" --notebook <id>
```

---

## Key File Paths

| File | Purpose |
|------|---------|
| `engine/nexus/client.py` | NexusClient — HTTP client (singleton via `get_nexus_client()`) |
| `engine/nexus/query_router.py` | NexusQueryRouter — 6-tier query pipeline |
| `engine/nexus/knowledge_pipeline.py` | KnowledgePipeline — unified ingestion |
| `engine/nexus/vector_store.py` | NexusVectorStore — ChromaDB semantic search |
| `engine/nexus/embedding_service.py` | EmbeddingService — Gemini Embedding 2 Preview + local |
| `engine/nexus/governance_rules.py` | GovernanceManager — rules + AGENT_TYPES |
| `engine/nexus/nexus_namespaces.py` | Namespace definitions and enforcement |
| `engine/nexus/scheduler_daemon.py` | TaskSchedulerDaemon — 89 recurring tasks |
| `engine/nexus/training_flywheel.py` | TrainingFlywheel — auto training data |
| `engine/nexus/qa_generator.py` | QA Generator — rule-based + LLM modes |
| `engine/nexus/qa_expander.py` | QA Expander — reverse Q&A from entries |
| `engine/nexus/bridge.py` | CLI bridge for direct Nexus access |
| `engine/nexus/models.py` | Pydantic v2 domain models |
| `engine/nexus/knowledge_capture.py` | Dual-write backfill helper |
| `engine/nexus/notebooklm_flywheel.py` | Control notebook flywheel |
| `engine/nexus/nlm_chain.py` | Multi-step NLM chain prompting |
| `engine/nexus/bootstrap_notebooks.py` | NLM notebook fleet management |
| `engine/skills/builtin/nexus_skills.py` | 17 Nexus MCP skills |
| `config/default.yaml` | Nexus configuration (source of truth) |
| `C:\Files\Nexus` | Nexus server installation directory |

---

## Change Log

```
v1.57.0 [2026-03-26] — Gemini Native: 7-tier query pipeline (+ File Search at Tier 2.5),
                        Gemini integration section (File Search, structured output, context
                        caching, Embedding 2 Preview), 91 scheduler tasks (+2 Gemini),
                        Oracle Gemini Services section, renumbered sections 9-14.
v1.56.0 [2026-03-26] — Initial creation: comprehensive deep-dive document covering
                        architecture, query pipeline, agent registry, knowledge pipeline,
                        NLM integration, self-improvement loop, 89 scheduler tasks,
                        governance rules, configuration, API reference, MCP tools, and CLI.
```
