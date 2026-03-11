# CosySim Character System

> Reference for CharacterMemory, ReputationManager, the relationship system, emotion model,
> and speech patterns. v0.69b.

---

## Overview

CosySim's character system has two layers:

1. **Simulation layer** (`content/simulation/character_system/`) — static character
   definition: physical attributes, personality template, database-backed state
2. **Engine layer** (`engine/characters/`) — live, session-persistent intelligence:
   memory recall, reputation tracking, cross-scene effects

Both layers integrate via the MCP interceptor pipeline, injecting context into every
LLM call before the model responds.

```
Player message
     │
     ▼
CharacterMemoryInterceptor (priority 7)
     │  — fetches top-5 relevant memories from Nexus
     │  — prepends [CHARACTER MEMORY] block to system_prompt
     ▼
ReputationInterceptor (priority 22)
     │  — prepends [REPUTATION] block to system_prompt
     ▼
LLM call
     │
     ▼
Character response (contextualised by memory + reputation)
```

---

## Simulation Layer

### Character Class (`content/simulation/character_system/character.py`)

The `Character` class is the static definition of a character loaded from the SQLite
database. It is instantiated when a scene starts.

```python
from content.simulation.character_system.character import Character

char = Character("luna")
print(char.name)        # "Luna"
print(char.appearance)  # "female, 24 years old, slim, blonde hair, blue eyes"
```

**Physical attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique character identifier |
| `name` | `str` | Display name |
| `age` | `int` | Age in years |
| `sex` | `str` | Gender/sex descriptor |
| `hair_color` | `str` | Hair colour |
| `eye_color` | `str` | Eye colour |
| `height` | `str` | Height description |
| `body_type` | `str` | Body type descriptor |
| `description` | `str` | Free-text appearance note |

**Computed property `appearance`** returns a comma-joined description suitable for
image generation prompts (ComfyUI / SceneArtManager).

**State** (`character_state` table): mutable runtime values — `mood`, `scene`, and
any scene-specific stat values.

**Personality** (`personality_id` FK): links to a `PersonalityTemplate`.

On initialisation, the `Character` registers with `CharacterRegistry` (MCP), allowing
the MCP framework to address it by ID for governor calls.

---

### Personality System (`content/simulation/character_system/personality.py`)

Personalities are defined as `PersonalityTemplate` dataclasses with:

- `system_prompt` — base LLM system prompt injected for every response
- `traits` — list of personality adjectives (used in prompt and tagging)
- `communication_style` — `{tone, emoji_usage, humor, directness}`
- `sexual_openness` — float 0.0–1.0 (seeds `openness` stat at creation)

**Personality trait floats (all 0.0–1.0):**

| Trait | Effect |
|-------|--------|
| `warmth` | Affectionate vs. cool baseline |
| `formality` | Casual vs. formal register |
| `humor` | How often the character jokes |
| `flirtiness` | Baseline flirt tendency |
| `intelligence` | Vocabulary complexity, analytical depth |
| `creativity` | Metaphor use, imaginative responses |

**Built-in templates:**

| Template ID | Description |
|-------------|-------------|
| `playful_girlfriend` | Warm, teasing, high emoji, confident; openness 0.7 |
| `sweet_girlfriend` | Nurturing, empathetic, romantic, low-medium openness |
| `dominant_mistress` | Commanding, assertive, scene-appropriate authority |
| `mysterious_stranger` | Cryptic, minimalist, high intrigue |
| `intellectual_companion` | High intelligence/creativity, low formality |

---

## Engine Layer

### CharacterMemory (`engine/characters/memory.py`)

`CharacterMemory` provides **persistent, cross-session memory** for a single character.
All memories are stored in Nexus with `content_type="memory"` and retrieved via
semantic search.

#### MemoryEntry

```python
@dataclass
class MemoryEntry:
    id: str                # UUID
    character_id: str      # owner character
    player_id: str         # which player this memory is about
    content: str           # natural-language description
    emotional_weight: float # salience, 0.0 (trivial) → 1.0 (unforgettable)
    scene: str             # scene where memory was formed
    created_at: str        # ISO-8601 UTC
    accessed_at: str       # ISO-8601 UTC, updated on every recall
    access_count: int      # how many times recalled
    tags: List[str]        # free-form labels (e.g. ["wardrobe", "request"])
```

#### API

```python
from engine.characters.memory import get_character_memory

# Get the singleton for a character
mem = get_character_memory("luna")

# Store a new memory
entry = mem.remember(
    "The player asked Luna to wear the red dress",
    player_id="player",
    emotional_weight=0.8,
    scene="penthouse",
    tags=["wardrobe", "request"],
)

# Retrieve relevant memories (semantic search + emotional_weight re-rank)
memories = mem.recall("what did the player ask about clothes", player_id="player", limit=5)

# Get the most recent memories
recent = mem.recall_recent(player_id="player", limit=10)

# Get system-prompt-ready summary of top memories
summary = mem.get_memory_summary(player_id="player")
# → "You remember: The player asked you to wear the red dress.\nYou remember: ..."

# NLM-generated relationship summary
prose = mem.summarize(player_id="player")

# Forget old memories (cleanup)
deleted = mem.forget_old(days=30, player_id="player")

# Forget a specific entry
mem.forget_entry(entry_id="uuid-here")
```

#### Recall Algorithm

`recall()` performs a 4-step ranking:

1. Nexus semantic search for `context` (returns up to `limit × 4` candidates)
2. Filter to `character_id` and `player_id`
3. Score: `relevance = (1.0 / (rank + 1)) × (0.5 + 0.5 × emotional_weight)`
4. Sort descending, return top `limit`; bump `access_count` on each returned entry

#### Nexus Storage Layout

```
content_type = "memory"
category     = "character_memory:{character_id}"
title        = "memory:{character_id}:{entry_id}"
content      = JSON-serialised MemoryEntry
tags         = [entry.tags..., "player:{player_id}", "character:{character_id}"]
```

---

### CharacterMemoryInterceptor

An `InterceptorBase` that fires at **priority 7** (before CharacterRegistryInterceptor
at 8, after NaturalMoodDriftInterceptor at 5).

On every `pre_call`:
1. Reads `character_id`, `player_id`, `user_message` from `ResponseContext`
2. Calls `mem.recall(user_message, limit=5)`
3. Calls `mem.get_memory_summary()`
4. Prepends `[CHARACTER MEMORY]\n{summary}\n[/CHARACTER MEMORY]` to `system_prompt`

```python
from engine.characters.memory import CharacterMemoryInterceptor
interceptor = CharacterMemoryInterceptor()
governor.pipeline.add(interceptor)
```

---

### ReputationManager (`engine/characters/reputation.py`)

`ReputationManager` tracks **standing** between the player and every character or
faction across all scenes. Standing persists in Nexus and survives restarts.

#### Standing Scale

| Range | Label | Behaviour in Prompts |
|-------|-------|---------------------|
| 81–100 | **Revered** | Deeply loyal, would go to great lengths |
| 61–80 | **Trusted** | Warm, open, genuinely willing to help |
| 41–60 | **Friendly** | Cooperative, pleased to assist |
| 21–40 | **Neutral** | Polite, willing to engage on fair terms |
| −20–20 | **Indifferent** | No strong feelings, neutral and professional |
| −40 to −21 | **Cold** | Uneasy, guarded and curt |
| −60 to −41 | **Hostile** | Dislikes player, cold and distrustful |
| −80 to −61 | **Enemy** | Views player as adversary, dismissive |
| −100 to −81 | **Nemesis** | Despises player, openly hostile |

#### ReputationEntry

```python
@dataclass
class ReputationEntry:
    entity_id: str       # character ID or FactionId value
    entity_type: str     # "character" or "faction"
    player_id: str
    standing: int        # clamped to [-100, 100]
    label: str           # computed tier label
    history: List[str]   # last 10 change notes
    last_updated: str    # ISO-8601
```

#### API

```python
from engine.characters.reputation import get_reputation_manager

mgr = get_reputation_manager()

# Adjust standing
entry = mgr.adjust("mira", delta=-30, reason="player betrayed Mira at the heist")
print(entry.label)   # "Hostile"

# Set absolute standing
mgr.set_standing("mira", standing=50, reason="player helped Mira escape")

# Get prompt-ready context
print(mgr.get_prompt_context("mira"))
# → "Your standing with the player is HOSTILE (-30). Recent: -30: player betrayed... You are guarded and cold."

# All faction standings
factions = mgr.get_faction_standings()   # Dict[str, ReputationEntry]

# Cross-scene ripple
summaries = mgr.apply_cross_scene_ripple("casino", "debt_created", delta=-1)
```

#### Cross-Scene Ripple Map

When a scene fires an event, `apply_cross_scene_ripple` applies pre-defined
adjustments to other entities:

```python
_RIPPLE_MAP = {
    ("casino", "debt_created"):   [(FactionId.SYNDICATE, -10), ("mira", -5)],
    ("heist",  "job_complete"):   [(FactionId.UNDERGROUND, +15)],
    ("arena",  "bet_win"):        [(FactionId.ARENA_GUILD, +10)],
    ("casino", "cheat_detected"): [(FactionId.CORPORATE, -30), (FactionId.SYNDICATE, -20)],
}
```

#### FactionId Enum

```python
class FactionId(str, Enum):
    SYNDICATE   = "SYNDICATE"    # → SynthSec (NeonCity)
    CORPORATE   = "CORPORATE"    # → OmniCorp (NeonCity)
    UNDERGROUND = "UNDERGROUND"  # → BlackMarket (NeonCity)
    STREET      = "STREET"       # → DeepState (NeonCity)
    HACKER      = "HACKER"       # → Ghost_Net (NeonCity)
    ARENA_GUILD = "ARENA_GUILD"  # → NeoTech (NeonCity) + THE COLOSSEUM
```

#### ReputationInterceptor

Fires at **priority 22**. Prepends `[REPUTATION]\n{context}\n[/REPUTATION]` to
every LLM system prompt:

```python
from engine.characters.reputation import ReputationInterceptor
governor.pipeline.add(ReputationInterceptor())
```

---

## Emotion Model (0–100 Stats)

Each scene exposes a different subset of emotion stats, all tracked in
`SceneStateManager`. The penthouse scene has the most complete model:

| Stat | Range | Description |
|------|-------|-------------|
| `warmth` | 0–100 | Emotional closeness and affection felt in the moment |
| `comfort` | 0–100 | Sense of safety and ease |
| `arousal` | 0–100 | Sexual and sensual excitement |
| `openness` | 0–100 | Willingness to try new things; vulnerability |
| `compliance` | 0–100 | Readiness to follow suggestions or requests |
| `happiness` | 0–100 | General positive mood |
| `horniness` | 0–100 | Desire for sexual activity |
| `fear` | 0–100 | Fear or apprehension (used in fear-play and horror scenes) |
| `affection` | 0–100 | Deep emotional bond |
| `trust` | 0–100 | Confidence in the player's intentions |
| `sanity` | 0–100 | Grip on reality (realm scene) |
| `heat` | 0–100 | Scene atmosphere temperature (lounge, tavern) |

**Stat seeding from personality:** When a character is created from a `PersonalityTemplate`,
the personality trait floats (`warmth`, `flirtiness`, `sexual_openness`) are scaled to
0–100 and used as initial stat values.

**Stat decay:** `NaturalMoodDriftInterceptor` (priority 5) applies small natural drifts
each turn — e.g., arousal decays 2 pts/turn unless stimulated; warmth increases 1 pt/turn
in positive interactions.

---

## Speech Patterns

Speech patterns are defined in `communication_style` on the personality template and
injected into every system prompt.

### Communication Style Fields

| Field | Values | Effect |
|-------|--------|--------|
| `tone` | `"casual"`, `"warm"`, `"dominant"`, `"cryptic"`, `"formal"` | Registers |
| `emoji_usage` | `"high"`, `"medium"`, `"low"`, `"none"` | Frequency of emoji in responses |
| `humor` | `"playful"`, `"dry"`, `"dark"`, `"none"` | Joke style |
| `directness` | `"high"`, `"medium"`, `"low"` | How directly needs are expressed |

### Prompt Injection Format

The character's system prompt is composed by the MCP framework in this order:

```
[CHARACTER MEMORY]
{memory summary — up to 10 lines}
[/CHARACTER MEMORY]

[REPUTATION]
Your standing with the player is {LABEL} ({standing}).
{attitude sentence}
[/REPUTATION]

{personality.system_prompt}

{scene-specific rules}
{current stat context}
{Director directive (if any)}
```

### ResponseDirective System

The `DialogSystem` can inject `ResponseDirective` objects to steer the character's
next response without editing the system prompt directly:

| Directive Type | Effect |
|----------------|--------|
| `style_lock` | Forces a writing style for N turns (e.g., `"pornographic"`, `"tender"`) |
| `must_include` | Character must include a specific phrase or action |
| `forbidden` | Character must not say or do something |
| `exact_line` | Character speaks an exact line (can resist based on stats) |
| `whisper` | Secret nudge visible only to the receiving agent |

---

## Relationship Lifecycle

A typical relationship arc across sessions:

```
Session 1:
  player meets character → standing = 0 (Indifferent)
  positive interactions → warmth +15, affection +10
  CharacterMemory: remembers "player asked my name" (weight 0.3)

Session 2 (different day):
  CharacterMemoryInterceptor recalls memories from Session 1
  Character references past interaction naturally
  Trust grows: player demonstrates consistency → trust +20 → Neutral

Session 5+:
  standing ≥ 41 → Friendly
  Intimate gate unlocks
  Memory entries multiply; top-weight memories persist

Session 10+:
  standing ≥ 61 → Trusted
  Character initiates topics from past memories
  Autonomous texting frequency increases (phone scene)
```

---

## Integration Map

| System | Connects To | How |
|--------|-------------|-----|
| `CharacterMemory` | Nexus | Stores/retrieves via `content_type="memory"` |
| `CharacterMemory` | MCP Pipeline | `CharacterMemoryInterceptor` at priority 7 |
| `ReputationManager` | Nexus | Upserts `ReputationEntry` per entity |
| `ReputationManager` | EventBus | Fires `reputation.label_changed` on tier cross |
| `ReputationManager` | MCP Pipeline | `ReputationInterceptor` at priority 22 |
| `Character` | CharacterRegistry | Auto-registers on init; MCP can address by ID |
| `PersonalityTemplate` | SceneStateManager | Stat seeds at character creation |
| `NaturalMoodDriftInterceptor` | Stats | Decays/drifts stats each turn |

---

*See [CHARACTERS.md](./CHARACTERS.md) for the older character reference (buffs, tags).*
*See [SCENE_GUIDE.md](./SCENE_GUIDE.md) for per-scene emotion stat usage.*
*See [INTERCEPTORS.md](./INTERCEPTORS.md) for the full interceptor pipeline.*
*See [MCP_FRAMEWORK.md](./MCP_FRAMEWORK.md) for ResponseDirective and DialogSystem.*
