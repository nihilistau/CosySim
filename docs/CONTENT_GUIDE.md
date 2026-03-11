# CosySim Content Guide

> v1.04b — CosySim Documentation

A comprehensive guide to creating scenes, characters, skills, templates, and
narrative content for NeonCity. Whether you're building a new game scene or
adding characters to an existing one, this is your starting point.

---

## Quick Start

```powershell
# 1. Create a scene directory
mkdir content\scenes\my_scene
mkdir content\scenes\my_scene\templates
mkdir content\scenes\my_scene\static

# 2. Copy the template from an existing scene
copy content\scenes\arena\__init__.py content\scenes\my_scene\__init__.py
copy content\scenes\arena\arena_skills.py content\scenes\my_scene\my_scene_skills.py

# 3. Edit SCENE_METADATA, rename the class, register routes
# 4. Add the scene to config/default.yaml
# 5. Run: python launcher.py --scene my_scene
```

---

## 1. Scene Development

Every scene lives in `content/scenes/{name}/` and follows a standard layout.

### Directory Structure

```
content/scenes/my_scene/
├── __init__.py              # Scene class (BaseScene subclass)
├── my_scene_skills.py       # @skill-decorated MCP functions
├── templates/
│   └── my_scene.html        # Jinja2 template (extends neon_base.html)
└── static/
    ├── my_scene.css          # Scene-specific styles
    ├── my_scene.js           # Scene-specific JavaScript
    └── img/                  # Scene images
```

### BaseScene Subclass

Every scene inherits from `BaseScene` (`engine/scenes/base_scene.py`) and
optionally mixes in `MCPSceneMixin` for MCP framework registration.

```python
from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.shared import register_shared_assets
from content.scenes.my_scene import my_scene_skills  # noqa: F401

class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
    SCENE_METADATA = {
        "name": "my_scene",
        "display_name": "MY SCENE",
        "port": 5570,
        "type": "game",           # "game" | "utility" | "service"
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

### MCP Integration in `start()`

Register the scene with the MCP framework so state is accessible system-wide:

```python
fw = get_framework()
scene_node = fw.get_or_create("scenes.my_scene", MCPSceneNode)
scene_node.set("status", "running")
scene_node.set("port", self.SCENE_METADATA["port"])
```

### Active Scene Registry

Skills look up running scenes via `get_active_scene()`:

```python
from engine.scenes.base_scene import get_active_scene
scene = get_active_scene("my_scene")   # returns MyScene or None
```

---

## 2. Character Creation

Characters are managed by the asset system (`engine/assets/`) and enriched with
neurochemistry, relationships, and reputation.

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

Emotions are *computed* from neurotransmitter combinations — no hardcoded moods:
- High dopamine + low cortisol → **Confident**
- High cortisol + high adrenaline → **Panicked**
- High oxytocin + high serotonin → **Loved**

```python
from engine.characters.neurochemistry import get_neurochemistry_manager

mgr = get_neurochemistry_manager()
state = mgr.get_or_create("lola")
mgr.apply_stimulus("lola", "received_compliment")     # boosts dopamine + oxytocin
prompt_ctx = mgr.get_prompt_context("lola")            # inject into LLM prompt
```

### Seeded Characters

Five characters are always present in the database: **Lola**, **Viktor**,
**Aria**, **Frankie**, and **Mira**. Tests can rely on these existing.

### Reputation System

See `engine/characters/reputation.py` — tracks per-faction reputation (-100 to +100)
with threshold-based relationship labels.

---

## 3. Skill Packs

Skills are MCP-callable functions registered via the `@skill` decorator.

### The `@skill` Decorator

Defined in `engine/skills/skill.py`:

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

- Skill files: `content/scenes/{name}/{name}_skills.py`
- Import in scene `__init__.py`: `from content.scenes.my_scene import my_scene_skills`
- The import triggers `@skill` registration with the global `SKILL_REGISTRY`
- Skills access the running scene via `get_active_scene("my_scene")`

### Cooldown Tracking

The global `COOLDOWN_TRACKER` enforces per-skill cooldowns with thread safety.
Skills with `cooldown > 0` cannot fire again until the cooldown expires.

---

## 4. Templates & Frontend

### Base Template Inheritance

All scene templates extend `neon_base.html`:

```html
{% extends "neon_base.html" %}

{% block title %}MY SCENE{% endblock %}

{% block scene_content %}
  <div class="scene-panel">
    <!-- Your scene content -->
  </div>
{% endblock %}

{% block extra_js %}
  <script src="{{ url_for('static', filename='my_scene.js') }}"></script>
{% endblock %}
```

### Required Context Variables

Templates receive these from the Flask route:

| Variable | Type | Description |
|----------|------|-------------|
| `scene_data` | dict | Scene-specific state |
| `scene_name` | str | Scene identifier |
| `accent_color` | str | CSS accent (e.g. `"#dc2626"`) |
| `port` | int | Scene port number |

### Navbar Include

**Never** manually load navbar CSS/JS — the include is self-contained:

```html
{% include 'navbar_v2.html' %}
```

Similarly for the Aria AI widget:

```html
{% include 'aria_widget.html' %}
```

### Socket.IO Integration

```javascript
const socket = io();

socket.on('connect', () => console.log('Connected'));
socket.on('state_update', (data) => updateUI(data));
socket.emit('action', { type: 'interact', data: { target: 'npc' } });
```

### CSS Conventions

- Use CSS custom properties: `--primary-color`, `--bg-color`, `--accent`
- Class naming: kebab-case (`game-panel`, `chat-message`)
- Scene accent injection: `style="--accent: {{ accent_color }}"`
- Prefer flexbox/grid; mobile-responsive with media queries

### Shared Assets

Every scene **must** call `register_shared_assets(self.app)` in `start()`.
This mounts the `/shared/*` route for navbar, base CSS, and Aria widget assets.

---

## 5. Narrative Content

### ContentEngine

Dynamic content pools for dialog, scenarios, and ambient text:

```python
from engine.content.content_engine import get_content_engine

engine = get_content_engine()
item = engine.get("penthouse", "scenario")       # random from pool
engine.add("penthouse", "scenario", "Neon light flickers across the bar...")
```

### ContentGate

Enforces content intensity per player profile:

```python
from engine.content.content_gate import get_content_gate

gate = get_content_gate()
gate.set_profile("player1", sexual=2, violence=1, language=3)
allowed = gate.check("player1", "sexual", 3)   # False — above limit
```

| Level | Label | Description |
|-------|-------|-------------|
| 0 | Clean | No adult content |
| 1 | Mild | Suggestive, mild language |
| 2 | Mature | Explicit suggestion, moderate violence |
| 3 | Explicit | Full explicit content |

### NLM Content Seeding

Generate content pools via the TeacherPipeline:

```bash
python -m engine.content.seed_all                    # all scenes
```

```python
from engine.nexus.teacher_pipeline import TeacherPipeline
tp = TeacherPipeline()
tp.generate_content("penthouse", content_type="scenarios", count=20)
```

---

## 6. Asset Pipeline

### Static Files

Static assets served from each scene's `static/` directory:

```python
url_for('static', filename='my_scene.css')
url_for('static', filename='img/background.png')
```

### ComfyUI Integration

Image generation via ComfyUI (when running):

```python
from engine.media.comfyui_client import generate_image
result = generate_image(prompt="cyberpunk street at night", width=512, height=512)
```

### TTS

Voice synthesis for character dialog — see [TTS.md](TTS.md).

---

## 7. Configuration

All settings live in `config/default.yaml` with dot-notation access:

```python
from engine.config import get_config
cfg = get_config()

port = cfg.get("scenes.my_scene.port", 5570)
model = cfg.get("lmstudio.models.primary", "default-model")
accent = cfg.get("scenes.my_scene.accent_color", "#8b5cf6")
```

### Adding Scene Config

```yaml
# config/default.yaml
scenes:
  my_scene:
    port: 5570
    host: localhost
    accent_color: "#8b5cf6"
    max_players: 10
    custom_setting: true
```

**Rules:** Never hardcode ports, paths, or model names. Always provide
defaults in `get()` calls. See [CONFIGURATION.md](CONFIGURATION.md).

---

## 8. Testing New Content

### Running Tests

```powershell
# Full suite
python -m pytest tests/ -v --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py

# Single file
python -m pytest tests/test_my_scene.py -v
```

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

### Mocking Rules

- **Never** make real HTTP calls to LMStudio, ComfyUI, or TTS
- Mock at the client boundary, not deep internals
- Use `tmp_path` for any file I/O tests
- The five seeded characters (lola, viktor, aria, frankie, mira) are always present

---

## Cross-References

- [ARCHITECTURE.md](ARCHITECTURE.md) — System overview
- [SCENES.md](SCENES.md) — Scene listing and ports
- [SKILLS.md](SKILLS.md) — Full skill reference
- [CHARACTER_SYSTEM.md](CHARACTER_SYSTEM.md) — Character deep dive
- [MCP_FRAMEWORK.md](MCP_FRAMEWORK.md) — MCP tree and state management
- [CONFIGURATION.md](CONFIGURATION.md) — YAML config reference
- [TESTING.md](TESTING.md) — Testing conventions
- [ECONOMY_GUIDE.md](ECONOMY_GUIDE.md) — Economy system
- [ARENA_GUIDE.md](ARENA_GUIDE.md) — Arena / Colosseum
