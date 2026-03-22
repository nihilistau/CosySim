# Interceptor Pipeline

> CosySim Documentation — v1.50 [2026-03-22]
>
> 24 pre/post-call hooks governing every agent LLM call.

The interceptor pipeline modifies prompts **before** the LLM runs (`pre_call`) and processes
replies **after** it returns (`post_call`). This gives CosySim fine-grained
control over agent behavior without changing agent code.

> **Source:** `engine/agents/interceptors/` (24 interceptor modules + 2 infrastructure) · `engine/mcp/comms_framework.py`
>
> See also: [MCP Framework](MCP_FRAMEWORK.md) · [Skills](SKILLS.md) · [Architecture](ARCHITECTURE.md)

---

## How It Works

```
User message
  │
  ▼
┌──────────────────────────────────────────────────────┐
│  AgentGovernor.reply()                               │
│                                                      │
│  1. Build ResponseContext (scene, agent, policy)      │
│  2. Execute AUTO-triggered skills                    │
│  3. ─── PRE-CALL PIPELINE (ascending priority) ───   │
│     │  MoodDrift (5) → NexusPrompt (6) → Recap (7)  │
│     │  → CharRegistry (8) → Router (10) → Dialog(12)│
│     │  → SceneInterceptors (15-16) → Ambient (17)   │
│     │  → AutoResult (20) → SkillAware (30) → Game(35)│
│     │  → PersonalityGuard (50) → Variety (55)       │
│     │  → PolicyEnforcer (60) → Memory (70)          │
│  4. Call LLM (CharacterAgent.reply)                  │
│  5. Parse response (ContentRouter.parse_full)        │
│  6. ─── POST-CALL PIPELINE (ascending priority) ──   │
│     │  Dialog (12) → Game (35) → Variety (55)        │
│     │  → ResponseShaper (80) → TTS (85)              │
│     │  → Logger (90) → MoodSync (92) → Rel (93)     │
│  7. Return final reply                               │
└──────────────────────────────────────────────────────┘
```

### ResponseContext

`ResponseContext` is a mutable dict shared across all interceptors. Key fields:

| Key | Phase | Description |
|-----|-------|-------------|
| `system_prompt` | pre | System prompt text — interceptors append to this |
| `user_message` | pre | The player's message |
| `messages` | pre | Full message list sent to the LLM |
| `reply` | post | The LLM's response text |
| `scene` | both | Current scene name (e.g. `"penthouse"`, `"phone"`) |
| `agent_id` | both | Character ID |
| `agent_name` | both | Character display name |
| `skill_manifest` | pre | `SceneManifest` for available skills |
| `policy` | both | `InteractionPolicy` (tone, length, restrictions) |
| `game_state` | both | Active game state dict |
| `auto_results` | pre | Results from auto-triggered skills |
| `parsed` | post | `ParsedResponse` from `ContentRouter` |
| `abort` | both | Set `True` to stop the pipeline |
| `skip_llm` | pre | Set `True` to bypass the LLM call entirely |
| `extra` | both | Arbitrary pass-through data between interceptors |
| `tts_meta` | post | TTS rendering metadata (emotion, speed, voice) |

---

## Priority Ordering

Interceptors are sorted by `priority` (ascending). **Lower priority runs first.**

- Priorities 5–10: Identity and context setup (mood drift, Nexus, character)
- Priorities 10–20: Message routing, scene state, ambient events
- Priorities 20–40: Skills, game rules, auto-results
- Priorities 50–70: Behavioral guardrails (personality, variety, policy, memory)
- Priorities 80–93: Post-processing (shaping, TTS, logging, state sync)

If an interceptor sets `ctx["abort"] = True`, the pipeline stops — no further
interceptors run.

---

## Complete Interceptor Reference

### Pre-Call Interceptors

These modify `ctx["system_prompt"]` before the LLM sees it.

| Pri | Class | Config Key | Scenes | Purpose |
|-----|-------|------------|--------|---------|
| 5 | `NaturalMoodDriftInterceptor` | — | selective¹ | Apply natural stat drift (arousal cools, tiredness accumulates). Inject inner-thought cues. Sweep expired buffs/tags |
| 6 | `NexusPromptInterceptor` | `nexus_prompt` | all | Inject Nexus KMS knowledge: base prompts, governance rules (global, scene, agent). Cached with 5-min TTL |
| 7 | `ConversationRecapInterceptor` | — | all | Track last 4 exchanges per conversation. Inject recap so agents don't forget recent context |
| 8 | `CharacterRegistryInterceptor` | — | all | Inject character identity (name, mood, personality, skills). Load personality profile from DB. Handle `force_response` directives |
| 10 | `RouterMessageInjector` | `router_message_injector` | all | Drain pending agent-to-agent inbox messages (local + cross-scene). Inject player journey context |
| 12 | `DialogDirectiveInterceptor` | — | all | Inject `must_include`, `style_lock`, `topic_steer`, `mood_set` directives from the DialogSystem |
| 15 | `PenthouseSceneInterceptor` | — | penthouse | Inject wardrobe state, emotional/physical stats, atmosphere, recent narrative |
| 15 | `PhoneSceneInterceptor` | — | phone | Inject conversation heat, vibe hints, stats, narrative context, available MCP actions |
| 15 | `LoungeSceneInterceptor` | — | lounge | Inject trust, heat, stage performance, cocktail menu, back-room access, MCP actions |
| 15 | `GallerySceneInterceptor` | — | gallery | Inject artwork context, exhibition state, mood, narrative, conversation pacing |
| 16 | `UniversalSceneInterceptor` | — | others² | Catch-all for scenes without dedicated interceptors. Inject scene descriptor, mood, narrative, heat, MCP actions |
| 17 | `AmbientEventInterceptor` | — | all | 25% chance per call: inject a random scene-aware micro-event. Anti-repetition tracking per scene |
| 20 | `AutoResultInjector` | `auto_result_injector` | all | Append results from auto-triggered skills into system prompt |
| 30 | `SkillAwarenessInterceptor` | `skill_awareness` | all | Build "available skills" and "required skills" sections so the LLM knows its tools |
| 35 | `GameInterceptor` | `game_rules` | all | Inject active game session state + history. Inject game-specific rules (Truth or Dare, Mystery, etc.) |
| 50 | `PersonalityGuardInterceptor` | `personality_guard` | all | Append in-character reminders: required tone, forbidden topics, custom append text |
| 55 | `ConversationVarietyInterceptor` | — | all | Anti-repetition guidance. Track recent responses. Inject expressiveness cues and conversation heat directives |
| 60 | `PolicyEnforcerInterceptor` | `policy_enforcer` | all | Inject token-budget instruction (min/max reply tokens from `InteractionPolicy`) |
| 70 | `MemoryEnhancerInterceptor` | `memory_enhancer` | all | Extra RAG search on user message. Append top-3 relevant memories. **Disabled by default** |

¹ `NaturalMoodDriftInterceptor` runs in: penthouse, phone, lounge, gallery, arena, casino, heist, realm, neoncity, coders.
² `UniversalSceneInterceptor` skips penthouse, phone, lounge, gallery (which have dedicated interceptors).

### Post-Call Interceptors

These read/modify `ctx["reply"]` after the LLM responds.

| Pri | Class | Config Key | Purpose |
|-----|-------|------------|---------|
| 12 | `DialogDirectiveInterceptor` | — | Enforce `must_include` fragments (append if missing). Tick conversation state and fire consequence chains |
| 35 | `GameInterceptor` | `game_rules` | Log game session events from `ctx["parsed"].game_events` |
| 55 | `ConversationVarietyInterceptor` | — | Track agent reply for future repetition detection. Update conversation heat analysis |
| 80 | `ResponseShaperInterceptor` | `response_shaper` | Strip leaked system prompt sections. Remove LLM token artifacts. Trim excessively long replies |
| 85 | `TTSStyleInterceptor` | — | Attach TTS metadata to `ctx["tts_meta"]`: emotion label, speed multiplier, voice ID, style lock |
| 90 | `ActivityLoggerInterceptor` | `activity_logger` | Log the governed response to `EventChain` with governance metadata |
| 92 | `MoodSyncInterceptor` | — | Parse mood tags from reply. Push mood updates to CharacterRegistry. Fire threshold rules in SceneRulesEngine |
| 93 | `RelationshipEventInterceptor` | — | Detect relationship keywords (kiss, argue, compliment…). Apply temporary stat buffs/debuffs via StateCoordinator. Add behavioral tags |

---

## Registration

### Package Layout

Interceptors live in `engine/agents/interceptors/` — one class per file, 24 interceptor
modules plus 2 infrastructure files:

```
engine/agents/interceptors/
├── __init__.py              ← imports all modules, exports registry
├── cache.py                 ← _InterceptorCache singleton (TTL cache)
├── natural_mood_drift.py    ← NaturalMoodDriftInterceptor     (pri 5)
├── nexus_prompt.py          ← NexusPromptInterceptor          (pri 6)
├── conversation_recap.py    ← ConversationRecapInterceptor    (pri 7)
├── character_registry.py    ← CharacterRegistryInterceptor    (pri 8)
├── router_message.py        ← RouterMessageInjector           (pri 10)
├── dialog_directive.py      ← DialogDirectiveInterceptor      (pri 12)
├── penthouse_scene.py       ← PenthouseSceneInterceptor       (pri 15)
├── phone_scene.py           ← PhoneSceneInterceptor           (pri 15)
├── lounge_scene.py          ← LoungeSceneInterceptor          (pri 15)
├── gallery_scene.py         ← GallerySceneInterceptor         (pri 15)
├── universal_scene.py       ← UniversalSceneInterceptor       (pri 16)
├── ambient_event.py         ← AmbientEventInterceptor         (pri 17)
├── auto_result.py           ← AutoResultInjector              (pri 20)
├── skill_awareness.py       ← SkillAwarenessInterceptor       (pri 30)
├── game.py                  ← GameInterceptor                 (pri 35)
├── personality_guard.py     ← PersonalityGuardInterceptor     (pri 50)
├── conversation_variety.py  ← ConversationVarietyInterceptor  (pri 55)
├── policy_enforcer.py       ← PolicyEnforcerInterceptor       (pri 60)
├── memory_enhancer.py       ← MemoryEnhancerInterceptor       (pri 70)
├── response_shaper.py       ← ResponseShaperInterceptor       (pri 80)
├── tts_style.py             ← TTSStyleInterceptor             (pri 85)
├── activity_logger.py       ← ActivityLoggerInterceptor       (pri 90)
├── mood_sync.py             ← MoodSyncInterceptor             (pri 92)
└── relationship_event.py    ← RelationshipEventInterceptor    (pri 93)
```

### How Interceptors Are Loaded

Every interceptor file decorates its class with `@register_interceptor`. When
`engine.agents.interceptors` is imported, all modules are loaded and every
`@register_interceptor` decorator fires, populating the central registry.
`_build_default_pipeline()` reads the registry to build the pipeline — no
hardcoded list anywhere.

```python
# engine/agents/interceptors/natural_mood_drift.py
from engine.agents.interceptors.base import InterceptorBase, register_interceptor

@register_interceptor
class NaturalMoodDriftInterceptor(InterceptorBase):
    name     = "natural_mood_drift"
    priority = 5
    ...
```

```python
# engine/mcp/comms_framework.py
from engine.agents.interceptors import get_interceptor_registry

def _build_default_pipeline():
    registry = get_interceptor_registry()
    pipeline = InterceptorPipeline()
    for cls in registry.values():
        pipeline.add(cls())   # sorted by priority automatically
    return pipeline

governor = AgentGovernor(agent, scene="phone")
# governor.pipeline contains all 24 interceptors, sorted by priority
```

### Config Toggles

`config/default.yaml` → `comms.interceptors` controls which config-aware
interceptors are enabled:

```yaml
comms:
  governance_enabled: true      # master switch for the entire pipeline
  interceptors:
    nexus_prompt:              true
    router_message_injector:   true
    auto_result_injector:      true
    skill_awareness:           true
    game_rules:                true
    personality_guard:         true
    policy_enforcer:           true
    memory_enhancer:           false   # heavier — opt-in
    response_shaper:           true
    activity_logger:           true
```

> **Note:** Interceptors without a config key (scene interceptors,
> `NaturalMoodDriftInterceptor`, `ConversationRecapInterceptor`,
> `CharacterRegistryInterceptor`, etc.) always run. They self-filter using
> `applicable_scenes`.

### Scene Filtering

Interceptors can declare `applicable_scenes` to limit where they run:

```python
class PenthouseSceneInterceptor(InterceptorBase):
    applicable_scenes = {"penthouse"}   # only runs in penthouse scene
```

When `applicable_scenes` is `None` (the default), the interceptor runs in
every scene. The pipeline checks `ctx["scene"]` against this set before
calling `pre_call`/`post_call`.

---

## Interceptor Cache

Interceptors that produce identical output across calls (character identity,
skill lists, personality reminders) can use the global TTL cache:

```python
from engine.agents.interceptors import INTERCEPTOR_CACHE

# Read (returns None if expired or missing)
cached = INTERCEPTOR_CACHE.get(agent_id, "my_key")

# Write (default TTL: 60 seconds)
INTERCEPTOR_CACHE.set(agent_id, "my_key", computed_value, ttl=120.0)

# Invalidate one key or all keys for an agent
INTERCEPTOR_CACHE.invalidate(agent_id, "my_key")
INTERCEPTOR_CACHE.invalidate(agent_id)           # all keys
```

The cache is thread-safe and keyed by `(agent_id, interceptor_name)`.

---

## Writing a Custom Interceptor

### 1. Create the File

Create a new module in `engine/agents/interceptors/`. One class per file.

```python
# engine/agents/interceptors/weather.py
from engine.agents.interceptors.base import InterceptorBase, register_interceptor

@register_interceptor
class WeatherInterceptor(InterceptorBase):
    """Inject current weather into the scene context."""
    name     = "weather"
    priority = 18                           # after scene interceptors (15–16)
    applicable_scenes = {"realm", "arena"}  # or None for all scenes

    def pre_call(self, ctx):
        weather = self._get_weather(ctx.get("scene", ""))
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n[WEATHER] {weather} [/WEATHER]"
        )

    def post_call(self, ctx):
        pass

    def _get_weather(self, scene):
        return "Heavy rain, low visibility"
```

### 2. Done — Auto-Registered

The `@register_interceptor` decorator adds the class to the global registry.
When `engine.agents.interceptors` is imported (which happens at server startup),
all module files are loaded and all decorated classes are registered.

**No changes required** to `__init__.py`, `comms_framework.py`, or any server
file. The new interceptor appears in every pipeline automatically on next startup.

### 3. Runtime Registration (Optional)

To add an interceptor to a running governor without restarting:

```python
from engine.mcp.comms_framework import get_governor
from engine.agents.interceptors.weather import WeatherInterceptor

gov = get_governor(agent, scene="realm")
gov.pipeline.add(WeatherInterceptor())
```

### 4. Remove an Interceptor

```python
gov.pipeline.remove("weather")     # by name
```

### Key Rules

- **`pre_call(ctx)`** — Append to `ctx["system_prompt"]`. Don't overwrite it.
- **`post_call(ctx)`** — Read/modify `ctx["reply"]`. Write back to `ctx["reply"]`.
- **Priority** — Lower = runs first. Avoid conflicts with existing priorities.
- **Fail gracefully** — Wrap external calls in `try/except`. A failing
  interceptor logs a warning but doesn't crash the pipeline.
- **Scene gating** — Set `applicable_scenes` to restrict to specific scenes.
- **`abort`** — Set `ctx["abort"] = True` to stop the pipeline early.
- **`skip_llm`** — Set `ctx["skip_llm"] = True` and write `ctx["reply"]` to
  bypass the LLM call entirely (used by `CharacterRegistryInterceptor` for
  forced responses).

### Priority Guide

| Range | Purpose | Examples |
|-------|---------|----------|
| 5–10 | Identity, knowledge, mood | MoodDrift, Nexus, Recap, CharacterRegistry |
| 10–20 | Routing, scene context, events | Router, DialogDirective, scene interceptors, Ambient |
| 20–40 | Skills, games, auto-results | AutoResult, SkillAwareness, GameInterceptor |
| 50–70 | Behavioral guardrails | PersonalityGuard, Variety, PolicyEnforcer, Memory |
| 80–93 | Post-processing, logging | ResponseShaper, TTS, Logger, MoodSync, Relationship |

---

## Configuration Reference

### `comms` Section (`config/default.yaml`)

```yaml
comms:
  # Master switch — when false, AgentGovernor.reply() bypasses the pipeline
  governance_enabled: true

  # Path to skill manifests (which skills auto-trigger per scene)
  skill_manifest_path: "config/skill_manifests.yaml"

  # Toggle individual interceptors (true = enabled)
  interceptors:
    nexus_prompt:              true    # Nexus KMS knowledge injection
    router_message_injector:   true    # agent-to-agent message routing
    auto_result_injector:      true    # auto-skill results in prompt
    skill_awareness:           true    # skill list for LLM
    game_rules:                true    # game rules + session state
    personality_guard:         true    # in-character tone enforcement
    policy_enforcer:           true    # reply length constraints
    memory_enhancer:           false   # extra RAG lookup (heavier)
    response_shaper:           true    # post-call reply cleanup
    activity_logger:           true    # EventChain logging

  # Browser overlay stats polling interval
  stats_poll_interval_ms: 2000
```

### Environment Variable Override

```
COSYSIM_GOVERNANCE_ENABLED=false    # disable governance pipeline entirely
```

Mapped via `engine/config.py` → `comms.governance_enabled`.

---

## Debugging

### Dry-Run Context Dump

`AgentGovernor.context_dump()` runs the pre-call pipeline without calling the
LLM, returning the full `ResponseContext` for inspection:

```python
gov = get_governor(agent, scene="penthouse")
ctx = gov.context_dump("Hello there!")
print(ctx["system_prompt"])  # see everything interceptors injected
```

### Pipeline Inspection

```python
gov.pipeline.names
# ['natural_mood_drift', 'nexus_prompt', 'conversation_recap',
#  'character_registry', 'router_messages', 'dialog_directive',
#  'penthouse_scene', 'phone_scene', 'lounge_scene', 'gallery_scene',
#  'universal_scene', 'ambient_events', 'auto_results',
#  'skill_awareness', 'game', 'personality_guard',
#  'conversation_variety', 'policy_enforcer', 'memory_enhancer',
#  'response_shaper', 'tts_style', 'activity_logger',
#  'mood_sync', 'relationship_event']
```

### Logging

All interceptors log at `DEBUG` level via `engine.agents.interceptors`. Set
logging level in `config/default.yaml`:

```yaml
logging:
  level: "DEBUG"
```

---

## Change Log

| Version | Date | Changes |
|---------|------|---------|
| v1.50 | 2026-03-22 | Complete doc overhaul — fixed priority numbers (NexusPrompt 6 not 4, Recap 7 not 6), corrected filenames to match code, accurate count (24 interceptors + 2 infrastructure), unified v1.50 versioning |
| v1.42 | 2026-03-21 | Initial comprehensive interceptor reference |
