# NotebookLM SDK — Complete Protocol Documentation

> **Version:** 3.0 (based on HAR analysis of 8 HAR files, 21 unique RPCs confirmed, 2026-02-27/28)
> **Status:** Production implementation in `engine/mcp/nlm_live_proxy.py`
> **New in 3.0:** 21 confirmed RPCs (+3 new: `CCqFvf`, `Ljjv0c`, `LBwxtb`), corrected 5 RPC
> descriptions (`sqTeoe`, `hPTbtc`, `khqZz`, `JFMDGd`, `cFji9`, `CYK0Xb`), added
> `GenerateFreeFormStreamed` proto endpoint, source data structure, missing operations list.

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

**21 unique RPCs confirmed across 8 HAR files.** Operations are divided into
Read (data retrieval), Write (mutations), and Async (background operations).

### Config Object (`_WRITE_CONFIG`)

Several write RPCs share a common config object as their first argument:
```python
_WRITE_CONFIG = [2, None, None,
    [1, None, None, None, None, None, None, None, None, None, [1]],
    [[2, 1]]
]
```

### Source Data Structure

All source objects across RPCs follow this structure:
```python
source = [
    [source_id],              # position 0: UUID wrapped in list
    "filename_or_title",      # position 1: display name
    [
        None,
        word_count,           # position 1: word count (int)
        [unix_sec, nano_sec], # position 2: created_at timestamp
        [process_id, [unix_sec, nano_sec]],  # position 3: processing job info
        format_type,          # position 4: see table below
        None,
        status,               # position 6: 1=private, 2=shared/processed
        [url],                # position 7: source URL (web/YouTube only)
        char_count,           # position 8: total character count (optional)
    ],
    [None, add_method]        # position 3: add_method: 2=url, 1=upload
]
```

**Source format type codes:**
| Code | Type |
|------|------|
| `1`  | Google Doc (Drive) |
| `2`  | Google Slides |
| `3`  | PDF |
| `5`  | Web article / URL |
| `7`  | YouTube video |
| `8`  | Markdown / plain text file |

---

### Read RPCs

#### `ZwVcOc` — Get Session Limits
```python
args = [None, [1, None, None, None, None, None, None, None, None, None, [1]]]
# Response: [[None, [max_notebooks_visible, max_sources, ?, max_chars_per_source], features]]
# Confirmed values: [6, 200, 100, 500000]
```
Called on page load. Returns account limits that govern what the UI can show.

---

#### `ub2Bae` — List Notebooks
```python
args = [[2]]
# Response: [[[notebook_title, [[sources_preview]], notebook_id, state...]]]
```
Returns user notebooks (homepage view). Called on `/` and notebook paths.
Each notebook entry includes a sources preview array.

---

#### `wXbhsf` — Get Notebook Sources + State
```python
args = [None, 1, None, [2]]
# Response: [[[notebook_title, [[source_obj, ...]], ...]]]
```
Returns all sources for the current notebook. Called from multiple paths:
- From `/`: returns last-opened notebook's sources
- From `/notebook/creating`: returns `["", null, new_uuid, ...]` state + last notebook data
- From `/notebook/<id>`: returns that notebook's current source list

This is the primary source list RPC. Use `rLM1Ne` for polling (it's identical
but takes a notebook_id argument for specificity).

---

#### `rLM1Ne` — Load Notebook by ID (Poll)
```python
args = [notebook_id, None, [2], None, 0]
# Response: [[notebook_title, [[source_obj, ...]]]]
```
Load a specific notebook by UUID. Identical payload structure to `wXbhsf` but
takes an explicit `notebook_id`. Used as a **polling RPC** after `LBwxtb` — call
repeatedly until all newly added sources have a non-zero `word_count`.

**Polling pattern:**
```python
for _ in range(30):  # up to ~5 minutes
    sources = load_notebook(notebook_id, cookies)
    if all(s["word_count"] > 0 for s in sources):
        break
    time.sleep(10)
```

---

#### `e3bVqc` — Get Full Notebook Info
```python
args = [None, None, notebook_id]
# Response: [[[session_id, [notebook_id, [description_text, 1], version, [sources]]]]]
```
Returns the complete notebook record — description text, version, all source
objects. Response can be 80-100KB for populated notebooks. The `description_text`
is the notebook's topic/search description (e.g., "multi-agent frameworks...").

---

#### `hPTbtc` — Get Conversation Thread IDs ⚠️ **Corrected in v3.0**
```python
args = [[], None, notebook_id, page_size]  # page_size default: 20
# Response: [[[thread_id]]]
# Example: [[["f3acda91-f4b5-4b1c-8793-45bbd5fa45b0"]]]
```
Returns the sub-notebook (conversation thread) IDs for a notebook. The returned
`thread_id` is used by `khqZz` to read the actual conversation messages.
**Not** a paginated sources list as previously documented.

---

#### `khqZz` — Read Conversation Thread Messages ⚠️ **Corrected in v3.0**
```python
args = [[], None, None, thread_id, page_size]  # thread_id from hPTbtc
# Response: [[[msg_id, [unix_sec, nano_sec], role, None, [[message_text]]]]]
# role: 2 = user, 1 = assistant (hypothesis)
```
Reads all messages from a conversation thread. `thread_id` comes from `hPTbtc`.
**Not** a sub-notebook source list as previously documented.

**Full conversation retrieval pattern:**
```python
thread_ids = get_thread_ids(notebook_id, cookies)  # hPTbtc
for tid in thread_ids:
    messages = read_thread(tid, cookies)            # khqZz
    for msg in messages:
        store_in_nexus(msg["text"])
```

---

#### `VfAZjd` — Generate Notebook AI Overview
```python
args = [notebook_id, [2]]
# Response: [[[markdown_overview_text]]]
```
Returns (or generates) the AI-written overview of all notebook sources. This
is the "Notebook Guide" / overview panel in the NLM UI. Appears to be cached
server-side and regenerated when sources change.

---

#### `gArtLc` — List Saved Artifacts
```python
args = [_WRITE_CONFIG, notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
# Response: [[[artifact_id, title, type_int, [[source_id_arrays]], timestamp, ...]]]
```
Returns all explicitly saved artifacts (study guides, briefs, tables, slides).
The filter string `'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'` excludes
AI-suggested but not-yet-saved artifacts. Omit the filter to include suggestions.

---

#### `sqTeoe` — List Audio Overview Types ⚠️ **Corrected in v3.0**
```python
args = [_WRITE_CONFIG, None, 1]
# Response: [[[[1,'Deep dive','A lively conversation...'],
#              [2,'Brief','A bite-sized overview...'],
#              [3,'Critique','An expert review...'],
#              [4,'Debate','...'], ...]]]
```
Returns the available audio overview styles with their display names and
descriptions. **Not** an extended notebook list as previously documented.

---

#### `JFMDGd` — Get User Profile ⚠️ **Corrected in v3.0**
```python
args = [notebook_id, [2]]
# Response: [[[email, 1, [], [display_name, avatar_url]]], None, queries_remaining]
# Example: [[["knack112358@gmail.com", 1, [], ["Ray Daniels", "https://lh3..."]]], None, 1000]
```
Returns the signed-in user's profile. The third element is the **remaining query
count** (e.g. `1000`). **Not** a condensed source list as previously documented.

---

#### `ozz5Z` — Get Account UI State
```python
args = [[[[None, "1", plan_tier_id], [None,...,[None,None,4]], 1]]]
# Response: account plan info, subscription URL, [[[None,'1',627],[subscription_urls,...],1]]]
# plan_tier_id 1287 = NotebookLM Plus
```
Returns subscription tier, plan management URL, and UI feature flags.
The integer at position `[0][0][0][2]` is the plan tier ID.

---

#### `CCqFvf` — Resume Session / Load Last Notebook ⭐ **New in v3.0**
```python
args = ["", None, None, [2], [1, None, None, None, None, None, None, None, None, None, [1]]]
# Response: ["", None, last_notebook_id, None, None, state_obj, None, ..., [[conv_thread_id]]]
# Example: ["", None, "50ab3060-466e-4c90-aacb-8134a130de29", None, None, [...], ..., [["3a6cd367-..."]]]
```
Called from the homepage (`/`) on every page load. Resumes the user's last
active notebook session. Returns the last-used notebook ID and its conversation
thread ID. The `""` first arg means "use last session". The `[2]` flag requests
full source data.

> **Note on Create Notebook:** No batchexecute RPC was observed for notebook
> creation across 8 HAR files. The notebook UUID is generated client-side (in
> browser JS) and the backend record is created lazily on the first mutation
> (e.g. `LBwxtb`). To create a notebook programmatically: generate a UUID v4,
> call `LBwxtb` with it as the `notebook_id` — this implicitly creates it.

---

#### `tr032e` — Get Source AI Summary
```python
args = [[[[source_id]]]]  # source_id wrapped in 3 nested lists
# Response: [[[None, [summary_markdown_text]]]]
```
Returns the AI-generated summary shown when you click a source in the NLM UI.
Not the full source text — use `wXbhsf` / `rLM1Ne` for full content extraction.

---

### Write RPCs

#### `s0tc2d` — Ask Question (Chat) — **Asynchronous**

The current chat interface. Triggers Gemini to generate a response
asynchronously. **The response does NOT contain the answer** — poll `khqZz`
(via `hPTbtc` to get the thread ID) to retrieve it.

```python
inner_msg = [[2, question_text], [response_length]]
chat_config = [
    role_or_none,      # position 0: Configure Chat role string (optional)
    None,              # positions 1–6: reserved
    None,
    None,
    None,
    None,
    None,
    inner_msg,         # position 7: the message content
]
args = [notebook_id, [chat_config]]
# Response: echoes question metadata + notebook_title (answer arrives async)
```

**Response length values:**
| Value | Meaning |
|-------|---------|
| `4`   | Default length |
| `1`   | Longer response |
| `2`   | Shorter response |

**Role injection examples:**
```python
roles = {
    "teacher":     "Act as a patient teacher. Use simple language with concrete examples.",
    "researcher":  "You are a PhD researcher. Cite sources with precise quotes.",
    "distiller":   "Extract key facts and generate structured Q&A pairs.",
    "developer":   "You are an expert Python developer. Provide working code with type hints.",
    "critic":      "Critically analyze claims, identify gaps and contradictions.",
}
```

---

#### `CYK0Xb` — Save Notebook Note ⚠️ **Corrected in v3.0**

Saves a user-created text note to the notebook. **Not** a legacy chat RPC.
The note text is markdown and saved to the notebook's notes section.

```python
args = [notebook_id, note_markdown_text, optional_cursor_position, ...]
# Response: [[note_id, saved_note_text, ...]]
# Example: [["d4e015e3-b6f0-4deb-9024-e297a94fc2bf", "# Note title\n\nContent..."]]
```

Use this to programmatically save analysis, summaries, or extracted Q&A as
persistent notes inside the notebook.

---

#### `R7cb6c` — Generate Report / Document ⭐ **Confirmed types in v3.0**

Generates and saves a structured document (study guide, FAQ, brief, table, etc.)
from selected source IDs.

```python
source_array = [[[src_id]] for src_id in source_ids]  # triple-nested
report_body = [None, None, report_type, source_array]
args = [_WRITE_CONFIG, notebook_id, report_body]
# Response: [[report_id, title, type_int, [[source_id_arrays]], ...]]
```

**Confirmed report type codes:**
| `report_type` | Format | Confirmed |
|--------------|--------|-----------|
| `2`          | Research brief / summary | ✅ HAR confirmed |
| `9`          | Free-form notes | ✅ HAR confirmed |
| `3`–`8`      | Study guide, FAQ, Timeline, Outline, Glossary | Inferred |

---

#### `ciyUvf` — Generate Suggested Report Preview

Generates a report preview (title + description) from selected sources.
The response is a suggestion — call `R7cb6c` to save it.

```python
source_id_arrays = [[src_id] for src_id in source_ids]  # double-nested
args = [_WRITE_CONFIG, notebook_id, source_id_arrays]
# Response: [[[preview_id, title, description, [[source_ids]], ...]]]
```

---

#### `cFji9` — Generate / Get Mind Map ⚠️ **Corrected in v3.0**

Generates or retrieves a mind map for the notebook. Returns a JSON string
(D3-compatible hierarchical tree) stored as a notebook artifact.

```python
args = [notebook_id, None, cursor_timestamp, [2]]
# cursor_timestamp: [unix_sec, nano_sec] for cache staleness check, or None
# Response: [[[mind_map_id, [mind_map_id, json_tree_string]]]]
```

**Mind map JSON structure:**
```json
{
  "name": "Root Topic",
  "children": [
    {"name": "Subtopic A", "children": [{"name": "Leaf"}]},
    {"name": "Subtopic B", "children": [...]}
  ]
}
```
**Not** a conversation history RPC as previously documented. The mind map is
the interactive visual in the NLM "Studio" panel.

---

#### `Ljjv0c` — Start Fast Research Session ⭐ **New in v3.0**

Initiates a Fast Research session — NLM searches the web for sources related
to a query. Returns a `research_session_id` used by `LBwxtb` to add the
discovered sources to the notebook.

```python
args = [[search_query, 1], None, 1, notebook_id]
# Response: [research_session_id]
# Example: ["22200e6d-8653-43c7-bedc-cdf6c6a787fb"]
```

The `1` flag in `[search_query, 1]` indicates search type (web search).
The standalone `1` after `None` appears to be a request mode flag.

---

#### `LBwxtb` — Add URL Sources (Batch) ⭐ **New in v3.0**

Adds one or more URL sources to a notebook. Must be called after `Ljjv0c`
to provide the `research_session_id`. After calling, poll `rLM1Ne` until all
sources have a non-zero `word_count` (processing is asynchronous).

```python
sources_array = [
    # Web URL:
    [None, None, [url, title], None, None, None, None, None, None, None, 2],
    # YouTube URL (url goes to position 7, not 2):
    [None, None, None, None, None, None, None, [youtube_url], None, None, 2],
    # PDF URL:
    [None, None, [pdf_url, title], None, None, None, None, None, None, None, 3],
]
args = [None, [1], research_session_id, notebook_id, sources_array]
# Response: [[[source_id], title, [None, word_count, [ts_sec, ts_ns],
#             [process_id, [ts_sec, ts_ns]], format_type, None, status,
#             [url], char_count], [None, 2]]]
```

**Source position cheatsheet:**
| Position in source entry | Web URL | YouTube |
|--------------------------|---------|---------|
| `[2]` | `[url, title]` | `None` |
| `[7]` | `None` | `[url]` |

**Can `LBwxtb` be called without a prior `Ljjv0c`?** Unconfirmed — all observed
calls included a valid `research_session_id`. Test with a dummy/empty session ID
to determine if it is strictly required.

---

### Proto / gRPC Endpoints

#### `GenerateFreeFormStreamed` — Fast Research Report ⭐ **New in v3.0**

Generates the AI research report from Fast Research sources. Uses a different
transport from batchexecute — this is a server-streaming gRPC call over HTTP/1.1.

**URL:**
```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
  google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/
  GenerateFreeFormStreamed
?bl=<build_label>&f.sid=<session_id>&hl=en&_reqid=<reqid>&rt=c
```

**Request body (URL-encoded `f.req`):**
```python
inner_args = [
    [[[src_id]] for src_id in source_ids],  # position 0: source ID arrays
    question_text,                           # position 1: research question
    None,                                    # position 2: reserved
    [2, None, [1], [1]],                    # position 3: generation config
    conv_thread_id,                          # position 4: conversation thread (from CCqFvf)
    None,                                    # position 5: reserved
    None,                                    # position 6: reserved
    notebook_id,                             # position 7: target notebook
    # ... additional None fields
]
f_req = [None, json.dumps(inner_args)]
```

**Response:** Streaming SSE — same `)]}'` prefix, `wrb.fr` chunks with
`null` as the RPC ID (since it's not a batchexecute call). Returns the
research narrative in markdown chunks, citations, and a final turn ID.

**Fast Research full flow:**
```python
# 1. Start fast research (web search)
session_id = fast_research_start(notebook_id, query, cookies)  # Ljjv0c

# 2. Add discovered sources
sources = add_url_sources(notebook_id, session_id, url_list, cookies)  # LBwxtb

# 3. Poll until all sources processed
wait_for_sources(notebook_id, cookies)  # rLM1Ne polling

# 4. Generate the research report (streaming)
report = generate_free_form(notebook_id, source_ids, question, thread_id, cookies)
# → GenerateFreeFormStreamed

# 5. Store in Nexus
nexus.add_entry(query, report, content_type="research")
```

---

### Operations Not Yet Captured

These operations exist in the NLM UI but were not captured in any of the 8 HARs.
A fresh HAR where these specific actions are performed is needed.

| Operation | Status | Notes |
|-----------|--------|-------|
| **Delete Notebook** | ❌ Unknown RPC | Never performed during capture |
| **Delete Source** | ❌ Unknown RPC | Never performed during capture |
| **Rename Notebook** | ❌ Unknown RPC | Never performed during capture |
| **Add Text Source** (paste text) | ❌ Unknown RPC | Never performed during capture |
| **Add File Source** (upload PDF) | ❌ Likely multipart | May be a separate `/upload` endpoint |
| **Generate Audio Overview** | ❌ Unknown RPC | `sqTeoe` lists types but trigger unknown |
| **Audio Overview Status Poll** | ❌ Unknown RPC | Needed for completion detection |
| **Share Notebook** | ❌ Unknown RPC | Never performed during capture |
| **Add Google Drive source** | ❌ Partially known | `ub2Bae` response shows Drive sources (format 1) |

**To capture missing RPCs:** Export a HAR while performing each operation above.
Enable "Include sensitive data" checkbox in Chrome DevTools HAR export.

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

Complete route reference for the proxy at `http://localhost:8800`. All routes
return JSON. Routes requiring auth return `503` with `{"error":"no_cookies"}`
if no cookies are stored.

### Authentication & Setup

```bash
# ── Health check ──────────────────────────────────────────────────────
GET http://localhost:8800/health
# Response: {"status":"ok","cookie_count":12,"bl":"boq_...","bl_age_days":3,
#            "bl_stale":false,"rpc_catalog_version":"v3.0","known_rpcs":21,
#            "rate_limit_seconds":1.5,"registry_available":true}

# ── Import cookies from HAR file ──────────────────────────────────────
POST http://localhost:8800/cookies/import
Content-Type: application/json
Body: {"har_path": "/absolute/path/to/notebooklm.har"}
# OR multipart: field "har_file" with the .har file upload
# Response: {"imported_cookies":12,"total_cookies":12,"bl":"boq_...","status":"ok"}

# ── Auto-capture cookies via Chrome CDP (recommended) ─────────────────
POST http://localhost:8800/cookies/capture
# Requires Chrome running with --remote-debugging-port=9222
# Response: {"imported_cookies":12,"bl":"boq_...","f_sid":"..."}

# ── Refresh f.sid and at token (no new HAR needed) ────────────────────
POST http://localhost:8800/cookies/refresh
# Fetches the NLM page with stored cookies, extracts fresh tokens
# Response: {"refreshed":true,"f_sid":"...","at_present":true,"bl":"boq_..."}

# ── List stored cookie names ──────────────────────────────────────────
GET http://localhost:8800/cookies
# Response: {"count":12,"names":["SID","SSID",...],"has_cookies":true}

# ── Clear all stored cookies ──────────────────────────────────────────
DELETE http://localhost:8800/cookies
# Response: {"cleared":true}

# ── Read current build label and session metadata ─────────────────────
GET http://localhost:8800/meta
# Response: {"bl":"boq_labs-tailwind-frontend_20260226.08_p0","f_sid":"...","at":"..."}

# ── Update build label or f.sid manually ─────────────────────────────
POST http://localhost:8800/meta
Content-Type: application/json
Body: {"bl": "boq_labs-tailwind-frontend_YYYYMMDD.NN_p0", "f_sid": "12345678"}
# Response: {"updated":true,"bl":"...","f_sid":"..."}
```

### Notebook Operations

```bash
# ── List all notebooks ────────────────────────────────────────────────
GET http://localhost:8800/notebooks
# → ub2Bae RPC
# Response: {"notebooks":[{"id":"uuid","name":"Notebook Title"}],"count":5}

# ── Create a notebook (client-side UUID, backend lazy-creation) ────────
POST http://localhost:8800/notebooks
Content-Type: application/json
Body: {"title": "My Research Notebook"}
# Response: {"notebook_id":"uuid-v4","title":"My Research Notebook",
#            "message":"Notebook UUID reserved. Add sources to materialise on NLM backend.",
#            "warning":"Backend record is created lazily — call POST /notebooks/<id>/sources next."}
# HTTP 201

# ── Get full notebook data (summary + sources + notes + conversations) ─
GET http://localhost:8800/notebooks/<notebook_id>
# → VfAZjd + wXbhsf + gArtLc + cFji9 RPCs
# Response: {"notebook_id":"...","notebook_name":"...","summary":"...",
#            "sources":[...],"notes":[...],"conversations":[...],"stats":{...}}

# ── Get raw full notebook info blob ──────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/content
# → e3bVqc RPC — returns 80–100 KB blob, documents extracted
# Response: {"documents":[...],"count":N}
```

### Source Operations

```bash
# ── List sources in a notebook ────────────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/sources
# → wXbhsf RPC
# Response: {"notebook_name":"...","sources":[{"id":"...","title":"...","url":"...",
#            "word_count":1234,"source_type":5}],"count":N}

# ── Add URL sources (starts fast research session, then adds sources) ──
POST http://localhost:8800/notebooks/<notebook_id>/sources
Content-Type: application/json
Body: {
  "urls": [
    {"url": "https://example.com/article", "title": "Optional Title"},
    {"url": "https://www.youtube.com/watch?v=abc", "title": "YT Video"}
  ],
  "query": "multi-agent AI systems",
  "session_id": "optional — omit to auto-start a Ljjv0c session"
}
# → Ljjv0c (if no session_id) + LBwxtb RPCs
# Response: {"added":2,"session_id":"uuid","notebook_id":"...","poll_url":"/notebooks/.../sources/wait"}

# ── Poll source processing completion ─────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/sources/wait
# Query params: timeout=60 (max 300), interval=3 (min 2)
# → rLM1Ne RPC polled until all word_count > 0
# Response: {"ready":true,"sources":[...],"pending_count":0,"elapsed_seconds":12.3}

# ── Read full text content of a single source ─────────────────────────
GET http://localhost:8800/sources/<source_id>/content
# → tr032e RPC
# Response: {"source_id":"...","content":"markdown text...","word_count":1547}
```

### Summary & AI Features

```bash
# ── Get AI overview summary of a notebook ────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/summary
# → VfAZjd RPC
# Response: {"notebook_id":"...","summary":"Markdown overview text..."}

# ── Get or generate the mind map (D3 JSON) ────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/mindmap
# → cFji9 RPC
# Response: {"notebook_id":"...","mindmap":{"name":"Root","children":[...]}}
```

### Notes & Artifacts

```bash
# ── List saved notes/artifacts ────────────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/notes
# → gArtLc RPC (excludes ARTIFACT_STATUS_SUGGESTED)
# Response: {"notes":["Study guide text..."],"count":N}

# ── Generate a report preview (ciyUvf) ────────────────────────────────
POST http://localhost:8800/notebooks/<notebook_id>/generate
Content-Type: application/json
Body: {"source_ids": ["uuid1", "uuid2"], "doc_type": 2}
# → ciyUvf RPC
# Response: {"title":"Report Title","description":"Summary...","source_ids":[...]}

# ── Save a report/note artifact ───────────────────────────────────────
POST http://localhost:8800/notebooks/<notebook_id>/save_note
Content-Type: application/json
Body: {"source_ids": ["uuid1", "uuid2"], "note_type": 9}
# → R7cb6c RPC — note_type: 2=brief, 9=notes
# Response: {"note_id":"uuid","title":"Note Title","note_type":9}
```

### Conversation Threads

```bash
# ── Get conversation history (thread IDs + all messages) ─────────────
GET http://localhost:8800/notebooks/<notebook_id>/history
# Query params: page_size=20
# → hPTbtc (thread IDs) + khqZz (messages) RPCs
# Response: {"threads":[{"thread_id":"uuid","messages":["Q text","A text"]}],
#            "count":1,"notebook_id":"..."}

# ── Get conversation thread IDs only ─────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/threads
# Query params: page_size=20
# → hPTbtc RPC
# Response: {"threads":[{"thread_id":"f3acda91-..."}],"count":1,"notebook_id":"..."}

# ── Read messages in a single thread ─────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/threads/<thread_id>
# Query params: page_size=20
# → khqZz RPC
# Response: {"thread_id":"...","messages":["User question","Assistant answer"],"count":4}

# ── Legacy conversation endpoint (uses cFji9 mind-map RPC, limited) ──
GET http://localhost:8800/notebooks/<notebook_id>/conversations
# → cFji9 RPC (note: this is the mind map RPC, returns partial text)
# Prefer /history or /threads + /threads/<id> for accurate conversation data
# Response: {"conversations":[...],"count":N}
```

### Ask / Chat (Write)

```bash
# ── Ask with inline citations (synchronous) ───────────────────────────
POST http://localhost:8800/notebooks/<nb_id>/ask
Content-Type: application/json
Body: {"question": "What is the main argument?", "mode": "annotate"}
# → CYK0Xb RPC — synchronous, answer returned immediately with [source_id] citations
# Response: {"answer_id":"uuid","answer":"The main argument is... [src_uuid]","sources":["uuid"]}

# ── Chat with role config (asynchronous) ─────────────────────────────
POST http://localhost:8800/notebooks/<nb_id>/ask
Content-Type: application/json
Body: {
  "question": "Summarize the key findings",
  "mode": "chat",
  "role": "Act as a PhD researcher providing thorough analysis with citations",
  "response_length": 4
}
# → s0tc2d RPC — async, answer arrives in conversation thread
# Response: {"queued":true,"notebook_title":"...","notebook_id":"...","question":"..."}
# Then: GET /notebooks/<nb_id>/history to retrieve the answer

# ── Batch ask — up to 5 questions per HTTP request ────────────────────
POST http://localhost:8800/notebooks/<nb_id>/ask_batch
Content-Type: application/json
Body: {
  "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"],
  "mode": "annotate",
  "max_batch": 5
}
# → Multiple CYK0Xb (or s0tc2d if mode=chat) packed in one batchexecute call
# Response: {"answers":[{...},{...}],"count":5,"questions":[...],"mode":"annotate"}

# ── Chat (s0tc2d dedicated endpoint) ─────────────────────────────────
POST http://localhost:8800/notebooks/<nb_id>/chat
Content-Type: application/json
Body: {
  "question": "What are the key techniques?",
  "role": "You are a PhD researcher. Cite sources precisely.",
  "response_length": 4
}
# → s0tc2d RPC (async)
# Response: {"queued":true,"notebook_title":"...","note":"s0tc2d queues the response. Poll /conversations for answer."}

# ── Batch chat ────────────────────────────────────────────────────────
POST http://localhost:8800/notebooks/<nb_id>/chat_batch
Content-Type: application/json
Body: {
  "questions": ["Q1?", "Q2?", "Q3?"],
  "role": "Act as a teacher explaining to a student",
  "response_length": 4,
  "max_batch": 5
}
# → Multiple s0tc2d calls packed in one request
# Response: {"results":[...],"queued_count":3,"count":3,"questions":[...]}
```

### Research Workflow

```bash
# ── Start a fast research session (web search) ────────────────────────
POST http://localhost:8800/notebooks/<nb_id>/research
Content-Type: application/json
Body: {"query": "multi-agent AI systems 2025"}
# → Ljjv0c RPC
# Response: {"session_id":"22200e6d-...","notebook_id":"...","query":"..."}
# Then use session_id in POST /notebooks/<nb_id>/sources to add sources
```

### User Info

```bash
# ── User profile + queries remaining ─────────────────────────────────
GET http://localhost:8800/user/profile?notebook_id=<optional_nb_id>
# → JFMDGd RPC
# Response: {"email":"user@gmail.com","name":"Display Name",
#            "queries_remaining":1000,"notebook_id":"..."}

# ── Account quota and plan tier ───────────────────────────────────────
GET http://localhost:8800/user/quota
# → ozz5Z RPC
# Response: {"quota_data":[...],"extracted":["NotebookLM Plus","..."]}
```

### Rate Limiting

```bash
# ── Check current rate limit ──────────────────────────────────────────
GET http://localhost:8800/rate_limit
# Response: {"min_gap_seconds":1.5,"config_key":"notebooklm.rate_limit_seconds"}

# ── Override rate limit for this session ─────────────────────────────
POST http://localhost:8800/rate_limit
Content-Type: application/json
Body: {"seconds": 2.0}
# Clamped to [0.5, 30.0] range
# Response: {"min_gap_seconds":2.0}
```

### RPC Registry & Direct Calls

```bash
# ── Check RPC registry status ─────────────────────────────────────────
GET http://localhost:8800/rpc_registry
# Response: {"available":true, ...registry report fields...}
# If nlm_rpc_mapper.py not installed: {"available":false}

# ── Call any RPC directly (testing/exploration) ───────────────────────
POST http://localhost:8800/rpc/<rpc_id>
Content-Type: application/json
Body: {"args": "[\"notebook_id\",[2]]", "notebook_id": "uuid"}
# Response: {"rpc_id":"VfAZjd","data":[[[" overview text..."]]]}

# Example — get AI overview via raw RPC call:
curl -X POST http://localhost:8800/rpc/VfAZjd \
  -H "Content-Type: application/json" \
  -d '{"args": "[\"bec06e03-7cf2-4989-bf17-bcb0ac9927a0\",[2]]",
       "notebook_id": "bec06e03-7cf2-4989-bf17-bcb0ac9927a0"}'
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
   Use `hPTbtc` to get the thread ID, then `khqZz` to read the answer. Or poll
   `GET /notebooks/<id>/history` via the proxy for a simpler interface.

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

---

## Rate Limiter Behaviour

All outbound calls to `notebooklm.google.com` pass through the `_RateLimiter`
class, which enforces a minimum gap between consecutive requests.

| Setting | Default | Range | Source |
|---------|---------|-------|--------|
| `min_gap_seconds` | `1.5` | `0.5–30.0` | `config/default.yaml` → `notebooklm.rate_limit_seconds` |

**Important behaviours:**
- Batch calls (multiple RPCs in one HTTP request) count as **one request** for
  rate-limiting purposes — this is the correct way to maximise throughput.
- The limiter uses a thread lock (`threading.Lock`) so concurrent proxy requests
  queue correctly.
- Aggressive calls (e.g. `> 40 questions/minute`) may trigger Google soft-limits.
  If you observe empty/null responses, increase the gap: `POST /rate_limit {"seconds": 2.5}`.
- Rate limit is **per-process** — restarting the proxy resets it to the config value.
- Dynamic override (API) is **session-only** — restarting resets to config value.

**Recommended settings by use case:**
```yaml
# config/default.yaml
notebooklm:
  rate_limit_seconds: 1.5   # default — good for interactive use
  rate_limit_seconds: 3.0   # conservative — for overnight batch jobs
  rate_limit_seconds: 0.8   # aggressive — only for testing, may hit soft limits
```

---

*Last updated: 2026-02-28 | Version 3.0 | 21 RPCs confirmed across 8 HAR capture sessions*

