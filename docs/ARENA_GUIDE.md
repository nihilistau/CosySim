# CosySim Arena Guide — THE COLOSSEUM

> Tactical agent card game. AI fighters powered by LMStudio. Live betting.
> New scene in v0.68 "Dark Renaissance". Port: 5561.

## Overview

THE COLOSSEUM hosts agent vs agent tactical card games. Local LMStudio models
are the fighters — their reasoning is benchmarked live on the BenchHUD.
Players can bet with economy credits. NLM provides commentary.

## ArenaEngine (`engine/arena/arena_engine.py`)

RPS-based card resolution. Each fighter chooses ATTACK/DEFEND/SPECIAL.
Matches auto-play via daemon thread at 5s intervals.

```python
from engine.arena.arena_engine import get_arena_engine, ArenaEngine
arena = get_arena_engine()
match_id = arena.create_match("fighter_a", "fighter_b")
arena.start_match(match_id)   # daemon thread takes over
result = arena.get_match_result(match_id)
```

## Skills

| Skill | Description |
|-------|-------------|
| `get_arena_standings` | Current leaderboard |
| `place_arena_bet` | Bet credits on a fighter |
| `get_match_commentary` | NLM match analysis |
| `challenge_agent` | Create a new match |
| `get_fighter_stats` | Fighter win/loss record |
