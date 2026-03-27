# CosySim CLI & Apps Reference

> v1.57.2 [2026-03-27] - Unified CLI and standalone app reference.
>
> All CLI apps auto-exec into `.venv/Scripts/python.exe` - no manual venv activation needed.

---

## Unified CLI

The root `cli.py` provides a single entry point to all tools:

```bash
python cli.py <command> [args...]
python cli.py --help
```

## Standalone Apps

Each app in `apps/` is independently runnable with the same venv bootstrap:

```bash
python apps/nexus.py search "query"
python apps/argus.py har file.har
python apps/account.py list
```

---

## Command Reference

### AI & Models

| App | Command | Description |
|-----|---------|-------------|
| `ask` | `python apps/ask.py "prompt"` | AI query - routes to Copilot (38 models), NLM, or LMStudio |
| | `--model claude-opus-4.6` | Specify model (Anthropic, Google, OpenAI, xAI) |
| | `--nlm` | Route to NotebookLM (grounded research) |
| | `--local` | Route to local LMStudio |
| | `--models` | List all available models |
| `nlm` | `python apps/nlm.py ask "question"` | Query NotebookLM via CDP browser |
| | `ingest --file FILE` | Ingest file into NLM notebook |
| | `upload FILE [--notebook-url URL]` | Upload with auto-rename (.py -> .py.txt) |
| | `create [--name NAME]` | Create new NLM notebook |
| | `seed FILE` | Bulk-ask Q&A pairs, store in Nexus |
| | `chain PIPELINE` | Run Gemini prompt chain |
| | `flashcards` | Generate flashcards via Gemini |
| | `protocol` | Reverse-engineer NLM API from HAR |
| | `cli <subcmd>` | Full NLM CLI (16 commands) |
| `nexus` | `python apps/nexus.py search "query"` | Search Nexus knowledge base |
| | `ask "question"` | Smart Q&A (7-tier query router) |
| | `add "title" "content" --type TYPE` | Add knowledge entry |
| | `status` | Nexus health and statistics |
| | `prompts [--category]` | List prompt templates |
| | `rules [--scope]` | Get governance rules |
| | `nlm <subcmd>` | NLM operations (ask, batch-ask, distill, stats) |
| | `seed` | Seed core Q&A pairs |
| | `embed "text"` | Generate embeddings |
| | `maintenance` | Run cleanup, dedup, reindex |
| `filestore` | `python apps/filestore.py list` | List Gemini File Search stores |
| | `create "name"` | Create new store |
| | `upload STORE FILE [FILES...]` | Upload documents to store |
| | `docs STORE` | List documents in store |
| | `query STORE "question"` | Grounded query with citations |
| | `bootstrap` | Upload core project docs (13 files) |
| | `bootstrap-code` | Upload engine source (14 files) |
| | `bootstrap-all` | Both docs + code |
| `lmstudio` | `python apps/lmstudio.py status` | Check LMStudio health + loaded models |
| | `models` | List available models |
| | `chat "prompt"` | Quick one-shot inference |
| | `bench` | Run latency benchmark (5 prompts) |
| | `proxy` | Start OpenAI-compatible proxy (:5800) |

### Analysis

| App | Command | Description |
|-----|---------|-------------|
| `argus` | `python apps/argus.py har FILE [--report]` | Analyze HAR file |
| | `heap FILE` | Mine V8 heap snapshot |
| | `auto DIR` | Auto-analyze all captures |
| | `compare A B` | Diff two HAR files |
| | `heap-diff A B` | Diff two heap snapshots |
| | `probe` | Live NLM chat probe via CDP |
| | `crawl` | Systematic NLM UI crawl |
| | `grpc` | Scan for gRPC + batchexecute calls |
| | `capture` | Type into NLM chat, capture payload |
| | `registry` | Validate RPC ID registry |
| | `vision` | Vision-based page analysis |
| `har` | `python apps/har.py list` | List all known HAR files |
| | `analyze FILE` | Quick analysis summary |
| | `deep FILE` | Deep mine for endpoints, rpcids, schemas |
| | `payloads FILE` | Extract operation codes, model IDs |
| | `cookies FILE [--domain X]` | Extract all cookies |
| | `capture` | Cookie refresh via CDP |
| | `watch` | Watch folder for new HAR files |
| `heap` | `python apps/heap.py heap FILE` | Parse V8 heap snapshot |
| | `cookies --update-pool ACCOUNT` | Decrypt Chrome cookies |
| | `live --metamap` | Scan live Chrome process memory |
| | `all` | Run all three extraction strategies |
| | `report` | Summarize previous runs |
| `cdp` | `python apps/cdp.py tabs` | List open Chrome tabs |
| | `dom [TAB] [--url URL]` | Full DOM/z-index report |
| | `css [TAB] SELECTOR` | Computed CSS for element |
| | `net [TAB]` | Capture network + console |
| | `api [TAB] PATH` | Fetch API from page context |
| | `js [TAB] EXPR` | Evaluate JS expression |
| | `snap [TAB] [FILE]` | Screenshot to PNG |
| | `trace [TAB]` | DOM + CSS + net + console |
| | `monitor` | Persistent live browser watcher |
| | `probe` | Attach to NLM tab, inject fetch calls |

### Operations

| App | Command | Description |
|-----|---------|-------------|
| `oracle` | `python apps/oracle.py` | Full diagnostic report |
| | `--health` | Service health grid |
| | `--errors` | Top errors by count |
| | `--perf` | LLM latency, benchmarks |
| | `--trace ID` | Trace waterfall |
| | `--logs N` | Last N error-level logs |
| `test` | `python apps/test.py` | Tests for uncommitted changes |
| | `--smoke` | Quick smoke tests (~15 files) |
| | `--domain NAME` | All tests for a domain |
| | `--since HEAD~3` | Tests for last 3 commits |
| | `--list` | Dry-run (show what would run) |
| | `browser [--scene NAME]` | Automated browser UI test |
| | `health [--port PORT]` | CDP-based scene health check |
| `launch` | `python apps/launch.py penthouse` | Launch single scene |
| | `--core` | Core scenes + services |
| | `--all` | Everything |
| | `--list` | Show targets with port status |
| `cleanup` | `python apps/cleanup.py` | Dry run (show what would be freed) |
| | `--execute` | Actually delete + checkpoint WALs |
| | `--execute --keep-hars 3` | Keep 3 days of HARs |
| `training` | `python apps/training.py status` | Pipeline status + dataset counts |
| | `datasets` | List all datasets with line counts |
| | `bench` | Show benchmark results |
| | `train` | Start fine-tuning |

### Accounts

| App | Command | Description |
|-----|---------|-------------|
| `account` | `python apps/account.py list` | List all accounts in pool |
| | `import FILE` | Import cookies from HAR/JSON |
| | `import FILE --analyze` | Analyze without importing |
| | `import FILE --name NAME` | Explicit account name |
| | `cookies` | Extract from Chrome via CDP/DPAPI |
| | `refresh [--mode cdp]` | Refresh Google cookies via CDP |

---

## Architecture

```
cli.py (unified entry point)
  |
  +-- apps/_bootstrap.py (shared venv/path bootstrap)
  |
  +-- apps/nexus.py -----> engine/nexus/cli.py + nlm_cli.py
  +-- apps/argus.py -----> scripts/argus/analyze.py + scripts/argus_*.py
  +-- apps/oracle.py ----> scripts/oracle.py
  +-- apps/ask.py -------> scripts/ask.py
  +-- apps/cdp.py -------> scripts/cdp_inspect.py + cdp_monitor.py
  +-- apps/nlm.py -------> scripts/nlm_*.py + engine/nexus/nlm_cli.py
  +-- apps/account.py ---> engine/integrations/github_account_importer.py
  +-- apps/har.py -------> engine/integrations/har_parser.py + scripts/har_*.py
  +-- apps/heap.py ------> scripts/heap_toolkit.py
  +-- apps/test.py ------> scripts/smart_test.py + browser_test.py
  +-- apps/lmstudio.py --> engine/lmstudio/chat.py + lms_client.py
  +-- apps/training.py --> training/auto_train.py
  +-- apps/filestore.py -> engine/integrations/file_search_client.py
  +-- apps/launch.py ----> launcher.py
  +-- apps/cleanup.py ---> scripts/disk_cleanup.py
```

All apps use the `_bootstrap.py` module which:
1. Detects if running from system Python (not venv)
2. Re-execs with `.venv/Scripts/python.exe` via subprocess
3. Sets project root on `sys.path`
4. Changes CWD to project root

---

## NLM File Upload Notes

NotebookLM blocks certain file extensions. The `apps/nlm.py upload` command
auto-renames blocked extensions by appending `.txt`:

**Blocked:** `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.css`, `.scss`, `.java`, `.go`,
`.rs`, `.c`, `.cpp`, `.h`, `.yaml`, `.yml`, `.toml`, `.sql`, `.proto`, `.sh`, `.ps1`

**Example:** `engine/config.py` -> `engine/config.py.txt`

The Gemini File Search API (`apps/filestore.py`) accepts all these directly -
use it for code-grounded queries instead.

---

## See Also

- [Operations](OPERATIONS.md) - Launcher, TUI, ports, logging
- [Architecture](ARCHITECTURE.md) - System design, layers, data flow
- [Configuration](CONFIGURATION.md) - YAML config, get_config() pattern
- [ARGUS](ARGUS.md) - Web app analysis toolkit
- [Testing](TESTING.md) - Smart test system, fixtures

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.57.2 | 2026-03-27 | Initial CLI + 15 standalone apps |
