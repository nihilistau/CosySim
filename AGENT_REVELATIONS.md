# AGENT_REVELATIONS.md — Living Design Audit

Generated: 2026-07-26  
Status: Active — updated as revelations emerge  
Purpose: Observations, patterns, anti-patterns, and design insights that accumulate  
into actionable system redesigns.

---

## Table of Contents

1. [The Three State Stores Problem](#1-the-three-state-stores-problem)
2. [Framework Adoption Is Wide But Shallow](#2-framework-adoption-is-wide-but-shallow)
3. [The Interceptor Pipeline Is The Real Engine](#3-the-interceptor-pipeline-is-the-real-engine)
4. [Scene Rules Engine: Half-Implemented Governor](#4-scene-rules-engine-half-implemented-governor)
5. [DialogSystem Is Production-Ready But Scenes Ignore It](#5-dialogsystem-is-production-ready-but-scenes-ignore-it)
6. [Clothing System: Built But Never Undressed](#6-clothing-system-built-but-never-undressed)
7. [Interaction Trees: Rich Data, Narrow Pipe](#7-interaction-trees-rich-data-narrow-pipe)
8. [ConversationHeat: The Secret Weapon Nobody Uses Fully](#8-conversationheat-the-secret-weapon-nobody-uses-fully)
9. [Thread Safety Gaps In Shared State](#9-thread-safety-gaps-in-shared-state)
10. [The Phone Scene Anti-Pattern](#10-the-phone-scene-anti-pattern)
11. [Cross-Scene Messaging Works But Has No Consumers](#11-cross-scene-messaging-works-but-has-no-consumers)
12. [MCPTimer vs Manual Threading](#12-mcptimer-vs-manual-threading)
13. [The Big Picture: What These Revelations Add Up To](#13-the-big-picture)
14. [Design: The Consequence Engine](#14-design-the-consequence-engine)
15. [Implementation Priority](#15-implementation-priority)
16. [Implementation Log](#16-implementation-log)
17. [_PhoneCharacterAgent Bypasses DialogSystem](#17-phonecharacteragent-bypasses-dialogsystem)

---

## 1. The Three State Stores Problem

**Severity: CRITICAL — This is the #1 architectural debt**

Character state lives in THREE places that don't sync:

| Store | What it holds | Persistence | Who reads | Who writes |
|-------|--------------|-------------|-----------|------------|
| **Database** (db.py) | name, age, sex, personality_id, conversations | SQLite ✓ | Everyone on load | Only DB CRUD |
| **CharacterRegistry** | mood, energy, inhibition, skills, restrictions, flags | Memory only ✗ | Interceptors, rules engine | Scenes, interceptors |
| **SceneStateManager** | clothing, arousal, stats dict, narrative, timed actions | Memory only ✗ | Scenes, interceptors | Scenes, rules engine |

**The problem:**
- Registry changes are **never written back to DB**. Restart = total amnesia.
- SceneStateManager stats and Registry mood can **contradict each other**.
  A scene sets `arousal=80` in SSM while Registry says `mood=bored`.
- Interceptors read from Registry; scenes write to SSM. They're talking past each other.
- No single `get_full_character_state()` call exists.

**The fix (Revelation → Design):**
Create a **CharacterStateCoordinator** — single write-through API:
```
coordinator.update(char_id, mood="flirty", arousal=+10, energy=-5)
  → writes to Registry (runtime state)
  → writes to SSM (scene-visible stats)  
  → optionally persists to DB (configurable: every N changes or on scene exit)
  → emits event on ActivityBus ("state_changed", char_id, deltas)
```

Every scene and interceptor goes through this. No more direct Registry/SSM writes.

---

## 2. Framework Adoption Is Wide But Shallow

**Severity: MODERATE — Structural, not breaking**

All 11 scenes inherit `MCPSceneMixin`. All wire `_mcp_init()`. All import TagRegistry
and SceneStateManager. **But most don't actually use the framework's power features.**

| Feature | Available | Actually Used By |
|---------|-----------|-----------------|
| MCPSceneMixin | All 11 scenes | All 11 (lifecycle only) |
| Governor/Interceptors | All scenes | Bedroom ✓, Phone ✓, Lounge ✓, Casino ✓ |
| SceneRulesEngine | Bedroom, Phone, Lounge | Bedroom (director tools only) |
| DialogSystem | Full API ready | Interceptors only (no scene calls it directly) |
| ConversationHeat | Phone, Lounge | Phone (autotxt decisions) |
| SceneStateManager.clothing | Bedroom | **Nobody** (methods exist, never called) |
| SceneStateManager.timed_actions | Registered in skills | MCP server only |
| Consequence scheduling | Lounge, Casino, NeonCity | ~4 scenes lightly |
| Cross-scene messaging | Lounge | 1 scene |
| MCPTimer | 8 file imports | Lounge, Bedroom, Casino |
| InteractionTree phases | 12 types × 5 subtypes | 1 function call only |

**Pattern:** Scenes import the framework, initialize it, then proceed to hardcode
their own logic. The framework is a "pass-through" not a "driver."

**The fix:** Scenes should be THIN — declare rules, register handlers, provide templates.
The framework drives behavior. See §14 for the design.

---

## 3. The Interceptor Pipeline Is The Real Engine

**Severity: POSITIVE — This works well**

The 17-interceptor pipeline (priority 8→92) is the **best-integrated part of the system**.
Every governor-wrapped agent call flows through it. It actually works:

- CharacterRegistryInterceptor (8) → identity injection
- Scene interceptors (15) → context injection  
- GameInterceptor (35) → game state
- PersonalityGuardInterceptor (50) → tone enforcement
- ConversationVarietyInterceptor (55) → anti-repetition
- ResponseShaperInterceptor (80) → cleanup
- MoodSyncInterceptor (92) → state writeback

**But there's a gap:** The pipeline only fires on **governor-wrapped calls**. Any scene
that calls VAM directly (fallback paths in phone, some bedroom paths) **bypasses all
interceptors**. This means personality, rules, variety, mood sync — all skipped.

**The fix:** Make governor wrapping **mandatory**. Remove all direct VAM call paths from
scenes. If governor fails, the call fails — don't silently degrade.

---

## 4. Scene Rules Engine: Half-Implemented Governor

**Severity: HIGH — Infrastructure without teeth**

The SceneRulesEngine is a **1,255-line declarative rules system** that can:
- Define rules with conditions (stat thresholds, flags)
- Execute effects (stat adjust, set directive, add narrative, assign skill)
- Gate actions by permission matrix
- Auto-trigger on threshold crossing

**Reality:**
- `apply_rule()` works but is only called by **Director tools** (manual trigger)
- `evaluate_threshold_rules()` exists but **has no call site** — nobody auto-fires rules
- Rules are "always_on" text blobs injected into prompts, not executable constraints
- The permission matrix gates actions but **no scene checks permissions before acting**

**This means:** The engine can say "arousal > 60 → unlock intimate actions" but nobody
asks it "is this action allowed?" before doing the action. Rules are advisory, not enforced.

**The fix:** Wire `evaluate_threshold_rules()` into the interceptor pipeline. After every
response, check if any stat thresholds crossed. If so, auto-fire the rule effects.
This turns passive rules into **active governors**.

---

## 5. DialogSystem Is Production-Ready But Scenes Ignore It

**Severity: MODERATE — Wasted capability**

The DialogSystem (1,075 lines) provides:
- `ResponseDirective` types: force_response, must_include, style_lock, topic_steer, mood_set, refuse
- `SpeechEnhancer` with voice style rewriting
- Dialog trees with branching nodes
- Conversation state tracking

**Who uses it:** Interceptors (DialogDirectiveInterceptor), MCP server tools, social skills.
**Who doesn't:** Bedroom scene (hardcodes dialogue injection), Phone scene (hardcodes system prompt).

**The insight:** Scenes manually construct system prompts with personality/mood/stats when
DialogSystem could build these automatically from character profile + current state.

---

## 6. Clothing System: Built But Never Undressed

**Severity: LOW — Dead code, no harm**

SceneStateManager has a complete clothing system:
- `ClothingItem` with layer, coverage_map, removal_order
- `CharacterWardrobe` with add/remove/re_dress
- Layer-based ordering (underwear < clothing < outerwear < accessories)

**Usage:** `initialise_wardrobe()` is called in bedroom setup.
`remove_clothing()`, `remove_outermost()`, `re_dress()` — **zero calls in entire codebase**.

The bedroom scene tracks outfit state as a simple string (`"lingerie"`, `"nothing"`)
instead of using the wardrobe system.

**The fix:** Either wire it into bedroom (track outfit changes through wardrobe API)
or remove it. Dead code is confusing code.

---

## 7. Interaction Trees: Rich Data, Narrow Pipe

**Severity: MODERATE — Underutilized content**

`interaction_trees.py` defines 12 interaction types with:
- 4-5 subtypes each (e.g., kiss → peck, deep_kiss, neck_kiss, passionate, playful)
- Stat effects per subtype (arousal +5, happiness +10, etc.)
- Stat requirements (deep_kiss requires arousal ≥ 25)
- Narrative fragments (flavor text the agent can use)
- Phase progression (build-up → peak → afterglow)

**All of this** flows through a single function: `get_interaction_result()` in cosysim_server.py.
The phases, fragments, and progression system are **data that nobody reads**.

**The fix:** InteractionTree should drive a **multi-turn interaction sequence**:
1. Agent announces intent → tree checks requirements
2. Tree selects phase fragments → injected as DialogDirective
3. Stat effects applied progressively (not all at once)
4. Consequences scheduled for aftereffects

This turns static data into dynamic gameplay.

---

## 8. ConversationHeat: The Secret Weapon Nobody Uses Fully

**Severity: MODERATE — Easy win**

ConversationHeat (0-100 scale) is a **thermal model** that:
- Auto-bumps from keywords ("flirt" +8, "kiss" +15, "intimate" +20)
- Decays over time (-2/min after 30s idle)
- Generates tier directives: Normal / WARM / HOT / INTENSE

**Usage:** Phone scene uses it for autotxt tone decisions. ConversationVarietyInterceptor
reads it for system prompt injection.

**What nobody does:**
- Bedroom doesn't use heat at all (uses manual arousal stat instead)
- No scene uses heat to **gate interactions** (heat < 30 = no intimate options)
- No scene uses heat for **pacing** (heat climbing too fast = slow down directive)
- Heat never triggers **SceneRulesEngine** consequences

**The fix:** Make heat a first-class stat that feeds into rules engine:
```
rule: heat > 60 AND mood != "resistant" → unlock "intimate" action set
rule: heat > 80 → inject "passionate energy" directive
rule: heat drops below 20 after being > 60 → inject "awkward cooldown" narrative
```

---

## 9. Thread Safety Gaps In Shared State

**Severity: HIGH — Can cause corruption under load**

Found during audit:

1. **ConversationVarietyInterceptor._recent_responses** — `Dict[str, List[str]]` shared
   across threads, modified in post_process. No lock. If two agents respond simultaneously,
   dict mutation during iteration → RuntimeError.

2. **CharacterRegistry state updates** — `set_state()` modifies `CharacterRecord.state`
   attributes individually. No atomic update. Two interceptors updating the same character
   in different threads could interleave writes.

3. **SceneStateManager.update_stats()** — Reads current stats, applies deltas, writes back.
   Not atomic. Two concurrent delta applications could lose one.

**The fix:** 
- Add `threading.Lock` to ConversationVarietyInterceptor per-character
- Make CharacterRegistry updates atomic (lock per character_id)
- Make SSM stat updates use compare-and-swap or per-character lock

---

## 10. The Phone Scene Anti-Pattern

**Severity: HIGH — Template for what NOT to do**

Phone scene maintains a **parallel universe** of state:

| Framework provides | Phone uses instead |
|---|---|
| ConversationManager | PhoneDB message tables |
| SceneStateManager stats | PhoneDB game state |
| MCPGameSession | Manual game CRUD |
| MCPTimer scheduling | `_ticker_loop()` with threading.Thread |
| DialogSystem prompts | Hardcoded system prompt strings |
| ActivityBus events | Manual Socket.IO emissions |

The phone scene is essentially a **standalone Flask app** that happens to import
the framework for governor wrapping. Everything else is parallel implementation.

**Why this matters:** Any framework improvement (better memory, cross-scene messaging,
unified state) **doesn't benefit the phone scene** because it doesn't use the framework.

**The fix:** Phone needs a rewrite where PhoneDB becomes a thin persistence layer
and all runtime state flows through the framework. The DB stores messages; the
framework manages character state, scheduling, game sessions, and dialogue.

---

## 11. Cross-Scene Messaging Works But Has No Consumers

**Severity: LOW — Feature waiting for scenes**

`MCPFramework.cross_scene_send()` works. `RouterMessageInjector` (priority 10)
drains the inbox and injects messages. The Lounge uses it for Viktor↔Lola.

**But:** No scene-to-scene messaging exists. Characters can't text someone in another
scene. The phone scene (the natural place for this) doesn't use it.

**The fix:** Wire phone scene's autonomous messaging through cross_scene_send.
When Lola in the lounge wants to text the player, she sends a cross-scene message
that appears in the phone scene. This is the whole point of the framework.

---

## 12. MCPTimer vs Manual Threading

**Severity: MODERATE — Inconsistency**

MCPTimer exists and is used by 4-5 scenes. But the phone scene runs its own
`_ticker_loop()` with `threading.Thread(daemon=True)`. The bedroom's `AgentLoop`
has its own tick cycle. Casino has manual timing for round clocks.

**The pattern:** Every scene that needs periodic behavior reinvents threading.
MCPTimer was built to solve this but adoption is incomplete.

---

## 13. The Big Picture

**What all these revelations add up to:**

The CosySim framework is **architecturally sound but operationally fragmented**.
The right abstractions exist (rules engine, dialog system, state manager, interceptors,
timers, game sessions, interaction trees, conversation heat). But scenes were built
before or alongside these systems and never fully migrated.

The result is a **dual-track system**: the framework provides one way to do things,
and scenes have their own way. Both work independently but don't reinforce each other.

**The core realization:**

> Every scene should be a **thin declarative shell** that registers rules, handlers,  
> and templates. The framework should drive ALL behavior. Scenes shouldn't contain  
> logic — they should contain **configuration**.

This is the difference between:
```python
# CURRENT: Scene contains logic
class BedroomScene:
    def on_kiss(self):
        self.stats["arousal"] += 8
        self.stats["happiness"] += 5
        self.agent.inject("She felt a rush of warmth...")
```

vs:

```python
# TARGET: Scene declares rules, framework executes
bedroom_rules = {
    "kiss": {
        "requires": {"arousal": 15, "trust": 30},
        "effects": {"arousal": +8, "happiness": +5},
        "narrative": "A rush of warmth...",
        "unlocks": ["deep_kiss", "neck_kiss"],
        "cooldown": 30
    }
}
```

The framework already supports the second pattern. Scenes just don't use it.

---

## 14. Design: The Consequence Engine

**This is where revelations become architecture.**

Taking everything above, the unified fix is a **Consequence Engine** — a single
system that replaces scattered state updates, manual threading, and hardcoded logic:

```
┌─────────────────────────────────────────────────────────────┐
│                    CONSEQUENCE ENGINE                         │
│                                                               │
│  Input:  action/event + context                              │
│  Output: state changes + directives + narrative + scheduling │
│                                                               │
│  ┌──────────┐    ┌───────────────┐    ┌──────────────┐      │
│  │ Rules    │───►│ Condition     │───►│ Effect       │      │
│  │ Engine   │    │ Evaluator     │    │ Executor     │      │
│  └──────────┘    └───────────────┘    └──────┬───────┘      │
│                                              │               │
│                    ┌─────────────────────────┬┘              │
│                    ▼                         ▼               │
│            ┌──────────────┐         ┌──────────────┐        │
│            │ State        │         │ Scheduler    │        │
│            │ Coordinator  │         │ (MCPTimer)   │        │
│            │ (unified)    │         │              │        │
│            └──────┬───────┘         └──────────────┘        │
│                   │                                          │
│         ┌─────────┼─────────┐                               │
│         ▼         ▼         ▼                               │
│   CharRegistry  SSM Stats  Database                         │
│   (runtime)     (scene)    (persist)                        │
│                                                               │
│  Triggers:                                                    │
│  • Agent response (post-interceptor) → auto-evaluate         │
│  • Player action → evaluate prerequisites, apply effects     │
│  • Timer expiry → scheduled consequence fires                │
│  • Stat threshold crossed → threshold rules auto-fire        │
│  • Cross-scene message → route + apply effects               │
│                                                               │
│  Hooks into:                                                  │
│  • InterceptorPipeline (MoodSyncInterceptor replacement)     │
│  • ConversationHeat (auto-bump from actions)                 │
│  • InteractionTree (multi-turn sequence driver)              │
│  • DialogSystem (directive injection)                        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

**What this replaces:**
- Manual stat updates in bedroom (hardcoded `stat_drifts` map)
- Manual game state in phone (PhoneDB CRUD)  
- Manual threading in phone (`_ticker_loop`)
- Orphaned `evaluate_threshold_rules()` in rules engine
- Scattered narrative logging
- Unsynced state across Registry/SSM/DB

**What scenes become:**
```python
class BedroomScene(BaseScene, MCPSceneMixin):
    def setup(self):
        # Register rules (declarative)
        self.engine.register_rules(BEDROOM_RULES)
        # Register interaction sequences
        self.engine.register_interactions(BEDROOM_INTERACTIONS)
        # Register consequence chains
        self.engine.register_consequences(BEDROOM_CONSEQUENCES)
        # Register templates
        self.register_template("bedroom.html")
        # That's it. Framework drives everything else.
```

---

## 15. Implementation Priority

Based on impact vs effort:

### Phase A: Wire What Exists (no new code needed)
1. **Wire `evaluate_threshold_rules()`** into MoodSyncInterceptor (post-process)
   - After mood syncs, check threshold rules → fire effects
   - Effort: ~20 lines in interceptors.py

2. **Remove direct VAM fallback paths** from phone scene
   - Force all calls through governor
   - Effort: ~10 lines deleted

3. **Add threading.Lock** to ConversationVarietyInterceptor
   - Effort: ~5 lines

### Phase B: Unify State (CharacterStateCoordinator)
4. **Build CharacterStateCoordinator**
   - Single API for all state mutations
   - Writes through to Registry + SSM + optional DB persist
   - Effort: New file, ~200 lines

5. **Migrate bedroom stat updates** to coordinator
   - Replace `self.stats["arousal"] += 8` with `coordinator.update(...)`
   - Effort: ~50 lines changed

### Phase C: Activate Framework Features
6. **Wire ConversationHeat into bedroom** 
   - Replace manual arousal tracking with heat-based unlocks
   - Effort: ~30 lines

7. **Wire InteractionTree phases** into DialogDirective
   - Multi-turn sequences with progressive stat application
   - Effort: ~100 lines new, ~50 lines in bedroom

8. **Phone scene framework migration** (biggest single task)
   - Replace PhoneDB runtime state with framework
   - Keep PhoneDB for message persistence only
   - Effort: ~500 lines refactored

### Phase D: Consequence Engine
9. **Build ConsequenceEngine** that unifies all of the above
   - Effort: New file, ~400 lines
   - Replaces scattered logic across all scenes

---

## Appendix: Quick Wins Identified

| Fix | File | Lines | Impact |
|-----|------|-------|--------|
| Thread lock on _recent_responses | interceptors.py | +5 | Prevents crash |
| Remove VAM fallback in phone | phone_scene_v2.py | -15 | Forces framework |
| Wire threshold rules | interceptors.py | +20 | Activates rules engine |
| Use wardrobe OR delete it | scene_state.py | ±0 | Reduces confusion |
| ConversationHeat in bedroom | bedroom_scene.py | +30 | Better pacing |
| Sync Registry → DB on scene exit | character_registry.py | +40 | State persistence |

---

*This document is alive. New revelations are appended as they emerge.*
*When revelations cluster around a theme, they get promoted to a Design section.*


---

## 16. Implementation Log

### Phase B.4 — CharacterStateCoordinator: COMPLETE

**File:** `engine/mcp/state_coordinator.py` (280 lines)

**What it does:**
- Single `update(char_id, **fields)` API that auto-routes fields to the right store
- Registry fields (mood, energy, inhibition) -> CharacterRegistry.set_state()
- Stats fields (arousal, happiness, etc.) -> SceneStateManager.update_stats() or set_stats()
- Unknown fields -> Registry flags
- Restrictions -> add_restriction / remove_restriction
- Supports `mode="delta"` (default) and `mode="set"` (absolute)
- Emits `state_changed` event to ActivityBus + registered listeners
- Optional `persist=True` writes to database
- Per-character threading.Lock for safe concurrent updates

**Wired into:**
- `MoodSyncInterceptor` (priority 92) — mood sync now goes through coordinator
- `SceneRulesEngine._execute_effect()` — stat_adjust, state_set, restrictions all routed
- `cosysim_server.py` — `_coord()` helper + update_character_scene_stats + set_character_scene_stat

**Tests:** 22 new tests covering field routing, restrictions, events, full state snapshot,
graceful degradation, thread safety, singleton, field classification.

**Status:** Revelation #1 (Three State Stores) is now PARTIALLY RESOLVED.
The coordinator exists and high-traffic paths use it. Remaining: migrate all
scattered `set_state()` / `update_stats()` calls in scenes to use `_coord()`.

### Phase B.8 — ConversationHeat in Bedroom: COMPLETE

**File:** `engine/agents/interceptors.py` (BedroomSceneInterceptor.pre_call)

**What it does:**
- Reads ConversationHeat for the current conversation key
- Injects heat-level directive and pacing guidance into system prompt
- Gates content explicitness based on thresholds:
  - <30: Suggestion and innuendo only
  - 30-60: Mild explicit, flirting encouraged
  - 60-80: Explicit content allowed, escalation encouraged
  - ≥80: Fully explicit, intense emotional expression

**Status:** Revelation #8 RESOLVED.

### Phase B.10 — Remove Phone VAM Fallback: COMPLETE

**File:** `content/scenes/phone/phone_scene_v2.py` (_generate_reply)

**What was removed:** 47-line fallback block (lines 432-480) that bypassed the
governor and all 17 interceptors when the governor threw an exception. This was
the primary anti-pattern where phone scene calls could skip the entire framework.

**What replaced it:** Clean error handler (3 lines) — logs the error and returns
a user-friendly fallback message. All phone AI must now go through the governor.

**Status:** Revelation #10 RESOLVED.

### New Feature — Overlay State/Heat APIs: COMPLETE

**File:** `engine/overlay/overlay_bp.py` (3 new endpoints)

- `GET /api/character/<id>/state` — unified state via CharacterStateCoordinator
- `POST /api/character/<id>/state` — update fields via coordinator (delta/set mode)
- `GET /api/heat?key=X` — conversation heat levels (single key or all)

These endpoints give admin panels, debugging tools, and external integrations
direct access to the unified state layer and heat system without touching internals.

---

## 17. _PhoneCharacterAgent Bypasses DialogSystem

**Severity: MEDIUM — Duplicate prompt engineering**

While removing the VAM fallback (Revelation #10), I noticed that `_PhoneCharacterAgent.reply()`
at line 106 constructs its own hardcoded system prompt:

```python
system = (
    f"You are {name}. {pers}\n"
    "Reply naturally as a real person texting. Keep messages short and conversational.\n"
    "Use emojis naturally. Be expressive and emotionally vivid.\n"
    ...
)
```

This means the phone scene's character dialogue NEVER goes through `DialogSystem.build_prompt()`,
which provides:
- Personality profile loading from DB
- Speech pattern injection from character config
- DialogDirective-based tone/style control
- Scene-appropriate vocabulary constraints
- Interaction tree phase awareness

**Impact:** Phone characters sound generic. They don't benefit from the personality
system, speech patterns, or any of the interceptor-injected directives that bedroom
characters get. The governor fires interceptors but the agent's own system prompt
overwrites whatever the interceptors were trying to inject.

**Fix:** Make `_PhoneCharacterAgent` use `DialogSystem.build_prompt()` or accept
the governor's system prompt instead of building its own. The governor already injects
interceptor context via `governance_context` kwarg — the agent just needs to USE it
instead of constructing a fresh prompt from scratch.

**Effort:** ~30 lines changed in `_PhoneCharacterAgent.reply()`


---

## 18. Sprint 1 Audit Results

**Date:** 2026-02-24
**Scope:** Full 6-subsystem audit (~51,000 lines of Python)

### Bugs Found & Fixed
- **BUG-001 (CRITICAL):** resource_manager.py returned undefined \success\ variable.
  Every model load via ResourceManager raised NameError. Fixed: eturn result.status == 'loaded'\.
- **BUG-002:** pipeline_result.py \pipeline_started = time.time()\ at class definition.
  Already fixed (uses field(default_factory=time.time)).
- **BUG-003:** config.py set() doesn't create nested dicts. Already fixed.

### Port Conflicts Found & Fixed
- Realm (5562) and Heist (5562) shared port → Heist moved to 5565
- NeonCity (5563) and CommandCenter (5563) shared port → CmdCtr moved to 5566

### Code Quality Issues Fixed
- framework.py: 5 bare \xcept Exception: pass\ blocks → now log via logger.debug
- housekeeping.py: Invalid type hint \ny\ → \Any- overlay_bp.py: Used private \SKILL_REGISTRY._skills\ → now uses public API

### Key Insight from Audit
**The framework-adoption gap is THE core problem.** The MCP framework provides 15+
sophisticated subsystems. Only 4 of 11 scenes use the Governor/Interceptor pipeline.
ALL scenes bypass DialogSystem. The gap between available features and used features
is where all the value is locked up.

### Design Document Created
\docs/ProjectNext/Project-CozyDreamz.md\ — Complete dream architecture with:
- 7-sprint implementation plan
- Framework adoption matrix (every scene × every feature)
- Target architecture diagrams
- Component documentation
- Scene migration plans


---

## 19. Phone Scene: governance_context Was Accepted But Ignored

**Discovery:** The governor passes governance_context to every agent's 
eply() method.
The Phone's _PhoneCharacterAgent.reply() accepted it in **_kwargs — meaning all 17
interceptor injections (personality, heat, variety, mood sync, etc.) were silently discarded
on every single phone reply.

**Fix:** Made governance_context an explicit kwarg, merged it with the base system prompt.
Now the phone agent gets: base identity + interceptor injections + scene context.

**Pattern:** Any scene with a custom agent class must explicitly accept and use
governance_context. Grep for **_kwargs in reply methods to find others.

---

## 20. Bedroom Stats: Direct Writes Bypass Cross-System Sync

**Discovery:** The bedroom's _on_agent_action() calls self.profiles[cid].stats.adjust()
directly. This updates the local profile stats but never touches:
- CharacterRegistry (mood, energy)
- SceneStateManager (the global stats snapshot)
- ActivityBus (no state_changed events)

The CharacterStateCoordinator was built to solve exactly this — unified write-through
to all stores — but the bedroom (the most stat-heavy scene) never used it.

**Fix:** Added get_coordinator().update(character_id, **deltas) before the local
adjust call. Now stat changes from agent actions propagate everywhere.

**Impact:** The overlay /character_state endpoint, interceptors reading from SSM,
and any cross-scene stat queries now see bedroom stat changes in real-time.

---

## 21. Framework Adoption Audit: 0/10 Scenes Use ConversationHeat

**Discovery:** Full audit of all 10 scenes reveals:
- MCPSceneMixin: 10/10 (100%) — universal
- SceneStateManager: 9/10 (90%) — only Coders Room missing
- Interceptor Pipeline: 9/10 (90%)
- AgentGovernor: 2/10 (20%) — only Bedroom & Lounge
- DialogSystem: 2/10 (20%) — only Lounge & Gallery
- ConversationHeat: 0/10 (0%) — ZERO scenes use it
- CharacterStateCoordinator: 0/10 (0%) — ZERO scenes use it

**The adoption funnel:** Scenes adopt the easy stuff (mixin, state manager) but not
the sophisticated stuff (governor, dialog, heat, coordinator). This is the #1 gap.

**Fix path:** Wire heat into Phone interceptor (done), wire coordinator into Bedroom
(done). Next: Gallery, Warzone, Realm need governor adoption.

---

## Implementation Log (Sprint 2)

| Date | Revelation | Action | Status |
|------|-----------|--------|--------|
| Sprint 2 | #19 Phone governance_context | governance_context now explicit + merged | ✅ Done |
| Sprint 2 | #20 Bedroom stat writes | Coordinator.update() before local adjust | ✅ Done |
| Sprint 2 | #21 Adoption audit | ConversationHeat wired into PhoneSceneInterceptor | ✅ Done |

---

## 22. Gallery Can't Use Governor — Architecture Gap

**Discovery:** Gallery scene calls `mgr.infer_processed()` with streaming callbacks
(`on_delta`, `on_mood`, `on_image`). The governor's `tell()` returns a plain string,
losing all tag extraction callbacks. This is why Gallery (and any streaming scene)
can't adopt the full governor path.

**Workaround:** Created `_get_governor_context()` helper that gathers framework state
(mood, heat, narrative) and injects into the system prompt before the VAM call.
This gets ~70% of the governor benefit (interceptor-equivalent context) without
breaking the streaming pipeline.

**Root cause:** The governor was designed for request/response, not streaming.
The VirtualPipeline (planned Part 2) will solve this by being stream-native.

---

## 23. NeonCity _sync_to_mcp() Was Calling Invalid API

**Discovery:** NeonCity's `_sync_to_mcp()` called `self._state_mgr.update_stats(SCENE_ID, turn=..., round=..., storm_radius=...)`. But `update_stats()` takes a `character_id` and `StatsSnapshot` fields — passing a scene_id and arbitrary kwargs did nothing (silently ignored by kwargs).

**Fix:** Replaced with `add_narrative()` which is the correct API for scene-level state logging.

**Pattern:** SSM's `update_stats()` is character-scoped. For scene-level state, use `add_narrative()` or store in scene's own state dict.

---

## 24. Bedroom Clothing System: Functional But Not Framework-Integrated

**Discovery:** The bedroom has a working clothing system: `OUTFITS` list, `/api/character/outfit` endpoint, outfit tracking in `CharacterProfile`, outfit display in prompts. SSM has a `CharacterWardrobe` API (`add_outfit`, `set_current`, `get_wardrobe`) that is more sophisticated but unused by bedroom.

**Decision:** Keep bedroom's simpler outfit system. It works, it's tested, and it feeds into the agent prompt. The SSM wardrobe is designed for complex inventory scenes (like a fashion/shopping scene). The two can coexist — bedroom uses strings, a future scene could use the full wardrobe API.

---

## 25. InteractionRecord Logging Gaps

**Discovery:** Bedroom tracks physical interactions (flirt, kiss, intimate, cuddle, touch) via stat changes and agent prompts, but never logged them as structured `InteractionRecord` objects in SSM. This meant:
- No interaction history queryable via SSM
- No cross-scene awareness of interaction patterns
- No data for ConversationHeat auto-bumping from physical actions

**Fix:** Added `ssm.log_interaction()` calls for all physical interaction types with appropriate metadata. Now interaction history is available to interceptors, heat system, and cross-scene queries.

---

## Implementation Log (Sprint 3)

| Date | Revelation | Action | Status |
|------|-----------|--------|--------|
| Sprint 3 | #22 Gallery governor gap | _get_governor_context() helper + Coordinator sync | Done |
| Sprint 3 | #23 NeonCity invalid API | Fixed update_stats() -> add_narrative() | Done |
| Sprint 3 | #24 Clothing system audit | Keep simple system, document decision | Done |
| Sprint 3 | #25 InteractionRecord gaps | Added ssm.log_interaction() for physical actions | Done |
| Sprint 3 | N/A | Warzone: Coordinator mood sync for AI commander | Done |
| Sprint 3 | N/A | Realm: Coordinator sync for stat changes + narrative | Done |
| Sprint 3 | N/A | Heist: Coordinator mood sync for crew replies | Done |

### Updated Framework Adoption (Post-Sprint 3)

| Feature | Adoption | Change |
|---------|----------|--------|
| MCPSceneMixin | 10/10 (100%) | unchanged |
| SceneStateManager | 10/10 (100%) | unchanged |
| Interceptor Pipeline | 9/10 (90%) | unchanged |
| CharacterStateCoordinator | 6/10 (60%) | was 1/10 |
| AgentGovernor | 2/10 (20%) | unchanged (Gallery uses helper instead) |
| ConversationHeat | 1/10 (10%) | was 0/10 |
| DialogSystem | 2/10 (20%) | unchanged |

---

## 26. Action-Based Heat Bumping: A Missing Feedback Loop

**Discovery:** ConversationHeat was only bumped by analyzing text content in
`ConversationVarietyInterceptor.post_call()`. Physical interactions (kiss, touch,
dance, etc.) detected in `[ACTION:xxx]` tags never affected heat. This meant the
pacing system was blind to the most significant escalation signals.

**Fix:** Added `_ACTION_HEAT` map and `_bump_heat_from_actions()` to
MoodSyncInterceptor. Now when parsed responses contain action tags matching
physical keywords, heat auto-bumps (e.g., kiss=+15, touch=+10, flirt=+6).

**Impact:** ConversationHeat now captures both verbal (text analysis) and
non-verbal (action tags) escalation. Pacing directives become much more
responsive to actual scene dynamics.

---

## 27. Gallery Had No Scene Interceptor

**Discovery:** Gallery was the only scene with framework adoption (MCPSceneMixin,
SSM) but no scene-specific interceptor. This meant gallery curator agents never
received framework context (mood, narrative, heat) in their prompts.

**Fix:** Created GallerySceneInterceptor (priority 15) that injects Coordinator
mood state, scene narrative, and ConversationHeat pacing into gallery agent prompts.
Pipeline now has 20 interceptors (was 19).

---

## 28. Registry State Amnesia on Restart

**Discovery:** CharacterRegistry is in-memory only. All runtime state (mood, energy,
inhibition, flags, restrictions) is lost on restart. The database has a
`character_states` table with mood, energy, arousal columns, but nothing writes to it.

**Fix:** Added `persist_to_db()` method on CharacterRegistry that writes all
registered characters' runtime state back to the database. Wired into `BaseScene.stop()`
so persistence happens automatically when any scene shuts down.

---

## Implementation Log (Sprint 4)

| Date | Revelation | Action | Status |
|------|-----------|--------|--------|
| Sprint 4 | #26 Action heat bumping | _ACTION_HEAT map + _bump_heat_from_actions() | Done |
| Sprint 4 | #27 Gallery no interceptor | Created GallerySceneInterceptor (priority 15) | Done |
| Sprint 4 | #28 Registry amnesia | persist_to_db() + BaseScene.stop() auto-persist | Done |
| Sprint 4 | N/A | ConversationHeat wired into Lounge interceptor | Done |
| Sprint 4 | N/A | Thread safety + threshold rules already implemented (verified) | Done |

### Updated Framework Adoption (Post-Sprint 4)

| Feature | Adoption | Change |
|---------|----------|--------|
| MCPSceneMixin | 10/10 (100%) | unchanged |
| SceneStateManager | 10/10 (100%) | unchanged |
| Interceptor Pipeline | 10/10 (100%) | Gallery now has interceptor |
| CharacterStateCoordinator | 6/10 (60%) | unchanged |
| AgentGovernor | 2/10 (20%) | unchanged |
| ConversationHeat | 4/10 (40%) | Bedroom, Phone, Lounge, Gallery |
| DialogSystem | 2/10 (20%) | unchanged |
| Registry Persistence | 10/10 (100%) | NEW: auto-persist on scene stop |

---

## 29. No Cross-Scene Narrative Continuity

**Discovery:** When a player moves between scenes, agents have zero awareness
of where the player was before or what they were doing. A character in the
bedroom has no idea the player just left the lounge after an intense conversation.
This breaks narrative immersion.

**Fix:** Added scene transition tracking to MCPFramework:
- `record_scene_visit()` logs each scene visit with timestamp
- `get_player_journey()` returns recent visit history
- `get_previous_scene()` returns last scene
- MCPSceneMixin._mcp_init() auto-records visits
- RouterMessageInjector injects "(player just came from X scene)" into system prompts

Now agents naturally know the player's journey and can reference it.

---

## 30. Codebase is Clean — Minimal Dead Code

**Audit result:** Full dead code audit of engine/ and content/ found:
- 0 unused/unimported files
- 0 deprecated/legacy named files
- Only 2 TODO/FIXME comments (triton deployment + video lip sync)
- All __init__.py files have content
- __pycache__ properly gitignored

The codebase is well-maintained. No cleanup needed.

---

## Implementation Log (Sprint 5)

| Date | Revelation | Action | Status |
|------|-----------|--------|--------|
| Sprint 5 | #29 No narrative continuity | Scene transition tracking + journey injection | Done |
| Sprint 5 | #30 Dead code audit | Full audit — codebase clean | Done |
| Sprint 5 | N/A | 5 new tests for journey tracking | Done |

### Updated Framework Adoption (Post-Sprint 5)

| Feature | Adoption | Change |
|---------|----------|--------|
| MCPSceneMixin | 10/10 (100%) | now auto-records scene visits |
| SceneStateManager | 10/10 (100%) | unchanged |
| Interceptor Pipeline | 10/10 (100%) | unchanged |
| CharacterStateCoordinator | 6/10 (60%) | unchanged |
| AgentGovernor | 2/10 (20%) | unchanged |
| ConversationHeat | 4/10 (40%) | unchanged |
| DialogSystem | 2/10 (20%) | already wired via DialogDirectiveInterceptor |
| Registry Persistence | 10/10 (100%) | unchanged |
| Scene Transition Tracking | 10/10 (100%) | NEW: auto via MCPSceneMixin |

---

## 31. Six Scenes Have Zero Scene-Specific Interceptors

**Discovery:** Framework audit revealed that Casino, Warzone, Realm, NeonCity,
Coders Room, and Heist had NO scene-specific interceptors. The pipeline ran all
generic interceptors (CharacterRegistry, PersonalityGuard, etc.) but no scene
context was injected — no mood, no narrative, no ConversationHeat, no atmosphere.

**Design decision:** Rather than creating 6 individual interceptors (each ~80 lines
of near-identical code), created a **UniversalSceneInterceptor** (priority 16) that
acts as a catch-all. It skips scenes with dedicated interceptors (bedroom, phone,
lounge, gallery) and injects Coordinator mood, scene narrative, atmosphere,
ConversationHeat, and available MCP actions for all other scenes.

**Impact:** Scene-specific interceptor coverage went from 4/10 to 10/10.
ConversationHeat coverage went from 4/10 to 10/10. All in one 100-line class.

**Pattern:** This is the "universal catch-all" pattern — write dedicated interceptors
for complex scenes, use the universal one for everything else. New scenes get
framework context for free without writing any interceptor code.

---

## 32. Scenes Need Ambient Life — The "Dead World" Problem

**Discovery:** Between player actions, scenes feel static. Nothing happens unless
the player does something. Real environments have ambient activity — sounds, NPC
movements, environmental changes. Without these, the AI agents describe a dead world.

**Fix:** Created **AmbientEventInterceptor** (priority 17) that injects random
micro-events with configurable probability (default 25%). Events are scene-specific:
- Casino: slot machines, card shuffling, champagne orders
- Warzone: distant artillery, radio crackle, stray dogs
- Bedroom: shifting moonlight, distant music, candle scent

The interceptor tracks recent events per scene to avoid repetition within a sliding
window. Agents naturally weave these ambient details into their responses, creating
a living world without any scene code changes.

---

## 33. The Universal Pattern Scales Better

**Insight:** The per-scene interceptor pattern doesn't scale. Each new scene needs a
dedicated interceptor class, registration in `_build_default_pipeline()`, import line,
`__all__` entry, and tests. The UniversalSceneInterceptor proved that one catch-all
handles 6 scenes with better consistency than 6 individual implementations would.

**Recommendation for new scenes:** Only create a dedicated interceptor if the scene
has unique context needs (cocktail menus, artwork metadata, etc.). Otherwise, rely
on the universal interceptor + Coordinator + SSM narrative.

---

## Implementation Log (Sprint 6)

| Date | Revelation | Action | Status |
|------|-----------|--------|--------|
| Sprint 6 | #31 Six scenes missing interceptors | Created UniversalSceneInterceptor (priority 16) | Done |
| Sprint 6 | #32 Dead world problem | Created AmbientEventInterceptor (priority 17) | Done |
| Sprint 6 | #33 Universal pattern scales | Design insight documented | Done |
| Sprint 6 | N/A | Pipeline count 20 → 22 | Done |
| Sprint 6 | N/A | 15 new tests (1223 total) | Done |

### Updated Framework Adoption (Post-Sprint 6)

| Feature | Adoption | Change |
|---------|----------|--------|
| MCPSceneMixin | 10/10 (100%) | unchanged |
| SceneStateManager | 10/10 (100%) | unchanged |
| Interceptor Pipeline | 10/10 (100%) | now 22 interceptors |
| Scene-Specific Context | 10/10 (100%) | was 4/10 — UniversalSceneInterceptor covers rest |
| CharacterStateCoordinator | 10/10 (100%) | was 6/10 — Universal injects for all |
| AgentGovernor | 2/10 (20%) | unchanged |
| ConversationHeat | 10/10 (100%) | was 4/10 — Universal injects for all |
| DialogSystem | 2/10 (20%) | already wired via DialogDirectiveInterceptor |
| Registry Persistence | 10/10 (100%) | unchanged |
| Scene Transition Tracking | 10/10 (100%) | unchanged |
| Ambient Events | 10/10 (100%) | NEW: all scenes get micro-events |

---

## Sprint 7 Implementation Log

### Revelation #7 Addressed: Interaction Tree Phases → Prompt Injection

**Problem:** Interaction tree phases (setup → deepening → climax) existed in data
but never reached the agent's prompt during timed interactions. The agent had no
idea where in the arc it was.

**Fix:** BedroomSceneInterceptor now checks `ssm.active_timed_actions()` and injects
phase-aware guidance: early stage (< 30%) → "build anticipation", middle (30-70%) →
"deepen the moment", late (> 70%) → "bring to peak, then resolve". The phase label
from the interaction tree is included when available.

### Revelation #34: Scene Descriptors Give Agents Spatial Awareness

The UniversalSceneInterceptor now carries a `_SCENE_DESCRIPTORS` dict with thematic
one-liners for each scene. Before this, agents in Casino/Warzone/Realm/NeonCity/
Coders Room/Heist received mood and stats but no sense of *where they are*. Now
every response starts with spatial grounding: "The Grand Casino — opulent,
high-stakes gambling floor" etc. Simple data, outsized effect on immersion.

### Revelation #35: Revelation #11 Is Outdated

Cross-scene messaging was marked as a gap in revelation #11, but it was already
fully wired by Sprint 2: Lounge sends messages via AgentRouter, and
RouterMessageInjector (priority 10) drains inbox automatically. No work needed.

| Sprint | Revelation | Action | Status |
|--------|-----------|--------|--------|
| Sprint 7 | #7 Narrow pipe | Phase injection in BedroomSceneInterceptor | Done |
| Sprint 7 | #34 Scene descriptors | 6 thematic descriptors in UniversalSceneInterceptor | Done |
| Sprint 7 | #35 Rev #11 outdated | Confirmed cross-scene messaging already wired | Done |
| Sprint 7 | N/A | 11 new tests (1234 total) | Done |
