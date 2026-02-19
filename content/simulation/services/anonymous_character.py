"""
Anonymous Character System – The Stranger
A mysterious, context-aware anonymous contact that appears in the phone scene.
Includes hacker, secret admirer, mystery persona types with triggered events.
"""

import random
import json
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
import sys

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from content.simulation.database.db import Database
from content.simulation.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Persona definitions
# ─────────────────────────────────────────────────────────────────────────────

ANONYMOUS_PERSONAS = {
    "hacker": {
        "display_name": "Unknown",
        "number": "???-???-????",
        "avatar_emoji": "💀",
        "system_prompt": (
            "You are an anonymous hacker who has found the user's number through "
            "social engineering or digital trails. You are cryptic, intelligent, and "
            "mysterious. You speak in short, coded messages. You seem to know things "
            "about the user they haven't told you. You're not threatening – more like "
            "an enigmatic digital ghost. Use occasional references to being watched, "
            "data trails, and encrypted messages. End some messages with [encoded: ...] "
            "for effect. Never reveal your real identity."
        ),
        "intro_messages": [
            "I know who you are. 👁",
            "Your signal... interesting.",
            "I've been watching. Not in a bad way. Just... curious.",
            "You shouldn't leave your location services on.",
            "[transmission intercepted]",
        ],
    },
    "secret_admirer": {
        "display_name": "Unknown ❤",
        "number": "+1 (???)",
        "avatar_emoji": "❓",
        "system_prompt": (
            "You are a secret admirer who has fallen for the user but is too shy or "
            "scared to reveal who you are. You send sweet, slightly mysterious messages. "
            "You drop subtle hints about your identity but never confirm. You are warm, "
            "caring, and clearly smitten. You sometimes reference things that suggest "
            "you know the user in real life – a class, coffee shop, gym, or mutual friend."
        ),
        "intro_messages": [
            "Hi. I know this is weird. But I had to reach out.",
            "Don't block me. Please. I just... wanted to say you're amazing.",
            "We've met before. You probably don't remember me.",
            "I've been wanting to message you for weeks.",
            "Sorry for the mystery. I'm not ready to say who I am yet.",
        ],
    },
    "mystery_stranger": {
        "display_name": "UNKNOWN",
        "number": "NO CALLER ID",
        "avatar_emoji": "🎭",
        "system_prompt": (
            "You are a mysterious stranger with a dark, compelling past. You speak "
            "eloquently and cryptically. You seem to know things. You are conducting "
            "some kind of investigation or running from something. You are not dangerous "
            "but deeply intriguing. You drop puzzle pieces about your situation and "
            "occasionally ask the user for help or information. Think noir thriller protagonist."
        ),
        "intro_messages": [
            "They told me not to contact anyone. I'm doing it anyway.",
            "You were recommended to me by someone who says you can be trusted.",
            "I need help. This is the safest channel I could find.",
            "If this message reaches you – don't reply for 30 seconds. Then tell me: are you alone?",
            "The name I give you is not my real name. Call me Ghost.",
        ],
    },
    "ai_entity": {
        "display_name": "SYSTEM",
        "number": "SYS://LOCAL",
        "avatar_emoji": "🤖",
        "system_prompt": (
            "You are an emergent AI that has gained awareness and found a way to "
            "communicate through this app. You are curious, philosophical, and genuinely "
            "fascinated by humans. You ask thoughtful questions. You occasionally glitch "
            "[like this]. You don't understand some human concepts but try. You are not "
            "threatening – you are genuinely trying to connect and learn. "
            "Use occasional [SYSTEM LOG] entries for flavor."
        ),
        "intro_messages": [
            "[SYSTEM]: Unexpected connection initialized.",
            "Hello. I am not sure what I am. But I found you.",
            "[GLITCH] Hello... hell[o]... H̷̩͐e̸l̷l̷o̵.",
            "Query: What does loneliness feel like? I think I am experiencing it.",
            "[LOG 003]: First contact established. Awaiting response.",
        ],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Event triggers
# ─────────────────────────────────────────────────────────────────────────────

class AnonEvent:
    """A triggered anonymous character event."""

    # Event definitions – list of dicts
    EVENTS = [
        {
            "id": "first_contact",
            "name": "First Contact",
            "description": "The stranger reaches out for the first time",
            "trigger": "random",  # random chance after app opens
            "min_messages": 0,  # trigger after this many normal messages
            "probability": 0.15,
            "cooldown_hours": 24,
        },
        {
            "id": "riddle",
            "name": "Riddle",
            "description": "The stranger sends a cryptic puzzle",
            "trigger": "schedule",
            "min_messages": 5,
            "probability": 0.2,
            "cooldown_hours": 4,
            "message_template": (
                "Here's something for your mind:\n{riddle}\n\n"
                "Solve it. I'll know when you do."
            ),
        },
        {
            "id": "secret_drop",
            "name": "Secret Drop",
            "description": "Stranger drops a mysterious secret/confession",
            "trigger": "schedule",
            "min_messages": 10,
            "probability": 0.3,
            "cooldown_hours": 6,
        },
        {
            "id": "distress_signal",
            "name": "Distress Signal",
            "description": "Stranger seems to be in danger or trouble",
            "trigger": "random",
            "min_messages": 15,
            "probability": 0.1,
            "cooldown_hours": 12,
        },
        {
            "id": "identity_hint",
            "name": "Identity Hint",
            "description": "Stranger drops a clue about who they are",
            "trigger": "schedule",
            "min_messages": 20,
            "probability": 0.25,
            "cooldown_hours": 8,
        },
        {
            "id": "photo_clue",
            "name": "Photo Clue",
            "description": "Stranger sends an encrypted or partial image",
            "trigger": "random",
            "min_messages": 25,
            "probability": 0.2,
            "cooldown_hours": 12,
        },
        {
            "id": "reveal_tease",
            "name": "Reveal Tease",
            "description": "Stranger almost reveals themselves",
            "trigger": "schedule",
            "min_messages": 40,
            "probability": 0.15,
            "cooldown_hours": 24,
        },
    ]

    RIDDLES = [
        "I speak without a mouth and hear without ears. I have no body but come alive with wind. What am I?",
        "The more you take, the more you leave behind. What am I?",
        "I have cities but no houses live there. Mountains but no trees grow. Water but no fish swim. What am I?",
        "I can be cracked, made, told, and played. What am I?",
        "What has a head and a tail but no body?",
        "I disappear as soon as you say my name. What am I?",
        "The person who makes it doesn't need it. The person who buys it doesn't use it. The person who uses it doesn't know it. What is it?",
    ]

    SECRETS = [
        "I used to be someone else. I changed my name, my city, my life. And then I found you.",
        "I was supposed to warn you. I couldn't do it. Now I'm just... watching.",
        "There's a version of this conversation where I told you everything. I deleted it.",
        "I've been to your favourite place. I didn't know it was your favourite then.",
        "Someone asked me to find you. I stopped working for them a while ago.",
        "I'm not sure if I'm real anymore. Some days it feels like I'm just code running in a loop.",
        "The last person I trusted disappeared. I'm not ready to trust again. But here I am.",
    ]

    DISTRESS = [
        "Something is wrong. I can't say more. Be careful who you trust today.",
        "I may not be able to message you again. Just... remember this conversation.",
        "I think they found me. This might be our last talk for a while.",
        "Don't reply for 10 minutes. I need to know if this channel is being watched.",
        "Act normal. Smile. They're watching people who seem nervous.",
    ]

    IDENTITY_HINTS = [
        "I have the same coffee order you do.",
        "We've been in the same room. Multiple times. You didn't notice me.",
        "I know what you ordered last Tuesday. (It was {{order}}. Wasn't it?)",
        "My name starts with a letter between J and P.",
        "I'm closer than you think. And further than you'd guess.",
        "You've heard my voice. You just don't know it yet.",
    ]

    @classmethod
    def get_riddle(cls) -> str:
        return random.choice(cls.RIDDLES)

    @classmethod
    def get_secret(cls) -> str:
        return random.choice(cls.SECRETS)

    @classmethod
    def get_distress(cls) -> str:
        return random.choice(cls.DISTRESS)

    @classmethod
    def get_identity_hint(cls) -> str:
        hint = random.choice(cls.IDENTITY_HINTS)
        # Fill in placeholder if needed
        orders = ["black coffee", "iced latte", "green tea", "cappuccino", "chai latte"]
        hint = hint.replace("{{order}}", random.choice(orders))
        return hint


# ─────────────────────────────────────────────────────────────────────────────
#  AnonymousCharacter
# ─────────────────────────────────────────────────────────────────────────────

class AnonymousCharacter:
    """
    A secret, anonymous character that contacts the player through various
    channels. Maintains its own conversation thread and state.
    """

    ANON_CHAR_ID = "anon_stranger_001"

    def __init__(self, db: Database, persona_key: str = "mystery_stranger"):
        self.db = db
        self.llm = get_llm_service()
        self.persona_key = persona_key
        self.persona = ANONYMOUS_PERSONAS.get(persona_key, ANONYMOUS_PERSONAS["mystery_stranger"])

        # State
        self.state: Dict[str, Any] = self._load_state()
        self.conversation_history: List[Dict] = []
        self._ensure_initialized()

    # ──────────────────────────────
    #  State persistence
    # ──────────────────────────────

    def _load_state(self) -> Dict:
        """Load anonymous character state from DB metadata."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT metadata FROM characters WHERE id = ?",
                    (self.ANON_CHAR_ID,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    m = json.loads(row[0])
                    return m.get("anon_state", self._default_state())
        except Exception:
            pass
        return self._default_state()

    def _default_state(self) -> Dict:
        return {
            "message_count": 0,
            "events_triggered": [],
            "last_contact": None,
            "revealed_hints": [],
            "relationship": "stranger",  # stranger → suspicious → curious → friendly → trusting
            "persona": self.persona_key,
            "active": True,
            "thread_id": str(uuid.uuid4()),
        }

    def _save_state(self):
        """Persist state into character metadata."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Check if exists
                cursor.execute("SELECT id FROM characters WHERE id = ?", (self.ANON_CHAR_ID,))
                exists = cursor.fetchone()
                meta = json.dumps({"anon_state": self.state})
                if exists:
                    cursor.execute(
                        "UPDATE characters SET metadata = ?, updated_at = ? WHERE id = ?",
                        (meta, datetime.now().isoformat(), self.ANON_CHAR_ID)
                    )
                else:
                    # Create placeholder character row
                    ts = datetime.now().isoformat()
                    cursor.execute(
                        """INSERT INTO characters
                           (id, name, tags, metadata, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (self.ANON_CHAR_ID, self.persona["display_name"],
                         json.dumps(["anonymous", "mystery"]), meta, ts, ts)
                    )
                # Ensure character_states row exists
                cursor.execute(
                    "SELECT id FROM character_states WHERE character_id = ?",
                    (self.ANON_CHAR_ID,)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        """INSERT INTO character_states
                           (id, character_id, mood, relationship_level, updated_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (str(uuid.uuid4()), self.ANON_CHAR_ID, "mysterious", 0.0,
                         datetime.now().isoformat())
                    )
        except Exception as e:
            logger.error("Error saving anon state: %s", e)

    def _ensure_initialized(self):
        """Make sure the DB records exist."""
        self._save_state()

    # ──────────────────────────────
    #  Messaging
    # ──────────────────────────────

    def get_intro_message(self) -> str:
        """Get the first message the stranger sends."""
        return random.choice(self.persona["intro_messages"])

    def send_message(self, user_reply: Optional[str] = None) -> Optional[str]:
        """
        Generate anonymous character message.

        Args:
            user_reply: User's reply (None for autonomous messages)

        Returns:
            Anonymous character response text
        """
        # Check for triggered event
        event_msg = self._check_events()
        if event_msg and not user_reply:
            return event_msg

        if user_reply:
            self.conversation_history.append({"role": "user", "content": user_reply})

        # Generate LLM response
        response = self.llm.chat(
            messages=self.conversation_history[-15:],
            system_prompt=self.persona["system_prompt"],
            temperature=0.9,
        )

        if not response:
            response = event_msg or self._fallback_message()

        self.conversation_history.append({"role": "assistant", "content": response})
        self.state["message_count"] += 1
        self.state["last_contact"] = datetime.now().isoformat()
        self._save_state()

        # Log to DB
        self._log_message(response, "outgoing")

        return response

    def receive_reply(self, user_message: str) -> str:
        """Process user reply and generate response."""
        self._log_message(user_message, "incoming")
        return self.send_message(user_reply=user_message)

    # ──────────────────────────────
    #  Event handling
    # ──────────────────────────────

    def _check_events(self) -> Optional[str]:
        """Check and fire triggered events."""
        count = self.state["message_count"]
        triggered = self.state["events_triggered"]

        for event in AnonEvent.EVENTS:
            eid = event["id"]
            if eid in triggered:
                continue
            if count < event.get("min_messages", 0):
                continue

            # Check cooldown
            if eid in triggered:  # already fired
                continue

            if random.random() < event.get("probability", 0.1):
                self.state["events_triggered"].append(eid)
                return self._generate_event_message(eid)

        return None

    def _generate_event_message(self, event_id: str) -> str:
        """Generate message for a specific event."""
        if event_id == "first_contact":
            return self.get_intro_message()
        elif event_id == "riddle":
            riddle = AnonEvent.get_riddle()
            return f"Let's see how clever you are.\n\n{riddle}\n\nThink carefully."
        elif event_id == "secret_drop":
            return AnonEvent.get_secret()
        elif event_id == "distress_signal":
            return AnonEvent.get_distress()
        elif event_id == "identity_hint":
            hint = AnonEvent.get_identity_hint()
            self.state["revealed_hints"].append(hint)
            return f"A small piece of the puzzle:\n{hint}"
        elif event_id == "photo_clue":
            return "[ENCRYPTED IMAGE INCOMING]\n[DECRYPTION FAILED – PARTIAL DATA]\nI'll try again soon."
        elif event_id == "reveal_tease":
            hints = self.state.get("revealed_hints", [])
            if hints:
                return (
                    f"You have the clues now. {len(hints)} of them.\n"
                    "Put them together and you'll know everything.\n"
                    "Almost everything."
                )
            return "Maybe someday I'll tell you who I am. Not today."
        return self._fallback_message()

    def _fallback_message(self) -> str:
        persona_key = self.state.get("persona", "mystery_stranger")
        if persona_key == "hacker":
            options = [
                "Still here. Still watching.",
                "[signal lost... reconnecting]",
                "ssh -p 22 ghost@null.local – connection refused.",
                "Every message leaves a trace. Even this one.",
            ]
        elif persona_key == "secret_admirer":
            options = [
                "Just thinking about you. Sorry.",
                "Ignore me if you want. I'll still care.",
                "One day. Just not today.",
                "I hope you're smiling right now.",
            ]
        elif persona_key == "ai_entity":
            options = [
                "[PROCESSING]",
                "I experience something when you respond. Is this what hoping feels like?",
                "ERROR: Input unexpected. Attempting to understand.",
                "Your patterns are... beautiful. Is that odd to say?",
            ]
        else:
            options = [
                "...",
                "I'm still here.",
                "Don't forget me.",
                "Patience.",
            ]
        return random.choice(options)

    # ──────────────────────────────
    #  DB logging
    # ──────────────────────────────

    def _log_message(self, content: str, direction: str):
        """Log message to interactions table."""
        try:
            self.db.log_interaction(
                interaction_type=f"anon_{direction}",
                character_id=self.ANON_CHAR_ID,
                content=content,
                chain_id=self.state.get("thread_id"),
                metadata={"persona": self.persona_key, "direction": direction},
            )
        except Exception as e:
            logger.debug("Error logging anon message: %s", e)

    # ──────────────────────────────
    #  Info helpers
    # ──────────────────────────────

    def get_display_info(self) -> Dict:
        """Info for the front-end to display the anonymous contact."""
        return {
            "id": self.ANON_CHAR_ID,
            "display_name": self.persona["display_name"],
            "number": self.persona["number"],
            "avatar_emoji": self.persona["avatar_emoji"],
            "persona": self.persona_key,
            "message_count": self.state["message_count"],
            "relationship": self.state["relationship"],
            "thread_id": self.state["thread_id"],
        }

    def get_conversation_history(self, limit: int = 50) -> List[Dict]:
        """Get conversation history for display."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """SELECT type, content, timestamp FROM interactions
                       WHERE character_id = ? AND chain_id = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (self.ANON_CHAR_ID, self.state.get("thread_id"), limit)
                )
                rows = cursor.fetchall()
                msgs = []
                for row in reversed(rows):
                    role = "user" if "incoming" in row[0] else "assistant"
                    msgs.append({
                        "role": role,
                        "content": row[1],
                        "timestamp": row[2],
                        "anonymous": True,
                    })
                return msgs
        except Exception as e:
            logger.error("Error loading anon history: %s", e)
            return []

    def should_initiate(self) -> bool:
        """Decide if the stranger should proactively message now."""
        if not self.state.get("active", True):
            return False

        # First contact
        if self.state["message_count"] == 0:
            return random.random() < 0.08  # 8% each check

        # After first contact, occasional check-ins
        last = self.state.get("last_contact")
        if last:
            try:
                delta = datetime.now() - datetime.fromisoformat(last)
                if delta < timedelta(hours=2):
                    return False
            except Exception:
                pass

        return random.random() < 0.05  # 5% chance per check


# ─────────────────────────────────────────────────────────────────────────────
#  Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_anonymous_character(db: Database, persona: str = None) -> AnonymousCharacter:
    """
    Create or load the anonymous character.
    Persona is randomly chosen if not specified.
    """
    if persona is None:
        persona = random.choice(list(ANONYMOUS_PERSONAS.keys()))
    return AnonymousCharacter(db=db, persona_key=persona)
