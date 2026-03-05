"""ARGUS Agent — LMStudio v1 REST API + ephemeral MCP server.

Architecture:
  1. argus_mcp_server.py (FastMCP SSE on :8010) exposes @skill-decorated browser tools
     — LMStudio discovers and calls them via the MCP protocol
  2. LMStudio v1 REST /api/v1/chat with integrations=[MCP.ephemeral(ARGUS_MCP_URL)]
     — tools are called server-side, results streamed back via SSE

  3. Hybrid conversation state:

     Server-side (primary):
       _primed_id   — single init anchor (system prompt + nav map, store=True)
       _progress_id — advances after each section visit (store=True)
       previous_response_id used on every tool turn for efficient KV reuse.
       Loop kill → branch from _primed_id (restore clean context).

     Local mirror (backup):
       self._history — plain List[Dict] kept in sync with the server-side state.
       If server state is lost (response_id rejected, model reloaded), _post_turn
       automatically falls back to replaying self._history as the input array.
       This makes the agent resilient to LMStudio restarts mid-crawl.

  4. SSE stream parsed in real-time for loop detection + stream kill via aclose().

Usage::

    python -m scripts.argus.agent --target aistudio
    python -m scripts.argus.agent --target nlm
    python -m scripts.argus.agent --target all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from playwright.async_api import async_playwright

from engine.config import get_config
from scripts.argus.argus_mcp_server import ARGUS_MCP_URL, start_server as start_argus_mcp
from scripts.argus.browser_tools import get_summary, is_done, set_browser_context
from scripts.argus.config import CDP_URL, TARGETS
from scripts.argus.network_monitor import NetworkMonitor
from scripts.argus.vision_agent import VisionAgent

logger = logging.getLogger(__name__)

ARGUS_MODEL = "qwen/qwen3-vl-4b"
ARGUS_TOOLS = [
    "argus_screenshot",
    "argus_navigate",
    "argus_click",
    "argus_fill",
    "argus_press",
    "argus_wait",
    "argus_current_url",
    "argus_get_network_log",
    "argus_run_js",
    "argus_get_page_text",
    "argus_done",
]

TARGET_SECTIONS: Dict[str, List[str]] = {
    "aistudio": [
        "Home", "Playground", "Apps", "Files", "Tuning", "Settings",
        # Dark corners — rarely crawled, high rpcid yield
        "Grounding", "API Keys", "Models", "Usage",
    ],
    "notebooklm": [
        "open notebook", "view sources", "generate study guide", "send chat message",
        # Dark corners — Studio panel features that trigger hidden rpcids
        "audio overview", "video overview", "data table",
    ],
    "gemini": [
        "start conversation", "send message", "try different model", "explore sidebar",
        # Dark corners — settings/extensions/history endpoints
        "extensions", "activity", "advanced settings",
    ],
}

# Exact canonical URLs per section — used for URL→section matching in browser_tools
TARGET_SECTION_URLS: Dict[str, Dict[str, str]] = {
    "aistudio": {
        "Home":       "https://aistudio.google.com/",
        "Playground": "https://aistudio.google.com/prompts/new_chat",
        "Apps":       "https://aistudio.google.com/apps",
        "Files":      "https://aistudio.google.com/files",
        "Tuning":     "https://aistudio.google.com/tune",
        "Settings":   "https://aistudio.google.com/settings",
        "Grounding":  "https://aistudio.google.com/grounding",
        "API Keys":   "https://aistudio.google.com/apikey",
        "Models":     "https://aistudio.google.com/models",
        "Usage":      "https://aistudio.google.com/usage",
    },
    "notebooklm": {
        "open notebook": "https://notebooklm.google.com/",
    },
    "gemini": {
        "start conversation": "https://gemini.google.com/",
        "extensions":         "https://gemini.google.com/extensions",
        "activity":           "https://myactivity.google.com/product/gemini",
        "advanced settings":  "https://gemini.google.com/settings",
    },
}

# Human-readable nav instructions per section — injected into turn messages
TARGET_NAV_HINTS: Dict[str, Dict[str, str]] = {
    "aistudio": {
        "Home":       "call argus_navigate('https://aistudio.google.com/')",
        "Playground": "call argus_navigate('https://aistudio.google.com/prompts/new_chat')",
        "Apps":       "call argus_navigate('https://aistudio.google.com/apps')",
        "Files":      "call argus_navigate('https://aistudio.google.com/files')",
        "Tuning":     "call argus_navigate('https://aistudio.google.com/tune')",
        "Settings":   "call argus_navigate('https://aistudio.google.com/settings')",
        "Grounding":  "call argus_navigate('https://aistudio.google.com/grounding')",
        "API Keys":   "call argus_navigate('https://aistudio.google.com/apikey')",
        "Models":     "call argus_navigate('https://aistudio.google.com/models')",
        "Usage":      "call argus_navigate('https://aistudio.google.com/usage')",
    },
    "notebooklm": {
        "open notebook":     "call argus_navigate('https://notebooklm.google.com/')",
        "view sources":      "click the Sources tab or panel in the current notebook",
        "generate study guide": "click the 'Study guide' button in the notebook Studio panel",
        "send chat message": "click the chat input at the bottom and type a test message",
        "audio overview":    "click 'Audio Overview' in the Studio panel, then click Generate",
        "video overview":    "click 'Video Overview' in the Studio panel, then click Generate",
        "data table":        "click 'Data table' in the Studio panel to trigger table generation",
    },
    "gemini": {
        "start conversation": "call argus_navigate('https://gemini.google.com/')",
        "send message":       "click the chat input field and type a short test message",
        "try different model": "click the model selector dropdown in the top bar",
        "explore sidebar":    "click the hamburger/menu icon to open the sidebar",
        "extensions":         "call argus_navigate('https://gemini.google.com/extensions')",
        "activity":           "call argus_navigate('https://myactivity.google.com/product/gemini')",
        "advanced settings":  "call argus_navigate('https://gemini.google.com/settings')",
    },
}

SYSTEM_PROMPT = """\
You are ARGUS, an autonomous web API discovery agent. You control a live Chrome \
browser via tools provided by the MCP server.

RULES (follow exactly):
1. Never explain or think out loud — only call tools.
2. Start every new section with argus_screenshot to orient yourself.
3. Visit sections IN ORDER, one at a time — do not skip ahead.
4. After each section: call argus_get_network_log to capture API calls, then move on.
5. Never repeat the exact same tool call with the same arguments twice in a row.
6. Every tool response includes an ARGUS STATE footer — read visited/remaining and obey it.
7. Call argus_done ONLY when the ARGUS STATE footer says "All sections complete".\
"""


class ArgusAgent:
    """ARGUS autonomous crawler — v1 REST + ephemeral MCP + anchor-chain context."""

    def __init__(self, target: str, max_turns: int = 35) -> None:
        self.target = target
        self.max_turns = max_turns
        self._cfg = TARGETS.get(target, {})
        self._all_network: List[Dict] = []

        # Server-side anchor IDs (store=True — efficient KV reuse)
        self._primed_id: Optional[str] = None    # single init anchor
        self._progress_id: Optional[str] = None  # advances per section

        # Local history mirror — kept in sync; used as fallback if server state is lost
        self._history: List[Dict[str, str]] = []
        self._init_history_len: int = 0  # len(_history) after init — for loop-kill reset

        cfg = get_config()
        host = cfg.get("lmstudio.host", "localhost")
        port = cfg.get("lmstudio.port", 1234)
        self._base_url = f"http://{host}:{port}/api/v1/chat"
        token = cfg.get("lmstudio.api_token", "")
        self._headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    # ──── Local history persistence ────

    @property
    def _history_path(self) -> Path:
        return Path("data/argus") / f"{self.target}_history.json"

    def _save_history(self) -> None:
        """Persist local history mirror to disk after each store=True turn."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            self._history_path.write_text(
                json.dumps(self._history, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("_save_history failed: %s", exc)

    def _load_history(self) -> bool:
        """Load history from disk on init (resume support). Returns True if loaded."""
        if not self._history_path.exists():
            return False
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                self._history = data
                self._init_history_len = len(data)
                logger.info("ARGUS resumed from history (%d messages)", len(data))
                return True
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("_load_history failed: %s", exc)
        return False

    # ──── MCP integration descriptor ────

    def _mcp_integration(self) -> Dict[str, Any]:
        return {
            "type": "ephemeral_mcp",
            "server_url": ARGUS_MCP_URL,
            "server_label": "argus_browser",
            "allowed_tools": ARGUS_TOOLS,
        }

    # ──── Non-streaming store helper ────

    async def _store_message(
        self,
        text: str,
        previous_id: Optional[str] = None,
    ) -> str:
        """POST a plain text message (no tools), store=True, return response_id.

        Used to build/advance anchors without burning a tool-calling turn.
        The model's reply is irrelevant — we only care about the stored response_id.
        """
        payload: Dict[str, Any] = {
            "model": ARGUS_MODEL,
            "input": text,
            "stream": False,
            "store": True,
            "temperature": 0.0,
        }
        if previous_id:
            payload["previous_response_id"] = previous_id
        async with httpx.AsyncClient(timeout=60.0, headers=self._headers) as client:
            for attempt in range(3):
                r = await client.post(self._base_url, json=payload)
                if r.status_code == 500 and attempt < 2:
                    logger.warning("_store_message got 500 (attempt %d/3) — retrying in 5s", attempt + 1)
                    await asyncio.sleep(5)
                    continue
                r.raise_for_status()
                break
            data = r.json()
        return data.get("response_id") or data.get("id") or ""

    # ──── Session init: build anchor chain ────

    async def _init_session(self, sections: List[str]) -> None:
        """Build a single primed anchor (system prompt + nav map in one store call).

        With max_streams=1, sending multiple store:True calls back-to-back fills
        the single slot and causes queuing.  One combined message avoids that.

        _root_id == _primed_id — the single warm anchor.
        _progress_id starts there and advances per section visited.
        Loop kills branch back to _primed_id for a clean context reset.
        """
        tool_list = "\n".join(f"  • {t}()" for t in ARGUS_TOOLS)

        urls = TARGET_SECTION_URLS.get(self.target, {})
        hints = TARGET_NAV_HINTS.get(self.target, {})
        section_list = " → ".join(sections)
        nav_lines = "\n".join(
            f"  {s}: {urls.get(s) or hints.get(s, '?')}" for s in sections
        )

        # Single combined message: system context + tool list + nav map
        init_msg = (
            f"{SYSTEM_PROMPT}\n\n"
            f"Available tools (via MCP):\n{tool_list}\n\n"
            f"NAV MAP — {self.target} ({len(sections)} sections)\n\n"
            f"Visit IN ORDER: {section_list}\n\n"
            f"Exact navigation commands:\n{nav_lines}\n\n"
            "Workflow per section:\n"
            "  1. argus_navigate(exact_url_above)\n"
            "  2. argus_get_network_log() — capture all API calls made\n"
            "  3. Move to next section immediately\n\n"
            "DO NOT navigate to any URL not listed above.\n"
            "Reply: ARGUS READY"
        )

        # ONE store call — keeps max_streams=1 happy
        self._primed_id = await self._store_message(init_msg, previous_id=None)
        self._root_id = self._primed_id  # alias — no separate root anchor needed
        self._progress_id = self._primed_id
        # Seed local history mirror with the same init exchange
        self._history = [
            {"role": "user", "content": init_msg},
            {"role": "assistant", "content": "ARGUS READY"},
        ]
        self._init_history_len = len(self._history)
        logger.info("ARGUS init anchor primed_id=%s — crawl ready", self._primed_id)

    # ──── Advance progress anchor after sections are confirmed visited ────

    async def _advance_anchor(self, newly_visited: List[str], visited: List[str], remaining: List[str]) -> None:
        """Store a single progress update for all newly-visited sections and advance _progress_id.

        Accepts a list so we always make exactly ONE store call per turn, regardless
        of how many sections were completed — prevents slot stacking when a turn
        visits multiple sections at once.
        """
        hints = TARGET_NAV_HINTS.get(self.target, {})
        visited_str = ", ".join(visited)
        next_section = remaining[0] if remaining else None
        done_str = ", ".join(f"'{s}'" for s in newly_visited)

        if next_section:
            next_hint = hints.get(next_section, f"click the '{next_section}' nav link")
            progress_msg = (
                f"PROGRESS UPDATE:\n"
                f"  ✓ Sections completed this turn: [{done_str}]\n"
                f"  Visited so far: [{visited_str}]\n"
                f"  Remaining: [{', '.join(remaining)}]\n\n"
                f"Next: '{next_section}'\n"
                f"Command: {next_hint}\n"
                f"Reply: ACKNOWLEDGED"
            )
        else:
            progress_msg = (
                f"PROGRESS UPDATE:\n"
                f"  ✓ Sections completed this turn: [{done_str}]\n"
                f"  ALL SECTIONS COMPLETE: [{visited_str}]\n"
                f"  Call argus_done now.\n"
                f"Reply: ACKNOWLEDGED"
            )

        try:
            new_id = await self._store_message(progress_msg, previous_id=self._progress_id)
        except Exception as exc:
            logger.warning("_advance_anchor store failed (%s) — continuing without anchor update", exc)
            return
        logger.info("ARGUS anchor advanced → %s  (sections: %s)", new_id, done_str)
        self._progress_id = new_id
        # Mirror into local history backup
        self._history.append({"role": "user", "content": progress_msg})
        self._history.append({"role": "assistant", "content": "ACKNOWLEDGED"})

    # ──── Per-turn POST with SSE streaming ────

    async def _post_turn(
        self,
        turn: int,
        input_msg: str,
        branch_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST one tool-calling turn, branching from a specific anchor.

        Args:
            turn:        Turn index (for logging).
            input_msg:   Supervisor injection text.
            branch_from: Response ID to branch from.  Defaults to _progress_id.
                         Pass _primed_id on loop kills to reset to clean nav context.

        SSE stream is cancelled immediately (aclose) if any tool+args combination
        is repeated more than 3 times within the turn (loop kill).

        Returns dict with:
            loop_killed (bool) — True if stream was cancelled
            calls (List[str]) — tool names called this turn
            response_id (str) — stored response id for this turn (if available)
        """
        anchor = branch_from or self._progress_id

        def _build_payload(use_history_fallback: bool = False) -> Dict[str, Any]:
            payload: Dict[str, Any] = {
                "model": ARGUS_MODEL,
                "stream": True,
                "store": True,
                "temperature": 0.1,
                "context_length": 32768,
                "max_output_tokens": 512,
                "integrations": [self._mcp_integration()],
            }
            if use_history_fallback:
                # Replay full context from local mirror — no previous_response_id needed
                payload["input"] = self._history + [{"role": "user", "content": input_msg}]
            else:
                payload["input"] = input_msg
                if anchor:
                    payload["previous_response_id"] = anchor
            return payload

        use_fallback = False
        for attempt in range(3):
            try:
                tool_calls: List[str] = []
                loop_counts: Dict[str, int] = {}  # "toolname:args_prefix" → count
                event_type = ""
                result: Dict[str, Any] = {}
                loop_killed = False
                response_id: Optional[str] = None

                async with httpx.AsyncClient(timeout=600.0, headers=self._headers) as client:
                    async with client.stream(
                        "POST", self._base_url, json=_build_payload(use_fallback)
                    ) as resp:
                        if resp.status_code == 422:
                            # Server-side KV lost — switch to history fallback for this attempt
                            logger.warning(
                                "  [T%d] 422 Unprocessable — KV lost, falling back to history replay",
                                turn,
                            )
                            use_fallback = True
                            await asyncio.sleep(1)
                            continue
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                                continue
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            try:
                                ev = json.loads(raw)
                            except json.JSONDecodeError:
                                continue

                            if event_type == "tool_call.arguments":
                                name = ev.get("tool") or ev.get("name") or "?"
                                args_raw = str(ev.get("arguments", ""))
                                args_key = args_raw[:60]  # key prefix for dedup
                                tool_calls.append(name)
                                loop_key = f"{name}:{args_key}"
                                loop_counts[loop_key] = loop_counts.get(loop_key, 0) + 1
                                logger.info("  [T%d] → %s  %s", turn, name, args_raw[:80])

                                # Kill stream if same tool+args repeated >3 times
                                if loop_counts[loop_key] > 3:
                                    logger.warning(
                                        "  [T%d] LOOP DETECTED — %s called %d times — killing turn",
                                        turn, name, loop_counts[loop_key],
                                    )
                                    loop_killed = True
                                    await resp.aclose()
                                    break

                            elif event_type == "tool_call.success":
                                name = ev.get("tool") or ev.get("name") or "?"
                                out = str(ev.get("output", ""))[:120]
                                logger.debug("       ✓ %s → %s", name, out)

                            elif event_type == "tool_call.failure":
                                reason = ev.get("reason", "?")
                                logger.warning("       ✗ tool_call.failure: %s  %s", reason, ev)

                            elif event_type == "message.delta":
                                text = ev.get("content", "")
                                if text:
                                    logger.debug("  model: %s", str(text)[:120])

                            elif event_type == "chat.end":
                                result = ev.get("result", ev)
                                response_id = result.get("response_id") or result.get("id")

                if tool_calls:
                    logger.info("  [T%d] calls: %s", turn, " → ".join(tool_calls))

                # Mirror this turn into local history backup (store=True turns only)
                if not loop_killed and response_id:
                    model_reply = result.get("output", [{}])
                    reply_text = ""
                    if isinstance(model_reply, list):
                        for part in model_reply:
                            if isinstance(part, dict) and part.get("type") == "text":
                                reply_text = part.get("text", "")
                                break
                    elif isinstance(model_reply, str):
                        reply_text = model_reply
                    self._history.append({"role": "user", "content": input_msg})
                    self._history.append({"role": "assistant", "content": reply_text or "(tool calls)"})
                    self._save_history()

                result["loop_killed"] = loop_killed
                result["calls"] = tool_calls
                return result
            except httpx.ReadTimeout:
                logger.warning("ReadTimeout turn %d attempt %d/3 — retrying", turn, attempt + 1)
                await asyncio.sleep(5)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (500, 503):
                    logger.warning("HTTP %s turn %d attempt %d/3 — retrying",
                                   exc.response.status_code, turn, attempt + 1)
                    await asyncio.sleep(5)
                    continue
                raise

        raise RuntimeError(f"ARGUS: turn {turn} failed after 3 attempts")

    # ──── Per-turn supervisor message (SHORT — context lives in anchor) ────

    def _build_turn_input(
        self,
        turn: int,
        sections: List[str],
        current_url: str = "",
        loop_killed: bool = False,
        visited: Optional[List[str]] = None,
        remaining: Optional[List[str]] = None,
        vision_context: Optional[str] = None,
    ) -> str:
        """Build the supervisor injection for this turn.

        Turn messages are deliberately SHORT because the model already has full
        context loaded from the anchor chain (_progress_id or _primed_id).
        We only need to state the immediate task + current position.

        Args:
            vision_context: Optional vision-model description of the current screen.
                            Injected when ARGUS is stuck (no tool calls) or after a
                            loop kill to give the model ground truth about the UI state.
        """
        visited = visited or []
        remaining = list(sections) if remaining is None else remaining
        next_section = remaining[0] if remaining else None
        url_line = f"Current URL: {current_url}\n" if current_url else ""
        hints = TARGET_NAV_HINTS.get(self.target, {})

        if turn == 0:
            # First turn: state is the full nav map (already in _primed_id context)
            first_section = sections[0] if sections else "?"
            hint = hints.get(first_section, f"click the '{first_section}' nav link")
            msg = (
                f"BEGIN — {self.target}\n"
                f"{url_line}"
                f"Start with: argus_screenshot, then navigate to '{first_section}'.\n"
                f"Command: {hint}"
            )
            if vision_context:
                msg += f"\n\nVISION: {vision_context[:400]}"
            return msg

        if loop_killed:
            # Branch from _primed_id — model has clean nav map, we just say what to do
            if next_section:
                hint = hints.get(next_section, f"click the '{next_section}' nav link")
                msg = (
                    f"LOOP INTERRUPTED.\n"
                    f"{url_line}"
                    f"Execute NOW: {hint}\n"
                    f"Then: argus_get_network_log()\n"
                    f"DO NOT call argus_screenshot first."
                )
            else:
                msg = f"LOOP INTERRUPTED.\n{url_line}All sections done — call argus_done."
            if vision_context:
                msg += f"\n\nVISION (what Chrome shows now): {vision_context[:400]}"
            return msg

        if not remaining:
            msg = f"All sections visited.\n{url_line}Call argus_done with a brief summary."
            if vision_context:
                msg += f"\n\nVISION: {vision_context[:400]}"
            return msg

        # Normal turn: progress anchor already has "Section X done, next: Y" context
        hint = hints.get(next_section, f"click the '{next_section}' nav link") if next_section else ""
        msg = (
            f"Turn {turn + 1}/{self.max_turns}\n"
            f"{url_line}"
            f"Next: '{next_section}' — {hint}\n"
            f"After navigating: argus_get_network_log() then move on."
        )
        if vision_context:
            msg += f"\n\nVISION (screen state): {vision_context[:400]}"
        return msg

    # ──── Main run (async) ────

    async def run_async(self) -> Dict[str, Any]:
        """Start MCP server, connect browser, run agent loop, return results."""
        await start_argus_mcp()

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

            base_url = self._cfg.get("base_url", "")
            aliases = self._cfg.get("url_aliases", [base_url.split("//")[-1].split("/")[0]])

            page = next(
                (pg for pg in ctx.pages if any(a in pg.url for a in aliases)),
                None,
            )
            if page is None:
                page = await ctx.new_page()
                await page.goto(base_url, wait_until="domcontentloaded")

            await page.bring_to_front()
            monitor = NetworkMonitor()
            await monitor.attach_playwright_page(page)

            sections = TARGET_SECTIONS.get(self.target, [])
            url_hints = TARGET_SECTION_URLS.get(self.target, {})
            set_browser_context(page, monitor, loop=asyncio.get_event_loop(),
                                sections=sections, url_hints=url_hints)
            logger.info("ARGUS browser ready — %d sections, url=%s", len(sections), page.url)

            # Vision agent — gives the model ground truth about stuck/loop-kill states
            _vision = VisionAgent()

            # Build primed anchor (system prompt + nav map)
            await self._init_session(sections)

            loop_killed = False
            prev_visited: List[str] = []
            vision_context: Optional[str] = None

            for turn in range(self.max_turns):
                logger.info("ARGUS [%s] turn %d/%d", self.target, turn + 1, self.max_turns)

                # Read live state from browser_tools module
                from scripts.argus.browser_tools import _state as argus_state
                current_url = page.url
                visited = list(argus_state.sections_visited)
                remaining = list(argus_state.sections_remaining)

                # Detect newly completed sections since last turn — one advance call for all
                newly_visited = [s for s in visited if s not in prev_visited]
                if newly_visited:
                    logger.info("  ✓ Sections confirmed: %s — advancing anchor", newly_visited)
                    await self._advance_anchor(newly_visited, visited, remaining)
                prev_visited = visited

                input_msg = self._build_turn_input(
                    turn, sections,
                    current_url=current_url,
                    loop_killed=loop_killed,
                    visited=visited,
                    remaining=remaining,
                    vision_context=vision_context,  # inject vision diagnosis from prior turn
                )
                vision_context = None  # consumed — clear after injection

                # Loop kill → branch from _primed_id (reset context to clean nav map)
                # Normal turn → branch from _progress_id (accumulated progress context)
                branch = self._primed_id if loop_killed else self._progress_id

                result = await self._post_turn(turn, input_msg, branch_from=branch)
                loop_killed = result.get("loop_killed", False)

                # ── Vision diagnostics ──────────────────────────────────────────
                # When ARGUS gets stuck or loops, take a Playwright screenshot and ask
                # the vision model what Chrome is actually showing.  The description is
                # injected into the NEXT turn's supervisor message so the model has
                # ground truth about the UI state rather than guessing from context alone.
                if loop_killed:
                    try:
                        vision_context = await _vision.ask_page(
                            f"ARGUS loop detected on target '{self.target}'. "
                            "Describe exactly: current URL, page title, and any UI elements visible. "
                            "Are there error messages, loading spinners, login prompts, or modals?",
                            page,
                        )
                        logger.info("  [T%d] VISION (loop-kill): %s", turn, vision_context[:200])
                    except Exception as exc:
                        logger.debug("  [T%d] Vision failed (loop-kill): %s", turn, exc)
                        vision_context = None
                elif not result.get("calls"):
                    try:
                        next_s = remaining[0] if remaining else "unknown"
                        vision_context = await _vision.ask_page(
                            f"ARGUS made no tool calls (stuck before section '{next_s}'). "
                            "Describe what Chrome is currently showing. "
                            "Is there a CAPTCHA, login screen, error message, empty page, or loading state?",
                            page,
                        )
                        logger.info("  [T%d] VISION (no-calls): %s", turn, vision_context[:200])
                    except Exception as exc:
                        logger.debug("  [T%d] Vision failed (no-calls): %s", turn, exc)
                        vision_context = None
                # ────────────────────────────────────────────────────────────────

                # Drain network after every turn
                new_entries = await monitor.drain(google_only=True)
                if new_entries:
                    serialized = [vars(e) if hasattr(e, "__dict__") else e for e in new_entries]
                    self._all_network.extend(serialized)
                    logger.info("  +%d network entries (%d total)",
                                len(new_entries), len(self._all_network))

                if is_done():
                    logger.info("ARGUS [%s] done after turn %d", self.target, turn + 1)
                    break
            else:
                logger.warning("ARGUS [%s] hit max_turns=%d without argus_done",
                               self.target, self.max_turns)

        return {
            "target": self.target,
            "network_entries": self._all_network,
            "summary": get_summary(),
        }

    def run(self) -> Dict[str, Any]:
        """Sync entry point."""
        return asyncio.run(self.run_async())


def _process_and_store(target: str, network_entries: List[Dict], summary: str) -> None:
    """Decode captured network entries and store new discoveries in Nexus."""
    from scripts.argus.decoders.batchexecute import BatchExecuteDecoder
    from scripts.argus.decoders.grpc_web import GrpcWebDecoder
    from scripts.argus.nexus_sink import ArgusNexusSink
    from scripts.argus.config import NLM_RPCIDS, GEMINI_RPCIDS, AISTUDIO_METHODS

    sink = ArgusNexusSink()
    be_decoder = BatchExecuteDecoder()
    grpc_decoder = GrpcWebDecoder()

    known_nlm = set(NLM_RPCIDS.keys())
    known_gemini = set(GEMINI_RPCIDS.keys())
    known_ais = set(AISTUDIO_METHODS) if isinstance(AISTUDIO_METHODS, (list, set)) else set()

    new_nlm: List[str] = []
    new_gemini: List[str] = []
    new_ais: List[str] = []
    new_endpoints: List[str] = []

    for entry in network_entries:
        url = entry.get("url", "")
        method = entry.get("method", "")
        post_data = entry.get("post_data", "") or ""
        body = entry.get("response_body", "") or ""

        # batchexecute (NLM + Gemini)
        if "batchexecute" in url:
            for req in be_decoder.decode_request(post_data, url):
                rpcid = req.rpcid
                if "notebooklm" in url and rpcid not in known_nlm:
                    new_nlm.append(rpcid)
                    sink.store_new_rpcid(rpcid, "Unknown", "nlm", f"URL: {url[:80]}")
                elif "gemini" in url and rpcid not in known_gemini:
                    new_gemini.append(rpcid)
                    sink.store_new_rpcid(rpcid, "Unknown", "gemini", f"URL: {url[:80]}")

        # gRPC-web (AI Studio)
        if "$rpc/" in url or "clients6.google.com" in url:
            parts = url.split("/")
            if len(parts) >= 2:
                method_name = parts[-1]
                if method_name not in known_ais:
                    new_ais.append(method_name)
                    sink.store_new_aistudio_method(method_name, "/".join(parts[-3:-1]))

        # Unknown Google API endpoint
        if ("googleapis.com" in url or "google.com" in url) and \
           "batchexecute" not in url and "$rpc/" not in url and \
           "www.google.com" not in url and method == "POST":
            new_endpoints.append(url[:100])

    stats = {
        "nlm_rpcids_seen": len(known_nlm),
        "nlm_rpcids_total": len(known_nlm),
        "gemini_rpcids_seen": len(known_gemini),
        "gemini_rpcids_total": len(known_gemini),
        "aistudio_methods_seen": len(known_ais),
        "aistudio_methods_total": len(known_ais),
    }

    # Store scan summary (even if no new discoveries — records coverage)
    sink.store_scan_results(new_nlm, new_gemini, new_ais, new_endpoints, stats)

    total_new = len(new_nlm) + len(new_gemini) + len(new_ais) + len(new_endpoints)
    logger.info(
        "ARGUS [%s] stored: %d network entries → %d new discoveries (%d NLM, %d Gemini, %d AIS, %d other)",
        target, len(network_entries), total_new,
        len(new_nlm), len(new_gemini), len(new_ais), len(new_endpoints),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ARGUS autonomous crawl agent")
    parser.add_argument(
        "--target",
        choices=list(TARGETS.keys()) + ["all"],
        default="aistudio",
    )
    parser.add_argument("--turns", type=int, default=35)
    parser.add_argument("--no-store", action="store_true", help="Skip Nexus storage")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    targets = list(TARGETS.keys()) if args.target == "all" else [args.target]
    for target in targets:
        agent = ArgusAgent(target=target, max_turns=args.turns)
        result = agent.run()
        entries = result["network_entries"]
        print(f"\n[{target}] Network entries: {len(entries)}")
        if result["summary"]:
            summary = result["summary"][:300].encode("utf-8", errors="replace").decode("utf-8")
            print(f"[{target}] Summary: {summary}")
        if not args.no_store:
            _process_and_store(target, entries, result.get("summary", ""))


if __name__ == "__main__":
    main()
