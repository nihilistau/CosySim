# Skills

> CosySim Documentation — v1.52.0 [2026-03-26]
>
> The @skill decorator, pack system, registry, and governance filtering.

---

## Overview

Skills are plain Python functions that LLM agents invoke as **tools** during inference. The `@skill` decorator registers a function into the global `SKILL_REGISTRY` at import time, making it discoverable by the MCP pipeline, the AgentGovernor, and LMStudio's tool-calling API.

CosySim has approximately **~1,040 skills across 99 packs**:

| Source | Location | Skills | Files |
|--------|----------|--------|-------|
| Engine packs | `engine/skills/builtin/` | ~785 | 83 |
| Scene packs | `content/scenes/` | ~223 | per-scene |

Skills are organized into **8 categories** (COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM, NARRATIVE) and governed by the AgentGovernor, which filters the full registry down to **~50-80 contextual skills per call** based on the active scene, pack membership, cooldown state, and prerequisite chains.

```
@skill decorator               engine/skills/skill.py
  └─► SKILL_REGISTRY           engine/skills/registry.py
        ├─ _by_name: dict       name → SkillMeta (flat, deduplication)
        └─ _skills: dict        pack → [SkillMeta, …] (nested)

AgentGovernor                  engine/mcp/comms_framework.py
  └─► SkillManifest            scene-specific skill selection
        └─► ResponseContext    pre/post interceptor pipeline
              └─► LMStudio     /api/v1/chat → tool_call → skill → result
```

Cross-references: [MCP Framework](MCP_FRAMEWORK.md) | [Interceptors](INTERCEPTORS.md) | [Contributing](CONTRIBUTING.md)

---

## The @skill Decorator

The decorator lives in `engine/skills/skill.py`. It supports two forms — bare (no arguments) and configured:

### Bare Form

```python
from engine.skills import skill

@skill
def greet_user(name: str) -> str:
    """Say hello to a user by name."""
    return f"Hello, {name}!"
```

The function is registered with `pack="default"`, the description is taken from the docstring's first line, and the name is taken from `func.__name__`.

### Configured Form

```python
from engine.skills import skill, SkillCategory

@skill(
    pack="scene_name",
    description="LLM-facing description",
    category="GAME",       # or SkillCategory.GAME
    cooldown=5.0,
    cost=1.0,
    tags=["tag"],
    prerequisites=["other_skill"],
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

### Decorator Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `func.__name__` | Registry key. Must be unique across all packs. |
| `pack` | `str` | `"default"` | Pack name for grouping and filtering. |
| `description` | `str` | docstring first line | Tool description surfaced to the LLM. |
| `tags` | `list[str]` | `[]` | Free-form tags for discovery and filtering. |
| `category` | `str` | `""` | One of the 8 SkillCategory constants. |
| `cooldown` | `float` | `0.0` | Minimum seconds between invocations. |
| `prerequisites` | `list[str]` | `[]` | Skill names that must be called first in the same session. |
| `cost` | `float` | `1.0` | Abstract cost for budget tracking (higher = more expensive). |
| `nexus_first` | `bool` | `False` | When True, wrap with Nexus-first lookup — cache hits bypass the function body. |
| `pillar` | `str` | `""` | Three-pillar assignment (system / game / creation). |

The decorator does **not** modify the function — it remains directly callable in tests. Registration happens as a side effect at import time.

---

## Categories

The `SkillCategory` class in `engine/skills/skill.py` defines the 8 category constants:

```python
class SkillCategory:
    COMMUNICATION = "communication"     # messaging, voice, cross-scene
    MEMORY        = "memory"            # search, store, recall
    MEDIA         = "media"             # images, voice, video generation
    GAME          = "game"              # game state, dice, scoring
    SOCIAL        = "social"            # mood, relationship, contagion
    ENVIRONMENT   = "environment"       # lighting, props, scene changes
    SYSTEM        = "system"            # config, status, admin
    NARRATIVE     = "narrative"         # story beats, dialog, narration
```

Categories are used for:

- **Governance filtering** — the AgentGovernor can restrict which categories an agent sees.
- **Registry queries** — `SKILL_REGISTRY.get_by_category("game")` returns all game skills.
- **Admin dashboards** — the MCP manifest groups skills by category for inspection.

---

## Pack System

A **pack** is a named collection of related skills. Packs come in two flavors:

### Engine Packs

Located in `engine/skills/builtin/`. These provide core capabilities available across all scenes. Each `.py` file registers its skills under one or more pack names at import time.

Examples: `memory`, `character`, `comfyui`, `voice`, `tts`, `social`, `nexus`, `nlm_forge`, `debugger`, `training`, `notebooklm`, `coding`, `boards`, `autonomy`, `workspace`.

### Scene Packs

Located in `content/scenes/{name}/{name}_skills.py`. These provide scene-specific game mechanics and are loaded when the scene starts. The pack name matches the scene name.

Examples: `realm`, `penthouse`, `neoncity`, `phone`, `casino`, `heist`, `lounge`, `tavern`, `gallery`, `games`, `coders`, `command_center`.

### SkillPack Helper

The `SkillPack` dataclass provides a convenience wrapper:

```python
from engine.skills.skill import SkillPack

comfy = SkillPack("comfyui")
tools = comfy.tools          # list of callables for lmstudio.llm().act()
metas = comfy.skill_metas    # list of SkillMeta objects
```

### Top Packs by Size

| Pack | Skills | Type |
|------|--------|------|
| `autonomy` | 81 | engine |
| `workspace` | 49 | engine |
| `realm` | 28 | scene |
| `penthouse` | 24 | scene |

---

## Registry & Loading

### SKILL_REGISTRY

The global singleton `SKILL_REGISTRY` (class `SkillRegistry` in `engine/skills/registry.py`) is the single source of truth. It maintains two internal data structures:

- **`_by_name`** — a flat `dict[str, SkillMeta]` mapping skill name to metadata. If a skill name is registered twice, the later registration wins and a warning is logged.
- **`_skills`** — a nested `dict[str, list[SkillMeta]]` mapping pack name to a list of skill metadata entries.

Both structures are guarded by a `threading.Lock` for thread safety.

### Registration Flow

1. A module containing `@skill`-decorated functions is imported.
2. Each decorator call creates a `SkillMeta` and calls `SKILL_REGISTRY.register(meta)`.
3. The registry deduplicates by name (later wins) and appends to the pack list.
4. An `activity_type="skill_registered"` event is published to the `ActivityBus`.

### Naming Collisions

There are **5 known naming collisions** between engine and scene packs. When the same skill name appears in multiple packs, the last-imported module wins. The registry logs a warning for each collision.

### Querying the Registry

```python
from engine.skills.registry import SKILL_REGISTRY

# List all pack names
SKILL_REGISTRY.all_packs()                     # → ["autonomy", "memory", "realm", ...]

# Get callables for a pack (pass to lmstudio tools=[...])
tools = SKILL_REGISTRY.get_pack_tools("memory")

# Get metadata for a pack
metas = SKILL_REGISTRY.get_pack_metas("realm")
for m in metas:
    print(f"{m.name}: {m.description} (cooldown={m.cooldown_secs}s)")

# Filter by tags
image_tools = SKILL_REGISTRY.all_tools(tags=["image"])

# Filter by category
game_skills = SKILL_REGISTRY.get_by_category("game")

# Get skills that are off cooldown and match filters
available = SKILL_REGISTRY.get_available(tags=["combat"], category="game")

# Look up a single skill by name
meta = SKILL_REGISTRY.get_skill("search_memory")

# Execute with cooldown enforcement
result = SKILL_REGISTRY.execute_skill("search_memory", "coffee", character_id="abc123")

# Full manifest for admin panels
manifest = SKILL_REGISTRY.mcp_manifest()       # list of dicts with all fields

# Human-readable summary
print(SKILL_REGISTRY.describe())
```

### Module-Level Convenience API

```python
from engine.skills import get_skills, get_pack_tools, mcp_skill_pack

# Get callables with optional pack/tag filtering
tools = get_skills(pack="comfyui")
tools = get_skills(tags=["image"])

# Shorthand for pack tools
tools = get_pack_tools("memory")

# Build MCP integration payload for LMStudio
mcp = mcp_skill_pack("ws://127.0.0.1:3001", allowed_tools=[], name="cosysim-tools")
```

---

## Governance Filtering

The `AgentGovernor` (in `engine/mcp/comms_framework.py`) wraps a `CharacterAgent` with the full governance pipeline. On each `reply()` call, the governor determines which skills the agent can see and use.

### Pipeline Steps

1. **Load SkillManifest** — the scene-specific manifest defines which packs, categories, and individual skills are available for that scene.
2. **Build ResponseContext** — collects the scene name, agent identity, user message, skill manifest, and interaction policy.
3. **Execute AUTO skills** — skills flagged as auto-triggered run first, and their results are injected into the context.
4. **Run pre-call interceptors** — interceptors (priorities 4-16) modify the system prompt, inject rules, and shape the tool list.
5. **LLM call** — the agent calls LMStudio with the filtered tool list. LMStudio invokes skills via `tool_call` during SSE streaming.
6. **Run post-call interceptors** — interceptors (priorities 92-93) parse mood tags, fire relationship events, and validate the response.
7. **Post to ActivityBus** — the completed interaction is published for monitoring.

### What Agents Actually See

Out of ~1,000 registered skills, an agent sees **~50-80 per call**. The reduction comes from:

| Filter | Effect |
|--------|--------|
| **Scene manifest** | Only packs assigned to the active scene are included. |
| **Pack membership** | Engine packs are included selectively per scene config. |
| **Cooldowns** | Skills still on cooldown are excluded (`CooldownTracker`). |
| **Prerequisites** | Skills whose prerequisites have not been met are excluded. |
| **Budget** | Skills whose `cost` exceeds the remaining budget are excluded. |
| **Category** | The interaction policy can restrict visible categories. |
| **Tags** | Optional tag-based filtering narrows the list further. |

### CooldownTracker

The global `COOLDOWN_TRACKER` (in `engine/skills/skill.py`) enforces minimum intervals between skill invocations:

```python
from engine.skills.skill import COOLDOWN_TRACKER

COOLDOWN_TRACKER.can_use("generate_image", cooldown_secs=30.0)  # → bool
COOLDOWN_TRACKER.mark_used("generate_image")
COOLDOWN_TRACKER.get_remaining("generate_image", 30.0)          # → float seconds
COOLDOWN_TRACKER.reset("generate_image")                        # reset one skill
COOLDOWN_TRACKER.reset()                                        # reset all
```

---

## Writing a Skill

### Quick-Start

1. **Choose a location**: engine pack (`engine/skills/builtin/`) or scene pack (`content/scenes/{name}/`).
2. **Write the function**: type-annotate all parameters and the return type. Return a human-readable string.
3. **Add the decorator**: set `pack`, `description`, `category`, and any governance fields.
4. **Import the module**: ensure the module is imported at startup so the `@skill` decorators fire.

### Engine Pack Example

```python
# engine/skills/builtin/weather_skills.py

from engine.skills import skill, SkillCategory

@skill(
    pack="environment",
    description="Set the weather for the current scene.",
    category=SkillCategory.ENVIRONMENT,
    cooldown=10.0,
    cost=1.0,
    tags=["weather", "atmosphere"],
)
def set_weather(condition: str, intensity: float = 0.5) -> str:
    """Set weather to rain, snow, fog, or clear with intensity 0-1."""
    # implementation here
    return f"Weather set to {condition} at intensity {intensity}"
```

### Scene Pack Example

Scene skills access the running scene instance via `get_active_scene()`:

```python
# content/scenes/tavern/tavern_skills.py

from engine.skills import skill, SkillCategory
from engine.scenes.base_scene import get_active_scene

@skill(pack="tavern", tags=["game", "food"], category=SkillCategory.GAME)
def order_food(item: str, player_id: str) -> str:
    """Order a food item from the tavern menu."""
    scene = get_active_scene("tavern")
    if not scene or not hasattr(scene, "state"):
        return "Tavern not running"
    return scene.state.place_order(player_id, item)
```

**Registration**: Import the skills module in the scene's `__init__.py`:

```python
# content/scenes/tavern/__init__.py
from . import tavern_skills  # triggers @skill decorators
```

### Testing

Skills are plain functions — test them directly:

```python
from engine.skills.builtin.memory_skills import search_memory

result = search_memory("coffee", character_id="abc123", top_k=3)
assert "coffee" in result
```

### Best Practices

1. **Keep skills small and single-purpose** — the LLM picks tools by name + docstring.
2. **Return human-readable strings** — results are fed back to the LLM as `tool_result`.
3. **Type-annotate everything** — LMStudio infers the JSON schema from Python type hints.
4. **Use cooldown for expensive ops** — prevents rapid repeated image generation or API calls.
5. **Set cost for budget tracking** — higher cost skills are excluded sooner when budget runs low.
6. **Use prerequisites for ordered flows** — e.g., `gather_intel` must run before `execute_heist`.
7. **Use `nexus_first=True`** — for skills that can be served from Nexus cache, bypassing the function body on cache hits.

---

## Pack Inventory

### Engine Packs (engine/skills/builtin/) — Top 20 by Size

| Pack | Skills | Description |
|------|--------|-------------|
| `autonomy` | 81 | Autonomous agent behaviors, goal tracking, self-directed actions |
| `workspace` | 49 | Workspace management, file operations, project tools |
| `nexus` | 15 | Nexus KMS integration — search, store, research, converse |
| `debugger` | 14 | ARGUS CDP diagnostics — console, network, DOM, screenshots |
| `nlm_forge` | 10 | NLM chain — ask, batch, distill, decompose, analyze, solve |
| `notebooklm` | 5 | NotebookLM — ask, add source, generate audio, list, search |
| `coding` | 8 | Code snippets, decisions, research, bug tracking, sessions |
| `training` | 4 | Fine-tuning orchestration — trigger, status, export, list |
| `memory` | 4 | Memory search, store, event chain summary, summarize |
| `character` | 4 | Character state, trait adjustment, mood, relationships |
| `comfyui` | 3 | Image generation via ComfyUI — generate, portrait, list workflows |
| `tts` | 4 | Text-to-speech — generate voice, cast, list presets, voicemails |
| `voice` | 2 | Voice message generation and listing |
| `social` | varies | Social interaction mechanics |
| `boards` | varies | Shared board game mechanics |

### Scene Packs (content/scenes/) — All

| Pack | Skills | Description |
|------|--------|-------------|
| `realm` | 28 | Inventory CRUD, stat checks, director control, murder mystery, fourth-wall, desperation dice |
| `penthouse` | 24 | Wardrobe, interactions, stats, consent, atmosphere, narrative, timed actions, furniture |
| `tavern` | 10 | Order food/drink, patron info, tales, dice, brawl, cook, menu, atmosphere, secret menu, bard song |
| `lounge` | 10 | Jukebox, drinks, secrets, back room, atmosphere, social, trust |
| `neoncity` | 9 | Player status, movement, combat, hacking, storm queries, events, end turn |
| `casino` | 9 | Game state, betting, cards, table management, jackpots, check, raise, bluff |
| `gallery` | 8 | Exhibit management, art generation, critique, curation, tours, gallery walk |
| `heist` | 7 | Crew management, intel, planning, execute phase, escape |
| `games` | 7 | Word games, trivia, creative challenges, scores, status, hint, skip |
| `phone` | 6 | Message send/read, contacts, media, call controls |
| `coders` | 6 | Room status, agent info, add feature, feature list, run code, tick |
| `command_center` | 6 | System monitoring, model control, scene status, diagnostics, training |

---

## MCP Integration

Skills are exposed to LMStudio as MCP tools via the skills server (`engine/mcp/skills_server.py`):

```python
from engine.skills import mcp_skill_pack

payload = mcp_skill_pack(
    server_url="ws://127.0.0.1:3001",
    allowed_tools=["generate_image", "search_memory"],
    name="cosysim-tools",
)
# Pass as: llm.act(prompt, tools, integrations=[payload])
```

The `StreamProcessor` tracks the tool call lifecycle during SSE streaming: `start → arguments → result`. Post-call interceptors can inspect `context["tool_calls"]` to see which skills were invoked.

See [MCP Framework](MCP_FRAMEWORK.md) for the full pipeline architecture.

---

## Change Log

```
v1.50 [2026-03-22] — Complete documentation rewrite for ~1,000 skills / 95 packs
v1.42.1 [2026-03-21] — Module headers, section dividers, version stamps
v1.42.0 [2026-03-21] — Three-pillar architecture, pillar field on SkillMeta
v1.41.0 [2026-03-20] — ARGUS deep polish, nexus_first decorator option
v1.39.0 [2026-03-19] — CooldownTracker thread safety, SkillMeta cost field
v1.03b  [original]   — Initial skills documentation
```
