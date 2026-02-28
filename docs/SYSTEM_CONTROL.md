# System Control Panel

> Port **5575** · Flask scene · `content/scenes/system_control/`

The System Control Panel is the human operator's window into the running CosySim
system. It provides direct read/write access to configuration files, service
health monitoring, launcher control, NLM proxy management, and Nexus inspection —
all in a single dark-themed UI.

## Quick Start

```bash
python launcher.py system_control
# or auto-starts with:
python launcher.py --core
```

Open: [http://localhost:5575](http://localhost:5575)

---

## Tabs

### 1. Overview
- CPU, RAM, GPU utilisation (live refresh every 30s)
- System uptime and Python version
- Quick links to all services

### 2. Services
- Health status for all 19 CosySim services (parallel checks, 3s timeout)
- Shows port, label, status (✅ online / ❌ offline)
- Refresh button

### 3. Config Editor
- Dropdown lists all editable YAML + JSON config files
- Load → edit in textarea → validate → save (creates .bak backup automatically)
- Validates YAML syntax before writing
- Editable files: `config/default.yaml`, `config/production.yaml`, `config/launcher.yaml`,
  `config/voices.yaml`, `config/skill_manifests.yaml`, `config/mcp.json`, `config/news_sources.yaml`

### 4. Launcher
- Toggle `auto_start` on/off for each service and scene
- Persisted immediately to `config/launcher.yaml`
- Shows current port for each target

### 5. NLM Proxy
- Status: connected / offline, BL age, cookie freshness
- Import HAR file (drag & drop or paste path)
- Capture Chrome cookies via CDP (requires Chrome running)
- List all notebooks with source counts

### 6. Nexus
- Health: entry count, QA pair count, rules count
- Quick search: type a query and see top 5 results immediately
- Links to Nexus Panel (:5570) for full management

### 7. LMStudio
- Connection status to `localhost:1234`
- Lists all loaded models with size / context info
- Quick model load (enter model ID)

### 8. Logs
- Dropdown of available log files in `logs/`
- Tail last N lines (configurable)
- Auto-refresh every 10s

### 9. Git
- Current branch and last 10 commits (one-line format)
- Working tree status (modified / untracked files)
- Refresh button

---

## API Endpoints

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

---

## Architecture Notes

- The panel never calls NLM directly — all NLM operations proxy to `:8800`
- Config writes are atomic: file validated then written; on validation failure nothing is changed
- `.bak` backups are created before each config write
- Service health checks run in parallel threads (10-thread pool)
- Metrics use `psutil` (CPU/RAM) and `pynvml` (GPU); both degrade gracefully if not installed

---

## Configuration

In `config/default.yaml`:
```yaml
scenes:
  system_control:
    host: "localhost"
    port: 5575
    debug: false
```

In `config/launcher.yaml`:
```yaml
services:
  system_control:
    auto_start: true
```
