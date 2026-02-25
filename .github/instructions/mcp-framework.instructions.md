---
description: 'CosySim MCP framework patterns — skill decorator, interceptors, governance pipeline, state coordination'
applyTo: 'engine/mcp/**/*.py,engine/skills/**/*.py,engine/agents/**/*.py'
---

# MCP Framework Patterns

## Skill Decorator
```python
@skill(
    pack="scene_name",           # Skill grouping
    description="LLM-facing desc",  # What the LLM sees
    category="game",             # COMMUNICATION|MEMORY|MEDIA|GAME|SOCIAL|ENVIRONMENT|SYSTEM|NARRATIVE
    cooldown=5.0,                # Min seconds between calls
    cost=1.0,                    # Budget tracking
    tags=["combat", "rpg"],      # Free-form tags
    prerequisites=["other_skill"],  # Must run first
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

## Interceptor Pipeline
```python
from engine.mcp import InterceptorBase

class MyInterceptor(InterceptorBase):
    def pre_call(self, request, context):
        # Inject system prompts, modify request before LLM
        return request

    def post_call(self, response, context):
        # Strip artifacts, extract tags, modify response after LLM
        return response
```
Register in `config/default.yaml` under `comms.interceptors`.

## Governance Context Flow
`AgentGovernor` → `CharacterAgent.reply()` → `VirtualAgent.reply()` → `build_request()`
- Pass `governance_context` kwarg through the chain
- Context appended after agent's base system prompt
- Without this, interceptor injections are silently lost

## State Coordination
- `MCPFramework` — root singleton via `get_framework()`
- `MCPSceneNode` — per-scene state container
- `MCPCharacterNode` — per-character state (stats, inventory, relationships)
- `MCPTimer` — scheduled events with callbacks
- State auto-persists if `framework.state_persistence` enabled in config

## Key Singletons
```python
get_framework()              # MCPFramework
get_character_registry()     # CharacterRegistry
get_dialog_system()          # DialogSystem
get_rules_engine()           # SceneRulesEngine
get_scene_state_manager()    # SceneStateManager
get_governor()               # AgentGovernor
get_router()                 # AgentRouter
```

## Stream Processing
- `StreamProcessor` extracts tags: [MOOD:x], [IMAGE:prompt], [ACTION:x], [STAT:name±val], [VOICE:style]
- Use `infer_processed()` for rich responses with tag extraction
- Use `infer_stream()` for raw streaming
