---
description: 'CosySim YAML configuration conventions — dot-notation access, defaults, no hardcoding'
applyTo: 'config/**/*.yaml,config/**/*.yml'
---

# Configuration Conventions

## Access Pattern
Always use `get_config()` with dot-notation and defaults:
```python
from engine.config import get_config
cfg = get_config()
port = cfg.get("scenes.bedroom.port", 5555)
model = cfg.get("lmstudio.models.primary", "default-model")
```

## File Hierarchy
- `config/default.yaml` — base configuration (all settings)
- `config/development.yaml` — dev overrides (debug=true, test DB)
- `config/production.yaml` — prod overrides (debug=false, real paths)
- `config/voices.yaml` — TTS voice definitions
- `config/skill_manifests.yaml` — skill pack metadata
- `config/mcp.json` — MCP server definitions

## Rules
- Never hardcode ports, paths, model names, or API URLs
- Always provide sensible defaults in `get()` calls
- Keep environment-specific values in development.yaml/production.yaml
- Keep default.yaml as the single source of truth for all settings
- Use 2-space indentation in YAML files
