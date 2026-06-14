"""Protocol Monitor JSON Importer — parse Chrome DevTools Protocol Monitor exports.

Chrome DevTools has a Protocol Monitor (Settings > Experiments > Protocol Monitor)
that captures all CDP messages. The "Save" button exports them as JSON.

This importer extracts:
- Network.requestWillBeSent / Network.responseReceived events
- batchexecute request/response payloads (rpcids + args)
- gRPC-web method calls (LabsTailwindOrchestrationService)
- Cookies, session tokens, and auth headers

Usage:
    from scripts.argus.importers.protocol_monitor import import_protocol_monitor_json

    results = import_protocol_monitor_json("path/to/protocol_monitor_export.json")
    print(f"Found {len(results['rpcids'])} rpcids")
    print(f"Found {len(results['grpc_methods'])} gRPC methods")

The watchfolder (har_watchfolder.py) auto-detects .json files in data/hars/
and routes them through this importer.

v1.50.2 [2026-03-23]
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote

logger = logging.getLogger(__name__)


# ──── Protocol Monitor JSON Format ───────────────────────────────────
#
# The export is an array of CDP messages, each with:
#   {
#     "id": <int>,              // message ID (requests only)
#     "method": "Network.requestWillBeSent",
#     "params": { ... },        // event params
#     "result": { ... },        // response result (responses only)
#     "sessionId": "...",       // target session
#     "timestamp": <float>      // when captured
#   }
#
# We care about:
#   Network.requestWillBeSent  → extract URL, method, headers, postData
#   Network.responseReceived   → extract status, headers
#   Network.loadingFinished    → signal that response body is available
#   Fetch.requestPaused        → intercepted requests (if Fetch domain enabled)


def import_protocol_monitor_json(
    json_path: str | Path,
) -> Dict[str, Any]:
    """Import a Protocol Monitor JSON export and extract NLM/Gemini API calls.

    Args:
        json_path: Path to the exported .json file

    Returns:
        Dict with:
            rpcids: Dict[str, Dict] — rpcid → {trigger, payload, url}
            grpc_methods: Dict[str, Dict] — method → {trigger, url}
            cookies: Dict[str, str] — extracted cookie name/value pairs
            session: Dict[str, str] — bl, f_sid, at tokens if found
            raw_requests: List[Dict] — all extracted API requests
            stats: Dict — import statistics
    """
    path = Path(json_path)
    if not path.exists():
        return {"error": f"File not found: {path}"}

    raw = path.read_text(encoding="utf-8", errors="replace")

    # Protocol Monitor exports can be either:
    # 1. An array of CDP messages: [{"method": "...", "params": {...}}, ...]
    # 2. A single object with a "messages" key: {"messages": [...]}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    if isinstance(data, dict) and "messages" in data:
        messages = data["messages"]
    elif isinstance(data, list):
        messages = data
    else:
        return {"error": "Unexpected JSON structure — expected array or {messages: [...]}"}

    logger.info(
        "[ProtocolMonitor] Importing %s (%d messages)",
        path.name, len(messages),
    )

    # ──── Extract network requests ───────────────────────────────
    rpcids: Dict[str, Dict[str, Any]] = {}
    grpc_methods: Dict[str, Dict[str, Any]] = {}
    cookies: Dict[str, str] = {}
    session: Dict[str, str] = {}
    raw_requests: List[Dict[str, Any]] = []

    for msg in messages:
        method = msg.get("method", "")
        params = msg.get("params", {})

        # ── Network.requestWillBeSent ────────────────────────────
        if method == "Network.requestWillBeSent":
            request = params.get("request", {})
            url = request.get("url", "")

            # Skip non-Google API calls
            if "LabsTailwind" not in url and "batchexecute" not in url:
                continue

            post_data = request.get("postData", "")
            headers = request.get("headers", {})

            entry = {
                "url": url,
                "method": request.get("method", "GET"),
                "requestId": params.get("requestId"),
                "timestamp": params.get("wallTime", 0),
                "headers": headers,
            }

            # Extract cookies from headers
            cookie_header = headers.get("cookie", headers.get("Cookie", ""))
            if cookie_header:
                for pair in cookie_header.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        cookies[k.strip()] = v.strip()

            # Extract rpcids from batchexecute URLs
            rpcid_match = re.search(r"rpcids=([^&]+)", url)
            if rpcid_match:
                for rid in rpcid_match.group(1).split(","):
                    rid = rid.strip()
                    if rid and rid not in rpcids:
                        rpcids[rid] = {
                            "url": url[:200],
                            "timestamp": entry["timestamp"],
                        }

                # Parse f.req from POST body for payload details
                if post_data:
                    _extract_freqs(post_data, rpcids)

                # Extract session tokens from URL
                fsid_match = re.search(r"f\.sid=([^&]+)", url)
                if fsid_match:
                    session["f_sid"] = unquote(fsid_match.group(1))

                bl_match = re.search(r"bl=([^&]+)", url)
                if bl_match:
                    session["bl"] = unquote(bl_match.group(1))

            # Extract gRPC methods
            grpc_match = re.search(
                r"OrchestrationService/(\w+)", url
            )
            if grpc_match:
                method_name = grpc_match.group(1)
                if method_name not in grpc_methods:
                    grpc_methods[method_name] = {
                        "url": url[:200],
                        "timestamp": entry["timestamp"],
                    }

            # Extract 'at' token from POST body
            if post_data and "at=" in post_data:
                at_match = re.search(r"at=([^&]+)", post_data)
                if at_match:
                    session["at"] = unquote(at_match.group(1))

            raw_requests.append(entry)

        # ── Network.responseReceived ─────────────────────────────
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            url = response.get("url", "")

            if "LabsTailwind" not in url and "batchexecute" not in url:
                continue

            status = response.get("status", 0)

            # Find matching request and annotate with status
            req_id = params.get("requestId")
            for req in raw_requests:
                if req.get("requestId") == req_id:
                    req["status"] = status
                    break

    # ──── Stats ──────────────────────────────────────────────────
    stats = {
        "total_messages": len(messages),
        "api_requests": len(raw_requests),
        "unique_rpcids": len(rpcids),
        "unique_grpc_methods": len(grpc_methods),
        "cookies_found": len(cookies),
        "session_tokens": list(session.keys()),
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    logger.info(
        "[ProtocolMonitor] Extracted %d rpcids, %d gRPC methods, %d cookies from %s",
        len(rpcids), len(grpc_methods), len(cookies), path.name,
    )

    return {
        "rpcids": rpcids,
        "grpc_methods": grpc_methods,
        "cookies": cookies,
        "session": session,
        "raw_requests": raw_requests,
        "stats": stats,
    }


def _extract_freqs(
    post_data: str,
    rpcids: Dict[str, Dict[str, Any]],
) -> None:
    """Parse f.req from URL-encoded POST body and extract rpcid payloads.

    The f.req value is a triple-nested JSON array:
        [[[rpcid, payload_json, null, "generic"], ...]]

    Each inner array is one RPC call.
    """
    try:
        # URL-decode the POST body
        params = parse_qs(post_data)
        freq_raw = params.get("f.req", [""])[0]
        if not freq_raw:
            return

        freq = json.loads(freq_raw)

        # Walk the triple-nested structure
        if isinstance(freq, list):
            for batch in freq:
                if isinstance(batch, list):
                    for call in batch:
                        if isinstance(call, list) and len(call) >= 2:
                            rid = call[0]
                            payload_str = call[1] if len(call) > 1 else ""
                            if isinstance(rid, str) and rid in rpcids:
                                rpcids[rid]["payload"] = payload_str
                                # Try to parse the payload JSON
                                try:
                                    rpcids[rid]["payload_parsed"] = json.loads(payload_str)
                                except (json.JSONDecodeError, TypeError):
                                    pass
    except Exception:
        pass  # Malformed POST data — skip


def merge_into_registry(
    results: Dict[str, Any],
    registry_path: Optional[Path] = None,
) -> Dict[str, int]:
    """Merge imported results into the ARGUS endpoint registry.

    Args:
        results: Output from import_protocol_monitor_json()
        registry_path: Path to registry.json (default: data/argus/registry.json)

    Returns:
        Dict with counts: {new_rpcids, new_grpc_methods, updated_rpcids}
    """
    try:
        from scripts.argus.discovery.endpoint_registry import get_registry
        registry = get_registry()
    except ImportError:
        logger.warning("[ProtocolMonitor] ARGUS registry not available")
        return {"new_rpcids": 0, "new_grpc_methods": 0, "updated_rpcids": 0}

    new_rpc = 0
    new_grpc = 0
    updated = 0

    for rid, info in results.get("rpcids", {}).items():
        was_new = registry.register_rpcid(
            rid,
            target="nlm",
            context=f"protocol_monitor import",
        )
        if was_new:
            new_rpc += 1
        else:
            updated += 1

    for method, info in results.get("grpc_methods", {}).items():
        was_new = registry.register_method(
            method,
            service="LabsTailwindOrchestrationService",
            context="protocol_monitor import",
        )
        if was_new:
            new_grpc += 1

    registry.save()

    counts = {
        "new_rpcids": new_rpc,
        "new_grpc_methods": new_grpc,
        "updated_rpcids": updated,
    }
    logger.info("[ProtocolMonitor] Merged: %s", counts)
    return counts


# ──── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m scripts.argus.importers.protocol_monitor <path.json>")
        sys.exit(1)

    path = sys.argv[1]
    results = import_protocol_monitor_json(path)

    if "error" in results:
        print(f"Error: {results['error']}")
        sys.exit(1)

    print(f"Messages:     {results['stats']['total_messages']}")
    print(f"API requests: {results['stats']['api_requests']}")
    print(f"RPC IDs:      {results['stats']['unique_rpcids']}")
    print(f"gRPC methods: {results['stats']['unique_grpc_methods']}")
    print(f"Cookies:      {results['stats']['cookies_found']}")
    print(f"Session:      {results['stats']['session_tokens']}")

    print("\nRPC IDs:")
    for rid, info in sorted(results["rpcids"].items()):
        payload_preview = str(info.get("payload_parsed", ""))[:60]
        print(f"  {rid:12s}  {payload_preview}")

    print("\ngRPC Methods:")
    for method in sorted(results["grpc_methods"]):
        print(f"  {method}")

    if results["session"]:
        print("\nSession tokens:")
        for k, v in results["session"].items():
            print(f"  {k}: {str(v)[:40]}...")
