# NLM Reference

> Consolidated NotebookLM integration reference for CosySim.
> Covers architecture, client API, RPC catalogue, proxy routes, and multimodal workflows.

---

## 1. Overview

CosySim uses Google NotebookLM as a free Gemini intelligence layer for knowledge distillation, research, and Q&A. Control is via a browser-attached auth + private RPC stack:

- Live Chrome session on CDP port `9222`
- Cookie/session harvesting (`scripts\har_capture.py`, `python -m scripts.argus.tools tokens`)
- HAR import for rebuilding or inspecting exact browser traffic
- Direct private RPC access via `engine.integrations.nlm_direct_client` and `engine.mcp.nlm_live_proxy`

**Configuration** (`config/default.yaml`):

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

---

## 2. Architecture

```
CosySim skill / agent
        |
        +-- browser-attached auth refresh
        |      +-- scripts/har_capture.py
        |      +-- python -m scripts.argus.tools tokens
        |
        +-- engine/integrations/nlm_direct_client.py
        |
        +-- engine/mcp/nlm_live_proxy.py   (Flask :8800 -- batchexecute RPC bridge)
                       |
                       v  HTTPS
              notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
               (using live browser cookies + NotebookLM session metadata)
```

**Higher-level abstractions:**

| Module | Purpose |
|--------|---------|
| `engine/nexus/nlm_engine.py` | Unified NLM client with stats tracking |
| `engine/nexus/nlm_notebook_manager.py` | Named notebook fleet management |
| `engine/nexus/nlm_qa_distiller.py` | Batch Q&A distillation to Nexus |
| `engine/nexus/nlm_router.py` | 4-tier query router (cache -> FTS -> NLM -> LLM) |
| `engine/nexus/bootstrap_notebooks.py` | Control notebook seeding and scheduled refresh |
| `engine/nexus/notebooklm_flywheel.py` | Two-pass control-notebook artifact generator |

### Control Notebook Flywheel

The `copilot-system-control` notebook is treated as a control-plane orchestrator:

1. `bootstrap_notebooks.py` refreshes notebook sources and keeps the browser-bundle seed current.
2. `notebooklm_flywheel.py` asks grounded control questions, then runs a second strict-JSON report prompt to produce a structured artifact.
3. The artifact is stored in Nexus (full artifact, compact startup context packet, raw NLM report).
4. Parsed tasks are pushed into `engine/nexus/task_scheduler.py`.
5. Q&A, task envelopes, and conversation turns are pushed into `engine/nexus/training_flywheel.py`.
6. `engine/nexus/copilot_bridge.py` loads the latest control-flywheel startup packet into onboarding as `control_context_packet`.

Scheduler tasks:
- `notebook-bootstrap` -- weekly notebook refresh + immediate control follow-up
- `control-notebook-flywheel` -- recurring control-plane artifact refresh every 8 hours

---

## 3. Authentication

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

### Cookie Acquisition Methods

**1. Chrome CDP (recommended)**
```powershell
python scripts\har_capture.py --mode cdp --account knack112358 --services notebooklm,colab
```
Attaches to the running Chrome tab on port `9222`, refreshes cookies, captures session metadata (`bl`, `f_sid`, `at`), writes to `data\accounts\pool.json`.

**2. ARGUS token harvesting**
```powershell
python -m scripts.argus.tools tokens --account knack112358
```

**3. Browser-attached notebook ingest**
```powershell
python scripts\nlm_ingest.py --file docs\ARGUS.md --name "ARGUS Docs"
python scripts\nlm_ingest.py --file docs\ARGUS.md --name "ARGUS Docs" --notebook-url https://notebooklm.google.com/notebook/<id>
```

**4. HAR import / recovery**
```bash
curl -X POST http://localhost:8800/cookies/import \
     -H "Content-Type: application/json" \
     -d '{"har_path": "C:\\path\\to\\capture.har"}'
```

### Cookie File Format (`data/accounts/pool.json`)

```json
{
  "knack112358": {
    "notebooklm": {
      "cookies": {
        "SAPISID": "value", "SID": "value", "APISID": "value",
        "HSID": "value", "SSID": "value", "NID": "value",
        "SIDCC": "value", "__Secure-1PSID": "value",
        "__Secure-1PAPISID": "value", "__Secure-1PSIDCC": "value",
        "__Secure-3PSID": "value", "__Secure-3PAPISID": "value",
        "SOCS": "value"
      },
      "extracted_at": "2026-03-05T04:07:19",
      "source": "har"
    }
  }
}
```

### Build Label (BL) Management

Format: `boq_labs-tailwind-frontend_YYYYMMDD.NN_p0`

- Changes roughly weekly with Google frontend deployments
- If stale (>8 days), requests may return 404 or malformed responses
- Stored in `data/nlm_meta.json` alongside `bl_updated_at`
- Auto-extracted from imported HARs
- Check staleness: `GET /health` returns `bl_age_days` and `bl_stale`

### CORS / Origin Restrictions

- Client sets `origin: https://notebooklm.google.com`
- Sets `referer` to a real notebook URL
- `x-same-domain: 1` header confirms "same domain"

### Bot Detection (HPKE)

- `x-browser-validation` header uses HPKE encryption of browser attestation
- Current clients omit this header -- NLM accepts requests without it
- If enforcement increases, the scheme is known (P256-HKDF-SHA256/AES-128-GCM)

---

## 4. Client API -- NLMDirectClient

### Initialization

```python
from engine.integrations.nlm_direct_client import get_nlm_direct_client

client = get_nlm_direct_client()  # Singleton, uses pool.json cookies
```

### Methods

#### `ask_question(notebook_uuid, question, source_uuids=None) -> str`
Ask a question and get a Gemini-grounded answer.

Parameters:
- `notebook_uuid` -- target notebook
- `question` -- natural language question
- `source_uuids` -- list of specific source UUIDs (None = all sources)

Returns: answer text.
Raises: `NLMAuthError`, `NLMRateLimitError`, `NLMNotFoundError`

#### `ask_question_stream(notebook_uuid, question) -> Generator[str]`
Streaming version -- yields text chunks.

#### `list_notebooks() -> List[dict]`
Returns: list of dicts with keys: `uuid`, `title`, `created_at`, `source_count`, `artifact_count`

#### `get_notebook_info(notebook_uuid) -> dict`
Returns: dict with `uuid`, `title`, `description`, `created_at`, `updated_at`

#### `list_sources(notebook_uuid) -> List[dict]`
Returns: list of dicts with `source_uuid`, `type`, `status`, `title`, `created_at`

#### `get_source_content(notebook_uuid, source_uuid) -> str`
Returns: the source's text content.

#### `get_notebook_analysis(notebook_uuid) -> str`
Returns: structured markdown analysis of all sources.

#### `list_artifacts(notebook_uuid) -> List[dict]`
Returns: list of dicts with `artifact_uuid`, `type`, `title`, `status`, `created_at`

#### `create_artifact(notebook_uuid, artifact_type) -> str`
Trigger generation of a new artifact. Returns artifact UUID. Generation is async -- poll `list_artifacts` for `SAVED` status.

#### `get_suggested_questions(notebook_uuid, hint="", count=5) -> List[str]`
Returns: list of suggested questions.

#### `get_audio_overview_options(notebook_uuid) -> List[dict]`
Returns: `[{"id": 1, "name": "Deep dive", "description": "..."}, ...]`

#### `create_note(notebook_uuid, title, content_html) -> str`
Create a pinned note. Returns note UUID.

#### `rename_notebook(notebook_uuid, new_title) -> None`

#### `watch_notebook(notebook_uuid) -> Generator[dict]`
SSE stream for real-time updates.

#### `batchexecute(rpcid, payload, notebook_uuid) -> dict`
Direct access to any batchexecute endpoint. Returns parsed response JSON (after stripping `)]}' ` prefix and `wrb.fr` unwrapping).

### GoogleAccountPool

```python
from engine.integrations.google_account_pool import get_account_pool

pool = get_account_pool()
cookies = pool.get_cookies("knack112358")
pool.is_stale("knack112358", max_age_hours=48)
pool.refresh_via_cdp("knack112358")
pool.mark_rate_limited("knack112358")
next_account = pool.get_available_account()
pool.import_from_har("path/to/har", "knack112358", ["notebooklm"])
pool.save()
```

### Error Handling

```python
from engine.integrations.nlm_direct_client import (
    NLMAuthError,       # Cookies expired/invalid
    NLMRateLimitError,  # 50 queries/day exceeded
    NLMNotFoundError,   # Notebook UUID not found
    NLMTimeoutError,    # Request timed out
    NLMResponseError,   # Malformed response
)
```

### Response Parsing

The batchexecute response format requires multi-step parsing:

```python
def parse_batchexecute_response(raw: str) -> dict:
    # 1. Strip security prefix
    if raw.startswith(")]}'"):
        raw = raw[5:]

    # 2. Parse chunked transfer -- skip hex chunk size lines
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

### Multi-Account Scale

| Accounts | Queries/Day | Notebooks |
|----------|-------------|-----------|
| 1 | 50 | 100 |
| 5 | 250 | 500 |
| 10 | 500 | 1,000 |
| 20 | 1,000 | 2,000 |

---

## 5. Batchexecute Protocol

**Endpoint:** `POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute`

**Format:** `f.req=[[['rpcid','json_payload',null,'generic']]]`

**Auth:** Session cookies (`__Secure-1PSID`, `__Secure-1PAPISID`)

**Response:** `)]}' ` prefix + `wrb.fr` JSON frames

### URL Parameters

| Parameter | Example | Notes |
|-----------|---------|-------|
| `rpcids` | `CYK0Xb` or `CYK0Xb;s0tc2d` | Semicolon-separated for batch |
| `source-path` | `/notebook/<nb_id>` | Optional -- sets auth context |
| `bl` | `boq_labs-tailwind-frontend_...` | Build label -- CRITICAL |
| `f.sid` | `-1` or extracted from HAR | Session ID |
| `hl` | `en` | Language |
| `_reqid` | `100000` | Auto-incrementing request ID |
| `rt` | `c` | Response type (always `c`) |

### Request Body

```
f.req=<url_encoded_json>
```

JSON is an array of `[rpc_id, args_json, null, "generic"]` tuples.

### Response Format

Responses start with `)]}' ` (XSSI protection), followed by newline-delimited chunks. Each `wrb.fr` chunk:

```json
[["wrb.fr", "RPC_ID", "inner_json_string", null, null, null, "generic"],
 ["di", 457],
 ["af.httprm", ...]]
```

The inner JSON string must be `json.loads()`'d again to get the actual data.

### Config Object (`_WRITE_CONFIG`)

Several write RPCs share a common config object as their first argument:

```python
_WRITE_CONFIG = [2, None, None,
    [1, None, None, None, None, None, None, None, None, None, [1]],
    [[2, 1]]
]
```

### Source Data Structure

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
| `1` | Google Doc (Drive) |
| `2` | Google Slides |
| `3` | PDF |
| `5` | Web article / URL |
| `7` | YouTube video |
| `8` | Markdown / plain text file |

### Multi-Question Batching

Up to 5 RPCs per batchexecute request:

```python
calls = [
    ("CYK0Xb", json.dumps([notebook_id, q]))
    for q in questions[:5]
]
f_req = [[rpc_id, args_json, None, "generic"] for rpc_id, args_json in calls]
# rpcids URL param: "CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb"
```

Each `wrb.fr` block in the response corresponds to one call, in order.

---

## 6. RPC Catalogue

25 batchexecute RPCs + 1 proto endpoint. Operations are divided into Read (data retrieval) and Write (mutations).

### Read RPCs

#### `ZwVcOc` -- Get Session Limits
```python
args = [None, [1, None, None, None, None, None, None, None, None, None, [1]]]
# Response: [[None, [max_notebooks_visible, max_sources, ?, max_chars_per_source], features]]
# Confirmed values: [6, 200, 100, 500000]
```

#### `ub2Bae` -- List Notebooks
```python
args = [[2]]
# Response: [[[notebook_title, [[sources_preview]], notebook_id, state...]]]
```

#### `wXbhsf` -- Get Notebook Sources + State
```python
args = [None, 1, None, [2]]
# Response: [[[notebook_title, [[source_obj, ...]], ...]]]
```
Primary source list RPC. Use `rLM1Ne` for polling.

#### `rLM1Ne` -- Load Notebook by ID (Poll)
```python
args = [notebook_id, None, [2], None, 0]
# Response: [[notebook_title, [[source_obj, ...]]]]
```
Polling pattern after adding sources:
```python
for _ in range(30):  # up to ~5 minutes
    sources = load_notebook(notebook_id, cookies)
    if all(s["word_count"] > 0 for s in sources):
        break
    time.sleep(10)
```

#### `e3bVqc` -- Get Full Notebook Info
```python
args = [None, None, notebook_id]
# Response: [[[session_id, [notebook_id, [description_text, 1], version, [sources]]]]]
```
Returns complete notebook record (80-100KB for populated notebooks).

#### `hPTbtc` -- Get Conversation Thread IDs
```python
args = [[], None, notebook_id, page_size]  # page_size default: 20
# Response: [[[thread_id]]]
```

#### `khqZz` -- Read Conversation Thread Messages
```python
args = [[], None, None, thread_id, page_size]
# Response: [[[msg_id, [unix_sec, nano_sec], role, None, [[message_text]]]]]
# role: 2 = user, 1 = assistant
```

#### `VfAZjd` -- Generate Notebook AI Overview
```python
args = [notebook_id, [2]]
# Response: [[[markdown_overview_text]]]
```

#### `gArtLc` -- List Saved Artifacts
```python
args = [_WRITE_CONFIG, notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
# Response: [[[artifact_id, title, type_int, [[source_id_arrays]], timestamp, ...]]]
```

#### `sqTeoe` -- List Audio Overview Types
```python
args = [_WRITE_CONFIG, None, 1]
# Response: [[[[1,'Deep dive','A lively conversation...'],
#              [2,'Brief','A bite-sized overview...'],
#              [3,'Critique','An expert review...'],
#              [4,'Debate','...'], ...]]]
```

#### `JFMDGd` -- Get User Profile
```python
args = [notebook_id, [2]]
# Response: [[[email, 1, [], [display_name, avatar_url]]], None, queries_remaining]
```

#### `ozz5Z` -- Get Account UI State / Feature Flags
```python
args = [[[[None, "1", plan_tier_id], [None,...,[None,None,4]], 1]]]
# plan_tier_id 1287 = NotebookLM Plus
```

#### `CCqFvf` -- Resume Session / Load Last Notebook
```python
args = ["", None, None, [2], [1, None, None, None, None, None, None, None, None, None, [1]]]
# Response: ["", None, last_notebook_id, None, None, state_obj, None, ..., [[conv_thread_id]]]
```

#### `tr032e` -- Read Full Source Text
```python
args = [[[[source_id]]]]  # source_id wrapped in 3 nested lists
# Response: [[[None, [source_markdown_text]]]]
```
Returns raw source text (not AI summary).

#### `cFji9` -- Get/Generate Mind Map
```python
args = [notebook_id, None, cursor_timestamp, [2]]
# Response: [[[mind_map_id, [mind_map_id, json_tree_string]]]]
```
Mind map JSON is D3-compatible hierarchical tree.

### Write RPCs

#### `s0tc2d` -- Rename Notebook
```python
args = [notebook_id, [[None, None, None, [None, "new_name"]]]]
```

#### `CYK0Xb` -- Save Note / Annotate with Citations
```python
args = [notebook_id, question_text]
# Response: [[note_id, answer_markdown_with_citations, ...]]
```
Synchronous citation Q&A. Answer with inline `[source_id]` references.

For creating user notes:
```python
args = [nb_id, html, [1], None, title, None, [2]]
```

#### `R7cb6c` -- Generate Report / Document
```python
source_array = [[[src_id]] for src_id in source_ids]
report_body = [None, None, report_type, source_array]
args = [_WRITE_CONFIG, notebook_id, report_body]
```
Report type codes: `2`=brief, `3-8`=study guide/FAQ/timeline/outline/glossary, `9`=free-form notes.

#### `ciyUvf` -- Generate Suggested Report Preview
```python
source_id_arrays = [[src_id] for src_id in source_ids]
args = [_WRITE_CONFIG, notebook_id, source_id_arrays]
```

#### `izAoDd` -- Add Source (URL, YouTube, or text paste)
```python
_SOURCE_CONFIG = [2, None, None,
    [1, None, None, None, None, None, None, None, None, None, [1]],
    [[2, 1]]
]

# Regular URL source:
source_obj = [None, None, url, None, None, None, None, None, None, None, 1]
# YouTube source (URL at position 7):
source_obj = [None, None, None, None, None, None, None, [url], None, None, 1]

args = [[[source_obj]], notebook_id, [2], _SOURCE_CONFIG]
```
After calling, poll `rLM1Ne` until `word_count > 0`.

#### `o4cbdc` -- Add Source (file upload, step 1)
```python
args = [[filename], nb_id, [2], [1, None, None, [1]]]
# Returns: [[source_id, filename, [gcs_signed_upload_url, ...]]]
```
Then PUT file bytes to the signed URL. Poll `rLM1Ne` until processed.

#### `tGMBJ` -- Delete Source
```python
args = [[[source_id]], [2]]
```

#### `Ljjv0c` -- Start Fast Research Session
```python
args = [[search_query, 1], None, 1, notebook_id]
# Response: [research_session_id]
```

#### `QA9ei` -- Start Deep Research
```python
args = [None, [1], ["topic_query", 1], 5, notebook_id]
# Response: [session_id]
```

#### `LBwxtb` -- Add Research Source
```python
args = [None, [1], session_id, notebook_id, [[None, [title, content]]]]
```
Adds AI-generated research document from a completed Deep Research session.

#### `cYAfTb` -- Save Note (live auto-save)

### YouTube Source Encoding

```python
def is_youtube(url: str) -> bool:
    return "youtube.com/watch" in url or "youtu.be/" in url

def make_source_obj(url: str) -> list:
    if is_youtube(url):
        return [None, None, None, None, None, None, None, [url], None, None, 1]
    else:
        return [None, None, url, None, None, None, None, None, None, None, 1]
```

| Position | Content | NLM format type |
|----------|---------|-----------------|
| `[2]` (string) | Web article, PDF URL | `5` (web) or `3` (PDF) |
| `[7]` (list) | YouTube video URL | `7` (YouTube) |

### Deep Research Flow

```
1. QA9ei  -- args: [None, [1], ["topic", 1], 5, nb_id]  -> session_id
2. (NLM generates AI document asynchronously)
3. LBwxtb -- args: [None,[1],session_id,nb_id,[[None,[title,doc]]]]  -> source added
4. (Optional) R7cb6c -- generate structured note artifact from all sources
```

| Aspect | Fast Research | Deep Research |
|--------|---------------|---------------|
| RPC | `Ljjv0c` -> `izAoDd` | `QA9ei` -> `LBwxtb` |
| Source type | Existing web pages | AI-generated document |
| Input | Search query | Research topic |
| Output | Multiple URL sources | Single AI research doc |

### Proto / gRPC Endpoint

#### `GenerateFreeFormStreamed` -- NLM Chat

Uses a different transport from batchexecute -- server-streaming gRPC over HTTP/1.1. Auth uses cookies only (no `at` token in body).

**URL:**
```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
  google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/
  GenerateFreeFormStreamed
?bl=<build_label>&rt=c
```

`f.sid` and `_reqid` are NOT required.

**Request body (URL-encoded `f.req`):**

```python
inner_args = [
    [[[src_id]] for src_id in source_ids],  # [0]: source context
    question_text,                           # [1]: the question
    None,                                    # [2]: reserved
    [2, None, [1], [1]],                    # [3]: response config (always this value)
    thread_id,                               # [4]: thread UUID (same=continue, new=fresh)
    None,                                    # [5]: reserved
    None,                                    # [6]: reserved
    notebook_id,                             # [7]: notebook UUID
    1,                                       # [8]: mode flag (always 1)
]
f_req = [None, json.dumps(inner_args)]
body = urllib.parse.urlencode({"f.req": json.dumps(f_req)}).encode()
```

**Response -- SSE-like streaming:**

Each chunk contains the FULL TEXT SO FAR (not deltas):

```python
raw = response_text.lstrip(")]}'").lstrip("\n")
for line in raw.split("\n"):
    if not line.strip().startswith("[["):
        continue
    for item in json.loads(line.strip()):
        if item[0] == "wrb.fr":
            inner = json.loads(item[2])
            text_so_far = inner[0][0]
            thread_id   = inner[0][2][0]
            msg_id      = inner[0][2][1]
```

### Observed RPC Registry (ARGUS, 33/50 rpcids)

Additional rpcids observed by ARGUS but not fully documented above:

| rpcid | Operation | Status | Times Observed |
|-------|-----------|--------|----------------|
| `jzEKsc` | Access shared notebook via share token | Not yet observed | 0 |
| `PoHVkb` | AddSource | Not yet observed | 0 |
| `VqhFhd` | CreateNotebook | Not yet observed | 0 |
| `kVoZqc` | DeleteNotebook | Not yet observed | 0 |
| `VSSXud` | DeleteSource | Not yet observed | 0 |
| `Of0kDd` | Fetch STUN/TURN ICE config for WebRTC | Not yet observed | 0 |
| `dI5Y8` | Get/create shareable link | Not yet observed | 0 |
| `bfEAsb` | ActOnSources | Not yet observed | 0 |
| `GfmCOc` | DeleteNotes | Not yet observed | 0 |
| `tJHFsf` | GenerateFreeFormStreamed | Not yet observed | 0 |
| `GzgSEd` | ListChatTurns | Not yet observed | 0 |
| `K4YCPe` | LoadSource | Not yet observed | 0 |
| `mFtdI` | GetProject | Not yet observed | 0 |
| `WWINqb` | RemoveRecentlyViewedProject | Not yet observed | 0 |
| `wIlBFe` | ListNotebooks | Not yet observed | 0 |
| `sM6gLf` | UpdateNotebook | Not yet observed | 0 |
| `DYBcR` | User locale/language preferences | Not yet observed | 0 |
| `eyWvXc` | WebRTC SDP offer for live audio | Not yet observed | 0 |
| `xqEXEf` | GenerateNotebookGuide | Observed | 34 |
| `hizoJc` | LoadSource | Observed | 6 |
| `jtGGne` | LoadSource | Observed | 6 |
| `b7Wfje` | Unknown | Observed | 4 |
| `otmP3b` | Unknown | Observed | 54 |

### Discovered but Unwired Capabilities

| Capability | RPCs | Notes |
|------------|------|-------|
| Source Discovery | `DiscoverSources`, `DiscoverSourcesAsync`, `DiscoverSourcesManifold` | Autonomous web source discovery |
| Magic View | `CCqFvf`, `yyryJe`, `VfAZjd` | AI visual organization of notebook content |
| Multi-Model | `ListModelOptions` | Switch between Gemini 2.5, 3.0, Ultra |
| Drive Export | `Krh3pd` | Export artifacts to Google Drive / Sheets |
| Writing Functions | `ExecuteWritingFunction` | AI editing (rewrite, expand, summarize) |
| Report Scaffolding | `GenerateReportSuggestions` | AI-generated report structure |
| Source Freshness | `CheckSourceFreshness` | Verify URL sources are up-to-date |
| Mutation API | `MutateProject`, `MutateNote`, `MutateSource`, `MutateAccount` | Full CRUD mutations |
| WebRTC Audio | `Of0kDd` (GetIceConfig), `eyWvXc` (SendSdpOffer) | Programmatic audio stream |
| Sharing | `CreateAccessRequest`, `GetProjectDetails`, `ShareProject` | Auto-share notebooks |

---

## 7. Proxy Routes (`:8800`)

Complete route reference for `engine/mcp/nlm_live_proxy.py`. All routes return JSON. Routes requiring auth return `503` with `{"error":"no_cookies"}` if no cookies are stored.

### Authentication & Setup

```
GET  /health               -- Status, cookie count, BL age, RPC version
POST /cookies/import        -- Import cookies from HAR file
POST /cookies/capture       -- Auto-capture cookies via Chrome CDP
POST /cookies/refresh       -- Refresh f.sid and at token
GET  /cookies               -- List stored cookie names
DELETE /cookies             -- Clear all cookies
GET  /meta                  -- Current BL and session metadata
POST /meta                  -- Update BL or f.sid manually
```

### Notebook Operations

```
GET  /notebooks                          -- List all notebooks (ub2Bae)
POST /notebooks                          -- Create notebook (client-side UUID)
GET  /notebooks/<id>                     -- Full notebook data (summary+sources+notes+convos)
GET  /notebooks/<id>/content             -- Raw full notebook info blob (e3bVqc)
POST /notebooks/<id>/rename              -- Rename notebook (s0tc2d)
```

### Source Operations

```
GET    /notebooks/<id>/sources           -- List sources (wXbhsf)
POST   /notebooks/<id>/sources           -- Add URL/YouTube source (izAoDd)
GET    /notebooks/<id>/sources/wait      -- Poll source processing completion (rLM1Ne)
GET    /notebooks/<id>/sources/content   -- Download all source texts (tr032e per source)
DELETE /sources/<id>                     -- Delete source (tGMBJ)
GET    /sources/<id>/content             -- Read source text (tr032e)
GET    /sources/<id>/export              -- Download source as plain text file
```

### Summary & AI Features

```
GET /notebooks/<id>/summary              -- AI overview (VfAZjd)
GET /notebooks/<id>/mindmap              -- Mind map D3 JSON (cFji9)
```

### Notes & Artifacts

```
GET  /notebooks/<id>/notes               -- List saved notes/artifacts (gArtLc)
POST /notebooks/<id>/notes               -- Create note (CYK0Xb)
PUT  /notebooks/<id>/notes/<note_id>     -- Update note (cYAfTb)
GET  /notebooks/<id>/notes/sync          -- Delta poll notes (cFji9)
GET  /notebooks/<id>/audio-options       -- Audio overview types (sqTeoe)
POST /notebooks/<id>/generate            -- Generate report preview (ciyUvf)
POST /notebooks/<id>/save_note           -- Save report/note artifact (R7cb6c)
```

### Conversation Threads

```
GET /notebooks/<id>/history              -- Thread IDs + all messages (hPTbtc + khqZz)
GET /notebooks/<id>/threads              -- Thread IDs only (hPTbtc)
GET /notebooks/<id>/threads/<thread_id>  -- Messages in thread (khqZz)
GET /notebooks/<id>/conversations        -- Legacy (cFji9 mind-map, limited)
```

### Ask / Chat

```
POST /notebooks/<id>/ask                 -- Synchronous Q&A with citations (CYK0Xb)
POST /notebooks/<id>/ask_batch           -- Batch up to 5 questions (CYK0Xb batched)
POST /notebooks/<id>/chat                -- Streaming multi-turn chat (GenerateFreeFormStreamed)
```

### Research Workflow

```
POST /notebooks/<id>/research            -- Start fast research (Ljjv0c)
POST /notebooks/<id>/research/deep       -- Start deep research (QA9ei)
POST /notebooks/<id>/research/source     -- Add AI research doc as source (LBwxtb)
```

### Download & Archive

```
GET /notebooks/<id>/archive              -- Full notebook archive (sources+content+notes+threads+mindmap)
GET /notebooks/archive                   -- Export all notebooks
GET /sources/<id>/export                 -- Single source as text file download
```

### User Info

```
GET /user/profile?notebook_id=<id>       -- Profile + queries remaining (JFMDGd)
GET /user/quota                          -- Account quota and plan tier (ozz5Z)
```

### Rate Limiting

```
GET  /rate_limit                         -- Current rate limit
POST /rate_limit                         -- Override rate limit (0.5-30.0s range)
```

### RPC Registry & Direct Calls

```
GET  /rpc_registry                       -- RPC registry status
POST /rpc/<rpc_id>                       -- Call any RPC directly
```

---

## 8. Multimodal Workflows

### Supported Source Types

```
Sources IN                          Generation OUT
text          -> izAoDd (paste)      CYK0Xb  -> report / analysis / code
URL           -> izAoDd (url)        QA9ei   -> 30-min podcast (MP3)
YouTube URL   -> izAoDd (native)     ciyUvf  -> flashcard Q&A pairs
Google Sheets -> izAoDd (url)        R7cb6c  -> quiz with citations
image (.png)  -> o4cbdc + PUT        yyryJe  -> concept mind map (JSON tree)
audio (.mp3)  -> o4cbdc + PUT        LBwxtb  -> long-form narrative
video (.mp4)  -> o4cbdc + PUT        Krh3pd  -> export to Google Sheets
PDF           -> o4cbdc + PUT        otmP3b  -> video content suggestions
                                     Ljjv0c  -> deep research
```

Every OUTPUT can become the next call's INPUT. Generated MP3 can be uploaded back. Sheets URLs can be added as sources. Report artifacts can feed the flashcard generator.

### File Upload Flow (`add_source_file`)

```
1. o4cbdc([filename], nb_id, [2], [1, null, null, [1]])
   -> returns [[source_id, filename, [gcs_signed_upload_url, ...]]]

2. PUT file_bytes to gcs_signed_upload_url
   headers: Content-Type: <mime_type>, Content-Length: <bytes>
   timeout: 300s (video files can be large)

3. Poll rLM1Ne until source_id is no longer in pending list
```

### Supported MIME Types

| Extension | MIME type | Gemini capability |
|-----------|----------|-------------------|
| `.jpg` | image/jpeg | Full visual understanding |
| `.png` | image/png | Full visual understanding |
| `.mp3` | audio/mpeg | Transcription + understanding |
| `.wav` | audio/wav | Transcription + understanding |
| `.mp4` | video/mp4 | Frame + audio + transcription |
| `.mov` | video/quicktime | Frame + audio + transcription |
| `.pdf` | application/pdf | Text + embedded images |
| `.webm` | video/webm | Frame + audio + transcription |

### YouTube Native Ingestion

Pass the URL directly to `add_source_url()`. NLM handles transcription, chapter extraction, and indexing. No Whisper needed.

### Generation Prompt Capacity

Every generation call (`CYK0Xb`, `QA9ei`, `ciyUvf`, `R7cb6c`) accepts ~10,000 words of prompt. This is a complete creative brief, not just a question.

### Workflow: Self-Referential Audio Loop

```python
# Round 1: Generate podcast
# QA9ei("Explain CosySim architecture. Hosts: Alex + Sam")
# -> 30-min MP3 -> add_source_file(mp3)  (Gemini listens to its own podcast)

# Round 2: Generate follow-up podcast with Round 1 as context
# -> another 30-min MP3 -> add_source_file(mp3)

# Round 3: Debrief episode
# -> run_knowledge_flywheel(all 3 transcripts + original docs)
# -> 300+ Q&A pairs from combined analysis
```

Cost: 3 NLM API calls + 3 local Whisper runs = 300+ Q&A pairs.

### Workflow: Visual Feedback Loop (ComfyUI)

```python
# Notebook has: character description, style guide, reference images
# 1. ComfyUI generates image
# 2. add_source_file(image) -- Gemini evaluates visually
# 3. create_note() with evaluation prompt (composition, quality, adherence)
# 4. Extract improved prompt from evaluation
# 5. Repeat until score >= 8
```

### Workflow: Sheets Read-Write Loop

```python
# 1. Generate structured data via create_note()
# 2. export_to_sheets(report_id) -> sheets_url
# 3. add_source_url(sheets_url)  -- Gemini reads its own table
# 4. create_note() with analysis prompt on the data
```

### Workflow: Chart-to-Action Pipeline

```python
# 1. Colab generates matplotlib chart -> chart.png
# 2. add_source_file(chart.png)
# 3. create_note() -- Gemini reads chart visually, produces analysis + action items
# 4. generate_audio() -- narrate the chart findings
```

---

## 9. Skills

### NotebookLM Skills (`engine/skills/builtin/notebooklm_skills.py`, pack: `notebooklm`)

| Skill | Description |
|-------|-------------|
| `notebooklm_ask` | Ask a question against a notebook; returns answer with citations |
| `notebooklm_add_source` | Add a URL, text, PDF, or YouTube link to a notebook |
| `notebooklm_generate_audio` | Generate a podcast-style Audio Overview (async) |
| `notebooklm_list_notebooks` | List all notebooks visible to the authenticated user |
| `notebooklm_search` | Search across all notebooks by keyword |

### MCP NLM Live Skills

```python
nlm_live_ask(notebook_id, "What is X?")
nlm_live_batch_ask(notebook_id, ["Q1?", "Q2?", "Q3?"])
nlm_generate_document(notebook_id, source_ids)
nlm_save_note(notebook_id, source_ids)
nlm_capture_cookies()
nlm_proxy_meta()
nlm_distill_notebook(notebook_id)
```

### NLM Forge Skills (routed through 4-tier Nexus pipeline)

```python
nlm_ask("question")         # Cache -> FTS -> NLM -> LLM
nlm_batch_ask(questions)
nlm_generate_doc(nb_id)
```

Higher-level NLM skills (pack: `nlm`) are in `engine/skills/builtin/autonomy_skills.py`.

---

## 10. Scheduler Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `news-distill-nlm` | 1x/day | Distill 20 Q&A from each news notebook |
| `nlm-batch-ask` | Weekly | Batch-ask questions across all notebooks |
| `cookie-auto-refresh` | 72h | CDP cookie refresh for all accounts |
| `cookie-health-check` | Daily | Verify cookie freshness |
| `notebook-bootstrap` | Weekly | Notebook refresh + control follow-up |
| `control-notebook-flywheel` | 8h | Control-plane artifact refresh |

---

## 11. Rate Limiter

All outbound calls to `notebooklm.google.com` pass through `_RateLimiter`:

| Setting | Default | Range | Source |
|---------|---------|-------|--------|
| `min_gap_seconds` | `1.5` | `0.5-30.0` | `config/default.yaml` -> `notebooklm.rate_limit_seconds` |

- Batch calls count as one request for rate-limiting
- Thread-safe via `threading.Lock`
- Aggressive calls (>40 questions/minute) may trigger Google soft-limits
- Dynamic override via API is session-only

Recommended settings:
```yaml
notebooklm:
  rate_limit_seconds: 1.5   # interactive use
  rate_limit_seconds: 3.0   # overnight batch jobs
  rate_limit_seconds: 0.8   # testing only
```

---

## 12. Known Limitations

1. **`s0tc2d` is RENAME, not chat** -- use `GenerateFreeFormStreamed` for chat.
2. **`CYK0Xb` is synchronous Q&A with citations** -- best for programmatic extraction.
3. **`GenerateFreeFormStreamed` uses cookies-only auth** -- no `at` CSRF token.
4. **Streaming response contains FULL TEXT, not deltas** -- do not concatenate chunks.
5. **YouTube sources use position 7** in the source object (not position 2).
6. **Chrome 130+ redacts cookies from HAR exports** -- use CDP capture instead.
7. **Build label changes weekly** -- monitor `bl_stale` in `/health`.
8. **Batch limit: 5 RPCs** per batchexecute request. `GenerateFreeFormStreamed` cannot be batched.
9. **Rate limiting** -- >50 questions/minute may trigger soft limits.
10. **Source UUIDs are per-notebook** -- always fetch fresh from `wXbhsf`.

---

## 13. Troubleshooting

| Problem | Fix |
|---------|-----|
| `/notebooks` returns `no_data` | Run `python scripts\har_capture.py --mode cdp ...`; if still fails, import fresh HAR |
| `python -m scripts.argus.tools tokens` hangs | Prefer CDP path; ensure Chrome exposing port 9222 with live NLM tab |
| HTTP 502 from proxy | Refresh browser auth; check `data\nlm_meta.json` has valid `bl`, `f_sid`, `at` |
| `cookie_count: 0` in `/health` | Run CDP refresh or import HAR |
| Proxy not starting | Check port 8800 is free; `python -m engine.mcp.nlm_live_proxy` |
| RPC returns 404 | BL may be stale; import fresh HAR or run `/cookies/capture` |

---

## 14. Testing

Mock at the client boundary. Never make real NLM calls in tests.

```python
from unittest.mock import patch

@patch("engine.integrations.nlm_direct_client.get_nlm_direct_client")
def test_nlm_distillation(mock_client):
    mock_client.return_value.ask_question.return_value = "Test answer"
    mock_client.return_value.get_suggested_questions.return_value = ["Q1?", "Q2?"]
    # ... assertions
```

---

*See also: `docs/NLM_API_REFERENCE.md` (ARGUS auto-generated rpcid observations)*
*Client implementation: `engine/integrations/nlm_direct_client.py`*
*Proxy implementation: `engine/mcp/nlm_live_proxy.py`*
