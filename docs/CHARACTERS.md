# CosySim Character System

## Overview

Characters are AI-driven agents with persistent personality, stats, relationships, and behavioral tags. Each character combines an **immutable profile** (name, appearance, backstory, personality traits) with **mutable runtime state** (mood, energy, inhibition) and **assigned skills** (memory recall, speech style, web lookup, etc.).

The system spans four layers:

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Identity | `CharacterRegistry` | Profile, state, skills, restrictions |
| Stats | `SceneStateManager` | Arousal, happiness, anger, trust, etc. |
| Coordination | `CharacterStateCoordinator` | Unified write-through to all stores |
| Persistence | `Database` | Cross-session storage |

```
engine/mcp/character_registry.py   — profiles, skills, state
engine/mcp/state_coordinator.py    — unified update API, buffs, tags
engine/mcp/tag_registry.py         — inline [TAG:value] system
engine/agents/interceptors.py      — interceptor pipeline
content/simulation/database/db.py  — persistence + seed data
```

---

## Character Stats

### Registry Fields (CharacterState)

| Stat | Range | Description |
|------|-------|-------------|
| `mood` | string | Current emotional label: happy, sad, excited, nervous, etc. |
| `mood_intensity` | 0.0–1.0 | Strength of the current mood |
| `energy` | 0–100 | Physical/mental energy level |
| `inhibition` | 0–100 | Restraint level (0 = uninhibited, 100 = guarded) |
| `focus` | string | What the character is focused on right now |
| `current_role` | string | Active role in the scene: flirt, confessor, aggressor, etc. |

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
| `openness` | 0–100 | Willingness to share / be vulnerable |
| `explicitness` | 0–100 | Comfort with explicit content |
| `pleasure` | 0–100 | Current physical/emotional pleasure |
| `relationship` | 0–100 | Overall relationship level |

---

## Personality System

Each character's `CharacterProfile` contains:

- **Personality vector** — trait scores from 0.0 to 1.0:
  `warmth`, `curiosity`, `assertiveness`, `playfulness`, `empathy`, `dominance`, `vulnerability`, `wit`, `sensuality`, `openness`, `humor`, `flirtiness`, `intelligence`, `creativity`, `formality`
- **Voice style** — natural-language description of how they speak
- **Backstory** — paragraph of background context
- **Appearance** — dict of physical descriptors (hair, eyes, height, body, etc.)
- **Pronouns** — subject/object/possessive

The `CharacterRegistryInterceptor` loads the full personality profile from the simulation database, including:
- Backstory (up to 300 chars)
- Speech patterns and style
- Core traits list
- Quirks and interests

These are injected into the `[CHARACTER IDENTITY]` block at the top of every system prompt.

---

## Behavioral Tags

Tags are **soft labels** that reflect accumulated behavior patterns. They emerge from interactions and shape future personality.

### Mechanics

| Property | Value |
|----------|-------|
| Strength range | 0.0–1.0 |
| Default decay rate | 0.01 per drift tick |
| Reinforcement | Adds `strength × 0.5` to existing (diminishing returns) |
| Permanence | After 5 reinforcements at max strength → decay drops to 0 |
| Sweep | Dead tags (strength ≤ 0) removed on each drift tick |

### How Tags Flow

1. **Creation** — `RelationshipEventInterceptor` detects keywords in agent replies and maps them to tags via 20 keyword→tag mappings:

   | Keywords | Tag |
   |----------|-----|
   | cuddle, hug, caress | `affectionate` |
   | kiss | `romantic` |
   | flirt, wink | `flirtatious` |
   | tease | `playful` |
   | laugh | `fun-loving` |
   | moan, orgasm | `passionate` |
   | thrust, ride | `daring` |
   | compliment | `charming` |
   | apologize | `empathetic` |
   | argue | `confrontational` |
   | insult | `hostile` |
   | yell | `aggressive` |
   | cry | `vulnerable` |
   | massage | `caring` |

2. **Storage** — Tags live in `CharacterStateCoordinator._tags` (character_id → {tag → info dict}).

3. **Injection** — `CharacterRegistryInterceptor` reads the **top 5 strongest tags** and injects them into the `[CHARACTER IDENTITY]` prompt block. Permanent tags are labeled `(core)`.

4. **Decay** — `NaturalMoodDriftInterceptor` calls `coord.sweep_all_tags()` on every tick, reducing each tag's strength by its `decay_rate`.

### API

```python
from engine.mcp.state_coordinator import get_coordinator
coord = get_coordinator()

coord.add_tag("lola", "flirtatious", strength=0.15)
coord.get_tags("lola", min_strength=0.1)       # {"flirtatious": 0.15}
coord.get_top_tags("lola", n=5)                 # ["flirtatious"]
coord.get_permanent_tags("lola")                # ["charming"] (if earned)
coord.decay_tags("lola")                        # returns removed count
```

---

## Relationship Buffs

Buffs are **temporary stat modifiers** applied when relationship-significant events are detected in agent replies.

### Mechanics

| Property | Value |
|----------|-------|
| Duration | 60–600 seconds (varies by event type) |
| Application | Stat deltas applied immediately via `coord.update()` |
| Expiry | Reversed cleanly when timer expires |
| Cooldown | 10 seconds per buff type per agent (prevents spam) |
| Sweep | `coord.sweep_all_expired_buffs()` runs on every drift tick |

### Buff Definitions (from RelationshipEventInterceptor)

**Affectionate:**
| Keyword | Buff ID | Deltas | Duration |
|---------|---------|--------|----------|
| cuddle | warmth | affection+8, arousal+3, trust+2 | 300s |
| hug | warmth | affection+5, trust+2 | 180s |
| kiss | kiss | affection+10, arousal+8, trust+3 | 240s |
| caress | caress | affection+6, arousal+10 | 200s |
| massage | massage | arousal+12, affection+4 | 300s |

**Intimate:**
| Keyword | Buff ID | Deltas | Duration |
|---------|---------|--------|----------|
| moan | pleasure | arousal+15, affection+5 | 180s |
| orgasm | climax | arousal+20, affection+12, trust+5 | 300s |
| thrust | sex_act | arousal+18, affection+3 | 180s |
| lick | oral | arousal+14, affection+4 | 180s |
| suck | oral | arousal+16, affection+3 | 180s |
| penetrat | sex_act | arousal+20, affection+5, trust+3 | 240s |
| ride | sex_act | arousal+18, affection+5 | 200s |
| spank | rough | arousal+12, affection−2 | 120s |

**Social:**
| Keyword | Buff ID | Deltas | Duration |
|---------|---------|--------|----------|
| compliment | flattered | affection+4, trust+3 | 120s |
| laugh | joy | affection+3 | 90s |
| flirt | flirty | arousal+5, affection+4 | 120s |
| tease | teased | arousal+4, affection+2 | 90s |
| wink | flirty | arousal+3, affection+2 | 60s |

**Negative:**
| Keyword | Buff ID | Deltas | Duration |
|---------|---------|--------|----------|
| argue | tension | affection−6, trust−4, anger+10 | 300s |
| insult | hurt | affection−10, trust−8, anger+15 | 600s |
| yell | shaken | affection−5, trust−3, anger+12 | 240s |
| cry | sympathy | affection+3, trust+2 | 180s |
| apologize | mending | affection+4, trust+5, anger−8 | 300s |

### API

```python
coord.add_buff("lola", "warmth_123", {"affection": 8, "trust": 2}, duration_secs=300)
coord.get_active_buffs("lola")          # {buff_id: {deltas, remaining_secs, source}}
coord.remove_expired_buffs("lola")      # returns list of removed buff IDs
coord.sweep_all_expired_buffs()         # sweep all characters
```

---

## Conversation Heat

A 0–100 scale tracking the intensity of each conversation thread, per character×scene.

### Heat Levels

| Range | Level | Directive |
|-------|-------|-----------|
| 0–29 | Cold | No special directives |
| 30–59 | Warm | Flirty, playful energy; innuendo and light teasing |
| 60–79 | Hot | Explicit/suggestive content; escalation encouraged |
| 80–100 | Intense | Full adult content; raw emotion and desire |

### Mechanics

| Property | Value |
|----------|-------|
| Time-based decay | 2.0 per minute (applied after 30s idle) |
| Keyword bump cap | Max 25 per message |
| Heat keywords | flirt(8), kiss(15), intimate(20), touch(10), cuddle(5), tease(7), dare(6), sexy(12), love(5), desire(10), passion(12), seduce(15) |

### Flow

1. `ConversationVarietyInterceptor.post_call()` sends each agent reply to `heat.analyze_message()`.
2. The message is scanned for heat keywords; matching values are summed and bumped (capped at 25).
3. On the next `pre_call()`, `heat.get_directive(conv_key)` returns the appropriate system prompt directive.
4. Time-based decay is applied on every `get()` call.

### API

```python
from engine.mcp.scene_rules_engine import get_conversation_heat
heat = get_conversation_heat()

heat.bump("phone_aria_thread1", 10, "flirt")
heat.get("phone_aria_thread1")                # current level (0–100)
heat.analyze_message("phone_aria_thread1", msg)
heat.get_directive("phone_aria_thread1")       # system prompt string
heat.cool_all()                                # decay all threads
```

---

## Natural Mood Drift

Every interceptor tick, `NaturalMoodDriftInterceptor` (priority 5) applies small stat drifts toward baseline, preventing stats from getting stuck at extremes.

### Drift Rates (per call)

| Stat | Rate | Direction |
|------|------|-----------|
| arousal | −1.0 | Cools toward baseline |
| tiredness | +0.5 | Slowly accumulates |
| happiness | −0.3 | Regresses to mean |
| anger | −1.5 | Fades over time |
| fear | −1.0 | Dissipates |
| drunkenness | −0.5 | Sobers up |
| affection | −0.2 | Barely drifts |

Drift only applies when stats are outside the neutral zone (below 45 or above 55), except tiredness which always accumulates up to 90.

### Inner Thoughts

Based on current stat levels, an `[Inner feeling: ...]` line is injected into the system prompt:

| Condition | Thought |
|-----------|---------|
| arousal > 70 | "You feel the intensity fading a little — still present, but settling." |
| anger > 40 | "The tension eases. Your breathing slows." |
| tiredness > 60 | "A gentle wave of tiredness washes over you." |
| drunkenness > 30 | "The buzz is wearing off, edges sharpening." |
| any stat > 60 | "Your mood softens slightly, evening out." |

### Piggyback Operations

On each drift tick, the interceptor also:
- Sweeps all expired relationship buffs (`coord.sweep_all_expired_buffs()`)
- Decays all behavioral tags (`coord.sweep_all_tags()`)

---

## Character Registry

### Singleton Access

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

### Default Skills (applied to all characters)

1. `memory_recall` — auto, priority 10 (top_k=5, min_score=0.3)
2. `speech_enhance` — auto, priority 20 (default_style=natural)
3. `check_restrictions` — auto, priority 5 (personality_lock type)
4. `get_dialog_options` — optional, priority 30 (max 4 options)
5. `web_lookup` — optional, priority 60 (max 3 results)

---

## State Coordinator

The `CharacterStateCoordinator` is the **single write-through API** for all character state mutations. It routes fields to the correct store automatically.

### Why It Exists

Before the coordinator, state was scattered across three stores that didn't sync:
- **CharacterRegistry** — mood, energy, inhibition, focus
- **SceneStateManager** — arousal, happiness, clothing, stats
- **Database** — persistent name/age/personality

### Usage

```python
from engine.mcp.state_coordinator import get_coordinator
coord = get_coordinator()

# Delta mode (default) — numeric fields are added to current value
coord.update("lola", mood="flirty", arousal=+10, energy=-5)

# Absolute mode — set exact values
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

Factors: affection (±20), trust (±15), mood alignment (±5), relationship level (±10), baseline of 50.

---

## Default Characters

Five characters are seeded by `Database.seed_default_characters()`:

| ID | Name | Age | Sex | Appearance | Tags | Backstory |
|----|------|-----|-----|------------|------|-----------|
| `lola` | Lola Voss | 29 | F | Dark brunette hair, deep brown eyes, 5'6 | lounge, singer | Fled Vienna in 1919, built The Velvet Lounge from nothing. |
| `viktor` | Viktor Marlowe | 38 | M | Dark hair with grey, pale grey eyes, 6'2 | lounge, bartender | A past he doesn't discuss. Measures people like spirits. |
| `aria` | Aria | 22 | F | Platinum blonde, blue eyes, 5'4 | phone, companion | Your playful, flirty companion on CosyPhone. |
| `frankie` | Frankie DeLuca | 45 | M | Slicked black hair, dark eyes, 5'11 | casino, dealer | The Midnight Casino's head dealer. Smooth operator. |
| `mira` | Mira Vex | 28 | F | Red hair, green eyes, 5'7 | casino, hustler | Card shark and confidence artist. Never loses twice. |

Each character also gets a seeded `character_states` row with baseline trait scores (warmth, formality, humor, flirtiness, intelligence, creativity all at 0.5).

---

## API

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/overlay/api/characters` | List all registered characters |
| GET | `/overlay/api/characters/<id>/tags` | Get behavioral tags for a character |
| POST | `/overlay/api/characters/<id>/tags` | Add a behavioral tag |

### MCP Tools

| Tool | Description |
|------|-------------|
| `get_character_state` | Get unified state snapshot |
| `adjust_relationship` | Modify relationship stats between characters |
| `character_register` | Register a new character |
| `get_conversation_heat` | Get heat level for a conversation |
| `get_conversation_heat_level` | Get heat level with directive |

---

## Interceptor Pipeline (Character-Related)

These interceptors run in priority order on every agent call. Lower priority number = runs first.

| Priority | Interceptor | Phase | What It Does |
|----------|-------------|-------|--------------|
| 5 | `NaturalMoodDriftInterceptor` | pre_call | Applies stat drift toward baseline, sweeps expired buffs, decays tags, injects inner-thought line |
| 8 | `CharacterRegistryInterceptor` | pre_call | Ensures registry entry, injects `[CHARACTER IDENTITY]` block with personality + top 5 tags + skills, checks for `force_response` directive |
| 55 | `ConversationVarietyInterceptor` | pre_call + post_call | Pre: injects anti-repetition + expressiveness + heat-level directives. Post: tracks response, analyzes message for heat keywords |
| 93 | `RelationshipEventInterceptor` | post_call | Scans reply for 20 interaction keywords → applies relationship buffs + behavioral tags with cooldown |

### System Prompt Assembly Order

```
1. [CHARACTER IDENTITY] block          ← CharacterRegistryInterceptor (pri 8)
   - Name, mood, personality traits
   - Voice style, restrictions, skills
   - Personality profile (backstory, speech patterns, quirks)
   - Behavioral tags (top 5, permanent marked as "core")

2. [Inner feeling: ...]                ← NaturalMoodDriftInterceptor (pri 5)

3. [CONVERSATION VARIETY] block        ← ConversationVarietyInterceptor (pri 55)
   - Anti-repetition guidance
   - Expressiveness instructions
   - [CONVERSATION HEAT: level]        ← from ConversationHeat.get_directive()

4. (other scene/policy interceptors)
```

### Post-Call Processing

```
1. ConversationVarietyInterceptor (pri 55)
   → Tracks response text for variety checking
   → Sends reply to ConversationHeat.analyze_message()

2. RelationshipEventInterceptor (pri 93)
   → Scans reply for interaction keywords
   → Applies relationship buffs via StateCoordinator
   → Adds behavioral tags (strength 0.15 each)
```
