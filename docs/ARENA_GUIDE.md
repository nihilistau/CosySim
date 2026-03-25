# CosySim Arena Guide — THE COLOSSEUM

> CosySim Documentation — v1.51.0 [2026-03-25]
>
> THE COLOSSEUM is a tactical card-game arena where AI fighters powered by
> LMStudio battle in real-time. Players spectate, place bets, and watch each
> fighter's reasoning unfold live. Port **5561**, accent color **#dc2626**.

---

## Quick Start

```python
from engine.arena.arena_engine import get_arena_engine

engine = get_arena_engine()
match  = engine.create_match("shadow", "blaze")
bet    = engine.place_bet(match.id, "match_winner", "fighter_a", 50)
round1 = engine.play_round(match.id)
engine.resolve_bets(match.id)
```

```powershell
# Launch the arena scene
python launcher.py --scene arena
# Visit http://localhost:5561
```

---

## 1. Arena Scene Overview

Source: `content/scenes/arena/__init__.py`

```python
class ArenaScene(BaseScene, MCPSceneMixin, mcp_scene_id="arena"):
    SCENE_METADATA = {
        "name": "arena",
        "display_name": "THE COLOSSEUM",
        "port": 5561,
        "type": "game",
        "accent_color": "#dc2626",
        "description": "Agent vs agent tactical card game with live betting.",
    }
```

### Architecture

- **Flask + Socket.IO** for HTTP routes and real-time events
- **ArenaEngine** (lazy-loaded) manages match lifecycle
- **MCPSceneMixin** registers the scene with the MCP framework
- **Auto-play mode** drives rounds every 5 seconds in a daemon thread

### HTTP Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Arena template (spectator view) |
| `/api/fighters` | GET | List all known fighters |
| `/api/match/<id>` | GET | Match state and round history |
| `/api/leaderboard` | GET | Career rankings |
| `/api/economy` | GET | Player balance and bet status |
| `/api/framework-status` | GET | MCP framework health |

### Socket.IO Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `create_match` | Client -> Server | Request a new match |
| `play_round` | Client -> Server | Advance to next round |
| `place_bet` | Client -> Server | Place a bet on a fighter |
| `get_match` | Client -> Server | Request current match state |
| `match_update` | Server -> Client | Real-time match state broadcast |
| `round_result` | Server -> Client | Round outcome with reasoning |

---

## 2. Combat System

Source: `engine/arena/arena_engine.py`

The arena uses an **RPS-based (Rock-Paper-Scissors) tactical card game**.
Each round, both fighters select a card from their hand. An LMStudio model
makes the card choice for each fighter, providing tactical reasoning.

### Card Types

| Card Type | Role | Special Behavior |
|-----------|------|------------------|
| **ATTACK** | Deal damage | Standard offensive card |
| **DEFENSE** | Block damage | Reduces incoming damage |
| **SPECIAL** | Unique effects | `double_damage`, `heal`, `steal`, `skip` |
| **WILD** | Random type | Resolves as a random card type |
| **TRAP** | Delayed detonation | Queued to explode next round (2x power) |
| **COUNTER** | Anti-attack | Beats ATTACK for 2x damage |

### Resolution Rules

Resolution follows an extended RPS pattern:

```
1. Traps detonate first (2x power, queued from previous round)
2. WILD cards randomize into ATTACK, DEFENSE, or SPECIAL
3. COUNTER vs ATTACK -> Counter wins, deals 2x damage
4. ATTACK vs DEFENSE -> Net damage = attack power - defense power
5. ATTACK vs ATTACK -> Both take damage from opposing card
6. DEFENSE vs DEFENSE -> Draw (no damage)
7. SPECIAL effects trigger based on effect keyword
```

### Special Effects

| Effect | Behavior |
|--------|----------|
| `double_damage` | Card power is doubled |
| `heal` | Restore HP instead of dealing damage |
| `steal` | Steal HP from opponent |
| `skip` | Opponent loses their turn |

### AI Card Selection

Each fighter is controlled by an LMStudio model. The engine sends a tactical
prompt with the fighter's persona, hand, HP status, and match history. The
model responds with a card selection and reasoning:

```python
# LMStudio call for card selection
response = requests.post(f"{lmstudio_url}/api/v1/chat", json={
    "model": fighter.model_id,
    "messages": [
        {"role": "system", "content": fighter.persona},
        {"role": "user", "content": tactical_prompt},
    ],
    "max_tokens": 150,
    "temperature": 0.8,
})
# Parses: CARD: <card_name>  REASON: <tactical reasoning>
```

---

## 3. Fighter Stats

Source: `engine/arena/arena_engine.py` -> `Fighter` dataclass

```python
@dataclass
class Fighter:
    id: str                    # Unique identifier (e.g. "shadow")
    name: str                  # Display name
    persona: str               # LLM system prompt for personality
    model_id: str              # LMStudio model ID for card selection
    hp: int = 100              # Current hit points
    max_hp: int = 100          # Starting HP
    deck: List[Card] = []     # 15-card draw pile
    hand: List[Card] = []     # Up to 5 held cards
    wins: int = 0              # Career wins
    losses: int = 0            # Career losses
    draws: int = 0             # Career draws
    stats: dict = {}           # Free-form metrics (e.g. last_response_ms)
```

### Default Deck Composition (15 cards)

| Card Type | Count | Purpose |
|-----------|-------|---------|
| ATTACK | 4 | Core offense |
| DEFENSE | 3 | Damage mitigation |
| SPECIAL | 3 | Unique effects |
| WILD | 3 | Unpredictable plays |
| TRAP | 1 | Delayed detonation |
| COUNTER | 1 | Anti-attack tech |

### Fighter Methods

```python
fighter.draw_card(count=1)     # Draw from deck into hand
fighter.play_card(card_id)     # Remove card from hand, return it
fighter.is_alive()             # True if HP > 0
fighter.to_dict()              # JSON-safe serialization
```

---

## 4. Match Lifecycle

### Match Dataclass

```python
@dataclass
class ArenaMatch:
    id: str                            # UUID
    fighter_a: Fighter
    fighter_b: Fighter
    status: MatchStatus                # PENDING -> IN_PROGRESS -> COMPLETE
    rounds: List[RoundOutcome] = []    # Round history
    bets: List[Bet] = []              # All placed bets
    max_rounds: int = 7                # Hard cap
    winner: Optional[str] = None       # "fighter_a" | "fighter_b" | "draw"
    pending_trap_a: Optional[Card]     # Queued trap against fighter A
    pending_trap_b: Optional[Card]     # Queued trap against fighter B
```

### Lifecycle Flow

```
create_match(fighter_a_id, fighter_b_id)
  -> Load/generate fighters, reset HP, shuffle deck, deal 5 cards
  -> Status: PENDING -> IN_PROGRESS
  -> Persist to Nexus

play_round(match_id)              [repeat up to max_rounds]
  -> Both fighters select cards via LMStudio
  -> RPS resolution -> damage applied
  -> Commentary generated
  -> EventBus fires "arena.round_complete"
  -> Check for KO or max rounds

Match end
  -> Winner determined (KO or HP ratio tiebreaker)
  -> Career stats updated (wins/losses/draws)
  -> Bets resolved
  -> Status: COMPLETE
```

### MatchStatus Enum

| Status | Description |
|--------|-------------|
| `PENDING` | Created, waiting to start |
| `IN_PROGRESS` | Rounds being played |
| `COMPLETE` | Winner determined, bets resolved |
| `ABANDONED` | Match cancelled or timed out |

### Auto-Play Mode

When enabled, a daemon thread plays rounds automatically every 5 seconds
and broadcasts results to all connected clients via Socket.IO:

```python
# In ArenaScene -- auto-play loop
def _auto_play_loop(self, match_id: str):
    while match.status == MatchStatus.IN_PROGRESS:
        outcome = self._engine.play_round(match_id)
        socketio.emit("round_result", outcome.to_dict())
        time.sleep(5)
```

---

## 5. Betting System

Source: `engine/arena/arena_engine.py` -> `Bet` dataclass

### Bet Types

| Bet Type | Target | Odds | Description |
|----------|--------|------|-------------|
| `match_winner` | `fighter_a` / `fighter_b` | 2.0x | Predict overall winner |
| `round_winner` | `fighter_a` / `fighter_b` | 1.8x | Predict a round winner |
| `special_move` | Card name | 1.5x | Predict a specific card play |

### Betting Flow

```python
# 1. Place bet -- credits deducted immediately via BET_LOSS
bet = engine.place_bet(match_id, "match_winner", "fighter_a", 100)

# 2. Match plays out...

# 3. Resolve -- winning bets paid out via BET_WIN
engine.resolve_bets(match_id)
# If fighter_a wins: player receives 100 x 2.0 = C200
```

### Economy Integration

- Bet placement deducts credits via `TransactionType.BET_LOSS`
- Winning bets are credited via `TransactionType.BET_WIN`
- Balance is immediately queryable via `/api/economy`
- All transactions appear in the player's economy history

---

## 6. Round Outcomes

Each round produces a `RoundOutcome` record:

```python
@dataclass
class RoundOutcome:
    round_num: int                # 1-based round number
    fighter_a_card: Card          # Card played by fighter A
    fighter_b_card: Card          # Card played by fighter B
    fighter_a_reasoning: str      # LLM tactical reasoning
    fighter_b_reasoning: str      # LLM tactical reasoning
    winner: str                   # "fighter_a" | "fighter_b" | "draw"
    damage_a: int                 # HP damage dealt TO fighter A
    damage_b: int                 # HP damage dealt TO fighter B
    commentary: str               # Generated play-by-play text
    special_triggered: str = ""   # Special effect label (if any)
```

Commentary is generated by a secondary LMStudio call to provide entertaining
play-by-play narration for the spectator experience.

---

## 7. MCP Skills

Source: `content/scenes/arena/arena_skills.py`

All arena skills use `pack="arena"` and `category=SkillCategory.GAME`:

| Skill | Parameters | Description |
|-------|------------|-------------|
| `create_arena_match` | `fighter_a_id, fighter_b_id` | Create a new match |
| `play_arena_round` | `match_id` | Play one round |
| `place_arena_bet` | `match_id, target, amount, bet_type` | Place a bet (5s cooldown) |
| `get_arena_leaderboard` | — | Career rankings by wins |
| `list_arena_fighters` | — | Discover available fighters |

### Example Skill Usage

```python
@skill(pack="arena", category=SkillCategory.GAME, cooldown=5,
       description="Place a bet on an arena match")
def place_arena_bet(match_id: str, target: str, amount: int,
                    bet_type: str = "match_winner") -> str:
    scene = get_active_scene("arena")
    bet = scene._engine.place_bet(match_id, bet_type, target, amount)
    balance = get_economy_manager().get_balance("player")
    return f"Bet placed! C{bet.amount} on {bet.target} | Balance: C{balance}"
```

---

## 8. Leaderboard

Fighter career stats are tracked persistently:

```python
# Query leaderboard
leaders = engine.get_leaderboard()   # sorted by wins

# Individual fighter profile
profile = engine.get_fighter_profile("shadow")
# -> {name, wins, losses, draws, win_rate, ...}
```

The leaderboard is served at `/api/leaderboard` and accessible via the
`get_arena_leaderboard` skill. Fighter profiles persist in Nexus across
sessions and restarts.

---

## 9. Configuration

Arena config in `config/default.yaml`:

```yaml
scenes:
  arena:
    port: 5561
    host: localhost
    accent_color: "#dc2626"

arena:
  max_rounds: 7               # rounds before HP-ratio tiebreaker
  round_interval: 5           # seconds between auto-play rounds
  fighter_hp: 100              # starting HP for fighters
  hand_size: 5                 # cards dealt at match start
  deck_size: 15                # total cards per fighter
  lmstudio_url: "http://localhost:1234"
  agent_max_tokens: 150        # max tokens for card selection
  agent_temperature: 0.8       # creativity for fighter reasoning
  commentary_max_tokens: 120   # max tokens for round commentary
  bet_odds:
    match_winner: 2.0
    round_winner: 1.8
    special_move: 1.5
```

Access via:

```python
cfg = get_config()
max_rounds = cfg.get("arena.max_rounds", 7)
bet_odds = cfg.get("arena.bet_odds.match_winner", 2.0)
```

---

## 10. Integration Points

### Economy

Full two-way integration with `EconomyManager`:
- Bets deducted and paid out through the transaction system
- Player balance available at `/api/economy`
- See [Economy Guide](ECONOMY_GUIDE.md)

### EventBus

Arena events fire on the global bus:
- `arena.match_created` — new match registered
- `arena.round_complete` — round outcome with full details
- `arena.match_complete` — final result with winner
- `arena.bet_resolved` — bet payout event

### Nexus

- Fighter profiles stored and loaded from Nexus
- Match history persisted for analytics
- Career stats survive restarts

### LMStudio

- Each fighter uses a configurable LMStudio model
- Card selection via `/api/v1/chat` with tactical prompts
- Commentary generated as a secondary inference call
- Default URL: `http://localhost:1234`

---

## Cross-References

- [Scenes](SCENES.md) — Scene listing and ports
- [Skills](SKILLS.md) — Full skill reference
- [Game Systems](GAME_SYSTEMS.md) — All game mechanics
- [Economy Guide](ECONOMY_GUIDE.md) — Full economy system
- [LMStudio](LMSTUDIO.md) — LMStudio integration
- [MCP Framework](MCP_FRAMEWORK.md) — MCP state tree
- [Contributing](CONTRIBUTING.md) — Creating new scenes

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Updated header to v1.50, fixed cross-references (CONTENT_GUIDE -> CONTRIBUTING) |
| v1.04 | 2026-03-15 | Initial comprehensive arena documentation with combat, betting, skills, and config |
