# Nexus KMS API Reference

> v1.56.0 [2026-03-26] — Complete endpoint reference for agents and developers.

---

## Python Client API

Access the Nexus client singleton:

```python
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
```

The client is configured via `config/default.yaml` under `nexus.base_url` (default
`http://localhost:8700`). All methods include retry logic (2 retries with exponential
backoff) and governance checks on mutating operations.

### Knowledge Entry Methods

#### `search(query: str, limit: int = 10) -> List[NexusEntry]`

Full-text search across all knowledge entries.

```python
results = client.search("interceptor pipeline", limit=10)
for entry in results:
    print(entry.title, entry.content_type, entry.category)
```

#### `add_entry(title, content, content_type="note", category="", tags=None, created_by="cosysim", agent_id="", namespace="") -> Optional[str]`

Create a new knowledge entry. Returns the entry ID or None on failure.
Runs governance check (`write` operation) and namespace validation.
Auto-embeds the entry into the vector store via `embedding_hooks`.

```python
entry_id = client.add_entry(
    title="Decision: Use FTS5 for search",
    content="Chose FTS5 over vector-only search because...",
    content_type="note",
    category="architecture",
    tags=["database", "search"],
)
```

#### `get_entry(entry_id: str) -> Optional[NexusEntry]`

Retrieve a single entry by ID.

```python
entry = client.get_entry("abc-123")
print(entry.title, entry.content)
```

#### `update_entry(entry_id: str, agent_id="", namespace="", **fields) -> bool`

Update fields on an existing entry. Returns True on success.

```python
client.update_entry("abc-123", content="Updated content", category="architecture")
```

#### `delete_entry(entry_id: str, agent_id: str = "") -> bool`

Delete an entry. Requires `delete` permission. Returns True on success.

```python
client.delete_entry("abc-123", agent_id="copilot")
```

#### `list_entries(content_type="", category="", limit=20) -> List[NexusEntry]`

List entries with optional type and category filters.

```python
notes = client.list_entries(content_type="note", category="architecture", limit=50)
```

#### `list_by_type(content_type: str, category="", limit=50) -> List[NexusEntry]`

Shortcut to list entries filtered by content type.

```python
prompts = client.list_by_type("prompt", category="system")
```

#### `batch_add(entries: List[Dict], agent_id="copilot") -> List[str]`

Add multiple entries in one request. Returns list of created IDs.

```python
ids = client.batch_add([
    {"title": "Note 1", "content": "...", "content_type": "note"},
    {"title": "Note 2", "content": "...", "content_type": "code"},
], agent_id="copilot")
```

#### `agent_submit(agent_id, submit_type, title, content, category="", tags=None, importance=0.5) -> Optional[str]`

Agent-specific knowledge submission with importance scoring.

```python
entry_id = client.agent_submit(
    agent_id="scene_agent_lola",
    submit_type="observation",
    title="Player prefers stealth",
    content="Player chose stealth in 3 out of 4 encounters...",
    importance=0.7,
)
```

### Q&A Methods

#### `ask(question: str, depth="auto", category="") -> Dict`

Smart Q&A that routes through cache, knowledge base, then NLM.

```python
result = client.ask("How does the interceptor pipeline work?", depth="auto")
# Returns: {answer, source, confidence, sources, qa_id}
print(result["answer"])
print(result["source"])       # "cache", "fts", "nlm"
print(result["confidence"])   # 0.0-1.0
```

**Depth options:**
- `"shallow"` — cache + FTS only
- `"auto"` — cache + FTS + NLM if needed
- `"deep"` — always query NLM

#### `find_qa(question: str, limit=5) -> List[Dict]`

Search the Q&A cache for existing answers (fuzzy match).

```python
pairs = client.find_qa("interceptor pipeline", limit=5)
for pair in pairs:
    print(pair["question"], pair["answer"][:100])
```

#### `add_qa(question, answer, category="", tags=None, quality_score=0.5, agent_id="", namespace="") -> Optional[str]`

Store a Q&A pair. Auto-embeds into the vector store.

```python
qa_id = client.add_qa(
    "How does state sync work?",
    "State sync uses the MCPFramework singleton...",
    category="architecture",
    quality_score=0.8,
)
```

### Session Methods

#### `log_session(session_id=None, project="", repo="", branch="", agent_id="copilot") -> Optional[str]`

Create a new session record. Returns session ID.

```python
sid = client.log_session(project="CosySim", branch="main", agent_id="copilot")
```

#### `update_session(session_id: str, agent_id="copilot", **fields) -> bool`

Update session fields (summary, commits, files_changed, status).

```python
client.update_session(sid, summary="Implemented query router", status="completed")
```

#### `get_session(session_id: str) -> Optional[Dict]`

Retrieve a session by ID.

#### `list_sessions(project="", status="", limit=50) -> List[Dict]`

List sessions with optional filters.

```python
recent = client.list_sessions(project="CosySim", status="completed", limit=10)
```

### Research Methods

#### `research(question: str, notebook_id="", sources=None) -> Dict`

Start a deep NLM research session.

```python
session = client.research("MCP state management best practices")
research_id = session["research_id"]
```

#### `converse(research_id: str, message: str) -> Dict`

Continue a research conversation.

```python
followup = client.converse(research_id, "What about persistence?")
```

#### `finish_research(research_id: str) -> Dict`

Complete a research session and distill Q&A pairs.

```python
done = client.finish_research(research_id)
```

#### `list_research(status="", limit=20) -> List[Dict]`

List research sessions.

### Rules Methods

#### `get_rules(scope="", rule_type="") -> List[NexusRule]`

Get active rules, optionally filtered.

```python
rules = client.get_rules(scope="global", rule_type="validation")
for rule in rules:
    print(rule.scope, rule.rule_type, rule.condition)
```

#### `add_rule(scope, rule_type, name, condition=None, action=None, priority=50, active=True, agent_id="copilot") -> Optional[str]`

Create a new governance rule. Requires `admin` permission.

```python
rule_id = client.add_rule(
    scope="global",
    rule_type="auto_action",
    name="nexus-first",
    condition={"trigger": "editing_code"},
    action={"severity": "remind", "message": "Search Nexus first"},
)
```

### NotebookLM Methods

#### `nlm_ask(question, notebook_id="", notebook_url="") -> Dict`

Ask via HTTP-only NLM backend.

#### `nlm_unified_ask(question, notebook_id="", notebook_url="") -> Dict`

Ask via best available backend (HTTP, then browser fallback).

```python
result = client.nlm_unified_ask("What are the core components?")
```

#### `nlm_status() -> Dict`

Get status of all NLM backends.

#### `nlm_list_notebooks() -> List[Dict]`

List all NLM notebooks.

#### `nlm_sync(notebook_id="") -> Dict`

Sync NLM data to Nexus.

### Prompt Methods

#### `store_prompt(name, content, category="system", version="1", tags=None) -> Optional[str]`

Store a prompt with version tracking.

```python
pid = client.store_prompt("system-v3", "You are a helpful assistant...", version="3")
```

#### `get_prompts(category="", name="") -> List[Dict]`

Retrieve stored prompts with optional filters.

### System Methods

#### `health() -> Dict`

Health check — returns `{ok, status, ...}`.

#### `stats() -> Dict`

Database statistics — entry counts, Q&A pairs, rules, sessions.

#### `is_available(timeout=5.0) -> bool`

Quick connectivity check. Uses a short timeout (5s, not the default 30s).

```python
if client.is_available():
    results = client.search("topic")
```

### Benchmark Methods

#### `store_benchmark(model, method, metrics, tags=None) -> Optional[str]`

Store model benchmark results.

```python
client.store_benchmark("qwen3-0.6b", "gpu_primary", {
    "tps": 42.5,
    "latency_ms": 180,
    "ttft_ms": 45,
    "memory_mb": 1200,
})
```

#### `get_leaderboard(method="", limit=20) -> List[NexusEntry]`

Retrieve benchmark entries, optionally filtered by method.

### Plugin Methods

#### `list_plugins(scope="", hook_type="") -> List[Dict]`

List registered plugins.

#### `add_plugin(name, hook_type, scope="global", config=None) -> Optional[str]`

Register a new plugin.

### Sub-Client Facades

The NexusClient provides lazy-initialized sub-clients for domain-specific operations:

```python
client.rules.get_rules(scope="global")        # NexusRulesClient
client.sessions.list(project="CosySim")       # NexusSessionClient
client.memory.recall(agent_id="copilot")       # NexusMemoryClient
```

---

## REST API Endpoints

All endpoints are served by the Nexus server on `http://localhost:8700`.
Responses follow the format: `{"ok": true/false, "data": ..., "error": "..."}`.

### Knowledge Entries (9 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `GET` | `/api/search?q={query}&limit={n}` | — | `{data: [entries]}` |
| `POST` | `/api/entries` | `{title, content, content_type, category, tags, created_by}` | `{data: {id}}` |
| `GET` | `/api/entries/{id}` | — | `{data: entry}` |
| `PUT` | `/api/entries/{id}` | `{title?, content?, content_type?, category?, tags?}` | `{ok}` |
| `DELETE` | `/api/entries/{id}` | — | `{ok}` |
| `GET` | `/api/entries?type={t}&category={c}&limit={n}` | — | `{data: [entries]}` |
| `GET` | `/api/entries/by-type/{type}?limit={n}&category={c}` | — | `{data: [entries]}` |
| `POST` | `/api/entries/{id}/annotate` | `{type, data}` | `{ok}` |
| `POST` | `/api/batch` | `{entries: [{title, content, ...}]}` | `{data: {ids: [...]}}` |

### Agent Registry (6 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `POST` | `/api/agents/register` | `{agent_id, display_name, agent_type, tier}` | `{ok}` |
| `GET` | `/api/agents/{id}` | — | `{data: {agent_id, agent_type, tier, allowed_operations}}` |
| `GET` | `/api/agents` | — | `{data: [agents]}` |
| `PUT` | `/api/agents/{id}` | `{display_name?, agent_type?, tier?}` | `{ok}` |
| `DELETE` | `/api/agents/{id}` | — | `{ok}` |
| `POST` | `/api/agent/submit` | `{agent_id, type, title, content, category, tags, importance}` | `{data: {entry_id}}` |

### Q&A Cache (3 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `GET` | `/api/qa/ask?q={question}&limit={n}` | — | `{data: [{question, answer, ...}]}` |
| `POST` | `/api/qa` | `{question, answer, category, tags, quality_score}` | `{data: {id}}` |
| `POST` | `/api/research/ask` | `{question, depth, category}` | `{data: {answer, source, confidence}}` |

### Research Sessions (4 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `POST` | `/api/research/deep` | `{question, notebook_id?, sources?}` | `{data: {research_id, ...}}` |
| `POST` | `/api/research/{id}/converse` | `{message}` | `{data: {answer, ...}}` |
| `POST` | `/api/research/{id}/finish` | `{}` | `{data: {qa_pairs, ...}}` |
| `GET` | `/api/research?status={s}&limit={n}` | — | `{data: [sessions]}` |

### Sessions (4 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `POST` | `/api/sessions` | `{project, repo, branch, agent_id, id?}` | `{data: {id}}` |
| `PUT` | `/api/sessions/{id}` | `{summary?, commits?, status?, ...}` | `{ok}` |
| `GET` | `/api/sessions/{id}` | — | `{data: session}` |
| `GET` | `/api/sessions?project={p}&status={s}&limit={n}` | — | `{data: [sessions]}` |

### Rules (2 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `GET` | `/api/rules?scope={s}&type={t}` | — | `{data: [rules]}` |
| `POST` | `/api/rules` | `{scope, rule_type, name, condition, action, priority}` | `{data: {id}}` |

### NotebookLM Proxy (5 endpoints on port 8700)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `POST` | `/api/nlm/ask` | `{question, notebook_id?, notebook_url?}` | `{data: {answer}}` |
| `POST` | `/api/nlm/unified/ask` | `{question, notebook_id?, notebook_url?}` | `{data: {answer}}` |
| `GET` | `/api/nlm/status` | — | `{data: {backends}}` |
| `GET` | `/api/nlm/notebooks` | — | `{data: [notebooks]}` |
| `POST` | `/api/nlm/sync` | `{notebook_id?}` | `{data: {synced}}` |

### System (5 endpoints)

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| `GET` | `/api/health` | — | `{ok, status}` |
| `GET` | `/api/stats` | — | `{data: {knowledge_entries, qa_pairs, rules, ...}}` |
| `POST` | `/api/import/youtube` | `{url, category, tags}` | `{data: {entry_id, ...}}` |
| `GET` | `/api/plugins?scope={s}&hook_type={t}` | — | `{data: [plugins]}` |
| `POST` | `/api/plugins` | `{name, hook_type, scope, config}` | `{data: {id}}` |

### NLM Live Proxy (port 8800)

The NLM Live Proxy runs on port 8800 and provides direct NotebookLM access:

#### Authentication & Setup

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Status, cookie count, BL age, RPC version |
| `POST` | `/cookies/import` | Import cookies from HAR file |
| `POST` | `/cookies/capture` | Auto-capture cookies via Chrome CDP |
| `POST` | `/cookies/refresh` | Refresh f.sid and at token |
| `GET` | `/cookies` | List stored cookie names |
| `DELETE` | `/cookies` | Clear all cookies |
| `GET` | `/meta` | Current BL and session metadata |
| `POST` | `/meta` | Update BL or f.sid manually |

#### Notebook Operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notebooks` | List all notebooks |
| `POST` | `/notebooks` | Create notebook |
| `GET` | `/notebooks/{id}` | Full notebook data |
| `POST` | `/notebooks/{id}/rename` | Rename notebook |

#### Source Operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notebooks/{id}/sources` | List sources |
| `POST` | `/notebooks/{id}/sources` | Add URL/YouTube source |
| `GET` | `/notebooks/{id}/sources/wait` | Poll source processing |
| `GET` | `/notebooks/{id}/sources/content` | Download source texts |
| `DELETE` | `/sources/{id}` | Delete source |
| `GET` | `/sources/{id}/content` | Read source text |

#### AI Features

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notebooks/{id}/summary` | AI overview |
| `GET` | `/notebooks/{id}/mindmap` | Mind map D3 JSON |
| `POST` | `/notebooks/{id}/ask` | Synchronous Q&A with citations |
| `POST` | `/notebooks/{id}/ask_batch` | Batch up to 5 questions |
| `POST` | `/notebooks/{id}/chat` | Streaming multi-turn chat |

#### Research Workflow

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/notebooks/{id}/research` | Start fast research |
| `POST` | `/notebooks/{id}/research/deep` | Start deep research |
| `POST` | `/notebooks/{id}/research/source` | Add AI research doc as source |

#### Archive & Export

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notebooks/{id}/archive` | Full notebook archive |
| `GET` | `/notebooks/archive` | Export all notebooks |
| `GET` | `/sources/{id}/export` | Single source as text file |

#### User & Rate Limiting

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/user/profile?notebook_id={id}` | Profile + queries remaining |
| `GET` | `/user/quota` | Account quota and plan tier |
| `GET` | `/rate_limit` | Current rate limit |
| `POST` | `/rate_limit` | Override rate limit (0.5-30.0s) |
| `POST` | `/rpc/{rpc_id}` | Call any RPC directly |

---

## MCP Tools

All MCP tools are registered via the `@skill` decorator and are available to agents
during the interceptor pipeline.

### Nexus Skills (pack="nexus")

| Tool | Parameters | Returns |
|------|-----------|---------|
| `nexus_search` | `query: str, limit: int = 10` | JSON list of matching entries |
| `nexus_add` | `title: str, content: str, content_type: str = "note", category: str = ""` | `{ok, entry_id}` |
| `nexus_ask` | `question: str, depth: str = "auto", category: str = ""` | `{answer, source, confidence}` |
| `nexus_nlm_ask` | `question: str, notebook_id: str = "", notebook_url: str = ""` | NLM response dict |
| `nexus_status` | — | `{stats, nlm_backends}` |
| `nexus_log_session` | `project: str = "CosySim", repo: str = "", branch: str = "", summary: str = ""` | `{ok, session_id}` |
| `nexus_store_prompt` | `name: str, content: str, category: str = "system", version: str = "1"` | `{ok, entry_id}` |
| `nexus_search_prompts` | `name: str = "", category: str = ""` | JSON list of prompt entries |
| `nexus_get_rules` | `scope: str = "global", rule_type: str = ""` | JSON list of rules |
| `nexus_submit_idea` | `title: str, description: str, category: str = "improvement"` | `{ok, entry_id}` |
| `nexus_changelog` | `version: str = "", limit: int = 10` | JSON list of changelog entries |
| `nexus_research` | `question: str, notebook_id: str = ""` | `{research_id, ...}` |
| `nexus_converse` | `research_id: str, message: str` | `{answer, ...}` |
| `nexus_finish_research` | `research_id: str` | `{qa_pairs, ...}` |
| `nexus_youtube` | `url: str, category: str = "youtube"` | `{entry_id, ...}` |
| `nexus_smart_query` | `question: str, min_confidence: float = 0.3` | `{answer, source, confidence, tokens_saved}` |
| `nexus_flywheel_stats` | — | `{router, training, scheduler, nexus}` |

### Coding Skills (pack="coding")

| Tool | Parameters | Returns |
|------|-----------|---------|
| `coding_store_snippet` | `title: str, code: str, language: str = "", category: str = ""` | `{ok, entry_id}` |
| `coding_search` | `query: str, limit: int = 10` | JSON list of entries |
| `coding_store_decision` | `title: str, content: str, category: str = "architecture"` | `{ok, entry_id}` |
| `coding_log_session` | `summary: str, project: str = "CosySim"` | `{ok, session_id}` |
| `coding_research` | `topic: str, depth: str = "auto"` | `{answer, sources}` |
| `coding_store_bug` | `title: str, content: str` | `{ok, entry_id}` |
| `coding_store_test_pattern` | `title: str, content: str` | `{ok, entry_id}` |
| `coding_project_status` | `project: str = "CosySim"` | Status dict |
| `coding_search_qa` | `question: str, limit: int = 5` | JSON list of Q&A pairs |

---

## Query Router API

The query router is the preferred entry point for all information retrieval.

### Access

```python
from engine.nexus.query_router import get_query_router
router = get_query_router()
```

### `query(question, min_confidence=0.3, use_llm=True, category="", tags=None, source_hint="system", depth="auto", agent_id=None) -> QueryResult`

Route a query through the 6-tier Nexus-first pipeline.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `question` | `str` | required | The question to answer |
| `min_confidence` | `float` | `0.3` | Minimum confidence to accept |
| `use_llm` | `bool` | `True` | Enable LLM fallback (tier 6) |
| `category` | `str` | `""` | Category filter for search |
| `tags` | `List[str]` | `None` | Tags for stored answers |
| `source_hint` | `str` | `"system"` | Who is asking |
| `depth` | `str` | `"auto"` | shallow, auto, deep |
| `agent_id` | `str` | `None` | Agent ID for per-agent tracking |

**Returns `QueryResult`:**

| Field | Type | Description |
|-------|------|-------------|
| `answer` | `str` | The answer text |
| `source` | `str` | Tier: `cache`, `vector`, `search`, `nexus-*`, `nlm*`, `llm`, `none` |
| `confidence` | `float` | 0.0-1.0 confidence score |
| `cached` | `bool` | Whether served from cache |
| `tokens_saved` | `int` | Estimated tokens saved vs LLM |
| `query_time_ms` | `float` | Total query time |
| `sources` | `List[str]` | Contributing source references |
| `metadata` | `Dict` | Additional metadata |

**Example:**

```python
result = router.query(
    "How does the interceptor pipeline work?",
    min_confidence=0.5,
    use_llm=True,
    agent_id="copilot",
)
print(result.answer)        # "The interceptor pipeline..."
print(result.source)        # "cache"
print(result.confidence)    # 0.90
print(result.tokens_saved)  # 450
```

### `stats` property -> `RouterStats`

Cumulative router statistics.

```python
stats = router.stats
print(stats.total_queries)       # 142
print(stats.cache_hits)          # 98
print(stats.hit_rate())          # 0.915
print(stats.total_tokens_saved)  # 45000
```

---

## Knowledge Pipeline API

Unified ingestion for all knowledge sources.

### Access

```python
from engine.nexus.knowledge_pipeline import get_knowledge_pipeline
pipeline = get_knowledge_pipeline()
```

### `ingest(title, content, content_type="note", category="general", tags=None, agent_id="system", auto_qa=True, auto_embed=True, source="") -> PipelineResult`

Single entry point for ALL knowledge ingestion.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str` | required | Human-readable title |
| `content` | `str` | required | Knowledge content body (min 20 chars) |
| `content_type` | `str` | `"note"` | Nexus content type |
| `category` | `str` | `"general"` | Category for routing/filtering |
| `tags` | `List[str]` | `None` | String tags |
| `agent_id` | `str` | `"system"` | Originating agent |
| `auto_qa` | `bool` | `True` | Auto-generate Q&A pairs |
| `auto_embed` | `bool` | `True` | Auto-embed in vector store |
| `source` | `str` | `""` | Source identifier |

**Returns `PipelineResult`:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Whether ingestion succeeded |
| `entry_id` | `str` | Created entry ID |
| `qa_pairs_generated` | `int` | Number of Q&A pairs created |
| `was_duplicate` | `bool` | Whether content was a duplicate |
| `quality_score` | `float` | Heuristic quality score |
| `embedded` | `bool` | Whether vector embedding succeeded |
| `subscribers_notified` | `int` | Subscribers notified |
| `error` | `str` | Error message if failed |
| `duration_ms` | `float` | Pipeline duration |

---

## Configuration Reference

All keys are accessed via `get_config().get("dotted.path", default)`.

### Nexus Core

| Key | Default | Description |
|-----|---------|-------------|
| `nexus.enabled` | `true` | Master enable for Nexus integration |
| `nexus.base_url` | `"http://localhost:8700"` | Nexus server URL |
| `nexus.auto_submit` | `false` | Auto-submit agent observations |
| `nexus.knowledge_expiry.default_max_age_days` | `90` | Default entry TTL |
| `nexus.knowledge_expiry.stale_threshold` | `0.2` | Staleness quality threshold |

### Embeddings

| Key | Default | Description |
|-----|---------|-------------|
| `nexus.embeddings.enabled` | `true` | Enable embedding service |
| `nexus.embeddings.provider` | `"auto"` | `gemini`, `local`, or `auto` |
| `nexus.embeddings.model` | `"gemini-embedding-001"` | Gemini model name |
| `nexus.embeddings.dimensions` | `768` | MRL dimensions (768/1536/3072) |
| `nexus.embeddings.local_model` | `"text-embedding-nomic-embed-text-v1.5"` | LMStudio fallback model |
| `nexus.embeddings.cache_size` | `10000` | In-memory embedding cache size |
| `nexus.embeddings.batch_size` | `100` | Batch embedding size |
| `nexus.embeddings.auto_embed` | `true` | Auto-embed new entries |

### Vector Store

| Key | Default | Description |
|-----|---------|-------------|
| `nexus.vector_store.enabled` | `true` | Enable ChromaDB vector store |
| `nexus.vector_store.persist_dir` | `"data/nexus_vectors"` | ChromaDB persistence directory |
| `nexus.vector_store.default_top_k` | `5` | Default results per search |
| `nexus.vector_store.min_score` | `0.5` | Minimum similarity score |

### Agent Cache

| Key | Default | Description |
|-----|---------|-------------|
| `nexus.agent_cache.enabled` | `true` | Nexus-first agent inference toggle |
| `nexus.agent_cache.min_confidence` | `0.75` | Min confidence to accept cached answer |
| `nexus.agent_cache.skip_tool_calls` | `true` | Skip cache when tools involved |

### Query Router

| Key | Default | Description |
|-----|---------|-------------|
| `nexus.query_router.cache_confidence` | `0.90` | Q&A cache hit confidence |
| `nexus.query_router.vector_confidence` | `0.82` | Vector search confidence |
| `nexus.query_router.search_high` | `0.75` | Strong FTS match confidence |
| `nexus.query_router.search_medium` | `0.50` | Decent FTS match confidence |
| `nexus.query_router.search_low` | `0.30` | Weak FTS match confidence |
| `nexus.query_router.min_answer_length` | `20` | Min chars for valid answer |
| `nexus.query_router.local_cache_ttl` | `300` | Session cache TTL (seconds) |

### NotebookLM

| Key | Default | Description |
|-----|---------|-------------|
| `notebooklm.enabled` | `true` | Enable NLM integration |
| `notebooklm.proxy_url` | `"http://localhost:8800"` | NLM proxy URL |
| `notebooklm.timeout` | `120` | Request timeout (seconds) |
| `notebooklm.rate_limit_seconds` | `1.5` | Min gap between requests |
| `notebooklm.flywheel.enabled` | `true` | Enable control flywheel |
| `notebooklm.flywheel.min_interval_hours` | `8` | Minimum flywheel interval |
| `notebooklm.flywheel.max_tasks` | `6` | Max tasks per flywheel run |

### Interceptors

| Key | Default | Description |
|-----|---------|-------------|
| `comms.interceptors.nexus_prompt` | `true` | Inject Nexus knowledge into agent context |
| `comms.interceptors.nexus_context_injector` | `true` | Inject search results before LLM calls |
| `nexus.nexus_cache_enabled` | `true` | Enable Nexus cache in phone panel |

---

## Authentication

### Agent Registration

Agents self-register with Nexus via the `/api/agents/register` endpoint:

```python
client._post("/api/agents/register", {
    "agent_id": "my_agent",
    "display_name": "My Custom Agent",
    "agent_type": "worker",       # copilot | scene_agent | scheduler | training | observer | player | system
    "tier": "worker",             # readonly | worker | expert | system | admin
})
```

### Access Control Flow

1. Agent calls a mutating method (e.g., `add_entry`)
2. `_check_governance()` resolves the actor identity
3. Registry check: query `/api/agents/{id}` for `allowed_operations`
4. If registry unavailable: fall back to `AGENT_TYPES` heuristic
5. If denied: raise `PermissionError`

### Tier Permissions

| Tier | read | write | delete | admin |
|------|------|-------|--------|-------|
| `readonly` | yes | -- | -- | -- |
| `worker` | yes | yes | -- | -- |
| `expert` | yes | yes | yes | yes |
| `system` | yes | yes | -- | yes |
| `admin` | yes | yes | yes | yes |

### Trusted Actor Prefixes

Actors whose `created_by` starts with these prefixes are automatically trusted:

```
copilot, nexus, session, research, content, workflow, benchmark,
api, system, filesystem, oracle, scheduler, training
```

---

## Data Models

All domain models are in `engine/nexus/models.py` using Pydantic v2.

### NexusEntry

```python
class NexusEntry(BaseModel):
    id: str
    title: str
    content: str
    content_type: str = "note"
    category: str = ""
    tags: List[str] = []
    created_by: str = "cosysim"
    created_at: datetime
    updated_at: Optional[datetime]
```

Supports dict-style access: `entry.get("title")`, `entry["content"]`.

### NexusEntryCreate

```python
class NexusEntryCreate(BaseModel):
    title: str
    content: str
    content_type: str = "note"
    category: str = ""
    tags: List[str] = []
    created_by: str = "cosysim"
```

### NexusRule

```python
class NexusRule(BaseModel):
    rule_id: str
    scope: str
    rule_type: str
    condition: Dict[str, Any] = {}
    action: Dict[str, Any] = {}
    active: bool = True
```

### AgentMemory

```python
class AgentMemory(BaseModel):
    agent_id: str
    memory_type: str = "observation"
    importance: float = 0.5       # 0.0-1.0
    content: str
    tags: List[str] = []
    timestamp: datetime
```

---

## Change Log

```
v1.56.0 [2026-03-26] — Initial creation: complete API reference covering Python client,
                        REST endpoints, MCP tools, query router, knowledge pipeline,
                        configuration, authentication, and data models.
```
