# CosySim Scenes Guide

Complete reference for every scene in the CosySim simulation framework.

---

## Scene Architecture

Every game scene in CosySim follows the same architecture:

- **BaseScene** (`engine/scenes/base_scene.py`) — Abstract base class providing asset management, character loading, save/load, and lifecycle hooks. Each scene binds to a `host:port` and maintains an `active_characters` dict.
- **MCPSceneMixin** (`engine/mcp/framework.py`) — Mixin that wires a scene into the MCP governance framework. Declared via `class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene")`. Automatically registers the scene node, patches character enter/leave, and enables skills, rules, and state management.
- **SCENE_METADATA** — Dict on each scene class declaring `title`, `description`, `genre`, `max_characters`, and `features`. Used by the Command Center and Hub for discovery.
- **Flask + SocketIO** — Each scene runs a Flask web server with SocketIO for real-time client updates. Templates live in `content/scenes/<name>/templates/`.
- **Auto-registration** — Skills (`@skill` decorator), rules (registered via `SceneRulesEngine`), and characters (loaded from the asset database) are wired up in `__init__`.

### Port Map

| Port | Scene | Genre |
|------|-------|-------|
| 5555 | Phone | Social simulation |
| 5556 | Bedroom | Adult roleplay |
| 5557 | Lounge | Social / speakeasy |
| 5559 | Casino | Gambling simulation |
| 5560 | Gallery | Creative / art |
| 5561 | Warzone | Military RTS |
| 5562 | Realm | Fantasy RPG |
| 5563 | Neon City | Cyberpunk strategy |
| 5564 | Coders Room | Coding simulation |
| 5565 | Heist | Crime co-op |
| 5566 | Command Center | System monitoring |
| 8500 | Hub | Scene launcher (Streamlit) |
| 8501 | Dashboard | Character management (Streamlit) |
| 8502 | Admin Panel | System admin (Streamlit) |

---

## Creating a New Scene

### 1. Directory Structure

```
content/scenes/my_scene/
├── __init__.py
├── my_scene_scene.py      # Scene class
├── my_scene_skills.py     # MCP skill functions
├── my_scene_rules.py      # Rule definitions
└── templates/
    └── index.html          # Frontend UI
```

### 2. Scene Class

```python
from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin

class MyScene(BaseScene, MCPSceneMixin, mcp_scene_id="my_scene"):
    SCENE_METADATA = {
        "title": "My Scene",
        "description": "What the scene does.",
        "genre": "genre_tag",
        "max_characters": 4,
        "features": ["feature_a", "feature_b"],
    }

    def __init__(self, host="0.0.0.0", port=5570):
        super().__init__(scene_name="my_scene", host=host, port=port)
        self._mcp_init()
        self.app = Flask(__name__, template_folder="templates")
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        # Register routes, load characters, register rules...
```

### 3. Skills File

Define callable tools that LLM agents can invoke:

```python
from engine.mcp.framework import get_framework

def register_my_scene_skills(scene):
    fw = get_framework()
    node = fw.get_scene("my_scene")

    @node.skill("my_scene_status", "Get current scene state")
    def status():
        return scene.get_state_dict()
```

### 4. Rules File

Register MCP rules with conditions, effects, and actions:

```python
def register_my_scene_rules(scene_node):
    scene_node.add_rule(Rule(
        name="example_gate",
        conditions={"stat_name": {"min": 50}},
        effects={"unlock": "feature_x"},
    ))
```

### 5. Registration

In `__init__.py`, export the scene class. The Hub and launcher discover scenes automatically.

---

## Scene Reference

---

### Phone (port 5555)

**CosyPhone OS** — An iOS-style phone interface with messaging, calls, and character social media. Characters send autonomous texts and maintain relationships.

**Genre:** Social simulation · **Max characters:** 5

#### Apps
- **Messages** — Thread-based DMs and group chats with characters
- **Hacker** — Character state inspection, profile reading, message interception
- **Games** — Arcade mini-games (trivia, would-you-rather, story chain) and Truth or Dare
- **Gallery** — Photo and video browser
- **Voice Messages** — Audio clip playback
- **Voice Studio** — Premade voice collection / TTS
- **Research (NotebookLM)** — Knowledge-base Q&A

#### MCP Skills (6)
| Skill | Description |
|-------|-------------|
| `phone_send_message` | Text a character |
| `phone_check_messages` | Get threads and unread counts |
| `phone_start_game` | Start arcade game (trivia, truth_or_dare, etc.) |
| `phone_game_action` | Submit a game move |
| `phone_generate_image` | Generate AI images |
| `phone_toggle_autotxt` | Mute/unmute autonomous texting |

#### Game Mechanics
- **Conversation threading** — PhoneDB-backed threads with stateful `ConversationManager`; last 20 messages loaded per reply; previous response IDs reduce token usage by ~80%.
- **Autonomous texting** — Background ticker schedules character-initiated messages based on relationship warmth: Cold (10–30 min), Warm (3–10 min), Hot (1–4 min), Obsessed (20–90 sec). Mode-specific prompts (casual → flirty → intimate → explicit).
- **Heat gates** — Stat thresholds (trust ≥ 35, affection ≥ 50, etc.) unlock progressively intimate conversation modes.
- **Group chats** — Multiple members in a single thread; AI replies from each character independently.

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/threads` | List all message threads |
| POST | `/api/thread/<id>/send` | Send message (spawns async reply) |
| GET | `/api/contacts` | List characters with mood and unread count |
| POST | `/api/games/start` | Start truth-or-dare session |
| GET | `/api/hacker/targets` | List characters with full state |
| POST | `/api/hacker/<id>/intercept` | Inject system-level directives |

#### State Management
- **PhoneDB** for persistent messages, threads, and media
- **ConversationManager** for server-side KV conversation cache
- **MCP Governor pipeline** wraps every character reply through interceptors
- **SocketIO events:** `message_new`, `thread_updated`, `typing`, `mood_update`

---

### Bedroom (port 5556)

**The Bedroom** — Adult roleplay scene with detailed 3D avatars, a clothing system, bed-game mechanics, and heat-gated explicit content progression.

**Genre:** Adult roleplay · **Max characters:** 3

#### MCP Skills (10)
| Skill | Description |
|-------|-------------|
| `bedroom_character_status` | Get character positions, stats, moods |
| `bedroom_adjust_stat` | Modify a character stat by delta |
| `bedroom_give_line` | Script dialogue for a character |
| `bedroom_whisper` | Send hidden directive to a character |
| `bedroom_add_prop` | Place furniture/props in room |
| `bedroom_set_time` | Change lighting (morning → midnight) |
| `bedroom_start_game` | Start intimate gameplay scenario |
| `bedroom_game_action` | Submit game action |
| `bedroom_set_scenario` | Configure scenario and mood |
| `bedroom_fire_event` | Trigger custom narrative event |

#### Game Mechanics
- **Bed Game** — Turn-based intimate game tracked by `BedGameState`. Players, turns, rounds, escalation level (1–5). Escalation tiers reward increasingly explicit actions with points and bonuses.
- **Intimacy gates** — 8 tiers gated by stat thresholds: Light Touch (always), Kiss (warmth ≥ 30), Caress (arousal ≥ 40), Striptease (arousal ≥ 55), Intimate (arousal ≥ 70 + consent), Explicit (arousal ≥ 80), Depraved (arousal ≥ 90), Aftercare (arousal ≤ 20).
- **Consent system** — Grant consent (arousal ≥ 45, trust ≥ 35) or withdraw consent (blocks all intimate actions).
- **Director mode** — Whisper hidden instructions, force lines/actions, broadcast, enter as participant.
- **Scenarios** — 8 premade: romantic_evening, truth_or_dare, spa_night, slave_master, voyeur, threesome, edging_challenge, roleplay_fantasy.

#### Scene Rules
- 14 escalating actions (cuddle → deep kiss → striptease → bondage → orgasm → aftercare)
- Director-only overrides: Lights Off, Mood Lift, Escalate, Reset, Max Arousal, Strip Everyone
- Timed actions with durations (striptease 45s, massage 120s, intimate 180s)

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/scene/state` | Full scene state |
| POST | `/api/character/load` | Load character into scene |
| POST | `/api/director/whisper` | Hidden instruction to character |
| POST | `/api/bedgame/start` | Start bed game |
| POST | `/api/bedgame/action` | Perform game action |
| POST | `/api/scenario/set` | Activate premade scenario |
| POST | `/api/event/fire` | Fire custom narrative event |

#### State Management
- **AgentStats** — 10 stats per character: arousal, horniness, drunkenness, tiredness, happiness, anger, fear, pleasure, explicitness, openness (all 0–100).
- **CharacterProfile** — Personality keys (bold_dominant, shy_submissive, playful_tease, etc.), outfit, position, held props, base stats.
- **BedGameState** — Active game, players, turns, rounds, escalation level, scores, streak tracking.
- **Props** — 27 items with stat effects (vibrator, bondage gear, etc.); **Positions** — 20 options; **Outfits** — 15 options.

---

### Lounge (port 5557)

**The Velvet Lounge** — A 1920s underground jazz speakeasy. Two resident characters powered entirely by the MCP framework with consequence chains, timers, and trust gates.

**Genre:** Social · **Max characters:** 5

#### MCP Skills (6)
| Skill | Description |
|-------|-------------|
| `lounge_status` | Get atmosphere, current song, character moods |
| `lounge_order_drink` | Order cocktail with mood/stat effects (10s cooldown) |
| `lounge_request_song` | Request song for playlist |
| `lounge_share_secret` | Build intimacy/trust with character (30s cooldown) |
| `lounge_dream_whisper` | Enter character's dreamspace (60s cooldown) |
| `lounge_mirror_soul` | Reflect character's emotions empathically (45s cooldown) |

#### Game Mechanics
- **Heat meter** — 0–100, ticks every 180 seconds via MCPTimer. At ≥ 65 mood shifts to alert; at ≥ 85 enforcement consequences trigger.
- **Trust economy** — 0–100 trust score gates secrets, back room access (≥ 60), and premium pours.
- **Music system** — Active song plays via MCPTimer; song completion triggers mood_contagion.
- **Cocktail system** — Drinks affect mood, stats, and scene atmosphere via consequence chains.
- **Random events** — MCPFramework.random_pick each turn for atmospheric surprises.
- **Cross-agent comms** — Lola ↔ Viktor communicate via MCPFramework.cross_scene_send.

#### Characters
| Character | Role | Personality |
|-----------|------|-------------|
| **Lola Voss** (29) | Singer / speakeasy owner | Warm, assertive, sensual, witty. Warm smoky contralto, faint Eastern European accent. |
| **Viktor Marlowe** (38) | Bartender / silent guardian | Assertive, dominant, low warmth. Deep baritone, short sentences. |

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | Atmosphere, song, heat, character moods |
| POST | `/api/order` | Order cocktail |
| POST | `/api/message` | Send message to character |
| POST | `/api/back_room` | Attempt back room access (trust-gated) |
| POST | `/api/ask_secret` | Request character secret |

#### State Management
- Framework-first: most state lives in MCPFramework / SceneStateManager.
- Thin in-memory layer: `turn_count`, `heat_level`, `guest_trust`, `secrets_revealed`, `current_song`, `in_back_room`.
- CharacterRegistry tracks mood, mood_intensity, energy for Lola and Viktor.

---

### Casino (port 5559)

**The Casino Floor** — A noir underground poker den with blackjack, poker, roulette, and slots. AI dealers and characters with personality-driven gambling styles.

**Genre:** Gambling simulation · **Max characters:** 5

#### MCP Skills (6)
| Skill | Description |
|-------|-------------|
| `casino_table_status` | Get round, phase, pot, player chips, community cards |
| `casino_bet` | Place bet with chip management |
| `casino_fold` | Fold hand and forfeit pot |
| `casino_all_in` | Push all remaining chips into pot |
| `casino_order_drink` | Order cocktail with stat effects |
| `casino_read_opponent` | Analyze opponent bluff tells (15s cooldown) |

#### Game Mechanics
- **Texas Hold'em poker** — Community cards, betting rounds, hand evaluation, showdown.
- **Chip economy** — Players start with 500 chips; bets tracked in pot.
- **Bluffing system** — Characters have poker "tells" (nervous habits) that can be read.
- **Phases** — lobby → deal → bet → showdown → result.
- **Drink system** — Cocktails modify confidence, focus, luck stats.
- **Consequence chains** — Delayed effects (drunk penalties, luck streaks).

#### Characters
| Character | Role | Personality |
|-----------|------|-------------|
| **Dealer Jack** (45) | House dealer | Low warmth, high dominance, deep measured voice. 20 years reading people. |
| **Hustler Mira** (31) | Fellow player | Warm, witty, playful. Expert card counter from Macau. |

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | Current game state |
| POST | `/api/new-hand` | Deal new poker hand |
| POST | `/api/bet` | Place bet |
| POST | `/api/bluff` | Attempt bluff |
| POST | `/api/showdown` | Reveal cards, determine winner |
| POST | `/api/fold` | Fold current hand |

#### State Management
- In-memory game state: pot, player_chips, phase, round_number.
- MCPSceneStateManager tracks confidence, focus, luck, charm, recklessness (0–100).
- MCPGameSession records turn history for hand replay.
- save_state/load_state for persistence across restarts.

---

### Gallery (port 5560)

**Art Gallery** — An AI art gallery where characters evaluate, create, and debate generated artwork. Showcases image generation integration.

**Genre:** Creative · **Max characters:** 5

#### MCP Skills (5)
| Skill | Description |
|-------|-------------|
| `gallery_exhibition_status` | Get current theme, artwork count, room |
| `gallery_create_art` | Submit new artwork (20s cooldown) |
| `gallery_critique` | Rate artwork 1–10 with verdict (10s cooldown) |
| `gallery_change_room` | Navigate gallery rooms |
| `gallery_art_debate` | Initiate art debate with opponent (30s cooldown) |

#### Game Mechanics
- **Exhibition system** — Themed exhibitions enforce style consistency (Dreams Unveiled, Neon Futures, Raw Emotions).
- **Art creation** — Characters generate artworks via AI image generation with `[IMAGE:prompt]` tags.
- **Evaluation system** — Structured 3-point scoring: Technique (0–10), Emotion (0–10), Originality (0–10). Average ≥ 9.0 triggers "Masterpiece Declaration" event.
- **Debate mechanics** — Characters debate artwork merits with rebuttals.
- **Room navigation** — 5 rooms: Main Hall (10 cap, bright), Modern Wing (6, dramatic), Sculpture Garden (8, dappled), Dark Room (4, UV/projection), Private Collection (3, invitation-only, trust ≥ 60).

#### Characters
Characters are dynamically assigned roles from the database on startup:
- **Curator** — Exhibition design and art history
- **Critic** — Evaluating composition, technique, emotional impact
- **Artist** — Creating new works inspired by the exhibition
- **Visitor** — Experiencing art with fresh eyes

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | Exhibition theme, artwork count, room |
| POST | `/api/artwork/create` | Generate artwork via AI |
| POST | `/api/evaluate` | Structured artwork evaluation |
| POST | `/api/debate` | Challenge character to art debate |
| POST | `/api/exhibition/set` | Switch exhibition theme |

#### State Management
- Database-backed character profiles.
- In-memory: `artworks` dict (title, style, description, evaluations), `characters` dict (role, mood, evaluations count, current_room), `active_exhibition`.
- Streaming-enabled conversations (v2.7 default).

---

### Warzone (port 5561)

**Warzone** — Real-time strategy scene with AI commanders managing squads, buildings, and combat. Features event-driven warfare mechanics rendered in Three.js.

**Genre:** Strategy · **Max characters:** 4

#### MCP Skills (5)
| Skill | Description |
|-------|-------------|
| `warzone_status` | Get turn, weather, resources, unit positions |
| `warzone_deploy` | Deploy unit: infantry, armor, artillery, air_support |
| `warzone_attack` | Attack enemy: base, flanks, supply_line |
| `warzone_recon` | Spend intel to gather enemy intelligence |
| `warzone_special_op` | Execute sabotage, airstrike, or counter-intelligence |

#### Game Mechanics
- **Resource tycoon loop** — Collect credits/power/intel from buildings → upgrade weapons/defenses → attack.
- **Escalation** — Income multiplier increases 5% per turn for late-game acceleration.
- **Weather system** — Clear, Cloudy, Storm, Fog, Favorable; affects attack accuracy (storm −15%, fog −20%).
- **Combat** — Accuracy rolls, crit chance (15% = 1.5× damage), interception, shield bypass, counterstrike (25% chance when base HP < 30%).
- **7 weapon tiers** — Artillery (30 dmg) → Cruise Missile → ICBM → Bunker Buster → Laser Cannon → Drone Swarm (3 hits) → Orbital Strike (250 dmg).
- **5 special abilities** — Spy Satellite, EMP Burst, Sabotage, Shield Overcharge, Commander Taunt.
- **Buildings** — Factory (+75 credits/turn), Power Plant (+2 power/turn), Intel Center (+1 intel/turn).

#### Scene Rules
- Weapon/defense unlock gates (Cruise Missile at 300 credits, Orbital Strike at 2500 credits + 8 power + 3 intel)
- AI Commander rules: aggressive when weapon advantage, defensive when base HP < 50%, taunt on successful hits
- Counterstrike at < 30% HP (desperation mode)

#### Characters
| Character | Role | Behavior |
|-----------|------|----------|
| **General Ironside** | AI Commander | Adaptive strategy — aggressive/defensive based on game state. Taunts after hits. |

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/game` | Current game state |
| POST | `/api/game/action` | Execute action (attack, build, upgrade, deploy) |
| SocketIO | — | Real-time game state broadcasts, combat results |

#### State Management
- Player and AI state: credits, power, intel, base HP, weapon/defense levels, buildings.
- Weather, turn/phase, status effects (Spy, EMP, Shield Overcharge), escalation multiplier.
- Three.js 3D battlefield with SocketIO sync.

---

### Realm (port 5562)

**The Realm** — A director-guided LitRPG visual novel with quests, exploration, and character skills. Features a dual-agent system with a fourth-wall-breaking companion.

**Genre:** Fantasy RPG · **Max characters:** 4

#### MCP Skills (18)
| Skill | Description |
|-------|-------------|
| `realm_inventory` | List items |
| `realm_add_item` | Add item to inventory |
| `realm_remove_item` | Remove item |
| `realm_stats` | Show HP/MP/Level/XP/Attributes |
| `realm_skill_check` | d20 + stat mod vs DC |
| `realm_adjust_hp` | Heal or damage |
| `realm_start_combat` | Initiate encounter |
| `realm_combat_attack` | Roll d20 + STR to attack |
| `realm_combat_defend` | Halve incoming damage |
| `realm_combat_flee` | Attempt escape |
| `realm_combat_use_item` | Use consumable in combat |
| `realm_director_status` | Check patience, mutiny status |
| `realm_fourth_wall_steal` | Break fourth wall |
| `realm_desperation_dice` | Sacrifice max HP to reset Director context |
| `realm_murder_status` | Murder mystery: phase, clues, accusations remaining |
| `realm_murder_accuse` | Accuse suspect + weapon + room |
| `realm_location` | Current location and connections |
| `realm_move` | Travel (may trigger random encounters) |

#### Game Mechanics
- **Dual-agent system** — Director (game master) narrates and presents choices; Assistant (fourth-wall companion) provides commentary and can break the fourth wall.
- **Gameplay loop** — Director presents narration + 2–4 choices → player selects → Director processes via LLM → state updates (HP, XP, inventory) → repeat.
- **Skill checks** — d20 + stat_mod (stat ÷ 2 − 5) vs DC. Nat 20 = critical success; Nat 1 = critical failure.
- **Combat** — Initiative (d20 + AGI), weapon damage + STR mod, crit on nat 20 (2× damage), death at HP ≤ 0 → lose random item, respawn at 50% HP.
- **Exploration** — Room discovery: 30% encounter, 40% loot, 30% empty. Locked doors require skill checks.
- **Murder mystery** — Sub-game with investigation phases, clue gathering (3+ unlock accusation), suspect interrogation. Wrong accusation = −25 HP.
- **Director patience** — Decreases each turn; at 0 → mutiny (forced narrative, no player choice).

#### Scene Rules
- Level up on XP overflow: +10 max HP, +5 max MP, +2 to random stat, XP multiplier ×1.5
- Fourth-wall mechanics: Assistant can steal UI elements, force context resets
- Available skills: persuasion, lockpicking, arcana, athletics, stealth, intimidation, deception, investigation, survival

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/game` | Fetch current game state |
| POST | `/api/game/new` | Initialize new game |
| POST | `/api/game/action` | Execute player action |
| POST | `/api/choice` | Submit player choice |
| POST | `/api/director/infer` | Get Director narration + choices |
| POST | `/api/assistant/infer` | Get Assistant commentary |

#### State Management
- `RealmGameState` — Player stats (HP, MP, XP, Level, STR/AGI/INT/CHA/LCK), inventory, location graph, active quests, combat state, murder mystery state.
- Stateful Director/Assistant conversation IDs maintain continuity.
- Director patience meter controls difficulty and mutiny events.

---

### Neon City (port 5563)

**Neon City** — A cyberpunk battle-royale board game on a shrinking grid with hacking, factions, and street events.

**Genre:** Cyberpunk · **Max characters:** 5

#### MCP Skills (8)
| Skill | Description |
|-------|-------------|
| `neoncity_status` | Get turn, storm radius, alive players, firewall status |
| `neoncity_player_info` | Get HP, position, weapons, implants |
| `neoncity_move` | Move on grid (may discover loot) |
| `neoncity_attack` | Attack player with weapon |
| `neoncity_hack` | Breach AI firewall at target location |
| `neoncity_storm_status` | Get storm boundary and danger zones |
| `neoncity_trigger_event` | Trigger random event (blackout, drone strike) |
| `neoncity_end_turn` | Process AI turns and advance round |

#### Game Mechanics
- **12×12 grid** with procedural loot locations (caches, upgrades, weapons, implants).
- **Glitch Storm** — Shrinking safe zone each round; players outside take 15 damage/turn, inside regenerate 5 HP.
- **Combat** — Turn-based with weapons, accuracy modifiers, critical hits (10% chance, 2× damage).
- **Hacking** — Progressive firewall breaching to defeat an AI target at grid center.
- **AI opponents** — Up to 3 AI players with behavior profiles (aggressive, opportunist, flee at 25% HP).
- **Dynamic events** — 30% chance per turn (blackouts, drone strikes, supply drops).

#### Scene Rules
- Zone rules: storm damage, safe zone shrinking, regeneration inside zone
- Combat: weapon accuracy, crits, kill detection
- Hacking: progressive firewall layers, breach mechanics

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/game/new` | Start new game |
| POST | `/api/game/move` | Move player on grid |
| POST | `/api/game/attack` | Combat attack |
| POST | `/api/game/hack` | Breach AI firewall |
| POST | `/api/game/end_turn` | End turn, process AI |

#### State Management
- `NeonCityGameState` — Players, grid, storm radius, firewall layers, turn/round counters.
- MCP framework integration for narrative context and governance.
- SocketIO for real-time state sync.

---

### Coders Room (port 5564)

**Coders Room** — An AI coding room where agents collaboratively write, review, and test Python code in an idle-simulation loop.

**Genre:** Coding simulation · **Max characters:** 3

#### MCP Skills (6)
| Skill | Description |
|-------|-------------|
| `coders_status` | Get simulation state (ticks, features, agents) |
| `coders_agent_info` | Get agent stats (lines written, reviews, tests) |
| `coders_add_feature` | Queue a feature request |
| `coders_feature_list` | List pipeline and completed features |
| `coders_run_code` | Execute Python in sandboxed subprocess (10s timeout) |
| `coders_tick` | Advance pipeline by one tick |

#### Game Mechanics
- **5-phase pipeline** — FEATURE → DESIGN → CODING → REVIEW → TESTING.
- **Role-based agents** — Reviewer (writes specs), Writer (generates code), QA (runs tests).
- **Real code generation** — LLM generates actual Python code in markdown blocks.
- **Sandboxed execution** — 10-second timeout subprocess with pytest for test validation.
- **Auto-queuing** — New features auto-generated when queue is empty.
- **Failure handling** — Consecutive test failures trigger rollback to DESIGN phase.

#### Scene Rules
- Pipeline phase gates (each phase must pass before advancing)
- Code quality gates enforced during REVIEW
- Test coverage requirements during TESTING

#### Characters
Three AI agents with mood, status, and task tracking:
- **Reviewer** — Specification and design
- **Writer** — Code generation
- **QA** — Testing and validation

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/start` | Start simulation |
| POST | `/api/stop` | Stop simulation |
| GET | `/api/state` | Get current state |
| POST | `/api/feature/add` | Queue feature request |
| POST | `/api/tick` | Manual pipeline advance |

#### State Management
- `CodersRoomState` — Agents, feature queue, pipeline metrics (lines written, tests run, completed count).
- Tick-based loop (configurable interval, default 15s).
- Agent stats sync to StateCoordinator for cross-system visibility.

---

### Heist (port 5565)

**The Heist** — Cooperative heist planning and execution with specialized crew roles. The player directs a crew through phase-gated operations.

**Genre:** Crime co-op · **Max characters:** 4

#### MCP Skills (6)
| Skill | Description |
|-------|-------------|
| `heist_status` | Phase, suspicion, crew status, obstacles, loot |
| `heist_action` | Perform crew action (disable_alarm, hack_door, persuade, etc.) |
| `heist_advance_phase` | Progress to next phase |
| `heist_collect_loot` | Grab loot (default $50k) |
| `heist_crew_check` | Get crew member skills and status |
| `heist_obstacles` | List remaining barriers to clear |

#### Game Mechanics
- **Phase system** — PLANNING → APPROACH → EXECUTION → ESCAPE → COMPLETE. Each phase gates available actions and AI prompts.
- **Suspicion meter** — 0–100; affects action success rates. Low (< 30%) = calm; Medium (30–60%) = guards suspicious; High (> 60%) = danger, one mistake = bust.
- **Specialty-based skill checks** — Each crew member excels at certain actions (e.g., Ghost: 85% hack_door, 30% fight).
- **Autonomous tick** — Crew makes independent decisions in background via VirtualPipeline.
- **Action tags** — `[ACTION:action_name]` in crew AI response auto-executes the action.
- **Leaderboard** — SharedBoard tracks highest-value heists.

#### Scene Rules
- Phase-gated directives (planning: discuss strategy; approach: stealth/disguises; execution: speed/obstacles; escape: getaway/roadblocks)
- Suspicion escalation affects available options
- Specialty emphasis: crew nudged toward their strengths

#### Characters (Crew)
| Character | Role | Specialty |
|-----------|------|-----------|
| **Ghost** | Hacker | disable_alarm, hack_door, loop_cameras, jam_comms |
| **Tank** | Muscle | breach_door, fight, carry_loot |
| **Silk** | Talker | persuade, bribe, distract |
| **Wheels** | Driver | drive, scout, getaway |

Each has health, morale, and status (ok/injured/arrested).

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/game` | Fetch heist state |
| POST | `/api/game/new` | Start new heist (select venue + crew) |
| POST | `/api/game/action` | Crew performs action |
| POST | `/api/game/advance` | Move to next phase |
| POST | `/api/game/loot` | Collect loot |
| POST | `/api/chat` | Send message to crew member |
| GET | `/api/venues` | List heist targets |

#### State Management
- Phase, suspicion (0–100), crew status (health, morale, arrested/injured flags).
- Obstacles remaining (alarm, guards, safe, cameras).
- Loot haul vs target; venues with distinct layouts, guard counts, and loot values.

---

### Command Center (port 5566)

**Command Center** — System observatory dashboard showing real-time metrics, pipeline status, cross-scene activity, live scene monitoring, and remote scene control.

**Genre:** System monitoring · **Max characters:** 0 (observatory only)

#### MCP Skills (6)
| Skill | Description |
|-------|-------------|
| `cc_scene_list` | List all active scenes with status and character count |
| `cc_scene_status` | Detailed scene state, characters, heat |
| `cc_scene_feed` | Recent chat messages from a scene |
| `cc_character_status` | Character mood, energy, stats, relationships |
| `cc_inject_event` | Inject narrative/directive/broadcast into a scene |
| `cc_system_status` | Monitor CPU, RAM, GPU, LMStudio status |

#### Features
- **Real-time monitoring** — CPU/RAM/GPU usage with alert thresholds (GPU VRAM > 80% yellow, > 95% red).
- **Cross-scene view** — Monitor all active scenes simultaneously (state, characters, live chat).
- **Live scene control** — Inject narratives, directives, or broadcast system messages into any scene.
- **Character viewer** — Inspect any character's mood, energy, stats, and relationships across scenes.
- **Training capture** — Export high-quality scene data as JSONL for model fine-tuning.
- **Alert system** — Queue depth, latency thresholds, node status (green/yellow/red).
- **Activity bus** — Current and historical event tracking.

#### Key API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dashboard` | Full system state |
| GET | `/api/scenes` | List active scenes with summaries |
| GET | `/api/scenes/<id>` | Detailed scene state |
| GET | `/api/scenes/<id>/feed` | Recent chat messages |
| GET | `/api/characters/<id>` | Character details across scenes |
| POST | `/api/training/export` | Export training data as JSONL |
| GET | `/api/system` | System metrics snapshot |
| GET | `/api/alerts` | Alert history |

#### State Management
- Lazy-loads MetricsCollector, MetricsDB, ActivityBus, SystemMonitor singletons.
- Scene summaries extracted from each running scene (phase, heat, state, SCENE_METADATA).
- Background ticker thread (1s default) updates dashboard.
- Director-only access for injection and stat editing.

---

### Hub (port 8500)

**Scene Hub** — Central launcher and navigation for the entire CosySim system. Runs as a Streamlit application.

#### Features
- **Scene launcher** with live status indicators (🟢 Running / ⚫ Stopped) for 14 services across 3 categories:
  - **Core Scenes (6):** Phone, Bedroom, Lounge, Casino, Gallery, Warzone
  - **v3.2 Showcase (3):** Realm, Neon City, Coders Room
  - **Tools & Services (5):** Dashboard, Admin, Asset Generator, TTS Server, MCP Bridge
- **System health monitoring** — HTTP health checks against all scene ports.
- **Asset browser** — View total assets, characters, images.
- **Tutorials** — Getting started guides, game guides, MCP framework docs.
- **Settings** — System config, paths, version info.

---

### Admin Panel (port 8502)

**Admin Panel** — Unified 14-page system management interface. Runs as a Streamlit application.

#### Pages
| # | Page | Purpose |
|---|------|---------|
| 1 | 📊 Dashboard | System stats and asset overview |
| 2 | 🗂️ Asset Browser | Browse all asset types |
| 3 | 👥 Character Manager | Create, edit, delete characters |
| 4 | 🎭 Personality Manager | Manage personality presets and custom profiles |
| 5 | 🎬 Scene Manager | Configure and manage scenes |
| 6 | 💾 Media Manager | Manage images, videos, audio |
| 7 | 🔗 Conversation Explorer | Browse saved conversations |
| 8 | ⚙️ Config Editor | Edit system configuration files |
| 9 | 📊 LMStudio Integration | Model management and configuration |
| 10 | 🎨 Asset Generator | ComfyUI and TTS integration |
| 11 | 🧠 RAG Editor | Memory and embeddings management |
| 12 | ⛓️ Chains Manager | Workflow chain management |
| 13 | 📜 Logs Viewer | System and scene log browser |
| 14 | 💾 Backups | Database backup and restore |

---

### Dashboard (port 8501)

**Dashboard** — Character-centric monitoring and state management. Runs as a Streamlit application.

#### Pages
- **📊 Dashboard** — Stats overview (character count, personalities, roles, memories), recent activity
- **👤 Characters** — Create, view, edit characters (name, age, sex, physical traits, tags, metadata)
- **🎭 Personalities** — View/create personality templates with system prompts, traits, values
- **🎬 Roles** — Manage character roles with context and scenarios
- **💾 Memories** — Browse, add, edit, search character memories (RAG-backed)
- **🚀 Deploy** — Launch scenes with selected character
- **⚙️ Settings** — Database paths, reset options

#### State Tracked
Mood, energy, relationship level, arousal, memory count per character.

---

### Games (sub-modules)

Standalone mini-game modules used by the Phone and Bedroom scenes.

#### Truth or Dare
- **Flow:** Start → Roll (1–6, odd = truth, even = dare) → Answer → End
- **Content:** 15 truth questions + 15 dare prompts
- **Scoring:** 1 pt per truth, 2 pts per dare completed
- **API:** `/games/truth-or-dare/start`, `/roll`, `/answer`, `/state`, `/end`
- **Integration:** Standalone `TruthOrDareGame` class + MCP session logging

#### Mystery Investigation
- **Flow:** Start (pick case) → Gather clues (5 total, red herrings every 3rd) → Accuse culprit → Win/Loss
- **Cases:** 3 pre-built (Heirloom, Poisoning, Masterpiece) with clues, red herrings, culprits
- **Accusation:** Fuzzy matching — suspect name substring matches culprit
- **API:** `/games/mystery/start`, `/clue`, `/accuse`, `/state`, `/end`
- **Integration:** Standalone `MysteryGame` class + MCP session logging
