"""ARGUS extended MCP skills — Opal, AppCatalyst Gemini 3, and Gemini extended.

10 new skills providing agent access to:
  - Opal creative content service (Google Labs)
  - AppCatalyst Gemini 3 Flash Preview inference
  - Extended Gemini features (storybooks, saved info, subscriptions)

All network calls are delegated to the dedicated client modules — no
inline HTTP in skills.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── Skill 1: opal_generate ─────────────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Generate creative content via Google Opal using rpcid ug7pge. "
        "Returns generated text with style applied."
    ),
    category="system",
    cooldown=5.0,
    cost=1.0,
    tags=["opal", "generate", "creative"],
)
def opal_generate(prompt: str, style: str = "default") -> str:
    """Generate creative content via the Opal service.

    Args:
        prompt: Text prompt for content generation.
        style: Style hint (e.g. ``"default"``, ``"formal"``, ``"creative"``).

    Returns:
        JSON string with ``content``, ``rpcid``, and status fields.
    """
    from engine.integrations.opal_client import get_opal_client
    try:
        client = get_opal_client()
        result = client.generate_content(prompt=prompt, style=style)
        return json.dumps({
            "status": "ok",
            "content": result.get("content", ""),
            "rpcid": result.get("rpcid"),
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("opal_generate failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 2: opal_gallery_list ─────────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Browse the Opal gallery. Lists templates, examples, and shared "
        "content. Optionally filter by category."
    ),
    category="system",
    cooldown=3.0,
    cost=0.5,
    tags=["opal", "gallery"],
)
def opal_gallery_list(category: str = "", page_size: int = 20) -> str:
    """List items in the Opal gallery.

    Args:
        category: Optional category filter (empty = all categories).
        page_size: Maximum number of items to return.

    Returns:
        JSON string with ``items`` list and ``count`` fields.
    """
    from engine.integrations.opal_client import get_opal_client
    try:
        client = get_opal_client()
        items = client.gallery_list(category=category, page_size=page_size)
        return json.dumps({
            "status": "ok",
            "count": len(items),
            "items": items,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("opal_gallery_list failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 3: opal_drive_list ────────────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "List Opal content items stored in Google Drive via the Opal "
        "Drive proxy API."
    ),
    category="system",
    cooldown=3.0,
    cost=0.5,
    tags=["opal", "drive"],
)
def opal_drive_list(page_size: int = 20) -> str:
    """List Opal content items in Drive via the Drive proxy.

    Args:
        page_size: Maximum number of items to return.

    Returns:
        JSON string with ``files`` list and ``count`` fields.
    """
    from engine.integrations.opal_client import get_opal_client
    try:
        client = get_opal_client()
        files = client.drive_proxy_list(page_size=page_size)
        return json.dumps({
            "status": "ok",
            "count": len(files),
            "files": files,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("opal_drive_list failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 4: appcatalyst_generate ──────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Run inference via AppCatalyst Gemini 3 Flash Preview. "
        "Supports temperature control and system prompts."
    ),
    category="system",
    cooldown=5.0,
    cost=2.0,
    tags=["appcatalyst", "gemini3", "inference"],
)
def appcatalyst_generate(
    prompt: str,
    model: str = "gemini-3-flash-preview",
    temperature: float = 0.7,
    system_prompt: str = "",
    max_tokens: int = 2048,
) -> str:
    """Generate text via AppCatalyst Gemini 3 Flash Preview.

    Args:
        prompt: User prompt text.
        model: Model identifier (default ``"gemini-3-flash-preview"``).
        temperature: Sampling temperature (0.0–2.0).
        system_prompt: Optional system-level instruction.
        max_tokens: Maximum output tokens.

    Returns:
        JSON string with ``text``, ``model``, and status fields.
    """
    from engine.integrations.appcatalyst_client import get_appcatalyst_client
    try:
        client = get_appcatalyst_client()
        result = client.generate(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        return json.dumps({
            "status": "ok",
            "text": result.get("text", ""),
            "model": result.get("model", model),
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("appcatalyst_generate failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 5: appcatalyst_generate_vision ────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Multimodal vision inference via AppCatalyst. "
        "Accepts an image file path and a text prompt."
    ),
    category="system",
    cooldown=8.0,
    cost=3.0,
    tags=["appcatalyst", "vision", "multimodal"],
)
def appcatalyst_generate_vision(
    prompt: str,
    image_path: str,
    model: str = "gemini-3-flash-preview",
) -> str:
    """Multimodal vision inference — image + text prompt.

    Args:
        prompt: Text prompt describing what to analyse.
        image_path: Path to the image file (jpg/png/webp/gif).
        model: Model identifier (must support vision).

    Returns:
        JSON string with ``text`` response and status fields.
    """
    from engine.integrations.appcatalyst_client import get_appcatalyst_client
    import mimetypes
    try:
        img_path = Path(image_path)
        if not img_path.exists():
            return json.dumps({"status": "error", "error": f"Image not found: {image_path}"})
        raw = img_path.read_bytes()
        image_b64 = base64.b64encode(raw).decode("ascii")
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        client = get_appcatalyst_client()
        result = client.generate_vision(
            prompt=prompt,
            image_b64=image_b64,
            model=model,
            mime_type=mime_type,
        )
        return json.dumps({
            "status": "ok",
            "text": result.get("text", ""),
            "model": result.get("model", model),
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("appcatalyst_generate_vision failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 6: appcatalyst_list_models ───────────────────────────────────────


@skill(
    pack="argus_extended",
    description="List all available models on AppCatalyst including Gemini 3 variants.",
    category="system",
    cooldown=10.0,
    cost=0.1,
    tags=["appcatalyst", "models"],
)
def appcatalyst_list_models() -> str:
    """List available AppCatalyst models.

    Returns:
        JSON string with ``models`` list and ``count`` fields.
    """
    from engine.integrations.appcatalyst_client import get_appcatalyst_client
    try:
        client = get_appcatalyst_client()
        models = client.list_models()
        return json.dumps({
            "status": "ok",
            "count": len(models),
            "models": models,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("appcatalyst_list_models failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 7: appcatalyst_embed ─────────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Get a text embedding vector via AppCatalyst. "
        "Returns a float list suitable for similarity search."
    ),
    category="system",
    cooldown=2.0,
    cost=0.5,
    tags=["appcatalyst", "embeddings"],
)
def appcatalyst_embed(
    text: str,
    model: str = "text-embedding-004",
) -> str:
    """Get a text embedding via AppCatalyst.

    Args:
        text: Text to embed.
        model: Embedding model identifier.

    Returns:
        JSON string with ``embedding`` (float list), ``dim``, and status.
    """
    from engine.integrations.appcatalyst_client import get_appcatalyst_client
    try:
        client = get_appcatalyst_client()
        embedding = client.embed(text=text, model=model)
        return json.dumps({
            "status": "ok",
            "dim": len(embedding),
            "embedding": embedding,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("appcatalyst_embed failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 8: gemini_list_storybooks ────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "List available Gemini storybooks (gem content) using rpcid HcT8bb. "
        "Discovered in v1.37 HAR goldmine."
    ),
    category="system",
    cooldown=5.0,
    cost=0.5,
    tags=["gemini", "storybooks", "gems"],
)
def gemini_list_storybooks(
    page_size: int = 20,
    locale: str = "en-AU",
) -> str:
    """List Gemini gem storybooks via rpcid HcT8bb.

    Args:
        page_size: Maximum number of storybooks to return.
        locale: Locale string (e.g. ``"en-AU"``, ``"en-US"``).

    Returns:
        JSON string with ``storybooks`` list and ``count`` fields.
    """
    from engine.integrations.gemini_extended_client import get_gemini_extended_client
    try:
        client = get_gemini_extended_client()
        items = client.list_storybooks(page_size=page_size, locale=locale)
        return json.dumps({
            "status": "ok",
            "count": len(items),
            "storybooks": items,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("gemini_list_storybooks failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 9: gemini_list_saved_info ────────────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Get the user's saved content and bookmarks via Gemini rpcid ZKcapf. "
        "Discovered in v1.37 HAR goldmine."
    ),
    category="system",
    cooldown=5.0,
    cost=0.5,
    tags=["gemini", "saved", "content"],
)
def gemini_list_saved_info(
    category: str = "",
    page_size: int = 100,
) -> str:
    """List the user's saved Gemini content via rpcid ZKcapf.

    Args:
        category: Optional category filter (empty = all).
        page_size: Maximum items to return.

    Returns:
        JSON string with ``items`` list and ``count`` fields.
    """
    from engine.integrations.gemini_extended_client import get_gemini_extended_client
    try:
        client = get_gemini_extended_client()
        items = client.list_saved_info(category=category, page_size=page_size)
        return json.dumps({
            "status": "ok",
            "count": len(items),
            "items": items,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("gemini_list_saved_info failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ──── Skill 10: gemini_get_subscription_tiers ────────────────────────────────


@skill(
    pack="argus_extended",
    description=(
        "Check the user's Gemini subscription tier (Pro/Free) and quota "
        "status via rpcid sJBwce. Discovered in v1.37 HAR goldmine."
    ),
    category="system",
    cooldown=10.0,
    cost=0.1,
    tags=["gemini", "subscription", "quota"],
)
def gemini_get_subscription_tiers() -> str:
    """Get Gemini subscription tier and quota info via rpcid sJBwce.

    Returns:
        JSON string with ``current_tier``, ``available_tiers``, and status.
    """
    from engine.integrations.gemini_extended_client import get_gemini_extended_client
    try:
        client = get_gemini_extended_client()
        result = client.get_subscription_tiers()
        return json.dumps({
            "status": "ok",
            "current_tier": result.get("current_tier"),
            "available_tiers": result.get("available_tiers", []),
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("gemini_get_subscription_tiers failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})
