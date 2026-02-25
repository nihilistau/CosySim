"""Tavern scene rules — atmosphere gates, reputation checks, NPC behaviour.

Defines the rule predicates and directives that shape agent behaviour
in the Dragon's Flagon scene.  Imported by tavern_scene.py at init.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .tavern_state import Atmosphere, NPC_PROFILES, TavernState, TimeOfDay


# ---------------------------------------------------------------------------
#  Atmosphere → directive text (injected into agent system prompt)
# ---------------------------------------------------------------------------

ATMOSPHERE_DIRECTIVES: Dict[Atmosphere, str] = {
    Atmosphere.QUIET: (
        "The tavern is quiet — only a few patrons murmur over their drinks. "
        "Speak softly, be observant. Good time for private conversation."
    ),
    Atmosphere.LIVELY: (
        "The tavern is lively — laughter, music, clinking tankards fill the air. "
        "Be sociable and energetic. Patrons are in good spirits."
    ),
    Atmosphere.ROWDY: (
        "The tavern is rowdy — voices are raised, someone just spilled a drink. "
        "Tensions are high. Choose words carefully or risk a fight."
    ),
    Atmosphere.BRAWL: (
        "A BRAWL has broken out! Chairs are flying, fists are swinging. "
        "Duck, fight, or try to calm things down. Greta is furious."
    ),
}

TIME_DIRECTIVES: Dict[TimeOfDay, str] = {
    TimeOfDay.MORNING: (
        "It's morning — the tavern is mostly empty. Greta sweeps the floor. "
        "Only the most dedicated drinkers are here."
    ),
    TimeOfDay.AFTERNOON: (
        "Afternoon light streams through dusty windows. Merchants conduct "
        "business over lunch. The bard tunes his lute."
    ),
    TimeOfDay.EVENING: (
        "Evening has fallen. The tavern fills up. The fire crackles. "
        "This is when the tavern truly comes alive."
    ),
    TimeOfDay.MIDNIGHT: (
        "Midnight. Only shadows and secrets remain. The stranger's hour. "
        "Those still here have reasons to be."
    ),
}

# ---------------------------------------------------------------------------
#  Reputation gates
# ---------------------------------------------------------------------------

REPUTATION_GATES: Dict[str, List[Dict[str, Any]]] = {
    "greta": [
        {"min": 70, "unlock": "cellar_access",
         "text": "Greta trusts you enough to let you into the cellar."},
        {"min": 80, "unlock": "secret_menu",
         "text": "Greta offers you drinks from the secret menu."},
    ],
    "bard": [
        {"min": 65, "unlock": "private_song",
         "text": "The bard will perform a song just for you."},
        {"min": 80, "unlock": "true_name",
         "text": "The bard reveals his true name and past."},
    ],
    "merchant": [
        {"min": 60, "unlock": "discount",
         "text": "The merchant gives you a 20% discount."},
        {"min": 80, "unlock": "rare_goods",
         "text": "The merchant shows you rare enchanted items."},
    ],
    "stranger": [
        {"min": 60, "unlock": "real_quest",
         "text": "The stranger hints at a deeper quest."},
        {"min": 85, "unlock": "identity",
         "text": "The stranger reveals their true identity."},
    ],
}


def get_unlocked_features(state: TavernState) -> List[str]:
    """Return list of features the player has unlocked via reputation."""
    unlocked = []
    for npc_id, gates in REPUTATION_GATES.items():
        rep = state.reputation.get(npc_id, 50)
        for gate in gates:
            if rep >= gate["min"]:
                unlocked.append(gate["unlock"])
    return unlocked


def get_reputation_directive(state: TavernState, npc_id: str) -> str:
    """Build a directive string describing the NPC's attitude toward player."""
    tier = state.get_reputation_tier(npc_id)
    profile = NPC_PROFILES.get(npc_id, {})
    name = profile.get("name", npc_id)

    attitude_map = {
        "hostile": f"{name} is hostile — refuses service, answers curtly, may call guards.",
        "wary": f"{name} is wary — short answers, won't share secrets, watches carefully.",
        "neutral": f"{name} is neutral — polite but guarded. Standard service.",
        "friendly": f"{name} is friendly — shares gossip, offers better deals, warm tone.",
        "trusted": f"{name} fully trusts the player — shares secrets, grants special access, warm and open.",
    }
    return attitude_map.get(tier, "")


# ---------------------------------------------------------------------------
#  Stat-gated actions
# ---------------------------------------------------------------------------

def can_haggle(state: TavernState) -> bool:
    """Player needs clarity ≥40 and charm ≥30 to haggle effectively."""
    return state.stats["clarity"] >= 40 and state.stats["charm"] >= 30


def can_start_brawl(state: TavernState) -> bool:
    """Only possible when atmosphere is rowdy and courage ≥60."""
    return state.atmosphere in (Atmosphere.ROWDY, Atmosphere.BRAWL) and state.stats["courage"] >= 60


def can_approach_stranger(state: TavernState) -> bool:
    """Stranger only appears at night; need courage ≥40."""
    return ("stranger" in state.npcs_present and state.stats["courage"] >= 40)


# ---------------------------------------------------------------------------
#  Build full scene directive
# ---------------------------------------------------------------------------

def build_scene_directive(state: TavernState, npc_id: str | None = None) -> str:
    """Assemble the complete scene context directive for the LLM.

    This is injected into the system prompt to guide agent behaviour.
    """
    parts = [
        "## Scene: The Dragon's Flagon Tavern",
        f"Turn {state.turn} | Gold: {state.gold} | Heat: {state.heat}/100",
        "",
        ATMOSPHERE_DIRECTIVES.get(state.atmosphere, ""),
        TIME_DIRECTIVES.get(state.time_of_day, ""),
        "",
    ]

    # NPC-specific directive
    if npc_id and npc_id in NPC_PROFILES:
        prof = NPC_PROFILES[npc_id]
        parts.append(f"You are **{prof['name']}**, the {prof['role']}.")
        parts.append(f"Personality: {prof['personality']}")
        parts.append(f"Speech style: {prof['speech_style']}")
        parts.append(get_reputation_directive(state, npc_id))
        parts.append("")

    # Active quests context
    active = state.get_active_quests()
    if active:
        parts.append("Active quests: " + ", ".join(
            f"{q.title} ({q.progress}/{q.max_progress})" for q in active
        ))

    # Unlocked features
    unlocked = get_unlocked_features(state)
    if unlocked:
        parts.append(f"Player has unlocked: {', '.join(unlocked)}")

    # Stats summary
    stats = state.stats
    drunk = state.stats["clarity"] < 40
    if drunk:
        parts.append("⚠ The player is quite drunk — slurred speech, impaired judgement.")

    return "\n".join(parts)
