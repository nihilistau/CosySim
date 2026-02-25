"""Games Arcade MCP skills — agent-callable game actions.

Wraps MysteryGame and TruthOrDareGame in @skill decorators so
LLM agents can play games via the MCP skills server.
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
