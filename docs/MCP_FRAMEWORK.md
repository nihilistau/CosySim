# CosySim MCP Framework

> **Audience:** Developers extending or debugging the CosySim agent / governance layer.

---

## Table of Contents

1. [Overview](#overview)
2. [MCP Server (cosysim_server.py)](#mcp-server-cosysim_serverpy)
3. [Governance Pipeline](#governance-pipeline)
4. [State Management](#state-management)
5. [Dialog System](#dialog-system)
6. [Rules Engine](#rules-engine)
7. [Interaction Trees](#interaction-trees)
8. [Skills Integration](#skills-integration)
9. [Writing a Custom Tool](#writing-a-custom-tool)
10. [MCP Tool Decorator](#mcp-tool-decorator)
11. [Writing a Custom Interceptor](#writing-a-custom-interceptor)

---

## Overview

CosySim is a multi-agent simulation framework built on the **Model Context Protocol (MCP)** pattern. An ephemeral MCP server (`cosysim_server.py`) exposes every simulation action — memory, character state, scene manipulation, dialog, media — as discrete tool calls that LLM agents can invoke.

### Why MCP?

MCP provides a structured, tool-call interface between LLM agents and the simulation. Instead of free-form text commands, every agent action is a typed function with validated parameters and structured return values. This gives us:

- **Governance hooks** — every tool call passes through the interceptor pipeline where policy, personality, and scene rules can shape or block it.
- **Auditability** — every invocation is logged with the agent ID, scene, and parameters.
- **Composability** — tools can be mixed per-scene via skill manifests without code changes.

### Architecture Layers

```
┌──────────────────────────────────────────────────────────┐
│  config/                YAML configuration               │
│  ├── default.yaml       All settings: scenes, agents,    │
│  │                      LMStudio, framework params       │
│  └── skill_manifests    Per-scene skill rosters          │
├──────────────────────────────────────────────────────────┤
│  engine/                Reusable technology               │
│  ├── mcp/               MCPFramework, tools/, governance │
│  ├── skills/            @skill decorator, registry       │
│  ├── agents/            CharacterAgent, interceptors     │
│  ├── lmstudio/          ModelManager, VRAM management    │
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

## MCP Server (cosysim_server.py)

The MCP server is the single entry point for all agent tool calls. It registers **107 `@mcp.tool` functions** that delegate to **8 domain modules** in `engine/mcp/tools/`.

### Tool Categories

| Module | Category | Example tools |
|--------|----------|---------------|
| `memory_tools.py` | Memory | `memory_recall`, `store_memory` |
| `character_tools.py` | Character | `character_get_summary`, `mood_contagion`, `relationship_adjust` |
| `game_tools.py` | Game | Game state CRUD, session management |
| `scene_tools.py` | Scene | `get_scene_snapshot`, `set_scene_atmosphere`, `environment_change` |
| `wardrobe_tools.py` | Wardrobe | Clothing management, outfit changes |
| `dialog_tools.py` | Dialog | `get_dialog_options`, `speech_enhance`, `set_response_directive` |
| `media_tools.py` | Media | `generate_image`, `generate_voice_message` |
| `utility_tools.py` | Utility | Dice rolls, random topics, benchmarks |

### How Tools Are Registered

Each domain module exposes plain functions. `cosysim_server.py` imports them and wraps each one with `@mcp.tool`:

```python
# cosysim_server.py (simplified)
from engine.mcp.tools.character_tools import get_character_summary

@mcp.tool
def character_get_summary(character_id: str) -> str:
    return get_character_summary(character_id)
```

The LLM sees these as available tool calls in its context. The `SkillAwarenessInterceptor` (priority 30) controls which tools are advertised per scene via the skill manifest.

### How Tools Are Invoked

```
LLM decides to call tool  ──►  MCP server receives call
    ──►  Route to domain module function
    ──►  Function reads/writes state via singletons (GameState, CharacterRegistry, etc.)
    ──►  Return structured result to LLM
```

---

## Governance Pipeline

Every LLM interaction passes through the **AgentGovernor**, which wraps a `CharacterAgent` with a pipeline of interceptors that shape requests and responses.

### AgentGovernor

`engine/mcp/comms_framework.py` · class `AgentGovernor`

The governor implements the `IAgent` protocol and orchestrates a single turn:

```
AgentGovernor.reply(user_message)
    │
    ├─ Build ResponseContext {
    │      system_prompt, policy, skill_manifest,
    │      user_message, agent_id, scene
    │  }
    │
    ├─ pipeline.run_pre(ctx)        ← 20 PRE interceptors inject/shape
    │
    ├─ CharacterAgent.reply(...)    ← single LLM call
    │
    ├─ ctx["reply"] = llm_response
    │
    └─ pipeline.run_post(ctx)       ← 4 POST interceptors shape/log
          │
          └─► return ctx["reply"]
```

Any pre-interceptor can set `ctx["abort"] = True` to skip the LLM call entirely.

### build_governance_context()

`engine/mcp/comms_framework.py` · function `build_governance_context()`

For scenes that call the LLM directly (streaming, special pipelines) but still want interceptor-generated directives:

```python
from engine.mcp.comms_framework import build_governance_context

# Returns multi-line string of interceptor injections to append to system prompt
gov_ctx = build_governance_context(agent_id="lola", scene="bedroom",
                                    user_message="Hello")
```

This builds a `ResponseContext`, runs all pre-interceptors, and returns the accumulated `system_prompt` without making an LLM call.

### Full Interceptor Pipeline (24 interceptors)

| Priority | Interceptor | Phase | Purpose |
|----------|-------------|-------|---------|
| 5 | `NaturalMoodDriftInterceptor` | pre | Subtle per-interaction stat drift & inner-thought hints |
| 6 | `ConversationRecapInterceptor` | pre | Injects conversation recap context |
| 8 | `CharacterRegistryInterceptor` | pre | Syncs character mood/energy to sys-prompt |
| 10 | `RouterMessageInjector` | pre | Injects pending inter-agent router messages |
| 12 | `DialogDirectiveInterceptor` | pre | Applies active dialog directives |
| 15 | `BedroomSceneInterceptor` | pre | Bedroom-specific sys-prompt + heat gating |
| 15 | `PhoneSceneInterceptor` | pre | Phone scene sys-prompt + ConversationHeat |
| 15 | `LoungeSceneInterceptor` | pre | Lounge scene sys-prompt additions |
| 15 | `GallerySceneInterceptor` | pre | Gallery scene sys-prompt additions |
| 16 | `UniversalSceneInterceptor` | pre | Catch-all for scenes without a dedicated interceptor |
| 17 | `AmbientEventInterceptor` | pre | Random micro-events (25% chance per call) |
| 20 | `AutoResultInjector` | pre | Injects auto-triggered skill results |
| 30 | `SkillAwarenessInterceptor` | pre | Lists REQUIRED / AVAILABLE tools per scene |
| 35 | `GameInterceptor` | pre | Injects active game session state + rules |
| 45 | *(reserved)* | pre | Custom interceptor slot |
| 50 | `PersonalityGuardInterceptor` | pre | Forbidden topics, required tone |
| 55 | `ConversationVarietyInterceptor` | pre | Adjusts tone using ConversationHeat directives |
| 60 | `PolicyEnforcerInterceptor` | pre | Enforces max-token prompt reminder |
| 70 | `MemoryEnhancerInterceptor` | pre | Injects top-k semantic memories |
| 80 | `ResponseShaperInterceptor` | post | Strips leaked skill sections, trims |
| 85 | `TTSStyleInterceptor` | post | Builds `ctx["tts_meta"]` for CosyVoice |
| 90 | `ActivityLoggerInterceptor` | post | Logs interaction to DB |
| 92 | `MoodSyncInterceptor` | post | Strips `[MOOD:xxx]` tag, syncs registry, evaluates threshold rules |
| 93 | `RelationshipEventInterceptor` | post | Emits relationship change events |

---

## State Management

State is distributed across four systems. The **CharacterStateCoordinator** acts as the single write-through API that keeps them in sync.

### SceneStateManager

`engine/mcp/scene_state.py` — Per-scene state: character stats, clothing, narrative, timed actions, atmosphere.

```python
from engine.mcp.scene_state import get_scene_state_manager

ssm = get_scene_state_manager()
ssm.update_stats("bedroom", "lola", {"arousal": +10, "happiness": +5})
stats = ssm.get_stats("bedroom", "lola")
```

### CharacterRegistry

`engine/mcp/character_registry.py` — Character profiles, personality, skills, restrictions, mood/energy/inhibition state.

```python
from engine.mcp.character_registry import get_character_registry

reg = get_character_registry()
reg.set_state("lola", mood="flirty", energy=80.0)
state = reg.get_state("lola")
```

### CharacterStateCoordinator

`engine/mcp/state_coordinator.py` — Unified write-through API. Routes fields to the correct store automatically.

```python
from engine.mcp.state_coordinator import get_coordinator

coord = get_coordinator()

# Single call routes mood → Registry, arousal → SSM, emits event, optionally persists
coord.update("lola", mood="flirty", arousal=+10, energy=-5)
coord.update("lola", arousal=50, mode="set")   # absolute instead of delta

state = coord.get_full_state("lola")
```

| Field group | Target store | Examples |
|-------------|-------------|----------|
| Registry fields | `CharacterRegistry.set_state()` | mood, mood_intensity, energy, inhibition, focus |
| Stats fields | `SceneStateManager.update_stats()` | arousal, happiness, anger, fear, drunkenness, tiredness |
| Restrictions | `CharacterRegistry.add/remove_restriction()` | add_restriction, remove_restriction |

Every `update()` emits a `state_changed` event on the ActivityBus. Pass `persist=True` to also write to the database.

> **Convention:** All scenes, interceptors, and MCP tools should use the coordinator — never call `set_state()` / `update_stats()` directly.

### TagRegistry

`engine/mcp/tag_registry.py` — Central registry for inline behavioral tags (`[MOOD:xxx]`, `[IMAGE:xxx]`, `[ACTION:xxx]`, etc.) with decay support. Tags are parsed from LLM output and routed to the appropriate system.

---

## Dialog System

`engine/mcp/dialog_system.py` · class `DialogSystem`

The dialog system manages contextual dialog options, speech style enhancement, and temporary behavior steering.

### Dialog Options

Per-scene dialog trees with context-aware choices:

```python
from engine.mcp.dialog_system import get_dialog_system

ds = get_dialog_system()
options = ds.get_options("bedroom", "lola", context={"mood": "playful"})
# [DialogOption(label="Tease her", text="...", tag="flirty"), ...]
```

### Speech Enhancement

`SpeechEnhancer` transforms plain text into character-appropriate speech styles:

```python
enhanced = ds.enhance_speech("lola", "Hello there",
                              style="playful")  # or "teasing", "vulnerable", "dominant"
```

Available styles: `playful`, `teasing`, `vulnerable`, `dominant`, `seductive`, and more (see `SpeechStyle` constants).

### ResponseDirective

Temporary behavior steering injected by the director or scene logic:

```python
ds.set_directive("bedroom", "lola",
                  force_response="Ask about the gift",
                  must_include=["surprise"],
                  style_lock="vulnerable")
```

The `DialogDirectiveInterceptor` (priority 12) picks up active directives and injects them into the system prompt before the LLM call.

### ConversationHeat

`engine/mcp/scene_rules_engine.py` · class `ConversationHeat`

A thermal model tracking conversation intensity on a **0–100 scale**:

| Range | Tier | Directive injected |
|-------|------|--------------------|
| < 30 | Normal | *(none)* |
| 30–59 | WARM | Flirty, playful energy; innuendo and light teasing |
| 60–79 | HOT | Suggestive and seductive; escalation encouraged |
| ≥ 80 | INTENSE | Passionate and explicit; full adult content |

Messages are scanned for keywords that auto-bump heat (e.g. `kiss` +15, `intimate` +20, `touch` +10). Per-message bump is capped at +25. Heat decays at −2/min after 30 seconds idle.

```python
from engine.mcp.scene_rules_engine import get_conversation_heat

heat = get_conversation_heat()
heat.analyze_message("phone_aria_thread1", "She leaned in to kiss him")
level = heat.get("phone_aria_thread1")          # e.g. 45.0
directive = heat.get_directive("phone_aria_thread1")
```

---

## Rules Engine

`engine/mcp/scene_rules_engine.py` · class `SceneRulesEngine`

A data-driven rules engine that governs scene behavior, available actions, and character permissions.

### RuleDefinition

Named rules with conditions, effects, and priorities:

```python
from engine.mcp.scene_rules_engine import get_rules_engine

eng = get_rules_engine()

# Register a triggered rule
eng.add_rule("bedroom", RuleDefinition(
    rule_id="intimate_unlock",
    label="Unlock intimate actions",
    rule_type="triggered",
    conditions=[RuleCondition(stat="arousal", operator=">=", value=70)],
    effects=[RuleEffect(action="unlock_actions", params={"group": "intimate"})],
    priority=10
))

# Evaluate threshold rules after stat changes
triggered = eng.evaluate_threshold_rules("bedroom", "lola",
    {"arousal": 70, "happiness": 50})
for rule in triggered:
    eng.apply_rule("bedroom", rule["rule_id"], target_ids=["lola"])
```

Rule types: `always_on` (active every turn), `triggered` (fires when stat thresholds crossed), `director_only` (manually invoked).

### ActionDefinition

Available actions per scene, with intimacy levels and stat conditions:

```python
action = ActionDefinition(
    action_id="kiss",
    label="Kiss",
    intimacy_level=2,
    conditions={"arousal": 30},
    effects={"arousal": +15, "happiness": +10}
)
```

### PermissionMatrix

Per-scene, per-character action permission table:

```python
matrix = PermissionMatrix()
matrix.allow("bedroom", "lola", "kiss")
matrix.deny("bedroom", "lola", "leave_scene")
can = matrix.check("bedroom", "lola", "kiss")  # True
```

### Threshold Rules Flow

```
LLM response arrives
    → MoodSyncInterceptor.post_call() (priority 92)
        → sync mood/energy to CharacterRegistry
        → gather stats from SSM + CharacterRegistry
        → SceneRulesEngine.evaluate_threshold_rules()
        → apply_rule() for each triggered rule
```

---

## Interaction Trees

`engine/mcp/interaction_trees.py`

Interaction trees define branching interaction paths with phases, stat effects, and requirements.

### Core Data Model

```python
@dataclass
class InteractionSubtype:
    id: str
    label: str
    description: str
    duration: float            # seconds
    intimacy: int              # 1–5
    stat_effects: Dict[str, float]
    phases: List[str]          # e.g. ["beginning", "peak", "afterglow"]
    fragments: List[str]       # sample narrative lines
    requires: Dict[str, float] # minimum stat thresholds

@dataclass
class InteractionType:
    id: str
    label: str
    description: str
    subtypes: List[InteractionSubtype]
```

### Built-in Interaction Sets

**Bedroom** (6 types): `cuddle`, `kiss`, `caress`, `striptease`, `oral`, `penetration`
**Phone** (6 types): phone-specific interaction variants

Each type contains multiple subtypes with escalating intimacy levels (1–5).

### Phase Management

Subtypes define ordered phases that represent narrative progression:

```python
subtype.phases  # ["beginning", "building", "peak", "afterglow"]
```

### Requirements Checking

Interactions check minimum stat thresholds before firing:

```python
interaction = BEDROOM_INTERACTIONS["kiss"]
subtype = interaction.get_subtype("neck_kiss")
# subtype.requires = {"arousal": 30, "affection": 20}
# Only available when character stats meet these minimums

result = get_interaction_result(interaction_type="kiss", subtype="neck_kiss",
                                 character_stats=current_stats)
```

---

## Skills Integration

### The @skill Decorator

`engine/skills/skill.py`

Every tool available to agents is registered as a skill:

```python
from engine.skills.skill import skill, SkillCategory

@skill(
    name="serve_drink",
    pack="casino",
    description="Serve a cocktail to a player",
    tags=["casino", "social"],
    category=SkillCategory.SOCIAL,
    cooldown=5.0,
    prerequisites=["get_scene_snapshot"],
    cost=1.0
)
def serve_drink(drink_id: str, target: str = "player") -> str:
    return f"Served {drink_id} to {target}"
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | Skill identifier |
| `pack` | str | `"default"` | Group name for related skills |
| `description` | str | `""` | LLM-facing description |
| `tags` | list | `[]` | Searchable tags |
| `category` | SkillCategory | `""` | Category constant |
| `cooldown` | float | `0.0` | Minimum seconds between invocations |
| `prerequisites` | list | `[]` | Required skill names that must exist |
| `cost` | float | `1.0` | Relative compute/resource cost |

### Skill Packs

Skills are grouped into packs — some scene-specific, some built-in:

| Pack | Skills | Description |
|------|--------|-------------|
| `character` | speak_as, speech_enhance, character_get_summary | Character voice and identity |
| `memory` | memory_recall, store_memory | Long-term memory |
| `environment` | set_scene_atmosphere, environment_change | Scene atmosphere |
| `narrative` | inject_story_beat, get_dialog_options, set_response_directive | Story direction |
| `social` | mood_contagion, relationship_adjust, scene_broadcast, get_scene_snapshot | Social dynamics |
| `tts` / `voice` | generate_voice_message | Voice synthesis |
| `comfyui` | generate_image | Image generation |

### Skill Manifest (Per-Scene)

`SkillManifest` controls which skills are available per scene and how the LLM interacts with them:

| Trigger | Meaning |
|---------|---------|
| `auto` | Fires automatically every turn; result injected into pre-call context |
| `optional` | LLM is told the skill exists but chooses whether to call it |
| `required` | LLM must call this skill before replying |

Manifests are configured in `config/skill_manifests.yaml` and hot-reloadable per scene.

### How the LLM Invokes Skills

1. `SkillAwarenessInterceptor` (priority 30) reads the scene manifest and lists `REQUIRED` / `AVAILABLE` tools in the system prompt.
2. The LLM responds with a tool-call in its output.
3. The MCP server routes the call to the registered skill function.
4. The result is returned to the LLM for incorporation into its reply.
5. `AutoResultInjector` (priority 20) handles `auto`-trigger skills by pre-injecting their results before the LLM call.

---

## Writing a Custom Tool

> **v0.84b pattern:** Use `@mcp_tool` in the domain file, then add a thin
> wrapper in `cosysim_server.py`. Full details in the
> [MCP Tool Decorator](#mcp-tool-decorator) section below.

### Step 1: Create the function in a tools module

```python
# engine/mcp/tools/utility_tools.py  (or a new module)
from engine.mcp.decorators import mcp_tool, ToolExecutionError

@mcp_tool
def roll_dice(sides: int = 6) -> dict:
    """Roll a dice with N sides."""
    import random
    if sides < 2:
        raise ToolExecutionError(f"sides must be >= 2, got {sides}")
    result = random.randint(1, sides)
    return {"roll": result, "sides": sides}
```

### Step 2: Add the wrapper in cosysim_server.py

```python
# cosysim_server.py
from engine.mcp.tools.utility_tools import roll_dice as _roll_dice

@mcp.tool
def roll_dice(sides: int = 6) -> dict:
    """Roll a dice with N sides."""
    return _roll_dice(sides)
```

### Step 3: (Optional) Register as a skill for manifest control

```python
from engine.skills import SKILL_REGISTRY
SKILL_REGISTRY["roll_dice"] = roll_dice
```

Then add it to the scene's skill manifest in `config/skill_manifests.yaml`:

```yaml
scenes:
  casino:
    - name: roll_dice
      trigger: optional
      description: "Roll a dice (1–N sides)"
```

---

## MCP Tool Decorator

> **Added in v0.84b (Project Hindsight).** See [Project Hindsight](./PROJECT_HINDSIGHT.md)
> for full context on the MCP server extraction.

### The Thin Wrapper Pattern

All tool logic in v0.84b lives in domain files under `engine/mcp/tools/`.
`cosysim_server.py` is a pure thin routing layer — it only holds `@mcp.tool`
stubs that immediately delegate:

```
Before v0.84b                         After v0.84b
─────────────────────────────         ──────────────────────────────────────
cosysim_server.py (3,088 lines)  →    cosysim_server.py (2,192 lines)
  all logic here                         thin wrappers only
                                       engine/mcp/tools/ (43 files, 8,147 lines)
                                         all logic here
```

**Rule:** Never add business logic directly in `cosysim_server.py`.

### `@mcp_tool`

`engine/mcp/decorators.py` · decorator `mcp_tool`

Wraps domain functions with:

- **JSON serialisation** — dict/list returns are serialised automatically
- **Structured errors** — `ToolExecutionError` is caught and returned as
  `{"error": "..."}` rather than raising to the LLM
- **Execution timing** — logged at `DEBUG` with tool name and duration
- **Tool name** — auto-extracted from function name (no decorator argument needed)

```python
# engine/mcp/tools/character_tools.py
from engine.mcp.decorators import mcp_tool, ToolExecutionError
from engine.mcp.character_registry import get_character_registry

@mcp_tool
def get_character_summary(character_id: str) -> str:
    """Return a full character summary string."""
    reg = get_character_registry()
    char = reg.get(character_id)
    if char is None:
        raise ToolExecutionError(f"Character not found: {character_id}")
    return char.to_summary()

@mcp_tool
def set_character_mood(character_id: str, mood: str) -> dict:
    reg = get_character_registry()
    reg.set_state(character_id, mood=mood)
    return {"ok": True, "character_id": character_id, "mood": mood}
```

```python
# cosysim_server.py — thin wrapper only
from engine.mcp.tools.character_tools import (
    get_character_summary as _get_character_summary,
    set_character_mood as _set_character_mood,
)

@mcp.tool
def character_get_summary(character_id: str) -> str:
    """Get a full character summary."""
    return _get_character_summary(character_id)

@mcp.tool
def character_set_mood(character_id: str, mood: str) -> dict:
    """Set a character's mood."""
    return _set_character_mood(character_id, mood)
```

### `ToolExecutionError`

`engine/mcp/decorators.py` · exception `ToolExecutionError`

Use for **expected** failures: bad input, resource not found, permission denied.
These are returned to the LLM as structured error responses — not Python exceptions.

```python
from engine.mcp.decorators import ToolExecutionError

# Expected failure → returned as {"error": "Scene not active: casino"}
raise ToolExecutionError("Scene not active: casino")

# Unexpected failure → propagates, logged, returned as generic error
raise RuntimeError("Database connection lost")
```

| Error type | When to use | LLM receives |
|------------|-------------|--------------|
| `ToolExecutionError` | Bad param, not found, permission | `{"error": "your message"}` |
| Any other exception | Unexpected crash | `{"error": "internal error"}` + server log |

### Domain File Layout

The 43 domain files in `engine/mcp/tools/` are grouped by responsibility:

| File | Domain | Example functions |
|------|--------|-------------------|
| `character_tools.py` | Character state | `get_character_summary`, `set_mood` |
| `memory_tools.py` | Memory / Nexus | `memory_recall`, `store_memory` |
| `scene_tools.py` | Scene state | `get_scene_snapshot`, `set_atmosphere` |
| `wardrobe_tools.py` | Clothing | `change_outfit`, `get_wardrobe_state` |
| `game_tools.py` | Game sessions | `start_game`, `get_game_state` |
| `dialog_tools.py` | Dialog / speech | `get_dialog_options`, `speech_enhance` |
| `media_tools.py` | Images / TTS | `generate_image`, `generate_voice_message` |
| `utility_tools.py` | Dice, topics, misc | `roll_dice`, `random_topic` |
| *(35 more)* | Scene-specific | Arena, Casino, Heist, Grid, etc. |

### Adding a New Tool (v0.84b Pattern)

#### Step 1: Add logic to a domain file

```python
# engine/mcp/tools/utility_tools.py

from engine.mcp.decorators import mcp_tool, ToolExecutionError

@mcp_tool
def flip_coin() -> dict:
    """Flip a coin and return the result."""
    import random
    return {"result": random.choice(["heads", "tails"])}
```

#### Step 2: Add a thin wrapper in cosysim_server.py

```python
# cosysim_server.py
from engine.mcp.tools.utility_tools import flip_coin as _flip_coin

@mcp.tool
def flip_coin() -> dict:
    """Flip a coin."""
    return _flip_coin()
```

#### Step 3: (Optional) Register as a skill for manifest control

```python
from engine.skills import SKILL_REGISTRY
SKILL_REGISTRY["flip_coin"] = flip_coin
```

Then add to `config/skill_manifests.yaml`:

```yaml
scenes:
  casino:
    - name: flip_coin
      trigger: optional
      description: "Flip a coin — heads or tails"
```

---

## Writing a Custom Interceptor

> **v0.84b:** Interceptors use `@register_interceptor` auto-registry. See
> [INTERCEPTORS.md](./INTERCEPTORS.md) for the full reference.

### Step 1: Create the file in the interceptors package

```python
# engine/agents/interceptors/weather_injector.py
from engine.agents.interceptors.base import InterceptorBase, register_interceptor
from engine.mcp.comms_framework import ResponseContext

@register_interceptor
class WeatherInjector(InterceptorBase):
    """Inject current weather into system prompt before LLM call."""

    name     = "weather_injector"
    priority = 45                   # slot in pipeline (0–100+)

    def pre_call(self, ctx: ResponseContext) -> None:
        weather = fetch_weather()
        ctx["system_prompt"] += f"\n[Current weather: {weather}]"

    def post_call(self, ctx: ResponseContext) -> None:
        pass
```

### Step 2: Done — auto-registered

`@register_interceptor` adds the class to the global registry. No changes to
`__init__.py`, `comms_framework.py`, or any server file are needed. The
interceptor appears in all pipelines on the next server startup.

### Step 3: (Optional) Add at runtime

```python
from engine.mcp import get_governor
from engine.agents.interceptors.weather_injector import WeatherInjector

gov = get_governor(my_agent, scene="lounge")
gov.pipeline.add(WeatherInjector())  # sorted by priority automatically
```

### Step 4: (Optional) Remove later

```python
gov.pipeline.remove("weather_injector")
```

### Priority Guidelines

| Range | Convention |
|-------|-----------|
| 1–10 | Early state sync (mood drift, registry sync) |
| 10–20 | Message/directive injection |
| 15–17 | Scene-specific interceptors |
| 20–40 | Skill awareness, game state |
| 45–70 | Guards, policy, memory |
| 80–93 | Post-processing (shaping, TTS, logging, mood sync) |

---

## Module Exports Quick Reference

### `from engine.mcp import ...`

| Symbol | Type | Purpose |
|--------|------|---------|
| `get_governor` | function | Create/get a governor for an agent |
| `AgentGovernor` | class | Governance wrapper for any IAgent |
| `InterceptorBase` | ABC | Base class for custom interceptors |
| `InterceptorPipeline` | class | Ordered interceptor container |
| `ResponseContext` | class | Dict-like context bag for one turn |
| `InteractionPolicy` | dataclass | Per-turn policy configuration |
| `build_governance_context` | function | Build interceptor context without a governor |
| `GameState` | class | Game key/value store |
| `get_game_state` | function | Get singleton GameState |
| `AgentRouter` | class | Inter-agent message inbox |
| `get_router` | function | Get singleton AgentRouter |
| `SkillManifest` | class | Scene→skill registry |
| `get_skill_manifest` | function | Get singleton SkillManifest |

### `from engine.agents import ...`

| Symbol | Type | Purpose |
|--------|------|---------|
| `CharacterAgent` | class | Primary LLM conversational agent |
| `AgentGovernor` | class | (re-export from mcp) |
| `get_governor` | function | (re-export from mcp) |
| `IAgent` | Protocol | Structural interface contract |
| `AgentCapability` | Enum | Declared agent capabilities |
