"""Vision skills for CosySim.

Provides MCP-accessible vision capabilities using VLM models via LMStudio.
Supports screenshot analysis, UI extraction, image comparison, and OCR-style
text reading.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────

VISION_MODEL = "qwen/qwen3-vl-4b"


def _get_client():
    """Lazy import to avoid circular deps."""
    from engine.lmstudio.lms_client import get_lms_client
    return get_lms_client()


def _resolve_vision_model() -> str:
    """Resolve the vision model from config or fallback to default."""
    try:
        from engine.config import get_config
        cfg = get_config()
        return cfg.get("lmstudio.models.vision", VISION_MODEL)
    except Exception:
        return VISION_MODEL


def _image_to_data_url(image_path: str) -> str:
    """Convert a local image file to a base64 data URL."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    ext = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(ext, "image/png")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _ask_vision(image_path: str, question: str, *, system: str = "") -> str:
    """Send an image + question to the vision model and return the response."""
    client = _get_client()
    model = _resolve_vision_model()

    if image_path.startswith(("data:", "http://", "https://")):
        data_url = image_path
    else:
        data_url = _image_to_data_url(image_path)

    if not system:
        system = (
            "You are a precise vision analysis assistant. "
            "Describe exactly what you see. Be specific and structured."
        )

    start = time.monotonic()
    response = client.chat_with_images(
        text=question,
        image_urls=[data_url],
        system=system,
        model=model,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    text = response.text if hasattr(response, "text") else str(response)
    logger.info("Vision query completed in %dms (model=%s)", elapsed_ms, model)
    return text


# ── Skills ───────────────────────────────────────────────────────────


@skill(
    pack="vision",
    description=(
        "Analyze a screenshot or image and describe its contents in detail. "
        "Returns a natural-language description of what is visible."
    ),
    category="MEDIA",
    tags=["vision", "screenshot", "describe", "vlm"],
    cooldown=2.0,
    cost=2.0,
)
def screen_to_text(image_path: str, focus: str = "") -> str:
    """Describe the contents of a screenshot or image.

    Args:
        image_path: Path to a PNG/JPG image file, a data URL, or an HTTP URL.
        focus: Optional area to focus on (e.g. 'the toolbar', 'error dialog').

    Returns:
        Natural-language description of the image contents.
    """
    try:
        question = "Describe everything visible in this screenshot in detail."
        if focus:
            question = (
                f"Focus on {focus} in this screenshot. "
                "Describe what you see in detail."
            )
        return _ask_vision(image_path, question)
    except FileNotFoundError:
        return f"Error: Image file not found at {image_path}"
    except Exception as exc:
        logger.warning("screen_to_text failed: %s", exc)
        return f"Vision analysis failed: {exc}"


@skill(
    pack="vision",
    description=(
        "Analyze a UI screenshot and extract structured information about "
        "visible UI elements: buttons, inputs, labels, menus, dialogs, etc."
    ),
    category="MEDIA",
    tags=["vision", "ui", "extraction", "elements", "vlm"],
    cooldown=2.0,
    cost=2.0,
)
def ui_analysis(image_path: str, element_types: str = "") -> str:
    """Extract structured UI element information from a screenshot.

    Args:
        image_path: Path to a UI screenshot.
        element_types: Comma-separated element types to focus on
            (e.g. 'buttons,inputs,labels'). Empty means all elements.

    Returns:
        Structured description of UI elements with approximate positions.
    """
    try:
        system = (
            "You are a UI analysis expert. Extract all visible UI elements "
            "from screenshots. For each element, identify: type (button, input, "
            "label, menu, dialog, icon, link, toggle, dropdown, etc.), text/label, "
            "approximate position (top-left, center, bottom-right, etc.), and state "
            "(enabled, disabled, selected, focused, error). Return results as a "
            "structured list."
        )
        question = "List all UI elements visible in this screenshot with their types, labels, positions, and states."
        if element_types:
            types = [t.strip() for t in element_types.split(",")]
            question = (
                f"List all {', '.join(types)} elements visible in this screenshot "
                "with their labels, positions, and states."
            )
        return _ask_vision(image_path, question, system=system)
    except FileNotFoundError:
        return f"Error: Image file not found at {image_path}"
    except Exception as exc:
        logger.warning("ui_analysis failed: %s", exc)
        return f"UI analysis failed: {exc}"


@skill(
    pack="vision",
    description=(
        "Compare two screenshots and describe the visual differences. "
        "Useful for detecting UI changes, regressions, or state transitions."
    ),
    category="MEDIA",
    tags=["vision", "compare", "diff", "screenshots", "vlm"],
    cooldown=3.0,
    cost=3.0,
)
def compare_screenshots(before_path: str, after_path: str, context: str = "") -> str:
    """Compare two screenshots and describe what changed.

    Args:
        before_path: Path to the 'before' screenshot.
        after_path: Path to the 'after' screenshot.
        context: Optional context about what action was performed between screenshots.

    Returns:
        Description of visual differences between the two images.
    """
    try:
        if before_path.startswith(("data:", "http://", "https://")):
            before_url = before_path
        else:
            before_url = _image_to_data_url(before_path)

        if after_path.startswith(("data:", "http://", "https://")):
            after_url = after_path
        else:
            after_url = _image_to_data_url(after_path)

        client = _get_client()
        model = _resolve_vision_model()

        system = (
            "You are a visual diff expert. Compare two screenshots and identify "
            "all differences: added elements, removed elements, changed text, "
            "color changes, layout shifts, new dialogs, state changes, etc. "
            "Be precise and exhaustive."
        )
        question = "Compare these two screenshots. The first is BEFORE, the second is AFTER."
        if context:
            question += f" The action performed between them: {context}"
        question += " List all visual differences you can identify."

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": before_url}},
                {"type": "image_url", "image_url": {"url": after_url}},
            ]},
        ]

        start = time.monotonic()
        response = client.chat(messages, model=model)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        text = response.text if hasattr(response, "text") else str(response)
        logger.info("Screenshot comparison completed in %dms", elapsed_ms)
        return text
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as exc:
        logger.warning("compare_screenshots failed: %s", exc)
        return f"Screenshot comparison failed: {exc}"


@skill(
    pack="vision",
    description=(
        "Extract all readable text from an image using a vision language model. "
        "Works like OCR but powered by a VLM for better accuracy with styled text."
    ),
    category="MEDIA",
    tags=["vision", "ocr", "text", "extraction", "vlm"],
    cooldown=2.0,
    cost=2.0,
)
def read_text_from_image(image_path: str, region: str = "") -> str:
    """Extract readable text from an image.

    Args:
        image_path: Path to the image file.
        region: Optional region to focus on (e.g. 'header', 'body text',
            'error message', 'code block').

    Returns:
        All readable text extracted from the image.
    """
    try:
        system = (
            "You are a text extraction specialist. Read and transcribe ALL text "
            "visible in the image exactly as it appears. Preserve formatting, "
            "line breaks, and structure. Include text from buttons, labels, "
            "headings, body text, error messages, tooltips, and any other "
            "readable content. Do not describe the image — only output the text."
        )
        question = "Extract and transcribe all readable text from this image exactly as it appears."
        if region:
            question = (
                f"Extract and transcribe all readable text from the {region} "
                "area of this image exactly as it appears."
            )
        return _ask_vision(image_path, question, system=system)
    except FileNotFoundError:
        return f"Error: Image file not found at {image_path}"
    except Exception as exc:
        logger.warning("read_text_from_image failed: %s", exc)
        return f"Text extraction failed: {exc}"


@skill(
    pack="vision",
    description=(
        "Take a screenshot of the current desktop or a specific window and "
        "return the file path. Requires PowerShell on Windows."
    ),
    category="SYSTEM",
    tags=["vision", "screenshot", "capture", "desktop"],
    cooldown=1.0,
    cost=1.0,
)
def capture_screenshot(target: str = "desktop") -> str:
    """Capture a screenshot and save it to disk.

    Args:
        target: What to capture — 'desktop' for full screen, or a window title
            substring to capture a specific window.

    Returns:
        Path to the saved screenshot file.
    """
    import subprocess

    try:
        screenshots_dir = Path("artifacts/screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        output_path = screenshots_dir / f"capture_{timestamp}.png"

        if os.name == "nt":
            ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save('{output_path.as_posix()}')
$graphics.Dispose()
$bitmap.Dispose()
"""
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return f"Screenshot capture failed: {result.stderr.strip()}"
        else:
            result = subprocess.run(
                ["import", "-window", "root", str(output_path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return f"Screenshot capture failed (requires ImageMagick): {result.stderr.strip()}"

        if output_path.exists():
            return str(output_path)
        return "Screenshot capture completed but file not found"
    except subprocess.TimeoutExpired:
        return "Screenshot capture timed out"
    except Exception as exc:
        logger.warning("capture_screenshot failed: %s", exc)
        return f"Screenshot capture failed: {exc}"
