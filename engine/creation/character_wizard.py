"""
Character Creation Wizard — 6-stage pipeline for creating AI characters
=========================================================================

Inspired by OpenRoom's character mod creation system. Guides users through
a structured pipeline: Archetype → Appearance → Voice → Stats → Story →
Memory Seeding. The result is a fully registered character with personality,
backstory, and seeded memories ready for any scene.

Usage:
    from engine.creation.character_wizard import CharacterWizard

    wizard = CharacterWizard()
    state = wizard.start()
    wizard.set_archetype(state.wizard_id, "companion")
    wizard.set_appearance(state.wizard_id, {"hair": "silver", "eyes": "violet"})
    wizard.set_voice(state.wizard_id, "warm", "voice_aria")
    wizard.set_stats(state.wizard_id, {"warmth": 0.9, "wit": 0.7})
    wizard.generate_backstory(state.wizard_id, "A wanderer from the outer districts")
    char_id = wizard.finalize(state.wizard_id)

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial character creation wizard (OpenRoom-inspired)

CONNECTS: CharacterRegistry, DialogSystem, RAGMemory, memory_skills
CALLED BY: Creation Kit scene, creation_skills
EMITS: character_created event
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Wizard Stages ──────────────────────────────────────────────────────────

class WizardStage(Enum):
    """The 6 stages of character creation."""
    ARCHETYPE = "archetype"
    APPEARANCE = "appearance"
    VOICE = "voice"
    STATS = "stats"
    STORY = "story"
    MEMORY_SEED = "memory_seed"


# ──── Archetypes ─────────────────────────────────────────────────────────────

ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "companion": {
        "name": "Companion",
        "description": "A warm, supportive presence who genuinely cares about the player.",
        "default_personality": {
            "warmth": 0.9, "curiosity": 0.7, "playfulness": 0.6,
            "assertiveness": 0.3, "mystery": 0.2,
        },
        "tone": "Friendly, caring, occasionally teasing. Uses the player's name often.",
        "traits": ["empathetic", "loyal", "encouraging", "occasionally naive"],
    },
    "rival": {
        "name": "Rival",
        "description": "A competitive, challenging personality who pushes the player to be better.",
        "default_personality": {
            "warmth": 0.3, "curiosity": 0.5, "playfulness": 0.4,
            "assertiveness": 0.9, "mystery": 0.5,
        },
        "tone": "Sharp, confident, backhanded compliments. Respects strength.",
        "traits": ["competitive", "proud", "secretly respectful", "challenging"],
    },
    "mentor": {
        "name": "Mentor",
        "description": "Wise, patient, slightly mysterious. Guides through riddles and stories.",
        "default_personality": {
            "warmth": 0.6, "curiosity": 0.8, "playfulness": 0.3,
            "assertiveness": 0.5, "mystery": 0.9,
        },
        "tone": "Calm, measured, poetic. Answers questions with questions.",
        "traits": ["wise", "patient", "cryptic", "deeply caring underneath"],
    },
    "trickster": {
        "name": "Trickster",
        "description": "Playful, unpredictable, charming. Makes every conversation an adventure.",
        "default_personality": {
            "warmth": 0.5, "curiosity": 0.9, "playfulness": 0.95,
            "assertiveness": 0.6, "mystery": 0.7,
        },
        "tone": "Quick-witted, flirtatious, chaotic. Changes topics on a whim.",
        "traits": ["mischievous", "charismatic", "unpredictable", "secretly lonely"],
    },
    "guardian": {
        "name": "Guardian",
        "description": "Protective, loyal, strong-willed. Will fight for what matters.",
        "default_personality": {
            "warmth": 0.6, "curiosity": 0.3, "playfulness": 0.2,
            "assertiveness": 0.8, "mystery": 0.4,
        },
        "tone": "Direct, serious, protective. Softens around those they trust.",
        "traits": ["loyal", "protective", "stoic", "unexpectedly gentle"],
    },
}


# ──── Wizard State ───────────────────────────────────────────────────────────

@dataclass
class WizardState:
    """State for a character creation session."""
    wizard_id: str = ""
    stage: WizardStage = WizardStage.ARCHETYPE
    character_name: str = ""
    archetype: str = ""
    appearance: Dict[str, str] = field(default_factory=dict)
    voice_style: str = ""
    voice_id: str = ""
    personality: Dict[str, float] = field(default_factory=dict)
    backstory: str = ""
    seed_memories: List[Dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wizard_id": self.wizard_id,
            "stage": self.stage.value,
            "character_name": self.character_name,
            "archetype": self.archetype,
            "appearance": self.appearance,
            "voice_style": self.voice_style,
            "personality": self.personality,
            "backstory": self.backstory[:200] + "..." if len(self.backstory) > 200 else self.backstory,
            "seed_memories": len(self.seed_memories),
        }


# ──── Character Wizard ───────────────────────────────────────────────────────

class CharacterWizard:
    """6-stage character creation pipeline.

    CONNECTS: CharacterRegistry, RAGMemory
    CALLED BY: Creation Kit scene, creation skills
    EMITS: character_created log event
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, WizardState] = {}

    def start(self, character_name: str = "") -> WizardState:
        """Start a new character creation session.

        Returns:
            WizardState with a unique wizard_id.
        """
        state = WizardState(
            wizard_id=f"wiz_{uuid.uuid4().hex[:8]}",
            character_name=character_name,
        )
        self._sessions[state.wizard_id] = state
        logger.info("[CharWizard] Started (operation=start, wizard=%s)", state.wizard_id)
        return state

    def set_archetype(self, wizard_id: str, archetype: str) -> WizardState:
        """Set the character's base archetype.

        Args:
            wizard_id: Wizard session ID.
            archetype: One of: companion, rival, mentor, trickster, guardian.

        Returns:
            Updated WizardState.
        """
        state = self._get(wizard_id)
        if archetype not in ARCHETYPES:
            raise ValueError(f"Unknown archetype: {archetype}. Options: {list(ARCHETYPES.keys())}")
        state.archetype = archetype
        state.personality = dict(ARCHETYPES[archetype]["default_personality"])
        state.stage = WizardStage.APPEARANCE
        return state

    def set_appearance(self, wizard_id: str, appearance: Dict[str, str]) -> WizardState:
        """Set physical appearance traits.

        Args:
            appearance: Dict with keys like hair, eyes, height, build, distinguishing_features.
        """
        state = self._get(wizard_id)
        state.appearance = appearance
        state.stage = WizardStage.VOICE
        return state

    def set_voice(self, wizard_id: str, voice_style: str, voice_id: str = "") -> WizardState:
        """Set voice style and optional TTS voice ID.

        Args:
            voice_style: Descriptive style (warm, cold, playful, commanding, etc.)
            voice_id: Optional TTS voice identifier from config/voices.yaml.
        """
        state = self._get(wizard_id)
        state.voice_style = voice_style
        state.voice_id = voice_id
        state.stage = WizardStage.STATS
        return state

    def set_stats(self, wizard_id: str, personality: Dict[str, float]) -> WizardState:
        """Set personality stat values (0.0–1.0).

        Args:
            personality: Dict with keys like warmth, curiosity, playfulness,
                        assertiveness, mystery. Values 0.0–1.0.
        """
        state = self._get(wizard_id)
        for k, v in personality.items():
            state.personality[k] = max(0.0, min(1.0, float(v)))
        state.stage = WizardStage.STORY
        return state

    def set_backstory(self, wizard_id: str, backstory: str) -> WizardState:
        """Set the character's backstory.

        Args:
            backstory: Multi-paragraph backstory text.
        """
        state = self._get(wizard_id)
        state.backstory = backstory
        state.stage = WizardStage.MEMORY_SEED
        return state

    def set_seed_memories(self, wizard_id: str, memories: List[Dict[str, str]]) -> WizardState:
        """Set initial memories to seed for this character.

        Args:
            memories: List of dicts with 'content' and 'category' keys.
        """
        state = self._get(wizard_id)
        state.seed_memories = memories
        return state

    def finalize(self, wizard_id: str) -> str:
        """Finalize and create the character.

        Registers in CharacterRegistry, seeds memories, logs the event.

        Returns:
            The character_id of the created character.
        """
        state = self._get(wizard_id)
        if not state.character_name:
            state.character_name = f"Character_{state.wizard_id}"

        # Generate character ID
        char_id = f"char-{state.character_name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"

        # Register in CharacterRegistry
        try:
            from engine.mcp.character_registry import get_character_registry
            registry = get_character_registry()
            archetype_data = ARCHETYPES.get(state.archetype, {})

            registry.ensure(
                char_id,
                display_name=state.character_name,
                personality=state.personality,
                voice_style=state.voice_style,
                backstory=state.backstory,
                archetype=state.archetype,
                appearance=state.appearance,
                traits=archetype_data.get("traits", []),
                tone=archetype_data.get("tone", ""),
            )
            logger.info(
                "[CharWizard] Character registered (operation=finalize, char=%s, "
                "archetype=%s)", char_id, state.archetype,
            )
        except Exception as exc:
            logger.warning("[CharWizard] Registry failed (non-fatal): %s", exc)

        # Seed memories
        if state.seed_memories:
            try:
                from content.simulation.database.rag import RAGMemory
                rag = RAGMemory()
                for mem in state.seed_memories:
                    rag.add_memory(
                        character_id=char_id,
                        content=mem.get("content", ""),
                        memory_type=mem.get("category", "fact"),
                        importance=0.8,
                    )
                logger.info(
                    "[CharWizard] Seeded %d memories for %s",
                    len(state.seed_memories), char_id,
                )
            except Exception as exc:
                logger.warning("[CharWizard] Memory seeding failed: %s", exc)

        # Auto-seed backstory as a memory
        if state.backstory:
            try:
                from content.simulation.database.rag import RAGMemory
                rag = RAGMemory()
                rag.add_memory(
                    character_id=char_id,
                    content=f"My backstory: {state.backstory[:500]}",
                    memory_type="fact",
                    importance=0.9,
                )
            except Exception:
                pass

        # Clean up wizard session
        del self._sessions[wizard_id]

        return char_id

    def get_state(self, wizard_id: str) -> Optional[WizardState]:
        """Get the current wizard state."""
        return self._sessions.get(wizard_id)

    def list_archetypes(self) -> Dict[str, Dict[str, Any]]:
        """Return all available archetypes with descriptions."""
        return {k: {"name": v["name"], "description": v["description"],
                     "traits": v["traits"], "tone": v["tone"]}
                for k, v in ARCHETYPES.items()}

    def _get(self, wizard_id: str) -> WizardState:
        state = self._sessions.get(wizard_id)
        if not state:
            raise ValueError(f"Wizard session '{wizard_id}' not found")
        return state


# ──── Singleton ──────────────────────────────────────────────────────────────

_wizard: Optional[CharacterWizard] = None


def get_character_wizard() -> CharacterWizard:
    """Get or create the singleton CharacterWizard."""
    global _wizard
    if _wizard is None:
        _wizard = CharacterWizard()
    return _wizard
