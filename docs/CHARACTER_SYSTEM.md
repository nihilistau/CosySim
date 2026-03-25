# Character System

> CosySim Documentation — v1.51.0 [2026-03-25]
>
> Consolidated reference for character identity, stats, memory, reputation, player profile,
> relationships, and the interceptor pipeline. Covers ~1,000 skills across 95 packs,
> 24 interceptors, 32 launch targets, and the three-pillar architecture.

---

## Architecture

The character system spans six subsystems:

| Subsystem | Module | Responsibility |
|-----------|--------|----------------|
| Identity | `CharacterRegistry` | Profile, state, skills, restrictions |
| Stats | `SceneStateManager` | Emotion stats (arousal, trust, anger, etc.) |
| Coordination | `CharacterStateCoordinator` | Unified write-through to all stores |
| Memory | `CharacterMemory` | Persistent cross-session memory via Nexus |
| Reputation | `ReputationManager` | Player standing per character/faction |
| Player | `PlayerProfile` | Persistent player identity and NPC relationships |

```
engine/mcp/character_registry.py     — profiles, skills, state
engine/mcp/state_coordinator.py      — unified update API, buffs, tags
engine/mcp/tag_registry.py           — inline [TAG:value] system
engine/agents/interceptors.py        — interceptor pipeline
engine/characters/memory.py          — CharacterMemory, CharacterMemoryInterceptor
engine/characters/reputation.py      — ReputationManager, ReputationInterceptor
engine/characters/player_profile.py  — PlayerProfile, RelationshipEntry
content/simulation/database/db.py    — persistence + seed data
content/simulation/character_system/ — Character class, PersonalityTemplate
```

---

## Character Registry

### Singleton

```python
from engine.mcp.character_registry import get_character_registry
reg = get_character_registry()
```

### Data Model

```
CharacterRecord
├── CharacterProfile  (immutable identity)
│   ├── character_id, name, age
│   ├── appearance: Dict[str, Any]
│   ├── personality: Dict[str, float]
│   ├── backstory, voice_style, voice_id
│   ├── pronouns, scene_roles
│   └── created_at
├── CharacterState  (mutable runtime)
│   ├── mood, mood_intensity
│   ├── focus, current_role
│   ├── energy, inhibition
│   ├── restrictions: Set[str]
│   ├── flags: Dict[str, Any]
│   └── last_updated
└── skills: Dict[str, SkillEntry]
    └── skill_id, skill_type, label, params, enabled, trigger, priority
```

### Key Methods

```python
# Registration
reg.register("aria", name="Aria", age=26, personality={...}, backstory="...")
reg.ensure("aria")                          # auto-creates stub if missing

# Profile queries
reg.get_profile("aria")                     # CharacterProfile
reg.get_attribute("aria", "eyes")           # flat lookup into appearance/profile
reg.list_characters(scene_role="lounge")    # filter by scene

# State
reg.get_state("aria")                       # dict snapshot
reg.set_state("aria", mood="excited", mood_intensity=0.8)
reg.add_restriction("aria", "refuse_explicit")
reg.remove_restriction("aria", "refuse_explicit")
reg.get_restrictions("aria")                # Set[str]

# Skills
reg.assign_skill("aria", "memory_recall", skill_type="memory_recall", params={...})
reg.revoke_skill("aria", "memory_recall")
reg.toggle_skill("aria", "memory_recall", enabled=False)
reg.get_skills("aria", trigger="auto", enabled_only=True)
reg.has_skill("aria", "memory_recall")

# Full record
reg.get_record("aria")                      # CharacterRecord
reg.get_character_summary("aria")           # compact dict for LLM injection

# Persistence
reg.persist_to_db("aria")                   # write to database
reg.load_from_dict("aria", yaml_data)       # hydrate from config
```

### Skill Types

| Type | Description |
|------|-------------|
| `memory_recall` | RAG-backed consistent memory |
| `speech_enhance` | Stylistic voice transformation |
| `dialog_choices` | Guided response options from DialogSystem |
| `web_lookup` | Realtime information via web search |
| `image_gen` | ComfyUI image generation |
| `mood_influence` | Passive mood drift / aura effect |
| `personality_lock` | Enforce personality constraints at post-call |
| `custom` | Arbitrary, payload-defined behaviour |

### Default Skills (all characters)

1. `memory_recall` — auto, priority 10 (top_k=5, min_score=0.3)
2. `speech_enhance` — auto, priority 20 (default_style=natural)
3. `check_restrictions` — auto, priority 5 (personality_lock type)
4. `get_dialog_options` — optional, priority 30 (max 4 options)
5. `web_lookup` — optional, priority 60 (max 3 results)

---

## Character Stats

### Registry Fields (CharacterState)

| Stat | Range | Description |
|------|-------|-------------|
| `mood` | string | Current emotional label |
| `mood_intensity` | 0.0–1.0 | Strength of current mood |
| `energy` | 0–100 | Physical/mental energy |
| `inhibition` | 0–100 | Restraint level (0=uninhibited, 100=guarded) |
| `focus` | string | Current focus target |
| `current_role` | string | Active role in scene |

### SSM Stats (SceneStateManager)

| Stat | Range | Description |
|------|-------|-------------|
| `arousal` | 0–100 | Excitement / sexual tension |
| `happiness` | 0–100 | General contentment |
| `anger` | 0–100 | Frustration / hostility |
| `fear` | 0–100 | Anxiety / dread |
| `tiredness` | 0–100 | Fatigue level |
| `drunkenness` | 0–100 | Intoxication |
| `affection` | 0–100 | Warmth toward another character |
| `trust` | 0–100 | Per-relationship trust level |
| `attraction` | 0–100 | Per-relationship attraction score |
| `dominance` | 0–100 | Assertiveness in interactions |
| `openness` | 0–100 | Willingness to be vulnerable |
| `explicitness` | 0–100 | Comfort with explicit content |
| `pleasure` | 0–100 | Current physical/emotional pleasure |
| `relationship` | 0–100 | Overall relationship level |
| `warmth` | 0–100 | Emotional closeness |
| `comfort` | 0–100 | Sense of safety and ease |
| `compliance` | 0–100 | Readiness to follow suggestions |
| `horniness` | 0–100 | Desire for sexual activity |
| `sanity` | 0–100 | Grip on reality (realm scene) |
| `heat` | 0–100 | Scene atmosphere temperature |

Not all scenes expose all stats. Each scene defines its own subset.

### Stat Seeding

When a character is created from a `PersonalityTemplate`, personality trait floats (0.0–1.0) are scaled to 0–100 and used as initial stat values.

---

## Personality System

### Personality Vector

Each `CharacterProfile` contains trait scores from 0.0 to 1.0:
`warmth`, `curiosity`, `assertiveness`, `playfulness`, `empathy`, `dominance`, `vulnerability`, `wit`, `sensuality`, `openness`, `humor`, `flirtiness`, `intelligence`, `creativity`, `formality`

### PersonalityTemplate

Defined as dataclasses in `content/simulation/character_system/personality.py`:

- `system_prompt` — base LLM system prompt
- `traits` — list of personality adjectives
- `communication_style` — `{tone, emoji_usage, humor, directness}`
- `sexual_openness` — float 0.0–1.0

### Communication Style

| Field | Values | Effect |
|-------|--------|--------|
| `tone` | `"casual"`, `"warm"`, `"dominant"`, `"cryptic"`, `"formal"` | Register |
| `emoji_usage` | `"high"`, `"medium"`, `"low"`, `"none"` | Emoji frequency |
| `humor` | `"playful"`, `"dry"`, `"dark"`, `"none"` | Joke style |
| `directness` | `"high"`, `"medium"`, `"low"` | How directly needs are expressed |

### Built-in Templates

| Template ID | Description |
|-------------|-------------|
| `playful_girlfriend` | Warm, teasing, high emoji, confident; openness 0.7 |
| `sweet_girlfriend` | Nurturing, empathetic, romantic, low-medium openness |
| `dominant_mistress` | Commanding, assertive, scene-appropriate authority |
| `mysterious_stranger` | Cryptic, minimalist, high intrigue |
| `intellectual_companion` | High intelligence/creativity, low formality |

---

## Simulation Layer

### Character Class

`content/simulation/character_system/character.py` — static definition loaded from SQLite, instantiated at scene start.

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique identifier |
| `name` | `str` | Display name |
| `age` | `int` | Age in years |
| `sex` | `str` | Gender/sex descriptor |
| `hair_color` | `str` | Hair colour |
| `eye_color` | `str` | Eye colour |
| `height` | `str` | Height description |
| `body_type` | `str` | Body type descriptor |
| `description` | `str` | Free-text appearance note |

Computed property `appearance` returns a comma-joined description suitable for image generation prompts.

On init, the `Character` auto-registers with `CharacterRegistry` (MCP).

### Default Characters

Five characters seeded by `Database.seed_default_characters()`:

| ID | Name | Age | Sex | Appearance | Tags |
|----|------|-----|-----|------------|------|
| `lola` | Lola Voss | 29 | F | Dark brunette, deep brown eyes, 5'6 | lounge, singer |
| `viktor` | Viktor Marlowe | 38 | M | Dark hair with grey, pale grey eyes, 6'2 | lounge, bartender |
| `aria` | Aria | 22 | F | Platinum blonde, blue eyes, 5'4 | phone, companion |
| `frankie` | Frankie DeLuca | 45 | M | Slicked black hair, dark eyes, 5'11 | casino, dealer |
| `mira` | Mira Vex | 28 | F | Red hair, green eyes, 5'7 | casino, hustler |

Each gets a seeded `character_states` row with baseline trait scores (warmth, formality, humor, flirtiness, intelligence, creativity all at 0.5).

---

## State Coordinator

The `CharacterStateCoordinator` is the single write-through API for all character state mutations.

```python
from engine.mcp.state_coordinator import get_coordinator
coord = get_coordinator()

# Delta mode (default)
coord.update("lola", mood="flirty", arousal=+10, energy=-5)

# Absolute mode
coord.update("lola", arousal=50, mode="set")

# Unified snapshot
state = coord.get_full_state("lola")

# Single field
energy = coord.get_field("lola", "energy", default=80.0)
```

### Field Routing

```
coord.update(char_id, **fields)
├── Registry fields (mood, mood_intensity, focus, current_role, energy, inhibition)
│   → CharacterRegistry.set_state()
├── Stats fields (arousal, happiness, anger, fear, trust, attraction, etc.)
│   → SceneStateManager.update_stats() or set_stats()
├── Restriction ops (add_restriction, remove_restriction)
│   → CharacterRegistry.add/remove_restriction()
├── Unknown fields → Registry flags
├── ActivityBus → emit("state_changed", {char_id, changes, snapshot})
└── DB persist → Database.update_character() (if persist=True)
```

### Attraction Model

```python
score = coord.calculate_attraction("lola", "aria")  # 0–100
```

Factors: affection (+-20), trust (+-15), mood alignment (+-5), relationship level (+-10), baseline 50.

---

## Behavioral Tags

Tags are soft labels reflecting accumulated behavior patterns. They emerge from interactions and shape future personality.

### Mechanics

| Property | Value |
|----------|-------|
| Strength range | 0.0–1.0 |
| Default decay rate | 0.01 per drift tick |
| Reinforcement | Adds `strength x 0.5` (diminishing returns) |
| Permanence | After 5 reinforcements at max strength, decay drops to 0 |
| Sweep | Dead tags (strength <= 0) removed each drift tick |

### Tag Flow

1. **Creation** — `RelationshipEventInterceptor` detects keywords in agent replies and maps them to tags via 20 keyword-to-tag mappings (e.g., `cuddle/hug/caress` -> `affectionate`, `kiss` -> `romantic`, `flirt/wink` -> `flirtatious`, `argue` -> `confrontational`, `insult` -> `hostile`).

2. **Storage** — Tags live in `CharacterStateCoordinator._tags` (character_id -> {tag -> info dict}).

3. **Injection** — `CharacterRegistryInterceptor` reads the top 5 strongest tags and injects them into the `[CHARACTER IDENTITY]` prompt block. Permanent tags are labeled `(core)`.

4. **Decay** — `NaturalMoodDriftInterceptor` calls `coord.sweep_all_tags()` on every tick.

### API

```python
coord.add_tag("lola", "flirtatious", strength=0.15)
coord.get_tags("lola", min_strength=0.1)
coord.get_top_tags("lola", n=5)
coord.get_permanent_tags("lola")
coord.decay_tags("lola")
```

---

## Relationship Buffs

Buffs are temporary stat modifiers applied when relationship-significant events are detected in agent replies.

| Property | Value |
|----------|-------|
| Duration | 60–600 seconds (varies by event type) |
| Application | Stat deltas applied immediately via `coord.update()` |
| Expiry | Reversed cleanly when timer expires |
| Cooldown | 10 seconds per buff type per agent |
| Sweep | `coord.sweep_all_expired_buffs()` runs on every drift tick |

### Buff Definitions

**Affectionate:** cuddle (+aff8, +aro3, +tru2, 300s), hug (+aff5, +tru2, 180s), kiss (+aff10, +aro8, +tru3, 240s), caress (+aff6, +aro10, 200s), massage (+aro12, +aff4, 300s)

**Intimate:** moan (+aro15, +aff5, 180s), orgasm (+aro20, +aff12, +tru5, 300s), thrust (+aro18, +aff3, 180s), lick (+aro14, +aff4, 180s), suck (+aro16, +aff3, 180s), penetrat (+aro20, +aff5, +tru3, 240s), ride (+aro18, +aff5, 200s), spank (+aro12, -aff2, 120s)

**Social:** compliment (+aff4, +tru3, 120s), laugh (+aff3, 90s), flirt (+aro5, +aff4, 120s), tease (+aro4, +aff2, 90s), wink (+aro3, +aff2, 60s)

**Negative:** argue (-aff6, -tru4, +ang10, 300s), insult (-aff10, -tru8, +ang15, 600s), yell (-aff5, -tru3, +ang12, 240s), cry (+aff3, +tru2, 180s), apologize (+aff4, +tru5, -ang8, 300s)

### API

```python
coord.add_buff("lola", "warmth_123", {"affection": 8, "trust": 2}, duration_secs=300)
coord.get_active_buffs("lola")
coord.remove_expired_buffs("lola")
coord.sweep_all_expired_buffs()
```

---

## Conversation Heat

A 0–100 scale tracking conversation intensity per character x scene.

| Range | Level | Directive |
|-------|-------|-----------|
| 0–29 | Cold | No special directives |
| 30–59 | Warm | Flirty, playful energy; innuendo and light teasing |
| 60–79 | Hot | Explicit/suggestive content; escalation encouraged |
| 80–100 | Intense | Full adult content; raw emotion and desire |

Time-based decay: 2.0 per minute (after 30s idle). Keyword bump cap: 25 per message.

### API

```python
from engine.mcp.scene_rules_engine import get_conversation_heat
heat = get_conversation_heat()

heat.bump("phone_aria_thread1", 10, "flirt")
heat.get("phone_aria_thread1")
heat.analyze_message("phone_aria_thread1", msg)
heat.get_directive("phone_aria_thread1")
heat.cool_all()
```

---

## Natural Mood Drift

`NaturalMoodDriftInterceptor` (priority 5) applies small stat drifts toward baseline each tick.

| Stat | Rate | Direction |
|------|------|-----------|
| arousal | -1.0 | Cools toward baseline |
| tiredness | +0.5 | Accumulates |
| happiness | -0.3 | Regresses to mean |
| anger | -1.5 | Fades |
| fear | -1.0 | Dissipates |
| drunkenness | -0.5 | Sobers up |
| affection | -0.2 | Barely drifts |

Drift applies only when stats are outside neutral zone (below 45 or above 55), except tiredness (always accumulates up to 90).

Inner-thought injection based on stat levels (e.g., arousal > 70 -> "You feel the intensity fading...").

Piggyback operations per tick: sweep expired buffs, decay behavioral tags.

---

## CharacterMemory

`engine/characters/memory.py` — persistent, cross-session memory per character. Stored in Nexus with `content_type="memory"`.

### MemoryEntry

```python
@dataclass
class MemoryEntry:
    id: str                # UUID
    character_id: str
    player_id: str
    content: str           # natural-language description
    emotional_weight: float # 0.0 (trivial) to 1.0 (unforgettable)
    scene: str
    created_at: str        # ISO-8601 UTC
    accessed_at: str       # updated on every recall
    access_count: int
    tags: List[str]
```

### API

```python
from engine.characters.memory import get_character_memory
mem = get_character_memory("lola")

entry = mem.remember("Player asked Lola to wear the red dress",
    player_id="player", emotional_weight=0.8, scene="penthouse", tags=["wardrobe"])
memories = mem.recall("what did the player ask about clothes", player_id="player", limit=5)
recent = mem.recall_recent(player_id="player", limit=10)
summary = mem.get_memory_summary(player_id="player")
prose = mem.summarize(player_id="player")       # NLM-generated
deleted = mem.forget_old(days=30, player_id="player")
mem.forget_entry(entry_id="uuid-here")
```

### Recall Algorithm

1. Nexus semantic search for context (up to `limit x 4` candidates)
2. Filter to `character_id` and `player_id`
3. Score: `relevance = (1.0 / (rank + 1)) x (0.5 + 0.5 x emotional_weight)`
4. Sort descending, return top `limit`; bump `access_count`

### Nexus Storage Layout

```
content_type = "memory"
category     = "character_memory:{character_id}"
title        = "memory:{character_id}:{entry_id}"
content      = JSON-serialised MemoryEntry
tags         = [entry.tags..., "player:{player_id}", "character:{character_id}"]
```

---

## ReputationManager

`engine/characters/reputation.py` — tracks player standing per character/faction. Persists in Nexus.

### Standing Scale

| Range | Label | Behaviour |
|-------|-------|-----------|
| 81–100 | Revered | Deeply loyal |
| 61–80 | Trusted | Warm, open |
| 41–60 | Friendly | Cooperative |
| 21–40 | Neutral | Polite |
| -20–20 | Indifferent | No strong feelings |
| -40 to -21 | Cold | Guarded, curt |
| -60 to -41 | Hostile | Distrustful |
| -80 to -61 | Enemy | Dismissive |
| -100 to -81 | Nemesis | Openly hostile |

### ReputationEntry

```python
@dataclass
class ReputationEntry:
    entity_id: str       # character ID or FactionId
    entity_type: str     # "character" or "faction"
    player_id: str
    standing: int        # clamped to [-100, 100]
    label: str           # computed tier label
    history: List[str]   # last 10 change notes
    last_updated: str
```

### API

```python
from engine.characters.reputation import get_reputation_manager
mgr = get_reputation_manager()

entry = mgr.adjust("mira", delta=-30, reason="player betrayed Mira")
mgr.set_standing("mira", standing=50, reason="player helped Mira escape")
mgr.get_prompt_context("mira")          # prompt-ready string
mgr.get_faction_standings()             # Dict[str, ReputationEntry]
mgr.apply_cross_scene_ripple("casino", "debt_created", delta=-1)
```

### Cross-Scene Ripple Map

```python
_RIPPLE_MAP = {
    ("casino", "debt_created"):   [(FactionId.SYNDICATE, -10), ("mira", -5)],
    ("heist",  "job_complete"):   [(FactionId.UNDERGROUND, +15)],
    ("arena",  "bet_win"):        [(FactionId.ARENA_GUILD, +10)],
    ("casino", "cheat_detected"): [(FactionId.CORPORATE, -30), (FactionId.SYNDICATE, -20)],
}
```

### FactionId Enum

`SYNDICATE` (SynthSec), `CORPORATE` (OmniCorp), `UNDERGROUND` (BlackMarket), `STREET` (DeepState), `HACKER` (Ghost_Net), `ARENA_GUILD` (NeoTech + THE COLOSSEUM)

---

## PlayerProfile

`engine/characters/player_profile.py` — persistent player identity across sessions. Backed by Nexus KMS under category `player_profile`.

```python
from engine.characters.player_profile import get_player_profile
profile = get_player_profile()

profile.player_id          # UUID, stable across sessions
profile.display_name       # editable

profile.update_relationship("lola", delta=+15, note="Helped with the heist")
entry = profile.get_relationship("lola")
# entry.score = 65.0, entry.sentiment = "close"

profile.record_decision(scene="tavern", text="Chose to protect Viktor")
profile.record_scene_visit("casino")
profile.save()
```

### RelationshipEntry

| Field | Type | Description |
|-------|------|-------------|
| `character_id` | str | NPC identifier |
| `score` | float | Clamped to -100 to +100 |
| `sentiment` | str | `"close"` (>50), `"neutral"` (-50..50), `"hostile"` (<-50) |
| `last_interaction` | float | Unix timestamp |
| `interaction_count` | int | Update count |
| `notes` | list[str] | Free-text notes |

### Player Profile Skills

Pack `player_profile` in `engine/skills/builtin/player_profile_skills.py`:

| Skill | Description |
|-------|-------------|
| `get_player_summary` | Display name, top relationships, scene history |
| `update_npc_relationship` | Adjust relationship score by signed delta |
| `record_player_decision` | Log a key decision |
| `get_relationship_context` | Formatted context string for prompt injection |

### How Relationships Affect NPC Behavior

1. **System prompt injection** — `RelationshipContextInterceptor` (priority 30) injects top-5 NPC relationships into every agent call.
2. **DialogueGate** — NPCs with `min_relationship` thresholds gate dialogue branches.
3. **Scene rules** — `SceneRulesEngine` can query scores to gate quests, unlock locations, or trigger narrative beats.

### Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `player_profile.nexus_category` | `"player_profile"` | Nexus category |
| `player_profile.auto_save` | `true` | Save on every relationship update |
| `player_profile.auto_save_interval_seconds` | `300` | Periodic auto-save |
| `player_profile.inject_relationship_context` | `true` | Enable interceptor |
| `player_profile.max_notes_per_relationship` | `10` | Trim oldest notes above limit |

---

## Interceptor Pipeline (Character-Related)

Lower priority number = runs first. CosySim has 24 interceptors total across the full pipeline; the character-related subset is listed below.

| Priority | Interceptor | Phase | Description |
|----------|-------------|-------|-------------|
| 5 | `NaturalMoodDriftInterceptor` | pre_call | Stat drift, sweep buffs, decay tags, inner-thought injection |
| 7 | `CharacterMemoryInterceptor` | pre_call | Fetches top-5 memories from Nexus, injects `[CHARACTER MEMORY]` block |
| 8 | `CharacterRegistryInterceptor` | pre_call | Injects `[CHARACTER IDENTITY]` block (personality, top-5 tags, skills) |
| 22 | `ReputationInterceptor` | pre_call | Injects `[REPUTATION]` block with standing and attitude |
| 30 | `RelationshipContextInterceptor` | pre_call | Injects `[RELATIONSHIP CONTEXT]` block (top-5 NPC relationships) |
| 55 | `ConversationVarietyInterceptor` | pre+post | Anti-repetition, expressiveness, heat-level directives; post: tracks response, analyzes heat |
| 93 | `RelationshipEventInterceptor` | post_call | Scans reply for interaction keywords, applies buffs + tags |

### System Prompt Assembly Order

```
1. [CHARACTER MEMORY]           <- CharacterMemoryInterceptor (pri 7)
2. [CHARACTER IDENTITY]         <- CharacterRegistryInterceptor (pri 8)
3. [Inner feeling: ...]         <- NaturalMoodDriftInterceptor (pri 5)
4. [REPUTATION]                 <- ReputationInterceptor (pri 22)
5. [RELATIONSHIP CONTEXT]      <- RelationshipContextInterceptor (pri 30)
6. [CONVERSATION VARIETY]      <- ConversationVarietyInterceptor (pri 55)
   └── [CONVERSATION HEAT]     <- ConversationHeat.get_directive()
7. {personality.system_prompt}
8. {scene-specific rules}
9. {Director directive (if any)}
```

### ResponseDirective System

The `DialogSystem` injects `ResponseDirective` objects to steer character responses:

| Directive Type | Effect |
|----------------|--------|
| `style_lock` | Forces a writing style for N turns |
| `must_include` | Character must include a specific phrase or action |
| `forbidden` | Character must not say or do something |
| `exact_line` | Character speaks an exact line (can resist based on stats) |
| `whisper` | Secret nudge visible only to receiving agent |

---

## REST and MCP API

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/characters` | List all registered characters |
| GET | `/overlay/api/characters/<id>/tags` | Get behavioral tags |
| POST | `/overlay/api/characters/<id>/tags` | Add a behavioral tag |
| GET | `/api/admin/profile` | Player profile data |
| POST | `/api/admin/profile/relationship` | Manual relationship adjustment |

### MCP Tools

| Tool | Description |
|------|-------------|
| `get_character_state` | Unified state snapshot |
| `adjust_relationship` | Modify relationship stats between characters |
| `character_register` | Register a new character |
| `get_conversation_heat` | Heat level for a conversation |
| `get_conversation_heat_level` | Heat level with directive |

---

## See Also

- [MCP Framework](MCP_FRAMEWORK.md) — ResponseDirective and DialogSystem
- [Interceptors](INTERCEPTORS.md) — Full interceptor pipeline
- [Skills](SKILLS.md) — `@skill` decorator, pack registration, ~1,000 skills across 95 packs
- [Scenes](SCENES.md) — Per-scene emotion stat usage
- [Architecture](ARCHITECTURE.md) — BaseScene, MCP pipeline, 32 launch targets

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated to v1.50; fixed counts (~1,000 skills / 95 packs, 24 interceptors, 32 targets); removed stale cross-refs |
| v1.42 | 2025-12-15 | Consolidated reference from three-pillar architecture merge |
| v1.04b | 2025-09-01 | Initial character system documentation |
