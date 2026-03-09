"""Territory skills — faction control, crew HQ, district info."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="territory",
    description="View faction control percentages for a district",
    category="GAME",
)
def view_territory(district: Optional[str] = None) -> str:
    """Display faction control map for one district or the entire city.

    Args:
        district: District name (e.g. DOWNTOWN, COMBAT_ZONE). Omit for full city.
    """
    from engine.world.territory import get_territory_manager

    mgr = get_territory_manager()

    if district:
        d = district.upper().replace(" ", "_")
        control = mgr.get_district_control(d)
        if not control:
            return f"❌ Unknown district '{district}'."
        spec = mgr.get_district_specialization(d)
        lines = [f"🏙️ {d} — {spec.get('description', '')}"]
        lines.append(f"  Specialization: {spec.get('type', 'none')}")
        for faction, pct in sorted(control.items(), key=lambda x: -x[1]):
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(f"  {faction:.<15} {bar} {pct:.1f}%")
        return "\n".join(lines)

    return mgr.get_territory_summary()


@skill(
    pack="territory",
    description="Attempt to capture territory in a district for your faction",
    category="GAME",
    cost=3.0,
    cooldown=30.0,
)
def capture_point(
    district: str,
    faction: str,
    strength: float = 5.0,
) -> str:
    """Attempt to increase faction control in a district.

    Args:
        district: Target district.
        faction: Faction capturing (OmniCorp, NeoTech, BlackMarket, Ghost_Net, SynthSec, DeepState).
        strength: Control shift percentage (1.0–15.0).
    """
    from engine.world.territory import get_territory_manager

    mgr = get_territory_manager()
    strength = max(1.0, min(15.0, strength))

    try:
        event = mgr.shift_control(
            district.upper().replace(" ", "_"),
            faction,
            strength,
            reason="player_capture",
        )
    except (KeyError, ValueError) as e:
        return f"❌ {e}"

    lines = [f"⚔️ Territory operation in {district}:"]
    lines.append(f"  {faction} gained {event.delta:+.1f}% control")

    if event.triggered_war:
        lines.append(f"  🔥 FACTION WAR TRIGGERED! {faction} vs defenders!")

    new_control = mgr.get_district_control(district.upper().replace(" ", "_"))
    top = sorted(new_control.items(), key=lambda x: -x[1])[:3]
    for f, p in top:
        lines.append(f"  {f}: {p:.1f}%")

    return "\n".join(lines)


@skill(
    pack="territory",
    description="View crew headquarters status and room details",
    category="GAME",
)
def crew_hq_status(crew_id: str = "player_crew") -> str:
    """Display the player's crew HQ: location, rooms, levels, bonuses.

    Args:
        crew_id: Crew identifier (default player_crew).
    """
    from engine.world.territory import get_territory_manager, HQ_ROOM_TYPES

    mgr = get_territory_manager()
    hq = mgr.get_hq(crew_id)

    if not hq:
        return "🏚️ No crew HQ established yet. Use 'establish_hq' to set one up."

    data = hq.to_dict()
    lines = [f"🏠 Crew HQ — {hq.district} District"]
    lines.append(f"  Crew: {hq.crew_id}")

    rooms = hq.rooms
    for room_name, room in rooms.items():
        max_level = HQ_ROOM_TYPES.get(room_name, {}).get("max_level", 3)
        desc = HQ_ROOM_TYPES.get(room_name, {}).get("description", "")
        bonus = room.get_bonus()
        status = "🟢" if room.level > 0 else "⬛"
        lines.append(f"  {status} {room_name}: Level {room.level}/{max_level}")
        if bonus:
            bonus_str = ", ".join(f"{k}={v}" for k, v in bonus.items())
            lines.append(f"      Bonus: {bonus_str}")

    total_bonuses = hq.get_all_bonuses()
    if total_bonuses:
        lines.append(f"  Total bonuses: {total_bonuses}")

    return "\n".join(lines)


@skill(
    pack="territory",
    description="Establish a crew HQ in a district",
    category="GAME",
    cost=5.0,
)
def establish_hq(district: str, crew_id: str = "player_crew") -> str:
    """Set up a crew headquarters in the specified district.

    Args:
        district: District to establish HQ in.
        crew_id: Crew identifier (default player_crew).
    """
    from engine.world.territory import get_territory_manager, DISTRICT_NAMES

    mgr = get_territory_manager()
    d = district.upper().replace(" ", "_")
    if d not in DISTRICT_NAMES:
        return f"❌ Unknown district '{district}'. Valid: {', '.join(DISTRICT_NAMES)}"

    hq = mgr.establish_hq(d, crew_id)
    room_names = list(hq.rooms.keys()) if hq.rooms else ["(none yet — build rooms!)"]
    return (
        f"🏠 Crew HQ established in {d}!\n"
        f"  Rooms: {', '.join(room_names)}\n"
        f"  Build rooms with 'upgrade_hq_room'."
    )


@skill(
    pack="territory",
    description="Upgrade a room in your crew HQ",
    category="GAME",
    cost=3.0,
)
def upgrade_hq_room(room: str, crew_id: str = "player_crew") -> str:
    """Upgrade a specific room in the crew HQ.

    Args:
        room: Room to upgrade (barracks, armory, lab, vault, comms).
        crew_id: Crew identifier (default player_crew).
    """
    from engine.world.territory import get_territory_manager, HQ_ROOM_TYPES

    mgr = get_territory_manager()
    hq = mgr.get_hq(crew_id)
    if not hq:
        return "❌ No HQ established. Use 'establish_hq' first."

    room_lower = room.lower()
    if room_lower not in HQ_ROOM_TYPES:
        return f"❌ Unknown room type '{room}'. Valid: {', '.join(HQ_ROOM_TYPES.keys())}"

    if room_lower not in hq.rooms:
        built = mgr.build_room(crew_id, room_lower)
        if built:
            return f"🔧 Built {room_lower} at level 1!"
        return f"❌ Failed to build {room_lower}."

    upgraded = mgr.upgrade_room(crew_id, room_lower)
    if upgraded:
        new_level = hq.rooms[room_lower].level
        bonus = hq.rooms[room_lower].get_bonus()
        bonus_str = ", ".join(f"{k}={v}" for k, v in bonus.items()) if bonus else "none"
        return (
            f"🔧 Upgraded {room_lower} to level {new_level}!\n"
            f"  New bonus: {bonus_str}"
        )
    return f"❌ {room_lower} is already at max level."


@skill(
    pack="territory",
    description="View faction rankings across the entire city",
    category="GAME",
)
def faction_ranking() -> str:
    """Show city-wide faction power rankings."""
    from engine.world.territory import get_territory_manager

    mgr = get_territory_manager()
    rankings = mgr.get_faction_ranking()

    if not rankings:
        return "⚠️ No territory data available."

    lines = ["🏆 City-Wide Faction Power Rankings:"]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]
    for i, (faction, total_pct) in enumerate(rankings):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        bar = "█" * int(total_pct / 3) + "░" * max(0, 20 - int(total_pct / 3))
        lines.append(f"  {medal} {faction:.<15} {bar} {total_pct:.1f}%")

    return "\n".join(lines)


@skill(
    pack="territory",
    description="Simulate one tick of faction AI territorial movement",
    category="SYSTEM",
    cost=2.0,
    cooldown=60.0,
)
def faction_tick() -> str:
    """Run one cycle of autonomous faction territorial expansion/contraction."""
    from engine.world.territory import get_territory_manager

    mgr = get_territory_manager()
    events = mgr.simulate_faction_tick()

    if not events:
        return "🔄 Faction tick: no significant changes."

    lines = ["🔄 Faction tick results:"]
    for evt in events[:10]:
        lines.append(f"  • {evt}")
    if len(events) > 10:
        lines.append(f"  ... and {len(events) - 10} more events")

    return "\n".join(lines)
