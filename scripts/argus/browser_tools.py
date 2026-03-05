"""ARGUS Browser MCP Tools — exposes Playwright browser control as MCP skills.

Wires a live Playwright CDP session into the MCP skill system so any LMStudio
agent can drive Chrome autonomously: navigate, click, fill, screenshot, inspect.

Key design: every tool return string is a coaching message. The model reads
tool outputs directly — we embed ARGUS state (visited sections, network count,
next target) so the model is always oriented without relying on turn history.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = Path(r"C:\Files\Models\CosySim\data\har_files\users_dump_folder\screenshots")
VISION_MODEL   = "qwen/qwen3-vl-4b"


# ──── ARGUS session state ────

@dataclass
class ArgusState:
    """Tracks crawl progress — injected into every tool response."""
    sections_all: List[str] = field(default_factory=list)
    sections_visited: List[str] = field(default_factory=list)
    network_total: int = 0
    call_counts: Dict[str, int] = field(default_factory=dict)  # per-tool call count
    # Maps section name → canonical URL from TARGET_NAV_HINTS (set at init)
    section_urls: Dict[str, str] = field(default_factory=dict)

    @property
    def sections_remaining(self) -> List[str]:
        return [s for s in self.sections_all if s not in self.sections_visited]

    @property
    def next_section(self) -> Optional[str]:
        rem = self.sections_remaining
        return rem[0] if rem else None

    def mark_visited(self, section: str) -> None:
        if section not in self.sections_visited:
            self.sections_visited.append(section)

    def increment(self, tool: str) -> int:
        self.call_counts[tool] = self.call_counts.get(tool, 0) + 1
        return self.call_counts[tool]

    def reset_count(self, tool: str) -> None:
        self.call_counts[tool] = 0

    def footer(self, current_url: str = "") -> str:
        visited = ", ".join(self.sections_visited) or "none yet"
        remaining = ", ".join(self.sections_remaining) or "ALL DONE"
        url_line = f"Current URL: {current_url}\n" if current_url else ""
        if self.next_section:
            next_url = self.section_urls.get(self.next_section, "")
            if next_url:
                nxt = f"Next: call argus_navigate('{next_url}')  [section={self.next_section}]"
            else:
                nxt = f"Next target: {self.next_section}"
        else:
            nxt = "All sections complete — call argus_done NOW"
        return (
            f"\n\n--- ARGUS STATE ---\n"
            f"{url_line}"
            f"Visited: [{visited}]\n"
            f"Remaining: [{remaining}]\n"
            f"Network entries captured: {self.network_total}\n"
            f"{nxt}\n"
            f"---"
        )

    def loop_warning(self, tool: str, count: int) -> str:
        nxt = self.next_section or "argus_done"
        return (
            f"\n\nWARNING: You have called {tool} {count} times in a row. "
            f"STOP. Do not call {tool} again. "
            f"Move to the next section immediately: {nxt}"
        )


_state: ArgusState = ArgusState()

# ──── Shared browser session ────

_page: Any = None
_monitor: Any = None
_loop: Any = None
_done: bool = False
_summary: str = ""

_LOOP_LIMIT = 4        # warn after this many calls to the same tool
_TOTAL_CALL_LIMIT = 25 # hard-stop after this many total tool calls per session


def set_browser_context(
    page: Any,
    monitor: Any = None,
    loop: Any = None,
    sections: Optional[List[str]] = None,
    url_hints: Optional[Dict[str, str]] = None,
) -> None:
    """Called by ArgusAgent to share the live Playwright page and sections list.

    Args:
        url_hints: Maps section name → canonical URL (from TARGET_NAV_HINTS).
                   Used by _section_for_url to mark sections visited on navigate.
    """
    global _page, _monitor, _loop, _done, _summary, _state
    _page = page
    _monitor = monitor
    _loop = loop or asyncio.get_event_loop()
    _done = False
    _summary = ""
    _state = ArgusState(
        sections_all=sections or [],
        section_urls=url_hints or {},
    )


def is_done() -> bool:
    """Return True if argus_done has been called."""
    return _done


def _run(coro: Any) -> Any:
    """Run a coroutine from sync context."""
    if _loop and _loop.is_running():
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        return future.result(timeout=30)
    return asyncio.run(coro)


def _check_loop(tool: str) -> Optional[str]:
    """Increment call counter; return hard-stop string if over limit, else None.

    Two limits:
      - Per-tool: warn after _LOOP_LIMIT calls to the same tool
      - Total: force _done=True after _TOTAL_CALL_LIMIT total tool calls
    """
    global _done
    count = _state.increment(tool)

    # Total session cap — force termination (accepts argus_done even with sections remaining)
    total = sum(_state.call_counts.values())
    if total > _TOTAL_CALL_LIMIT:
        _done = True
        return (
            f"HARD STOP — {total} tool calls in this turn. Session limit is {_TOTAL_CALL_LIMIT}. "
            f"STOP ALL TOOL CALLS. Call argus_done NOW with whatever you have captured. "
            f"argus_done will be accepted immediately."
        )

    if count > _LOOP_LIMIT:
        return _state.loop_warning(tool, count)
    return None


# ──── Vision helper ────

def _ask_vision(image_path: Path, question: str) -> str:
    """Feed screenshot to vision model via VisionAgent (LMSClient → /api/v1/chat)."""
    from scripts.argus.vision_agent import get_vision_agent
    return get_vision_agent()._ask_vision(image_path, question)


def _current_url() -> str:
    return _page.url if _page else ""


def _section_for_url(url: str) -> Optional[str]:
    """Return the section name whose canonical URL (or keyword) matches the given URL.

    Priority:
    1. Canonical URL match from section_urls (exact prefix match, strips trailing slash)
    2. Section name keyword in URL (fallback for targets with no URL hints)
    """
    url_clean = url.rstrip("/").lower()

    # 1. Match against known nav-hint URLs — longest canonical first so specific
    #    paths (e.g. /prompts/new_chat) are checked before root paths (e.g. /).
    sorted_hints = sorted(_state.section_urls.items(), key=lambda kv: len(kv[1]), reverse=True)
    for section, canonical in sorted_hints:
        if canonical:
            canonical_clean = canonical.rstrip("/").lower()
            # Exact match OR canonical is a true path prefix (must be followed by /)
            if url_clean == canonical_clean or url_clean.startswith(canonical_clean + "/"):
                return section

    # 2. Keyword fallback
    for section in _state.sections_all:
        slug = section.lower().replace(" ", "")
        if slug in url_clean or section.lower() in url_clean:
            return section

    return None


# ──── MCP Skills ────

@skill(
    pack="argus_browser",
    description=(
        "Take a screenshot of the current page and return a description plus current "
        "crawl state (visited sections, remaining sections, network count, next target)."
    ),
    category="SYSTEM",
)
def argus_screenshot(question: str = "Describe what is visible: URL bar, navigation items, main content area.") -> str:
    """Screenshot + vision description + ARGUS state footer."""
    if _page is None:
        return "ERROR: no browser session active"
    warn = _check_loop("argus_screenshot")
    if warn:
        return warn
    try:
        path = SCREENSHOT_DIR / "argus_agent.png"
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _run(_page.screenshot(path=str(path)))
        description = _ask_vision(path, question)
        # Auto-detect section from current URL
        section = _section_for_url(_current_url())
        if section:
            _state.mark_visited(section)
            _state.reset_count("argus_screenshot")
        return description + _state.footer(_current_url())
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description="Navigate the browser to a URL. Returns landed URL and updated crawl state.",
    category="SYSTEM",
)
def argus_navigate(url: str) -> str:
    """Navigate to URL, auto-mark section visited, return state footer."""
    if _page is None:
        return "ERROR: no browser session"
    nav_key = f"argus_navigate:{url}"
    warn = _check_loop(nav_key)
    if warn:
        return warn
    try:
        _run(_page.goto(url, wait_until="domcontentloaded"))
        _run(asyncio.sleep(1.5))
        landed = _page.url
        # Mark the section for the REQUESTED url (handles redirects — e.g. Home → Playground)
        requested_section = _section_for_url(url)
        landed_section = _section_for_url(landed)
        for sec in {requested_section, landed_section}:
            if sec:
                _state.mark_visited(sec)
        section = requested_section or landed_section
        logger.info("[argus_navigate] url=%s landed=%s section=%s hints=%d", url, landed, section, len(_state.section_urls))
        if section:
            _state.reset_count(nav_key)
        return f"Navigated to: {landed}" + _state.footer(landed)
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description="Click an element on the page by CSS selector or visible text.",
    category="SYSTEM",
)
def argus_click(selector: str) -> str:
    """Click element, return result + state footer."""
    if _page is None:
        return "ERROR: no browser session"
    warn = _check_loop(f"argus_click:{selector}")
    if warn:
        return warn
    try:
        for attempt in [selector, f"text={selector}", f":has-text('{selector}')"]:
            try:
                _run(_page.locator(attempt).first.click(timeout=5_000))
                _run(asyncio.sleep(0.8))
                landed = _page.url
                section = _section_for_url(landed)
                if section:
                    _state.mark_visited(section)
                return f"Clicked: {selector} — now at {landed}" + _state.footer(landed)
            except Exception:
                continue
        return f"ERROR: could not find element: {selector}"
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description="Type text into an input field identified by CSS selector or label.",
    category="SYSTEM",
)
def argus_fill(selector: str, text: str) -> str:
    """Fill a text input field."""
    if _page is None:
        return "ERROR: no browser session"
    try:
        for attempt in [selector, f"[aria-label*='{selector}']", f"[placeholder*='{selector}']"]:
            try:
                _run(_page.locator(attempt).first.fill(text, timeout=5_000))
                return f"Filled '{selector}' with: {text[:50]}"
            except Exception:
                continue
        return f"ERROR: could not find input: {selector}"
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description="Press a keyboard key (e.g. Enter, Tab, Escape).",
    category="SYSTEM",
)
def argus_press(key: str = "Enter") -> str:
    """Press a keyboard key."""
    if _page is None:
        return "ERROR: no browser session"
    try:
        _run(_page.keyboard.press(key))
        _run(asyncio.sleep(0.5))
        return f"Pressed: {key}"
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description="Wait for page load or animations. Max 15 seconds.",
    category="SYSTEM",
)
def argus_wait(seconds: float = 2.0) -> str:
    """Wait for N seconds."""
    warn = _check_loop("argus_wait")
    if warn:
        return warn
    _run(asyncio.sleep(min(seconds, 15.0)))
    return f"Waited {seconds}s"


@skill(
    pack="argus_browser",
    description="Get the current page URL.",
    category="SYSTEM",
)
def argus_current_url() -> str:
    """Return the current browser URL."""
    if _page is None:
        return "ERROR: no browser session"
    return _page.url + _state.footer(_page.url)


@skill(
    pack="argus_browser",
    description=(
        "Get all network API calls captured since the last drain. "
        "Returns JSON list of requests plus crawl state and next action."
    ),
    category="SYSTEM",
)
def argus_get_network_log() -> str:
    """Drain network log, update total count, return entries + coaching footer."""
    if _monitor is None:
        return "ERROR: no network monitor active"
    warn = _check_loop("argus_get_network_log")
    if warn:
        return warn
    try:
        requests = _run(_monitor.drain())
        results = []
        for r in requests:
            results.append({
                "url": r.url[:120],
                "method": r.method,
                "is_batchexecute": r.is_batchexecute,
                "is_grpc_web": r.is_grpc_web,
                "rpcids": getattr(r, "rpcids", []),
            })
        _state.network_total += len(results)
        _state.reset_count("argus_get_network_log")
        nxt = _state.next_section
        action = f"Navigate to the next section: {nxt}" if nxt else "All sections done — call argus_done NOW"
        return (
            json.dumps(results, indent=2)
            + f"\n\n--- NETWORK LOG ---\n"
            f"New entries: {len(results)} | Total captured: {_state.network_total}\n"
            f"{action}\n"
            f"---"
            + _state.footer(_current_url())
        )
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description="Run JavaScript in the page and return the result.",
    category="SYSTEM",
)
def argus_run_js(code: str) -> str:
    """Evaluate JavaScript and return result."""
    if _page is None:
        return "ERROR: no browser session"
    try:
        result = _run(_page.evaluate(f"() => {{ {code} }}"))
        return str(result)[:500]
    except Exception as exc:
        return f"ERROR: {exc}"


@skill(
    pack="argus_browser",
    description=(
        "Signal that the crawl mission is complete. Call this ONLY when ALL sections "
        "have been visited. Provide a summary of what API calls were captured."
    ),
    category="SYSTEM",
)
def argus_done(summary: str = "Crawl complete.") -> str:
    """Signal crawl completion — accepted immediately if hard-stop fired, else rejected if sections unvisited."""
    global _done, _summary
    # Accept unconditionally if hard-stop already fired
    if _done:
        _summary = summary
        visited = ", ".join(_state.sections_visited) or "none"
        remaining = _state.sections_remaining
        return (
            f"CRAWL ENDED (hard-stop).\n"
            f"Sections visited: [{visited}]\n"
            f"Sections NOT visited: {remaining}\n"
            f"Network entries captured: {_state.network_total}\n"
            f"Summary: {summary[:300]}"
        )
    remaining = _state.sections_remaining
    if remaining:
        return (
            f"REJECTED: {len(remaining)} section(s) not yet visited: {remaining}. "
            f"You MUST visit ALL sections before calling argus_done. "
            f"Next section: {remaining[0]}"
        )
    _done = True
    _summary = summary
    logger.info("ArgusAgent: done — %s", summary[:200])
    visited = ", ".join(_state.sections_visited) or "none"
    return (
        f"CRAWL COMPLETE.\n"
        f"Sections visited: [{visited}]\n"
        f"Network entries captured: {_state.network_total}\n"
        f"Summary: {summary[:300]}"
    )


@skill(
    pack="argus_browser",
    description="Get the visible text content of the current page.",
    category="SYSTEM",
)
def argus_get_page_text() -> str:
    """Return visible text from the page body."""
    if _page is None:
        return "ERROR: no browser session"
    try:
        text = _run(_page.inner_text("body"))
        return text[:2000]
    except Exception as exc:
        return f"ERROR: {exc}"


def get_summary() -> str:
    """Return the summary string set by argus_done."""
    return _summary


# ──── _impl aliases for argus_mcp_server.py ────

_argus_screenshot_impl    = argus_screenshot
_argus_navigate_impl      = argus_navigate
_argus_click_impl         = argus_click
_argus_fill_impl          = argus_fill
_argus_press_impl         = argus_press
_argus_wait_impl          = argus_wait
_argus_current_url_impl   = argus_current_url
_argus_get_network_log_impl = argus_get_network_log
_argus_run_js_impl        = argus_run_js
_argus_get_page_text_impl = argus_get_page_text
_argus_done_impl          = argus_done
