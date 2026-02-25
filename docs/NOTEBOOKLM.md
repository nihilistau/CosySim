# NotebookLM Integration

Google [NotebookLM](https://notebooklm.google.com/) is an AI research
assistant that can ingest sources (URLs, PDFs, YouTube links, plain text) and
answer questions with citations.  CosySim uses NotebookLM as a knowledge
backend — the **recommended path** is through the Nexus service, which adds
unified search, storage, and automatic backend selection.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  CosySim Engine                                                 │
│                                                                 │
│  nexus_search ─┐                                                │
│  nexus_add ────┤  ──HTTP──▶  Nexus REST API (localhost:8700)    │
│  nexus_nlm_ask ┤                  │                             │
│  nexus_status ─┘                  ▼                             │
│                          ┌────────────────┐                     │
│                          │   NLMManager    │                     │
│                          │ (auto-select)   │                     │
│                          └──┬──────────┬───┘                    │
│                             │          │                        │
│               ┌─────────────┘          └──────────────┐        │
│               ▼                                       ▼        │
│    ┌─────────────────────┐             ┌──────────────────┐    │
│    │  HTTP backend        │             │  Browser backend  │    │
│    │  notebooklm-mcp      │             │  notebooklm-skill │    │
│    │  v1.5.3 · port 3000  │             │  (Patchright)     │    │
│    │  33 REST endpoints   │             │  No server needed │    │
│    └─────────────────────┘             └──────────────────┘    │
│                                                                 │
│  Legacy path (still available):                                 │
│  notebooklm_* skills ──▶ NotebookLMProxy ──▶ notebooklm-mcp    │
└─────────────────────────────────────────────────────────────────┘
```

**Data flow:** CosySim skills call the Nexus REST API at
`http://localhost:8700`.  Nexus's NLMManager picks the best NLM backend
(`prefer_backend: auto | http | browser`), tries it, and falls back to the
other if the primary is unavailable.

---

## Authentication Setup

NotebookLM requires a Google account.  Both backends authenticate via a
stored Chrome/Chromium profile:

1. **First run** — start the HTTP backend (`npx notebooklm-mcp`) or the
   browser backend manually.  A browser window opens for Google sign-in.
2. **Subsequent runs** — the stored profile is reused automatically; no
   interactive login is needed.
3. **Custom profile** — set `auth_profile_dir` in `config/default.yaml` to
   point to an existing Chrome profile directory.

---

## Nexus Skills (Recommended)

Defined in `engine/skills/builtin/nexus_skills.py` (pack: `nexus`).

| Skill | Description |
|---|---|
| `nexus_search` | Search the Nexus knowledge base.  Returns JSON results. |
| `nexus_add` | Add a knowledge entry (note, source, etc.) to Nexus. |
| `nexus_nlm_ask` | Query NotebookLM via the best available backend (HTTP → browser fallback).  Accepts `question`, optional `notebook_id` / `notebook_url`. |
| `nexus_status` | Report Nexus stats and NLM backend health. |

These skills talk to Nexus over HTTP.  They work whenever the Nexus service
is running — no direct dependency on the NLM servers from CosySim's side.

---

## Legacy Skills

Defined in `engine/skills/builtin/notebooklm_skills.py` (pack: `notebooklm`).
These use `NotebookLMProxy` (`engine/mcp/notebooklm_proxy.py`) to manage a
local `notebooklm-mcp` Node.js process directly, bypassing Nexus.

| Skill | Description |
|---|---|
| `notebooklm_ask` | Ask a question against a notebook; returns an answer with citations. |
| `notebooklm_add_source` | Ingest a URL, text, PDF, or YouTube link into a notebook. |
| `notebooklm_generate_audio` | Generate a podcast-style Audio Overview (async). |
| `notebooklm_list_notebooks` | List all notebooks visible to the authenticated user. |
| `notebooklm_search` | Search across all notebooks by keyword. |

> **Note:** The legacy skills still work and are useful for direct access
> without Nexus, but the Nexus path is preferred for new workflows.

---

## Dual Backend: HTTP vs Browser

| | HTTP Backend | Browser Backend |
|---|---|---|
| **Package** | `roomi-fields/notebooklm-mcp` v1.5.3 | `notebooklm-skill` (Patchright) |
| **Port** | 3000 | None (headless browser) |
| **Endpoints** | 33 REST endpoints | N/A — browser automation |
| **Speed** | Fast (direct API calls) | Slower (UI automation) |
| **Reliability** | Depends on upstream API stability | Works as long as the NLM UI is unchanged |
| **Use case** | Primary / production | Fallback when HTTP backend is down |

The `NLMManager` in Nexus selects the backend based on `prefer_backend`:

- **`auto`** (default) — try HTTP first, fall back to browser.
- **`http`** — HTTP only; fail if unavailable.
- **`browser`** — browser only; useful when the HTTP API is broken.

---

## Configuration Reference

### CosySim — `config/default.yaml`

```yaml
notebooklm:
  enabled: false                       # enable NotebookLM integration
  proxy_url: "http://localhost:8800"    # legacy proxy URL (used by old skills)
  node_cmd: "node"                     # Node.js command
  server_path: ""                      # path to notebooklm-mcp dist/index.js
  default_notebook_id: ""              # default notebook for queries
  auth_profile_dir: ""                 # Chrome profile directory for Google auth
  startup_timeout: 15                  # seconds to wait for server startup
```

### Nexus — `C:\Files\Nexus\config\nexus.yaml`

The Nexus-side config controls the NLM backend selection and endpoints.
Key fields (see Nexus docs for full reference):

```yaml
nlm:
  prefer_backend: auto                 # auto | http | browser
  http:
    url: "http://localhost:3000"        # notebooklm-mcp address
  browser:
    headless: true                      # run Patchright headless
```

### MCP Servers — `config/mcp.json`

Three MCP servers are registered for use with LMStudio or other MCP hosts:

```json
{
  "mcpServers": {
    "cosysim":    { "command": "python", "args": ["-m", "engine.mcp.cosysim_server"] },
    "notebooklm": { "command": "npx",   "args": ["notebooklm-mcp"] },
    "nexus":      { "command": "python", "args": ["-m", "nexus.mcp.server"],
                    "cwd": "C:\\Files\\Nexus" }
  }
}
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `nexus_nlm_ask` returns connection error | Ensure Nexus is running: `curl http://localhost:8700/health` |
| HTTP backend unreachable | Check `notebooklm-mcp` is running on port 3000: `curl http://localhost:3000/health` |
| Browser backend fails | Verify Patchright is installed (`pip install patchright && patchright install chromium`) |
| Google auth expired | Delete the stored Chrome profile and re-authenticate on next launch |
| Legacy skills not working | Set `notebooklm.enabled: true` in `config/default.yaml` and ensure the proxy is started |
| `nexus_status` shows both backends down | Start at least one backend; for HTTP run `npx notebooklm-mcp`, for browser ensure `notebooklm-skill` is configured in Nexus |
| Timeout on startup | Increase `startup_timeout` in `config/default.yaml` (default 15 s may be too short on slow machines) |
