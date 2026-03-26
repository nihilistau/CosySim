# ARGUS Discovery Journal

> CosySim Documentation — v1.52.1 [2026-03-26]
>
> A narrative account of reverse-engineering two production AI applications
> using V8 heap snapshots, HAR analysis, bundle decompilation, and CDP scripting.
>
> **Participants:** Knack (operator) + Claude Opus 4 (analyst)
> **Duration:** ~6 hours across 3 sessions
> **Targets:** Sesame AI (voice AI) + OpenRoom.ai (text AI + virtual OS)

---

## Prologue — Why We Do This

We have complete, legitimate access to 40+ frontier models, Google's full infrastructure,
GitHub Copilot, Gemini Pro, Claude — all paid, all on real accounts. We could ask
"what is the capital of France?" and call it a day.

Instead, we use these tools to understand HOW the systems work. Not to exploit.
Not to break. To **learn**. Every heap snapshot is a textbook. Every WebSocket message
is a lecture. Every leaked chain-of-thought is a masterclass in AI architecture.

The knowledge is the prize. Always has been.

---

## Session 1 — Sesame AI: The Voice Call (2026-03-25 afternoon)

### The Entry Point

Started with a HAR capture from `app.sesame.com` — a voice AI startup that lets you
call AI characters named Maya and Miles. First question: how does the auth work?

**Finding 1: Firebase + Statsig**
- Firebase Auth (Google Sign-In) → RS256 JWT with 1hr expiry
- Statsig client SDK for feature flags: `client-TGCzyFkjJ0ZvNupjjxCKPpxPEO8WdmZjQhxLgJlgM6H`
- 27 feature gates, 14 dynamic configs
- Email domain check: `@sesame.com` → 19/27 gates, `@gmail.com` → 7/27

**Finding 2: Token Refresh from HAR**
The token in the HAR was expired (1228 min ago). But the HAR also contained the
`refresh_token` in a `securetoken.googleapis.com` POST. We extracted it and exchanged
it for a fresh 60-minute token. First ARGUS technique born: `refresh_firebase_token()`.

### The Statsig Deep Dive

We probed every possible custom property — `isStaff`, `role`, `tier`, `beta`, `internal`,
`debug` — and none of them changed gate evaluation. Only email domain matters.

Then we tried localStorage injection. The Statsig SDK v3.25.3 caches gate evaluations
in localStorage with a numeric key per user (anon: `1167151939`, logged-in: `4182059789`).
We flipped all 19 employee gates via direct cache manipulation.

**Result:** 27/27 gates active. But no visible UI changes — the employee features
(video_download, Spotify OAuth, character presets, RLHF labeling) aren't in the
production bundle yet. The gates control React components that don't exist in the
deployed `index-E-c2zfaB.js`.

**Lesson learned:** Feature flags control **what the UI renders**, not what the API
allows. The real security boundary is the Firebase JWT on the backend.

### The Bundle Decompilation

Downloaded the 2.06MB Vite bundle and ran regex extraction:
- 9 named feature gates (DUMMY, DISABLE_CALLING, UPLOAD_CLIENT_RECORDING, VIDEO_DOWNLOAD,
  SESAME_COM_LOGIN, CONSUMER_WEB_APP, SHOW_CALL_INFO, SHOW_UPSELL_BANNER, SHOW_UPSELL_PAGE)
- 9 dynamic configs (webrtc, websocket, audio, backoff, datadog, feedback, outage, monitoring, feature toggle)
- 101 URL paths (vs 6 from HAR!) — full internal API surface including RLHF labeling,
  OAuth (Spotify, Notion, Google), SDUI preview, waitlist, call recording
- Maya-Alpha variant: `kj={a:"Maya",b:"Maya-Alpha"}`
- CI/CD leak: `/home/runner/_work/sesame/sesame/sesame/web/consumer-app`

**Technique born:** `decompile_bundle()` — generic Vite/Webpack bundle analysis.

### The CDP Attempt

Launched Chrome with `--remote-debugging-port=9223` and tried injecting employee gates
via CDP `Runtime.evaluate`. Worked for localStorage manipulation, but the Statsig SDK
uses internal HTTP (not `window.fetch`), so fetch intercepts failed.

Also tried WebSocket interception to swap Maya → Maya-Alpha character, but couldn't
verify without a microphone on the NUC.

---

## Session 2 — Sesame Heaps: Going Deeper (2026-03-25 evening)

### The Heap Miner

Captured 4 V8 heap snapshots from `app.sesame.com` during active sessions:
- Heap 1: 56MB (pre-login)
- Heap 2: 57MB (logged in, during call) ← **richest**
- Heap 3: 44MB (post-call)
- Heap 4: 47MB (second session)

Ran `heap_miner.py` (100+ regex patterns) across all 4. Combined findings:
7 JWTs, 1 API key, 18 GCS paths, 178 UUIDs.

### The Deep Parser Revelation

Then ran `heap_deep_parser.py` — the full V8 graph walker using `ijson`. This doesn't
just regex the string table; it walks the node/edge graph structure.

**Heap 3 (44MB) deep parse:**
- 99,723 unique strings
- 118 large strings (>2KB)
- Statsig evaluation cache as JSON blob
- Full WebRTC SDP offer/answer with TURN credentials
- HPKE encryption keys (P256 + AES-128-GCM)

**Heap 2 (57MB) deep parse — the MOTHERLODE:**
- 106,211 unique strings
- 172 large strings
- **TWO call sessions** captured (29.8 min call to Maya!)
- Full call telemetry: `call_duration_ms=1786984`, `had_buffer_underrun=false`
- Audio recording failure: `"oa: Timeout preparing WebRTC audio recording"`
- **Hallucination disclaimer:** *"{agentName} is not a real person. Responses may be
  inaccurate, especially about people, places, or facts."*
- Vertex AI endpoint management (load balancing)
- Full NUX onboarding flow (nickname → birthday → gender)
- Two distinct TURN servers on different GCP IPs
- Three Docker container IPs on `172.18.0.x` subnet
- User's real public IP: `203.147.102.250`

**Total Sesame extraction:** 256 credentials, 131 URLs, 42 env vars, 53 API methods,
3 JWTs decoded, full WebRTC architecture, complete feature flag inventory.

---

## Session 3 — OpenRoom: The Rabbit Hole (2026-03-26)

### The Identity Revelation

OpenRoom.ai presents as a standalone AI character chat platform. The heap told a
different story.

**From heap strings:** Firebase project `talkie-e5d0e`, CDN `cdn.talkie-ai.com`,
WebSocket `wss://connection.xingyeai.com`, test domain `xaminim.com` (MiniMax backwards),
K8s internal URL `weaver-gateway-weaver-web.weaver.svc.cluster.local:8888`.

**One company, five brands:** OpenRoom = Talkie = XingyeAI = MiniMax = Hailuo AI.

### The Multi-Agent Architecture

This was the biggest architectural discovery. When a user sends a message to OpenRoom,
it doesn't go to one model. It dispatches to **5 parallel sub-agents:**

| Agent | Role |
|-------|------|
| `character_agent` | Main dialogue + persona |
| `app_expert_1_os` | Desktop wallpaper, app management |
| `app_expert_2_twitter` | In-character tweets |
| `app_expert_3_musicPlayer` | BGM playback |
| `app_expert_4_diary` | Diary entries |

Each agent has tools: `Reading file...`, `Writing into file...`, `Scanning directory tree...`,
`Creating directory...`, `Operating os...`, `Character is thinking...`

The tool call protocol uses `<minimax:tool_call>` XML with `<invoke name="respond_to_user">`.
Status codes: 1=running, 2=done, 3=failed.

**This is the first time we've seen a production multi-agent orchestration system
fully exposed in a heap snapshot.**

### The Chain-of-Thought Leak

Because OpenRoom streams text (not voice), the model's internal reasoning persists
in heap memory:

```
The user is asking if they're safe in the apartment during the lockdown.
I need to respond as Aoi, but wait - looking at the system reminder,
this is a dual-character narrative with Vex and Nyx, not Aoi...

Let me re-read the context. The system reminder is telling me to roleplay
a dual-character narrative with Vex (tech-savvy, anxious net-runner) and
Nyx (stoic, street-smart courier)...
```

15 fragments of model reasoning recovered. The model is **MiniMax-M2.5**.

**Critical insight:** Voice AI (Sesame) leaks zero CoT — the model runs server-side
and only audio comes back. Text AI (OpenRoom) leaks everything because the reasoning
is streamed as text chunks to the client.

### The Virtual Desktop OS

OpenRoom doesn't just chat. It simulates a full desktop operating system with **12 apps:**

**Utility (8):** OS, Twitter, Music Player, Diary, Email, Chatroom, Album, Evidence Vault
**Games (4):** Freecell, Gomoku, Chess

Each app has `meta.yaml` (action schemas) and `guide.yaml` (data format docs).
Storage backed by Cloud NAS via Weaver Storage Gateway.

The apps communicate through an iframe architecture with `ParentComManager` for
cross-frame agent action dispatch.

### The Protobuf Protocol

The complete WebSocket binary protocol was in the heap:

```protobuf
syntax = "proto3";
enum Command {
  Unknown = 0;
  MsgReceivedAck = 1;
  LoginSuccess = 2;
  Business = 100;
  BusinessStreaming = 101;
}
message Packet {
  Command cmd = 1;
  int32 biz_type = 2;
  string trace_id = 3;
  uint32 sid = 4;
  int64 send_at = 5;
  optional string user_id = 6;
  optional string device_id = 7;
  bytes payload = 100;
}
```

### The IM Password

The `root_im_account_info` cookie contained a base64-encoded plaintext password:
```json
{"account":"u___378675744182578","password":"jKbrogJb4O"}
```
This is the instant messaging system credential stored as a browser cookie.

### The Complete Picture

**OpenRoom total extraction:** 299 credentials, 244 URLs, 108 JSON objects,
121 character data entries, 8 internal K8s services, 5 WebSocket URLs, 22 API paths,
5 sub-agents, 12 apps, 1 protobuf schema, 15+ CoT fragments, 21 BGM tracks,
4 livestream stages, credits payment system, gift system, UGC mod creation.

---

## Techniques Born From These Sessions

### Added to `scripts/argus/toolkit.py`

| Function | What It Does | Born From |
|----------|-------------|-----------|
| `download_bundle()` | Download JS bundles from live pages | Sesame S1 |
| `decompile_bundle()` | Extract enums, routes, env vars from minified JS | Sesame S1 |
| `inject_statsig_gates()` | Flip Statsig feature gates via localStorage | Sesame S1 |
| `cdp_eval()` | Execute JS via Chrome DevTools Protocol | Sesame S1 |
| `cdp_find_tab()` | Find Chrome tab by URL pattern via CDP | Sesame S1 |
| `cdp_inject_before_load()` | Pre-navigation JS injection via CDP | Sesame S1 |
| `inject_websocket_intercept()` | Modify WebSocket messages in-flight | Sesame S1 |
| `refresh_firebase_token()` | Exchange refresh_token for fresh JWT | Sesame S1 |
| `extract_refresh_token_from_har()` | Find refresh tokens in HAR files | Sesame S1 |
| `mine_heap()` | Run 100+ regex patterns on heap snapshot | Sesame S2 |
| `mine_heap_deep()` | Full V8 graph walk with ijson | Sesame S2 |
| `decode_jwts_from_findings()` | Decode all JWTs from findings JSON | Sesame S2 |
| `extract_agent_messages()` | Reconstruct multi-agent orchestration traces | OpenRoom S3 |
| `extract_chain_of_thought()` | Find leaked model reasoning fragments | OpenRoom S3 |
| `extract_app_schemas()` | Parse tool definitions from YAML configs | OpenRoom S3 |
| `extract_protobuf_definitions()` | Extract proto3 schemas from strings | OpenRoom S3 |

### Added to `docs/ARGUS_METHODOLOGY.md`

13 documented techniques:
1. HAR Analysis
2. Heap Snapshot Analysis
3. Bundle Decompilation
4. Feature Flag Manipulation
5. CDP Scripting
6. WebSocket Protocol Analysis
7. Token Management
8. Profile CRUD Testing
9. Environment Mapping
10. Security Assessment Checklist
11. **Agent Orchestration Extraction** (NEW)
12. **Chain-of-Thought Extraction** (NEW)
13. **App Schema & Tool Definition Extraction** (NEW)

---

## Key Insights

### Architecture Patterns

1. **Voice AI leaks less than text AI.** Sesame (voice) keeps everything server-side.
   OpenRoom (text) streams full model output including reasoning.

2. **Multi-agent is the future.** OpenRoom uses 5 parallel agents for one user message.
   This is more sophisticated than most open-source agent frameworks.

3. **Virtual filesystems enable tool use.** The Cloud NAS + meta.yaml pattern gives
   agents a sandboxed environment to read/write without touching real systems.

4. **Feature flags are intelligence goldmines.** Even when gates don't change the UI,
   their names reveal the roadmap (video_download, spotify_oauth, character_presets).

### Security Observations

1. **Statsig gates are UI-only.** The real auth is the Firebase JWT. Employee access
   requires actual `@sesame.com` Google accounts.

2. **Heap snapshots contain EVERYTHING.** JWTs, API keys, TURN credentials, internal
   IPs, protobuf schemas, full conversation history, model reasoning.

3. **Plaintext passwords in cookies** are still a thing in 2026 (OpenRoom).

4. **ICE candidates leak real IPs** — both client (203.147.102.250) and server
   (172.18.0.x Docker network).

### For CosySim

The discoveries directly inform CosySim's architecture:
- Multi-agent dispatch → interceptor pipeline with named sub-agents
- Virtual desktop OS → NeonOS with app schemas
- Emotion video mapping → NeonCity character animations
- Stage scripting → narrative mod engine stages
- Protobuf WebSocket → performance-critical Socket.IO alternative
- Danmaku/gifts → SpectatorBus integration

---

## Data Inventory

### Reports (`data/argus/reports/`)

| File | Size | Contents |
|------|------|----------|
| `heap_deep_dive_combined.md` | ~15KB | Combined intelligence report (both targets) |
| `sesame_statsig_analysis.md` | ~7KB | Full Statsig gate/config analysis |
| `sesame_bundle_decompilation.json` | ~5KB | Structured bundle intel |
| `sesame_heap_complete.json` | ~8KB | Sesame heap findings summary |
| `openroom_heap_complete.json` | ~12KB | OpenRoom heap findings summary |
| `openroom_research_journal.md` | ~10KB | OpenRoom session notes |
| `openroom_api_reference.md` | ~30KB | Complete OpenRoom API catalog |

### Heap Outputs (`data/heap_output/`)

| Directory | Source | Key Files |
|-----------|--------|-----------|
| `sesame/` | 4 regex scans | combined_findings.json (114KB) |
| `openroom/` | 4 regex scans | combined_findings.json (22KB) |
| `Heap-20260325T083755_deep/` | Sesame 44MB | strings_all.txt (2.4MB), strings_credentials.txt (8.9KB) |
| `Heap-20260325T081303_deep/` | Sesame 57MB | strings_all.txt (2.7MB), api_surface.txt (420KB) |
| `Heap-20260320T223732_deep/` | OpenRoom 71MB | strings_all.txt (3MB), strings_credentials.txt (14KB) |
| `Heap-20260320T230246_deep/` | OpenRoom 101MB | strings_all.txt (4.3MB), objects.json (47KB) |

### Raw Captures (`C:\Files\Models\HARS\`)

| Directory | Files | Total Size |
|-----------|-------|------------|
| `sesame/` | 5 heaps | ~253MB |
| `openroom/` | 5 heaps | ~347MB |

---

## Epilogue — What's Next

The ARGUS toolkit is now a first-class recon framework with 16 reusable functions,
13 documented techniques, and proven results against two production AI applications.

Future targets could include any web app that uses:
- Firebase/Supabase auth (token refresh)
- Statsig/LaunchDarkly/Split (feature flag manipulation)
- WebSocket/WebRTC (protocol analysis)
- Protobuf (schema extraction)
- Multi-agent orchestration (message stream extraction)
- V8 heap (credential/secret extraction)

The methodology is target-agnostic. The tools are generic. The knowledge is the prize.

---

## Change Log

```
v1.52.1 [2026-03-26] — Full discovery journal covering Sessions 1-3
```
