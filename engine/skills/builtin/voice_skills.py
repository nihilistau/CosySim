"""
voice_skills.py — Voice message generation skills

These skills allow the LLM to generate voice messages for a character
and retrieve the audio file URL, which can then be sent to the user.
"""
from __future__ import annotations

from engine.skills.skill import skill


@skill(
    pack="voice",
    description=(
        "Generate a voice message for a character speaking the given text. "
        "Returns the audio file URL or an error message."
    ),
    tags=["voice", "audio", "generation"],
)
def generate_voice_message(
    character_id: str,
    text: str,
    mood: str = "neutral",
    speed: float = 1.0,
) -> str:
    """
    Generate speech audio for a character using the TTS engine.

    Args:
        character_id: The character's database ID (used to select voice profile).
        text:         The text the character should speak (max ~500 chars).
        mood:         Mood to influence speech style: "happy", "sad", "excited", etc.
        speed:        Speech speed multiplier (0.5 = slow, 1.0 = normal, 1.5 = fast).

    Returns:
        URL of the generated audio file on success; error string on failure.
    """
    try:
        from content.simulation.database.db import Database
        from content.simulation.character_system.character import Character
        from content.simulation.services.voice_message import VoiceMessageGenerator
        from engine.skills.chain_context import get_chain_context

        ctx    = get_chain_context()
        db     = Database()
        char   = Character.load(character_id, db=db)
        name   = char.name if char else "Unknown"
        gen    = VoiceMessageGenerator(db=db)

        result = gen.generate_voice_message(
            character_id=character_id,
            character_name=name,
            text=text,
            emotion=mood,
            chain_id=ctx.get("chain_id"),
            scene_id=ctx.get("scene_id", "unknown"),
        )

        if result and result.get("url"):
            return result["url"]
        if result and result.get("filepath"):
            from pathlib import Path
            fname = Path(result["filepath"]).name
            return f"/api/voice/download/{fname}"

        return "Voice message generated but no URL returned."

    except Exception as exc:
        return f"Failed to generate voice message: {exc}"


@skill(
    pack="voice",
    description=(
        "List the most recent voice messages for a character. "
        "Returns a JSON-formatted list of voice message metadata."
    ),
    tags=["voice", "history"],
)
def list_voice_messages(character_id: str, limit: int = 10) -> str:
    """
    Return a JSON list of recent voice messages for a character.

    Args:
        character_id: The character's database ID.
        limit:        Maximum number of messages to return (1–50).

    Returns:
        JSON string of message metadata, or error message.
    """
    try:
        import json
        from content.simulation.database.db import Database
        from content.scenes.phone.apps.voice_messages import VoiceMessagesApp

        db    = Database()
        app   = VoiceMessagesApp(db)
        limit = max(1, min(limit, 50))
        cards = app.get_list(character_id, limit=limit)
        return json.dumps([
            {"title": c["title"], "duration": c["duration"], "url": c["url"], "timestamp": c["timestamp"]}
            for c in cards
        ], indent=2)
    except Exception as exc:
        return f"Failed to list voice messages: {exc}"
