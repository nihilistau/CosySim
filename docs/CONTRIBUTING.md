# Contributing

> CosySim Documentation -- v1.51.0 [2026-03-25]
>
> Development conventions, scene creation, skills, testing, and code standards.

---

## 1. Development Setup

### Prerequisites

- **Python 3.10+** (3.13 recommended)
- **Node.js 18+** (for Nexus Canvas)
- **LMStudio** running at `:1234` with at least one model loaded

### Install

```bash
pip install -r requirements.txt && npm install
```

### Verify

```bash
python launcher.py --status           # System health check
python launcher.py --list             # All targets with port status
python -m pytest tests/ --smoke-only  # Quick smoke test (~30s)
```

### Launch for Development

```bash
python tui.py                         # Terminal UI (recommended)
python launcher.py penthouse          # Single scene at http://localhost:5556
python launcher.py --core             # Core auto-start targets
```

---

## 2. Code Conventions -- Python

### Imports

Absolute imports only. Never use relative imports (`from .foo`). Group with blank lines:

```python
# 1. Standard library
import logging
from pathlib import Path
from typing import Dict, Optional

# 2. Third-party
from flask import Flask, render_template
import socketio

# 3. Engine
from engine.config import get_config
from engine.mcp.framework import get_framework

# 4. Content
from content.scenes.penthouse.penthouse_skills import my_skill

# 5. Local (same package -- still absolute)
from engine.skills.chain_context import get_chain_context
```

### Type Hints

Required on all function signatures. Use `from __future__ import annotations` for forward references:

```python
from __future__ import annotations

def process_message(
    scene_id: str,
    message: str,
    player_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process an incoming message."""
    ...
```

### Docstrings

Google style with `Args:`, `Returns:`, `Raises:`:

```python
def get_character(char_id: str, include_stats: bool = False) -> Dict[str, Any]:
    """Fetch a character profile by ID.

    Args:
        char_id: Unique character identifier (e.g. "lola").
        include_stats: If True, include neurochemistry state.

    Returns:
        Character profile dict with name, persona, traits.

    Raises:
        KeyError: If character not found in database.
    """
```

### Naming

| Element | Convention | Example |
|---------|-----------|---------|
| Classes | PascalCase | `PenthouseScene`, `SkillPack` |
| Functions/methods | snake_case | `get_active_scene()`, `register_skill()` |
| Files/modules | snake_case | `penthouse_scene.py`, `skill_registry.py` |
| Constants | UPPER_SNAKE | `MAX_RETRIES`, `DEFAULT_PORT` |
| Private | `_underscore` prefix | `_internal_state`, `_parse_response()` |

### Formatting

- 4-space indent (Python). Never tabs.
- Double quotes for strings. F-strings preferred.
- 88--100 character soft limit, 120 max.
- No `print()` statements. Use `logger = logging.getLogger(__name__)`.

### Configuration

Never hardcode ports, paths, or model names. Always use config with defaults:

```python
from engine.config import get_config
cfg = get_config()

port = cfg.get("scenes.penthouse.port", 5556)
model = cfg.get("lmstudio.models.primary", "default-model")
```

### Logging

Structured logging with context. Every module gets its own logger:

```python
import logging
logger = logging.getLogger(__name__)

logger.info("Scene started: %s on port %d", scene_id, port)
logger.error("LLM call failed for %s: %s", agent_name, err, exc_info=True)
```

Never swallow errors silently. Use `exc_info=True` for tracebacks. Embedding/API errors must be caught and surfaced, not swallowed.

### State Management

Mutable game state must sync to MCPFramework. Access config via `get_config().get("dot.path", default)`:

```python
from engine.mcp.framework import get_framework
fw = get_framework()
scene_node = fw.get_or_create("scenes.penthouse", MCPSceneNode)
scene_node.set("status", "running")
```

### EventChain

Every service interaction must be logged. If it's not in EventChain, it didn't happen:

```python
from engine.events.event_chain import get_event_chain
chain = get_event_chain()
chain.log("skill_called", {"skill": "attack", "target": "dragon"})
```

### SQL Safety

Always use parameterized queries (`?` placeholders). Column names in dynamic SQL must be validated against whitelists (see `ALLOWED_COLUMNS`):

```python
cursor.execute("SELECT * FROM characters WHERE id = ?", (char_id,))
```

---

## 3. Code Conventions -- Frontend

CosySim uses vanilla JavaScript with no build step. No React, Vue, or other frameworks.

### JavaScript

- 2-space indent. Single quotes in JS, double quotes in HTML attributes.
- `const` and `let` only. Never `var`.
- `const socket = io()` for Socket.IO. `fetch()` for REST. Never `XMLHttpRequest`.
- Template literals for string interpolation.

```javascript
const socket = io();

socket.on('connect', () => console.log('Connected'));
socket.on('state_update', (data) => updateUI(data));
socket.emit('action', { type: 'interact', data: { target: 'npc' } });

const response = await fetch('/api/health');
const data = await response.json();
```

### CSS

- 2-space indent.
- CSS custom properties for theming: `--primary-color`, `--bg-color`, `--accent`.
- kebab-case class names: `game-panel`, `chat-message`, `neon-glow`.
- Scene accent injection: `style="--accent: {{ accent_color }}"`.
- Prefer flexbox/grid. Mobile-responsive with media queries.

### Templates

Jinja2 templates live in `content/scenes/{name}/templates/`. All scene templates extend `neon_base.html`:

```html
{% extends "neon_base.html" %}

{% block title %}MY SCENE{% endblock %}

{% block scene_content %}
  <div class="scene-panel">
    <!-- Scene content -->
  </div>
{% endblock %}

{% block extra_js %}
  <script src="{{ url_for('static', filename='my_scene.js') }}"></script>
{% endblock %}
```

### Required Includes

Never manually load navbar CSS/JS -- the include is self-contained:

```html
{% include 'navbar_v2.html' %}
{% include 'aria_widget.html' %}
```

### Shared Assets

Every scene **must** call `register_shared_assets(self.app)` in `start()`. This mounts the `/shared/*` route for navbar, base CSS, and Aria widget assets.

### Browser Testing

After ANY JS/CSS/HTML change, run `python scripts/browser_test.py` (Playwright). Never commit UI changes without a passing browser test. Read telemetry: `python scripts/browser_test.py --report`.

---

## 4. Creating a Scene

Every scene lives in `content/scenes/{name}/` and follows a standard layout.

### Directory Structure

```
content/scenes/my_scene/
+-- __init__.py              # Scene class (BaseScene subclass)
+-- my_scene_skills.py       # @skill-decorated MCP functions
+-- templates/
|   +-- my_scene.html        # Jinja2 template (extends neon_base.html)
+-- static/
    +-- my_scene.css          # Scene-specific styles
    +-- my_scene.js           # Scene-specific JavaScript
    +-- img/                  # Scene images
```

### BaseScene Subclass

Every scene inherits from `BaseScene` (`engine/scenes/base_scene.py`) and optionally mixes in `MCPSceneMixin` for MCP framework registration:

```python
from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.shared import register_shared_assets
from content.scenes.my_scene import my_scene_skills  # noqa: F401

class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
    SCENE_METADATA = {
        "name": "my_scene",
        "display_name": "MY SCENE",
        "port": 5573,                  # Must match port_registry.py
        "type": "game",               # "game" | "utility" | "service"
        "accent_color": "#8b5cf6",
        "description": "A new scene in NeonCity.",
    }

    def start(self):
        """Initialize Flask, register routes, start serving."""
        self.app = Flask(__name__,
                         template_folder=str(Path(__file__).parent / "templates"),
                         static_folder=str(Path(__file__).parent / "static"))

        # REQUIRED shared asset routes
        register_shared_assets(self.app)
        self.register_health_route(self.app)       # /api/health
        self.register_hud_route(self.app)           # /api/hud/state
        self.register_announcer_route(self.app)     # /api/announcer/feed

        @self.app.route("/")
        def index():
            return render_template("my_scene.html", scene_data={...})

        self.app.run(host="0.0.0.0", port=self.SCENE_METADATA["port"])

    def stop(self):
        """Persist state, clean up resources."""
        pass

    def get_plugin_info(self):
        """Return metadata for hub discovery."""
        return self.SCENE_METADATA
```

### MCP Integration

Register the scene with the MCP framework so state is accessible system-wide:

```python
fw = get_framework()
scene_node = fw.get_or_create("scenes.my_scene", MCPSceneNode)
scene_node.set("status", "running")
scene_node.set("port", self.SCENE_METADATA["port"])
```

### Registration Checklist

1. Create the directory structure above.
2. Inherit from `BaseScene` and mix in `MCPSceneMixin`.
3. Implement: `start()`, `stop()`, `get_plugin_info()`.
4. Wire `build_governance_context()` + `StateCoordinator` in scene init.
5. Add entry to `engine/control_plane_registry.py` -> `SCENE_DEFS`.
6. Add port to `engine/port_registry.py` -> `_DEFAULT_PORTS`.
7. Add config to `config/default.yaml` under `scenes.<name>`.
8. Call `register_shared_assets(self.app)` and `self.register_health_route(self.app)`.
9. Add tests in `tests/test_my_scene.py`.
10. Run `python scripts/browser_test.py` if the scene has a UI.

### Active Scene Registry

Skills look up running scenes via `get_active_scene()`:

```python
from engine.scenes.base_scene import get_active_scene
scene = get_active_scene("my_scene")   # returns MyScene or None
```

### Template Context Variables

Templates receive these from the Flask route:

| Variable | Type | Description |
|----------|------|-------------|
| `scene_data` | dict | Scene-specific state |
| `scene_name` | str | Scene identifier |
| `accent_color` | str | CSS accent (e.g. `"#dc2626"`) |
| `port` | int | Scene port number |

---

## 5. Creating Characters

Characters are managed by the asset system (`engine/assets/`) and enriched with neurochemistry, relationships, and reputation.

### Core Character Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique identifier (e.g. `"lola"`) |
| `name` | str | Display name |
| `persona` | str | LLM system prompt personality |
| `traits` | list | Personality descriptors |
| `speech_pattern` | str | How the character talks |
| `backstory` | str | Background narrative |

### Neurochemistry System

Six neurotransmitters drive character emotions (`engine/characters/neurochemistry.py`):

| Neurotransmitter | Function | High State | Low State |
|------------------|----------|------------|-----------|
| **Dopamine** | Reward, motivation | Confident, focused | Apathetic |
| **Serotonin** | Mood stability | Content, warm | Anxious, irritable |
| **Oxytocin** | Bonding, trust | Affectionate | Distant, guarded |
| **Cortisol** | Stress response | Alert, on edge | Relaxed |
| **Adrenaline** | Fight-or-flight | Excited, reckless | Calm |
| **Endorphins** | Pain relief | Euphoric | Neutral |

Emotions are *computed* from neurotransmitter combinations -- no hardcoded moods:
- High dopamine + low cortisol = **Confident**
- High cortisol + high adrenaline = **Panicked**
- High oxytocin + high serotonin = **Loved**

```python
from engine.characters.neurochemistry import get_neurochemistry_manager

mgr = get_neurochemistry_manager()
state = mgr.get_or_create("lola")
mgr.apply_stimulus("lola", "received_compliment")     # boosts dopamine + oxytocin
prompt_ctx = mgr.get_prompt_context("lola")            # inject into LLM prompt
```

### ContentGate Levels

Enforces content intensity per player profile:

```python
from engine.content.content_gate import get_content_gate

gate = get_content_gate()
gate.set_profile("player1", sexual=2, violence=1, language=3)
allowed = gate.check("player1", "sexual", 3)   # False -- above limit
```

| Level | Label | Description |
|-------|-------|-------------|
| 0 | Clean | No adult content |
| 1 | Mild | Suggestive, mild language |
| 2 | Mature | Explicit suggestion, moderate violence |
| 3 | Explicit | Full explicit content |

### Seeded Characters

Five characters are always present in the database: **Lola**, **Viktor**, **Aria**, **Frankie**, and **Mira**. Tests can rely on these existing.

### Reputation System

See `engine/characters/reputation.py` -- tracks per-faction reputation (-100 to +100) with threshold-based relationship labels.

For full character system documentation, see [CHARACTER_SYSTEM.md](./CHARACTER_SYSTEM.md).

---

## 6. Writing Skills

Skills are MCP-callable functions registered via the `@skill` decorator. Each scene defines its skills in `content/scenes/{name}/{name}_skills.py`.

### The `@skill` Decorator

```python
from engine.skills.skill import skill, SkillCategory

@skill(
    pack="my_scene",                         # Skill grouping name
    description="What the LLM sees",         # Tool description for LLM
    category=SkillCategory.GAME,             # Category constant
    cooldown=5.0,                            # Min seconds between calls
    cost=1.0,                                # Budget tracking value
    tags=["combat", "rpg"],                  # Free-form tags
    prerequisites=["other_skill"],           # Must run first in session
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    scene = get_active_scene("my_scene")
    return f"Did something to {target}"
```

### Skill Categories

| Category | Constant | Use For |
|----------|----------|---------|
| Communication | `SkillCategory.COMMUNICATION` | Messaging, voice, cross-scene |
| Memory | `SkillCategory.MEMORY` | Search, store, recall |
| Media | `SkillCategory.MEDIA` | Images, voice, video |
| Game | `SkillCategory.GAME` | Game state, dice, scoring |
| Social | `SkillCategory.SOCIAL` | Mood, relationships |
| Environment | `SkillCategory.ENVIRONMENT` | Lighting, props, scene changes |
| System | `SkillCategory.SYSTEM` | Config, status, admin |
| Narrative | `SkillCategory.NARRATIVE` | Story beats, dialog, narration |

### Pack Convention

- Skill files live at `content/scenes/{name}/{name}_skills.py`.
- Import in the scene's `__init__.py`: `from content.scenes.my_scene import my_scene_skills`.
- The import triggers `@skill` registration with the global `SKILL_REGISTRY`.
- Skills access the running scene via `get_active_scene("my_scene")`.
- The global `COOLDOWN_TRACKER` enforces per-skill cooldowns with thread safety.

### Governance

The `AgentGovernor` manages budgets, cooldowns, and prerequisites for all skills. See [SKILLS.md](./SKILLS.md) for the full skill reference, including the runtime registry, MCP-facing metadata, and the complete list of 38 skill packs.

---

## 7. Writing Interceptors

Interceptors modify prompts before inference (pre-call) or process responses after (post-call). They form the agent pipeline that all LLM calls pass through.

### Quick Example

```python
from engine.mcp.comms_framework import InterceptorBase

class MyInterceptor(InterceptorBase):
    priority = 20    # Lower runs first

    def pre_call(self, context):
        """Modify the prompt before it reaches the LLM."""
        context["messages"].append({"role": "system", "content": "extra context"})
        return context

    def post_call(self, context, response):
        """Process the LLM response after generation."""
        # Parse mood tags, update state, etc.
        return response
```

### Priority Order

| Priority | Interceptor | Purpose |
|----------|-------------|---------|
| 4 | NexusPrompt | Context hydration from Nexus |
| 5 | NaturalMoodDrift | Neurochemistry tagging |
| 8--16 | Identity & scene | Identity injection, scene-specific context |
| 92--93 | Post-call sync | Mood parsing, relationship events |

Register interceptors in `config/default.yaml` under `comms.interceptors`.

For the full interceptor reference (26 hooks, auto-registry, scene filtering), see [INTERCEPTORS.md](./INTERCEPTORS.md).

---

## 8. Testing Conventions

### Smart Test Runner (Preferred)

```bash
python scripts/smart_test.py                      # Tests for uncommitted changes
python scripts/smart_test.py --smoke              # ~15 files, one per domain (~30s)
python scripts/smart_test.py --domain scene_hub   # All tests for a domain
python scripts/smart_test.py --since HEAD~3       # Tests for last 3 commits
python scripts/smart_test.py --list               # Show what would run (dry-run)
```

### Pytest with Smart Flags

```bash
python -m pytest tests/ --affected                # Only tests for uncommitted changes
python -m pytest tests/ --staged                  # Only tests for staged files
python -m pytest tests/ --smoke-only              # ~15 smoke files
python -m pytest tests/ --since HEAD~1            # Since last commit
python -m pytest tests/ --affected --cap 40       # Fall back to smoke if >40 files
```

### Test Requirements

- Every new module needs tests. No exceptions -- skills, interceptors, tools, scenes.
- Mock all external services (LMStudio, ComfyUI, TTS, Nexus). Never call live services.
- Mock at the client boundary, not deep internals.
- Use `tmp_path` fixture for temp databases.
- Use `conftest.py` fixtures: `temp_db`, `event_chain`, `mock_config`.
- Test the happy path + at least one error case.
- DB tests should test create -> read -> update -> delete.
- The five seeded characters (lola, viktor, aria, frankie, mira) are always present.
- Ignore `tests/test_agent_loop.py` and `tests/live_wire_test.py` (require live services).

### Key Fixtures (from `tests/conftest.py`)

| Fixture | Provides |
|---------|----------|
| `temp_db(tmp_path)` | Temporary SQLite Database instance |
| `event_chain(temp_db)` | EventChain with temp DB backing |
| `mock_config()` | MagicMock dict-like with `.get(key, default)` |

### Writing a Scene Test

```python
import pytest
from unittest.mock import MagicMock, patch

def test_scene_metadata(mock_config):
    """SCENE_METADATA contains required keys."""
    from content.scenes.my_scene import MyScene
    meta = MyScene.SCENE_METADATA
    assert meta["name"] == "my_scene"
    assert "port" in meta
    assert "type" in meta

def test_my_skill_returns_result(mock_config):
    """Skill returns expected output when scene is active."""
    with patch("engine.scenes.base_scene.get_active_scene") as mock_scene:
        mock_scene.return_value = MagicMock()
        from content.scenes.my_scene.my_scene_skills import my_skill
        result = my_skill("test_target")
        assert "test_target" in result
```

### Browser Testing

After ANY JS/CSS/HTML change, run `python scripts/browser_test.py` (Playwright). Never commit UI changes without a passing browser test. The telemetry system (`cosysim-telemetry.js`) captures all browser clicks, errors, and hotkeys via `POST /api/telemetry` to `data/structured_logs.jsonl`.

For the full testing reference (markers, parallel execution, coverage), see [TESTING.md](./TESTING.md).

---

## 9. Version Stamps & Comments

Every file you create or significantly modify must follow these rules. These are mandatory -- no exceptions.

### Module Headers

Python files get a docstring header at the top:

```python
"""
Module Title
============

Brief description of what this module does.

Version: v1.50.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.50.0 [2026-03-22] -- What changed in this version
    v1.49.0 [2026-03-21] -- Previous significant change
"""
```

JS files use `/** ... */` JSDoc style. CSS/HTML use `/* ... */` or `<!-- ... -->`.

### Section Dividers

Organize code into logical sections with divider comments:

```python
# ---- Section Name -------------------------------------------------------
```

### Version Stamps

Tag significant code blocks with version stamps for traceability:

```python
# v1.50.0 [2026-03-22] -- Added oracle scene support
def _register_oracle():
```

### Versioning Scheme

- Format: `vMAJOR.MINOR.PATCH [YYYY-MM-DD]`
- MAJOR: Breaking architecture changes (pillars, engine rewrites)
- MINOR: Feature sprints (each numbered session = +1 minor)
- PATCH: Within-session refinements
- Current: **v1.50** (Three Pillars -- System/Game/Creation)

### Navigational Comments

Tag code blocks with what they connect to, who calls them, and what they emit:

```python
# CONNECTS: PlayerState, EconomyManager, MissionSystem
# CALLED BY: district_chat handler, NPC interaction flow
# EMITS: hud_update Socket.IO event
```

### Rules Summary

- **Every edit** gets a version stamp: `# v1.50.0 [2026-03-22] -- description`
- **Every new/modified file** gets a module header with Change Log
- **Always add/update the Change Log** when modifying a file
- **Use section dividers** to organize files with 50+ lines
- **Add navigational comments** on functions that connect systems
- **Add inline comments** for non-obvious logic -- explain WHY, not WHAT
- **Never remove existing version stamps** -- they are historical record
- **JS/CSS** use `/** ... */` or `/* ... */` with the same version stamp rules

---

## 10. Cross-References

| Doc | Relevance |
|-----|-----------|
| [Architecture](./ARCHITECTURE.md) | System design, layers, data flow, singletons |
| [MCP Framework](./MCP_FRAMEWORK.md) | Skill dispatch, governance, state coordination, dialog system |
| [Skills](./SKILLS.md) | Full skill reference -- 38 packs, runtime registry, MCP metadata |
| [Interceptors](./INTERCEPTORS.md) | 26 pre/post-call hooks, priorities, auto-registry, scene filtering |
| [Testing](./TESTING.md) | Smart test system, markers, parallel execution, coverage |
| [Configuration](./CONFIGURATION.md) | YAML config hierarchy, `get_config()` pattern, environment overrides |
| [Character System](./CHARACTER_SYSTEM.md) | Profiles, personality, stats, relationships, speech patterns |
| [Scenes](./SCENES.md) | Scene listing, mechanics, APIs, routes |
| [Operations](./OPERATIONS.md) | Launching, ports, monitoring, logging, scheduling, admin panels |
| [Neon HUD](./NEON_HUD.md) | Universal HUD v2, glass panels, phone overlay, announcer |
| [Economy Guide](./ECONOMY_GUIDE.md) | EconomyManager, cross-scene credits, betting |
| [Nexus](./NEXUS.md) | Knowledge storage, query router, training flywheel |

---

## 11. Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Merged CONTENT_GUIDE.md into CONTRIBUTING.md; added character creation, neurochemistry, ContentGate, version stamp rules; updated cross-references |
| v1.49 | 2026-03-21 | Added creation kit components, browser testing section |
| v1.42 | 2026-03-21 | Three-pillar architecture, updated scene registration checklist |
| v1.04b | 2025-12-15 | Original content guide with scene development, templates, asset pipeline |
