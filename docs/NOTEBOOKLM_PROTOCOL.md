# NotebookLM Private API — Protocol Deep Dive

> **Version:** 1.0 (reverse-engineered from 8 HAR capture sessions, 21 unique RPCs confirmed)
> **Status:** Production — implemented in `engine/mcp/nlm_live_proxy.py`
> **Audience:** Developers building on or maintaining the NLM proxy integration

---

## What Is This Document?

NotebookLM has no public API. Every operation performed in the browser — listing
notebooks, adding sources, asking questions, generating reports — goes through a
**private Google batchexecute transport** that was reverse-engineered by capturing
and analysing real browser sessions (HAR files) over multiple capture sessions.

This document explains:
1. **What the batchexecute protocol is** and how it works at the wire level
2. **How we reverse-engineered it** — methodology, tools, sessions
3. **Authentication** — every secret token required and how to compute/obtain them
4. **All 21 RPCs** we discovered, with request/response structures
5. **The gRPC-style streaming endpoint** for Fast Research
6. **The complete data model** — how sources, notebooks, threads are structured
7. **Notebook lifecycle** — create → add sources → ask → read results
8. **RPC ID rotation** — why IDs change and how to survive it
9. **Known gaps** — what we haven't captured yet
10. **How CosySim's proxy uses all of this**

---

## Part 1: The batchexecute Protocol

### Background

Google's internal products (Search, Docs, Maps, NotebookLM) use a proprietary
RPC transport called **batchexecute** instead of conventional REST or gRPC APIs.
It was never designed for third-party use — it's an internal Google infrastructure
layer exposed via HTTP.

Key characteristics:
- **Single endpoint** — all RPCs go to one URL via HTTP POST
- **RPC IDs** — short 5–7 character strings (not human-readable) identify functions
- **JSPB encoding** — responses use a Google-internal JSON-over-Protocol-Buffers
  hybrid (not standard JSON or protobuf)
- **XSSI protection** — every response is prefixed with `)]}'` to prevent
  cross-site script injection attacks (strip before parsing)
- **Batching** — multiple RPCs can be packed into a single HTTP request

### The Single Endpoint

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
```

All 21 RPCs (except the streaming proto endpoint) go here. The NLM service
is served from `LabsTailwindUi` — the codename for the NotebookLM frontend
app within Google's internal infrastructure.

### URL Parameters

Every request includes these query parameters:

| Parameter | Example | Purpose |
|-----------|---------|---------|
| `rpcids` | `VfAZjd` or `VfAZjd;wXbhsf` | Which RPC(s) to call — semicolon-separated for batching |
| `source-path` | `/notebook/bec06e03-...` | Sets auth/notebook context; optional but helps routing |
| `bl` | `boq_labs-tailwind-frontend_20260226.08_p0` | **Build label — CRITICAL** (see below) |
| `f.sid` | `-8234567890` | Session ID extracted from page load |
| `hl` | `en` | Language/locale |
| `_reqid` | `100000` | Auto-incrementing request counter (cosmetic) |
| `rt` | `c` | Response type — always `c` |

### Request Body Format

The body is URL-encoded `application/x-www-form-urlencoded`:

```
f.req=<url_encoded_json>[&at=<anti_forgery_token>]
```

`f.req` is a JSON array of call tuples. Each call is:
```json
["RPC_ID", "<args_json_string>", null, "generic"]
```

The `args_json_string` is a **JSON string** (not an object) — it must be
`json.dumps()`'d before being embedded in the outer array.

**Single call example:**
```python
args = json.dumps([notebook_id, [2]])  # the args for VfAZjd
f_req = [["VfAZjd", args, None, "generic"]]
body = urllib.parse.urlencode({"f.req": json.dumps(f_req)})
# → f.req=%5B%5B%22VfAZjd%22%2C%22...
```

**Batched call example (3 RPCs):**
```python
f_req = [
    ["VfAZjd",  json.dumps([nb_id, [2]]),         None, "generic"],
    ["wXbhsf",  json.dumps([None, 1, None, [2]]),  None, "generic"],
    ["gArtLc",  json.dumps([[2], nb_id, filter_str]), None, "generic"],
]
# rpcids URL param: "VfAZjd;wXbhsf;gArtLc"
```

### Response Format

The response is a series of newline-separated JSON blocks:

```
)]}'
<length>
[["wrb.fr","VfAZjd","[[[ overview markdown ]]]",null,null,null,"generic"],["di",457],["af.httprm",457,"....",1]]
<length>
[["wrb.fr","wXbhsf","[[[\"Notebook Title\",[[...sources...]]]]",null,null,null,"generic"]]
```

**Parsing algorithm:**
```python
body = raw.lstrip(")]}'").lstrip("\n")
for line in body.split("\n"):
    line = line.strip()
    if not line.startswith('[["wrb.fr"'):
        continue
    outer = json.loads(line)
    rpc_id    = outer[0][1]        # e.g. "VfAZjd"
    inner_raw = outer[0][2]        # a JSON *string* (needs second parse!)
    inner     = json.loads(inner_raw)  # the actual response data
```

**The double-decode is essential.** The inner response data is a string containing
JSON, not a JSON object directly — always call `json.loads()` on `outer[0][2]`.

### JSPB Data Encoding

Responses use JSPB (JSON-Protocol-Buffer hybrid). What this means in practice:
- Positional arrays instead of named keys (position matters!)
- `None` / `null` as explicit placeholder for missing fields
- Nested arrays for repeated fields (not `[]` for empty)
- Integer codes instead of enum strings (e.g. format type `5` = web URL)

This is why all our parsing code accesses specific array indices rather than
dictionary keys. A response like:
```json
[["source-uuid"], "Article Title", [null, 1547, [1709000000, 0], [...], 5, null, 1, ["https://..."], 8230], [null, 2]]
```
Must be parsed knowing: `[0][0]`=source_id, `[1]`=title, `[2][1]`=word_count,
`[2][4]`=format_type, `[2][7][0]`=url, `[3][1]`=add_method.

---

## Part 2: Discovery Methodology

### HAR Capture Sessions

We captured **8 HAR (HTTP Archive) files** from real browser sessions across
multiple days and accounts to build the complete RPC catalogue:

| Session | Date | Focus | New RPCs Found |
|---------|------|-------|----------------|
| HAR-1 | 2026-02-20 | Basic navigation, list notebooks | `ub2Bae`, `wXbhsf`, `ZwVcOc` |
| HAR-2 | 2026-02-21 | Open notebook, read sources | `rLM1Ne`, `e3bVqc`, `VfAZjd` |
| HAR-3 | 2026-02-22 | Ask questions, chat | `CYK0Xb`, `s0tc2d` |
| HAR-4 | 2026-02-23 | Notes, artifacts | `gArtLc`, `R7cb6c`, `ciyUvf` |
| HAR-5 | 2026-02-24 | Account info, audio | `ozz5Z`, `sqTeoe`, `JFMDGd` |
| HAR-6 | 2026-02-25 | Source reading, mind map | `tr032e`, `cFji9` |
| HAR-7 | 2026-02-26 | Full session from homepage | `CCqFvf`, `hPTbtc`, `khqZz` |
| HAR-8 | 2026-02-27 | Fast Research + URL add | `Ljjv0c`, `LBwxtb`, `GenerateFreeFormStreamed` |

**Total:** 21 batchexecute RPCs + 1 gRPC-style streaming endpoint.

### HAR Extraction Process

For each session:
1. Open Chrome DevTools (F12) → Network tab → check "Preserve log"
2. Visit `https://notebooklm.google.com` and perform the target actions
3. Export: right-click any request → "Save all as HAR with content"
   - ⚠️ **Must tick "Include sensitive information"** — Chrome 130+ redacts cookies by default
4. Import into CosySim: `POST /cookies/import {"har_path": "..."}`

The `extract_cookies_from_har()` function in `nlm_live_proxy.py` handles:
- Auth cookies extraction from request headers
- Build label (`bl`) extraction from batchexecute URL params
- `f.sid` extraction from URL params
- `at` anti-forgery token extraction from POST body

### Multi-Session Analysis

Each HAR was analysed for:
- Which RPC IDs appeared in requests
- The exact `f.req` payload structure
- The response structure in `wrb.fr` blocks
- Whether responses were consistent across sessions (confirming RPC stability)

**Version correction:** 6 RPCs had incorrect descriptions in v2.1. The correct
identifications were confirmed by comparing response payloads across multiple
sessions and matching them to known UI operations:

| Old Description | Correct Description | How Confirmed |
|-----------------|---------------------|---------------|
| `sqTeoe` — "List All Notebooks" | "List Audio Overview Types" | Response contains `[[1,'Deep dive',...]]` |
| `hPTbtc` — "List Sources Paginated" | "Get Conversation Thread IDs" | Response contains UUIDs matching thread format |
| `khqZz` — "Sub-notebook sources" | "Read Conversation Thread Messages" | Response has role codes + message text |
| `JFMDGd` — "Sources Condensed" | "User Profile + Queries Remaining" | Response has email, name, integer quota |
| `cFji9` — "Conversation History" | "Generate/Get Mind Map" | Response is JSON tree string for D3 |
| `CYK0Xb` — "Legacy Chat RPC" | "Save Notebook Note" | Response has note UUID + markdown content |

### Playwright Automation

For ongoing RPC discovery and validation, we built an automation system:

```python
# engine/nexus/nlm_automation.py
# Drives Chrome via Playwright, captures all batchexecute calls,
# maps them to operations, and stores in data/nlm_rpc_registry.json
python -m engine.nexus.nlm_automation
```

The automation:
1. Opens a Playwright browser with the stored user profile (cookies already present)
2. Navigates to NotebookLM and performs standard operations
3. Intercepts all `batchexecute` requests and records RPC IDs with timestamps
4. Compares against the fallback catalogue to detect ID changes
5. Updates `data/nlm_rpc_registry.json` with fresh IDs

---

## Part 3: Authentication Deep Dive

### Overview of Required Credentials

A NotebookLM batchexecute request requires:

| Token | Where | How to Obtain | Validity |
|-------|-------|---------------|---------|
| `Cookie` header | HTTP header | HAR capture or CDP | Until session expires (~days) |
| `Authorization` header | HTTP header | Computed from SAPISID cookie | Recomputed each request |
| `bl` URL param | URL query | HAR capture / page load | Until next Google deploy (~weekly) |
| `f.sid` URL param | URL query | HAR capture / page load | Until session expires |
| `at` POST body | POST body | HAR capture / page load | Until session expires |

### Cookie Composition

Six categories of Google session cookies are required:

```
SID=<long_value>
SSID=<long_value>
APISID=<long_value>
SAPISID=<long_value>       ← CRITICAL: used to compute SAPISIDHASH
HSID=<long_value>
__Secure-1PSID=<long_value>
__Secure-3PAPISID=<long_value>
OSID=<long_value>
```

The proxy stores these in `data/nlm_cookies.json` and filters incoming cookies
to only keep known auth cookie prefixes (defined in `_AUTH_PREFIXES`).

**Why Chrome 130+ redacts cookies:**
Chrome's HAR export dialog added a "Include sensitive information" checkbox
in Chrome 130. If this is unchecked (the default), all cookie values are
replaced with `<redacted>`. Always check this box, or use CDP capture instead.

### SAPISIDHASH Computation

The `Authorization` header value is not a static token — it is computed fresh
for each request using a SHA1 hash:

```python
import hashlib, time

def compute_sapisidhash(sapisid: str, origin: str) -> str:
    """
    Compute Google SAPISIDHASH for the Authorization header.

    Args:
        sapisid: Value of the SAPISID (or __Secure-3PAPISID) cookie.
        origin:  The request origin — always "https://notebooklm.google.com".

    Returns:
        Full Authorization header value, e.g.:
        "SAPISIDHASH 1709000000_a3f4b2c1d5e6..."
    """
    timestamp = str(int(time.time()))
    raw = f"{timestamp} {sapisid} {origin}"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {timestamp}_{digest}"
```

This prevents replay attacks — the timestamp means each computed hash is valid
for only a short window. Google validates this server-side.

The proxy tries `SAPISID` first, then falls back to `__Secure-3PAPISID`:
```python
sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID", "")
```

### Build Label (BL) — The Most Critical Parameter

The `bl` URL parameter is a Google frontend build identifier:

```
boq_labs-tailwind-frontend_20260226.08_p0
```

Format breakdown:
- `boq_` — Google's binary-over-query prefix (internal build system)
- `labs-tailwind-frontend` — the NLM frontend app codename
- `20260226.08` — build date and build number (YYYYMMDD.NN)
- `_p0` — patch level (almost always 0)

**Why it matters:** The BL serves as a version check. If your BL doesn't match
the currently deployed frontend version, Google may return 404, empty responses,
or malformed data. BL changes roughly weekly with each Google frontend deployment.

**Staleness detection:**
```python
# The proxy logs a warning when BL is >= 8 days old
# GET /health returns:
{"bl": "boq_...", "bl_age_days": 9, "bl_stale": true}
```

**Auto-refresh methods:**
1. Import a new HAR (BL auto-extracted from batchexecute URL params)
2. `POST /cookies/refresh` — loads the NLM page with stored cookies, extracts
   BL from `WIZ_global_data` JavaScript object in the HTML
3. Run `python -m engine.nexus.nlm_automation` (Playwright automation)

**WIZ_global_data extraction** (used by `refresh_session_tokens()`):
```python
# Keys attempted for each token (Google obfuscates these per build):
# f.sid:  "IxjpMA", "FdrFJe"
# at:     "SNlM0e"
# bl:     "QrtxK", "cfb2h" (also: scan for boq_ string in HTML)
m = re.search(r"WIZ_global_data\s*=\s*({.*?});", html, re.DOTALL)
wiz = json.loads(m.group(1))
bl = wiz.get("QrtxK") or wiz.get("cfb2h")
```

### f.sid and at Token

- **f.sid** — Google session ID. Appears in the URL as `f.sid=<value>`. Used for
  server-side session correlation. Value of `-1` is accepted when unknown.
- **at** — Anti-forgery token. Sent in POST body alongside `f.req`. Prevents
  CSRF attacks on the batchexecute endpoint. Extracted from `WIZ_global_data.SNlM0e`.

Both are stored in `data/nlm_meta.json` alongside the BL.

---

## Part 4: Complete RPC Catalogue

### Config Object (Shared by Write RPCs)

Several write RPCs share a common config object as their first argument:

```python
_WRITE_CONFIG = [2, None, None,
    [1, None, None, None, None, None, None, None, None, None, [1]],
    [[2, 1]]
]
```

This config appears unchanged across all 8 HAR files. Its exact semantics are
unknown but it appears to set permission/write flags.

---

### Read RPCs (14 confirmed)

#### `ZwVcOc` — Session Init / Get Account Limits

**Called:** On every page load — the first RPC in any session.

```python
args = [None, [1, None, None, None, None, None, None, None, None, None, [1]]]
# Response: [[None, [max_notebooks, max_sources, max_notebooks_plus, max_chars_per_source], features_list]]
# Confirmed values: [6, 200, 100, 500000]
```

```bash
# curl example
curl -X POST http://localhost:8800/rpc/ZwVcOc \
  -H "Content-Type: application/json" \
  -d '{"args": "[null,[1,null,null,null,null,null,null,null,null,null,[1]]]"}'
```

Returns session limits:
- `max_notebooks` — max notebooks visible (default 6 for free, 100 for Plus)
- `max_sources` — max sources per notebook (200)
- `max_chars_per_source` — character limit per source (500,000)

---

#### `ub2Bae` — List Notebooks

**Called:** On homepage load, on any path that renders the notebook list sidebar.

```python
args = [[2]]
# Response: [[[notebook_title, [[sources_preview_array]], notebook_id, state, ...]]]
```

```python
# Python example
args_json = "[[2]]"
_, data = _batchexecute("ub2Bae", args_json, cookies)
# data[0] is a list of notebook entries
# Each entry: [title, [[source_previews]], notebook_uuid, ...]
```

Returns all notebooks for the authenticated user. Each entry includes a preview
of the first few sources. Used to build the homepage grid.

---

#### `wXbhsf` — Get Notebook Sources + State

**Called:** When navigating to a notebook path to load its source list.

```python
args = [None, 1, None, [2]]
# Response: [[[notebook_title, [[source_obj, ...]], ...]]]
```

Returns sources for the **current/last-used** notebook. The notebook context is
determined by the `source-path` URL parameter. If called without a notebook
context, returns the last-opened notebook's sources.

Returns a list of source objects — see the Source Data Structure section for
field positions.

---

#### `rLM1Ne` — Load Notebook by ID (+ Poll)

**Called:** When opening a specific notebook or polling during source processing.

```python
args = [notebook_id, None, [2], None, 0]
# Response: [[notebook_title, [[source_obj, ...]]]]
```

Identical payload structure to `wXbhsf` but takes an explicit `notebook_id`.
The key use case is **polling**: after adding sources via `LBwxtb`, call this
repeatedly until all sources have a non-zero `word_count`.

```python
# Polling pattern — wait for all sources to finish processing
for attempt in range(30):  # max ~5 minutes at 10s interval
    _, data = _batchexecute("rLM1Ne", json.dumps([nb_id, None, [2], None, 0]), cookies, nb_id)
    _, sources = _extract_sources(data)
    pending = [s for s in sources if s.get("word_count", 0) == 0]
    if not pending:
        break
    time.sleep(10)
```

---

#### `e3bVqc` — Get Full Notebook Info Blob

**Called:** On initial notebook open to get the complete record.

```python
args = [None, None, notebook_id]
# Response: [[[session_id, [notebook_id, [description_text, 1], version, [sources_array]]]]]
```

Returns the complete notebook record — description, version, all sources.
Response can be **80–100 KB** for notebooks with many sources. The
`description_text` is the notebook's topic/search description set at creation.

```bash
curl http://localhost:8800/notebooks/bec06e03-7cf2-4989-bf17-bcb0ac9927a0/content
# Response: {"documents":["extracted text..."],"count":N}
```

---

#### `VfAZjd` — Generate Notebook AI Overview

**Called:** When the "Notebook Guide" / overview panel is displayed.

```python
args = [notebook_id, [2]]
# Response: [[[markdown_overview_text]]]
```

Returns the AI-written markdown overview of all notebook sources. The overview
is cached server-side and regenerated when sources change. If no overview exists
yet, this call may trigger generation (which takes a few seconds).

```bash
curl http://localhost:8800/notebooks/bec06e03-.../summary
# Response: {"notebook_id":"...","summary":"## Overview\n\nThis notebook..."}
```

---

#### `hPTbtc` — Get Conversation Thread IDs ⚠️ *Corrected in v3.0*

**Called:** When loading the conversation history panel.

```python
args = [[], None, notebook_id, page_size]   # page_size default: 20
# Response: [[[thread_id_string]]]
# Example: [[["f3acda91-f4b5-4b1c-8793-45bbd5fa45b0"]]]
```

Returns the list of conversation (sub-notebook) thread IDs for a notebook.
Each thread is a conversation started in the NLM "Add note or start discussing"
interface.

**Was incorrectly documented** in v2.1 as "List Sources Paginated". The actual
response contains UUIDs in a nested list structure matching conversation thread IDs.

```bash
curl "http://localhost:8800/notebooks/bec06e03-.../threads?page_size=20"
# Response: {"threads":[{"thread_id":"f3acda91-..."}],"count":1,"notebook_id":"..."}
```

---

#### `khqZz` — Read Conversation Thread Messages ⚠️ *Corrected in v3.0*

**Called:** When reading a specific conversation thread.

```python
args = [[], None, None, thread_id, page_size]   # thread_id from hPTbtc
# Response: [[[msg_id, [unix_sec, nano_sec], role, None, [[message_text]]]]]
# role codes: 2 = user, 1 = assistant (hypothesis based on ordering)
```

Reads all messages in a conversation thread. The `thread_id` must be obtained
first via `hPTbtc`.

**Was incorrectly documented** in v2.1 as "Sub-notebook sources". The response
contains message IDs, timestamps, role codes, and message text arrays.

```python
# Full conversation retrieval pattern
args_threads = json.dumps([[], None, notebook_id, 20])
_, data = _batchexecute("hPTbtc", args_threads, cookies, notebook_id)
# Extract thread IDs from data[0]
for thread_id in thread_ids:
    args_msgs = json.dumps([[], None, None, thread_id, 20])
    _, msgs = _batchexecute("khqZz", args_msgs, cookies, notebook_id)
    # msgs[0] is list of [msg_id, timestamp, role, null, [[text]]]
```

```bash
curl http://localhost:8800/notebooks/bec06e03-.../threads/f3acda91-.../
# Response: {"thread_id":"f3acda91-...","messages":["User: Q?","Assistant: A."],"count":4}
```

---

#### `gArtLc` — List Saved Artifacts

**Called:** When the notes/artifacts panel is opened.

```python
args = [_WRITE_CONFIG, notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
# Response: [[[artifact_id, title, type_int, [[source_id_arrays]], timestamp, ...]]]
```

Returns all saved artifacts (study guides, briefs, tables, slides). The filter
string excludes AI-suggested (not-yet-accepted) artifacts. Omit it to include
suggestions.

```bash
curl http://localhost:8800/notebooks/bec06e03-.../notes
# Response: {"notes":["# Study Guide\n\n..."],"count":2}
```

---

#### `sqTeoe` — List Audio Overview Types ⚠️ *Corrected in v3.0*

**Called:** When the Audio Overview panel is opened.

```python
args = [_WRITE_CONFIG, None, 1]
# Response: [[[[1, 'Deep dive', 'A lively conversation between two hosts...'],
#              [2, 'Brief', 'A bite-sized overview...'],
#              [3, 'Critique', 'An expert critical review...'],
#              [4, 'Debate', '...'],
#              [5, 'Interview', '...']]]]
```

Returns available audio overview styles with their display names and descriptions.
The integer at position 0 of each entry is the type ID used to trigger generation
(the trigger RPC itself is not yet captured — see Known Gaps).

**Was incorrectly documented** in v2.1 as "List All Notebooks".

---

#### `JFMDGd` — User Profile + Queries Remaining ⚠️ *Corrected in v3.0*

**Called:** When the user menu is opened or account info is needed.

```python
args = [notebook_id, [2]]
# Response: [[[email, 1, [], [display_name, avatar_url]]], None, queries_remaining]
# Example: [[["user@gmail.com", 1, [], ["Ray Daniels", "https://lh3..."]]], None, 1000]
```

Returns the signed-in user's profile. Third element is **remaining query count**.
For NotebookLM Plus, this is typically 1000; for free tier it is lower.

**Was incorrectly documented** in v2.1 as "Sources Condensed".

```bash
curl "http://localhost:8800/user/profile?notebook_id=bec06e03-..."
# Response: {"email":"user@gmail.com","name":"Display Name","queries_remaining":1000}
```

---

#### `ozz5Z` — Get Account UI State

**Called:** When account/subscription UI elements are rendered.

```python
args = [[[[None, "1", plan_tier_id],
          [None, None, None, None, None, None, None, None, None, [None, None, 4]],
          1]]]
# plan_tier_id: 1287 = NotebookLM Plus, 627 = standard
# Response: account plan info, subscription management URLs, feature flags
```

Returns subscription tier information, plan management URL, and UI feature flags.

```bash
curl http://localhost:8800/user/quota
# Response: {"quota_data":[...],"extracted":["NotebookLM Plus","..."]}
```

---

#### `CCqFvf` — Resume Session / Load Last Notebook ⭐ *New in v3.0*

**Called:** On every page load from the homepage (`/`).

```python
args = ["", None, None, [2], [1, None, None, None, None, None, None, None, None, None, [1]]]
# Response: ["", None, last_notebook_id, None, None, state_obj, None, ..., [[conv_thread_id]]]
# Example: ["", None, "50ab3060-466e-4c90-aacb-8134a130de29", None, None, [...], ...,
#           [["3a6cd367-f1a2-4b3c-8d5e-6f7a8b9c0d1e"]]]
```

Called on every homepage visit. Resumes the user's last active session and
returns the last-used notebook ID and its conversation thread ID. The first
argument `""` means "use last session". The `[2]` flag requests full source data.

**Notebook creation insight:** Across 8 HAR files, we never observed a batchexecute
RPC being called to create a notebook. The notebook UUID is generated client-side
in browser JavaScript, and the backend record is created lazily on the first
mutation (e.g. `LBwxtb`). This means we can generate UUID v4 values and use them
as notebook IDs immediately.

---

#### `tr032e` — Get Source AI Summary

**Called:** When clicking on a source in the NLM UI.

```python
args = [[[[source_id]]]]   # source_id wrapped in 3 levels of nesting
# Response: [[[None, [summary_markdown_text]]]]
```

Returns the AI-generated summary shown in the source detail panel. This is the
short overview text — not the full source content. For full content, use
`wXbhsf` / `rLM1Ne` which return the source object with all metadata.

```bash
curl http://localhost:8800/sources/3fa4b5c6-d7e8-9f0a-b1c2-d3e4f5a6b7c8/content
# Response: {"source_id":"...","content":"markdown summary text...","word_count":234}
```

---

### Write RPCs (7 confirmed)

#### `s0tc2d` — Ask Question / Chat (Asynchronous)

**Called:** When the user sends a message in the chat interface.

```python
inner_msg = [[2, question_text], [response_length]]
chat_config = [
    role_string_or_none,   # position 0: Configure Chat role (optional)
    None, None, None, None, None, None,  # positions 1–6: reserved
    inner_msg,             # position 7: message content
]
args = [notebook_id, [chat_config]]
# Response: [notebook_title, null, notebook_id, emoji, null, [status_flags...],
#            null, [[2,"question"],[resp_len]]]
```

⚠️ **The response does NOT contain the answer.** The answer is generated
asynchronously by Gemini. To retrieve it:
1. Call `hPTbtc` to get the thread IDs for the notebook
2. Call `khqZz` with the relevant thread ID to read the messages
3. Or poll `GET /notebooks/<id>/history` via the proxy

**Response length values:**
| Value | Meaning |
|-------|---------|
| `4` | Default length |
| `1` | Longer (extended) response |
| `2` | Shorter (brief) response |

**Configure Chat role examples:**
```python
# Teacher persona
role = "Act as a patient teacher. Use simple language with concrete examples. Structure answers clearly."

# Research analyst
role = "You are a PhD researcher. Cite specific passages. Be analytical and thorough."

# Code generator
role = "You are an expert Python developer. Provide working, typed, documented code."

# Knowledge distiller (for Nexus pipeline)
role = "Extract key facts and generate structured Q&A pairs. Use format: Q: ... A: ..."
```

```bash
# Chat (async — answer arrives in conversation history)
curl -X POST http://localhost:8800/notebooks/bec06e03-.../chat \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the main contributions?","role":"Act as a researcher"}'
# Response: {"queued":true,"notebook_title":"...","note":"Poll /history for answer"}

# Poll for the answer
curl http://localhost:8800/notebooks/bec06e03-.../history
```

---

#### `CYK0Xb` — Save Notebook Note ⚠️ *Corrected in v3.0*

**Called:** When creating a text note in the notebook; also used by the proxy
for citation-annotated Q&A (a dual-use pattern).

```python
# Primary use: save a note
args = [notebook_id, note_markdown_text]
# Response: [[note_id, saved_note_text, ...]]
# Example: [["d4e015e3-b6f0-4deb-9024-e297a94fc2bf", "# Note title\n\nContent..."]]

# Proxy Q&A use: pass a question as the "note text" — NLM annotates it with citations
args = [notebook_id, question_text]
# Response: [[answer_id, answer_with_inline_citations]]
# Example: [["abc123", "The main argument is X [src_uuid1]. Supporting evidence..."]]
```

The citation format in answers is `[source_uuid]` — square-bracketed UUIDs that
reference specific source documents. These can be extracted with:
```python
source_refs = re.findall(r"\[([a-f0-9-]{36})\]", answer_text)
```

**Was incorrectly documented** in v2.1 as "Legacy Chat RPC". The RPC saves notes
and also performs annotation/Q&A in a single call pattern.

```bash
# Ask with citations (synchronous — answer returned immediately)
curl -X POST http://localhost:8800/notebooks/bec06e03-.../ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the main methodology?","mode":"annotate"}'
# Response: {"answer_id":"uuid","answer":"The methodology uses... [src_uuid]","sources":["uuid"]}
```

---

#### `R7cb6c` — Generate Report / Save Document

**Called:** When the user saves a generated report artifact.

```python
source_array = [[[src_id]] for src_id in source_ids]  # triple-nested
report_body = [None, None, report_type, source_array]
args = [_WRITE_CONFIG, notebook_id, report_body]
# Response: [[report_id, title, type_int, [[source_id_arrays]], ...]]
```

**Report type codes:**
| `report_type` | Format | Confirmation |
|--------------|--------|-------------|
| `2` | Research brief / summary | ✅ HAR-confirmed |
| `9` | Free-form notes | ✅ HAR-confirmed |
| `3`–`8` | Study guide, FAQ, Timeline, Outline, Glossary, Table | Inferred from UI |

```bash
curl -X POST http://localhost:8800/notebooks/bec06e03-.../save_note \
  -H "Content-Type: application/json" \
  -d '{"source_ids":["uuid1","uuid2"],"note_type":2}'
# Response: {"note_id":"uuid","title":"Research Brief","note_type":2}
```

---

#### `ciyUvf` — Generate Suggested Report Preview

**Called:** When the NLM UI generates a preview of what a report would look like.

```python
source_id_arrays = [[src_id] for src_id in source_ids]   # double-nested
args = [_WRITE_CONFIG, notebook_id, source_id_arrays]
# Response: [[[preview_id, title, description, [[source_ids]], ...]]]
```

Generates a preview (title + description) of a report from selected sources.
The preview is a suggestion — call `R7cb6c` to persist it.

```bash
curl -X POST http://localhost:8800/notebooks/bec06e03-.../generate \
  -H "Content-Type: application/json" \
  -d '{"source_ids":["uuid1","uuid2"],"doc_type":2}'
# Response: {"title":"AI Research Methods","description":"This brief covers...","source_ids":[...]}
```

---

#### `cFji9` — Generate / Get Mind Map ⚠️ *Corrected in v3.0*

**Called:** When the Mind Map panel is opened.

```python
args = [notebook_id, None, cursor_timestamp, [2]]
# cursor_timestamp: [unix_sec, nano_sec] for cache check, or None for fresh
# Response: [[[mind_map_id, [mind_map_id, json_tree_string]]]]
```

Returns (or generates) a D3-compatible hierarchical tree JSON string:
```json
{
  "name": "Root Topic",
  "children": [
    {"name": "Subtopic A", "children": [{"name": "Leaf Node"}]},
    {"name": "Subtopic B", "children": [{"name": "Another Leaf"}]}
  ]
}
```

**Was incorrectly documented** in v2.1 as "Conversation History".

```bash
curl http://localhost:8800/notebooks/bec06e03-.../mindmap
# Response: {"notebook_id":"...","mindmap":{"name":"Root","children":[...]}}
```

---

#### `Ljjv0c` — Start Fast Research Session ⭐ *New in v3.0*

**Called:** When "Fast Research" is initiated in the NLM UI.

```python
args = [[search_query, 1], None, 1, notebook_id]
# The "1" in [search_query, 1] = search type: 1=web search
# The standalone "1" after None = request mode flag
# Response: [research_session_id]
# Example: ["22200e6d-8653-43c7-bedc-cdf6c6a787fb"]
```

Initiates a server-side web search for sources related to the query. The returned
`research_session_id` UUID must be passed to `LBwxtb` to add the discovered
sources to the notebook. The session ID acts as an authorization token tying the
source-add operation to the search.

```bash
curl -X POST http://localhost:8800/notebooks/bec06e03-.../research \
  -H "Content-Type: application/json" \
  -d '{"query":"multi-agent AI systems 2025"}'
# Response: {"session_id":"22200e6d-...","notebook_id":"...","query":"multi-agent AI..."}
```

---

#### `LBwxtb` — Add URL Sources (Batch) ⭐ *New in v3.0*

**Called:** After `Ljjv0c`, to actually add sources to the notebook.

```python
sources_array = [
    # Web URL (url and title at position 2):
    [None, None, [url, title], None, None, None, None, None, None, None, 2],

    # YouTube URL (url at position 7, NOT position 2 — different format!):
    [None, None, None, None, None, None, None, [youtube_url], None, None, 2],

    # PDF URL (same format as web URL):
    [None, None, [pdf_url, filename], None, None, None, None, None, None, None, 3],
]
args = [None, [1], research_session_id, notebook_id, sources_array]
# Response: [[[source_id], title, [None, word_count, [ts_sec, ts_ns],
#             [process_id, [ts_sec, ts_ns]], format_type, None, status,
#             [url], char_count], [None, 2]]]
```

**Source entry position cheatsheet:**
| Position | Web URL | YouTube URL |
|----------|---------|-------------|
| `[2]` | `[url, title]` | `None` |
| `[7]` | `None` | `[url]` |
| Final int | `2` (web) | `2` (YouTube) — format type in last position |

**Critical:** After calling `LBwxtb`, sources are NOT immediately ready.
NLM processes them asynchronously (fetches, extracts text, indexes). Poll
`rLM1Ne` until all sources have `word_count > 0` before querying.

**Open question:** Can `LBwxtb` be called with a dummy/empty session ID?
All observed calls in 8 HARs included a valid `research_session_id` from
a prior `Ljjv0c` call. We have not confirmed whether it is strictly required.

```bash
# Complete flow: start research session, then add sources
SESSION_ID=$(curl -s -X POST http://localhost:8800/notebooks/bec06e03-.../research \
  -H "Content-Type: application/json" \
  -d '{"query":"AI agents"}' | jq -r '.session_id')

curl -X POST http://localhost:8800/notebooks/bec06e03-.../sources \
  -H "Content-Type: application/json" \
  -d "{\"urls\":[{\"url\":\"https://example.com/paper\",\"title\":\"AI Paper\"}],
       \"session_id\":\"$SESSION_ID\"}"
# Response: {"added":1,"session_id":"...","poll_url":"/notebooks/.../sources/wait"}

# Poll until ready
curl "http://localhost:8800/notebooks/bec06e03-.../sources/wait?timeout=120&interval=5"
# Response: {"ready":true,"sources":[...],"pending_count":0,"elapsed_seconds":23.4}
```

---

## Part 5: The GenerateFreeFormStreamed Proto Endpoint

This is the only non-batchexecute endpoint we've confirmed. It's a server-streaming
gRPC call made over HTTP/1.1 (not native gRPC), used for the Fast Research report
generation.

### Endpoint

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
     google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/
     GenerateFreeFormStreamed
```

URL parameters: same as batchexecute (`bl`, `f.sid`, `hl`, `_reqid`, `rt=c`).

### Request Structure

The body uses the same `f.req=<url_encoded>` format as batchexecute:

```python
inner_args = [
    [[[src_id]] for src_id in source_ids],  # position 0: source ID arrays
    question_text,                           # position 1: research question
    None,                                    # position 2: reserved
    [2, None, [1], [1]],                    # position 3: generation config flags
    conv_thread_id,                          # position 4: conversation thread (from CCqFvf)
    None,                                    # position 5: reserved
    None,                                    # position 6: reserved
    notebook_id,                             # position 7: target notebook
    None, None, None, None,                  # positions 8–11: reserved
]
f_req = [None, json.dumps(inner_args)]   # note: [None, ...] not [["rpc_id", ...]]
body = urllib.parse.urlencode({"f.req": json.dumps(f_req)})
```

### Response

Streaming SSE — same `)]}'` prefix, chunks arrive as the report is generated:

```
)]}'
<length>
[["wrb.fr", null, "[[[null, \"First chunk of report text...\"]]]", ...]]
<length>
[["wrb.fr", null, "[[[null, \"...continuation of report...\"]]]", ...]]
<length>
[["wrb.fr", null, "[[[turn_id, null, true]]]", ...]]   ← final chunk
```

Note `null` as the RPC ID in `wrb.fr` blocks (because it's not a standard
batchexecute call — the endpoint itself names the operation).

### Fast Research Full Flow

```python
# 1. Start a Fast Research session (web search)
args = json.dumps([["multi-agent AI", 1], None, 1, notebook_id])
_, data = _batchexecute("Ljjv0c", args, cookies, notebook_id)
session_id = data[0]  # research_session_id UUID

# 2. Add discovered sources
sources = [
    [None, None, ["https://example.com/paper1", "Paper 1"], None, None, None, None, None, None, None, 2],
    [None, None, ["https://example.com/paper2", "Paper 2"], None, None, None, None, None, None, None, 2],
]
args = json.dumps([None, [1], session_id, notebook_id, sources])
_, added_sources = _batchexecute("LBwxtb", args, cookies, notebook_id)

# 3. Poll until all sources processed (rLM1Ne)
for _ in range(30):
    _, data = _batchexecute("rLM1Ne", json.dumps([notebook_id, None, [2], None, 0]), cookies)
    _, srcs = _extract_sources(data)
    if all(s["word_count"] > 0 for s in srcs):
        break
    time.sleep(10)

# 4. Get thread ID for conversation
args = json.dumps([[], None, notebook_id, 20])
_, t_data = _batchexecute("hPTbtc", args, cookies, notebook_id)
thread_id = t_data[0][0][0]  # first thread

# 5. Generate the report (streaming proto endpoint)
source_ids = [s["id"] for s in srcs]
inner_args = [
    [[[sid]] for sid in source_ids],
    "Summarize and analyze the key findings",
    None, [2, None, [1], [1]],
    thread_id, None, None, notebook_id,
]
# → Call GenerateFreeFormStreamed endpoint with streaming reader

# 6. Store in Nexus
nexus.add_entry("Fast Research Report", report_text, category="research")
```

---

## Part 6: Source Data Structure

All source objects share a common JSPB array structure. Understanding positions
is essential for extracting fields correctly.

### Full Schema

```python
source = [
    [source_id],              # position 0: UUID wrapped in list — access as source[0][0]
    "display_name",           # position 1: filename or web page title
    [                         # position 2: metadata array
        None,                 #   [2][0]: reserved / null
        word_count,           #   [2][1]: word count (int) — 0 if still processing
        [unix_sec, nano_sec], #   [2][2]: created_at timestamp
        [process_id, [unix_sec, nano_sec]],  # [2][3]: processing job info
        format_type,          #   [2][4]: source type code (see table)
        None,                 #   [2][5]: reserved
        status_code,          #   [2][6]: 1=private, 2=shared/processed
        [url],                #   [2][7]: source URL (web/YouTube only — None for uploads)
        char_count,           #   [2][8]: character count (optional)
    ],
    [None, add_method]        # position 3: [null, add_method_code]
]
```

### Source Format Type Codes

| Code | Type | URL Format |
|------|------|-----------|
| `1` | Google Doc (Drive) | `docs.google.com/document/...` |
| `2` | Google Slides | `docs.google.com/presentation/...` |
| `3` | PDF | Direct PDF URL or Drive PDF |
| `5` | Web article / URL | Any `https://` URL |
| `7` | YouTube video | `youtube.com/watch?v=...` |
| `8` | Markdown / plain text | Uploaded .md or .txt file |

### Add Method Codes

| Code | Source |
|------|--------|
| `1` | File upload (PDF, text, markdown) |
| `2` | URL (web, YouTube, Google Drive) |

### Parsing Example

```python
def parse_source(src: list) -> dict:
    """Parse a raw source JSPB array into a Python dict."""
    try:
        source_id   = src[0][0] if isinstance(src[0], list) else src[0]
        title       = src[1] if isinstance(src[1], str) else ""
        meta        = src[2] if len(src) > 2 and isinstance(src[2], list) else []
        word_count  = meta[1] if len(meta) > 1 and isinstance(meta[1], int) else 0
        format_type = meta[4] if len(meta) > 4 else None
        status      = meta[6] if len(meta) > 6 else None
        url         = meta[7][0] if (len(meta) > 7 and isinstance(meta[7], list)
                                     and meta[7]) else ""
        char_count  = meta[8] if len(meta) > 8 and isinstance(meta[8], int) else 0
        add_method  = src[3][1] if (len(src) > 3 and isinstance(src[3], list)
                                    and len(src[3]) > 1) else None
        return {
            "id": source_id, "title": title, "url": url,
            "word_count": word_count, "char_count": char_count,
            "format_type": format_type, "status": status,
            "add_method": add_method,
            "ready": word_count > 0,
        }
    except (IndexError, TypeError):
        return {}
```

---

## Part 7: Notebook Lifecycle

### Creating a Notebook

**No batchexecute RPC was observed for notebook creation.** Across 8 HAR files
spanning diverse usage patterns, we never captured a "create notebook" batchexecute
call. The explanation: the NLM frontend generates a UUID v4 in JavaScript and
makes no network call. The backend record is created lazily on the first mutation.

```python
import uuid
notebook_id = str(uuid.uuid4())  # e.g. "bec06e03-7cf2-4989-bf17-bcb0ac9927a0"
# No NLM call needed — backend will create the record when LBwxtb is called
```

```bash
# Proxy creates the UUID for you:
POST http://localhost:8800/notebooks
Body: {"title": "My Research Notebook"}
# Response: {"notebook_id":"uuid-v4","title":"...","warning":"Add sources to materialise."}
# HTTP 201
```

### Adding Sources

```
1. [POST /notebooks/<id>/research]  → Ljjv0c → research_session_id
2. [POST /notebooks/<id>/sources]   → LBwxtb → sources added (async processing starts)
3. [GET  /notebooks/<id>/sources/wait] → rLM1Ne loop → all word_count > 0
```

### Querying

```
4. [POST /notebooks/<id>/ask]        mode="annotate" → CYK0Xb → answer with citations
5. [POST /notebooks/<id>/chat]       → s0tc2d → queued response
6. [GET  /notebooks/<id>/history]    → hPTbtc + khqZz → conversation messages
```

### Reading Results

```
7. [GET /notebooks/<id>/summary]    → VfAZjd → AI overview
8. [GET /notebooks/<id>/mindmap]    → cFji9  → D3 mind map JSON
9. [GET /notebooks/<id>/notes]      → gArtLc → saved artifacts
10. [GET /sources/<id>/content]     → tr032e → full source text
```

### State Diagram

```
                     ┌─────────────────────────────────────┐
                     │         Notebook Lifecycle           │
                     └─────────────────────────────────────┘

    [UUID Gen]     [Ljjv0c]     [LBwxtb]      [rLM1Ne poll]
        │              │             │               │
    Generate  →  Start Research  → Add URLs  →   Wait Ready
      UUID         Session             │               │
        │                              │         word_count > 0
        │            ╔═════════════════╩═════════════╗
        │            ║        Sources Ready           ║
        │            ╚═══════════╦═══════════════════╝
        │                        │
        │           ┌────────────┼────────────┐
        │           │            │            │
        │      [CYK0Xb]     [s0tc2d]     [VfAZjd]
        │      Ask w/cites  Async chat   AI Overview
        │           │            │
        │     Answer now   [hPTbtc+khqZz]
        │                  Poll threads
        │
    ┌───▼────────────────────────────────────────┐
    │  [cFji9] Mind map  [R7cb6c] Save report    │
    │  [gArtLc] List notes  [tr032e] Source text │
    └────────────────────────────────────────────┘
```

---

## Part 8: Multi-Question Batching

One of the most powerful capabilities of batchexecute: **up to 5 RPCs in a
single HTTP request**.

```python
# 5 questions → 1 HTTP request → 5× throughput
calls = [
    ("CYK0Xb", json.dumps([notebook_id, q]))
    for q in questions[:5]
]
# f.req structure:
f_req = [
    ["CYK0Xb", json.dumps([notebook_id, "Q1?"]), None, "generic"],
    ["CYK0Xb", json.dumps([notebook_id, "Q2?"]), None, "generic"],
    ["CYK0Xb", json.dumps([notebook_id, "Q3?"]), None, "generic"],
    ["CYK0Xb", json.dumps([notebook_id, "Q4?"]), None, "generic"],
    ["CYK0Xb", json.dumps([notebook_id, "Q5?"]), None, "generic"],
]
# rpcids URL param: "CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb;CYK0Xb"
```

**Response parsing** — 5 `wrb.fr` blocks, one per answer, in order:
```
[["wrb.fr","CYK0Xb","[[\"answer-id-1\",\"Answer 1 text...\"]...]",...]]
[["wrb.fr","CYK0Xb","[[\"answer-id-2\",\"Answer 2 text...\"]...]",...]]
...
```

The proxy handles this via `_batchexecute_multi()` → `_parse_batchexecute_multi()`.

**Practical throughput:**
- 20 questions at batch size 5 = 4 HTTP requests
- With 1.5s rate limit: ~6 seconds total (vs 30s sequential)
- With 3.0s rate limit: ~12 seconds total (vs 60s sequential)

---

## Part 9: RPC ID Rotation

### Why IDs Change

RPC IDs are **compiled into Google's JavaScript frontend bundle**. When Google
deploys a new frontend version (approximately weekly), the build process assigns
new IDs. The old IDs remain valid until the old frontend is fully decommissioned
(typically 2–4 weeks after a new deploy).

The BL (build label) is the version marker. A stale BL = potentially stale IDs.

### Stability Characteristics

From our 8 HAR analysis sessions (spanning ~10 days):
- **Read RPCs are more stable** — `ub2Bae`, `wXbhsf`, `VfAZjd` persisted unchanged
- **Write RPCs change more often** — chat RPCs changed between sessions
- `CYK0Xb` changed role (old chat → save note) after build `20260226`
- `s0tc2d` appeared as the replacement chat RPC in build `20260226`

### Resilience Architecture

The proxy uses a 3-layer fallback for RPC IDs:

```
Layer 1: data/nlm_rpc_registry.json  ← Updated by nlm_automation.py (Playwright)
Layer 2: nlm_rpc_mapper._FALLBACK_RPC_IDS  ← Hardcoded confirmed IDs
Layer 3: Module-level constants in nlm_live_proxy.py  ← Last resort

def _rpc(operation: str, fallback: str) -> str:
    if _registry_available:
        rid = _get_rpc_id(operation)  # Layer 1
        if rid:
            return rid
    return fallback  # Layer 2/3
```

### Re-Discovery Procedure

When Google deploys a new frontend:
1. Check `GET /health` — if `bl_stale: true`, action needed
2. Import a fresh HAR: `POST /cookies/import {"har_path": "..."}`
3. Auto-refresh tokens: `POST /cookies/refresh`
4. Run Playwright automation: `python -m engine.nexus.nlm_automation`
   — This drives Chrome, captures all batchexecute calls, maps IDs to operations
5. Verify recovery: `GET /rpc_registry` to confirm all IDs loaded

---

## Part 10: Known Gaps

Operations that exist in the NLM UI but were **not observed** in any of the 8
HAR capture sessions. Capturing these requires performing each specific action
while recording a HAR with "Include sensitive information" enabled.

| Operation | Status | Notes |
|-----------|--------|-------|
| **Delete Notebook** | ❌ Unknown RPC | Never performed during any capture session |
| **Delete Source** | ❌ Unknown RPC | Never performed during any capture session |
| **Rename Notebook** | ❌ Unknown RPC | Never performed during any capture session |
| **Rename Source** | ❌ Unknown RPC | Never performed during any capture session |
| **Add Text Source** (paste text) | ❌ Unknown RPC | Different from URL add — may use different endpoint |
| **Add File Source** (upload PDF) | ❌ Likely multipart/form-data | Probably a separate `/upload` endpoint, not batchexecute |
| **Add Google Drive source** | ❌ Partially known | `ub2Bae` shows Drive sources (format type 1/2) but add RPC unknown |
| **Generate Audio Overview** | ❌ Unknown trigger RPC | `sqTeoe` lists types but the trigger call was not captured |
| **Audio Overview Status Poll** | ❌ Unknown RPC | Needed for completion detection |
| **Share Notebook** | ❌ Unknown RPC | Never performed during any capture session |
| **Export Notebook** | ❌ Unknown | May be a download endpoint, not RPC |
| **Collaborative editing** | ❌ Unknown | May use different transport entirely |

**How to capture:** Export a HAR while performing each operation. For each operation:
1. Open DevTools → Network → check "Preserve log"
2. Perform the specific action (e.g. click Delete on a source)
3. Export HAR with "Include sensitive information" checked
4. Import via `POST /cookies/import`
5. The new BL and any new RPC IDs will be auto-extracted

---

## Part 11: CosySim Proxy Architecture

### Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    CosySim NLM Integration                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐    ┌──────────────────────────────────┐   │
│  │   MCP Skills      │    │   NLM Live Proxy (Flask :8800)  │   │
│  │  nlm_skills.py   ├───►│   nlm_live_proxy.py             │   │
│  │  (21 NLM tools)  │    │   - 35+ REST endpoints          │   │
│  └──────────────────┘    │   - Rate limiter (_RateLimiter)  │   │
│                           │   - RPC registry (nlm_rpc_mapper)│  │
│  ┌──────────────────┐    │   - Cookie/meta management       │   │
│  │   NLM Engine     │    └──────────────┬───────────────────┘   │
│  │  nlm_engine.py   ├───────────────────┘                       │
│  │  4-tier pipeline │                   │                        │
│  └──────────────────┘            ┌──────▼───────────────────┐   │
│                                  │  batchexecute transport  │   │
│  ┌──────────────────┐            │                          │   │
│  │  NLM Automation  │            │  POST notebooklm.google  │   │
│  │  nlm_automation  ├────────────┤  /_/LabsTailwindUi/data  │   │
│  │  (Playwright)    │  updates   │  /batchexecute           │   │
│  └──────────────────┘  registry  │                          │   │
│                                  │  21 RPCs + 1 proto       │   │
│  ┌──────────────────┐            └──────────────────────────┘   │
│  │  RPC Registry    │                                            │
│  │  nlm_rpc_mapper  │  data/nlm_rpc_registry.json               │
│  │                  │  data/nlm_cookies.json                     │
│  └──────────────────┘  data/nlm_meta.json                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Files

| File | Contents | Updated By |
|------|----------|-----------|
| `data/nlm_cookies.json` | Google auth cookies (SID, SAPISID, etc.) | HAR import, CDP capture |
| `data/nlm_meta.json` | `bl`, `f_sid`, `at`, `bl_updated_at` | HAR import, `refresh_session_tokens()` |
| `data/nlm_rpc_registry.json` | Current RPC ID → operation mappings | `nlm_automation.py` (Playwright) |

### Request Flow

```
Agent/Tool call
      │
      ▼
MCP Skill (nlm_live_ask, etc.)
      │
      ▼
NLMClient method  OR  Flask route handler
      │
      ▼
_batchexecute() / _batchexecute_multi()
      │
      ├── _get_bl()          reads data/nlm_meta.json
      ├── _get_fsid()        reads data/nlm_meta.json
      ├── _build_headers()   computes SAPISIDHASH
      ├── _rate_limiter.wait()  enforces min gap
      │
      ▼
urllib.request POST to notebooklm.google.com
      │
      ▼
_parse_batchexecute_multi()
      │   strips )]}'
      │   extracts wrb.fr blocks
      │   double-decodes inner JSON
      ▼
Parsed response → returned to caller
```

### Auto-Retry on Null

If **all** results from a batch call are `None` (common when `at` or `f.sid`
are stale), the proxy automatically:
1. Calls `refresh_session_tokens()` — loads the NLM page, extracts fresh tokens
2. Retries the entire batch exactly once (`_refreshed=True` flag prevents loops)

---

## Part 12: Security & Operational Notes

### Cookie Security

- Cookies are stored in plaintext in `data/nlm_cookies.json`
- This file should be in `.gitignore` (it is — confirmed)
- Never log cookie values at INFO or lower level
- The proxy returns cookie **names only** (not values) from `GET /cookies`

### Rate Limiting Rationale

NotebookLM is a consumer product, not a developer API. There is no official
rate limit documentation. From our usage:
- **1.5s gap** — safe for normal usage (interactive pace)
- **<0.8s gap** — may return empty responses from soft-limit enforcement
- **Batch calls are 1 request** — use batching to maximise throughput within limits

Google's soft limits appear to be based on request count per minute, not data
volume. 5 questions per 1.5s = ~200 questions/minute — we've tested this without
triggering limits. Going above ~300/minute risks soft-limits.

### Proxy Startup

The proxy starts successfully even without cookies — it returns 503 on auth-
requiring routes but 200 on `/health` and cookie management routes. This allows
the health check to pass in CI/deployment even before cookies are provisioned.

---

*Last updated: 2026-02-28 | v1.0 — 21 RPCs + GenerateFreeFormStreamed confirmed across 8 HAR sessions*
