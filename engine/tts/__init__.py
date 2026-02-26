"""engine.tts — Text-to-Speech subsystem (Qwen3-TTS, CosyVoice, etc.)"""

from __future__ import annotations

from engine.tts.qwen3_server import Qwen3TTSEngine
from engine.tts.voice_designer import VoiceDesigner
from engine.tts.audio_processor import AudioProcessor

__all__ = [
    "Qwen3TTSEngine",
    "VoiceDesigner",
    "AudioProcessor",
    "get_tts_stream_url",
    "get_tts_ws_url",
]


def get_tts_stream_url() -> str:
    """Return the SSE streaming endpoint URL from config.

    Scenes can import this to avoid hardcoding the TTS server address::

        from engine.tts import get_tts_stream_url
        url = get_tts_stream_url()  # e.g. "http://localhost:8600/generate_stream"
    """
    try:
        from engine.config import get_config
        base = get_config().get("tts.server_url", "http://localhost:8600")
    except Exception:
        base = "http://localhost:8600"
    return f"{base.rstrip('/')}/generate_stream"


def get_tts_ws_url() -> str:
    """Return the WebSocket streaming endpoint URL from config.

    Scenes can import this for real-time audio push::

        from engine.tts import get_tts_ws_url
        url = get_tts_ws_url()  # e.g. "ws://localhost:8600/ws/stream"
    """
    try:
        from engine.config import get_config
        base = get_config().get("tts.server_url", "http://localhost:8600")
    except Exception:
        base = "http://localhost:8600"
    base = base.rstrip("/")
    # Convert http(s):// to ws(s)://
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://"):]
    else:
        ws_base = base
    return f"{ws_base}/ws/stream"
