# Scheduler Daemon — Autonomous Task System

> **Module:** `engine/nexus/scheduler_daemon.py`
> **Version:** v1.18a
> **Tasks:** 61 recurring tasks
> **Tests:** `tests/test_scheduler_daemon.py` (44 tests)

## Overview

The scheduler daemon manages recurring background tasks for CosySim's autonomous
operations: Nexus maintenance, news ingestion, pipeline execution, training data
collection, system health monitoring, and more.

Tasks are plain Python callbacks registered with schedule strings. The daemon
persists execution state across restarts and logs results to Nexus for audit.

## Architecture

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

## Task Registration

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()

daemon.register(
    task_id="my-task",          # Unique identifier
    name="My Task Description", # Human-readable name
    schedule="every_4h",        # Schedule string
    callback=my_callback,       # Zero-arg function → Dict[str, Any]
    enabled=True,               # Whether to auto-run
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
| `"every_Nh"` | N hours (arbitrary) |
| `"every_Nm"` | N minutes (arbitrary) |

### Callback Pattern

Callbacks must be zero-argument functions returning a dict:

```python
def my_callback() -> Dict[str, Any]:
    """Do something useful and return results."""
    try:
        # Lazy imports inside callback
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        # Do work
        result = client.search("important things")

        # Optionally store results
        client.add_entry(
            title="Task Result",
            content=json.dumps(result),
            content_type="history",
            category="system",
        )

        return {"items_processed": len(result), "status": "ok"}
    except Exception as exc:
        logger.error("Task failed: %s", exc)
        return {"error": str(exc)}
```

## Task Categories (61 Tasks)

### Nexus Maintenance (12 tasks)
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

### Workspace Pipeline (4 tasks)
| Task ID | Schedule | Description |
|---------|----------|-------------|
| `workspace-news-pipeline` | every_8h | RSS → NLM → Sheets → Nexus |
| `workspace-news-to-knowledge` | daily | News → NLM → Docs → Drive → Nexus |
| `workspace-research-cycle` | every_12h | Research queued topics from Nexus |
| `workspace-pipeline-health` | every_6h | Client connectivity and stage health |

### News & Intelligence (4 tasks)
| Task ID | Schedule | Description |
|---------|----------|-------------|
| `news-fetch` | every_8h | RSS fetch, score, store, NLM distillation |
| `news-nlm-retry` | every_8h | Retry failed NLM distillation jobs |
| `news-source-health` | daily | Check RSS feed availability |
| `news-digest-publish` | daily | Publish daily digest to scenes |

### NotebookLM (6 tasks)
| Task ID | Schedule | Description |
|---------|----------|-------------|
| `notebook-rotation` | weekly | Rotate NLM notebooks by age/size |
| `notebook-health` | daily | Check notebook accessibility |
| `control-notebook-flywheel` | every_4h | Run control notebook follow-up tasks |
| `nlm-distil-queue` | every_8h | Process NLM distillation queue |
| `argus-nlm-distil` | weekly | Upload ARGUS discoveries, batch Q&A |
| `improvement-review` | weekly | NLM review of low-quality responses |

### System Health (8 tasks)
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

### Training & Data (6 tasks)
| Task ID | Schedule | Description |
|---------|----------|-------------|
| `flywheel-collect` | every_4h | Collect training data from sessions |
| `flywheel-quality` | daily | Score training example quality |
| `flywheel-export` | daily | Export training datasets |
| `benchmark-run` | daily | Run model benchmarks |
| `cdp-mine` | daily | Mine CDP logs for training data |
| `colab-pipeline-sync` | daily | NLM→Drive→Colab analysis sync |

### ARGUS & Browser (4 tasks)
| Task ID | Schedule | Description |
|---------|----------|-------------|
| `argus-weekly-scan` | weekly | Full API surface scan |
| `argus-diff-report` | weekly | Compare scans, store deltas |
| `har-watchfolder` | every_4h | Process new HAR captures |
| `cdp-health` | every_4h | Check CDP endpoint availability |

### Other (17 tasks)
Additional tasks for operator inbox, session logging, Copilot validation,
inventory snapshots, etc.

## CLI Usage

```bash
# Show status of all tasks
python -m engine.nexus.scheduler_daemon status

# Run a specific task immediately
python -m engine.nexus.scheduler_daemon run workspace-news-pipeline

# Start the daemon (checks tasks every 60s)
python -m engine.nexus.scheduler_daemon start
```

## Python API

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()

# Run a task immediately
result = daemon.run_task("workspace-news-pipeline")

# Check task status
task = daemon._tasks.get("news-fetch")
print(f"Last run: {task.last_run}")
print(f"Run count: {task.run_count}")
print(f"Last result: {task.last_result}")

# List all task IDs
task_ids = list(daemon._tasks.keys())

# Enable/disable a task
daemon._tasks["my-task"].enabled = False
```

## State Persistence

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

State survives restarts — tasks resume from where they left off.

## Adding New Tasks

1. **Define the callback** (module-level function in `scheduler_daemon.py`):
```python
def _my_new_task_callback() -> Dict[str, Any]:
    """Description of what this task does."""
    try:
        # Lazy imports
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        # Do work...
        return {"status": "ok", "items": 42}
    except Exception as exc:
        logger.error("Task failed: %s", exc)
        return {"error": str(exc)}
```

2. **Register in `_register_builtin_tasks()`**:
```python
daemon.register(
    "my-new-task",
    "My New Task — does something useful",
    "every_4h",
    _my_new_task_callback,
)
```

3. **Add test**:
```python
def test_my_new_task_registered(self) -> None:
    from engine.nexus.scheduler_daemon import _register_builtin_tasks
    daemon = MagicMock()
    _register_builtin_tasks(daemon)
    task_ids = [call.args[0] for call in daemon.register.call_args_list]
    assert "my-new-task" in task_ids
```

4. **Update task count** in `test_builtin_task_count`.

## Related Documentation

- [Workspace Pipeline](WORKSPACE_PIPELINE.md) — Pipeline templates and stages
- [News System](NEWS_SYSTEM.md) — RSS sources and NLM distillation
- [Nexus Integration](NEXUS_INTEGRATION.md) — Knowledge storage
- [Deployment](DEPLOYMENT.md) — Service startup order
