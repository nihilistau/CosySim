"""
Media tool logic — extracted from cosysim_server.py (Sprint 14 Phase A).

Pure business-logic functions. Each takes its dependencies as parameters
so the MCP @tool wrappers in cosysim_server.py remain thin.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Image generation ───────────────────────────────────────────────────

def generate_image_request_logic(
    prompt: str,
    width: int = 512,
    height: int = 768,
    character_id: Optional[str] = None,
) -> str:
    """Generate an image via ComfyUI and return the file path."""
    try:
        from content.simulation.services.comfyui_client import ComfyUIClient
        from engine.config import get_config
        config = get_config()
        url = config.get("comfyui.base_url", "http://127.0.0.1:8188")
        client = ComfyUIClient(base_url=url)
        result = client.generate_image(prompt=prompt, width=width, height=height)
        return f"Image generated: {result}" if result else "Image generation failed."
    except Exception as e:
        return f"Image generation failed: {e}"


# ── Selfie generation ─────────────────────────────────────────────────

def send_selfie_logic(
    prompt: str,
    character_id: Optional[str] = None,
    width: int = 512,
    height: int = 768,
) -> str:
    """Generate a selfie/photo and return JSON with the image path."""
    try:
        from content.simulation.services.comfyui_client import ComfyUIClient
        from engine.config import get_config
        config = get_config()
        url = config.get("comfyui.base_url", "http://127.0.0.1:8188")
        client = ComfyUIClient(base_url=url)
        result = client.generate_image(prompt=prompt, width=width, height=height)
        if result:
            return json.dumps({
                "success": True,
                "image_path": str(result),
                "prompt": prompt,
                "character_id": character_id or "unknown",
                "display_hint": "inline_image",
            })
        return json.dumps({"success": False, "error": "Generation returned no result"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ── Voice message ──────────────────────────────────────────────────────

def send_voice_message_logic(
    text: str,
    character_id: Optional[str] = None,
    emotion: str = "neutral",
) -> str:
    """Generate a voice message via TTS and return JSON with the audio path."""
    try:
        from content.simulation.services.voice_message import generate_voice_message
        result = generate_voice_message(
            text=text,
            character_id=character_id or "default",
            emotion=emotion,
        )
        if result:
            return json.dumps({
                "success": True,
                "audio_path": str(result),
                "text": text,
                "emotion": emotion,
                "display_hint": "audio_player",
            })
        return json.dumps({"success": False, "error": "TTS generation failed"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ── Web search ─────────────────────────────────────────────────────────

def search_web_logic(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo Instant Answers and return JSON results."""
    # Try DuckDuckGo Instant Answers API (no key required)
    try:
        import httpx
        params = {
            "q":              query,
            "format":         "json",
            "no_html":        "1",
            "skip_disambig":  "1",
        }
        r = httpx.get(
            "https://api.duckduckgo.com/",
            params=params,
            timeout=8.0,
        )
        data = r.json()
        results: List[Dict[str, str]] = []
        # Abstract (main answer)
        if data.get("AbstractText"):
            results.append({
                "title":   data.get("Heading", "DuckDuckGo"),
                "snippet": data["AbstractText"][:400],
                "url":     data.get("AbstractURL", ""),
            })
        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results - 1]:
            if "Text" in topic:
                results.append({
                    "title":   topic.get("Text", "")[:80],
                    "snippet": topic.get("Text", "")[:400],
                    "url":     topic.get("FirstURL", ""),
                })
        if results:
            return json.dumps(results, indent=2)
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Fallback: return a note that web search is unavailable offline
    return json.dumps([{
        "title": "Search unavailable",
        "snippet": f"Could not perform web search for '{query}'. "
                   "The system may be offline or the search service is unreachable.",
        "url": "",
    }])
