#!/usr/bin/env python3
"""
Account CLI - Cookie Pool Management
=======================================

Manage the Google/GitHub account cookie pool. Import from HAR files,
extract from Chrome, refresh via CDP, list accounts.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/account.py list                              # List all accounts
    python apps/account.py import github.har                 # Import GitHub cookies
    python apps/account.py import nlm.har --name knack112358 # Import NLM cookies
    python apps/account.py import github.har --analyze       # Analyze without importing
    python apps/account.py cookies                           # Extract from Chrome
    python apps/account.py refresh                           # Refresh via CDP
    python apps/account.py refresh --mode cdp                # Force CDP mode
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, run_module, ROOT, SCRIPTS
bootstrap()

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="account",
        description="Account pool management - cookies, imports, listing",
    )
    sub = parser.add_subparsers(dest="subcmd")

    # list
    sub.add_parser("list", aliases=["ls"], help="List all accounts in the pool")

    # import
    imp = sub.add_parser("import", help="Import cookies from HAR or JSON file")
    imp.add_argument("file", help="Path to .har or .json file")
    imp.add_argument("--name", "-n", help="Account name (auto-detected for GitHub)")
    imp.add_argument("--service", "-s", default=None,
                     help="Service: github, notebooklm, colab, aistudio")
    imp.add_argument("--json", "-j", action="store_true", help="File is JSON cookies")
    imp.add_argument("--analyze", "-a", action="store_true", help="Analyze only, don't import")

    # cookies
    cookies_p = sub.add_parser("cookies", help="Extract cookies from Chrome via CDP/DPAPI")
    cookies_p.add_argument("--account", default=None, help="Account name for pool")

    # refresh
    refresh_p = sub.add_parser("refresh", help="Refresh Google cookies via CDP")
    refresh_p.add_argument("--mode", choices=["cdp", "launch", "macro"])
    refresh_p.add_argument("--account", default=None)

    parsed, remaining = parser.parse_known_args()

    if parsed.subcmd in ("list", "ls"):
        return _account_list()

    elif parsed.subcmd == "import":
        is_github = "github" in parsed.file.lower()
        if is_github or parsed.service == "github":
            extra = [parsed.file]
            if parsed.name:
                extra += ["--name", parsed.name]
            if parsed.analyze:
                extra += ["--analyze"]
            if parsed.json:
                extra += ["--json"]
            return run_module("engine.integrations.github_account_importer", extra)
        else:
            # Generic HAR import
            from engine.integrations.har_parser import analyze_har, extract_cookies, import_har_to_pool
            filepath = parsed.file
            if not os.path.isabs(filepath):
                filepath = str(ROOT / filepath)

            if parsed.analyze:
                result = analyze_har(filepath)
                print(json.dumps(result, indent=2))
                return 0

            account_name = parsed.name
            if not account_name:
                fname = os.path.basename(filepath).lower()
                for known in ["knack112358", "knack122358", "nihilistcod", "nihilistau"]:
                    if known in fname:
                        account_name = known
                        break
                if not account_name:
                    print("ERROR: Use --name <account>")
                    return 1

            service = parsed.service or "notebooklm"
            result = import_har_to_pool(filepath, account_name, services=[service])
            if result.get("ok"):
                print(f"\n  Import SUCCESS: {result['cookies_imported']} cookies for {result['account_name']}")
            else:
                print(f"ERROR: {result.get('error')}")
                return 1
            return 0

    elif parsed.subcmd == "cookies":
        extra = []
        if parsed.account:
            extra += ["--update-pool", parsed.account]
        return run(SCRIPTS / "chrome_cookie_extractor.py", extra)

    elif parsed.subcmd == "refresh":
        extra = []
        if parsed.mode:
            extra += ["--mode", parsed.mode]
        if parsed.account:
            extra += ["--account", parsed.account]
        return run(SCRIPTS / "har_capture.py", extra)

    else:
        parser.print_help()
        return 0


def _account_list() -> int:
    pool_path = ROOT / "data" / "accounts" / "pool.json"
    if not pool_path.exists():
        print("No account pool found.")
        return 1

    with open(pool_path, "r", encoding="utf-8") as f:
        pool = json.load(f)

    print(f"\n  Account Pool ({pool_path.relative_to(ROOT)})")
    print(f"  {'-' * 60}")
    print(f"  {'Name':<20} {'Services':<30} {'Cookies':<10}")
    print(f"  {'-' * 60}")

    for name, data in pool.items():
        if isinstance(data, dict):
            services = data.get("services", [])
            cookies = data.get("cookies", {})
            count = len(cookies) if isinstance(cookies, (dict, list)) else 0
            svc = ", ".join(services) if isinstance(services, list) else str(services)
            print(f"  {name:<20} {svc:<30} {count:<10}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
