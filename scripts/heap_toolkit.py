"""V8 Heap & Memory Mining Toolkit — Unified CLI.

Combines all three extraction strategies into one tool:

  1. heap    — Deep parse .heapsnapshot JSON files (V8 structured export)
               Uses scripts/heap_deep_parser.py via subprocess
  2. cookies — Decrypt Chrome on-disk cookie DB via DPAPI + AES-GCM
               Uses scripts/chrome_cookie_extractor.py
  3. live    — Scan live Chrome process memory via Windows ReadProcessMemory
               Uses scripts/chrome_live_scanner.py + MetaMap detection
  4. all     — Run all three in sequence and merge findings
  5. report  — Summarize all previous runs from data/heap_output/

All findings are documented in Nexus with full provenance.

Usage:
    python scripts/heap_toolkit.py heap data/har_files/Heap-X.heapsnapshot
    python scripts/heap_toolkit.py cookies --update-pool nihilistcod
    python scripts/heap_toolkit.py live --metamap
    python scripts/heap_toolkit.py all
    python scripts/heap_toolkit.py report
    python scripts/heap_toolkit.py nexus-push   # Push all run summaries to Nexus
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
OUT_BASE = REPO_ROOT / "data" / "heap_output"
HAR_FILES = REPO_ROOT / "data" / "har_files"
ACCOUNTS_DIR = REPO_ROOT / "data" / "accounts"

SCRIPTS = {
    "heap_deep_parser": REPO_ROOT / "scripts" / "heap_deep_parser.py",
    "cookie_extractor": REPO_ROOT / "scripts" / "chrome_cookie_extractor.py",
    "live_scanner":     REPO_ROOT / "scripts" / "chrome_live_scanner.py",
}


# ──────────────────────────────── Heap subcommand ──────────────────────────────

def cmd_heap(args: argparse.Namespace) -> int:
    """Deep parse one or more .heapsnapshot files."""
    files: List[Path] = []

    if args.files:
        for f in args.files:
            p = Path(f)
            if p.exists():
                files.append(p)
            else:
                logger.error("File not found: %s", f)
    elif args.auto:
        files = sorted(HAR_FILES.glob("**/*.heapsnapshot"), key=lambda x: x.stat().st_size)
        if not files:
            logger.error("No .heapsnapshot files found in %s", HAR_FILES)
            return 1
        logger.info("Auto-discovered %d heap files", len(files))

    if not files:
        logger.error("No heap files specified — use --files or --auto")
        return 1

    results = []
    for heap_file in files:
        logger.info("Parsing heap: %s (%.1f MB)", heap_file.name, heap_file.stat().st_size / 1e6)
        cmd = [sys.executable, str(SCRIPTS["heap_deep_parser"]), str(heap_file)]
        if getattr(args, "nexus", False):
            cmd.append("--nexus")
        if getattr(args, "strings_only", False):
            cmd.append("--strings-only")

        ret = subprocess.run(cmd, cwd=str(REPO_ROOT))
        results.append({"file": str(heap_file), "returncode": ret.returncode})

    failed = [r for r in results if r["returncode"] != 0]
    if failed:
        logger.error("%d heap(s) failed", len(failed))
        return 1

    logger.info("All %d heap(s) parsed successfully", len(results))

    if getattr(args, "nexus", False):
        _nexus_push_heap_summary(results)

    return 0


# ──────────────────────────────── Cookies subcommand ────────────────────────────

def cmd_cookies(args: argparse.Namespace) -> int:
    """Extract and decrypt Chrome cookies."""
    cmd = [sys.executable, str(SCRIPTS["cookie_extractor"])]

    if getattr(args, "profile", None):
        cmd += ["--profile", args.profile]
    if getattr(args, "all_profiles", False):
        cmd.append("--all-profiles")
    if getattr(args, "domains", None):
        cmd += ["--domains"] + args.domains
    if getattr(args, "all_domains", False):
        cmd.append("--all-domains")
    if getattr(args, "update_pool", None):
        cmd += ["--update-pool", args.update_pool]

    ret = subprocess.run(cmd, cwd=str(REPO_ROOT))

    if ret.returncode == 0 and getattr(args, "nexus", False):
        _nexus_push_cookie_event()

    return ret.returncode


# ──────────────────────────────── Live subcommand ───────────────────────────────

def cmd_live(args: argparse.Namespace) -> int:
    """Scan live Chrome process memory."""
    cmd = [sys.executable, str(SCRIPTS["live_scanner"])]

    if getattr(args, "pid", None):
        cmd += ["--pid"] + [str(p) for p in args.pid]
    if getattr(args, "metamap", False):
        cmd.append("--metamap")
    if getattr(args, "string_scan_only", False):
        cmd.append("--string-scan-only")
    if getattr(args, "nexus", False):
        cmd.append("--nexus")
    if getattr(args, "max_procs", None):
        cmd += ["--max-procs", str(args.max_procs)]

    ret = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return ret.returncode


# ──────────────────────────────── All subcommand ────────────────────────────────

def cmd_all(args: argparse.Namespace) -> int:
    """Run all extraction strategies sequentially."""
    print("\n" + "═" * 65)
    print("  V8 Heap Mining Toolkit — Full Run")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("═" * 65 + "\n")

    exit_codes = []

    # 1. Cookie extraction (fastest — DPAPI on-disk)
    print("\n[1/3] Cookie extraction (DPAPI + AES-GCM)")
    print("─" * 40)
    cookies_args = argparse.Namespace(
        profile=getattr(args, "profile", "Default"),
        all_profiles=getattr(args, "all_profiles", False),
        domains=None,
        all_domains=False,
        update_pool=getattr(args, "update_pool", None),
        nexus=getattr(args, "nexus", False),
    )
    exit_codes.append(cmd_cookies(cookies_args))

    # 2. Live memory scan
    print("\n[2/3] Live process memory scan")
    print("─" * 40)
    live_args = argparse.Namespace(
        pid=None,
        metamap=getattr(args, "metamap", False),
        string_scan_only=False,
        nexus=getattr(args, "nexus", False),
        max_procs=3,
    )
    exit_codes.append(cmd_live(live_args))

    # 3. Heap files (if any present)
    heap_files = sorted(HAR_FILES.glob("**/*.heapsnapshot"))
    if heap_files:
        print(f"\n[3/3] Heap snapshot parsing ({len(heap_files)} files)")
        print("─" * 40)
        heap_args = argparse.Namespace(
            files=[str(f) for f in heap_files],
            auto=False,
            nexus=getattr(args, "nexus", False),
            strings_only=False,
        )
        exit_codes.append(cmd_heap(heap_args))
    else:
        print("\n[3/3] No .heapsnapshot files found — skipping")
        exit_codes.append(0)

    failed = sum(1 for c in exit_codes if c != 0)
    print(f"\n{'═' * 65}")
    print(f"  Full run complete — {len(exit_codes) - failed}/{len(exit_codes)} steps successful")
    print(f"{'═' * 65}\n")

    if getattr(args, "nexus", False):
        _nexus_push_full_run_summary(exit_codes)

    return 0 if failed == 0 else 1


# ──────────────────────────────── Report subcommand ─────────────────────────────

def cmd_report(args: argparse.Namespace) -> int:
    """Summarize all previous scan runs."""
    print(f"\n{'═' * 65}")
    print(f"  Heap Mining Toolkit — Run History")
    print(f"{'═' * 65}\n")

    if not OUT_BASE.exists():
        print("  No runs found")
        return 0

    runs = []

    # Deep parse runs
    for d in sorted(OUT_BASE.iterdir()):
        if d.is_dir() and d.name.endswith("_deep"):
            report_file = d / "report.txt"
            if report_file.exists():
                lines = report_file.read_text(encoding="utf-8", errors="replace").splitlines()
                summary_lines = [l for l in lines[:20] if l.strip()]
                runs.append({
                    "type": "heap_deep_parse",
                    "dir": d.name,
                    "summary": "\n".join(summary_lines[:10]),
                })

    # Live scan runs
    for d in sorted(OUT_BASE.iterdir()):
        if d.is_dir() and d.name.startswith("live_scan_"):
            creds_file = d / "credentials.txt"
            if creds_file.exists():
                lines = creds_file.read_text(encoding="utf-8", errors="replace").splitlines()
                runs.append({
                    "type": "live_scan",
                    "dir": d.name,
                    "summary": "\n".join(lines[:10]),
                })

    if not runs:
        print("  No completed runs found in", OUT_BASE)
        return 0

    for run in runs[-10:]:  # Show last 10
        print(f"  [{run['type']}] {run['dir']}")
        for line in run["summary"].splitlines()[:5]:
            if line.strip():
                print(f"    {line}")
        print()

    # Cookie reports
    cookie_reports = sorted(ACCOUNTS_DIR.glob("chrome_cookies_*.json"))
    if cookie_reports:
        print(f"  Cookie extraction reports: {len(cookie_reports)}")
        latest = cookie_reports[-1]
        print(f"  Latest: {latest.name}")
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            print(f"    Total cookies: {data.get('total', 0)}")
            print(f"    Domains: {len(data.get('by_domain', {}))}")
        except Exception:
            pass

    print(f"\n  Total runs: {len(runs)}")
    print(f"{'═' * 65}\n")
    return 0


# ──────────────────────────────── Nexus push ────────────────────────────────────

def cmd_nexus_push(args: argparse.Namespace) -> int:
    """Push all run summaries to Nexus knowledge base."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
    except Exception as e:
        logger.error("Cannot connect to Nexus: %s", e)
        return 1

    pushed = 0

    # Deep parse index
    index_path = OUT_BASE / "deep_index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text())
            for entry in index:
                title = f"Heap Deep Parse: {Path(entry.get('file', 'unknown')).name}"
                content = json.dumps(entry, indent=2)
                client.add_entry(title, content, content_type="memory", category="debugging")
                pushed += 1
        except Exception as e:
            logger.warning("Index push failed: %s", e)

    # Live scan reports
    for d in sorted(OUT_BASE.iterdir()):
        if d.is_dir() and d.name.startswith("live_scan_"):
            report_file = d / "live_scan_report.json"
            if report_file.exists():
                try:
                    report = json.loads(report_file.read_text())
                    creds = report.get("credentials", {})
                    title = f"Chrome Live Scan: {d.name}"
                    content = json.dumps({
                        "scan_time": report.get("scan_time"),
                        "credential_types": list(creds.keys()),
                        "counts": {k: len(v) for k, v in creds.items()},
                        "total_mb": report.get("total_bytes_read", 0) // (1024 * 1024),
                    }, indent=2)
                    client.add_entry(title, content, content_type="memory", category="debugging")
                    pushed += 1
                except Exception as e:
                    logger.warning("Live scan push failed: %s", e)

    logger.info("Pushed %d entries to Nexus", pushed)
    print(f"\nPushed {pushed} entries to Nexus")
    return 0


# ──────────────────────────────── Nexus helpers ─────────────────────────────────

def _nexus_push_heap_summary(results: List[Dict]) -> None:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            "Heap Mining Run Summary",
            json.dumps({"results": results, "timestamp": datetime.now(timezone.utc).isoformat()}, indent=2),
            content_type="memory",
            category="debugging",
        )
    except Exception as e:
        logger.warning("Nexus push failed: %s", e)


def _nexus_push_cookie_event() -> None:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            f"Chrome Cookie Extraction {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "DPAPI + AES-GCM cookie extraction completed. See data/accounts/chrome_cookies_*.json for details.",
            content_type="memory",
            category="debugging",
        )
    except Exception as e:
        logger.warning("Nexus push failed: %s", e)


def _nexus_push_full_run_summary(exit_codes: List[int]) -> None:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            f"Full Mining Toolkit Run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            json.dumps({
                "steps": ["cookies", "live_scan", "heap_parse"],
                "exit_codes": exit_codes,
                "success": all(c == 0 for c in exit_codes),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            content_type="memory",
            category="debugging",
        )
        # Also store Q&A
        client.add_qa(
            "What extraction tools are available for Chrome V8 heap mining?",
            "Three tools: (1) chrome_cookie_extractor.py — DPAPI on-disk cookie DB decryption. "
            "(2) chrome_live_scanner.py — Live process ReadProcessMemory + MetaMap V8 detection. "
            "(3) heap_deep_parser.py — Full .heapsnapshot JSON graph walker. "
            "All unified via heap_toolkit.py. MetaMap signature: FF 03 20/40 (Wang et al 2022).",
        )
    except Exception as e:
        logger.warning("Nexus push failed: %s", e)


# ──────────────────────────────── Main ──────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="heap_toolkit",
        description="V8 Heap & Chrome Memory Mining Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--nexus", action="store_true", help="Store all findings in Nexus")

    sub = parser.add_subparsers(dest="command", required=True)

    # heap
    p_heap = sub.add_parser("heap", help="Deep parse .heapsnapshot files")
    p_heap.add_argument("files", nargs="*", help=".heapsnapshot file paths")
    p_heap.add_argument("--auto", action="store_true", help="Auto-discover all .heapsnapshot in data/har_files/")
    p_heap.add_argument("--strings-only", action="store_true", help="Fast string scan only")
    p_heap.add_argument("--nexus", action="store_true")

    # cookies
    p_cook = sub.add_parser("cookies", help="Decrypt Chrome on-disk cookies (DPAPI)")
    p_cook.add_argument("--profile", default="Default")
    p_cook.add_argument("--all-profiles", action="store_true")
    p_cook.add_argument("--domains", nargs="*")
    p_cook.add_argument("--all-domains", action="store_true")
    p_cook.add_argument("--update-pool", metavar="ACCOUNT")
    p_cook.add_argument("--nexus", action="store_true")

    # live
    p_live = sub.add_parser("live", help="Scan live Chrome process memory")
    p_live.add_argument("--pid", type=int, nargs="*")
    p_live.add_argument("--metamap", action="store_true", help="Enable MetaMap V8 extraction")
    p_live.add_argument("--string-scan-only", action="store_true")
    p_live.add_argument("--max-procs", type=int, default=3)
    p_live.add_argument("--nexus", action="store_true")

    # all
    p_all = sub.add_parser("all", help="Run all extraction strategies")
    p_all.add_argument("--metamap", action="store_true")
    p_all.add_argument("--update-pool", metavar="ACCOUNT")
    p_all.add_argument("--profile", default="Default")
    p_all.add_argument("--all-profiles", action="store_true")
    p_all.add_argument("--nexus", action="store_true")

    # report
    sub.add_parser("report", help="Summarize all previous runs")

    # nexus-push
    sub.add_parser("nexus-push", help="Push all run summaries to Nexus")

    args = parser.parse_args()

    # Propagate top-level --nexus to subcommand
    if hasattr(args, "nexus") and parser.parse_known_args()[0].nexus:
        args.nexus = True

    dispatch = {
        "heap": cmd_heap,
        "cookies": cmd_cookies,
        "live": cmd_live,
        "all": cmd_all,
        "report": cmd_report,
        "nexus-push": cmd_nexus_push,
    }

    handler = dispatch.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
