"""SVG Generator — LLM-powered SVG icon and graphic generation.

Uses LMStudio to generate valid SVG markup from natural-language descriptions.
The PromptBuilder produces a detailed instruction string; the LLM returns raw
SVG which is validated and saved.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_OUTPUT_DIR_KEY = "asset_studio.svg_output_dir"
_DEFAULT_OUTPUT_DIR = "data/asset_studio/svg"

# Validate that the LLM returned something resembling an SVG.
_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)


class SvgGenerator:
    """Generate SVG assets using LMStudio as the backend."""

    def __init__(self) -> None:
        """Initialise, ensuring output directory exists."""
        cfg = get_config()
        self._output_dir = Path(cfg.get(_OUTPUT_DIR_KEY, _DEFAULT_OUTPUT_DIR))
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        subject: str,
        style: str = "minimal",
        scene: str = "",
        colors: Optional[List[str]] = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate an SVG from a natural-language description.

        Args:
            subject: What the SVG depicts.
            style: Visual style hint (minimal|detailed|logo|icon|ornate).
            scene: Scene context for color palette.
            colors: Explicit hex color list to use.

        Returns:
            Dict with ``url``, ``svg_content``, ``duration_ms``.
        """
        from engine.asset_studio.prompt_builder import get_prompt_builder  # noqa: PLC0415

        builder = get_prompt_builder()
        description = builder.build_svg_description(
            subject=subject,
            style=style,
            scene=scene,
            colors=colors,
        )

        t_start = time.monotonic()
        try:
            svg_content = self._call_llm(description)
            validated = self._extract_svg(svg_content)
            duration_ms = int((time.monotonic() - t_start) * 1000)

            if not validated:
                raise ValueError("LLM did not return valid SVG markup")

            filename = f"svg_{uuid.uuid4().hex[:12]}.svg"
            out_path = self._output_dir / filename
            out_path.write_text(validated, encoding="utf-8")

            return {
                "url": f"/asset_studio/svg/{filename}",
                "file_path": str(out_path),
                "svg_content": validated,
                "cached": False,
                "duration_ms": duration_ms,
                "subject": subject,
                "style": style,
                "scene": scene,
            }

        except Exception as exc:
            logger.warning("SVG generation failed: %s", exc)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            fallback_svg = self._fallback_svg(subject)
            return {
                "url": "",
                "svg_content": fallback_svg,
                "cached": False,
                "duration_ms": duration_ms,
                "subject": subject,
                "error": str(exc),
            }

    def _call_llm(self, description: str) -> str:
        """Submit the SVG description to LMStudio and return the response."""
        from engine.lmstudio.client import get_lmstudio_client  # noqa: PLC0415
        client = get_lmstudio_client()
        response = client.complete(description, max_tokens=2000, temperature=0.3)
        return response.strip()

    @staticmethod
    def _extract_svg(text: str) -> str:
        """Extract the first valid <svg>…</svg> block from *text*."""
        # Strip markdown fences if present.
        text = re.sub(r"```(?:svg|xml)?\n?", "", text).strip().rstrip("`").strip()
        match = _SVG_RE.search(text)
        return match.group(0) if match else ""

    @staticmethod
    def _fallback_svg(subject: str) -> str:
        """Return a minimal placeholder SVG when generation fails."""
        safe = subject[:30].replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg">'
            f'<rect width="512" height="512" fill="#1a1a2e"/>'
            f'<text x="256" y="256" fill="#8b5cf6" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="28" font-family="sans-serif">'
            f"{safe}"
            f"</text></svg>"
        )
