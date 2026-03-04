"""ARGUS Console — unified CLI for live Chrome inspection and automation.

A Swiss-Army tool that gives you full console, DOM, selector, and token access
to any running Chrome tab via CDP.  No browser UI needed.

Sub-commands:
    scan      — Scan a tab for interactive elements and generate selectors
    eval      — Evaluate JavaScript in a tab
    tokens    — Harvest Google cookies and refresh the account pool
    tabs      — List all open Chrome tabs
    snap      — Take a screenshot of a tab
    watch     — Continuously scan a tab (live DOM monitor)
    repl      — Interactive JavaScript REPL

Examples:
    python -m scripts.argus.tools                              # show this help
    python -m scripts.argus.tools tabs                        # list tabs
    python -m scripts.argus.tools scan                        # scan NLM
    python -m scripts.argus.tools scan --url github           # scan any tab
    python -m scripts.argus.tools scan --filter insert        # filter elements
    python -m scripts.argus.tools eval "document.title"       # quick JS eval
    python -m scripts.argus.tools eval --helper buttons       # built-in helpers
    python -m scripts.argus.tools tokens                      # harvest + save
    python -m scripts.argus.tools tokens --show               # print only
    python -m scripts.argus.tools snap                        # screenshot NLM
    python -m scripts.argus.tools watch                       # live DOM monitor
    python -m scripts.argus.tools repl                        # JS REPL
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Force UTF-8 output so box-drawing chars work on Windows — only when running as CLI
def _fix_windows_encoding() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except AttributeError:
            pass  # pytest capsys has no .buffer

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.argus.config import CDP_URL, DATA_DIR

# ──── helpers ─────────────────────────────────────────────────────────────────

JS_HELPERS: Dict[str, str] = {
    "buttons": """() => [...document.querySelectorAll('button,[role=button]')]
        .filter(e => {const r=e.getBoundingClientRect(); return r.width>0})
        .map(e => ({text:e.innerText?.trim().replace(/\\s+/g,' ').slice(0,50), aria:e.getAttribute('aria-label'), disabled:e.disabled}))""",

    "inputs": """() => [...document.querySelectorAll('input,textarea')]
        .filter(e => {const r=e.getBoundingClientRect(); return r.width>0})
        .map(e => ({tag:e.tagName, type:e.type, placeholder:e.placeholder, disabled:e.disabled, value_len:(e.value||'').length, class:e.className.slice(0,60)}))""",

    "dialogs": """() => [...document.querySelectorAll('[role=dialog],mat-dialog-container,.cdk-overlay-pane')]
        .map(d => d.innerText?.slice(0,400)).filter(Boolean)""",

    "cookies": """() => document.cookie.split(';').map(c => c.trim()).filter(Boolean)""",

    "links": """() => [...document.querySelectorAll('a[href]')]
        .map(a => ({text:a.innerText?.trim().slice(0,40), href:a.href.slice(0,80)}))
        .filter(a => a.href.startsWith('http'))""",

    "forms": """() => [...document.querySelectorAll('form')]
        .map(f => ({id:f.id, action:f.action, inputs:[...f.querySelectorAll('input,textarea,select')].length}))""",

    "angular": """() => {
        try {
            const el = document.querySelector('[ng-version]');
            return el ? el.getAttribute('ng-version') : 'not Angular';
        } catch(e) { return 'error'; }
    }""",

    "network": """() => {
        // Check for any XHR/fetch in-flight
        return typeof window.__argus_requests !== 'undefined' ? window.__argus_requests : 'not injected';
    }""",

    "storage": """() => ({
        localStorage_keys: Object.keys(localStorage).slice(0,20),
        sessionStorage_keys: Object.keys(sessionStorage).slice(0,20)
    })""",

    "meta": """() => ({
        title: document.title,
        url: location.href,
        description: document.querySelector('meta[name=description]')?.content,
        viewport: document.querySelector('meta[name=viewport]')?.content
    })""",
}




async def find_page(ctx, url_pattern: str):
    """Find first page matching url_pattern."""
    return next((p for p in ctx.pages if url_pattern in p.url), None)


# ──── sub-commands ────────────────────────────────────────────────────────────

async def cmd_tabs(ctx) -> None:
    """List all open Chrome tabs."""
    print(f"\n{'─'*70}")
    print(f"{'#':<4} {'TYPE':<10} TITLE / URL")
    print(f"{'─'*70}")
    pages = [p for p in ctx.pages if p.url.startswith("http")]
    for i, p in enumerate(pages):
        title = (p.url.split("//")[1].split("/")[0])[:20]
        print(f"{i:<4} {'page':<10} {title:<22} {p.url[:50]}")
    print(f"{'─'*70}")
    print(f"{len(pages)} tabs")


async def cmd_scan(ctx, url: str, filter_kw: str, save: bool) -> None:
    """Scan tab for interactive elements."""
    from scripts.argus.tools.selector_scanner import scan_page, print_report, save_selectors
    elements = await scan_page(url)
    if elements:
        print_report(elements, filter_kw)
        if save:
            save_selectors(elements, name=url.split(".")[0])


async def cmd_eval(ctx, url: str, js: Optional[str], helper: Optional[str], interactive: bool) -> None:
    """Evaluate JS in a tab."""
    page = await find_page(ctx, url)
    if not page:
        print(f"[argus] No tab matching '{url}'")
        return

    print(f"[argus] Tab: {page.url[:70]}")

    if interactive:
        await _repl(page)
        return

    code = JS_HELPERS.get(helper or "", "") or js or "() => ({title:document.title, url:location.href})"
    result = await page.evaluate(code)
    _pp(result)


async def cmd_tokens(url: str, show: bool, account: str) -> None:
    """Harvest Google cookies and update account pool."""
    from scripts.argus.tools.token_harvester import harvest_cookies, update_account_pool, print_cookies
    cookies, detected_name = await harvest_cookies(url)
    name = account or detected_name
    print_cookies(cookies, name)
    if not show and cookies:
        update_account_pool(cookies, name)


async def cmd_snap(ctx, url: str, out: Optional[str]) -> None:
    """Screenshot a tab."""
    page = await find_page(ctx, url)
    if not page:
        print(f"[argus] No tab matching '{url}'")
        return
    path = out or str(DATA_DIR / f"screenshot_{int(time.time())}.png")
    await page.screenshot(path=path, full_page=False)
    print(f"[argus] Screenshot → {path}")


async def cmd_watch(ctx, url: str, filter_kw: str, interval: float) -> None:
    """Continuously re-scan a tab."""
    from scripts.argus.tools.selector_scanner import scan_page, print_report
    print(f"[argus] Watching '{url}' every {interval}s — Ctrl+C to stop\n")
    try:
        while True:
            import os; os.system("cls" if sys.platform == "win32" else "clear")
            elements = await scan_page(url)
            if elements:
                print_report(elements, filter_kw)
            print(f"\n[{time.strftime('%H:%M:%S')}] Next scan in {interval}s…")
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\n[argus] Stopped.")


async def _repl(page) -> None:
    """Interactive JS REPL against a live tab."""
    print(f"\n[argus] REPL on: {page.url[:70]}")
    print(f"[argus] Helpers: {', '.join(JS_HELPERS.keys())}")
    print("[argus] Type 'snap' to screenshot, 'exit' to quit\n")

    while True:
        try:
            line = input("js> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue
        if line == "exit":
            break
        if line == "snap":
            path = str(DATA_DIR / f"repl_snap_{int(time.time())}.png")
            await page.screenshot(path=path)
            print(f"→ {path}")
            continue

        code = JS_HELPERS.get(line, line)
        try:
            result = await page.evaluate(code)
            _pp(result)
        except Exception as e:
            print(f"Error: {e}")


def _pp(value: Any) -> None:
    if value is None:
        print("null")
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        print(value)


# ──── main ────────────────────────────────────────────────────────────────────

async def main(argv: List[str]) -> None:
    import argparse
    from playwright.async_api import async_playwright

    ap = argparse.ArgumentParser(
        description="ARGUS Console — live Chrome DOM/JS/token toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd")

    # tabs
    sub.add_parser("tabs", help="List open Chrome tabs")

    # scan
    ps = sub.add_parser("scan", help="Scan DOM for interactive elements + selectors")
    ps.add_argument("--url",    default="notebooklm")
    ps.add_argument("--filter", default="")
    ps.add_argument("--save",   action="store_true")

    # eval
    pe = sub.add_parser("eval", help="Evaluate JavaScript in a tab")
    pe.add_argument("js",          nargs="?",  default=None)
    pe.add_argument("--url",       default="notebooklm")
    pe.add_argument("--helper",    default=None, choices=list(JS_HELPERS.keys()),
                    help="Run a built-in helper snippet")
    pe.add_argument("-i", "--interactive", action="store_true", help="REPL mode")

    # tokens
    pt = sub.add_parser("tokens", help="Harvest Google cookies + refresh account pool")
    pt.add_argument("--show",    action="store_true")
    pt.add_argument("--account", default="")
    pt.add_argument("--url",     default="notebooklm")

    # snap
    pn = sub.add_parser("snap", help="Screenshot a tab")
    pn.add_argument("--url", default="notebooklm")
    pn.add_argument("--out", default=None)

    # watch
    pw_arg = sub.add_parser("watch", help="Live DOM monitor (re-scan loop)")
    pw_arg.add_argument("--url",      default="notebooklm")
    pw_arg.add_argument("--filter",   default="")
    pw_arg.add_argument("--interval", type=float, default=3.0)

    # repl
    pr = sub.add_parser("repl", help="Interactive JavaScript REPL")
    pr.add_argument("--url", default="notebooklm")

    args = ap.parse_args(argv)

    if args.cmd in (None, "help"):
        ap.print_help()
        return

    # tokens doesn't need the playwright context wrapper (harvester opens its own)
    if args.cmd == "tokens":
        await cmd_tokens(args.url, args.show, args.account)
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        if args.cmd == "tabs":
            await cmd_tabs(ctx)

        elif args.cmd == "scan":
            await cmd_scan(ctx, args.url, args.filter, args.save)

        elif args.cmd == "eval":
            await cmd_eval(ctx, args.url, args.js, args.helper, args.interactive)

        elif args.cmd == "snap":
            await cmd_snap(ctx, args.url, args.out)

        elif args.cmd == "watch":
            await cmd_watch(ctx, args.url, args.filter, args.interval)

        elif args.cmd == "repl":
            page = await find_page(ctx, args.url)
            if page:
                await _repl(page)


if __name__ == "__main__":
    _fix_windows_encoding()
    asyncio.run(main(sys.argv[1:]))
