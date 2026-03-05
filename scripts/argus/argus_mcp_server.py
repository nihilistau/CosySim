"""Argus Browser MCP Server — in-process FastMCP SSE server for browser tools.

Runs on port 8010 inside the ArgusAgent process so LMStudio can call the
browser skills via ephemeral_mcp integration.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

ARGUS_MCP_PORT = 8010
ARGUS_MCP_URL  = f"http://127.0.0.1:{ARGUS_MCP_PORT}/sse"

mcp = FastMCP("ArgusBrowser", instructions="Playwright browser control tools for ARGUS.")


@mcp.tool()
def argus_screenshot(question: str = "Describe the current page.") -> str:
    """Take a screenshot and ask the vision model what it sees."""
    from scripts.argus.browser_tools import _argus_screenshot_impl
    return _argus_screenshot_impl(question)


@mcp.tool()
def argus_navigate(url: str) -> str:
    """Navigate the browser to a URL."""
    from scripts.argus.browser_tools import _argus_navigate_impl
    return _argus_navigate_impl(url)


@mcp.tool()
def argus_click(selector: str) -> str:
    """Click an element by CSS selector or visible text."""
    from scripts.argus.browser_tools import _argus_click_impl
    return _argus_click_impl(selector)


@mcp.tool()
def argus_fill(selector: str, text: str) -> str:
    """Type text into an input field identified by selector or label."""
    from scripts.argus.browser_tools import _argus_fill_impl
    return _argus_fill_impl(selector, text)


@mcp.tool()
def argus_press(key: str = "Enter") -> str:
    """Press a keyboard key."""
    from scripts.argus.browser_tools import _argus_press_impl
    return _argus_press_impl(key)


@mcp.tool()
def argus_wait(seconds: float = 2.0) -> str:
    """Wait N seconds for the page to settle."""
    from scripts.argus.browser_tools import _argus_wait_impl
    return _argus_wait_impl(seconds)


@mcp.tool()
def argus_current_url() -> str:
    """Return the current browser URL."""
    from scripts.argus.browser_tools import _argus_current_url_impl
    return _argus_current_url_impl()


@mcp.tool()
def argus_get_network_log() -> str:
    """Return all API calls captured since the last call. Call after every action."""
    from scripts.argus.browser_tools import _argus_get_network_log_impl
    return _argus_get_network_log_impl()


@mcp.tool()
def argus_run_js(code: str) -> str:
    """Execute JavaScript in the browser and return the result."""
    from scripts.argus.browser_tools import _argus_run_js_impl
    return _argus_run_js_impl(code)


@mcp.tool()
def argus_get_page_text() -> str:
    """Get the visible text content of the current page."""
    from scripts.argus.browser_tools import _argus_get_page_text_impl
    return _argus_get_page_text_impl()


@mcp.tool()
def argus_done(summary: str) -> str:
    """Signal that crawling is complete. Call when all major sections have been visited."""
    from scripts.argus.browser_tools import _argus_done_impl
    return _argus_done_impl(summary)


_server_thread: Optional[threading.Thread] = None


async def start_server() -> None:
    """Start the FastMCP SSE server in a background thread, wait until ready."""
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        logger.info("Argus MCP server already running at %s", ARGUS_MCP_URL)
        return

    import socket

    ready = threading.Event()

    def _run() -> None:
        # mcp.run(transport="sse") blocks; signals ready before binding
        # We poll the port instead to know when it's actually up
        mcp.run(transport="sse", host="127.0.0.1", port=ARGUS_MCP_PORT)

    _server_thread = threading.Thread(target=_run, daemon=True)
    _server_thread.start()

    # Wait until the port is actually accepting connections
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.2)
        try:
            with socket.create_connection(("127.0.0.1", ARGUS_MCP_PORT), timeout=0.5):
                break
        except OSError:
            pass

    logger.info("Argus MCP server running at %s", ARGUS_MCP_URL)
