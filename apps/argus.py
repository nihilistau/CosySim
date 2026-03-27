#!/usr/bin/env python3
"""
ARGUS CLI - Web Application Analysis Toolkit
==============================================

Deep API discovery, HAR mining, heap analysis, CDP scripting,
bundle decompilation, and automated reconnaissance.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/argus.py har file.har                    # Analyze HAR file
    python apps/argus.py har file.har --report           # Generate markdown report
    python apps/argus.py heap file.heapsnapshot           # Mine heap snapshot
    python apps/argus.py auto path/to/captures/           # Auto-analyze directory
    python apps/argus.py compare a.har b.har              # Diff two captures
    python apps/argus.py heap-diff before.heap after.heap # Diff heap snapshots
    python apps/argus.py probe                            # Live NLM chat probe
    python apps/argus.py crawl                            # Deep NLM UI crawl
    python apps/argus.py grpc                             # gRPC/batchexecute discovery
    python apps/argus.py capture                          # Live chat capture
    python apps/argus.py registry                         # Validate RPC registry
    python apps/argus.py vision                           # Vision-based analysis
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, run_module, ROOT, SCRIPTS
bootstrap()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print_help()
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    # Core ARGUS analyze commands (har, heap, auto, compare, heap-diff, dir)
    analyze_cmds = {"har", "heap", "auto", "compare", "heap-diff", "dir"}
    if cmd in analyze_cmds:
        return run_module("scripts.argus.analyze", [cmd] + rest)

    # Extended ARGUS tools
    dispatch = {
        "probe":    SCRIPTS / "argus_chat_probe.py",
        "crawl":    SCRIPTS / "argus_deep_crawl.py",
        "grpc":     SCRIPTS / "argus_grpc_discovery.py",
        "capture":  SCRIPTS / "argus_chat_capture.py",
        "live":     SCRIPTS / "argus_live_chat.py",
    }

    if cmd in dispatch:
        return run(dispatch[cmd], rest)

    # Argus submodule tools
    module_dispatch = {
        "registry":    "scripts.argus.registry_validator",
        "vision":      "scripts.argus.vision_agent",
        "orchestrate": "scripts.argus.orchestrator",
        "mcp":         "scripts.argus.argus_mcp_server",
        "sdk":         "scripts.argus.sdk_auditor",
    }

    if cmd in module_dispatch:
        return run_module(module_dispatch[cmd], rest)

    print(f"Unknown command: {cmd}")
    print_help()
    return 1


def print_help() -> None:
    print("""
  ARGUS - Web Application Analysis Toolkit v1.57.2
  =================================================

  Usage: python apps/argus.py <command> [args...]

  Analysis:
    har <file> [--report]    Analyze HAR file
    heap <file>              Mine V8 heap snapshot
    auto <dir>               Auto-analyze all captures in directory
    compare <a> <b>          Diff two HAR files
    heap-diff <a> <b>        Diff two heap snapshots
    dir <path>               Analyze all files in directory

  Discovery:
    probe                    Live NLM chat probe via CDP
    crawl                    Systematic NLM UI crawl + RPC verification
    grpc                     Scan for all gRPC + batchexecute calls
    capture                  Type into NLM chat, capture real payload
    live                     Launch Chrome, inject query, capture traffic

  Tools:
    registry                 Validate RPC ID registry
    vision                   Vision-based page analysis
    orchestrate              Run full orchestration pipeline
    mcp                      Start ARGUS MCP server
    sdk                      Audit SDK bundles
""")


if __name__ == "__main__":
    sys.exit(main())
