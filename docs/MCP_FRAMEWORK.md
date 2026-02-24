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

> **Note:** For character-level state (mood, energy, stats), use the **CharacterStateCoordinator** with `persist=True` instead — see [CharacterStateCoordinator](#characterstatecoordinator).

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

## CharacterStateCoordinator

> **Module:** `engine/mcp/state_coordinator.py`

The **CharacterStateCoordinator** is the unified write-through API for all character state mutations. Before it existed, state was scattered across three stores that didn't sync:

- **CharacterRegistry** — mood, energy, inhibition, focus, restrictions
- **SceneStateManager** — arousal, happiness, clothing, narrative, stats
- **Database** — persistent name/age/personality

The coordinator provides a single `update()` method that auto-routes fields to the correct store and keeps everything in sync.

### Quick Start

```python
from engine.mcp.state_coordinator import get_coordinator

coord = get_coordinator()

# Unified update — routes fields to the right store automatically
coord.update("lola", mood="flirty", arousal=+10, energy=-5)

# Get a unified snapshot of all state
state = coord.get_full_state("lola")
# {"mood": "flirty", "mood_intensity": 0.5, "energy": 75.0,
#  "arousal": 30.0, "happiness": 60.0, ...}
```

### Delta vs Set Mode

```python
coord.update("lola", arousal=+15)              # delta (default): arousal += 15
coord.update("lola", arousal=50, mode="set")   # absolute: arousal = 50
```

### Field Routing

| Field group | Target store | Examples |
|-------------|-------------|----------|
| Registry fields | `CharacterRegistry.set_state()` | mood, mood_intensity, energy, inhibition, focus, current_role |
| Stats fields | `SceneStateManager.update_stats()` / `set_stats()` | arousal, happiness, anger, fear, drunkenness, tiredness, explicitness, openness, affection, dominance |
| Restrictions | `CharacterRegistry.add/remove_restriction()` | add_restriction, remove_restriction |
| Unknown fields | Registry flags | Any other key |

### Events & Persistence

Every `update()` call emits a `state_changed` event on the **ActivityBus** with the character ID, changed fields, and a full snapshot. Register listeners directly:

```python
coord.on_state_changed(lambda event, snapshot: print(event))
```

Optional database persistence (cross-session):

```python
coord.update("lola", mood="happy", persist=True)
```

### Thread Safety

Per-character `threading.Lock` ensures concurrent updates to different characters don't block each other. A global lock protects the lock-map itself.

### Singleton Access

```python
from engine.mcp.state_coordinator import get_coordinator
coord = get_coordinator()  # Thread-safe, returns the global singleton
```

### Architecture

```
coord.update(char_id, **fields)
    ├── Registry fields → CharacterRegistry.set_state()
    ├── Stats fields    → SceneStateManager.update_stats() or set_stats()
    ├── ActivityBus     → emit("state_changed", {char_id, deltas, snapshot})
    └── DB persist      → Database.update_character() (if persist=True)
```

> **Convention:** Every scene, interceptor, and MCP tool should go through the coordinator instead of calling `set_state()` / `update_stats()` directly.

---

## ConversationHeat

> **Module:** `engine/mcp/scene_rules_engine.py` · **Class:** `ConversationHeat`

A thermal conversation model that tracks "heat" per conversation key on a **0–100 scale**. Heat increases with flirty, intimate, or emotional topics and decays automatically with idle time.

### Heat Tiers & Directives

| Range | Tier | Directive injected into system prompt |
|-------|------|--------------------------------------|
| < 30 | Normal | *(none)* |
| 30–59 | WARM | Flirty, playful energy; innuendo and light teasing |
| 60–79 | HOT | Suggestive and seductive; escalation encouraged |
| ≥ 80 | INTENSE | Passionate and explicit; full adult content |

### Keyword Auto-Bumps

Messages are scanned for keywords that automatically increase heat:

| Keyword | Bump | Keyword | Bump |
|---------|------|---------|------|
| `flirt` | +8 | `touch` | +10 |
| `kiss` | +15 | `sexy` | +12 |
| `intimate` | +20 | `seduce` | +15 |
| `tease` | +7 | `passion` | +12 |
| `cuddle` | +5 | `desire` | +10 |
| `dare` | +6 | `love` | +5 |

Per-message bump is capped at +25.

### Decay

Heat decays at **−2 per minute** after 30 seconds of idle time on each conversation key.

### Usage

```python
from engine.mcp.scene_rules_engine import get_conversation_heat

heat = get_conversation_heat()

# Analyze a message (auto-bumps from keywords)
heat.analyze_message("phone_aria_thread1", "She leaned in to kiss him")

# Manual bump/cool
heat.bump("phone_aria_thread1", 10, "flirt")
heat.cool("phone_aria_thread1", 5)

# Get current level and directive
level = heat.get("phone_aria_thread1")       # e.g. 45.0
directive = heat.get_directive("phone_aria_thread1")
# "[CONVERSATION HEAT: WARM] The conversation has a flirty, playful energy..."

# Snapshot all conversations
heat.to_dict()  # {"phone_aria_thread1": 45.0, ...}
```

### Consumers

- **ConversationVarietyInterceptor** — uses heat directives to adjust tone
- **BedroomSceneInterceptor** — uses heat level to gate escalation
- **PhoneSceneInterceptor** — integrates heat level for phone conversation tone *(Sprint 2)*

---

## NaturalMoodDriftInterceptor

> **Module:** `engine/agents/interceptors.py` · **Priority:** 5 (first in pipeline)

The **NaturalMoodDriftInterceptor** applies subtle, per-interaction stat drift so characters feel emotionally alive even when nothing dramatic is happening. It is the first interceptor in the 19-interceptor pipeline (priority 5).

### Drift Values (per interaction)

| Stat | Delta | Rationale |
|------|-------|-----------|
| arousal | −2 | Cools naturally between interactions |
| tiredness | +1 | Gradually builds over a session |
| happiness | −0.5 | Regresses toward neutral baseline |
| anger | −3 | Fades quickly without reinforcement |
| fear | −2 | Dissipates when nothing scary happens |
| drunkenness | −1 | Slowly metabolises over time |

### Inner-Thought Hints

After applying drift, the interceptor inspects the dominant emotional state and injects a brief "inner thought" hint into the system prompt. This gives the LLM a subtle nudge without overriding scene directives — e.g. *"She feels a lingering tiredness creeping in"* or *"A faint unease still echoes from earlier."*

### Scene Scope

Active only in **bedroom**, **phone**, **lounge**, and **gallery** scenes. Other scenes (casino, hub, admin) are unaffected.

### Cross-System Sync

All stat mutations are routed through the **CharacterStateCoordinator** (`get_coordinator().update()`), ensuring drift values propagate to the CharacterRegistry, SceneStateManager, and ActivityBus listeners in a single atomic write.

---

## Sprint 2 Integration Notes

The following cross-cutting changes were made in Sprint 2:

- **PhoneSceneInterceptor** now integrates **ConversationHeat** — phone conversations respond to heat tier directives just like bedroom scenes.
- **Phone agent** now accepts `governance_context` — interceptor injections (directives, memory, personality guards) are no longer silently discarded by the phone agent.
- **Bedroom stat changes** now route through **CharacterStateCoordinator** — all bedroom stat mutations use `get_coordinator().update()` for cross-system sync instead of direct `SceneStateManager` calls.
- **Pipeline size** increased from 18 to **20 interceptors** (priority 5 → 92) with the additions of `NaturalMoodDriftInterceptor` (Sprint 2) and `GallerySceneInterceptor` (Sprint 4).

### Sprint 3-5 Updates

- **Sprint 3:** Migrated remaining 6 scenes to CharacterStateCoordinator (Gallery, Warzone, Realm, NeonCity, Heist, Bedroom). Fixed NeonCity invalid `update_stats()` API call. Added InteractionRecord logging for bedroom physical interactions.
- **Sprint 4:** Added `GallerySceneInterceptor` (pipeline now 20 interceptors). Action-based heat bumping in MoodSyncInterceptor — physical actions auto-bump ConversationHeat. `CharacterRegistry.persist_to_db()` writes runtime state to DB. `BaseScene.stop()` auto-persists. ConversationHeat wired into Lounge interceptor.
- **Sprint 5:** Scene transition tracking — MCPFramework tracks player journey. `RouterMessageInjector` tells agents where the player came from. Dead code audit confirmed codebase is clean.

---

## Threshold Rules

> **Module:** `engine/mcp/scene_rules_engine.py` · **Method:** `SceneRulesEngine.evaluate_threshold_rules()`
> **Wired via:** `engine/agents/interceptors.py` · **Class:** `MoodSyncInterceptor` (priority 92)

Threshold rules are **triggered rules** that auto-fire when character stats cross defined thresholds. After every mood sync in the interceptor pipeline, the MoodSyncInterceptor automatically evaluates all threshold rules and applies any that match.

### Flow

```
LLM response arrives
    → MoodSyncInterceptor.post_call()  (priority 92)
        → sync mood/energy to CharacterRegistry
        → _evaluate_threshold_rules(scene, agent_id, ctx)
            → gather stats from SSM + CharacterRegistry
            → SceneRulesEngine.evaluate_threshold_rules(scene, char_id, stats)
            → for each triggered rule: SceneRulesEngine.apply_rule()
```

### Rule Evaluation

`evaluate_threshold_rules(scene, character_id, stats)` checks all rules of type `"triggered"` for the given scene. Each rule has conditions with a stat name, operator (`>=`, `<=`, `==`), and threshold. All conditions must be met for the rule to fire.

```python
from engine.mcp.scene_rules_engine import get_rules_engine

eng = get_rules_engine()
triggered = eng.evaluate_threshold_rules("bedroom", "lola", {
    "arousal": 70, "happiness": 50
})
# [{"rule_id": "intimate_unlock", "label": "Unlock intimate actions"}]

for rule in triggered:
    eng.apply_rule("bedroom", rule["rule_id"], target_ids=["lola"])
```

### Stats Merging

The MoodSyncInterceptor merges stats from both stores before evaluation:
- **SceneStateManager** stats: arousal, happiness, etc.
- **CharacterRegistry** state: mood_intensity, energy, inhibition

This ensures threshold conditions can reference fields from either store.

---

## Overlay REST API

> **Module:** `engine/overlay/overlay_bp.py`

The overlay Blueprint exposes REST endpoints for direct access to the unified state layer and conversation heat system. All endpoints are under the `/overlay` prefix.

### Character State

#### `GET /overlay/api/character/<id>/state`

Returns unified character state via the CharacterStateCoordinator. Merges CharacterRegistry fields (mood, energy, inhibition) with SceneStateManager stats (arousal, happiness, etc.) into one response.

```json
{
  "ok": true,
  "character_id": "lola",
  "mood": "flirty",
  "energy": 75.0,
  "arousal": 30.0,
  "happiness": 60.0
}
```

#### `POST /overlay/api/character/<id>/state`

Update character state via the CharacterStateCoordinator. Accepts any combination of Registry and Stats fields.

**Request body:**

```json
{
  "mood": "playful",
  "arousal": 10,
  "mode": "delta",
  "source": "overlay_api",
  "persist": false
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | string | `"delta"` | `"delta"` adds to numeric fields; `"set"` overwrites |
| `source` | string | `"overlay_api"` | Audit trail identifier |
| `scene` | string | `""` | Scene context |
| `persist` | bool | `false` | Also write to database |

Returns the full state snapshot after the update.

### Conversation Heat

#### `GET /overlay/api/heat`

Returns conversation heat levels. Optionally filter by conversation key.

**Without key** — returns all tracked conversations:

```json
{
  "ok": true,
  "conversations": {
    "phone_aria_thread1": 45.2,
    "bedroom_lola": 72.0
  }
}
```

**With `?key=phone_aria_thread1`** — returns single conversation with directive:

```json
{
  "ok": true,
  "key": "phone_aria_thread1",
  "heat": 45.2,
  "directive": "[CONVERSATION HEAT: WARM] The conversation has a flirty, playful energy..."
}
```

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
