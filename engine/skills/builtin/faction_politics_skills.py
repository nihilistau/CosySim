"""
Faction Politics Skills — Social manipulation and faction diplomacy
===================================================================

Skills for agents to engage in political maneuvering: charm, blackmail,
negotiate alliances, spread rumors, bribe officials. These skills
interact with the faction standing system and PlayerState.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: 10 faction politics skills

CONNECTS: PlayerState (faction_standings, reputation, credits), NexusFilesystem
CALLED BY: AgentGovernor skill pipeline
"""
from __future__ import annotations

import logging
import random

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── Helpers ────────────────────────────────────────────────────────────

def _get_player():
    from engine.world.player_state import get_player_state
    return get_player_state()


def _adjust_faction(faction: str, delta: int, reason: str) -> str:
    """Adjust faction standing and return status message."""
    player = _get_player()
    standings = getattr(player, "faction_standings", {})
    old = standings.get(faction, 0)
    new = max(-100, min(100, old + delta))
    standings[faction] = new
    player.faction_standings = standings

    direction = "improved" if delta > 0 else "worsened"
    logger.info(
        "[FactionPolitics] %s: %s %s %+d → %d (operation=faction_adjust)",
        reason, faction, direction, delta, new,
    )
    return f"{faction} standing {direction} by {abs(delta)} ({old:+d} → {new:+d})"


# ──── Skills ─────────────────────────────────────────────────────────────

@skill(
    pack="faction_politics",
    description="Charm an NPC to improve their faction's opinion of you. Uses charisma and social skill.",
    category=SkillCategory.SOCIAL,
    cooldown=30.0,
    cost=1.0,
    tags=["faction", "social", "charm", "reputation"],
)
def charm_npc(target_npc: str, faction: str = "") -> str:
    """Use charm and social skills to improve faction standing.

    Args:
        target_npc: The NPC you're charming.
        faction: Their faction (if known).

    Returns:
        Result of the charm attempt.
    """
    success = random.random() < 0.7  # 70% base success rate
    if success:
        delta = random.randint(3, 8)
        result = _adjust_faction(faction or "unknown", delta, f"Charmed {target_npc}")
        return f"Your charm wins over {target_npc}. {result}"
    else:
        return f"{target_npc} sees through your flattery. No effect — and they're slightly annoyed."


@skill(
    pack="faction_politics",
    description="Blackmail someone with compromising information. High risk, high reward — but damages trust.",
    category=SkillCategory.SOCIAL,
    cooldown=120.0,
    cost=3.0,
    tags=["faction", "social", "blackmail", "dark"],
)
def blackmail(target: str, leverage: str, faction: str = "") -> str:
    """Blackmail a target using compromising information.

    Args:
        target: Who you're blackmailing.
        leverage: What you have on them.
        faction: Their faction.

    Returns:
        Result — compliance or retaliation.
    """
    success = random.random() < 0.5  # 50% — risky
    if success:
        delta = random.randint(5, 15)
        result = _adjust_faction(faction or "unknown", delta, f"Blackmailed {target}")
        player = _get_player()
        player.earn_credits(random.randint(200, 500), f"Blackmail: {target}")
        return f"{target} complies under pressure. {result}. Credits earned from their 'cooperation.'"
    else:
        delta = random.randint(-10, -5)
        result = _adjust_faction(faction or "unknown", delta, f"Failed blackmail on {target}")
        player = _get_player()
        player.heat = min(100, getattr(player, "heat", 0) + 10)
        return f"{target} calls your bluff and reports you. {result}. Heat increased by 10."


@skill(
    pack="faction_politics",
    description="Negotiate a formal alliance with a faction. Requires existing positive standing.",
    category=SkillCategory.SOCIAL,
    cooldown=300.0,
    cost=5.0,
    tags=["faction", "diplomacy", "alliance"],
    prerequisites=["charm_npc"],
)
def negotiate_alliance(faction: str, offering: str = "") -> str:
    """Negotiate a formal alliance with a faction.

    Args:
        faction: The faction to ally with.
        offering: What you're offering in exchange.

    Returns:
        Alliance result.
    """
    player = _get_player()
    standings = getattr(player, "faction_standings", {})
    current = standings.get(faction, 0)

    if current < 20:
        return f"{faction} refuses to negotiate — your standing is too low ({current:+d}). Build trust first."

    delta = random.randint(15, 25)
    result = _adjust_faction(faction, delta, f"Alliance negotiated")
    return f"Alliance formed with {faction}! {result}. They now consider you a trusted partner."


@skill(
    pack="faction_politics",
    description="Spread a rumor about a faction or individual. Can damage reputations or sow discord.",
    category=SkillCategory.SOCIAL,
    cooldown=60.0,
    cost=2.0,
    tags=["faction", "social", "rumor", "manipulation"],
)
def spread_rumor(target_faction: str, rumor: str) -> str:
    """Spread a rumor to damage a faction's reputation.

    Args:
        target_faction: Faction to target with the rumor.
        rumor: The rumor content.

    Returns:
        How the rumor spreads.
    """
    effectiveness = random.choice(["devastating", "moderate", "minor", "backfires"])
    if effectiveness == "devastating":
        delta = random.randint(-12, -8)
        _adjust_faction(target_faction, delta, f"Devastating rumor: {rumor[:50]}")
        return f"The rumor spreads like wildfire. {target_faction}'s reputation takes a major hit."
    elif effectiveness == "moderate":
        delta = random.randint(-6, -3)
        _adjust_faction(target_faction, delta, f"Rumor: {rumor[:50]}")
        return f"The rumor circulates. Some believe it, some don't. {target_faction} notices."
    elif effectiveness == "minor":
        return f"The rumor fizzles. Few people care enough to spread it further."
    else:
        player = _get_player()
        player.adjust_reputation(-5)
        return f"The rumor is traced back to you! Your own reputation suffers (-5)."


@skill(
    pack="faction_politics",
    description="Bribe an official or faction member to look the other way or provide a favor.",
    category=SkillCategory.SOCIAL,
    cooldown=45.0,
    cost=2.0,
    tags=["faction", "bribe", "credits"],
)
def bribe_official(target: str, amount: int = 500, faction: str = "") -> str:
    """Bribe someone with credits.

    Args:
        target: Who to bribe.
        amount: Credits offered.
        faction: Their faction.

    Returns:
        Bribe result.
    """
    player = _get_player()
    if getattr(player, "credits", 0) < amount:
        return f"You don't have enough credits. Need {amount}, have {getattr(player, 'credits', 0)}."

    success = amount >= 300  # Minimum bribe threshold
    if success:
        player.spend_credits(amount, f"Bribe: {target}")
        delta = random.randint(3, 8)
        result = _adjust_faction(faction or "unknown", delta, f"Bribed {target}")
        return f"{target} pockets the {amount} credits and nods. {result}."
    else:
        player.spend_credits(amount, f"Failed bribe: {target}")
        return f"{target} takes the credits but doesn't follow through. Money wasted."


@skill(
    pack="faction_politics",
    description="Request a favor from a faction you have positive standing with.",
    category=SkillCategory.SOCIAL,
    cooldown=180.0,
    cost=3.0,
    tags=["faction", "favor", "alliance"],
)
def request_favor(faction: str, favor_description: str) -> str:
    """Request a favor from a faction.

    Args:
        faction: Which faction to ask.
        favor_description: What you need.

    Returns:
        Whether the faction agrees.
    """
    player = _get_player()
    standings = getattr(player, "faction_standings", {})
    current = standings.get(faction, 0)

    if current < 30:
        return f"{faction} doesn't owe you anything. Standing too low ({current:+d})."

    # Costs standing to cash in a favor
    delta = random.randint(-8, -4)
    _adjust_faction(faction, delta, f"Called in favor: {favor_description[:50]}")
    return (
        f"{faction} agrees to help with: {favor_description}. "
        f"Standing decreased by {abs(delta)} — favors aren't free."
    )


@skill(
    pack="faction_politics",
    description="Betray your current faction alliance. Massive standing loss but potential gain elsewhere.",
    category=SkillCategory.SOCIAL,
    cooldown=600.0,
    cost=10.0,
    tags=["faction", "betrayal", "dark"],
)
def betray_faction(faction: str, new_faction: str = "") -> str:
    """Betray a faction — massive consequences.

    Args:
        faction: Faction to betray.
        new_faction: Who you're betraying them to (optional).

    Returns:
        Consequences of betrayal.
    """
    _adjust_faction(faction, -40, f"Betrayal")
    result = f"You have betrayed {faction}. Standing dropped by 40. They will remember."

    if new_faction:
        _adjust_faction(new_faction, 20, f"Defection from {faction}")
        result += f" {new_faction} welcomes your defection (+20 standing)."

    player = _get_player()
    player.heat = min(100, getattr(player, "heat", 0) + 15)
    result += " Heat increased by 15 — betrayal doesn't go unnoticed."

    return result


@skill(
    pack="faction_politics",
    description="Defect to a new faction. Burns bridges with the old one.",
    category=SkillCategory.SOCIAL,
    cooldown=600.0,
    cost=8.0,
    tags=["faction", "defection"],
)
def defect_to_faction(new_faction: str, old_faction: str = "") -> str:
    """Formally defect to a new faction.

    Args:
        new_faction: Faction to join.
        old_faction: Faction you're leaving (standing penalty).

    Returns:
        Defection result.
    """
    result_parts = []

    if old_faction:
        _adjust_faction(old_faction, -25, f"Defected to {new_faction}")
        result_parts.append(f"Left {old_faction} (-25 standing).")

    _adjust_faction(new_faction, 15, f"Defected from {old_faction or 'independence'}")
    result_parts.append(f"Joined {new_faction} (+15 standing).")

    return " ".join(result_parts) + " Your new allies will test your loyalty."


@skill(
    pack="faction_politics",
    description="Call in a debt someone owes you. Only works if you've done them a favor before.",
    category=SkillCategory.SOCIAL,
    cooldown=120.0,
    cost=2.0,
    tags=["faction", "debt", "leverage"],
)
def call_in_debt(debtor: str, what_you_want: str) -> str:
    """Call in a debt from someone who owes you.

    Args:
        debtor: Who owes you.
        what_you_want: What you're demanding.

    Returns:
        Whether they pay up.
    """
    success = random.random() < 0.65
    if success:
        return f"{debtor} acknowledges the debt and agrees: '{what_you_want}'. The debt is cleared."
    else:
        return f"{debtor} disputes the debt. 'I don't owe you anything.' This could get ugly."


@skill(
    pack="faction_politics",
    description="Deliver a political speech to sway public opinion about a faction.",
    category=SkillCategory.SOCIAL,
    cooldown=180.0,
    cost=3.0,
    tags=["faction", "speech", "public"],
)
def political_speech(topic: str, target_faction: str, stance: str = "support") -> str:
    """Deliver a speech supporting or opposing a faction.

    Args:
        topic: What you're speaking about.
        target_faction: Faction the speech is about.
        stance: "support" or "oppose".

    Returns:
        Impact of the speech.
    """
    player = _get_player()
    charisma = random.randint(1, 10)  # Simulated charisma check

    if stance == "support":
        if charisma >= 5:
            delta = random.randint(5, 12)
            _adjust_faction(target_faction, delta, f"Supportive speech: {topic[:30]}")
            player.adjust_reputation(3)
            return f"Your speech rallies support for {target_faction}. Standing improved. Reputation +3."
        else:
            return "Your speech falls flat. The crowd disperses, unconvinced."
    else:
        if charisma >= 5:
            delta = random.randint(-10, -5)
            _adjust_faction(target_faction, delta, f"Opposing speech: {topic[:30]}")
            return f"Your speech damages {target_faction}'s public image."
        else:
            player.adjust_reputation(-3)
            return f"You're booed off stage. {target_faction} supporters aren't happy. Reputation -3."
