"""ARGUS Console Eval — run arbitrary JS in any open Chrome tab via CDP.

Think of this as your terminal-based browser console. Attach to any tab
and evaluate any JavaScript expression, with pretty-printed output.

Usage:
    python -m scripts.argus.tools.console_eval "document.title"
    python -m scripts.argus.tools.console_eval "document.querySelectorAll('button').length"
    python -m scripts.argus.tools.console_eval --url github "document.querySelector('h1')?.innerText"
    python -m scripts.argus.tools.console_eval --interactive          # REPL mode
    python -m scripts.argus.tools.console_eval --file myscript.js     # run a .js file
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.argus.config import CDP_URL


async def get_page(url_pattern: str):
    from playwright.async_api import async_playwright
    pw_cm = async_playwright()
    pw = await pw_cm.__aenter__()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0]
    page = next((p for p in ctx.pages if url_pattern in p.url), None)
    if not page:
        print(f"[console] No tab matching '{url_pattern}'")
        print("[console] Open tabs:")
        for p in ctx.pages:
            if p.url.startswith("http"):
                print(f"  {p.url[:80]}")
        await pw_cm.__aexit__(None, None, None)
        return None, None
    return page, pw_cm


async def eval_js(page, js: str) -> Any:
    """Evaluate JS and return Python value."""
    try:
        result = await page.evaluate(js)
        return result
    except Exception as e:
        return {"error": str(e)}


def pretty(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


# ──── Built-in helper snippets ──────────────────────────────────────────────

HELPERS = {
    "buttons": "() => [...document.querySelectorAll('button,[role=button]')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0}).map(e=>({text:e.innerText?.trim().slice(0,50),aria:e.getAttribute('aria-label'),disabled:e.disabled}))",
    "inputs": "() => [...document.querySelectorAll('input,textarea')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0}).map(e=>({tag:e.tagName,type:e.type,placeholder:e.placeholder,disabled:e.disabled,value_len:(e.value||'').length}))",
    "dialogs": "() => [...document.querySelectorAll('[role=dialog],mat-dialog-container,.cdk-overlay-pane')].map(d=>d.innerText?.slice(0,300)).filter(Boolean)",
    "url": "() => location.href",
    "title": "() => document.title",
    "screenshot": None,  # special handling
}


async def interactive_repl(page, pw) -> None:
    """Simple REPL for live browser console."""
    print("[console] Interactive mode — type JS to evaluate, or a helper name.")
    print(f"[console] Helpers: {', '.join(HELPERS.keys())}")
    print("[console] Type 'exit' to quit.\n")

    while True:
        try:
            line = input("js> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line or line == "exit":
            break

        if line in HELPERS:
            js = HELPERS[line]
            if js is None:
                path = ROOT / "data" / "argus" / "screenshot.png"
                await page.screenshot(path=str(path))
                print(f"[console] Screenshot → {path}")
                continue
        else:
            js = line

        result = await eval_js(page, js)
        print(pretty(result))

    await pw.__aexit__(None, None, None)


async def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="ARGUS Console Eval")
    ap.add_argument("js",        nargs="?",       help="JavaScript to evaluate")
    ap.add_argument("--url",     default="notebooklm", help="Tab URL substring")
    ap.add_argument("--file",    default="",       help="Run a .js file")
    ap.add_argument("--interactive", "-i", action="store_true", help="REPL mode")
    args = ap.parse_args()

    page, pw = await get_page(args.url)
    if not page:
        return

    print(f"[console] Tab: {page.url[:80]}\n")

    if args.interactive:
        await interactive_repl(page, pw)
        return

    if args.file:
        js = Path(args.file).read_text(encoding="utf-8")
    elif args.js:
        js = args.js
    elif args.js in (None, ""):
        # Default: print page summary
        js = "() => ({title: document.title, url: location.href, buttons: document.querySelectorAll('button').length, inputs: document.querySelectorAll('input,textarea').length})"
    else:
        js = args.js

    result = await eval_js(page, js)
    print(pretty(result))
    await pw.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
