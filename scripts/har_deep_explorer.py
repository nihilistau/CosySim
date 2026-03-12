"""Deep HAR exploration script for Google Workspace API surface mining.

Parses all HAR files in C:/Files/Models/New-Hars/ to extract:
- All API endpoints (REST, gRPC, batchexecute)
- API keys, tokens, auth patterns
- Client-side gating parameters (tier markers, feature flags)
- Model identifiers and selection parameters
- Rate limits, quotas, permission levels
- Bypass patterns (client-side-only restrictions)
- Payload structures and controllable parameters
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

HAR_DIR = r"C:\Files\Models\New-Hars"

# Known Google service categories
SERVICE_CATEGORIES = {
    "appsgenaiserver-pa": "workspace_gemini",
    "appsgrowthpromo-pa": "workspace_promo",
    "espresso-pa": "workspace_espresso",
    "peoplestack-pa": "workspace_people",
    "ogads-pa": "workspace_ogads",
    "workspaceui-pa": "workspace_ui",
    "addons-pa": "workspace_addons",
    "waa-pa": "workspace_analytics",
    "docs.google.com": "google_docs",
    "sheets.google.com": "google_sheets",
    "drive.google.com": "google_drive",
    "cloudsearch.clients6.google.com": "cloud_search",
    "gemini.google.com": "gemini",
    "notebooklm.google.com": "notebooklm",
    "colab.research.google.com": "colab",
    "script.google.com": "apps_script",
    "www.appsheet.com": "appsheet",
    "generativelanguage.googleapis.com": "gemini_api",
    "aistudio.google.com": "ai_studio",
    "alkali-pa.clients6.google.com": "gemini_alkali",
    "content-push.googleapis.com": "content_push",
    "play.google.com": "play_store",
    "myactivity.google.com": "my_activity",
    "ogs.google.com": "ogs",
    "lh3.googleusercontent.com": "image_proxy",
    "ssl.gstatic.com": "static_assets",
}


def categorize_host(host: str) -> str:
    """Categorize a host into a service group."""
    if not host:
        return "unknown"
    for pattern, category in SERVICE_CATEGORIES.items():
        if pattern in host:
            return category
    if "clients6.google.com" in host:
        prefix = host.split(".")[0]
        return f"workspace_{prefix.replace('-pa', '')}"
    if "googleapis.com" in host:
        return "google_api"
    if "google.com" in host:
        return "google_other"
    return "external"


def extract_api_keys(url: str, headers: List[Dict]) -> List[Dict[str, str]]:
    """Extract API keys from URL query params and headers."""
    keys = []
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    for param in ["key", "apikey", "api_key", "token", "access_token"]:
        if param in qs:
            for val in qs[param]:
                keys.append({"source": f"query:{param}", "value": val})

    for h in headers:
        name = h.get("name", "").lower()
        value = h.get("value", "")
        if name == "x-goog-api-key":
            keys.append({"source": "header:x-goog-api-key", "value": value})
        elif name == "authorization" and value.startswith("Bearer "):
            keys.append({"source": "header:authorization", "value": value[:50] + "..."})
        elif name == "x-goog-authuser":
            keys.append({"source": "header:x-goog-authuser", "value": value})

    return keys


def extract_batchexecute_details(post_data: str) -> List[Dict[str, Any]]:
    """Parse batchexecute f.req payload to extract rpcids and parameters."""
    results = []
    if not post_data:
        return results

    # Extract f.req parameter
    freq_match = re.search(r"f\.req=([^&]+)", post_data)
    if not freq_match:
        return results

    from urllib.parse import unquote
    freq_data = unquote(freq_match.group(1))

    # Find all rpcid invocations: [["rpcid",...
    rpcid_pattern = re.compile(r'\[\["([A-Za-z0-9]+)"')
    for match in rpcid_pattern.finditer(freq_data):
        rpcid = match.group(1)
        # Try to extract the payload section after the rpcid
        start = match.start()
        # Find the payload (next quoted JSON string after rpcid)
        payload_match = re.search(r'"(\[.{0,500}?)"', freq_data[start + len(rpcid) + 5:start + 2000])
        payload_preview = ""
        if payload_match:
            payload_preview = payload_match.group(1)[:200]

        results.append({
            "rpcid": rpcid,
            "payload_preview": payload_preview,
        })

    return results


def extract_protobuf_json_params(body: str) -> Dict[str, Any]:
    """Extract parameters from application/json+protobuf payloads."""
    params = {}
    if not body:
        return params

    try:
        data = json.loads(body)
        if isinstance(data, list):
            params["structure"] = "array"
            params["top_level_length"] = len(data)
            params["element_types"] = [type(x).__name__ for x in data[:10]]

            # Look for tier markers, model selectors, etc.
            flat = json.dumps(data)
            if "[2]" in flat:
                params["has_tier_marker_2"] = True
            if "[1]" in flat:
                params["has_tier_marker_1"] = True

            # Detect nested arrays that might be operation codes
            for i, item in enumerate(data[:5]):
                if isinstance(item, list) and len(item) > 0:
                    if isinstance(item[0], int):
                        params[f"position_{i}_int_code"] = item[0]
                    elif isinstance(item[0], str) and len(item[0]) < 50:
                        params[f"position_{i}_string"] = item[0]

        elif isinstance(data, dict):
            params["structure"] = "object"
            params["keys"] = list(data.keys())[:20]
    except (json.JSONDecodeError, TypeError):
        pass

    return params


def extract_grpc_method(url: str) -> Optional[str]:
    """Extract gRPC method name from URL."""
    match = re.search(r'/\$rpc/([^?]+)', url)
    if match:
        return match.group(1)
    return None


def analyze_response_headers(headers: List[Dict]) -> Dict[str, str]:
    """Extract interesting response headers (gating, limits, etc.)."""
    interesting = {}
    interesting_names = {
        "x-quota-remaining", "x-ratelimit-remaining", "x-ratelimit-limit",
        "x-ratelimit-reset", "x-goog-quota-user", "x-goog-fieldmask",
        "x-content-type-options", "x-frame-options",
        "alt-svc", "x-gfe-request-trace", "server-timing",
        "x-goog-safety-encoding", "x-goog-safety-content-type",
        "x-goog-upload-protocol", "x-goog-upload-status",
        "x-goog-upload-url", "x-goog-upload-chunk-granularity",
    }
    for h in headers:
        name = h.get("name", "").lower()
        if name in interesting_names or name.startswith("x-goog-") or name.startswith("x-ratelimit"):
            interesting[name] = h.get("value", "")[:100]
    return interesting


def parse_har_deep(filepath: str) -> Dict[str, Any]:
    """Deep parse a single HAR file."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    entries = data.get("log", {}).get("entries", [])

    # Aggregators
    service_endpoints = defaultdict(list)
    api_keys_found = []
    auth_patterns = set()
    grpc_methods = []
    batchexecute_ops = []
    protobuf_endpoints = []
    content_types = defaultdict(int)
    status_codes = defaultdict(int)
    hosts = defaultdict(int)
    response_headers_interesting = defaultdict(dict)
    cookie_names = set()
    feature_flags = set()
    model_refs = set()

    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        method = req.get("method", "GET")
        req_headers = req.get("headers", [])
        resp_headers = resp.get("headers", [])
        post_data_obj = req.get("postData", {})
        post_body = post_data_obj.get("text", "")
        mime_type = post_data_obj.get("mimeType", "")
        resp_body = resp.get("content", {}).get("text", "")

        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path or "/"
        qs = parse_qs(parsed.query)

        # Skip static assets
        if any(ext in path for ext in [".js", ".css", ".png", ".jpg", ".gif", ".svg", ".ico", ".woff", ".ttf", ".map", ".woff2"]):
            continue
        if host.endswith("gstatic.com") or host.endswith("googleusercontent.com"):
            continue

        hosts[host] += 1
        status_codes[str(resp.get("status", 0))] += 1
        if mime_type:
            content_types[mime_type.split(";")[0]] += 1

        category = categorize_host(host)

        # API keys
        keys = extract_api_keys(url, req_headers)
        api_keys_found.extend(keys)

        # Auth patterns
        for h in req_headers:
            name = h.get("name", "").lower()
            value = h.get("value", "")
            if name == "authorization":
                auth_patterns.add(value[:40] + "..." if len(value) > 40 else value)
            if name == "cookie":
                for part in value.split(";"):
                    cname = part.strip().split("=")[0]
                    if cname:
                        cookie_names.add(cname)

        # gRPC methods
        grpc_method = extract_grpc_method(url)
        if grpc_method:
            grpc_methods.append({
                "host": host,
                "method": grpc_method,
                "http_method": method,
                "status": resp.get("status", 0),
                "category": category,
                "request_content_type": mime_type,
            })

        # batchexecute
        if "batchexecute" in url:
            ops = extract_batchexecute_details(post_body)
            for op in ops:
                op["host"] = host
                op["url"] = url[:200]
                op["category"] = category
            batchexecute_ops.extend(ops)

        # Protobuf-JSON endpoints
        if "json+protobuf" in mime_type or "json+protobuf" in str(resp.get("content", {}).get("mimeType", "")):
            params = extract_protobuf_json_params(post_body)
            protobuf_endpoints.append({
                "host": host,
                "path": path,
                "method": method,
                "params": params,
                "category": category,
                "status": resp.get("status", 0),
                "request_size": len(post_body) if post_body else 0,
                "response_size": len(resp_body) if resp_body else 0,
            })

        # Response headers
        interesting = analyze_response_headers(resp_headers)
        if interesting:
            response_headers_interesting[f"{method} {host}{path[:60]}"] = interesting

        # Feature flags / model references in responses
        if resp_body and len(resp_body) < 100000:
            # Look for model IDs
            model_patterns = re.findall(r'"(gemini[^"]*(?:pro|flash|ultra|nano|exp)[^"]*)"', resp_body, re.IGNORECASE)
            model_refs.update(model_patterns[:5])

            # Look for feature flags
            flag_patterns = re.findall(r'"(enable[A-Z][^"]{3,50})"', resp_body)
            feature_flags.update(flag_patterns[:10])
            flag_patterns2 = re.findall(r'"(is[A-Z][^"]{3,50})"', resp_body)
            feature_flags.update(flag_patterns2[:10])

        # General endpoint tracking
        endpoint_key = f"{method} {path}"
        service_endpoints[category].append({
            "method": method,
            "host": host,
            "path": path[:150],
            "status": resp.get("status", 0),
            "content_type": mime_type.split(";")[0] if mime_type else "",
            "has_body": bool(post_body),
            "query_params": list(qs.keys())[:10],
        })

    # Deduplicate API keys
    unique_keys = {}
    for k in api_keys_found:
        key = f"{k['source']}:{k['value'][:30]}"
        if key not in unique_keys:
            unique_keys[key] = k

    # Deduplicate gRPC methods
    unique_grpc = {}
    for g in grpc_methods:
        key = f"{g['host']}/{g['method']}"
        unique_grpc[key] = g

    # Deduplicate batchexecute
    unique_batch = {}
    for b in batchexecute_ops:
        if b["rpcid"] not in unique_batch:
            unique_batch[b["rpcid"]] = b

    # Deduplicate endpoints per category
    unique_endpoints_per_category = {}
    for cat, eps in service_endpoints.items():
        seen = set()
        unique = []
        for ep in eps:
            key = f"{ep['method']} {ep['host']}{ep['path']}"
            if key not in seen:
                seen.add(key)
                unique.append(ep)
        unique_endpoints_per_category[cat] = unique

    return {
        "filename": os.path.basename(filepath),
        "size_mb": round(os.path.getsize(filepath) / (1024 * 1024), 1),
        "total_entries": len(entries),
        "hosts": dict(sorted(hosts.items(), key=lambda x: -x[1])),
        "status_codes": dict(status_codes),
        "content_types": dict(sorted(content_types.items(), key=lambda x: -x[1])),
        "api_keys": list(unique_keys.values()),
        "auth_patterns": sorted(auth_patterns),
        "cookie_names": sorted(cookie_names),
        "grpc_methods": list(unique_grpc.values()),
        "batchexecute_ops": list(unique_batch.values()),
        "protobuf_endpoints": protobuf_endpoints,
        "service_endpoints": unique_endpoints_per_category,
        "response_headers": dict(response_headers_interesting),
        "feature_flags": sorted(feature_flags),
        "model_refs": sorted(model_refs),
    }


def print_report(results: List[Dict[str, Any]]) -> None:
    """Print comprehensive exploration report."""
    print("\n" + "=" * 100)
    print("COMPREHENSIVE HAR DEEP EXPLORATION REPORT")
    print("=" * 100)

    # Global aggregates
    all_api_keys = {}
    all_grpc = {}
    all_batch = {}
    all_protobuf = []
    all_flags = set()
    all_models = set()
    all_cookies = set()
    all_endpoints_by_service = defaultdict(list)

    for result in results:
        print(f"\n{'─' * 100}")
        print(f"FILE: {result['filename']} ({result['size_mb']} MB, {result['total_entries']} entries)")
        print(f"{'─' * 100}")

        print(f"\n  Status codes: {result['status_codes']}")
        print(f"  Content types: {dict(list(result['content_types'].items())[:8])}")

        print(f"\n  ┌─ API Keys ({len(result['api_keys'])})")
        for k in result["api_keys"]:
            print(f"  │  {k['source']}: {k['value'][:60]}")
            all_api_keys[k["value"][:30]] = k

        print(f"\n  ┌─ Auth Patterns ({len(result['auth_patterns'])})")
        for a in result["auth_patterns"][:5]:
            print(f"  │  {a}")

        print(f"\n  ┌─ gRPC Methods ({len(result['grpc_methods'])})")
        for g in result["grpc_methods"]:
            print(f"  │  [{g['category']}] {g['host']}/{g['method']} (HTTP {g['status']})")
            all_grpc[f"{g['host']}/{g['method']}"] = g

        print(f"\n  ┌─ batchexecute rpcids ({len(result['batchexecute_ops'])})")
        for b in result["batchexecute_ops"]:
            print(f"  │  [{b['category']}] {b['rpcid']}: {b['payload_preview'][:80]}")
            all_batch[b["rpcid"]] = b

        print(f"\n  ┌─ Protobuf-JSON Endpoints ({len(result['protobuf_endpoints'])})")
        for p in result["protobuf_endpoints"][:15]:
            print(f"  │  [{p['category']}] {p['method']} {p['host']}{p['path'][:60]} "
                  f"(status={p['status']}, req={p['request_size']}b, resp={p['response_size']}b)")
            if p.get("params"):
                for pk, pv in list(p["params"].items())[:5]:
                    print(f"  │    {pk}: {pv}")
            all_protobuf.append(p)

        print(f"\n  ┌─ Service Endpoints by Category")
        for cat, eps in sorted(result["service_endpoints"].items()):
            if cat in ("google_other", "external", "google_api", "static_assets", "image_proxy"):
                continue
            print(f"  │  {cat} ({len(eps)} unique):")
            for ep in eps[:8]:
                qs = f" ?{','.join(ep['query_params'][:3])}" if ep.get("query_params") else ""
                print(f"  │    {ep['method']} {ep['host']}{ep['path'][:70]}{qs}")
            all_endpoints_by_service[cat].extend(eps)

        if result["feature_flags"]:
            print(f"\n  ┌─ Feature Flags ({len(result['feature_flags'])})")
            for ff in result["feature_flags"][:15]:
                print(f"  │  {ff}")
            all_flags.update(result["feature_flags"])

        if result["model_refs"]:
            print(f"\n  ┌─ Model References ({len(result['model_refs'])})")
            for mr in result["model_refs"]:
                print(f"  │  {mr}")
            all_models.update(result["model_refs"])

        all_cookies.update(result.get("cookie_names", []))

    # Global summary
    print(f"\n{'=' * 100}")
    print("GLOBAL SUMMARY ACROSS ALL HAR FILES")
    print(f"{'=' * 100}")

    print(f"\n  Total unique API keys: {len(all_api_keys)}")
    for k in all_api_keys.values():
        print(f"    {k['source']}: {k['value'][:60]}")

    print(f"\n  Total unique gRPC methods: {len(all_grpc)}")
    by_cat = defaultdict(list)
    for g in all_grpc.values():
        by_cat[g["category"]].append(g)
    for cat, methods in sorted(by_cat.items()):
        print(f"    {cat}:")
        for g in methods:
            print(f"      {g['method']}")

    print(f"\n  Total unique batchexecute rpcids: {len(all_batch)}")
    for rpcid, b in sorted(all_batch.items()):
        print(f"    {rpcid} [{b['category']}]")

    print(f"\n  Total feature flags: {len(all_flags)}")
    for ff in sorted(all_flags)[:30]:
        print(f"    {ff}")

    print(f"\n  Total model references: {len(all_models)}")
    for mr in sorted(all_models):
        print(f"    {mr}")

    print(f"\n  Auth cookies ({len(all_cookies)}):")
    auth_cookies = [c for c in all_cookies if any(x in c.upper() for x in ["SID", "AUTH", "SAPISD", "HSID", "SSID", "APISID", "NID", "CONSENT", "LOGIN"])]
    for c in sorted(auth_cookies):
        print(f"    {c}")

    print(f"\n  Service endpoint counts:")
    for cat, eps in sorted(all_endpoints_by_service.items()):
        seen = set()
        unique = [e for e in eps if f"{e['method']}{e['path']}" not in seen and not seen.add(f"{e['method']}{e['path']}")]
        print(f"    {cat}: {len(unique)} unique endpoints")

    print(f"\n{'=' * 100}")
    print("YAML-READY PARAMETER CATALOG")
    print(f"{'=' * 100}")

    # Extract controllable parameters from protobuf endpoints
    print("\n  Protobuf-JSON payload patterns:")
    for p in all_protobuf:
        if p.get("params") and p["params"].get("structure") == "array":
            print(f"\n    {p['method']} {p['host']}{p['path'][:60]}:")
            print(f"      top_level_length: {p['params'].get('top_level_length')}")
            print(f"      element_types: {p['params'].get('element_types')}")
            for pk, pv in p["params"].items():
                if pk.startswith("position_"):
                    print(f"      {pk}: {pv}")
            if p["params"].get("has_tier_marker_2"):
                print("      ⚠ TIER MARKER [2] DETECTED (Pro tier)")
            if p["params"].get("has_tier_marker_1"):
                print("      ⚠ TIER MARKER [1] DETECTED (Free tier)")


def main() -> None:
    """Run deep HAR exploration."""
    har_files = [
        os.path.join(HAR_DIR, f)
        for f in os.listdir(HAR_DIR)
        if f.endswith(".har")
    ]

    if not har_files:
        print(f"No HAR files found in {HAR_DIR}")
        sys.exit(1)

    print(f"Found {len(har_files)} HAR files:")
    for f in har_files:
        size = os.path.getsize(f) / (1024 * 1024)
        print(f"  {os.path.basename(f)}: {size:.1f} MB")

    results = []
    for filepath in har_files:
        print(f"\nParsing {os.path.basename(filepath)}...")
        try:
            result = parse_har_deep(filepath)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print_report(results)

    # Save full results as JSON for further processing
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "har_deep_exploration.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Serialize (skip non-serializable)
    serializable = []
    for r in results:
        s = {}
        for k, v in r.items():
            try:
                json.dumps(v)
                s[k] = v
            except (TypeError, ValueError):
                s[k] = str(v)
        serializable.append(s)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {output_path}")


if __name__ == "__main__":
    main()
