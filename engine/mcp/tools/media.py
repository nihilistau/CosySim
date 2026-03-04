"""MCP tool domain: media.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── MEDIA TOOLS ────────────────────────────────────────────────────────


@mcp_tool
def generate_image_request(
    prompt: str,
    width: int = 512,
    height: int = 768,
    character_id: Optional[str] = None,
) -> str:
    """
    Request image generation via ComfyUI.
    Provide a detailed prompt describing the desired image.
    Returns the file path of the generated image.
    """
    try:
        from engine.mcp.tools.media_tools import generate_image_request_logic as _impl
        return _impl(prompt, width=width, height=height, character_id=character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def send_selfie(
    prompt: str,
    character_id: Optional[str] = None,
    width: int = 512,
    height: int = 768,
) -> str:
    """
    Generate a selfie/photo and return the image path for inline display.
    Use this when the character wants to send a picture of themselves.
    Provide a detailed prompt describing the selfie (pose, expression, setting).
    Returns JSON with the image path and metadata.
    """
    try:
        from engine.mcp.tools.media_tools import send_selfie_logic as _impl
        return _impl(prompt, character_id=character_id, width=width, height=height)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def send_voice_message(
    text: str,
    character_id: Optional[str] = None,
    emotion: str = "neutral",
) -> str:
    """
    Generate a voice message via TTS and return the audio path.
    Use this when the character wants to send a voice note.
    Provide the text to speak and optional emotion tag.
    Returns JSON with the audio path.
    """
    try:
        from engine.mcp.tools.media_tools import send_voice_message_logic as _impl
        return _impl(text, character_id=character_id, emotion=emotion)
    except Exception as e:
        return json.dumps({"error": str(e)})
