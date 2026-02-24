# Scene AAA Upgrade Plan
## Deep Audit & Upgrade Path for All CosySim Scenes

Generated: 2026-02-24  
Status: Planning Phase

---

## Executive Summary

Every scene has been audited across 10 dimensions: LOC, game mechanics, MCP framework
adoption, legacy systems, fun factor, rules separation, skills, interceptors, completeness,
and critical gaps. The goal: bring ALL scenes to AAA quality — same framework, same systems,
fully wired, genuinely fun, mechanically deep.

---

## Scene Rankings (Current State)

| Rank | Scene | Score | LOC | Framework % | Key Strength | Critical Gap |
|------|-------|-------|-----|-------------|-------------|-------------|
| 1 | **Bedroom** | 9/10 | 2200+ | 98% | Full adult system, poses, escalation, 23 interceptors | UI for bed game controls |
| 2 | **Casino** | 8/10 | 988 | 95% | Complete poker loop, bluffing, consequences | Hand eval too simple, no all-in |
| 3 | **Heist** | 8/10 | 1111 | 85% | 4-phase state machine, crew AI, complications | Manual threading, no leaderboard |
| 4 | **Coders** | 7.5/10 | 757 | 100% | Clean MCP-native, sandbox execution | No failure recovery, agents identical |
| 5 | **Lounge** | 7/10 | 1993 | 90% | Rich heat/trust mechanics, dual characters | Skills never triggered, hybrid timers |
| 6 | **Phone** | 7/10 | 1300 | 80% | Strong messaging, relationship AI | Missing apps (email, calls), PhoneDB legacy |
| 7 | **Gallery** | 7/10 | 865 | 75% | Streaming showcase, ComfyUI art gen | No persistence, shallow debate, rules inline |
| 8 | **Warzone** | 7/10 | 659 | 75% | Rich combat balance, weather/events | No squads/missions, AI too simple |
| 9 | **NeonCity** | 6/10 | 992 | 65% | Good concept, loot/combat/hacking | State bypasses MCP, AI trivial, no rules file |
| 10 | **Realm** | 6/10 | 1335 | 80% | Dual-agent orchestration, murder mystery | Gameplay thin, combat narrative-only, no equipment |
| 11 | **CommandCenter** | 6/10 | 404 | 50% | Solid monitoring infra | ZERO control, no skills, no rules |

---

## Character System Upgrade (Applies to ALL Scenes)

**Current: 6/10** — Well-architected state management, shallow character arcs.

### Phase C1: Persistent Character Overhaul
- [ ] **Slow-moving personality traits**: warmth, formality, humor, flirtiness, intelligence, creativity move ±0.01 per interaction (not per scene). Takes 50+ interactions to shift meaningfully.
- [ ] **Attraction model**: Characters rate other characters on attractiveness (physical + personality compatibility). Uses sex, body_type, personality overlap, status, past_interactions.
- [ ] **Relationship buffs/debuffs**: Past positive interactions create warmth buffs (decay over 24h). Negative interactions create tension debuffs (decay over 48h). Must maintain relationship or it cools.
- [ ] **Character tags**: Up to 5 personality tags per character (e.g., "flirty", "jealous", "loyal", "impulsive"). Tags influence interceptor injections and dialogue style.
- [ ] **Live stat editing**: Admin API endpoint `POST /api/character/<id>/edit_stats` for real-time stat manipulation with broadcast.
- [ ] **Cross-scene persistence**: Ensure `CharacterStateCoordinator.update(persist=True)` is called on every scene exit and periodically during long sessions.

### Phase C2: Relationship System
- [ ] **Attraction calculation**: `attraction = (physical_compat * 0.3) + (personality_overlap * 0.3) + (status_ratio * 0.1) + (interaction_history * 0.3)`
- [ ] **Interaction memory**: Last 20 interactions stored with sentiment score. Characters remember how you made them feel.
- [ ] **Buff/debuff system**: `RelationshipEffect` dataclass with `{effect_type, magnitude, decay_rate, source}`. Applied in `CharacterRegistryInterceptor`.
- [ ] **Wire relationships into interceptors**: `CharacterRegistryInterceptor` reads attraction and relationship buffs/debuffs and includes them in system prompt context.

---

## Command Center — Complete Overhaul (Priority: HIGH)

**Current: 6/10 → Target: 9/10**

This is your primary control hub. It MUST have:

### CC1: Live Scene Monitor System
- [ ] **Multi-scene viewer**: A "computer monitor" component that cycles through all active scenes
- [ ] **Per-scene feed**: Shows last 5 chat messages, current characters, heat level, game state
- [ ] **Visual state representation**: ASCII/emoji state diagrams showing game phase, character positions, escalation level
- [ ] **Socket aggregation**: Subscribe to all scene Socket.IO feeds and relay events to Command Center UI
- [ ] **Scene status cards**: Each scene shows: running/stopped, character count, heat level, current game phase, last activity timestamp

### CC2: Scene Control Panel
- [ ] **Pause/resume scenes** remotely
- [ ] **Reset scene** to defaults
- [ ] **Inject narrative events** to any scene from command center
- [ ] **Cross-scene character transfer**: Move characters between scenes
- [ ] **Broadcast directive**: Issue dialog directives to any character in any scene
- [ ] **Force scenario**: Load a premade scenario in any scene remotely

### CC3: Character Turn Viewer
- [ ] **Turn-by-turn replay**: See each character's latest turn, what they said, what tags they emitted
- [ ] **Live mood indicators**: Real-time mood/energy/arousal bars per character
- [ ] **Conversation thread viewer**: See the full conversation history for any character pair

### CC4: System Metrics
- [ ] Keep existing monitoring (CPU, RAM, GPU, LMS metrics)
- [ ] Add **per-scene metrics**: response latency, messages/minute, heat trends
- [ ] Add **interceptor hit counters**: Which interceptors fire most often

---

## Phone — New "Hack" App + Missing Apps (Priority: HIGH)

**Current: 7/10 → Target: 9/10**

### P1: Hacker App
- [ ] **App icon**: "Hack" with terminal aesthetic
- [ ] **Character selector**: Pick any character from any scene
- [ ] **View conversation history**: See their full chat history (not just with you)
- [ ] **View internal state**: See their current stats, mood, personality, relationships
- [ ] **View phone messages**: See messages they've sent to OTHER characters
- [ ] **Intercept messages**: Option to read messages in real-time before delivery
- [ ] **Inject whisper**: Send a hidden message that only the hacked character hears

### P2: Missing Core Apps
- [ ] **Call History app**: Log of voice interactions (even if voice isn't real-time yet)
- [ ] **Notes app**: Simple text storage per-character
- [ ] **Settings app**: Toggle NSFW, change themes, notification preferences
- [ ] **Social Feed app**: Aggregated updates from all characters (mood changes, scene transitions, events)

### P3: Framework Fixes
- [ ] Replace PhoneDB with SceneStateManager + MCP state
- [ ] Replace manual threading with MCPTimer for autonomous texting
- [ ] Wire _PhoneCharacterAgent through full VirtualAgentManager pipeline

---

## Realm — Complete Game Mechanics Overhaul (Priority: CRITICAL)

**Current: 6/10 → Target: 8.5/10**

The Realm promises "LitRPG / Visual Novel" but delivers a thin narrative wrapper. Needs real game systems.

### R1: Combat System
- [ ] **Turn-based combat loop**: Initiative rolls → attack/defend/skill → damage calculation → loot
- [ ] **Equipment system**: Weapons affect damage, armor affects defense. Equip/unequip from inventory.
- [ ] **Skill-based attacks**: Each of the 9 skills can be used offensively (athletics=power attack, stealth=backstab, arcana=spell)
- [ ] **Enemy types**: 5+ enemy templates with stats, weaknesses, loot tables
- [ ] **HP consequences**: Death = lose items, respawn at camp. Not just narrative.

### R2: Exploration & Quests
- [ ] **Room/location system**: 8+ interconnected rooms with descriptions, loot, NPCs, exits
- [ ] **Quest tracker**: Active quests with objectives, progress, rewards
- [ ] **NPC interaction**: Dialogue options that check CHA/persuasion/intimidation
- [ ] **Locked areas**: Require keys, lockpicking, or strength checks to access

### R3: Resource Economy
- [ ] **Gold/currency**: Earned from combat, quests, loot. Spent at shops.
- [ ] **Consumables**: Health potions, mana potions, buff items
- [ ] **Crafting (light)**: Combine 2 items → better item

### R4: Rules & MCP
- [ ] Extract all game rules to `realm_rules.py` with SceneRulesEngine registration
- [ ] Add interceptor for stat-gated content (e.g., INT < 5 = simpler vocabulary from Director)
- [ ] Wire SharedBoard for leaderboard (highest level, fastest mystery solve)

---

## NeonCity — Framework Alignment + AI Depth (Priority: HIGH)

**Current: 6/10 → Target: 8/10**

### NC1: MCP Alignment
- [ ] Replace `self.state` with proper MCP GameState wrapper
- [ ] Move all balance constants to `neoncity_rules.py` with SceneRulesEngine registration
- [ ] Wire events through MCP consequence system instead of inline execution
- [ ] Add interceptor hook for narrative injection based on game phase

### NC2: AI Improvement
- [ ] **Heuristic AI**: Score-based target selection (threat, distance, resource value)
- [ ] **AI personalities**: Aggressive, defensive, opportunistic variants
- [ ] **AI communication**: AI trash-talks via LLM during combat

### NC3: Hacking Depth
- [ ] **Multi-step hacking puzzle**: Not just a single roll — sequence of decisions (bypass/brute force/social engineer)
- [ ] **Hacking minigame**: Pattern matching or logic puzzle
- [ ] **Consequences**: Failed hack = alert system, harder security

### NC4: Persistence
- [ ] Save/load game state
- [ ] SharedBoard leaderboard (survival time, kills, hacks completed)

---

## Casino — Polish to AAA (Priority: MEDIUM)

**Current: 8/10 → Target: 9.5/10**

### CA1: Poker Upgrade
- [ ] **Full hand evaluation**: Straights, flushes, full houses, straight flushes
- [ ] **All-in mechanic**: Implement the registered but missing action
- [ ] **Bankruptcy/buy-in**: When chips hit 0, offer buy-in or end session

### CA2: Multi-opponent
- [ ] Allow 2-3 AI opponents with different personalities (tight, loose, aggressive, passive)
- [ ] Side conversations between AI opponents during hands

### CA3: Game Variety
- [ ] **Blackjack**: Simple 21 game as alternative
- [ ] **Roulette**: Betting board with spin animation (or text-based)

---

## Heist — Wire Remaining Systems (Priority: MEDIUM)

**Current: 8/10 → Target: 9/10**

### H1: Agent Migration
- [ ] Replace manual threading with VirtualAgentManager pipeline
- [ ] Replace raw InferenceRequest with managed agent calls

### H2: Features
- [ ] SharedBoard leaderboard (fastest heist, biggest haul, no-alarm runs)
- [ ] Crew inter-conflict system: personality clashes during planning phase
- [ ] Mid-heist save/load for long sessions

### H3: Complication Pool
- [ ] Expand from 15 to 30+ complications
- [ ] Add crew-specific complications (Ghost loses nerve, Tank goes rogue)

---

## Lounge — Activate Dormant Systems (Priority: MEDIUM)

**Current: 7/10 → Target: 8.5/10**

### L1: Fix Skill Activation
- [ ] Wire `mood_influence` to fire on Lola's performances
- [ ] Wire `memory_recall` to fire on Viktor's reminiscences
- [ ] Add skill trigger points in message loop

### L2: Timer Cleanup
- [ ] Replace hybrid timer (MCPTimer + time.time()) with pure MCPTimer
- [ ] Ensure song rotation fully managed by framework

### L3: Consequence Enforcement
- [ ] Heat lockdown actually blocks actions (refuse drink orders, pause songs)
- [ ] Add real failure consequences (getting kicked out, Lola refusing to perform)
- [ ] Add win condition (Lola reveals final secret at 100 trust)

---

## Coders — Depth & Personality (Priority: LOW)

**Current: 7.5/10 → Target: 8.5/10**

### CO1: Agent Differentiation
- [ ] Linus (writer) generates different code style than Ada (reviewer)
- [ ] Custom prompts per agent role reflecting expertise

### CO2: Failure Recovery
- [ ] Failed features get retry option (max 2 retries)
- [ ] Debug mode: agent tries to fix test failures

### CO3: Rules Externalization
- [ ] Move phase timing and difficulty to `coders_rules.py`
- [ ] Register with SceneRulesEngine

---

## Gallery — Persistence & Depth (Priority: LOW)

**Current: 7/10 → Target: 8/10**

### G1: State Persistence
- [ ] Save artwork history to database
- [ ] Preserve character critiques across sessions

### G2: Debate Upgrade
- [ ] Replace "longest text" picker with semantic scoring
- [ ] Add rebuttal rounds

### G3: Rules Migration
- [ ] Move exhibition themes, styles to `gallery_rules.py`
- [ ] Register with SceneRulesEngine

---

## Warzone — Depth & Squads (Priority: MEDIUM)

**Current: 7/10 → Target: 8.5/10**

### W1: Squad System
- [ ] 3-unit squads with different roles (assault, support, recon)
- [ ] Squad morale affecting combat effectiveness
- [ ] Squad abilities (flanking, suppression, medic)

### W2: Mission System
- [ ] 5 premade missions with objectives (hold point, destroy target, rescue, escort, sabotage)
- [ ] Mission rewards (credits, upgrades, unlocks)

### W3: AI Strategy
- [ ] Replace deterministic AI with heuristic decision tree
- [ ] AI builds strategically (factories early, weapons mid, defense late)
- [ ] AI adapts to player strategy

### W4: Rules Migration
- [ ] Extract balance constants to `warzone_rules.py`
- [ ] Register weapons, buildings, upgrades with SceneRulesEngine

---

## Implementation Passes

### Pass 1: Character System + Command Center (CRITICAL)
**Why first:** Character system improvements benefit ALL scenes. Command Center
is the user's home base — must be functional first.

- Character system overhaul (C1 + C2)
- Command Center live monitor (CC1)
- Command Center controls (CC2)
- Command Center turn viewer (CC3)

### Pass 2: Phone + Realm (HIGH PRIORITY)
**Why second:** These are the most broken scenes relative to their promise.

- Phone: Hacker app (P1)
- Phone: Missing apps (P2)
- Phone: Framework fixes (P3)
- Realm: Combat system (R1)
- Realm: Exploration (R2)
- Realm: Economy (R3)
- Realm: Rules migration (R4)

### Pass 3: NeonCity + Warzone (HIGH)
**Why third:** Solid bones but need alignment and depth.

- NeonCity: MCP alignment (NC1)
- NeonCity: AI improvement (NC2)
- NeonCity: Hacking depth (NC3)
- Warzone: Squad system (W1)
- Warzone: Mission system (W2)
- Warzone: AI strategy (W3)

### Pass 4: Casino + Heist + Lounge (MEDIUM)
**Why fourth:** Already good — need polish, not overhaul.

- Casino: Poker upgrade (CA1) + Multi-opponent (CA2)
- Heist: Agent migration (H1) + Leaderboard (H2)
- Lounge: Skill activation (L1) + Timer cleanup (L2)

### Pass 5: Coders + Gallery + Final Polish (LOW)
**Why last:** Already MCP-native, need depth not architecture.

- Coders: Agent differentiation (CO1) + Failure recovery (CO2)
- Gallery: Persistence (G1) + Debate upgrade (G2)
- All scenes: Final rules migration audit
- All scenes: SharedBoard leaderboard integration where missing
- All scenes: Interceptor coverage audit

---

## Quality Checklist (Must pass for AAA rating)

Every scene must satisfy ALL of these:

- [ ] Uses MCPSceneMixin ✓ (already 10/10)
- [ ] Uses SceneStateManager for all state
- [ ] Has separate rules file registered with SceneRulesEngine
- [ ] Has skill pack with 3+ skills
- [ ] Has TagRegistry custom tags
- [ ] Has SCENE_METADATA ✓ (already 10/10)
- [ ] Uses MCPTimer instead of manual threading
- [ ] Uses VirtualAgentManager (not raw LMS calls)
- [ ] Has SharedBoard integration (leaderboard or bulletin)
- [ ] Has consequence chains (not just instant effects)
- [ ] Has interceptor integration (scene-specific + universal)
- [ ] Has 2+ meaningful game loops/state machines
- [ ] Has win/loss/progression conditions
- [ ] Has character personality integration
- [ ] Uses Governor pipeline for all LLM calls
- [ ] State persists across restarts
- [ ] Has live admin control via overlay API
- [ ] Frontend responsive to state changes via Socket.IO

---

## Current Compliance Matrix

| Scene | Rules File | Skills 3+ | MCPTimer | VAM | SharedBoard | Consequences | 2+ Loops | Win/Loss | Persist |
|-------|-----------|----------|---------|-----|------------|-------------|---------|---------|---------|
| Bedroom | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Casino | ✅ | ⚠️2 | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ |
| Heist | ✅ | ✅ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Coders | ❌ | ✅ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Lounge | ✅ | ⚠️dead | ✅ | ✅ | ❌ | ✅ | ✅ | ⚠️ | ⚠️ |
| Phone | ✅ | ⚠️ | ❌ | ⚠️ | ✅ | ⚠️ | ✅ | N/A | ✅ |
| Gallery | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ | ❌ |
| Warzone | ❌ | ⚠️1 | ❌ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ❌ |
| NeonCity | ❌ | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ✅ | ✅ | ❌ |
| Realm | ❌ | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ⚠️ | ⚠️ | ❌ |
| CmdCenter | ❌ | ❌ | ❌ | N/A | ❌ | ❌ | ❌ | N/A | ❌ |

**Legend:** ✅ = Done | ⚠️ = Partial/Broken | ❌ = Missing

**Total ✅ across all scenes:** ~33%  
**Target:** 100%

---

## Estimated Scope

| Pass | Scenes | Effort | New Code |
|------|--------|--------|----------|
| Pass 1 | Character + CmdCenter | Large | ~800 lines |
| Pass 2 | Phone + Realm | Large | ~1200 lines |
| Pass 3 | NeonCity + Warzone | Medium | ~600 lines |
| Pass 4 | Casino + Heist + Lounge | Medium | ~400 lines |
| Pass 5 | Coders + Gallery + Polish | Small | ~300 lines |
| **Total** | **All 11** | | **~3300 lines** |

---

## Notes

- Bedroom is the gold standard — all other scenes should aspire to its level of
  framework integration, game depth, and prompt engineering.
- The character system upgrade in Pass 1 automatically improves every scene because
  interceptors inject character state into all LLM calls.
- Command Center as a monitoring hub makes QA testing much easier — you can watch
  all scenes simultaneously and catch issues.
- The Phone Hacker app creates a unique gameplay mechanic that ties scenes together.
