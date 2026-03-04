"""
nlm_protocol_mapper.py — Complete NLM API reverse-engineering from HAR files.

Extracts:
  - All batchexecute rpcids with decoded request/response structures
  - GenerateFreeFormStreamed protocol details
  - Query parameters, headers, session tokens
  - Full source/notebook/artifact UUID maps
  - Cookie state at time of each call
"""

import json
import re
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any


# ── Helpers ──────────────────────────────────────────────────────────────────

def decode_freq(body: str) -> Any:
    """Extract and parse the f.req parameter from a form-encoded POST body."""
    if "f.req=" not in body:
        return body
    raw = body.split("f.req=")[1].split("&")[0]
    decoded = urllib.parse.unquote(raw)
    try:
        return json.loads(decoded)
    except Exception:
        return decoded


def parse_wrb_response(text: str) -> list[dict]:
    """Parse the chunked wrb.fr streaming response format."""
    results = []
    # Strip security prefix
    clean = text
    if clean.startswith(")]}'"):
        clean = clean[4:].lstrip("\n")
    # Split on chunk boundaries (decimal length on its own line)
    chunks = re.split(r"\n\d+\n", clean)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            arr = json.loads(chunk)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, list) and len(item) >= 2 and item[0] == "wrb.fr":
                        rpcid = item[1] if len(item) > 1 else None
                        data_raw = item[2] if len(item) > 2 else None
                        data = None
                        if isinstance(data_raw, str):
                            try:
                                data = json.loads(data_raw)
                            except Exception:
                                data = data_raw
                        results.append({"rpcid": rpcid, "data": data})
        except Exception:
            pass
    return results


def extract_uuids(obj: Any) -> list[str]:
    """Recursively extract all UUID strings from a nested structure."""
    uuids = []
    pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
    text = json.dumps(obj) if not isinstance(obj, str) else obj
    uuids.extend(pattern.findall(text))
    return list(set(uuids))


# ── Core Analysis ─────────────────────────────────────────────────────────────

def analyze_har(har_path: str, verbose: bool = True) -> dict:
    print(f"\nAnalyzing: {har_path}")
    with open(har_path, encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    entries = data.get("log", {}).get("entries", [])
    print(f"  Total entries: {len(entries)}")

    # Collection
    rpc_methods: dict[str, dict] = {}  # rpcid -> {description, calls, req_schema, resp_schema}
    generate_calls: list[dict] = []
    all_uuids: set[str] = set()
    all_headers: dict[str, set] = defaultdict(set)
    query_params: dict[str, set] = defaultdict(set)
    session_tokens: dict[str, str] = {}
    static_assets: list[str] = []
    cookie_state: dict[str, str] = {}
    build_labels: set[str] = set()
    source_uuids: set[str] = set()
    notebook_uuids: set[str] = set()

    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "GET")
        status = resp.get("status", 0)
        body_raw = req.get("postData", {}).get("text", "") if req.get("postData") else ""
        resp_text = resp.get("content", {}).get("text", "") or ""

        # Collect request headers
        for hdr in req.get("headers", []):
            n, v = hdr.get("name", ""), hdr.get("value", "")
            all_headers[n].add(v[:200])
            # Session tokens
            if n.lower() == "cookie":
                for part in v.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, _, cv = part.partition("=")
                        cookie_state[k.strip()] = cv.strip()[:80]

        # Extract query params from API URLs
        if "LabsTailwind" in url and "?" in url:
            qs = urllib.parse.parse_qs(url.split("?")[1])
            for k, vals in qs.items():
                for v in vals:
                    query_params[k].add(v[:120])
                    if k == "bl":
                        build_labels.add(v)
                    elif k == "f.sid":
                        session_tokens["f.sid"] = v

        # Extract all UUIDs from full URL
        all_uuids.update(extract_uuids(url))

        # Static assets
        if method == "GET" and ("/_/static/" in url or "gstatic.com" in url):
            static_assets.append(url.split("?")[0])
            continue

        if method != "POST":
            continue

        # ── batchexecute ─────────────────────────────────────────────────────
        if "batchexecute" in url:
            qs = urllib.parse.parse_qs(url.split("?")[1] if "?" in url else "")
            rpcid = qs.get("rpcids", ["?"])[0]
            source_path = qs.get("source-path", [""])[0]
            bl = qs.get("bl", [""])[0]
            if bl:
                build_labels.add(bl)

            # Notebook UUID from source-path
            nb_match = re.search(r"/notebook/([0-9a-f-]{36})", source_path)
            if nb_match:
                notebook_uuids.add(nb_match.group(1))

            req_data = decode_freq(body_raw)
            resp_chunks = parse_wrb_response(resp_text)

            # Extract UUIDs from request
            req_uuids = extract_uuids(req_data)
            all_uuids.update(req_uuids)

            # Classify this rpcid
            if rpcid not in rpc_methods:
                rpc_methods[rpcid] = {
                    "calls": 0,
                    "req_examples": [],
                    "resp_examples": [],
                    "uuids_seen": set(),
                }
            rpc_methods[rpcid]["calls"] += 1
            rpc_methods[rpcid]["uuids_seen"].update(req_uuids)
            if len(rpc_methods[rpcid]["req_examples"]) < 2:
                rpc_methods[rpcid]["req_examples"].append(req_data)
            if len(rpc_methods[rpcid]["resp_examples"]) < 2:
                for chunk in resp_chunks:
                    if chunk.get("rpcid") == rpcid:
                        rpc_methods[rpcid]["resp_examples"].append(chunk.get("data"))

        # ── GenerateFreeFormStreamed ──────────────────────────────────────────
        elif "GenerateFreeForm" in url or "OrchestrationService" in url:
            req_data = decode_freq(body_raw)
            req_uuids = extract_uuids(req_data)
            source_uuids.update(req_uuids)
            all_uuids.update(req_uuids)

            # Parse streaming response
            thinking_text = ""
            citations = []
            m = re.search(r'"(\*\*[^"]{20,})', resp_text)
            if m:
                thinking_text = m.group(1)[:300]
            uuid_matches = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", resp_text)
            citations = list(set(uuid_matches))

            generate_calls.append({
                "url": url,
                "status": status,
                "sources_sent": req_uuids,
                "thinking_preview": thinking_text,
                "citation_uuids": citations[:10],
                "resp_len": len(resp_text),
            })

    # ── Output ────────────────────────────────────────────────────────────────
    result = {
        "har_file": har_path,
        "total_entries": len(entries),
        "build_labels": sorted(build_labels),
        "session_tokens": session_tokens,
        "cookie_state": cookie_state,
        "notebook_uuids": sorted(notebook_uuids),
        "source_uuids": sorted(source_uuids),
        "all_uuids": sorted(all_uuids),
        "rpc_methods": {k: {**v, "uuids_seen": sorted(v["uuids_seen"])} for k, v in rpc_methods.items()},
        "generate_calls": generate_calls,
        "query_params": {k: sorted(v) for k, v in query_params.items()},
        "unique_headers": sorted(all_headers.keys()),
        "static_assets": sorted(set(static_assets)),
    }

    if verbose:
        _print_report(result)

    return result


def _print_report(r: dict) -> None:
    sep = "=" * 70

    print(f"\n{sep}")
    print("BUILD INFO")
    print(sep)
    for bl in r["build_labels"]:
        print(f"  build_label: {bl}")
    for k, v in r["session_tokens"].items():
        print(f"  {k}: {v}")

    print(f"\n{sep}")
    print("SESSION COOKIES")
    print(sep)
    for k, v in sorted(r["cookie_state"].items()):
        print(f"  {k} = {v[:60]}{'...' if len(v) > 60 else ''}")

    print(f"\n{sep}")
    print(f"NOTEBOOKS ({len(r['notebook_uuids'])})")
    print(sep)
    for nb in r["notebook_uuids"]:
        print(f"  {nb}")

    print(f"\n{sep}")
    print(f"SOURCE UUIDs IN GENERATE CALLS ({len(r['source_uuids'])})")
    print(sep)
    for s in r["source_uuids"][:30]:
        print(f"  {s}")

    print(f"\n{sep}")
    print(f"BATCHEXECUTE RPC METHODS ({len(r['rpc_methods'])})")
    print(sep)
    for rpcid, info in sorted(r["rpc_methods"].items(), key=lambda x: -x[1]["calls"]):
        print(f"\n  [{rpcid}] — {info['calls']} calls")
        if info["req_examples"]:
            req = info["req_examples"][0]
            req_str = json.dumps(req, separators=(",", ":"))[:400] if not isinstance(req, str) else req[:400]
            print(f"    REQ: {req_str}")
        if info["resp_examples"]:
            resp = info["resp_examples"][0]
            resp_str = json.dumps(resp, separators=(",", ":"))[:400] if not isinstance(resp, str) else resp[:400]
            print(f"    RESP: {resp_str}")

    print(f"\n{sep}")
    print(f"GENERATE CALLS ({len(r['generate_calls'])})")
    print(sep)
    for i, call in enumerate(r["generate_calls"]):
        print(f"\n  Call {i+1}: {call['resp_len']} bytes response")
        print(f"    Sources sent: {len(call['sources_sent'])}")
        print(f"    Thinking: {call['thinking_preview'][:200]}")
        print(f"    Citations: {call['citation_uuids'][:5]}")

    print(f"\n{sep}")
    print("API QUERY PARAMETERS")
    print(sep)
    for k, vals in sorted(r["query_params"].items()):
        print(f"  {k}:")
        for v in sorted(vals)[:3]:
            print(f"    {v[:100]}")

    print(f"\n{sep}")
    print(f"STATIC ASSETS ({len(r['static_assets'])})")
    print(sep)
    for a in r["static_assets"][:40]:
        print(f"  {a.replace('https://notebooklm.google.com', '')}")

    print(f"\n{sep}")
    print(f"ALL UNIQUE UUIDs ({len(r['all_uuids'])})")
    print(sep)
    for u in r["all_uuids"][:50]:
        print(f"  {u}")


def analyze_all_hars(har_dir: str = "data/har_files") -> dict:
    """Analyze all HAR files and merge results."""
    har_files = list(Path(har_dir).glob("*.har"))
    print(f"Found {len(har_files)} HAR files")

    all_rpc: dict[str, dict] = {}
    all_notebooks: set[str] = set()
    all_sources: set[str] = set()
    all_builds: set[str] = set()

    for har in sorted(har_files):
        try:
            r = analyze_har(str(har), verbose=False)
            all_notebooks.update(r["notebook_uuids"])
            all_sources.update(r["source_uuids"])
            all_builds.update(r["build_labels"])
            for rpcid, info in r["rpc_methods"].items():
                if rpcid not in all_rpc:
                    all_rpc[rpcid] = info
                else:
                    all_rpc[rpcid]["calls"] += info["calls"]
                    all_rpc[rpcid]["req_examples"] += info["req_examples"]
                    all_rpc[rpcid]["resp_examples"] += info["resp_examples"]
        except Exception as e:
            print(f"  Error: {har.name}: {e}")

    print(f"\n{'='*70}")
    print("MERGED RESULTS ACROSS ALL HARs")
    print(f"{'='*70}")
    print(f"  Build labels: {sorted(all_builds)}")
    print(f"  Notebooks: {sorted(all_notebooks)}")
    print(f"  Source UUIDs: {len(all_sources)}")
    print(f"\n  ALL RPC METHODS ({len(all_rpc)}):")
    for rpcid, info in sorted(all_rpc.items(), key=lambda x: -x[1]["calls"]):
        print(f"    [{rpcid}] {info['calls']} calls")
        if info["req_examples"]:
            print(f"      REQ: {json.dumps(info['req_examples'][0], separators=(',',':'))[:300]}")
        if info["resp_examples"] and info["resp_examples"][0]:
            print(f"      RESP: {json.dumps(info['resp_examples'][0], separators=(',',':'))[:300]}")

    return {"rpc_methods": all_rpc, "notebooks": sorted(all_notebooks), "sources": sorted(all_sources)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        analyze_har(sys.argv[1])
    else:
        analyze_all_hars()
