---
description: 'CosySim scene development patterns — BaseScene lifecycle, MCP wiring, skill packs, templates, and state management'
applyTo: 'content/scenes/**/*.py'
---

# Scene Development Patterns

## Scene Structure
Every scene lives in `content/scenes/{name}/` with:
- `__init__.py` — Scene class inheriting `BaseScene`
- `{name}_skills.py` — @skill-decorated functions (pack="{name}")
- `templates/` — Jinja2 HTML templates
- `static/` — CSS, JS, images

## Required Overrides
```python
from engine.scenes.base_scene import BaseScene

class MyScene(BaseScene):
    SCENE_METADATA = {"name": "my_scene", "port": 5567, "type": "game"}

    def start(self): ...       # Initialize, register MCP nodes, start Flask
    def stop(self): ...        # Persist state, cleanup
    def get_plugin_info(self): ...  # Return metadata for hub discovery
```

## MCP Integration
- Create scene node: `fw.get_or_create("scenes.{name}", MCPSceneNode)`
- Create character nodes for each loaded character
- Register all skills in scene `__init__.py` by importing `{name}_skills`
- Wire DialogSystem for conversation tracking
- Wire EventChain for audit logging

## State Management
- Use `SceneStateManager` for mutable scene state
- Never store game state in Python locals — always MCP tree
- Use `MCPTimer` for scheduled events
- Use `ScheduledConsequence` for delayed effects

## Skills Pattern
- Scene skills go in `{name}_skills.py`
- Use `@skill(pack="{name}", description="...", category="game")`
- Access running scene via `BaseScene.get_active_scene("{name}")`
- Skills return string results for LLM consumption

## Character Lifecycle
- `on_character_added(character)` — sync to MCP, set up personality
- `on_character_removed(character_id)` — cleanup MCP nodes
- Characters have: traits, emotions (0–100), relationships, speech patterns

## Templates
- Use Jinja2 with `{{ scene_data }}` context
- Include Socket.IO for real-time updates
- Static assets served from `static/` directory
- **NEVER** explicitly load `navbar_v2.css` or `navbar_v2.js` — `navbar_v2.html` is self-contained
- **NEVER** load `aria_widget.js` — use `{% include 'aria_widget.html' %}` instead
- Use `{% include 'navbar_v2.html' %}` as the single navbar include

## Required start() Routes
Every scene `start()` MUST call all of these after Flask setup:
```python
from content.shared import register_shared_assets
register_shared_assets(self.app)        # /shared/* routes — REQUIRED or all shared assets 404
self.register_health_route(self.app)    # /api/health
self.register_hud_route(self.app)       # /api/hud/state
self.register_announcer_route(self.app) # /api/announcer/feed
```

## Health Check (run after every scene edit)
```powershell
python scripts/scene_health_check.py --port <PORT> --fix
```
See `.github/instructions/scene-debugging.instructions.md` for full debugging guide.
