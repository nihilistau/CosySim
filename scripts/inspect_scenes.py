"""
Live scene inspector using Playwright.
Visits each scene, captures screenshots, console errors, DOM state.
Usage: python scripts/inspect_scenes.py
"""
from __future__ import annotations
import json
import time
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext

OUT = Path("scripts/inspection_output")
OUT.mkdir(parents=True, exist_ok=True)

SCENES = {
    "phone":        "http://localhost:5555/",
    "bedroom":      "http://localhost:5556/",
    "asset_studio": "http://localhost:5568/",
    "hub":          "http://localhost:8500/",
    "system_ctrl":  "http://localhost:5575/",
    "canvas":       "http://localhost:5590/",
}

CHECKS = {
    "phone": [
        ("thread list visible",  "css=.thread-list, css=#thread-list, css=.contact-list"),
        ("message input",        "css=input[type=text], css=textarea[placeholder*=message i], css=#msg-input"),
        ("nav bar present",      "css=.cs-navbar, css=nav"),
    ],
    "bedroom": [
        ("content warning overlay",    "id=contentWarning"),
        ("header visible",             "css=.scene-header, css=header"),
        ("black overlay on top",       None),  # checked via JS
        ("side panel",                 "id=sidePanel"),
    ],
    "asset_studio": [
        ("tab buttons",          "css=.cs-tab-btn"),
        ("library tab active",   "css=#tab-library.active"),
        ("generate buttons",     "css=.cs-generate-btn"),
        ("navbar present",       "css=.cs-navbar"),
    ],
}


async def capture_scene(page: Page, name: str, url: str) -> dict:
    result = {"name": name, "url": url, "errors": [], "warnings": [], "checks": {}, "network_errors": []}
    
    # Capture console
    page.on("console", lambda m: result["errors"].append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: result["errors"].append(f"[pageerror] {e}"))
    page.on("requestfailed", lambda r: result["network_errors"].append(f"FAILED: {r.url} — {r.failure}"))

    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        result["status"] = resp.status if resp else "no response"
    except Exception as e:
        result["status"] = f"ERROR: {e}"
        result["screenshot"] = None
        return result

    await page.wait_for_timeout(2000)

    # Screenshot
    ss_path = OUT / f"{name}.png"
    await page.screenshot(path=str(ss_path), full_page=False)
    result["screenshot"] = str(ss_path)

    # Run DOM checks
    for check_name, selector in (CHECKS.get(name) or []):
        if selector is None:
            # Special JS check for bedroom black overlay
            if "black overlay" in check_name:
                overlay_info = await page.evaluate("""
                    () => {
                        const w = document.getElementById('contentWarning');
                        if (!w) return {exists: false};
                        const style = window.getComputedStyle(w);
                        const rect = w.getBoundingClientRect();
                        return {
                            exists: true,
                            display: style.display,
                            visibility: style.visibility,
                            opacity: style.opacity,
                            zIndex: style.zIndex,
                            width: rect.width,
                            height: rect.height,
                            pointerEvents: style.pointerEvents
                        };
                    }
                """)
                result["checks"][check_name] = overlay_info
            continue
        try:
            el = await page.query_selector(selector)
            if el:
                visible = await el.is_visible()
                box = await el.bounding_box()
                result["checks"][check_name] = {"found": True, "visible": visible, "box": box}
            else:
                result["checks"][check_name] = {"found": False}
        except Exception as e:
            result["checks"][check_name] = {"error": str(e)}

    # Scene-specific deep inspections
    if name == "bedroom":
        result["bedroom_deep"] = await page.evaluate("""
            () => {
                const warn = document.getElementById('contentWarning');
                const header = document.querySelector('.scene-header, header');
                const headerStyle = header ? window.getComputedStyle(header) : null;
                
                // Find any element covering the full viewport at high z-index
                const blocking = [];
                document.querySelectorAll('*').forEach(el => {
                    const s = window.getComputedStyle(el);
                    const z = parseInt(s.zIndex) || 0;
                    const pos = s.position;
                    if (z > 100 && (pos === 'fixed' || pos === 'absolute')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 200 && r.height > 200) {
                            blocking.push({
                                id: el.id, class: el.className.substring(0,60),
                                z, pos, display: s.display, 
                                opacity: s.opacity, visibility: s.visibility,
                                w: Math.round(r.width), h: Math.round(r.height)
                            });
                        }
                    }
                });
                return {
                    contentWarning: warn ? {
                        display: window.getComputedStyle(warn).display,
                        zIndex: window.getComputedStyle(warn).zIndex,
                        visible: warn.offsetParent !== null
                    } : null,
                    headerTag: header ? header.tagName : null,
                    headerZ: headerStyle ? headerStyle.zIndex : null,
                    headerClick: header ? header.getAttribute('onclick') : null,
                    blockingElements: blocking,
                    sessionWarned: sessionStorage.getItem('bedroom_warned')
                };
            }
        """)

    if name == "asset_studio":
        result["asset_studio_deep"] = await page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.cs-tab-btn');
                const tabInfo = Array.from(tabs).map(t => ({
                    tab: t.dataset.tab,
                    active: t.classList.contains('active'),
                    visible: t.offsetParent !== null,
                    disabled: t.disabled,
                    pointerEvents: window.getComputedStyle(t).pointerEvents
                }));
                
                // Check if anything is covering the sidebar
                const sidebar = document.getElementById('studio-sidebar');
                const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;
                
                // Find what element is at the center of the first tab button
                let hitTest = null;
                if (tabs[1]) {
                    const r = tabs[1].getBoundingClientRect();
                    const cx = r.left + r.width/2;
                    const cy = r.top + r.height/2;
                    const topEl = document.elementFromPoint(cx, cy);
                    hitTest = topEl ? {tag: topEl.tagName, id: topEl.id, class: topEl.className.substring(0,60)} : null;
                }
                
                return {
                    tabCount: tabs.length,
                    tabInfo,
                    sidebarRect: sidebarRect ? {x: Math.round(sidebarRect.x), y: Math.round(sidebarRect.y), w: Math.round(sidebarRect.width), h: Math.round(sidebarRect.height)} : null,
                    navbarPresent: !!document.querySelector('.cs-navbar'),
                    hudPresent: !!document.getElementById('cs-hud'),
                    hudOverTop: (() => {
                        const hud = document.getElementById('cs-hud');
                        if (!hud) return false;
                        const r = hud.getBoundingClientRect();
                        const s = window.getComputedStyle(hud);
                        return {z: s.zIndex, h: r.height, pointerEvents: s.pointerEvents, top: r.top};
                    })(),
                    hitTestOnTab: hitTest,
                    scriptErrors: window.__cs_errors || []
                };
            }
        """)

    if name == "phone":
        result["phone_deep"] = await page.evaluate("""
            () => {
                return {
                    threadListEl: !!document.querySelector('.thread-list, #thread-list, [data-role=thread-list]'),
                    contactListEl: !!document.querySelector('.contact-list, .contacts'),
                    msgContainerEl: !!document.querySelector('#chat-messages, .messages, .message-list'),
                    hasSocket: typeof io !== 'undefined',
                    allContainers: Array.from(document.querySelectorAll('[class*=thread],[class*=contact],[class*=message],[class*=chat]'))
                        .map(el => ({tag: el.tagName, id: el.id, class: el.className.substring(0,60), children: el.children.length}))
                };
            }
        """)

    return result


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Show browser so user can see
            args=["--remote-debugging-port=9223", "--window-size=1400,900"]
        )
        context: BrowserContext = await browser.new_context(viewport={"width": 1400, "height": 900})

        all_results = {}
        for name, url in SCENES.items():
            print(f"\n{'='*60}")
            print(f"  Inspecting: {name} → {url}")
            print(f"{'='*60}")
            page = await context.new_page()
            result = await capture_scene(page, name, url)
            all_results[name] = result
            print(f"  Status: {result.get('status')}")
            print(f"  Screenshot: {result.get('screenshot')}")
            if result["errors"]:
                print(f"  Console errors ({len(result['errors'])}):")
                for e in result["errors"][:10]:
                    print(f"    {e}")
            if result["network_errors"]:
                print(f"  Network failures ({len(result['network_errors'])}):")
                for e in result["network_errors"][:10]:
                    print(f"    {e}")
            if "bedroom_deep" in result:
                print(f"  Bedroom deep: {json.dumps(result['bedroom_deep'], indent=2)}")
            if "asset_studio_deep" in result:
                d = result["asset_studio_deep"]
                print(f"  Asset Studio: {d.get('tabCount')} tabs, hitTest={d.get('hitTestOnTab')}")
                print(f"    hudOverTop={d.get('hudOverTop')}")
                for t in (d.get("tabInfo") or [])[:3]:
                    print(f"    tab {t['tab']}: visible={t['visible']} pointerEvents={t['pointerEvents']}")
            if "phone_deep" in result:
                print(f"  Phone deep: {json.dumps(result['phone_deep'], indent=2)}")
            await page.close()

        # Save full report
        report_path = OUT / "inspection_report.json"
        with open(report_path, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n\nFull report saved: {report_path}")

        print("\nBrowser left open on port 9223 for 30s — you can inspect too")
        await asyncio.sleep(30)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
