# Exploration Journal — Reverse-Engineering Google's Internal APIs

**A technical narrative of how CosySim learned to talk to NotebookLM, Gemini, AI Studio, GitHub Copilot, and Google Workspace — without a single official API.**

Version: v2.0 [2026-03-23]
Author: Knack + Claude Code

---

## Prologue: The Problem

CosySim is a local-first AI simulation framework. It needed to connect to frontier AI models — but not through official SDKs. The goal was to build a unified pipeline where local agents could query NotebookLM for grounded research, Gemini for generation, AI Studio for embeddings, GitHub Copilot for 38 frontier models, and LMStudio for local inference — all through a single interface.

None of these services had public APIs for what we needed. NotebookLM has no API at all. Gemini's internal protocol is undocumented. GitHub Copilot's model access isn't meant for programmatic use. So we reverse-engineered everything.

This is the story of how.

---

## Chapter 1: Cracking batchexecute

### The First HAR File

It started with Chrome DevTools. Open NotebookLM in the browser, open the Network tab, use the app, export a HAR file. Inside that HAR file: every HTTP request the browser made.

The pattern was immediately obvious. Every operation — creating a notebook, adding a source, asking a question — went through a single endpoint:

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
```

The request body was URL-encoded with a parameter called `f.req` containing a JSON array:

```json
[[["wXbhsf", "[null,1,null,[2]]", null, "generic"]]]
```

That 6-7 character string (`wXbhsf`) is an **rpcid** — Google's internal operation identifier. Different rpcid = different operation. The second element is the payload, JSON-encoded as a string. The response comes back in a custom format:

```
)]}'
[["wrb.fr","wXbhsf","[...response_json...]",null,null,null,"generic"]]
```

Strip the `)]}'\n` JSONP safety prefix, parse the outer array, find the `wrb.fr` items, extract the JSON string at position [2], parse that. Five layers of decoding for every response.

We had our first breakthrough: batchexecute is Google's universal internal RPC framework. The same protocol powers Docs, Sheets, Drive, Gemini, NotebookLM, and Apps Script. Different service, different rpcids, same wire format.

### The Authentication Puzzle

The browser sends a wall of cookies with every request. Through trial and error, we identified which ones matter:

- **SID, SSID, HSID, APISID** — core Google session identifiers
- **SAPISID, __Secure-3PAPISID** — used to compute the SAPISIDHASH anti-abuse header
- **__Secure-3PSID, __Secure-3PSIDTS** — same-site secure session variants

The SAPISIDHASH computation was the first real reverse-engineering win:

```python
timestamp = str(int(time.time()))
raw = f"{timestamp} {SAPISID_cookie} https://notebooklm.google.com"
hash_value = hashlib.sha1(raw.encode()).hexdigest()
header = f"SAPISIDHASH {timestamp}_{hash_value}"
```

**But then a critical discovery:** We were adding SAPISIDHASH to batchexecute calls and getting HTTP 400 errors. After comparing our requests to actual browser HAR traffic side-by-side, we realized: **NotebookLM batchexecute does NOT use SAPISIDHASH**. It authenticates purely via cookies + the `at` CSRF token in the POST body. Adding the extra header broke it. (Other Google services like Colab and Sheets DO use SAPISIDHASH — it's per-service.)

### The Build Label Problem

Every batchexecute call requires a `bl` (build label) parameter in the URL query string:

```
?bl=boq_labs-tailwind-frontend_20260226.08_p0
```

This is the frontend deploy version. Google pushes new frontend builds roughly weekly. When the build label changes, **all requests with the old label silently return null**. No error, no 400, no 401 — just empty responses. This was maddening to debug the first time it happened. Everything was "working" but returning nothing.

We also need `f.sid` (server session ID) and `at` (anti-CSRF token), both extracted from a JavaScript object called `WIZ_global_data` embedded in the page HTML. Google obfuscates the key names — we found the session ID under keys like `IxjpMA` or `FdrFJe`, and the CSRF token under `SNlM0e`. These change with each page load.

### Building the RPC Catalog

Over several sessions, we analyzed 8+ HAR files and mapped rpcids to operations:

| RPC ID | Operation | How We Figured It Out |
|--------|-----------|----------------------|
| `wXbhsf` | List sources | Fired when opening a notebook |
| `rLM1Ne` | Load notebook | Fired on notebook navigation |
| `ub2Bae` | List notebooks | Fired on homepage load |
| `CYK0Xb` | Create note (Q&A) | Fired when asking a question |
| `VfAZjd` | AI summary | Fired when requesting a study guide |
| `izAoDd` | Add source | Fired when adding a URL |
| `tGMBJ` | Delete source | Fired when removing a source |
| `ozz5Z` | Feature flags | Fired on app initialization |
| `sqTeoe` | Audio overview types | Fired in audio panel |

We eventually cataloged **49 NotebookLM rpcids** and **36 Gemini rpcids**.

---

## Chapter 2: The Great Misidentification (v2.x → v3.1)

### The Crisis

On **2026-02-28**, a fresh manual HAR capture (`manual_testing.har`) revealed a catastrophic error in our v2.x RPC mappings. We had been using `s0tc2d` as the chat message rpcid. It's not. **It's RENAME_NOTEBOOK.**

```
WRONG (v2.x):
  s0tc2d = RPC_CHAT_MESSAGE     ← WRONG
  sqTeoe = "list all notebooks"  ← WRONG
  cFji9  = "conversation history" ← WRONG

CORRECT (v3.0+):
  s0tc2d = RPC_RENAME_NOTEBOOK   ← Actually renames
  sqTeoe = RPC_LIST_AUDIO_TYPES  ← Audio overview options
  cFji9  = RPC_MIND_MAP          ← Mind map / sync notes
```

Sixteen rpcids were wrong. We had been sending rename requests thinking we were chatting.

### The Real Chat Endpoint

The biggest discovery from this correction: **real NLM chat doesn't use batchexecute at all.** It uses a gRPC-web streaming endpoint:

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
     google.internal.labs.tailwind.orchestration.v1.
     LabsTailwindOrchestrationService/GenerateFreeFormStreamed
```

The payload is a 9-element array:

```python
[source_ids, question, history, [2, None, [1], [1]], thread_id, None, None, notebook_id, 1]
```

The response streams progressively — full text at each chunk, not deltas. This was a completely different protocol from batchexecute.

---

## Chapter 3: Chrome DevTools Protocol — The Browser as API

### Why CDP?

After the rpcid corrections, we had a working batchexecute client for source management (add, delete, list) but chat required the gRPC streaming endpoint. The problem: calling that endpoint server-side required headers that only the browser adds automatically (`x-browser-validation`, specific cookie scoping).

Solution: **inject JavaScript directly into the browser** via Chrome DevTools Protocol.

### The CDP Live Probe (`cdp_live_probe.py`)

This was the proof-of-concept. Connect to Chrome on port 9223 via WebSocket, inject a `fetch()` call, let the browser handle auth:

```python
# 1. Connect to Chrome
tabs = requests.get("http://localhost:9223/json").json()
nlm_tab = next(t for t in tabs if "notebooklm.google.com" in t["url"])

# 2. Connect via WebSocket
ws = websocket.create_connection(nlm_tab["webSocketDebuggerUrl"])

# 3. Extract session tokens from page
ws.send(json.dumps({
    "id": 1, "method": "Runtime.evaluate",
    "params": {"expression": "JSON.stringify(window.WIZ_global_data)"}
}))
# Parse out bl, f_sid, at from the response

# 4. Inject fetch() — browser adds all auth automatically
js = f"""
fetch('https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute?...', {{
    method: 'POST',
    credentials: 'include',  // ← Browser adds cookies automatically
    body: 'f.req=...'
}}).then(r => r.text())
"""
ws.send(json.dumps({
    "id": 2, "method": "Runtime.evaluate",
    "params": {"expression": js, "awaitPromise": True}
}))
```

**This worked.** The browser handles cookies, CORS, and all Google's anti-automation headers. We just needed to inject the right fetch call.

### Debugging the Stream (`nlm_debug_chunks.py`)

The streaming response from `GenerateFreeFormStreamed` comes back in `wrb.fr` chunks. Each chunk has different structure — some contain text, some contain status codes, some contain metadata. This script attached to a running NLM tab via CDP, injected a chat request, and printed every chunk with its structure annotated. This is how we learned:

- Text lives in nested arrays at varying depths
- Status/error info is at position [5] in the wrb.fr item
- Gemini "thinking" traces appear as bold headers (`**Analyzing...**`) before the real answer
- The final answer must be extracted by skipping thinking traces

---

## Chapter 4: The ARGUS Intelligence Platform

### From Manual to Automated Discovery

After the v2.x → v3.1 crisis, it was clear that manual HAR analysis wouldn't scale. Google rotates rpcids with every frontend deploy (~weekly). We needed automated discovery.

ARGUS (Automated Reconnaissance & Google Universal Surveyor) was built as a living API intelligence platform with multiple signal sources:

### Signal Sources

**1. Network Traffic Capture (CDP)**
- `Network.enable` on Chrome tabs to intercept all HTTP/HTTPS
- Real-time rpcid extraction from batchexecute URLs and payloads
- Compare against known baselines — new rpcid = discovery event

**2. Heap Snapshot Diffing**
- Take V8 heap snapshot BEFORE an action
- Perform the action (click button, navigate)
- Take heap snapshot AFTER
- Diff the string tables — new strings matching rpcid pattern = discovered
- Can find rpcids triggered internally but never sent over the network

**3. Playwright UI Crawlers**
- Automated crawlers for NotebookLM (14 flows), Gemini (10 flows), AI Studio (15 flows)
- Drive every UI feature to trigger all endpoints
- Each flow: screenshot → action → capture traffic → diff heaps

**4. HAR File Mining**
- Batch processor for imported HAR captures
- Deduplicates by MD5 content hash
- Extracts all batchexecute + gRPC-web calls
- Saves first-seen payload examples per rpcid

**5. Bundle Analysis**
- Scan JS bundles for embedded proto field name→number mappings
- Pattern: `fieldNumber: N, name: 'field_name'`
- Feeds into proto reconstruction

### The Crawl Loop

```
For each target (NLM, Gemini, AI Studio):
  1. Start network monitor (CDP)
  2. Launch Playwright crawler
  3. For each UI flow:
     a. Heap snapshot BEFORE
     b. Perform action
     c. Drain captured traffic
     d. Heap snapshot AFTER
     e. Diff heaps → new rpcids
     f. Decode traffic (batchexecute + gRPC-web)
     g. Register discoveries in endpoint registry
     h. Store in Nexus knowledge base
  4. Probe feature flags (ozz5Z rpcid, IDs 300-1500)
  5. Rebuild .proto files from accumulated field data
  6. Generate diff report (pre-scan vs post-scan)
```

### Chat Traffic Capture Scripts

When Google's Gemini v2 migration broke the chat rpcids, we built a progression of increasingly sophisticated capture scripts:

**`argus_chat_capture.py`** — The quick-and-dirty version:
- Spawn Chrome with injected cookies
- Navigate to a notebook
- Inject a question into the textarea (Angular-safe: use native property setter + event dispatch)
- Capture 20 seconds of traffic
- Extract new rpcid + payload format

**`argus_live_chat.py`** — More robust, with Angular bypass:
```javascript
// Angular's change detection doesn't see programmatic value changes.
// Must use the native setter to trigger Angular's model binding:
Object.getOwnPropertyDescriptor(
  HTMLTextAreaElement.prototype, 'value'
).set.call(textarea, question);
textarea.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
```

**`argus_chat_probe.py`** — Production-grade with CLI args, structured JSON output, and response body capture. Designed for integration into the scheduler.

### Knowledge Distillation

ARGUS doesn't just capture — it distills discoveries into knowledge:

1. Build markdown document from endpoint registry (all rpcids, methods, coverage stats)
2. Upload to a persistent NotebookLM notebook as a source
3. Ask 40+ targeted questions about the API surface
4. Store all Q&A pairs in Nexus knowledge base under `category=argus`

This creates a searchable knowledge layer that agents can query: "What rpcid handles source deletion?" → instant answer from Nexus.

---

## Chapter 5: The Gemini v2 Migration Crisis

### What Happened (March 19-22, 2026)

Google merged NotebookLM + Sheets + Drive + AI Studio + Gemini + Docs into a unified "Gemini v2 Workspace" surface. This caused:

- **25 of 49 NLM rpcids stopped working** (rotated or removed)
- **Payload format changed** for surviving rpcids
- **f.sid became session-scoped** — headless browser profiles couldn't access notebook content
- **Source IDs became session-scoped** — IDs from one session were invalid in another

### What We Discovered

From HAR entry #68 of `notebooklm_knack112358-questions-asked.har`:
- Chat requests have NO rpcid in the URL — they go directly to the gRPC streaming endpoint
- Error `[16]` means source IDs are invalid/stale for the current session
- The `GenerateFreeFormStreamed` endpoint still works — only batchexecute rpcids rotated

### The Solution: CDP Auth Recovery

We built a unified auth recovery system (`cdp_auth_recovery.py`) that:

1. **DETECT** — Check if Chrome is running on port 9222
2. **INJECT** — Open a disposable tab, inject saved cookies via `Network.setCookie`
3. **NAVIGATE** — Go to NotebookLM, verify login (title check, no signin redirect)
4. **EXTRACT** — Pull session tokens from `WIZ_global_data` via `Runtime.evaluate`
5. **HARVEST** — Fresh cookies from the tab session
6. **SAVE** — Cookies to `nlm_cookies.json`, tokens to `nlm_meta.json`
7. **SYNC** — Push to GoogleAccountPool for ARGUS/crawler reuse
8. **VALIDATE** — Test each API key against Gemini embedding endpoint
9. **HARVEST KEYS** — If dead, intercept AI Studio network traffic for fresh keys
10. **UPDATE** — Write new keys to config

The key insight: use a **disposable Chrome tab** (opened fresh, closed after) so the user's actual browsing session is never disrupted.

### API Key Harvesting

When API keys die (Google rotates them), the recovery system:
- Navigates to `https://aistudio.google.com/app/apikey` via CDP
- Monitors network traffic for responses from `alkalimakersuite-pa.clients6.google.com`
- Regex extracts keys: `AIza[a-zA-Z0-9_\-]{35}`
- Tests each against the Gemini embedding endpoint
- Keeps only working keys

---

## Chapter 6: The Proxy Layer — Unifying Everything

### The Problem of Many Protocols

By this point we had access to:
- **NotebookLM** via batchexecute + gRPC streaming (cookies + CSRF)
- **Gemini** via batchexecute (cookies + SAPISIDHASH)
- **AI Studio** via gRPC-web (API key + SAPISIDHASH)
- **GitHub Copilot** via REST API (GitHub Bearer token, refreshed hourly)
- **LMStudio** via REST v1 API (optional Bearer token)
- **Google Colab** via gRPC (SAPISIDHASH)

Five different protocols, five different auth mechanisms. Agents shouldn't need to care about any of this.

### ask.py — The Unified CLI

One script to query any model:

```bash
ask.py "What is X?" --model claude-opus-4.6    # → GitHub Copilot (38 models)
ask.py "What is X?" --nlm                       # → NotebookLM (Gemini, grounded)
ask.py "What is X?" --local                     # → LMStudio (local inference)
ask.py --models --vendor anthropic              # → List available models
```

Routes to the right backend, handles auth, returns a clean answer. Model aliases: `opus`, `sonnet`, `haiku`, `gpt5`, `gpt`, `codex`, `gemini`, `flash`, `grok`.

### model_proxy.py — OpenAI-Compatible API Server

For tools that speak OpenAI protocol (Cursor, Continue, aider, etc.):

```
GET  http://localhost:5800/v1/models           → List all models
POST http://localhost:5800/v1/chat/completions  → Chat (streaming & non-streaming)
```

Takes OpenAI format in, routes to the right backend, returns OpenAI format out. Supports SSE streaming. Any tool that can talk to OpenAI can now talk to Claude, GPT-5, Gemini, Grok, or local models.

### nlm_ask.py — CDP Browser Fetch

The simplest and most reliable NLM integration. Attaches to a running Chrome tab with NotebookLM open, extracts session tokens, injects a `fetch()` call, and returns the answer:

```bash
python scripts/nlm_ask.py "What are the key findings?"
```

The browser handles all auth. We just inject the question and read the response. Handles Gemini thinking traces (skips `**Bold headers**`), extracts the final answer, 90-second timeout for complex queries.

### The NLM Hybrid Router

Two backends for NotebookLM, automatically routed:

- **batchexecute (direct HTTP)** — fast, good for source management, breaks when rpcids rotate
- **Node.js MCP Bridge (Patchright)** — slow but stable, handles real chat via browser automation

The hybrid router (`nlm_hybrid.py`) tries batchexecute first, falls back to Node bridge if it fails. Chat always goes to the Node bridge (batchexecute chat doesn't work).

---

## Chapter 7: The Chrome-Free Client — Faking Everything

### The Problem

The CDP browser injection approach (Chapter 3) works, but it requires Chrome to be running for every API call. For a production system that runs 24/7, you don't want to depend on a browser being open. The goal: make server-side HTTP calls that Google's servers can't distinguish from a real Chrome browser.

### What Needs Faking

Through months of HAR analysis and trial-and-error, we identified exactly which headers Google validates and which it ignores. The complete header set for a Chrome-free batchexecute client:

```python
headers = {
    # ── Standard HTTP ────────────────────────────────────────
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/145.0.0.0 Safari/537.36"),
    "Referer": "https://notebooklm.google.com/",
    "Origin": "https://notebooklm.google.com",

    # ── CORS compliance (required — request rejected without these) ──
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",

    # ── Chrome identity (faked — server validates these) ─────
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "x-browser-channel": "stable",
    "x-browser-year": "2026",

    # ── Anti-XSRF (required) ─────────────────────────────────
    "X-Same-Domain": "1",

    # ── Privacy (optional but looks more real) ───────────────
    "DNT": "1",

    # ── Auth (from cookies, NOT SAPISIDHASH) ─────────────────
    "Cookie": "SID=...; SSID=...; APISID=...; __Secure-3PSID=...; ...",
}
```

### What We Learned NOT to Send

**SAPISIDHASH — the biggest gotcha.** Other Google APIs (Maps, Docs, Colab, Sheets, Drive) require an `Authorization: SAPISIDHASH <timestamp>_<sha1>` header. We initially added it to NLM calls because every other Google API uses it. **It causes HTTP 400, error code 3.** NotebookLM batchexecute authenticates ONLY via Cookie + the `at` CSRF token in the POST body. This took days to figure out — the error response is opaque, and every instinct said "add more auth headers."

The HAR comparison that cracked it: we recorded a real Chrome session, exported the HAR, and diff'd our request headers against the browser's. The browser never sends `Authorization` to the batchexecute endpoint. That was the moment.

**Empty `at` token — causes 403.** If the CSRF token isn't available yet (first page load), you must **omit the `at` parameter entirely** from the POST body. Sending `at=` (empty string) triggers a 403 Forbidden. This is different from most CSRF implementations that accept empty tokens.

### Headers the Real Browser Sends That We Can't Easily Fake

The Chrome MCP capture (2026-03-23) revealed headers that only a real browser generates:

```
x-browser-validation: OsQr7VAWzRcWhg0pyQAkUi0ayRw=    ← cryptographic, changes per request
x-browser-copyright: Copyright 2026 Google LLC          ← static but Chrome-binary-embedded
x-client-data: CIe2yQEIpbbJAQipncoBCM7eygEI...         ← Chrome variation/experiment flags
x-goog-ext-353267353-jspb: [null,null,null,282611]       ← Google internal extension data
```

**We fake `x-browser-channel` and `x-browser-year`** — these are static strings that don't change per-request, and Google accepts our fakes. The `x-browser-validation` is cryptographic and per-request — we don't send it, and Google still accepts the request. This means it's likely used for telemetry/analytics, not auth enforcement.

**Bottom line:** The Chrome-free client works for all batchexecute operations. The only thing it can't do is `GenerateFreeFormStreamed` (gRPC chat) which requires the `x-browser-validation` header — for that, we use the Chrome MCP approach or the Node.js bridge.

### The f.req Payload Format

The POST body is URL-encoded with two parameters:

```
f.req=<url_encoded_triple_nested_json>&at=<csrf_token>
```

The `f.req` structure (this took MANY attempts to get right):

```python
# CORRECT (confirmed from HAR — triple-nested)
f_req = [[[rpc_id, args_json, None, "generic"]]]     # Three levels of nesting

# WRONG (causes HTTP 400)
f_req = [[rpc_id, args_json, None, "generic"]]        # Two levels — REJECTED
f_req = [rpc_id, args_json, None, "generic"]           # One level — REJECTED
```

The third element (`None`) and fourth element (`"generic"`) are required padding. We don't know what they mean, but omitting them causes rejection. Every HAR capture shows them.

For multi-RPC batching (up to ~10 calls per request):

```python
f_req = [[[rpc_id_1, args_1, None, "generic"],
          [rpc_id_2, args_2, None, "generic"],
          [rpc_id_3, args_3, None, "generic"]]]
```

### The URL Parameters

```
https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
    ?rpcids=VfAZjd;CYK0Xb         # semicolon-separated rpcid list
    &source-path=/notebook/<uuid>   # notebook context (critical!)
    &bl=boq_labs-tailwind-frontend_20260319.10_p0  # build label
    &f.sid=-6520081273601444256     # server session ID
    &hl=en                          # language
    &_reqid=357556                  # request counter
    &rt=c                           # response type: chunked wrb.fr
```

**`source-path` is critical.** Without the correct notebook UUID here, source-scoped RPCs (LIST_SOURCES, CREATE_NOTE, SAVE_NOTE, etc.) silently return null. For account-level RPCs (LIST_NOTEBOOKS, USER_QUOTA), use `source-path=/`.

### The GenerateFreeFormStreamed Payload (gRPC Chat)

This is the 9-element array for real conversational chat, confirmed from HAR entry #68 (March 2026 deployment):

```python
inner = [
    # [0] Source context — every source UUID triple-nested
    [[[source_id_1]], [[source_id_2]], [[source_id_3]], ...],

    # [1] The question text
    "What are the key findings?",

    # [2] Conversation history (previous turns)
    #     Format: [[prev_answer, null, 2], [prev_question, null, 1], ...]
    #     Empty list [] for first message
    [[previous_answer_text, None, 2],
     [previous_question_text, None, 1]],

    # [3] Response config
    [2, None, [1], [1]],    # tier=2 (Pro), include citations, include thinking

    # [4] Thread UUID (for conversation continuity)
    "thread-uuid-here",     # or None for new conversation

    # [5] Reserved (always None)
    None,

    # [6] Reserved (always None)
    None,

    # [7] Notebook UUID
    "c3165bf5-b1a1-40e8-8f1f-2008234987b3",

    # [8] Request type flag (always 1)
    1,
]

# Wrapped as: f.req=[null, json.dumps(inner)]
# Plus: &at={csrf_token} in POST body
```

### The Response Format (5-Layer Decode)

Every batchexecute response follows this structure:

```
Layer 1: XSSI prefix     )]}'              ← strip this first
Layer 2: Size hint        1053              ← byte count for next block
Layer 3: wrb.fr frame     [["wrb.fr", "rpcid", "<inner_json>", null, null, null, "generic"]]
Layer 4: Inner JSON       [[answer_id, "markdown with [citation_uuid] markers"]]
Layer 5: Citation UUIDs   Extract via regex: [a-f0-9]{8}-[a-f0-9]{4}-...-[a-f0-9]{12}
```

For streaming responses (GenerateFreeFormStreamed), each chunk contains the **FULL answer text so far** — not deltas. Use the last chunk's text as the complete answer.

### Source Object Encoding Gotchas

Different source types use different positions in the source object array — getting this wrong causes silent failures (empty source created, no error):

```python
# Regular URL → position [2] as a string
source_obj = [None, None, "https://example.com", None, None, None, None, None, None, None, 1]
#                         ↑ position 2

# YouTube URL → position [7] as a LIST (not a string!)
source_obj = [None, None, None, None, None, None, None, ["https://youtube.com/watch?v=xyz"], None, None, 1]
#                                                        ↑ position 7, wrapped in list

# Text source → position [1] as [title, content], position [3] = 3
source_obj = [None, ["Title", "Content..."], None, 3, None, None, None, None, None, None, 1]
#                   ↑ position 1                   ↑ format type 3 = text
```

Using position 2 for YouTube or position 7 for regular URLs creates an empty source with no error message. This took considerable debugging to discover.

---

## Chapter 8: The Chrome MCP Revolution

### What Changed Everything

On 2026-03-23, we discovered that Chrome DevTools has an **official MCP server** (`chrome-devtools-mcp`). This replaces the entire CDP WebSocket nightmare with clean, standard MCP tool calls.

### The Old Way (CDP WebSocket)

```python
# Async websockets library (NOT the sync websocket library — CORS blocks it)
async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=50*1024*1024) as ws:
    await ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
    while True:
        r = json.loads(await asyncio.wait_for(ws.recv(), 30))
        if r.get("id") == 1: break
    # ... fight with CORS, async, timeouts, port mismatches ...
```

Problems: CORS 403 errors with sync library, port confusion (9222 vs 9223), async-only, no response body access, custom event loop needed.

### The New Way (Chrome MCP)

```json
{
  "mcpServers": {
    "chrome": {
      "command": "npx",
      "args": ["chrome-devtools-mcp@latest", "--browserUrl", "http://127.0.0.1:9223", "--no-usage-statistics"]
    }
  }
}
```

Then just call MCP tools:

```
take_snapshot          → Full accessibility tree with element UIDs
fill(uid, value)       → Type into any input (Angular-safe)
click(uid)             → Click any button
evaluate_script(fn)    → Run JS in page context
list_network_requests  → All network traffic with filtering
get_network_request    → Full request/response with headers, cookies, body
take_screenshot        → Visual capture to disk
navigate_page          → Go to URL
press_key              → Keyboard input
```

### What the MCP Capture Revealed

In one `get_network_request` call on the NLM chat endpoint, we extracted:

1. **Full request headers** — including `x-browser-validation` (cryptographic, per-request), `x-client-data` (Chrome experiment flags), and `x-goog-ext-353267353-jspb` (Google internal extension data)
2. **Complete cookie string** — every Google auth cookie, fresh, with exact domain/path/expiry
3. **The exact f.req payload** — all 39 source UUIDs, the question, full conversation history
4. **Response headers** — including fresh `Set-Cookie` with rotated SIDCC tokens
5. **794KB response body** — saved to disk, the complete gRPC streaming response

All without a single line of WebSocket code.

### Two Methods, Two Use Cases

| Aspect | Chrome-Free Client | Chrome MCP |
|--------|-------------------|------------|
| **Requires Chrome** | No (only for auth refresh) | Yes (must be running) |
| **Auth source** | Cookies from disk (`nlm_cookies.json`) | Live browser session |
| **Speed** | Fast (~200ms per call) | Medium (~500ms, MCP overhead) |
| **batchexecute** | Full support | Full support |
| **GenerateFreeFormStreamed** | Works but missing `x-browser-validation` | Full support (browser sends it) |
| **Auth refresh** | CDP recovery or HAR import | Automatic (browser manages) |
| **Best for** | Production, scheduled tasks, batch ops | ARGUS discovery, live debugging, auth capture |
| **Setup** | Zero — just needs cookies on disk | `npx chrome-devtools-mcp` + Chrome |

**The production architecture uses BOTH:**
- Chrome-free client for all batchexecute operations (fast, no browser dependency)
- Chrome MCP or Node.js bridge for gRPC chat (needs browser headers)
- CDP auth recovery refreshes cookies periodically (every 15 minutes via scheduler)

---

## Chapter 9: Beyond NotebookLM — The WIZ Pattern

### The Shared Architecture

Through ARGUS discovery, we found that Google uses the exact same `batchexecute` protocol across multiple services. We call this the **WIZ pattern** (after the `WIZ_global_data` JavaScript object that contains session tokens):

| Service | Endpoint | Auth | Status |
|---------|----------|------|--------|
| **NotebookLM** | `notebooklm.google.com/_/LabsTailwindUi/data/batchexecute` | Cookie + `at` CSRF | Production |
| **Gemini** | `gemini.google.com/_/BardChatUi/data/batchexecute` | Cookie + `at` CSRF | Production |
| **Opal** | `opal.google.com/_/Opal/data/batchexecute` | Cookie + `at` CSRF | Experimental |
| **Colab** | `colab.clients6.google.com/...` | Cookie + SAPISIDHASH | Production |
| **Sheets/Drive** | `clients6.google.com/...` | Cookie + SAPISIDHASH | Production |

The key difference: NLM, Gemini, and Opal do NOT use SAPISIDHASH. Colab, Sheets, and Drive DO. This is a per-service decision by Google's auth team, not a protocol-level difference.

### Gemini Extended Client

Discovered 5 new rpcids from `gemini.google.com-NEWEST.har`:

| rpcid | Operation | Notes |
|-------|-----------|-------|
| `HcT8bb` | List Storybook Gems | Creative workspace |
| `XqA3Ic` | Get Storybook Detail | Individual gem content |
| `ZKcapf` | List Saved Info | Bookmarks/saved items |
| `jGArJ` | List My Content | /mystuff page |
| `sJBwce` | Get Subscription Tiers | Pro/Ultra plan details |

Gemini's gRPC streaming uses `BardFrontendService/StreamGenerate` instead of NLM's `LabsTailwindOrchestrationService/GenerateFreeFormStreamed`.

### Opal Client (Google Labs)

A new experimental creative workspace at `opal.google.com`. Uses the same WIZ batchexecute pattern. Shares credentials with NLM via `data/nlm_meta.json` — once you authenticate with NLM, Opal works automatically.

---

## Chapter 10: The ARGUS Intelligence Platform — Deep Internals

### Architecture

ARGUS isn't a single script — it's a multi-layer intelligence platform:

```
Orchestrator (scripts/argus/orchestrator.py)
    ├── NetworkMonitor — CDP-based traffic capture (all tabs)
    ├── NLMCrawler — 13 UI flows for NotebookLM
    ├── GeminiCrawler — 10 UI flows for Gemini
    ├── AIStudioCrawler — 15 UI flows for AI Studio
    ├── BatchExecuteDecoder — f.req/wrb.fr parsing
    ├── GrpcWebDecoder — Binary proto + JSON frame parsing
    ├── HeapDiffer — V8 heap snapshot string table diffing
    ├── FeatureFlagProber — ID range scanning (300-1500)
    ├── ProtoReconstructor — Build .proto files from wire data
    ├── EndpointRegistry — Versioned discovery storage
    ├── ApiDocGenerator — Auto-generate API reference docs
    └── NexusSink — Store discoveries in Nexus knowledge base
```

### Endpoint Registry

The registry (`data/argus/registry.json`) is a versioned, diffable store of all discovered API endpoints:

```json
{
  "schema": "2.0",
  "nlm_rpcids": {"AUrzMb": {"name": "Analytics", "seen": 3, "last": "2026-03-23"}},
  "gemini_rpcids": {...},
  "aistudio_methods": {...},
  "nlm_grpc_methods": {...},
  "heap_discovered": {...},
  "unknown_endpoints": {...},
  "runs": [{"ts": "2026-03-23", "new_rpcids": ["AUrzMb"], "duration_s": 529.7}]
}
```

The baseline is YAML-driven (`config/nlm_rpcids.yaml`), not hardcoded. When Google rotates rpcids, update the YAML and the entire SDK, transport layer, and ARGUS baseline update automatically.

### The Crawler Flows

Each crawler systematically exercises every UI feature to trigger all possible API calls:

**NLM Crawler (13 flows):**
1. List notebooks → `ub2Bae`
2. Open notebook → `rLM1Ne`, `wXbhsf`, `e3bVqc`, `gArtLc`, `hPTbtc`, `sqTeoe`
3. Send chat → `GenerateFreeFormStreamed`
4. Get history → `GzgSEd`
5. Generate study guide → `xqEXEf`
6. Generate FAQ → `xqEXEf` (variant payload)
7. Generate briefing → `xqEXEf` (variant payload)
8. Audio overview → `sqTeoe`
9. Notebook analysis → `VfAZjd`
10. Add text source → `izAoDd`
11. List sources → `wXbhsf`
12. Feature flags → `ozz5Z`
13. Create/delete notebook → `CCqFvf`, `WWINqb`

### Protocol Monitor JSON Importer

Chrome DevTools has a Protocol Monitor (Settings > Experiments > Protocol Monitor) that captures all CDP messages. The Save button exports them as JSON. We built an importer (`scripts/argus/importers/protocol_monitor.py`) that:

1. Parses the exported JSON (array of CDP messages)
2. Extracts `Network.requestWillBeSent` events
3. Filters for `LabsTailwind` / `batchexecute` URLs
4. Decodes `f.req` payloads (URL-encoded → JSON → rpcid + args)
5. Extracts cookies, session tokens, gRPC method names
6. Merges discoveries into the ARGUS endpoint registry

The HAR watchfolder (`scripts/har_watchfolder.py`) auto-detects `.json` files alongside `.har` files and routes them through this importer.

---

## Chapter 11: The HAR Watchfolder — Closing the Auth Loop

### The Auth Lifecycle

Google session cookies expire. API keys rotate. Build labels change weekly. The system needs fresh credentials continuously.

**`har_watchfolder.py`** is the background daemon that closes this loop:

```
Drop HAR file into data/hars/
  ↓
Watchfolder detects new file (polls every 30s)
  ↓
Extracts Google session cookies
  ↓
Updates GoogleAccountPool
  ↓
Probes NLM + Colab to verify auth works
  ↓
Moves HAR to imported/ (or failed/)
  ↓
Logs event to Nexus for audit trail
```

Commands:
```bash
python scripts/har_watchfolder.py watch              # Start polling daemon
python scripts/har_watchfolder.py import file.har     # Import single file
python scripts/har_watchfolder.py health              # Probe all accounts
python scripts/har_watchfolder.py status              # Show cookie ages
```

Combined with the CDP auth recovery (runs every 15 minutes via scheduler), the system maintains fresh credentials automatically. Drop a HAR file, and within 30 seconds every service has fresh auth.

---

## Chapter 12: What We Learned

### Protocol Discoveries

1. **batchexecute** is Google's universal internal RPC framework — same wire format across Docs, Sheets, Drive, Gemini, NotebookLM, Apps Script, Opal. Learn it once, access everything. We call this the **WIZ pattern**.

2. **SAPISIDHASH** is per-service — NotebookLM, Gemini, and Opal don't use it (cookies + CSRF only). Colab, Sheets, and Drive DO use it. Adding it where it's not expected causes 400 errors. This per-service auth decision took days to discover.

3. **Build labels expire silently** — no error, just empty responses. This is the #1 cause of "everything was working yesterday" failures. No HTTP error code, no 401 — just null data in a 200 response.

4. **Real chat uses gRPC streaming**, not batchexecute. The `GenerateFreeFormStreamed` endpoint returns progressive full text, not deltas. The rpcid for chat rotated from `tJHFsf` to `Bgzyjc` during the Gemini v2 migration (confirmed 2026-03-23).

5. **Source IDs and session IDs are scoped** — after the Gemini v2 migration, IDs from one session don't work in another. You need fresh session context.

6. **Angular textarea injection** requires the native property setter — `element.value = x` doesn't trigger Angular's change detection. Must use `Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(element, x)` followed by `InputEvent` dispatch.

7. **f.req MUST be triple-nested** — `[[[rpc, args, null, "generic"]]]` with three levels. Two levels causes 400. This took many failed attempts to get right.

8. **Empty `at=` causes 403** — unlike most CSRF implementations, NLM rejects blank tokens. Omit the parameter entirely if you don't have it.

9. **Chrome's `x-browser-*` headers CAN be faked** — `x-browser-channel: stable` and `x-browser-year: 2026` are static strings that Google accepts from server-side HTTP calls. The `x-browser-validation` header is cryptographic and per-request, but Google doesn't enforce it for batchexecute. It IS checked for some gRPC endpoints.

10. **Source object positions vary by type and are undocumented** — regular URLs go at position [2], YouTube at position [7] as a list, text at position [1] as [title, content]. Wrong position = silent empty source, no error.

### Architecture Discoveries

11. **Two-method architecture is optimal** — Chrome-free HTTP client for fast production batchexecute calls (no browser needed), Chrome MCP for gRPC chat and ARGUS discovery (needs browser). CDP auth recovery refreshes cookies for both.

12. **Chrome DevTools MCP server** (`chrome-devtools-mcp`) replaces all raw CDP WebSocket code. One `get_network_request` call extracts headers, cookies, full request/response body — everything we spent hours fighting CDP for.

13. **Dual-backend redundancy** is essential — when batchexecute rpcids rotate, the Node.js browser bridge keeps working. When the bridge is slow, batchexecute handles source management.

14. **Heap snapshot diffing** finds APIs that network capture misses — some rpcids are triggered internally but never sent over the wire. V8 heap analysis catches them.

15. **Knowledge distillation compounds** — feeding ARGUS discoveries into NotebookLM, then extracting Q&A pairs into Nexus, creates a searchable knowledge layer that gets richer with every scan.

16. **Local agents need APIs** — the system is designed so local LMStudio models (Qwen, Gemma, etc.) can call the NotebookLM SDK, ARGUS, and all integrations via the Flask proxy and MCP skills. The system builds itself from the inside.

### Operational Discoveries

17. **Google deploys weekly** — build labels, rpcids, and sometimes payload formats change. Automated discovery isn't optional, it's mandatory for production stability.

18. **API keys rotate unpredictably** — the CDP recovery system that harvests fresh keys from AI Studio is the only reliable way to maintain access.

19. **HAR files are gold** — a single HAR capture contains everything: cookies, session tokens, build labels, rpcid→payload mappings, response formats. The watchfolder automation makes this a one-drop operation.

20. **Protocol Monitor JSON exports** are the new HAR — drop a `.json` export from Chrome DevTools Protocol Monitor into `data/hars/` and the watchfolder auto-imports rpcids + payloads + cookies into the ARGUS registry.

---

## Appendix: The Scripts

| Script | Purpose | Key Technique |
|--------|---------|---------------|
| `nlm_debug_chunks.py` | Debug NLM streaming response structure | CDP injection, wrb.fr parsing |
| `cdp_live_probe.py` | Proof-of-concept: browser-side fetch works | CDP Runtime.evaluate, session extraction |
| `argus_live_chat.py` | Quick chat traffic capture | Chrome spawn, cookie injection, Angular bypass |
| `argus_chat_capture.py` | Detailed capture after rpcid rotation | Two-stage cookie injection, DOM detection |
| `argus_chat_probe.py` | Production chat probe with CLI + JSON output | CDPSession class, response body retrieval |
| `argus_grpc_discovery.py` | CDP-based gRPC method discovery | Tab navigation, button clicking, traffic capture |
| `argus_deep_crawl.py` | Systematic UI crawl + direct RPC verification | All buttons + direct fetch tests |
| `har_payload_analyzer.py` | Deep HAR mining for rpcids and payloads | Multi-endpoint extraction, override detection |
| `analyze_gemini_deep.py` | Gemini rpcid and service path analysis | batchexecute decode, gRPC path extraction |
| `analyze_gemini_deep2.py` | Gemini model list and thinking signatures | Response structure analysis |
| `har_watchfolder.py` | Background auto-import for HAR + Protocol Monitor JSON | Polling, health probes, Nexus audit |
| `nlm_ask.py` | Simple NLM query via CDP browser fetch | Tab attach, fetch injection, thinking skip |
| `ask.py` | Unified CLI for all frontier models | Multi-backend routing (Copilot/NLM/LMStudio) |
| `model_proxy.py` | OpenAI-compatible API server | Protocol translation, SSE streaming |
| `oracle.py` | System diagnostics and observability | Error aggregation, health grid, trace waterfall |

**ARGUS Platform** (`scripts/argus/`):

| Module | Purpose |
|--------|---------|
| `orchestrator.py` | Master controller — runs all phases sequentially |
| `crawlers/nlm_crawler.py` | 13 NLM UI flows (list/open/chat/generate/source/flags) |
| `crawlers/gemini_crawler.py` | 10 Gemini UI flows |
| `crawlers/aistudio_crawler.py` | 15 AI Studio UI flows |
| `decoders/batchexecute.py` | f.req/wrb.fr parsing and payload extraction |
| `decoders/grpc_web.py` | Binary proto + JSON gRPC-web frame parsing |
| `decoders/heap_diffing.py` | V8 heap snapshot string table diffing |
| `discovery/endpoint_registry.py` | Versioned discovery storage with baseline diffs |
| `discovery/feature_flag_probe.py` | NLM feature flag ID scanning (300-1500) |
| `discovery/proto_reconstructor.py` | Build .proto files from captured wire data |
| `discovery/rpcid_detector.py` | Pattern detection for new rpcids |
| `network_monitor.py` | Real-time CDP network traffic capture |
| `cdp_bridge.py` | CDP WebSocket connection management |
| `importers/protocol_monitor.py` | Chrome Protocol Monitor JSON import |
| `reporting/api_doc_generator.py` | Auto-generate API reference docs from registry |
| `nexus_sink.py` | Store discoveries in Nexus knowledge base |

---

## Appendix: The RPC Catalog (as of 2026-03-23)

### NotebookLM batchexecute (42 rpcids mapped, 18 confirmed live)

**Notebook Management:**
`ub2Bae` ListNotebooks · `CCqFvf` CreateNotebook/ResumeSession · `mFtdI` GetNotebook · `e3bVqc` NotebookInfo · `s0tc2d` RenameNotebook · `WWINqb` DeleteNotebook · `dI5Y8` ShareNotebook · `jzEKsc` GetSharedNotebook

**Source Management:**
`izAoDd` AddSource · `tGMBJ` DeleteSource · `wXbhsf` ListSources · `tr032e` ReadSource · `hizoJc` SourceDetail · `o4cbdc` RegisterFiles · `K4YCPe` SourceMetadata · `jtGGne` SourcesAdvanced · `bfEAsb` ProcessSource

**Q&A & Chat:**
`CYK0Xb` CreateNote (Q&A with citations) · `Bgzyjc` GenerateFreeFormStreamed (real chat — **rotated from `tJHFsf`**)

**Notes & Artifacts:**
`cYAfTb` SaveNote · `R7cb6c` SaveReport · `gArtLc` ListArtifacts

**Document Generation:**
`VfAZjd` AISummary · `ciyUvf` GenerateDoc · `xqEXEf` GenerateGuide · `yyryJe` GenerateMindMap

**Audio:**
`sqTeoe` ListAudioTypes

**Research:**
`Ljjv0c` FastResearch · `QA9ei` DeepResearch · `LBwxtb` AddResearchSource

**Threads & History:**
`hPTbtc` GetThreadIds · `khqZz` ReadThread · `GzgSEd` GetChatHistory · `GfmCOc` DeleteChatHistory · `cFji9` SyncNotes/MindMap

**User & Account:**
`JFMDGd` UserProfile · `ozz5Z` FeatureFlags/AccountState · `ZwVcOc` UserPlan/SessionInit · `DYBcR` GetLocale · `AUrzMb` Analytics (**discovered 2026-03-23**)

**Export:**
`Krh3pd` ExportToSheets

### NotebookLM gRPC (25 methods via LabsTailwindOrchestrationService)

**Implemented:**
`GenerateFreeFormStreamed` (real chat — streaming, progressive full text)

**Discovered (heap analysis + ARGUS crawl):**
`CreateArtifact` · `DeriveArtifact` · `GenerateArtifact` · `GetArtifactUserState` · `UpsertArtifactUserState` · `CheckSourceFreshness` · `DiscoverSourcesAsync` · `DiscoverSourcesManifold` · `CancelDiscoverSourcesJob` · `FinishDiscoverSourcesRun` · `MutateSource` · `RefreshSource` · `DeleteSources` · `MutateProject` · `DeleteProjects` · `ListFeaturedProjects` · `UpdateFeaturedNotebookStatus` · `DeleteChatTurns` · `ListChatSessions` · `MutateNote` · `GetOrCreateAccount` · `ReportContent` · `GeneratePromptSuggestions` · `GenerateReportSuggestions`

### Gemini batchexecute (41 rpcids)

**Core:** `otAQ7b` GenerateContent · `aPya6c` SessionInit · `ESY5D` GetHistory · `L5adhe` DraftInit · `PCck7e` ShareConversation · `NXpLKc` GetLinkedNotebooks · `ku4Jyf` CodeExecution

**New (2026-03-23):** `HcT8bb` ListStorybookGems · `XqA3Ic` GetStorybookDetail · `ZKcapf` ListSavedInfo · `jGArJ` ListMyContent · `sJBwce` GetSubscriptionTiers

### AI Studio gRPC (150+ methods, growing)

Services: `MakerSuiteService` · `MakersuiteAppletControlService`
Key methods: `GenerateContent` · `StreamGenerateContent` · `CreatePrompt` · `GetModel` · `ListModels`

### Opal (Google Labs — experimental)

Endpoint: `opal.google.com/_/Opal/data/batchexecute`
Key rpcid: `ug7pge` OpalGeminiInit
Auth: Same Cookie + `at` CSRF as NLM

---

## Appendix: Authentication Quick Reference

| Service | Auth Method | SAPISIDHASH? | Tokens Needed |
|---------|------------|:---:|---------------|
| NotebookLM (batchexecute) | Cookies + CSRF | **NO** | SID, SSID, APISID, __Secure-3PSID + `at` + `bl` + `f.sid` |
| NotebookLM (gRPC chat) | Cookies + CSRF + browser headers | **NO** | Same + `x-browser-validation` (via Chrome MCP or faked) |
| Gemini | Cookies + CSRF | **NO** | Same as NLM (different `bl` and `f.sid`) |
| Opal | Cookies + CSRF | **NO** | Same as NLM (shared `nlm_meta.json`) |
| AI Studio | API Key or SAPISIDHASH | **YES** | `AIza...` key or cookie-based |
| GitHub Copilot | GitHub Bearer token | N/A | GitHub cookies → `/chat/token` → 1hr Bearer |
| Google Colab | Cookies + SAPISIDHASH | **YES** | Same cookies + `SHA1(ts + SAPISID + origin)` |
| Google Sheets/Drive | Cookies + SAPISIDHASH | **YES** | Same cookies + SHA1 hash |
| LMStudio | Optional Bearer | N/A | Config-driven (`lmstudio.api_token`), local only |

### SAPISIDHASH Computation (for services that need it)

```python
import hashlib, time
ts = str(int(time.time()))
raw = f"{ts} {cookies['SAPISID']} {origin_url}"
hash_value = hashlib.sha1(raw.encode()).hexdigest()
header = f"SAPISIDHASH {ts}_{hash_value}"
# Add as: Authorization: SAPISIDHASH <timestamp>_<hash>
```

**Services that use it:** Colab, Sheets, Drive, AI Studio
**Services that REJECT it:** NotebookLM, Gemini, Opal (causes HTTP 400)

---

## Appendix: The Two-Method Architecture

CosySim uses both a Chrome-free HTTP client and Chrome MCP, each for what they do best:

```
┌─────────────────────────────────────────────────┐
│  Chrome-Free HTTP Client (nlm_transport.py)     │
│  ├── All batchexecute RPCs (42 operations)      │
│  ├── Faked headers (x-browser-*, sec-ch-*, etc) │
│  ├── Cookie auth from disk (nlm_cookies.json)   │
│  ├── No browser needed at runtime               │
│  └── Used by: SDK, agents, scheduled tasks      │
├─────────────────────────────────────────────────┤
│  Chrome MCP (chrome-devtools-mcp)               │
│  ├── GenerateFreeFormStreamed (gRPC chat)        │
│  ├── ARGUS discovery crawls                     │
│  ├── Network traffic capture + analysis         │
│  ├── Auth refresh (cookie + token extraction)    │
│  └── Used by: ARGUS, live debugging, chat       │
├─────────────────────────────────────────────────┤
│  CDP Auth Recovery (cdp_auth_recovery.py)       │
│  ├── Refreshes cookies for both methods         │
│  ├── Harvests API keys from AI Studio           │
│  ├── Runs every 15 minutes via scheduler        │
│  └── Syncs to GoogleAccountPool for all clients │
└─────────────────────────────────────────────────┘
```

Local agents (LMStudio models) access everything through the Flask proxy API and MCP skills — they don't need to know which method is used internally.

---

*This document is a living record. As Google continues to evolve their internal APIs, ARGUS continues to discover, and this journal continues to grow. v2.0 — 2026-03-23.*
