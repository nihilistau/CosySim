# MCP Framework

> CosySim Documentation -- v1.56.0 [2026-03-26]
>
> Skill dispatch, agent governance, state coordination, and the dialog system.

---

## Overview

The MCP Framework is CosySim's core runtime substrate. Every character reply
flows through this pipeline: skill discovery, pre-call interceptors, LLM
inference, post-call interceptors, tag extraction, and state synchronization.

The framework manages approximately 1,040 skills across 99 packs (785 engine
+ 255 scene-level), 36 interceptor classes, 43 MCP tool modules, and 10 key
singletons. Eight skill categories classify all registered abilities:
COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM, and
NARRATIVE.

```
User message
     |
     v
+-----------------------------+
|      AgentGovernor          |   governance pipeline
|  +------------------------+ |
|  | 1. Load Manifest       | |   SkillManifest per scene
|  | 2. AUTO Skills         | |   inject results into context
|  | 3. Pre-Call             |---> InterceptorPipeline (36 classes)
|  | 4. LLM Inference       |---> VirtualAgentManager -> LMSClient
|  | 5. Parse Response      | |   StreamProcessor tag extraction
|  | 6. Post-Call            |---> InterceptorPipeline
|  | 7. Return Reply        | |
|  +------------------------+ |
+-----------------------------+
     |
     v
Response + mood + images + stat changes + actions
```

**See also:** [Architecture](ARCHITECTURE.md) |
[Skills](SKILLS.md) |
[Interceptors](INTERCEPTORS.md) |
[Nexus](NEXUS.md)

---

## State Tree (MCPFramework Singleton)

The root singleton in `engine/mcp/framework.py`. Every scene, character,
timer, and state operation routes through this class. The state tree is a
hierarchical node graph:

```
MCPFramework  (global singleton -- the root)
|
+--- MCPSceneNode  (one per active scene: "penthouse", "phone", ...)
|     +-- local rules (from SceneRulesEngine)
|     +-- present characters  (MCPCharacterNode refs)
|     +-- event subscriptions
|     +-- cross-scene bridge slots
|
+--- MCPCharacterNode  (one per character -- exists independently of scene)
      +-- profile + state  (from CharacterRegistry)
      +-- skill list        (auto / optional / required)
      +-- RAG memory knob
      +-- current_scene ref
      +-- message inbox
```

### Access

```python
from engine.mcp.framework import get_framework

fw = get_framework()
```

### Scene Management

| Method | Purpose |
|--------|---------|
| `get_or_create(path, node_class)` | Get or create scene/character node at path |
| `register_scene(scene_id, node)` | Register a scene node |
| `unregister_scene(scene_id)` | Unregister a scene |
| `get_scene(scene_id)` | Get scene node (auto-created if absent) |
| `list_scenes()` | All registered scenes |
| `get_scene_state(scene_id)` | Scene state dict |

### Character Management

| Method | Purpose |
|--------|---------|
| `register_character(scene_id, character)` | Add character to scene |
| `unregister_character(scene_id, character_id)` | Remove character |
| `get_character(scene_id, character_id)` | Get character node |
| `list_characters(scene_id)` | Characters in scene |
| `move_character(character_id, from_scene, to_scene)` | Cross-scene transfer |

### Timer Management

| Method | Purpose |
|--------|---------|
| `create_timer(timer_id, duration, callback)` | Create countdown timer |
| `cancel_timer(timer_id)` | Cancel running timer |
| `get_timer(timer_id)` | Timer status |
| `list_timers()` | All active timers |

### Scheduled Consequences

Consequences are deferred effects that fire after N conversation turns.
The `DialogDirectiveInterceptor` ticks `MCPFramework.tick_consequences()`
each turn, draining the queue.

| Method | Purpose |
|--------|---------|
| `schedule_consequence(delay, action, context)` | Delayed action |
| `cancel_consequence(consequence_id)` | Cancel scheduled action |
| `get_pending_consequences()` | Upcoming consequences |
| `process_consequences()` | Tick pending consequences |

### State and Events

| Method | Purpose |
|--------|---------|
| `emit_event(event_type, data)` | Broadcast event |
| `on_event(event_type, handler)` | Register event listener |
| `get_state_snapshot()` | Full framework state dump |
| `persist_state()` | Save to disk (if enabled) |
| `load_state()` | Restore from disk |

### Tree Operations

| Method | Purpose |
|--------|---------|
| `resolve(path)` | Navigate MCP node tree by dot-path |
| `tree_dump()` | Full tree as JSON |
| `find_nodes(predicate)` | Search nodes by condition |

### MCPSceneNode

Per-scene state container. Each scene node holds its own characters, rules,
events, and metadata.

| Method | Purpose |
|--------|---------|
| `add_character(character_id, character_data)` | Register character |
| `remove_character(character_id)` | Unregister character |
| `get_character(character_id)` | Get character state |
| `list_characters()` | All characters in scene |
| `set_state(key, value)` | Scene-level state |
| `get_state(key, default)` | Read scene state |
| `get_full_state()` | All scene state |
| `add_rule(rule_id, rule)` | Add scene rule |
| `remove_rule(rule_id)` | Remove scene rule |
| `get_rules()` | Active rules |
| `emit_event(event_type, data)` | Scene-scoped event |
| `on_event(event_type, handler)` | Scene event listener |

### MCPCharacterNode

Per-character state container. Characters exist independently of scenes and
can join or leave scenes dynamically.

| Method | Purpose |
|--------|---------|
| `get_scene_id()` | Current scene |
| `get_scenes()` | All scenes character is in |
| `join_scene(scene_id)` | Add to scene |
| `leave_scene(scene_id)` | Remove from scene |
| `set_state(key, value)` | Character state |
| `get_state(key, default)` | Read state |
| `get_full_state()` | All character state |
| `send_message(target_id, message)` | Cross-scene messaging |
| `get_messages(since)` | Incoming messages |
| `update_stats(stat_deltas)` | Emotional/physical updates |
| `get_stats()` | Current stats |

### MCPTimer

Passive countdown timer with progress tracking:

```python
timer = MCPTimer(
    timer_id="bomb_countdown",
    duration_seconds=300,
    callback=on_timer_expire,
    metadata={"scene": "heist"},
)

timer.progress       # 0.0 -> 1.0
timer.remaining_ms   # milliseconds left
timer.is_expired     # bool
```

---

## Singletons Reference

All singletons are re-exported from `engine/mcp/__init__.py` for convenient
access.

| Singleton | Module | Accessor | Purpose |
|-----------|--------|----------|---------|
| `MCPFramework` | `engine/mcp/framework.py` | `get_framework()` | Root state tree -- scenes, characters, timers, events |
| `CharacterRegistry` | `engine/mcp/character_registry.py` | `get_character_registry()` | Character profiles, traits, relationships |
| `DialogSystem` | `engine/mcp/dialog_system.py` | `get_dialog_system()` | Conversation tracking, speech enhancement, directives |
| `SceneRulesEngine` | `engine/mcp/scene_rules_engine.py` | `get_rules_engine()` | Governance rules -- permissions, actions, effects |
| `SceneStateManager` | `engine/mcp/scene_state.py` | `get_scene_state_manager()` | Per-scene/character stats, wardrobe, narrative log |
| `AgentGovernor` | `engine/mcp/comms_framework.py` | `get_governor()` | Reply pipeline -- budgets, cooldowns, prerequisites |
| `AgentRouter` | `engine/mcp/comms_framework.py` | `get_router()` | Cross-agent message routing |
| `GameState` | `engine/mcp/comms_framework.py` | `get_game_state()` | Thread-safe key-value store for game variables |
| `SkillManifest` | `engine/mcp/comms_framework.py` | `get_skill_manifest()` | Scene-to-skill mapping (auto/optional/required) |
| `KnowledgePipeline` | `engine/nexus/knowledge_pipeline.py` | `get_knowledge_pipeline()` | End-to-end knowledge flow orchestration (Nexus-first inference) |

### Usage Pattern

```python
from engine.mcp import (
    get_framework,
    get_character_registry,
    get_dialog_system,
    get_rules_engine,
    get_scene_state_manager,
    get_governor,
    get_router,
    get_game_state,
    get_skill_manifest,
)

# All return thread-safe singletons
fw = get_framework()
registry = get_character_registry()
ds = get_dialog_system()
```

---

## Skill System Overview

CosySim registers approximately 1,000 skills across 95 packs organized into
8 categories. Skills are registered at import time via the `@skill` decorator
and stored in the global `SKILL_REGISTRY` singleton.

For the complete skill reference -- decorator parameters, pack inventory,
registration API, and authoring guide -- see [Skills](SKILLS.md).

### Quick Reference

```python
from engine.skills.registry import skill

@skill(
    pack="penthouse",
    description="LLM-facing description",
    category="GAME",
    cooldown=5.0,
    cost=1.0,
    tags=["tag"],
    prerequisites=["other_skill"],
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

### Skill Categories

| Category | Purpose |
|----------|---------|
| `COMMUNICATION` | Messaging, speech, social interaction |
| `MEMORY` | Recall, store, search memories |
| `MEDIA` | Image generation, TTS, video |
| `GAME` | Game mechanics, economy, combat |
| `SOCIAL` | Relationships, reputation, factions |
| `ENVIRONMENT` | World state, weather, location |
| `SYSTEM` | Config, admin, infrastructure |
| `NARRATIVE` | Story, quests, world building |

### SkillManifest and Trigger Types

The `SkillManifest` singleton maps scene names to lists of skills with
trigger types that control when each skill executes:

| Trigger | Constant | Behavior |
|---------|----------|----------|
| Auto | `TRIGGER_AUTO` | Executed before the LLM call; result injected into context |
| Optional | `TRIGGER_OPTIONAL` | Offered to the LLM as an available tool (model decides) |
| Required | `TRIGGER_REQUIRED` | LLM MUST call this before replying (enforced by system prompt) |

Manifests are loaded from `config/skill_manifests.yaml` with built-in
defaults for core scenes.

### Registry API

```python
from engine.skills.registry import SKILL_REGISTRY

skills = SKILL_REGISTRY.get_pack_tools("penthouse")  # all penthouse skills
all_skills = SKILL_REGISTRY.all_tools()               # everything
count = SKILL_REGISTRY.count()                         # total count
```

---

## Agent Governance

The `AgentGovernor` in `engine/mcp/comms_framework.py` wraps `CharacterAgent`
with the full governance pipeline. It handles budget tracking, cooldown
enforcement, and prerequisite validation for every agent reply.

### Reply Pipeline

```python
governor = get_governor(agent, scene="penthouse")

response = governor.reply(
    user_message="Hello, how are you?",
    chain_id="conv_001",
    history=previous_messages,
    skip_gov=False,
)
```

#### Pipeline Steps

1. **Load SkillManifest** for the scene
2. **Execute AUTO skills** -- results injected into context
3. **Build ResponseContext** -- mutable dict passed through the pipeline
4. **Run pre-call interceptors** -- modify system prompt, inject context
5. **LLM inference** via VirtualAgentManager
6. **Parse response** -- StreamProcessor extracts inline tags
7. **Run post-call interceptors** -- shape and validate response
8. **Return final reply**

### Governor Methods

| Method | Purpose |
|--------|---------|
| `reply(user_message, *, chain_id, history, skip_gov)` | Full governed reply |
| `quick_query(prompt, max_tokens)` | Fast query (bypass governance) |
| `context_dump(user_message)` | Dry-run snapshot (no LLM call) |

### Governance Building Blocks

**SkillManifest** -- Maps scenes to skill lists with auto/optional/required
trigger types. Determines which skills run before the LLM call and which
are offered as tools.

**InteractionPolicy** -- Per-character/scene rules: max reply length,
forbidden topics, tone constraints, response format.

**ResponseContext** -- Mutable dict that each interceptor reads and writes.
Carries system prompt, messages, reply text, and metadata through the
entire pipeline. Any interceptor can abort the pipeline by setting
`ctx["abort"] = True`.

### Budget Tracking

The AgentGovernor tracks skill invocation costs against per-scene budgets.
Each skill declares a `cost` value (default 1.0) in its `@skill` decorator.
The governor checks the remaining budget before executing optional skills
and logs an event when budget is exhausted.

### Cooldown Enforcement

Skills with a `cooldown` parameter (in seconds) are tracked by the
`COOLDOWN_TRACKER` in `engine/skills/skill.py`. The governor checks
cooldown state before executing any skill and returns a cooldown message
if the skill was called too recently.

### Prerequisite Validation

Skills can declare `prerequisites` -- a list of skill names that must have
been executed in the current conversation before the skill can run. The
governor validates prerequisites before execution and returns a descriptive
error if unmet.

### Governance Context Propagation

```
AgentGovernor.reply()
  -> CharacterAgent.reply(governance_context=ctx)
    -> VirtualAgent.reply(governance_context=ctx)
      -> build_request() appends ctx after system prompt
```

Without this propagation, interceptor injections are silently lost.

---

## Dialog System

Conversation tracking, speech enhancement, and response directive management
in `engine/mcp/dialog_system.py`.

### Access

```python
from engine.mcp.dialog_system import get_dialog_system

ds = get_dialog_system()
```

### Capabilities

**Speech Enhancement** -- Raw LLM text is rewritten through `SpeechEnhancer`
to match the character's voice style (playful, dominant, vulnerable, teasing,
etc.). Style parameters come from `CharacterRegistry`.

**Dialog Option Trees** -- Each scene has a `DialogTree` -- a graph of
situational nodes. When the agent asks for dialog options, the system returns
2-4 context-appropriate choices that match current stats and scene atmosphere.

**Response Directives** -- The Director or scene logic can issue a
`ResponseDirective` that overrides or constrains the next response:
- `force_response` -- LLM is bypassed entirely; directive text is returned
- `must_include` -- LLM reply MUST contain this fragment
- `style_lock` -- enforce a specific speech style for N turns

**Conversation State** -- A per-scene-per-character `ConversationState`
tracks dialog heat (how intimate/charged the conversation is), recent
topics, and any active response directives.

**Memory Coherence** -- The system surfaces "remember when..." hooks from
the character's memory so responses feel consistent with shared history.

### Core Methods

| Method | Purpose |
|--------|---------|
| `start_conversation(scene_id, character_id, user_id)` | Begin tracking |
| `add_turn(conv_id, role, content, metadata)` | Record a turn |
| `get_conversation(conv_id)` | Full conversation state |
| `end_conversation(conv_id, reason)` | Close conversation |
| `get_speech_style(character_id)` | Character's speech patterns |
| `set_response_directive(conv_id, directive)` | Set next-reply directive |
| `get_options(character_id, scene_id, context_tags)` | Get contextual dialog options |
| `enhance_speech(character_id, text, style)` | Apply speech style transform |
| `get_active_directive(character_id, scene_id)` | Resolve active directive |

### Data Types

```python
# SpeechStyle -- enum-like constants for speech transforms
# DialogOption -- one option in a dialog choice set (label + text + tag)
# DialogNode -- a scene situation node with associated options
# DialogTree -- per-scene collection of DialogNodes
# ConversationState -- mutable per-(scene, character) record
# ResponseDirective -- a Director-issued instruction shaping the reply
```

---

## Stream Processing

The `StreamProcessor` in `engine/agents/stream_processor.py` consumes SSE
events from LMStudio inference and produces a rich `ProcessedResponse` with
extracted tags, reasoning content, tool call records, and performance stats.

### Inline Tag Patterns

Characters embed structured tags in their responses. The StreamProcessor
extracts them in real time:

| Tag | Example | Extraction Field |
|-----|---------|------------------|
| `[MOOD:x]` | `[MOOD:happy]` | `mood_tags` list |
| `[IMAGE:prompt]` | `[IMAGE:sunset scene]` | `image_requests` list |
| `[ACTION:x]` | `[ACTION:sit down]` | `action_tags` list |
| `[STAT:name+/-val]` | `[STAT:arousal+10]` | `stat_deltas` list |
| `[VOICE:style]` | `[VOICE:whisper]` | `voice_style` |

Additional routing tags (`[SEND:x]`, `[EVENT:x]`, `[MEMORY:x]`, `[THINK:x]`)
are handled by the `TagRegistry` for extensible processing.

### Two Inference Modes

| Method | Use Case |
|--------|----------|
| `infer_processed()` | Full tag extraction -- returns a `ProcessedResponse` with clean text, extracted tags, tool calls, and stats |
| `infer_stream()` | Raw streaming -- yields content deltas with typed SSE event callbacks |

Use `infer_processed()` for the standard agent reply path where you need
mood, image, action, and stat tag extraction. Use `infer_stream()` when you
only need raw content deltas (e.g., for a streaming UI).

### ProcessedResponse

```python
@dataclass
class ProcessedResponse:
    raw_text: str                     # with tags
    clean_text: str                   # tags stripped
    reasoning_content: str            # chain-of-thought
    mood_tags: List[str]
    image_requests: List[str]
    action_tags: List[str]
    stat_deltas: List[StatDelta]
    voice_style: Optional[str]
    tool_calls: List[ToolCallRecord]
    response_id: str
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    server_tps: float
    time_to_first_token_s: float
    model_load_time_s: float
    latency_ms: float
```

### Streaming Callbacks

```python
processor = StreamProcessor(
    on_delta=lambda chunk: print(chunk, end=""),
    on_tool_call=lambda tc: handle_tool(tc),
    on_mood=lambda mood: update_mood(mood),
    on_image_request=lambda prompt: queue_image(prompt),
    on_action=lambda action: execute_action(action),
    on_stat_delta=lambda sd: apply_stat(sd),
    on_tag=lambda tag_type, value: log_tag(tag_type, value),
)
```

### Usage

```python
# Full tag extraction (preferred)
result = mgr.infer_processed(request, on_delta=print_chunk)
print(result.clean_text)       # text with tags stripped
print(result.mood_tags)        # ["happy"]
print(result.image_requests)   # ["a selfie in the penthouse"]

# Raw streaming
for chunk in mgr.infer_stream(request, on_event=handler):
    print(chunk, end="")
```

---

## Tool Routing

CosySim exposes 43 MCP tool modules in `engine/mcp/tools/`, each decorated
with `@mcp_tool` for registration with the FastMCP server. Tools are the
external interface that LLM agents use to interact with the framework.

### MCP Server

The FastMCP server in `engine/mcp/cosysim_server.py` exposes tools and
resources to LMStudio.

| Mode | Command | Use Case |
|------|---------|----------|
| stdio | `python -m engine.mcp.cosysim_server` | mcp.json integration |
| HTTP | `python -m engine.mcp.cosysim_server --http` | Direct HTTP |
| Mount | `app.mount("/mcp", mcp.http_app())` | Embedded in Flask |

### Tool Modules (43 files)

| Module | Purpose |
|--------|---------|
| `agent.py` | Agent lifecycle and routing |
| `allm.py` | LLM model selection and configuration |
| `backup.py` | State backup and restore |
| `cache_pipeline.py` | Response cache operations |
| `character.py` / `character_tools.py` | Character state and profile access |
| `consequence.py` | Scheduled consequence management |
| `conversation.py` | Conversation history and management |
| `copilot.py` | GitHub Copilot integration |
| `deep_storage.py` | Long-term persistent storage |
| `diagnostics.py` | System health and diagnostics |
| `dialog.py` / `dialog_tools.py` | Dialog tree and directives |
| `event_chain.py` | Audit logging and event browsing |
| `game.py` / `game_tools.py` | Game state and mechanics |
| `governance.py` | Governor and policy management |
| `home_assistant.py` | Home automation integration |
| `interaction.py` | Interaction tracking |
| `knowledge_graph.py` | Knowledge graph queries |
| `lounge.py` | Lounge-specific tools |
| `master_notebook.py` | NotebookLM integration |
| `media.py` / `media_tools.py` | Image generation, TTS, video |
| `memory.py` / `memory_tools.py` | RAG vector search and storage |
| `narrative.py` | Narrative log and story events |
| `news.py` | News pipeline and insights |
| `nexus.py` | Nexus KMS queries |
| `nlm.py` | NLM transport layer |
| `phone_assistant.py` | Phone scene assistant |
| `qa.py` | Question-answering pipeline |
| `review.py` | Response quality review |
| `scene.py` / `scene_tools.py` | Scene state and management |
| `scheduler.py` | Task scheduling |
| `system.py` | System configuration and admin |
| `training.py` | Data collection and fine-tuning |
| `user_profile.py` | User profile management |
| `utility_tools.py` | Dice, topics, general utilities |
| `wardrobe.py` / `wardrobe_tools.py` | Clothing inventory and outfit management |

### MCP Resources

Resources are read-only data endpoints exposed to the LLM:

| Resource URI | Data |
|-------------|------|
| `config://cosysim` | YAML config snapshot |
| `benchmark://summary` | KPI timing |
| `character://{id}` | Full profile + state |
| `chain://{chain_id}` | EventChain tree as JSON |
| `scene://{name}/status` | Scene health |

---

## Interceptor Pipeline Overview

The interceptor pipeline modifies every agent request (pre-call) and response
(post-call). Interceptors run in priority order -- lower priority numbers
execute first.

For the complete interceptor reference -- class details, configuration, and
authoring guide -- see [Interceptors](INTERCEPTORS.md).

### InterceptorBase

All 36 interceptors extend `InterceptorBase` in
`engine/mcp/comms_framework.py`:

```python
class InterceptorBase:
    priority: int = 50               # lower = runs first
    applicable_scenes: List[str]     # empty = all scenes
    name: str                        # display name

    def pre_call(self, request: Dict, context: ResponseContext) -> Dict:
        """Modify request before LLM call."""
        return request

    def post_call(self, response: str, context: ResponseContext) -> str:
        """Modify response after LLM call."""
        return response
```

### Pipeline Execution

```python
pipeline = InterceptorPipeline(scene_id="penthouse")

# Pre-call: ascending priority order
request = pipeline.run_pre_call(request, context)

# LLM inference happens here

# Post-call: same priority order
response = pipeline.run_post_call(response, context)
```

### Priority Map

The pipeline runs interceptors in two phases. The priority assignments from
`config/default.yaml` determine execution order:

**Pre-call (system prompt building):**

```
Pri  4  -> NexusPrompt          context hydration from Nexus KMS
Pri  5  -> NaturalMoodDrift     neurochemistry tagging
Pri  8  -> PolicyEnforcer       enforce limits, forbidden topics
Pri 10  -> ActivityLogger       start timing
Pri 12  -> DialogDirective      inject response directives
Pri 15  -> CharacterRegistry    inject character state
Pri 16  -> SkillAwareness       inject available skills list
Pri 18  -> MemoryEnhancer       inject relevant RAG memories
Pri 20  -> AutoResult           inject AUTO skill results
Pri 22  -> NexusPrompt          inject Nexus knowledge
Pri 25  -> ConversationRecap    summarize if history too long
Pri 30  -> AmbientEvent         inject world events
Pri 35  -> GameInterceptor      inject game session state
Pri 38  -> UniversalScene       global context
Pri 40  -> [Scene]-specific     scene-customized context
Pri 45  -> PersonalityGuard     character consistency prompt
Pri 46  -> RelationshipContext  relationship tier + memories
Pri 50  -> RouterMessage        cross-scene messages
```

**Post-call (response processing):**

```
Pri 55  -> ConversationVariety  detect repetition
Pri 60  -> MoodSync             extract [MOOD:x], sync state
Pri 62  -> NaturalMoodDrift     decay mood toward neutral
Pri 65  -> RelationshipEvent    detect relationship changes
Pri 68  -> TTSStyle             inject TTS hints
Pri 70  -> ResponseShaper       format/tone refinement
```

### Interceptor Inventory (36 classes)

Located in `engine/agents/interceptors/`:

| Class | Priority | Scenes | Purpose |
|-------|----------|--------|---------|
| `ActivityLogger` | 10 | all | Log tool calls to DataCollector |
| `AmbientEvent` | 30 | game | Inject world events into context |
| `AutoResult` | 20 | all | Inject AUTO skill results |
| `Cache` | 5 | all | Response cache |
| `CharacterRegistry` | 15 | all | Inject character state |
| `ConversationRecap` | 25 | all | Summarize long conversations |
| `ConversationVariety` | 55 | all | Detect repetition, inject variety |
| `DialogDirective` | 12 | all | Enforce response directives |
| `GalleryScene` | 40 | gallery | Gallery art context |
| `GameInterceptor` | 35 | game | Game session mechanics |
| `LoungeScene` | 40 | lounge | Lounge ambiance |
| `MemoryEnhancer` | 18 | all | RAG memory injection |
| `MoodSync` | 60 | all | Sync mood state after reply |
| `NaturalMoodDrift` | 62 | all | Gradual mood decay |
| `NexusPrompt` | 22 | all | Inject Nexus knowledge |
| `PenthouseScene` | 40 | penthouse | Penthouse-specific logic |
| `PersonalityGuard` | 45 | all | Character consistency |
| `PhoneScene` | 40 | phone | Phone message formatting |
| `PolicyEnforcer` | 8 | all | InteractionPolicy enforcement |
| `RelationshipContext` | 46 | all | Inject relationship metrics |
| `RelationshipEvent` | 65 | all | Track relationship changes |
| `ResponseShaper` | 70 | all | Format/tone refinement |
| `RouterMessage` | 50 | all | Cross-scene message routing |
| `SkillAwareness` | 16 | all | Inject available skills |
| `TTSStyle` | 68 | all | TTS style hints |
| `UniversalScene` | 38 | all | Global scene context |

---

## Scene State Management

The `SceneStateManager` singleton in `engine/mcp/scene_state.py` provides
per-scene and per-character state that persists across hot-reloads.

### STAT_KEYS (0-100 Scale)

```python
STAT_KEYS = [
    "arousal", "horniness", "pleasure", "happiness",
    "anger", "fear", "drunkenness", "tiredness",
    "explicitness", "openness", "affection", "dominance",
]
```

### Character State Methods

| Method | Purpose |
|--------|---------|
| `update_stats(char_id, **kwargs)` | Adjust emotional/physical stats |
| `get_stats(char_id)` | Get StatsSnapshot |
| `give_clothing(char_id, item)` | Add wearable item |
| `remove_clothing(char_id, item_id)` | Remove item |
| `start_timed_action(char_id, action, duration)` | Long-form action timer |
| `poll_timed_action(token)` | Check action status |

### Scene State Methods

| Method | Purpose |
|--------|---------|
| `set_scene_state(scene_id, **kwargs)` | Scene-level state |
| `get_scene_state(scene_id)` | Read scene state |
| `add_narrative(scene_id, text, entry_type, character_id)` | Log narrative event |
| `get_narrative(scene_id, limit)` | Recent narrative events |

---

## Scene Rules Engine

The `SceneRulesEngine` in `engine/mcp/scene_rules_engine.py` centralizes
governance rules that define what is allowed, required, triggered, or
forbidden in each scene.

### Access

```python
from engine.mcp.scene_rules_engine import get_rules_engine

rules = get_rules_engine()
```

### Core Methods

| Method | Purpose |
|--------|---------|
| `get_rules_text(scene_id)` | Full rules for system prompt injection |
| `get_available_actions(scene_id, character_id, stats)` | Allowed actions |
| `check_permission(scene_id, character_id, action_id)` | Permission check |
| `apply_rule(scene_id, rule_id, target_ids, issuer)` | Execute a rule |

### Rule Concepts

**RuleCondition** -- Stat/state thresholds with AND logic.

**ActionDefinition** -- Named action with intimacy requirement, condition,
and effects.

**RuleDefinition** -- Named rule: `always_on`, `triggered`, or
`director_only`.

**RuleEffect types:**
- `stat_adjust` -- modify stat by delta
- `state_set` -- set state flag
- `add_restriction` / `remove_restriction` -- toggle restrictions
- `add_narrative` -- log narrative event
- `set_directive` -- set response directive
- `scene_event` -- emit scene event
- `set_atmosphere` -- change scene ambiance

---

## State Synchronization

State flows between subsystems through well-defined synchronization points.

### Cross-Scene Communication

Characters in different scenes communicate through the `CrossSceneBridge`
managed by MCPFramework:

```python
fw.cross_scene_send(
    from_char="user", from_scene="phone",
    to_char="aria",   to_scene="penthouse",
    message="Hey, thinking about you.",
    message_type="text",
)
```

Use cases: phone calls between scenes, message notifications arriving
mid-conversation, director events spanning multiple scenes.

### Agent Router

The `AgentRouter` singleton routes messages between named agents:

```python
router = get_router()
router.send("char-aria", "Your friend just called.")
```

### Game State

The `GameState` singleton provides a thread-safe key-value store shared
across all governors:

```python
gs = get_game_state()
gs.set("tod_game", "dare_count", 3)
value = gs.get("tod_game", "dare_count")
```

### Character Registry

Character profiles are loaded from `content/characters/` YAML files and
managed by `CharacterRegistry`:

```python
registry = get_character_registry()
character = registry.get("lola")
characters = registry.get_by_scene("penthouse")
```

Each character profile includes: traits, backstory, speech patterns,
emotional state (12 STAT_KEYS), relationships, inventory, wardrobe, and
scene membership.

### State Persistence

The framework persists its state tree to `data/mcp_state.json` when
`mcp.state_persistence` is enabled in `config/default.yaml`.

### Configuration

MCP framework settings in `config/default.yaml`:

```yaml
comms:
  interceptors:
    - PolicyEnforcer
    - Cache
    - ActivityLogger
    # ... (36 total, loaded in priority order)
  pipeline:
    max_interceptors: 30
    timeout_per_interceptor_ms: 5000

mcp:
  state_persistence: true
  state_file: "data/mcp_state.json"
  timer_tick_ms: 1000
  consequence_tick_ms: 5000
```

---

## Metrics Summary

| Metric | Value |
|--------|-------|
| Total skills | ~1,040 across 99 packs |
| Engine skills | ~785 |
| Scene skills | ~255 |
| Skill categories | 8 |
| MCP tool modules | 43 |
| Interceptor classes | 36 |
| Key singletons | 10 |
| STAT_KEYS | 12 |
| Inline tag patterns | 5 core + extensible via TagRegistry |
| Stream tag types | [MOOD], [IMAGE], [ACTION], [STAT], [VOICE] |

---

## Change Log

```
v1.56.0 [2026-03-26] - Updated counts: 36 interceptors, ~1,040 skills across
                       99 packs, 10 singletons. Added KnowledgePipeline to
                       singletons reference.
v1.50 [2026-03-22]  - Complete rewrite: accurate skill counts (~1,000 across
                       95 packs), corrected interceptor count (26), updated
                       singletons table (9 accessors), added AgentGovernor
                       budget/cooldown/prerequisite documentation, streamlined
                       from ~30K to ~20K, fixed cross-references
v1.42 [2026-03-21]  - Initial comprehensive MCP Framework reference
```
