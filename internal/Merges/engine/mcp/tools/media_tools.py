"""
Media tool logic — extracted from cosysim_server.py (Sprint 14 Phase A).

Pure business-logic functions. Each takes its dependencies as parameters
so the MCP @tool wrappers in cosysim_server.py remain thin.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool

logger = logging.getLogger(__name__)


# ── Pydantic Models ───────────────────────────────────────────────────


class ImageGenerationResponse(BaseModel):
    status: str
    result: Optional[str] = None


class SelfieResponse(BaseModel):
    success: bool
    image_path: Optional[str] = None
    prompt: Optional[str] = None
    character_id: Optional[str] = None
    display_hint: Optional[str] = None
    error: Optional[str] = None


class VoiceMessageResponse(BaseModel):
    success: bool
    audio_path: Optional[str] = None
    text: Optional[str] = None
    emotion: Optional[str] = None
    display_hint: Optional[str] = None
    error: Optional[str] = None


class SearchResult(BaseModel):
    title: str
    snippet: str
    url: str


# ── Image generation ───────────────────────────────────────────────────


@mcp_tool
def generate_image_request_logic(
    prompt: str,
    width: int = 512,
    height: int = 768,
    character_id: Optional[str] = None,
) -> ImageGenerationResponse:
    """Generate an image via ComfyUI and return the file path."""
    from content.simulation.services.comfyui_client import ComfyUIClient
    from engine.config import get_config

    config = get_config()
    url = config.get("comfyui.base_url", "http://127.0.0.1:8188")
    client = ComfyUIClient(base_url=url)
    result = client.generate_image(prompt=prompt, width=width, height=height)
    if result:
        return ImageGenerationResponse(
            status=f"Image generated: {result}", result=str(result)
        )
    return ImageGenerationResponse(status="Image generation failed.")


# ── Selfie generation ─────────────────────────────────────────────────


@mcp_tool
def send_selfie_logic(
    prompt: str,
    character_id: Optional[str] = None,
    width: int = 512,
    height: int = 768,
) -> SelfieResponse:
    """Generate a selfie/photo and return JSON with the image path."""
    from content.simulation.services.comfyui_client import ComfyUIClient
    from engine.config import get_config

    config = get_config()
    url = config.get("comfyui.base_url", "http://127.0.0.1:8188")
    client = ComfyUIClient(base_url=url)
    result = client.generate_image(prompt=prompt, width=width, height=height)
    if result:
        return SelfieResponse(
            success=True,
            image_path=str(result),
            prompt=prompt,
            character_id=character_id or "unknown",
            display_hint="inline_image",
        )
    return SelfieResponse(success=False, error="Generation returned no result")


# ── Voice message ──────────────────────────────────────────────────────


@mcp_tool
def send_voice_message_logic(
    text: str,
    character_id: Optional[str] = None,
    emotion: str = "neutral",
) -> VoiceMessageResponse:
    """Generate a voice message via TTS and return JSON with the audio path."""
    from content.simulation.services.voice_message import generate_voice_message

    result = generate_voice_message(
        text=text,
        character_id=character_id or "default",
        emotion=emotion,
    )
    if result:
        return VoiceMessageResponse(
            success=True,
            audio_path=str(result),
            text=text,
            emotion=emotion,
            display_hint="audio_player",
        )
    return VoiceMessageResponse(success=False, error="TTS generation failed")


# ── Web search ─────────────────────────────────────────────────────────


@mcp_tool
def search_web_logic(query: str, max_results: int = 5) -> List[SearchResult]:
    """Search the web via DuckDuckGo Instant Answers and return JSON results."""
    # Try DuckDuckGo Instant Answers API (no key required)
    try:
        import httpx

        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
        r = httpx.get(
            "https://api.duckduckgo.com/",
            params=params,
            timeout=8.0,
        )
        data = r.json()
        results: List[SearchResult] = []
        # Abstract (main answer)
        if data.get("AbstractText"):
            results.append(
                SearchResult(
                    title=data.get("Heading", "DuckDuckGo"),
                    snippet=data["AbstractText"][:400],
                    url=data.get("AbstractURL", ""),
                )
            )
        # Related topics
        for topic in data.get("RelatedTopics", [])[: max_results - 1]:
            if "Text" in topic:
                results.append(
                    SearchResult(
                        title=topic.get("Text", "")[:80],
                        snippet=topic.get("Text", "")[:400],
                        url=topic.get("FirstURL", ""),
                    )
                )
        if results:
            return results
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Fallback: return a note that web search is unavailable offline
    return [
        SearchResult(
            title="Search unavailable",
            snippet=f"Could not perform web search for '{query}'. "
            "The system may be offline or the search service is unreachable.",
            url="",
        )
    ]
