# CosySim Scene AAA Upgrade Plan
> Generated: 2026-02-24 | Deep audit of all 12 scenes + character system overhaul

---

## Executive Summary

This document rates every CosySim scene on framework adoption, game quality, and completeness,
then provides a prioritized upgrade plan to bring all scenes to AAA standard. Scenes are scored
on a 0-100 scale across 8 dimensions and ranked for upgrade priority.

---

## Scene Audit Scores

### Scoring Dimensions (0-10 each, max 80)

| Dim | Name | Description |
|-----|------|-------------|
| FW | Framework Adoption | MCPSceneMixin, SSM, TagRegistry, SCENE_METADATA, event bus |
| GL | Game Logic | Rules, mechanics, state machines, win/loss conditions |
| AI | Agent Quality | Character depth, personality, interceptor pipeline usage |
| UI | Frontend Quality | HTML/JS/CSS, responsiveness, visual polish |
| WR | Wiring | Routes connected, sockets working, state syncing to MCP |
| IN | Interactivity | Player agency, choices, consequences, replayability |
| FN | Fun Factor | Is it actually engaging? Would someone play this? |
| CM | Completeness | Dead code ratio, missing features, placeholder content |

### Scene Rankings

| # | Scene | FW | GL | AI | UI | WR | IN | FN | CM | TOTAL | GRADE |
|---|-------|----|----|----|----|----|----|----|----|-------|-------|
| 1 | **Bedroom** | 10 | 9 | 9 | 8 | 9 | 10 | 9 | 9 | **73** | **A** |
| 2 | **Casino** | 9 | 8 | 8 | 7 | 9 | 8 | 8 | 8 | **65** | **B+** |
| 3 | **Lounge** | 9 | 7 | 8 | 7 | 9 | 7 | 7 | 8 | **62** | **B** |
| 4 | **Heist** | 8 | 8 | 7 | 6 | 7 | 8 | 8 | 7 | **59** | **B** |
| 5 | **Phone** | 8 | 7 | 8 | 7 | 8 | 7 | 7 | 7 | **59** | **B** |
| 6 | **Gallery** | 8 | 6 | 7 | 6 | 7 | 6 | 6 | 7 | **53** | **C+** |
| 7 | **Warzone** | 7 | 8 | 5 | 7 | 7 | 7 | 7 | 6 | **54** | **C+** |
| 8 | **Coders** | 7 | 6 | 5 | 5 | 6 | 5 | 5 | 6 | **45** | **C** |
| 9 | **NeonCity** | 7 | 6 | 4 | 5 | 6 | 5 | 5 | 5 | **43** | **C** |
| 10 | **Realm** | 7 | 5 | 6 | 5 | 5 | 5 | 4 | 4 | **41** | **C-** |
| 11 | **CmdCenter** | 7 | 2 | 0 | 4 | 5 | 2 | 2 | 4 | **26** | **D** |
| 12 | **Hub** | 5 | 1 | 0 | 6 | 3 | 2 | 2 | 4 | **23** | **D** |

---

## Detailed Scene Audits

### 1. BEDROOM — Grade A (73/80) — Reference Standard

**Strengths:**
- Full MCP framework: SSM, TagRegistry, SCENE_METADATA, rules engine, interceptors
- 36 bed game actions with escalation competition system (5 tiers)
- 15 premade scenarios with graphic beats
- 6 personality profiles, full stat vector (10 dimensions)
- 3D avatars with 22 sex poses, clothing system, LERP animations
- Director tools: whisper, give line, give action, story beats, mount, interact
- SceneMap with 7 mountable locations, each with explicit interactions
- Dedicated rules file (bedroom_rules.py) with 11 gate rules, 14 actions, 7 director rules
- Consequence chains, timed actions, consent system

**Gaps:**
- [ ] Bed game UI tab in frontend (actions/state display)
- [ ] InteractionTree multi-phase sequences not fully wired
- [ ] Auto-narrative generation from stat changes
- [ ] Sound effects / ambient audio integration

**Status:** Reference implementation. Other scenes should aspire to this level.

---

### 2. CASINO — Grade B+ (65/80)

**Strengths:**
- Full MCP framework adoption (SSM, event bus, timers, consequences)
- Dedicated casino_mcp.py with rules, drinks, random events, tells
- Dual AI agents (Dealer Jack, Hustler Mira) with rich registry profiles
- Poker game engine with phases (lobby, deal, bet, showdown, result)
- Player stats (confidence, focus, luck, charm, recklessness)
- Drink system with delayed consequences via framework
- Hand history tracking, bluff mechanics

**Gaps:**
- [ ] Only poker implemented — needs blackjack, roulette, slots
- [ ] No chip persistence across sessions
- [ ] Mira AI lacks real strategic poker behavior
- [ ] No tournament/progressive mode
- [ ] Tell system could be richer (body language descriptions)
- [ ] Frontend needs more visual polish (card animations, chip stacks)
- [ ] No social mechanics between characters at the table

**Upgrade Plan:**
1. Add blackjack (simple rules, fast games)
2. Add slot machine (visual, reward mechanic)
3. Chip persistence via SceneStateManager
4. Mira poker AI: use personality-driven bet sizing
5. Tournament mode with rounds + leaderboard
6. Table talk: let agents comment on each other's plays

---

### 3. LOUNGE — Grade B (62/80)

**Strengths:**
- Full MCP-first design (lounge_mcp.py has rules, drinks, songs, secrets)
- Dual AI agents (Lola Voss, Viktor Marlowe) with registry profiles
- Heat meter + trust economy system
- Stage performance with song system
- Back room access gated on trust
- Cross-agent comms (Lola to Viktor)
- Random events per turn
- MCP ResponseDirective on every reply

**Gaps:**
- [ ] Limited interactivity — mostly "chat + order drinks"
- [ ] Heat system consequences feel thin (should affect more)
- [ ] No mini-games (drinking games, karaoke, performance scoring)
- [ ] Song system is passive — player cant request or perform
- [ ] No group conversation dynamics (other patrons)
- [ ] Back room content is sparse
- [ ] No time-of-night progression (sets change, crowd changes)

**Upgrade Plan:**
1. Add karaoke/performance mini-game with scoring
2. Add NPC patrons who rotate and have conversations
3. Deepen heat system: police raid events, hiding mechanics
4. Player performance: let player sing/perform
5. Drinking game mechanic (shot roulette, ring of fire)
6. Night progression: early crowd, late crowd, after-hours

---

### 4. HEIST — Grade B (59/80)

**Strengths:**
- Multi-agent crew system (Ghost, Tank, Silk, Wheels) with specialties
- Phase-gated gameplay (planning, approach, execution, escape)
- Dedicated heist_game.py + heist_rules.py + heist_skills.py
- Skill check system with complications
- SharedBoard integration (leaderboard)
- VirtualPipeline integration for streaming

**Gaps:**
- [ ] Limited venue variety (needs more heist targets)
- [ ] Crew conversations feel scripted, not dynamic
- [ ] Planning phase lacks depth (no blueprint mechanic)
- [ ] No equipment loadout system
- [ ] Execution phase needs more branching outcomes
- [ ] No heat/wanted system carrying across heists
- [ ] Frontend needs heist map visualization

**Upgrade Plan:**
1. Add 3+ more venue types with unique challenges
2. Equipment loadout system (tools, disguises, vehicles)
3. Blueprint mechanic in planning phase
4. Branching execution outcomes based on crew skills + RNG
5. Heat/wanted level that persists
6. Crew relationship dynamics (loyalty, trust, betrayal risk)

---

### 5. PHONE — Grade B (59/80)

**Strengths:**
- iOS-style messaging UI with threads and contacts
- PhoneDB for persistence (SQLite-backed messages)
- MCP governor pipeline on every AI reply
- Background auto-texting via MCPTimer
- Voice/photo/video message cards
- Truth-or-dare game via MCPGameSession
- Governance_context now properly prepends (Sprint 9 fix)

**Gaps:**
- [ ] No "hack" app (user request) — inspect character internals
- [ ] Apps (gallery, voice_studio) are partially implemented
- [ ] No group chat dynamics (characters messaging each other)
- [ ] No notification system
- [ ] Messages app doesnt use character relationship data
- [ ] No "social media" feed app
- [ ] Auto-texting prompts could be more personality-driven

**Upgrade Plan:**
1. NEW: Hack App — select any character, see conversation history, stats, mood, relationship scores, internal thoughts
2. Wire messages between characters (not just player to character)
3. Social media feed app (characters post updates, react)
4. Notification badges on unread messages
5. Character relationship data drives message tone
6. Voice messages actually use TTS system

---

### 6. GALLERY — Grade C+ (53/80)

**Strengths:**
- Full v2.7 streaming showcase (StreamProcessor, mood/action extraction)
- Image generation via [IMAGE:prompt] tags
- Conversation branching (art debate alternatives)
- Structured output (art evaluations as typed JSON)
- Multiple rooms with different atmospheres
- Curator + critic dual agents

**Gaps:**
- [ ] Art generation is placeholder — no actual image pipeline
- [ ] Limited interactivity beyond chatting about art
- [ ] No collection/acquisition mechanic
- [ ] No exhibition creation feature
- [ ] Frontend template likely basic
- [ ] No art style discovery/progression
- [ ] No social events (exhibition openings, auctions)

**Upgrade Plan:**
1. Wire image generation to actual asset generation pipeline
2. Art collection mechanic: buy, curate, display
3. Exhibition creation: arrange pieces, theme rooms
4. Art auction mini-game
5. Add visitor NPCs who react to exhibitions
6. Style progression: discover new styles through exploration

---

### 7. WARZONE — Grade C+ (54/80)

**Strengths:**
- Complete tactical game engine (weapons, defenses, buildings, specials)
- Weather system affecting accuracy
- Resource economy (credits, power, intel)
- Three.js battlefield rendering
- SharedBoard highscores
- AI opponent with strategy
- Building system (factory, powerplant, intel center)

**Gaps:**
- [ ] AI commentary is basic (should use infer_processed)
- [ ] No AI personality — just "AI opponent"
- [ ] Single game mode only
- [ ] No campaign/mission progression
- [ ] Building system could have more variety
- [ ] No diplomacy/alliance mechanics
- [ ] Agent integration is minimal (no rich character behind AI)

**Upgrade Plan:**
1. Give AI opponent a character (General Koda — arrogant, strategic)
2. Use infer_processed for AI taunts, commentary, reactions
3. Add campaign mode: 5 missions with escalating difficulty
4. More building types (radar, hospital, barracks)
5. AI personality affects strategy (aggressive, defensive, tricky)
6. Taunt system: player and AI verbal sparring affects morale

---

### 8. CODERS — Grade C (45/80)

**Strengths:**
- Multi-agent coding pipeline (write, review, test)
- CodersRoomState with PipelinePhase tracking
- TagRegistry with CODE tag
- Sandboxed code execution
- Feature seeds for variety

**Gaps:**
- [ ] Actual code execution sandbox not verified
- [ ] Agent conversations are thin — need more personality
- [ ] No visual code editor or terminal display
- [ ] Pipeline phases may not all be wired
- [ ] No project progression (building something over time)
- [ ] No code quality scoring system
- [ ] Frontend is likely minimal (249 lines of scene code)

**Upgrade Plan:**
1. Add coder personalities (perfectionist, hacker, cowboy coder)
2. Visual terminal display showing code being written
3. Code quality scoring with reviews and refactoring
4. Project board: features, in progress, done
5. Bug injection: random bugs that need debugging
6. Pair programming mode: player guides one coder

---

### 9. NEONCITY — Grade C (43/80)

**Strengths:**
- Procedural board game with Glitch Storm shrink mechanic
- Prefab loot locations (PREFAB_TYPES)
- AI opponents via VirtualAgentManager
- EVENT_POOL for random events
- TagRegistry with HACK tag
- MCP framework integration

**Gaps:**
- [ ] Very short scene file (249 lines) — likely minimal
- [ ] No rich narrative/flavor beyond board game
- [ ] AI opponents are generic, not characterized
- [ ] No faction system despite genre suggesting it
- [ ] No hacking mini-game despite HACK tag
- [ ] Board game mechanics may be shallow
- [ ] No cyberpunk flavor in agent prompts

**Upgrade Plan:**
1. Add hacking mini-game (code puzzles, network infiltration)
2. Faction system: 3 gangs with territories and relations
3. Characterize AI opponents with cyberpunk personalities
4. Street events: encounters, deals, ambushes
5. Cyberpunk flavor narration via LMS
6. Night market: buy upgrades, implants, weapons
7. Territory control mechanic

---

### 10. REALM — Grade C- (41/80) — MAJOR UPGRADE NEEDED

**Strengths:**
- Good architecture: dual-agent (Director + Assistant) with player choices
- RealmGameState with player stats, inventory, skill tree
- Director personality system (5 types with patience decay)
- Murder mystery sub-module with phases
- Memory echoes (cross-run hints)
- Desperation dice + mutiny mechanics
- MCP framework integration (timers, consequences)

**Gaps:**
- [ ] Almost NO game loop content — Director generates everything on-the-fly
- [ ] No predefined quests, locations, or encounters
- [ ] No world map or zone system
- [ ] Combat system is entirely Director-improvised
- [ ] No loot tables or reward structures
- [ ] Skill tree exists but skills rarely used in gameplay
- [ ] Frontend likely very basic (544 lines total)
- [ ] No progression save/load
- [ ] Murder mystery is the only structured content
- [ ] "LitRPG" promises but delivers improv story

**Upgrade Plan:**
1. Create zone/world map: 5+ areas with unique themes
2. Predefined encounter tables per zone (combat, social, puzzle)
3. Structured combat system: initiative, attack/defend, spells
4. Loot tables with item tiers (common to legendary)
5. Quest journal: active quests with objectives and rewards
6. NPC roster: 10+ characters with personalities, dialog trees
7. Save/load game progress
8. Structured dungeon generation (rooms + hazards + bosses)
9. Level-up system with stat point allocation + new abilities
10. Shop/merchant system for buying/selling gear

---

### 11. COMMAND CENTER — Grade D (26/80) — MAJOR UPGRADE NEEDED

**Strengths:**
- System metrics dashboard (CPU, RAM, GPU)
- Pipeline metrics (latency, TPS)
- Alert system with history
- Activity bus integration
- Training data capture stats
- Background ticker for live updates

**Gaps:**
- [ ] NO live scene monitoring (user priority request)
- [ ] NO cross-scene chat viewer
- [ ] NO scene state representation
- [ ] NO character turn viewer
- [ ] No agent management controls
- [ ] No model configuration controls
- [ ] No scene launch/stop controls
- [ ] No character stat editing
- [ ] Purely observational — no control capability
- [ ] Frontend is basic metrics dashboard only

**Upgrade Plan (HIGH PRIORITY — user will use this a lot):**
1. Scene Monitor Panel: cycle through all scenes, see live state
   - Chat feed from each scene (last 20 messages)
   - Character positions, stats, moods as visual cards
   - Game state summary per scene (phase, score, turn)
2. Character Inspector: click any character, see all stats, mood, personality, conversation history, relationship scores
3. Live Stat Editor: edit any characters stats in real-time
4. Scene Controls: start/stop scenes, reset states, inject events
5. Model Dashboard: see loaded models, VRAM usage, configure agent profiles
6. Cross-scene event log: unified timeline of all scene events
7. Director Console: send directives to any character in any scene

---

### 12. HUB — Grade D (23/80) — MAJOR UPGRADE NEEDED

**Strengths:**
- Streamlit-based scene launcher
- Port status checking
- Categorized scene listing
- Asset browser

**Gaps:**
- [ ] Streamlit is slow and limited for a dashboard
- [ ] No live status updates (manual refresh only)
- [ ] Scene launching is via subprocess (brittle)
- [ ] No scene preview or description
- [ ] No integrated chat/activity view
- [ ] No settings panel
- [ ] No character overview across all scenes
- [ ] No quick-action buttons (directives, stat edits)

**Upgrade Plan:**
1. Add scene thumbnails and descriptions
2. Live WebSocket status updates (not polling)
3. Quick-launch buttons with config presets
4. Character dashboard: all characters, their current scene, mood
5. Global settings panel (LMStudio config, model selection)
6. Recent activity feed from all scenes

---

## Character System Overhaul

### Current State
Characters have:
- Name, personality (backstory, traits, speech patterns, quirks, interests)
- Scene-specific stats (bedroom has 10-dim AgentStats, casino has chips/confidence)
- Mood tracking (mood + mood_intensity)
- CharacterRegistry with state persistence

### Proposed Upgrades

#### 1. Universal Emotional Model
Replace per-scene stats with a universal emotional model that persists across scenes.
Core emotions (0-100) change SLOWLY (2-5 per interaction):
happiness, confidence, trust, attraction, anger, fear, excitement.
Derived mood is computed from emotions automatically.

#### 2. Attraction System
Characters attracted to other characters based on:
- Appearance: attractiveness stat (inherent + outfit)
- Personality match: compatible traits boost attraction
- Status: high-status characters are more attractive
- History: positive interactions create attraction buffs
- Chemistry: random spark modifier (some pairs just click)

#### 3. Relationship Buffs/Debuffs
Past interactions leave lasting effects that decay over time:
- name (e.g., "great_date", "argument", "saved_my_life")
- stat_mods: specific stat bonuses
- strength: 1.0 to 0.0 (decays over time)
- decay_rate: per-hour decay rate

#### 4. Tags System
Characters can have tags that affect behavior:
- flirty: more likely to initiate romantic interactions
- jealous: reacts negatively when crush talks to others
- loyal: relationship buffs decay slower
- wild: higher chance of unpredictable actions
- shy: lower initiation, higher response to being pursued

#### 5. Live Stat Editing
Admin panel and Command Center can edit any stat in real-time via REST API and WebSocket.

---

## Implementation Priority (Pass Order)

### Pass 1: Foundation (Character System + Command Center)
Build the systems everything else depends on.
- [ ] Universal EmotionalState model in character system
- [ ] Attraction system between characters
- [ ] Relationship buff/debuff with decay
- [ ] Character tags system
- [ ] Live stat editing API
- [ ] Command Center: scene monitor panel with live chat feeds
- [ ] Command Center: character inspector
- [ ] Command Center: live stat editor

### Pass 2: Critical Scenes (Realm + Phone + Hub)
Bring the worst scenes up to minimum viable.
- [ ] Realm: Zone system, encounter tables, structured combat, quest journal
- [ ] Phone: Hack app, inter-character messaging, notification system
- [ ] Hub: Scene thumbnails, live status, character dashboard

### Pass 3: Enhancement (Casino + Lounge + Warzone)
Add missing game modes and deepen interactivity.
- [ ] Casino: blackjack + slots + chip persistence + tournament
- [ ] Lounge: karaoke/performance + night progression + drinking games
- [ ] Warzone: AI personality + campaign mode + taunt system

### Pass 4: Polish (Heist + Gallery + Coders + NeonCity)
Fill gaps and add personality.
- [ ] Heist: equipment loadout + more venues + crew dynamics
- [ ] Gallery: wire image generation + collection mechanic + auctions
- [ ] Coders: visual terminal + project board + coder personalities
- [ ] NeonCity: hacking game + factions + territory control

### Pass 5: Integration and QA
Everything wired, tested, polished.
- [ ] All scenes using universal character system
- [ ] All scenes firing events to Command Center feed
- [ ] All characters have attraction/relationship data
- [ ] Cross-scene character awareness (phone messages reference other scenes)
- [ ] Full test coverage for new systems
- [ ] Frontend polish pass on all scenes
- [ ] Documentation update

---

## Key Comparisons: Best vs Worst

### What makes Bedroom grade A:
1. Deep state model: 10-dimension stats + compliance scoring + personality profiles
2. Rich game mechanics: 36 bed game actions, escalation system, turn-based competition
3. MCP rules: 11 gate rules create a progression system (kiss gate to explicit gate to depraved)
4. Director tools: 7+ ways to influence the scene (whisper, give line, mount, interact, etc.)
5. Frontend quality: 3D avatars with clothing, poses, expressions, animations
6. Interceptor depth: BedroomSceneInterceptor injects wardrobe, stats, heat, MCP rules, timed phases
7. Scenario variety: 15 premade scenarios with story beats

### What Realm needs to match:
1. No predefined content — needs zones, encounters, NPCs, quests
2. No structured game loop — needs turn/phase system with clear objectives
3. Director generates everything — needs templates + Director fills in details
4. No progression — needs XP, levels, gear upgrades, quest completion
5. No replayability — needs procedural variety within structured framework
6. Has dual-agent architecture — good foundation, needs content

### What Command Center needs to match:
1. Observation only — needs control capabilities
2. Metrics only — needs scene awareness (live chats, character states)
3. No scene switching — needs scene browser with live previews
4. No character management — needs inspector + editor
5. Has real-time ticker — good foundation, needs data sources

---

## Success Criteria

A scene is AAA when:
1. Uses ALL MCP framework features (SSM, TagRegistry, rules engine, event bus, interceptors)
2. Has a clear, fun game loop with objectives and progression
3. AI agents have rich personalities that drive unique interactions
4. Player has meaningful choices with visible consequences
5. Frontend is polished and responsive
6. State persists and syncs correctly
7. Rules engine gates content appropriately
8. Interceptor pipeline is active and scene-specific
9. At least 2 mini-games or interaction modes
10. Character system uses universal emotions + attraction + relationships
