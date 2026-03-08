---
description: 'ARGUS browser automation patterns — CDP bridge, heap analysis, network capture, automated API exploration'
applyTo: 'scripts/argus/**/*.py'
---

# ARGUS Browser Automation System

## Architecture
ARGUS is split into three paths:
1. **Live orchestrator crawlers** — Playwright + CDP browser automation
2. **LMStudio+MCP ArgusAgent** — AI-driven browser control via tool calling
3. **Offline tools** — HAR parsing, heap analysis, protocol monitoring

All paths share decoders but are NOT one unified pipeline.

## CDP Bridge Pattern
```python
import websockets
import json

# Connect to Chrome DevTools Protocol
ws = await websockets.connect("ws://localhost:9222/devtools/page/<target_id>")

# Execute JavaScript in page context
await ws.send(json.dumps({
    "id": 1,
    "method": "Runtime.evaluate",
    "params": {"expression": "document.title"}
}))

# Network capture
await ws.send(json.dumps({
    "id": 2,
    "method": "Network.enable"
}))
```

## File Organization
```
scripts/argus/
├── __init__.py
├── agent.py              # ArgusAgent with LMStudio tool calling
├── browser_tools.py      # Playwright browser control + CDP bridge
├── config.py             # Baselines, targets, CDP port
├── explorer.py           # Automated API surface testing
├── orchestrator.py       # Master crawl controller
├── decoders/
│   ├── batchexecute.py   # f.req → rpcid+payload parsing
│   ├── grpc_web.py       # Binary gRPC-web frame decoding
│   └── heap_diffing.py   # CDP heap snapshot diffing
├── discovery/
│   └── endpoint_registry.py  # Versioned endpoint tracking
├── tools/
│   ├── __main__.py       # CLI: screenshot, ask, token refresh
│   ├── har_replay.py     # HAR file replay and analysis
│   └── token_harvester.py  # CDP token + cookie extraction
└── reporting/
    └── api_doc_generator.py  # Generate API reference from captures
```

## Explorer System
```python
from scripts.argus.explorer import AutoExplorer

explorer = AutoExplorer()
results = explorer.run(mode="auto")  # auto|discover|sweep

# CLI usage:
# python -m scripts.argus.explorer --mode auto --report --store-nexus
# python -m scripts.argus.explorer --mode sweep --op list_notebooks
# python -m scripts.argus.explorer --mode discover
```

## Key Conventions
- Always store discoveries in Nexus via `NexusCatalogStore`
- Use `data/argus/` for captures, heap diffs, SSL keys
- Chrome CDP runs at `localhost:9222` — always on
- Browser data is gitignored: `data/har_files/`, heap output, captures
- Never commit cookies, tokens, or auth artifacts

## Token Refresh
```python
# Preferred: Direct CDP extraction (fastest, no UI)
python scripts/har_capture.py --mode cdp --account knack112358

# Fallback: Full browser harvest
python -m scripts.argus.tools harvest --account knack112358
```

## Heap Analysis
```python
# Capture heap snapshots for API surface mining
from scripts.argus.decoders.heap_diffing import HeapDiffer

differ = HeapDiffer()
before = differ.capture_snapshot()
# ... perform action ...
after = differ.capture_snapshot()
new_shapes = differ.diff(before, after)
```

## Testing
```bash
python -m pytest tests/test_argus_explorer.py tests/test_argus_tools.py -v
```
