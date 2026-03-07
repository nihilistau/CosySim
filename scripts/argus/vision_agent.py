"""ARGUS Vision Agent — screenshot and ask qwen3-vl-4b via LMStudio Python SDK.

Uses lms.Client() (sync) with client.files.prepare_image() for native multimodal support.

Usage::

    from scripts.argus.vision_agent import VisionAgent, get_vision_agent
    agent = VisionAgent()

    # Desktop: screenshot Chrome foreground window
    answer = agent.ask("What page is showing on the AIStudio tab?")

    # Playwright: screenshot a specific page (async context)
    answer = await agent.ask_page("Is the Playground chat input visible?", page)

    # Quick visible check
    visible, reason = await agent.check_visible("Playground nav link", page)
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from scripts.argus.paths import SCREENSHOT_SCRIPT_PATH, SCREENSHOTS_DIR

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

SCREENSHOT_SCRIPT = SCREENSHOT_SCRIPT_PATH
SCREENSHOT_DIR = SCREENSHOTS_DIR
VISION_MODEL = "qwen/qwen3-vl-4b"

SYSTEM_PROMPT = (
    "You are working with an agent who is debugging a web app. "
    "The agent has no vision so you must be their eyes. "
    "Analyze the screenshot provided and answer questions about what is visible. "
    "Be precise: describe the current URL, navigation elements, error messages, "
    "buttons, form inputs, and any relevant UI state."
)


class VisionAgent:
    """Screenshot Chrome and ask the qwen3-vl vision model questions about it.

    All inference goes through lmstudio.Client (sync SDK) — no raw HTTP, no asyncio.
    """

    def __init__(self, model: str = VISION_MODEL) -> None:
        self._model = model

    # ──── Screenshot helpers ────

    def screenshot_desktop(self) -> Optional[Path]:
        """Capture Chrome foreground window via PowerShell script."""
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(SCREENSHOT_SCRIPT)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.error("VisionAgent: PS1 failed: %s", result.stderr[:200])
                return None
            files = sorted(SCREENSHOT_DIR.glob("Chrome_Capture_*.png"))
            return files[-1] if files else None
        except Exception as exc:
            logger.error("VisionAgent: desktop screenshot error: %s", exc)
            return None

    async def screenshot_page(self, page: "Page") -> Optional[Path]:
        """Take a Playwright screenshot of a specific page (most reliable)."""
        try:
            ts = time.strftime("%Y-%m-%d_%H-%M-%S")
            path = SCREENSHOT_DIR / f"Playwright_Capture_{ts}.png"
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(path), full_page=False)
            logger.debug("VisionAgent: playwright screenshot → %s", path)
            return path
        except Exception as exc:
            logger.error("VisionAgent: playwright screenshot error: %s", exc)
            return None

    # ──── Ask methods ────

    def ask(self, question: str, image_path: Optional[Path] = None) -> str:
        """Take a desktop screenshot (or use provided path) and ask a question."""
        if image_path is None:
            image_path = self.screenshot_desktop()
        if not image_path:
            return "ERROR: could not take screenshot"
        return self._ask_vision(image_path, question)

    def describe(self, question: str = "Describe what Chrome is currently showing.") -> str:
        """Convenience wrapper: screenshot desktop and describe."""
        return self.ask(question)

    async def ask_page(self, question: str, page: "Page") -> str:
        """Playwright mode: screenshot a page and ask a question."""
        path = await self.screenshot_page(page)
        if not path:
            return "ERROR: could not screenshot page"
        return self._ask_vision(path, question)

    async def check_visible(self, element: str, page: "Page") -> Tuple[bool, str]:
        """Return (is_visible, reasoning) for a described UI element."""
        response = await self.ask_page(
            f"Is '{element}' visible in this screenshot? "
            "Answer YES or NO on the first line, then explain briefly.",
            page,
        )
        is_visible = "YES" in response.strip().split("\n")[0].upper()
        return is_visible, response

    async def current_url(self, page: "Page") -> str:
        """Extract the URL from the browser address bar in a Playwright screenshot."""
        return await self.ask_page(
            "What is the exact URL shown in the browser address bar? Reply with just the URL.",
            page,
        )

    # ──── Core inference ────

    def _ask_vision(self, image_path: Path, question: str) -> str:
        """Send image + question to vision model via OpenAI-compat REST (sync httpx)."""
        try:
            import base64
            import httpx as _httpx
            from engine.config import get_config
            cfg = get_config()
            host = cfg.get("lmstudio.host", "localhost")
            port = cfg.get("lmstudio.port", 1234)
            token = cfg.get("lmstudio.api_token", "")
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            data_url = f"data:image/png;base64,{img_b64}"
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": question},
                    ]},
                ],
                "max_tokens": 512,
                "temperature": 0.1,
            }
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            r = _httpx.post(
                f"http://{host}:{port}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("VisionAgent: vision query failed: %s", exc)
            return f"ERROR: {exc}"


# ──── Singleton ────

_agent: Optional[VisionAgent] = None


def get_vision_agent() -> VisionAgent:
    """Return the shared VisionAgent instance."""
    global _agent
    if _agent is None:
        _agent = VisionAgent()
    return _agent


# ──── CLI ────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Describe what Chrome is showing."
    print(VisionAgent().ask(question))
