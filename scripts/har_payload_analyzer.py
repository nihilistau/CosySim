"""Deep HAR payload analyzer — extracts operation codes, model IDs, controllable params."""
from __future__ import annotations
import json
import os
import sys
from collections import defaultdict
from urllib.parse import urlparse, parse_qs

HAR_DIR = r"C:\Files\Models\New-Hars"


def truncate(obj, max_str=80, depth=0):
    if depth > 6:
        return "..."
    if isinstance(obj, str):
        return obj[:max_str] + "..." if len(obj) > max_str else obj
    if isinstance(obj, list):
        return [truncate(x, max_str, depth + 1) for x in obj[:10]]
    if isinstance(obj, dict):
        return {k: truncate(v, max_str, depth + 1) for k, v in list(obj.items())[:8]}
    return obj


def analyze_hars():
    files = [
        os.path.join(HAR_DIR, "docs.-google.com-sheets-gemini.har"),
        os.path.join(HAR_DIR, "docs.-google.com-sheets-gemini2.har"),
    ]

    api_key_services = defaultdict(set)
    stream_payloads = []
    settings_payloads = []
    gems_payloads = []
    quota_payloads = []
    update_settings_payloads = []
    drive_ops = []
    sheets_ops = []
    prewarm_payloads = []
    promo_payloads = []
    consent_payloads = []
    survey_payloads = []
    cloud_search_payloads = []
    batch_payloads = []

    for fpath in files:
        if not os.path.exists(fpath):
            print(f"SKIP: {fpath}")
            continue
        fname = os.path.basename(fpath)
        print(f"Loading {fname}...")
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        for entry in data.get("log", {}).get("entries", []):
            req = entry.get("request", {})
            resp = entry.get("response", {})
            url = req.get("url", "")
            parsed = urlparse(url)
            host = parsed.hostname or ""
            path = parsed.path or "/"
            qs = parse_qs(parsed.query)
            method = req.get("method", "GET")
            post_body = req.get("postData", {}).get("text", "")
            resp_body = resp.get("content", {}).get("text", "")
            status = resp.get("status", 0)

            # Skip OPTIONS
            if method == "OPTIONS":
                continue

            # Map API keys to services
            for h in req.get("headers", []):
                if h["name"].lower() == "x-goog-api-key":
                    api_key_services[h["value"]].add(f"{host}:{path[:50]}")
            for v in qs.get("key", []):
                api_key_services[v].add(f"{host}:{path[:50]}")

            # streamGenerate
            if "streamGenerate" in path and post_body:
                try:
                    stream_payloads.append({
                        "file": fname,
                        "payload": json.loads(post_body),
                        "response_preview": resp_body[:2000] if resp_body else None,
                        "payload_size": len(post_body),
                        "response_size": len(resp_body) if resp_body else 0,
                        "api_key": qs.get("key", [""])[0][:30],
                        "status": status,
                    })
                except json.JSONDecodeError:
                    pass

            # getSettings
            if "getSettings" in path and method == "POST":
                try:
                    settings_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # listGems
            if "listGems" in path and method == "POST":
                try:
                    gems_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # quotaSummary
            if "quotaSummary" in path and method == "POST":
                try:
                    quota_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # updateUserSettings
            if "updateUserSettings" in path and method == "POST":
                try:
                    update_settings_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # prewarm
            if "prewarm" in path and method == "POST":
                try:
                    prewarm_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # FetchRecommendation(s)
            if "FetchRecommendation" in path and method == "POST":
                try:
                    promo_payloads.append({
                        "file": fname,
                        "path": path,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # udpConsent
            if "udpConsent" in path and method == "POST":
                try:
                    consent_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # Cloud Search
            if "cloudsearch" in host and method == "POST":
                try:
                    cloud_search_payloads.append({
                        "file": fname,
                        "request": json.loads(post_body) if post_body else None,
                        "response_size": len(resp_body) if resp_body else 0,
                        "response": json.loads(resp_body) if resp_body else None,
                    })
                except:
                    pass

            # workspaceui batch
            if host and "workspaceui" in host and "batch" in path and method == "POST":
                batch_payloads.append({
                    "file": fname,
                    "content_type": req.get("postData", {}).get("mimeType", ""),
                    "body_size": len(post_body),
                    "response_size": len(resp_body) if resp_body else 0,
                })

            # Drive v2internal
            if "drive/v2internal" in path:
                drive_ops.append({
                    "method": method,
                    "path": path,
                    "query_params": {k: v[0][:80] for k, v in qs.items()},
                    "file": fname,
                    "status": status,
                })

            # Sheets-specific (columnsmith, externaldata, save, prefs)
            if any(x in path for x in ["columnsmith", "externaldata", "save", "prefs", "/exter"]):
                if method == "POST":
                    sheets_ops.append({
                        "method": method,
                        "path": path[:120],
                        "query_params": list(qs.keys()),
                        "body_preview": post_body[:500] if post_body else "",
                        "body_size": len(post_body),
                        "file": fname,
                    })

    # ───── REPORT ─────

    print("\n" + "=" * 90)
    print("API KEY → SERVICE MAPPING")
    print("=" * 90)
    for key, services in sorted(api_key_services.items()):
        print(f"\n  Key: {key}")
        for s in sorted(services):
            print(f"    → {s}")

    print("\n" + "=" * 90)
    print(f"STREAM GENERATE — {len(stream_payloads)} payloads")
    print("=" * 90)
    seen_ops = set()
    for i, sp in enumerate(stream_payloads):
        payload = sp["payload"]
        if not isinstance(payload, list) or len(payload) < 2:
            continue
        op_part = payload[0]
        ctx_part = payload[1]
        op_code = op_part[0] if isinstance(op_part, list) and op_part else "?"
        ctx_code = ctx_part[0] if isinstance(ctx_part, list) and ctx_part else "?"
        key = f"op={op_code},ctx={ctx_code}"
        if key in seen_ops:
            continue
        seen_ops.add(key)
        print(f"\n  ─── Operation {op_code} / Context {ctx_code} ({sp['file']}) ───")
        print(f"  Payload: {sp['payload_size']}b → Response: {sp['response_size']}b")
        print(f"  Full payload (truncated):")
        print(json.dumps(truncate(payload), indent=2)[:2000])

    print("\n" + "=" * 90)
    print(f"GET SETTINGS — {len(settings_payloads)} payloads")
    print("=" * 90)
    for sp in settings_payloads[:4]:
        print(f"\n  File: {sp['file']}")
        print(f"  Request:  {json.dumps(sp['request'])[:300]}")
        print(f"  Response: {json.dumps(sp['response'])[:800]}")

    print("\n" + "=" * 90)
    print(f"LIST GEMS — {len(gems_payloads)} payloads")
    print("=" * 90)
    for sp in gems_payloads[:2]:
        print(f"\n  File: {sp['file']}")
        print(f"  Request:  {json.dumps(truncate(sp['request']))[:500]}")
        print(f"  Response: {json.dumps(truncate(sp['response']), indent=2)[:3000]}")

    print("\n" + "=" * 90)
    print(f"QUOTA SUMMARY — {len(quota_payloads)} payloads")
    print("=" * 90)
    for sp in quota_payloads[:4]:
        print(f"\n  File: {sp['file']}")
        print(f"  Request:  {json.dumps(sp['request'])[:300]}")
        print(f"  Response: {json.dumps(sp['response'], indent=2)[:1000]}")

    print("\n" + "=" * 90)
    print(f"UPDATE SETTINGS — {len(update_settings_payloads)} payloads")
    print("=" * 90)
    for sp in update_settings_payloads:
        print(f"\n  File: {sp['file']}")
        print(f"  Request:  {json.dumps(sp['request'])[:500]}")
        print(f"  Response: {json.dumps(sp['response'])[:500]}")

    print("\n" + "=" * 90)
    print(f"PREWARM — {len(prewarm_payloads)} payloads")
    print("=" * 90)
    for sp in prewarm_payloads[:3]:
        print(f"\n  File: {sp['file']}")
        print(f"  Request:  {json.dumps(truncate(sp['request']))[:500]}")
        print(f"  Response: {json.dumps(truncate(sp['response']))[:500]}")

    print("\n" + "=" * 90)
    print(f"CLOUD SEARCH — {len(cloud_search_payloads)} payloads")
    print("=" * 90)
    for sp in cloud_search_payloads[:3]:
        print(f"\n  File: {sp['file']}")
        print(f"  Request:  {json.dumps(truncate(sp['request']), indent=2)[:1500]}")

    print("\n" + "=" * 90)
    print(f"DRIVE V2INTERNAL — {len(drive_ops)} operations")
    print("=" * 90)
    for op in drive_ops:
        print(f"\n  {op['method']} {op['path'][:80]}")
        for k, v in op["query_params"].items():
            print(f"    {k}={v}")

    print("\n" + "=" * 90)
    print(f"SHEETS OPS — {len(sheets_ops)} operations")
    print("=" * 90)
    for op in sheets_ops[:6]:
        print(f"\n  {op['method']} {op['path']}")
        print(f"    params: {op['query_params']}")
        if op["body_preview"]:
            print(f"    body ({op['body_size']}b): {op['body_preview'][:200]}")

    # Save full analysis
    out = {
        "api_key_services": {k: list(v) for k, v in api_key_services.items()},
        "stream_payloads": [{**s, "payload": truncate(s["payload"])} for s in stream_payloads],
        "settings": settings_payloads,
        "gems": [{**g, "response": truncate(g["response"])} for g in gems_payloads],
        "quota": quota_payloads,
        "update_settings": update_settings_payloads,
        "prewarm": prewarm_payloads,
        "cloud_search": [{**c, "response": truncate(c.get("response"))} for c in cloud_search_payloads],
        "drive_ops": drive_ops,
        "sheets_ops": sheets_ops,
    }
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "har_payload_analysis.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nFull analysis saved to {out_path}")


if __name__ == "__main__":
    analyze_hars()
