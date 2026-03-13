"""v1.21 HAR Deep Extraction — processes all HAR files and extracts rpcids, endpoints, gRPC methods."""
import json
import os
import re
import sys
import urllib.parse
from collections import defaultdict


HAR_DIR = os.path.join("data", "har_files", "users_dump_folder")

HAR_FILES = [
    # NLM files (smallest first — most relevant for missing rpcids)
    "notebooklm_knack112358-latest.har",        # 9 MB — PRO account
    "notebooklm.google.com-FRESH.har",           # 12 MB — pre-rollout
    "notebooklm.google.com-jackpot-nihilistcod.har",  # 16 MB — FREE account
    "quicktest.har",                              # 10 MB — mixed
    # Drive / Docs / Sheets
    "drive.google.com.har",                       # 7 MB
    "docs.-google.com-sheets-gemini2.har",        # 30 MB — Workspace Gemini!
    # Apps Script
    "script.google.com.har",                      # 39 MB
    # AI Studio
    "aistudio.google.com-clean.har",              # 39 MB — FREE
    "aistudio.google.com-gemini-app-2.har",       # 95 MB — Gemini App v2
    "aistudio.google.com-nihilistcod.har",        # 91 MB — FREE
    "aistudio.google.com-capped-apprunning.har",  # 184 MB — capped/running app
    # Colab
    "colab.research.google.com-goldmine-nihilistcod.har",  # 56 MB — FREE
    # GitHub (huge, separate service — process last)
    "github.com-Extra-long-nihilistcod.har",      # 285 MB — GitHub APIs
]

# Account tier mapping for payload comparison
ACCOUNT_TIERS = {
    "nihilistcod": "free",
    "knack112358": "pro",
}

SKIP_PATH_FRAGMENTS = [
    "/log", "/gen204", "/collect", "/jserror", "/cspreport",
    "/$ct", "/mss/", "/.well-known", "/youtubei/", "/play.google.com",
    "/safebrowsing", "/gstatic.com", "/_/chrome", "/fonts.googleapis.com",
]


def extract_rpcids_from_body(post_data: str) -> list[str]:
    """Extract rpcids from batchexecute f.req payload."""
    decoded = urllib.parse.unquote(post_data)
    matches = re.findall(r'\["([A-Za-z0-9_]{3,12})"', decoded)
    # Filter out common false positives
    valid = []
    for m in matches:
        if len(m) >= 4 and not m.startswith("http"):
            valid.append(m)
        elif m in ("DYBcR",):  # known short rpcids
            valid.append(m)
    return valid


def get_post_body(req: dict) -> str:
    """Extract POST body from HAR request."""
    pd = req.get("postData", {})
    if pd.get("text"):
        return pd["text"]
    if pd.get("params"):
        for p in pd["params"]:
            if p.get("name") == "f.req":
                return p.get("value", "")
    return ""


def extract_payload_structure(body: str, rpcid: str) -> dict | None:
    """Try to extract the payload structure for a specific rpcid from batchexecute body."""
    decoded = urllib.parse.unquote(body)
    # Find the rpcid's payload block
    pattern = rf'\["{re.escape(rpcid)}","([^"]*)",(".*?"|null),(".*?"|null)'
    match = re.search(pattern, decoded)
    if match:
        inner_payload = match.group(1)
        try:
            parsed = json.loads(inner_payload)
            return {"structure": type(parsed).__name__, "depth": _depth(parsed), "size": len(inner_payload)}
        except (json.JSONDecodeError, TypeError):
            return {"raw_length": len(inner_payload)}
    return None


def _depth(obj, current=0):
    """Get nesting depth of a structure."""
    if isinstance(obj, list) and obj:
        return max(_depth(item, current + 1) for item in obj)
    if isinstance(obj, dict) and obj:
        return max(_depth(v, current + 1) for v in obj.values())
    return current


def process_har(filepath: str, results: dict) -> int:
    """Process a single HAR file. Returns entry count."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)
    except Exception as e:
        print(f"  ERROR loading: {e}")
        return 0

    entries = har.get("log", {}).get("entries", [])
    fname = os.path.basename(filepath)

    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "")
        status = resp.get("status", 0)

        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path

        # gRPC methods
        if "$rpc/google.internal" in url:
            parts = url.split("$rpc/")
            if len(parts) > 1:
                rpc_path = parts[1].split("?")[0]
                results["grpc"][rpc_path]["count"] += 1
                results["grpc"][rpc_path]["hosts"].add(host)
                results["grpc"][rpc_path]["sources"].add(fname)
                results["grpc"][rpc_path]["statuses"].add(status)
                # Get response size
                resp_size = resp.get("bodySize", 0)
                if resp_size > 0:
                    results["grpc"][rpc_path]["resp_sizes"].append(resp_size)

        # batchexecute rpcids
        if "batchexecute" in url:
            body = get_post_body(req)
            if body:
                rpcids = extract_rpcids_from_body(body)
                for rid in rpcids:
                    results["rpcids"][rid]["count"] += 1
                    results["rpcids"][rid]["hosts"].add(host)
                    results["rpcids"][rid]["sources"].add(fname)
                    results["rpcids"][rid]["statuses"].add(status)
                    # Payload info
                    ps = extract_payload_structure(body, rid)
                    if ps:
                        results["rpcids"][rid]["payload_info"] = ps
                    results["rpcids"][rid]["payload_sizes"].append(len(body))

                    # Also extract batch URL params for context
                    qs = urllib.parse.parse_qs(parsed.query)
                    if "source-path" in qs:
                        results["rpcids"][rid]["source_paths"].update(qs["source-path"])

        # REST/API endpoints (POST, PUT, PATCH, DELETE)
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            if any(h in host for h in [
                "clients6.google.com", "googleapis.com", "google.com",
                "content-sheets.googleapis.com", "content-docs.googleapis.com",
            ]):
                if not any(skip in path for skip in SKIP_PATH_FRAGMENTS):
                    key = f"{host}{path}"
                    results["rest"][key]["count"] += 1
                    results["rest"][key]["methods"].add(method)
                    results["rest"][key]["sources"].add(fname)
                    results["rest"][key]["statuses"].add(status)
                    # Content type
                    for h in req.get("headers", []):
                        if h.get("name", "").lower() == "content-type":
                            results["rest"][key]["content_types"].add(h["value"].split(";")[0].strip())

        # Auth tokens — extract from headers
        for h in req.get("headers", []):
            hname = h.get("name", "").lower()
            if hname == "authorization":
                val = h.get("value", "")
                if val.startswith("Bearer "):
                    results["auth"]["bearer_tokens"].add(val[:30] + "...")
                elif "SAPISIDHASH" in val:
                    results["auth"]["sapisidhash_seen"] += 1
            if hname == "x-goog-api-key":
                results["auth"]["api_keys"].add(h["value"])

        # Query params — extract API keys
        qs = urllib.parse.parse_qs(parsed.query)
        if "key" in qs:
            for k in qs["key"]:
                if k.startswith("AIza"):
                    results["auth"]["api_keys"].add(k)

    return len(entries)


def main():
    results = {
        "rpcids": defaultdict(lambda: {
            "count": 0, "hosts": set(), "sources": set(),
            "statuses": set(), "payload_sizes": [], "payload_info": None,
            "source_paths": set(),
        }),
        "grpc": defaultdict(lambda: {
            "count": 0, "hosts": set(), "sources": set(),
            "statuses": set(), "resp_sizes": [],
        }),
        "rest": defaultdict(lambda: {
            "count": 0, "methods": set(), "sources": set(),
            "statuses": set(), "content_types": set(),
        }),
        "auth": {
            "bearer_tokens": set(),
            "sapisidhash_seen": 0,
            "api_keys": set(),
        },
    }

    total_entries = 0

    # Process files in order of size (smallest first)
    for fname in HAR_FILES:
        fpath = os.path.join(HAR_DIR, fname)
        if not os.path.isfile(fpath):
            print(f"SKIP: {fname} not found")
            continue

        fsize = os.path.getsize(fpath) / (1024 * 1024)
        print(f"Processing {fname} ({fsize:.1f} MB)...")
        count = process_har(fpath, results)
        total_entries += count
        print(f"  {count} entries processed")

    # Report
    print(f"\n{'='*70}")
    print(f"TOTAL: {total_entries} entries across {len(HAR_FILES)} files")
    print(f"{'='*70}")

    print(f"\n=== UNIQUE RPCIDS ({len(results['rpcids'])}) ===")
    for rid in sorted(results["rpcids"].keys()):
        info = results["rpcids"][rid]
        avg = sum(info["payload_sizes"]) / len(info["payload_sizes"]) if info["payload_sizes"] else 0
        hosts = ", ".join(sorted(info["hosts"]))
        sources = ", ".join(sorted(info["sources"]))
        sp = ", ".join(sorted(info["source_paths"])) if info["source_paths"] else ""
        print(f"  {rid}: count={info['count']}, hosts=[{hosts}], sources=[{sources}]")
        if sp:
            print(f"    source_paths: {sp}")

    print(f"\n=== gRPC METHODS ({len(results['grpc'])}) ===")
    for path in sorted(results["grpc"].keys()):
        info = results["grpc"][path]
        hosts = ", ".join(sorted(info["hosts"]))
        sources = ", ".join(sorted(info["sources"]))
        print(f"  {path}: count={info['count']}, hosts=[{hosts}], sources=[{sources}]")

    print(f"\n=== REST ENDPOINTS (top 80 by count) ===")
    sorted_eps = sorted(results["rest"].items(), key=lambda x: -x[1]["count"])
    for key, info in sorted_eps[:80]:
        methods = ", ".join(sorted(info["methods"]))
        sources = ", ".join(sorted(info["sources"]))
        ct = ", ".join(sorted(info["content_types"])) if info["content_types"] else ""
        print(f"  [{methods}] {key}: count={info['count']}, sources=[{sources}]")
        if ct:
            print(f"    content_type: {ct}")

    print(f"\n=== AUTH SUMMARY ===")
    print(f"  Unique bearer tokens: {len(results['auth']['bearer_tokens'])}")
    print(f"  SAPISIDHASH occurrences: {results['auth']['sapisidhash_seen']}")
    print(f"  API keys: {len(results['auth']['api_keys'])}")
    for k in sorted(results["auth"]["api_keys"]):
        print(f"    {k}")

    # Save machine-readable results
    out = {
        "rpcids": {k: {"count": v["count"], "hosts": sorted(v["hosts"]), "sources": sorted(v["sources"])}
                   for k, v in results["rpcids"].items()},
        "grpc": {k: {"count": v["count"], "hosts": sorted(v["hosts"]), "sources": sorted(v["sources"])}
                 for k, v in results["grpc"].items()},
        "rest_top": {k: {"count": v["count"], "methods": sorted(v["methods"]), "sources": sorted(v["sources"]),
                         "content_types": sorted(v["content_types"])}
                     for k, v in sorted_eps[:120]},
        "api_keys": sorted(results["auth"]["api_keys"]),
    }
    outpath = os.path.join("data", "heap_output", "v121_har_extraction.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved machine-readable results to {outpath}")


if __name__ == "__main__":
    main()
