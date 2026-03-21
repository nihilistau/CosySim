# CosySim Operations Guide

> Logging, monitoring, scheduling, admin panels, news pipeline, and local agent operations.

---

## 1. Logging & Monitoring

### Architecture

```
engine/logging/
├── __init__.py          Public API — re-exports everything below
├── cosy_logger.py       CosyLogger: ring-buffer handler + install_logger()
├── benchmark.py         @timed decorator, LLM KPI tracking, timeseries
└── monitor.py           SystemMonitor: CPU/RAM/GPU metrics, service health
```

| Subsystem | Module | Purpose |
|-----------|--------|---------|
| **CosyLogger** | `cosy_logger.py` | In-memory ring buffer (2,000 entries) for live log streaming |
| **Benchmark** | `benchmark.py` | `@timed` decorator and LLM KPI tracking |
| **SystemMonitor** | `monitor.py` | Hardware metrics and service health pings |

All three are exposed through a single import path:

```python
from engine.logging import (
    install_logger, get_logs, clear_logs,          # CosyLogger
    timed, get_benchmarks, reset_benchmarks,       # Benchmark
    record_llm_kpi, get_llm_kpis, get_kpi_timeseries,
    get_system_monitor,                            # SystemMonitor
)
```

### Configuration

In `config/default.yaml` under the `logging` key:

```yaml
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "./logs/cosysim.log"
  max_bytes: 10485760  # 10 MB
  backup_count: 5
```

| Key | Default | Description |
|-----|---------|-------------|
| `level` | `INFO` | Minimum log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `format` | see above | Python `logging.Formatter` pattern |
| `file` | `./logs/cosysim.log` | Log file path |
| `max_bytes` | `10485760` (10 MB) | Max size before rotation |
| `backup_count` | `5` | Number of rotated backups to keep |

The log directory is also set in `paths.logs_dir` (default: `./logs`).

### Per-Module Logging Convention

Every module uses one logger, never `print()`:

```python
import logging
logger = logging.getLogger(__name__)
```

| Level | When to Use | Examples |
|-------|-------------|---------|
| `DEBUG` | Detailed diagnostic info, high-volume | Token counts, cache hits, state transitions |
| `INFO` | Significant operational events | Scene started, model loaded, skill registered |
| `WARNING` | Unexpected but recoverable situations | Missing optional dependency, falling back to default |
| `ERROR` | Operation failed, needs attention | LMStudio unreachable, database write failed |
| `CRITICAL` | System-level failure (rarely used) | Cannot start engine, data corruption |

Errors and critical messages are automatically forwarded to the **ActivityBus** as `log_error` events, making them visible in the admin panel without extra code.

Always use `exc_info=True` to capture tracebacks:

```python
try:
    result = client.chat(messages)
except Exception as e:
    logger.error("LLM call failed: %s", e, exc_info=True)
```

For non-critical failures, log at `DEBUG` to keep noise low:

```python
except Exception:
    logger.debug("Suppressed exception", exc_info=True)
```

### CosyLogger Ring Buffer

Call `install_logger()` once at startup (idempotent):

```python
from engine.logging import install_logger
handler = install_logger(
    logger_name="",           # "" = root logger (captures everything)
    level=logging.DEBUG,
    propagate_root=True,
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

Query logs via:

```python
from engine.logging import get_logs, clear_logs

logs = get_logs()                             # Last 200 entries
errors = get_logs(level="ERROR", limit=50)    # Filter by level
new_logs = get_logs(since_id=last_seen_id)    # Long-polling
clear_logs()                                  # Clear buffer
```

Each entry is a dict with fields: `id` (monotonic), `ts` (HH:MM:SS.mmm), `level`, `logger`, `message`.

```
┌─────────────┐    emit()    ┌──────────────────┐
│ Any module   │────────────>│ _RingHandler      │
│ logger.info()│             │ deque(maxlen=2000)│
└─────────────┘             └────────┬─────────┘
                                     │ if ERROR+
                                     v
                              ┌──────────────┐
                              │ ActivityBus   │
                              │ "log_error"   │
                              └──────────────┘
```

### SystemMonitor

The `SystemMonitor` singleton collects hardware metrics (cached 5 seconds) and pings external services.

```python
from engine.logging import get_system_monitor
monitor = get_system_monitor()

snap = monitor.snapshot()        # CPU%, RAM, GPU VRAM, GPU temp
health = monitor.check_services() # Per-service up/down + latency
model = monitor.get_loaded_model() # Currently loaded LMStudio model
```

Monitored services:

| Service | Health Endpoint | Default URL |
|---------|-----------------|-------------|
| LMStudio | `/v1/models` | `http://localhost:1234` |
| ComfyUI | `/system_stats` | `http://localhost:8188` |
| TTS | `/status` | `http://localhost:8600` |
| MCP (CosySim) | `/health` | `http://localhost:8700` |

URLs are read from config (`lmstudio.base_url`, `comfyui.base_url`, etc.) with fallback to the defaults above.

### Log Files and Rotation

| Item | Value |
|------|-------|
| Default directory | `./logs/` (`paths.logs_dir` in config) |
| Default file | `./logs/cosysim.log` |
| Max file size | 10 MB (`logging.max_bytes`) |
| Backup count | 5 (`logging.backup_count`) |

When `cosysim.log` reaches 10 MB it rotates, keeping up to 5 backups (`cosysim.log.1` through `.5`). The `logs/` directory is created automatically.

### Benchmarking and KPIs

```python
from engine.logging import timed, get_benchmarks, record_llm_kpi

@timed("llm_generate")
def generate(prompt):
    return client.chat(messages)

record_llm_kpi("llm_generate", latency_ms=350, tokens_in=50, tokens_out=120)
stats = get_benchmarks()
```

See [KPI.md](./KPI.md) for full documentation of the `@timed` decorator, LLM KPI tracking, timeseries export, and the admin dashboard.

### Backward Compatibility

The shim at `content/simulation/services/cosylogger.py` re-exports the public API from `engine.logging.cosy_logger`. All new code should import directly from `engine.logging`.

---

## 2. Scheduler Daemon

> **Module:** `engine/nexus/scheduler_daemon.py` | **Tasks:** 61 recurring | **Tests:** `tests/test_scheduler_daemon.py`

The scheduler daemon manages recurring background tasks: Nexus maintenance, news ingestion, pipeline execution, training data collection, and system health monitoring. Tasks are plain Python callbacks registered with schedule strings. Execution state is persisted across restarts.

### Architecture

```
                    ┌──────────────────────────────┐
                    │     TaskSchedulerDaemon       │
                    │   get_scheduler_daemon()      │
                    └──────────┬───────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────┴────┐  ┌───────┴──────┐  ┌──────┴──────┐
    │  60s Tick    │  │  State File  │  │ Nexus Log   │
    │  run_due()   │  │  (JSON)      │  │ (history)   │
    └──────────────┘  └──────────────┘  └─────────────┘
```

### Task Registration

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()
daemon.register(
    task_id="my-task",
    name="My Task Description",
    schedule="every_4h",
    callback=my_callback,       # Zero-arg function -> Dict[str, Any]
    enabled=True,
)
```

### Schedule Strings

| String | Interval |
|--------|----------|
| `"every_5m"` | 5 minutes |
| `"every_15m"` | 15 minutes |
| `"every_1h"` | 1 hour |
| `"every_4h"` | 4 hours |
| `"every_6h"` | 6 hours |
| `"every_8h"` | 8 hours |
| `"every_12h"` | 12 hours |
| `"daily"` | 24 hours |
| `"weekly"` | 7 days |
| `"every_Nh"` / `"every_Nm"` | Arbitrary N hours/minutes |

### Callback Pattern

```python
def my_callback() -> Dict[str, Any]:
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        result = client.search("important things")
        return {"items_processed": len(result), "status": "ok"}
    except Exception as exc:
        logger.error("Task failed: %s", exc)
        return {"error": str(exc)}
```

### Task Catalog (61 Tasks)

**Nexus Maintenance (12 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `nexus-dedup` | daily | Deduplicate similar knowledge entries |
| `nexus-quality-scan` | daily | Score and flag low-quality entries |
| `nexus-stale-cleanup` | weekly | Archive stale entries |
| `nexus-stats` | every_4h | Collect database statistics |
| `nexus-backup` | daily | Backup Nexus database |
| `qa-quality-check` | daily | Validate Q&A pair quality |
| `qa-expander` | daily | Expand thin Q&A pairs with richer answers |
| `qa-generator` | daily | Generate Q&A from knowledge entries |
| `training-sync` | daily | Sync training data from Nexus |
| `auto-embedding` | every_4h | Batch-embed entries into ChromaDB |
| `doc-sync` | every_6h | Detect repo doc changes, sync to Nexus |
| `copilot-reseed` | daily | Reseed Copilot instruction mirrors |

**Workspace Pipeline (4 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `workspace-news-pipeline` | every_8h | RSS -> NLM -> Sheets -> Nexus |
| `workspace-news-to-knowledge` | daily | News -> NLM -> Docs -> Drive -> Nexus |
| `workspace-research-cycle` | every_12h | Research queued topics from Nexus |
| `workspace-pipeline-health` | every_6h | Client connectivity and stage health |

**News & Intelligence (4 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `news-fetch` | every_8h | RSS fetch, score, store, NLM distillation |
| `news-nlm-retry` | every_8h | Retry failed NLM distillation jobs |
| `news-source-health` | daily | Check RSS feed availability |
| `news-digest-publish` | daily | Publish daily digest to scenes |

**NotebookLM (6 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `notebook-rotation` | weekly | Rotate NLM notebooks by age/size |
| `notebook-health` | daily | Check notebook accessibility |
| `control-notebook-flywheel` | every_4h | Run control notebook follow-up tasks |
| `nlm-distil-queue` | every_8h | Process NLM distillation queue |
| `argus-nlm-distil` | weekly | Upload ARGUS discoveries, batch Q&A |
| `improvement-review` | weekly | NLM review of low-quality responses |

**System Health (8 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `metrics-collect` | every_4h | Collect system metrics |
| `test-monitor` | daily | Run test suite, track regressions |
| `scene-health` | every_6h | Check scene port availability |
| `lmstudio-health` | every_1h | Verify LMStudio server |
| `cookie-health-check` | daily | Check Google account pool freshness |
| `port-conflict-check` | every_4h | Detect port conflicts |
| `log-rotation` | daily | Rotate and compress log files |
| `error-digest` | every_4h | Summarize error patterns |

**Training & Data (6 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `flywheel-collect` | every_4h | Collect training data from sessions |
| `flywheel-quality` | daily | Score training example quality |
| `flywheel-export` | daily | Export training datasets |
| `benchmark-run` | daily | Run model benchmarks |
| `cdp-mine` | daily | Mine CDP logs for training data |
| `colab-pipeline-sync` | daily | NLM -> Drive -> Colab analysis sync |

**ARGUS & Browser (4 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `argus-weekly-scan` | weekly | Full API surface scan |
| `argus-diff-report` | weekly | Compare scans, store deltas |
| `har-watchfolder` | every_4h | Process new HAR captures |
| `cdp-health` | every_4h | Check CDP endpoint availability |

**Other (17 tasks)** — operator inbox, session logging, Copilot validation, inventory snapshots, etc.

### CLI Usage

```bash
python -m engine.nexus.scheduler_daemon status     # Show all task statuses
python -m engine.nexus.scheduler_daemon run <id>    # Run a task immediately
python -m engine.nexus.scheduler_daemon start       # Start daemon (checks every 60s)
```

### Python API

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()
result = daemon.run_task("workspace-news-pipeline")   # Run immediately
task = daemon._tasks.get("news-fetch")                # Inspect task state
task_ids = list(daemon._tasks.keys())                 # List all task IDs
daemon._tasks["my-task"].enabled = False              # Disable a task
```

### State Persistence

Task execution state is persisted to `data/scheduler_state.json`:

```json
{
  "news-fetch": {
    "last_run": 1710456000.0,
    "run_count": 42,
    "error_count": 1,
    "last_result": "{\"fetched\": 30, \"stored\": 25}"
  }
}
```

State survives restarts -- tasks resume from where they left off.

### Adding a New Task

1. Define the callback in `scheduler_daemon.py` (zero-arg, returns dict, lazy imports).
2. Register in `_register_builtin_tasks()`.
3. Add a test asserting the task_id appears in `_register_builtin_tasks`.
4. Update task count in `test_builtin_task_count`.

---

## 3. Admin Panel (Streamlit)

**Launch:** `python launcher.py --mode admin` (port 8502)

A Streamlit-based diagnostic and control center (`admin_panel.py`, ~120 lines) that delegates to 12 page modules in `content/scenes/admin/pages/`.

### Page Modules

```
admin_panel.py          -> Sidebar navigation, session state init
pages/
├── dashboard.py        -> System overview + health
├── logs.py             -> Log viewer + benchmarks
├── chains.py           -> EventChain browser
├── config_editor.py    -> Interactive config editing
├── rag_editor.py       -> RAG message editor
├── god_mode.py         -> Full override access
├── character_manager.py-> Character CRUD
├── scene_manager.py    -> Scene registry
├── media.py            -> Media gallery
├── lmstudio.py         -> LMStudio management
├── backup.py           -> Backup & restore
└── assets.py           -> Asset browser
```

Each page exports a `render()` function.

### Key Pages

**Dashboard** -- Service health indicators (LMStudio, ComfyUI, Database, EventChain), system metrics (CPU%, RAM, GPU VRAM), loaded model info, benchmark summary table.

**Logs** -- Three tabs: file logs from disk, ring buffer from CosyLogger, and benchmark timing table. Supports level filter, search, tail, export (JSON/CSV).

**EventChain Browser** -- Browse chains with filters (scene, character, event type, date). Tree view with causal hierarchy. Click to expand full JSON payload.

**Config Editor** -- Organized by YAML section. Type-aware inputs (booleans as toggles, numbers as sliders). Validation with red border on invalid values. Save & Apply writes to YAML and reloads ConfigManager singleton.

**GOD Mode** -- Password-protected (`cosysim`) full override access. Raw SQL, event injection, force state override, DB browser, danger zone (clear all events/tables). Red banner when active; all actions logged as `god_mode_action` events.

### Session State

Shared via `st.session_state`:

| Key | Type | Purpose |
|-----|------|---------|
| `asset_manager` | AssetManager | Asset CRUD |
| `config` | ConfigManager | Configuration access |
| `god_mode` | bool | GOD mode toggle |

### Adding a New Page

1. Create `pages/my_page.py` with a `render()` function.
2. Add to `_PAGES` dict in `admin_panel.py`.
3. Import at top of `admin_panel.py`.

---

## 4. System Control Panel (Flask)

> Port **5575** | `content/scenes/system_control/`

The operator's runtime dashboard for CosySim. Auto-starts with `--core`.

```bash
python launcher.py system_control
# or auto-starts with:
python launcher.py --core
```

Open: [http://localhost:5575](http://localhost:5575)

### Tabs

| Tab | Features |
|-----|----------|
| **Overview** | CPU, RAM, GPU utilisation (live 30s refresh), uptime, quick links |
| **Services** | Health status for all 19 services (parallel checks, 3s timeout) |
| **Config Editor** | Load/edit/validate/save YAML + JSON config files (`.bak` backups) |
| **Launcher** | Toggle `auto_start` per service/scene, persists to `config/launcher.yaml` |
| **NLM Proxy** | Status, BL age, cookie freshness, HAR import, CDP cookie capture, notebook list |
| **Nexus** | Entry/QA/rules counts, quick search, links to Nexus Panel (:5570) |
| **LMStudio** | Connection status, loaded models, quick model load |
| **Logs** | Log file dropdown, tail last N lines, auto-refresh every 10s |
| **Git** | Current branch, last 10 commits, working tree status |

Editable config files: `config/default.yaml`, `config/production.yaml`, `config/launcher.yaml`, `config/voices.yaml`, `config/skill_manifests.yaml`, `config/mcp.json`, `config/news_sources.yaml`.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Scene health check |
| GET | `/api/metrics` | CPU/RAM/GPU stats |
| GET | `/api/services` | Health of all 19 services |
| GET | `/api/configs` | List editable config files |
| GET | `/api/config/<name>` | Read a config file |
| POST | `/api/config/<name>` | Write a config file (validated) |
| GET | `/api/launcher` | Current auto-start settings |
| POST | `/api/launcher/<name>` | Toggle auto-start flag |
| GET | `/api/nlm/status` | NLM proxy status (proxies to :8800) |
| POST | `/api/nlm/import-har` | Import a HAR file into NLM proxy |
| POST | `/api/nlm/capture-cookies` | Trigger Chrome CDP cookie capture |
| GET | `/api/nlm/notebooks` | List NLM notebooks |
| GET | `/api/nexus/health` | Nexus health summary |
| GET | `/api/nexus/search` | Quick Nexus search (`?q=...`) |
| GET | `/api/lmstudio/status` | LMStudio connection + loaded models |
| GET | `/api/logs` | List available log files |
| GET | `/api/logs/<name>` | Tail a log file (`?lines=100`) |
| GET | `/api/git` | Git branch, commits, and status |

### Architecture Notes

- All NLM operations proxy to `:8800` (never called directly).
- Config writes are atomic: validated then written; `.bak` backups created before each write.
- Service health checks run in a 10-thread pool.
- Metrics use `psutil` (CPU/RAM) and `pynvml` (GPU); both degrade gracefully if not installed.

### Configuration

```yaml
# config/default.yaml
scenes:
  system_control:
    host: "localhost"
    port: 5575
    debug: false

# config/launcher.yaml
services:
  system_control:
    auto_start: true
```

---

## 5. News & Intelligence Pipeline

> Automated news ingestion, NLM distillation, and curated intelligence feeds.

### Pipeline Overview

```
RSS Sources -> Fetch -> Dedup -> NLM Distillation -> Nexus Storage -> Scene Delivery
```

1. **Ingestion** -- Fetch top stories from RSS/web sources 3x daily.
2. **Deduplication** -- URL fingerprint + title similarity (>85%) within a 48-hour window.
3. **NLM Distillation** -- Upload to NotebookLM notebooks, ask 10 curated questions per category.
4. **Nexus Storage** -- Answers stored as searchable Q&A and knowledge entries.
5. **Scene Delivery** -- Intel Hub ticker + Phone scene feed display curated news.
6. **Agent Access** -- Any agent can query `nexus_ask("latest AI news")`.

### Source Layout

```
engine/nexus/news/
├── news_pipeline.py      -- Orchestrator: fetch -> parse -> dedup -> distill -> store
├── rss_fetcher.py        -- RSS feed fetcher + HTML scraper
├── dedup_filter.py       -- Title/URL fingerprint deduplication
├── source_registry.py    -- Curated source list per category
└── news_models.py        -- NewsItem, NewsDigest, NewsCategory dataclasses
engine/skills/builtin/
└── news_skills.py        -- LLM skills: fetch_news, get_news_digest, search_news
```

### News Categories

| Category | Sources | NLM Notebook |
|----------|---------|-------------|
| `ai_research` | arxiv, HuggingFace blog, OpenAI blog, Anthropic, Google DeepMind | `news-ai-research` |
| `tech` | Hacker News, Ars Technica, The Verge, WIRED | `news-tech` |
| `world` | Reuters, AP News, BBC World | `news-world` |
| `science` | Nature News, New Scientist, Phys.org | `news-science` |
| `crypto` | CoinDesk, The Block, Decrypt | `news-crypto` |

New categories can be added by extending `source_registry.py`.

### Pipeline Stages

**Stage 1: Fetch** (`news-fetch` task, 07:00 / 13:00 / 20:00)

```python
from engine.nexus.news.rss_fetcher import RSSFetcher
fetcher = RSSFetcher()
items = fetcher.fetch_category("ai_research", limit=20)
# -> List[NewsItem]: title, url, summary, published_at, source_name
```

Respects per-source rate limits (1 req/5s). Falls back to HTML scrape if RSS unavailable. Stores raw items in Nexus with `content_type=raw_news`.

**Stage 2: Deduplication**

```python
from engine.nexus.news.dedup_filter import DedupFilter
dedup = DedupFilter()
fresh = dedup.filter(items)
# Removes: same URL, title similarity > 85%, within 48h window
```

URL fingerprint stored in Nexus `news_seen` index. Title similarity via character-level n-gram (no heavy NLP deps).

**Stage 3: NLM Distillation** (`news-distill` task, 21:00)

Each category has a dedicated NLM notebook. Per cycle: collect today's fresh items (up to 15), format and upload as text source, ask 10 curated questions, store each Q&A in Nexus with category + date tags. Session chaining ensures later questions benefit from earlier answers.

Example curated questions for `ai_research`:
- "What are the most significant AI research findings reported today?"
- "Which papers or announcements could change how we build AI systems?"
- "What are the key technical claims and are there limitations?"
- "What open-source models or tools were announced?"
- "Summarise today's AI news in 5 bullet points."

**Stage 4: Cleanup** (`news-cleanup` task, weekly Sunday 04:00)

- Removes `raw_news` entries older than 30 days.
- Archives Q&A older than 90 days to `news_archive` category.
- Rebuilds Nexus search index.

### Scheduler Tasks

| Task | Schedule | Duration est. |
|------|----------|---------------|
| `news-fetch` | 07:00, 13:00, 20:00 daily | ~2 min |
| `news-distill` | 21:30 daily | ~8 min (NLM calls) |
| `news-cleanup` | Sunday 04:00 | ~1 min |

### Scene Delivery

**Intel Hub** (`/intel`) -- Scrolling news ticker from Nexus. `GET /api/news/ticker` returns last 20 Q&A summaries. Socket.IO event `world_news.update` emitted after each distill cycle. Filterable by category.

**Phone Scene** (`/phone`) -- FEED tab with curated news. `GET /api/news/feed?category=all&limit=10`. Rendered as chat-style messages from "NEXUS FEED" sender. Clicking a headline shows full Q&A distillation.

### Agent Skills (`news` pack)

| Skill | Args | Description |
|-------|------|-------------|
| `fetch_news` | `category, limit` | Latest news headlines + summaries from Nexus |
| `get_news_digest` | `category, date` | Full distilled digest for a category on a date |
| `search_news` | `query, category, days_back` | Semantic search through news Q&A |

```python
result = search_news("open source LLM", category="ai_research", days_back=7)
```

### NotebookLM Integration

Each category uses a dedicated notebook. Notebooks accumulate sources (up to 50) then rotate. Notebook IDs are stored in Nexus under the `news_notebooks` key:

```json
{
  "ai_research": "nb-news-ai",
  "tech": "nb-news-tech",
  "world": "nb-news-world",
  "science": "nb-news-science",
  "crypto": "nb-news-crypto"
}
```

### Nexus Knowledge Structure

| Field | Value |
|-------|-------|
| `content_type` | `news` (distilled) or `raw_news` (pre-distill) |
| `category` | `news` |
| `tags` | `["{date}", "{category}", "news", "distilled"]` |
| `title` | Question asked |
| `content` | NLM answer |
| `source` | `news_pipeline:{category}` |

### Configuration

```yaml
news_system:
  enabled: true
  categories: [ai_research, tech, world, science]
  fetch_limit_per_source: 20
  dedup_window_hours: 48
  distill_questions_per_category: 10
  max_sources_per_notebook: 15
  nexus_retention_days: 30
  archive_after_days: 90
  ticker_item_count: 20
```

### Testing

```bash
python -m pytest tests/test_news_pipeline.py tests/test_news_skills.py -v
python scripts/smart_test.py --domain news
```

---

## 6. Local Agent Operations

> Safety rails and operational guide for local LMStudio-hosted agents executing scheduler tasks.

### Permissions

**Allowed:**
- Read any file in the CosySim codebase
- Edit/create files specified in the task ticket
- Run the test suite
- Search and add entries to Nexus
- Create git commits (conventional commit format)

**Prohibited:**
- Delete files
- Modify `engine/mcp/` core framework files (unless explicitly authorized)
- Modify `config/default.yaml` without backup
- Make real HTTP calls to external services in tests
- Push to remote repositories
- Install new packages without authorization
- Modify other agents' active tasks
- Skip running tests before committing

### Task Ticket Format

```json
{
    "id": "task-uuid",
    "title": "Short task description",
    "description": "Detailed requirements and acceptance criteria",
    "priority": 1,
    "complexity": "low|medium|high",
    "status": "claimed",
    "assigned_agent": "agent-name",
    "allowed_operations": ["read", "edit", "create", "test"],
    "target_files": ["engine/skills/builtin/my_skills.py"],
    "acceptance_criteria": ["Tests pass", "No regressions", "Nexus entry created"]
}
```

### Execution Workflow

1. **Claim** -- Acknowledge the assigned task.
2. **Research** -- Search Nexus for context. Read relevant test files.
3. **Baseline tests** -- Run full test suite, record pass count.
4. **Implement** -- Minimal, surgical changes. Follow Python conventions.
5. **Test** -- Run full suite again. Verify same or more tests pass, 0 failures.
6. **Store results** -- Add a Nexus entry documenting decisions and changes.
7. **Commit** -- `git commit -m "feat: description" -m "Task: task-uuid" -m "Co-authored-by: ..."`.
8. **Report** -- Mark task complete with files changed, tests added, Nexus entries created.

### Pre-Commit Safety Checks

| Check | How |
|-------|-----|
| Tests pass | `python -m pytest tests/ -q --tb=line` |
| No syntax errors | `python -m py_compile changed_file.py` |
| Imports are absolute | grep for `from .` in changed files |
| No print statements | grep for `print(` in changed files |
| Type hints present | Review function signatures |
| No hardcoded values | grep for port numbers, file paths |

### Complexity Guidelines

| Level | Examples |
|-------|----------|
| **Low** | Add a test case, fix a typo, update a config value, add a Nexus entry |
| **Medium** | Add a new skill, fix a bug with known root cause, refactor a module, update docs |
| **High** | Add a new scene, modify the interceptor pipeline, change inference routing, multi-file refactoring |

If a task feels higher complexity than labeled, STOP and report.

### Error Recovery

1. **Test failures after change**: `git checkout -- .` to revert.
2. **Can't understand the task**: Mark as "blocked" with explanation.
3. **Unexpected behavior**: Revert and report -- do not chase cascading issues.
4. **Nexus unreachable**: Continue but note Nexus storage is pending.

### Communication Channels

Local agents communicate through: task status updates (scheduler), Nexus entries (knowledge/decisions), git commits (code changes), task comments (questions/blockers). Agents do not send emails, interact with external services, modify the scheduler, or communicate directly with other agents.

---

## See Also

- [Configuration](./CONFIGURATION.md) -- `logging`, `news_system` sections in `default.yaml`
- [KPI & Benchmarking](./KPI.md) -- `@timed`, LLM KPIs, admin dashboard
- [Architecture](./ARCHITECTURE.md) -- System design and data flow
- [Deployment](./DEPLOYMENT.md) -- Service startup order and ports
- [Nexus Integration](./NEXUS_INTEGRATION.md) -- Knowledge storage and query router
- [Agent Onboarding](./AGENT_ONBOARDING.md) -- Copilot/local agent onboarding and session logging
