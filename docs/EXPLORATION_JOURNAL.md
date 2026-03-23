# Exploration Journal — Reverse-Engineering Google's Internal APIs

**A technical narrative of how CosySim learned to talk to NotebookLM, Gemini, AI Studio, GitHub Copilot, and Google Workspace — without a single official API.**

Version: v1.0 [2026-03-23]
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

## Chapter 7: The HAR Watchfolder — Closing the Loop

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

## Chapter 8: What We Learned

### Protocol Discoveries

1. **batchexecute** is Google's universal internal RPC framework — same wire format across Docs, Sheets, Drive, Gemini, NotebookLM, Apps Script. Learn it once, access everything.

2. **SAPISIDHASH** is per-service — NotebookLM batchexecute doesn't use it (cookies + CSRF only), but Colab, Sheets, and Drive do. Adding it where it's not expected causes 400 errors.

3. **Build labels expire silently** — no error, just empty responses. This is the #1 cause of "everything was working yesterday" failures.

4. **Real chat uses gRPC streaming**, not batchexecute. The `GenerateFreeFormStreamed` endpoint returns progressive full text, not deltas.

5. **Source IDs and session IDs are scoped** — after the Gemini v2 migration, IDs from one session don't work in another. You need fresh session context.

6. **Angular textarea injection** requires the native property setter — `element.value = x` doesn't trigger Angular's change detection. Must use `Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(element, x)` followed by `InputEvent` dispatch.

### Architecture Discoveries

7. **CDP browser injection** is more reliable than direct HTTP — the browser handles all anti-automation headers, cookie scoping, and CORS. Let the browser do the auth.

8. **Dual-backend redundancy** is essential — when batchexecute rpcids rotate, the Node.js browser bridge keeps working. When the browser bridge is slow, batchexecute handles source management.

9. **Heap snapshot diffing** finds APIs that network capture misses — some rpcids are triggered internally but never sent over the wire. V8 heap analysis catches them.

10. **Knowledge distillation** compounds — feeding ARGUS discoveries into NotebookLM, then extracting Q&A pairs into Nexus, creates a searchable knowledge layer that gets richer with every scan.

### Operational Discoveries

11. **Google deploys weekly** — build labels, rpcids, and sometimes payload formats change. Automated discovery isn't optional, it's mandatory for production stability.

12. **API keys rotate unpredictably** — the CDP recovery system that harvests fresh keys from AI Studio is the only reliable way to maintain access.

13. **HAR files are gold** — a single HAR capture contains everything: cookies, session tokens, build labels, rpcid→payload mappings, response formats. The watchfolder automation makes this a one-drop operation.

---

## Appendix: The Scripts

| Script | Purpose | Key Technique |
|--------|---------|---------------|
| `nlm_debug_chunks.py` | Debug NLM streaming response structure | CDP injection, wrb.fr parsing |
| `cdp_live_probe.py` | Proof-of-concept: browser-side fetch works | CDP Runtime.evaluate, session extraction |
| `argus_live_chat.py` | Quick chat traffic capture | Chrome spawn, cookie injection, Angular bypass |
| `argus_chat_capture.py` | Detailed capture after rpcid rotation | Two-stage cookie injection, DOM detection |
| `argus_chat_probe.py` | Production chat probe with CLI + JSON output | CDPSession class, response body retrieval |
| `har_payload_analyzer.py` | Deep HAR mining for rpcids and payloads | Multi-endpoint extraction, override detection |
| `analyze_gemini_deep.py` | Gemini rpcid and service path analysis | batchexecute decode, gRPC path extraction |
| `analyze_gemini_deep2.py` | Gemini model list and thinking signatures | Response structure analysis |
| `har_watchfolder.py` | Background auto-import daemon for HAR files | Polling, health probes, Nexus audit |
| `nlm_ask.py` | Simple NLM query via CDP browser fetch | Tab attach, fetch injection, thinking skip |
| `ask.py` | Unified CLI for all frontier models | Multi-backend routing (Copilot/NLM/LMStudio) |
| `model_proxy.py` | OpenAI-compatible API server | Protocol translation, SSE streaming |
| `oracle.py` | System diagnostics and observability | Error aggregation, health grid, trace waterfall |

---

## Appendix: The RPC Catalog (as of 2026-03-22)

### NotebookLM batchexecute (49 rpcids, 67% observed)

**Notebook Management:**
`wIlBFe`/`ub2Bae` ListNotebooks · `bv7rAb` CreateNotebook · `mFtdI` GetNotebook · `sM6gLf` UpdateNotebook · `kVoZqc` DeleteNotebook · `s0tc2d` RenameNotebook

**Source Management:**
`PoHVkb`/`izAoDd` AddSource · `VSSXud`/`tGMBJ` DeleteSource · `wXbhsf` ListSources · `tr032e` GetSourceSummary

**Q&A & Chat:**
`CYK0Xb` CreateNote (Q&A with citations) · `tJHFsf` SendChatMessage · `VfAZjd` AISummary · `xqEXEf` GenerateGuide

**Audio & Artifacts:**
`sqTeoe` GetAudioOverview · `gArtLc` GetArtifacts · `ciyUvf` GenerateDoc · `R7cb6c` SaveReport

**System:**
`ozz5Z` GetFeatureFlags · `JFMDGd` UserProfile · `CCqFvf` ResumeSession

### NotebookLM gRPC (24 methods)

`GenerateFreeFormStreamed` · `CreateArtifact` · `DeriveArtifact` · `GenerateArtifact` · `MutateSource` · `RefreshSource` · `DeleteSources` · `CheckSourceFreshness` · `DiscoverSourcesAsync` · `MutateProject` · `DeleteProjects` · `ListFeaturedProjects` · `DeleteChatTurns` · `ListChatSessions` · `GetOrCreateAccount` · `ReportContent` · `GeneratePromptSuggestions` · `GenerateReportSuggestions`

### Gemini batchexecute (36 rpcids, 47% observed)

`otAQ7b` GenerateContent · `aPya6c` SessionInit · `ESY5D` GetHistory · `L5adhe` DraftInit · `PCck7e` ShareConversation · `NXpLKc` GetLinkedNotebooks · `ku4Jyf` CodeExecution

### AI Studio gRPC (150+ methods, growing)

Services: `MakerSuiteService` · `MakersuiteAppletControlService`
Key methods: `GenerateContent` · `StreamGenerateContent` · `CreatePrompt` · `GetModel` · `ListModels`

---

## Appendix: Authentication Quick Reference

| Service | Auth Method | Tokens Needed |
|---------|------------|---------------|
| NotebookLM (batchexecute) | Cookies + CSRF | SID, SSID, APISID, __Secure-3PSID + `at` token + `bl` build label + `f.sid` |
| NotebookLM (gRPC) | Browser fetch (CDP) | Cookies via `credentials: 'include'` |
| Gemini | Cookies + SAPISIDHASH | Same cookies + `SHA1(ts + SAPISID + origin)` |
| AI Studio | API Key or SAPISIDHASH | `AIza...` key or cookie-based |
| GitHub Copilot | GitHub Bearer token | GitHub cookies → `/chat/token` → 1hr Bearer |
| Google Colab | SAPISIDHASH | Same cookies + SHA1 hash |
| Google Sheets/Drive | SAPISIDHASH | Same cookies + SHA1 hash |
| LMStudio | Optional Bearer | Config-driven, local only |

---

*This document is a living record. As Google continues to evolve their internal APIs, ARGUS continues to discover, and this journal continues to grow.*
