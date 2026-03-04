"""Deep HAR analysis - extract all API calls, request/response patterns, and protocol details."""
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

HAR_PATH = "data/har_files/notebooklm.google.com-complete-sense-new.har"


def decode_freqreq(text: str) -> list[str]:
    """Decode f.req URL-encoded parameter."""
    try:
        decoded = urllib.parse.unquote(text)
        return decoded[:2000]
    except Exception:
        return text[:500]


def analyze_har(har_path: str) -> None:
    with open(har_path, encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    entries = data.get("log", {}).get("entries", [])
    print(f"Total entries: {len(entries)}")

    # Categorize all entries
    post_apis: dict[str, Any] = {}
    all_headers_seen: set[str] = set()
    grpc_methods: list[dict] = []
    batchexecute_calls: list[dict] = []

    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "")
        status = resp.get("status", 0)
        req_hdrs = {h["name"]: h["value"] for h in req.get("headers", [])}
        resp_hdrs = {h["name"]: h["value"] for h in resp.get("headers", [])}

        for h in req_hdrs:
            all_headers_seen.add(h)

        if method != "POST":
            continue

        base_url = url.split("?")[0]
        query_str = url.split("?")[1] if "?" in url else ""
        body = req.get("postData", {})
        body_text = body.get("text", "") if body else ""

        if "GenerateFreeForm" in url or "Orchestration" in url:
            grpc_methods.append({
                "url": url,
                "status": status,
                "body": body_text[:3000],
                "req_hdrs": req_hdrs,
                "resp_hdrs": resp_hdrs,
                "resp_text": resp.get("content", {}).get("text", "")[:3000],
            })
        elif "batchexecute" in url:
            batchexecute_calls.append({
                "url": url,
                "status": status,
                "body": body_text[:2000],
                "req_hdrs": req_hdrs,
                "resp_text": resp.get("content", {}).get("text", "")[:2000],
            })
        elif any(x in url for x in ["LabsTailwind", "tailwind", "rpc", "/api/"]):
            if base_url not in post_apis:
                post_apis[base_url] = []
            post_apis[base_url].append({
                "status": status,
                "body": body_text[:500],
                "resp": resp.get("content", {}).get("text", "")[:500],
            })

    # ── GenerateFreeFormStreamed calls ──────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"GenerateFreeFormStreamed / LabsTailwindOrchestrationService calls ({len(grpc_methods)})")
    print(f"{'='*70}")

    for i, call in enumerate(grpc_methods):
        print(f"\n--- Call {i+1} ---")
        print(f"URL: {call['url'][:120]}")
        print(f"Status: {call['status']}")
        print("Request headers:")
        for k, v in call["req_hdrs"].items():
            if k.lower() not in ("cookie", "user-agent", "accept-language"):
                print(f"  {k}: {v[:100]}")
        body = call["body"]
        print(f"Body ({len(body)} chars):")
        # Try to URL-decode f.req param
        if "f.req=" in body:
            freqpart = body.split("f.req=")[1].split("&")[0]
            decoded = urllib.parse.unquote(freqpart)
            print(f"  f.req (decoded): {decoded[:1500]}")
        else:
            print(f"  {body[:800]}")
        resp_text = call["resp_text"]
        print(f"Response ({len(resp_text)} chars):")
        print(f"  {resp_text[:800]}")

    # ── batchexecute calls ──────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"batchexecute calls ({len(batchexecute_calls)})")
    print(f"{'='*70}")

    for i, call in enumerate(batchexecute_calls[:5]):
        print(f"\n--- batchexecute {i+1} ---")
        print(f"URL: {call['url'][:150]}")
        body = call["body"]
        # Decode f.req in batchexecute
        if "f.req=" in body:
            freqpart = body.split("f.req=")[1].split("&")[0]
            decoded = urllib.parse.unquote(freqpart)
            print(f"  f.req: {decoded[:1000]}")
        else:
            print(f"  body: {body[:400]}")
        print(f"  resp: {call['resp_text'][:400]}")

    # ── Other POST APIs ─────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"Other POST endpoints ({len(post_apis)})")
    print(f"{'='*70}")
    for url, calls in sorted(post_apis.items()):
        print(f"\n{url} ({len(calls)} calls)")
        c = calls[0]
        print(f"  status={c['status']}")
        if c["body"]:
            print(f"  body: {c['body'][:200]}")
        if c["resp"]:
            print(f"  resp: {c['resp'][:200]}")

    # ── Custom request headers ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("All unique request headers seen")
    print(f"{'='*70}")
    google_hdrs = sorted(h for h in all_headers_seen if "goog" in h.lower() or "x-" in h.lower())
    for h in google_hdrs:
        print(f"  {h}")

    # ── Extract f.req patterns for understanding NLM protocol ──────────────
    print(f"\n{'='*70}")
    print("Extracting NLM protocol patterns")
    print(f"{'='*70}")

    # Look at query params on API calls
    for entry in entries:
        req = entry.get("request", {})
        url = req.get("url", "")
        if "LabsTailwind" in url and "?" in url:
            qs = urllib.parse.parse_qs(url.split("?")[1])
            print(f"\nURL query params for: {url.split('?')[0][-60:]}")
            for k, v in qs.items():
                print(f"  {k} = {v[0][:80]}")
            break


if __name__ == "__main__":
    analyze_har(HAR_PATH)
