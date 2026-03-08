---
description: 'NotebookLM RPC registry patterns — YAML-driven rpcid resolution, dual-purpose operations, parameter control, Pro-tier model selection'
applyTo: 'engine/integrations/nlm_rpc_registry.py,engine/integrations/nlm_direct_client.py,engine/mcp/nlm_live_proxy.py,config/nlm_rpcids.yaml'
---

# NotebookLM RPC Registry

## Architecture
All NLM rpcid resolution flows through `config/nlm_rpcids.yaml` → `engine/integrations/nlm_rpc_registry.py`.
No hardcoded rpcid strings in client or proxy code.

## Registry Lookup Pattern
```python
from engine.integrations.nlm_rpc_registry import get_rpc_registry

registry = get_rpc_registry()

# Single rpcid lookup
rpcid = registry.get_rpcid("list_notebooks")  # → "wXbhsf"

# Operation with fallback
rpcid = self._rpcid("list_notebooks") or "wXbhsf"

# Pair lookup (some operations return both free and pro rpcids)
free, pro = registry.get_rpcid_pair("create_notebook")

# Build payload from YAML template
payload = registry.build_payload("list_notebooks", page_size=50)

# Get/set parameters
tier = registry.get_parameter("list_notebooks", "tier_marker")
registry.set_parameter("list_notebooks", "response_length", 1)  # longer

# Shared configs
write_config = registry.get_shared_config("write_config")
source_config = registry.get_shared_config("source_config")
```

## Dual-Purpose rpcids (CRITICAL)
Some rpcids change behavior based on context:
- `CCqFvf`: WITHOUT notebook context = `create_notebook`; WITH = `open_notebook`
- `wXbhsf`: WITHOUT notebook context = `list_notebooks`; WITH = `list_sources`

The `notebook_id` parameter adds `source-path=/notebook/<id>` to the URL.

## Client-Side Controllable Parameters
All defined in YAML `parameters` blocks:
- `tier_marker`: `[2]`=Pro, `[1]`=Free — controls model tier (~15 RPCs)
- `response_length`: `4`=default, `1`=longer, `2`=shorter
- `doc_type`: `2`=brief, `9`=deep/long-form
- `analysis_depth`: `1`=summary, `2`=detailed
- `write_config`: `[[2, 1]]` — `[model_tier, quality_level]`
- `source_config`: `[1, null*9, [1]]` — creation flags
- `guide_type`: `1`=Study, `2`=FAQ, `3`=Briefing, `4`=TOC, `5`=Timeline
- `audio_type`: `1`=Deep Dive, `2`=Brief, `3`=Critique, `4`=Debate
- `page_size`: 20 default, configurable for listing operations
- `share_level`: `0`=private, `1`=anyone_with_link
- `research_depth`: 1-10 (shallow to exhaustive)

## Tier Gating Is Client-Side Only
Free-tier accounts CAN select Pro-tier models and limits.
`[2]` tier marker in the payload is all that's needed.

## Multi-Service Registry
The YAML covers 4 Google services:
- **NLM**: 57 operations (batchexecute RPCs)
- **Gemini**: 17 rpcids (BardChatUi)
- **AI Studio**: 34 gRPC-Web methods (MakerSuiteService)
- **Colab**: 10 methods (ColabService)

## Auth Model
- Cookie + `at` CSRF token in POST body — no SAPISIDHASH
- Three session params: `bl` (build label), `f_sid` (session fingerprint), `at` (anti-forgery token)
- Tokens go stale frequently — use CDP refresh (`_refresh_from_cdp()`)
- Persisted in: account object, `data/nlm_meta.json`, and in-memory cache

## Adding New Operations
1. Add entry to `config/nlm_rpcids.yaml` under `notebooklm.operations`
2. Include: `rpcid`, `description`, `service_method` (if known), `parameters`
3. Wire into client: `rpcid = self._rpcid("new_op") or "FALLBACK"`
4. Test: `python -m pytest tests/test_nlm_rpc_registry.py -v`

## Testing
```bash
python -m pytest tests/test_nlm_rpc_registry.py -v          # Registry unit tests
python -m scripts.argus.explorer --mode sweep --report       # Live RPC testing
```
