# CosySim Integrations SDK Reference

**Complete API reference for all external service integrations. Designed for agents loading context and developers building on top of CosySim.**

Version: v1.0 [2026-03-23]

---

## How to Use This Document

**For agents (Claude, LMStudio, etc.):** Load this file for context when working with external services. Every public function signature is listed with params, return types, and usage examples.

**For developers:** This is the definitive reference for calling any external service from CosySim code. All integrations follow the singleton pattern (`get_X() → X`) and return `Dict[str, Any]` with an `"error"` key on failure.

**Quick lookup:** Jump to the service you need:
- [Port Registry](#1-port-registry) — Service URL/port resolution
- [LMStudio](#2-lmstudio) — Local LLM inference
- [NotebookLM](#3-notebooklm) — Google NLM (grounded research)
- [GitHub Copilot](#4-github-copilot) — 38 frontier models
- [Google Account Pool](#5-google-account-pool) — Multi-account auth management
- [Google Colab](#6-google-colab) — AI agent, code execution, compute
- [Google Sheets](#7-google-sheets) — Spreadsheet read/write
- [RPC Proxy](#8-rpc-proxy) — Low-level Google API proxy
- [CDP Auth Recovery](#9-cdp-auth-recovery) — Automated auth refresh
- [ARGUS](#10-argus) — API discovery platform
- [CLI Tools](#11-cli-tools) — ask.py, model_proxy.py, nlm_ask.py

---

## 1. Port Registry

**Module:** `engine/port_registry.py`
**Purpose:** Canonical source for all service URLs and ports. Read from `config/default.yaml`.

```python
from engine.port_registry import get_service_url, get_port

# Get a service URL (most common usage)
url = get_service_url("nexus")              # "http://localhost:8700"
url = get_service_url("lmstudio", "/api/v1/models")  # "http://localhost:1234/api/v1/models"
url = get_service_url("comfyui")            # "http://localhost:8188"
url = get_service_url("tts")                # "http://localhost:8600"

# Get just the port
port = get_port("phone")   # 5555
port = get_port("nexus")   # 8700

# Full registry access
from engine.port_registry import get_port_registry
registry = get_port_registry()
registry.all_ports()         # {"phone": 5555, "nexus": 8700, ...}
registry.find_conflicts()    # [(svc1, svc2, port), ...]
registry.for_group("scenes") # {"phone": 5555, "penthouse": 5556, ...}
```

**Available services:** phone, penthouse, tavern, lounge, casino, gallery, arena, neoncity, grid, oracle, hub, admin, asset_studio, creation_kit, nexus, lmstudio, comfyui, tts, bridge, nlm_proxy, cosyvoice_tts, stt

---

## 2. LMStudio

### 2a. LMS Client — REST API

**Module:** `engine/lmstudio/lms_client.py`
**Port:** 1234 (configurable via `lmstudio.port`)
**Protocol:** HTTP REST v1

```python
from engine.lmstudio.lms_client import get_lms_client

client = get_lms_client()  # Singleton

# ──── Health ──────────────────────────────────────────────────────
client.is_available()  # True/False

# ──── Models ──────────────────────────────────────────────────────
models = client.get_models(loaded_only=True)   # List[LMSModel]
info = client.get_model_info()                 # LMSModelInfo (current model)
key = client.resolve_model("qwen")             # Canonical model key

# ──── Inference ───────────────────────────────────────────────────
# Stateless chat
response = client.chat([
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"}
])
print(response.content)  # "Hi there!"

# Stateful chat (server manages context)
r1 = client.chat_stateful("Hello!")
r2 = client.chat_stateful("Follow up", previous_response_id=r1.response_id)

# Streaming
for chunk in client.chat_stream(messages, on_event=lambda e: print(e.type)):
    print(chunk, end="")

# Simple completion
text = client.complete("Once upon a time", max_tokens=100)

# Classification
label = client.classify("I love this!", ["positive", "negative", "neutral"])

# ──── Model Management ────────────────────────────────────────────
client.load_model("qwen2.5-7b-instruct", echo_load_config=True)
client.unload_model("qwen2.5-7b-instruct")
job = client.download_model("TheBloke/Mistral-7B-v0.1-GGUF")

# ──── Speculative Decoding ────────────────────────────────────────
client.enable_speculative(main_model="qwen-14b", draft_model="qwen-0.5b")

# ──── Auth Circuit Breaker ────────────────────────────────────────
client.reset_auth_circuit()  # Reset after fixing auth issues
```

### 2b. Server Controller — Lifecycle Management

**Module:** `engine/lmstudio/server_controller.py`

```python
from engine.lmstudio.server_controller import get_server_controller

ctrl = get_server_controller()

# ──── Server Status ───────────────────────────────────────────────
health = ctrl.get_server_status()  # ServerHealth
health.reachable      # True/False
health.loaded_models  # 2
health.vram_usage_pct # 78.5

# ──── Model Instances ─────────────────────────────────────────────
instance = ctrl.create_agent_instance("lola", "qwen2.5-7b", context_length=8192)
instance = ctrl.get_agent_instance("lola")
all_instances = ctrl.list_instances()

# ──── Inference Config ────────────────────────────────────────────
ctrl.configure_inference("qwen2.5-7b", temperature=0.8, max_tokens=4096)

# ──── Metrics ─────────────────────────────────────────────────────
metrics = ctrl.get_metrics()  # {instances, total_requests, total_tokens, ...}
```

### 2c. Inference Router — Priority Queue

**Module:** `engine/lmstudio/router.py`

```python
from engine.lmstudio.router import InferenceRouter, InferenceRequest, Priority, Tier

router = InferenceRouter()
router.start()

# Submit a request
future = router.submit(InferenceRequest(
    priority=Priority.INTERACTIVE,
    tier=Tier.GPU_PRIMARY,
    agent_id="lola",
    messages=[{"role": "user", "content": "Hello"}],
    stream=False
))
result = future.result(timeout=30)

# Bind agents to tiers
router.bind_agent("lola", Tier.GPU_PRIMARY)
router.bind_agent("system_router", Tier.CPU_ROUTER)

# Monitoring
metrics = router.get_metrics()  # RouterMetrics
```

**Priority levels:** REALTIME(0) → INTERACTIVE(1) → BACKGROUND(2) → BATCH(3)
**Tiers:** GPU_PRIMARY (T1, big models) → CPU_UTILITY (T2, small models) → CPU_ROUTER (T3, tiny router)

---

## 3. NotebookLM

### 3a. NLM Engine — High-Level API (Recommended)

**Module:** `engine/nexus/nlm_engine.py`
**Depends on:** NLM Live Proxy running on port 8800

```python
from engine.nexus.nlm_engine import get_nlm_engine

engine = get_nlm_engine()

# ──── Health ──────────────────────────────────────────────────────
engine.is_available()  # True/False
engine.status()        # {available, proxy, has_cookies, stats}
engine.stats()         # {asks, batch_asks, cache_hits, creates, ...}

# ──── Notebooks ───────────────────────────────────────────────────
notebooks = engine.list_notebooks()
nb = engine.create_notebook("My Research", sources=["https://example.com"])
nb = engine.get_notebook("notebook-uuid")
engine.delete_notebook("notebook-uuid")

# ──── Sources ─────────────────────────────────────────────────────
engine.add_source("nb-id", source_type="url", source_value="https://example.com")
engine.add_source("nb-id", source_type="text", source_value="Raw text content here")
engine.add_source("nb-id", source_type="youtube", source_value="https://youtube.com/watch?v=xyz")
engine.add_sources_batch("nb-id", [
    {"type": "url", "value": "https://example.com"},
    {"type": "text", "value": "Some content", "title": "My Note"}
])
engine.remove_source("source-uuid")

# ──── Q&A ─────────────────────────────────────────────────────────
answer = engine.ask("nb-id", "What are the key findings?")
# answer = {"answer": "...", "sources": [...], "citations": [...]}

answers = engine.ask_batch("nb-id", [
    "What is the main argument?",
    "Who are the key stakeholders?",
    "What are the risks?"
], delay=1.0)

# Conversation mode (multi-turn)
r1 = engine.converse("nb-id", "Explain the methodology")
r2 = engine.converse("nb-id", "How does that compare to X?", session_id=r1["session_id"])

# ──── Generation ──────────────────────────────────────────────────
guide = engine.generate("nb-id", doc_type="study_guide")
brief = engine.generate("nb-id", doc_type="briefing_doc")
faq = engine.generate("nb-id", doc_type="faq")
audio = engine.generate_audio("nb-id", customization="Make it conversational")

# ──── From Files ──────────────────────────────────────────────────
engine.create_from_files(
    ["/path/to/doc1.md", "/path/to/doc2.py"],
    name="Code Review Notebook",
    max_chars_per_source=50000
)
```

### 3b. NLM Hybrid Router — Dual-Backend

**Module:** `engine/mcp/nlm_hybrid.py`
**Routes:** batchexecute (fast, source management) ↔ Node.js bridge (reliable, chat)

```python
from engine.mcp.nlm_hybrid import get_nlm_hybrid

hybrid = get_nlm_hybrid()

# Chat always routes to Node bridge (batchexecute chat is broken)
answer = hybrid.ask("nb-id", "What is X?")
answers = hybrid.ask_batch("nb-id", ["Q1?", "Q2?"])

# Source management tries batchexecute first, falls back to Node
hybrid.add_text_source("nb-id", "Title", "Content body")
hybrid.add_url_source("nb-id", "https://example.com")

# Audio/video/data always route to Node bridge
hybrid.generate_audio("nb-id", style="deep_dive")
hybrid.generate_video("nb-id", style="cinematic")
tables = hybrid.extract_tables("nb-id", query="revenue by quarter")

# Health (both backends)
hybrid.health()  # {node_bridge: {...}, batchexecute_proxy: {...}}
```

### 3c. NLM Node Bridge — Browser-Based Backend

**Module:** `engine/mcp/nlm_node_bridge.py`
**Requires:** Node.js + `C:\Files\MCP\notebooklm-mcp\dist\index.js`

```python
from engine.mcp.nlm_node_bridge import get_nlm_node_bridge

bridge = get_nlm_node_bridge()

# Lifecycle
bridge.start(headless=True)
bridge.ensure_started()
bridge.stop()
bridge.is_running           # True/False
bridge.chrome_profile_exists # True/False

# First-time auth setup (opens visible browser for Google login)
bridge.setup_auth(show_browser=True)

# Operations (all return Dict)
bridge.ask_question("nb-id", "What is X?")
bridge.ask_batch("nb-id", ["Q1", "Q2", "Q3"])
bridge.list_notebooks()
bridge.create_notebook("Title", sources=[{"url": "https://..."}])
bridge.add_source("nb-id", url="https://...")
bridge.add_source("nb-id", text="Raw content", title="My Source")
bridge.list_sources("nb-id")
bridge.generate_audio_overview("nb-id", style="critique")
bridge.extract_data_tables("nb-id", query="metrics")
bridge.extract_flashcards("nb-id", store_in_nexus=True)
bridge.extract_quiz("nb-id")
bridge.distill_to_nexus("nb-id", nexus_category="research")

# Quota
bridge.get_quota()  # {tier, notebooks_used, queries_today, daily_limit}
```

### 3d. RPC Constants & Registry

**Modules:** `engine/mcp/nlm_rpc_constants.py`, `engine/integrations/nlm_rpc_registry.py`

```python
# Constants (hardcoded fallbacks, always available)
from engine.mcp.nlm_rpc_constants import (
    RPC_LIST_NOTEBOOKS, RPC_CREATE_NOTE, RPC_RENAME_NOTEBOOK,
    RPC_ADD_SOURCE, RPC_LIST_SOURCES, RPC_DELETE_SOURCE,
    DOC_TYPE_BRIEF, DOC_TYPE_STUDY_GUIDE, DOC_TYPE_FAQ,
    AUDIO_DEEP_DIVE, AUDIO_BRIEF, AUDIO_CRITIQUE, AUDIO_DEBATE,
)

# Dynamic registry (from config/nlm_rpcids.yaml, auto-refreshes)
from engine.integrations.nlm_rpc_registry import get_rpc_registry

reg = get_rpc_registry()
rpcid = reg.get_rpcid("list_notebooks")     # Current rpcid
payload = reg.build_payload("add_source", notebook_id="x", url="y")
reg.list_operations()                        # All operations by category
reg.list_categories()                        # ["notebook", "source", "qa", ...]
```

---

## 4. GitHub Copilot

**Module:** `engine/integrations/github_copilot_client.py`
**Auth:** GitHub session cookies → Bearer token (auto-refreshed hourly)

```python
from engine.integrations.github_copilot_client import get_copilot_client

client = get_copilot_client("nihilistcod")  # Per-account singleton

# ──── Models ──────────────────────────────────────────────────────
models = client.list_models()  # 38 frontier models
# Includes: claude-opus-4.6, sonnet-4.6, haiku-4.5,
#           gpt-5.4, gpt-5.3-codex, gpt-4o,
#           gemini-3.1-pro, gemini-3-flash,
#           grok-code-fast-1

# ──── Simple Ask ──────────────────────────────────────────────────
answer = client.ask("What is quantum computing?", model="claude-opus-4.6")

# ──── Threaded Conversation ───────────────────────────────────────
thread_id = client.create_thread()
reply, msg_id = client.send_message(thread_id, "Hello", model="gpt-5.4")
reply2, msg_id2 = client.send_message(thread_id, "Follow up",
                                       model="gpt-5.4",
                                       parent_message_id=msg_id)
```

**Model aliases (for ask.py):** `opus`, `sonnet`, `haiku`, `gpt5`, `gpt`, `codex`, `gemini`, `flash`, `grok`

---

## 5. Google Account Pool

**Module:** `engine/integrations/google_account_pool.py`
**Storage:** `data/accounts/pool.json`

```python
from engine.integrations.google_account_pool import get_account_pool

pool = get_account_pool()

# ──── Import from HAR ─────────────────────────────────────────────
account = pool.import_from_har(
    "path/to/capture.har",
    account_name="myaccount",
    services=["notebooklm", "colab", "github_copilot"]
)

# ──── Account Management ──────────────────────────────────────────
pool.add_account(account)
pool.remove_account("myaccount")
acct = pool.get_by_name("nihilistcod")

# ──── Service-Aware Selection ─────────────────────────────────────
acct = pool.get_account("notebooklm")  # Round-robin, skips rate-limited
pool.mark_rate_limited("nihilistcod", "colab", duration_seconds=3600)
pool.mark_available("nihilistcod", "colab")

# ──── Listing ─────────────────────────────────────────────────────
pool.list_accounts()                              # All accounts summary
pool.get_stale_accounts(max_age_days=7.0)         # Old cookies
pool.get_available_accounts("notebooklm")          # Not rate-limited
pool.get_cookie_header(acct, domain="google.com")  # Cookie header string

# ──── Account Properties ──────────────────────────────────────────
acct.cookie_age_days()    # 3.5
acct.is_stale()           # False
acct.is_rate_limited("colab")  # True/False
```

---

## 6. Google Colab

**Module:** `engine/integrations/colab_client.py`
**Auth:** SAPISIDHASH (from account pool cookies)

```python
from engine.integrations.colab_client import get_colab_client

client = get_colab_client("nihilistcod")

# ──── AI Agent ────────────────────────────────────────────────────
answer = client.ask("Write a function to parse CSV files", timeout=120)
suggestions = client.get_suggestions("import pandas as pd\n")

# ──── Code Execution ──────────────────────────────────────────────
result = client.run_python("print('Hello from Colab!')")
# result = {"output": "Hello from Colab!", "error": None, "status": "ok"}

# ──── Runtime Management ──────────────────────────────────────────
runtime_url, token = client.get_or_assign_runtime()
assignments = client.list_assignments()
info = client.get_user_info()  # {free_tiers, pro_tiers, compute_units}

# ──── Code Intelligence ───────────────────────────────────────────
completions = client.complete_code("def fibonacci(n):", cursor_pos=20)
pasted = client.smart_paste("some code snippet")
```

---

## 7. Google Sheets

**Module:** `engine/integrations/gsheets_client.py`
**Auth:** SAPISIDHASH (from account pool cookies)

```python
from engine.integrations.gsheets_client import get_sheets_client

sheets = get_sheets_client("nihilistcod")

# ──── Create ──────────────────────────────────────────────────────
result = sheets.create_sheet("My Spreadsheet")
result = sheets.create_from_data("Revenue", [
    {"month": "Jan", "revenue": 1000},
    {"month": "Feb", "revenue": 1200},
])

# ──── Read ────────────────────────────────────────────────────────
rows = sheets.read_rows("sheet-id", range_="Sheet1", include_headers=True)
raw = sheets.read_raw("sheet-id", range_="A1:D10")
meta = sheets.get_metadata("sheet-id")

# ──── Write ───────────────────────────────────────────────────────
sheets.append_rows("sheet-id", [{"col1": "val1", "col2": "val2"}])
sheets.write_rows("sheet-id", rows, start_row=5)
sheets.clear_sheet("sheet-id", sheet_name="Sheet1")

# ──── Sharing ─────────────────────────────────────────────────────
url = sheets.get_shareable_url("sheet-id")
sheets.make_public("sheet-id")

# ──── Export ──────────────────────────────────────────────────────
csv = sheets.export_as_csv("sheet-id")

# ──── Gemini Integration ──────────────────────────────────────────
sheets.fill_with_gemini("sheet-id", "B2:B10", "Generate product descriptions")
result = sheets.build_with_gemini("Create a project tracker with tasks and deadlines")

# ──── Tab Management ──────────────────────────────────────────────
tabs = sheets.list_sheets("sheet-id")
sheets.add_sheet_tab("sheet-id", "Analytics")
```

---

## 8. RPC Proxy

**Module:** `engine/integrations/rpc_proxy.py`
**Purpose:** Low-level Google API proxy with automatic SAPISIDHASH auth

```python
from engine.integrations.rpc_proxy import proxy_request

# Direct Google API call (auto-selects account by domain)
result = proxy_request(
    url="https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute",
    method="POST",
    body='f.req=[[["wXbhsf","[null,1,null,[2]]",null,"generic"]]]',
    content_type="application/x-www-form-urlencoded"
)
# result = {"status": 200, "body": "...", "headers": {...}, "latency_ms": 234}

# Explicit account
result = proxy_request(
    url="https://colab.clients6.google.com/...",
    account_name="nihilistcod"
)
```

---

## 9. CDP Auth Recovery

**Module:** `engine/nexus/cdp_auth_recovery.py`
**Purpose:** Automated Google auth refresh via Chrome DevTools Protocol

```python
from engine.nexus.cdp_auth_recovery import run_check, run_recovery

# Read-only health check
status = run_check()
print(status.healthy)   # True/False
print(status.summary()) # "CDP=ok | NLM=in | AIStudio=in | keys=3ok/0dead | BL=ok"

# Full recovery (injects cookies, harvests tokens, validates keys)
status = run_recovery()
status.cdp_available            # Chrome running?
status.nlm_logged_in            # NLM authenticated?
status.aistudio_logged_in       # AI Studio authenticated?
status.working_api_keys         # ["AIza...", ...]
status.dead_api_keys            # ["AIza...", ...]
status.bl_refreshed             # Build label updated?
status.session_tokens_refreshed # f.sid + at refreshed?
status.pool_synced              # GoogleAccountPool updated?
```

**CLI:**
```bash
python -m engine.nexus.cdp_auth_recovery          # Full recovery
python -m engine.nexus.cdp_auth_recovery --check   # Health only
python -m engine.nexus.cdp_auth_recovery --keys    # API key rotation only
```

**Scheduler:** Runs automatically every 15 minutes via `scheduler_daemon`.

---

## 10. ARGUS

**Module:** `scripts/argus/`
**Purpose:** Automated Google API discovery and mapping

```bash
# Full crawl (all targets)
python scripts/argus/orchestrator.py

# Individual crawlers
python scripts/argus/orchestrator.py --target notebooklm
python scripts/argus/orchestrator.py --target gemini
python scripts/argus/orchestrator.py --target aistudio

# Chat traffic capture (after rpcid rotation)
python scripts/argus_chat_probe.py --notebook <uuid> --account <name>

# HAR analysis
python scripts/har_payload_analyzer.py path/to/capture.har
python scripts/analyze_gemini_deep.py path/to/gemini.har

# HAR auto-import daemon
python scripts/har_watchfolder.py watch --interval 30
python scripts/har_watchfolder.py health
python scripts/har_watchfolder.py status
```

**Registry output:** `data/argus/registry.json` — versioned endpoint catalog
**Coverage:** 49 NLM rpcids (67%), 36 Gemini rpcids (47%), 150+ AI Studio methods (growing)

---

## 11. CLI Tools

### ask.py — Unified AI CLI

```bash
# Query any frontier model
ask.py "What is X?" --model claude-opus-4.6      # GitHub Copilot
ask.py "What is X?" --model gpt-5.4              # GitHub Copilot
ask.py "What is X?" --nlm                         # NotebookLM
ask.py "What is X?" --local                       # LMStudio

# List models
ask.py --models                                   # All models
ask.py --models --vendor anthropic                # Filter by vendor
```

### model_proxy.py — OpenAI-Compatible API Server

```bash
python scripts/model_proxy.py  # Starts on port 5800

# Any OpenAI-compatible tool can connect:
curl http://localhost:5800/v1/models
curl http://localhost:5800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-opus-4.6", "messages": [{"role": "user", "content": "Hello"}]}'
```

### nlm_ask.py — Direct NLM Query via CDP

```bash
python scripts/nlm_ask.py "What are the key findings?"
# Attaches to running Chrome NLM tab, injects fetch(), returns answer
# Handles Gemini thinking traces, 90s timeout
```

---

## Authentication Quick Reference

| Service | Method | How to Set Up |
|---------|--------|---------------|
| **LMStudio** | Optional Bearer token | Config: `lmstudio.api_token` |
| **NotebookLM** | Google cookies + CSRF | `har_watchfolder.py import` or `cdp_auth_recovery` |
| **GitHub Copilot** | GitHub cookies → Bearer | Import GitHub HAR via account pool |
| **Google Colab** | SAPISIDHASH | Import Google HAR via account pool |
| **Google Sheets** | SAPISIDHASH | Import Google HAR via account pool |
| **AI Studio** | API key or SAPISIDHASH | Auto-harvested by `cdp_auth_recovery` |

**SAPISIDHASH computation:**
```python
import hashlib, time
ts = str(int(time.time()))
raw = f"{ts} {SAPISID_cookie} {origin_url}"
hash = hashlib.sha1(raw.encode()).hexdigest()
header = f"SAPISIDHASH {ts}_{hash}"
```

---

## Error Handling Convention

All integration methods return `Dict[str, Any]`. Check for errors:

```python
result = engine.ask("nb-id", "question")
if "error" in result:
    logger.error("[module] NLM ask failed (operation=ask): %s", result["error"])
else:
    answer = result["answer"]
```

---

## Configuration

All service config lives in `config/default.yaml`. Access via:

```python
from engine.config import get_config
cfg = get_config()

cfg.get("lmstudio.base_url", "http://localhost:1234")
cfg.get("nexus.base_url", "http://localhost:8700")
cfg.get("notebooklm.base_url", "http://localhost:8800")
cfg.get("comfyui.base_url", "http://localhost:8188")
cfg.get("tts.server_url", "http://localhost:8600")
```

Never hardcode ports or URLs. Use `get_service_url()` or `get_config()`.

---

*This document is auto-generated from codebase analysis. For the exploration narrative behind these systems, see [EXPLORATION_JOURNAL.md](EXPLORATION_JOURNAL.md).*
