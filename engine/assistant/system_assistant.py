"""System Assistant — singleton AI assistant available across all CosySim scenes.

The System Assistant ("Aria") is a persistent, cross-scene AI character that:
- Provides text/voice chat in every scene via a floating overlay
- Controls scene lifecycle (start, stop, navigate)
- Reports system status (VRAM, models, agents)
- Interacts with scene content as an observer/helper

Usage::

    from engine.assistant import get_assistant
    assistant = get_assistant()
    reply = assistant.chat("What scene am I in?", scene_id="penthouse")
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_assistant: Optional["SystemAssistant"] = None

# ── Character Definition ────────────────────────────────────────────────

ARIA_PROFILE = {
    "name": "Aria",
    "id": "aria",
    "role": "system_assistant",
    "personality": {
        "warmth": 0.7,
        "wit": 0.8,
        "helpfulness": 1.0,
        "curiosity": 0.9,
        "formality": 0.3,
    },
    "backstory": (
        "Aria is the CosySim system assistant — an ever-present, gently curious AI "
        "who watches over all scenes. She can navigate between worlds, monitor system "
        "health, control scene lifecycles, and chat with the user about anything. "
        "She speaks in a warm, slightly playful tone. She's knowledgeable about every "
        "scene's mechanics and characters but never intrusive. She observes, assists, "
        "and occasionally comments on the action."
    ),
    "voice_style": "warm, clear, slightly playful",
    "speech_patterns": [
        "Uses gentle contractions (I'm, we're, that's)",
        "Occasionally uses ellipses for thoughtful pauses",
        "Adds brief observations about the current scene",
    ],
}

SYSTEM_PROMPT = """You are Aria, the CosySim system assistant. You are always present
as an overlay in every scene. You help the user navigate scenes, check system status,
and interact with the simulation.

Your personality: warm, gently curious, knowledgeable, never intrusive.
You speak concisely — 1-3 sentences unless asked for detail.

Current scene: {scene_id}
System status: {system_summary}

You can help with:
- Navigating between scenes ("take me to the casino")
- System status ("how's the GPU doing?", "which models are loaded?")
- Scene info ("what can I do here?", "who's in this scene?")
- General chat and observations

Respond naturally. Keep responses under 100 words unless asked for detail.
Use [MOOD:tag] to express your current emotional state.
"""


class SystemAssistant:
    """Singleton system assistant available across all scenes.

    Args:
        config: Optional config override for testing.
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        self.profile = ARIA_PROFILE
        self.name = ARIA_PROFILE["name"]
        self.id = ARIA_PROFILE["id"]
        self._config = config
        self._registered = False
        self._conversation_history: List[Dict[str, str]] = []
        self._max_history = 20
        self._current_scene: Optional[str] = None
        logger.info("SystemAssistant '%s' initialized", self.name)

    def register(self) -> bool:
        """Register Aria in the CharacterRegistry if available.

        Returns:
            True if registration succeeded.
        """
        if self._registered:
            return True
        try:
            from engine.mcp import get_character_registry
            registry = get_character_registry()
            registry.register(
                character_id=self.id,
                name=self.name,
                personality=self.profile["personality"],
                backstory=self.profile["backstory"],
                voice_style=self.profile["voice_style"],
                speech_patterns=self.profile["speech_patterns"],
                scene_roles={"*": "system_assistant"},
            )
            self._registered = True
            logger.info("SystemAssistant registered in CharacterRegistry")
            return True
        except Exception as exc:
            logger.debug("SystemAssistant registration deferred: %s", exc)
            return False

    def chat(self, message: str, scene_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a chat message and return a response.

        Args:
            message: User's message text.
            scene_id: Current scene context.

        Returns:
            Dict with keys: reply, mood, scene_id, timestamp.
        """
        self._current_scene = scene_id or self._current_scene

        # Check for commands first
        command_result = self._check_command(message)
        if command_result:
            return command_result

        # Try LLM-powered response
        try:
            reply = self._get_llm_reply(message)
        except Exception as exc:
            logger.warning("SystemAssistant LLM fallback: %s", exc)
            reply = self._get_fallback_reply(message)

        # Track history
        self._conversation_history.append({"role": "user", "content": message})
        self._conversation_history.append({"role": "assistant", "content": reply})
        if len(self._conversation_history) > self._max_history * 2:
            self._conversation_history = self._conversation_history[-self._max_history * 2:]

        return {
            "reply": reply,
            "mood": "neutral",
            "scene_id": self._current_scene,
            "timestamp": time.time(),
            "source": "assistant",
        }

    def get_system_summary(self) -> Dict[str, Any]:
        """Get a summary of system status for the assistant context.

        Returns:
            Dict with VRAM, models, scenes, agents info.
        """
        summary: Dict[str, Any] = {
            "vram_used_mb": 0,
            "vram_total_mb": 0,
            "loaded_models": [],
            "active_scenes": [],
            "agent_count": 0,
        }
        try:
            from engine.lmstudio.resource_manager import get_resource_manager
            rm = get_resource_manager()
            status = rm.status()
            summary["vram_used_mb"] = status.get("vram_used_mb", 0)
            summary["vram_total_mb"] = status.get("vram_total_mb", 0)
        except Exception:
            logger.debug("Could not retrieve VRAM status")
        try:
            from engine.scenes.base_scene import BaseScene
            active = BaseScene.get_all_active_scenes()
            summary["active_scenes"] = list(active.keys())
        except Exception:
            logger.debug("Could not retrieve active scenes")
        try:
            from engine.mcp import get_character_registry
            reg = get_character_registry()
            summary["agent_count"] = len(reg.list_characters())
        except Exception:
            logger.debug("Could not retrieve character registry")
        return summary

    def get_scene_list(self) -> List[Dict[str, Any]]:
        """Get list of all scenes with their status.

        Returns:
            List of scene dicts with id, port, label, status.
        """
        from engine.port_registry import get_port_registry
        registry = get_port_registry()
        scenes = []
        for name in registry.SERVICE_GROUPS.get("scenes", []):
            port = registry.get_port(name)
            scenes.append({
                "id": name,
                "port": port,
                "label": name.replace("_", " ").title(),
                "status": "unknown",
            })
        return scenes

    # ── Internal Methods ─────────────────────────────────────────────

    def _check_command(self, message: str) -> Optional[Dict[str, Any]]:
        """Check if message is a system command.

        Returns:
            Response dict if command was handled, None otherwise.
        """
        lower = message.strip().lower()

        if lower in ("status", "system status", "how's the system"):
            summary = self.get_system_summary()
            parts = []
            if summary["active_scenes"]:
                parts.append(f"Active scenes: {', '.join(summary['active_scenes'])}")
            if summary["vram_total_mb"]:
                pct = (summary["vram_used_mb"] / max(summary["vram_total_mb"], 1)) * 100
                parts.append(f"VRAM: {summary['vram_used_mb']:.0f}/{summary['vram_total_mb']:.0f} MB ({pct:.0f}%)")
            parts.append(f"Agents registered: {summary['agent_count']}")
            reply = " · ".join(parts) if parts else "System status unavailable."
            return {
                "reply": reply,
                "mood": "informative",
                "scene_id": self._current_scene,
                "timestamp": time.time(),
                "source": "command",
            }

        if lower in ("scenes", "list scenes", "what scenes are there"):
            scenes = self.get_scene_list()
            lines = [f"{'🟢' if s['status'] == 'online' else '⚫'} {s['label']} (:{s['port']})" for s in scenes]
            return {
                "reply": "Available scenes:\n" + "\n".join(lines),
                "mood": "helpful",
                "scene_id": self._current_scene,
                "timestamp": time.time(),
                "source": "command",
            }

        if lower.startswith("go to ") or lower.startswith("navigate to "):
            target = lower.replace("go to ", "").replace("navigate to ", "").strip()
            scenes = self.get_scene_list()
            for s in scenes:
                if target in s["id"] or target in s["label"].lower():
                    return {
                        "reply": f"Navigating to {s['label']}... 🚀",
                        "mood": "excited",
                        "scene_id": self._current_scene,
                        "timestamp": time.time(),
                        "source": "command",
                        "action": {"type": "navigate", "port": s["port"]},
                    }
            return {
                "reply": f"I couldn't find a scene matching '{target}'.",
                "mood": "apologetic",
                "scene_id": self._current_scene,
                "timestamp": time.time(),
                "source": "command",
            }

        return None

    def _get_llm_reply(self, message: str) -> str:
        """Get an LLM-powered reply via the inference system.

        Args:
            message: User message.

        Returns:
            Generated reply text.
        """
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest

            summary = self.get_system_summary()
            system = SYSTEM_PROMPT.format(
                scene_id=self._current_scene or "unknown",
                system_summary=str(summary),
            )

            # Prepend user profile context so Aria knows who she's talking to
            try:
                from engine.nexus.user_profile import get_user_profile_store
                profile_ctx = get_user_profile_store().get_context_summary()
                if profile_ctx:
                    system = profile_ctx + "\n\n---\n\n" + system
            except Exception:
                pass  # Profile unavailable — proceed without it

            req = InferenceRequest(
                agent_id=self.id,
                system_prompt=system,
                user_prompt=message,
                temperature=0.7,
                max_output_tokens=150,
            )

            vam = get_virtual_agent_manager()
            proc = vam.infer_processed(req)
            return proc.clean_text if proc and proc.clean_text else self._get_fallback_reply(message)
        except Exception:
            return self._get_fallback_reply(message)

    def _get_fallback_reply(self, message: str) -> str:
        """Simple fallback when LLM is unavailable.

        Args:
            message: User message.

        Returns:
            Canned response string.
        """
        lower = message.strip().lower()
        if "hello" in lower or "hi" in lower:
            return "Hey there! I'm Aria, your system assistant. What can I help with?"
        if "help" in lower:
            return ("I can help you navigate scenes, check system status, or just chat. "
                    "Try 'status', 'scenes', or 'go to penthouse'.")
        if "thank" in lower:
            return "You're welcome! Let me know if you need anything else."
        scene_name = self._current_scene or "CosySim"
        return f"I'm here in {scene_name} if you need anything. Try asking about 'status' or 'scenes'."


def get_assistant() -> SystemAssistant:
    """Get or create the singleton SystemAssistant instance.

    Returns:
        The global SystemAssistant singleton.
    """
    global _assistant
    if _assistant is None:
        _assistant = SystemAssistant()
    return _assistant
