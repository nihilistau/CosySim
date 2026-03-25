"""
Heist Planning Skills — Reconnaissance, planning, and execution
================================================================

Skills for agents to plan and execute heists: case targets, find
weaknesses, recruit specialists, plan entry/escape routes, acquire
tools, set distractions, and execute the job.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: 8 heist planning skills

CONNECTS: PlayerState (credits, heat), NexusFilesystem, MCPFramework
CALLED BY: AgentGovernor skill pipeline
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── Heist State ────────────────────────────────────────────────────────

# In-memory heist plans (keyed by heist_id)
_ACTIVE_HEISTS: dict = {}


def _get_heist(heist_id: str) -> dict:
    """Get or create a heist plan."""
    if heist_id not in _ACTIVE_HEISTS:
        _ACTIVE_HEISTS[heist_id] = {
            "id": heist_id,
            "target": "",
            "weaknesses": [],
            "specialists": [],
            "entry_plan": "",
            "escape_plan": "",
            "tools": [],
            "distractions": [],
            "status": "planning",
            "risk_level": 50,
            "created_at": datetime.now().isoformat(),
        }
    return _ACTIVE_HEISTS[heist_id]


def _save_heist_to_fs(heist: dict) -> None:
    """Persist heist plan to virtual filesystem."""
    try:
        from engine.nexus.filesystem import get_filesystem
        fs = get_filesystem()
        path = f"/home/player/heists/{heist['id']}.json"
        fs.write(path, json.dumps(heist, indent=2), metadata={"type": "heist_plan"})
    except Exception:
        pass


# ──── Skills ─────────────────────────────────────────────────────────────

@skill(
    pack="heist_planning",
    description="Case a target to gather intelligence before a heist. First step in planning.",
    category=SkillCategory.GAME,
    cooldown=30.0,
    cost=2.0,
    tags=["heist", "recon", "planning"],
)
def case_target(target_name: str, target_type: str = "building") -> str:
    """Case a target location or entity for a heist.

    Args:
        target_name: What you're planning to hit.
        target_type: building, person, vehicle, data_node, vault.

    Returns:
        Heist ID and initial recon findings.
    """
    heist_id = f"heist_{uuid.uuid4().hex[:6]}"
    heist = _get_heist(heist_id)
    heist["target"] = target_name
    heist["target_type"] = target_type

    # Generate random recon findings
    findings = {
        "building": [
            "Two guards rotate every 20 minutes",
            "Rear entrance has a faulty lock sensor",
            "Security cameras have a 3-second blind spot during rotation",
            "Loading dock is unmonitored between 2-4 AM",
        ],
        "data_node": [
            "ICE is aggressive but predictable — pattern resets every 90 seconds",
            "Backup power kicks in after 15 seconds of main power loss",
            "Admin credentials rotate weekly — next rotation in 3 days",
            "Node has a debug port that was never disabled",
        ],
        "vault": [
            "Biometric scanner can be bypassed with a thermal overlay",
            "Time-lock opens for 30 minutes at dawn for maintenance",
            "Vault walls are reinforced but the floor is standard concrete",
            "Internal sensors are motion-based — slow movement goes undetected",
        ],
    }

    found = random.sample(findings.get(target_type, findings["building"]), 2)
    heist["weaknesses"] = found

    _save_heist_to_fs(heist)

    logger.info("[HeistPlanning] Target cased (operation=case_target, heist=%s, target=%s)", heist_id, target_name)
    return (
        f"Heist plan started: {heist_id}\n"
        f"Target: {target_name} ({target_type})\n"
        f"Initial recon findings:\n"
        + "\n".join(f"  - {f}" for f in found)
    )


@skill(
    pack="heist_planning",
    description="Analyze a target's weaknesses in more detail. Requires casing first.",
    category=SkillCategory.GAME,
    cooldown=20.0,
    cost=1.0,
    tags=["heist", "recon", "analysis"],
)
def find_weaknesses(heist_id: str) -> str:
    """Dig deeper into target weaknesses.

    Args:
        heist_id: The heist plan ID from case_target.

    Returns:
        Additional weaknesses found.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found with ID: {heist_id}. Case a target first."

    heist = _get_heist(heist_id)
    new_weakness = random.choice([
        "Shift change creates a 5-minute window with half security",
        "The target's IT contractor has gambling debts — susceptible to bribery",
        "Fire alarm system triggers full evacuation — 8 minute response time",
        "Sewer access tunnel connects to basement — unmapped by security",
        "Cleaning crew has unrestricted access after hours",
        "Emergency backup generator is external and accessible",
    ])

    heist["weaknesses"].append(new_weakness)
    heist["risk_level"] = max(20, heist["risk_level"] - 5)
    _save_heist_to_fs(heist)

    return f"New weakness found: {new_weakness}\nRisk level: {heist['risk_level']}%"


@skill(
    pack="heist_planning",
    description="Recruit a specialist for the heist. Each specialist type improves different aspects.",
    category=SkillCategory.GAME,
    cooldown=45.0,
    cost=3.0,
    tags=["heist", "crew", "recruit"],
)
def recruit_specialist(heist_id: str, specialist_type: str) -> str:
    """Recruit a specialist for the heist crew.

    Args:
        heist_id: The heist plan ID.
        specialist_type: hacker, muscle, driver, insider, demolitions, face.

    Returns:
        Recruitment result and risk adjustment.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found: {heist_id}"

    specialists = {
        "hacker": {"name": "Byte", "skill": "Digital infiltration", "risk_mod": -10, "cost": 500},
        "muscle": {"name": "Tank", "skill": "Security neutralization", "risk_mod": -8, "cost": 300},
        "driver": {"name": "Drift", "skill": "Extraction under pursuit", "risk_mod": -7, "cost": 400},
        "insider": {"name": "Whisper", "skill": "Internal access + intel", "risk_mod": -15, "cost": 800},
        "demolitions": {"name": "Boom", "skill": "Structural bypass", "risk_mod": -5, "cost": 600},
        "face": {"name": "Silk", "skill": "Social engineering + disguise", "risk_mod": -12, "cost": 450},
    }

    if specialist_type not in specialists:
        return f"Unknown specialist type. Available: {', '.join(specialists.keys())}"

    spec = specialists[specialist_type]
    heist = _get_heist(heist_id)

    # Check if already recruited
    if specialist_type in [s["type"] for s in heist["specialists"]]:
        return f"Already have a {specialist_type} on the crew."

    player = None
    try:
        from engine.world.player_state import get_player_state
        player = get_player_state()
        if getattr(player, "credits", 0) < spec["cost"]:
            return f"Can't afford {spec['name']}. Need {spec['cost']} credits."
        player.spend_credits(spec["cost"], f"Heist crew: {spec['name']}")
    except Exception:
        pass

    heist["specialists"].append({"type": specialist_type, **spec})
    heist["risk_level"] = max(10, heist["risk_level"] + spec["risk_mod"])
    _save_heist_to_fs(heist)

    return (
        f"Recruited {spec['name']} ({specialist_type}): {spec['skill']}\n"
        f"Cost: {spec['cost']} credits\n"
        f"Risk level: {heist['risk_level']}%"
    )


@skill(
    pack="heist_planning",
    description="Plan the entry method for the heist.",
    category=SkillCategory.GAME,
    cooldown=20.0,
    cost=1.0,
    tags=["heist", "planning", "entry"],
)
def plan_entry(heist_id: str, method: str) -> str:
    """Plan how to get in.

    Args:
        heist_id: The heist plan ID.
        method: Approach — stealth, force, social, digital, underground.

    Returns:
        Entry plan details.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found: {heist_id}"

    methods = {
        "stealth": "Silent entry through identified blind spots. Requires patience.",
        "force": "Breach and clear. Fast but loud. 2-minute window before response.",
        "social": "Walk in disguised as authorized personnel. Requires a face specialist.",
        "digital": "Remote access through compromised systems. Requires a hacker.",
        "underground": "Physical tunnel or utility access. Slow but undetectable.",
    }

    if method not in methods:
        return f"Unknown method. Available: {', '.join(methods.keys())}"

    heist = _get_heist(heist_id)
    heist["entry_plan"] = f"{method}: {methods[method]}"

    risk_mods = {"stealth": -5, "force": 10, "social": -8, "digital": -3, "underground": -10}
    heist["risk_level"] = max(5, min(95, heist["risk_level"] + risk_mods.get(method, 0)))
    _save_heist_to_fs(heist)

    return f"Entry plan set: {method}\n{methods[method]}\nRisk: {heist['risk_level']}%"


@skill(
    pack="heist_planning",
    description="Plan the escape route after the heist.",
    category=SkillCategory.GAME,
    cooldown=20.0,
    cost=1.0,
    tags=["heist", "planning", "escape"],
)
def plan_escape(heist_id: str, route: str) -> str:
    """Plan how to get out.

    Args:
        heist_id: The heist plan ID.
        route: Escape method — vehicle, rooftop, underground, blend, digital.

    Returns:
        Escape plan details.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found: {heist_id}"

    routes = {
        "vehicle": "High-speed extraction. Driver waits 2 blocks out. Requires a driver.",
        "rooftop": "Rooftop hop to adjacent building. Requires climbing gear.",
        "underground": "Exit through utility tunnels. Slow but safe. Pre-mapped route.",
        "blend": "Change clothes, walk out the front door. Requires nerves of steel.",
        "digital": "Never physically present. All remote. The best escape is not being there.",
    }

    if route not in routes:
        return f"Unknown route. Available: {', '.join(routes.keys())}"

    heist = _get_heist(heist_id)
    heist["escape_plan"] = f"{route}: {routes[route]}"
    _save_heist_to_fs(heist)

    return f"Escape plan set: {route}\n{routes[route]}"


@skill(
    pack="heist_planning",
    description="Acquire tools and equipment needed for the heist.",
    category=SkillCategory.GAME,
    cooldown=30.0,
    cost=2.0,
    tags=["heist", "equipment", "planning"],
)
def acquire_tools(heist_id: str, tool_name: str) -> str:
    """Acquire equipment for the heist.

    Args:
        heist_id: The heist plan ID.
        tool_name: What to acquire — lockpicks, EMP, disguise_kit, signal_jammer, thermal_cutter, smoke_grenades.

    Returns:
        Acquisition result.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found: {heist_id}"

    tools = {
        "lockpicks": {"cost": 100, "risk_mod": -3, "desc": "Electronic lockpick set — opens most doors in under 10s"},
        "EMP": {"cost": 800, "risk_mod": -8, "desc": "Localized EMP — kills electronics in 20m radius for 60s"},
        "disguise_kit": {"cost": 300, "risk_mod": -5, "desc": "Professional disguise kit — face prosthetics + ID forge"},
        "signal_jammer": {"cost": 500, "risk_mod": -6, "desc": "Comms jammer — blocks all radio in 50m for 5min"},
        "thermal_cutter": {"cost": 600, "risk_mod": -4, "desc": "Plasma cutter — cuts through reinforced steel in 30s"},
        "smoke_grenades": {"cost": 150, "risk_mod": -2, "desc": "6x smoke grenades — visual cover for 90s"},
    }

    if tool_name not in tools:
        return f"Unknown tool. Available: {', '.join(tools.keys())}"

    tool = tools[tool_name]
    heist = _get_heist(heist_id)

    try:
        from engine.world.player_state import get_player_state
        player = get_player_state()
        if getattr(player, "credits", 0) < tool["cost"]:
            return f"Can't afford {tool_name}. Need {tool['cost']} credits."
        player.spend_credits(tool["cost"], f"Heist gear: {tool_name}")
    except Exception:
        pass

    heist["tools"].append(tool_name)
    heist["risk_level"] = max(5, heist["risk_level"] + tool["risk_mod"])
    _save_heist_to_fs(heist)

    return f"Acquired: {tool_name} — {tool['desc']}\nCost: {tool['cost']} credits\nRisk: {heist['risk_level']}%"


@skill(
    pack="heist_planning",
    description="Set up a distraction to draw attention away from the heist.",
    category=SkillCategory.GAME,
    cooldown=45.0,
    cost=2.0,
    tags=["heist", "distraction", "planning"],
)
def set_distraction(heist_id: str, distraction_type: str) -> str:
    """Set up a distraction for the heist.

    Args:
        heist_id: The heist plan ID.
        distraction_type: fire_alarm, power_outage, fake_emergency, street_fight, cyber_attack.

    Returns:
        Distraction setup result.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found: {heist_id}"

    types = {
        "fire_alarm": {"risk_mod": -8, "heat_mod": 3, "desc": "Pull the fire alarm — 8min evacuation window"},
        "power_outage": {"risk_mod": -10, "heat_mod": 5, "desc": "Cut main power — security goes to backup (15s blind)"},
        "fake_emergency": {"risk_mod": -6, "heat_mod": 2, "desc": "Call in a fake emergency — redirects security"},
        "street_fight": {"risk_mod": -4, "heat_mod": 4, "desc": "Paid brawl outside — draws guards to the entrance"},
        "cyber_attack": {"risk_mod": -12, "heat_mod": 8, "desc": "DDoS the security network — total digital chaos"},
    }

    if distraction_type not in types:
        return f"Unknown type. Available: {', '.join(types.keys())}"

    d = types[distraction_type]
    heist = _get_heist(heist_id)
    heist["distractions"].append(distraction_type)
    heist["risk_level"] = max(5, heist["risk_level"] + d["risk_mod"])
    _save_heist_to_fs(heist)

    return f"Distraction set: {distraction_type}\n{d['desc']}\nRisk: {heist['risk_level']}%\n+{d['heat_mod']} heat when triggered."


@skill(
    pack="heist_planning",
    description="Execute the heist! Rolls against your risk level. Lower risk = better odds.",
    category=SkillCategory.GAME,
    cooldown=600.0,
    cost=5.0,
    tags=["heist", "execute", "action"],
    prerequisites=["case_target", "plan_entry"],
)
def execute_heist(heist_id: str) -> str:
    """Execute the planned heist.

    Args:
        heist_id: The heist plan ID.

    Returns:
        Full heist execution narrative and results.
    """
    if heist_id not in _ACTIVE_HEISTS:
        return f"No heist plan found: {heist_id}"

    heist = _get_heist(heist_id)
    if not heist["entry_plan"]:
        return "No entry plan! Use plan_entry first."

    risk = heist["risk_level"]
    roll = random.randint(1, 100)
    success = roll > risk

    # Calculate rewards based on risk and crew
    base_reward = random.randint(1000, 5000)
    crew_cut = sum(s.get("cost", 0) for s in heist["specialists"]) // 2

    try:
        from engine.world.player_state import get_player_state
        player = get_player_state()
    except Exception:
        player = None

    if success:
        net_reward = base_reward - crew_cut
        heat_gain = 5 + len(heist["distractions"]) * 3

        if player:
            player.earn_credits(max(0, net_reward), f"Heist: {heist['target']}")
            player.heat = min(100, getattr(player, "heat", 0) + heat_gain)

        heist["status"] = "success"
        _save_heist_to_fs(heist)

        logger.info("[HeistPlanning] Heist succeeded (operation=execute, heist=%s, reward=%d)", heist_id, net_reward)
        return (
            f"HEIST SUCCESSFUL!\n"
            f"Target: {heist['target']}\n"
            f"Risk was: {risk}% | Roll: {roll}\n"
            f"Gross take: {base_reward} credits\n"
            f"Crew cut: {crew_cut} credits\n"
            f"Net profit: {max(0, net_reward)} credits\n"
            f"Heat gained: +{heat_gain}\n"
            f"Specialists used: {len(heist['specialists'])}\n"
            f"Tools used: {', '.join(heist['tools']) or 'none'}"
        )
    else:
        heat_gain = 15 + len(heist["distractions"]) * 5

        if player:
            player.heat = min(100, getattr(player, "heat", 0) + heat_gain)
            # Lose some credits from failed gear
            lost = sum(100 for _ in heist["tools"])
            if lost and getattr(player, "credits", 0) >= lost:
                player.spend_credits(lost, f"Failed heist losses: {heist['target']}")

        heist["status"] = "failed"
        _save_heist_to_fs(heist)

        logger.info("[HeistPlanning] Heist FAILED (operation=execute, heist=%s, risk=%d, roll=%d)", heist_id, risk, roll)
        return (
            f"HEIST FAILED.\n"
            f"Target: {heist['target']}\n"
            f"Risk was: {risk}% | Roll: {roll} (needed > {risk})\n"
            f"Heat gained: +{heat_gain}\n"
            f"Equipment lost. Crew scattered.\n"
            f"The target knows someone tried. They'll be ready next time."
        )


# ──── Co-Op Squad Skills ────────────────────────────────────────────────
# v1.52.0 [2026-03-26] — Multiplayer squad formation for co-op heists

@skill(
    pack="heist_planning",
    description=(
        "Form a heist squad for co-op play. Creates a squad that other "
        "players can join. Requires 2-4 players, each choosing a role "
        "(hacker, muscle, talker, driver, demo, recon)."
    ),
    category=SkillCategory.GAME,
    cooldown=60.0,
    cost=1.0,
    tags=["heist", "squad", "multiplayer", "co-op"],
)
def form_heist_squad(squad_name: str, player_id: str = "player") -> str:
    """Form a new heist squad for co-op play.

    Args:
        squad_name: Name for the squad.
        player_id: ID of the player creating the squad.

    Returns:
        Squad ID and join instructions.
    """
    try:
        from engine.multiplayer.squad import get_squad_manager
        mgr = get_squad_manager()
        squad = mgr.create_squad(player_id, squad_name, scene="heist")
        return (
            f"Squad formed: {squad.squad_id}\n"
            f"Leader: {squad_name}\n"
            f"Share this code with others to join: {squad.squad_id}\n"
            f"Roles available: hacker, muscle, talker, driver, demo, recon\n"
            f"Waiting for members (1/{squad.max_members})..."
        )
    except ValueError as exc:
        return f"Cannot form squad: {exc}"
    except Exception as exc:
        return f"Squad creation failed: {exc}"


@skill(
    pack="heist_planning",
    description=(
        "Invite another player to join your heist squad. They'll receive "
        "a message with the squad code to join."
    ),
    category=SkillCategory.GAME,
    cooldown=15.0,
    cost=0.5,
    tags=["heist", "squad", "invite", "multiplayer"],
)
def invite_to_squad(
    target_player: str,
    player_id: str = "player",
) -> str:
    """Invite a player to your squad.

    Args:
        target_player: Player ID or name to invite.
        player_id: Your player ID.

    Returns:
        Invitation result.
    """
    try:
        from engine.multiplayer.squad import get_squad_manager
        mgr = get_squad_manager()
        squad = mgr.get_player_squad(player_id)
        if not squad:
            return "You're not in a squad. Use form_heist_squad first."

        # Send invitation via messaging system
        try:
            from engine.multiplayer.messaging import get_message_store
            store = get_message_store()
            store.send_message(
                sender_id=player_id,
                receiver_id=target_player,
                content=f"You're invited to join heist squad: {squad.squad_id}",
                thread_id=f"squad_invite_{squad.squad_id}",
            )
        except Exception:
            pass  # Messaging optional

        return f"Invitation sent to {target_player} for squad {squad.squad_id}"
    except Exception as exc:
        return f"Invite failed: {exc}"


@skill(
    pack="heist_planning",
    description=(
        "Vote to advance the heist to the next phase. In co-op mode, "
        "majority vote is required to proceed."
    ),
    category=SkillCategory.GAME,
    cooldown=10.0,
    cost=0.5,
    tags=["heist", "squad", "vote", "phase"],
)
def vote_phase_advance(
    player_id: str = "player",
) -> str:
    """Cast a vote to advance the heist phase.

    Args:
        player_id: Your player ID.

    Returns:
        Current vote tally and whether the phase advances.
    """
    try:
        from engine.multiplayer.squad import get_squad_manager
        mgr = get_squad_manager()
        squad = mgr.get_player_squad(player_id)
        if not squad:
            return "You're not in a squad."

        # Track votes in-memory on the squad (simple approach)
        if not hasattr(squad, "_phase_votes"):
            squad._phase_votes = set()
        squad._phase_votes.add(player_id)

        total = squad.member_count
        votes = len(squad._phase_votes)
        needed = (total // 2) + 1  # Majority

        if votes >= needed:
            squad._phase_votes = set()  # Reset for next phase
            return f"PHASE ADVANCE! Votes: {votes}/{total} (majority reached). Moving to next phase."
        else:
            return f"Vote cast. {votes}/{total} votes ({needed} needed for majority)."
    except Exception as exc:
        return f"Vote failed: {exc}"
