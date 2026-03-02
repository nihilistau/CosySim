"""Reputation skills — manage player-NPC reputation scores."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill
from engine.mcp import get_framework

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
#  Skills
# ──────────────────────────────────────────────────────────────────────────────

@skill(pack="reputation", description="Get player's reputation with an NPC", category="SOCIAL")
def get_reputation(character_id: str, player_id: str = "player") -> str:
    """Return a formatted reputation summary for one NPC."""
    fw = get_framework()
    rep = int(fw.get(f"characters.{character_id}.reputation.{player_id}", 0))
    label = _rep_label(rep)
    return f"{character_id}'s opinion of {player_id}: {rep:+d} [{label}]"


@skill(
    pack="reputation",
    description="Modify player reputation with an NPC",
    category="SOCIAL",
    cost=1.0,
)
def modify_reputation(
    character_id: str,
    delta: int,
    reason: str = "",
    player_id: str = "player",
) -> str:
    """Adjust an NPC's reputation score by *delta* (clamped to ±100)."""
    fw = get_framework()
    key = f"characters.{character_id}.reputation.{player_id}"
    current = int(fw.get(key, 0))
    new_val = max(-100, min(100, current + delta))
    fw.set(key, new_val)
    direction = "📈" if delta > 0 else "📉"
    label = _rep_label(new_val)
    msg = f"{direction} {character_id} reputation: {current:+d} → {new_val:+d} [{label}]"
    if reason:
        msg += f" (reason: {reason})"
    logger.info(msg)
    return msg


@skill(
    pack="reputation",
    description="Get all NPC reputation scores for player",
    category="SOCIAL",
)
def get_all_reputations(player_id: str = "player") -> str:
    """Return reputation scores for every character in the MCP tree."""
    fw = get_framework()
    chars = fw.get("characters", {})
    lines = []
    for char_id, char_data in chars.items():
        rep_data = char_data.get("reputation", {}) if isinstance(char_data, dict) else {}
        rep = int(rep_data.get(player_id, 0))
        lines.append(f"  {char_id}: {rep:+d} [{_rep_label(rep)}]")
    if not lines:
        return "No character reputation data found."
    return "Reputation scores:\n" + "\n".join(sorted(lines))


# ──────────────────────────────────────────────────────────────────────────────
#  Helper (also imported by DialogueGateInterceptor tests)
# ──────────────────────────────────────────────────────────────────────────────

def _rep_label(score: int) -> str:
    """Return a human-readable disposition label for a reputation score."""
    if score >= 75:
        return "devoted"
    if score >= 50:
        return "trusted"
    if score >= 20:
        return "friendly"
    if score > -20:
        return "neutral"
    if score > -50:
        return "wary"
    if score > -75:
        return "hostile"
    return "enemy"
