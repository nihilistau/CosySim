"""Phone assistant — passthrough to system assistant + offline fallback.

When the phone is connected to the CosySim server, routes queries through
the system assistant (Aria). When disconnected, falls back to AnythingLLM
on the phone for basic Q&A.

Provides voice message synthesis via TTS for spoken responses.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)


class PhoneAssistant:
    """Smart-routing assistant for the phone scene.

    Routes queries through a cascade:
    1. System assistant (Aria) — when CosySim server is reachable
    2. Nexus Q&A — when Nexus is available but assistant isn't
    3. AnythingLLM (phone instance) — offline/local fallback

    Also handles TTS synthesis of responses for voice playback.
    """

    def __init__(self) -> None:
        cfg = get_config()
        self._mode: str = "auto"  # auto, passthrough, offline
        self._history: List[Dict[str, str]] = []
        self._max_history: int = cfg.get("phone.assistant.max_history", 50)
        self._tts_enabled: bool = cfg.get("phone.assistant.tts_enabled", True)
        self._stats: Dict[str, int] = {
            "queries": 0,
            "assistant_hits": 0,
            "nexus_hits": 0,
            "allm_hits": 0,
            "fallback_hits": 0,
            "tts_requests": 0,
        }
        logger.info("PhoneAssistant initialized (mode=%s)", self._mode)

    # ── Chat ────────────────────────────────────────────────────────────

    def chat(
        self,
        message: str,
        mode: Optional[str] = None,
        voice: bool = False,
    ) -> Dict[str, Any]:
        """Process a chat message through the routing cascade.

        Args:
            message: User message text.
            mode: Override mode ('passthrough', 'offline', 'auto').
            voice: If True, generate TTS audio for the response.

        Returns:
            Dict with reply, source, voice_url (if voice=True), timestamp.
        """
        self._stats["queries"] += 1
        effective_mode = mode or self._mode
        reply = ""
        source = "fallback"
        audio_path: Optional[str] = None

        # Tier 1: System assistant (passthrough)
        if effective_mode in ("auto", "passthrough"):
            result = self._try_system_assistant(message)
            if result:
                reply = result.get("reply", "")
                source = "assistant"
                self._stats["assistant_hits"] += 1

        # Tier 2: Nexus Q&A
        if not reply and effective_mode in ("auto", "passthrough"):
            result = self._try_nexus(message)
            if result:
                reply = result
                source = "nexus"
                self._stats["nexus_hits"] += 1

        # Tier 3: AnythingLLM (offline/local)
        if not reply and effective_mode in ("auto", "offline"):
            result = self._try_anythingllm(message)
            if result:
                reply = result
                source = "anythingllm"
                self._stats["allm_hits"] += 1

        # Tier 4: Static fallback
        if not reply:
            reply = "I'm currently offline. Please try again when connected to the system."
            source = "fallback"
            self._stats["fallback_hits"] += 1

        # Store in conversation history
        self._history.append({"role": "user", "text": message, "ts": time.time()})
        self._history.append({"role": "assistant", "text": reply, "source": source, "ts": time.time()})
        if len(self._history) > self._max_history * 2:
            self._history = self._history[-self._max_history * 2:]

        # TTS synthesis
        if voice and self._tts_enabled and reply:
            audio_path = self._synthesize_voice(reply)

        return {
            "reply": reply,
            "source": source,
            "voice_url": audio_path,
            "timestamp": time.time(),
        }

    # ── Routing Tiers ───────────────────────────────────────────────────

    def _try_system_assistant(self, message: str) -> Optional[Dict[str, Any]]:
        """Try the system assistant (Aria)."""
        try:
            from engine.assistant.system_assistant import get_assistant
            assistant = get_assistant()
            result = assistant.chat(message)
            if isinstance(result, dict) and result.get("reply"):
                return result
            if isinstance(result, str) and result:
                return {"reply": result}
        except Exception as exc:
            logger.debug("System assistant unavailable: %s", exc)
        return None

    def _try_nexus(self, message: str) -> Optional[str]:
        """Try Nexus Q&A cache."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            result = client.ask(message)
            if result and isinstance(result, dict):
                answer = result.get("answer", "")
                confidence = result.get("confidence", 0)
                if answer and confidence > 0.3:
                    return answer
        except Exception as exc:
            logger.debug("Nexus unavailable: %s", exc)
        return None

    def _try_anythingllm(self, message: str) -> Optional[str]:
        """Try AnythingLLM (local/phone instance)."""
        try:
            from engine.integrations.anythingllm import get_anythingllm_client
            client = get_anythingllm_client()
            # Try the default workspace on the phone instance
            result = client.chat("cosysim", message, mode="chat", instance="phone")
            if isinstance(result, dict):
                text = result.get("textResponse", result.get("text", ""))
                if text:
                    return text
        except Exception as exc:
            logger.debug("AnythingLLM unavailable: %s", exc)
        return None

    # ── Voice ───────────────────────────────────────────────────────────

    def _synthesize_voice(self, text: str) -> Optional[str]:
        """Generate TTS audio for a response."""
        self._stats["tts_requests"] += 1
        try:
            from engine.tts.tts_manager import get_tts_manager
            manager = get_tts_manager()
            audio_path = manager.synthesize(text)
            if audio_path:
                return str(audio_path)
        except Exception as exc:
            logger.debug("TTS synthesis failed: %s", exc)
        return None

    # ── Mode Control ────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> str:
        """Set the routing mode.

        Args:
            mode: 'auto' (cascade all tiers), 'passthrough' (server only),
                  'offline' (AnythingLLM only).

        Returns:
            The effective mode.
        """
        if mode in ("auto", "passthrough", "offline"):
            self._mode = mode
            logger.info("PhoneAssistant mode set to %s", mode)
        else:
            logger.warning("Invalid mode %r, keeping %s", mode, self._mode)
        return self._mode

    def get_mode(self) -> str:
        """Get current routing mode."""
        return self._mode

    # ── History & Stats ─────────────────────────────────────────────────

    def get_history(self, limit: int = 20) -> List[Dict[str, str]]:
        """Get recent conversation history."""
        return self._history[-limit * 2:]

    def clear_history(self) -> int:
        """Clear conversation history."""
        count = len(self._history)
        self._history.clear()
        return count

    def stats(self) -> Dict[str, Any]:
        """Get assistant statistics."""
        total = self._stats["queries"]
        return {
            "mode": self._mode,
            "queries": total,
            "hits": {
                "assistant": self._stats["assistant_hits"],
                "nexus": self._stats["nexus_hits"],
                "anythingllm": self._stats["allm_hits"],
                "fallback": self._stats["fallback_hits"],
            },
            "tts_requests": self._stats["tts_requests"],
            "history_length": len(self._history),
            "hit_rates": {
                "assistant": self._stats["assistant_hits"] / total if total else 0,
                "nexus": self._stats["nexus_hits"] / total if total else 0,
                "anythingllm": self._stats["allm_hits"] / total if total else 0,
                "fallback": self._stats["fallback_hits"] / total if total else 0,
            },
        }

    def status(self) -> Dict[str, Any]:
        """Get current status including connectivity."""
        connected = {"assistant": False, "nexus": False, "anythingllm": False}
        try:
            from engine.assistant.system_assistant import get_assistant
            get_assistant()
            connected["assistant"] = True
        except Exception:
            pass
        try:
            from engine.nexus.client import get_nexus_client
            get_nexus_client()
            connected["nexus"] = True
        except Exception:
            pass
        try:
            from engine.integrations.anythingllm import get_anythingllm_client
            client = get_anythingllm_client()
            connected["anythingllm"] = client.is_connected()
        except Exception:
            pass

        return {
            "mode": self._mode,
            "connected": connected,
            "stats": self.stats(),
        }


# ── Module-level singleton ──────────────────────────────────────────────

_instance: Optional[PhoneAssistant] = None


def get_phone_assistant() -> PhoneAssistant:
    """Get or create the singleton PhoneAssistant."""
    global _instance
    if _instance is None:
        _instance = PhoneAssistant()
    return _instance


def reset_phone_assistant() -> None:
    """Reset singleton (for testing)."""
    global _instance
    _instance = None
