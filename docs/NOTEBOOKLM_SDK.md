# NotebookLM SDK — Complete Protocol Documentation

> **Version:** 2.1 (based on HAR analysis of 11 HAR files across 5 NLM sessions, 2026-02-26/28)
> **Status:** Production implementation in `engine/mcp/nlm_live_proxy.py`
> **New in 2.1:** Full RPC catalogue (18 RPCs), s0tc2d chat, tr032e source reader,
> Configure Chat, response length control, BL staleness tracking.

---

## Overview

NotebookLM uses Google's **batchexecute** RPC transport — the same protocol
used across Google Search, Docs, and other G-Suite products. All API calls
go to a single endpoint via HTTP POST, with RPC functions identified by
short 5–7 character IDs.

**Key insights from multi-session HAR analysis:**
- The API is stateless (after auth). Every call is self-contained.
- RPC IDs are **STABLE within a Google frontend build** (build label / BL).
- RPC IDs **CAN change** when Google deploys a new frontend (~weekly).
- `CYK0Xb` (old chat) → replaced by `s0tc2d` (current chat) after build 20260226.
- `CYK0Xb` still works as "annotate text with citations" — different use case.
- Multi-question batching: 5 RPCs per HTTP request → 5× throughput.
- The proxy at :8800 wraps all of this in a clean REST API.

---

## Build Label (BL) Management

The BL is the most critical operational parameter:

```
boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
```

- Changes roughly weekly with Google frontend deployments
- If BL is stale (>8 days), requests may return 404 or malformed responses
- BL is stored in `data/nlm_meta.json` alongside `bl_updated_at`
- Auto-extracted from imported HARs
- Check staleness: `GET /health` returns `bl_age_days` and `bl_stale: true/false`
- If stale: import a fresh HAR via `POST /cookies/import` or run `POST /cookies/capture`

**Monitoring BL health:**
```bash
curl http://localhost:8800/health
# Response includes: {"bl": "boq_labs-...", "bl_age_days": 3, "bl_stale": false}
```

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

| Parameter   | Example                             | Notes                          |
|-------------|-------------------------------------|--------------------------------|
| `rpcids`    | `CYK0Xb` or `CYK0Xb;s0tc2d`       | Semicolon-separated for batch  |
| `source-path` | `/notebook/<nb_id>`              | Optional — sets auth context   |
| `bl`        | `boq_labs-tailwind-frontend_...`   | Build label — CRITICAL         |
| `f.sid`     | `-1` or extracted from HAR         | Session ID                     |
| `hl`        | `en`                               | Language                       |
| `_reqid`    | `100000`                           | Auto-incrementing request ID   |
| `rt`        | `c`                                | Response type (always `c`)     |

### Request Body

```
f.req=<url_encoded_json>
```

Where the JSON is an array of `[rpc_id, args_json, null, "generic"]` tuples.

### Response Format

Responses start with `)]}'` (XSSI protection), followed by newline-delimited
chunks. Each `wrb.fr` chunk is a JSON array:

```json
[["wrb.fr", "RPC_ID", "inner_json_string", null, null, null, "generic"],
 ["di", 457],
 ["af.httprm", ...]]
```

The inner JSON string must be `json.loads()`'d again to get the actual data.

---

## Complete RPC Catalogue

### Read RPCs

#### `ZwVcOc` — Session Initialization
```python
args = [None, [1, None, None, None, None, None, None, None, None, None, [1]]]
```
Called on page load to initialize the session context.

#### `wXbhsf` — List Sources (Full)
```python
args = [None, 1, None, [2]]
```
Returns the full list of sources for the current notebook including title, URL,
word count, and source type. Also returns the notebook name.

**Response structure:** `[[[notebook_name, [source_array]...]]]`

#### `ub2Bae` — List Notebooks
```python
args = [[2]]
```
Returns all user notebooks with IDs and names.

#### `sqTeoe` — List All Notebooks (Extended)
```python
args = [[2, None, None, [1,...,[1]], [[2,1]]], None, 1]
```
Extended notebook list with more metadata.

#### `rLM1Ne` — Load Notebook by ID
```python
args = [notebook_id, None, [2], None, 0]
```
Load a specific notebook by UUID. Returns notebook metadata.

#### `e3bVqc` — Notebook Extended Info
```python
args = [None, None, notebook_id]
```
Returns extended notebook information including content metadata.

#### `hPTbtc` — List Sources (Paginated)
```python
args = [[], None, notebook_id, page_size]  # page_size default: 20
```
Paginated source listing for large notebooks.

#### `khqZz` — List Sources (Sub-notebook)
```python
args = [[], None, None, source_notebook_id, page_size]
```
Sources list for a nested/sub notebook context.

#### `JFMDGd` — Sources Condensed
```python
args = [notebook_id, [2]]
```
Compact source list — lighter payload than `wXbhsf`.

#### `VfAZjd` — AI Overview / Summary
```python
args = [notebook_id, [2]]
```
Returns the AI-generated overview/summary for a notebook. This is the
"Notebook Guide" section visible in the NLM UI.

#### `gArtLc` — List Artifacts (Notes/Docs)
```python
args = [_WRITE_CONFIG, notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
```
Returns all user-created notes, study guides, briefs, and other artifacts.
The filter string excludes auto-suggested artifacts (AI suggestions).

#### `cFji9` — Conversation History
```python
args = [notebook_id, None, cursor_timestamp, [2]]
# cursor_timestamp: [unix_seconds, nanoseconds] for pagination, or None for latest
```
Returns the conversation history for a notebook. Used after `s0tc2d` to
retrieve the generated answer.

#### `ozz5Z` — User Quota / Account Info
```python
args = [[[[None, "1", 627], [None, None, None, None, None, None, None,
           None, None, [None, None, 4]], 1]]]
```
Returns user account metadata, storage quota, and plan information.
The `627` appears to be a notebook count or content size indicator.

#### `tr032e` — Read Source Content ⭐ **New in v2.1**
```python
args = [[[[source_id]]]]
```
Returns the **complete markdown text** of a source document. This is
extremely valuable for offline analysis and Nexus ingestion:

```python
# Read all source content from a notebook
sources = get_sources(notebook_id, cookies)
for source in sources:
    result = read_source(source["id"], cookies)
    # result["content"] = full markdown text
    # result["word_count"] = word count
    nexus_client.add_entry(source["title"], result["content"], "document")
```

---

### Write RPCs

#### `s0tc2d` — Chat Message (CURRENT) ⭐ **Primary chat RPC**

The current chat interface as of build `20260226.08_p0`. Triggers NLM's
Gemini model to generate a response asynchronously.

**Full payload structure:**
```python
inner_msg = [[2, question_text], [response_length]]
chat_config = [
    role_or_none,      # position 0: Configure Chat goal/role string
    None,              # position 1: reserved
    None,              # position 2: reserved
    None,              # position 3: reserved
    None,              # position 4: reserved
    None,              # position 5: reserved
    None,              # position 6: reserved
    inner_msg,         # position 7: the message content
]
args = [notebook_id, [chat_config]]
```

**Response length constants:**
| Value | Meaning | Source |
|-------|---------|--------|
| `4`   | Default | Confirmed from HAR |
| `1`   | Longer  | Hypothesis — test with `/rpc/s0tc2d` |
| `2`   | Shorter | Hypothesis — test with `/rpc/s0tc2d` |

**Response:** Echoes question metadata + notebook title. The actual answer
arrives asynchronously — poll `cFji9` (conversation history) to retrieve it.

**Configure Chat — Role Injection:**
Inject a role/persona at position 0 of `chat_config`:
```python
# Teacher mode
role = "Act as a patient teacher. Explain concepts clearly with examples."

# Researcher mode
role = "You are a PhD researcher. Provide thorough analysis with source citations."

# Q&A Distiller mode
role = "Extract key facts and generate structured Q&A pairs from the sources."

# Code Helper mode
role = "You are an expert Python developer. Provide working code examples."

# Critic mode
role = "Critically analyze the claims and identify gaps or weaknesses."
```

**Important:** s0tc2d is ASYNCHRONOUS — the response does not contain the
answer. Use `cFji9` to poll for the answer after calling s0tc2d.

---

#### `CYK0Xb` — Annotate Text with Citations (LEGACY + STILL VALID)

Older chat RPC, still valid. Different behavior from s0tc2d:
- Takes text as input instead of a structured question
- Returns the answer WITH inline source citations immediately (synchronous)
- Ideal for Q&A distillation where you want cited answers

```python
args = [notebook_id, question_or_context_text]
# Response: [[answer_id, markdown_text_with_citations]]
```

**When to use CYK0Xb vs s0tc2d:**
| Use Case | RPC | Reason |
|----------|-----|--------|
| Q&A distillation (need citations) | `CYK0Xb` | Synchronous, cited |
| Batch Q&A (5 per request) | `CYK0Xb` | Works with multi-batch |
| Conversational chat | `s0tc2d` | Proper chat interface |
| Configure Chat + role | `s0tc2d` | Supports role injection |
| Response length control | `s0tc2d` | Supports length hint |

---

#### `ciyUvf` — Generate Deep Research Document

Generates a comprehensive document from selected sources. This is the
"Deep Research" or "Study Guide" generation feature.

```python
source_array = [[src_id] for src_id in source_ids]
args = [_WRITE_CONFIG, notebook_id, source_array]
# Response: [[title, description, null, [[source_id], ...]]]
```

The response provides a preview (title + description) before saving.
Follow with `R7cb6c` to save to the notebook.

---

#### `R7cb6c` — Save Note / Brief

Saves a note or brief to the notebook. Used after `ciyUvf` to persist a
generated document, or standalone to create a custom note.

```python
source_array = [[[src_id]] for src_id in source_ids]
note_body = [None, None, doc_type, source_array]
args = [_WRITE_CONFIG, notebook_id, note_body]
# Response: [[note_id, title, type_int, [[source_ids]]]]
```

**Document types:**
| `doc_type` | Format | Confirmed? |
|-----------|--------|-----------|
| `2`       | Research brief | ✅ Confirmed from HAR |
| `9`       | Notes (free-form) | ✅ Confirmed from HAR |
| `3`–`8`   | Study guide, FAQ, Timeline, etc. | Hypothesis — test with `/rpc/R7cb6c` |

---

## Multi-Question Batching

Up to 5 RPCs can be packed into a single batchexecute request:

```python
# 5 questions in one HTTP request
calls = [
    ("CYK0Xb", json.dumps([notebook_id, q]))
    for q in questions[:5]
]
# Pack into f.req:
f_req = [[rpc_id, args_json, None, "generic"] for rpc_id, args_json in calls]
# rpcids URL param: "CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb"
```

**Response parsing:** Each `wrb.fr` block in the response corresponds to
one call, in order. Our `_parse_batchexecute_multi()` handles this automatically.

---

## CosySim REST API (via :8800 proxy)

### Authentication & Setup

```bash
# Check health and BL staleness
GET http://localhost:8800/health

# Import cookies from HAR
POST http://localhost:8800/cookies/import
Body: {"har_path": "/path/to/notebooklm.har"}

# Auto-capture cookies via Chrome CDP (recommended)
POST http://localhost:8800/cookies/capture

# Check/update build label
GET http://localhost:8800/meta
POST http://localhost:8800/meta
Body: {"bl": "boq_labs-tailwind-frontend_YYYYMMDD.NN_p0"}
```

### Reading Notebook Data

```bash
# List all notebooks
GET http://localhost:8800/notebooks

# Get all notebook data (sources, notes, conversations)
GET http://localhost:8800/notebooks/<notebook_id>

# Get sources only
GET http://localhost:8800/notebooks/<notebook_id>/sources

# Get AI overview summary
GET http://localhost:8800/notebooks/<notebook_id>/summary

# Get notes/artifacts
GET http://localhost:8800/notebooks/<notebook_id>/notes

# Get conversation history
GET http://localhost:8800/notebooks/<notebook_id>/conversations

# Read full text of a source ⭐ New
GET http://localhost:8800/sources/<source_id>/content

# Check user quota ⭐ New
GET http://localhost:8800/user/quota
```

### Ask / Chat (Write)

```bash
# Ask with citations (CYK0Xb — synchronous, recommended for Q&A)
POST http://localhost:8800/notebooks/<nb_id>/ask
Body: {"question": "What is the main argument?", "mode": "annotate"}

# Chat with role config (s0tc2d — asynchronous) ⭐ New
POST http://localhost:8800/notebooks/<nb_id>/ask
Body: {
  "question": "Summarize the key findings",
  "mode": "chat",
  "role": "Act as a researcher providing thorough analysis",
  "response_length": 4
}

# Batch ask (5 at once)
POST http://localhost:8800/notebooks/<nb_id>/ask_batch
Body: {
  "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"],
  "mode": "annotate",
  "max_batch": 5
}

# Chat endpoint (s0tc2d specific) ⭐ New
POST http://localhost:8800/notebooks/<nb_id>/chat
Body: {
  "question": "What are the key techniques?",
  "role": "You are a PhD researcher",
  "response_length": 4
}

# Batch chat ⭐ New
POST http://localhost:8800/notebooks/<nb_id>/chat_batch
Body: {
  "questions": ["Q1?", "Q2?", "Q3?"],
  "role": "Act as a teacher",
  "max_batch": 5
}
```

### Generate & Save

```bash
# Generate deep research document
POST http://localhost:8800/notebooks/<nb_id>/generate
Body: {"source_ids": ["uuid1", "uuid2", ...], "doc_type": 2}

# Save note/brief
POST http://localhost:8800/notebooks/<nb_id>/save_note
Body: {"source_ids": ["uuid1", ...], "note_type": 9}

# Call any RPC directly (for testing/exploration)
POST http://localhost:8800/rpc/<rpc_id>
Body: {"args": "[\"nb_id\", ...]", "notebook_id": "uuid"}
```

---

## Use Case Playbooks

### 1. Q&A Distillation (Nexus Feed)

The most valuable use case: extract Q&A knowledge from notebooks into Nexus.

```python
from engine.mcp.nlm_live_proxy import ask_questions_batch, _load_cookies

cookies = _load_cookies()
notebook_id = "your-notebook-uuid"

# Prepare 25 topic questions (5 batches of 5)
questions = [
    "What is the core architecture?",
    "How does the training process work?",
    # ... 23 more questions
]

# Run all in 5 HTTP requests
answers = ask_questions_batch(notebook_id, questions, cookies, max_batch=5)

# Store in Nexus
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
for q, a in zip(questions, answers):
    if a.get("answer"):
        client.add_qa(q, a["answer"])
```

### 2. Configure Chat Persona for Specialized Output

```python
from engine.mcp.nlm_live_proxy import chat_message, _load_cookies

cookies = _load_cookies()

# Teacher mode — generates educational content
answer = chat_message(
    notebook_id,
    "Explain the key concepts step by step",
    cookies,
    role="You are a patient teacher. Use simple language and concrete examples. "
         "Structure your answer with clear headings and bullet points.",
)

# Researcher mode — generates cited academic-style analysis
answer = chat_message(
    notebook_id,
    "What are the main contributions of this work?",
    cookies,
    role="You are a PhD researcher. Provide thorough analysis. "
         "Cite specific sections and quote key passages.",
)

# Code generator mode
answer = chat_message(
    notebook_id,
    "Show me how to implement this in Python",
    cookies,
    role="You are an expert Python developer. Always provide working, "
         "tested code with type hints and docstrings.",
)
```

### 3. Source Content Extraction to Nexus

```python
from engine.mcp.nlm_live_proxy import _load_cookies, read_source
import requests

cookies = _load_cookies()

# Get all sources
resp = requests.get(f"http://localhost:8800/notebooks/{nb_id}/sources")
sources = resp.json()["sources"]

# Extract content from each source into Nexus
from engine.nexus.client import get_nexus_client
client = get_nexus_client()
for source in sources:
    content = read_source(source["id"], cookies)
    if content.get("content"):
        client.add_entry(
            source["title"],
            content["content"],
            content_type="document",
            category="research",
        )
```

### 4. Document Generation Pipeline

Generate a full research brief and save to notebook:

```python
from engine.mcp.nlm_live_proxy import generate_document, save_note, _load_cookies
import requests

cookies = _load_cookies()
nb_id = "your-notebook-uuid"

# Get source IDs
resp = requests.get(f"http://localhost:8800/notebooks/{nb_id}/sources")
source_ids = [s["id"] for s in resp.json()["sources"]]

# Preview the generated document
preview = generate_document(nb_id, source_ids, cookies, doc_type=2)
print(f"Title: {preview['title']}")
print(f"Description: {preview['description'][:200]}")

# Save as research brief
saved = save_note(nb_id, source_ids, cookies, note_type=2)
print(f"Saved: {saved['title']} (ID: {saved['note_id']})")

# Or save as notes
notes = save_note(nb_id, source_ids, cookies, note_type=9)
```

### 5. News Research Workflow

Use NLM notebooks as research agents for the news feed system:

```python
# 1. Create a notebook for the news topic (via /rpc/ub2Bae + notebook creation)
# 2. Add news sources (article URLs)
# 3. Run Q&A distillation on the sources
# 4. Generate a research brief
# 5. Store Q&A + brief in Nexus with news category

RESEARCHER_ROLE = (
    "You are an expert analyst covering breaking AI/tech news. "
    "Identify the most important developments, their implications, "
    "and how they connect to existing knowledge. Be concise and factual."
)

questions = [
    "What are the key announcements or findings in these sources?",
    "What is the immediate impact on the field?",
    "What questions does this raise for future research?",
    "How does this compare to previous approaches?",
    "What should practitioners implement based on this?",
]

answers = chat_messages_batch(nb_id, questions, cookies,
                               role=RESEARCHER_ROLE, max_batch=5)
```

### 6. Maximizing Output Efficiency

```python
# Strategy: 5 questions per request → 5× throughput vs sequential

# BAD: Sequential (5 requests)
for q in questions:
    answer = ask_question(nb_id, q, cookies)

# GOOD: Batch (1 request for 5 questions)
answers = ask_questions_batch(nb_id, questions, cookies, max_batch=5)

# Even better: Pre-plan 20 questions, 4 batches of 5
# Total: 4 HTTP requests instead of 20
questions = generate_20_questions_for_topic("local AI systems")
answers = ask_questions_batch(nb_id, questions, cookies, max_batch=5)
```

---

## BL Discovery and RPC Health Monitoring

### Detecting Stale BL

```bash
# Check health
curl http://localhost:8800/health
# {"bl": "boq_labs-...", "bl_age_days": 5, "bl_stale": false}

# If bl_stale: true, refresh immediately:
curl -X POST http://localhost:8800/cookies/capture
# Or import a new HAR from a fresh NLM session
```

### Testing RPC Availability

```bash
# Test if a specific RPC still works
curl -X POST http://localhost:8800/rpc/CYK0Xb \
  -H "Content-Type: application/json" \
  -d '{"args": "[\"nb_id\", \"test question\"]", "notebook_id": "nb_id"}'

# If you get HTTP 404 or error → RPC ID changed after build update
# Import fresh HAR and re-extract BL
```

### Discovering New RPC IDs After Build Update

When Google deploys a new frontend:
1. Import a fresh HAR captured from the new build
2. The new BL is auto-extracted and saved
3. Old RPC IDs remain valid until the old build is decommissioned (~2–4 weeks)
4. Monitor for HTTP 404 responses on write RPCs (reads tend to be more stable)

---

## Protocol Deep Dive

### Full Request Example (CYK0Xb)

```python
import urllib.parse, urllib.request, json

notebook_id = "bec06e03-7cf2-4989-bf17-bcb0ac9927a0"
question = "What are the main contributions?"
bl = "boq_labs-tailwind-frontend_20260226.08_p0"

# Build URL
params = urllib.parse.urlencode({
    "rpcids": "CYK0Xb",
    "source-path": f"/notebook/{notebook_id}",
    "bl": bl,
    "f.sid": "-1",
    "hl": "en",
    "_reqid": "100000",
    "rt": "c",
})
url = f"https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute?{params}"

# Build body
f_req = [["CYK0Xb", json.dumps([notebook_id, question]), None, "generic"]]
body = urllib.parse.urlencode({"f.req": json.dumps(f_req)}).encode()

# Send
req = urllib.request.Request(url, data=body, headers=headers)
with urllib.request.urlopen(req, timeout=60) as resp:
    raw = resp.read().decode("utf-8")
```

### Full Request Example (s0tc2d with Configure Chat)

```python
question = "Explain the key architecture"
role = "You are a PhD researcher. Be thorough and cite sources."
resp_len = 4  # Default

inner_msg = [[2, question], [resp_len]]
chat_config = [role, None, None, None, None, None, None, inner_msg]
args = json.dumps([notebook_id, [chat_config]])

f_req = [["s0tc2d", args, None, "generic"]]
# ... same URL construction and send as above
```

### Response Parsing

```python
raw = ")]}'\\n530\\n[...]\\n25\\n[...]\\n"
body = raw.lstrip(")]}'").lstrip("\\n")

for line in body.split("\\n"):
    line = line.strip()
    if not line.startswith('[["wrb.fr"'):
        continue
    outer = json.loads(line)
    rpc_id = outer[0][1]           # "CYK0Xb"
    inner_raw = outer[0][2]        # string-encoded inner JSON
    inner = json.loads(inner_raw)  # [[answer_id, answer_text]]
```

---

## Known Limitations and Gotchas

1. **s0tc2d is asynchronous** — the response does NOT contain the answer.
   Use `cFji9` (conversation history) to retrieve it after ~2–5 seconds.

2. **CYK0Xb is synchronous** — better for programmatic Q&A where you need
   the answer immediately.

3. **Chrome 130+ redacts cookies from HAR exports** — always use CDP capture
   (`POST /cookies/capture`) or extract via the `data/nlm_cookies.json` manual method.

4. **Build label changes weekly** — implement BL monitoring and auto-refresh.
   The `bl_stale` field in `/health` is your early warning system.

5. **Batch limit** — 5 RPCs per request appears to be the practical limit.
   Exceeding this may cause malformed responses.

6. **Rate limiting** — No hard rate limit observed, but aggressive batching
   (>50 questions/minute) may trigger soft limits. Add 1–2s delays between
   large batch groups.

7. **Source UUIDs** — Source IDs are per-notebook and do not transfer between
   notebooks. Always fetch source IDs from `wXbhsf` before using them in
   `ciyUvf` or `R7cb6c`.

---

## Integration with CosySim Nexus

The NLM proxy is fully integrated with the CosySim Nexus knowledge system:

```python
# Via MCP skills (agents can call these directly)
nlm_live_ask(notebook_id, "What is X?")
nlm_live_batch_ask(notebook_id, ["Q1?", "Q2?", "Q3?"])
nlm_generate_document(notebook_id, source_ids)
nlm_save_note(notebook_id, source_ids)
nlm_capture_cookies()
nlm_proxy_meta()
nlm_distill_notebook(notebook_id)  # Full Q&A distillation workflow

# Via NLM Forge skills (routes through 4-tier Nexus pipeline first)
nlm_ask("question")         # Cache → FTS → NLM → LLM
nlm_batch_ask(questions)    # Same but batched
nlm_generate_doc(nb_id)     # Full document generation

# Via QA Distiller CLI
python -m engine.nexus.nlm_qa_distiller --bulk --notebook <id>
```

---

*Last updated: 2026-02-28 | Version 2.1 | 18 RPCs catalogued across 11 HAR files*

