"""
ARGUS Protocol Monitor Parser — Extract network requests from Chrome DevTools Protocol logs.

Chrome DevTools Protocol Monitor captures raw CDP events including Network.requestWillBeSent
which contains full POST bodies that the HAR exporter sometimes omits (e.g. batchexecute).

Usage:
    python -m scripts.argus.tools.protocol_monitor_parser --file PATH.json [--target gas] [--report]
    python -m scripts.argus.tools.protocol_monitor_parser --file PATH.json --extract-bodies
    python -m scripts.argus.tools.protocol_monitor_parser --file PATH.json --rpcid OOPYjd
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Known batchexecute service host patterns
BATCH_EXECUTE_HOSTS = [
    "script.google.com",
    "notebooklm.google.com",
    "myaccount.google.com",
    "gemini.google.com",
    "aistudio.google.com",
]

GAS_RPCIDS = [
    "OOPYjd", "OQOG2e", "AJ6bre", "pEig0e", "ivJzse", "toGAmc",
    "LuHlxe", "UvGaob", "KKLVD", "qqL5ld", "zzomTc", "yFXSbd",
    "NFMk7c", "GXx9jd", "AvwHP",
]


def load_events(path: str) -> list[dict]:
    """Load CDP events from a Protocol Monitor JSON file."""
    p = Path(path)
    logger.info(f"Loading Protocol Monitor: {p} ({p.stat().st_size / 1024:.1f} KB)")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    # May be a list directly or wrapped
    if isinstance(data, list):
        return data
    return data.get("events", data.get("messages", []))


def extract_network_events(events: list[dict]) -> dict[str, list[dict]]:
    """Separate events by CDP method type."""
    categorized: dict[str, list[dict]] = {}
    for ev in events:
        method = ev.get("method", "")
        if method.startswith("Network."):
            categorized.setdefault(method, []).append(ev)
    return categorized


def get_params(event: dict) -> dict:
    """Extract params from a CDP event (result or params field)."""
    return event.get("params", event.get("result", {}))


def extract_batchexecute_requests(
    events: list[dict],
    target_host: Optional[str] = None,
) -> list[dict]:
    """Find all batchexecute POST requests with their bodies.

    Returns:
        List of dicts with url, post_data, rpcids_found, decoded_requests
    """
    results = []
    for ev in events:
        if ev.get("method") != "Network.requestWillBeSent":
            continue
        params = get_params(ev)
        request = params.get("request", {})
        url = request.get("url", "")
        if "batchexecute" not in url:
            continue
        if target_host and target_host not in url:
            continue

        post_data = request.get("postData", "")
        entry = {
            "url": url,
            "method": request.get("method", ""),
            "post_data": post_data,
            "request_id": params.get("requestId", ""),
            "timestamp": params.get("timestamp", 0),
            "rpcids_found": [],
            "decoded_requests": [],
        }

        # Scan for known rpcids in URL + body
        combined = url + post_data
        for rpcid in GAS_RPCIDS:
            if rpcid in combined:
                entry["rpcids_found"].append(rpcid)

        # Scan for ANY rpcid-like pattern in the f.req body
        if post_data:
            decoded = _decode_freq(post_data)
            if decoded:
                entry["decoded_requests"] = decoded

        results.append(entry)

    return results


def _decode_freq(post_data: str) -> list[dict]:
    """Attempt to decode f.req batchexecute POST body.

    Format: f.req=%5B%5B%5B%22rpcid%22%2C%22payload%22%2Cnull%2C%221%22%5D%5D%5D

    Uses unquote_plus because batchexecute bodies are application/x-www-form-urlencoded
    where spaces are encoded as '+'.
    """
    try:
        # URL-decode — use unquote_plus so '+' is decoded back to space
        decoded = urllib.parse.unquote_plus(post_data)
        # Strip f.req= prefix if present
        if decoded.startswith("f.req="):
            decoded = decoded[6:]
        # Strip any trailing &key=value pairs from other form fields
        if "&" in decoded:
            decoded = decoded[: decoded.index("&")]
        # Parse JSON
        outer = json.loads(decoded)
        if not isinstance(outer, list):
            return []
        results = []
        for item in outer:
            if isinstance(item, list) and len(item) >= 2:
                rpcid = item[0] if isinstance(item[0], str) else None
                payload_str = item[1] if isinstance(item[1], str) else None
                result = {"rpcid": rpcid, "raw_payload": payload_str}
                if payload_str:
                    try:
                        result["payload"] = json.loads(payload_str)
                    except Exception:
                        result["payload"] = payload_str
                results.append(result)
        return results
    except Exception:
        return []


def extract_response_bodies(events: list[dict]) -> dict[str, str]:
    """Map requestId -> response body from Network.loadingFinished + getResponseBody.

    Note: CDP Protocol Monitor may not include response bodies unless DevTools was
    capturing them explicitly. Returns what's available.
    """
    bodies = {}
    for ev in events:
        if ev.get("method") == "Network.dataReceived":
            params = get_params(ev)
            req_id = params.get("requestId", "")
            body = params.get("encodedDataLength", "")  # usually just length
            if body:
                bodies[req_id] = str(body)
    return bodies


def find_all_rpcids_in_events(events: list[dict]) -> dict[str, int]:
    """Scan all events for any known rpcid occurrence, count frequency."""
    counts: dict[str, int] = {}
    text = json.dumps(events)
    all_rpcids = GAS_RPCIDS + [
        # NLM rpcids
        "UIVaxd", "Uu9RRc", "RuoToe", "W5Pqvd",
        # Gemini rpcids
        "XqA3Ie", "aCbzBe", "jnPYZd",
    ]
    for rpcid in all_rpcids:
        count = text.count(rpcid)
        if count > 0:
            counts[rpcid] = count
    return counts


def extract_script_sources(events: list[dict]) -> list[dict]:
    """Find Debugger.scriptParsed events (JS source file info)."""
    results = []
    for ev in events:
        if ev.get("method") == "Debugger.scriptParsed":
            params = get_params(ev)
            url = params.get("url", "")
            if "script.google.com" in url or "gas" in url.lower():
                results.append({
                    "url": url,
                    "script_id": params.get("scriptId", ""),
                    "length": params.get("length", 0),
                })
    return results


def print_report(
    events: list[dict],
    batch_requests: list[dict],
    rpcid_counts: dict[str, int],
) -> None:
    """Print analysis report."""
    network_events = extract_network_events(events)
    script_sources = extract_script_sources(events)

    print("\n" + "=" * 70)
    print("ARGUS Protocol Monitor Parser — Analysis Report")
    print("=" * 70)

    print(f"\nTotal CDP events: {len(events)}")
    print(f"\nNetwork event types:")
    for method, evs in sorted(network_events.items()):
        print(f"  {method}: {len(evs)}")

    if batch_requests:
        print(f"\nBatchexecute requests found: {len(batch_requests)}")
        for req in batch_requests:
            print(f"\n  URL: {req['url'][:100]}")
            print(f"  rpcids: {req['rpcids_found']}")
            if req["decoded_requests"]:
                for dr in req["decoded_requests"]:
                    print(f"  decoded: rpcid={dr.get('rpcid')} payload_len={len(str(dr.get('payload','')))}") 
            elif req["post_data"]:
                print(f"  post_data: {req['post_data'][:200]}")
    else:
        print("\nNo batchexecute requests found in this Protocol Monitor file.")
        print("(CDP Protocol Monitor may not capture POST bodies unless Network interception was enabled)")

    if rpcid_counts:
        print(f"\nrpcid occurrences in events:")
        for rpcid, count in sorted(rpcid_counts.items(), key=lambda x: -x[1]):
            print(f"  {rpcid}: {count}")

    if script_sources:
        print(f"\nGAS script sources ({len(script_sources)}):")
        for s in script_sources[:10]:
            print(f"  {s['url'][:80]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ARGUS Protocol Monitor Parser")
    parser.add_argument("--file", required=True, help="Path to Protocol Monitor JSON file")
    parser.add_argument("--target", default=None, help="Filter by host (e.g. script.google.com)")
    parser.add_argument("--report", action="store_true", help="Print full report")
    parser.add_argument("--extract-bodies", action="store_true", help="Extract batchexecute bodies")
    parser.add_argument("--rpcid", help="Find events mentioning specific rpcid")
    parser.add_argument("--event-types", action="store_true", help="List CDP event types")
    parser.add_argument("--output-json", help="Write results to JSON file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    events = load_events(args.file)
    batch_requests = extract_batchexecute_requests(events, target_host=args.target)
    rpcid_counts = find_all_rpcids_in_events(events)

    if args.event_types:
        types: dict[str, int] = {}
        for ev in events:
            m = ev.get("method", "unknown")
            types[m] = types.get(m, 0) + 1
        print("CDP event types:")
        for t, c in sorted(types.items(), key=lambda x: -x[1])[:30]:
            print(f"  {t}: {c}")
        return

    if args.rpcid:
        text = json.dumps(events)
        if args.rpcid in text:
            print(f"rpcid '{args.rpcid}' found {text.count(args.rpcid)} times in events")
            # Find relevant events
            for i, ev in enumerate(events):
                if args.rpcid in json.dumps(ev):
                    print(f"\n  Event {i} ({ev.get('method')}):")
                    print(f"  {json.dumps(ev, indent=2)[:500]}")
        else:
            print(f"rpcid '{args.rpcid}' NOT found in events")
        return

    if args.report or args.extract_bodies:
        print_report(events, batch_requests, rpcid_counts)

    if args.output_json:
        output = {
            "event_count": len(events),
            "batch_requests": batch_requests,
            "rpcid_counts": rpcid_counts,
        }
        with open(args.output_json, "w") as f:
            json.dump(output, f, indent=2)
        logger.info(f"Written to {args.output_json}")

    if not args.report and not args.extract_bodies and not args.output_json:
        # Default: quick summary
        print(f"Events: {len(events)}, Batchexecute: {len(batch_requests)}")
        if rpcid_counts:
            print(f"rpcids found: {rpcid_counts}")


if __name__ == "__main__":
    main()
