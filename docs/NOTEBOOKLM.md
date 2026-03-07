# NotebookLM Integration

Google [NotebookLM](https://notebooklm.google.com/) is used as a free Gemini
intelligence layer for knowledge distillation, research, and Q&A.  CosySim
controls it through a **browser-attached auth + private RPC stack**:

- a live Chrome session on CDP port `9222`
- direct cookie/session harvesting (`scripts\har_capture.py`,
  `python -m scripts.argus.tools tokens`)
- HAR import when we need to rebuild or inspect exact browser traffic
- direct private RPC access via `engine.integrations.nlm_direct_client`
  and `engine.mcp.nlm_live_proxy`

This is deliberate. The system prefers the live browser/CDP/HAR method because it
captures real NotebookLM session state (`bl`, `f_sid`, `at`, notebook context)
and keeps the double-prompt/browser-control workflow available.

---

## Architecture

```
CosySim skill / agent
        │
        ├── browser-attached auth refresh
        │      ├── scripts/har_capture.py
        │      └── python -m scripts.argus.tools tokens
        │
        ├── engine/integrations/nlm_direct_client.py
        │
        └── engine/mcp/nlm_live_proxy.py   (Flask :8800 — batchexecute RPC bridge)
                       │
                       ▼  HTTPS
              notebooklm.google.com/_/LabsTailwindUi/data/batchexecute
               (using live browser cookies + NotebookLM session metadata)
```

Higher-level abstractions build on top:

- `engine/nexus/nlm_engine.py` — unified NLM client with stats tracking
- `engine/nexus/nlm_notebook_manager.py` — named notebook fleet management
- `engine/nexus/nlm_qa_distiller.py` — batch Q&A distillation to Nexus
- `engine/nexus/nlm_router.py` — 4-tier query router (cache → FTS → NLM → LLM)
- `engine/nexus/bootstrap_notebooks.py` — control notebook seeding and scheduled
  refresh, including browser-bundle seeding for `copilot-system-control`
- `engine/nexus/notebooklm_flywheel.py` — two-pass control-notebook artifact
  generator that stores Nexus artifacts, creates TaskScheduler tasks, and feeds the
  training flywheel

---

## Control Notebook Flywheel

The dedicated `copilot-system-control` notebook is now treated as a control-plane
orchestrator, not just a Q&A notebook:

1. `engine/nexus/bootstrap_notebooks.py` refreshes the notebook sources and keeps
   the browser-bundle seed current.
2. `engine/nexus/notebooklm_flywheel.py` asks grounded control questions, then runs
   a second strict-JSON report prompt to produce a structured artifact.
3. The resulting artifact is stored in Nexus as:
   - the full control artifact
   - a compact startup context packet
   - the raw NotebookLM report
4. Parsed tasks are pushed into `engine/nexus/task_scheduler.py`.
5. Q&A, task envelopes, and conversation turns are pushed into
   `engine/nexus/training_flywheel.py`.
6. `engine/nexus/copilot_bridge.py` loads the latest control-flywheel startup
   packet into onboarding as `control_context_packet`, so restart/session-start
   flows can reuse the curated immediate summary, startup focus, and watch
   surfaces instead of re-deriving them from scratch.

The scheduler now keeps this path alive in two ways:

- `notebook-bootstrap` — weekly notebook refresh + immediate control follow-up
- `control-notebook-flywheel` — recurring control-plane artifact refresh every 8 hours

This is the current implementation of the double-prompt control loop the project
uses to turn grounded NotebookLM context into reusable Nexus memory and small
downstream agent tasks.

---

## Authentication Setup

Preferred flow: keep Chrome logged into NotebookLM and refresh auth from the live
browser session first.

### 1) Browser-attached CDP refresh (preferred)

Open Chrome on the real user profile with NotebookLM already logged in, then run:

```powershell
python scripts\har_capture.py --mode cdp --account knack112358 --services notebooklm,colab
```

That path:
- attaches to the running Chrome tab on port `9222`
- refreshes Google cookies directly from the browser
- captures NotebookLM session metadata (`bl`, `f_sid`, `at`, notebook context)
- writes the merged result into `data\accounts\pool.json`
- keeps `data\nlm_meta.json` and service cookie exports aligned

### 2) ARGUS token harvesting

For quick live-browser harvesting from the ARGUS toolkit:

```powershell
python -m scripts.argus.tools tokens --account knack112358
```

This now prefers the same direct CDP path and falls back to Playwright only if
needed. It also writes NotebookLM session metadata back into the modern account
pool model instead of the old legacy-only cookie list format.

### 2b) Browser-attached notebook ingest (current reliable upload path)

When private-RPC source upload drifts, use the ARGUS browser path:

```powershell
python scripts\nlm_ingest.py --file docs\ARGUS.md --name "ARGUS Docs"
python scripts\nlm_ingest.py --file docs\ARGUS.md --name "ARGUS Docs" --notebook-url https://notebooklm.google.com/notebook/<id>
```

This path attaches to the live Chrome session, drives the current NotebookLM
create/add-source UI, pastes the source content, captures the resulting
`batchexecute` HAR, and can now reopen an existing notebook with `--notebook-url`
to append a new pasted-text source.

### 3) HAR import / recovery

HARs remain a first-class recovery and inspection surface when we need exact
browser traffic, build labels, or captured request bodies:

```bash
curl -X POST http://localhost:8800/cookies/import \
     -H "Content-Type: application/json" \
     -d '{"har_path": "C:\\path\\to\\capture.har"}'
```

Use HAR import when:
- rebuilding a stale pool from a known-good session
- comparing live browser state against stored pool state
- extracting NotebookLM request metadata from captured traffic

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
  flywheel:
    enabled: true
    min_interval_hours: 8
    max_tasks: 6
    distill_category: "notebooklm-flywheel"
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `/notebooks` returns `no_data` | First run `python scripts\har_capture.py --mode cdp ...`; if that still fails, import a fresh HAR and compare the stored `bl` / `f_sid` / `at` values |
| `python -m scripts.argus.tools tokens` hangs on Playwright | Prefer the direct CDP path; ensure Chrome is already exposing port `9222` and keep a live NotebookLM tab open |
| `python -m scripts.argus.tools ask ...` errors on duplicate submit buttons | Update to the current ARGUS toolkit; `cmd_ask()` now targets the query-box submit button (`button.submit-button[aria-label="Submit"]`) instead of the disabled source-discovery submit control |
| HTTP 502 from proxy | Check proxy logs; refresh browser auth so `data\nlm_meta.json` contains a valid `bl`, `f_sid`, and `at` |
| `bootstrap_notebooks --notebook control --distill` cannot upload sources through the proxy | The control notebook now uses browser-bundle seeding through `scripts\nlm_ingest.py`; keep Chrome logged into NotebookLM and the CDP port available |
| `cookie_count: 0` in `/health` | No cookies loaded — run the CDP refresh or import a HAR file |
| Proxy not starting | Check port 8800 is free; start with `python -m engine.mcp.nlm_live_proxy` |
