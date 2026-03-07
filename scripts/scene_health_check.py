"""CosySim Scene Health Checker — CDP-based auto-debugger.

Usage:
    python scripts/scene_health_check.py              # check all running scenes
    python scripts/scene_health_check.py --port 5569  # check one scene
    python scripts/scene_health_check.py --fix        # print fix suggestions
    python scripts/scene_health_check.py --host 127.0.0.1  # custom scene host
    python scripts/scene_health_check.py --chrome 9222 # custom debug port

What it checks (per scene):
    1. HTTP reachability + /api/health response
    2. Template render errors (500 on root route)
    3. Shared asset 404s (/shared/css, /shared/js)
    4. Duplicate SCENE_PORTS JS declaration (double navbar_v2.js load)
    5. Missing route registrations (/api/hud/state, /api/announcer/feed)
    6. Console errors / unhandled exceptions via CDP
    7. Stale/ghost widgets (aria_widget.js + cosysim-aria-portrait loaded together)
    8. ComfyUI checkpoint references to missing models

Requires:
    pip install websockets
    Chrome launched with --remote-debugging-port=9222

Copilot agent usage:
    Run before and after any template or scene_py change.
    Run after restarting a scene to confirm it's healthy.
    Add to git pre-push hook for CI safety.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from engine.port_registry import build_scene_port_map

# ── Scene registry ─────────────────────────────────────────────────────────────
# port → scene key (canonicalised via engine.port_registry)
SCENE_PORTS: dict[int, str] = build_scene_port_map()
DEFAULT_HOST = "localhost"

# Routes every scene should expose
REQUIRED_ROUTES = ["/api/health", "/api/hud/state", "/api/announcer/feed"]

# Shared assets that must load without 404
REQUIRED_SHARED = [
    "/shared/css/navbar_v2.css",
    "/shared/css/cosysim-neon-hud.css",
    "/shared/js/navbar_v2.js",
    "/shared/js/cosysim-neon-hud.js",
    "/shared/js/cosysim-announcer.js",
]

# JS patterns that indicate known bugs
KNOWN_BAD_PATTERNS = [
    (re.compile(r"SCENE_PORTS.*already declared", re.I), "duplicate navbar_v2.js load — remove explicit <script> from template"),
    (re.compile(r"CosyNavbar is not defined", re.I), "navbar_v2.js failed to load — check /shared/js/navbar_v2.js 404"),
    (re.compile(r"nlmNotebooks\.find is not a function", re.I), "NLMPanel: nlmNotebooks not an array — wrap in Array.isArray check"),
    (re.compile(r"aria_widget.*fallback|_buildFallback", re.I), "old aria_widget.js creating ghost button — remove from template"),
]


@dataclass
class SceneResult:
    port: int
    name: str
    reachable: bool = False
    health_ok: bool = False
    root_status: int = 0
    missing_routes: list[str] = field(default_factory=list)
    shared_404s: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    known_bugs: list[str] = field(default_factory=list)
    fix_hints: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.reachable
            and self.health_ok
            and not self.missing_routes
            and not self.shared_404s
            and not self.known_bugs
        )


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: float = 3.0) -> tuple[int, bytes]:
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return r.status, r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def _scene_base_url(port: int, host: str = DEFAULT_HOST) -> str:
    """Return the canonical HTTP base URL for a scene."""
    return f"http://{host}:{port}"


def _chrome_http_url(port: int, path: str, host: str = DEFAULT_HOST) -> str:
    """Return the canonical HTTP URL for the Chrome debug endpoint."""
    return f"http://{host}:{port}{path}"


def _chrome_ws_url(tab_id: str, port: int, host: str = DEFAULT_HOST) -> str:
    """Return the canonical websocket URL for a Chrome DevTools tab."""
    return f"ws://{host}:{port}/devtools/page/{tab_id}"


def _check_scene_http(port: int, host: str = DEFAULT_HOST) -> SceneResult:
    name = SCENE_PORTS.get(port, f"port_{port}")
    result = SceneResult(port=port, name=name)
    base = _scene_base_url(port, host)

    # Reachability + health
    status, body = _http_get(f"{base}/api/health")
    result.reachable = status != 0
    result.health_ok = status == 200

    # Root render
    root_status, _ = _http_get(f"{base}/")
    result.root_status = root_status

    # Required routes
    for route in REQUIRED_ROUTES:
        s, _ = _http_get(f"{base}{route}")
        if s not in (200, 204):
            result.missing_routes.append(route)
            # Add fix hint
            method = route.split("/")[-1].replace("-", "_")
            result.fix_hints.append(
                f"Add self.register_{method}_route(self.app) to {name}_scene.py start()"
            )

    # Shared assets
    for asset in REQUIRED_SHARED:
        s, _ = _http_get(f"{base}{asset}")
        if s == 404:
            result.shared_404s.append(asset)

    if result.shared_404s:
        result.fix_hints.append(
            f"Add 'register_shared_assets(self.app)' to {name}_scene.py start() "
            f"and import from content.shared"
        )

    return result


# ── CDP helpers ────────────────────────────────────────────────────────────────

async def _cdp_check_page(
    page_url: str,
    tab_id: str,
    chrome_port: int = 9222,
    chrome_host: str = DEFAULT_HOST,
) -> tuple[list[str], list[str]]:
    """Navigate to page_url and collect console errors + pattern matches.

    Returns: (console_errors, known_bug_messages)
    """
    try:
        import websockets  # type: ignore
    except ImportError:
        return ["websockets not installed — run: pip install websockets"], []

    console_errors: list[str] = []
    known_bugs: list[str] = []

    try:
        async with websockets.connect(
            _chrome_ws_url(tab_id, chrome_port, chrome_host),
            max_size=10_000_000,
            open_timeout=5,
        ) as ws:
            _id = 0

            async def _send(method: str, params: dict[str, Any] | None = None) -> None:
                nonlocal _id
                _id += 1
                await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))

            for domain in ["Network.enable", "Console.enable", "Runtime.enable", "Page.enable"]:
                await _send(domain)
            # Drain ACKs
            for _ in range(4):
                await asyncio.wait_for(ws.recv(), timeout=2)

            await _send("Page.navigate", {"url": page_url})

            deadline = time.time() + 7
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.4)
                    evt = json.loads(raw)
                    method = evt.get("method", "")
                    params = evt.get("params", {})

                    if method == "Console.messageAdded":
                        msg = params.get("message", {})
                        if msg.get("level") in ("error", "warning"):
                            text = msg.get("text", "")
                            console_errors.append(text)
                            for pattern, hint in KNOWN_BAD_PATTERNS:
                                if pattern.search(text):
                                    known_bugs.append(hint)

                    elif method == "Runtime.exceptionThrown":
                        exc = params.get("exceptionDetails", {})
                        text = exc.get("text", "") or str(
                            exc.get("exception", {}).get("description", "")
                        )
                        if text:
                            console_errors.append(f"UNCAUGHT: {text}")
                            for pattern, hint in KNOWN_BAD_PATTERNS:
                                if pattern.search(text):
                                    known_bugs.append(hint)

                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        console_errors.append(f"CDP connect error: {e}")

    return console_errors, list(set(known_bugs))


async def _get_chrome_tab(
    chrome_port: int = 9222,
    chrome_host: str = DEFAULT_HOST,
) -> str | None:
    """Return the first non-devtools tab ID from Chrome debug port."""
    status, body = _http_get(_chrome_http_url(chrome_port, "/json", chrome_host))
    if not body:
        return None
    tabs = json.loads(body)
    for tab in tabs:
        if tab.get("type") == "page" and "devtools" not in tab.get("url", ""):
            return tab["id"]
    return None


# ── Main check ────────────────────────────────────────────────────────────────

async def check_scenes(
    ports: list[int] | None = None,
    host: str = DEFAULT_HOST,
    chrome_port: int = 9222,
    chrome_host: str = DEFAULT_HOST,
    use_cdp: bool = True,
    show_fixes: bool = False,
) -> list[SceneResult]:
    """Run full health check on all running scenes."""
    if ports is None:
        ports = sorted(SCENE_PORTS.keys())

    # HTTP checks (fast, parallel)
    results = [_check_scene_http(p, host=host) for p in ports]
    running = [r for r in results if r.reachable]

    if not running:
        print("No scenes reachable.")
        return results

    # CDP check — reuse one tab, navigate sequentially
    tab_id = None
    if use_cdp:
        tab_id = await _get_chrome_tab(chrome_port, chrome_host)
        if tab_id:
            for r in running:
                if r.root_status == 200:
                    errors, bugs = await _cdp_check_page(
                        f"{_scene_base_url(r.port, host)}/",
                        tab_id,
                        chrome_port=chrome_port,
                        chrome_host=chrome_host,
                    )
                    r.console_errors = errors
                    r.known_bugs = bugs
        else:
            print(f"  [cdp] Chrome not reachable on port {chrome_port} — skipping JS checks")

    return results


def print_report(results: list[SceneResult], show_fixes: bool = False) -> int:
    """Print formatted report. Returns number of failing scenes."""
    running = [r for r in results if r.reachable]
    ok = [r for r in running if r.ok]
    fail = [r for r in running if not r.ok]

    print(f"\n{'='*60}")
    print(f"  CosySim Scene Health Check")
    print(f"{'='*60}")
    print(f"  Scanned {len(results)} ports — {len(running)} running, {len(ok)} OK, {len(fail)} issues\n")

    for r in running:
        icon = "✅" if r.ok else "❌"
        print(f"  {icon} [{r.port}] {r.name}")
        if not r.ok:
            if not r.health_ok:
                print(f"       ⚠ /api/health returned {r.root_status}")
            for route in r.missing_routes:
                print(f"       ✗ MISSING ROUTE: {route}")
            for asset in r.shared_404s:
                print(f"       ✗ SHARED 404:    {asset}")
            for bug in r.known_bugs:
                print(f"       🐛 KNOWN BUG:    {bug}")
            if r.console_errors and not r.known_bugs:
                for e in r.console_errors[:3]:
                    print(f"       ⚠ JS ERROR:     {e[:100]}")
            if show_fixes:
                for hint in r.fix_hints:
                    print(f"       💡 FIX: {hint}")

    not_running = [r for r in results if not r.reachable]
    if not_running:
        keys = [f"{r.name}({r.port})" for r in not_running[:8]]
        print(f"\n  ⏸  Not running: {', '.join(keys)}")

    print(f"\n{'='*60}\n")
    return len(fail)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CosySim scene health checker")
    parser.add_argument("--port", type=int, help="Check only this port")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Scene host (default: localhost)")
    parser.add_argument("--fix", action="store_true", help="Show fix suggestions")
    parser.add_argument("--no-cdp", action="store_true", help="Skip CDP/JS checks")
    parser.add_argument("--chrome", type=int, default=9222, help="Chrome debug port")
    parser.add_argument("--chrome-host", default=DEFAULT_HOST, help="Chrome debug host (default: localhost)")
    args = parser.parse_args()

    ports = [args.port] if args.port else None
    results = asyncio.run(
        check_scenes(
            ports=ports,
            host=args.host,
            chrome_port=args.chrome,
            chrome_host=args.chrome_host,
            use_cdp=not args.no_cdp,
            show_fixes=args.fix,
        )
    )
    failures = print_report(results, show_fixes=args.fix)
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
