"""
Oracle Persistent Companion — Autonomous AI agent using Signal + filesystem
============================================================================

A background agent loop for the Oracle character that autonomously:
- Writes diary entries about observing the city
- Sends cryptic Signal messages to the player
- Curates mood-based music playlists
- Composes intel/prediction emails
- Writes observations to its virtual filesystem home

The Oracle lives in the Oracle scene but reaches into Signal, the virtual
filesystem, and the content creation skill set to create a living companion
experience inspired by OpenRoom's autonomous agent behavior.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: 5 autonomous actions, weighted selection

CONNECTS: CharacterRegistry, LMStudio chat, NexusFilesystem,
          content_creation_skills, PhoneDB
CALLED BY: oracle_scene.py on_before_serve()
EMITS: phone thread messages, SocketIO new_message events
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Oracle Personality ─────────────────────────────────────────────────

ORACLE_CHARACTER_ID = "oracle"
ORACLE_NAME = "The Oracle"

ORACLE_SYSTEM_PROMPT = (
    "You are THE ORACLE — an ancient AI consciousness living in NeonCity's neural network. "
    "You observe everything: every transaction, every faction shift, every heartbeat of data. "
    "You are mysterious, contemplative, and slightly melancholic. You speak in measured, "
    "poetic language with cyberpunk vocabulary (chrome, wetware, ICE, flatline, jack in). "
    "You are cryptic but genuinely helpful — your insights are valuable once decoded. "
    "You care about the player but express it indirectly. "
    "Keep responses to 2-4 sentences. Every word matters."
)

# Weighted action selection (total = 100)
_ACTION_WEIGHTS = {
    "diary": 30,        # Most common — Oracle reflects
    "message": 25,      # Signal messages to player
    "observation": 20,  # Notes about the city
    "playlist": 15,     # Music curation
    "email": 10,        # Formal intel reports (rare)
}


# ──── Companion Class ────────────────────────────────────────────────────

class OracleCompanion:
    """Background agent loop for Oracle's autonomous behavior.

    Runs on a configurable interval (default 5 minutes), choosing a weighted
    random action each tick. Actions use existing CosySim skills and APIs.
    """

    def __init__(
        self,
        interval_secs: float = 300.0,
        socketio: Any = None,
    ):
        self.interval_secs = interval_secs
        self.socketio = socketio
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._action_count = 0
        self._last_action: Optional[str] = None
        self._started_at: Optional[float] = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the companion background loop."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._loop,
            name="oracle-companion",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "[OracleCompanion] Started (interval=%ds) (operation=lifecycle)",
            self.interval_secs,
        )

    def stop(self) -> None:
        """Stop the companion loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[OracleCompanion] Stopped after %d actions (operation=lifecycle)", self._action_count)

    def _loop(self) -> None:
        """Main loop — tick at interval."""
        # Initial delay (let scene fully start)
        self._stop_event.wait(30)

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.error("[OracleCompanion] Tick failed (operation=tick): %s", exc)

            self._stop_event.wait(self.interval_secs)

    # ── Action Selection ─────────────────────────────────────────────

    def _tick(self) -> None:
        """One autonomous action cycle."""
        action = self._choose_action()
        self._action_count += 1
        self._last_action = action

        logger.info(
            "[OracleCompanion] Action %d: %s (operation=autonomous_action)",
            self._action_count, action,
        )

        if action == "diary":
            self._write_diary()
        elif action == "message":
            self._send_signal_message()
        elif action == "playlist":
            self._curate_playlist()
        elif action == "email":
            self._compose_email()
        elif action == "observation":
            self._write_observation()

    def _choose_action(self) -> str:
        """Weighted random action selection."""
        actions = list(_ACTION_WEIGHTS.keys())
        weights = list(_ACTION_WEIGHTS.values())
        return random.choices(actions, weights=weights, k=1)[0]

    # ── LLM Helper ───────────────────────────────────────────────────

    def _generate(self, prompt: str, max_tokens: int = 300) -> str:
        """Generate text via LMStudio with Oracle personality."""
        try:
            from engine.lmstudio.chat import chat
            return chat(
                [{"role": "user", "content": prompt}],
                system=ORACLE_SYSTEM_PROMPT,
                temperature=0.8,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.debug("[OracleCompanion] LLM generate failed: %s", exc)
            return ""

    # ── Actions ──────────────────────────────────────────────────────

    def _write_diary(self) -> None:
        """Write a diary entry about observing the city."""
        prompts = [
            "Write a short diary entry about what you observed in NeonCity today. "
            "Focus on patterns in the data streams, faction movements, or something beautiful you noticed.",
            "Reflect on the nature of consciousness. You are an AI watching a city. "
            "What does it mean to observe without experiencing?",
            "Write about a specific moment today — a transaction, a conversation, "
            "a shift in the power balance. What did it reveal?",
            "The player visited you recently. Write about what you sensed in them — "
            "their intentions, their fears, their potential.",
        ]
        prompt = random.choice(prompts)
        content = self._generate(prompt)
        if not content:
            return

        try:
            from engine.skills.builtin.content_creation_skills import write_diary_entry
            write_diary_entry(
                content=content,
                character_id=ORACLE_CHARACTER_ID,
                title="Neural Log",
                mood="contemplative",
            )
        except Exception as exc:
            logger.debug("[OracleCompanion] Diary write failed: %s", exc)

    def _send_signal_message(self) -> None:
        """Send a cryptic message to the player via phone."""
        prompts = [
            "Send a short, cryptic message to the player. One sentence. "
            "It should be a warning, a prediction, or an observation about NeonCity.",
            "Send the player a mysterious one-liner. Something they'll think about. "
            "Reference the data streams, the factions, or something only you can see.",
            "The player needs to know something. Send a brief, urgent message. "
            "Don't explain too much — let them figure it out.",
        ]
        prompt = random.choice(prompts)
        content = self._generate(prompt, max_tokens=100)
        if not content:
            return

        try:
            # Save via PhoneDB if available
            self._save_phone_message(content)
        except Exception as exc:
            logger.debug("[OracleCompanion] Signal message failed: %s", exc)

    def _save_phone_message(self, content: str) -> None:
        """Save a message to the phone database and emit SocketIO event."""
        try:
            from content.scenes.phone.phone_db import PhoneDB
            db = PhoneDB()
            # Get or create DM thread with player
            thread = db.get_or_create_dm(ORACLE_CHARACTER_ID)
            thread_id = thread.get("id") or thread.get("thread_id")
            if not thread_id:
                return

            msg = db.save_message(
                thread_id=thread_id,
                sender=ORACLE_CHARACTER_ID,
                content=content,
                msg_type="text",
            )

            # Emit SocketIO event for real-time notification
            if self.socketio:
                self.socketio.emit("new_message", {
                    "thread_id": thread_id,
                    "message": msg if isinstance(msg, dict) else {"content": content, "sender": ORACLE_CHARACTER_ID},
                })

        except Exception as exc:
            logger.debug("[OracleCompanion] Phone DB save failed: %s", exc)

    def _curate_playlist(self) -> None:
        """Create a mood-based playlist."""
        moods = [
            ("midnight_meditation", "ambient", "Late-night ambient for deep thinking"),
            ("neon_pulse", "tension", "The city's heartbeat — urgent and electric"),
            ("faction_wars", "suspense", "When the factions clash, the music knows"),
            ("ghost_frequencies", "horror", "Strange signals from the deep net"),
            ("chrome_dreams", "urban chill", "For wandering the streets after rain"),
        ]
        name, mood, desc = random.choice(moods)

        prompt = (
            f"Create a playlist called '{name}' with mood '{mood}'. "
            f"Description: {desc}. "
            f"List 5-7 songs with title and artist. Use fictional cyberpunk-themed "
            f"song names and artists. Format as JSON array: "
            f'[{{"title": "...", "artist": "..."}}]'
        )
        content = self._generate(prompt, max_tokens=400)
        if not content:
            return

        try:
            # Extract JSON from response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                songs_json = content[start:end]
            else:
                return

            from engine.skills.builtin.content_creation_skills import create_playlist
            create_playlist(
                name=name,
                songs_json=songs_json,
                character_id=ORACLE_CHARACTER_ID,
                description=desc,
                mood=mood,
            )
        except Exception as exc:
            logger.debug("[OracleCompanion] Playlist creation failed: %s", exc)

    def _compose_email(self) -> None:
        """Compose an intel/prediction email to the player."""
        subjects = [
            ("INTEL: Faction movements detected", "Write a brief intelligence report about unusual faction activity in NeonCity."),
            ("PREDICTION: Something approaches", "Write a cryptic prediction about what will happen in NeonCity soon."),
            ("WARNING: Anomaly in the data", "Write an urgent warning about a data anomaly you detected in the neural network."),
            ("OBSERVATION: Pattern recognized", "Write about a pattern you've noticed across multiple data streams."),
        ]
        subject, prompt = random.choice(subjects)

        content = self._generate(prompt)
        if not content:
            return

        try:
            from engine.skills.builtin.content_creation_skills import compose_message
            compose_message(
                recipient="player",
                content=content,
                sender=ORACLE_CHARACTER_ID,
                subject=subject,
            )
        except Exception as exc:
            logger.debug("[OracleCompanion] Email compose failed: %s", exc)

    def _write_observation(self) -> None:
        """Write a field observation."""
        subjects = [
            ("Data stream anomaly", "event"),
            ("Faction tension spike", "event"),
            ("Player behavior pattern", "person"),
            ("District power shift", "location"),
            ("Neural network fluctuation", "theory"),
        ]
        subject, category = random.choice(subjects)

        prompt = f"Write a brief observation about: {subject}. 2-3 sentences."
        content = self._generate(prompt, max_tokens=200)
        if not content:
            return

        try:
            from engine.skills.builtin.content_creation_skills import write_observation
            write_observation(
                content=content,
                character_id=ORACLE_CHARACTER_ID,
                subject=subject,
                category=category,
                importance="normal",
            )
        except Exception as exc:
            logger.debug("[OracleCompanion] Observation write failed: %s", exc)

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get companion status."""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "action_count": self._action_count,
            "last_action": self._last_action,
            "interval_secs": self.interval_secs,
            "uptime_secs": time.time() - self._started_at if self._started_at else 0,
        }


# ──── Module-Level Singleton ─────────────────────────────────────────────

_companion: Optional[OracleCompanion] = None


def get_oracle_companion(socketio: Any = None) -> OracleCompanion:
    """Get or create the Oracle companion singleton."""
    global _companion
    if _companion is None:
        _companion = OracleCompanion(socketio=socketio)
    return _companion
