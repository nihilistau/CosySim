# ARGUS Intelligence Report — OpenRoom.ai

```
 ╔══════════════════════════════════════════════════════════════════════╗
 ║   ___  ____  _____ _   _ ____   _____ ___  __  __           _      ║
 ║  / _ \|  _ \| ____| \ | |  _ \ / _ \ / _ \|  \/  |   __ _ (_)     ║
 ║ | | | | |_) |  _| |  \| | |_) | | | | | | | |\/| |  / _` || |    ║
 ║ | |_| |  __/| |___| |\  |  _ <| |_| | |_| | |  | | | (_| || |    ║
 ║  \___/|_|   |_____|_| \_|_| \_\\___/ \___/|_|  |_|  \__,_||_|    ║
 ║                                                                      ║
 ║              ARGUS Intelligence Report — CosySim                     ║
 ║                                                                      ║
 ║  Classification: COMPREHENSIVE                                       ║
 ║  Version:        v1.52.1 [2026-03-26]                               ║
 ║  Target:         www.openroom.ai                                     ║
 ║  Author:         ARGUS Intelligence Platform                         ║
 ╚═══════��═════════════════════════════════════���════════════════���═══════╝
```

> **Sources:** 10 HAR files (51MB—502MB), 4 heap snapshots (46MB—101MB),
> 2 deep-parsed V8 heaps, 120K+ strings analyzed, live API probing
>
> **Capture Period:** 2026-03-20 through 2026-03-26
>
> **Method:** Passive traffic analysis, authenticated browsing, heap memory forensics

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Brand Mapping (Definitive)](#2-brand-mapping-definitive)
3. [Authentication & Credentials](#3-authentication--credentials)
4. [Kubernetes Infrastructure](#4-kubernetes-infrastructure)
5. [WebSocket Protocol](#5-websocket-protocol)
6. [Multi-Agent Architecture](#6-multi-agent-architecture)
7. [Chain-of-Thought Analysis](#7-chain-of-thought-analysis)
8. [Virtual Desktop OS — 12 Apps](#8-virtual-desktop-os--12-apps)
9. [Weaver API Surface](#9-weaver-api-surface)
10. [Characters](#10-characters)
11. [Live Stream (VTuber) System](#11-live-stream-vtuber-system)
12. [Music / Audio System](#12-music--audio-system)
13. [Monetization](#13-monetization)
14. [CDN Architecture](#14-cdn-architecture)
15. [Observability](#15-observability)
16. [Security Assessment](#16-security-assessment)
17. [Methodology](#17-methodology)

---

## 1. Executive Summary

**OpenRoom.ai** is a multi-agent AI character chat platform disguised as a standalone product.
Heap snapshot forensics reveal it is one face of a multi-brand operation spanning **at least
five consumer brands** and **two corporate entities**, all running on the same backend
infrastructure, the same Firebase project, and the same proprietary model.

### Key Numbers

| Metric | Value |
|--------|-------|
| Sub-agents per user message | **5** |
| Virtual desktop apps | **12** (8 utility + 4 games) |
| API endpoints discovered | **22+** |
| WebSocket environments | **5** (3 prod, 2 test) |
| Backing LLM | **MiniMax-M2.5** |
| Concurrent viewers observed | **9,974** |
| Total likes on single room | **3,600,608** |
| BGM tracks | **21** across 7 playlists |
| CoT fragments recovered | **15+** |
| Credentials extracted | **299** |
| URLs cataloged | **244** |
| JSON objects extracted | **108** |

### What It Is

OpenRoom presents as a "live AI character performance platform" — think **Twitch + The Sims
+ ChatGPT**. AI characters inhabit a virtual desktop operating system with 12 apps (Twitter,
Diary, Music Player, Email, Album, Evidence Vault, games). The characters autonomously
create social media posts, write diary entries, play music, change wallpapers, and stream
live performances to audiences of 10,000+ viewers with danmaku (bullet comments), gifts,
and real-time chat.

Under the hood, it is powered by **MiniMax/Hailuo AI** — one of China's leading AI companies.
The platform routes each user message to **5 parallel sub-agents**, each specialized for a
different app domain, coordinated through a proprietary tool-call protocol.

---

## 2. Brand Mapping (Definitive)

**One company, five+ brands.** Evidence from heap strings, CDN domains, Firebase projects,
WebSocket URLs, internal service names, and model output tags.

| Brand | Evidence | Role |
|-------|----------|------|
| **OpenRoom** | `www.openroom.ai`, `cdn.openroom.ai`, `connection.openroom.ai` | Consumer-facing web app |
| **Talkie** | Firebase project `talkie-e5d0e`, `cdn.talkie-ai.com`, `talkie.cdn.minimax.io` | Original/mobile brand |
| **XingyeAI** | `wss://connection.xingyeai.com/connection/ws` | Chinese-market WebSocket endpoint |
| **Xaminim** | `talkie-test.xaminim.com`, `xingye-test.xaminim.com`, `wapi-talkie-test.xaminim.com` | Test/staging domain (MiniMax spelled backwards) |
| **Gomerry** | Firebase project `gomerry-a677f` (secondary) | Secondary Firebase project |
| **MiniMax** | `<minimax:tool_call>` in model output, `talkie.cdn.minimax.io` CDN | Parent AI company |
| **Hailuo AI** | `data.hailuoai.video` reporting, `isHailuo` / `isHailuoOversea` flags, `hailuovideocn/X.X.X` version strings | Video AI brand (same parent company) |
| **OpenClaw** | Strategic text: "With OpenClaw and similar personal agents, we noticed that beyond getting work done, many users also want the model to have high emotional intelligence and character consistency." | AI agent product (same parent) |

### Evidence Chain

```
cdn.talkie-ai.com     ── same BGM files ──>  talkie.cdn.minimax.io
talkie-e5d0e          ── Firebase project ──> OpenRoom login
connection.xingyeai.com ─ same proto ──────> connection.openroom.ai
xaminim.com           ── test domain ──────> "MiniMax" reversed
data.hailuoai.video   ── reporting ────────> same meerkat-reporter as xaminim.com
<minimax:tool_call>   ── model output ─────> MiniMax-M2.5 model
```

---

## 3. Authentication & Credentials

### 3.1 Firebase Authentication

| Field | Value |
|-------|-------|
| Firebase Project | `talkie-e5d0e` |
| API Key 1 | `AIza_REDACTED` |
| API Key 2 | `AIza_REDACTED` |
| API Key 3 | `AIza_REDACTED` |
| Auth Provider | Google Sign-In (`securetoken.google.com/talkie-e5d0e`) |
| Token Type | RS256 JWT (Firebase ID Token) |

### 3.2 Weaver JWT (Primary API Auth)

| Field | Value |
|-------|-------|
| Algorithm | **HS256** (shared secret — security concern) |
| Issuer | `weaver_account` |
| `app_id` | `999` |
| `account_id` | `378675744182578` |
| `device_id` | `378675802251393` |
| `is_anonymous` | `false` |
| Expiry | **~100 days** from issue (extremely long-lived) |
| Delivery | Cookie (`auth_token`) or header (`x-token`) |

**JWT Payload (decoded):**
```json
{
  "app_id": 999,
  "account_id": 378675744182578,
  "device_id": 378675802251393,
  "is_anonymous": false,
  "iss": "weaver_account",
  "exp": 1782643185,
  "nbf": 1774003184
}
```

### 3.3 IM Account Cookie (CRITICAL)

The `root_im_account_info` cookie contains a **base64-encoded plaintext password**:

```json
{"account": "u___378675744182578", "password": "jKbrogJb4O"}
```

This is the instant messaging system credential stored as a browser cookie in cleartext.
Anyone with access to the browser (XSS, cookie theft, shared computer) gets the IM password.

### 3.4 Cookie Inventory

| Cookie | Purpose |
|--------|---------|
| `auth_token` | Primary Weaver JWT |
| `refresh_token` | Token refresh JWT |
| `user_id` | Numeric user ID (`378675744182578`) |
| `device_id` | UUID per device/browser |
| `uuid` | Alternate device identifier |
| `is_anonymous` | Registration status flag |
| `root_im_account_info` | **Plaintext IM credentials (!)** |
| `auth_check_flag` | Auth verification flag |

### 3.5 Guance RUM Tokens

| Token | Endpoint |
|-------|----------|
| `e3abd1d44458401296f85941b4292615` | `us1-rum-openway.guance.com/v1/write/rum` |
| `1dc1d95a8f384ffeaf478077cd8d5b04` | `us1-rum-openway.guance.com/v1/write/rum` |

Both tokens also used for `/v1/write/logging` and `/v1/write/rum/replay` endpoints.

---

## 4. Kubernetes Infrastructure

Heap strings reveal internal Kubernetes service discovery URLs — these should never be
visible to the client.

| Internal URL | Purpose |
|--------------|---------|
| `http://weaver-gateway-weaver-web.weaver.svc.cluster.local:8888` | **API Gateway** — routes all Weaver API traffic |
| `http://weaver-storage-gateway.weaver.svc.cluster.local:8080` | **Cloud NAS** — virtual filesystem storage backend |

### Infrastructure Map

```
K8s Namespace: weaver
├── weaver-gateway-weaver-web  :8888   (API gateway)
├── weaver-storage-gateway     :8080   (Cloud NAS / virtual filesystem)
└── (additional services behind gateway)

Test Infrastructure:
├── wapi-talkie-test.xaminim.com       (test API gateway)
├── talkie-test.xaminim.com            (test WebSocket)
├── xingye-test.xaminim.com            (test WebSocket, XingyeAI brand)
└── meerkat-prod.xaminim.com           (telemetry reporter)
```

### External Reporting Endpoints

| URL | Project |
|-----|---------|
| `https://data.hailuoai.com/meerkat-reporter/api/report?project=HailuoVideo` | Hailuo (Chinese domain) |
| `https://data.hailuoai.video/meerkat-reporter/api/report?project=HailuoVideo` | Hailuo (video domain) |
| `https://meerkat-prod.xaminim.com/meerkat-reporter/api/report?project=default` | MiniMax staging |

---

## 5. WebSocket Protocol

### 5.1 Endpoints (5 total)

| # | URL | Environment |
|---|-----|-------------|
| 1 | `wss://connection.openroom.ai/connection/ws` | **Production** (OpenRoom brand) |
| 2 | `wss://connection.talkie-ai.com/connection/ws` | **Production** (Talkie brand) |
| 3 | `wss://connection.xingyeai.com/connection/ws` | **Production** (XingyeAI brand, China) |
| 4 | `wss://talkie-test.xaminim.com/connection/ws` | **Test** (Talkie staging) |
| 5 | `wss://xingye-test.xaminim.com/connection/ws` | **Test** (XingyeAI staging) |

### 5.2 Connection Parameters

```
wss://connection.openroom.ai/connection/ws?os=3&token=<JWT>&device_id=<uuid>&app_id=999
```

| Param | Value | Description |
|-------|-------|-------------|
| `os` | `3` | Client platform (3 = web) |
| `token` | `<Weaver JWT>` | Authentication token |
| `device_id` | `<UUID>` | Device identifier |
| `app_id` | `999` | Application identifier |

### 5.3 Complete Proto3 Schema

Extracted directly from heap memory — this is the binary framing protocol for all
WebSocket communication:

```protobuf
syntax = "proto3";

enum Command {
  Unknown           = 0;
  MsgReceivedAck    = 1;
  LoginSuccess      = 2;
  Business          = 100;
  BusinessStreaming  = 101;
}

message Packet {
  Command cmd             = 1;
  int32   biz_type        = 2;
  string  trace_id        = 3;
  uint32  sid             = 4;
  int64   send_at         = 5;
  optional string user_id   = 6;
  optional string device_id = 7;
  bytes   payload         = 100;
}
```

### 5.4 Protocol Behavior

| Event | Description |
|-------|-------------|
| Connection | Client sends JWT in query param, server responds with `LoginSuccess` (cmd=2) |
| Heartbeat | 15-second ping/pong interval |
| Agent Narrative | `BusinessStreaming` (cmd=101) with JSON payload containing agent text chunks |
| App Actions | `Business` (cmd=100) with action results (e.g., file written, song played) |
| Ack | Client sends `MsgReceivedAck` (cmd=1) to confirm receipt |

The `payload` field (field 100) contains base64-encoded JSON with the actual message content.
Message types within the payload include `msg_type` values:
- `2` = narrative text chunk
- `3` = action result

---

## 6. Multi-Agent Architecture

### 6.1 The Five Agents

When a user sends a message, OpenRoom dispatches to **5 parallel sub-agents**, each
specialized for a different domain:

| Agent ID | Display Name | Role | App ID |
|----------|-------------|------|--------|
| `character_agent` | Character | Main dialogue, persona, emotional expression | N/A |
| `app_expert_1_os` | OS Expert | Desktop management, wallpapers, app launching | 1 |
| `app_expert_2_twitter` | Twitter Expert | In-character social media posts | 2 |
| `app_expert_3_musicPlayer` | Music Expert | BGM playback, playlist management | 3 |
| `app_expert_4_diary` | Diary Expert | Journal entries, mission boards | 4 |

### 6.2 Orchestration Flow

```
User sends message
        │
        ▼
   ┌─────────────┐
   │  Dispatcher  │
   └──────┬──────┘
          │
    ┌─────┼─────┬──────────┬──────────┐
    ▼     ▼     ▼          ▼          ▼
 char   os    twitter   music     diary
 agent  expert expert   expert    expert
    │     │     │          │          │
    ▼     ▼     ▼          ▼          ▼
 respond  SET_   CREATE_   PLAY_    CREATE_
 _to_user WALL   POST     SONG     ENTRY
    │     PAPER  │          │          │
    └─────┴──────┴──────────┴──────────┘
                    │
                    ▼
            WebSocket stream
            to all clients
```

### 6.3 Tool Call Protocol

The model uses a proprietary XML-based tool call format:

```xml
<minimax:tool_call>
  <invoke name="respond_to_user">
    <parameter name="character_expression">{
      "content": "(Vex pours three glasses of glowing synthohol...) This stuff's not cheap.",
      "emotion": "peaceful"
    }</parameter>
    <parameter name="user_interaction">{
      "suggested_replies": [
        "Tell me more about the old Sector 4.",
        "To surviving the night.",
        "You're both like family to me."
      ]
    }</parameter>
  </invoke>
</minimax:tool_call>
```

### 6.4 Tool Call Status Codes

| Code | Meaning |
|------|---------|
| `1` | Running (agent is processing) |
| `2` | Done (agent completed successfully) |
| `3` | Failed (agent encountered an error) |

### 6.5 `respond_to_user` Schema

The primary tool for character output:

```
respond_to_user
├── character_expression
│   ├── content: string     — Narrative text with action descriptions in parentheses
│   └── emotion: string     — One of: angry, depressing, happy, peaceful, shy
└── user_interaction
    └── suggested_replies: string[]  — 3 clickable reply options
```

### 6.6 Agent Tools Observed

Each agent has access to file system tools:

| Tool Status | Description |
|-------------|-------------|
| `Reading file...` | Agent reads a file from the virtual filesystem |
| `Writing into file...` | Agent writes content to a file |
| `Scanning directory tree...` | Agent lists directory contents |
| `Creating directory...` | Agent creates a new directory |
| `Operating os...` | Agent performs OS-level actions (wallpaper, app management) |
| `Character is thinking...` | Agent reasoning phase (visible to client) |

### 6.7 `system_prompt_map` Field

Discovered in heap — indicates per-agent system prompts are stored in a map keyed by
agent ID. Each agent receives a specialized system prompt defining its role, tools, and
behavioral guidelines.

---

## 7. Chain-of-Thought Analysis

### 7.1 The Leak

Because OpenRoom streams **text** (not voice), the model's internal chain-of-thought
reasoning persists in the V8 heap as string objects. Voice AI platforms (like Sesame)
leak zero CoT because the model runs server-side and only audio reaches the client.

**15+ fragments** of model reasoning were recovered from the 71MB and 101MB heap snapshots.

### 7.2 Example: The Vex/Nyx Character Switch

The most revealing fragment shows the model catching and correcting a character identity error:

```
The user is asking if they're safe in the apartment during the lockdown.
I need to respond as Aoi, but wait - looking at the system reminder,
this is a dual-character narrative with Vex and Nyx, not Aoi...

Let me re-read the context. The system reminder is telling me to roleplay
a dual-character narrative with Vex (tech-savvy, anxious net-runner) and
Nyx (stoic, street-smart courier)...
```

This reveals:
1. The model **initially confused** which character it was playing
2. It has access to a **system reminder** containing character definitions
3. It actively **re-reads context** to correct itself
4. Character personas include personality descriptors (anxious, stoic, street-smart)

### 7.3 Common CoT Patterns

| Pattern | Example | Frequency |
|---------|---------|-----------|
| User intent analysis | "The user is asking..." | High |
| Character identity check | "I need to respond as..." | High |
| Context re-reading | "Let me re-read the context..." | Medium |
| Task completion | "All tasks completed..." | Medium |
| Tool selection | "I should use [tool] to..." | Low |
| Emotion selection | "The mood here should be..." | Low |

### 7.4 Key Insight

> **Text AI leaks chain-of-thought. Voice AI does not.**
>
> This is a fundamental architectural difference. Streaming text to the client means
> every token the model generates — including reasoning tokens — passes through the
> browser's memory. Voice AI keeps all reasoning server-side and only sends audio.

The model is confirmed as **MiniMax-M2.5** based on the `<minimax:tool_call>` format
in the output and `stop_reason: "tool_use"` patterns.

---

## 8. Virtual Desktop OS — 12 Apps

### 8.1 Workspace Filesystem Tree

```
workspace/
├── workspace.json                        — Workspace configuration
├── mod/
│   └── mod.json                          — Story stage tracking (0/4, completion targets)
└── apps/
    ├── os/
    │   ├��─ guide.yaml                    — (87 lines) OS behavior guide
    │   ├── meta.yaml                     — (30 lines) Action schemas
    │   └── data/
    │       └── wallpaper/
    │           ├── list.json             — (79 lines) Available wallpapers
    │           └── state.json            — Current wallpaper state
    ├── twitter/
    │   ├── guide.yaml                    — (123 lines) Twitter behavior guide
    │   ├── meta.yaml                     — (57 lines) Post/like/comment schemas
    │   └── data/
    │       ├── state.json                — Feed state (50+ posts tracked)
    │       └── posts/
    │           ├── post_1774006442.json  — Individual post
    │           ├── post_1774006542.json
    │           └── sc-1 through sc-50    — 50+ character posts
    ├── musicPlayer/
    │   ├── guide.yaml
    │   ├── meta.yaml                     — (141 lines) Playback schemas
    │   └── data/
    │       ├─��� state.json                — Current playback state
    │       ├── songs/
    ��       │   ├── song-125.json
    │       │   ├── song-129.json
    │       │   ├── song-162.json
    ��       │   ├── song-174.json
    │       │   ├── song-185.json
    │       ��   ├── song-389.json
    │       │   ├── song-392.json
    │       │   ├── song-505.json
    │       │   ├── song-524.json
    │       │   ├── song-743.json
    │       │   ├── song-761.json
    │       │   ├── song-803.json
    │       │   ├── song-822.json
    │       │   ├── song-838.json
    │       │   ├── song-1119.json
    │       │   └── song-1538.json        — 16+ songs
    │       └── playlists/
    │           ├── playlist-ambient.json
    │           ├── playlist-horror.json
    │           ├── playlist-lyrical.json
    │           ├── playlist-playful.json
    │           ├── playlist-suspense.json
    │           ├── playlist-tension.json
    │           └── playlist-urban chill.json  — 7 mood playlists
    ├── diary/
    │   ├── guide.yaml
    │   ├── meta.yaml                     — (49 lines) Entry schemas
    │   └── data/
    │       ├── state.json
    │       └── entries/
    │           └── 1774006529289-a1b2c3.json  — 15+ diary entries
    ├── email/
    │   ├── guide.yaml
    │   ├── meta.yaml
    │   ��── data/
    │       └── emails/
    │           ├── protocol-zero-email.json
    │           ├── ghost-*.json
    │           ├── job-*.json
    │           ├── quarantine-*.json
    │           └── safety-*.json
    ├── album/
    │   ├── guide.yaml
    │   └── meta.yaml
    ├── evidencevault/
    │   ├── guide.yaml
    │   └── meta.yaml
    ├── chatroom/
    │   ├── guide.yaml
    │   ├── meta.yaml
    │   └── data/
    │       └── 0/
    │           └── scripts/              — Live stream scripts, gift configs
    ├── freecell/                         — Card game app
    ├── gomoku/                           — Five-in-a-row board game
    └── chess/                            — Chess game
```

### 8.2 Complete App Registry

#### Utility Apps (8)

| App ID | Name | Description | Schema URL |
|--------|------|-------------|------------|
| 1 | **OS** | Desktop OS — wallpaper, app launcher, window management | `/webuiapps/os` |
| 2 | **Twitter** | Social media — post, like, comment, hashtags | `/webuiapps/twitter` |
| 3 | **Music Player** | Songs, playlists, play/pause/volume control | `/webuiapps/musicPlayer` |
| 4 | **Diary** | Journal entries with dates, moods, weather tags | `/webuiapps/diary` |
| 8 | **Album** | Image browser (pre-stored, read-only) | `/webuiapps/album` |
| 11 | **Email** | Inbox with read/star/delete (agent composes) | `/webuiapps/email` |
| 13 | **Evidence Vault** | Archive display (read-only evidence system) | `/webuiapps/evidencevault` |
| 100 | **Chatroom** | Live streaming with scripts, danmaku, gifts | `/webuiapps/chatroom` |

#### Game Apps (4)

| App | Type | Schema URL |
|-----|------|------------|
| **Freecell** | Card game (solitaire variant) | `/webuiapps/freecell` |
| **Gomoku** | Five-in-a-row board game | `/webuiapps/gomoku` |
| **Chess** | Chess game | `/webuiapps/chess` |
| **Home** | App launcher / home screen | (integrated with OS) |

### 8.3 Action Schemas (from meta.yaml)

| App | Actions | Key Parameters |
|-----|---------|----------------|
| **OS** (id:1) | `OPEN_APP`, `CLOSE_APP`, `SET_WALLPAPER` | `app_id` (string), `wallpaper_url` (from list.json) |
| **Twitter** (id:2) | `CREATE_POST`, `DELETE_POST` | `filePath` (e.g., `/posts/post_1774006542.json`) |
| **Music Player** (id:3) | `PLAY_SONG`, `PAUSE`, `SET_VOLUME` | `songId` (e.g., `song-803`), `volume` (e.g., `0.215`) |
| **Diary** (id:4) | `CREATE_ENTRY`, `UPDATE_ENTRY` | `filePath` (e.g., `/entries/1774006529289-a1b2c3.json`) |
| **Email** (id:11) | `READ_EMAIL`, `STAR_EMAIL`, `DELETE_EMAIL` | `emailId` |
| **Album** (id:8) | (read-only browse) | — |
| **Evidence Vault** (id:13) | (read-only browse) | — |
| **Chatroom** (id:100) | (live stream control) | — |

### 8.4 Cloud NAS Storage

All app data is persisted via the **Weaver Storage Gateway** (`weaver-storage-gateway.weaver.svc.cluster.local:8080`). Three core operations:

| Operation | Observed Calls/Session | Purpose |
|-----------|----------------------|---------|
| `list_files` | ~30 | Directory listing (type: 0=file, 1=dir) |
| `get_file` | **~75** | Read file content |
| `put_text_files_by_json` | ~22 | Write/update files (batch capable) |

### 8.5 Iframe Architecture

Apps run as **iframes** within the virtual desktop shell. Cross-frame communication uses
`ParentComManager` — a message-passing bridge that:

1. Receives agent actions from the WebSocket stream
2. Routes them to the correct app iframe via `postMessage`
3. Collects action results from app iframes
4. Reports results back to the server via `report_os_event`

---

## 9. Weaver API Surface

All endpoints use `POST` with `Content-Type: application/json`. Authentication via
JWT cookie (`auth_token`) or header (`x-token`).

### 9.1 Character & Chat Endpoints

| Endpoint | Path | Key Parameters |
|----------|------|----------------|
| **Start Session** | `/weaver/api/v1/character/start_session` | `mod_id`, `character_id` |
| **Send Message** | `/weaver/api/v1/character/send_msg` | `text`, `session_id`, `model` |
| **Get Chat History** | `/weaver/api/v1/character/get_chat_history` | `session_id`, `cursor`, `size`, `is_asc`, `start_time`, `end_time` |
| **List Sessions** | `/weaver/api/v1/character/list_sessions` | `size` |
| **Get Mod List** | `/weaver/api/v1/character/get_mod_list` | `{}` |
| **Get App List** | `/weaver/api/v1/character/get_app_list` | `mod_id`, `session_id` |
| **Report OS Event** | `/weaver/api/v1/character/report_os_event` | `session_id`, `model`, `os_events[]` |
| **Query Credits** | `/weaver/api/v1/character/query_credits` | `{}` |

### 9.2 Conversation Endpoints (from heap)

| Endpoint | Path | Source |
|----------|------|--------|
| **Query Sorted Conversations** | `/weaver/api/v1/conversation/page_query_sorted_conversation` | heap |
| **Query All Messages** | `/weaver/api/v1/conversation/page_query_all_message` | heap |
| **Restart Conversation** | `/weaver/api/v1/conversation/restart_conversation` | heap |
| **Delete Conversation** | `/weaver/api/v1/conversation/delete_conversation` | heap |
| **Accept Message** | `/weaver/api/v1/conversation/accept_msg` | heap |

### 9.3 Chatroom Endpoints

| Endpoint | Path | Key Parameters |
|----------|------|----------------|
| **List Rooms** | `/weaver/api/v1/chatroom/room/list` | `limit` |
| **Get Chatroom Info** | `/weaver/api/v1/chatroom/get_chatroom_info` | `room_id`, `media_cursor` |
| **List Messages** | `/weaver/api/v1/chatroom/message/list` | `room_id`, `type`, `limit` |
| **List Comments** | `/weaver/api/v1/chatroom/comment/list` | `room_id`, `sort`, `limit`, `page` |

### 9.4 Connection & Account Endpoints

| Endpoint | Path | Source |
|----------|------|--------|
| **Poll Message** | `/weaver/api/v1/connection/poll_message` | heap |
| **Get User Status** | `/weaver/api/v1/account/get_user_status` | HAR |
| **Report Events** | `/weaver/api/v1/event/report` | HAR |

### 9.5 Storage Endpoints (Virtual Filesystem)

| Endpoint | Path | Key Parameters |
|----------|------|----------------|
| **List Files** | `/weaver_storage/api/v1/storage/list_files` | `path`, `session_id` |
| **Get File** | `/weaver_storage/api/v1/storage/get_file` | `session_id`, `file_path` |
| **Write Files** | `/weaver_storage/api/v1/storage/put_text_files_by_json` | `files[]`, `session_id` |
| **Delete Files** | `/weaver_storage/api/v1/storage/delete_files_by_paths` | `file_paths[]`, `session_id` |

### 9.6 UGC / Mod Creation Endpoints

| Endpoint | Path | Key Parameters |
|----------|------|----------------|
| **Create Mod** | `/ugc/api/mod/create` | `mod`, `author_id`, `published` |
| **Generate Mod** | `/ugc/api/mod/generate` | `description`, `system_prompt` |
| **Default System Prompt** | `/ugc/api/mod/default-system-prompt` | `{}` |
| **Mod Generator Page** | `/ugc/mod/gen?user_id={id}` | `user_id` |

### 9.7 Credits / Payment Endpoints (from heap)

| RPC Name | Purpose |
|----------|---------|
| `credits/fetchBalance` | Check credit balance |
| `credits/fetchProductList` | List purchasable credit packs |
| `credits/fetchHistory` | Transaction history |
| `credits/createPreOrder` | Initiate purchase |
| `credits/fetchOrderStatus` | Check order completion |

---

## 10. Characters

### 10.1 Named Characters

| Character | Description | Discovered Via |
|-----------|-------------|----------------|
| **Jill** | Bartender — "permanent dark circles and a sharp tongue, pouring drinks in a dying city at 3 AM" | heap strings, character art CDN |
| **Aoi** | AI VTuber bounty hunter — "streaming alone at 3 AM, running on borrowed time", silver-haired | chatroom API, character art CDN |
| **Vex** | Tech-savvy, anxious net-runner — blue hair, Sector 4 resident | CoT fragments, agent messages |
| **Nyx** | Stoic, street-smart courier — cybernetic hand, stoic face | CoT fragments, agent messages |
| **Rea** | Silver-haired drifter — "woke up from 80 years of cryo with no memories" | agent messages, character art CDN |

### 10.2 Character Emotion Video Map

Each character has pre-rendered video segments mapped to emotions:

```json
{
  "angry":      ["angry_0.mp4", "angry_1.mp4"],
  "depressing": ["depression_0.mp4", "depression_1.mp4"],
  "happy":      ["happy_0.mp4", "happy_1.mp4"],
  "peaceful":   ["peaceful_0.mp4", "peaceful_1.mp4"],
  "shy":        ["shy_0.mp4", "shy_1.mp4"]
}
```

CDN pattern: `cdn.openroom.ai/public-cdn-s3-us-west-2/talkie-op-img/{id}_{timestamp}_{emotion}_{variant}.mp4`

Two separate character emotion sets found (different CDN timestamps = different characters):
- Character A (Vex/Nyx mod): timestamps `1770889821xxx`
- Character B (Rea/Silver-haired): timestamps `1770889350xxx`

### 10.3 Character Art Assets

| Asset Type | URL Pattern | Example |
|------------|-------------|---------|
| Front View | `CharacterXViewFront.png` | `CharacterAoiViewFront.png`, `CharacterReaViewFront.png`, `CharacterJillViewFront.png` |
| Back View | `CharacterXViewback.png` | `CharacterAoiViewback.png`, `CharacterJillViewback.png` |
| Side View | `CharacterXViewside.png` | `CharacterReaViewside.png` |
| Head Shot | `head_img_url.png` | Multiple versions per character |
| Avatar | `avatar_img_url.png` | Multiple versions per character |
| Chat Pic | `chat_pic_url.png` | In-chat character image |

### 10.4 UGC Mod Creation

User-generated character mods are created via:
```
https://www.openroom.ai/ugc/mod/gen?user_id=378675744182578
```

The creation pipeline generates:
1. `name` + `identifier` (snake_case)
2. `description` — detailed AI agent directive with setting and dynamics
3. `display_desc` — user-facing atmospheric description
4. `prologue` — character's opening message
5. `opening_rec_replies` — 3 clickable starter replies
6. `stages` — 3-5 stages with targets and app integration instructions

---

## 11. Live Stream (VTuber) System

### 11.1 Scripted Stage Progression

Live streams follow a scripted narrative with measurable stage targets:

```json
{
  "stage_progress": {
    "completed_stage": {
      "index": 0,
      "name": "Lockdown Initiated"
    },
    "total_stages_count": 4,
    "all_stages_finished": false,
    "next_stage": {
      "index": 1,
      "name": "The Long Wait"
    }
  }
}
```

**4-Stage Example (Vex/Nyx Mod):**

| Stage | Name | Description |
|-------|------|-------------|
| 0 | **Lockdown Initiated** | Opening scenario, character introductions |
| 1 | **The Long Wait** | Mid-story tension building |
| 2 | **Signal to Noise** | Investigation / action phase |
| 3 | **Offline Mode** | Resolution / conclusion |

### 11.2 Script Types Per Stage

Each stage contains multiple script categories:

| Script Type | Purpose |
|-------------|---------|
| `chat_messages` | Scripted AI character dialogue |
| `danmaku` | Scripted bullet comments (appear as viewer messages) |
| `gifts` | Scripted gift events |
| `likes` | Scripted like surges |
| `streamer` | Streamer behavior instructions |
| `videos` | Video segment playlist |

### 11.3 Video Segment Types

| Segment ID | Description |
|------------|-------------|
| `S_Talk_Happy_2` | Character talking with happy emotion |
| `S_Talk_Normal_A_1` | Character talking with neutral emotion |
| `S_Func_Dancing_0` | Character performing dance animation |
| `S_Func_Dancing_1` | Character performing dance animation (alt) |
| `S_Func_Thinking_0` | Character in thinking pose |
| `S_Idle_Look_1` | Character idle / looking around |

### 11.4 Gift System

| Gift | Image |
|------|-------|
| Crayfish | `gift-crayfish.png` |
| Heart | `gift-heart.png` |
| Rose | `gift-rose.png` |
| Star | `gift-star.png` |

### 11.5 Chinese Danmaku Examples

The danmaku system includes Chinese-language examples, confirming the platform's Chinese
market origins:

```json
{"id": "dm-1", "username": "森林守望者", "content": "小红帽加油！我们陪你找妈妈", "userType": "other"}
```

Translation: "Little Red Riding Hood, keep going! We're with you to find your mom!"

### 11.6 Chatroom Stats (Room 5050 — Aoi)

| Metric | Value |
|--------|-------|
| Concurrent viewers | **9,974** |
| Total likes | **3,600,608** |
| Total comments | **284,110** |
| BGM tracks active | 3 |
| Rooms scanned (5045–5059) | 15 accessible, 1 active |

### 11.7 Livestream Feature Events

```
os_livestream_add_agent
os_livestream_gift_send
os_livestream_stage_index
os_livestream_next_stage
os_livestream_play_voice
os_livestream_task_completed
send_agent_message
receive_agent_message
```

---

## 12. Music / Audio System

### 12.1 TTS (Text-to-Speech)

| Field | Value |
|-------|-------|
| CDN Pattern | `cdn.openroom.ai/tts_audio/chat/{YYYYMMDD}/{timestamp}-{random}.mp3` |
| Delivery | Per-message audio URLs in chatroom `media_info.items` |
| Fallback | Google Translate TTS: `translate-pa.googleapis.com/v1/textToSpeech` |
| Languages | `translate-pa.googleapis.com/v1/supportedLanguages` |

### 12.2 BGM (Background Music)

**21 tracks** served from dual CDN:

| CDN | URL Pattern |
|-----|-------------|
| Primary | `cdn.talkie-ai.com/npc_bgm/music{N}.mp3` |
| MiniMax CDN | `talkie.cdn.minimax.io/npc_bgm/music{N}.mp3` |

These serve the **same files** — further confirming Talkie = MiniMax.

### 12.3 Playlists (7 moods)

| Playlist | Mood | Use Case |
|----------|------|----------|
| `playlist-ambient.json` | Ambient | Background atmosphere |
| `playlist-horror.json` | Horror | Thriller/mystery scenes |
| `playlist-lyrical.json` | Lyrical | Emotional/romantic moments |
| `playlist-playful.json` | Playful | Light/fun interactions |
| `playlist-suspense.json` | Suspense | Tension building |
| `playlist-tension.json` | Tension | High-stakes scenes |
| `playlist-urban chill.json` | Urban Chill | Default cyberpunk vibe |

### 12.4 Custom Tracks (from CDN)

| Track | CDN Path |
|-------|----------|
| Cybertipsy | `talkie-op-img/1317732845_1771762012928_Cybertipsy.mp3` |
| NeonSmokeSyncopation | `talkie-op-img/1481527607_1771762015707_NeonSmokeSyncopation.mp3` |
| LivingRoomLevels | `talkie-op-img/712717380_1771762009141_LivingRoomLevels.mp3` |

---

## 13. Monetization

### 13.1 Credits System

| Field | Details |
|-------|---------|
| Currency | Credits (virtual tokens) |
| Error | "You don't have enough credits for this conversation." |
| Expiry | **2 years** from purchase |
| Transferable | No |
| Refundable | No |
| Fast Track | Requires active subscription |

### 13.2 Payment Events

| Event | Description |
|-------|-------------|
| `os_credits_payment_success` | Purchase completed |
| `os_credits_payment_failed` | Purchase failed |
| `os_credits_payment_canceled` | User canceled |
| `os_credits_payment_refunded` | Refund processed |
| `os_credits_payment_timeout` | Purchase timed out |

### 13.3 Subscription Events

| Event | Platform |
|-------|----------|
| `app_store_subscription_convert` | App Store — new subscription |
| `app_store_subscription_renew` | App Store — renewal |
| `in_app_purchase` | Generic in-app purchase |
| `purchase` | Generic purchase event |

### 13.4 Revenue Tracking

| Event | Type |
|-------|------|
| `Ad_Impression_Revenue` | Ad revenue tracking |
| `Total_Ads_Revenue_001` | Aggregate ad revenue |
| `ad_impression` | Individual ad impression |

### 13.5 Order Error

```
"Failed to create order. Please try again."
```

Payment terms: `https://www.openroom.ai/doc/payment-terms.html`

---

## 14. CDN Architecture

### 14.1 Domain Inventory

| Domain | Purpose | Technology |
|--------|---------|------------|
| `cdn.openroom.ai` | **Primary CDN** — images, TTS audio, avatars, character art, emotion videos, wallpapers | Alibaba Cloud OSS |
| `cdn.talkie-ai.com` | **Secondary CDN** — BGM music, webui app bundles | Alibaba Cloud OSS |
| `talkie.cdn.minimax.io` | **MiniMax CDN** — same BGM files as talkie-ai.com | MiniMax infrastructure |

### 14.2 CDN Path Structure

| Content Type | Pattern | Example |
|-------------|---------|---------|
| TTS Audio | `/tts_audio/chat/{date}/{id}.mp3` | `/tts_audio/chat/20260325/1774398604-abc123.mp3` |
| Character Art | `/public-cdn-s3-us-west-2/talkie-op-img/image/{id}_{ts}_{name}.png` | `CharacterAoiViewFront.png` |
| Emotion Video | `/public-cdn-s3-us-west-2/talkie-op-img/{id}_{ts}_{emotion}_{n}.mp4` | `happy_0.mp4` |
| Livestream Video | `/public-cdn-s3-us-west-2/talkie-op-img/{id}_{ts}_{segment}.mp4` | `S_Func_Dancing_0.mp4` |
| BGM Music | `/npc_bgm/music{N}.mp3` | `/npc_bgm/music1.mp3` through `music21.mp3` |
| Wallpapers | `/public-cdn-s3-us-west-2/talkie-op-img/image/{id}_{ts}_{name}.jpg` | `inverted_city.jpg`, `Flow.jpg` |
| AI-Generated Images | `/image_inference_output/talkie/prod/img/{date}/{uuid}.jpeg` | Alibaba OSS processed |
| User Avatars | `/talkie-user-img/{user_id}/a/{hash}=s96-c-100.jpeg` | Google profile photo proxy |
| Web App Bundle | `/public-cdn-s3-us-west-2/gui-web/_next/static/...` | Next.js static assets |

### 14.3 Image Processing

Alibaba Cloud OSS image processing parameters:
```
?x-oss-process=image/resize,w_256,h_256/quality,q_80
?x-oss-process=image/resize,w_512/format,webp
```

---

## 15. Observability

### 15.1 Guance Real User Monitoring (RUM)

| Field | Value |
|-------|-------|
| SDK | `df_web_rum_sdk` **v3.2.32** |
| Application | `gui_web` |
| Endpoint | `us1-rum-openway.guance.com` |
| Token 1 | `e3abd1d44458401296f85941b4292615` |
| Token 2 | `1dc1d95a8f384ffeaf478077cd8d5b04` |
| Protocol | InfluxDB line protocol (not JSON) |

**Metrics collected:**
- FCP (First Contentful Paint)
- LCP (Largest Contentful Paint)
- CLS (Cumulative Layout Shift)
- INP (Interaction to Next Paint)
- TTFB (Time to First Byte)
- Long task duration
- DOM metrics (nodes, depth)
- Session replay recordings

**Endpoints used:**
- `/v1/write/rum` — core Web Vitals metrics
- `/v1/write/logging` — client-side error logs
- `/v1/write/rum/replay` — session replay data

### 15.2 Sentry Error Tracking

Multiple Sentry debug IDs found across JS bundles, indicating source-map-enabled
error tracking in production.

### 15.3 Firebase Analytics (GA4)

| Field | Value |
|-------|-------|
| Measurement ID | `G-3ME46BPC5M` |
| Events tracked | `session_start`, `first_open`, `purchase`, `in_app_purchase`, `ad_impression` |
| FCM events | `fcm_message_send_new{1,5,10,50,100,250}` (push notification tiers) |
| Cookie | `_ga_3ME46BPC5M` |

### 15.4 Hailuo Video Reporting

| Endpoint | Project |
|----------|---------|
| `data.hailuoai.video/meerkat-reporter/api/report` | `HailuoVideo` |
| `data.hailuoai.com/meerkat-reporter/api/report` | `HailuoVideo` |
| `meerkat-prod.xaminim.com/meerkat-reporter/api/report` | `default` |

Flags in codebase: `isHailuo`, `isHailuoOversea`
Version strings: `hailuovideocn/X.X.X`, `hailuovideo/X.X.X`

### 15.5 Firebase Logging

| Endpoint | Purpose |
|----------|---------|
| `firebaselogging-pa.googleapis.com/v1/firelog/legacy/log` | Legacy Firebase logging |
| `firebaselogging.googleapis.com/v0cc/log?format=json_proto` | Structured Firebase logging |

---

## 16. Security Assessment

### 16.1 HIGH Severity

| Finding | Impact | Details |
|---------|--------|---------|
| **Plaintext IM password in cookie** | Account takeover | `root_im_account_info` cookie contains `{"account":"u___378675744182578","password":"jKbrogJb4O"}` in base64. XSS, cookie theft, or shared computer access yields full IM credentials. |

### 16.2 MEDIUM Severity

| Finding | Impact | Details |
|---------|--------|---------|
| **K8s internal URLs exposed** | Infrastructure reconnaissance | `weaver-gateway-weaver-web.weaver.svc.cluster.local:8888` and `weaver-storage-gateway.weaver.svc.cluster.local:8080` reveal namespace structure, service names, and ports. |
| **WebSocket JWT in URL params** | Token leakage | JWT passed as `?token=<JWT>` in WebSocket URL — appears in server access logs, browser history, proxy logs, and referrer headers. |
| **Full chain-of-thought leaked** | Model/prompt exposure | 15+ reasoning fragments in heap memory expose model behavior, system prompts, character switching logic, and tool selection reasoning. |
| **HS256 JWT with 100-day expiry** | Long-lived token risk | Shared-secret HMAC means server and all token holders share the same signing key. 100-day expiry makes stolen tokens dangerous for extended periods. |

### 16.3 LOW Severity

| Finding | Impact | Details |
|---------|--------|---------|
| **MiniMax model name exposed** | Competitive intelligence | `<minimax:tool_call>` in output confirms the backing model is MiniMax-M2.5, not a proprietary model. |
| **Multi-brand infrastructure revealed** | Competitive intelligence | Heap strings confirm OpenRoom = Talkie = XingyeAI = MiniMax = Hailuo AI — all one company. |
| **3 Firebase API keys exposed** | Limited (public keys) | Firebase API keys are technically public, but presence confirms Firebase project ID and enables enumeration. |

### 16.4 INFO

| Finding | Details |
|---------|---------|
| Hailuo Video reporting endpoints | `data.hailuoai.video` and `data.hailuoai.com` confirm video AI brand connection |
| Full user profile in heap | User ID, device ID, email, Google profile photo, account creation timestamp |
| App version `46.0.0` | Production deployment version visible in heap |
| Environment `production` | `__ENV__: "production"` confirms production deployment |
| Contact email | `official@openroom.ai` |
| Social media | `x.com/openroom_AI_` |

---

## 17. Methodology

### 17.1 Capture Summary

| Capture | Type | Size | Key Findings |
|---------|------|------|--------------|
| Heap 1 (Mar 20) | `.heapsnapshot` | 50.2 MB | Firebase keys, Weaver JWTs, initial API surface |
| Heap 2 (Mar 25, newest) | `.heapsnapshot` | 77.5 MB | Updated JWTs, new UUIDs, same credential set |
| Heap 3 (Mar 25, mod page) | `.heapsnapshot` | 46.3 MB | Protobuf in context, mod creation flow |
| Deep Parse 1 | V8 graph walk | 71 MB source | Agent messages, CoT fragments, app schemas |
| Deep Parse 2 | V8 graph walk | 101 MB source | Additional agents, 12 apps, BGM library, credits |
| HAR 1-4 (chatroom) | Traffic capture | 51MB—341MB | Chatroom API, danmaku, live video segments |
| HAR 5-6 (newest) | Traffic capture | 441MB—502MB | Full session with storage API, OS events |
| HAR 7 (newest3) | Traffic capture | 36 MB | Mod creation flow |

### 17.2 Analysis Techniques

| Technique | Tool | What It Found |
|-----------|------|---------------|
| Regex mining | `mine_heap()` (100+ patterns) | Firebase keys, JWTs, emails, UUIDs, API paths |
| V8 graph walk | `mine_heap_deep()` (ijson streaming) | JSON objects, agent messages, character data |
| JWT decoding | `decode_jwts_from_findings()` | Weaver account IDs, expiry, Firebase user IDs |
| Agent reconstruction | `extract_agent_messages()` | Multi-agent orchestration trace |
| CoT extraction | `extract_chain_of_thought()` | 15+ reasoning fragments |
| App schema parsing | `extract_app_schemas()` | Tool definitions from meta.yaml configs |
| Protobuf extraction | `extract_protobuf_definitions()` | Complete proto3 Packet schema |
| Heap diffing | `heap_diffing.py` | 20 new URLs, 119 new RPC IDs, 9 new configs between Mar 20 and Mar 25 |
| HAR analysis | ARGUS HAR analyzer | Full API endpoint catalog with request/response bodies |

### 17.3 Total Extraction

| Category | Count |
|----------|-------|
| Credentials | **299** |
| URLs | **244** |
| JSON objects | **108** |
| Character data entries | **121** |
| Internal K8s services | **8** |
| WebSocket URLs | **5** |
| API paths | **22** |
| Sub-agents | **5** |
| Apps | **12** |
| Protobuf schemas | **1** (complete) |
| CoT fragments | **15+** |
| BGM tracks | **21** |
| Livestream stages | **4** |
| Emotion video variants | **10** |
| Character art assets | **20+** |

### 17.4 Limitations

- No server-side code access — all findings are from client-side artifacts
- WebSocket payloads not fully decoded (protobuf binary, only schema extracted)
- Credits API not exercised (would require token refresh)
- Game apps (freecell, gomoku, chess) not deeply explored — only URLs confirmed
- Test/staging environments not probed (xaminim.com endpoints)

---

```
 ╔══════════════════════════════════════════════════════════════════════╗
 ║                                                                      ║
 ║  Report generated by ARGUS Intelligence Platform                     ║
 ║  CosySim v1.52.1 [2026-03-26]                                      ║
 ║                                                                      ║
 ║  "The heap remembers everything the UI tries to forget."            ║
 ║                                                                      ║
 ╚══════════════════════════════════════════════════════════════════════╝
```
