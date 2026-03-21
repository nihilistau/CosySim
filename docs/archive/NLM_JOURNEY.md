# NLM Reverse Engineering Journey
## From Black Box to Complete API: How We Unlocked NotebookLM

> **Status:** Complete. 61 service methods mapped, 24 rpcids decoded, WebRTC discovered.  
> **Updated:** March 2026 | **Author:** CosySim Research

---

## Chapter 1: Why We Did This

CosySim's Nexus knowledge system needed more than a database. It needed a **thinking partner** — a system that could ingest raw sources, reason over them, distill knowledge, and return precise answers to deliberate questions. NotebookLM (NLM) is exactly that system, running on Gemini 2.5/3.0 with no per-query cost (free tier: 50 queries/day, unlimited with multiple accounts).

The only problem: there is no official API.

So we built one.

---

## Chapter 2: First Contact — HAR Analysis

The first breakthrough came from simply recording network traffic. Chrome DevTools' HAR export captured every HTTP request made by the NLM web app. The key discovery: NLM uses Google's **batchexecute** system — an internal RPC framework where every API call is a POST to:

```
https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
?rpcids=rLM1Ne&source-path=/notebook/UUID&bl=build_label&f.sid=FSID
```

The request body is a URL-encoded JSON envelope:
```
f.req=[[["{rpcid}","{proto_json}",null,"generic"]]]
```

The response is a chunked stream with a security prefix:
```
)]}'\n
152\n
[["wrb.fr","{rpcid}","{response_json}",null,null,null,"generic"],["di",...]
```

### 35 rpcids Recovered

From 5 HAR files (including two full login sessions), we identified 35 unique rpcid strings and correlated each one with its behavior by examining request payloads and response shapes:

| rpcid | Method | What It Does |
|-------|--------|-------------|
| `rLM1Ne` | WatchNotebook | Server-sent events stream (153 calls — the heartbeat) |
| `gArtLc` | ListArtifacts | Get all artifacts (audio, video, study guides, FAQs) |
| `R7cb6c` | CreateConversationTurn | **The main chat API** — send a message, get AI response |
| `GenerateFreeFormStreamed` | `yyryJe` | Streaming generation mode |
| `sqTeoe` | GetAudioOverviewOptions | Returns available audio formats (Deep Dive, Brief) |
| `VfAZjd` | GetNotebookAnalysis | Returns AI-generated source summary |

*(Full table in NLM_API_REFERENCE.md)*

The HAR analysis gave us the **what** (which endpoints exist and what they do). But it couldn't tell us what **other** endpoints existed that we hadn't triggered during recording.

---

## Chapter 3: The V8 Heap — A Different Kind of Mining

Chrome is a V8 JavaScript runtime. Every string that was ever assigned to a variable, every compiled function stub, every cached response — it all lives in the V8 heap. Chrome DevTools can snapshot this heap as a `.heapsnapshot` file.

The key insight: **Angular gRPC stubs store the service method path string as a property**. This means if NLM ever loaded a gRPC service descriptor in this browser session, the string `/LabsTailwindOrchestrationService.GenerateMagicView` will be sitting in the heap.

### The Parser

We built `scripts/heap_deep_parser.py` — a binary heap snapshot parser that handles the V8 format:
- Node types: string, object, array, regexp, number, native, code, closure, etc.
- Edge types: element, property, context, internal, hidden, shortcut
- Parses the node/edge arrays in `.heapsnapshot` format
- For `.heaptimeline` files: processes all snapshots in the timeline

Performance on 306MB timeline: **38 seconds** to extract 406,585 unique strings.

### The Critical Setting: "Record Additional Information"

The first 5 heaps we captured yielded ~1,185 API function entries. The parser completed but the output was thin.

Then we enabled Chrome DevTools → Memory → "Record additional information to support heap snapshot details" and captured `Heap-20260305T041326.heaptimeline`.

The difference: **17,810 API function entries** vs 1,185. This setting causes Chrome to preserve compiled code objects in the heap instead of discarding them after JIT compilation. The compiled Angular gRPC stub functions are now in the heap — and their `servicePathString` properties come with them.

---

## Chapter 4: The Mother Lode

Running the parser on the 306MB full-functions heap yielded:

```
Parsing: Heap-20260305T041326.heaptimeline (306 MB)
  Nodes: 2,109,847  Edges: 5,891,234
  Strings extracted: 406,585
  API functions found: 17,810
  Credential findings: 3,977
  Parse time: 38.1 seconds
```

### 61 Proto Service Methods

Searching `strings_all.txt` for `LabsTailwindOrchestrationService`:

```
/LabsTailwindOrchestrationService.ActOnSources
/LabsTailwindOrchestrationService.AddSources
/LabsTailwindOrchestrationService.AddTentativeSources
...
```

**58 methods** in `LabsTailwindOrchestrationService` — versus the 35 rpcids we had from HAR analysis. There are ~20+ methods we had never triggered, sitting dormant in the app:

- `DiscoverSources` / `DiscoverSourcesAsync` / `DiscoverSourcesManifold` — NLM can **auto-discover** web sources
- `ExecuteWritingFunction` — AI-powered document editing  
- `GenerateMagicView` / `GetMagicView` / `GetMagicIndex` — a "Magic View" feature (AI visualization?)
- `ListModelOptions` — NLM can switch between AI models
- `ExportToDrive` — export artifacts to Google Drive
- `MutateProject` / `MutateNote` / `MutateAccount` / `MutateSource` — full proto Mutate CRUD API
- `GenerateReportSuggestions` — AI report scaffolding
- `CheckSourceFreshness` — URL source freshness verification
- `GetOrCreateAccount` — account initialization
- **WebRTC:** `GetIceConfig` + `SendSdpOffer` — the audio overview uses P2P WebRTC

Plus 3 methods in a separate **`LabsTailwindSharingService`**:
- `CreateAccessRequest`, `GetProjectDetails`, `ShareProject`

### The Angular Module Decode

In the DR4Ugf module (downloaded from gstatic CDN), we found the Closure Compiler pattern that assigns rpcids to gRPC stub classes:

```javascript
new _.Kz("Of0kDd", class extends _.r { constructor(a){super(a)} },
    [_.Dz, !0, _.Fz, "/LabsTailwindOrchestrationService.GetIceConfig"])

new _.Kz("eyWvXc", class extends _.r { constructor(a){super(a)} },
    [_.Dz, !0, _.Fz, "/LabsTailwindOrchestrationService.SendSdpOffer"])
```

This is the Kz pattern: `new _.Kz("RPCID", stubClass, [flags, ..., "/Service.Method"])`.

**Confirmed:** `Of0kDd` → `GetIceConfig`, `eyWvXc` → `SendSdpOffer`.

### Proto Enums

The heap also gave us all the proto enum values:

```
ARTIFACT_STATUS_SUGGESTED, ARTIFACT_STATUS_SAVED
SOURCE_TYPE_DRIVE, SOURCE_TYPE_UPLOAD, SOURCE_TYPE_URL, SOURCE_TYPE_TEXT, SOURCE_TYPE_YOUTUBE
STUDY_GUIDE, FAQ, BRIEFING_DOC, TIMELINE, TABLE_OF_CONTENTS, NOTE, AUDIO_OVERVIEW, VIDEO_OVERVIEW
Video styles: anime, autoselect, classic, custom, heritage, kawaii, papercraft, retroprint, watercolor, whiteboard
```

---

## Chapter 5: Authentication Archaeology

The heap revealed the complete authentication picture:

**API Key (embedded in app):** `AIzaSyC_pzrI0AjEDXDYcg7kkq3uQEjnXV50pBM`  
**OAuth Client ID:** `371316423795-luo3ln0198apr966qa7dkrmrsj30vrja.apps.googleusercontent.com`

But NLM doesn't use the API key for batchexecute calls. It uses **Cookie-based session auth**:

```
Cookie: SAPISID=...; SID=...; APISID=...; HSID=...; SSID=...
         NID=...; SIDCC=...; __Secure-1PSID=...; __Secure-1PAPISID=...
         __Secure-3PSID=...; __Secure-3PAPISID=...; SOCS=...
```

The `at` parameter in batchexecute URLs is a request-level CSRF token derived from SAPISID:
```
at=AIXQIkZu-fVpDiJYbK2rijLdgCOg:1772641571670
    └── base64(SAPISID hash) : unix_timestamp_ms
```

The `HPKE` (Hybrid Public Key Encryption) scheme found in the heap is used for `x-browser-validation` headers — browser attestation for bot detection, using P256-HKDF-SHA256/AES-128-GCM.

**Our cookie refresh system** (`scripts/har_capture.py`) extracts fresh cookies from a running Chrome session via the Chrome DevTools Protocol in ~1 second, no UI interaction needed.

---

## Chapter 6: What This Unlocks

### Before This Work
- 1 working endpoint: `GenerateFreeFormStreamed` (direct gRPC)
- Manual notebook management via Playwright browser automation
- ~50 queries/day limit (1 account)
- No programmatic access to artifacts, notes, or source management

### After This Work
- **24 rpcids decoded** covering all major operations
- **61 proto service methods** fully catalogued
- **Complete CRUD**: create/read/update/delete notebooks, sources, notes, artifacts
- **Source discovery**: NLM can auto-find web sources for a topic
- **Drive export**: artifacts → Google Drive
- **Multi-model**: switch underlying AI models
- **WebRTC audio**: understand how audio overview streaming works
- **Sharing API**: create access requests, share notebooks
- **Multi-account rotation**: with cookie pool, ~500 queries/day across 10 accounts
- **Magic View**: unexplored AI visualization feature ready to exploit

---

## Chapter 7: The Living System

The NLM integration is now embedded throughout CosySim:

1. **Nexus NLM Router** (`engine/nexus/nlm_direct_client.py`) — direct batchexecute calls
2. **Scheduler tasks** — daily news distillation, weekly NLM batch-ask  
3. **Skills** — `nlm_ask`, `nlm_create_notebook`, `nlm_add_source`, `nlm_distill`
4. **MCP tools** — 12 NLM tools exposed to all agents
5. **Cookie pool** — `data/accounts/pool.json` with CDP auto-refresh (task #49)

Every agent in CosySim can now ask questions to NotebookLM, create and populate notebooks, distill Q&A pairs, and get structured AI analysis — all programmatically, at scale, for free.

---

## Appendix: Key Files

| File | Purpose |
|------|---------|
| `scripts/heap_deep_parser.py` | Primary heap mining tool |
| `scripts/nlm_protocol_mapper.py` | HAR rpcid analyzer |
| `scripts/heap_miner.py` | High-level mining orchestrator |
| `data/nlm_artifacts.json` | Master artifacts: rpcids, methods, credentials |
| `data/heap_output/Heap-20260305T041326_deep/` | Gold heap output (406k strings) |
| `data/heap_output/nlm_module_DR4Ugf.js` | Angular WebRTC module (Kz patterns) |
| `engine/integrations/nlm_direct_client.py` | Live NLM client |
| `data/accounts/pool.json` | Live Google auth cookies |

---

*"Mine the heap. The heap never lies."*
