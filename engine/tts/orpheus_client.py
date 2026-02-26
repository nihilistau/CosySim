"""
Orpheus TTS Client — OpenAI-compatible interface to Orpheus-FastAPI.

Orpheus-FastAPI runs as a standalone FastAPI server that connects to
LMStudio for inference. It provides high-quality emotional TTS with
24 voices across 8 languages.

The client sends requests to the ``/v1/audio/speech`` endpoint and
saves WAV files to the standard VOICE_DIR.

Configuration (config/default.yaml)::

    tts:
      orpheus:
        server_url: "http://localhost:5005"
        default_voice: "tara"
        timeout: 120

Usage::

    from engine.tts.orpheus_client import get_orpheus_client
    client = get_orpheus_client()
    path = client.generate("Hello world", voice="tara")
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


# ── Voice mapping ──────────────────────────────────────────────────────

ORPHEUS_VOICES: Dict[str, Dict[str, str]] = {
    # English
    "tara": {"lang": "en", "gender": "female", "style": "conversational, clear"},
    "leah": {"lang": "en", "gender": "female", "style": "warm, gentle"},
    "jess": {"lang": "en", "gender": "female", "style": "energetic, youthful"},
    "leo": {"lang": "en", "gender": "male", "style": "authoritative, deep"},
    "dan": {"lang": "en", "gender": "male", "style": "friendly, casual"},
    "mia": {"lang": "en", "gender": "female", "style": "professional, articulate"},
    "zac": {"lang": "en", "gender": "male", "style": "enthusiastic, dynamic"},
    "zoe": {"lang": "en", "gender": "female", "style": "calm, soothing"},
    # French
    "pierre": {"lang": "fr", "gender": "male", "style": "sophisticated"},
    "amelie": {"lang": "fr", "gender": "female", "style": "elegant"},
    "marie": {"lang": "fr", "gender": "female", "style": "spirited"},
    # German
    "jana": {"lang": "de", "gender": "female", "style": "clear"},
    "thomas": {"lang": "de", "gender": "male", "style": "authoritative"},
    "max": {"lang": "de", "gender": "male", "style": "energetic"},
    # Korean
    "유나": {"lang": "ko", "gender": "female", "style": "melodic"},
    "준서": {"lang": "ko", "gender": "male", "style": "confident"},
    # Hindi
    "ऋतिका": {"lang": "hi", "gender": "female", "style": "expressive"},
    # Mandarin
    "长乐": {"lang": "zh", "gender": "female", "style": "gentle"},
    "白芷": {"lang": "zh", "gender": "female", "style": "clear"},
    # Spanish
    "javi": {"lang": "es", "gender": "male", "style": "warm"},
    "sergio": {"lang": "es", "gender": "male", "style": "professional"},
    "maria": {"lang": "es", "gender": "female", "style": "friendly"},
    # Italian
    "pietro": {"lang": "it", "gender": "male", "style": "passionate"},
    "giulia": {"lang": "it", "gender": "female", "style": "expressive"},
    "carlo": {"lang": "it", "gender": "male", "style": "refined"},
}

# Emotion tags Orpheus supports — maps CosySim mood tags to Orpheus tags
MOOD_TO_EMOTION: Dict[str, str] = {
    "happy": "<laugh>",
    "amused": "<chuckle>",
    "sad": "<sigh>",
    "tired": "<yawn>",
    "surprised": "<gasp>",
    "disgusted": "<groan>",
    "sick": "<cough>",
    "crying": "<sniffle>",
}


class OrpheusClient:
    """HTTP client for Orpheus-FastAPI TTS server."""

    def __init__(
        self,
        server_url: str = "http://localhost:5005",
        default_voice: str = "tara",
        timeout: int = 120,
        output_dir: Optional[Path] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.default_voice = default_voice
        self.timeout = timeout

        if output_dir is None:
            try:
                from engine.paths import VOICE_DIR
                self.output_dir = VOICE_DIR
            except ImportError:
                self.output_dir = Path("outputs")
        else:
            self.output_dir = output_dir

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        mood: Optional[str] = None,
    ) -> str:
        """Generate speech and save as WAV file.

        Args:
            text: Text to synthesize.
            voice: Orpheus voice name (e.g. "tara", "leo"). Defaults to config.
            speed: Speed factor (0.5–1.5).
            mood: Optional CosySim mood tag to inject emotion.

        Returns:
            Absolute path to the generated WAV file.

        Raises:
            ConnectionError: If the Orpheus server is unreachable.
            RuntimeError: If generation fails.
        """
        voice = voice or self.default_voice

        # Inject emotion tags based on mood
        if mood and mood.lower() in MOOD_TO_EMOTION:
            emotion_tag = MOOD_TO_EMOTION[mood.lower()]
            text = f"{text} {emotion_tag}"

        payload = {
            "model": "orpheus",
            "input": text,
            "voice": voice,
            "response_format": "wav",
            "speed": max(0.5, min(1.5, speed)),
        }

        url = f"{self.server_url}/v1/audio/speech"
        filename = f"orpheus_{voice}_{uuid.uuid4().hex[:8]}.wav"
        filepath = self.output_dir / filename

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                f.write(response.content)

            logger.info(
                "Orpheus TTS: generated %s (%d bytes, voice=%s)",
                filename, len(response.content), voice,
            )
            return str(filepath)

        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot reach Orpheus server at {self.server_url}. "
                "Start it with: cd D:\\F\\Orpheus-FastAPI && python app.py"
            )
        except requests.HTTPError as exc:
            raise RuntimeError(f"Orpheus generation failed: {exc.response.text}")

    def generate_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> str:
        """Generate speech using streaming — saves chunks as single WAV.

        Uses the /speak legacy endpoint for simpler streaming.

        Args:
            text: Text to synthesize.
            voice: Orpheus voice name.
            speed: Speed factor.

        Returns:
            Absolute path to the generated WAV file.
        """
        voice = voice or self.default_voice
        payload = {"text": text, "voice": voice}
        url = f"{self.server_url}/speak"
        filename = f"orpheus_{voice}_{uuid.uuid4().hex[:8]}.wav"
        filepath = self.output_dir / filename

        try:
            response = requests.post(url, json=payload, timeout=self.timeout, stream=True)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info("Orpheus TTS stream: generated %s (voice=%s)", filename, voice)
            return str(filepath)

        except requests.ConnectionError:
            raise ConnectionError(f"Cannot reach Orpheus server at {self.server_url}")
        except requests.HTTPError as exc:
            raise RuntimeError(f"Orpheus stream failed: {exc.response.text}")

    def list_voices(self) -> Dict[str, Dict[str, str]]:
        """Return the Orpheus voice catalog."""
        return ORPHEUS_VOICES.copy()

    def health(self) -> Dict[str, Any]:
        """Check if the Orpheus server is running.

        Returns:
            Dict with status, server_url, and available voices count.
        """
        try:
            response = requests.get(
                f"{self.server_url}/docs",
                timeout=5,
            )
            return {
                "status": "ok" if response.status_code == 200 else "error",
                "server_url": self.server_url,
                "voices": len(ORPHEUS_VOICES),
            }
        except requests.ConnectionError:
            return {
                "status": "offline",
                "server_url": self.server_url,
                "voices": 0,
            }

    def match_voice(
        self,
        gender: Optional[str] = None,
        style: Optional[str] = None,
        lang: str = "en",
    ) -> str:
        """Find the best matching Orpheus voice for given criteria.

        Args:
            gender: "male" or "female".
            style: Style keywords to match (e.g. "warm", "energetic").
            lang: Language code (default "en").

        Returns:
            Voice name string.
        """
        candidates = [
            (name, info) for name, info in ORPHEUS_VOICES.items()
            if info["lang"] == lang
        ]

        if not candidates:
            candidates = [
                (name, info) for name, info in ORPHEUS_VOICES.items()
                if info["lang"] == "en"
            ]

        if gender:
            gender_match = [
                (n, i) for n, i in candidates if i["gender"] == gender.lower()
            ]
            if gender_match:
                candidates = gender_match

        if style and candidates:
            style_lower = style.lower()
            scored = []
            for name, info in candidates:
                score = sum(
                    1 for word in style_lower.split()
                    if word in info["style"]
                )
                scored.append((score, name))
            scored.sort(reverse=True)
            if scored[0][0] > 0:
                return scored[0][1]

        return candidates[0][0] if candidates else self.default_voice


# ── Singleton ──────────────────────────────────────────────────────────
_client: Optional[OrpheusClient] = None


def get_orpheus_client() -> OrpheusClient:
    """Return the global OrpheusClient singleton, configured from YAML."""
    global _client
    if _client is None:
        try:
            from engine.config import get_config
            cfg = get_config()
            _client = OrpheusClient(
                server_url=cfg.get("tts.orpheus.server_url", "http://localhost:5005"),
                default_voice=cfg.get("tts.orpheus.default_voice", "tara"),
                timeout=cfg.get("tts.orpheus.timeout", 120),
            )
        except Exception:
            _client = OrpheusClient()
    return _client
