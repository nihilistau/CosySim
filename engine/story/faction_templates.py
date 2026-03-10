"""Default faction templates for all 9 CosySim scenes.

Call ``seed_all_factions()`` once at startup (or in tests) to populate
the singleton FactionManager with the standard scene factions.
"""
from __future__ import annotations

from engine.story.faction_politics import Faction, get_faction_manager

# ──── Faction definitions ────────────────────────────────────────────────────

SCENE_FACTIONS: dict = {
    # ── penthouse ────────────────────────────────────────────────────────────
    "penthouse": [
        Faction(
            id="elite",
            name="The Elite",
            scene="penthouse",
            description="High-society insiders who pull the strings.",
            player_standing=10,
            relationships={"press": -30},
            tags=["power", "social"],
        ),
        Faction(
            id="press",
            name="The Press",
            scene="penthouse",
            description="Journalists and gossip networks — neutral observers.",
            player_standing=0,
            relationships={"elite": -30},
            tags=["media", "neutral"],
        ),
    ],
    # ── casino ─────────────────────────────────────────────────────────────
    "casino": [
        Faction(
            id="house",
            name="The House",
            scene="casino",
            description="Casino management and ownership.",
            player_standing=0,
            relationships={"players": -50, "enforcers": 60},
            tags=["authority", "finance"],
        ),
        Faction(
            id="players",
            name="The Players",
            scene="casino",
            description="The gamblers' syndicate — always looking for an edge.",
            player_standing=0,
            relationships={"house": -50, "enforcers": -40},
            tags=["underground", "risk"],
        ),
        Faction(
            id="enforcers",
            name="The Enforcers",
            scene="casino",
            description="Muscle for hire — loyal to whoever pays.",
            player_standing=0,
            relationships={"house": 60, "players": -40},
            tags=["violence", "order"],
        ),
    ],
    # ── arena ──────────────────────────────────────────────────────────────
    "arena": [
        Faction(
            id="gladiators",
            name="The Gladiators",
            scene="arena",
            description="Warriors who live and die by the crowd.",
            player_standing=0,
            relationships={"promoters": -20, "underground": -60},
            tags=["combat", "honor"],
        ),
        Faction(
            id="promoters",
            name="The Promoters",
            scene="arena",
            description="Showmen who profit from spectacle.",
            player_standing=0,
            relationships={"gladiators": -20, "underground": 40},
            tags=["commerce", "spectacle"],
        ),
        Faction(
            id="underground",
            name="The Underground",
            scene="arena",
            description="Shadow organisers of unsanctioned bouts.",
            player_standing=0,
            relationships={"gladiators": -60, "promoters": 40},
            tags=["criminal", "shadow"],
        ),
    ],
    # ── tavern ─────────────────────────────────────────────────────────────
    "tavern": [
        Faction(
            id="guild",
            name="The Guild",
            scene="tavern",
            description="Craftsmen and merchants who keep order.",
            player_standing=0,
            relationships={"outlaws": -60, "guard": 40},
            tags=["commerce", "law"],
        ),
        Faction(
            id="outlaws",
            name="The Outlaws",
            scene="tavern",
            description="Brigands and smugglers who thrive in chaos.",
            player_standing=0,
            relationships={"guild": -60, "guard": -70},
            tags=["criminal", "freedom"],
        ),
        Faction(
            id="guard",
            name="The Guard",
            scene="tavern",
            description="Town watch enforcing the king's law.",
            player_standing=0,
            relationships={"guild": 40, "outlaws": -70},
            tags=["authority", "order"],
        ),
    ],
    # ── lounge ─────────────────────────────────────────────────────────────
    "lounge": [
        Faction(
            id="inner_circle",
            name="The Inner Circle",
            scene="lounge",
            description="Exclusive inner ring of power brokers.",
            player_standing=0,
            relationships={"outsiders": -50},
            tags=["power", "exclusive"],
        ),
        Faction(
            id="outsiders",
            name="The Outsiders",
            scene="lounge",
            description="Those who want in — willing to do whatever it takes.",
            player_standing=0,
            relationships={"inner_circle": -50},
            tags=["ambition", "fringe"],
        ),
    ],
    # ── gallery ────────────────────────────────────────────────────────────
    "gallery": [
        Faction(
            id="collectors",
            name="The Collectors",
            scene="gallery",
            description="Wealthy patrons obsessed with acquisition.",
            player_standing=0,
            relationships={"thieves": -70, "curators": 30},
            tags=["wealth", "art"],
        ),
        Faction(
            id="thieves",
            name="The Thieves Network",
            scene="gallery",
            description="Professional art thieves and forgers.",
            player_standing=0,
            relationships={"collectors": -70, "curators": -40},
            tags=["criminal", "art"],
        ),
        Faction(
            id="curators",
            name="The Curators",
            scene="gallery",
            description="Scholars and conservators who prize authenticity.",
            player_standing=0,
            relationships={"collectors": 30, "thieves": -40},
            tags=["culture", "knowledge"],
        ),
    ],
    # ── realm ──────────────────────────────────────────────────────────────
    "realm": [
        Faction(
            id="crown",
            name="The Crown",
            scene="realm",
            description="The royal court and its loyalists.",
            player_standing=0,
            relationships={"rebels": -80, "clergy": 30},
            tags=["royalty", "authority"],
        ),
        Faction(
            id="rebels",
            name="The Rebels",
            scene="realm",
            description="Insurgents fighting for a new order.",
            player_standing=0,
            relationships={"crown": -80, "clergy": -20},
            tags=["revolution", "freedom"],
        ),
        Faction(
            id="clergy",
            name="The Clergy",
            scene="realm",
            description="Religious order that mediates between power factions.",
            player_standing=0,
            relationships={"crown": 30, "rebels": -20},
            tags=["religion", "neutral"],
        ),
    ],
    # ── neoncity ───────────────────────────────────────────────────────────
    "neoncity": [
        Faction(
            id="omnicorp",
            name="OmniCorp",
            scene="neoncity",
            description="The megacorporation that owns the city grid.",
            player_standing=0,
            relationships={"ghost_net": -70, "synthsec": 50},
            tags=["corporate", "authority"],
        ),
        Faction(
            id="ghost_net",
            name="Ghost_Net",
            scene="neoncity",
            description="Anarchist hacker collective living off the grid.",
            player_standing=0,
            relationships={"omnicorp": -70, "synthsec": -40},
            tags=["hackers", "freedom"],
        ),
        Faction(
            id="synthsec",
            name="SynthSec",
            scene="neoncity",
            description="Private security contractor — loyal to the highest bidder.",
            player_standing=0,
            relationships={"omnicorp": 50, "ghost_net": -40},
            tags=["security", "mercenary"],
        ),
    ],
    # ── phone ──────────────────────────────────────────────────────────────
    "phone": [
        Faction(
            id="network",
            name="The Network",
            scene="phone",
            description="Your intelligence support network.",
            player_standing=20,
            relationships={"rivals": -60},
            tags=["intelligence", "allies"],
        ),
        Faction(
            id="rivals",
            name="The Rivals",
            scene="phone",
            description="Competing intelligence operatives.",
            player_standing=-20,
            relationships={"network": -60},
            tags=["intelligence", "adversary"],
        ),
    ],
}


def seed_all_factions() -> int:
    """Register all default factions with the singleton FactionManager.

    Returns:
        Total number of factions registered.
    """
    mgr = get_faction_manager()
    count = 0
    for _scene, factions in SCENE_FACTIONS.items():
        for faction in factions:
            mgr.register(faction)
            count += 1
    return count
