"""engine.tts — Text-to-Speech subsystem (Piper, Orpheus, Qwen3-TTS)"""

from __future__ import annotations

from engine.tts.qwen3_server import Qwen3TTSEngine
from engine.tts.voice_designer import VoiceDesigner
from engine.tts.audio_processor import AudioProcessor
from engine.tts.orpheus_client import OrpheusClient, get_orpheus_client
from engine.tts.orpheus_native import OrpheusNative, get_orpheus_native
from engine.tts.tts_manager import TTSManager, get_tts_manager

__all__ = [
    "Qwen3TTSEngine",
    "VoiceDesigner",
    "AudioProcessor",
    "OrpheusClient",
    "get_orpheus_client",
    "OrpheusNative",
    "get_orpheus_native",
    "TTSManager",
    "get_tts_manager",
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
