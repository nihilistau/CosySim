# ARGUS Methodology Guide

> CosySim Documentation -- v1.52.0 [2026-03-26]
>
> Reusable reconnaissance techniques for any web application.
> Distilled from the Sesame AI and OpenRoom.ai explorations.

---

## Table of Contents

1. [Overview](#overview)
2. [HAR Analysis](#1-har-analysis)
3. [Heap Snapshot Analysis](#2-heap-snapshot-analysis)
4. [Bundle Decompilation](#3-bundle-decompilation)
5. [Feature Flag Manipulation](#4-feature-flag-manipulation)
6. [CDP Scripting](#5-cdp-scripting)
7. [WebSocket Protocol Analysis](#6-websocket-protocol-analysis)
8. [Token Management](#7-token-management)
9. [Profile CRUD Testing](#8-profile-crud-testing)
10. [Environment Mapping](#9-environment-mapping)
11. [Security Assessment Checklist](#10-security-assessment-checklist)
12. [ARGUS CLI Quick Reference](#argus-cli-quick-reference)
13. [Cross-References](#cross-references)
14. [Change Log](#change-log)

---

## Overview

ARGUS (Automated Reconnaissance & General-purpose Universal Surveyor) is CosySim's
intelligence platform for mapping undocumented web APIs. Over 370+ sessions, we have
refined a repeatable methodology that works against any web application -- from
Google's internal batchexecute services to startup WebSocket APIs to Chinese social
platforms with custom RPC.

This guide documents every technique as a step-by-step playbook. Each section
includes the theory, the ARGUS tooling, concrete code examples, and lessons learned
from real operations.

**Prerequisites:**

- Python 3.11+ with `requests`, `websockets`, `beautifulsoup4`
- Chrome running with `--remote-debugging-port=9223`
- CosySim repo (for ARGUS tools): `scripts/argus/`
- Optional: Playwright, tshark, jq

**Philosophy:** Capture everything, decode offline. Never modify live state until
you have fully mapped the surface. The recon phase is sacred -- observe before you
interact.

---

## 1. HAR Analysis

HAR (HTTP Archive) files are the single richest intelligence source. One browsing
session captures every request/response pair, headers, cookies, timing, and
payload bodies. ARGUS starts every engagement here.

### 1.1 Capturing Traffic

**Chrome DevTools (manual):**

1. Open DevTools (F12) -> Network tab
2. Check "Preserve log" to survive navigations
3. Use the target app normally -- trigger every feature you can find
4. Right-click the request list -> "Save all as HAR with content"

**Programmatic (CDP):**

```python
# scripts/argus/network_monitor.py captures all traffic via CDP
from scripts.argus.network_monitor import NetworkMonitor

monitor = NetworkMonitor()
await monitor.start()
# ... user interaction happens ...
traffic = await monitor.drain()
for req in traffic:
    print(f"{req.method} {req.url} -> {req.response_status}")
await monitor.stop()
```

**Tips:**
- Capture multiple sessions (logged-out, logged-in, different accounts)
- Export separate HARs for each user role to diff permissions
- HAR files can be 10-50 MB -- ARGUS handles them efficiently via streaming

### 1.2 Extracting Endpoints

ARGUS auto-detects protocol types and groups endpoints by service:

```bash
python -m scripts.argus.analyze har path/to/capture.har
```

The `HARAnalyzer` (in `scripts/argus/analyzers/har_analyzer.py`) extracts:

| Category | What It Finds |
|----------|---------------|
| **Endpoints** | Every unique URL, grouped by domain and path pattern |
| **Auth schemes** | Bearer tokens, API keys, cookies, SAPISIDHASH, Basic auth |
| **Protocols** | REST, GraphQL, gRPC-web, batchexecute, WebSocket upgrade |
| **Tokens** | JWTs (decoded payload), API keys (pattern-matched), refresh tokens |
| **Rate limits** | `X-RateLimit-*` headers, `Retry-After`, 429 responses |
| **Cookies** | Session cookies with domain, expiry, secure/httpOnly flags |
| **GraphQL** | Operation names, query strings, variable schemas |

### 1.3 Comparing HAR Files

Diff two sessions to find what changed -- new user vs admin, before/after an action:

```bash
python -m scripts.argus.analyze compare session_a.har session_b.har
```

This reveals:
- Endpoints that only appear for authenticated users
- Additional headers sent by admin accounts
- New cookies set after login
- Rate limit changes between user tiers

### 1.4 Token Extraction from HAR

```python
import json
from pathlib import Path

def extract_bearer_tokens(har_path: Path) -> list[str]:
    """Pull all Bearer tokens from a HAR file."""
    har = json.loads(har_path.read_text(errors="replace"))
    tokens = []
    for entry in har["log"]["entries"]:
        for header in entry["request"]["headers"]:
            if header["name"].lower() == "authorization":
                val = header["value"]
                if val.startswith("Bearer "):
                    tokens.append(val[7:])
    return list(set(tokens))

def extract_refresh_tokens(har_path: Path) -> list[str]:
    """Pull refresh_tokens from Firebase securetoken calls."""
    har = json.loads(har_path.read_text(errors="replace"))
    refresh_tokens = []
    for entry in har["log"]["entries"]:
        url = entry["request"]["url"]
        if "securetoken.googleapis.com" in url:
            post = entry["request"].get("postData", {}).get("text", "")
            if "refresh_token" in post:
                parts = dict(x.split("=", 1) for x in post.split("&") if "=" in x)
                if "refresh_token" in parts:
                    refresh_tokens.append(parts["refresh_token"])
    return refresh_tokens
```

### 1.5 Batch Directory Analysis

When you have multiple HAR files from different sessions:

```bash
python -m scripts.argus.analyze dir path/to/har_folder/ --pattern "*.har"
```

### 1.6 Intelligence Report Generation

Generate a formatted Markdown report from any HAR:

```bash
python -m scripts.argus.analyze har capture.har --report
```

This produces a structured intelligence document with endpoint tables, auth
scheme summaries, and protocol breakdowns.

---

## 2. Heap Snapshot Analysis

V8 heap snapshots contain every string the JavaScript runtime has interned --
including API URLs, method names, configuration values, RPC IDs, and secrets that
never appear in network traffic.

### 2.1 Capturing Heap Snapshots

**Chrome DevTools (manual):**

1. Open DevTools -> Memory tab
2. Select "Heap snapshot" and click "Take snapshot"
3. Right-click the snapshot -> "Save" (.heapsnapshot file)

**Best practice:** Take two snapshots -- before and after an action -- to isolate
strings introduced by that action.

**CDP (programmatic):**

```python
from scripts.argus.cdp_bridge import CDPBridge

bridge = CDPBridge()
await bridge.connect()
session = await bridge.get_session_for_url("app.sesame.com")
await session.send("HeapProfiler.enable")

# Take snapshot -- returns chunks that form a JSON file
chunks = []
session.on("HeapProfiler.addHeapSnapshotChunk", lambda p: chunks.append(p["chunk"]))
await session.send("HeapProfiler.takeHeapSnapshot", {"reportProgress": False})
snapshot_json = "".join(chunks)
```

### 2.2 Extracting Strings

ARGUS parses the V8 heap format and classifies every string:

```bash
python -m scripts.argus.analyze heap snapshot.heapsnapshot
```

The `HeapAnalyzer` (in `scripts/argus/analyzers/heap_analyzer.py`) classifies
strings into:

| Category | Pattern | Example |
|----------|---------|---------|
| **URLs** | `https?://...` | `https://sesameai.app/agent-service-0/v1/connect` |
| **API endpoints** | `/api/`, `/v1/`, `/$rpc/`, `/graphql` | `/external/labeling/crowd-items` |
| **Method names** | `Create*`, `Get*`, `List*`, `Delete*` | `CreateNotebook`, `GetFeatureFlags` |
| **Service paths** | `*.Service/*` | `google.internal.alkali...MakerSuiteService/CountTokens` |
| **RPC IDs** | 4-8 char alphanumeric | `wXbhsf`, `Bgzyjc`, `ozz5Z` |
| **API keys** | `AIza*`, `sk-*`, `ghp_*` | `AIzaSyDtC7Uwb5pGAsdmrH2T4Gqdk5Mga07jYPM` |

### 2.3 Heap Diffing

The killer technique: diff two snapshots to find what a specific user action
introduces into memory.

```bash
python -m scripts.argus.analyze heap-diff before.heapsnapshot after.heapsnapshot
```

This isolates:
- New API endpoints fetched during the action
- RPC IDs loaded by lazy-loaded code
- Configuration objects populated after authentication
- Temporary tokens and session identifiers

### 2.4 What You Find That Network Traffic Misses

Heap snapshots reveal strings that never transit the network:

- **Compiled-in config**: Environment variables baked into the Vite/Webpack build
- **Unused API routes**: Endpoints defined in code but never called in your session
- **Internal service names**: gRPC service paths, proto package names
- **Feature flag names**: Before hashing (if the SDK stores originals)
- **Error messages**: Internal error strings that reveal architecture
- **Enum values**: Character names, status codes, permission levels

### 2.5 Large Snapshot Handling

Heap snapshots can be 50-100 MB. ARGUS streams the JSON parser and filters
strings by minimum length (default: 8 chars) to avoid noise. The `strings`
array in V8 heap format is a flat list -- no tree traversal needed.

---

## 3. Bundle Decompilation

Modern SPAs ship a single minified JavaScript bundle containing the entire
application logic. Decompiling this bundle is the most thorough way to map an
application's complete feature set.

### 3.1 Downloading the Bundle

**From HAR:**

Search for the main JS asset in captured traffic (usually the largest `.js` file):

```python
import json
from pathlib import Path

def extract_main_bundle(har_path: Path, output_dir: Path) -> Path:
    """Find and save the main JS bundle from a HAR file."""
    har = json.loads(har_path.read_text(errors="replace"))
    largest = None
    for entry in har["log"]["entries"]:
        url = entry["request"]["url"]
        resp = entry["response"]
        body = resp.get("content", {}).get("text", "")
        if url.endswith(".js") and body and (not largest or len(body) > largest[1]):
            largest = (url, len(body), body)
    if largest:
        filename = largest[0].split("/")[-1].split("?")[0]
        out_path = output_dir / filename
        out_path.write_text(largest[2], encoding="utf-8")
        print(f"Saved {len(largest[2]):,} bytes -> {out_path}")
        return out_path
    return None
```

**Direct download:**

```bash
# Find the bundle URL from the page source
curl -s https://app.example.com | grep -oP 'src="(/assets/[^"]+\.js)"'
# Download it
curl -o bundle.js https://app.example.com/assets/index-ABC123.js
```

### 3.2 What to Search For

Once you have the bundle, search systematically for these patterns:

**Feature gates and flags:**
```bash
# Enum definitions (React apps with TypeScript enums)
grep -oP '(FEATURE_|GATE_|FLAG_)[A-Z_]+' bundle.js | sort -u

# Statsig gate names
grep -oP '"[a-z_]+"' bundle.js | sort -u | head -100
```

**API routes:**
```bash
# URL path patterns
grep -oP '"/(?:api|v[0-9]|external)/[a-z0-9/_-]+"' bundle.js | sort -u

# Full URL construction
grep -oP '"https?://[^"]+"' bundle.js | sort -u
```

**Environment variables:**
```bash
# Vite env vars
grep -oP 'VITE_[A-Z_]+' bundle.js | sort -u

# Next.js env vars
grep -oP 'NEXT_PUBLIC_[A-Z_]+' bundle.js | sort -u

# Create React App env vars
grep -oP 'REACT_APP_[A-Z_]+' bundle.js | sort -u
```

**Characters/entities:**
```bash
# String literals that look like entity names
grep -oP '"[A-Z][a-z]+-?[A-Za-z]*"' bundle.js | sort -u
```

### 3.3 Sesame Bundle Analysis Example

From the Sesame `index-E-c2zfaB.js` (2.06 MB) bundle decompilation:

```
9 named feature gates (vs 27 hashed IDs from Statsig)
9 dynamic configs with actual names
3 characters (Maya, Maya-Alpha, Miles)
101 URL paths (vs 6 from HAR traffic)
21 Vite environment variables
32 internal IAP-protected endpoints
CI/CD stack: GitHub Actions, Vite 6.2.5, pnpm 9.15.3
Monorepo path: sesame/web/consumer-app
```

The bundle revealed 17x more URL paths than live traffic observation. This is
typical -- most endpoints are for features the current user cannot access.

### 3.4 Source Map Discovery

Some applications accidentally ship source maps in production:

```bash
# Check if source maps exist
curl -s -o /dev/null -w "%{http_code}" https://app.example.com/assets/index-ABC.js.map
# 200 = jackpot (full original source code)
# 404 = stripped (normal for production)
```

If available, source maps give you the original TypeScript/JSX with function
names, comments, and file paths intact.

### 3.5 CI/CD and Infrastructure Leaks

Bundles often contain build metadata:

| Pattern | Reveals |
|---------|---------|
| `__SENTRY_DSN__` or Sentry config | Error tracking org/project IDs |
| `DATADOG_CLIENT_TOKEN` | Monitoring infrastructure |
| `RUDDERSTACK_WRITE_KEY` | Analytics data plane |
| Package manager lockfile hashes | Dependency versions |
| Build tool version strings | Vite/Webpack/Next.js version |
| GitHub Actions artifacts | CI/CD pipeline, repo structure |
| Docker/K8s references | Infrastructure topology |

---

## 4. Feature Flag Manipulation

Modern apps use feature flag services (Statsig, LaunchDarkly, Optimizely,
Unleash, Split) to gate features. The client SDKs cache evaluation results
locally, making them modifiable.

### 4.1 Identifying the Flag System

**From HAR traffic:**

| Service | Network Signature |
|---------|-------------------|
| **Statsig** | `featureassets.org/v1/initialize`, `featuregates.org` |
| **LaunchDarkly** | `app.launchdarkly.com/sdk/evalx`, `events.launchdarkly.com` |
| **Optimizely** | `cdn.optimizely.com/datafiles`, `logx.optimizely.com` |
| **Unleash** | `/api/client/features`, `/api/frontend` |
| **Split** | `sdk.split.io`, `events.split.io` |
| **ConfigCat** | `cdn-global.configcat.com` |
| **Flagsmith** | `api.flagsmith.com/api/v1/flags` |

**From heap/bundle:**

```bash
grep -i "statsig\|launchdarkly\|optimizely\|unleash\|split\.io\|configcat\|flagsmith" bundle.js
```

### 4.2 Statsig localStorage Injection

Statsig SDK v3+ caches evaluation results in localStorage. The cache format
(discovered during the Sesame exploration):

**Key format:** `statsig.cached.evaluations.{user_hash}`

The user_hash differs per user (anonymous vs logged-in). To find it:

```javascript
// Console injection — find all Statsig cache keys
Object.keys(localStorage).filter(k => k.startsWith('statsig.'));
```

**Cache structure (double-encoded JSON):**

```javascript
// The outer value has a .data field that is JSON.stringify'd
let key = Object.keys(localStorage).find(k => k.startsWith('statsig.cached.evaluations'));
let outer = JSON.parse(localStorage.getItem(key));
let inner = JSON.parse(outer.data);

// inner.feature_gates is an object mapping gate_hash -> evaluation
// Each gate: { value: true/false, rule_id: "...", ... }

// Flip all gates ON
for (let gate of Object.keys(inner.feature_gates)) {
    inner.feature_gates[gate].value = true;
}

// Re-encode and save
outer.data = JSON.stringify(inner);
localStorage.setItem(key, JSON.stringify(outer));

// Reload to apply
location.reload();
```

### 4.3 LaunchDarkly localStorage Injection

LaunchDarkly's JS SDK caches flags in localStorage under a key derived from the
SDK key and user key:

```javascript
// Find LD cache keys
Object.keys(localStorage).filter(k => k.startsWith('ld:'));

// Typical key: ld:$user_hash
let ldKey = Object.keys(localStorage).find(k => k.startsWith('ld:'));
let flags = JSON.parse(localStorage.getItem(ldKey));

// flags is a flat object: { flagName: flagValue, ... }
// Modify any flag
flags['new-feature'] = true;
flags['beta-access'] = true;
localStorage.setItem(ldKey, JSON.stringify(flags));
location.reload();
```

### 4.4 Server-Side vs Client-Side Gates

**Critical distinction:** Feature flags control two different things:

1. **Client-side rendering** -- which UI components are shown
2. **Server-side authorization** -- which API endpoints accept requests

localStorage injection only affects #1. If an API endpoint checks the flag
server-side, flipping the client gate will show the UI but all API calls will
fail with 403/401.

**How to test:**

```python
# After flipping a gate that reveals a new UI button,
# capture the API call that button makes and replay it
# without the gate flip. If it succeeds, the gate is client-only.
import requests

# Test endpoint discovered behind a flipped gate
r = requests.post(
    "https://api.example.com/v1/beta-feature",
    headers={"Authorization": f"Bearer {token}"},
    json={"action": "test"},
)
print(f"Status: {r.status_code}")
# 200 = server doesn't check the gate (client-only)
# 403 = server enforces the gate (server-side)
```

### 4.5 Environment-Based Flag Differences

Flag services return different evaluations per environment. Compare them:

```python
import requests

STATSIG_URL = "https://featureassets.org/v1/initialize"

def get_gates(email: str, env: str = "production") -> dict:
    """Get Statsig gate evaluations for a user/environment combo."""
    r = requests.post(
        f"{STATSIG_URL}?k={STATSIG_CLIENT_KEY}",
        json={
            "user": {"email": email, "userID": "test"},
            "statsigMetadata": {
                "sdkType": "js-client",
                "sdkVersion": "5.4.0",
                "stableID": env,
            },
        },
    )
    gates = r.json().get("feature_gates", {})
    return {k: v.get("value", False) for k, v in gates.items()}

# Compare environments
for env in ["production", "staging", "development"]:
    gates = get_gates("user@gmail.com", env)
    on_count = sum(1 for v in gates.values() if v)
    print(f"{env}: {on_count}/{len(gates)} gates ON")
```

---

## 5. CDP Scripting

Chrome DevTools Protocol gives programmatic access to everything DevTools can
do -- network interception, JS execution, heap profiling, DOM inspection -- via
a WebSocket connection to Chrome.

### 5.1 Setup

Chrome must be launched with remote debugging enabled:

```powershell
# Windows — launch Chrome with CDP on port 9223
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9223
```

```bash
# Linux/Mac
google-chrome --remote-debugging-port=9223
```

Verify it works:

```bash
curl http://localhost:9223/json
```

### 5.2 ARGUS CDP Bridge

ARGUS provides a full async CDP client in `scripts/argus/cdp_bridge.py`:

```python
from scripts.argus.cdp_bridge import CDPBridge, CDPSession

async def example():
    bridge = CDPBridge()
    await bridge.connect()

    # List all open tabs
    tabs = await bridge.get_tabs()
    for tab in tabs:
        print(f"  {tab['title'][:40]}  {tab['url'][:60]}")

    # Get a session for a specific tab
    session = await bridge.get_session_for_url("app.sesame.com")

    # Enable domains
    await session.send("Network.enable")
    await session.send("Runtime.enable")
    await session.send("HeapProfiler.enable")

    # Execute JavaScript in the page context
    result = await session.send("Runtime.evaluate", {
        "expression": "document.title",
        "returnByValue": True,
    })
    print(f"Page title: {result['result']['value']}")
```

### 5.3 JavaScript Injection

Execute arbitrary JS in any page context via CDP:

```python
# Read localStorage
result = await session.send("Runtime.evaluate", {
    "expression": "JSON.stringify(localStorage)",
    "returnByValue": True,
})
local_storage = json.loads(result["result"]["value"])

# Modify localStorage
await session.send("Runtime.evaluate", {
    "expression": """
        let key = Object.keys(localStorage).find(k => k.startsWith('statsig.cached'));
        let data = JSON.parse(localStorage.getItem(key));
        let inner = JSON.parse(data.data);
        Object.keys(inner.feature_gates).forEach(g => {
            inner.feature_gates[g].value = true;
        });
        data.data = JSON.stringify(inner);
        localStorage.setItem(key, JSON.stringify(data));
        'Done: ' + Object.keys(inner.feature_gates).length + ' gates flipped';
    """,
    "returnByValue": True,
})

# Intercept fetch/XHR responses
await session.send("Runtime.evaluate", {
    "expression": """
        const origFetch = window.fetch;
        window.fetch = async (...args) => {
            const resp = await origFetch(...args);
            const clone = resp.clone();
            clone.text().then(body => {
                console.log('FETCH:', args[0], resp.status, body.slice(0, 200));
            });
            return resp;
        };
        'Fetch interceptor installed';
    """,
    "returnByValue": True,
})
```

### 5.4 Network Interception

Capture all network traffic programmatically:

```python
from scripts.argus.network_monitor import NetworkMonitor

monitor = NetworkMonitor()
await monitor.start()

# Wait for user to interact with the page
await asyncio.sleep(30)

# Drain all captured requests
traffic = await monitor.drain()
for req in traffic:
    if req.response_status and req.url.startswith("https://api"):
        print(f"  {req.method} {req.url}")
        print(f"    Status: {req.response_status}")
        if req.post_data:
            print(f"    Body: {req.post_data[:200]}")
```

### 5.5 WebSocket Frame Interception

CDP can intercept WebSocket frames in flight:

```python
# Enable network domain with WebSocket interception
await session.send("Network.enable")

# Listen for WebSocket frames
frames = []

def on_ws_frame(params):
    frames.append({
        "direction": "recv" if "response" in str(params) else "send",
        "data": params.get("response", {}).get("payloadData", ""),
        "timestamp": params.get("timestamp", 0),
    })

session.on("Network.webSocketFrameReceived", on_ws_frame)
session.on("Network.webSocketFrameSent", lambda p: frames.append({
    "direction": "send",
    "data": p.get("request", {}).get("payloadData", ""),
}))
```

### 5.6 ARGUS MCP Skills for CDP

ARGUS exposes CDP capabilities as MCP skills so LMStudio agents can drive
Chrome autonomously:

```python
# From engine/skills/builtin/debugger_skills.py
debug_eval(port=5556, expression="document.title")
debug_dom(port=5556, selector="div.chat-messages")
debug_screenshot(port=5556)
debug_click(port=5556, selector="button.send")
debug_navigate(port=5556, url="http://localhost:5556/admin")
```

See `scripts/argus/browser_tools.py` for the full MCP skill set.

---

## 6. WebSocket Protocol Analysis

WebSocket connections carry real-time protocols that are invisible to standard
HAR analysis (HAR only captures the HTTP upgrade, not the frames). Full protocol
mapping requires frame-level capture.

### 6.1 Identifying WebSocket Endpoints

**From HAR:**

```python
def find_websocket_upgrades(har_path: Path) -> list[str]:
    """Find WebSocket upgrade requests in HAR."""
    har = json.loads(har_path.read_text(errors="replace"))
    ws_urls = []
    for entry in har["log"]["entries"]:
        # Check for 101 Switching Protocols
        if entry["response"]["status"] == 101:
            ws_urls.append(entry["request"]["url"])
        # Check for upgrade headers
        for h in entry["request"]["headers"]:
            if h["name"].lower() == "upgrade" and h["value"].lower() == "websocket":
                ws_urls.append(entry["request"]["url"])
    return ws_urls
```

**From bundle:**

```bash
grep -oP 'wss?://[^"'"'"']+' bundle.js | sort -u
```

### 6.2 Connecting and Mapping Messages

```python
import asyncio
import json
import websockets

async def map_ws_protocol(url: str, auth_token: str = ""):
    """Connect to a WebSocket endpoint and log all message types."""
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    # Some APIs pass auth as a query parameter
    if auth_token and "?" not in url:
        url = f"{url}?token={auth_token}"

    async with websockets.connect(url, extra_headers=headers) as ws:
        message_types = set()

        async def reader():
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    msg_type = (
                        data.get("type")
                        or data.get("event")
                        or data.get("action")
                        or data.get("method")
                        or "unknown"
                    )
                    message_types.add(msg_type)
                    print(f"  <- {msg_type}: {json.dumps(data)[:200]}")
                except json.JSONDecodeError:
                    print(f"  <- BINARY: {len(msg)} bytes")

        # Read for 30 seconds
        try:
            await asyncio.wait_for(reader(), timeout=30)
        except asyncio.TimeoutError:
            pass

        print(f"\nDiscovered {len(message_types)} message types:")
        for mt in sorted(message_types):
            print(f"  - {mt}")
```

### 6.3 Sesame WebSocket Protocol Map

Example protocol mapping from the Sesame exploration:

```
13 message types discovered:
  Client -> Server (6):
    initialize      — session setup with character + settings
    location        — user geolocation
    webrtc_config   — request ICE/TURN configuration
    sdp_offer       — WebRTC SDP offer for audio
    ice_candidates  — ICE candidate exchange
    ping            — keepalive (~500ms interval)

  Server -> Client (7):
    call_connect    — session confirmed, call ID assigned
    ice_servers     — TURN server credentials
    sdp_answer      — WebRTC SDP answer
    chat_init       — character greeting message
    pong            — keepalive response
    call_disconnect — session terminated
    error           — error with code + message
```

### 6.4 Replay and Fuzzing

Once you have the protocol mapped, build a client that replays the connection
flow:

```python
async def connect_sesame_agent(token: str, character: str = "Maya"):
    """Example: Sesame voice agent WebSocket connection."""
    url = f"wss://sesameai.app/agent-service-0/v1/connect?token={token}"

    async with websockets.connect(url) as ws:
        # Step 1: Initialize
        await ws.send(json.dumps({
            "type": "initialize",
            "character": character,
            "settings": {"sample_rate": 44100, "codec": "none"},
        }))

        # Step 2: Read response messages
        while True:
            msg = json.loads(await ws.recv())
            print(f"  <- {msg['type']}")

            if msg["type"] == "call_connect":
                session_id = msg.get("session_id")
                call_id = msg.get("call_id")
                print(f"  Connected! Session: {session_id}, Call: {call_id}")

            if msg["type"] == "ice_servers":
                print(f"  ICE servers: {len(msg.get('servers', []))} servers")

            if msg["type"] == "error":
                print(f"  Error: {msg.get('message')}")
                break
```

---

## 7. Token Management

Every authenticated API requires tokens. ARGUS manages token lifecycle across
multiple authentication systems.

### 7.1 Firebase JWT Refresh

Firebase Authentication uses short-lived JWTs (1 hour) with long-lived refresh
tokens. The refresh flow is universal across all Firebase apps:

```python
import requests
import json
import base64
import time

FIREBASE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

def refresh_firebase_token(api_key: str, refresh_token: str) -> dict:
    """Exchange a Firebase refresh token for a fresh JWT.

    Args:
        api_key: The Firebase project's Web API key (public, from app config).
        refresh_token: The refresh_token from a previous auth or HAR capture.

    Returns:
        Dict with id_token, refresh_token (may rotate), expires_in.
    """
    r = requests.post(
        f"{FIREBASE_TOKEN_URL}?key={api_key}",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return {
        "id_token": data["id_token"],
        "refresh_token": data["refresh_token"],  # may be rotated
        "expires_in": int(data.get("expires_in", 3600)),
    }

def decode_jwt_payload(token: str) -> dict:
    """Decode a JWT payload without signature verification."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    # Add padding
    payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))
```

### 7.2 Auto-Refresh Pattern

The `SesameClient` (in `scripts/argus/clients/sesame_client.py`) implements
auto-refresh that transparently keeps tokens valid:

```python
class TokenStore:
    """Token management with auto-refresh."""

    def ensure_valid(self) -> bool:
        """Auto-refresh if token is expired or about to expire (<5min)."""
        if not self._token:
            return False
        remaining = self._expires - time.time()
        if remaining > 300:  # More than 5 min left
            return True
        return self.refresh()

    @property
    def auth_headers(self) -> dict:
        """Get Authorization headers, auto-refreshing if needed."""
        self.ensure_valid()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
```

Every API call uses `auth_headers`, which triggers auto-refresh when the token
is within 5 minutes of expiry. This pattern works for any token-based API.

### 7.3 Google Cookie-Based Auth (SAPISIDHASH)

For Google's internal APIs (batchexecute, gRPC-web), authentication uses
cookies plus a computed hash:

```python
import hashlib
import time

def compute_sapisidhash(sapisid: str, origin: str) -> str:
    """Compute Google SAPISIDHASH header from SAPISID cookie.

    Args:
        sapisid: Value of the SAPISID or __Secure-3PAPISID cookie.
        origin: The origin URL (e.g., https://notebooklm.google.com).

    Returns:
        Full header value: "SAPISIDHASH {timestamp}_{hash}"
    """
    timestamp = str(int(time.time()))
    raw = f"{timestamp} {sapisid} {origin}"
    hash_value = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {timestamp}_{hash_value}"
```

**Important caveat:** Not all Google services use SAPISIDHASH. NotebookLM
batchexecute authenticates purely via cookies + CSRF token. Adding SAPISIDHASH
to NLM calls causes HTTP 400 errors. Always test with and without.

### 7.4 Token Harvesting from Chrome

ARGUS can pull live tokens directly from Chrome via CDP:

```bash
python -m scripts.argus.tools.token_harvester             # harvest + save
python -m scripts.argus.tools.token_harvester --show       # print only
python -m scripts.argus.tools.token_harvester --account me # specific account
```

The token harvester (`scripts/argus/tools/token_harvester.py`) extracts cookies
from all Google domains, computes SAPISIDHASH, and updates the account pool.

---

## 8. Profile CRUD Testing

User profile endpoints are high-value targets for authorization testing. The
goal is to map which fields are writable, which are protected server-side, and
whether any privilege escalation is possible.

### 8.1 Methodology

1. **GET** the full profile to see all fields
2. **PATCH/PUT** each field individually to test writability
3. Attempt to write protected fields (roles, email, permissions)
4. Check if the server silently ignores or explicitly rejects

### 8.2 Example: Sesame Profile Testing

```python
import requests

API = "https://sesameai.app"

def test_profile_fields(token: str) -> dict:
    """Test which profile fields are writable."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Step 1: Get current profile
    r = requests.get(f"{API}/api/user", headers=headers)
    original = r.json()
    print(f"Original profile: {json.dumps(original, indent=2)}")

    results = {}

    # Step 2: Test writable fields
    writable_tests = {
        "nickname": "test_nick_123",
        "birthday": "1990-01-01",
        "allow_training_from_calls": False,
        "prefer_product_news_emails": False,
    }

    for field, test_value in writable_tests.items():
        r = requests.patch(
            f"{API}/api/user", headers=headers,
            json={field: test_value},
        )
        if r.status_code == 200:
            new_val = r.json().get(field)
            results[field] = "WRITABLE" if new_val == test_value else "IGNORED"
        else:
            results[field] = f"REJECTED ({r.status_code})"

    # Step 3: Test protected fields (these should be rejected or ignored)
    protected_tests = {
        "email": "hacker@evil.com",
        "roles": ["ADMIN", "USER"],
        "moderation_status": "ALLOWED",
        "display_name": "Admin User",
    }

    for field, test_value in protected_tests.items():
        r = requests.patch(
            f"{API}/api/user", headers=headers,
            json={field: test_value},
        )
        if r.status_code == 200:
            new_val = r.json().get(field)
            if new_val == test_value:
                results[field] = "WRITABLE (VULNERABILITY!)"
            else:
                results[field] = "IGNORED (server-side protected)"
        else:
            results[field] = f"REJECTED ({r.status_code})"

    # Step 4: Restore original values
    restore = {k: original.get(k) for k in writable_tests if original.get(k) is not None}
    requests.patch(f"{API}/api/user", headers=headers, json=restore)

    return results
```

### 8.3 What to Test

| Test | What It Reveals |
|------|-----------------|
| Change email | Can you take over another account? |
| Set roles to ADMIN | Can you escalate privileges? |
| Change moderation_status | Can you unban yourself? |
| Set is_staff/is_admin | Does the server check custom properties? |
| Inject unknown fields | Does the server accept arbitrary data? |
| Change user_id/uuid | Can you impersonate another user? |
| Set deleted_at to null | Can you undelete a banned account? |

### 8.4 Sesame Results

From the Session 3 deep dive:

| Field | Result |
|-------|--------|
| `nickname` | WRITABLE |
| `birthday` | WRITABLE |
| `allow_training_from_calls` | WRITABLE |
| `prefer_product_news_emails` | WRITABLE |
| `email` | IGNORED (server-side protected) |
| `roles` | IGNORED (server-side protected) |
| `moderation_status` | IGNORED (server-side protected) |
| `display_name` | IGNORED (server-side protected) |
| `gender` | WRITABLE (with enum validation: MALE, FEMALE, etc.) |

All sensitive fields are properly protected. The server silently ignores
unknown or protected fields rather than rejecting the whole request.

---

## 9. Environment Mapping

Applications typically have multiple environments (production, staging,
development) with different configurations. Mapping these differences reveals
testing features, debug endpoints, and upcoming changes.

### 9.1 Discovering Environments

**From bundle analysis:**

```bash
# Vite environment detection
grep -oP 'import\.meta\.env\.[A-Z_]+' bundle.js | sort -u

# Next.js environment detection
grep -oP 'process\.env\.(NODE_ENV|NEXT_PUBLIC_[A-Z_]+)' bundle.js | sort -u
```

**From DNS enumeration:**

```bash
# Common environment subdomains
for env in staging stg dev beta canary preview internal admin api; do
    host "$env.example.com" 2>/dev/null && echo "FOUND: $env.example.com"
done
```

**From feature flag configurations:**

```python
# Compare Statsig evaluations across environments
# (see Section 4.5 for full code)
for env in ["production", "staging", "development"]:
    gates = get_gates(email, env)
    print(f"{env}: {sum(v for v in gates.values())}/{len(gates)} gates ON")
```

### 9.2 Configuration Comparison

Map dynamic config differences across environments:

```python
def compare_configs(email: str, environments: list[str]) -> dict:
    """Compare dynamic configs across environments."""
    results = {}
    for env in environments:
        r = requests.post(
            f"{STATSIG_URL}/initialize?k={STATSIG_CLIENT_KEY}",
            json={
                "user": {"email": email},
                "statsigMetadata": {"stableID": env},
            },
        )
        configs = r.json().get("dynamic_configs", {})
        results[env] = {}
        for name, config in configs.items():
            results[env][name] = config.get("value", {})
    return results
```

### 9.3 What Environment Differences Reveal

| Finding | Meaning |
|---------|---------|
| Staging has more gates ON | Upcoming features being tested |
| Dev has debug configs enabled | Debug endpoints may be accessible |
| Different WebRTC configs | Audio quality tuning in progress |
| Extra API endpoints in staging | New backend features not yet deployed |
| Different error reporting levels | Debug logging available in non-prod |

### 9.4 Sesame Environment Map

```
Production:  20/27 gates enabled for employees
Staging:     19/27 gates (1 prod-only gate)
Development: 21/27 gates (1 extra dev-only gate)

Staff configs differ:
  production:  webrtc_log_level="error"
  staging:     webrtc_log_level="info"  (verbose debugging)
  development: show_toggle=true         (hidden UI toggle)
```

---

## 10. Security Assessment Checklist

After completing recon (Sections 1-9), use this checklist to assess the
application's security posture. Each item categorizes findings as
client-only (cosmetic) or server-enforced (real).

### 10.1 Authentication

- [ ] **Token type**: JWT (RS256/HS256), opaque session, API key?
- [ ] **Token lifetime**: How long until expiry? Is rotation enforced?
- [ ] **Refresh mechanism**: Does the refresh token rotate? Is it bound to IP/device?
- [ ] **Token storage**: localStorage (XSS-vulnerable), httpOnly cookie (CSRF-vulnerable), or memory-only?
- [ ] **Multi-session**: Can you use the same token from multiple IPs?
- [ ] **Token leakage**: Is the JWT in URL query strings (visible in logs)?

### 10.2 Authorization

- [ ] **Role escalation**: Can you PATCH roles/permissions on your profile?
- [ ] **Email takeover**: Can you change your email to another user's?
- [ ] **IDOR**: Can you access other users' resources by changing IDs in URLs?
- [ ] **Feature gates**: Are they client-only (localStorage) or server-enforced?
- [ ] **API endpoint protection**: Do gated endpoints check auth server-side?
- [ ] **Admin endpoints**: Are internal/admin paths behind network-level auth (IAP, VPN)?

### 10.3 Data Exposure

- [ ] **Profile fields**: What PII is returned in profile endpoints?
- [ ] **Enumeration**: Can you enumerate user IDs, call IDs, session IDs?
- [ ] **Public storage**: Are cloud storage buckets publicly readable?
- [ ] **Source maps**: Are `.js.map` files accessible in production?
- [ ] **Error messages**: Do errors reveal internal architecture?
- [ ] **Environment variables**: Are secrets baked into the JS bundle?

### 10.4 Infrastructure

- [ ] **Debug endpoints**: `/docs`, `/openapi.json`, `/swagger`, `/debug`, `/health`
- [ ] **Service segregation**: Are internal services behind IAP/VPN?
- [ ] **Rate limiting**: Are there rate limits on auth, API, and WebSocket?
- [ ] **CORS**: Does `Access-Control-Allow-Origin: *` permit cross-origin requests?
- [ ] **CSP**: Is Content-Security-Policy enforced? Does it block inline scripts?

### 10.5 Client-Only vs Server-Enforced

The most critical distinction in any assessment. Document every finding:

```
| Finding                     | Client-Only | Server-Enforced |
|-----------------------------|:-----------:|:---------------:|
| Feature gate rendering      |      X      |                 |
| API endpoint auth           |             |        X        |
| Role field in profile PATCH |             |        X        |
| Email field in profile PATCH|             |        X        |
| Statsig gate values         |      X      |                 |
| WebSocket token validation  |             |        X        |
| Firebase JWT signing        |             |        X        |
| IAP on agent-service-1-5    |             |        X        |
```

### 10.6 Sesame Security Assessment Summary

```
SECURE:
  - Email change: BLOCKED server-side
  - Role injection: BLOCKED server-side
  - JWT: RS256 signed (cannot forge)
  - Agent services 1-5: behind Google IAP
  - Firebase App Check: reCAPTCHA Enterprise

CLIENT-ONLY (not security bugs):
  - Statsig gates: UI rendering only, not API auth
  - localStorage injection: persists but no server effect

INFORMATIONAL:
  - JWT in WebSocket query string (appears in logs)
  - GCS bucket 'sesame-dev-public' publicly readable (by design)
  - Sequential call IDs (enumerable but no data leakage)
  - Agent-service-0 is public (by design — it's the user-facing service)
  - Swagger at /docs exists but behind IAP (no public access)
```

---

## ARGUS CLI Quick Reference

```bash
# ──── HAR / Heap Analysis ──────────────────────────────────────
python -m scripts.argus.analyze har file.har           # Analyze single HAR
python -m scripts.argus.analyze har file.har --report  # Generate Markdown report
python -m scripts.argus.analyze har file.har --json    # JSON output
python -m scripts.argus.analyze heap file.heapsnapshot # Analyze heap snapshot
python -m scripts.argus.analyze heap-diff a.heap b.heap # Diff two snapshots
python -m scripts.argus.analyze compare a.har b.har    # Diff two HARs
python -m scripts.argus.analyze dir ./hars/            # Batch analyze directory
python -m scripts.argus.analyze deep ./captures/       # Full automated workflow

# ──── Token Harvesting ─────────────────────────────────────────
python -m scripts.argus.tools.token_harvester          # Harvest from Chrome
python -m scripts.argus.tools.token_harvester --show   # Print only
python -m scripts.argus.tools.token_harvester --account myname

# ──── CDP / Browser Debugging ──────────────────────────────────
python -m scripts.argus.tools.debug_scene --port 5556           # Full diagnostics
python -m scripts.argus.tools.debug_scene --port 5556 --watch   # Live console
python -m scripts.argus.tools.debug_scene --port 5556 --eval "document.title"
python -m scripts.argus.tools.debug_scene --port 5556 --dom "div.panel"
python -m scripts.argus.tools.debug_scene --port 5556 --z-stack
python -m scripts.argus.tools.debug_scene --port 5556 --screenshot

# ──── Orchestrated Crawls ──────────────────────────────────────
python -m scripts.argus.orchestrator                   # Full scan (all targets)
python -m scripts.argus.orchestrator --target nlm      # NLM only
python -m scripts.argus.orchestrator --probe-flags     # Feature flag enumeration
python -m scripts.argus.orchestrator --docs-only       # Regenerate docs

# ──── Application-Specific Clients ─────────────────────────────
python -m scripts.argus.clients.sesame_client          # Sesame interactive menu
python -m scripts.argus.clients.sesame_client flags    # Feature flags
python -m scripts.argus.clients.sesame_client user     # Profile info
python -m scripts.argus.clients.sesame_client agents   # Agent service health
python -m scripts.argus.clients.sesame_client export   # Export API spec JSON
python -m scripts.argus.clients.openroom_client        # OpenRoom interactive menu
python -m scripts.argus.clients.openroom_client repl   # OpenRoom REPL
python -m scripts.argus.clients.openroom_client full   # Run everything

# ──── Nexus Integration ────────────────────────────────────────
python -m engine.nexus.bridge search "argus rpcid"
python -m engine.nexus.bridge ask "What new endpoints did ARGUS find?"
```

---

## Cross-References

| Document | Relevance |
|----------|-----------|
| `docs/ARGUS.md` | Full ARGUS platform docs (CDP, crawlers, LiveDebugger, API catalog) |
| `docs/EXPLORATION_JOURNAL.md` | Narrative of the Google API reverse-engineering campaign |
| `docs/ARGUS_API_CATALOG.md` | All discovered API endpoints and RPC IDs |
| `data/argus/reports/sesame_research_journal.md` | Sesame AI intelligence journal |
| `docs/OPENROOM_FEATURES.md` | OpenRoom.ai feature documentation |
| `scripts/argus/analyzers/har_analyzer.py` | Generic HAR analysis engine |
| `scripts/argus/analyzers/heap_analyzer.py` | V8 heap snapshot parser |
| `scripts/argus/clients/sesame_client.py` | Sesame API client with auto-refresh |
| `scripts/argus/clients/openroom_client.py` | OpenRoom API client |
| `scripts/argus/cdp_bridge.py` | Chrome DevTools Protocol async client |
| `scripts/argus/network_monitor.py` | CDP network traffic capture |
| `scripts/argus/tools/token_harvester.py` | Live token extraction from Chrome |
| `scripts/argus/discovery/feature_flag_probe.py` | NLM feature flag enumeration |

---

## Change Log

```
v1.52.0 [2026-03-26] — Initial methodology guide covering all 10 reconnaissance
                        techniques from Sesame + OpenRoom explorations
```
