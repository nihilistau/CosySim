# NotebookLM Integration

Google [NotebookLM](https://notebooklm.google.com/) is used as a free Gemini
intelligence layer for knowledge distillation, research, and Q&A.  CosySim
controls it directly via the **NLM Live Proxy** — a local Flask server that
makes authenticated batchexecute calls to NotebookLM's private API using
HAR-extracted Google session cookies.  No Node.js or browser automation required.

---

## Architecture

```
CosySim skill / agent
        │
        ▼
engine/mcp/notebooklm_proxy.py   (HTTP client wrapper)
        │
        ▼  HTTP
engine/mcp/nlm_live_proxy.py     (Flask :8800 — batchexecute RPC bridge)
        │
        ▼  HTTPS
notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
       (using HAR-extracted session cookies)
```

Higher-level abstractions build on top:

- `engine/nexus/nlm_engine.py` — unified NLM client with stats tracking
- `engine/nexus/nlm_notebook_manager.py` — named notebook fleet management
- `engine/nexus/nlm_qa_distiller.py` — batch Q&A distillation to Nexus
- `engine/nexus/nlm_router.py` — 4-tier query router (cache → FTS → NLM → LLM)

---

## Authentication Setup

All auth is cookie-based — no passwords, no browser automation.

1. Open Chrome and log in to [notebooklm.google.com](https://notebooklm.google.com).
2. Open DevTools → Network tab.  Do a few interactions (open a notebook, ask a question).
3. Right-click any request → **Save all as HAR with content**.
4. Import the HAR:

```bash
# Via CLI
curl -X POST http://localhost:8800/cookies/import \
     -H "Content-Type: application/json" \
     -d '{"har_path": "C:\\path\\to\\capture.har"}'

# Or via Nexus Panel → NLM Lab → Import HAR
```

Cookies last weeks to months.  Re-import a fresh HAR when they expire.

---

## Skills

Defined in `engine/skills/builtin/notebooklm_skills.py` (pack: `notebooklm`):

| Skill | Description |
|---|---|
| `notebooklm_ask` | Ask a question against a notebook; returns answer with citations. |
| `notebooklm_add_source` | Add a URL, text, PDF, or YouTube link to a notebook. |
| `notebooklm_generate_audio` | Generate a podcast-style Audio Overview (async). |
| `notebooklm_list_notebooks` | List all notebooks visible to the authenticated user. |
| `notebooklm_search` | Search across all notebooks by keyword. |

Higher-level NLM skills (pack: `nlm`) are in `engine/skills/builtin/autonomy_skills.py`.

---

## Configuration — `config/default.yaml`

```yaml
notebooklm:
  enabled: true
  proxy_url: "http://localhost:8800"   # NLM Live Proxy
  base_url: "http://localhost:8800"    # alias
  default_notebook_id: ""             # default notebook for queries
  timeout: 120                        # per-request timeout (seconds)
  metadata_path: "data/nlm_notebooks.json"
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `/notebooks` returns `no_data` | Import a fresh HAR — cookies or `at` token may be stale |
| HTTP 502 from proxy | Check proxy logs; try `POST /cookies/refresh` to refresh `at` token |
| `cookie_count: 0` in `/health` | No cookies loaded — import a HAR file |
| Proxy not starting | Check port 8800 is free; start with `python -m engine.mcp.nlm_live_proxy` |
