# NotebookLM MCP Integration

CosySim integrates with Google NotebookLM through the
[notebooklm-mcp](https://www.npmjs.com/package/@roomi-fields/notebooklm-mcp)
bridge.  This lets CosySim skills search notebooks, add sources (URLs, PDFs,
YouTube links), and generate podcast-style audio overviews — all without
leaving the engine.

---

## Authentication Setup

1. **Install the npm package** (one-time):

   ```bash
   npm install @roomi-fields/notebooklm-mcp
   ```

2. **Launch the MCP server** and complete browser-based Google login:

   ```bash
   npx @roomi-fields/notebooklm-mcp
   ```

   A browser window opens for Google sign-in.  After you authenticate, the
   server stores a Chrome profile so future launches skip the login step.

3. **Optional** — point `auth_profile_dir` in `config/default.yaml` to a
   specific Chrome profile directory if you want to reuse an existing session.

---

## Configuration

All settings live under the `notebooklm:` key in `config/default.yaml`:

```yaml
notebooklm:
  enabled: false                       # enable NotebookLM MCP bridge
  proxy_url: "http://localhost:8800"    # CosySim-side proxy URL
  node_cmd: "node"                     # Node.js command
  server_path: ""                      # path to notebooklm-mcp dist/index.js
  default_notebook_id: ""              # default notebook for queries
  auth_profile_dir: ""                 # Chrome profile directory for Google auth
  startup_timeout: 15                  # seconds to wait for server startup
```

Set `enabled: true` and, if you installed the package locally, set
`server_path` to `node_modules/@roomi-fields/notebooklm-mcp/dist/index.js`.

An MCP-compatible config file is also available at `config/mcp.json` for use
with LMStudio or other MCP hosts.

---

## Skills

Five skills are registered in `engine/skills/builtin/notebooklm_skills.py`:

| Skill | Description |
|---|---|
| `notebooklm_ask` | Ask a question against a notebook; returns an answer with citations. |
| `notebooklm_add_source` | Ingest a URL, raw text, PDF, or YouTube link into a notebook. |
| `notebooklm_generate_audio` | Generate a podcast-style Audio Overview of a notebook (async). |
| `notebooklm_list_notebooks` | List all notebooks visible to the authenticated user. |
| `notebooklm_search` | Search across all notebooks by keyword. |

All skills are in the `notebooklm` pack and are only active when the proxy is
running.

---

## Architecture

```
CosySim skill  ──▶  NotebookLMProxy (Python)  ──HTTP──▶  notebooklm-mcp (Node.js)
                     engine/mcp/                               │
                     notebooklm_proxy.py                  Google Auth
                                                         (Chrome profile)
```

- **`notebooklm_proxy.py`** manages the Node.js process lifecycle (start /
  stop / restart), performs health checks, and forwards HTTP requests.
- **Skills** call the proxy via `urllib.request` — no extra Python dependencies
  are needed.
- The proxy is a singleton obtained with `get_notebooklm_proxy()`.
