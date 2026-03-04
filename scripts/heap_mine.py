"""
Exhaustive V8 Heap Snapshot Miner.

Extracts EVERYTHING of value from a Chrome heap snapshot:
  - All cookies (any domain)
  - Auth tokens (at_token, Bearer, OAuth)
  - API keys (AIza*, gapi_key)
  - JWT tokens (eyJ*)
  - Notebook / source UUIDs
  - Email addresses / user IDs
  - NLM session values (f.sid, bl, X-Goog-*)
  - Internal API endpoints & paths
  - XSRF / CSRF tokens
  - Any base64-encoded credential blobs

Run:
    python scripts/heap_mine.py
Output:
    data/heap_findings.json   — structured JSON
    data/heap_findings.txt    — human-readable report
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HEAP_PATH = Path("data/har_files/Heap-20260305T014003.heapsnapshot")
OUT_JSON = Path("data/heap_findings.json")
OUT_TXT = Path("data/heap_findings.txt")
CHUNK = 4 * 1024 * 1024   # 4 MB chunks with 2 KB overlap
OVERLAP = 2048

# ──── Pattern registry ────────────────────────────────────────────────────────
PATTERNS: list[tuple[str, str]] = [
    # Google auth cookies
    ("SAPISID",        r'SAPISID["\s:=]+([A-Za-z0-9_/+\-]{20,60})'),
    ("APISID",         r'APISID["\s:=]+([A-Za-z0-9_/+\-]{20,60})'),
    ("__Secure-1PAPISID", r'__Secure-1PAPISID["\s:=]+([A-Za-z0-9_/+\-]{20,60})'),
    ("__Secure-3PAPISID", r'__Secure-3PAPISID["\s:=]+([A-Za-z0-9_/+\-]{20,60})'),
    ("SID",            r'"SID"["\s:=,]+([A-Za-z0-9_./\-]{40,200})'),
    ("HSID",           r'HSID["\s:=]+([A-Za-z0-9_/+\-]{20,60})'),
    ("SSID",           r'SSID["\s:=]+([A-Za-z0-9_/+\-]{20,60})'),
    ("SIDCC",          r'SIDCC["\s:=]+([A-Za-z0-9_/+\-]{40,200})'),
    ("__Secure-1PSID", r'__Secure-1PSID["\s:=]+([A-Za-z0-9_./\-]{40,200})'),
    ("__Secure-3PSID", r'__Secure-3PSID["\s:=]+([A-Za-z0-9_./\-]{40,200})'),
    ("__Secure-1PSIDCC", r'__Secure-1PSIDCC["\s:=]+([A-Za-z0-9_/+\-]{40,200})'),
    ("__Secure-3PSIDCC", r'__Secure-3PSIDCC["\s:=]+([A-Za-z0-9_/+\-]{40,200})'),
    ("AEC",            r'AEC["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("NID",            r'"NID"["\s:=,]+([A-Za-z0-9_/+\-=;]{20,400})'),
    # at_token (NLM direct API)
    ("at_token",       r'(AIXQIk[A-Za-z0-9_/+\-]{10,30}:\d{13})'),
    # API keys
    ("api_key_AIza",   r'(AIza[A-Za-z0-9_\-]{35,40})'),
    # OAuth / access tokens
    ("ya29_oauth",     r'(ya29\.[A-Za-z0-9_\-\.]{30,200})'),
    ("Bearer_token",   r'Bearer\s+([A-Za-z0-9_\-\.]{30,200})'),
    # JWT tokens
    ("jwt",            r'(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})'),
    # NLM f.sid  (session id for direct API)
    ("nlm_fsid",       r'"f\.sid"\s*:\s*"(-?\d{15,20})"'),
    ("nlm_bl",         r'"bl"\s*:\s*"([a-zA-Z0-9_\-]{5,30})"'),
    ("nlm_at",         r'"at"\s*:\s*"([A-Za-z0-9_/+\-=]{20,80})"'),
    # XSRF / CSRF
    ("xsrf_token",     r'(?:xsrf|csrf)[_\-]?token["\s:=]+([A-Za-z0-9_/+\-=]{20,100})'),
    ("SNlM0e",         r'(SNlM0e).*?:\s*"([A-Za-z0-9_/+\-=]{20,100})"'),
    # Google user / account info
    ("email",          r'([a-zA-Z0-9._%+\-]+@(?:gmail|google|googlemail)\.com)'),
    ("gaia_id",        r'"gaiaId"\s*:\s*"(\d{15,25})"'),
    ("user_id",        r'"userId"\s*:\s*"(\d{15,25})"'),
    ("obfuscated_id",  r'"obfuscatedGaiaId"\s*:\s*"([A-Za-z0-9_\-]{10,40})"'),
    # Notebook / source UUIDs  (real user notebooks have 8-4-4-4-12 format)
    ("uuid_notebook",  r'"notebookId"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'),
    ("uuid_source",    r'"sourceId"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'),
    ("uuid_generic",   r'["\']([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})["\']'),
    # Internal Google API paths
    ("nlm_rpc_path",   r'(/_/LabsTailwindUi/data/batchexecute[^\s"\']{0,80})'),
    ("gapi_path",      r'(https://[a-z\-]+\.googleapis\.com/[^\s"\'<>]{10,120})'),
    ("colab_path",     r'(https://colab\.research\.google\.com[^\s"\'<>]{10,120})'),
    # X-Goog headers
    ("x_goog_authuser", r'X-Goog-AuthUser["\s:=]+(\d)'),
    ("x_goog_apikey",  r'X-Goog-Api-Key["\s:=]+([A-Za-z0-9_\-]{20,50})'),
    # NotebookLM specific keys
    ("notebook_title", r'"notebookTitle"\s*:\s*"([^"]{3,80})"'),
    ("source_title",   r'"sourceTitle"\s*:\s*"([^"]{3,80})"'),
    ("display_name",   r'"displayName"\s*:\s*"([^"]{3,60})"'),
    # Google Workspace org ID
    ("hd_domain",      r'"hd"\s*:\s*"([a-z0-9\.\-]+\.[a-z]{2,6})"'),
    # GitHub tokens (in case Chrome has GitHub open)
    ("github_token",   r'(gh[pousr]_[A-Za-z0-9]{36,40})'),
    ("github_pat",     r'(github_pat_[A-Za-z0-9_]{82})'),
    # Colab credentials
    ("colab_token",    r'"token"\s*:\s*"([A-Za-z0-9_\-]{30,200})"'),
    # Drive file IDs
    ("drive_file_id",  r'(?:fileId|driveFileId)["\s:=]+([A-Za-z0-9_\-]{25,50})'),
    # SAPISIDHASH (used in auth header)
    ("sapisidhash",    r'(SAPISIDHASH\s+\d{10}\s+[a-f0-9]{40})'),
    # OAUTH2 client IDs
    ("oauth_client_id", r'(\d{10,12}-[a-z0-9]{32}\.apps\.googleusercontent\.com)'),
    # Private key patterns
    ("private_key",    r'-----BEGIN [A-Z ]+PRIVATE KEY-----'),
]

# Context window around match (chars each side)
CTX = 120


def mine_heap(path: Path) -> dict[str, list[dict]]:
    findings: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set] = defaultdict(set)
    compiled = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in PATTERNS]

    total_bytes = path.stat().st_size
    processed = 0
    prev_tail = b""

    print(f"Mining {path.name} ({total_bytes / 1e6:.1f} MB)...")

    with open(path, "rb") as fh:
        while True:
            raw = fh.read(CHUNK)
            if not raw:
                break
            # Stitch overlap to catch matches that cross chunk boundaries
            chunk_bytes = prev_tail + raw
            prev_tail = raw[-OVERLAP:]
            processed += len(raw)

            # Decode — ignore errors for binary noise
            chunk = chunk_bytes.decode("utf-8", errors="replace")

            for name, rx in compiled:
                for m in rx.finditer(chunk):
                    # Use first capture group value if exists, else full match
                    value = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                    value = value.strip()
                    if not value or value in seen[name]:
                        continue
                    if len(value) < 4:
                        continue
                    seen[name].add(value)

                    start = max(0, m.start() - CTX)
                    end = min(len(chunk), m.end() + CTX)
                    context = chunk[start:end].replace("\x00", "").strip()
                    # Trim long contexts
                    if len(context) > 300:
                        context = context[:150] + " … " + context[-150:]

                    findings[name].append({"value": value, "context": context})

            pct = processed / total_bytes * 100
            print(f"\r  {pct:.0f}%  ({processed / 1e6:.1f} MB)  findings: {sum(len(v) for v in findings.values())}    ", end="", flush=True)

    print()
    return dict(findings)


def write_report(findings: dict[str, list[dict]], txt_path: Path, json_path: Path) -> None:
    total = sum(len(v) for v in findings.items())

    # JSON
    json_path.parent.mkdir(exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)

    # Human-readable
    lines = [
        "=" * 80,
        "HEAP SNAPSHOT MINING REPORT",
        f"Source: {HEAP_PATH}",
        f"Total unique findings: {sum(len(v) for v in findings.values())}",
        "=" * 80,
        "",
    ]

    # Priority order for display
    priority = [
        "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "APISID",
        "SID", "HSID", "SSID", "SIDCC", "__Secure-1PSID", "__Secure-3PSID",
        "__Secure-1PSIDCC", "__Secure-3PSIDCC", "AEC", "NID",
        "at_token", "api_key_AIza", "ya29_oauth", "Bearer_token", "jwt",
        "nlm_fsid", "nlm_bl", "nlm_at", "xsrf_token", "SNlM0e",
        "email", "gaia_id", "user_id", "obfuscated_id",
        "uuid_notebook", "uuid_source",
        "notebook_title", "source_title", "display_name",
        "sapisidhash", "oauth_client_id",
        "github_token", "github_pat",
        "colab_token", "drive_file_id",
        "gapi_path", "nlm_rpc_path", "colab_path",
        "x_goog_authuser", "x_goog_apikey", "hd_domain",
        "uuid_generic", "private_key",
    ]

    # Show priority categories first, then any extras
    shown = set()
    order = priority + [k for k in findings if k not in priority]

    for cat in order:
        if cat not in findings or cat in shown:
            continue
        shown.add(cat)
        items = findings[cat]
        lines.append(f"\n{'─' * 60}")
        lines.append(f"[{cat}]  ({len(items)} unique values)")
        lines.append("─" * 60)
        for item in items[:30]:  # cap at 30 per category
            lines.append(f"  VALUE: {item['value']}")
            ctx = item['context']
            if ctx and ctx.strip() != item['value']:
                lines.append(f"  CTX:   {ctx[:200]}")
            lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nJSON: {json_path}")
    print(f"TXT:  {txt_path}")


def summarise(findings: dict[str, list[dict]]) -> None:
    """Print a short summary to stdout."""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for cat, items in sorted(findings.items(), key=lambda x: -len(x[1])):
        if items:
            sample = items[0]["value"][:80]
            print(f"  {cat:25s}  {len(items):3d}  e.g. {sample}")


if __name__ == "__main__":
    if not HEAP_PATH.exists():
        print(f"ERROR: heap not found: {HEAP_PATH}")
        sys.exit(1)

    findings = mine_heap(HEAP_PATH)
    write_report(findings, OUT_TXT, OUT_JSON)
    summarise(findings)
    print("\nDone.")
