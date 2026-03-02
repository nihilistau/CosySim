# CosySim Player Identity System

> Persistent player state — session history, NPC relationships, decisions, and admin tooling.
> Added in v0.72b "The Asset Studio".

---

## Overview

The Player Identity System gives every play session a persistent identity. Rather than treating the
player as a stateless input source, CosySim tracks who they are across sessions: which scenes they
have visited, which NPCs they have bonded with or antagonised, and which key decisions they have
made. This context is injected automatically into every agent system prompt, making NPCs react
to history rather than treating each conversation as a blank slate.

---

## Components

### PlayerProfile (`engine/characters/player_profile.py`)

The central persistent state object for the player. Backed by Nexus KMS under category
`player_profile` (key `player_profile_v1`). Thread-safe — all mutations are serialised through
an internal lock.

```python
from engine.characters.player_profile import get_player_profile
profile = get_player_profile()

# Identity
print(profile.player_id)        # UUID, stable across sessions
print(profile.display_name)     # "Player" (editable in admin)

# Relationships
profile.update_relationship("lola", delta=+15, note="Helped with the heist")
entry = profile.get_relationship("lola")
print(entry.score)      # 65.0
print(entry.sentiment)  # "close"  (>50), "neutral" (-50..50), "hostile" (<-50)

# Decisions
profile.record_decision(scene="tavern", text="Chose to protect Viktor")

# Scene history
profile.record_scene_visit("casino")

# Persist (also called automatically on shutdown)
profile.save()
```

**RelationshipEntry fields:**

| Field | Type | Description |
|-------|------|-------------|
| `character_id` | str | NPC identifier |
| `score` | float | Relationship score, clamped to –100 … +100 |
| `sentiment` | str | `"close"` (>50) · `"neutral"` (–50..50) · `"hostile"` (<–50) |
| `last_interaction` | float | Unix timestamp of last update |
| `interaction_count` | int | Number of times the relationship has been updated |
| `notes` | list[str] | Free-text notes (e.g., reason for a big delta) |

---

### PlayerProfile Skills (`engine/skills/builtin/player_profile_skills.py`)

Four `@skill`-decorated functions in the `player_profile` pack expose the profile to LLM agents:

| Skill | Description |
|-------|-------------|
| `get_player_summary` | Returns display name, top relationships, and scene history |
| `update_npc_relationship` | Adjust relationship score by a signed delta |
| `record_player_decision` | Log a key decision (scene + free text) |
| `get_relationship_context` | Formatted context string for injection into prompts |

```python
# Called by an NPC agent to understand how to treat the player
context = get_relationship_context()
# → "Player relationship with lola: close (+65). Notes: Helped with the heist."
```

---

### RelationshipContextInterceptor

A pre-call interceptor (priority 30) that runs before every agent LLM call. It reads the current
`PlayerProfile`, formats the top-5 NPC relationships, and appends a relationship context block to
the agent's system prompt. This ensures NPCs have immediate awareness of relationship history
without scene code needing to manually inject it.

```
[RELATIONSHIP CONTEXT]
Player → lola: close (+65) — 3 interactions
Player → viktor: neutral (+10) — 1 interaction
Player → aria: hostile (−72) — 7 interactions
```

The interceptor is registered in `config/default.yaml` under `comms.interceptors`:

```yaml
comms:
  interceptors:
    - engine.agents.relationship_context_interceptor.RelationshipContextInterceptor
```

Set `player_profile.inject_relationship_context: false` to disable injection without removing the
interceptor from the pipeline.

---

## Admin Overlay — PROFILE Tab

The admin overlay (accessible on every scene at `/admin`) includes a **[PROFILE]** tab that provides
a live view of the active `PlayerProfile`:

- **Identity panel** — player ID, display name, total sessions, first/last seen timestamps.
- **Relationship grid** — all tracked NPCs sorted by score, colour-coded by sentiment (green =
  close, grey = neutral, red = hostile). Scores update in real time via Socket.IO.
- **Decision log** — chronological list of recorded decisions with scene and timestamp.
- **Scene history** — visit counts per scene, rendered as a bar chart.
- **Manual controls** — reset relationship scores, edit display name, force save to Nexus.

The PROFILE tab data is served by `/api/admin/profile` (GET) and `/api/admin/profile/relationship`
(POST for manual score adjustments).

---

## How Relationships Affect NPC Behavior

Relationship scores influence NPC behavior at three levels:

1. **System prompt injection** (`RelationshipContextInterceptor`) — every agent call receives the
   current relationship summary. NPCs use this to adjust tone, willingness to help, and dialogue
   choices without explicit scene-level wiring.

2. **DialogueGate** (`engine/agents/dialogue_gate.py`) — NPCs with a `min_relationship` threshold
   set in their character config will refuse certain dialogue branches until the score is met.
   Example: Viktor will not reveal faction secrets unless `score("viktor") ≥ 40`.

3. **Scene rules** (`SceneRulesEngine`) — scenes can query `profile.get_relationship(npc_id).score`
   to gate quests, unlock locations, or trigger narrative beats. The `player_profile` skill pack
   exposes helpers for rules authors who prefer declarative YAML conditions.

---

## Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `player_profile.nexus_category` | `"player_profile"` | Nexus category for persistence |
| `player_profile.auto_save` | `true` | Save to Nexus on every relationship update |
| `player_profile.auto_save_interval_seconds` | `300` | Periodic auto-save interval |
| `player_profile.inject_relationship_context` | `true` | Enable interceptor injection |
| `player_profile.max_notes_per_relationship` | `10` | Trim oldest notes above this limit |

---

## Example: Full Relationship Lifecycle

```python
from engine.characters.player_profile import get_player_profile

profile = get_player_profile()

# Player helps Lola during a heist scene
profile.update_relationship("lola", delta=+20, note="Saved her during the warehouse job")
profile.record_decision(scene="heist", text="Protected Lola instead of taking the money")

# Later, in the lounge — Lola greets the player differently
# (RelationshipContextInterceptor has injected the +20 score into Lola's system prompt)
# Lola: "I won't forget what you did at the warehouse. You can trust me."

# Player betrays Viktor
profile.update_relationship("viktor", delta=-60, note="Sold Viktor's location to the cartel")

# Viktor's DialogueGate now blocks faction intel routes
# Viktor: "I've got nothing to say to you."
```
