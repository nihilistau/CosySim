"""ARGUS Selector Scanner — live DOM introspection via CDP.

Connects to running Chrome, scans a page for interactive elements, and
generates robust CSS selectors using priority: aria-label > id > data-* >
text-content > class chain.  Outputs a JSON map you can paste into automation scripts.

Usage:
    python -m scripts.argus.tools.selector_scanner                   # scan NLM
    python -m scripts.argus.tools.selector_scanner --url <pattern>   # scan any tab
    python -m scripts.argus.tools.selector_scanner --watch           # re-scan every 3s
    python -m scripts.argus.tools.selector_scanner --filter "insert" # filter by keyword
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# ──── sys.path so `scripts.argus` resolves ────────────────────────────────────
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.argus.config import CDP_URL, DATA_DIR

# Force UTF-8 on Windows so box-drawing chars print correctly
if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# JS that scans all visible interactive elements and returns rich info
_SCAN_JS = """
() => {
    const TAGS = 'button, input, textarea, select, [role=button], [role=tab], [role=menuitem]';
    const els = [...document.querySelectorAll(TAGS)].filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    });

    return els.map(el => {
        const text = (el.innerText || el.value || el.placeholder || '')
                       .trim().replace(/\\s+/g, ' ').slice(0, 60);
        const aria        = el.getAttribute('aria-label') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const disabled    = el.disabled || el.getAttribute('aria-disabled') === 'true';
        const tag         = el.tagName.toLowerCase();

        // Build the best selector
        let selector = '';
        if (aria) {
            selector = `[aria-label="${aria.replace(/"/g, '\\"')}"]`;
        } else if (el.id) {
            selector = '#' + CSS.escape(el.id);
        } else if (text && text.length > 1 && text.length < 50 && tag === 'button') {
            selector = `button:has-text("${text.replace(/"/g, '\\"')}")`;
        } else {
            const meaningful = [...el.classList].filter(c =>
                !c.startsWith('ng-') && !c.startsWith('mat-') && !c.startsWith('mdc-') &&
                !c.startsWith('_mat') && !c.startsWith('cdk-') && c.length > 3
            ).slice(0, 2);
            if (meaningful.length) selector = tag + '.' + meaningful.join('.');
            else selector = tag;
        }

        // Uniqueness check
        let unique = false;
        try { unique = document.querySelectorAll(selector).length === 1; } catch(e) {}

        return {tag, text, aria, placeholder, disabled, selector, unique,
                classes: [...el.classList].join(' ').slice(0, 80)};
    });
}
"""


async def scan_page(url_pattern: str = "notebooklm") -> List[Dict[str, Any]]:
    """Attach to running Chrome and scan the tab matching url_pattern."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page = next((p for p in ctx.pages if url_pattern in p.url), None)

        if not page:
            print(f"[scanner] No tab matching '{url_pattern}'")
            print("[scanner] Open tabs:")
            for p in ctx.pages:
                if p.url.startswith("http"):
                    print(f"  {p.url[:80]}")
            return []

        print(f"[scanner] {page.url[:80]}")
        return await page.evaluate(_SCAN_JS)


def print_report(elements: List[Dict[str, Any]], filter_kw: str = "") -> None:
    kw = filter_kw.lower()
    rows = [
        e for e in elements
        if not kw or kw in (e["text"] + e["aria"] + e["selector"] + e["classes"]).lower()
    ]

    print(f"\n{'─'*78}")
    print(f"{'TAG':<8} {'U':<2} {'D':<2} {'SELECTOR':<44} LABEL / TEXT")
    print(f"{'─'*78}")
    for e in rows:
        label = e["aria"] or e["text"] or e["placeholder"] or "(unlabelled)"
        u = "✓" if e["unique"] else " "
        d = "✗" if e["disabled"] else " "
        sel = e["selector"][:43]
        print(f"{e['tag']:<8} {u:<2} {d:<2} {sel:<44} {label[:38]}")
    print(f"{'─'*78}")
    print(f"{len(rows)} elements  (U=unique selector  D=disabled)")


def save_selectors(elements: List[Dict[str, Any]], name: str = "nlm") -> Path:
    """Save selector map JSON — useful for pasting into scripts."""
    out_dir = DATA_DIR / "selectors"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    path = out_dir / f"{name}_{ts}.json"

    seen: dict[str, dict] = {}
    for e in elements:
        sel = e.get("selector", "")
        if not sel:
            continue
        key = (e["aria"] or e["text"] or sel)[:50].strip().lower().replace(" ", "_")
        if key not in seen:
            seen[key] = {k: e[k] for k in ("selector", "text", "aria", "tag", "disabled", "unique")}

    path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    print(f"[scanner] Saved → {path} ({len(seen)} selectors)")
    return path


async def run(url: str, filter_kw: str, save: bool, watch: bool) -> None:
    while True:
        elements = await scan_page(url)
        if elements:
            print_report(elements, filter_kw)
            if save:
                save_selectors(elements, name=url.split(".")[0])
        if not watch:
            break
        print("\n[scanner] Watching — Ctrl+C to stop")
        await asyncio.sleep(3)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ARGUS Selector Scanner")
    ap.add_argument("--url",    default="notebooklm", help="Tab URL substring to match")
    ap.add_argument("--filter", default="",           help="Filter output by keyword")
    ap.add_argument("--save",   action="store_true",  help="Write selector JSON to disk")
    ap.add_argument("--watch",  action="store_true",  help="Re-scan every 3 s")
    args = ap.parse_args()
    asyncio.run(run(args.url, args.filter, args.save, args.watch))
