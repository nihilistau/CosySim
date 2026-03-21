# MCP Framework

> Model Context Protocol implementation powering agent governance, skill dispatch,
> interceptor pipelines, state management, and character-scene coordination — v1.42+.

The MCP Framework is CosySim's core runtime substrate. Every character
reply flows through this pipeline: skill discovery → pre-call interceptors
→ LLM inference → post-call interceptors → tag extraction → state sync.
The framework manages 178+ skills across 38 packs, 26 interceptor
classes, and 10 singleton subsystems.

---

## Architecture Overview

```
User message
     │
     ▼
┌─────────────────────────┐
│     AgentGovernor       │ ← governance pipeline
│  ┌───────────────────┐  │
│  │ 1. Load Manifest  │  │    SkillManifest per scene
│  │ 2. AUTO Skills    │  │    inject results into context
│  │ 3. Pre-Call       │──┼──▶ InterceptorPipeline (28 classes)
│  │ 4. LLM Inference  │──┼──▶ VirtualAgentManager → LMSClient
│  │ 5. Parse Response │  │    StreamProcessor tag extraction
│  │ 6. Post-Call      │──┼──▶ InterceptorPipeline
│  │ 7. Return Reply   │  │
│  └───────────────────┘  │
└─────────────────────────┘
     │
     ▼
Response + mood + images + stat changes + actions
```

---

## MCPFramework

The root singleton in `engine/mcp/framework.py`. Every scene, character,
timer, and state operation routes through this class.

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
| `get_scene(scene_id)` | Get scene node |
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

| Method | Purpose |
|--------|---------|
| `schedule_consequence(delay, action, context)` | Delayed action |
| `cancel_consequence(consequence_id)` | Cancel scheduled action |
| `get_pending_consequences()` | Upcoming consequences |
| `process_consequences()` | Tick pending consequences |

### State & Events

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

---

## MCPSceneNode

Per-scene state container in `engine/mcp/framework.py`.

### Public Methods

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
| `get_event_history(limit)` | Recent events |
| `get_metadata()` | Scene metadata |

---

## MCPCharacterNode

Per-character state container in `engine/mcp/framework.py`.

### Public Methods

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
| `start_stream()` | Enable streaming |
| `stop_stream()` | Disable streaming |
| `is_streaming()` | Stream status |

---

## MCPTimer

Passive countdown timer with progress tracking.

```python
timer = MCPTimer(
    timer_id="bomb_countdown",
    duration_seconds=300,
    callback=on_timer_expire,
    metadata={"scene": "heist"},
)

timer.progress       # 0.0 → 1.0
timer.remaining_ms   # milliseconds left
timer.is_expired     # bool
```

---

## Skill System

### @skill Decorator

```python
from engine.skills.registry import skill

@skill(
    pack="penthouse",                    # grouping (scene/module name)
    description="LLM-facing desc",    # what the LLM sees
    category="GAME",                   # see categories below
    cooldown=5.0,                      # min seconds between calls
    cost=1.0,                          # budget tracking
    tags=["intimate", "social"],       # free-form tags
    prerequisites=["other_skill"],     # must run first
    nexus_first=False,                 # query Nexus before executing
)
def my_skill(target: str, amount: int = 1) -> str:
    """Brief description for the LLM."""
    return "Result string"
```

### Decorator Parameters

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `name` | `str` | function name | Skill identifier |
| `description` | `str` | docstring | LLM-facing description |
| `pack` | `str` | `""` | Skill grouping |
| `tags` | `List[str]` | `[]` | Discovery tags |
| `category` | `str` | `"GAME"` | Classification |
| `cooldown` | `float` | `0.0` | Min seconds between calls |
| `prerequisites` | `List[str]` | `[]` | Required prior skills |
| `cost` | `float` | `1.0` | Budget tracking |
| `nexus_first` | `bool` | `False` | Query Nexus before executing |

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

### SkillRegistry

Thread-safe singleton in `engine/skills/registry.py`:

```python
from engine.skills.registry import SKILL_REGISTRY

# Registration (automatic at import via @skill)
SKILL_REGISTRY.register(skill_entry)

# Discovery
skills = SKILL_REGISTRY.get_pack("penthouse")        # all penthouse skills
skills = SKILL_REGISTRY.get_by_category("GAME")     # all game skills
skills = SKILL_REGISTRY.get_by_tag("combat")         # tagged skills
skill = SKILL_REGISTRY.get("penthouse.set_mood")       # exact lookup
all_skills = SKILL_REGISTRY.list_all()               # everything
count = SKILL_REGISTRY.count()                        # total count
```

---

## Skill Pack Inventory (45 Packs)

### Scene Skills (20 packs)

| Pack | File | Skills | Scene |
|------|------|--------|-------|
| `penthouse` | `penthouse_skills.py` | 8 | Penthouse (5556) |
| `phone` | `phone_skills.py` | 6 | Phone (5555) |
| `lounge` | `lounge_skills.py` | 7 | Lounge (5557) |
| `tavern` | `tavern_skills.py` | 8 | Tavern (5558) |
| `casino` | `casino_skills.py` | 9 | Casino (5559) |
| `gallery` | `gallery_skills.py` | 6 | Gallery (5560) |
| `arena` | `arena_skills.py` | 10 | Arena (5561) |
| `realm` | `realm_skills.py` | 9 | Realm (5562) |
| `neoncity` | `neoncity_skills.py` | 7 | NeonCity (5563) |
| `coders` | `coders_skills.py` | 8 | Coders (5564) |
| `heist` | `heist_skills.py` | 11 | Heist (5565) |
| `command_center` | `command_center_skills.py` | 5 | Command Center (5566) |
| `games` | `games_skills.py` | 6 | Games (5567) |
| `asset_studio` | `asset_studio_skills.py` | 7 | Asset Studio (5568) |
| `grid` | `grid_skills.py` | 6 | Grid (5569) |
| `nexus_panel` | `nexus_panel_skills.py` | 4 | Nexus Panel (5570) |
| `lab_break` | `lab_break_skills.py` | 9 | Lab Break (5571) |
| `system_control` | `system_control_skills.py` | 5 | System Control (5575) |
| `intel_hub` | `intel_hub_skills.py` | 6 | Intel Hub (5580) |
| `hub` | `hub_skills.py` | 3 | Hub (8500) |

### Engine Skills (25 packs)

| Pack | File | Skills | Purpose |
|------|------|--------|---------|
| `nexus` | `nexus_skills.py` | 17 | Knowledge CRUD, search, Q&A |
| `coding` | `coding_skills.py` | 9 | Code snippets, search, analysis |
| `autonomy` | `autonomy_skills.py` | 67 | System management, governance |
| `copilot` | `copilot_skills.py` | 9 | GitHub Copilot integration |
| `colab` | `colab_skills.py` | 13 | Google Colab integration |
| `memory` | `memory_skills.py` | 6 | RAG vector memory |
| `character` | `character_skills.py` | 8 | Character state, relationships |
| `social` | `social_skills.py` | 5 | Relationships, reputation |
| `world` | `world_skills.py` | 6 | World state, events, time |
| `economy` | `economy_skills.py` | 4 | Credits, market, transactions |
| `city` | `city_skills.py` | 8 | City zones, locations |
| `mission` | `mission_skills.py` | 9 | Quests, objectives |
| `news` | `news_skills.py` | 4 | News pipeline, insights |
| `media` | `media_skills.py` | 5 | Image gen, TTS, video |
| `google_account` | `google_account_skills.py` | 4 | Account pool management |
| `comfyui` | `comfyui_skills.py` | 6 | ComfyUI workflow dispatch |
| `tts` | `tts_skills.py` | 3 | Text-to-speech |
| `faction` | `faction_skills.py` | 5 | Faction standings |
| `lmstudio_server` | `lmstudio_server_skills.py` | 7 | Model lifecycle |
| `inference` | `inference_skills.py` | 5 | Benchmark, delegate |
| `vision` | `vision_skills.py` | 4 | VLM image analysis |
| `evaluation` | `evaluation_skills.py` | 4 | Response quality rating |
| `conversation` | `conversation_skills.py` | 4 | Conversation management |
| `game_common` | `game_common_skills.py` | 5 | Dice, topics, state |
| `training` | `training_skills.py` | 3 | Data collection, flywheel |

---

## Interceptor Pipeline

### InterceptorBase

All interceptors extend `InterceptorBase` in `engine/mcp/comms_framework.py`:

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

### InterceptorPipeline

The pipeline runs all applicable interceptors in priority order:

```python
pipeline = InterceptorPipeline(scene_id="penthouse")
# pre_call: priority 10, 12, 15, ..., 70 (ascending)
request = pipeline.run_pre_call(request, context)
# LLM inference happens here
response = pipeline.run_post_call(response, context)
# post_call: same priority order
```

### Interceptor Inventory (28 Classes)

| # | File | Class | Priority | Scenes | Purpose |
|---|------|-------|----------|--------|---------|
| 1 | `activity_logger.py` | ActivityLogger | 10 | all | Log tool calls to DataCollector |
| 2 | `ambient_event.py` | AmbientEvent | 30 | game | Inject world events into context |
| 3 | `auto_result.py` | AutoResult | 20 | all | Inject AUTO skill results |
| 4 | `penthouse_scene.py` | PenthouseScene | 40 | penthouse | Penthouse-specific logic |
| 5 | `cache.py` | Cache | 5 | all | Response cache v1 |
| 6 | `_cache.py` | CacheV2 | 5 | all | Response cache v2 |
| 7 | `character_registry.py` | CharacterRegistry | 15 | all | Inject character state |
| 8 | `conversation_recap.py` | ConversationRecap | 25 | all | Summarize long conversations |
| 9 | `conversation_variety.py` | ConversationVariety | 55 | all | Detect repetition, inject variety |
| 10 | `dialog_directive.py` | DialogDirective | 12 | all | Enforce response directives |
| 11 | `game.py` | GameInterceptor | 35 | game | Game session mechanics |
| 12 | `gallery_scene.py` | GalleryScene | 40 | gallery | Gallery art context |
| 13 | `lounge_scene.py` | LoungeScene | 40 | lounge | Lounge ambiance |
| 14 | `memory_enhancer.py` | MemoryEnhancer | 18 | all | RAG memory injection |
| 15 | `mood_sync.py` | MoodSync | 60 | all | Sync mood state after reply |
| 16 | `natural_mood_drift.py` | NaturalMoodDrift | 62 | all | Gradual mood decay |
| 17 | `nexus_prompt.py` | NexusPrompt | 22 | all | Inject Nexus knowledge |
| 18 | `personality_guard.py` | PersonalityGuard | 45 | all | Character consistency |
| 19 | `phone_scene.py` | PhoneScene | 40 | phone | Phone message formatting |
| 20 | `policy_enforcer.py` | PolicyEnforcer | 8 | all | InteractionPolicy enforcement |
| 21 | `relationship_context.py` | RelationshipContext | 46 | all | Inject relationship metrics |
| 22 | `relationship_event.py` | RelationshipEvent | 65 | all | Track relationship changes |
| 23 | `response_shaper.py` | ResponseShaper | 70 | all | Format/tone refinement |
| 24 | `router_message.py` | RouterMessage | 50 | all | Cross-scene message routing |
| 25 | `skill_awareness.py` | SkillAwareness | 16 | all | Inject available skills |
| 26 | `tts_style.py` | TTSStyle | 68 | all | TTS style hints |
| 27 | `universal_scene.py` | UniversalScene | 38 | all | Global scene context |
| 28 | `__init__.py` | `get_all_interceptors()` | — | — | Discovery function |

### Pre-Call Flow (System Prompt Building)

```
PolicyEnforcer (8)    → enforce limits, forbidden topics
Cache (5)             → check cache, short-circuit if hit
ActivityLogger (10)   → start timing
DialogDirective (12)  → inject response directives
CharacterRegistry (15)→ inject character state
SkillAwareness (16)   → inject available skills list
MemoryEnhancer (18)   → inject relevant RAG memories
AutoResult (20)       → inject AUTO skill results
NexusPrompt (22)      → inject Nexus knowledge
ConversationRecap (25)→ summarize if history too long
AmbientEvent (30)     → inject world events
GameInterceptor (35)  → inject game session state
UniversalScene (38)   → global context
[Scene]-specific (40) → scene-customized context
PersonalityGuard (45) → character consistency prompt
RelationshipContext(46)→ relationship tier + memories
RouterMessage (50)    → cross-scene messages
```

### Post-Call Flow (Response Processing)

```
ConversationVariety(55)→ detect repetition
MoodSync (60)          → extract [MOOD:x], sync state
NaturalMoodDrift (62)  → decay mood toward neutral
RelationshipEvent (65) → detect relationship changes
TTSStyle (68)          → inject TTS hints
ResponseShaper (70)    → format/tone refinement
```

---

## AgentGovernor

The governance wrapper in `engine/mcp/comms_framework.py` (lines 506–726).

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

#### Full Pipeline Steps:

1. **Load SkillManifest** for the scene
2. **Execute AUTO skills** — results injected into context
3. **Build ResponseContext** — mutable dict passed through pipeline
4. **Run pre-call interceptors** — modify system prompt, inject context
5. **LLM inference** via VirtualAgentManager
6. **Parse response** — StreamProcessor extracts inline tags
7. **Run post-call interceptors** — shape/validate response
8. **Return final reply**

### Public Methods

| Method | Purpose |
|--------|---------|
| `reply(user_message, *, chain_id, history, skip_gov)` | Full governed reply |
| `quick_query(prompt, max_tokens)` | Fast query (bypass governance) |
| `context_dump(user_message)` | Dry-run snapshot (no LLM call) |

### Governance Context

- **SkillManifest** — auto/optional/required skills per scene
- **InteractionPolicy** — token limits, forbidden topics, tone
- **ResponseContext** — mutable dict: system_prompt, messages, reply, metadata

### governance_context Propagation

```
AgentGovernor.reply()
  → CharacterAgent.reply(governance_context=ctx)
    → VirtualAgent.reply(governance_context=ctx)
      → build_request() appends ctx after system prompt
```

Without this propagation, interceptor injections are silently lost.

---

## DialogSystem

Conversation tracking and speech style management in
`engine/mcp/dialog_system.py`.

### Access

```python
from engine.mcp.dialog_system import get_dialog_system

ds = get_dialog_system()
```

### Public Methods

| Method | Purpose |
|--------|---------|
| `start_conversation(scene_id, character_id, user_id)` | Begin tracking |
| `add_turn(conv_id, role, content, metadata)` | Record a turn |
| `get_conversation(conv_id)` | Full conversation state |
| `end_conversation(conv_id, reason)` | Close conversation |
| `get_speech_style(character_id)` | Character's speech patterns |
| `set_response_directive(conv_id, directive)` | Set next-reply directive |

### Conversation Tracking

- Creates a conversation ID per character-user pair
- Tracks: turns, mood progression, topic shifts, directive queue
- Speech styles loaded from character profile
- Response directives consumed once (single-use instructions)

---

## EventChain

Audit logging with typed events in `engine/mcp/event_chain.py`.

### MCP Tools

| Tool | Purpose |
|------|---------|
| `get_chain_events(chain_id, limit)` | Browse event history |
| `log_event(chain_id, event_type, actor, summary, payload, character_id)` | Record event |

### Event Types

- `conversation`, `skill_call`, `state_change`, `scene_event`,
  `relationship`, `economy`, `combat`, `quest`, `system`

### Usage

```python
from engine.mcp.event_chain import get_event_chain

chain = get_event_chain()
chain.log("conv_001", "conversation", actor="lola",
          summary="Greeted the player", payload={"mood": "happy"})
events = chain.get_events("conv_001", limit=20)
```

---

## SceneStateManager

Per-scene, per-character state management in `engine/mcp/scene_state.py`.

### Access

```python
from engine.mcp.scene_state import get_scene_state_manager

ssm = get_scene_state_manager()
```

### STAT_KEYS (0–100 Scale)

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
| `give_clothing(char_id, item)` | Add wearable |
| `remove_clothing(char_id, item_id)` | Strip item |
| `start_timed_action(char_id, action, duration)` | Long-form action timer |
| `poll_timed_action(token)` | Check action status |

### Scene State Methods

| Method | Purpose |
|--------|---------|
| `set_scene_state(scene_id, **kwargs)` | Scene-level state |
| `get_scene_state(scene_id)` | Read scene state |
| `add_narrative(scene_id, text, entry_type, character_id)` | Log narrative event |
| `get_narrative(scene_id, limit)` | Recent narrative events |

### Data Types

**StatsSnapshot:** Named dict of all STAT_KEYS with 0–100 values.

**ClothingItem:**
```python
@dataclass
class ClothingItem:
    item_id: str
    name: str
    category: str       # top, bottom, shoes, accessory, underwear
    color: str
    style: str
    worn: bool = True
```

**CharacterWardrobe:** Ordered clothing inventory with `wear()`, `remove()`, `list_worn()`.

---

## SceneRulesEngine

Centralized governance rules in `engine/mcp/scene_rules_engine.py`.

### Access

```python
from engine.mcp.scene_rules_engine import get_rules_engine

rules = get_rules_engine()
```

### Public Methods

| Method | Purpose |
|--------|---------|
| `get_rules_text(scene_id)` | Full rules for system prompt |
| `get_available_actions(scene_id, character_id, stats)` | Allowed actions |
| `check_permission(scene_id, character_id, action_id)` | Permission check |
| `apply_rule(scene_id, rule_id, target_ids, issuer)` | Execute a rule |

### Data Types

**RuleCondition:** stat/state thresholds (AND logic)

**ActionDefinition:** named action with intimacy requirement, condition, effects

**RuleDefinition:** named rule — `always_on`, `triggered`, or `director_only`

**RuleEffect Types:**
- `stat_adjust` — modify stat by delta
- `state_set` — set state flag
- `add_restriction` / `remove_restriction` — toggle restrictions
- `add_narrative` — log narrative event
- `set_directive` — set response directive
- `scene_event` — emit scene event
- `set_atmosphere` — change scene ambiance

---

## StreamProcessor

Real-time SSE processing in `engine/agents/stream_processor.py`.

### Inline Tag Patterns

| Tag | Example | Extraction |
|-----|---------|------------|
| `[MOOD:X]` | `[MOOD:happy]` | `mood_tags` list |
| `[IMAGE:X]` | `[IMAGE:sunset scene]` | `image_requests` list |
| `[SELFIE:X]` | `[SELFIE:winking]` | `image_requests` list |
| `[ACTION:X]` | `[ACTION:sit down]` | `action_tags` list |
| `[STAT:X±N]` | `[STAT:arousal+10]` | `stat_deltas` list |
| `[VOICE:X]` | `[VOICE:whisper]` | `voice_style` |
| `[SEND:X]` | `[SEND:lola]` | routing target |
| `[EVENT:X]` | `[EVENT:alarm]` | scene event |
| `[MEMORY:X]` | `[MEMORY:user likes coffee]` | memory store |
| `[THINK:X]` | `[THINK:considering options]` | reasoning |

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

### Constructor Callbacks

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
# Generator-based
result = StreamProcessor.process_generator(client.chat_stream(msgs))

# Event-based
processor.on_event(stream_event)   # typed LMSStreamEvent
processor.feed_content(chunk)      # raw content string
result = processor.result()        # final ProcessedResponse
```

---

## VirtualAgent / VirtualAgentManager

### VirtualAgent

Decoupled agent identity in `engine/agents/virtual_agent.py`:

```python
class VirtualAgent:
    def reply(self, user_message: str) -> str:
        """Route through VirtualAgentManager."""

    def quick_query(self, prompt: str, max_tokens: int = 200) -> str:
        """Fast query."""

    def get_state(self) -> Dict[str, Any]:
        """Character local state mirror."""

    def load_state(self) -> None:
        """Restore persisted state."""

    def save_state(self) -> None:
        """Persist state."""
```

### VirtualAgentManager

Centralized inference server in `engine/agents/virtual_agent_manager.py`:

```python
class VirtualAgentManager:
    def create_agent(
        self, character, *, scene=None, model=None, skill_packs=None
    ) -> VirtualAgent:
        """Create and register agent."""

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Single LLM inference (routed)."""

    def infer_batch(self, requests: List[InferenceRequest]) -> List[InferenceResponse]:
        """Parallel inference."""

    def infer_stream(
        self, request: InferenceRequest, on_event=None
    ) -> Generator[str, None, None]:
        """Streaming inference with typed SSE events."""

    def get_stats(self) -> Dict:
        """Request/token/latency stats."""
```

### Inference Flow

```
VirtualAgent.reply()
  → InferenceRequest
    → VirtualAgentManager.infer()
      → ConversationManager (stateful fast-path) or LMSClient.chat()
        → StreamProcessor (if streaming)
          → InferenceResponse
```

---

## CharacterRegistry

Character profile management in `engine/mcp/character_registry.py`.

```python
from engine.mcp.character_registry import get_character_registry

registry = get_character_registry()
character = registry.get("lola")          # by ID
characters = registry.get_by_scene("penthouse")
all_chars = registry.list_all()
```

Characters loaded from `content/characters/` YAML profiles with:
- traits, backstory, speech patterns
- emotional state (12 STAT_KEYS)
- relationships (with other characters)
- inventory, wardrobe
- scene membership

---

## MCP Server (cosysim_server.py)

FastMCP-based server exposing 30+ MCP tools:

### Execution Modes

| Mode | Command | Use Case |
|------|---------|----------|
| stdio | `python -m engine.mcp.cosysim_server` | mcp.json integration |
| HTTP | `python -m engine.mcp.cosysim_server --http` | Direct HTTP |
| Mount | `app.mount("/mcp", mcp.http_app())` | Embedded in Flask |

### MCP Tools (Sample)

| Tool | Purpose |
|------|---------|
| `search_memory(query, character_id, top_k)` | RAG vector search |
| `store_memory(text, character_id, metadata)` | Persist to ChromaDB |
| `get_character_state(character_id)` | Mood, energy, relationships |
| `adjust_relationship(char_a, char_b, field, delta)` | Modify trust/attraction |
| `generate_image_request(prompt, width, height)` | ComfyUI proxy |
| `get_chain_events(chain_id, limit)` | Browse EventChain |
| `log_event(chain_id, event_type, actor, summary)` | Record event |
| `list_characters()` | Character directory |
| `get_my_skills(scene)` | Available skills |
| `roll_dice(sides, count)` | Random outcomes |
| `get_game_state(game_id, key)` | Read game state |
| `set_game_state(game_id, key, value)` | Write game state |
| `start_game(game_id, scene, config_json)` | Initialize game |

### MCP Resources

| Resource URI | Data |
|-------------|------|
| `config://cosysim` | YAML config snapshot |
| `benchmark://summary` | KPI timing |
| `character://{id}` | Full profile + state |
| `chain://{chain_id}` | EventChain tree as JSON |
| `scene://{name}/status` | Scene health |

---

## Singletons Reference

| Singleton | Module | Access |
|-----------|--------|--------|
| `MCPFramework` | `engine/mcp/framework.py` | `get_framework()` |
| `CharacterRegistry` | `engine/mcp/character_registry.py` | `get_character_registry()` |
| `DialogSystem` | `engine/mcp/dialog_system.py` | `get_dialog_system()` |
| `SceneRulesEngine` | `engine/mcp/scene_rules_engine.py` | `get_rules_engine()` |
| `SceneStateManager` | `engine/mcp/scene_state.py` | `get_scene_state_manager()` |
| `SkillRegistry` | `engine/skills/registry.py` | `SKILL_REGISTRY` |
| `SkillManifest` | `engine/mcp/comms_framework.py` | `get_skill_manifest()` |
| `GameState` | `engine/mcp/comms_framework.py` | `get_game_state()` |
| `AgentRouter` | `engine/mcp/comms_framework.py` | `get_router()` |
| `VirtualAgentManager` | `engine/agents/virtual_agent_manager.py` | `get_virtual_agent_manager()` |

---

## Configuration

MCP framework settings in `config/default.yaml`:

```yaml
comms:
  interceptors:
    - PolicyEnforcer
    - Cache
    - ActivityLogger
    - DialogDirective
    - CharacterRegistry
    - SkillAwareness
    - MemoryEnhancer
    - AutoResult
    - NexusPrompt
    - ConversationRecap
    - AmbientEvent
    - GameInterceptor
    - UniversalScene
    - PenthouseScene
    - LoungeScene
    - GalleryScene
    - PhoneScene
    - PersonalityGuard
    - RelationshipContext
    - RouterMessage
    - ConversationVariety
    - MoodSync
    - NaturalMoodDrift
    - RelationshipEvent
    - TTSStyle
    - ResponseShaper
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
| MCP tool files | 43 |
| Builtin skill packs | 45 |
| Interceptor classes | 28 |
| MCPFramework public methods | 40+ |
| Singletons | 10 |
| STAT_KEYS | 12 |
| Inline tag patterns | 10 |
| SSE event types processed | 19 |
| Skill categories | 8 |
