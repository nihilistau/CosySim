"""
LLM Service - Connects to LM Studio (or any OpenAI-compatible API)
Used for all character AI responses in CosySim
"""
import json
import time
import logging
from typing import Optional, Dict, List, Generator
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class LLMService:
    """
    OpenAI-compatible LLM client for LM Studio or any local LLM.
    Defaults to LM Studio at localhost:1234.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = None,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model  # If None, auto-detect first available model
        self.timeout = timeout
        self._model_cache: Optional[str] = None
        self._connected: Optional[bool] = None

        if not REQUESTS_AVAILABLE:
            logger.warning("requests library not installed – LLM service unavailable")

    # ─────────────────────────────────────────────
    #  Connection helpers
    # ─────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check whether the LLM backend is reachable."""
        if not REQUESTS_AVAILABLE:
            return False
        try:
            r = requests.get(f"{self.base_url}/models", timeout=4)
            self._connected = r.ok
            return r.ok
        except Exception:
            self._connected = False
            return False

    def get_active_model(self) -> Optional[str]:
        """Return the model name to use (explicit or first available)."""
        if self.model:
            return self.model
        if self._model_cache:
            return self._model_cache
        if not REQUESTS_AVAILABLE:
            return None
        try:
            r = requests.get(f"{self.base_url}/models", timeout=4)
            if r.ok:
                data = r.json()
                models = data.get("data", [])
                if models:
                    self._model_cache = models[0]["id"]
                    return self._model_cache
        except Exception:
            pass
        return None

    # ─────────────────────────────────────────────
    #  Core chat method
    # ─────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict],
        system_prompt: Optional[str] = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
        stream: bool = False,
    ) -> Optional[str]:
        """
        Send messages and return the assistant reply.

        Args:
            messages: list of {"role": "user"/"assistant", "content": "..."}
            system_prompt: Prepended system message (character persona)
            temperature: Creativity (0.0 – 2.0)
            max_tokens: Hard limit on response length
            stream: Stream response (unused for now, kept for future)

        Returns:
            Response text or None on failure
        """
        if not REQUESTS_AVAILABLE:
            return self._fallback_response(messages)

        model = self.get_active_model()
        if not model:
            logger.warning("No LLM model available – using fallback")
            return self._fallback_response(messages)

        # Build message list
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()

        except requests.exceptions.ConnectionError:
            logger.error("LLM backend not reachable at %s", self.base_url)
            return self._fallback_response(messages)
        except requests.exceptions.Timeout:
            logger.error("LLM request timed out after %ss", self.timeout)
            return self._fallback_response(messages)
        except Exception as e:
            logger.error("LLM error: %s", e)
            return self._fallback_response(messages)

    def chat_with_character(
        self,
        character,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None,
        temperature: float = 0.85,
    ) -> str:
        """
        Generate character response to a user message.
        Uses the character's system prompt, memories, and history.

        Args:
            character: Character instance
            user_message: What the user typed
            conversation_history: Previous messages [{"role", "content"}, ...]
            temperature: Personality expressiveness

        Returns:
            Character response text
        """
        # Build system prompt from character
        try:
            system_prompt = character.get_system_prompt()
        except Exception:
            system_prompt = f"You are {character.name}, a virtual companion. Be warm, engaging, and stay in character."

        # Add memory context if available
        try:
            memory_context = character.build_context(user_message)
            if memory_context:
                system_prompt += f"\n\n## Relevant Memories\n{memory_context}"
        except Exception:
            pass

        # Build message history
        messages = []
        if conversation_history:
            # Include last 20 messages to keep context window manageable
            for msg in conversation_history[-20:]:
                if msg.get("role") in ("user", "assistant"):
                    messages.append({
                        "role": msg["role"],
                        "content": str(msg.get("content", ""))
                    })

        messages.append({"role": "user", "content": user_message})

        response = self.chat(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
        )

        return response or self._character_fallback(character, user_message)

    def parse_intent(self, message: str, character_name: str = "") -> Dict:
        """
        Detect if the user is asking for specific media.
        Returns dict like:
          {"type": "selfie", "subject": "beach", "nsfw": False}
          {"type": "voice_message", "topic": "tell me a story"}
          {"type": "video_message", "topic": "your day"}
          {"type": "text"}  <- default
        """
        msg = message.lower()

        # Image/selfie detection
        selfie_keywords = ["selfie", "photo", "picture", "pic", "image", "show me", "send me a photo", "send me a pic"]
        if any(k in msg for k in selfie_keywords):
            # Try to extract subject
            subject = "casual"
            if "beach" in msg:
                subject = "beach"
            elif "bedroom" in msg or "bed" in msg:
                subject = "bedroom"
            elif "gym" in msg or "workout" in msg:
                subject = "gym"
            elif "outfit" in msg or "wearing" in msg:
                subject = "outfit"
            elif "face" in msg or "smile" in msg:
                subject = "portrait"

            nsfw_hints = ["naked", "nude", "sexy", "hot", "nsfw", "lingerie", "topless"]
            nsfw = any(k in msg for k in nsfw_hints)

            return {"type": "selfie", "subject": subject, "nsfw": nsfw}

        # Video message detection
        video_keywords = ["video", "clip", "film", "record yourself", "send a video", "video message"]
        if any(k in msg for k in video_keywords):
            topic = "your day"
            if "story" in msg:
                topic = "tell me a story"
            elif "day" in msg:
                topic = "your day"
            elif "outfit" in msg:
                topic = "show me your outfit"
            elif "dance" in msg:
                topic = "dance for me"
            return {"type": "video_message", "topic": topic}

        # Voice message detection
        voice_keywords = ["voice message", "voice note", "audio", "record", "sing", "tell me", "story"]
        if any(k in msg for k in voice_keywords):
            topic = message
            return {"type": "voice_message", "topic": topic}

        return {"type": "text"}

    # ─────────────────────────────────────────────
    #  Fallback responses (when LLM is unavailable)
    # ─────────────────────────────────────────────

    def _fallback_response(self, messages: List[Dict]) -> str:
        """Generic fallback when LLM is offline."""
        import random
        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break

        responses = [
            "Hey! I'm here, just thinking... 💭",
            "I love hearing from you! 😊",
            "You always know how to make me smile ❤️",
            "Tell me more about your day!",
            "I've been thinking about you 💕",
            "What's on your mind? 😘",
        ]
        return random.choice(responses)

    def _character_fallback(self, character, user_message: str) -> str:
        """Character-specific fallback."""
        import random
        name = character.name if hasattr(character, "name") else "Babe"
        mood = character.mood if hasattr(character, "mood") else "happy"

        if mood in ("happy", "excited", "playful"):
            options = [
                f"You always make me smile 😊",
                f"I was just thinking about you!",
                f"That's so sweet of you to say! 💕",
            ]
        elif mood in ("flirty", "seductive"):
            options = [
                "You have no idea what you do to me... 😏",
                "Keep talking like that 😉",
                "I like the way you think 💋",
            ]
        else:
            options = [
                "Tell me more... I'm listening 💭",
                "That's really interesting 😊",
                "I love when you talk to me like this ❤️",
            ]

        return random.choice(options)


# ─────────────────────────────────────────────
#  Singleton helper
# ─────────────────────────────────────────────

_llm_service: Optional[LLMService] = None


def get_llm_service(base_url: str = "http://localhost:1234/v1") -> LLMService:
    """Return the module-level singleton LLM service."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService(base_url=base_url)
    return _llm_service


if __name__ == "__main__":
    svc = LLMService()
    print("LLM available:", svc.is_available())
    print("Model:", svc.get_active_model())
    resp = svc.chat(
        messages=[{"role": "user", "content": "Say hello briefly."}],
        system_prompt="You are a warm, friendly assistant.",
    )
    print("Response:", resp)
