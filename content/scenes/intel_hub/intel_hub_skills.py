"""Intelligence Hub skill pack — agent-accessible tools for the hub and assistant."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="intel_hub",
    description="Get the current status of the Intelligence Hub (Nexus, scheduler, cache, resources).",
    category="SYSTEM",
    tags=["hub", "status", "overview"],
)
def intel_hub_status() -> str:
    """Return a summary of hub status."""
    try:
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        from engine.scenes.base_scene import BaseScene
        scene = BaseScene.get_active_scene("intel_hub")
        if scene is None:
            return "Intelligence Hub is not running."
        return f"Intelligence Hub is online at port {scene._port}."
    except Exception as exc:
        return f"Error: {exc}"


@skill(
    pack="intel_hub",
    description="Chat with the system assistant Aria and receive her text response.",
    category="COMMUNICATION",
    tags=["assistant", "aria", "chat"],
)
def intel_hub_chat(message: str) -> str:
    """Send a message to Aria and return her response text.

    Args:
        message: The message to send to the assistant.

    Returns:
        Aria's response as a string.
    """
    try:
        from engine.assistant.system_assistant import get_system_assistant
        assistant = get_system_assistant()
        result = assistant.chat(message)
        if isinstance(result, dict):
            return result.get("response", str(result))
        return str(result)
    except Exception as exc:
        return f"Error communicating with assistant: {exc}"


@skill(
    pack="intel_hub",
    description="Test a TTS backend by synthesizing a sample phrase. Returns RTF and backend used.",
    category="MEDIA",
    tags=["tts", "voice", "test"],
    cooldown=5.0,
)
def intel_hub_tts_test(text: str = "Hello, I am Aria.", backend: str = "piper") -> str:
    """Synthesize speech and return timing info.

    Args:
        text: Text to synthesize.
        backend: TTS backend — piper, orpheus, orpheus_native, or qwen3.

    Returns:
        JSON string with backend, latency_ms, duration_s, rtf.
    """
    import json
    try:
        from engine.tts.tts_manager import get_tts_manager
        mgr = get_tts_manager()
        result = mgr.synthesize(text, backend=backend)
        rtf = (result.latency_ms / 1000) / max(result.duration, 0.001)
        return json.dumps({
            "backend": result.backend,
            "latency_ms": result.latency_ms,
            "duration_s": round(result.duration, 2),
            "rtf": round(rtf, 2),
            "bytes": len(result.audio_bytes) if result.audio_bytes else 0,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc), "backend": backend})


@skill(
    pack="intel_hub",
    description="List all available TTS voices for each backend.",
    category="MEDIA",
    tags=["tts", "voices"],
)
def intel_hub_list_voices() -> str:
    """Return all TTS voice options as JSON."""
    import json
    try:
        from content.scenes.intel_hub.intel_hub_scene import _get_tts_voices
        return json.dumps(_get_tts_voices())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="intel_hub",
    description="Get the current VTT (voice-to-text) configuration for all backends.",
    category="COMMUNICATION",
    tags=["vtt", "stt", "config"],
)
def intel_hub_vtt_config() -> str:
    """Return VTT backend configuration as JSON."""
    import json
    try:
        from content.scenes.intel_hub.intel_hub_scene import _get_vtt_config
        return json.dumps(_get_vtt_config())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@skill(
    pack="intel_hub",
    description="Get a summary of the QA cache pipeline — last cycle stats and gap list.",
    category="SYSTEM",
    tags=["cache", "pipeline", "qa"],
)
def intel_hub_cache_status() -> str:
    """Return QA cache pipeline status as JSON."""
    import json
    try:
        from content.scenes.intel_hub.intel_hub_scene import _get_cache_status
        return json.dumps(_get_cache_status())
    except Exception as exc:
        return json.dumps({"error": str(exc)})
