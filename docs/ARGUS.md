# ARGUS — Automated Reconnaissance & Google Universal Surveyor

> **Status:** Active | **Version:** 1.0 | **Scheduler tasks:** `argus-weekly-scan`, `argus-diff-report`

ARGUS is a living API intelligence platform embedded in CosySim that systematically
maps Google's internal APIs (NotebookLM, Gemini AI, AI Studio) using:

- **Chrome DevTools Protocol (CDP)** — intercept every HTTP request without a proxy
- **Playwright UI crawlers** — drive every UI flow to trigger every API endpoint
- **Heap snapshot diffing** — extract rpcids and method names from V8 memory before/after actions
- **tshark TLS decryption** — decode binary gRPC-web payloads for proto reconstruction
- **Auto-documentation** — generates API reference Markdown from live captures

Everything discovered is stored in Nexus and available to all agents instantly.

---

## What It Knows

| Target | Protocol | Known Items | Coverage |
|--------|----------|-------------|----------|
| NotebookLM | batchexecute | 24 rpcids | Growing |
| Gemini | batchexecute | 17 rpcids | Growing |
| AI Studio (MakerSuite) | gRPC-web | 136 methods | Growing |

See `data/argus/registry.json` for the versioned live registry.

---

## Architecture

```
scripts/argus/
├── config.py                  # Baselines: 24 NLM rpcids, 17 Gemini rpcids, 136 AIS methods
├── cdp_bridge.py              # CDP WebSocket client → Chrome :9222
├── network_monitor.py         # Capture all requests/responses on all Chrome tabs
├── tshark_capture.py          # TLS-decrypted packet capture (proto reconstruction)
├── nexus_sink.py              # Store all discoveries in Nexus (entries + Q&A pairs)
├── orchestrator.py            # Master controller — runs all phases, stores results
├── crawlers/
│   ├── base_crawler.py        # Playwright base: attach/launch, screenshot, CDP handoff
│   ├── nlm_crawler.py         # 14 NLM UI flows (24 rpcid coverage target)
│   ├── gemini_crawler.py      # 10 Gemini UI flows (17 rpcid coverage target)
│   └── aistudio_crawler.py    # 15 AI Studio UI flows (136 method coverage target)
├── decoders/
│   ├── batchexecute.py        # f.req decoder + wrb.fr response frame parser
│   ├── grpc_web.py            # gRPC-web binary frame decoder + proto field extractor
│   └── heap_diffing.py        # CDP heap snapshot diff → new API shapes
└── discovery/
    ├── endpoint_registry.py   # Versioned JSON registry at data/argus/registry.json
    ├── rpcid_detector.py      # Compare live vs known rpcids, fire discovery callbacks
    ├── feature_flag_probe.py  # Enumerate hidden flag IDs via GetFeatureFlags (ozz5Z)
    └── proto_reconstructor.py # Build .proto stubs from binary frames + bundle field maps
```

---

## How It Works

### The Crawl Loop

For every UI flow, ARGUS:

1. Attaches network monitor (CDP `Network.enable` on all tabs)
2. Takes a heap snapshot before the action
3. Performs the action (click, type, navigate) via Playwright
4. Drains all captured network requests/responses
5. Takes another heap snapshot
6. Diffs the heaps → new strings → new rpcids/methods
7. Decodes captured traffic:
   - batchexecute → rpcid + JSON payload
   - gRPC-web → service/method + proto field numbers
8. Registers everything in the endpoint registry
9. Stores new discoveries in Nexus

### Protocol Details

**NotebookLM + Gemini (batchexecute):**
```
POST https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
Body: f.req=[[["rpcid","json_payload",null,"generic"]]]
Auth: Session cookies (__Secure-1PSID, __Secure-1PAPISID)
Response: )]}'\n + wrb.fr frames
```

**AI Studio (gRPC-web):**
```
POST https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{Method}
Auth: Authorization: SAPISIDHASH {ts}_{sha1}
Content-Type: application/grpc-web+json OR application/grpc-web+proto
```

**SAPISIDHASH:** `sha1(f"{timestamp} {SAPISID} {origin}")`

---

## Usage

### Quick Run (requires Chrome + CDP)

```powershell
# Start Chrome with CDP enabled (if not already running)
# Chrome Settings → More tools → Developer tools → Remote debugging

# Full scan
python -m scripts.argus.orchestrator

# Specific target
python -m scripts.argus.orchestrator --target nlm

# Probe NLM feature flags
python -m scripts.argus.orchestrator --probe-flags

# Generate docs from current registry only
python -m scripts.argus.orchestrator --docs-only
```

### Scheduler (automatic weekly)

ARGUS runs automatically via the scheduler:
- `argus-weekly-scan` — full crawl (all 3 targets), every 7 days
- `argus-diff-report` — registry diff vs baseline, every 7 days

```powershell
# Trigger manually
python -m engine.nexus.scheduler_daemon run argus-weekly-scan
python -m engine.nexus.scheduler_daemon run argus-diff-report
```

### Query Results via Nexus

All discoveries are stored in Nexus under `category=argus`:

```powershell
python -m engine.nexus.bridge search "argus rpcid"
python -m engine.nexus.bridge ask "What new NLM rpcids did ARGUS find?"
python -m engine.nexus.bridge search "AI Studio method"
```

---

## TLS Decryption Setup (for proto reconstruction)

Chrome must be launched with `SSLKEYLOGFILE` for tshark to decrypt HTTPS:

```powershell
$env:SSLKEYLOGFILE = "C:\Files\Models\CosySim\artifacts\argus\tls\sslkeys.log"
Start-Process "chrome.exe"
```

Then capture:
```powershell
python -c "from scripts.argus.tshark_capture import TsharkCapture; tc=TsharkCapture(); tc.start()"
# ... navigate in Chrome ...
python -c "from scripts.argus.tshark_capture import TsharkCapture; tc=TsharkCapture(); tc.stop()"
```

---

## CDP Requirements

```powershell
# Check Chrome is exposing CDP
Invoke-RestMethod http://localhost:9222/json
```

Chrome must be running. ARGUS attaches to the existing session without closing your tabs.

---

## Generated Output Files

| File | Description |
|------|-------------|
| `data/argus/registry.json` | Versioned endpoint + rpcid registry (all discoveries) |
| `data/argus/feature_flags.json` | Active NLM feature flag IDs |
| `data/argus/protos/*.proto` | Reconstructed .proto stubs |
| `artifacts/argus/har/**/*.har` | Raw imported HAR captures and dumps |
| `artifacts/argus/screenshots/*.png` | Vision/browser screenshots and debug captures |
| `artifacts/argus/pcap/*.pcapng` | Raw packet captures (tshark) |
| `docs/NLM_API_REFERENCE.md` | Auto-generated NLM API reference |
| `docs/GEMINI_API_REFERENCE.md` | Auto-generated Gemini API reference |
| `docs/AISTUDIO_API_REFERENCE.md` | Auto-generated AI Studio API reference |

---

## Key Discoveries (Baseline)

### NotebookLM rpcids (24 known)
- `bv7rAb` — CreateNotebook
- `dlXLMc` — GetNotebook
- `UbmKqb` — ListNotebooks
- `NbGLKb` — AddSource
- `ozz5Z` — GetFeatureFlags
- `Bgzyjc` — GenerateFreeFormStreamed (main chat)
- `VHpbob` — GetAudioOverviewStatus
- `Ygx6Tb` — StartAudioOverview
- ... (see config.py for full list)

### Gemini rpcids (17 known)
- `boaYGb` — ProxyUnaryCall (main generate)
- `NXpLKc` — ListLinkedNotebooks (NLM bridge)
- `k9yDXd` — SetModel
- `XqsOBb` — GetModelInfo
- ... (see config.py for full list)

### AI Studio methods (136 known)
- `StreamGenerateContent` — main generation endpoint
- `ListModels` / `GetModel` — model management
- `ListPrompts` / `GetPrompt` / `CreatePrompt` — prompt CRUD
- `ListTunedModels` / `CreateTunedModel` — fine-tuning
- `ListCachedContents` / `CreateCachedContent` — context caching
- `ListApplets` / `GetApplet` / `DeployApplet` — deployed apps
- ... (see config.py for full list)

---

## Extending ARGUS

### Add a new crawler flow

```python
# In scripts/argus/crawlers/nlm_crawler.py
async def _new_flow_name(self) -> None:
    """Trigger rpcid XYZ by doing ..."""
    element = await self._page.query_selector("some-selector")
    if element:
        await element.click()
        await asyncio.sleep(1)

# Register in run_flows()
await self.step("new_flow_name", self._new_flow_name)
```

### Add a new discovery pattern

```python
# In scripts/argus/discovery/rpcid_detector.py
# Add to _is_candidate() or analyse_bundle() to catch new patterns
```

---

## Philosophy

> "Every time Google updates their UI, ARGUS knows before anyone else."

The system never stops learning. Every crawl adds to the registry.
Every new rpcid goes into Nexus. Every .proto stub gets refined.
The more it runs, the more it knows.

---

## LiveDebugger — Real-Time Scene Diagnostics

The LiveDebugger is a separate ARGUS component that reuses the CDP infrastructure
for real-time CosySim scene debugging. While the crawlers map external APIs, the
LiveDebugger points the same CDP tooling inward — attaching to running scene pages
to capture console output, inspect the DOM, profile performance, and diagnose UI
issues without leaving the terminal or agent context.

### Architecture

```
scripts/argus/
├── live_debugger.py      # Core async debugger (1149 lines)
├── cdp_bridge.py         # CDP WebSocket client (used by both crawlers and debugger)
└── tools/
    └── debug_scene.py    # CLI tool with 10 subcommands (306 lines)

engine/skills/builtin/
└── debugger_skills.py    # 14 MCP skills for agent access (600 lines)
```

### Core Capabilities

1. **Console Streaming** — Captures `console.log`, `console.warn`, and
   `console.error` from the page in real-time via CDP `Runtime.consoleAPICalled`.
2. **Network Monitoring** — Intercepts all HTTP requests and responses, tracks
   loading time, and captures request/response bodies.
3. **DOM Inspection** — Executes arbitrary JavaScript in page context via CDP
   `Runtime.evaluate`. Query DOM state, check element visibility, read computed
   styles.
4. **Z-Stack Analysis** — Reports the z-index layering of all positioned elements
   to diagnose overlay and blocking issues.
5. **Click Testing** — Uses `document.elementFromPoint()` to verify which element
   receives clicks at specific coordinates, exposing invisible overlays.
6. **Vision Analysis** — Takes CDP screenshots and can analyse them with LMStudio
   vision models (Qwen2-VL) for visual regression detection.
7. **Performance Profiling** — Captures `performance.timing`, resource loading
   waterfall, and memory usage.
8. **Scene Health Check** — Automated validation: page loads, Socket.IO connects,
   no console errors, API routes respond.

### CLI Usage

```powershell
# Full diagnostics
python -m scripts.argus.tools.debug_scene --port 5556

# Live console monitoring (Ctrl+C to stop)
python -m scripts.argus.tools.debug_scene --port 5556 --watch

# Execute JavaScript
python -m scripts.argus.tools.debug_scene --port 5556 --eval "document.title"

# DOM queries
python -m scripts.argus.tools.debug_scene --port 5556 --dom "div.ph-director-panel"

# Z-index stack analysis
python -m scripts.argus.tools.debug_scene --port 5556 --z-stack

# Click target at coordinates
python -m scripts.argus.tools.debug_scene --port 5556 --click-test 400,300

# Take screenshot
python -m scripts.argus.tools.debug_scene --port 5556 --screenshot

# Performance metrics
python -m scripts.argus.tools.debug_scene --port 5556 --perf

# List Chrome tabs
python -m scripts.argus.tools.debug_scene --port 5556 --tabs

# Scene health check
python -m scripts.argus.tools.debug_scene --port 5556 --health
```

### MCP Skills (14 skills, pack="debugger")

All skills are exposed to agents via the `@skill(pack="debugger")` decorator in
`debugger_skills.py`. Each skill wraps the async LiveDebugger core with a sync
entry point.

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `debug_scene` | Full diagnostics snapshot | `port` |
| `debug_watch` | Live console + network monitor | `port`, `duration` |
| `debug_console` | Console log capture | `port`, `duration` |
| `debug_network` | Network traffic capture | `port`, `duration` |
| `debug_eval` | Execute JS in page | `port`, `expression` |
| `debug_dom` | Query DOM elements | `port`, `selector` |
| `debug_z_stack` | Z-index layer analysis | `port` |
| `debug_click_test` | Check click target | `port`, `x`, `y` |
| `debug_screenshot` | Capture screenshot | `port`, `output_path` |
| `debug_click` | Simulate click | `port`, `selector` |
| `debug_navigate` | Navigate to URL | `port`, `url` |
| `debug_perf` | Performance metrics | `port` |
| `debug_list_tabs` | List Chrome tabs | *(none)* |
| `debug_health` | Scene health check | `port` |

### Integration with Existing ARGUS

- LiveDebugger reuses `CDPBridge` and `CDPSession` from `cdp_bridge.py` — the
  same WebSocket client that powers the crawlers.
- Same CDP port (`localhost:9222`) used by crawlers and debugger. Both can
  coexist on different tabs.
- Discoveries from debugging (new endpoints, JS errors) can be stored in Nexus
  via `nexus_sink.py`.
- Screenshots are stored in `data/argus/screenshots/`.

### Async Pattern

The LiveDebugger is fully async (`asyncio`). MCP skills use a sync wrapper to
bridge the gap:

```python
def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
```

> **Important:** Must use `asyncio.new_event_loop()` (not `asyncio.get_event_loop()`)
> to avoid conflicts with already-running loops and to ensure compatibility with
> the full test suite.

### Testing

```powershell
python -m pytest tests/test_live_debugger.py -v  # 57 tests
```
