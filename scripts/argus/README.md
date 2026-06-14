# ARGUS — API Reconnaissance & General-purpose Utility Suite

> v1.52.1 [2026-03-26]
>
> A comprehensive toolkit for web application analysis, reverse engineering,
> and API surface discovery. Target-agnostic, technique-driven.

---

## What Is ARGUS?

ARGUS is CosySim's integrated reconnaissance framework. It provides **reusable tools**
for analyzing any web application's architecture, authentication, APIs, feature flags,
real-time protocols, and AI agent systems.

**ARGUS is a first-class tool.** It should be used automatically whenever analyzing
web applications, not just when explicitly asked. When you encounter a HAR file,
heap snapshot, or web application — run ARGUS.

### Philosophy

- **Knowledge is the prize.** We don't exploit. We learn.
- **Technique-driven, not target-driven.** Every tool works on any target.
- **Automate everything.** If a human has to ask for it, the workflow is broken.
- **Document everything.** Findings without reports are forgotten findings.

---

## Quick Start

```bash
# Analyze a HAR file
python -m scripts.argus.analyze har path/to/file.har --report

# Analyze a V8 heap snapshot
python -m scripts.argus.analyze heap path/to/file.heapsnapshot

# Compare two captures
python -m scripts.argus.analyze compare a.har b.har

# Auto-analyze: run full pipeline on a directory of captures
python -m scripts.argus.analyze auto path/to/captures/

# Run the Sesame AI interactive client
python -m scripts.argus.clients.sesame_client

# Run heap deep parser (full V8 graph walk)
python scripts/heap_deep_parser.py path/to/file.heapsnapshot --out data/heap_output/

# Run heap miner (100+ regex patterns)
python scripts/heap_miner.py path/to/file.heapsnapshot --out data/heap_output/
```

---

## Architecture

```
scripts/argus/
    toolkit.py          ← 16 reusable generic functions (the core)
    analyze.py          ← CLI entry point (har, heap, compare, auto)
    agent.py            ← ARGUS autonomous agent
    explorer.py         ← Interactive web explorer
    config.py           ← YAML config loader

    clients/            ← Target-specific interactive clients
        sesame_client.py    — Sesame AI (voice AI)
        openroom_config.py  — OpenRoom.ai (text AI + virtual OS)

    analyzers/          ← Specialized analyzers
    crawlers/           ← Web crawlers
    decoders/           ← Payload decoders
    discovery/          ← API discovery modules
    importers/          ← Data importers
    reporting/          ← Report generators
    tools/              ← Standalone tools

    har_miner.py        ← HAR file analysis
    har_scanner.py      ← HAR scanning
    cdp_bridge.py       ← Chrome DevTools Protocol bridge
    network_monitor.py  ← Network traffic monitoring
    vision_agent.py     ← Screenshot + vision analysis
    argus_mcp_server.py ← MCP server for tool exposure

scripts/
    heap_miner.py       ← V8 heap regex scanner (100+ patterns)
    heap_deep_parser.py ← V8 heap graph walker (ijson-based)
```

---

## The Toolkit — 16 Reusable Functions

### Bundle Analysis

| Function | Purpose |
|----------|---------|
| `download_bundle(url)` | Download JS bundle from URL |
| `decompile_bundle(js_path)` | Extract enums, routes, env vars, API methods |
| `find_bundle_urls_in_page(html)` | Find bundle URLs in HTML source |

**What to look for in bundles:**
- Feature flag enums (gate names, config names)
- API route strings (`/api/`, `/v1/`, internal paths)
- Environment variables (`VITE_*`, `NEXT_PUBLIC_*`, `REACT_APP_*`)
- CI/CD paths (`/home/runner/`, `_work/`)
- Character/model names
- OpenAPI codegen comments (`openapi-rq`, `swagger`)

### Feature Flag Manipulation

| Function | Purpose |
|----------|---------|
| `inject_statsig_gates(tab_url, gates, cdp_port)` | Flip Statsig gates via localStorage |

**What to look for:**
- Statsig client keys (`client-*`)
- Gate names and their evaluation rules
- Dynamic config keys and values
- Email domain conditions
- Environment-specific gates (staging vs production)

### CDP Scripting

| Function | Purpose |
|----------|---------|
| `cdp_eval(expression, cdp_port, tab_url)` | Execute JS in Chrome via CDP |
| `cdp_find_tab(url_pattern, cdp_port)` | Find Chrome tab by URL |
| `cdp_inject_before_load(script, cdp_port)` | Pre-navigation JS injection |

**Requirements:** Chrome launched with `--remote-debugging-port=9223`

### WebSocket Interception

| Function | Purpose |
|----------|---------|
| `inject_websocket_intercept(field_path, new_value, msg_type, cdp_port)` | Modify outgoing WS messages |

### Token Management

| Function | Purpose |
|----------|---------|
| `refresh_firebase_token(refresh_token, api_key)` | Exchange refresh_token for fresh JWT |
| `extract_refresh_token_from_har(har_path)` | Find refresh tokens in HAR files |

### Deep Heap Mining

| Function | Purpose |
|----------|---------|
| `mine_heap(heap_path, output_dir)` | Run 100+ regex patterns on V8 heap |
| `mine_heap_deep(heap_path, output_dir)` | Full V8 graph walk (strings, objects, scripts) |
| `decode_jwts_from_findings(findings_json)` | Decode all JWTs from findings |

**What to look for in heaps:**
- JWTs (Firebase, Vercel OIDC, custom)
- API keys (`AIza*`, `client-*`, custom patterns)
- Internal URLs (`*.svc.cluster.local`, `172.x.x.x`, `10.x.x.x`)
- WebRTC SDP (STUN/TURN servers, container IPs)
- Feature flag caches (Statsig evaluations)
- Protobuf definitions (`syntax = "proto3"`)
- Model chain-of-thought reasoning
- Agent orchestration messages (`onReceiveAgentMessage`)
- App/tool definitions (YAML meta configs)
- Cookie values (session tokens, passwords)
- Conversation history
- Character descriptions
- Encryption keys (HPKE, RSA)

### Agent Intelligence Extraction

| Function | Purpose |
|----------|---------|
| `extract_agent_messages(strings_file)` | Reconstruct multi-agent orchestration traces |
| `extract_chain_of_thought(strings_file)` | Find leaked model reasoning |
| `extract_app_schemas(strings_file)` | Parse tool definitions from YAML configs |
| `extract_protobuf_definitions(strings_file)` | Extract proto3 schemas |

---

## The Workflow — How to Analyze Any Web App

### Phase 1: Passive Collection

1. **Capture HAR** — Open Chrome DevTools → Network → record all activity → Export HAR
2. **Capture Heap** — Chrome DevTools → Memory → Take heap snapshot → Save
3. **Download bundle** — Find main JS bundle URL → download

**Pro tip:** Capture heaps at different states (before login, during activity, after).
More state in memory = more findings.

### Phase 2: Automated Analysis

```bash
# Run the full pipeline
python -m scripts.argus.analyze har capture.har --report
python -m scripts.argus.analyze heap snapshot.heapsnapshot
python scripts/heap_deep_parser.py snapshot.heapsnapshot --out data/heap_output/Name_deep
```

### Phase 3: Deep Extraction

```python
from scripts.argus.toolkit import (
    mine_heap, mine_heap_deep, decode_jwts_from_findings,
    extract_agent_messages, extract_chain_of_thought,
    extract_app_schemas, extract_protobuf_definitions,
    decompile_bundle, refresh_firebase_token,
)

# Mine the heap (regex)
result = mine_heap("path/to/heap.heapsnapshot")

# Mine the heap (graph walk)
deep = mine_heap_deep("path/to/heap.heapsnapshot")

# Decode JWTs
jwts = decode_jwts_from_findings("data/heap_output/Name_findings.json")

# Extract agent orchestration
agents = extract_agent_messages("data/heap_output/Name_deep/strings_all.txt")

# Extract chain-of-thought
cot = extract_chain_of_thought("data/heap_output/Name_deep/strings_all.txt")

# Extract app tool definitions
apps = extract_app_schemas("data/heap_output/Name_deep/strings_all.txt")

# Extract protobuf schemas
protos = extract_protobuf_definitions("data/heap_output/Name_deep/strings_all.txt")
```

### Phase 4: Active Probing (Optional)

```python
# Refresh expired tokens
new_token = refresh_firebase_token(refresh_token, api_key)

# Flip feature flags
inject_statsig_gates("https://app.example.com", {"gate_name": True})

# Execute JS via CDP
result = cdp_eval("document.title", cdp_port=9223)
```

### Phase 5: Report Generation

All findings should be saved to `data/argus/reports/` as structured Markdown.
See existing reports for format examples.

---

## Regex Patterns — What heap_miner.py Searches For

### Authentication & Credentials

| Category | Pattern | Example Match |
|----------|---------|---------------|
| JWT | `eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}` | Firebase/OAuth tokens |
| Google API Key | `AIza[A-Za-z0-9_-]{35}` | `AIzaSyDtC7Uwb5pG...` |
| Firebase Config | `[a-z]+-[a-z0-9]+\.firebaseapp\.com` | `sesame-ai-demo.firebaseapp.com` |
| Statsig Key | `client-[A-Za-z0-9]{40,}` | `client-TGCzyFkj...` |
| Sentry DSN | `https://[a-f0-9]+@[a-z0-9.]+\.sentry\.io/\d+` | Sentry error tracking |
| Bearer Token | `Bearer [A-Za-z0-9._-]{20,}` | Authorization headers |
| AWS Key | `AKIA[A-Z0-9]{16}` | AWS access keys |
| Base64 Blob | `[A-Za-z0-9+/]{100,}={0,2}` | Encoded credentials/cookies |

### Infrastructure

| Category | Pattern | Example Match |
|----------|---------|---------------|
| K8s Internal | `[a-z-]+\.svc\.cluster\.local(:\d+)?` | `weaver-gateway...local:8888` |
| Docker IP | `172\.\d+\.\d+\.\d+` | `172.18.0.35` |
| Private IP | `10\.\d+\.\d+\.\d+` | Internal networks |
| WebSocket | `wss?://[^\s"']+` | `wss://connection.openroom.ai/...` |
| STUN/TURN | `(stun\|turn):[^\s"']+` | `turn:35.202.36.29:3478` |

### AI/ML Specific

| Category | Pattern | Example Match |
|----------|---------|---------------|
| Protobuf | `syntax = "proto3"` | Protocol definitions |
| Agent Message | `onReceiveAgentMessage` | Multi-agent orchestration |
| Chain-of-Thought | `I need to respond\|The user is asking\|Let me` | Leaked reasoning |
| Tool Call | `tool_call_status\|tool_call_display_name` | Agent tool invocations |
| MiniMax | `<minimax:tool_call>` | MiniMax model output |
| System Prompt | `system_prompt_map\|system_prompt\|persona` | Prompt configurations |

### Application State

| Category | Pattern | Example Match |
|----------|---------|---------------|
| Session ID | `session_id["\s:=]+[a-f0-9-]{20,}` | Active sessions |
| User ID | `user_id["\s:=]+\d+` | Internal user IDs |
| Email | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | User emails |
| UUID | `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` | Various IDs |
| Cookie | `(cookie\|Cookie)[^\n]{10,100}` | Session cookies |

---

## Auto-Discovery — Making ARGUS Proactive

ARGUS should run automatically when:

1. **A heap snapshot is detected** → Run `mine_heap()` + `mine_heap_deep()` + all extractors
2. **A HAR file is opened** → Run HAR analysis + extract refresh tokens
3. **A web app is being explored** → Download bundle + decompile
4. **JWTs are found** → Decode all, check expiry, attempt refresh
5. **Agent messages are found** → Extract full orchestration trace
6. **Protobuf is found** → Extract schema definitions

The `auto_analyze()` function in `toolkit.py` implements this full pipeline.

---

## Output Structure

```
data/
    argus/
        reports/                    ← Intelligence reports (Markdown)
            heap_deep_dive_combined.md
            sesame_statsig_analysis.md
            openroom_api_reference.md
            ...
    heap_output/
        sesame/                     ← Regex scan results
            combined_findings.json
            *_findings.json
        openroom/                   ← Regex scan results
            combined_findings.json
        Heap-*_deep/                ← Deep parse outputs
            strings_all.txt         ← All unique strings
            strings_large.txt       ← Strings >2KB
            strings_credentials.txt ← Credential-like strings
            findings.json           ← Structured findings
            objects.json            ← Reconstructed JS objects
            scripts.js              ← Extracted script sources
            api_surface.txt         ← Function/method names
            report.txt              ← Summary report
    har_files/                      ← Raw HAR captures
```

---

## Target-Specific Clients

### Sesame AI (`scripts/argus/clients/sesame_client.py`)

Interactive REPL for the Sesame AI voice platform:
- Token management (refresh, store, validate)
- Profile CRUD (get, update nickname/birthday/training/news prefs)
- Feature flag analysis (Statsig gates, configs, environment comparison)
- Bundle decompilation
- Browser launch with CDP

### OpenRoom (`config/argus_openroom.yaml`)

Config-driven endpoint registry for the OpenRoom/Talkie/MiniMax platform:
- Weaver API endpoints
- WebSocket URLs (5 environments)
- CDN domains
- App catalog

---

## Proven Results

| Metric | Sesame AI | OpenRoom.ai |
|--------|-----------|-------------|
| API methods discovered | 53 | 20+ |
| Feature flags mapped | 27 gates, 14 configs | N/A |
| JWTs decoded | 3 | 2 |
| Internal IPs found | 3 | 2 (K8s) |
| Sub-agents discovered | 0 | 5 |
| Apps discovered | 0 | 12 |
| CoT fragments extracted | 0 | 15+ |
| Protobuf schemas | 0 | 1 |
| Security findings | 14 | — |

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARGUS Methodology](../../docs/ARGUS_METHODOLOGY.md) | 13 reusable reconnaissance techniques |
| [Discovery Journal](../../docs/ARGUS_DISCOVERY_JOURNAL.md) | Narrative of all sessions |
| [Sesame Analysis](../../data/argus/reports/sesame_statsig_analysis.md) | Sesame Statsig deep dive |
| [OpenRoom API Reference](../../data/argus/reports/openroom_api_reference.md) | Complete OpenRoom API catalog |
| [Combined Deep Dive](../../data/argus/reports/heap_deep_dive_combined.md) | Both targets combined report |

---

## Change Log

```
v1.52.1 [2026-03-26] — Full documentation, 4 new toolkit functions, auto-discovery,
                        13 techniques, 2 target analyses, discovery journal
v1.52.0 [2026-03-26] — Initial toolkit: 12 functions, 10 techniques, Sesame client
```
