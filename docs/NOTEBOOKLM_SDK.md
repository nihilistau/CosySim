# NotebookLM SDK — Complete Protocol Documentation

> **Version:** 2.0 (based on HAR analysis of `notebooklm.google.com3.har`, 2026-02-26)
> **Status:** Production implementation in `engine/mcp/nlm_live_proxy.py`

---

## Overview

NotebookLM uses Google's **batchexecute** RPC transport — the same protocol
used across Google Search, Docs, and other G-Suite products. All API calls
go to a single endpoint via HTTP POST, with RPC functions identified by
short 5–7 character IDs.

**Key insight:** This API is stateless (after auth). Every call is self-contained
and returns full structured data. No WebSocket, no streaming, no session state
beyond auth cookies.

---

## Authentication

### Required Headers

Every batchexecute request needs:

```http
POST /_/LabsTailwindUi/data/batchexecute HTTP/1.1
Host: notebooklm.google.com
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
Origin: https://notebooklm.google.com
Referer: https://notebooklm.google.com/
X-Same-Domain: 1
Cookie: SID=...; SSID=...; APISID=...; SAPISID=...; __Secure-1PSID=...
Authorization: SAPISIDHASH <timestamp>_<sha1>
```

### SAPISIDHASH Computation

```python
import hashlib, time

def compute_sapisidhash(sapisid: str) -> str:
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} https://notebooklm.google.com"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"
```

### Cookie Acquisition

Two methods:

**1. Chrome CDP (Automated — Recommended)**
```python
from engine.nexus.nlm_har_capture import capture_nlm_cookies
result = capture_nlm_cookies()
# Requires websocket-client: pip install websocket-client
# Launch Chrome: chrome.exe --remote-debugging-port=9222 --user-data-dir=...
```

**2. Manual HAR Export**
1. Open Chrome DevTools (F12) → Network tab
2. Visit `https://notebooklm.google.com`
3. Interact with a notebook
4. Right-click any request → "Save all as HAR with content"
5. Call `POST http://localhost:8800/cookies/import` with the HAR path

> **Note:** Chrome 130+ may redact cookies from HAR exports. If cookies are
> missing, use CDP capture instead.

---

## Endpoint

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
```

### URL Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `rpcids` | Yes | Semicolon-separated RPC ID(s) |
| `source-path` | Yes | `/notebook/<notebook_id>` |
| `bl` | Yes | Build label (changes periodically) |
| `f.sid` | Yes | Session ID (extract from page load) |
| `hl` | No | Language code, default `en` |
| `_reqid` | No | Incrementing request counter |
| `rt` | No | Response type, always `c` |

**Current build label:** `boq_labs-tailwind-frontend_20260226.08_p0`
*(Updated automatically when importing a fresh HAR)*

### Request Body

```
f.req=<url_encoded_json>
```

Where the JSON is a list of RPC call tuples:
```json
[
  ["RPC_ID", "{\"escaped\":\"json_args\"}", null, "generic"]
]
```

### Response Format

The response uses a 5-layer decode:

1. Strip XSSI prefix: `)]}'\n`
2. Split by newlines
3. Find lines starting with `[["wrb.fr","RPC_ID",`
4. `outer[0][2]` = inner JSON string
5. Parse inner JSON for actual data

Multi-call responses contain multiple `wrb.fr` lines, one per call.

---

## RPC Catalogue

### READ Operations

#### `ub2Bae` — List All Notebooks

```python
args = "[[2]]"
# Returns: list of notebooks in the account
# Response structure: [[notebook_list], ...]
```

**Returns:** Array of notebook objects with id, name, created_at, source_count.

---

#### `wXbhsf` — List Sources

```python
args = json.dumps([None, 1, None, [2]])
# Returns: sources for the current notebook
# Response: [[notebook_name, [source_list]], ...]
```

**Source object:**
```json
{
  "id": "uuid-v4",
  "title": "Source Title",
  "url": "https://...",
  "word_count": 1500,
  "source_type": 1
}
```

---

#### `VfAZjd` — Get AI Summary / Study Guide

```python
args = json.dumps([notebook_id, [2]])
# Returns: AI-generated summary and study guide
```

---

#### `e3bVqc` — Get Full Source Content

```python
args = json.dumps([None, None, notebook_id])
# Returns: full text content of all sources
```

---

#### `gArtLc` — List Notes / Artifacts

```python
args = json.dumps([
    [2], notebook_id,
    "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""
])
# Returns: list of user-created notes and generated artifacts
```

---

#### `cFji9` — Get Conversation History

```python
args = json.dumps([notebook_id, None, None, [2]])
# Returns: full conversation thread with Q&A pairs
```

**Response structure:** Array of conversation turns:
```json
[
  {"role": "user", "text": "Question?"},
  {"role": "assistant", "text": "Answer with citations [source-id]"}
]
```

---

### WRITE Operations

#### `CYK0Xb` — Ask Question ⭐ (Most Important)

```python
args = json.dumps([notebook_id, "What is the main argument?"])
# Returns: [[answer_id, markdown_answer_with_citations], ...]
```

**Answer format:**
- Markdown text with inline citations like `[source-id]`
- `answer_id` is a UUID for referencing in follow-up operations
- Response is typically 200-800 words with 2-8 citations

**Multi-question batch (single HTTP request):**
```python
f_req = json.dumps([
    ["CYK0Xb", json.dumps([notebook_id, "Question 1?"]), None, "generic"],
    ["CYK0Xb", json.dumps([notebook_id, "Question 2?"]), None, "generic"],
    ["CYK0Xb", json.dumps([notebook_id, "Question 3?"]), None, "generic"],
])
# URL: ?rpcids=CYK0Xb;CYK0Xb;CYK0Xb
# Returns 3 separate wrb.fr blocks in the response
```

**Maximum batch size:** 5 questions per HTTP request (tested up to 3 in HAR, 5 seems stable).

---

#### `ciyUvf` — Generate Document / Deep Research

```python
config = [2, None, None,
          [1, None, None, None, None, None, None, None, None, None, [1]],
          [[2, 1]]]
source_array = [[src_id] for src_id in source_ids]
args = json.dumps([config, notebook_id, source_array])
# Returns: [[title, description, null, [[source_ids]]], ...]
```

**Document types:**
- `doc_type=2`: Standard implementation strategy document
- `doc_type=9`: Deep research report

**Example response:**
```json
[["Implementation Strategy",
  "A comprehensive analysis of deployment pathways...",
  null,
  [["source-uuid-1"], ["source-uuid-2"]]]]
```

---

#### `R7cb6c` — Create / Save Note

```python
config = [2, None, None,
          [1, None, None, None, None, None, None, None, None, None, [1]],
          [[2, 1]]]
source_array = [[src_id] for src_id in source_ids]
note_body = [None, None, note_type, source_array]
args = json.dumps([config, notebook_id, note_body])
# Returns: [[note_id, title, note_type_int, [[source_ids]]], ...]
```

**Note types:**
- `2`: Standard note/summary
- `9`: Deep research artifact

**Example response:**
```json
[["674b1362-9653-4b52-8193-a17dfd89a08f",
  "Modern AI Infrastructure: Local Inference, Agents, and Optimization",
  2,
  [["source-uuid-1"], ["source-uuid-2"]]]]
```

---

## CosySim REST API (nlm_live_proxy.py)

The proxy runs at `http://localhost:8800` and exposes these endpoints:

### Cookie Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service status + cookie status |
| GET | `/cookies` | List stored cookie names |
| DELETE | `/cookies` | Clear all stored cookies |
| POST | `/cookies/import` | Import cookies from HAR file |
| POST | `/cookies/capture` | Auto-capture via Chrome CDP |
| GET | `/meta` | Get bl and f.sid values |
| POST | `/meta` | Manually update bl/f.sid |

### Read Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/notebooks` | List all notebooks |
| GET | `/notebooks/<id>` | Full notebook data |
| GET | `/notebooks/<id>/sources` | List sources |
| GET | `/notebooks/<id>/summary` | AI summary |
| GET | `/notebooks/<id>/notes` | List notes |
| GET | `/notebooks/<id>/conversations` | Conversation history |
| GET | `/notebooks/<id>/content` | Source full text |

### Write Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/notebooks/<id>/ask` | Ask single question |
| POST | `/notebooks/<id>/ask_batch` | Ask multiple questions (batched) |
| POST | `/notebooks/<id>/generate` | Generate document |
| POST | `/notebooks/<id>/save_note` | Save note artifact |
| POST | `/rpc/<rpc_id>` | Raw RPC passthrough |

### Example: Ask a Question

```bash
curl -X POST http://localhost:8800/notebooks/de7fee37-1c07-406f-85ec-108c530dc3ea/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "What are the key benefits of multi-token prediction?"}'
```

Response:
```json
{
  "answer_id": "d4e015e3-b6f0-4deb-9abc-123",
  "answer": "Multi-token prediction (MTP) provides several benefits...\n\nCited from [source-uuid]",
  "sources": ["ec27acaf-72f5-47a6-9c7d-629725a17927"]
}
```

### Example: Batch Ask (Most Efficient)

```bash
curl -X POST http://localhost:8800/notebooks/de7fee37.../ask_batch \
     -H "Content-Type: application/json" \
     -d '{
       "questions": [
         "What is the main architecture of the system?",
         "How does the interceptor pipeline work?",
         "What are the key failure modes?",
         "What optimizations are recommended?",
         "How should agents be structured?"
       ]
     }'
```

Response:
```json
{
  "answers": [
    {"answer_id": "...", "answer": "...", "sources": ["..."]},
    {"answer_id": "...", "answer": "...", "sources": ["..."]},
    ...
  ],
  "count": 5,
  "questions": ["..."]
}
```

---

## CosySim Python API

```python
from engine.mcp.notebooklm_proxy import NotebookLMProxy

proxy = NotebookLMProxy()

# Check if proxy is running
if proxy.is_running():
    # List notebooks
    notebooks = proxy.list_notebooks()

    # Ask a question
    result = proxy.ask_question("notebook-id", "What is the main topic?")
    print(result["answer"])

    # Batch ask (efficient — 1 HTTP request per 5 questions)
    results = proxy.batch_ask("notebook-id", [
        "What are the key components?",
        "How does authentication work?",
        "What are the performance characteristics?",
    ])
    for q, r in zip(questions, results):
        print(f"Q: {q}\nA: {r['answer'][:200]}\n")

    # Generate a document
    doc = proxy.generate_document("notebook-id", source_ids=["uuid1", "uuid2"])
    print(f"Generated: {doc['title']}")

    # Save a note
    note = proxy.save_note("notebook-id", source_ids=["uuid1"])
    print(f"Saved note: {note['note_id']}")
```

---

## NLM Skills (MCP Tools)

Available via `engine/skills/builtin/autonomy_skills.py`:

| Skill | Description |
|-------|-------------|
| `nlm_ask` | Ask a question to a notebook |
| `nlm_batch_ask` | Batch ask multiple questions |
| `nlm_create_notebook` | Create a new research notebook |
| `nlm_add_source` | Add a URL/file as a source |
| `nlm_generate_doc` | Generate a document from sources |
| `nlm_save_note` | Save a note artifact |
| `nlm_list_notebooks` | List all notebooks |
| `nlm_distill` | Full distillation pipeline |
| `nlm_decompose` | Break task into subtasks |

---

## Strategies for Maximum Effectiveness

### Strategy 1: Deliberate Question Batching

Design question sets that cover a topic from multiple angles. Ask 5 at once:

```python
questions = [
    # Understanding questions
    "What is the core architecture and how do the main components interact?",
    # Problem questions
    "What are the main failure modes and edge cases to handle?",
    # Implementation questions
    "What is the recommended implementation approach and why?",
    # Quality questions
    "What are the key quality metrics and how should they be measured?",
    # Future questions
    "What improvements would have the highest impact?",
]
results = proxy.batch_ask(notebook_id, questions)
```

### Strategy 2: Progressive Deepening

Start broad, then drill into specific areas:

```
Round 1: 5 broad architecture questions → get overview
Round 2: 5 detailed questions on the most complex component
Round 3: 5 edge case / failure mode questions
Round 4: 5 implementation detail questions
```

Each round builds on answers from the previous.

### Strategy 3: Knowledge Extraction Pipeline

For research notebooks:

1. **Seed notebook** with 10-20 sources (papers, docs, articles)
2. **Ask 20 questions** in 4 batches of 5
3. **Generate document** — creates titled summary
4. **Save note** — creates persistent artifact
5. **Store all Q&A in Nexus** — cache for future retrieval
6. **Delete notebook** — frees quota

### Strategy 4: Code Analysis

For analyzing a codebase module:

1. Create notebook with source files as uploads
2. Ask architecture questions
3. Ask quality/testing questions
4. Ask improvement questions
5. Store findings in Nexus with `content_type="code_analysis"`

### Strategy 5: News Distillation

For the news pipeline:

1. Create rotating daily notebook
2. Add 15-20 articles as URL sources
3. Batch ask: "Summarize the 3 most important developments"
4. Batch ask: "What are the implications for local AI systems?"
5. Store summaries in Nexus as `content_type="news"`
6. Delete notebook (or archive)

---

## Protocol Observations from HAR Analysis

### Complete HAR Statistics

| Metric | Value |
|--------|-------|
| Total entries | 162 |
| batchexecute calls | 19 |
| Unique RPC IDs | 5 |
| Notebook ID | `de7fee37-1c07-406f-85ec-108c530dc3ea` |
| Build label | `boq_labs-tailwind-frontend_20260226.08_p0` |
| f.sid | `5167585844626553481` |
| Chrome version | 145.0.7632.117 |

### RPC Call Distribution

| RPC | Count | Type |
|-----|-------|------|
| `CYK0Xb` | 9 | WRITE — Ask question |
| `cFji9` | 5 | READ — Get conversation |
| `gArtLc` | 5 | READ — List artifacts |
| `R7cb6c` | 2 | WRITE — Save note |
| `ciyUvf` | 1 | WRITE — Generate document |

### Key Findings

1. **CYK0Xb answers synchronously** — No polling needed. One request → one response
   with the complete answer. Average response time: ~3-8 seconds.

2. **Multi-question batching works** — The HAR shows 9 separate CYK0Xb calls,
   but they could all be sent in 2 batched HTTP requests (5+4). The batchexecute
   f.req format explicitly supports multiple RPCs in one call.

3. **Cookies are NOT required in the f.req** — The session token (`f.sid`) extracted
   from the page on initial load provides some auth context. However, full write
   operations (CYK0Xb, R7cb6c, ciyUvf) require valid session cookies.

4. **Config object is constant** — The `_WRITE_CONFIG` pattern
   `[2, None, None, [1, None, None, ..., [1]], [[2, 1]]]` appears identically
   in both ciyUvf and R7cb6c calls. It appears to control document type formatting.

5. **Note types**: `2` = standard note, `9` = deep research report. Other types
   likely exist but weren't observed in HAR.

6. **Source IDs are UUIDs** — All source references use v4 UUIDs. The nested
   structure `[[src_id], [src_id], ...]` is required for write operations.

7. **Answer IDs chain into conversations** — The `answer_id` from CYK0Xb can be
   used in cFji9 to retrieve the conversation thread, enabling follow-up Q&A.

8. **cFji9 timestamp format** — The `[ts_sec, ts_ns]` parameter is Unix timestamp
   split into seconds and nanoseconds. Pass `[0, 0]` to get full history.

---

## Session Refresh Strategy

Google session cookies typically last **1-24 hours**. When they expire:

1. **Automatic (preferred):** CDP capture via `POST /cookies/capture`
2. **Scheduled:** Run `nlm_har_capture.py` every 8 hours via scheduler_daemon
3. **Manual:** Save new HAR and call `POST /cookies/import`
4. **Detection:** HTTP 401 from proxy → trigger auto-recapture

```python
# In scheduler_daemon.py callback:
def _refresh_nlm_cookies() -> None:
    """Auto-refresh NLM cookies every 8 hours."""
    try:
        resp = requests.post("http://localhost:8800/cookies/capture", timeout=30)
        if resp.ok:
            logger.info("NLM cookies refreshed successfully")
        else:
            logger.warning("NLM cookie refresh failed: %s", resp.text)
    except Exception as exc:
        logger.error("NLM cookie refresh error: %s", exc)
```

---

## Build Label Maintenance

The `bl` parameter changes periodically (roughly weekly). When it changes,
all batchexecute calls return HTTP 400 until updated.

**Detection:** HTTP 400 response from proxy
**Fix:** Import a fresh HAR (automatically extracts new bl) or visit NLM page
and capture via CDP (extracts bl from page JavaScript).

The proxy stores `bl` in `data/nlm_meta.json`. The last known good value is
hardcoded as fallback in `nlm_live_proxy.py`.

---

## Integration with Nexus

All NLM interactions should be stored in Nexus:

```python
from engine.nexus.client import get_nexus_client

client = get_nexus_client()

# Store Q&A pair from NLM answer
client.add_qa(
    question="What is the main architecture?",
    answer=result["answer"],
    category="architecture",
)

# Store research session
client.add_entry(
    title=f"NLM Research: {topic}",
    content="\n\n".join(f"Q: {q}\nA: {a['answer']}" for q, a in zip(questions, answers)),
    content_type="research",
    category="architecture",
)
```

---

## Files

| File | Purpose |
|------|---------|
| `engine/mcp/nlm_live_proxy.py` | Flask proxy at :8800, full RPC implementation |
| `engine/mcp/notebooklm_proxy.py` | High-level Python client for the proxy |
| `engine/nexus/nlm_har_capture.py` | Chrome CDP cookie extraction |
| `engine/nexus/nlm_qa_distiller.py` | NLM-powered Q&A generation for Nexus |
| `engine/nexus/nlm_notebook_manager.py` | Research notebook fleet management |
| `engine/nexus/nlm_research_pipeline.py` | Structured research workflows |
| `data/nlm_cookies.json` | Stored Google auth cookies |
| `data/nlm_meta.json` | Build label, session ID |
| `tests/test_nlm_live_proxy.py` | Test suite (35+ tests) |

---

## Dependencies

```
pip install websocket-client   # For Chrome CDP capture (nlm_har_capture.py)
flask                           # Already installed (proxy server)
requests                        # Already installed (HTTP client)
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-02 | Complete rewrite — CYK0Xb (ask), ciyUvf (generate), R7cb6c (save note), multi-batch |
| 1.5 | 2025-12 | Added HAR ingestion to Nexus Panel, 464 entries ingested |
| 1.0 | 2025-11 | Initial NLM proxy — read-only operations |
