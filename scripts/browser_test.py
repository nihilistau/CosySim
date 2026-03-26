"""
Browser Test Suite — Automated UI Verification
================================================

Launches headless Chromium via Playwright, navigates to NeonCity,
and tests every interactive HUD element. Reads telemetry logs after
each interaction. Outputs a structured diagnostic report.

Usage:
    python scripts/browser_test.py                    # Full NeonCity test
    python scripts/browser_test.py --scene penthouse  # Test specific scene
    python scripts/browser_test.py --all              # Quick smoke test all scenes
    python scripts/browser_test.py --report           # Just read last telemetry

Version: v1.53.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.53.0 [2026-03-26] — Added --all multi-scene smoke tests (14 scenes)
    v1.43.0 [2026-03-21] — Initial NeonCity deep test suite
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SCENE_URL = "http://localhost:5563"
REPORT_PATH = Path("data/browser_test_report.json")
JSONL_PATH = Path("data/structured_logs.jsonl")


def run_tests() -> dict:
    """Run full browser test suite, return results dict."""
    from playwright.sync_api import sync_playwright

    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scene_url": SCENE_URL,
        "tests": [],
        "errors": [],
        "summary": {"passed": 0, "failed": 0, "errors": 0},
    }

    def test(name: str, passed: bool, detail: str = ""):
        status = "PASS" if passed else "FAIL"
        results["tests"].append({"name": name, "status": status, "detail": detail})
        results["summary"]["passed" if passed else "failed"] += 1
        # v1.49.3 [2026-03-22] — Use ASCII-safe icons to avoid cp1252 crash on Windows
        icon = "[PASS]" if passed else "[FAIL]"
        try:
            print(f"  {icon} {name}: {detail}" if detail else f"  {icon} {name}")
        except UnicodeEncodeError:
            print(f"  {icon} {name}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Collect JS errors
        js_errors = []
        page.on("console", lambda msg: js_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: js_errors.append(str(err)))

        # ── Page Load ──────────────────────────────────────────────
        print("\n=== PAGE LOAD ===")
        try:
            page.goto(SCENE_URL, timeout=15000)
            page.wait_for_load_state("load", timeout=10000)
            page.wait_for_timeout(3000)
            test("Page loads", True, f"{len(page.content())} bytes")
        except Exception as e:
            test("Page loads", False, str(e))
            browser.close()
            return results

        # ── Telemetry ──────────────────────────────────────────────
        print("\n=== TELEMETRY ===")
        tel = page.evaluate("typeof window.CosyTelemetry")
        test("Telemetry JS loaded", tel == "object", tel)

        # ── HUD Strip ──────────────────────────────────────────────
        print("\n=== HUD STRIP ===")
        test("HUD element exists", page.query_selector("#cs-hud") is not None)
        test("Credits display", page.query_selector("#hud-credits") is not None)
        test("Location display", page.query_selector("#hud-location") is not None)
        test("Heat display", page.query_selector("#hud-heat") is not None)

        # ── Left Panel (I key) ─────────────────────────────────────
        print("\n=== LEFT PANEL (I) ===")
        page.keyboard.press("i")
        page.wait_for_timeout(600)
        left_vis = page.is_visible("#cs-hud-left-panel")
        test("I key opens left panel", left_vis)

        if left_vis:
            # Stats
            test("Health bar", page.query_selector("#left-health-bar") is not None)
            test("Energy bar", page.query_selector("#left-energy-bar") is not None)
            test("Credits display", page.query_selector("#left-credits") is not None)

            # Factions
            factions_el = page.query_selector("#left-factions")
            factions_text = factions_el.inner_text() if factions_el else ""
            test("Faction display rendered", len(factions_text) > 10, factions_text[:60])

            # Inventory
            slots = page.query_selector_all(".cs-hud-slide__inv-slot--occupied")
            test(f"Inventory slots occupied", len(slots) > 0, f"{len(slots)} slots")

            if slots:
                # Click an inventory item
                page.evaluate('document.querySelector(".cs-hud-slide__inv-slot--occupied").click()')
                page.wait_for_timeout(400)
                popup = page.query_selector(".cs-hud-popup")
                test("Inventory click → popup appears", popup is not None)

                if popup:
                    # Check popup has close/action buttons
                    buttons = popup.query_selector_all(".cs-hud-popup__btn")
                    test("Popup has action buttons", len(buttons) > 0, f"{len(buttons)} buttons")

                    # Check popup is inside viewport
                    box = popup.bounding_box()
                    if box:
                        in_viewport = box["x"] >= 0 and box["y"] >= 0 and box["x"] + box["width"] <= 1920 and box["y"] + box["height"] <= 1080
                        test("Popup within viewport", in_viewport, f"x={box['x']:.0f} y={box['y']:.0f}")

                    # Try to close popup with Escape
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                    popup_after = page.query_selector(".cs-hud-popup")
                    test("Escape closes popup", popup_after is None)

            # Skills
            skills_el = page.query_selector("#left-skills")
            test("Skills section", skills_el is not None)

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # ── Right Panel (C key) ────────────────────────────────────
        print("\n=== RIGHT PANEL (C) ===")
        page.keyboard.press("c")
        page.wait_for_timeout(600)
        right_vis = page.is_visible("#cs-hud-right-panel")
        test("C key opens right panel", right_vis)

        if right_vis:
            # Phone button
            phone_btn = page.query_selector("#hud-phone-launch")
            test("Phone launch button exists", phone_btn is not None)

            # Quick travel grid
            nav_grid = page.query_selector("#hud-nav-grid")
            test("Quick travel grid", nav_grid is not None)

            # Crew list
            crew_el = page.query_selector("#hud-crew-list")
            test("Crew list element", crew_el is not None)

            # Mission tracker
            mission_el = page.query_selector("#hud-mission-list")
            test("Mission tracker element", mission_el is not None)
            if mission_el:
                mission_text = mission_el.inner_text()
                test("Mission tracker content", len(mission_text) > 0, mission_text[:60])

            # Shop button
            shop_btn = page.query_selector("#hud-shop-open")
            test("Shop button exists", shop_btn is not None)
            if shop_btn:
                btn_html = shop_btn.get_attribute("onclick") or ""
                test("Shop button uses new handler", "NeonHUD" in btn_html, btn_html[:60])

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # ── Mission Board (M key) ──────────────────────────────────
        print("\n=== MISSION BOARD (M) ===")
        page.keyboard.press("m")
        page.wait_for_timeout(800)
        board_vis = page.is_visible("#cs-mission-board")
        test("M key opens mission board", board_vis)

        if board_vis:
            cards = page.query_selector_all(".cs-mission__card")
            test("Mission cards rendered", len(cards) > 0, f"{len(cards)} cards")

            # Check accept button exists (template uses cs-mission__card-accept)
            accept_btns = page.query_selector_all(".cs-mission__card-accept")
            if not accept_btns:
                accept_btns = page.query_selector_all("[class*=accept]")
            test("Accept buttons", len(accept_btns) > 0, f"{len(accept_btns)} buttons")

            # Tab switching
            active_tab = page.query_selector('.cs-mission__tab[data-tab="active"]')
            if active_tab:
                active_tab.click()
                page.wait_for_timeout(300)
                active_content = page.query_selector("#mission-tab-active")
                test("Active tab switches", active_content is not None and active_content.is_visible())

            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            test("Escape closes mission board", not page.is_visible("#cs-mission-board"))

        # ── Shop (B key) ──────────────────────────────────────────
        print("\n=== SHOP (B) ===")
        page.keyboard.press("b")
        page.wait_for_timeout(800)
        shop_vis = page.is_visible("#cs-shop-overlay")
        test("B key opens shop", shop_vis)

        if shop_vis:
            items = page.query_selector_all(".cs-shop__item")
            test("Shop items rendered", len(items) > 0, f"{len(items)} items")

            balance_el = page.query_selector("#shop-balance")
            if balance_el:
                balance = balance_el.inner_text()
                test("Balance displayed", len(balance) > 0, balance)

            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            test("Escape closes shop", not page.is_visible("#cs-shop-overlay"))

        # ── Phone Overlay (P key) ─────────────────────────────────
        print("\n=== PHONE (P) ===")
        page.keyboard.press("p")
        page.wait_for_timeout(1000)
        phone_overlay = page.query_selector("#cs-hud-phone-overlay") or page.query_selector("[id*=phone-overlay]")
        phone_vis = phone_overlay.is_visible() if phone_overlay else False
        test("P key opens phone overlay", phone_vis or page.is_visible("#cs-hud-phone-overlay"))

        # Phone launch button in right panel
        phone_launch = page.query_selector("#hud-phone-launch")
        test("Phone launch button available", phone_launch is not None)

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # ── Districts ──────────────────────────────────────────────
        print("\n=== DISTRICTS ===")
        district_cards = page.query_selector_all(".district-card")
        test("District cards exist", len(district_cards) > 0, f"{len(district_cards)} cards")

        if district_cards:
            # Click first district
            district_cards[0].click()
            page.wait_for_timeout(600)
            modal = page.query_selector(".district-modal") or page.query_selector("[class*=modal]")
            modal_vis = modal.is_visible() if modal else False
            test("District click opens modal", modal_vis)

            if modal_vis:
                enter_btn = page.query_selector("#btn-enter-district") or page.query_selector("[class*=enter-district]")
                test("Enter district button", enter_btn is not None)

            # Close modal
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        # ── Announcer ──────────────────────────────────────────────
        print("\n=== ANNOUNCER (A) ===")
        page.keyboard.press("a")
        page.wait_for_timeout(600)
        announcer = page.query_selector("#cs-announcer") or page.query_selector("[id*=announcer]")
        test("A key toggles announcer", announcer is not None)

        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ── v1.52.0 — Footer ─────────────────────────────────────
        print("\n=== FOOTER ===")
        footer = page.query_selector(".cs-footer")
        test("Footer exists", footer is not None)
        if footer:
            version_el = page.query_selector(".cs-footer-version")
            test("Footer version shown", version_el is not None and "CosySim" in (version_el.inner_text() or ""))
            keys_el = page.query_selector(".cs-footer-keys")
            test("Footer keyboard hints", keys_el is not None)
            links = page.query_selector_all(".cs-footer-link")
            test("Footer quick links (2+)", len(links) >= 2, f"{len(links)} links")

        # ── v1.52.0 — Navbar ─────────────────────────────────────
        print("\n=== NAVBAR ===")
        navbar = page.query_selector("#cs-navbar") or page.query_selector(".cs-navbar")
        test("Navbar exists", navbar is not None)
        if navbar:
            nav_items = page.query_selector_all("[class*=navbar] a") or page.query_selector_all(".cs-navbar__nav-item")
            test("Navbar scene links (8+)", len(nav_items) >= 8, f"{len(nav_items)} items")

        # ── v1.52.0 — Danmaku (F7) ───────────────────────────────
        print("\n=== DANMAKU (F7) ===")
        page.keyboard.press("F7")
        page.wait_for_timeout(600)
        overlay = page.query_selector("#cosy-danmaku-overlay") or page.query_selector("[class*=danmaku-overlay]")
        test("F7 creates danmaku overlay", overlay is not None)
        page.keyboard.press("F7")
        page.wait_for_timeout(300)

        # ── v1.52.0 — HUD Narrative + Spectator Widgets ──────────
        print("\n=== HUD WIDGETS ===")
        narrative_el = page.query_selector("#hud-narrative")
        test("Narrative widget in DOM", narrative_el is not None)
        spectator_el = page.query_selector("#hud-spectator")
        test("Spectator widget in DOM", spectator_el is not None)

        # ── JS Errors ──────────────────────────────────────────────
        print(f"\n=== JS ERRORS: {len(js_errors)} ===")
        # Filter out expected connection refused errors
        real_errors = [e for e in js_errors if "ERR_CONNECTION_REFUSED" not in e and "signal" not in e.lower()]
        for e in real_errors[:10]:
            safe = e.encode("ascii", "replace").decode()[:120]
            print(f"  [ERR] {safe}")
            results["errors"].append(safe)
        results["summary"]["errors"] = len(real_errors)

        if not real_errors:
            print("  None (excluding expected connection refused)")

        browser.close()

    # ── Summary ────────────────────────────────────────────────────
    s = results["summary"]
    total = s["passed"] + s["failed"]
    print(f"\n{'='*50}")
    print(f"RESULTS: {s['passed']}/{total} passed, {s['failed']} failed, {s['errors']} JS errors")
    print(f"{'='*50}\n")

    # Save report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Report saved to {REPORT_PATH}")

    return results


def read_telemetry(limit: int = 30) -> None:
    """Read recent browser telemetry from structured logs."""
    if not JSONL_PATH.exists():
        print("No structured logs found")
        return

    with JSONL_PATH.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    browser = []
    for l in lines:
        try:
            d = json.loads(l)
            if "browser" in d.get("svc", ""):
                browser.append(d)
        except Exception:
            pass

    print(f"\n=== Last {min(limit, len(browser))} browser telemetry events ===\n")
    for e in browser[-limit:]:
        lvl = e.get("level", "?")
        msg = e.get("msg", "?")
        ctx = e.get("ctx", {})
        ts = ctx.get("timestamp", "")[-12:]
        icon = "[ERR]" if lvl == "ERROR" else " . "
        print(f"  {icon} [{lvl:7s}] {ts} {msg[:90]}")


# v1.53.0 [2026-03-26] — Multi-scene smoke test for --all flag
# ──── Scene Registry ─────────────────────────────────────────────────
ALL_SCENES = {
    "neoncity":     ("http://localhost:5563", "NEON CITY"),
    "penthouse":    ("http://localhost:5556", "THE PENTHOUSE"),
    "phone":        ("http://localhost:5555", "SIGNAL"),
    "lounge":       ("http://localhost:5557", "THE VELVET PIT"),
    "tavern":       ("http://localhost:5558", "THE RUSTY ANCHOR"),
    "casino":       ("http://localhost:5559", "CLUB NOIR"),
    "gallery":      ("http://localhost:5560", "THE OBSCURA"),
    "arena":        ("http://localhost:5561", "THE COLOSSEUM"),
    "cyberspace":   ("http://localhost:5573", "CYBERSPACE"),
    "auction":      ("http://localhost:5574", "THE AUCTION HOUSE"),
    "neonos":       ("http://localhost:5593", "NEON OS"),
    "creation_kit": ("http://localhost:5592", "CREATION KIT"),
    "grid":         ("http://localhost:5569", "THE GRID"),
    "lab_break":    ("http://localhost:5571", "LAB BREAK"),
}


def run_smoke_all() -> dict:
    """Quick smoke test: page load + basic DOM check for every scene."""
    from playwright.sync_api import sync_playwright

    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "smoke-all",
        "scenes": [],
        "summary": {"up": 0, "down": 0, "errors": 0},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for key, (url, display_name) in ALL_SCENES.items():
            scene_result = {"key": key, "name": display_name, "url": url}
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                js_errors = []
                page.on("console", lambda msg: js_errors.append(msg.text) if msg.type == "error" else None)

                page.goto(url, timeout=8000)
                page.wait_for_load_state("load", timeout=6000)
                page.wait_for_timeout(1500)

                html_len = len(page.content())
                has_content = html_len > 2000
                scene_result["status"] = "UP" if has_content else "EMPTY"
                scene_result["html_bytes"] = html_len
                scene_result["js_errors"] = len(js_errors)

                # Check for shared footer (present on most scenes)
                footer = page.query_selector(".cs-footer")
                scene_result["has_footer"] = footer is not None

                results["summary"]["up"] += 1
                icon = "[UP]"
                print(f"  {icon}  {display_name:24s} {url:36s} {html_len:>7,}B  errors:{len(js_errors)}")
                page.close()

            except Exception as exc:
                scene_result["status"] = "DOWN"
                scene_result["error"] = str(exc)[:120]
                results["summary"]["down"] += 1
                print(f"  [DOWN] {display_name:24s} {url:36s} {str(exc)[:60]}")

            results["scenes"].append(scene_result)

        browser.close()

    # Save report
    report_path = Path("data/browser_smoke_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2))

    up = results["summary"]["up"]
    down = results["summary"]["down"]
    print(f"\n  === SMOKE: {up} UP / {down} DOWN / {up + down} total ===\n")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CosySim Browser Test Suite")
    parser.add_argument("--scene", default="http://localhost:5563", help="Scene URL")
    parser.add_argument("--report", action="store_true", help="Just read last telemetry")
    parser.add_argument("--all", action="store_true", help="Quick smoke test all scenes")
    args = parser.parse_args()

    if args.report:
        read_telemetry()
    elif args.all:
        run_smoke_all()
    else:
        SCENE_URL = args.scene
        results = run_tests()
        read_telemetry(15)
