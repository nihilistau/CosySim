"""
Realm Skills — MCP skill functions for The Realm LitRPG scene.

Exposes inventory management, skill checks, director control, murder mystery
actions, and fourth-wall mechanics as @skill-decorated functions callable
by LMS agents via tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_realm_scene():
    """Look up the running Realm scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("realm")


# ── Inventory ─────────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "inventory"],
    category=SkillCategory.GAME,
    description="List the player's current inventory in The Realm.",
)
def realm_inventory() -> str:
    """Return a formatted list of all items the player is carrying."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    items = scene.state.inventory
    if not items:
        return "Inventory is empty."
    lines = [f"🎒 Inventory ({len(items)} items):"]
    for i in items:
        lines.append(f"  • {i['name']} ({i.get('type', '?')}) — {i.get('description', '')[:60]}")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "inventory"],
    category=SkillCategory.GAME,
    description="Add an item to the player's inventory.",
)
def realm_add_item(name: str, item_type: str = "misc", description: str = "") -> str:
    """Give the player a new item."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    item = {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "type": item_type,
        "description": description,
    }
    scene.state.add_item(item)
    return f"Added '{name}' to inventory."


@skill(
    pack="realm",
    tags=["game", "inventory"],
    category=SkillCategory.GAME,
    description="Remove an item from the player's inventory by its ID.",
)
def realm_remove_item(item_id: str) -> str:
    """Remove an item from the player's inventory."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    removed = scene.state.remove_item(item_id)
    if removed:
        return f"Removed '{removed['name']}' from inventory."
    return f"Item '{item_id}' not found in inventory."


# ── Stats & Skills ────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Get the player's current stats in The Realm.",
)
def realm_stats() -> str:
    """Return the player's stats as a formatted summary."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    s = scene.state.player_stats
    return (
        f"HP: {s['hp']}/{s['max_hp']} | MP: {s['mp']}/{s['max_mp']}\n"
        f"Level {s['level']} ({s['xp']}/{s['xp_next']} XP)\n"
        f"STR: {s['strength']} AGI: {s['agility']} INT: {s['intellect']} "
        f"CHA: {s['charisma']} LCK: {s['luck']}"
    )


@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Perform a skill check for the player (d20 + stat bonus vs DC).",
)
def realm_skill_check(skill_name: str, dc_modifier: int = 0) -> str:
    """Roll a skill check and return the result."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.skill_check(skill_name, dc_modifier)
    if not result.get("success") and result.get("reason") == "unknown skill":
        return f"Unknown skill '{skill_name}'. Available: persuasion, lockpicking, arcana, athletics, stealth, intimidation, deception, investigation, survival."
    outcome = "SUCCESS ✅" if result["success"] else "FAILURE ❌"
    return (
        f"Skill Check: {skill_name} — {outcome}\n"
        f"Roll: {result['roll']} + {result['bonus']} ({result['stat']} {result['stat_value']}) = {result['total']} vs DC {result['dc']}"
    )


@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Deal damage to or heal the player.",
)
def realm_adjust_hp(amount: int) -> str:
    """Positive heals, negative damages. Returns new HP and death status."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    if amount >= 0:
        hp = scene.state.heal(amount)
        return f"Healed {amount} HP. Current: {hp}/{scene.state.player_stats['max_hp']}"
    hp, dead = scene.state.take_damage(abs(amount))
    result = f"Took {abs(amount)} damage. Current: {hp}/{scene.state.player_stats['max_hp']}"
    if dead:
        result += " — PLAYER DIED 💀"
    return result


# ── Director Control ──────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "narrative"],
    category=SkillCategory.NARRATIVE,
    description="Get the Director's current personality and patience level.",
)
def realm_director_status() -> str:
    """Return Director personality, patience meter, and mutiny status."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    st = scene.state
    mutiny = "ACTIVE ⚡" if st.is_mutiny_active() else "inactive"
    return (
        f"Director: {st.director_personality} | Patience: {st.director_patience:.0f}/100\n"
        f"Mutiny: {mutiny} | Turn: {st.turn_number}"
    )


@skill(
    pack="realm",
    tags=["game", "narrative"],
    category=SkillCategory.NARRATIVE,
    description="The Assistant steals a UI element and adds it to the player's inventory (fourth-wall break).",
)
def realm_fourth_wall_steal(item_name: str) -> str:
    """The Assistant rips an item from the game interface."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    item = scene.state.assistant_steal(item_name)
    return f"🕳️ FOURTH WALL BREACH — Stole '{item_name}' from the UI! Added as [{item['name']}]."


@skill(
    pack="realm",
    tags=["game", "narrative"],
    category=SkillCategory.NARRATIVE,
    description="Sacrifice 10 max HP to force the Director to start a fresh conversation context.",
    cooldown=30.0,
)
def realm_desperation_dice() -> str:
    """Desperation dice — sacrifice permanent HP to reset Director context."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.desperation_dice()
    if result["success"]:
        scene._director_conv_id = None
        return f"🎲 DESPERATION DICE — Sacrificed 10 max HP! New max: {result['new_max_hp']}. Director context reset."
    return f"Cannot sacrifice — {result['reason']}"


# ── Murder Mystery ────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "narrative", "murder_mystery"],
    category=SkillCategory.GAME,
    description="Get the current state of the murder mystery investigation.",
)
def realm_murder_status() -> str:
    """Return murder mystery phase, clues, accusations remaining."""
    scene = _get_realm_scene()
    if not scene or not scene.state or not scene.state.murder:
        return "No active murder mystery."
    m = scene.state.murder
    return (
        f"Phase: {m.phase} | Time remaining: {m.phase_time_remaining():.0f}s\n"
        f"Clues found: {len(m.clues_found)} | Interrogations: {len(m.interrogations)}\n"
        f"Accusations remaining: {m.accusations_remaining} | Resolved: {m.resolved}"
    )


@skill(
    pack="realm",
    tags=["game", "narrative", "murder_mystery"],
    category=SkillCategory.GAME,
    description="Make an accusation in the murder mystery (suspect_id, weapon, room).",
)
def realm_murder_accuse(suspect_id: str, weapon: str, room: str) -> str:
    """Accuse a suspect with a weapon and room. Returns verdict."""
    scene = _get_realm_scene()
    if not scene or not scene.state or not scene.state.murder:
        return "No active murder mystery."
    result = scene.state.murder.accuse(suspect_id, weapon, room)
    if not result.get("allowed"):
        return f"Cannot accuse: {result.get('reason', 'unknown')}"
    parts = []
    if result["correct_suspect"]:
        parts.append("✅ Correct suspect")
    else:
        parts.append("❌ Wrong suspect")
    if result["correct_weapon"]:
        parts.append("✅ Correct weapon")
    else:
        parts.append("❌ Wrong weapon")
    if result["correct_room"]:
        parts.append("✅ Correct room")
    else:
        parts.append("❌ Wrong room")
    verdict = "🎉 CASE SOLVED!" if result["won"] else f"Wrong! {result['remaining']} attempts left."
    return f"Accusation: {' | '.join(parts)}\n{verdict}"


# ── Combat ────────────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "combat"],
    category=SkillCategory.GAME,
    description="Start a combat encounter with an enemy in The Realm.",
    cooldown=5,
)
def realm_start_combat(enemy: str = "") -> str:
    """Start a combat encounter. Optionally specify enemy type."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.start_combat(enemy or None)
    if "error" in result:
        return result["error"]
    return f"⚔️ COMBAT! A {result['enemy_name']} appears! HP: {result['enemy_hp']}/{result['enemy_max_hp']}"


@skill(
    pack="realm",
    tags=["game", "combat"],
    category=SkillCategory.GAME,
    description="Attack the current enemy in combat.",
    cooldown=2,
)
def realm_combat_attack() -> str:
    """Attack the enemy in the current combat encounter."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.combat_attack()
    if "error" in result:
        return result["error"]
    lines = []
    if result.get("miss"):
        lines.append(f"❌ MISS! You swing wide with {result['weapon']}.")
    elif result.get("crit"):
        lines.append(f"💥 CRITICAL HIT with {result['weapon']}! {result['player_damage']} damage!")
    else:
        lines.append(f"🗡️ Hit with {result['weapon']} for {result['player_damage']} damage.")
    if result.get("enemy_damage", 0) > 0:
        lines.append(f"Enemy strikes back for {result['enemy_damage']} damage!")
    lines.append(f"Enemy HP: {result['enemy_hp']} | Your HP: {result['player_hp']}")
    if result.get("defeated"):
        lines.append(f"🏆 VICTORY! +{result.get('xp_gained', 0)} XP")
        if result.get("loot"):
            lines.append(f"💰 Loot: {result['loot']['name']}")
        if result.get("quest_updates"):
            for qu in result["quest_updates"]:
                if qu.get("completed"):
                    lines.append(f"🎯 Quest '{qu['quest']}' COMPLETE!")
                else:
                    lines.append(f"📋 Quest progress: {qu['progress']}/{qu['target']}")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "combat"],
    category=SkillCategory.GAME,
    description="Attempt to flee from combat.",
    cooldown=3,
)
def realm_combat_flee() -> str:
    """Try to run from the current combat encounter."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.combat_flee()
    if "error" in result:
        return result["error"]
    if result.get("fled"):
        return "🏃 You escaped! The enemy fades behind you."
    return f"❌ Failed to flee! Enemy hits for {result.get('enemy_damage', 0)} damage. HP: {result.get('player_hp', '?')}"


@skill(
    pack="realm",
    tags=["game", "combat"],
    category=SkillCategory.GAME,
    description="Defend in combat — halves incoming damage this round.",
    cooldown=2,
)
def realm_combat_defend() -> str:
    """Raise your guard to reduce incoming damage."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.combat_defend()
    if "error" in result:
        return result["error"]
    lines = [f"🛡️ DEFEND! You brace against the {result.get('enemy_name', 'enemy')}."]
    if result.get("enemy_damage", 0) > 0:
        lines.append(f"Reduced hit: {result['enemy_damage']} damage taken.")
    else:
        lines.append("The enemy's attack glances off!")
    lines.append(f"HP: {result['player_hp']} | Enemy HP: {result['enemy_hp']}")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "combat"],
    category=SkillCategory.GAME,
    description="Use a consumable item during combat (health potion, fire scroll, etc.).",
    cooldown=2,
)
def realm_combat_use_item(item_id: str = "") -> str:
    """Use a consumable item mid-combat."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    if not item_id:
        return "Provide an item_id. Use realm_inventory() to see items."
    result = scene.state.combat_use_item(item_id)
    if "error" in result:
        return result["error"]
    lines = [f"🧪 Used {result.get('item_name', 'item')} in combat!"]
    if result.get("healed"):
        lines.append(f"  ❤️ Healed {result['healed']} HP")
    if result.get("restored_mp"):
        lines.append(f"  💙 Restored {result['restored_mp']} MP")
    if result.get("item_damage"):
        lines.append(f"  💥 Dealt {result['item_damage']} damage to enemy")
    if result.get("enemy_damage", 0) > 0:
        lines.append(f"  Enemy strikes back for {result['enemy_damage']} damage")
    lines.append(f"HP: {result.get('player_hp', '?')} | Enemy HP: {result.get('enemy_hp', '?')}")
    if result.get("defeated"):
        lines.append(f"🏆 VICTORY! +{result.get('xp_gained', 0)} XP")
    return "\n".join(lines)


# ── Location ──────────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "exploration"],
    category=SkillCategory.GAME,
    description="View your current location and connected destinations.",
    cooldown=1,
)
def realm_location() -> str:
    """Show current location info and connections."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    info = scene.state.get_location_info()
    lines = [f"📍 {info['name']}", info['description'], "— Connections:"]
    for c in info.get("connections_info", []):
        lines.append(f"  → {c['name']} ({c['key']})")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "exploration"],
    category=SkillCategory.GAME,
    description="Travel to a connected location. May trigger random encounters.",
    cooldown=3,
)
def realm_move(destination: str = "") -> str:
    """Move to a connected location by its key."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    if not destination:
        return "Provide a destination key. Use realm_location() to see connections."
    result = scene.state.move_to_location(destination)
    if "error" in result:
        return result["error"]
    lines = [f"🚶 Traveled to {result['to_name']}.", result["description"]]
    if result.get("encounter"):
        enc = result["encounter"]
        lines.append(f"⚔️ AMBUSH! A {enc.get('enemy_name', 'creature')} blocks your path! "
                     f"HP: {enc.get('enemy_hp', '?')}/{enc.get('enemy_max_hp', '?')}")
    if result.get("quest_updates"):
        for qu in result["quest_updates"]:
            if qu.get("completed"):
                lines.append(f"🎯 Quest '{qu['quest']}' COMPLETE!")
            else:
                lines.append(f"📋 Quest progress: {qu['progress']}/{qu['target']}")
    lines.append("— Connections:")
    for c in result.get("connections", []):
        lines.append(f"  → {c['name']} ({c['key']})")
    return "\n".join(lines)


# ── Quests ────────────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "quest"],
    category=SkillCategory.GAME,
    description="View available, active, and completed quests in The Realm.",
    cooldown=2,
)
def realm_quests() -> str:
    """View quest status: available, active, and completed."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    avail = scene.state.get_available_quests()
    active = scene.state.active_quests
    completed = scene.state.completed_quests
    lines = ["📜 QUEST LOG"]
    if active:
        lines.append("— Active:")
        for q in active:
            lines.append(f"  [{q['progress']}/{q['target']}] {q['title']}: {q['objective']}")
    if avail:
        lines.append("— Available:")
        for q in avail:
            lines.append(f"  🆕 {q['title']}: {q['description']}")
    if completed:
        lines.append(f"— Completed: {', '.join(completed)}")
    if not active and not avail:
        lines.append("No quests available.")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "quest"],
    category=SkillCategory.GAME,
    description="Accept a quest by its key name.",
    cooldown=3,
)
def realm_accept_quest(quest_key: str = "") -> str:
    """Accept a quest. Provide the quest key (e.g., 'rats_in_cellar')."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    if not quest_key:
        return "Provide a quest key. Use realm_quests() to see available quests."
    result = scene.state.accept_quest(quest_key)
    if "error" in result:
        return result["error"]
    q = result["quest"]
    return f"✅ Quest accepted: '{q['title']}' — {q['objective']}"


# ── Advanced Mechanics (v0.50b) ────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="View skill mastery progress. Skills improve with use.",
)
def realm_skill_mastery() -> str:
    """Show all skill proficiencies and mastery progress."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    st = scene.state
    # Track skill uses if not already tracked
    if not hasattr(st, 'skill_uses'):
        st.skill_uses = {s: 0 for s in st.skills}

    lines = ["📚 SKILL MASTERY:"]
    for skill_name, base_mod in st.skills.items():
        uses = st.skill_uses.get(skill_name, 0)
        mastery_bonus = uses // 10  # +1 per 10 uses
        total = base_mod + mastery_bonus
        rank = (
            "Novice" if uses < 10 else
            "Apprentice" if uses < 25 else
            "Journeyman" if uses < 50 else
            "Expert" if uses < 100 else
            "Master"
        )
        lines.append(f"  {skill_name}: +{total} ({rank}, {uses} uses, +{mastery_bonus} mastery)")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "social", "npc"],
    category=SkillCategory.SOCIAL,
    description="Talk to an NPC to build relationship, gather clues, or trade.",
    cooldown=5,
)
def realm_npc_talk(npc_id: str = "", topic: str = "greeting") -> str:
    """Interact with NPCs. Topics: greeting, rumors, trade, interrogate."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    st = scene.state

    # Initialize NPC relationships if needed
    if not hasattr(st, 'npc_relationships'):
        st.npc_relationships = {}

    # Get NPCs at current location
    available_npcs = []
    if st.murder and hasattr(st.murder, 'suspects'):
        available_npcs = list(st.murder.suspects.keys())
    if not npc_id:
        if available_npcs:
            return f"Who do you want to talk to? Available: {', '.join(available_npcs)}"
        return "No NPCs nearby to talk to."

    # Track relationship
    if npc_id not in st.npc_relationships:
        st.npc_relationships[npc_id] = {"trust": 0, "interactions": 0, "known_topics": []}
    rel = st.npc_relationships[npc_id]
    rel["interactions"] += 1

    if topic == "greeting":
        rel["trust"] = min(100, rel["trust"] + 5)
        return (
            f"🗣️ You greet {npc_id}. They warm up to you.\n"
            f"Trust: {rel['trust']}/100 | Interactions: {rel['interactions']}"
        )
    elif topic == "rumors":
        if rel["trust"] < 20:
            return f"{npc_id} doesn't trust you enough to share rumors. Trust: {rel['trust']}/100"
        rel["trust"] = min(100, rel["trust"] + 2)
        import random
        rumors = [
            "There's been strange sounds from the dark forest at night...",
            "The merchant guild is hiding something in the castle vault.",
            "A traveling scholar was seen near the ancient ruins.",
            "The tavern keeper knows more than they let on.",
            "Something valuable is hidden in the temple's lower chambers.",
        ]
        rumor = random.choice(rumors)
        return f"🗣️ {npc_id} leans in: \"{rumor}\""
    elif topic == "trade":
        return f"🗣️ {npc_id} shows their wares. (Use realm_add_item to acquire items)"
    elif topic == "interrogate":
        if not st.murder:
            return "No murder mystery active — interrogation unavailable."
        if rel["trust"] < 30:
            return f"{npc_id} clams up. Build trust first. Trust: {rel['trust']}/100"
        rel["trust"] = max(0, rel["trust"] - 5)
        # Check if NPC is a murder suspect
        if npc_id in getattr(st.murder, 'suspects', {}):
            suspect = st.murder.suspects[npc_id]
            clue = suspect.get("alibi", "No alibi given.")
            if npc_id not in [c.get("source") for c in st.murder.clues_found]:
                st.murder.clues_found.append({"type": "testimony", "source": npc_id, "detail": clue})
            return (
                f"🔍 Interrogation of {npc_id}:\n"
                f"\"{clue}\"\n"
                f"Trust: {rel['trust']}/100 (interrogation lowers trust)"
            )
        return f"🔍 {npc_id} has no relevant information about the case."
    return "Topics: greeting, rumors, trade, interrogate."


@skill(
    pack="realm",
    tags=["game", "exploration"],
    category=SkillCategory.GAME,
    description="Check the time remaining and urgency of the current situation.",
)
def realm_time_check() -> str:
    """Show time pressure, turn count, and urgency warnings."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    st = scene.state

    lines = [f"⏰ Turn {st.turn_number}"]

    # Director patience
    lines.append(f"Director patience: {st.director_patience:.0f}/100 ({st.director_personality})")
    if st.director_patience < 30:
        lines.append("  ⚠️ Director is getting impatient! Bad things may happen soon...")
    elif st.director_patience < 60:
        lines.append("  ⏳ Director is watching closely...")

    # Murder mystery time
    if st.murder and hasattr(st.murder, 'phase_time_remaining'):
        remaining = st.murder.phase_time_remaining()
        lines.append(f"Mystery time: {remaining:.0f}s remaining in phase '{st.murder.phase}'")
        if remaining < 60:
            lines.append("  🚨 TIME RUNNING OUT!")

    # Quest deadlines (if any active)
    if st.active_quests:
        lines.append(f"Active quests: {len(st.active_quests)}")

    # Mutiny check
    if st.is_mutiny_active():
        lines.append("⚡ MUTINY ACTIVE — The Director has gone rogue!")

    return "\n".join(lines)


# ── Dark Renaissance v0.68 — Shattered Throne Skills ──────────────────────────

@skill(
    pack="realm",
    tags=["game", "state", "narrative"],
    category=SkillCategory.GAME,
    description="Get current story arc progress, player stats, active quest, and world events.",
)
def realm_state() -> str:
    """Return full game state for THE SHATTERED THRONE."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "THE SHATTERED THRONE — no active game."
    st = scene.state
    s = st.player_stats
    arc_id = getattr(st, "active_arc", None)
    arc_label = arc_id.replace("_", " ").title() if arc_id else "None"
    sanity = getattr(st, "sanity", 100)
    active_quest_title = st.active_quests[0]["title"] if st.active_quests else "None"
    return (
        f"⚔️ THE SHATTERED THRONE — Turn {st.turn_number}\n"
        f"Arc: {arc_label} | Director: {st.director_personality} "
        f"(patience {st.director_patience:.0f}/100)\n"
        f"HP: {s['hp']}/{s['max_hp']} | MP: {s['mp']}/{s['max_mp']} | "
        f"Sanity: {sanity}/100 | XP: {s['xp']}/{s['xp_next']}\n"
        f"Level {s['level']} | Gold: {s.get('gold', 0)} | "
        f"Location: {st.current_location}\n"
        f"Active Quest: {active_quest_title}\n"
        f"Inventory: {len(st.inventory)} item(s)"
    )


@skill(
    pack="realm",
    tags=["game", "narrative", "arc"],
    category=SkillCategory.NARRATIVE,
    description="Get available dark story arcs to begin in THE SHATTERED THRONE.",
)
def get_story_arcs() -> str:
    """Return the five dark story arcs available in the Shattered Throne."""
    arcs = [
        ("corruption",         "☠️", "The Corruptor's Bargain",
         "A dark entity offers impossible power — at the cost of your soul."),
        ("forbidden_magic",    "📖", "Forbidden Tome",
         "A cursed grimoire promises omniscience. Every spell costs sanity."),
        ("betrayal",           "🗡️", "The Knife in the Dark",
         "Your closest ally is the realm's most dangerous traitor."),
        ("lovecraftian",       "🦑", "What Stirs Beneath",
         "Something ancient and unspeakable stirs beneath the shattered throne."),
        ("political_intrigue", "👑", "Game of Shards",
         "Four factions war for the throne's fragments. Every alliance is a lie."),
    ]
    lines = ["🌑 DARK STORY ARCS — THE SHATTERED THRONE:"]
    for arc_id, icon, title, desc in arcs:
        lines.append(f"  {icon} [{arc_id}] {title}: {desc}")
    lines.append("\nUse start_story_arc(arc_id) to begin an arc.")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "narrative", "arc"],
    category=SkillCategory.NARRATIVE,
    description=(
        "Start a dark story arc in THE SHATTERED THRONE "
        "(arc_id: corruption, forbidden_magic, betrayal, lovecraftian, political_intrigue)."
    ),
    cooldown=10.0,
)
def start_story_arc(arc_id: str) -> str:
    """Begin a dark story arc. The Director narrates the arc opening."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Shattered Throne game."
    valid = {"corruption", "forbidden_magic", "betrayal", "lovecraftian", "political_intrigue"}
    if arc_id not in valid:
        return f"Unknown arc '{arc_id}'. Valid arcs: {', '.join(sorted(valid))}"
    scene.state.active_arc = arc_id  # type: ignore[attr-defined]
    return f"🌑 Arc '{arc_id}' activated. The Director will narrate the opening on next turn."


@skill(
    pack="realm",
    tags=["game", "narrative", "choice"],
    category=SkillCategory.NARRATIVE,
    description="Make a narrative choice at a branching point in THE SHATTERED THRONE.",
)
def make_choice(choice_id: str, reason: str = "") -> str:
    """Select a story choice by ID. Optionally provide a reason for the choice."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Shattered Throne game."
    st = scene.state
    if st.ended:
        return "The game has ended. Start a new game to make choices."
    choice_match = next(
        (c for c in st.current_choices if c.get("id") == choice_id), None
    )
    if not choice_match:
        available = [f"{c['id']}: {c['text']}" for c in st.current_choices]
        return (
            f"Choice '{choice_id}' not found.\n"
            f"Available: {'; '.join(available) if available else 'No choices available'}"
        )
    reason_suffix = f" (Reason: {reason})" if reason else ""
    return f"✅ Choice '{choice_id}' selected: {choice_match['text']}{reason_suffix}"


@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Check player stats: HP, MP, XP, Sanity, Level, Gold.",
)
def player_stats() -> str:
    """Return player stats for THE SHATTERED THRONE including sanity."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Shattered Throne game."
    s = scene.state.player_stats
    sanity = getattr(scene.state, "sanity", 100)
    sanity_bar = "█" * (sanity // 10) + "░" * (10 - sanity // 10)
    sanity_status = (
        "SHATTERED 💔" if sanity < 20 else
        "Fraying 😰" if sanity < 40 else
        "Strained 😟" if sanity < 60 else
        "Stable 🧠" if sanity < 80 else
        "Clear ✨"
    )
    return (
        f"⚔️ PLAYER STATS — THE SHATTERED THRONE\n"
        f"HP:     {s['hp']:>3}/{s['max_hp']:<3}\n"
        f"MP:     {s['mp']:>3}/{s['max_mp']:<3}\n"
        f"Sanity: {sanity:>3}/100  [{sanity_bar}] {sanity_status}\n"
        f"Level:  {s['level']} ({s['xp']}/{s['xp_next']} XP)\n"
        f"Gold:   {s.get('gold', 0)}\n"
        f"STR: {s['strength']}  AGI: {s['agility']}  "
        f"INT: {s['intellect']}  CHA: {s['charisma']}  LCK: {s['luck']}"
    )
