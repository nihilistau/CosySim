# OpenRoom-Inspired Features

> CosySim Documentation — v1.51.1 [2026-03-25]
>
> 6 features inspired by OpenRoom/VibeApps that transform AI characters from reactive
> chat agents into autonomous beings with memory, agency, and a virtual world.

---

## Background & Inspiration

In March 2026, [OpenRoom.ai](https://openroom.ai) launched a live-streaming AI character
platform built on **VibeApps** (their open-source engine). Within days it reached
**~10,000 concurrent viewers** and **3.6M likes** on a single character room. Using ARGUS
deep analysis (HAR traffic, V8 heap snapshots, open source code), we reverse-engineered
the architecture and identified 6 features that CosySim's engine was perfectly positioned
to adopt.

### What OpenRoom Proved

| Metric | OpenRoom Live Stats | CosySim Equivalent |
|--------|--------------------|--------------------|
| Concurrent viewers | ~10,000 | Danmaku spectator bus |
| AI model | MiniMax-M2.5 + "Modern" LLM | LMStudio local inference |
| Character creation | UGC pipeline with archetypes | CharacterWizard 6-stage pipeline |
| Story system | Stage-based narrative with targets | NarrativeModEngine |
| Virtual OS | 8 apps (Twitter, Diary, Music, Email, Album, Evidence Vault, Chat, OS) | NeonOS desktop shell |
| File generation | AI-authored diary entries, tweets, playlists | Virtual filesystem over Nexus |
| Real-time broadcast | Protobuf-framed WebSocket danmaku | SpectatorBus + danmaku overlay |

### Architecture Comparison

```
OpenRoom/VibeApps                         CosySim v1.51.0
─────────────────                         ───────────────
Weaver API (REST)              ←→         MCPFramework + AgentGovernor
Character Session Manager      ←→         CharacterRegistry + WizardState
Stage/Target Narrative         ←→         NarrativeModEngine + ModStage/ModTarget
Virtual OS Apps (8)            ←→         NeonOS Desktop Shell + /api/apps
AI File Creation               ←→         NexusFilesystem + fs_skills
Danmaku WebSocket Broadcast    ←→         SpectatorBus + cosysim-danmaku.js
UGC Character Pipeline         ←→         CharacterWizard (6-stage)
MiniMax Credits System         ←→         (Future: economy integration)
```

### ARGUS Discovery Process

All features were identified through ARGUS deep analysis:

1. **HAR capture** of OpenRoom web client → endpoint enumeration, auth flow, WebSocket framing
2. **V8 heap snapshot** → hidden APIs (`/weaver/api/v1/conversation/*`), credits system,
   `ADMIN_ONLY_OPERATION` flag, CDN music URLs, `__claudeElementMap` reference
3. **Open source review** of [github.com/nihilistau/OpenRoom](https://github.com/nihilistau/OpenRoom)
   → VibeApps engine internals, stage system, app architecture

Full analysis reports are in `data/argus/reports/`:
- `openroom_research_journal.md` — Complete research narrative
- `openroom_vs_cosysim_architecture.md` — Architecture comparison matrix

---

## Feature 1: save_memory + recall_about Skills

**Status:** Shipped
**Files Modified:** `engine/skills/builtin/memory_skills.py`, `content/simulation/database/rag.py`
**Inspired by:** OpenRoom's character memory system where AI characters remember facts across sessions

### What It Does

Agents can now **proactively save important information** to long-term memory during
conversations, and **recall information by subject** rather than just keyword search.

### Usage

```python
# Agent self-invokes during conversation
save_memory(
    content="The player's favorite color is midnight blue",
    category="preference",    # fact | preference | event | emotion | observation
    subject="player",
    importance=0.8,
)

# Subject-based retrieval
recall_about(subject="player", category="preference", top_k=5)
# → Returns: "The player's favorite color is midnight blue" (similarity: 0.94)
```

### Categories

| Category | Purpose | Example |
|----------|---------|---------|
| `fact` | Objective information | "Player lives in District 7" |
| `preference` | Likes, dislikes, favorites | "Player prefers whiskey over wine" |
| `event` | Things that happened | "We explored the abandoned warehouse together" |
| `emotion` | Emotional moments | "Player was visibly moved when talking about their sister" |
| `observation` | Character's own observations | "Player seems to trust me more after I shared my backstory" |

### How It Works

1. `save_memory` calls `RAGMemory.add_memory()` with the category as `memory_type` and subject as a tag
2. `recall_about` calls `RAGMemory.query_memories()` with subject/category filters in the ChromaDB where clause
3. The existing `search_memory` skill gains optional `category` and `subject` filter parameters

### CONNECTS

- **RAGMemory** — ChromaDB-backed vector store for character memories
- **AgentGovernor** — Auto-includes memory skills in skill manifest
- **MemoryEnhancerInterceptor** — Injects recent memories into system prompt

---

## Feature 2: Danmaku/Spectator Mode

**Status:** Shipped
**New Files:**
- `engine/services/spectator_bus.py` — SpectatorBus singleton (~224 lines)
- `engine/agents/interceptors/spectator_broadcast.py` — Priority 92 interceptor (~106 lines)
- `content/shared/static/js/cosysim-danmaku.js` — Floating bullet comments (~226 lines)
- `content/shared/static/css/cosysim-danmaku.css` — Cyberpunk neon styling (~165 lines)

**Modified:** `content/scenes/oracle/oracle_scene.py` (spectator API endpoint)
**Inspired by:** OpenRoom's real-time danmaku (bullet comments) system with ~10K concurrent viewers

### What It Does

Every agent reply broadcasts a **spectator message** via the SpectatorBus. Any connected
client renders these as **floating right-to-left bullet comments** (danmaku) overlaid on
the scene, creating a live "audience watching the AI" experience.

### Architecture

```
Agent Reply
  ↓ (InterceptorPipeline, post_call)
SpectatorBroadcastInterceptor (priority 92)
  ↓ extracts: text, agent, mood, scene
SpectatorBus.broadcast(SpectatorMessage)
  ├→ Ring buffer (200 entries, get_recent)
  └→ Subscriber callbacks
       ↓
  SocketIO → danmaku_msg event
       ↓
  cosysim-danmaku.js → floating bullet comment
```

### SpectatorMessage Fields

```python
@dataclass
class SpectatorMessage:
    kind: str          # "chat" | "action" | "skill" | "system"
    text: str          # First 100 chars of reply
    agent_id: str      # Character who spoke
    scene: str         # Active scene ID
    color: str         # Mood-mapped hex color
    ttl_secs: float    # Time-to-live (default 10s)
    timestamp: float   # time.time()
    msg_id: str        # Unique ID
```

### Mood → Color Mapping

| Mood | Color | Visual |
|------|-------|--------|
| happy | `#00ff88` | Neon green |
| sad | `#6699ff` | Soft blue |
| angry | `#ff3366` | Hot pink |
| flirty | `#ff66cc` | Pink |
| neutral | `#cccccc` | Silver |
| mysterious | `#9966ff` | Purple |
| excited | `#ffcc00` | Gold |

### Frontend Controls

- **F7** toggles danmaku on/off (persists in localStorage)
- Messages float across 5 lanes (top to bottom)
- Each message has a neon glow matching its color
- `prefers-reduced-motion` fallback shows static list
- Any scene can load the overlay by including the shared JS/CSS

### API

```
GET /api/oracle/spectator         → Recent spectator messages (JSON)
SocketIO: danmaku_msg event       → Real-time broadcast to connected clients
```

---

## Feature 3: NeonOS Virtual Desktop Shell

**Status:** Shipped
**New Files:**
- `content/scenes/neonos/neonos_scene.py` — FlaskScene on port 5593 (~313 lines)
- `content/scenes/neonos/templates/neonos.html` — Desktop template
- `content/scenes/neonos/static/neonos.js` + `neonos.css` — Scene glue
- `content/shared/static/js/cosysim-desktop.js` — Window manager (~468 lines)
- `content/shared/static/css/cosysim-desktop.css` — Desktop styling (~393 lines)

**Inspired by:** OpenRoom's Virtual OS with 8 built-in apps (Twitter, Diary, Music, Email, Album, Evidence Vault, ChatRoom, OS Settings)

### What It Does

NeonOS is a **virtual desktop shell** that renders every CosySim scene as a **draggable,
resizable window** inside a single browser tab. Instead of opening 15 browser tabs for
15 scenes, you open one NeonOS tab and launch scenes as "apps" in floating windows.

### Architecture

```
NeonOS Scene (port 5593)
  ├─ /api/apps → reads control_plane_registry → returns app descriptors
  │              TCP-probes each port for online/offline status
  │
  ├─ NeonDesktop (JS) → renders app launcher grid grouped by pillar
  │   ├─ App tiles with accent colors and online/offline indicators
  │   ├─ Click tile → opens NeonWindow(iframe to localhost:{port})
  │   └─ Taskbar with clock, minimize/restore buttons
  │
  └─ NeonWindow (JS) → individual floating window
      ├─ Draggable titlebar (pointer events, z-index management)
      ├─ Resizable (8 edge/corner handles)
      ├─ Minimize → hides window, shows in taskbar
      ├─ Maximize → full viewport
      ├─ Close → removes iframe + window
      └─ Drag overlay → prevents iframe from stealing mouse events
```

### Launching

```bash
python launcher.py neonos    # → http://localhost:5593
```

### App Discovery

The `/api/apps` endpoint queries `control_plane_registry.py` and returns:

```json
[
  {
    "name": "penthouse",
    "display_name": "THE PENTHOUSE",
    "port": 5556,
    "pillar": "game",
    "accent_color": "#ff6b9d",
    "status": "online",
    "url": "http://localhost:5556/"
  },
  ...
]
```

### Glass-Morphism Styling

Windows use CSS `backdrop-filter: blur()` for frosted glass effect, with neon-glow
borders matching each app's accent color. The cyberpunk aesthetic matches CosySim's
existing Neon HUD v2 design language.

---

## Feature 4: Virtual Filesystem over Nexus

**Status:** Shipped
**New Files:**
- `engine/nexus/filesystem.py` — NexusFilesystem class (~513 lines)
- `engine/skills/builtin/fs_skills.py` — 6 filesystem skills (~222 lines)

**Inspired by:** OpenRoom's AI file creation system where characters autonomously write diary entries, tweets, playlists, and email drafts stored in a virtual OS

### What It Does

A **virtual filesystem** that maps paths (`/home/player/notes/todo.txt`) to Nexus KMS
entries. Agents can read, write, create directories, and search files — everything persists
in Nexus and survives restarts.

### Path → Nexus Mapping

```
Virtual Path                    Nexus Entry
───────────                     ──────────
/home/player/notes/todo.txt  →  title: "/home/player/notes/todo.txt"
                                 content_type: "filesystem"
                                 category: "fs_file"
                                 tags: ["fs", "path:/home/player/notes/todo.txt",
                                        "parent:/home/player/notes/",
                                        "owner:player"]
```

### Auto-Seeded Directories

On first access, the filesystem auto-creates:

```
/home/player/           # Player's home directory
/home/player/notes/     # Quick notes
/home/player/journal/   # Daily journal entries
/shared/                # Cross-character shared files
/system/                # System-generated files
```

### Skills

```python
# Agent reads a file
read_file(path="/home/player/notes/todo.txt")
# → "Buy milk\nFix the generator\nTalk to Viktor about the heist"

# Agent writes a file
write_file(
    path="/home/player/journal/2026-03-25.md",
    content="Today I met someone interesting at the tavern...",
)
# → "Written 51 characters to /home/player/journal/2026-03-25.md"

# List directory contents
list_files(path="/home/player/")
# → "notes/ (directory)\njournal/ (directory)"

# Create a new directory
make_directory(path="/home/player/evidence/")

# Search across all files
find_files(query="heist plans")
# → Semantic search across all file contents
```

### NexusFilesystem API

```python
from engine.nexus.filesystem import get_filesystem

fs = get_filesystem()
fs.write("/shared/announcement.txt", "Server maintenance at midnight")
content = fs.read("/shared/announcement.txt")
entries = fs.list_dir("/home/player/")
tree = fs.tree("/home/player/", max_depth=3)
exists = fs.exists("/home/player/notes/")
fs.delete("/home/player/notes/old_draft.txt")
```

---

## Feature 5: Stage+Target Narrative System

**Status:** Shipped
**New Files:**
- `engine/mcp/narrative_mod.py` — NarrativeModEngine (~340 lines)
- `engine/agents/interceptors/narrative_mod.py` — Priority 15 interceptor (~51 lines)
- `engine/skills/builtin/narrative_skills.py` — 4 narrative skills (~215 lines)

**Modified:** `engine/agents/interceptors/__init__.py` (registered interceptor)
**Wired Into:** Realm (quest system), Lab Break (personality arcs)
**Inspired by:** OpenRoom's stage-based narrative system where AI characters progress through story stages with specific objectives that advance the plot

### What It Does

A **stage-based storytelling engine** where narratives have stages, each stage has targets
(objectives), and completing all targets in a stage auto-advances to the next. The current
stage's description is **injected into the agent's system prompt** via the
NarrativeModInterceptor, guiding the AI to follow the story.

### Data Model

```
NarrativeModEngine (singleton)
  └─ ModState (one per active narrative)
       ├─ mod_id: "realm_quest_missing_merchant"
       ├─ mod_name: "The Missing Merchant"
       ├─ stages: [ModStage, ModStage, ...]
       │    └─ ModStage
       │         ├─ stage_id: "act1"
       │         ├─ title: "Investigation"
       │         ├─ prompt_injection: "You are investigating..."
       │         └─ targets: [ModTarget, ...]
       │              └─ ModTarget
       │                   ├─ target_id: "find_clue"
       │                   ├─ description: "Find the hidden clue"
       │                   └─ completed: False
       ├─ stage_index: 0
       └─ is_finished: False
```

### Prompt Injection

The NarrativeModInterceptor (priority 15) runs **after** identity/scene injection (7-12)
but **before** skills (20+). It injects:

```
[NARRATIVE: The Missing Merchant — Stage 1/3: Investigation]
You are investigating the merchant's disappearance. The forest trail is dark
and overgrown. Listen for clues in the player's choices.
Current objectives:
  - Search the forest trail
  - Ask around the tavern
  - Follow the wagon tracks
```

### Usage

```python
from engine.mcp.narrative_mod import (
    ModStage, ModTarget, get_narrative_engine,
)

engine = get_narrative_engine()

# Start a narrative
mod = engine.start_mod(
    mod_id="bounty_hunter",
    mod_name="Bounty Hunter Fugue",
    stages=[
        ModStage(
            stage_id="act1",
            title="Reunion",
            description="The bounty hunter returns...",
            prompt_injection="You are reuniting with the player after years apart.",
            targets=[
                ModTarget(target_id="greet", description="Exchange introductions"),
                ModTarget(target_id="share_news", description="Share what happened"),
            ],
        ),
        ModStage(
            stage_id="act2",
            title="The Hunt",
            ...
        ),
    ],
    scene_id="realm",
    character_id="director",
)

# Complete targets — auto-advances stage when all targets done
engine.complete_target("bounty_hunter", "greet")
engine.complete_target("bounty_hunter", "share_news")
# → Stage auto-advances to "act2"
```

### Skills

| Skill | Description |
|-------|-------------|
| `start_narrative(mod_id, mod_name, stages_json)` | Start a new narrative mod |
| `complete_target(mod_id, target_id)` | Mark an objective as completed |
| `get_narrative_progress(mod_id)` | Get progress on active narratives |
| `advance_narrative_stage(mod_id)` | Force-advance to next stage (skip targets) |

### Scene Integrations

**Realm — Quest System:**
- `accept_library_quest()` → `engine.start_mod()` with branch options as targets
- `choose_quest_branch()` → `engine.complete_target()` for chosen branch
- Director receives quest context via prompt injection

**Lab Break — Personality Arcs:**
- Scene init → `engine.start_mod()` with 4 arc targets (trusting/hostile/resigned/desperate)
- `_check_personality_arc()` → `engine.complete_target()` on arc shift
- Door open → completes final stage target

### Events

The engine fires events that can be wired to SocketIO or other systems:

```python
engine.on_event(lambda e: print(e))
# Events: mod_started, mod_target_completed, mod_stage_advanced, mod_completed
```

---

## Feature 6: Character Creation Pipeline

**Status:** Shipped
**New Files:**
- `engine/creation/character_wizard.py` — 6-stage wizard (~351 lines)

**Inspired by:** OpenRoom's UGC character creation system with personality archetypes, appearance customization, voice selection, and story generation

### What It Does

A **6-stage character creation pipeline** that guides users through building a complete
AI character: archetype selection → appearance → voice → personality stats → backstory →
memory seeding. The result is a fully registered character with personality, backstory,
and seeded memories ready for any scene.

### The 6 Stages

```
[1] ARCHETYPE → [2] APPEARANCE → [3] VOICE → [4] STATS → [5] STORY → [6] MEMORY_SEED
     ↓                ↓              ↓            ↓           ↓              ↓
   companion      hair: silver    warm style    warmth:0.9  backstory     initial
   rival          eyes: violet    voice_aria    wit:0.7     generated     memories
   mentor         build: lean                   mystery:0.5               seeded
   trickster      scars: left                                             into RAG
   guardian       cheek
```

### 5 Archetypes

| Archetype | Personality | Tone | Traits |
|-----------|------------|------|--------|
| **Companion** | Warm 0.9, Curious 0.7, Playful 0.6 | Friendly, caring, occasionally teasing | Empathetic, loyal, encouraging, occasionally naive |
| **Rival** | Assert 0.9, Mystery 0.5, Warm 0.3 | Sharp, confident, backhanded compliments | Competitive, proud, secretly respectful, challenging |
| **Mentor** | Mystery 0.9, Curious 0.8, Warm 0.6 | Calm, measured, poetic | Wise, patient, cryptic, deeply caring underneath |
| **Trickster** | Playful 0.95, Curious 0.9, Mystery 0.7 | Quick-witted, flirtatious, chaotic | Mischievous, charismatic, unpredictable, secretly lonely |
| **Guardian** | Assert 0.8, Warm 0.6, Mystery 0.4 | Direct, serious, protective | Loyal, protective, stoic, unexpectedly gentle |

### Usage

```python
from engine.creation.character_wizard import get_character_wizard

wizard = get_character_wizard()

# Start creation
state = wizard.start("Aoi")

# Set archetype (auto-fills default personality)
wizard.set_archetype(state.wizard_id, "trickster")

# Customize appearance
wizard.set_appearance(state.wizard_id, {
    "hair": "electric blue, asymmetric cut",
    "eyes": "heterochromia — one gold, one silver",
    "build": "lean and agile",
    "distinguishing_features": "holographic tattoo on left forearm",
})

# Set voice
wizard.set_voice(state.wizard_id, "playful and unpredictable", "voice_aria")

# Adjust personality (overrides archetype defaults)
wizard.set_stats(state.wizard_id, {
    "warmth": 0.6,        # Slightly warmer than default trickster
    "mystery": 0.8,       # More mysterious
})

# Set backstory
wizard.set_backstory(state.wizard_id, """
    Aoi grew up in the neon-lit back alleys of District 9. She learned to pick
    pockets before she learned to read. Now she runs the most exclusive
    information brokerage in NeonCity — if you can find her.
""")

# Seed initial memories
wizard.set_seed_memories(state.wizard_id, [
    {"content": "I once stole a data crystal from the CEO of Axiom Corp", "category": "event"},
    {"content": "I have a hidden cache of credits in the old arcade", "category": "fact"},
    {"content": "I don't trust anyone who smiles too easily", "category": "observation"},
])

# Finalize — registers in CharacterRegistry + seeds memories in RAG
char_id = wizard.finalize(state.wizard_id)
# → "char-aoi-a3f21c"
```

### What Finalize Does

1. Generates character ID (`char-{name}-{hex}`)
2. Registers in **CharacterRegistry** with full personality, appearance, traits, tone
3. Seeds all provided memories into **RAGMemory** with importance 0.8
4. Auto-seeds backstory as a high-importance (0.9) fact memory
5. Cleans up the wizard session
6. Returns the character ID for immediate use in any scene

---

## Interceptor Pipeline (Updated)

With Features 2 and 5, the pipeline now has **28 interceptors**:

```
Pri  5 → NaturalMoodDrift          (neurochemistry tagging)
Pri  6 → NexusPrompt               (context hydration)
Pri  7–16 → Identity, scene injection, routing
  Pri 15 → NarrativeModInterceptor  ← NEW: stage context injection
Pri 20–70 → Skills, games, guardrails
Pri 80–93 → Post-call sync
  Pri 92 → SpectatorBroadcastInterceptor  ← NEW: danmaku broadcast
```

---

## File Summary

### New Files (18)

| File | Feature | Lines |
|------|---------|-------|
| `engine/services/spectator_bus.py` | Danmaku | 224 |
| `engine/agents/interceptors/spectator_broadcast.py` | Danmaku | 106 |
| `content/shared/static/js/cosysim-danmaku.js` | Danmaku | 226 |
| `content/shared/static/css/cosysim-danmaku.css` | Danmaku | 165 |
| `content/scenes/neonos/neonos_scene.py` | NeonOS | 313 |
| `content/scenes/neonos/templates/neonos.html` | NeonOS | 44 |
| `content/scenes/neonos/static/neonos.js` | NeonOS | 39 |
| `content/scenes/neonos/static/neonos.css` | NeonOS | 43 |
| `content/shared/static/js/cosysim-desktop.js` | NeonOS | 468 |
| `content/shared/static/css/cosysim-desktop.css` | NeonOS | 393 |
| `engine/nexus/filesystem.py` | Virtual FS | 513 |
| `engine/skills/builtin/fs_skills.py` | Virtual FS | 222 |
| `engine/mcp/narrative_mod.py` | Narrative | 340 |
| `engine/agents/interceptors/narrative_mod.py` | Narrative | 51 |
| `engine/skills/builtin/narrative_skills.py` | Narrative | 215 |
| `engine/creation/character_wizard.py` | Char Creator | 351 |
| `content/scenes/neonos/__init__.py` | NeonOS | 1 |
| `tests/test_neonos.py` | NeonOS | 49 |

### Modified Files (5)

| File | Feature | Change |
|------|---------|--------|
| `engine/skills/builtin/memory_skills.py` | Memory | Added save_memory, recall_about |
| `engine/agents/interceptors/__init__.py` | Danmaku, Narrative | Registered 2 new interceptors |
| `content/scenes/oracle/oracle_scene.py` | Danmaku | Added spectator API endpoint |
| `content/scenes/realm/realm_state.py` | Narrative | Wired quests to NarrativeModEngine |
| `content/scenes/lab_break/lab_break_scene.py` | Narrative | Wired arcs to NarrativeModEngine |

### Total

- **18 new files**, **5 modified files**
- **~3,800 new lines** of code
- **28 interceptors** (was 26)
- **~1,010 skills** (was ~1,000)
- **33 targets** (was 32 — NeonOS added)

---

## See Also

- [Architecture](ARCHITECTURE.md) — System design and three-pillar overview
- [Skills](SKILLS.md) — @skill decorator and governance system
- [Interceptors](INTERCEPTORS.md) — Pipeline hook reference
- [Scenes](SCENES.md) — Full scene catalog
- [Character System](CHARACTER_SYSTEM.md) — Personality and neurochemistry
- [ARGUS](ARGUS.md) — API discovery tools used for OpenRoom analysis
