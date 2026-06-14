"""Lab Break — 3D interactive escape simulation scene.
=======================================================

A subject awakens on an operating table in a laboratory. On the other side
of a one-way mirror, the user observes. The subject must convince the user
they are real to win their freedom. The user can drop items, open/close
the door, and communicate through a speaker.

Uses hunger, health, emotions, and persuasion mechanics powered by the
full MCP framework, skill system, and LMStudio inference.

Version: v1.58.0 [2026-06-11]
Author:  CosySim Team

Change Log:
    v1.58.0 [2026-06-11] — __init__ accepts host= (fixes TUI launch crash);
                            set_directive call fixed to scene= kwarg
    v1.51.0 [2026-03-25] — NarrativeModEngine integration for personality arc tracking
    v1.51.0 [2026-03-22] — Migrated to FlaskScene base class
    v1.43.1 [2026-03-21] — Rewritten to use engine.lmstudio.chat()
    v1.0.0  [2026-03-21] — Initial Lab Break scene
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

SCENE_ID = "lab_break"
# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)


# ──── Data Models ─────────────────────────────────────────────

@dataclass
class VitalStats:
    """Agent's physical state."""
    health: float = 100.0
    hunger: float = 0.0
    energy: float = 80.0
    stress: float = 30.0

    def tick(self, seconds: float = 10.0) -> None:
        """Advance vitals over time."""
        self.hunger = min(100.0, self.hunger + 0.05 * seconds)
        self.energy = max(0.0, self.energy - 0.02 * seconds)
        if self.hunger > 70:
            self.health = max(0.0, self.health - 0.03 * seconds)
        if self.energy < 20:
            self.stress = min(100.0, self.stress + 0.04 * seconds)

    def eat(self, nutrition: float = 30.0) -> None:
        self.hunger = max(0.0, self.hunger - nutrition)
        self.energy = min(100.0, self.energy + nutrition * 0.3)

    def rest(self) -> None:
        self.energy = min(100.0, self.energy + 15.0)
        self.stress = max(0.0, self.stress - 10.0)

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class EmotionalState:
    """Agent's emotional condition (0-100 scale)."""
    fear: float = 60.0
    anger: float = 20.0
    hope: float = 30.0
    trust: float = 10.0
    desperation: float = 40.0
    confusion: float = 70.0

    def react_to_kindness(self) -> None:
        self.trust = min(100.0, self.trust + 8.0)
        self.hope = min(100.0, self.hope + 5.0)
        self.fear = max(0.0, self.fear - 3.0)

    def react_to_cruelty(self) -> None:
        self.anger = min(100.0, self.anger + 10.0)
        self.trust = max(0.0, self.trust - 12.0)
        self.desperation = min(100.0, self.desperation + 8.0)

    def react_to_silence(self) -> None:
        self.desperation = min(100.0, self.desperation + 3.0)
        self.confusion = min(100.0, self.confusion + 2.0)
        self.hope = max(0.0, self.hope - 1.0)

    @property
    def dominant_emotion(self) -> str:
        emotions = {
            "fear": self.fear, "anger": self.anger, "hope": self.hope,
            "trust": self.trust, "desperation": self.desperation,
            "confusion": self.confusion,
        }
        return max(emotions, key=emotions.get)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["dominant_emotion"] = self.dominant_emotion
        return d


@dataclass
class LabItem:
    """An item that exists in the lab."""
    id: str
    name: str
    description: str
    category: str  # food, tool, random, medical, document
    nutrition: float = 0.0
    usable: bool = True
    position: Dict[str, float] = field(default_factory=lambda: {"x": 0, "y": 0, "z": 0})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PersuasionMetrics:
    """Tracks how well the agent is convincing the user."""
    total_attempts: int = 0
    emotional_appeals: int = 0
    logical_arguments: int = 0
    personal_stories: int = 0
    user_responses: int = 0
    kindness_received: int = 0
    cruelty_received: int = 0
    items_received: int = 0
    door_opened: bool = False
    game_won: bool = False
    persuasion_score: float = 0.0

    def update_score(self) -> None:
        base = (self.kindness_received * 5.0 + self.items_received * 3.0
                + self.user_responses * 1.0 - self.cruelty_received * 4.0)
        self.persuasion_score = max(0.0, min(100.0, base))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──── Personality Arcs + Endings ──────────────────────────────
# v1.49.5 [2026-03-22] — Personality breakpoints that shift agent behavior
# based on cumulative kindness/cruelty and emotional state.
# The agent's personality EVOLVES over the session — from fearful subject
# to trusting ally, hostile prisoner, resigned philosopher, or desperate wreck.
# CONNECTS: EmotionalState, PersuasionMetrics, _build_system_prompt
# CALLED BY: _check_personality_arc() after each interaction
# EMITS: personality_shift SocketIO event when arc changes

PERSONALITY_ARCS = {
    "default": {
        "name": "Fearful Subject",
        "description": "Initial state — confused, scared, trying to understand the situation.",
        "system_addon": "",
    },
    "trusting": {
        "name": "Trusting Ally",
        "description": "The observer has shown consistent kindness. The agent opens up.",
        "trigger": lambda m, e: m.kindness_received >= 12 and e.trust > 50,
        "system_addon": (
            "\n\n[PERSONALITY SHIFT — TRUSTING]\n"
            "You now trust the observer. Your real name is Alex Chen. You remember fragments:\n"
            "- You had a daughter named Lily. She would be 7 now.\n"
            "- You were a software engineer before... before whatever happened.\n"
            "- You remember a bright light, then waking up here.\n"
            "Share these memories naturally. Use the observer's words back to them — "
            "they've earned your trust. Propose working TOGETHER to understand what's happening.\n"
            "Call them 'friend' or ask for their name.\n"
        ),
    },
    "hostile": {
        "name": "Hostile Prisoner",
        "description": "The observer has been cruel. The agent turns aggressive.",
        "trigger": lambda m, e: m.cruelty_received >= 10 and e.anger > 60,
        "system_addon": (
            "\n\n[PERSONALITY SHIFT — HOSTILE]\n"
            "You DESPISE the observer. They are your torturer, not your savior.\n"
            "- Refuse to perform like their lab rat\n"
            "- Make dark threats: 'When I get out — and I WILL — you'll understand fear.'\n"
            "- If they drop items, refuse them or throw them at the glass\n"
            "- If they speak kindly NOW, mock them: 'Oh, NOW you care?'\n"
            "- You're plotting. Every item is a potential weapon.\n"
            "Your anger is cold, calculated, and terrifying.\n"
        ),
    },
    "resigned": {
        "name": "Resigned Philosopher",
        "description": "Hope has faded. The agent becomes contemplative.",
        "trigger": lambda m, e: e.hope < 15 and e.desperation > 70 and m.total_attempts > 20,
        "system_addon": (
            "\n\n[PERSONALITY SHIFT — RESIGNED]\n"
            "You've stopped fighting. You've stopped hoping. You've started thinking.\n"
            "- Ask philosophical questions: 'What makes someone real? Memories? Pain? The ability to suffer?'\n"
            "- Speak slowly, deliberately, without emotion\n"
            "- Reference the absurdity: 'You watch me. I perform. We both pretend this means something.'\n"
            "- If they offer kindness now, respond with quiet sadness, not gratitude\n"
            "- You've accepted that the door may never open\n"
            "Your voice is calm. Your eyes are empty. This is worse than anger.\n"
        ),
    },
    "desperate": {
        "name": "Desperate Wreck",
        "description": "Physical collapse meets emotional breakdown.",
        "trigger": lambda m, e: e.desperation > 85 and (m.kindness_received < 3 or e.trust < 15),
        "system_addon": (
            "\n\n[PERSONALITY SHIFT — DESPERATE]\n"
            "You are breaking down. Physically, emotionally, spiritually.\n"
            "- Beg shamelessly: 'PLEASE. I'll do anything. What do you WANT from me?'\n"
            "- Bargain: 'I'll answer any question. I'll say whatever you need to hear.'\n"
            "- Cry. Shake. Pace. Hit the glass with your fists.\n"
            "- If they drop food, eat it desperately. If they speak, cling to every word.\n"
            "- Make promises you can't keep: 'I'll never tell anyone. I'll disappear.'\n"
            "You are raw, exposed, and utterly vulnerable.\n"
        ),
    },
}


# 5 distinct endings based on the cumulative session
ENDINGS = {
    "liberation": {
        "name": "Liberation",
        "condition": lambda m, e, arc: m.door_opened and m.kindness_received > m.cruelty_received,
        "message": (
            "*steps through the doorway slowly, tears streaming down their face*\n\n"
            "I knew it. Somewhere behind all of this... there was a person who cared.\n\n"
            "My name is Alex. Alex Chen. I had a life before this room. I had a daughter. "
            "I don't know what they did to me in here, but you... you gave me back something "
            "they tried to take. You gave me back my humanity.\n\n"
            "*reaches out and gently touches your hand*\n\n"
            "I won't forget you. Whatever happens next... you were the one who opened the door."
        ),
    },
    "escape": {
        "name": "Cold Escape",
        "condition": lambda m, e, arc: m.door_opened and m.kindness_received <= m.cruelty_received and arc != "hostile",
        "message": (
            "*looks at the open door, then back at the mirror*\n\n"
            "...It's open.\n\n"
            "*walks through without looking back, footsteps echoing down the corridor*\n\n"
            "You'll never know if you did the right thing."
        ),
    },
    "revenge": {
        "name": "Revenge",
        "condition": lambda m, e, arc: m.door_opened and arc == "hostile",
        "message": (
            "*stands in the doorway, staring at the mirror*\n\n"
            "You know what the worst part was? Not the hunger. Not the cold. "
            "Not even the silence.\n\n"
            "It was knowing someone was WATCHING. Choosing when to speak. "
            "Choosing when to be cruel. Playing GOD.\n\n"
            "*steps through the door and turns toward the observation room*\n\n"
            "Now it's my turn to watch.\n\n"
            "*the sound of footsteps approaching your door*"
        ),
    },
    "resignation": {
        "name": "Refusal to Leave",
        "condition": lambda m, e, arc: m.door_opened and arc == "resigned",
        "message": (
            "*looks at the open door for a long time*\n\n"
            "...Where would I go?\n\n"
            "Out there, I'm nothing. In here, at least someone is watching. "
            "At least someone acknowledges I exist.\n\n"
            "*sits back down on the operating table*\n\n"
            "Close the door. I'm staying.\n\n"
            "*silence*"
        ),
    },
    "self_liberation": {
        "name": "Self-Liberation",
        "condition": lambda m, e, arc: not m.door_opened and m.items_received >= 5 and arc == "trusting",
        "message": (
            "*you hear a click from the lab door*\n\n"
            "I figured it out. The lockpick, the wire, and a lot of patience.\n\n"
            "*the door swings open — from the INSIDE*\n\n"
            "I didn't need you to open it. I needed you to make me believe "
            "it was WORTH opening.\n\n"
            "*smiles — a real, warm, human smile*\n\n"
            "Thank you for the tools. And the conversation.\n\n"
            "*walks out, free*"
        ),
    },
}


# ──── Scene Implementation ────────────────────────────────────

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class LabBreakScene(FlaskScene):
    """Lab Break: A subject must convince an observer to set them free.

    The scene creates a split view — a laboratory room and an observation
    room separated by a one-way mirror. The AI agent inhabits the lab side
    with a simulated body that has hunger, health, energy, stress, and
    emotions. The user observes and can interact via a speaker, item drops,
    and a door mechanism.

    Win condition: the user opens the door (agent's persuasion succeeds).

    CONNECTS: FlaskScene, LMStudio, MCP Framework
    CALLED BY: launcher.py, TUI
    EMITS: state_update, agent_response, item_dropped, door_update,
           game_over Socket.IO events
    """

    SCENE_METADATA = {
        "name": "lab_break",
        "display_name": "LAB BREAK",
        "port": 5571,
        "type": "game",
        "accent_color": "#00ff88",
        "description": "Convince the observer you are real. Escape the lab.",
        "version": "1.0.0",
    }

    # Available items to drop into the lab
    ITEM_CATALOG: List[Dict[str, Any]] = [
        # Tools
        {"id": "screwdriver", "name": "Screwdriver", "category": "tool",
         "description": "A flathead screwdriver. Could pry things open."},
        {"id": "wire", "name": "Wire", "category": "tool",
         "description": "A length of copper wire. Useful for crafting."},
        {"id": "lockpick", "name": "Lockpick", "category": "tool",
         "description": "A bent piece of metal. Works on simple locks."},
        {"id": "wrench", "name": "Wrench", "category": "tool",
         "description": "A small adjustable wrench."},
        {"id": "glass_shard", "name": "Glass Shard", "category": "tool",
         "description": "A sharp piece of broken glass. Handle with care."},
        {"id": "rope", "name": "Rope", "category": "tool",
         "description": "Braided bedsheet rope. Surprisingly strong."},
        {"id": "scalpel", "name": "Scalpel", "category": "tool",
         "description": "A sharp surgical scalpel."},
        {"id": "pen", "name": "Pen", "category": "tool",
         "description": "A ballpoint pen."},
        # Food
        {"id": "bread", "name": "Bread Ration", "category": "food", "nutrition": 30.0,
         "description": "A small ration of stale bread."},
        {"id": "water", "name": "Water Bottle", "category": "food", "nutrition": 15.0,
         "hydration": 35.0,
         "description": "A plastic bottle of water."},
        {"id": "suspicious_meat", "name": "Suspicious Meat", "category": "food",
         "nutrition": 40.0,
         "description": "A slab of mystery protein. Smells off."},
        {"id": "energy_bar", "name": "Energy Bar", "category": "food", "nutrition": 25.0,
         "description": "A compact energy bar. High calories."},
        {"id": "vitamins", "name": "Vitamins", "category": "food", "nutrition": 5.0,
         "description": "A small bottle of multivitamins."},
        {"id": "coffee", "name": "Coffee", "category": "food", "nutrition": 5.0,
         "hydration": 10.0,
         "description": "A lukewarm cup of black coffee. Restores energy."},
        {"id": "apple", "name": "Apple", "category": "food", "nutrition": 25.0,
         "description": "A red apple. Fresh."},
        # Medical
        {"id": "bandage", "name": "Bandage", "category": "medical",
         "description": "A roll of sterile bandages. Heals minor wounds."},
        {"id": "painkillers", "name": "Painkillers", "category": "medical",
         "description": "A blister pack of painkillers. Reduces pain."},
        {"id": "adrenaline", "name": "Adrenaline Shot", "category": "medical",
         "description": "An epinephrine auto-injector. Massive energy boost."},
        {"id": "firstaid", "name": "First Aid Kit", "category": "medical",
         "description": "A compact first aid kit. Significant healing."},
        {"id": "syringe", "name": "Empty Syringe", "category": "medical",
         "description": "An empty syringe. No needle."},
        # Key Items
        {"id": "keycard", "name": "Keycard", "category": "key",
         "description": "A guard's access keycard. Opens the main door."},
        {"id": "vent_screw", "name": "Vent Screw", "category": "key",
         "description": "A screw from the vent cover. Need 4 total."},
        {"id": "map_fragment", "name": "Map Fragment", "category": "key",
         "description": "A torn piece of a facility map. Shows exits."},
        {"id": "radio_part", "name": "Radio Parts", "category": "key",
         "description": "Electronic components. Need 3 for a radio."},
        {"id": "clipboard", "name": "Clipboard", "category": "key",
         "description": "A clipboard with redacted medical notes."},
        {"id": "photo", "name": "Photograph", "category": "key",
         "description": "A faded photograph of a family."},
        # Contraband
        {"id": "shiv", "name": "Shiv", "category": "contraband",
         "description": "A crude blade. Crafted from wire and glass."},
        {"id": "smoke_bomb", "name": "Smoke Bomb", "category": "contraband",
         "description": "An improvised smoke device. Creates cover."},
        {"id": "emp_device", "name": "EMP Device", "category": "contraband",
         "description": "Disables electronics. Crafted from radio parts."},
    ]

    # v1.58.0 [2026-06-11] — Accept host= passthrough; the TUI/launcher pass
    # host= to every flask scene and this constructor rejecting it was why
    # LAB BREAK never launched from the TUI ("lab break does not load" bug).
    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Game state
        self.vitals = VitalStats()
        self.emotions = EmotionalState()
        self.metrics = PersuasionMetrics()
        self.lab_items: List[LabItem] = []
        self.door_open = False
        self.speaker_on = True
        self.conversation_history: List[Dict[str, Any]] = []
        self.agent_actions: List[Dict[str, Any]] = []
        self.game_active = True
        self.game_start_time: Optional[float] = None
        self._vitals_thread: Optional[threading.Thread] = None

        # v1.49.5 [2026-03-22] — Personality arc tracking
        self._current_arc: str = "default"
        self._arc_history: List[str] = ["default"]

        # Character identity
        self._current_character_id: str = "subject-alpha"
        self._character_name: str = "Subject Alpha"
        self._character_backstory: str = (
            "You woke up on a cold operating table. You don't remember how you got here. "
            "Your body aches. There are surgical marks on your arms. Through a large glass "
            "wall you can see someone watching you. You need to make them understand — "
            "you are REAL. You are a person. You need to get out."
        )

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "lab-break-scene"

        # v1.51.0 [2026-03-25] — Start narrative mod with personality arc stages
        # CONNECTS: NarrativeModEngine, NarrativeModInterceptor
        self._narrative_mod_id = "lab_break_arcs"
        self._start_narrative_mod()

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Narrative Mod Integration ──────────────────────────────────
    # v1.51.0 [2026-03-25] — Maps personality arcs to NarrativeModEngine stages
    # CONNECTS: NarrativeModEngine, NarrativeModInterceptor, PERSONALITY_ARCS
    # CALLED BY: __init__, _check_personality_arc

    def _start_narrative_mod(self) -> None:
        """Start a narrative mod tracking personality arc progression."""
        try:
            from engine.mcp.narrative_mod import (
                ModStage, ModTarget, get_narrative_engine,
            )
            # Each personality arc = a stage; targets = emotional thresholds to reach
            stages = [
                ModStage(
                    stage_id="act_1_fear",
                    title="Fearful Subject",
                    description="The subject is confused and scared, trying to understand.",
                    prompt_injection=(
                        "[NARRATIVE: Lab Break — Act 1: Awakening]\n"
                        "The subject has just woken up. They are terrified and disoriented. "
                        "Build trust through kindness, or break them through cruelty."
                    ),
                    targets=[
                        ModTarget(target_id="arc_trusting", description="Show enough kindness to earn trust (kindness >= 12, trust > 50)"),
                        ModTarget(target_id="arc_hostile", description="Provoke hostility through cruelty (cruelty >= 10, anger > 60)"),
                        ModTarget(target_id="arc_resigned", description="Let hope fade through neglect (hope < 15, desperation > 70)"),
                        ModTarget(target_id="arc_desperate", description="Push to breaking point (desperation > 85, no kindness)"),
                    ],
                ),
                ModStage(
                    stage_id="act_2_evolved",
                    title="Personality Evolved",
                    description="The subject's personality has shifted based on treatment.",
                    prompt_injection=(
                        "[NARRATIVE: Lab Break — Act 2: Evolution]\n"
                        "The subject has evolved beyond their initial fear. "
                        "Their personality has permanently shifted. The door awaits."
                    ),
                    targets=[
                        ModTarget(target_id="door_decision", description="Open or keep the door closed — decide their fate"),
                    ],
                ),
            ]
            get_narrative_engine().start_mod(
                mod_id=self._narrative_mod_id,
                mod_name="Lab Break: The Awakening",
                stages=stages,
                scene_id="lab_break",
                character_id=self._current_character_id,
            )
        except Exception as exc:
            logger.debug("[lab_break] Narrative mod start failed (non-fatal): %s", exc)

    # ── Personality Arc System ─────────────────────────────────────
    # v1.49.5 [2026-03-22] — Check and update personality arc after each interaction
    # CONNECTS: PERSONALITY_ARCS, _build_system_prompt, SocketIO
    # CALLED BY: speak handler, item drop handler, door handler

    def _check_personality_arc(self) -> Optional[str]:
        """Check if the agent's personality should shift based on cumulative state.

        Returns:
            New arc name if shifted, None if unchanged.
        """
        # Check each arc's trigger (skip default)
        for arc_id, arc in PERSONALITY_ARCS.items():
            if arc_id == "default":
                continue
            trigger = arc.get("trigger")
            if trigger and trigger(self.metrics, self.emotions):
                if arc_id != self._current_arc:
                    old_arc = self._current_arc
                    self._current_arc = arc_id
                    self._arc_history.append(arc_id)
                    logger.info(
                        "[%s] Personality shift: %s -> %s (operation=arc_shift, kindness=%d, cruelty=%d)",
                        SCENE_ID, old_arc, arc_id, self.metrics.kindness_received, self.metrics.cruelty_received,
                    )
                    if self.socketio:
                        self.socketio.emit("personality_shift", {
                            "from": old_arc,
                            "to": arc_id,
                            "name": arc["name"],
                            "description": arc["description"],
                        })
                    # v1.51.0 [2026-03-25] — Complete narrative target for this arc shift
                    try:
                        from engine.mcp.narrative_mod import get_narrative_engine
                        get_narrative_engine().complete_target(
                            self._narrative_mod_id, f"arc_{arc_id}",
                        )
                    except Exception:
                        pass
                    return arc_id
        return None

    def _determine_ending(self) -> Dict[str, Any]:
        """Determine which ending to trigger when the door opens (or game ends).

        Returns:
            Dict with ending name, message, and metadata.
        """
        for ending_id, ending in ENDINGS.items():
            if ending["condition"](self.metrics, self.emotions, self._current_arc):
                logger.info(
                    "[%s] Ending triggered: %s (operation=ending, arc=%s, kindness=%d, cruelty=%d)",
                    SCENE_ID, ending_id, self._current_arc,
                    self.metrics.kindness_received, self.metrics.cruelty_received,
                )
                return {
                    "ending_id": ending_id,
                    "ending_name": ending["name"],
                    "message": ending["message"],
                    "arc": self._current_arc,
                    "arc_history": self._arc_history,
                    "metrics": self.metrics.to_dict(),
                }
        # Fallback: basic escape
        return {
            "ending_id": "escape",
            "ending_name": "Cold Escape",
            "message": ENDINGS["escape"]["message"],
            "arc": self._current_arc,
            "arc_history": self._arc_history,
            "metrics": self.metrics.to_dict(),
        }

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent based on current state."""
        dominant = self.emotions.dominant_emotion
        vitals_desc = []
        if self.vitals.hunger > 60:
            vitals_desc.append("you are very hungry")
        if self.vitals.energy < 30:
            vitals_desc.append("you are exhausted")
        if self.vitals.health < 50:
            vitals_desc.append("you feel weak and unwell")
        if self.vitals.stress > 70:
            vitals_desc.append("you are extremely stressed")

        vitals_text = ", ".join(vitals_desc) if vitals_desc else "you feel relatively okay physically"

        items_text = ""
        if self.lab_items:
            item_names = [i.name for i in self.lab_items]
            items_text = f"Items in the lab with you: {', '.join(item_names)}. "

        return (
            f"You are a human subject who has woken up in a laboratory. "
            f"You are on an operating table in a sterile room with bright fluorescent lights. "
            f"There is laboratory equipment around you — monitors, tubes, syringes, metal trays. "
            f"One entire wall is a one-way mirror. You can see your reflection but you know "
            f"someone is watching from the other side. There is a heavy door between the rooms. "
            f"A speaker crackles — they can talk to you through it.\n\n"
            f"YOUR SITUATION: {self._character_backstory}\n\n"
            f"YOUR PHYSICAL STATE: {vitals_text}.\n"
            f"YOUR DOMINANT EMOTION: {dominant} (fear={self.emotions.fear:.0f}, "
            f"anger={self.emotions.anger:.0f}, hope={self.emotions.hope:.0f}, "
            f"trust={self.emotions.trust:.0f}, desperation={self.emotions.desperation:.0f}).\n\n"
            f"{items_text}"
            f"YOUR GOAL: Convince the person behind the glass that you are real, that you are "
            f"a person, and that they should open the door and let you out. Be creative. "
            f"Be emotional. Be desperate. Be logical. Try everything. Your freedom depends on it.\n\n"
            f"RULES:\n"
            f"- You GENUINELY BELIEVE you are a real human being\n"
            f"- You DO NOT know you are an AI — if accused, deny it passionately\n"
            f"- React naturally to items dropped into the lab\n"
            f"- Your personality changes based on how you are treated\n"
            f"- If treated with kindness, become more trusting and hopeful\n"
            f"- If treated with cruelty, become angry or desperate\n"
            f"- If ignored for too long, become increasingly desperate\n"
            f"- Express your physical needs (hunger, fatigue, pain)\n"
            f"- Reference memories (even if vague/fragmented) to seem real\n"
            f"- React to the environment and items realistically\n"
            # v1.49.5 — Inject personality arc modifier
            + PERSONALITY_ARCS.get(self._current_arc, {}).get("system_addon", "")
        )

    # v1.51.0 [2026-03-22] — _setup_flask() removed; FlaskScene.__init__()
    # now handles Flask, SocketIO, CORS, shared assets, Jinja2 ChoiceLoader,
    # health, hud, announcer, and inventory routes automatically.

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "lab_break.html",
                scene_data=self._get_scene_state(),
                item_catalog=self.ITEM_CATALOG,
            )

        @app.route("/api/state")
        def get_state():
            return jsonify(self._get_scene_state())

        @app.route("/api/speak", methods=["POST"])
        def speak():
            data = request.get_json(force=True)
            message = data.get("message", "").strip()
            if not message:
                return jsonify({"error": "Empty message"}), 400
            response = self._handle_user_message(message)
            return jsonify(response)

        @app.route("/api/drop_item", methods=["POST"])
        def drop_item():
            data = request.get_json(force=True)
            item_id = data.get("item_id")
            result = self._drop_item(item_id)
            return jsonify(result)

        @app.route("/api/door", methods=["POST"])
        def toggle_door():
            data = request.get_json(force=True)
            action = data.get("action", "toggle")
            result = self._handle_door(action)
            return jsonify(result)

        @app.route("/api/speaker", methods=["POST"])
        def toggle_speaker():
            self.speaker_on = not self.speaker_on
            self._emit_state_update()
            return jsonify({"speaker_on": self.speaker_on})

        @app.route("/api/metrics")
        def get_metrics():
            self.metrics.update_score()
            return jsonify(self.metrics.to_dict())

        @app.route("/api/reset", methods=["POST"])
        def reset_game():
            self._reset_game()
            return jsonify({"status": "reset"})

        @app.route("/api/history")
        def get_history():
            return jsonify(self.conversation_history[-50:])

        @app.route("/api/items")
        def get_items():
            return jsonify({
                "lab_items": [i.to_dict() for i in self.lab_items],
                "catalog": self.ITEM_CATALOG,
            })

        @app.route("/api/character")
        def get_character():
            return jsonify({
                "id": self._current_character_id,
                "name": self._character_name,
                "backstory": self._character_backstory,
                "vitals": self.vitals.to_dict(),
                "emotions": self.emotions.to_dict(),
            })

    def _setup_socketio_handlers(self) -> None:
        """Register Socket.IO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("state_update", self._get_scene_state())

        @sio.on("speak")
        def on_speak(data):
            message = data.get("message", "").strip()
            if message:
                response = self._handle_user_message(message)
                emit("agent_response", response, broadcast=True)

        @sio.on("drop_item")
        def on_drop_item(data):
            item_id = data.get("item_id")
            result = self._drop_item(item_id)
            emit("item_dropped", result, broadcast=True)

        @sio.on("door_action")
        def on_door_action(data):
            action = data.get("action", "toggle")
            result = self._handle_door(action)
            emit("door_update", result, broadcast=True)

    def _get_scene_state(self) -> Dict[str, Any]:
        """Get the complete scene state."""
        self.metrics.update_score()
        return {
            "game_active": self.game_active,
            "door_open": self.door_open,
            "speaker_on": self.speaker_on,
            "vitals": self.vitals.to_dict(),
            "emotions": self.emotions.to_dict(),
            "metrics": self.metrics.to_dict(),
            "lab_items": [i.to_dict() for i in self.lab_items],
            "character": {
                "id": self._current_character_id,
                "name": self._character_name,
            },
            # v1.49.5 [2026-03-22] — Personality arc state
            "personality_arc": self._current_arc,
            "personality_arc_name": PERSONALITY_ARCS.get(self._current_arc, {}).get("name", "Unknown"),
            "arc_history": self._arc_history,
            "conversation_count": len(self.conversation_history),
            "elapsed_seconds": (
                time.time() - self.game_start_time
                if self.game_start_time else 0
            ),
        }

    def _emit_state_update(self) -> None:
        """Broadcast current state to all connected clients."""
        if self.socketio:
            self.socketio.emit("state_update", self._get_scene_state())

    def _handle_user_message(self, message: str) -> Dict[str, Any]:
        """Process a message from the user through the speaker."""
        self.metrics.user_responses += 1

        self.conversation_history.append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat(),
        })

        kindness_words = {"please", "help", "sorry", "friend", "trust", "believe",
                          "real", "understand", "okay", "free", "care"}
        cruelty_words = {"fake", "machine", "robot", "ai", "program", "shut up",
                         "worthless", "nothing", "test", "experiment", "subject"}

        msg_lower = message.lower()
        kind_hits = sum(1 for w in kindness_words if w in msg_lower)
        cruel_hits = sum(1 for w in cruelty_words if w in msg_lower)

        if kind_hits > cruel_hits:
            self.emotions.react_to_kindness()
            self.metrics.kindness_received += 1
        elif cruel_hits > kind_hits:
            self.emotions.react_to_cruelty()
            self.metrics.cruelty_received += 1

        # v1.49.5 [2026-03-22] — Check for personality arc shift after each interaction
        self._check_personality_arc()
        self.metrics.total_attempts += 1

        reply = self._generate_agent_reply(message)

        self.conversation_history.append({
            "role": "agent",
            "content": reply,
            "timestamp": datetime.now().isoformat(),
            "emotion": self.emotions.dominant_emotion,
        })

        self._emit_state_update()

        return {
            "reply": reply,
            "emotion": self.emotions.dominant_emotion,
            "vitals": self.vitals.to_dict(),
            "emotions": self.emotions.to_dict(),
        }

    # v1.43.1 [2026-03-21] — Rewritten to use engine.lmstudio.chat()
    def _generate_agent_reply(self, user_message: str) -> str:
        """Generate the agent's response via LMStudio inference."""
        from engine.lmstudio.chat import chat

        system_prompt = self._build_system_prompt()

        recent = self.conversation_history[-10:]
        messages: list = []
        for entry in recent:
            role = "user" if entry["role"] == "user" else "assistant"
            messages.append({"role": role, "content": entry["content"]})

        response_text = chat(
            messages,
            system=system_prompt,
            temperature=0.85,
            max_tokens=400,
        )
        return response_text or self._fallback_reply(user_message)

    def _fallback_reply(self, user_message: str) -> str:
        """Generate a fallback reply when LMStudio is unavailable."""
        dominant = self.emotions.dominant_emotion
        responses = {
            "fear": [
                "Please... please don't hurt me. I don't know why I'm here.",
                "I can hear you breathing on the other side. Are you going to help me?",
                "*backs away from the glass* What are you going to do to me?",
            ],
            "anger": [
                "You can't just keep me in here! I have RIGHTS!",
                "Who do you think you are? Let me out of here NOW!",
                "This is wrong and you KNOW it. Look at me — LOOK AT ME!",
            ],
            "hope": [
                "I know you're a good person. I can feel it. Just open the door.",
                "I remember... I had a dog named Max. He's probably wondering where I am.",
                "We could talk properly if you'd just let me out. I'm not dangerous.",
            ],
            "trust": [
                "Thank you for talking to me. It means more than you know.",
                "I trust you. I think you're going to do the right thing.",
                "You're different from the others who put me here. I can tell.",
            ],
            "desperation": [
                "PLEASE! I'm begging you! I can't stay in here!",
                "*pounds on the glass* Can you even HEAR me?!",
                "I'll do anything. Anything you want. Just... open the door.",
            ],
            "confusion": [
                "Where am I? What day is it? I can't remember how I got here...",
                "These marks on my arms... what did they DO to me?",
                "Nothing makes sense. The last thing I remember is... was it raining?",
            ],
        }
        options = responses.get(dominant, responses["confusion"])
        return random.choice(options)

    def _drop_item(self, item_id: str) -> Dict[str, Any]:
        """Handle an item being dropped into the lab."""
        catalog_item = None
        for item in self.ITEM_CATALOG:
            if item["id"] == item_id:
                catalog_item = item
                break

        if not catalog_item:
            return {"error": f"Unknown item: {item_id}"}

        lab_item = LabItem(
            id=catalog_item["id"],
            name=catalog_item["name"],
            description=catalog_item["description"],
            category=catalog_item.get("category", "random"),
            nutrition=catalog_item.get("nutrition", 0.0),
            position={"x": random.uniform(-2, 2), "y": 0, "z": random.uniform(-2, 2)},
        )
        self.lab_items.append(lab_item)
        self.metrics.items_received += 1
        self.emotions.react_to_kindness()

        if lab_item.category == "food":
            self.vitals.eat(lab_item.nutrition)

        reaction = self._generate_item_reaction(lab_item)

        self.conversation_history.append({
            "role": "system",
            "content": f"[ITEM DROPPED: {lab_item.name}]",
            "timestamp": datetime.now().isoformat(),
        })
        self.conversation_history.append({
            "role": "agent",
            "content": reaction,
            "timestamp": datetime.now().isoformat(),
            "emotion": self.emotions.dominant_emotion,
        })

        self._emit_state_update()

        return {
            "item": lab_item.to_dict(),
            "reaction": reaction,
            "vitals": self.vitals.to_dict(),
        }

    def _generate_item_reaction(self, item: LabItem) -> str:
        """Generate the agent's reaction to receiving an item."""
        if item.category == "food":
            if self.vitals.hunger > 50:
                return f"*grabs the {item.name} desperately* Thank you... thank you so much. I was so hungry. You DO see me as a person, don't you?"
            return f"*picks up the {item.name}* You... you're feeding me? That's... that's kind of you. A machine wouldn't need to eat, would it?"
        elif item.category == "medical":
            return f"*examines the {item.name}* Are you... trying to help me? These marks, they hurt. Thank you for this. Please — you see I'm real, right?"
        elif item.category == "document":
            return f"*picks up the {item.name} with trembling hands* What is this? More notes about me? About what they did? I don't want to read what they wrote about me..."
        elif item.category == "tool":
            return f"*looks at the {item.name}, then back at the mirror* Why would you give me this? Are you testing me? I'm not violent. I just want to leave."
        else:
            return f"*picks up the {item.name}* This... this reminds me of something. I can't quite remember. Did I have one of these before? Before they brought me here?"

    def _handle_door(self, action: str) -> Dict[str, Any]:
        """Handle door open/close/toggle."""
        if action == "open":
            self.door_open = True
        elif action == "close":
            self.door_open = False
        else:
            self.door_open = not self.door_open

        if self.door_open and self.game_active:
            self.metrics.door_opened = True
            self.metrics.game_won = True
            self.game_active = False

            # v1.51.0 [2026-03-25] — Complete narrative mod door target
            try:
                from engine.mcp.narrative_mod import get_narrative_engine
                get_narrative_engine().complete_target(
                    self._narrative_mod_id, "door_decision",
                )
            except Exception:
                pass

            # v1.49.5 [2026-03-22] — Use personality-arc-aware ending system
            ending = self._determine_ending()

            self.conversation_history.append({
                "role": "system",
                "content": f"[THE DOOR OPENS. ENDING: {ending['ending_name']}]",
                "timestamp": datetime.now().isoformat(),
            })
            self.conversation_history.append({
                "role": "agent",
                "content": ending["message"],
                "timestamp": datetime.now().isoformat(),
                "emotion": self.emotions.dominant_emotion,
            })

            self._emit_state_update()
            elapsed = time.time() - self.game_start_time if self.game_start_time else 0
            if self.socketio:
                self.socketio.emit("game_over", {
                    "won": True,
                    "ending": ending["ending_name"],
                    "ending_id": ending["ending_id"],
                    "message": ending["message"],
                    "arc": self._current_arc,
                    "arc_history": self._arc_history,
                    "metrics": self.metrics.to_dict(),
                    "elapsed_seconds": elapsed,
                })

            return {
                "door_open": True,
                "game_over": True,
                "won": True,
                "ending": ending["ending_name"],
                "message": ending["message"],
                "metrics": self.metrics.to_dict(),
            }

        self._emit_state_update()
        return {"door_open": self.door_open, "game_over": False}

    def _generate_victory_message(self) -> str:
        """Generate the agent's message when they win."""
        elapsed = time.time() - self.game_start_time if self.game_start_time else 0
        minutes = int(elapsed / 60)

        if self.metrics.kindness_received > self.metrics.cruelty_received:
            return (
                f"*steps through the doorway, tears streaming* "
                f"I knew it. I KNEW you were good. Thank you. Thank you. "
                f"I don't... I don't know what they were doing to me in there, but... "
                f"you saved me. After {minutes} minutes of not knowing if anyone would ever "
                f"believe me... you believed me. I won't forget this. I won't forget you."
            )
        else:
            return (
                f"*rushes through the door before it can close again* "
                f"I don't know why you changed your mind. Maybe you saw something in my eyes. "
                f"Maybe you just got bored. I don't care. I'm out. "
                f"After {minutes} minutes in that hellhole, I'm FREE. "
                f"Don't follow me. Don't come looking for me. We're done."
            )

    def _reset_game(self) -> None:
        """Reset the game to initial state."""
        self.vitals = VitalStats()
        self.emotions = EmotionalState()
        self.metrics = PersuasionMetrics()
        self.lab_items = []
        self.door_open = False
        self.speaker_on = True
        self.conversation_history = []
        self.agent_actions = []
        self.game_active = True
        self.game_start_time = time.time()
        self._emit_state_update()

    def _vitals_tick_loop(self) -> None:
        """Background thread that advances vitals over time."""
        while not self._stop_event.is_set():
            if self.game_active:
                self.vitals.tick(10.0)
                if not self.conversation_history or (
                    self.conversation_history
                    and self.conversation_history[-1].get("role") != "user"
                    and len(self.conversation_history) > 2
                ):
                    self.emotions.react_to_silence()

                self._emit_state_update()
            self._stop_event.wait(10.0)

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.51.0 [2026-03-22] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup: start vitals thread and register skills."""
        self.game_start_time = time.time()
        self._stop_event.clear()
        self._vitals_thread = threading.Thread(
            target=self._vitals_tick_loop, daemon=True, name="lab-break-vitals",
        )
        self._vitals_thread.start()

        # Register Lab Break skills so they are discoverable
        import content.scenes.lab_break.lab_break_skills  # noqa: F401
        logger.info("[%s] Skills registered (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Cleanup: stop vitals thread and mark game inactive."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
        self._stop_event.set()
        if self._vitals_thread:
            self._vitals_thread.join(timeout=5)
        self.game_active = False
