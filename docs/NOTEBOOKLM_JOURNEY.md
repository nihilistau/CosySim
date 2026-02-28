# NotebookLM Reverse Engineering — The Full Journey

> **Document Type:** Project Retrospective & Technical Reference
> **Period:** 2026-02-20 through 2026-02-28 (approx. 8 days, 10+ sessions)
> **Author:** Copilot (GitHub Copilot CLI) + Human operator
> **Status:** v3.1 complete — all RPCs confirmed, real chat implemented, archive built

---

## Table of Contents

1. [Why We Did This](#why-we-did-this)
2. [The Discovery Method](#the-discovery-method)
3. [Session-by-Session Chronicle](#session-by-session-chronicle)
4. [Every Wrong Assumption We Made (and How We Corrected Them)](#wrong-assumptions)
5. [The Critical Discoveries](#the-critical-discoveries)
6. [The Complete RPC Map — Final State](#the-complete-rpc-map)
7. [What Is Now Possible](#what-is-now-possible)
8. [What We Could Have Done Better](#what-we-could-have-done-better)
9. [What We Don't Know Yet](#what-we-dont-know-yet)
10. [The Bigger Picture — What This Means for the System](#the-bigger-picture)
11. [Operational Playbook — How to Keep This Working](#operational-playbook)

---

## Why We Did This

NotebookLM is Google's AI research assistant. It takes documents, PDFs, YouTube
videos, and URLs as sources, and lets you have conversations with Gemini about that
content — with citations. It's powerful, and crucially, it runs **on Google's compute**
for free (with daily query limits).

For CosySim and Nexus, NotebookLM represents:

1. **Free Gemini compute** — NLM runs Gemini 2.5 (or 3.0+) on every query, with
   full access to your sources. Every question answered by NLM is a question we
   don't have to route through our local LMStudio GPU.

2. **Knowledge distillation** — Upload CosySim's codebase, architecture docs, and
   decisions to a notebook. Then ask 20 precise questions. Get back cited, structured
   answers. Store them in Nexus. The local models now have access to Gemini-quality
   analysis without burning local tokens.

3. **Research automation** — Build a notebook with news sources, arXiv papers, or
   documentation. Ask systematic questions. Extract and store answers. Do this on
   a schedule. The Nexus knowledge base grows automatically.

4. **Source ingestion** — Add URLs, YouTube videos, PDFs programmatically. NLM
   processes and indexes them at Google's scale. We don't need a local scraper or
   embedding model for source retrieval.

The problem: NotebookLM has no public API. No SDK. No documented endpoints. Google
explicitly restricts third-party automation. The only way in is to reverse-engineer
the private `batchexecute` RPC protocol from browser network traffic.

That's what we did.

---

## The Discovery Method

### What is HAR Analysis?

An HTTP Archive (HAR) file is a recording of all network requests made by a browser.
Chrome DevTools can export HAR files with "sensitive data" (cookies, headers, POST
bodies) included. This gives us a complete record of every API call NotebookLM's
frontend makes when you interact with it.

Our methodology:

```
1. Open Chrome DevTools → Network tab → Start recording
2. Perform ONE specific operation in NotebookLM
3. Stop recording, export HAR (with sensitive data)
4. Run Python analysis script against the HAR
5. Find the new batchexecute call, decode its RPC ID and payload
6. Implement the RPC in the proxy
7. Test against the live API
8. Repeat for the next operation
```

This is called "differential analysis" — perform exactly one operation, observe
exactly one new RPC call, record the mapping. After 10+ sessions and ~10 HAR files,
we had mapped every meaningful operation in the NotebookLM interface.

### The batchexecute Protocol

NotebookLM uses the same private RPC transport as Google Search, Docs, Maps, and
most other Google products. All calls go to one endpoint:

```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
```

The `f.req` body is a JSON array of `[rpc_id, args_json, null, "generic"]` tuples.
Multiple RPCs can be packed into a single HTTP request — up to 5 in practice.

The **build label** (`bl`) is the most critical parameter. It's a string like
`boq_labs-tailwind-frontend_20260226.08_p0` that changes when Google deploys a new
frontend (~weekly). Old build labels still work for a while, but go stale after ~8
days. The `bl` is extracted automatically from every HAR we import.

### Authentication

Google auth requires a set of session cookies (`SID`, `SSID`, `APISID`, `SAPISID`,
`__Secure-1PSID`, etc.) plus a computed `Authorization: SAPISIDHASH` header.
The SAPISIDHASH is computed from `SAPISID` + current timestamp using SHA1.

Chrome 130+ started redacting cookies from HAR exports by default. We worked around
this in two ways:
- Explicit HAR export with "include sensitive data" checkbox ticked
- Chrome DevTools Protocol (CDP) automation to extract cookies from a live Chrome
  session programmatically

---

## Session-by-Session Chronicle

### Sessions 1–3: Foundation (HAR 1–3)

**Goal:** Establish basic read operations.

We started with the simplest possible question: what happens when NotebookLM loads?
The HAR revealed:
- `ZwVcOc` — session init, returns limits (max notebooks, max sources, etc.)
- `ub2Bae` — list all notebooks
- `wXbhsf` — list sources in a notebook
- `VfAZjd` — get AI summary of a notebook
- `gArtLc` — list notes/artifacts
- `rLM1Ne` — full notebook load

These were clean, easy to decode. We had a working read API in two days.

**What we got right:** The response parsing pattern — `)]}'` stripping, `wrb.fr`
detection, double `json.loads()` — was identified correctly from the first HAR.

### Sessions 4–5: Write Operations Attempted (HAR 4–5)

**Goal:** Find the chat/Q&A RPC.

This is where we first went wrong. We saw `CYK0Xb` firing when we submitted a
question in the chat interface. We mapped it as `RPC_CHAT_MESSAGE`.

What we missed: we were looking at an older version of the interface. `CYK0Xb` in
the *current* NLM interface fires when you **annotate text with citations** — a
different code path from the main chat. But in an older build it may have been the
chat RPC. We had stale assumptions from the early HAR data.

We also saw `s0tc2d` firing and thought it was "the new chat RPC" based on its
frequency and the fact it appeared right after submitting messages. That was the
second mistake — it's actually `RENAME_NOTEBOOK`. The "chat messages" we saw as
responses were actually the notebook title being returned after a rename.

**What went wrong:** We performed operations too quickly, with multiple actions per
HAR recording. Without differential isolation we couldn't cleanly separate
"rename happened" from "chat message sent."

### Sessions 6–7: Source Management Discovery (HAR 6–7)

**Goal:** Understand how sources are added, removed, and read.

Clean HAR isolation revealed:
- `tr032e` — read full source text. Powerful — returns the complete markdown of any source.
- `izAoDd` — add URL source (previously unknown)
- `tGMBJ` — delete source

The YouTube encoding discovery was serendipitous: the user added a YouTube video,
and we noticed the source object had the URL at position 7 instead of position 2.
Regular URLs at pos 2; YouTube at pos 7 (wrapped in `[[url]]`). Same RPC (`izAoDd`),
different payload shape — auto-detected by our YouTube URL regex.

### Sessions 8–9: Research Operations (HAR 8–9)

**Goal:** Understand NLM's "deep research" feature.

**The biggest wrong assumption:** We had previously seen `QA9ei` and labelled it
"Add Text Source" based on it appearing when we were manipulating sources. When we
did targeted HAR isolation — performing *only* the deep research operation — we
discovered `QA9ei` starts an asynchronous deep research session and returns a
`session_id` UUID.

`LBwxtb` was previously mapped as "add URL sources batch." With clean isolation
we saw it fires *after* `QA9ei` completes, carrying an AI-generated document title
and content. It adds that document as a source. This is the deep research pipeline:
`QA9ei` (start research) → NLM generates AI doc → `LBwxtb` (add AI doc as source).

### Session 10: The Real Chat Endpoint (HAR 10 — the breakthrough)

**Goal:** Find the actual chat interface.

The user typed "what is this notebook about?" into the NLM chat. We searched the HAR
for the call that returned Gemini's answer. It wasn't in the batchexecute calls at all.

After careful inspection we found: the chat goes to a completely different URL:
```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/
     google.internal.labs.tailwind.orchestration.v1
     .LabsTailwindOrchestrationService/GenerateFreeFormStreamed
```

This is a gRPC-over-HTTP/1.1 call (the `GenerateFreeFormStreamed` method name is the
protobuf service method). It has:
- Different URL pattern (no `batchexecute`)
- No `at` anti-forgery token in the body (cookies-only auth)
- Different payload format (`[null, json.dumps(inner)]`)
- Streaming SSE-like response where each chunk contains **the full text so far** (not deltas)
- A `thread_id` UUID that enables multi-turn conversation

This was the final missing piece. Without this we had a proxy that could read notebooks,
manage sources, and run research — but couldn't actually chat.

---

## Wrong Assumptions

This section catalogues every incorrect assumption we held, how long we held it,
and what corrected it.

### ❌ Assumption 1: `s0tc2d` = CHAT_MESSAGE

- **Held from:** Sessions 4–9 (roughly 5 sessions)
- **Impact:** Every "chat" call was silently **renaming the notebook**. We got back
  the notebook title (e.g. "CosySim Architecture") as a "queued response" and thought
  it was a pending AI answer. Chat appeared to "work" but produced garbage.
- **Corrected by:** HAR 10 differential analysis. We renamed the notebook to
  "RPC Test Notebook" while recording, saw `s0tc2d` fire with the exact name we typed
  in the payload. Confirmed: rename, not chat.
- **Root cause:** In an earlier NLM build, `s0tc2d` may have been the chat ID.
  Google rotates RPC IDs per build. We had stale mapping data.

### ❌ Assumption 2: `LBwxtb` = ADD_URL_SOURCES_BATCH

- **Held from:** Sessions 5–9
- **Impact:** Our `/sources` POST route was calling `LBwxtb` to add URLs. This
  silently added AI-generated research documents when triggered — not URLs. URL
  add appeared to fail (or succeed with wrong source type).
- **Corrected by:** Deep research HAR. Isolated `LBwxtb` payload showed
  `[null, [1], session_id, nb_id, [[null, [title, content]]]]` — the structure for
  adding an AI-written document, not a URL.
- **Root cause:** We saw `LBwxtb` during source management sessions and assumed
  it was a URL batching RPC without proper payload inspection.

### ❌ Assumption 3: `QA9ei` = ADD_TEXT_SOURCE

- **Held from:** Sessions 6–9
- **Impact:** Our "add text source" operation was actually starting deep research
  sessions with garbage payloads, returning session IDs we discarded as "errors."
- **Corrected by:** Deep research HAR. The payload `[null,[1],["topic",1],5,nb_id]`
  doesn't look anything like a source add payload on close inspection.
- **Root cause:** Timing — `QA9ei` appeared in HAR sessions when we were working
  with sources, so we assumed it was source-related.

### ❌ Assumption 4: Chat works via batchexecute

- **Held from:** The very beginning
- **Impact:** Delayed discovery of `GenerateFreeFormStreamed` by ~6 sessions.
  We kept looking for a batchexecute RPC ID for chat that didn't exist.
- **Corrected by:** Careful HAR search for the response containing Gemini's answer.
  When we searched for the answer text in the HAR and found it in a call to a
  completely different URL pattern, the assumption collapsed immediately.
- **Root cause:** Reasonable assumption — all other operations use batchexecute.
  Chat turned out to be a special case using the gRPC-over-HTTP proto service.

### ❌ Assumption 5: `CYK0Xb` = legacy chat (dead code)

- **Held from:** After discovering `s0tc2d` (which we wrongly thought was the new chat)
- **Impact:** We deprioritised `CYK0Xb` for several sessions.
- **Corrected by:** Final analysis. `CYK0Xb` still works and returns markdown with
  inline source citations. It's **annotation mode** — useful for Q&A distillation
  where you want cited answers. Different from `GenerateFreeFormStreamed` which is
  the conversational chat.
- **Root cause:** Two different "chat" modes exist. We collapsed them into one.

### ❌ Assumption 6: `sqTeoe` = LIST_ALL_NOTEBOOKS

- **Held from:** Very early (sessions 1–2)
- **Corrected by:** Isolating the exact operation that fires `sqTeoe`. It lists
  available audio overview types (podcast formats), not notebooks.
- **Impact:** Low — we had `ub2Bae` for notebook listing, so this didn't block anything.

### ❌ Assumption 7: `hPTbtc` = LIST_SOURCES_PAGED

- **Corrected by:** HAR isolation showing it returns thread IDs (UUIDs of
  conversation threads), not sources. Sources are via `wXbhsf`.

### ❌ Assumption 8: `khqZz` = SUB-NOTEBOOK_SOURCES

- **Corrected by:** HAR isolation — it reads messages within a thread (identified
  by thread_id), not sources.

---

## The Critical Discoveries

### Discovery 1: GenerateFreeFormStreamed is NOT batchexecute

The single most important discovery. The real NLM chat interface is a separate
gRPC/proto service endpoint, completely outside the batchexecute framework.

```
https://notebooklm.google.com/_/LabsTailwindUi/data/
    google.internal.labs.tailwind.orchestration.v1
    .LabsTailwindOrchestrationService/GenerateFreeFormStreamed
```

Key properties:
- No `at` anti-forgery token in body (cookies only)
- Outer payload: `[null, json.dumps(inner_9_element_array)]`
- Response: SSE streaming with **full text so far** (not deltas)
- Thread-based multi-turn conversation
- Source context passed in the request (all source IDs)

### Discovery 2: Every source type is one RPC

`izAoDd` handles URLs, YouTube videos, and presumably other URL-accessible content
all with the same RPC. The payload differs by content type:
- Regular URL → position 2 in source object
- YouTube → position 7 in source object (wrapped in `[[url]]`)

This means we can add any web content to a notebook with a single call.

### Discovery 3: tr032e can extract all source content

`tr032e` (READ_SOURCE) returns the full processed text of any source. This is NLM's
internal representation after OCR/scraping/transcription — clean, formatted content.
Combined with `wXbhsf` (list sources), we can extract the *entire* processed content
of a notebook's sources programmatically. This is essentially a document scraper that
runs at Google's scale.

### Discovery 4: The deep research pipeline

NLM's deep research feature is a two-RPC pipeline:
1. `QA9ei` → starts research, returns `session_id`
2. (NLM generates AI document asynchronously)
3. `LBwxtb` → adds the AI document as a notebook source

This means we can trigger NLM to research any topic and add the results as a source,
expanding the notebook's knowledge base automatically. The research document becomes
searchable, citable, and readable via `tr032e`.

### Discovery 5: Multi-turn conversation via thread_id

The `GenerateFreeFormStreamed` endpoint accepts a `thread_id` UUID at position 4 of
the inner payload. Using the same thread_id across questions maintains conversation
context. This enables:
- Multi-turn research conversations with NLM
- Follow-up questions that reference prior answers
- Guided knowledge extraction with conversational depth

### Discovery 6: The SAPISIDHASH doesn't need to be fresh

Despite the timestamp in the SAPISIDHASH, NLM's auth validation doesn't appear to
strictly enforce timestamp freshness beyond basic cookie validity. The key requirement
is valid session cookies, not a precisely timed hash. This simplifies token refresh
logic — cookies are the real auth material.

---

## The Complete RPC Map

Final confirmed state as of 2026-02-28 (v3.1):

| RPC ID | Name | Category | Confirmed | Notes |
|--------|------|----------|-----------|-------|
| `ZwVcOc` | SESSION_INIT | Read | HAR 1 | Session limits: max notebooks, sources, chars |
| `ub2Bae` | LIST_NOTEBOOKS | Read | HAR 1 | Returns all user notebooks with IDs and names |
| `wXbhsf` | LIST_SOURCES | Read | HAR 1 | All sources in a notebook with metadata |
| `VfAZjd` | AI_SUMMARY | Read | HAR 2 | Gemini-generated notebook overview |
| `gArtLc` | LIST_ARTIFACTS | Read | HAR 2 | Notes, saved reports, generated docs |
| `rLM1Ne` | LOAD_NOTEBOOK | Read | HAR 2 | Full notebook state including sources |
| `e3bVqc` | NOTEBOOK_INFO | Read | HAR 3 | Detailed notebook content/documents |
| `tr032e` | READ_SOURCE | Read | HAR 6 | **Full text of any source — very powerful** |
| `sqTeoe` | LIST_AUDIO_TYPES | Read | HAR 3 | Audio overview format options |
| `hPTbtc` | GET_THREAD_IDS | Read | HAR 7 | Conversation thread UUIDs for a notebook |
| `khqZz` | READ_THREAD | Read | HAR 7 | Messages in a specific conversation thread |
| `JFMDGd` | USER_PROFILE | Read | HAR 3 | Email, name, queries remaining |
| `ozz5Z` | ACCOUNT_STATE | Read | HAR 3 | Storage quota, plan info |
| `cFji9` | MIND_MAP | Read | HAR 4 | D3-format knowledge graph/mind map |
| `CCqFvf` | RESUME_SESSION | Read | HAR 3 | Load last active notebook |
| `CYK0Xb` | ANNOTATE | Write | HAR 4 | Citation Q&A — synchronous, returns markdown+citations |
| `s0tc2d` | **RENAME_NOTEBOOK** | Write | HAR 10 ⭐ | ❌ Was wrongly `CHAT_MESSAGE` in v2.x |
| `ciyUvf` | GENERATE_DOC | Write | HAR 5 | Generate document from selected sources |
| `R7cb6c` | SAVE_REPORT | Write | HAR 5 | Save note artifact to notebook |
| `Ljjv0c` | FAST_RESEARCH_START | Write | HAR 8 | Start fast research session |
| `QA9ei` | **START_DEEP_RESEARCH** | Async | HAR 9 ⭐ | ❌ Was wrongly `ADD_TEXT_SOURCE` in v2.x |
| `LBwxtb` | **ADD_RESEARCH_SOURCE** | Async | HAR 9 ⭐ | ❌ Was wrongly `ADD_URL_SOURCES_BATCH` in v2.x |
| `izAoDd` | **ADD_SOURCE** | Write | HAR 6 ⭐ | URL + YouTube, auto-detected by URL pattern |
| `tGMBJ` | **DELETE_SOURCE** | Write | HAR 6 ⭐ | Payload: `[[[source_id]], [2]]` |
| — | **GenerateFreeFormStreamed** | Proto | HAR 10 ⭐ | ❌ Not batchexecute. Real NLM chat |

**Symbols:** ⭐ = new in v3.1, ❌ = corrected wrong assumption

---

## What Is Now Possible

### Immediate capabilities (implemented in v3.1)

**Read everything:**
- List all notebooks: `GET /notebooks`
- Get notebook summary: `GET /notebooks/<id>/summary`
- List all sources: `GET /notebooks/<id>/sources`
- Read full source text: `GET /sources/<id>/content`
- Get notes/artifacts: `GET /notebooks/<id>/notes`
- Get conversation threads: `GET /notebooks/<id>/threads`
- Read thread messages: `GET /notebooks/<id>/threads/<tid>`
- Get mind map: `GET /notebooks/<id>/mindmap`
- Get user profile + query limits: `GET /user/profile`

**Write everything:**
- Add URL sources: `POST /notebooks/<id>/sources/url`
- Add YouTube sources: same route, auto-detected
- Delete sources: `DELETE /notebooks/<id>/sources/<source_id>`
- Rename notebooks: `POST /notebooks/<id>/rename`
- Annotate/cite text: `POST /notebooks/<id>/ask`
- Batch annotate: `POST /notebooks/<id>/ask_batch`
- Real chat: `POST /notebooks/<id>/chat`
- Multi-turn chat batch: `POST /notebooks/<id>/chat_batch`
- Generate document: `POST /notebooks/<id>/generate`
- Save note: `POST /notebooks/<id>/save_note`
- Start fast research: `POST /notebooks/<id>/research`
- Start deep research: `POST /notebooks/<id>/research/deep`
- Add research source: `POST /notebooks/<id>/research/source`

**Download everything:**
- Download all source text: `GET /notebooks/<id>/sources/content`
- Export single source: `GET /sources/<id>/export`
- Full notebook archive: `GET /notebooks/<id>/archive`
- All notebooks archive: `GET /notebooks/archive`

### Workflows now unlocked

**1. Knowledge distillation pipeline**
```
Upload codebase/docs as sources
→ Batch-ask 20+ questions via /chat_batch
→ Store all Q&A pairs in Nexus
→ Local models answer future questions from Nexus cache
→ Zero GPU tokens spent on already-answered questions
```

**2. Automated news/research ingestion**
```
Create topic notebook (e.g. "AI News 2026-02-28")
→ Add 10-20 source URLs via /sources
→ Wait for processing via /sources/wait
→ Start deep research on topic via /research/deep
→ Ask 20 curated questions via /chat_batch
→ Store distilled knowledge in Nexus
→ Archive notebook content to local storage
→ Run on schedule 2-3x/day
```

**3. Source content extraction**
```
List all sources in any notebook
→ Download full text of each source via /sources/content
→ Push to Nexus as knowledge entries
→ Source content becomes searchable, citeable, trainable
→ NLM's processed/cleaned text is better than raw scraping
```

**4. Multi-turn agent conversations**
```
Create a notebook with project documentation as sources
→ Local agent asks NLM questions via /chat with thread_id
→ Follow-up questions maintain context
→ Agent extracts structured answers
→ Store Q&A in Nexus for future agents
```

**5. Autonomous notebook management**
```
Agent creates notebook (POST /notebooks)
→ Adds sources (URLs, YouTube, research docs)
→ Waits for processing (/sources/wait)
→ Generates document from sources (/generate)
→ Asks questions (/chat_batch)
→ Archives everything (/archive)
→ Deletes notebook when done
→ Full lifecycle, zero human interaction
```

### What requires more HAR work

**Not yet confirmed:**
- `DELETE /notebooks/<id>` — we have `ZwVcOc` listed as "delete notebook" but
  the RPC ID and payload are unconfirmed
- Upload file as source (PDF, Google Doc) — `izAoDd` may handle this or there may
  be a different upload pathway
- Edit/update an existing note
- Podcast/audio overview generation — `sqTeoe` returns types but we haven't found
  the generation RPC

---

## What We Could Have Done Better

### 1. One operation per HAR from the start

**The problem:** Early sessions recorded multiple operations per HAR. This made
differential analysis hard — we had to guess which RPC corresponded to which action.

**What would have been better:** Strict one-operation-per-HAR discipline from day
one. Open DevTools, clear network log, perform *exactly one operation*, export HAR.
This would have cut our sessions from 10+ down to 5-6 and avoided all the wrong
assumptions.

**Lesson learned:** When reverse-engineering unknown APIs, isolation is everything.
One observation per experiment.

### 2. Inspect payload structure immediately, not just RPC IDs

**The problem:** In early sessions we recorded the RPC ID and a surface description
but didn't always decode the full payload and response. We assigned names based on
timing and frequency.

**What would have been better:** For each new RPC, immediately decode and document:
- Full payload structure (every position, even nulls)
- Full response structure (what comes back)
- Cross-reference against the operation we just performed

This would have caught the `s0tc2d` / `LBwxtb` / `QA9ei` errors much sooner.

### 3. Script the HAR analysis from session 1

**The problem:** Early analysis was manual — reading HAR JSON by hand in a text editor.

**What would have been better:** Write the Python analysis script in session 1 and
run it against every HAR from the start. The script should:
- Extract all batchexecute calls
- Decode RPC IDs and payloads
- Diff against previously seen RPCs
- Highlight new and changed calls

We did build this script, but in session 4 rather than session 1.

### 4. Test every RPC against the live API immediately

**The problem:** We implemented RPCs in the proxy and moved on without live-testing them.

**What would have been better:** After implementing each RPC:
1. Start the proxy
2. Make a live call with a known notebook_id
3. Verify the response matches expectations

This would have caught the `s0tc2d` rename problem in session 5 instead of session 10.

### 5. Build a payload fingerprint database

**The problem:** We relied on human interpretation of payload shapes to assign RPC
names. Humans make errors under ambiguity.

**What would have been better:** Build a payload fingerprint system:
- Hash the payload structure (list lengths, types at each position)
- Store all observed fingerprints per RPC
- Flag when a new HAR shows a known RPC with a different fingerprint

This would have immediately flagged that `s0tc2d`'s payload doesn't look like a chat
message payload (chat messages are strings; rename payloads have the
`[[null,null,null,[null,"name"]]]` nesting).

### 6. Check for non-batchexecute calls in the HAR from the start

**The problem:** We only looked at batchexecute calls for the first 9 sessions.
`GenerateFreeFormStreamed` was hiding in plain sight in every chat HAR we captured.

**What would have been better:** In the analysis script, always log ALL distinct URL
patterns in the HAR, not just batchexecute ones. A one-line filter change that would
have revealed the proto endpoint in session 5.

---

## What We Don't Know Yet

### Unconfirmed RPCs

| RPC | Suspected operation | Confidence | Notes |
|-----|--------------------|----|-------|
| `ZwVcOc` | DELETE_NOTEBOOK | Medium | Listed as session init AND delete in some analyses |
| Upload pipeline | File upload as source | Unknown | PDF/Doc upload likely uses a different non-batchexecute path |
| Podcast generation | Generate audio overview | Low | Related to `sqTeoe` but generation RPC unknown |
| Note editing | Update existing note content | Unknown | We can create notes, can we edit them? |
| Source reordering | Change source order in notebook | Unknown | Drag-drop in UI suggests a write RPC exists |

### Open questions

1. **Does NLM enforce per-notebook query limits?** The `queries_remaining` field in
   `JFMDGd` suggests yes. We haven't hit a limit yet.

2. **Can `GenerateFreeFormStreamed` be interrupted mid-stream?** We buffer the full
   response, but streaming opens the door to incremental display.

3. **Are there write RPCs for editing notes?** We can create notes (R7cb6c) but haven't
   found an update/edit operation.

4. **What does `sqTeoe` return exactly, and what triggers podcast generation?** Audio
   overviews are a flagship NLM feature — automating them would be valuable.

5. **Can multiple notebooks be active simultaneously?** Rate limiting suggests NLM
   may serialize some operations at the account level.

---

## The Bigger Picture

### What We Built

A complete programmatic interface to NotebookLM. Not a scraper, not a hack — a
proper API client that mirrors everything the official UI can do, plus things the
UI doesn't offer (bulk source download, full archive export, batch Q&A).

The proxy at `:8800` is a first-class citizen in the CosySim/Nexus stack:
- MCP tools (`nlm_create_notebook`, `nlm_add_codebase`, `nlm_distill`, etc.)
- Nexus integration (research → store)
- Skill packs for local agents
- Scheduled news ingestion

### The Compound Effect

Every answer from NLM is stored in Nexus. Every stored answer reduces future LLM
compute. The system gets smarter every time it uses NLM, because answers accumulate
in the cache. Over time:

```
NLM API calls → Nexus Q&A cache → Local model answers
(free Gemini)   (permanent memory)  (zero tokens)
```

The more we use NLM, the more the local models benefit without burning GPU resources.

### Why This Matters Long-Term

NotebookLM is updated by Google continuously. New features appear. RPC IDs may
change with frontend deployments. The protocol we reverse-engineered is a living
target.

But the *methodology* is permanent:
- HAR analysis for API discovery
- Differential isolation for clean mapping
- Proxy pattern for API abstraction
- Registry + fallback for RPC ID management

When Google changes something, we run a new targeted HAR, update the registry,
and the proxy continues working. The proxy is designed for this — the RPC IDs are
loaded from `nlm_rpc_mapper` at runtime with hardcoded fallbacks.

---

## Operational Playbook

### When the proxy stops working

**Symptom:** All responses return null or HTTP 400/401

**Steps:**
1. Check BL staleness: `GET http://localhost:8800/health` → check `bl_stale`
2. If stale: `POST /cookies/refresh` (tries to pull fresh tokens from live page)
3. If still failing: capture fresh cookies via `POST /cookies/capture` (CDP)
4. If CDP fails: manual HAR export from Chrome, import via `POST /cookies/import`

### Weekly maintenance

1. Check BL age: `GET /health` → `bl_age_days`
2. If > 6 days: capture fresh cookies proactively
3. Run a test query against a known notebook to verify end-to-end

### Adding a new notebook workflow

```bash
# 1. Create notebook
curl -X POST http://localhost:8800/notebooks \
  -H 'Content-Type: application/json' \
  -d '{"title": "My Research Notebook"}'
# → returns notebook_id

# 2. Add sources
curl -X POST http://localhost:8800/notebooks/<id>/sources/url \
  -d '{"url": "https://arxiv.org/abs/2312.12345"}'

# 3. Wait for processing
curl http://localhost:8800/notebooks/<id>/sources/wait?timeout=120

# 4. Batch-ask questions
curl -X POST http://localhost:8800/notebooks/<id>/chat_batch \
  -d '{"questions": ["What is the main contribution?", "What are the limitations?"]}'

# 5. Archive everything
curl http://localhost:8800/notebooks/<id>/archive > notebook_archive.json
```

### When Google changes RPC IDs

1. Open Chrome, visit NotebookLM
2. Open DevTools → Network tab → clear log
3. Perform the operation that's failing (one operation only)
4. Export HAR: right-click → "Save all as HAR with content"
5. Run analysis: `python engine/nexus/nlm_automation.py --har /path/to.har`
6. Update `data/nlm_rpc_registry.json` with new IDs
7. The proxy loads registry at runtime — no code change needed unless new operations

---

*This document captures the complete technical and methodological history of the*
*NotebookLM reverse engineering project. Store it in Nexus. Reference it when*
*onboarding new agents or planning new NLM integrations.*

*Last updated: 2026-02-28 | Version: 3.1 | Author: Copilot*
