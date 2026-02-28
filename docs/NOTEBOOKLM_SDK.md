# NotebookLM SDK — Complete Protocol Documentation

> **Version:** 3.3 (2026-03-01 — CREATE_NOTE/SAVE_NOTE confirmed, SYNC_NOTES corrected, tr032e GET_SOURCE_SUMMARY discovered)
> **Status:** Production implementation in `engine/mcp/nlm_live_proxy.py`
> **New in 3.3:** `CYK0Xb`=CREATE_NOTE confirmed `[nb_id,html,[1],null,title,null,[2]]`;
> `cYAfTb`=SAVE_NOTE (live auto-save, CORRECTION — was mislabelled GET_SOURCE_STATUS_DETAIL);
> `cFji9`=SYNC_NOTES delta poll (CORRECTION — was labelled NOTEBOOK_HEARTBEAT);
> `tr032e`=GET_SOURCE_SUMMARY `[[[[source_id]]]]` → AI markdown summary (NEW — never seen before);
> `sqTeoe`=GET_AUDIO_OPTIONS → Deep dive/Brief/Critique/Debate formats;
> `gArtLc`=GET_ARTIFACTS with SQL-like filter string; `khqZz`=LIST_NOTES;
> New routes: `POST /notebooks/<id>/notes`, `PUT /notebooks/<id>/notes/<note_id>`,
> `GET /notebooks/<id>/notes/sync`, `GET /notebooks/<id>/audio-options`,
> `GET /sources/<id>/summary`. 22 RPCs now fully mapped (3 still unconfirmed).
> **New in 3.2:** `izAoDd` text paste sources, file upload flow (o4cbdc + /upload/_/),
> 10 new RPCs, ZwVcOc corrected to GET_USER_PLAN.
> **New in 3.1:** 3 RPC mappings corrected (`s0tc2d`, `LBwxtb`, `QA9ei`), 2 new RPCs discovered
> (`izAoDd`, `tGMBJ`), `GenerateFreeFormStreamed` confirmed as the real chat endpoint,
> Deep Research flow documented, Download/Archive routes added, YouTube encoding clarified.
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
- `CYK0Xb` is the synchronous annotate/Q&A RPC — returns markdown with `[source_id]` citations.
- **`s0tc2d` is NOT chat** — it renames the notebook. Every "chat" call in v2.x and v3.0
  that used `s0tc2d` was silently renaming the notebook.
- **`GenerateFreeFormStreamed`** is the real chat endpoint — a gRPC/proto call at a different URL.
- Multi-question batching: 5 RPCs per HTTP request → 5× throughput.
- The proxy at :8800 wraps all of this in a clean REST API.

---

## ⚠️ What's New in v3.1 — Critical Corrections

> **Three RPC mappings were WRONG in v3.0 and have been corrected based on 2026-02-28 HAR
> analysis. If you shipped code using these RPCs for the described purposes, it was silently
> doing the wrong thing.**

### Corrected RPC Mappings

| RPC | v3.0 (WRONG) | v3.1 (CORRECT) | Impact |
|-----|-------------|----------------|--------|
| `s0tc2d` | `RPC_CHAT_MESSAGE` — used to "send chat" | `RPC_RENAME_NOTEBOOK` | Every "chat" call via this RPC was silently renaming the notebook |
| `LBwxtb` | "add URL sources batch" — used to add web/YouTube URLs | `RPC_ADD_RESEARCH_SOURCE` — adds AI-generated research docs as sources | URL sources must use `izAoDd` (new) |
| `QA9ei` | "Add Text Source" — listed as unknown | `RPC_START_DEEP_RESEARCH` — starts deep research, returns `session_id` | Deep Research flow now fully documented |

### New RPCs Discovered in v3.1

| RPC | Operation | Notes |
|-----|-----------|-------|
| `izAoDd` | `RPC_ADD_SOURCE` | Add URL or YouTube video as a source. Replaces the role `LBwxtb` was incorrectly assumed to play. |
| `tGMBJ` | `RPC_DELETE_SOURCE` | Delete a source from a notebook. |

### Real Chat Endpoint Confirmed

`GenerateFreeFormStreamed` is **NOT** a batchexecute RPC. It is a gRPC/proto endpoint at a
completely separate URL. Every prior attempt to "chat" using `s0tc2d` was renaming the notebook
to the question text. See the [GenerateFreeFormStreamed](#generatefreefromstreamed--nlm-chat-proto-endpoint)
section for the correct payload format.

### v3.1 RPC Count: 25 batchexecute RPCs + 1 proto endpoint

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

**25 unique RPCs confirmed + 1 proto endpoint (v3.1).** Operations are divided into
Read (data retrieval), Write (mutations), and the proto chat endpoint.

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
takes an explicit `notebook_id`. Used as a **polling RPC** after adding sources
via `izAoDd` or `LBwxtb` — call repeatedly until all newly added sources have
a non-zero `word_count`.

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
> (e.g. `izAoDd`). To create a notebook programmatically: generate a UUID v4,
> call `izAoDd` with it as the `notebook_id` — this implicitly creates it.

---

#### `tr032e` — Read Full Source Text ⭐ **Clarified in v3.1**
```python
args = [[[[source_id]]]]  # source_id wrapped in 3 nested lists
# Response: [[[None, [source_markdown_text]]]]
```
Returns the full extracted text of a source in markdown format. This is the
complete source content — not an AI summary. Useful for programmatic extraction
of source text into Nexus or for offline processing.

> **v3.0 incorrectly described this as "Get Source AI Summary".** The response is
> the raw source text (as rendered by NLM's document parser), not an AI-generated
> summary. `VfAZjd` is the RPC that returns the AI-generated notebook overview.

---

### Write RPCs

#### `s0tc2d` — Rename Notebook ⭐ **v3.1 CORRECTED** (was wrongly described as chat)

> **⚠️ BREAKING CORRECTION:** In v3.0 this was documented as `RPC_CHAT_MESSAGE`.
> HAR analysis on 2026-02-28 confirmed it is `RPC_RENAME_NOTEBOOK`. Any code
> that used `s0tc2d` to "chat" with a notebook was silently renaming the notebook
> to the question text. See `GenerateFreeFormStreamed` for the real chat interface.

```python
args = [notebook_id, [[None, None, None, [None, "new_name"]]]]
# Response: echoes the rename operation metadata
```

Use this to rename a notebook programmatically:
```python
# Rename a notebook
rename_args = json.dumps([notebook_id, [[None, None, None, [None, "My New Title"]]]])
f_req = [["s0tc2d", rename_args, None, "generic"]]
```

---

#### `CYK0Xb` — Save Note / Annotate with Citations ⚠️ **Clarified in v3.1**

Synchronous citation Q&A. Submits a question and gets an immediate markdown
response with inline `[source_id]` citation references. Also used to save
user-created text notes to the notebook's notes section.

```python
args = [notebook_id, question_text]
# Response: [[note_id, answer_markdown_with_citations, ...]]
# Example: [["d4e015e3-b6f0-4deb-9024-e297a94fc2bf",
#            "The main argument is... [src-uuid1] as further supported by [src-uuid2]"]]
```

This is the preferred RPC for **programmatic Q&A extraction** because:
- Response is synchronous — answer returned in the same HTTP request
- Citations are embedded as `[source_uuid]` tokens in the markdown
- Answer is stored as a notebook note artifact

Use `GenerateFreeFormStreamed` for interactive multi-turn chat.

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

#### `LBwxtb` — Add Research Source ⭐ **v3.1 CORRECTED** (was wrongly "add URL batch")

> **⚠️ BREAKING CORRECTION:** In v3.0 this was documented as adding URL sources.
> It actually adds an **AI-generated research document** produced by Deep Research
> (`QA9ei`) as a notebook source. To add URL/YouTube sources, use `izAoDd` (new in v3.1).

Adds the AI-generated document from a completed Deep Research session as a source
in the notebook. Called after `QA9ei` once the research content is available.

```python
args = [None, [1], session_id, notebook_id, [[None, [title, content]]]]
# session_id: returned by QA9ei (START_DEEP_RESEARCH)
# title: display name for the AI-generated source
# content: the AI research document text
# Response: [[[source_id], title, [None, word_count, ...]]]
```

See the [Deep Research Flow](#deep-research-flow) section for the complete usage pattern.

---

#### `QA9ei` — Start Deep Research ⭐ **v3.1 CORRECTED** (was wrongly "Add Text Source")

> **⚠️ BREAKING CORRECTION:** In v3.0 this was listed as unknown ("Add Text Source").
> HAR analysis on 2026-02-28 confirmed it is `RPC_START_DEEP_RESEARCH`.

Initiates an asynchronous Deep Research session. NLM generates a comprehensive
AI research document on a given topic. Returns a `session_id` used by `LBwxtb`
to add the resulting document as a source.

```python
args = [None, [1], ["topic_query", 1], 5, notebook_id]
# "topic_query": the research topic
# 5: depth/iteration count (controls research thoroughness)
# Response: [session_id]
# Example: ["a3f8c021-94b2-4e11-bc3a-0f9d72e1aa87"]
```

The `session_id` is used in the subsequent `LBwxtb` call to attach the
AI-generated document to the notebook as a source.

---

#### `izAoDd` — Add Source ⭐ **v3.1 NEW** — add URL or YouTube video

Adds a single URL or YouTube video as a source to a notebook. This is the correct
RPC for adding web sources (replaces the misidentified role of `LBwxtb`).

```python
_SOURCE_CONFIG = [2, None, None,
    [1, None, None, None, None, None, None, None, None, None, [1]],
    [[2, 1]]
]

# Regular URL source:
source_obj = [None, None, url, None, None, None, None, None, None, None, 1]
# YouTube source (URL at position 7, not 2):
source_obj = [None, None, None, None, None, None, None, [url], None, None, 1]

args = [[[source_obj]], notebook_id, [2], _SOURCE_CONFIG]
# Response: [[[source_id], title, [None, word_count, [ts_sec, ts_ns],
#             [process_id, [ts_sec, ts_ns]], format_type, None, status,
#             [url], char_count], [None, 2]]]
```

After calling, poll `rLM1Ne` until `word_count > 0` (processing is asynchronous).

See [YouTube Source Encoding](#youtube-source-encoding) for the full position reference.

---

#### `tGMBJ` — Delete Source ⭐ **v3.1 NEW**

Deletes a source from a notebook.

```python
args = [[[source_id]], [2]]
# source_id: UUID of the source to delete
# Response: confirms deletion
```

---

### Proto / gRPC Endpoints

#### `GenerateFreeFormStreamed` — NLM Chat (Proto Endpoint) ⭐ **v3.1 CONFIRMED as real chat**

> **⚠️ KEY FINDING:** This is the **REAL NLM chat interface**, not a research-report
> generator as documented in v3.0. Every prior "chat" via `s0tc2d` was renaming the
> notebook. This endpoint handles all multi-turn conversational interactions.

Uses a different transport from batchexecute — this is a server-streaming gRPC call
over HTTP/1.1. Auth uses **cookies only** (no `at` token in the body).

**URL:**
```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
  google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/
  GenerateFreeFormStreamed
?bl=<build_label>&rt=c
```

> Note: `f.sid` and `_reqid` are NOT required for this endpoint (unlike batchexecute).

**Request body (URL-encoded `f.req`):**
```python
# Inner payload — 9-element array
inner_args = [
    [[[src_id]] for src_id in source_ids],  # [0]: source context — all source IDs
    question_text,                           # [1]: the question / user message
    None,                                    # [2]: reserved
    [2, None, [1], [1]],                    # [3]: response config (always this value)
    thread_id,                               # [4]: thread UUID — same = continue, new = fresh
    None,                                    # [5]: reserved
    None,                                    # [6]: reserved
    notebook_id,                             # [7]: notebook UUID
    1,                                       # [8]: mode flag (always 1)
]
# Outer payload wraps inner as JSON string:
f_req = [None, json.dumps(inner_args)]
body = urllib.parse.urlencode({"f.req": json.dumps(f_req)}).encode()
```

**Payload field reference:**

| Position | Field | Value | Notes |
|----------|-------|-------|-------|
| `[0]` | `source_context` | `[[[src_id1]], [[src_id2]], ...]` | All source IDs triple-wrapped |
| `[1]` | `question` | string | The user's question |
| `[2]` | reserved | `None` | Always None |
| `[3]` | `response_config` | `[2, None, [1], [1]]` | Always this exact value |
| `[4]` | `thread_id` | UUID string | Same UUID = continue conversation; new UUID = fresh thread |
| `[5]` | reserved | `None` | Always None |
| `[6]` | reserved | `None` | Always None |
| `[7]` | `notebook_id` | UUID string | Target notebook |
| `[8]` | mode | `1` | Always 1 |

**Response — SSE-like streaming:**

Each chunk contains the **FULL TEXT SO FAR** (not deltas). Parse as follows:

```python
# Strip XSSI prefix
raw = response_text.lstrip(")]}'").lstrip("\n")

for line in raw.split("\n"):
    line = line.strip()
    if not line.startswith("[["):
        continue
    outer = json.loads(line)
    for item in outer:
        if item[0] == "wrb.fr":
            inner = json.loads(item[2])
            text_so_far = inner[0][0]           # Full response text accumulated so far
            turn_info   = inner[0][2]           # [thread_id, msg_id, sequence_num]
            thread_id   = turn_info[0]          # Use for next turn (multi-turn)
            msg_id      = turn_info[1]
```

**Multi-turn conversation pattern:**

```python
import uuid, json, urllib.parse, requests

def chat(notebook_id, source_ids, question, cookies, thread_id=None):
    """Send one chat turn. Returns (answer_text, thread_id) for continuation."""
    if thread_id is None:
        thread_id = str(uuid.uuid4())  # fresh conversation

    inner = [
        [[[s]] for s in source_ids],
        question,
        None,
        [2, None, [1], [1]],
        thread_id,
        None,
        None,
        notebook_id,
        1,
    ]
    f_req = [None, json.dumps(inner)]
    body = urllib.parse.urlencode({"f.req": json.dumps(f_req)}).encode()

    url = (
        "https://notebooklm.google.com/_/LabsTailwindUi/data/"
        "google.internal.labs.tailwind.orchestration.v1."
        "LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
        f"?bl={bl}&rt=c"
    )
    resp = requests.post(url, data=body, headers=headers, stream=True)

    full_text = ""
    for chunk in resp.iter_lines():
        line = chunk.decode("utf-8").strip()
        if not line.startswith("[["):
            continue
        for item in json.loads(line):
            if item[0] == "wrb.fr":
                inner_data = json.loads(item[2])
                full_text = inner_data[0][0]        # always full text, not delta
                thread_id = inner_data[0][2][0]     # thread_id for next turn

    return full_text, thread_id

# Usage — multi-turn:
text1, tid = chat(nb_id, src_ids, "What is the main thesis?", cookies)
text2, tid = chat(nb_id, src_ids, "Can you elaborate on point 2?", cookies, thread_id=tid)
text3, tid = chat(nb_id, src_ids, "How does this compare to X?", cookies, thread_id=tid)
```

---

## YouTube Source Encoding

When adding a YouTube source via `izAoDd`, the URL position differs from regular URLs:

```python
# Regular URL (web article, PDF, etc.) — URL at position 2:
source_obj = [None, None, url, None, None, None, None, None, None, None, 1]
#                         ^^^

# YouTube URL (youtube.com/watch?v= or youtu.be/) — URL at position 7:
source_obj = [None, None, None, None, None, None, None, [url], None, None, 1]
#                                                        ^^^^^

def is_youtube(url: str) -> bool:
    return "youtube.com/watch" in url or "youtu.be/" in url

def make_source_obj(url: str) -> list:
    if is_youtube(url):
        return [None, None, None, None, None, None, None, [url], None, None, 1]
    else:
        return [None, None, url, None, None, None, None, None, None, None, 1]
```

**Source type detection by URL position:**

| Position | Content | NLM format type |
|----------|---------|-----------------|
| `[2]` (string) | Web article, PDF URL | `5` (web) or `3` (PDF) |
| `[7]` (list)   | YouTube video URL   | `7` (YouTube) |

---

## Deep Research Flow

Deep Research differs from Fast Research (`Ljjv0c`) — it generates an **AI-authored
document** rather than collecting existing web pages as sources.

```
┌─────────────────────────────────────────────────────────────┐
│                    Deep Research Flow                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. POST /notebooks/<id>/research/deep                      │
│     → QA9ei RPC                                             │
│     → args: [None, [1], ["topic", 1], 5, nb_id]             │
│     → returns: session_id                                   │
│                                                             │
│  2. NLM generates AI document asynchronously               │
│     (no polling needed — generation happens server-side)    │
│                                                             │
│  3. POST /notebooks/<id>/research/source                    │
│     → LBwxtb RPC                                            │
│     → args: [None,[1],session_id,nb_id,[[None,[title,doc]]]]│
│     → adds AI document as a notebook source                 │
│                                                             │
│  4. (Optional) POST /notebooks/<id>/save_note               │
│     → R7cb6c RPC                                            │
│     → generates structured note artifact from all sources  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Python implementation:**

```python
import requests, time

BASE = "http://localhost:8800"

def deep_research_workflow(notebook_id: str, topic: str, note_type: int = 2):
    """Full deep research workflow: research → add source → save note."""

    # Step 1: Start deep research
    resp = requests.post(f"{BASE}/notebooks/{notebook_id}/research/deep",
                         json={"topic": topic})
    session_id = resp.json()["session_id"]
    print(f"Research session started: {session_id}")

    # Step 2: (NLM generates document async — give it time)
    time.sleep(15)

    # Step 3: Add the AI document as a source
    resp = requests.post(f"{BASE}/notebooks/{notebook_id}/research/source",
                         json={
                             "session_id": session_id,
                             "title": f"Deep Research: {topic}",
                             "content": None,  # proxy fetches from session
                         })
    source_id = resp.json()["source_id"]
    print(f"Research source added: {source_id}")

    # Step 4: Save as structured note (optional)
    resp = requests.post(f"{BASE}/notebooks/{notebook_id}/save_note",
                         json={"source_ids": [source_id], "note_type": note_type})
    note = resp.json()
    print(f"Note saved: {note['title']} ({note['note_id']})")
    return note
```

**Contrast with Fast Research:**

| Aspect | Fast Research | Deep Research |
|--------|--------------|---------------|
| RPC | `Ljjv0c` → `izAoDd` | `QA9ei` → `LBwxtb` |
| Source type | Existing web pages | AI-generated document |
| Input | Search query | Research topic |
| Output | Multiple URL sources | Single AI research doc |
| Speed | Fast (URL fetch) | Slower (LLM generation) |

---

### Operations Not Yet Captured

These operations exist in the NLM UI but were not captured in any of the HAR sessions.
A fresh HAR where these specific actions are performed is needed.

| Operation | Status | Notes |
|-----------|--------|-------|
| **Delete Notebook** | ❌ Unknown RPC | Never performed during capture |
| **Add File Source** (upload PDF) | ❌ Likely multipart | May be a separate `/upload` endpoint |
| **Generate Audio Overview** | ❌ Unknown RPC | `sqTeoe` lists types but trigger unknown |
| **Audio Overview Status Poll** | ❌ Unknown RPC | Needed for completion detection |
| **Share Notebook** | ❌ Unknown RPC | Never performed during capture |
| **Add Google Drive source** | ❌ Partially known | `ub2Bae` response shows Drive sources (format 1) |

> **Resolved in v3.1 (no longer missing):** Rename Notebook (`s0tc2d`), Add URL/YouTube
> source (`izAoDd`), Delete Source (`tGMBJ`), Start Deep Research (`QA9ei`),
> Add Research Source (`LBwxtb`), Chat (`GenerateFreeFormStreamed`).

**To capture remaining RPCs:** Export a HAR while performing each operation above.
Enable "Include sensitive data" checkbox in Chrome DevTools HAR export.

---

## Multi-Question Batching

Up to 5 RPCs can be packed into a single batchexecute request:

```python
# 5 questions in one HTTP request (uses CYK0Xb for synchronous annotate)
calls = [
    ("CYK0Xb", json.dumps([notebook_id, q]))
    for q in questions[:5]
]
# Pack into f.req:
f_req = [[rpc_id, args_json, None, "generic"] for rpc_id, args_json in calls]
# rpcids URL param: "CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb"
```

> **Note:** Batching applies to batchexecute RPCs only. `GenerateFreeFormStreamed`
> (chat) is a streaming proto endpoint and cannot be batched this way.

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
#            "bl_stale":false,"rpc_catalog_version":"v3.1","known_rpcs":25,
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

# ── Add a URL or YouTube source ───────────────────────────────────────
# ⭐ v3.1: uses izAoDd (new). Replaces the old LBwxtb-based URL route.
POST http://localhost:8800/notebooks/<notebook_id>/sources
Content-Type: application/json
Body: {
  "url": "https://example.com/article",
  "title": "Optional Title"
}
# → izAoDd RPC (YouTube URLs auto-detected and encoded at position 7)
# Response: {"source_id":"uuid","title":"...","notebook_id":"...","poll_url":"/notebooks/.../sources/wait"}

# ── Poll source processing completion ─────────────────────────────────
GET http://localhost:8800/notebooks/<notebook_id>/sources/wait
# Query params: timeout=60 (max 300), interval=3 (min 2)
# → rLM1Ne RPC polled until all word_count > 0
# Response: {"ready":true,"sources":[...],"pending_count":0,"elapsed_seconds":12.3}

# ── Delete a source ───────────────────────────────────────────────────
# ⭐ v3.1 new route
DELETE http://localhost:8800/sources/<source_id>
# → tGMBJ RPC
# Response: {"deleted":true,"source_id":"..."}

# ── Read full text content of a single source ─────────────────────────
GET http://localhost:8800/sources/<source_id>/content
# → tr032e RPC — returns raw extracted source text (not AI summary)
# Response: {"source_id":"...","content":"markdown text...","word_count":1547}
```

### Download & Archive Routes ⭐ **v3.1 NEW**

Bulk export endpoints for offline processing, backup, and Nexus ingestion.

```bash
# ── Download full text of ALL sources in a notebook ───────────────────
GET http://localhost:8800/notebooks/<notebook_id>/sources/content
# → tr032e RPC called for each source
# Response: {"notebook_id":"...","sources":[{"id":"...","title":"...","content":"..."}],"count":N}

# ── Full notebook archive: sources + content + notes + threads + mindmap ─
GET http://localhost:8800/notebooks/<notebook_id>/archive
# Query params:
#   include_content=true/false  (default: true)  — read source text via tr032e
#   include_threads=true/false  (default: true)  — read conversation threads
# Response: {
#   "notebook_id": "...",
#   "notebook_name": "...",
#   "summary": "...",
#   "sources": [...],           # with full content if include_content=true
#   "notes": [...],
#   "threads": [...],           # with messages if include_threads=true
#   "mindmap": {...},
#   "exported_at": "2026-02-28T12:00:00Z"
# }

# ── Export ALL notebooks for the authenticated user ────────────────────
GET http://localhost:8800/notebooks/archive
# Query params:
#   include_content=false  (default) — metadata only; set true for full source text
# Response: {
#   "notebooks": [{"id":"...","name":"...","sources":[...],"notes":[...]}],
#   "count": 5,
#   "exported_at": "2026-02-28T12:00:00Z"
# }

# ── Export single source as plain text file download ──────────────────
GET http://localhost:8800/sources/<source_id>/export
# → tr032e RPC; returns Content-Disposition: attachment
# Response: plain text file download (Content-Type: text/plain)
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

# ── Batch ask — up to 5 questions per HTTP request ────────────────────
POST http://localhost:8800/notebooks/<nb_id>/ask_batch
Content-Type: application/json
Body: {
  "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"],
  "mode": "annotate",
  "max_batch": 5
}
# → Multiple CYK0Xb packed in one batchexecute call
# Response: {"answers":[{...},{...}],"count":5,"questions":[...],"mode":"annotate"}

# ── Chat (streaming, multi-turn) ──────────────────────────────────────
# ⭐ v3.1: uses GenerateFreeFormStreamed (proto endpoint), NOT s0tc2d.
# The old /chat and mode=chat routes that used s0tc2d were silently RENAMING
# the notebook to the question text. Use this endpoint for real chat.
POST http://localhost:8800/notebooks/<nb_id>/chat
Content-Type: application/json
Body: {
  "question": "What are the key techniques?",
  "thread_id": "optional — omit for new conversation, reuse to continue",
  "source_ids": ["uuid1", "uuid2"]   # optional — defaults to all sources
}
# → GenerateFreeFormStreamed (proto, streaming)
# Response: {"answer":"Full response text...","thread_id":"uuid","msg_id":"uuid"}
# Reuse thread_id in the next request to continue the conversation

# ── Rename notebook ───────────────────────────────────────────────────
# ⭐ v3.1: this is what s0tc2d actually does
POST http://localhost:8800/notebooks/<nb_id>/rename
Content-Type: application/json
Body: {"title": "New Notebook Name"}
# → s0tc2d RPC
# Response: {"renamed":true,"notebook_id":"...","title":"New Notebook Name"}
```

### Research Workflow

```bash
# ── Start a fast research session (web search, adds URL sources) ───────
POST http://localhost:8800/notebooks/<nb_id>/research
Content-Type: application/json
Body: {"query": "multi-agent AI systems 2025"}
# → Ljjv0c RPC (starts search session)
# Response: {"session_id":"22200e6d-...","notebook_id":"...","query":"..."}
# Then: POST /notebooks/<nb_id>/sources with the returned session_id

# ── Start a deep research session (AI-generated document) ─────────────
# ⭐ v3.1 new route
POST http://localhost:8800/notebooks/<nb_id>/research/deep
Content-Type: application/json
Body: {"topic": "transformer architecture advances 2025"}
# → QA9ei RPC
# Response: {"session_id":"a3f8c021-...","notebook_id":"...","topic":"..."}
# NLM generates the AI document asynchronously

# ── Add AI research document as a source ──────────────────────────────
# ⭐ v3.1 new route (uses corrected LBwxtb)
POST http://localhost:8800/notebooks/<nb_id>/research/source
Content-Type: application/json
Body: {
  "session_id": "a3f8c021-...",
  "title": "Deep Research: Transformer Advances 2025",
  "content": null
}
# → LBwxtb RPC
# Response: {"source_id":"uuid","title":"...","notebook_id":"..."}
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

### 2. Multi-Turn Chat via GenerateFreeFormStreamed

```python
# ⭐ v3.1: Use GenerateFreeFormStreamed for real chat — NOT s0tc2d (which renames)
import requests

BASE = "http://localhost:8800"
nb_id = "your-notebook-uuid"

# Get source IDs first
sources = requests.get(f"{BASE}/notebooks/{nb_id}/sources").json()["sources"]
src_ids = [s["id"] for s in sources]

# Start a conversation (fresh thread)
r = requests.post(f"{BASE}/notebooks/{nb_id}/chat", json={
    "question": "What are the main contributions of this work?",
    "source_ids": src_ids,
})
result = r.json()
answer = result["answer"]
thread_id = result["thread_id"]   # keep for follow-ups

# Continue the conversation (same thread)
r = requests.post(f"{BASE}/notebooks/{nb_id}/chat", json={
    "question": "Can you elaborate on contribution #2?",
    "source_ids": src_ids,
    "thread_id": thread_id,        # reuse thread for context
})
follow_up = r.json()["answer"]
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

answers = ask_questions_batch(nb_id, questions, cookies, max_batch=5)
# Note: use ask_questions_batch (CYK0Xb) for synchronous citation Q&A.
# For conversational analysis, use POST /notebooks/<nb_id>/chat instead.
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

### Full Request Example (s0tc2d — Rename Notebook)

> **⚠️ v3.1 Correction:** `s0tc2d` renames notebooks. The example below is the
> correct usage. Do NOT use this RPC to send chat messages.

```python
new_name = "My Research Notebook — Revised"
args = json.dumps([notebook_id, [[None, None, None, [None, new_name]]]])

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

1. **`s0tc2d` is RENAME, not chat** ⭐ v3.1 correction — every call to `s0tc2d` with
   a question string was renaming the notebook to that string. For conversational chat,
   use `GenerateFreeFormStreamed` (proto endpoint) via `POST /notebooks/<id>/chat`.

2. **`CYK0Xb` is synchronous Q&A with citations** — best for programmatic extraction
   where you need the answer immediately in the same HTTP response. Returns markdown
   with embedded `[source_uuid]` citation tokens.

3. **`GenerateFreeFormStreamed` uses cookies-only auth** — the `at` CSRF token is NOT
   included in the request body (unlike batchexecute RPCs). Only cookies are needed.

4. **Streaming response contains FULL TEXT, not deltas** — each SSE chunk from
   `GenerateFreeFormStreamed` replaces the previous one; do not concatenate chunks.

5. **YouTube sources use position 7** in the source object (not position 2 like web URLs).
   The proxy's `make_source_obj()` handles this automatically.

6. **Chrome 130+ redacts cookies from HAR exports** — always use CDP capture
   (`POST /cookies/capture`) or extract via the `data/nlm_cookies.json` manual method.

7. **Build label changes weekly** — implement BL monitoring and auto-refresh.
   The `bl_stale` field in `/health` is your early warning system.

8. **Batch limit** — 5 RPCs per batchexecute request is the practical limit.
   Exceeding this may cause malformed responses. `GenerateFreeFormStreamed` cannot
   be batched at all (it's a separate proto endpoint).

9. **Rate limiting** — No hard rate limit observed, but aggressive batching
   (>50 questions/minute) may trigger soft limits. Add 1–2s delays between
   large batch groups.

10. **Source UUIDs are per-notebook** — Source IDs do not transfer between notebooks.
    Always fetch source IDs from `wXbhsf` before using them in `ciyUvf` or `R7cb6c`.

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

*Last updated: 2026-02-28 | Version 3.1 | 25 RPCs + 1 proto endpoint confirmed | 3 critical corrections from v3.0*

