"""
tts_skills.py — TTS generation and voice management skills

Skill pack: ``tts``

These skills let agents generate voice messages, manage voice designs,
and list available voicemails via the Qwen3-TTS server.
"""
from __future__ import annotations

from engine.skills.skill import skill


@skill(
    pack="tts",
    description=(
        "Generate a voice message using TTS. Returns the audio file path. "
        "The character's voice design is automatically applied."
    ),
    tags=["tts", "voice", "audio", "generation"],
)
def tts_generate_voice(
    text: str,
    character_id: str,
    max_duration: int = 60,
) -> str:
    """
    Generate a voice message as a WAV file via the Qwen3-TTS engine.

    Args:
        text: The text to speak (up to 50,000 chars for stories).
        character_id: Character ID — voice design is auto-loaded.
        max_duration: Maximum duration in seconds (10-3600).

    Returns:
        Path to the generated WAV file, or error message.
    """
    try:
        from engine.tts.voice_designer import get_voice_designer
        from engine.tts.qwen3_server import _engine, _jobs, _run_generation, TTSJob, GenerateRequest, VOICE_DIR
        from engine.skills.chain_context import get_chain_context
        import uuid

        ctx = get_chain_context()
        designer = get_voice_designer()
        design = designer.get(character_id)

        job_id = str(uuid.uuid4())[:12]
        req = GenerateRequest(
            text=text,
            voice_design=design.description,
            character_id=character_id,
            model_size=design.model_size,
            max_duration=max(10, min(max_duration, 3600)),
            chain_id=ctx.get("chain_id"),
        )

        _jobs[job_id] = TTSJob(job_id=job_id)
        _run_generation(job_id, req)
        job = _jobs[job_id]

        if job.status == "completed":
            return f"Voice message saved: {job.filepath} ({job.duration:.1f}s)"
        return f"Voice generation failed: {job.error}"

    except Exception as exc:
        return f"TTS generation failed: {exc}"


@skill(
    pack="tts",
    description="Cast or update a character's voice design. Saves persistently.",
    tags=["tts", "voice", "design", "cast"],
)
def cast_voice(
    character_id: str,
    description: str,
    model_size: str = "1.7b",
) -> str:
    """
    Save a voice design for a character.

    Args:
        character_id: The character's ID.
        description: Natural language voice description for Qwen3-TTS.
        model_size: '0.6b' for simple, '1.7b' for complex voices.

    Returns:
        Confirmation message.
    """
    try:
        from engine.tts.voice_designer import get_voice_designer, VoiceDesign

        designer = get_voice_designer()
        designer.cast(character_id, VoiceDesign(
            description=description,
            model_size=model_size,
        ))
        return f"Voice design saved for {character_id}: {model_size} model"

    except Exception as exc:
        return f"Failed to cast voice: {exc}"


@skill(
    pack="tts",
    description="List available voice presets for quick character casting.",
    tags=["tts", "voice", "presets"],
)
def list_voice_presets() -> str:
    """
    List all built-in voice presets.

    Returns:
        Formatted list of preset names and descriptions.
    """
    try:
        from engine.tts.voice_designer import VOICE_PRESETS
        lines = []
        for name, design in VOICE_PRESETS.items():
            lines.append(f"• {name} ({design.model_size}): {design.description[:80]}...")
        return "\n".join(lines) if lines else "No presets available."
    except Exception as exc:
        return f"Failed to list presets: {exc}"


@skill(
    pack="tts",
    description="List voicemails for a character from the voice message directory.",
    tags=["tts", "voice", "voicemail", "list"],
)
def list_voicemails(character_id: str, limit: int = 10) -> str:
    """
    List voice message files for a character.

    Args:
        character_id: Character ID to filter by.
        limit: Max results (1-50).

    Returns:
        JSON list of voicemail metadata.
    """
    try:
        import json
        from pathlib import Path
        voice_dir = Path(__file__).parent.parent.parent / "content" / "simulation" / "media" / "voice"
        if not voice_dir.exists():
            return "No voice messages directory found."

        files = sorted(voice_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        limit = max(1, min(limit, 50))
        results = []
        for f in files[:limit]:
            import wave
            try:
                with wave.open(str(f), "rb") as wf:
                    duration = wf.getnframes() / wf.getframerate()
            except Exception:
                duration = 0
            results.append({
                "filename": f.name,
                "duration": round(duration, 1),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
        return json.dumps(results, indent=2) if results else "No voice messages found."
    except Exception as exc:
        return f"Failed to list voicemails: {exc}"
