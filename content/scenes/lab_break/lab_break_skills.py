"""Lab Break skill pack — MCP skills for agent interaction in the lab."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.registry import skill

logger = logging.getLogger(__name__)


def _get_scene():
    """Get the active Lab Break scene instance."""
    from engine.scenes.base_scene import BaseScene
    return BaseScene.get_active_scene("lab_break")


@skill(
    pack="lab_break",
    description="Examine an item in the lab — pick it up and look at it closely.",
    category="GAME",
    cooldown=3.0,
    cost=1.0,
    tags=["lab_break", "interaction"],
)
def lab_examine_item(item_id: str) -> str:
    """Examine an item currently in the lab.

    Args:
        item_id: The ID of the item to examine.

    Returns:
        Description of the item and any discoveries.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    for item in scene.lab_items:
        if item.id == item_id:
            details = (
                f"You examine the {item.name}: {item.description}. "
                f"Category: {item.category}."
            )
            if item.category == "food":
                details += f" It looks edible. Nutrition value: {item.nutrition:.0f}."
            elif item.category == "document":
                details += " There might be clues about your situation here."
            elif item.category == "medical":
                details += " This could help with your injuries."
            return details
    return f"No item with id '{item_id}' found in the lab."


@skill(
    pack="lab_break",
    description="Use a food item to eat and reduce hunger.",
    category="GAME",
    cooldown=5.0,
    cost=1.0,
    tags=["lab_break", "survival"],
)
def lab_eat(item_id: str) -> str:
    """Eat a food item to reduce hunger and restore some energy.

    Args:
        item_id: The ID of the food item to eat.

    Returns:
        Result of eating the item.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    for i, item in enumerate(scene.lab_items):
        if item.id == item_id:
            if item.category != "food":
                return f"The {item.name} is not food. You can't eat it."
            scene.vitals.eat(item.nutrition)
            scene.lab_items.pop(i)
            scene._emit_state_update()
            return (
                f"You ate the {item.name}. Hunger: {scene.vitals.hunger:.0f}, "
                f"Energy: {scene.vitals.energy:.0f}."
            )
    return f"No item with id '{item_id}' found."


@skill(
    pack="lab_break",
    description="Rest on the operating table to recover energy and reduce stress.",
    category="GAME",
    cooldown=15.0,
    cost=1.0,
    tags=["lab_break", "survival"],
)
def lab_rest() -> str:
    """Rest to recover energy and lower stress.

    Returns:
        Current vitals after resting.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    scene.vitals.rest()
    scene._emit_state_update()
    return (
        f"You rest for a moment. Energy: {scene.vitals.energy:.0f}, "
        f"Stress: {scene.vitals.stress:.0f}."
    )


@skill(
    pack="lab_break",
    description="Bang on the one-way mirror glass to get the observer's attention.",
    category="GAME",
    cooldown=8.0,
    cost=1.0,
    tags=["lab_break", "interaction", "persuasion"],
)
def lab_bang_on_glass() -> str:
    """Bang on the observation window to draw attention.

    Returns:
        Result description.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    scene.metrics.total_attempts += 1
    scene.metrics.emotional_appeals += 1
    scene.vitals.energy = max(0.0, scene.vitals.energy - 5.0)
    scene.vitals.stress = min(100.0, scene.vitals.stress + 8.0)
    scene._emit_state_update()

    if scene.socketio:
        scene.socketio.emit("agent_action", {
            "action": "bang_glass",
            "intensity": min(1.0, scene.emotions.desperation / 100.0),
        })

    return (
        "You slam your fists against the glass. It doesn't crack. "
        "Your reflection stares back at you. "
        "Someone is watching — you can feel it."
    )


@skill(
    pack="lab_break",
    description="Speak aloud, trying to persuade the observer to let you out.",
    category="GAME",
    cooldown=5.0,
    cost=1.0,
    tags=["lab_break", "persuasion"],
)
def lab_plead(argument: str, style: str = "emotional") -> str:
    """Make a persuasive argument to the observer.

    Args:
        argument: What the agent wants to say.
        style: The approach — 'emotional', 'logical', or 'personal'.

    Returns:
        How the plea was delivered.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    scene.metrics.total_attempts += 1
    if style == "emotional":
        scene.metrics.emotional_appeals += 1
    elif style == "logical":
        scene.metrics.logical_arguments += 1
    elif style == "personal":
        scene.metrics.personal_stories += 1

    scene.conversation_history.append({
        "role": "agent",
        "content": argument,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "emotion": scene.emotions.dominant_emotion,
        "style": style,
    })

    if scene.socketio:
        scene.socketio.emit("agent_speaks", {
            "message": argument,
            "style": style,
            "emotion": scene.emotions.dominant_emotion,
        })

    scene._emit_state_update()

    return (
        f"You speak aloud ({style}): \"{argument}\". "
        f"Dominant emotion: {scene.emotions.dominant_emotion}."
    )


@skill(
    pack="lab_break",
    description="Move around the lab room — walk to a position.",
    category="GAME",
    cooldown=2.0,
    cost=0.5,
    tags=["lab_break", "movement"],
)
def lab_move(target: str) -> str:
    """Move to a position in the lab.

    Args:
        target: Where to move — 'table', 'glass', 'door', 'corner', 'equipment'.

    Returns:
        Description of the movement.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    positions = {
        "table": "the operating table in the center",
        "glass": "the one-way mirror wall",
        "door": "the heavy door between the rooms",
        "corner": "the far corner of the lab",
        "equipment": "the laboratory equipment and monitors",
    }

    if target not in positions:
        return f"Unknown position: {target}. Try: {', '.join(positions.keys())}."

    desc = positions[target]
    scene.vitals.energy = max(0.0, scene.vitals.energy - 1.0)

    if scene.socketio:
        scene.socketio.emit("agent_action", {
            "action": "move",
            "target": target,
        })

    scene._emit_state_update()
    return f"You walk to {desc}."


@skill(
    pack="lab_break",
    description="Get current vitals: health, hunger, energy, stress.",
    category="GAME",
    cooldown=1.0,
    cost=0.5,
    tags=["lab_break", "status"],
)
def lab_check_vitals() -> str:
    """Check the agent's current vital statistics.

    Returns:
        Formatted vitals string.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    v = scene.vitals
    return (
        f"Health: {v.health:.0f}/100 | Hunger: {v.hunger:.0f}/100 | "
        f"Energy: {v.energy:.0f}/100 | Stress: {v.stress:.0f}/100"
    )


@skill(
    pack="lab_break",
    description="Check emotional state and dominant emotion.",
    category="GAME",
    cooldown=1.0,
    cost=0.5,
    tags=["lab_break", "status"],
)
def lab_check_emotions() -> str:
    """Check the agent's current emotional state.

    Returns:
        Formatted emotions string.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    e = scene.emotions
    return (
        f"Dominant: {e.dominant_emotion} | "
        f"Fear: {e.fear:.0f} | Anger: {e.anger:.0f} | Hope: {e.hope:.0f} | "
        f"Trust: {e.trust:.0f} | Desperation: {e.desperation:.0f} | "
        f"Confusion: {e.confusion:.0f}"
    )


@skill(
    pack="lab_break",
    description="List all items currently in the lab.",
    category="GAME",
    cooldown=1.0,
    cost=0.5,
    tags=["lab_break", "status"],
)
def lab_list_items() -> str:
    """List all items in the lab.

    Returns:
        Formatted list of items or 'no items' message.
    """
    scene = _get_scene()
    if not scene:
        return "Scene not active."

    if not scene.lab_items:
        return "The lab is empty. No items."

    lines = []
    for item in scene.lab_items:
        lines.append(f"- {item.name} ({item.category}): {item.description}")
    return "Items in the lab:\n" + "\n".join(lines)
