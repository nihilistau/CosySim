"""Tavern scene MCP skills — agent-callable actions.

Each @skill is discoverable by LLM agents via the MCP skills server.
Skills modify TavernState and return a feedback string the agent can
incorporate into its response.

Showcases: @skill decorator, get_active_scene(), stat gating,
reputation checks, consequence scheduling, event emission,
MCPTimer usage, DialogSystem directives.
"""

from __future__ import annotations

from engine.skills.skill import SkillCategory, skill

from .tavern_state import DRINKS_MENU, NPC_PROFILES, TavernState


def _get_tavern():
    """Lazy-import to avoid circular deps."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("tavern")


def _get_state() -> TavernState | None:
    scene = _get_tavern()
    return getattr(scene, "tavern_state", None) if scene else None


# ── Status ──────────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "status", "info"],
    category=SkillCategory.SOCIAL,
    description="Get tavern status: atmosphere, NPCs present, gold, stats, quests.",
)
def tavern_status() -> str:
    state = _get_state()
    if not state:
        return "The tavern is closed."
    snap = state.to_snapshot()
    npcs = ", ".join(
        NPC_PROFILES[n]["name"] for n in snap["npcs_present"] if n in NPC_PROFILES
    )
    quests_active = [
        f"{q['title']} ({q['progress']}/{q['max']})"
        for q in snap["quests"].values() if q["status"] == "active"
    ]
    return (
        f"🍺 The Dragon's Flagon — Turn {snap['turn']}\n"
        f"Atmosphere: {snap['atmosphere']} | Heat: {snap['heat']}/100\n"
        f"Time: {snap['time_of_day']}\n"
        f"Gold: {snap['gold']}\n"
        f"NPCs present: {npcs}\n"
        f"Stats: {', '.join(f'{k}={v}' for k, v in snap['stats'].items())}\n"
        f"Active quests: {', '.join(quests_active) if quests_active else 'none'}\n"
        f"Dice game: {'active' if snap['dice_game_active'] else 'inactive'}"
    )


# ── Ordering Drinks ─────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "drink", "bar"],
    category=SkillCategory.SOCIAL,
    description="Order a drink from the bar. Drinks cost gold and affect stats.",
    cooldown=5,
)
def tavern_order_drink(drink_id: str = "ale") -> str:
    state = _get_state()
    if not state:
        return "The bar is closed."
    drink = next((d for d in DRINKS_MENU if d.id == drink_id), None)
    if not drink:
        menu = ", ".join(f"{d.id} ({d.price}g)" for d in DRINKS_MENU)
        return f"Unknown drink '{drink_id}'. Menu: {menu}"
    if not state.spend_gold(drink.price):
        return f"Not enough gold. {drink.name} costs {drink.price}g, you have {state.gold}g."
    changes = state.adjust_stats(**drink.effects)
    state.drinks_consumed.append(drink.id)
    state.adjust_heat(3)
    state.log_event(f"Player ordered {drink.name}.", "drink")

    # Schedule consequence: warmth fades after 3 turns
    scene = _get_tavern()
    if scene:
        try:
            from engine.mcp.framework import get_framework
            get_framework().schedule_consequence(
                scene_id="tavern", character_id="player",
                consequence_type="stat_adjust",
                params={"warmth": -5},
                trigger_after_turns=3,
                description=f"The warmth from {drink.name} fades.",
            )
        except Exception:
            pass

    fx = ", ".join(f"{k}{'+' if v > 0 else ''}{v}" for k, v in changes.items() if v)
    return f"🍺 {drink.name} — {drink.description}\nCost: {drink.price}g | Effects: {fx}"


# ── Reputation & Interaction ────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "npc", "reputation"],
    category=SkillCategory.SOCIAL,
    description="Check reputation with an NPC. Shows attitude and unlocked features.",
)
def tavern_check_reputation(npc_id: str = "greta") -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."
    if npc_id not in NPC_PROFILES:
        return f"Unknown NPC. Available: {', '.join(NPC_PROFILES.keys())}"
    prof = NPC_PROFILES[npc_id]
    rep = state.reputation.get(npc_id, 50)
    tier = state.get_reputation_tier(npc_id)

    from .tavern_rules import REPUTATION_GATES
    unlocked = [
        g["text"] for g in REPUTATION_GATES.get(npc_id, [])
        if rep >= g["min"]
    ]
    return (
        f"{prof['name']} ({prof['role']}) — Reputation: {rep}/100 ({tier})\n"
        f"{''.join('✅ ' + u + chr(10) for u in unlocked) if unlocked else 'No special access unlocked yet.'}"
    )


# ── Rumors ──────────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "rumor", "gossip", "info"],
    category=SkillCategory.SOCIAL,
    description="Listen for rumours in the tavern. May unlock quests.",
    cooldown=10,
)
def tavern_hear_rumor() -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."
    rumor = state.hear_rumor()
    if not rumor:
        return "No new rumours to hear. You've caught up on all the gossip."
    state.adjust_heat(2)
    quest_hint = ""
    if rumor.unlocks_quest:
        quest = state.quests.get(rumor.unlocks_quest)
        if quest:
            quest_hint = f"\n💡 This might relate to: '{quest.title}'"
    return (
        f"🗣️ Rumour from {NPC_PROFILES.get(rumor.source, {}).get('name', rumor.source)}:\n"
        f'"{rumor.text}"{quest_hint}'
    )


# ── Quests ──────────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "quest", "mission"],
    category=SkillCategory.GAME,
    description="View available quests or accept one by ID.",
)
def tavern_quest_board(action: str = "list", quest_id: str = "") -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."

    if action == "accept" and quest_id:
        q = state.accept_quest(quest_id)
        if q:
            state.log_event(f"Accepted quest: {q.title}", "quest")
            return f"📜 Quest accepted: {q.title}\nObjective: {q.objective}\nReward: {q.reward_gold}g"
        return f"Quest '{quest_id}' not available."

    if action == "progress" and quest_id:
        q = state.advance_quest(quest_id)
        if q:
            if q.status.value == "completed":
                state.log_event(f"Completed quest: {q.title}!", "quest")
                return f"🎉 Quest COMPLETE: {q.title}! Earned {q.reward_gold}g."
            return f"Quest '{q.title}' progress: {q.progress}/{q.max_progress}"
        return f"Quest '{quest_id}' not active."

    # Default: list
    available = state.get_available_quests()
    active = state.get_active_quests()
    lines = ["📋 Quest Board:"]
    if available:
        lines.append("Available:")
        for q in available:
            lines.append(f"  • [{q.id}] {q.title} — {q.reward_gold}g ({q.giver})")
    if active:
        lines.append("Active:")
        for q in active:
            lines.append(f"  • [{q.id}] {q.title} — {q.progress}/{q.max_progress}")
    if not available and not active:
        lines.append("No quests on the board right now.")
    return "\n".join(lines)


# ── Dice Game ───────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "game", "dice", "gambling"],
    category=SkillCategory.GAME,
    description="Play Dragon's Dice — bet gold, roll 2d6, try to beat the house without going over 21.",
    cooldown=3,
)
def tavern_dice(action: str = "start", bet: int = 5) -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."

    if action == "start":
        if state.dice_game_active:
            return "A dice game is already in progress. Roll or hold."
        if not state.start_dice_game(bet):
            return f"Not enough gold. You have {state.gold}g."
        state.adjust_heat(5)
        return f"🎲 Dragon's Dice! Bet: {bet}g. Roll 2d6, beat the house, don't bust over 21. Type roll or hold."

    if action == "roll":
        result = state.roll_dice()
        if "error" in result:
            return result["error"]
        state.adjust_heat(2)
        return f"🎲 {result.get('message', '')}"

    if action == "hold":
        result = state.hold_dice()
        if "error" in result:
            return result["error"]
        if result.get("won"):
            state.adjust_heat(8)
            state.log_event(f"Player won {result['winnings']}g at dice!", "game")
        return f"🎲 {result.get('message', '')}"

    return "Actions: start (with bet), roll, hold."


# ── Atmosphere Control ──────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "atmosphere", "mood"],
    category=SkillCategory.SOCIAL,
    description="Influence tavern atmosphere: buy a round (heat+15, gold-20), calm down (heat-10), toast (heat+5).",
    cooldown=8,
)
def tavern_influence(action: str = "toast") -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."

    if action == "buy_round":
        if not state.spend_gold(20):
            return f"Not enough gold for a round. Need 20g, have {state.gold}g."
        state.adjust_heat(15)
        for npc_id in state.npcs_present:
            state.adjust_reputation(npc_id, 5)
        state.log_event("Player bought a round for the house!", "social")
        return f"🍻 You buy a round for everyone! The tavern cheers. Heat +15, all reputations +5."

    if action == "calm":
        state.adjust_heat(-10)
        state.log_event("Player tried to calm the tavern.", "social")
        return f"🕊️ You signal for calm. Heat -10. Atmosphere: {state.atmosphere.value}"

    if action == "toast":
        state.adjust_heat(5)
        state.log_event("Player raised a toast.", "social")
        return f"🥂 You raise your glass! The tavern follows. Heat +5. Atmosphere: {state.atmosphere.value}"

    return "Actions: buy_round, calm, toast."


# ── Bard ────────────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "bard", "music", "song"],
    category=SkillCategory.SOCIAL,
    description="Request a song from the bard. Costs 5g. Changes mood.",
    cooldown=15,
)
def tavern_request_song(mood: str = "merry") -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."
    if "bard" not in state.npcs_present:
        return "The bard isn't here right now."
    if not state.spend_gold(5):
        return f"Not enough gold. Song costs 5g, you have {state.gold}g."

    mood_effects = {
        "merry": {"happiness": 10, "warmth": 5},
        "sad": {"happiness": -5, "warmth": 10, "clarity": 5},
        "epic": {"courage": 15, "happiness": 5},
        "romantic": {"charm": 10, "warmth": 10},
        "mysterious": {"mystery": 15, "clarity": 5},
    }
    effects = mood_effects.get(mood, mood_effects["merry"])
    changes = state.adjust_stats(**effects)
    state.adjust_reputation("bard", 3)
    state.adjust_heat(3)

    # Start a song timer
    try:
        from engine.mcp.framework import get_framework
        get_framework().start_timer(
            name="bard_song",
            duration_secs=60.0,
            on_complete_note="The bard's song ends with a flourish.",
            metadata={"mood": mood},
        )
    except Exception:
        pass

    state.log_event(f"Bard plays a {mood} song.", "music")
    fx = ", ".join(f"{k}{'+' if v > 0 else ''}{v}" for k, v in changes.items() if v)
    return f"🎵 The bard plays a {mood} tune. Effects: {fx}. Reputation with bard +3."


# ── Trade ───────────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "trade", "merchant", "buy"],
    category=SkillCategory.GAME,
    description="Trade with the merchant. Browse goods or buy items.",
)
def tavern_trade(action: str = "browse", item_id: str = "") -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."
    if "merchant" not in state.npcs_present:
        return "The merchant isn't here right now."

    goods = {
        "healing_potion": {"name": "Healing Potion", "price": 15, "desc": "Restores 20 warmth."},
        "lucky_charm": {"name": "Lucky Charm", "price": 25, "desc": "Grants +10 mystery."},
        "fine_cloak": {"name": "Fine Cloak", "price": 30, "desc": "Impresses NPCs. +5 charm."},
        "map_fragment": {"name": "Map Fragment", "price": 20, "desc": "Hints at hidden treasure."},
        "smoke_bomb": {"name": "Smoke Bomb", "price": 10, "desc": "Escape any brawl instantly."},
    }

    # Discount for high reputation
    from .tavern_rules import get_unlocked_features
    discount = 0.8 if "discount" in get_unlocked_features(state) else 1.0

    if action == "buy" and item_id:
        item = goods.get(item_id)
        if not item:
            return f"Unknown item. Available: {', '.join(goods.keys())}"
        price = int(item["price"] * discount)
        if not state.spend_gold(price):
            return f"Not enough gold. {item['name']} costs {price}g."
        state.inventory[item_id] = state.inventory.get(item_id, 0) + 1
        state.adjust_reputation("merchant", 2)
        state.log_event(f"Bought {item['name']} for {price}g.", "trade")
        return f"🛒 Bought {item['name']} for {price}g. {item['desc']}"

    # Browse
    lines = ["🏪 Merchant's Wares:"]
    for iid, item in goods.items():
        price = int(item["price"] * discount)
        lines.append(f"  • [{iid}] {item['name']} — {price}g — {item['desc']}")
    if discount < 1.0:
        lines.append("✨ Loyalty discount applied (20% off)!")
    return "\n".join(lines)


# ── Advance Time ────────────────────────────────────────────────────

@skill(
    pack="tavern",
    tags=["tavern", "time", "advance"],
    category=SkillCategory.GAME,
    description="Advance the time of day in the tavern. Morning → Afternoon → Evening → Midnight.",
    cooldown=20,
)
def tavern_advance_time() -> str:
    state = _get_state()
    if not state:
        return "Tavern closed."
    order = [
        state.time_of_day.MORNING, state.time_of_day.AFTERNOON,
        state.time_of_day.EVENING, state.time_of_day.MIDNIGHT,
    ]
    idx = order.index(state.time_of_day)
    state.time_of_day = order[(idx + 1) % len(order)]
    state.turn += 1
    state.adjust_heat(-5)  # Natural cool-down over time

    events = []
    if state.maybe_stranger_appears():
        events.append("A hooded stranger enters the tavern...")
        state.log_event("The stranger has arrived.", "event")

    state.log_event(f"Time advanced to {state.time_of_day.value}.", "time")
    result = f"⏰ Time is now {state.time_of_day.value}. Turn {state.turn}."
    if events:
        result += "\n" + "\n".join(events)
    return result
