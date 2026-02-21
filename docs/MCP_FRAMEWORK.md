# CosySim MCP Framework — Developer Guide

> **Version 2.0** — Unified architecture for multi-agent AI simulation

---

## Overview

CosySim is a multi-agent simulation framework built on the **Model Context Protocol (MCP)** pattern. Every scene, character, skill, timer, and cross-scene message flows through a single root object — `MCPFramework` — which acts as the central nervous system.

### Architecture Layers

```
┌──────────────────────────────────────────────────────────┐
│  config/                YAML configuration               │
│  ├── default.yaml       All settings: scenes, agents,    │
│  │                      LMStudio, framework params       │
│  └── skill_manifests    Per-scene skill rosters          │
├──────────────────────────────────────────────────────────┤
│  engine/                Reusable technology               │
│  ├── mcp/               MCPFramework, SceneMixin, skills │
│  ├── skills/            @skill decorator, registry       │
│  ├── lmstudio/          ModelManager, VRAM management    │
│  ├── agents/            CharacterAgent, LLM wrappers     │
│  ├── tts/               Text-to-speech server            │
│  └── services/          Housekeeping, media ingest       │
├──────────────────────────────────────────────────────────┤
│  content/               Game content                     │
│  ├── scenes/            Phone, Bedroom, Lounge, Casino   │
│  ├── characters/        Character definitions            │
│  └── simulation/        Shared game logic                │
└──────────────────────────────────────────────────────────┘
```

---

## Quick Start

```python
from engine.mcp.framework import get_framework

fw = get_framework()

# Register a scene
scene = fw.get_scene("my_scene")

# Register a character
char = fw.get_character("alice")
char.enter_scene("my_scene")

# Emit events
fw.emit_event("player_joined", {"name": "alice"}, source="my_scene")

# Start a timer
fw.start_timer("round_clock", 120, on_complete_note="Round over!")

# Tick the simulation
fired = fw.tick("my_scene")
```

---

## MCPFramework (Singleton)

The root singleton manages all scenes, characters, timers, consequences, and the event bus.

```python
from engine.mcp.framework import get_framework
fw = get_framework()
```

### Scene & Character Registry

| Method | Returns | Description |
|--------|---------|-------------|
| `get_scene(scene_id)` | `MCPSceneNode` | Get or create a scene |
| `register_scene(scene_id)` | `MCPSceneNode` | Explicitly register a scene (fires `scene_registered`) |
| `list_scenes()` | `List[str]` | All registered scene IDs |
| `get_character(character_id)` | `MCPCharacterNode` | Get or create a character |
| `list_characters()` | `List[str]` | All registered character IDs |
| `get_characters_in_scene(scene_id)` | `List[str]` | Characters currently in a scene |

### Cross-Scene Communication

Characters can send messages to characters in other scenes:

```python
fw.cross_scene_send(
    from_char="alice", from_scene="phone",
    to_char="bob", to_scene="bedroom",
    message="Come to the lounge!", message_type="text"
)

# Receiver reads inbox
messages = fw.get_cross_scene_inbox("bob")
```

### Timers

Passive, turn-driven countdown timers:

```python
timer = fw.start_timer("bomb_clock", 60, on_complete_note="💥 BOOM!")
status = fw.check_timer("bomb_clock")  # .completed, .remaining, .progress
fw.cancel_timer("bomb_clock")
fw.list_timers()
```

### Scheduled Consequences

Deferred effects that fire after N turns:

```python
fw.schedule_consequence(
    scene_id="casino", character_id="mira",
    consequence_type="mood_shift",
    params={"mood": "suspicious", "intensity": 0.8},
    trigger_after_turns=3,
    description="Mira gets suspicious after losing 3 hands"
)

# Tick processes consequences
fired = fw.tick("casino")  # Returns list of fired consequences
```

### Random Pick

Weighted random selection:

```python
result = fw.random_pick(
    n=3, options=["win", "lose", "draw"],
    weights=[0.3, 0.5, 0.2]
)
# result = {"picked": [...], "seed": 42}
```

### Event Bus

Decoupled communication between any components:

```python
# Subscribe
def on_mood_change(event):
    print(f"{event.source} mood changed: {event.payload}")

fw.on("mood_change", on_mood_change)

# Emit
fw.emit_event("mood_change", {"mood": "happy"}, source="bedroom")

# Unsubscribe
fw.off("mood_change", on_mood_change)

# Review history
log = fw.get_event_log(event_type="mood_change", limit=10)
```

**Built-in lifecycle events** (fired automatically):
- `framework_ready` — after `mark_ready()` is called
- `scene_registered` — when a new scene is registered
- `character_registered` — when a new character is created
- `scene_tick` — on every `tick()` call
- `state_saved` / `state_loaded` — on state persistence operations

### Lifecycle Hooks

```python
fw.add_lifecycle_hook("framework_ready", lambda: print("Ready!"))
fw.mark_ready()  # Fires all framework_ready hooks
```

### Agent Profiles

Pre-configured LLM settings per agent role:

```python
profile = fw.get_agent_profile("big")
# AgentProfile(role="big", model="qwen3-30b-a3b", context_length=16384, ...)

fw.set_agent_profile(AgentProfile(
    role="custom_role", model="my-model",
    context_length=8192, max_tokens=2048,
    temperature=0.8, top_p=0.95,
    description="Custom agent"
))

all_profiles = fw.list_agent_profiles()
```

**Built-in profiles** (configured in `config/default.yaml`):

| Role | Model | Context | Max Tokens | Temperature |
|------|-------|---------|------------|-------------|
| `big` | qwen3-30b-a3b | 16384 | 4096 | 0.85 |
| `small` | qwen3-8b | 4096 | 1024 | 0.7 |
| `router` | qwen3-8b | 2048 | 256 | 0.3 |
| `narrator` | qwen3-30b-a3b | 8192 | 2048 | 0.9 |
| `game_master` | qwen3-30b-a3b | 12288 | 3072 | 0.75 |

### State Persistence

Save/restore framework state across restarts:

```python
fw.save_state()  # Saves to data/mcp_framework_state.json
fw.load_state()  # Restores from file

# Custom path
fw.save_state("backups/state_v1.json")
```

Persisted data: turn counter, scene membership, timers, consequences, cross-scene messages.

### Status

```python
status = fw.get_status()
# {
#   "scenes": [...], "characters": [...],
#   "turn": 42, "timers_active": 2,
#   "consequences_pending": 1, "ready": True
# }
```

---

## Skills System

### The @skill Decorator

Every tool available to agents is registered as a skill:

```python
from engine.skills.skill import skill, SkillCategory

@skill(
    name="serve_drink",
    pack="casino",
    description="Serve a cocktail to a player",
    tags=["casino", "social"],
    category=SkillCategory.SOCIAL,
    cooldown=5.0,          # Seconds between uses
    prerequisites=["get_scene_snapshot"],  # Must exist in registry
    cost=1.0               # Relative cost weight
)
def serve_drink(drink_id: str, target: str = "player") -> str:
    """Serve a drink at the casino bar."""
    return f"Served {drink_id} to {target}"
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | Skill identifier |
| `pack` | str | `"default"` | Group name for related skills |
| `description` | str | `""` | LLM-facing description |
| `tags` | list | `[]` | Searchable tags |
| `category` | str | `""` | One of `SkillCategory.*` constants |
| `cooldown` | float | `0.0` | Minimum seconds between invocations |
| `prerequisites` | list | `[]` | Required skill names that must exist |
| `cost` | float | `1.0` | Relative compute/resource cost |

### Skill Categories

```python
from engine.skills.skill import SkillCategory

SkillCategory.COMMUNICATION  # "communication"
SkillCategory.MEMORY         # "memory"
SkillCategory.MEDIA          # "media"
SkillCategory.GAME           # "game"
SkillCategory.SOCIAL         # "social"
SkillCategory.ENVIRONMENT    # "environment"
SkillCategory.SYSTEM         # "system"
SkillCategory.NARRATIVE      # "narrative"
```

### Cooldown Tracking

```python
from engine.skills.skill import COOLDOWN_TRACKER

can_use = COOLDOWN_TRACKER.can_use("serve_drink", cooldown_secs=5.0)
remaining = COOLDOWN_TRACKER.get_remaining("serve_drink", cooldown_secs=5.0)
COOLDOWN_TRACKER.mark_used("serve_drink")
COOLDOWN_TRACKER.reset("serve_drink")  # Reset one
COOLDOWN_TRACKER.reset()               # Reset all
```

### Skill Registry

```python
from engine.skills.registry import SKILL_REGISTRY

# Get all skills in a pack
tools = SKILL_REGISTRY.get_pack_tools("casino")
metas = SKILL_REGISTRY.get_pack_metas("casino")

# Search by category
social_skills = SKILL_REGISTRY.get_by_category("social")

# Get available skills (respects cooldowns)
available = SKILL_REGISTRY.get_available(tags=["casino"], category="social")

# Execute a skill directly (with cooldown enforcement)
result = SKILL_REGISTRY.execute_skill("serve_drink", drink_id="martini")

# Get a single skill's metadata
meta = SKILL_REGISTRY.get_skill("serve_drink")

# List all packs
packs = SKILL_REGISTRY.all_packs()  # ["character", "casino", "social", ...]

# Full manifest for MCP protocol
manifest = SKILL_REGISTRY.mcp_manifest()
```

### Built-in Skill Packs

| Pack | Skills | Description |
|------|--------|-------------|
| `character` | speak_as, speech_enhance, character_get_summary | Character voice and identity |
| `memory` | memory_recall, store_memory | Long-term memory |
| `environment` | set_scene_atmosphere, environment_change | Scene atmosphere |
| `narrative` | inject_story_beat, get_dialog_options, set_response_directive | Story direction |
| `social` | mood_contagion, relationship_adjust, scene_broadcast, get_scene_snapshot | Social dynamics |
| `tts` | generate_voice_message | Text-to-speech |
| `voice` | generate_voice_message | Voice synthesis |
| `comfyui` | generate_image | Image generation |

---

## MCPSceneMixin

The mixin wires any Flask-based scene into the MCP framework:

```python
from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin

class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
    def __init__(self):
        super().__init__(
            scene_id="my_scene",
            template_folder="templates",
            static_folder="static"
        )
        # ... setup ...
        self._mcp_init()  # MUST call at end of __init__

    def start(self):
        # Register characters
        self.mcp_on_enter("alice")
        self.mcp_on_enter("bob")
        super().start()

    def stop(self):
        get_framework().save_state()
        super().stop()
```

**Key properties/methods:**
- `self.mcp` — returns the `MCPSceneNode` for this scene
- `self._mcp_init()` — registers scene and loads rules from config
- `self.mcp_on_enter(char_id)` — registers character entry
- `self.mcp_on_leave(char_id)` — registers character departure

---

## LMStudio Integration

### ModelManager

Controls which LLM models are loaded in LMStudio:

```python
from engine.lmstudio.model_manager import get_model_manager

mm = get_model_manager()
```

### Load Modes

| Mode | Behavior |
|------|----------|
| `CONCURRENT` | One model loaded, N parallel request slots |
| `JIT` | Load on demand, evict previous model |
| `JIT_TTL` | Load on demand, auto-unload after idle timeout |

```python
from engine.lmstudio.model_manager import LoadMode

mm.set_mode(LoadMode.JIT_TTL, ttl_seconds=300)
```

### Agent-Aware Loading

```python
# Load the right model for an agent role
model_key = mm.ensure_for_agent("big")       # Loads qwen3-30b-a3b
model_key = mm.ensure_for_agent("small")     # Loads qwen3-8b
model_key = mm.ensure_for_agent("narrator")  # Loads qwen3-30b-a3b

# Get config without loading
config = mm.get_agent_config("game_master")
# {"model": "qwen3-30b-a3b", "context_length": 12288, ...}
```

### Runtime Config

```python
# Get full config (for admin panels)
full = mm.get_full_config()

# Update at runtime
mm.update_config(
    mode="jit_ttl",
    ttl_seconds=600,
    context_length=8192
)
```

### Status

```python
status = mm.status()
# {
#   "mode": "jit_ttl", "loaded": [...],
#   "vram_total_mb": 11500, "vram_used_mb": 8200, ...
# }
```

---

## Configuration

All settings live in `config/default.yaml`. Access via:

```python
from engine.config import get_config
config = get_config()

port = config.get("scenes.phone.port", 5555)
model = config.get("agent_profiles.big.model", "qwen3-30b-a3b")
```

### Key Config Sections

```yaml
# Agent profiles for different LLM roles
agent_profiles:
  big:
    model: "qwen3-30b-a3b"
    context_length: 16384
    max_tokens: 4096
    temperature: 0.85

# Framework behavior
framework:
  state_persistence: true
  state_file: "data/mcp_framework_state.json"
  max_event_log: 500
  max_consequence_age_turns: 50

# LMStudio connection
lmstudio:
  host: "http://localhost:1234"
  load_mode: "concurrent"
  vram_cap_mb: 11500

# Scene ports
scenes:
  phone:
    port: 5555
  bedroom:
    port: 5556
  lounge:
    port: 5557
  casino:
    port: 5559
```

Environment variables override config values:
- `COSYSIM_LMSTUDIO_HOST` → `lmstudio.host`
- `COSYSIM_<SECTION>_<KEY>` → `section.key`

### Skill Manifests

`config/skill_manifests.yaml` maps scenes to their available skills with trigger types:

```yaml
scenes:
  casino:
    - name: get_scene_snapshot
      trigger: auto          # Always runs before LLM call
      description: "Read full casino state"
      when: always
    - name: mood_contagion
      trigger: optional      # LLM may choose to use
      description: "Spread emotion to other players"
      when: always
```

**Trigger types:**
- `auto` — executed before every LLM call; result injected into context
- `optional` — advertised to the LLM, which may call it
- `required` — LLM must call this tool before replying

---

## Scene Development Guide

### Creating a New Scene

1. **Create directory structure:**
```
content/scenes/my_scene/
├── __init__.py
├── my_scene.py          # Scene class
├── my_scene_mcp.py      # Scene-specific MCP rules & data
├── templates/
│   └── my_scene.html    # Jinja2 template
└── static/
    ├── css/
    └── js/
```

2. **Define MCP rules** in `my_scene_mcp.py`:
```python
SCENE_ID = "my_scene"
CHARACTER_IDS = ["npc_1", "npc_2"]

def register_mcp_rules(mcp_scene):
    mcp_scene.register_rule("greeting", {
        "description": "NPCs greet the player on entry",
        "trigger": "on_enter",
        "effect": {"mood": "welcoming"}
    })
```

3. **Create the scene class:**
```python
class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
    def __init__(self):
        super().__init__(scene_id="my_scene", ...)
        # Setup characters, routes, socket handlers
        self._mcp_init()

    def start(self):
        fw = get_framework()
        for char_id in CHARACTER_IDS:
            self.mcp_on_enter(char_id)
        # Subscribe to events
        fw.on("story_beat", self._on_story_beat)
        super().start()

    def stop(self):
        get_framework().save_state()
        super().stop()
```

4. **Add to config:**
```yaml
# config/default.yaml
scenes:
  my_scene:
    port: 5560
    characters: ["npc_1", "npc_2"]
```

5. **Add to launcher:**
```python
# launcher.py
elif args.mode == "my_scene":
    from content.scenes.my_scene.my_scene import MyScene
    MyScene().start()
```

6. **Add skill manifest** in `config/skill_manifests.yaml`

---

## Existing Scenes

| Scene | Port | Characters | Description |
|-------|------|------------|-------------|
| **Phone** | 5555 | Companion | Text/call companion, media sharing |
| **Bedroom** | 5556 | Multiple | Multi-agent intimate roleplay |
| **Lounge** | 5557 | Lola, Viktor | 1920s jazz speakeasy |
| **Casino** | 5559 | Frankie, Mira | Noir poker night (showcase scene) |
| **Hub** | 8500 | System | Central hub & dashboard |
| **Admin** | 8502 | — | System administration |

---

## Launcher

```bash
python launcher.py --mode phone      # Start phone scene
python launcher.py --mode casino     # Start casino scene
python launcher.py --mode all        # Start all services
python launcher.py --mode test       # Run tests
python launcher.py --status          # Show system status
python launcher.py --housekeep       # Run maintenance
```

---

## Testing

```bash
python -m pytest tests/ -v --tb=short
```

Tests cover:
- Config dot-notation access and env overrides
- Skill decorator and pack registration
- Chain context thread-local management
- Event chain tree structure and querying
- Framework singleton behavior

---

## Hardware Requirements

- **Target GPU:** RTX 2060 12GB (VRAM cap: 11,500 MB)
- **LMStudio** manages model loading with VRAM guard
- Agent profiles sized to fit within VRAM budget
- JIT/JIT_TTL modes enable model swapping when memory is constrained
