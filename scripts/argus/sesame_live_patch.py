#!/usr/bin/env python3
"""
Sesame Live Patch — Statsig gate flip + Maya-Alpha WebSocket intercept
======================================================================

A single, self-contained client-side patch for a live Sesame session, applied
over Chrome DevTools Protocol (CDP). It does two things in one shot:

    1. Flips every Statsig feature gate in localStorage to enabled (unlocks
       gated UI/features), and nudges known dynamic configs.
    2. Installs a `WebSocket.prototype.send` interceptor that rewrites the
       `call_connect` frame's `settings.character` to a target character
       (default: "Maya-Alpha", the unreleased alpha voice model).

The combined JS is exposed as `COMBINED_PATCH_JS` so it can be pasted straight
into the DevTools console (`--dump-js`), and `apply_live()` injects + verifies it
via CDP. Both effects are reversible: reload the page (drops the in-memory WS
patch and re-evaluates gates against the server), or clear the
`statsig.cached.evaluations.*` localStorage keys.

Intelligence + findings: ../../sesame.md

Version: v1.63.1 [2026-06-18]
Author:  CosySim Team

Change Log:
    v1.63.1 [2026-06-18] — Initial: combined gate-flip + Maya-Alpha WS intercept,
                            CDP injector with before/after verification, --dump-js

Usage:
    .venv/Scripts/python.exe -m scripts.argus.sesame_live_patch
    .venv/Scripts/python.exe -m scripts.argus.sesame_live_patch --gates-only
    .venv/Scripts/python.exe -m scripts.argus.sesame_live_patch --ws-only --character Maya-Alpha
    .venv/Scripts/python.exe -m scripts.argus.sesame_live_patch --dump-js

CONNECTS: scripts.argus.toolkit.cdp_eval (CDP :9223)
CALLED BY: ARGUS Sesame live-test / operator console
EMITS: localStorage gate mutations + WebSocket.prototype.send wrapper in the live tab
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.argus.toolkit import cdp_eval

logger = logging.getLogger(__name__)

DEFAULT_CHARACTER = "Maya-Alpha"
DEFAULT_TAB_FILTER = "sesame"
DEFAULT_CDP_PORT = 9223


# ──── Patch fragments (JS) ─────────────────────────────────────────────────────

# Flip every Statsig feature gate to enabled + nudge known dynamic configs.
GATES_JS = r"""
  // -- 1. Statsig gates -> all enabled --
  try {
    const keys = Object.keys(localStorage).filter(k => k.includes('statsig.cached.evaluations'));
    let flipped = 0, total = 0, on = 0;
    for (const k of keys) {
      const outer = JSON.parse(localStorage.getItem(k));
      const inner = JSON.parse(outer.data);
      const gates = inner.feature_gates || {};
      for (const g of Object.values(gates)) {
        total++;
        if (!g.value) { g.value = true; g.rule_id = 'argus'; flipped++; }
      }
      for (const cfg of Object.values(inner.dynamic_configs || {})) {
        if (cfg.value && typeof cfg.value === 'object') {
          if ('show_toggle' in cfg.value) cfg.value.show_toggle = true;
          if ('webrtc_log_level' in cfg.value) cfg.value.webrtc_log_level = 'verbose';
        }
      }
      on += Object.values(gates).filter(g => g.value).length;
      outer.data = JSON.stringify(inner);
      localStorage.setItem(k, JSON.stringify(outer));
    }
    out.gates_caches = keys.length;
    out.gates_flipped = flipped;
    out.gates_total = total;
    out.gates_on = on;
  } catch (e) { out.gates_error = String(e); }
"""

# Wrap WebSocket.prototype.send so call_connect.settings.character → target.
# Idempotent: guarded by window.__ARGUS_WS_PATCHED__ (records the target char).
WS_JS = r"""
  // -- 2. Maya-Alpha WebSocket character-swap intercept --
  try {
    if (window.__ARGUS_WS_PATCHED__ !== TARGET_CHARACTER) {
      const _orig = window.__ARGUS_WS_ORIG_SEND__ || WebSocket.prototype.send;
      window.__ARGUS_WS_ORIG_SEND__ = _orig;
      WebSocket.prototype.send = function (data) {
        if (typeof data === 'string' && data.includes('call_connect')) {
          try {
            const p = JSON.parse(data);
            if (p.type === 'call_connect' && p.settings) {
              const prev = p.settings.character;
              p.settings.character = TARGET_CHARACTER;
              data = JSON.stringify(p);
              console.log('[ARGUS] character: ' + prev + ' -> ' + TARGET_CHARACTER);
            }
          } catch (_) {}
        }
        return _orig.call(this, data);
      };
      window.__ARGUS_WS_PATCHED__ = TARGET_CHARACTER;
      out.ws_newly_patched = true;
    } else {
      out.ws_newly_patched = false;
    }
    out.ws_patched = (window.__ARGUS_WS_PATCHED__ === TARGET_CHARACTER);
  } catch (e) { out.ws_error = String(e); }
"""

_WRAP_HEAD = '(function(){\n  const TARGET_CHARACTER = "__CHARACTER__";\n  const out = { character: TARGET_CHARACTER };\n'
_WRAP_TAIL = '\n  return JSON.stringify(out);\n})()'


def build_patch_js(character: str = DEFAULT_CHARACTER, gates: bool = True, ws: bool = True) -> str:
    """Assemble the combined patch JS for a target character.

    Args:
        character: Character to swap call_connect frames to.
        gates: Include the Statsig gate-flip fragment.
        ws: Include the WebSocket intercept fragment.

    Returns:
        A self-contained JS IIFE that returns a JSON status string.
    """
    body = ""
    if gates:
        body += GATES_JS
    if ws:
        body += WS_JS
    return (_WRAP_HEAD + body + _WRAP_TAIL).replace("__CHARACTER__", character)


# Canonical full patch (both effects, default character) for console paste / import.
COMBINED_PATCH_JS = build_patch_js()


# ──── Live application over CDP ────────────────────────────────────────────────

def apply_live(
    character: str = DEFAULT_CHARACTER,
    gates: bool = True,
    ws: bool = True,
    cdp_port: int = DEFAULT_CDP_PORT,
    tab_filter: str = DEFAULT_TAB_FILTER,
) -> Dict[str, Any]:
    """Inject the patch into the live Sesame tab and verify it.

    Args:
        character: Target character for the WebSocket swap.
        gates: Apply the gate flip.
        ws: Apply the WebSocket intercept.
        cdp_port: Chrome DevTools Protocol port.
        tab_filter: Substring matched against open tab URLs.

    Returns:
        The parsed patch result plus an independent ``verified`` block.
    """
    js = build_patch_js(character, gates=gates, ws=ws)
    raw = cdp_eval(js, cdp_port=cdp_port, tab_filter=tab_filter)
    try:
        result: Dict[str, Any] = json.loads(raw)
    except Exception:
        logger.error("[SesameLivePatch] inject failed (operation=apply_live): %s", str(raw)[:300])
        return {"error": str(raw)}

    # Independent re-read so we trust state, not just the patch's own report.
    verify_js = (
        "(function(){const out={};"
        "const k=Object.keys(localStorage).find(k=>k.includes('statsig.cached.evaluations.'));"
        "if(k){const g=JSON.parse(JSON.parse(localStorage.getItem(k)).data).feature_gates||{};"
        "out.gates_total=Object.keys(g).length;out.gates_on=Object.values(g).filter(x=>x.value).length;}"
        "out.ws_flag=window.__ARGUS_WS_PATCHED__||null;"
        "return JSON.stringify(out);})()"
    )
    try:
        result["verified"] = json.loads(cdp_eval(verify_js, cdp_port=cdp_port, tab_filter=tab_filter))
    except Exception as exc:  # pragma: no cover - best-effort verification
        result["verified"] = {"error": str(exc)}
    return result


# ──── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Sesame live patch — gates + Maya-Alpha WS intercept")
    parser.add_argument("--character", default=DEFAULT_CHARACTER, help="Target character (default: Maya-Alpha)")
    parser.add_argument("--gates-only", action="store_true", help="Only flip Statsig gates")
    parser.add_argument("--ws-only", action="store_true", help="Only install the WebSocket intercept")
    parser.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, help="Chrome CDP port (default: 9223)")
    parser.add_argument("--tab", default=DEFAULT_TAB_FILTER, help="Tab URL filter (default: sesame)")
    parser.add_argument("--dump-js", action="store_true", help="Print the patch JS for console paste and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    do_gates = not args.ws_only
    do_ws = not args.gates_only

    if args.dump_js:
        print(build_patch_js(args.character, gates=do_gates, ws=do_ws))
        return 0

    print("=" * 60)
    print("  SESAME LIVE PATCH")
    print(f"  gates={do_gates}  ws={do_ws}  character={args.character}  port={args.port}")
    print("=" * 60)

    result = apply_live(args.character, gates=do_gates, ws=do_ws, cdp_port=args.port, tab_filter=args.tab)

    if "error" in result:
        print(f"  [FAIL] {result['error']}")
        print("  Is Chrome running with --remote-debugging-port=9223 on a Sesame tab?")
        return 1

    print(json.dumps(result, indent=2))

    v = result.get("verified", {})
    gates_ok = (not do_gates) or (v.get("gates_total") and v.get("gates_on") == v.get("gates_total"))
    ws_ok = (not do_ws) or (v.get("ws_flag") == args.character)
    ok = bool(gates_ok and ws_ok)
    print(f"\n  [{'PASS' if ok else 'FAIL'}] "
          f"gates {v.get('gates_on')}/{v.get('gates_total')} · ws_flag={v.get('ws_flag')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
