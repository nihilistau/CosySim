"""Google account management skills for LLM agents.

Provides skills for monitoring cookie health, importing HAR files,
and managing the Google account pool used for NLM/Colab/Copilot access.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="google_accounts",
    description=(
        "Show health status of all Google accounts in the pool: cookie age, "
        "staleness, NLM/Colab reachability. Use this to know if HAR refresh is needed."
    ),
    category="SYSTEM",
    tags=["google", "auth", "cookies", "health"],
)
def cookie_status() -> str:
    """Return a summary of all Google account cookie health."""
    try:
        from engine.integrations.google_account_pool import get_account_pool

        pool = get_account_pool()
        accounts = pool.list_accounts()

        if not accounts:
            return (
                "No Google accounts in pool. "
                "Drop a .har file into data/hars/ to add one, "
                "or run: python scripts/har_watchfolder.py import <file.har>"
            )

        lines = ["Google Account Pool Status:", ""]
        stale_names = []

        for info in accounts:
            acct = pool.get_by_name(info["name"])
            age = round(acct.cookie_age_days(), 1) if acct else "?"
            is_stale = acct.is_stale() if acct else True
            flag = "⚠ STALE" if is_stale else "✓ OK"
            lines.append(
                f"  {flag}  {info['name']}  "
                f"age={age}d  cookies={info['cookie_count']}  "
                f"services={','.join(info['services'])}"
            )
            if is_stale:
                stale_names.append(info["name"])

        if stale_names:
            lines.append("")
            lines.append(
                f"⚠ {len(stale_names)} stale account(s): {', '.join(stale_names)}"
            )
            lines.append("To refresh: drop a new .har file into data/hars/")
            lines.append(
                "To check what HAR to capture: open notebooklm.google.com in Chrome, "
                "use DevTools → Network → Export HAR, save to data/hars/<name>.har"
            )
        else:
            lines.append("")
            lines.append("All accounts fresh — no action needed.")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("cookie_status failed: %s", exc)
        return f"Error checking cookie status: {exc}"


@skill(
    pack="google_accounts",
    description=(
        "Import a HAR file to refresh Google auth cookies for an account. "
        "Provide the path to the .har file. Account name is inferred from "
        "the filename unless specified."
    ),
    category="SYSTEM",
    tags=["google", "auth", "har", "import", "refresh"],
)
def har_import(har_path: str, account_name: str = "") -> str:
    """Import a HAR file into the Google account pool.

    Args:
        har_path: Full or relative path to the .har file.
        account_name: Account name override. Defaults to filename stem.

    Returns:
        Import result summary.
    """
    import os
    from pathlib import Path

    path = Path(har_path)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path

    if not path.exists():
        return f"File not found: {path}"

    if not account_name:
        import re
        stem = path.stem
        account_name = re.sub(r"[_-]\d{4}[-]?\d{2}[-]?\d{2}$", "", stem).strip("_-") or stem

    try:
        from engine.integrations.google_account_pool import get_account_pool

        pool = get_account_pool()
        account = pool.import_from_har(
            str(path),
            account_name,
            services=["colab", "notebooklm", "github_copilot"],
        )
        pool.save()

        return (
            f"Imported '{account_name}': "
            f"{len(account.cookies)} cookies, "
            f"services: {', '.join(account.services)}. "
            f"Cookies are fresh (age: 0d)."
        )
    except Exception as exc:
        logger.error("har_import failed: %s", exc)
        return f"Import failed: {exc}"


@skill(
    pack="google_accounts",
    description=(
        "Run a live authentication probe against NotebookLM and Colab for all "
        "accounts in the pool. Reports whether each account can actually make "
        "authenticated requests right now."
    ),
    category="SYSTEM",
    tags=["google", "auth", "probe", "health"],
    cooldown=60.0,
)
def cookie_probe() -> str:
    """Probe all pool accounts against live Google services."""
    try:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/har_watchfolder.py", "health"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent),
        )

        if result.returncode != 0:
            return f"Probe failed: {result.stderr[:200]}"

        try:
            data: Dict[str, Any] = json.loads(result.stdout)
        except Exception:
            return result.stdout[:500]

        lines = ["Cookie Probe Results:", ""]
        for acct in data.get("accounts", []):
            status = acct["status"]
            icon = "✓" if status == "ok" else "⚠"
            lines.append(
                f"  {icon} {acct['name']}  "
                f"age={acct['age_days']}d  "
                f"nlm={'✓' if acct['nlm_ok'] else '✗'}  "
                f"colab={'✓' if acct['colab_ok'] else '✗'}  "
                f"→ {status}"
            )

        lines.append("")
        lines.append(
            f"Healthy: {data.get('healthy_count',0)} / {data.get('total',0)}  |  "
            f"Stale: {data.get('stale_count',0)}"
        )

        if data.get("stale_count", 0):
            lines.append("")
            lines.append("Action needed: drop fresh .har into data/hars/ and run har_import skill.")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("cookie_probe failed: %s", exc)
        return f"Probe error: {exc}"


@skill(
    pack="google_accounts",
    description=(
        "Start the HAR watchfolder as a background process. It will auto-import "
        "any .har file dropped into data/hars/ without needing manual commands."
    ),
    category="SYSTEM",
    tags=["google", "auth", "watchfolder", "background"],
)
def har_watchfolder_start() -> str:
    """Start the HAR watchfolder background process."""
    import subprocess
    import sys

    try:
        proc = subprocess.Popen(
            [sys.executable, "scripts/har_watchfolder.py", "watch"],
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return (
            f"HAR watchfolder started (pid={proc.pid}). "
            f"Drop any .har file into data/hars/ to auto-refresh cookies. "
            f"Log: logs/har_watchfolder.log"
        )
    except Exception as exc:
        logger.error("har_watchfolder_start failed: %s", exc)
        return f"Could not start watchfolder: {exc}"
