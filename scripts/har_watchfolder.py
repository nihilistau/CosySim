"""HAR Watchfolder — auto-import Google cookies from dropped HAR files.

Polls data/hars/ every 30 seconds. When a new .har file appears, it is
immediately parsed for Google auth cookies and imported into the account
pool, then moved to data/hars/imported/.

Run as a persistent background process alongside cdp_monitor.py:
    python scripts/har_watchfolder.py [--interval 30] [--watch-dir data/hars]

The account name is inferred from the filename stem (e.g. nihilistcod.har
→ account "nihilistcod"). You can also name files with a timestamp suffix
to force re-import of the same account (e.g. nihilistcod_20260304.har).

All events are logged to logs/har_watchfolder.log and stored in Nexus.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

# Allow running from project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("har_watchfolder")

WATCH_DIR = PROJECT_ROOT / "data" / "hars"
IMPORTED_DIR = WATCH_DIR / "imported"
FAILED_DIR = WATCH_DIR / "failed"
LOG_FILE = PROJECT_ROOT / "logs" / "har_watchfolder.log"
DEFAULT_INTERVAL = 30  # seconds between polls
DEFAULT_SERVICES = ["colab", "notebooklm", "github_copilot"]


# ──── Setup ───────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt)
    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt))
    fh.setLevel(level)
    logger.addHandler(fh)


def _infer_account_name(har_path: Path) -> str:
    """Derive account name from filename, stripping timestamp suffixes.

    Examples:
        nihilistcod.har          -> nihilistcod
        nihilistcod_20260304.har -> nihilistcod
        myaccount_2026-03-04.har -> myaccount
    """
    stem = har_path.stem
    # Strip trailing _YYYYMMDD or _YYYY-MM-DD
    import re
    stem = re.sub(r"[_-]\d{4}[-]?\d{2}[-]?\d{2}$", "", stem)
    return stem.strip("_-") or stem


# ──── Import logic ────────────────────────────────────────────────────────────

def _import_har(har_path: Path, account_name: str) -> dict:
    """Import a HAR file into the account pool.

    Returns a result dict with keys: success, account_name, cookie_count,
    age_days, error.
    """
    from engine.integrations.google_account_pool import get_account_pool

    pool = get_account_pool()

    try:
        account = pool.import_from_har(
            str(har_path),
            account_name,
            services=DEFAULT_SERVICES,
        )
        pool.save()
        return {
            "success": True,
            "account_name": account_name,
            "cookie_count": len(account.cookies),
            "age_days": 0.0,
            "services": account.services,
        }
    except Exception as exc:
        return {
            "success": False,
            "account_name": account_name,
            "error": str(exc),
        }


def _store_nexus_event(event_type: str, data: dict) -> None:
    """Record HAR import event in Nexus."""
    try:
        import requests
        title = f"HAR Import: {data.get('account_name','?')} ({event_type})"
        content_lines = [f"**Event:** {event_type}"]
        for k, v in data.items():
            content_lines.append(f"**{k}:** {v}")
        requests.post(
            "http://localhost:8700/api/entries",
            json={
                "title": title,
                "content": "\n".join(content_lines),
                "content_type": "note",
                "category": "system",
                "tags": ["har-import", "cookie-refresh", event_type],
            },
            timeout=5,
        )
    except Exception:
        pass  # Nexus down — not critical


# ──── Probe helpers ───────────────────────────────────────────────────────────

def _probe_notebooklm(account_name: str) -> bool:
    """Quick auth probe against NotebookLM homepage. Returns True if authenticated."""
    try:
        from engine.integrations.google_account_pool import get_account_pool
        pool = get_account_pool()
        acct = pool.get_by_name(account_name)
        if not acct:
            return False

        import requests
        cookie_header = pool.get_cookie_header(acct)
        resp = requests.get(
            "https://notebooklm.google.com",
            headers={"Cookie": cookie_header, "User-Agent": "Mozilla/5.0"},
            allow_redirects=False,
            timeout=10,
        )
        # Authenticated users get 200; unauthenticated get 302 to accounts.google.com
        return resp.status_code == 200
    except Exception:
        return False


def _probe_colab(account_name: str) -> bool:
    """Quick auth probe against Colab API. Returns True if authenticated."""
    try:
        from engine.integrations.google_account_pool import get_account_pool
        pool = get_account_pool()
        acct = pool.get_by_name(account_name)
        if not acct:
            return False

        import requests
        cookie_header = pool.get_cookie_header(acct)
        resp = requests.get(
            "https://colab.research.google.com/api/kernels",
            headers={"Cookie": cookie_header, "User-Agent": "Mozilla/5.0"},
            allow_redirects=False,
            timeout=10,
        )
        return resp.status_code in (200, 204)
    except Exception:
        return False


# ──── Main loop ───────────────────────────────────────────────────────────────

def watch_loop(interval: int = DEFAULT_INTERVAL) -> None:
    """Main polling loop. Runs indefinitely until interrupted."""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("HAR watchfolder started. Watching: %s (interval: %ds)", WATCH_DIR, interval)

    seen: set = set()

    while True:
        try:
            har_files = list(WATCH_DIR.glob("*.har"))
            json_files = list(WATCH_DIR.glob("*.json"))
            for har_path in har_files + json_files:
                if har_path.name in seen:
                    continue

                # Protocol Monitor JSON exports → ARGUS rpcid import
                if har_path.suffix == ".json":
                    logger.info("Protocol Monitor JSON detected: %s", har_path.name)
                    try:
                        from scripts.argus.importers.protocol_monitor import (
                            import_protocol_monitor_json,
                            merge_into_registry,
                        )
                        pm_result = import_protocol_monitor_json(har_path)
                        if "error" not in pm_result:
                            counts = merge_into_registry(pm_result)
                            logger.info(
                                "Protocol Monitor import: %d rpcids, %d gRPC, %d cookies",
                                pm_result["stats"]["unique_rpcids"],
                                pm_result["stats"]["unique_grpc_methods"],
                                pm_result["stats"]["cookies_found"],
                            )
                            # Also import cookies if found
                            if pm_result.get("cookies"):
                                account_name = _infer_account_name(har_path)
                                from engine.integrations.google_account_pool import get_account_pool
                                pool = get_account_pool()
                                acct = pool.get_by_name(account_name)
                                if acct:
                                    acct.cookies.update(pm_result["cookies"])
                                    pool.save()
                            dest = IMPORTED_DIR / f"{har_path.stem}_{int(time.time())}.json"
                            shutil.move(str(har_path), str(dest))
                            _store_nexus_event("protocol_monitor_import", {
                                "rpcids": pm_result["stats"]["unique_rpcids"],
                                "grpc_methods": pm_result["stats"]["unique_grpc_methods"],
                                **counts,
                            })
                        else:
                            logger.error("Protocol Monitor import failed: %s", pm_result["error"])
                            dest = FAILED_DIR / har_path.name
                            shutil.move(str(har_path), str(dest))
                    except Exception as exc:
                        logger.error("Protocol Monitor import error: %s", exc)
                    seen.add(har_path.name)
                    continue

                account_name = _infer_account_name(har_path)
                logger.info("New HAR detected: %s → account '%s'", har_path.name, account_name)

                result = _import_har(har_path, account_name)

                if result["success"]:
                    dest = IMPORTED_DIR / f"{har_path.stem}_{int(time.time())}.har"
                    shutil.move(str(har_path), str(dest))
                    logger.info(
                        "Imported '%s': %d cookies | moved to %s",
                        account_name,
                        result["cookie_count"],
                        dest.name,
                    )
                    _store_nexus_event("import_success", result)
                else:
                    dest = FAILED_DIR / har_path.name
                    shutil.move(str(har_path), str(dest))
                    logger.error(
                        "Import failed for '%s': %s | moved to %s",
                        account_name,
                        result.get("error"),
                        dest.name,
                    )
                    _store_nexus_event("import_failed", result)

                seen.add(har_path.name)

        except KeyboardInterrupt:
            logger.info("HAR watchfolder stopped")
            break
        except Exception as exc:
            logger.error("Watchfolder error: %s", exc)

        time.sleep(interval)


def run_health_check() -> dict:
    """Probe all pool accounts and return a health report.

    Returns dict with:
        - accounts: list of {name, age_days, stale, nlm_ok, colab_ok}
        - stale_count: number of stale accounts
        - total: total account count
    """
    from engine.integrations.google_account_pool import get_account_pool

    pool = get_account_pool()
    accounts_info = pool.list_accounts()

    report: list = []
    for info in accounts_info:
        name = info["name"]
        acct = pool.get_by_name(name)
        age_days = round(acct.cookie_age_days(), 1) if acct else 0.0
        stale = acct.is_stale() if acct else True

        nlm_ok = _probe_notebooklm(name) if not stale else False
        colab_ok = _probe_colab(name) if not stale else False

        status = "ok" if (not stale and (nlm_ok or colab_ok)) else ("stale" if stale else "auth_failed")
        logger.info("  %s: age=%.1fd  stale=%s  nlm=%s  colab=%s  → %s",
                    name, age_days, stale, nlm_ok, colab_ok, status)

        report.append({
            "name": name,
            "age_days": age_days,
            "stale": stale,
            "nlm_ok": nlm_ok,
            "colab_ok": colab_ok,
            "status": status,
        })

    stale_count = sum(1 for r in report if r["stale"])
    return {
        "accounts": report,
        "stale_count": stale_count,
        "total": len(report),
        "healthy_count": sum(1 for r in report if r["status"] == "ok"),
    }


# ──── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HAR Watchfolder — auto-import Google cookies")
    sub = parser.add_subparsers(dest="command")

    # watch (default)
    watch_p = sub.add_parser("watch", help="Start polling loop (default)")
    watch_p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                         help="Seconds between polls (default 30)")
    watch_p.add_argument("--watch-dir", default=str(WATCH_DIR),
                         help="Directory to watch")

    # import single file
    import_p = sub.add_parser("import", help="Import a single HAR file immediately")
    import_p.add_argument("har_file", help="Path to .har file")
    import_p.add_argument("--name", help="Account name (inferred from filename if omitted)")

    # health check
    sub.add_parser("health", help="Probe all accounts and report status")

    # status
    sub.add_parser("status", help="List all accounts and cookie ages")

    args = parser.parse_args()
    _setup_logging()

    if args.command == "import":
        har_path = Path(args.har_file)
        name = args.name or _infer_account_name(har_path)
        result = _import_har(har_path, name)
        print(json.dumps(result, indent=2))

    elif args.command == "health":
        report = run_health_check()
        print(json.dumps(report, indent=2))
        if report["stale_count"]:
            print(f"\n⚠  {report['stale_count']} stale account(s). Drop a fresh HAR into {WATCH_DIR}")

    elif args.command == "status":
        from engine.integrations.google_account_pool import get_account_pool
        pool = get_account_pool()
        for info in pool.list_accounts():
            acct = pool.get_by_name(info["name"])
            age = round(acct.cookie_age_days(), 1) if acct else "?"
            stale = "! STALE" if (acct and acct.is_stale()) else "ok"
            print(f"  {stale}  {info['name']}  age={age}d  cookies={info['cookie_count']}  services={info['services']}")
        stale = pool.get_stale_accounts()
        if stale:
            print(f"\nTo refresh: drop a new .har file into {WATCH_DIR}")
            print("Then run: python scripts/har_watchfolder.py watch")

    else:
        # Default: start watch loop
        interval = getattr(args, "interval", DEFAULT_INTERVAL)
        watch_loop(interval)


if __name__ == "__main__":
    main()
