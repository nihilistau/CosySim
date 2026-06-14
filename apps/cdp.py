#!/usr/bin/env python3
"""
CDP CLI - Chrome DevTools Protocol Tools
==========================================

Live browser inspection, DOM debugging, network capture, JS evaluation,
screenshots, and persistent monitoring.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/cdp.py tabs                        # List open tabs
    python apps/cdp.py dom [tab] [--url URL]       # Full DOM report
    python apps/cdp.py css [tab] SELECTOR          # Computed CSS
    python apps/cdp.py net [tab]                   # Network + console capture
    python apps/cdp.py api [tab] PATH              # Fetch API from page context
    python apps/cdp.py js  [tab] EXPR              # Evaluate JS expression
    python apps/cdp.py snap [tab] [FILE]           # Screenshot to PNG
    python apps/cdp.py trace [tab] [--url URL]     # Full trace (DOM+CSS+net)
    python apps/cdp.py monitor                     # Persistent live watcher
    python apps/cdp.py probe                       # Attach to NLM tab
    python apps/cdp.py debug [--url URL]           # Navigate + capture events
    python apps/cdp.py mine                        # Extract training data from logs
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print("""
  CDP - Chrome DevTools Protocol Tools v1.57.2
  =============================================

  Usage: python apps/cdp.py <command> [args...]

  Inspection:
    tabs                        List open Chrome tabs
    dom [tab] [--url URL]       Full DOM/z-index/hit-test report
    css [tab] SELECTOR          Computed CSS for element
    net [tab]                   Capture network + console for 8s
    api [tab] PATH              Fetch API route from page context
    js  [tab] EXPR              Evaluate JS expression
    snap [tab] [FILE]           Screenshot to PNG
    trace [tab] [--url URL]     DOM + CSS + net + console all at once

  Monitoring:
    monitor                     Persistent live browser watcher
    probe                       Attach to NLM tab, inject fetch calls
    debug [--url URL]           Navigate to scene, capture events
    mine                        Extract training data from CDP logs

  Chrome must be running with --remote-debugging-port=9223
""")
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "monitor": SCRIPTS / "cdp_monitor.py",
        "probe":   SCRIPTS / "cdp_live_probe.py",
        "debug":   SCRIPTS / "cdp_debug.py",
        "mine":    SCRIPTS / "cdp_data_miner.py",
    }

    if cmd in dispatch:
        return run(dispatch[cmd], rest)

    # Default: cdp_inspect.py handles tabs, dom, css, net, api, js, snap, trace
    return run(SCRIPTS / "cdp_inspect.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
