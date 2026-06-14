#!/usr/bin/env python3
"""
HAR CLI - HTTP Archive Analysis
==================================

Analyze, mine, capture, and watch HAR files. Extract endpoints,
rpcids, cookies, authentication schemes, and protocol details.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/har.py list                          # List all HAR files
    python apps/har.py analyze file.har              # Quick analysis summary
    python apps/har.py deep file.har                 # Deep mine for endpoints
    python apps/har.py payloads file.har             # Extract operation codes
    python apps/har.py cookies file.har              # Extract all cookies
    python apps/har.py capture                       # Cookie refresh via CDP
    python apps/har.py watch                         # Watch folder for new HARs
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, ROOT, SCRIPTS
bootstrap()


def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print("""
  HAR - HTTP Archive Analysis v1.57.2
  =====================================

  Usage: python apps/har.py <command> [args...]

  Commands:
    list                      List all known HAR files
    analyze <file>            Quick analysis summary
    deep <file>               Deep mine for endpoints, rpcids, schemas
    payloads <file>           Extract operation codes, model IDs, params
    cookies <file> [--domain] Extract all cookies from HAR
    capture                   Automated cookie refresh via CDP
    watch                     Watch folder for new HAR files
""")
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd in ("list", "ls"):
        from engine.integrations.har_parser import list_har_files
        files = list_har_files()
        if not files:
            print("No HAR files found.")
            return 0
        print(f"\n  HAR Files ({len(files)} found)")
        print(f"  {'-' * 70}")
        for f in files:
            print(f"  {f['size_mb']:>6.1f} MB  {f['name']}")
        print()
        return 0

    elif cmd == "analyze":
        if not rest:
            print("Usage: har analyze <file>")
            return 1
        from engine.integrations.har_parser import analyze_har
        print(json.dumps(analyze_har(rest[0]), indent=2))
        return 0

    elif cmd == "cookies":
        if not rest:
            print("Usage: har cookies <file> [--domain github.com]")
            return 1
        from engine.integrations.har_parser import extract_cookies
        domain = None
        if "--domain" in rest:
            idx = rest.index("--domain")
            if idx + 1 < len(rest):
                domain = rest[idx + 1]
        cookies = extract_cookies(rest[0], domain=domain)
        for k, v in sorted(cookies.items()):
            print(f"  {k} = {v[:50]}{'...' if len(v) > 50 else ''}")
        print(f"\n  Total: {len(cookies)} cookies")
        return 0

    elif cmd == "deep":
        return run(SCRIPTS / "har_deep_explorer.py", rest)

    elif cmd == "payloads":
        return run(SCRIPTS / "har_payload_analyzer.py", rest)

    elif cmd == "capture":
        return run(SCRIPTS / "har_capture.py", rest)

    elif cmd == "watch":
        return run(SCRIPTS / "har_watchfolder.py", rest)

    else:
        print(f"Unknown command: {cmd}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
