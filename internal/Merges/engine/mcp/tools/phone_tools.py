import json
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


async def phone_assistant_chat_impl(
    message: str, mode: str = "", voice: bool = False
) -> str:
    """Chat with the phone assistant (cascade: system → nexus → anythingllm → fallback)."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        result = get_phone_assistant().chat(message, mode=mode or None, voice=voice)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def phone_assistant_status_impl() -> str:
    """Get phone assistant status: mode, connectivity, stats."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        return json.dumps(get_phone_assistant().status(), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def phone_assistant_set_mode_impl(mode: str) -> str:
    """Set phone assistant mode: auto, passthrough, or offline."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        result = get_phone_assistant().set_mode(mode)
        return json.dumps({"mode": result}, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def phone_assistant_history_impl(limit: int = 20) -> str:
    """Get recent phone assistant conversation history."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        return json.dumps(get_phone_assistant().get_history(limit), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
