# COSYSIM HACKING SYSTEM ANALYSIS — PHASE 4 FOUNDATION

## 1. EXISTING HACKING-RELATED FILES & SYSTEMS

### Core Hacking System
- **engine/services/hack_engine.py** — Main hacking engine with puzzle generation, target management, solution evaluation
- **engine/skills/builtin/hacking_skills.py** — 6 @skill-decorated functions for hacking operations
- **content/scenes/grid/grid_scene.py** — THE GRID scene (travel, market, faction intel)
- **content/scenes/grid/grid_skills.py** — Grid scene skills (buy, sell, pledge faction, quests)
- **tests/test_hacking.py** — Comprehensive tests for hacking system
- **content/shared/static/js/cosysim-hack-minigame.js** — Frontend JavaScript for puzzle UI
- **content/shared/static/css/cosysim-hack-minigame.css** — Styling for puzzle interface

### Game Content Files
- **engine/world/inventory.py** — Item management (cyberdecks with crack_speed, trace_resist stats)
- **engine/world/player_state.py** — Player state management
- **engine/world/mission.py** — Mission/quest system
- **content/scenes/grid/grid_scene.py** — Grid marketplace with factions and cyberdecks

## 2. EXISTING SKILL SYSTEM PATTERNS

### @skill Decorator Pattern (engine/skills/skill.py)
All skills follow this pattern:

`python
from engine.skills.skill import skill, SkillCategory

@skill(
    pack="hacking",                              # Skill pack name (groups related skills)
    description="Human-readable description",   # Shown to LLM
    category=SkillCategory.GAME,               # One of: COMMUNICATION, MEMORY, MEDIA, GAME, SOCIAL, ENVIRONMENT, SYSTEM, NARRATIVE
    tags=["hacking", "targets", "recon"],      # Optional metadata tags
    cooldown=3.0,                               # Optional cooldown in seconds
    prerequisites=[],                           # Optional prerequisite skills
    cost=1.0                                    # Optional execution cost
)
def skill_name(arg1: str, arg2: int = 1) -> str:
    """Docstring becomes the skill tooltip."""
    return "Human-readable result string"
`

### Hacking Skills Currently Registered (6 total)
1. **list_hack_targets(location="")** — List nearby hackable targets
2. **initiate_hack(target_id)** — Generate and return puzzle
3. **submit_hack_solution(puzzle_id, cells, elapsed_seconds)** — Evaluate solution
4. **get_hacking_profile()** — Return player hacking stats
5. **can_hack_target(target_id)** — Feasibility check
6. **register_hack_target(...)** — Admin/director skill to register new targets
7. **reset_hack_target_lock(target_id)** — Admin skill to unlock targets

### Key Pattern from hacking_skills.py
- Uses lazy imports via helper functions (_engine(), _player(), _deck_stats())
- All return human-readable strings (suitable for LLM dialogue)
- Use SkillCategory.GAME for gameplay, SkillCategory.SYSTEM for admin functions
- Skills are stateless — they call engine/world singletons

## 3. ENGINE/WORLD/ DIRECTORY STRUCTURE

Files in engine/world/:
- **city_map.py** — Map representation
- **crew.py** — Crew/party management
- **event_cascade.py** — Event system architecture
- **inventory.py** — Item/equipment system (includes cyberdeck stats)
- **mission.py** — Quest/mission tracking
- **neon_city_events.py** — World events
- **npc_state.py** — NPC state management
- **onboarding.py** — Onboarding system
- **player_state.py** — Player character state (health, credits, heat, skills, reputation)
- **skill_progression.py** — Skill level/XP tracking
- **territory.py** — Territory control system
- **world_announcer.py** — Announcement system
- **world_sim.py** — World simulation loop
- **world_state.py** — Global world state

## 4. NETWORK/CYBERSPACE REFERENCES

### Grid Scene CITY_MAP_NODES (The Grid)
- 15 scene locations (ports 5556-5580, 8500) with:
  - NeonCity travel map with socket.io online/offline detection
  - Faction headquarters (OmniCorp, NeoTech, BlackMarket, Ghost_Net, SynthSec, DeepState)
  - Quest system tied to factions
  - Intel broker feed (Nexus-powered)

### Existing Cybernetic Concepts
- **Cyberdecks** — Equipment items with crack_speed, trace_resist stats
  - netrunner_mk1: +1/+1
  - void_runner: +3/+3
  - specter_3000: +6/+6
- **Software Items** — ICE_Breaker_v1, Shadow_Protocol, Data_Mine, Tracer_Kill
- **Cyberthreat Concepts** — Heat system (accumulated from failed hacks), trace timers, security levels

## 5. EXISTING SKILL CATEGORIES

Used across the project:
- **COMMUNICATION** — messaging, voice, cross-scene
- **MEMORY** — search, store, recall (used by Nexus system)
- **MEDIA** — images, voice, video generation
- **GAME** — game state, dice, scoring (used by hacking skills)
- **SOCIAL** — mood, relationship, contagion (faction pledges, NPC interactions)
- **ENVIRONMENT** — lighting, props, scene changes (grid travel map)
- **SYSTEM** — config, status, admin (used by registration/reset skills)
- **NARRATIVE** — story beats, dialog, narration

For Phase 4 "Hacking Depth," use:
- **GAME** for: hacking attack/defense mechanics, node operations
- **SYSTEM** for: admin/director tools
- **MEMORY** for: intrusion logging, hack history, network mapping
- **SOCIAL** for: social engineering scenarios (if added)

## 6. CONTENT/SCENES/GRID/ DIRECTORY STRUCTURE

- **grid_scene.py** — Main Grid scene Flask app with SocketIO (31.7 KB)
  - _GridState singleton managing market, quests, faction data
  - Market catalogue (16 items: tech, contraband, meds, intel)
  - Faction quests (6 factions × 1 quest each)
  - CITY_MAP_NODES with 15 scene locations
  - Intel broker feed integration
- **grid_skills.py** — 7 skills exposed:
  - grid_buy_item / grid_sell_item
  - grid_get_market_prices
  - grid_faction_pledge
  - grid_accept_quest
  - grid_get_travel_map (with socket checks)
  - grid_broker_intel (Nexus feed queries)
- **static/** — HTML/CSS/JS assets
- **templates/** — Jinja2 templates
- **__init__.py** — Module marker

## 7. HACKTARGET DATA MODEL (from hack_engine.py)

`python
@dataclass
class HackTarget:
    target_id: str                              # Unique ID
    security_level: int = 1                     # 1–5
    label: str = ""                             # Display name
    location: str = ""                          # Scene/area
    rewards: List[str] = []                     # e.g., ["credits:500", "intel:data"]
    locked_until: float = 0.0                   # Epoch timestamp when unlock
    hack_count: int = 0                         # Successful hacks
    last_hacked: float = 0.0                    # Last hack timestamp
`

## 8. HACKPUZZLE DATA MODEL (from hack_engine.py)

`python
@dataclass
class HackPuzzle:
    puzzle_id: str                              # Unique per generation
    target_id: str                              # Target being attacked
    grid: List[List[str]]                       # 4×4 to 6×6 matrix of hex codes
    solution: List[Tuple[int, int]]             # Correct cell sequence
    time_limit: float                           # Seconds before trace completes
    created_at: float = time.time()
    solved: bool = False
    failed: bool = False
`

## 9. HACKRESULT OUTCOME MODEL (from hack_engine.py)

`python
@dataclass
class HackResult:
    success: bool
    target_id: str
    puzzle_id: str
    rewards_granted: List[str]                  # Rewards from target
    heat_delta: int                             # Heat change (0 or positive)
    xp_delta: int                               # Hacking XP gain
    message: str                                # Human-readable outcome
`

## 10. BUILTIN HACKABLE TARGETS (15 default)

From hack_engine.py._register_builtin_targets():

| Target ID | Level | Label | Location | Rewards |
|-----------|-------|-------|----------|---------|
| signal_comms_tower | 3 | Comms Tower | SIGNAL | credits:800, intel:signal_freq |
| penthouse_vault_door | 4 | Vault Door Access | THE PENTHOUSE | credits:2000, item:corp_keycard |
| velvet_atm | 2 | ATM Terminal | THE VELVET PIT | credits:500 |
| anchor_security_cam | 1 | Security Camera | THE RUSTY ANCHOR | intel:anchor_patrol |
| club_noir_vip_list | 2 | VIP Access Terminal | CLUB NOIR | intel:vip_list, credits:200 |
| obscura_server | 4 | Hidden Server Rack | THE OBSCURA | intel:faction_data, credits:1500 |
| colosseum_bet_fix | 3 | Betting System | THE COLOSSEUM | credits:1200 |
| throne_corp_console | 5 | Corp Command Console | THE SHATTERED THRONE | intel:throne_blueprint, credits:3000 |
| neoncity_adboard | 1 | Advertising Board | NEON CITY | credits:100 |
| lab_mainframe | 5 | Lab Mainframe | THE LAB | intel:experiment_data, credits:2500 |
| score_vault | 4 | Score Vault | THE SCORE | credits:1800, item:ghost_net_token |
| cmd_uplink | 3 | Command Uplink | Command Center | intel:orders, credits:600 |
| arcade_high_score | 1 | High Score Board | THE ARCADE | credits:50, intel:player_dossier |
| grid_node_alpha | 3 | Grid Node Alpha | THE GRID | intel:grid_topology, credits:900 |
| briefing_intel_feed | 2 | Intel Feed Terminal | THE BRIEFING ROOM | intel:mission_brief |

## 11. SECURITY & DIFFICULTY PARAMETERS

Scaling by Security Level (1–5):

| Param | Lv1 | Lv2 | Lv3 | Lv4 | Lv5 |
|-------|-----|-----|-----|-----|-----|
| Grid Size | 4×4 | 4×4 | 5×5 | 5×5 | 6×6 |
| Seq Length | 3 | 4 | 4 | 5 | 5 |
| Base Timer (s) | 18 | 15 | 12 | 9 | 7 |
| Fail Heat % | 5% | 8% | 12% | 18% | 25% |
| Lock Duration (s) | 60 | 120 | 180 | 240 | 300 |

Cyberdeck modifiers:
- **trace_resist** +0.4 seconds per point (buffers timer)
- **crack_speed** reduces sequence length by 1 per 3 points (min 2)
- **hacking_skill** +0.5 seconds per level above 1

## 12. KEY ARCHITECTURAL PATTERNS FOR PHASE 4

1. **New skills should go in engine/skills/builtin/hacking_depth_skills.py**
   - Import SkillCategory from engine.skills.skill
   - Follow @skill decorator pattern
   - Return human-readable strings
   - Use lazy imports for singletons

2. **New game logic goes in engine/services/**
   - Keep puzzles/targets in hack_engine.py or create hack_depth_engine.py
   - Thread-safe with locks for concurrent access
   - Singletons with get_xxx() / reset_xxx() pattern

3. **New world state in engine/world/**
   - If tracking ICE/firewall, add to player_state.py or create intrusion_state.py
   - Inventory already has cyberdeck items ready

4. **Grid scene integration**
   - Add skills to content/scenes/grid/grid_skills.py for cyberspace access
   - Extend CITY_MAP_NODES with ICE defense nodes
   - Use Socket.IO for real-time network visualization

5. **Frontend in content/shared/static/js/**
   - Extend cosysim-hack-minigame.js for attack/defense UI
   - Add network visualization (D3.js, Cytoscape, or canvas-based)

## 13. TESTING APPROACH

Pattern from tests/test_hacking.py:
- Use @pytest.fixture(autouse=True) for fresh_engine() isolation
- Mock get_player_state() and deck_stats for unit tests
- Test business logic (calculate, register, list, evaluate)
- Test edge cases (timeout, double-submit, locked targets)
- Test result structure (success/failure messages, rewards, heat)

