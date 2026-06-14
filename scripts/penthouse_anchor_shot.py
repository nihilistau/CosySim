"""
Penthouse Anchor-Placement Screenshot Harness
=============================================

Drives the live penthouse 3D scene (:5556) via Playwright, spawns a character
at a given location, lets the pose blend in, reports the rendered feet-origin
group.position.y, and captures a PNG. Supports a `--legacy` mode that reproduces
the pre-v1.62.0 behavior (model._baseY forced to 0) so BEFORE/AFTER can be
captured from the same build.

Usage:
    .venv/Scripts/python.exe scripts/penthouse_anchor_shot.py --loc bed --out docs/superpowers/artifacts/t1-bed-after.png
    .venv/Scripts/python.exe scripts/penthouse_anchor_shot.py --loc bed --legacy --out .../t1-bed-before.png

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — anchor-aware placement verification harness
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

URL = "http://localhost:5556"

# Camera view per location for a clear shot (falls back to default if missing).
VIEW_FOR = {
    "bed": "bed",
    "couch": "couch",
    "bar": "bar",
    "vanity": "vanity",
    "bath": "bath",
}


def capture(loc: str, out: Path, legacy: bool) -> dict:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    info: dict = {"loc": loc, "legacy": legacy, "out": str(out)}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # Pre-admit through the 18+ gate (it checks sessionStorage on load).
        page.add_init_script(
            "try { sessionStorage.setItem('penthouse_admitted','1'); } catch(e){}"
        )

        page.goto(URL, timeout=20000, wait_until="domcontentloaded")

        # Belt-and-braces: force-hide the gate if it is still present.
        page.evaluate(
            "() => { const g = document.getElementById('penthouse-gate'); "
            "if (g) { g.hidden = true; g.style.display = 'none'; } }"
        )

        # Wait for the 3D scene to finish initializing.
        page.wait_for_function(
            "() => window.penthouse3D && window.penthouse3D.isInitialized && "
            "window.penthouse3D.isInitialized() && window.CharacterBridge",
            timeout=25000,
        )

        # Spawn a single character at the requested location, then freeze
        # syncCharacters so the scene's own Socket.IO state loop cannot remove
        # our probe (real scene state has no 'probe' → it would be culled).
        page.evaluate(
            """(loc) => {
                window.CharacterBridge.syncCharacters(
                  { probe: { name: 'Probe', location_id: loc, outfit: 'casual', feeling: 'relaxed' } },
                  {}
                );
                window.CharacterBridge.syncCharacters = function () {};
            }""",
            loc,
        )

        # Wait until the AnimManager has registered the character (spawn can lag).
        page.wait_for_function(
            "() => window.PenthouseAnim.AnimManager.getState('Probe') !== null",
            timeout=8000,
        )

        # Legacy reproduction: undo the anchor base-Y seeding so the pose offset
        # sinks the body (the pre-fix bug) — same as the old register()-captured 0.
        if legacy:
            page.wait_for_timeout(200)
            page.evaluate(
                """() => {
                    const s = window.penthouse3D.getScene();
                    // Reach the model via PenthouseAnim states (keyed by name).
                    const st = window.PenthouseAnim.AnimManager.getState('Probe');
                    if (st && st.model) { st.model._baseY = 0; }
                }"""
            )

        # Let the pose blend fully in.
        page.wait_for_timeout(2200)

        # NOTE: headless Chromium throttles requestAnimationFrame, so the scene's
        # camera-view lerp (switchView) never completes and a bare
        # renderer.render() skips the post-FX pipeline (dark frame). We therefore
        # capture the scene's default lit overview. The load-bearing proof is the
        # numeric read below (model._baseY + rendered group.position.y), which is
        # exact regardless of camera framing.

        # Read the rendered feet-origin Y + anchor Y for proof.
        info["render"] = page.evaluate(
            """(loc) => {
                const st = window.PenthouseAnim.AnimManager.getState('Probe');
                const m = st ? st.model : null;
                const lp = window.penthouse3D.getLocationPositions()[loc] || {};
                return {
                  group_y: m ? +m.group.position.y.toFixed(4) : null,
                  base_y: m ? +(m._baseY||0).toFixed(4) : null,
                  state: st ? st.currentState : null,
                  anchor: lp.anchor || null,
                  surface_y: (lp.y !== undefined) ? lp.y : null,
                  resolved_base: +window.penthouse3D.resolveAnchorY(lp).toFixed(4),
                };
            }""",
            loc,
        )

        page.wait_for_timeout(200)
        page.screenshot(path=str(out))
        info["errors"] = [e for e in errors if "ERR_CONNECTION_REFUSED" not in e][:8]
        browser.close()

    return info


def main() -> int:
    ap = argparse.ArgumentParser(description="Penthouse anchor-placement screenshot")
    ap.add_argument("--loc", default="bed")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--legacy", action="store_true", help="Reproduce pre-fix sink")
    args = ap.parse_args()

    info = capture(args.loc, args.out, args.legacy)
    print(f"[{'BEFORE' if args.legacy else 'AFTER '}] loc={info['loc']}")
    r = info.get("render", {})
    print(f"  state={r.get('state')} anchor={r.get('anchor')} surface_y={r.get('surface_y')}")
    print(f"  resolved_base={r.get('resolved_base')} model._baseY={r.get('base_y')} "
          f"rendered group.y={r.get('group_y')}")
    print(f"  saved -> {info['out']}")
    if info.get("errors"):
        print(f"  JS errors: {info['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
