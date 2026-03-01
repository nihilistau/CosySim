"""Games Arcade MCP skills — agent-callable game actions.

Wraps MysteryGame and TruthOrDareGame in @skill decorators so
LLM agents can play games via the MCP skills server.

v0.68 Dark Renaissance: adds arcade_state, start_game, get_leaderboard.
"""

from __future__ import annotations

from typing import Dict

from engine.skills.skill import SkillCategory, skill

from .mystery_investigation import MysteryGame
from .truth_or_dare import TruthOrDareGame


# Module-level game instances (shared across skill calls)
_mystery_instances: Dict[str, MysteryGame] = {}
_tod_instances: Dict[str, TruthOrDareGame] = {}


def _get_mystery(player: str = "player") -> MysteryGame:
    if player not in _mystery_instances:
        _mystery_instances[player] = MysteryGame()
    return _mystery_instances[player]


def _get_tod(player: str = "player") -> TruthOrDareGame:
    if player not in _tod_instances:
        _tod_instances[player] = TruthOrDareGame()
    return _tod_instances[player]


def _get_games_scene():
    """Return the live GamesScene instance if available, else None."""
    try:
        from engine.scenes.scene_registry import get_scene_registry
        registry = get_scene_registry()
        return registry.get_scene("games")
    except Exception:
        return None


# ── v0.68 THE ARCADE skills ──────────────────────────────────────────

@skill(
    pack="games",
    tags=["games", "arcade", "status"],
    category=SkillCategory.GAME,
    description="Get available games and current scores in THE ARCADE.",
)
def arcade_state(player: str = "player") -> str:
    """Return current arcade state: available games, active game, and scores."""
    scene = _get_games_scene()
    lines = ["🎮 THE ARCADE — Insert coin. Lose yourself."]
    lines.append("")
    lines.append("Available games: Mystery Board | Dice Challenge | Truth or Dare | Trivia | Word Game")
    if scene:
        active = getattr(scene, "_active_game", {}).get(player)
        lines.append(f"Active game: {active or 'none'}")
        if scene._scene_node:
            state = scene._scene_node.get_state()
            scores = state.get("scores", {}).get(player, {})
            if scores:
                lines.append(
                    f"Your scores — Mysteries: {scores.get('mystery_wins', 0)}W/"
                    f"{scores.get('mystery_losses', 0)}L | "
                    f"ToD: {scores.get('tod_score', 0)}pts | "
                    f"Total: {scores.get('total_points', 0)}pts"
                )
    mystery = _mystery_instances.get(player)
    tod = _tod_instances.get(player)
    if mystery and mystery.active:
        lines.append(f"  🔍 Mystery: Active — {mystery.clues_found}/{mystery.clues_total} clues")
    if tod and tod.active:
        lines.append(f"  🎲 Truth-or-Dare: Active — Score {tod.score}")
    return "\n".join(lines)


@skill(
    pack="games",
    tags=["games", "arcade", "start"],
    category=SkillCategory.GAME,
    description="Start a specific mini-game in THE ARCADE (mystery, dice_challenge, truth_or_dare, trivia, word_game).",
)
def start_game(game_name: str = "mystery", player: str = "player") -> str:
    """Start the named game for the given player."""
    from .games_scene import ARCADE_GAMES
    game_name = game_name.lower().strip()
    if game_name not in ARCADE_GAMES:
        return (
            f"⚠ Unknown game '{game_name}'. "
            f"Available: {', '.join(ARCADE_GAMES)}"
        )
    scene = _get_games_scene()
    if scene:
        if hasattr(scene, "_active_game"):
            scene._active_game[player] = game_name
    return (
        f"🎮 Starting {game_name.replace('_', ' ').title()} for {player}.\n"
        f"Use the Socket.IO interface or specific skill commands to play."
    )


@skill(
    pack="games",
    tags=["games", "arcade", "leaderboard"],
    category=SkillCategory.GAME,
    description="Get the leaderboard for THE ARCADE (top-10 players by total points).",
)
def get_leaderboard() -> str:
    """Return the current Nexus-backed leaderboard."""
    scene = _get_games_scene()
    if not scene:
        return "⚠ THE ARCADE is not active. No leaderboard available."
    lb = scene._get_leaderboard() if hasattr(scene, "_get_leaderboard") else []
    if not lb:
        return "🏆 THE ARCADE Leaderboard — No scores yet. Be the first!"
    lines = ["🏆 THE ARCADE — HIGH SCORES", ""]
    for i, entry in enumerate(lb, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(
            f"{medal} {entry.get('player', '?'):12s}  "
            f"{entry.get('points', 0):>5} pts  "
            f"({entry.get('games', 0)} games)"
        )
    return "\n".join(lines)


# ── Status ──────────────────────────────────────────────────────────

@skill(
    pack="games",
    tags=["games", "status"],
    category=SkillCategory.GAME,
    description="Check status of active games (mystery investigation and truth-or-dare).",
)
def games_status(player: str = "player") -> str:
    mystery = _mystery_instances.get(player)
    tod = _tod_instances.get(player)
    lines = ["🎮 Games Arcade Status:"]
    if mystery and mystery.active:
        lines.append(f"  🔍 Mystery: Active — {mystery.clues_found}/{mystery.clues_total} clues")
    else:
        lines.append("  🔍 Mystery: Not active (use games_mystery_start)")
    if tod and tod.active:
        lines.append(f"  🎲 Truth-or-Dare: Active — Score {tod.score}")
    else:
        lines.append("  🎲 Truth-or-Dare: Not active (use games_tod_start)")
    return "\n".join(lines)


# ── Mystery Investigation ──────────────────────────────────────────

@skill(
    pack="games",
    tags=["games", "mystery", "detective"],
    category=SkillCategory.GAME,
    description="Start a mystery investigation. Optionally specify case index (0-2).",
)
def games_mystery_start(case_index: int = -1, player: str = "player") -> str:
    game = MysteryGame(character_id=player)
    _mystery_instances[player] = game
    result = game.start(case_index if case_index >= 0 else None)
    return (
        f"🔍 Mystery started: {result.get('case_title', 'Unknown')}\n"
        f"Setting: {result.get('setting', '?')}\n"
        f"Find 5 clues, then accuse the culprit!"
    )


@skill(
    pack="games",
    tags=["games", "mystery", "clue"],
    category=SkillCategory.GAME,
    description="Get the next clue in the active mystery investigation.",
    cooldown=3,
)
def games_mystery_clue(player: str = "player") -> str:
    game = _mystery_instances.get(player)
    if not game:
        return "No active mystery. Use games_mystery_start first."
    result = game.next_clue()
    if "message" in result and "No more" in result["message"]:
        return "All clues found! Make your accusation with games_mystery_accuse."
    return (
        f"🟢 Clue ({result.get('clues_found', '?')}/5): "
        f"{result.get('clue', '?')}"
    )


@skill(
    pack="games",
    tags=["games", "mystery", "accuse"],
    category=SkillCategory.GAME,
    description="Accuse the culprit in the mystery. Name must match closely.",
    cooldown=5,
)
def games_mystery_accuse(suspect: str = "", player: str = "player") -> str:
    game = _mystery_instances.get(player)
    if not game:
        return "No active mystery."
    if not suspect:
        return "You must name a suspect!"
    result = game.accuse(suspect)
    if result.get("correct"):
        return f"🎉 CORRECT! The culprit was {result.get('real_culprit', '?')}. Case solved!"
    return f"❌ Wrong! '{suspect}' is not the culprit. The real culprit was {result.get('real_culprit', '?')}."


# ── Truth or Dare ──────────────────────────────────────────────────

@skill(
    pack="games",
    tags=["games", "truth_or_dare", "social"],
    category=SkillCategory.GAME,
    description="Start a truth-or-dare game.",
)
def games_tod_start(player: str = "player") -> str:
    game = TruthOrDareGame(character_id=player)
    _tod_instances[player] = game
    game.start()
    return "🎲 Truth or Dare started! Roll the dice to get a prompt."


@skill(
    pack="games",
    tags=["games", "truth_or_dare", "dice"],
    category=SkillCategory.GAME,
    description="Roll dice in truth-or-dare. Odd = truth, even = dare.",
    cooldown=3,
)
def games_tod_roll(player: str = "player") -> str:
    game = _tod_instances.get(player)
    if not game:
        return "No active truth-or-dare game. Use games_tod_start first."
    try:
        result = game.roll()
    except RuntimeError as e:
        return f"⚠ {e}"
    kind = result.get("type", "truth")
    emoji = "💬" if kind == "truth" else "🔥"
    return (
        f"{emoji} {kind.upper()} (rolled {result.get('roll', '?')}):\n"
        f"{result.get('prompt', '?')}"
    )


@skill(
    pack="games",
    tags=["games", "truth_or_dare", "answer"],
    category=SkillCategory.GAME,
    description="Submit an answer for the current truth-or-dare prompt.",
    cooldown=3,
)
def games_tod_answer(answer: str = "", player: str = "player") -> str:
    game = _tod_instances.get(player)
    if not game:
        return "No active truth-or-dare game."
    result = game.answer(completed=True, response=answer)
    score = result.get("score", 0)
    if score >= 5:
        return f"🎉 You WIN! Final score: {score}. Game complete!"
    return f"✅ Answer recorded. Score: {score}. Roll again!"
