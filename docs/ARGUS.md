# ARGUS -- Intelligence Platform

> CosySim Documentation -- v1.51.1 [2026-03-25]
>
> Browser automation, API surface discovery, RPC registry, and the LiveDebugger.

---

## Table of Contents

1. [Overview](#overview)
2. [CDP / Playwright](#cdp--playwright)
3. [LiveDebugger](#livedebugger--real-time-scene-diagnostics)
4. [API Catalog](#api-catalog)
5. [Token Harvesting](#token-harvesting)
6. [Configuration](#configuration)
7. [Cross-References](#cross-references)
8. [Change Log](#change-log)

---

## Overview

ARGUS (Automated Reconnaissance & Google Universal Surveyor) is a living API
intelligence platform embedded in CosySim. It systematically maps Google's
internal APIs (NotebookLM, Gemini AI, AI Studio, Colab, Apps Script, Workspace)
using browser automation and traffic analysis, then stores every discovery in
Nexus so all agents can use it immediately.

Core techniques:

- **Chrome DevTools Protocol (CDP)** -- intercept every HTTP request without a proxy
- **Playwright UI crawlers** -- drive every UI flow to trigger every API endpoint
- **Heap snapshot diffing** -- extract rpcids and method names from V8 memory before/after actions
- **tshark TLS decryption** -- decode binary gRPC-web payloads for proto reconstruction
- **Auto-documentation** -- generates API reference Markdown from live captures

**Catalog size:**

| Target | Protocol | Known Items | Coverage |
|--------|----------|-------------|----------|
| NotebookLM | batchexecute | 49 rpcids | 67% observed |
| Gemini | batchexecute | 36 rpcids | 47% observed |
| AI Studio (MakerSuite) | gRPC-web | 150+ methods | Growing |
| Google Colab | gRPC-web | 10 methods | 0% observed |
| Apps Script | batchexecute | 14 rpcids | 0% observed |
| Workspace Gemini | mixed | 49 operations | 0% observed |

See `data/argus/registry.json` for the versioned live registry.

---

## CDP / Playwright

### Architecture

```
scripts/argus/
+-- config.py                  # Baselines: 49 NLM rpcids, 36 Gemini rpcids, 150+ AIS methods
+-- cdp_bridge.py              # CDP WebSocket client -> Chrome :9222
+-- network_monitor.py         # Capture all requests/responses on all Chrome tabs
+-- tshark_capture.py          # TLS-decrypted packet capture (proto reconstruction)
+-- nexus_sink.py              # Store all discoveries in Nexus (entries + Q&A pairs)
+-- orchestrator.py            # Master controller -- runs all phases, stores results
+-- crawlers/
|   +-- base_crawler.py        # Playwright base: attach/launch, screenshot, CDP handoff
|   +-- nlm_crawler.py         # 14 NLM UI flows (49 rpcid coverage target)
|   +-- gemini_crawler.py      # 10 Gemini UI flows (36 rpcid coverage target)
|   +-- aistudio_crawler.py    # 15 AI Studio UI flows (150+ method coverage target)
+-- decoders/
|   +-- batchexecute.py        # f.req decoder + wrb.fr response frame parser
|   +-- grpc_web.py            # gRPC-web binary frame decoder + proto field extractor
|   +-- heap_diffing.py        # CDP heap snapshot diff -> new API shapes
+-- discovery/
    +-- endpoint_registry.py   # Versioned JSON registry at data/argus/registry.json
    +-- rpcid_detector.py      # Compare live vs known rpcids, fire discovery callbacks
    +-- feature_flag_probe.py  # Enumerate hidden flag IDs via GetFeatureFlags (ozz5Z)
    +-- proto_reconstructor.py # Build .proto stubs from binary frames + bundle field maps
```

### The Crawl Loop

For every UI flow, ARGUS:

1. Attaches network monitor (CDP `Network.enable` on all tabs)
2. Takes a heap snapshot before the action
3. Performs the action (click, type, navigate) via Playwright
4. Drains all captured network requests/responses
5. Takes another heap snapshot
6. Diffs the heaps -- new strings -- new rpcids/methods
7. Decodes captured traffic:
   - batchexecute -- rpcid + JSON payload
   - gRPC-web -- service/method + proto field numbers
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

### gRPC Service Paths

```
AI Studio:  google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{Method}
Applets:    google.alkali.boq.makersuite.makersuiteappletcontrol.proto.MakersuiteAppletControlService/{Method}
Colab AI:   google.internal.colab.v1.AIService/{Method}
Colab RT:   google.internal.colab.v1.RuntimeService/{Method}
NLM gRPC:   google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/{Method}
```

### TLS Decryption Setup (for proto reconstruction)

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

### CDP Requirements

```powershell
# Check Chrome is exposing CDP
Invoke-RestMethod http://localhost:9222/json
```

Chrome must be running. ARGUS attaches to the existing session without closing your tabs.

### Usage

**Quick Run (requires Chrome + CDP):**

```powershell
# Full scan
python -m scripts.argus.orchestrator

# Specific target
python -m scripts.argus.orchestrator --target nlm

# Probe NLM feature flags
python -m scripts.argus.orchestrator --probe-flags

# Generate docs from current registry only
python -m scripts.argus.orchestrator --docs-only
```

**Scheduler (automatic weekly):**

ARGUS runs automatically via the scheduler:
- `argus-weekly-scan` -- full crawl (all 3 targets), every 7 days
- `argus-diff-report` -- registry diff vs baseline, every 7 days

```powershell
# Trigger manually
python -m engine.nexus.scheduler_daemon run argus-weekly-scan
python -m engine.nexus.scheduler_daemon run argus-diff-report
```

**Query Results via Nexus:**

All discoveries are stored in Nexus under `category=argus`:

```powershell
python -m engine.nexus.bridge search "argus rpcid"
python -m engine.nexus.bridge ask "What new NLM rpcids did ARGUS find?"
python -m engine.nexus.bridge search "AI Studio method"
```

### Generated Output Files

| File | Description |
|------|-------------|
| `data/argus/registry.json` | Versioned endpoint + rpcid registry (all discoveries) |
| `data/argus/feature_flags.json` | Active NLM feature flag IDs |
| `data/argus/protos/*.proto` | Reconstructed .proto stubs |
| `artifacts/argus/har/**/*.har` | Raw imported HAR captures and dumps |
| `artifacts/argus/screenshots/*.png` | Vision/browser screenshots and debug captures |
| `artifacts/argus/pcap/*.pcapng` | Raw packet captures (tshark) |
| `docs/NEXUS.md` | Auto-generated NLM API reference |
| `docs/GEMINI_API_REFERENCE.md` | Auto-generated Gemini API reference |
| `docs/AISTUDIO_API_REFERENCE.md` | Auto-generated AI Studio API reference |

### Extending ARGUS

**Add a new crawler flow:**

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

**Add a new discovery pattern:**

```python
# In scripts/argus/discovery/rpcid_detector.py
# Add to _is_candidate() or analyse_bundle() to catch new patterns
```

---

## LiveDebugger -- Real-Time Scene Diagnostics

The LiveDebugger reuses the CDP infrastructure for real-time CosySim scene
debugging. While the crawlers map external APIs, the LiveDebugger points the
same CDP tooling inward -- attaching to running scene pages to capture console
output, inspect the DOM, profile performance, and diagnose UI issues without
leaving the terminal or agent context.

### Architecture

```
scripts/argus/
+-- live_debugger.py      # Core async debugger (1149 lines)
+-- cdp_bridge.py         # CDP WebSocket client (used by both crawlers and debugger)
+-- tools/
    +-- debug_scene.py    # CLI tool with 10 subcommands (306 lines)

engine/skills/builtin/
+-- debugger_skills.py    # 14 MCP skills for agent access (600 lines)
```

### Core Capabilities

1. **Console Streaming** -- Captures `console.log`, `console.warn`, and
   `console.error` from the page in real-time via CDP `Runtime.consoleAPICalled`.
2. **Network Monitoring** -- Intercepts all HTTP requests and responses, tracks
   loading time, and captures request/response bodies.
3. **DOM Inspection** -- Executes arbitrary JavaScript in page context via CDP
   `Runtime.evaluate`. Query DOM state, check element visibility, read computed
   styles.
4. **Z-Stack Analysis** -- Reports the z-index layering of all positioned elements
   to diagnose overlay and blocking issues.
5. **Click Testing** -- Uses `document.elementFromPoint()` to verify which element
   receives clicks at specific coordinates, exposing invisible overlays.
6. **Vision Analysis** -- Takes CDP screenshots and can analyse them with LMStudio
   vision models (Qwen2-VL) for visual regression detection.
7. **Performance Profiling** -- Captures `performance.timing`, resource loading
   waterfall, and memory usage.
8. **Scene Health Check** -- Automated validation: page loads, Socket.IO connects,
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

### Integration with ARGUS Crawlers

- LiveDebugger reuses `CDPBridge` and `CDPSession` from `cdp_bridge.py` -- the
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

---

## API Catalog

The full RPC registry maintained by ARGUS. All data from live crawls and HAR
imports, stored at `data/argus/registry.json`.

**Total baseline operations:** 184 | **Observed in crawls:** 200 | **New discoveries:** 152

| Service | Baseline | Seen | New | Coverage |
|---------|----------|------|-----|----------|
| NotebookLM (batchexecute) | 49 | 33 | 2 | 67% |
| Gemini (BardChatUi) | 36 | 17 | 0 | 47% |
| AI Studio (MakerSuite gRPC) | 0 | 150 | 150 | -- |
| Google Colab (gRPC) | 10 | 0 | 0 | 0% |
| Apps Script (batchexecute) | 14 | 0 | 0 | 0% |
| Workspace Gemini (mixed) | 49 | 0 | 0 | 0% |
| NLM gRPC (proto) | 2 | 0 | 0 | 0% |
| Heap-Discovered (unconfirmed) | 24 | 0 | 0 | 0% |

### NotebookLM rpcids (49 known)

Key rpcids for CosySim integration:

| rpcid | Operation | Notes |
|-------|-----------|-------|
| `bv7rAb` | CreateNotebook | |
| `dlXLMc` | GetNotebook | |
| `UbmKqb` | ListNotebooks | |
| `NbGLKb` | AddSource | |
| `ozz5Z` | GetFeatureFlags | Shared with Gemini |
| `Bgzyjc` | GenerateFreeFormStreamed | Main chat endpoint |
| `VHpbob` | GetAudioOverviewStatus | |
| `Ygx6Tb` | StartAudioOverview | |
| `izAoDd` | Add URL/text source | URL, YouTube, Sheets, image, text paste |
| `o4cbdc` | Register file upload | Returns upload URL + source ID |
| `rLM1Ne` | Poll source processing | Returns pending source IDs |
| `hPTbtc` | List sources | All source IDs in a notebook |
| `LBwxtb` | Delete source / blog post | Multipurpose by payload shape |
| `CYK0Xb` | Create note (report) | ~10k word prompt -> full document |
| `QA9ei` | Generate audio podcast | 30-min deep dive / brief / critique / debate |
| `gArtLc` | Poll / list artifacts | Get download URL when COMPLETE |
| `ciyUvf` | Generate flashcards | Instant Q&A pairs from sources |
| `R7cb6c` | Generate quiz | Multiple choice or true/false |
| `yyryJe` | Generate mind map | Nested concept JSON tree |
| `Krh3pd` | Export to Sheets | Returns live Google Sheet URL |
| `tr032e` | Source summary | Gemini summary of one source |
| `ub2Bae` | List notebooks | All notebooks in account |
| `s0tc2d` | Rename notebook | Update display name |

See `scripts/argus/config.py` for the full baseline list.

### Gemini rpcids (36 known)

| rpcid | Description | Status | Observed | Last Seen |
|-------|-------------|--------|----------|-----------|
| `ku4Jyf` | Code execution request | active | 11 | 2026-03-08 |
| `K4WWud` | Conversation management -- list, create, delete | active | 7 | 2026-03-08 |
| `mMEAEd` | CountTokens | -- | 0 | -- |
| `VUBhEd` | CreateCachedContent | -- | 0 | -- |
| `BgXnQc` | CreateFile | -- | 0 | -- |
| `sPOurf` | DeleteCachedContent | -- | 0 | -- |
| `qVSQ5c` | DeleteFile | -- | 0 | -- |
| `L5adhe` | Draft / edit message -- large state initialization | active | 97 | 2026-03-08 |
| `MaZiqc` | Extension/plugin interaction | active | 14 | 2026-03-08 |
| `ozz5Z` | Feature flags / account state (shared with NLM) | active | 7 | 2026-03-08 |
| `jKHnxe` | GenerateContent | -- | 0 | -- |
| `ESY5D` | Get conversation history / feature flags list | active | 72 | 2026-03-08 |
| `NXpLKc` | Get linked notebooks (cross-product bridge) | active | 2 | 2026-03-05 |
| `XqA3Ic` | Get storybook detail -- fetch specific gem by ID | -- | 0 | never |
| `sJBwce` | Get subscription tiers -- Pro/Free tier info | -- | 0 | never |
| `jPv1oc` | GetCachedContent | -- | 0 | -- |
| `ozVbQb` | GetFile | -- | 0 | -- |
| `XqsOBb` | GetModel | -- | 0 | -- |
| `jGArJ` | List my content -- filtered /mystuff | -- | 0 | never |
| `ZKcapf` | List saved info -- paginated saved content | -- | 0 | never |
| `HcT8bb` | List storybook gems | -- | 0 | never |
| `dXH9nb` | ListCachedContents | -- | 0 | -- |
| `mfvMVb` | ListFiles | -- | 0 | -- |
| `k9yDXd` | ListModels | -- | 0 | -- |
| `DYBcR` | Locale / language preferences (shared with NLM) | active | 7 | 2026-03-08 |
| `otAQ7b` | Main chat generation -- send message, get response | active | 7 | 2026-03-08 |
| `CNgdBe` | Model selection / configuration | active | 7 | 2026-03-08 |
| `boaYGb` | ProxyUnaryCall | -- | 0 | -- |
| `GPRiHf` | Response rating / feedback | active | 7 | 2026-03-08 |
| `qpEbW` | Search conversation history | active | 11 | 2026-03-08 |
| `aPya6c` | Session initialization / heartbeat | active | 70 | 2026-03-08 |
| `PCck7e` | Share conversation / gem | active | 20 | 2026-03-08 |
| `r7Bvze` | StreamGenerateContent | -- | 0 | -- |
| `maGuAc` | Upload attachment / file | active | 14 | 2026-03-08 |
| `cYRIkd` | User preferences / settings | active | 7 | 2026-03-08 |
| `o30O0e` | User profile fetch (contacts/identity) | active | 7 | 2026-03-08 |

### AI Studio Methods (150+ observed)

**Endpoint:** `https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService/{Method}`

**Auth:** `Authorization: SAPISIDHASH <ts>_<sha1>` + session cookies

**Format:** gRPC-web with binary proto encoding OR JSON mode

#### Cancel

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CancelCodeAssistantOfflineGeneration` | -- | 0 | never |
| `CancelTuningJob` | -- | 0 | never |

#### Check

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CheckCloudProjectForTermsOfService` | -- | 0 | never |
| `CheckCloudRunService` | -- | 0 | never |
| `CheckImage` | -- | 0 | never |

#### Count

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CountSessionTurns` | -- | 0 | never |
| `CountTokens` | active | 21 | 2026-03-05 |

#### Create

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `CreateApplet` | -- | 0 | never |
| `CreateCloudApiKey` | -- | 0 | never |
| `CreateCloudProject` | -- | 0 | never |
| `CreateCloudRunService` | -- | 0 | never |
| `CreateContextCache` | -- | 0 | never |
| `CreateDataset` | -- | 0 | never |
| `CreateGitHubRepository` | -- | 0 | never |
| `CreateInteraction` | -- | 0 | never |
| `CreatePrompt` | active | 5 | 2026-03-05 |
| `CreateSession` | -- | 0 | never |
| `CreateTunedModel` | -- | 0 | never |

#### Delete

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `DeleteApplet` | -- | 0 | never |
| `DeleteCloudApiKey` | -- | 0 | never |
| `DeleteCloudRunService` | -- | 0 | never |
| `DeleteContextCache` | -- | 0 | never |
| `DeleteDataset` | -- | 0 | never |
| `DeletePrompt` | -- | 0 | never |
| `DeleteSession` | -- | 0 | never |
| `DeleteTunedModel` | -- | 0 | never |
| `DeleteUploadedFile` | -- | 0 | never |

#### Export / Fetch

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `ExportDataset` | -- | 0 | never |
| `FetchMetricTimeSeries` | active | 37 | 2026-03-08 |

#### Generate

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `GenerateAccessToken` | active | 142 | 2026-03-17 |
| `GenerateCodeAssistantSuggestionChips` | active | 34 | 2026-03-05 |
| `GenerateContent` | active | 7 | 2026-03-05 |
| `GenerateFunctionCallAnswer` | -- | 0 | never |
| `GenerateGitHubCommitMessage` | -- | 0 | never |
| `GenerateImage` | -- | 0 | never |
| `GenerateTitle` | active | 5 | 2026-03-05 |
| `GenerateVideo` | -- | 0 | never |

#### Get

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `GetAnnouncementBanner` | -- | 0 | never |
| `GetApplet` | active | 18 | 2026-03-08 |
| `GetAppletCloudRunServiceLogs` | -- | 0 | never |
| `GetAppletOutputMetadata` | -- | 0 | never |
| `GetCodeAssistantSnapshot` | active | 10 | 2026-03-05 |
| `GetDataset` | -- | 0 | never |
| `GetExtension` | -- | 0 | never |
| `GetFeatureFlags` | -- | 0 | never |
| `GetGenerateVideoOperation` | -- | 0 | never |
| `GetGitHubAuthStatus` | -- | 0 | never |
| `GetGitHubSettings` | -- | 0 | never |
| `GetGitHubStatus` | -- | 0 | never |
| `GetGroundingPassage` | -- | 0 | never |
| `GetImFeelingLuckyOptions` | -- | 0 | never |
| `GetLoggingContext` | active | 62 | 2026-03-08 |
| `GetModel` | -- | 0 | never |
| `GetPrepayEligibility` | -- | 0 | never |
| `GetProjectUsageLimit` | -- | 0 | never |
| `GetPrompt` | -- | 0 | never |
| `GetSample` | -- | 0 | never |
| `GetSession` | -- | 0 | never |
| `GetSessionTurn` | -- | 0 | never |
| `GetSharedPrompt` | -- | 0 | never |
| `GetStarterPrompts` | -- | 0 | never |
| `GetSurvey` | -- | 0 | never |
| `GetTunedModel` | -- | 0 | never |
| `GetTuningJob` | -- | 0 | never |
| `GetUploadedFile` | -- | 0 | never |
| `GetUserPreferences` | active | 62 | 2026-03-08 |
| `GetUserRestrictions` | active | 15 | 2026-03-08 |
| `GetVersionInfo` | -- | 0 | never |

#### Import

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `ImportGitHubRepository` | -- | 0 | never |
| `ImportProject` | -- | 0 | never |

#### List

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `ListAppletRunConfigurations` | -- | 0 | never |
| `ListAppletTemplates` | -- | 0 | never |
| `ListApplets` | active | 4 | 2026-03-05 |
| `ListBillingAccounts` | -- | 0 | never |
| `ListCloudApiKeys` | active | 8 | 2026-03-05 |
| `ListCloudProjects` | active | 12 | 2026-03-08 |
| `ListCodeAssistantConfigurations` | active | 62 | 2026-03-08 |
| `ListCodeAssistantFeatures` | active | 36 | 2026-03-08 |
| `ListCodeAssistantOfflineGenerations` | active | 18 | 2026-03-08 |
| `ListCodeGenSuggestionCards` | active | 10 | 2026-03-05 |
| `ListContextCaches` | -- | 0 | never |
| `ListDatasets` | -- | 0 | never |
| `ListDriveApplets` | -- | 0 | never |
| `ListExtensions` | -- | 0 | never |
| `ListGitHubRepositories` | -- | 0 | never |
| `ListImportedProjects` | active | 9 | 2026-03-08 |
| `ListModels` | active | 78 | 2026-03-08 |
| `ListPromos` | active | 4 | 2026-03-05 |
| `ListPrompts` | active | 125 | 2026-03-08 |
| `ListRecentApplets` | active | 74 | 2026-03-08 |
| `ListSessionTurns` | -- | 0 | never |
| `ListSessions` | -- | 0 | never |
| `ListTunedModels` | -- | 0 | never |
| `ListTuningJobs` | -- | 0 | never |
| `ListUnsetAppletSecrets` | active | 44 | 2026-03-08 |
| `ListUploadedFiles` | -- | 0 | never |

#### Stream

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `StreamBidiGenerateContent` | -- | 0 | never |
| `StreamCodeAssistantOfflineGeneration` | active | 26 | 2026-03-05 |
| `StreamExtractVideoFrames` | -- | 0 | never |
| `StreamGenerateContent` | -- | 0 | never |

#### Update

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `UpdateCloudProject` | -- | 0 | never |
| `UpdateCloudRunService` | -- | 0 | never |
| `UpdateDataset` | -- | 0 | never |
| `UpdateProjectUsageLimit` | -- | 0 | never |
| `UpdatePrompt` | -- | 0 | never |

#### Other

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `AuthenticateGitHub` | -- | 0 | never |
| `BidiGenerateContent` | -- | 0 | never |
| `BulkDeleteSessionTurns` | -- | 0 | never |
| `CodeAssistant` | -- | 0 | never |
| `CodeAssistantOffline` | active | 28 | 2026-03-05 |
| `ComputeStagedGitHubDiff` | -- | 0 | never |
| `ConnectApplet` | -- | 0 | never |
| `DisconnectApplet` | -- | 0 | never |
| `EmbedContent` | -- | 0 | never |
| `EnhancePrompt` | -- | 0 | never |
| `GeminiSpeechToText` | -- | 0 | never |
| `GoogleSearch` | -- | 0 | never |
| `LoadBundledApplet` | -- | 0 | never |
| `LoadCodeAssistantInteractionHistory` | active | 18 | 2026-03-08 |
| `LoadCodeAssistantSnapshots` | -- | 0 | never |
| `LoadDriveApplet` | -- | 0 | never |
| `Log` | active | 26 | 2026-03-05 |
| `ProvisionAndInitializeApplet` | active | 28 | 2026-03-05 |
| `ProxyStreamedCall` | -- | 0 | never |
| `ProxyUnaryCall` | active | 4 | 2026-03-05 |
| `ProxyUnaryFileApiCall` | -- | 0 | never |
| `PushNewCommit` | -- | 0 | never |
| `QueryCodeSearch` | -- | 0 | never |
| `RecordSessionTurnFeedback` | -- | 0 | never |
| `RecordSurveyResponse` | -- | 0 | never |
| `RerunTuningJob` | -- | 0 | never |
| `SaveApplet` | active | 26 | 2026-03-05 |
| `SaveDriveApplet` | -- | 0 | never |
| `SharePrompt` | -- | 0 | never |
| `StoreRecentApplet` | active | 41 | 2026-03-08 |
| `UpgradeAndDisablePrepay` | -- | 0 | never |
| `UploadScs` | -- | 0 | never |
| `batchGenerateContent` | -- | 0 | never |

### Google Colab Methods (10 known)

**Endpoint:** `https://colab.research.google.com/$rpc/google.internal.colab.v1.{Service}/{Method}`

**Auth:** Session cookies + `X-Goog-AuthUser` header

**Format:** gRPC-web binary proto

| Method | Status | Observed | Last Seen |
|--------|--------|----------|-----------|
| `AgentCreateTask` | -- | 0 | never |
| `AgentQuerySuggestions` | -- | 0 | never |
| `AgentQueryTask` | -- | 0 | never |
| `AgentUpdateTask` | -- | 0 | never |
| `CompleteCode` | -- | 0 | never |
| `ExecuteCell` | -- | 0 | never |
| `GetRuntimeProxyToken` | -- | 0 | never |
| `GetUserInfo` | -- | 0 | never |
| `ListAssignments` | -- | 0 | never |
| `SmartPaste` | -- | 0 | never |

### Apps Script rpcids (14 known)

**Endpoint:** `https://script.google.com/_/AppsMakerFrontendUi/data/batchexecute`

**Format:** Same batchexecute f.req encoding as NLM/Gemini

| rpcid | Description | Status | Observed |
|-------|-------------|--------|----------|
| `pEig0e` | Execute a named function in the script project | -- | 0 |
| `OQOG2e` | Get all files in the script project | -- | 0 |
| `LuHlxe` | Get current editor state/mode | -- | 0 |
| `AvwHP` | Get extended project metadata with container info | -- | 0 |
| `NFMk7c` | Get project metadata (name, dates, owner) | -- | 0 |
| `yFXSbd` | Get project revision history with tour hints | -- | 0 |
| `UvGaob` | Get project settings and configuration | -- | 0 |
| `AJ6bre` | Initialize page/view state | -- | 0 |
| `zzomTc` | List project version history with pagination | -- | 0 |
| `OOPYjd` | List script execution history with status filters | -- | 0 |
| `KKLVD` | List script triggers (time-driven, event-driven) | -- | 0 |
| `toGAmc` | Save code content to a script file | -- | 0 |
| `GXx9jd` | Save/update project with full metadata | -- | 0 |
| `ivJzse` | Update cursor position in code editor | -- | 0 |

### Google Workspace Operations (49 known)

**Hosts:** `appsgenaiserver-pa.clients6.google.com`, `docs.google.com`, `sheets.google.com`, `drive.google.com`

**Auth:** API key + session cookies OR SAPISIDHASH

**Format:** REST JSON, gRPC-JSON transcoding, or batchexecute

#### Cloud Search

| Method | Description |
|--------|-------------|
| `query_search` | Cross-workspace semantic search query |

#### Docs Gemini

| Method | Description |
|--------|-------------|
| `help_me_create` | Generate document content from a prompt |
| `match_style` | Match generated content style to existing document |

#### Drive Gemini

| Method | Description |
|--------|-------------|
| `ai_overview_search` | Semantic search across Drive files using AI Overviews |
| `ask_gemini` | Ask Gemini a question about Drive files |

#### Drive V2Internal

| Method | Description |
|--------|-------------|
| `copy_file` | Copy a file in Drive (template duplication) |
| `export_file` | Export a Workspace file in a specified format |
| `get_file` | Get file metadata from Drive |
| `get_permissions` | List permissions on a Drive file |
| `insert_permission` | Add/modify sharing permissions |
| `list_files` | List/search files in Drive |
| `trash_file` | Move file to trash |
| `update_file` | Update file metadata (title, description, parents) |
| `upload_file` | Upload file to Drive with metadata (multipart) |

#### People Stack

| Method | Description |
|--------|-------------|
| `autocomplete` | Autocomplete people/contacts for sharing and @mentions |
| `autocomplete_alt` | Alternative API key for people autocomplete (load balancing) |
| `warmup` | Pre-warm people autocomplete service |

#### Sheets BigQuery

| Method | Description |
|--------|-------------|
| `createDataSourcePivotTableOnNewSheet` | Create a pivot table backed by a data source on a new sheet |
| `enableAllDataSourcesExecution` | Enable execution for all data source connections |
| `getBigQueryProjects` | List BigQuery projects accessible from Sheets |
| `insertDataSourceSheet` | Insert a new sheet backed by a data source |
| `newDataSourceSpec` | Create a new data source specification (BigQuery, Looker) |
| `refreshAllDataSources` | Refresh all connected data sources |

#### Sheets Extended

| Method | Description |
|--------|-------------|
| `external_data_batch` | Batch fetch external data for multiple cell ranges |
| `get_prefs` | Get/set session preferences for spreadsheet editing |
| `get_revision_history` | Get version history/revisions for a spreadsheet |
| `save` | Save spreadsheet changes with commands bundle |

#### Sheets Gemini

| Method | Description |
|--------|-------------|
| `columnsmith_execute` | AI-driven column transformation via Gemini on cell ranges |
| `external_data_fetch` | Fetch and inject external data into sheet cells |

#### Sheets REST

| Method | Description |
|--------|-------------|
| `save` | Save document changes (internal Sheets RPC) |
| `scripts_getitems` | Get Apps Script items bound to the spreadsheet |
| `scripts_uiready` | Signal that the Apps Script UI is loaded and ready |

#### Workspace Analytics

| Method | Description |
|--------|-------------|
| `create` | Create a new analytics session/event |
| `ping` | Lightweight activity heartbeat ping |

#### Workspace Gemini

| Method | Description |
|--------|-------------|
| `get_settings` | Get current Gemini settings for the user |
| `list_gems` | List available Gemini models and capabilities |
| `quota_summary` | Get Gemini API usage quota summary |
| `stream_generate` | Stream-based Gemini text generation for Workspace apps |
| `update_settings` | Update user Gemini preferences |

#### Workspace Support

| Method | Description |
|--------|-------------|
| `addons_list` | List installed Workspace add-ons and extensions |
| `async_data` | Fetch async data for Workspace integrations |
| `doc_sync` | Real-time document collaboration sync |
| `fetch_recommendation` | Fetch AI-powered feature recommendations |
| `fetch_recommendations_batch` | Batch fetch multiple AI recommendations |
| `peoplestack_autocomplete` | People autocomplete for sharing and collaboration |
| `prewarm` | Pre-warm Gemini AI models before generation |
| `scripts_ui` | Apps Script UI integration for document automation |
| `waa_ping` | Workspace analytics and activity tracking ping |
| `workspace_batch` | Batch multiple Workspace UI operations |

---

## Token Harvesting

### Authentication Model

CosySim's external API layer is built on a single insight: every Google service
accepts the same browser session cookies. One HAR capture from a logged-in
account yields all the credentials needed to talk to Drive, Sheets, Colab,
NotebookLM, AI Studio, and Apps Script programmatically -- no OAuth dance, no
service account, no API key quota.

### SAPISIDHASH (all Google services)

Every Google property uses the same SAPISID cookie pattern:

```python
import hashlib, time

ts = str(int(time.time()))
origin = "https://aistudio.google.com"  # or drive.google.com, docs.google.com, etc.
digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
auth = f"SAPISIDHASH {ts}_{digest}"
# Plus SAPISID1PHASH and SAPISID3PHASH if those cookies are present
```

### Account Pool

Account credentials live in `data/accounts/pool.json`. Import an account with:

```python
from engine.integrations.google_account_pool import get_account_pool
pool = get_account_pool()
pool.import_from_har("path/to/capture.har", name="nihilistcod", services=["colab", "drive", "notebooklm"])
```

### Account Tiers

| Account | Tier | Notes |
|---------|------|-------|
| nihilistcod | Free | Can set `[2]` tier marker (client-side gating) |
| knack112358 | Pro | Full Pro tier access |

### SDK Architecture

Three layers connect agents to external services:

1. **SDK clients** -- standalone, auth-encapsulated HTTP clients for each service
2. **Artifact Bus** -- a unified routing layer that moves artifacts between services
3. **Skills** -- `@skill`-decorated wrappers that expose every bus operation to LLM agents

```
LLM Agents / CosySim Skills
             |
    Artifact Bus (engine/integrations/artifact_bus.py)
      |     |     |     |
  Drive  Sheets  Colab  NLM SDK
             |
    GoogleAccountPool (data/accounts/pool.json)
```

### Google Drive Client

**File:** `engine/integrations/google_drive_client.py`

**Auth:** SAPISIDHASH with `origin = "https://drive.google.com"`.
All requests target `clients6.google.com`.

| Method | Purpose | Endpoint |
|--------|---------|----------|
| `list_files(folder_id, query)` | List files, optionally filtered | `GET /drive/v3/files` |
| `get_file_metadata(file_id)` | Get metadata for one file | `GET /drive/v2beta/files/{id}` |
| `download_file(file_id)` | Download raw bytes | `GET /drive/v3/files/{id}?alt=media` |
| `download_text(file_id)` | Download and decode UTF-8 | same |
| `upload_file(name, content, mime_type, folder_id)` | Create or update a file | `POST /upload/drive/v3/files?uploadType=multipart` |
| `create_folder(name, parent_id)` | Create a folder | `POST /drive/v3/files` |
| `find_or_create_folder(name, parent_id)` | Idempotent folder upsert | list + create |
| `delete_file(file_id)` | Delete file or folder | `DELETE /drive/v3/files/{id}` |
| `upload_text_to_cosysim_folder(name, content, subfolder)` | Upload to `CosySim/{subfolder}/` | multipart create |
| `make_file_accessible_to_notebooklm(file_id)` | Grant anyone-reader | `POST /drive/v3/files/{id}/permissions` |
| `get_shareable_link(file_id)` | Build shareable URL | (string build) |

```python
from engine.integrations.google_drive_client import get_drive_client

drive = get_drive_client()                    # round-robin from pool
drive = get_drive_client("nihilistcod")       # specific account
```

### Google Sheets Client

**File:** `engine/integrations/gsheets_client.py`

**Auth:** SAPISIDHASH with `origin = "https://docs.google.com"`.
Sheets v4 at `sheets.googleapis.com` + Drive v3 at `clients6.google.com`.

| Method | Purpose |
|--------|---------|
| `create_sheet(title, folder_id)` | Create new spreadsheet |
| `get_metadata(sheet_id)` | Get tabs list and properties |
| `read_rows(sheet_id, range_, include_headers)` | Read as list of dicts |
| `read_raw(sheet_id, range_)` | Read as list of lists |
| `append_rows(sheet_id, rows, sheet_name)` | Append rows, auto-header |
| `write_rows(sheet_id, rows, sheet_name, start_row)` | Overwrite from row N |
| `clear_sheet(sheet_id, sheet_name)` | Clear all values |
| `create_from_data(title, rows, folder_id)` | Create + populate in one call |
| `export_as_csv(sheet_id, sheet_name)` | Export to CSV string |
| `list_sheets(sheet_id)` | List tab names |
| `add_sheet_tab(sheet_id, tab_name)` | Add new tab |
| `make_public(sheet_id)` | Grant anyone-reader |
| `get_shareable_url(sheet_id)` | Build `?usp=sharing` URL |

### NLM Direct Client

**File:** `engine/integrations/nlm_direct_client.py`

See [Nexus](NEXUS.md) for full rpcid catalog.

**Two-endpoint architecture:**

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GenerateFreeFormStreamed` | Multi-turn notebook Q&A (ask / streaming ask) | cookies + f.req |
| `batchexecute` | All studio ops: create, generate, export, manage | cookies + rpcids |

Both require a `bl` (build label) and `f.sid` (session fingerprint) extracted
from the NLM homepage HTML.

Audio types: `AUDIO_DEEP_DIVE=1` (30 min), `AUDIO_BRIEF=2` (5 min),
`AUDIO_CRITIQUE=3`, `AUDIO_DEBATE=4`.

### Colab Runtime Client

**File:** `engine/integrations/colab_client.py`

**Auth:** SAPISIDHASH with `origin = "https://colab.research.google.com"`.
All RPC calls go to `colab.clients6.google.com/$rpc/google.internal.colab.v1.*`.

**AI Agent API (Gemini 3.1 Pro) -- three-call cycle:**

| Method | RPC Endpoint | Purpose |
|--------|-------------|---------|
| `create_task()` | `AIService/AgentCreateTask` | Allocate a task UUID |
| `update_task(task_id, context)` | `AIService/AgentUpdateTask` | Load context (notebook content, code) |
| `query_task(task_id)` | `AIService/AgentQueryTask` | Poll for the response |

**Kernel Execution:** WebSocket-based cell execution using the Jupyter messaging
protocol over `wss://{runtime_url}/api/kernels/{kernel_id}/channels`.

### Colab Notebook Builder

**File:** `engine/integrations/colab_notebook_builder.py`

**`build_and_run()` pipeline:**

1. Get/assign Colab runtime
2. Create Jupyter kernel session
3. Optional: prepend a cell that loads a Drive file as input data
4. Ask AI agent to create cells for `task_description`
5. Execute cells with self-repair (up to 3 retries per failing cell)
6. For each `chain_prompt`: ask AI for follow-up cells with prior outputs injected
7. Save notebook JSON to Drive
8. Store output summary in Nexus

Specialised pipelines: `training_notebook()`, `research_to_notebook()`,
`data_analysis_notebook()`.

### Colab GPU Manager

**File:** `engine/integrations/colab_gpu_manager.py`

| Tier | CU/hour | VRAM (GB) | RAM (GB) | Best For |
|------|---------|-----------|---------|----------|
| FREE | 0.0 | 0 | 12.7 | CPU-only tasks |
| T4 | 0.5 | 16 | 12.7 | Inference, embeddings, <3B LoRA |
| L4 | 1.2 | 22.5 | 53.0 | 3-13B LoRA, vLLM server, video gen |
| A100 | 6.0 | 40 | 83.5 | 7-34B LoRA, image fine-tune |
| H100 | 7.0 | 80 | 83.5 | 34B+ LoRA, full fine-tune |

Budget state persists to `data/accounts/cu_budget.json`.

### Colab Venv Manager

**File:** `engine/integrations/colab_venv_manager.py`

Drive-backed venv pattern: packages installed once (~3 GB), stored on Drive,
activated by prepending site-packages to `sys.path` at notebook start.

```python
DRIVE_MOUNT_PATH   = "/content/drive"
COSYSIM_DRIVE_ROOT = "/content/drive/MyDrive/CosySim"
VENV_PATH          = "/content/drive/MyDrive/CosySim/.venv"
OUTPUTS_PATH       = "/content/drive/MyDrive/CosySim/outputs"
MODELS_PATH        = "/content/drive/MyDrive/CosySim/models"
DATASETS_PATH      = "/content/drive/MyDrive/CosySim/datasets"
```

### Artifact Bus

**File:** `engine/integrations/artifact_bus.py`

The bus abstracts all transport logic between services.

**Service Enum:** `LOCAL`, `DRIVE`, `COLAB`, `NLM`, `SHEETS`, `NEXUS`

**Route Matrix:**

| From -> To | Transport |
|-----------|-----------|
| LOCAL -> DRIVE | multipart upload |
| LOCAL -> NLM | via Drive (make_public + add_source_url) |
| LOCAL -> NEXUS | read text + add_entry |
| DRIVE -> NLM | make_public + add_source_url |
| DRIVE -> COLAB | kernel cell that mounts Drive + copies file |
| DRIVE -> NEXUS | download_text + add_entry |
| DRIVE -> SHEETS | download JSON/CSV + create_sheet + append_rows |
| COLAB -> DRIVE | kernel reads file via base64 + upload |
| COLAB -> NLM | via Drive intermediary |
| COLAB -> SHEETS | Colab -> Drive then Drive -> Sheets |
| COLAB -> NEXUS | kernel reads text + add_entry |
| NLM -> COLAB | inject content as Python variable in kernel |
| NLM -> DRIVE | local audio download + upload |
| NLM -> NEXUS | generate_flashcards + add_qa (or add_entry) |
| SHEETS -> NLM | add spreadsheet URL as source |
| SHEETS -> NEXUS | read_rows + JSON + add_entry |

**Methods:** `handoff()` (single hop), `pipeline()` (multi-hop),
`full_knowledge_loop()` (compound workflow).

### Apps Script as Serverless Compute

Google Apps Script (GAS) is a serverless JavaScript runtime built into every
Google account. Key properties:

- **Free** -- unlimited execution time for personal use, 6-minute max per
  execution (30 min for Workspace accounts)
- **Native Workspace access** -- `SpreadsheetApp`, `DriveApp`, `GmailApp`,
  `CalendarApp` work without OAuth, without credentials
- **Web App deployment** -- any script deployed as public HTTPS endpoint
- **Time triggers** -- `ScriptApp.newTrigger().timeBased().everyHours(4)` is cron, for free
- **UrlFetchApp** -- outbound HTTP with custom headers including `Cookie` and
  `Authorization`

Every Google account is another GAS environment. An account pool of 10
accounts is 10 independent scheduled runtimes.

**GAS Template Library (planned `templates/gas/`):**

| Template | Purpose |
|----------|---------|
| `webhook_receiver.js` | Receives POST from CosySim scheduler, dispatches actions, POSTs results back |
| `nlm_caller.js` | Calls NLM batchexecute with session cookies from Script Properties |
| `drive_processor.js` | Processes Drive folder files on schedule, calls NLM, tracks in Sheet |
| `nexus_ingestor.js` | Reads Q&A pairs from Sheet, POSTs to CosySim Nexus API |

### Client-Side Research Targets

| Target | Value |
|--------|-------|
| NLM Quota Counter (`remainingQueries` in heap) | Rotate accounts before 429s |
| Model Override in batchexecute payload | Force Gemini 2.5 Pro for specific operations |
| AI Studio Model ID Override | Switch frontier models without UI |
| Feature Flag IDs 400-1200 | Gate premium generation capabilities on free accounts |

---

## Configuration

ARGUS is configured via `scripts/argus/config.py` which contains:

- Baseline rpcid lists for all targets (NLM, Gemini, AI Studio)
- CDP connection settings (`localhost:9222`)
- Output paths for registry, screenshots, and proto stubs
- Crawl flow definitions per target
- Feature flag probe ranges

Scheduler tasks are defined in the CosySim scheduler config:
- `argus-weekly-scan` -- full crawl
- `argus-diff-report` -- registry diff vs baseline

---

## Generic API Discovery Engine (v1.50)

ARGUS now includes a **general-purpose API discovery engine** that analyzes any HAR file
or V8 heap snapshot — not limited to Google services.

### CLI

```bash
# HAR analysis
python -m scripts.argus.analyze har path/to/file.har            # Console report
python -m scripts.argus.analyze har path/to/file.har --json      # Machine-readable JSON
python -m scripts.argus.analyze har path/to/file.har --report    # Markdown intelligence report

# Heap snapshot analysis
python -m scripts.argus.analyze heap path/to/snapshot.heapsnapshot

# Batch + comparison
python -m scripts.argus.analyze dir path/to/har_folder/          # Analyze all HARs
python -m scripts.argus.analyze compare file1.har file2.har      # Diff two captures
python -m scripts.argus.analyze heap-diff before.heap after.heap # Diff two heaps
```

### Protocol Auto-Detection

The analyzer classifies every request by content, not domain:

| Protocol | Detection Method |
|----------|-----------------|
| batchexecute | `/_/*/data/batchexecute` URL or `f.req=` in body |
| gRPC-web | `$rpc/` in URL or `application/grpc-web` Content-Type |
| GraphQL | `query`/`mutation` in JSON body or `/graphql` URL |
| REST JSON | `application/json` Content-Type |
| WebSocket | `wss://` URL scheme |
| Protobuf | `application/x-protobuf` Content-Type |

### What It Discovers

- **All unique endpoints** grouped by domain/service
- **Auth schemes**: Bearer, API key, Cookie, SAPISIDHASH, custom headers
- **Tokens** (redacted): API keys, JWTs, session tokens
- **GraphQL operations**: query/mutation names, variable shapes
- **Rate limits**: 429 responses, Retry-After headers
- **Service groups**: auto-detected from domain names
- **Feature flags**: Statsig, LaunchDarkly, custom flag endpoints
- **WebSocket endpoints** and protocols

### Architecture

```
scripts/argus/analyzers/
├── __init__.py              # Package exports
├── data_types.py            # Report dataclasses (HARAnalysisReport, etc.)
├── protocol_detector.py     # Auto-detect protocol from URL/headers/body
├── har_analyzer.py          # Core HAR analysis engine
└── heap_analyzer.py         # V8 heap snapshot analyzer

scripts/argus/
├── analyze.py               # CLI entry point
└── clients/                 # Target-specific API exploration clients
    └── sesame_client.py     # Sesame AI interactive explorer
```

### Target Clients

ARGUS can auto-generate exploration clients from HAR intelligence. Example:

```bash
# Sesame AI Explorer (built from HAR analysis)
python -m scripts.argus.clients.sesame_client flags      # 27 feature gates
python -m scripts.argus.clients.sesame_client domains     # Email domain gate testing
python -m scripts.argus.clients.sesame_client configs     # 14 dynamic configs
python -m scripts.argus.clients.sesame_client user        # Profile + roles
python -m scripts.argus.clients.sesame_client agents      # 5 agent-service instances
python -m scripts.argus.clients.sesame_client protocol    # WebSocket agent protocol spec
python -m scripts.argus.clients.sesame_client interactive  # Interactive REPL
python -m scripts.argus.clients.sesame_client full        # Everything
```

### Sesame AI Findings (2026-03-25)

| Finding | Detail |
|---------|--------|
| Employee domains | `@sesame.com`, `@sesameai.com` unlock 12 extra feature gates (19/27) |
| Meta partnership | `@meta.com` gets 1 extra gate (8/27 vs normal 7/27) |
| Staff configs | `webrtc_log_level: "info"`, `show_toggle: true` |
| Agent services | 5 instances (agent-service-0 through 4), behind Google IAP |
| WebSocket protocol | 13 message types, WebRTC SDP/ICE, character selection (Maya, Miles) |
| Public bucket | `sesame-dev-public` on GCS — no auth required for reads |
| Firebase project | `sesame-ai-demo`, API key `AIzaSyDtC7Uwb5pGAsdmrH2T4Gqdk5Mga07jYPM` |
| User roles | `['USER', 'EMAIL_VERIFIED']`, `moderation_status: 'ALLOWED'` |
| Audio | 44100 Hz, raw WebRTC Opus, TURN servers at `34.134.236.52:3478` |

---

## Cross-References

- [Nexus](NEXUS.md) -- all discoveries stored in Nexus for agent access
- [Architecture](ARCHITECTURE.md) -- system layers, engine/integrations placement
- [Nexus](NEXUS.md) -- NotebookLM full rpcid documentation
- [Gemini API Reference](GEMINI_API_REFERENCE.md) -- auto-generated Gemini catalog
- [AI Studio API Reference](AISTUDIO_API_REFERENCE.md) -- auto-generated AI Studio catalog

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50.1 | 2026-03-25 | Generic API Discovery Engine: HAR/heap analyzers, protocol auto-detection, Sesame AI explorer CLI, interactive REPL, domain gate testing |
| v1.50 | 2026-03-22 | Merged EXTERNAL_APIS.md into unified ARGUS doc; added full API catalog, SDK clients, Artifact Bus, Colab/GPU/Venv managers, Apps Script, Workspace operations |
| v1.49 | 2026-03-19 | Added ARGUS catalog summary with crawl statistics |
| v1.45 | 2026-03-15 | LiveDebugger section added (14 MCP skills, CLI tool, async pattern) |
| v1.0 | 2026-03-01 | Initial ARGUS doc -- CDP crawlers, decoders, discovery pipeline |
