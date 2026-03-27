#!/usr/bin/env python3
"""
CosySim Unified CLI
====================

Single entry point for all CosySim tools, scripts, and diagnostics.
Automatically handles venv activation and sys.path setup.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] — Initial unified CLI with 10 command groups

Usage:
    python cli.py ask "What is CosySim?"                    # AI query (Copilot/NLM/local)
    python cli.py oracle                                     # System diagnostics
    python cli.py account list                               # Account pool
    python cli.py account import github.har                  # Import cookies from HAR
    python cli.py har analyze file.har                       # HAR analysis
    python cli.py har capture                                # Cookie refresh via CDP
    python cli.py heap mine snapshot.heapsnapshot             # Heap mining
    python cli.py argus har file.har                         # ARGUS deep analysis
    python cli.py cdp tabs                                   # Chrome DevTools
    python cli.py nlm ask "question"                         # NotebookLM query
    python cli.py nlm ingest --file docs/ARCH.md             # Ingest into NLM
    python cli.py test                                       # Smart test runner
    python cli.py test --smoke                               # Smoke tests
    python cli.py scene health                               # Scene health check
    python cli.py scene browser --scene penthouse            # Browser test
    python cli.py cleanup                                    # Disk cleanup
    python cli.py launch penthouse                           # Launch a scene
    python cli.py launch --list                              # List all targets
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ──── Bootstrap ───────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Ensure venv python and project root on sys.path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# If we're not running from the venv, re-exec with venv python via subprocess
# (os.execv doesn't propagate stdout on Windows)
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    result = subprocess.run([str(VENV_PYTHON)] + sys.argv, cwd=str(ROOT))
    sys.exit(result.returncode)

# Ensure project root on sys.path for engine imports
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure CWD is project root for relative paths (pool.json etc.)
os.chdir(ROOT)

SCRIPTS = ROOT / "scripts"


# ──── Subprocess helper ──────────────────────────────────────────────────────

def _run(script: Path, args: list[str], description: str = "") -> int:
    """Run a script with the venv python, forwarding all args.

    Args:
        script: Path to the .py script.
        args: Arguments to pass through.
        description: Optional description for error messages.

    Returns:
        Exit code from the subprocess.
    """
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [python, str(script)] + args
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        print(f"ERROR: Script not found: {script}")
        return 1


def _run_module(module: str, args: list[str]) -> int:
    """Run a python module with -m, forwarding args.

    Args:
        module: Module path (e.g. 'engine.nexus.cli').
        args: Arguments to pass through.

    Returns:
        Exit code from the subprocess.
    """
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [python, "-m", module] + args
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode
    except KeyboardInterrupt:
        return 130


# ──── Command: ask ────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — AI query routing (Copilot / NLM / LMStudio)
# CONNECTS: scripts/ask.py, scripts/nlm_ask.py

def cmd_ask(args: list[str]) -> int:
    """Route AI queries to Copilot, NLM, or LMStudio."""
    return _run(SCRIPTS / "ask.py", args, "AI query")


# ──── Command: oracle ────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — System diagnostics
# CONNECTS: scripts/oracle.py

def cmd_oracle(args: list[str]) -> int:
    """Run Oracle system diagnostics."""
    return _run(SCRIPTS / "oracle.py", args, "Oracle diagnostics")


# ──── Command: account ───────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Account pool management
# CONNECTS: engine/integrations/google_account_pool.py,
#           engine/integrations/github_account_importer.py,
#           scripts/chrome_cookie_extractor.py, scripts/har_capture.py

def cmd_account(args: list[str]) -> int:
    """Manage the Google/GitHub account cookie pool."""
    parser = argparse.ArgumentParser(
        prog="cli.py account",
        description="Account pool management — cookies, imports, listing",
    )
    sub = parser.add_subparsers(dest="subcmd")

    # account list
    sub.add_parser("list", aliases=["ls"], help="List all accounts in the pool")

    # account import <file> [--name NAME] [--service github|notebooklm|colab]
    imp = sub.add_parser("import", help="Import cookies from HAR or JSON file")
    imp.add_argument("file", help="Path to .har or .json file")
    imp.add_argument("--name", "-n", help="Account name (auto-detected for GitHub HARs)")
    imp.add_argument("--service", "-s", default=None,
                     help="Service type: github, notebooklm, colab (auto-detected from domain)")
    imp.add_argument("--json", "-j", action="store_true", help="File is JSON cookies (not HAR)")
    imp.add_argument("--analyze", "-a", action="store_true", help="Analyze only, don't import")

    # account cookies — extract from Chrome
    cookies_p = sub.add_parser("cookies", help="Extract cookies from running Chrome via CDP")
    cookies_p.add_argument("--account", default=None, help="Account name for pool import")

    # account refresh — HAR capture cookie refresh
    refresh_p = sub.add_parser("refresh", help="Refresh Google cookies via CDP browser")
    refresh_p.add_argument("--mode", choices=["cdp", "launch", "macro"], default=None)
    refresh_p.add_argument("--account", default=None)

    parsed, remaining = parser.parse_known_args(args)

    if parsed.subcmd in ("list", "ls"):
        return _account_list()

    elif parsed.subcmd == "import":
        return _account_import(parsed)

    elif parsed.subcmd == "cookies":
        extra = []
        if parsed.account:
            extra += ["--update-pool", parsed.account]
        return _run(SCRIPTS / "chrome_cookie_extractor.py", extra)

    elif parsed.subcmd == "refresh":
        extra = []
        if parsed.mode:
            extra += ["--mode", parsed.mode]
        if parsed.account:
            extra += ["--account", parsed.account]
        return _run(SCRIPTS / "har_capture.py", extra)

    else:
        parser.print_help()
        return 0


def _account_list() -> int:
    """Print all accounts in pool.json."""
    import json

    pool_path = ROOT / "data" / "accounts" / "pool.json"
    if not pool_path.exists():
        print("No account pool found at data/accounts/pool.json")
        return 1

    with open(pool_path, "r", encoding="utf-8") as f:
        pool = json.load(f)

    if not pool:
        print("Account pool is empty.")
        return 0

    print(f"\n  Account Pool ({pool_path.relative_to(ROOT)})")
    print(f"  {'-' * 60}")
    print(f"  {'Name':<20} {'Services':<30} {'Cookies':<10}")
    print(f"  {'-' * 60}")

    for name, data in pool.items():
        if isinstance(data, dict):
            services = data.get("services", [])
            cookies = data.get("cookies", {})
            cookie_count = len(cookies) if isinstance(cookies, dict) else len(cookies) if isinstance(cookies, list) else 0
            svc_str = ", ".join(services) if isinstance(services, list) else str(services)
            print(f"  {name:<20} {svc_str:<30} {cookie_count:<10}")

    print()
    return 0


def _account_import(parsed: argparse.Namespace) -> int:
    """Import cookies from HAR or JSON into the account pool."""
    filepath = parsed.file
    if not os.path.isabs(filepath):
        filepath = str(ROOT / filepath)

    # Detect service type from file content
    is_github = "github" in filepath.lower()

    if is_github or parsed.service == "github":
        # Use GitHub-specific importer (auto-detects username)
        extra = [filepath]
        if parsed.name:
            extra += ["--name", parsed.name]
        if parsed.analyze:
            extra += ["--analyze"]
        if parsed.json:
            extra += ["--json"]
        return _run_module("engine.integrations.github_account_importer", extra)

    else:
        # Use generic HAR importer for Google services
        from engine.integrations.har_parser import extract_cookies, analyze_har

        if parsed.analyze:
            result = analyze_har(filepath)
            import json
            print(json.dumps(result, indent=2))
            return 0

        cookies = extract_cookies(filepath)
        if not cookies:
            print(f"ERROR: No cookies found in {filepath}")
            return 1

        account_name = parsed.name
        if not account_name:
            # Try to detect from filename
            fname = os.path.basename(filepath).lower()
            for known in ["knack112358", "knack122358", "nihilistcod", "nihilistau"]:
                if known in fname:
                    account_name = known
                    break
            if not account_name:
                print("ERROR: Cannot auto-detect account name. Use --name <account>")
                return 1

        service = parsed.service or "notebooklm"

        from engine.integrations.har_parser import import_har_to_pool
        result = import_har_to_pool(filepath, account_name, services=[service])

        if result.get("ok"):
            print(f"\n  Cookie Import: SUCCESS")
            print(f"  {'-' * 50}")
            print(f"  Account:  {result['account_name']}")
            print(f"  Cookies:  {result['cookies_imported']}")
            print(f"  Services: {', '.join(result['services'])}")
            print()
        else:
            print(f"ERROR: {result.get('error', 'Unknown error')}")
            return 1

        return 0


# ──── Command: har ────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — HAR file operations
# CONNECTS: scripts/har_deep_explorer.py, scripts/har_payload_analyzer.py,
#           scripts/har_capture.py, scripts/har_watchfolder.py

def cmd_har(args: list[str]) -> int:
    """HAR file analysis and capture tools."""
    parser = argparse.ArgumentParser(
        prog="cli.py har",
        description="HAR file analysis, mining, and capture",
    )
    sub = parser.add_subparsers(dest="subcmd")

    sub.add_parser("analyze", help="Quick HAR analysis summary").add_argument("file")
    sub.add_parser("deep", help="Deep mine HAR for endpoints, rpcids, schemas").add_argument("file")
    sub.add_parser("payloads", help="Extract operation codes, model IDs, params").add_argument("file")
    sub.add_parser("capture", help="Automated cookie refresh via CDP")
    sub.add_parser("watch", help="Watch folder for new HAR files and auto-import")
    sub.add_parser("list", aliases=["ls"], help="List all known HAR files")

    parsed, remaining = parser.parse_known_args(args)

    if parsed.subcmd == "analyze":
        from engine.integrations.har_parser import analyze_har
        import json
        result = analyze_har(parsed.file)
        print(json.dumps(result, indent=2))
        return 0

    elif parsed.subcmd == "deep":
        return _run(SCRIPTS / "har_deep_explorer.py", [parsed.file] + remaining)

    elif parsed.subcmd == "payloads":
        return _run(SCRIPTS / "har_payload_analyzer.py", [parsed.file] + remaining)

    elif parsed.subcmd == "capture":
        return _run(SCRIPTS / "har_capture.py", remaining)

    elif parsed.subcmd == "watch":
        return _run(SCRIPTS / "har_watchfolder.py", remaining)

    elif parsed.subcmd in ("list", "ls"):
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

    else:
        parser.print_help()
        return 0


# ──── Command: heap ───────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — V8 heap snapshot analysis
# CONNECTS: scripts/heap_toolkit.py

def cmd_heap(args: list[str]) -> int:
    """V8 heap snapshot mining and analysis."""
    return _run(SCRIPTS / "heap_toolkit.py", args)


# ──── Command: argus ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — ARGUS deep analysis toolkit
# CONNECTS: scripts/argus/analyze.py

def cmd_argus(args: list[str]) -> int:
    """ARGUS API discovery and web app analysis."""
    return _run_module("scripts.argus.analyze", args)


# ──── Command: cdp ────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Chrome DevTools Protocol tools
# CONNECTS: scripts/cdp_inspect.py, scripts/cdp_monitor.py, scripts/cdp_live_probe.py

def cmd_cdp(args: list[str]) -> int:
    """Chrome DevTools Protocol — inspect, monitor, probe."""
    if not args:
        print("Usage: cli.py cdp <command> [args]")
        print()
        print("Commands:")
        print("  tabs              List open Chrome tabs")
        print("  dom [tab]         Full DOM/z-index report")
        print("  css [tab] SEL     Computed CSS for selector")
        print("  net [tab]         Capture network + console")
        print("  api [tab] PATH    Fetch API route from page context")
        print("  js  [tab] EXPR    Evaluate JS expression")
        print("  snap [tab] [FILE] Screenshot to PNG")
        print("  trace [tab]       DOM + CSS + net + console")
        print("  monitor           Persistent live browser watcher")
        print("  probe             Attach to NLM tab, inject fetch calls")
        return 0

    subcmd = args[0]
    rest = args[1:]

    if subcmd == "monitor":
        return _run(SCRIPTS / "cdp_monitor.py", rest)
    elif subcmd == "probe":
        return _run(SCRIPTS / "cdp_live_probe.py", rest)
    else:
        # Everything else goes to cdp_inspect.py
        return _run(SCRIPTS / "cdp_inspect.py", args)


# ──── Command: nlm ────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — NotebookLM operations
# CONNECTS: scripts/nlm_ask.py, scripts/nlm_ingest.py, scripts/nlm_bulk_seeder.py,
#           scripts/nlm_create_notebook.py, scripts/nlm_prompt_chain.py,
#           engine/nexus/nlm_cli.py

def cmd_nlm(args: list[str]) -> int:
    """NotebookLM — query, ingest, seed, create notebooks."""
    if not args:
        print("Usage: cli.py nlm <command> [args]")
        print()
        print("Commands:")
        print("  ask  \"question\"          Query NLM via CDP browser")
        print("  ingest --file FILE       Ingest file into NLM notebook")
        print("  create [--name NAME]     Create new NLM notebook")
        print("  seed FILE                Bulk-ask Q&A pairs from file")
        print("  chain PIPELINE           Run prompt chain pipeline")
        print("  flashcards               Generate flashcards via Gemini")
        print("  protocol                 Reverse-engineer NLM API from HAR")
        print("  cli ...                  Full NLM CLI (ask, batch-ask, distill, stats)")
        return 0

    subcmd = args[0]
    rest = args[1:]

    dispatch = {
        "ask":        SCRIPTS / "nlm_ask.py",
        "ingest":     SCRIPTS / "nlm_ingest.py",
        "create":     SCRIPTS / "nlm_create_notebook.py",
        "seed":       SCRIPTS / "nlm_bulk_seeder.py",
        "chain":      SCRIPTS / "nlm_prompt_chain.py",
        "flashcards": SCRIPTS / "nlm_flashcard_builder.py",
        "protocol":   SCRIPTS / "nlm_protocol_mapper.py",
    }

    if subcmd in dispatch:
        return _run(dispatch[subcmd], rest)
    elif subcmd == "cli":
        return _run_module("engine.nexus.nlm_cli", rest)
    else:
        print(f"Unknown nlm command: {subcmd}")
        return 1


# ──── Command: test ───────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Testing tools
# CONNECTS: scripts/smart_test.py, scripts/browser_test.py, scripts/scene_health_check.py

def cmd_test(args: list[str]) -> int:
    """Smart test runner — git-diff aware, domain-based."""
    return _run(SCRIPTS / "smart_test.py", args)


# ──── Command: scene ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Scene management and diagnostics
# CONNECTS: scripts/scene_health_check.py, scripts/browser_test.py

def cmd_scene(args: list[str]) -> int:
    """Scene health checks and browser testing."""
    if not args:
        print("Usage: cli.py scene <command> [args]")
        print()
        print("Commands:")
        print("  health [--port PORT]           CDP-based scene health check")
        print("  browser [--scene NAME] [--all] Automated browser UI test")
        return 0

    subcmd = args[0]
    rest = args[1:]

    if subcmd == "health":
        return _run(SCRIPTS / "scene_health_check.py", rest)
    elif subcmd == "browser":
        return _run(SCRIPTS / "browser_test.py", rest)
    else:
        print(f"Unknown scene command: {subcmd}")
        return 1


# ──── Command: nexus ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Nexus knowledge management
# CONNECTS: engine/nexus/cli.py

def cmd_nexus(args: list[str]) -> int:
    """Nexus KMS — search, ask, add, status, prompts, rules."""
    return _run_module("engine.nexus.cli", args)


# ──── Command: launch ─────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Scene/service launcher
# CONNECTS: launcher.py

def cmd_launch(args: list[str]) -> int:
    """Launch scenes and services."""
    return _run(ROOT / "launcher.py", args)


# ──── Command: cleanup ────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Disk cleanup
# CONNECTS: scripts/disk_cleanup.py

def cmd_cleanup(args: list[str]) -> int:
    """Disk cleanup — free space from caches, HARs, WAL files."""
    return _run(SCRIPTS / "disk_cleanup.py", args)


# ──── Command: proxy ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Model proxy server
# CONNECTS: scripts/model_proxy.py

def cmd_proxy(args: list[str]) -> int:
    """OpenAI-compatible model proxy server (port 5800)."""
    return _run(SCRIPTS / "model_proxy.py", args)


# ──── Command: filestore ──────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Gemini File Search (Managed RAG)
# CONNECTS: engine/integrations/file_search_client.py

def cmd_filestore(args: list[str]) -> int:
    """Gemini File Search - managed RAG stores."""
    return _run(ROOT / "apps" / "filestore.py", args)


# ──── Main dispatch ──────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — Top-level argparse with subcommand routing

COMMANDS = {
    "ask":       (cmd_ask,       "AI query - Copilot (38 models), NLM, or LMStudio"),
    "oracle":    (cmd_oracle,    "System diagnostics - health, errors, performance"),
    "account":   (cmd_account,   "Account pool - list, import cookies, refresh"),
    "har":       (cmd_har,       "HAR files - analyze, mine, capture, watch"),
    "heap":      (cmd_heap,      "V8 heap snapshots - mine, cookies, live scan"),
    "argus":     (cmd_argus,     "ARGUS - deep API discovery and web app analysis"),
    "cdp":       (cmd_cdp,       "Chrome DevTools - inspect, monitor, probe"),
    "nlm":       (cmd_nlm,       "NotebookLM - ask, ingest, create, seed, chain"),
    "filestore": (cmd_filestore, "Gemini File Search - managed RAG stores"),
    "test":      (cmd_test,      "Smart test runner - git-diff aware"),
    "scene":     (cmd_scene,     "Scene health checks and browser testing"),
    "nexus":     (cmd_nexus,     "Nexus KMS - search, ask, add knowledge"),
    "launch":    (cmd_launch,    "Launch scenes and services"),
    "cleanup":   (cmd_cleanup,   "Disk cleanup - free space from caches"),
    "proxy":     (cmd_proxy,     "OpenAI-compatible model proxy (port 5800)"),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print_help()
        return 0

    command = sys.argv[1]

    if command in COMMANDS:
        handler, _ = COMMANDS[command]
        return handler(sys.argv[2:])
    else:
        print(f"Unknown command: {command}")
        print()
        print_help()
        return 1


def print_help() -> None:
    """Print the top-level help message with all commands."""
    print()
    print("  CosySim CLI v1.57.2")
    print("  ===================")
    print()
    print("  Usage: python cli.py <command> [args...]")
    print()

    # Group commands by category
    groups = {
        "AI & Models": ["ask", "nlm", "nexus", "filestore", "proxy"],
        "Analysis":    ["argus", "har", "heap", "cdp"],
        "Operations":  ["oracle", "test", "scene", "launch", "cleanup"],
        "Accounts":    ["account"],
    }

    for group_name, cmd_names in groups.items():
        print(f"  {group_name}:")
        for name in cmd_names:
            if name in COMMANDS:
                _, desc = COMMANDS[name]
                print(f"    {name:<12} {desc}")
        print()

    print("  Run 'python cli.py <command> --help' for command-specific help.")
    print()


if __name__ == "__main__":
    sys.exit(main())
