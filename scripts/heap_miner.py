"""
Heap Snapshot Miner  —  scripts/heap_miner.py
==============================================
Exhaustively mines V8 heap snapshots (Chrome, Chromium, Electron).
Handles NLM, Colab, GitHub Copilot, AI Studio, Google Drive, and generic
Google sessions.  Outputs per-file JSON + TXT reports and a combined summary.

Usage:
    # Mine all heaps in data/har_files/
    python scripts/heap_miner.py

    # Mine specific files
    python scripts/heap_miner.py data/har_files/Heap-NLM.heapsnapshot

    # Mine a glob
    python scripts/heap_miner.py data/har_files/*.heapsnapshot

    # Store findings in Nexus
    python scripts/heap_miner.py --nexus

    # Adjust how much of each file to read (default: 20 MB)
    python scripts/heap_miner.py --tail 40

Output:
    data/heap_output/<stem>_findings.json
    data/heap_output/<stem>_findings.txt
    data/heap_output/combined_findings.json
    data/heap_output/combined_report.txt
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(format="%(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ──── Output directory ────────────────────────────────────────────────────────
OUT_DIR = Path("data/heap_output")

# ──── Reading parameters ──────────────────────────────────────────────────────
DEFAULT_TAIL_MB = 20        # read last N MB of each file (strings are at the end)
EXPAND_TRIGGER = 5          # if fewer than this many categories found, expand by +10MB
MAX_TAIL_MB = 80            # never read more than this per file
CHUNK = 4 * 1024 * 1024     # 4 MB processing chunk
OVERLAP = 4096              # overlap between chunks to catch cross-boundary matches
CTX = 150                   # chars of context either side of each match


# ──── Pattern registry ────────────────────────────────────────────────────────
# Each entry: (category_name, regex_pattern)
# The first capture group is taken as the VALUE; if no group, full match is used.

PATTERNS: list[tuple[str, str]] = [

    # ── Google auth cookies ──────────────────────────────────────────────────
    ("SAPISID",             r'SAPISID["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("APISID",              r'(?<![_A-Z])APISID["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("__Secure-1PAPISID",   r'__Secure-1PAPISID["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("__Secure-3PAPISID",   r'__Secure-3PAPISID["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("HSID",                r'(?<![_A-Z])HSID["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("SSID",                r'(?<![_A-Z])SSID["\s:=]+([A-Za-z0-9_/+\-]{20,80})'),
    ("SID",                 r'"SID"["\s:=,]+([A-Za-z0-9_./\-]{40,250})'),
    ("SIDCC",               r'SIDCC["\s:=]+([A-Za-z0-9_/+\-]{40,250})'),
    ("__Secure-1PSID",      r'__Secure-1PSID["\s:=]+([A-Za-z0-9_./\-]{40,250})'),
    ("__Secure-3PSID",      r'__Secure-3PSID["\s:=]+([A-Za-z0-9_./\-]{40,250})'),
    ("__Secure-1PSIDCC",    r'__Secure-1PSIDCC["\s:=]+([A-Za-z0-9_/+\-]{40,250})'),
    ("__Secure-3PSIDCC",    r'__Secure-3PSIDCC["\s:=]+([A-Za-z0-9_/+\-]{40,250})'),
    ("__Secure-1PSIDTS",    r'__Secure-1PSIDTS["\s:=]+([A-Za-z0-9_/+\-=]{20,200})'),
    ("__Secure-3PSIDTS",    r'__Secure-3PSIDTS["\s:=]+([A-Za-z0-9_/+\-=]{20,200})'),
    ("AEC",                 r'(?<![A-Z])AEC["\s:=]+([A-Za-z0-9_/+\-]{20,100})'),
    ("NID",                 r'"NID"["\s:=,]+([A-Za-z0-9_/+\-=;]{20,500})'),
    ("OTZ",                 r'OTZ["\s:=]+([A-Za-z0-9_/+\-=_]{5,40})'),
    ("SEARCH_SAMESITE",     r'SEARCH_SAMESITE["\s:=]+([A-Za-z0-9_/+\-=]{5,30})'),

    # Full cookie blob (the whole cookie header string in one go)
    ("cookie_blob",         r'((?:SAPISID|APISID|SID|HSID|OTZ)=[A-Za-z0-9_./\-]{5,}(?:;\s*[A-Za-z0-9_\-]+=[A-Za-z0-9_./+\-=;, ]{5,}){5,})'),

    # ── Auth tokens ───────────────────────────────────────────────────────────
    ("at_token",            r'(AIXQIk[A-Za-z0-9_/+\-]{10,40}:\d{13})'),
    ("snlm0e_at",           r'SNlM0e["\s:,]+([A-Za-z0-9_/+\-=]{20,120})'),
    ("SAPISIDHASH",         r'(SAPISIDHASH\s+\d{10}\s+[a-f0-9]{40})'),
    ("ya29_oauth",          r'(ya29\.[A-Za-z0-9_\-\.]{30,250})'),
    ("Bearer_token",        r'Bearer\s+([A-Za-z0-9_\-\.]{30,250})'),

    # ── API keys ──────────────────────────────────────────────────────────────
    ("api_key_AIza",        r'(AIza[A-Za-z0-9_\-]{35,42})'),

    # ── JWT / access tokens ───────────────────────────────────────────────────
    ("jwt",                 r'(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})'),

    # ── NLM session state ─────────────────────────────────────────────────────
    ("nlm_fsid",            r'"f\.sid"\s*:\s*"(-?\d{15,20})"'),
    ("nlm_bl",              r'"(?:bl|KjTSIf)"\s*:\s*"(boq_[A-Za-z0-9_\-\.]{5,60})"'),
    ("nlm_at",              r'"(?:at|SNlM0e)"\s*:\s*"([A-Za-z0-9_/+\-=]{20,120})"'),
    ("nlm_gaia_id",         r'"(?:gaiaId|S06Grb|W3Yyqf)"\s*:\s*"(\d{15,25})"'),
    ("nlm_rpcid",           r'/LabsTailwindUi/data/batchexecute\?rpcids=([A-Za-z0-9]{4,8})'),
    ("nlm_rpc_path_short",  r'(/LabsTailwindOrchestrationService\.[A-Za-z]{5,50})'),
    ("nlm_rpc_path_full",   r'(/google\.internal\.labs\.tailwind\.[a-z0-9.]+/[A-Za-z]{5,60})'),
    ("nlm_notebook_id",     r'"notebookId"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'),
    ("nlm_source_id",       r'"sourceId"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'),
    ("nlm_notebook_title",  r'"notebookTitle"\s*:\s*"([^"]{3,100})"'),
    ("nlm_source_title",    r'"sourceTitle"\s*:\s*"([^"]{3,100})"'),
    ("nlm_source_type",     r'"sourceType"\s*:\s*(\d+)'),
    ("nlm_project_id",      r'"projectId"\s*:\s*"([^"]{5,80})"'),
    ("nlm_chat_session_id", r'"chatSessionId"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'),

    # ── NLM internals / quota ─────────────────────────────────────────────────
    ("nlm_quota_event",     r'(deepResearchQuotaReached\$|sourceLimitReached\$|notebookLimitReached\$|audioOverviewQuotaReached\$)'),
    ("nlm_service_method",  r'(LabsTailwindOrchestrationService\.[A-Za-z]{5,50})'),
    ("nlm_route",           r'"/(notebook|accessrequest)/:notebookId[^"]{0,80}"'),

    # ── Colab session & auth ──────────────────────────────────────────────────
    ("colab_xsrf",          r'(?:_xsrf|xsrf_token|XSRF-TOKEN)["\s:=]+([A-Za-z0-9_/+\-=]{20,100})'),
    ("colab_kernel_id",     r'"(?:kernel_id|kernelId)"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'),
    ("colab_session_id",    r'"(?:session_id|sessionId)"\s*:\s*"([A-Za-z0-9_\-]{20,80})"'),
    ("colab_runtime_id",    r'"(?:runtime_id|runtimeId|backendId)"\s*:\s*"([A-Za-z0-9_\-]{20,80})"'),
    ("colab_notebook_id",   r'"(?:fileId|colabFileId)"\s*:\s*"([A-Za-z0-9_\-]{25,50})"'),
    ("colab_api_path",      r'((?:https://)?colab\.research\.google\.com/\$rpc/[A-Za-z0-9./]{10,100})'),
    ("colab_ai_rpc",        r'(clients6\.google\.com/\$rpc/google\.internal\.colab\.v1\.[A-Za-z]{5,60})'),
    ("colab_rpc_method",    r'(AgentCreateTask|AgentUpdateTask|AgentQueryTask|ExecuteCell|GetKernelStatus|InterruptKernel|ReassignRuntime|GetRuntimeInfo|MigrateNotebook)'),
    ("colab_grpc_path",     r'(/google\.internal\.colab\.[a-z0-9.]+/[A-Za-z]{5,60})'),
    ("colab_access_token",  r'"access_token"\s*:\s*"([A-Za-z0-9_/+\-=\.]{30,250})"'),
    ("colab_refresh_token", r'"refresh_token"\s*:\s*"([A-Za-z0-9_/+\-=\.]{30,250})"'),
    ("colab_tunnel_url",    r'(https://[a-z0-9\-]+\.ngrok\.io[^\s"\']{0,80})'),
    ("colab_drive_token",   r'drive\.google\.com.*?token=([A-Za-z0-9_\-]{30,200})'),
    ("colab_ws_url",        r'(wss?://[a-z0-9\-\.]+colab[^\s"\']{0,120})'),

    # ── Google Drive ──────────────────────────────────────────────────────────
    ("drive_file_id",       r'(?:fileId|driveFileId|drive/d/)([A-Za-z0-9_\-]{25,50})'),
    ("drive_folder_id",     r'(?:folderId|folders/)([A-Za-z0-9_\-]{25,50})'),
    ("drive_share_token",   r'sharing/[^\s"\']{0,80}(\?usp=[^\s"\'<]{5,40})'),

    # ── GitHub Copilot ────────────────────────────────────────────────────────
    ("github_token",        r'(gh[pousr]_[A-Za-z0-9]{36,50})'),
    ("github_pat",          r'(github_pat_[A-Za-z0-9_]{82,90})'),
    ("copilot_token",       r'"token"\s*:\s*"(ghu_[A-Za-z0-9]{36,50})"'),
    ("copilot_endpoint",    r'(api\.individual\.githubcopilot\.com/[^\s"\'<>]{5,100})'),
    ("github_api_path",     r'(https://api\.github\.com/[^\s"\'<>]{5,100})'),

    # ── AI Studio / Gemini ────────────────────────────────────────────────────
    ("aistudio_api_key",    r'(?:gemini|aistudio)[^"]{0,40}key["\s:=]+([A-Za-z0-9_\-]{30,50})'),
    ("aistudio_model",      r'models/(gemini-[A-Za-z0-9\-\.]{3,40})'),
    ("aistudio_project",    r'"projectId"\s*:\s*"([a-z][a-z0-9\-]{4,28})"'),

    # ── Generic Google internals ──────────────────────────────────────────────
    ("gapi_path",           r'(https://[a-z\-]+\.googleapis\.com/[^\s"\'<>]{10,150})'),
    ("google_internal_rpc", r'(/google\.[a-z][a-z0-9.]{5,60}/[A-Za-z][A-Za-z0-9]{5,50})'),
    ("wiz_global_key",      r'"([A-Z][A-Za-z0-9]{4,8})"\s*:\s*"([A-Za-z0-9_\-/+]{20,150})"'),

    # ── User identity ─────────────────────────────────────────────────────────
    ("email",               r'([a-zA-Z0-9._%+\-]+@(?:gmail|google|googlemail|github|microsoft|outlook|yahoo)\.com)'),
    ("gaia_id",             r'"(?:gaiaId|GAIA_ID|obfuscatedGaiaId)"\s*:\s*"(\d{10,25})"'),
    ("profile_photo",       r'lh3\.googleusercontent\.com/a/([A-Za-z0-9_\-]{20,80})'),
    ("display_name",        r'"displayName"\s*:\s*"([^"]{3,80})"'),
    ("x_goog_authuser",     r'X-Goog-AuthUser["\s:=]+(\d)'),

    # ── OAuth ─────────────────────────────────────────────────────────────────
    ("oauth_client_id",     r'(\d{10,12}-[a-z0-9]{32}\.apps\.googleusercontent\.com)'),

    # ── Generic UUID ─────────────────────────────────────────────────────────
    ("uuid",                r'["\']([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})["\']'),

    # ── Private keys (high alert) ─────────────────────────────────────────────
    ("private_key",         r'-----BEGIN [A-Z ]+PRIVATE KEY-----'),
    ("cert_pem",            r'-----BEGIN CERTIFICATE-----'),
]

# Human-readable priority order for reports
PRIORITY_ORDER = [
    # cookies first (most actionable)
    "cookie_blob", "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "APISID",
    "SID", "HSID", "SSID", "SIDCC", "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC", "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "AEC", "NID", "OTZ", "SEARCH_SAMESITE",
    # auth tokens
    "at_token", "snlm0e_at", "SAPISIDHASH", "ya29_oauth", "Bearer_token",
    "api_key_AIza", "jwt",
    # NLM specific
    "nlm_fsid", "nlm_bl", "nlm_at", "nlm_gaia_id",
    "nlm_rpcid", "nlm_notebook_id", "nlm_source_id", "nlm_chat_session_id",
    "nlm_notebook_title", "nlm_source_title", "nlm_project_id", "nlm_source_type",
    "nlm_service_method", "nlm_rpc_path_short", "nlm_rpc_path_full", "nlm_route",
    "nlm_quota_event",
    # Colab specific
    "colab_xsrf", "colab_access_token", "colab_refresh_token",
    "colab_kernel_id", "colab_session_id", "colab_runtime_id", "colab_notebook_id",
    "colab_ai_rpc", "colab_rpc_method", "colab_grpc_path", "colab_api_path",
    "colab_tunnel_url", "colab_ws_url", "colab_drive_token",
    # Drive
    "drive_file_id", "drive_folder_id", "drive_share_token",
    # GitHub
    "github_token", "github_pat", "copilot_token", "copilot_endpoint", "github_api_path",
    # AI Studio
    "aistudio_api_key", "aistudio_model", "aistudio_project",
    # Identity
    "email", "gaia_id", "nlm_gaia_id", "profile_photo", "display_name", "oauth_client_id",
    # Internal paths
    "gapi_path", "google_internal_rpc", "wiz_global_key",
    # Generic
    "uuid", "x_goog_authuser",
    # Danger
    "private_key", "cert_pem",
]

# Categories that are likely noise when very numerous — limit display
NOISE_CATS = {"uuid", "wiz_global_key", "gapi_path", "google_internal_rpc"}
NOISE_LIMIT = 15


# ──── Core miner ──────────────────────────────────────────────────────────────

def _compile() -> list[tuple[str, re.Pattern]]:
    compiled = []
    seen_names: dict[str, int] = defaultdict(int)
    for name, pat in PATTERNS:
        try:
            compiled.append((name, re.compile(pat, re.IGNORECASE | re.DOTALL)))
        except re.error as exc:
            log.warning("Bad pattern [%s]: %s", name, exc)
        seen_names[name] += 1
    return compiled


def mine_file(
    path: Path,
    tail_mb: int = DEFAULT_TAIL_MB,
) -> dict[str, list[dict]]:
    """Mine a single heap snapshot.  Returns findings dict."""

    compiled = _compile()
    findings: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set] = defaultdict(set)

    total = path.stat().st_size
    tail_bytes = min(tail_mb * 1024 * 1024, total)

    log.info("")
    log.info("═" * 70)
    log.info("  MINING: %s  (%.1f MB file,  reading last %.0f MB)", path.name, total / 1e6, tail_bytes / 1e6)
    log.info("═" * 70)

    def _process_tail(tail_bytes_to_read: int) -> None:
        nonlocal findings, seen

        offset = max(0, total - tail_bytes_to_read)
        findings = defaultdict(list)
        seen = defaultdict(set)

        processed = 0
        prev_tail = b""

        with open(path, "rb") as fh:
            fh.seek(offset)
            while True:
                raw = fh.read(CHUNK)
                if not raw:
                    break
                chunk_bytes = prev_tail + raw
                prev_tail = raw[-OVERLAP:]
                processed += len(raw)

                chunk = chunk_bytes.decode("utf-8", errors="replace")

                for name, rx in compiled:
                    for m in rx.finditer(chunk):
                        value = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                        value = value.strip().replace("\x00", "")
                        if not value or len(value) < 4 or value in seen[name]:
                            continue
                        seen[name].add(value)
                        start = max(0, m.start() - CTX)
                        end = min(len(chunk), m.end() + CTX)
                        ctx = chunk[start:end].replace("\x00", "").strip()
                        findings[name].append({"value": value, "context": ctx[:400]})

                pct = (offset + processed) / total * 100
                n = sum(len(v) for v in findings.values())
                print(f"\r  {pct:5.1f}%   {processed / 1e6:6.1f} / {tail_bytes_to_read / 1e6:.1f} MB   "
                      f"findings: {n}   cats: {len(findings)}    ",
                      end="", flush=True)

        print()

    # First pass
    _process_tail(tail_bytes)
    n_cats = len(findings)
    n_total = sum(len(v) for v in findings.values())
    log.info("  Pass 1: %d findings across %d categories", n_total, n_cats)

    # If we found very little, expand the window
    current_tail = tail_bytes
    while n_cats < EXPAND_TRIGGER and current_tail < total:
        current_tail = min(current_tail + 10 * 1024 * 1024, total)
        log.info("  Expanding window to %.0f MB ...", current_tail / 1e6)
        _process_tail(current_tail)
        n_cats = len(findings)
        n_total = sum(len(v) for v in findings.values())
        log.info("  Expanded: %d findings, %d categories", n_total, n_cats)

    return dict(findings)


# ──── Auto-detect heap source ─────────────────────────────────────────────────

def detect_source(findings: dict[str, list[dict]]) -> str:
    """Guess what service this heap came from."""
    has = lambda cat: bool(findings.get(cat))

    if has("nlm_fsid") or has("nlm_notebook_id") or has("nlm_service_method"):
        return "NotebookLM"
    if has("colab_kernel_id") or has("colab_xsrf") or has("colab_rpc_method") or has("colab_grpc_path"):
        return "Google Colab"
    if has("copilot_token") or has("copilot_endpoint"):
        return "GitHub Copilot"
    if has("aistudio_model") or has("aistudio_api_key"):
        return "Google AI Studio"
    if has("email") or has("SAPISID") or has("api_key_AIza"):
        return "Google (generic)"
    return "Unknown"


# ──── Report writer ────────────────────────────────────────────────────────────

def _section(lines: list[str], cat: str, items: list[dict], limit: int = 30) -> None:
    n = len(items)
    lines.append(f"\n{'─' * 70}")
    lines.append(f"  [{cat}]   {n} unique values")
    lines.append("─" * 70)
    capped = items[:limit]
    for item in capped:
        v = item["value"]
        lines.append(f"  VALUE: {v}")
        ctx = item.get("context", "")
        if ctx and ctx.strip() != v:
            # Truncate long context
            ctx_short = ctx[:250].replace("\n", " ").strip()
            lines.append(f"  CTX:   {ctx_short}")
        lines.append("")
    if n > limit:
        lines.append(f"  ... {n - limit} more values in JSON ...")
        lines.append("")


def write_report(
    findings: dict[str, list[dict]],
    source_file: Path,
    source_type: str,
    out_json: Path,
    out_txt: Path,
) -> None:
    """Write JSON + TXT reports for a single file's findings."""
    out_json.parent.mkdir(parents=True, exist_ok=True)

    # JSON
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)

    # TXT
    total = sum(len(v) for v in findings.values())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        "=" * 70,
        "  HEAP SNAPSHOT MINING REPORT",
        f"  Source:  {source_file.name}  ({source_file.stat().st_size / 1e6:.1f} MB)",
        f"  Type:    {source_type}",
        f"  Mined:   {now}",
        f"  Total:   {total} unique findings across {len(findings)} categories",
        "=" * 70,
    ]

    shown: set[str] = set()
    order = PRIORITY_ORDER + [k for k in findings if k not in PRIORITY_ORDER]

    for cat in order:
        if cat not in findings or cat in shown:
            continue
        shown.add(cat)
        items = findings[cat]
        if not items:
            continue
        limit = NOISE_LIMIT if cat in NOISE_CATS else 30
        _section(lines, cat, items, limit)

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info("  JSON → %s", out_json)
    log.info("  TXT  → %s", out_txt)


def write_combined_report(
    all_findings: dict[str, dict[str, list[dict]]],  # filename → findings
    out_json: Path,
    out_txt: Path,
) -> None:
    """Deduplicate across all files and write a combined report."""
    # Merge: category → set of unique values (keep first context seen)
    merged: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set] = defaultdict(set)

    for fname, findings in all_findings.items():
        for cat, items in findings.items():
            for item in items:
                v = item["value"]
                if v not in seen[cat]:
                    seen[cat].add(v)
                    merged[cat].append({**item, "_source": fname})

    merged_dict = dict(merged)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(merged_dict, f, indent=2, ensure_ascii=False)

    total = sum(len(v) for v in merged_dict.values())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        "=" * 70,
        "  COMBINED HEAP MINING REPORT",
        f"  Files:   {len(all_findings)}",
        f"  Mined:   {now}",
        f"  Total:   {total} unique findings across {len(merged_dict)} categories",
        "=" * 70,
        "",
        "  FILES:",
    ]
    for fname in all_findings:
        n = sum(len(v) for v in all_findings[fname].values())
        lines.append(f"    {fname}  →  {n} findings")
    lines.append("")

    shown: set[str] = set()
    order = PRIORITY_ORDER + [k for k in merged_dict if k not in PRIORITY_ORDER]

    for cat in order:
        if cat not in merged_dict or cat in shown:
            continue
        shown.add(cat)
        items = merged_dict[cat]
        if not items:
            continue
        limit = NOISE_LIMIT if cat in NOISE_CATS else 30
        _section(lines, cat, items, limit)

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info("")
    log.info("═" * 70)
    log.info("  COMBINED → %s", out_json)
    log.info("  COMBINED → %s", out_txt)


# ──── Nexus storage ────────────────────────────────────────────────────────────

def store_in_nexus(
    all_findings: dict[str, dict[str, list[dict]]],
    source_type: str,
) -> None:
    try:
        from engine.nexus.client import get_nexus_client  # noqa
        client = get_nexus_client()
    except Exception as exc:
        log.warning("Nexus unavailable (%s) — skipping storage", exc)
        return

    for fname, findings in all_findings.items():
        # Store actionable tokens and paths as a Nexus entry
        summary_lines = [f"## Heap Mining: {fname}", f"Source type: {source_type}", ""]

        high_value = [
            "SAPISID", "cookie_blob", "at_token", "snlm0e_at", "SAPISIDHASH",
            "nlm_fsid", "nlm_bl", "nlm_rpcid", "nlm_service_method",
            "nlm_rpc_path_short", "nlm_rpc_path_full",
            "colab_xsrf", "colab_kernel_id", "colab_rpc_method", "colab_grpc_path",
            "colab_ai_rpc", "colab_access_token", "colab_tunnel_url",
            "api_key_AIza", "ya29_oauth", "oauth_client_id",
            "github_token", "copilot_token", "copilot_endpoint",
            "email", "gaia_id",
        ]
        for cat in high_value:
            items = findings.get(cat, [])
            if items:
                summary_lines.append(f"### {cat} ({len(items)} values)")
                for it in items[:5]:
                    summary_lines.append(f"  - `{it['value']}`")
                summary_lines.append("")

        content = "\n".join(summary_lines)
        try:
            client.add_entry(
                title=f"Heap Mining: {fname}",
                content=content,
                content_type="document",
                category="debugging",
                tags=["heap", "tokens", "auth", source_type.lower().replace(" ", "_")],
            )
            log.info("  Stored in Nexus: %s", fname)
        except Exception as exc:
            log.warning("  Nexus store failed: %s", exc)


# ──── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine V8 heap snapshots for auth tokens, API secrets, and session data.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Heap snapshot files to mine.  Defaults to data/har_files/*.heapsnapshot",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=DEFAULT_TAIL_MB,
        metavar="MB",
        help=f"MB from end of file to read (default {DEFAULT_TAIL_MB}).  "
             "Increase for very large heaps.",
    )
    parser.add_argument(
        "--nexus",
        action="store_true",
        help="Store high-value findings in Nexus after mining.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR,
        metavar="DIR",
        help=f"Output directory (default: {OUT_DIR})",
    )
    args = parser.parse_args()

    # Resolve input files
    if args.files:
        paths = [Path(p) for p in args.files]
    else:
        paths = sorted(Path("data/har_files").glob("*.heapsnapshot"))
        if not paths:
            log.error("No .heapsnapshot files found in data/har_files/")
            sys.exit(1)

    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            log.error("File not found: %s", p)
        sys.exit(1)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    all_findings: dict[str, dict[str, list[dict]]] = {}

    for path in paths:
        findings = mine_file(path, tail_mb=args.tail)
        source_type = detect_source(findings)
        log.info("  Detected source: %s", source_type)

        stem = path.stem
        out_json = out_dir / f"{stem}_findings.json"
        out_txt = out_dir / f"{stem}_findings.txt"
        write_report(findings, path, source_type, out_json, out_txt)

        all_findings[path.name] = findings

        # Quick summary
        log.info("  ── Top categories ──")
        sorted_cats = sorted(findings.items(), key=lambda x: -len(x[1]))
        for cat, items in sorted_cats[:15]:
            sample = items[0]["value"][:70] if items else ""
            log.info("    %-28s %3d   e.g. %s", cat, len(items), sample)

    # Combined report
    if len(all_findings) > 1:
        write_combined_report(
            all_findings,
            out_dir / "combined_findings.json",
            out_dir / "combined_report.txt",
        )

    # Nexus storage
    if args.nexus:
        for fname, findings in all_findings.items():
            source_type = detect_source(findings)
            store_in_nexus({fname: findings}, source_type)

    log.info("")
    log.info("Done.  Output in: %s", out_dir)


if __name__ == "__main__":
    main()
